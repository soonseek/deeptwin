from copy import deepcopy
from hashlib import sha256
import sqlite3
import threading
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from app.domain.schema_exports import domain_schema
from app.domain.schemas import ImmutableRecord
from app.domain.refs import DomainContractError, EntityRef, canonical_json
from app.domain.store import BlobRef, CorruptRecord, DomainStore, ImmutableConflict
from app.extensions.provider_semantic_contracts import (ProviderSemanticError,
    allowed_terminal, canonical_provider_error, canonical_provider_result,
    instruction_projection_digest, semantic_record_id)
from app.extensions.provider_semantic_records import (
    admit_operation, load_cancel_intent, load_operation, load_semantic_record, load_terminal,
    seal_cancel_intent, seal_cancel_operation_and_intent, seal_capability, seal_catalog,
    seal_catalog_traversal,
    seal_effect, seal_frozen, seal_operation, seal_output, seal_page, seal_response,
    seal_terminal, seal_usage,
)
from app.storage import Store
from app.tests.test_provider_semantic_codec import dense_page
from app.tests.support.provider_semantic_harness import (canonical_provider_config,
                                                         canonical_provider_request)
from app.workers.provider_semantic_codec import (CatalogTraversal, advance_catalog,
                                                  encode_text_body, parse_model_page)


STAMP = "2026-09-20T00:00:00.000000Z"


def opened(tmp_path):
    domain = DomainStore(Store(tmp_path / "vault"))
    roots = domain.initialize_vault()
    return domain, roots


def record(domain, roots, kind, *, content=None, parents=()):
    item = ImmutableRecord.create(kind=kind, id=str(uuid4()), version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=parents, purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content=content or {"schema_version": "task47-fixture-v1"})
    domain.put(item)
    return item.ref


def request_value(roots, config, operation, input_value, **kwargs):
    return canonical_provider_request(operation, input_value, identity={
        "qualification_ref": config.as_dict(), "binding_revision_ref": config.as_dict(),
        "purpose_ref": config.as_dict(), "actor_ref": roots.actor.as_dict(),
    }, **kwargs)


def frozen_content(domain, roots):
    blob = domain.put_blob(b"hello", purpose="operational")
    artifact = record(domain, roots, "artifact", content={"schema_version": "task47-input-v1",
                      "blob_ref": blob.as_dict(), "media_type": "text/plain"})
    refs = {kind: record(domain, roots, kind) for kind in
            ("work_revision", "environment", "model_catalog", "runtime_profile", "budget_policy",
             "run_consent", "execution_envelope", "validation_report")}
    projection = {"profile_id": "execution-model-step", "system_artifact_ref": None}
    return {"schema_version": "provider-semantic-frozen-v1", "turn": {
        "profile": "execution-model-step", "work_ref": refs["work_revision"].as_dict(),
        "environment_ref": refs["environment"].as_dict(), "node_id": "writer",
        "execution_id": str(uuid4()), "attempt_index": 0, "provider": "claude_api",
        "account_id": "account", "catalog_ref": refs["model_catalog"].as_dict(),
        "model_id": "model-1", "effort": None,
        "instruction_profile_digest": instruction_projection_digest(projection),
        "inputs": [{"type": "text", "ref": artifact.as_dict(), "marker": None, "omissions": []}],
        "granted_tools": [], "output_schema_id": None,
        "runtime_profile_ref": refs["runtime_profile"].as_dict(), "deadline_seconds": 30,
        "budget_ref": refs["budget_policy"].as_dict(), "consent_ref": refs["run_consent"].as_dict()},
        "execution_envelope_ref": refs["execution_envelope"].as_dict(),
        "purpose_ref": refs["validation_report"].as_dict(), "grant_refs": [],
        "artifact_input_bindings": [{"artifact_ref": artifact.as_dict(), "selector_ref": None,
                                      "declared_media_type": "text/plain", "role": "model_input"}],
        "messages": [{"role": "user", "input_ordinals": [0]}], "max_output_tokens": 8,
        "instruction_projection": projection}


def test_records_rehash_and_acyclic_refs(tmp_path):
    domain, roots = opened(tmp_path)
    frozen = seal_frozen(domain, command_id=str(uuid4()), content=frozen_content(domain, roots),
                         created_at_utc=STAMP)
    config = record(domain, roots, "validation_report")
    request_id = str(uuid4())
    frozen_record = domain.get(frozen).body["content"]
    request = request_value(roots, config, "model_step", {"frozen_turn_ref": frozen.as_dict(),
        "model_id": frozen_record["turn"]["model_id"], "effort": None,
        "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None}, request_id=request_id,
        artifact_inputs=frozen_record["artifact_input_bindings"])
    operation = seal_operation(domain, config_ref=config, request=request, core_boot_id=str(uuid4()),
                               reservation_ref=None, created_at_utc=STAMP)
    response = seal_response(domain, operation_ref=operation, exchange_id=str(uuid4()),
        proposal_sha256=sha256(encode_text_body(frozen_record, (b"hello",))).hexdigest(),
        status=200, raw=b"raw", phase="terminal_observed",
        observed_model="model-1", stop_reason="end_turn", cancel_observed=False, created_at_utc=STAMP)
    usage = seal_usage(domain, operation_ref=operation, response_ref=response,
        usage={name: {"state": "absent", "value": None} for name in
               ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
                "cache_creation", "output_tokens_details", "server_tool_use", "inference_geo", "service_tier")}
              | {"unknown_categories": [], "cache_zero_basis": "request_omits_cache_and_tools",
                 "currency_cost_known": False}, created_at_utc=STAMP)
    effect = seal_effect(domain, operation_ref=operation, response_ref=response,
        request_sha256=sha256(canonical_json(request)).hexdigest(),
        effect_state="committed", remote_outcome="confirmed",
        created_at_utc=STAMP)
    output = seal_output(domain, operation_ref=operation, ordinal=0, data=b"answer", created_at_utc=STAMP)
    result = canonical_provider_result(request, terminal="succeeded",
        started_at="2026-09-20T00:00:00.000Z", completed_at="2026-09-20T00:00:00.001Z",
        output={"provider_id": "claude_api", "model_id": "model-1",
                "content_block_refs": [output.as_dict()], "tool_proposal_refs": [],
                "usage_report_ref": usage.as_dict(), "provider_response_ref": response.as_dict()},
        artifacts=[{"artifact_ref": output.as_dict(), "role": "model_content",
                    "media_type": "text/plain", "content_digest": sha256(b"answer").hexdigest(),
                    "byte_count": 6, "omissions_ref": None}],
        usage={"input_units": None, "output_units": None, "billed_units": None,
               "unit_name": "tokens", "provider_report_ref": usage.as_dict()},
        effect={"effect_class": "external_irreversible", "effect_state": "committed",
                "effect_receipt_ref": effect.as_dict(), "remote_outcome": "confirmed"})
    for mutate in (
        lambda value: value["output"].update(usage_report_ref=config.as_dict()),
        lambda value: value["usage"].update(provider_report_ref=config.as_dict()),
        lambda value: value["effect"].update(effect_receipt_ref=config.as_dict()),
        lambda value: value["output"].update(provider_response_ref=config.as_dict()),
        lambda value: value["output"].update(content_block_refs=[config.as_dict()]),
    ):
        mismatched = deepcopy(result)
        mutate(mismatched)
        with pytest.raises(ProviderSemanticError, match="terminal result graph"):
            seal_terminal(domain, operation_ref=operation, result=mismatched,
                          response_ref=response, created_at_utc=STAMP)
    terminal = seal_terminal(domain, operation_ref=operation, result=result,
                             response_ref=response, created_at_utc=STAMP)
    assert load_semantic_record(domain, terminal).body["content"]["response_ref"] == response.as_dict()
    request2 = request_value(roots, config, "model_step", deepcopy(request["input"]),
        request_id=str(uuid4()), artifact_inputs=deepcopy(request["artifact_inputs"]))
    operation2 = seal_operation(domain, config_ref=config, request=request2,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    result2 = deepcopy(result)
    result2["request_id"] = request2["request_id"]
    malicious_content = {"schema_version": "provider-semantic-terminal-v1",
        "operation_ref": operation2.as_dict(), "result": result2,
        "response_ref": response.as_dict()}
    malicious_parents = set()
    def collect_refs(value):
        if type(value) is dict:
            if set(value) == {"kind", "id", "version", "sha256"}:
                malicious_parents.add(EntityRef.from_dict(value))
            elif set(value) != {"vault_id", "purpose", "sha256", "size"}:
                for child in value.values():
                    collect_refs(child)
        elif type(value) is list:
            for child in value:
                collect_refs(child)
    collect_refs(malicious_content)
    malicious = ImmutableRecord.create(kind="validation_report",
        id=semantic_record_id(domain.vault_id, "provider-semantic-terminal-v1",
                              request2["request_id"]), version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=tuple(sorted(malicious_parents,
            key=lambda item: canonical_json(item.as_dict()))), purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content=malicious_content)
    domain.put(malicious)
    with pytest.raises(ProviderSemanticError, match="terminal result graph"):
        load_terminal(domain, operation2)
    assert {ref.kind for ref in (response, usage, effect, output, terminal)} == {
        "validation_report", "artifact"}
    with sqlite3.connect(domain.path) as db:
        db.execute("UPDATE domain_records SET body=? WHERE id=?", (b"{}", response.id))
    with pytest.raises(CorruptRecord):
        load_semantic_record(domain, terminal)


@pytest.mark.parametrize("broken", ["missing_usage", "proposal", "phase", "status",
                                     "model", "stop"])
def test_succeeded_model_requires_selected_profile_response_and_usage_joins(tmp_path, broken):
    domain, roots = opened(tmp_path)
    frozen = seal_frozen(domain, command_id=str(uuid4()), content=frozen_content(domain, roots),
                         created_at_utc=STAMP)
    frozen_value = domain.get(frozen).body["content"]
    config = record(domain, roots, "validation_report")
    request = request_value(roots, config, "model_step", {"frozen_turn_ref": frozen.as_dict(),
        "model_id": "model-1", "effort": None, "requested_modalities": ["text"],
        "tool_definition_refs": [], "response_schema_ref": None},
        artifact_inputs=frozen_value["artifact_input_bindings"])
    operation = seal_operation(domain, config_ref=config, request=request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    response_values = {"proposal_sha256": sha256(
        encode_text_body(frozen_value, (b"hello",))).hexdigest(), "status": 200,
        "phase": "terminal_observed", "observed_model": "model-1", "stop_reason": "end_turn"}
    if broken == "proposal": response_values["proposal_sha256"] = "0" * 64
    elif broken == "phase": response_values["phase"] = "may_have_sent"
    elif broken == "status": response_values["status"] = 503
    elif broken == "model": response_values["observed_model"] = "model-2"
    elif broken == "stop": response_values["stop_reason"] = "max_tokens"
    response = seal_response(domain, operation_ref=operation, exchange_id=str(uuid4()),
        raw=b"bounded upstream bytes", cancel_observed=False, failure_class=None,
        created_at_utc=STAMP, **response_values)
    usage = seal_usage(domain, operation_ref=operation, response_ref=response,
        usage={name: {"state": "absent", "value": None} for name in
               ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                "cache_read_input_tokens", "cache_creation", "output_tokens_details",
                "server_tool_use", "inference_geo", "service_tier")}
              | {"unknown_categories": [], "cache_zero_basis": "request_omits_cache_and_tools",
                 "currency_cost_known": False}, created_at_utc=STAMP)
    effect = seal_effect(domain, operation_ref=operation, response_ref=response,
        request_sha256=sha256(canonical_json(request)).hexdigest(),
        effect_state="committed", remote_outcome="confirmed", created_at_utc=STAMP)
    usage_ref = None if broken == "missing_usage" else usage.as_dict()
    result = canonical_provider_result(request, terminal="succeeded",
        started_at="2026-09-20T00:00:00.000Z", completed_at="2026-09-20T00:00:00.001Z",
        output={"provider_id": "claude_api", "model_id": "model-1",
                "content_block_refs": [], "tool_proposal_refs": [],
                "usage_report_ref": usage_ref, "provider_response_ref": response.as_dict()},
        usage={"input_units": None, "output_units": None, "billed_units": None,
               "unit_name": "tokens", "provider_report_ref": usage_ref},
        effect={"effect_class": "external_irreversible", "effect_state": "committed",
                "effect_receipt_ref": effect.as_dict(), "remote_outcome": "confirmed"})
    with pytest.raises(ProviderSemanticError, match="terminal result graph"):
        seal_terminal(domain, operation_ref=operation, result=result,
                      response_ref=response, created_at_utc=STAMP)


def test_status_terminal_ref_must_belong_to_exact_target_operation(tmp_path):
    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    target_request = request_value(roots, config, "capabilities", {})
    target = seal_operation(domain, config_ref=config, request=target_request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    other_request = request_value(roots, config, "capabilities", {})
    other = seal_operation(domain, config_ref=config, request=other_request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    other_result = canonical_provider_result(other_request, terminal="succeeded",
        started_at="2026-09-20T00:00:00.000Z", completed_at="2026-09-20T00:00:00.001Z",
        output={"modalities": ["text"],
        "tool_calling": False, "usage_reporting": True, "cancellation": True})
    other_terminal = seal_terminal(domain, operation_ref=other, result=other_result,
                                   response_ref=None, created_at_utc=STAMP)
    status_request = request_value(roots, config, "status", {"operation_ref": target.as_dict()})
    status_operation = seal_operation(domain, config_ref=config, request=status_request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    status_result = canonical_provider_result(status_request, terminal="succeeded",
        started_at="2026-09-20T00:00:00.000Z", completed_at="2026-09-20T00:00:00.001Z",
        output={"observed_state": "succeeded", "observed_at":
        "2026-09-20T00:00:00.001Z", "terminal_result_ref": other_terminal.as_dict()})
    with pytest.raises(ProviderSemanticError, match="terminal result graph"):
        seal_terminal(domain, operation_ref=status_operation, result=status_result,
                      response_ref=None, created_at_utc=STAMP)


def test_durable_response_failure_class_is_required_finite_and_coherent(tmp_path):
    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    request = request_value(roots, config, "catalog", {"catalog_epoch": None})
    operation = seal_operation(domain, config_ref=config, request=request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    response = seal_response(domain, operation_ref=operation, exchange_id=str(uuid4()),
        proposal_sha256="a" * 64, status=None, raw=None, phase="not_sent",
        observed_model=None, stop_reason=None, cancel_observed=False,
        failure_class="permission_denied", created_at_utc=STAMP)
    assert domain.get(response).body["content"]["failure_class"] == "permission_denied"
    portable = Draft202012Validator(domain_schema())
    portable.validate(domain.get(response).as_dict())
    for invalid in (None, "unknown_category"):
        changed = deepcopy(domain.get(response).as_dict())
        if invalid is None:
            changed["body"]["content"].pop("failure_class")
        else:
            changed["body"]["content"]["failure_class"] = invalid
        assert list(portable.iter_errors(changed))
    wrong_error = canonical_provider_error(request, code="dependency_unavailable",
        message_class="dependency", retry_class="human_action_required",
        evidence_ref=response.as_dict())
    wrong_result = canonical_provider_result(request, terminal="failed",
        started_at="2026-09-20T00:00:00.000Z", completed_at="2026-09-20T00:00:00.001Z",
        error=wrong_error)
    with pytest.raises(ProviderSemanticError, match="terminal result graph"):
        seal_terminal(domain, operation_ref=operation, result=wrong_result,
                      response_ref=response, created_at_utc=STAMP)
    missing = deepcopy(domain.get(response).body["content"])
    missing.pop("failure_class")
    with pytest.raises(DomainContractError):
        ImmutableRecord.create(kind="validation_report", id=str(uuid4()), version=1,
            created_at_utc=STAMP, actor_ref=roots.actor, parent_refs=(operation,),
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy, content=missing)
    for category in ("unknown_category", False, 1):
        with pytest.raises((ProviderSemanticError, DomainContractError)):
            seal_response(domain, operation_ref=operation, exchange_id=str(uuid4()),
                proposal_sha256="b" * 64, status=None, raw=None, phase="not_sent",
                observed_model=None, stop_reason=None, cancel_observed=False,
                failure_class=category, created_at_utc=STAMP)
    with pytest.raises((ProviderSemanticError, DomainContractError)):
        seal_response(domain, operation_ref=operation, exchange_id=str(uuid4()),
            proposal_sha256="c" * 64, status=200, raw=b"forbidden", phase="not_sent",
            observed_model=None, stop_reason=None, cancel_observed=False,
            failure_class="integrity_failed", created_at_utc=STAMP)
    with pytest.raises((ProviderSemanticError, DomainContractError)):
        seal_response(domain, operation_ref=operation, exchange_id=str(uuid4()),
            proposal_sha256="d" * 64, status=None, raw=None, phase="not_sent",
            observed_model=None, stop_reason=None, cancel_observed=False,
            failure_class="cancelled", created_at_utc=STAMP)


def test_all_20_operation_terminal_candidates_use_durable_anchors_and_quarantine_artifacts(
        tmp_path):
    """Exercise the provider matrix through actual operation/terminal records, not an enum helper."""
    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    frozen = seal_frozen(domain, command_id=str(uuid4()), content=frozen_content(domain, roots),
                         created_at_utc=STAMP)
    frozen_value = domain.get(frozen).body["content"]
    inputs = {
        "capabilities": {},
        "catalog": {"catalog_epoch": None},
        "model_step": {"frozen_turn_ref": frozen.as_dict(), "model_id": "model-1",
                       "effort": None, "requested_modalities": ["text"],
                       "tool_definition_refs": [], "response_schema_ref": None},
        "status": {"operation_ref": config.as_dict()},
        "cancel": {"operation_ref": config.as_dict(), "reason_class": "user_requested"},
    }
    outputs = {
        "capabilities": {"modalities": ["text"], "tool_calling": False,
                         "usage_reporting": True, "cancellation": True},
        "status": {"observed_state": "running", "observed_at":
                   "2026-09-20T00:00:00.000Z", "terminal_result_ref": None},
        "cancel": {"cancel_state": "accepted", "observed_at":
                   "2026-09-20T00:00:00.000Z"},
    }

    sealed, refused = set(), set()
    quarantined = quarantined_terminal = None
    for operation_name in inputs:
        for terminal_name in ("succeeded", "failed", "cancelled", "unknown"):
            request = request_value(roots, config, operation_name, inputs[operation_name],
                artifact_inputs=(frozen_value["artifact_input_bindings"]
                                 if operation_name == "model_step" else None))
            operation = seal_operation(domain, config_ref=config, request=request,
                core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
            output = outputs.get(operation_name, {})
            response = None
            completed = None if terminal_name == "unknown" else "2026-09-20T00:00:00.001Z"
            error = None
            if terminal_name != "succeeded":
                code, message = {
                    "failed": ("invalid_request", "validation"),
                    "cancelled": ("cancelled", "cancelled"),
                    "unknown": ("external_effect_unknown", "external_outcome"),
                }[terminal_name]
                error = canonical_provider_error(request, code=code, message_class=message,
                                                  retry_class="never")
            if operation_name == "model_step":
                state, remote = {
                    "succeeded": ("committed", "confirmed"),
                    "failed": ("none", "not_applicable"),
                    "cancelled": ("none", "not_applicable"),
                    "unknown": ("unknown", "unknown"),
                }[terminal_name]
                receipt = None
                if terminal_name in {"succeeded", "unknown"}:
                    response = seal_response(domain, operation_ref=operation,
                        exchange_id=str(uuid4()), proposal_sha256=sha256(
                            encode_text_body(frozen_value, (b"hello",))).hexdigest(),
                        status=200 if terminal_name == "succeeded" else None,
                        raw=b"matrix", phase=("terminal_observed" if terminal_name == "succeeded"
                                              else "may_have_sent"),
                        observed_model="model-1" if terminal_name == "succeeded" else None,
                        stop_reason="end_turn" if terminal_name == "succeeded" else None,
                        cancel_observed=False, created_at_utc=STAMP)
                    receipt = seal_effect(domain, operation_ref=operation,
                        response_ref=response,
                        request_sha256=sha256(canonical_json(request)).hexdigest(),
                        effect_state=state, remote_outcome=remote, created_at_utc=STAMP)
                if terminal_name == "succeeded":
                    usage = seal_usage(domain, operation_ref=operation, response_ref=response,
                        usage={name: {"state": "absent", "value": None} for name in
                            ("input_tokens", "output_tokens", "cache_creation_input_tokens",
                             "cache_read_input_tokens", "cache_creation", "output_tokens_details",
                             "server_tool_use", "inference_geo", "service_tier")}
                            | {"unknown_categories": [],
                               "cache_zero_basis": "request_omits_cache_and_tools",
                               "currency_cost_known": False}, created_at_utc=STAMP)
                    output = {"provider_id": "claude_api", "model_id": "model-1",
                        "content_block_refs": [], "tool_proposal_refs": [],
                        "usage_report_ref": usage.as_dict(),
                        "provider_response_ref": response.as_dict()}
                effect = {"effect_class": "external_irreversible", "effect_state": state,
                          "effect_receipt_ref": None if receipt is None else receipt.as_dict(),
                          "remote_outcome": remote}
            else:
                effect = {"effect_class": "none" if operation_name == "cancel" else "read",
                          "effect_state": "none", "effect_receipt_ref": None,
                          "remote_outcome": "not_applicable"}
            if allowed_terminal(operation_name, terminal_name):
                if operation_name == "catalog" and terminal_name == "succeeded":
                    page_ref = seal_page(domain, operation_ref=operation, index=0,
                        after_id=None,
                        raw=b'{"data":[],"first_id":null,"last_id":null,"has_more":false}',
                        first_id=None, last_id=None, has_more=False, model_ids=[],
                        created_at_utc=STAMP)
                    catalog_ref = seal_catalog(domain, operation_ref=operation,
                        connection_ref=config, fetched_at="2026-09-20T00:00:00.000Z",
                        expires_at="2026-09-20T00:01:00.000Z", page_refs=[page_ref],
                        complete=True, models=[], eligible_model_ids=[], excluded=[],
                        created_at_utc=STAMP)
                    output = {"catalog_ref": catalog_ref.as_dict(), "complete": True,
                              "models": []}
                if operation_name == "model_step" and terminal_name == "failed":
                    quarantined = seal_output(domain, operation_ref=operation, ordinal=0,
                        data=b"late private evidence", created_at_utc=STAMP)
                try:
                    result = canonical_provider_result(request, terminal=terminal_name,
                        started_at="2026-09-20T00:00:00.000Z", completed_at=completed,
                        output=output if terminal_name == "succeeded" else {},
                        artifacts=[], effect=effect, error=error)
                    if operation_name == "model_step" and terminal_name == "succeeded":
                        result["usage"]["provider_report_ref"] = usage.as_dict()
                except ProviderSemanticError as exc:
                    raise AssertionError((operation_name, terminal_name)) from exc
                terminal = seal_terminal(domain, operation_ref=operation, result=result,
                                         response_ref=response, created_at_utc=STAMP)
                if quarantined is not None and operation_name == "model_step" \
                        and terminal_name == "failed":
                    quarantined_terminal = terminal
                retained = domain.get(terminal).body["content"]["result"]
                assert retained["terminal"] == terminal_name
                if terminal_name != "succeeded":
                    assert retained["artifacts"] == []
                sealed.add((operation_name, terminal_name))
            else:
                # Start from a valid failed envelope for this exact operation, then exercise the
                # rejected terminal at the real durable sealing boundary.
                candidate = canonical_provider_result(request, terminal="failed",
                    started_at="2026-09-20T00:00:00.000Z",
                    completed_at="2026-09-20T00:00:00.001Z", output={}, artifacts=[],
                    effect=effect, error=canonical_provider_error(request,
                        code="invalid_request", message_class="validation", retry_class="never"))
                candidate["terminal"] = terminal_name
                candidate["completed_at"] = completed
                candidate["error"] = error
                with pytest.raises(ProviderSemanticError):
                    seal_terminal(domain, operation_ref=operation, result=candidate,
                                  response_ref=None, created_at_utc=STAMP)
                assert load_terminal(domain, operation) is None
                refused.add((operation_name, terminal_name))
    assert len(sealed) == 12 and len(refused) == 8
    assert quarantined is not None and quarantined_terminal is not None
    assert quarantined.as_dict() not in domain.get(quarantined_terminal).body[
        "content"]["result"]["artifacts"]


def test_frozen_rehashes_actual_utf8_input_bytes(tmp_path):
    domain, roots = opened(tmp_path)
    content = frozen_content(domain, roots)
    ref = seal_frozen(domain, command_id=str(uuid4()), content=content, created_at_utc=STAMP)
    assert domain.get(ref).body["content"] == content
    bad = deepcopy(content)
    bad["artifact_input_bindings"][0]["artifact_ref"]["sha256"] = "0" * 64
    with pytest.raises(Exception):
        seal_frozen(domain, command_id=str(uuid4()), content=bad, created_at_utc=STAMP)


def test_fresh_read_ids_share_semantic_key_but_same_id_is_immutable(tmp_path):
    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    retained = None
    for operation_name, input_value in (("capabilities", {}), ("catalog", {"catalog_epoch": None}),
            ("status", {"operation_ref": config.as_dict()})):
        first = request_value(roots, config, operation_name, input_value)
        second = deepcopy(first); second["request_id"] = str(uuid4())
        first_ref, replay = admit_operation(domain, config_ref=config, request=first,
            core_boot_id=str(uuid4()), reservation_ref=None,
            semantic_key=first["idempotency_key"], created_at_utc=STAMP)
        second_ref, second_replay = admit_operation(domain, config_ref=config, request=second,
            core_boot_id=str(uuid4()), reservation_ref=None,
            semantic_key=second["idempotency_key"], created_at_utc=STAMP)
        assert first_ref != second_ref and not replay and not second_replay
        if operation_name == "status": retained = first, first_ref
    first, first_ref = retained
    assert admit_operation(domain, config_ref=config, request=first,
        core_boot_id=str(uuid4()), reservation_ref=None, semantic_key=first["idempotency_key"],
        created_at_utc=STAMP) == (first_ref, True)
    changed = deepcopy(first); changed["input"] = {"operation_ref": first_ref.as_dict()}
    with pytest.raises(ProviderSemanticError):
        admit_operation(domain, config_ref=config, request=changed,
            core_boot_id=str(uuid4()), reservation_ref=None,
            semantic_key=changed["idempotency_key"],
            created_at_utc=STAMP)


def test_concurrent_same_catalog_admission_issues_one_owner_capability(tmp_path, monkeypatch):
    import app.extensions.provider_semantic_records as records_module

    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    request = request_value(roots, config, "catalog", {"catalog_epoch": None})
    boot_id = str(uuid4())
    callers_ready = threading.Barrier(2)
    first_capability_taken = threading.Event()
    original_load = records_module.load_operation
    original_put = DomainStore.put
    original_issue = records_module._issue_owner_capability
    original_take = records_module.take_operation_owner_capability
    put_calls = 0
    issued = []

    def simultaneous_absence(store, request_id):
        value = original_load(store, request_id)
        if value is None:
            callers_ready.wait(timeout=2)
        return value

    def ordered_old_put(store, item):
        nonlocal put_calls
        if item.body["content"].get("schema_version") == "provider-semantic-operation-v1":
            put_calls += 1
            if put_calls == 2:
                assert first_capability_taken.wait(2)
        return original_put(store, item)

    def capture_issue(store, operation_ref, owner_boot_id):
        original_issue(store, operation_ref, owner_boot_id)
        issued.append(original_take(store, operation_ref))
        first_capability_taken.set()

    monkeypatch.setattr(records_module, "load_operation", simultaneous_absence)
    monkeypatch.setattr(DomainStore, "put", ordered_old_put)
    monkeypatch.setattr(records_module, "_issue_owner_capability", capture_issue)
    results, failures = [], []

    def admit():
        try:
            results.append(admit_operation(domain, config_ref=config, request=request,
                core_boot_id=boot_id, reservation_ref=None,
                semantic_key=request["idempotency_key"], created_at_utc=STAMP))
        except BaseException as exc:
            failures.append(exc)

    threads = [threading.Thread(target=admit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(3)
        assert not thread.is_alive()
    assert failures == []
    assert sorted(replay for _, replay in results) == [False, True]
    assert len(issued) == 1 and issued[0] is not None
    assert issued[0].consume(domain, results[0][0], boot_id)


def test_cancel_intent_is_atomic_durable_and_target_monotonic(tmp_path):
    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    target_request = request_value(roots, config, "status", {"operation_ref": config.as_dict()})
    target = seal_operation(domain, config_ref=config, request=target_request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    cancel = request_value(roots, config, "cancel", {"operation_ref": target.as_dict(),
                                       "reason_class": "user_requested"})
    cancel_ref, intent_ref = seal_cancel_operation_and_intent(domain, config_ref=config,
        request=cancel, core_boot_id=str(uuid4()), target_operation_ref=target,
        reason_class="user_requested", created_at_utc=STAMP)
    assert load_operation(domain, cancel["request_id"]).ref == cancel_ref
    intent = load_cancel_intent(domain, target)
    assert intent.ref == intent_ref
    assert intent.body["content"]["first_cancel_operation_ref"] == cancel_ref.as_dict()
    later = deepcopy(cancel); later["request_id"] = str(uuid4())
    later_ref = seal_operation(domain, config_ref=config, request=later,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    with pytest.raises(Exception):
        seal_cancel_intent(domain, target_operation_ref=target,
            first_cancel_operation_ref=later_ref, first_request_sha256="c" * 64,
            reason_class="deadline", core_boot_id=str(uuid4()), created_at_utc=STAMP)
    assert load_cancel_intent(domain, target).ref == intent_ref


def test_model_semantic_key_keeps_one_durable_operation_across_request_ids(tmp_path):
    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    frozen = seal_frozen(domain, command_id=str(uuid4()), content=frozen_content(domain, roots),
                         created_at_utc=STAMP)
    frozen_value = domain.get(frozen).body["content"]
    request = request_value(roots, config, "model_step", {"frozen_turn_ref": frozen.as_dict(),
        "model_id": frozen_value["turn"]["model_id"], "effort": None,
        "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None}, artifact_inputs=frozen_value["artifact_input_bindings"])
    operation, replay = admit_operation(domain, config_ref=config, request=request,
        core_boot_id=str(uuid4()), reservation_ref=None, semantic_key=request["idempotency_key"],
        created_at_utc=STAMP)
    assert not replay
    assert admit_operation(domain, config_ref=config, request=request,
        core_boot_id=str(uuid4()), reservation_ref=None, semantic_key=request["idempotency_key"],
        created_at_utc=STAMP) == (operation, True)
    duplicate = deepcopy(request); duplicate["request_id"] = str(uuid4())
    with pytest.raises(ProviderSemanticError, match="durable owner"):
        admit_operation(domain, config_ref=config, request=duplicate,
            core_boot_id=str(uuid4()), reservation_ref=None, semantic_key=duplicate["idempotency_key"],
            created_at_utc=STAMP)
    assert load_operation(domain, duplicate["request_id"]) is None


def test_model_anchor_without_semantic_index_cannot_be_admitted_for_execution(tmp_path):
    domain, roots = opened(tmp_path)
    config = record(domain, roots, "validation_report")
    frozen = seal_frozen(domain, command_id=str(uuid4()), content=frozen_content(domain, roots),
                         created_at_utc=STAMP)
    frozen_value = domain.get(frozen).body["content"]
    request = request_value(roots, config, "model_step", {"frozen_turn_ref": frozen.as_dict(),
        "model_id": frozen_value["turn"]["model_id"], "effort": None,
        "requested_modalities": ["text"], "tool_definition_refs": [],
        "response_schema_ref": None}, artifact_inputs=frozen_value["artifact_input_bindings"])
    anchor = seal_operation(domain, config_ref=config, request=request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    with pytest.raises(ProviderSemanticError, match="lacks its semantic index"):
        admit_operation(domain, config_ref=config, request=request,
            core_boot_id=str(uuid4()), reservation_ref=None,
            semantic_key=request["idempotency_key"], created_at_utc=STAMP)
    assert load_operation(domain, request["request_id"]).ref == anchor


def test_full_256_row_catalog_seals_pages_capabilities_and_bounded_graph(tmp_path):
    domain, roots = opened(tmp_path)
    metadata = {"command_id": str(uuid4()), "record_id": str(uuid4()), "record_version": 1,
        "provider": "claude", "auth_mode": "api", "created_at": STAMP, "predecessor": None}
    credential_record = {"record_id": metadata["record_id"], "record_version": 1,
                         "ciphertext_sha256": "b" * 64}
    connection = record(domain, roots, "validation_report", content={
        "schema_version": "provider-semantic-connection-v1",
        "locator": {"kind": "connection", "id": str(uuid4())}, "revision_digest": "c" * 64,
        "provider_id": "claude_api", "account_id": "account", "credential_metadata": metadata,
        "credential_metadata_sha256": __import__("app.workers.credential_contracts",
            fromlist=["fingerprint"]).fingerprint(metadata), "credential_record": credential_record})
    source = domain.put_blob(b"synthetic reviewed model scope", purpose="operational")
    policy = record(domain, roots, "validation_report", content={
        "schema_version": "provider-semantic-text-policy-v1",
        "source_url": "https://platform.claude.com/docs/en/models/overview",
        "source_blob": source.as_dict(), "source_sha256": source.sha256,
        "retrieved_at": "2026-09-20T00:00:00.000Z", "reviewed_at": "2026-09-20T00:00:00.000Z",
        "valid_until": "2026-09-21T00:00:00.000Z",
        "scope_model_ids": [f"model-{index:03d}" for index in range(255)],
        "claim": "current-models-text-input-output", "reviewer_ref": roots.actor.as_dict()},
        parents=(roots.actor,))
    compatibility_observation = record(domain, roots, "validation_report")
    request_policy_sha256 = sha256(canonical_json({"profile_id": "claude-api-text-semantic-v1",
        "api_version": "2023-06-01", "auth": "api-key", "effort": None, "tools": False,
        "cache": False, "thinking_override": None, "success_stop": "end_turn",
        "input_media_types": ["text/plain"], "max_inputs": 4, "max_output_blocks": 4,
        "max_output_tokens": 8192, "deadline_ms": 30000})).hexdigest()
    compatibility = record(domain, roots, "validation_report", content={
        "schema_version": "provider-semantic-compatibility-v1",
        "profile_id": "claude-api-text-semantic-v1", "connection_ref": connection.as_dict(),
        "model_id": "model-000", "request_policy_sha256": request_policy_sha256,
        "observed_at": "2026-09-20T00:00:00.000Z",
        "expires_at": "2026-09-21T00:00:00.000Z",
        "observation_ref": compatibility_observation.as_dict(), "outcome": "complete_text"},
        parents=tuple(sorted((connection, compatibility_observation),
                             key=lambda ref: canonical_json(ref.as_dict()))))
    compatibility_set = record(domain, roots, "validation_report", content={
        "schema_version": "provider-semantic-compatibility-set-v1",
        "profile_id": "claude-api-text-semantic-v1", "connection_ref": connection.as_dict(),
        "observation_refs": [compatibility.as_dict()]}, parents=(connection,))
    config_projection = canonical_provider_config(connection.as_dict(), identity={
        "qualification_ref": compatibility_observation.as_dict(),
        "binding_revision_ref": compatibility_observation.as_dict(),
        "egress_policy_ref": roots.access_policy.as_dict()})
    config_parents = tuple(sorted({connection, policy, compatibility_set,
        compatibility_observation, roots.access_policy},
        key=lambda ref: canonical_json(ref.as_dict())))
    config = record(domain, roots, "validation_report", content={
        "schema_version": "provider-semantic-config-v1",
        "config": config_projection,
        "connection_ref": connection.as_dict(), "text_policy_ref": policy.as_dict(),
        "compatibility_set_ref": compatibility_set.as_dict()},
        parents=config_parents)
    request = request_value(roots, config, "catalog", {"catalog_epoch": None})
    operation = seal_operation(domain, config_ref=config, request=request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    raw_pages, traversal = [], CatalogTraversal()
    for page_index, count in enumerate((100, 100, 56)):
        ids = [f"model-{page_index * 100 + index:03d}" for index in range(count)]
        raw = dense_page(ids, more=page_index < 2)
        if page_index == 0:
            native = __import__("json").loads(raw)
            native["future_root"] = {"retained": 1}
            native["data"][0]["future_model"] = ["retained-only-in-raw"]
            raw = __import__("json").dumps(native, separators=(",", ":")).encode()
        raw_pages.append(raw)
        traversal = advance_catalog(traversal, parse_model_page(raw))
    catalog = seal_catalog_traversal(domain, operation_ref=operation,
        connection_ref=connection, text_policy_ref=policy,
        compatibility_by_model={"model-000": compatibility},
        traversal=traversal, raw_pages=tuple(raw_pages),
        fetched_at="2026-09-20T00:00:00.000Z", expires_at="2026-09-21T00:00:00.000Z",
        created_at_utc=STAMP)
    loaded = domain.get(catalog)
    assert len(loaded.body["content"]["models"]) == 256
    assert loaded.body["content"]["eligible_model_ids"] == ["model-000"]
    assert loaded.body["content"]["models"][0]["modalities"] == ["text"]
    assert loaded.body["content"]["excluded"][0] == {
        "model_id": "model-001", "reason": "profile_unproved"}
    assert loaded.body["content"]["excluded"][-1] == {
        "model_id": "model-255", "reason": "text_scope_unproved"}
    page_refs = [EntityRef.from_dict(item) for item in loaded.body["content"]["page_refs"]]
    assert {EntityRef.from_dict(item) for item in loaded.body["parent_refs"]} == {
        operation, connection, *page_refs}
    first_page = domain.get(page_refs[0])
    assert domain.read_blob(BlobRef.from_dict(first_page.body["content"]["raw_blob"]),
                            purpose="operational") == raw_pages[0]
    first_capability = EntityRef.from_dict(loaded.body["content"]["models"][0][
        "capability_evidence_ref"])
    assert set(domain.get(first_capability).body["content"]["projection"]) == {
        "id", "display_name", "created_at", "capabilities", "max_input_tokens", "max_tokens"}
    with pytest.raises(ProviderSemanticError, match="catalog expiry"):
        seal_catalog_traversal(domain, operation_ref=operation, connection_ref=connection,
            text_policy_ref=policy, compatibility_by_model={"model-000": compatibility},
            traversal=traversal, raw_pages=tuple(raw_pages),
            fetched_at="2026-09-20T00:00:00.000Z",
            expires_at="2026-09-20T12:00:00.000Z", created_at_utc=STAMP)
    changed = list(raw_pages)
    changed[0] = changed[0].replace(b"retained-only-in-raw", b"different-raw-value")
    with pytest.raises(ProviderSemanticError):
        seal_catalog_traversal(domain, operation_ref=operation, connection_ref=connection,
            text_policy_ref=policy, compatibility_by_model={"model-000": compatibility},
            traversal=traversal, raw_pages=tuple(changed),
            fetched_at="2026-09-20T00:00:00.000Z",
            expires_at="2026-09-21T00:00:00.000Z", created_at_utc=STAMP)
    bad_hash_policy = deepcopy(domain.get(policy).body["content"])
    bad_hash_policy["source_sha256"] = "0" * 64
    with pytest.raises(DomainContractError):
        record(domain, roots, "validation_report", content=bad_hash_policy,
               parents=(roots.actor,))
    bad_policy_value = deepcopy(domain.get(policy).body["content"])
    bad_policy_value["valid_until"] = "2026-09-19T00:00:00.000Z"
    bad_policy = record(domain, roots, "validation_report", content=bad_policy_value,
                        parents=(roots.actor,))
    bad_config_projection = deepcopy(config_projection)
    bad_config = record(domain, roots, "validation_report", content={
        "schema_version": "provider-semantic-config-v1",
        "config": bad_config_projection,
        "connection_ref": connection.as_dict(), "text_policy_ref": bad_policy.as_dict(),
        "compatibility_set_ref": compatibility_set.as_dict()},
        parents=tuple(sorted({connection, bad_policy, compatibility_set,
            compatibility_observation, roots.access_policy},
            key=lambda ref: canonical_json(ref.as_dict()))))
    bad_request = deepcopy(request); bad_request["request_id"] = str(uuid4())
    bad_operation = seal_operation(domain, config_ref=bad_config, request=bad_request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    with pytest.raises(ProviderSemanticError):
        seal_catalog_traversal(domain, operation_ref=bad_operation,
            connection_ref=connection, text_policy_ref=bad_policy,
            compatibility_by_model={"model-000": compatibility}, traversal=traversal,
            raw_pages=tuple(raw_pages), fetched_at="2026-09-20T00:00:00.000Z",
            expires_at="2026-09-21T00:00:00.000Z", created_at_utc=STAMP)
    with sqlite3.connect(domain.path) as db:
        assert db.execute("SELECT count(*) FROM domain_edges WHERE source_kind='model_catalog' "
                          "AND source_id=?", (catalog.id,)).fetchone()[0] == 264
        capability_refs = [EntityRef.from_dict(row["capability_evidence_ref"])
                           for row in loaded.body["content"]["models"]]
        assert db.execute("SELECT count(*) FROM domain_edges WHERE source_kind='model_catalog' "
            "AND source_id=? AND target_id IN (%s)" % ",".join("?" for _ in capability_refs),
            (catalog.id, *(ref.id for ref in capability_refs))).fetchone()[0] == 256
