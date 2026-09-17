"""Task 25 slice 2b: the populated-generation fence
(contracts/extension-worker-probe.md §6; proposal §3).

A held `GenerationLease` keeps the shared rotation lock but closes its
boot-secret descriptor after the initial read, so a held generation alone
cannot establish named currentness once the endpoint is populated. The
fence borrows the actual generation, owns one additional no-follow
boot-secret descriptor plus fixed ancestry observations, and on every
recheck compares the named and held root/endpoint/lock/secret identities
and constant-time compares the reread 32 secret bytes with the generation's
secret. It permits populated endpoint files (`worker.sock`, `listener.json`)
— the absence-only `MetadataGenerationLease` is untouched — and never
outputs a secret.
"""

import copy
import os
import pickle
import stat

import pytest

from app.workers import ipc_root
from deploy.tests.test_ipc_root_initializer import layout as layout  # noqa: PLC0414


def open_fds():
    return {int(name) for name in os.listdir("/dev/fd")}


def retain(spec, generation):
    assert hasattr(ipc_root, "_retain_populated_generation"), "populated fence missing"
    return ipc_root._retain_populated_generation(spec, generation)


def test_the_fence_borrows_the_generation_and_owns_exactly_one_secret_descriptor(
    layout,
):
    ipc_root.initialize_pair_root(layout, entropy=lambda size: b"a" * size)
    (layout.endpoint_path / "worker.sock").touch()
    (layout.endpoint_path / ipc_root.LISTENER_NAME).write_bytes(b"{}")
    with ipc_root.acquire_generation(layout) as generation:
        before = open_fds()
        with retain(layout, generation) as fence:
            assert (
                len(open_fds() - before) == 1
            )  # one more open descriptor: the owned secret
            fence.recheck_current()  # populated endpoint files are permitted here
            with pytest.raises(ipc_root.IpcRootError):
                ipc_root.acquire_generation_metadata(
                    layout
                )  # absence-only lease untouched
            assert not hasattr(fence, "secret")
            assert "boot" not in repr(fence) and "a" * 8 not in repr(fence)
            for clone in (copy.copy, copy.deepcopy, pickle.dumps):
                with pytest.raises(TypeError):
                    clone(fence)
            with pytest.raises(TypeError):
                ipc_root.PopulatedGenerationFence()
            assert not generation.closed  # borrowed, not owned
        assert open_fds() == before
        assert not generation.closed
        fence.close()  # idempotent
        with pytest.raises(ipc_root.IpcRootError):
            fence.recheck_current()
        assert generation.pair_fd >= 0  # still usable after the fence closed


def test_a_closed_generation_fails_the_fence_and_the_fence_never_closes_it_twice(
    layout,
):
    ipc_root.initialize_pair_root(layout)
    generation = ipc_root.acquire_generation(layout)
    fence = retain(layout, generation)
    generation.close()
    with pytest.raises(ipc_root.IpcRootError):
        fence.recheck_current()
    fence.close()
    with pytest.raises(ipc_root.IpcRootError):
        retain(layout, generation)  # a closed generation cannot be borrowed
    with pytest.raises(ipc_root.IpcRootError):
        retain(layout, object())


def _traceback_locals(error):
    frames = []
    trace = error.__traceback__
    while trace is not None:
        frames.append(trace.tb_frame)
        trace = trace.tb_next
    values = []
    for frame in frames:
        values.extend(frame.f_locals.values())
    return values


def test_a_swapped_secret_of_correct_shape_is_caught_only_by_the_reread(layout):
    # review: rewriting the file in place bumps mtime/ctime, so the stat
    # compare fires first. The reread is load-bearing when boot-secret was
    # atomically replaced by another 32-byte file of correct uid/gid/mode
    # BETWEEN acquiring the generation and retaining the fence: the fence
    # then captures the swapped file's stats and only the constant-time
    # byte compare against the generation's secret can tell
    ipc_root.initialize_pair_root(layout, entropy=lambda size: b"a" * size)
    generation = ipc_root.acquire_generation(layout)
    try:
        path = layout.boot_secret_path
        info = path.lstat()
        swapped = path.with_name("boot-secret.swap")
        swapped.write_bytes(b"b" * 32)
        os.chmod(swapped, stat.S_IMODE(info.st_mode))
        os.chown(swapped, info.st_uid, info.st_gid)
        os.replace(swapped, path)
        with pytest.raises(ipc_root.IpcRootError):
            ipc_root._retain_populated_generation(layout, generation)
    finally:
        generation.close()


def test_the_reread_is_compared_even_when_the_stats_lie(layout, monkeypatch):
    ipc_root.initialize_pair_root(layout, entropy=lambda size: b"a" * size)
    with ipc_root.acquire_generation(layout) as generation:
        fence = retain(layout, generation)
        try:
            # freeze the stats per file (by inode) so only the byte compare
            # can notice the rewrite below
            lock_ino = layout.generation_lock_path.lstat().st_ino
            lock_stat, secret_stat = fence._lock_stat, fence._secret_stat
            monkeypatch.setattr(
                ipc_root,
                "_metadata_stat",
                lambda info: lock_stat if info.st_ino == lock_ino else secret_stat,
            )
            path = layout.boot_secret_path
            mode = stat.S_IMODE(path.lstat().st_mode)
            os.chmod(path, 0o600)
            path.write_bytes(b"b" * 32)
            os.chmod(path, mode)
            with pytest.raises(ipc_root.IpcRootError):
                fence.recheck_current()
            # a short reread (the stats still frozen) fails the fence too, and
            # the partially read secret bytes are not reachable through the
            # error's traceback frames afterwards
            os.chmod(path, 0o600)
            with path.open("r+b") as handle:
                handle.truncate(31)
            os.chmod(path, mode)
            with pytest.raises(ipc_root.IpcRootError) as failure:
                fence.recheck_current()
            assert not any(
                isinstance(item, (bytes, bytearray)) and b"b" * 8 in item
                for item in _traceback_locals(failure.value)
            )
        finally:
            fence.close()


@pytest.mark.parametrize("change", ["truncated", "hardlink", "symlink", "lock_deleted"])
def test_metadata_shape_drift_is_refused(layout, change):
    ipc_root.initialize_pair_root(layout, entropy=lambda size: b"a" * size)
    with (
        ipc_root.acquire_generation(layout) as generation,
        retain(layout, generation) as fence,
    ):
        secret = layout.boot_secret_path
        if change == "truncated":
            mode = stat.S_IMODE(secret.lstat().st_mode)
            os.chmod(secret, 0o600)
            with secret.open("r+b") as handle:
                handle.truncate(31)
            os.chmod(secret, mode)
        elif change == "hardlink":
            os.link(secret, secret.with_name("boot-secret.link"))
        elif change == "symlink":
            secret.rename(secret.with_name("boot-secret.real"))
            secret.symlink_to("boot-secret.real")
        else:
            layout.generation_lock_path.unlink()
        with pytest.raises(ipc_root.IpcRootError) as failure:
            fence.recheck_current()
        # these shapes are refused by the stat compare before any reread; the
        # traceback check is the same invariant the frozen-stats test enforces
        # on the reread path itself
        assert not any(
            isinstance(item, (bytes, bytearray))
            and (b"a" * 8 in item or b"b" * 8 in item)
            for item in _traceback_locals(failure.value)
        )


def test_a_root_replaced_by_a_symlink_is_refused(layout):
    ipc_root.initialize_pair_root(layout)
    with (
        ipc_root.acquire_generation(layout) as generation,
        retain(layout, generation) as fence,
    ):
        real = layout.pair_root.with_name(layout.pair_root.name + ".real")
        layout.pair_root.rename(real)
        layout.pair_root.symlink_to(real)
        with pytest.raises(ipc_root.IpcRootError):
            fence.recheck_current()


@pytest.mark.skipif(os.geteuid() != 0, reason="changing the endpoint owner needs root")
def test_endpoint_owner_drift_is_refused(layout):
    ipc_root.initialize_pair_root(layout)
    with (
        ipc_root.acquire_generation(layout) as generation,
        retain(layout, generation) as fence,
    ):
        os.chown(layout.endpoint_path, layout.responder_uid + 1, layout.pair_gid)
        with pytest.raises(ipc_root.IpcRootError):
            fence.recheck_current()


def test_every_acquisition_failure_unwinds_the_owned_descriptor(layout, monkeypatch):
    ipc_root.initialize_pair_root(layout, entropy=lambda size: b"a" * size)
    with ipc_root.acquire_generation(layout) as generation:
        before = open_fds()
        original = ipc_root._read_exact_secret

        def explode(descriptor):
            raise AssertionError("not an ipc error")

        # a BaseException from the initial recheck still unwinds the descriptor
        monkeypatch.setattr(ipc_root, "_read_exact_secret", explode)
        with pytest.raises(AssertionError):
            ipc_root._retain_populated_generation(layout, generation)
        assert open_fds() == before
        # a context entry whose recheck fails releases the owned descriptor
        monkeypatch.setattr(ipc_root, "_read_exact_secret", original)
        fence = retain(layout, generation)
        monkeypatch.setattr(ipc_root, "_read_exact_secret", explode)
        with pytest.raises(AssertionError):
            fence.__enter__()
        assert fence.closed and open_fds() == before
        # an OS failure AFTER the descriptor was opened (the retain function's
        # own fstat observations, the 2nd and 3rd calls) is the closed error,
        # never a raw AttributeError, and leaks nothing
        monkeypatch.setattr(ipc_root, "_read_exact_secret", original)
        real_fstat = os.fstat
        for failing_call in (2, 3):
            calls = {"count": 0}

            def fail_fstat(descriptor, *, failing=failing_call, calls=calls):
                calls["count"] += 1
                if calls["count"] == failing:
                    raise OSError("EIO")
                return real_fstat(descriptor)

            monkeypatch.setattr(ipc_root.os, "fstat", fail_fstat)
            with pytest.raises(ipc_root.IpcRootError):
                ipc_root._retain_populated_generation(layout, generation)
            monkeypatch.setattr(ipc_root.os, "fstat", real_fstat)
            assert calls["count"] == failing_call
            assert open_fds() == before


def test_rotation_stays_excluded_after_the_fence_closes_while_the_generation_lives(
    layout,
):
    ipc_root.initialize_pair_root(layout)
    with ipc_root.acquire_generation(layout) as generation:
        fence = retain(layout, generation)
        fence.close()
        with pytest.raises(ipc_root.IpcRootBusy):
            ipc_root.initialize_pair_root(layout)


@pytest.mark.parametrize(
    "target", ["generation.lock", "boot-secret", "endpoint", "root"]
)
def test_the_fence_detects_name_replacement(layout, target):
    ipc_root.initialize_pair_root(layout)
    with (
        ipc_root.acquire_generation(layout) as generation,
        retain(layout, generation) as fence,
    ):
        fence.recheck_current()
        path = layout.pair_root if target == "root" else layout.pair_root / target
        path.rename(path.with_name(path.name + ".old"))
        if target in {"endpoint", "root"}:
            path.mkdir()
        else:
            path.write_bytes(b"a" * (32 if target == "boot-secret" else 0))
        with pytest.raises(ipc_root.IpcRootError):
            fence.recheck_current()


@pytest.mark.parametrize("target", ["generation.lock", "boot-secret", "endpoint"])
def test_the_fence_detects_mode_drift(layout, target):
    ipc_root.initialize_pair_root(layout)
    with (
        ipc_root.acquire_generation(layout) as generation,
        retain(layout, generation) as fence,
    ):
        fence.recheck_current()
        path = layout.pair_root / target
        os.chmod(path, 0o777 if target == "endpoint" else 0o666)
        with pytest.raises(ipc_root.IpcRootError):
            fence.recheck_current()


def test_the_fence_never_outputs_the_secret_and_fails_closed_on_read_errors(
    layout, monkeypatch
):
    ipc_root.initialize_pair_root(layout, entropy=lambda size: b"a" * size)
    with (
        ipc_root.acquire_generation(layout) as generation,
        retain(layout, generation) as fence,
    ):
        original = os.read

        def broken(fd, size):
            raise OSError("disk")

        monkeypatch.setattr(ipc_root.os, "read", broken)
        with pytest.raises(ipc_root.IpcRootError) as failure:
            fence.recheck_current()
        assert "a" * 8 not in repr(failure.value) and "disk" not in str(failure.value)
        monkeypatch.setattr(ipc_root.os, "read", original)
        fence.recheck_current()


def test_the_fence_holds_the_shared_lock_through_the_generation(layout):
    ipc_root.initialize_pair_root(layout)
    with (
        ipc_root.acquire_generation(layout) as generation,
        retain(layout, generation) as fence,
    ):
        fence.recheck_current()
        with pytest.raises(ipc_root.IpcRootBusy):
            ipc_root.initialize_pair_root(layout)  # rotation stays excluded
