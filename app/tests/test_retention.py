"""US7 retention: manual-only core, bounded pruning, explicit deletion.

Core records (originals, alternatives, executions, changes, approvals) have
no expiry and are NEVER auto-deleted — core_mode is `manual_only` and no
other mode exists. Only regenerable cache (14d/1GiB LRU) and sensitive-free
diagnostics (30d/100MiB) prune by policy, an irreplaceable tool observation
can never be classified as cache, and every prune leaves a core event
record of the kinds, window and quantities it removed. Explicit deletion is
a two-step act: a preview states the exact scope, bytes and derived and
approval impact; the deletion must present that exact preview against an
unchanged ledger with an authenticated actor, and it leaves a tombstone —
never a silent hole (operations.md OPS-D04/D05, §RetentionPolicy,
OPS-AC06; T069).
"""

import dataclasses

import pytest

from app.operations.retention import (
    RetentionError,
    delete_items,
    freeze_retention_policy,
    open_retention_ledger,
    preview_deletion,
    prune,
    register_item,
)
from app.tests.test_alternatives import ref

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
    deleted = delete_items(state, preview, actor={
        "actor_id": ACTOR, "authenticated": True,
        "evidence": ref("action_approval", 1703),
    })
    remaining = {entry.item_id for entry in deleted.entries}
    assert "core-with-impact" not in remaining
    tombstone = deleted.tombstones[0]
    assert tombstone.item_id == "core-with-impact"
    assert tombstone.derived_impact == ("preview-1",)
    with pytest.raises(RetentionError):
        # the consumed preview never deletes twice
        delete_items(deleted, preview, actor={
            "actor_id": ACTOR, "authenticated": True,
            "evidence": ref("action_approval", 1703),
        })


def test_deletion_refuses_stale_previews_and_unauthenticated_actors():
    state = ledger()
    preview = preview_deletion(state, ["cache-preview"])
    moved = register_item(state, item("late-item", "cache", created_at=NOW))
    with pytest.raises(RetentionError):
        # the ledger changed since the preview: the scope must be re-shown
        delete_items(moved, preview, actor={
            "actor_id": ACTOR, "authenticated": True,
            "evidence": ref("action_approval", 1703),
        })
    with pytest.raises(RetentionError):
        delete_items(state, preview, actor={
            "actor_id": ACTOR, "authenticated": False,
            "evidence": ref("action_approval", 1703),
        })
    with pytest.raises(RetentionError):
        preview_deletion(state, ["never-registered"])
    with pytest.raises(RetentionError):
        delete_items(state, object(), actor={
            "actor_id": ACTOR, "authenticated": True,
            "evidence": ref("action_approval", 1703),
        })


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
