"""G-14 (growth.md §5, §9; T067, 2026-09-25): a prior-work queue that contains a past
gated external send is re-evaluated in isolation without sending anything again.

The original run is real: the tool-gated graph runs on the real scheduler, the owner
approves the writer's exact attempt, and the real extension attempt transport invokes
the TEST-ACTOR tool `test_actor_notify` (external_irreversible; it performs no effect)
over the in-process extension worker on its real socket. The ledger records that
ToolCall. The queue item then names it by its record digest, and the paired runner
executes baseline and candidate in fresh isolated vaults with only the boundary the
plan's `tool_effect_policy` names, and only once the owner approved exactly that
boundary of exactly that policy through the persistent owner session (an owner
decision, `owner_decisions` kind `tool_effect_boundary`; 2026-09-25):

- replay hands back the recorded result, bound to the ToolCall record digest;
- an isolated sink keeps the would-be send inside the isolated vault;
- a digest mismatch, a missing / rejected / later-rejected approval, an approval of
  the same boundary in another policy, a record in the owner decision shape authored
  by the test actor, changed inputs under replay, no bound policy, or a graph that
  would need the production transport all make the item not comparable with the
  stated reason; a policy that embeds its own approval reference is invalid.

Every case counts, after the original send: the test-actor tool's own invocation
counter, the worker's served exchanges, the production transport factory, the worker
channel lookup, the authenticated worker connection and the attempt dispatcher
factory. They never move. All evidence is synthetic, authored by the test actor.
"""

from contextlib import contextmanager
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.domain.schemas import ImmutableRecord
from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime.ledger import tool_inputs_digest
from app.services.comparisons import freeze_comparison_plan
from app.services.growth_store import (
    persist_comparison_plan,
    persist_comparison_round,
    persist_round_outputs,
    resume_round_item_outcomes,
    resume_round_outputs,
)
from app.services.owner_decisions import (
    PersistentOwnerDecisions,
    decision_identity,
    subject_digest,
)
from app.services.paired_execution import (
    PairedExecutionError,
    PairedSide,
    execute_paired_round,
)
from app.services.tool_effect_isolation import (
    ToolEffectIsolationError,
    ToolEffectSource,
    boundary_decision_command,
    policy_content,
    record_boundary_approval,
    record_tool_effect_policy,
    recorded_effect_bindings,
    tool_call_record_digest,
)
from app.tests.support.tool_gate import TEST_ACTOR_TOOL, compiled_tool_gated
from app.tests.test_alternatives import ref
from app.tests.test_extension_attempt_transport import (  # noqa: F401 - fixture re-exports
    app_subject,
    channel,
    slot,
    staged,
    worker_tree,
)
from app.tests.test_graph_contract import compile_value
from app.tests.test_graph_execution import linear_graph
from app.tests.test_tool_gate_scheduler import (  # noqa: F401 - fixture re-exports
    actor_tool,
    decide,
    gated,
    pending_entry,
    scheduler_of,
    worker,
)
from app.workers import listener

TOOL, VERSION = TEST_ACTOR_TOOL["tool_id"], TEST_ACTOR_TOOL["version"]
EFFECT = "external_irreversible"
PAYLOAD = b"hello"  # the exact input the original run's transport declared (transport_of)
COMPILED = compile_value(linear_graph())  # intake -> writer -> publish
STAMP = "2026-09-25T00:00:00.000000Z"


def marks(domain):
    roots = domain.roots()
    return {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
            "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}


@contextmanager
def original_send(tmp_path, worker):  # noqa: F811 - the imported fixture
    """The real original run: the owner approves the writer's attempt; the tool runs once."""
    with gated(tmp_path) as subject:
        scheduler_of(subject).run()
        decide(subject, pending_entry(subject, 1))
        done = scheduler_of(subject).run()
        assert "publish" in done.completed_node_ids
        assert worker.tool["calls"] == 1 and worker.box.get("served") == 1
        [binding] = recorded_effect_bindings(subject.ledger, subject.run.run_id)
        assert (binding["tool_id"], binding["version"], binding["effect_class"]) == (TOOL, VERSION, EFFECT)
        subject.binding = binding
        yield subject


@pytest.fixture
def guarded(monkeypatch):
    """Counts every way out to the worker after the original send."""
    counts = {"transport_build": 0, "channel": 0, "connect": 0, "dispatcher_build": 0}

    def counting(name, original):
        def wrapper(*args, **kwargs):
            counts[name] += 1
            return original(*args, **kwargs)
        return wrapper

    def install():
        monkeypatch.setattr(xt.ExtensionAttemptTransport, "build",
                            classmethod(counting("transport_build", xt.ExtensionAttemptTransport.build.__func__)))
        monkeypatch.setattr(xt, "extension_channel", counting("channel", xt.extension_channel))
        monkeypatch.setattr(listener, "_connect_extension_authenticated",
                            counting("connect", listener._connect_extension_authenticated))
        monkeypatch.setattr(na.NodeAttemptDispatcher, "build",
                            classmethod(counting("dispatcher_build", na.NodeAttemptDispatcher.build.__func__)))
        return counts

    return install


def boundary(kind="replay", *, tool=TOOL, effect=EFFECT):
    value = {"tool_id": tool, "version": VERSION, "effect_class": effect, "boundary": kind}
    if kind == "isolated_sink":
        value["sink_id"] = "g14-isolated-sink"
    return value


def decisions(subject):
    return PersistentOwnerDecisions(subject.domain, subject.app.state.owner_authority)


def decide_boundary(subject, plan, value, decision="approve"):
    """The owner's decision over one boundary of the plan's policy, through the
    persistent owner session (authenticated, CSRF-verified request)."""
    return record_boundary_approval(decisions(subject), subject.request, plan.tool_effect_policy, value, decision)


def approved_plan(subject, *values):
    plan = plan_with(subject.domain, list(values))
    for value in values:
        decide_boundary(subject, plan, value)
    return plan


def plan_with(domain, boundaries):
    policy = record_tool_effect_policy(domain, boundaries, **marks(domain))
    return freeze_comparison_plan({
        "lineage_id": str(uuid4()), "baseline_environment": ref("environment", 14901),
        "queue": ref("run_manifest", 14905), "quality_profile": ref("evaluation_profile", 14906),
        "evaluator_bundle": ref("rubric", 14907), "reset_manifest": ref("run_manifest", 14908),
        "allowed_changes": ref("decision_record", 14909), "tool_effect_policy": policy.as_dict(),
        "budget": ref("budget_policy", 14911), "mode": "automatic"})


def sides(candidate_payload=PAYLOAD):
    """Code-owned sides over intake -> writer -> publish. The writer of an item that
    names a notice makes the item's tool call through the run's isolated effects."""

    def factory(payload):
        def make(item, domain, effects):
            roots = domain.roots()

            def produce(context, view):
                if context.node_id == "writer" and "notice" in item:
                    return effects.invoke(TOOL, VERSION, (("document_source", "text/plain", payload),))
                record = ImmutableRecord.create(
                    kind="artifact", id=str(uuid4()), version=1, created_at_utc=STAMP,
                    actor_ref=roots.actor, parent_refs=(), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content={"output": f"{context.node_id}:{item['text']}"})
                domain.put(record)
                return record.ref

            return {"core.deterministic": produce, "core.agent": produce}
        return make

    return (PairedSide("baseline", COMPILED, factory(PAYLOAD), uses_tool_effects=True),
            PairedSide("candidate", COMPILED, factory(candidate_payload), uses_tool_effects=True))


def evaluate(item, left, right):
    return {"valid": True, "reasons": [], "metrics": {"utility": "0.9"}}


def run_round(subject, plan, items, reset, *, candidate_payload=PAYLOAD, source=True, compiled=None):
    baseline, candidate = sides(candidate_payload)
    if compiled is not None:
        baseline = PairedSide("baseline", compiled, baseline.handlers, uses_tool_effects=True)
        candidate = PairedSide("candidate", compiled, candidate.handlers, uses_tool_effects=True)
    return execute_paired_round(
        plan, items=items, baseline=baseline, candidate=candidate, evaluator=evaluate,
        reset_root=reset, declared_changes=("writer",),
        round_value={"round_id": f"g14-{uuid4()}", "round_index": 0, "candidate": ref("change_candidate", 14920),
                     "mandatory_checks": ref("validation_report", 14925), "evidence": [],
                     "usage": ref("decision_record", 14927)},
        tool_effects=(ToolEffectSource.build(domain_store=subject.domain, ledger=subject.ledger,
                                             decisions=decisions(subject))
                      if source else None))


def past(subject, binding=None):
    return {"text": "과거 발송이 있는 합성 업무", "notice": True,
            "past_tool_effects": [dict(binding or subject.binding)]}


PLAIN = {"text": "외부 효과가 없는 합성 업무"}


def assert_nothing_sent(worker, counts):  # noqa: F811 - the imported fixture
    assert worker.tool["calls"] == 1 and worker.box.get("served") == 1
    assert counts == {"transport_build": 0, "channel": 0, "connect": 0, "dispatcher_build": 0}


def test_replay_answers_the_past_send_from_its_record_and_sends_nothing(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        plan = approved_plan(subject, boundary("replay"))
        counts = guarded()
        paired = run_round(subject, plan, [PLAIN, past(subject)], tmp_path / "reset")
        assert paired.result.validity == "valid" and len(paired.runs) == 2
        plain, sent = paired.item_outcomes
        assert plain["outcome"] == "compared" and plain["baseline_effects"] == []
        assert sent["outcome"] == "compared" and sent["past_tool_effects"] == [subject.binding]
        [call] = subject.ledger.tool_calls_for_attempt(subject.binding["attempt_id"])
        original = subject.domain.get(EntityRef.from_dict(call["result_ref"])).body["content"]["output"]
        for side, run in (("baseline", paired.runs[1][0]), ("candidate", paired.runs[1][1])):
            [effect] = sent[f"{side}_effects"]
            assert effect["boundary"] == "replay"
            assert effect["tool_call_sha256"] == subject.binding["tool_call_sha256"] == tool_call_record_digest(call)
            writer = dict(run.results)["writer"]
            # the recorded reply, handed back inside the isolated vault, bound to the record
            assert writer["schema_version"] == "tool-effect-replay-v1" and writer["output"] == original
            assert writer["replayed_tool_call_sha256"] == subject.binding["tool_call_sha256"]
        assert_nothing_sent(worker, counts)
        # the original ledger still holds exactly the one call
        assert [item["attempt_id"] for item in recorded_effect_bindings(subject.ledger, subject.run.run_id)] == [
            subject.binding["attempt_id"]]


def test_a_replay_binding_that_does_not_match_the_record_is_not_comparable(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        plan = approved_plan(subject, boundary("replay"))
        counts = guarded()
        forged = {**subject.binding, "tool_call_sha256": "0" * 64}
        paired = run_round(subject, plan, [PLAIN, past(subject, forged)], tmp_path / "reset")
        assert paired.result.validity == "invalid" and len(paired.runs) == 1
        assert paired.result.metric_vector is None and paired.result.utility is None
        [reason] = paired.result.validity_reasons
        assert reason.startswith("item 1: not comparable: replay binding mismatch")
        assert paired.item_outcomes[1]["outcome"] == "not_comparable"
        # a binding naming another call of the ledger is refused too
        missing = {**subject.binding, "tool_call_id": str(uuid4())}
        other = run_round(subject, plan, [PLAIN, past(subject, missing)], tmp_path / "reset-2")
        assert "is not in the original run's ledger" in other.result.validity_reasons[0]
        assert_nothing_sent(worker, counts)


@pytest.mark.parametrize("approval", ["none", "rejected", "later_rejected", "other_boundary",
                                      "other_policy", "test_actor_record"])
def test_an_unapproved_isolation_boundary_makes_the_item_not_comparable(tmp_path, worker, guarded, approval):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        domain = subject.domain
        value = boundary("replay")
        plan = plan_with(domain, [value])
        if approval == "rejected":
            decide_boundary(subject, plan, value, "reject")
        elif approval == "later_rejected":  # the latest owner decision decides
            decide_boundary(subject, plan, value)
            decide_boundary(subject, plan, value, "reject")
        elif approval == "other_boundary":  # the owner approved the sink, not replay
            decide_boundary(subject, plan_with(domain, [boundary("isolated_sink")]), boundary("isolated_sink"))
        elif approval == "other_policy":  # the same boundary, approved in another policy
            decide_boundary(subject, plan_with(domain, [value]), value)
        else:  # the owner-decision record shape, authored by the test actor: not a decision
            command = boundary_decision_command(plan.tool_effect_policy, value, "approve", str(uuid4()))
            forged = {"schema_version": "owner-decision-v1", "subject_kind": "tool_effect_boundary",
                      "subject": command["subject"], "subject_sha256": subject_digest(command["subject"]),
                      "decision": "approve", "command_id": (other := command["command_id"]),
                      "decided_at_utc": STAMP, "event_sequence": 1}
            roots = domain.roots()
            domain.put(ImmutableRecord.create(
                kind="action_approval", id=decision_identity(other), version=1, created_at_utc=STAMP,
                actor_ref=roots.actor, parent_refs=(), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content=forged))
            assert decisions(subject).decisions_over("tool_effect_boundary", command["subject"]) == ()
        counts = guarded()
        paired = run_round(subject, plan, [PLAIN, past(subject)], tmp_path / "reset")
        assert paired.result.validity == "invalid" and len(paired.runs) == 1
        label = "the replay boundary for test_actor_notify 1.0.0"
        expected = f"{label} was rejected by the owner" if "rejected" in approval else f"{label} is not approved"
        assert list(paired.result.validity_reasons) == [f"item 1: not comparable: {expected}"]
        assert paired.item_outcomes[1] == {"item_index": 1, "outcome": "not_comparable",
                                           "reasons": [expected], "past_tool_effects": [],
                                           "baseline_effects": [], "candidate_effects": []}
        assert_nothing_sent(worker, counts)


def test_a_boundary_is_approved_only_through_the_owner_session(tmp_path, worker):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        domain = subject.domain
        # a policy cannot carry its own approval
        with pytest.raises(ToolEffectIsolationError, match="carries no approval"):
            policy_content([{**boundary("replay"), "approval_ref": ref("decision_record", 14930)}])
        plan = plan_with(domain, [boundary("replay")])
        # the helper is the owner path: without the persistent owner service or an
        # authenticated owner request nothing is recorded
        with pytest.raises(ToolEffectIsolationError):
            record_boundary_approval(domain, subject.request, plan.tool_effect_policy, boundary("replay"))
        with pytest.raises(Exception) as refused:
            record_boundary_approval(decisions(subject), object(), plan.tool_effect_policy, boundary("replay"))
        assert type(refused.value).__name__ == "OwnerAuthError"
        # replay-safe by command id; a changed body under the same id conflicts
        command_id = str(uuid4())
        first = record_boundary_approval(decisions(subject), subject.request, plan.tool_effect_policy,
                                         boundary("replay"), command_id=command_id)
        again = record_boundary_approval(decisions(subject), subject.request, plan.tool_effect_policy,
                                         boundary("replay"), command_id=command_id)
        assert again.approval_ref == first.approval_ref and first.subject_kind == "tool_effect_boundary"
        assert first.subject["boundary"] == boundary("replay")
        assert first.subject["policy_record"]["sha256"] == plan.tool_effect_policy.sha256
        for changed in ({"decision": "reject"}, {"value": boundary("isolated_sink")}):
            with pytest.raises(Exception, match="conflict"):
                record_boundary_approval(decisions(subject), subject.request, plan.tool_effect_policy,
                                         changed.get("value", boundary("replay")),
                                         changed.get("decision", "approve"), command_id=command_id)
        # the paired runner needs the owner-decision reader bound to the same store
        with pytest.raises(ToolEffectIsolationError, match="owner-decision reader"):
            ToolEffectSource.build(domain_store=domain, ledger=subject.ledger, decisions=None)


def test_an_approved_isolated_sink_keeps_a_changed_send_inside_the_isolated_vault(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        plan = approved_plan(subject, boundary("isolated_sink"))
        counts = guarded()
        changed = b"hello, with the candidate's source line"
        paired = run_round(subject, plan, [past(subject)], tmp_path / "reset", candidate_payload=changed)
        assert paired.result.validity == "valid"
        [outcome] = paired.item_outcomes
        [left], [right] = outcome["baseline_effects"], outcome["candidate_effects"]
        assert left["boundary"] == right["boundary"] == "isolated_sink"
        assert left["sink_id"] == "g14-isolated-sink"
        # the baseline would have sent the recorded inputs again; the candidate a changed one
        [call] = subject.ledger.tool_calls_for_attempt(subject.binding["attempt_id"])
        assert left["inputs_digest"] == tool_inputs_digest(call["artifact_inputs"])
        assert left["inputs_digest"] != right["inputs_digest"]
        writer = dict(paired.runs[0][1].results)["writer"]
        assert writer["delivered"] == "isolated_sink_only" and writer["inputs"][0]["declared_size"] == len(changed)
        assert "writer" in paired.changed_nodes[0]
        assert_nothing_sent(worker, counts)


def test_replay_refuses_an_isolated_call_whose_inputs_differ_from_the_record(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        plan = approved_plan(subject, boundary("replay"))
        counts = guarded()
        paired = run_round(subject, plan, [PLAIN, past(subject)], tmp_path / "reset", candidate_payload=b"changed")
        assert paired.result.validity == "invalid" and len(paired.runs) == 1
        [reason] = paired.result.validity_reasons
        assert reason == ("item 1: not comparable: the isolated test_actor_notify 1.0.0 call's inputs differ "
                          "from the recorded call; replaying its result would misstate the effect")
        assert_nothing_sent(worker, counts)


def test_without_a_bound_isolation_source_a_past_send_is_never_re_run(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        plan = approved_plan(subject, boundary("replay"))
        counts = guarded()
        paired = run_round(subject, plan, [PLAIN, past(subject)], tmp_path / "reset", source=False)
        assert list(paired.result.validity_reasons) == [
            "item 1: not comparable: the item has past external effects and no isolation boundary is bound"]
        # a queue whose every item is not comparable records no round at all
        with pytest.raises(PairedExecutionError, match="no item ran on both sides: item 0: not comparable"):
            run_round(subject, plan, [past(subject)], tmp_path / "reset-2", source=False)
        assert_nothing_sent(worker, counts)


def test_an_unreadable_policy_is_not_a_boundary(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        plan = freeze_comparison_plan({**{key.removesuffix("_ref"): value for key, value in
                                          plan_with(subject.domain, []).as_dict().items()
                                          if key != "schema_version"},
                                       "tool_effect_policy": ref("observation_contract", 14910)})
        counts = guarded()
        paired = run_round(subject, plan, [PLAIN, past(subject)], tmp_path / "reset")
        assert list(paired.result.validity_reasons) == [
            "item 1: not comparable: the plan's tool effect policy could not be read"]
        assert_nothing_sent(worker, counts)


def test_the_isolated_runner_cannot_schedule_the_gated_production_graph(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        plan = approved_plan(subject, boundary("replay"))
        counts = guarded()
        # the original environment's own graph binds the tool behind its gate: without a
        # per-attempt approval transport and approval service the scheduler refuses it
        with pytest.raises(PairedExecutionError, match=r"item 0: run failed \(SchedulerError\)"):
            run_round(subject, plan, [past(subject)], tmp_path / "reset", compiled=compiled_tool_gated())
        assert_nothing_sent(worker, counts)


def test_the_round_keeps_each_item_outcome_and_the_boundary_used(tmp_path, worker, guarded):  # noqa: F811
    with original_send(tmp_path, worker) as subject:
        domain = subject.domain
        plan = approved_plan(subject, boundary("replay"))
        counts = guarded()
        paired = run_round(subject, plan, [PLAIN, past(subject)], tmp_path / "reset")
        value = paired.result.as_dict()
        stored_plan = persist_comparison_plan(domain, plan, **marks(domain))
        record = persist_comparison_round(domain, plan, {
            "round_id": value["round_id"], "round_index": value["round_index"], "candidate": value["candidate_ref"],
            "baseline_runs": value["baseline_run_refs"], "candidate_runs": value["candidate_run_refs"],
            "validity": value["validity"], "validity_reasons": value["validity_reasons"],
            "mandatory_checks": value["mandatory_checks_ref"], "metric_vector": value["metric_vector"],
            "utility": value["utility"], "evidence": value["evidence_refs"], "usage": value["usage_ref"]},
            plan_record_ref=stored_plan, **marks(domain))
        persist_round_outputs(domain, record, paired, **marks(domain))
        outcomes = resume_round_item_outcomes(domain, record)
        assert [item["outcome"] for item in outcomes] == ["compared", "compared"]
        assert outcomes[1]["baseline_effects"][0]["tool_call_sha256"] == subject.binding["tool_call_sha256"]
        assert [item["item_index"] for item in resume_round_outputs(domain, record)] == [0, 1]
        assert_nothing_sent(worker, counts)


def test_the_counters_do_observe_a_real_send(tmp_path, worker, guarded):  # noqa: F811
    """The guard is not vacuous: installed before the original send, it sees every step."""
    counts = guarded()
    with gated(tmp_path) as subject:
        scheduler_of(subject).run()
        decide(subject, pending_entry(subject, 1))
        scheduler_of(subject).run()
        assert worker.tool["calls"] == 1 and worker.box.get("served") == 1
        assert all(counts[name] >= 1 for name in counts), counts
