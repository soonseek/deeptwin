"""Format-aware observed differences between an original and an alternative
(US5, T055; growth.md journey step 3, FR-018).

The framework, not a model, observes what differs: it reads the two exact
artifacts' bytes and reports where they differ in the format's own units —
text lines, table cells and rows, JSON paths — as `Observation` values ready
for `diagnosis.record_difference`. Observations describe positions and
operations only; they never interpret why (that is a `Hypothesis`), and the
alignment of positions is `proposed` (a longest-matching-block alignment),
never claimed as confirmed (a JSON path is exact, so it is). Formats this
process does not parse — PDF,
images, office containers, time media — yield one whole-artifact observation
when the bytes differ, with the reason stated as an uncertainty, so different
files are never presented as the same and no page or region difference is
invented. Everything is bounded: inputs, lines, rows, paths and the number of
itemised observations (the rest are counted, not dropped silently).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from difflib import SequenceMatcher

MAX_INPUT_BYTES = 1_048_576
MAX_LINES = 20_000
MAX_ROWS = 10_000
MAX_JSON_DEPTH = 32
MAX_OBSERVATIONS = 256  # record_difference's own bound
TEXT_MEDIA = frozenset({"text/plain", "text/markdown"})


class DifferenceObservationError(ValueError):
    """The inputs cannot be observed within the declared bounds."""


@dataclass(frozen=True, slots=True)
class ObservedDifferences:
    """What the framework observed; `observations` feed record_difference."""

    format: str
    observations: tuple[dict, ...]
    uncertainties: tuple[str, ...]
    identical: bool


def _decode(data: bytes, label: str) -> str | None:
    if b"\x00" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _span(start: int, end: int) -> list[int]:
    # 1-based inclusive lines as a reader counts them; an empty span is [n+1, n]
    return [start + 1, end]


def _text_observations(original: str, alternative: str) -> list[dict]:
    left, right = original.splitlines(), alternative.splitlines()
    if len(left) > MAX_LINES or len(right) > MAX_LINES:
        raise DifferenceObservationError("the text exceeds the line bound")
    observations = []
    matcher = SequenceMatcher(a=left, b=right, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        observations.append({
            "kind": "text_change",
            "locator": {"operation": tag, "original_lines": _span(i1, i2),
                        "alternative_lines": _span(j1, j2), "alignment": "proposed"},
            "description": {
                "replace": f"원본 {i1 + 1}–{i2}행이 대안 {j1 + 1}–{j2}행으로 바뀌었다.",
                "delete": f"원본 {i1 + 1}–{i2}행이 대안에 없다.",
                "insert": f"대안 {j1 + 1}–{j2}행이 원본에 없다.",
            }[tag],
        })
    if not observations and original != alternative:
        # the lines are equal but the text is not: line endings or a final newline
        observations.append({
            "kind": "text_change",
            "locator": {"operation": "line_endings", "alignment": "proposed"},
            "description": "행 내용은 같고 줄바꿈 또는 끝 줄바꿈만 다르다.",
        })
    return observations


def _rows(text: str) -> list[list[str]]:
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if len(rows) > MAX_ROWS:
        raise DifferenceObservationError("the table exceeds the row bound")
    return rows


def _table_observations(original: str, alternative: str) -> list[dict]:
    left, right = _rows(original), _rows(alternative)
    observations = []
    matcher = SequenceMatcher(a=[tuple(r) for r in left], b=[tuple(r) for r in right],
                              autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            # rows paired one to one: the cells that differ, by position
            for offset in range(i2 - i1):
                row_left, row_right = left[i1 + offset], right[j1 + offset]
                for column in range(max(len(row_left), len(row_right))):
                    before = row_left[column] if column < len(row_left) else None
                    after = row_right[column] if column < len(row_right) else None
                    if before == after:
                        continue
                    observations.append({
                        "kind": "table_change",
                        "locator": {"original_row": i1 + offset + 1,
                                    "alternative_row": j1 + offset + 1,
                                    "column": column + 1, "alignment": "proposed",
                                    "operation": "cell_added" if before is None
                                    else "cell_removed" if after is None else "cell_changed"},
                        "description": f"원본 {i1 + offset + 1}행 {column + 1}열과 "
                                       f"대안 {j1 + offset + 1}행 {column + 1}열의 값이 다르다.",
                    })
            continue
        observations.append({
            "kind": "table_change",
            "locator": {"operation": f"rows_{tag}", "original_rows": _span(i1, i2),
                        "alternative_rows": _span(j1, j2), "alignment": "proposed"},
            "description": f"원본 {i1 + 1}–{i2}행과 대안 {j1 + 1}–{j2}행이 대응하지 않는다 ({tag}).",
        })
    return observations


def _pointer(parts) -> str:
    return "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in parts)


def _json_observations(original, alternative) -> list[dict]:
    observations = []

    def walk(left, right, parts):
        if len(parts) > MAX_JSON_DEPTH:
            raise DifferenceObservationError("the JSON exceeds the depth bound")
        if type(left) is dict and type(right) is dict:
            for key in sorted(set(left) | set(right)):
                if key not in right:
                    note("removed", (*parts, key))
                elif key not in left:
                    note("added", (*parts, key))
                else:
                    walk(left[key], right[key], (*parts, key))
            return
        if type(left) is list and type(right) is list:
            for index in range(max(len(left), len(right))):
                if index >= len(right):
                    note("removed", (*parts, index))
                elif index >= len(left):
                    note("added", (*parts, index))
                else:
                    walk(left[index], right[index], (*parts, index))
            return
        if type(left) is not type(right) or left != right:
            note("changed", parts)

    def note(change, parts):
        pointer = _pointer(parts)
        if len(pointer) > 1_024:
            raise DifferenceObservationError("a JSON path exceeds the locator bound")
        observations.append({
            "kind": "structure_change",
            "locator": {"path": pointer, "change": change, "alignment": "confirmed"},
            "description": {"added": f"대안에만 {pointer} 값이 있다.",
                            "removed": f"원본에만 {pointer} 값이 있다.",
                            "changed": f"{pointer} 값이 다르다."}[change],
        })

    walk(original, alternative, ())
    return observations


def _finish(fmt, observations, uncertainties, identical):
    extra = len(observations) - MAX_OBSERVATIONS
    if extra > 0:
        observations = observations[:MAX_OBSERVATIONS - 1]
        observations.append({
            "kind": "structure_change",
            "locator": {"operation": "further_changes", "count": extra + 1},
            "description": f"같은 형식의 차이가 {extra + 1}개 더 있으나 항목별로 적지 않았다.",
        })
        uncertainties = [*uncertainties, f"차이 {extra + 1}개는 개수만 기록했다."]
    numbered = tuple({"observation_id": f"obs-{index + 1}", **item}
                     for index, item in enumerate(observations))
    return ObservedDifferences(fmt, numbered, tuple(uncertainties), identical)


def observe_differences(original: bytes, alternative: bytes, *, media_type: str) -> ObservedDifferences:
    """Observe how two artifacts of one declared media type differ."""

    if type(original) is not bytes or type(alternative) is not bytes:
        raise DifferenceObservationError("exact bytes are required")
    if len(original) > MAX_INPUT_BYTES or len(alternative) > MAX_INPUT_BYTES:
        raise DifferenceObservationError("an artifact exceeds the observation bound")
    if type(media_type) is not str:
        raise DifferenceObservationError("a media type is required")
    if original == alternative:
        return _finish("identical", [], [], True)
    left, right = _decode(original, "original"), _decode(alternative, "alternative")
    if left is not None and right is not None:
        if media_type == "application/json":
            try:
                parsed = json.loads(left), json.loads(right)
            except ValueError:
                parsed = None
            if parsed is not None:
                observations = _json_observations(*parsed)
                if observations:
                    return _finish("json", observations, [], False)
                return _finish("json", [{
                    "kind": "structure_change",
                    "locator": {"operation": "serialization", "alignment": "confirmed"},
                    "description": "JSON 값은 같고 직렬화(공백·키 순서·표기)만 다르다.",
                }], [], False)
        if media_type == "text/csv":
            return _finish("table", _table_observations(left, right), [], False)
        if media_type in TEXT_MEDIA or media_type == "application/json" or media_type.startswith("text/"):
            uncertainties = [] if media_type in TEXT_MEDIA else [
                f"{media_type}은 줄 단위 텍스트로 비교했다."]
            return _finish("text", _text_observations(left, right), uncertainties, False)
    return _finish("opaque", [{
        "kind": "structure_change",
        "locator": {"scope": "whole_artifact", "alignment": "unresolved"},
        "description": "두 산출물의 바이트가 다르다. 이 형식의 위치별 차이는 관측하지 않았다.",
    }], [f"{media_type} 형식은 이 과정에서 해석하지 않는다: 쪽·영역·구간 차이는 코덱 워커가 필요하다."],
        False)


def observe_boundary_output(domain_store, trace_slice, *, ordinal, alternative):
    """Observe how an alternative differs from what a sliced boundary produced.

    The original is the exact artifact the boundary execution's durable result
    names at `ordinal` (the store verifies its bytes on read); its declared
    media type is the one the transport sealed. A boundary without a result, a
    result without that artifact, or a trace the framework did not issue is
    refused — nothing is compared against a caller-described original.
    """

    from ..domain.store import BlobRef
    from .run_artifacts import _entries
    from .run_trace import TraceSlice, is_issued_trace

    if type(trace_slice) is not TraceSlice or not is_issued_trace(trace_slice):
        raise DifferenceObservationError("a framework-issued trace slice is required")
    result = trace_slice.boundary.result_ref
    if result is None:
        raise DifferenceObservationError("the boundary produced no durable result")
    try:
        entries = _entries(domain_store.get(result))
    except Exception:  # noqa: BLE001 - the store's detail stays private
        raise DifferenceObservationError("the boundary result is unreadable") from None
    if type(ordinal) is not int or not 0 <= ordinal < len(entries):
        raise DifferenceObservationError("the boundary result has no such artifact")
    entry = entries[ordinal]
    blob = entry["blob"]
    if type(blob) is not BlobRef:
        raise DifferenceObservationError("the boundary artifact is malformed")
    original = domain_store.read_blob(blob, purpose=blob.purpose)
    return observe_differences(original, alternative, media_type=entry["media_type"])


__all__ = [
    "DifferenceObservationError",
    "ObservedDifferences",
    "observe_boundary_output",
    "observe_differences",
]
