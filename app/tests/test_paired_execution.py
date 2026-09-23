"""T061: isolated paired execution of a frozen comparison over the real scheduler.

Both sides run every frozen queue item, each (side, item) run in its own fresh
vault and ledger; the code-owned evaluator scores what each run durably produced
as exact decimals; the round is recorded against the exact frozen plan — invalid
with every reason when any item is invalid or a run fails, measured only when
fully valid; and the nodes whose results differ are traced, with differences
outside the declared change's downstream closure reported as unexplained.
"""

from decimal import Decimal
from uuid import uuid4

import pytest

from app.domain.schemas import ImmutableRecord
from app.services.comparisons import freeze_comparison_plan
from app.services.paired_execution import (
    PairedExecutionError,
    PairedSide,
    execute_paired_round,
    remove_isolated_runs,
)
from app.tests.test_alternatives import ref
from app.tests.test_comparisons import plan_value
from app.tests.test_graph_contract import compile_value
from app.tests.test_graph_execution import linear_graph

COMPILED = compile_value(linear_graph())  # intake -> writer -> publish
ROUND = {"round_id": "round-1", "round_index": 0, "candidate": ref("change_candidate", 920),
         "mandatory_checks": ref("validation_report", 925), "evidence": [],
         "usage": ref("decision_record", 927)}
ITEMS = [{"text": "첫 업무"}, {"text": "둘째 업무"}]


def handlers_for(behaviour, seen=None):
    """A side's code-owned handlers: each node seals its output in the run's own vault."""

    def factory(item, domain):
        roots = domain.roots()

        def produce(context, view):
            if seen is not None:
                seen.append((context.node_id, item["text"], domain.vault_id))
            output = behaviour(context.node_id, item)
            record = ImmutableRecord.create(
                kind="artifact", id=str(uuid4()), version=1,
                created_at_utc="2026-09-23T00:00:00.000000Z", actor_ref=roots.actor,
                parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy, content={"output": output})
            domain.put(record)
            return record.ref

        return {"core.deterministic": produce, "core.agent": produce}

    return factory


def baseline_behaviour(node, item):
    return f"{node}:{item['text']}"


def candidate_behaviour(node, item):
    # the candidate changed the writer; publish consumes it, so it differs downstream
    return f"{node}:{item['text']}" + ("+출처" if node in {"writer", "publish"} else "")


def length_evaluator(item, baseline, candidate):
    before = dict(baseline.results)["publish"]["output"]
    after = dict(candidate.results)["publish"]["output"]
    gain = Decimal(len(after) - len(before))
    return {"valid": True, "reasons": [], "metrics": {"utility": str(gain), "length": str(len(after))}}


def run(tmp_path, *, baseline=baseline_behaviour, candidate=candidate_behaviour,
        evaluator=length_evaluator, declared=("writer",), items=ITEMS, seen=None):
    plan = freeze_comparison_plan(plan_value())
    return plan, execute_paired_round(
        plan, items=list(items),
        baseline=PairedSide("baseline", COMPILED, handlers_for(baseline, seen)),
        candidate=PairedSide("candidate", COMPILED, handlers_for(candidate, seen)),
        evaluator=evaluator, reset_root=tmp_path / "reset", declared_changes=declared,
        round_value=dict(ROUND))


def test_a_valid_round_pairs_isolated_runs_and_measures_exactly(tmp_path):
    seen = []
    plan, paired = run(tmp_path, seen=seen)
    result = paired.result
    assert result.plan_ref == plan.plan_ref and result.validity == "valid"
    assert len(result.baseline_runs) == len(result.candidate_runs) == 2
    assert set(result.baseline_runs).isdisjoint(result.candidate_runs)
    assert result.utility == Decimal(len("+출처"))
    assert dict(result.metric_vector)["length"] == Decimal("15.5")  # (15 + 16) / 2, exact
    # every (side, item) run had its own vault: four distinct vaults, never shared
    vaults = {vault for _node, _text, vault in seen}
    assert len(vaults) == 4
    assert paired.changed_nodes == (("publish", "writer"), ("publish", "writer"))
    assert paired.unexplained_nodes == ((), ())
    remove_isolated_runs(tmp_path / "reset")
    assert not (tmp_path / "reset").exists()


def test_a_difference_outside_the_declared_scope_is_unexplained(tmp_path):
    def leaky(node, item):
        return f"{node}:{item['text']}" + ("*" if node == "intake" else "")

    _plan, paired = run(tmp_path, candidate=leaky, declared=("writer",))
    assert paired.unexplained_nodes == (("intake",), ("intake",))


def test_an_invalid_item_invalidates_the_round_and_carries_no_measurement(tmp_path):
    def picky(item, baseline, candidate):
        if item["text"] == "둘째 업무":
            return {"valid": False, "reasons": ["평가 루브릭이 이 항목에 적용되지 않는다"], "metrics": {}}
        return length_evaluator(item, baseline, candidate)

    _plan, paired = run(tmp_path, evaluator=picky)
    result = paired.result
    assert result.validity == "invalid"
    assert result.metric_vector is None and result.utility is None  # never a zero
    assert result.validity_reasons == ("item 1: 평가 루브릭이 이 항목에 적용되지 않는다",)


def test_a_failed_run_is_an_invalid_round_with_the_runs_that_completed(tmp_path):
    def crashing(node, item):
        if item["text"] == "둘째 업무" and node == "writer":
            raise RuntimeError("PRIVATE_CANARY")
        return candidate_behaviour(node, item)

    _plan, paired = run(tmp_path, candidate=crashing)
    result = paired.result
    assert result.validity == "invalid" and len(result.baseline_runs) == 1
    assert "run failed" in result.validity_reasons[0]
    assert "PRIVATE_CANARY" not in " ".join(result.validity_reasons)


def test_inputs_are_checked_before_anything_runs(tmp_path):
    plan = freeze_comparison_plan(plan_value())
    side = PairedSide("baseline", COMPILED, handlers_for(baseline_behaviour))
    other = PairedSide("candidate", COMPILED, handlers_for(candidate_behaviour))
    base = {"items": list(ITEMS), "baseline": side, "candidate": other,
            "evaluator": length_evaluator, "reset_root": tmp_path / "r",
            "declared_changes": ("writer",), "round_value": dict(ROUND)}
    for bad in ({"items": []}, {"items": ["x"]}, {"candidate": side},
                {"declared_changes": ()}, {"declared_changes": ("ghost",)},
                {"evaluator": None}):
        with pytest.raises(PairedExecutionError):
            execute_paired_round(plan, **{**base, **bad})
    with pytest.raises(PairedExecutionError):
        execute_paired_round(object(), **base)
    (tmp_path / "r").mkdir()
    (tmp_path / "r" / "stale").write_text("x")
    with pytest.raises(PairedExecutionError, match="empty"):
        execute_paired_round(plan, **base)


def test_an_evaluator_outside_its_contract_stops_the_round(tmp_path):
    with pytest.raises(PairedExecutionError, match="contract"):
        run(tmp_path, evaluator=lambda *a: {"score": 1})
    with pytest.raises(PairedExecutionError, match="exact decimal"):
        run(tmp_path / "b", evaluator=lambda *a: {"valid": True, "reasons": [], "metrics": {"utility": 0.5}})
