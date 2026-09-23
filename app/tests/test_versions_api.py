"""T066 server half: the owner's operating versions over the durable US6 chain.

The owner adopts the current environment once; a persisted candidate (its frozen
bundle, the rounds its gates cite and its validation report all resume exactly) is
listed with its gates; only a passed sealed-offline candidate can be approved; an
approval is bound to the candidate, the report the owner saw and the current
environment, and is applied exactly once; a rollback states its reason, restores
the last retired version, and never claims to undo external effects.
"""

from uuid import uuid4

from app.services.comparisons import freeze_comparison_plan, record_comparison_round
from app.services.growth_store import (
    persist_comparison_plan,
    persist_comparison_round,
    persist_frozen_candidate,
    persist_validation_report,
)
from app.services.validation import freeze_candidate, run_validation
from app.tests.test_alternatives import ref
from app.tests.test_comparisons import plan_value
from app.tests.test_growth_chain_store import round_input
from app.tests.test_server_api_v1 import immutable
from app.tests.test_validation import (
    GATES,
    LINEAGE,
    candidate_value,
    ledger_with_sealed,
)
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import owner_app

STAMP = "2026-09-23T00:00:00.000000Z"


def seed_candidate(domain, *, status="pass", suffix=0):
    roots = domain.roots()
    marks = {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
             "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}
    plan = freeze_comparison_plan(plan_value())
    plan_ref = persist_comparison_plan(domain, plan, **marks)
    rounds = []
    for index in range(len(GATES)):
        value = round_input(960 + index + suffix * 100)
        persist_comparison_round(domain, plan, value, plan_record_ref=plan_ref, **marks)
        rounds.append(record_comparison_round(plan, value))
    candidate = freeze_candidate(candidate_value(prompts=ref("artifact", 933 + suffix)))
    persist_frozen_candidate(domain, candidate, **marks)
    gates = {name: {"status": status if index == 0 else "pass", "evidence": [rounds[index]],
                    "reasons": ["회귀 발견"] if status != "pass" and index == 0 else []}
             for index, name in enumerate(GATES)}
    report, _ = run_validation(candidate, ledger_with_sealed(f"sealed-{suffix}"), {
        "mode": "sealed_offline", "datasets": [f"sealed-{suffix}"], "approved_scope": None, "gates": gates})
    persist_validation_report(domain, report, lineage_id=LINEAGE, **marks)
    return candidate


def call(subject, name, body):
    return subject.client.post(f"{subject.path.rsplit('/works', 1)[0]}/versions/{name}",
                               json=body, headers=headers(subject.profile, subject.csrf))


def read(subject):
    return subject.client.get(f"{subject.path.rsplit('/works', 1)[0]}/versions", headers=headers(subject.profile))


def test_adopt_approve_apply_and_roll_back(tmp_path):
    with owner_app(tmp_path) as subject:
        domain = subject.domain
        environment = immutable(domain, domain.roots(), "environment").ref
        assert read(subject).json() == {"state": None, "candidates": [], "experiments": []}
        adopted = call(subject, "adopt", {"environment_ref": environment.as_dict()})
        assert adopted.status_code == 200, adopted.text
        assert adopted.json()["state"]["current_environment_ref"] == environment.as_dict()
        assert call(subject, "adopt", {"environment_ref": environment.as_dict()}).status_code == 409
        candidate = seed_candidate(domain)
        listed = read(subject).json()
        [item] = listed["candidates"]
        assert item["approvable"] is True and item["status"] == "passed"
        assert item["candidate_bundle_ref"] == candidate.bundle_ref.as_dict()
        decided = call(subject, "decisions", {"command_id": str(uuid4()), "decision": "approve",
                                              "validation_report_ref": item["validation_report_ref"]})
        assert decided.status_code == 200, decided.text
        approval = decided.json()["approval_ref"]
        stale = call(subject, "activate", {"approval_ref": approval, "expected_revision": 9})
        assert stale.status_code == 409
        applied = call(subject, "activate", {"approval_ref": approval, "expected_revision": 1})
        assert applied.status_code == 200, applied.text
        state = applied.json()["state"]
        assert state["current_environment_ref"] == candidate.bundle_ref.as_dict()
        assert state["history"] == [{"environment_ref": environment.as_dict(), "lifecycle": "retired"}]
        # an approval is applied once; the environment it expected has moved anyway
        assert call(subject, "activate", {"approval_ref": approval, "expected_revision": 2}).status_code == 409
        rolled = call(subject, "rollback", {"reason": "현장 보고서 품질 저하", "expected_revision": 2})
        assert rolled.status_code == 200, rolled.text
        state = rolled.json()["state"]
        assert state["current_environment_ref"] == environment.as_dict()
        assert state["history"][-1] == {"environment_ref": candidate.bundle_ref.as_dict(), "lifecycle": "rolled_back"}
        assert state["external_effects_reverted"] is False
        # the rolled-back bundle does not come back without a fresh approval
        assert call(subject, "activate", {"approval_ref": approval, "expected_revision": 3}).status_code == 409


def test_a_failed_candidate_can_be_rejected_never_approved(tmp_path):
    with owner_app(tmp_path) as subject:
        domain = subject.domain
        environment = immutable(domain, domain.roots(), "environment").ref
        call(subject, "adopt", {"environment_ref": environment.as_dict()})
        seed_candidate(domain, status="fail", suffix=1)
        [item] = read(subject).json()["candidates"]
        assert item["status"] == "failed" and item["approvable"] is False
        assert item["gates"]["reconstruction"]["reasons"] == ["회귀 발견"]
        approved = call(subject, "decisions", {"command_id": str(uuid4()), "decision": "approve",
                                               "validation_report_ref": item["validation_report_ref"]})
        assert approved.status_code == 200  # the decision is recorded as the owner made it…
        applied = call(subject, "activate", {"approval_ref": approved.json()["approval_ref"], "expected_revision": 1})
        assert applied.status_code == 409  # …but a failed report never backs an operational promotion
        rejected = call(subject, "decisions", {"command_id": str(uuid4()), "decision": "reject",
                                               "validation_report_ref": item["validation_report_ref"]})
        assert rejected.status_code == 200 and rejected.json()["decision"] == "reject"


def test_experiments_show_the_stop_reason_the_loop_recorded(tmp_path):
    from app.services.growth import stop_growth_loop
    from app.services.growth_store import persist_loop_state
    from app.tests.test_growth_loop import LINEAGE as LOOP_LINEAGE
    from app.tests.test_growth_loop import profile, valid

    with owner_app(tmp_path) as subject:
        domain = subject.domain
        roots = domain.roots()
        marks = {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
                 "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}
        from app.services.growth import apply_round, start_growth_loop

        state = start_growth_loop(LOOP_LINEAGE, profile())
        first = persist_loop_state(domain, state, parent_ref=None, **marks)
        state = apply_round(state, valid(0, "0.80"))
        second = persist_loop_state(domain, state, parent_ref=first, **marks)
        state = stop_growth_loop(state, "human_stop")
        persist_loop_state(domain, state, parent_ref=second, **marks)
        [experiment] = read(subject).json()["experiments"]
        assert experiment["lineage_id"] == LOOP_LINEAGE and experiment["revision"] == 3
        assert experiment["stop_reason"] == "human_stop"
        assert experiment["best_observed"]["utility"] == "0.80"


def test_the_wire_is_closed(tmp_path):
    with owner_app(tmp_path) as subject:
        for name, body in (("adopt", {}), ("adopt", {"environment_ref": {"kind": "environment"}}),
                           ("decisions", {"command_id": "x", "decision": "approve"}),
                           ("rollback", {"reason": "x", "expected_revision": "1"}),
                           ("unknown", {})):
            assert call(subject, name, body).status_code in {400, 404, 405}, (name, body)
        assert call(subject, "rollback", {"reason": "x", "expected_revision": 1}).status_code == 409
        subject.client.cookies.clear()  # no session: nothing is read
        anonymous = subject.client.get(f"{subject.path.rsplit('/works', 1)[0]}/versions",
                                       headers=headers(subject.profile))
        assert anonymous.status_code == 401
