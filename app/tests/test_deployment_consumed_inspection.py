import base64
import copy
import hashlib
import json
import os
import pickle
from pathlib import Path

import pytest

from app.tests.deployment_receipt_source_fixture import (
    actual_consumption_exchange as actual_consumption_exchange,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import consumed_marker
from app.tests.deployment_source_fixture import module, profile


def _selector(number):
    return base64.urlsafe_b64encode(number.to_bytes(32, "big")).rstrip(b"=").decode()


def test_actual_consumption_source_retains_k_and_exact_empty_channel_identity(
    actual_consumption_exchange,
):
    actual = actual_consumption_exchange
    with actual.open() as source:
        assert source.consumption_exchange_bytes == actual.consumption_exchange_bytes
        identity = source.recheck_current()
        value = identity.as_dict()
        assert value["schema_version"] == "deployment-consumed-identity-v1"
        assert value["source"]["source_kind"] == "consumption"
        assert value["source"]["schema_version"] == (
            "deployment-public-source-identity-v1"
        )
        assert set(value["source"]["root"]) == {"device", "inode"}
        assert set(value["source"]["file"]) == {"device", "inode"}
        assert set(value["root"]) == {"device", "inode"}
        assert set(value["consumed"]) == {"device", "inode"}
        assert len(value["source"]["backing_root_digest"]) == 64
        assert len(value["backing_root_digest"]) == 64
        assert source.inspect_consumed() == ()


def test_consumed_inventory_returns_actual_marker_selector_bytes_and_file_identity(
    actual_consumption_exchange,
):
    actual = actual_consumption_exchange
    marker = consumed_marker()
    receipt_digest = json.loads(marker)["receipt_digest"]
    actual.add_final(marker)
    assert hashlib.sha256(marker).digest() != base64.urlsafe_b64decode(
        receipt_digest + "="
    )
    with actual.open() as source:
        observed = source.inspect_consumed()
        assert len(observed) == 1
        assert observed[0].receipt_digest == receipt_digest
        assert observed[0].payload == marker
        assert observed[0].file_identity.uid == 20102
        assert observed[0].file_identity.gid == 21201
        assert observed[0].file_identity.mode == 0o440
        assert source.inspect_consumed() == observed


def test_consumed_inventory_reads_only_bounded_finals_in_filename_order(
    actual_consumption_exchange, monkeypatch
):
    actual = actual_consumption_exchange
    expected = [_selector(number + 1) for number in reversed(range(16))]
    for receipt_digest in expected:
        actual.add_final(consumed_marker(receipt_digest))
    for number in range(32):
        actual.add_stage(number, b"stage-bytes-are-never-read")
    opened = []
    original = actual.f._open_final

    def track_final(*args, **kwargs):
        opened.append(args[1].name)
        return original(*args, **kwargs)

    monkeypatch.setattr(actual.f, "_open_final", track_final)
    with actual.open() as source:
        observed = source.inspect_consumed()
    expected_sorted = tuple(
        sorted(expected, key=lambda value: base64.urlsafe_b64decode(value + "=").hex())
    )
    assert tuple(item.receipt_digest for item in observed) == expected_sorted
    assert len(opened) == 32
    assert all(name.endswith(".json") for name in opened)


def test_consumed_private_inventory_does_not_recurse_through_public_recheck(
    actual_consumption_exchange, monkeypatch
):
    actual = actual_consumption_exchange
    actual.add_final(consumed_marker())
    with actual.open() as source:
        monkeypatch.setattr(
            type(source),
            "recheck_current",
            lambda _self: (_ for _ in ()).throw(
                AssertionError("public recheck recursed during inventory")
            ),
        )
        assert len(source.inspect_consumed()) == 1


@pytest.mark.parametrize("finals,stages", [(17, 0), (0, 33), (17, 33)])
def test_consumed_inventory_rejects_first_entry_past_fixed_bounds(
    actual_consumption_exchange, finals, stages
):
    actual = actual_consumption_exchange
    for number in range(finals):
        receipt_digest = _selector(number + 1)
        actual.add_final(consumed_marker(receipt_digest))
    for number in range(stages):
        actual.add_stage(number)
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open()


@pytest.mark.parametrize(
    "change",
    [
        "unknown",
        "malformed",
        "foreign_selector",
        "empty",
        "oversize",
        "mode",
        "owner",
        "group",
        "hardlink",
        "symlink",
    ],
)
def test_consumed_inventory_rejects_unsafe_or_noncanonical_final(
    actual_consumption_exchange, change
):
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    path = actual.add_final(marker)
    if change == "unknown":
        path.rename(path.with_name("unexpected"))
    elif change == "malformed":
        path.chmod(0o640)
        path.write_bytes(b"not-json")
        path.chmod(0o440)
    elif change == "foreign_selector":
        path.chmod(0o640)
        path.write_bytes(consumed_marker(_selector(2)))
        path.chmod(0o440)
    elif change == "empty":
        path.chmod(0o640)
        path.write_bytes(b"")
        path.chmod(0o440)
    elif change == "oversize":
        path.chmod(0o640)
        path.write_bytes(b"x" * 4097)
        path.chmod(0o440)
    elif change == "mode":
        path.chmod(0o640)
    elif change in {"owner", "group"}:
        info = os.stat(path, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "owner" else 20102,
            99 if change == "group" else 21201,
        )
    elif change == "hardlink":
        os.link(path, path.with_name("link"))
    else:
        path.rename(path.with_name("actual"))
        path.symlink_to(path.with_name("actual"))
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open()


@pytest.mark.parametrize(
    "change",
    [
        "bad_pin",
        "bad_recipe_pin",
        "bad_instance_pin",
        "bad_profile_type",
        "wrong_profile",
        "bad_exchange",
        "exchange_symlink",
        "exchange_hardlink",
        "source_root_mode",
        "source_root_owner",
        "source_root_group",
        "extra_source_member",
        "extra_channel_member",
        "missing_namespace",
        "consumed_root_mode",
        "consumed_root_owner",
        "consumed_root_group",
        "namespace_mode",
        "namespace_owner",
        "namespace_group",
        "source_rw",
        "consumed_ro",
        "nested",
        "device",
        "backing_alias",
    ],
)
def test_consumption_factory_rejects_invalid_k_or_actual_boundaries(
    actual_consumption_exchange, change
):
    actual = actual_consumption_exchange
    kwargs = {}
    if change == "bad_pin":
        kwargs["exchange_pin"] = "a" * 64
    elif change == "bad_recipe_pin":
        kwargs["recipe_pin"] = "a" * 64
    elif change == "bad_instance_pin":
        kwargs["instance_pin"] = "a" * 64
    elif change == "bad_profile_type":
        kwargs["profile_value"] = actual.profile.as_dict()
    elif change == "wrong_profile":
        kwargs["profile_value"] = profile(instance="9" * 32)
    elif change == "bad_exchange":
        payload = actual.consumption_exchange_bytes + b" "
        actual.exchange_path.chmod(0o640)
        actual.exchange_path.write_bytes(payload)
        actual.exchange_path.chmod(0o440)
        kwargs["exchange_pin"] = hashlib.sha256(payload).hexdigest()
    elif change == "exchange_symlink":
        actual.exchange_path.rename(actual.exchange_path.with_name("actual-exchange"))
        actual.exchange_path.symlink_to(
            actual.exchange_path.with_name("actual-exchange")
        )
    elif change == "exchange_hardlink":
        os.link(actual.exchange_path, actual.exchange_path.with_name("link"))
    elif change == "source_root_mode":
        actual.exchange_path.parent.chmod(0o700)
    elif change in {"source_root_owner", "source_root_group"}:
        root = actual.exchange_path.parent
        info = os.stat(root, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "source_root_owner" else 0,
            99 if change == "source_root_group" else 21201,
        )
    elif change == "extra_source_member":
        (actual.exchange_path.parent / "extra").write_bytes(b"")
    elif change == "extra_channel_member":
        (actual.actual(actual.consumed_root) / "extra").mkdir()
    elif change == "missing_namespace":
        actual.consumed_path.rmdir()
    elif change == "consumed_root_mode":
        actual.actual(actual.consumed_root).chmod(0o700)
    elif change in {"consumed_root_owner", "consumed_root_group"}:
        root = actual.actual(actual.consumed_root)
        info = os.stat(root, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "consumed_root_owner" else 20102,
            99 if change == "consumed_root_group" else 21201,
        )
    elif change == "namespace_mode":
        actual.consumed_path.chmod(0o700)
    elif change in {"namespace_owner", "namespace_group"}:
        info = os.stat(actual.consumed_path, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "namespace_owner" else 20102,
            99 if change == "namespace_group" else 21201,
        )
    elif change == "source_rw":
        actual.mount_lines[0] = actual.mount_lines[0].replace(" ro ", " rw ")
    elif change == "consumed_ro":
        actual.mount_lines[1] = actual.mount_lines[1].replace(" rw ", " ro ")
    elif change == "nested":
        actual.mount_lines.append(
            f"100 2 {actual.device} /nested {actual.namespace_root} "
            "rw - ext4 /dev/fake rw\n"
        )
    elif change == "device":
        actual.mount_lines[1] = actual.mount_lines[1].replace(
            f" {actual.device} ", " 999:999 "
        )
    elif change == "backing_alias":
        actual.mount_lines[1] = actual.mount_lines[1].replace(
            " /vol2 ", " /vol1/child "
        )
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open(**kwargs)


@pytest.mark.parametrize(
    "change",
    [
        "source",
        "source_bytes",
        "root",
        "namespace",
        "final",
        "platform",
    ],
)
def test_consumed_recheck_and_inspection_reject_currentness_drift(
    actual_consumption_exchange, monkeypatch, change
):
    actual = actual_consumption_exchange
    marker = consumed_marker()
    path = actual.add_final(marker)
    with actual.open() as source:
        if change == "source":
            actual.replace_exchange()
        elif change == "source_bytes":
            actual.exchange_path.chmod(0o640)
            actual.exchange_path.write_bytes(
                b"x" * len(actual.consumption_exchange_bytes)
            )
            actual.exchange_path.chmod(0o440)
        elif change == "root":
            root = actual.actual(actual.consumed_root)
            root.rename(root.with_name("old-consumed-root"))
            root.mkdir(mode=0o750)
            actual.register(root, 20102, 21201)
            child = root / "consumed"
            child.mkdir(mode=0o750)
            actual.register(child, 20102, 21201)
        elif change == "namespace":
            actual.consumed_path.rename(actual.consumed_path.with_name("old-consumed"))
            actual.consumed_path.mkdir(mode=0o750)
            actual.register(actual.consumed_path, 20102, 21201)
        elif change == "final":
            path.rename(path.with_name("old-final"))
            actual.add_final(marker)
        else:
            monkeypatch.setattr(actual.m, "native_platform", lambda: "linux/arm64")
        with pytest.raises(actual.c.DeploymentSourceError):
            source.inspect_consumed()


def test_consumed_inventory_rejects_marker_that_changes_during_retained_read(
    actual_consumption_exchange, monkeypatch
):
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    with actual.open() as source:
        path = actual.add_final(marker)
        original = actual.f._FinalFile.read_current
        reads = 0

        def mutate_after_first_read(selected):
            nonlocal reads
            raw = original(selected)
            reads += 1
            if reads == 1:
                path.chmod(0o640)
                path.write_bytes(consumed_marker(receipt_digest, outcome="unknown"))
                path.chmod(0o440)
            return raw

        monkeypatch.setattr(
            actual.f._FinalFile, "read_current", mutate_after_first_read
        )
        with pytest.raises(actual.c.DeploymentSourceError):
            source.inspect_consumed()


@pytest.mark.parametrize("drift", ["k_source", "namespace_membership"])
def test_consumed_inventory_rejects_drift_during_last_retained_read_and_closes_fds(
    actual_consumption_exchange, monkeypatch, drift
):
    actual = actual_consumption_exchange
    marker = consumed_marker(_selector(1))
    actual.add_final(marker)
    with actual.open() as source:
        original_read = actual.f._FinalFile.read_current
        reads = 0

        def drift_on_last_read(selected):
            nonlocal reads
            reads += 1
            if reads == 2:
                if drift == "k_source":
                    actual.replace_exchange()
                else:
                    (actual.consumed_path / "unexpected-late-member").write_bytes(b"x")
            return original_read(selected)

        opened = set()
        original_open, original_close = os.open, os.close

        def track_open(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            opened.add(fd)
            return fd

        def track_close(fd):
            original_close(fd)
            opened.discard(fd)

        monkeypatch.setattr(actual.f._FinalFile, "read_current", drift_on_last_read)
        monkeypatch.setattr(os, "open", track_open)
        monkeypatch.setattr(os, "close", track_close)
        with pytest.raises(actual.c.DeploymentSourceError):
            source.inspect_consumed()
        assert reads == 2
        assert opened == set()


def test_consumption_source_construction_copy_pickle_close_and_inert_observation(
    actual_consumption_exchange,
):
    actual, receipt_sources = actual_consumption_exchange, module("receipt_sources")
    with pytest.raises(TypeError):
        receipt_sources.ConsumptionExchangeSource()
    source = actual.open()
    observation = source.recheck_current().as_dict()
    observation["consumed"]["inode"] = 0
    assert source.recheck_current().as_dict()["consumed"]["inode"] != 0
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(source)
    source.close()
    source.close()
    for operation in (source.recheck_current, source.inspect_consumed):
        with pytest.raises(actual.c.DeploymentSourceError):
            operation()


@pytest.mark.parametrize("fail", [False, True])
def test_consumption_factory_closes_every_owned_descriptor(
    actual_consumption_exchange, monkeypatch, fail
):
    actual = actual_consumption_exchange
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
            actual.open(exchange_pin="a" * 64)
    else:
        with actual.open() as source:
            source.inspect_consumed()
    assert opened == set()


def test_consumption_requires_configured_protected_root(actual_consumption_exchange):
    actual = actual_consumption_exchange
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open(protected_roots=(Path("/run/deeptwin/missing-protected"),))


def test_consumption_source_has_no_database_import_or_acknowledgement_api(
    actual_consumption_exchange,
):
    with actual_consumption_exchange.open() as source:
        assert source.inspect_consumed() == ()
        assert not hasattr(source, "acknowledge")
        assert not hasattr(source, "consume")
        assert not hasattr(source, "import_receipt")
