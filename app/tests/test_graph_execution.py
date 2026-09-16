"""US3 scheduling patterns: sequential, parallel, router, join, loop,
retry, restart (T039; R02, with R07/R08's crash/cancel substrate already
covered by test_runtime_ledger).

These patterns compose the sealed-activation/join/visit primitives the way
a driver would: a successor runs only after its producer is terminal; a
router's unsealed branch can never report; a bounded loop makes NEW visits
(never retries); a retry stays inside one visit; and a restart that
replays the recorded evidence reconstructs the identical join decision —
late duplicates stay refused after the replay too.
"""

import pytest

from app.runtime.scheduling_state import (
    SchedulingError,
    apply_branch_result,
    apply_simultaneous_results,
    blocked_dependants,
    next_attempt,
    open_join,
    seal_activation,
    visit_identity,
)

RUN_ID = "00000000-0000-4000-8000-00000000d101"


def sealed(branches, *, mode="all_selected", min_success=None, loop_index=0):
    activation = seal_activation(
        run_id=RUN_ID,
        router_node_id="router-main",
        visit=visit_identity("router-main", loop_index=loop_index),
        branch_ids=list(branches),
    )
    return activation, open_join(
        activation, mode=mode, min_success=min_success,
    )


def result(branch, status, index, artifact=None):
    return {
        "branch_id": branch,
        "status": status,
        "observation_index": index,
        "artifact_ref": artifact,
    }


def test_sequential_chain_gates_each_successor_on_terminal_producers():
    # a sequential chain is a chain of single-branch all_selected joins:
    # the next stage's activation is sealed only after the previous stage
    # completed
    stages = ["research", "write", "review"]
    completed = []
    for stage in stages:
        _activation, join = sealed([f"{stage}-branch"])
        assert join.completed is False  # nothing runs ahead of its producer
        join = apply_branch_result(
            join, result(f"{stage}-branch", "succeeded", 1),
        )
        assert join.completed is True and join.satisfied is True
        completed.append(stage)
    assert completed == stages


def test_parallel_branches_progress_independently_within_the_seal():
    _activation, join = sealed(["b1", "b2", "b3"])
    join = apply_branch_result(join, result("b2", "succeeded", 1))
    assert join.completed is False  # others still in flight, none blocked
    join = apply_branch_result(join, result("b3", "failed", 2))
    join = apply_branch_result(join, result("b1", "succeeded", 3))
    assert join.completed is True
    assert join.satisfied is False  # a required failure is never hidden
    assert join.inputs == ("b1", "b2")


def test_a_router_activates_a_subset_and_outsiders_never_report():
    # the router chose 2 of 4 statically-possible branches; the sealed set
    # IS the decision
    activation, join = sealed(["path-a", "path-c"], mode="any_success")
    assert activation.branch_ids == ("path-a", "path-c")
    with pytest.raises(SchedulingError):
        apply_branch_result(join, result("path-b", "succeeded", 1))
    join = apply_branch_result(join, result("path-c", "succeeded", 1))
    assert join.winner == "path-c"
    blocked = blocked_dependants(
        activation, "path-a", {"path-a": ["delivery"], "path-c": []},
    )
    assert blocked == ("delivery",)


def test_a_bounded_loop_makes_new_visits_never_retries():
    seen_activations = set()
    for iteration in range(3):
        activation, join = sealed(
            ["loop-body"], loop_index=iteration,
        )
        assert activation.activation_id not in seen_activations
        seen_activations.add(activation.activation_id)
        join = apply_branch_result(join, result("loop-body", "succeeded", 1))
        assert join.completed is True
    # the loop's visits are three DIFFERENT identities
    visits = {
        visit_identity("loop-body", loop_index=i) for i in range(3)
    }
    assert len(visits) == 3
    with pytest.raises(SchedulingError):
        visit_identity("loop-body", loop_index=1_000_001)  # hard cap


def test_a_retry_stays_inside_one_visit():
    visit = visit_identity("write", loop_index=0)
    first = next_attempt(visit, previous_index=None)
    second = next_attempt(visit, previous_index=first.attempt_index)
    third = next_attempt(visit, previous_index=second.attempt_index)
    assert first.visit == second.visit == third.visit == visit
    assert (first.attempt_index, second.attempt_index,
            third.attempt_index) == (0, 1, 2)
    repeat_visit = visit_identity("write", loop_index=1)
    assert repeat_visit != visit  # a repeat visit is NOT attempt 3
    with pytest.raises(SchedulingError):
        next_attempt(visit, previous_index=1_001)  # retry budget cap


def test_a_restart_replays_evidence_to_the_identical_decision():
    _activation, join = sealed(
        ["b1", "b2", "b3"], mode="any_success",
    )
    join = apply_simultaneous_results(join, [
        result("b2", "succeeded", 4),
        result("b3", "succeeded", 4),
    ])
    join = apply_branch_result(join, result("b1", "failed", 5))
    # crash: rebuild from the recorded evidence in recorded order
    _activation2, rebuilt = sealed(
        ["b1", "b2", "b3"], mode="any_success",
    )
    for item in join.evidence:
        rebuilt = apply_branch_result(rebuilt, dict(item))
    assert rebuilt.winner == join.winner == "b2"  # frozen-order tie held
    assert rebuilt.inputs == join.inputs
    assert rebuilt.completed is True
    with pytest.raises(SchedulingError):
        # a late duplicate stays refused after the replay too
        apply_branch_result(rebuilt, result("b1", "succeeded", 9))


def test_collect_pattern_gathers_the_minimum_across_parallel_workers():
    _activation, join = sealed(
        ["w1", "w2", "w3", "w4"], mode="collect", min_success=2,
    )
    join = apply_branch_result(join, result("w4", "succeeded", 1))
    join = apply_branch_result(join, result("w2", "failed", 2))
    assert join.completed is False
    join = apply_branch_result(join, result("w1", "succeeded", 3))
    assert join.completed is True and join.satisfied is True
    assert join.inputs == ("w1", "w4")  # frozen order, not arrival order
    late = apply_branch_result(join, result("w3", "succeeded", 4))
    assert late.inputs == ("w1", "w4")  # sealed decision, evidence only


# ---------------------------------------------------------------------------
# T040 (first slice) / T039: the actual LangGraph scheduling adapter over a
# CompiledGraph with ledger-reconciled idempotent node visits and opaque
# checkpoint cursors. Handlers are code-owned registry entries keyed by the
# compiled handler keys; model output can never add one. Real StateGraph,
# real SQLite ledger and checkpoint journal; no live provider.
# ---------------------------------------------------------------------------

import uuid as _uuid

from app.runtime import scheduler as sch
from app.tests.test_graph_contract import (
    artifact_edge,
    compile_value,
    control_edge,
    graph_value,
    input_slot,
    node,
    output_slot,
    router_graph,
)
from app.tests.test_langgraph_checkpoints import reopen
from app.tests.test_runtime_ledger import identifier, opened, run_spec


def linear_graph():
    raw = graph_value()
    raw["nodes"] = [
        node("intake", "deterministic", "원자료를 정규화한다",
             outputs=[output_slot("draft", "text-document")]),
        node("writer", "agent", "전체 초안을 만든다",
             inputs=[input_slot("source", "text-document")],
             outputs=[output_slot("draft", "text-document")]),
        node("publish", "deterministic", "산출물을 고정한다",
             inputs=[input_slot("approved", "text-document")],
             outputs=[output_slot("result", "text-document")]),
    ]
    raw["edges"] = [
        artifact_edge("e1", "intake", "draft", "writer", "source", "text-document"),
        artifact_edge("e2", "writer", "draft", "publish", "approved", "text-document"),
    ]
    return raw


def parallel_graph():
    raw = router_graph()
    raw["nodes"] = [
        node("left", "deterministic", "왼쪽 경로", outputs=[output_slot("out", "text-document")]),
        node("right", "deterministic", "오른쪽 경로", outputs=[output_slot("out", "text-document")]),
        node("join", "join", "두 경로를 합류한다",
             inputs=[input_slot("items", "text-document", multiplicity="many")],
             outputs=[output_slot("result", "text-document")]),
    ]
    raw["entry_node_ids"] = ["left", "right"]
    raw["edges"] = [
        artifact_edge("p1", "left", "out", "join", "items", "text-document", multiplicity="many"),
        artifact_edge("p2", "right", "out", "join", "items", "text-document", multiplicity="many"),
    ]
    return raw


def ledger_run(tmp_path):
    subject = opened(tmp_path)
    run = run_spec(subject)
    subject.ledger.create_run(identifier(), run)
    return subject, run


def registry(subject, calls, *, decision="accept", failing=None):
    def produce(context, view):
        calls.append(context.node_id)
        if context.node_id == failing:
            raise RuntimeError("PRIVATE_HANDLER_CANARY")
        return subject.refs.result

    def route(context, view):
        calls.append(context.node_id)
        return decision

    return {"core.deterministic": produce, "core.agent": produce,
            "core.join": produce, "core.router": route}


def build(subject, run, raw, handlers):
    return sch.build_scheduler(compile_value(raw), ledger=subject.ledger,
                               run_id=run.run_id, handlers=handlers)


def test_scheduler_runs_a_sequential_chain_with_ledger_reconciled_executions(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    outcome = build(subject, run, linear_graph(), registry(subject, calls)).run()
    assert calls == ["intake", "writer", "publish"]
    assert outcome.completed_node_ids == ("intake", "publish", "writer")
    assert outcome.run_id == run.run_id
    executions = dict(outcome.execution_ids)
    for node_id, execution_id in executions.items():
        recorded = subject.ledger.get_execution(execution_id)
        assert recorded["spec"]["node_id"] == node_id
        assert execution_id == sch.execution_identity(run.run_id, node_id, 0)
    assert set(dict(outcome.result_refs)) == set(executions.values())
    # the outcome is a bounded projection, never the raw channel state
    assert set(outcome.__dataclass_fields__) == {
        "run_id", "graph_digest", "completed_node_ids", "execution_ids",
        "result_refs", "counters", "activations", "awaiting_human", "approvals",
    }
    assert outcome.counters == {"intake": 1, "writer": 1, "publish": 1}


def test_parallel_entries_fan_in_to_one_join_visit(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    outcome = build(subject, run, parallel_graph(), registry(subject, calls)).run()
    assert sorted(calls[:2]) == ["left", "right"]
    assert calls[2:] == ["join"]
    assert outcome.counters == {"left": 1, "right": 1, "join": 1}


def test_router_seals_exactly_the_decided_branch(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    outcome = build(subject, run, router_graph(), registry(subject, calls)).run()
    assert calls == ["choose", "accept", "join"]  # revise was never activated
    assert len(outcome.activations) == 1
    router, activation_id, branches = outcome.activations[0]
    assert router == "choose" and branches == ("accept",)
    _uuid.UUID(activation_id)
    subject2, run2 = ledger_run(tmp_path / "other")
    calls2 = []
    with pytest.raises(sch.SchedulerError):
        build(subject2, run2, router_graph(), registry(subject2, calls2, decision="other")).run()
    assert calls2 == ["choose"]  # an undeclared decision activates nothing


def test_restart_after_a_failure_never_reruns_completed_visits(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    scheduler = build(subject, run, linear_graph(), registry(subject, calls, failing="writer"))
    with pytest.raises(sch.SchedulerError) as caught:
        scheduler.run()
    assert "PRIVATE_HANDLER_CANARY" not in str(caught.value)
    assert "writer" in str(caught.value)
    assert calls == ["intake", "writer"]
    intake_execution = sch.execution_identity(run.run_id, "intake", 0)
    assert subject.ledger.get_execution(intake_execution)["spec"]["node_id"] == "intake"
    reopen(subject, tmp_path)
    resumed_calls = []
    outcome = build(subject, run, linear_graph(), registry(subject, resumed_calls)).run()
    assert resumed_calls == ["writer", "publish"]  # intake's visit was durable
    assert outcome.completed_node_ids == ("intake", "publish", "writer")
    assert dict(outcome.execution_ids)["intake"] == intake_execution
    # the journal never carried the private error text
    head = subject.ledger.checkpoint_for_replay(run.run_id, sch.NAMESPACE)
    for revision in range(1, head["revision"] + 1):
        row = subject.ledger.checkpoint_for_replay(run.run_id, sch.NAMESPACE, revision=revision)
        assert b"PRIVATE_HANDLER_CANARY" not in row["cursor"]


def test_a_completed_run_is_idempotent(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    first = build(subject, run, linear_graph(), registry(subject, calls)).run()
    again = build(subject, run, linear_graph(), registry(subject, calls)).run()
    assert calls == ["intake", "writer", "publish"]  # nothing re-ran
    assert again == first


def test_the_handler_registry_is_closed_and_kinds_are_explicit(tmp_path):
    subject, run = ledger_run(tmp_path)
    good = registry(subject, [])
    missing = dict(good)
    del missing["core.agent"]
    extra = dict(good, **{"core.shell": good["core.agent"]})
    not_callable = dict(good, **{"core.agent": "os.system"})
    for handlers in (missing, extra, not_callable):
        with pytest.raises(sch.SchedulerError):
            build(subject, run, linear_graph(), handlers)
    with pytest.raises(sch.SchedulerError):
        sch.build_scheduler({"graph_digest": "x"}, ledger=subject.ledger,
                            run_id=run.run_id, handlers=good)
    with pytest.raises(sch.SchedulerError, match="human_gate"):
        build(subject, run, graph_value(), good)  # unsupported kinds refuse loudly


def test_handler_results_must_be_exact_refs_and_nothing_streams(tmp_path):
    subject, run = ledger_run(tmp_path)

    def bad(context, view):
        return {"text": "not a ref"}

    handlers = dict(registry(subject, []), **{"core.deterministic": bad})
    scheduler = build(subject, run, linear_graph(), handlers)
    assert not hasattr(scheduler, "stream")
    with pytest.raises(sch.SchedulerError) as caught:
        scheduler.run()
    assert "not a ref" not in str(caught.value)


def test_handlers_receive_identity_only_and_a_detached_view(tmp_path):
    subject, run = ledger_run(tmp_path)
    seen = {}

    def produce(context, view):
        seen[context.node_id] = (context, dict(view))
        view["results"]["forged"] = "x"  # a mutated view must not leak into state
        return subject.refs.result

    handlers = {"core.deterministic": produce, "core.agent": produce,
                "core.join": produce, "core.router": produce}
    outcome = build(subject, run, linear_graph(), handlers).run()
    context, view = seen["writer"]
    assert context.run_id == run.run_id and context.loop_index == 0
    assert set(view) == {"results", "counters"}
    assert "forged" not in dict(outcome.result_refs)
    assert type(context).__dataclass_params__.frozen


# ---------------------------------------------------------------------------
# T040 slice 2: bounded loops. The loop controller's handler returns validated
# facts; the compiled termination expression decides exit versus another
# iteration; every iteration is a NEW visit with its own execution identity;
# the hard iteration cap is a product limit that fails the run loudly.
# ---------------------------------------------------------------------------

from app.tests.test_graph_contract import loop_graph


def loop_registry(subject, calls, *, done_after, facts_for_loop=None):
    def produce(context, view):
        calls.append((context.node_id, context.loop_index))
        return subject.refs.result

    def control(context, view):
        calls.append((context.node_id, context.loop_index))
        if facts_for_loop is not None:
            return None if facts_for_loop == "RETURN_NONE" else facts_for_loop
        return {"loop_done": context.loop_index >= done_after}

    return {"core.deterministic": produce, "core.agent": produce,
            "core.bounded_loop": control}


def test_bounded_loop_iterates_as_new_visits_until_termination(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    outcome = build(subject, run, loop_graph(), loop_registry(subject, calls, done_after=2)).run()
    assert calls == [
        ("seed", 0), ("loop", 0), ("revise", 0), ("loop", 1), ("revise", 1),
        ("loop", 2), ("done", 0),
    ]
    assert outcome.counters == {"seed": 1, "loop": 3, "revise": 2, "done": 1}
    revise_ids = [eid for node, eid in outcome.execution_ids if node == "revise"]
    assert revise_ids == [sch.execution_identity(run.run_id, "revise", 0),
                          sch.execution_identity(run.run_id, "revise", 1)]
    for execution_id in revise_ids:
        assert subject.ledger.get_execution(execution_id)["spec"]["node_id"] == "revise"


def test_the_hard_iteration_cap_fails_the_run_loudly(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    scheduler = build(subject, run, loop_graph(), loop_registry(subject, calls, done_after=99))
    with pytest.raises(sch.SchedulerError, match="loop_cap:revision-loop"):
        scheduler.run()
    loop_visits = [index for node, index in calls if node == "loop"]
    assert loop_visits == [0, 1, 2, 3, 4]  # the compiled cap is 5 controller visits
    assert ("done", 0) not in calls


def test_restart_inside_a_loop_never_reruns_completed_iterations(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    state = {"fail_once": True}

    def produce(context, view):
        calls.append((context.node_id, context.loop_index))
        if context.node_id == "revise" and context.loop_index == 1 and state["fail_once"]:
            state["fail_once"] = False
            raise RuntimeError("PRIVATE_LOOP_CANARY")
        return subject.refs.result

    def control(context, view):
        calls.append((context.node_id, context.loop_index))
        return {"loop_done": context.loop_index >= 2}

    handlers = {"core.deterministic": produce, "core.agent": produce, "core.bounded_loop": control}
    with pytest.raises(sch.SchedulerError, match="node_failed:revise"):
        build(subject, run, loop_graph(), handlers).run()
    assert calls[-1] == ("revise", 1)
    reopen(subject, tmp_path)
    before = list(calls)
    outcome = build(subject, run, loop_graph(), handlers).run()
    resumed = calls[len(before):]
    assert resumed == [("revise", 1), ("loop", 2), ("done", 0)]
    assert outcome.counters == {"seed": 1, "loop": 3, "revise": 2, "done": 1}


@pytest.mark.parametrize(
    "facts", ["done", {"ambient": True}, {"loop_done": "yes"}, "RETURN_NONE"]
)
def test_loop_facts_are_validated_against_the_graph(tmp_path, facts):
    subject, run = ledger_run(tmp_path)
    calls = []
    scheduler = build(subject, run, loop_graph(),
                      loop_registry(subject, calls, done_after=0, facts_for_loop=facts))
    with pytest.raises(sch.SchedulerError, match="node_failed:loop"):
        scheduler.run()
    assert ("revise", 0) not in calls and ("done", 0) not in calls


# ---------------------------------------------------------------------------
# T040 slice 3: human gates. A `human_gate` node runs only when an actual
# owner-recorded approval exists for every declared scope; without one the
# run stops honestly in `awaiting_human`, and a recorded rejection fails the
# gate. No handler return value can substitute for the record.
# ---------------------------------------------------------------------------

from types import SimpleNamespace as _NS

from app.services.run_approvals import PersistentRunApprovals
from app.tests.test_extension_candidates_persistent import owner as _owner
from app.tests.test_runtime_ledger import immutable


def gated_app(tmp_path):
    """A real owner-bootstrapped app whose ledger/store host the gated run."""
    context = _owner(tmp_path)
    app, _client, request, _profile, _arguments = context.__enter__()
    from app.runtime import ledger as ledger_module

    domain = app.state.domain_store
    roots = domain.roots()
    refs = _NS(
        work=immutable(domain, roots, "work_revision"),
        environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"),
        budget=immutable(domain, roots, "budget_policy"),
        manifest=immutable(domain, roots, "run_manifest"),
        result=immutable(domain, roots, "run_manifest", content={"fixture": "terminal"}),
    )
    # the supported server reconciles its ledger at startup only when worker
    # dispatch is configured; this fixture performs that same startup step
    app.state.runtime_ledger.reconcile_startup(identifier(), observed_owners={})
    subject = _NS(module=ledger_module, refs=refs, ledger=app.state.runtime_ledger,
                  domain=domain, app=app, request=request, context=context)
    run = run_spec(subject)
    subject.ledger.create_run(identifier(), run)
    approvals = PersistentRunApprovals(domain, app.state.owner_authority)
    return subject, run, approvals


def gate_registry(subject, calls):
    def produce(context, view):
        calls.append(context.node_id)
        return subject.refs.result

    return {"core.deterministic": produce, "core.agent": produce,
            "core.human_gate": produce}


def approval_command(run, decision="approved", scope="release-output", node="owner-gate"):
    return {"schema_version": "run-approval-command-v1", "command_id": str(_uuid.uuid4()),
            "run_id": run.run_id, "node_id": node, "approval_scope": scope,
            "decision": decision}


def test_a_gate_waits_for_the_owner_and_runs_after_a_recorded_approval(tmp_path):
    subject, run, approvals = gated_app(tmp_path)
    try:
        calls = []
        scheduler = sch.build_scheduler(compile_value(graph_value()), ledger=subject.ledger,
                                        run_id=run.run_id, handlers=gate_registry(subject, calls),
                                        approvals=approvals)
        waiting = scheduler.run()
        assert calls == ["intake", "writer"]
        assert waiting.awaiting_human == (("owner-gate", "release-output"),)
        assert "publish" not in waiting.completed_node_ids
        assert scheduler.run().awaiting_human == waiting.awaiting_human  # still waiting
        assert calls == ["intake", "writer"]
        approvals.record(subject.request, approval_command(run))
        outcome = scheduler.run()
        assert calls == ["intake", "writer", "owner-gate", "publish"]
        assert outcome.awaiting_human == ()
        assert outcome.completed_node_ids == ("intake", "owner-gate", "publish", "writer")
        assert dict(outcome.approvals)["owner-gate"] == (
            approvals.lookup(run.run_id, "owner-gate", "release-output").approval_ref,
        )
    finally:
        subject.context.__exit__(None, None, None)


def test_a_recorded_rejection_fails_the_gate_and_never_runs_it(tmp_path):
    subject, run, approvals = gated_app(tmp_path)
    try:
        calls = []
        scheduler = sch.build_scheduler(compile_value(graph_value()), ledger=subject.ledger,
                                        run_id=run.run_id, handlers=gate_registry(subject, calls),
                                        approvals=approvals)
        assert scheduler.run().awaiting_human == (("owner-gate", "release-output"),)
        approvals.record(subject.request, approval_command(run, decision="rejected"))
        with pytest.raises(sch.SchedulerError, match="approval_rejected:owner-gate"):
            scheduler.run()
        assert "owner-gate" not in calls and "publish" not in calls
    finally:
        subject.context.__exit__(None, None, None)


def test_approvals_are_keyed_by_run_node_and_scope(tmp_path):
    subject, run, approvals = gated_app(tmp_path)
    try:
        calls = []
        scheduler = sch.build_scheduler(compile_value(graph_value()), ledger=subject.ledger,
                                        run_id=run.run_id, handlers=gate_registry(subject, calls),
                                        approvals=approvals)
        scheduler.run()
        other_run = run_spec(subject)
        subject.ledger.create_run(identifier(), other_run)
        approvals.record(subject.request, approval_command(other_run))
        approvals.record(subject.request, approval_command(run, scope="other-scope"))
        approvals.record(subject.request, approval_command(run, node="publish"))
        assert scheduler.run().awaiting_human == (("owner-gate", "release-output"),)
        assert calls == ["intake", "writer"]
    finally:
        subject.context.__exit__(None, None, None)


def test_a_gated_graph_requires_the_real_approval_service(tmp_path):
    subject, run = ledger_run(tmp_path)
    with pytest.raises(sch.SchedulerError, match="approval"):
        sch.build_scheduler(compile_value(graph_value()), ledger=subject.ledger,
                            run_id=run.run_id, handlers=gate_registry(subject, []))
    with pytest.raises(sch.SchedulerError, match="approval"):
        sch.build_scheduler(compile_value(graph_value()), ledger=subject.ledger,
                            run_id=run.run_id, handlers=gate_registry(subject, []),
                            approvals=object())


# --- independent review closures (2026-09-17) ---------------------------------


def unequal_depth_join_graph():
    raw = router_graph()
    raw["nodes"] = [
        node("left", "deterministic", "왼쪽 첫 단계", outputs=[output_slot("out", "text-document")]),
        node("mid", "deterministic", "왼쪽 둘째 단계",
             inputs=[input_slot("source", "text-document")],
             outputs=[output_slot("out", "text-document")]),
        node("right", "deterministic", "오른쪽 단계", outputs=[output_slot("out", "text-document")]),
        node("join", "join", "두 경로를 합류한다",
             inputs=[input_slot("items", "text-document", multiplicity="many")],
             outputs=[output_slot("result", "text-document")]),
    ]
    raw["entry_node_ids"] = ["left", "right"]
    raw["edges"] = [
        artifact_edge("u1", "left", "out", "mid", "source", "text-document"),
        artifact_edge("u2", "mid", "out", "join", "items", "text-document", multiplicity="many"),
        artifact_edge("u3", "right", "out", "join", "items", "text-document", multiplicity="many"),
    ]
    return raw


def test_f1_a_join_waits_for_every_activated_producer_and_visits_once(tmp_path):
    subject, run = ledger_run(tmp_path)
    calls = []
    outcome = build(subject, run, unequal_depth_join_graph(), registry(subject, calls)).run()
    assert calls.count("join") == 1 and calls[-1] == "join"
    assert set(calls[:-1]) == {"left", "right", "mid"}
    assert outcome.counters == {"left": 1, "right": 1, "mid": 1, "join": 1}
    join_ids = [eid for node_id, eid in outcome.execution_ids if node_id == "join"]
    assert join_ids == [sch.execution_identity(run.run_id, "join", 0)]
    # the ledger holds exactly one join visit, never a phantom repeat
    assert len(subject.ledger.executions_for_run(run.run_id)) == 4


def gated_loop_graph():
    raw = loop_graph()
    for key in ("model_bindings", "tool_bindings", "memory_policies", "grant_refs"):
        raw[key] = []  # no agent node remains, so no binding may stay unused
    raw["nodes"] = [
        node("seed", "deterministic", "초기 상태를 만든다"),
        node("gate", "human_gate", "반복마다 사람이 승인한다"),
        node("loop", "bounded_loop", "종료 조건과 반복 한도를 판정한다"),
        node("done", "deterministic", "최종 결과를 고정한다",
             outputs=[output_slot("result", "text-document")]),
    ]
    raw["edges"] = [
        control_edge("g1", "seed", "loop"),
        control_edge("g2", "loop", "gate", loop_id="revision-loop"),
        control_edge("g3", "gate", "loop", loop_id="revision-loop"),
        control_edge("g4", "loop", "done", {"op": "eq", "fact": "loop_done", "value": True}),
    ]
    return raw


def test_f2_a_human_gate_inside_a_bounded_loop_is_refused_at_build(tmp_path):
    subject, run, approvals = gated_app(tmp_path)
    try:
        compiled = compile_value(gated_loop_graph())
        assert compiled.loop_regions[0][1] == ("gate", "loop")
        handlers = {**gate_registry(subject, []), "core.bounded_loop": lambda c, v: {"loop_done": True}}
        with pytest.raises(sch.SchedulerError, match="human_gate.*loop"):
            sch.build_scheduler(compiled, ledger=subject.ledger, run_id=run.run_id,
                                handlers=handlers, approvals=approvals)
    finally:
        subject.context.__exit__(None, None, None)


def test_f3_a_forged_newer_approval_version_never_passes_a_gate(tmp_path):
    from app.domain.schemas import ImmutableRecord
    from app.services.run_approvals import approval_identity

    subject, run, approvals = gated_app(tmp_path)
    try:
        calls = []
        scheduler = sch.build_scheduler(compile_value(graph_value()), ledger=subject.ledger,
                                        run_id=run.run_id, handlers=gate_registry(subject, calls),
                                        approvals=approvals)
        scheduler.run()
        approvals.record(subject.request, approval_command(run, decision="rejected"))
        # a version-2 record for the same identity, authored by the system root
        domain = subject.domain
        roots = domain.roots()
        forged = ImmutableRecord.create(
            kind="action_approval",
            id=approval_identity(run.run_id, "owner-gate", "release-output"),
            version=2,
            created_at_utc="2026-09-17T00:00:00.000000Z",
            actor_ref=roots.actor,
            parent_refs=(),
            purpose="operational",
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={
                "schema_version": "run-approval-v1", "run_id": run.run_id,
                "node_id": "owner-gate", "approval_scope": "release-output",
                "decision": "approved", "command_id": str(_uuid.uuid4()),
                "decided_at_utc": "2026-09-17T00:00:00.000000Z", "event_sequence": 1,
            },
        )
        domain.put(forged)
        with pytest.raises(sch.SchedulerError):
            scheduler.run()
        assert "owner-gate" not in calls and "publish" not in calls
    finally:
        subject.context.__exit__(None, None, None)
