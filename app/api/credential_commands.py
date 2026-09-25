"""Control-plane credential command ledger and owner-act driver (T090).

Each explicit owner act (create, rotate, delete) carries a browser-chosen
``intent_id`` idempotency key. Before anything reaches the gateway the control
plane allocates the act's gateway command id(s) and the exact nonsecret target
(record id, version, predecessor reference, expected binding revision) and commits
them here in one SQLite transaction. The raw secret is never persisted, hashed or
compared: it lives only in the request memory of the call that transmits it.

Recovery follows the custody contract. A command whose transmission may have
reached the gateway (any failure other than a pre-send connection failure or a
definitive non-admission answer) is never re-sent with a secret: a retry of the
same act queries that command id (``query_record``) and adopts the committed
receipt, reports the nonterminal ``pending``/``unknown`` as retryable, or the
terminal ``secret_input_lost`` (after which only a new act with a fresh intent
and explicit secret re-entry may try again). Retirement carries no secret and
is idempotent under its command id, so its recovery is a same-command replay.

Provider connection binding (api.md "Secrets"): a custody receipt is never binding
authority. After the receipt is persisted, a second ledger transaction applies the
provider connection binding by compare-and-swap on the connection's binding
revision recorded at allocation: a create binds only an unbound connection, a
rotation moves the binding from its exact predecessor to the successor. A rotation
or delete invalidates, in that same transaction, every catalog snapshot and model
choice bound to the previous binding revision; a new catalog exists only through
an explicit refresh (:meth:`CredentialCommandLedger.record_catalog_refresh`).
A delete first CAS-revokes the binding to ``revoked_pending_erasure`` and only then
retires the record. A stored record that loses its binding CAS is a valid unbound
orphan: it is retired with reason ``unbound_orphan`` and never bound.

Gateway binding head: after each head change (create/rotate CAS, delete revoke) the
head is published to the gateway (``bind_head``, idempotent per revision) before the
act retires anything, and the act completes only once the gateway acknowledged it.
The gateway's send path delivers custody, at claim time, only for the record its head
binds; a head the gateway has not acknowledged is listed ``gateway_head: pending`` and
republished by the next act (a send naming its record is refused meanwhile).

Catalog refresh: :meth:`CredentialActs.refresh_catalog` is the owner's one explicit
provider read. It lists the models for the current binding revision through the
gateway's provider-send path and records them by CAS on that revision.

Unknown-command fence: the custody contract defines no gateway cancel/fence
operation, so a store command whose query stays ``unknown`` cannot be cancelled at
the gateway. After ``fence_after_seconds`` the owner may explicitly fence the act
(:meth:`CredentialActs.fence`): one more query must still answer ``unknown`` (a
committed answer is retired as ``unbound_orphan``; a lost answer is terminal),
then the act becomes terminal ``fenced`` without any secret being re-sent, and its
command can never be bound. A later rotation skips the fenced version. Because a
delayed accepted store may still commit afterwards, the fence is reconciled on
later owner acts: a fenced command that turns out stored is retired as
``unbound_orphan``. The fence neutralizes a late commit; it does not prevent it.

Reads (``snapshot``) serve only what this ledger already committed; they make
no vault, gateway, provider or network call. No create/rotate/delete/fence act
checks a key at the provider, refreshes a catalog or runs a model; only the explicit
refresh act reads the provider's model list. This module imports no vault code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

PROVIDER_MODES = {"claude": "api", "codex": "api"}
FENCE_AFTER_SECONDS = 300
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_MODELS = 200
_RECONCILE_BOUND = 16
_NOT_ADMITTED = frozenset({"busy", "capacity_exhausted", "nonce_exhausted",
                           "invalid_secret", "invalid_encoding", "unsupported_operation"})

_SCHEMA = """
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
CREATE TABLE IF NOT EXISTS connections (
    provider TEXT PRIMARY KEY, revision INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('bound', 'revoked_pending_erasure')),
    record TEXT NOT NULL, command_id TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS catalogs (
    provider TEXT NOT NULL, binding_revision INTEGER NOT NULL,
    refresh_command TEXT NOT NULL UNIQUE, models TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('current', 'invalidated')),
    refreshed_at TEXT NOT NULL, invalidated_at TEXT,
    PRIMARY KEY(provider, binding_revision));
CREATE TABLE IF NOT EXISTS model_choices (
    provider TEXT NOT NULL, binding_revision INTEGER NOT NULL, model TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('current', 'invalidated')),
    chosen_at TEXT NOT NULL, invalidated_at TEXT,
    PRIMARY KEY(provider, binding_revision));
CREATE TABLE IF NOT EXISTS orphans (
    command_id TEXT PRIMARY KEY, record TEXT NOT NULL, provider TEXT NOT NULL,
    source_intent TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('allocated', 'retired', 'conflict')),
    created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stale_refreshes (
    refresh_command TEXT PRIMARY KEY, provider TEXT NOT NULL, binding_revision INTEGER NOT NULL,
    refused_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS fences (
    store_command TEXT PRIMARY KEY, intent_id TEXT NOT NULL UNIQUE, metadata TEXT NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('fenced', 'orphaned', 'lost')),
    fenced_at TEXT NOT NULL);
"""
# Columns added to the first ledger layout; an older ledger gains them on open.
_ADDED_COLUMNS = (
    ("acts", "sent_at", "REAL"),
    ("acts", "binding_expected", "INTEGER"),
    ("acts", "bind_state", "TEXT"),
    ("records", "orphan", "INTEGER NOT NULL DEFAULT 0"),
    # the highest binding revision the gateway acknowledged through `bind_head`
    ("connections", "gateway_revision", "INTEGER NOT NULL DEFAULT 0"),
)
# Providers whose model list the gateway's send path can read (its `models` endpoint).
LISTABLE_PROVIDERS = frozenset({"claude"})


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


def _iso(seconds):
    return datetime.fromtimestamp(seconds, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(kind, **fields):
    return hashlib.sha256(_canonical({"schema": "credential-act-v1", "kind": kind, **fields})
                          .encode("utf-8")).hexdigest()


def _uncertain(fence_state, record_state):
    """What is known of a fenced command's record: still ``unknown`` at the gateway, its
    ingress lost, or a late commit whose ``unbound_orphan`` retirement is pending/done."""
    if fence_state == "fenced":
        return "unknown"
    if fence_state == "lost":
        return "secret_input_lost"
    return "cleanup_pending" if record_state == "cleanup_pending" else "retirement_pending"


def _reference(row):
    return {"record_id": row["record_id"], "record_version": row["record_version"],
            "ciphertext_sha256": row["ciphertext_sha256"]}


class CredentialCommandLedger:
    """Durable control-plane record of owner acts, their commands, receipts, the provider
    connection bindings and the catalog/model authority bound to each binding revision."""

    def __init__(self, path, *, fence_after_seconds=FENCE_AFTER_SECONDS, clock=time.time):
        if type(fence_after_seconds) not in (int, float) or fence_after_seconds < 0:
            raise ValueError("fence delay must be a nonnegative number of seconds")
        if not callable(clock):
            raise TypeError("clock must be callable")
        self._path = Path(path)
        if self._path.is_symlink():
            raise ValueError("credential command ledger cannot be a symlink")
        descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
        os.chmod(self._path, 0o600)
        self._lock = threading.RLock()
        self.fence_after_seconds = fence_after_seconds
        self.clock = clock
        with self._connect() as db:
            db.executescript(_SCHEMA)
            for table, column, declaration in _ADDED_COLUMNS:
                names = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
                if column not in names:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    def _connect(self):
        db = sqlite3.connect(self._path, timeout=5, isolation_level=None)
        db.row_factory = sqlite3.Row
        return _Transaction(db)

    # ---------------------------------------------------------------- reads

    def act(self, intent_id):
        with self._connect() as db:
            return db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()

    def current(self, db, handle):
        """The newest receipted, non-orphan version of a handle, or None."""
        return db.execute(
            "SELECT * FROM records WHERE record_id=? AND orphan=0 "
            "ORDER BY record_version DESC LIMIT 1", (record_of(handle),)).fetchone()

    @staticmethod
    def _connection(db, provider):
        return db.execute("SELECT * FROM connections WHERE provider=?", (provider,)).fetchone()

    def connection(self, provider):
        """The provider connection's binding head (a committed read), or None."""
        with self._connect() as db:
            row = self._connection(db, provider)
            if row is None:
                return None
            return {"provider": row["provider"], "revision": row["revision"], "state": row["state"],
                    "record": json.loads(row["record"]), "command_id": row["command_id"]}

    def catalog(self, provider):
        """The current catalog snapshot bound to the current binding revision, or None."""
        with self._connect() as db:
            row = self._current_catalog(db, provider)
            return None if row is None else {"binding_revision": row["binding_revision"],
                                             "models": json.loads(row["models"])}

    def model_choice(self, provider):
        with self._connect() as db:
            head = self._connection(db, provider)
            if head is None or head["state"] != "bound":
                return None
            row = db.execute("SELECT * FROM model_choices WHERE provider=? AND binding_revision=? "
                             "AND state='current'", (provider, head["revision"])).fetchone()
            return None if row is None else {"binding_revision": row["binding_revision"],
                                             "model": row["model"]}

    def unpublished_heads(self):
        """Binding heads the gateway has not yet acknowledged (bounded)."""
        with self._connect() as db:
            return [{"provider": row["provider"], "revision": row["revision"], "state": row["state"],
                     "record": json.loads(row["record"])} for row in db.execute(
                "SELECT * FROM connections WHERE gateway_revision < revision ORDER BY provider "
                "LIMIT ?", (_RECONCILE_BOUND,))]

    def mark_head_published(self, provider, revision):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE connections SET gateway_revision=? WHERE provider=? AND "
                       "gateway_revision < ?", (revision, provider, revision))

    def bound_head(self, provider):
        """The bound head, whether the gateway acknowledged it, and the vault metadata of
        the record it binds (nonsecret; what a send names), or None."""
        with self._connect() as db:
            row = self._connection(db, provider)
            if row is None or row["state"] != "bound":
                return None
            record = json.loads(row["record"])
            for act in db.execute("SELECT store_metadata FROM acts WHERE handle=? AND "
                                  "store_metadata IS NOT NULL", (handle_of(record["record_id"]),)):
                metadata = json.loads(act["store_metadata"])
                if metadata["command_id"] == row["command_id"]:
                    return {"provider": provider, "revision": row["revision"], "record": record,
                            "published": row["gateway_revision"] >= row["revision"],
                            "metadata": metadata}
            return None

    def refresh_result(self, refresh_command):
        """(provider, binding revision, state) of a refresh already recorded (``stale``
        when it was refused because the binding moved), or None."""
        with self._connect() as db:
            row = db.execute("SELECT provider, binding_revision, state FROM catalogs WHERE "
                             "refresh_command=?", (refresh_command,)).fetchone()
            if row is None:
                row = db.execute("SELECT provider, binding_revision, 'stale' AS state FROM "
                                 "stale_refreshes WHERE refresh_command=?",
                                 (refresh_command,)).fetchone()
            return None if row is None else (row["provider"], row["binding_revision"], row["state"])

    def refuse_refresh(self, refresh_command, provider, binding_revision):
        """Make a refresh whose binding moved terminal: a replay answers ``catalog_stale``."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO stale_refreshes VALUES(?,?,?,?)",
                       (refresh_command, provider, binding_revision, _now()))

    def _current_catalog(self, db, provider):
        head = self._connection(db, provider)
        if head is None or head["state"] != "bound":
            return None
        return db.execute("SELECT * FROM catalogs WHERE provider=? AND binding_revision=? "
                          "AND state='current'", (provider, head["revision"])).fetchone()

    def snapshot(self):
        """Committed redacted state only; zero vault/gateway/provider/network effect."""
        with self._connect() as db:
            entries = {}
            rows = db.execute("SELECT * FROM records ORDER BY record_id, orphan DESC, record_version")
            for row in rows:
                # per handle, the newest non-orphan version wins; an all-orphan handle
                # (a fenced or CAS-lost create) still shows its retirement
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
            connections = []
            for row in db.execute("SELECT * FROM connections ORDER BY provider"):
                bound = row["state"] == "bound"
                catalog = model = None
                if bound:
                    catalog = db.execute("SELECT models FROM catalogs WHERE provider=? AND "
                                         "binding_revision=? AND state='current'",
                                         (row["provider"], row["revision"])).fetchone()
                    model = db.execute("SELECT model FROM model_choices WHERE provider=? AND "
                                       "binding_revision=? AND state='current'",
                                       (row["provider"], row["revision"])).fetchone()
                connections.append({
                    "provider": row["provider"], "state": row["state"],
                    "handle": handle_of(json.loads(row["record"])["record_id"]),
                    "binding_revision": row["revision"],
                    "catalog": "current" if catalog is not None else "absent",
                    "model_choice": "current" if model is not None else "absent",
                    # whether the gateway's send path already enforces this head
                    "gateway_head": ("applied" if row["gateway_revision"] >= row["revision"]
                                     else "pending"),
                    "models": [] if catalog is None else json.loads(catalog["models"]),
                    "chosen_model": None if model is None else model["model"]})
            pending = []
            for row in db.execute(
                    "SELECT a.*, f.state AS fence_state, r.state AS fenced_record FROM acts a "
                    "LEFT JOIN fences f ON f.intent_id=a.intent_id "
                    "LEFT JOIN records r ON r.command_id=f.store_command "
                    "WHERE (a.outcome IS NULL AND (a.store_state='sent' OR a.bind_state='pending' "
                    "OR (a.retire_state IN ('allocated','sent') "
                    "AND (a.store_state IS NULL OR a.store_state='stored')))) "
                    "OR a.store_state='fenced' ORDER BY a.created_at, a.intent_id"):
                fenced = row["store_state"] == "fenced"
                sent = row["store_state"] == "sent"
                pending.append({
                    "intent_id": row["intent_id"], "kind": row["kind"], "handle": row["handle"],
                    "provider": row["provider"],
                    "state": "fenced" if fenced else "command_pending",
                    "fence_available_at": (_iso(row["sent_at"] + self.fence_after_seconds)
                                           if sent and row["sent_at"] is not None else None),
                    "uncertain_record": (_uncertain(row["fence_state"], row["fenced_record"])
                                         if fenced else None)})
            return {"credentials": list(entries.values())[:256], "connections": connections[:16],
                    "pending_acts": pending[:256]}

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
            head = self._connection(db, provider)
            revision = 0 if head is None else head["revision"]
            retire_command = retire_record = retire_reason = retire_state = None
            if rotate_from is None:
                if head is not None and head["state"] == "bound":
                    # one bound credential per provider connection: replacing it is a rotation
                    raise CredentialCommandError("connection_bound")
                record_id, version, predecessor = str(uuid4()), 1, None
            else:
                current = self.current(db, rotate_from)
                if current is None:
                    raise CredentialCommandError("not_found")
                if current["state"] != "stored_unbound" or current["provider"] != provider:
                    raise CredentialCommandError("conflict")
                predecessor = _reference(current)
                if (head is None or head["state"] != "bound"
                        or json.loads(head["record"]) != predecessor):
                    # only the provider's currently bound credential can be rotated
                    raise CredentialCommandError("conflict")
                self._require_quiet(db, rotate_from)
                record_id = current["record_id"]
                version = self._next_version(db, rotate_from, record_id)
                retire_command, retire_reason, retire_state = str(uuid4()), "superseded", "allocated"
                retire_record = _canonical(predecessor)
            metadata = {"command_id": str(uuid4()), "record_id": record_id, "record_version": version,
                        "provider": provider, "auth_mode": PROVIDER_MODES[provider],
                        "created_at": _now(), "predecessor": predecessor}
            db.execute(
                "INSERT INTO acts(intent_id, kind, fingerprint, handle, provider, store_metadata, "
                "store_state, retire_command, retire_record, retire_reason, retire_state, outcome, "
                "created_at, binding_expected) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    intent_id, kind, fingerprint, handle_of(record_id), provider, _canonical(metadata),
                    "allocated", retire_command, retire_record, retire_reason, retire_state, None,
                    _now(), revision))
            return db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()

    @staticmethod
    def _next_version(db, handle, record_id):
        # every version ever allocated to the record is burned, including a fenced one
        # whose delayed store may still commit at the gateway
        highest = db.execute("SELECT max(record_version) FROM records WHERE record_id=?",
                             (record_id,)).fetchone()[0] or 0
        for row in db.execute("SELECT store_metadata FROM acts WHERE handle=? AND "
                              "store_metadata IS NOT NULL", (handle,)):
            highest = max(highest, json.loads(row["store_metadata"])["record_version"])
        return highest + 1

    def allocate_delete(self, *, intent_id, handle):
        """Allocate a delete once. The same transaction first CAS-revokes the provider
        binding (``revoked_pending_erasure``) and invalidates its catalog/model authority,
        so no send or refresh can use the record even while its retirement is pending."""
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
            record = _reference(current)
            head = self._connection(db, current["provider"])
            revision = None
            if head is not None and head["state"] == "bound" and json.loads(head["record"]) == record:
                revision = head["revision"]
                cursor = db.execute(
                    "UPDATE connections SET state='revoked_pending_erasure', revision=?, updated_at=? "
                    "WHERE provider=? AND revision=? AND state='bound'",
                    (revision + 1, _now(), current["provider"], revision))
                if cursor.rowcount != 1:
                    raise CredentialCommandError("conflict")
                self._invalidate(db, current["provider"])
            db.execute(
                "INSERT INTO acts(intent_id, kind, fingerprint, handle, provider, store_metadata, "
                "store_state, retire_command, retire_record, retire_reason, retire_state, outcome, "
                "created_at, binding_expected) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                    intent_id, "delete", fingerprint, handle, current["provider"], None, None,
                    str(uuid4()), _canonical(record), "owner_delete", "allocated", None, _now(),
                    revision))
            return db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()

    @staticmethod
    def _require_quiet(db, handle):
        # One unfinished act per handle: a rotation or delete whose outcome is still
        # ambiguous must be resolved (or its store fenced) before another act can
        # target the same record.
        busy = db.execute(
            "SELECT 1 FROM acts WHERE handle=? AND outcome IS NULL AND kind != 'create'",
            (handle,)).fetchone()
        if busy is not None:
            raise CredentialCommandError("act_in_progress", retryable=True)

    @staticmethod
    def _invalidate(db, provider):
        """Invalidate every catalog snapshot and model choice of a provider connection."""
        stamp = _now()
        db.execute("UPDATE catalogs SET state='invalidated', invalidated_at=? "
                   "WHERE provider=? AND state='current'", (stamp, provider))
        db.execute("UPDATE model_choices SET state='invalidated', invalidated_at=? "
                   "WHERE provider=? AND state='current'", (stamp, provider))

    # ---------------------------------------------------------------- transitions

    def claim(self, intent_id, column, *, expected, new):
        """Compare-and-set one phase state; True only for the one winner."""
        if column not in ("store_state", "retire_state"):
            raise ValueError(column)
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if column == "store_state" and new == "sent":
                cursor = db.execute("UPDATE acts SET store_state=?, sent_at=? WHERE intent_id=? "
                                    "AND store_state=?", (new, self.clock(), intent_id, expected))
            else:
                cursor = db.execute(f"UPDATE acts SET {column}=? WHERE intent_id=? AND {column}=?",
                                    (new, intent_id, expected))
            return cursor.rowcount == 1

    def adopt_store_receipt(self, intent_id, metadata, receipt):
        """Persist the custody receipt (first transaction). Binding is a separate CAS."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()
            if row["store_state"] not in ("sent", "allocated", "stored"):
                raise CredentialCommandError(row["store_state"] or "conflict")
            self._insert_record(db, metadata, receipt, orphan=False)
            db.execute("UPDATE acts SET store_state='stored', bind_state=coalesce(bind_state, 'pending') "
                       "WHERE intent_id=?", (intent_id,))

    @staticmethod
    def _insert_record(db, metadata, receipt, *, orphan):
        existing = db.execute("SELECT * FROM records WHERE command_id=?",
                              (metadata["command_id"],)).fetchone()
        if existing is None:
            db.execute(
                "INSERT INTO records(record_id, record_version, provider, command_id, "
                "ciphertext_sha256, state, orphan) VALUES(?,?,?,?,?,?,?)", (
                    metadata["record_id"], metadata["record_version"], metadata["provider"],
                    metadata["command_id"], receipt["ciphertext_sha256"],
                    "cleanup_pending" if receipt["state"] == "cleanup_pending" else "stored_unbound",
                    int(orphan)))
        elif existing["ciphertext_sha256"] != receipt["ciphertext_sha256"]:
            raise CredentialCommandError("conflict")

    def bind(self, intent_id):
        """Apply the provider binding by compare-and-swap (second transaction).

        Returns ``"bound"`` or ``"orphaned"``; idempotent per act. The CAS succeeds only
        when the connection still has the binding revision recorded at allocation and,
        for a rotation, is still bound to the exact predecessor. A rotation's successful
        CAS invalidates the predecessor's catalog/model authority atomically. A lost CAS
        makes the stored record an unbound orphan with an allocated ``unbound_orphan``
        retirement; a lost rotation leaves its predecessor bound and unretired."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            act = db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()
            if act["bind_state"] in ("bound", "orphaned"):
                return act["bind_state"]
            if act["store_state"] != "stored" or act["bind_state"] != "pending":
                raise CredentialCommandError("conflict")
            metadata = json.loads(act["store_metadata"])
            record_row = db.execute("SELECT * FROM records WHERE command_id=?",
                                    (metadata["command_id"],)).fetchone()
            record = _reference(record_row)
            head = self._connection(db, act["provider"])
            revision = 0 if head is None else head["revision"]
            expected = act["binding_expected"]
            if act["kind"] == "create":
                won = revision == expected and (head is None or head["state"] != "bound")
            else:
                won = (head is not None and revision == expected and head["state"] == "bound"
                       and json.loads(head["record"]) == metadata["predecessor"])
            won = won and record_row["state"] == "stored_unbound"
            if won:
                if head is None:
                    db.execute("INSERT INTO connections(provider, revision, state, record, "
                               "command_id, updated_at) VALUES(?,?,?,?,?,?)", (
                        act["provider"], revision + 1, "bound", _canonical(record),
                        metadata["command_id"], _now()))
                else:
                    cursor = db.execute(
                        "UPDATE connections SET revision=?, state='bound', record=?, command_id=?, "
                        "updated_at=? WHERE provider=? AND revision=?", (
                            revision + 1, _canonical(record), metadata["command_id"], _now(),
                            act["provider"], revision))
                    if cursor.rowcount != 1:
                        raise CredentialCommandError("conflict")
                # the previous binding revision's catalog/model authority is void
                self._invalidate(db, act["provider"])
                outcome = "done" if act["retire_state"] is None else None
                db.execute("UPDATE acts SET bind_state='bound', outcome=? WHERE intent_id=?",
                           (outcome, intent_id))
                return "bound"
            db.execute("UPDATE records SET orphan=1 WHERE command_id=?", (metadata["command_id"],))
            self._allocate_orphan(db, record, act["provider"], intent_id)
            retire_state = None if act["retire_state"] is None else "cancelled"
            db.execute("UPDATE acts SET bind_state='orphaned', outcome='orphaned', retire_state=? "
                       "WHERE intent_id=?", (retire_state, intent_id))
            return "orphaned"

    @staticmethod
    def _allocate_orphan(db, record, provider, source):
        if db.execute("SELECT 1 FROM orphans WHERE source_intent=? AND record=?",
                      (source, _canonical(record))).fetchone() is None:
            db.execute("INSERT INTO orphans VALUES(?,?,?,?,?,?)", (
                str(uuid4()), _canonical(record), provider, source, "allocated", _now()))

    def open_orphans(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM orphans WHERE state='allocated' ORDER BY created_at, command_id "
                "LIMIT ?", (_RECONCILE_BOUND,))]

    def settle_orphan(self, command_id, state):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM orphans WHERE command_id=?", (command_id,)).fetchone()
            db.execute("UPDATE orphans SET state=? WHERE command_id=? AND state='allocated'",
                       (state, command_id))
            if state == "retired":
                record = json.loads(row["record"])
                db.execute("UPDATE records SET state='cleanup_pending' WHERE record_id=? AND "
                           "record_version=?", (record["record_id"], record["record_version"]))

    def terminal_store(self, intent_id, state):
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("UPDATE acts SET store_state=?, outcome=? WHERE intent_id=? AND "
                       "store_state IN ('allocated', 'sent')", (state, state, intent_id))

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

    # ---------------------------------------------------------------- fence

    def fence(self, intent_id, *, committed=None):
        """Make an act whose store stayed ``unknown`` terminal ``fenced`` (owner act).

        ``committed`` is the receipt the fence's own query found, if the command had in
        fact committed: that record is adopted only as an unbound orphan and gets an
        ``unbound_orphan`` retirement. The act's command is never bound or re-sent."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            act = db.execute("SELECT * FROM acts WHERE intent_id=?", (intent_id,)).fetchone()
            if act["store_state"] == "fenced":
                return
            if act["store_state"] != "sent":
                raise CredentialCommandError("not_fenceable")
            metadata = json.loads(act["store_metadata"])
            state = "fenced"
            if committed is not None:
                self._insert_record(db, metadata, committed, orphan=True)
                db.execute("UPDATE records SET orphan=1 WHERE command_id=?", (metadata["command_id"],))
                self._allocate_orphan(db, {"record_id": metadata["record_id"],
                                           "record_version": metadata["record_version"],
                                           "ciphertext_sha256": committed["ciphertext_sha256"]},
                                      act["provider"], intent_id)
                state = "orphaned"
            db.execute("INSERT INTO fences VALUES(?,?,?,?,?)", (
                metadata["command_id"], intent_id, act["store_metadata"], state, _now()))
            retire_state = None if act["retire_state"] is None else "cancelled"
            db.execute("UPDATE acts SET store_state='fenced', outcome='fenced', retire_state=? "
                       "WHERE intent_id=?", (retire_state, intent_id))

    def open_fences(self):
        with self._connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM fences WHERE state='fenced' ORDER BY fenced_at, store_command "
                "LIMIT ?", (_RECONCILE_BOUND,))]

    def fence_state(self, intent_id):
        """(fence state, state of the record the fenced command turned out to store)."""
        with self._connect() as db:
            row = db.execute("SELECT f.state, r.state AS record_state FROM fences f LEFT JOIN "
                             "records r ON r.command_id=f.store_command WHERE f.intent_id=?",
                             (intent_id,)).fetchone()
            return row["state"], row["record_state"]

    def settle_fence(self, store_command, *, committed=None, lost=False):
        """Reconcile a fenced command: a late commit becomes an unbound orphan."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM fences WHERE store_command=? AND state='fenced'",
                             (store_command,)).fetchone()
            if row is None:
                return
            metadata = json.loads(row["metadata"])
            if committed is not None:
                self._insert_record(db, metadata, committed, orphan=True)
                db.execute("UPDATE records SET orphan=1 WHERE command_id=?", (store_command,))
                acts = db.execute("SELECT provider FROM acts WHERE intent_id=?",
                                  (row["intent_id"],)).fetchone()
                self._allocate_orphan(db, {"record_id": metadata["record_id"],
                                           "record_version": metadata["record_version"],
                                           "ciphertext_sha256": committed["ciphertext_sha256"]},
                                      acts["provider"], row["intent_id"])
                db.execute("UPDATE fences SET state='orphaned' WHERE store_command=?", (store_command,))
            elif lost:
                db.execute("UPDATE fences SET state='lost' WHERE store_command=?", (store_command,))

    # ---------------------------------------------------------------- catalog authority

    def record_catalog_refresh(self, provider, *, refresh_command, expected_binding_revision, models):
        """Adopt the result of an explicit ``refresh_catalog`` act for one binding revision.

        This is the only way a catalog snapshot comes to exist; no credential act calls
        it. It requires the connection to be bound at exactly that revision, so a
        rotation or delete between the refresh request and its result voids the result.
        A later refresh at the same revision supersedes the earlier snapshot, and a model
        choice survives only while the new snapshot still lists it."""
        UUID(refresh_command)
        if (type(models) is not list or not 1 <= len(models) <= _MAX_MODELS
                or len(set(models)) != len(models)
                or any(type(name) is not str or _MODEL.fullmatch(name) is None for name in models)):
            raise CredentialCommandError("invalid_input")
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM catalogs WHERE refresh_command=?",
                               (refresh_command,)).fetchone()
            if prior is not None:
                if (prior["provider"], prior["binding_revision"], json.loads(prior["models"])) != (
                        provider, expected_binding_revision, models):
                    raise CredentialCommandError("conflict")
                return
            head = self._connection(db, provider)
            if head is None or head["state"] != "bound" or head["revision"] != expected_binding_revision:
                # the binding moved between the refresh request and its result
                raise CredentialCommandError("catalog_stale")
            db.execute("DELETE FROM catalogs WHERE provider=? AND binding_revision=?",
                       (provider, expected_binding_revision))
            db.execute("INSERT INTO catalogs VALUES(?,?,?,?,?,?,?)", (
                provider, expected_binding_revision, refresh_command, _canonical(models), "current",
                _now(), None))
            choice = db.execute("SELECT model FROM model_choices WHERE provider=? AND binding_revision=? "
                                "AND state='current'", (provider, expected_binding_revision)).fetchone()
            if choice is not None and choice["model"] not in models:
                db.execute("UPDATE model_choices SET state='invalidated', invalidated_at=? WHERE "
                           "provider=? AND binding_revision=?", (_now(), provider,
                                                                  expected_binding_revision))

    def choose_model(self, provider, *, expected_binding_revision, model):
        """Record the owner's model choice; only a model the current catalog lists."""
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            catalog = self._current_catalog(db, provider)
            if catalog is None or catalog["binding_revision"] != expected_binding_revision:
                raise CredentialCommandError("catalog_stale")
            if model not in json.loads(catalog["models"]):
                raise CredentialCommandError("model_not_listed")
            db.execute("INSERT OR REPLACE INTO model_choices VALUES(?,?,?,?,?,?)", (
                provider, expected_binding_revision, model, "current", _now(), None))


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
    """Drive owner acts against a frame-only gateway client (no vault import).

    No create/rotate/delete/fence act performs a provider key check, a catalog refresh,
    a model call or a runtime dispatch: the custody client exposes only custody
    operations and the binding-head publication. The one provider read is the owner's
    explicit :meth:`refresh_catalog`, through the separate ``catalog_lister`` (the
    gateway's provider-send path), and nothing else calls it."""

    def __init__(self, client, ledger, *, catalog_lister=None):
        from ..workers.credential_channel import GatewayServiceError

        if type(ledger) is not CredentialCommandLedger:
            raise TypeError("an exact credential command ledger is required")
        for name in ("store_at", "query_record", "retire", "bind_head"):
            if not callable(getattr(client, name, None)):
                raise TypeError("a credential gateway client is required")
        if catalog_lister is not None and not callable(catalog_lister):
            raise TypeError("a catalog lister must be callable")
        self._client = client
        self._ledger = ledger
        self._lister = catalog_lister
        self._gateway_error = GatewayServiceError

    # ------------------------------------------------------------ binding heads

    def _publish_heads(self, *, strict):
        """Publish every binding head the gateway has not acknowledged (``bind_head``,
        idempotent per revision, no secret). The gateway's send path delivers custody
        only for the record its head binds, so until a rotation's or delete's head is
        acknowledged the act is not complete: ``strict`` raises ``command_pending``
        (retryable; the same act replays the publication)."""
        for head in self._ledger.unpublished_heads():
            try:
                result = self._client.bind_head(provider=head["provider"], revision=head["revision"],
                                                state=head["state"], record=head["record"])
            except self._gateway_error as exc:
                if not strict:
                    continue
                if exc.code == "conflict":
                    # the gateway holds a newer or different head than this ledger
                    raise CredentialCommandError("gateway_invalid") from None
                raise CredentialCommandError("command_pending", retryable=True) from None
            if result != head:
                if not strict:
                    continue
                raise CredentialCommandError("gateway_invalid")
            self._ledger.mark_head_published(head["provider"], head["revision"])

    # ------------------------------------------------------------ create / rotate

    def store(self, ingress):
        """Create or rotate; the secret is transmitted at most once per command id."""
        self._reconcile()
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
        if act["store_state"] in ("secret_input_lost", "conflict", "fenced"):
            raise CredentialCommandError(act["store_state"])
        if act["store_state"] != "stored":
            raise CredentialCommandError("command_pending", retryable=True)
        if self._ledger.bind(intent) == "orphaned":
            # the connection moved on while this record was being stored: it is a valid
            # unbound orphan, retired and never bound (a rotation's predecessor stays bound)
            self._retire_orphans()
            raise CredentialCommandError("connection_conflict")
        # the gateway enforces the new head before the predecessor is retired
        self._publish_heads(strict=True)
        act = self._ledger.act(intent)
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

    @staticmethod
    def _receipt_state(metadata, result):
        """Validate a gateway store/query answer for exactly this command."""
        if type(result) is not dict or result.get("command_id") != metadata["command_id"]:
            raise CredentialCommandError("gateway_invalid")
        state = result.get("state")
        if state in ("secret_input_lost", "unknown", "pending"):
            return state
        if (state not in ("stored_unbound", "cleanup_pending")
                or any(result.get(name) != metadata[name] for name in
                       ("record_id", "record_version", "provider", "auth_mode", "created_at"))
                or type(result.get("ciphertext_sha256")) is not str
                or _HEX64.fullmatch(result["ciphertext_sha256"]) is None):
            raise CredentialCommandError("gateway_invalid")
        return "stored"

    def _settle_store(self, intent, metadata, result):
        state = self._receipt_state(metadata, result)
        if state == "secret_input_lost":
            self._ledger.terminal_store(intent, "secret_input_lost")
            return
        if state in ("unknown", "pending"):
            return  # nonterminal: never a new id, a new secret or a loss verdict
        self._ledger.adopt_store_receipt(intent, metadata, result)

    # ------------------------------------------------------------ delete / supersede

    def delete(self, *, intent_id, handle):
        self._reconcile()
        act = self._ledger.allocate_delete(intent_id=intent_id, handle=handle)
        # the revoked head reaches the gateway before the record is retired
        self._publish_heads(strict=True)
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

    # ------------------------------------------------------------ orphans / fence

    def _retire_orphans(self):
        """Retire every allocated ``unbound_orphan`` (same-command replay on ambiguity)."""
        for orphan in self._ledger.open_orphans():
            record = json.loads(orphan["record"])
            try:
                result = self._client.retire(command_id=orphan["command_id"], record=record,
                                             reason="unbound_orphan")
            except self._gateway_error as exc:
                if exc.code == "conflict":
                    self._ledger.settle_orphan(orphan["command_id"], "conflict")
                continue  # ambiguous or unreachable: replayed by a later reconciliation
            if (type(result) is dict and result.get("state") == "cleanup_pending"
                    and result.get("command_id") == orphan["command_id"]
                    and result.get("record") == record and result.get("reason") == "unbound_orphan"):
                self._ledger.settle_orphan(orphan["command_id"], "retired")

    def _reconcile(self):
        """Best-effort, bounded: query fenced commands and retire orphans. Queries and
        retirements only; never a secret, a new store command or a provider call. Unpublished
        binding heads are republished first (``bind_head``, best effort)."""
        self._publish_heads(strict=False)
        for fence in self._ledger.open_fences():
            metadata = json.loads(fence["metadata"])
            try:
                result = self._client.query_record(metadata=metadata)
                state = self._receipt_state(metadata, result)
            except (self._gateway_error, CredentialCommandError):
                continue
            if state == "stored":
                self._ledger.settle_fence(fence["store_command"], committed=result)
            elif state == "secret_input_lost":
                self._ledger.settle_fence(fence["store_command"], lost=True)
        self._retire_orphans()

    def fence(self, *, intent_id):
        """The owner's explicit resolution of a store act whose command stays unknown.

        Allowed only after ``fence_after_seconds`` since the command was sent, and only
        when a fresh query still answers ``unknown`` (or shows the command committed,
        which is then retired as ``unbound_orphan``). Never re-sends a secret, never
        binds the record, never calls a provider."""
        act = self._ledger.act(intent_id)
        if act is None:
            raise CredentialCommandError("not_found")
        if act["kind"] == "delete":
            raise CredentialCommandError("not_fenceable")
        if act["store_state"] == "fenced":
            self._reconcile()
            return self._fence_receipt(intent_id)
        if act["store_state"] != "sent":
            raise CredentialCommandError("not_fenceable")
        if act["sent_at"] is None or (
                self._ledger.clock() < act["sent_at"] + self._ledger.fence_after_seconds):
            raise CredentialCommandError("fence_not_due", retryable=True)
        metadata = json.loads(act["store_metadata"])
        try:
            result = self._client.query_record(metadata=metadata)
        except self._gateway_error as exc:
            if exc.code == "conflict":
                self._ledger.terminal_store(intent_id, "conflict")
                raise CredentialCommandError("conflict") from None
            raise CredentialCommandError("gateway_unavailable", retryable=True) from None
        state = self._receipt_state(metadata, result)
        if state == "pending":
            # the gateway journaled the command; its own recovery settles it
            raise CredentialCommandError("command_pending", retryable=True)
        if state == "secret_input_lost":
            self._ledger.terminal_store(intent_id, "secret_input_lost")
            raise CredentialCommandError("secret_input_lost")
        self._ledger.fence(intent_id, committed=result if state == "stored" else None)
        self._retire_orphans()
        return self._fence_receipt(intent_id)

    def _fence_receipt(self, intent_id):
        state, record_state = self._ledger.fence_state(intent_id)
        return {"intent_id": intent_id, "state": "fenced",
                "uncertain_record": _uncertain(state, record_state)}

    # ------------------------------------------------------------ catalog / model

    def _catalog_receipt(self, provider):
        head = self._ledger.connection(provider)
        catalog = self._ledger.catalog(provider)
        choice = self._ledger.model_choice(provider)
        if head is None or catalog is None:
            raise CredentialCommandError("catalog_stale")
        return {"provider": provider, "binding_revision": catalog["binding_revision"],
                "catalog": "current", "models": catalog["models"],
                "chosen_model": None if choice is None else choice["model"]}

    def refresh_catalog(self, *, intent_id, provider):
        """The owner's explicit catalog refresh for the connection's CURRENT binding.

        The model list is read through the gateway's provider-send path
        (``catalog_lister``): the gateway resolves the credential from its own custody,
        and only for the record its binding head binds; the control plane names the
        record and never sees the key. The result is recorded with
        :meth:`CredentialCommandLedger.record_catalog_refresh` bound to the revision read
        before the request, so a rotation or delete between request and result makes the
        result stale and it is refused (``catalog_stale``). ``intent_id`` is the refresh
        command: a replay of a recorded refresh answers from the ledger, with no provider
        call. No other act calls this."""
        if self._lister is None:
            raise CredentialCommandError("catalog_unavailable", retryable=True)
        if provider not in PROVIDER_MODES:
            raise CredentialCommandError("invalid_input")
        if provider not in LISTABLE_PROVIDERS:
            raise CredentialCommandError("catalog_unsupported")
        UUID(intent_id)
        prior = self._ledger.refresh_result(intent_id)
        if prior is not None:
            head = self._ledger.connection(provider)
            if (prior[0] != provider or prior[2] != "current" or head is None
                    or head["state"] != "bound" or head["revision"] != prior[1]):
                raise CredentialCommandError("catalog_stale")
            return self._catalog_receipt(provider)
        self._reconcile()
        head = self._ledger.bound_head(provider)
        if head is None:
            raise CredentialCommandError("connection_unbound")
        if not head["published"]:
            # the gateway must enforce this head before a send can name its record
            self._publish_heads(strict=True)
        try:
            models = self._lister(provider=provider, metadata=head["metadata"],
                                  record=head["record"], binding_revision=head["revision"],
                                  refresh_id=intent_id)
        except CatalogListError as exc:
            current = self._ledger.connection(provider)
            if (current is None or current["state"] != "bound"
                    or current["revision"] != head["revision"]):
                self._ledger.refuse_refresh(intent_id, provider, head["revision"])
                raise CredentialCommandError("catalog_stale") from None
            raise CredentialCommandError(exc.code, retryable=exc.retryable) from None
        # CAS on the revision read before the request: a rotation in between voids it
        try:
            self._ledger.record_catalog_refresh(provider, refresh_command=intent_id,
                                                expected_binding_revision=head["revision"],
                                                models=models)
        except CredentialCommandError as exc:
            if exc.code == "invalid_input":  # an empty or out-of-bounds provider list
                raise CredentialCommandError("provider_unavailable", retryable=True) from None
            if exc.code == "catalog_stale":
                self._ledger.refuse_refresh(intent_id, provider, head["revision"])
            raise
        return self._catalog_receipt(provider)

    def choose_model(self, *, provider, binding_revision, model):
        """The owner's model choice: only a model the current revision's catalog lists."""
        if provider not in PROVIDER_MODES:
            raise CredentialCommandError("invalid_input")
        self._ledger.choose_model(provider, expected_binding_revision=binding_revision, model=model)
        return {"provider": provider, "binding_revision": binding_revision, "model": model}


class CatalogListError(RuntimeError):
    """A sanitized failure of the gateway's model-list read (never provider bytes)."""

    RETRYABLE_CODES = ("provider_unavailable",)
    CODES = ("binding_refused", "provider_rejected", "transport_unqualified", "budget_refused",
             *RETRYABLE_CODES)

    def __init__(self, code):
        if code not in self.CODES:
            code = "provider_unavailable"
        self.code = code
        self.retryable = code in self.RETRYABLE_CODES
        super().__init__(code)


__all__ = ["FENCE_AFTER_SECONDS", "LISTABLE_PROVIDERS", "CatalogListError", "CredentialActs", "CredentialCommandError",
           "CredentialCommandLedger"]
