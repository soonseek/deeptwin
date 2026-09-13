"""Gateway-side credential vault core (`credential-vault-port-v1`, T090).

This module belongs to the isolated credential-vault service. The control plane
must never import it: application state carries only opaque handles, and the raw
secret is readable solely through :meth:`CredentialVault.resolve_for_gateway`
inside the gateway boundary.

Lifecycle: a store/rotate intent stages the secret into an owned 0600 file,
commits it atomically, and is deduplicated by intent id. Rotation supersedes the
predecessor (``cleanup_pending``) and immediately invalidates its resolution.
Retirement gates resolution the same way. ``erase`` reports
``erasure_completed`` only after the locally managed copy is verifiably gone.
Startup reconciliation removes orphaned staging files and marks committed
records whose secret bytes are missing as ``secret_input_lost``; the vault never
invents a secret it cannot verify. Errors are sanitized and never carry secret
bytes.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

MAX_SECRET_BYTES = 65_536
_PROVIDER = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_HANDLE = re.compile(r"[0-9a-f]{32}\Z")
_OPERATIONS = (
    "capabilities", "store", "resolve_for_gateway", "retire", "erase", "health",
)
_STATES = frozenset({
    "active", "cleanup_pending", "secret_input_lost", "erasure_completed",
})


class CredentialVaultError(RuntimeError):
    """Sanitized vault failure; the message never contains secret bytes."""


@dataclass(frozen=True, slots=True)
class CredentialRecord:
    """Opaque public view of one vault entry; it never carries the secret."""

    handle: str
    provider: str
    state: str


class CredentialVault:
    """File-backed vault: 0600 secret files, atomic index, staged commits."""

    __slots__ = ("_index", "root")

    def __init__(self, root: str) -> None:
        os.makedirs(root, mode=0o700, exist_ok=True)
        os.makedirs(os.path.join(root, "secrets"), mode=0o700, exist_ok=True)
        self.root = root
        self._index = self._load_index()
        self._reconcile_startup()

    # ----------------------------------------------------------- persistence

    def _index_path(self) -> str:
        return os.path.join(self.root, "index.json")

    def _secret_path(self, handle: str) -> str:
        return os.path.join(self.root, "secrets", handle)

    def _load_index(self) -> dict:
        try:
            with open(self._index_path(), "rb") as stream:
                value = json.loads(stream.read().decode("utf-8"))
        except FileNotFoundError:
            return {"records": {}, "intents": {}}
        except (OSError, ValueError) as exc:
            raise CredentialVaultError("vault index is unreadable") from exc
        if (
            type(value) is not dict
            or set(value) != {"records", "intents"}
            or type(value["records"]) is not dict
            or type(value["intents"]) is not dict
        ):
            raise CredentialVaultError("vault index is malformed")
        return value

    def _write_index(self) -> None:
        staging = os.path.join(self.root, f"staging-index-{uuid4().hex}")
        payload = json.dumps(
            self._index, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        descriptor = os.open(
            staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(staging, self._index_path())

    def _reconcile_startup(self) -> None:
        for name in os.listdir(self.root):
            if name.startswith("staging-"):
                try:
                    os.unlink(os.path.join(self.root, name))
                except OSError:
                    pass
        changed = False
        for handle, record in self._index["records"].items():
            if record["state"] != "active":
                continue
            try:
                info = os.stat(self._secret_path(handle), follow_symlinks=False)
                healthy = stat.S_ISREG(info.st_mode)
            except OSError:
                healthy = False
            if not healthy:
                record["state"] = "secret_input_lost"
                changed = True
        if changed:
            self._write_index()

    # ------------------------------------------------------------ validation

    def _record(self, handle: str) -> dict:
        record = self._index["records"].get(handle)
        if record is None:
            raise CredentialVaultError("unknown credential handle")
        return record

    @staticmethod
    def _validate_secret(secret: object) -> bytes:
        if type(secret) is not bytes or not 1 <= len(secret) <= MAX_SECRET_BYTES:
            raise CredentialVaultError("secret bytes are out of bounds")
        try:
            secret.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise CredentialVaultError("secret bytes are not UTF-8") from exc
        return secret

    # ------------------------------------------------------------ operations

    def capabilities(self) -> dict:
        return {"port": "credential-vault-port-v1", "operations": list(_OPERATIONS)}

    def health(self) -> dict:
        counts = {"active": 0, "cleanup_pending": 0, "secret_input_lost": 0}
        for record in self._index["records"].values():
            if record["state"] in counts:
                counts[record["state"]] += 1
        return counts

    def store(
        self,
        intent_id: str,
        provider: str,
        secret: bytes,
        *,
        rotate_from: str | None = None,
    ) -> CredentialRecord:
        if type(intent_id) is not str or _UUID.fullmatch(intent_id) is None:
            raise CredentialVaultError("store intent id is not a canonical UUID")
        if type(provider) is not str or _PROVIDER.fullmatch(provider) is None:
            raise CredentialVaultError("provider identifier is invalid")
        secret = self._validate_secret(secret)
        digest = sha256(secret).hexdigest()

        existing_handle = self._index["intents"].get(intent_id)
        if existing_handle is not None:
            existing = self._record(existing_handle)
            if (
                existing["provider"] != provider
                or existing["secret_sha256"] != digest
                or existing.get("predecessor") != rotate_from
            ):
                raise CredentialVaultError(
                    "store intent replay does not match its committed content"
                )
            return CredentialRecord(existing_handle, provider, existing["state"])

        predecessor = None
        if rotate_from is not None:
            predecessor = self._record(rotate_from)
            if predecessor["state"] != "active":
                raise CredentialVaultError("rotation predecessor is not active")

        handle = uuid4().hex
        staging = os.path.join(self.root, f"staging-{handle}")
        descriptor = os.open(
            staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        try:
            os.write(descriptor, secret)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(staging, self._secret_path(handle))

        self._index["records"][handle] = {
            "provider": provider,
            "state": "active",
            "intent_id": intent_id,
            "secret_sha256": digest,
            "predecessor": rotate_from,
        }
        self._index["intents"][intent_id] = handle
        if predecessor is not None:
            predecessor["state"] = "cleanup_pending"
        self._write_index()
        return CredentialRecord(handle, provider, "active")

    def resolve_for_gateway(self, handle: str) -> bytes:
        if type(handle) is not str or _HANDLE.fullmatch(handle) is None:
            raise CredentialVaultError("unknown credential handle")
        record = self._record(handle)
        if record["state"] != "active":
            raise CredentialVaultError("credential handle is not resolvable")
        try:
            with open(self._secret_path(handle), "rb") as stream:
                secret = stream.read(MAX_SECRET_BYTES + 1)
        except OSError as exc:
            raise CredentialVaultError("credential bytes are unavailable") from exc
        if (
            len(secret) > MAX_SECRET_BYTES
            or sha256(secret).hexdigest() != record["secret_sha256"]
        ):
            raise CredentialVaultError("credential bytes failed verification")
        return secret

    def retire(self, handle: str) -> CredentialRecord:
        if type(handle) is not str or _HANDLE.fullmatch(handle) is None:
            raise CredentialVaultError("unknown credential handle")
        record = self._record(handle)
        if record["state"] != "active":
            raise CredentialVaultError("only an active credential can be retired")
        record["state"] = "cleanup_pending"
        self._write_index()
        return CredentialRecord(handle, record["provider"], "cleanup_pending")

    def erase(self, handle: str) -> str:
        if type(handle) is not str or _HANDLE.fullmatch(handle) is None:
            raise CredentialVaultError("unknown credential handle")
        record = self._record(handle)
        if record["state"] not in ("cleanup_pending", "secret_input_lost"):
            raise CredentialVaultError(
                "erase requires a retired, superseded or lost credential"
            )
        path = self._secret_path(handle)
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise CredentialVaultError("credential bytes could not be removed") from exc
        # Verified removal: the copy must be demonstrably absent before the
        # state may claim completion.
        try:
            os.stat(path, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise CredentialVaultError("credential bytes are still present")
        record["state"] = "erasure_completed"
        record["secret_sha256"] = ""
        self._write_index()
        return "erasure_completed"


__all__ = [
    "MAX_SECRET_BYTES",
    "CredentialRecord",
    "CredentialVault",
    "CredentialVaultError",
]
