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
    design_approval_subject,
    open_environment,
    prepare_environment_version,
    record_design_approval,
)
from app.services.critic_qualification import (
    SUITE_RECORD_SCHEMA_VERSION,
    critic_qualification_from_suite,
    unknown_critic_qualification,
)
from app.services.owner_decisions import OwnerDecision
from app.tests.owner_session import OwnerSession
from app.tests.test_alternatives import ref
from app.tests.test_design_review import pool_inputs, verdict

ENV_ID = "00000000-0000-4000-8000-00000000e001"
CRITIC_DIGEST = "c" * 64


def suite_record(**overrides):
    record = {
        "schema_version": SUITE_RECORD_SCHEMA_VERSION,
        "design_id": "q01-release-v2",
        "configuration_digest": CRITIC_DIGEST,
        "sealed_set_sha256": "d" * 64,
        "suite_verdict": "pass",
        "judge_separation_established": True,
        "record_sha256": "e" * 64,
    }
    record.update(overrides)
    return record


def qualified_critic():
    # A test-actor suite record: no real release suite has passed (T077).
    return critic_qualification_from_suite(suite_record(), CRITIC_DIGEST)

# One real owner session per test module records every design approval in
# the value-level design suites (modules calling approval_value import
# `design_owner`); approvals are never assembled by a test.
SESSION = OwnerSession("design-owner")
design_owner = SESSION.fixture()


def record_owner_decision(subject, decision="approve", subject_kind="design_approval"):
    return SESSION.decide(subject_kind, subject, decision)


def approval_value(candidate, candidate_verdict, **overrides):
    value = {
        "environment": ENV_ID,
        "candidate": candidate,
        "verdict": candidate_verdict,
        "model_bindings": ref("model_choice", 1102),
        "tool_permissions": ref("grant", 1103),
        "observation_contract": ref("observation_contract", 1104),
        "critic_qualification": qualified_critic(),
    }
    decision = overrides.pop("decision", "approve")
    value.update(overrides)
    if "approval" not in value:
        try:
            subject = design_approval_subject(value)
        except EnvironmentContractError:
            # an unbuildable subject (fake candidate/verdict) still gets a
            # recorded decision over some subject so the constructor, not
            # this helper, is what refuses the value
            subject = {"unbuildable": True}
        value["approval"] = record_owner_decision(subject, decision)
    return value


def test_approval_is_an_authenticated_act_on_one_exact_passed_design():
    _request, two, _three, _duplicate = pool_inputs()
    decision = record_owner_decision(design_approval_subject(approval_value(two, verdict(two))))
    approval = record_design_approval(approval_value(two, verdict(two), approval=decision))
    assert type(approval) is DesignApproval
    assert approval.design_ref == two.graph_ref
    # the approver, evidence and time are the owner's recorded act
    assert approval.approver_id == decision.actor_ref.id
    assert approval.approver_evidence == decision.approval_ref
    assert approval.approved_at == decision.decided_at_utc
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(
            two, verdict(two, "rejected"),
        ))
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(
            two, verdict(two, "insufficient_evidence"),
        ))
    with pytest.raises(EnvironmentContractError):
        # a caller-declared approver is not evidence
        record_design_approval(approval_value(two, verdict(two), approval={
            "actor_id": decision.actor_ref.id, "authenticated": True,
            "evidence": decision.approval_ref,
        }))
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(two, verdict(two), approval=None))
    with pytest.raises(EnvironmentContractError):
        # a recorded reject approves nothing
        record_design_approval(approval_value(two, verdict(two), decision="reject"))
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(object(), verdict(two)))
    with pytest.raises(EnvironmentContractError):
        # the decision object keeps no caller-declared time
        record_design_approval(
            approval_value(two, verdict(two)) | {"approved_at": "2026-09-13T08:00:00.000000Z"}
        )


def test_the_owner_decision_must_be_over_this_exact_design_subject():
    _request, two, three, _duplicate = pool_inputs()
    value = approval_value(two, verdict(two))
    subject = design_approval_subject(value)
    # identities bind the entity kind too (as a sibling field, never the
    # four-key reference shape the store would try to resolve)
    assert subject["design"]["entity_kind"] == two.graph_ref.kind
    assert subject["model_bindings"]["entity_kind"] == "model_choice"
    assert "kind" not in subject["design"]
    for other in (
        design_approval_subject(approval_value(three, verdict(three))),  # another design
        design_approval_subject(approval_value(two, verdict(two), environment=ENV_ID[:-1] + "2")),
        design_approval_subject(approval_value(two, verdict(two), model_bindings=ref("model_choice", 1199))),
        subject | {"candidate_version": subject["candidate_version"] + 1},
    ):
        assert other != subject
        with pytest.raises(EnvironmentContractError):
            record_design_approval(value | {"approval": record_owner_decision(other)})
    with pytest.raises(EnvironmentContractError):
        # a decision of another subject kind over the same digest is not a
        # design approval
        record_design_approval(value | {"approval": record_owner_decision(subject, subject_kind="deletion")})
    forged = object.__new__(OwnerDecision)
    genuine = record_owner_decision(subject)
    for name in OwnerDecision.__slots__:
        object.__setattr__(forged, name, getattr(genuine, name))
    object.__setattr__(forged, "_issuer_token", object())
    with pytest.raises(EnvironmentContractError):
        record_design_approval(value | {"approval": forged})
    assert record_design_approval(value | {"approval": genuine}).approver_evidence == genuine.approval_ref


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


@pytest.mark.parametrize("critic, reason", [
    (lambda: unknown_critic_qualification(CRITIC_DIGEST), "unknown: no_suite_record"),
    (lambda: critic_qualification_from_suite(suite_record(design_id="q01-calibration-v1"), CRITIC_DIGEST),
     "unqualified: not_a_frozen_release_design"),
    (lambda: critic_qualification_from_suite(suite_record(suite_verdict="fail"), CRITIC_DIGEST),
     "unqualified: suite_fail"),
    (lambda: critic_qualification_from_suite(suite_record(suite_verdict="incomplete"), CRITIC_DIGEST),
     "unqualified: suite_incomplete"),
    (lambda: critic_qualification_from_suite(suite_record(judge_separation_established=False), CRITIC_DIGEST),
     "unqualified: judge_separation_not_established"),
    (lambda: critic_qualification_from_suite(suite_record(configuration_digest="f" * 64), CRITIC_DIGEST),
     "unknown: suite_is_for_another_configuration"),
])
def test_a_passed_verdict_from_an_unqualified_critic_is_never_approvable(critic, reason):
    _request, two, _three, _duplicate = pool_inputs()
    with pytest.raises(EnvironmentContractError, match=reason):
        design_approval_subject(approval_value(two, verdict(two), critic_qualification=critic()))
    with pytest.raises(EnvironmentContractError, match=reason):
        record_design_approval(approval_value(two, verdict(two), critic_qualification=critic()))


def test_a_look_alike_qualification_is_refused_and_the_approval_binds_the_record():
    _request, two, _three, _duplicate = pool_inputs()
    fake = object.__new__(type(qualified_critic()))
    for name, item in qualified_critic().as_dict().items():
        if name != "schema_version":
            object.__setattr__(fake, name, item)
    with pytest.raises(EnvironmentContractError, match="qualification state is required"):
        design_approval_subject(approval_value(two, verdict(two), critic_qualification=fake))
    approval = record_design_approval(approval_value(two, verdict(two)))
    assert approval.critic_qualification["record_sha256"] == "e" * 64
    assert approval.as_dict()["critic_qualification"]["status"] == "qualified"
