"""A durable US6 chain seeded through the real services (T067).

Every fact written here is SYNTHETIC and authored by the vault's test actor — no
actual user, alternative, candidate or validation exists. The chain is built only
through the framework functions the product itself uses:

- comparison plans frozen and persisted (`freeze_comparison_plan`,
  `persist_comparison_plan`);
- every round produced by isolated paired execution on the real scheduler
  (`execute_paired_round`: each (side, item) run in its own fresh vault), with a
  code-owned evaluator, recorded and persisted against the stored plan;
- the growth loop advanced one round at a time and persisted revision by revision
  under the store's CAS (`advance_and_persist_loop`), fed from each recorded round;
- candidates frozen (`freeze_candidate`), the dataset ledger registered/exposed and
  sealed validation run over separately executed rounds (`run_validation`), reports
  and ledgers persisted.

The seeded lineages (growth.md §6.4 sequences, synthetic numbers):

- PLATEAU: 0.80 → invalid (candidate run crashed) → 0.81 → invalid (evaluator
  unresolved) → 0.805 → 0.81 ⇒ `plateau_reached`, best 0.81 (the earlier one),
  reference 0.8, three valid non-improvements; invalid rounds never counted.
- BELOW: 0.71 → 0.72 → 0.72, then the finite budget ends ⇒ `below_floor_exhausted`.
- OLD (evaluator A): 0.80 → 0.81, then the evaluator is changed after observing
  ⇒ `lineage_changed`; NEW (evaluator B, a new plan and lineage): 0.82 with its own
  fresh baseline runs — counter 0, nothing carried over.

Candidates: EARLY (the plateau's best, tuning evidence only, shadow report — never
approvable), P and R (separately sealed-validated, passed), Q (sealed-validated,
failed heldout transfer); then Q is edited after its report was reviewed — the
sealed dataset is reclassified as tuning and the edited Q' can obtain no unseen pass.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.domain.schemas import ImmutableRecord
from app.services.comparisons import freeze_comparison_plan, record_comparison_round
from app.services.growth import (
    freeze_quality_profile,
    start_growth_loop,
    stop_growth_loop,
)
from app.services.growth_store import (
    advance_and_persist_loop,
    persist_comparison_plan,
    persist_comparison_round,
    persist_dataset_ledger,
    persist_frozen_candidate,
    persist_loop_state,
    persist_round_outputs,
    persist_validation_report,
)
from app.services.paired_execution import (
    PairedSide,
    execute_paired_round,
    remove_isolated_runs,
)
from app.services.validation import (
    GATES,
    GrowthValidationError,
    expose_dataset,
    freeze_candidate,
    open_dataset_ledger,
    register_dataset,
    run_validation,
    unseen_dataset_ids,
    validation_report_ref,
)
from app.tests.test_alternatives import ref
from app.tests.test_graph_contract import compile_value
from app.tests.test_graph_execution import linear_graph
from app.tests.test_server_api_v1 import immutable

LABEL = "synthetic/test-actor"
STAMP = "2026-09-25T00:00:00.000000Z"
COMPILED = compile_value(linear_graph())  # intake -> writer -> publish
ITEMS = [{"text": "합성 업무 1", "label": LABEL}, {"text": "합성 업무 2", "label": LABEL}]
PROFILE = {"profile_id": "bounded_artifact_quality_v1", "version": 1, "quality_floor": "0.80",
           "min_delta": "0.02", "patience": 3}

PLATEAU = "67001000-0000-4000-8000-000000000000"
BELOW = "67002000-0000-4000-8000-000000000000"
OLD = "67003000-0000-4000-8000-000000000000"
NEW = "67004000-0000-4000-8000-000000000000"
VALIDATE_P = "67011000-0000-4000-8000-000000000000"
VALIDATE_R = "67012000-0000-4000-8000-000000000000"
VALIDATE_Q = "67013000-0000-4000-8000-000000000000"

SEQUENCES = {
    PLATEAU: ["0.80", "crash", "0.81", "unresolved", "0.805", "0.81"],
    BELOW: ["0.71", "0.72", "0.72"],
    OLD: ["0.80", "0.81"],
    NEW: ["0.82"],
}
STOPS = {BELOW: "below_floor_exhausted", OLD: "lineage_changed"}
UNRESOLVED = "평가기가 판정을 내리지 못함(미결)"
HELDOUT_FAILURE = "새 사례 전이에서 필수 출처가 빠짐"


def marks(domain):
    roots = domain.roots()
    return {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
            "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}


def plan_for(lineage_id, *, evaluator=67907, queue=67905):
    return freeze_comparison_plan({
        "lineage_id": lineage_id, "baseline_environment": ref("environment", 67901),
        "queue": ref("run_manifest", queue), "quality_profile": ref("evaluation_profile", 67906),
        "evaluator_bundle": ref("rubric", evaluator), "reset_manifest": ref("run_manifest", 67908),
        "allowed_changes": ref("decision_record", 67909),
        "tool_effect_policy": ref("observation_contract", 67910),
        "budget": ref("budget_policy", 67911), "mode": "automatic"})


def _handlers(output):
    def factory(item, domain):
        roots = domain.roots()

        def produce(context, view):
            text = output(context.node_id, item)
            record = ImmutableRecord.create(
                kind="artifact", id=str(uuid4()), version=1, created_at_utc=STAMP,
                actor_ref=roots.actor, parent_refs=(), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content={"output": text, "evidence_label": LABEL})
            domain.put(record)
            return record.ref

        return {"core.deterministic": produce, "core.agent": produce}

    return factory


def _sides(spec):
    def baseline(node, item):
        return f"{node}:{item['text']}" + (" quality=0.78" if node == "publish" else "")

    def candidate(node, item):
        if spec == "crash" and node == "writer" and item["text"] == ITEMS[1]["text"]:
            raise RuntimeError("synthetic tool failure")
        quality = "0.80" if spec in {"crash", "unresolved"} else spec
        return f"{node}:{item['text']}+출처" + (f" quality={quality}" if node == "publish" else "")

    return PairedSide("baseline", COMPILED, _handlers(baseline)), PairedSide("candidate", COMPILED, _handlers(candidate))


def _evaluator(spec):
    def evaluate(item, left, right):
        if spec == "unresolved":
            return {"valid": False, "reasons": [UNRESOLVED], "metrics": {}}
        quality = dict(right.results)["publish"]["output"].rsplit("quality=", 1)[1]
        baseline = dict(left.results)["publish"]["output"].rsplit("quality=", 1)[1]
        return {"valid": True, "reasons": [], "metrics": {"utility": quality, "baseline_quality": baseline}}

    return evaluate


def _round_input(result):
    value = result.as_dict()
    return {"round_id": value["round_id"], "round_index": value["round_index"],
            "candidate": value["candidate_ref"], "baseline_runs": value["baseline_run_refs"],
            "candidate_runs": value["candidate_run_refs"], "validity": value["validity"],
            "validity_reasons": value["validity_reasons"], "mandatory_checks": value["mandatory_checks_ref"],
            "metric_vector": value["metric_vector"], "utility": value["utility"],
            "evidence": value["evidence_refs"], "usage": value["usage_ref"]}


def execute_round(domain, plan, plan_record, reset_base, *, index, spec, candidate):
    """One isolated paired round on the real scheduler, recorded and persisted."""

    baseline, candidate_side = _sides(spec)
    reset_root = Path(reset_base) / f"{plan.lineage_id}-{index}"
    paired = execute_paired_round(
        plan, items=[dict(item) for item in (ITEMS if spec == "crash" else ITEMS[:1])],
        baseline=baseline, candidate=candidate_side,
        evaluator=_evaluator(spec), reset_root=reset_root, declared_changes=("writer",),
        round_value={"round_id": f"{plan.lineage_id[:5]}-round-{index}", "round_index": index,
                     "candidate": candidate, "mandatory_checks": ref("validation_report", 67925),
                     "evidence": [], "usage": ref("decision_record", 67927)})
    value = _round_input(paired.result)
    assert record_comparison_round(plan, value).as_dict() == paired.result.as_dict()
    record = persist_comparison_round(domain, plan, value, plan_record_ref=plan_record, **marks(domain))
    persist_round_outputs(domain, record, paired, **marks(domain))  # before the isolated runs go
    consumed = {"isolated_runs": 2 * len(paired.runs),
                "node_visits": sum(len(run.trace.executions) for pair in paired.runs for run in pair)}
    remove_isolated_runs(reset_root)
    return paired.result, record, consumed


def _outcome(result, consumed):
    return {"round_id": result.round_id, "validity": result.validity,
            "utility": None if result.utility is None else str(result.utility),
            "mandatory_passed": True, "regression_ok": True, "consumed": consumed}


def seed_lineage(domain, reset_base, lineage_id, *, evaluator=67907):
    plan = plan_for(lineage_id, evaluator=evaluator)
    plan_record = persist_comparison_plan(domain, plan, **marks(domain))
    state = start_growth_loop(lineage_id, freeze_quality_profile(dict(PROFILE)))
    head = persist_loop_state(domain, state, parent_ref=None, **marks(domain))
    heads = [head]
    results = []
    for index, spec in enumerate(SEQUENCES[lineage_id]):
        candidate = ref("change_candidate", int(lineage_id[:5]) * 10 + index)
        result, _record, consumed = execute_round(domain, plan, plan_record, reset_base, index=index,
                                                  spec=spec, candidate=candidate)
        results.append(result)
        state, head = advance_and_persist_loop(domain, state, _outcome(result, consumed), prev_ref=head,
                                               **marks(domain))
        heads.append(head)
    if lineage_id in STOPS:
        state = stop_growth_loop(state, STOPS[lineage_id])
        head = persist_loop_state(domain, state, parent_ref=head, **marks(domain))
        heads.append(head)
    return {"plan": plan, "state": state, "heads": heads, "results": results}


def bundle(candidate, *, prompts, evaluation_policy=67939):
    return freeze_candidate({
        "candidate": candidate, "environment_graph": ref("environment", 67931),
        "model_bindings": ref("model_choice", 67932), "prompts": ref("artifact", prompts),
        "knowledge_rules": ref("decision_record", 67934), "archetype_io": ref("observation_contract", 67935),
        "tool_permissions": ref("grant", 67936), "lens_versions": ref("lens_composition", 67937),
        "scope": ref("decision_record", 67938), "evaluation_policy": ref("evaluation_profile", evaluation_policy),
        "approval_policy": ref("decision_record", 67940), "dependencies": ref("run_manifest", 67941),
        "rollback_bundle": ref("backup_manifest", 67942)})


def _gates(round_result, failing=None):
    return {name: {"status": "fail" if name == failing else "pass", "evidence": [round_result],
                   "reasons": [HELDOUT_FAILURE] if name == failing else []} for name in GATES}


def sealed_validation(domain, reset_base, lineage_id, candidate, *, dataset, manifest, quality, failing=None):
    """Separate sealed validation: its own plan over the sealed queue, a paired round
    executed for exactly this change candidate, the ledger consumed and persisted."""

    plan = plan_for(lineage_id, queue=manifest)
    plan_record = persist_comparison_plan(domain, plan, **marks(domain))
    result, _record, _consumed = execute_round(domain, plan, plan_record, reset_base, index=0, spec=quality,
                                               candidate=candidate.candidate.as_dict())
    ledger = register_dataset(open_dataset_ledger(lineage_id), {
        "dataset_id": dataset, "classification": "sealed_validation", "manifest": ref("run_manifest", manifest)})
    ledger_record = persist_dataset_ledger(domain, ledger, parent_ref=None, **marks(domain))
    report, consumed = run_validation(candidate, ledger, {
        "mode": "sealed_offline", "datasets": [dataset], "approved_scope": None,
        "gates": _gates(result, failing)})
    consumed_record = persist_dataset_ledger(domain, consumed, parent_ref=ledger_record, **marks(domain))
    record = persist_validation_report(domain, report, lineage_id=lineage_id, parent_ref=consumed_record,
                                       **marks(domain))
    return {"report": report, "record": record, "ledger": consumed, "ledger_record": consumed_record}


def seed(domain, reset_base):
    """Seed the whole chain; returns the facts the browser case checks, all labelled."""

    roots = domain.roots()
    operating = immutable(domain, roots, "environment", content={
        "fixture": "operating environment", "evidence_label": LABEL}).ref
    lineages = {lineage: seed_lineage(domain, reset_base, lineage, evaluator=67917 if lineage == NEW else 67907)
                for lineage in (PLATEAU, BELOW, OLD, NEW)}
    plateau = lineages[PLATEAU]
    best_round = next(item for item in plateau["results"] if item.round_id == plateau["state"].best_observed[0])
    # EARLY: the plateau's best candidate right after the early stop, backed only by its
    # tuning round — a shadow observation, never a sealed unseen pass (G-11)
    early = bundle(best_round.candidate.as_dict(), prompts=67950)
    persist_frozen_candidate(domain, early, **marks(domain))
    shadow, _ = run_validation(early, open_dataset_ledger(PLATEAU), {
        "mode": "shadow", "datasets": [], "approved_scope": None, "gates": _gates(best_round)})
    shadow_record = persist_validation_report(domain, shadow, lineage_id=PLATEAU, **marks(domain))
    candidates = {}
    for name, lineage, round_index, prompts, dataset, manifest, quality, failing in (
            ("P", VALIDATE_P, 2, 67951, "sealed-p", 67961, "0.83", None),
            ("R", VALIDATE_R, 4, 67952, "sealed-r", 67962, "0.82", None),
            ("Q", VALIDATE_Q, 5, 67953, "sealed-q", 67963, "0.79", "heldout_transfer")):
        change = plateau["results"][round_index].candidate.as_dict()
        frozen = bundle(change, prompts=prompts)
        persist_frozen_candidate(domain, frozen, **marks(domain))
        validated = sealed_validation(domain, reset_base, lineage, frozen, dataset=dataset, manifest=manifest,
                                      quality=quality, failing=failing)
        candidates[name] = {"candidate": frozen, **validated}
    # G-12: Q's failed report is reviewed and Q is edited after seeing the sealed data
    q = candidates["Q"]
    reviewed = expose_dataset(q["ledger"], "sealed-q", "report_review")
    reviewed_record = persist_dataset_ledger(domain, reviewed, parent_ref=q["ledger_record"], **marks(domain))
    edited = bundle(q["candidate"].candidate.as_dict(), prompts=67954)
    persist_frozen_candidate(domain, edited, **marks(domain))
    try:
        run_validation(edited, reviewed, {"mode": "sealed_offline", "datasets": ["sealed-q"],
                                          "approved_scope": None,
                                          "gates": _gates(_q_round(domain, q))})
        edited_unseen_pass = "issued"
    except GrowthValidationError as error:
        edited_unseen_pass = f"refused: {error}"
    ledger_view = {entry["dataset_id"]: entry for entry in reviewed.as_dict()["entries"]}
    return {
        "evidence_label": LABEL,
        "operating_environment_ref": operating.as_dict(),
        "lineages": {lineage: {**value["state"].as_dict(), "loop_heads": [head.as_dict() for head in value["heads"]],
                               "round_ids": [item.round_id for item in value["results"]],
                               "validities": [item.validity for item in value["results"]],
                               "baseline_runs": [[run.as_dict() for run in item.baseline_runs]
                                                 for item in value["results"]]}
                     for lineage, value in lineages.items()},
        "early": {"bundle_ref": early.bundle_ref.as_dict(),
                  "validation_report_ref": validation_report_ref(shadow).as_dict(),
                  "report_record": shadow_record.as_dict(), "mode": shadow.mode, "status": shadow.status},
        "candidates": {name: {"bundle_ref": item["candidate"].bundle_ref.as_dict(),
                              "validation_report_ref": validation_report_ref(item["report"]).as_dict(),
                              "report_record": item["record"].as_dict(), "status": item["report"].status}
                       for name, item in candidates.items()},
        "edited_q": {"bundle_ref": edited.bundle_ref.as_dict(), "unseen_pass": edited_unseen_pass,
                     "reviewed_ledger_record": reviewed_record.as_dict(),
                     "sealed_q_classification": ledger_view["sealed-q"]["classification"],
                     "sealed_q_seen": ledger_view["sealed-q"]["seen"],
                     "unseen_after_review": list(unseen_dataset_ids(reviewed))},
    }


def _q_round(domain, q):
    from app.domain.refs import EntityRef
    from app.services.growth_store import resume_comparison_round

    cited = q["report"].as_dict()["gates"]["heldout_transfer"]["evidence_refs"][0]
    return resume_comparison_round(domain, EntityRef.from_dict(cited))


def round_record_count(domain):
    with domain._connection() as db:
        roots = domain._read_roots(db)
        return db.execute("SELECT COUNT(*) FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                          "AND instr(body, ?) > 0", (roots.genesis.id, b'"growth_kind":"growth_comparison_round"')
                          ).fetchone()[0]


def growth_record_count(domain):
    with domain._connection() as db:
        roots = domain._read_roots(db)
        return db.execute("SELECT COUNT(*) FROM domain_records WHERE vault_id=? AND kind='decision_record'",
                          (roots.genesis.id,)).fetchone()[0]


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
