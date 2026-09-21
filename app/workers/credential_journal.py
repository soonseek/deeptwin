"""Bounded nonsecret SQLite journal; callers hold the independent mutation flock."""
from contextlib import contextmanager
import os
import sqlite3
import time
from pathlib import Path
from hashlib import sha256

from .credential_contracts import (CredentialVaultError, canonical, strict_json,
    metadata_value, fingerprint, reference, uuid_value)

MAX_COMMANDS, MAX_RECORDS, MAX_NONCES = 4096, 2048, 8192
MAX_JOURNAL_BYTES = 16 * 1024 * 1024

SCHEMA = """
CREATE TABLE binding (id INTEGER PRIMARY KEY CHECK(id=1), body BLOB NOT NULL);
CREATE TABLE nonces (key_id TEXT NOT NULL, nonce BLOB NOT NULL CHECK(length(nonce)=24), PRIMARY KEY(key_id,nonce));
CREATE TABLE commands (command_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, metadata BLOB NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','secret_input_lost','stored_unbound')),
 key_id TEXT NOT NULL, nonce BLOB NOT NULL, record_id TEXT NOT NULL, version INTEGER NOT NULL,
 UNIQUE(record_id,version), FOREIGN KEY(key_id,nonce) REFERENCES nonces(key_id,nonce));
CREATE TABLE receipts (command_id TEXT PRIMARY KEY REFERENCES commands(command_id), body BLOB NOT NULL);
CREATE TABLE retirements (command_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, body BLOB NOT NULL,
 target_command TEXT NOT NULL REFERENCES receipts(command_id));
"""


def checked_files(directory, *, custody_budget=None):
    if custody_budget is not None:
        custody_budget.checkpoint()
    directory.verify()
    if "journal.sqlite" not in directory.names():
        raise CredentialVaultError("maintenance_required")
    for name in ("journal.sqlite", "journal.sqlite-journal", "journal.sqlite-wal", "journal.sqlite-shm"):
        if name in directory.names():
            fd = directory.file(name, writable=True)
            try:
                if os.fstat(fd).st_size > MAX_JOURNAL_BYTES:
                    raise CredentialVaultError("maintenance_required")
            finally:
                os.close(fd)
        if custody_budget is not None:
            custody_budget.checkpoint()


class Journal:
    def __init__(self, directory, layout, *, initialize=False, custody_budget=None):
        self.directory = directory
        self.connection = None
        self._custody_budget = custody_budget
        try:
            if initialize:
                directory.write("journal.sqlite", b"")
            checked_files(directory, custody_budget=custody_budget)
            self.connection = sqlite3.connect(Path(directory.path, "journal.sqlite").as_uri() + "?mode=rw",
                uri=True, timeout=0 if custody_budget is not None else 5, isolation_level=None)
            self.connection.row_factory = sqlite3.Row
            for pragma in ("PRAGMA foreign_keys=ON",
                           "PRAGMA busy_timeout=" + ("0" if custody_budget is not None else "5000")):
                if custody_budget is not None:
                    custody_budget.checkpoint()
                self.connection.execute(pragma)
                if custody_budget is not None:
                    custody_budget.checkpoint()
            if custody_budget is not None:
                self.connection.set_progress_handler(
                    lambda: int(custody_budget.cancel_event.is_set()
                                or time.monotonic() >= custody_budget.deadline_monotonic), 1000)
            self.connection.execute("PRAGMA synchronous=FULL")
            if custody_budget is not None:
                custody_budget.checkpoint()
            # DELETE journaling retains no long-lived WAL and creates sidecars with DB mode.
            if initialize:
                self.connection.executescript("BEGIN IMMEDIATE;" + SCHEMA)
                self.connection.execute("INSERT INTO binding VALUES(1,?)", (canonical(layout),))
                self.connection.execute("COMMIT")
                os.fsync(directory.fd)
            if self.checked_read("PRAGMA journal_mode")[0][0] != "delete":
                raise CredentialVaultError("maintenance_required")
            expected_schema = sorted(part.strip() for part in SCHEMA.split(";") if part.strip())
            actual_schema = sorted(row[0] for row in self.checked_read(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"))
            if actual_schema != expected_schema:
                raise CredentialVaultError("maintenance_required")
            if self.checked_read("PRAGMA integrity_check")[0][0] != "ok" or self.checked_read(
                    "PRAGMA foreign_key_check"):
                raise CredentialVaultError("maintenance_required")
            bindings = self.checked_read("SELECT * FROM binding")
            if len(bindings) != 1 or bindings[0]["id"] != 1 or strict_json(bindings[0]["body"], 4096) != layout:
                raise CredentialVaultError("maintenance_required")
            checked_files(directory, custody_budget=custody_budget)
            self.capacity(existing=True)
            self._validate_metadata(layout, custody_budget=custody_budget)
        except sqlite3.Error as exc:
            self.close()
            if custody_budget is not None:
                custody_budget.checkpoint()
                if getattr(exc, "sqlite_errorcode", None) in {
                        sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                    raise CredentialVaultError("busy") from None
            raise CredentialVaultError("maintenance_required") from None
        except OSError:
            self.close()
            raise CredentialVaultError("maintenance_required") from None
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.connection is not None:
            self.connection.set_progress_handler(None, 0)
            self.connection.close()
            self.connection = None

    def checked_read(self, sql, parameters=()):
        """Bound a fixed code-owned read under the one absolute custody budget."""
        if type(sql) is not str or type(parameters) is not tuple or not (
                sql.startswith("SELECT ") or sql.startswith("PRAGMA ")):
            raise CredentialVaultError("maintenance_required")
        budget = self._custody_budget
        if budget is not None:
            budget.checkpoint()
        cursor = self.connection.cursor()
        rows = []
        try:
            cursor.execute(sql, parameters)
            while True:
                if budget is not None:
                    budget.checkpoint()
                row = cursor.fetchone()
                if row is None:
                    break
                if len(rows) >= 8192:
                    raise CredentialVaultError("capacity_exhausted")
                rows.append(row)
            if budget is not None:
                budget.checkpoint()
            return rows
        except sqlite3.Error as exc:
            if budget is not None:
                budget.checkpoint()
                if getattr(exc, "sqlite_errorcode", None) in {
                        sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                    raise CredentialVaultError("busy") from None
            raise
        finally:
            cursor.close()

    def _validate_metadata(self, layout, *, custody_budget=None):
        """Every coherent read validates nonsecret records without decrypting keys."""
        db = self.connection
        commands = {}
        for row in self.checked_read("SELECT * FROM commands"):
            if custody_budget is not None:
                custody_budget.checkpoint()
            meta = metadata_value(strict_json(row["metadata"], 4096))
            if (meta["command_id"] != row["command_id"] or fingerprint(meta) != row["fingerprint"]
                    or meta["record_id"] != row["record_id"] or meta["record_version"] != row["version"]
                    or row["key_id"] != layout["key_id"] or type(row["nonce"]) is not bytes or len(row["nonce"]) != 24):
                raise CredentialVaultError("maintenance_required")
            commands[row["command_id"]] = (meta, row["state"])
        for row in self.checked_read("SELECT * FROM nonces"):
            if custody_budget is not None:
                custody_budget.checkpoint()
            if row["key_id"] != layout["key_id"] or type(row["nonce"]) is not bytes or len(row["nonce"]) != 24:
                raise CredentialVaultError("maintenance_required")
        receipts = {}
        for row in self.checked_read("SELECT * FROM receipts"):
            if custody_budget is not None:
                custody_budget.checkpoint()
            receipt = strict_json(row["body"], 4096)
            meta, state = commands[row["command_id"]]
            if type(receipt) is not dict or set(receipt) != {"command_id", "record_id", "record_version", "provider", "auth_mode", "created_at", "ciphertext_sha256", "state"}:
                raise CredentialVaultError("maintenance_required")
            ref = reference({k: receipt[k] for k in ("record_id", "record_version", "ciphertext_sha256")})
            expected = {k: meta[k] for k in ("command_id", "record_id", "record_version", "provider", "auth_mode", "created_at")}
            expected.update(ciphertext_sha256=ref["ciphertext_sha256"], state="stored_unbound")
            if receipt != expected or state == "pending":
                raise CredentialVaultError("maintenance_required")
            receipts[row["command_id"]] = receipt
        if any(state == "stored_unbound" and command not in receipts for command, (_, state) in commands.items()):
            raise CredentialVaultError("maintenance_required")
        for row in self.checked_read("SELECT * FROM retirements"):
            if custody_budget is not None:
                custody_budget.checkpoint()
            body = strict_json(row["body"], 4096)
            if (type(body) is not dict or set(body) != {"command_id", "record", "reason", "state"}
                    or body["command_id"] != row["command_id"] or body["state"] != "cleanup_pending"
                    or body["reason"] not in ("owner_delete", "superseded", "unbound_orphan")):
                raise CredentialVaultError("maintenance_required")
            uuid_value(body["command_id"])
            ref = reference(body["record"])
            if body["command_id"] in commands or ref != {k: receipts[row["target_command"]][k] for k in ref}:
                raise CredentialVaultError("maintenance_required")
            if row["fingerprint"] != sha256(canonical({k: v for k, v in body.items() if k != "state"})).hexdigest():
                raise CredentialVaultError("maintenance_required")

    def count(self, table):
        if table not in ("commands", "nonces", "receipts", "retirements"):
            raise CredentialVaultError("maintenance_required")
        return self.checked_read("SELECT count(*) FROM " + table)[0][0]

    def capacity(self, *, existing=False, retirement=False):
        commands = self.count("commands") + self.count("retirements")
        if (commands > MAX_COMMANDS if existing else commands >= MAX_COMMANDS):
            raise CredentialVaultError("capacity_exhausted")
        if not retirement:
            records, nonces = self.count("commands"), self.count("nonces")
            exceeded = (records > MAX_RECORDS or nonces > MAX_NONCES) if existing else (records >= MAX_RECORDS or nonces >= MAX_NONCES)
            if exceeded:
                raise CredentialVaultError("capacity_exhausted")

    @contextmanager
    def transaction(self):
        checked_files(self.directory, custody_budget=self._custody_budget)
        try:
            if self._custody_budget is not None:
                self._custody_budget.checkpoint()
            self.connection.execute("BEGIN IMMEDIATE")
            yield self.connection
            if self._custody_budget is not None:
                self._custody_budget.checkpoint()
            self.connection.execute("COMMIT")
            checked_files(self.directory, custody_budget=self._custody_budget)
        except BaseException:
            if self.connection.in_transaction:
                self.connection.execute("ROLLBACK")
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
