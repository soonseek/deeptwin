"""Durable, masked API-key connection records with staged credential rotation.

The database stores only an opaque backend credential reference and non-secret
binding configuration.  Reads never open the credential vault.  Replacing a key
creates a new vault item before atomically moving the durable pointer; the retired
item is then removed through a tracked cleanup queue so a SQLite failure cannot
leave the current record pointing at a destroyed key.
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import os
import re
import stat
import threading
import time
from itertools import pairwise
from uuid import uuid4

from ..adapters.claude_api import ClaudeAPIAdapter, ClaudeBinding
from ..adapters.codex_api import CodexAPIAdapter, CodexAPIBinding
from ..adapters.keychain import (
    CredentialError,
    CredentialNotFound,
    CredentialRef,
    validate_credential_secret,
)
from ..storage import ConflictError, Store

_CONNECTIONS = {
    ("claude", "api"): "claude",
    ("codex", "api"): "codex_api",
}
_SHORT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_RECORD_VERSION = 1
_STORE_LOCKS_GUARD = threading.Lock()
_STORE_LOCKS = {}


class _StoreMutationLock:
    """Re-entrant thread + process lock for one provider ledger."""

    def __init__(self, path):
        self._path = path
        self._thread_lock = threading.RLock()
        self._local = threading.local()

    def acquire(self):
        if not self._thread_lock.acquire(timeout=10):
            raise TimeoutError("Provider connection ledger is busy")
        depth = getattr(self._local, "depth", 0)
        if depth:
            self._local.depth = depth + 1
            return True
        descriptor = None
        try:
            flags = os.O_CREAT | os.O_RDWR
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(self._path, flags, 0o600)
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode)
                    or info.st_uid != os.getuid()
                    or info.st_nlink != 1):
                raise OSError("Provider connection lock identity is unsafe")
            os.fchmod(descriptor, 0o600)
            deadline = time.monotonic() + 10
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(
                            "Provider connection ledger is busy"
                        ) from None
                    time.sleep(0.05)
            self._local.descriptor = descriptor
            self._local.depth = 1
            return True
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            self._thread_lock.release()
            raise

    def release(self):
        depth = getattr(self._local, "depth", 0)
        if depth < 1:
            raise RuntimeError("Provider connection lock is not held")
        if depth == 1:
            descriptor = self._local.descriptor
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
                del self._local.descriptor
                self._local.depth = 0
        else:
            self._local.depth = depth - 1
        self._thread_lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.release()


def _store_lock(store):
    """One cross-instance serialization boundary per durable provider ledger."""
    key = os.path.realpath(os.fspath(store.path))
    with _STORE_LOCKS_GUARD:
        return _STORE_LOCKS.setdefault(
            key,
            _StoreMutationLock(
                os.path.join(os.path.dirname(key), ".provider-connections.lock")
            ),
        )


class ProviderConnectionConflict(ConflictError):
    """The connection changed after the screen loaded."""


class CorruptProviderConnection(RuntimeError):
    """Persisted connection metadata no longer matches its integrity digest."""


class ProviderCredentialUnavailable(CredentialError):
    """The packaged secure credential store is not available."""


def _canonical(value):
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Invalid provider connection value") from exc


def _digest(value):
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _expected_version(value):
    if type(value) is not int or value < 0:
        raise ValueError("Connection version must be a non-negative integer")
    return value


def _optional_id(value, name):
    if value is None:
        return None
    if type(value) is not str or _SHORT_ID.fullmatch(value) is None:
        raise ValueError(f"Invalid {name}")
    return value


def _identity(provider, mode):
    if (provider, mode) not in _CONNECTIONS:
        raise ValueError("Unsupported provider connection mode")
    return _CONNECTIONS[(provider, mode)]


def _configuration(
    provider,
    *,
    workspace_id,
    project_id,
    organization_id,
):
    workspace_id = _optional_id(workspace_id, "workspace identifier")
    project_id = _optional_id(project_id, "project identifier")
    organization_id = _optional_id(organization_id, "organization identifier")
    if provider == "claude":
        if project_id is not None or organization_id is not None:
            raise ValueError("Claude API does not accept OpenAI account fields")
    elif workspace_id is not None:
        raise ValueError("Codex API does not accept a Claude workspace field")
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "organization_id": organization_id,
    }


class ProviderConnections:
    """Own current API connection pointers without reading secret material."""

    def __init__(self, store, *, credential_vault=None, clock_ms=None):
        if not isinstance(store, Store):
            raise TypeError("Provider connections require the application Store")
        self.store = store
        self._vault = credential_vault
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        # Lifespan re-entry can temporarily leave more than one service object
        # pointing at the same Store. They must share the staging lock or one
        # instance can mistake another instance's not-yet-stored ref for an orphan.
        self._lock = _store_lock(store)
        self._catalog = None
        self._catalog_sync_pending = set()
        # Operational vault failures are observational, not durable connection
        # state.  Bind each override to the durable version that was observed so
        # another service/process can supersede it without leaving this process
        # permanently stale.
        self._credential_states = {}
        self._adapters = {}
        if credential_vault is not None:
            self._adapters = {
                ("claude", "api"): ClaudeAPIAdapter(vault=credential_vault),
                ("codex", "api"): CodexAPIAdapter(vault=credential_vault),
            }
        with store._connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS provider_connections (
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    credential_provider TEXT,
                    credential_identifier TEXT,
                    configuration TEXT NOT NULL,
                    created_at_ms INTEGER NOT NULL,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(provider, mode, version)
                );
                CREATE TABLE IF NOT EXISTS provider_credential_cleanup (
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    credential_provider TEXT NOT NULL,
                    credential_identifier TEXT NOT NULL,
                    retired_at_version INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    cleanup_hash TEXT NOT NULL,
                    PRIMARY KEY(provider, mode, credential_provider, credential_identifier)
                );
                CREATE TABLE IF NOT EXISTS provider_connection_heads (
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(provider, mode)
                );
                CREATE TABLE IF NOT EXISTS provider_credential_allocations (
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    credential_provider TEXT NOT NULL,
                    credential_identifier TEXT NOT NULL,
                    expected_version INTEGER NOT NULL,
                    previous_connection_hash TEXT,
                    created_at_ms INTEGER NOT NULL,
                    previous_hash TEXT,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(provider, mode, sequence),
                    UNIQUE(provider, mode, credential_provider, credential_identifier)
                );
                CREATE TABLE IF NOT EXISTS provider_credential_allocation_heads (
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(provider, mode)
                );
                CREATE TABLE IF NOT EXISTS provider_orphan_cleanup (
                    provider TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    credential_provider TEXT NOT NULL,
                    credential_identifier TEXT NOT NULL,
                    cleaned_at_ms INTEGER NOT NULL,
                    record_hash TEXT NOT NULL,
                    PRIMARY KEY(provider, mode, credential_provider, credential_identifier)
                );
                """
            )
            cleanup_columns = {
                row["name"]
                for row in db.execute("PRAGMA table_info(provider_credential_cleanup)")
            }
            if "cleanup_hash" not in cleanup_columns:
                # Pre-release databases may contain the earlier five-column queue.
                # Those rows deliberately remain unhashed and therefore fail closed;
                # silently blessing an unauthenticated deletion request would be unsafe.
                db.execute(
                    "ALTER TABLE provider_credential_cleanup "
                    "ADD COLUMN cleanup_hash TEXT"
                )
            if "state" not in cleanup_columns:
                db.execute(
                    "ALTER TABLE provider_credential_cleanup ADD COLUMN state TEXT"
                )

    def __repr__(self):
        return "<ProviderConnections api_modes=2 secrets=masked>"

    def bind_catalog(self, catalog):
        """Attach the product catalog after construction; this performs no I/O."""
        self._catalog = catalog
        bind_authority = getattr(catalog, "bind_connection_authority", None)
        if callable(bind_authority):
            bind_authority(self.binding_is_current)
        bind_resolver = getattr(catalog, "bind_api_source_resolver", None)
        if callable(bind_resolver):
            bind_resolver(self.resolve_api_source)

    def reconcile_catalog(self):
        """Best-effort rebuild of the derived API catalog source cache."""
        for provider, mode in _CONNECTIONS:
            self._publish_current_source(provider, mode)

    def _now(self):
        value = self._clock_ms()
        if type(value) is not int or not 0 <= value <= 9_007_199_254_740_991:
            raise ValueError("Invalid provider connection clock")
        return value

    @staticmethod
    def _record_payload(
        provider,
        mode,
        version,
        state,
        credential_provider,
        credential_identifier,
        configuration,
        created_at_ms,
    ):
        return {
            "schema_version": _RECORD_VERSION,
            "provider": provider,
            "mode": mode,
            "version": version,
            "state": state,
            "credential_provider": credential_provider,
            "credential_identifier": credential_identifier,
            "configuration": configuration,
            "created_at_ms": created_at_ms,
        }

    @classmethod
    def _parse_row(cls, row, provider, mode):
        if row is None:
            return None
        try:
            if row["provider"] != provider or row["mode"] != mode:
                raise ValueError
            _identity(provider, mode)
            version = row["version"]
            created_at_ms = row["created_at_ms"]
            if (type(version) is not int or version < 1
                    or type(created_at_ms) is not int or created_at_ms < 0):
                raise ValueError
            configuration = json.loads(row["configuration"])
            if (type(configuration) is not dict
                    or set(configuration) != {
                        "workspace_id", "project_id", "organization_id"
                    }
                    or configuration != _configuration(provider, **configuration)):
                raise ValueError
            state = row["state"]
            credential_provider = row["credential_provider"]
            credential_identifier = row["credential_identifier"]
            if state == "configured":
                ref = CredentialRef(credential_provider, credential_identifier)
                if credential_provider != _CONNECTIONS[(provider, mode)]:
                    raise ValueError
            elif state == "not_configured":
                if credential_provider is not None or credential_identifier is not None:
                    raise ValueError
                ref = None
            else:
                raise ValueError
            payload = cls._record_payload(
                provider,
                mode,
                version,
                state,
                credential_provider,
                credential_identifier,
                configuration,
                created_at_ms,
            )
            if (type(row["record_hash"]) is not str
                    or not hmac.compare_digest(row["record_hash"], _digest(payload))):
                raise ValueError
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptProviderConnection(
                "Stored provider connection failed its integrity check"
            ) from exc
        return {**payload, "credential_ref": ref}

    def _latest(self, db, provider, mode):
        head = db.execute(
            "SELECT version,record_hash FROM provider_connection_heads "
            "WHERE provider=? AND mode=?",
            (provider, mode),
        ).fetchone()
        latest = db.execute(
            "SELECT version,record_hash FROM provider_connections "
            "WHERE provider=? AND mode=? ORDER BY version DESC LIMIT 1",
            (provider, mode),
        ).fetchone()
        if head is None and latest is None:
            return None
        if (head is None or latest is None
                or head["version"] != latest["version"]
                or not hmac.compare_digest(head["record_hash"], latest["record_hash"])):
            raise CorruptProviderConnection(
                "Provider connection head failed its integrity check"
            )
        row = db.execute(
            "SELECT * FROM provider_connections WHERE provider=? AND mode=? "
            "AND version=?",
            (provider, mode, head["version"]),
        ).fetchone()
        return self._parse_row(row, provider, mode)

    @staticmethod
    def _insert(db, record):
        payload = {
            key: value for key, value in record.items() if key != "credential_ref"
        }
        record_hash = _digest(payload)
        db.execute(
            "INSERT INTO provider_connections "
            "(provider,mode,version,state,credential_provider,"
            "credential_identifier,configuration,created_at_ms,record_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                payload["provider"],
                payload["mode"],
                payload["version"],
                payload["state"],
                payload["credential_provider"],
                payload["credential_identifier"],
                _canonical(payload["configuration"]),
                payload["created_at_ms"],
                record_hash,
            ),
        )
        db.execute(
            "INSERT INTO provider_connection_heads VALUES (?,?,?,?) "
            "ON CONFLICT(provider,mode) DO UPDATE SET "
            "version=excluded.version,record_hash=excluded.record_hash",
            (
                payload["provider"],
                payload["mode"],
                payload["version"],
                record_hash,
            ),
        )

    @staticmethod
    def _allocation_payload(
        provider,
        mode,
        sequence,
        ref,
        expected_version,
        previous_connection_hash,
        created_at_ms,
        previous_hash,
    ):
        return {
            "schema_version": _RECORD_VERSION,
            "provider": provider,
            "mode": mode,
            "sequence": sequence,
            "credential_provider": ref.provider,
            "credential_identifier": ref.identifier,
            "expected_version": expected_version,
            "previous_connection_hash": previous_connection_hash,
            "created_at_ms": created_at_ms,
            "previous_hash": previous_hash,
        }

    @classmethod
    def _parse_allocation(cls, db, row, provider, mode, previous_hash):
        try:
            if row["provider"] != provider or row["mode"] != mode:
                raise ValueError
            sequence = row["sequence"]
            expected_version = row["expected_version"]
            created_at_ms = row["created_at_ms"]
            if (type(sequence) is not int or sequence < 1
                    or type(expected_version) is not int or expected_version < 0
                    or type(created_at_ms) is not int or created_at_ms < 0
                    or row["previous_hash"] != previous_hash):
                raise ValueError
            ref = CredentialRef(
                row["credential_provider"], row["credential_identifier"]
            )
            if ref.provider != _identity(provider, mode):
                raise ValueError
            previous_connection_hash = row["previous_connection_hash"]
            if expected_version == 0:
                if previous_connection_hash is not None:
                    raise ValueError
            else:
                previous_row = db.execute(
                    "SELECT * FROM provider_connections WHERE provider=? AND mode=? "
                    "AND version=?",
                    (provider, mode, expected_version),
                ).fetchone()
                cls._parse_row(previous_row, provider, mode)
                if (previous_row is None
                        or type(previous_connection_hash) is not str
                        or not hmac.compare_digest(
                            previous_row["record_hash"], previous_connection_hash
                        )):
                    raise ValueError
            payload = cls._allocation_payload(
                provider,
                mode,
                sequence,
                ref,
                expected_version,
                previous_connection_hash,
                created_at_ms,
                previous_hash,
            )
            if (type(row["record_hash"]) is not str
                    or not hmac.compare_digest(row["record_hash"], _digest(payload))):
                raise ValueError
        except (
            CorruptProviderConnection,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise CorruptProviderConnection(
                "Stored credential allocation failed its integrity check"
            ) from exc
        return {**payload, "credential_ref": ref, "record_hash": row["record_hash"]}

    @classmethod
    def _allocations(cls, db, provider, mode):
        head = db.execute(
            "SELECT sequence,record_hash FROM provider_credential_allocation_heads "
            "WHERE provider=? AND mode=?",
            (provider, mode),
        ).fetchone()
        rows = list(
            db.execute(
                "SELECT * FROM provider_credential_allocations "
                "WHERE provider=? AND mode=? ORDER BY sequence",
                (provider, mode),
            )
        )
        if head is None and not rows:
            return []
        if (head is None or not rows or head["sequence"] != len(rows)
                or [row["sequence"] for row in rows]
                != list(range(1, len(rows) + 1))
                or not hmac.compare_digest(head["record_hash"], rows[-1]["record_hash"])):
            raise CorruptProviderConnection(
                "Credential allocation head failed its integrity check"
            )
        parsed = []
        previous_hash = None
        for row in rows:
            allocation = cls._parse_allocation(
                db, row, provider, mode, previous_hash
            )
            parsed.append(allocation)
            previous_hash = allocation["record_hash"]
        return parsed

    def _insert_allocation(self, db, provider, mode, ref, expected_version):
        allocations = self._allocations(db, provider, mode)
        sequence = len(allocations) + 1
        previous_hash = None if not allocations else allocations[-1]["record_hash"]
        connection_head = db.execute(
            "SELECT version,record_hash FROM provider_connection_heads "
            "WHERE provider=? AND mode=?",
            (provider, mode),
        ).fetchone()
        if expected_version == 0:
            if connection_head is not None:
                raise ProviderConnectionConflict(
                    "Provider connection changed before credential allocation"
                )
            previous_connection_hash = None
        else:
            if connection_head is None or connection_head["version"] != expected_version:
                raise ProviderConnectionConflict(
                    "Provider connection changed before credential allocation"
                )
            previous_connection_hash = connection_head["record_hash"]
        payload = self._allocation_payload(
            provider,
            mode,
            sequence,
            ref,
            expected_version,
            previous_connection_hash,
            self._now(),
            previous_hash,
        )
        record_hash = _digest(payload)
        db.execute(
            "INSERT INTO provider_credential_allocations VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                provider,
                mode,
                sequence,
                ref.provider,
                ref.identifier,
                expected_version,
                previous_connection_hash,
                payload["created_at_ms"],
                previous_hash,
                record_hash,
            ),
        )
        db.execute(
            "INSERT INTO provider_credential_allocation_heads VALUES (?,?,?,?) "
            "ON CONFLICT(provider,mode) DO UPDATE SET "
            "sequence=excluded.sequence,record_hash=excluded.record_hash",
            (provider, mode, sequence, record_hash),
        )
        observed = self._allocations(db, provider, mode)
        if (not observed or observed[-1]["credential_ref"] != ref
                or observed[-1]["record_hash"] != record_hash):
            raise CorruptProviderConnection(
                "Credential allocation changed before commit"
            )
        self._audit_all(db)
        pending_orphans = self._pending_orphans(db, provider, mode)
        if ref not in {item["credential_ref"] for item in pending_orphans}:
            raise CorruptProviderConnection(
                "New credential allocation is not recoverable before commit"
            )
        return observed[-1]

    @staticmethod
    def _orphan_cleanup_payload(provider, mode, ref, cleaned_at_ms):
        return {
            "schema_version": _RECORD_VERSION,
            "provider": provider,
            "mode": mode,
            "credential_provider": ref.provider,
            "credential_identifier": ref.identifier,
            "cleaned_at_ms": cleaned_at_ms,
        }

    @classmethod
    def _orphan_tombstones(cls, db, provider, mode, allocations):
        by_ref = {item["credential_ref"] for item in allocations}
        result = {}
        rows = db.execute(
            "SELECT * FROM provider_orphan_cleanup WHERE provider=? AND mode=?",
            (provider, mode),
        )
        try:
            for row in rows:
                ref = CredentialRef(
                    row["credential_provider"], row["credential_identifier"]
                )
                cleaned_at_ms = row["cleaned_at_ms"]
                if (ref not in by_ref or type(cleaned_at_ms) is not int
                        or cleaned_at_ms < 0):
                    raise ValueError
                payload = cls._orphan_cleanup_payload(
                    provider, mode, ref, cleaned_at_ms
                )
                if (type(row["record_hash"]) is not str
                        or not hmac.compare_digest(
                            row["record_hash"], _digest(payload)
                        )):
                    raise ValueError
                result[ref] = {**payload, "record_hash": row["record_hash"]}
        except (TypeError, ValueError) as exc:
            raise CorruptProviderConnection(
                "Stored orphan cleanup failed its integrity check"
            ) from exc
        return result

    def _pending_orphans(self, db, provider, mode):
        allocations = self._allocations(db, provider, mode)
        tombstones = self._orphan_tombstones(
            db, provider, mode, allocations
        )
        connection_refs = {
            parsed["credential_ref"]
            for row in db.execute(
                "SELECT * FROM provider_connections WHERE provider=? AND mode=?",
                (provider, mode),
            )
            if (parsed := self._parse_row(row, provider, mode))["state"]
            == "configured"
        }
        allocation_refs = {item["credential_ref"] for item in allocations}
        if not connection_refs.issubset(allocation_refs):
            raise CorruptProviderConnection(
                "Provider connection has no credential allocation provenance"
            )
        return [
            item for item in allocations
            if item["credential_ref"] not in connection_refs
            and item["credential_ref"] not in tombstones
        ]

    def _audit_all(self, db):
        """Authenticate every provider projection inside a mutation transaction."""
        for current_provider, current_mode in _CONNECTIONS:
            self._latest(db, current_provider, current_mode)
            self._pending(db, current_provider, current_mode)
            self._pending_orphans(db, current_provider, current_mode)

    def _mark_orphan_cleaned(self, db, provider, mode, ref):
        payload = self._orphan_cleanup_payload(
            provider, mode, ref, self._now()
        )
        record_hash = _digest(payload)
        db.execute(
            "INSERT OR IGNORE INTO provider_orphan_cleanup VALUES (?,?,?,?,?,?)",
            (
                provider,
                mode,
                ref.provider,
                ref.identifier,
                payload["cleaned_at_ms"],
                record_hash,
            ),
        )
        tombstones = self._orphan_tombstones(
            db, provider, mode, self._allocations(db, provider, mode)
        )
        if ref not in tombstones or tombstones[ref]["record_hash"] != record_hash:
            raise CorruptProviderConnection(
                "Orphan cleanup completion changed before commit"
            )

    def _retire_orphan(self, provider, mode, pending):
        ref = pending["credential_ref"]
        with self._lock, self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._audit_all(db)
            current_pending = self._pending_orphans(db, provider, mode)
            if pending not in current_pending:
                return True
            for current_provider, current_mode in _CONNECTIONS:
                current = self._latest(db, current_provider, current_mode)
                if (current is not None
                        and current["state"] == "configured"
                        and current["credential_ref"] == ref):
                    raise CorruptProviderConnection(
                        "A current provider credential cannot be orphaned"
                    )
            try:
                self._vault.delete(ref)
            except CredentialNotFound:
                pass
            except CredentialError:
                return False
            self._mark_orphan_cleaned(db, provider, mode, ref)
            self._audit_all(db)
            if ref in {
                item["credential_ref"]
                for item in self._pending_orphans(db, provider, mode)
            }:
                raise CorruptProviderConnection(
                    "Orphan cleanup completion changed before commit"
                )
        return True

    def _retry_orphans(self, provider, mode):
        if self._vault is None:
            return
        with self._lock, self.store._connection() as db:
            pending = self._pending_orphans(db, provider, mode)
        for item in pending:
            self._retire_orphan(provider, mode, item)

    def _assert_expected_version(self, provider, mode, expected_version):
        """CAS preflight with no vault, catalog, event, or durable side effect."""
        with self._lock, self.store._connection() as db:
            self._audit_all(db)
            current = self._latest(db, provider, mode)
            current_version = 0 if current is None else current["version"]
            if current_version != expected_version:
                raise ProviderConnectionConflict(
                    "Provider connection changed after it was loaded"
                )

    @staticmethod
    def _cleanup_payload(
        provider,
        mode,
        credential_provider,
        credential_identifier,
        retired_at_version,
        state,
    ):
        return {
            "schema_version": _RECORD_VERSION,
            "provider": provider,
            "mode": mode,
            "credential_provider": credential_provider,
            "credential_identifier": credential_identifier,
            "retired_at_version": retired_at_version,
            "state": state,
        }

    @classmethod
    def _parse_cleanup(cls, db, row, provider, mode):
        """Authenticate one destructive intent against its exact history edge."""
        try:
            if row is None or row["provider"] != provider or row["mode"] != mode:
                raise ValueError
            credential_provider = row["credential_provider"]
            credential_identifier = row["credential_identifier"]
            retired_at_version = row["retired_at_version"]
            state = row["state"]
            if (credential_provider != _identity(provider, mode)
                    or type(retired_at_version) is not int
                    or retired_at_version < 2
                    or state not in {"pending", "retired"}):
                raise ValueError
            ref = CredentialRef(credential_provider, credential_identifier)
            payload = cls._cleanup_payload(
                provider,
                mode,
                credential_provider,
                credential_identifier,
                retired_at_version,
                state,
            )
            if (type(row["cleanup_hash"]) is not str
                    or not hmac.compare_digest(row["cleanup_hash"], _digest(payload))):
                raise ValueError

            predecessor_row = db.execute(
                "SELECT * FROM provider_connections WHERE provider=? AND mode=? "
                "AND version=?",
                (provider, mode, retired_at_version - 1),
            ).fetchone()
            successor_row = db.execute(
                "SELECT * FROM provider_connections WHERE provider=? AND mode=? "
                "AND version=?",
                (provider, mode, retired_at_version),
            ).fetchone()
            predecessor = cls._parse_row(predecessor_row, provider, mode)
            successor = cls._parse_row(successor_row, provider, mode)
            if (predecessor is None or successor is None
                    or predecessor["state"] != "configured"
                    or predecessor["credential_ref"] != ref
                    or successor["credential_ref"] == ref):
                raise ValueError
        except (
            CorruptProviderConnection,
            KeyError,
            TypeError,
            ValueError,
        ) as exc:
            raise CorruptProviderConnection(
                "Stored credential cleanup intent failed its integrity check"
            ) from exc
        return {**payload, "credential_ref": ref, "cleanup_hash": row["cleanup_hash"]}

    @classmethod
    def _insert_cleanup(cls, db, provider, mode, ref, retired_at_version):
        payload = cls._cleanup_payload(
            provider,
            mode,
            ref.provider,
            ref.identifier,
            retired_at_version,
            "pending",
        )
        cleanup_hash = _digest(payload)
        db.execute(
            "INSERT OR IGNORE INTO provider_credential_cleanup "
            "(provider,mode,credential_provider,credential_identifier,"
            "retired_at_version,state,cleanup_hash) VALUES (?,?,?,?,?,?,?)",
            (
                provider,
                mode,
                ref.provider,
                ref.identifier,
                retired_at_version,
                "pending",
                cleanup_hash,
            ),
        )
        row = db.execute(
            "SELECT * FROM provider_credential_cleanup WHERE provider=? AND mode=? "
            "AND credential_provider=? AND credential_identifier=?",
            (provider, mode, ref.provider, ref.identifier),
        ).fetchone()
        parsed = cls._parse_cleanup(db, row, provider, mode)
        if parsed["cleanup_hash"] != cleanup_hash:
            raise CorruptProviderConnection(
                "Credential cleanup intent changed while it was being saved"
            )

    def _pending(self, db, provider, mode):
        records = list(
            db.execute(
                "SELECT * FROM provider_connections WHERE provider=? AND mode=? "
                "ORDER BY version",
                (provider, mode),
            )
        )
        latest = self._latest(db, provider, mode)
        if latest is None:
            if records:
                raise CorruptProviderConnection(
                    "Provider connection history has no current head"
                )
            parsed_records = []
        else:
            if (len(records) != latest["version"]
                    or [row["version"] for row in records]
                    != list(range(1, latest["version"] + 1))):
                raise CorruptProviderConnection(
                    "Provider connection history is incomplete"
                )
            parsed_records = [
                self._parse_row(row, provider, mode) for row in records
            ]
        expected = {
            (
                before["credential_ref"].provider,
                before["credential_ref"].identifier,
                after["version"],
            )
            for before, after in pairwise(parsed_records)
            if (before["state"] == "configured"
                and before["credential_ref"] != after["credential_ref"])
        }
        rows = list(
            db.execute(
                "SELECT * FROM provider_credential_cleanup "
                "WHERE provider=? AND mode=? ORDER BY retired_at_version, rowid",
                (provider, mode),
            )
        )
        parsed = [self._parse_cleanup(db, row, provider, mode) for row in rows]
        observed = {
            (
                row["credential_ref"].provider,
                row["credential_ref"].identifier,
                row["retired_at_version"],
            )
            for row in parsed
        }
        if observed != expected or len(parsed) != len(expected):
            raise CorruptProviderConnection(
                "Provider credential retirement history is incomplete"
            )
        return [row for row in parsed if row["state"] == "pending"]

    def _public(self, db, provider, mode, record):
        pending = bool(
            self._pending(db, provider, mode)
            or self._pending_orphans(db, provider, mode)
        )
        if record is None:
            version, connection_state = 0, "not_configured"
        else:
            version, connection_state = record["version"], record["state"]
        observed = self._credential_states.get((provider, mode))
        if observed is not None and observed[1] == version:
            state = observed[0]
        else:
            if observed is not None:
                self._credential_states.pop((provider, mode), None)
            state = connection_state
        if self._vault is None:
            state = "blocked"
        return {
            "connection_id": f"{provider}:api",
            "provider": provider,
            "mode": mode,
            "auth_mode": "api_key",
            "state": state,
            "key_present": connection_state == "configured",
            "checked_at": None,
            "catalog_ref": None,
            "billing_state": "api_usage",
            "version": version,
            "cleanup_pending": pending,
        }

    def _remember_credential_state(self, provider, mode, state):
        """Remember a vault observation only for the durable version it saw."""
        with self._lock, self.store._connection() as db:
            self._audit_all(db)
            record = self._latest(db, provider, mode)
            version = 0 if record is None else record["version"]
            self._credential_states[(provider, mode)] = (state, version)

    def get(self, provider, mode):
        _identity(provider, mode)
        with self._lock, self.store._connection() as db:
            record = self._latest(db, provider, mode)
            result = self._public(db, provider, mode, record)
            should_reconcile = (provider, mode) in self._catalog_sync_pending
        if should_reconcile:
            self._publish_current_source(provider, mode)
        return result

    def _binding(self, provider, mode, record):
        if record is None or record["state"] != "configured":
            return None
        ref = record["credential_ref"]
        config = record["configuration"]
        if provider == "claude":
            return ClaudeBinding(ref, workspace_id=config["workspace_id"])
        return CodexAPIBinding(
            ref,
            project_id=config["project_id"],
            organization_id=config["organization_id"],
        )

    def api_sources(self):
        """Return current adapter/binding pairs without opening the vault."""
        result = {}
        if not self._adapters:
            return result
        with self._lock, self.store._connection() as db:
            for provider, mode in _CONNECTIONS:
                record = self._latest(db, provider, mode)
                self._pending(db, provider, mode)
                self._pending_orphans(db, provider, mode)
                binding = self._binding(provider, mode, record)
                if binding is not None:
                    result[(provider, mode)] = (
                        self._adapters[(provider, mode)],
                        binding,
                    )
        return result

    def resolve_api_source(self, provider, mode, *, db=None):
        """Resolve the current durable binding using this process's safe adapter."""
        try:
            _identity(provider, mode)

            def evaluate(connection):
                self._audit_all(connection)
                record = self._latest(connection, provider, mode)
                binding = self._binding(provider, mode, record)
                if binding is None or not self._adapters:
                    return None, None
                return self._adapters[(provider, mode)], binding

            if db is not None:
                return evaluate(db)
            # This is a read-only resolver used while the catalog may already
            # hold its own refresh lock. A SQLite snapshot is sufficient because
            # every eventual catalog write repeats the authority check in its
            # write transaction; taking the provider mutation lock here would
            # invert provider->catalog and catalog->provider lock order.
            with self.store._connection() as connection:
                connection.execute("BEGIN")
                return evaluate(connection)
        except (CorruptProviderConnection, KeyError, TypeError, ValueError):
            return None, None

    def binding_is_current(self, provider, mode, binding_id, *, db=None):
        """Fail-closed durable authority callback used by the model catalog."""
        def evaluate(connection):
            self._audit_all(connection)
            record = self._latest(connection, provider, mode)
            binding = self._binding(provider, mode, record)
            if binding_id is None:
                return binding is None
            return binding is not None and hmac.compare_digest(
                binding.binding_id, binding_id
            )

        try:
            _identity(provider, mode)
            if binding_id is not None and type(binding_id) is not str:
                return False
            if db is not None:
                return evaluate(db)
            with self._lock, self.store._connection() as connection:
                return evaluate(connection)
        except (CorruptProviderConnection, TypeError, ValueError):
            return False

    def _publish_source(self, provider, mode, record):
        replace_source = getattr(self._catalog, "replace_api_source", None)
        if not callable(replace_source):
            return
        binding = self._binding(provider, mode, record)
        source = None if binding is None else (
            self._adapters[(provider, mode)], binding
        )
        replace_source(provider, mode, source)

    def _publish_current_source(self, provider, mode):
        """Publish only the authenticated latest pointer while mutations are serialized."""
        with self._lock:
            # Close the read connection before catalog publication.  The catalog
            # persists its own source generation, so keeping the SQLite reader
            # open here can otherwise turn a harmless publication into a lock
            # inversion with model-selection freeze.
            with self.store._connection() as db:
                current = self._latest(db, provider, mode)
                self._pending(db, provider, mode)
                self._pending_orphans(db, provider, mode)
            try:
                self._publish_source(provider, mode, current)
            except Exception:  # noqa: BLE001 - derived cache repair is best-effort
                # The provider ledger is authoritative and has already committed.
                # Catalog state is a derived cache: retain a local repair marker
                # and never turn a successful key rotation into an ambiguous error.
                self._catalog_sync_pending.add((provider, mode))
            else:
                self._catalog_sync_pending.discard((provider, mode))
            return current

    def _retire(self, provider, mode, pending):
        ref = pending["credential_ref"]
        with self._lock, self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._audit_all(db)
            row = db.execute(
                "SELECT * FROM provider_credential_cleanup WHERE provider=? AND mode=? "
                "AND credential_provider=? AND credential_identifier=?",
                (provider, mode, ref.provider, ref.identifier),
            ).fetchone()
            if row is None:
                raise CorruptProviderConnection(
                    "Credential cleanup intent disappeared before deletion"
                )
            verified = self._parse_cleanup(db, row, provider, mode)
            if (verified["state"] == "retired"
                    and verified["credential_ref"] == ref
                    and verified["retired_at_version"]
                    == pending["retired_at_version"]):
                return True
            if verified != pending:
                raise CorruptProviderConnection(
                    "Credential cleanup intent changed before deletion"
                )
            for current_provider, current_mode in _CONNECTIONS:
                current = self._latest(db, current_provider, current_mode)
                if (current is not None
                        and current["state"] == "configured"
                        and current["credential_ref"] == ref):
                    raise CorruptProviderConnection(
                        "A current provider credential cannot be retired"
                    )
            try:
                self._vault.delete(ref)
            except CredentialNotFound:
                pass
            except CredentialError:
                return False
            retired_payload = self._cleanup_payload(
                provider,
                mode,
                ref.provider,
                ref.identifier,
                pending["retired_at_version"],
                "retired",
            )
            retired_hash = _digest(retired_payload)
            updated = db.execute(
                "UPDATE provider_credential_cleanup SET state='retired',cleanup_hash=? "
                "WHERE provider=? AND mode=? "
                "AND credential_provider=? AND credential_identifier=? "
                "AND retired_at_version=? AND state='pending' AND cleanup_hash=?",
                (
                    retired_hash,
                    provider,
                    mode,
                    ref.provider,
                    ref.identifier,
                    pending["retired_at_version"],
                    pending["cleanup_hash"],
                ),
            )
            if updated.rowcount != 1:
                raise CorruptProviderConnection(
                    "Credential cleanup intent changed during deletion"
                )
            retired_row = db.execute(
                "SELECT * FROM provider_credential_cleanup WHERE provider=? AND mode=? "
                "AND credential_provider=? AND credential_identifier=?",
                (provider, mode, ref.provider, ref.identifier),
            ).fetchone()
            retired = self._parse_cleanup(db, retired_row, provider, mode)
            if retired["state"] != "retired" or retired["cleanup_hash"] != retired_hash:
                raise CorruptProviderConnection(
                    "Credential cleanup completion changed before commit"
                )
            self._audit_all(db)
        return True

    def _retry_cleanup(self, provider, mode):
        if self._vault is None:
            return
        with self._lock, self.store._connection() as db:
            pending = self._pending(db, provider, mode)
        for item in pending:
            self._retire(provider, mode, item)

    def configure(
        self,
        provider,
        mode,
        expected_version,
        key,
        *,
        workspace_id,
        project_id,
        organization_id,
    ):
        # This frame is part of the traceback when validation or Keychain setup
        # fails.  Keep the whole operation inside the scrub boundary so crash
        # diagnostics cannot retain the original immutable string in ``key``.
        try:
            credential_provider = _identity(provider, mode)
            expected_version = _expected_version(expected_version)
            configuration = _configuration(
                provider,
                workspace_id=workspace_id,
                project_id=project_id,
                organization_id=organization_id,
            )
            validate_credential_secret(key)
            if self._vault is None:
                raise ProviderCredentialUnavailable(
                    "Secure credential storage is unavailable"
                )
            self._assert_expected_version(provider, mode, expected_version)
            new_ref = CredentialRef(credential_provider, uuid4().hex)
            allocation = None
            old_ref = record = None
            with self._lock:
                # The opaque reference is durably chained before Keychain receives
                # secret material. A crash or double failure therefore leaves an
                # exact, recoverable orphan instead of an undiscoverable key.
                with self.store._connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    self._audit_all(db)
                    current = self._latest(db, provider, mode)
                    current_version = 0 if current is None else current["version"]
                    if current_version != expected_version:
                        raise ProviderConnectionConflict(
                            "Provider connection changed after it was loaded"
                        )
                    allocation = self._insert_allocation(
                        db, provider, mode, new_ref, expected_version
                    )
                try:
                    self._vault.store_at(new_ref, key)
                except CredentialError:
                    # Keychain failures can be outcome-ambiguous. Deleting the
                    # preallocated ref is safe; if deletion also fails, the durable
                    # allocation remains visible and retryable.
                    self._retire_orphan(provider, mode, allocation)
                    raise

                try:
                    with self.store._connection() as db:
                        db.execute("BEGIN IMMEDIATE")
                        self._audit_all(db)
                        current = self._latest(db, provider, mode)
                        current_version = 0 if current is None else current["version"]
                        if current_version != expected_version:
                            raise ProviderConnectionConflict(
                                "Provider connection changed after credential staging"
                            )
                        if allocation not in self._allocations(db, provider, mode):
                            raise CorruptProviderConnection(
                                "Credential allocation changed before connection save"
                            )
                        old_ref = (
                            None if current is None else current["credential_ref"]
                        )
                        record = self._record_payload(
                            provider,
                            mode,
                            current_version + 1,
                            "configured",
                            new_ref.provider,
                            new_ref.identifier,
                            configuration,
                            self._now(),
                        )
                        record["credential_ref"] = new_ref
                        self._insert(db, record)
                        if self._latest(db, provider, mode) != record:
                            raise CorruptProviderConnection(
                                "Provider connection changed while it was being saved"
                            )
                        if old_ref is not None:
                            self._insert_cleanup(
                                db,
                                provider,
                                mode,
                                old_ref,
                                record["version"],
                            )
                        Store._event(db, "connection.changed", None, {
                            "provider": provider,
                            "auth_mode": mode,
                            "key_present": True,
                            "ready": False,
                        })
                        if self._latest(db, provider, mode) != record:
                            raise CorruptProviderConnection(
                                "Provider connection changed before commit"
                            )
                        # Re-authenticate every destructive and allocation
                        # projection after all INSERT/UPDATE triggers have run.
                        # A trigger-added cleanup edge must roll this transaction
                        # back instead of poisoning the next read after commit.
                        self._audit_all(db)
                        if new_ref in {
                            item["credential_ref"]
                            for item in self._pending_orphans(db, provider, mode)
                        }:
                            raise CorruptProviderConnection(
                                "Current credential was left marked as an orphan"
                            )
                except Exception:
                    self._retire_orphan(provider, mode, allocation)
                    raise
            self._publish_current_source(provider, mode)
            # Maintenance is deliberately after the successful CAS commit. A
            # stale request must never delete an orphan created by another run.
            self._retry_orphans(provider, mode)
            if old_ref is not None:
                self._retry_cleanup(provider, mode)
            self._credential_states.pop((provider, mode), None)
            return self.get(provider, mode)
        except CredentialError as error:
            self._remember_credential_state(provider, mode, error.state)
            raise
        finally:
            key = ""

    def delete(self, provider, mode, expected_version):
        try:
            return self._delete(provider, mode, expected_version)
        except CredentialError as error:
            self._remember_credential_state(provider, mode, error.state)
            raise

    def _delete(self, provider, mode, expected_version):
        _identity(provider, mode)
        expected_version = _expected_version(expected_version)
        if self._vault is None:
            raise ProviderCredentialUnavailable(
                "Secure credential storage is unavailable"
            )
        self._assert_expected_version(provider, mode, expected_version)
        record = None
        with self._lock, self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            self._audit_all(db)
            current = self._latest(db, provider, mode)
            current_version = 0 if current is None else current["version"]
            if current_version != expected_version:
                raise ProviderConnectionConflict(
                    "Provider connection changed after it was loaded"
                )
            if current is not None and current["state"] == "configured":
                record = self._record_payload(
                    provider,
                    mode,
                    current_version + 1,
                    "not_configured",
                    None,
                    None,
                    current["configuration"],
                    self._now(),
                )
                record["credential_ref"] = None
                self._insert(db, record)
                if self._latest(db, provider, mode) != record:
                    raise CorruptProviderConnection(
                        "Provider connection changed while it was being removed"
                    )
                ref = current["credential_ref"]
                self._insert_cleanup(
                    db,
                    provider,
                    mode,
                    ref,
                    record["version"],
                )
                Store._event(db, "connection.changed", None, {
                    "provider": provider,
                    "auth_mode": mode,
                    "key_present": False,
                    "ready": False,
                })
                if self._latest(db, provider, mode) != record:
                    raise CorruptProviderConnection(
                        "Provider connection changed before commit"
                    )
                self._audit_all(db)
            else:
                record = current
        self._publish_current_source(provider, mode)
        self._retry_orphans(provider, mode)
        self._retry_cleanup(provider, mode)
        self._credential_states.pop((provider, mode), None)
        return self.get(provider, mode)
