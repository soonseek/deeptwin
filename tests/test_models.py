"""파일 모델의 필드와 형식 검사. 데이터는 모두 가상이다."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from deeptwin.models import (
    Candidate,
    Card,
    Example,
    Principle,
    Priority,
    Reference,
    Task,
)


def card_data(**fields: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "id": "card-0001",
        "skill": "minimal",
        "decision_point": "opening",
        "status": "active",
        "approval": "human",
        "when": {"purpose": ["문의"]},
        "choose": "첫 문장에서 문의에 고맙다고 한다",
        **fields,
    }


def example_data(**fields: Any) -> dict[str, Any]:
    return {
        "id": "ex-0001",
        "skill": "minimal",
        "kind": "good",
        "text": "문의 주셔서 고맙습니다.\n",
        "status": "active",
        "approval": "human",
        **fields,
    }


def priority_data(**fields: Any) -> dict[str, Any]:
    return {
        "id": "pri-01",
        "rule": "정확함이 먼저다",
        "status": "active",
        "approval": "human",
        **fields,
    }


def principle_data(**fields: Any) -> dict[str, Any]:
    return {
        "id": "prin-01",
        "rule": "수치를 부풀리지 않는다",
        "kind": "never",
        "status": "active",
        "approval": "human",
        **fields,
    }


def task_data(**fields: Any) -> dict[str, Any]:
    return {"id": "task-0001", "skill": "minimal", "split": "train", "input": "문의", **fields}


def candidate_data(**fields: Any) -> dict[str, Any]:
    return {
        "id": "cand-0001",
        "action": "add",
        "layer": "tendency",
        "target": None,
        "item": card_data(),
        "cause": "missing_card",
        "evidence": ["run-0001"],
        **fields,
    }


def errors(info: pytest.ExceptionInfo[ValidationError]) -> list[tuple[Any, str]]:
    return [(tuple(e["loc"]), e["type"]) for e in info.value.errors()]


# 층 항목의 공통 필드


@pytest.mark.parametrize(
    ("model", "data", "layer"),
    [
        (Example, example_data(), "instinct"),
        (Card, card_data(), "tendency"),
        (Priority, priority_data(), "priority"),
        (Principle, principle_data(), "principle"),
    ],
)
def test_layer_is_fixed_per_model_and_defaults_to_it(
    model: type[Example | Card | Priority | Principle], data: dict[str, Any], layer: str
) -> None:
    item = model.model_validate(data)

    assert item.layer == layer
    assert item.schema_ == 1
    assert item.evidence == []
    assert item.version == 1
    assert item.supersedes is None
    assert model.model_validate({**data, "layer": layer}) == item
    with pytest.raises(ValidationError) as info:
        model.model_validate({**data, "layer": "other"})
    assert errors(info) == [(("layer",), "literal_error")]


def test_card_reads_every_field_of_the_design() -> None:
    card = Card.model_validate(
        card_data(
            because="고맙다는 말이 먼저 오면 덜 딱딱하다고 본다",
            **{"except": "항의 메일은 사과로 시작한다"},
            outcome=None,
            differs_from_default="기본 모델은 바로 답부터 쓴다",
            conflicts_with=["card-0002"],
            evidence=["run-0001"],
            stats={"injected": 3, "agreed": 2, "last_used": date(2026, 11, 18)},
            version=2,
            supersedes="card-0000",
        )
    )

    assert card.except_ == "항의 메일은 사과로 시작한다"
    assert card.stats.injected == 3
    assert card.stats.last_used == date(2026, 11, 18)
    dumped = card.model_dump(by_alias=True)
    assert dumped["except"] == "항의 메일은 사과로 시작한다"
    assert "except_" not in dumped
    assert list(dumped)[0] == "schema"


def test_extension_fields_are_kept() -> None:
    card = Card.model_validate(card_data(x_note="확장 필드", stats={"x_hits": 1}))

    dumped = card.model_dump(by_alias=True)
    assert dumped["x_note"] == "확장 필드"
    assert dumped["stats"]["x_hits"] == 1


def test_card_needs_choose() -> None:
    data = card_data()
    del data["choose"]

    with pytest.raises(ValidationError) as info:
        Card.model_validate(data)

    assert errors(info) == [(("choose",), "missing")]


# schema


def test_missing_schema_reads_as_1() -> None:
    assert Principle.model_validate(principle_data()).schema_ == 1
    assert Task.model_validate(task_data()).schema_ == 1


@pytest.mark.parametrize("schema", [2, 0])
def test_unknown_schema_is_rejected(schema: int) -> None:
    with pytest.raises(ValidationError) as info:
        Principle.model_validate(principle_data(schema=schema))

    assert errors(info) == [(("schema",), "value_error")]
    if schema == 2:
        assert "읽을 수 있는 schema는 1까지입니다" in str(info.value)


# 예시


@pytest.mark.parametrize("kind", ["good", "avoid"])
def test_good_and_avoid_examples_need_text(kind: str) -> None:
    with pytest.raises(ValidationError) as info:
        Example.model_validate(example_data(kind=kind, text=None))

    assert errors(info) == [((), "value_error")]
    assert f"kind가 {kind}이면 text가 있어야 합니다" in str(info.value)


@pytest.mark.parametrize("missing", ["before", "after"])
def test_pair_examples_need_before_and_after(missing: str) -> None:
    data = example_data(kind="pair", text=None, before="고치기 전", after="고친 뒤")
    del data[missing]

    with pytest.raises(ValidationError) as info:
        Example.model_validate(data)

    assert errors(info) == [((), "value_error")]
    assert f"없는 필드: {missing}" in str(info.value)


def test_example_defaults() -> None:
    pair = Example.model_validate(
        example_data(kind="pair", text=None, before="고치기 전", after="고친 뒤")
    )

    assert pair.grade == "usual"
    assert pair.source == "past_work"
    assert pair.tags == {}


# 기준과 과제


@pytest.mark.parametrize("kind", ["my_version", "edit"])
def test_written_references_need_text(kind: str) -> None:
    with pytest.raises(ValidationError) as info:
        Reference.model_validate({"kind": kind})

    assert errors(info) == [((), "value_error")]
    assert f"kind가 {kind}이면 text가 있어야 합니다" in str(info.value)


@pytest.mark.parametrize("missing", ["picked", "rejected"])
def test_pick_references_need_picked_and_rejected(missing: str) -> None:
    data = {"kind": "pick", "picked": "고른 답장", "rejected": "버린 답장"}
    del data[missing]

    with pytest.raises(ValidationError) as info:
        Reference.model_validate(data)

    assert f"없는 필드: {missing}" in str(info.value)


def test_task_reads_reference() -> None:
    task = Task.model_validate(
        task_data(reference={"kind": "pick", "picked": "고른 답장", "rejected": "버린 답장"})
    )

    assert task.reference is not None
    assert task.reference.kind == "pick"
    assert task.reference.grade == "usual"
    assert Task.model_validate(task_data()).reference is None


def test_task_rejects_a_reference_without_its_body() -> None:
    with pytest.raises(ValidationError) as info:
        Task.model_validate(task_data(reference={"kind": "edit"}))

    assert errors(info) == [(("reference",), "value_error")]


# 후보


def test_candidate_item_takes_the_model_of_its_layer() -> None:
    candidate = Candidate.model_validate(candidate_data())

    assert isinstance(candidate.item, Card)
    assert candidate.item.choose == "첫 문장에서 문의에 고맙다고 한다"
    assert candidate.status == "pending"
    assert Candidate.model_validate(candidate_data(item=candidate.item)) == candidate


def test_candidate_item_must_match_its_layer() -> None:
    item = card_data()
    del item["choose"]

    with pytest.raises(ValidationError) as missing:
        Candidate.model_validate(candidate_data(item=item))
    with pytest.raises(ValidationError) as other_layer:
        Candidate.model_validate(candidate_data(layer="principle"))
    with pytest.raises(ValidationError) as item_of_other_layer:
        Candidate.model_validate(
            candidate_data(layer="principle", item=card_data(layer="tendency"))
        )

    assert errors(missing) == [(("item", "choose"), "missing")]
    assert errors(other_layer) == [(("item", "rule"), "missing"), (("item", "kind"), "missing")]
    assert (("item", "layer"), "literal_error") in errors(item_of_other_layer)


def test_candidate_with_wrong_layer_reports_only_the_layer() -> None:
    with pytest.raises(ValidationError) as info:
        Candidate.model_validate(candidate_data(layer="habit"))

    assert errors(info) == [(("layer",), "literal_error")]
