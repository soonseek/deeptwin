import os
from types import SimpleNamespace
from uuid import UUID

import pytest

from app.tests.deployment_source_fixture import module
from app.tests.support.inode_pins import identity_map


class Namespace:
    def __init__(self, tmp_path, monkeypatch):
        self.files = module("files")
        self.root = tmp_path / "namespace"
        self.root.mkdir(mode=0o750)
        self.directory = self.files.Directory.open(self.root)
        self.metadata = identity_map(monkeypatch)
        real_fstat, real_stat = os.fstat, os.stat

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

        monkeypatch.setattr(os, "fstat", lambda fd: observed(real_fstat(fd)))
        monkeypatch.setattr(
            os,
            "stat",
            lambda *args, **kwargs: observed(real_stat(*args, **kwargs)),
        )

    def close(self):
        self.directory.close()

    def add(self, name, payload, *, uid, gid, mode):
        path = self.root / name
        path.write_bytes(payload)
        path.chmod(mode)
        info = os.stat(path, follow_symlinks=False)
        self.metadata[(info.st_dev, info.st_ino)] = uid, gid
        return path


def final_name(number):
    return f"{number:064x}.json"


def stage_name(number):
    return f".stage-{UUID(int=number + 1)}.tmp"


def populate(namespace, policy, *, finals, stages):
    names = []
    for number in reversed(range(finals)):
        names.append(final_name(number))
        namespace.add(
            names[-1],
            b"x",
            uid=policy.writer_uid,
            gid=policy.pair_gid,
            mode=0o440,
        )
    for number in range(stages):
        namespace.add(
            stage_name(number),
            b"",
            uid=policy.writer_uid,
            gid=policy.primary_gid,
            mode=0o600,
        )
    return names


@pytest.mark.parametrize(
    "policy,final_count",
    [("_REQUEST_NAMESPACE", 16), ("_INCOMING_NAMESPACE", 64)],
)
def test_scanner_enumerates_metadata_only_at_fixed_boundaries(
    tmp_path, monkeypatch, policy, final_count
):
    files = module("files")
    namespace = Namespace(tmp_path, monkeypatch)
    try:
        selected = getattr(files, policy)
        expected_names = populate(namespace, selected, finals=final_count, stages=32)
        payload_reads = []
        original_read, original_open_regular = os.read, files.open_regular

        def guarded_read(fd, amount):
            payload_reads.append((fd, amount))
            return original_read(fd, amount)

        def guarded_open(*args, **kwargs):
            payload_reads.append((args, kwargs))
            return original_open_regular(*args, **kwargs)

        with monkeypatch.context() as guard:
            guard.setattr(os, "read", guarded_read)
            guard.setattr(files, "open_regular", guarded_open)
            scan = files._scan_namespace(namespace.directory, policy=selected)

        assert len(scan.finals) == final_count
        assert scan.stages == 32
        assert tuple(item.name for item in scan.finals) == tuple(sorted(expected_names))
        assert payload_reads == []
    finally:
        namespace.close()


@pytest.mark.parametrize(
    "policy,finals,stages",
    [
        ("_REQUEST_NAMESPACE", 17, 0),
        ("_REQUEST_NAMESPACE", 0, 33),
        ("_INCOMING_NAMESPACE", 65, 0),
        ("_INCOMING_NAMESPACE", 0, 33),
        ("_INCOMING_NAMESPACE", 65, 33),
    ],
)
def test_scanner_rejects_the_first_entry_past_each_fixed_bound(
    tmp_path, monkeypatch, policy, finals, stages
):
    files, contracts = module("files"), module("contracts")
    namespace = Namespace(tmp_path, monkeypatch)
    try:
        selected = getattr(files, policy)
        populate(namespace, selected, finals=finals, stages=stages)
        with pytest.raises(contracts.DeploymentSourceError):
            files._scan_namespace(namespace.directory, policy=selected)
    finally:
        namespace.close()


def test_scanner_accepts_each_fixed_stage_handoff_state(tmp_path, monkeypatch):
    files = module("files")
    namespace = Namespace(tmp_path, monkeypatch)
    policy = files._INCOMING_NAMESPACE
    try:
        for number, (gid, mode) in enumerate(
            (
                (policy.primary_gid, 0o600),
                (policy.pair_gid, 0o600),
                (policy.pair_gid, 0o440),
            )
        ):
            namespace.add(
                stage_name(number),
                b"",
                uid=policy.writer_uid,
                gid=gid,
                mode=mode,
            )
        assert files._scan_namespace(namespace.directory, policy=policy).stages == 3
    finally:
        namespace.close()


def test_scanner_rechecks_membership_after_real_inventory_walk(tmp_path, monkeypatch):
    files, contracts = module("files"), module("contracts")
    namespace = Namespace(tmp_path, monkeypatch)
    policy = files._CANCEL_NAMESPACE
    try:
        populate(namespace, policy, finals=1, stages=0)
        original = files.members
        calls = 0

        def mutating_members(fd, maximum):
            nonlocal calls
            result = original(fd, maximum)
            calls += 1
            if calls == 1:
                namespace.add(
                    "unexpected-after-enumeration",
                    b"",
                    uid=policy.writer_uid,
                    gid=policy.primary_gid,
                    mode=0o600,
                )
            return result

        monkeypatch.setattr(files, "members", mutating_members)
        with pytest.raises(contracts.DeploymentSourceError):
            files._scan_namespace(namespace.directory, policy=policy)
    finally:
        namespace.close()


def test_scanner_rechecks_earlier_unselected_metadata(tmp_path, monkeypatch):
    files, contracts = module("files"), module("contracts")
    namespace = Namespace(tmp_path, monkeypatch)
    policy = files._CANCEL_NAMESPACE
    try:
        populate(namespace, policy, finals=2, stages=0)
        earlier = namespace.root / final_name(0)
        original = files.stat_at

        def mutate_after_earlier(fd, name):
            if name == final_name(1):
                earlier.chmod(0o640)
            return original(fd, name)

        monkeypatch.setattr(files, "stat_at", mutate_after_earlier)
        with pytest.raises(contracts.DeploymentSourceError):
            files._scan_namespace(namespace.directory, policy=policy)
    finally:
        namespace.close()


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "invalid_uuid",
        "nil_uuid",
        "final_empty",
        "final_oversize",
        "final_mode",
        "final_owner",
        "final_group",
        "final_hardlink",
        "final_symlink",
        "stage_oversize",
        "stage_mode",
        "stage_owner",
        "stage_group",
        "stage_hardlink",
        "stage_symlink",
    ],
)
def test_scanner_rejects_every_unsafe_member(tmp_path, monkeypatch, change):
    files, contracts = module("files"), module("contracts")
    namespace = Namespace(tmp_path, monkeypatch)
    policy = files._CANCEL_NAMESPACE
    try:
        final = namespace.add(
            final_name(1),
            b"x",
            uid=policy.writer_uid,
            gid=policy.pair_gid,
            mode=0o440,
        )
        stage = namespace.add(
            stage_name(1),
            b"",
            uid=policy.writer_uid,
            gid=policy.primary_gid,
            mode=0o600,
        )
        target = final if change.startswith("final_") else stage
        if change == "unknown":
            target = namespace.add("unexpected", b"", uid=20102, gid=20102, mode=0o600)
        elif change == "invalid_uuid":
            stage.rename(namespace.root / ".stage-not-a-uuid.tmp")
        elif change == "nil_uuid":
            stage.rename(namespace.root / f".stage-{UUID(int=0)}.tmp")
        elif change.endswith("empty"):
            target.chmod(0o640)
            target.write_bytes(b"")
            target.chmod(0o440)
        elif change.endswith("oversize"):
            target.chmod(0o640)
            target.write_bytes(b"x" * (policy.payload_cap + 1))
            target.chmod(0o440 if change.startswith("final_") else 0o600)
        elif change.endswith("mode"):
            target.chmod(0o640)
        elif change.endswith("owner"):
            info = os.stat(target, follow_symlinks=False)
            namespace.metadata[(info.st_dev, info.st_ino)] = 999, info.st_gid
        elif change.endswith("group"):
            info = os.stat(target, follow_symlinks=False)
            namespace.metadata[(info.st_dev, info.st_ino)] = info.st_uid, 999
        elif change.endswith("hardlink"):
            os.link(target, namespace.root / "link")
        elif change.endswith("symlink"):
            target.rename(namespace.root / "actual")
            target.symlink_to(namespace.root / "actual")
        with pytest.raises(contracts.DeploymentSourceError):
            files._scan_namespace(namespace.directory, policy=policy)
    finally:
        namespace.close()


def test_opened_final_reads_actual_bytes_and_rejects_named_swap(tmp_path, monkeypatch):
    files, contracts = module("files"), module("contracts")
    namespace = Namespace(tmp_path, monkeypatch)
    policy = files._CANCEL_NAMESPACE
    try:
        path = namespace.add(
            final_name(1),
            b"actual",
            uid=policy.writer_uid,
            gid=policy.pair_gid,
            mode=0o440,
        )
        entry = files._scan_namespace(namespace.directory, policy=policy).finals[0]
        opened = files._open_final(namespace.directory, entry, policy=policy)
        try:
            assert opened.read_current() == b"actual"
            path.rename(namespace.root / "old")
            namespace.add(
                final_name(1),
                b"actual",
                uid=policy.writer_uid,
                gid=policy.pair_gid,
                mode=0o440,
            )
            with pytest.raises(contracts.DeploymentSourceError):
                opened.read_current()
        finally:
            opened.close()
        opened.close()
    finally:
        namespace.close()


def test_legacy_eager_wrapper_preserves_supplied_cap_above_fixed_request_cap(
    tmp_path, monkeypatch
):
    files = module("files")
    namespace = Namespace(tmp_path, monkeypatch)
    policy = files._REQUEST_NAMESPACE
    try:
        name = final_name(1)
        namespace.add(
            name,
            b"x",
            uid=policy.writer_uid,
            gid=policy.pair_gid,
            mode=0o440,
        )
        assert files.inspect_namespace(namespace.directory, 65537) == (
            ((name, b"x"),),
            0,
        )
    finally:
        namespace.close()
