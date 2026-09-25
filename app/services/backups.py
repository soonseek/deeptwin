"""The owner's backup and staged restore (T070/T073; operations.md §5.2, UX-AC08).

The control plane's half of the backup split. It snapshots, previews, archives and
verifies (`app.operations.backup`); every age operation crosses the verified
`cp-backup` channel to the networkless backup-crypto worker through
`BackupCryptoClient`, which alone mounts the backup-key volume. This service never
receives a key handle or path, and nothing here can read the key.

- `state` says what is true: whether a worker is attached at all (`not_configured`),
  reachable with its key present (`ready`), reachable without a key
  (`key_unavailable`: the volume is lost or malformed, so no new backup and no restore
  of an instance-key backup is possible), or unreachable; plus the backups this
  instance made (their external receipts) and the staged restores.
- `preview` computes the ACTUAL included content of a backup made now — included
  categories with row counts, originals with count and bytes, every excluded category
  with its closed reason — over one consistent snapshot, and stores nothing. Its
  digest is what consent binds.
- `create` requires `confirmed: true` and that digest; the backup recomputes the
  preview from its own snapshot and refuses (`conflict`) when the vault changed. The
  consent (the preview shown and its digest) is kept beside the receipt.
- `restore_begin` takes the external receipt, `restore_upload` the encrypted bundle;
  the bundle is checked against the receipt, decrypted by the worker, verified and
  staged as `restored_review` in its own directory, never over the active vault. The
  staged vault stays blocked: a new owner must bootstrap on it, re-create connections
  and service clients, and explicitly reactivate an exact environment. This screen does
  not switch the active vault.

Only `instance_backup_key` backups are made and restored here; `portable_recovery`
needs the owner's separately kept identity as one-shot masked input, which this
browser path does not collect yet.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from uuid import uuid4

from ..operations.backup import (
    STALE_PREVIEW,
    WORKER_FAILURES,
    BackupError,
    backup_preview,
    check_receipt,
    create_backup,
    restore_backup,
)
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner

CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "too_large", "unavailable", "backup_worker_unavailable", "backup_key_unavailable",
                   "backup_failed", "restore_failed"})
SERVER_RELEASE = "deeptwin-control-v1"
KEY_MODE = "instance_backup_key"
MAX_BUNDLE_BYTES = 64 << 20
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
BACKUPS_DIR = "backups"
RESTORES_DIR = "restores"

__all__ = ["MAX_BUNDLE_BYTES", "BackupService", "BackupServiceError"]


class BackupServiceError(ValueError):
    def __init__(self, code="invalid_input", detail=None):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code
        self.detail = detail


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (BackupServiceError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage and worker detail stays private
            raise BackupServiceError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _uuid(value) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise BackupServiceError("invalid_input")
    return value


def _write_new(path: Path, body: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(body)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _failure_code(failure: str) -> str:
    if failure == STALE_PREVIEW:
        return "conflict"
    if failure == WORKER_FAILURES["key_unavailable"]:
        return "backup_key_unavailable"
    if failure in (WORKER_FAILURES["worker_unavailable"], WORKER_FAILURES["stream_invalid"]):
        return "backup_worker_unavailable"
    return "backup_failed"


class BackupService:
    def __init__(self, domain_store, owner_authority, *, client=None):
        self._domain = domain_store
        self._owner = owner_authority
        self._client = client
        self._data_dir = Path(domain_store.data_dir)
        self._lock = threading.Lock()

    # --- storage --------------------------------------------------------------------

    def _directory(self, name: str) -> Path:
        path = self._data_dir / name
        if path.is_symlink():
            raise BackupServiceError("unavailable")
        if not path.exists():
            path.mkdir(mode=0o700)
        return path

    def _receipts(self) -> list[dict]:
        found = []
        directory = self._data_dir / BACKUPS_DIR
        if not directory.is_dir():
            return found
        for path in sorted(directory.glob("*.receipt.json")):
            try:
                receipt = json.loads(path.read_bytes())
                check_receipt(receipt)
            except (OSError, ValueError, BackupError):
                continue
            consent = directory / f"{receipt['backup_id']}.consent.json"
            try:
                consented = json.loads(consent.read_bytes())
            except (OSError, ValueError):
                consented = None
            found.append({"backup_id": receipt["backup_id"], "completed_at": receipt.get("completed_at"),
                          "ciphertext_sha256": receipt["ciphertext_sha256"],
                          "ciphertext_size": receipt.get("ciphertext_size"),
                          "key_mode": receipt.get("key_mode"),
                          "recoverable_after_host_or_volume_loss":
                              receipt.get("recoverable_after_host_or_volume_loss"),
                          "restore_verification": receipt.get("restore_verification_ref"),
                          "consented_preview_sha": None if consented is None else consented.get("preview_sha")})
        return sorted(found, key=lambda item: str(item["completed_at"]), reverse=True)

    def _restore_dir(self, restore_id: str) -> Path:
        path = self._data_dir / RESTORES_DIR / _uuid(restore_id)
        if path.is_symlink() or not path.is_dir():
            raise BackupServiceError("not_found")
        return path

    def _restore_view(self, restore_id: str) -> dict:
        path = self._restore_dir(restore_id)
        status = json.loads((path / "status.json").read_bytes())
        view = {"restore_id": restore_id, **status}
        marker = path / "staged" / "restored_review.json"
        if status.get("state") == "restored_review" and marker.is_file():
            value = json.loads(marker.read_bytes())
            view["review"] = {
                "dispatch": value["dispatch"], "requires": value["requires"],
                "not_restored": value["not_restored"], "in_flight_requests": value["in_flight_requests"],
                "vault_id": value["vault_id"], "backup_id": value["backup_id"],
                "environment_reactivation": "explicit_required",
                "active_vault_changed": False,
            }
        return view

    def _restores(self) -> list[dict]:
        directory = self._data_dir / RESTORES_DIR
        if not directory.is_dir():
            return []
        views = []
        for path in sorted(directory.iterdir()):
            if _UUID.fullmatch(path.name) and (path / "status.json").is_file():
                try:
                    views.append(self._restore_view(path.name))
                except (OSError, ValueError, KeyError, BackupServiceError):
                    continue
        return sorted(views, key=lambda item: str(item.get("created_at")), reverse=True)

    def _worker_state(self) -> dict:
        from ..workers.backup_crypto_client import BackupWorkerError

        if self._client is None:
            return {"worker": "not_configured"}
        try:
            described = self._client.describe()
        except BackupWorkerError as error:
            return {"worker": "key_unavailable" if error.code == "key_unavailable" else "unreachable"}
        return {"worker": "ready", "recipient": described["recipient"]}

    # --- reads ------------------------------------------------------------------------

    @_closed
    def state(self, request) -> dict:
        self._owner.authenticate_bound(request.session)
        return {"schema_version": "backup-state-v1", **self._worker_state(), "key_mode": KEY_MODE,
                "recoverable_after_host_or_volume_loss": False, "max_bundle_bytes": MAX_BUNDLE_BYTES,
                "backups": self._receipts(), "restores": self._restores()}

    @_closed
    def preview(self, request, request_id: str) -> dict:
        _authenticate_owner(self._owner, request)
        try:
            value = backup_preview(self._data_dir, key_mode=KEY_MODE)
        except BackupError:
            raise BackupServiceError("backup_failed") from None
        return {"request_id": _uuid(request_id), **value}

    @_closed
    def bundle(self, request, backup_id: str, member: str) -> bytes:
        self._owner.authenticate_bound(request.session)
        _uuid(backup_id)
        suffix = {"ciphertext": ".age", "receipt": ".receipt.json"}[member]
        path = self._data_dir / BACKUPS_DIR / f"{backup_id}{suffix}"
        if path.is_symlink() or not path.is_file():
            raise BackupServiceError("not_found")
        return path.read_bytes()

    @_closed
    def restore_state(self, request, restore_id: str) -> dict:
        self._owner.authenticate_bound(request.session)
        return self._restore_view(restore_id)

    # --- commands -----------------------------------------------------------------------

    @_closed
    def create(self, request, request_id: str, preview_sha: str, confirmed) -> dict:
        _authenticate_owner(self._owner, request)
        _uuid(request_id)
        if confirmed is not True:
            raise BackupServiceError("invalid_input")  # consent is never implicit
        if type(preview_sha) is not str or _SHA256.fullmatch(preview_sha) is None:
            raise BackupServiceError("invalid_input")
        if self._client is None:
            raise BackupServiceError("backup_worker_unavailable")
        if not self._lock.acquire(blocking=False):
            raise BackupServiceError("conflict")
        try:
            output = self._directory(BACKUPS_DIR)
            outcome = create_backup(self._data_dir, output, crypto=self._client, key_mode=KEY_MODE,
                                    server_release=SERVER_RELEASE, expected_preview_sha=preview_sha)
            if outcome.state != "ready":
                raise BackupServiceError(_failure_code(outcome.failure), detail=outcome.failure)
            receipt = outcome.receipt
            _write_new(output / f"{receipt['backup_id']}.consent.json", _canonical({
                "schema_version": "backup-consent-v1", "request_id": request_id, "confirmed": True,
                "preview_sha": preview_sha, "preview": outcome.preview, "consented_at": _stamp()}))
        finally:
            self._lock.release()
        return {"backup_id": receipt["backup_id"], "receipt": receipt, "states": list(outcome.states),
                "preview_sha": preview_sha}

    @_closed
    def restore_begin(self, request, request_id: str, receipt) -> dict:
        _authenticate_owner(self._owner, request)
        _uuid(request_id)
        try:
            check_receipt(receipt)
        except BackupError:
            raise BackupServiceError("invalid_input") from None
        if (receipt.get("key_mode") != KEY_MODE or type(receipt.get("ciphertext_size")) is not int
                or not 1 <= receipt["ciphertext_size"] <= MAX_BUNDLE_BYTES):
            # portable recovery needs the separately kept identity: not collected here
            raise BackupServiceError("invalid_input")
        if self._client is None:
            raise BackupServiceError("backup_worker_unavailable")
        restore_id = str(uuid4())
        path = self._directory(RESTORES_DIR) / restore_id
        path.mkdir(mode=0o700)
        _write_new(path / "receipt.json", _canonical(receipt))
        status = {"state": "awaiting_bundle", "backup_id": receipt["backup_id"], "created_at": _stamp(),
                  "request_id": request_id, "failure": None}
        (path / "status.json").write_bytes(_canonical(status))
        return self._restore_view(restore_id)

    @_closed
    def restore_upload(self, request, restore_id: str, bundle: bytes) -> dict:
        _authenticate_owner(self._owner, request)
        if self._client is None:
            raise BackupServiceError("backup_worker_unavailable")
        if type(bundle) is not bytes or not 1 <= len(bundle) <= MAX_BUNDLE_BYTES:
            raise BackupServiceError("too_large" if bundle else "invalid_input")
        if not self._lock.acquire(blocking=False):
            raise BackupServiceError("conflict")
        try:
            path = self._restore_dir(restore_id)
            status = json.loads((path / "status.json").read_bytes())
            if status.get("state") != "awaiting_bundle":
                raise BackupServiceError("conflict")
            receipt = json.loads((path / "receipt.json").read_bytes())
            _write_new(path / "bundle.age", bundle)
            staged = path / "staged"
            staged.mkdir(mode=0o700)
            outcome = restore_backup(path / "bundle.age", receipt, staged, crypto=self._client,
                                     active_vault_dir=self._data_dir)
            (path / "bundle.age").unlink()
            if outcome.state == "restored_review":
                status = {**status, "state": "restored_review", "restored_at": _stamp(),
                          "checked": list(outcome.checked), "records": outcome.manifest["snapshot_sequence"],
                          "originals": len(outcome.manifest["item_refs"]) - 1}
            else:
                shutil.rmtree(staged, ignore_errors=True)
                code = ("backup_key_unavailable" if outcome.failure == WORKER_FAILURES["key_unavailable"]
                        else "backup_worker_unavailable"
                        if outcome.failure in (WORKER_FAILURES["worker_unavailable"],
                                               WORKER_FAILURES["stream_invalid"]) else "restore_failed")
                status = {**status, "state": "failed", "failure": outcome.failure, "failure_code": code}
            (path / "status.json").write_bytes(_canonical(status))
        finally:
            self._lock.release()
        return self._restore_view(restore_id)
