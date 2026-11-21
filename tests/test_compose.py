from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from deeptwin.compose import FLUID_CLOSE, FLUID_OPEN, compose, fill_fluid
from deeptwin.errors import DeeptwinError
from deeptwin.models import Principle, Skill, Task
from deeptwin.store.files import read_yaml, write_text, write_yaml
from deeptwin.store.project import DeepTwin

CONTEXT = {"purpose": "문의"}

GUIDE_ONE_PRINCIPLE = "## 이번 작업의 개인 기준\n\n반드시 지킬 것\n- 수치를 부풀리지 않는다\n"


@pytest.fixture
def deeptwin(tmp_path: Path) -> DeepTwin:
    return DeepTwin.init(tmp_path).deeptwin


def make_skill(skill_id: str = "minimal") -> Skill:
    return Skill(id=skill_id, skill_md=Path("skills") / skill_id / "SKILL.md")


def make_task() -> Task:
    return Task(
        id="task-0001",
        skill="minimal",
        split="train",
        input="수강료가 얼마인가요?",
        context=CONTEXT,
    )


def principle(item_id: str, rule: str, **fields: Any) -> dict[str, Any]:
    return {
        "schema": 1,
        "id": item_id,
        "rule": rule,
        "kind": "never",
        "check": None,
        "scope": [],
        "status": "active",
        "approval": "human",
        **fields,
    }


def write_principles(deeptwin: DeepTwin, items: list[dict[str, Any]]) -> None:
    write_yaml(deeptwin.path / "layers" / "principles.yaml", items)


def test_guide_follows_fixed_template(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.guide == GUIDE_ONE_PRINCIPLE
    assert composed.injected == ["prin-01"]
    assert composed.rejected == []
    assert composed.no_hit == []
    assert composed.conflicts == []
    expected_hash = hashlib.sha256(GUIDE_ONE_PRINCIPLE.encode("utf-8")).hexdigest()
    assert composed.guide_hash == "sha256:" + expected_hash


def test_leaves_out_inactive_and_other_scope(deeptwin: DeepTwin) -> None:
    write_principles(
        deeptwin,
        [
            principle("prin-01", "수치를 부풀리지 않는다"),
            principle("prin-02", "쉬는 원칙", status="dormant"),
            principle("prin-03", "후보 원칙", status="candidate"),
            principle("prin-04", "다른 스킬의 원칙", scope=["post-writer"]),
            principle("prin-05", "모르는 것은 모른다고 쓴다", kind="must", scope=["minimal"]),
            principle("prin-06", "물러난 원칙", status="retired"),
        ],
    )

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.injected == ["prin-01", "prin-05"]
    assert composed.guide == (
        "## 이번 작업의 개인 기준\n\n반드시 지킬 것\n"
        "- 수치를 부풀리지 않는다\n- 모르는 것은 모른다고 쓴다\n"
    )


def test_no_principles_gives_empty_guide(deeptwin: DeepTwin) -> None:
    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert composed.guide == ""
    assert composed.injected == []


def test_ablate_principle_leaves_principles_out(deeptwin: DeepTwin) -> None:
    write_principles(deeptwin, [principle("prin-01", "수치를 부풀리지 않는다")])

    composed = compose(make_skill(), make_task(), deeptwin, context=CONTEXT, ablate=("principle",))

    assert composed.guide == ""
    assert composed.injected == []


@pytest.mark.acceptance
def test_same_input_gives_same_guide_and_hash(deeptwin: DeepTwin) -> None:
    """설계서 8.11 수용 테스트 1: 같은 입력으로 두 번 조립하면 `guide_hash`가 같다."""
    write_principles(
        deeptwin,
        [principle("prin-01", "수치를 부풀리지 않는다"), principle("prin-02", "약속하지 않는다")],
    )

    first = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)
    second = compose(make_skill(), make_task(), deeptwin, context=CONTEXT)

    assert first.guide == second.guide
    assert first.guide_hash == second.guide_hash
    assert first == second


SKILL_MD = f"# 문의 답변\n\n절차를 따른다.\n\n{FLUID_OPEN}\n{FLUID_CLOSE}\n\n맺음말.\n"


def test_fill_fluid_puts_guide_between_markers() -> None:
    filled = fill_fluid(SKILL_MD, GUIDE_ONE_PRINCIPLE)

    assert filled == (
        f"# 문의 답변\n\n절차를 따른다.\n\n{FLUID_OPEN}\n"
        f"{GUIDE_ONE_PRINCIPLE}{FLUID_CLOSE}\n\n맺음말.\n"
    )


def test_fill_fluid_replaces_what_was_there() -> None:
    once = fill_fluid(SKILL_MD, GUIDE_ONE_PRINCIPLE)

    assert fill_fluid(once, GUIDE_ONE_PRINCIPLE) == once
    assert fill_fluid(once, "") == SKILL_MD


@pytest.mark.parametrize(
    "skill_md",
    [
        "# 표시가 없다\n",
        f"# 여는 표시만 있다\n{FLUID_OPEN}\n",
        f"# 닫는 표시만 있다\n{FLUID_CLOSE}\n",
        f"# 순서가 거꾸로다\n{FLUID_CLOSE}\n{FLUID_OPEN}\n",
        f"# 두 번 있다\n{FLUID_OPEN}\n{FLUID_CLOSE}\n{FLUID_OPEN}\n{FLUID_CLOSE}\n",
    ],
)
def test_fill_fluid_needs_one_marker_pair(skill_md: str) -> None:
    with pytest.raises(DeeptwinError) as info:
        fill_fluid(skill_md, GUIDE_ONE_PRINCIPLE)

    assert info.value.code == "fluid_marker_missing"


def test_yaml_keeps_korean_and_key_order(tmp_path: Path) -> None:
    path = tmp_path / "principles.yaml"
    items = [principle("prin-01", "수치를 부풀리지 않는다")]

    write_yaml(path, items)

    text = path.read_text(encoding="utf-8")
    assert "rule: 수치를 부풀리지 않는다" in text
    assert text.index("schema:") < text.index("id:") < text.index("rule:")
    assert read_yaml(path) == items
    assert [p.name for p in tmp_path.iterdir()] == ["principles.yaml"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX 권한 비트")
def test_write_keeps_existing_mode_and_new_files_follow_umask(tmp_path: Path) -> None:
    existing = tmp_path / "existing.txt"
    existing.write_text("전", encoding="utf-8")
    existing.chmod(0o640)
    umask = os.umask(0o022)
    try:
        write_text(existing, "후")
        write_text(tmp_path / "new.txt", "새 파일")
    finally:
        os.umask(umask)

    assert stat.S_IMODE(existing.stat().st_mode) == 0o640
    assert existing.read_text(encoding="utf-8") == "후"
    assert stat.S_IMODE((tmp_path / "new.txt").stat().st_mode) == 0o644
    assert sorted(p.name for p in tmp_path.iterdir()) == ["existing.txt", "new.txt"]


def test_principle_reads_schema_alias() -> None:
    item = Principle.model_validate(principle("prin-01", "수치를 부풀리지 않는다", x_note="확장"))

    assert item.schema_ == 1
    assert item.model_dump(by_alias=True)["schema"] == 1
    assert item.model_dump()["x_note"] == "확장"
