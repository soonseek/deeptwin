"""G-14 boundary approvals as the owner's authenticated act (T067, 2026-09-25).

A persisted comparison plan's `tool_effect_policy` names one isolation boundary per
tool and version. The owner lists them with their standing decision and records
approve / reject through `versions-v1`'s CSRF-verified routes; each decision is an
owner decision (`owner_decisions`, kind `tool_effect_boundary`) over the exact subject
(policy record identity, tool, version, boundary kind and sink, boundary digest),
replay-safe by command id, a conflict on changed content or a digest the stored
boundary does not have — and it is what the paired runner's `ToolEffectSource` reads.
Synthetic test-actor values only.
"""

from uuid import uuid4

from app.runtime.ledger import RuntimeLedger
from app.services.comparisons import freeze_comparison_plan
from app.services.growth_store import persist_comparison_plan
from app.services.owner_decisions import PersistentOwnerDecisions
from app.services.tool_effect_isolation import (
    ToolEffectSource,
    boundary_digest,
    boundary_subject,
    record_tool_effect_policy,
)
from app.tests.test_comparisons import plan_value
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import owner_app

STAMP = "2026-09-25T00:00:00.000000Z"
REPLAY = {"tool_id": "test_actor_notify", "version": "1.0.0", "effect_class": "external_irreversible",
          "boundary": "replay"}
SINK = {"tool_id": "test_actor_publish", "version": "2.0.0", "effect_class": "external_irreversible",
        "boundary": "isolated_sink", "sink_id": "g14-isolated-sink"}


def marks(domain):
    roots = domain.roots()
    return {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
            "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}


def seed_plan(domain, boundaries=(REPLAY, SINK)):
    policy = record_tool_effect_policy(domain, list(boundaries), **marks(domain))
    plan = freeze_comparison_plan(plan_value(tool_effect_policy=policy.as_dict(), lineage_id=str(uuid4())))
    return plan, persist_comparison_plan(domain, plan, **marks(domain))


def base(subject):
    return subject.path.rsplit("/works", 1)[0] + "/versions/tool-effect-boundaries"


def listed(subject):
    return subject.client.get(base(subject), headers=headers(subject.profile))


def decide(subject, plan_record, boundary, decision="approve", *, command_id=None, digest=None, csrf=True):
    body = {"command_id": command_id or str(uuid4()), "plan_record_ref": plan_record.as_dict(),
            "tool_id": boundary["tool_id"], "version": boundary["version"],
            "boundary_sha256": digest or boundary_digest(boundary), "decision": decision}
    return subject.client.post(base(subject) + "/decisions", json=body,
                               headers=headers(subject.profile, subject.csrf if csrf else None))


def entry(subject, plan_record):
    [found] = [item for item in listed(subject).json()["plans"] if item["plan_record"] == plan_record.as_dict()]
    return found


def test_the_owner_lists_and_decides_each_boundary_a_plan_needs(tmp_path):
    with owner_app(tmp_path) as subject:
        domain = subject.domain
        assert listed(subject).json() == {"plans": []}
        plan, record = seed_plan(domain)
        view = entry(subject, record)
        assert view["readable"] is True and view["lineage_id"] == plan.lineage_id
        assert view["tool_effect_policy_ref"] == plan.tool_effect_policy.as_dict()
        assert [(item["tool_id"], item["boundary"], item["sink_id"], item["state"]) for item in view["boundaries"]] == [
            ("test_actor_notify", "replay", None, "pending"), ("test_actor_publish", "isolated_sink",
                                                                "g14-isolated-sink", "pending")]
        assert view["boundaries"][0]["boundary_sha256"] == boundary_digest(REPLAY)

        command_id = str(uuid4())
        approved = decide(subject, record, REPLAY, command_id=command_id)
        assert approved.status_code == 200, approved.text
        body = approved.json()
        assert body["decision"] == "approve" and body["boundary"]["state"] == "approved"
        assert body["approval_ref"]["kind"] == "action_approval"
        # the record is the owner's decision over exactly this subject
        decisions = PersistentOwnerDecisions(domain, subject.app.state.owner_authority)
        [issued] = decisions.decisions_over("tool_effect_boundary", boundary_subject(plan.tool_effect_policy, REPLAY))
        assert issued.approval_ref.as_dict() == body["approval_ref"]
        assert issued.actor_ref != domain.roots().actor  # the owner's human actor, not the test actor
        # exact replay returns the same decision; a changed body under the same id conflicts
        again = decide(subject, record, REPLAY, command_id=command_id)
        assert again.status_code == 200 and again.json()["approval_ref"] == body["approval_ref"]
        assert decide(subject, record, REPLAY, "reject", command_id=command_id).status_code == 409
        assert decide(subject, record, SINK, command_id=command_id).status_code == 409
        # a digest that is not the stored boundary's is a conflict, never a decision
        assert decide(subject, record, REPLAY, digest="0" * 64).status_code == 409
        # a tool the policy does not name, or a plan that is not stored, is not found
        assert decide(subject, record, {**REPLAY, "tool_id": "absent_tool"}).status_code == 404
        other_plan, other_record = seed_plan(domain)
        missing = other_record.__class__(other_record.kind, str(uuid4()), 1, other_record.sha256)
        assert decide(subject, missing, REPLAY).status_code == 404
        # without CSRF nothing is recorded
        assert decide(subject, record, SINK, csrf=False).status_code in {401, 403}
        assert decide(subject, record, SINK, "reject").status_code == 200
        view = entry(subject, record)
        assert [(item["state"], item["decisions"]) for item in view["boundaries"]] == [("approved", 1), ("rejected", 1)]
        # a later decision replaces the standing one; the other plan's same boundary is untouched
        assert decide(subject, record, REPLAY, "reject").status_code == 200
        assert entry(subject, record)["boundaries"][0]["state"] == "rejected"
        assert entry(subject, other_record)["boundaries"][0]["state"] == "pending"

        # the paired runner's source reads exactly these owner decisions
        source = ToolEffectSource.build(domain_store=domain, ledger=RuntimeLedger(domain), decisions=decisions)
        assert source.approved(plan.tool_effect_policy, REPLAY) == (
            "the replay boundary for test_actor_notify 1.0.0 was rejected by the owner")
        assert decide(subject, record, REPLAY).status_code == 200
        assert source.approved(plan.tool_effect_policy, REPLAY) is None
        assert source.approved(other_plan.tool_effect_policy, REPLAY) == (
            "the replay boundary for test_actor_notify 1.0.0 is not approved")


def test_a_plan_whose_policy_cannot_be_read_is_listed_with_its_reason(tmp_path):
    with owner_app(tmp_path) as subject:
        plan = freeze_comparison_plan(plan_value(lineage_id=str(uuid4())))  # its policy is not a stored record
        record = persist_comparison_plan(subject.domain, plan, **marks(subject.domain))
        view = entry(subject, record)
        assert view["readable"] is False and view["boundaries"] == []
        assert view["reason"] == "the plan's tool effect policy could not be read"
        assert decide(subject, record, REPLAY).status_code == 409


def test_the_boundary_routes_admit_only_their_exact_shapes(tmp_path):
    with owner_app(tmp_path) as subject:
        _plan, record = seed_plan(subject.domain)
        url = base(subject) + "/decisions"
        good = {"command_id": str(uuid4()), "plan_record_ref": record.as_dict(), "tool_id": REPLAY["tool_id"],
                "version": REPLAY["version"], "boundary_sha256": boundary_digest(REPLAY), "decision": "approve"}
        for bad in ({**good, "decision": "defer"}, {**good, "extra": 1}, {**good, "command_id": "x"},
                    {key: value for key, value in good.items() if key != "boundary_sha256"},
                    {**good, "plan_record_ref": {"kind": "decision_record"}}):
            response = subject.client.post(url, json=bad, headers=headers(subject.profile, subject.csrf))
            assert response.status_code == 400, (bad, response.text)
        assert subject.client.get(base(subject) + "?plan=x", headers=headers(subject.profile)).status_code == 400
        assert subject.client.post(base(subject), json={}, headers=headers(subject.profile, subject.csrf)).status_code in {
            400, 405}
        assert entry(subject, record)["boundaries"][0]["state"] == "pending"
