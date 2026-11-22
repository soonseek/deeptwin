from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from deeptwin.errors import DeeptwinError
from deeptwin.store.guard import SealedToken
from deeptwin.store.project import LAYOUT, DeepTwin

FOLDERS = (
    "layers/examples",
    "layers/cards",
    "candidates",
    "tasks/train",
    "tasks/sealed",
    "tasks/spare",
    "runs",
)


def snapshot(root: Path) -> dict[str, bytes | None]:
    """폴더 아래 모든 경로와 파일 바이트. 폴더는 `None`이다."""
    return {
        p.relative_to(root).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(root.rglob("*"))
    }


def test_creates_the_folders_of_the_design(tmp_path: Path) -> None:
    done = DeepTwin.init(tmp_path)

    assert LAYOUT == FOLDERS
    assert done.created == FOLDERS
    for rel in FOLDERS:
        assert (tmp_path / ".deeptwin" / rel).is_dir()
    assert done.deeptwin.path == tmp_path / ".deeptwin"


def test_creates_no_files_inside_the_data_folder(tmp_path: Path) -> None:
    DeepTwin.init(tmp_path)

    assert [p for p in (tmp_path / ".deeptwin").rglob("*") if p.is_file()] == []


def test_creates_gitignore_when_absent(tmp_path: Path) -> None:
    done = DeepTwin.init(tmp_path)

    assert done.gitignore == "added"
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".deeptwin/\n"


def test_appends_to_gitignore_and_keeps_other_lines(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes("# 기존 줄\nnode_modules/\n*.log".encode())

    DeepTwin.init(tmp_path)
    again = DeepTwin.init(tmp_path)

    assert again.gitignore == "present"
    assert gitignore.read_text(encoding="utf-8") == "# 기존 줄\nnode_modules/\n*.log\n.deeptwin/\n"


def test_keeps_crlf_gitignore_style(tmp_path: Path) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(b"dist/\r\n")

    DeepTwin.init(tmp_path)

    assert gitignore.read_bytes() == b"dist/\r\n.deeptwin/\r\n"


@pytest.mark.parametrize("line", [".deeptwin/", ".deeptwin", "/.deeptwin/", "/.deeptwin"])
def test_leaves_gitignore_alone_when_already_ignored(tmp_path: Path, line: str) -> None:
    gitignore = tmp_path / ".gitignore"
    gitignore.write_bytes(f"dist/\n{line}\n".encode())

    done = DeepTwin.init(tmp_path)

    assert done.gitignore == "present"
    assert gitignore.read_bytes() == f"dist/\n{line}\n".encode()


def test_keeps_existing_files(tmp_path: Path) -> None:
    principles = tmp_path / ".deeptwin" / "layers" / "principles.yaml"
    principles.parent.mkdir(parents=True)
    principles.write_bytes("- id: prin-01\n  rule: 수치를 부풀리지 않는다\n".encode())
    before = principles.read_bytes()

    done = DeepTwin.init(tmp_path)

    assert principles.read_bytes() == before
    assert "layers/examples" in done.created


def test_repeating_init_changes_nothing(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("dist/\n", encoding="utf-8")
    DeepTwin.init(tmp_path)
    first = snapshot(tmp_path)

    again = DeepTwin.init(tmp_path)

    assert again.created == ()
    assert again.gitignore == "present"
    assert snapshot(tmp_path) == first


@pytest.mark.parametrize(
    ("blocked", "shown"),
    [
        (".deeptwin", ".deeptwin"),
        (".deeptwin/layers", ".deeptwin/layers"),
        (".deeptwin/runs", ".deeptwin/runs"),
    ],
)
def test_a_file_where_a_folder_goes_blocks_init(tmp_path: Path, blocked: str, shown: str) -> None:
    # 예제의 JSON 출력 테스트가 드러냈다: 전에는 트레이스백으로 끝나 --json에 JSON이 없었다
    path = tmp_path / blocked
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("폴더가 아닌 파일\n", encoding="utf-8")
    before = snapshot(tmp_path)

    with pytest.raises(DeeptwinError) as info:
        DeepTwin.init(tmp_path)

    assert info.value.code == "init_blocked"
    assert info.value.message.splitlines() == [
        f"폴더를 만들 자리에 폴더가 아닌 것이 있습니다: {shown}",
        "그것을 옮기거나 지운 뒤 다시 실행하세요. 아무것도 만들거나 바꾸지 않았습니다.",
    ]
    assert snapshot(tmp_path) == before


def test_a_broken_symlink_where_the_data_folder_goes_blocks_init(tmp_path: Path) -> None:
    link = tmp_path / ".deeptwin"
    try:
        link.symlink_to(tmp_path / "없는 폴더", target_is_directory=True)
    except OSError:  # Windows에서는 심볼릭 링크를 만드는 데 권한이 필요할 수 있다
        pytest.skip("심볼릭 링크를 만들 수 없다")

    with pytest.raises(DeeptwinError) as info:
        DeepTwin.init(tmp_path)

    assert info.value.code == "init_blocked"
    assert info.value.message.splitlines()[0] == (
        "폴더를 만들 자리에 폴더가 아닌 것이 있습니다: .deeptwin"
    )
    assert link.is_symlink()
    assert not (tmp_path / "없는 폴더").exists()
    assert not (tmp_path / ".gitignore").exists()


def test_a_gitignore_that_is_not_a_file_blocks_init(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").mkdir()

    with pytest.raises(DeeptwinError) as info:
        DeepTwin.init(tmp_path)

    assert info.value.code == "init_blocked"
    assert info.value.message.splitlines()[0] == (
        ".gitignore에 .deeptwin/ 줄을 더해야 하는데 .gitignore가 파일이 아닙니다."
    )
    assert not (tmp_path / ".deeptwin").exists()


def test_open_needs_init(tmp_path: Path) -> None:
    with pytest.raises(DeeptwinError) as info:
        DeepTwin.open(tmp_path)

    assert info.value.code == "not_initialized"
    assert "deeptwin init" in info.value.message
    assert not (tmp_path / ".deeptwin").exists()


def test_open_after_init(tmp_path: Path) -> None:
    DeepTwin.init(tmp_path)

    assert DeepTwin.open(tmp_path).path == tmp_path / ".deeptwin"


def test_new_run_takes_the_next_number(tmp_path: Path) -> None:
    deeptwin = DeepTwin.init(tmp_path).deeptwin
    runs = deeptwin.path / "runs"

    assert deeptwin.new_run() == "run-0001"
    assert deeptwin.new_run() == "run-0002"
    (runs / "run-0007").mkdir()
    (runs / "run-9x").mkdir()
    (runs / "notes.txt").write_text("메모", encoding="utf-8")
    assert deeptwin.new_run() == "run-0008"
    assert (runs / "run-0008").is_dir()


def test_task_looks_in_every_split_but_sealed_needs_a_token(minimal_copy: Path) -> None:
    deeptwin = DeepTwin.init(minimal_copy).deeptwin
    tasks = deeptwin.path / "tasks"
    task_file = tasks / "train" / "task-0001.yaml"

    assert deeptwin.task("task-0001").split == "train"

    (tasks / "spare" / "task-0002.yaml").write_text(
        task_file.read_text(encoding="utf-8")
        .replace("task-0001", "task-0002")
        .replace("train", "spare"),
        encoding="utf-8",
    )
    assert deeptwin.task("task-0002").split == "spare"

    (tasks / "sealed" / "task-0003.yaml").write_text(
        task_file.read_text(encoding="utf-8")
        .replace("task-0001", "task-0003")
        .replace("train", "sealed"),
        encoding="utf-8",
    )
    with pytest.raises(DeeptwinError) as info:
        deeptwin.task("task-0003")
    assert info.value.code == "sealed_access"
    assert info.value.message == (
        "과제 task-0003은 봉인 과제라 읽을 수 없습니다. 봉인 과제는 평가에서만 씁니다."
    )
    assert deeptwin.task("task-0003", token=SealedToken()).split == "sealed"

    with pytest.raises(DeeptwinError) as missing:
        deeptwin.task("task-0004")
    assert missing.value.code == "task_not_found"
    for split in ("train", "sealed", "spare"):
        assert f".deeptwin/tasks/{split}/task-0004.yaml" in missing.value.message


@pytest.mark.parametrize("bad_id", ["../train/task-0001", "", ".", "a/b"])
def test_ids_with_paths_are_not_found(minimal_copy: Path, bad_id: str) -> None:
    deeptwin = DeepTwin.init(minimal_copy).deeptwin

    with pytest.raises(DeeptwinError) as task_info:
        deeptwin.task(bad_id)
    with pytest.raises(DeeptwinError) as skill_info:
        deeptwin.skill(bad_id)

    assert task_info.value.code == "task_not_found"
    assert skill_info.value.code == "skill_not_found"


def test_task_file_id_must_match_requested_id(minimal_copy: Path) -> None:
    deeptwin = DeepTwin.init(minimal_copy).deeptwin
    train = deeptwin.path / "tasks" / "train"
    (train / "task-0002.yaml").write_bytes((train / "task-0001.yaml").read_bytes())

    with pytest.raises(DeeptwinError) as info:
        deeptwin.task("task-0002")

    assert info.value.code == "task_not_found"
    assert ".deeptwin/tasks/train/task-0002.yaml" in info.value.message
    assert "task-0001" in info.value.message


def test_skill_file_id_must_match_folder_name(minimal_copy: Path) -> None:
    deeptwin = DeepTwin.init(minimal_copy).deeptwin
    skills = minimal_copy / "skills"
    shutil.copytree(skills / "minimal", skills / "other")

    with pytest.raises(DeeptwinError) as info:
        deeptwin.skill("other")

    assert info.value.code == "skill_not_found"
    assert "skills/other/skill.yaml" in info.value.message
    assert "minimal" in info.value.message


def test_skill_reads_skill_yaml_and_finds_skill_md(minimal_copy: Path) -> None:
    deeptwin = DeepTwin.init(minimal_copy).deeptwin

    skill = deeptwin.skill("minimal")

    assert skill.id == "minimal"
    assert skill.skill_md == minimal_copy / "skills" / "minimal" / "SKILL.md"
    assert [p.id for p in skill.decision_points] == ["opening", "tone"]
    assert "skill_md" not in skill.model_dump()
