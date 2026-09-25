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

Only `instance_backup_key` backups are made here. Both key modes are restored:
`portable_recovery` needs the owner's separately kept identity, which arrives once as
the first line of the portable bundle upload (`restore_upload_portable`), is wrapped in
a `OneShotIdentity`, handed to the worker for exactly one decrypt and wiped. It is
never written to disk, to the status, to an error or to a log.

Owner-initiated cleanup (the retention screen, app/services/retention_cleanup.py) may
remove an older backup's ciphertext or a staged restore, only through its own preview
and bound consent. A removed backup leaves a tombstone beside its receipt and consent
(`{backup_id}.deleted.json`); a discarded restore keeps its status (state `discarded`)
and receipt. Nothing here is ever deleted automatically.
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
    OneShotIdentity,
    backup_preview,
    check_receipt,
    create_backup,
    restore_backup,
)
from ..workers.backup_crypto import BackupCryptoError, require_identity
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner

CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "too_large", "unavailable", "backup_worker_unavailable", "backup_key_unavailable",
                   "backup_failed", "restore_failed"})
SERVER_RELEASE = "deeptwin-control-v1"
KEY_MODE = "instance_backup_key"
PORTABLE = "portable_recovery"
MAX_BUNDLE_BYTES = 64 << 20
MAX_IDENTITY_LINE = 256  # a native age identity is 74 ASCII bytes; the line ends with LF
TOMBSTONE_SCHEMA = "backup-tombstone-v1"
STALE_AWAITING_SECONDS = 3600
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


def _write_replace(path: Path, body: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    if temporary.exists():
        temporary.unlink()
    _write_new(temporary, body)
    os.replace(temporary, path)


def _tree_bytes(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if item.is_file() and not item.is_symlink():
            total += item.stat().st_size
    return total


def _wipe(identity) -> None:
    secret = getattr(identity, "_secret", None)
    if isinstance(secret, bytearray):
        for index in range(len(secret)):
            secret[index] = 0
        identity._secret = None


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
            tombstone = self._tombstone(receipt["backup_id"])
            stored = tombstone is None and (directory / f"{receipt['backup_id']}.age").is_file()
            found.append({"backup_id": receipt["backup_id"], "completed_at": receipt.get("completed_at"),
                          "ciphertext_state": "stored" if stored else "deleted" if tombstone else "missing",
                          "deleted_at": None if tombstone is None else tombstone.get("deleted_at"),
                          "ciphertext_sha256": receipt["ciphertext_sha256"],
                          "ciphertext_size": receipt.get("ciphertext_size"),
                          "key_mode": receipt.get("key_mode"),
                          "recoverable_after_host_or_volume_loss":
                              receipt.get("recoverable_after_host_or_volume_loss"),
                          "restore_verification": receipt.get("restore_verification_ref"),
                          "consented_preview_sha": None if consented is None else consented.get("preview_sha")})
        return sorted(found, key=lambda item: str(item["completed_at"]), reverse=True)

    def _tombstone(self, backup_id: str):
        path = self._data_dir / BACKUPS_DIR / f"{_uuid(backup_id)}.deleted.json"
        if path.is_symlink() or not path.is_file():
            return None
        try:
            value = json.loads(path.read_bytes())
        except (OSError, ValueError):
            return {"schema_version": TOMBSTONE_SCHEMA}  # a damaged tombstone still means deleted
        return value if type(value) is dict else {"schema_version": TOMBSTONE_SCHEMA}

    def _restore_dir(self, restore_id: str) -> Path:
        path = self._data_dir / RESTORES_DIR / _uuid(restore_id)
        if path.is_symlink() or not path.is_dir():
            raise BackupServiceError("not_found")
        return path

    def _restore_view(self, restore_id: str) -> dict:
        path = self._restore_dir(restore_id)
        status = json.loads((path / "status.json").read_bytes())
        view = {"restore_id": restore_id, **status}
        receipt_path = path / "receipt.json"
        if "key_mode" not in view and receipt_path.is_file():
            try:
                view["key_mode"] = json.loads(receipt_path.read_bytes()).get("key_mode")
            except (OSError, ValueError):
                pass
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
        if member == "ciphertext" and self._tombstone(backup_id) is not None:
            raise BackupServiceError("not_found")  # removed by the owner: its tombstone stands
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
        if (receipt.get("key_mode") not in (KEY_MODE, PORTABLE) or type(receipt.get("ciphertext_size")) is not int
                or not 1 <= receipt["ciphertext_size"] <= MAX_BUNDLE_BYTES):
            raise BackupServiceError("invalid_input")
        if self._client is None:
            raise BackupServiceError("backup_worker_unavailable")
        restore_id = str(uuid4())
        path = self._directory(RESTORES_DIR) / restore_id
        path.mkdir(mode=0o700)
        _write_new(path / "receipt.json", _canonical(receipt))
        status = {"state": "awaiting_bundle", "backup_id": receipt["backup_id"], "created_at": _stamp(),
                  "request_id": request_id, "failure": None, "key_mode": receipt["key_mode"]}
        (path / "status.json").write_bytes(_canonical(status))
        return self._restore_view(restore_id)

    @_closed
    def restore_upload(self, request, restore_id: str, bundle: bytes) -> dict:
        """The encrypted bundle of an `instance_backup_key` restore."""

        _authenticate_owner(self._owner, request)
        return self._stage(restore_id, bundle, None)

    @_closed
    def restore_upload_portable(self, request, restore_id: str, body: bytes) -> dict:
        """A `portable_recovery` restore: the owner's identity line, LF, then the bundle.

        The identity is used for exactly one decrypt and wiped; it is never stored,
        echoed or logged. A malformed identity refuses before the worker is asked.
        """

        _authenticate_owner(self._owner, request)
        if type(body) is not bytes or not 2 <= len(body) <= MAX_BUNDLE_BYTES + MAX_IDENTITY_LINE:
            raise BackupServiceError("too_large" if body else "invalid_input")
        end = body.find(b"\n", 0, MAX_IDENTITY_LINE)
        if end < 1:
            raise BackupServiceError("invalid_input")
        secret = bytearray(body[:end].strip())
        try:
            try:
                require_identity(bytes(secret))  # a native X25519 identity, or nothing reaches the worker
            except BackupCryptoError:
                raise BackupServiceError("invalid_input") from None
            identity = OneShotIdentity(secret)
        finally:
            for index in range(len(secret)):
                secret[index] = 0
        try:
            return self._stage(restore_id, body[end + 1:], identity)
        finally:
            _wipe(identity)  # used once or refused: either way nothing of it stays

    UPLOAD_INTERRUPTED = "the bundle upload was interrupted before it was complete; nothing was staged"

    @_closed
    def restore_interrupted(self, request, restore_id: str, received_bytes: int) -> dict:
        """T074: the owner's bundle upload for this restore ended before its body was
        complete (the client disconnected mid-stream). Nothing of it was kept — the web
        boundary holds the partial body only in memory and drops it — so the restore is
        marked `failed` at once (cleanable on the retention screen) instead of waiting an
        hour as an abandoned `awaiting_bundle`. The active vault is never touched; a
        fresh restore starts over."""

        _authenticate_owner(self._owner, request)
        if type(received_bytes) is not int or received_bytes < 0:
            raise BackupServiceError("invalid_input")
        if not self._lock.acquire(timeout=5):
            raise BackupServiceError("conflict")
        try:
            path = self._restore_dir(restore_id)
            status = json.loads((path / "status.json").read_bytes())
            if status.get("state") != "awaiting_bundle":
                raise BackupServiceError("conflict")  # only a restore still waiting can be interrupted
            if any(child.name not in {"status.json", "receipt.json"} for child in path.iterdir()):
                raise BackupServiceError("unavailable")  # never claim nothing was staged if something was
            status = {**status, "state": "failed", "failure": self.UPLOAD_INTERRUPTED,
                      "failure_code": "restore_failed", "interrupted_after_bytes": received_bytes}
            _write_replace(path / "status.json", _canonical(status))
        finally:
            self._lock.release()
        return self._restore_view(restore_id)

    def _stage(self, restore_id: str, bundle: bytes, identity) -> dict:
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
            if (receipt.get("key_mode") == PORTABLE) != (identity is not None):
                # a portable restore needs the kept identity; an instance restore takes none
                raise BackupServiceError("invalid_input")
            _write_new(path / "bundle.age", bundle)
            staged = path / "staged"
            staged.mkdir(mode=0o700)
            outcome = restore_backup(path / "bundle.age", receipt, staged, crypto=self._client,
                                     recovery_identity=identity, active_vault_dir=self._data_dir)
            identity = None
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

    # --- owner-initiated cleanup (the retention screen) ---------------------------------

    def cleanup_candidates(self) -> list[dict]:
        """Every stored backup file and staged restore, each with whether the owner may remove it.

        Only the owner removes anything, through the retention preview and consent. The
        newest stored backup is always kept; a restore still awaiting its bundle is
        eligible only after an hour (another tab may be mid-upload).
        """

        items = []
        stored = [item for item in self._receipts() if item["ciphertext_state"] == "stored"]
        newest = stored[0]["backup_id"] if stored else None
        for item in stored:
            size = (self._data_dir / BACKUPS_DIR / f"{item['backup_id']}.age").stat().st_size
            keep = item["backup_id"] == newest
            items.append({"item_id": f"backup:{item['backup_id']}", "category": "backups",
                          "created_at": item["completed_at"], "bytes": size,
                          "state": "stored", "eligible": not keep,
                          "reason": "newest_backup_kept" if keep else "older_backup",
                          "removes": "encrypted_backup_file",
                          "keeps": ["external_receipt", "consent_record", "tombstone"],
                          "sha256": item["ciphertext_sha256"]})
        now = datetime.now(UTC)
        for view in self._restores():
            state = view.get("state")
            if state == "discarded":
                continue
            path = self._restore_dir(view["restore_id"])
            size = sum(_tree_bytes(child) if child.is_dir() else child.stat().st_size
                       for child in path.iterdir() if child.name not in {"status.json", "receipt.json"})
            eligible = True
            reason = {"failed": "failed_restore", "restored_review": "staged_copy_not_activated"}.get(
                state, "stale_awaiting_bundle")
            if state == "awaiting_bundle":
                try:
                    created = datetime.strptime(view["created_at"], "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
                except (KeyError, TypeError, ValueError):
                    created = now
                if (now - created).total_seconds() < STALE_AWAITING_SECONDS:
                    eligible, reason = False, "awaiting_bundle_recently_begun"
            items.append({"item_id": f"restore:{view['restore_id']}", "category": "staged_restores",
                          "created_at": view.get("created_at"), "bytes": size, "state": state,
                          "eligible": eligible, "reason": reason,
                          "removes": "staged_restore_copy",
                          "keeps": ["restore_status", "external_receipt"],
                          "sha256": None})
        return items

    def discard(self, *, stamp: str, request_id: str, reason_code: str, preview_sha256: str,
                verify, commit) -> dict:
        """Remove exactly the previewed, consented items under the backup lock.

        `verify(current_candidates)` recomputes the preview inside the lock, returns its
        items, and raises when it no longer matches. Tombstones are written durably, then
        `commit()` records the core event, and only then do the bytes go.
        """

        if not self._lock.acquire(blocking=False):
            raise BackupServiceError("conflict")
        try:
            items = verify(self.cleanup_candidates())
            marks = []
            for item in items:
                kind, _, ident = item["item_id"].partition(":")
                if kind == "backup":
                    directory = self._data_dir / BACKUPS_DIR
                    _write_new(directory / f"{_uuid(ident)}.deleted.json", _canonical({
                        "schema_version": TOMBSTONE_SCHEMA, "backup_id": ident,
                        "ciphertext_sha256": item["sha256"], "ciphertext_size": item["bytes"],
                        "former_kind": "encrypted_backup_file", "deleted_at": stamp,
                        "deletion_request_id": request_id, "reason_code": reason_code,
                        "preview_sha256": preview_sha256}))
                    marks.append((item, directory / f"{ident}.age"))
                else:
                    path = self._restore_dir(ident)
                    status = json.loads((path / "status.json").read_bytes())
                    _write_replace(path / "status.json", _canonical({
                        **status, "state": "discarded", "previous_state": status.get("state"),
                        "discarded_at": stamp, "deletion_request_id": request_id,
                        "reason_code": reason_code, "preview_sha256": preview_sha256}))
                    marks.append((item, path))
            commit()
            removed = {}
            for item, target in marks:
                try:
                    if item["category"] == "backups":
                        if target.exists():
                            target.unlink()
                        removed[item["item_id"]] = not target.exists()
                    else:
                        for child in list(target.iterdir()):
                            if child.name in {"status.json", "receipt.json"}:
                                continue
                            if child.is_dir() and not child.is_symlink():
                                shutil.rmtree(child)
                            else:
                                child.unlink()
                        removed[item["item_id"]] = sorted(
                            child.name for child in target.iterdir()) == ["receipt.json", "status.json"]
                except OSError:
                    removed[item["item_id"]] = False  # reported as pending, never as done
            return removed
        finally:
            self._lock.release()
