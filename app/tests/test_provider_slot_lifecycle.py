"""Finite slot ownership, using real temporary FDs and flock operations.

ActualSources simulates only path, UID/GID, platform and mount observations;
all successful Directory, source, slot and metadata acquisitions remain real.
"""

import fcntl
import os
from contextlib import contextmanager

import pytest

from app.deployment import sources
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.deployment.prepare_service import PersistentDeploymentPrepare
from app.tests.deployment_source_fixture import (
    actual_sources as actual_sources,  # noqa: PLC0414 - pytest fixture re-export
)
from app.workers import ipc_root


class ControlAbort(BaseException):
    pass


CONTROLS = [KeyboardInterrupt, SystemExit, ControlAbort]


class Acquisitions:
    """Track open instances, allowing legitimate reuse of an integer FD.

    A refused physical close remains live for teardown, but is never retried
    by production. The borrowed sentinel is deliberately outside this ledger.
    """

    def __init__(self, monkeypatch, sentinel):
        self.patch = monkeypatch
        self.open = os.open
        self.close = os.close
        self.fstat = os.fstat
        self.sentinel = sentinel
        self.records = []
        self.live = {}
        self.unknown_closes = []
        self.close_failure = None
        monkeypatch.setattr(os, "open", self.tracked_open)
        monkeypatch.setattr(os, "close", self.tracked_close)

    def tracked_open(self, name, *args, **kwargs):
        fd = self.open(name, *args, **kwargs)
        record = {"fd": fd, "name": str(name), "attempts": 0}
        assert fd not in self.live
        self.live[fd] = record
        self.records.append(record)
        return fd

    def tracked_close(self, fd):
        record = self.live.get(fd)
        if record is None:
            self.unknown_closes.append(fd)
            raise AssertionError("closing borrowed or already detached descriptor")
        record["attempts"] += 1
        failure = self.close_failure(record) if self.close_failure else None
        if failure and failure[1] == "before":
            raise failure[0]
        self.close(fd)
        del self.live[fd]
        if failure:
            raise failure[0]

    def assert_released(self):
        assert not self.live, self.live
        self.assert_attempted()

    def assert_attempted(self):
        assert self.records
        assert all(r["attempts"] == 1 for r in self.records), self.records
        assert not self.unknown_closes
        self.fstat(self.sentinel)

    def teardown(self):
        for fd in tuple(self.live):
            self.close(fd)
            del self.live[fd]


@contextmanager
def observed(monkeypatch, tmp_path):
    sentinel = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    close = os.close
    with monkeypatch.context() as patch:
        ledger = Acquisitions(patch, sentinel)
        try:
            yield ledger
        finally:
            ledger.teardown()
            close(sentinel)


def spec_for(s):
    return ipc_root.PairRootSpec(s.c.IPC_ROOT / "xs01", 22001, 22001, 23001)


def service_for(topology):
    service = object.__new__(PersistentDeploymentPrepare)
    service._topology, service._profile = topology, topology._profile
    return service


@contextmanager
def lock_observer(s):
    fd = os.open(s.actual(s.c.IPC_ROOT / "xs01" / "generation.lock"), os.O_RDONLY)
    try:
        yield fd
    finally:
        os.close(fd)


def assert_locked(fd):
    with pytest.raises(BlockingIOError):
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def assert_unlocked(fd):
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(fd, fcntl.LOCK_UN)


def test_ordinary_actual_chain_preserves_slot_metadata_and_lock(
    actual_sources, monkeypatch, tmp_path
):
    s = actual_sources
    with s.open_topology() as topology, lock_observer(s) as lock:

        def forbidden(*args, **kwargs):
            raise AssertionError("metadata acquisition read secret or listed directory")

        monkeypatch.setattr(ipc_root, "_read_exact_secret", forbidden)
        protected = {
            os.stat(s.actual(path)).st_ino
            for path in (spec_for(s).pair_root, spec_for(s).endpoint_path)
        }
        for name in ("listdir", "scandir"):
            original = getattr(os, name)

            def checked(path, *args, _original=original, **kwargs):
                info = os.fstat(path) if isinstance(path, int) else os.stat(path)
                if info.st_ino in protected:
                    forbidden()
                return _original(path, *args, **kwargs)

            monkeypatch.setattr(os, name, checked)
        with observed(monkeypatch, tmp_path) as ledger:
            lease = service_for(topology)._acquire(1, None)
            assert lease.slot["uid"] == 22001
            assert lease.slot["gid"] == 22001
            assert lease.slot["pair_gid"] == 23001
            assert lease.slot["slot_number"] == 1
            assert lease.slot["service_identity"] == "ext-" + "1" * 32 + "-01"
            assert lease.slot["channel_id"] == "cp-ext-" + "1" * 32 + "-01"
            assert lease.slot["socket_mount"] == {
                "mount_id": "xs01",
                "volume_name": "dt-" + "1" * 32 + "-ipc-xs01",
                "container_path": "/run/deeptwin/ipc/xs01",
                "read_only": False,
                "purpose": "broker_pair",
            }
            assert lease.slot["socket_name"] == "worker.sock"
            assert lease.slot["protocol_id"] == "deeptwin-extension-worker-v1"
            assert lease.topology_bytes == s.output.topology_bytes
            metadata = lease.metadata_lease
            root = os.stat(s.actual(spec_for(s).pair_root))
            endpoint = os.stat(s.actual(spec_for(s).endpoint_path))
            assert metadata.pair_identity.inode == root.st_ino
            assert metadata.endpoint_identity.inode == endpoint.st_ino
            assert not hasattr(metadata, "secret")
            assert_locked(lock)
            lease.recheck_current()
            lease.close()
            lease.close()
            ledger.assert_released()
            assert_unlocked(lock)
        topology.recheck_current()


@pytest.mark.parametrize("change", ["missing", "owner", "mode", "link", "size", "busy"])
def test_ordinary_refusal_and_service_mapping(
    actual_sources, monkeypatch, tmp_path, change
):
    s = actual_sources
    with s.open_topology() as topology, lock_observer(s) as lock:
        path = s.actual(spec_for(s).generation_lock_path)
        if change == "missing":
            path.unlink()
        elif change == "owner":
            s.register(path, 99, 23001)
        elif change == "mode":
            path.chmod(0o600)
        elif change == "link":
            os.link(path, path.with_name("extra"))
        elif change == "size":
            path.write_bytes(b"x")
        else:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with observed(monkeypatch, tmp_path) as ledger:
            expected = (
                ipc_root.IpcRootBusy
                if change == "busy"
                else ipc_root.IpcRootIntegrityError
            )
            with pytest.raises(expected) as caught:
                ipc_root.acquire_generation_metadata(spec_for(s))
            assert str(caught.value) == (
                "ipc_generation_busy"
                if change == "busy"
                else "ipc_root_integrity_invalid"
            )
            source_error = (
                s.c.DeploymentSourceBusy
                if change == "busy"
                else s.c.DeploymentSourceError
            )
            with pytest.raises(source_error):
                topology.acquire_slot(1)
            with pytest.raises(DeploymentPrepareError) as caught:
                service_for(topology)._acquire(1, None)
            assert caught.value.code == (
                "capacity" if change == "busy" else "dependency_unavailable"
            )
            ledger.assert_released()


def test_ordinary_service_capacity_and_digest_refusal(
    actual_sources, monkeypatch, tmp_path
):
    with actual_sources.open_topology() as topology:
        service = service_for(topology)
        with observed(monkeypatch, tmp_path) as ledger:
            with pytest.raises(DeploymentPrepareError) as caught:
                service._acquire(2, None)
            assert caught.value.code == "not_found"
            with pytest.raises(DeploymentPrepareError) as caught:
                service._acquire(1, {"slot_capacity": 1, "topology_sha256": "0" * 64})
            assert caught.value.code == "dependency_unavailable"
            ledger.assert_released()


@pytest.mark.parametrize("kind", CONTROLS)
@pytest.mark.parametrize("checkpoint", ["next_open", "parent_close", "final_stat"])
def test_raw_directory_unwinds_owned_child_and_parent(
    monkeypatch, tmp_path, kind, checkpoint
):
    primary = kind("primary")
    with observed(monkeypatch, tmp_path) as ledger:
        if checkpoint == "next_open":

            def open_child(name, *args, **kwargs):
                if ledger.records:
                    raise primary
                return ledger.tracked_open(name, *args, **kwargs)

            ledger.patch.setattr(os, "open", open_child)
        elif checkpoint == "parent_close":
            ledger.close_failure = lambda record: (
                (primary, "after") if record is ledger.records[0] else None
            )
        else:

            def failed_stat(fd):
                raise primary

            ledger.patch.setattr(os, "fstat", failed_stat)
        with pytest.raises(kind) as caught:
            ipc_root._open_absolute_directory(tmp_path, searchable_only=True)
        assert caught.value is primary
        ledger.assert_released()


@pytest.mark.parametrize("kind", CONTROLS)
def test_raw_regular_fstat_interruption_closes_local_fd(monkeypatch, tmp_path, kind):
    path = tmp_path / "regular"
    path.write_bytes(b"")
    parent = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    primary = kind("primary")
    try:
        with observed(monkeypatch, tmp_path) as ledger:

            def failed_stat(fd):
                raise primary

            ledger.patch.setattr(os, "fstat", failed_stat)
            with pytest.raises(kind) as caught:
                ipc_root._open_regular_at(
                    parent,
                    "regular",
                    uid=os.getuid(),
                    gid=os.getgid(),
                    mode=0o644,
                    writable=False,
                    exact_size=0,
                )
            assert caught.value is primary
            ledger.assert_released()
    finally:
        os.close(parent)


@pytest.mark.parametrize("kind", CONTROLS)
def test_endpoint_validation_primary_survives_secondary_cleanup(
    actual_sources, monkeypatch, tmp_path, kind
):
    primary, secondary = kind("primary"), ControlAbort("secondary")
    validate = ipc_root._validate_directory

    def failed_endpoint(fd, **kwargs):
        if kwargs["uid"] == 22001:
            raise primary
        return validate(fd, **kwargs)

    monkeypatch.setattr(ipc_root, "_validate_directory", failed_endpoint)
    with observed(monkeypatch, tmp_path) as ledger:
        ledger.close_failure = lambda record: (
            (secondary, "after") if record["name"] == "endpoint" else None
        )
        with pytest.raises(BaseException) as caught:
            ipc_root.acquire_generation_metadata(spec_for(actual_sources))
        assert caught.value is primary
        ledger.assert_released()


@pytest.mark.parametrize("kind", CONTROLS)
@pytest.mark.parametrize(
    "checkpoint",
    [
        "layout",
        "lock_open",
        "flock",
        "secret_open",
        "endpoint_open",
        "stat",
        "initial_recheck",
    ],
)
def test_metadata_acquisition_unwinds_every_checkpoint(
    actual_sources, monkeypatch, tmp_path, kind, checkpoint
):
    s, primary = actual_sources, kind("primary")
    with lock_observer(s) as lock, observed(monkeypatch, tmp_path) as ledger:
        original_open = os.open
        counts = {}

        def failed_open(name, *args, **kwargs):
            counts[name] = counts.get(name, 0) + 1
            targets = {
                "lock_open": "generation.lock",
                "secret_open": "boot-secret",
                "endpoint_open": "endpoint",
            }
            if name == targets.get(checkpoint) and counts[name] == 2:
                raise primary
            return original_open(name, *args, **kwargs)

        ledger.patch.setattr(os, "open", failed_open)
        if checkpoint == "layout":

            def failed_layout(*args, **kwargs):
                raise primary

            ledger.patch.setattr(ipc_root, "_validate_layout", failed_layout)
        if checkpoint == "flock":
            flock = fcntl.flock

            def failed_flock(fd, operation):
                result = flock(fd, operation)
                if operation == fcntl.LOCK_SH | fcntl.LOCK_NB:
                    raise primary
                return result

            ledger.patch.setattr(fcntl, "flock", failed_flock)
        if checkpoint == "stat":
            fstat = os.fstat

            def failed_stat(fd):
                if counts.get("endpoint") == 2:
                    raise primary
                return fstat(fd)

            ledger.patch.setattr(os, "fstat", failed_stat)
        if checkpoint == "initial_recheck":

            def failed_recheck(lease):
                assert len(ledger.live) == 4
                assert_locked(lock)
                raise primary

            ledger.patch.setattr(
                ipc_root.MetadataGenerationLease, "recheck_current", failed_recheck
            )
        with pytest.raises(kind) as caught:
            ipc_root.acquire_generation_metadata(spec_for(s))
        assert caught.value is primary
        ledger.assert_released()
        assert_unlocked(lock)


@pytest.mark.parametrize("kind", CONTROLS)
@pytest.mark.parametrize("release", ["before", "after"])
def test_pretransfer_cleanup_attempts_all_and_preserves_primary(
    actual_sources, monkeypatch, tmp_path, kind, release
):
    primary, secondary = kind("primary"), ControlAbort("secondary")
    with (
        lock_observer(actual_sources) as lock,
        observed(monkeypatch, tmp_path) as ledger,
    ):
        fstat = os.fstat

        def failed_stat(fd):
            if sum(r["name"] == "endpoint" for r in ledger.records) == 2:
                raise primary
            return fstat(fd)

        ledger.patch.setattr(os, "fstat", failed_stat)
        ledger.close_failure = lambda r: (
            (secondary, release)
            if r["name"] == "boot-secret"
            and sum(x["name"] == "endpoint" for x in ledger.records) == 2
            else None
        )
        with pytest.raises(BaseException) as caught:
            ipc_root.acquire_generation_metadata(spec_for(actual_sources))
        assert caught.value is primary
        ledger.assert_attempted()
        assert len(ledger.live) == (1 if release == "before" else 0)
        assert_unlocked(lock)


@pytest.mark.parametrize("kind", CONTROLS)
def test_returned_recheck_releases_only_transient_fd(
    actual_sources, monkeypatch, tmp_path, kind
):
    primary, secondary = kind("primary"), ControlAbort("secondary")
    with (
        lock_observer(actual_sources) as lock,
        observed(monkeypatch, tmp_path) as ledger,
    ):
        lease = ipc_root.acquire_generation_metadata(spec_for(actual_sources))
        retained = dict(ledger.live)
        validate = ipc_root._validate_directory

        def failed_current(fd, **kwargs):
            if fd not in retained:
                raise primary
            return validate(fd, **kwargs)

        with monkeypatch.context() as patch:
            patch.setattr(ipc_root, "_validate_directory", failed_current)
            ledger.close_failure = lambda r: (
                (secondary, "after")
                if r["name"] == "xs01" and r not in retained.values()
                else None
            )
            with pytest.raises(BaseException) as caught:
                lease.recheck_current()
            assert caught.value is primary
        assert ledger.live == retained
        assert not lease.closed
        assert_locked(lock)
        ledger.close_failure = None
        lease.close()
        ledger.assert_released()
        assert_unlocked(lock)


@pytest.mark.parametrize("kind", CONTROLS)
@pytest.mark.parametrize("target", ["unlock", "secret", "endpoint", "lock", "pair"])
def test_metadata_close_attempts_all_once(
    actual_sources, monkeypatch, tmp_path, kind, target
):
    primary = kind("cleanup")
    with (
        lock_observer(actual_sources) as lock,
        observed(monkeypatch, tmp_path) as ledger,
    ):
        lease = ipc_root.acquire_generation_metadata(spec_for(actual_sources))
        close_order = [
            lease._secret_fd,
            lease._endpoint_fd,
            lease._lock_fd,
            lease._pair_fd,
        ]
        attempts = []
        unlocks = []
        flock = fcntl.flock

        def unlock(fd, operation):
            if operation == fcntl.LOCK_UN and fd == lease._lock_fd:
                unlocks.append(fd)
                if target == "unlock":
                    raise primary
            return flock(fd, operation)

        ledger.patch.setattr(fcntl, "flock", unlock)
        target_fd = dict(zip(["secret", "endpoint", "lock", "pair"], close_order)).get(
            target
        )

        def fail_close(record):
            attempts.append(record["fd"])
            return (primary, "after") if record["fd"] == target_fd else None

        ledger.close_failure = fail_close
        with pytest.raises(kind) as caught:
            lease.close()
        assert caught.value is primary
        lease.close()
        assert len(unlocks) == 1
        assert attempts == close_order
        assert lease.closed
        ledger.assert_released()
        assert_unlocked(lock)


@pytest.mark.parametrize("kind", CONTROLS)
@pytest.mark.parametrize(
    "checkpoint", ["mapping", "metadata", "slot_recheck", "digest"]
)
def test_actual_service_chain_unwinds_without_closing_borrowed_source(
    actual_sources, monkeypatch, tmp_path, kind, checkpoint
):
    s, primary = actual_sources, kind("primary")
    with s.open_topology() as topology, lock_observer(s) as lock:
        original_mapping = topology._mapping_for
        original_metadata = ipc_root.MetadataGenerationLease.recheck_current
        original_slot = sources.SlotMetadataLease.recheck_current
        original_digest = sources.c.digest
        armed = False

        def mapping(required):
            if checkpoint == "mapping" and spec_for(s).pair_root in required:
                raise primary
            return original_mapping(required)

        def metadata(lease):
            if checkpoint == "metadata":
                raise primary
            return original_metadata(lease)

        def slot(lease):
            nonlocal armed
            original_slot(lease)
            if checkpoint == "slot_recheck":
                raise primary
            armed = True

        def digest(raw):
            if armed and raw == s.output.topology_bytes and checkpoint == "digest":
                raise primary
            return original_digest(raw)

        with monkeypatch.context() as patch:
            patch.setattr(topology, "_mapping_for", mapping)
            patch.setattr(ipc_root.MetadataGenerationLease, "recheck_current", metadata)
            patch.setattr(sources.SlotMetadataLease, "recheck_current", slot)
            patch.setattr(sources.c, "digest", digest)
            with observed(patch, tmp_path) as ledger:
                with pytest.raises(kind) as caught:
                    service_for(topology)._acquire(
                        1,
                        {
                            "slot_capacity": 1,
                            "topology_sha256": s.pins["topology_sha256"],
                        },
                    )
                assert caught.value is primary
                ledger.assert_released()
                assert_unlocked(lock)
        topology.recheck_current()


@pytest.mark.parametrize("kind", CONTROLS)
def test_slot_close_attempts_directory_after_metadata_cleanup_failure(
    actual_sources, monkeypatch, tmp_path, kind
):
    primary = kind("cleanup")
    with (
        actual_sources.open_topology() as topology,
        observed(monkeypatch, tmp_path) as ledger,
    ):
        lease = topology.acquire_slot(1)
        secret = lease.metadata_lease._secret_fd
        ledger.close_failure = lambda r: (
            (primary, "after") if r["fd"] == secret else None
        )
        with pytest.raises(kind) as caught:
            lease.close()
        assert caught.value is primary
        lease.close()
        ledger.assert_released()


@pytest.mark.parametrize("kind", CONTROLS)
@pytest.mark.parametrize("release", ["before", "after"])
def test_initial_recheck_primary_survives_retained_cleanup_failure(
    actual_sources, monkeypatch, tmp_path, kind, release
):
    primary, secondary = kind("primary"), ControlAbort("secondary")
    with (
        lock_observer(actual_sources) as lock,
        observed(monkeypatch, tmp_path) as ledger,
    ):

        def failed_recheck(lease):
            assert len(ledger.live) == 4
            secret_record = ledger.live[lease._secret_fd]
            ledger.close_failure = lambda record: (
                (secondary, release) if record is secret_record else None
            )
            raise primary

        ledger.patch.setattr(
            ipc_root.MetadataGenerationLease, "recheck_current", failed_recheck
        )
        with pytest.raises(kind) as caught:
            ipc_root.acquire_generation_metadata(spec_for(actual_sources))
        assert caught.value is primary
        ledger.assert_attempted()
        assert len(ledger.live) == (1 if release == "before" else 0)
        assert_unlocked(lock)


@pytest.mark.parametrize("primary_kind", [ipc_root.IpcRootIntegrityError, OSError])
def test_ordinary_metadata_primary_mapping_survives_secondary(
    actual_sources, monkeypatch, tmp_path, primary_kind
):
    primary, secondary = primary_kind(), ControlAbort("secondary")
    with observed(monkeypatch, tmp_path) as ledger:

        def failed_recheck(lease):
            secret_record = ledger.live[lease._secret_fd]
            ledger.close_failure = lambda record: (
                (secondary, "after") if record is secret_record else None
            )
            raise primary

        ledger.patch.setattr(
            ipc_root.MetadataGenerationLease, "recheck_current", failed_recheck
        )
        with pytest.raises(ipc_root.IpcRootIntegrityError) as caught:
            ipc_root.acquire_generation_metadata(spec_for(actual_sources))
        if isinstance(primary, ipc_root.IpcRootError):
            assert caught.value is primary
        assert str(caught.value) == "ipc_root_integrity_invalid"
        ledger.assert_released()


@pytest.mark.parametrize("kind", CONTROLS)
def test_service_digest_primary_survives_secondary_slot_cleanup(
    actual_sources, monkeypatch, tmp_path, kind
):
    primary, secondary = kind("primary"), ControlAbort("secondary")
    s = actual_sources
    with s.open_topology() as topology, lock_observer(s) as lock:
        slot_recheck, digest = (
            sources.SlotMetadataLease.recheck_current,
            sources.c.digest,
        )
        armed = False
        with observed(monkeypatch, tmp_path) as ledger:

            def checked(lease):
                nonlocal armed
                slot_recheck(lease)
                secret_record = ledger.live[lease.metadata_lease._secret_fd]
                ledger.close_failure = lambda record: (
                    (secondary, "after") if record is secret_record else None
                )
                armed = True

            def failed_digest(raw):
                if armed and raw == s.output.topology_bytes:
                    raise primary
                return digest(raw)

            ledger.patch.setattr(sources.SlotMetadataLease, "recheck_current", checked)
            ledger.patch.setattr(sources.c, "digest", failed_digest)
            with pytest.raises(kind) as caught:
                service_for(topology)._acquire(
                    1,
                    {"slot_capacity": 1, "topology_sha256": s.pins["topology_sha256"]},
                )
            assert caught.value is primary
            ledger.assert_released()
            assert_unlocked(lock)
        topology.recheck_current()


def test_service_digest_mismatch_survives_secondary_cleanup(
    actual_sources, monkeypatch, tmp_path
):
    with (
        actual_sources.open_topology() as topology,
        observed(monkeypatch, tmp_path) as ledger,
    ):
        original = sources.SlotMetadataLease.recheck_current

        def checked(lease):
            original(lease)
            secret_record = ledger.live[lease.metadata_lease._secret_fd]
            ledger.close_failure = lambda record: (
                (ControlAbort("secondary"), "after")
                if record is secret_record
                else None
            )

        ledger.patch.setattr(sources.SlotMetadataLease, "recheck_current", checked)
        with pytest.raises(DeploymentPrepareError) as caught:
            service_for(topology)._acquire(
                1, {"slot_capacity": 1, "topology_sha256": "0" * 64}
            )
        assert caught.value.code == "dependency_unavailable"
        ledger.assert_released()


def test_close_reports_first_error_after_all_attempts_and_ignores_oserror(
    actual_sources, monkeypatch, tmp_path
):
    with observed(monkeypatch, tmp_path) as ledger:
        lease = ipc_root.acquire_generation_metadata(spec_for(actual_sources))
        first, later = ControlAbort("first"), KeyboardInterrupt("later")
        retained = [
            ledger.live[fd]
            for fd in (
                lease._secret_fd,
                lease._endpoint_fd,
                lease._lock_fd,
                lease._pair_fd,
            )
        ]

        def close_failure(record):
            index = next(i for i, item in enumerate(retained) if record is item)
            return ([OSError(), first, later, later][index], "after")

        ledger.close_failure = close_failure
        flock = fcntl.flock

        def unlock(fd, operation):
            if operation == fcntl.LOCK_UN:
                raise OSError("ignored unlock")
            return flock(fd, operation)

        ledger.patch.setattr(fcntl, "flock", unlock)
        with pytest.raises(ControlAbort) as caught:
            lease.close()
        assert caught.value is first
        lease.close()
        ledger.assert_released()
