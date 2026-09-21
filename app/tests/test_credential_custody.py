"""Synthetic-only custody regressions; inspect only pytest-owned temporary files."""
from hashlib import sha256

from app.workers.credential_vault import CredentialVault
from app.tests.test_credential_root import initialized
from uuid import uuid4
import pytest
import multiprocessing
import os
import sqlite3
import threading
from contextlib import contextmanager


def counts(args):
    with sqlite3.connect(args["records_directory"] / "journal.sqlite") as db:
        return tuple(db.execute("SELECT count(*) FROM " + table).fetchone()[0] for table in ("commands", "nonces", "receipts"))


def metadata(**changes):
    return dict(command_id=str(uuid4()), record_id=str(uuid4()), record_version=1,
                provider="claude", auth_mode="api", created_at="2026-09-19T00:00:00.000000Z",
                predecessor=None) | changes


def test_actual_backend_persists_neither_plaintext_nor_plaintext_digest(tmp_path):
    secret = b"synthetic-task30-not-a-credential"
    with CredentialVault(**initialized(tmp_path)) as vault:
        receipt = vault.store_at(metadata=metadata(), secret=secret)
        assert receipt["state"] == "stored_unbound"
    persisted = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    assert secret not in persisted
    assert sha256(secret).hexdigest().encode() not in persisted


def test_replay_ignores_new_secret_and_retirement_survives_reopen(tmp_path):
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    with CredentialVault(**args) as vault:
        receipt = vault.store_at(metadata=meta, secret=b"original-synthetic")
        assert vault.store_at(metadata=meta, secret=object()) == receipt
        assert vault.query_record(metadata=meta) == receipt
        with pytest.raises(CredentialVaultError):
            vault.store_at(metadata=meta | {"provider": "codex"}, secret=b"changed")
        reference = {k: receipt[k] for k in ("record_id", "record_version", "ciphertext_sha256")}
        retired = vault.retire(command_id=str(uuid4()), record=reference, reason="owner_delete")
        assert retired["state"] == "cleanup_pending"
        assert vault.query_record(metadata=meta)["state"] == "cleanup_pending"
    with CredentialVault(**args) as vault:
        assert vault.query_record(metadata=meta)["state"] == "cleanup_pending"
        with pytest.raises(CredentialVaultError):
            vault.resolve_for_gateway(meta["record_id"])
        with pytest.raises(CredentialVaultError):
            vault.erase(meta["record_id"])


def _crash_store(args, meta, point):
    from app.workers.credential_root import CredentialRoot
    from app.workers.credential_files import Directory
    with CredentialVault(**args) as vault:
        def crash(*a, **k):
            os._exit(71)
        if point == "before_reservation":
            os.urandom = crash
        elif point == "after_reservation":
            CredentialRoot.seal = crash
        elif point == "after_staging":
            CredentialVault._publish = crash
        elif point == "mid_destination":
            original = Directory.write
            def partial(self, name, payload, mode=0o600):
                if name == "1.json":
                    fd = self.file(name, create=True, writable=True)
                    os.write(fd, payload[:31])
                    os.fsync(fd)
                    os._exit(71)
                return original(self, name, payload, mode)
            Directory.write = partial
        elif point == "after_publication":
            CredentialVault._commit_receipt = crash
        elif point == "after_receipt":
            original = CredentialVault._commit_receipt
            def committed(self, *a):
                original(self, *a)
                os._exit(71)
            CredentialVault._commit_receipt = committed
        vault.store_at(metadata=meta, secret=b"synthetic-crash-fixture")


@pytest.mark.parametrize("point,expected", [("before_reservation", "unknown"), ("after_reservation", "secret_input_lost"),
    ("after_staging", "stored_unbound"), ("mid_destination", "maintenance"), ("after_publication", "stored_unbound"), ("after_receipt", "stored_unbound")])
def test_process_crash_recovery_preserves_original_allocation(tmp_path, point, expected):
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    process = multiprocessing.get_context("spawn").Process(target=_crash_store, args=(args, meta, point))
    process.start()
    process.join(10)
    if process.is_alive():
        process.terminate()
        process.join(3)
        pytest.fail("owned crash helper exceeded deadline")
    assert process.exitcode == 71
    process.close()
    before = {p: p.read_bytes() for p in args["records_directory"].rglob("*.json")}
    if expected == "maintenance":
        with pytest.raises(CredentialVaultError):
            CredentialVault(**args)
        assert before == {p: p.read_bytes() for p in args["records_directory"].rglob("*.json")}
        assert counts(args) == (1, 1, 0)
    else:
        with CredentialVault(**args) as vault:
            queried = vault.query_record(metadata=meta)
            assert queried["state"] == expected
            if expected != "unknown":
                assert vault.store_at(metadata=meta, secret=object()) == queried
            else:
                assert queried["terminal"] is False
            expected_counts = (0, 0, 0) if expected == "unknown" else (1, 1, int(expected == "stored_unbound"))
            assert counts(args) == expected_counts
        assert all(path.read_bytes() == value for path, value in before.items())
    secret = b"synthetic-crash-fixture"
    for p in tmp_path.rglob("*"):
        if p.is_file():
            data = p.read_bytes()
            assert secret not in data
            assert sha256(secret).hexdigest().encode() not in data


def test_nonce_collision_exhaustion_is_bounded_and_survives_restart(tmp_path, monkeypatch):
    from app.workers.credential_vault import CredentialVaultError
    from app.workers import credential_vault
    args = initialized(tmp_path)
    first, second = metadata(), metadata()
    calls = []
    def constant_nonce(size):
        calls.append(size)
        return b"n" * size
    monkeypatch.setattr(credential_vault.os, "urandom", constant_nonce)
    with CredentialVault(**args) as vault:
        vault.store_at(metadata=first, secret=b"synthetic-first")
    with CredentialVault(**args) as vault:
        with pytest.raises(CredentialVaultError) as failure:
            vault.store_at(metadata=second, secret=b"synthetic-second")
        assert failure.value.code == "nonce_exhausted"
    assert calls == [24] * 9
    assert counts(args) == (1, 1, 1)


@pytest.mark.parametrize("limit", ["MAX_COMMANDS", "MAX_RECORDS", "MAX_NONCES"])
def test_capacity_precedes_secret_validation_and_preserves_replay(tmp_path, monkeypatch, limit):
    from app.workers import credential_journal
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    with CredentialVault(**args) as vault:
        receipt = vault.store_at(metadata=meta, secret=b"synthetic")
        monkeypatch.setattr(credential_journal, limit, 1)
        with pytest.raises(CredentialVaultError) as failure:
            vault.store_at(metadata=metadata(), secret_b64u="invalid encoding")
        assert failure.value.code == "capacity_exhausted"
        assert vault.store_at(metadata=meta, secret=object()) == receipt
        assert counts(args) == (1, 1, 1)


def test_query_before_accepted_store_acquires_lock_is_nonterminal_unknown(tmp_path, monkeypatch):
    args, meta = initialized(tmp_path), metadata()
    accepted, resume = threading.Event(), threading.Event()
    original = CredentialVault._operation
    @contextmanager
    def delayed(self, **kwargs):
        if threading.current_thread().name == "delayed-store":
            accepted.set()
            assert resume.wait(5)
        with original(self, **kwargs) as journal:
            yield journal
    with CredentialVault(**args) as vault:
        monkeypatch.setattr(CredentialVault, "_operation", delayed)
        result, errors = [], []
        def store():
            try:
                result.append(vault.store_at(metadata=meta, secret=b"synthetic-delayed"))
            except BaseException as exc:
                errors.append(exc)
        thread = threading.Thread(target=store, name="delayed-store")
        thread.start()
        try:
            assert accepted.wait(3)
            assert vault.query_record(metadata=meta) == {"command_id": meta["command_id"], "state": "unknown", "terminal": False}
        finally:
            resume.set()
            thread.join(5)
        assert not thread.is_alive() and not errors
        assert vault.query_record(metadata=meta) == result[0]


def _process_store(args, meta, start, output):
    try:
        with CredentialVault(**args) as vault:
            start.wait(5)
            output.put(vault.store_at(metadata=meta, secret=b"synthetic-process"))
    except Exception as exc:
        output.put({"error": type(exc).__name__})


@pytest.mark.parametrize("same_command", [True, False])
def test_independent_process_command_and_nonce_races(tmp_path, same_command):
    args = initialized(tmp_path)
    context = multiprocessing.get_context("spawn")
    start, output = context.Event(), context.Queue()
    shared = metadata()
    metas = [shared if same_command else metadata() for _ in range(4)]
    children = [context.Process(target=_process_store, args=(args, meta, start, output)) for meta in metas]
    for child in children:
        child.start()
    start.set()
    try:
        results = [output.get(timeout=15) for _ in children]
        assert all(item.get("state") == "stored_unbound" for item in results), results
        expected = 1 if same_command else 4
        assert len({item["record_id"] for item in results}) == expected
        assert counts(args) == (expected, expected, expected)
    finally:
        for child in children:
            child.join(5)
            if child.is_alive():
                child.terminate()
                child.join(3)
            assert child.exitcode == 0
            child.close()
        output.close()
        output.join_thread()


def _hold_mutation(args, ready, release):
    from app.workers.credential_files import Directory, exclusion
    with Directory(args["records_directory"], args["expected_uid"], args["expected_gid"]) as directory:
        with exclusion(directory, "mutation.lock"):
            ready.set()
            release.wait(10)


def test_independent_process_mutation_lock_is_bounded_busy(tmp_path):
    from app.workers.credential_vault import CredentialVaultError
    import time
    args = initialized(tmp_path)
    context = multiprocessing.get_context("spawn")
    ready, release = context.Event(), context.Event()
    with CredentialVault(**args) as vault:
        child = context.Process(target=_hold_mutation, args=(args, ready, release))
        child.start()
        try:
            assert ready.wait(5)
            start = time.monotonic()
            with pytest.raises(CredentialVaultError) as failure:
                vault.query_record(metadata=metadata())
            assert failure.value.code == "busy"
            assert 4.9 <= time.monotonic() - start < 5.5
        finally:
            release.set()
            child.join(5)
            if child.is_alive():
                child.terminate()
                child.join(3)
            assert child.exitcode == 0
            child.close()


def test_query_and_replay_do_not_decrypt_or_encrypt(tmp_path, monkeypatch):
    from app.workers.credential_root import CredentialRoot
    with CredentialVault(**initialized(tmp_path)) as vault:
        meta = metadata()
        receipt = vault.store_at(metadata=meta, secret=b"synthetic")
        def forbidden(*args, **kwargs):
            raise AssertionError("query/replay touched cryptography")
        monkeypatch.setattr(CredentialRoot, "open", forbidden)
        monkeypatch.setattr(CredentialRoot, "seal", forbidden)
        assert vault.query_record(metadata=meta) == receipt
        assert vault.store_at(metadata=meta, secret=object()) == receipt


def test_short_writes_are_completed_without_plaintext_files(tmp_path, monkeypatch):
    from app.workers import credential_files
    args, meta = initialized(tmp_path), metadata()
    original = os.write
    writes = []
    def short(fd, data):
        writes.append(len(data))
        return original(fd, data[:7])
    monkeypatch.setattr(credential_files.os, "write", short)
    with CredentialVault(**args) as vault:
        result = vault.store_at(metadata=meta, secret=b"synthetic-short-write")
        assert vault.query_record(metadata=meta) == result
        assert vault._root.open(vault._published(meta), meta) == b"synthetic-short-write"
    assert len(writes) > 10


def test_pending_replay_never_uses_new_ingress(tmp_path, monkeypatch):
    from app.workers.credential_root import CredentialRoot
    args, meta = initialized(tmp_path), metadata()
    with CredentialVault(**args) as vault:
        def failed(*args):
            raise OSError("synthetic injected encryption failure")
        monkeypatch.setattr(CredentialRoot, "seal", failed)
        from app.workers.credential_vault import CredentialVaultError
        with pytest.raises(CredentialVaultError):
            vault.store_at(metadata=meta, secret=b"synthetic")
        assert vault.query_record(metadata=meta)["state"] == "pending"
        assert vault.store_at(metadata=meta, secret=object())["state"] == "pending"
        assert counts(args) == (1, 1, 0)


def test_unique_staging_recovery_uses_existing_capacity_allocation(tmp_path, monkeypatch):
    from app.workers import credential_journal
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    original = CredentialVault._publish
    with CredentialVault(**args) as vault:
        def failed(*args):
            raise OSError("synthetic prepublication failure")
        monkeypatch.setattr(CredentialVault, "_publish", failed)
        with pytest.raises(CredentialVaultError):
            vault.store_at(metadata=meta, secret=b"synthetic")
    monkeypatch.setattr(CredentialVault, "_publish", original)
    monkeypatch.setattr(credential_journal, "MAX_COMMANDS", 1)
    monkeypatch.setattr(credential_journal, "MAX_RECORDS", 1)
    monkeypatch.setattr(credential_journal, "MAX_NONCES", 1)
    with CredentialVault(**args) as vault:
        assert vault.query_record(metadata=meta)["state"] == "stored_unbound"
    assert counts(args) == (1, 1, 1)


def test_swapped_staging_command_identity_fails_closed(tmp_path):
    from app.workers.credential_vault import CredentialVaultError
    args, first, second = initialized(tmp_path), metadata(), metadata()
    with CredentialVault(**args) as vault:
        vault.store_at(metadata=first, secret=b"synthetic-first")
        vault.store_at(metadata=second, secret=b"synthetic-second")
    stages = args["records_directory"] / "staging"
    first_file = stages / (first["command_id"] + ".json")
    second_file = stages / (second["command_id"] + ".json")
    first_file.write_bytes(second_file.read_bytes())
    with pytest.raises(CredentialVaultError):
        CredentialVault(**args)


def test_corrupt_receipt_cannot_be_projected_after_open(tmp_path):
    import json
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    with CredentialVault(**args) as vault:
        receipt = vault.store_at(metadata=meta, secret=b"synthetic")
        with sqlite3.connect(args["records_directory"] / "journal.sqlite") as db:
            db.execute("UPDATE receipts SET body=?", (json.dumps(receipt | {"extra": "untrusted"}, sort_keys=True, separators=(",", ":")).encode(),))
        with pytest.raises(CredentialVaultError):
            vault.query_record(metadata=meta)


def test_unknown_journal_table_fails_closed_without_repair(tmp_path):
    from app.workers.credential_vault import CredentialVaultError
    args = initialized(tmp_path)
    with sqlite3.connect(args["records_directory"] / "journal.sqlite") as db:
        db.execute("CREATE TABLE unexplained (value TEXT)")
    before = (args["records_directory"] / "journal.sqlite").read_bytes()
    with pytest.raises(CredentialVaultError):
        CredentialVault(**args)
    assert (args["records_directory"] / "journal.sqlite").read_bytes() == before


def test_unexpected_staging_copy_is_not_misreported_as_ingress_loss(tmp_path, monkeypatch):
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    original = CredentialVault._publish
    with CredentialVault(**args) as vault:
        def failed(*args):
            raise OSError("synthetic interruption")
        monkeypatch.setattr(CredentialVault, "_publish", failed)
        with pytest.raises(CredentialVaultError):
            vault.store_at(metadata=meta, secret=b"synthetic")
    monkeypatch.setattr(CredentialVault, "_publish", original)
    stage = args["records_directory"] / "staging"
    (stage / (meta["command_id"] + ".json")).rename(stage / "unexpected.json")
    before = (stage / "unexpected.json").read_bytes()
    with pytest.raises(CredentialVaultError):
        CredentialVault(**args)
    with sqlite3.connect(args["records_directory"] / "journal.sqlite") as db:
        assert db.execute("SELECT state FROM commands").fetchone()[0] == "pending"
    assert (stage / "unexpected.json").read_bytes() == before


def test_authenticated_orphan_without_burned_nonce_history_requires_maintenance(tmp_path):
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    with CredentialVault(**args) as vault:
        payload = vault._root.seal(meta, b"synthetic-untracked-orphan", b"z" * 24)
    orphan = args["records_directory"] / "staging" / "unexpected.json"
    orphan.write_bytes(payload)
    orphan.chmod(0o600)
    with pytest.raises(CredentialVaultError) as failure:
        CredentialVault(**args)
    assert failure.value.code == "maintenance_required"
    assert orphan.read_bytes() == payload
    assert counts(args) == (0, 0, 0)


def recovery_inventory(args):
    """Capture exact journal and ciphertext inventory of this test-owned volume."""
    directory = args["records_directory"]
    with sqlite3.connect(directory / "journal.sqlite") as db:
        journal_rows = tuple(tuple(db.execute("SELECT * FROM " + name + " ORDER BY 1"))
                             for name in ("commands", "nonces", "receipts", "retirements"))
    return ({str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}, journal_rows)


@pytest.mark.parametrize("retired", [False, True])
def test_receipted_missing_destination_restores_exact_stage_without_state_change(tmp_path, retired):
    args, meta = initialized(tmp_path), metadata()
    with CredentialVault(**args) as vault:
        receipt = vault.store_at(metadata=meta, secret=b"synthetic-receipted")
        if retired:
            ref = {k: receipt[k] for k in ("record_id", "record_version", "ciphertext_sha256")}
            vault.retire(command_id=str(uuid4()), record=ref, reason="owner_delete")
        effective = vault.query_record(metadata=meta)
        destination = next(args["records_directory"].glob("generations/*/records/" + meta["record_id"] + "/1.json"))
        ciphertext = destination.read_bytes()
    destination.unlink()
    journal_before = (args["records_directory"] / "journal.sqlite").read_bytes()
    rows_before = recovery_inventory(args)[1]
    with CredentialVault(**args) as vault:
        assert vault.query_record(metadata=meta) == effective
        assert destination.read_bytes() == ciphertext
        assert vault.store_at(metadata=meta, secret=object()) == effective
        from app.workers.credential_vault import CredentialVaultError
        with pytest.raises(CredentialVaultError):
            vault.resolve_for_gateway(meta["record_id"])
    assert (args["records_directory"] / "journal.sqlite").read_bytes() == journal_before
    assert recovery_inventory(args)[1] == rows_before
    assert counts(args) == (1, 1, 1)


@pytest.mark.parametrize("damage", ["missing", "corrupt", "ambiguous", "receipt_mismatch"])
def test_receipted_missing_destination_without_unique_valid_stage_preserves_state(tmp_path, damage):
    from app.workers.credential_vault import CredentialVaultError
    args, meta = initialized(tmp_path), metadata()
    with CredentialVault(**args) as vault:
        receipt = vault.store_at(metadata=meta, secret=b"synthetic-receipted")
        destination = next(args["records_directory"].glob("generations/*/records/" + meta["record_id"] + "/1.json"))
        stage = args["records_directory"] / "staging" / (meta["command_id"] + ".json")
        if damage == "receipt_mismatch":
            from app.workers.credential_envelope import decode
            _, nonce, _ = decode(stage.read_bytes())
            stage.write_bytes(vault._root.seal(meta, b"different-synthetic-copy", nonce))
    destination.unlink()
    if damage == "missing":
        stage.unlink()
    elif damage == "corrupt":
        stage.write_bytes(b"partial")
    elif damage == "ambiguous":
        duplicate = stage.parent / "unexpected.json"
        duplicate.write_bytes(stage.read_bytes())
        duplicate.chmod(0o600)
    before = recovery_inventory(args)
    with pytest.raises(CredentialVaultError):
        CredentialVault(**args)
    assert recovery_inventory(args) == before
    assert not destination.exists()
    assert counts(args) == (1, 1, 1)


@pytest.mark.parametrize("damage", ["unknown_nonce", "malformed_stage", "malformed_destination", "bad_receipt", "ambiguous_stage"])
def test_global_recovery_preflight_leaves_all_pending_work_unchanged(tmp_path, monkeypatch, damage):
    import json
    from app.workers.credential_vault import CredentialVaultError
    args = initialized(tmp_path)
    recoverable, genuinely_lost, other = metadata(), metadata(), metadata()
    original = CredentialVault._publish
    with CredentialVault(**args) as vault:
        def interrupted(*args):
            raise OSError("synthetic interruption after staging")
        monkeypatch.setattr(CredentialVault, "_publish", interrupted)
        for meta in (recoverable, genuinely_lost):
            with pytest.raises(CredentialVaultError):
                vault.store_at(metadata=meta, secret=b"synthetic-pending")
        monkeypatch.setattr(CredentialVault, "_publish", original)
        receipt = vault.store_at(metadata=other, secret=b"synthetic-other")
        orphan_payload = vault._root.seal(metadata(), b"synthetic-untracked", b"q" * 24)
    stages = args["records_directory"] / "staging"
    (stages / (genuinely_lost["command_id"] + ".json")).unlink()
    if damage in ("unknown_nonce", "malformed_stage", "ambiguous_stage"):
        unexpected = stages / "unexpected.json"
        unexpected.write_bytes(orphan_payload if damage == "unknown_nonce" else
            b"corrupt" if damage == "malformed_stage" else (stages / (recoverable["command_id"] + ".json")).read_bytes())
        unexpected.chmod(0o600)
    elif damage == "malformed_destination":
        path = next(args["records_directory"].glob("generations/*/records/" + other["record_id"] + "/1.json"))
        path.write_bytes(b"corrupt")
    else:
        with sqlite3.connect(args["records_directory"] / "journal.sqlite") as db:
            changed = receipt | {"ciphertext_sha256": "0" * 64}
            db.execute("UPDATE receipts SET body=? WHERE command_id=?", (
                json.dumps(changed, sort_keys=True, separators=(",", ":")).encode(), other["command_id"]))
    before = recovery_inventory(args)
    with pytest.raises(CredentialVaultError):
        CredentialVault(**args)
    assert recovery_inventory(args) == before
    assert counts(args) == (3, 3, 1)
