import os
from pathlib import Path

import pytest

from app.tests.deployment_source_fixture import module


def line(mid=10, point="/sources", root="/volume", flags="ro", optional=""):
    return f"{mid} 1 8:1 {root} {point} {flags},nosuid {optional}- ext4 /dev/sda rw\n".encode()


def test_linux_mount_flags_backing_and_escapes():
    m = module("mounts")
    result = m.parse_mountinfo(line(root=r"/volume\040one"))
    assert result[0].root == Path("/volume one")
    assert result[0].read_only is True
    assert m.parse_mountinfo(line(flags="rw"))[0].read_only is False


@pytest.mark.parametrize(
    "raw",
    [
        line() + line(),
        line(mid=0),
        line(root="relative"),
        line(point="/a/../b"),
        line(root=r"/x\041"),
        line(root=r"/x\40"),
        line(root="/x\\"),
        line(flags="rw,ro"),
        line(flags="ro,ro"),
        line(optional="shared:1 shared:2 "),
        line().replace(b" - ", b" -- "),
        line().replace(b"8:1", b"8:x"),
        b"x" * 1048577,
        line(optional="x" * 8200 + " "),
    ],
    ids=[f"bad-{n}" for n in range(14)],
)
def test_malformed_mountinfo_denied(raw):
    m, c = module("mounts"), module("contracts")
    with pytest.raises(c.DeploymentSourceError):
        m.parse_mountinfo(raw)


def test_mount_alias_nested_and_backing_overlap_deny():
    m, c = module("mounts"), module("contracts")
    for raw in [
        line() + line(11, "/outbox", "/volume/sub", "rw"),
        line() + line(11, "/sources/nested", "/other"),
    ]:
        with pytest.raises(c.DeploymentSourceError):
            m.verify_boundaries(
                m.parse_mountinfo(raw), {Path("/sources"): True}, (Path("/outbox"),)
            )
    valid = line() + line(11, "/outbox", "/separate", "rw")
    a = m.verify_boundaries(
        m.parse_mountinfo(valid), {Path("/sources"): True}, (Path("/outbox"),)
    )
    b = m.verify_boundaries(
        m.parse_mountinfo(b"".join(reversed(valid.splitlines(keepends=True)))),
        {Path("/sources"): True},
        (Path("/outbox"),),
    )
    assert a == b


def test_real_retained_source_file_currentness(tmp_path):
    f, c = module("files"), module("contracts")
    tmp_path.chmod(0o750)
    path = tmp_path / "source.json"
    path.write_bytes(b"{}")
    path.chmod(0o440)
    with f.SourceFile.open(
        tmp_path,
        "source.json",
        uid=os.geteuid(),
        gid=os.getegid(),
        cap=10,
        pin=c.digest(b"{}"),
    ) as source:
        assert source.read_current() == b"{}"
        path.rename(tmp_path / "old")
        path.write_bytes(b"{}")
        path.chmod(0o440)
        with pytest.raises(c.DeploymentSourceError):
            source.read_current()
    source.close()
    with pytest.raises(c.DeploymentSourceError):
        source.read_current()


@pytest.mark.parametrize(
    "change",
    [
        "root_symlink",
        "file_symlink",
        "hardlink",
        "mode",
        "root_mode",
        "extra",
        "oversize",
        "pin",
    ],
)
def test_invalid_source_files_fail(tmp_path, change):
    f, c = module("files"), module("contracts")
    root = tmp_path / "root"
    root.mkdir(mode=0o750)
    path = root / "source.json"
    path.write_bytes(b"{}")
    path.chmod(0o440)
    if change == "root_symlink":
        root.rename(tmp_path / "actual")
        root.symlink_to(tmp_path / "actual", target_is_directory=True)
    elif change == "file_symlink":
        path.rename(root / "actual")
        path.symlink_to(root / "actual")
    elif change == "hardlink":
        os.link(path, tmp_path / "link")
    elif change == "mode":
        path.chmod(0o640)
    elif change == "root_mode":
        root.chmod(0o770)
    elif change == "extra":
        (root / "extra").touch()
    with pytest.raises(c.DeploymentSourceError):
        f.SourceFile.open(
            root,
            "source.json",
            uid=os.geteuid(),
            gid=os.getegid(),
            cap=1 if change == "oversize" else 10,
            pin=c.digest(b"other" if change == "pin" else b"{}"),
        )


def test_mountinfo_carriage_return_is_not_a_canonical_separator():
    m, c = module("mounts"), module("contracts")
    with pytest.raises(c.DeploymentSourceError):
        m.parse_mountinfo(line().replace(b"\n", b"\r\n"))


@pytest.mark.parametrize("change", ["truncate", "grow"])
def test_file_read_detects_concurrent_size_changes(tmp_path, monkeypatch, change):
    f, c = module("files"), module("contracts")
    path = tmp_path / "data"
    path.write_bytes(b"1234")
    fd = os.open(path, os.O_RDONLY)
    original = os.read

    def changing_read(descriptor, amount):
        result = original(descriptor, amount)
        if descriptor == fd:
            path.write_bytes(b"" if change == "truncate" else b"123456")
        return result

    monkeypatch.setattr(os, "read", changing_read)
    try:
        with pytest.raises(c.DeploymentSourceError):
            f.read_exact(fd, 10)
    finally:
        os.close(fd)


@pytest.mark.parametrize("system,machine", [("Darwin", "arm64"), ("Linux", "unknown")])
def test_native_platform_has_no_positive_non_linux_mode(monkeypatch, system, machine):
    m, c = module("mounts"), module("contracts")
    monkeypatch.setattr(m.platform, "system", lambda: system)
    monkeypatch.setattr(m.platform, "machine", lambda: machine)
    with pytest.raises(c.DeploymentSourceUnavailable):
        m.native_platform()


def test_mount_reader_enforces_cap_over_actual_file(tmp_path, monkeypatch):
    m, c = module("mounts"), module("contracts")
    path = tmp_path / "mountinfo"
    path.write_bytes(line() + b"x" * 1048576)
    original = os.open
    monkeypatch.setattr(m, "native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(
        os,
        "open",
        lambda name, flags: original(
            path if name == "/proc/self/mountinfo" else name, flags
        ),
    )
    with pytest.raises(c.DeploymentSourceError):
        m.read_mountinfo()
