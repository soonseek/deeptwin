"""Consistent encrypted backups and staged restore (US7, T070; operations.md §5.2).

`create_backup` takes one consistent SQLite online-backup snapshot of the vault
database, removes every category that must never become restorable authority,
seals the rest with an internal `BackupManifest` into a deterministic archive,
encrypts that archive with the verified age 1.3.2 runtime (backup_crypto) to a
native X25519 recipient, and then decrypts it again in a fresh staging directory
to prove it restores before the backup is `ready`. Creating the file alone is
never called recoverable. The external `BackupReceipt` binds the finished
ciphertext's hash and size (the manifest inside never carries its own archive's
hash) and names the restore verification that ran.

Table classification is closed: every table in the snapshot is either named as
restorable history or excluded under a stated category (credentials, owner
authenticators and sessions, service clients, pending challenges, unconsumed
capabilities and verifiers, deployment-receipt private state). A table this
module does not know refuses the backup rather than being carried silently.

Key modes are exact. `instance_backup_key` encrypts to the deployment's own
backup-key volume recipient (backup-key-init); such a backup is marked not
recoverable after host/volume loss. `portable_recovery` encrypts to a recipient
whose identity the user keeps elsewhere; the identity reaches this module only
as a `OneShotIdentity`, used once for the restore proof and wiped. Neither
identity is written into the archive, the manifest, the receipt or an error.

`restore_backup` never touches an active vault: it checks the external receipt
against the ciphertext before decrypting, requires the full authenticated
plaintext (a truncated or altered stream fails with nothing written), checks
archive members, sizes, hashes, schema and the excluded categories, opens the
restored data and reads every record back through the domain store, and only
then leaves a vault in an empty staging directory marked `restored_review`:
dispatch stays blocked until a new owner bootstraps, re-creates connections and
service clients, and explicitly reactivates an exact environment.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from ..workers.backup_crypto import (
    PROFILE,
    AgeRuntime,
    BackupCryptoError,
    require_identity,
)
from .backup_key import BackupKeyInitError, _verify_existing

SCHEMA_VERSION = 1
KEY_MODES = frozenset({"instance_backup_key", "portable_recovery"})
DATABASE_NAME = "intake.sqlite3"
_ARCHIVE_DB = "vault/" + DATABASE_NAME
_ARCHIVE_MANIFEST = "manifest.json"
_MARKER = "restored_review.json"
_MAX_ARCHIVE_BYTES = 1 << 31
_MAX_MANIFEST_BYTES = 1 << 20

# restorable history, by exact table family
INCLUDED_PREFIXES = (
    "domain_", "runtime_", "api_event_", "api_command", "extension_candidate_",
    "provider_conformance_", "model_catalog", "work_model_", "run_model_choices",
    "work_usage_", "conversation_", "speech_", "understanding_", "design_requests",
    "permission_",
)
INCLUDED_TABLES = frozenset({"works", "files", "revisions", "events"})
# never restorable: table (or family) -> the stated excluded category
EXCLUDED = (
    ("owner_auth_", "owner_authenticators_sessions_and_bootstrap_verifiers"),
    ("owner_material_", "unconsumed_human_capabilities"),
    ("service_client_", "service_client_credentials"),
    ("provider_connection", "provider_credential_handles"),
    ("provider_credential_", "provider_credential_handles"),
    ("provider_orphan_cleanup", "provider_credential_handles"),
    ("model_catalog_account_state", "provider_account_state"),
    ("conversation_challenges", "pending_challenges"),
    ("permission_grants", "unconsumed_capabilities"),
    ("permission_projections", "unconsumed_capabilities"),
    ("deployment_prepare_", "deployment_receipt_private_state"),
)
# never part of the vault database at all; stated so the manifest is complete
OUT_OF_SCOPE_CATEGORIES = (
    "provider_credential_root", "session_root", "backup_key_volume",
    "codex_auth_volume_and_tokens", "raw_audio", "regenerable_caches",
)
STATES = ("backup_pending", "snapshotting", "encrypting", "verify_restore", "ready")
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class BackupError(RuntimeError):
    """A closed backup/restore failure; never carries secret material."""


class OneShotIdentity:
    """A portable recovery identity handed over once (masked input, never stored)."""

    __slots__ = ("_secret",)

    def __init__(self, secret):
        if type(secret) not in (bytes, bytearray):
            raise BackupError("a recovery identity must be exact bytes")
        self._secret = bytearray(secret)

    def take(self) -> bytes:
        if self._secret is None:
            raise BackupError("the recovery identity was already used")
        try:
            return require_identity(bytes(self._secret))
        except BackupCryptoError:
            raise BackupError("the recovery identity is not a native age identity") from None
        finally:
            for index in range(len(self._secret)):
                self._secret[index] = 0
            self._secret = None

    def __repr__(self):
        return "OneShotIdentity(<masked>)"


@dataclass(frozen=True, slots=True)
class BackupKeyHandle:
    """The opaque handle to the deployment's own backup-key volume."""

    volume_root: Path

    def recipient(self) -> str:
        try:
            state = _verify_existing(self.volume_root / "identity.age",
                                     self.volume_root / "manifest.json")
        except (BackupKeyInitError, OSError):
            raise BackupError("the backup-key volume is missing or malformed") from None
        return state.recipient

    def identity(self) -> bytes:
        self.recipient()  # the exact verified pair, or nothing
        try:
            return require_identity((self.volume_root / "identity.age").read_bytes())
        except (BackupCryptoError, OSError):
            raise BackupError("the backup-key volume is missing or malformed") from None


@dataclass(frozen=True, slots=True)
class BackupOutcome:
    state: str
    states: tuple[str, ...]
    ciphertext_path: Path | None
    receipt: dict | None
    manifest: dict | None
    failure: str | None


@dataclass(frozen=True, slots=True)
class RestoreOutcome:
    state: str  # "restored_review" | "failed"
    vault_dir: Path | None
    manifest: dict | None
    checked: tuple[str, ...]
    failure: str | None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def classify_table(name: str) -> str | None:
    """None for restorable history, else the excluded category; unknown refuses."""

    for prefix, category in EXCLUDED:
        if name == prefix or name.startswith(prefix):
            return category
    if name in INCLUDED_TABLES or name.startswith(INCLUDED_PREFIXES) or name.startswith("sqlite_"):
        return None
    raise BackupError(f"an unclassified table would be carried: {name}")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tables(db) -> list[str]:
    return [row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def _consistency(db) -> dict:
    integrity = db.execute("PRAGMA integrity_check").fetchall()
    violations = db.execute("PRAGMA foreign_key_check").fetchall()
    if [tuple(row) for row in integrity] != [("ok",)] or violations:
        raise BackupError("the snapshot is not internally consistent")
    return {"method": "sqlite_online_backup", "integrity_check": "ok",
            "foreign_key_violations": 0}


def _snapshot(source: Path, target: Path) -> tuple[dict, list[str], dict]:
    """One consistent copy of the vault database, excluded tables removed."""

    if source.is_symlink() or not source.is_file():
        raise BackupError("the vault database is missing")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=10)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
            excluded = {}
            for name in _tables(dst):
                category = classify_table(name)
                if category is not None:
                    excluded.setdefault(category, []).append(name)
            dst.execute("PRAGMA foreign_keys=OFF")
            for names in excluded.values():
                for name in names:
                    dst.execute(f'DROP TABLE "{name}"')
            dst.commit()
            dst.execute("VACUUM")
            dst.execute("PRAGMA foreign_keys=ON")
            consistency = _consistency(dst)
            vault = dst.execute("SELECT vault_id FROM domain_vault").fetchone()
            if vault is None:
                raise BackupError("the snapshot holds no initialized vault")
            sequence = dst.execute("SELECT count(*) FROM domain_records").fetchone()[0]
            identity = {"vault_id": vault[0], "snapshot_sequence": sequence,
                        "data_schema_version": [list(row) for row in dst.execute(
                            "SELECT version, sha256 FROM domain_migrations ORDER BY version")]}
        finally:
            dst.close()
    except sqlite3.DatabaseError:
        raise BackupError("the vault database could not be snapshotted") from None
    finally:
        src.close()
    categories = sorted([*excluded, *OUT_OF_SCOPE_CATEGORIES])
    return identity, categories, consistency


def _archive(manifest: dict, database: bytes) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, body in ((_ARCHIVE_MANIFEST, _canonical(manifest)), (_ARCHIVE_DB, database)):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(body), 0o600, 0
            archive.addfile(info, io.BytesIO(body))
    return buffer.getvalue()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _unarchive(archive: bytes) -> tuple[dict, bytes]:
    """The exact two members, bounded, regular, with no path games."""

    members = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as reader:
            for info in reader:
                if (not info.isreg() or info.name not in {_ARCHIVE_MANIFEST, _ARCHIVE_DB}
                        or info.name in members):
                    raise BackupError("the archive holds an unexpected member")
                bound = _MAX_MANIFEST_BYTES if info.name == _ARCHIVE_MANIFEST else _MAX_ARCHIVE_BYTES
                if info.size > bound:
                    raise BackupError("an archive member exceeds its bound")
                members[info.name] = reader.extractfile(info).read()
    except tarfile.TarError:
        raise BackupError("the archive is malformed") from None
    if set(members) != {_ARCHIVE_MANIFEST, _ARCHIVE_DB}:
        raise BackupError("the archive is incomplete")
    try:
        manifest = json.loads(members[_ARCHIVE_MANIFEST])
    except ValueError:
        raise BackupError("the backup manifest is malformed") from None
    return manifest, members[_ARCHIVE_DB]


def _check_manifest(manifest, database: bytes) -> None:
    expected = {"schema_version", "backup_id", "vault_id", "server_release",
                "data_schema_version", "snapshot_sequence", "created_at", "item_refs",
                "encryption_profile_ref", "key_mode", "excluded_categories",
                "consistency_evidence_ref"}
    if type(manifest) is not dict or set(manifest) != expected:
        raise BackupError("the backup manifest is malformed")
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise BackupError("the backup schema version is not supported")
    if manifest["encryption_profile_ref"] != PROFILE or manifest["key_mode"] not in KEY_MODES:
        raise BackupError("the backup encryption profile is not supported")
    items = manifest["item_refs"]
    if items != [{"path": _ARCHIVE_DB, "sha256": _sha256(database), "size": len(database)}]:
        raise BackupError("an archive item differs from its manifest entry")


def _write_excl(path: Path, body: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(body)
        while view:
            view = view[os.write(descriptor, view):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_database(path: Path, manifest: dict) -> tuple[str, ...]:
    """Open the restored data and read every record back; no model or tool runs."""

    from ..domain.refs import EntityRef
    from ..domain.store import DomainStore
    from ..storage import Store

    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        _consistency(db)
        tables = _tables(db)
        for name in tables:
            if classify_table(name) is not None:
                raise BackupError("an excluded category is present in the backup")
        vault = db.execute("SELECT vault_id FROM domain_vault").fetchone()
        rows = db.execute("SELECT kind, id, version, sha256 FROM domain_records").fetchall()
    except sqlite3.DatabaseError:
        raise BackupError("the restored data does not open") from None
    finally:
        db.close()
    if vault is None or vault[0] != manifest["vault_id"] or len(rows) != manifest["snapshot_sequence"]:
        raise BackupError("the restored data is not the recorded vault")
    try:
        domain = DomainStore(Store(path.parent))
        domain.roots()
        for kind, record_id, version, sha in rows:
            domain.get(EntityRef(kind, record_id, version, sha))
    except BackupError:
        raise
    except Exception:  # noqa: BLE001 - the store's detail stays private
        raise BackupError("the restored lineage does not verify") from None
    return ("archive_members", "manifest_hashes", "schema_version", "sqlite_integrity",
            "foreign_keys", "excluded_categories_absent", "vault_identity", "record_lineage")


def _decrypt(runtime: AgeRuntime, ciphertext: bytes, identity: bytes) -> bytes:
    try:
        return runtime.decrypt(ciphertext, identity)
    except BackupCryptoError:
        raise BackupError("the backup does not decrypt and authenticate in full") from None


def create_backup(vault_dir, output_dir, *, runtime: AgeRuntime, key_mode: str,
                  server_release: str, key_handle: BackupKeyHandle | None = None,
                  recipient: str | None = None, recovery_identity: OneShotIdentity | None = None,
                  clock=_now) -> BackupOutcome:
    """snapshot → encrypt → verify_restore → ready, or a stated failure."""

    states = ["backup_pending"]

    def failed(reason):
        return BackupOutcome("failed", (*states, "failed"), None, None, None, reason)

    if type(runtime) is not AgeRuntime:
        return failed("the verified age runtime is required")
    if key_mode not in KEY_MODES or type(server_release) is not str or not server_release:
        return failed("an exact key mode and server release are required")
    try:
        if key_mode == "instance_backup_key":
            if type(key_handle) is not BackupKeyHandle or recipient or recovery_identity:
                raise BackupError("instance mode uses only the backup-key volume handle")
            target, identity = key_handle.recipient(), None
        else:
            if key_handle is not None or type(recovery_identity) is not OneShotIdentity:
                raise BackupError("portable mode needs its recipient and one-shot identity")
            target, identity = recipient, recovery_identity
        output = Path(output_dir)
        if output.is_symlink() or not output.is_dir():
            raise BackupError("the backup destination is not an existing directory")
    except BackupError as error:
        return failed(str(error))
    backup_id = str(uuid4())
    with tempfile.TemporaryDirectory(prefix="backup-") as scratch:
        scratch = Path(scratch)
        try:
            states.append("snapshotting")
            snapshot = scratch / DATABASE_NAME
            identity_fields, categories, consistency = _snapshot(
                Path(vault_dir) / DATABASE_NAME, snapshot)
            database = snapshot.read_bytes()
            manifest = {
                "schema_version": SCHEMA_VERSION, "backup_id": backup_id,
                "vault_id": identity_fields["vault_id"], "server_release": server_release,
                "data_schema_version": identity_fields["data_schema_version"],
                "snapshot_sequence": identity_fields["snapshot_sequence"],
                "created_at": clock(),
                "item_refs": [{"path": _ARCHIVE_DB, "sha256": _sha256(database),
                               "size": len(database)}],
                "encryption_profile_ref": PROFILE, "key_mode": key_mode,
                "excluded_categories": categories, "consistency_evidence_ref": consistency,
            }
            archive = _archive(manifest, database)
            states.append("encrypting")
            try:
                ciphertext = runtime.encrypt(archive, target)
            except BackupCryptoError:
                raise BackupError("the archive could not be encrypted") from None
            states.append("verify_restore")
            proof = identity.take() if identity is not None else key_handle.identity()
            restored_manifest, restored_db = _unarchive(_decrypt(runtime, ciphertext, proof))
            del proof
            _check_manifest(restored_manifest, restored_db)
            if restored_manifest != manifest:
                raise BackupError("the restored manifest differs from the sealed one")
            check_dir = scratch / "verify"
            check_dir.mkdir()
            _write_excl(check_dir / DATABASE_NAME, restored_db)
            scope = _verify_database(check_dir / DATABASE_NAME, manifest)
        except BackupError as error:
            return failed(str(error))
    path = output / f"{backup_id}.age"
    receipt = {
        "backup_id": backup_id, "ciphertext_sha256": _sha256(ciphertext),
        "ciphertext_size": len(ciphertext), "encryption_profile_ref": PROFILE,
        "completed_at": clock(),
        "restore_verification_ref": {"verified_at": clock(), "scope": list(scope)},
        "key_mode": key_mode,
        # a key that lives only in this deployment's volume does not survive its loss
        "recoverable_after_host_or_volume_loss": key_mode == "portable_recovery",
    }
    try:
        _write_excl(path, ciphertext)
        _write_excl(output / f"{backup_id}.receipt.json", _canonical(receipt))
        _fsync_directory(output)
    except OSError:
        return failed("the backup could not be written to its destination")
    states.append("ready")
    return BackupOutcome("ready", tuple(states), path, receipt, manifest, None)


def restore_backup(ciphertext_path, receipt, staging_dir, *, runtime: AgeRuntime,
                   key_handle: BackupKeyHandle | None = None,
                   recovery_identity: OneShotIdentity | None = None,
                   active_vault_dir=None) -> RestoreOutcome:
    """Restore into an empty staging directory as `restored_review`, or fail stating why."""

    def failed(reason):
        return RestoreOutcome("failed", None, None, (), reason)

    staging = Path(staging_dir)
    try:
        if type(runtime) is not AgeRuntime:
            raise BackupError("the verified age runtime is required")
        if (key_handle is None) == (recovery_identity is None):
            raise BackupError("exactly one key source is required")
        if staging.is_symlink() or not staging.is_dir() or any(staging.iterdir()):
            raise BackupError("the restore staging directory must exist and be empty")
        if active_vault_dir is not None and staging.resolve() == Path(active_vault_dir).resolve():
            raise BackupError("a restore never overwrites the active vault")
        if (type(receipt) is not dict or type(receipt.get("backup_id")) is not str
                or _UUID.fullmatch(receipt["backup_id"]) is None
                or type(receipt.get("ciphertext_sha256")) is not str
                or _SHA256.fullmatch(receipt["ciphertext_sha256"]) is None
                or receipt.get("encryption_profile_ref") != PROFILE):
            raise BackupError("the external backup receipt is malformed")
        source = Path(ciphertext_path)
        if source.is_symlink() or not source.is_file():
            raise BackupError("the backup file is missing")
        ciphertext = source.read_bytes()
        if (len(ciphertext) != receipt.get("ciphertext_size")
                or _sha256(ciphertext) != receipt["ciphertext_sha256"]):
            raise BackupError("the backup file differs from its external receipt")
        identity = (recovery_identity.take() if recovery_identity is not None
                    else key_handle.identity())
        manifest, database = _unarchive(_decrypt(runtime, ciphertext, identity))
        del identity
        _check_manifest(manifest, database)
        if manifest["backup_id"] != receipt["backup_id"]:
            raise BackupError("the backup manifest belongs to another receipt")
    except BackupError as error:
        return failed(str(error))
    vault = staging / "vault"
    try:
        vault.mkdir(mode=0o700)
        _write_excl(vault / DATABASE_NAME, database)
        checked = _verify_database(vault / DATABASE_NAME, manifest)
        marker = {
            "state": "restored_review", "dispatch": "blocked",
            "backup_id": manifest["backup_id"], "vault_id": manifest["vault_id"],
            "requires": ["new_owner_bootstrap", "recreate_connections_and_service_clients",
                         "review_and_activate_exact_environment"],
            "not_restored": manifest["excluded_categories"],
            "in_flight_requests": "remote_survival_unknown_until_confirmed",
        }
        _write_excl(staging / _MARKER, _canonical(marker))
        _fsync_directory(staging)
    except (BackupError, OSError) as error:
        for leftover in sorted(staging.rglob("*"), reverse=True):
            leftover.unlink() if not leftover.is_dir() else leftover.rmdir()
        reason = str(error) if type(error) is BackupError else "the restore could not be written"
        return failed(reason)
    return RestoreOutcome("restored_review", vault, manifest, checked, None)


def is_restored_review(staging_dir) -> bool:
    """A restored instance stays blocked until explicitly reactivated."""

    marker = Path(staging_dir) / _MARKER
    try:
        return json.loads(marker.read_bytes()).get("dispatch") == "blocked"
    except (OSError, ValueError):
        return False


def age_keygen(runtime: AgeRuntime):
    """The backup-key-init generator backed by the verified age-keygen."""

    def generate():
        identity, recipient = runtime.generate()
        return {"identity": identity.decode("ascii").strip(), "recipient": recipient}

    return generate


__all__ = [
    "KEY_MODES",
    "BackupError",
    "BackupKeyHandle",
    "BackupOutcome",
    "OneShotIdentity",
    "RestoreOutcome",
    "age_keygen",
    "classify_table",
    "create_backup",
    "is_restored_review",
    "restore_backup",
]
