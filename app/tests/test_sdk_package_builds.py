"""T087: separate PEP 517 package roots and exact wheel/sdist artifacts.

`sdk/python/deeptwin_ext` (extension-author kit) and `sdk/python/deeptwin_client`
(HTTPS service client) are independent distributions with their own metadata and
versions. Each builds offline through its own in-tree backend (`backend-path`), because
the project pins no build tool; the backend file is byte-identical in both roots.
"""

import ast
import base64
import csv
import hashlib
import io
import shutil
import sys
import tarfile
import zipfile
from email.parser import BytesParser

import pytest

from app.tests.support.sdk_packages import (
    IMPORT_NAMES,
    PACKAGE_ROOTS,
    REPOSITORY,
    build,
    project_table,
)

DISTRIBUTIONS = tuple(PACKAGE_ROOTS)


def _source_files(distribution):
    package = PACKAGE_ROOTS[distribution] / "src" / IMPORT_NAMES[distribution]
    return sorted(path for path in package.rglob("*.py") if "__pycache__" not in path.parts)


def test_each_distribution_is_its_own_offline_pep517_root():
    names, versions = set(), {}
    for distribution, root in PACKAGE_ROOTS.items():
        table = project_table(distribution)
        assert table["build-system"] == {
            "requires": [], "build-backend": "deeptwin_build_backend", "backend-path": ["_build"]}
        project = table["project"]
        assert project["name"] == distribution
        assert project["dependencies"] == []
        assert project["license"] == "Apache-2.0"
        assert project["license-files"] == ["LICENSE", "NOTICE"]
        for name in project["license-files"]:
            assert (root / name).read_bytes() == (REPOSITORY / name).read_bytes()
        assert table["tool"]["deeptwin-build"] == {
            "package-dir": "src", "packages": [IMPORT_NAMES[distribution]]}
        names.add(project["name"])
        versions[distribution] = project["version"]
    assert len(names) == 2
    backends = {(root / "_build" / "deeptwin_build_backend.py").read_bytes() for root in PACKAGE_ROOTS.values()}
    assert len(backends) == 1
    # the repository itself stays a non-package module tree
    assert "package = false" in (REPOSITORY / "pyproject.toml").read_text()


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_distribution_sources_use_only_the_standard_library(distribution):
    allowed = set(sys.stdlib_module_names) | {IMPORT_NAMES[distribution]}
    sources = _source_files(distribution)
    assert sources
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                roots = [] if node.level else [node.module.split(".")[0]]
            else:
                continue
            assert set(roots) <= allowed, (path.name, roots)
            assert "app" not in roots


def _record_hash(data):
    return "sha256=" + base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_wheel_has_exact_files_metadata_and_verified_record(distribution, tmp_path):
    project = project_table(distribution)["project"]
    stem = distribution.replace("-", "_")
    wheel = build(distribution, "wheel", tmp_path)
    assert wheel.name == f"{stem}-{project['version']}-py3-none-any.whl"
    dist_info = f"{stem}-{project['version']}.dist-info"
    package_dir = PACKAGE_ROOTS[distribution] / "src"
    expected_sources = {path.relative_to(package_dir).as_posix(): path.read_bytes()
                        for path in _source_files(distribution)}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert set(names) == set(expected_sources) | {
            f"{dist_info}/{name}" for name in ("METADATA", "WHEEL", "RECORD", "licenses/LICENSE", "licenses/NOTICE")}
        for name, data in expected_sources.items():
            assert archive.read(name) == data
        assert not any(name.startswith(("app/", "sdk/", "_build/")) for name in names)
        record = list(csv.reader(io.StringIO(archive.read(f"{dist_info}/RECORD").decode())))
        assert {row[0] for row in record} == set(names)
        for name, digest, size in record:
            if name == f"{dist_info}/RECORD":
                assert digest == size == ""
                continue
            data = archive.read(name)
            assert digest == _record_hash(data) and int(size) == len(data)
        wheel_file = archive.read(f"{dist_info}/WHEEL").decode()
        assert "Root-Is-Purelib: true" in wheel_file and "Tag: py3-none-any" in wheel_file
        metadata = BytesParser().parsebytes(archive.read(f"{dist_info}/METADATA"))
    assert metadata["Metadata-Version"] == "2.4"
    assert metadata["Name"] == distribution
    assert metadata["Version"] == project["version"]
    assert metadata["License-Expression"] == "Apache-2.0"
    assert metadata.get_all("License-File") == ["LICENSE", "NOTICE"]
    assert metadata["Requires-Python"] == project["requires-python"]
    assert metadata.get_all("Requires-Dist") is None


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
def test_sdist_is_a_self_contained_package_root(distribution, tmp_path):
    project = project_table(distribution)["project"]
    top = f"{distribution.replace('-', '_')}-{project['version']}"
    sdist = build(distribution, "sdist", tmp_path)
    assert sdist.name == f"{top}.tar.gz"
    root = PACKAGE_ROOTS[distribution]
    expected = {"pyproject.toml", "LICENSE", "NOTICE", "_build/deeptwin_build_backend.py"}
    expected |= {path.relative_to(root).as_posix() for path in _source_files(distribution)}
    with tarfile.open(sdist) as archive:
        members = {member.name: member for member in archive.getmembers()}
        files = {name[len(top) + 1:] for name, member in members.items() if member.isfile()}
        assert files == expected | {"PKG-INFO"}
        for name in expected:
            assert archive.extractfile(f"{top}/{name}").read() == (root / name).read_bytes()
        for member in members.values():
            assert member.name == top or member.name.startswith(top + "/")
            assert member.isfile() or member.isdir()
            assert member.uid == member.gid == 0 and member.mtime == 315532800
        pkg_info = BytesParser().parsebytes(archive.extractfile(f"{top}/PKG-INFO").read())
    assert pkg_info["Name"] == distribution and pkg_info["Version"] == project["version"]


@pytest.mark.parametrize("distribution", DISTRIBUTIONS)
@pytest.mark.parametrize("kind", ("wheel", "sdist"))
def test_builds_are_byte_reproducible(distribution, kind, tmp_path):
    first = build(distribution, kind, tmp_path / "a")
    second = build(distribution, kind, tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
    later = build(distribution, kind, tmp_path / "c", epoch=1_800_000_000)
    assert later.read_bytes() != first.read_bytes()


@pytest.mark.parametrize("change", (
    ('dependencies = []', 'dependencies = ["httpx"]'),
    ('version = "0.1.0"', 'version = "0.1"'),
    ('license-files = ["LICENSE", "NOTICE"]', 'license-files = ["../LICENSE"]'),
    ('dependencies = []', 'dependencies = []\nreadme = "README.md"'),
))
def test_backend_refuses_what_it_does_not_support(change, tmp_path, monkeypatch):
    copy = tmp_path / "root"
    shutil.copytree(PACKAGE_ROOTS["deeptwin-client"], copy,
                    ignore=shutil.ignore_patterns("__pycache__"))
    pyproject = copy / "pyproject.toml"
    text = pyproject.read_text()
    assert change[0] in text
    pyproject.write_text(text.replace(*change))
    monkeypatch.setitem(PACKAGE_ROOTS, "deeptwin-client", copy)
    with pytest.raises(AssertionError, match="BuildError"):
        build("deeptwin-client", "wheel", tmp_path / "out")
