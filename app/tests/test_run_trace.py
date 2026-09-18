"""T055 (reopened): trace slicing over REAL preserved runs.

A run trace is read back from the runtime ledger's execution records plus
the durable checkpoint journal (result refs only, never raw channel state),
and sliced around one boundary execution into its ancestors and direct
dependants — the sealed `OriginalExecution` boundary a diagnosis starts
from (growth.md §OriginalExecution; runtime.md §9 read-only replay). The
runs here are produced by the actual scheduler over a real SQLite ledger.
"""

import pytest

from app.runtime import scheduler as sch
from app.services.run_trace import (
    RunTraceError,
    is_issued_trace,
    read_run_trace,
    slice_trace,
)
from app.tests.test_graph_contract import compile_value, loop_graph, router_graph
from app.tests.test_graph_execution import (
    build,
    ledger_run,
    linear_graph,
    loop_registry,
    registry,
)
from app.tests.test_langgraph_checkpoints import reopen


def test_a_completed_linear_run_reads_back_as_an_ordered_trace(tmp_path):
    subject, run = ledger_run(tmp_path)
    compiled = compile_value(linear_graph())
    build(subject, run, linear_graph(), registry(subject, [])).run()
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    assert is_issued_trace(trace)
    assert trace.run_id == run.run_id and trace.graph_digest == compiled.graph_digest
    assert [item.node_id for item in trace.executions] == ["intake", "writer", "publish"]
    assert all(item.loop_index == 0 for item in trace.executions)
    intake, writer, publish = trace.executions
    assert intake.parents == () and writer.parents == (intake.execution_id,)
    assert publish.parents == (writer.execution_id,)
    assert all(item.result_ref is not None for item in trace.executions)
    assert trace.observation_gaps == ()
    assert trace.checkpoint_revision >= 1


def test_the_trace_never_carries_raw_channel_state_or_cursor_bytes(tmp_path):
    subject, run = ledger_run(tmp_path)
    compiled = compile_value(linear_graph())
    build(subject, run, linear_graph(), registry(subject, [])).run()
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    fields = set(trace.__dataclass_fields__)
    assert fields == {
        "run_id", "graph_digest", "node_ids", "executions", "checkpoint_revision",
        "observation_gaps", "_issuer_token",
    }
    execution_fields = set(trace.executions[0].__dataclass_fields__)
    assert execution_fields == {
        "execution_id", "node_id", "loop_index", "parents", "result_ref", "created_at_ms",
        "attempts", "producing_attempt_id",
    }
    assert "cursor" not in repr(trace) and "channel" not in repr(trace)


def test_a_failed_run_shows_the_gap_and_survives_reopen(tmp_path):
    subject, run = ledger_run(tmp_path)
    compiled = compile_value(linear_graph())
    with pytest.raises(sch.SchedulerError):
        build(subject, run, linear_graph(), registry(subject, [], failing="writer")).run()
    reopen(subject, tmp_path)
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    assert [item.node_id for item in trace.executions] == ["intake", "writer"]
    assert trace.executions[0].result_ref is not None
    assert trace.executions[1].result_ref is None  # recorded visit, no durable result
    assert trace.observation_gaps == (trace.executions[1].execution_id,)


def test_loop_iterations_are_distinct_executions_in_order(tmp_path):
    subject, run = ledger_run(tmp_path)
    compiled = compile_value(loop_graph())
    build(subject, run, loop_graph(), loop_registry(subject, [], done_after=2)).run()
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    assert [(item.node_id, item.loop_index) for item in trace.executions] == [
        ("seed", 0), ("loop", 0), ("revise", 0), ("loop", 1), ("revise", 1), ("loop", 2), ("done", 0),
    ]
    revise_second = trace.executions[4]
    assert revise_second.parents == (trace.executions[3].execution_id,)  # loop visit 1


def test_slicing_around_a_boundary_keeps_ancestors_and_direct_dependants(tmp_path):
    subject, run = ledger_run(tmp_path)
    compiled = compile_value(router_graph())
    build(subject, run, router_graph(), registry(subject, [])).run()
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    assert [item.node_id for item in trace.executions] == ["choose", "accept", "join"]
    sliced = slice_trace(trace, boundary_node_id="accept")
    assert sliced.boundary.node_id == "accept" and sliced.boundary.loop_index == 0
    assert [item.node_id for item in sliced.ancestors] == ["choose"]
    assert [item.node_id for item in sliced.dependants] == ["join"]
    assert sliced.excluded_node_ids == ("revise",)  # statically possible, never activated
    assert sliced.trace_run_id == run.run_id
    with pytest.raises(RunTraceError):
        slice_trace(trace, boundary_node_id="revise")  # no execution: nothing to slice
    with pytest.raises(RunTraceError):
        slice_trace(trace, boundary_node_id="accept", loop_index=3)


def test_reading_requires_the_exact_ledger_run_and_graph(tmp_path):
    subject, run = ledger_run(tmp_path)
    compiled = compile_value(linear_graph())
    build(subject, run, linear_graph(), registry(subject, [])).run()
    with pytest.raises(RunTraceError):
        read_run_trace(object(), run.run_id, compiled)
    with pytest.raises(RunTraceError):
        read_run_trace(subject.ledger, "not-a-uuid", compiled)
    other = compile_value(router_graph())
    with pytest.raises(RunTraceError):
        read_run_trace(subject.ledger, run.run_id, other)  # journal bound to another graph
    unknown = "00000000-0000-4000-8000-00000000ffff"
    with pytest.raises(RunTraceError):
        read_run_trace(subject.ledger, unknown, compiled)


def test_the_attempt_layer_attributes_the_result_to_the_attempt_that_produced_it(tmp_path):
    # T048/T055 attempt layer: each traced execution carries its ledger attempts, and
    # the durable result is attributed only to the attempt the bound checkpoint row
    # names — a past attempt never carries a later result (experience.md §7)
    from app.runtime import node_attempts as na
    from app.services.run_trace import TraceAttempt
    from app.tests import test_scheduler_attempt_dispatch as dispatch

    subject, run = dispatch.started(tmp_path)
    transport = dispatch.FailingOnce(subject)
    with pytest.raises(sch.SchedulerError):
        dispatch.build(subject, run, dispatch.dispatcher(subject, transport), dispatch.handlers(subject, [])).run()
    dispatch.build(subject, run, dispatch.retrying(subject, transport), dispatch.handlers(subject, [])).run()
    compiled = compile_value(linear_graph())
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    writer = next(item for item in trace.executions if item.node_id == "writer")
    first = na.attempt_identity(run.run_id, "writer", 0, 0)
    second = na.attempt_identity(run.run_id, "writer", 0, 1)
    assert [item.attempt_id for item in writer.attempts] == [first, second]
    assert all(type(item) is TraceAttempt for item in writer.attempts)
    failed, succeeded = writer.attempts
    assert failed.attempt_no == 1 and failed.terminal_outcome == "failed"
    assert failed.remote_terminal_observed == "failed" and failed.usage_finality == "final"
    assert failed.produced_result is False and failed.bound_revision is None
    assert succeeded.attempt_no == 2 and succeeded.terminal_outcome == "succeeded"
    assert succeeded.produced_result is True
    assert writer.producing_attempt_id == second
    assert writer.result_ref == subject.refs.produced
    bound = dispatch.bound_rows(subject, run)
    assert succeeded.bound_revision == bound[-1]["revision"]
    assert set(TraceAttempt.__dataclass_fields__) == {
        "attempt_id", "attempt_no", "phase", "terminal_outcome", "remote_terminal_observed",
        "usage_finality", "cancel_state", "produced_result", "bound_revision",
    }
    # executions the fixture handlers produced have no attempts and attribute nothing
    intake = next(item for item in trace.executions if item.node_id == "intake")
    assert intake.attempts == () and intake.producing_attempt_id is None
    assert intake.result_ref is not None
    # the trace survives a restart with the same attribution
    dispatch.restart(subject, tmp_path)
    again = read_run_trace(subject.ledger, run.run_id, compiled)
    writer_again = next(item for item in again.executions if item.node_id == "writer")
    assert writer_again.producing_attempt_id == second
    assert [item.produced_result for item in writer_again.attempts] == [False, True]


def test_ledger_failures_while_reading_the_attempt_layer_are_trace_errors(tmp_path, monkeypatch):
    from app.runtime.ledger import DispatchBlocked
    from app.tests import test_scheduler_attempt_dispatch as dispatch

    subject, run = dispatch.started(tmp_path)
    dispatch.build(subject, run, dispatch.dispatcher(subject, dispatch.Transport(dispatch.succeeded(subject))),
                   dispatch.handlers(subject, [])).run()
    compiled = compile_value(linear_graph())
    assert read_run_trace(subject.ledger, run.run_id, compiled).executions
    for name, error in (("bound_checkpoints_for_run", DispatchBlocked("PRIVATE_SESSION")),
                        ("attempts_for_run", KeyError("PRIVATE_KEY")),
                        ("checkpoint_for_replay", RuntimeError("PRIVATE_STORAGE"))):
        original = getattr(subject.ledger, name)

        def failing(*args, _error=error, **kwargs):
            raise _error

        monkeypatch.setattr(subject.ledger, name, failing)
        with pytest.raises(RunTraceError) as failure:
            read_run_trace(subject.ledger, run.run_id, compiled)
        assert "PRIVATE" not in str(failure.value)
        monkeypatch.setattr(subject.ledger, name, original)


def test_a_result_preserved_only_as_a_pending_write_is_attributed_and_not_a_gap(tmp_path, monkeypatch):
    # a crash between the bound pending-writes row and the merging checkpoint: the
    # journal preserved the result (LangGraph resumes from it), so the trace shows it
    from app.runtime import checkpoints as cp
    from app.runtime import node_attempts as na
    from app.tests import test_scheduler_attempt_dispatch as dispatch

    subject, run = dispatch.started(tmp_path)
    original = cp.LedgerCheckpointSaver._append
    writer_execution = sch.execution_identity(run.run_id, "writer", 0)
    state = {"bound": False}

    def crashing(self, kind, data):
        if kind == "checkpoint" and state["bound"]:
            raise RuntimeError("PRIVATE_CRASH")
        original(self, kind, data)
        if kind == "writes" and any(
            entry["channel"] == "results" and writer_execution in entry["value"]
            for entry in data["writes"]
        ):
            state["bound"] = True

    monkeypatch.setattr(cp.LedgerCheckpointSaver, "_append", crashing)
    with pytest.raises(sch.SchedulerError):
        dispatch.build(subject, run, dispatch.dispatcher(subject, dispatch.Transport(dispatch.succeeded(subject))),
                       dispatch.handlers(subject, [])).run()
    monkeypatch.undo()
    compiled = compile_value(linear_graph())
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    writer = next(item for item in trace.executions if item.node_id == "writer")
    assert writer.producing_attempt_id == na.attempt_identity(run.run_id, "writer", 0, 0)
    assert writer.result_ref == subject.refs.produced
    assert writer.attempts[0].produced_result is True
    assert writer.execution_id not in trace.observation_gaps


def test_a_result_no_attempt_produced_is_unattributed_not_misattributed(tmp_path):
    # the writer's sent attempt failed under the dispatcher; the run was then resumed
    # with a plain handler: the result exists, the attempt stays not producing
    from app.tests import test_scheduler_attempt_dispatch as dispatch

    subject, run = dispatch.started(tmp_path)
    with pytest.raises(sch.SchedulerError):
        dispatch.build(subject, run, dispatch.dispatcher(subject, dispatch.FailingOnce(subject)),
                       dispatch.handlers(subject, [])).run()
    dispatch.build(subject, run, None, dispatch.handlers(subject, [], agent=lambda context, view: subject.refs.result)).run()
    compiled = compile_value(linear_graph())
    trace = read_run_trace(subject.ledger, run.run_id, compiled)
    writer = next(item for item in trace.executions if item.node_id == "writer")
    assert writer.result_ref == subject.refs.result
    assert [(item.attempt_no, item.terminal_outcome, item.produced_result) for item in writer.attempts] == [
        (1, "failed", False),
    ]
    assert writer.producing_attempt_id is None
    assert writer.execution_id not in trace.observation_gaps
