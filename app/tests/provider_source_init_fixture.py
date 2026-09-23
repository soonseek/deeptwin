"""Real temporary files/FDs; simulated ownership, logical paths and mount/native facts.

NOT native evidence. No host sources, Docker, credentials or provider calls.
The accepted Task35 independent oracle supplies bytes, never this initializer.
"""

import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import mounts as m
from app.deployment import publication as p
from app.deployment.provider_source_contracts import validate_provider_source_bundle
from app.deployment.provider_source_render import render_provider_sources
from app.tests.provider_source_fixture import case
from app.tests.support.inode_pins import identity_map

BASE = Path("/run/deeptwin")
INPUT = BASE / "provider-source-init-input"
TARGETS = tuple(
    BASE / name
    for name in (
        "provider-stage-sources",
        "provider-deployment-outbox",
        "provider-deployment-receipts",
        "provider-deployment-consumed",
    )
)
CHANNELS = (
    (TARGETS[1], "cancelled", 20102),
    (TARGETS[1], "requests", 20102),
    (TARGETS[2], "receipts", 20113),
    (TARGETS[3], "consumed", 20102),
)
RELEASE = (
    ("deploy/compose.yaml", "base_compose_bytes"),
    ("deploy/security/service-ids.json", "base_service_ids_bytes"),
    (
        "deploy/security/deployment-prepare-recipe-v1.json",
        "original_prepare_recipe_bytes",
    ),
    (
        "deploy/security/deployment-receipt-recipe-v1.json",
        "original_receipt_recipe_bytes",
    ),
    (
        "deploy/security/deployment-provider-source-recipe-v1.json",
        "provider_recipe_bytes",
    ),
)
CONFIGS = (
    ("original-prepare-instance.json", "original_prepare_instance_bytes"),
    ("original-receipt-instance.json", "original_receipt_instance_bytes"),
    ("original-trust-set.json", "original_trust_bytes"),
    ("provider-instance.json", "provider_instance_bytes"),
    ("provider-trust-set.json", "provider_trust_bytes"),
)


class Tree:
    def __init__(self, tmp_path, monkeypatch):
        self.base, self.metadata = tmp_path, identity_map(monkeypatch)
        self.kwargs, self.bundle, self.old = case()
        validate_provider_source_bundle(self.bundle)
        assert render_provider_sources(**self.kwargs).bundle_files == self.bundle
        self.originals = (
            (
                BASE / "extension-topology",
                "topology.json",
                20102,
                self.old.prepare_artifacts.topology_bytes,
            ),
            (
                BASE / "deployment-exchange",
                "exchange.json",
                21201,
                self.old.prepare_artifacts.exchange_bytes,
            ),
            (
                BASE / "deployment-verify-public",
                "trust-set.json",
                20102,
                self.old.trust_bytes,
            ),
            (
                BASE / "deployment-receipt-ingress",
                "ingress.json",
                21201,
                self.old.ingress_bytes,
            ),
            (
                BASE / "deployment-consumption-exchange",
                "consumption-exchange.json",
                21201,
                self.old.consumption_exchange_bytes,
            ),
        )
        self.raw_stat, self.raw_fstat = os.stat, os.fstat
        self.base.chmod(0o755)
        self.register(self.base, 0, 0)
        for logical in (
            Path("/opt"),
            c.RELEASE_ROOT,
            c.RELEASE_ROOT / "deploy",
            c.RELEASE_ROOT / "deploy/security",
            Path("/run"),
            BASE,
            INPUT,
        ):
            self.directory(logical, 0, 0, 0o750 if logical == INPUT else 0o755)
        for relative, key in RELEASE:
            self.write(c.RELEASE_ROOT / relative, self.kwargs[key], 0, 0, 0o644)
        for name, key in CONFIGS:
            self.write(INPUT / name, self.kwargs[key], 0, 0)
        self.write(INPUT / "provider-source-pins.json", self.bundle[17][1], 0, 0)
        for root, name, gid, raw in self.originals:
            self.directory(root, 0, gid, 0o750)
            self.write(root / name, raw, 0, gid)
        for root in TARGETS:
            self.directory(root, 0, 0, 0o755)
        device = self.raw_stat(tmp_path).st_dev
        self.device = f"{os.major(device)}:{os.minor(device)}"
        self.mount_lines = []
        for index, (root, readonly) in enumerate(
            (
                (c.RELEASE_ROOT, True),
                (INPUT, True),
                *((v, False) for v in TARGETS),
                *((v[0], True) for v in self.originals),
            ),
            100,
        ):
            self.mount_lines.append(
                f"{index} 1 {self.device} /volume-{index} {root} {'ro' if readonly else 'rw'} - ext4 /dev/synthetic rw\n"
            )
        monkeypatch.setattr(f, "stat_fd", lambda fd: self.observed(self.raw_fstat(fd)))
        monkeypatch.setattr(
            f,
            "stat_at",
            lambda fd, name: self.observed(
                self.raw_stat(name, dir_fd=fd, follow_symlinks=False)
            ),
        )
        open_directory = f.open_directory
        monkeypatch.setattr(
            f,
            "open_directory",
            lambda path, **kw: open_directory(self.actual(path), **kw),
        )
        monkeypatch.setattr(m, "native_platform", lambda: "linux/amd64")
        monkeypatch.setattr(
            m,
            "read_mountinfo",
            lambda: m.parse_mountinfo("".join(self.mount_lines).encode()),
        )
        monkeypatch.setattr(os, "geteuid", lambda: 0)
        self.live, self.paths, self.effects, self.peak = set(), {}, [], 0
        self.opened, self.closed = os.open, os.close

        def open_fd(path, flags, *a, **kw):
            parent = self.paths.get(kw.get("dir_fd"), Path("/"))
            actual = Path(path) if Path(path).is_absolute() else parent / path
            if flags & (os.O_CREAT | os.O_TRUNC):
                self.effect("open_write", actual)
            fd = self.opened(path, flags, *a, **kw)
            self.live.add(fd)
            self.paths[fd] = actual
            self.peak = max(self.peak, len(self.live))
            return fd

        def close_fd(fd):
            self.live.remove(fd)
            self.paths.pop(fd)
            self.closed(fd)

        monkeypatch.setattr(os, "open", open_fd)
        monkeypatch.setattr(os, "close", close_fd)

        def chown(fd, uid, gid):
            self.effect("chown", self.paths[fd])
            info = self.raw_fstat(fd)
            self.metadata[(info.st_dev, info.st_ino)] = uid, gid

        monkeypatch.setattr(os, "fchown", chown)
        chmod, mkdir, fsync = os.fchmod, os.mkdir, os.fsync
        monkeypatch.setattr(
            os,
            "fchmod",
            lambda fd, mode: (self.effect("chmod", self.paths[fd]), chmod(fd, mode))[1],
        )
        monkeypatch.setattr(
            os,
            "mkdir",
            lambda name, mode=0o777, **kw: (
                self.effect("mkdir", self.paths[kw["dir_fd"]] / name),
                mkdir(name, mode, **kw),
            )[1],
        )
        monkeypatch.setattr(
            os, "fsync", lambda fd: (self.effect("fsync", self.paths[fd]), fsync(fd))[1]
        )

        def rename(fd, old, new):
            self.effect("rename", self.paths[fd] / new)
            try:
                self.raw_stat(new, dir_fd=fd, follow_symlinks=False)
            except FileNotFoundError:
                os.rename(old, new, src_dir_fd=fd, dst_dir_fd=fd)
            else:
                raise c.DeploymentSourceError()

        monkeypatch.setattr(p, "_rename_noreplace", rename)

    def actual(self, path):
        return self.base.joinpath(*Path(path).parts[1:])

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

    def effect(self, operation, path):
        assert any(path.is_relative_to(self.actual(root)) for root in TARGETS), (
            operation,
            path,
        )
        self.effects.append((operation, path))

    def directory(self, logical, uid, gid, mode):
        path = self.actual(logical)
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
        self.register(path, uid, gid)

    def write(self, logical, raw, uid, gid, mode=0o440):
        path = self.actual(logical)
        path.write_bytes(raw)
        path.chmod(mode)
        self.register(path, uid, gid)
        return path

    def install(self, indices=(0, 1, 2, 3)):
        # Test setup uses pathlib mkdir, so it must not enter syscall effect spies.
        for index in indices:
            root = TARGETS[index]
            actual = self.actual(root)
            actual.chmod(0o750)
            self.register(actual, (0, 20102, 20113, 20102)[index], 21201)
            if index == 0:
                child = actual / "documents"
                self.mkdir_setup(child)
                self.register(child, 0, 21201)
                for name, raw in self.bundle:
                    self.write(root / "documents" / name, raw, 0, 21201)
            else:
                for parent, name, uid in CHANNELS:
                    if parent == root:
                        child = actual / name
                        self.mkdir_setup(child)
                        self.register(child, uid, 21201)

    def mkdir_setup(self, path):
        # pathlib calls the patched os.mkdir; the fixture saves this setup syscall.
        self.setup_mkdir(path, 0o750)

    def payload(
        self,
        namespace,
        number=1,
        raw=b"not JSON; false signature",
        stage=False,
        state=0,
    ):
        root, _, uid = next(row for row in CHANNELS if row[1] == namespace)
        name = f".stage-{UUID(int=number)}.tmp" if stage else f"{number:064x}.json"
        gid, mode = (
            ((uid, 0o600), (21201, 0o600), (21201, 0o440))[state]
            if stage
            else (21201, 0o440)
        )
        return self.write(root / namespace / name, raw, uid, gid, mode)

    def snapshot(self):
        return tuple(
            (
                str(path.relative_to(self.base)),
                f.signature(self.observed(self.raw_stat(path))),
                None if path.is_dir() else path.read_bytes(),
            )
            for root in TARGETS
            for path in (self.actual(root), *sorted(self.actual(root).rglob("*")))
        )


@pytest.fixture
def tree(tmp_path, monkeypatch):
    setup_mkdir = os.mkdir
    result = Tree(tmp_path, monkeypatch)
    result.setup_mkdir = setup_mkdir
    yield result
    for fd in tuple(result.live):
        result.closed(fd)
