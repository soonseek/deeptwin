"""Initial encrypted custody lifecycle; no activation or erasure qualification."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import sqlite3
from uuid import uuid4

import pytest

from app.tests.test_credential_root import initialized
from app.tests.test_credential_custody import metadata
from app.workers.credential_vault import CredentialVault, CredentialVaultError


@pytest.fixture
def subject(tmp_path):
    args = initialized(tmp_path)
    with CredentialVault(**args) as vault:
        yield args, vault


def test_rotation_candidate_does_not_retire_predecessor(subject):
    _, vault = subject
    first_meta = metadata()
    first = vault.store_at(metadata=first_meta, secret=b"synthetic-first")
    ref = {k: first[k] for k in ("record_id", "record_version", "ciphertext_sha256")}
    second = vault.store_at(metadata=metadata(predecessor=ref), secret=b"synthetic-second")
    assert second["record_id"] != first["record_id"]
    assert vault.query_record(metadata=first_meta) == first
    assert vault.health()["stored_unbound"] == 2
    for record in (first, second):
        with pytest.raises(CredentialVaultError):
            vault.resolve_for_gateway(record["record_id"])


@pytest.mark.parametrize("secret", ["not-bytes", b"", b"x" * 65537, b"\xff", b"line1\nline2", b"sk\rtoken", b"sk\x00token", b"sk\x7ftoken"])
def test_input_bounds_fail_before_persistence(subject, secret):
    args, vault = subject
    with pytest.raises(CredentialVaultError) as failure:
        vault.store_at(metadata=metadata(), secret=secret)
    assert "token" not in str(failure.value)
    assert vault.snapshot() == []
    with sqlite3.connect(args["records_directory"] / "journal.sqlite") as db:
        assert db.execute("SELECT count(*) FROM nonces").fetchone()[0] == 0


def test_retirement_replay_is_exact_and_bytes_remain(subject):
    args, vault = subject
    meta = metadata()
    receipt = vault.store_at(metadata=meta, secret=b"synthetic-retired")
    command = str(uuid4())
    ref = {k: receipt[k] for k in ("record_id", "record_version", "ciphertext_sha256")}
    before = {p: p.read_bytes() for p in args["records_directory"].rglob("*.json")}
    result = vault.retire(command_id=command, record=ref, reason="owner_delete")
    assert vault.retire(command_id=command, record=ref, reason="owner_delete") == result
    with pytest.raises(CredentialVaultError):
        vault.retire(command_id=command, record=ref, reason="superseded")
    with pytest.raises(CredentialVaultError):
        vault.erase(ref["record_id"])
    assert before == {p: p.read_bytes() for p in args["records_directory"].rglob("*.json")}
    assert vault.store_at(metadata=meta, secret=object())["state"] == "cleanup_pending"


def test_retained_orphan_is_quarantined_and_missing_record_is_restored(subject):
    args, vault = subject
    a, b = metadata(), metadata()
    vault.store_at(metadata=a, secret=b"synthetic-a")
    vault.store_at(metadata=b, secret=b"synthetic-b")
    stages = args["records_directory"] / "staging"
    orphan = stages / "unexpected.json"
    orphan.write_bytes((stages / (a["command_id"] + ".json")).read_bytes())
    orphan.chmod(0o600)
    record_path = next(args["records_directory"].glob("generations/*/records/" + b["record_id"] + "/1.json"))
    record_path.unlink()
    with CredentialVault(**args) as reopened:
        assert reopened.health()["quarantined"] == 1
        assert reopened.query_record(metadata=b)["state"] == "stored_unbound"
        assert reopened.query_record(metadata=a)["state"] == "stored_unbound"
        assert orphan.exists()
        assert record_path.read_bytes() == (stages / (b["command_id"] + ".json")).read_bytes()


def test_concurrent_stores_and_replays_do_not_lose_or_alias_records(subject):
    args, vault = subject
    metas = [metadata() for _ in range(40)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        receipts = list(pool.map(lambda meta: vault.store_at(metadata=meta, secret=b"synthetic-thread"), metas))
    assert len({receipt["record_id"] for receipt in receipts}) == 40
    with ThreadPoolExecutor(max_workers=8) as pool:
        replays = list(pool.map(lambda _: vault.store_at(metadata=metas[0], secret=object()), range(16)))
    assert all(receipt == receipts[0] for receipt in replays)
    with CredentialVault(**args) as reopened:
        assert reopened.health()["stored_unbound"] == 40


def test_closed_vault_releases_descriptors_and_rejects_operations(subject):
    _, vault = subject
    vault.close()
    with pytest.raises(CredentialVaultError) as failure:
        vault.query_record(metadata=metadata())
    assert failure.value.code == "closed"
