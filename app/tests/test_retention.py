"""US7 retention: manual-only core, bounded pruning, explicit deletion.

Core records (originals, alternatives, executions, changes, approvals) have
no expiry and are NEVER auto-deleted — core_mode is `manual_only` and no
other mode exists. Only regenerable cache (14d/1GiB LRU) and sensitive-free
diagnostics (30d/100MiB) prune by policy, an irreplaceable tool observation
can never be classified as cache, and every prune leaves a core event
record of the kinds, window and quantities it removed. Explicit deletion is
a two-step act: a preview states the exact scope, bytes and derived and
approval impact; the deletion must present that exact preview against an
unchanged ledger together with the owner's recorded decision over exactly
that preview and reason (never a caller-declared actor), and it leaves a
tombstone — never a silent hole (operations.md OPS-D04/D05,
§RetentionPolicy, OPS-AC06; T069).
"""

import dataclasses

import pytest

from app.operations.retention import (
    RetentionError,
    delete_items,
    deletion_subject,
    freeze_retention_policy,
    open_retention_ledger,
    preview_deletion,
    prune,
    register_item,
)
from app.services.owner_decisions import OwnerDecision
from app.tests.owner_session import OwnerSession
from app.tests.test_alternatives import ref

SESSION = OwnerSession("retention-owner")
retention_owner = SESSION.fixture()


def deletion_approval(preview, reason_code="user_requested", decision="approve",
                      subject_kind="deletion"):
    return SESSION.decide(subject_kind, deletion_subject(preview, reason_code), decision)

NOW = "2026-09-13T12:00:00.000000Z"
OLD = "2026-08-01T00:00:00.000000Z"
ACTOR = "00000000-0000-4000-8000-00000000a201"


def policy(**overrides):
    value = {
        "policy_id": "default-retention",
        "version": 1,
        "core_mode": "manual_only",
        "cache_max_age_days": 14,
        "cache_max_bytes": 1_073_741_824,
        "diagnostics_max_age_days": 30,
        "diagnostics_max_bytes": 104_857_600,
        "effective_at": OLD,
        "actor_ref": ref("actor", 1701),
    }
    value.update(overrides)
    return freeze_retention_policy(value)


def item(item_id, classification, *, created_at=OLD, byte_length=1_000,
         irreplaceable=False, derived_ids=(), approval_refs=()):
    return {
        "item_id": item_id,
        "classification": classification,
        "byte_length": byte_length,
        "created_at": created_at,
        "irreplaceable_observation": irreplaceable,
        "derived_ids": list(derived_ids),
        "approval_refs": list(approval_refs),
    }


def ledger():
    state = open_retention_ledger()
    state = register_item(state, item("core-original", "core"))
    state = register_item(state, item("cache-preview", "cache"))
    state = register_item(state, item(
        "cache-fresh", "cache", created_at=NOW,
    ))
    state = register_item(state, item("diag-log", "diagnostics"))
    return state


def test_core_mode_is_manual_only_and_nothing_else():
    assert policy().core_mode == "manual_only"
    with pytest.raises(RetentionError):
        policy(core_mode="auto_after_90_days")
    with pytest.raises(RetentionError):
        policy(cache_max_age_days=0)


def test_irreplaceable_observations_are_never_cache():
    state = open_retention_ledger()
    with pytest.raises(RetentionError):
        register_item(state, item(
            "tool-snapshot", "cache", irreplaceable=True,
        ))
    kept = register_item(state, item(
        "tool-snapshot", "core", irreplaceable=True,
    ))
    assert kept.entries[0].classification == "core"


def test_pruning_touches_only_cache_and_diagnostics_and_reports():
    state, report = prune(ledger(), policy(), now=NOW)
    remaining = {entry.item_id for entry in state.entries}
    assert "core-original" in remaining  # core is NEVER auto-deleted
    assert "cache-fresh" in remaining    # inside the age window
    assert "cache-preview" not in remaining
    assert "diag-log" not in remaining
    # the prune leaves a core event record of what it removed
    assert report.pruned == (
        ("cache", 1, 1_000),
        ("diagnostics", 1, 1_000),
    )
    assert report.window_days == (14, 30)


def test_byte_caps_prune_lru_within_the_window():
    state = open_retention_ledger()
    state = register_item(state, item(
        "cache-old", "cache", created_at="2026-09-10T00:00:00.000000Z",
        byte_length=800,
    ))
    state = register_item(state, item(
        "cache-new", "cache", created_at="2026-09-12T00:00:00.000000Z",
        byte_length=800,
    ))
    tight = policy(cache_max_bytes=1_000)
    pruned, report = prune(state, tight, now=NOW)
    remaining = {entry.item_id for entry in pruned.entries}
    assert remaining == {"cache-new"}  # LRU: the older one went first
    assert report.pruned[0][0] == "cache"


def test_explicit_deletion_needs_the_exact_preview_and_leaves_tombstones():
    state = ledger()
    state = register_item(state, item(
        "core-with-impact", "core",
        derived_ids=("preview-1",), approval_refs=(ref("action_approval", 1702),),
    ))
    preview = preview_deletion(state, ["core-with-impact"])
    assert preview.total_bytes == 1_000
    assert preview.derived_impact == ("preview-1",)
    assert len(preview.approval_impact) == 1
    approval = deletion_approval(preview)
    deleted = delete_items(
        state, preview, approval=approval, reason_code="user_requested",
    )
    remaining = {entry.item_id for entry in deleted.entries}
    assert "core-with-impact" not in remaining
    tombstone = deleted.tombstones[0]
    assert tombstone.item_id == "core-with-impact"
    assert tombstone.derived_impact == ("preview-1",)
    # the tombstone carries the owner's recorded act, nothing caller-declared
    assert tombstone.actor_id == approval.actor_ref.id
    assert tombstone.evidence_ref == approval.approval_ref
    assert tombstone.deleted_at == approval.decided_at_utc
    assert tombstone.deletion_request_id == approval.command_id
    with pytest.raises(RetentionError):
        # the consumed preview never deletes twice
        delete_items(
            deleted, preview, approval=approval, reason_code="user_requested",
        )


def test_deletion_refuses_stale_previews_and_undecided_actors():
    state = ledger()
    preview = preview_deletion(state, ["cache-preview"])
    moved = register_item(state, item("late-item", "cache", created_at=NOW))
    approval = deletion_approval(preview)
    with pytest.raises(RetentionError):
        # the ledger changed since the preview: the scope must be re-shown
        delete_items(moved, preview, approval=approval, reason_code="user_requested")
    with pytest.raises(RetentionError):
        # a caller-declared actor is not evidence
        delete_items(state, preview, approval={
            "actor_id": ACTOR, "authenticated": True,
            "evidence": ref("action_approval", 1703),
        }, reason_code="user_requested")
    with pytest.raises(RetentionError):
        delete_items(state, preview, approval=None, reason_code="user_requested")
    with pytest.raises(RetentionError):
        preview_deletion(state, ["never-registered"])
    with pytest.raises(RetentionError):
        delete_items(state, object(), approval=approval, reason_code="user_requested")


def test_a_decision_binds_this_ledger_and_the_impact_the_human_saw():
    # review: two ledgers with the same item id, bytes and revision but a
    # different shown impact used to share a preview digest, so one owner
    # decision deleted on both. The ledger has an identity and the digest
    # covers the derived/approval impact that the preview displays.
    first = register_item(open_retention_ledger(), item(
        "core-a", "core", derived_ids=("preview-1",),
    ))
    second = register_item(open_retention_ledger(), item(
        "core-a", "core", approval_refs=(ref("action_approval", 1702),),
    ))
    assert first.ledger_id != second.ledger_id
    preview_first = preview_deletion(first, ["core-a"])
    preview_second = preview_deletion(second, ["core-a"])
    assert preview_first.preview_sha != preview_second.preview_sha
    assert preview_first.ledger_id == first.ledger_id
    assert deletion_subject(preview_first, "user_requested")["ledger_id"] == first.ledger_id
    approval = deletion_approval(preview_first)
    with pytest.raises(RetentionError):
        delete_items(second, preview_second, approval=approval, reason_code="user_requested")
    with pytest.raises(RetentionError):
        # a preview of another ledger never applies to this one
        delete_items(second, preview_first, approval=approval, reason_code="user_requested")
    twin = register_item(open_retention_ledger(), item(
        "core-a", "core", derived_ids=("preview-1",),
    ))
    with pytest.raises(RetentionError):
        # byte-identical scope on a different ledger is a different subject
        delete_items(
            twin, preview_deletion(twin, ["core-a"]), approval=approval,
            reason_code="user_requested",
        )
    deleted = delete_items(first, preview_first, approval=approval, reason_code="user_requested")
    assert deleted.ledger_id == first.ledger_id
    assert deleted.tombstones[0].deletion_request_id == approval.command_id


def test_the_owner_decision_must_be_over_this_exact_deletion_subject():
    state = ledger()
    preview = preview_deletion(state, ["cache-preview"])
    other = preview_deletion(state, ["diag-log"])
    subject = deletion_subject(preview, "user_requested")
    assert subject["preview_sha256"] == preview.preview_sha
    assert subject["item_ids"] == ["cache-preview"]
    with pytest.raises(RetentionError):
        deletion_subject(preview, "vibes")
    for wrong in (
        deletion_approval(other),  # another scope
        deletion_approval(preview, reason_code="policy_cleanup"),  # another reason
        deletion_approval(preview, decision="reject"),  # a recorded reject deletes nothing
        deletion_approval(preview, subject_kind="design_approval"),  # another kind
    ):
        with pytest.raises(RetentionError):
            delete_items(state, preview, approval=wrong, reason_code="user_requested")
    with pytest.raises(RetentionError):
        # the reason the human saw is the reason recorded
        delete_items(
            state, preview, approval=deletion_approval(preview), reason_code="policy_cleanup",
        )
    genuine = deletion_approval(preview)
    forged = object.__new__(OwnerDecision)
    for name in OwnerDecision.__slots__:
        object.__setattr__(forged, name, getattr(genuine, name))
    object.__setattr__(forged, "_issuer_token", object())
    with pytest.raises(RetentionError):
        delete_items(state, preview, approval=forged, reason_code="user_requested")
    assert delete_items(
        state, preview, approval=genuine, reason_code="user_requested",
    ).tombstones[0].evidence_ref == genuine.approval_ref


def test_values_are_issued_never_constructed():
    state = ledger()
    with pytest.raises(TypeError):
        dataclasses.replace(state, entries=())
    with pytest.raises(TypeError):
        dataclasses.replace(policy(), core_mode="auto")
    with pytest.raises(RetentionError):
        prune(object(), policy(), now=NOW)
    with pytest.raises(RetentionError):
        register_item(object(), item("x", "cache"))
