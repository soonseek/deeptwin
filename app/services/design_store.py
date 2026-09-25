"""Durable design-arc persistence: approvals, environment heads and the
run-facing environment entity (T036).

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
Beside that chain, `persist_environment_record` seals the `environment` entity
the runtime names: one record per prepared version, over the preparation its
own head record holds. Those three are the module's only writers, and only
that one writes a kind other than `decision_record`.
"""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import DomainContractError, EntityRef
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, ImmutableConflict, StorageError
from .design_persistence import decode_design_refs, encode_design_refs
from .environments import (
    design_approval_evidence_subject,
    is_issued_design_approval,
    is_issued_environment_state,
    is_issued_environment_version,
    restore_environment_state,
)
from .owner_decisions import OwnerDecisionError, PersistentOwnerDecisions

RECORD_KIND = "decision_record"
_ENTITY_KIND = "environment"  # the runtime's own kind (runs/run_consents input kinds)
_APPROVAL_KIND = "design_approval_record"
_HEAD_KIND = "environment_head"
_ENTITY_SCHEMA = "environment-record-v1"
# a version prepared with extension binding revisions (environments.EnvironmentVersion)
_ENTITY_SCHEMA_WITH_BINDINGS = "environment-record-v2"
ENTITY_SCHEMAS = (_ENTITY_SCHEMA, _ENTITY_SCHEMA_WITH_BINDINGS)


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
    kind=RECORD_KIND,
) -> EntityRef:
    if type(domain_store) is not DomainStore:
        raise DesignStoreError("an exact domain store is required")
    try:
        record = ImmutableRecord.create(
            kind=kind,
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
    except ImmutableConflict as exc:
        # This IS the CAS refusal: another writer already wrote this identity
        # with different content.
        raise DesignStoreError(
            "this record was already written with different content"
        ) from exc
    except StorageError as exc:
        # anything else — an unresolvable or altered parent, an integrity failure —
        # is not a lost race and must not be reported as one
        raise DesignStoreError("the design record could not be stored") from exc


def persist_design_approval(domain_store, approval, *, decisions, **headers) -> EntityRef:
    """Persist one human approval content-addressed; identical is idempotent.

    The approval's evidence must resolve, through the owner-decision reader
    bound to this very store, to an approve decision over exactly this
    design subject: evidence from another vault, another design or a
    tampered reference persists nothing.
    """

    if not is_issued_design_approval(approval):
        raise DesignStoreError("a recorded design approval is required")
    if type(decisions) is not PersistentOwnerDecisions or not decisions.bound_to(
        domain_store
    ):
        raise DesignStoreError("an owner-decision reader bound to this store is required")
    try:
        evidence = decisions.resolve(approval.approver_evidence)
    except OwnerDecisionError as exc:
        raise DesignStoreError("the approval's evidence is not in this vault") from exc
    if (
        evidence.subject_kind != "design_approval"
        or evidence.decision != "approve"
        or evidence.subject != design_approval_evidence_subject(approval)
        or evidence.actor_ref.id != approval.approver_id
        or evidence.decided_at_utc != approval.approved_at
    ):
        raise DesignStoreError("the approval's evidence is not over this exact design")
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


def persist_environment_record(domain_store, version, *, head_ref, **headers) -> EntityRef:
    """Seal one prepared version as the `environment` entity a run names.

    The design arc's own record is the chained head (its record version IS the
    head value); this is the entity the runtime resolves — one record per
    prepared version, cut from the exact head record and carrying only the
    preparation that head holds, so persisting the same preparation twice under
    the same headers is the same record and never a second act, and a second
    writer's different design at the same identity loses the compare-and-swap.
    Prepared is never active: only a `prepared` version is ever sealed.

    Recorded open: there is no activation or currency here — every prepared
    version stays nameable at its own record version, and nothing yet says
    which one is current (`environments`: no activation path). The environment's
    own design and a run's `graph_ref` are also not yet bound to each other:
    `design_ref` is a design-space content hash, not a store reference, and no
    consumer reads this content today.
    """

    if not is_issued_environment_version(version):
        raise DesignStoreError("a prepared environment version is required")
    if version.status != "prepared":
        raise DesignStoreError("only a prepared version is sealed as an environment")
    record_id = str(uuid5(
        NAMESPACE_URL, f"deeptwin:environment:{version.environment_id}",
    ))
    if (type(head_ref) is not EntityRef or head_ref.kind != RECORD_KIND
            or head_ref.id != record_id or head_ref.version != version.version):
        raise DesignStoreError("an environment record is cut from its own head record")
    # the head is the record of what was prepared: this entity may not claim any other
    # preparation at that identity (two writers may prepare different designs from one head)
    if type(domain_store) is not DomainStore:
        raise DesignStoreError("an exact domain store is required")
    try:
        head = domain_store.get(head_ref)
    except StorageError as exc:
        raise DesignStoreError("the head record could not be read") from exc
    head_content = head.body.get("content")
    try:
        prepared = decode_design_refs(head_content["design"])["version"]
    except (KeyError, TypeError, ValueError) as exc:
        raise DesignStoreError("the head record is not an environment head") from exc
    if (type(head_content) is not dict or head_content.get("design_kind") != _HEAD_KIND
            or prepared != version.as_dict()):
        raise DesignStoreError("the head record holds another preparation")
    prepared_value = {
        "environment_id": version.environment_id,
        "version": version.version,
        "design_ref": version.design_ref.as_dict(),
        "approval_sha": version.approval_sha,
        "status": version.status,
    }
    schema = _ENTITY_SCHEMA
    if version.extension_bindings:
        # the exact binding revisions this version was prepared with (slot digest,
        # revision, record digest: identities, not references the store resolves)
        schema = _ENTITY_SCHEMA_WITH_BINDINGS
        prepared_value["extension_binding_revisions"] = version.as_dict()["extension_binding_revisions"]
    return _put(
        domain_store,
        record_id=record_id,
        version=version.version,
        parents=(head_ref,),
        content={
            "schema_version": schema,
            # the design the owner approved may not live in this vault (the arc's own
            # encoder: an identity, never a reference the store would try to resolve)
            **encode_design_refs(prepared_value),
        },
        kind=_ENTITY_KIND,
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
    "ENTITY_SCHEMAS",
    "RECORD_KIND",
    "DesignStoreError",
    "persist_design_approval",
    "persist_environment_head",
    "persist_environment_record",
    "resume_environment_state",
]
