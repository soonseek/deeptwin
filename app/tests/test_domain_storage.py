"""Real temporary SQLite/filesystem tests; no user database or external calls."""

from contextlib import contextmanager
from hashlib import sha256
import importlib
import os
from pathlib import Path
import sqlite3
import stat
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.domain.schemas import ImmutableRecord
from app.storage import StorageIntegrityError, Store


STAMP = "2026-09-07T00:00:00.000000Z"


def api():
    if importlib.util.find_spec("app.domain.store") is None:
        pytest.fail("Missing additive DomainStore implementation")
    return importlib.import_module("app.domain.store")


def opened(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = module.DomainStore(legacy)
    roots = domain.initialize_vault()
    return module, legacy, domain, roots


def record(roots, *, identity=None, version=1, parents=(), content=None,
           purpose="operational", kind="work_model"):
    return ImmutableRecord.create(kind=kind, id=identity or str(uuid4()), version=version,
        created_at_utc=STAMP, actor_ref=roots.actor, parent_refs=parents, purpose=purpose,
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content={} if content is None else content)


def counts(legacy):
    with sqlite3.connect(legacy.path) as db:
        return {name: db.execute(f"SELECT count(*) FROM {name}").fetchone()[0]
                for name in ("domain_vault", "domain_records", "domain_edges", "domain_blobs")}


def test_additive_initialization_preserves_legacy_rows_and_exact_file_bytes(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work("이전 원본")
    added = legacy.add_file(work["id"], "original.txt", b"original\x00bytes", "text/plain")
    before = (legacy.get_work(work["id"]), legacy.get_revision(work["id"], 1),
              legacy.get_revision(work["id"], 2), legacy.read_file(work["id"], added["id"]),
              legacy.events())
    domain = module.DomainStore(legacy)
    roots = domain.initialize_vault()
    assert domain.path == legacy.path
    assert (legacy.get_work(work["id"]), legacy.get_revision(work["id"], 1),
            legacy.get_revision(work["id"], 2), legacy.read_file(work["id"], added["id"]),
            legacy.events()) == before
    assert roots.genesis.id == domain.vault_id
    assert len({roots.genesis, roots.actor, roots.access_policy, roots.retention_policy}) == 4
    for ref in (roots.actor, roots.access_policy, roots.retention_policy):
        assert domain.get(ref).body["genesis_ref"] == roots.genesis.as_dict()
    assert counts(legacy)["domain_records"] == 4


def test_empty_domain_requires_explicit_host_initialization(tmp_path):
    module = api()
    domain = module.DomainStore(Store(tmp_path / "vault"))
    with pytest.raises(module.UninitializedVault):
        domain.roots()


def test_initialization_is_one_time_and_reopen_keeps_exact_roots(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    with pytest.raises(module.AlreadyInitialized):
        domain.initialize_vault()
    assert module.DomainStore(legacy).roots() == roots
    assert counts(legacy)["domain_records"] == 4


def test_initialization_failure_rolls_back_all_four_roots(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = module.DomainStore(legacy)
    with sqlite3.connect(legacy.path) as db:
        db.execute("CREATE TRIGGER reject_retention BEFORE INSERT ON domain_records "
                   "WHEN NEW.kind = 'retention_policy' BEGIN SELECT RAISE(ABORT,'fixture'); END")
    with pytest.raises(sqlite3.DatabaseError):
        domain.initialize_vault()
    assert counts(legacy) == dict(domain_vault=0, domain_records=0, domain_edges=0, domain_blobs=0)
    with pytest.raises(module.UninitializedVault):
        domain.roots()


def test_import_and_normal_put_cannot_install_or_replace_bootstrap(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    for root in (domain.get(roots.genesis), domain.get(roots.actor),
                 ImmutableRecord.genesis(vault_id=str(uuid4()), created_at_utc=STAMP)):
        with pytest.raises(module.BootstrapDenied):
            domain.put(root)
    assert counts(legacy)["domain_records"] == 4


def test_records_roundtrip_and_idempotent_exact_put(tmp_path):
    _, legacy, domain, roots = opened(tmp_path)
    item = record(roots, content={"text": "보존", "amount": "0.10"})
    assert domain.put(item) == item.ref
    assert domain.put(item) == item.ref
    assert domain.get(item.ref) == item
    assert counts(legacy)["domain_records"] == 5


def test_same_identity_version_cannot_be_rewritten_but_next_version_can(tmp_path):
    module, _, domain, roots = opened(tmp_path)
    first = record(roots, content={"value": "original"})
    domain.put(first)
    replacement = record(roots, identity=first.ref.id, content={"value": "replacement"})
    with pytest.raises(module.ImmutableConflict):
        domain.put(replacement)
    next_version = record(roots, identity=first.ref.id, version=2, parents=[first.ref])
    domain.put(next_version)
    assert domain.get(first.ref) == first
    assert domain.get(next_version.ref) == next_version


@pytest.mark.parametrize("position", ["parent", "content", "nested"])
def test_missing_references_are_not_accepted_in_any_position(tmp_path, position):
    module, legacy, domain, roots = opened(tmp_path)
    absent = record(roots).ref
    parents = [absent] if position == "parent" else []
    content = {"source_ref": absent.as_dict()} if position == "content" else {}
    if position == "nested":
        content = {"items": [{"reference": absent.as_dict()}]}
    with pytest.raises(module.MissingRecord):
        domain.put(record(roots, parents=parents, content=content))
    assert counts(legacy)["domain_records"] == 4


def test_foreign_unregistered_ref_is_opaque_missing_not_vault_inference(tmp_path):
    module, _, domain, roots = opened(tmp_path)
    other = module.DomainStore(Store(tmp_path / "other"))
    other_roots = other.initialize_vault()
    foreign = record(other_roots)
    other.put(foreign)
    with pytest.raises(module.MissingRecord):
        domain.get(foreign.ref)
    with pytest.raises(module.MissingRecord):
        domain.put(record(roots, parents=[foreign.ref]))
    with pytest.raises(module.MissingRecord):
        domain.put(record(other_roots))


def test_bad_hash_and_corrupt_body_have_explicit_integrity_errors(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    item = record(roots)
    domain.put(item)
    wrong = EntityRef(item.ref.kind, item.ref.id, item.ref.version, "0" * 64)
    with pytest.raises(module.CorruptRecord):
        domain.get(wrong)
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE domain_records SET body = ? WHERE id = ?", (b"{}", item.ref.id))
    with pytest.raises(module.CorruptRecord):
        domain.get(item.ref)
    with pytest.raises(module.CorruptRecord):
        domain.put(record(roots, parents=[item.ref]))


def test_indexed_edges_match_body_and_cycle_tampering_is_rejected(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    first = record(roots)
    domain.put(first)
    second = record(roots, parents=[first.ref])
    domain.put(second)
    with sqlite3.connect(legacy.path) as db:
        db.execute("INSERT INTO domain_edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                   (domain.vault_id, first.ref.kind, first.ref.id, 1,
                    second.ref.kind, second.ref.id, 1, second.ref.sha256))
    with pytest.raises(module.CorruptRecord):
        domain.get(second.ref)


def test_corrupt_transitive_root_is_not_accepted(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    item = record(roots)
    domain.put(item)
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE domain_records SET body = ? WHERE id = ?", (b"{}", roots.genesis.id))
    with pytest.raises(module.CorruptRecord):
        domain.get(item.ref)


def test_actual_sqlite_durability_and_migration_version_are_observed(tmp_path):
    module, legacy, domain, _ = opened(tmp_path)
    settings = domain.sqlite_settings()
    assert settings["journal_mode"] == "wal"
    assert settings["synchronous"] == 2
    assert settings["foreign_keys"] == 1
    assert settings["fullfsync"] == 1
    assert 0 < settings["busy_timeout"] <= 10_000
    with sqlite3.connect(legacy.path) as db:
        rows = db.execute("SELECT version, sha256 FROM domain_migrations").fetchall()
    assert rows == [(1, module.MIGRATION_SHA256), (2, module.MIGRATION_2_SHA256)]
    module.DomainStore(legacy)
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT count(*) FROM domain_migrations").fetchone()[0] == 2


def test_unknown_or_tampered_migration_fails_closed(tmp_path):
    module, legacy, _, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE domain_migrations SET sha256 = ?", ("0" * 64,))
    with pytest.raises(module.CorruptRecord):
        module.DomainStore(legacy)


def test_cas_roundtrip_is_purpose_partitioned_and_private(tmp_path):
    module, legacy, domain, _ = opened(tmp_path)
    blob = domain.put_blob(b"same bytes", purpose="operational")
    assert blob.vault_id == domain.vault_id
    assert domain.read_blob(blob, purpose="operational") == b"same bytes"
    assert domain.put_blob(b"same bytes", purpose="operational") == blob
    separate = domain.put_blob(b"same bytes", purpose="diagnosis")
    assert separate.sha256 == blob.sha256 and separate != blob
    with pytest.raises(module.PurposeMismatch):
        domain.read_blob(blob, purpose="diagnosis")
    target = legacy.data_dir / "domain-cas" / "operational" / blob.sha256
    assert target.read_bytes() == b"same bytes"
    assert target.stat().st_mode & 0o777 == 0o600
    assert counts(legacy)["domain_blobs"] == 2


def test_blob_requires_real_registered_bytes_and_exact_vault(tmp_path):
    module, _, domain, roots = opened(tmp_path)
    blob = domain.put_blob(b"artifact", purpose="operational")
    item = record(roots, content={"bytes_ref": blob.as_dict()})
    domain.put(item)
    assert domain.get(item.ref) == item
    foreign = module.BlobRef(str(uuid4()), blob.purpose, blob.sha256, blob.size)
    with pytest.raises(module.ForeignVault):
        domain.read_blob(foreign, purpose="operational")
    with pytest.raises(module.ForeignVault):
        domain.put(record(roots, content={"bytes_ref": foreign.as_dict()}))
    missing = module.BlobRef(domain.vault_id, blob.purpose, "0" * 64, blob.size)
    with pytest.raises(module.MissingBlob):
        domain.put(record(roots, content={"bytes_ref": missing.as_dict()}))


def test_cas_limit_rejects_without_truncation_or_database_success(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = module.DomainStore(legacy, max_blob_bytes=3)
    domain.initialize_vault()
    with pytest.raises(ValueError):
        domain.put_blob(b"four", purpose="operational")
    with pytest.raises(ValueError):
        domain.put_blob(bytearray(b"ok"), purpose="operational")
    assert counts(legacy)["domain_blobs"] == 0
    assert domain.read_blob(domain.put_blob(b"123", purpose="operational"),
                            purpose="operational") == b"123"


def test_missing_or_corrupt_blob_does_not_return_empty_bytes_or_repair(tmp_path):
    module, legacy, domain, _ = opened(tmp_path)
    blob = domain.put_blob(b"original", purpose="operational")
    target = legacy.data_dir / "domain-cas" / "operational" / blob.sha256
    target.write_bytes(b"corrupt")
    with pytest.raises(module.CorruptBlob):
        domain.read_blob(blob, purpose="operational")
    with pytest.raises(module.CorruptBlob):
        domain.put_blob(b"original", purpose="operational")
    assert target.read_bytes() == b"corrupt"
    target.rename(target.with_name("explicit-test-missing"))
    with pytest.raises(module.MissingBlob):
        domain.read_blob(blob, purpose="operational")
    assert counts(legacy)["domain_blobs"] == 1


@pytest.mark.parametrize("component", ["domain-cas", "operational", "blob"])
def test_cas_rejects_symlink_at_each_owned_level(tmp_path, component):
    module, legacy, domain, _ = opened(tmp_path)
    domain.put_blob(b"seed", purpose="operational")
    outside = tmp_path / "outside"
    outside.mkdir()
    if component == "domain-cas":
        owned = legacy.data_dir / "domain-cas"
    else:
        owned = legacy.data_dir / "domain-cas" / "operational"
    if component == "blob":
        import hashlib
        owned.mkdir(exist_ok=True)
        owned = owned / hashlib.sha256(b"test").hexdigest()
        outside = outside / "file"
        outside.write_bytes(b"sentinel")
    elif owned.exists():
        owned.rename(owned.with_name(owned.name + "-preserved"))
    owned.symlink_to(outside)
    with pytest.raises(module.UnsafePath):
        domain.put_blob(b"test", purpose="operational")
    if component == "blob":
        assert outside.read_bytes() == b"sentinel"
    else:
        assert list(outside.iterdir()) == []


def test_database_and_parent_symlinks_rejected_before_domain_writes(tmp_path):
    module, legacy, _, _ = opened(tmp_path)
    real_database = legacy.path.with_name("preserved.sqlite3")
    legacy.path.rename(real_database)
    legacy.path.symlink_to(real_database)
    with pytest.raises(module.UnsafePath):
        module.DomainStore(legacy)


def test_repository_detects_directory_identity_change_during_sqlite_connect(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    expected = module.DomainStore(legacy).initialize_vault()
    replacement_store = Store(tmp_path / "replacement")
    replacement = module.DomainStore(replacement_store).initialize_vault()
    original_directory = tmp_path / "original-vault"
    connect = module.sqlite3.connect
    swapped = False

    def swapping_connect(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            legacy.data_dir.rename(original_directory)
            replacement_store.data_dir.rename(legacy.data_dir)
            swapped = True
        return connect(*args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", swapping_connect)
    with pytest.raises(module.UnsafePath, match="changed"):
        module.DomainStore(legacy)
    monkeypatch.undo()

    assert module.DomainStore(Store(original_directory)).roots() == expected
    assert module.DomainStore(Store(legacy.data_dir)).roots() == replacement


def test_repository_detects_persistent_directory_swap_before_database_commit(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    replacement_store = Store(tmp_path / "replacement")
    module.DomainStore(replacement_store).initialize_vault()
    original_directory = tmp_path / "original-vault"
    original_blob_directory = domain._blob_directory
    swapped = False

    @contextmanager
    def swapping_blob_directory(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            legacy.data_dir.rename(original_directory)
            replacement_store.data_dir.rename(legacy.data_dir)
            swapped = True
        with original_blob_directory(*args, **kwargs) as descriptor:
            yield descriptor

    monkeypatch.setattr(domain, "_blob_directory", swapping_blob_directory)
    data = b"split-root must not commit"
    digest = sha256(data).hexdigest()
    with pytest.raises(module.UnsafePath, match="changed"):
        domain.put_blob(data, purpose="operational")

    with sqlite3.connect(original_directory / "intake.sqlite3") as db:
        assert db.execute(
            "SELECT count(*) FROM domain_blobs WHERE sha256=?", (digest,)
        ).fetchone()[0] == 0
    assert (legacy.data_dir / "domain-cas" / "operational" / digest).read_bytes() == data


@pytest.mark.parametrize("operation", ["fsync", "rename"])
def test_cas_filesystem_failure_never_commits_blob_reference(tmp_path, monkeypatch, operation):
    module, legacy, domain, _ = opened(tmp_path)
    def fail(*args, **kwargs):
        raise OSError("injected filesystem failure")
    monkeypatch.setattr(module.os, operation, fail)
    with pytest.raises(OSError):
        domain.put_blob(b"not committed", purpose="operational")
    assert counts(legacy)["domain_blobs"] == 0


def test_cas_commit_failure_preserves_orphan_and_reports_error(tmp_path, monkeypatch):
    module, legacy, domain, _ = opened(tmp_path)
    connect = sqlite3.connect
    class FailingCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected commit failure")
    def failing_connection(*args, **kwargs):
        kwargs["factory"] = FailingCommit
        return connect(*args, **kwargs)
    monkeypatch.setattr(module.sqlite3, "connect", failing_connection)
    with pytest.raises(sqlite3.OperationalError):
        domain.put_blob(b"orphan preserved", purpose="operational")
    monkeypatch.undo()
    assert counts(legacy)["domain_blobs"] == 0
    objects = list((legacy.data_dir / "domain-cas" / "operational").iterdir())
    assert any(path.read_bytes() == b"orphan preserved" for path in objects if path.is_file())


def test_parent_fsync_precedes_database_blob_registration(tmp_path, monkeypatch):
    module, legacy, domain, _ = opened(tmp_path)
    fsync = module.os.fsync
    observed = []
    def recording_fsync(fd):
        import stat
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            observed.append(counts(legacy)["domain_blobs"])
        return fsync(fd)
    monkeypatch.setattr(module.os, "fsync", recording_fsync)
    domain.put_blob(b"ordered", purpose="operational")
    assert observed and all(value == 0 for value in observed)
    assert counts(legacy)["domain_blobs"] == 1


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_sqlite_sidecar_symlinks_are_rejected_before_sqlite_connect(tmp_path, monkeypatch, suffix):
    module = api()
    legacy = Store(tmp_path / "vault")
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"not database content")
    Path(str(legacy.path) + suffix).symlink_to(sentinel)
    called = []
    connect = sqlite3.connect
    def observed_connect(*args, **kwargs):
        called.append(True)
        return connect(*args, **kwargs)
    monkeypatch.setattr(module.sqlite3, "connect", observed_connect)
    with pytest.raises(module.UnsafePath):
        module.DomainStore(legacy)
    assert not called
    assert sentinel.read_bytes() == b"not database content"


def test_partial_root_registry_is_corrupt_not_fresh_initialization(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("DELETE FROM domain_vault")
    with pytest.raises(module.CorruptRecord):
        domain.roots()
    with pytest.raises(module.BootstrapDenied):
        domain.initialize_vault()


def test_blob_write_cannot_continue_with_incomplete_bootstrap(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("DELETE FROM domain_records WHERE id=?", (roots.retention_policy.id,))
    with pytest.raises(module.CorruptRecord):
        domain.put_blob(b"must not register", purpose="operational")
    assert counts(legacy)["domain_blobs"] == 0


def test_initialization_concurrency_has_one_atomic_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    module = api()
    legacy = Store(tmp_path / "vault")
    stores = [module.DomainStore(legacy), module.DomainStore(legacy)]
    barrier = Barrier(2)
    def initialize(domain):
        barrier.wait(timeout=5)
        try:
            return domain.initialize_vault()
        except module.AlreadyInitialized:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(initialize, stores))
    assert sum(value is not None for value in results) == 1
    assert stores[0].roots() == stores[1].roots()
    assert counts(legacy)["domain_records"] == 4


def test_ddl_failure_rolls_back_migration_and_preserves_legacy(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work("preserve migration failure")
    connect = sqlite3.connect
    class BrokenDDL(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("CREATE TABLE domain_edges"):
                raise sqlite3.OperationalError("injected migration failure")
            return super().execute(sql, *args, **kwargs)
    def broken_connect(*args, **kwargs):
        kwargs["factory"] = BrokenDDL
        return connect(*args, **kwargs)
    monkeypatch.setattr(module.sqlite3, "connect", broken_connect)
    with pytest.raises(sqlite3.OperationalError):
        module.DomainStore(legacy)
    monkeypatch.undo()
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name GLOB 'domain_*'").fetchall() == []
    assert legacy.get_work(work["id"]) == work


def test_record_commit_failure_has_no_record_or_edges(tmp_path, monkeypatch):
    module, legacy, domain, roots = opened(tmp_path)
    before = counts(legacy)
    connect = sqlite3.connect
    class BrokenCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("injected record commit failure")
    def broken_connect(*args, **kwargs):
        kwargs["factory"] = BrokenCommit
        return connect(*args, **kwargs)
    item = record(roots)
    monkeypatch.setattr(module.sqlite3, "connect", broken_connect)
    with pytest.raises(sqlite3.OperationalError):
        domain.put(item)
    monkeypatch.undo()
    assert counts(legacy) == before
    with pytest.raises(module.MissingRecord):
        domain.get(item.ref)


def test_parent_directory_sync_failure_leaves_unregistered_complete_object(tmp_path, monkeypatch):
    import hashlib
    import stat
    module, legacy, domain, _ = opened(tmp_path)
    domain.put_blob(b"existing", purpose="operational")
    fsync = module.os.fsync
    def fail_directory_sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected destination parent sync failure")
        return fsync(fd)
    monkeypatch.setattr(module.os, "fsync", fail_directory_sync)
    with pytest.raises(OSError):
        domain.put_blob(b"new complete bytes", purpose="operational")
    assert counts(legacy)["domain_blobs"] == 1
    target = legacy.data_dir / "domain-cas" / "operational" / hashlib.sha256(b"new complete bytes").hexdigest()
    assert target.read_bytes() == b"new complete bytes"


def test_parent_directory_symlink_is_rejected_on_existing_repository(tmp_path):
    module, legacy, domain, roots = opened(tmp_path)
    preserved = legacy.data_dir.with_name("preserved-vault")
    legacy.data_dir.rename(preserved)
    legacy.data_dir.symlink_to(preserved)
    with pytest.raises(module.UnsafePath):
        domain.get(roots.genesis)


@pytest.mark.parametrize("content", [{"source_ref": {"kind": "work_model"}},
                                    {"source_refs": "not a list"}])
def test_malformed_nested_reference_is_rejected_before_insert(tmp_path, content):
    module, legacy, domain, roots = opened(tmp_path)
    with pytest.raises(ValueError):
        domain.put(record(roots, content=content))
    assert counts(legacy)["domain_records"] == 4


def test_writer_wait_is_bounded(tmp_path, monkeypatch):
    from threading import Event, Thread
    module, _, domain, roots = opened(tmp_path)
    monkeypatch.setattr(module, "WRITER_TIMEOUT_SECONDS", 0.01, raising=False)
    entered, release = Event(), Event()
    def hold():
        with module._WRITER:
            entered.set()
            release.wait(timeout=3)
    worker = Thread(target=hold)
    worker.start()
    assert entered.wait(timeout=2)
    try:
        with pytest.raises(module.StorageError, match="writer"):
            domain.put(record(roots))
    finally:
        release.set()
        worker.join(timeout=3)


@pytest.mark.parametrize("target,mode", [("directory", 0o755), ("database", 0o644)])
def test_repository_rejects_permissive_modes_without_repair(tmp_path, target, mode):
    module, legacy, domain, roots = opened(tmp_path)
    path = legacy.data_dir if target == "directory" else legacy.path
    path.chmod(mode)
    with pytest.raises(module.UnsafePath):
        domain.get(roots.genesis)
    assert path.stat().st_mode & 0o777 == mode


def test_repository_rejects_different_uid_without_ownership_changes(tmp_path, monkeypatch):
    module, _, domain, roots = opened(tmp_path)
    actual_uid = os.getuid()
    monkeypatch.setattr(module.os, "getuid", lambda: actual_uid + 1)
    with pytest.raises(module.UnsafePath):
        domain.get(roots.genesis)


def test_staged_verification_read_has_a_byte_bound(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = module.DomainStore(legacy, max_blob_bytes=3)
    domain.initialize_vault()
    reads = []
    def growing_file(fd, count):
        reads.append(count)
        if len(reads) > 5:
            raise OSError("unbounded staging read")
        return b"x"
    monkeypatch.setattr(module.os, "read", growing_file)
    with pytest.raises(module.CorruptBlob):
        domain.put_blob(b"ok", purpose="operational")
    assert len(reads) <= 4
    assert counts(legacy)["domain_blobs"] == 0


def test_uploaded_json_bytes_do_not_become_domain_references(tmp_path):
    _, _, domain, _ = opened(tmp_path)
    data = b'{"source_ref":{"untrusted":"not a domain reference"}}'
    blob = domain.put_blob(data, purpose="operational")
    assert domain.read_blob(blob, purpose="operational") == data


@pytest.mark.parametrize("bound,value", [("MAX_GRAPH_NODES", 3), ("MAX_GRAPH_DEPTH", 1)])
def test_graph_verification_limits_are_explicit_failures_not_data_loss(tmp_path, monkeypatch, bound, value):
    module, legacy, domain, roots = opened(tmp_path)
    item = record(roots)
    domain.put(item)
    monkeypatch.setattr(module, bound, value)
    with pytest.raises(module.StorageError, match="bound") as error:
        domain.get(item.ref)
    assert not isinstance(error.value, module.CorruptRecord)
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT body FROM domain_records WHERE id=?", (item.ref.id,)).fetchone()[0] == item.body_bytes


@pytest.mark.parametrize("bound,value", [("MAX_GRAPH_NODES", 4), ("MAX_GRAPH_DEPTH", 1)])
def test_new_record_counts_toward_read_verification_limit_before_commit(tmp_path, monkeypatch, bound, value):
    module, legacy, domain, roots = opened(tmp_path)
    item = record(roots)
    before = counts(legacy)
    monkeypatch.setattr(module, bound, value)
    with pytest.raises(module.VerificationLimit):
        domain.put(item)
    assert counts(legacy) == before
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT body FROM domain_records WHERE id=?", (item.ref.id,)).fetchone() is None
    assert domain.get(roots.genesis).ref == roots.genesis


@pytest.mark.parametrize("operation", ["read", "reuse"])
def test_cas_fifo_rejected_without_waiting_for_a_writer(tmp_path, operation):
    from threading import Thread

    module, legacy, domain, _ = opened(tmp_path)
    blob = domain.put_blob(b"fixture", purpose="operational")
    path = legacy.data_dir / "domain-cas" / "operational" / blob.sha256
    path.unlink()  # Replace only this test's owned CAS fixture with a nonregular file.
    os.mkfifo(path, mode=0o600)
    errors = []

    def invoke():
        try:
            if operation == "read":
                domain.read_blob(blob, purpose="operational")
            else:
                domain.put_blob(b"fixture", purpose="operational")
        except Exception as error:
            errors.append(error)

    thread = Thread(target=invoke, daemon=True)
    thread.start()
    thread.join(timeout=0.5)
    was_blocked = thread.is_alive()
    try:
        assert not was_blocked, "CAS open blocked on a FIFO before nonregular rejection"
        assert len(errors) == 1 and isinstance(errors[0], module.UnsafePath)
    finally:
        if was_blocked:
            # Release the failing implementation without leaving a held writer lock.
            descriptor = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            os.close(descriptor)
        thread.join(timeout=2)
    assert not thread.is_alive()


@pytest.mark.parametrize("residual", ["domain_records", "domain_edges", "domain_blobs", "domain_record_blobs"])
def test_residual_domain_rows_are_corruption_not_a_fresh_vault(tmp_path, residual):
    module, legacy, domain, roots = opened(tmp_path)
    blob = domain.put_blob(b"preserve partial fixture", purpose="operational")
    domain.put(record(roots, content={"bytes_ref": blob.as_dict()}))
    tables = ("domain_records", "domain_edges", "domain_blobs", "domain_record_blobs")
    with sqlite3.connect(legacy.path) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for table in tables:
            if table != residual:
                db.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM domain_vault")
        preserved = db.execute(f"SELECT * FROM {residual}").fetchall()
        assert preserved
    with pytest.raises(module.CorruptRecord):
        domain.roots()
    with pytest.raises(module.BootstrapDenied):
        domain.initialize_vault()
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT count(*) FROM domain_vault").fetchone()[0] == 0
        assert db.execute(f"SELECT * FROM {residual}").fetchall() == preserved
    assert (legacy.data_dir / "domain-cas" / "operational" / blob.sha256).read_bytes() == b"preserve partial fixture"


def test_residual_legacy_migration_link_is_not_a_fresh_vault(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"linked", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    domain.migrate_legacy_file(work["id"], added["id"])
    with sqlite3.connect(legacy.path) as db:
        db.execute("PRAGMA foreign_keys=OFF")
        for table in ("domain_record_blobs", "domain_edges", "domain_records",
                      "domain_blobs", "domain_vault"):
            db.execute(f"DELETE FROM {table}")
        assert db.execute("SELECT count(*) FROM domain_legacy_files").fetchone()[0] == 1

    with pytest.raises(module.CorruptRecord):
        domain.roots()
    with pytest.raises(module.BootstrapDenied):
        domain.initialize_vault()


def test_valid_blob_exceeding_current_backend_limit_is_not_corrupt(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    original = module.DomainStore(legacy, max_blob_bytes=4)
    original.initialize_vault()
    blob = original.put_blob(b"1234", purpose="operational")
    smaller = module.DomainStore(legacy, max_blob_bytes=3)
    with pytest.raises(module.VerificationLimit):
        smaller.read_blob(blob, purpose="operational")
    assert original.read_blob(blob, purpose="operational") == b"1234"


def test_v1_store_upgrades_additively_to_v2_without_rewriting_legacy_bytes(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work("migration fixture")
    added = legacy.add_file(work["id"], "source.txt", b"legacy exact bytes", "text/plain")
    before = (legacy.get_work(work["id"]), legacy.get_revision(work["id"], 1),
              legacy.get_revision(work["id"], 2), legacy.read_file(work["id"], added["id"]),
              legacy.events())
    with sqlite3.connect(legacy.path) as db:
        for statement in module._MIGRATION_1_DDL:
            db.execute(statement)
        db.execute("INSERT INTO domain_migrations VALUES (1, ?)",
                   (module.MIGRATION_SHA256,))

    module.DomainStore(legacy)

    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT version,sha256 FROM domain_migrations ORDER BY version").fetchall() == [
            (1, module.MIGRATION_SHA256), (2, module.MIGRATION_2_SHA256)]
        assert bytes(db.execute("SELECT data FROM files WHERE id=?", (added["id"],)).fetchone()[0]) == b"legacy exact bytes"
    assert (legacy.get_work(work["id"]), legacy.get_revision(work["id"], 1),
            legacy.get_revision(work["id"], 2), legacy.read_file(work["id"], added["id"]),
            legacy.events()) == before


def test_v2_upgrade_failure_rolls_back_only_new_schema_and_preserves_v1(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work("preserve v1")
    with sqlite3.connect(legacy.path) as db:
        for statement in module._MIGRATION_1_DDL:
            db.execute(statement)
        db.execute("INSERT INTO domain_migrations VALUES (1, ?)",
                   (module.MIGRATION_SHA256,))
    connect = sqlite3.connect

    class BrokenV2(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("CREATE TABLE domain_legacy_files"):
                raise sqlite3.OperationalError("injected v2 migration failure")
            return super().execute(sql, *args, **kwargs)

    def broken_connect(*args, **kwargs):
        kwargs["factory"] = BrokenV2
        return connect(*args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", broken_connect)
    with pytest.raises(sqlite3.OperationalError):
        module.DomainStore(legacy)
    monkeypatch.undo()

    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT version,sha256 FROM domain_migrations").fetchall() == [
            (1, module.MIGRATION_SHA256)]
        assert db.execute("SELECT name FROM sqlite_master WHERE name='domain_legacy_files'").fetchone() is None
    assert legacy.get_work(work["id"]) == work


def test_matching_ledger_cannot_hide_rewritten_or_partial_domain_schema(tmp_path):
    module, legacy, domain, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute("DROP INDEX domain_legacy_files_work")
        db.execute("CREATE INDEX domain_legacy_files_work ON domain_legacy_files(file_id)")
    with pytest.raises(module.CorruptRecord, match="schema"):
        module.DomainStore(legacy)
    with sqlite3.connect(legacy.path) as db:
        db.execute("DROP INDEX domain_legacy_files_work")
    with pytest.raises(module.CorruptRecord, match="schema"):
        module.DomainStore(legacy)


@pytest.mark.parametrize("ddl", [
    "CREATE TRIGGER domain_unexpected_trigger AFTER INSERT ON domain_records "
    "BEGIN SELECT 1; END",
    "CREATE TRIGGER DOMAIN_UNEXPECTED_TRIGGER AFTER INSERT ON domain_records "
    "BEGIN SELECT 1; END",
    "CREATE TRIGGER unexpected_trigger AFTER INSERT ON domain_records "
    "BEGIN SELECT 1; END",
    "CREATE INDEX unexpected_record_index ON domain_records(id)",
])
def test_matching_ledger_cannot_hide_extra_domain_schema_objects(tmp_path, ddl):
    module, legacy, _, _ = opened(tmp_path)
    with sqlite3.connect(legacy.path) as db:
        db.execute(ddl)

    with pytest.raises(module.CorruptRecord, match="schema"):
        module.DomainStore(legacy)


def test_legacy_read_fails_closed_on_partial_v2_schema(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"preserved", "text/plain")
    module.DomainStore(legacy)
    with sqlite3.connect(legacy.path) as db:
        db.execute("DROP INDEX domain_legacy_files_work")

    with pytest.raises(Exception) as error:
        legacy.read_file(work["id"], added["id"])
    assert type(error.value).__name__ == "StorageIntegrityError"


def test_legacy_file_migration_preserves_ids_revisions_events_and_old_blob(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work("old work")
    added = legacy.add_file(work["id"], "source.txt", b"original legacy bytes", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    before_work = legacy.get_work(work["id"])
    before_revisions = [legacy.get_revision(work["id"], version) for version in (1, 2)]
    before_events = legacy.events()

    link = domain.migrate_legacy_file(work["id"], added["id"])

    assert link.work_id == work["id"] and link.file_id == added["id"]
    assert link.blob.purpose == "operational"
    assert domain.read_blob(link.blob, purpose="operational") == b"original legacy bytes"
    assert legacy.read_file(work["id"], added["id"]) == (added, b"original legacy bytes")
    assert legacy.get_work(work["id"]) == before_work
    assert [legacy.get_revision(work["id"], version) for version in (1, 2)] == before_revisions
    assert legacy.events() == before_events
    with sqlite3.connect(legacy.path) as db:
        row = db.execute("SELECT work_id,file_id,legacy_sha256,blob_sha256,read_source "
                         "FROM domain_legacy_files").fetchone()
        assert row == (work["id"], added["id"], added["sha256"], added["sha256"], "cas")
        assert bytes(db.execute("SELECT data FROM files WHERE id=?", (added["id"],)).fetchone()[0]) == b"original legacy bytes"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_migrated_legacy_read_uses_cas_and_never_falls_back_on_cas_corruption(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"authoritative after switch", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    link = domain.migrate_legacy_file(work["id"], added["id"])
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE files SET data=? WHERE id=?", (b"inactive old copy changed", added["id"]))
    assert legacy.read_file(work["id"], added["id"])[1] == b"authoritative after switch"

    target = legacy.data_dir / "domain-cas" / "operational" / link.blob.sha256
    target.write_bytes(b"corrupt cas")
    with pytest.raises(Exception) as error:
        legacy.read_file(work["id"], added["id"])
    assert type(error.value).__name__ == "StorageIntegrityError"
    with sqlite3.connect(legacy.path) as db:
        assert bytes(db.execute("SELECT data FROM files WHERE id=?", (added["id"],)).fetchone()[0]) == b"inactive old copy changed"


def test_failed_seal_does_not_switch_legacy_read_or_delete_old_bytes(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"still legacy", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()

    def fail(*args, **kwargs):
        raise OSError("injected sealing failure")

    monkeypatch.setattr(module.os, "rename", fail)
    with pytest.raises(OSError):
        domain.migrate_legacy_file(work["id"], added["id"])
    monkeypatch.undo()

    assert legacy.read_file(work["id"], added["id"]) == (added, b"still legacy")
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT count(*) FROM domain_legacy_files").fetchone()[0] == 0
        assert bytes(db.execute("SELECT data FROM files WHERE id=?", (added["id"],)).fetchone()[0]) == b"still legacy"


def test_mapping_commit_failure_leaves_verified_cas_but_no_read_switch(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"orphan mapping fixture", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    connect = sqlite3.connect

    class BrokenMapping(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("INSERT INTO domain_legacy_files"):
                raise sqlite3.OperationalError("injected mapping failure")
            return super().execute(sql, *args, **kwargs)

    def broken_connect(*args, **kwargs):
        kwargs["factory"] = BrokenMapping
        return connect(*args, **kwargs)

    monkeypatch.setattr(module.sqlite3, "connect", broken_connect)
    with pytest.raises(sqlite3.OperationalError):
        domain.migrate_legacy_file(work["id"], added["id"])
    monkeypatch.undo()

    assert legacy.read_file(work["id"], added["id"]) == (added, b"orphan mapping fixture")
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT count(*) FROM domain_legacy_files").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0] == 1


def test_legacy_migration_rejects_changed_metadata_or_bytes_without_switch(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"original", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE files SET data=? WHERE id=?", (b"changed", added["id"]))

    with pytest.raises(module.CorruptRecord, match="legacy"):
        domain.migrate_legacy_file(work["id"], added["id"])
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT count(*) FROM domain_legacy_files").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0] == 0


def test_unmigrated_read_rejects_non_blob_storage_before_materializing_it(tmp_path, monkeypatch):
    import app.storage as storage_module

    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"x", "text/plain")
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE files SET data=? WHERE id=?", (1_000_000, added["id"]))

    def forbidden_materialization(_):
        raise AssertionError("integer storage must not reach bytes()")

    monkeypatch.setattr(storage_module, "bytes", forbidden_materialization, raising=False)
    with pytest.raises(StorageIntegrityError, match="corrupt"):
        legacy.read_file(work["id"], added["id"])


def test_legacy_migration_rejects_non_blob_storage_before_materializing_it(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"x", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE files SET data=? WHERE id=?", (1_000_000, added["id"]))

    def forbidden_materialization(_):
        raise AssertionError("integer storage must not reach bytes()")

    monkeypatch.setattr(module, "bytes", forbidden_materialization, raising=False)
    with pytest.raises(module.CorruptRecord, match="storage class"):
        domain.migrate_legacy_file(work["id"], added["id"])


def test_legacy_migration_is_idempotent_bounded_and_includes_later_files(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    first = legacy.add_file(work["id"], "one.txt", b"one", "text/plain")
    second = legacy.add_file(work["id"], "two.txt", b"two", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()

    page = domain.migrate_legacy_files(max_items=1)
    assert len(page.links) == 1 and page.remaining == 1
    assert domain.migrate_legacy_file(page.links[0].work_id, page.links[0].file_id) == page.links[0]
    page = domain.migrate_legacy_files(max_items=1)
    assert len(page.links) == 1 and page.remaining == 0
    assert {link.file_id for link in domain.legacy_file_links()} == {first["id"], second["id"]}

    third = legacy.add_file(work["id"], "three.txt", b"three", "text/plain")
    assert legacy.read_file(work["id"], third["id"])[1] == b"three"
    final = domain.migrate_legacy_files(max_items=20)
    assert len(final.links) == 1 and final.links[0].file_id == third["id"] and final.remaining == 0
    assert {link.file_id for link in domain.legacy_file_links()} == {
        first["id"], second["id"], third["id"]}


def test_legacy_migration_limit_and_wrong_work_are_explicit_without_mutation(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    first = legacy.create_work()
    second = legacy.create_work()
    added = legacy.add_file(first["id"], "source.txt", b"1234", "text/plain")
    domain = module.DomainStore(legacy, max_blob_bytes=3)
    domain.initialize_vault()

    with pytest.raises(KeyError):
        domain.migrate_legacy_file(second["id"], added["id"])
    with pytest.raises(module.VerificationLimit):
        domain.migrate_legacy_file(first["id"], added["id"])
    with pytest.raises(ValueError):
        domain.migrate_legacy_files(max_items=0)
    with sqlite3.connect(legacy.path) as db:
        assert db.execute("SELECT count(*) FROM domain_legacy_files").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0] == 0


def test_idempotent_legacy_migration_still_requires_the_exact_work_id(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    first = legacy.create_work()
    second = legacy.create_work()
    added = legacy.add_file(first["id"], "source.txt", b"sealed", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    domain.migrate_legacy_file(first["id"], added["id"])

    with pytest.raises(KeyError):
        domain.migrate_legacy_file(second["id"], added["id"])


def test_mapped_file_identity_tamper_never_falls_back_to_legacy_bytes(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    first = legacy.create_work()
    second = legacy.create_work()
    added = legacy.add_file(first["id"], "source.txt", b"sealed", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    domain.migrate_legacy_file(first["id"], added["id"])
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE domain_legacy_files SET work_id=? WHERE file_id=?",
                   (second["id"], added["id"]))

    with pytest.raises(Exception) as error:
        legacy.read_file(first["id"], added["id"])
    assert type(error.value).__name__ == "StorageIntegrityError"
    with pytest.raises(module.CorruptRecord, match="legacy"):
        domain.migrate_legacy_file(first["id"], added["id"])


def test_legacy_mapping_purpose_is_fixed_and_tamper_fails_closed(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"same", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    domain.migrate_legacy_file(work["id"], added["id"])
    domain.put_blob(b"same", purpose="diagnosis")

    with sqlite3.connect(legacy.path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE domain_legacy_files SET purpose='diagnosis'")

    with sqlite3.connect(legacy.path) as db:
        db.execute("PRAGMA ignore_check_constraints=ON")
        db.execute("UPDATE domain_legacy_files SET purpose='diagnosis'")
    with pytest.raises(module.CorruptRecord, match="legacy"):
        domain.legacy_file_links()
    with pytest.raises(StorageIntegrityError):
        legacy.read_file(work["id"], added["id"])


def test_mapped_read_revalidates_migration_ledger_and_timestamp(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    added = legacy.add_file(work["id"], "source.txt", b"sealed", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    domain.migrate_legacy_file(work["id"], added["id"])
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE domain_migrations SET sha256=? WHERE version=2", ("0" * 64,))
    with pytest.raises(Exception) as error:
        legacy.read_file(work["id"], added["id"])
    assert type(error.value).__name__ == "StorageIntegrityError"

    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE domain_migrations SET sha256=? WHERE version=2",
                   (module.MIGRATION_2_SHA256,))
        db.execute("UPDATE domain_legacy_files SET migrated_at_utc='not-a-time'")
    with pytest.raises(Exception) as error:
        legacy.read_file(work["id"], added["id"])
    assert type(error.value).__name__ == "StorageIntegrityError"
    with pytest.raises(module.CorruptRecord, match="legacy"):
        domain.legacy_file_links()


def test_batch_legacy_migration_has_a_total_byte_bound(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    legacy.add_file(work["id"], "one.txt", b"12", "text/plain")
    legacy.add_file(work["id"], "two.txt", b"34", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    monkeypatch.setattr(module, "MAX_LEGACY_MIGRATION_BYTES", 3, raising=False)

    page = domain.migrate_legacy_files(max_items=20)

    assert len(page.links) == 1 and page.remaining == 1


def test_transitive_blob_verification_has_a_total_byte_bound_and_rolls_back(tmp_path, monkeypatch):
    module, legacy, domain, roots = opened(tmp_path)
    first_blob = domain.put_blob(b"12", purpose="operational")
    first = record(roots, content={"bytes_ref": first_blob.as_dict()})
    domain.put(first)
    second_blob = domain.put_blob(b"34", purpose="operational")
    second = record(roots, parents=[first.ref], content={"bytes_ref": second_blob.as_dict()})
    before = counts(legacy)
    monkeypatch.setattr(module, "MAX_GRAPH_BLOB_BYTES", 3, raising=False)

    with pytest.raises(module.VerificationLimit, match="byte"):
        domain.put(second)

    assert counts(legacy) == before
    assert domain.read_blob(first_blob, purpose="operational") == b"12"


def test_legacy_link_listing_has_a_total_byte_bound(tmp_path, monkeypatch):
    module = api()
    legacy = Store(tmp_path / "vault")
    work = legacy.create_work()
    first = legacy.add_file(work["id"], "one.txt", b"12", "text/plain")
    second = legacy.add_file(work["id"], "two.txt", b"34", "text/plain")
    domain = module.DomainStore(legacy)
    domain.initialize_vault()
    domain.migrate_legacy_file(work["id"], first["id"])
    domain.migrate_legacy_file(work["id"], second["id"])
    monkeypatch.setattr(module, "MAX_LEGACY_LINK_VERIFY_BYTES", 3, raising=False)

    with pytest.raises(module.VerificationLimit, match="byte"):
        domain.legacy_file_links()


@pytest.mark.parametrize("nlink,accepted", [(0, True), (1, True), (2, False)])
def test_sidecar_nlink_zero_is_a_concurrent_unlink_not_an_attack(tmp_path, monkeypatch,
                                                                 nlink, accepted):
    """A closing connection unlinks -wal/-shm while another opens: the observed healthy
    sidecar with st_nlink == 0 is treated as absent, while a hardlink still fails."""
    module, legacy, domain, roots = opened(tmp_path)
    Path(str(legacy.path) + "-wal").write_bytes(b"")
    os.chmod(str(legacy.path) + "-wal", 0o600)
    real_stat = os.stat

    def racing_stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if isinstance(path, str) and path.endswith("-wal"):
            values = list(result)
            values[stat.ST_NLINK] = nlink
            return os.stat_result(values)
        return result

    monkeypatch.setattr(module.os, "stat", racing_stat)
    if accepted:
        with domain._connection() as db:
            assert db.execute("SELECT 1").fetchone()[0] == 1
    else:
        with pytest.raises(module.UnsafePath, match="sidecar"):
            with domain._connection():
                pass
