"""Independent real-FD legacy characterizations and bounded interruption tests.

UID/GID observations alone are simulated; no provider production/fixture imports.
"""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import public_init_files as p


@pytest.fixture
def tree(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir(mode=0o750)
    leaf = root / "value.json"
    leaf.write_bytes(b"unchanged")
    leaf.chmod(0o440)
    original_fd, original_at = f.stat_fd, f.stat_at

    def observed(info):
        values = {
            name: getattr(info, name) for name in dir(info) if name.startswith("st_")
        }
        values.update(st_uid=0, st_gid=0)
        return SimpleNamespace(**values)

    monkeypatch.setattr(f, "stat_fd", lambda fd: observed(original_fd(fd)))
    monkeypatch.setattr(f, "stat_at", lambda fd, name: observed(original_at(fd, name)))
    return root, leaf


def source(root):
    return f.SourceFile.open(
        root, "value.json", uid=0, gid=0, cap=9, pin=c.digest(b"unchanged")
    )


def invalid(call):
    with pytest.raises(c.DeploymentSourceError) as caught:
        call()
    assert type(caught.value) is c.DeploymentSourceError
    assert caught.value.code == "deployment_source_invalid"


def test_ordinary_success_and_borrowed_parent(tree):
    root, _ = tree
    with source(root) as opened:
        assert opened.read_current() == b"unchanged"
        assert opened.root.identity.inode == root.stat().st_ino
    with f.Directory.open(root) as parent:
        child = p._PublicInputFile.open(parent, "value.json", cap=9, modes=(0o440,))
        assert child.read_current() == b"unchanged"
        child.close()
        child.close()
        assert os.fstat(parent.fd).st_ino == root.stat().st_ino


@pytest.mark.parametrize(
    "change", ["symlink", "hardlink", "mode", "cap", "uid", "gid", "pin", "replace"]
)
def test_ordinary_source_denials(tree, change):
    root, leaf = tree
    if change == "replace":
        with source(root) as opened:
            leaf.rename(root / "old")
            leaf.write_bytes(b"unchanged")
            leaf.chmod(0o440)
            (root / "old").unlink()
            invalid(opened.read_current)
        return
    if change in ("symlink", "hardlink"):
        outside = root.parent / "original"
        leaf.rename(outside)
        if change == "symlink":
            leaf.symlink_to(outside)
        else:
            os.link(outside, leaf)
    if change == "mode":
        leaf.chmod(0o600)
    kwargs = {"uid": 0, "gid": 0, "cap": 9, "pin": c.digest(b"unchanged")}
    if change in ("uid", "gid"):
        kwargs[change] = 1
    if change == "cap":
        kwargs["cap"] = 8
    if change == "pin":
        kwargs["pin"] = "0" * 64
    invalid(lambda: f.SourceFile.open(root, "value.json", **kwargs))


def test_ordinary_paths_and_close_suppression(tmp_path):
    for path in ("/", Path("relative"), Path("/a/../b")):
        invalid(lambda path=path: f.open_directory(path))
    with pytest.raises(c.DeploymentSourceUnavailable) as caught:
        f.open_directory(tmp_path / "absent")
    assert caught.value.code == "deployment_source_unavailable"
    fd = os.open(tmp_path, os.O_RDONLY)
    os.close(fd)
    f.close_fd(fd)


@pytest.mark.parametrize("retain", [False, True])
def test_ordinary_namespace_order_and_ownership(tmp_path, monkeypatch, retain):
    root = tmp_path / "virgin"
    root.mkdir(mode=0o755)
    events = []
    mkdir, chmod, fsync = os.mkdir, os.fchmod, os.fsync
    monkeypatch.setattr(
        os,
        "mkdir",
        lambda name, *a, **kw: (events.append(("mkdir", name)), mkdir(name, *a, **kw))[
            1
        ],
    )
    monkeypatch.setattr(
        os, "fchown", lambda fd, uid, gid: events.append(("chown", uid, gid))
    )
    monkeypatch.setattr(
        os,
        "fchmod",
        lambda fd, mode: (events.append(("chmod", mode)), chmod(fd, mode))[1],
    )
    monkeypatch.setattr(
        os, "fsync", lambda fd: (events.append(("fsync",)), fsync(fd))[1]
    )
    # Model root ownership only, preserving all real descriptor/name/mode observations.
    original = f.stat_fd

    def modeled(fd):
        info = original(fd)
        return SimpleNamespace(
            **{
                **{n: getattr(info, n) for n in dir(info) if n.startswith("st_")},
                "st_uid": 0,
                "st_gid": 0,
            }
        )

    monkeypatch.setattr(f, "stat_fd", modeled)
    with f.Directory.open(root) as directory:
        result = p._install_namespaces_impl(
            directory, names=("cancelled", "requests"), uid=0, gid=0, retain=retain
        )
        assert isinstance(result, tuple)
        assert len(result) == (2 if retain else 0)
        for handle in result:
            assert handle.identity.mode == 0o750
            handle.close()
        os.fstat(directory.fd)
    assert events == [
        ("mkdir", "cancelled"),
        ("chown", 0, 0),
        ("chmod", 0o750),
        ("fsync",),
        ("fsync",),
        ("mkdir", "requests"),
        ("chown", 0, 0),
        ("chmod", 0o750),
        ("fsync",),
        ("fsync",),
        ("chown", 0, 0),
        ("chmod", 0o750),
        ("fsync",),
    ]


class Stop(BaseException):
    pass


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize(
    "point",
    [
        "walk_open",
        "walk_close",
        "regular_stat",
        "regular_validate",
        "directory_validate",
        "directory_recheck",
        "transient_validate",
        "source_members",
        "source_signature",
        "source_read",
        "public_signature",
        "public_read",
        "release_ancestor",
        "release_read",
    ],
)
@pytest.mark.parametrize("secondary", [False, True])
def test_acquisition_primary_and_all_owned_closes(
    tree, monkeypatch, point, kind, secondary
):
    root, leaf = tree
    parent = f.Directory.open(root)
    # Release ancestor ownership uses real directories under a mapped logical tree.
    if point.startswith("release"):
        leaf.chmod(0o444)
        monkeypatch.setattr(c, "RELEASE_ROOT", root)
        walk = f.open_directory
        monkeypatch.setattr(f, "open_directory", lambda path, **kw: walk(root, **kw))
    opened, closed = os.open, os.close
    live, attempts = set(), []

    def acquire(*a, **kw):
        fd = opened(*a, **kw)
        live.add(fd)
        return fd

    def release(fd):
        attempts.append(fd)
        live.remove(fd)
        closed(fd)

    monkeypatch.setattr(os, "open", acquire)
    monkeypatch.setattr(os, "close", release)
    primary, cleanup = kind("primary"), Stop("cleanup")
    target, name, number = {
        "walk_open": (os, "open", 2),
        "walk_close": (f, "close_fd", 1),
        "regular_stat": (f, "stat_fd", 1),
        "regular_validate": (f, "validate_regular", 1),
        "directory_validate": (f, "validate_directory", 1),
        "directory_recheck": (f.Directory, "recheck_current", 1),
        "transient_validate": (f, "validate_directory", 1),
        "source_members": (f, "members", 1),
        "source_signature": (f, "signature", 1),
        "source_read": (f.SourceFile, "read_current", 1),
        "public_signature": (f, "signature", 1),
        "public_read": (p._PublicInputFile, "_read_current", 1),
        "release_ancestor": (f.Directory, "open", 2),
        "release_read": (p._ReleaseInput, "read_current", 1),
    }[point]
    original = getattr(target, name)
    calls = 0
    fired = False

    def interrupt(*args, **kwargs):
        nonlocal calls, fired
        calls += 1
        if calls == number:
            fired = True
            if point == "walk_close":
                original(*args, **kwargs)
            raise primary
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, interrupt)
    if secondary:
        closer = f.close_fd
        failed = False

        def secondary_close(fd):
            nonlocal failed
            closer(fd)
            if fired and fd >= 0 and not failed:
                failed = True
                raise cleanup

        monkeypatch.setattr(f, "close_fd", secondary_close)

    def run():
        if point.startswith("walk"):
            return f.open_directory(root)
        if point.startswith("regular"):
            return f.open_regular(
                parent.fd, "value.json", uid=0, gid=0, mode=0o440, cap=9
            )
        if point == "transient_validate":
            return parent.recheck_current()
        if point.startswith("directory"):
            return f.Directory.open(root)
        if point.startswith("source"):
            return source(root)
        if point.startswith("public"):
            return p._PublicInputFile.open(parent, "value.json", cap=9, modes=(0o440,))
        return p._ReleaseInput.open("value.json", 9)

    try:
        with pytest.raises(BaseException) as caught:
            run()
        assert caught.value is primary
        assert not live, f"factory leaked returned descriptors: {live}"
        os.fstat(parent.fd)
    finally:
        monkeypatch.setattr(os, "close", closed)
        for fd in live:
            closed(fd)
        closed(parent.fd)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize("release_input", [False, True])
def test_aggregate_close_attempts_all_once(tree, monkeypatch, kind, release_input):
    root, leaf = tree
    if release_input:
        leaf.chmod(0o444)
        monkeypatch.setattr(c, "RELEASE_ROOT", root)
        walk = f.open_directory
        monkeypatch.setattr(f, "open_directory", lambda path, **kw: walk(root, **kw))
        handle = p._ReleaseInput.open("value.json", 9)
        expected = [handle._source.fd, *(x.fd for x in handle._ancestors)]
    else:
        handle = source(root)
        expected = [handle.fd, handle.root.fd]
    closer, attempts, sentinel = f.close_fd, [], kind("cleanup")

    def fail_first(fd):
        attempts.append(fd)
        closer(fd)
        if len(attempts) == 1:
            raise sentinel

    monkeypatch.setattr(f, "close_fd", fail_first)
    try:
        with pytest.raises(BaseException) as caught:
            handle.close()
        assert caught.value is sentinel
        assert attempts == expected
        handle.close()
        assert attempts == expected
    finally:
        for fd in expected:
            if fd not in attempts:
                closer(fd)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize(
    "checkpoint,position",
    [
        ("fchown", 1),
        ("fchown", 2),
        ("fchown", 3),
        ("fchmod", 1),
        ("fchmod", 2),
        ("fchmod", 3),
        ("fsync", 1),
        ("fsync", 2),
        ("fsync", 3),
        ("fsync", 5),
        ("mkdir", 2),
        ("adopt", 1),
        ("adopt", 2),
    ],
)
def test_namespace_retained_and_raw_handoff(
    tree, monkeypatch, checkpoint, position, kind
):
    root, leaf = tree
    leaf.unlink()
    root.chmod(0o755)
    parent = f.Directory.open(root)
    monkeypatch.setattr(os, "fchown", lambda *_: None)
    opened, closed = os.open, os.close
    live = set()

    def acquire(*a, **kw):
        fd = opened(*a, **kw)
        live.add(fd)
        return fd

    def release(fd):
        live.remove(fd)
        closed(fd)

    monkeypatch.setattr(os, "open", acquire)
    monkeypatch.setattr(os, "close", release)
    target, name = (p, "_take_directory") if checkpoint == "adopt" else (os, checkpoint)
    original = getattr(target, name)
    primary, cleanup = kind("primary"), Stop("secondary")
    calls, fired, failed = 0, False, False

    def interrupt(*a, **kw):
        nonlocal calls, fired
        calls += 1
        if calls == position:
            fired = True
            raise primary
        return original(*a, **kw)

    monkeypatch.setattr(target, name, interrupt)
    closer = f.close_fd

    def secondary(fd):
        nonlocal failed
        closer(fd)
        if fired and fd >= 0 and not failed:
            failed = True
            raise cleanup

    monkeypatch.setattr(f, "close_fd", secondary)
    try:
        with pytest.raises(BaseException) as caught:
            p._install_namespaces_retained(
                parent, names=("cancelled", "requests"), uid=0, gid=0
            )
        assert caught.value is primary
        assert not live
        os.fstat(parent.fd)
        assert (root / "cancelled").is_dir()  # failure is never rollback
    finally:
        monkeypatch.setattr(os, "close", closed)
        for fd in live:
            closed(fd)
        closed(parent.fd)


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
def test_refused_close_attempts_others_without_retry(tree, monkeypatch, kind):
    root, _ = tree
    opened = source(root)
    closer, attempts, refusal = f.close_fd, [], kind("OS refusal simulated")

    def refuse(fd):
        attempts.append(fd)
        if fd == opened.fd:
            raise refusal
        closer(fd)

    monkeypatch.setattr(f, "close_fd", refuse)
    try:
        with pytest.raises(BaseException) as caught:
            opened.close()
        assert caught.value is refusal
        assert attempts == [opened.fd, opened.root.fd]
        os.fstat(opened.fd)  # refusal is explicitly NOT evidence of successful close
        with pytest.raises(OSError):
            os.fstat(opened.root.fd)
        opened.close()
        assert attempts == [opened.fd, opened.root.fd]
    finally:
        closer(opened.fd)


@pytest.mark.parametrize(
    "point", ["regular", "directory", "source", "public", "release"]
)
def test_ordinary_primary_mapping_survives_secondary_cleanup(tree, monkeypatch, point):
    root, leaf = tree
    parent = f.Directory.open(root)
    if point == "release":
        leaf.chmod(0o444)
        monkeypatch.setattr(c, "RELEASE_ROOT", root)
        walk = f.open_directory
        monkeypatch.setattr(f, "open_directory", lambda path, **kw: walk(root, **kw))
    target, name = {
        "regular": (f, "validate_regular"),
        "directory": (f.Directory, "recheck_current"),
        "source": (f.SourceFile, "read_current"),
        "public": (p._PublicInputFile, "_read_current"),
        "release": (p._ReleaseInput, "read_current"),
    }[point]
    fired = False

    def primary(*_a, **_kw):
        nonlocal fired
        fired = True
        raise c.DeploymentSourceUnavailable()

    monkeypatch.setattr(target, name, primary)
    closer = f.close_fd

    def secondary(fd):
        closer(fd)
        if fired and fd >= 0:
            raise Stop("secondary")

    monkeypatch.setattr(f, "close_fd", secondary)
    calls = {
        "regular": lambda: f.open_regular(
            parent.fd, "value.json", uid=0, gid=0, mode=0o440, cap=9
        ),
        "directory": lambda: f.Directory.open(root),
        "source": lambda: source(root),
        "public": lambda: p._PublicInputFile.open(
            parent, "value.json", cap=9, modes=(0o440,)
        ),
        "release": lambda: p._ReleaseInput.open("value.json", 9),
    }
    try:
        invalid(calls[point])
        os.fstat(parent.fd)
    finally:
        closer(parent.fd)
