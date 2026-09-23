"""Independent real reader tree; logical paths, uid/gid, native and mounts simulated.

No initializer is invoked. These observations are NOT native isolation evidence.
"""

import importlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import mounts as m
from app.operations.setup import OriginProfile
from app.tests.provider_source_fixture import case
from app.tests.support.inode_pins import identity_map

BASE = Path("/run/deeptwin")
STATIC = BASE / "provider-stage-sources"
CHANNELS = (
    (BASE / "provider-deployment-outbox", "cancelled", 20102, False, 16, 8192),
    (BASE / "provider-deployment-outbox", "requests", 20102, False, 16, 65536),
    (BASE / "provider-deployment-receipts", "receipts", 20113, True, 64, 16384),
    (BASE / "provider-deployment-consumed", "consumed", 20102, False, 16, 8192),
)
ORIGINALS = (
    (BASE / "extension-topology", "topology.json", 20102, 2),
    (BASE / "deployment-exchange", "exchange.json", 21201, 3),
    (BASE / "deployment-verify-public", "trust-set.json", 20102, 6),
    (BASE / "deployment-receipt-ingress", "ingress.json", 21201, 7),
    (BASE / "deployment-consumption-exchange", "consumption-exchange.json", 21201, 8),
)


def reader_module():
    try:
        return importlib.import_module("app.deployment.provider_sources")
    except ModuleNotFoundError as error:
        assert error.name == "app.deployment.provider_sources"
        pytest.fail("Actual retained provider source reader is missing")


class ReaderTree:
    def __init__(self, tmp_path, monkeypatch, **options):
        # `opens` is a per-open ledger read by two modules only; recording it in every
        # tree made the 64-execute capacity test retain ~17 M entries (a 3 GB heap whose
        # cyclic collection paused a later test's IPC for 13–30 s): opt in to record.
        self.record_opens = bool(options.pop("record_opens", False))
        self.base, self.metadata, self.mount_lines = tmp_path, identity_map(monkeypatch), []
        _, self.bundle, self.old = case(**options)
        self.profile = OriginProfile.from_dict(
            json.loads(self.bundle[1][1])["origin_profile"]
        )
        self.platform = options.get("platform", "linux/amd64")
        self.raw_stat, self.raw_fstat = os.stat, os.fstat
        device = self.raw_stat(tmp_path).st_dev
        self.device = f"{os.major(device)}:{os.minor(device)}"
        self.directory(STATIC, 0, 21201)
        self.directory(STATIC / "documents", 0, 21201)
        self.mount(STATIC, True)
        self.install_bundle(self.bundle)
        for root, leaf, gid, index in ORIGINALS:
            self.directory(root, 0, gid)
            self.write(root / leaf, self.bundle[index][1], 0, gid)
            self.mount(root, True)
        for root, name, uid, ro, _, _ in CHANNELS:
            self.directory(root, uid, 21201)
            self.directory(root / name, uid, 21201)
            if not any(f" {root} " in line for line in self.mount_lines):
                self.mount(root, ro)
        for path in c.BUILTIN_ROOTS:
            self.directory(path, 20102, 20102)
            self.mount(path, False)
        open_directory = f.open_directory
        monkeypatch.setattr(
            f,
            "open_directory",
            lambda path, **kw: open_directory(self.actual(path), **kw),
        )
        monkeypatch.setattr(f, "stat_fd", lambda fd: self.observed(self.raw_fstat(fd)))
        monkeypatch.setattr(
            f,
            "stat_at",
            lambda fd, name: self.observed(
                self.raw_stat(name, dir_fd=fd, follow_symlinks=False)
            ),
        )
        monkeypatch.setattr(m, "native_platform", lambda: self.platform)
        monkeypatch.setattr(
            m,
            "read_mountinfo",
            lambda: m.parse_mountinfo("".join(self.mount_lines).encode()),
        )
        self.live, self.paths, self.peak, self.opens = set(), {}, 0, []
        self.active_scans = 0
        self.raw_open, self.raw_close = os.open, os.close
        raw_scandir = os.scandir

        def opened(path, flags, *args, **kw):
            fd = self.raw_open(path, flags, *args, **kw)
            parent = self.paths.get(kw.get("dir_fd"), Path("/"))
            actual = Path(path) if Path(path).is_absolute() else parent / path
            self.paths[fd] = actual
            self.live.add(fd)
            if self.record_opens:
                self.opens.append((actual, flags))
            self.peak = max(self.peak, len(self.live) + self.active_scans)
            return fd

        def closed(fd):
            self.live.discard(fd)
            self.paths.pop(fd, None)
            self.raw_close(fd)

        monkeypatch.setattr(os, "open", opened)
        monkeypatch.setattr(os, "close", closed)

        @contextmanager
        def scanned(path):
            # scandir owns a directory descriptor (including its duplicate for
            # an FD argument), acquired inside CPython rather than os.open.
            entries = raw_scandir(path)
            self.active_scans += 1
            self.peak = max(self.peak, len(self.live) + self.active_scans)
            try:
                yield entries
            finally:
                entries.close()
                self.active_scans -= 1

        monkeypatch.setattr(os, "scandir", scanned)

    def actual(self, path):
        path = Path(path)
        return (
            path
            if path.is_relative_to(self.base)
            else self.base.joinpath(*path.parts[1:])
        )

    def register(self, path, uid, gid):
        info = self.raw_stat(path, follow_symlinks=False)
        self.metadata[(info.st_dev, info.st_ino)] = uid, gid

    def observed(self, info):
        uid, gid = self.metadata.get(
            (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
        )
        return SimpleNamespace(
            **{
                **{k: getattr(info, k) for k in dir(info) if k.startswith("st_")},
                "st_uid": uid,
                "st_gid": gid,
            }
        )

    def directory(self, path, uid, gid):
        actual = self.actual(path)
        actual.mkdir(parents=True, exist_ok=True)
        actual.chmod(0o750)
        self.register(actual, uid, gid)

    def write(self, path, raw, uid, gid, mode=0o440):
        actual = self.actual(path)
        if actual.exists():
            actual.chmod(0o640)
        actual.write_bytes(raw)
        actual.chmod(mode)
        self.register(actual, uid, gid)
        return actual

    def mount(self, path, ro, backing=None):
        index = 100 + len(self.mount_lines)
        self.mount_lines.append(
            f"{index} 1 {self.device} {backing or f'/volume-{index}'} {path} {'ro' if ro else 'rw'} - ext4 /synthetic rw\n"
        )

    def install_bundle(self, bundle):
        for name, raw in bundle:
            self.write(STATIC / "documents" / name, raw, 0, 21201)

    def payload(self, namespace, number=1, *, stage=False, state=0, raw=b"not JSON"):
        root, _, uid, _, _, _ = next(row for row in CHANNELS if row[1] == namespace)
        name = f".stage-{UUID(int=number)}.tmp" if stage else f"{number:064x}.json"
        gid, mode = (
            ((uid, 0o600), (21201, 0o600), (21201, 0o440))[state]
            if stage
            else (21201, 0o440)
        )
        return self.write(root / namespace / name, raw, uid, gid, mode)

    def open(self, **changes):
        return reader_module().open_provider_source_context(
            **{
                "profile": self.profile,
                "context_sha256": c.digest(self.bundle[16][1]),
                "protected_roots": (),
                **changes,
            }
        )


@pytest.fixture
def reader_tree(tmp_path, monkeypatch):
    result = ReaderTree(tmp_path, monkeypatch, record_opens=True)  # its modules read `opens`
    yield result
    for fd in tuple(result.live):
        result.raw_close(fd)
