"""Owner-authorized promotion approvals: the authoritative evidence behind a
promotion decision (T065 reopened scope; growth.md `PromotionDecision`
"사람의 인증된 명시 결정"; FR-026 authenticated human approval).

`record_promotion_decision` used to accept a caller-declared
`{"authenticated": True}` approver. This service replaces it: the persistent
owner session is re-authenticated inside the final writer, one immutable
`action_approval` record bound to the exact candidate bundle hash and the
expected current environment is written per command, an approve or reject
also appends its `approval.decided` event, and the issued value is the only
thing the promotion constructor accepts.
"""

import dataclasses
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.domain.schemas import ImmutableRecord
from app.domain.store import _writer
from app.services.owner_auth import OwnerAuthError
from app.services.promotion_approvals import (
    PersistentPromotionApprovals,
    PromotionApproval,
    PromotionApprovalError,
    approval_identity,
    is_issued_promotion_approval,
)
from app.services.run_approvals import _stored_owner_actor_ref
from app.services.validation import validation_report_ref
from app.tests.test_alternatives import ref
from app.tests.test_extension_candidates_persistent import owner
from app.tests.test_promotion import CURRENT_ENV, frozen_candidate, passed_report


def payload(candidate, **changes):
    value = {
        "schema_version": "promotion-approval-command-v1",
        "command_id": str(uuid4()),
        "candidate_bundle": candidate.bundle_ref.as_dict(),
        "validation_report": validation_report_ref(passed_report(candidate)).as_dict(),
        "expected_current_environment": CURRENT_ENV,
        "decision": "approve",
    }
    value.update(changes)
    return value


def identity(ref_dict):
    return {key: ref_dict[key] for key in ("id", "version", "sha256")}


def counts(domain):
    with domain._connection() as db:
        return tuple(
            db.execute(query).fetchone()[0]
            for query in (
                "SELECT count(*) FROM domain_records WHERE kind='action_approval'",
                "SELECT count(*) FROM api_event_envelopes WHERE event_type='approval.decided'",
            )
        )


def test_an_owner_records_one_durable_promotion_approval_with_its_event(tmp_path):
    candidate = frozen_candidate()
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentPromotionApprovals(
            app.state.domain_store, app.state.owner_authority
        )
        command = payload(candidate)
        approval = approvals.record(request, command)
        assert is_issued_promotion_approval(approval)
        assert approval.candidate_bundle == candidate.bundle_ref
        assert approval.expected_current_environment == EntityRef.from_dict(CURRENT_ENV)
        assert approval.decision == "approve"
        assert approval.command_id == command["command_id"]
        record = app.state.domain_store.get(approval.approval_ref)
        content = record.body["content"]
        # bindings are exact identities (id, version, sha256), not stored-record
        # references: the bundle's and report's records may not exist yet
        assert approval.validation_report == EntityRef.from_dict(
            command["validation_report"]
        )
        assert content == {
            "schema_version": "promotion-approval-v1",
            "candidate_bundle": identity(candidate.bundle_ref.as_dict()),
            "validation_report": identity(command["validation_report"]),
            "expected_current_environment": identity(CURRENT_ENV),
            "decision": "approve",
            "command_id": command["command_id"],
            "decided_at_utc": approval.decided_at_utc,
            "event_sequence": content["event_sequence"],
        }
        assert type(content["event_sequence"]) is int
        actor_ref = EntityRef.from_dict(record.body["actor_ref"])
        assert actor_ref == approval.actor_ref
        assert actor_ref.kind == "actor"
        assert actor_ref != app.state.domain_store.roots().actor
        assert counts(app.state.domain_store) == (1, 1)
        with app.state.domain_store._connection() as db:
            envelope = db.execute(
                "SELECT envelope FROM api_event_envelopes WHERE event_type='approval.decided'"
            ).fetchone()[0]
        assert b'"approved"' in envelope  # the closed catalog value, not "approve"
        # resolving the exact reference yields the same issued evidence
        resolved = approvals.resolve(approval.approval_ref)
        assert is_issued_promotion_approval(resolved)
        assert resolved == approval


def test_a_deferral_is_recorded_without_deciding_the_approval(tmp_path):
    candidate = frozen_candidate()
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentPromotionApprovals(
            app.state.domain_store, app.state.owner_authority
        )
        deferred = approvals.record(request, payload(candidate, decision="defer"))
        assert deferred.decision == "defer"
        content = app.state.domain_store.get(deferred.approval_ref).body["content"]
        assert content["event_sequence"] is None
        assert counts(app.state.domain_store) == (1, 0)
        rejected = approvals.record(request, payload(candidate, decision="reject"))
        assert rejected.decision == "reject"
        assert rejected.approval_ref != deferred.approval_ref
        assert counts(app.state.domain_store) == (2, 1)


def test_exact_replay_returns_the_same_approval_and_conflicts_never_overwrite(tmp_path):
    candidate = frozen_candidate()
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentPromotionApprovals(
            app.state.domain_store, app.state.owner_authority
        )
        command = payload(candidate)
        first = approvals.record(request, command)
        assert approvals.record(request, dict(command)) == first
        assert counts(app.state.domain_store) == (1, 1)
        with pytest.raises(PromotionApprovalError, match="conflict"):
            approvals.record(
                request,
                payload(candidate, command_id=command["command_id"], decision="reject"),
            )
        with pytest.raises(PromotionApprovalError, match="conflict"):
            approvals.record(
                request,
                payload(
                    frozen_candidate(prompts=ref("artifact", 999)),
                    command_id=command["command_id"],
                ),
            )
        assert counts(app.state.domain_store) == (1, 1)
        # a new command for the same bundle after the environment moved is a
        # fresh decision (G-13 re-approval), never a rewrite of the first
        again = approvals.record(
            request,
            payload(candidate, expected_current_environment=ref("environment", 984)),
        )
        assert again.approval_ref != first.approval_ref
        assert counts(app.state.domain_store) == (2, 2)


def test_only_the_authenticated_owner_session_can_record(tmp_path):
    candidate = frozen_candidate()
    with owner(tmp_path) as (app, client, request, _profile, _arguments):
        approvals = PersistentPromotionApprovals(
            app.state.domain_store, app.state.owner_authority
        )
        with pytest.raises(OwnerAuthError):
            approvals.record(
                dataclasses.replace(request, csrf_verified=False), payload(candidate)
            )
        with pytest.raises(OwnerAuthError):
            approvals.record(
                dataclasses.replace(request, method="GET"), payload(candidate)
            )
        with pytest.raises(OwnerAuthError):
            approvals.record(object(), payload(candidate))
        authority = app.state.owner_authority
        authority.logout(
            request,
            command_id=str(uuid4()),
            token_b64u=client.cookies[authority.cookie_name],
        )
        with pytest.raises(OwnerAuthError):
            approvals.record(request, payload(candidate))
        assert counts(app.state.domain_store) == (0, 0)


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": "run-approval-command-v1"},
        {"decision": "approved"},
        {"decision": None},
        {"command_id": "not-a-uuid"},
        {"candidate_bundle": "sha-only"},
        {"validation_report": CURRENT_ENV},  # an environment is not a report
        {
            "candidate_bundle": {
                "kind": "artifact",
                "id": CURRENT_ENV["id"],
                "version": 1,
                "sha256": "0" * 64,
            }
        },
        {
            "expected_current_environment": {
                "kind": "environment",
                "id": CURRENT_ENV["id"],
                "version": 1,
            }
        },
        {"extra": True},
    ],
)
def test_invalid_commands_are_refused_before_any_write(tmp_path, changes):
    candidate = frozen_candidate()
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentPromotionApprovals(
            app.state.domain_store, app.state.owner_authority
        )
        value = payload(candidate)
        value.update(changes)
        with pytest.raises(PromotionApprovalError, match="invalid"):
            approvals.record(request, value)
        assert counts(app.state.domain_store) == (0, 0)


def test_authentication_is_checked_before_the_command_is_parsed(tmp_path):
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentPromotionApprovals(
            app.state.domain_store, app.state.owner_authority
        )
        with pytest.raises(OwnerAuthError):
            # an unauthenticated caller learns nothing about command grammar
            approvals.record(
                dataclasses.replace(request, csrf_verified=False), {"garbage": True}
            )
        with pytest.raises(OwnerAuthError):
            approvals.record(object(), {"garbage": True})


def stored_content(candidate, **changes):
    content = {
        "schema_version": "promotion-approval-v1",
        "candidate_bundle": identity(candidate.bundle_ref.as_dict()),
        "validation_report": identity(
            validation_report_ref(passed_report(candidate)).as_dict()
        ),
        "expected_current_environment": identity(CURRENT_ENV),
        "decision": "defer",
        "command_id": str(uuid4()),
        "decided_at_utc": "2026-09-17T00:00:00.000000Z",
        "event_sequence": None,
    }
    content.update(changes)
    return {key: item for key, item in content.items() if item is not ...}


def write_owner_record(domain, record_id, content):
    with _writer(), domain._connection(write=True) as db:
        roots = domain._read_roots(db)
        record = ImmutableRecord.create(
            kind="action_approval",
            id=record_id,
            version=1,
            created_at_utc="2026-09-17T00:00:00.000000Z",
            actor_ref=EntityRef.from_dict(_stored_owner_actor_ref(db)),
            parent_refs=(),
            purpose="operational",
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content=content,
        )
        domain._put_in_transaction(db, record)
    return record.ref


RANDOM_IDENTITY = object()


@pytest.mark.parametrize(
    "changes",
    [
        {"decision": "auto_approve"},
        {"decision": "approved"},
        {"command_id": "not-a-uuid"},
        {"decided_at_utc": "2026-09-17T00:00:00Z"},
        {"event_sequence": ...},  # missing key
        {"note": "extra key"},
        {"candidate_bundle": {"id": CURRENT_ENV["id"], "sha256": "0" * 64}},
        {
            "validation_report": {
                "id": CURRENT_ENV["id"],
                "version": 1,
                "sha256": "Z" * 64,
            }
        },
        {"decision": "defer", "event_sequence": 3},  # a defer decides no event
        {"decision": "approve"},  # an approve names its decided event
        {"decision": "approve", "event_sequence": 1},  # sequence 1 is owner.created
        {"decision": "approve", "event_sequence": 999},  # no such event
        {
            RANDOM_IDENTITY: True
        },  # sound content at an identity not derived from its command
    ],
)
def test_resolve_refuses_malformed_records_even_from_the_owner(tmp_path, changes):
    # trust is the writer's grammar, not the record's schema_version label:
    # a record the owner's actor authored with malformed content never
    # resolves into an issued approval, even at the right identity
    candidate = frozen_candidate()
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        domain = app.state.domain_store
        approvals = PersistentPromotionApprovals(domain, app.state.owner_authority)
        random_identity = changes.pop(RANDOM_IDENTITY, False)
        content = stored_content(candidate, **changes)
        record_id = (
            str(uuid4())
            if random_identity
            else approval_identity(content["command_id"])
        )
        ref = write_owner_record(domain, record_id, content)
        with pytest.raises(PromotionApprovalError, match="unavailable"):
            approvals.resolve(ref)
        # a well-formed defer written the same direct way at its derived
        # identity does resolve, so the refusals above are the content and
        # identity checks, not the direct write
        sound = stored_content(candidate)
        assert is_issued_promotion_approval(
            approvals.resolve(
                write_owner_record(
                    domain, approval_identity(sound["command_id"]), sound
                )
            )
        )
        # and the writer's own approve still resolves with its real event
        recorded = approvals.record(request, payload(candidate))
        assert approvals.resolve(recorded.approval_ref) == recorded


def test_values_are_issued_never_constructed_and_resolve_is_exact(tmp_path):
    candidate = frozen_candidate()
    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = PersistentPromotionApprovals(
            app.state.domain_store, app.state.owner_authority
        )
        approval = approvals.record(request, payload(candidate))
        with pytest.raises(TypeError):
            dataclasses.replace(approval, decision="approve")
        with pytest.raises(TypeError):
            PromotionApproval(
                candidate_bundle=candidate.bundle_ref,
                validation_report=approval.validation_report,
                expected_current_environment=EntityRef.from_dict(CURRENT_ENV),
                decision="approve",
                command_id=approval.command_id,
                approval_ref=approval.approval_ref,
                actor_ref=approval.actor_ref,
                decided_at_utc=approval.decided_at_utc,
            )
        assert not is_issued_promotion_approval(object())
        with pytest.raises(PromotionApprovalError):
            approvals.resolve(ref("action_approval", 982))  # unknown record
        with pytest.raises(PromotionApprovalError):
            approvals.resolve(
                dataclasses.replace(approval.approval_ref, sha256="0" * 64)
            )  # a forged hash never resolves
        with pytest.raises(PromotionApprovalError):
            approvals.resolve(
                approval.approval_ref.as_dict()
            )  # an exact EntityRef only
        with pytest.raises(PromotionApprovalError):
            PersistentPromotionApprovals(object(), app.state.owner_authority)
