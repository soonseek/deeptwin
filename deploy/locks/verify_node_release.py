#!/usr/bin/env python3
"""Offline verifier for the Node runtime pinned by the browser worker.

The verifier connects four independently checked facts:

1. the repository-pinned Node release keyring verifies the repository-pinned
   clear-signed SHASUMS file with the exact expected signer and timestamp;
2. both caller-supplied Linux archives match entries in that authenticated
   checksum list as well as their manifest byte counts and hashes;
3. every effective tar member stays below the one expected distribution root,
   without duplicate paths, unsafe links, special files, or traversal; and
4. the regular ``bin/node`` and top-level ``LICENSE`` members match their exact
   manifest records.

No network operation is implemented. The gpgv executable is an explicit input:
its real path, byte count, SHA-256, and exact first version line are checked and
reported. This records the verifier runtime without pretending that a checksum
alone establishes its upstream provenance.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Callable, Mapping, Sequence


EXPECTED_NODE_VERSION = "24.20.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
FINGERPRINT40 = re.compile(r"^[0-9A-F]{40}$")
CHECKSUM_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._+/\-]*)$")
EXPECTED_PLATFORMS = {("linux", "amd64"), ("linux", "arm64")}
ARCHIVE_SUFFIX = {"amd64": "x64", "arm64": "arm64"}
MAX_ARCHIVE_MEMBERS = 10_000
MAX_DECLARED_UNPACKED_BYTES = 1_073_741_824
MAX_MEMBER_NAME_BYTES = 4096
MAX_GPG_OUTPUT_BYTES = 1_048_576
GPG_FAILURE_TAGS = {
    "BADSIG",
    "ERRSIG",
    "EXPSIG",
    "EXPKEYSIG",
    "REVKEYSIG",
    "NO_PUBKEY",
    "NODATA",
    "FAILURE",
    "UNEXPECTED",
}


class NodeReleaseVerificationError(ValueError):
    """One fail-closed Node release invariant was not met."""

    def __init__(self, code: str, location: str, detail: str) -> None:
        super().__init__(f"{location}: {detail}")
        self.code = code
        self.location = location
        self.detail = detail


def fail(code: str, location: str, detail: str) -> None:
    raise NodeReleaseVerificationError(code, location, detail)


def require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        fail("invalid_structure", location, "expected object")
    return value


def require_list(value: Any, location: str) -> list[Any]:
    if not isinstance(value, list):
        fail("invalid_structure", location, "expected array")
    return value


def require_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value:
        fail("invalid_structure", location, "expected non-empty string")
    return value


def require_integer(value: Any, location: str, *, positive: bool = True) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or (positive and value <= 0):
        fail("invalid_structure", location, "expected positive integer")
    return value


def require_equal(actual: Any, expected: Any, location: str) -> None:
    if actual != expected:
        fail(
            "identity_mismatch",
            location,
            f"expected {expected!r}, observed {actual!r}",
        )


def require_sha256(value: Any, location: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        fail("invalid_digest", location, "expected lowercase full SHA-256")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_stream(stream: Any) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("duplicate_json_key", "manifest", f"duplicate key {key!r}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        fail("file_read_failed", str(path), str(exc))
    if raw.startswith(b"\xef\xbb\xbf"):
        fail("invalid_json", str(path), "UTF-8 BOM is forbidden")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_float=lambda _: fail("invalid_json", "manifest", "floats are forbidden"),
            parse_constant=lambda _: fail(
                "invalid_json", "manifest", "non-finite values are forbidden"
            ),
        )
    except UnicodeDecodeError as exc:
        fail("invalid_json", str(path), f"invalid UTF-8: {exc}")
    except json.JSONDecodeError as exc:
        fail("invalid_json", str(path), str(exc))
    return require_object(value, "manifest")


def _safe_repo_relative(value: Any, location: str) -> PurePosixPath:
    text = require_string(value, location)
    if "\\" in text or "\x00" in text:
        fail("unsafe_repository_path", location, "backslash/NUL is forbidden")
    relative = PurePosixPath(text)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        fail("unsafe_repository_path", location, "path must be normalized and relative")
    if relative.as_posix() != text:
        fail("unsafe_repository_path", location, "path is not canonical POSIX form")
    return relative


def verify_repo_file(
    root: Path,
    reference: Mapping[str, Any],
    location: str,
) -> Path:
    relative = _safe_repo_relative(reference.get("path"), f"{location}.path")
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            fail("file_read_failed", f"{location}.path", str(exc))
        if stat.S_ISLNK(metadata.st_mode):
            fail(
                "unsafe_repository_path",
                f"{location}.path",
                f"symlink component at {'/'.join(relative.parts[: index + 1])}",
            )
    if not stat.S_ISREG(current.lstat().st_mode):
        fail("unsafe_repository_path", f"{location}.path", "expected regular file")
    require_equal(
        current.stat().st_size,
        require_integer(reference.get("bytes"), f"{location}.bytes"),
        f"{location}.bytes",
    )
    require_equal(
        sha256_file(current),
        require_sha256(reference.get("sha256"), f"{location}.sha256"),
        f"{location}.sha256",
    )
    return current


def verify_external_regular_file(path: Path, location: str) -> Path:
    if not path.is_absolute():
        fail("unsafe_input_path", location, "explicit input path must be absolute")
    try:
        metadata = path.lstat()
    except OSError as exc:
        fail("file_read_failed", location, str(exc))
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        fail("unsafe_input_path", location, "expected a non-symlink regular file")
    if path.resolve() != path:
        fail("unsafe_input_path", location, "resolved path differs from explicit path")
    return path


@dataclass(frozen=True)
class GpgvDescriptor:
    path: Path
    version_line: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class GpgvObservation:
    path: str
    version_line: str
    bytes: int
    sha256: str
    signer_fingerprint: str
    signature_time_utc: str


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def _run_bounded(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    runner: CommandRunner,
) -> subprocess.CompletedProcess[str]:
    try:
        result = runner(
            list(command),
            cwd=str(cwd),
            env=dict(environment),
            text=True,
            encoding="utf-8",
            errors="strict",
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        fail("gpgv_execution_failed", "gpgv", str(exc))
    if len(result.stdout.encode("utf-8")) + len(result.stderr.encode("utf-8")) > MAX_GPG_OUTPUT_BYTES:
        fail("gpgv_execution_failed", "gpgv", "output exceeded bounded limit")
    return result


def _parse_gpgv_status(
    status_output: str,
    *,
    expected_fingerprint: str,
    expected_time_utc: str,
) -> tuple[str, str]:
    records: list[tuple[str, list[str]]] = []
    for line in status_output.splitlines():
        if not line.startswith("[GNUPG:] "):
            fail("unexpected_gpgv_output", "gpgv.status", f"non-status stdout line {line!r}")
        fields = line.removeprefix("[GNUPG:] ").split()
        if not fields:
            fail("unexpected_gpgv_output", "gpgv.status", "empty status record")
        records.append((fields[0], fields[1:]))
    tags = [tag for tag, _ in records]
    bad = sorted(set(tags) & GPG_FAILURE_TAGS)
    if bad:
        fail("openpgp_verification_failed", "gpgv.status", f"failure tags {bad}")
    valid = [fields for tag, fields in records if tag == "VALIDSIG"]
    good = [fields for tag, fields in records if tag == "GOODSIG"]
    if len(valid) != 1 or len(good) != 1:
        fail(
            "ambiguous_openpgp_signature",
            "gpgv.status",
            f"expected one GOODSIG and one VALIDSIG, observed {len(good)} and {len(valid)}",
        )
    fields = valid[0]
    if len(fields) < 10 or FINGERPRINT40.fullmatch(fields[0]) is None:
        fail("unexpected_gpgv_output", "gpgv.VALIDSIG", "malformed VALIDSIG record")
    fingerprint = fields[0]
    primary_fingerprint = fields[-1]
    if primary_fingerprint != fingerprint:
        fail(
            "ambiguous_openpgp_signature",
            "gpgv.VALIDSIG",
            "signing subkey and primary fingerprint differ; manifest must model both explicitly",
        )
    require_equal(fingerprint, expected_fingerprint, "gpgv.VALIDSIG.fingerprint")
    good_key_id = good[0][0] if good[0] else ""
    if not good_key_id or not fingerprint.endswith(good_key_id):
        fail(
            "ambiguous_openpgp_signature",
            "gpgv.GOODSIG.key_id",
            "GOODSIG key id does not identify the VALIDSIG fingerprint",
        )
    try:
        timestamp = int(fields[2])
        observed_time = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (ValueError, OverflowError) as exc:
        fail("unexpected_gpgv_output", "gpgv.VALIDSIG.timestamp", str(exc))
    require_equal(observed_time, expected_time_utc, "gpgv.VALIDSIG.signature_time_utc")
    return fingerprint, observed_time


def verify_gpgv(
    descriptor: GpgvDescriptor,
    *,
    keyring_path: Path,
    signed_checksums_path: Path,
    expected_fingerprint: str,
    expected_time_utc: str,
    runner: CommandRunner = subprocess.run,
) -> GpgvObservation:
    executable = verify_external_regular_file(descriptor.path, "gpgv.path")
    metadata = executable.stat()
    if metadata.st_mode & 0o111 == 0:
        fail("unsafe_input_path", "gpgv.path", "gpgv is not executable")
    require_equal(metadata.st_size, require_integer(descriptor.bytes, "gpgv.bytes"), "gpgv.bytes")
    require_equal(sha256_file(executable), require_sha256(descriptor.sha256, "gpgv.sha256"), "gpgv.sha256")
    expected_version = require_string(descriptor.version_line, "gpgv.version_line")

    base_environment = {
        "LC_ALL": "C",
        "LANG": "C",
        "PATH": os.defpath,
    }
    with tempfile.TemporaryDirectory(prefix="deeptwin-node-gpgv-") as home_text:
        home = Path(home_text)
        home.chmod(0o700)
        version_result = _run_bounded(
            [str(executable), "--version"],
            cwd=home,
            environment={**base_environment, "GNUPGHOME": str(home)},
            runner=runner,
        )
        if version_result.returncode != 0:
            fail("gpgv_execution_failed", "gpgv.version", f"exit {version_result.returncode}")
        version_lines = version_result.stdout.splitlines()
        if not version_lines:
            fail("gpgv_execution_failed", "gpgv.version", "missing version output")
        require_equal(version_lines[0], expected_version, "gpgv.version_line")

        result = _run_bounded(
            [
                str(executable),
                "--homedir",
                str(home),
                "--keyring",
                str(keyring_path),
                "--status-fd",
                "1",
                str(signed_checksums_path),
            ],
            cwd=home,
            environment={**base_environment, "GNUPGHOME": str(home)},
            runner=runner,
        )
    if result.returncode != 0:
        fail("openpgp_verification_failed", "gpgv", f"exit {result.returncode}")
    fingerprint, observed_time = _parse_gpgv_status(
        result.stdout,
        expected_fingerprint=expected_fingerprint,
        expected_time_utc=expected_time_utc,
    )
    return GpgvObservation(
        path=str(executable),
        version_line=expected_version,
        bytes=metadata.st_size,
        sha256=descriptor.sha256,
        signer_fingerprint=fingerprint,
        signature_time_utc=observed_time,
    )


def parse_clearsigned_checksums(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        fail("invalid_signed_checksums", "signed_checksums", str(exc))
    lines = text.splitlines()
    if not lines or lines[0] != "-----BEGIN PGP SIGNED MESSAGE-----":
        fail("invalid_signed_checksums", "signed_checksums", "missing clear-sign header")
    index = 1
    headers: list[str] = []
    while index < len(lines) and lines[index] != "":
        headers.append(lines[index])
        index += 1
    if index >= len(lines) or headers != ["Hash: SHA256"]:
        fail("invalid_signed_checksums", "signed_checksums", "expected exact SHA256 armor header")
    index += 1
    body: list[str] = []
    while index < len(lines) and lines[index] != "-----BEGIN PGP SIGNATURE-----":
        line = lines[index]
        if line.startswith("- "):
            line = line[2:]
        elif line.startswith("-"):
            fail("invalid_signed_checksums", "signed_checksums", "invalid dash-escaped line")
        body.append(line)
        index += 1
    if index >= len(lines):
        fail("invalid_signed_checksums", "signed_checksums", "missing signature armor")
    if (
        lines.count("-----BEGIN PGP SIGNATURE-----") != 1
        or lines.count("-----END PGP SIGNATURE-----") != 1
        or lines[-1] != "-----END PGP SIGNATURE-----"
    ):
        fail(
            "invalid_signed_checksums",
            "signed_checksums",
            "signature armor must be unique and end the file",
        )
    checksums: dict[str, str] = {}
    for line_number, line in enumerate(body, 1):
        if not line:
            continue
        match = CHECKSUM_LINE.fullmatch(line)
        if match is None:
            fail(
                "invalid_signed_checksums",
                f"signed_checksums.body[{line_number}]",
                "noncanonical checksum row",
            )
        digest, filename = match.groups()
        filename_path = PurePosixPath(filename)
        if (
            filename_path.is_absolute()
            or any(part in {"", ".", ".."} for part in filename_path.parts)
            or filename_path.as_posix() != filename
        ):
            fail(
                "invalid_signed_checksums",
                f"signed_checksums.body[{line_number}]",
                "unsafe or noncanonical checksum filename",
            )
        if filename in checksums:
            fail("duplicate_signed_checksum", "signed_checksums", f"duplicate {filename}")
        checksums[filename] = digest
    if not checksums:
        fail("invalid_signed_checksums", "signed_checksums", "empty checksum list")
    return checksums


def _safe_member_name(name: str, expected_root: str, location: str) -> str:
    if not name or "\\" in name or "\x00" in name or any(ord(char) < 32 for char in name):
        fail("unsafe_archive_member", location, "empty/control/backslash member name")
    if len(name.encode("utf-8")) > MAX_MEMBER_NAME_BYTES:
        fail("unsafe_archive_member", location, "member name is too long")
    normalized_input = name.rstrip("/")
    path = PurePosixPath(normalized_input)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        fail("unsafe_archive_member", location, f"unsafe path {name!r}")
    if path.as_posix() != normalized_input or not path.parts or path.parts[0] != expected_root:
        fail("unsafe_archive_member", location, f"member escapes expected root {expected_root!r}")
    return path.as_posix()


def _resolve_safe_link(member_name: str, link_name: str, expected_root: str, location: str) -> str:
    if (
        not link_name
        or "\\" in link_name
        or "\x00" in link_name
        or any(ord(char) < 32 for char in link_name)
        or len(link_name.encode("utf-8")) > MAX_MEMBER_NAME_BYTES
    ):
        fail("unsafe_archive_link", location, "empty/control/backslash/oversized link target")
    target = PurePosixPath(link_name)
    if target.is_absolute():
        fail("unsafe_archive_link", location, "absolute link target")
    stack = list(PurePosixPath(member_name).parent.parts)
    for part in target.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if len(stack) <= 1:
                fail("unsafe_archive_link", location, "link target escapes distribution root")
            stack.pop()
        else:
            stack.append(part)
    if not stack or stack[0] != expected_root:
        fail("unsafe_archive_link", location, "link target escapes distribution root")
    return PurePosixPath(*stack).as_posix()


def verify_archive(
    archive_path: Path,
    platform: Mapping[str, Any],
    *,
    version: str,
    license_digest: str,
    license_bytes: int,
) -> dict[str, Any]:
    architecture = require_string(platform.get("architecture"), "node.platform.architecture")
    suffix = ARCHIVE_SUFFIX.get(architecture)
    if suffix is None:
        fail("unsupported_platform", "node.platform.architecture", architecture)
    expected_filename = f"node-v{version}-linux-{suffix}.tar.xz"
    require_equal(archive_path.name, expected_filename, f"node.platforms.{architecture}.archive_filename")
    archive_path = verify_external_regular_file(archive_path, f"node.platforms.{architecture}.archive_path")
    require_equal(
        archive_path.stat().st_size,
        require_integer(platform.get("archive_bytes"), f"node.platforms.{architecture}.archive_bytes"),
        f"node.platforms.{architecture}.archive_bytes",
    )
    require_equal(
        sha256_file(archive_path),
        require_sha256(platform.get("archive_sha256"), f"node.platforms.{architecture}.archive_sha256"),
        f"node.platforms.{architecture}.archive_sha256",
    )

    executable_path = require_string(
        platform.get("executable_path"), f"node.platforms.{architecture}.executable_path"
    )
    expected_root = f"node-v{version}-linux-{suffix}"
    require_equal(executable_path, f"{expected_root}/bin/node", f"node.platforms.{architecture}.executable_path")
    expected_license_path = f"{expected_root}/LICENSE"

    names: dict[str, tarfile.TarInfo] = {}
    safe_links: list[tuple[str, str]] = []
    total_bytes = 0
    try:
        with tarfile.open(archive_path, mode="r:xz") as archive:
            for index, member in enumerate(archive):
                if index >= MAX_ARCHIVE_MEMBERS:
                    fail("archive_limit_exceeded", f"archive.{architecture}", "too many members")
                location = f"archive.{architecture}.members[{index}]"
                canonical_name = _safe_member_name(member.name, expected_root, location)
                if canonical_name in names:
                    fail("duplicate_archive_member", location, canonical_name)
                if member.pax_headers or member.sparse:
                    fail("unsafe_archive_member", location, "PAX/sparse metadata is forbidden")
                if member.mode & 0o7000:
                    fail("unsafe_archive_member", location, "special permission bits are forbidden")
                if not (member.isdir() or member.isreg() or member.issym()):
                    fail("unsafe_archive_member", location, "only directory, regular file, and symlink are allowed")
                if member.size < 0:
                    fail("unsafe_archive_member", location, "negative member size")
                total_bytes += member.size
                if total_bytes > MAX_DECLARED_UNPACKED_BYTES:
                    fail("archive_limit_exceeded", f"archive.{architecture}", "declared bytes exceed limit")
                names[canonical_name] = member
                if member.issym():
                    safe_links.append(
                        (
                            canonical_name,
                            _resolve_safe_link(canonical_name, member.linkname, expected_root, location),
                        )
                    )

            for link_name, target_name in safe_links:
                target = names.get(target_name)
                if target is None or not target.isreg():
                    fail(
                        "unsafe_archive_link",
                        f"archive.{architecture}.{link_name}",
                        "link target is not a regular member in the archive",
                    )

            executable = names.get(executable_path)
            license_member = names.get(expected_license_path)
            if executable is None or not executable.isreg():
                fail("missing_archive_member", f"archive.{architecture}", executable_path)
            if license_member is None or not license_member.isreg():
                fail("missing_archive_member", f"archive.{architecture}", expected_license_path)
            require_equal(executable.mode, 0o755, f"archive.{architecture}.node.mode")
            require_equal(license_member.mode, 0o644, f"archive.{architecture}.license.mode")
            require_equal(
                executable.size,
                require_integer(platform.get("executable_bytes"), f"node.platforms.{architecture}.executable_bytes"),
                f"archive.{architecture}.node.bytes",
            )
            require_equal(license_member.size, license_bytes, f"archive.{architecture}.license.bytes")
            executable_stream = archive.extractfile(executable)
            license_stream = archive.extractfile(license_member)
            if executable_stream is None or license_stream is None:
                fail("archive_read_failed", f"archive.{architecture}", "required member stream missing")
            with executable_stream, license_stream:
                executable_digest = sha256_stream(executable_stream)
                observed_license_digest = sha256_stream(license_stream)
            require_equal(
                executable_digest,
                require_sha256(platform.get("executable_sha256"), f"node.platforms.{architecture}.executable_sha256"),
                f"archive.{architecture}.node.sha256",
            )
            require_equal(observed_license_digest, license_digest, f"archive.{architecture}.license.sha256")
    except NodeReleaseVerificationError:
        raise
    except (tarfile.TarError, OSError, EOFError, ValueError) as exc:
        fail("archive_read_failed", f"archive.{architecture}", str(exc))

    return {
        "platform": f"linux/{architecture}",
        "archive_filename": expected_filename,
        "archive_bytes": archive_path.stat().st_size,
        "archive_sha256": platform["archive_sha256"],
        "member_count": len(names),
        "declared_unpacked_bytes": total_bytes,
        "node_path": executable_path,
        "node_bytes": platform["executable_bytes"],
        "node_sha256": platform["executable_sha256"],
        "license_path": expected_license_path,
        "license_bytes": license_bytes,
        "license_sha256": license_digest,
    }


def _platform_map(values: Any, location: str) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw in enumerate(require_list(values, location)):
        value = require_object(raw, f"{location}[{index}]")
        key = (
            require_string(value.get("os"), f"{location}[{index}].os"),
            require_string(value.get("architecture"), f"{location}[{index}].architecture"),
        )
        if key in result:
            fail("duplicate_platform", f"{location}[{index}]", repr(key))
        result[key] = value
    if set(result) != EXPECTED_PLATFORMS:
        fail("platform_coverage_mismatch", location, f"expected {sorted(EXPECTED_PLATFORMS)}, observed {sorted(result)}")
    return result


def _validate_archive_url(value: Any, *, version: str, filename: str, location: str) -> None:
    expected = f"https://nodejs.org/dist/v{version}/{filename}"
    if require_string(value, location) != expected:
        fail("untrusted_archive_url", location, f"expected exact URL {expected!r}")


def verify_node_release(
    manifest: Mapping[str, Any],
    *,
    repository_root: Path,
    archive_paths: Mapping[str, Path],
    gpgv: GpgvDescriptor,
    runner: CommandRunner = subprocess.run,
) -> dict[str, Any]:
    root = repository_root.resolve(strict=True)
    node = require_object(require_object(manifest, "manifest").get("node"), "manifest.node")
    version = require_string(node.get("version"), "manifest.node.version")
    require_equal(version, EXPECTED_NODE_VERSION, "manifest.node.version")
    provenance = require_object(node.get("official_release_provenance"), "manifest.node.official_release_provenance")
    require_equal(provenance.get("source_repository"), "https://github.com/nodejs/node", "node.provenance.source_repository")
    require_equal(provenance.get("source_tag"), f"v{version}", "node.provenance.source_tag")
    if not isinstance(provenance.get("source_commit"), str) or HEX40.fullmatch(provenance["source_commit"]) is None:
        fail("invalid_source_commit", "node.provenance.source_commit", "expected full lowercase Git commit")

    signed = require_object(provenance.get("signed_checksums"), "node.provenance.signed_checksums")
    require_equal(signed.get("openpgp_verified"), True, "node.provenance.signed_checksums.openpgp_verified")
    fingerprint = require_string(signed.get("signer_fingerprint"), "node.provenance.signer_fingerprint")
    if FINGERPRINT40.fullmatch(fingerprint) is None:
        fail("invalid_fingerprint", "node.provenance.signer_fingerprint", fingerprint)
    signature_time = require_string(signed.get("signature_time_utc"), "node.provenance.signature_time_utc")
    try:
        parsed_time = datetime.strptime(signature_time, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        fail("invalid_signature_time", "node.provenance.signature_time_utc", str(exc))
    if parsed_time.strftime("%Y-%m-%dT%H:%M:%SZ") != signature_time:
        fail("invalid_signature_time", "node.provenance.signature_time_utc", "noncanonical UTC timestamp")

    signed_path = verify_repo_file(root, signed, "node.provenance.signed_checksums")
    keyring = require_object(provenance.get("verification_keyring"), "node.provenance.verification_keyring")
    require_equal(keyring.get("source_repository"), "https://github.com/nodejs/release-keys", "node.provenance.verification_keyring.source_repository")
    if not isinstance(keyring.get("source_commit"), str) or HEX40.fullmatch(keyring["source_commit"]) is None:
        fail("invalid_source_commit", "node.provenance.verification_keyring.source_commit", "expected full lowercase Git commit")
    require_equal(keyring.get("source_path"), "gpg/pubring.kbx", "node.provenance.verification_keyring.source_path")
    keyring_path = verify_repo_file(root, keyring, "node.provenance.verification_keyring")

    license_reference = require_object(provenance.get("license"), "node.provenance.license")
    require_equal(license_reference.get("identical_in_both_platform_archives"), True, "node.provenance.license.identical_in_both_platform_archives")
    license_path = verify_repo_file(root, license_reference, "node.provenance.license")
    license_bytes = require_integer(license_reference.get("bytes"), "node.provenance.license.bytes")
    license_digest = require_sha256(license_reference.get("sha256"), "node.provenance.license.sha256")

    observation = verify_gpgv(
        gpgv,
        keyring_path=keyring_path,
        signed_checksums_path=signed_path,
        expected_fingerprint=fingerprint,
        expected_time_utc=signature_time,
        runner=runner,
    )
    signed_checksums = parse_clearsigned_checksums(signed_path.read_bytes())

    platforms = _platform_map(provenance.get("platforms"), "node.provenance.platforms")
    base_image = require_object(node.get("base_image"), "manifest.node.base_image")
    base_platforms = _platform_map(base_image.get("platforms"), "node.base_image.platforms")
    if set(archive_paths) != {"amd64", "arm64"}:
        fail("platform_coverage_mismatch", "archive_paths", "exact amd64 and arm64 inputs required")
    archive_inodes: set[tuple[int, int]] = set()
    platform_results: list[dict[str, Any]] = []
    for architecture in ("amd64", "arm64"):
        platform = platforms[("linux", architecture)]
        base = base_platforms[("linux", architecture)]
        require_equal(base.get("os"), platform.get("os"), f"node.base_image.platforms.{architecture}.os")
        require_equal(base.get("architecture"), architecture, f"node.base_image.platforms.{architecture}.architecture")
        require_equal(platform.get("base_image_executable_sha256_match"), True, f"node.provenance.platforms.{architecture}.base_image_executable_sha256_match")
        archive_path = verify_external_regular_file(archive_paths[architecture], f"archive_paths.{architecture}")
        metadata = archive_path.stat()
        inode = (metadata.st_dev, metadata.st_ino)
        if inode in archive_inodes:
            fail("duplicate_archive_input", f"archive_paths.{architecture}", "both platforms resolve to one file")
        archive_inodes.add(inode)
        filename = f"node-v{version}-linux-{ARCHIVE_SUFFIX[architecture]}.tar.xz"
        _validate_archive_url(
            platform.get("archive_url"),
            version=version,
            filename=filename,
            location=f"node.provenance.platforms.{architecture}.archive_url",
        )
        signed_digest = signed_checksums.get(filename)
        if signed_digest is None:
            fail("missing_signed_checksum", "signed_checksums", filename)
        require_equal(
            signed_digest,
            require_sha256(platform.get("archive_sha256"), f"node.provenance.platforms.{architecture}.archive_sha256"),
            f"signed_checksums.{filename}",
        )
        platform_results.append(
            verify_archive(
                archive_path,
                platform,
                version=version,
                license_digest=license_digest,
                license_bytes=license_bytes,
            )
        )

    return {
        "schema_version": "deeptwin-node-release-verification-v1",
        "verified": True,
        "network_used": False,
        "node_version": version,
        "source_repository": provenance["source_repository"],
        "source_tag": provenance["source_tag"],
        "source_commit": provenance["source_commit"],
        "signed_checksums": {
            "path": signed["path"],
            "bytes": signed["bytes"],
            "sha256": signed["sha256"],
            "signer_fingerprint": observation.signer_fingerprint,
            "signature_time_utc": observation.signature_time_utc,
        },
        "gpgv": {
            "path": observation.path,
            "version_line": observation.version_line,
            "bytes": observation.bytes,
            "sha256": observation.sha256,
            "assurance_boundary": "exact executable observation; upstream provenance is a separate release input",
        },
        "verification_keyring": {
            "path": keyring["path"],
            "bytes": keyring["bytes"],
            "sha256": keyring["sha256"],
            "source_commit": keyring["source_commit"],
        },
        "license": {
            "path": str(license_path.relative_to(root)),
            "bytes": license_bytes,
            "sha256": license_digest,
        },
        "platforms": platform_results,
        "base_image_match_claim_rechecked": True,
        "assurance_boundary": (
            "OpenPGP authenticates the selected archive checksums and this verifier checks archive members; "
            "the manifest's separately observed OCI executable match still depends on the pinned OCI descriptor verification"
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="repository root",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("deploy/manifests/browser-worker.json"),
        help="browser-worker manifest, relative to --root unless absolute",
    )
    parser.add_argument("--archive-amd64", type=Path, required=True)
    parser.add_argument("--archive-arm64", type=Path, required=True)
    parser.add_argument("--gpgv", type=Path, required=True)
    parser.add_argument("--gpgv-version-line", required=True)
    parser.add_argument("--gpgv-bytes", type=int, required=True)
    parser.add_argument("--gpgv-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    manifest_path = args.manifest if args.manifest.is_absolute() else root / args.manifest
    expected_manifest_path = root / "deploy/manifests/browser-worker.json"
    try:
        if manifest_path.resolve(strict=True) != expected_manifest_path.resolve(strict=True):
            fail("unexpected_manifest", "manifest", "expected repository browser-worker manifest")
        result = verify_node_release(
            load_json(manifest_path),
            repository_root=root,
            archive_paths={
                "amd64": args.archive_amd64,
                "arm64": args.archive_arm64,
            },
            gpgv=GpgvDescriptor(
                path=args.gpgv,
                version_line=args.gpgv_version_line,
                bytes=args.gpgv_bytes,
                sha256=args.gpgv_sha256,
            ),
        )
    except (NodeReleaseVerificationError, OSError) as exc:
        if isinstance(exc, NodeReleaseVerificationError):
            error = {"code": exc.code, "location": exc.location, "detail": exc.detail}
        else:
            error = {"code": "file_read_failed", "location": "input", "detail": str(exc)}
        sys.stderr.write(
            json.dumps(
                {
                    "schema_version": "deeptwin-node-release-verification-v1",
                    "verified": False,
                    "error": error,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        )
        return 1
    sys.stdout.write(
        json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
