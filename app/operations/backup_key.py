"""backup-key-init: initialize the deployment's backup-key volume once
(T023 tail, OPS-AC07; operations.md §2 init-job semantics, §5 backup keys).

The separate `backup-key` volume holds the deployment's fixed
age-x25519-v1 identity. This job follows the `*-root-init` contract:
on ABSENT storage it creates `identity.age` (0600) and `manifest.json`
with O_EXCL, fsyncing both files and the directory; on the EXACT valid
existing state it verify-only no-ops, so stack-update reruns are
idempotent and never touch the key; ANY malformed state — a partial
pair, corrupt or foreign manifest, identity hash mismatch, loose
permissions, symlinks — fails WITHOUT replacing anything, because a
silently regenerated key would orphan every backup already encrypted to
the old identity. The generator is injected (production owns the real
`age-keygen` inside the networkless backup-crypto worker; this module
never spawns anything). The secret identity never appears in results,
errors or logs — only the public recipient and the identity's SHA-256.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_IDENTITY_NAME = "identity.age"
_MANIFEST_NAME = "manifest.json"
_IDENTITY_FORM = re.compile(r"AGE-SECRET-KEY-1[0-9A-Z]{10,200}\Z")
_RECIPIENT_FORM = re.compile(r"age1[0-9a-z]{10,200}\Z")
_PROFILE = "age-x25519-v1"
_KEY_MODE = "instance_backup_key"
_JOB = "backup-key-init"
_SCHEMA_VERSION = 1


class BackupKeyInitError(RuntimeError):
    """The volume state or generator output violates the init contract."""


@dataclass(frozen=True, slots=True)
class BackupKeyState:
    """The public outcome: status, recipient and identity hash — no secret."""

    status: str  # "created" | "verified"
    recipient: str
    identity_sha256: str


def _default_clock() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _validated_generated(generated) -> tuple[str, str]:
    if type(generated) is not dict or set(generated) != {"identity", "recipient"}:
        raise BackupKeyInitError("the generator must return identity and recipient")
    identity, recipient = generated["identity"], generated["recipient"]
    if type(identity) is not str or _IDENTITY_FORM.fullmatch(identity) is None:
        raise BackupKeyInitError("the generated identity is not an age-x25519-v1 secret")
    if type(recipient) is not str or _RECIPIENT_FORM.fullmatch(recipient) is None:
        raise BackupKeyInitError("the generated recipient is not an age recipient")
    return identity, recipient


def _write_excl(path: Path, body: bytes, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, mode)
    try:
        os.write(descriptor, body)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(root: Path) -> None:
    descriptor = os.open(root, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_existing(identity_path: Path, manifest_path: Path) -> BackupKeyState:
    for path in (identity_path, manifest_path):
        if path.is_symlink():
            raise BackupKeyInitError(f"{path.name} is a symlink")
    identity_info = identity_path.lstat()
    if stat.S_IMODE(identity_info.st_mode) != 0o600:
        raise BackupKeyInitError("the identity permissions are not 0600")
    try:
        manifest = json.loads(manifest_path.read_bytes())
    except (OSError, ValueError) as exc:
        raise BackupKeyInitError("the manifest is unreadable") from exc
    if type(manifest) is not dict:
        raise BackupKeyInitError("the manifest is not an object")
    expected_shape = {
        "schema_version": _SCHEMA_VERSION,
        "job": _JOB,
        "key_mode": _KEY_MODE,
        "encryption_profile_ref": _PROFILE,
    }
    for key, expected in expected_shape.items():
        if manifest.get(key) != expected:
            raise BackupKeyInitError(f"the manifest {key} does not match this job")
    recipient = manifest.get("recipient")
    recorded_sha = manifest.get("identity_sha256")
    if (
        type(recipient) is not str
        or _RECIPIENT_FORM.fullmatch(recipient) is None
        or type(recorded_sha) is not str
    ):
        raise BackupKeyInitError("the manifest key material records are malformed")
    actual_sha = hashlib.sha256(identity_path.read_bytes()).hexdigest()
    if actual_sha != recorded_sha:
        raise BackupKeyInitError("the identity does not match its recorded hash")
    body = identity_path.read_text()
    if not body.endswith("\n") or _IDENTITY_FORM.fullmatch(body[:-1]) is None:
        raise BackupKeyInitError("the identity file is not a single age secret line")
    return BackupKeyState(
        status="verified", recipient=recipient, identity_sha256=actual_sha,
    )


def initialize_backup_key(volume_root, *, keygen, clock=None) -> BackupKeyState:
    root = Path(volume_root)
    if root.is_symlink():
        raise BackupKeyInitError("the backup-key volume is a symlink")
    if not root.is_dir():
        # The deployment authority mounts the volume; this job never
        # creates storage locations of its own.
        raise BackupKeyInitError("the backup-key volume is not mounted")
    identity_path = root / _IDENTITY_NAME
    manifest_path = root / _MANIFEST_NAME
    identity_exists = identity_path.is_symlink() or identity_path.exists()
    manifest_exists = manifest_path.is_symlink() or manifest_path.exists()
    if identity_exists and manifest_exists:
        return _verify_existing(identity_path, manifest_path)
    if identity_exists or manifest_exists:
        # A partial pair is a malformed state: never repaired, never
        # replaced — the deployment authority resolves it explicitly.
        raise BackupKeyInitError(
            "the backup-key volume holds a partial state; refusing to replace"
        )
    identity, recipient = _validated_generated(keygen())
    identity_body = (identity + "\n").encode("utf-8")
    identity_sha = hashlib.sha256(identity_body).hexdigest()
    manifest = {
        "schema_version": _SCHEMA_VERSION,
        "job": _JOB,
        "key_mode": _KEY_MODE,
        "encryption_profile_ref": _PROFILE,
        "recipient": recipient,
        "identity_sha256": identity_sha,
        "created_at": (clock or _default_clock)(),
    }
    _write_excl(identity_path, identity_body, 0o600)
    _write_excl(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        0o644,
    )
    _fsync_directory(root)
    return BackupKeyState(
        status="created", recipient=recipient, identity_sha256=identity_sha,
    )
