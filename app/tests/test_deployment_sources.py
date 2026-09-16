import copy
import json
import pickle

import pytest

from app.tests.deployment_source_fixture import (
    actual_sources as actual_sources,  # noqa: PLC0414
)
from app.tests.deployment_source_fixture import module, profile


def test_real_independent_sources_and_held_slot(actual_sources):
    source = actual_sources
    with source.open_topology() as topology, source.open_exchange() as exchange:
        with topology.acquire_slot(1) as lease:
            lease.recheck_current()
            assert lease.topology_bytes == source.output.topology_bytes
            assert lease.slot["uid"] == 22001
            assert not hasattr(lease.metadata_lease, "secret")
            assert exchange.recheck_current() == exchange.recheck_current()
        with pytest.raises(source.c.DeploymentSourceError):
            lease.recheck_current()
    for handle in (topology, exchange):
        for clone in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                clone(handle)
        with pytest.raises(source.c.DeploymentSourceError):
            handle.recheck_current()
    with pytest.raises(source.c.DeploymentSourceError):
        _ = lease.topology_bytes


def test_t_loss_denies_admission_but_e_opens_after_restart(actual_sources):
    source = actual_sources
    with source.open_topology() as topology:
        source.actual(source.c.TOPOLOGY_ROOT / "topology.json").unlink()
        with pytest.raises(source.c.DeploymentSourceError):
            topology.acquire_slot(1)
        with pytest.raises(source.c.DeploymentSourceError):
            source.open_topology()
        with source.open_exchange() as exchange:
            assert exchange.recheck_current().root.inode > 0


def test_observed_outbox_namespace_identity_changes_after_restart(actual_sources):
    source = actual_sources
    with source.open_exchange() as exchange:
        before = exchange.recheck_current()
        path = source.actual(source.c.OUTBOX_ROOT / "requests")
        path.rename(path.with_name("old"))
        path.mkdir(mode=0o750)
        source.register(path, 20102, 21201)
        path.with_name("old").rmdir()
        with pytest.raises(source.c.DeploymentSourceError):
            exchange.recheck_current()
    with source.open_exchange() as exchange:
        assert exchange.recheck_current() != before


@pytest.mark.parametrize(
    "change",
    [
        "rw_source",
        "ro_outbox",
        "alias",
        "nested",
        "source_bytes",
        "namespace_mode",
        "extra",
    ],
)
def test_bad_actual_exchange_boundary_denies(actual_sources, change):
    s = actual_sources
    if change == "rw_source":
        s.mount_lines[1] = s.mount_lines[1].replace(" ro ", " rw ")
    elif change == "ro_outbox":
        s.mount_lines[2] = s.mount_lines[2].replace(" rw -", " ro -")
    elif change == "alias":
        s.mount_lines[2] = s.mount_lines[2].replace("/vol3", "/vol2/child")
    elif change == "nested":
        s.mount_lines.append(
            "99 3 8:1 /elsewhere /run/deeptwin/deployment-outbox/requests ro - ext4 /dev/fake rw\n"
        )
    elif change == "source_bytes":
        s.actual(s.c.EXCHANGE_ROOT / "exchange.json").chmod(0o640)
        s.actual(s.c.EXCHANGE_ROOT / "exchange.json").write_bytes(b"{}")
    elif change == "namespace_mode":
        s.actual(s.c.OUTBOX_ROOT / "requests").chmod(0o770)
    else:
        (s.actual(s.c.OUTBOX_ROOT) / "extra").touch()
    with pytest.raises(s.c.DeploymentSourceError):
        s.open_exchange()


def test_source_pin_and_derived_fields_checked(actual_sources):
    s = actual_sources
    data = json.loads(s.output.exchange_bytes)
    data["reader"]["uid"] = 20114
    raw = s.c.encode(data)
    path = s.actual(s.c.EXCHANGE_ROOT / "exchange.json")
    path.chmod(0o640)
    path.write_bytes(raw)
    path.chmod(0o440)
    s.pins["exchange_sha256"] = s.c.digest(raw)
    with pytest.raises(s.c.DeploymentSourceError):
        s.open_exchange()


def test_relevant_mount_drift_denies_but_unrelated_order_does_not(actual_sources):
    s = actual_sources
    with s.open_exchange() as exchange:
        before = exchange.recheck_current()
        s.mount_lines.reverse()
        assert exchange.recheck_current() == before
        s.mount_lines.append("100 999 9:1 / /unrelated rw - ext4 /dev/else rw\n")
        assert exchange.recheck_current() == before
        s.mount_lines = [
            line.replace("/vol3 ", "/different ") for line in s.mount_lines
        ]
        with pytest.raises(s.c.DeploymentSourceError):
            exchange.recheck_current()


def test_e_opens_with_vanished_t_mount_and_directory(actual_sources):
    s = actual_sources
    root = s.actual(s.c.TOPOLOGY_ROOT)
    root.rename(root.with_name("gone"))
    s.mount_lines = [
        line for line in s.mount_lines if str(s.c.TOPOLOGY_ROOT) not in line
    ]
    with s.open_exchange() as exchange:
        assert exchange.exchange_bytes == s.output.exchange_bytes


def test_configured_protected_root_missing_denies(actual_sources):
    s = actual_sources
    with pytest.raises(s.c.DeploymentSourceError):
        module("sources").open_exchange_source(
            profile=profile(),
            recipe_sha256=s.pins["recipe_sha256"],
            instance_sha256=s.pins["instance_sha256"],
            exchange_sha256=s.pins["exchange_sha256"],
            protected_roots=(s.c.OUTBOX_ROOT.parent / "missing-trust",),
        )


def test_namespace_stat_failure_is_sanitized(actual_sources, monkeypatch):
    s = actual_sources
    with s.open_exchange() as exchange:
        path = (
            s.actual(s.c.OUTBOX_ROOT / "requests")
            / ".stage-33333333-3333-4333-8333-333333333333.tmp"
        )
        path.touch(mode=0o600)
        s.register(path, 20102, 20102)
        original = s.f.stat_at

        def denied(fd, name):
            if fd == exchange._namespaces["request"].fd:
                raise PermissionError("private filesystem detail")
            return original(fd, name)

        monkeypatch.setattr(s.f, "stat_at", denied)
        with pytest.raises(
            s.c.DeploymentSourceError, match="^deployment_source_(invalid|unavailable)$"
        ):
            exchange.recheck_current()


def test_public_constructors_and_unsupported_os_cannot_open_sources(
    actual_sources, monkeypatch
):
    s, sources = actual_sources, module("sources")
    for cls in (
        sources.TopologySource,
        sources.ExchangeSource,
        sources.SlotMetadataLease,
    ):
        with pytest.raises(TypeError):
            cls()

    def unsupported():
        raise s.c.DeploymentSourceUnavailable()

    monkeypatch.setattr(s.m, "native_platform", unsupported)
    with pytest.raises(s.c.DeploymentSourceUnavailable):
        s.open_exchange()


def test_mount_device_must_match_actual_held_fd(actual_sources):
    s = actual_sources
    s.mount_lines[1] = s.mount_lines[1].replace(f" {s.device} ", " 999:999 ")
    with pytest.raises(s.c.DeploymentSourceError):
        s.open_exchange()


@pytest.mark.parametrize("fail", [False, True])
def test_factory_closes_all_explicit_fds_on_success_and_failure(
    actual_sources, monkeypatch, fail
):
    import os

    s = actual_sources
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
        s.pins["exchange_sha256"] = "a" * 64
        with pytest.raises(s.c.DeploymentSourceError):
            s.open_exchange()
    else:
        with s.open_exchange() as source:
            source.recheck_current()
    assert opened == set()


@pytest.mark.parametrize("value", [True, 0, 2, 17])
def test_slot_bounds_and_exact_types(actual_sources, value):
    s = actual_sources
    with s.open_topology() as source, pytest.raises(s.c.DeploymentSourceError):
        source.acquire_slot(value)


def test_slot_lock_exclusive_contention_is_source_busy(actual_sources):
    import fcntl
    import os

    s = actual_sources
    fd = os.open(s.actual(s.c.IPC_ROOT / "xs01" / "generation.lock"), os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with s.open_topology() as source, pytest.raises(s.c.DeploymentSourceBusy):
            source.acquire_slot(1)
    finally:
        os.close(fd)


def test_slot_alias_to_exchange_denies_admission(actual_sources):
    s = actual_sources
    s.mount_lines[3] = s.mount_lines[3].replace("/vol4", "/vol2/child")
    with pytest.raises(s.c.DeploymentSourceError), s.open_topology() as source:
        source.acquire_slot(1)


def test_held_slot_rechecks_its_own_mount(actual_sources):
    s = actual_sources
    with s.open_topology() as source, source.acquire_slot(1) as lease:
        s.mount_lines[3] = s.mount_lines[3].replace(" ro -", " rw -")
        with pytest.raises(s.c.DeploymentSourceError):
            lease.recheck_current()


def test_observed_other_source_alias_is_not_ignored_by_e(actual_sources):
    s = actual_sources
    s.mount_lines[3] = s.mount_lines[3].replace("/vol4", "/vol1/child")
    with pytest.raises(s.c.DeploymentSourceError):
        s.open_exchange()


def test_observed_receipt_root_alias_is_not_ignored_by_old_exchange(actual_sources):
    s = actual_sources
    s.mount_lines.append(
        f"100 999 {s.device} /vol2/child /run/deeptwin/deployment-verify-public "
        "ro - ext4 /dev/fake rw\n"
    )
    with pytest.raises(s.c.DeploymentSourceError):
        s.open_exchange()


def test_removed_nonoverlapping_receipt_root_does_not_invalidate_old_exchange(
    actual_sources,
):
    s = actual_sources
    receipt_line = (
        "100 999 9:1 /receipt /run/deeptwin/deployment-verify-public "
        "ro - ext4 /dev/receipt rw\n"
    )
    s.mount_lines.append(receipt_line)
    with s.open_exchange() as exchange:
        before = exchange.recheck_current()
        s.mount_lines.remove(receipt_line)
        assert exchange.recheck_current() == before


def test_optional_nested_mount_is_alias_only_for_old_exchange(actual_sources):
    s = actual_sources
    s.mount_lines.extend(
        [
            (
                "100 999 9:1 /receipt /run/deeptwin/deployment-verify-public "
                "ro - ext4 /dev/receipt rw\n"
            ),
            (
                "101 100 10:1 /nested "
                "/run/deeptwin/deployment-verify-public/child "
                "ro - ext4 /dev/nested rw\n"
            ),
        ]
    )
    with s.open_exchange() as exchange:
        s.mount_lines[-1] = (
            f"101 100 {s.device} /vol2/child "
            "/run/deeptwin/deployment-verify-public/child "
            "ro - ext4 /dev/fake rw\n"
        )
        with pytest.raises(s.c.DeploymentSourceError):
            exchange.recheck_current()
