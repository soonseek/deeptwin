"""T084: inbound contributions carry a Developer Certificate of Origin sign-off."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("dco_check", ROOT / "packaging/contributions/dco_check.py")
dco_check = importlib.util.module_from_spec(_spec)
sys.modules["dco_check"] = dco_check
_spec.loader.exec_module(dco_check)


def _git(repo: Path, *args: str, name: str = "Ada Author", email: str = "ada@example.org") -> str:
    env = {"GIT_AUTHOR_NAME": name, "GIT_AUTHOR_EMAIL": email, "GIT_COMMITTER_NAME": name,
           "GIT_COMMITTER_EMAIL": email, "HOME": str(repo), "PATH": "/usr/bin:/bin"}
    return subprocess.run(["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True).stdout


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "base")
    return tmp_path


def test_the_dco_text_is_the_verbatim_version_1_1():
    text = (ROOT / "DCO").read_text()
    assert text.startswith("Developer Certificate of Origin\nVersion 1.1\n")
    assert "changing it is not allowed" in text
    assert text.count("\n(") == 4  # clauses (a)-(d)
    assert 'path = "DCO"' in (ROOT / "REUSE.toml").read_text()


def test_a_signed_off_commit_by_its_author_passes(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-s", "-m", "change")
    assert [dco_check.problem(c) for c in dco_check.commits("main~1..main", repo)] == [None]


def test_an_unsigned_commit_fails(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "change")
    [commit] = dco_check.commits("main~1..main", repo)
    assert dco_check.problem(commit) == "no Signed-off-by trailer"


def test_a_sign_off_by_someone_else_does_not_cover_the_author(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "change\n\nSigned-off-by: Bo Other <bo@example.org>")
    [commit] = dco_check.commits("main~1..main", repo)
    assert "no Signed-off-by for the author" in dco_check.problem(commit)


def test_a_sign_off_quoted_in_the_body_is_not_a_trailer():
    message = "change\n\nSigned-off-by: Ada Author <ada@example.org>\n\nmore text"
    assert dco_check.signoffs(message) == []


def test_merge_commits_are_exempt_and_email_case_is_ignored():
    merge = dco_check.Commit("a" * 40, "Ada", "ada@x.org", 2, "Merge")
    signed = dco_check.Commit("b" * 40, "Ada", "Ada@X.org", 1, "c\n\nSigned-off-by: Ada <ada@x.org>")
    assert dco_check.problem(merge) is None and dco_check.problem(signed) is None


def test_the_command_line_reports_failures_with_exit_status(tmp_path, capsys, monkeypatch):
    repo = _repo(tmp_path)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "unsigned")
    monkeypatch.chdir(repo)
    assert dco_check.main(["dco_check.py", "main~1..main"]) == 1
    assert "fail the DCO sign-off check" in capsys.readouterr().out
