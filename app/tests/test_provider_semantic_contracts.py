from copy import deepcopy
from hashlib import sha256
from uuid import uuid4

import pytest

from app.extensions.provider_semantic_contracts import (
    PROFILE,
    ProviderSemanticError,
    allowed_terminal,
    instruction_projection_digest,
    semantic_record_id,
    validate_semantic_domain_body,
    validate_frozen_content,
)
from app.domain.refs import canonical_json
from app.tests.support.provider_semantic_harness import canonical_provider_request


H = "a" * 64


def ref(kind="artifact"):
    return {"kind": kind, "id": str(uuid4()), "version": 1, "sha256": H}


def frozen():
    artifact = ref()
    projection = {"profile_id": "execution-model-step", "system_artifact_ref": None}
    return {
        "schema_version": "provider-semantic-frozen-v1",
        "turn": {
            "profile": "execution-model-step", "work_ref": ref("work_revision"),
            "environment_ref": ref("environment"), "node_id": "writer",
            "execution_id": str(uuid4()), "attempt_index": 0,
            "provider": "claude_api", "account_id": "account", "catalog_ref": ref("model_catalog"),
            "model_id": "model-1", "effort": None,
            "instruction_profile_digest": instruction_projection_digest(projection),
            "inputs": [{"type": "text", "ref": artifact, "marker": None, "omissions": []}],
            "granted_tools": [], "output_schema_id": None,
            "runtime_profile_ref": ref("runtime_profile"), "deadline_seconds": 30,
            "budget_ref": ref("budget_policy"), "consent_ref": ref("run_consent"),
        },
        "execution_envelope_ref": ref("execution_envelope"),
        "purpose_ref": ref("validation_report"), "grant_refs": [],
        "artifact_input_bindings": [{"artifact_ref": artifact, "selector_ref": None,
                                     "declared_media_type": "text/plain", "role": "model_input"}],
        "messages": [{"role": "user", "input_ordinals": [0]}],
        "max_output_tokens": 128, "instruction_projection": projection,
    }


def semantic_body(kind, content, *, parents=()):
    return {"schema_version": "domain-v1", "kind": kind, "id": str(uuid4()),
        "version": 1, "created_at_utc": "2026-09-20T00:00:00.000000Z",
        "actor_ref": ref("actor"), "parent_refs": list(parents), "purpose": "operational",
        "access_policy_ref": ref("access_policy"),
        "retention_policy_ref": ref("retention_policy"), "content": content}


def portable_envelope(body):
    return {"ref": {"kind": body["kind"], "id": body["id"], "version": 1,
                    "sha256": sha256(canonical_json(body)).hexdigest()}, "body": body}


def test_frozen_f_model_exact_order_and_instruction_digest():
    value = frozen()
    assert validate_frozen_content(value) == value
    for mutate in (
        lambda v: v["messages"][0].update(input_ordinals=[1]),
        lambda v: v["artifact_input_bindings"][0].update(selector_ref=ref("selector")),
        lambda v: v["artifact_input_bindings"][0].update(declared_media_type="image/png"),
        lambda v: v["turn"].update(instruction_profile_digest="0" * 64),
        lambda v: v["turn"]["inputs"][0].update(ref=ref()),
    ):
        bad = deepcopy(value)
        mutate(bad)
        with pytest.raises(ProviderSemanticError):
            validate_frozen_content(bad)


def test_malformed_durable_variants_refuse_runtime_and_portable_validation():
    from jsonschema import Draft202012Validator
    from app.domain.schema_exports import domain_schema

    frozen_content = frozen()
    missing_parent_projection = semantic_body("frozen_turn", frozen_content, parents=())
    with pytest.raises(ProviderSemanticError, match="parent projection"):
        validate_semantic_domain_body(missing_parent_projection)

    portable_bad = deepcopy(missing_parent_projection)
    portable_bad["content"]["turn"]["future_decision"] = True
    assert list(Draft202012Validator(domain_schema()).iter_errors(
        portable_envelope(portable_bad)))

    request = canonical_provider_request("capabilities", {})
    operation_ref = ref("validation_report")
    config_ref = ref("validation_report")
    operation_content = {"schema_version": "provider-semantic-operation-v1",
        "request": request, "config_ref": config_ref, "request_sha256": "0" * 64,
        "core_boot_id": str(uuid4()), "frozen_ref": None, "envelope_ref": None,
        "reservation_ref": None}
    operation = semantic_body("validation_report", operation_content,
        parents=sorted((config_ref,), key=canonical_json))
    with pytest.raises(ProviderSemanticError, match="request digest"):
        validate_semantic_domain_body(operation)

    page_ref = ref("validation_report")
    rows = [
        {"model_id": "model-a", "display_name": "A", "modalities": ["text"],
         "effort_values": ["low"], "capability_evidence_ref": ref("validation_report")},
        {"model_id": "model-b", "display_name": "B", "modalities": ["text"],
         "effort_values": ["medium"], "capability_evidence_ref": ref("validation_report")},
        {"model_id": "model-c", "display_name": "C", "modalities": [],
         "effort_values": [], "capability_evidence_ref": ref("validation_report")},
    ]
    catalog_content = {"schema_version": "provider-semantic-catalog-v1",
        "operation_ref": operation_ref, "connection_ref": config_ref,
        "fetched_at": "2026-09-20T00:00:00.000Z",
        "expires_at": "2026-09-20T00:01:00.000Z", "page_refs": [page_ref],
        "complete": True, "models": rows, "eligible_model_ids": ["model-b", "model-a"],
        "excluded": [{"model_id": "model-c", "reason": "text_scope_unproved"}]}
    catalog = semantic_body("model_catalog", catalog_content,
        parents=sorted((operation_ref, config_ref, page_ref), key=canonical_json))
    with pytest.raises(ProviderSemanticError, match="API order"):
        validate_semantic_domain_body(catalog)
    bad_effort = deepcopy(catalog)
    bad_effort["content"]["eligible_model_ids"] = ["model-a", "model-b"]
    bad_effort["content"]["models"][0]["effort_values"] = ["future"]
    with pytest.raises(ProviderSemanticError, match="effort"):
        validate_semantic_domain_body(bad_effort)


def test_read_ids_refresh_without_changing_semantic_hash():
    vault = str(uuid4())
    owner1, owner2 = str(uuid4()), str(uuid4())
    assert semantic_record_id(vault, "provider-semantic-operation-v1", owner1) != semantic_record_id(
        vault, "provider-semantic-operation-v1", owner2
    )
    assert PROFILE == "claude-api-text-semantic-v1"


def test_observation_exception_is_profile_scoped():
    from app.extensions.provider_semantic_contracts import permits_fresh_observation

    for operation in ("capabilities", "catalog", "status"):
        assert permits_fresh_observation("provider-port-v1", PROFILE, operation)
    assert not permits_fresh_observation("provider-port-v1", "other", "status")
    assert not permits_fresh_observation("model-runtime-port-v1", PROFILE, "status")
    assert not permits_fresh_observation("provider-port-v1", PROFILE, "model_step")


def test_terminal_matrix_and_artifact_quarantine():
    permitted = {(operation, terminal) for operation in
                 ("capabilities", "catalog", "model_step", "status", "cancel")
                 for terminal in ("succeeded", "failed", "cancelled", "unknown")
                 if allowed_terminal(operation, terminal)}
    assert len(permitted) == 12
    assert {terminal for operation, terminal in permitted if operation == "model_step"} == {
        "succeeded", "failed", "cancelled", "unknown"
    }
    for operation in ("capabilities", "catalog", "status", "cancel"):
        assert {terminal for op, terminal in permitted if op == operation} == {"succeeded", "failed"}


def test_domain_schema_export_includes_provider_semantic_variants():
    import json
    from jsonschema import Draft202012Validator
    from app.domain.schema_exports import domain_schema
    from app.domain.schemas import ImmutableRecord

    actor, access, retention, operation = ref("actor"), ref("access_policy"), ref("retention_policy"), ref("validation_report")
    blob = {"vault_id": str(uuid4()), "purpose": "operational", "sha256": H, "size": 2}
    item = ImmutableRecord.create(kind="artifact", id=str(uuid4()), version=1,
        created_at_utc="2026-09-20T00:00:00.000000Z", actor_ref=__import__("app.domain.refs", fromlist=["EntityRef"]).EntityRef.from_dict(actor),
        parent_refs=[__import__("app.domain.refs", fromlist=["EntityRef"]).EntityRef.from_dict(operation)],
        purpose="operational", access_policy_ref=__import__("app.domain.refs", fromlist=["EntityRef"]).EntityRef.from_dict(access),
        retention_policy_ref=__import__("app.domain.refs", fromlist=["EntityRef"]).EntityRef.from_dict(retention),
        content={"schema_version": "provider-semantic-output-v1", "operation_ref": operation,
                 "ordinal": 0, "blob_ref": blob, "media_type": "text/plain",
                 "content_digest": H, "byte_count": 2})
    assert list(Draft202012Validator(domain_schema()).iter_errors(item.as_dict())) == []
    malformed = deepcopy(item.as_dict())
    malformed["body"]["content"]["ordinal"] = 5
    assert list(Draft202012Validator(domain_schema()).iter_errors(malformed))
    checked = json.loads(open("schemas/v1/domain-envelopes.schema.json", encoding="utf-8").read())
    assert checked == domain_schema()


@pytest.mark.parametrize("currency", ["usd", "Usd", "US1", "US ", "US\n", "\u00d9SD", "US", "USDD", None, True])
def test_reservation_currency_exact_uppercase_runtime_and_portable_schema(currency):
    from jsonschema import Draft202012Validator
    from app.domain.schema_exports import domain_schema
    actor, access, retention = ref("actor"), ref("access_policy"), ref("retention_policy")
    connection = ref("validation_report")
    content = {"schema_version": "provider-semantic-reservation-v1",
        "connection_ref": connection, "model_id": "model-1",
        "proposal_sha256": H, "input_upper_bound": 1, "max_output_tokens": 1,
        "currency": currency, "reserved_microunits": 1,
        "effective_at": "2026-09-20T00:00:00.000Z",
        "expires_at": "2026-09-20T00:01:00.000Z",
        "method_blob": {"vault_id": str(uuid4()), "purpose": "operational",
                        "sha256": H, "size": 1},
        "reviewer_ref": actor, "basis": "reviewed-conservative-estimate"}
    valid = {"schema_version": "domain-v1", "kind": "validation_report", "id": str(uuid4()),
        "version": 1, "created_at_utc": "2026-09-20T00:00:00.000000Z",
        "actor_ref": actor,
        "parent_refs": sorted([connection, actor], key=lambda item: __import__(
            "app.domain.refs", fromlist=["canonical_json"]).canonical_json(item)),
        "purpose": "operational", "access_policy_ref": access,
        "retention_policy_ref": retention, "content": content}
    from app.domain.refs import canonical_json
    envelope = {"ref": {"kind": valid["kind"], "id": valid["id"], "version": 1,
                        "sha256": __import__("hashlib").sha256(canonical_json(valid)).hexdigest()},
                "body": valid}
    if currency in {"USD", "EUR", "KRW"}:
        validate_semantic_domain_body(valid)
        assert list(Draft202012Validator(domain_schema()).iter_errors(envelope)) == []
    else:
        with pytest.raises(ProviderSemanticError):
            validate_semantic_domain_body(valid)
        assert list(Draft202012Validator(domain_schema()).iter_errors(envelope))


def test_reservation_currency_valid_uppercase_variants():
    for currency in ("USD", "EUR", "KRW"):
        # Exercise the same direct/schema boundary with valid values without
        # normalizing to the budget policy's selected currency.
        test_reservation_currency_exact_uppercase_runtime_and_portable_schema(currency)
