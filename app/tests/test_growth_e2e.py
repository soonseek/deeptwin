"""T067: US6 recovery/loop/heldout/approval cases over the supported app, for the parts
the browser cannot reach (growth.md §9 G-08/G-10/G-12/G-13).

One supported app (owner session, versions-v1 routes) over a durable chain seeded
through the real services (app/tests/growth_chain_fixture.py: isolated paired
execution on the real scheduler, persisted rounds, CAS loop revisions, sealed
validation). Every fact is synthetic and authored by the vault's test actor.
"""

from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.services.growth import GrowthLoopError, apply_round
from app.services.growth_store import (
    GrowthStoreError,
    persist_loop_state,
    resume_dataset_ledger,
    resume_loop,
    resume_validation_report,
)
from app.services.promotion import (
    PromotionError,
    activate_candidate,
    open_promotion_state,
    record_promotion_decision,
)
from app.services.promotion_approvals import PersistentPromotionApprovals
from app.services.validation import GrowthValidationError, run_validation
from app.tests import growth_chain_fixture as chain
from app.tests.test_versions_api import call, read
from app.tests.test_works_api import owner_app


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    root = tmp_path_factory.mktemp("growth-e2e")
    with owner_app(root) as subject:
        facts = chain.seed(subject.domain, root / "reset")
        adopted = call(subject, "adopt", {"environment_ref": facts["operating_environment_ref"]})
        assert adopted.status_code == 200, adopted.text
        yield subject, facts


def _item(subject, report_ref):
    return next(item for item in read(subject).json()["candidates"]
                if item.get("validation_report_ref") == report_ref)


def _approve(subject, facts, name):
    report = facts["candidates"][name]["validation_report_ref"]
    answer = call(subject, "decisions", {"command_id": str(uuid4()), "decision": "approve",
                                         "validation_report_ref": report})
    assert answer.status_code == 200, answer.text
    return answer.json()["approval_ref"]


def _resolve(subject, approval_ref):
    """The owner's recorded approval, resolved by the same producer the route uses."""

    return PersistentPromotionApprovals(subject.domain, subject.app.state.owner_authority).resolve(
        EntityRef.from_dict(approval_ref))


def test_g08_invalid_rounds_are_never_scored_or_counted_and_duplicates_are_refused(seeded):
    subject, facts = seeded
    plateau = facts["lineages"][chain.PLATEAU]
    assert plateau["validities"] == ["valid", "invalid", "valid", "invalid", "valid", "valid"]
    rounds = [item for item in read(subject).json()["rounds"] if item["lineage_id"] == chain.PLATEAU]
    for item in rounds:
        if item["validity"] != "valid":
            assert item["utility"] is None and item["metric_vector"] is None and item["validity_reasons"]
    # six completed rounds, three counted: the two invalid ones changed no counter
    assert len(plateau["completed_round_ids"]) == 6 and plateau["non_improving_valid_count"] == 3
    state = resume_loop(subject.domain, EntityRef.from_dict(plateau["loop_heads"][-1]))
    with pytest.raises(GrowthLoopError):  # a terminal loop accepts no late result
        apply_round(state, {"round_id": "late", "validity": "valid", "utility": "0.99",
                            "mandatory_passed": True, "regression_ok": True, "consumed": {}})
    running = facts["lineages"][chain.NEW]
    heads = [EntityRef.from_dict(item) for item in running["loop_heads"]]
    live = resume_loop(subject.domain, heads[-1])
    with pytest.raises(GrowthLoopError):  # the same round result never applies twice
        apply_round(live, {"round_id": live.completed_round_ids[-1], "validity": "valid", "utility": "0.99",
                           "mandatory_passed": True, "regression_ok": True, "consumed": {}})
    forked = apply_round(resume_loop(subject.domain, heads[-2]), {
        "round_id": "re-dispatched", "validity": "valid", "utility": "0.99", "mandatory_passed": True,
        "regression_ok": True, "consumed": {}})
    with pytest.raises(GrowthStoreError):  # a second writer from the older revision collides
        persist_loop_state(subject.domain, forked, parent_ref=heads[-2], **chain.marks(subject.domain))
    assert resume_loop(subject.domain, heads[-1]).as_dict() == live.as_dict()


def test_g10_a_changed_evaluator_is_a_new_lineage_that_reuses_nothing(seeded):
    subject, facts = seeded
    old, new = facts["lineages"][chain.OLD], facts["lineages"][chain.NEW]
    assert old["stop_reason"] == "lineage_changed" and old["non_improving_valid_count"] == 1
    assert new["status"] == "running" and new["non_improving_valid_count"] == 0
    assert set(new["completed_round_ids"]).isdisjoint(old["completed_round_ids"])
    # the baseline was run again under the new plan: no run is shared with the old lineage
    old_runs = {run["id"] for pair in old["baseline_runs"] for run in pair}
    assert old_runs.isdisjoint(run["id"] for pair in new["baseline_runs"] for run in pair)
    # a candidate bound to the changed evaluation policy is another bundle: the old
    # validation report and an approval over it back nothing for it
    p = facts["candidates"]["P"]
    candidate, report = resume_validation_report(subject.domain, EntityRef.from_dict(p["report_record"]))
    rebound = chain.bundle(candidate.candidate.as_dict(), prompts=67951, evaluation_policy=67917)
    assert rebound.bundle_ref != candidate.bundle_ref
    approval_ref = _approve(subject, facts, "P")
    approval = _resolve(subject, approval_ref)
    with pytest.raises(PromotionError):
        record_promotion_decision({
            "candidate": rebound, "validation_report": report, "scope": rebound.scope.as_dict(),
            "approval": approval, "expected_current_environment": facts["operating_environment_ref"],
            "rollback_bundle": rebound.rollback_bundle.as_dict()})


def test_g12_a_candidate_edited_after_review_gets_no_unseen_pass(seeded):
    subject, facts = seeded
    edited = facts["edited_q"]
    assert edited["sealed_q_classification"] == "tuning" and edited["sealed_q_seen"] is True
    assert edited["unseen_after_review"] == []
    assert edited["unseen_pass"].startswith("refused:")
    ledger = resume_dataset_ledger(subject.domain, EntityRef.from_dict(edited["reviewed_ledger_record"]))
    assert [entry["classification"] for entry in ledger.as_dict()["entries"]] == ["tuning"]
    q = facts["candidates"]["Q"]
    candidate, _report = resume_validation_report(subject.domain, EntityRef.from_dict(q["report_record"]))
    with pytest.raises(GrowthValidationError):  # even the unedited candidate gets no second claim
        run_validation(candidate, ledger, {"mode": "sealed_offline", "datasets": ["sealed-q"],
                                           "approved_scope": None, "gates": {}})
    listed = read(subject).json()["candidates"]
    assert edited["bundle_ref"] not in [item.get("candidate_bundle_ref") for item in listed]
    assert _item(subject, q["validation_report_ref"])["approvable"] is False


def test_g13_a_tampered_bundle_never_applies_under_the_approval(seeded):
    subject, facts = seeded
    approval_ref = _approve(subject, facts, "P")
    approval = _resolve(subject, approval_ref)
    p = facts["candidates"]["P"]
    candidate, report = resume_validation_report(subject.domain, EntityRef.from_dict(p["report_record"]))
    tampered = chain.bundle(candidate.candidate.as_dict(), prompts=67999)  # a prompt changed after approval
    before = read(subject).json()["state"]
    with pytest.raises(PromotionError):
        record_promotion_decision({
            "candidate": tampered, "validation_report": report, "scope": tampered.scope.as_dict(),
            "approval": approval, "expected_current_environment": before["current_environment_ref"],
            "rollback_bundle": tampered.rollback_bundle.as_dict()})
    decision = record_promotion_decision({
        "candidate": candidate, "validation_report": report, "scope": candidate.scope.as_dict(),
        "approval": approval, "expected_current_environment": before["current_environment_ref"],
        "rollback_bundle": candidate.rollback_bundle.as_dict()})
    with pytest.raises(PromotionError):  # the decision over P never activates another bundle
        activate_candidate(open_promotion_state(before["current_environment_ref"]), decision, tampered)
    assert read(subject).json()["state"] == before  # nothing was applied, nothing else promoted


def test_g13_an_approval_given_before_the_version_changed_never_applies_later(seeded):
    """A→B→A: P and R are approved against the adopted version; R is applied and then
    rolled back, so the adopted version is current again — P's old approval was given
    over a state that has since changed and must be given again (re-review)."""

    subject, facts = seeded
    p_approval = _approve(subject, facts, "P")
    r_approval = _approve(subject, facts, "R")
    applied = call(subject, "activate", {"approval_ref": r_approval, "expected_revision": 1})
    assert applied.status_code == 200, applied.text
    assert applied.json()["state"]["current_environment_ref"] == facts["candidates"]["R"]["bundle_ref"]
    assert call(subject, "activate", {"approval_ref": p_approval, "expected_revision": 2}).status_code == 409
    rolled = call(subject, "rollback", {"reason": "합성 사례: 보고서 품질 저하", "expected_revision": 2})
    assert rolled.status_code == 200, rolled.text
    state = rolled.json()["state"]
    assert state["current_environment_ref"] == facts["operating_environment_ref"]
    assert state["external_effects_reverted"] is False
    stale = call(subject, "activate", {"approval_ref": p_approval, "expected_revision": 3})
    assert stale.status_code == 409, stale.text
    assert call(subject, "activate", {"approval_ref": r_approval, "expected_revision": 3}).status_code == 409
    assert read(subject).json()["state"] == state  # nothing auto-promoted
    # a fresh approval over the current state is the owner's re-review, and applies
    fresh = _approve(subject, facts, "P")
    again = call(subject, "activate", {"approval_ref": fresh, "expected_revision": 3})
    assert again.status_code == 200, again.text
    assert again.json()["state"]["current_environment_ref"] == facts["candidates"]["P"]["bundle_ref"]


def test_every_executed_round_keeps_both_sides_outputs_side_by_side(seeded):
    # T066: the isolated runs are removed after each round; what each side produced is kept
    # beside the round record, so the two can be read side by side
    subject, _facts = seeded
    rounds = [item for item in read(subject).json()["rounds"] if item["readable"]]
    assert rounds and all(isinstance(item["outputs"], list) and item["outputs"] for item in rounds)
    for item in rounds:
        for output in item["outputs"]:
            baseline = {entry["node_id"] for entry in output["baseline"]}
            candidate = {entry["node_id"] for entry in output["candidate"]}
            assert set(output["changed_nodes"]) <= baseline | candidate
            assert all(entry["result_text"] and entry["result_bytes"] > 0 for entry in output["baseline"])
    # a valid round's candidate changed the declared writer node
    valid = next(item for item in rounds if item["validity"] == "valid")
    assert "writer" in valid["outputs"][0]["changed_nodes"]
