"""Durable design-arc persistence: approvals and environment heads (T036).

Discharges the environments module's documented storage-CAS seam on the
DomainStore's immutable identity, exactly as growth_store does for the
growth chain. A design approval persists content-addressed — an identical
re-persist is idempotent (the same human act), never a second act. The
environment head persists as one record per head value: the record version
IS the head and each write chains to its exact predecessor, so two writers
preparing from the same head produce the same (kind, id, version) with
different content and the second transaction fails instead of silently
forking. Resume rebuilds the framework-issued state through the strict
restore path — a resumed state still refuses every consumed approval.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError
from .design_persistence import decode_design_refs, encode_design_refs
from .environments import (
    is_issued_design_approval,
    is_issued_environment_state,
    is_issued_environment_version,
    restore_environment_state,
)

RECORD_KIND = "decision_record"
_APPROVAL_KIND = "design_approval_record"
_HEAD_KIND = "environment_head"


class DesignStoreError(ValueError):
    """A design persistence operation is invalid or lost a CAS race."""


def _put(
    domain_store,
    *,
    record_id,
    version,
    parents,
    content,
    actor_ref,
    access_policy_ref,
    retention_policy_ref,
    created_at_utc,
) -> EntityRef:
    if type(domain_store) is not DomainStore:
        raise DesignStoreError("an exact domain store is required")
    try:
        record = ImmutableRecord.create(
            kind=RECORD_KIND,
            id=record_id,
            version=version,
            created_at_utc=created_at_utc,
            actor_ref=actor_ref,
            parent_refs=parents,
            purpose="operational",
            access_policy_ref=access_policy_ref,
            retention_policy_ref=retention_policy_ref,
            content=content,
        )
    except (DomainContractError, TypeError, ValueError) as exc:
        raise DesignStoreError("the design record is invalid") from exc
    try:
        return domain_store.put(record)
    except StorageError as exc:
        # An ImmutableConflict here IS the CAS refusal: another writer
        # already wrote this identity with different content.
        raise DesignStoreError(
            "this record was already written with different content"
        ) from exc


def persist_design_approval(domain_store, approval, **headers) -> EntityRef:
    """Persist one human approval content-addressed; identical is idempotent."""

    if not is_issued_design_approval(approval):
        raise DesignStoreError("a recorded design approval is required")
    record_id = str(uuid5(
        NAMESPACE_URL, f"deeptwin:design-approval:{approval.approval_sha}",
    ))
    return _put(
        domain_store,
        record_id=record_id,
        version=1,
        parents=(),
        content={
            "design_kind": _APPROVAL_KIND,
            "design": encode_design_refs(approval.as_dict()),
        },
        **headers,
    )


def persist_environment_head(
    domain_store, version, state, *, parent_ref, approval_ref, **headers,
) -> EntityRef:
    """Persist one prepared head; the record version IS the head value."""

    if not is_issued_environment_version(version):
        raise DesignStoreError("a prepared environment version is required")
    if not is_issued_environment_state(state):
        raise DesignStoreError("a framework-issued environment state is required")
    if (
        version.environment_id != state.environment_id
        or version.version != state.head
        or version.approval_sha not in state.consumed_approvals
    ):
        raise DesignStoreError(
            "the version and the state do not describe the same preparation"
        )
    record_id = str(uuid5(
        NAMESPACE_URL, f"deeptwin:environment:{state.environment_id}",
    ))
    parents = []
    if parent_ref is not None:
        if (
            type(parent_ref) is not EntityRef
            or parent_ref.kind != RECORD_KIND
            or parent_ref.id != record_id
            or parent_ref.version != state.head - 1
        ):
            raise DesignStoreError(
                "a head must chain to its exact predecessor record"
            )
        parents.append(parent_ref)
    if approval_ref is not None:
        if type(approval_ref) is not EntityRef:
            raise DesignStoreError("the approval parent must be a record ref")
        parents.append(approval_ref)
    return _put(
        domain_store,
        record_id=record_id,
        version=state.head,
        parents=tuple(parents),
        content={
            "design_kind": _HEAD_KIND,
            "design": encode_design_refs({
                "version": version.as_dict(),
                "state": state.as_dict(),
            }),
        },
        **headers,
    )


def resume_environment_state(domain_store, ref):
    """Rebuild the issued environment state stored at one exact record ref."""

    if type(domain_store) is not DomainStore or type(ref) is not EntityRef:
        raise DesignStoreError(
            "an exact domain store and record ref are required"
        )
    try:
        record = domain_store.get(ref)
    except StorageError as exc:
        raise DesignStoreError("the design record could not be read") from exc
    content = record.body.get("content")
    if type(content) is not dict or content.get("design_kind") != _HEAD_KIND:
        raise DesignStoreError("the record is not an environment head")
    try:
        decoded = decode_design_refs(content["design"])
        return restore_environment_state(decoded["state"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DesignStoreError("the stored environment state is invalid") from exc


__all__ = [
    "RECORD_KIND",
    "DesignStoreError",
    "persist_design_approval",
    "persist_environment_head",
    "resume_environment_state",
]
