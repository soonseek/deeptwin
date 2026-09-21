"""Durable first-owner tests over bounded synthetic stores."""
import importlib
import threading

import pytest


def test_password_lane_exposes_bounded_reservations():
    module = importlib.import_module("app.services.owner_admission")
    lane = module.PasswordLane()
    reservations = [lane.reserve() for _ in range(4)]
    try:
        with pytest.raises(module.AdmissionRejected):
            lane.reserve()
    finally:
        for reservation in reservations:
            reservation.close()


def test_lane_fifo_and_no_early_release_during_native_work():
    module = importlib.import_module("app.services.owner_admission")
    lane = module.PasswordLane()
    reservations = [lane.reserve() for _ in range(4)]
    entered, release = threading.Event(), threading.Event()
    order = []

    def operation(index):
        order.append(index)
        if index == 0:
            entered.set()
            assert release.wait(2)

    threads = [threading.Thread(target=lambda i=i: reservations[i].run(lambda: operation(i)))
               for i in range(4)]
    threads[0].start()
    assert entered.wait(2)
    reservations[0].close()
    with pytest.raises(module.AdmissionRejected):
        lane.reserve()
    for thread in reversed(threads[1:]):
        thread.start()
    release.set()
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert order == [0, 1, 2, 3]


def test_buckets_independent_bounded_and_unknown_names_share_sentinel():
    module = importlib.import_module("app.services.owner_admission")
    buckets = module.PasswordBuckets()
    for index in range(5):
        buckets.admit(f"source-{index}", None)
    with pytest.raises(module.AdmissionRejected):
        buckets.admit("different-source", None)
    for index in range(5):
        buckets.admit("known-source", f"account-{index}")
    with pytest.raises(module.AdmissionRejected):
        buckets.admit("known-source", "another-account")


def test_queue_expiry_starts_no_operation():
    module = importlib.import_module("app.services.owner_admission")
    lane = module.PasswordLane(timeout=0.02)
    first, second = lane.reserve(), lane.reserve()
    started = []
    with pytest.raises(module.AdmissionRejected):
        second.run(lambda: started.append(True))
    first.close()
    assert started == []


def test_serving_lock_excludes_second_owner_and_releases_on_close(tmp_path):
    module = importlib.import_module("app.services.owner_admission")
    import os
    lock = module.ServingLock(tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid())
    with pytest.raises(module.AdmissionRejected):
        module.ServingLock(tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid())
    lock.close()
    module.ServingLock(tmp_path, expected_uid=os.getuid(), expected_gid=os.getgid()).close()


def test_existing_lock_only_never_creates_or_repairs(tmp_path):
    import os
    from app.services.owner_admission import ServingLock, AdmissionRejected
    args = dict(expected_uid=os.geteuid(), expected_gid=os.getegid(), create=False)
    with pytest.raises(AdmissionRejected):
        ServingLock(tmp_path, **args)
    path = tmp_path / "owner-auth.lock"
    assert not path.exists()
    ServingLock(tmp_path, expected_uid=os.geteuid(), expected_gid=os.getegid()).close()
    inode = path.stat().st_ino
    ServingLock(tmp_path, **args).close()
    assert path.stat().st_ino == inode
    path.chmod(0o640)
    with pytest.raises(AdmissionRejected):
        ServingLock(tmp_path, **args)
    assert path.stat().st_mode & 0o777 == 0o640


@pytest.mark.parametrize("create", [True, False])
def test_serving_lock_rejects_inode_replacement_during_acquisition(tmp_path, monkeypatch, create):
    import os
    from app.services import owner_admission as module
    args = dict(expected_uid=os.geteuid(), expected_gid=os.getegid())
    module.ServingLock(tmp_path, **args).close()
    original = module.fcntl.flock
    def replace_lock(fd, flags):
        path = tmp_path / "owner-auth.lock"
        path.rename(tmp_path / "held.lock")
        path.touch(mode=0o600)
        original(fd, flags)
    monkeypatch.setattr(module.fcntl, "flock", replace_lock)
    with pytest.raises(module.AdmissionRejected):
        module.ServingLock(tmp_path, **args, create=create)


def test_lane_close_waits_for_native_completion_and_refuses_new_work():
    module = importlib.import_module("app.services.owner_admission")
    lane = module.PasswordLane()
    reservation = lane.reserve()
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    def native():
        entered.set()
        assert release.wait(2)
    worker = threading.Thread(target=lambda: reservation.run(native))
    worker.start()
    assert entered.wait(2)
    def close():
        lane.close()
        closed.set()
    closer = threading.Thread(target=close)
    closer.start()
    assert not closed.wait(0.03)
    release.set()
    worker.join(2)
    closer.join(2)
    assert closed.is_set()
    with pytest.raises(module.AdmissionRejected):
        lane.reserve()


def test_auth_public_schema_export_is_closed_and_matches_installed_artifact():
    import json
    from pathlib import Path
    module = importlib.import_module("app.services.owner_auth_schema")
    schema = module.owner_auth_schema()
    path = Path(__file__).parents[2] / "schemas/v1/owner-auth-public.schema.json"
    assert json.loads(path.read_text()) == schema
    receipt = schema["$defs"]["SessionRootReceipt"]
    assert receipt["additionalProperties"] is False
    assert "integrity_tag" not in receipt["properties"]
    assert "key" not in receipt["properties"]


def test_bucket_maps_never_replenish_live_keys_to_admit_a_new_key(monkeypatch):
    module = importlib.import_module("app.services.owner_admission")
    now = [100.0]
    monkeypatch.setattr(module.time, "monotonic", lambda: now[0])
    buckets = module.PasswordBuckets()
    for index in range(1024):
        for _ in range(5):
            buckets.admit(f"source-{index}", f"account-{index}")
    with pytest.raises(module.AdmissionRejected):
        buckets.admit("new-source", "new-account")
    with pytest.raises(module.AdmissionRejected):
        buckets.admit("source-0", "account-0")
    now[0] += 6
    buckets.admit("source-0", "account-0")
    with pytest.raises(module.AdmissionRejected):
        buckets.admit("new-source", "new-account")
    now[0] += 60
    buckets.admit("new-source", "new-account")


def test_private_storage_helpers_reject_unknown_columns_before_sql():
    import sqlite3

    from app.services import owner_auth_storage as storage
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        storage.install(db)
        with pytest.raises(storage.AuthStorageError):
            storage.insert(db, "audit", {"sequence": 1, "not_a_column": "bad"})


def test_private_storage_rejects_foreign_named_trigger_and_index():
    import sqlite3

    from app.services import owner_auth_storage as storage
    with sqlite3.connect(":memory:") as db:
        db.row_factory = sqlite3.Row
        storage.install(db)
        db.execute("CREATE TRIGGER unregistered AFTER INSERT ON owner_auth_audit BEGIN SELECT 1; END")
        with pytest.raises(storage.AuthStorageError):
            storage.verify(db)
        db.execute("DROP TRIGGER unregistered")
        db.execute("CREATE INDEX unregistered ON owner_auth_audit(kind)")
        with pytest.raises(storage.AuthStorageError):
            storage.verify(db)
