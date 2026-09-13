"""B4 critic lineage: exact-hash parent binding, no forged cross-call
evidence (T032).

Every downstream critic call binds its parent by request id AND by the
exact hash of the evidence that parent actually produced: a proposal binds
its review; a validity call binds its proposal plus the SHA-256 of the
counterexample as recorded from the proposal's completed result; a
response binds its validity plus that result's hash. A hash never recorded
under that exact parent, a parent that never completed, a parent from a
different run or candidate, or a parent of the wrong purpose is forged
cross-call evidence and refuses the reservation.
"""

from hashlib import sha256

import pytest

from app.critic_audit import FrozenCall, Ledger, canonical


def frozen(request_id, purpose, *, run="run-1", candidate="cand-1"):
    return FrozenCall(
        request_id=request_id,
        run_id=run,
        purpose=purpose,
        candidate_id=candidate,
        candidate_version="1",
        prompt='{"input": {}}',
        schema_json=canonical({"a": 1}),
        manifest_json=canonical({"b": 2}),
        selection_json=canonical({"c": 3}),
        metadata_json=canonical({"d": 4}),
    )


@pytest.fixture
def ledger(tmp_path):
    journal = Ledger(tmp_path / "audit" / "eval.sqlite3")
    journal.open_run("run-1", max_calls=32, max_seconds=600)
    journal.open_run("run-2", max_calls=32, max_seconds=600)
    return journal


def completed_review(ledger, request_id="req-review"):
    ledger.reserve(frozen(request_id, "review"))
    ledger.begin(request_id)
    ledger.finish(request_id, "completed", {"findings": 3})
    return request_id


def completed_proposal(ledger, counterexample):
    review = completed_review(ledger)
    ledger.reserve_with_lineage(
        frozen("req-proposal", "counterexample_proposal"),
        parent_request_id=review, evidence_sha=None,
    )
    ledger.begin("req-proposal")
    ledger.finish("req-proposal", "completed", {"status": "proposed"})
    shas = ledger.register_result_evidence("req-proposal", [counterexample])
    return "req-proposal", shas[0]


def test_the_chain_binds_by_request_and_exact_hash(ledger):
    counterexample = {"id": "ce-1", "claim": "검증 없는 주장"}
    proposal, cex_sha = completed_proposal(ledger, counterexample)
    assert cex_sha == sha256(
        canonical(counterexample).encode("utf-8"),
    ).hexdigest()
    ledger.reserve_with_lineage(
        frozen("req-validity", "counterexample_validity"),
        parent_request_id=proposal, evidence_sha=cex_sha,
    )
    ledger.begin("req-validity")
    ledger.finish("req-validity", "completed", {"status": "valid"})
    validity_shas = ledger.register_result_evidence(
        "req-validity", [{"status": "valid", "counterexample_id": "ce-1"}],
    )
    ledger.reserve_with_lineage(
        frozen("req-response", "candidate_response"),
        parent_request_id="req-validity", evidence_sha=validity_shas[0],
    )


def test_a_hash_the_parent_never_produced_is_forged(ledger):
    proposal, _cex_sha = completed_proposal(ledger, {"id": "ce-1"})
    forged = sha256(canonical({"id": "ce-FAKE"}).encode("utf-8")).hexdigest()
    with pytest.raises(ValueError):
        ledger.reserve_with_lineage(
            frozen("req-validity", "counterexample_validity"),
            parent_request_id=proposal, evidence_sha=forged,
        )


def test_an_unfinished_parent_never_grounds_a_child(ledger):
    review = completed_review(ledger)
    ledger.reserve_with_lineage(
        frozen("req-proposal", "counterexample_proposal"),
        parent_request_id=review, evidence_sha=None,
    )  # reserved, never completed
    with pytest.raises(ValueError):
        ledger.register_result_evidence("req-proposal", [{"id": "ce-1"}])
    with pytest.raises(ValueError):
        ledger.reserve_with_lineage(
            frozen("req-validity", "counterexample_validity"),
            parent_request_id="req-proposal", evidence_sha="ab" * 32,
        )


def test_cross_run_and_cross_candidate_parents_are_forged(ledger):
    proposal, cex_sha = completed_proposal(ledger, {"id": "ce-1"})
    with pytest.raises(ValueError):
        ledger.reserve_with_lineage(
            frozen("req-v2", "counterexample_validity", run="run-2"),
            parent_request_id=proposal, evidence_sha=cex_sha,
        )
    with pytest.raises(ValueError):
        ledger.reserve_with_lineage(
            frozen("req-v3", "counterexample_validity",
                   candidate="cand-OTHER"),
            parent_request_id=proposal, evidence_sha=cex_sha,
        )


def test_the_parent_purpose_must_match_the_chain(ledger):
    review = completed_review(ledger)
    with pytest.raises(ValueError):
        # a validity call can never claim a review as its proposal parent
        ledger.reserve_with_lineage(
            frozen("req-validity", "counterexample_validity"),
            parent_request_id=review, evidence_sha="ab" * 32,
        )
    with pytest.raises(ValueError):
        # a review has no lineage parent at all
        ledger.reserve_with_lineage(
            frozen("req-review-2", "review"),
            parent_request_id=review, evidence_sha=None,
        )
    with pytest.raises(ValueError):
        # a proposal never carries an evidence hash (its parent is a review)
        ledger.reserve_with_lineage(
            frozen("req-p2", "counterexample_proposal"),
            parent_request_id=review, evidence_sha="ab" * 32,
        )


def test_evidence_registration_is_bounded_and_exact(ledger):
    proposal, _sha = completed_proposal(ledger, {"id": "ce-1"})
    with pytest.raises(ValueError):
        ledger.register_result_evidence(proposal, [])
    with pytest.raises(ValueError):
        ledger.register_result_evidence("missing-request", [{"id": "x"}])
    with pytest.raises(ValueError):
        ledger.register_result_evidence(proposal, ["not-a-dict"])
