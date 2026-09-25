"""`updates`: the stopped-control-plane web-release update tool (operator only; T072).

This is deployment operator tooling, never an end-user product journey. It is the update
half of the T025 `DeploymentControlPort` (the owner-recovery half is
`app/operations/deployment_control.py`): the product seals an exact digest-bound request
and verifies the returned receipt, while the privileged effect (pulling the exact images
of the image-lock set and replacing the containers) stays with the Portainer/operator
surface. Nothing here downloads, installs or starts anything; it never runs a package
manager (no runtime pip/npm) and never talks to Docker.

    python -m app.operations.updates status  <common options>
    python -m app.operations.updates prepare <common> --target-manifest M --image-lock L [--ttl-seconds S]
    python -m app.operations.updates backup  <common> --backup-worker-config C
    python -m app.operations.updates cancel  <common>
    python -m app.operations.updates migrate <common> --receipt R --trust-set T [--backup-worker-config C]

    common options: --data-dir D --session-root-dir S --deployment-config C --work-dir W
                    --expected-uid U --expected-gid G

It runs only while the control plane is stopped: it holds the data directory's serving
lock through the same `_Maintenance` as the owner-recovery tool and refuses `busy` while
a server holds it.

The request (`deployment-request-v1`, kind `release_update`) binds exactly: the instance
and origin-profile digest, the target web-release manifest's SHA-256 and release id, the
service-keyed image-lock set's SHA-256 (which the manifest itself names), the target data
schema, the current recovery epoch with its session-root generation and manifest (an
update never moves the epoch: old and new authority epochs are equal), the current
release manifest (or `null` while none is recorded) and the current data-schema ledgers,
plus a fresh 32-byte nonce, the creator and the creation/expiry.

Its lifecycle is a revisioned CAS in the vault database itself (the `deployment_update_`
table family, excluded from backups as deployment private state):

    prepared → backup_verified → migrating → completed
    prepared | backup_verified → cancelled          migrating → failed

Each transition inserts revision r+1 of the request's lifecycle only while its head is
still r (a primary key, inside one `BEGIN IMMEDIATE` transaction), so a cancel and a
receipt race through the same CAS and exactly one wins.

Backup gate (no silent new-data loss). `backup` takes a backup through the backup-crypto
port (the networkless worker's `BackupCryptoClient` in a deployment), verifies its
external receipt against the ciphertext, decrypts it again through the same port and
recomputes the vault's restorable-state digest from the archived database: only a backup
whose archive has exactly the live state digest is recorded (`backup_verified`). The
migration transaction recomputes the live digest and refuses `backup_stale` when anything
was written after the backup; a deleted or altered ciphertext refuses `backup_missing`.

Missing component handshake. Every component the target manifest names must answer the
tool's code-owned handshake with the exact protocol before the gate is passed; an absent
or wrong-version component refuses (`component_unavailable`,
`component_version_mismatch`) in a safe state: nothing migrated, the lifecycle unchanged,
the refusal recorded for the guidance.

`migrate` verifies the signed `deployment-update-receipt-v1` against the stored request
and the `deployment-public-trust-set-v2` (a key holding the recovery-operator adapter:
the same stopped-control-plane deployment authority; a stage-only key never signs one),
rechecks the epoch/root/configuration, the schema, the components and the gate, journals
`migrating` with the receipt digest, and then runs ONE transaction that rechecks the gate
digest, applies the code-owned migration steps, verifies the target schema, inserts the
migration record and the unique `deployment_update_consumptions` row (receipt digest,
request id and nonce each unique), advances the release head and CASes `completed`.
A step failure rolls that transaction back and records `failed`: the data is exactly the
backed-up state. A crash anywhere leaves either the previous revision or `migrating`;
re-running `migrate` with the same receipt completes it, a different receipt is refused,
and re-running after completion is a verify-only no-op. Output is one canonical JSON line.
"""

from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys
import tempfile
import time
from contextlib import closing
from base64 import urlsafe_b64encode
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from ..domain.refs import canonical_json, parse_canonical

MANIFEST_SCHEMA = "deeptwin-web-release-manifest-v1"
IMAGE_LOCK_SCHEMA = "deeptwin-image-lock-set-v1"
REQUEST_KIND = "release_update"
RECEIPT_SCHEMA = "deployment-update-receipt-v1"
RECEIPT_DOMAIN = "deeptwin-deployment-update-receipt-v1"
STATE_DIGEST_DOMAIN = b"deeptwin-update-state-digest-v1\n"
STATES = ("prepared", "backup_verified", "migrating", "completed", "cancelled", "failed")
ACTIVE = frozenset({"prepared", "backup_verified", "migrating"})
TRANSITIONS = {
    "prepared": frozenset({"backup_verified", "cancelled"}),
    "backup_verified": frozenset({"backup_verified", "migrating", "cancelled"}),
    "migrating": frozenset({"completed", "failed"}),
}
DEFAULT_TTL_SECONDS = 86400
BACKUP_COMPONENT = "backup-crypto"
UNRECORDED_RELEASE = "deeptwin-control-v1"
RECEIPT_FIELDS = (
    "schema", "domain", "request_id", "request_digest", "request_nonce", "kind", "instance_id",
    "origin_profile_digest", "deployment_profile_id", "operator_adapter", "operator_version",
    "recovery_epoch", "previous_release_manifest_sha256", "release_manifest_sha256",
    "image_lock_set_sha256", "outcome", "completed_at", "key_id", "trust_set_digest", "trust_class",
    "signature",
)
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_NAME = re.compile(r"[a-z][a-z0-9-]{0,63}\Z")
_FAMILY = re.compile(r"[a-z][a-z_]{0,47}\Z")
_RELEASE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,63}\Z")
_IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PROTOCOL = re.compile(r"[a-z0-9][a-z0-9.-]{0,95}\Z")

# the lifecycle store: one governed table family in the vault database
FAMILY_DDL = (
    "CREATE TABLE deployment_update_migrations (version INTEGER PRIMARY KEY CHECK(version=1), "
    "checksum TEXT NOT NULL)",
    "CREATE TABLE deployment_update_requests (request_id TEXT PRIMARY KEY, "
    "request_digest TEXT NOT NULL UNIQUE, request_nonce TEXT NOT NULL UNIQUE, "
    "request_sha256 TEXT NOT NULL UNIQUE, request BLOB NOT NULL, target_release_id TEXT NOT NULL, "
    "target_manifest_sha256 TEXT NOT NULL, target_image_lock_sha256 TEXT NOT NULL, "
    "recovery_epoch INTEGER NOT NULL, created_at TEXT NOT NULL, expires_at TEXT NOT NULL)",
    "CREATE TABLE deployment_update_lifecycle (request_id TEXT NOT NULL "
    "REFERENCES deployment_update_requests(request_id), revision INTEGER NOT NULL CHECK(revision>=1), "
    "state TEXT NOT NULL CHECK(state IN ('prepared','backup_verified','migrating','completed',"
    "'cancelled','failed')), backup_id TEXT, backup_ciphertext_sha256 TEXT, backup_state_digest TEXT, "
    "receipt_sha256 TEXT, failure_code TEXT, recorded_at TEXT NOT NULL, PRIMARY KEY(request_id,revision))",
    "CREATE TABLE deployment_update_consumptions (receipt_sha256 TEXT PRIMARY KEY, "
    "request_id TEXT NOT NULL UNIQUE REFERENCES deployment_update_requests(request_id), "
    "request_nonce TEXT NOT NULL UNIQUE, migration_id TEXT NOT NULL UNIQUE, "
    "trust_set_sha256 TEXT NOT NULL, consumed_at TEXT NOT NULL)",
    "CREATE TABLE deployment_update_applied (migration_id TEXT PRIMARY KEY, "
    "request_id TEXT NOT NULL UNIQUE REFERENCES deployment_update_requests(request_id), "
    "from_schema_sha256 TEXT NOT NULL, to_schema_sha256 TEXT NOT NULL, steps TEXT NOT NULL, "
    "state_digest_before TEXT NOT NULL, state_digest_after TEXT NOT NULL, applied_at TEXT NOT NULL)",
    "CREATE TABLE deployment_update_releases (revision INTEGER PRIMARY KEY CHECK(revision>=1), "
    "release_id TEXT NOT NULL, manifest_sha256 TEXT NOT NULL, image_lock_sha256 TEXT NOT NULL, "
    "request_id TEXT NOT NULL UNIQUE REFERENCES deployment_update_requests(request_id), "
    "installed_at TEXT NOT NULL)",
    "CREATE TABLE deployment_update_refusals (request_id TEXT NOT NULL "
    "REFERENCES deployment_update_requests(request_id), attempt INTEGER NOT NULL CHECK(attempt>=1), "
    "code TEXT NOT NULL, detail TEXT, recorded_at TEXT NOT NULL, PRIMARY KEY(request_id,attempt))",
)
FAMILY_SHA256 = sha256("\n".join(FAMILY_DDL).encode("utf-8")).hexdigest()


class UpdateError(Exception):
    """A closed refusal; `code` names it and carries no secret or filesystem detail."""

    def __init__(self, code, detail=None):
        super().__init__(code)
        self.code = code
        self.detail = detail


class MigrationStepFailure(Exception):
    """A code-owned migration step could not apply; its transaction is rolled back."""


# what a step failing on its own terms raises; anything else is treated as a crash
STEP_FAILURES = (MigrationStepFailure, sqlite3.DatabaseError, ValueError, TypeError, LookupError)


def _step(name):
    """A named point between two durable steps; tests replace it to inject a crash."""


def _sha256(data):
    return sha256(data).hexdigest()


def _b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _now_ms():
    return time.time_ns() // 1_000_000


def _stamp(milliseconds=None):
    from ..deployment.prepare_contracts import stamp

    return stamp(_now_ms() if milliseconds is None else milliseconds)


def _require(condition, code="invalid_request"):
    if not condition:
        raise UpdateError(code)


def _hex(value):
    _require(type(value) is str and _HEX.fullmatch(value) is not None)
    return value


# ---- release manifest and image-lock set --------------------------------------------------

def _canonical_object(raw, limit):
    _require(type(raw) is bytes and 1 <= len(raw) <= limit)
    try:
        value = parse_canonical(raw)
    except Exception:  # noqa: BLE001 - every decoding failure is the same refusal
        raise UpdateError("invalid_request") from None
    _require(type(value) is dict and canonical_json(value) == raw)
    return value


def _schema_rows(rows):
    _require(type(rows) is list and 1 <= len(rows) <= 64)
    for row in rows:
        _require(type(row) is list and 2 <= len(row) <= 3
                 and all(type(item) in (int, str) for item in row))
    return rows


def parse_manifest(raw: bytes) -> dict:
    """An exact `deeptwin-web-release-manifest-v1` (canonical JSON bytes)."""
    value = _canonical_object(raw, 16384)
    _require(set(value) == {"schema", "release_id", "image_lock_set_sha256", "data_schema", "components"}
             and value["schema"] == MANIFEST_SCHEMA)
    _require(type(value["release_id"]) is str and _RELEASE.fullmatch(value["release_id"]) is not None)
    _hex(value["image_lock_set_sha256"])
    schema = value["data_schema"]
    _require(type(schema) is dict and len(schema) <= 32)
    for family, rows in schema.items():
        _require(_FAMILY.fullmatch(family) is not None and family != "deployment_update")
        _schema_rows(rows)
    components = value["components"]
    _require(type(components) is list and len(components) <= 16)
    names = []
    for component in components:
        _require(type(component) is dict and set(component) == {"component_id", "protocol"}
                 and type(component["component_id"]) is str
                 and _NAME.fullmatch(component["component_id"]) is not None
                 and type(component["protocol"]) is str
                 and _PROTOCOL.fullmatch(component["protocol"]) is not None)
        names.append(component["component_id"])
    _require(names == sorted(set(names)))
    return value


def parse_image_lock(raw: bytes, *, manifest: dict) -> dict:
    """An exact service-keyed `deeptwin-image-lock-set-v1` that the manifest names."""
    value = _canonical_object(raw, 16384)
    _require(set(value) == {"schema", "release_id", "services"} and value["schema"] == IMAGE_LOCK_SCHEMA)
    _require(value["release_id"] == manifest["release_id"]
             and _sha256(raw) == manifest["image_lock_set_sha256"])
    services = value["services"]
    _require(type(services) is dict and 1 <= len(services) <= 32)
    for name, digest in services.items():
        _require(_NAME.fullmatch(name) is not None and type(digest) is str and _IMAGE.fullmatch(digest) is not None)
    return value


# ---- the vault's state and schema ------------------------------------------------------------

def _quote(name):
    return '"' + name.replace('"', '""') + '"'


def data_schema(db) -> dict:
    """Every table family's migration ledger (`<family>_migrations`), as exact rows."""
    result = {}
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' "
                              "AND name GLOB '*_migrations' ORDER BY name"):
        family = name[: -len("_migrations")]
        if family == "deployment_update":
            continue
        rows = [list(row) for row in db.execute(f"SELECT * FROM {_quote(name)}")]
        result[family] = sorted(rows, key=lambda row: canonical_json(row))
    return result


def schema_sha256(schema: dict) -> str:
    return _sha256(canonical_json(schema))


def _encode_row(row):
    return repr(tuple((type(item).__name__, item) for item in row)).encode("utf-8")


def state_digest(db) -> str:
    """The digest of everything a backup restores: every restorable table's definition
    and its rows as a multiset (a backup's VACUUM may renumber rowids). Excluded state
    (sessions, credentials, this lifecycle) never moves it; an unclassified table refuses."""
    from .backup import BackupError, classify_table

    digest = sha256(STATE_DIGEST_DOMAIN)
    names = [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    for name in names:
        try:
            if classify_table(name) is not None:
                continue
        except BackupError:
            raise UpdateError("unclassified_table", name) from None
        objects = [list(row) for row in db.execute(
            "SELECT type,name,sql FROM sqlite_master WHERE tbl_name=? AND sql IS NOT NULL "
            "ORDER BY type,name", (name,))]
        digest.update(sha256(canonical_json(["table", name, objects])).digest())
        rows = sorted(sha256(_encode_row(row)).digest() for row in db.execute(f"SELECT * FROM {_quote(name)}"))
        digest.update(len(rows).to_bytes(8, "big"))
        for row in rows:
            digest.update(row)
    return digest.hexdigest()


# ---- code-owned migration steps -------------------------------------------------------------

def _domain_v2(db):
    """The domain store's migration 2 (legacy-file CAS links) as an update step."""
    from ..domain import store

    store.DomainStore._verify_schema(db, through_version=1)
    for statement in store._MIGRATION_2_DDL:
        db.execute(statement)
    db.execute("INSERT INTO domain_migrations VALUES (2, ?)", (store.MIGRATION_2_SHA256,))
    store.DomainStore._verify_schema(db, through_version=2)


def _builtin_steps():
    from ..domain import store

    return {("domain", (2, store.MIGRATION_2_SHA256)): _domain_v2}


def plan_migration(current: dict, target: dict, steps: dict) -> list:
    """The ordered code-owned steps from the current ledgers to the target ones.

    Only the families the target manifest names are governed; each must already hold a
    prefix of the target rows, and every missing row must have its own step."""
    todo = []
    for family in sorted(target):
        have, want = current.get(family, []), target[family]
        if have == want:
            continue
        if len(have) > len(want) or want[: len(have)] != have:
            raise UpdateError("migration_unsupported", family)
        for row in want[len(have):]:
            step = steps.get((family, tuple(row)))
            if step is None:
                raise UpdateError("migration_unsupported", family)
            todo.append((family, row, step))
    return todo


# ---- the lifecycle store ---------------------------------------------------------------------

def _connect(path):
    db = sqlite3.connect(os.fspath(path), isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


class UpdateStore:
    """The `deployment_update_` family of one vault database; every write is one
    `BEGIN IMMEDIATE` transaction and every lifecycle move a revision CAS."""

    def __init__(self, data_dir):
        self.path = Path(os.path.abspath(os.fspath(data_dir))) / "intake.sqlite3"
        if not self.path.is_file() or self.path.is_symlink():
            raise UpdateError("unavailable")

    def connect(self):
        return _connect(self.path)

    # -- schema --

    @staticmethod
    def installed(db):
        return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' "
                          "AND name='deployment_update_migrations'").fetchone() is not None

    @staticmethod
    def verify(db):
        from ..domain.store import _normalize_schema_sql

        rows = {row["name"]: _normalize_schema_sql(row["sql"]) for row in db.execute(
            "SELECT name,sql FROM sqlite_master WHERE name GLOB 'deployment_update_*' AND sql IS NOT NULL")}
        expected = {re.match(r"CREATE TABLE (\w+)", statement).group(1): _normalize_schema_sql(statement)
                    for statement in FAMILY_DDL}
        ledger = [tuple(row) for row in db.execute("SELECT version,checksum FROM deployment_update_migrations")] \
            if "deployment_update_migrations" in rows else []
        if rows != expected or ledger != [(1, FAMILY_SHA256)]:
            raise UpdateError("unavailable")

    def ensure(self, db):
        if not self.installed(db):
            db.execute("BEGIN IMMEDIATE")
            try:
                if not self.installed(db):
                    for statement in FAMILY_DDL:
                        db.execute(statement)
                    db.execute("INSERT INTO deployment_update_migrations VALUES (1, ?)", (FAMILY_SHA256,))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
        self.verify(db)

    # -- reads --

    @staticmethod
    def head(db, request_id):
        row = db.execute("SELECT * FROM deployment_update_lifecycle WHERE request_id=? "
                         "ORDER BY revision DESC LIMIT 1", (request_id,)).fetchone()
        return None if row is None else dict(row)

    @staticmethod
    def request(db, request_id):
        row = db.execute("SELECT * FROM deployment_update_requests WHERE request_id=?", (request_id,)).fetchone()
        return None if row is None else dict(row)

    @classmethod
    def heads(cls, db):
        return [cls.head(db, row[0]) for row in db.execute(
            "SELECT request_id FROM deployment_update_requests ORDER BY created_at DESC, request_id")]

    @classmethod
    def active(cls, db):
        found = [head for head in cls.heads(db) if head["state"] in ACTIVE]
        if len(found) > 1:
            raise UpdateError("unavailable")
        return found[0] if found else None

    @staticmethod
    def release(db):
        row = db.execute("SELECT * FROM deployment_update_releases ORDER BY revision DESC LIMIT 1").fetchone()
        return None if row is None else dict(row)

    @staticmethod
    def refusals(db, request_id):
        return [dict(row) for row in db.execute(
            "SELECT code,detail,recorded_at,attempt FROM deployment_update_refusals WHERE request_id=? "
            "ORDER BY attempt", (request_id,))]

    # -- writes (the caller holds `BEGIN IMMEDIATE`) --

    @classmethod
    def advance_in_transaction(cls, db, request_id, *, expected_revision, state, **fields):
        head = cls.head(db, request_id)
        if head is None:
            raise UpdateError("no_pending")
        if head["revision"] != expected_revision:
            # someone else moved it first: report what it is now
            raise UpdateError(head["state"] if head["state"] in ("cancelled", "completed", "failed")
                              else "conflict")
        if state not in TRANSITIONS.get(head["state"], ()):
            raise UpdateError("conflict")
        row = {name: head[name] for name in ("backup_id", "backup_ciphertext_sha256", "backup_state_digest",
                                             "receipt_sha256", "failure_code")}
        row.update(fields)
        db.execute("INSERT INTO deployment_update_lifecycle (request_id,revision,state,backup_id,"
                   "backup_ciphertext_sha256,backup_state_digest,receipt_sha256,failure_code,recorded_at) "
                   "VALUES (?,?,?,?,?,?,?,?,?)",
                   (request_id, expected_revision + 1, state, row["backup_id"], row["backup_ciphertext_sha256"],
                    row["backup_state_digest"], row["receipt_sha256"], row["failure_code"], _stamp()))
        return cls.head(db, request_id)

    def advance(self, request_id, *, expected_revision, state, **fields):
        """One CAS in its own transaction (the cancel path and the lifecycle journal)."""
        with closing(self.connect()) as db:
            self.verify(db)
            db.execute("BEGIN IMMEDIATE")
            try:
                head = self.advance_in_transaction(db, request_id, expected_revision=expected_revision,
                                                   state=state, **fields)
                db.execute("COMMIT")
                return head
            except BaseException:
                db.execute("ROLLBACK")
                raise

    def refuse(self, request_id, code, detail=None):
        """Record a refusal for the guidance; the lifecycle itself does not move."""
        with closing(self.connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                attempt = db.execute("SELECT coalesce(max(attempt),0)+1 FROM deployment_update_refusals "
                                     "WHERE request_id=?", (request_id,)).fetchone()[0]
                db.execute("INSERT INTO deployment_update_refusals VALUES (?,?,?,?,?)",
                           (request_id, attempt, code, detail, _stamp()))
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise


# ---- the request and the receipt ------------------------------------------------------------

def make_update_request(*, profile, request_id, nonce, actor_ref, created_ms, ttl_seconds, epoch,
                        generation_id, root_manifest_sha256, current_release_manifest_sha256,
                        current_schema_sha256, manifest_sha256, manifest):
    from ..deployment.prepare_contracts import interval

    _require(type(nonce) is bytes and len(nonce) == 32 and type(epoch) is int)
    created_at, expires_at = interval(created_ms, ttl_seconds)
    value = {
        "schema": "deployment-request-v1",
        "domain": "deeptwin-deployment-request-v1",
        "request_id": request_id,
        "kind": REQUEST_KIND,
        "request_nonce": _b64(nonce),
        "instance_id": profile.instance_id,
        "origin_profile_digest": _b64(bytes.fromhex(profile.digest)),
        "effect_payload": {
            "target_release_id": manifest["release_id"],
            "target_release_manifest_sha256": manifest_sha256,
            "target_image_lock_set_sha256": manifest["image_lock_set_sha256"],
            "target_data_schema_sha256": schema_sha256(manifest["data_schema"]),
            "target_recovery_epoch": epoch,
        },
        "preconditions": {
            "current_recovery_epoch": epoch,
            "current_session_root_generation_id": generation_id,
            "current_session_root_manifest_sha256": root_manifest_sha256,
            "current_release_manifest_sha256": current_release_manifest_sha256,
            "current_data_schema_sha256": current_schema_sha256,
        },
        "created_by": actor_ref,
        "created_at": created_at,
        "expires_at": expires_at,
    }
    value["request_digest"] = _b64(sha256(canonical_json(value)).digest())
    return canonical_json(value)


def parse_update_receipt(raw: bytes) -> dict:
    from ..deployment.receipt_contracts import ReceiptWireError, _parse, _signature, _timestamp
    from ..domain.refs import uuid_string
    from ..domain.wire import WireLimits
    from ..operations.setup import parse_base64url_32

    try:
        value = _parse(raw, fields=RECEIPT_FIELDS, limits=WireLimits(
            max_bytes=8192, max_depth=4, max_items=64, max_members=32, max_string_bytes=256))
        _require(value["schema"] == RECEIPT_SCHEMA and value["domain"] == RECEIPT_DOMAIN
                 and value["kind"] == REQUEST_KIND and value["outcome"] == "applied"
                 and value["trust_class"] == "instance_operator")
        for name in ("request_id", "key_id"):
            uuid_string(value[name])
        for name in ("request_digest", "request_nonce", "origin_profile_digest", "trust_set_digest"):
            parse_base64url_32(value[name])
        for name in ("release_manifest_sha256", "image_lock_set_sha256"):
            _hex(value[name])
        if value["previous_release_manifest_sha256"] is not None:
            _hex(value["previous_release_manifest_sha256"])
        _require(type(value["recovery_epoch"]) is int and value["recovery_epoch"] >= 1)
        for name in ("instance_id", "deployment_profile_id", "operator_adapter", "operator_version"):
            _require(type(value[name]) is str)
        _signature(value["signature"])
        _timestamp(value["completed_at"])
        return value
    except UpdateError:
        raise UpdateError("receipt_invalid") from None
    except (ReceiptWireError, KeyError, TypeError, ValueError, RecursionError):
        raise UpdateError("receipt_invalid") from None


def receipt_preimage(receipt: dict) -> bytes:
    return canonical_json({name: receipt[name] for name in RECEIPT_FIELDS if name != "signature"})


def verify_update_receipt(raw: bytes, *, request_bytes: bytes, trust_bytes: bytes, profile) -> dict:
    """Authentic, request-bound and in time; binds manifest, image lock, origin and epoch."""
    from ..deployment.receipt_contracts import ReceiptWireError, _signature, _timestamp
    from ..deployment.receipt_crypto import verify_detached
    from ..deployment.recovery_contracts import parse_trust_set_v2
    from ..deployment.recovery_schema_exports import ADAPTER_VERSION, RECOVERY_ADAPTER
    from ..operations.setup import parse_base64url_32

    receipt = parse_update_receipt(raw)
    request = parse_canonical(request_bytes)
    try:
        trust = parse_trust_set_v2(trust_bytes, profile=profile)
        if receipt["trust_set_digest"] != _b64(sha256(trust_bytes).digest()):
            raise UpdateError("receipt_invalid")
        key = next((entry for entry in trust["keys"] if entry["key_id"] == receipt["key_id"]), None)
        # the stopped-control-plane deployment authority; a stage-only key never signs one
        if (key is None or key["algorithm"] != "ed25519" or key["trust_class"] != receipt["trust_class"]
                or RECOVERY_ADAPTER not in key["adapter_ids"] or receipt["operator_adapter"] != RECOVERY_ADAPTER
                or receipt["operator_version"] != ADAPTER_VERSION
                or receipt["deployment_profile_id"] != profile.deployment_profile_id):
            raise UpdateError("receipt_invalid")
        preimage = receipt_preimage(receipt)
        verify_detached(parse_base64url_32(key["public_key"]), preimage, _signature(receipt["signature"]))
    except ReceiptWireError:
        raise UpdateError("receipt_invalid") from None
    payload, preconditions = request["effect_payload"], request["preconditions"]
    if not all(receipt[name] == request[name] for name in (
            "request_id", "request_digest", "request_nonce", "kind", "instance_id", "origin_profile_digest")):
        raise UpdateError("receipt_mismatch")
    if (receipt["instance_id"] != profile.instance_id
            or receipt["origin_profile_digest"] != _b64(bytes.fromhex(profile.digest))
            or receipt["recovery_epoch"] != preconditions["current_recovery_epoch"]
            or receipt["recovery_epoch"] != payload["target_recovery_epoch"]
            or receipt["previous_release_manifest_sha256"] != preconditions["current_release_manifest_sha256"]
            or receipt["release_manifest_sha256"] != payload["target_release_manifest_sha256"]
            or receipt["image_lock_set_sha256"] != payload["target_image_lock_set_sha256"]):
        raise UpdateError("receipt_mismatch")
    try:
        in_time = (_timestamp(request["created_at"]) <= _timestamp(receipt["completed_at"])
                   < _timestamp(request["expires_at"]))
    except ReceiptWireError:
        in_time = False
    if not in_time:
        raise UpdateError("receipt_expired")
    return receipt


# ---- the stopped control plane ---------------------------------------------------------------

def open_maintenance(*, data_dir, session_root_dir, deployment_config, work_dir, expected_uid, expected_gid):
    """The held serving lock of a stopped control plane (shared with owner recovery)."""
    from .deployment_control import OwnerRecoveryError
    from .deployment_control import open_maintenance as _open

    try:
        return _open(data_dir=data_dir, session_root_dir=session_root_dir, deployment_config=deployment_config,
                     work_dir=work_dir, expected_uid=expected_uid, expected_gid=expected_gid)
    except OwnerRecoveryError as error:
        raise UpdateError(error.code) from None


def _consistent(maintenance):
    """Configuration, root and database at the same epoch; no owner recovery in flight."""
    from .deployment_control import OwnerRecoveryError, _consistent_epoch

    try:
        profile, configuration = maintenance.configuration()
        root, database = _consistent_epoch(maintenance, profile, configuration)
        pending = maintenance.pending()
    except OwnerRecoveryError as error:
        raise UpdateError(error.code) from None
    if pending is not None and pending["state"] in ("prepared", "importing"):
        # one deployment-authority transition at a time: finish or cancel the recovery first
        raise UpdateError("recovery_pending")
    return profile, root, database


def _updates_dir(maintenance):
    from .deployment_control import _child_directory

    return _child_directory(maintenance.work, "updates", maintenance.uid, maintenance.gid)


def _write_request_file(maintenance, request_id, request_bytes):
    from .deployment_control import _replace

    directory = _updates_dir(maintenance)
    try:
        _replace(directory, request_id + ".request.json", request_bytes, mode=0o644)
    finally:
        os.close(directory)
    return str(maintenance.work_path / "updates" / (request_id + ".request.json"))


def handshake(manifest, probes) -> list:
    """Every component the target release needs answers with its exact protocol."""
    answered = []
    probes = probes or {}
    for component in manifest["components"]:
        probe = probes.get(component["component_id"])
        if probe is None:
            raise UpdateError("component_unavailable", component["component_id"])
        try:
            answer = probe()
        except Exception:  # noqa: BLE001 - an unreachable component is one closed refusal
            raise UpdateError("component_unavailable", component["component_id"]) from None
        if type(answer) is not dict or answer.get("protocol") != component["protocol"]:
            raise UpdateError("component_version_mismatch", component["component_id"])
        answered.append(component["component_id"])
    return answered


def _stored(store, db, request_id):
    request = store.request(db, request_id)
    if request is None:
        raise UpdateError("unavailable")
    request_bytes = bytes(request["request"])
    if _sha256(request_bytes) != request["request_sha256"]:
        raise UpdateError("unavailable")
    return request, request_bytes, parse_canonical(request_bytes)


def _manifest_of(maintenance, request_id):
    from .deployment_control import _read

    directory = _updates_dir(maintenance)
    try:
        raw = _read(directory, request_id + ".manifest.json", 16384, maintenance.uid, maintenance.gid)
    finally:
        os.close(directory)
    if raw is None:
        raise UpdateError("unavailable")
    return raw, parse_manifest(raw)


# ---- subcommands ---------------------------------------------------------------------------

def status(maintenance) -> dict:
    from .recovery import update_guidance

    store = UpdateStore(maintenance.data_dir)
    with closing(store.connect()) as db:
        if not store.installed(db):
            return {"state": "status", **update_guidance(None)}
        store.verify(db)
        return {"state": "status", **update_guidance(db, live_state_digest=state_digest(db))}


def prepare(maintenance, *, manifest_bytes, image_lock_bytes, ttl_seconds=DEFAULT_TTL_SECONDS, now_ms=None):
    manifest = parse_manifest(manifest_bytes)
    parse_image_lock(image_lock_bytes, manifest=manifest)
    if type(ttl_seconds) is not int or not 60 <= ttl_seconds <= 86400:
        raise UpdateError("invalid_request")
    manifest_sha256 = _sha256(manifest_bytes)
    profile, root, database = _consistent(maintenance)
    store = UpdateStore(maintenance.data_dir)
    with closing(store.connect()) as db:
        store.ensure(db)
        active = store.active(db)
        if active is not None:
            request, request_bytes, value = _stored(store, db, active["request_id"])
            if request["target_manifest_sha256"] != manifest_sha256:
                raise UpdateError("pending")  # cancel it first
            path = _write_request_file(maintenance, request["request_id"], request_bytes)
            return _prepared(value, active, path, repeated=True)
        current = store.release(db)
        if current is not None and current["manifest_sha256"] == manifest_sha256:
            raise UpdateError("already_current")
        current_schema = data_schema(db)
        plan_migration(current_schema, manifest["data_schema"], _builtin_steps())
        now = _now_ms() if now_ms is None else now_ms
        request_id = str(uuid4())
        request_bytes = make_update_request(
            profile=profile, request_id=request_id, nonce=os.urandom(32), actor_ref=database["actor"],
            created_ms=now - now % 1000, ttl_seconds=ttl_seconds, epoch=root["epoch"],
            generation_id=root["generation_id"], root_manifest_sha256=root["manifest_sha256"],
            current_release_manifest_sha256=None if current is None else current["manifest_sha256"],
            current_schema_sha256=schema_sha256(current_schema), manifest_sha256=manifest_sha256,
            manifest=manifest)
        value = parse_canonical(request_bytes)
        # the manifest is kept beside its request (the tool rechecks components and schema
        # from these exact bytes); an unnamed file left by a crash is inert
        from .deployment_control import _replace

        directory = _updates_dir(maintenance)
        try:
            _replace(directory, request_id + ".manifest.json", manifest_bytes, mode=0o644)
            _replace(directory, request_id + ".image-lock.json", image_lock_bytes, mode=0o644)
        finally:
            os.close(directory)
        path = _write_request_file(maintenance, request_id, request_bytes)
        _step("request_written")
        db.execute("BEGIN IMMEDIATE")
        try:
            if store.active(db) is not None:
                raise UpdateError("pending")
            db.execute("INSERT INTO deployment_update_requests VALUES (?,?,?,?,?,?,?,?,?,?,?)", (
                request_id, value["request_digest"], value["request_nonce"], _sha256(request_bytes), request_bytes,
                manifest["release_id"], manifest_sha256, manifest["image_lock_set_sha256"], root["epoch"],
                value["created_at"], value["expires_at"]))
            db.execute("INSERT INTO deployment_update_lifecycle (request_id,revision,state,recorded_at) "
                       "VALUES (?,1,'prepared',?)", (request_id, _stamp()))
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        return _prepared(value, store.head(db, request_id), path, repeated=False)


def _prepared(value, head, path, *, repeated):
    return {"state": head["state"], "repeated": repeated, "request_id": value["request_id"],
            "request_path": path, "revision": head["revision"],
            "target_release_id": value["effect_payload"]["target_release_id"],
            "target_release_manifest_sha256": value["effect_payload"]["target_release_manifest_sha256"],
            "target_image_lock_set_sha256": value["effect_payload"]["target_image_lock_set_sha256"],
            "recovery_epoch": value["preconditions"]["current_recovery_epoch"],
            "expires_at": value["expires_at"]}


def cancel(maintenance) -> dict:
    store = UpdateStore(maintenance.data_dir)
    with closing(store.connect()) as db:
        if not store.installed(db):
            raise UpdateError("no_pending")
        store.verify(db)
        active = store.active(db)
        if active is None:
            last = next(iter(store.heads(db)), None)
            if last is not None and last["state"] == "cancelled":
                return {"state": "cancelled", "repeated": True, "request_id": last["request_id"]}
            raise UpdateError("already_completed" if last is not None and last["state"] == "completed"
                              else "no_pending")
    if active["state"] == "migrating":
        raise UpdateError("migration_in_progress")  # re-run migrate with the journaled receipt
    head = store.advance(active["request_id"], expected_revision=active["revision"], state="cancelled")
    return {"state": "cancelled", "repeated": False, "request_id": head["request_id"], "revision": head["revision"]}


def _backup_files(maintenance, backup_id):
    from ..services.backups import BACKUPS_DIR

    directory = maintenance.data_dir / BACKUPS_DIR
    return directory / f"{backup_id}.age", directory / f"{backup_id}.receipt.json", \
        directory / f"{backup_id}.deleted.json"


def _check_backup_files(maintenance, head):
    """The gate's backup is still exactly there: ciphertext, external receipt, no tombstone."""
    import json

    ciphertext, receipt, tombstone = _backup_files(maintenance, head["backup_id"])
    try:
        if tombstone.exists() or ciphertext.is_symlink() or receipt.is_symlink():
            raise UpdateError("backup_missing")
        value = json.loads(receipt.read_bytes())
        body = ciphertext.read_bytes()
    except OSError:
        raise UpdateError("backup_missing") from None
    except ValueError:
        raise UpdateError("backup_missing") from None
    if (type(value) is not dict or value.get("backup_id") != head["backup_id"]
            or value.get("ciphertext_sha256") != head["backup_ciphertext_sha256"]
            or _sha256(body) != head["backup_ciphertext_sha256"] or value.get("ciphertext_size") != len(body)):
        raise UpdateError("backup_missing")


def backup(maintenance, *, crypto, probes=None) -> dict:
    """Take and verify the gate backup at the current state digest."""
    from .backup import BackupError, _check_manifest, _unarchive, check_receipt, create_backup
    from ..services.backups import BACKUPS_DIR

    _consistent(maintenance)
    store = UpdateStore(maintenance.data_dir)
    with closing(store.connect()) as db:
        if not store.installed(db):
            raise UpdateError("no_pending")
        store.verify(db)
        active = store.active(db)
        if active is None:
            raise UpdateError("no_pending")
        if active["state"] == "migrating":
            raise UpdateError("migration_in_progress")
        release = store.release(db)
        before = state_digest(db)
    request_id = active["request_id"]
    try:
        handshake({"components": [{"component_id": BACKUP_COMPONENT, "protocol": _backup_protocol()}]}, probes)
    except UpdateError as error:
        store.refuse(request_id, error.code, error.detail)
        raise
    output = maintenance.data_dir / BACKUPS_DIR
    if output.is_symlink():
        raise UpdateError("unavailable")
    output.mkdir(mode=0o700, exist_ok=True)
    outcome = create_backup(maintenance.data_dir, output, key_mode="instance_backup_key", crypto=crypto,
                            server_release=UNRECORDED_RELEASE if release is None else release["release_id"])
    if outcome.state != "ready":
        store.refuse(request_id, "backup_failed", outcome.failure)
        raise UpdateError("backup_failed", outcome.failure)
    _step("backup_created")
    # verify it as a restore would see it: the external receipt against the ciphertext,
    # then the archive decrypted again through the same port, then its state digest
    try:
        receipt = check_receipt(outcome.receipt)
        ciphertext = Path(outcome.ciphertext_path).read_bytes()
        if _sha256(ciphertext) != receipt["ciphertext_sha256"] or len(ciphertext) != receipt["ciphertext_size"]:
            raise BackupError("the backup file differs from its external receipt")
        archive = crypto.decrypt(ciphertext, key_mode="instance_backup_key")
        manifest, database, originals = _unarchive(archive)
        _check_manifest(manifest, database, originals)
        if manifest["backup_id"] != receipt["backup_id"]:
            raise BackupError("the backup manifest belongs to another receipt")
        with tempfile.TemporaryDirectory(prefix="update-gate-") as scratch:
            copy = Path(scratch) / "intake.sqlite3"
            copy.write_bytes(database)
            with sqlite3.connect(f"file:{copy}?mode=ro", uri=True) as archived:
                archived_digest = state_digest(archived)
    except (BackupError, OSError, KeyError, TypeError, ValueError):
        store.refuse(request_id, "backup_unverified")
        raise UpdateError("backup_unverified") from None
    except Exception:  # noqa: BLE001 - a worker failure is the same refusal, never a detail
        store.refuse(request_id, "backup_unverified")
        raise UpdateError("backup_unverified") from None
    with closing(store.connect()) as db:
        after = state_digest(db)
    if not before == after == archived_digest:
        store.refuse(request_id, "backup_state_mismatch")
        raise UpdateError("backup_state_mismatch")
    head = store.advance(request_id, expected_revision=active["revision"], state="backup_verified",
                         backup_id=receipt["backup_id"], backup_ciphertext_sha256=receipt["ciphertext_sha256"],
                         backup_state_digest=archived_digest)
    return {"state": "backup_verified", "request_id": request_id, "revision": head["revision"],
            "backup_id": receipt["backup_id"], "state_digest": archived_digest}


def _backup_protocol():
    from ..workers.backup_stream import REQUEST_SCHEMA

    return REQUEST_SCHEMA


def migrate(maintenance, *, receipt_bytes, trust_bytes, probes=None, steps=None) -> dict:
    if type(receipt_bytes) is not bytes or type(trust_bytes) is not bytes:
        raise UpdateError("invalid_request")
    steps = _builtin_steps() if steps is None else steps
    claimed = parse_update_receipt(receipt_bytes)["request_id"]
    receipt_sha256 = _sha256(receipt_bytes)
    store = UpdateStore(maintenance.data_dir)
    with closing(store.connect()) as db:
        if not store.installed(db):
            raise UpdateError("no_pending")
        store.verify(db)
        head = store.head(db, claimed)
        if head is None:
            raise UpdateError("receipt_mismatch")  # a request this instance never sealed
        consumed = db.execute("SELECT receipt_sha256 FROM deployment_update_consumptions WHERE request_id=?",
                              (claimed,)).fetchone()
        if head["state"] == "completed":
            if consumed is not None and consumed[0] == receipt_sha256:
                return _completed(db, store, claimed, repeated=True)
            raise UpdateError("replayed")
        if head["state"] == "cancelled":
            raise UpdateError("cancelled")
        if head["state"] == "failed":
            raise UpdateError("failed")
        if head["state"] == "prepared":
            store.refuse(claimed, "backup_required")
            raise UpdateError("backup_required")
        if head["state"] == "migrating" and head["receipt_sha256"] != receipt_sha256:
            raise UpdateError("migration_in_progress")  # only the journaled receipt completes it
        _request, request_bytes, request = _stored(store, db, claimed)
    manifest_bytes, manifest = _manifest_of(maintenance, claimed)
    if _sha256(manifest_bytes) != request["effect_payload"]["target_release_manifest_sha256"]:
        raise UpdateError("unavailable")
    try:
        profile, root, _database = _consistent(maintenance)
        receipt = verify_update_receipt(receipt_bytes, request_bytes=request_bytes, trust_bytes=trust_bytes,
                                        profile=profile)
        preconditions = request["preconditions"]
        if (root["epoch"], root["generation_id"], root["manifest_sha256"]) != (
                preconditions["current_recovery_epoch"], preconditions["current_session_root_generation_id"],
                preconditions["current_session_root_manifest_sha256"]):
            raise UpdateError("epoch_changed")
        handshake(manifest, probes)
        _check_backup_files(maintenance, head)
    except UpdateError as error:
        if error.code not in ("receipt_invalid", "busy"):
            store.refuse(claimed, error.code, error.detail)
        raise
    _step("receipt_verified")
    if head["state"] == "backup_verified":
        with closing(store.connect()) as db:
            if state_digest(db) != head["backup_state_digest"]:
                store.refuse(claimed, "backup_stale")
                raise UpdateError("backup_stale")
        # the journal: from here only this receipt completes the request, and no cancel
        head = store.advance(claimed, expected_revision=head["revision"], state="migrating",
                             receipt_sha256=receipt_sha256)
        _step("migrating_recorded")
    return _migrate_transaction(maintenance, store, claimed, head, receipt, receipt_sha256, request, manifest,
                                trust_bytes, steps)


def _migrate_transaction(maintenance, store, request_id, head, receipt, receipt_sha256, request, manifest,
                         trust_bytes, steps):
    """The one transaction: gate recheck, steps, target check, migration record, unique
    receipt consumption, release head and the `completed` CAS commit together."""
    db = store.connect()
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            current = store.head(db, request_id)
            if current is None or current["revision"] != head["revision"] or current["state"] != "migrating" \
                    or current["receipt_sha256"] != receipt_sha256:
                raise UpdateError("conflict")
            if db.execute("SELECT 1 FROM deployment_update_consumptions WHERE receipt_sha256=? OR request_id=? "
                          "OR request_nonce=?", (receipt_sha256, request_id, receipt["request_nonce"])).fetchone():
                raise UpdateError("replayed")
            before = state_digest(db)
            if before != current["backup_state_digest"]:
                # a write after the backup: never migrate over data the backup does not hold
                raise UpdateError("backup_stale")
            schema = data_schema(db)
            if schema_sha256(schema) != request["preconditions"]["current_data_schema_sha256"]:
                raise UpdateError("schema_changed")
            todo = plan_migration(schema, manifest["data_schema"], steps)
            failure = None
            db.execute("SAVEPOINT update_steps")
            try:
                for _family, _row, step in todo:
                    step(db)
                result = data_schema(db)
                if any(result.get(family) != rows for family, rows in manifest["data_schema"].items()):
                    raise MigrationStepFailure("the migrated schema is not the target")
                db.execute("RELEASE update_steps")
            except STEP_FAILURES:
                # a step failed on its own terms (never a crash: that ends the process and
                # rolls the whole transaction back)
                db.execute("ROLLBACK TO update_steps")
                db.execute("RELEASE update_steps")
                failure = "migration_failed"
            if failure is not None:
                # the data is exactly the backed-up state; the request ends failed
                store.advance_in_transaction(db, request_id, expected_revision=current["revision"],
                                             state="failed", failure_code=failure)
                db.execute("COMMIT")
                raise UpdateError(failure)
            _step("migration_applied")
            after = state_digest(db)
            migration_id = str(uuid4())
            now = _stamp()
            db.execute("INSERT INTO deployment_update_applied VALUES (?,?,?,?,?,?,?,?)", (
                migration_id, request_id, schema_sha256(schema), schema_sha256(data_schema(db)),
                canonical_json([[family, row] for family, row, _step_fn in todo]).decode("utf-8"),
                before, after, now))
            db.execute("INSERT INTO deployment_update_consumptions VALUES (?,?,?,?,?,?)", (
                receipt_sha256, request_id, receipt["request_nonce"], migration_id, _sha256(trust_bytes), now))
            revision = db.execute("SELECT coalesce(max(revision),0)+1 FROM deployment_update_releases").fetchone()[0]
            payload = request["effect_payload"]
            db.execute("INSERT INTO deployment_update_releases VALUES (?,?,?,?,?,?)", (
                revision, payload["target_release_id"], payload["target_release_manifest_sha256"],
                payload["target_image_lock_set_sha256"], request_id, now))
            store.advance_in_transaction(db, request_id, expected_revision=current["revision"], state="completed")
            db.execute("COMMIT")
        except BaseException:
            if db.in_transaction:
                db.execute("ROLLBACK")
            raise
        _step("committed")
        return _completed(db, store, request_id, repeated=False)
    finally:
        db.close()


def _completed(db, store, request_id, *, repeated):
    head = store.head(db, request_id)
    applied = db.execute("SELECT * FROM deployment_update_applied WHERE request_id=?", (request_id,)).fetchone()
    release = store.release(db)
    return {"state": "completed", "repeated": repeated, "request_id": request_id, "revision": head["revision"],
            "release_id": release["release_id"], "release_manifest_sha256": release["manifest_sha256"],
            "migration_id": applied["migration_id"], "steps": parse_canonical(applied["steps"].encode("utf-8")),
            "next": "start the control plane of the new release"}


# ---- command line -------------------------------------------------------------------------

def _backup_client(path):
    """The control side of the verified `cp-backup` channel, and its handshake probe."""
    from ..domain.wire import WireLimits, parse_json_object
    from ..workers.backup_channel import BackupWorkerConfiguration
    from ..workers.backup_crypto_client import BackupCryptoClient

    if path is None:
        return None, {}
    try:
        with open(os.path.abspath(os.fspath(path)), "rb") as source:
            configuration = BackupWorkerConfiguration.from_mapping(parse_json_object(
                source.read(4097), required=("schema", "pair_root", "requester_boot_id"),
                limits=WireLimits(max_bytes=4096)))
        client = BackupCryptoClient.for_worker(configuration)
    except Exception:  # noqa: BLE001 - an unusable configuration is an unreachable component
        return None, {}

    def probe():
        client.describe()
        return {"protocol": _backup_protocol()}

    return client, {BACKUP_COMPONENT: probe}


def run(argv=None):
    from .recovery import read_operator_input

    parser = argparse.ArgumentParser(prog="python -m app.operations.updates",
                                     description="DeepTwin web-release update (control plane stopped)")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("status", "prepare", "backup", "cancel", "migrate"):
        command = commands.add_parser(name)
        for option in ("--data-dir", "--session-root-dir", "--deployment-config", "--work-dir"):
            command.add_argument(option, type=Path, required=True)
        command.add_argument("--expected-uid", type=int, required=True)
        command.add_argument("--expected-gid", type=int, required=True)
        if name == "prepare":
            command.add_argument("--target-manifest", type=Path, required=True)
            command.add_argument("--image-lock", type=Path, required=True)
            command.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
        if name in ("backup", "migrate"):
            command.add_argument("--backup-worker-config", type=Path, required=name == "backup")
        if name == "migrate":
            command.add_argument("--receipt", type=Path, required=True)
            command.add_argument("--trust-set", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with open_maintenance(data_dir=args.data_dir, session_root_dir=args.session_root_dir,
                              deployment_config=args.deployment_config, work_dir=args.work_dir,
                              expected_uid=args.expected_uid, expected_gid=args.expected_gid) as maintenance:
            if args.command == "status":
                result = status(maintenance)
            elif args.command == "prepare":
                result = prepare(maintenance,
                                 manifest_bytes=read_operator_input(maintenance, args.target_manifest, 16384),
                                 image_lock_bytes=read_operator_input(maintenance, args.image_lock, 16384),
                                 ttl_seconds=args.ttl_seconds)
            elif args.command == "cancel":
                result = cancel(maintenance)
            elif args.command == "backup":
                client, probes = _backup_client(args.backup_worker_config)
                result = backup(maintenance, crypto=client, probes=probes)
            else:
                _client, probes = _backup_client(args.backup_worker_config)
                result = migrate(maintenance,
                                 receipt_bytes=read_operator_input(maintenance, args.receipt, 8192),
                                 trust_bytes=read_operator_input(maintenance, args.trust_set, 16384),
                                 probes=probes)
    except UpdateError as error:
        refusal = {"state": "refused", "code": error.code}
        if error.detail is not None and error.code in ("component_unavailable", "component_version_mismatch",
                                                        "migration_unsupported"):
            refusal["component"] = error.detail
        sys.stdout.write(canonical_json(refusal).decode("utf-8") + "\n")
        return 2
    sys.stdout.write(canonical_json(result).decode("utf-8") + "\n")
    return 0


def main():
    raise SystemExit(run())


if __name__ == "__main__":
    main()
