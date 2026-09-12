#!/usr/bin/env python3
"""Fail-closed Codex 0.153.4 minimal runner and offline protocol verifier.

This module intentionally separates three claims:

* each target has separately pinned and signed ``codex``, code-mode host, and
  bubblewrap standalone executables;
* their fixed sibling layout and pinned Debian Bookworm ``/bin/bash`` runtime
  input are exact and contain no implicit rg, zsh, package metadata, or full
  package dependency;
* a captured ``codex exec --json`` stream obeys a bounded JSONL state machine;
* a supervising process owns deadline/cancellation and an isolated CODEX_HOME.

It never performs a login or a model call.  The authentication lifecycle helper
will only run a hash-pinned executable that identifies itself as the explicit
DeepTwin offline fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import lzma
import math
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

HEX64 = re.compile(r"^[0-9a-f]{64}$")
RUNNER_SCHEMA = "deeptwin-managed-runner-build-input-v3"
CODEX_VERSION = "0.153.4"
CODEX_TAG = "rust-v0.153.4"
PLATFORM_TARGETS = {
    "linux/amd64": "x86_64-unknown-linux-musl",
    "linux/arm64": "aarch64-unknown-linux-musl",
}
PLATFORMS = tuple(PLATFORM_TARGETS)
COMPONENTS = ("codex", "codex-code-mode-host", "bubblewrap")
EXPECTED_MINIMAL_RUNNER_INPUT_FILE_COUNT = 17
COMPONENT_MEMBERS = {
    ("linux/amd64", "codex"): "codex-x86_64-unknown-linux-musl",
    ("linux/amd64", "codex-code-mode-host"):
        "codex-code-mode-host-x86_64-unknown-linux-musl",
    ("linux/amd64", "bubblewrap"): "bwrap-x86_64-unknown-linux-musl",
    ("linux/arm64", "codex"): "codex-aarch64-unknown-linux-musl",
    ("linux/arm64", "codex-code-mode-host"):
        "codex-code-mode-host-aarch64-unknown-linux-musl",
    ("linux/arm64", "bubblewrap"): "bwrap-aarch64-unknown-linux-musl",
}
INSTALL_ROOT = "/opt/deeptwin/codex"
INSTALL_PATHS = {
    "codex": f"{INSTALL_ROOT}/bin/codex",
    "codex-code-mode-host": f"{INSTALL_ROOT}/bin/codex-code-mode-host",
    "bubblewrap": f"{INSTALL_ROOT}/bin/bwrap",
}
FIXED_PATH_ENV = f"{INSTALL_ROOT}/bin:/usr/bin:/bin"
CERTIFICATE_IDENTITY = (
    "https://github.com/openai/codex/.github/workflows/"
    "rust-release.yml@refs/tags/rust-v0.153.4"
)
CERTIFICATE_ISSUER = "https://token.actions.githubusercontent.com"
OMITTED_COMPONENTS = ("codex-package.json", "full-package-tar", "ripgrep", "zsh")
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024
MAX_EXECUTABLE_BYTES = 384 * 1024 * 1024
MAX_BUNDLE_BYTES = 1024 * 1024
MAX_BASH_BYTES = 16 * 1024 * 1024
MAX_DEB_BYTES = 16 * 1024 * 1024
MAX_DEB_MEMBER_BYTES = 16 * 1024 * 1024
MAX_DEB_MEMBERS = 16
MAX_DEB_TAR_BYTES = 64 * 1024 * 1024
MAX_DEB_TAR_MEMBERS = 4096
MAX_VERIFIER_BYTES = 256 * 1024 * 1024
COSIGN_RELEASE_PREFIX = (
    "https://github.com/sigstore/cosign/releases/download/v3.1.2/"
)
COSIGN_BOOTSTRAP_IDENTITY = "keyless@projectsigstore.iam.gserviceaccount.com"
COSIGN_BOOTSTRAP_ISSUER = "https://accounts.google.com"
OPENAI_RELEASE_PREFIX = (
    "https://github.com/openai/codex/releases/download/rust-v0.153.4/"
)
SNAPSHOT_ARTIFACT_URL = re.compile(
    r"^https://snapshot\.debian\.org/file/[0-9a-f]{40}$"
)
OCI_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
OCI_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
OCI_LAYER_MEDIA_TYPE = "application/vnd.oci.image.layer.v1.tar+gzip"
BOOKWORM_INDEX = {
    "media_type": OCI_INDEX_MEDIA_TYPE,
    "digest": "sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171",
    "bytes": 5651,
}
BASH_SOURCE_INPUTS = [
    {
        "filename": "bash_5.2.15-2.dsc",
        "url": "https://snapshot.debian.org/file/1c8463de9b96f5e72d178a50c49f80242e48d8c7",
        "bytes": 2317,
        "sha256": "f51753e946af43eb58549c81e03b35a47af9fe6c6364179ccd4ef862b7c3b2d3",
    },
    {
        "filename": "bash_5.2.15.orig.tar.gz",
        "url": "https://snapshot.debian.org/file/87f4eb879578479049306f3b721ff38aa17cfa1d",
        "bytes": 9997221,
        "sha256": "7a315bc0e9d90713159e4390ec1096a41e4f33cd8cc3d1a749a8e5ad56600f51",
    },
    {
        "filename": "bash_5.2.15-2.debian.tar.xz",
        "url": "https://snapshot.debian.org/file/d922d9f78e120a6068105ebfe7c15cbadddc31a0",
        "bytes": 97380,
        "sha256": "998f8ea5b754a734ae7d8306e149c43d713ddfcf49623a036004b729237dbcca",
    },
]


COSIGN_BOOTSTRAP_POLICY: dict[str, Any] = {
    "name": "cosign",
    "version": "3.1.2",
    "certificate_identity": COSIGN_BOOTSTRAP_IDENTITY,
    "certificate_oidc_issuer": COSIGN_BOOTSTRAP_ISSUER,
    "checksum_manifest": {
        "url": f"{COSIGN_RELEASE_PREFIX}cosign_checksums.txt",
        "filename": "cosign_checksums.txt",
        "bytes": 3906,
        "sha256": (
            "3ef5d389c3f508b96025fd1b92744a305c46e95951c91242b57467567d5622db"
        ),
        "sigstore_bundle": {
            "url": f"{COSIGN_RELEASE_PREFIX}cosign_checksums.txt.sigstore.json",
            "filename": "cosign_checksums.txt.sigstore.json",
            "bytes": 6578,
            "sha256": (
                "be73ee422be126a70190ee24bf88a1b078cde1f954f076ddf9c0901de4136362"
            ),
            "verified": True,
        },
        "signature_chain_verified": True,
    },
    "release_build_verifiers": [
        {
            "platform": "linux/amd64",
            "executable": {
                "url": f"{COSIGN_RELEASE_PREFIX}cosign-linux-amd64",
                "filename": "cosign-linux-amd64",
                "bytes": 141150460,
                "sha256": (
                    "f7622ed3cf22e55e1ae6377c080979ff77a22da9981c11df222a2e444991e7cf"
                ),
                "mode": "0755",
            },
            "sigstore_bundle": {
                "url": f"{COSIGN_RELEASE_PREFIX}cosign-linux-amd64.sigstore.json",
                "filename": "cosign-linux-amd64.sigstore.json",
                "bytes": 6433,
                "sha256": (
                    "fdaa1c168d67041cd0d8f5782f8136ac5d148827b6911ba8bb577cbc7e13de2c"
                ),
                "verified": True,
            },
            "checksum_manifest_match": True,
            "signature_chain_verified": True,
        },
        {
            "platform": "linux/arm64",
            "executable": {
                "url": f"{COSIGN_RELEASE_PREFIX}cosign-linux-arm64",
                "filename": "cosign-linux-arm64",
                "bytes": 132737437,
                "sha256": (
                    "90e7ae0b5dfd60f20816b52c012addf7fc055ebcc7bea4ce81c428ca8518c302"
                ),
                "mode": "0755",
            },
            "sigstore_bundle": {
                "url": f"{COSIGN_RELEASE_PREFIX}cosign-linux-arm64.sigstore.json",
                "filename": "cosign-linux-arm64.sigstore.json",
                "bytes": 6543,
                "sha256": (
                    "e5cb6bc66d703b69c3dc629e77a600cbb67ca6e4bd81e7d690f2c52a73247d10"
                ),
                "verified": True,
            },
            "checksum_manifest_match": True,
            "signature_chain_verified": True,
        },
    ],
    "audit_observations": [
        {
            "label": "darwin-arm64-audit-only",
            "platform": "darwin/arm64",
            "eligible_for_release_build": False,
            "executable": {
                "url": f"{COSIGN_RELEASE_PREFIX}cosign-darwin-arm64",
                "filename": "cosign-darwin-arm64",
                "bytes": 139584002,
                "sha256": (
                    "dec1c3f802320b19c2fbcf2dc7bcfb3f258e1c181a046c23a1a074bdf932f10a"
                ),
                "mode": "0755",
            },
            "sigstore_bundle": {
                "url": f"{COSIGN_RELEASE_PREFIX}cosign-darwin-arm64.sigstore.json",
                "filename": "cosign-darwin-arm64.sigstore.json",
                "bytes": 6574,
                "sha256": (
                    "ffbec621bbef3c1e02f05633e74892bd874f2b1157ea57bcb0c7449113966500"
                ),
                "verified": True,
            },
            "checksum_manifest_match": True,
            "signature_chain_verified": True,
        }
    ],
}


# T089 has frozen every current child build input. These release blockers are
# deliberately downstream: they cannot make the input lock depend on work that
# consumes the lock, and they may remain present when ``locked=True``.
EXPECTED_BUILD_INPUT_BLOCKERS: tuple[dict[str, str], ...] = ()
EXPECTED_DOWNSTREAM_RELEASE_BLOCKERS: tuple[dict[str, str], ...] = (
    {
        "blocker_id": "codex-runner-worker-isolation",
        "owner_task": "T018",
        "gate_id": "t018-managed-runner-worker-isolation",
        "summary": "Managed-runner worker and IPC isolation remain unqualified.",
    },
    {
        "blocker_id": "codex-provider-authority-recovery",
        "owner_task": "T025",
        "gate_id": "t025-provider-authority-recovery",
        "summary": "Provider authorization, secret custody, and restart recovery remain open.",
    },
    {
        "blocker_id": "codex-security-provenance-qualification",
        "owner_task": "T079",
        "gate_id": "t079-integrated-security-qualification",
        "summary": "Integrated isolation and unsigned upstream provenance risk remain unqualified.",
    },
    {
        "blocker_id": "codex-final-image-runtime-canaries",
        "owner_task": "T081",
        "gate_id": "t081-final-image-runtime-canaries",
        "summary": "Final dual-platform runner images and sandbox canaries remain open.",
    },
    {
        "blocker_id": "codex-packaged-provenance-sbom",
        "owner_task": "T082",
        "gate_id": "t082-packaged-provenance-sbom",
        "summary": "Packaged SBOM, source-to-binary linkage, and authorized signing remain open.",
    },
    {
        "blocker_id": "codex-redistribution-publication-approval",
        "owner_task": "T084",
        "gate_id": "t084-redistribution-publication-approval",
        "summary": "Third-party notices, redistribution, legal, and publication approval remain open.",
    },
    {
        "blocker_id": "codex-native-subscription-qualification",
        "owner_task": "T088",
        "gate_id": "t088-native-subscription-qualification",
        "summary": "Native dual-platform and authorized subscription-runner qualification remain open.",
    },
)


def _pinned_runtime_image(
    *,
    source_revision: str,
    manifest_digest: str,
    manifest_bytes: int,
    config_digest: str,
    config_bytes: int,
    layer_digest: str,
    layer_bytes: int,
    architecture: str,
    package_bytes: int,
    package_sha256: str,
    package_snapshot_sha1: str,
    member_bytes: int,
    member_sha256: str,
) -> dict[str, Any]:
    return {
        "distribution": "debian",
        "suite": "bookworm",
        "repository": "docker.io/library/debian",
        "tag": "bookworm-20260824-slim",
        "created_at": "2026-08-24T00:00:00Z",
        "snapshot": "20260824T000000Z",
        "source_repository": (
            "https://github.com/debuerreotype/docker-debian-artifacts.git"
        ),
        "source_revision": source_revision,
        "index": dict(BOOKWORM_INDEX),
        "manifest": {
            "media_type": OCI_MANIFEST_MEDIA_TYPE,
            "digest": manifest_digest,
            "bytes": manifest_bytes,
        },
        "config": {
            "media_type": OCI_CONFIG_MEDIA_TYPE,
            "digest": config_digest,
            "bytes": config_bytes,
        },
        "layers": [{
            "position": 1,
            "media_type": OCI_LAYER_MEDIA_TYPE,
            "digest": layer_digest,
            "bytes": layer_bytes,
        }],
        "bash": {
            "package": "bash",
            "package_version": "5.2.15-2+b13",
            "source_package": "bash",
            "source_version": "5.2.15-2",
            "installed_path": "/bin/bash",
            "mode": "0755",
            "binary_package": {
                "filename": f"bash_5.2.15-2+b13_{architecture}.deb",
                "url": (
                    "https://snapshot.debian.org/file/"
                    f"{package_snapshot_sha1}"
                ),
                "bytes": package_bytes,
                "sha256": package_sha256,
            },
            "package_member": {
                "path": "bin/bash",
                "installed_path": "/bin/bash",
                "bytes": member_bytes,
                "sha256": member_sha256,
                "mode": "0755",
            },
            "license_member": {
                "path": "usr/share/doc/bash/copyright",
                "bytes": 9764,
                "sha256": (
                    "06319d84c3e5ed096036f6a9310a030c7e84e50dff2b8a6792285c83ec0ada73"
                ),
            },
            "source_inputs": [dict(source) for source in BASH_SOURCE_INPUTS],
        },
    }


CODEX_RUNTIME_INPUTS = {
    "linux/amd64": _pinned_runtime_image(
        source_revision="bae6d64d90b4068b09ff9d8b564c2773ef5d8d83",
        manifest_digest=(
            "sha256:5ae3c39ebd15e229dcedd5cee596b2497182493d41ff162e824ba13fc1b2b867"
        ),
        manifest_bytes=1021,
        config_digest=(
            "sha256:160466e67bb85a4099d9d9c2356b4a6a64747b281a22c142efbd4539db1b8525"
        ),
        config_bytes=453,
        layer_digest=(
            "sha256:a8ac7f6c67abc236e4c745052c404112b8fab6fe8ac3a329d1ef3b867ad67c71"
        ),
        layer_bytes=28232655,
        architecture="amd64",
        package_bytes=1490652,
        package_sha256=(
            "82130bb6a560cd2a7234d8018baf73f188f5dd56413d5aa0accc987b2197a6a1"
        ),
        package_snapshot_sha1="c3d560d63523ba240e565376b57724de72e89e6b",
        member_bytes=1265648,
        member_sha256=(
            "55b89ab22bee4792a210f493a53fb066accd5d30b69837c28d98be5ff863efcf"
        ),
    ),
    "linux/arm64": _pinned_runtime_image(
        source_revision="f73bd086e8d0e5e1c8b838ccc442bf24eb3ea205",
        manifest_digest=(
            "sha256:6bd27d44e6c32a66bbd72d7cb2b76a8ae3497ec2e5274a81abd1b37f6013fa1f"
        ),
        manifest_bytes=1041,
        config_digest=(
            "sha256:32d322b19846336d25f755f73618a448e3621982d52c48064e95af8b3dcbc2d9"
        ),
        config_bytes=468,
        layer_digest=(
            "sha256:75782e20ea1f4a9d9259bc20a5ecbbea8d5943bf5370bf0f5727900728f1cc9a"
        ),
        layer_bytes=28117289,
        architecture="arm64",
        package_bytes=1444200,
        package_sha256=(
            "fdb470b5ec1773b90014138bfc1deda4505c1c23e7f5731e8b527c636ac03385"
        ),
        package_snapshot_sha1="2b5075a3983b5d1b4d6288bcccf0371ebc0fccd3",
        member_bytes=1346480,
        member_sha256=(
            "f5918390c5b15392ad8835e8368a79c1ee9937fbb19f2349cccf5d4524183299"
        ),
    ),
}
# The official Bookworm bash package contains this one safe compatibility link.
# Every other symlink and every hard link remains forbidden by the package parser.
PERMITTED_BASH_SYMLINKS = {"bin/rbash": "bash"}
OFFLINE_FIXTURE_VERSION = b"deeptwin-offline-codex-fixture 1\n"
TERMINAL_EVENTS = {"turn.completed", "turn.failed"}
EVENT_TYPES = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "error",
}
ITEM_TYPES = {
    "agent_message",
    "reasoning",
    "command_execution",
    "file_change",
    "mcp_tool_call",
    "collab_tool_call",
    "web_search",
    "todo_list",
    "error",
}
SENSITIVE_ENV_FRAGMENT = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|CREDENTIAL|API_KEY|AUTH)", re.IGNORECASE
)
SAFE_SANDBOXES = {"read-only", "workspace-write"}
SAFE_APPROVAL_POLICIES = {"never"}


class VerificationError(ValueError):
    """The candidate did not meet a fail-closed verification invariant."""


def _require_regular_input(path: Path, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationError(f"{label}: input is unavailable: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise VerificationError(f"{label}: input must be a regular non-symlink file")
    return info


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise VerificationError(f"non-finite JSON number is forbidden: {value}")


def _bounded_json_int(value: str) -> int:
    if len(value.lstrip("-")) > 128:
        raise VerificationError("JSON integer exceeds 128 digits")
    return int(value)


def _bounded_json_float(value: str) -> float:
    if len(value) > 128:
        raise VerificationError("JSON float representation exceeds 128 bytes")
    result = float(value)
    if not math.isfinite(result):
        raise VerificationError("non-finite JSON float is forbidden")
    return result


def _strict_json_loads(value: str | bytes) -> Any:
    return json.loads(
        value,
        object_pairs_hook=_strict_object,
        parse_constant=_reject_json_constant,
        parse_int=_bounded_json_int,
        parse_float=_bounded_json_float,
    )


def load_json(path: Path) -> dict[str, Any]:
    _require_regular_input(path, str(path))
    try:
        value = _strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise VerificationError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise VerificationError(f"{path}: JSON root must be an object")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise VerificationError(f"{label}: exact lowercase SHA-256 required")
    return value


def _require_positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise VerificationError(f"{label}: positive integer required")
    return value


def _require_bounded_positive_int(value: Any, label: str, maximum: int) -> int:
    result = _require_positive_int(value, label)
    if result > maximum:
        raise VerificationError(f"{label}: exceeds bounded maximum {maximum}")
    return result


def _exact_mapping(value: Any, fields: set[str] | frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != set(fields):
        raise VerificationError(f"{label}: exact fields required")
    return value


def _bounded_text(value: Any, label: str, maximum: int = 512) -> str:
    if type(value) is not str or not value:
        raise VerificationError(f"{label}: nonempty text required")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise VerificationError(f"{label}: invalid Unicode") from exc
    if (len(encoded) > maximum
            or any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise VerificationError(f"{label}: invalid bounded text")
    return value


def _artifact_filename(value: Any, label: str) -> str:
    text = _bounded_text(value, label, 256)
    if PurePosixPath(text).name != text or text in {".", ".."} or "\\" in text:
        raise VerificationError(f"{label}: basename required")
    return text


def _https_asset_url(value: Any, filename: str, label: str) -> str:
    text = _bounded_text(value, label, 2048)
    if not text.startswith("https://") or text.rsplit("/", 1)[-1] != filename:
        raise VerificationError(f"{label}: HTTPS URL must bind the declared filename")
    return text


def _safe_tar_name(name: str) -> str:
    if not isinstance(name, str) or not name or "\\" in name or "\x00" in name:
        raise VerificationError(f"unsafe archive member name: {name!r}")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise VerificationError(f"unsafe archive member name: {name!r}")
    canonical = path.as_posix()
    if canonical != name.rstrip("/"):
        raise VerificationError(f"noncanonical archive member name: {name!r}")
    return canonical


def _read_tar_member(archive: tarfile.TarFile, info: tarfile.TarInfo) -> bytes:
    stream = archive.extractfile(info)
    if stream is None:
        raise VerificationError(f"archive member is unreadable: {info.name}")
    data = stream.read(info.size + 1)
    if len(data) != info.size:
        raise VerificationError(f"archive member size changed while reading: {info.name}")
    return data


def _json_depth(value: Any, limit: int) -> int:
    stack: list[tuple[Any, int]] = [(value, 1)]
    deepest = 0
    while stack:
        current, depth = stack.pop()
        deepest = max(deepest, depth)
        if depth > limit:
            raise VerificationError(f"JSON nesting exceeds {limit}")
        if isinstance(current, dict):
            stack.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
    return deepest


@dataclass(frozen=True)
class JsonlLimits:
    max_total_bytes: int = 4 * 1024 * 1024
    max_line_bytes: int = 512 * 1024
    max_events: int = 4096
    max_depth: int = 32
    max_identifier_bytes: int = 512
    max_error_bytes: int = 64 * 1024


DEFAULT_JSONL_LIMITS = JsonlLimits()


def _require_text(value: Any, label: str, byte_limit: int) -> str:
    if not isinstance(value, str) or not value:
        raise VerificationError(f"{label}: nonempty string required")
    if len(value.encode("utf-8")) > byte_limit:
        raise VerificationError(f"{label}: text exceeds {byte_limit} bytes")
    return value


def _verify_usage(value: Any) -> None:
    if not isinstance(value, dict):
        raise VerificationError("turn.completed.usage must be an object")
    required = {
        "input_tokens",
        "cached_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
    }
    if not required.issubset(value):
        raise VerificationError("turn.completed.usage is incomplete")
    allowed = required | {"cache_write_input_tokens"}
    if not set(value).issubset(allowed):
        raise VerificationError("turn.completed.usage has unknown fields")
    for key, count in value.items():
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise VerificationError(f"turn.completed.usage.{key} must be nonnegative")


def validate_jsonl_bytes(
    data: bytes,
    *,
    require_terminal: bool = True,
    limits: JsonlLimits = DEFAULT_JSONL_LIMITS,
) -> dict[str, Any]:
    """Validate bounded Codex 0.153.4 JSONL and return content-free metadata."""

    if len(data) > limits.max_total_bytes:
        raise VerificationError("JSONL exceeds total byte limit")
    if not data.endswith(b"\n"):
        raise VerificationError("JSONL must end at a newline boundary")
    if b"\r" in data:
        raise VerificationError("JSONL accepts LF delimiters only")
    raw_lines = data[:-1].split(b"\n")
    if len(raw_lines) > limits.max_events:
        raise VerificationError("JSONL exceeds event-count limit")
    if not raw_lines:
        raise VerificationError("JSONL stream is empty")

    events: list[dict[str, Any]] = []
    types: list[str] = []
    for number, raw_bytes in enumerate(raw_lines, 1):
        try:
            raw_line = raw_bytes.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise VerificationError(f"JSONL line {number} is not UTF-8") from exc
        if not raw_line:
            raise VerificationError(f"JSONL line {number} is empty")
        if len(raw_bytes) > limits.max_line_bytes:
            raise VerificationError(f"JSONL line {number} exceeds byte limit")
        try:
            event = _strict_json_loads(raw_line)
        except (json.JSONDecodeError, VerificationError, RecursionError) as exc:
            raise VerificationError(f"JSONL line {number} is invalid: {exc}") from exc
        if not isinstance(event, dict):
            raise VerificationError(f"JSONL line {number} must be an object")
        _json_depth(event, limits.max_depth)
        event_type = event.get("type")
        if event_type not in EVENT_TYPES:
            raise VerificationError(f"JSONL line {number} has unknown event type")
        events.append(event)
        types.append(event_type)

    if types[0] != "thread.started" or types.count("thread.started") != 1:
        raise VerificationError("thread.started must occur exactly once as the first event")
    _require_text(
        events[0].get("thread_id"),
        "thread.started.thread_id",
        limits.max_identifier_bytes,
    )
    if types.count("turn.started") > 1:
        raise VerificationError("only one turn.started is accepted per invocation")

    terminal_positions = [index for index, value in enumerate(types) if value in TERMINAL_EVENTS]
    if len(terminal_positions) > 1:
        raise VerificationError("JSONL contains multiple terminal events")
    if terminal_positions and terminal_positions[0] != len(events) - 1:
        raise VerificationError("terminal event must be the final JSONL event")
    if require_terminal and len(terminal_positions) != 1:
        raise VerificationError("completed invocation lacks one terminal event")

    turn_started = False
    active_items: set[str] = set()
    completed_items: set[str] = set()
    item_types: dict[str, str] = {}
    for number, event in enumerate(events, 1):
        event_type = event["type"]
        if event_type == "turn.started":
            turn_started = True
            continue
        if event_type in TERMINAL_EVENTS:
            if not turn_started:
                raise VerificationError("terminal event precedes turn.started")
            if event_type == "turn.completed":
                _verify_usage(event.get("usage"))
            else:
                error = event.get("error")
                if not isinstance(error, dict):
                    raise VerificationError("turn.failed.error must be an object")
                _require_text(
                    error.get("message"), "turn.failed.error.message", limits.max_error_bytes
                )
            continue
        if event_type == "error":
            _require_text(event.get("message"), "error.message", limits.max_error_bytes)
            continue
        if not event_type.startswith("item."):
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            raise VerificationError(f"JSONL line {number}: item must be an object")
        item_id = _require_text(
            item.get("id"), f"JSONL line {number}: item.id", limits.max_identifier_bytes
        )
        item_type = item.get("type")
        if item_type not in ITEM_TYPES:
            raise VerificationError(f"JSONL line {number}: unknown item type")
        prior_item_type = item_types.setdefault(item_id, item_type)
        if prior_item_type != item_type:
            raise VerificationError(f"item type changed for id: {item_id}")
        if not turn_started and not (
            event_type == "item.completed" and item_type == "error"
        ):
            raise VerificationError("only a completed warning/error item may precede turn.started")
        if event_type == "item.started":
            if item_id in active_items or item_id in completed_items:
                raise VerificationError(f"duplicate item.started id: {item_id}")
            active_items.add(item_id)
        elif event_type == "item.updated":
            if item_id not in active_items:
                raise VerificationError(f"item.updated without item.started: {item_id}")
        else:
            if item_id in completed_items:
                raise VerificationError(f"duplicate item.completed id: {item_id}")
            active_items.discard(item_id)
            completed_items.add(item_id)

    terminal_type = types[terminal_positions[0]] if terminal_positions else None
    if terminal_type is not None and active_items:
        raise VerificationError("terminal event leaves unfinished items")
    return {
        "event_count": len(events),
        "event_types": types,
        "terminal_event": terminal_type,
        "unfinished_item_count": len(active_items),
        "stream_bytes": len(data),
        "stream_sha256": hashlib.sha256(data).hexdigest(),
    }


@dataclass
class _Capture:
    limit: int
    retained: bytearray = field(default_factory=bytearray)
    seen: int = 0
    digest: Any = field(default_factory=hashlib.sha256)
    exceeded: bool = False

    def add(self, chunk: bytes) -> None:
        self.seen += len(chunk)
        self.digest.update(chunk)
        remaining = max(0, self.limit - len(self.retained))
        if remaining:
            self.retained.extend(chunk[:remaining])
        if self.seen > self.limit:
            self.exceeded = True


@dataclass(frozen=True)
class ProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    stdout_seen: int
    stderr_seen: int
    stdout_sha256: str
    stderr_sha256: str
    stop_reason: str | None
    signals_sent: tuple[str, ...]
    elapsed_seconds: float


def isolated_environment(
    codex_home: Path,
    *,
    path: str = FIXED_PATH_ENV,
    extra: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build an allowlisted environment; ambient credentials are never inherited."""

    try:
        home_info = codex_home.lstat()
    except OSError as exc:
        raise VerificationError(f"isolated CODEX_HOME is unavailable: {exc}") from exc
    if stat.S_ISLNK(home_info.st_mode) or not stat.S_ISDIR(home_info.st_mode):
        raise VerificationError("isolated CODEX_HOME must be a non-symlink directory")
    if home_info.st_uid != os.geteuid():
        raise VerificationError("isolated CODEX_HOME must be owned by the runner uid")
    if stat.S_IMODE(home_info.st_mode) != 0o700:
        raise VerificationError("isolated CODEX_HOME must have mode 0700")
    home = codex_home.resolve(strict=True)
    environment = {
        "PATH": path,
        "HOME": str(home),
        "CODEX_HOME": str(home),
        "SHELL": "/bin/bash",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_COLOR": "1",
    }
    for key, value in (extra or {}).items():
        if key in environment or key in {"HOME", "CODEX_HOME"}:
            raise VerificationError(f"environment override is reserved: {key}")
        if SENSITIVE_ENV_FRAGMENT.search(key):
            raise VerificationError(f"sensitive environment injection is forbidden: {key}")
        if not re.fullmatch(r"DEEPTWIN_[A-Z0-9_]+", key):
            raise VerificationError(f"fixture environment key is not allowlisted: {key}")
        if not isinstance(value, str) or "\x00" in value:
            raise VerificationError(f"invalid environment value for {key}")
        environment[key] = value
    return environment


def prepare_isolated_codex_home(parent: Path) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    home = parent / "codex-home"
    home.mkdir(mode=0o700)
    home.chmod(0o700)
    if stat.S_IMODE(home.stat().st_mode) != 0o700:
        raise VerificationError("isolated CODEX_HOME must have mode 0700")
    return home


def credential_file_state(codex_home: Path) -> dict[str, Any]:
    """Inspect credential metadata without opening or hashing credential bytes."""

    path = codex_home / "auth.json"
    try:
        info = path.lstat()
    except FileNotFoundError:
        return {"exists": False}
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise VerificationError("auth.json must be a regular non-symlink file")
    if info.st_uid != os.geteuid():
        raise VerificationError("auth.json must be owned by the runner uid")
    if info.st_nlink != 1:
        raise VerificationError("auth.json must have exactly one hard link")
    mode = stat.S_IMODE(info.st_mode)
    if mode & 0o077:
        raise VerificationError("auth.json must not be accessible to group or others")
    return {"exists": True, "mode": f"{mode:04o}", "bytes_observed": False}


def _signal_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> bool:
    try:
        os.killpg(process.pid, sig)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    stdin_data: bytes = b"",
    timeout_seconds: float = 10.0,
    cancel_after_seconds: float | None = None,
    signal_grace_seconds: float = 0.5,
    stdout_limit: int = 4 * 1024 * 1024,
    stderr_limit: int = 512 * 1024,
) -> ProcessResult:
    """Own a subprocess group, both pipe caps, deadline, cancel and escalation."""

    if not argv or any(not isinstance(value, str) or "\x00" in value for value in argv):
        raise VerificationError("argv must contain non-NUL strings")
    if timeout_seconds <= 0 or signal_grace_seconds <= 0:
        raise VerificationError("process deadlines must be positive")
    if cancel_after_seconds is not None and not (0 <= cancel_after_seconds < timeout_seconds):
        raise VerificationError("cancel_after_seconds must precede timeout")
    if len(stdin_data) > 64 * 1024:
        raise VerificationError("stdin exceeds the 64 KiB runner boundary")
    if stdout_limit <= 0 or stderr_limit <= 0:
        raise VerificationError("capture limits must be positive")

    started = time.monotonic()
    process = subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    assert process.stdin is not None and process.stdout is not None and process.stderr is not None
    stdout = _Capture(stdout_limit)
    stderr = _Capture(stderr_limit)
    selector = selectors.DefaultSelector()
    stdin_view = memoryview(stdin_data)
    stdin_offset = 0
    try:
        selector.register(process.stdout, selectors.EVENT_READ, ("output", stdout))
        selector.register(process.stderr, selectors.EVENT_READ, ("output", stderr))
        if stdin_data:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, ("stdin", None))
        else:
            process.stdin.close()
    except BaseException:
        selector.close()
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
        _signal_process_group(process, signal.SIGKILL)
        process.wait()
        raise
    stop_reason: str | None = None
    signal_stage = 0
    next_signal_at: float | None = None
    hard_drain_at: float | None = None
    signals_sent: list[str] = []

    def close_stdin() -> None:
        if process.stdin is None or process.stdin.closed:
            return
        try:
            selector.unregister(process.stdin)
        except (KeyError, ValueError):
            pass
        process.stdin.close()

    def begin_stop(reason: str, now: float) -> None:
        nonlocal stop_reason, signal_stage, next_signal_at
        if stop_reason is not None:
            return
        stop_reason = reason
        close_stdin()
        if _signal_process_group(process, signal.SIGINT):
            signals_sent.append("SIGINT")
        signal_stage = 1
        next_signal_at = now + signal_grace_seconds

    try:
        while selector.get_map() or process.poll() is None:
            now = time.monotonic()
            elapsed = now - started
            if stop_reason is None:
                if cancel_after_seconds is not None and elapsed >= cancel_after_seconds:
                    begin_stop("cancelled", now)
                elif elapsed >= timeout_seconds:
                    begin_stop("deadline_exceeded", now)

            if (
                stop_reason is not None
                and next_signal_at is not None
                and now >= next_signal_at
            ):
                if signal_stage == 1:
                    if _signal_process_group(process, signal.SIGTERM):
                        signals_sent.append("SIGTERM")
                    signal_stage = 2
                    next_signal_at = now + signal_grace_seconds
                elif signal_stage == 2:
                    if _signal_process_group(process, signal.SIGKILL):
                        signals_sent.append("SIGKILL")
                    signal_stage = 3
                    next_signal_at = None
                    hard_drain_at = now + signal_grace_seconds

            if hard_drain_at is not None and now >= hard_drain_at:
                # A descendant can deliberately create a new session and retain our
                # inherited pipes after the owned group is gone.  Stop draining at a
                # fixed boundary; the production container/cgroup owns that escape.
                break

            wait = 0.05
            wakeups = [value for value in (next_signal_at, hard_drain_at) if value]
            if wakeups:
                wait = max(0.0, min(wait, min(wakeups) - now))
            for key, _ in selector.select(wait):
                kind, capture = key.data
                if kind == "stdin":
                    try:
                        written = os.write(key.fd, stdin_view[stdin_offset:])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError:
                        close_stdin()
                        continue
                    stdin_offset += written
                    if stdin_offset == len(stdin_view):
                        close_stdin()
                    continue
                try:
                    chunk = os.read(key.fd, 64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                capture.add(chunk)
                if (stdout.exceeded or stderr.exceeded) and stop_reason is None:
                    begin_stop("output_limit_exceeded", time.monotonic())

            if signal_stage == 3 and process.poll() is not None and not selector.get_map():
                break
    finally:
        close_stdin()
        selector.close()
        process.stdout.close()
        process.stderr.close()
        if process.poll() is None:
            _signal_process_group(process, signal.SIGKILL)
            try:
                process.wait(timeout=signal_grace_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    exit_code = process.wait()
    elapsed = time.monotonic() - started
    return ProcessResult(
        exit_code=exit_code,
        stdout=bytes(stdout.retained),
        stderr=bytes(stderr.retained),
        stdout_seen=stdout.seen,
        stderr_seen=stderr.seen,
        stdout_sha256=stdout.digest.hexdigest(),
        stderr_sha256=stderr.digest.hexdigest(),
        stop_reason=stop_reason,
        signals_sent=tuple(signals_sent),
        elapsed_seconds=elapsed,
    )


def _verify_declared_artifact(
    path: Path,
    declaration: Mapping[str, Any],
    label: str,
    *,
    require_executable: bool = False,
) -> dict[str, Any]:
    """Verify a regular, non-symlink file against an exact declaration."""

    try:
        info = path.lstat()
    except OSError as exc:
        raise VerificationError(f"{label}: artifact is unavailable: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise VerificationError(f"{label}: artifact must be a regular non-symlink file")
    if info.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o022):
        raise VerificationError(f"{label}: artifact mode is unsafe")
    if require_executable and not info.st_mode & 0o111:
        raise VerificationError(f"{label}: verifier is not executable")
    expected_bytes = _require_positive_int(declaration.get("bytes"), f"{label}.bytes")
    expected_digest = _require_sha256(declaration.get("sha256"), f"{label}.sha256")
    url = declaration.get("url")
    if not isinstance(url, str) or not url or url.rsplit("/", 1)[-1] != path.name:
        raise VerificationError(f"{label}: artifact filename does not match its URL")
    if info.st_size != expected_bytes or sha256_file(path) != expected_digest:
        raise VerificationError(f"{label}: exact bytes changed")
    return {
        "filename": path.name,
        "bytes": expected_bytes,
        "sha256": expected_digest,
    }


_RUNNER_FIELDS = frozenset({
    "schema_version", "status", "version", "tag", "source_commit", "target_platforms",
    "signature_policy", "runtime_layout", "platform_inputs", "omitted_components",
    "runtime_mutation_policy", "build_input_gate", "build_input_blockers",
    "release_gate", "downstream_release_blockers",
})
_SIGNATURE_POLICY_FIELDS = frozenset({
    "offline", "subject_scope", "certificate_identity", "certificate_oidc_issuer",
    "verifier_bootstrap",
})
_VERIFIER_BOOTSTRAP_FIELDS = frozenset({
    "name", "version", "certificate_identity", "certificate_oidc_issuer",
    "checksum_manifest", "release_build_verifiers", "audit_observations",
})
_COSIGN_CHECKSUM_FIELDS = frozenset({
    "url", "filename", "bytes", "sha256", "sigstore_bundle",
    "signature_chain_verified",
})
_COSIGN_VERIFIER_FIELDS = frozenset({
    "platform", "executable", "sigstore_bundle", "checksum_manifest_match",
    "signature_chain_verified",
})
_COSIGN_AUDIT_FIELDS = frozenset({
    "label", "platform", "eligible_for_release_build", "executable",
    "sigstore_bundle", "checksum_manifest_match", "signature_chain_verified",
})
_COSIGN_EXECUTABLE_FIELDS = frozenset({
    "url", "filename", "bytes", "sha256", "mode",
})
_COSIGN_ARTIFACT_FIELDS = frozenset({"url", "filename", "bytes", "sha256"})
_BLOCKER_FIELDS = frozenset({"blocker_id", "owner_task", "gate_id", "summary"})
_LAYOUT_FIELDS = frozenset({
    "install_root", "codex_path", "code_mode_host_path", "bubblewrap_path", "bash_path",
    "path_env", "required_internal_sandbox_profiles", "codex_home_policy",
})
_PLATFORM_FIELDS = frozenset({"platform", "target", "components", "runtime_image"})
_COMPONENT_FIELDS = frozenset({
    "name", "archive", "executable", "sigstore_bundle", "signature_scope",
})
_ARCHIVE_FIELDS = frozenset({"url", "filename", "bytes", "sha256", "member_path"})
_EXECUTABLE_FIELDS = frozenset({"installed_path", "bytes", "sha256", "mode"})
_BUNDLE_FIELDS = frozenset({"url", "filename", "bytes", "sha256", "verified"})
_RUNTIME_IMAGE_FIELDS = frozenset({
    "distribution", "suite", "repository", "tag", "created_at", "snapshot",
    "source_repository", "source_revision", "index", "manifest", "config",
    "layers", "bash",
})
_OCI_DESCRIPTOR_FIELDS = frozenset({"media_type", "digest", "bytes"})
_OCI_LAYER_FIELDS = frozenset({"position", "media_type", "digest", "bytes"})
_BASH_FIELDS = frozenset({
    "package", "package_version", "source_package", "source_version", "installed_path",
    "mode", "binary_package", "package_member", "license_member", "source_inputs",
})
_SNAPSHOT_ARTIFACT_FIELDS = frozenset({"filename", "url", "bytes", "sha256"})
_PACKAGE_MEMBER_FIELDS = frozenset({
    "path", "installed_path", "bytes", "sha256", "mode",
})
_LICENSE_MEMBER_FIELDS = frozenset({"path", "bytes", "sha256"})
_MUTATION_FIELDS = frozenset({
    "browser_download_at_runtime", "model_download_at_runtime", "package_install_at_runtime",
    "package_resolution_at_runtime", "tool_download_at_runtime",
})


def _validate_blocker_records(value: Any, label: str) -> list[dict[str, str]]:
    if type(value) is not list or len(value) > 64:
        raise VerificationError(f"{label}: bounded list required")
    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw_record in enumerate(value):
        record = _exact_mapping(raw_record, _BLOCKER_FIELDS, f"{label}[{index}]")
        blocker_id = _bounded_text(record["blocker_id"], f"{label}[{index}].blocker_id", 96)
        owner_task = _bounded_text(record["owner_task"], f"{label}[{index}].owner_task", 8)
        gate_id = _bounded_text(record["gate_id"], f"{label}[{index}].gate_id", 96)
        summary = _bounded_text(record["summary"], f"{label}[{index}].summary", 256)
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", blocker_id) is None:
            raise VerificationError(f"{label}[{index}].blocker_id: stable kebab ID required")
        if re.fullmatch(r"T[0-9]{3}", owner_task) is None:
            raise VerificationError(f"{label}[{index}].owner_task: task ID required")
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", gate_id) is None:
            raise VerificationError(f"{label}[{index}].gate_id: stable kebab ID required")
        if blocker_id in seen:
            raise VerificationError(f"{label}: duplicate blocker_id")
        seen.add(blocker_id)
        records.append({
            "blocker_id": blocker_id,
            "owner_task": owner_task,
            "gate_id": gate_id,
            "summary": summary,
        })
    return records


def _require_canonical_blocker_subset(
    records: Sequence[Mapping[str, str]],
    allowed: Sequence[Mapping[str, str]],
    label: str,
) -> None:
    expected_by_id = {item["blocker_id"]: item for item in allowed}
    expected_order = {item["blocker_id"]: index for index, item in enumerate(allowed)}
    positions: list[int] = []
    for record in records:
        expected = expected_by_id.get(record["blocker_id"])
        if expected is None or dict(record) != dict(expected):
            raise VerificationError(f"{label}: exact canonical blocker subset required")
        positions.append(expected_order[record["blocker_id"]])
    if positions != sorted(positions):
        raise VerificationError(f"{label}: exact canonical blocker subset order required")


def _validate_cosign_coordinates(
    declaration: Mapping[str, Any],
    label: str,
    *,
    expected_filename: str,
    maximum_bytes: int,
) -> None:
    filename = _artifact_filename(declaration.get("filename"), f"{label}.filename")
    if filename != expected_filename:
        raise VerificationError(f"{label}: official Cosign filename changed")
    url = _https_asset_url(declaration.get("url"), filename, f"{label}.url")
    if url != f"{COSIGN_RELEASE_PREFIX}{filename}":
        raise VerificationError(f"{label}: official Cosign release URL changed")
    _require_bounded_positive_int(declaration.get("bytes"), f"{label}.bytes", maximum_bytes)
    _require_sha256(declaration.get("sha256"), f"{label}.sha256")


def _validate_cosign_bundle(
    value: Any, label: str, *, expected_filename: str
) -> dict[str, Any]:
    bundle = _exact_mapping(value, _BUNDLE_FIELDS, label)
    _validate_cosign_coordinates(
        bundle,
        label,
        expected_filename=expected_filename,
        maximum_bytes=MAX_BUNDLE_BYTES,
    )
    if bundle["verified"] is not True:
        raise VerificationError(f"{label}: Cosign signature chain must be verified")
    return bundle


def _validate_cosign_executable(
    value: Any, label: str, *, expected_filename: str
) -> dict[str, Any]:
    executable = _exact_mapping(value, _COSIGN_EXECUTABLE_FIELDS, label)
    _validate_cosign_coordinates(
        executable,
        label,
        expected_filename=expected_filename,
        maximum_bytes=MAX_VERIFIER_BYTES,
    )
    if executable["mode"] != "0755":
        raise VerificationError(f"{label}: release-build verifier mode must be 0755")
    return executable


def _validate_cosign_bootstrap(
    value: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    bootstrap = _exact_mapping(
        value, _VERIFIER_BOOTSTRAP_FIELDS, "signature_policy.verifier_bootstrap"
    )
    if (
        bootstrap["name"] != "cosign"
        or bootstrap["version"] != "3.1.2"
        or bootstrap["certificate_identity"] != COSIGN_BOOTSTRAP_IDENTITY
        or bootstrap["certificate_oidc_issuer"] != COSIGN_BOOTSTRAP_ISSUER
    ):
        raise VerificationError("Cosign verifier bootstrap identity or version changed")

    checksum = _exact_mapping(
        bootstrap["checksum_manifest"],
        _COSIGN_CHECKSUM_FIELDS,
        "Cosign checksum manifest",
    )
    _validate_cosign_coordinates(
        checksum,
        "Cosign checksum manifest",
        expected_filename="cosign_checksums.txt",
        maximum_bytes=MAX_BUNDLE_BYTES,
    )
    _validate_cosign_bundle(
        checksum["sigstore_bundle"],
        "Cosign checksum manifest bundle",
        expected_filename="cosign_checksums.txt.sigstore.json",
    )
    if checksum["signature_chain_verified"] is not True:
        raise VerificationError("Cosign checksum signature chain is not verified")

    raw_verifiers = bootstrap["release_build_verifiers"]
    if type(raw_verifiers) is not list or len(raw_verifiers) != len(PLATFORMS):
        raise VerificationError("exactly two Linux release-build verifiers are required")
    verifiers: list[dict[str, Any]] = []
    verifier_platforms: list[str] = []
    for index, raw_record in enumerate(raw_verifiers):
        record = _exact_mapping(
            raw_record,
            _COSIGN_VERIFIER_FIELDS,
            f"Cosign release build verifier {index}",
        )
        platform = _bounded_text(
            record["platform"], f"Cosign release build verifier {index}.platform", 32
        )
        verifier_platforms.append(platform)
        suffix = PLATFORM_TARGETS.get(platform)
        if suffix is None:
            raise VerificationError("Cosign release build accepts Linux platforms only")
        architecture = platform.rsplit("/", 1)[-1]
        _validate_cosign_executable(
            record["executable"],
            f"Cosign {platform} executable",
            expected_filename=f"cosign-linux-{architecture}",
        )
        _validate_cosign_bundle(
            record["sigstore_bundle"],
            f"Cosign {platform} bundle",
            expected_filename=f"cosign-linux-{architecture}.sigstore.json",
        )
        if (
            record["checksum_manifest_match"] is not True
            or record["signature_chain_verified"] is not True
        ):
            raise VerificationError(
                f"Cosign {platform}: checksum and signature chains must be verified"
            )
        verifiers.append(record)
    if verifier_platforms != list(PLATFORMS) or len(set(verifier_platforms)) != len(PLATFORMS):
        raise VerificationError("exact Linux verifier platforms and order are required")

    raw_audits = bootstrap["audit_observations"]
    if type(raw_audits) is not list or len(raw_audits) != 1:
        raise VerificationError("exact Darwin audit observation required")
    audit = _exact_mapping(raw_audits[0], _COSIGN_AUDIT_FIELDS, "Cosign audit observation")
    if (
        audit["label"] != "darwin-arm64-audit-only"
        or audit["platform"] != "darwin/arm64"
        or audit["eligible_for_release_build"] is not False
    ):
        raise VerificationError("Darwin Cosign audit cannot satisfy the release build")
    _validate_cosign_executable(
        audit["executable"],
        "Cosign Darwin audit executable",
        expected_filename="cosign-darwin-arm64",
    )
    _validate_cosign_bundle(
        audit["sigstore_bundle"],
        "Cosign Darwin audit bundle",
        expected_filename="cosign-darwin-arm64.sigstore.json",
    )
    if (
        audit["checksum_manifest_match"] is not True
        or audit["signature_chain_verified"] is not True
    ):
        raise VerificationError("Cosign Darwin audit signature chain is incomplete")

    if bootstrap != COSIGN_BOOTSTRAP_POLICY:
        raise VerificationError("Cosign verifier bootstrap differs from exact locked evidence")
    return bootstrap, verifiers, audit


def _require_exact_file_mode(path: Path, expected: int, label: str) -> None:
    mode = stat.S_IMODE(path.lstat().st_mode)
    if mode != expected:
        raise VerificationError(f"{label}: file mode must be {expected:04o}")


def _require_oci_digest(value: Any, label: str) -> str:
    if type(value) is not str or OCI_DIGEST.fullmatch(value) is None:
        raise VerificationError(f"{label}: exact lowercase OCI SHA-256 required")
    return value


def _verify_snapshot_artifact(
    path: Path,
    declaration: Mapping[str, Any],
    label: str,
    *,
    maximum_bytes: int,
) -> dict[str, Any]:
    """Verify a Debian snapshot file whose content-address URL is opaque."""

    filename = _artifact_filename(declaration.get("filename"), f"{label}.filename")
    if path.name != filename:
        raise VerificationError(f"{label}: artifact filename changed")
    url = declaration.get("url")
    if type(url) is not str or SNAPSHOT_ARTIFACT_URL.fullmatch(url) is None:
        raise VerificationError(f"{label}: exact Debian snapshot content URL required")
    expected_bytes = _require_bounded_positive_int(
        declaration.get("bytes"), f"{label}.bytes", maximum_bytes
    )
    expected_digest = _require_sha256(declaration.get("sha256"), f"{label}.sha256")
    info = _require_regular_input(path, label)
    if info.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o022):
        raise VerificationError(f"{label}: artifact mode is unsafe")
    if info.st_size > maximum_bytes:
        raise VerificationError(f"{label}: artifact exceeds its byte limit")
    if info.st_size != expected_bytes or sha256_file(path) != expected_digest:
        raise VerificationError(f"{label}: exact bytes changed")
    return {
        "filename": filename,
        "url": url,
        "bytes": expected_bytes,
        "sha256": expected_digest,
    }


def _verified_input_file(record: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact file identity retained in a successful runner report."""

    return {
        "filename": record["filename"],
        "bytes": record["bytes"],
        "sha256": record["sha256"],
    }


def _ar_integer(field: bytes, label: str, *, base: int = 10) -> int:
    try:
        text = field.decode("ascii").strip()
    except UnicodeDecodeError as exc:
        raise VerificationError(f"{label}: non-ASCII ar header field") from exc
    digits = "01234567" if base == 8 else "0123456789"
    if not text or any(character not in digits for character in text):
        raise VerificationError(f"{label}: invalid ar header integer")
    return int(text, base)


def _parse_deb_ar(data: bytes, label: str) -> dict[str, bytes]:
    """Parse the small, classic-ar subset permitted for a Debian binary package."""

    if len(data) > MAX_DEB_BYTES:
        raise VerificationError(f"{label}: Debian package exceeds its byte limit")
    if not data.startswith(b"!<arch>\n"):
        raise VerificationError(f"{label}: invalid Debian ar magic")
    offset = 8
    members: dict[str, bytes] = {}
    while offset < len(data):
        if len(members) >= MAX_DEB_MEMBERS:
            raise VerificationError(f"{label}: too many ar members")
        if len(data) - offset < 60:
            raise VerificationError(f"{label}: trailing garbage after ar members")
        header = data[offset:offset + 60]
        offset += 60
        if header[58:60] != b"`\n":
            raise VerificationError(f"{label}: malformed ar member header")
        try:
            raw_name = header[0:16].decode("ascii").rstrip()
        except UnicodeDecodeError as exc:
            raise VerificationError(f"{label}: non-ASCII ar member name") from exc
        if (
            raw_name.startswith(("/", "#1/"))
            or "/" in raw_name.rstrip("/")
            or raw_name.count("/") > 1
        ):
            raise VerificationError(f"{label}: extended or unsafe ar member name")
        name = _artifact_filename(raw_name.rstrip("/"), f"{label}.ar member")
        _ar_integer(header[16:28], f"{label}/{name}.timestamp")
        owner = _ar_integer(header[28:34], f"{label}/{name}.owner")
        group = _ar_integer(header[34:40], f"{label}/{name}.group")
        mode = _ar_integer(header[40:48], f"{label}/{name}.mode", base=8)
        if owner != 0 or group != 0 or mode != 0o100644:
            raise VerificationError(f"{label}/{name}: unexpected ar ownership or mode")
        size = _ar_integer(header[48:58], f"{label}/{name}.size")
        if size > MAX_DEB_MEMBER_BYTES:
            raise VerificationError(f"{label}/{name}: ar member exceeds its byte limit")
        end = offset + size
        if end > len(data):
            raise VerificationError(f"{label}/{name}: truncated ar member")
        if name in members:
            raise VerificationError(f"{label}: duplicate ar member: {name}")
        members[name] = data[offset:end]
        offset = end
        if size % 2:
            if offset >= len(data) or data[offset:offset + 1] != b"\n":
                raise VerificationError(f"{label}/{name}: invalid ar alignment byte")
            offset += 1
    if offset != len(data):
        raise VerificationError(f"{label}: trailing garbage after ar members")
    if list(members) != ["debian-binary", "control.tar.xz", "data.tar.xz"]:
        raise VerificationError(f"{label}: exact Debian ar members and ordering required")
    if members["debian-binary"] != b"2.0\n":
        raise VerificationError(f"{label}: unsupported debian-binary version")
    return members


def _debian_tar_name(name: str, label: str) -> str | None:
    if name == "./":
        return None
    candidate = name.removeprefix("./")
    canonical = _safe_tar_name(candidate)
    accepted = {canonical, f"./{canonical}"}
    if name.endswith("/"):
        accepted |= {f"{canonical}/", f"./{canonical}/"}
    if name not in accepted:
        raise VerificationError(f"{label}: noncanonical Debian tar member name: {name!r}")
    return canonical


def _open_bounded_xz_tar(
    compressed: bytes,
    label: str,
    *,
    permitted_symlinks: Mapping[str, str] | None = None,
) -> tuple[tarfile.TarFile, dict[str, tarfile.TarInfo], io.BytesIO]:
    """Return a validated tar plus members; the BytesIO keeps its backing alive."""

    try:
        decompressor = lzma.LZMADecompressor(format=lzma.FORMAT_XZ)
        raw = decompressor.decompress(compressed, max_length=MAX_DEB_TAR_BYTES + 1)
    except lzma.LZMAError as exc:
        raise VerificationError(f"{label}: invalid xz stream: {exc}") from exc
    if len(raw) > MAX_DEB_TAR_BYTES:
        raise VerificationError(f"{label}: expanded tar exceeds its byte limit")
    if not decompressor.eof:
        raise VerificationError(f"{label}: truncated or overlong xz stream")
    if decompressor.unused_data:
        raise VerificationError(f"{label}: trailing data after xz stream")
    if len(raw) % 512:
        raise VerificationError(f"{label}: tar stream is not block aligned")
    backing = io.BytesIO(raw)
    archive: tarfile.TarFile | None = None
    try:
        # The caller must keep this handle open while hashing selected members.
        archive = tarfile.open(fileobj=backing, mode="r:")  # noqa: SIM115
        members: list[tarfile.TarInfo] = []
        while True:
            info = archive.next()
            if info is None:
                break
            members.append(info)
            if len(members) > MAX_DEB_TAR_MEMBERS:
                raise VerificationError(f"{label}: invalid bounded tar member count")
        if not members:
            raise VerificationError(f"{label}: invalid bounded tar member count")
        tail = raw[archive.offset:]
        if len(tail) < 1024 or any(tail):
            raise VerificationError(
                f"{label}: nonzero trailing data after tar end marker"
            )

        allowed_links = dict(permitted_symlinks or {})
        indexed: dict[str, tarfile.TarInfo] = {}
        root_seen = False
        for info in members:
            name = _debian_tar_name(info.name, label)
            if name is None:
                if root_seen or not info.isdir():
                    raise VerificationError(
                        f"{label}: root member must be one unique directory"
                    )
                root_seen = True
                continue
            if name in indexed:
                raise VerificationError(f"{label}: duplicate tar member: {name}")
            indexed[name] = info
            if info.uid != 0 or info.gid != 0:
                raise VerificationError(f"{label}: non-root tar member owner: {name}")
            if info.islnk():
                raise VerificationError(f"{label}: hard links are forbidden: {name}")
            if info.issym():
                if (
                    allowed_links.get(name) != info.linkname
                    or stat.S_IMODE(info.mode) != 0o777
                ):
                    raise VerificationError(
                        f"{label}: unpinned symlink is forbidden: {name}"
                    )
                continue
            if info.isdev() or info.isfifo() or not (info.isfile() or info.isdir()):
                raise VerificationError(
                    f"{label}: special tar member is forbidden: {name}"
                )
            if info.mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o022):
                raise VerificationError(f"{label}: unsafe tar member mode: {name}")
            if info.size > MAX_DEB_TAR_BYTES:
                raise VerificationError(
                    f"{label}: tar member exceeds its byte limit: {name}"
                )
        missing_links = set(allowed_links) - {
            name for name, info in indexed.items() if info.issym()
        }
        if missing_links:
            raise VerificationError(f"{label}: pinned compatibility symlink is missing")
        return archive, indexed, backing
    except (OSError, tarfile.TarError, VerificationError) as exc:
        if archive is not None:
            archive.close()
        backing.close()
        if isinstance(exc, VerificationError):
            raise
        raise VerificationError(f"{label}: invalid tar stream: {exc}") from exc


def _verify_debian_bash_package(
    path: Path,
    declaration: Mapping[str, Any],
    package_member: Mapping[str, Any],
    license_member: Mapping[str, Any],
    *,
    platform: str,
) -> dict[str, Any]:
    label = f"{platform} Debian Bash package"
    package_report = _verify_snapshot_artifact(
        path, declaration, label, maximum_bytes=MAX_DEB_BYTES
    )
    _require_exact_file_mode(path, 0o644, label)
    data = path.read_bytes()
    if (
        len(data) != declaration["bytes"]
        or hashlib.sha256(data).hexdigest() != declaration["sha256"]
    ):
        raise VerificationError(f"{label}: bytes changed while opening package")
    ar_members = _parse_deb_ar(data, label)
    control_archive, _, control_backing = _open_bounded_xz_tar(
        ar_members["control.tar.xz"], f"{label}/control.tar.xz"
    )
    control_archive.close()
    control_backing.close()
    data_archive, members, data_backing = _open_bounded_xz_tar(
        ar_members["data.tar.xz"],
        f"{label}/data.tar.xz",
        permitted_symlinks=PERMITTED_BASH_SYMLINKS,
    )
    try:
        verified_members: dict[str, dict[str, Any]] = {}
        for member_label, expected, require_mode in (
            ("package_member", package_member, True),
            ("license_member", license_member, False),
        ):
            member_path = _safe_tar_name(expected["path"])
            info = members.get(member_path)
            if info is None or not info.isfile() or info.issym() or info.islnk():
                raise VerificationError(
                    f"{label}: {member_label} is not the pinned regular file"
                )
            expected_bytes = _require_bounded_positive_int(
                expected["bytes"], f"{label}.{member_label}.bytes", MAX_BASH_BYTES
            )
            expected_digest = _require_sha256(
                expected["sha256"], f"{label}.{member_label}.sha256"
            )
            if info.size != expected_bytes:
                raise VerificationError(f"{label}: {member_label} size changed")
            member_data = _read_tar_member(data_archive, info)
            if hashlib.sha256(member_data).hexdigest() != expected_digest:
                raise VerificationError(f"{label}: {member_label} digest changed")
            if require_mode:
                if expected.get("installed_path") != "/bin/bash":
                    raise VerificationError(f"{label}: installed Bash path changed")
                if expected.get("mode") != "0755" or stat.S_IMODE(info.mode) != 0o755:
                    raise VerificationError(f"{label}: installed Bash mode changed")
            elif stat.S_IMODE(info.mode) != 0o644:
                raise VerificationError(f"{label}: Bash license mode changed")
            verified_members[member_label] = {
                "path": member_path,
                "bytes": expected_bytes,
                "sha256": expected_digest,
            }
    finally:
        data_archive.close()
        data_backing.close()
    return {**package_report, **verified_members}


def _verify_oci_descriptor(
    value: Any,
    label: str,
    *,
    media_type: str,
) -> dict[str, Any]:
    descriptor = _exact_mapping(value, _OCI_DESCRIPTOR_FIELDS, label)
    if descriptor["media_type"] != media_type:
        raise VerificationError(f"{label}: OCI media type changed")
    _require_oci_digest(descriptor["digest"], f"{label}.digest")
    _require_bounded_positive_int(
        descriptor["bytes"], f"{label}.bytes", MAX_DEB_TAR_BYTES
    )
    return descriptor


def _validate_runtime_declaration(
    value: Any,
    *,
    platform: str,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    label = f"{platform}.runtime_image"
    runtime = _exact_mapping(value, _RUNTIME_IMAGE_FIELDS, label)
    fixed = {
        "distribution": "debian",
        "suite": "bookworm",
        "repository": "docker.io/library/debian",
        "tag": "bookworm-20260824-slim",
        "created_at": "2026-08-24T00:00:00Z",
        "snapshot": "20260824T000000Z",
        "source_repository": (
            "https://github.com/debuerreotype/docker-debian-artifacts.git"
        ),
    }
    if any(runtime[key] != expected for key, expected in fixed.items()):
        raise VerificationError(f"{platform}: pinned Debian Bookworm image changed")
    if (
        type(runtime["source_revision"]) is not str
        or re.fullmatch(r"[0-9a-f]{40}", runtime["source_revision"]) is None
    ):
        raise VerificationError(f"{platform}: exact image source revision required")
    _verify_oci_descriptor(
        runtime["index"], f"{label}.index", media_type=OCI_INDEX_MEDIA_TYPE
    )
    _verify_oci_descriptor(
        runtime["manifest"], f"{label}.manifest", media_type=OCI_MANIFEST_MEDIA_TYPE
    )
    _verify_oci_descriptor(
        runtime["config"], f"{label}.config", media_type=OCI_CONFIG_MEDIA_TYPE
    )
    layers = runtime["layers"]
    if type(layers) is not list or len(layers) != 1:
        raise VerificationError(f"{platform}: exactly one pinned OCI layer is required")
    layer = _exact_mapping(layers[0], _OCI_LAYER_FIELDS, f"{label}.layers[0]")
    if layer["position"] != 1 or layer["media_type"] != OCI_LAYER_MEDIA_TYPE:
        raise VerificationError(f"{platform}: OCI layer ordering or media type changed")
    _require_oci_digest(layer["digest"], f"{label}.layers[0].digest")
    _require_bounded_positive_int(
        layer["bytes"], f"{label}.layers[0].bytes", MAX_DEB_TAR_BYTES
    )

    bash = _exact_mapping(runtime["bash"], _BASH_FIELDS, f"{label}.bash")
    if (
        bash["package"] != "bash"
        or bash["package_version"] != "5.2.15-2+b13"
        or bash["source_package"] != "bash"
        or bash["source_version"] != "5.2.15-2"
        or bash["installed_path"] != "/bin/bash"
        or bash["mode"] != "0755"
    ):
        raise VerificationError(f"{platform}: pinned /bin/bash declaration changed")
    package = _exact_mapping(
        bash["binary_package"], _SNAPSHOT_ARTIFACT_FIELDS,
        f"{label}.bash.binary_package",
    )
    architecture = platform.rsplit("/", 1)[-1]
    expected_package_filename = f"bash_5.2.15-2+b13_{architecture}.deb"
    if _artifact_filename(
        package["filename"], f"{label}.bash.binary_package.filename"
    ) != expected_package_filename:
        raise VerificationError(f"{platform}: Bash binary package filename changed")
    if (
        type(package["url"]) is not str
        or SNAPSHOT_ARTIFACT_URL.fullmatch(package["url"]) is None
    ):
        raise VerificationError(f"{platform}: Bash package snapshot URL changed")
    _require_bounded_positive_int(
        package["bytes"], f"{label}.bash.binary_package.bytes", MAX_DEB_BYTES
    )
    _require_sha256(package["sha256"], f"{label}.bash.binary_package.sha256")

    package_member = _exact_mapping(
        bash["package_member"], _PACKAGE_MEMBER_FIELDS,
        f"{label}.bash.package_member",
    )
    if (
        package_member["path"] != "bin/bash"
        or package_member["installed_path"] != "/bin/bash"
        or package_member["mode"] != "0755"
    ):
        raise VerificationError(f"{platform}: Bash package member path or mode changed")
    _require_bounded_positive_int(
        package_member["bytes"], f"{label}.bash.package_member.bytes", MAX_BASH_BYTES
    )
    _require_sha256(
        package_member["sha256"], f"{label}.bash.package_member.sha256"
    )
    license_member = _exact_mapping(
        bash["license_member"], _LICENSE_MEMBER_FIELDS,
        f"{label}.bash.license_member",
    )
    if license_member["path"] != "usr/share/doc/bash/copyright":
        raise VerificationError(f"{platform}: Bash license member path changed")
    _require_bounded_positive_int(
        license_member["bytes"], f"{label}.bash.license_member.bytes", MAX_BASH_BYTES
    )
    _require_sha256(
        license_member["sha256"], f"{label}.bash.license_member.sha256"
    )

    source_inputs = bash["source_inputs"]
    if type(source_inputs) is not list or len(source_inputs) != 3:
        raise VerificationError(f"{platform}: exact three Bash source inputs required")
    validated_sources: list[dict[str, Any]] = []
    source_filenames: set[str] = set()
    for index, source_value in enumerate(source_inputs):
        source = _exact_mapping(
            source_value, _SNAPSHOT_ARTIFACT_FIELDS,
            f"{label}.bash.source_inputs[{index}]",
        )
        filename = _artifact_filename(
            source["filename"], f"{label}.bash.source_inputs[{index}].filename"
        )
        if filename in source_filenames:
            raise VerificationError(f"{platform}: duplicate Bash source input filename")
        source_filenames.add(filename)
        if (
            type(source["url"]) is not str
            or SNAPSHOT_ARTIFACT_URL.fullmatch(source["url"]) is None
        ):
            raise VerificationError(f"{platform}: Bash source snapshot URL changed")
        _require_bounded_positive_int(
            source["bytes"], f"{label}.bash.source_inputs[{index}].bytes",
            MAX_BASH_BYTES,
        )
        _require_sha256(
            source["sha256"], f"{label}.bash.source_inputs[{index}].sha256"
        )
        validated_sources.append(source)
    expected_names = [item["filename"] for item in BASH_SOURCE_INPUTS]
    if [item["filename"] for item in validated_sources] != expected_names:
        raise VerificationError(f"{platform}: Bash source input ordering changed")
    return runtime, bash, validated_sources


def _verify_standalone_archive(
    path: Path,
    archive_declaration: Mapping[str, Any],
    executable_declaration: Mapping[str, Any],
    *,
    platform: str,
    component: str,
) -> bytes:
    _verify_declared_artifact(path, archive_declaration, f"{platform}/{component} archive")
    _require_exact_file_mode(path, 0o644, f"{platform}/{component} archive")
    expected_member = COMPONENT_MEMBERS[(platform, component)]
    if archive_declaration["member_path"] != expected_member:
        raise VerificationError(f"{platform}/{component}: standalone member path changed")
    try:
        with tarfile.open(path, mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) != 1:
                raise VerificationError(
                    f"{platform}/{component}: archive must contain exactly one executable"
                )
            info = members[0]
            name = _safe_tar_name(info.name)
            if (name != expected_member or not info.isfile() or info.issym() or info.islnk()
                    or info.isdev() or info.isfifo()):
                raise VerificationError(
                    f"{platform}/{component}: archive member is not the pinned regular file"
                )
            if stat.S_IMODE(info.mode) != 0o755 or info.mode & (
                stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX | 0o022
            ):
                raise VerificationError(f"{platform}/{component}: unsafe executable mode")
            if info.size != executable_declaration["bytes"]:
                raise VerificationError(f"{platform}/{component}: executable size changed")
            data = _read_tar_member(archive, info)
    except (OSError, tarfile.TarError) as exc:
        raise VerificationError(
            f"{platform}/{component}: invalid standalone archive: {exc}"
        ) from exc
    if hashlib.sha256(data).hexdigest() != executable_declaration["sha256"]:
        raise VerificationError(f"{platform}/{component}: executable digest changed")
    return data


def _verify_component_signature(
    *,
    component_data: bytes,
    bundle_path: Path,
    cosign_path: Path,
    identity: str,
    issuer: str,
    platform: str,
    component: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="deeptwin-codex-v3-signature-") as raw:
        temporary = Path(raw)
        subject = temporary / "subject"
        subject.write_bytes(component_data)
        subject.chmod(0o700)
        result = run_bounded_process(
            [
                str(cosign_path), "verify-blob", "--offline", "--bundle", str(bundle_path),
                "--certificate-identity", identity,
                "--certificate-oidc-issuer", issuer,
                str(subject),
            ],
            cwd=temporary,
            environment={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "HOME": str(temporary),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_COLOR": "1",
            },
            timeout_seconds=30,
            stdout_limit=128 * 1024,
            stderr_limit=128 * 1024,
        )
    if result.stop_reason is not None or result.exit_code != 0:
        raise VerificationError(
            f"{platform}/{component}: offline Sigstore verification failed closed "
            f"(exit={result.exit_code}, stop={result.stop_reason})"
        )


def verify_minimal_runner(
    manifest_path: Path,
    artifacts_directory: Path,
    cosign_path: Path,
    *,
    locked: bool = False,
    allow_audit_verifier: bool = False,
) -> dict[str, Any]:
    """Verify the complete two-platform minimal managed-runner input set offline."""

    if type(locked) is not bool:
        raise VerificationError("locked must be an exact boolean")
    if type(allow_audit_verifier) is not bool:
        raise VerificationError("allow_audit_verifier must be an exact boolean")

    manifest_info = _require_regular_input(manifest_path, "minimal runner manifest")
    if not 1 <= manifest_info.st_size <= MAX_MANIFEST_BYTES:
        raise VerificationError("minimal runner manifest exceeds its byte limit")
    manifest = _exact_mapping(load_json(manifest_path), _RUNNER_FIELDS, "manifest")
    if manifest["schema_version"] != RUNNER_SCHEMA:
        raise VerificationError("unsupported Codex minimal-runner manifest schema")
    if manifest["status"] != "candidate_not_release_qualified":
        raise VerificationError("minimal runner must remain explicitly non-release-qualified")
    if manifest["version"] != CODEX_VERSION or manifest["tag"] != CODEX_TAG:
        raise VerificationError("Codex version/tag changed")
    source_commit = manifest["source_commit"]
    if type(source_commit) is not str or re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise VerificationError("source_commit must be an exact lowercase Git SHA")
    if manifest["target_platforms"] != list(PLATFORMS):
        raise VerificationError("target_platforms must be the exact supported pair")
    if manifest["omitted_components"] != list(OMITTED_COMPONENTS):
        raise VerificationError("obsolete full-package components must be explicitly omitted")
    build_blockers = _validate_blocker_records(
        manifest["build_input_blockers"], "build_input_blockers"
    )
    downstream_blockers = _validate_blocker_records(
        manifest["downstream_release_blockers"], "downstream_release_blockers"
    )
    expected_build_gate = "not_satisfied" if build_blockers else "satisfied"
    if manifest["build_input_gate"] != expected_build_gate:
        raise VerificationError(
            "build_input_gate must depend only on build_input_blockers"
        )
    if locked and build_blockers:
        raise VerificationError("locked build input cannot retain build blockers")
    _require_canonical_blocker_subset(
        build_blockers, EXPECTED_BUILD_INPUT_BLOCKERS, "build_input_blockers"
    )
    _require_canonical_blocker_subset(
        downstream_blockers,
        EXPECTED_DOWNSTREAM_RELEASE_BLOCKERS,
        "downstream_release_blockers",
    )
    expected_release_gate = (
        "not_satisfied" if build_blockers or downstream_blockers else "satisfied"
    )
    if manifest["release_gate"] != expected_release_gate:
        raise VerificationError(
            "release_gate must depend on build and downstream release blockers"
        )

    mutation = _exact_mapping(
        manifest["runtime_mutation_policy"], _MUTATION_FIELDS, "runtime_mutation_policy"
    )
    if any(value is not False for value in mutation.values()):
        raise VerificationError("all managed-runner runtime mutation must remain disabled")

    layout = _exact_mapping(manifest["runtime_layout"], _LAYOUT_FIELDS, "runtime_layout")
    expected_layout = {
        "install_root": INSTALL_ROOT,
        "codex_path": INSTALL_PATHS["codex"],
        "code_mode_host_path": INSTALL_PATHS["codex-code-mode-host"],
        "bubblewrap_path": INSTALL_PATHS["bubblewrap"],
        "bash_path": "/bin/bash",
        "path_env": FIXED_PATH_ENV,
        "required_internal_sandbox_profiles": ["read-only", "workspace-write"],
        "codex_home_policy": "isolated_per_run",
    }
    if layout != expected_layout:
        raise VerificationError("runtime_layout differs from the fixed sibling layout")
    if PurePosixPath(layout["codex_path"]).parent != PurePosixPath(
        layout["code_mode_host_path"]
    ).parent:
        raise VerificationError("codex-code-mode-host must remain adjacent to codex")

    signature = _exact_mapping(
        manifest["signature_policy"], _SIGNATURE_POLICY_FIELDS, "signature_policy"
    )
    if (
        signature["offline"] is not True
        or signature["subject_scope"] != "extracted executable only"
        or signature["certificate_identity"] != CERTIFICATE_IDENTITY
        or signature["certificate_oidc_issuer"] != CERTIFICATE_ISSUER
    ):
        raise VerificationError("signature policy differs from the pinned OpenAI release policy")
    bootstrap, release_build_verifiers, audit_verifier = _validate_cosign_bootstrap(
        signature["verifier_bootstrap"]
    )
    eligible_verifiers = (
        [audit_verifier] if allow_audit_verifier else release_build_verifiers
    )
    matching_verifiers = [
        record for record in eligible_verifiers
        if record["executable"]["filename"] == cosign_path.name
    ]
    if len(matching_verifiers) != 1:
        expected_kind = (
            "locked Darwin audit verifier"
            if allow_audit_verifier
            else "locked Linux release-build verifier"
        )
        raise VerificationError(f"--cosign must select exactly one {expected_kind}")
    selected_verifier = matching_verifiers[0]
    selected_verifier_label = (
        "declared Darwin audit Sigstore verifier"
        if allow_audit_verifier
        else "declared Linux release-build Sigstore verifier"
    )
    verifier_report = _verify_declared_artifact(
        cosign_path,
        selected_verifier["executable"],
        selected_verifier_label,
        require_executable=True,
    )
    _require_exact_file_mode(cosign_path, 0o755, selected_verifier_label)

    try:
        root_info = artifacts_directory.lstat()
    except OSError as exc:
        raise VerificationError(f"artifact directory is unavailable: {exc}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise VerificationError("artifact directory must be a real directory")
    if root_info.st_mode & 0o022:
        raise VerificationError("artifact directory must not be group/world writable")

    platform_inputs = manifest["platform_inputs"]
    if type(platform_inputs) is not list or len(platform_inputs) != len(PLATFORMS):
        raise VerificationError("platform_inputs must contain exactly two records")
    reports: list[dict[str, Any]] = []
    verified_input_files: list[dict[str, Any]] = []
    expected_filenames: set[str] = set()
    common_source_inputs: list[dict[str, Any]] | None = None
    source_reports: list[dict[str, Any]] = []
    for platform_index, platform in enumerate(PLATFORMS):
        record = _exact_mapping(
            platform_inputs[platform_index], _PLATFORM_FIELDS,
            f"platform_inputs[{platform_index}]",
        )
        if record["platform"] != platform or record["target"] != PLATFORM_TARGETS[platform]:
            raise VerificationError(f"{platform}: platform/target ordering changed")

        runtime, bash, source_inputs = _validate_runtime_declaration(
            record["runtime_image"], platform=platform
        )
        if common_source_inputs is None:
            common_source_inputs = source_inputs
            for source_index, source in enumerate(source_inputs):
                filename = source["filename"]
                if filename in expected_filenames:
                    raise VerificationError("artifact filenames must be globally unique")
                expected_filenames.add(filename)
                path = artifacts_directory / filename
                report = _verify_snapshot_artifact(
                    path,
                    source,
                    f"Bash source input {source_index}",
                    maximum_bytes=MAX_BASH_BYTES,
                )
                _require_exact_file_mode(path, 0o644, f"Bash source input {source_index}")
                source_reports.append(report)
                verified_input_files.append(_verified_input_file(report))
        elif source_inputs != common_source_inputs:
            raise VerificationError(
                "Bash source inputs must be identical across target platforms"
            )
        expected_runtime = CODEX_RUNTIME_INPUTS.get(platform)
        if expected_runtime is None or runtime != expected_runtime:
            raise VerificationError(
                f"{platform}: runtime image differs from the exact pinned Bookworm input"
            )

        binary_package = bash["binary_package"]
        package_member = bash["package_member"]
        license_member = bash["license_member"]
        bash_filename = binary_package["filename"]
        if bash_filename in expected_filenames:
            raise VerificationError("artifact filenames must be globally unique")
        expected_filenames.add(bash_filename)
        bash_path = artifacts_directory / bash_filename
        bash_report = _verify_debian_bash_package(
            bash_path,
            binary_package,
            package_member,
            license_member,
            platform=platform,
        )
        verified_input_files.append(_verified_input_file(bash_report))

        components = record["components"]
        if type(components) is not list or len(components) != len(COMPONENTS):
            raise VerificationError(f"{platform}: exactly three components are required")
        component_reports: list[dict[str, Any]] = []
        for component_index, component in enumerate(COMPONENTS):
            declaration = _exact_mapping(
                components[component_index], _COMPONENT_FIELDS,
                f"{platform}.components[{component_index}]",
            )
            if declaration["name"] != component:
                raise VerificationError(f"{platform}: component ordering or label changed")
            if declaration["signature_scope"] != "extracted executable only":
                raise VerificationError(f"{platform}/{component}: signature scope changed")
            archive = _exact_mapping(declaration["archive"], _ARCHIVE_FIELDS,
                                     f"{platform}/{component}.archive")
            executable = _exact_mapping(declaration["executable"], _EXECUTABLE_FIELDS,
                                        f"{platform}/{component}.executable")
            bundle = _exact_mapping(declaration["sigstore_bundle"], _BUNDLE_FIELDS,
                                    f"{platform}/{component}.sigstore_bundle")
            member = COMPONENT_MEMBERS[(platform, component)]
            archive_filename = _artifact_filename(
                archive["filename"], f"{platform}/{component}.archive.filename"
            )
            bundle_filename = _artifact_filename(
                bundle["filename"], f"{platform}/{component}.bundle.filename"
            )
            if archive_filename != f"{member}.tar.gz" or bundle_filename != f"{member}.sigstore":
                raise VerificationError(f"{platform}/{component}: release asset filename changed")
            archive_url = _https_asset_url(
                archive["url"], archive_filename, f"{platform}/{component}.archive.url"
            )
            bundle_url = _https_asset_url(
                bundle["url"], bundle_filename, f"{platform}/{component}.bundle.url"
            )
            if (not archive_url.startswith(OPENAI_RELEASE_PREFIX)
                    or not bundle_url.startswith(OPENAI_RELEASE_PREFIX)):
                raise VerificationError(
                    f"{platform}/{component}: assets must be from the pinned OpenAI release"
                )
            _require_bounded_positive_int(
                archive["bytes"], f"{platform}/{component}.archive.bytes", MAX_ARCHIVE_BYTES
            )
            _require_sha256(archive["sha256"], f"{platform}/{component}.archive.sha256")
            _require_bounded_positive_int(
                executable["bytes"], f"{platform}/{component}.bytes", MAX_EXECUTABLE_BYTES
            )
            _require_sha256(executable["sha256"], f"{platform}/{component}.sha256")
            if executable["installed_path"] != INSTALL_PATHS[component] \
                    or executable["mode"] != "0755":
                raise VerificationError(f"{platform}/{component}: installed layout changed")
            _require_bounded_positive_int(
                bundle["bytes"], f"{platform}/{component}.bundle.bytes", MAX_BUNDLE_BYTES
            )
            _require_sha256(bundle["sha256"], f"{platform}/{component}.bundle.sha256")
            if bundle["verified"] is not True:
                raise VerificationError(f"{platform}/{component}: bundle is not verification-bound")
            for filename in (archive_filename, bundle_filename):
                if filename in expected_filenames:
                    raise VerificationError("artifact filenames must be globally unique")
                expected_filenames.add(filename)

            archive_path = artifacts_directory / archive_filename
            bundle_path = artifacts_directory / bundle_filename
            component_data = _verify_standalone_archive(
                archive_path, archive, executable, platform=platform, component=component
            )
            verified_input_files.append(_verified_input_file(archive))
            bundle_report = _verify_declared_artifact(
                bundle_path, bundle, f"{platform}/{component} Sigstore bundle"
            )
            verified_input_files.append(_verified_input_file(bundle_report))
            _require_exact_file_mode(bundle_path, 0o644,
                                     f"{platform}/{component} Sigstore bundle")
            _verify_component_signature(
                component_data=component_data,
                bundle_path=bundle_path,
                cosign_path=cosign_path,
                identity=signature["certificate_identity"],
                issuer=signature["certificate_oidc_issuer"],
                platform=platform,
                component=component,
            )
            component_reports.append({
                "name": component,
                "archive_sha256": archive["sha256"],
                "executable_sha256": executable["sha256"],
                "bundle_sha256": bundle_report["sha256"],
                "sigstore_verified": True,
            })
        reports.append({
            "platform": platform,
            "target": record["target"],
            "runtime_image": {
                "index_digest": runtime["index"]["digest"],
                "manifest_digest": runtime["manifest"]["digest"],
                "config_digest": runtime["config"]["digest"],
                "layer_digest": runtime["layers"][0]["digest"],
                "source_revision": runtime["source_revision"],
            },
            "bash": bash_report,
            "components": component_reports,
        })

    actual_filenames = {entry.name for entry in artifacts_directory.iterdir()}
    if actual_filenames != expected_filenames:
        raise VerificationError("artifact directory contains missing or undeclared files")
    verified_input_files.sort(key=lambda item: item["filename"])
    if (
        len(verified_input_files) != EXPECTED_MINIMAL_RUNNER_INPUT_FILE_COUNT
        or [item["filename"] for item in verified_input_files]
        != sorted(expected_filenames)
    ):
        raise VerificationError("verified runner input-file inventory is incomplete")
    return {
        "schema_version": RUNNER_SCHEMA,
        "status": manifest["status"],
        "version": CODEX_VERSION,
        "platform_count": len(reports),
        "component_count": sum(len(item["components"]) for item in reports),
        "layout": dict(layout),
        "omitted_components": list(OMITTED_COMPONENTS),
        "cosign": {
            "selected_verifier_platform": selected_verifier["platform"],
            "selection_mode": (
                "audit-only" if allow_audit_verifier else "release-build"
            ),
            "artifact": verifier_report,
            "linux_platform_coverage": [
                item["platform"] for item in release_build_verifiers
            ],
            "bootstrap_identity": bootstrap["certificate_identity"],
            "audit_only_platforms": [
                item["platform"] for item in bootstrap["audit_observations"]
            ],
        },
        "signature_scope": signature["subject_scope"],
        "bash_source_inputs": source_reports,
        "verified_input_file_count": len(verified_input_files),
        "verified_input_files": verified_input_files,
        "platforms": reports,
        "build_input_gate": manifest["build_input_gate"],
        "build_input_blocker_count": len(build_blockers),
        "release_gate": manifest["release_gate"],
        "downstream_release_blocker_count": len(downstream_blockers),
    }


def verify_package_archive(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Fail closed for callers of the retired v1 full-package API."""

    raise VerificationError(
        "full-package verification was retired by the minimal runner v3 contract"
    )


def verify_signed_sidecar(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Fail closed for callers of the retired cyclic sidecar-proposal API."""

    raise VerificationError(
        "sidecar proposals were retired by the minimal runner v3 contract"
    )


def verify_imported_sidecar(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """Fail closed for callers of the retired imported rg/zsh API."""

    raise VerificationError(
        "imported sidecars were retired by the minimal runner v3 contract"
    )


def codex_exec_argv(
    cli: Sequence[str],
    *,
    model: str,
    workspace: Path,
    sandbox: str = "read-only",
    approval_policy: str = "never",
) -> list[str]:
    if not cli:
        raise VerificationError("Codex command prefix is empty")
    if (
        not isinstance(model, str)
        or not model
        or len(model.encode("utf-8")) > 256
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", model) is None
    ):
        raise VerificationError("explicit bounded model identifier required")
    if sandbox not in SAFE_SANDBOXES:
        raise VerificationError("unsafe or unknown Codex sandbox")
    if approval_policy not in SAFE_APPROVAL_POLICIES:
        raise VerificationError("noninteractive approval policy must be explicit and fail-closed")
    root = workspace.resolve(strict=True)
    if not root.is_dir():
        raise VerificationError("workspace must be a directory")
    return [
        *cli,
        "exec",
        "--ignore-user-config",
        "--ignore-rules",
        "--strict-config",
        "-c",
        f'approval_policy="{approval_policy}"',
        "--ephemeral",
        "--model",
        model,
        "--sandbox",
        sandbox,
        "--color",
        "never",
        "--json",
        "--skip-git-repo-check",
        "--cd",
        str(root),
        "-",
    ]


def run_codex_jsonl(
    cli: Sequence[str],
    *,
    prompt: str,
    model: str,
    workspace: Path,
    codex_home: Path,
    timeout_seconds: float = 10.0,
    cancel_after_seconds: float | None = None,
    signal_grace_seconds: float = 0.5,
    sandbox: str = "read-only",
    approval_policy: str = "never",
    extra_environment: Mapping[str, str] | None = None,
    stdout_limit: int = 4 * 1024 * 1024,
    stderr_limit: int = 512 * 1024,
) -> dict[str, Any]:
    prompt_bytes = prompt.encode("utf-8")
    argv = codex_exec_argv(
        cli,
        model=model,
        workspace=workspace,
        sandbox=sandbox,
        approval_policy=approval_policy,
    )
    result = run_bounded_process(
        argv,
        cwd=workspace,
        environment=isolated_environment(codex_home, extra=extra_environment),
        stdin_data=prompt_bytes,
        timeout_seconds=timeout_seconds,
        cancel_after_seconds=cancel_after_seconds,
        signal_grace_seconds=signal_grace_seconds,
        stdout_limit=stdout_limit,
        stderr_limit=stderr_limit,
    )
    protocol: dict[str, Any] | None = None
    protocol_error: str | None = None
    try:
        protocol = validate_jsonl_bytes(
            result.stdout,
            require_terminal=result.stop_reason is None and result.exit_code == 0,
            limits=JsonlLimits(max_total_bytes=stdout_limit),
        )
    except VerificationError as exc:
        protocol_error = str(exc)

    if result.stop_reason is not None:
        outcome = result.stop_reason
    elif protocol_error is not None:
        outcome = "protocol_error"
    elif result.exit_code != 0 or protocol.get("terminal_event") == "turn.failed":
        outcome = "failed"
    else:
        outcome = "completed"
    return {
        "outcome": outcome,
        "exit_code": result.exit_code,
        "signals_sent": list(result.signals_sent),
        "elapsed_seconds": round(result.elapsed_seconds, 6),
        "stdout": {
            "bytes_seen": result.stdout_seen,
            "bytes_retained": len(result.stdout),
            "sha256": result.stdout_sha256,
        },
        "stderr": {
            "bytes_seen": result.stderr_seen,
            "bytes_retained": len(result.stderr),
            "sha256": result.stderr_sha256,
        },
        "protocol": protocol,
        "protocol_error": protocol_error,
    }


def exercise_offline_auth_fixture(
    cli: Sequence[str], *, fixture_sha256: str, base_directory: Path
) -> dict[str, Any]:
    """Exercise auth state transitions only after an exact offline-fixture marker."""

    expected_fixture_digest = _require_sha256(
        fixture_sha256, "offline fixture SHA-256"
    )
    if not cli:
        raise VerificationError("offline fixture command is empty")
    fixture_path = Path(cli[-1])
    _require_regular_input(fixture_path, "offline fixture")
    if sha256_file(fixture_path) != expected_fixture_digest:
        raise VerificationError("offline fixture executable hash changed")
    base_directory.mkdir(parents=True, exist_ok=True)
    codex_home = prepare_isolated_codex_home(base_directory)
    workspace = base_directory / "workspace"
    workspace.mkdir(mode=0o700)
    environment = isolated_environment(
        codex_home, extra={"DEEPTWIN_OFFLINE_FIXTURE": "1"}
    )
    marker = run_bounded_process(
        [*cli, "--version"],
        cwd=workspace,
        environment=environment,
        timeout_seconds=2,
        stdout_limit=1024,
        stderr_limit=1024,
    )
    if marker.exit_code != 0 or marker.stdout != OFFLINE_FIXTURE_VERSION:
        raise VerificationError(
            "refusing auth exercise: executable is not the DeepTwin offline fixture"
        )

    before = credential_file_state(codex_home)
    if before != {"exists": False}:
        raise VerificationError("offline fixture must start without auth state")
    signed_out = run_bounded_process(
        [*cli, "login", "status"],
        cwd=workspace,
        environment=environment,
        timeout_seconds=2,
        stdout_limit=4096,
        stderr_limit=4096,
    )
    if (
        signed_out.stop_reason is not None
        or signed_out.exit_code != 1
        or signed_out.stdout != b"Not logged in\n"
    ):
        raise VerificationError("offline fixture did not report a normal signed-out state")
    login = run_bounded_process(
        [*cli, "login", "--device-auth"],
        cwd=workspace,
        environment=environment,
        timeout_seconds=2,
        stdout_limit=4096,
        stderr_limit=4096,
    )
    after_login = credential_file_state(codex_home)
    if login.stop_reason is not None or login.exit_code != 0 or after_login != {
        "exists": True,
        "mode": "0600",
        "bytes_observed": False,
    }:
        raise VerificationError("offline fixture did not materialize a protected auth handle")
    signed_in = run_bounded_process(
        [*cli, "login", "status"],
        cwd=workspace,
        environment=environment,
        timeout_seconds=2,
        stdout_limit=4096,
        stderr_limit=4096,
    )
    if (
        signed_in.stop_reason is not None
        or signed_in.exit_code != 0
        or signed_in.stdout != b"Logged in\n"
    ):
        raise VerificationError("offline fixture does not reuse dedicated auth state")

    run = run_codex_jsonl(
        cli,
        prompt="offline fixture prompt",
        model="fixture-model",
        workspace=workspace,
        codex_home=codex_home,
        timeout_seconds=2,
        extra_environment={"DEEPTWIN_OFFLINE_FIXTURE": "1"},
    )
    if run["outcome"] != "completed":
        raise VerificationError("offline fixture JSONL run did not complete")
    logout = run_bounded_process(
        [*cli, "logout"],
        cwd=workspace,
        environment=environment,
        timeout_seconds=2,
        stdout_limit=4096,
        stderr_limit=4096,
    )
    after_logout = credential_file_state(codex_home)
    if (
        logout.stop_reason is not None
        or logout.exit_code != 0
        or after_logout != {"exists": False}
    ):
        raise VerificationError("offline fixture did not remove dedicated auth state")
    return {
        "fixture_marker_verified": True,
        "ambient_environment_inherited": False,
        "credential_bytes_observed": False,
        "before": before,
        "after_login": after_login,
        "after_logout": after_logout,
        "jsonl_run": run,
    }


def _command_minimal_runner(args: argparse.Namespace) -> dict[str, Any]:
    return verify_minimal_runner(
        args.manifest,
        args.artifacts_directory,
        args.cosign,
        locked=args.locked,
        allow_audit_verifier=args.allow_audit_verifier,
    )


def _command_jsonl(args: argparse.Namespace) -> dict[str, Any]:
    return validate_jsonl_bytes(
        args.input.read_bytes(), require_terminal=not args.allow_incomplete
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser(
        "minimal-runner", help="verify the complete two-platform standalone runner set"
    )
    runner.add_argument("--manifest", type=Path, required=True)
    runner.add_argument("--artifacts-directory", type=Path, required=True)
    runner.add_argument("--cosign", type=Path, required=True)
    runner.add_argument(
        "--locked",
        action="store_true",
        help="require the child build-input gate to be satisfied",
    )
    runner.add_argument(
        "--allow-audit-verifier",
        action="store_true",
        help=(
            "select only the locked Darwin audit verifier for offline evidence "
            "capture; this never qualifies a release-build verifier"
        ),
    )
    runner.set_defaults(handler=_command_minimal_runner)

    jsonl = commands.add_parser("jsonl", help="verify a captured JSONL stream")
    jsonl.add_argument("--input", type=Path, required=True)
    jsonl.add_argument("--allow-incomplete", action="store_true")
    jsonl.set_defaults(handler=_command_jsonl)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        report = args.handler(args)
    except (OSError, VerificationError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
