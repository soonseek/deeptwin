"""Real finite release inputs and OS fixtures for deployment source tests."""

import importlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.domain.refs import canonical_json
from app.operations.setup import OriginProfile
from app.tests.support.inode_pins import identity_map

ROOT = Path(__file__).resolve().parents[2]
BASE_HASH = "6a18faa38379724a18466f39b42f66c4405fe11eb790b8e9c21addd39cbd152e"
IDS_HASH = "4330b2080d5579847909fb086ebde6144b1fc54fdee6251a97383acd1e5565f4"


def module(name):
    try:
        return importlib.import_module("app.deployment." + name)
    except ModuleNotFoundError:
        assert False, "Concrete deployment source implementation is missing"


def profile(portable=False, instance="1" * 32):
    if portable:
        return OriginProfile.portable(instance_id=instance, url="https://example.org/")
    return OriginProfile.local(instance_id=instance, path_id="2" * 32, port=8080)


def instance(capacity=1, platform="linux/amd64", portable=False, identity="1" * 32):
    return {
        "schema_version": "deployment-prepare-instance-v1",
        "origin_profile": profile(portable, identity).as_dict(),
        "topology_id": "11111111-1111-4111-8111-111111111111",
        "exchange_id": "22222222-2222-4222-8222-222222222222",
        "platform": platform,
        "slot_capacity": capacity,
    }


def recipe():
    return {
        "schema_version": "deployment-prepare-recipe-v1",
        "recipe_id": "ordinary-tool-slots-v1",
        "base_compose": {
            "path": "deploy/compose.yaml",
            "sha256": BASE_HASH,
            "size_bytes": 25731,
        },
        "base_service_ids": {
            "path": "deploy/security/service-ids.json",
            "sha256": IDS_HASH,
            "size_bytes": 9544,
        },
        "renderer_id": "deeptwin-prepare-expand-v1",
        "initializer_id": "deeptwin-prepare-source-init-v1",
        "slot_capacity_max": 16,
        "slot_budget": {
            "memory_bytes": 1073741824,
            "cpu_millicores": 1000,
            "pids_limit": 128,
            "tmpfs_bytes": 134217728,
        },
    }


def inputs(**kwargs):
    return (
        (ROOT / "deploy/compose.yaml").read_bytes(),
        (ROOT / "deploy/security/service-ids.json").read_bytes(),
        canonical_json(recipe()),
        canonical_json(instance(**kwargs)),
    )


def artifacts(**kwargs):
    return module("render").render_prepare_sources(*inputs(**kwargs))


def decoded_artifacts(**kwargs):
    output = artifacts(**kwargs)
    return [
        json.loads(getattr(output, field))
        for field in (
            "topology_bytes",
            "exchange_bytes",
            "pins_bytes",
            "expanded_compose_bytes",
            "expansion_record_bytes",
        )
    ]


class ActualSources:
    """Real temp files/FDs with synthetic ownership and Linux mount observations."""

    def __init__(self, tmp_path, monkeypatch, *, capacity=1):
        self.c, self.f, self.m = module("contracts"), module("files"), module("mounts")
        self.slot_capacity = capacity
        self.instance_bytes = inputs(capacity=capacity)[3]
        self.output = artifacts(capacity=capacity)
        self.pins = json.loads(self.output.pins_bytes)
        self.base = tmp_path
        self.metadata = identity_map(monkeypatch)
        self.original_stat = os.stat
        self.original_fstat = os.fstat
        self.original_open_directory = self.f.open_directory
        device = self.original_stat(tmp_path).st_dev
        self.device = f"{os.major(device)}:{os.minor(device)}"
        self.mount_lines = []
        paths = [
            (self.c.TOPOLOGY_ROOT, 0, 20102, True),
            (self.c.EXCHANGE_ROOT, 0, 21201, True),
            (self.c.OUTBOX_ROOT, 20102, 21201, False),
        ] + [
            (self.c.IPC_ROOT / f"xs{number:02}", 0, 23000 + number, True)
            for number in range(1, capacity + 1)
        ]
        paths += [(p, 20102, 20102, False) for p in self.c.BUILTIN_ROOTS]
        for index, (path, uid, gid, ro) in enumerate(paths, 1):
            actual = self.actual(path)
            actual.mkdir(parents=True, exist_ok=True)
            actual.chmod(0o750)
            self.register(actual, uid, gid)
            self.mount_lines.append(
                f"{index} 999 {self.device} /vol{index} {path} {'ro' if ro else 'rw'} - ext4 /dev/fake rw\n"
            )
        for root, name, content, gid in [
            (self.c.TOPOLOGY_ROOT, "topology.json", self.output.topology_bytes, 20102),
            (self.c.EXCHANGE_ROOT, "exchange.json", self.output.exchange_bytes, 21201),
        ]:
            path = self.actual(root) / name
            path.write_bytes(content)
            path.chmod(0o440)
            self.register(path, 0, gid)
        for name in ("requests", "cancelled"):
            path = self.actual(self.c.OUTBOX_ROOT) / name
            path.mkdir(mode=0o750)
            self.register(path, 20102, 21201)

        def observed(info):
            uid, gid = self.metadata.get(
                (info.st_dev, info.st_ino), (info.st_uid, info.st_gid)
            )
            values = {
                name: getattr(info, name)
                for name in dir(info)
                if name.startswith("st_")
            }
            return SimpleNamespace(**(values | {"st_uid": uid, "st_gid": gid}))

        monkeypatch.setattr(os, "fstat", lambda fd: observed(self.original_fstat(fd)))
        monkeypatch.setattr(
            os,
            "stat",
            lambda *args, **kwargs: observed(self.original_stat(*args, **kwargs)),
        )

        def chown(fd, uid, gid):
            info = self.original_fstat(fd)
            old_uid, old_gid = self.metadata.get(
                (info.st_dev, info.st_ino), (20102, 20102)
            )
            self.metadata[(info.st_dev, info.st_ino)] = (
                old_uid if uid == -1 else uid,
                old_gid if gid == -1 else gid,
            )

        monkeypatch.setattr(os, "fchown", chown)
        original_unlink = os.unlink

        def unlink(path, *, dir_fd=None):
            # ext4 hands a removed file's inode number straight to the next file: an
            # unlinked last link forgets its controlled identity so a new file never
            # inherits it
            try:
                info = self.original_stat(path, dir_fd=dir_fd, follow_symlinks=False)
            except OSError:
                info = None
            original_unlink(path, dir_fd=dir_fd)
            if info is not None and info.st_nlink <= 1:
                self.metadata.pop((info.st_dev, info.st_ino), None)

        monkeypatch.setattr(os, "unlink", unlink)
        monkeypatch.setattr(
            self.f,
            "open_directory",
            lambda path, **kwargs: self.original_open_directory(
                self.actual(path), **kwargs
            ),
        )
        monkeypatch.setattr(self.m, "native_platform", lambda: "linux/amd64")
        monkeypatch.setattr(
            self.m,
            "read_mountinfo",
            lambda: self.m.parse_mountinfo("".join(self.mount_lines).encode()),
        )
        from app.workers import ipc_root

        original_ipc_open = ipc_root._open_absolute_directory
        monkeypatch.setattr(
            ipc_root,
            "_open_absolute_directory",
            lambda path, **kwargs: original_ipc_open(self.actual(path), **kwargs),
        )
        for number in range(1, capacity + 1):
            pair = self.actual(self.c.IPC_ROOT / f"xs{number:02}")
            pair.chmod(0o710)
            for name, size in (("generation.lock", 0), ("boot-secret", 32)):
                path = pair / name
                path.write_bytes(b"a" * size)
                path.chmod(0o640)
                self.register(path, 0, 23000 + number)
            endpoint = pair / "endpoint"
            endpoint.mkdir()
            endpoint.chmod(0o2710)
            self.register(endpoint, 22000 + number, 23000 + number)

    def actual(self, path):
        return self.base.joinpath(*Path(path).parts[1:])

    def register(self, path, uid, gid):
        info = self.original_stat(path, follow_symlinks=False)
        self.metadata[(info.st_dev, info.st_ino)] = uid, gid

    def open_exchange(self):
        return module("sources").open_exchange_source(
            profile=profile(),
            recipe_sha256=self.pins["recipe_sha256"],
            instance_sha256=self.pins["instance_sha256"],
            exchange_sha256=self.pins["exchange_sha256"],
            protected_roots=(),
        )

    def open_topology(self):
        return module("sources").open_topology_source(
            profile=profile(),
            recipe_sha256=self.pins["recipe_sha256"],
            instance_sha256=self.pins["instance_sha256"],
            topology_sha256=self.pins["topology_sha256"],
            protected_roots=(),
        )


@pytest.fixture
def actual_sources(tmp_path, monkeypatch):
    return ActualSources(tmp_path, monkeypatch)
