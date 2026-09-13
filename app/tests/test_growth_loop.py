"""US6 growth loop: exact decimal plateau per growth.md §6.2-§6.4.

best_observed and progress_reference are separate; the first floor round sets
the reference without counting as non-improvement; improvement is an exact
Decimal `current - reference >= min_delta`; invalid/unresolved rounds never
touch the counters while budget still accrues; confirmed-defect rounds count
as valid non-improvement but never replace the best; three consecutive valid
non-improving rounds after the floor end the loop as plateau_reached; a loop
that never reaches the floor ends below_floor_exhausted, never plateau. Early
stopping is a PRODUCT policy only — nothing here stops development. Every
sequence below is the synthetic §6.4 table, not a real score.
"""

import dataclasses
from decimal import Decimal

import pytest

from app.services.growth import (
    GrowthLoop,
    GrowthLoopError,
    apply_round,
    freeze_quality_profile,
    start_growth_loop,
    stop_growth_loop,
)

LINEAGE = "00000000-0000-4000-8000-00000000f101"


def profile():
    return freeze_quality_profile({
        "profile_id": "bounded_artifact_quality_v1",
        "version": 1,
        "quality_floor": "0.80",
        "min_delta": "0.02",
        "patience": 3,
    })


def loop():
    return start_growth_loop(LINEAGE, profile())


def valid(index, utility, *, mandatory=True, regression=True):
    return {
        "round_id": f"round-{index}",
        "validity": "valid",
        "utility": utility,
        "mandatory_passed": mandatory,
        "regression_ok": regression,
        "consumed": {"calls": 1},
    }


def broken(index, reason="tool_failure"):
    return {
        "round_id": f"round-{index}",
        "validity": "invalid",
        "utility": None,
        "mandatory_passed": False,
        "regression_ok": False,
        "consumed": {"calls": 1},
        "invalid_reason": reason,
    }


def run(state, rounds):
    for value in rounds:
        state = apply_round(state, value)
    return state


def test_sequence_one_floor_then_three_small_gains_is_plateau():
    state = run(loop(), [
        valid(0, "0.79"), valid(1, "0.80"), valid(2, "0.805"),
        valid(3, "0.81"), valid(4, "0.81"),
    ])
    assert state.status == "plateau_reached"
    assert state.stop_reason == "plateau_reached"
    assert state.best_observed == ("round-3", Decimal("0.81"))
    assert state.floor_reached is True


def test_sequence_two_cumulative_gain_resets_the_counter():
    state = run(loop(), [
        valid(0, "0.80"), valid(1, "0.81"), valid(2, "0.825"),
        valid(3, "0.83"), valid(4, "0.84"), valid(5, "0.84"),
    ])
    assert state.status == "plateau_reached"
    # 0.825 was a meaningful gain over the 0.80 reference; the best is 0.84.
    assert state.progress_reference == ("round-2", Decimal("0.825"))
    assert state.best_observed == ("round-4", Decimal("0.84"))


def test_sequence_three_invalid_and_unresolved_rounds_never_count():
    state = run(loop(), [
        valid(0, "0.80"), broken(1), valid(2, "0.81"),
        broken(3, "judgment_unresolved"), valid(4, "0.805"), valid(5, "0.81"),
    ])
    assert state.status == "plateau_reached"
    assert state.consumed_budget == (("calls", 6),)  # failures still consume


def test_sequence_four_below_floor_is_never_plateau():
    state = run(loop(), [valid(0, "0.71"), valid(1, "0.72"), valid(2, "0.72")])
    assert state.status == "running"
    assert state.floor_reached is False
    stopped = stop_growth_loop(state, "below_floor_exhausted")
    assert stopped.status == "below_floor_exhausted"
    with pytest.raises(GrowthLoopError):
        stop_growth_loop(state, "plateau_reached")  # never claimable by fiat
    with pytest.raises(GrowthLoopError):
        # budget exhaustion above the floor is a different honest reason.
        stop_growth_loop(state, "budget_exhausted")


def test_sequence_five_confirmed_defects_count_but_never_replace_the_best():
    state = run(loop(), [
        valid(0, "0.80"), valid(1, "0.79"),
        valid(2, "0.83", mandatory=False),  # confirmed mandatory defect
        valid(3, "0.795"),
    ])
    assert state.status == "plateau_reached"
    assert state.best_observed == ("round-0", Decimal("0.80"))


def test_sequence_six_lineage_change_never_carries_the_counter():
    state = run(loop(), [valid(0, "0.80"), valid(1, "0.81")])
    assert state.non_improving_valid_count == 1
    ended = stop_growth_loop(state, "lineage_changed")
    assert ended.status == "lineage_changed"
    fresh = start_growth_loop(
        "00000000-0000-4000-8000-00000000f102", profile(),
    )
    assert fresh.non_improving_valid_count == 0
    assert fresh.consumed_budget == ()


def test_first_floor_round_is_not_a_non_improvement():
    state = run(loop(), [valid(0, "0.80")])
    assert state.floor_reached is True
    assert state.non_improving_valid_count == 0
    assert state.progress_reference == ("round-0", Decimal("0.80"))


def test_duplicate_rounds_and_terminal_states_are_rejected():
    state = run(loop(), [valid(0, "0.80")])
    with pytest.raises(GrowthLoopError):
        apply_round(state, valid(0, "0.81"))  # duplicate application
    finished = run(state, [valid(1, "0.805"), valid(2, "0.81"), valid(3, "0.81")])
    assert finished.status == "plateau_reached"
    with pytest.raises(GrowthLoopError):
        apply_round(finished, valid(4, "0.90"))
    with pytest.raises(GrowthLoopError):
        stop_growth_loop(finished, "human_stop")


def test_values_are_issued_and_exact():
    state = loop()
    with pytest.raises(TypeError):
        dataclasses.replace(state, non_improving_valid_count=0)
    with pytest.raises(TypeError):
        GrowthLoop(
            LINEAGE, state.profile, 1, "running", False, None, None, 0, (), (),
        )
    with pytest.raises(GrowthLoopError):
        freeze_quality_profile({
            "profile_id": "p", "version": 1, "quality_floor": 0.8,
            "min_delta": "0.02", "patience": 3,
        })
    with pytest.raises(GrowthLoopError):
        apply_round(state, valid(0, 0.81))  # float utilities are inexact
    with pytest.raises(GrowthLoopError):
        apply_round(object(), valid(0, "0.81"))
