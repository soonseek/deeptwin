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

from ..domain.refs import DomainContractError, EntityRef, canonical_json
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
_PLAN_KIND = "growth_comparison_plan"
_ROUND_KIND = "growth_comparison_round"
_CANDIDATE_KIND = "growth_frozen_candidate"
_OUTPUTS_KIND = "growth_round_outputs"
MAX_SIDE_RESULT_BYTES = 8_192
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


# --- the durable US6 chain: plan → rounds → frozen candidate → report --------------
# Each value is stored once, at an identity derived from its own content-derived ref,
# with its exact issue input; resume re-issues it through the same framework function
# and refuses anything that does not read back byte-for-byte (trust is the store's
# hash-linked record, never the payload).


def _once(domain_store, record_id, content, **headers) -> EntityRef:
    try:
        return _put(domain_store, record_id=record_id, revision=1, parents=(), content=content,
                    **headers)
    except GrowthStoreError:
        existing = _existing(domain_store, record_id)
        if existing is not None and existing.body["content"] == content:
            return existing.ref  # the same value persisted again: idempotent
        raise


def _existing(domain_store, record_id):
    with domain_store._connection() as db:
        roots = domain_store._read_roots(db)
        row = db.execute(
            "SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? AND version=1",
            (roots.genesis.id, RECORD_KIND, record_id)).fetchone()
    if row is None:
        return None
    return domain_store.get(EntityRef(RECORD_KIND, record_id, 1, row["sha256"]))


def _plan_input(plan_dict) -> dict:
    value = {key.removesuffix("_ref"): item for key, item in plan_dict.items() if key != "schema_version"}
    return value


def persist_comparison_plan(domain_store, plan, **headers) -> EntityRef:
    from .comparisons import is_frozen_plan

    if not is_frozen_plan(plan):
        raise GrowthStoreError("a frozen comparison plan is required")
    record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:growth-plan:{plan.plan_ref.id}"))
    return _once(domain_store, record_id, {
        "growth_kind": _PLAN_KIND, "plan": encode_design_refs(plan.as_dict())}, **headers)


def resume_comparison_plan(domain_store, ref):
    from .comparisons import freeze_comparison_plan

    content = _load(domain_store, ref, _PLAN_KIND)
    try:
        stored = decode_design_refs(content["plan"])
        plan = freeze_comparison_plan(_plan_input(stored))
    except (KeyError, ValueError) as exc:
        raise GrowthStoreError("the stored comparison plan is invalid") from exc
    if plan.as_dict() != stored:
        raise GrowthStoreError("the stored comparison plan does not read back exactly")
    return plan


def _round_record_id(result_ref: EntityRef) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:growth-round:{result_ref.id}"))


def persist_comparison_round(domain_store, plan, value, *, plan_record_ref, **headers) -> EntityRef:
    """Persist one recorded round with its exact input; the plan must be the stored one."""

    from .comparisons import comparison_result_ref, record_comparison_round

    if resume_comparison_plan(domain_store, plan_record_ref).as_dict() != plan.as_dict():
        raise GrowthStoreError("the round's plan is not the stored plan")
    try:
        result = record_comparison_round(plan, value)
    except ValueError as exc:
        raise GrowthStoreError("the comparison round is invalid") from exc
    result_ref = comparison_result_ref(result)
    return _once(domain_store, _round_record_id(result_ref), {
        "growth_kind": _ROUND_KIND, "plan_record": plan_record_ref.as_dict()["id"],
        "plan_record_sha256": plan_record_ref.sha256, "round": encode_design_refs(value),
        "result": encode_design_refs(result.as_dict())}, **headers)


def resume_comparison_round(domain_store, result_ref: EntityRef):
    """The recorded round whose content-derived ref is `result_ref`, re-issued."""

    stored = _existing(domain_store, _round_record_id(result_ref))
    if stored is None:
        raise GrowthStoreError("that comparison round was never persisted")
    _plan, result = _reissue_round(domain_store, stored, result_ref)
    return result


def resume_comparison_round_record(domain_store, record_ref: EntityRef):
    """(plan, round) of one persisted round record, both re-issued exactly."""

    from .comparisons import comparison_result_ref

    content = _load(domain_store, record_ref, _ROUND_KIND)
    try:
        stated = decode_design_refs(content["result"])
    except (KeyError, ValueError) as exc:
        raise GrowthStoreError("the stored comparison round is invalid") from exc
    plan, result = _reissue_round(domain_store, domain_store.get(record_ref), None)
    if result.as_dict() != stated or _round_record_id(comparison_result_ref(result)) != record_ref.id:
        raise GrowthStoreError("the stored comparison round does not read back exactly")
    return plan, result


def _reissue_round(domain_store, stored, result_ref):
    from .comparisons import comparison_result_ref, record_comparison_round

    content = stored.body["content"]
    if content.get("growth_kind") != _ROUND_KIND:
        raise GrowthStoreError("the record is not a comparison round")
    try:
        plan = resume_comparison_plan(domain_store, EntityRef(
            RECORD_KIND, content["plan_record"], 1, content["plan_record_sha256"]))
        result = record_comparison_round(plan, decode_design_refs(content["round"]))
        stated = decode_design_refs(content["result"])
    except (KeyError, ValueError) as exc:
        if isinstance(exc, GrowthStoreError):
            raise
        raise GrowthStoreError("the stored comparison round is invalid") from exc
    if result.as_dict() != stated or (result_ref is not None and comparison_result_ref(result) != result_ref):
        raise GrowthStoreError("the stored comparison round does not read back exactly")
    return plan, result


def _outputs_record_id(round_record_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:growth-round-outputs:{round_record_id}"))


def _side_results(run) -> list:
    # each node's durable result as bounded canonical text: its refs point into the run's
    # own isolated vault, which is discarded after the round, so they are kept as text
    results = []
    for node_id, content in run.results:
        text = canonical_json(content).decode("utf-8")
        data = text.encode("utf-8")
        truncated = len(data) > MAX_SIDE_RESULT_BYTES
        if truncated:
            text = data[:MAX_SIDE_RESULT_BYTES].decode("utf-8", errors="ignore")
        results.append({"node_id": node_id, "result_text": text, "truncated": truncated,
                        "result_bytes": len(data)})
    return results


def persist_round_outputs(domain_store, round_record_ref: EntityRef, paired_round, **headers) -> EntityRef:
    """Persist what each side of a recorded round produced, before its isolated vaults are
    removed, so the two can be read side by side: per item, both sides' node results
    (bounded; a longer one says so) and the nodes whose results differ, inside and outside
    the declared change scope. The round record must be the one this execution recorded."""

    from .comparisons import is_recorded_round

    if not is_recorded_round(getattr(paired_round, "result", None)):
        raise GrowthStoreError("a recorded paired round is required")
    _plan, result = resume_comparison_round_record(domain_store, round_record_ref)
    if result.as_dict() != paired_round.result.as_dict():
        raise GrowthStoreError("the outputs belong to another round")
    items = []
    for (left, right), changed, unexplained in zip(
            paired_round.runs, paired_round.changed_nodes, paired_round.unexplained_nodes, strict=True):
        # the queue position the pair ran for (an item that was not compared has no pair)
        items.append({"item_index": left.item_index, "changed_nodes": list(changed),
                      "unexplained_nodes": list(unexplained),
                      "baseline": _side_results(left), "candidate": _side_results(right)})
    content = {"growth_kind": _OUTPUTS_KIND, "round_record": round_record_ref.id,
               "round_record_sha256": round_record_ref.sha256, "items": items}
    if paired_round.tool_effects_involved:
        # G-14: each item's outcome and the isolation boundary every isolated call used
        content["item_outcomes"] = [dict(item) for item in paired_round.item_outcomes]
    return _once(domain_store, _outputs_record_id(round_record_ref.id), content, **headers)


def _stored_outputs(domain_store, round_record_ref: EntityRef):
    stored = _existing(domain_store, _outputs_record_id(round_record_ref.id))
    if stored is None:
        return None
    content = stored.body["content"]
    if (content.get("growth_kind") != _OUTPUTS_KIND or content.get("round_record") != round_record_ref.id
            or content.get("round_record_sha256") != round_record_ref.sha256):
        raise GrowthStoreError("the stored round outputs belong to another round")
    return content


def resume_round_outputs(domain_store, round_record_ref: EntityRef):
    """The persisted side-by-side outputs of one round, or None when none were kept."""

    content = _stored_outputs(domain_store, round_record_ref)
    return None if content is None else content["items"]


def resume_round_item_outcomes(domain_store, round_record_ref: EntityRef):
    """The per-item outcomes of a round that involved tool effects (G-14), else None."""

    content = _stored_outputs(domain_store, round_record_ref)
    return None if content is None else content.get("item_outcomes")


def persist_frozen_candidate(domain_store, candidate, **headers) -> EntityRef:
    from .validation import is_frozen_candidate

    if not is_frozen_candidate(candidate):
        raise GrowthStoreError("a frozen candidate bundle is required")
    record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:growth-candidate:{candidate.bundle_ref.id}"))
    return _once(domain_store, record_id, {
        "growth_kind": _CANDIDATE_KIND, "bundle": encode_design_refs(candidate.as_dict())}, **headers)


def resume_frozen_candidate(domain_store, bundle_ref: EntityRef):
    """The frozen candidate whose content-derived bundle ref is `bundle_ref`, re-issued."""

    from .validation import freeze_candidate

    stored = _existing(domain_store, str(uuid5(
        NAMESPACE_URL, f"deeptwin:growth-candidate:{bundle_ref.id}")))
    if stored is None or stored.body["content"].get("growth_kind") != _CANDIDATE_KIND:
        raise GrowthStoreError("that candidate bundle was never persisted")
    bundle = decode_design_refs(stored.body["content"]["bundle"])
    try:
        candidate = freeze_candidate({key.removesuffix("_ref"): item for key, item in bundle.items()
                                      if key != "schema_version"})
    except ValueError as exc:
        raise GrowthStoreError("the stored candidate bundle is invalid") from exc
    if candidate.as_dict() != bundle or candidate.bundle_ref != bundle_ref:
        raise GrowthStoreError("the stored candidate bundle does not read back exactly")
    return candidate


def resume_validation_report(domain_store, ref):
    """Rebuild one persisted report over its stored candidate and recorded rounds."""

    from .validation import restore_validation_report

    content = _load(domain_store, ref, _REPORT_KIND)
    try:
        stored = decode_design_refs(content["report"])
        candidate = resume_frozen_candidate(domain_store, EntityRef.from_dict(stored["candidate_bundle_ref"]))
        cited = {item["sha256"]: item for gate in stored["gates"].values() for item in gate["evidence_refs"]}
        rounds = [resume_comparison_round(domain_store, EntityRef.from_dict(item)) for item in cited.values()]
        return candidate, restore_validation_report(candidate, stored, rounds)
    except (KeyError, TypeError) as exc:
        raise GrowthStoreError("the stored validation report is invalid") from exc
    except ValueError as exc:
        if isinstance(exc, GrowthStoreError):
            raise
        raise GrowthStoreError("the stored validation report is invalid") from exc


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
    "persist_comparison_plan",
    "persist_comparison_round",
    "persist_dataset_ledger",
    "persist_frozen_candidate",
    "persist_loop_state",
    "persist_promotion_state",
    "persist_round_outputs",
    "persist_validation_report",
    "resume_comparison_plan",
    "resume_comparison_round",
    "resume_comparison_round_record",
    "resume_dataset_ledger",
    "resume_frozen_candidate",
    "resume_loop",
    "resume_promotion_state",
    "resume_round_item_outcomes",
    "resume_round_outputs",
    "resume_validation_report",
]
