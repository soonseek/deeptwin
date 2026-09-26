"""Build the T087 Python distributions and install them into fresh environments.

The frontend here plays the role `python -m build` would: it calls the package root's
declared PEP 517 backend in a child process whose working directory is that root, and
nothing from the repository is on its `sys.path` except the root's own `backend-path`.
Installation goes through pip in a new `venv` with `--no-index --no-deps`, and code under
test then runs with `python -I` from a directory outside the repository.
"""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
SDK = REPOSITORY / "sdk" / "python"
PACKAGE_ROOTS = {
    "deeptwin-ext": SDK / "deeptwin_ext",
    "deeptwin-client": SDK / "deeptwin_client",
}
IMPORT_NAMES = {"deeptwin-ext": "deeptwin_ext", "deeptwin-client": "deeptwin_client"}

_FRONTEND = r"""
import json, sys, tomllib
from pathlib import Path
system = tomllib.loads(Path("pyproject.toml").read_text())["build-system"]
assert system["requires"] == [], system
for entry in system["backend-path"]:
    sys.path.insert(0, str(Path(entry).resolve()))
backend = __import__(system["build-backend"])
kind, out = sys.argv[1], sys.argv[2]
hook = getattr(backend, "get_requires_for_build_" + kind)
assert hook({}) == []
print(json.dumps(getattr(backend, "build_" + kind)(out, {})))
"""


def scrubbed_environment(**extra):
    """An environment without PYTHONPATH/PYTHONHOME or pip configuration leaking in."""

    keep = {"PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT"}
    environment = {key: value for key, value in os.environ.items() if key in keep}
    environment.update(PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INPUT="1")
    environment.update(extra)
    return environment


def build(distribution, kind, out_dir, *, epoch=None):
    """Build `kind` ("wheel" or "sdist") of `distribution` into `out_dir`; return its path."""

    root = PACKAGE_ROOTS[distribution]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    extra = {} if epoch is None else {"SOURCE_DATE_EPOCH": str(epoch)}
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _FRONTEND, kind, str(out_dir)],
        cwd=root, env=scrubbed_environment(**extra), capture_output=True, text=True, timeout=60, check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr[-4000:])
    return out_dir / json.loads(completed.stdout.strip().splitlines()[-1])


def fresh_environment(directory):
    """Create a new venv (no system site-packages, no repository path); return its python."""

    directory = Path(directory)
    subprocess.run([sys.executable, "-I", "-m", "venv", str(directory)], check=True,
                   capture_output=True, env=scrubbed_environment(), timeout=120)
    python = directory / "bin" / "python"
    assert python.exists()
    return python


def pip_install(python, artifact, *, cwd):
    completed = subprocess.run(
        [str(python), "-I", "-m", "pip", "install", "--isolated", "--no-index", "--no-deps",
         "--no-cache-dir", "--quiet", str(artifact)],
        cwd=cwd, env=scrubbed_environment(), capture_output=True, text=True, timeout=180, check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stdout[-2000:] + completed.stderr[-4000:])


def run_isolated(python, script, *, cwd, args=(), timeout=60, stdin=None):
    """Run `script` with `python -I` in `cwd`; return (returncode, stdout, stderr)."""

    completed = subprocess.run(
        [str(python), "-I", "-B", "-c", script, *args], cwd=cwd, env=scrubbed_environment(),
        capture_output=True, text=True, timeout=timeout, input=stdin, check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def project_table(distribution):
    return tomllib.loads((PACKAGE_ROOTS[distribution] / "pyproject.toml").read_text())
