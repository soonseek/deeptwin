"""Check the Developer Certificate of Origin sign-off on a range of commits (T084).

Inbound contributions are accepted under the DCO (DCO at the repository root; decided
2026-09-26 in specs/001-autonomous-release/decisions.md). Every non-merge commit in the
range must carry a ``Signed-off-by: Name <email>`` trailer naming the commit's author, as
``git commit -s`` writes it. The check reads git only; it never edits history.

    python packaging/contributions/dco_check.py origin/main..HEAD
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

_SIGNOFF = re.compile(r"^Signed-off-by:\s*(?P<name>.+?)\s*<(?P<email>[^<>\s]+)>\s*$")


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    parents: int
    message: str


def signoffs(message: str) -> list[tuple[str, str]]:
    """The sign-offs in the message's final trailer block, in order."""
    blocks = message.strip().split("\n\n")
    found = []
    for line in blocks[-1].splitlines() if blocks else []:
        match = _SIGNOFF.match(line.strip())
        if match:
            found.append((match.group("name"), match.group("email")))
    return found


def problem(commit: Commit) -> str | None:
    if commit.parents > 1:
        return None
    signed = signoffs(commit.message)
    if not signed:
        return "no Signed-off-by trailer"
    author = (commit.author_name.strip(), commit.author_email.strip().lower())
    if not any((name, email.lower()) == author for name, email in signed):
        return f"no Signed-off-by for the author {commit.author_name} <{commit.author_email}>"
    return None


def commits(revision_range: str, cwd: Path) -> list[Commit]:
    out = subprocess.run(
        ["git", "log", "--format=%H%x00%an%x00%ae%x00%P%x00%B%x1e", revision_range],
        cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout
    found = []
    for record in out.split("\x1e"):
        record = record.lstrip("\n")
        if not record:
            continue
        sha, name, email, parents, message = record.split("\x00", 4)
        found.append(Commit(sha, name, email, len(parents.split()), message))
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: dco_check.py <revision-range>", file=sys.stderr)
        return 2
    failures = [(c.sha[:12], p) for c in commits(argv[1], Path.cwd()) if (p := problem(c))]
    for sha, reason in failures:
        print(f"{sha}: {reason}")
    if failures:
        print(f"{len(failures)} commit(s) fail the DCO sign-off check; see DCO and docs/release/contributing.md.")
        return 1
    print("DCO sign-off check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
