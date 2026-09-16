"""Task 23: the fixed-file extension worker metadata source
(contracts/extension-worker-metadata.md; lineage values from Task 22).

Every test builds an actual temporary tree with the fixed relative leaves,
real shipped tool-port schema bytes (including the >64KiB result schema)
and a synthetic worker executable, then redirects ONLY the fixed root
constants and samples ownership/process/mount facts. File type, names,
inodes, sizes, modes and bytes are real. This is simulated Linux evidence,
not kernel or OCI proof: no real /opt, mount, user file or worker process
is touched.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import os
import pickle
import platform
import stat
import threading
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.deployment import mounts as m
from app.domain.refs import canonical_json
from app.extensions.port_contracts import PORT_SCHEMA_SHAPES
from app.tests.test_extension_lineage_contracts import (
    identity_mapping,
    shipped_schema_bytes,
)
from app.workers import extension_metadata as em
from app.workers.broker import Deadline

WORKER_BYTES = b"\x7fELF-synthetic-worker-" + bytes(range(256)) * 8
UID = GID = 22001


@dataclass(frozen=True)
class WorkerTree:
    root: Path
    prefix: Path
    identity_bytes: bytes
    worker: Path
    identity: Path
    schemas: tuple[Path, ...]

    @property
    def directories(self) -> tuple[Path, ...]:
        return (
            self.root,
            self.root / "opt",
            self.prefix,
            self.prefix / "bin",
            self.prefix / "identity",
            self.prefix / "ports",
            self.prefix / "ports" / "tool-port-v1",
        )


def _mountinfo(root: Path, extra: tuple[str, ...] = ()) -> bytes:
    info = root.stat()
    device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
    lines = [f"1 1 {device} / {root} ro,relatime shared:1 - tmpfs tmpfs rw", *extra]
    return ("\n".join(lines) + "\n").encode()


def _identity_bytes(worker_bytes: bytes, platform_name: str = "linux/amd64") -> bytes:
    mapping = identity_mapping(platform_name)
    mapping["entrypoint"] = {
        "sha256": hashlib.sha256(worker_bytes).hexdigest(),
        "size_bytes": len(worker_bytes),
    }
    return canonical_json(mapping)


def _write(path: Path, data: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    path.chmod(mode)


@pytest.fixture
def worker_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> WorkerTree:
    root = tmp_path / "root"
    prefix = root / "opt" / "deeptwin-extension"
    identity_bytes = _identity_bytes(WORKER_BYTES)
    worker = prefix / "bin" / "worker"
    identity = prefix / "identity" / "build-identity-v1.json"
    _write(worker, WORKER_BYTES, 0o555)
    _write(identity, identity_bytes, 0o444)
    schemas = []
    for role, raw in zip(PORT_SCHEMA_SHAPES, shipped_schema_bytes(), strict=True):
        path = prefix / "ports" / "tool-port-v1" / f"{role}.schema.json"
        _write(path, raw, 0o444)
        schemas.append(path)
    tree = WorkerTree(root, prefix, identity_bytes, worker, identity, tuple(schemas))
    for directory in tree.directories:
        directory.chmod(0o755)
    monkeypatch.setattr(em, "EXTENSION_ROOT", root)
    monkeypatch.setattr(em, "EXTENSION_PREFIX", prefix)
    monkeypatch.setattr(em, "_expected_owner", lambda: (os.getuid(), os.getgid()))
    monkeypatch.setattr(em, "_native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(em, "_credentials", lambda: (UID, UID, GID, GID))
    monkeypatch.setattr(
        em, "_read_mountinfo", lambda: m.parse_mountinfo(_mountinfo(root))
    )
    return tree


def _read(source):
    return source.read_current(deadline=Deadline.after_ms(1000))


def _relax(path: Path) -> None:
    """Make a 0444/0555 leaf writable for a mutation, restoring the mode after."""
    path.chmod(0o644)


def test_brief_mandated_reading_lifecycle(worker_tree):
    source = em.open_worker_metadata_source()
    try:
        result = source.read_current(deadline=Deadline.after_ms(1000))
        assert result.build_identity.content_bytes == worker_tree.identity_bytes
        assert result.platform == "linux/amd64"
        assert (result.uid, result.gid) == (22001, 22001)
        assert source.read_current(deadline=Deadline.after_ms(1000)) == result
    finally:
        source.close()
    assert source.closed
    source.close()
    with pytest.raises(em.WorkerMetadataClosed):
        source.read_current(deadline=Deadline.after_ms(1000))


def test_reading_is_frozen_observation_without_worker_bytes(worker_tree):
    with em.open_worker_metadata_source() as source:
        result = _read(source)
    assert set(result.__dataclass_fields__) == {
        "build_identity",
        "platform",
        "uid",
        "gid",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.platform = "linux/arm64"  # type: ignore[misc]
    assert WORKER_BYTES not in repr(result).encode()
    assert source.closed  # context manager exit closes


def test_direct_construction_and_copies_are_rejected(worker_tree):
    with pytest.raises(TypeError):
        em.WorkerMetadataSource()
    with em.open_worker_metadata_source() as source:
        with pytest.raises(TypeError):
            copy.copy(source)
        with pytest.raises(TypeError):
            copy.deepcopy(source)
        with pytest.raises(TypeError):
            pickle.dumps(source)


def test_errors_are_closed_fixed_codes():
    for cls, code in (
        (em.WorkerMetadataUnavailable, "worker_metadata_unavailable"),
        (em.WorkerMetadataInvalid, "worker_metadata_invalid"),
        (em.WorkerMetadataUnsupportedPlatform, "worker_metadata_unsupported_platform"),
        (em.WorkerMetadataClosed, "worker_metadata_closed"),
        (em.WorkerMetadataBusy, "worker_metadata_busy"),
        (em.WorkerMetadataDeadline, "worker_metadata_deadline"),
    ):
        error = cls()
        assert issubclass(cls, em.WorkerMetadataError)
        assert str(error) == code and error.code == code
        assert error.__cause__ is None


def test_unpatched_non_linux_factory_fails_before_any_path_access(monkeypatch):
    if platform.system() == "Linux":
        pytest.skip("Linux host: the unpatched factory would touch the real /opt tree")
    opened = []
    monkeypatch.setattr(os, "open", lambda *a, **k: opened.append(a) or -1)
    with pytest.raises(em.WorkerMetadataUnsupportedPlatform):
        em.open_worker_metadata_source()
    assert opened == []


def test_unsupported_platform_is_reported_when_sampled_platform_is_foreign(
    worker_tree,
    monkeypatch,
):
    def foreign():
        raise em.WorkerMetadataUnsupportedPlatform()

    monkeypatch.setattr(em, "_native_platform", foreign)
    with pytest.raises(em.WorkerMetadataUnsupportedPlatform):
        em.open_worker_metadata_source()


def _tracking(monkeypatch):
    real_open, real_close = os.open, os.close
    live: set[int] = set()
    peak = {"transient": 0}

    def tracked_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        live.add(fd)
        return fd

    def tracked_close(fd):
        live.discard(fd)
        real_close(fd)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "close", tracked_close)
    return live, peak


def test_exactly_thirteen_descriptors_are_retained_and_all_released(
    worker_tree, monkeypatch
):
    live, _ = _tracking(monkeypatch)
    source = em.open_worker_metadata_source()
    assert len(live) == 13
    _read(source)
    assert len(live) == 13  # every transient descriptor closed after a read
    source.close()
    assert live == set()


def test_transient_descriptors_stay_within_the_source_bound(worker_tree, monkeypatch):
    real_open = os.open
    counts = {"live": 0, "peak": 0}

    def counting_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        counts["live"] += 1
        counts["peak"] = max(counts["peak"], counts["live"])
        return fd

    real_close = os.close

    def counting_close(fd):
        counts["live"] -= 1
        real_close(fd)

    monkeypatch.setattr(os, "open", counting_open)
    monkeypatch.setattr(os, "close", counting_close)
    with em.open_worker_metadata_source() as source:
        _read(source)
    assert counts["peak"] <= 13 + 32


def test_partial_acquisition_failure_leaks_no_descriptor(worker_tree, monkeypatch):
    live, _ = _tracking(monkeypatch)
    worker_tree.schemas[2].unlink()
    with pytest.raises(em.WorkerMetadataUnavailable):  # a missing leaf is an OSError
        em.open_worker_metadata_source()
    assert live == set()


def test_wrong_deadline_type_and_expired_deadline_do_not_poison(worker_tree):
    with em.open_worker_metadata_source() as source:
        with pytest.raises(em.WorkerMetadataInvalid):
            source.read_current(deadline=1000)  # type: ignore[arg-type]
        expired = Deadline(1e-9 + 0.0000001)
        with pytest.raises(em.WorkerMetadataDeadline):
            source.read_current(deadline=expired)
        assert _read(source).platform == "linux/amd64"  # still fully usable
        assert not source.closed


def test_overlapping_read_or_close_is_busy_never_a_close(worker_tree):
    with em.open_worker_metadata_source() as source:
        holding = threading.Event()
        release = threading.Event()
        outcome = {}

        def slow_platform():
            holding.set()
            release.wait(5)
            return "linux/amd64"

        original = em._native_platform
        em._native_platform = slow_platform
        try:
            worker = threading.Thread(
                target=lambda: outcome.setdefault("r", _read(source))
            )
            worker.start()
            assert holding.wait(5)
            with pytest.raises(em.WorkerMetadataBusy):
                _read(source)
            with pytest.raises(em.WorkerMetadataBusy):
                source.close()
            assert not source.closed
            release.set()
            worker.join(5)
        finally:
            em._native_platform = original
        assert outcome["r"].platform == "linux/amd64"


@pytest.mark.parametrize(
    "mutation",
    [
        "identical_replace",
        "unlink",
        "truncate",
        "growth",
        "edit",
        "chmod_leaf",
        "chmod_dir",
        "ancestor_replace",
        "schema_edit",
        "worker_edit",
    ],
)
def test_every_post_open_mutation_is_invalid_and_poisons(worker_tree, mutation):
    source = em.open_worker_metadata_source()
    _read(source)
    t = worker_tree
    if mutation == "identical_replace":
        data = t.identity.read_bytes()
        _relax(t.identity)
        t.identity.unlink()
        _write(t.identity, data, 0o444)
    elif mutation == "unlink":
        _relax(t.identity)
        t.identity.unlink()
    elif mutation == "truncate":
        _relax(t.schemas[0])
        t.schemas[0].write_bytes(t.schemas[0].read_bytes()[:-1])
        t.schemas[0].chmod(0o444)
    elif mutation == "growth":
        _relax(t.schemas[1])
        t.schemas[1].write_bytes(t.schemas[1].read_bytes() + b" ")
        t.schemas[1].chmod(0o444)
    elif mutation == "edit":
        _relax(t.identity)
        data = bytearray(t.identity.read_bytes())
        data[-2] ^= 1
        t.identity.write_bytes(bytes(data))
        t.identity.chmod(0o444)
    elif mutation == "chmod_leaf":
        t.worker.chmod(0o755)
    elif mutation == "chmod_dir":
        (t.prefix / "bin").chmod(0o775)
    elif mutation == "ancestor_replace":
        moved = t.root / "opt" / "moved"
        t.prefix.rename(moved)
        import shutil

        shutil.copytree(moved, t.prefix)
    elif mutation == "schema_edit":
        _relax(t.schemas[3])
        data = bytearray(t.schemas[3].read_bytes())
        data[10] ^= 1
        t.schemas[3].write_bytes(bytes(data))
        t.schemas[3].chmod(0o444)
    elif mutation == "worker_edit":
        _relax(t.worker)
        data = bytearray(WORKER_BYTES)
        data[100] ^= 1
        t.worker.write_bytes(bytes(data))
        t.worker.chmod(0o555)
    # a vanished leaf surfaces as unavailable (OSError); every other drift is invalid
    expected = (
        em.WorkerMetadataUnavailable
        if mutation == "unlink"
        else em.WorkerMetadataInvalid
    )
    with pytest.raises(expected):
        _read(source)
    assert source.closed  # integrity/unavailable failure poisons the source
    with pytest.raises(em.WorkerMetadataClosed):
        _read(source)


@pytest.mark.parametrize("shape", ["symlink", "hardlink", "fifo", "directory"])
def test_non_regular_or_aliased_leaves_never_open(worker_tree, shape):
    t = worker_tree
    target = t.identity
    if shape == "symlink":
        _relax(target)
        target.unlink()
        real = t.root / "elsewhere.json"
        real.write_bytes(t.identity_bytes)
        real.chmod(0o444)
        target.symlink_to(real)
    elif shape == "hardlink":
        os.link(target, t.root / "alias.json")  # nlink becomes 2
    elif shape == "fifo":
        _relax(target)
        target.unlink()
        os.mkfifo(target, 0o444)
    elif shape == "directory":
        _relax(target)
        target.unlink()
        target.mkdir(0o755)
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()  # must not block on the FIFO either


def test_directory_inode_aliases_are_rejected(worker_tree):
    t = worker_tree
    (t.prefix / "ports" / "tool-port-v1").rename(t.root / "held")
    (t.prefix / "ports" / "tool-port-v1").symlink_to(t.root / "held")
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()


@pytest.mark.parametrize(
    "case", ["entrypoint_sha", "entrypoint_size", "platform", "schema_digest"]
)
def test_identity_schema_and_worker_mismatches_are_invalid(worker_tree, case):
    t = worker_tree
    mapping = identity_mapping("linux/arm64" if case == "platform" else "linux/amd64")
    mapping["entrypoint"] = {
        "sha256": (
            "0" * 64
            if case == "entrypoint_sha"
            else hashlib.sha256(WORKER_BYTES).hexdigest()
        ),
        "size_bytes": len(WORKER_BYTES) + (1 if case == "entrypoint_size" else 0),
    }
    if case == "schema_digest":
        mapping["port_schemas"][2]["sha256"] = "f" * 64
    _relax(t.identity)
    t.identity.write_bytes(canonical_json(mapping))
    t.identity.chmod(0o444)
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()


@pytest.mark.parametrize(
    "case", ["identity_cap", "schema_cap", "worker_cap", "empty_worker"]
)
def test_exact_byte_caps_are_enforced(worker_tree, case):
    t = worker_tree
    if case == "identity_cap":
        _relax(t.identity)
        t.identity.write_bytes(b"{" + b" " * 8192 + b"}")
        t.identity.chmod(0o444)
    elif case == "schema_cap":
        _relax(t.schemas[3])
        t.schemas[3].write_bytes(b"x" * 262145)
        t.schemas[3].chmod(0o444)
    elif case == "worker_cap":
        _relax(t.worker)
        with open(t.worker, "wb") as handle:
            handle.truncate(16_777_217)  # sparse: size is what the cap sees
        t.worker.chmod(0o555)
    elif case == "empty_worker":
        _relax(t.worker)
        t.worker.write_bytes(b"")
        t.worker.chmod(0o555)
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()


def _mount_line(
    mount_id: int, device: str, root: str, point: str, options: str = "ro,relatime"
) -> str:
    return f"{mount_id} 1 {device} {root} {point} {options} shared:{mount_id} - tmpfs tmpfs rw"


def _device(path: Path) -> str:
    info = path.stat()
    return f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"


@pytest.mark.parametrize(
    "case",
    [
        "root_rw",
        "mount_at_prefix",
        "mount_below_prefix",
        "intervening_opt",
        "same_device_alias",
        "other_device_root",
    ],
)
def test_mount_observations_reject_writable_root_prefix_mounts_and_aliases(
    worker_tree,
    monkeypatch,
    case,
):
    t = worker_tree
    device = _device(t.root)
    if case == "root_rw":
        info = t.root.stat()
        data = (
            f"1 1 {device} / {t.root} rw,relatime shared:1 - tmpfs tmpfs rw\n".encode()
        )
        del info
    elif case == "mount_at_prefix":
        data = _mountinfo(t.root, (_mount_line(2, "0:99", "/", str(t.prefix)),))
    elif case == "mount_below_prefix":
        data = _mountinfo(
            t.root, (_mount_line(2, "0:99", "/", str(t.prefix / "ports")),)
        )
    elif case == "intervening_opt":
        data = _mountinfo(t.root, (_mount_line(2, "0:99", "/", str(t.root / "opt")),))
    elif case == "same_device_alias":
        # a visible same-device mount whose backing root overlaps the prefix backing path
        data = _mountinfo(
            t.root, (_mount_line(2, device, "/opt", str(t.root / "srv" / "alias")),)
        )
    elif case == "other_device_root":
        data = f"1 1 0:99 / {t.root} ro,relatime shared:1 - tmpfs tmpfs rw\n".encode()
    monkeypatch.setattr(em, "_read_mountinfo", lambda: m.parse_mountinfo(data))
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()


def test_unrelated_mounts_and_order_are_accepted(worker_tree, monkeypatch):
    t = worker_tree
    extra = (
        _mount_line(5, "0:77", "/", str(t.root / "opt" / "another-product")),
        _mount_line(3, "0:66", "/", str(t.root / "run")),
    )
    monkeypatch.setattr(
        em, "_read_mountinfo", lambda: m.parse_mountinfo(_mountinfo(t.root, extra))
    )
    with em.open_worker_metadata_source() as source:
        first = _read(source)
        # a different unrelated order and an extra unrelated mount are not drift
        reordered = (
            extra[1],
            extra[0],
            _mount_line(9, "0:55", "/", str(t.root / "tmp")),
        )
        monkeypatch.setattr(
            em,
            "_read_mountinfo",
            lambda: m.parse_mountinfo(_mountinfo(t.root, reordered)),
        )
        assert _read(source) == first


def test_mount_and_process_drift_after_open_are_invalid_and_poison(
    worker_tree, monkeypatch
):
    t = worker_tree
    with em.open_worker_metadata_source() as source:
        _read(source)
        monkeypatch.setattr(
            em,
            "_read_mountinfo",
            lambda: m.parse_mountinfo(
                _mountinfo(t.root, (_mount_line(2, "0:99", "/", str(t.prefix)),))
            ),
        )
        with pytest.raises(em.WorkerMetadataInvalid):
            _read(source)
        assert source.closed
    monkeypatch.setattr(
        em, "_read_mountinfo", lambda: m.parse_mountinfo(_mountinfo(t.root))
    )
    with em.open_worker_metadata_source() as source:
        _read(source)
        monkeypatch.setattr(em, "_credentials", lambda: (UID, UID + 1, GID, GID))
        with pytest.raises(em.WorkerMetadataInvalid):
            _read(source)
        assert source.closed
    monkeypatch.setattr(em, "_credentials", lambda: (UID, UID, GID, GID))
    with em.open_worker_metadata_source() as source:
        _read(source)
        monkeypatch.setattr(em, "_native_platform", lambda: "linux/arm64")
        with pytest.raises(em.WorkerMetadataInvalid):
            _read(source)
        assert source.closed


@pytest.mark.parametrize(
    "credentials",
    [
        (0, 0, 0, 0),
        (UID, UID, 0, 0),
        (UID, UID + 1, GID, GID),
        (UID, UID, GID, GID + 1),
        (2**32, 2**32, GID, GID),
        (-1, -1, GID, GID),
    ],
)
def test_process_credentials_must_be_matching_nonzero_bounded(
    worker_tree, monkeypatch, credentials
):
    monkeypatch.setattr(em, "_credentials", lambda: credentials)
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()


def test_os_errors_become_unavailable_and_poison(worker_tree, monkeypatch):
    with em.open_worker_metadata_source() as source:
        _read(source)
        real_read = os.read

        def failing_read(fd, size):
            raise OSError(5, "input/output error")

        monkeypatch.setattr(os, "read", failing_read)
        with pytest.raises(em.WorkerMetadataUnavailable) as caught:
            _read(source)
        monkeypatch.setattr(os, "read", real_read)
        assert caught.value.__cause__ is None
        assert "input/output" not in str(caught.value)
        assert source.closed


def test_base_exception_during_read_closes_then_propagates(worker_tree, monkeypatch):
    source = em.open_worker_metadata_source()

    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(em, "_native_platform", interrupt)
    with pytest.raises(KeyboardInterrupt):
        _read(source)
    assert source.closed


def test_close_attempts_every_descriptor_despite_one_close_error(
    worker_tree, monkeypatch
):
    live, _ = _tracking(monkeypatch)
    source = em.open_worker_metadata_source()
    victim = sorted(live)[3]
    real_close = os.close

    def flaky_close(fd):
        if fd == victim:
            live.discard(fd)
            real_close(fd)
            raise OSError(9, "bad file descriptor")
        live.discard(fd)
        real_close(fd)

    monkeypatch.setattr(os, "close", flaky_close)
    source.close()  # must not raise, must keep closing the rest
    assert source.closed
    assert live == set()


def test_real_shipped_result_schema_exceeds_64kib(worker_tree):
    assert worker_tree.schemas[2].stat().st_size > 65536
    with em.open_worker_metadata_source() as source:
        assert (
            _read(source).build_identity.as_dict()["port_schemas"][2]["size_bytes"]
            > 65536
        )


def test_leaf_modes_are_exact(worker_tree):
    assert stat.S_IMODE(worker_tree.worker.stat().st_mode) == 0o555
    worker_tree.identity.chmod(0o440)
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()


# --- independent review closures (2026-09-16) ---------------------------------


@pytest.mark.parametrize(
    "case",
    ["below_prefix_other_device", "below_prefix_same_device", "below_bin"],
)
def test_any_mount_below_the_prefix_refuses_even_off_the_named_chain(
    worker_tree, monkeypatch, case
):
    t = worker_tree
    device = _device(t.root)
    if case == "below_prefix_other_device":
        extra = (_mount_line(2, "0:99", "/", str(t.prefix / "extra")),)
    elif case == "below_prefix_same_device":
        extra = (_mount_line(2, device, "/var/lib", str(t.prefix / "extra")),)
    else:
        extra = (_mount_line(2, "0:99", "/", str(t.prefix / "bin" / "extra")),)
    monkeypatch.setattr(
        em, "_read_mountinfo", lambda: m.parse_mountinfo(_mountinfo(t.root, extra))
    )
    with pytest.raises(em.WorkerMetadataInvalid):
        em.open_worker_metadata_source()


def test_a_base_exception_in_the_factory_tail_releases_every_descriptor(
    worker_tree, monkeypatch
):
    live, _ = _tracking(monkeypatch)

    def interrupted():
        raise KeyboardInterrupt

    monkeypatch.setattr(em.threading, "Lock", interrupted)
    with pytest.raises(KeyboardInterrupt):
        em.open_worker_metadata_source()
    assert live == set()


def test_an_os_error_while_opening_a_leaf_is_unavailable_not_invalid(
    worker_tree, monkeypatch
):
    real_open = os.open

    def denied(*args, **kwargs):
        if args and args[0] == "worker":
            raise PermissionError(13, "denied")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(os, "open", denied)
    with pytest.raises(em.WorkerMetadataUnavailable):
        em.open_worker_metadata_source()


def test_the_deadline_is_checked_between_identity_and_schema_chunks(
    worker_tree, monkeypatch
):
    from app.workers import broker

    with em.open_worker_metadata_source() as source:
        real_read = os.read
        clock = {"now": broker.time.monotonic(), "worker_seen": False}
        monkeypatch.setattr(broker.time, "monotonic", lambda: clock["now"])
        deadline = Deadline.after_ms(1000)
        state = {"jumped": False}

        def slow_read(fd, size):
            data = real_read(fd, size)
            # the FIRST schema chunk takes "longer" than the whole budget
            if not state["jumped"] and data.startswith(b"{") and len(data) > 100:
                state["jumped"] = True
                clock["now"] += 5.0
            return data

        monkeypatch.setattr(os, "read", slow_read)
        with pytest.raises(em.WorkerMetadataDeadline):
            source.read_current(deadline=deadline)
        assert not source.closed  # a deadline never poisons


def test_exit_never_replaces_a_propagating_exception_with_busy(worker_tree):
    source = em.open_worker_metadata_source()
    source._lock.acquire()  # simulate a read in flight on another thread
    try:
        with pytest.raises(RuntimeError, match="caller failure"), source:
            raise RuntimeError("caller failure")
    finally:
        source._lock.release()
    assert not source.closed
    with pytest.raises(em.WorkerMetadataBusy):
        source._lock.acquire()
        try:
            with source:
                pass  # no exception in flight: busy close still surfaces
        finally:
            source._lock.release()
    source.close()
