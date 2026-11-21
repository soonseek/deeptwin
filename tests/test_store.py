"""저장 계층: 일곱 파일 읽기·쓰기, 형식 오류의 줄 번호, 잠금. 데이터는 모두 가상이다."""

from __future__ import annotations

import textwrap
from datetime import date
from pathlib import Path

import pytest
from filelock import FileLock

from deeptwin.errors import DeeptwinError
from deeptwin.models import (
    Candidate,
    Card,
    CardStats,
    DecisionPoint,
    Example,
    Principle,
    Priority,
    Reference,
    Skill,
    Task,
)
from deeptwin.store.files import write_model
from deeptwin.store.project import DeepTwin

CARD_YAML = """\
# 가상 인물의 판단 카드. 테스트용으로 지어낸 것이다.
schema: 1
id: card-0001
layer: tendency
skill: minimal
decision_point: opening
status: active
approval: human
when:
  purpose: [문의]
choose: 첫 문장에서 문의에 고맙다고 한다
because: 고맙다는 말이 먼저 오면 덜 딱딱하다고 본다
except: 항의 메일은 사과로 시작한다
"""

PRINCIPLE_ITEM = """\
- schema: 1
  id: {id}
  rule: {rule}
  kind: never
  check: null
  scope: []
  status: active
  approval: human
"""


@pytest.fixture
def deeptwin(minimal_copy: Path) -> DeepTwin:
    return DeepTwin.init(minimal_copy).deeptwin


def write(path: Path, text: str) -> Path:
    """줄바꿈을 바꾸지 않고 쓴다. 줄 번호를 운영체제와 관계없이 같게 둔다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(textwrap.dedent(text).encode("utf-8"))
    return path


def invalid(info: pytest.ExceptionInfo[DeeptwinError]) -> list[str]:
    assert info.value.code == "invalid_file"
    return info.value.message.splitlines()


def principles_path(deeptwin: DeepTwin) -> Path:
    return deeptwin.path / "layers" / "principles.yaml"


def card_path(deeptwin: DeepTwin, name: str = "card-0001") -> Path:
    return deeptwin.path / "layers" / "cards" / f"{name}.yaml"


# 형식이 틀린 파일


def test_wrong_value_points_to_its_line(deeptwin: DeepTwin) -> None:
    path = principles_path(deeptwin)
    path.write_bytes(path.read_bytes().replace(b"kind: never", b"kind: nevr"))

    with pytest.raises(DeeptwinError) as info:
        deeptwin.principles()

    assert invalid(info) == [
        ".deeptwin/layers/principles.yaml:5: kind: 쓸 수 있는 값은 'must', 'never'입니다"
        "(받은 값: 'nevr')"
    ]


def test_missing_field_points_to_where_the_item_starts(deeptwin: DeepTwin) -> None:
    write(card_path(deeptwin), CARD_YAML.replace("choose: 첫 문장에서 문의에 고맙다고 한다\n", ""))

    with pytest.raises(DeeptwinError) as info:
        deeptwin.cards()

    assert invalid(info) == [
        ".deeptwin/layers/cards/card-0001.yaml:2: choose: 꼭 있어야 하는 필드가 없습니다"
    ]


def test_missing_field_in_a_list_points_to_that_item(deeptwin: DeepTwin) -> None:
    second = PRINCIPLE_ITEM.format(id="prin-02", rule="약속하지 않는다")
    write(
        principles_path(deeptwin),
        PRINCIPLE_ITEM.format(id="prin-01", rule="수치를 부풀리지 않는다")
        + second.replace("  rule: 약속하지 않는다\n", ""),
    )

    with pytest.raises(DeeptwinError) as info:
        deeptwin.principles()

    assert invalid(info) == [
        ".deeptwin/layers/principles.yaml:9: rule: 꼭 있어야 하는 필드가 없습니다"
    ]


def test_yaml_syntax_error_uses_the_line_yaml_reports(deeptwin: DeepTwin) -> None:
    write(card_path(deeptwin), CARD_YAML.replace("purpose: [문의]", "purpose: [문의"))

    with pytest.raises(DeeptwinError) as info:
        deeptwin.cards()

    assert invalid(info) == [
        ".deeptwin/layers/cards/card-0001.yaml:11: YAML 문법이 틀렸습니다: "
        "expected ',' or ']', but got ':' (while parsing a flow sequence: 10번째 줄)"
    ]


def test_higher_schema_points_to_the_schema_line(deeptwin: DeepTwin) -> None:
    second = PRINCIPLE_ITEM.format(id="prin-02", rule="약속하지 않는다")
    write(
        principles_path(deeptwin),
        PRINCIPLE_ITEM.format(id="prin-01", rule="수치를 부풀리지 않는다")
        + second.replace("schema: 1", "schema: 2"),
    )

    with pytest.raises(DeeptwinError) as info:
        deeptwin.principles()

    assert invalid(info) == [
        ".deeptwin/layers/principles.yaml:9: schema: 읽을 수 있는 schema는 1까지입니다"
        "(받은 값: 2). deeptwin을 새 버전으로 올리세요."
    ]


def test_task_split_must_match_its_folder(deeptwin: DeepTwin) -> None:
    path = deeptwin.path / "tasks" / "train" / "task-0001.yaml"
    path.write_bytes(path.read_bytes().replace(b"split: train", b"split: spare"))

    with pytest.raises(DeeptwinError) as info:
        deeptwin.task("task-0001")

    assert invalid(info) == [
        ".deeptwin/tasks/train/task-0001.yaml:5: split: 과제가 든 폴더(tasks/train)와 다릅니다"
        "(받은 값: 'spare')"
    ]


def test_file_name_must_match_id(deeptwin: DeepTwin) -> None:
    write(card_path(deeptwin), CARD_YAML.replace("id: card-0001", "id: card-0002"))

    with pytest.raises(DeeptwinError) as info:
        deeptwin.cards()

    assert invalid(info) == [
        ".deeptwin/layers/cards/card-0001.yaml:3: id: 파일 이름과 다릅니다"
        "(파일 이름: card-0001, 받은 값: 'card-0002')"
    ]


def test_several_errors_are_listed_by_line(deeptwin: DeepTwin) -> None:
    write(
        principles_path(deeptwin),
        """\
        - id: prin-01
          kind: nevr
          rule: 3
          approval: human
        """,
    )

    with pytest.raises(DeeptwinError) as info:
        deeptwin.principles()

    assert invalid(info) == [
        ".deeptwin/layers/principles.yaml:1: status: 꼭 있어야 하는 필드가 없습니다",
        ".deeptwin/layers/principles.yaml:2: kind: 쓸 수 있는 값은 'must', 'never'입니다"
        "(받은 값: 'nevr')",
        ".deeptwin/layers/principles.yaml:3: rule: 글이어야 합니다(받은 값: 3)",
    ]


def test_nested_field_names_and_lines(deeptwin: DeepTwin) -> None:
    config = deeptwin.root / "skills" / "minimal" / "skill.yaml"
    config.write_bytes(config.read_bytes().replace(b"weight: 1}", "weight: 높음}".encode()))

    with pytest.raises(DeeptwinError) as info:
        deeptwin.skill("minimal")

    assert invalid(info) == [
        "skills/minimal/skill.yaml:6: decision_points[1].weight: 정수여야 합니다(받은 값: '높음')"
    ]


def test_candidate_item_errors_point_into_the_item(deeptwin: DeepTwin) -> None:
    write(
        deeptwin.path / "candidates" / "cand-0001.yaml",
        """\
        schema: 1
        id: cand-0001
        action: add
        layer: tendency
        target: null
        item:
          id: card-0009
          skill: minimal
          decision_point: opening
          status: candidate
          approval: human
          choose: 3
        cause: missing_card
        evidence: [run-0001]
        status: pending
        """,
    )

    with pytest.raises(DeeptwinError) as info:
        deeptwin.candidates()

    assert invalid(info) == [
        ".deeptwin/candidates/cand-0001.yaml:12: item.choose: 글이어야 합니다(받은 값: 3)"
    ]


def test_a_mapping_file_that_is_a_list_is_rejected(deeptwin: DeepTwin) -> None:
    write(card_path(deeptwin), "- 카드가 아니다\n")

    with pytest.raises(DeeptwinError) as info:
        deeptwin.cards()

    assert invalid(info) == [
        ".deeptwin/layers/cards/card-0001.yaml:1: 매핑(키: 값)이어야 합니다"
        "(받은 값: ['카드가 아니다'])"
    ]


def test_a_file_that_is_not_utf8_is_rejected(deeptwin: DeepTwin) -> None:
    card_path(deeptwin).write_bytes(b"schema: 1\nid: card-0001\nchoose: \xff\n")

    with pytest.raises(DeeptwinError) as info:
        deeptwin.cards()

    assert invalid(info) == [".deeptwin/layers/cards/card-0001.yaml:3: UTF-8 글로 읽을 수 없습니다"]


# 순서


def test_folder_files_come_in_file_name_order(deeptwin: DeepTwin) -> None:
    for name in ("card-0003", "card-0001", "card-0002"):
        write(card_path(deeptwin, name), CARD_YAML.replace("id: card-0001", f"id: {name}"))
    write(card_path(deeptwin).with_name(".card-0004.yaml"), "숨은 파일은 읽지 않는다: [")
    write(card_path(deeptwin).with_name("notes.txt"), "yaml이 아닌 파일은 읽지 않는다")
    write(card_path(deeptwin).with_name("card-0005.YAML"), "확장자는 대소문자까지 맞아야 한다: [")

    assert [card.id for card in deeptwin.cards()] == ["card-0001", "card-0002", "card-0003"]


def test_list_files_keep_the_order_written(deeptwin: DeepTwin) -> None:
    write(
        principles_path(deeptwin),
        "".join(PRINCIPLE_ITEM.format(id=f"prin-0{n}", rule=f"원칙 {n}") for n in (3, 1, 2)),
    )
    write(
        deeptwin.path / "layers" / "priorities.yaml",
        """\
        - {id: pri-02, rule: 정확함이 친절함보다 먼저다, scope: [], status: active, approval: human}
        - {id: pri-01, rule: 친절함이 짧음보다 먼저다, scope: [], status: active, approval: human}
        """,
    )

    assert [p.id for p in deeptwin.principles()] == ["prin-03", "prin-01", "prin-02"]
    assert [p.id for p in deeptwin.priorities()] == ["pri-02", "pri-01"]


def test_absent_and_empty_files_read_as_nothing(tmp_path: Path) -> None:
    deeptwin = DeepTwin.init(tmp_path).deeptwin

    assert deeptwin.examples() == []
    assert deeptwin.cards() == []
    assert deeptwin.priorities() == []
    assert deeptwin.principles() == []
    assert deeptwin.candidates() == []
    write(principles_path(deeptwin), "# 아직 원칙이 없다\n")
    assert deeptwin.principles() == []


# 쓰고 다시 읽기


def seven_models(root: Path) -> tuple[Example, Card, Priority, Principle, Skill, Task, Candidate]:
    example = Example(
        id="ex-0001",
        skill="minimal",
        kind="good",
        grade="signature",
        text="안녕하세요, 주말 파이썬 교실입니다.\n문의 주셔서 고맙습니다.\n",
        tags={"purpose": "문의"},
        source="past_work",
        status="active",
        approval="human",
    )
    card = Card.model_validate(
        {
            "id": "card-0001",
            "skill": "minimal",
            "decision_point": "opening",
            "status": "active",
            "approval": "human",
            "when": {"purpose": ["문의", "상담"]},
            "choose": "첫 문장에서 문의에 고맙다고 한다",
            "because": "고맙다는 말이 먼저 오면 덜 딱딱하다고 본다",
            "except": "항의 메일은 사과로 시작한다",
            "evidence": ["run-0001"],
            "stats": CardStats(injected=3, agreed=2, last_used=date(2026, 11, 18)),
            "version": 2,
            "supersedes": "card-0000",
            "x_note": "확장 필드",
        }
    )
    priority = Priority(
        id="pri-01", rule="정확함이 친절함보다 먼저다", status="active", approval="human"
    )
    principle = Principle(
        id="prin-01", rule="수치를 부풀리지 않는다", kind="never", status="active", approval="human"
    )
    skill = Skill(
        id="minimal",
        decision_points=[DecisionPoint(id="opening", name="첫 문장", weight=2)],
        context_axes={"purpose": ["문의", "상담", "기타"]},
        skill_md=root / "skills" / "minimal" / "SKILL.md",
    )
    task = Task(
        id="task-0002",
        skill="minimal",
        split="train",
        input="수강료가 얼마인가요?\n다음 기수는 언제 시작하나요?\n",
        context={"purpose": "문의"},
        reference=Reference(kind="my_version", text="수강료는 확인해 알려 드리겠습니다.\n"),
    )
    candidate = Candidate(
        id="cand-0001",
        action="revise",
        layer="tendency",
        target="card-0001",
        item=card.model_copy(update={"version": 3, "status": "candidate"}),
        cause="wrong_card",
        evidence=["run-0002"],
    )
    return example, card, priority, principle, skill, task, candidate


def test_seven_models_round_trip(deeptwin: DeepTwin) -> None:
    example, card, priority, principle, skill, task, candidate = seven_models(deeptwin.root)

    paths = [
        deeptwin.write_example(example),
        deeptwin.write_card(card),
        deeptwin.write_priorities([priority]),
        deeptwin.write_principles([principle]),
        deeptwin.write_task(task),
        deeptwin.write_candidate(candidate),
    ]
    skill_yaml = deeptwin.root / "skills" / "minimal" / "skill.yaml"
    write_model(skill_yaml, skill)

    assert deeptwin.examples() == [example]
    assert deeptwin.cards() == [card]
    assert deeptwin.priorities() == [priority]
    assert deeptwin.principles() == [principle]
    assert deeptwin.skill("minimal") == skill
    assert deeptwin.task("task-0002") == task
    assert deeptwin.candidates() == [candidate]

    rel = [p.relative_to(deeptwin.path).as_posix() for p in paths]
    assert rel == [
        "layers/examples/ex-0001.yaml",
        "layers/cards/card-0001.yaml",
        "layers/priorities.yaml",
        "layers/principles.yaml",
        "tasks/train/task-0002.yaml",
        "candidates/cand-0001.yaml",
    ]
    for path in [*paths, skill_yaml]:
        text = path.read_bytes().decode("utf-8")
        assert text.startswith(("schema: 1\n", "- schema: 1\n")), path
        assert "\\u" not in text
    assert "choose: 첫 문장에서 문의에 고맙다고 한다" in paths[1].read_text("utf-8")
    assert "except: 항의 메일은 사과로 시작한다" in paths[1].read_text("utf-8")
    assert "last_used: 2026-11-18" in paths[1].read_text("utf-8")
    assert "input: |\n  수강료가 얼마인가요?\n" in paths[4].read_text("utf-8")


def test_writing_replaces_the_file(deeptwin: DeepTwin) -> None:
    _, card, *_ = seven_models(deeptwin.root)
    deeptwin.write_card(card)

    deeptwin.write_card(card.model_copy(update={"choose": "바뀐 선택"}))

    [read] = deeptwin.cards()
    assert read.choose == "바뀐 선택"
    names = [p.name for p in (deeptwin.path / "layers" / "cards").iterdir()]
    assert names == ["card-0001.yaml"]


@pytest.mark.parametrize("bad_id", ["../card-0001", "", ".hidden", "a/b", "카드"])
def test_unsafe_ids_are_not_written(deeptwin: DeepTwin, bad_id: str) -> None:
    _, card, priority, *_ = seven_models(deeptwin.root)

    with pytest.raises(ValueError, match="쓸 수 없는 ID"):
        deeptwin.write_card(card.model_copy(update={"id": bad_id}))
    with pytest.raises(ValueError, match="쓸 수 없는 ID"):
        deeptwin.write_priorities([priority, priority.model_copy(update={"id": bad_id})])

    assert list((deeptwin.path / "layers" / "cards").iterdir()) == []
    assert not (deeptwin.path / "layers" / "priorities.yaml").exists()


# 잠금


def test_lock_can_be_taken_again_by_the_same_handle(deeptwin: DeepTwin) -> None:
    _, card, *_ = seven_models(deeptwin.root)

    with deeptwin.lock(), deeptwin.lock():
        deeptwin.write_card(card)
        deeptwin.append_ledger({"id": "run-0001", "type": "run"})

    assert deeptwin.cards() == [card]
    other = FileLock(deeptwin.path / ".lock")
    with other.acquire(timeout=0):
        pass


def test_writes_wait_for_another_lock_then_give_up(deeptwin: DeepTwin) -> None:
    _, card, *_ = seven_models(deeptwin.root)
    deeptwin.lock_timeout = 0.2
    other = FileLock(deeptwin.path / ".lock")

    with other.acquire(timeout=0):
        with pytest.raises(DeeptwinError) as card_info:
            deeptwin.write_card(card)
        with pytest.raises(DeeptwinError) as ledger_info:
            deeptwin.append_ledger({"id": "run-0001", "type": "run"})

    for info in (card_info, ledger_info):
        assert info.value.code == "store_locked"
        assert ".deeptwin/.lock" in info.value.message
        assert "0.2초" in info.value.message
    assert not card_path(deeptwin).exists()
    assert not (deeptwin.path / "ledger.jsonl").exists()
    deeptwin.write_card(card)
    assert deeptwin.cards() == [card]


def test_lock_needs_init(tmp_path: Path) -> None:
    with pytest.raises(DeeptwinError) as info, DeepTwin(tmp_path).lock():
        pass

    assert info.value.code == "not_initialized"
    assert not (tmp_path / ".deeptwin").exists()
