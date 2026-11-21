"""과제 등록, 분할, 봉인 보호, 봉인 기준 검사. 과제와 기준은 모두 가상 인물의 것이다."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml
from filelock import FileLock
from typer.testing import CliRunner, Result

from deeptwin.cli import main
from deeptwin.errors import DeeptwinError
from deeptwin.llm import FakeProvider
from deeptwin.models import Reference, Task
from deeptwin.store.guard import SealedToken, reference_hash
from deeptwin.store.ledger import GENESIS, line_hash
from deeptwin.store.project import DeepTwin

REFERENCE_TEXT = "수강료는 한 달에 십만 원입니다."
SEALED_INPUT = "수강료를 알려 주세요."
SECRETS = (REFERENCE_TEXT, SEALED_INPUT, "십만")
"""봉인 과제의 내용. 어느 출력과 오류 메시지에도 나오면 안 된다."""

SEALED_YAML = f"""\
# 가상의 문의와 내 버전. 테스트용으로 지어낸 것이다.
schema: 1
id: task-0101
skill: minimal
split: sealed
input: {SEALED_INPUT}
context:
  purpose: 문의
reference:
  kind: my_version
  text: {REFERENCE_TEXT}
"""

TRAIN_YAML = """\
# 가상의 상담 메일. 테스트용으로 지어낸 것이다.
schema: 1
id: task-0102
skill: minimal
split: train
input: |
  다음 기수는 언제 시작하나요?
context:
  purpose: 상담
"""

REFERENCE_CANONICAL = (
    '{"grade":"usual","kind":"my_version","picked":null,"rejected":null,'
    '"text":"수강료는 한 달에 십만 원입니다."}'
)
"""`SEALED_YAML`의 기준을 정렬된 JSON으로 손으로 쓴 것. 기본값과 빈 필드도 들어간다."""

REFERENCE_HASH = "sha256:53d5512e92dcd3b57e2ff5ffc5291df9a8978c8090bd13f16a418be65c9467d4"
"""`REFERENCE_CANONICAL`의 UTF-8 바이트를 `shasum -a 256`으로 계산한 값."""

TASK_LEDGER_KEYS = ["id", "type", "ts", "skill", "split", "reference_hash", "prev_hash", "hash"]
ADD_RESULT_KEYS = ["task", "split", "skill", "path", "reference_hash"]

SEALED_ACCESS = "과제 task-0101은 봉인 과제라 읽을 수 없습니다. 봉인 과제는 평가에서만 씁니다."
SEALED_FILE = ".deeptwin/tasks/sealed/task-0101.yaml"

runner = CliRunner()


def invoke(*args: str) -> Result:
    return runner.invoke(main.app, list(args))


def parsed(result: Result) -> dict[str, Any]:
    assert result.stdout.count("\n") == 1, result.stdout
    payload: dict[str, Any] = json.loads(result.stdout)
    return payload


def ok_json(result: Result, command: str) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    payload = parsed(result)
    assert payload["ok"] is True
    assert payload["command"] == command
    body: dict[str, Any] = payload["result"]
    return body


def error_json(result: Result, command: str, code: str) -> str:
    assert result.exit_code == 1, result.output
    payload = parsed(result)
    assert payload["ok"] is False
    assert payload["command"] == command
    assert payload["error"]["code"] == code
    message: str = payload["error"]["message"]
    return message


def keeps_secrets(result: Result) -> None:
    """봉인 과제의 `input`과 기준 글이 stdout과 stderr에 없다."""
    for secret in SECRETS:
        assert secret not in result.stdout, result.stdout
        assert secret not in result.stderr, result.stderr


def add(root: Path, text: str, name: str = "task.yaml", *, as_json: bool = True) -> Result:
    """`text`를 프로젝트 루트의 `name`에 쓰고 `deeptwin task add <name>`을 돌린다."""
    (root / name).write_text(text, encoding="utf-8")
    return invoke("task", "add", name, *(["--json"] if as_json else []))


def add_sealed(root: Path) -> dict[str, Any]:
    result = add(root, SEALED_YAML, "sealed.yaml")
    keeps_secrets(result)
    return ok_json(result, "task add")


def ledger(root: Path) -> list[dict[str, Any]]:
    path = root / ".deeptwin" / "ledger.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def snapshot(root: Path) -> dict[str, bytes | None]:
    """`.deeptwin/` 아래 모든 경로와 파일 바이트. 폴더는 `None`이다. 잠금 파일은 뺀다."""
    data = root / ".deeptwin"
    return {
        p.relative_to(data).as_posix(): (p.read_bytes() if p.is_file() else None)
        for p in sorted(data.rglob("*"))
        if p.name != ".lock"
    }


def sealed_file(root: Path) -> Path:
    return root / ".deeptwin" / "tasks" / "sealed" / "task-0101.yaml"


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, text
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# 등록


def test_add_train_task(in_minimal: Path) -> None:
    result = add(in_minimal, TRAIN_YAML, "train.yaml")

    body = ok_json(result, "task add")
    assert list(body) == ADD_RESULT_KEYS
    assert body == {
        "task": "task-0102",
        "split": "train",
        "skill": "minimal",
        "path": "tasks/train/task-0102.yaml",
        "reference_hash": None,
    }
    expected = Task.model_validate(yaml.safe_load(TRAIN_YAML))
    assert DeepTwin.open(in_minimal).task("task-0102") == expected
    [entry] = ledger(in_minimal)
    assert list(entry) == TASK_LEDGER_KEYS
    assert entry["id"] == "task-0102"
    assert entry["type"] == "task"
    assert datetime.fromisoformat(entry["ts"]).utcoffset() is not None
    assert entry["skill"] == "minimal"
    assert entry["split"] == "train"
    assert entry["reference_hash"] is None
    assert entry["prev_hash"] == GENESIS
    verified = ok_json(invoke("verify", "--json"), "verify")
    assert verified == {"lines": 1, "head": entry["hash"], "sealed": 0}


@pytest.mark.parametrize("split", ["train", "spare"])
def test_only_sealed_tasks_record_the_reference_hash(in_minimal: Path, split: str) -> None:
    text = SEALED_YAML.replace("split: sealed", f"split: {split}")

    body = ok_json(add(in_minimal, text), "task add")

    assert body["split"] == split
    assert body["reference_hash"] is None
    assert ledger(in_minimal)[0]["reference_hash"] is None
    assert (in_minimal / ".deeptwin" / "tasks" / split / "task-0101.yaml").is_file()


def test_add_sealed_task_records_the_reference_hash(in_minimal: Path) -> None:
    body = add_sealed(in_minimal)

    assert list(body) == ADD_RESULT_KEYS
    assert body == {
        "task": "task-0101",
        "split": "sealed",
        "skill": "minimal",
        "path": "tasks/sealed/task-0101.yaml",
        "reference_hash": REFERENCE_HASH,
    }
    [entry] = ledger(in_minimal)
    assert list(entry) == TASK_LEDGER_KEYS
    assert entry["split"] == "sealed"
    assert entry["reference_hash"] == REFERENCE_HASH
    assert sealed_file(in_minimal).is_file()
    token = SealedToken()
    stored = DeepTwin.open(in_minimal).task("task-0101", token=token)
    assert stored == Task.model_validate(yaml.safe_load(SEALED_YAML))


def test_add_sealed_task_in_text_mode_shows_no_reference(in_minimal: Path) -> None:
    result = add(in_minimal, SEALED_YAML, "sealed.yaml", as_json=False)

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "과제 task-0101을 sealed 분할에 등록했습니다.\n"
        f"과제 파일: {SEALED_FILE}\n"
        f"기준 해시: {REFERENCE_HASH}\n"
    )
    assert result.stderr == ""
    keeps_secrets(result)


def test_reference_hash_is_the_sorted_json_of_the_reference() -> None:
    reference = Reference(kind="my_version", text=REFERENCE_TEXT)

    assert reference_hash(reference) == REFERENCE_HASH
    # 기본값을 적어도 같고, 등급을 바꾸면 다르다
    assert reference_hash(Reference(kind="my_version", grade="usual", text=REFERENCE_TEXT)) == (
        REFERENCE_HASH
    )
    assert reference_hash(Reference(kind="my_version", grade="signature", text=REFERENCE_TEXT)) != (
        REFERENCE_HASH
    )


def test_hand_written_canonical_json_gives_the_reference_hash() -> None:
    expected = "sha256:" + hashlib.sha256(REFERENCE_CANONICAL.encode("utf-8")).hexdigest()

    assert expected == REFERENCE_HASH


def test_sealed_task_needs_a_reference(in_minimal: Path) -> None:
    before = snapshot(in_minimal)
    text = SEALED_YAML.split("reference:")[0]

    message = error_json(add(in_minimal, text), "task add", "reference_required")

    assert message == (
        "봉인(sealed) 과제 task-0101에는 기준(reference)이 있어야 합니다. "
        "봉인 과제의 기준은 결과물을 만들기 전에 받아 둡니다."
    )
    assert snapshot(in_minimal) == before
    assert ledger(in_minimal) == []


# 같은 ID는 다시 등록할 수 없다


def test_sealed_task_cannot_be_added_again_as_train(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    before = snapshot(in_minimal)

    result = add(in_minimal, SEALED_YAML.replace("split: sealed", "split: train"), "again.yaml")

    message = error_json(result, "task add", "task_exists")
    assert message == (
        "과제 task-0101은 이미 sealed 분할에 있습니다. 분할은 바꿀 수 없습니다. "
        f"있는 곳: {SEALED_FILE}, .deeptwin/ledger.jsonl:1"
    )
    keeps_secrets(result)
    assert snapshot(in_minimal) == before


def test_same_file_twice_is_refused(in_minimal: Path) -> None:
    ok_json(add(in_minimal, TRAIN_YAML), "task add")
    before = snapshot(in_minimal)

    message = error_json(add(in_minimal, TRAIN_YAML), "task add", "task_exists")

    assert "이미 train 분할에 있습니다" in message
    assert snapshot(in_minimal) == before
    assert len(ledger(in_minimal)) == 1


@pytest.mark.parametrize("split", ["train", "sealed", "spare"])
def test_file_put_by_hand_blocks_the_id(in_minimal: Path, split: str) -> None:
    folder = in_minimal / ".deeptwin" / "tasks" / split
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "task-0101.yaml").write_text(
        SEALED_YAML.replace("split: sealed", f"split: {split}"), encoding="utf-8"
    )
    before = snapshot(in_minimal)

    result = add(in_minimal, SEALED_YAML.replace("split: sealed", "split: train"))

    message = error_json(result, "task add", "task_exists")
    assert message == (
        f"과제 task-0101은 이미 {split} 분할에 있습니다. 분할은 바꿀 수 없습니다. "
        f"있는 곳: .deeptwin/tasks/{split}/task-0101.yaml"
    )
    assert snapshot(in_minimal) == before
    assert ledger(in_minimal) == []


def test_deleted_file_still_blocks_the_id(in_minimal: Path) -> None:
    ok_json(add(in_minimal, TRAIN_YAML), "task add")
    (in_minimal / ".deeptwin" / "tasks" / "train" / "task-0102.yaml").unlink()
    before = snapshot(in_minimal)

    message = error_json(
        add(in_minimal, TRAIN_YAML.replace("split: train", "split: spare")),
        "task add",
        "task_exists",
    )

    assert message == (
        "과제 task-0102은 이미 train 분할에 있습니다. 분할은 바꿀 수 없습니다. "
        "있는 곳: .deeptwin/ledger.jsonl:1"
    )
    assert snapshot(in_minimal) == before


def test_store_refuses_to_move_a_task_to_another_split(in_minimal: Path) -> None:
    deeptwin = DeepTwin.open(in_minimal)
    task = deeptwin.task("task-0001")

    with pytest.raises(DeeptwinError) as info:
        deeptwin.write_task(task.model_copy(update={"split": "sealed"}))

    assert info.value.code == "task_exists"
    assert info.value.message == (
        "과제 task-0001은 이미 train 분할에 있습니다. 분할은 바꿀 수 없습니다. "
        "있는 곳: .deeptwin/tasks/train/task-0001.yaml"
    )
    assert not (in_minimal / ".deeptwin" / "tasks" / "sealed").exists()
    # 같은 분할에 다시 쓰는 것은 된다
    deeptwin.write_task(task.model_copy(update={"input": "바뀐 문의\n"}))
    assert deeptwin.task("task-0001").input == "바뀐 문의\n"


# 틀린 과제 파일


@pytest.mark.parametrize(
    ("old", "new", "code", "message"),
    [
        (
            "split: train",
            "split: test",
            "invalid_file",
            "train.yaml:5: split: 쓸 수 있는 값은 'train', 'sealed', 'spare'입니다",
        ),
        (
            "id: task-0102",
            "id: ../task-0102",
            "invalid_file",
            "train.yaml:3: id: 쓸 수 없는 ID입니다(받은 값: '../task-0102'). "
            "영문자, 숫자, '.', '_', '-'만 쓰고 영문자나 숫자로 시작하세요.",
        ),
        (
            "input: |\n  다음 기수는 언제 시작하나요?\n",
            "",
            "invalid_file",
            "train.yaml:2: input: 꼭 있어야 하는 필드가 없습니다",
        ),
        (
            "skill: minimal",
            "skill: nope",
            "skill_not_found",
            "스킬을 찾지 못했습니다: nope. 찾아본 곳: skills/nope/skill.yaml, skills/nope/SKILL.md",
        ),
        (
            "purpose: 상담",
            "purpose: 항의",
            "invalid_context",
            "맥락 값이 스킬 minimal의 context_axes에 없습니다: purpose=항의. "
            "purpose에 쓸 수 있는 값: 문의, 상담, 기타",
        ),
    ],
    ids=["unknown-split", "path-in-id", "missing-input", "unknown-skill", "unknown-context"],
)
def test_wrong_task_file_writes_nothing(
    in_minimal: Path, old: str, new: str, code: str, message: str
) -> None:
    before = snapshot(in_minimal)
    assert old in TRAIN_YAML

    result = add(in_minimal, TRAIN_YAML.replace(old, new), "train.yaml")

    assert error_json(result, "task add", code) == message
    assert snapshot(in_minimal) == before
    assert ledger(in_minimal) == []


@pytest.mark.parametrize(
    ("old", "new", "secret", "message"),
    [
        (
            f"reference:\n  kind: my_version\n  text: {REFERENCE_TEXT}\n",
            f"reference: {REFERENCE_TEXT}\n",
            REFERENCE_TEXT,
            "task.yaml:9: reference: 매핑(키: 값)이어야 합니다",
        ),
        (
            f"text: {REFERENCE_TEXT}",
            "text: 100000",
            "100000",
            "task.yaml:11: reference.text: 글이어야 합니다",
        ),
        (
            "kind: my_version",
            f"kind: {REFERENCE_TEXT}",
            REFERENCE_TEXT,
            "task.yaml:10: reference.kind: 쓸 수 있는 값은 'my_version', 'edit', 'pick'입니다",
        ),
        (
            f"input: {SEALED_INPUT}",
            f"input: [{SEALED_INPUT}]",
            SEALED_INPUT,
            "task.yaml:6: input: 글이어야 합니다",
        ),
        (
            f"text: {REFERENCE_TEXT}",
            "text: 2026-02-30",
            "2026-02-30",
            "task.yaml:1: YAML 문법이 틀렸습니다: 값으로 읽을 수 없는 날짜나 시각이 있습니다",
        ),
    ],
    ids=["reference-scalar", "text-number", "kind-text", "input-list", "impossible-date"],
)
def test_malformed_sealed_file_shows_no_values(
    in_minimal: Path, old: str, new: str, secret: str, message: str
) -> None:
    """형식이 틀린 과제 파일의 메시지에는 파일, 줄, 필드, 까닭만 있고 받은 값은 없다."""
    assert old in SEALED_YAML
    text = SEALED_YAML.replace(old, new)
    before = snapshot(in_minimal)

    result = add(in_minimal, text)
    plain = add(in_minimal, text, as_json=False)

    assert error_json(result, "task add", "invalid_file") == message
    assert plain.exit_code == 1
    assert plain.stderr == f"오류: {message}\n"
    for checked in (result, plain):
        keeps_secrets(checked)
        assert secret not in checked.stdout
        assert secret not in checked.stderr
    assert snapshot(in_minimal) == before


def test_missing_task_file_is_an_argument_error(in_minimal: Path) -> None:
    result = invoke("task", "add", "없음.yaml", "--json")

    assert result.exit_code == 2
    assert result.stdout == ""


def test_task_add_before_init(minimal_copy: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shutil.rmtree(minimal_copy / ".deeptwin")
    monkeypatch.chdir(minimal_copy)

    message = error_json(add(minimal_copy, TRAIN_YAML), "task add", "not_initialized")

    assert "deeptwin init" in message
    assert not (minimal_copy / ".deeptwin").exists()


def test_broken_ledger_makes_no_task_file(in_minimal: Path) -> None:
    ok_json(add(in_minimal, TRAIN_YAML), "task add")
    path = in_minimal / ".deeptwin" / "ledger.jsonl"
    path.write_bytes(path.read_bytes() + b'{"id": "run-0001"\n')
    before = snapshot(in_minimal)

    message = error_json(add(in_minimal, SEALED_YAML), "task add", "ledger_broken")

    assert message.splitlines()[0] == ".deeptwin/ledger.jsonl:2: JSON으로 읽을 수 없는 줄입니다"
    assert snapshot(in_minimal) == before
    assert not sealed_file(in_minimal).exists()


def test_failed_file_write_leaves_the_ledger_line(
    in_minimal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """원장을 먼저 쓴다. 파일을 쓰다 실패하면 원장 줄만 남고, 그 ID는 다시 등록할 수 없다."""
    deeptwin = DeepTwin.open(in_minimal)
    task = Task.model_validate(yaml.safe_load(SEALED_YAML))

    def fail(_task: Task) -> Path:
        raise OSError("디스크가 찼다")

    monkeypatch.setattr(deeptwin, "write_task", fail)
    with pytest.raises(OSError):
        deeptwin.add_task(task)

    assert [entry["id"] for entry in ledger(in_minimal)] == ["task-0101"]
    assert not sealed_file(in_minimal).exists()
    with pytest.raises(DeeptwinError) as again:
        DeepTwin.open(in_minimal).add_task(task)
    assert again.value.code == "task_exists"
    message = error_json(invoke("verify", "--json"), "verify", "sealed_changed")
    assert message == f"{SEALED_FILE}: 파일이 없습니다"


def test_add_waits_for_another_lock_then_gives_up(in_minimal: Path) -> None:
    deeptwin = DeepTwin.open(in_minimal)
    deeptwin.lock_timeout = 0.2
    task = Task.model_validate(yaml.safe_load(TRAIN_YAML))

    with FileLock(deeptwin.path / ".lock").acquire(timeout=0), pytest.raises(DeeptwinError) as info:
        deeptwin.add_task(task)

    assert info.value.code == "store_locked"
    assert ledger(in_minimal) == []
    assert not (deeptwin.path / "tasks" / "train" / "task-0102.yaml").exists()


# 봉인 과제로 실행


RUN_SEALED = ("run", "minimal", "task-0101", "--provider", "fake", "--fake-answer", "answer.txt")


def test_run_with_a_sealed_task_is_refused(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    before = snapshot(in_minimal)

    result = invoke(*RUN_SEALED, "--json")
    text = invoke(*RUN_SEALED)

    assert error_json(result, "run", "sealed_access") == SEALED_ACCESS
    assert text.exit_code == 1
    assert text.stdout == ""
    assert text.stderr == f"오류: {SEALED_ACCESS}\n"
    keeps_secrets(result)
    keeps_secrets(text)
    assert snapshot(in_minimal) == before
    assert not (in_minimal / ".deeptwin" / "runs").exists()
    assert [entry["type"] for entry in ledger(in_minimal)] == ["task"]


def test_run_with_a_sealed_task_calls_no_model(
    in_minimal: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeProvider(["가짜 답"])
    monkeypatch.setitem(main.PROVIDERS, "fake", lambda options: fake)
    invoke("init")
    add_sealed(in_minimal)

    error_json(
        invoke("run", "minimal", "task-0101", "--provider", "fake", "--json"),
        "run",
        "sealed_access",
    )

    assert fake.calls == []
    assert list((in_minimal / ".deeptwin" / "runs").iterdir()) == []


def test_run_with_a_sealed_task_needs_no_provider_options(in_minimal: Path) -> None:
    """공급자는 과제를 본 뒤에 만든다. 답 파일이 없어도 봉인 과제면 sealed_access다."""
    add_sealed(in_minimal)

    result = invoke("run", "minimal", "task-0101", "--provider", "fake", "--json")

    assert error_json(result, "run", "sealed_access") == SEALED_ACCESS
    assert not (in_minimal / ".deeptwin" / "runs").exists()


@pytest.mark.parametrize(
    "options",
    [
        ("--context", "purpose=상담", "--ablate", "instinct"),
        ("--context", "purpose"),  # 틀린 옵션이어도 봉인을 먼저 본다
    ],
    ids=["good-options", "wrong-option"],
)
def test_run_with_a_sealed_task_is_refused_whatever_the_options(
    in_minimal: Path, options: tuple[str, ...]
) -> None:
    add_sealed(in_minimal)
    before = snapshot(in_minimal)

    result = invoke(*RUN_SEALED, *options, "--json")

    assert error_json(result, "run", "sealed_access") == SEALED_ACCESS
    keeps_secrets(result)
    assert snapshot(in_minimal) == before
    assert not (in_minimal / ".deeptwin" / "runs").exists()


def test_compose_with_a_sealed_task_is_refused(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    before = snapshot(in_minimal)

    result = invoke("compose", "minimal", "task-0101", "--json")
    text = invoke("compose", "minimal", "task-0101", "--context", "purpose=상담")

    assert error_json(result, "compose", "sealed_access") == SEALED_ACCESS
    assert text.exit_code == 1
    assert text.stderr == f"오류: {SEALED_ACCESS}\n"
    keeps_secrets(result)
    keeps_secrets(text)
    assert snapshot(in_minimal) == before


# 저장 계층의 봉인


def test_store_blocks_sealed_tasks_without_a_token(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    deeptwin = DeepTwin.open(in_minimal)

    with pytest.raises(DeeptwinError) as listed:
        deeptwin.tasks("sealed")
    with pytest.raises(DeeptwinError) as found:
        deeptwin.task("task-0101")
    with pytest.raises(DeeptwinError) as fake_token:
        deeptwin.tasks("sealed", token=object())  # type: ignore[arg-type]

    assert listed.value.code == found.value.code == fake_token.value.code == "sealed_access"
    assert listed.value.message == (
        ".deeptwin/tasks/sealed/의 과제는 봉인 과제라 읽을 수 없습니다. "
        "봉인 과제는 평가에서만 씁니다."
    )
    assert found.value.message == SEALED_ACCESS
    for info in (listed, found, fake_token):
        assert all(secret not in info.value.message for secret in SECRETS)

    token = SealedToken()
    [sealed] = deeptwin.tasks("sealed", token=token)
    assert sealed.reference is not None
    assert sealed.reference.text == REFERENCE_TEXT
    assert deeptwin.task("task-0101", token=token) == sealed
    assert [task.id for task in deeptwin.tasks("train")] == ["task-0001"]
    assert deeptwin.tasks("spare") == []


def test_sealed_needs_a_token_even_without_files(in_minimal: Path) -> None:
    deeptwin = DeepTwin.open(in_minimal)
    assert not (deeptwin.path / "tasks" / "sealed").exists()

    with pytest.raises(DeeptwinError) as info:
        deeptwin.tasks("sealed")

    assert info.value.code == "sealed_access"
    assert deeptwin.tasks("sealed", token=SealedToken()) == []


def test_sealed_file_is_not_read_without_a_token(in_minimal: Path) -> None:
    """토큰이 없으면 파일을 읽지 않는다. 형식이 틀려도 그 내용이 메시지에 나오지 않는다."""
    folder = in_minimal / ".deeptwin" / "tasks" / "sealed"
    folder.mkdir()
    (folder / "task-0101.yaml").write_text(
        SEALED_YAML.replace("kind: my_version", f"kind: [{REFERENCE_TEXT}]"), encoding="utf-8"
    )
    deeptwin = DeepTwin.open(in_minimal)

    with pytest.raises(DeeptwinError) as info:
        deeptwin.task("task-0101")
    with pytest.raises(DeeptwinError) as with_token:
        deeptwin.task("task-0101", token=SealedToken())

    assert info.value.code == "sealed_access"
    assert info.value.message == SEALED_ACCESS
    assert with_token.value.code == "invalid_file"


def test_sealed_id_wins_over_a_copy_in_another_split(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    train = in_minimal / ".deeptwin" / "tasks" / "train" / "task-0101.yaml"
    train.write_text(SEALED_YAML.replace("split: sealed", "split: train"), encoding="utf-8")

    with pytest.raises(DeeptwinError) as info:
        DeepTwin.open(in_minimal).task("task-0101")

    assert info.value.code == "sealed_access"


def test_tasks_checks_the_split_of_each_file(in_minimal: Path) -> None:
    deeptwin = DeepTwin.open(in_minimal)
    train = deeptwin.path / "tasks" / "train"
    (train / "task-0102.yaml").write_text(
        TRAIN_YAML.replace("split: train", "split: spare"), encoding="utf-8"
    )

    with pytest.raises(DeeptwinError) as info:
        deeptwin.tasks("train")
    with pytest.raises(ValueError, match="알 수 없는 분할"):
        deeptwin.tasks("test")  # type: ignore[arg-type]

    assert info.value.code == "invalid_file"
    assert info.value.message == (
        ".deeptwin/tasks/train/task-0102.yaml:5: split: 과제가 든 폴더(tasks/train)와 다릅니다"
        "(받은 값: 'spare')"
    )


# verify의 봉인 검사


def test_verify_counts_sealed_tasks(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    ok_json(add(in_minimal, TRAIN_YAML), "task add")

    body = ok_json(invoke("verify", "--json"), "verify")
    text = invoke("verify")

    assert body == {"lines": 2, "head": ledger(in_minimal)[-1]["hash"], "sealed": 1}
    assert text.exit_code == 0, text.output
    assert text.stdout == (
        "원장 .deeptwin/ledger.jsonl의 2줄이 모두 해시로 이어져 있습니다.\n"
        "봉인 과제 1개의 기준이 등록 때와 같습니다.\n"
    )


def test_verify_finds_a_changed_reference_then_passes_after_undo(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    path = sealed_file(in_minimal)
    good = path.read_bytes()
    edit(path, "십만", "구만")

    result = invoke("verify", "--json")
    text = invoke("verify")

    message = error_json(result, "verify", "sealed_changed")
    assert message == f"{SEALED_FILE}: 기준(reference)이 등록 때와 다릅니다"
    assert text.exit_code == 1
    assert text.stdout == ""
    assert text.stderr == f"오류: {message}\n"
    for checked in (result, text):
        keeps_secrets(checked)
        assert "구만" not in checked.output

    path.write_bytes(good)
    assert ok_json(invoke("verify", "--json"), "verify")["sealed"] == 1


@pytest.mark.parametrize(
    ("old", "new", "reason"),
    [
        ("grade: usual", "grade: signature", "기준(reference)이 등록 때와 다릅니다"),
        ("kind: my_version", "kind: edit", "기준(reference)이 등록 때와 다릅니다"),
        ("reference:\n", "reference: [\n", "과제 파일로 읽을 수 없습니다"),
        ("kind: my_version", "kind: pick", "과제 파일로 읽을 수 없습니다"),
        ("id: task-0101", "id: task-0199", "파일의 id가 원장에 등록한 과제 ID와 다릅니다"),
        ("split: sealed", "split: train", "파일의 split이 sealed가 아닙니다"),
    ],
    ids=["grade", "kind", "broken-yaml", "invalid-reference", "other-id", "other-split"],
)
def test_verify_reports_a_sealed_file_without_its_content(
    in_minimal: Path, old: str, new: str, reason: str
) -> None:
    add_sealed(in_minimal)
    edit(sealed_file(in_minimal), old, new)

    result = invoke("verify", "--json")

    assert error_json(result, "verify", "sealed_changed") == f"{SEALED_FILE}: {reason}"
    keeps_secrets(result)


def test_verify_reports_a_sealed_file_with_an_impossible_date(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    edit(sealed_file(in_minimal), REFERENCE_TEXT, "2026-02-30")

    result = invoke("verify", "--json")

    message = error_json(result, "verify", "sealed_changed")
    assert message == f"{SEALED_FILE}: 과제 파일로 읽을 수 없습니다"
    assert "2026-02-30" not in result.output


def test_verify_reports_a_sealed_file_without_reference(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    path = sealed_file(in_minimal)
    path.write_text(path.read_text("utf-8").split("reference:")[0], encoding="utf-8")

    message = error_json(invoke("verify", "--json"), "verify", "sealed_changed")

    assert message == f"{SEALED_FILE}: 기준(reference)이 없습니다"


def test_verify_reports_deleted_and_unregistered_sealed_files(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    ok_json(add(in_minimal, SEALED_YAML.replace("task-0101", "task-0103")), "task add")
    folder = in_minimal / ".deeptwin" / "tasks" / "sealed"
    (folder / "task-0101.yaml").unlink()
    (folder / "task-0105.yaml").write_text(
        SEALED_YAML.replace("task-0101", "task-0105"), encoding="utf-8"
    )
    (folder / "notes.txt").write_text("yaml이 아닌 파일은 보지 않는다", encoding="utf-8")

    result = invoke("verify", "--json")

    assert error_json(result, "verify", "sealed_changed").splitlines() == [
        f"{SEALED_FILE}: 파일이 없습니다",
        ".deeptwin/tasks/sealed/task-0105.yaml: 원장에 봉인 과제로 등록한 task 줄이 없습니다",
    ]
    keeps_secrets(result)


def test_verify_reports_a_sealed_file_written_without_registering(in_minimal: Path) -> None:
    task = Task.model_validate(yaml.safe_load(SEALED_YAML))
    DeepTwin.open(in_minimal).write_task(task)

    message = error_json(invoke("verify", "--json"), "verify", "sealed_changed")

    assert message == f"{SEALED_FILE}: 원장에 봉인 과제로 등록한 task 줄이 없습니다"


def rehash(entry: dict[str, Any]) -> dict[str, Any]:
    """`entry`의 `hash`를 내용에 맞게 다시 계산한다. 체인은 멀쩡하게 고친 원장 줄을 만든다."""
    body = {k: v for k, v in entry.items() if k not in ("prev_hash", "hash")}
    return {**body, "prev_hash": entry["prev_hash"], "hash": line_hash(entry["prev_hash"], body)}


@pytest.mark.parametrize(
    ("field", "value", "lines"),
    [
        (
            "reference_hash",
            None,
            [f"{SEALED_FILE}: 원장의 task 줄에 기준 해시(reference_hash)가 없습니다"],
        ),
        (
            "id",
            "../task-0101",
            [
                ".deeptwin/ledger.jsonl:1: "
                "봉인 과제로 등록한 task 줄의 id를 과제 ID로 읽을 수 없습니다",
                f"{SEALED_FILE}: 원장에 봉인 과제로 등록한 task 줄이 없습니다",
            ],
        ),
        ("split", "train", [f"{SEALED_FILE}: 원장에 봉인 과제로 등록한 task 줄이 없습니다"]),
    ],
    ids=["no-hash", "bad-id", "other-split"],
)
def test_verify_reads_the_sealed_task_line(
    in_minimal: Path, field: str, value: Any, lines: list[str]
) -> None:
    add_sealed(in_minimal)
    [entry] = ledger(in_minimal)
    entry[field] = value
    path = in_minimal / ".deeptwin" / "ledger.jsonl"
    path.write_text(json.dumps(rehash(entry), ensure_ascii=False) + "\n", encoding="utf-8")

    message = error_json(invoke("verify", "--json"), "verify", "sealed_changed")

    assert message.splitlines() == lines


def test_verify_puts_sealed_lines_after_chain_lines(in_minimal: Path) -> None:
    add_sealed(in_minimal)
    ok_json(add(in_minimal, TRAIN_YAML), "task add")
    path = in_minimal / ".deeptwin" / "ledger.jsonl"
    first, second = path.read_bytes().splitlines()
    second = second.replace(b'"skill": "minimal"', b'"skill": "other"')
    path.write_bytes(first + b"\n" + second + b"\n")
    edit(sealed_file(in_minimal), "십만", "구만")

    result = invoke("verify", "--json")

    assert error_json(result, "verify", "ledger_broken").splitlines() == [
        ".deeptwin/ledger.jsonl:2: hash가 내용과 맞지 않습니다",
        f"{SEALED_FILE}: 기준(reference)이 등록 때와 다릅니다",
    ]
    keeps_secrets(result)
    assert "구만" not in result.output


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (f"input: {SEALED_INPUT}", "input: 수강료와 시작일을 알려 주세요."),
        ("schema: 1\n", "# 손으로 단 주석\nschema: 1\n"),
        ("purpose: 문의", "purpose: 상담"),
        ("  grade: usual\n", ""),
        ("  picked: null\n  rejected: null\n", ""),
    ],
    ids=["input", "comment", "context", "default-grade", "empty-fields"],
)
def test_verify_ignores_edits_outside_the_reference(in_minimal: Path, old: str, new: str) -> None:
    add_sealed(in_minimal)
    edit(sealed_file(in_minimal), old, new)

    assert ok_json(invoke("verify", "--json"), "verify")["sealed"] == 1
