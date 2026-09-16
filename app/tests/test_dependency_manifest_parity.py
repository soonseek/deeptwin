"""The dependency truth lives in pyproject.toml — and nowhere else drifts.

Three places used to disagree about what this project depends on: the
uv-managed virtual environment (packages installed by hand), the worktree's
app/requirements.txt (a partial development slice) and the repository
pyproject.toml (scaffold-era ranges). This test binds them: every runtime
dependency declared in pyproject.toml is pinned exactly, app/requirements.txt
is a byte-faithful projection of those pins, and the interpreter running the
suite actually has each pinned version installed. Any future drift fails
here instead of surfacing as a missing import on a fresh checkout.
"""

import re
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_PYPROJECT = _ROOT / "pyproject.toml"
_REQUIREMENTS = _ROOT / "app" / "requirements.txt"
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(\[[A-Za-z0-9,_-]+\])?==([A-Za-z0-9.+!]+)$")


def _normalize(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def _pins(specifiers, label):
    pins = {}
    for item in specifiers:
        match = _PIN.match(item.strip())
        assert match is not None, f"{label}: {item!r} is not an exact == pin"
        pins[_normalize(match.group(1))] = match.group(3)
    return pins


def _pyproject():
    assert _PYPROJECT.is_file(), "pyproject.toml must live at the repository root"
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def test_runtime_dependencies_are_exact_pins():
    pins = _pins(_pyproject()["project"]["dependencies"], "pyproject dependencies")
    assert pins, "pyproject.toml declares no runtime dependencies"


def test_requirements_txt_is_a_projection_of_pyproject():
    expected = _pins(_pyproject()["project"]["dependencies"], "pyproject dependencies")
    lines = [
        line.strip() for line in _REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]
    actual = _pins(lines, "app/requirements.txt")
    assert actual == expected


@pytest.mark.parametrize("group", ["dependencies", "dev"])
def test_every_pinned_package_is_installed_at_that_version(group):
    document = _pyproject()
    specifiers = (
        document["project"]["dependencies"] if group == "dependencies"
        else document["dependency-groups"]["dev"]
    )
    for name, version in _pins(specifiers, group).items():
        try:
            installed = metadata.version(name)
        except metadata.PackageNotFoundError:
            pytest.fail(f"{name}=={version} is declared but not installed")
        assert installed == version, f"{name}: declared {version}, installed {installed}"
