"""In-tree PEP 517 build backend for DeepTwin's dependency-free Python distributions.

Why an in-tree backend: the project environment pins no build tool (no setuptools,
hatchling or flit), and these distributions must build offline from their own source
tree. This module uses only the standard library, supports exactly the pyproject subset
the DeepTwin package roots declare, and refuses anything else instead of guessing.

It builds a pure-Python ``py3-none-any`` wheel and a ``.tar.gz`` sdist. Output bytes
are reproducible: sorted entries, fixed timestamps (``SOURCE_DATE_EPOCH`` when set) and
normalized permissions. Editable installs (PEP 660) are not offered.

The same file is kept byte-identical in every DeepTwin package root (a test pins that),
because PEP 517 ``backend-path`` must lie inside the source tree being built.
"""

import base64
import gzip
import hashlib
import io
import os
import re
import tarfile
import time
import tomllib
import zipfile
from pathlib import Path

_NAME = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")
_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_MODULE = re.compile(r"^[a-z_][a-z0-9_]*$")
_PROJECT_KEYS = frozenset({
    "name", "version", "description", "requires-python", "license", "license-files",
    "dependencies", "classifiers",
})
_TOOL_KEYS = frozenset({"package-dir", "packages"})
_ZIP_EPOCH = 315532800  # 1980-01-01, the earliest time a zip entry can carry
_GENERATOR = "deeptwin-build-backend 1"


class BuildError(ValueError):
    pass


def _root():
    return Path.cwd()


def _project():
    root = _root()
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project")
    tool = data.get("tool", {}).get("deeptwin-build")
    if type(project) is not dict or type(tool) is not dict:
        raise BuildError("pyproject needs [project] and [tool.deeptwin-build]")
    if set(project) - _PROJECT_KEYS or set(tool) - _TOOL_KEYS:
        raise BuildError("pyproject declares a field this backend does not support")
    name, version = project.get("name"), project.get("version")
    if type(name) is not str or _NAME.fullmatch(name) is None:
        raise BuildError("invalid project name")
    if type(version) is not str or _VERSION.fullmatch(version) is None:
        raise BuildError("version must be MAJOR.MINOR.PATCH")
    if project.get("dependencies", []) != []:
        raise BuildError("these distributions are dependency-free")
    for key in ("description", "requires-python", "license"):
        if type(project.get(key)) is not str or not project[key]:
            raise BuildError(f"{key} is required")
    licenses = project.get("license-files")
    classifiers = project.get("classifiers", [])
    if (type(licenses) is not list or not licenses
            or any(type(item) is not str or "/" in item or not (root / item).is_file() for item in licenses)):
        raise BuildError("license-files must name top-level files")
    if type(classifiers) is not list or any(type(item) is not str for item in classifiers):
        raise BuildError("classifiers must be strings")
    package_dir, packages = tool.get("package-dir"), tool.get("packages")
    if (type(package_dir) is not str or "/" in package_dir or not (root / package_dir).is_dir()
            or type(packages) is not list or not packages
            or any(type(item) is not str or _MODULE.fullmatch(item) is None for item in packages)):
        raise BuildError("invalid [tool.deeptwin-build]")
    return {
        "name": name, "version": version, "description": project["description"],
        "requires_python": project["requires-python"], "license": project["license"],
        "license_files": sorted(licenses), "classifiers": list(classifiers),
        "package_dir": package_dir, "packages": sorted(packages),
    }


def _distribution(project):
    return project["name"].replace("-", "_")


def _metadata(project):
    lines = [
        "Metadata-Version: 2.4",
        f"Name: {project['name']}",
        f"Version: {project['version']}",
        f"Summary: {project['description']}",
        f"License-Expression: {project['license']}",
        *(f"License-File: {name}" for name in project["license_files"]),
        *(f"Classifier: {item}" for item in project["classifiers"]),
        f"Requires-Python: {project['requires_python']}",
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _package_files(project):
    """Return (archive path, bytes) for each package source file, sorted."""

    base = _root() / project["package_dir"]
    files = []
    for package in project["packages"]:
        directory = base / package
        if not (directory / "__init__.py").is_file():
            raise BuildError(f"package {package} has no __init__.py")
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise BuildError("symbolic links are not packaged")
            if "__pycache__" in path.parts or not path.is_file():
                continue
            if path.suffix not in {".py", ".json", ".typed"}:
                raise BuildError(f"unexpected package file {path.name}")
            files.append((path.relative_to(base).as_posix(), path.read_bytes()))
    return files


def _epoch():
    value = os.environ.get("SOURCE_DATE_EPOCH")
    return max(_ZIP_EPOCH, int(value)) if value and value.isdecimal() else _ZIP_EPOCH


def _record_hash(data):
    digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
    return f"sha256={digest}"


def _dist_info_files(project):
    dist_info = f"{_distribution(project)}-{project['version']}.dist-info"
    wheel = (f"Wheel-Version: 1.0\nGenerator: {_GENERATOR}\nRoot-Is-Purelib: true\n"
             "Tag: py3-none-any\n").encode("ascii")
    files = [(f"{dist_info}/METADATA", _metadata(project)), (f"{dist_info}/WHEEL", wheel)]
    for name in project["license_files"]:
        files.append((f"{dist_info}/licenses/{name}", (_root() / name).read_bytes()))
    return dist_info, files


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    project = _project()
    dist_info, files = _dist_info_files(project)
    for name, data in files:
        target = Path(metadata_directory) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return dist_info


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    project = _project()
    dist_info, metadata = _dist_info_files(project)
    entries = _package_files(project) + metadata
    record = "".join(f"{name},{_record_hash(data)},{len(data)}\n" for name, data in entries)
    record += f"{dist_info}/RECORD,,\n"
    entries.append((f"{dist_info}/RECORD", record.encode("utf-8")))
    filename = f"{_distribution(project)}-{project['version']}-py3-none-any.whl"
    stamp = time.gmtime(_epoch())[:6]
    with zipfile.ZipFile(Path(wheel_directory) / filename, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            info = zipfile.ZipInfo(name, date_time=stamp)
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return filename


def _sdist_sources(project):
    root = _root()
    names = ["pyproject.toml", *project["license_files"], "_build/deeptwin_build_backend.py"]
    files = [(name, (root / name).read_bytes()) for name in names]
    files += [(f"{project['package_dir']}/{name}", data) for name, data in _package_files(project)]
    return sorted(files)


def build_sdist(sdist_directory, config_settings=None):
    project = _project()
    top = f"{_distribution(project)}-{project['version']}"
    entries = [("PKG-INFO", _metadata(project)), *_sdist_sources(project)]
    filename = f"{top}.tar.gz"
    epoch = _epoch()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        expanded = set()
        for name, _ in entries:
            parent = Path(top, name).parent
            while parent.as_posix() != ".":
                expanded.add(parent.as_posix())
                parent = parent.parent
        for directory in sorted(expanded):
            info = tarfile.TarInfo(directory)
            info.type, info.mode, info.mtime = tarfile.DIRTYPE, 0o755, epoch
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info)
        for name, data in entries:
            info = tarfile.TarInfo(f"{top}/{name}")
            info.size, info.mode, info.mtime = len(data), 0o644, epoch
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
    with (open(Path(sdist_directory) / filename, "wb") as target,
          gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=epoch) as compressed):
        compressed.write(buffer.getvalue())
    return filename
