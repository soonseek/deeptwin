"""Durable growth-chain persistence with store-enforced CAS (growth.md §7).

The growth loop and the dataset ledger are immutable in-process values; two
independent audits recorded that lineage single-liveness and consumption
replay are the storage layer's obligation. This module discharges it on the
DomainStore's immutable (kind, id, version) identity: every loop revision
and ledger revision is one record whose version IS the revision, linked to
its predecessor through ``parent_refs``. Two writers advancing from the same
revision therefore collide on the same identity with different content and
the second transaction fails instead of silently forking (G-09); re-opening
a lineage collides with its revision-1 record; and a validation report is
stored at the identity of the ledger revision it consumed, so a different
run replaying the same pre-consumption revision collides and exactly one
unseen claim per revision survives into the durable chain (a byte-identical
replay is idempotent — the same record, never a second claim).
Resume rebuilds framework-issued values through the strict restore paths —
trust comes from the store's hash-linked records, never from the payload.
"""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError
from .design_persistence import decode_design_refs, encode_design_refs
from .growth import (
    apply_round,
    freeze_quality_profile,
    is_issued_loop,
    restore_growth_loop,
)
from .promotion import is_issued_promotion_state, restore_promotion_state
from .validation import (
    is_issued_ledger,
    is_validation_report,
    restore_dataset_ledger,
)

RECORD_KIND = "decision_record"
_LOOP_KIND = "growth_loop_state"
_LEDGER_KIND = "growth_dataset_ledger"
_REPORT_KIND = "growth_validation_report"
_PROMOTION_KIND = "growth_promotion_state"
_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)


class GrowthStoreError(ValueError):
    """A growth persistence operation is invalid or lost a CAS race."""


def _ledger_record_id(lineage_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:growth-ledger:{lineage_id}"))


def _parent(parent_ref, *, record_id, revision, first_revision_only):
    if parent_ref is None:
        if first_revision_only and revision != 1:
            # A loop always persists from revision 1, so a parentless write
            # at a later revision is the restart-laundering path.
            raise GrowthStoreError("only revision 1 persists without a parent")
        return ()
    if (
        type(parent_ref) is not EntityRef
        or parent_ref.kind != RECORD_KIND
        or parent_ref.id != record_id
        or parent_ref.version != revision - 1
    ):
        raise GrowthStoreError(
            "a revision must chain to its exact predecessor record"
        )
    if first_revision_only and revision == 1:
        raise GrowthStoreError("revision 1 never carries a parent")
    return (parent_ref,)


def _put(
    domain_store,
    *,
    record_id,
    revision,
    parents,
    content,
    actor_ref,
    access_policy_ref,
    retention_policy_ref,
    created_at_utc,
) -> EntityRef:
    if type(domain_store) is not DomainStore:
        raise GrowthStoreError("an exact domain store is required")
    try:
        record = ImmutableRecord.create(
            kind=RECORD_KIND,
            id=record_id,
            version=revision,
            created_at_utc=created_at_utc,
            actor_ref=actor_ref,
            parent_refs=parents,
            purpose="operational",
            access_policy_ref=access_policy_ref,
            retention_policy_ref=retention_policy_ref,
            content=content,
        )
    except (DomainContractError, TypeError, ValueError) as exc:
        raise GrowthStoreError("the growth record is invalid") from exc
    try:
        return domain_store.put(record)
    except StorageError as exc:
        # An ImmutableConflict here IS the CAS refusal: another writer
        # already advanced this revision with different content.
        raise GrowthStoreError(
            "this revision was already written with different content"
        ) from exc


def persist_loop_state(domain_store, state, *, parent_ref, **headers) -> EntityRef:
    """Persist one loop revision; the record version is the revision."""

    if not is_issued_loop(state):
        raise GrowthStoreError("a framework-issued growth loop state is required")
    profile = state.profile
    content = {
        "growth_kind": _LOOP_KIND,
        "profile": {
            "profile_id": profile.profile_id,
            "version": profile.version,
            "quality_floor": str(profile.quality_floor),
            "min_delta": str(profile.min_delta),
            "patience": profile.patience,
        },
        "state": encode_design_refs(state.as_dict()),
    }
    return _put(
        domain_store,
        record_id=state.lineage_id,
        revision=state.revision,
        parents=_parent(
            parent_ref, record_id=state.lineage_id, revision=state.revision,
            first_revision_only=True,
        ),
        content=content,
        **headers,
    )


def advance_and_persist_loop(domain_store, state, value, *, prev_ref, **headers):
    """Apply one round and persist the new revision in one CAS step."""

    new_state = apply_round(state, value)
    ref = persist_loop_state(
        domain_store, new_state, parent_ref=prev_ref, **headers,
    )
    return new_state, ref


def resume_loop(domain_store, ref):
    """Rebuild the issued loop state stored at one exact record ref."""

    content = _load(domain_store, ref, _LOOP_KIND)
    if type(content.get("profile")) is not dict:
        raise GrowthStoreError("the stored loop record has no profile")
    try:
        profile = freeze_quality_profile(dict(content["profile"]))
        return restore_growth_loop(
            profile, decode_design_refs(content["state"]),
        )
    except ValueError as exc:
        raise GrowthStoreError("the stored loop state is invalid") from exc


def persist_dataset_ledger(domain_store, ledger, *, parent_ref, **headers) -> EntityRef:
    """Persist one ledger revision; the record version is the revision."""

    if not is_issued_ledger(ledger):
        raise GrowthStoreError("a framework-issued dataset ledger is required")
    record_id = _ledger_record_id(ledger.lineage_id)
    content = {
        "growth_kind": _LEDGER_KIND,
        "ledger": encode_design_refs(ledger.as_dict()),
    }
    return _put(
        domain_store,
        record_id=record_id,
        revision=ledger.revision,
        # A ledger's first persisted revision may exceed 1 (register/expose
        # already advanced the value), so a parentless first write is legal;
        # every later write must chain to its exact predecessor.
        parents=_parent(
            parent_ref, record_id=record_id, revision=ledger.revision,
            first_revision_only=False,
        ),
        content=content,
        **headers,
    )


def persist_validation_report(
    domain_store, report, *, lineage_id, parent_ref=None, **headers,
) -> EntityRef:
    """Persist one validation run at the identity of the ledger revision it
    consumed: two different runs replaying the same pre-consumption revision
    collide here, so exactly one unseen claim per revision becomes durable."""

    if not is_validation_report(report):
        raise GrowthStoreError(
            "a framework-issued validation report is required"
        )
    record_id = str(uuid5(
        NAMESPACE_URL,
        f"deeptwin:growth-validation:{lineage_id}:{report.ledger_revision}",
    ))
    parents = ()
    if parent_ref is not None:
        if type(parent_ref) is not EntityRef or parent_ref.kind != RECORD_KIND:
            raise GrowthStoreError("the report parent must be a ledger record")
        parents = (parent_ref,)
    return _put(
        domain_store,
        record_id=record_id,
        revision=1,
        parents=parents,
        content={
            "growth_kind": _REPORT_KIND,
            "lineage_id": lineage_id,
            "report": encode_design_refs(report.as_dict()),
        },
        **headers,
    )


def persist_promotion_state(
    domain_store, state, *, scope_id, parent_ref, **headers,
) -> EntityRef:
    """Persist one promotion-state revision for one deployment scope."""

    if not is_issued_promotion_state(state):
        raise GrowthStoreError(
            "a framework-issued promotion state is required"
        )
    if type(scope_id) is not str or _UUID_RE.fullmatch(scope_id) is None:
        raise GrowthStoreError("scope id is not a canonical UUID")
    record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:promotion:{scope_id}"))
    return _put(
        domain_store,
        record_id=record_id,
        revision=state.revision,
        # A promotion state may first persist mid-history (revision > 1)
        # when the scope adopts an existing environment; later writes chain.
        parents=_parent(
            parent_ref, record_id=record_id, revision=state.revision,
            first_revision_only=False,
        ),
        content={
            "growth_kind": _PROMOTION_KIND,
            "scope_id": scope_id,
            "state": encode_design_refs(state.as_dict()),
        },
        **headers,
    )


def resume_promotion_state(domain_store, ref):
    """Rebuild the issued promotion state stored at one exact record ref."""

    content = _load(domain_store, ref, _PROMOTION_KIND)
    try:
        return restore_promotion_state(decode_design_refs(content["state"]))
    except (KeyError, ValueError) as exc:
        raise GrowthStoreError("the stored promotion state is invalid") from exc


def resume_dataset_ledger(domain_store, ref):
    """Rebuild the issued ledger stored at one exact record ref."""

    content = _load(domain_store, ref, _LEDGER_KIND)
    try:
        return restore_dataset_ledger(decode_design_refs(content["ledger"]))
    except (KeyError, ValueError) as exc:
        raise GrowthStoreError("the stored ledger is invalid") from exc


def _load(domain_store, ref, growth_kind):
    if type(domain_store) is not DomainStore or type(ref) is not EntityRef:
        raise GrowthStoreError("an exact domain store and record ref are required")
    try:
        record = domain_store.get(ref)
    except StorageError as exc:
        raise GrowthStoreError("the growth record could not be read") from exc
    content = record.body.get("content")
    if type(content) is not dict or content.get("growth_kind") != growth_kind:
        raise GrowthStoreError("the record is not the expected growth kind")
    return content


__all__ = [
    "RECORD_KIND",
    "GrowthStoreError",
    "advance_and_persist_loop",
    "persist_dataset_ledger",
    "persist_loop_state",
    "persist_promotion_state",
    "persist_validation_report",
    "resume_dataset_ledger",
    "resume_loop",
    "resume_promotion_state",
]
