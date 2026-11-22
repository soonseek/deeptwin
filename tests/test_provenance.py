"""패키지의 버전과 커밋(`deeptwin.provenance`), 빌드 훅(`hatch_build.py`), 빌드 의존성.

git이 필요한 테스트는 로컬 `git`으로 임시 저장소를 만들어 돈다. git이 없으면 건너뛴다. 소스의 git을
보는 테스트는 `deeptwin._commit.COMMIT`을 `None`으로 바꿔 둔다(sdist를 풀어 돌릴 때 그 안의
`_commit.py`에는 해시가 들어 있다). 네트워크와 모델을 쓰지 않는다.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
import types
from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

import pytest

import deeptwin
import deeptwin._commit
from deeptwin import provenance

REPO = Path(__file__).resolve().parent.parent
"""저장소(또는 sdist를 푼 폴더)의 최상위."""
PACKAGE_DIR = Path(provenance.__file__).resolve().parent
HOOK_FILE = REPO / "hatch_build.py"
DEFAULT_LINE = "COMMIT: str | None = None"
COMMIT_TEXT = '"""가상의 커밋 파일. 테스트용으로 만든 것이다."""\n\n' + DEFAULT_LINE + "\n"
"""임시 저장소에 두는 `src/deeptwin/_commit.py`의 글."""
HOOK_MODULES = (
    "hatchling",
    "hatchling.builders",
    "hatchling.builders.hooks",
    "hatchling.builders.hooks.plugin",
    "hatchling.builders.hooks.plugin.interface",
)

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git이 없습니다")


def git(*args: str, cwd: Path) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return done.stdout.strip()


def make_repo(folder: Path, *, commit: bool = True) -> str | None:
    """`folder`에 git 저장소를 만든다. `commit`이면 빈 커밋 하나를 만들고 그 해시를 돌려준다."""
    folder.mkdir(parents=True, exist_ok=True)
    git("init", "-q", cwd=folder)
    if not commit:
        return None
    git(
        "-c",
        "user.name=deeptwin-test",
        "-c",
        "user.email=dev@example.com",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "fake commit",
        cwd=folder,
    )
    return git("rev-parse", "HEAD", cwd=folder)


def forbid_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """`subprocess.run`을 부르면 실패하게 하고, 부른 인자를 모은다."""
    called: list[Any] = []

    def run(*args: Any, **kwargs: Any) -> Any:
        called.append(args)
        raise AssertionError("git을 부르지 않아야 합니다")

    monkeypatch.setattr(subprocess, "run", run)
    return called


# 버전


def test_package_version_is_the_installed_version() -> None:
    assert provenance.package_version() == version("deeptwin")
    assert deeptwin.__version__ == provenance.package_version()


def test_package_version_without_metadata_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr(provenance, "version", missing)

    assert provenance.package_version() == "0+unknown"


# 커밋을 읽는 곳


def test_commit_put_in_by_the_build_is_used_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deeptwin._commit, "COMMIT", "a" * 40)
    called = forbid_subprocess(monkeypatch)

    assert provenance.package_commit() == "a" * 40
    assert called == []


@needs_git
def test_commit_from_the_source_is_git_head(from_source: str | None) -> None:
    if from_source is None:
        pytest.skip("저장소의 src/deeptwin에서 돌지 않습니다")

    assert provenance.package_commit() == from_source
    assert provenance.git_commit(PACKAGE_DIR) == from_source


def test_commit_without_git_is_unknown(
    from_source: str | None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(provenance, "GIT", str(tmp_path / "no-such-git"))

    assert provenance.package_commit() is None


@needs_git
def test_git_commit_is_the_head_only_for_the_src_deeptwin_of_that_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    head = make_repo(repo)
    package = repo / "src" / "deeptwin"
    package.mkdir(parents=True)
    other = repo / "lib" / "deeptwin"
    other.mkdir(parents=True)
    empty = tmp_path / "empty"
    make_repo(empty, commit=False)
    (empty / "src" / "deeptwin").mkdir(parents=True)
    outside = tmp_path / "outside" / "src" / "deeptwin"
    outside.mkdir(parents=True)

    assert head is not None and len(head) in (40, 64)
    assert provenance.git_commit(package) == head
    # 다른 저장소 안에 설치한 패키지가 그 저장소의 해시를 내지 않는다
    assert provenance.git_commit(other) is None
    assert provenance.git_commit(repo / "src") is None
    assert provenance.git_commit(empty / "src" / "deeptwin") is None
    assert provenance.git_commit(outside) is None


@pytest.mark.parametrize(
    ("stdout", "code"),
    [
        ("{top}\n" + "a" * 40 + "\n", 1),
        ("{top}\n", 0),
        ("{top}\n" + "a" * 39 + "\n", 0),
        ("{top}\n" + "A" * 40 + "\n", 0),
        ("{top}\n" + "a" * 40 + "\nextra\n", 0),
    ],
    ids=["failed", "one-line", "short-hash", "upper-case", "three-lines"],
)
def test_git_commit_refuses_output_of_the_wrong_shape(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, stdout: str, code: int
) -> None:
    package = tmp_path / "src" / "deeptwin"
    package.mkdir(parents=True)

    def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args, code, stdout.format(top=tmp_path), "")

    monkeypatch.setattr(subprocess, "run", run)

    assert provenance.git_commit(package) is None


@pytest.mark.parametrize("error", [OSError("없음"), subprocess.TimeoutExpired("git", 5)])
def test_git_commit_is_unknown_when_git_cannot_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: Exception
) -> None:
    def run(*args: Any, **kwargs: Any) -> Any:
        raise error

    monkeypatch.setattr(subprocess, "run", run)

    assert provenance.git_commit(tmp_path) is None


def test_the_repository_default_is_none_in_the_source() -> None:
    source = Path(deeptwin._commit.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # sdist를 풀어 돌리면 빌드가 넣은 해시가 들어 있다. 그때는 값만 다르다
    [assign] = [node for node in tree.body if isinstance(node, ast.AnnAssign)]
    assert ast.unparse(assign.target) == "COMMIT"
    assert ast.unparse(assign.annotation) == "str | None"
    assert len(tree.body) == 2
    assert isinstance(tree.body[0], ast.Expr)


# 빌드 훅


class _FakeBuildHookInterface:
    """hatchling의 `BuildHookInterface` 자리. 훅이 쓰는 `root`만 받는다."""

    def __init__(self, root: str) -> None:
        self.root = root


@pytest.fixture
def hook(monkeypatch: pytest.MonkeyPatch) -> Callable[[Path], Any]:
    """가짜 hatchling으로 `hatch_build.py`를 불러 `hook(root)`이 훅 하나를 만들게 한다."""
    for name in HOOK_MODULES:
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    interface = sys.modules["hatchling.builders.hooks.plugin.interface"]
    interface.BuildHookInterface = _FakeBuildHookInterface  # type: ignore[attr-defined]
    spec = importlib.util.spec_from_file_location("hatch_build", HOOK_FILE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.CommitHook.PLUGIN_NAME == "custom"
    return lambda root: module.CommitHook(str(root))


def build_root(folder: Path, text: str = COMMIT_TEXT, *, commit: bool = True) -> str | None:
    """`folder`에 `src/deeptwin/_commit.py`가 있는 저장소를 만들고 `HEAD`를 돌려준다."""
    head = make_repo(folder, commit=commit)
    package = folder / "src" / "deeptwin"
    package.mkdir(parents=True)
    (package / "_commit.py").write_text(text, encoding="utf-8", newline="\n")
    return head


def files_under(folder: Path) -> list[str]:
    return sorted(
        p.relative_to(folder).as_posix()
        for p in folder.rglob("*")
        if ".git" not in p.relative_to(folder).parts
    )


@needs_git
def test_hook_puts_the_head_into_a_temporary_commit_file(
    hook: Callable[[Path], Any], tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    head = build_root(root)
    before = files_under(root)
    data: dict[str, Any] = {"force_include": {}}
    made = hook(root)

    made.initialize("standard", data)

    [(source, target)] = data["force_include"].items()
    assert target == "src/deeptwin/_commit.py"
    written = Path(source)
    assert written.read_bytes() == COMMIT_TEXT.replace(
        DEFAULT_LINE, f'COMMIT: str | None = "{head}"'
    ).encode("utf-8")
    assert root not in written.parents
    assert files_under(root) == before
    assert (root / "src" / "deeptwin" / "_commit.py").read_text(encoding="utf-8") == COMMIT_TEXT

    made.finalize("standard", data, str(tmp_path / "dist" / "deeptwin.whl"))

    assert not written.parent.exists()
    assert files_under(root) == before


@needs_git
@pytest.mark.parametrize("where", ["not-a-repo", "inside-another-repo", "no-commit"])
def test_hook_does_nothing_outside_its_own_repo(
    hook: Callable[[Path], Any], tmp_path: Path, where: str
) -> None:
    if where == "not-a-repo":
        root = tmp_path / "unpacked"
        (root / "src" / "deeptwin").mkdir(parents=True)
        (root / "src" / "deeptwin" / "_commit.py").write_text(COMMIT_TEXT, encoding="utf-8")
    elif where == "inside-another-repo":
        build_root(tmp_path / "outer")
        root = tmp_path / "outer" / "sdist" / "deeptwin-0.0.0"
        (root / "src" / "deeptwin").mkdir(parents=True)
        (root / "src" / "deeptwin" / "_commit.py").write_text(COMMIT_TEXT, encoding="utf-8")
    else:
        root = tmp_path / "fresh"
        build_root(root, commit=False)
    data: dict[str, Any] = {"force_include": {}}
    made = hook(root)

    made.initialize("standard", data)
    made.finalize("standard", data, str(tmp_path / "deeptwin.whl"))

    assert data == {"force_include": {}}


@needs_git
def test_hook_keeps_the_commit_of_an_unpacked_sdist_inside_a_git_repo(
    hook: Callable[[Path], Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # 배포판을 꾸리는 도구가 풀어 둔 sdist를 그대로 git 저장소로 만든 경우
    root = tmp_path / "deeptwin-0.0.0"
    stamped = '"""가상의 커밋 파일."""\n\nCOMMIT: str | None = "' + "c" * 40 + '"\n'
    build_root(root, stamped)
    (root / "PKG-INFO").write_text("Metadata-Version: 2.4\nName: deeptwin\n", encoding="utf-8")
    called = forbid_subprocess(monkeypatch)
    data: dict[str, Any] = {"force_include": {}}
    made = hook(root)

    made.initialize("standard", data)
    made.finalize("standard", data, str(tmp_path / "deeptwin.whl"))

    assert data == {"force_include": {}}
    assert called == []
    assert (root / "src" / "deeptwin" / "_commit.py").read_text(encoding="utf-8") == stamped


def test_hook_skips_editable_installs_without_calling_git(
    hook: Callable[[Path], Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    called = forbid_subprocess(monkeypatch)
    data: dict[str, Any] = {"force_include": {}}
    made = hook(tmp_path)

    made.initialize("editable", data)
    made.finalize("editable", data, str(tmp_path / "deeptwin.whl"))

    assert data == {"force_include": {}}
    assert called == []


@needs_git
@pytest.mark.parametrize(
    "text",
    [
        '"""가상의 커밋 파일."""\n\nCOMMIT: str | None = "' + "b" * 40 + '"\n',
        COMMIT_TEXT + DEFAULT_LINE + "\n",
    ],
    ids=["committed-hash", "twice"],
)
def test_hook_stops_the_build_without_exactly_one_default_line(
    hook: Callable[[Path], Any], tmp_path: Path, text: str
) -> None:
    root = tmp_path / "repo"
    build_root(root, text)
    data: dict[str, Any] = {"force_include": {}}

    with pytest.raises(RuntimeError, match="COMMIT: str \\| None = None"):
        hook(root).initialize("standard", data)

    assert data == {"force_include": {}}


# 빌드 의존성


def test_build_needs_only_hatchling_and_runtime_has_four_dependencies() -> None:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))

    assert config["build-system"]["requires"] == ["hatchling>=1.27"]
    names = [re.split(r"[<>=!~;\[ ]", dep)[0] for dep in config["project"]["dependencies"]]
    assert names == ["pydantic", "pyyaml", "filelock", "typer"]
    hatch = config["tool"]["hatch"]["build"]
    assert hatch["hooks"] == {"custom": {}}
    assert "hatch_build.py" in hatch["targets"]["sdist"]["include"]
    assert hatch["targets"]["wheel"]["packages"] == ["src/deeptwin"]


def test_hook_imports_only_the_standard_library_and_hatchling() -> None:
    tree = ast.parse(HOOK_FILE.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add((node.module or "").split(".")[0])

    assert "hatchling" in imported
    assert imported - {"hatchling"} <= set(sys.stdlib_module_names)
    assert "deeptwin" not in imported
    calls = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "print" not in calls
