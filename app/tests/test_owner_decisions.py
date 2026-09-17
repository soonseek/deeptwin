"""Owner decisions over an exact subject digest: the shared producer of
`action_approval` evidence for value-level approvals that are not run gates
or promotions (first consumer: design approval, T036/FR-008).

The persistent owner session is re-authenticated inside the final writer;
one immutable record per command stores the closed subject kind, the exact
subject the human saw (a JSON object that can contain no stored-record
reference) and its canonical digest; approve/reject append
`approval.decided`; the issued value is the only thing a consumer accepts.
"""

import dataclasses
from hashlib import sha256
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef, canonical_json
from app.services.owner_auth import OwnerAuthError
from app.services.owner_decisions import (
    SUBJECT_KINDS,
    OwnerDecision,
    OwnerDecisionError,
    PersistentOwnerDecisions,
    is_issued_owner_decision,
)
from app.tests.test_extension_candidates_persistent import owner

SUBJECT = {
    "environment_id": "00000000-0000-4000-8000-00000000e001",
    "design": {
        "id": "00000000-0000-4000-8000-00000000d001",
        "version": 2,
        "sha256": "a" * 64,
    },
    "verdict_sha256": "b" * 64,
    "candidate_version": 1,
}


def payload(**changes):
    value = {
        "schema_version": "owner-decision-command-v1",
        "command_id": str(uuid4()),
        "subject_kind": "design_approval",
        "subject": SUBJECT,
        "decision": "approve",
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


def test_an_owner_records_one_durable_decision_over_the_exact_subject(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        decisions = PersistentOwnerDecisions(
            app.state.domain_store, app.state.owner_authority
        )
        command = payload()
        decision = decisions.record(request, command)
        assert is_issued_owner_decision(decision)
        assert decision.subject_kind == "design_approval"
        assert decision.subject == SUBJECT
        assert decision.subject_sha256 == sha256(canonical_json(SUBJECT)).hexdigest()
        assert decision.decision == "approve"
        assert decision.command_id == command["command_id"]
        record = app.state.domain_store.get(decision.approval_ref)
        content = record.body["content"]
        assert content == {
            "schema_version": "owner-decision-v1",
            "subject_kind": "design_approval",
            "subject": SUBJECT,
            "subject_sha256": decision.subject_sha256,
            "decision": "approve",
            "command_id": command["command_id"],
            "decided_at_utc": decision.decided_at_utc,
            "event_sequence": content["event_sequence"],
        }
        assert type(content["event_sequence"]) is int
        actor_ref = EntityRef.from_dict(record.body["actor_ref"])
        assert actor_ref == decision.actor_ref and actor_ref.kind == "actor"
        assert actor_ref != app.state.domain_store.roots().actor
        assert counts(app.state.domain_store) == (1, 1)
        assert decisions.resolve(decision.approval_ref) == decision
        # the subject the value carries is read-only and a copy of the input
        with pytest.raises(TypeError):
            decision.subject["candidate_version"] = 9
        assert decision.subject == SUBJECT
        assert decisions.resolve(decision.approval_ref).subject == SUBJECT


def test_replay_is_exact_and_conflicts_never_overwrite(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        decisions = PersistentOwnerDecisions(
            app.state.domain_store, app.state.owner_authority
        )
        command = payload()
        first = decisions.record(request, command)
        assert decisions.record(request, dict(command)) == first
        with pytest.raises(OwnerDecisionError, match="conflict"):
            decisions.record(
                request, payload(command_id=command["command_id"], decision="reject")
            )
        with pytest.raises(OwnerDecisionError, match="conflict"):
            decisions.record(
                request,
                payload(
                    command_id=command["command_id"],
                    subject=SUBJECT | {"candidate_version": 2},
                ),
            )
        assert counts(app.state.domain_store) == (1, 1)
        rejected = decisions.record(request, payload(decision="reject"))
        assert (
            rejected.decision == "reject"
            and rejected.approval_ref != first.approval_ref
        )
        assert counts(app.state.domain_store) == (2, 2)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "promotion-approval-command-v1"},
        {"subject_kind": "run_gate"},
        {"decision": "defer"},
        {"decision": "approved"},
        {"command_id": "not-a-uuid"},
        {"subject": []},
        {"subject": {}},
        {
            "subject": {
                "design": {
                    "kind": "graph",
                    "id": SUBJECT["environment_id"],
                    "version": 1,
                    "sha256": "a" * 64,
                }
            }
        },
        {"subject": {"design_ref": {"id": SUBJECT["environment_id"]}}},
        {"subject": {"evidence_refs": []}},
        {"subject": {"nested": [{"inner_ref": 1}]}},
        {
            "subject": {
                "note": {
                    "vault_id": SUBJECT["environment_id"],
                    "purpose": "operational",
                    "sha256": "a" * 64,
                    "size": 1,
                }
            }
        },  # a blob-reference shape would be indexed by the store
        {"subject": {"value": 1.5}},  # canonical JSON carries no floats
        {"subject": {"value": float("nan")}},
        {"subject": {"value": b"bytes"}},
        {"subject": {"value": "x" * 70_000}},
        {"extra": True},
    ],
)
def test_invalid_commands_are_refused_before_any_write(tmp_path, changes):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        decisions = PersistentOwnerDecisions(
            app.state.domain_store, app.state.owner_authority
        )
        with pytest.raises(OwnerDecisionError, match="invalid"):
            decisions.record(request, payload(**changes))
        assert counts(app.state.domain_store) == (0, 0)


def test_only_the_authenticated_owner_session_can_record_and_auth_comes_first(tmp_path):
    with owner(tmp_path) as (app, client, request, _profile, _arguments):
        decisions = PersistentOwnerDecisions(
            app.state.domain_store, app.state.owner_authority
        )
        with pytest.raises(OwnerAuthError):
            decisions.record(
                dataclasses.replace(request, csrf_verified=False), {"garbage": True}
            )
        with pytest.raises(OwnerAuthError):
            decisions.record(dataclasses.replace(request, method="GET"), payload())
        with pytest.raises(OwnerAuthError):
            decisions.record(object(), payload())
        authority = app.state.owner_authority
        authority.logout(
            request,
            command_id=str(uuid4()),
            token_b64u=client.cookies[authority.cookie_name],
        )
        with pytest.raises(OwnerAuthError):
            decisions.record(request, payload())
        assert counts(app.state.domain_store) == (0, 0)


def test_resolve_requires_the_decided_event_of_this_very_command(tmp_path):
    from app.domain.schemas import ImmutableRecord
    from app.domain.store import _writer
    from app.services.owner_decisions import decision_identity
    from app.services.run_approvals import _stored_owner_actor_ref

    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        domain = app.state.domain_store
        decisions = PersistentOwnerDecisions(domain, app.state.owner_authority)
        genuine = decisions.record(request, payload())
        borrowed = domain.get(genuine.approval_ref).body["content"]["event_sequence"]
        # an owner-authored record at its derived identity that names another
        # command's approval.decided event never resolves
        command_id = str(uuid4())
        content = {
            "schema_version": "owner-decision-v1",
            "subject_kind": "design_approval",
            "subject": SUBJECT,
            "subject_sha256": genuine.subject_sha256,
            "decision": "approve",
            "command_id": command_id,
            "decided_at_utc": genuine.decided_at_utc,
            "event_sequence": borrowed,
        }
        with _writer(), domain._connection(write=True) as db:
            roots = domain._read_roots(db)
            record = ImmutableRecord.create(
                kind="action_approval",
                id=decision_identity(command_id),
                version=1,
                created_at_utc=genuine.decided_at_utc,
                actor_ref=EntityRef.from_dict(_stored_owner_actor_ref(db)),
                parent_refs=(),
                purpose="operational",
                access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content=content,
            )
            domain._put_in_transaction(db, record)
        with pytest.raises(OwnerDecisionError, match="unavailable"):
            decisions.resolve(record.ref)
        assert decisions.resolve(genuine.approval_ref) == genuine


def test_values_are_issued_never_constructed_and_resolve_is_exact(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        decisions = PersistentOwnerDecisions(
            app.state.domain_store, app.state.owner_authority
        )
        decision = decisions.record(request, payload())
        with pytest.raises(TypeError):
            dataclasses.replace(decision, decision="approve")
        with pytest.raises(TypeError):
            OwnerDecision(
                subject_kind="design_approval",
                subject=SUBJECT,
                subject_sha256=decision.subject_sha256,
                decision="approve",
                command_id=decision.command_id,
                approval_ref=decision.approval_ref,
                actor_ref=decision.actor_ref,
                decided_at_utc=decision.decided_at_utc,
            )
        assert not is_issued_owner_decision(object())
        assert "design_approval" in SUBJECT_KINDS
        with pytest.raises(OwnerDecisionError):
            decisions.resolve(
                dataclasses.replace(decision.approval_ref, sha256="0" * 64)
            )
        with pytest.raises(OwnerDecisionError):
            decisions.resolve(decision.approval_ref.as_dict())
        with pytest.raises(OwnerDecisionError):
            PersistentOwnerDecisions(object(), app.state.owner_authority)
        assert decisions.bound_to(app.state.domain_store)
        assert not decisions.bound_to(object())
