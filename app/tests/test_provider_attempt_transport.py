from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import threading
from uuid import uuid4

import pytest

from app.extensions.provider_semantic_context import (ProviderSemanticAuthority,
    validate_bound_handle)
from app.extensions.provider_semantic_contracts import (ProviderSemanticError,
    canonical_provider_result)
from app.extensions.provider_semantic_records import (load_cancel_intent, load_operation, seal_operation,
    seal_cancel_operation_and_intent, seal_terminal)
from app.domain.schemas import ImmutableRecord
from app.domain.store import DomainStore
from app.storage import Store
from app.runtime.ledger import RuntimeLedger
from app.workers.credential_contracts import fingerprint
from app.domain.refs import EntityRef, canonical_json
from app.tests.support import durable_binding
from app.tests.support.provider_semantic_harness import (canonical_provider_config,
    canonical_provider_request)


def ref():
    return {"kind": "validation_report", "id": str(uuid4()), "version": 1, "sha256": "a" * 64}


def test_bound_handle_is_exact_connection_snapshot():
    handle = ref()
    meta = {"command_id": str(uuid4()), "record_id": str(uuid4()), "record_version": 1,
            "provider": "claude", "auth_mode": "api", "created_at": "2026-09-20T00:00:00.000000Z",
            "predecessor": None}
    record = {"record_id": meta["record_id"], "record_version": 1, "ciphertext_sha256": "b" * 64}
    connection = {"ref": handle, "content": {"schema_version": "provider-semantic-connection-v1",
        "locator": {"kind": "connection", "id": str(uuid4())}, "revision_digest": "c" * 64,
        "provider_id": "claude_api", "account_id": "account", "credential_metadata": meta,
        "credential_metadata_sha256": fingerprint(meta), "credential_record": record}}
    config = {"credential_handle_refs": [handle]}
    binding = {"credential_handle_refs": [handle]}
    current = {key: connection["content"][key] for key in
               ("locator", "revision_digest", "provider_id", "account_id", "credential_metadata_sha256")}
    pin = validate_bound_handle(config=config, binding=binding, connection_record=connection,
                                current_connection=current)
    assert pin["selected_handle_ref"] == handle and pin["credential_record"] == record
    mutations = [
        lambda c, b, r, n: c.update(credential_handle_refs=[ref()]),
        lambda c, b, r, n: b.update(credential_handle_refs=[ref()]),
        lambda c, b, r, n: r["content"].update(account_id="other"),
        lambda c, b, r, n: n.update(revision_digest="d" * 64),
        lambda c, b, r, n: r["content"]["credential_record"].update(record_version=2),
    ]
    for mutate in mutations:
        c, b, r, n = deepcopy(config), deepcopy(binding), deepcopy(connection), deepcopy(current)
        mutate(c, b, r, n)
        with pytest.raises(ProviderSemanticError):
            validate_bound_handle(config=c, binding=b, connection_record=r, current_connection=n)
    # A coherent alternate B snapshot is still invalid under the admitted A
    # config/binding handle.  This join belongs to core; the gateway has no store.
    meta_b = {**meta, "command_id": str(uuid4()), "record_id": str(uuid4())}
    record_b = {"record_id": meta_b["record_id"], "record_version": 1,
                "ciphertext_sha256": "d" * 64}
    connection_b = {"ref": ref(), "content": {**connection["content"],
        "locator": {"kind": "connection", "id": str(uuid4())},
        "revision_digest": "e" * 64, "account_id": "account-b",
        "credential_metadata": meta_b,
        "credential_metadata_sha256": fingerprint(meta_b), "credential_record": record_b}}
    current_b = {key: connection_b["content"][key] for key in
                 ("locator", "revision_digest", "provider_id", "account_id",
                  "credential_metadata_sha256")}
    with pytest.raises(ProviderSemanticError):
        validate_bound_handle(config=config, binding=binding, connection_record=connection_b,
                              current_connection=current_b)


def test_provider_attempt_transport_has_exact_dispatcher_callable_shape():
    from inspect import signature
    from app.runtime.provider_attempt_transport import ProviderAttemptTransport

    assert list(signature(ProviderAttemptTransport.__call__).parameters) == ["self", "permit", "request", "window"]


@pytest.mark.parametrize(("code", "effect_state", "expected"), [
    ("permission_denied", "none", ("denied", "not_observed", "permission_denied")),
    ("integrity_failed", "none", ("failed", "not_observed", "validation_failed")),
    ("dependency_unavailable", "unknown", ("failed", "failed", "validation_failed")),
])
def test_historical_failed_transport_reconstruction_preserves_local_semantics(
        code, effect_state, expected):
    from types import SimpleNamespace
    from app.runtime.provider_attempt_transport import ProviderAttemptTransport

    retained = SimpleNamespace(ref=__import__("app.domain.refs", fromlist=["EntityRef"]).EntityRef(
        "validation_report", str(uuid4()), 1, "f" * 64), body={"content": {"result": {
        "terminal": "failed", "error": {"code": code},
        "effect": {"effect_state": effect_state}}}})
    rebuilt = ProviderAttemptTransport._retained_attempt_result(retained)
    assert (rebuilt.outcome, rebuilt.remote_terminal_observed,
            rebuilt.reason_code) == expected


STAMP = "2026-09-20T00:00:00.000000Z"
_port_time = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@pytest.fixture(autouse=True)
def query_case_clock():
    # Each case gets the same 30s budget, independent of collection/suite duration.
    global STAMP, PORT_STAMP, PORT_STAMP_1, PORT_STAMP_2, FUTURE
    now = datetime.now(timezone.utc)
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    STAMP = now.isoformat(timespec="microseconds").replace("+00:00", "Z")
    PORT_STAMP = _port_time(now)
    PORT_STAMP_1 = _port_time(now + timedelta(seconds=1))
    PORT_STAMP_2 = _port_time(now + timedelta(seconds=2))
    FUTURE = _port_time(now + timedelta(seconds=30))


INSTALLATIONS = set()


@pytest.fixture(autouse=True)
def durable_installations(monkeypatch):
    # the durable binding a config names points at a test-admitted verified installation
    global INSTALLATIONS
    INSTALLATIONS = durable_binding.admit_test_installations(monkeypatch)


def operation_case(tmp_path):
    domain = DomainStore(Store(tmp_path / "vault")); roots = domain.initialize_vault()
    ledger = RuntimeLedger(domain, clock_ms=lambda: 1_000)
    ledger.reconcile_startup(str(uuid4()), observed_owners={})
    def put(content, *, kind="validation_report", parents=()):
        return domain.put(ImmutableRecord.create(kind=kind, id=str(uuid4()), version=1,
            created_at_utc=STAMP, actor_ref=roots.actor, parent_refs=parents,
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy, content=content))
    qualification = put({"fixture": "qualification"})
    bound = durable_binding.bind(domain, INSTALLATIONS, qualification_ref=qualification.as_dict())
    binding_revision = EntityRef.from_dict(bound.ref)
    purpose, text_policy, compatibility_set = (put({"fixture": name}) for name in
        ("purpose", "text-policy", "compatibility-set"))
    meta = {"command_id": str(uuid4()), "record_id": str(uuid4()), "record_version": 1,
        "provider": "claude", "auth_mode": "api", "created_at": STAMP,
        "predecessor": None}
    credential = {"record_id": meta["record_id"], "record_version": 1,
                  "ciphertext_sha256": "b" * 64}
    pin = {"locator": {"kind": "connection", "id": str(uuid4())},
        "revision_digest": "c" * 64, "provider_id": "claude_api", "account_id": "account",
        "credential_metadata_sha256": fingerprint(meta)}
    connection = put({"schema_version": "provider-semantic-connection-v1", **pin,
                      "credential_metadata": meta, "credential_record": credential})
    identity = {"installation_digest": bound.installation.sha256,
        "qualification_ref": qualification.as_dict(),
        "binding_revision_ref": binding_revision.as_dict(), "purpose_ref": purpose.as_dict(),
        "actor_ref": roots.actor.as_dict(), "grant_refs": [],
        "egress_policy_ref": roots.access_policy.as_dict()}
    config_value = canonical_provider_config(connection.as_dict(), identity={
        **identity, **durable_binding.config_identity(bound)})
    parents = tuple(sorted((connection, text_policy, compatibility_set, qualification,
        binding_revision, roots.access_policy), key=lambda item: canonical_json(item.as_dict())))
    config = put({"schema_version": "provider-semantic-config-v1", "config": config_value,
        "connection_ref": connection.as_dict(), "text_policy_ref": text_policy.as_dict(),
        "compatibility_set_ref": compatibility_set.as_dict()}, parents=parents)
    target_request = canonical_provider_request("status", {"operation_ref": config.as_dict()},
        identity=identity,
        deadline_at=FUTURE)
    owner_boot = str(uuid4())
    target = seal_operation(domain, config_ref=config, request=target_request,
        core_boot_id=owner_boot, reservation_ref=None, created_at_utc=STAMP)
    assert config_value["binding_slot_key_digest"] == bound.digest
    authority = ProviderSemanticAuthority(
        binding_refs=durable_binding.binding_refs(config_value),
        current_connection=pin, qualification_record={"ref": qualification.as_dict(),
            "status": "qualified", "installation_digest": config_value["installation_digest"],
            "port_contract_version": "provider-port-v1", "expires_at": FUTURE},
        actor_record={"ref": roots.actor.as_dict(), "authenticated": True,
                      "actor_type": "system"},
        purpose_record={"ref": purpose.as_dict(), "active": True,
                        "purpose": "operational"}, grant_records={}, artifact_records={},
        selector_records={}, input_records={}, core_boot_id=owner_boot)
    return domain, ledger, config, target, target_request, authority


def test_fresh_status_replays_old_observation_and_new_id_reads_terminal_or_restart_unknown(tmp_path):
    from app.runtime.provider_attempt_transport import ProviderSemanticOperationController

    domain, ledger, config, target, target_request, authority = operation_case(tmp_path)
    controller = ProviderSemanticOperationController(domain, ledger=ledger, config_ref=config,
        core_boot_id=str(uuid4()), authority=authority)
    controller.register_live(target, cancel_event=threading.Event(), forward_cancel=lambda _reason: None)
    identity = {name: target_request[name] for name in ("installation_digest", "qualification_ref",
        "binding_revision_ref", "purpose_ref", "actor_ref", "grant_refs")}
    q1 = canonical_provider_request("status", {"operation_ref": target.as_dict()}, identity=identity,
                                    deadline_at=FUTURE)
    running = controller.observe_status(q1, semantic_key=q1["idempotency_key"],
        observed_at=PORT_STAMP, created_at_utc=STAMP)
    assert running["output"]["observed_state"] == "running"
    target_result = canonical_provider_result(target_request, terminal="succeeded",
        started_at=PORT_STAMP, completed_at=PORT_STAMP,
        output={"observed_state": "unknown", "observed_at": PORT_STAMP,
                "terminal_result_ref": None})
    target_terminal = seal_terminal(domain, operation_ref=target, result=target_result,
                                    response_ref=None, created_at_utc=STAMP)
    controller.finish(target, target_terminal)
    q2 = deepcopy(q1); q2["request_id"] = str(uuid4())
    completed = controller.observe_status(q2, semantic_key=q2["idempotency_key"],
        observed_at=PORT_STAMP_1, created_at_utc=STAMP)
    assert completed["output"]["observed_state"] == "running"
    assert completed["output"]["terminal_result_ref"] is None
    assert controller.observe_status(q1, semantic_key=q1["idempotency_key"],
        observed_at=PORT_STAMP_2, created_at_utc=STAMP) == running

    unresolved_request = canonical_provider_request("status", {"operation_ref": config.as_dict()},
                                                     identity=identity, deadline_at=FUTURE)
    unresolved = seal_operation(domain, config_ref=config, request=unresolved_request,
        core_boot_id=str(uuid4()), reservation_ref=None, created_at_utc=STAMP)
    restarted = ProviderSemanticOperationController(domain, ledger=ledger, config_ref=config,
        core_boot_id=str(uuid4()), authority=authority)
    q3 = canonical_provider_request("status", {"operation_ref": unresolved.as_dict()},
                                    identity=identity, deadline_at=FUTURE)
    assert restarted.observe_status(q3, semantic_key=q3["idempotency_key"],
        observed_at=PORT_STAMP, created_at_utc=STAMP)["output"]["observed_state"] == "unknown"


def test_cancel_fence_forwards_once_and_crash_before_latch_never_reconstructs_action(tmp_path):
    from app.runtime.provider_attempt_transport import ProviderSemanticOperationController

    domain, ledger, config, target, _, authority = operation_case(tmp_path)
    event, forwarded = threading.Event(), []
    controller = ProviderSemanticOperationController(domain, ledger=ledger, config_ref=config,
        core_boot_id=str(uuid4()), authority=authority)
    controller.register_live(target, cancel_event=event, forward_cancel=forwarded.append)
    target_request = domain.get(target).body["content"]["request"]
    identity = {name: target_request[name] for name in ("installation_digest", "qualification_ref",
        "binding_revision_ref", "purpose_ref", "actor_ref", "grant_refs")}
    first = canonical_provider_request("cancel", {"operation_ref": target.as_dict(),
        "reason_class": "user_requested"}, identity=identity, deadline_at=FUTURE)
    accepted = controller.cancel(first, semantic_key=first["idempotency_key"],
        observed_at=PORT_STAMP, created_at_utc=STAMP)
    assert accepted["output"]["cancel_state"] == "accepted"
    assert event.is_set() and forwarded == ["user_requested"]
    second = deepcopy(first); second["request_id"] = str(uuid4())
    repeated = controller.cancel(second, semantic_key=second["idempotency_key"],
        observed_at=PORT_STAMP, created_at_utc=STAMP)
    assert repeated["output"]["cancel_state"] == "accepted" and len(forwarded) == 1
    assert controller.cancel(first, semantic_key=first["idempotency_key"],
        observed_at=PORT_STAMP_1, created_at_utc=STAMP) == accepted
    target_result = canonical_provider_result(target_request, terminal="succeeded",
        started_at=PORT_STAMP, completed_at=PORT_STAMP,
        output={"observed_state": "unknown", "observed_at": PORT_STAMP,
                "terminal_result_ref": None})
    target_terminal = seal_terminal(domain, operation_ref=target, result=target_result,
                                    response_ref=None, created_at_utc=STAMP)
    controller.finish(target, target_terminal)
    third = deepcopy(first); third["request_id"] = str(uuid4())
    assert controller.cancel(third, semantic_key=third["idempotency_key"],
        observed_at=PORT_STAMP, created_at_utc=STAMP)["output"]["cancel_state"] == "accepted"
    assert len(forwarded) == 1

    domain2, ledger2, config2, target2, _, authority2 = operation_case(tmp_path / "crash")
    event2, forwarded2 = threading.Event(), []
    before = ProviderSemanticOperationController(domain2, ledger=ledger2, config_ref=config2,
        core_boot_id=str(uuid4()), authority=authority2)
    before.register_live(target2, cancel_event=event2, forward_cancel=forwarded2.append)
    target2_request = domain2.get(target2).body["content"]["request"]
    identity2 = {name: target2_request[name] for name in ("installation_digest", "qualification_ref",
        "binding_revision_ref", "purpose_ref", "actor_ref", "grant_refs")}
    lost = canonical_provider_request("cancel", {"operation_ref": target2.as_dict(),
        "reason_class": "user_requested"}, identity=identity2, deadline_at=FUTURE)
    lost_operation, _ = seal_cancel_operation_and_intent(domain2, config_ref=config2,
        request=lost, core_boot_id=str(uuid4()), target_operation_ref=target2,
        reason_class="user_requested", created_at_utc=STAMP)
    assert load_cancel_intent(domain2, target2) is not None
    assert not event2.is_set() and forwarded2 == []
    after = ProviderSemanticOperationController(domain2, ledger=ledger2, config_ref=config2,
        core_boot_id=str(uuid4()), authority=authority2)
    fresh = deepcopy(lost); fresh["request_id"] = str(uuid4())
    assert after.cancel(fresh, semantic_key=fresh["idempotency_key"],
        observed_at=PORT_STAMP, created_at_utc=STAMP)["output"]["cancel_state"] == "not_cancellable"
    assert forwarded2 == []
    with pytest.raises(ValueError, match="acknowledgement unavailable"):
        after.cancel(lost, semantic_key=lost["idempotency_key"],
            observed_at=PORT_STAMP, created_at_utc=STAMP)


def test_unauthorized_query_cannot_observe_or_cancel_live_target(tmp_path):
    from app.runtime.provider_attempt_transport import ProviderSemanticOperationController

    domain, ledger, config, target, target_request, authority = operation_case(tmp_path)
    event, forwarded = threading.Event(), []
    controller = ProviderSemanticOperationController(domain, ledger=ledger, config_ref=config,
        core_boot_id=str(uuid4()), authority=authority)
    controller.register_live(target, cancel_event=event, forward_cancel=forwarded.append,
        attempt_id=str(uuid4()), execution_id=str(uuid4()), envelope_ref=config)
    exact = {name: target_request[name] for name in ("installation_digest", "qualification_ref",
        "binding_revision_ref", "purpose_ref", "actor_ref", "grant_refs")}
    mutations = [
        {**exact, "actor_ref": ref()},
        {**exact, "purpose_ref": ref()},
        {**exact, "binding_revision_ref": ref()},
        {**exact, "qualification_ref": ref()},
    ]
    for identity in mutations:
        status = canonical_provider_request("status", {"operation_ref": target.as_dict()},
            identity=identity, deadline_at=FUTURE)
        with pytest.raises(Exception):
            controller.observe_status(status, semantic_key=status["idempotency_key"],
                observed_at=PORT_STAMP, created_at_utc=STAMP)
        cancel = canonical_provider_request("cancel", {"operation_ref": target.as_dict(),
            "reason_class": "user_requested"}, identity=identity, deadline_at=FUTURE)
        with pytest.raises(Exception):
            controller.cancel(cancel, semantic_key=cancel["idempotency_key"],
                observed_at=PORT_STAMP, created_at_utc=STAMP)
        assert load_cancel_intent(domain, target) is None
        assert load_operation(domain, status["request_id"]) is None
        assert load_operation(domain, cancel["request_id"]) is None
    assert not event.is_set() and forwarded == []


def test_query_historical_replay_requires_owner_read_authority(tmp_path):
    from app.runtime.provider_attempt_transport import ProviderSemanticOperationController

    domain, ledger, config, target, target_request, authority = operation_case(tmp_path)
    controller = ProviderSemanticOperationController(domain, ledger=ledger, config_ref=config,
        core_boot_id=str(uuid4()), authority=authority)
    controller.register_live(target, cancel_event=threading.Event(),
                             forward_cancel=lambda _reason: None)
    identity = {name: target_request[name] for name in ("installation_digest",
        "qualification_ref", "binding_revision_ref", "purpose_ref", "actor_ref", "grant_refs")}
    query = canonical_provider_request("status", {"operation_ref": target.as_dict()},
        identity=identity, deadline_at=FUTURE)
    retained = controller.observe_status(query, semantic_key=query["idempotency_key"],
        observed_at=PORT_STAMP, created_at_utc=STAMP)
    rotated = replace(authority, current_connection={**authority.current_connection,
                                                       "revision_digest": "f" * 64})
    restarted = ProviderSemanticOperationController(domain, ledger=ledger, config_ref=config,
        core_boot_id=str(uuid4()), authority=rotated)
    assert restarted.observe_status(query, semantic_key=query["idempotency_key"],
        observed_at=PORT_STAMP_1, created_at_utc=STAMP) == retained
    unauthorized = deepcopy(query)
    unauthorized["actor_ref"] = ref()
    with pytest.raises(Exception):
        restarted.observe_status(unauthorized, semantic_key=unauthorized["idempotency_key"],
            observed_at=PORT_STAMP_1, created_at_utc=STAMP)
