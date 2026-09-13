"""US2 exact design approval and environment-version preparation (T036 B).

`이 설계로 준비` is a human's authenticated explicit act on one EXACT design
version: the approval binds the candidate's graph hash, the passed criticism
verdict for that exact candidate, and the concrete configuration refs
(models, tool grants, observation contract). It never includes work start,
external sends, or operational promotion of later changes — a design changed
after approval is a different hash and the stale approval never prepares it.
Preparation is compare-and-swap on the environment head: a stale head
refuses, the same approval can never prepare twice, and the prepared version
is status "prepared" — never active, with no activation path in this module
(experience.md §6.3; FR-004/007/008).
"""

import dataclasses

import pytest

from app.services.environments import (
    DesignApproval,
    EnvironmentContractError,
    EnvironmentVersion,
    open_environment,
    prepare_environment_version,
    record_design_approval,
)
from app.tests.test_alternatives import ref
from app.tests.test_design_review import pool_inputs, verdict

APPROVER = "00000000-0000-4000-8000-00000000a101"
ENV_ID = "00000000-0000-4000-8000-00000000e001"


def approval_value(candidate, candidate_verdict, **overrides):
    value = {
        "environment": ENV_ID,
        "candidate": candidate,
        "verdict": candidate_verdict,
        "approver": {
            "actor_id": APPROVER,
            "authenticated": True,
            "evidence": ref("action_approval", 1101),
        },
        "approved_at": "2026-09-13T08:00:00.000000Z",
        "model_bindings": ref("model_choice", 1102),
        "tool_permissions": ref("grant", 1103),
        "observation_contract": ref("observation_contract", 1104),
    }
    value.update(overrides)
    return value


def test_approval_is_an_authenticated_act_on_one_exact_passed_design():
    _request, two, _three, _duplicate = pool_inputs()
    approval = record_design_approval(approval_value(two, verdict(two)))
    assert type(approval) is DesignApproval
    assert approval.design_ref == two.graph_ref
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(
            two, verdict(two, "rejected"),
        ))
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(
            two, verdict(two, "insufficient_evidence"),
        ))
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(two, verdict(two), approver={
            "actor_id": APPROVER, "authenticated": False,
            "evidence": ref("action_approval", 1101),
        }))
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(object(), verdict(two)))


def test_the_verdict_must_bind_the_exact_approved_candidate():
    _request, two, three, _duplicate = pool_inputs()
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(two, verdict(three)))


def test_preparation_is_compare_and_swap_on_the_environment_head():
    _request, two, three, _duplicate = pool_inputs()
    state = open_environment(ENV_ID)
    approval = record_design_approval(approval_value(two, verdict(two)))
    prepared, state2 = prepare_environment_version(
        state, approval, expected_head=state.head,
    )
    assert type(prepared) is EnvironmentVersion
    assert prepared.status == "prepared"  # never active, never promoted
    assert prepared.version == 1
    assert prepared.design_ref == two.graph_ref
    assert state2.head == 1
    with pytest.raises(EnvironmentContractError):
        # a stale head never prepares (the environment moved)
        prepare_environment_version(state2, approval, expected_head=0)
    other = record_design_approval(approval_value(three, verdict(three)))
    with pytest.raises(EnvironmentContractError):
        # a consumed approval never prepares twice
        prepare_environment_version(state2, approval, expected_head=1)
    prepared2, state3 = prepare_environment_version(
        state2, other, expected_head=1,
    )
    assert prepared2.version == 2
    assert state3.head == 2


def test_a_design_changed_after_approval_never_prepares(monkeypatch):
    _request, two, three, _duplicate = pool_inputs()
    approval = record_design_approval(approval_value(two, verdict(two)))
    # simulate the tamper: an approval object whose design hash no longer
    # matches the candidate being prepared is a different version
    forged = dataclasses.replace  # replace must fail on issued approvals
    with pytest.raises(TypeError):
        forged(approval, design_ref=three.graph_ref)
    state = open_environment(ENV_ID)
    with pytest.raises(EnvironmentContractError):
        prepare_environment_version(
            state, object(), expected_head=state.head,
        )


def test_prepared_versions_and_states_are_issued_values():
    _request, two, _three, _duplicate = pool_inputs()
    state = open_environment(ENV_ID)
    approval = record_design_approval(approval_value(two, verdict(two)))
    prepared, state2 = prepare_environment_version(
        state, approval, expected_head=state.head,
    )
    with pytest.raises(TypeError):
        dataclasses.replace(prepared, status="active")
    with pytest.raises(TypeError):
        dataclasses.replace(state2, head=99)
    with pytest.raises(EnvironmentContractError):
        prepare_environment_version(object(), approval, expected_head=0)
    from app.services import environments

    assert not hasattr(environments, "activate_environment_version")
