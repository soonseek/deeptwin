"""Strict bounded Linux mount observations, without Docker provenance claims."""

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import DeploymentSourceError, DeploymentSourceUnavailable

LIMIT = 1048576


def native_platform():
    if platform.system() != "Linux":
        raise DeploymentSourceUnavailable()
    result = {
        "x86_64": "linux/amd64",
        "aarch64": "linux/arm64",
        "arm64": "linux/arm64",
    }.get(platform.machine())
    if result is None:
        raise DeploymentSourceUnavailable()
    return result


def _decode(value):
    escapes = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}
    result = ""
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\":
            code = value[index + 1 : index + 4]
            if code not in escapes:
                raise DeploymentSourceError()
            result += escapes[code]
            index += 4
        else:
            if ord(char) < 33 or ord(char) == 127:
                raise DeploymentSourceError()
            result += char
            index += 1
    return result


def _path(value):
    decoded = _decode(value)
    path = Path(decoded)
    if (
        not path.is_absolute()
        or str(path) != decoded
        or ".." in path.parts
        or path.anchor != "/"
    ):
        raise DeploymentSourceError()
    return path


def _positive(value):
    if re.fullmatch(r"[1-9][0-9]{0,18}", value) is None or int(value) > 2**63 - 1:
        raise DeploymentSourceError()
    return int(value)


def _options(value):
    result = value.split(",")
    if (
        len(result) > 128
        or len(set(result)) != len(result)
        or any(not item for item in result)
    ):
        raise DeploymentSourceError()
    for item in result:
        _decode(item)
    return tuple(sorted(result))


@dataclass(frozen=True, slots=True)
class Mount:
    mount_id: int
    parent_id: int
    device: str
    root: Path
    mountpoint: Path
    options: tuple[str, ...]
    optional: tuple[str, ...]
    filesystem: str
    source: str
    super_options: tuple[str, ...]

    @property
    def read_only(self):
        return "ro" in self.options


def parse_mountinfo(data):
    if type(data) is not bytes or not 1 <= len(data) <= LIMIT:
        raise DeploymentSourceError()
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeError:
        raise DeploymentSourceError() from None
    if lines[-1] == "":
        lines.pop()
    if len(lines) > 4096:
        raise DeploymentSourceError()
    mounts = []
    ids = set()
    points = set()
    for line in lines:
        parts = line.split(" ")
        if (
            not line
            or len(line.encode()) > 8192
            or any(not p for p in parts)
            or parts.count("-") != 1
        ):
            raise DeploymentSourceError()
        sep = parts.index("-")
        if not 6 <= sep <= 22 or len(parts) != sep + 4:
            raise DeploymentSourceError()
        mid, parent = _positive(parts[0]), _positive(parts[1])
        if (
            re.fullmatch(r"(?:0|[1-9][0-9]{0,9}):(?:0|[1-9][0-9]{0,9})", parts[2])
            is None
        ):
            raise DeploymentSourceError()
        root, point, options = _path(parts[3]), _path(parts[4]), _options(parts[5])
        if len({"ro", "rw"} & set(options)) != 1 or mid in ids or point in points:
            raise DeploymentSourceError()
        tags = parts[6:sep]
        keys = []
        for tag in tags:
            if re.fullmatch(r"[a-z_]+(?::[1-9][0-9]{0,18})?", tag) is None:
                raise DeploymentSourceError()
            keys.append(tag.split(":")[0])
        if len(set(keys)) != len(keys):
            raise DeploymentSourceError()
        ids.add(mid)
        points.add(point)
        mounts.append(
            Mount(
                mid,
                parent,
                parts[2],
                root,
                point,
                options,
                tuple(sorted(tags)),
                _decode(parts[sep + 1]),
                _decode(parts[sep + 2]),
                _options(parts[sep + 3]),
            )
        )
    return tuple(sorted(mounts, key=lambda mount: str(mount.mountpoint)))


def read_mountinfo():
    native_platform()
    descriptor = -1
    try:
        descriptor = os.open(
            "/proc/self/mountinfo", os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW
        )
        parts = []
        size = 0
        while size <= LIMIT:
            chunk = os.read(descriptor, min(65536, LIMIT + 1 - size))
            if not chunk:
                break
            parts.append(chunk)
            size += len(chunk)
        return parse_mountinfo(b"".join(parts))
    except OSError:
        raise DeploymentSourceUnavailable() from None
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def containing(mounts, path):
    matches = [m for m in mounts if path.is_relative_to(m.mountpoint)]
    if not matches:
        raise DeploymentSourceError()
    return max(matches, key=lambda m: len(m.mountpoint.parts))


def backing(mount, path):
    return mount.root / path.relative_to(mount.mountpoint)


def verify_device(mount, identity):
    if mount.device != f"{os.major(identity.device)}:{os.minor(identity.device)}":
        raise DeploymentSourceError()


def verify_boundaries(mounts, required, protected):
    """Return only relevant normalized mappings; unrelated mount order is immaterial."""
    observations = {}
    for path, read_only in required.items():
        mount = containing(mounts, path)
        if mount.mountpoint != path or mount.read_only is not read_only:
            raise DeploymentSourceError()
        if any(
            m.mountpoint != path and m.mountpoint.is_relative_to(path) for m in mounts
        ):
            raise DeploymentSourceError()
    for path in dict.fromkeys((*required, *protected)):
        mount = containing(mounts, path)
        observations[path] = (mount, backing(mount, path))
    for path in required:
        mount, root = observations[path]
        for other, (other_mount, other_root) in observations.items():
            if other == path:
                continue
            if (
                other.is_relative_to(path)
                or path.is_relative_to(other)
                or mount.device == other_mount.device
                and (root.is_relative_to(other_root) or other_root.is_relative_to(root))
            ):
                raise DeploymentSourceError()
    return tuple(sorted(observations.items(), key=lambda item: str(item[0])))
