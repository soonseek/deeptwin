"""T090 credential-vault core: opaque handles, staged commits, verified erasure.

The vault is a gateway-side component (`credential-vault-port-v1`): the control plane
never imports it, secrets stay opaque behind handles, an intent id deduplicates
store/rotate, retirement gates resolution, and `erasure_completed` is reported only
after every locally managed copy (active, superseded, staging) is verifiably gone.
"""

import json
import os

import pytest

from app.workers.credential_vault import (
    CredentialVault,
    CredentialVaultError,
)

PROVIDER = "claude"
INTENT_A = "00000000-0000-4000-8000-00000000aa01"
INTENT_B = "00000000-0000-4000-8000-00000000aa02"
INTENT_C = "00000000-0000-4000-8000-00000000aa03"
SECRET = b"sk-test-0123456789"
ROTATED = b"sk-test-rotated-999"


@pytest.fixture
def vault(tmp_path):
    return CredentialVault(str(tmp_path / "vault"))


def test_store_resolve_lifecycle_with_opaque_handles(vault):
    record = vault.store(INTENT_A, PROVIDER, SECRET)
    assert record.provider == PROVIDER
    assert record.state == "active"
    handle = record.handle
    assert SECRET.decode() not in handle
    assert SECRET.decode() not in repr(record)
    assert vault.resolve_for_gateway(handle) == SECRET
    health = vault.health()
    assert health["active"] == 1
    assert "store" in vault.capabilities()["operations"]
    assert "resolve_for_gateway" in vault.capabilities()["operations"]


def test_store_is_idempotent_by_intent_id(vault):
    first = vault.store(INTENT_A, PROVIDER, SECRET)
    replay = vault.store(INTENT_A, PROVIDER, SECRET)
    assert replay.handle == first.handle
    # A replayed intent with different bytes is a conflict, not a new record.
    with pytest.raises(CredentialVaultError):
        vault.store(INTENT_A, PROVIDER, b"sk-different")
    assert vault.health()["active"] == 1


def test_rotation_supersedes_and_invalidates_the_predecessor(vault):
    first = vault.store(INTENT_A, PROVIDER, SECRET)
    second = vault.store(INTENT_B, PROVIDER, ROTATED, rotate_from=first.handle)
    assert second.handle != first.handle
    assert vault.resolve_for_gateway(second.handle) == ROTATED
    with pytest.raises(CredentialVaultError):
        vault.resolve_for_gateway(first.handle)
    states = vault.health()
    assert states["active"] == 1
    assert states["cleanup_pending"] == 1


def test_retire_blocks_resolution_and_erase_requires_verified_removal(vault):
    record = vault.store(INTENT_A, PROVIDER, SECRET)
    vault.retire(record.handle)
    with pytest.raises(CredentialVaultError):
        vault.resolve_for_gateway(record.handle)
    assert vault.health()["cleanup_pending"] == 1

    outcome = vault.erase(record.handle)
    assert outcome == "erasure_completed"
    assert vault.health()["cleanup_pending"] == 0
    # No secret bytes remain anywhere under the vault directory.
    for base, _dirs, files in os.walk(vault.root):
        for name in files:
            with open(os.path.join(base, name), "rb") as stream:
                assert SECRET not in stream.read()


def test_erase_of_a_rotated_predecessor_completes_cleanup(vault):
    first = vault.store(INTENT_A, PROVIDER, SECRET)
    vault.store(INTENT_B, PROVIDER, ROTATED, rotate_from=first.handle)
    assert vault.erase(first.handle) == "erasure_completed"
    assert vault.health() == {
        "active": 1, "cleanup_pending": 0, "secret_input_lost": 0,
    }


def test_restart_reconciliation_cleans_staging_and_marks_lost_intents(tmp_path):
    root = str(tmp_path / "vault")
    vault = CredentialVault(root)
    record = vault.store(INTENT_A, PROVIDER, SECRET)

    # A crash leaves a staging file and a committed intent without its secret.
    staging = os.path.join(root, "staging-orphan")
    with open(staging, "wb") as stream:
        stream.write(b"sk-orphaned-secret")
    lost = vault.store(INTENT_B, PROVIDER, ROTATED)
    os.unlink(os.path.join(root, "secrets", lost.handle))

    reopened = CredentialVault(root)
    assert not os.path.exists(staging)
    assert reopened.resolve_for_gateway(record.handle) == SECRET
    with pytest.raises(CredentialVaultError):
        reopened.resolve_for_gateway(lost.handle)
    health = reopened.health()
    assert health["secret_input_lost"] == 1
    assert health["active"] == 1


def test_bounds_and_foreign_inputs_fail_before_any_effect(vault):
    for intent, provider, secret in (
        ("not-a-uuid", PROVIDER, SECRET),
        (INTENT_A, "Bad Provider!", SECRET),
        (INTENT_A, PROVIDER, "not-bytes"),
        (INTENT_A, PROVIDER, b""),
        (INTENT_A, PROVIDER, b"x" * 65_537),
        (INTENT_A, PROVIDER, b"\xff\xfe raw-bytes"),  # not UTF-8
    ):
        with pytest.raises(CredentialVaultError):
            vault.store(intent, provider, secret)
    assert vault.health() == {
        "active": 0, "cleanup_pending": 0, "secret_input_lost": 0,
    }
    with pytest.raises(CredentialVaultError):
        vault.store(INTENT_A, PROVIDER, SECRET, rotate_from="unknown-handle")
    with pytest.raises(CredentialVaultError):
        vault.resolve_for_gateway("unknown-handle")
    with pytest.raises(CredentialVaultError):
        vault.retire("unknown-handle")
    with pytest.raises(CredentialVaultError):
        vault.erase("unknown-handle")


def test_errors_never_leak_secret_bytes(vault):
    vault.store(INTENT_A, PROVIDER, SECRET)
    try:
        vault.store(INTENT_A, PROVIDER, b"sk-second-secret-value")
    except CredentialVaultError as exc:
        message = str(exc)
        assert "sk-second-secret-value" not in message
        assert SECRET.decode() not in message


def test_metadata_on_disk_never_contains_secret_bytes(vault, tmp_path):
    vault.store(INTENT_A, PROVIDER, SECRET)
    index_path = os.path.join(vault.root, "index.json")
    with open(index_path, "rb") as stream:
        index = stream.read()
    assert SECRET not in index
    parsed = json.loads(index)
    assert type(parsed) is dict
