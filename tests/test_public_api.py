"""CLI는 공개 API만 쓴다(설계서 9.3).

`src/deeptwin/cli/*.py`가 `from deeptwin.<모듈> import <이름>`으로 가져오는 이름은 모두 그 모듈의
`__all__`에 있어야 하고 `_`로 시작하지 않는다. `deeptwin.cli` 안끼리는 예외다.
모듈을 통째로 가져오면(`import deeptwin.<모듈>`) 쓰는 이름을 검사할 수 없으므로 막는다.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
import textwrap
from pathlib import Path

import pytest

import deeptwin.cli

CLI = Path(deeptwin.cli.__file__).parent
CLI_PACKAGE = "deeptwin.cli"


def checked(module: str) -> bool:
    """규칙이 걸리는 모듈인가: `deeptwin`과 그 아래 모듈 가운데 `deeptwin.cli` 밖의 것."""
    inside = module == "deeptwin" or module.startswith("deeptwin.")
    cli = module == CLI_PACKAGE or module.startswith(CLI_PACKAGE + ".")
    return inside and not cli


def violations(shown: str, source: str) -> list[str]:
    """CLI 파일 하나의 import 가운데 규칙을 어긴 것. `<파일>:<줄>: <모듈>.<이름>: <까닭>`이다.

    함수 안의 import도 본다. 상대 import는 `deeptwin.cli` 기준으로 푼다.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if checked(alias.name):
                    found.append(
                        f"{shown}:{node.lineno}: {alias.name}: 모듈을 통째로 가져오면 쓰는 이름을 "
                        f"검사할 수 없습니다. from {alias.name} import <이름>으로 쓰세요"
                    )
        elif isinstance(node, ast.ImportFrom):
            module = importlib.util.resolve_name(
                "." * node.level + (node.module or ""), CLI_PACKAGE
            )
            if not checked(module):
                continue
            exported = getattr(importlib.import_module(module), "__all__", None)
            for alias in node.names:
                where = f"{shown}:{node.lineno}: {module}.{alias.name}"
                if alias.name.startswith("_"):
                    found.append(f"{where}: _로 시작하는 이름입니다")
                elif exported is None:
                    found.append(f"{where}: {module}에 __all__이 없습니다")
                elif alias.name not in exported:
                    found.append(f"{where}: {module}의 __all__에 없습니다")
    return found


def test_cli_imports_only_public_names() -> None:
    files = sorted(CLI.glob("*.py"))
    assert {"main.py", "output.py"} <= {path.name for path in files}

    found = [
        problem
        for path in files
        for problem in violations(
            path.relative_to(CLI.parent.parent).as_posix(), path.read_text(encoding="utf-8")
        )
    ]

    assert found == [], "\n".join(found)


def test_cli_does_import_from_deeptwin() -> None:
    """검사할 import가 실제로 있다. 하나도 못 찾아서 통과하는 것이 아니다."""
    tree = ast.parse((CLI / "main.py").read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module and checked(node.module)
    }

    assert {"deeptwin.errors", "deeptwin.runs", "deeptwin.store.project"} <= modules


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from deeptwin.store.project import DATA_DIR, _RUN_DIR",
            "deeptwin/cli/sample.py:1: deeptwin.store.project._RUN_DIR: _로 시작하는 이름입니다",
        ),
        (
            "from deeptwin.store.project import Path",
            "deeptwin/cli/sample.py:1: deeptwin.store.project.Path: "
            "deeptwin.store.project의 __all__에 없습니다",
        ),
        (
            "from deeptwin.store import project",
            "deeptwin/cli/sample.py:1: deeptwin.store.project: deeptwin.store에 __all__이 없습니다",
        ),
        (
            "from deeptwin import store",
            "deeptwin/cli/sample.py:1: deeptwin.store: deeptwin의 __all__에 없습니다",
        ),
        (
            "from ..runs import _unknown",
            "deeptwin/cli/sample.py:1: deeptwin.runs._unknown: _로 시작하는 이름입니다",
        ),
        (
            "import json\n\n\ndef late():\n    from deeptwin.compose import _in_scope\n",
            "deeptwin/cli/sample.py:5: deeptwin.compose._in_scope: _로 시작하는 이름입니다",
        ),
        (
            "import deeptwin.store.project",
            "deeptwin/cli/sample.py:1: deeptwin.store.project: 모듈을 통째로 가져오면 쓰는 "
            "이름을 검사할 수 없습니다. from deeptwin.store.project import <이름>으로 쓰세요",
        ),
    ],
    ids=["underscore", "not-in-all", "no-all", "package", "relative", "in-function", "module"],
)
def test_breaking_the_rule_names_the_file_module_and_name(source: str, expected: str) -> None:
    assert violations("deeptwin/cli/sample.py", source) == [expected]


def test_public_names_and_imports_outside_the_rule_pass() -> None:
    source = textwrap.dedent(
        """\
        import json
        import typer
        from deeptwin import DeepTwin
        from deeptwin.cli.output import _echo_json
        from . import output
        from .output import Reply
        from deeptwin.llm import FakeProvider
        from deeptwin.store.project import DATA_DIR
        """
    )

    assert violations("deeptwin/cli/sample.py", source) == []
