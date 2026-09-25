"""Control-plane credential command ledger and owner-act driver (T090).

Each explicit owner act (create, rotate, delete) carries a browser-chosen
``intent_id`` idempotency key. Before anything reaches the gateway the control
plane allocates the act's gateway command id(s) and the exact nonsecret target
(record id, version, predecessor reference) and commits them here in one SQLite
transaction. The raw secret is never persisted, hashed or compared: it lives
only in the request memory of the call that transmits it.

Recovery follows the custody contract. A command whose transmission may have
reached the gateway (any failure other than a pre-send connection failure or a
definitive non-admission answer) is never re-sent with a secret: a retry of the
same act queries that command id (``query_record``) and adopts the committed
receipt, reports the nonterminal ``pending``/``unknown`` as retryable, or the
terminal ``secret_input_lost`` (after which only a new act with a fresh intent
and explicit secret re-entry may try again). Retirement carries no secret and
is idempotent under its command id, so its recovery is a same-command replay.

Reads (``snapshot``) serve only what this ledger already committed; they make
no vault, gateway, provider or network call. This module imports no vault code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

PROVIDER_MODES = {"claude": "api", "codex": "api"}
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_NOT_ADMITTED = frozenset({"busy", "capacity_exhausted", "nonce_exhausted",
                           "invalid_secret", "invalid_encoding", "unsupported_operation"})


class CredentialCommandError(RuntimeError):
    """A sanitized, typed act outcome for the HTTP boundary (never secret-bearing)."""

    def __init__(self, code, *, retryable=False):
        self.code = code
        self.retryable = retryable
        super().__init__(code)


def handle_of(record_id):
    return UUID(record_id).hex


def record_of(handle):
    return str(UUID(hex=handle))


def _now():
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(kind, **fields):
    return hashlib.sha256(_canonical({"schema": "credential-act-v1", "kind": kind, **fields})
                          .encode("utf-8")).hexdigest()


class CredentialCommandLedger:
    """Durable control-plane record of owner acts, their commands and receipts."""

    def __init__(self, path):
        self._path = Path(path)
        if self._path.is_symlink():
            raise ValueError("credential command ledger cannot be a symlink")
        descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
        os.chmod(self._path, 0o600)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS acts (
                    intent_id TEXT PRIMARY KEY, kind TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    handle TEXT NOT NULL, provider TEXT NOT NULL,
                    store_metadata TEXT, store_state TEXT,
                    retire_command TEXT, retire_record TEXT, retire_reason TEXT, retire_state TEXT,
                    outcome TEXT, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records (
                    record_id TEXT NOT NULL, record_version INTEGER NOT NULL,
                    provider TEXT NOT NULL, command_id TEXT NOT NULL UNIQUE,
                    ciphertext_sha256 TEXT NOT NULL, state TEXT NOT NULL,
                    PRIMARY KEY(record_id, record_version));
            """)

    def _connect(self):
        db = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        return _Transaction(db)

    # ---------------------------------------------------------------- reads

    def act(self, intent_id):
        with self._connect() as db:
            return db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()

    def current(self, db, handle):
        """The newest receipted version of a handle, or None."""
        return db.execute("SELECT * FROM records WHERE record_id=? ORDER BY record_version DESC LIMIT 1",
                          (record_of(handle),)).fetchone()

    def snapshot(self):
        """Committed redacted state only; zero vault/gateway/provider/network effect."""
        with self._connect() as db:
            entries = {}
            for row in db.execute("SELECT * FROM records ORDER BY record_id, record_version"):
                entries[handle_of(row["record_id"])] = {
                    "handle": handle_of(row["record_id"]), "provider": row["provider"],
                    "state": row["state"]}
            for row in db.execute("SELECT * FROM acts WHERE kind='create' ORDER BY created_at, intent_id"):
                if row["handle"] in entries:
                    continue
                state = {"secret_input_lost": "secret_input_lost", "sent": "pending"}.get(row["store_state"])
                if state is not None:
                    entries[row["handle"]] = {"handle": row["handle"], "provider": row["provider"],
                                              "state": state}
            return list(entries.values())[:256]

    # ---------------------------------------------------------------- allocation

    def allocate_store(self, *, intent_id, provider, rotate_from):
        """Return the act row for an intent, allocating it (and its command ids) once."""
        kind = "create" if rotate_from is None else "rotate"
        fingerprint = _fingerprint(kind, provider=provider, rotate_from=rotate_from)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise CredentialCommandError("conflict")
                return row
            if provider not in PROVIDER_MODES:
                raise CredentialCommandError("invalid_input")
            retire_command = retire_record = retire_reason = retire_state = None
            if rotate_from is None:
                record_id, version, predecessor = str(uuid4()), 1, None
            else:
                current = self.current(db, rotate_from)
                if current is None:
                    raise CredentialCommandError("not_found")
                if current["state"] != "stored_unbound" or current["provider"] != provider:
                    raise CredentialCommandError("conflict")
                self._require_quiet(db, rotate_from)
                record_id, version = current["record_id"], current["record_version"] + 1
                predecessor = {"record_id": record_id, "record_version": current["record_version"],
                               "ciphertext_sha256": current["ciphertext_sha256"]}
                retire_command, retire_reason, retire_state = str(uuid4()), "superseded", "allocated"
                retire_record = _canonical(predecessor)
            metadata = {"command_id": str(uuid4()), "record_id": record_id, "record_version": version,
                        "provider": provider, "auth_mode": PROVIDER_MODES[provider],
                        "created_at": _now(), "predecessor": predecessor}
            db.execute("INSERT INTO acts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                intent_id, kind, fingerprint, handle_of(record_id), provider, _canonical(metadata),
                "allocated", retire_command, retire_record, retire_reason, retire_state, None, _now()))
            return db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()

    def allocate_delete(self, *, intent_id, handle):
        fingerprint = _fingerprint("delete", handle=handle)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()
            if row is not None:
                if row["fingerprint"] != fingerprint:
                    raise CredentialCommandError("conflict")
                return row
            current = self.current(db, handle)
            if current is None:
                raise CredentialCommandError("not_found")
            if current["state"] != "stored_unbound":
                raise CredentialCommandError("conflict")
            self._require_quiet(db, handle)
            record = {"record_id": current["record_id"], "record_version": current["record_version"],
                      "ciphertext_sha256": current["ciphertext_sha256"]}
            db.execute("INSERT INTO acts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                intent_id, "delete", fingerprint, handle, current["provider"], None, None,
                str(uuid4()), _canonical(record), "owner_delete", "allocated", None, _now()))
            return db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()

    @staticmethod
    def _require_quiet(db, handle):
        # One unfinished act per handle: a rotation or delete whose outcome is still
        # ambiguous must be resolved before another act can target the same record.
        busy = db.execute(
            "SELECT 1 FROM acts WHERE handle=? AND outcome IS NULL AND kind != 'create'",
            (handle,)).fetchone()
        if busy is not None:
            raise CredentialCommandError("act_in_progress", retryable=True)

    # ---------------------------------------------------------------- transitions

    def claim(self, intent_id, column, *, expected, new):
        """Compare-and-set one phase state; True only for the one winner."""
        if column not in ("store_state", "retire_state"):
            raise ValueError(column)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(f"UPDATE acts SET {column}=? WHERE intent_id=? AND {column}=?",
                                (new, intent_id, expected))
            return cursor.rowcount == 1

    def adopt_store_receipt(self, intent_id, metadata, receipt):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM records WHERE command_id=?",
                                  (metadata["command_id"],)).fetchone()
            if existing is None:
                db.execute("INSERT INTO records VALUES(?,?,?,?,?,?)", (
                    metadata["record_id"], metadata["record_version"], metadata["provider"],
                    metadata["command_id"], receipt["ciphertext_sha256"],
                    "cleanup_pending" if receipt["state"] == "cleanup_pending" else "stored_unbound"))
            elif existing["ciphertext_sha256"] != receipt["ciphertext_sha256"]:
                raise CredentialCommandError("conflict")
            db.execute("UPDATE acts SET store_state='stored' WHERE intent_id=?", (intent_id,))
            row = db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()
            if row["retire_state"] is None:
                db.execute("UPDATE acts SET outcome='done' WHERE intent_id=?", (intent_id,))

    def terminal_store(self, intent_id, state):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE acts SET store_state=?, outcome=? WHERE intent_id=?",
                       (state, state, intent_id))

    def terminal_retire(self, intent_id):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE acts SET retire_state='conflict', outcome='conflict' WHERE intent_id=?",
                       (intent_id,))

    def adopt_retirement(self, intent_id, record):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE records SET state='cleanup_pending' WHERE record_id=? AND record_version=?",
                       (record["record_id"], record["record_version"]))
            db.execute("UPDATE acts SET retire_state='retired', outcome='done' WHERE intent_id=?",
                       (intent_id,))


class _Transaction:
    """A connection whose `with` commits an explicit transaction or rolls it back."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, kind, _value, _traceback):
        try:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK" if kind is not None else "COMMIT")
        finally:
            self._db.close()


class CredentialActs:
    """Drive owner acts against a frame-only gateway client (no vault import)."""

    def __init__(self, client, ledger):
        from ..workers.credential_channel import GatewayServiceError

        if type(ledger) is not CredentialCommandLedger:
            raise TypeError("an exact credential command ledger is required")
        for name in ("store_at", "query_record", "retire"):
            if not callable(getattr(client, name, None)):
                raise TypeError("a credential gateway client is required")
        self._client = client
        self._ledger = ledger
        self._gateway_error = GatewayServiceError

    # ------------------------------------------------------------ create / rotate

    def store(self, ingress):
        """Create or rotate; the secret is transmitted at most once per command id."""
        act = self._ledger.allocate_store(intent_id=ingress.intent_id, provider=ingress.provider,
                                          rotate_from=ingress.rotate_from)
        metadata = json.loads(act["store_metadata"])
        intent = act["intent_id"]
        if act["store_state"] == "allocated" and self._ledger.claim(
                intent, "store_state", expected="allocated", new="sent"):
            try:
                receipt = self._client.store_at(metadata=metadata, secret=ingress.secret)
            except self._gateway_error as exc:
                if not exc.sent or exc.code in _NOT_ADMITTED:
                    # definitively not admitted: the command id was not consumed
                    self._ledger.claim(intent, "store_state", expected="sent", new="allocated")
                    raise CredentialCommandError("gateway_unavailable", retryable=True) from None
                if exc.code == "conflict":
                    self._ledger.terminal_store(intent, "conflict")
                    raise CredentialCommandError("conflict") from None
                receipt = None  # ambiguous: recover by querying the same command id
            if receipt is not None:
                self._settle_store(intent, metadata, receipt)
        act = self._ledger.act(intent)
        if act["store_state"] == "sent":
            self._recover_store(intent, metadata)
            act = self._ledger.act(intent)
        if act["store_state"] in ("secret_input_lost", "conflict"):
            raise CredentialCommandError(act["store_state"])
        if act["store_state"] != "stored":
            raise CredentialCommandError("command_pending", retryable=True)
        if act["retire_state"] == "conflict":
            raise CredentialCommandError("conflict")
        if act["retire_state"] is not None and act["retire_state"] != "retired":
            self._retire(act)
        return {"handle": act["handle"], "provider": act["provider"], "state": "stored_unbound"}

    def _recover_store(self, intent, metadata):
        try:
            result = self._client.query_record(metadata=metadata)
        except self._gateway_error as exc:
            if exc.code == "conflict":
                self._ledger.terminal_store(intent, "conflict")
                raise CredentialCommandError("conflict") from None
            raise CredentialCommandError("command_pending", retryable=True) from None
        self._settle_store(intent, metadata, result)

    def _settle_store(self, intent, metadata, result):
        if type(result) is not dict or result.get("command_id") != metadata["command_id"]:
            raise CredentialCommandError("gateway_invalid")
        state = result.get("state")
        if state == "secret_input_lost":
            self._ledger.terminal_store(intent, "secret_input_lost")
            return
        if state in ("unknown", "pending"):
            return  # nonterminal: never a new id, a new secret or a loss verdict
        if (state not in ("stored_unbound", "cleanup_pending")
                or any(result.get(name) != metadata[name] for name in
                       ("record_id", "record_version", "provider", "auth_mode", "created_at"))
                or type(result.get("ciphertext_sha256")) is not str
                or _HEX64.fullmatch(result["ciphertext_sha256"]) is None):
            raise CredentialCommandError("gateway_invalid")
        self._ledger.adopt_store_receipt(intent, metadata, result)

    # ------------------------------------------------------------ delete / supersede

    def delete(self, *, intent_id, handle):
        act = self._ledger.allocate_delete(intent_id=intent_id, handle=handle)
        if act["retire_state"] == "conflict":
            raise CredentialCommandError("conflict")
        if act["retire_state"] != "retired":
            self._retire(act)
        return {"handle": handle, "state": "cleanup_pending"}

    def _retire(self, act):
        """Retirement carries no secret and is idempotent under its command id: an
        ambiguous result is recovered by replaying the exact same retirement."""
        intent = act["intent_id"]
        self._ledger.claim(intent, "retire_state", expected="allocated", new="sent")
        record = json.loads(act["retire_record"])
        try:
            result = self._client.retire(command_id=act["retire_command"], record=record,
                                         reason=act["retire_reason"])
        except self._gateway_error as exc:
            if exc.code == "conflict":
                self._ledger.terminal_retire(intent)
                raise CredentialCommandError("conflict") from None
            raise CredentialCommandError("command_pending", retryable=True) from None
        if (type(result) is not dict or result.get("state") != "cleanup_pending"
                or result.get("command_id") != act["retire_command"] or result.get("record") != record
                or result.get("reason") != act["retire_reason"]):
            raise CredentialCommandError("gateway_invalid")
        self._ledger.adopt_retirement(intent, record)


__all__ = ["CredentialActs", "CredentialCommandError", "CredentialCommandLedger"]
