"""Retention: manual-only core, bounded pruning, explicit deletion
(US7, T069; operations.md OPS-D04/D05, RetentionPolicy, OPS-AC06).

Core records have no expiry and are NEVER auto-deleted: `core_mode` is
``manual_only`` and no other mode exists. Only regenerable cache
(age/byte-capped, LRU) and sensitive-free diagnostics prune by policy; an
irreplaceable tool observation can never be classified as cache; and every
prune returns a report of the kinds, windows and quantities it removed —
the record the caller must persist as a core event. Byte-cap eviction is
oldest-created-first: this value layer records no access times, so it is a
creation-order approximation of the contract's LRU — the access layer owns
real usage recency and may re-touch entries by re-registering derived ones. Explicit deletion is a
two-step human act: `preview_deletion` states the exact scope, bytes and
derived/approval impact against the ledger's current revision;
`delete_items` must present that exact preview against the unchanged
ledger with an authenticated actor, and it leaves tombstones — never a
silent hole. Values are issued, never constructed; storage owns the
single-writer transaction as with the other ledgers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256

from ..domain.refs import DomainContractError, EntityRef, canonical_json

CLASSIFICATIONS = frozenset({"core", "cache", "diagnostics"})
DELETION_REASONS = frozenset({
    "user_requested", "policy_cleanup", "rights_request", "migration",
})
_PRUNABLE = ("cache", "diagnostics")
_STAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z\Z"
)
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_ISSUE_TOKEN = object()


class RetentionError(ValueError):
    """A policy, ledger operation, prune or deletion is invalid."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kind, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise RetentionError(f"invalid {label} reference") from exc
    if result.kind != kind:
        raise RetentionError(f"invalid {label} reference kind")
    return result


def _stamp(value, label):
    if type(value) is not str or _STAMP.fullmatch(value) is None:
        raise RetentionError(f"{label} must be a canonical UTC timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")  # noqa: DTZ007
    except ValueError as exc:
        raise RetentionError(f"{label} must be a canonical UTC timestamp") from exc


@dataclass(frozen=True, slots=True, init=False)
class RetentionPolicy:
    """The frozen retention contract; core is manual-only, always."""

    policy_id: str
    version: int
    core_mode: str
    cache_max_age_days: int
    cache_max_bytes: int
    diagnostics_max_age_days: int
    diagnostics_max_bytes: int
    effective_at: str
    actor_ref: EntityRef
    _issuer_token: object = field(repr=False, compare=False)


def freeze_retention_policy(value) -> RetentionPolicy:
    if type(value) is not dict or set(value) != {
        "policy_id", "version", "core_mode", "cache_max_age_days",
        "cache_max_bytes", "diagnostics_max_age_days",
        "diagnostics_max_bytes", "effective_at", "actor_ref",
    }:
        raise RetentionError("expected the exact retention policy object")
    if value["core_mode"] != "manual_only":
        # No other core mode exists: core records never expire.
        raise RetentionError("core retention is manual_only, always")
    policy_id = value["policy_id"]
    if type(policy_id) is not str or not 1 <= len(policy_id) <= 128:
        raise RetentionError("policy id is out of bounds")
    version = value["version"]
    if type(version) is not int or not 1 <= version <= 1_000_000:
        raise RetentionError("policy version is out of bounds")
    numbers = {}
    for name, ceiling in (
        ("cache_max_age_days", 3650),
        ("cache_max_bytes", 2 ** 40),
        ("diagnostics_max_age_days", 3650),
        ("diagnostics_max_bytes", 2 ** 40),
    ):
        item = value[name]
        if type(item) is not int or not 1 <= item <= ceiling:
            raise RetentionError(f"{name} is out of bounds")
        numbers[name] = item
    _stamp(value["effective_at"], "effective time")
    return _issue(
        RetentionPolicy,
        policy_id=policy_id,
        version=version,
        core_mode="manual_only",
        effective_at=value["effective_at"],
        actor_ref=_ref(value["actor_ref"], "actor", "actor"),
        _issuer_token=_ISSUE_TOKEN,
        **numbers,
    )


@dataclass(frozen=True, slots=True, init=False)
class RetentionEntry:
    """One retained item's classification and impact links."""

    item_id: str
    classification: str
    byte_length: int
    created_at: str
    irreplaceable_observation: bool
    derived_ids: tuple[str, ...]
    approval_refs: tuple[EntityRef, ...]


@dataclass(frozen=True, slots=True, init=False)
class Tombstone:
    """The durable mark an explicit deletion leaves behind."""

    item_id: str
    classification: str
    byte_length: int
    actor_id: str
    evidence_ref: EntityRef
    deleted_at: str
    deletion_request_id: str
    reason_code: str
    derived_impact: tuple[str, ...]
    approval_impact: tuple[EntityRef, ...]


@dataclass(frozen=True, slots=True, init=False)
class RetentionLedger:
    """One ledger value; evolution only through the module functions."""

    entries: tuple[RetentionEntry, ...]
    tombstones: tuple[Tombstone, ...]
    revision: int
    _issuer_token: object = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True, init=False)
class PruneReport:
    """What a prune actually removed — the caller's core event record."""

    pruned: tuple[tuple[str, int, int], ...]  # (classification, count, bytes)
    window_days: tuple[int, int]


@dataclass(frozen=True, slots=True, init=False)
class DeletionPreview:
    """The exact scope an explicit deletion will remove, shown first."""

    item_ids: tuple[str, ...]
    total_bytes: int
    derived_impact: tuple[str, ...]
    approval_impact: tuple[EntityRef, ...]
    ledger_revision: int
    preview_sha: str
    _issuer_token: object = field(repr=False, compare=False)


def _require_ledger(value) -> None:
    if (
        type(value) is not RetentionLedger
        or getattr(value, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise RetentionError("a framework-issued retention ledger is required")


def open_retention_ledger() -> RetentionLedger:
    return _issue(
        RetentionLedger, entries=(), tombstones=(), revision=1,
        _issuer_token=_ISSUE_TOKEN,
    )


def register_item(ledger, value) -> RetentionLedger:
    _require_ledger(ledger)
    if type(value) is not dict or set(value) != {
        "item_id", "classification", "byte_length", "created_at",
        "irreplaceable_observation", "derived_ids", "approval_refs",
    }:
        raise RetentionError("expected the exact retention item object")
    item_id = value["item_id"]
    if type(item_id) is not str or not 1 <= len(item_id) <= 128:
        raise RetentionError("item id is out of bounds")
    if any(entry.item_id == item_id for entry in ledger.entries):
        raise RetentionError("an item id registers exactly once")
    classification = value["classification"]
    if classification not in CLASSIFICATIONS:
        raise RetentionError("unknown retention classification")
    irreplaceable = value["irreplaceable_observation"]
    if type(irreplaceable) is not bool:
        raise RetentionError("the irreplaceable flag must be explicit")
    if irreplaceable and classification != "core":
        # A tool observation that cannot be re-obtained is evidence, never
        # a regenerable cache (OPS-D05).
        raise RetentionError(
            "an irreplaceable observation can never be cache or diagnostics"
        )
    byte_length = value["byte_length"]
    if type(byte_length) is not int or not 0 <= byte_length <= 2 ** 40:
        raise RetentionError("byte length is out of bounds")
    _stamp(value["created_at"], "created time")
    derived = value["derived_ids"]
    if type(derived) is not list or len(derived) > 64 or any(
        type(item) is not str or not 1 <= len(item) <= 128 for item in derived
    ):
        raise RetentionError("derived ids are out of bounds")
    approvals_value = value["approval_refs"]
    if type(approvals_value) is not list or len(approvals_value) > 32:
        raise RetentionError("approval refs are out of bounds")
    approvals = tuple(
        _ref(item, "action_approval", "approval") for item in approvals_value
    )
    entry = _issue(
        RetentionEntry,
        item_id=item_id,
        classification=classification,
        byte_length=byte_length,
        created_at=value["created_at"],
        irreplaceable_observation=irreplaceable,
        derived_ids=tuple(derived),
        approval_refs=approvals,
    )
    return _issue(
        RetentionLedger,
        entries=(*ledger.entries, entry),
        tombstones=ledger.tombstones,
        revision=ledger.revision + 1,
        _issuer_token=_ISSUE_TOKEN,
    )


def prune(ledger, policy, *, now):
    """Prune ONLY cache/diagnostics per policy; report what was removed."""

    _require_ledger(ledger)
    if (
        type(policy) is not RetentionPolicy
        or getattr(policy, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise RetentionError("a frozen retention policy is required")
    moment = _stamp(now, "prune time")
    limits = {
        "cache": (policy.cache_max_age_days, policy.cache_max_bytes),
        "diagnostics": (
            policy.diagnostics_max_age_days, policy.diagnostics_max_bytes,
        ),
    }
    keep: list[RetentionEntry] = []
    removed: dict[str, list[RetentionEntry]] = {"cache": [], "diagnostics": []}
    survivors: dict[str, list[RetentionEntry]] = {
        "cache": [], "diagnostics": [],
    }
    for entry in ledger.entries:
        if entry.classification == "core":
            keep.append(entry)  # core is NEVER auto-deleted
            continue
        age_days, _cap = limits[entry.classification]
        created = _stamp(entry.created_at, "created time")
        if moment - created > timedelta(days=age_days):
            removed[entry.classification].append(entry)
        else:
            survivors[entry.classification].append(entry)
    for classification, (_age, cap) in limits.items():
        pool = sorted(survivors[classification], key=lambda e: e.created_at)
        total = sum(entry.byte_length for entry in pool)
        while total > cap and pool:
            oldest = pool.pop(0)  # oldest-created eviction (see docstring)
            removed[classification].append(oldest)
            total -= oldest.byte_length
        keep.extend(pool)
    report = _issue(
        PruneReport,
        pruned=tuple(
            (
                classification,
                len(removed[classification]),
                sum(e.byte_length for e in removed[classification]),
            )
            for classification in _PRUNABLE
            if removed[classification]
        ),
        window_days=(
            policy.cache_max_age_days, policy.diagnostics_max_age_days,
        ),
    )
    ordered = tuple(
        entry for entry in ledger.entries if entry in keep
    )
    return _issue(
        RetentionLedger,
        entries=ordered,
        tombstones=ledger.tombstones,
        revision=ledger.revision + 1,
        _issuer_token=_ISSUE_TOKEN,
    ), report


def preview_deletion(ledger, item_ids) -> DeletionPreview:
    """Show the exact scope and impact BEFORE anything is deleted."""

    _require_ledger(ledger)
    if type(item_ids) is not list or not 1 <= len(item_ids) <= 256:
        raise RetentionError("expected a bounded nonempty item list")
    if len(set(item_ids)) != len(item_ids):
        # A duplicated id would inflate the byte total the human is shown.
        raise RetentionError("a deletion scope never repeats an item")
    entries = []
    for item_id in item_ids:
        entry = next(
            (e for e in ledger.entries if e.item_id == item_id), None,
        )
        if entry is None:
            raise RetentionError("an item in the scope does not exist")
        entries.append(entry)
    derived = tuple(
        derived_id for entry in entries for derived_id in entry.derived_ids
    )
    approvals = tuple(
        approval for entry in entries for approval in entry.approval_refs
    )
    payload = {
        "item_ids": list(item_ids),
        "ledger_revision": ledger.revision,
        "total_bytes": sum(entry.byte_length for entry in entries),
    }
    return _issue(
        DeletionPreview,
        item_ids=tuple(item_ids),
        total_bytes=payload["total_bytes"],
        derived_impact=derived,
        approval_impact=approvals,
        ledger_revision=ledger.revision,
        preview_sha=sha256(canonical_json(payload)).hexdigest(),
        _issuer_token=_ISSUE_TOKEN,
    )


def delete_items(
    ledger, preview, *, actor, deleted_at, deletion_request_id, reason_code,
) -> RetentionLedger:
    """Delete exactly the previewed scope, leaving complete tombstones."""

    _require_ledger(ledger)
    if (
        type(preview) is not DeletionPreview
        or getattr(preview, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise RetentionError("a framework-issued deletion preview is required")
    if preview.ledger_revision != ledger.revision:
        # The ledger changed since the human saw the scope: show it again.
        raise RetentionError("the preview is stale; re-show the exact scope")
    if type(actor) is not dict or set(actor) != {
        "actor_id", "authenticated", "evidence",
    }:
        raise RetentionError("expected the exact actor object")
    actor_id = actor["actor_id"]
    if type(actor_id) is not str or _UUID.fullmatch(actor_id) is None:
        raise RetentionError("actor id is not a canonical UUID")
    if actor["authenticated"] is not True:
        raise RetentionError("deletion requires an authenticated actor")
    evidence = _ref(actor["evidence"], "action_approval", "actor evidence")
    _stamp(deleted_at, "deletion time")
    if (
        type(deletion_request_id) is not str
        or _UUID.fullmatch(deletion_request_id) is None
    ):
        raise RetentionError("deletion request id is not a canonical UUID")
    if reason_code not in DELETION_REASONS:
        raise RetentionError("unknown deletion reason")
    scope = set(preview.item_ids)
    tombstones = list(ledger.tombstones)
    kept = []
    for entry in ledger.entries:
        if entry.item_id in scope:
            tombstones.append(_issue(
                Tombstone,
                item_id=entry.item_id,
                classification=entry.classification,
                byte_length=entry.byte_length,
                actor_id=actor_id,
                evidence_ref=evidence,
                deleted_at=deleted_at,
                deletion_request_id=deletion_request_id,
                reason_code=reason_code,
                derived_impact=entry.derived_ids,
                approval_impact=entry.approval_refs,
            ))
            scope.discard(entry.item_id)
        else:
            kept.append(entry)
    if scope:
        raise RetentionError("an item in the scope does not exist")
    return _issue(
        RetentionLedger,
        entries=tuple(kept),
        tombstones=tuple(tombstones),
        revision=ledger.revision + 1,
        _issuer_token=_ISSUE_TOKEN,
    )


__all__ = [
    "CLASSIFICATIONS",
    "DELETION_REASONS",
    "DeletionPreview",
    "PruneReport",
    "RetentionEntry",
    "RetentionError",
    "RetentionLedger",
    "RetentionPolicy",
    "Tombstone",
    "delete_items",
    "freeze_retention_policy",
    "open_retention_ledger",
    "preview_deletion",
    "prune",
    "register_item",
]
