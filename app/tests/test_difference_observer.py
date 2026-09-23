"""T055: the framework observes format-aware differences from the exact bytes.

Text lines, table cells/rows and JSON paths are located in the format's own
units; alignment is `proposed` (or `confirmed` for a JSON path, which is exact),
never asserted beyond what the matcher found; formats this process does not
parse yield one whole-artifact observation with the reason as an uncertainty,
so different files never read as the same; identical bytes observe nothing.
Every observation feeds diagnosis.record_difference unchanged.
"""

import json

import pytest

from app.services.diagnosis import Observation, record_difference
from app.services.difference_observer import (
    MAX_OBSERVATIONS,
    DifferenceObservationError,
    observe_differences,
)
from app.tests.test_diagnosis import alternative


def test_text_lines_are_located_as_replace_delete_and_insert():
    original = "제목\n첫 문단\n둘째 문단\n끝\n".encode()
    changed = "제목\n첫 문단 (출처: A)\n끝\n추가 문단\n".encode()
    observed = observe_differences(original, changed, media_type="text/markdown")
    assert observed.format == "text" and not observed.identical
    locators = [item["locator"] for item in observed.observations]
    assert locators[0] == {"operation": "replace", "original_lines": [2, 3],
                           "alternative_lines": [2, 2], "alignment": "proposed"}
    assert locators[1] == {"operation": "insert", "original_lines": [5, 4],
                           "alternative_lines": [4, 4], "alignment": "proposed"}
    assert all(item["kind"] == "text_change" for item in observed.observations)
    assert [item["observation_id"] for item in observed.observations] == ["obs-1", "obs-2"]


def test_only_line_endings_differ_is_still_a_difference():
    observed = observe_differences(b"a\nb\n", b"a\r\nb", media_type="text/plain")
    assert observed.observations[0]["locator"]["operation"] == "line_endings"


def test_table_cells_and_rows_are_located():
    original = b"item,value\nsources,12\nlength,300\n"
    changed = b"item,value\nsources,14\nlength,300\nnotes,1\n"
    observed = observe_differences(original, changed, media_type="text/csv")
    assert observed.format == "table"
    cell, rows = observed.observations
    assert cell["locator"] == {"original_row": 2, "alternative_row": 2, "column": 2,
                               "alignment": "proposed", "operation": "cell_changed"}
    assert rows["locator"]["operation"] == "rows_insert"
    assert rows["locator"]["alternative_rows"] == [4, 4]
    # a formula-looking cell is compared as text, never evaluated
    formula = observe_differences(b"=1+1\n", b"=2\n", media_type="text/csv")
    assert formula.observations[0]["locator"]["operation"] == "cell_changed"


def test_json_paths_are_exact():
    original = json.dumps({"a": 1, "list": [1, 2], "gone": True, "k/x": "v"}).encode()
    changed = json.dumps({"a": "1", "list": [1], "new": None, "k/x": "v"}).encode()
    observed = observe_differences(original, changed, media_type="application/json")
    found = {(item["locator"]["path"], item["locator"]["change"]) for item in observed.observations}
    assert found == {("/a", "changed"), ("/list/1", "removed"), ("/gone", "removed"),
                     ("/new", "added")}
    same = observe_differences(b'{"a":1,"b":2}', b'{ "b": 2, "a": 1 }', media_type="application/json")
    assert same.observations[0]["locator"]["operation"] == "serialization"


def test_unparsed_formats_are_one_whole_artifact_observation_with_the_reason():
    observed = observe_differences(b"%PDF-1.7 a", b"%PDF-1.7 b", media_type="application/pdf")
    assert observed.format == "opaque" and len(observed.observations) == 1
    assert observed.observations[0]["locator"] == {"scope": "whole_artifact", "alignment": "unresolved"}
    assert "코덱 워커" in observed.uncertainties[0]
    binary_text = observe_differences(b"\x00a", b"\x00b", media_type="text/plain")
    assert binary_text.format == "opaque"


def test_identical_bytes_observe_nothing():
    observed = observe_differences(b"same", b"same", media_type="text/plain")
    assert observed.identical and observed.observations == ()


def test_many_changes_are_counted_not_dropped():
    original = "\n".join(f"{i},a" for i in range(600)).encode()
    changed = "\n".join(f"{i},b" for i in range(600)).encode()
    observed = observe_differences(original, changed, media_type="text/csv")
    assert len(observed.observations) == MAX_OBSERVATIONS
    last = observed.observations[-1]
    assert last["locator"] == {"operation": "further_changes", "count": 600 - MAX_OBSERVATIONS + 1}
    assert any("개수만" in item for item in observed.uncertainties)


def test_bounds_are_enforced():
    with pytest.raises(DifferenceObservationError):
        observe_differences(b"a" * 1_048_577, b"b", media_type="text/plain")
    with pytest.raises(DifferenceObservationError):
        observe_differences("a", b"b", media_type="text/plain")
    deep = b"[" * 40 + b"]" * 40
    with pytest.raises(DifferenceObservationError):
        observe_differences(deep, deep.replace(b"[]", b"[1]", 1), media_type="application/json")


def test_observations_feed_record_difference_unchanged():
    observed = observe_differences(b"a\nb\n", b"a\nc\n", media_type="text/plain")
    for item in observed.observations:
        Observation.from_untrusted(item)
    difference = record_difference(alternative(), list(observed.observations),
                                   uncertainties=list(observed.uncertainties))
    assert difference.observations[0].as_dict()["locator"]["original_lines"] == [2, 2]


def test_a_sliced_boundary_output_is_the_original_compared(tmp_path):
    """Over a real scheduler run: the writer's sealed output artifact, read back
    through the run trace's boundary slice, is what the alternative is observed
    against — never a caller-described original."""

    from uuid import uuid4

    from app.domain.schemas import ImmutableRecord
    from app.runtime.scheduler import build_scheduler
    from app.services.difference_observer import observe_boundary_output
    from app.services.run_trace import read_run_trace, slice_trace
    from app.tests.test_graph_contract import compile_value
    from app.tests.test_graph_execution import ledger_run, linear_graph

    subject, run = ledger_run(tmp_path)
    domain = subject.domain
    roots = domain.roots()
    blob = domain.put_blob("제목\n초안 문단\n".encode(), purpose="operational")
    record = ImmutableRecord.create(
        kind="artifact", id=str(uuid4()), version=1, created_at_utc="2026-09-23T00:00:00.000000Z",
        actor_ref=roots.actor, parent_refs=(), purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content={"schema_version": "fixture-output-v1", "output": {}, "artifacts": [
            {"ordinal": 0, "role": "draft", "media_type": "text/markdown", "blob": blob.as_dict()}]},
    )
    domain.put(record)

    def produce(context, view):
        return record.ref if context.node_id == "writer" else subject.refs.result

    compiled = compile_value(linear_graph())
    build_scheduler(compiled, ledger=subject.ledger, run_id=run.run_id,
                    handlers={"core.deterministic": produce, "core.agent": produce}).run()
    boundary = slice_trace(read_run_trace(subject.ledger, run.run_id, compiled),
                           boundary_node_id="writer")
    observed = observe_boundary_output(domain, boundary, ordinal=0,
                                       alternative="제목\n출처를 단 문단\n".encode())
    assert observed.format == "text"
    assert observed.observations[0]["locator"]["original_lines"] == [2, 2]
    # the intake boundary sealed no artifact list; a missing ordinal is refused
    intake = slice_trace(read_run_trace(subject.ledger, run.run_id, compiled),
                         boundary_node_id="intake")
    with pytest.raises(DifferenceObservationError):
        observe_boundary_output(domain, intake, ordinal=0, alternative=b"x")
    with pytest.raises(DifferenceObservationError):
        observe_boundary_output(domain, boundary, ordinal=1, alternative=b"x")
    with pytest.raises(DifferenceObservationError):
        observe_boundary_output(domain, object(), ordinal=0, alternative=b"x")
