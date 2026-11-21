"""원장의 해시 체인: 해시 계산, 덧붙이기, 검사. 데이터는 모두 가상이다."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from filelock import FileLock

from deeptwin.errors import DeeptwinError
from deeptwin.store.ledger import GENESIS, Damage, LedgerCheck, line_hash
from deeptwin.store.project import DeepTwin

ZEROS = "sha256:" + "0" * 64

KOREAN_ENTRY = {
    "type": "run",
    "note": "수치를 부풀리지 않는다",
    "id": "run-0001",
    "injected": ["prin-01"],
}
KOREAN_CANONICAL = (
    '{"id":"run-0001","injected":["prin-01"],"note":"수치를 부풀리지 않는다","type":"run"}'
)
"""`KOREAN_ENTRY`를 정렬된 JSON으로 손으로 쓴 것. 키는 이름순, 공백 없음, 한글 그대로."""

KOREAN_HASH = "sha256:f494432977194e9c96350410cb1be6aa5427b804401fbfd157c4780cff11a15d"
"""`ZEROS + KOREAN_CANONICAL`의 UTF-8 바이트를 `shasum -a 256`으로 계산한 값."""


@pytest.fixture
def deeptwin(tmp_path: Path) -> DeepTwin:
    return DeepTwin.init(tmp_path).deeptwin


def ledger_path(deeptwin: DeepTwin) -> Path:
    return deeptwin.path / "ledger.jsonl"


def lines_of(deeptwin: DeepTwin) -> list[dict[str, Any]]:
    text = ledger_path(deeptwin).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines()]


def append_three(deeptwin: DeepTwin) -> None:
    for number in (1, 2, 3):
        deeptwin.append_ledger({"id": f"run-000{number}", "type": "run", "note": "가상"})


# 해시 계산


def test_hash_matches_one_computed_by_hand() -> None:
    assert GENESIS == ZEROS
    expected = "sha256:" + hashlib.sha256((ZEROS + KOREAN_CANONICAL).encode("utf-8")).hexdigest()

    assert expected == KOREAN_HASH
    assert line_hash(GENESIS, KOREAN_ENTRY) == KOREAN_HASH


def test_first_line_starts_from_zeros_and_the_fields_go_last(deeptwin: DeepTwin) -> None:
    written = deeptwin.append_ledger(KOREAN_ENTRY)

    [line] = lines_of(deeptwin)
    assert line == written
    assert list(line) == ["type", "note", "id", "injected", "prev_hash", "hash"]
    assert line["prev_hash"] == ZEROS
    assert line["hash"] == KOREAN_HASH
    assert "수치를 부풀리지 않는다" in ledger_path(deeptwin).read_text(encoding="utf-8")


def test_next_line_takes_the_hash_of_the_line_before(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)

    first, second, third = lines_of(deeptwin)
    assert second["prev_hash"] == first["hash"]
    assert third["prev_hash"] == second["hash"]
    assert deeptwin.verify_ledger() == LedgerCheck(lines=3, head=third["hash"], damages=())


def test_same_entry_twice_gets_another_hash(deeptwin: DeepTwin) -> None:
    deeptwin.append_ledger(KOREAN_ENTRY)
    deeptwin.append_ledger(KOREAN_ENTRY)

    first, second = lines_of(deeptwin)
    assert second["prev_hash"] == first["hash"] != ZEROS
    assert second["hash"] != first["hash"]


def test_entry_is_hashed_as_it_reads_back(deeptwin: DeepTwin) -> None:
    deeptwin.append_ledger({"id": "run-0001", "injected": ("prin-01", "pri-01")})

    assert deeptwin.verify_ledger().damages == ()


@pytest.mark.parametrize("field", ["prev_hash", "hash"])
def test_chain_fields_are_not_taken_from_the_caller(deeptwin: DeepTwin, field: str) -> None:
    with pytest.raises(ValueError, match=field):
        deeptwin.append_ledger({"id": "run-0001", field: ZEROS})

    assert not ledger_path(deeptwin).exists()


# 줄 나누기


def test_final_newline_is_not_a_line(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)

    assert ledger_path(deeptwin).read_bytes().endswith(b"}\n")
    assert deeptwin.verify_ledger().lines == 3


def test_empty_line_is_a_damaged_line(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)
    path = ledger_path(deeptwin)
    first, rest = path.read_bytes().split(b"\n", 1)
    path.write_bytes(first + b"\n\n" + rest + b"\n")

    check = deeptwin.verify_ledger()

    assert check.lines == 5
    assert check.damages == (Damage(2, "빈 줄입니다"), Damage(5, "빈 줄입니다"))


def test_ledger_without_final_newline_still_appends_on_its_own_line(deeptwin: DeepTwin) -> None:
    deeptwin.append_ledger({"id": "run-0001"})
    path = ledger_path(deeptwin)
    path.write_bytes(path.read_bytes().rstrip(b"\n"))
    assert deeptwin.verify_ledger().damages == ()

    deeptwin.append_ledger({"id": "run-0002"})

    assert [line["id"] for line in lines_of(deeptwin)] == ["run-0001", "run-0002"]
    assert deeptwin.verify_ledger().damages == ()


# 검사


def test_missing_ledger_is_empty(deeptwin: DeepTwin) -> None:
    assert deeptwin.verify_ledger() == LedgerCheck(lines=0, head=None, damages=())


def test_empty_ledger_file_is_empty(deeptwin: DeepTwin) -> None:
    ledger_path(deeptwin).write_bytes(b"")

    assert deeptwin.verify_ledger() == LedgerCheck(lines=0, head=None, damages=())
    deeptwin.append_ledger({"id": "run-0001"})
    assert lines_of(deeptwin)[0]["prev_hash"] == ZEROS


def test_deleting_the_first_line_breaks_the_new_first_line(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)
    path = ledger_path(deeptwin)
    path.write_bytes(path.read_bytes().split(b"\n", 1)[1])

    assert deeptwin.verify_ledger().damages == (Damage(1, "prev_hash가 첫 줄의 시작값이 아닙니다"),)


def test_changing_prev_hash_breaks_only_that_line(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)
    first, second, third = lines_of(deeptwin)
    second["prev_hash"] = ZEROS
    rewrite(deeptwin, [first, second, third])

    assert deeptwin.verify_ledger().damages == (
        Damage(2, "hash가 내용과 맞지 않습니다"),
        Damage(2, "앞줄의 hash와 이어지지 않습니다"),
    )


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"[1, 2]", "JSON 객체가 아닙니다"),
        (b'"run-0002"', "JSON 객체가 아닙니다"),
        (b'{"id": "\xff"}', "UTF-8 글로 읽을 수 없습니다"),
        (b'{"id": "run-0002"', "JSON으로 읽을 수 없는 줄입니다"),
        (b"   ", "빈 줄입니다"),
    ],
)
def test_unreadable_line_breaks_only_that_line(deeptwin: DeepTwin, raw: bytes, reason: str) -> None:
    append_three(deeptwin)
    path = ledger_path(deeptwin)
    first, _, third = path.read_bytes().splitlines()
    path.write_bytes(b"\n".join([first, raw, third]) + b"\n")

    check = deeptwin.verify_ledger()

    assert check.lines == 3
    assert check.damages == (Damage(2, reason),)


def test_wrong_type_of_chain_field(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)
    first, second, third = lines_of(deeptwin)
    second["hash"] = 7
    rewrite(deeptwin, [first, second, third])

    assert deeptwin.verify_ledger().damages == (Damage(2, "hash가 글이 아닙니다"),)


def test_head_is_none_when_the_last_line_has_no_hash(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)
    first, second, third = lines_of(deeptwin)
    del third["hash"]
    rewrite(deeptwin, [first, second, third])

    check = deeptwin.verify_ledger()

    assert check.head is None
    assert check.damages == (Damage(3, "hash가 없습니다"),)


def test_last_line_without_hash_is_not_appended_to(deeptwin: DeepTwin) -> None:
    append_three(deeptwin)
    first, second, third = lines_of(deeptwin)
    del third["hash"]
    rewrite(deeptwin, [first, second, third])
    before = ledger_path(deeptwin).read_bytes()

    with pytest.raises(DeeptwinError) as info:
        deeptwin.append_ledger({"id": "run-0004"})

    assert info.value.code == "ledger_broken"
    assert info.value.message.splitlines() == [
        ".deeptwin/ledger.jsonl:3: hash가 없습니다",
        "원장의 마지막 줄에서 앞줄로 이을 hash를 얻지 못해 줄을 덧붙이지 않았습니다. "
        "deeptwin verify로 원장을 확인하세요.",
    ]
    assert ledger_path(deeptwin).read_bytes() == before


# 잠금


def test_verify_waits_for_another_lock_then_gives_up(deeptwin: DeepTwin) -> None:
    deeptwin.lock_timeout = 0.2

    with FileLock(deeptwin.path / ".lock").acquire(timeout=0), pytest.raises(DeeptwinError) as info:
        deeptwin.verify_ledger()

    assert info.value.code == "store_locked"


def test_verify_needs_init(tmp_path: Path) -> None:
    with pytest.raises(DeeptwinError) as info:
        DeepTwin(tmp_path).verify_ledger()

    assert info.value.code == "not_initialized"
    assert not (tmp_path / ".deeptwin").exists()


def rewrite(deeptwin: DeepTwin, lines: list[dict[str, Any]]) -> None:
    text = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
    ledger_path(deeptwin).write_bytes(text.encode("utf-8"))
