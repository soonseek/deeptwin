"""`CallRecorder`를 `FakeProvider`로 확인한다."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from deeptwin.errors import DeeptwinError
from deeptwin.llm import FakeProvider, Provider
from deeptwin.llm.calls import CallRecorder

CALL_KEYS = [
    "provider",
    "model",
    "version",
    "prompt_version",
    "input_chars",
    "output_chars",
    "seconds",
    "cached",
]


def lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_one_line_per_call(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    recorder = CallRecorder(FakeProvider(["첫 답", "둘째 답입니다"]), path)

    assert recorder.complete("지침", "과제 하나") == "첫 답"
    assert recorder.complete("긴 지침입니다", "과제") == "둘째 답입니다"

    first, second = lines(path)
    for entry in (first, second):
        assert list(entry) == CALL_KEYS
        assert entry["provider"] == "fake"
        assert entry["model"] is None
        assert entry["version"] is None
        assert entry["prompt_version"] is None
        assert entry["cached"] is False
        assert isinstance(entry["seconds"], float)
        assert entry["seconds"] >= 0
        assert round(entry["seconds"], 3) == entry["seconds"]
    assert (first["input_chars"], first["output_chars"]) == (2 + 5, 3)
    assert (second["input_chars"], second["output_chars"]) == (7 + 2, 7)


def test_passes_arguments_through(tmp_path: Path) -> None:
    fake = FakeProvider(["답"])
    recorder = CallRecorder(fake, tmp_path / "calls.jsonl")

    recorder.complete("지침", "과제", temperature=0.5, timeout=3)

    assert fake.calls == [("지침", "과제")]


def test_prompt_version(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"

    CallRecorder(FakeProvider(["답"]), path, prompt_version="diff-v1").complete("지침", "과제")

    [entry] = lines(path)
    assert entry["prompt_version"] == "diff-v1"


class _Described(FakeProvider):
    """`model`과 `version`을 가진 공급자. `version`은 글이 아니다."""

    model = "model-x"
    version = 3


def test_reads_model_and_version_only_when_they_are_text(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"

    CallRecorder(_Described(["답"]), path).complete("지침", "과제")

    [entry] = lines(path)
    assert entry["model"] == "model-x"
    assert entry["version"] is None


def test_no_line_when_the_call_fails(tmp_path: Path) -> None:
    path = tmp_path / "calls.jsonl"
    recorder = CallRecorder(FakeProvider([]), path)

    with pytest.raises(DeeptwinError) as info:
        recorder.complete("지침", "과제")

    assert info.value.code == "fake_answers_exhausted"
    assert not path.exists()


def test_recorder_is_a_provider(tmp_path: Path) -> None:
    recorder = CallRecorder(FakeProvider(["답"]), tmp_path / "calls.jsonl")

    assert isinstance(recorder, Provider)
    assert recorder.name == "fake"
