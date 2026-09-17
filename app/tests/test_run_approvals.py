"""Owner-authorized run approvals: the actual producer of `action_approval`
records for human gates (runtime.md §2 approval edges, §4 awaiting_human;
FR-026 authenticated approval).

Until now `action_approval` records existed only as fixture references.
This service is their real producer: the persistent owner session
(Task 7) is re-authenticated inside the final writer, one immutable
decision per (run, gate node, approval scope) is recorded together with
its `approval.decided` event, exact replay returns the same receipt, and
a caller-declared boolean never substitutes for the record.
"""

from dataclasses import replace
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.services.owner_auth import OwnerAuthError
from app.services.run_approvals import (
    PersistentRunApprovals,
    RunApprovalError,
)
from app.tests.test_extension_candidates_persistent import owner

RUN_ID = "00000000-0000-4000-8000-00000000a001"


def payload(**changes):
    value = {
        "schema_version": "run-approval-command-v1",
        "command_id": str(uuid4()),
        "run_id": RUN_ID,
        "node_id": "owner-gate",
        "approval_scope": "release-output",
        "decision": "approved",
    }
    value.update(changes)
    return value


def counts(domain):
    with domain._connection() as db:
        return tuple(
            db.execute(query).fetchone()[0]
            for query in (
                "SELECT count(*) FROM domain_records WHERE kind='action_approval'",
                "SELECT count(*) FROM api_event_envelopes WHERE event_type='approval.decided'",
            )
        )


def test_authentication_is_checked_before_the_command_is_parsed(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        with pytest.raises(OwnerAuthError):
            # an unauthenticated caller learns nothing about command grammar
            approvals.record(replace(request, csrf_verified=False), {"garbage": True})
        with pytest.raises(OwnerAuthError):
            approvals.record(object(), {"garbage": True})


def test_an_owner_records_one_durable_approval_with_its_event(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        assert approvals.lookup(RUN_ID, "owner-gate", "release-output") is None
        command = payload()
        receipt = approvals.record(request, command)
        assert receipt["command_id"] == command["command_id"]
        assert receipt["state"] == "recorded"
        assert receipt["decision"] == "approved"
        ref = EntityRef.from_dict(receipt["approval_ref"])
        assert ref.kind == "action_approval"
        record = app.state.domain_store.get(ref)
        content = record.body["content"]
        assert content == {
            "schema_version": "run-approval-v1",
            "run_id": RUN_ID,
            "node_id": "owner-gate",
            "approval_scope": "release-output",
            "decision": "approved",
            "command_id": command["command_id"],
            "decided_at_utc": content["decided_at_utc"],
            "event_sequence": content["event_sequence"],
        }
        assert type(content["event_sequence"]) is int
        actor_ref = EntityRef.from_dict(record.body["actor_ref"])
        assert actor_ref.kind == "actor"  # the owner's human actor, never the system root
        assert actor_ref == approvals.lookup(RUN_ID, "owner-gate", "release-output").actor_ref
        assert actor_ref != app.state.domain_store.roots().actor
        assert counts(app.state.domain_store) == (1, 1)
        found = approvals.lookup(RUN_ID, "owner-gate", "release-output")
        assert found.decision == "approved" and found.approval_ref == ref
        assert approvals.lookup(RUN_ID, "owner-gate", "other-scope") is None
        assert approvals.lookup(str(uuid4()), "owner-gate", "release-output") is None


def test_exact_replay_returns_the_same_receipt_and_conflicts_never_overwrite(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        command = payload()
        first = approvals.record(request, command)
        assert approvals.record(request, dict(command)) == first
        assert counts(app.state.domain_store) == (1, 1)
        with pytest.raises(RunApprovalError, match="conflict"):
            approvals.record(request, dict(command, decision="rejected"))
        with pytest.raises(RunApprovalError, match="conflict"):
            approvals.record(request, payload(command_id=str(uuid4()), decision="rejected"))
        assert counts(app.state.domain_store) == (1, 1)
        assert approvals.lookup(RUN_ID, "owner-gate", "release-output").decision == "approved"


@pytest.mark.parametrize("change", [
    {"method": "GET"}, {"csrf_verified": False}, {"origin": None},
    {"host": "evil.example"},
])
def test_only_a_real_mutating_owner_request_can_record(tmp_path, change):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        with pytest.raises(OwnerAuthError):
            approvals.record(replace(request, **change), payload())
        assert counts(app.state.domain_store) == (0, 0)


@pytest.mark.parametrize("change", [
    {"decision": "maybe"}, {"decision": True}, {"run_id": "not-a-uuid"},
    {"node_id": ""}, {"node_id": "../gate"}, {"approval_scope": ""},
    {"schema_version": "run-approval-command-v2"}, {"extra": 1},
    {"command_id": "bad"},
])
def test_the_command_payload_is_closed_and_validated_before_any_write(tmp_path, change):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        value = payload()
        value.update(change)
        if "extra" in change:
            value["extra"] = 1
        with pytest.raises(RunApprovalError, match="invalid"):
            approvals.record(request, value)
        assert counts(app.state.domain_store) == (0, 0)


def test_a_failed_event_write_rolls_back_the_record(tmp_path, monkeypatch):
    from app.services import run_approvals as module

    def failing(*args, **kwargs):
        raise RuntimeError("PRIVATE_FAULT_CANARY")

    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        monkeypatch.setattr(module, "_append_event_in_transaction", failing)
        with pytest.raises(RunApprovalError) as caught:
            approvals.record(request, payload())
        assert "PRIVATE_FAULT_CANARY" not in str(caught.value)
        assert counts(app.state.domain_store) == (0, 0)
        assert approvals.lookup(RUN_ID, "owner-gate", "release-output") is None


def test_the_service_binds_the_exact_store_and_authority(tmp_path):
    from app.domain.store import DomainStore

    with owner(tmp_path) as (app, _client, _request, _profile, _arguments):
        with pytest.raises(RunApprovalError):
            PersistentRunApprovals(DomainStore(app.state.store), app.state.owner_authority)
        with pytest.raises(RunApprovalError):
            PersistentRunApprovals(app.state.domain_store, object())


# --- independent review closures (2026-09-17) ---------------------------------


def test_f3_lookup_pins_version_one_and_the_owner_actor(tmp_path):
    from app.domain.schemas import ImmutableRecord
    from app.services.run_approvals import approval_identity

    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        approvals.record(request, payload(decision="rejected"))
        domain = app.state.domain_store
        roots = domain.roots()
        identity = approval_identity(RUN_ID, "owner-gate", "release-output")

        def forged(version, actor_ref):
            return ImmutableRecord.create(
                kind="action_approval", id=identity, version=version,
                created_at_utc="2026-09-17T00:00:00.000000Z", actor_ref=actor_ref,
                parent_refs=(), purpose="operational",
                access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={"schema_version": "run-approval-v1", "run_id": RUN_ID,
                         "node_id": "owner-gate", "approval_scope": "release-output",
                         "decision": "approved", "command_id": str(uuid4()),
                         "decided_at_utc": "2026-09-17T00:00:00.000000Z", "event_sequence": 1},
            )

        domain.put(forged(2, roots.actor))
        with pytest.raises(RunApprovalError, match="unavailable"):
            approvals.lookup(RUN_ID, "owner-gate", "release-output")
        with pytest.raises(RunApprovalError):
            approvals.record(request, payload())  # never silently repaired either
        # a version-1 record authored by the system root is not owner evidence
        other = approval_identity(RUN_ID, "other-gate", "release-output")
        domain.put(ImmutableRecord.create(
            kind="action_approval", id=other, version=1,
            created_at_utc="2026-09-17T00:00:00.000000Z", actor_ref=roots.actor,
            parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={"schema_version": "run-approval-v1", "run_id": RUN_ID,
                     "node_id": "other-gate", "approval_scope": "release-output",
                     "decision": "approved", "command_id": str(uuid4()),
                     "decided_at_utc": "2026-09-17T00:00:00.000000Z", "event_sequence": 1},
        ))
        with pytest.raises(RunApprovalError, match="unavailable"):
            approvals.lookup(RUN_ID, "other-gate", "release-output")


def test_f5_the_approval_identity_is_delimiter_proof():
    from app.services.run_approvals import approval_identity

    assert approval_identity(RUN_ID, "a:b", "c") != approval_identity(RUN_ID, "a", "b:c")
    assert approval_identity(RUN_ID, "a.b", "c") != approval_identity(RUN_ID, "a", "b.c")
