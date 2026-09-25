"""T070: consistent age-encrypted backups through the verified age runtime.

The crypto runs against the exact locked age 1.3.2 binaries (member digests
verified on every open). They are not vendored in the repository: point
DEEPTWIN_AGE_RUNTIME_ROOT at the verified `age/` directory of the locked
archive (deploy/manifests/age-1.3.2.json); without it the binary-backed tests
skip and say so, and the pre-spawn refusals still run.
"""

import json
import os
import sqlite3
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.schemas import ImmutableRecord
from app.domain.store import DomainStore
from app.operations.backup import (
    BackupError,
    BackupKeyHandle,
    OneShotIdentity,
    age_keygen,
    classify_table,
    create_backup,
    is_restored_review,
    restore_backup,
)
from app.operations.backup_key import initialize_backup_key
from app.storage import Store
from app.workers.backup_crypto import (
    AgeRuntime,
    BackupCryptoError,
    require_identity,
    require_recipient,
)

AGE_ROOT = os.environ.get("DEEPTWIN_AGE_RUNTIME_ROOT")
needs_age = pytest.mark.skipif(
    not AGE_ROOT, reason="DEEPTWIN_AGE_RUNTIME_ROOT (the verified locked age 1.3.2) is not set")
CANARY = "credential-canary-7f3a"
STAMP = "2026-09-23T00:00:00.000000Z"


@pytest.fixture(scope="module")
def runtime():
    return AgeRuntime.open(AGE_ROOT)


def populated_vault(root: Path):
    domain = DomainStore(Store(root))
    roots = domain.initialize_vault()
    record = ImmutableRecord.create(
        kind="work_revision", id=str(uuid4()), version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=(), purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content={"text": "백업할 작업 내용"},
    )
    domain.put(record)
    with sqlite3.connect(root / "intake.sqlite3") as db:
        # sensitive state living in the same database must never be carried
        db.execute("CREATE TABLE IF NOT EXISTS owner_auth_sessions (session_id TEXT, token TEXT)")
        db.execute("INSERT INTO owner_auth_sessions VALUES ('s', ?)", (CANARY,))
        db.execute("CREATE TABLE IF NOT EXISTS conversation_challenges (id TEXT, verifier TEXT)")
        db.execute("INSERT INTO conversation_challenges VALUES ('c', ?)", (CANARY,))
        db.execute("CREATE TABLE IF NOT EXISTS provider_connections (id TEXT, handle TEXT)")
        db.execute("INSERT INTO provider_connections VALUES ('p', ?)", (CANARY,))
    return domain, record


def instance_key(runtime, root: Path) -> BackupKeyHandle:
    volume = root / "backup-key"
    volume.mkdir()
    initialize_backup_key(volume, keygen=age_keygen(runtime))
    return BackupKeyHandle(volume)


def backed_up(runtime, tmp_path, **kwargs):
    vault = tmp_path / "vault"
    _domain, record = populated_vault(vault)
    out = tmp_path / "out"
    out.mkdir()
    if "key_handle" not in kwargs and "recovery_identity" not in kwargs:
        kwargs["key_handle"] = instance_key(runtime, tmp_path)
        kwargs["key_mode"] = "instance_backup_key"
    outcome = create_backup(vault, out, runtime=runtime, server_release="1.0.0", **kwargs)
    return outcome, record, vault, out


# --- the code-owned age caller ----------------------------------------------------


def test_only_native_x25519_reaches_age():
    for refused in ("ssh-ed25519 AAAAC3Nza", "age1yubikey1qqqq", "age1pq1abc", "-p",
                    "--plugin=x", "age1" + "q" * 57, "AGE1" + "q" * 58, 7):
        with pytest.raises(BackupCryptoError):
            require_recipient(refused)
    assert require_recipient("age1" + "q" * 58)
    for refused in (b"AGE-PLUGIN-YUBIKEY-1QQQ", b"AGE-SECRET-KEY-1" + b"Q" * 57,
                    "AGE-SECRET-KEY-1" + "Q" * 58, b"# comment\nAGE-SECRET-KEY-1" + b"Q" * 58):
        with pytest.raises(BackupCryptoError):
            require_identity(refused)
    assert require_identity(b"AGE-SECRET-KEY-1" + b"Q" * 58).endswith(b"\n")


def test_a_runtime_with_other_binaries_is_refused(tmp_path):
    (tmp_path / "age").write_bytes(b"#!/bin/sh\necho v1.3.2\n")
    (tmp_path / "age-keygen").write_bytes(b"#!/bin/sh\necho v1.3.2\n")
    with pytest.raises(BackupCryptoError, match="locked digest"):
        AgeRuntime.open(tmp_path, machine="x86_64")
    with pytest.raises(BackupCryptoError, match="platform"):
        AgeRuntime.open(tmp_path, machine="riscv64")
    with pytest.raises(BackupCryptoError, match="installed"):
        AgeRuntime.open(tmp_path / "missing", machine="x86_64")


def test_the_one_shot_identity_is_used_once_and_masked():
    identity = OneShotIdentity(bytearray(b"AGE-SECRET-KEY-1" + b"Q" * 58))
    assert "SECRET" not in repr(identity)
    assert identity.take().startswith(b"AGE-SECRET-KEY-1")
    with pytest.raises(BackupError, match="already used"):
        identity.take()


def test_table_classification_is_closed():
    assert classify_table("domain_records") is None
    assert classify_table("runtime_runs") is None
    assert classify_table("owner_auth_sessions").startswith("owner_authenticators")
    assert classify_table("service_client_records") == "service_client_credentials"
    assert classify_table("provider_connections") == "provider_credential_handles"
    assert classify_table("conversation_challenges") == "pending_challenges"
    assert classify_table("permission_grants") == "unconsumed_capabilities"
    assert classify_table("deployment_prepare_receipts") == "deployment_receipt_private_state"
    with pytest.raises(BackupError, match="unclassified"):
        classify_table("brand_new_table")


def test_the_credential_command_ledger_is_stated_and_never_carried(tmp_path):
    """The control plane's credential command ledger (T090) sits beside the vault database
    but is a separate file: the snapshot never reads it and the manifest states it."""

    from app.api.credential_commands import CredentialCommandLedger
    from app.api.credential_wiring import LEDGER_NAME
    from app.operations.backup import OUT_OF_SCOPE_CATEGORIES, _snapshot

    vault = tmp_path / "vault"
    populated_vault(vault)
    CredentialCommandLedger(vault / LEDGER_NAME)
    with sqlite3.connect(vault / LEDGER_NAME) as db:
        ledger_tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert ledger_tables
    assert "credential_command_ledger" in OUT_OF_SCOPE_CATEGORIES
    _identity, categories, _consistency = _snapshot(vault / "intake.sqlite3", tmp_path / "snapshot.sqlite3")
    assert "credential_command_ledger" in categories
    with sqlite3.connect(tmp_path / "snapshot.sqlite3") as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not ledger_tables & tables
    # were its tables ever moved into the vault database, they would be unclassified and
    # refuse the backup rather than ride along
    for name in ledger_tables:
        with pytest.raises(BackupError):
            classify_table(name)


@needs_age
def test_a_backup_beside_a_credential_command_ledger_restores_without_it(runtime, tmp_path):
    from app.api.credential_commands import CredentialCommandLedger
    from app.api.credential_wiring import LEDGER_NAME

    vault = tmp_path / "vault"
    populated_vault(vault)
    CredentialCommandLedger(vault / LEDGER_NAME)
    out = tmp_path / "out"
    out.mkdir()
    outcome = create_backup(vault, out, runtime=runtime, server_release="1.0.0",
                            key_handle=instance_key(runtime, tmp_path), key_mode="instance_backup_key")
    assert outcome.state == "ready", outcome.failure
    assert "credential_command_ledger" in outcome.manifest["excluded_categories"]
    assert all(LEDGER_NAME not in item["path"] for item in outcome.manifest["item_refs"])
    staging = tmp_path / "staging"
    staging.mkdir()
    restored = restore_backup(outcome.ciphertext_path, outcome.receipt, staging, runtime=runtime,
                              key_handle=BackupKeyHandle(tmp_path / "backup-key"), active_vault_dir=vault)
    assert restored.state == "restored_review", restored.failure
    assert not (restored.vault_dir / LEDGER_NAME).exists()


@needs_age
def test_age_roundtrip_wrong_identity_and_tamper(runtime):
    identity, recipient = runtime.generate()
    assert runtime.recipient_of(identity) == recipient
    ciphertext = runtime.encrypt(b"plain bytes", recipient)
    assert b"plain bytes" not in ciphertext
    assert runtime.decrypt(ciphertext, identity) == b"plain bytes"
    other, _ = runtime.generate()
    with pytest.raises(BackupCryptoError) as refused:
        runtime.decrypt(ciphertext, other)
    assert "AGE-SECRET" not in str(refused.value)
    tampered = bytearray(ciphertext)
    tampered[-5] ^= 0x01
    with pytest.raises(BackupCryptoError):
        runtime.decrypt(bytes(tampered), identity)


# --- backup -------------------------------------------------------------------------


@needs_age
def test_instance_backup_is_ready_only_after_a_restore_proof(runtime, tmp_path):
    outcome, _record, _vault, out = backed_up(runtime, tmp_path)
    assert outcome.state == "ready", outcome.failure
    assert outcome.states == ("backup_pending", "snapshotting", "encrypting",
                              "verify_restore", "ready")
    receipt = outcome.receipt
    assert receipt["recoverable_after_host_or_volume_loss"] is False
    assert "record_lineage" in receipt["restore_verification_ref"]["scope"]
    manifest = outcome.manifest
    assert manifest["key_mode"] == "instance_backup_key"
    assert {"owner_authenticators_sessions_and_bootstrap_verifiers", "pending_challenges",
            "provider_credential_handles", "codex_auth_volume_and_tokens",
            "backup_key_volume"} <= set(manifest["excluded_categories"])
    # the manifest never carries its own archive's or ciphertext's hash
    assert receipt["ciphertext_sha256"] not in json.dumps(manifest)
    ciphertext = outcome.ciphertext_path.read_bytes()
    assert ciphertext.startswith(b"age-encryption.org/v1\n")
    assert CANARY.encode() not in ciphertext
    assert stat.S_IMODE(outcome.ciphertext_path.stat().st_mode) == 0o600
    on_disk = json.loads((out / f"{receipt['backup_id']}.receipt.json").read_bytes())
    assert on_disk == receipt
    for text in (json.dumps(receipt), json.dumps(manifest)):
        assert "AGE-SECRET-KEY" not in text


@needs_age
def test_a_missing_key_volume_or_unknown_table_refuses(runtime, tmp_path):
    vault = tmp_path / "vault"
    populated_vault(vault)
    out = tmp_path / "out"
    out.mkdir()
    lost = create_backup(vault, out, runtime=runtime, key_mode="instance_backup_key",
                         server_release="1.0.0", key_handle=BackupKeyHandle(tmp_path / "gone"))
    assert lost.state == "failed" and "backup-key volume" in lost.failure
    handle = instance_key(runtime, tmp_path)
    with sqlite3.connect(vault / "intake.sqlite3") as db:
        db.execute("CREATE TABLE mystery (secret TEXT)")
    unknown = create_backup(vault, out, runtime=runtime, key_mode="instance_backup_key",
                            server_release="1.0.0", key_handle=handle)
    assert unknown.state == "failed" and "unclassified" in unknown.failure
    assert unknown.states[-1] == "failed" and list(out.iterdir()) == []
    mixed = create_backup(vault, out, runtime=runtime, key_mode="bogus", server_release="1.0.0")
    assert mixed.state == "failed"


# --- restore ------------------------------------------------------------------------


@needs_age
def test_instance_restore_opens_as_restored_review_without_the_excluded_state(runtime, tmp_path):
    outcome, record, vault, _out = backed_up(runtime, tmp_path)
    handle = BackupKeyHandle(tmp_path / "backup-key")
    staging = tmp_path / "staging"
    staging.mkdir()
    restored = restore_backup(outcome.ciphertext_path, outcome.receipt, staging,
                              runtime=runtime, key_handle=handle, active_vault_dir=vault)
    assert restored.state == "restored_review", restored.failure
    assert is_restored_review(staging)
    marker = json.loads((staging / "restored_review.json").read_bytes())
    assert marker["dispatch"] == "blocked"
    assert "new_owner_bootstrap" in marker["requires"]
    domain = DomainStore(Store(restored.vault_dir))
    assert domain.get(record.ref).body["content"] == {"text": "백업할 작업 내용"}
    with sqlite3.connect(restored.vault_dir / "intake.sqlite3") as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    assert not {"owner_auth_sessions", "conversation_challenges", "provider_connections"} & tables
    assert CANARY.encode() not in (restored.vault_dir / "intake.sqlite3").read_bytes()
    # the source vault was only read
    with sqlite3.connect(vault / "intake.sqlite3") as db:
        assert db.execute("SELECT token FROM owner_auth_sessions").fetchone() == (CANARY,)


@needs_age
def test_portable_recovery_uses_a_one_shot_identity(runtime, tmp_path):
    identity, recipient = runtime.generate()
    outcome, _record, _vault, _out = backed_up(
        runtime, tmp_path, key_mode="portable_recovery", recipient=recipient,
        recovery_identity=OneShotIdentity(identity))
    assert outcome.state == "ready", outcome.failure
    assert outcome.receipt["recoverable_after_host_or_volume_loss"] is True
    # another deployment: no backup-key volume, only the user's kept identity
    staging = tmp_path / "elsewhere"
    staging.mkdir()
    once = OneShotIdentity(identity)
    restored = restore_backup(outcome.ciphertext_path, outcome.receipt, staging,
                              runtime=runtime, recovery_identity=once)
    assert restored.state == "restored_review", restored.failure
    with pytest.raises(BackupError, match="already used"):
        once.take()
    wrong_staging = tmp_path / "wrong"
    wrong_staging.mkdir()
    other, _ = runtime.generate()
    wrong = restore_backup(outcome.ciphertext_path, outcome.receipt, wrong_staging,
                           runtime=runtime, recovery_identity=OneShotIdentity(other))
    assert wrong.state == "failed" and list(wrong_staging.iterdir()) == []


@needs_age
def test_corruption_interruption_and_receipt_mismatch_restore_nothing(runtime, tmp_path):
    outcome, _record, _vault, _out = backed_up(runtime, tmp_path)
    handle = BackupKeyHandle(tmp_path / "backup-key")
    ciphertext = outcome.ciphertext_path.read_bytes()

    def attempt(name, body, receipt):
        path = tmp_path / f"{name}.age"
        path.write_bytes(body)
        staging = tmp_path / f"staging-{name}"
        staging.mkdir()
        result = restore_backup(path, receipt, staging, runtime=runtime, key_handle=handle)
        assert result.state == "failed" and list(staging.iterdir()) == []
        return result.failure

    flipped = bytearray(ciphertext)
    flipped[len(flipped) // 2] ^= 0x40
    # the external receipt catches a changed file before any decryption
    assert "external receipt" in attempt("corrupt", bytes(flipped), outcome.receipt)
    truncated = ciphertext[: len(ciphertext) - 100]
    assert "external receipt" in attempt("cut", truncated, outcome.receipt)
    # a stream cut short whose receipt was forged to match still fails authentication
    import hashlib

    forged = {**outcome.receipt, "ciphertext_size": len(truncated),
              "ciphertext_sha256": hashlib.sha256(truncated).hexdigest()}
    assert "authenticate" in attempt("interrupted", truncated, forged)
    forged_flip = {**outcome.receipt, "ciphertext_size": len(flipped),
                   "ciphertext_sha256": hashlib.sha256(bytes(flipped)).hexdigest()}
    assert "authenticate" in attempt("tampered", bytes(flipped), forged_flip)
    assert "malformed" in attempt("noreceipt", ciphertext, {"backup_id": "x"})


@needs_age
def test_restore_never_overwrites_an_occupied_or_active_directory(runtime, tmp_path):
    outcome, _record, vault, _out = backed_up(runtime, tmp_path)
    handle = BackupKeyHandle(tmp_path / "backup-key")
    active = restore_backup(outcome.ciphertext_path, outcome.receipt, vault,
                            runtime=runtime, key_handle=handle, active_vault_dir=vault)
    assert active.state == "failed"
    empty_active = tmp_path / "fresh-active"
    empty_active.mkdir()
    refused = restore_backup(outcome.ciphertext_path, outcome.receipt, empty_active,
                             runtime=runtime, key_handle=handle, active_vault_dir=empty_active)
    assert refused.state == "failed" and "active vault" in refused.failure
    both = tmp_path / "both"
    both.mkdir()
    ambiguous = restore_backup(outcome.ciphertext_path, outcome.receipt, both, runtime=runtime,
                               key_handle=handle, recovery_identity=OneShotIdentity(b"x"))
    assert ambiguous.state == "failed" and "exactly one" in ambiguous.failure


@needs_age
def test_backup_key_init_with_the_real_keygen_is_idempotent_across_reruns(runtime, tmp_path):
    volume = tmp_path / "backup-key"
    volume.mkdir()
    first = initialize_backup_key(volume, keygen=age_keygen(runtime))
    identity = (volume / "identity.age").read_bytes()
    assert runtime.recipient_of(identity) == first.recipient
    for _rerun in range(2):  # stack-update reruns verify and never regenerate
        again = initialize_backup_key(volume, keygen=age_keygen(runtime))
        assert again.status == "verified" and again.recipient == first.recipient
    assert (volume / "identity.age").read_bytes() == identity


# --- originals: the content-addressed bytes the records name ----------------------------

ORIGINAL = "원본 PDF 대신 쓰는 합성 원본 바이트".encode() * 64


def vault_with_original(root: Path):
    domain, _record = populated_vault(root)
    roots = domain.roots()
    blob = domain.put_blob(ORIGINAL, purpose="operational")
    source = ImmutableRecord.create(
        kind="artifact", id=str(uuid4()), version=1, created_at_utc=STAMP, actor_ref=roots.actor,
        parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content={"original": {"blob": blob.as_dict()}})
    domain.put(source)
    return domain, source, blob


@needs_age
def test_originals_are_backed_up_and_restored_byte_for_byte(runtime, tmp_path):
    vault = tmp_path / "vault"
    _domain, source, blob = vault_with_original(vault)
    out = tmp_path / "out"
    out.mkdir()
    handle = instance_key(runtime, tmp_path)
    outcome = create_backup(vault, out, runtime=runtime, server_release="1.0.0",
                            key_mode="instance_backup_key", key_handle=handle)
    assert outcome.state == "ready", outcome.failure
    assert "original_bytes" in outcome.receipt["restore_verification_ref"]["scope"]
    paths = [item["path"] for item in outcome.manifest["item_refs"]]
    assert f"vault/domain-cas/operational/{blob.sha256}" in paths
    assert ORIGINAL not in outcome.ciphertext_path.read_bytes()  # encrypted, never in the clear
    staging = tmp_path / "staging"
    staging.mkdir()
    restored = restore_backup(outcome.ciphertext_path, outcome.receipt, staging, runtime=runtime,
                              key_handle=handle, active_vault_dir=vault)
    assert restored.state == "restored_review", restored.failure
    domain = DomainStore(Store(restored.vault_dir))
    assert domain.get(source.ref).ref == source.ref  # the lineage check reads the original too
    assert domain.read_blob(blob, purpose="operational") == ORIGINAL


@needs_age
def test_a_missing_or_altered_original_refuses_the_backup(runtime, tmp_path):
    vault = tmp_path / "vault"
    _domain, _source, blob = vault_with_original(vault)
    out = tmp_path / "out"
    out.mkdir()
    handle = instance_key(runtime, tmp_path)
    path = vault / "domain-cas" / "operational" / blob.sha256
    kept = path.read_bytes()
    os.chmod(path, 0o600)
    path.write_bytes(kept[:-1] + b"!")
    altered = create_backup(vault, out, runtime=runtime, server_release="1.0.0",
                            key_mode="instance_backup_key", key_handle=handle)
    assert altered.state == "failed" and "differs from its registered digest" in altered.failure
    path.unlink()
    missing = create_backup(vault, out, runtime=runtime, server_release="1.0.0",
                            key_mode="instance_backup_key", key_handle=handle)
    assert missing.state == "failed" and "missing" in missing.failure
    assert list(out.iterdir()) == []


@needs_age
def test_a_deleted_original_stays_deleted_through_backup_and_restore(runtime, tmp_path):
    from app.domain.store import ERASURE_KIND, ERASURE_SCHEMA, ErasedBlob, _writer, erasure_identity

    vault = tmp_path / "vault"
    domain, source, blob = vault_with_original(vault)
    roots = domain.roots()
    tombstone = ImmutableRecord.create(
        kind=ERASURE_KIND, id=erasure_identity(roots.genesis.id, blob.purpose, blob.sha256), version=1,
        created_at_utc=STAMP, actor_ref=roots.actor, parent_refs=(), purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content={"schema_version": ERASURE_SCHEMA, "blob_purpose": blob.purpose, "blob_sha256": blob.sha256,
                 "blob_size": blob.size, "object_id": source.ref.id, "former_kind": "original",
                 "deleted_at": STAMP, "deletion_request_id": str(uuid4()), "affected_refs": [source.ref.as_dict()],
                 "reason_code": "user_requested", "preview_sha256": "0" * 64})
    with _writer(), domain._connection(write=True) as db:
        domain._erase_in_transaction(db, blob, tombstone)
    assert domain.remove_erased_bytes(blob) is True
    out = tmp_path / "out"
    out.mkdir()
    handle = instance_key(runtime, tmp_path)
    outcome = create_backup(vault, out, runtime=runtime, server_release="1.0.0",
                            key_mode="instance_backup_key", key_handle=handle)
    assert outcome.state == "ready", outcome.failure
    assert not any(blob.sha256 in item["path"] for item in outcome.manifest["item_refs"])
    staging = tmp_path / "staging"
    staging.mkdir()
    restored = restore_backup(outcome.ciphertext_path, outcome.receipt, staging, runtime=runtime,
                              key_handle=handle, active_vault_dir=vault)
    assert restored.state == "restored_review", restored.failure
    again = DomainStore(Store(restored.vault_dir))
    assert again.get(source.ref).ref == source.ref
    with pytest.raises(ErasedBlob):
        again.read_blob(blob, purpose="operational")
