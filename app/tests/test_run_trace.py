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
