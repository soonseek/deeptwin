import importlib
import json
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.tests.deployment_receipt_source_fixture import (
    actual_receipt_public_init as actual_receipt_public_init,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import consumed_marker
from app.tests.test_deployment_publication import syscall_fixture


def public_files():
    try:
        return importlib.import_module("app.deployment.public_init_files")
    except ModuleNotFoundError:
        assert False, "Shared retained public-init file helpers are missing"


def initializer():
    try:
        return importlib.import_module("app.operations.deployment_receipt_public_init")
    except ModuleNotFoundError:
        assert False, "Fixed receipt public initializer is missing"


def _bind_release_leaves(actual, *, first_mount_id=500):
    for index, relative in enumerate(
        (
            "deploy/compose.yaml",
            "deploy/security/service-ids.json",
            "deploy/security/deployment-prepare-recipe-v1.json",
            "deploy/security/deployment-receipt-recipe-v1.json",
        ),
        first_mount_id,
    ):
        actual.mount_lines.append(
            f"{index} 100 {actual.device} /release-file-{index} "
            f"{actual.c.RELEASE_ROOT / relative} ro - overlay overlay rw\n"
        )


def test_public_input_file_retains_fd_name_metadata_and_whole_bytes(
    actual_receipt_public_init,
):
    actual = actual_receipt_public_init
    helpers = public_files()
    with actual.f.Directory.open(
        actual.input_root, uid=0, gid=0, mode=0o750
    ) as directory:
        source = helpers._PublicInputFile.open(
            directory,
            "prepare-instance.json",
            cap=4096,
            modes=(0o440,),
        )
        try:
            assert source.read_current() == actual.prepare_inputs[3]
            path = actual.actual(actual.input_root / "prepare-instance.json")
            old = path.with_name("old-prepare-instance.json")
            path.rename(old)
            path.write_bytes(actual.prepare_inputs[3])
            path.chmod(0o440)
            actual.register(path, 0, 0)
            with pytest.raises(actual.c.DeploymentSourceError):
                source.read_current()
        finally:
            source.close()


def test_retained_input_read_rechecks_fixed_parent_after_whole_byte_read(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    helpers = public_files()
    with actual.f.Directory.open(
        actual.input_root, uid=0, gid=0, mode=0o750
    ) as directory:
        source = helpers._PublicInputFile.open(
            directory,
            "prepare-instance.json",
            cap=4096,
            modes=(0o440,),
        )
        original = actual.f.read_exact

        def replace_parent_after_read(fd, cap):
            raw = original(fd, cap)
            actual.replace_input_root("displaced-retained-input-root")
            return raw

        monkeypatch.setattr(actual.f, "read_exact", replace_parent_after_read)
        try:
            with pytest.raises(actual.c.DeploymentSourceError):
                source.read_current()
        finally:
            source.close()


def test_old_read_at_delegate_rechecks_parent_after_its_final_read(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    init = importlib.import_module("app.operations.deployment_prepare_init")
    original = actual.f.read_exact
    reads = 0

    def replace_parent_after_final_read(fd, cap):
        nonlocal reads
        raw = original(fd, cap)
        reads += 1
        if reads == 2:
            actual.replace_input_root("displaced-old-delegate-input-root")
        return raw

    monkeypatch.setattr(actual.f, "read_exact", replace_parent_after_final_read)
    with (
        actual.f.Directory.open(
            actual.input_root, uid=0, gid=0, mode=0o750
        ) as directory,
        pytest.raises(actual.c.DeploymentSourceError),
    ):
        init._read_at(
            directory,
            "prepare-instance.json",
            cap=4096,
            modes=(0o440,),
        )
    assert reads == 2


def test_old_outbox_wrapper_keeps_cancelled_then_requests_sequence(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    init = importlib.import_module("app.operations.deployment_prepare_init")
    root = actual.target_specs[4][0]
    made = []
    original_mkdir = os.mkdir

    def recording(name, *args, **kwargs):
        made.append(name)
        return original_mkdir(name, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", recording)
    with actual.f.Directory.open(root) as directory:
        init._install_outbox(directory)
    assert made == ["cancelled", "requests"]
    root_info = os.stat(actual.actual(root), follow_symlinks=False)
    assert (root_info.st_uid, root_info.st_gid, root_info.st_mode & 0o7777) == (
        20102,
        21201,
        0o750,
    )


def test_fixed_initializer_creates_only_five_empty_public_roots(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    syscall_fixture(monkeypatch)
    result = initializer().initialize_receipt_public_sources()
    assert result == {
        "trust_sha256": actual.pins["trust_sha256"],
        "ingress_sha256": actual.pins["ingress_sha256"],
        "consumption_exchange_sha256": actual.pins["consumption_exchange_sha256"],
    }
    expected = (
        (actual.target_specs[0], "trust-set.json", actual.output.trust_bytes),
        (actual.target_specs[1], "ingress.json", actual.output.ingress_bytes),
        (
            actual.target_specs[2],
            "consumption-exchange.json",
            actual.output.consumption_exchange_bytes,
        ),
    )
    for (logical, uid, gid), name, raw in expected:
        root = actual.actual(logical)
        path = root / name
        assert (
            os.stat(root).st_uid,
            os.stat(root).st_gid,
            root.stat().st_mode & 0o7777,
        ) == (
            uid,
            gid,
            0o750,
        )
        assert path.read_bytes() == raw
        assert (
            os.stat(path).st_uid,
            os.stat(path).st_gid,
            path.stat().st_mode & 0o7777,
            path.stat().st_nlink,
        ) == (uid, gid, 0o440, 1)
    for (logical, uid, gid), name in zip(
        actual.target_specs[3:], ("receipts", "consumed"), strict=True
    ):
        root = actual.actual(logical)
        child = root / name
        assert sorted(item.name for item in root.iterdir()) == [name]
        assert (
            os.stat(root).st_uid,
            os.stat(root).st_gid,
            root.stat().st_mode & 0o7777,
        ) == (
            uid,
            gid,
            0o750,
        )
        assert (
            os.stat(child).st_uid,
            os.stat(child).st_gid,
            child.stat().st_mode & 0o7777,
        ) == (uid, gid, 0o750)


def test_restart_verifies_only_and_preserves_existing_final_bytes_and_inodes(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    receipt = actual.add_receipt()
    consumed = actual.add_consumed()
    before = {
        path: (path.stat().st_ino, path.read_bytes()) for path in (receipt, consumed)
    }

    def forbidden(*_args, **_kwargs):
        raise AssertionError("restart attempted a write")

    monkeypatch.setattr(os, "fchown", forbidden)
    assert (
        initializer().initialize_receipt_public_sources()["trust_sha256"]
        == (actual.pins["trust_sha256"])
    )
    assert before == {
        path: (path.stat().st_ino, path.read_bytes()) for path in (receipt, consumed)
    }


def test_completed_root_is_verify_only_while_later_empty_roots_initialize(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    for logical, _uid, _gid in actual.target_specs[1:]:
        actual.empty_target(logical)
    trust = actual.actual(actual.target_specs[0][0]) / "trust-set.json"
    before = trust.stat().st_ino, trust.read_bytes()
    syscall_fixture(monkeypatch)
    initializer().initialize_receipt_public_sources()
    assert (trust.stat().st_ino, trust.read_bytes()) == before
    assert all(
        any(actual.actual(logical).iterdir())
        for logical, _uid, _gid in actual.target_specs[1:]
    )


def test_partial_source_rejection_preserves_every_target_observation(
    actual_receipt_public_init,
):
    actual = actual_receipt_public_init
    before = actual.snapshot_targets()
    actual.make_partial_source()
    partial = actual.snapshot_targets()
    with pytest.raises(actual.c.DeploymentSourceError):
        initializer().initialize_receipt_public_sources()
    assert actual.snapshot_targets() == partial
    assert before != partial


@pytest.mark.parametrize(
    "change",
    [
        "source_stage",
        "empty_handed_off",
        "wrong_pin",
        "input_extra",
        "config_mode",
        "config_rw",
        "config_device",
        "release_rw",
        "release_mode",
        "release_root_device_with_file_binds",
        "target_ro",
        "target_nested",
        "target_backing_alias",
    ],
)
def test_all_invalid_preflight_states_leave_five_targets_unchanged(
    actual_receipt_public_init, monkeypatch, change
):
    actual = actual_receipt_public_init
    if change == "source_stage":
        path = actual.actual(actual.target_specs[1][0]) / (
            ".stage-33333333-3333-4333-8333-333333333333.tmp"
        )
        path.touch(mode=0o600)
        actual.register(path, 0, 0)
    elif change == "empty_handed_off":
        path = actual.actual(actual.target_specs[0][0])
        path.chmod(0o750)
        actual.register(path, 0, 20102)
    elif change == "wrong_pin":
        path = actual.actual(actual.input_root / "receipt-source-pins.json")
        value = json.loads(path.read_bytes())
        value["trust_sha256"] = "a" * 64
        path.chmod(0o640)
        path.write_bytes(actual.c.encode(value))
        path.chmod(0o440)
    elif change == "input_extra":
        path = actual.actual(actual.input_root) / "extra"
        path.touch(mode=0o440)
        actual.register(path, 0, 0)
    elif change == "config_mode":
        actual.actual(actual.input_root / "trust-set.json").chmod(0o640)
    elif change in {"config_rw", "config_device"}:
        marker = str(actual.input_root / "trust-set.json")
        index = next(i for i, line in enumerate(actual.mount_lines) if marker in line)
        if change == "config_rw":
            actual.mount_lines[index] = actual.mount_lines[index].replace(
                " ro -", " rw -"
            )
        else:
            actual.mount_lines[index] = actual.mount_lines[index].replace(
                f" {actual.device} ", " 99:99 "
            )
    elif change == "release_rw":
        actual.mount_lines[0] = actual.mount_lines[0].replace(" ro -", " rw -")
    elif change == "release_mode":
        actual.actual(actual.c.RELEASE_ROOT / "deploy/compose.yaml").chmod(0o664)
    elif change == "release_root_device_with_file_binds":
        actual.mount_lines[0] = actual.mount_lines[0].replace(
            f" {actual.device} ", " 99:99 "
        )
        for index, (relative, _raw) in enumerate(
            (
                ("deploy/compose.yaml", actual.prepare_inputs[0]),
                ("deploy/security/service-ids.json", actual.prepare_inputs[1]),
                (
                    "deploy/security/deployment-prepare-recipe-v1.json",
                    actual.prepare_inputs[2],
                ),
                (
                    "deploy/security/deployment-receipt-recipe-v1.json",
                    actual.receipt_recipe_bytes,
                ),
            ),
            500,
        ):
            actual.mount_lines.append(
                f"{index} 100 {actual.device} /release-file-{index} "
                f"{actual.c.RELEASE_ROOT / relative} ro - overlay overlay rw\n"
            )
    elif change == "target_ro":
        actual.mount_lines[-1] = actual.mount_lines[-1].replace(" rw -", " ro -")
    elif change == "target_nested":
        root = actual.target_specs[0][0]
        actual.mount_lines.append(
            f"400 200 {actual.device} /nested {root / 'nested'} rw - ext4 /dev/fake rw\n"
        )
    else:
        actual.mount_lines[-1] = actual.mount_lines[-1].replace(
            "/target-204", "/target-203/child"
        )
    before = actual.snapshot_targets()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("invalid preflight attempted an effect")

    monkeypatch.setattr(os, "fchown", forbidden)
    with pytest.raises(actual.c.DeploymentSourceError):
        initializer().initialize_receipt_public_sources()
    assert actual.snapshot_targets() == before


@pytest.mark.parametrize("change", ["rw", "device"])
def test_ro_release_leaf_binds_do_not_hide_unsafe_retained_deploy_ancestor(
    actual_receipt_public_init, monkeypatch, change
):
    actual = actual_receipt_public_init
    mount_device = actual.device if change == "rw" else "99:99"
    mode = "rw" if change == "rw" else "ro"
    actual.mount_lines.append(
        f"450 100 {mount_device} /release-deploy "
        f"{actual.c.RELEASE_ROOT / 'deploy'} {mode} - overlay overlay rw\n"
    )
    _bind_release_leaves(actual)
    before = actual.snapshot_targets()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unsafe release ancestor reached a target effect")

    monkeypatch.setattr(os, "fchown", forbidden)
    with pytest.raises(actual.c.DeploymentSourceError):
        initializer().initialize_receipt_public_sources()
    assert actual.snapshot_targets() == before


def test_retained_release_ancestor_mount_mapping_survives_commits(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    actual.mount_lines.append(
        f"450 100 {actual.device} /release-security "
        f"{actual.c.RELEASE_ROOT / 'deploy/security'} ro - overlay overlay rw\n"
    )
    _bind_release_leaves(actual)
    init = initializer()
    syscall_fixture(monkeypatch)
    original = init._install_source
    changed = False

    def drift_ancestor_after_commit(*args, **kwargs):
        nonlocal changed
        retained = original(*args, **kwargs)
        if not changed:
            changed = True
            index = next(
                i
                for i, line in enumerate(actual.mount_lines)
                if "/release-security " in line
            )
            actual.mount_lines[index] = actual.mount_lines[index].replace(
                " /release-security ", " /changed-release-security "
            )
        return retained

    monkeypatch.setattr(init, "_install_source", drift_ancestor_after_commit)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()


@pytest.mark.parametrize("kind, count", [("incoming", 65), ("consumed", 17)])
def test_existing_channel_bounds_inhibit_without_repair(
    actual_receipt_public_init, kind, count
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    if kind == "incoming":
        namespace = actual.actual(actual.target_specs[3][0]) / "receipts"
        uid = 20113
        payload = actual.receipt_bytes
    else:
        namespace = actual.actual(actual.target_specs[4][0]) / "consumed"
        uid = 20102
        payload = consumed_marker()
    for number in range(count):
        path = namespace / f"{number:064x}.json"
        path.write_bytes(payload)
        path.chmod(0o440)
        actual.register(path, uid, 21201)
    before = actual.snapshot_targets()
    with pytest.raises(actual.c.DeploymentSourceError):
        initializer().initialize_receipt_public_sources()
    assert actual.snapshot_targets() == before


@pytest.mark.parametrize("kind", ["incoming", "consumed"])
def test_malformed_existing_final_inhibits_without_repair(
    actual_receipt_public_init, kind
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    namespace, uid = (
        (
            actual.actual(actual.target_specs[3][0]) / "receipts",
            20113,
        )
        if kind == "incoming"
        else (
            actual.actual(actual.target_specs[4][0]) / "consumed",
            20102,
        )
    )
    path = namespace / f"{'a' * 64}.json"
    path.write_bytes(b"{}")
    path.chmod(0o440)
    actual.register(path, uid, 21201)
    before = actual.snapshot_targets()
    with pytest.raises(actual.c.DeploymentSourceError):
        initializer().initialize_receipt_public_sources()
    assert actual.snapshot_targets() == before


@pytest.mark.parametrize(
    "change",
    [
        "incoming_stage",
        "consumed_stage",
        "incoming_extra_root",
        "consumed_missing_namespace",
        "incoming_namespace_mode",
        "wrong_source_bytes",
        "extra_source_member",
    ],
)
def test_existing_partial_or_staged_roots_inhibit_without_repair(
    actual_receipt_public_init, change
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    incoming = actual.actual(actual.target_specs[3][0])
    consumed = actual.actual(actual.target_specs[4][0])
    if change in {"incoming_stage", "consumed_stage"}:
        namespace, uid, gid = (
            (incoming / "receipts", 20113, 20113)
            if change == "incoming_stage"
            else (consumed / "consumed", 20102, 20102)
        )
        path = namespace / ".stage-33333333-3333-4333-8333-333333333333.tmp"
        path.touch(mode=0o600)
        actual.register(path, uid, gid)
    elif change == "incoming_extra_root":
        path = incoming / "extra"
        path.touch(mode=0o600)
        actual.register(path, 20113, 21201)
    elif change == "consumed_missing_namespace":
        (consumed / "consumed").rmdir()
    elif change == "incoming_namespace_mode":
        (incoming / "receipts").chmod(0o700)
    elif change == "wrong_source_bytes":
        path = actual.actual(actual.target_specs[1][0]) / "ingress.json"
        path.chmod(0o640)
        path.write_bytes(b"{}")
        path.chmod(0o440)
    else:
        path = actual.actual(actual.target_specs[2][0]) / "extra"
        path.touch(mode=0o440)
        actual.register(path, 0, 21201)
    before = actual.snapshot_targets()
    with pytest.raises(actual.c.DeploymentSourceError):
        initializer().initialize_receipt_public_sources()
    assert actual.snapshot_targets() == before


@pytest.mark.parametrize("change", ["config", "release", "mount"])
def test_retained_input_or_mount_change_after_first_commit_blocks_later_roots(
    actual_receipt_public_init, monkeypatch, change
):
    actual = actual_receipt_public_init
    init = initializer()
    helpers = public_files()
    syscall_fixture(monkeypatch)
    original = init._install_source
    calls = 0
    drifted = False

    def install_then_swap(*args, **kwargs):
        nonlocal calls, drifted
        retained = original(*args, **kwargs)
        calls += 1
        if calls == 1:
            drifted = True
            if change == "config":
                path = actual.actual(actual.input_root / "receipt-source-pins.json")
                raw, mode = actual.output.pins_bytes, 0o440
            elif change == "release":
                path = actual.actual(actual.c.RELEASE_ROOT / "deploy/compose.yaml")
                raw, mode = actual.prepare_inputs[0], 0o644
            else:
                actual.mount_lines[-1] = actual.mount_lines[-1].replace(
                    "/target-204", "/changed-target-204"
                )
                return retained
            old = path.with_name("old-" + path.name)
            path.rename(old)
            path.write_bytes(raw)
            path.chmod(mode)
            actual.register(path, 0, 0)
        return retained

    original_read = helpers._RetainedTargetFile.read_current

    def read_only_with_current_inputs(source):
        if drifted:
            raise AssertionError("target bytes read before owning input/mount check")
        return original_read(source)

    monkeypatch.setattr(init, "_install_source", install_then_swap)
    monkeypatch.setattr(
        helpers._RetainedTargetFile,
        "read_current",
        read_only_with_current_inputs,
    )
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()
    snapshot = actual.snapshot_targets()
    completed = [item for item in snapshot if item[1] == "trust-set.json"]
    assert len(completed) == 1
    assert not any(item[1] == "ingress.json" for item in snapshot)


@pytest.mark.parametrize("failure", ["write", "file_fsync", "commit", "dir_fsync"])
def test_source_effect_failures_leave_honest_partial_state_without_cleanup(
    actual_receipt_public_init, monkeypatch, failure
):
    actual = actual_receipt_public_init
    init = initializer()
    helpers = public_files()
    syscall_fixture(monkeypatch)
    if failure == "write":
        original = helpers.p._write_all

        def fail(fd, raw):
            original(fd, raw)
            raise OSError("controlled write failure")

        monkeypatch.setattr(helpers.p, "_write_all", fail)
    elif failure == "commit":
        original = helpers.p._rename_noreplace

        def fail(directory_fd, stage, final):
            original(directory_fd, stage, final)
            raise OSError("controlled commit observation failure")

        monkeypatch.setattr(helpers.p, "_rename_noreplace", fail)
    else:
        original = os.fsync
        directories = 0

        def fail(fd):
            nonlocal directories
            mode = actual.original_fstat(fd).st_mode
            if failure == "file_fsync" and stat.S_ISREG(mode):
                raise OSError("controlled file fsync failure")
            if failure == "dir_fsync" and stat.S_ISDIR(mode):
                directories += 1
                if directories == 1:
                    raise OSError("controlled directory fsync failure")
            return original(fd)

        monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()
    names = sorted(
        path.name for path in actual.actual(actual.target_specs[0][0]).iterdir()
    )
    assert names and (names[0].startswith(".stage-") or names == ["trust-set.json"])


@pytest.mark.parametrize("failure", ["create", "chown", "chmod", "sourcecheck"])
def test_more_source_effect_failures_are_visible_and_never_cleaned(
    actual_receipt_public_init, monkeypatch, failure
):
    actual = actual_receipt_public_init
    init = initializer()
    syscall_fixture(monkeypatch)
    if failure == "create":
        original = os.open

        def fail(name, *args, **kwargs):
            if isinstance(name, str) and name.startswith(".stage-"):
                raise OSError("controlled create failure")
            return original(name, *args, **kwargs)

        monkeypatch.setattr(os, "open", fail)
    elif failure in {"chown", "chmod"}:
        operation = os.fchown if failure == "chown" else os.fchmod
        calls = 0

        def fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError(f"controlled {failure} failure")
            return operation(*args, **kwargs)

        monkeypatch.setattr(os, "fchown" if failure == "chown" else "fchmod", fail)
    else:
        original = init._install_source
        corrupted = False

        def corrupt_after_commit(directory, name, raw, gid):
            nonlocal corrupted
            retained = original(directory, name, raw, gid)
            if corrupted:
                return retained
            corrupted = True
            path = actual.actual(actual.target_specs[0][0]) / name
            old = actual.base / "committed-before-sourcecheck"
            path.rename(old)
            path.write_bytes(raw)
            path.chmod(0o440)
            actual.register(path, 0, gid)
            return retained

        monkeypatch.setattr(init, "_install_source", corrupt_after_commit)
    before = actual.snapshot_targets()
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()
    after = actual.snapshot_targets()
    if failure == "create":
        assert after != before  # root ownership was already deliberately handed off
    else:
        assert any(
            item[1].startswith(".stage-") or item[1] == "trust-set.json"
            for item in after
        )


@pytest.mark.parametrize(
    "member",
    [
        "unexpected-extra",
        ".stage-33333333-3333-4333-8333-333333333333.tmp",
    ],
)
def test_new_source_rejects_post_commit_extra_or_stage_membership(
    actual_receipt_public_init, monkeypatch, member
):
    actual = actual_receipt_public_init
    init = initializer()
    syscall_fixture(monkeypatch)
    original = init._install_source
    changed = False

    def add_member_after_commit(directory, name, raw, gid):
        nonlocal changed
        retained = original(directory, name, raw, gid)
        if not changed:
            changed = True
            path = actual.actual(actual.target_specs[0][0]) / member
            path.write_bytes(b"late member")
            path.chmod(0o600 if member.startswith(".stage-") else 0o440)
            actual.register(path, 0, gid)
        return retained

    monkeypatch.setattr(init, "_install_source", add_member_after_commit)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()
    root = actual.actual(actual.target_specs[0][0])
    assert sorted(path.name for path in root.iterdir()) == sorted(
        [member, "trust-set.json"]
    )


@pytest.mark.parametrize("mutation", ["mode", "hardlink"])
def test_new_source_rejects_invalid_metadata_at_publication_transfer(
    actual_receipt_public_init, monkeypatch, mutation
):
    actual = actual_receipt_public_init
    init = initializer()
    helpers = public_files()
    syscall_fixture(monkeypatch)
    original = helpers.p._rename_noreplace
    changed = False

    def mutate_after_commit(directory_fd, stage, final):
        nonlocal changed
        original(directory_fd, stage, final)
        if changed:
            return
        changed = True
        path = actual.actual(actual.target_specs[0][0]) / final
        if mutation == "mode":
            path.chmod(0o640)
        else:
            os.link(path, actual.base / "outside-target-publication-hardlink")

    monkeypatch.setattr(helpers.p, "_rename_noreplace", mutate_after_commit)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()
    path = actual.actual(actual.target_specs[0][0]) / "trust-set.json"
    info = actual.original_stat(path, follow_symlinks=False)
    if mutation == "mode":
        assert (stat.S_IMODE(info.st_mode), info.st_nlink) == (0o640, 1)
    else:
        outside = actual.base / "outside-target-publication-hardlink"
        assert outside.stat().st_ino == info.st_ino
        assert (stat.S_IMODE(info.st_mode), info.st_nlink) == (0o440, 2)


def test_existing_consumed_final_binding_survives_other_root_commit(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    consumed = actual.add_consumed()
    actual.empty_target(actual.target_specs[1][0])
    init = initializer()
    syscall_fixture(monkeypatch)
    original = init._install_source

    def replace_consumed_after_commit(*args, **kwargs):
        retained = original(*args, **kwargs)
        displaced = actual.base / "displaced-consumed-final"
        consumed.rename(displaced)
        consumed.write_bytes(displaced.read_bytes())
        consumed.chmod(0o440)
        actual.register(consumed, 20102, 21201)
        return retained

    monkeypatch.setattr(init, "_install_source", replace_consumed_after_commit)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()


def test_target_root_identity_survives_intentional_metadata_reopen(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    init = initializer()
    syscall_fixture(monkeypatch)
    original = init._install_source
    replaced = False

    def replace_root_after_commit(directory, name, raw, gid):
        nonlocal replaced
        retained = original(directory, name, raw, gid)
        if replaced:
            return retained
        replaced = True
        root = actual.actual(actual.target_specs[0][0])
        displaced = actual.base / "displaced-trust-root"
        root.rename(displaced)
        root.mkdir(mode=0o750)
        actual.register(root, 0, gid)
        path = root / name
        path.write_bytes(raw)
        path.chmod(0o440)
        actual.register(path, 0, gid)
        return retained

    monkeypatch.setattr(init, "_install_source", replace_root_after_commit)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()


def test_new_channel_namespace_binding_survives_final_checks(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    actual.empty_target(actual.target_specs[3][0])
    init = initializer()
    original = init._install_namespaces

    def replace_namespace(directory, *, names, uid, gid):
        retained = original(directory, names=names, uid=uid, gid=gid)
        root = actual.actual(actual.target_specs[3][0])
        namespace = root / "receipts"
        namespace.rename(actual.base / "displaced-receipts-namespace")
        namespace.mkdir(mode=0o750)
        actual.register(namespace, uid, gid)
        return retained

    monkeypatch.setattr(init, "_install_namespaces", replace_namespace)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()


@pytest.mark.parametrize("failure", ["mkdir", "child_fsync", "root_handoff"])
def test_channel_effect_failures_leave_partial_namespace_for_external_recovery(
    actual_receipt_public_init, monkeypatch, failure
):
    actual = actual_receipt_public_init
    init = initializer()
    actual.install_existing_targets()
    actual.empty_target(actual.target_specs[3][0])
    if failure == "mkdir":
        monkeypatch.setattr(
            os,
            "mkdir",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("controlled mkdir failure")
            ),
        )
    elif failure == "child_fsync":
        original = os.fsync

        def fail(fd):
            if stat.S_ISDIR(actual.original_fstat(fd).st_mode):
                raise OSError("controlled child fsync failure")
            return original(fd)

        monkeypatch.setattr(os, "fsync", fail)
    else:
        original = os.fchown
        calls = 0

        def fail(fd, uid, gid):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("controlled root handoff failure")
            return original(fd, uid, gid)

        monkeypatch.setattr(os, "fchown", fail)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()
    entries = tuple(actual.actual(actual.target_specs[3][0]).iterdir())
    if failure == "mkdir":
        assert entries == ()
    else:
        assert [path.name for path in entries] == ["receipts"]


def test_fixed_api_rejects_nonroot_arguments_and_closed_diagnostics(
    actual_receipt_public_init, monkeypatch, capsys
):
    init = initializer()
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    assert init.main() == 1
    assert capsys.readouterr().err == "deployment_source_unavailable\n"
    with pytest.raises(TypeError):
        init.initialize_receipt_public_sources(path=Path("/tmp"))


def test_missing_input_root_closes_cleanly_as_source_error(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    init = initializer()
    original = actual.f.Directory.open

    def missing(path, **kwargs):
        if path == actual.input_root:
            raise actual.c.DeploymentSourceError()
        return original(path, **kwargs)

    monkeypatch.setattr(actual.f.Directory, "open", missing)
    with pytest.raises(actual.c.DeploymentSourceError):
        init.initialize_receipt_public_sources()


@pytest.mark.parametrize("fail", [False, True])
def test_initializer_closes_every_retained_descriptor(
    actual_receipt_public_init, monkeypatch, fail
):
    actual = actual_receipt_public_init
    syscall_fixture(monkeypatch)
    if fail:
        path = actual.actual(actual.input_root / "receipt-source-pins.json")
        path.chmod(0o640)
        path.write_bytes(b"{}")
        path.chmod(0o440)
    opened = set()
    original_open, original_close = os.open, os.close

    def track_open(*args, **kwargs):
        fd = original_open(*args, **kwargs)
        opened.add(fd)
        return fd

    def track_close(fd):
        original_close(fd)
        opened.discard(fd)

    monkeypatch.setattr(os, "open", track_open)
    monkeypatch.setattr(os, "close", track_close)
    if fail:
        with pytest.raises(actual.c.DeploymentSourceError):
            initializer().initialize_receipt_public_sources()
    else:
        initializer().initialize_receipt_public_sources()
    assert opened == set()


def test_initializer_opens_no_old_source_ipc_private_or_session_roots(
    actual_receipt_public_init, monkeypatch
):
    actual = actual_receipt_public_init
    actual.install_existing_targets()
    seen = []
    original = actual.f.open_directory

    def recording(path, **kwargs):
        seen.append(path)
        forbidden = {
            actual.c.TOPOLOGY_ROOT,
            actual.c.EXCHANGE_ROOT,
            actual.c.OUTBOX_ROOT,
            *actual.c.BUILTIN_ROOTS,
        }
        if path in forbidden or "private" in str(path):
            raise AssertionError(f"forbidden initializer open: {path}")
        return original(path, **kwargs)

    monkeypatch.setattr(actual.f, "open_directory", recording)
    initializer().initialize_receipt_public_sources()
    assert actual.input_root in seen
    assert {path for path, _uid, _gid in actual.target_specs} <= set(seen)


def test_fresh_initializer_import_has_no_old_initializer_ipc_or_crypto_import():
    script = textwrap.dedent(
        """
        import builtins
        import importlib
        import sys

        original = builtins.__import__
        def guarded(name, *args, **kwargs):
            forbidden = (
                name == "app.operations.deployment_prepare_init"
                or name.startswith("app.workers.ipc_root")
                or name.startswith("app.deployment.receipt_crypto")
                or name.startswith("nacl")
            )
            if forbidden:
                raise AssertionError("forbidden authority import: " + name)
            return original(name, *args, **kwargs)
        builtins.__import__ = guarded
        importlib.import_module("app.operations.deployment_receipt_public_init")
        assert "app.operations.deployment_prepare_init" not in sys.modules
        assert "app.workers.ipc_root" not in sys.modules
        assert "app.deployment.receipt_crypto" not in sys.modules
        print("fresh-public-init-import-ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "fresh-public-init-import-ok\n"


def test_module_main_rejects_extra_arguments_with_closed_diagnostic():
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "app.operations.deployment_receipt_public_init",
            "unexpected",
        ],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == "deployment_source_invalid\n"
