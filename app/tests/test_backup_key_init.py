"""T023 tail / OPS-AC07: the backup-key-init job
(operations.md §2 line "모든 *-root-init/backup-key-init job", §5 backup keys).

The job initializes the deployment's separate `backup-key` volume with the
fixed age-x25519-v1 identity: on ABSENT storage it creates the identity
and its manifest with O_EXCL and fsync; on the EXACT valid existing state
it verify-only no-ops (stack-update reruns are idempotent); ANY malformed
state — partial files, corrupt manifest, hash mismatch, wrong profile or
mode, loose permissions, symlinks — fails WITHOUT replacing anything (a
silent regeneration would orphan every existing backup). The key
generator is injected (production owns age-keygen inside the networkless
worker); the secret identity never appears in results or errors.
"""

import json
import os
import stat

import pytest

from app.operations.backup_key import (
    BackupKeyInitError,
    initialize_backup_key,
)

IDENTITY = "AGE-SECRET-KEY-1TESTTESTTESTTESTTESTTESTTESTTESTTESTTESTTESTTESTTESTTEST"
RECIPIENT = "age1testrecipienttestrecipienttestrecipienttestrecipient"


def keygen():
    return {"identity": IDENTITY, "recipient": RECIPIENT}


def run(root, generator=keygen):
    return initialize_backup_key(
        root, keygen=generator, clock=lambda: "2026-09-13T00:00:00+00:00",
    )


def snapshot(root):
    return {
        path.name: (path.read_bytes(), path.lstat().st_mtime_ns)
        for path in sorted(root.iterdir())
    }


def test_absent_storage_creates_identity_and_manifest(tmp_path):
    result = run(tmp_path)
    assert result.status == "created"
    assert result.recipient == RECIPIENT
    identity = tmp_path / "identity.age"
    manifest = tmp_path / "manifest.json"
    assert identity.read_text() == IDENTITY + "\n"
    assert stat.S_IMODE(identity.lstat().st_mode) == 0o600
    body = json.loads(manifest.read_text())
    assert body["schema_version"] == 1
    assert body["job"] == "backup-key-init"
    assert body["key_mode"] == "instance_backup_key"
    assert body["encryption_profile_ref"] == "age-x25519-v1"
    assert body["recipient"] == RECIPIENT
    assert body["created_at"] == "2026-09-13T00:00:00+00:00"
    assert body["identity_sha256"] == result.identity_sha256
    # the secret never leaks through the result value
    assert IDENTITY not in repr(result)


def test_a_stack_update_rerun_is_verify_only(tmp_path):
    run(tmp_path)
    before = snapshot(tmp_path)

    def poisoned():
        raise AssertionError("a rerun must never generate a new key")

    result = initialize_backup_key(
        tmp_path, keygen=poisoned, clock=lambda: "2026-09-14T00:00:00+00:00",
    )
    assert result.status == "verified"
    assert result.recipient == RECIPIENT
    assert snapshot(tmp_path) == before  # bytes AND mtimes untouched


@pytest.mark.parametrize("damage", [
    lambda root: (root / "manifest.json").write_text("{not json"),
    lambda root: (root / "manifest.json").unlink(),
    lambda root: (root / "identity.age").unlink(),
    lambda root: (root / "identity.age").write_text("AGE-SECRET-KEY-1TAMPERED\n"),
    lambda root: (root / "identity.age").chmod(0o644),
])
def test_malformed_state_fails_without_replace(tmp_path, damage):
    run(tmp_path)
    damage(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(BackupKeyInitError) as caught:
        run(tmp_path)
    assert snapshot(tmp_path) == before  # nothing repaired, nothing replaced
    assert IDENTITY not in str(caught.value)


@pytest.mark.parametrize("change", [
    {"encryption_profile_ref": "custom-crypto-v9"},
    {"key_mode": "portable_recovery"},
    {"schema_version": 2},
    {"job": "vault-init"},
])
def test_a_foreign_manifest_never_verifies(tmp_path, change):
    run(tmp_path)
    manifest = tmp_path / "manifest.json"
    body = json.loads(manifest.read_text())
    body.update(change)
    manifest.write_text(json.dumps(body))
    with pytest.raises(BackupKeyInitError):
        run(tmp_path)


def test_symlinked_storage_refuses(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "volume"
    link.symlink_to(real)
    with pytest.raises(BackupKeyInitError):
        run(link)
    run(real)
    (real / "identity.age").unlink()
    (real / "identity.age").symlink_to(real / "manifest.json")
    with pytest.raises(BackupKeyInitError):
        run(real)


@pytest.mark.parametrize("generated", [
    {"identity": "not-an-age-key", "recipient": RECIPIENT},
    {"identity": IDENTITY + "\nsecond-line", "recipient": RECIPIENT},
    {"identity": IDENTITY, "recipient": "https://example.invalid"},
    {"identity": "", "recipient": RECIPIENT},
    {"recipient": RECIPIENT},
    "not-a-dict",
])
def test_keygen_output_is_validated_before_any_write(tmp_path, generated):
    with pytest.raises(BackupKeyInitError):
        run(tmp_path, generator=lambda: generated)
    assert list(tmp_path.iterdir()) == []  # nothing half-written


def test_a_missing_volume_is_not_created(tmp_path):
    with pytest.raises(BackupKeyInitError):
        run(tmp_path / "never-mounted")
    assert not (tmp_path / "never-mounted").exists()


def test_created_files_survive_reopen_with_exclusive_semantics(tmp_path):
    run(tmp_path)
    # O_EXCL against the now-existing identity must refuse at the OS level
    with pytest.raises(FileExistsError):
        os.open(tmp_path / "identity.age",
                os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
