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
from contextlib import contextmanager

import pytest

from app.services import critic_qualification as gate
from app.services.critic_qualification import (
    SUITE_RECORD_SCHEMA_VERSION,
    CriticQualificationError,
    critic_qualification_from_suite,
    suite_record_sha256,
    unknown_critic_qualification,
)
from app.services.environments import (
    DesignApproval,
    EnvironmentContractError,
    EnvironmentVersion,
    design_approval_subject,
    open_environment,
    prepare_environment_version,
    record_design_approval,
)
from app.services.owner_decisions import OwnerDecision
from app.tests.owner_session import OwnerSession
from app.tests.test_alternatives import ref
from app.tests.test_design_review import pool_inputs, verdict

ENV_ID = "00000000-0000-4000-8000-00000000e001"
CRITIC_DIGEST = "c" * 64
# TEST-ACTOR design id: no frozen design uses it, and production code never
# admits it (critic_qualification._TEST_ACTOR_V3_DESIGN_IDS is empty outside
# ``actor_v3_design``, and it is honoured only while pytest runs a test). No
# production record can be ``qualified``: V3_VERIFYING_DESIGN_IDS is empty and
# release-v5 cannot verify V3 (audits 3 and 4).
TEST_ACTOR_DESIGN = "test-actor-v3-verifying-design"


@contextmanager
def actor_v3_design():
    """Admit the test-only V3-verifying design id for the duration of a block."""
    previous = gate._TEST_ACTOR_V3_DESIGN_IDS
    gate._TEST_ACTOR_V3_DESIGN_IDS = frozenset({TEST_ACTOR_DESIGN})
    try:
        yield
    finally:
        gate._TEST_ACTOR_V3_DESIGN_IDS = previous


def suite_record(**overrides):
    record = {
        "schema_version": SUITE_RECORD_SCHEMA_VERSION,
        "design_id": "q01-release-v5",
        "critic_configuration_digest": CRITIC_DIGEST,
        "pre_dispatch_manifest_sha256": "a" * 64,
        "sealed_set_sha256": "d" * 64,
        "attempt": 1,
        "prior_outcomes": [],
        "suite_outcome": "pass",
        "independence_profile_sha256": "b" * 64,
        "judge_separation_established": True,
        "v3_error_independence": "unverified",
        "prior_sealed_set_sha256s": [],
        "prior_attempts_sha256": "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945",
        "dispatch_journal_head": "e" * 64,
        "manifest_commit_ref": {"kind": "git_commit", "ref": "0123456789abcdef0123456789abcdef01234567"},
    }
    record.update(overrides)
    if "record_sha256" not in overrides:
        record["record_sha256"] = suite_record_sha256(record)
    return record


def actor_record(**overrides):
    return suite_record(**{"design_id": TEST_ACTOR_DESIGN, "v3_error_independence": "verified", **overrides})


def qualified_critic():
    # A TEST-ACTOR qualification: a record of the test-only V3-verifying design
    # id, admitted only inside ``actor_v3_design``. No real release suite
    # has passed, no design can verify V3, and V3 is unverified (T077).
    with actor_v3_design():
        return critic_qualification_from_suite(actor_record(), CRITIC_DIGEST)

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
    (lambda: critic_qualification_from_suite(suite_record(design_id="q01-release-v2"), CRITIC_DIGEST),
     "unqualified: not_a_frozen_release_design"),
    (lambda: critic_qualification_from_suite(suite_record(design_id="q01-release-v3"), CRITIC_DIGEST),
     "unqualified: not_a_frozen_release_design"),
    (lambda: critic_qualification_from_suite(suite_record(), CRITIC_DIGEST),
     "scoped_pass: design_cannot_verify_v3"),
    (lambda: critic_qualification_from_suite(suite_record(design_id="q01-release-v4"), CRITIC_DIGEST),
     "unqualified: not_a_frozen_release_design"),
    # the test-actor design id is refused outside the test-actor hook
    (lambda: critic_qualification_from_suite(actor_record(), CRITIC_DIGEST),
     "unqualified: not_a_frozen_release_design"),
    (lambda: critic_qualification_from_suite(suite_record(suite_outcome="not_judged"), CRITIC_DIGEST),
     "unqualified: suite_not_judged"),
    (lambda: critic_qualification_from_suite(suite_record(suite_outcome="fail"), CRITIC_DIGEST),
     "unqualified: suite_fail"),
    (lambda: critic_qualification_from_suite(suite_record(suite_outcome="incomplete"), CRITIC_DIGEST),
     "unqualified: suite_incomplete"),
    (lambda: critic_qualification_from_suite(suite_record(judge_separation_established=False), CRITIC_DIGEST),
     "unqualified: judge_separation_not_established"),
    (lambda: critic_qualification_from_suite(suite_record(critic_configuration_digest="f" * 64), CRITIC_DIGEST),
     "unknown: suite_is_for_another_configuration"),
])
def test_a_passed_verdict_from_an_unqualified_critic_is_never_approvable(critic, reason):
    _request, two, _three, _duplicate = pool_inputs()
    with pytest.raises(EnvironmentContractError, match=reason):
        design_approval_subject(approval_value(two, verdict(two), critic_qualification=critic()))
    with pytest.raises(EnvironmentContractError, match=reason):
        record_design_approval(approval_value(two, verdict(two), critic_qualification=critic()))


def test_the_production_gate_can_never_yield_qualified():
    # BF1: no design is declared able to verify V3, and the test-actor hook is
    # empty outside tests; every production-shaped pass is at most scoped.
    assert gate.V3_VERIFYING_DESIGN_IDS == frozenset()
    assert gate._TEST_ACTOR_V3_DESIGN_IDS == frozenset()
    assert gate.RELEASE_DESIGN_IDS == {"q01-release-v5"}
    state = critic_qualification_from_suite(suite_record(), CRITIC_DIGEST)
    assert state.status == "scoped_pass"
    # audit 4, N5: a v5 record claiming V3 verified is not schema-valid and is refused, not capped
    with pytest.raises(CriticQualificationError, match="V3 unverified"):
        critic_qualification_from_suite(suite_record(v3_error_independence="verified"), CRITIC_DIGEST)
    with actor_v3_design():
        # even under the hook a record of the test-actor design must say V3 verified
        state = critic_qualification_from_suite(actor_record(v3_error_independence="unverified"),
                                                CRITIC_DIGEST)
        assert (state.status, state.reason) == ("scoped_pass", "v3_error_independence_unverified")
    assert gate._TEST_ACTOR_V3_DESIGN_IDS == frozenset()


def test_the_test_actor_hook_is_honoured_only_under_pytest(monkeypatch):
    # audit 4, N5: outside a running pytest test the hook admits nothing, so even a
    # test-actor record set up by the hook stays unqualified in production
    with actor_v3_design():
        assert critic_qualification_from_suite(actor_record(), CRITIC_DIGEST).status == "qualified"
        monkeypatch.delenv("PYTEST_CURRENT_TEST")
        state = critic_qualification_from_suite(actor_record(), CRITIC_DIGEST)
        assert (state.status, state.reason) == ("unqualified", "not_a_frozen_release_design")
        with pytest.raises(CriticQualificationError, match="V3 unverified"):
            critic_qualification_from_suite(suite_record(v3_error_independence="verified"), CRITIC_DIGEST)
    previous = gate._TEST_ACTOR_V3_DESIGN_IDS
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "hook test")
    try:
        gate._TEST_ACTOR_V3_DESIGN_IDS = frozenset({"q01-release-v5"})  # a hook naming a release design
        with pytest.raises(CriticQualificationError, match="test-only"):
            critic_qualification_from_suite(suite_record(), CRITIC_DIGEST)
    finally:
        gate._TEST_ACTOR_V3_DESIGN_IDS = previous


@pytest.mark.parametrize("overrides, match", [
    ({"prior_sealed_set_sha256s": ["d" * 64], "attempt": 2, "prior_outcomes": ["fail"]}, "already spent"),
    ({"attempt": 2, "prior_outcomes": ["fail"]}, "prior attempt"),
    ({"prior_sealed_set_sha256s": "none"}, "prior attempt"),
    ({"prior_attempts_sha256": "x"}, "prior attempts sha256"),
    ({"dispatch_journal_head": None}, "journal head"),
    ({"dispatch_journal_head": "E" * 64}, "journal head"),
    ({"manifest_commit_ref": None}, "commit reference"),
    ({"manifest_commit_ref": {"kind": "git_commit", "ref": "not-hex"}}, "commit reference"),
    ({"manifest_commit_ref": {"kind": "rumour", "ref": "x"}}, "commit reference"),
])
def test_a_schema_invalid_v5_record_is_refused(overrides, match):
    # audit 4 (B2, N3, N5): the gate refuses a v5 record whose set was spent by a listed prior
    # attempt, that lists no prior sets, or that passes without a journal head or commit reference
    with pytest.raises(CriticQualificationError, match=match):
        critic_qualification_from_suite(suite_record(**overrides), CRITIC_DIGEST)
    # the same fields on a non-pass record that is otherwise valid are still checked
    if overrides.get("dispatch_journal_head", "e" * 64) is None or overrides.get("manifest_commit_ref", 1) is None:
        state = critic_qualification_from_suite(suite_record(suite_outcome="incomplete", **overrides), CRITIC_DIGEST)
        assert (state.status, state.reason) == ("unqualified", "suite_incomplete")


def test_a_forged_record_sha256_is_refused():
    # BF1 probe: record_sha256 is recomputed from the record, never trusted
    with pytest.raises(CriticQualificationError, match="record sha256"):
        critic_qualification_from_suite(suite_record(record_sha256="e" * 64), CRITIC_DIGEST)
    edited = suite_record(judge_separation_established=False)
    edited["judge_separation_established"] = True
    with pytest.raises(CriticQualificationError, match="record sha256"):
        critic_qualification_from_suite(edited, CRITIC_DIGEST)
    with actor_v3_design(), pytest.raises(CriticQualificationError, match="record sha256"):
        critic_qualification_from_suite(actor_record(record_sha256="e" * 64), CRITIC_DIGEST)


def test_a_look_alike_qualification_is_refused_and_the_approval_binds_the_record():
    _request, two, _three, _duplicate = pool_inputs()
    fake = object.__new__(type(qualified_critic()))
    for name, item in qualified_critic().as_dict().items():
        if name != "schema_version":
            object.__setattr__(fake, name, item)
    with pytest.raises(EnvironmentContractError, match="qualification state is required"):
        design_approval_subject(approval_value(two, verdict(two), critic_qualification=fake))
    approval = record_design_approval(approval_value(two, verdict(two)))
    assert approval.critic_qualification["record_sha256"] == actor_record()["record_sha256"]
    assert approval.critic_qualification["design_id"] == TEST_ACTOR_DESIGN
    assert approval.as_dict()["critic_qualification"]["status"] == "qualified"


def test_a_suite_record_must_list_every_prior_attempt():
    with actor_v3_design():
        with pytest.raises(CriticQualificationError, match="prior outcomes"):
            critic_qualification_from_suite(actor_record(attempt=2), CRITIC_DIGEST)
        later = critic_qualification_from_suite(actor_record(attempt=2, prior_outcomes=["fail"],
                                                             prior_sealed_set_sha256s=["9" * 64]),
                                                CRITIC_DIGEST)
    assert later.status == "qualified"
