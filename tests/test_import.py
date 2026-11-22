"""과거 작업물 가져오기: 파일 고르기, 글 읽기, 번호, 건너뛰기, 전부 아니면 전무.

글은 모두 가상 인물의 것이다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptwin.compose import GOOD_EXAMPLES_HEADING, compose
from deeptwin.errors import DeeptwinError
from deeptwin.importing import import_folder, read_past_work
from deeptwin.models import Example, Task
from deeptwin.store.project import DeepTwin

PAST_NOTICES = [
    "4기 수강생 여러분, 마지막 수업은 11월 22일 토요일 오전 10시입니다.",
    "이번 주 토요일 수업은 강사 사정으로 쉽니다.\n보강은 다음 주 화요일 저녁 7시입니다.",
    "5기 모집을 시작합니다. 첫 수업은 12월 6일입니다.",
    "수료 과제는 수업 전날 밤 12시까지 올려 주세요.",
    "다음 주 수업은 온라인으로 엽니다. 링크는 하루 전에 보냅니다.",
]
"""가상 강의 "주말 파이썬 교실"의 지난 공지. 테스트용으로 지어낸 것이다."""


@pytest.fixture
def deeptwin(tmp_path: Path) -> DeepTwin:
    """`init`을 마치고 스킬 `notice`의 뼈대를 만든 프로젝트."""
    deeptwin = DeepTwin.init(tmp_path / "project").deeptwin
    deeptwin.new_skill("notice")
    return deeptwin


@pytest.fixture
def past(deeptwin: DeepTwin) -> Path:
    """프로젝트 안의 `past/` 폴더. 지난 공지 다섯 편이 `p1.txt`~`p5.txt`로 들어 있다."""
    folder = deeptwin.root / "past"
    folder.mkdir()
    for number, text in enumerate(PAST_NOTICES, start=1):
        (folder / f"p{number}.txt").write_text(text + "\n", encoding="utf-8")
    return folder


def example_files(deeptwin: DeepTwin) -> list[str]:
    folder = deeptwin.path / "layers" / "examples"
    return sorted(p.name for p in folder.iterdir())


def tree_bytes(folder: Path) -> dict[str, bytes]:
    return {
        p.relative_to(folder).as_posix(): p.read_bytes() for p in folder.rglob("*") if p.is_file()
    }


def an_example(example_id: str, text: str, *, skill: str = "notice") -> Example:
    return Example(
        id=example_id,
        skill=skill,
        kind="good",
        grade="usual",
        text=text,
        status="active",
        approval="human",
    )


# 가져오기


def test_signature_import_makes_one_example_per_file(deeptwin: DeepTwin, past: Path) -> None:
    done = import_folder(deeptwin, past, skill="notice", signature=True)

    assert [(i.example.id, i.file) for i in done.imported] == [
        (f"ex-000{n}", past / f"p{n}.txt") for n in range(1, 6)
    ]
    assert done.skipped == ()
    assert example_files(deeptwin) == [f"ex-000{n}.yaml" for n in range(1, 6)]
    assert deeptwin.examples() == [
        Example(
            id=f"ex-000{n}",
            skill="notice",
            kind="good",
            grade="signature",
            text=text,
            tags={},
            source="past_work",
            status="active",
            approval="human",
        )
        for n, text in enumerate(PAST_NOTICES, start=1)
    ]
    assert [i.example for i in done.imported] == deeptwin.examples()


def test_without_signature_the_grade_is_usual(deeptwin: DeepTwin, past: Path) -> None:
    import_folder(deeptwin, past, skill="notice")

    assert {e.grade for e in deeptwin.examples()} == {"usual"}


def test_importing_again_adds_nothing(deeptwin: DeepTwin, past: Path) -> None:
    import_folder(deeptwin, past, skill="notice", signature=True)
    before = tree_bytes(deeptwin.path / "layers")

    again = import_folder(deeptwin, past, skill="notice", signature=True)

    assert again.imported == ()
    assert [(s.file, s.same_as) for s in again.skipped] == [
        (past / f"p{n}.txt", f"ex-000{n}") for n in range(1, 6)
    ]
    assert tree_bytes(deeptwin.path / "layers") == before


def test_numbers_continue_after_the_largest_ex_number(deeptwin: DeepTwin, past: Path) -> None:
    deeptwin.write_example(an_example("ex-0003", "직접 적어 둔 예시"))
    deeptwin.write_example(an_example("my-note", "번호가 없는 ID의 예시"))

    done = import_folder(deeptwin, past, skill="notice")

    assert [i.example.id for i in done.imported] == [f"ex-000{n}" for n in range(4, 9)]


def test_a_number_taken_by_a_path_the_reader_skips_is_not_reused(
    deeptwin: DeepTwin, past: Path
) -> None:
    # 읽기는 `.yaml` 파일만 본다. 이 이름의 폴더는 읽기에서 빠지지만 그 번호를 쓰지 않는다
    # (대소문자를 가리지 않는 파일 시스템의 `ex-0001.YAML`도 같다)
    taken = deeptwin.path / "layers" / "examples" / "ex-0001.yaml"
    taken.mkdir()
    (taken / "keep.txt").write_bytes(b"kept")

    done = import_folder(deeptwin, past, skill="notice")

    assert [i.example.id for i in done.imported] == [f"ex-000{n}" for n in range(2, 7)]
    assert (taken / "keep.txt").read_bytes() == b"kept"


def test_same_text_twice_in_one_import_is_skipped(deeptwin: DeepTwin, tmp_path: Path) -> None:
    folder = tmp_path / "twice"
    folder.mkdir()
    (folder / "a.txt").write_bytes("같은 공지입니다.\r\n둘째 줄\r\n".encode())
    (folder / "b.md").write_bytes("\n  같은 공지입니다.\n둘째 줄  \n".encode())

    done = import_folder(deeptwin, folder, skill="notice")

    assert [(i.example.id, i.file.name) for i in done.imported] == [("ex-0001", "a.txt")]
    assert [(s.file.name, s.same_as) for s in done.skipped] == [("b.md", "ex-0001")]


def test_an_existing_example_with_surrounding_blank_lines_counts_as_the_same(
    deeptwin: DeepTwin, past: Path
) -> None:
    # 손으로 `text: |` 블록으로 적은 예시는 끝에 줄바꿈이 붙는다
    deeptwin.write_example(an_example("ex-0001", PAST_NOTICES[0] + "\n"))

    done = import_folder(deeptwin, past, skill="notice")

    assert [(s.file.name, s.same_as) for s in done.skipped] == [("p1.txt", "ex-0001")]
    assert [i.example.id for i in done.imported] == ["ex-0002", "ex-0003", "ex-0004", "ex-0005"]


def test_the_same_text_in_another_skill_is_not_a_duplicate(deeptwin: DeepTwin, past: Path) -> None:
    deeptwin.write_example(an_example("ex-0001", PAST_NOTICES[0], skill="other"))

    done = import_folder(deeptwin, past, skill="notice")

    assert len(done.imported) == 5
    assert done.skipped == ()


# 글 읽기


def test_text_is_utf8_with_lf_line_breaks_and_no_surrounding_whitespace(
    deeptwin: DeepTwin, tmp_path: Path
) -> None:
    folder = tmp_path / "mixed"
    folder.mkdir()
    raw = "﻿\n  첫 줄\r\n\r\n  들여 쓴 줄\r셋째 줄\n\n".encode()
    (folder / "a.txt").write_bytes(raw)

    done = import_folder(deeptwin, folder, skill="notice")

    assert done.imported[0].example.text == "첫 줄\n\n  들여 쓴 줄\n셋째 줄"


def test_a_file_with_unicode_line_breaks_imported_twice_adds_nothing_the_second_time(
    deeptwin: DeepTwin, tmp_path: Path
) -> None:
    # YAML은 U+0085도 줄바꿈으로 읽는다. 바꾸지 않으면 다시 읽은 글이 달라 중복이 생긴다
    folder = tmp_path / "nel"
    folder.mkdir()
    (folder / "a.txt").write_text("첫 줄\x85둘째 줄\u2028셋째 줄\u2029넷째 줄", encoding="utf-8")

    first = import_folder(deeptwin, folder, skill="notice")
    second = import_folder(deeptwin, folder, skill="notice")

    assert first.imported[0].example.text == "첫 줄\n둘째 줄\n셋째 줄\n넷째 줄"
    assert second.imported == ()
    assert [s.same_as for s in second.skipped] == ["ex-0001"]
    assert example_files(deeptwin) == ["ex-0001.yaml"]


def test_files_are_picked_by_suffix_in_file_name_order(deeptwin: DeepTwin, tmp_path: Path) -> None:
    folder = tmp_path / "picked"
    folder.mkdir()
    for name in ["b.TXT", "a.md", "c.Md", ".hidden.txt", "._a.txt", "notes.docx", "readme"]:
        (folder / name).write_text(f"{name} 파일의 글", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "inner.txt").write_text("하위 폴더의 글", encoding="utf-8")
    (folder / "d.txt").mkdir()  # 이름이 .txt로 끝나는 폴더

    done = import_folder(deeptwin, folder, skill="notice")

    assert [i.file.name for i in done.imported] == ["a.md", "b.TXT", "c.Md"]


@pytest.mark.parametrize(
    ("raw", "line", "reason"),
    [
        (b"", 1, "글이 비었습니다(공백뿐인 파일도 빈 글로 봅니다)"),
        (b" \n\t\r\n  \n", 1, "글이 비었습니다(공백뿐인 파일도 빈 글로 봅니다)"),
        ("첫 줄\n둘째 줄\n".encode() + b"\xff\xfe", 3, "UTF-8 글로 읽을 수 없습니다"),
        ("첫 줄\n".encode("cp949"), 1, "UTF-8 글로 읽을 수 없습니다"),
    ],
    ids=["empty", "blank", "bad-byte", "cp949"],
)
def test_an_empty_or_broken_file_stops_the_whole_import(
    deeptwin: DeepTwin, past: Path, raw: bytes, line: int, reason: str
) -> None:
    (past / "p3.txt").write_bytes(raw)

    with pytest.raises(DeeptwinError) as info:
        import_folder(deeptwin, past, skill="notice", signature=True)

    assert info.value.code == "invalid_file"
    assert info.value.message == f"past/p3.txt:{line}: {reason}"
    assert example_files(deeptwin) == []


def test_every_bad_file_is_listed_in_file_name_order(deeptwin: DeepTwin, past: Path) -> None:
    (past / "p4.txt").write_bytes(b"")
    (past / "p2.txt").write_bytes(b"\x80")

    with pytest.raises(DeeptwinError) as info:
        import_folder(deeptwin, past, skill="notice")

    assert info.value.message.splitlines() == [
        "past/p2.txt:1: UTF-8 글로 읽을 수 없습니다",
        "past/p4.txt:1: 글이 비었습니다(공백뿐인 파일도 빈 글로 봅니다)",
    ]


def test_the_bad_line_is_counted_after_the_bom(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"\xef\xbb\xbf" + "첫 줄\n".encode() + b"\xff")

    with pytest.raises(DeeptwinError) as info:
        read_past_work(path, root=tmp_path)

    assert info.value.message == "a.txt:2: UTF-8 글로 읽을 수 없습니다"


def test_a_folder_without_text_files_has_nothing_to_import(
    deeptwin: DeepTwin, tmp_path: Path
) -> None:
    folder = deeptwin.root / "drafts"
    folder.mkdir()
    (folder / "notes.docx").write_bytes(b"PK")
    (folder / "sub").mkdir()
    (folder / "sub" / "inner.txt").write_text("하위 폴더의 글", encoding="utf-8")

    with pytest.raises(DeeptwinError) as info:
        import_folder(deeptwin, folder, skill="notice")

    assert info.value.code == "nothing_to_import"
    assert info.value.message.startswith("가져올 글 파일이 없습니다: drafts. ")
    assert example_files(deeptwin) == []


def test_an_unknown_skill_imports_nothing(deeptwin: DeepTwin, past: Path) -> None:
    with pytest.raises(DeeptwinError) as info:
        import_folder(deeptwin, past, skill="nope")

    assert info.value.code == "skill_not_found"
    assert example_files(deeptwin) == []


def test_a_failed_write_removes_the_examples_written_so_far(
    deeptwin: DeepTwin, past: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_example = DeepTwin.write_example
    calls = 0

    def fail_on_the_third(self: DeepTwin, example: Example) -> Path:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("디스크가 찼습니다")
        return write_example(self, example)

    monkeypatch.setattr(DeepTwin, "write_example", fail_on_the_third)

    with pytest.raises(OSError, match="디스크가 찼습니다"):
        import_folder(deeptwin, past, skill="notice")

    assert example_files(deeptwin) == []


def test_import_writes_no_ledger_line(deeptwin: DeepTwin, past: Path) -> None:
    import_folder(deeptwin, past, skill="notice", signature=True)
    import_folder(deeptwin, past, skill="notice", signature=True)

    assert not (deeptwin.path / "ledger.jsonl").exists()


# 조립


def test_imported_signature_examples_go_into_the_guide(deeptwin: DeepTwin, tmp_path: Path) -> None:
    folder = tmp_path / "two"
    folder.mkdir()
    (folder / "a.txt").write_text(PAST_NOTICES[1] + "\n", encoding="utf-8")
    (folder / "b.txt").write_text(PAST_NOTICES[2] + "\n", encoding="utf-8")
    import_folder(deeptwin, folder, skill="notice", signature=True)
    task = Task(id="task-0001", skill="notice", split="train", input="휴강 공지를 써 주세요.")

    composed = compose(deeptwin.skill("notice"), task, deeptwin, context={})

    assert sorted(composed.injected) == ["ex-0001", "ex-0002"]
    examples_part = composed.guide.split(GOOD_EXAMPLES_HEADING + "\n", 1)[1]
    assert PAST_NOTICES[1] in examples_part
    assert PAST_NOTICES[2] in examples_part


def test_usual_imports_stay_out_of_the_guide(deeptwin: DeepTwin, past: Path) -> None:
    import_folder(deeptwin, past, skill="notice")
    task = Task(id="task-0001", skill="notice", split="train", input="휴강 공지를 써 주세요.")

    composed = compose(deeptwin.skill("notice"), task, deeptwin, context={})

    assert composed.injected == []
    assert composed.guide == ""
