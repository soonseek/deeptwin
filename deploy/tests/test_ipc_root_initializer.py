from __future__ import annotations

import fcntl
import json
import os
import stat
from copy import deepcopy
from pathlib import Path

import pytest

from app.workers import ipc_root
from deploy.tests import t018_foundation_linux_canary as linux_canary


def _pair_gid() -> int:
    for value in os.getgroups():
        if value not in {0, os.getegid()}:
            return value
    if os.geteuid() == 0:
        return 21_151
    pytest.skip("a distinct supplemental test group is unavailable")


@pytest.fixture
def layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ipc_root.PairRootSpec:
    metadata_uid = os.geteuid()
    responder_uid = metadata_uid if metadata_uid != 0 else 21_152
    responder_gid = os.getegid() if os.getegid() != 0 else 21_153
    pair_gid = _pair_gid()
    monkeypatch.setattr(ipc_root, "METADATA_UID", metadata_uid)
    return ipc_root.PairRootSpec(
        pair_root=tmp_path.resolve(),
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
    )


def _initialize(
    layout: ipc_root.PairRootSpec,
    byte: bytes,
) -> ipc_root.InitializedGeneration:
    return ipc_root.initialize_pair_root(
        layout,
        entropy=lambda size: byte * size,
    )


def _identity(path: Path) -> tuple[int, int, int, int]:
    info = path.lstat()
    return info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode), info.st_nlink


def _channel_manifest() -> dict[str, object]:
    source = linux_canary.REPOSITORY_ROOT / "deploy/security/service-ids.json"
    return json.loads(source.read_bytes())


def _write_manifest(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def test_linux_canary_accepts_current_exact_two_level_static_manifest() -> None:
    services, pairs = linux_canary._load_identities(
        linux_canary.REPOSITORY_ROOT / "deploy/security/service-ids.json"
    )
    assert set(pairs) == set(linux_canary.EXPECTED_PAIRS)
    assert services["ipc-root-init"]["capabilities"] == ["CHOWN", "FOWNER", "FSETID"]


def test_linux_canary_rejects_legacy_one_level_static_manifest(tmp_path: Path) -> None:
    value = deepcopy(_channel_manifest())
    value["services"]["ipc-root-init"]["capabilities"] = ["CHOWN"]
    for pair in value["pairs"].values():
        responder_id = value["services"][pair["responder"]]["uid"]
        pair["root_uid"] = responder_id
        pair["root_mode"] = "02710"
        for field in (
            "endpoint", "endpoint_uid", "endpoint_gid", "endpoint_mode",
            "generation_lock", "generation_lock_uid", "generation_lock_gid",
            "generation_lock_mode",
        ):
            pair.pop(field)
    manifest = tmp_path / "legacy-one-level.json"
    _write_manifest(manifest, value)
    with pytest.raises(linux_canary.CanaryFailure):
        linux_canary._load_identities(manifest)


def test_linux_canary_accepts_only_exact_two_level_channel_manifest(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "channels.json"
    _write_manifest(manifest, _channel_manifest())

    services, pairs = linux_canary._load_identities(manifest)
    contracts = [
        linux_canary._pair_contract(name, services, pairs)
        for name in linux_canary.EXPECTED_PAIRS
    ]

    assert len(contracts) == 10
    for root, spec in contracts:
        assert str(root.pair_root) == f"/run/deeptwin/ipc/{spec.channel_id}"
        assert spec.pair_root == root.pair_root / "endpoint"
        assert spec.socket_name == "worker.sock"


@pytest.mark.parametrize(
    "mutation",
    [
        "schema",
        "status",
        "scope",
        "duplicate_service_uid",
        "duplicate_pair_gid",
        "root_path",
        "root_uid",
        "root_mode",
        "endpoint_name",
        "endpoint_owner",
        "endpoint_mode",
        "socket_name",
        "socket_owner",
        "socket_mode",
        "secret_owner",
        "secret_mode",
        "secret_size",
        "secret_policy",
        "lock_name",
        "lock_owner",
        "lock_mode",
        "initializer_capabilities",
        "unknown_pair_field",
    ],
)
def test_linux_canary_rejects_manifest_identity_or_layout_drift(
    tmp_path: Path,
    mutation: str,
) -> None:
    value = deepcopy(_channel_manifest())
    pair = value["pairs"]["cp-provider"]
    mutations = {
        "schema": lambda: value.__setitem__("schema_version", "other"),
        "status": lambda: value.__setitem__("status", "qualified"),
        "scope": lambda: value.__setitem__("scope", "other"),
        "duplicate_service_uid": lambda: value["services"]["provider"].__setitem__(
            "uid", value["services"]["fetch"]["uid"]
        ),
        "duplicate_pair_gid": lambda: pair.__setitem__(
            "pair_gid", value["pairs"]["cp-fetch"]["pair_gid"]
        ),
        "root_path": lambda: pair.__setitem__("root", "/run/deeptwin/ipc/other"),
        "root_uid": lambda: pair.__setitem__("root_uid", 20_103),
        "root_mode": lambda: pair.__setitem__("root_mode", "02710"),
        "endpoint_name": lambda: pair.__setitem__("endpoint", "other"),
        "endpoint_owner": lambda: pair.__setitem__("endpoint_uid", 20_104),
        "endpoint_mode": lambda: pair.__setitem__("endpoint_mode", "0770"),
        "socket_name": lambda: pair.__setitem__("socket", "other.sock"),
        "socket_owner": lambda: pair.__setitem__("socket_uid", 20_104),
        "socket_mode": lambda: pair.__setitem__("socket_mode", "0666"),
        "secret_owner": lambda: pair.__setitem__("boot_secret_uid", 20_103),
        "secret_mode": lambda: pair.__setitem__("boot_secret_mode", "0600"),
        "secret_size": lambda: pair.__setitem__("boot_secret_bytes", 31),
        "secret_policy": lambda: pair.__setitem__("boot_secret_policy", "reuse"),
        "lock_name": lambda: pair.__setitem__("generation_lock", "other.lock"),
        "lock_owner": lambda: pair.__setitem__("generation_lock_uid", 20_103),
        "lock_mode": lambda: pair.__setitem__("generation_lock_mode", "0600"),
        "initializer_capabilities": lambda: value["services"][
            "ipc-root-init"
        ].__setitem__("capabilities", ["CHOWN"]),
        "unknown_pair_field": lambda: pair.__setitem__("unknown", True),
    }
    mutations[mutation]()
    manifest = tmp_path / "channels.json"
    _write_manifest(manifest, value)

    with pytest.raises(linux_canary.CanaryFailure):
        linux_canary._load_identities(manifest)


def test_empty_root_initialization_creates_exact_two_level_boundary(
    layout: ipc_root.PairRootSpec,
) -> None:
    initialized = _initialize(layout, b"a")

    assert _identity(layout.pair_root)[:3] == (
        ipc_root.METADATA_UID,
        layout.pair_gid,
        0o710,
    )
    assert _identity(layout.boot_secret_path) == (
        ipc_root.METADATA_UID,
        layout.pair_gid,
        0o640,
        1,
    )
    assert _identity(layout.generation_lock_path) == (
        ipc_root.METADATA_UID,
        layout.pair_gid,
        0o640,
        1,
    )
    assert _identity(layout.endpoint_path)[:3] == (
        layout.responder_uid,
        layout.pair_gid,
        0o2710,
    )
    assert layout.boot_secret_path.read_bytes() == b"a" * 32
    assert len(initialized.generation_id) == 64
    assert initialized.endpoint_identity.inode == layout.endpoint_path.stat().st_ino
    assert {path.name for path in layout.pair_root.iterdir()} == {
        "boot-secret",
        "generation.lock",
        "endpoint",
    }


def test_second_boot_never_repairs_responder_owned_endpoint(
    layout: ipc_root.PairRootSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize(layout, b"a")
    real_fchmod = ipc_root.os.fchmod
    real_fchown = ipc_root.os.fchown
    endpoint_inode = layout.endpoint_path.stat().st_ino

    def reject_endpoint_fchmod(descriptor: int, mode: int) -> None:
        if os.fstat(descriptor).st_ino == endpoint_inode:
            raise PermissionError("synthetic CAP_FOWNER denial")
        real_fchmod(descriptor, mode)

    def reject_endpoint_fchown(descriptor: int, uid: int, gid: int) -> None:
        if os.fstat(descriptor).st_ino == endpoint_inode:
            raise PermissionError("synthetic endpoint ownership repair denial")
        real_fchown(descriptor, uid, gid)

    monkeypatch.setattr(ipc_root.os, "fchmod", reject_endpoint_fchmod)
    monkeypatch.setattr(ipc_root.os, "fchown", reject_endpoint_fchown)
    _initialize(layout, b"b")


def test_valid_second_boot_rotates_only_secret_generation(
    layout: ipc_root.PairRootSpec,
) -> None:
    first = _initialize(layout, b"a")
    first_lock = layout.generation_lock_path.stat().st_ino
    first_endpoint = layout.endpoint_path.stat().st_ino
    first_secret = layout.boot_secret_path.stat().st_ino

    second = _initialize(layout, b"b")

    assert second.generation_id != first.generation_id
    assert layout.boot_secret_path.read_bytes() == b"b" * 32
    assert layout.generation_lock_path.stat().st_ino == first_lock
    assert layout.endpoint_path.stat().st_ino == first_endpoint
    assert layout.boot_secret_path.stat().st_ino != first_secret


def test_lifetime_shared_generation_lease_blocks_rotation(
    layout: ipc_root.PairRootSpec,
) -> None:
    first = _initialize(layout, b"a")
    with ipc_root.acquire_generation(layout) as lease:
        assert lease.generation_id == first.generation_id
        with pytest.raises(ipc_root.IpcRootBusy):
            _initialize(layout, b"b")
        assert layout.boot_secret_path.read_bytes() == b"a" * 32
    second = _initialize(layout, b"b")
    assert second.generation_id != first.generation_id


def test_generation_lock_is_shared_for_lease_and_initializer_uses_exclusive(
    layout: ipc_root.PairRootSpec,
) -> None:
    _initialize(layout, b"a")
    with ipc_root.acquire_generation(layout) as lease:
        contender_fd = os.open(
            ipc_root.GENERATION_LOCK_NAME,
            os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW,
            dir_fd=lease.pair_fd,
        )
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender_fd)


def test_short_or_repeated_entropy_fails_without_replacing_old_secret(
    layout: ipc_root.PairRootSpec,
) -> None:
    _initialize(layout, b"a")
    old_inode = layout.boot_secret_path.stat().st_ino
    for entropy in (lambda _size: b"short", lambda size: b"a" * size):
        with pytest.raises(ipc_root.IpcRootIntegrityError):
            ipc_root.initialize_pair_root(layout, entropy=entropy)
        assert layout.boot_secret_path.read_bytes() == b"a" * 32
        assert layout.boot_secret_path.stat().st_ino == old_inode


@pytest.mark.parametrize(
    "candidate",
    [
        b"P" * 32,
        b"C" * 31,
    ],
)
def test_entropy_rejection_scrubs_raw_secrets_from_ipc_root_traceback_locals(
    layout: ipc_root.PairRootSpec,
    candidate: bytes,
) -> None:
    previous = b"P" * 32
    _initialize(layout, b"P")
    old_identity = _identity(layout.boot_secret_path)

    with pytest.raises(ipc_root.IpcRootIntegrityError) as caught:
        ipc_root.initialize_pair_root(layout, entropy=lambda _size: candidate)

    inspected = 0
    current = caught.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "app.workers.ipc_root":
            inspected += 1
            rendered = repr(tuple(current.tb_frame.f_locals.values()))
            assert previous.decode("ascii") not in rendered
            assert candidate.decode("ascii") not in rendered
        current = current.tb_next
    assert inspected >= 1
    assert layout.boot_secret_path.read_bytes() == previous
    assert _identity(layout.boot_secret_path) == old_identity


def test_failed_atomic_replace_preserves_old_secret_and_removes_owned_stage(
    layout: ipc_root.PairRootSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize(layout, b"a")
    old_identity = _identity(layout.boot_secret_path)

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(ipc_root.os, "replace", fail_replace)
    with pytest.raises(ipc_root.IpcRootIntegrityError):
        _initialize(layout, b"b")

    assert layout.boot_secret_path.read_bytes() == b"a" * 32
    assert _identity(layout.boot_secret_path) == old_identity
    assert {path.name for path in layout.pair_root.iterdir()} == {
        "boot-secret",
        "generation.lock",
        "endpoint",
    }


def test_interrupted_first_secret_publish_leaves_retryable_verified_skeleton(
    layout: ipc_root.PairRootSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_replace = ipc_root.os.replace
    monkeypatch.setattr(
        ipc_root.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("synthetic")),
    )
    with pytest.raises(ipc_root.IpcRootIntegrityError):
        _initialize(layout, b"a")
    assert {path.name for path in layout.pair_root.iterdir()} == {
        "generation.lock",
        "endpoint",
    }

    monkeypatch.setattr(ipc_root.os, "replace", real_replace)
    initialized = _initialize(layout, b"b")
    assert initialized.generation_id
    assert layout.boot_secret_path.read_bytes() == b"b" * 32


def test_sigkill_secret_stage_is_reconciled_only_when_exact_and_owned(
    layout: ipc_root.PairRootSpec,
) -> None:
    first = _initialize(layout, b"a")
    stage = layout.pair_root / f".boot-secret.{'1' * 32}.tmp"
    stage.write_bytes(b"partial-secret")
    stage.chmod(0o640)
    if os.geteuid() == 0:
        os.chown(stage, ipc_root.METADATA_UID, layout.pair_gid)

    second = _initialize(layout, b"b")

    assert second.generation_id != first.generation_id
    assert not stage.exists()
    assert layout.boot_secret_path.read_bytes() == b"b" * 32


@pytest.mark.parametrize("tamper", ["foreign", "symlink", "hardlink", "fifo", "mode"])
def test_untrusted_secret_stage_is_rejected_without_unlink(
    layout: ipc_root.PairRootSpec,
    tmp_path: Path,
    tamper: str,
) -> None:
    _initialize(layout, b"a")
    name = "foreign" if tamper == "foreign" else f".boot-secret.{'2' * 32}.tmp"
    stage = layout.pair_root / name
    if tamper == "symlink":
        stage.symlink_to(layout.boot_secret_path.name)
    elif tamper == "hardlink":
        os.link(layout.boot_secret_path, stage)
    elif tamper == "fifo":
        os.mkfifo(stage, 0o640)
    else:
        stage.write_bytes(b"partial-secret")
        stage.chmod(0o600 if tamper == "mode" else 0o640)
        if os.geteuid() == 0:
            os.chown(stage, ipc_root.METADATA_UID, layout.pair_gid)
    before = stage.lstat()

    with pytest.raises(ipc_root.IpcRootIntegrityError):
        _initialize(layout, b"b")

    after = stage.lstat()
    assert (after.st_dev, after.st_ino, after.st_mode, after.st_nlink) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
    )


def test_secret_publish_fsyncs_regular_file_and_parent_directory(
    layout: ipc_root.PairRootSpec,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _initialize(layout, b"a")
    real_fsync = ipc_root.os.fsync
    observed_types: list[int] = []

    def record_fsync(descriptor: int) -> None:
        observed_types.append(stat.S_IFMT(os.fstat(descriptor).st_mode))
        real_fsync(descriptor)

    monkeypatch.setattr(ipc_root.os, "fsync", record_fsync)
    _initialize(layout, b"b")

    assert stat.S_IFREG in observed_types
    assert stat.S_IFDIR in observed_types


@pytest.mark.parametrize("tamper", ["mode", "hardlink", "symlink", "fifo"])
def test_existing_metadata_tamper_fails_closed_without_repair(
    layout: ipc_root.PairRootSpec,
    tmp_path: Path,
    tamper: str,
) -> None:
    _initialize(layout, b"a")
    secret = layout.boot_secret_path
    if tamper == "mode":
        secret.chmod(0o600)
    elif tamper == "hardlink":
        os.link(secret, tmp_path / "secret-link")
    elif tamper == "symlink":
        secret.unlink()
        secret.symlink_to(layout.generation_lock_path.name)
    else:
        secret.unlink()
        os.mkfifo(secret, 0o640)

    before = secret.lstat()
    with pytest.raises(ipc_root.IpcRootIntegrityError):
        _initialize(layout, b"b")
    after = secret.lstat()
    assert (after.st_dev, after.st_ino, after.st_mode, after.st_nlink) == (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_nlink,
    )


def test_pair_root_symlink_and_unexpected_entry_are_rejected(
    layout: ipc_root.PairRootSpec,
    tmp_path: Path,
) -> None:
    _initialize(layout, b"a")
    (layout.pair_root / "foreign").write_text("foreign", encoding="utf-8")
    with pytest.raises(ipc_root.IpcRootIntegrityError):
        _initialize(layout, b"b")

    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "linked-pair"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ipc_root.IpcRootIntegrityError):
        ipc_root.initialize_pair_root(
            ipc_root.PairRootSpec(
                pair_root=link,
                responder_uid=layout.responder_uid,
                responder_gid=layout.responder_gid,
                pair_gid=layout.pair_gid,
            ),
            entropy=lambda size: b"b" * size,
        )


def test_public_initializer_has_no_owner_or_validation_bypass() -> None:
    import inspect

    parameters = inspect.signature(ipc_root.initialize_pair_root).parameters
    assert "metadata_uid" not in parameters
    assert "repair" not in parameters
    assert "follow_symlinks" not in parameters
