"""Regression tests for the design-batch adversarial audit (2026-09-13).

F1/F2: the inputs of record — CandidateVerdict, CriticismCallRecord,
CriticismRunResult — are now issued values: the fold and the driver are
their only issuers, public construction and dataclasses.replace fail, and
the pool, the approval and the persistence path all refuse look-alikes, so
an unreviewed design can neither pool, nor approve, nor acquire durable
fake review evidence. F3: a refused criticism run stores nothing — the
candidate-record binding and the fold recompute run before the first put.
F4: an approval binds one environment and never prepares another. F5: a
verdict binds its candidate by content hash, not by name — a verdict earned
by design A never approves design B. F6: the pool and every derivation bind
one exact generation request, and a merge needs distinct parents. F7: the
structural-duplicate choice is deterministic, not caller-order-controlled.
F10: the durable approval names the verdict that justified it.
"""

import dataclasses

import pytest

from app.services.design_criticism import CandidateVerdict
from app.services.design_criticism_live import (
    CriticismCallRecord,
    CriticismRunResult,
)
from app.services.design_review import (
    DesignReviewError,
    assemble_selection_pool,
    derive_design_version,
)
from app.services.environments import (
    EnvironmentContractError,
    open_environment,
    prepare_environment_version,
    record_design_approval,
)
from app.tests.test_design_review import pool_inputs, verdict
from app.tests.test_environments import (  # noqa: F401 - design_owner is an autouse fixture
    ENV_ID,
    approval_value,
    design_owner,
)


def test_f1_verdicts_and_run_records_are_issued_never_constructed():
    with pytest.raises(TypeError):
        CandidateVerdict(
            candidate_id="00000000-0000-4000-8000-000000000231",
            candidate_version="1",
            candidate_sha="ab" * 32,
            status="passed",
            reasons=(),
        )
    real = verdict_for_pool()
    with pytest.raises(TypeError):
        dataclasses.replace(real, status="passed")
    with pytest.raises(TypeError):
        CriticismCallRecord(
            call_id="00000000-0000-4000-8000-000000000900",
            version=1,
            request_ref=None,
            purpose="review",
            profile_digest="ab" * 32,
            model_id="m",
            prompt_sha256="ab" * 32,
            response_sha256="ab" * 32,
        )
    with pytest.raises(TypeError):
        CriticismRunResult(
            verdict=real, review={}, chains=(), call_records=(),
        )


def verdict_for_pool():
    _request, two, _three, _duplicate = pool_inputs()
    return verdict(two)


def test_f1_the_pool_and_the_approval_refuse_lookalike_verdicts():
    request, two, _three, _duplicate = pool_inputs()

    class FakeVerdict:
        candidate_id = two.candidate_id
        candidate_version = str(two.version)
        candidate_sha = two.graph_ref.sha256
        status = "passed"
        reasons = ()

    with pytest.raises(DesignReviewError):
        assemble_selection_pool(request, [(two, FakeVerdict())])
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(two, FakeVerdict()))


def test_f5_a_verdict_never_transplants_onto_a_different_design():
    request, two, three, _duplicate = pool_inputs()
    earned_by_two = verdict(two)
    # same ids could collide across designs; the content hash cannot
    assert earned_by_two.candidate_sha == two.graph_ref.sha256
    assert earned_by_two.candidate_sha != three.graph_ref.sha256
    with pytest.raises(EnvironmentContractError):
        record_design_approval(approval_value(three, earned_by_two))
    with pytest.raises(DesignReviewError):
        assemble_selection_pool(request, [(three, earned_by_two)])


def test_f6_the_pool_and_derivations_bind_one_exact_request():
    request, two, three, _duplicate = pool_inputs()
    other_request, other, _o3, _od = pool_inputs(request_id_suffix=240)
    with pytest.raises(DesignReviewError):
        assemble_selection_pool(request, [(other, verdict(other))])
    with pytest.raises(DesignReviewError):
        derive_design_version(request, "merge", [two, other])
    with pytest.raises(DesignReviewError):
        # a merge requires DISTINCT parents
        derive_design_version(request, "merge", [two, two])
    merged = derive_design_version(request, "merge", [two, three])
    assert merged.request_ref == request.request_ref
    del other_request


def test_f7_structural_duplicate_choice_is_not_caller_ordered():
    request, two, _three, duplicate = pool_inputs()
    forward = assemble_selection_pool(
        request, [(two, verdict(two)), (duplicate, verdict(duplicate))],
    )
    reversed_pool = assemble_selection_pool(
        request, [(duplicate, verdict(duplicate)), (two, verdict(two))],
    )
    assert [c.candidate_id for c in forward.presented] == [
        c.candidate_id for c in reversed_pool.presented
    ]


def test_f4_an_approval_binds_one_environment_only():
    _request, two, _three, _duplicate = pool_inputs()
    approval = record_design_approval(approval_value(two, verdict(two)))
    assert approval.environment_id == ENV_ID
    other_env = open_environment("00000000-0000-4000-8000-00000000e005")
    with pytest.raises(EnvironmentContractError):
        prepare_environment_version(
            other_env, approval, expected_head=other_env.head,
        )


def test_f10_the_durable_approval_names_its_verdict():
    _request, two, _three, _duplicate = pool_inputs()
    passed = verdict(two)
    approval = record_design_approval(approval_value(two, passed))
    payload = approval.as_dict()
    assert payload["verdict_sha"] == approval.verdict_sha
    assert len(approval.verdict_sha) == 64
