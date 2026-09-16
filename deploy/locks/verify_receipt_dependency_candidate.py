"""Verify the inert control-plane receipt dependency candidate."""

from __future__ import annotations

import hashlib
import json
import stat
from copy import deepcopy
from pathlib import Path
from typing import Any

from deploy.locks.verify_build_inputs import parse_lock

ERROR_TEXT = "receipt_dependency_candidate_invalid"
SCHEMA_VERSION = "deeptwin-control-receipt-dependency-candidate-v1"
ADDENDUM_PATH = "deploy/manifests/python-wheel-artifacts-receipt-v1.addendum.json"
LOCK_PATH = "deploy/locks/requirements-control-plane-receipt-v1-linux.lock"
BASE_LOCK_PATH = "deploy/locks/requirements-control-plane-linux.lock"
ROOTS_PATH = "deploy/locks/service-roots.json"
WHEELS_PATH = "deploy/manifests/python-wheel-artifacts.json"
BASE_INPUTS = {
    BASE_LOCK_PATH: (
        2077,
        "66ced7fca949d303db10df2802f7b3a8b533d1dc7175d1edf30fe7f2a36fcb47",
    ),
    ROOTS_PATH: (
        3714,
        "5feea78f28397217f2afdc1f51b41a3a3be916b4a0f3dd59f9b078f349e9150f",
    ),
    "deploy/manifests/build-input-lock.json": (
        27290,
        "212eb478026a2e38b40d882c2525fcee6a3945ed258dbb0d89b615489e62e0bd",
    ),
    WHEELS_PATH: (
        201104,
        "8d14cbc3b0acd9bc35773b3658c620409ef5e2ad3f9101b35395a740d4a85029",
    ),
}
EXPECTED_KEYS = {
    "schema_version",
    "status",
    "service",
    "consumers",
    "runtime",
    "target_platforms",
    "base_inputs",
    "added_direct_roots",
    "service_lock",
    "artifacts",
}
EXPECTED_RUNTIME = {
    "implementation": "CPython",
    "python_version": "3.12.14",
    "abi": "cp312",
    "glibc_floor": "2.28",
}
EXPECTED_TARGETS = [
    {"os": "linux", "architecture": "amd64"},
    {"os": "linux", "architecture": "arm64"},
]
EXPECTED_BASE_ROOTS = [
    "fastapi==0.141.1",
    "uvicorn==0.52.4",
    "pydantic==2.13.5",
    "argon2-cffi==25.1.0",
]
EXPECTED_PYNACL_HASHES = {
    "46065496ab748469cdd999246d17e301b2c24ae2fdf739132e580a0e94c94a87",
    "8a66d6fb6ae7661c58995f9c6435bda2b1e68b54b598a6a10247bfcdadac996c",
}
PLATFORMS = ("amd64", "arm64")
MAX_ADDENDUM_BYTES = 65_536
MAX_LOCK_BYTES = 16_384
MAX_DEPTH = 16
MAX_ITEMS = 4_000
MAX_STRING_BYTES = 4_096
MAX_INTEGER = (1 << 63) - 1


class ReceiptDependencyError(ValueError):
    """A safe, fixed candidate-validation failure."""

    def __init__(self) -> None:
        super().__init__(ERROR_TEXT)
        self.code = ERROR_TEXT


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read_regular(root: Path, relative: str, maximum: int) -> bytes:
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ValueError("candidate input path is not a descendant")
    parent = root
    for component in relative_path.parts[:-1]:
        parent /= component
        parent_info = parent.lstat()
        if stat.S_ISLNK(parent_info.st_mode) or not stat.S_ISDIR(
            parent_info.st_mode
        ):
            raise ValueError("candidate input ancestor is not a real directory")
    path = parent / relative_path.name
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ValueError("candidate input is not a regular file")
    if info.st_size > maximum:
        raise ValueError("candidate input is too large")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError("candidate input is too large")
    return raw


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_float(_: str) -> None:
    raise ValueError("JSON floats are forbidden")


def _reject_constant(_: str) -> None:
    raise ValueError("non-finite JSON numbers are forbidden")


def _decode_json(raw: bytes) -> Any:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError("UTF-8 BOM is forbidden")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_strict_object,
        parse_float=_reject_float,
        parse_constant=_reject_constant,
    )


def _validate_addendum_tree(value: Any, *, depth: int = 0) -> int:
    if depth > MAX_DEPTH:
        raise ValueError("JSON depth limit exceeded")
    if value is None or type(value) is bool:
        return 1
    if type(value) is int:
        if not 0 <= value <= MAX_INTEGER:
            raise ValueError("JSON integer is outside the unsigned 63-bit domain")
        return 1
    if type(value) is str:
        if len(value.encode("utf-8")) > MAX_STRING_BYTES:
            raise ValueError("JSON string limit exceeded")
        return 1
    if type(value) is list:
        count = 1
        for item in value:
            count += _validate_addendum_tree(item, depth=depth + 1)
            if count > MAX_ITEMS:
                raise ValueError("JSON item limit exceeded")
        return count
    if type(value) is dict:
        count = 1
        for key, item in value.items():
            count += _validate_addendum_tree(key, depth=depth + 1)
            count += _validate_addendum_tree(item, depth=depth + 1)
            if count > MAX_ITEMS:
                raise ValueError("JSON item limit exceeded")
        return count
    raise ValueError("unsupported JSON value")


def _exact(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(
            _exact(left[key], right[key]) for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _exact(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return bool(left == right)


def _expected_base_refs() -> list[dict[str, Any]]:
    return [
        {"path": path, "sha256": digest, "size_bytes": size}
        for path, (size, digest) in BASE_INPUTS.items()
    ]


def _validate_addendum_shape(
    addendum: Any, lock_raw: bytes, wheel_manifest: dict[str, Any]
) -> None:
    if type(addendum) is not dict or set(addendum) != EXPECTED_KEYS:
        raise ValueError("addendum root fields changed")
    fixed_fields = {
        "schema_version": SCHEMA_VERSION,
        "status": "candidate_not_release_qualified",
        "service": "control-plane",
        "consumers": ["control-plane"],
        "runtime": EXPECTED_RUNTIME,
        "target_platforms": EXPECTED_TARGETS,
        "base_inputs": _expected_base_refs(),
        "added_direct_roots": ["pynacl==1.6.2"],
    }
    for field, expected in fixed_fields.items():
        if not _exact(addendum[field], expected):
            raise ValueError("fixed addendum field changed")
    if not _exact(wheel_manifest.get("runtime"), EXPECTED_RUNTIME):
        raise ValueError("base runtime changed")
    if not _exact(wheel_manifest.get("target_platforms"), EXPECTED_TARGETS):
        raise ValueError("base target platforms changed")
    expected_lock = {
        "path": LOCK_PATH,
        "sha256": _digest(lock_raw),
        "size_bytes": len(lock_raw),
        "package_count": 18,
    }
    if not _exact(addendum["service_lock"], expected_lock):
        raise ValueError("candidate lock reference changed")


def _expected_candidate_artifacts(
    wheel_manifest: dict[str, Any]
) -> list[dict[str, Any]]:
    expected: list[dict[str, Any]] = []
    for architecture in PLATFORMS:
        matches = [
            artifact
            for artifact in wheel_manifest.get("artifacts", [])
            if type(artifact) is dict
            and artifact.get("name") == "pynacl"
            and artifact.get("version") == "1.6.2"
            and artifact.get("wheel", {}).get("platform")
            == {"os": "linux", "architecture": architecture}
            and artifact.get("usage")
            == [
                {
                    "service": "provider",
                    "os": "linux",
                    "architecture": architecture,
                }
            ]
        ]
        if len(matches) != 1:
            raise ValueError("base PyNaCl platform record changed")
        copied = deepcopy(matches[0])
        copied["usage"] = [
            {
                "service": "control-plane",
                "os": "linux",
                "architecture": architecture,
            }
        ]
        expected.append(copied)
    return expected


def _validate_lock_delta(
    root: Path,
    roots: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    base_lock = parse_lock(root / BASE_LOCK_PATH)
    candidate_lock = parse_lock(root / LOCK_PATH)
    if set(candidate_lock) != set(base_lock) | {"pynacl"}:
        raise ValueError("candidate lock package delta changed")
    for name, pin in base_lock.items():
        if not _exact(candidate_lock.get(name), pin):
            raise ValueError("candidate changed a base pin")
    pynacl = candidate_lock.get("pynacl")
    if (
        type(pynacl) is not dict
        or pynacl.get("version") != "1.6.2"
        or pynacl.get("hashes") != EXPECTED_PYNACL_HASHES
    ):
        raise ValueError("candidate PyNaCl pin changed")
    control_roots = roots.get("services", {}).get("control-plane")
    if not _exact(control_roots, EXPECTED_BASE_ROOTS):
        raise ValueError("base control-plane roots changed")
    for requirement in (*EXPECTED_BASE_ROOTS, "pynacl==1.6.2"):
        name, version = requirement.split("==", 1)
        if candidate_lock.get(name, {}).get("version") != version:
            raise ValueError("candidate direct root is absent")
    return candidate_lock


def _select_base_platform_records(
    wheel_manifest: dict[str, Any], architecture: str
) -> list[dict[str, Any]]:
    usage = {
        "service": "control-plane",
        "os": "linux",
        "architecture": architecture,
    }
    return [
        artifact
        for artifact in wheel_manifest.get("artifacts", [])
        if type(artifact) is dict
        and type(artifact.get("usage")) is list
        and any(_exact(item, usage) for item in artifact["usage"])
    ]


def _validate_platform_closures(
    wheel_manifest: dict[str, Any],
    candidate_artifacts: list[dict[str, Any]],
    candidate_lock: dict[str, dict[str, Any]],
) -> None:
    combined_hashes = {name: set() for name in candidate_lock}
    for index, architecture in enumerate(PLATFORMS):
        selected = _select_base_platform_records(wheel_manifest, architecture)
        selected.append(candidate_artifacts[index])
        by_name: dict[str, dict[str, Any]] = {}
        for artifact in selected:
            name = artifact.get("name")
            if type(name) is not str or name in by_name:
                raise ValueError("platform closure has a duplicate package")
            expected_usage = {
                "service": "control-plane",
                "os": "linux",
                "architecture": architecture,
            }
            if not any(
                _exact(item, expected_usage) for item in artifact.get("usage", [])
            ):
                raise ValueError("platform closure usage changed")
            wheel_platform = artifact.get("wheel", {}).get("platform")
            if wheel_platform not in (
                {"os": "any", "architecture": "any"},
                {"os": "linux", "architecture": architecture},
            ):
                raise ValueError("wheel platform does not match usage")
            by_name[name] = artifact
        if set(by_name) != set(candidate_lock):
            raise ValueError("platform closure names changed")
        for name, artifact in by_name.items():
            pin = candidate_lock[name]
            if artifact.get("version") != pin["version"]:
                raise ValueError("platform closure version changed")
            digest = artifact.get("sha256")
            if type(digest) is not str or digest not in pin["hashes"]:
                raise ValueError("platform artifact is absent from the lock")
            combined_hashes[name].add(digest)
    for name, hashes in combined_hashes.items():
        if hashes != candidate_lock[name]["hashes"]:
            raise ValueError("candidate lock has an unused hash")


def _verify_candidate(root: Path) -> dict[str, Any]:
    base_raw: dict[str, bytes] = {}
    for relative, (size, digest) in BASE_INPUTS.items():
        raw = _read_regular(root, relative, size)
        if len(raw) != size or _digest(raw) != digest:
            raise ValueError("historical base input changed")
        base_raw[relative] = raw

    roots = _decode_json(base_raw[ROOTS_PATH])
    wheel_manifest = _decode_json(base_raw[WHEELS_PATH])
    if type(roots) is not dict or type(wheel_manifest) is not dict:
        raise ValueError("historical metadata root changed")

    addendum_raw = _read_regular(root, ADDENDUM_PATH, MAX_ADDENDUM_BYTES)
    lock_raw = _read_regular(root, LOCK_PATH, MAX_LOCK_BYTES)
    addendum = _decode_json(addendum_raw)
    if _validate_addendum_tree(addendum) > MAX_ITEMS:
        raise ValueError("JSON item limit exceeded")
    _validate_addendum_shape(addendum, lock_raw, wheel_manifest)

    candidate_lock = _validate_lock_delta(root, roots)
    expected_artifacts = _expected_candidate_artifacts(wheel_manifest)
    if not _exact(addendum["artifacts"], expected_artifacts):
        raise ValueError("candidate artifact records changed")
    _validate_platform_closures(
        wheel_manifest, expected_artifacts, candidate_lock
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "candidate_not_release_qualified",
        "service": "control-plane",
        "package_count": 18,
        "target_platforms": ["linux/amd64", "linux/arm64"],
        "lock_sha256": _digest(lock_raw),
        "addendum_sha256": _digest(addendum_raw),
    }


def verify_candidate(root: Path) -> dict[str, Any]:
    """Validate repository-local candidate inputs and return inert metadata."""

    try:
        if not isinstance(root, Path):
            raise TypeError("root must be a Path")
        anchor = root.resolve(strict=True)
        if not stat.S_ISDIR(anchor.lstat().st_mode):
            raise ValueError("root must resolve to a directory")
        return _verify_candidate(anchor)
    except ReceiptDependencyError:
        raise
    except (
        AttributeError,
        IndexError,
        KeyError,
        OSError,
        RecursionError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as exc:
        raise ReceiptDependencyError() from exc


def main() -> int:
    try:
        result = verify_candidate(Path(__file__).resolve().parents[2])
    except ReceiptDependencyError:
        print(ERROR_TEXT)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
