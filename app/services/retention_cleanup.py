"""What this instance keeps, for how long, and the owner's explicit cleanup (US7, T073;
operations.md OPS-D04/D05, RetentionPolicy, OPS-AC06; app/operations/retention.py).

`state` reads what the server actually holds, per category, and says for each what is
kept, for how long, whether anything in it is eligible for owner-initiated cleanup, and
what is never deleted and why:

- core records (records, lineage, the public event log) are kept with no expiry
  (`core_mode = manual_only`, the only mode) and are never deleted automatically; the
  record store is append-only, so this screen offers no deletion of them.
- deletion tombstones are the durable record of a deletion and are never deleted.
- stored originals are kept until the owner deletes one on the work screen
  (source deletion, its own preview and consent); never automatically.
- encrypted backups this instance made are never deleted automatically; the owner may
  remove an OLDER backup's ciphertext here. The newest stored backup is always kept.
- staged restores (decrypted copies waiting for review, failed or abandoned restores)
  are never deleted automatically; the owner may discard them here.
- regenerable caches and raw audio: this server stores none (raw audio is
  `ephemeral_only`), so there is nothing to keep or clean.

Cleanup mirrors source deletion: `preview` computes, from the server's own state, the
exact items, bytes, what goes, what stays and what the cleanup cannot reach, and
digests it together with the request id and reason; `cleanup` needs `confirmed: true`
and that exact digest, recomputes the preview under the backup lock (anything changed
is a conflict), writes each item's tombstone durably, commits the core
`retention.deleted` event, and only then removes the bytes. The cleanup receipt (the
preview shown, the consent, what was removed) is kept under `retention/`. The same
request replays its receipt; nothing is ever undone or removed without consent.
"""

from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from functools import wraps
from hashlib import sha256
from pathlib import Path

from ..domain.refs import canonical_json
from ..domain.store import ERASURE_KIND, _writer
from .backups import BackupServiceError
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _owner_actor_ref

CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "unavailable"})
STATE_SCHEMA = "retention-state-v1"
PREVIEW_SCHEMA = "retention-cleanup-preview-v1"
CONFIRM_SCHEMA = "retention-cleanup-v1"
RECEIPT_SCHEMA = "retention-cleanup-receipt-v1"
REASONS = frozenset({"user_requested", "policy_cleanup"})
# the closed vocabularies the state speaks (mirrored by app/static/records.mjs)
CATEGORIES = ("core_records", "deletion_tombstones", "originals", "backups", "staged_restores",
              "regenerable_caches", "raw_audio")
KEPT = frozenset({"forever", "until_owner_deletes", "until_owner_cleanup", "not_stored"})
OWNER_CLEANUP = frozenset({"not_offered", "work_screen", "this_screen", "nothing_stored"})
MAX_ITEMS = 64
RECEIPTS_DIR = "retention"
NOT_REACHED = ("copies_already_downloaded", "copies_outside_this_instance")
POLICY = {"core_mode": "manual_only", "automatic_deletion": "none",
          "cache_stored": False, "raw_audio_mode": "ephemeral_only"}
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_ITEM = re.compile(r"(backup|restore):([0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")

__all__ = ["CONFIRM_SCHEMA", "PREVIEW_SCHEMA", "RetentionCleanup", "RetentionServiceError"]


class RetentionServiceError(ValueError):
    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (RetentionServiceError, OwnerAuthError):
            raise
        except BackupServiceError as error:
            raise RetentionServiceError(error.code if error.code in CODES else "unavailable") from None
        except Exception:  # noqa: BLE001 - storage detail stays private
            raise RetentionServiceError("unavailable") from None

    return invoke


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _uuid(value) -> str:
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise RetentionServiceError("invalid_input")
    return value


class RetentionCleanup:
    def __init__(self, domain_store, owner_authority, *, backups, works):
        self._domain = domain_store
        self._owner = owner_authority
        self._backups = backups
        self._works = works
        self._data_dir = Path(domain_store.data_dir)

    # --- what the server holds ----------------------------------------------------------

    def _counts(self) -> dict:
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            vault = roots.genesis.id
            records = db.execute("SELECT count(*) FROM domain_records WHERE vault_id=?", (vault,)).fetchone()[0]
            tombstones = db.execute("SELECT count(*) FROM domain_records WHERE vault_id=? AND kind=?",
                                    (vault, ERASURE_KIND)).fetchone()[0]
            events = db.execute("SELECT count(*) FROM api_event_envelopes WHERE vault_id=?",
                                (vault,)).fetchone()[0]
            blobs = db.execute("SELECT count(*), coalesce(sum(size), 0) FROM domain_blobs WHERE vault_id=?",
                               (vault,)).fetchone()
            policy_ref = roots.retention_policy.as_dict()
        return {"records": records - tombstones, "tombstones": tombstones, "events": events,
                "originals_registered": blobs[0], "originals_bytes_registered": blobs[1],
                "policy_ref": policy_ref}

    def _originals(self, counts) -> dict:
        from ..operations.backup import _live_blobs

        with self._domain._connection() as db:
            vault = self._domain._read_roots(db).genesis.id
            live = _live_blobs(db, vault)
        return {"count": len(live), "bytes": sum(size for _p, _d, size in live),
                "deleted_count": counts["originals_registered"] - len(live)}

    def _receipt_list(self) -> list[dict]:
        directory = self._data_dir / RECEIPTS_DIR
        if not directory.is_dir():
            return []
        found = []
        for path in sorted(directory.glob("*.json")):
            try:
                value = json.loads(path.read_bytes())
            except (OSError, ValueError):
                continue
            if type(value) is dict and value.get("schema_version") == RECEIPT_SCHEMA:
                found.append({"request_id": value["request_id"], "cleaned_at": value["cleaned_at"],
                              "item_count": len(value["removed"]), "byte_count": value["byte_count"],
                              "preview_sha256": value["preview_sha256"], "reason_code": value["reason_code"]})
        return sorted(found, key=lambda item: item["cleaned_at"], reverse=True)

    @_closed
    def state(self, request) -> dict:
        self._owner.authenticate_bound(request.session)
        counts = self._counts()
        originals = self._originals(counts)
        candidates = self._backups.cleanup_candidates()
        backups = [item for item in candidates if item["category"] == "backups"]
        restores = [item for item in candidates if item["category"] == "staged_restores"]
        receipts = self._backups._receipts()

        def eligible(items):
            chosen = [item for item in items if item["eligible"]]
            return len(chosen), sum(item["bytes"] for item in chosen)

        backup_eligible = eligible(backups)
        restore_eligible = eligible(restores)
        categories = [
            {"category": "core_records", "kept": "forever", "automatic_deletion": "never",
             "owner_cleanup": "not_offered", "reason": "append_only_history",
             "count": counts["records"], "events": counts["events"]},
            {"category": "deletion_tombstones", "kept": "forever", "automatic_deletion": "never",
             "owner_cleanup": "not_offered", "reason": "record_of_a_deletion",
             "count": counts["tombstones"] + sum(1 for item in receipts if item["ciphertext_state"] == "deleted")},
            {"category": "originals", "kept": "until_owner_deletes", "automatic_deletion": "never",
             "owner_cleanup": "work_screen", "reason": "source_deletion_with_its_own_preview",
             "count": originals["count"], "bytes": originals["bytes"],
             "deleted_count": originals["deleted_count"]},
            {"category": "backups", "kept": "until_owner_cleanup", "automatic_deletion": "never",
             "owner_cleanup": "this_screen", "reason": "newest_backup_kept",
             "count": len(backups), "bytes": sum(item["bytes"] for item in backups),
             "eligible_count": backup_eligible[0], "eligible_bytes": backup_eligible[1],
             "deleted_count": sum(1 for item in receipts if item["ciphertext_state"] == "deleted")},
            {"category": "staged_restores", "kept": "until_owner_cleanup", "automatic_deletion": "never",
             "owner_cleanup": "this_screen", "reason": "staged_copy_never_activated_here",
             "count": len(restores), "bytes": sum(item["bytes"] for item in restores),
             "eligible_count": restore_eligible[0], "eligible_bytes": restore_eligible[1]},
            {"category": "regenerable_caches", "kept": "not_stored", "automatic_deletion": "never",
             "owner_cleanup": "nothing_stored", "reason": "no_cache_is_stored", "count": 0},
            {"category": "raw_audio", "kept": "not_stored", "automatic_deletion": "never",
             "owner_cleanup": "nothing_stored", "reason": "ephemeral_only", "count": 0},
        ]
        return {"schema_version": STATE_SCHEMA, "policy": {**POLICY, "policy_ref": counts["policy_ref"]},
                "categories": categories, "items": [self._public(item) for item in candidates],
                "cleanups": self._receipt_list()}

    @staticmethod
    def _public(item) -> dict:
        return {key: item[key] for key in ("item_id", "category", "created_at", "bytes", "state", "eligible",
                                           "reason", "removes", "keeps")}

    # --- the exact scope -----------------------------------------------------------------

    @staticmethod
    def _command(payload, schema, keys):
        if type(payload) is not dict or set(payload) != keys or payload.get("schema_version") != schema:
            raise RetentionServiceError("invalid_input")
        ids = payload["item_ids"]
        if (type(ids) is not list or not 1 <= len(ids) <= MAX_ITEMS or len(set(ids)) != len(ids)
                or any(type(item) is not str or _ITEM.fullmatch(item) is None for item in ids)
                or payload["reason_code"] not in REASONS):
            raise RetentionServiceError("invalid_input")
        _uuid(payload["request_id"])
        return payload

    @staticmethod
    def _scope(candidates, item_ids):
        by_id = {item["item_id"]: item for item in candidates}
        items = []
        for item_id in item_ids:
            item = by_id.get(item_id)
            if item is None:
                raise RetentionServiceError("not_found")
            if not item["eligible"]:
                raise RetentionServiceError("conflict")  # kept by policy: never offered
            items.append(item)
        return items

    @staticmethod
    def _view(request_id, reason, items) -> dict:
        body = {
            "schema_version": PREVIEW_SCHEMA, "request_id": request_id, "reason_code": reason,
            "items": [{key: item[key] for key in ("item_id", "category", "created_at", "bytes", "state",
                                                  "removes", "keeps", "sha256")} for item in items],
            "item_count": len(items), "byte_count": sum(item["bytes"] for item in items),
            "not_reached": list(NOT_REACHED),
            "never_deleted": ["core_records", "deletion_tombstones", "originals", "newest_backup"],
            "records_kept": "core records stay and read back; each removed item leaves its tombstone",
        }
        return {**body, "preview_sha256": sha256(canonical_json(body)).hexdigest()}

    @_closed
    def preview(self, request, payload) -> dict:
        command = self._command(payload, PREVIEW_SCHEMA, {"schema_version", "request_id", "item_ids", "reason_code"})
        _authenticate_owner(self._owner, request)
        items = self._scope(self._backups.cleanup_candidates(), command["item_ids"])
        return self._view(command["request_id"], command["reason_code"], items)

    # --- the cleanup ---------------------------------------------------------------------

    def _receipt_path(self, request_id) -> Path:
        return self._data_dir / RECEIPTS_DIR / f"{_uuid(request_id)}.json"

    @_closed
    def cleanup(self, request, payload) -> dict:
        command = self._command(payload, CONFIRM_SCHEMA, {"schema_version", "request_id", "item_ids",
                                                          "reason_code", "preview_sha256", "confirmed"})
        if (command["confirmed"] is not True or type(command["preview_sha256"]) is not str
                or _SHA256.fullmatch(command["preview_sha256"]) is None):
            raise RetentionServiceError("invalid_input")  # consent is explicit, never implied
        _authenticate_owner(self._owner, request)
        receipt_path = self._receipt_path(command["request_id"])
        if receipt_path.is_file():
            done = json.loads(receipt_path.read_bytes())
            if (done.get("preview_sha256") != command["preview_sha256"]
                    or done.get("item_ids") != command["item_ids"]):
                raise RetentionServiceError("conflict")
            return done  # the same request replays its receipt; nothing runs twice
        stamp = _stamp()
        shown = {}

        def verify(candidates):
            items = self._scope(candidates, command["item_ids"])
            view = self._view(command["request_id"], command["reason_code"], items)
            if view["preview_sha256"] != command["preview_sha256"]:
                raise RetentionServiceError("conflict")  # changed since the owner saw it
            shown["items"], shown["view"] = items, view
            return items

        def commit():
            with _writer(), self._domain._connection(write=True) as db:
                actor = _authenticate_owner(self._owner, request, db)
                roots = self._domain._read_roots(db)
                actor_ref = _owner_actor_ref(db, actor)
                self._works._event(db, roots, actor_ref, "retention.deleted", (), command["request_id"],
                                   {"object_count": len(shown["items"]), "byte_count": shown["view"]["byte_count"]})

        removed = self._backups.discard(
            stamp=stamp, request_id=command["request_id"], reason_code=command["reason_code"],
            preview_sha256=command["preview_sha256"], verify=verify, commit=commit)
        receipt = {
            "schema_version": RECEIPT_SCHEMA, "request_id": command["request_id"], "cleaned_at": stamp,
            "reason_code": command["reason_code"], "confirmed": True, "item_ids": command["item_ids"],
            "preview_sha256": command["preview_sha256"], "preview": shown["view"],
            "byte_count": shown["view"]["byte_count"],
            "removed": [{"item_id": item["item_id"], "category": item["category"], "bytes": item["bytes"],
                         "bytes_removed": removed[item["item_id"]]} for item in shown["items"]],
            "not_reached": list(NOT_REACHED),
        }
        directory = self._data_dir / RECEIPTS_DIR
        if directory.is_symlink():
            raise RetentionServiceError("unavailable")
        directory.mkdir(mode=0o700, exist_ok=True)
        descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                             0o600)
        try:
            os.write(descriptor, canonical_json(receipt))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return receipt
