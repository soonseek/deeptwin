"""The backup-crypto worker's one-operation dialogue (T070; operations.md §5.2).

`BackupCryptoService` holds the verified age runtime and the path of the read-only
backup-key volume. It is the only code that reads the instance identity: per operation
it verifies the exact `backup-key-init` pair (`identity.age` + `manifest.json`), reads
the identity into memory, hands it to age through an owned descriptor
(`backup_crypto.AgeRuntime`) and drops it. A missing, partial or altered volume answers
`key_unavailable` (no regeneration: backup-key-init owns genesis). The dialogue itself
is `app.workers.backup_stream`; the service never opens a file the request names,
never writes anywhere, and returns only ciphertext, archive bytes, the recipient and
closed failure codes.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..operations.backup_key import BackupKeyInitError, _verify_existing
from . import backup_stream as stream
from .backup_crypto import (
    AgeRuntime,
    BackupCryptoError,
    require_identity,
    require_recipient,
)

KEY_FILES = frozenset({"identity.age", "manifest.json"})

__all__ = ["KEY_FILES", "BackupCryptoService", "BackupKeyRootError", "check_key_root"]


class BackupKeyRootError(RuntimeError):
    """The key root is not the exact read-only backup-key volume."""


def check_key_root(key_root: Path) -> bool:
    """Whether the key volume is present; raises when it is something else.

    Present means exactly the two backup-key-init files on a read-only mount, or in a
    directory whose mode grants no write at all (0500). Any other content —
    for example a provider credential root or its records — refuses the start, so the
    worker is never pointed at credential material. Absent is allowed: the worker then
    serves and answers every keyed operation `key_unavailable`.
    """

    key_root = Path(key_root)
    if key_root.is_symlink():
        raise BackupKeyRootError("the backup-key root is a symlink")
    if not key_root.exists():
        return False
    if not key_root.is_dir():
        raise BackupKeyRootError("the backup-key root is not a directory")
    names = set(os.listdir(key_root))
    if not names:
        return False
    if names != KEY_FILES:
        raise BackupKeyRootError("the backup-key root holds something other than the backup key")
    info = os.stat(key_root, follow_symlinks=False)
    read_only = bool(os.statvfs(key_root).f_flag & os.ST_RDONLY) or not (info.st_mode & 0o222)
    if not read_only:
        raise BackupKeyRootError("the backup-key root is writable by the worker")
    return True


class BackupCryptoService:
    def __init__(self, runtime: AgeRuntime, key_root: Path):
        if type(runtime) is not AgeRuntime:
            raise TypeError("the verified age runtime is required")
        self._runtime = runtime
        self._key_root = Path(key_root)

    # --- the key volume, read per operation -------------------------------------------

    def _recipient(self) -> str:
        try:
            if not check_key_root(self._key_root):
                raise stream.BackupStreamError("key_unavailable")
            state = _verify_existing(self._key_root / "identity.age", self._key_root / "manifest.json")
            return require_recipient(state.recipient)
        except (BackupKeyInitError, BackupKeyRootError, BackupCryptoError, OSError):
            raise stream.BackupStreamError("key_unavailable") from None

    def _identity(self) -> bytes:
        self._recipient()
        try:
            return require_identity((self._key_root / "identity.age").read_bytes())
        except (BackupCryptoError, OSError):
            raise stream.BackupStreamError("key_unavailable") from None

    # --- one operation ------------------------------------------------------------------

    def run(self, request: dict, body: bytes) -> tuple[bytes, str | None]:
        """The result body and recipient of one checked request (closed failures)."""

        op, portable = request["op"], request["key_mode"] == "portable_recovery"
        if op == "describe":
            return b"", self._recipient()
        if op == "encrypt":
            try:
                recipient = require_recipient(request["recipient"]) if portable else self._recipient()
            except BackupCryptoError:
                raise stream.BackupStreamError("request_invalid") from None
            try:
                return self._runtime.encrypt(body, recipient), recipient
            except BackupCryptoError:
                raise stream.BackupStreamError("encrypt_failed") from None
        secret = None
        try:
            if portable:
                try:
                    secret = require_identity(request["identity"].encode("ascii"))
                except (BackupCryptoError, UnicodeError):
                    raise stream.BackupStreamError("request_invalid") from None
            else:
                secret = self._identity()
            try:
                return self._runtime.decrypt(body, secret), None
            except BackupCryptoError:
                raise stream.BackupStreamError("decrypt_failed") from None
        finally:
            del secret
            request["identity"] = None

    def serve_connection(self, owner, *, deadline) -> str:
        """Read one request and its whole body, answer it; returns the outcome code."""

        request_id, request = stream.read_message(owner, stream.REQUEST, deadline=deadline)
        body = b""
        try:
            request = stream.check_request(request)
            body = stream.read_body(owner, size=request["size"], sha256=request["sha256"], deadline=deadline)
            result, recipient = self.run(request, body)
        except stream.BackupStreamError as error:
            stream.write_message(owner, stream.RESULT, {"schema": stream.RESULT_SCHEMA, "ok": False,
                                                        "code": error.code},
                                 deadline=deadline, correlation_id=request_id)
            return error.code
        finally:
            del body
        stream.write_message(owner, stream.RESULT, {
            "schema": stream.RESULT_SCHEMA, "ok": True, "op": request["op"], "size": len(result),
            "sha256": hashlib.sha256(result).hexdigest(), "recipient": recipient},
            deadline=deadline, correlation_id=request_id)
        stream.write_body(owner, result, deadline=deadline, correlation_id=request_id)
        return "served"
