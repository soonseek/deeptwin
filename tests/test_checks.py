"""원칙 검사 `check`와 `prepare_checks`. 계획의 I/O 매트릭스를 줄마다 돌린다.

데이터는 모두 가상이다.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

import deeptwin as package
from deeptwin.checks import check, prepare_checks
from deeptwin.compose import FLUID_CLOSE, FLUID_OPEN
from deeptwin.errors import DeeptwinError
from deeptwin.models import Principle, Skill, Violation
from deeptwin.store.files import write_yaml
from deeptwin.store.project import DeepTwin

CHECKS_SOURCE = """\
import re


def no_inflated_numbers(output: str) -> bool:
    return not re.search(r"역대급|최고의|100%", output)


def polite(output: str) -> bool:
    return "습니다" in output
"""
"""가상 인물의 검사 함수. 설계서 8.4의 `no_inflated_numbers`와 존댓말 검사다."""

INFLATED = "역대급 혜택! 지금 신청하세요.\n"
"""`no_inflated_numbers`가 `False`, `polite`가 `False`인 결과물."""
PLAIN = "다음 기수 시작일은 확인해 알려 드리겠습니다.\n"
"""두 함수가 모두 `True`인 결과물."""


@pytest.fixture
def deeptwin(tmp_path: Path) -> DeepTwin:
    return DeepTwin.init(tmp_path).deeptwin


def make_skill(
    deeptwin: DeepTwin,
    skill_id: str = "minimal",
    *,
    checks: str | None = "checks.py",
    source: str | None = CHECKS_SOURCE,
) -> Skill:
    """`skills/<skill_id>/`에 `skill.yaml`, `SKILL.md`, (`source`를 주면) `checks.py`를 쓴다."""
    folder = deeptwin.root / "skills" / skill_id
    folder.mkdir(parents=True, exist_ok=True)
    write_yaml(folder / "skill.yaml", {"schema": 1, "id": skill_id, "checks": checks})
    (folder / "SKILL.md").write_text(f"{FLUID_OPEN}\n{FLUID_CLOSE}\n", encoding="utf-8")
    if source is not None:
        (folder / "checks.py").write_text(source, encoding="utf-8")
    return deeptwin.skill(skill_id)


def principle(item_id: str, rule: str, check: str | None, **fields: Any) -> Principle:
    data = {
        "id": item_id,
        "rule": rule,
        "kind": "never",
        "check": check,
        "status": "active",
        "approval": "human",
        **fields,
    }
    return Principle.model_validate(data)


PRIN_01 = principle("prin-01", "수치를 부풀리지 않는다", "no_inflated_numbers")
PRIN_02 = principle("prin-02", "존댓말로 쓴다", "polite", kind="must")


def raises(code: str, call: Any) -> str:
    with pytest.raises(DeeptwinError) as info:
        call()
    assert info.value.code == code
    return info.value.message


# 위반과 통과


@pytest.mark.acceptance
def test_check_returns_the_violation_the_function_catches(deeptwin: DeepTwin) -> None:
    """설계서 8.11 수용 테스트 8.

    `checks.py`의 함수가 위반을 잡으면 `check`가 그 위반을 돌려준다.
    """
    skill = make_skill(deeptwin)
    deeptwin.write_principles([PRIN_01])

    assert check(skill, INFLATED, deeptwin) == [
        Violation(principle="prin-01", rule="수치를 부풀리지 않는다", check="no_inflated_numbers")
    ]
    assert check(skill, PLAIN, deeptwin) == []


def test_violations_follow_the_principles_file_order(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin)
    deeptwin.write_principles([PRIN_02, PRIN_01])

    violations = check(skill, INFLATED, deeptwin)

    assert [v.principle for v in violations] == ["prin-02", "prin-01"]
    assert [v.check for v in violations] == ["polite", "no_inflated_numbers"]
    assert violations[0].rule == "존댓말로 쓴다"


def test_output_that_keeps_every_principle_has_no_violation(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin)
    deeptwin.write_principles([PRIN_01, PRIN_02])

    assert check(skill, PLAIN, deeptwin) == []


def test_principle_without_a_check_is_skipped(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin)
    deeptwin.write_principles([principle("prin-03", "날짜는 숫자로 쓴다", None), PRIN_01])

    assert [v.principle for v in check(skill, INFLATED, deeptwin)] == ["prin-01"]


@pytest.mark.parametrize(
    ("checks", "source"),
    [(None, None), ("checks.py", "raise RuntimeError('불러오면 안 된다')\n")],
    ids=["checks-null", "checks-file-not-read"],
)
def test_nothing_to_check_does_not_read_checks_py(
    deeptwin: DeepTwin, checks: str | None, source: str | None
) -> None:
    skill = make_skill(deeptwin, checks=checks, source=source)
    deeptwin.write_principles([principle("prin-01", "수치를 부풀리지 않는다", None)])

    assert prepare_checks(skill, deeptwin).found == ()
    assert check(skill, INFLATED, deeptwin) == []


def test_no_principles_file_has_nothing_to_check(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin, source="raise RuntimeError('불러오면 안 된다')\n")

    assert check(skill, INFLATED, deeptwin) == []


def test_only_active_principles_in_scope_are_checked(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin)
    deeptwin.write_principles(
        [
            principle("prin-other", "다른 스킬", "no_inflated_numbers", scope=["class-notice"]),
            principle("prin-dormant", "휴면", "no_inflated_numbers", status="dormant"),
            principle("prin-candidate", "후보", "no_inflated_numbers", status="candidate"),
            principle("prin-retired", "은퇴", "no_inflated_numbers", status="retired"),
            principle("prin-mine", "이 스킬", "no_inflated_numbers", scope=["minimal", "x"]),
            principle("prin-all", "모든 스킬", "no_inflated_numbers", scope=[]),
        ]
    )

    violations = check(skill, INFLATED, deeptwin)

    assert [v.principle for v in violations] == ["prin-mine", "prin-all"]


def test_out_of_scope_principles_need_no_function(deeptwin: DeepTwin) -> None:
    """범위 밖이거나 비활성인 원칙의 함수는 찾지 않는다. 없어도 오류가 아니다."""
    skill = make_skill(deeptwin, checks=None, source=None)
    deeptwin.write_principles(
        [
            principle("prin-other", "다른 스킬", "missing", scope=["class-notice"]),
            principle("prin-dormant", "휴면", "missing", status="dormant"),
        ]
    )

    assert check(skill, INFLATED, deeptwin) == []


# 찾기 단계: prepare_checks가 낸다. 결과물에 돌리기 전이다


def test_missing_function_is_check_not_found(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin)
    deeptwin.write_principles([PRIN_01, principle("prin-02", "존댓말로 쓴다", "no_such_check")])

    message = raises("check_not_found", lambda: prepare_checks(skill, deeptwin))

    assert message == (
        "skills/minimal/checks.py에 원칙 prin-02의 검사 함수가 없습니다: no_such_check"
    )


def test_every_missing_function_gets_a_line(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin)
    deeptwin.write_principles(
        [principle("prin-01", "하나", "first_missing"), principle("prin-02", "둘", "second")]
    )

    message = raises("check_not_found", lambda: check(skill, PLAIN, deeptwin))

    assert message.splitlines() == [
        "skills/minimal/checks.py에 원칙 prin-01의 검사 함수가 없습니다: first_missing",
        "skills/minimal/checks.py에 원칙 prin-02의 검사 함수가 없습니다: second",
    ]


def test_function_name_that_is_not_callable_is_check_not_found(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin, source="no_inflated_numbers = 3\n")
    deeptwin.write_principles([PRIN_01])

    message = raises("check_not_found", lambda: prepare_checks(skill, deeptwin))

    assert message.startswith(
        "skills/minimal/checks.py에 있는 원칙 prin-01의 검사 함수를 부를 수 없습니다: "
        "no_inflated_numbers(int)."
    )


def test_only_names_defined_in_checks_py_are_looked_up(deeptwin: DeepTwin) -> None:
    """함수 이름은 `checks.py`의 이름공간에서 찾는다. 모듈 객체의 다른 속성은 보지 않는다."""
    skill = make_skill(deeptwin)
    deeptwin.write_principles([principle("prin-01", "하나", "__class__")])

    raises("check_not_found", lambda: prepare_checks(skill, deeptwin))


def test_checks_null_with_a_principle_check_is_check_not_found(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin, checks=None)
    deeptwin.write_principles([PRIN_01])

    message = raises("check_not_found", lambda: prepare_checks(skill, deeptwin))

    assert message == (
        "스킬 minimal의 skill.yaml에 checks가 없는데, 검사 함수를 적은 원칙이 있습니다: "
        "prin-01(no_inflated_numbers). skills/minimal/skill.yaml에 checks: checks.py를 적고 "
        "그 파일에 함수를 두거나, 원칙의 check를 null로 바꾸세요."
    )


def test_missing_checks_file_is_check_not_found(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin, checks="rules/checks.py")
    deeptwin.write_principles([PRIN_01])

    message = raises("check_not_found", lambda: prepare_checks(skill, deeptwin))

    assert message == (
        "검사 파일이 없습니다: skills/minimal/rules/checks.py. "
        "검사 함수를 적은 원칙: prin-01(no_inflated_numbers)"
    )


def test_checks_in_a_sub_folder_of_the_skill_is_found(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin, checks="rules/checks.py", source=None)
    (deeptwin.root / "skills" / "minimal" / "rules").mkdir()
    (deeptwin.root / "skills" / "minimal" / "rules" / "checks.py").write_text(
        CHECKS_SOURCE, encoding="utf-8"
    )
    deeptwin.write_principles([PRIN_01])

    assert [v.principle for v in check(skill, INFLATED, deeptwin)] == ["prin-01"]


@pytest.mark.parametrize("where", ["parent", "absolute"])
def test_checks_outside_the_skill_folder_is_check_not_found(deeptwin: DeepTwin, where: str) -> None:
    outside = deeptwin.root / "skills" / "outside.py"
    checks = "../outside.py" if where == "parent" else str(outside)
    skill = make_skill(deeptwin, checks=checks, source=None)
    outside.write_text("raise RuntimeError('불러오면 안 된다')\n", encoding="utf-8")
    deeptwin.write_principles([PRIN_01])

    message = raises("check_not_found", lambda: prepare_checks(skill, deeptwin))

    assert message == (
        f"스킬 minimal의 checks가 스킬 폴더 밖을 가리킵니다: {checks}. "
        "skills/minimal/ 안의 상대 경로(예: checks.py)를 적으세요."
    )


@pytest.mark.parametrize(
    ("source", "shown"),
    [
        ("def no_inflated_numbers(output)\n    return True\n", "SyntaxError: "),
        ("raise ValueError('가짜 실패')\n", "ValueError: 가짜 실패"),
        ("import sys\nsys.exit(3)\n", "SystemExit: 3"),
    ],
    ids=["syntax-error", "raises", "exits"],
)
def test_checks_py_that_fails_to_load_is_check_failed(
    deeptwin: DeepTwin, source: str, shown: str
) -> None:
    skill = make_skill(deeptwin, source=source)
    deeptwin.write_principles([PRIN_01])

    message = raises("check_failed", lambda: prepare_checks(skill, deeptwin))

    assert message.startswith(
        f"검사 파일을 불러오다 오류가 났습니다: skills/minimal/checks.py. {shown}"
    )


# 돌리기 단계: PreparedChecks.run이 낸다


@pytest.mark.parametrize(
    ("body", "shown"),
    [
        ("raise ValueError('가짜 실패')", "에서 오류가 났습니다: ValueError: 가짜 실패"),
        ("return 'no'", "의 반환값이 bool이 아닙니다: 'no'."),
        ("return None", "의 반환값이 bool이 아닙니다: None."),
        ("return 0", "의 반환값이 bool이 아닙니다: 0."),
    ],
    ids=["raises", "returns-str", "returns-none", "returns-int"],
)
def test_function_that_raises_or_returns_non_bool_is_check_failed(
    deeptwin: DeepTwin, body: str, shown: str
) -> None:
    skill = make_skill(deeptwin, source=f"def no_inflated_numbers(output):\n    {body}\n")
    deeptwin.write_principles([PRIN_01])
    prepared = prepare_checks(skill, deeptwin)  # 찾기는 통과한다

    message = raises("check_failed", lambda: prepared.run(PLAIN))

    assert message.startswith(
        f"원칙 prin-01의 검사 함수 no_inflated_numbers(skills/minimal/checks.py){shown}"
    )


def test_function_gets_the_output_as_it_is(deeptwin: DeepTwin) -> None:
    source = "def same(output):\n    return output == '첫 줄\\r\\n둘째 줄\\r\\n'\n"
    skill = make_skill(deeptwin, source=source)
    deeptwin.write_principles([principle("prin-01", "하나", "same")])

    assert check(skill, "첫 줄\r\n둘째 줄\r\n", deeptwin) == []
    assert len(check(skill, "첫 줄\n둘째 줄\n", deeptwin)) == 1


# 불러오기: 스킬끼리 섞이지 않고 흔적을 남기지 않는다


def banned_word_source(word: str) -> str:
    return f"def no_banned_word(output):\n    return {word!r} not in output\n"


def test_two_skills_with_the_same_function_name_do_not_mix(deeptwin: DeepTwin) -> None:
    alpha = make_skill(deeptwin, "alpha", source=banned_word_source("알파"))
    beta = make_skill(deeptwin, "beta", source=banned_word_source("베타"))
    deeptwin.write_principles(
        [
            principle("prin-a", "알파를 쓰지 않는다", "no_banned_word", scope=["alpha"]),
            principle("prin-b", "베타를 쓰지 않는다", "no_banned_word", scope=["beta"]),
        ]
    )
    # 두 스킬을 먼저 모두 불러 둔 뒤에 돌린다. 뒤에 부른 것이 앞의 것을 덮지 않는다
    prepared_alpha = prepare_checks(alpha, deeptwin)
    prepared_beta = prepare_checks(beta, deeptwin)

    assert [v.principle for v in prepared_alpha.run("알파 소식")] == ["prin-a"]
    assert prepared_alpha.run("베타 소식") == []
    assert [v.principle for v in prepared_beta.run("베타 소식")] == ["prin-b"]
    assert prepared_beta.run("알파 소식") == []
    assert [v.principle for v in check(alpha, "알파 베타", deeptwin)] == ["prin-a"]
    assert [v.principle for v in check(beta, "알파 베타", deeptwin)] == ["prin-b"]


def test_loading_leaves_sys_modules_and_sys_path_alone(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin, source="import json\n" + CHECKS_SOURCE)
    deeptwin.write_principles([PRIN_01])
    import json  # noqa: F401 - checks.py가 부르는 모듈을 미리 불러 둔다

    modules, path = set(sys.modules), list(sys.path)

    assert len(check(skill, INFLATED, deeptwin)) == 1

    assert set(sys.modules) == modules
    assert sys.path == path
    assert not [name for name in sys.modules if name.startswith("deeptwin_checks")]
    assert "checks" not in sys.modules


def test_edited_checks_py_is_read_again_and_leaves_no_pycache(deeptwin: DeepTwin) -> None:
    skill = make_skill(deeptwin, source=banned_word_source("알파"))
    deeptwin.write_principles([principle("prin-a", "금지어를 쓰지 않는다", "no_banned_word")])
    assert len(check(skill, "알파", deeptwin)) == 1

    # 크기가 같은 글로 바로 고친다. 캐시를 쓰면 수정 시각과 크기가 같아 옛 코드가 돈다
    (deeptwin.root / "skills" / "minimal" / "checks.py").write_text(
        banned_word_source("베타"), encoding="utf-8"
    )

    assert check(skill, "알파", deeptwin) == []
    assert len(check(skill, "베타", deeptwin)) == 1
    assert not (deeptwin.root / "skills" / "minimal" / "__pycache__").exists()


def test_project_opened_with_a_relative_root_finds_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    DeepTwin.init(Path("proj"))
    deeptwin = DeepTwin.open(Path("proj"))
    skill = make_skill(deeptwin)
    deeptwin.write_principles([PRIN_01])

    assert [v.principle for v in check(skill, INFLATED, deeptwin)] == ["prin-01"]


def test_check_is_public(deeptwin: DeepTwin) -> None:
    assert package.check is check
    assert package.Violation is Violation
