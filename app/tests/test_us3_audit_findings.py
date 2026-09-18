"""Regression tests for the US3 batch adversarial audit (2026-09-13).

F1 a dedup retry must equal the stored dispatch exactly — a different
tool, argument set, grant or approval under a reused request id is
laundering, not replay; F2/F3 a join decision never changes after the
successor is scheduled — later successes are evidence only, and completed
inputs are frozen; simultaneous observations tie-break by frozen branch
order AT ingestion; F4 host-path refusal survives backslashes, drive
letters, URL schemes, percent-encoding, trailing parent segments and
poisoned dict keys; F5 activation ids are delimiter-proof; F6/F7 admitted
outputs and recorded evidence are detached from caller-mutable objects and
artifact refs are validated; F8 a collect join states whether its minimum
was actually met; F9 hostile nesting depth is a typed refusal; F10
artifact slots are path-scanned; F11 visits and attempts are issued;
F12 the envelope records the grant and the effect approval; F13 every
bound artifact is supplied or explicitly truncated; F14 argument key names
are bounded.
"""

import dataclasses

import pytest

from app.runtime.gateway import GatewayError, freeze_turn, validate_step_output
from app.runtime.scheduling_state import (
    Attempt,
    NodeVisit,
    SchedulingError,
    apply_branch_result,
    apply_simultaneous_results,
    next_attempt,
    open_join,
    seal_activation,
    visit_identity,
)
from app.runtime.tools import ToolBoundaryError, dispatch_tool, register_tool
from app.services.handoffs import (
    HandoffError,
    create_handoff,
    mark_ready,
    record_delivery,
)
from app.tests.test_alternatives import ref
from app.tests.test_handoffs import handoff_value
from app.tests.test_model_payloads import turn_value
from app.tests.test_scheduling_state import RUN_ID, result, sealed
from app.tests.test_tool_boundary import REQUEST2, definition, registry, request


def test_f1_a_reused_request_id_must_match_the_stored_dispatch_exactly():
    state = registry()
    envelope, state = dispatch_tool(state, request())
    again, state = dispatch_tool(state, request())  # true replay: identical
    assert again == envelope
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            arguments={"page_range": "9-99", "dpi": 144},  # different args
        ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(grant_ref=ref("grant", 1499)))
    other = register_tool(state, definition(tool_id="deeptwin_other"))
    with pytest.raises(ToolBoundaryError):
        # the same request id under a different tool is laundering
        dispatch_tool(other, request(tool_id="deeptwin_other"))


def test_f2_the_winner_never_changes_after_the_successor_is_scheduled():
    _activation, join = sealed()
    join = apply_branch_result(join, result("b-beta", "succeeded",
                                            observation_index=5))
    assert join.winner == "b-beta"
    # a later-arriving success with an EARLIER observation is evidence only
    join = apply_branch_result(join, result("b-alpha", "succeeded",
                                            observation_index=1))
    assert join.winner == "b-beta"
    assert join.inputs == ("b-beta",)


def test_f2_simultaneous_observations_tie_break_at_ingestion():
    _activation, join = sealed()
    join = apply_simultaneous_results(join, [
        result("b-gamma", "succeeded", observation_index=1),
        result("b-alpha", "succeeded", observation_index=1),
    ])
    # the frozen branch order decides WITHIN one ingestion; afterwards the
    # decision is sealed
    assert join.winner == "b-alpha"
    join = apply_branch_result(join, result("b-beta", "succeeded",
                                            observation_index=0))
    assert join.winner == "b-alpha"


def test_f3_completed_inputs_are_frozen():
    activation = seal_activation(
        run_id=RUN_ID, router_node_id="router-1",
        visit=visit_identity("router-1", loop_index=0),
        branch_ids=["b1", "b2", "b3"],
    )
    collect = open_join(activation, mode="collect", min_success=2)
    collect = apply_branch_result(collect, result("b1", "succeeded",
                                                  observation_index=1))
    collect = apply_branch_result(collect, result("b3", "succeeded",
                                                  observation_index=2))
    assert collect.completed is True
    assert collect.satisfied is True
    frozen_inputs = collect.inputs
    late = apply_branch_result(collect, result("b2", "succeeded",
                                               observation_index=3))
    assert late.inputs == frozen_inputs  # evidence only, never a new input


def test_f8_collect_states_when_its_minimum_was_not_met():
    activation = seal_activation(
        run_id=RUN_ID, router_node_id="router-1",
        visit=visit_identity("router-1", loop_index=0),
        branch_ids=["b1", "b2", "b3"],
    )
    collect = open_join(activation, mode="collect", min_success=3)
    collect = apply_branch_result(collect, result("b1", "succeeded",
                                                  observation_index=1))
    collect = apply_branch_result(collect, result("b2", "failed",
                                                  observation_index=2))
    collect = apply_branch_result(collect, result("b3", "failed",
                                                  observation_index=3))
    assert collect.completed is True
    assert collect.satisfied is False  # never silently below the minimum


@pytest.mark.parametrize("poison", [
    "C:/Windows/System32/config",
    "C:\\Windows\\System32",
    "..\\..\\secrets.env",
    "\\\\fileserver\\share\\x",
    "file:///etc/passwd",
    "%2e%2e%2fetc%2fpasswd",
    "workspace/..",
    "a\x00b",
])
def test_f4_path_evasions_are_refused_in_values_and_keys(poison):
    turn = freeze_turn(turn_value())
    with pytest.raises(GatewayError):
        validate_step_output(turn, {
            "kind": "tool_request", "tool": "deeptwin_pdf",
            "arguments": {"target": poison},
        })
    with pytest.raises(GatewayError):
        validate_step_output(turn, {
            "kind": "tool_request", "tool": "deeptwin_pdf",
            "arguments": {poison: "x"},  # poisoned KEY
        })


def test_f4_tool_scopes_and_arguments_refuse_the_same_evasions():
    from app.runtime.tools import open_tool_registry

    with pytest.raises(ToolBoundaryError):
        register_tool(open_tool_registry(), definition(
            filesystem_scopes=["workspace/.."],
        ))
    state = registry()
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "..\\..\\up", "dpi": 144},
        ))


def test_f5_activation_ids_are_delimiter_proof():
    one = seal_activation(
        run_id=RUN_ID, router_node_id="router-1",
        visit=visit_identity("router-1", loop_index=0),
        branch_ids=["a,b"],
    )
    two = seal_activation(
        run_id=RUN_ID, router_node_id="router-1",
        visit=visit_identity("router-1", loop_index=0),
        branch_ids=["a", "b"],
    )
    assert one.activation_id != two.activation_id


def test_f6_f7_admitted_output_and_evidence_are_detached_and_validated():
    turn = freeze_turn(turn_value())
    arguments = {"nested": {"value": "safe"}}
    accepted = validate_step_output(turn, {
        "kind": "tool_request", "tool": "deeptwin_pdf",
        "arguments": arguments,
    })
    arguments["nested"]["value"] = "/etc/passwd"  # post-admit mutation
    assert accepted["arguments"]["nested"]["value"] == "safe"
    _activation, join = sealed()
    with pytest.raises(SchedulingError):
        apply_branch_result(join, result(
            "b-alpha", "succeeded", observation_index=1,
            artifact={"path": "/etc/passwd", "obj": object()},
        ))
    payload = result("b-alpha", "succeeded", observation_index=1,
                     artifact=ref("artifact", 1501))
    join = apply_branch_result(join, payload)
    payload["status"] = "TAMPERED"
    assert join.evidence[0]["status"] == "succeeded"


def test_f9_hostile_nesting_depth_is_a_typed_refusal():
    turn = freeze_turn(turn_value())
    deep = "x"
    for _ in range(200):
        deep = [deep]
    with pytest.raises(GatewayError):
        validate_step_output(turn, {
            "kind": "tool_request", "tool": "deeptwin_pdf",
            "arguments": {"payload": deep},
        })


def test_f10_artifact_slots_are_path_scanned():
    turn = freeze_turn(turn_value())
    with pytest.raises(GatewayError):
        validate_step_output(turn, {
            "kind": "final_artifacts",
            "artifacts": [{"slot": "../../etc/cron.d/evil",
                           "media_type": "text/plain"}],
        })


def test_f11_visits_and_attempts_are_issued_values():
    shell = object.__new__(NodeVisit)
    with pytest.raises(SchedulingError):
        seal_activation(
            run_id=RUN_ID, router_node_id="r", visit=shell,
            branch_ids=["b"],
        )
    with pytest.raises(SchedulingError):
        next_attempt(shell, previous_index=None)
    with pytest.raises(TypeError):
        dataclasses.replace(
            visit_identity("writer-node", loop_index=0), loop_index=9,
        )
    assert Attempt is not None


def test_f12_the_envelope_records_grant_and_approval():
    state = register_tool(registry(), definition(
        tool_id="deeptwin_send_email", effect_class="external_irreversible",
        replay="never", idempotency="none",
    ))
    envelope, _state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2,
        effect_approval_ref=ref("action_approval", 1405),
    ))
    assert envelope.grant_ref.as_dict() == ref("grant", 1401)
    assert envelope.effect_approval_ref.as_dict() == ref("action_approval", 1405)


def test_f13_every_bound_artifact_is_supplied_or_explicitly_truncated():
    handoff = mark_ready(
        create_handoff(handoff_value()), manifest_ref=ref("handoff", 1304),
    )
    with pytest.raises(HandoffError):
        # artifact 1 silently vanishes: neither supplied nor truncated
        record_delivery(handoff, {
            "supplied_spans": [{"artifact_index": 0, "span": "pages:1-4"}],
            "truncations": [],
        })
    disclosed = record_delivery(handoff, {
        "supplied_spans": [{"artifact_index": 0, "span": "pages:1-4"}],
        "truncations": [
            {"artifact_index": 1, "note": "이번 요청에는 포함되지 않았다"},
        ],
    })
    assert disclosed.truncations == ((1, "이번 요청에는 포함되지 않았다"),)


def test_f14_argument_key_names_are_bounded():
    from app.runtime.tools import open_tool_registry

    with pytest.raises(ToolBoundaryError):
        register_tool(open_tool_registry(), definition(
            argument_keys={"k" * 100_000: "str"},
        ))
