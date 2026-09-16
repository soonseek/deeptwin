import copy
import hashlib
import os
import pickle
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from app.tests.deployment_receipt_source_fixture import (
    actual_consumption_exchange as actual_consumption_exchange,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import (
    actual_portable_receipt_ingress as actual_portable_receipt_ingress,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import (
    actual_public_trust as actual_public_trust,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import (
    actual_receipt_ingress as actual_receipt_ingress,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import trust_bytes
from app.tests.deployment_source_fixture import ROOT, module, profile


def _selector(hex_digest):
    from base64 import urlsafe_b64encode

    return urlsafe_b64encode(bytes.fromhex(hex_digest)).rstrip(b"=").decode("ascii")


def test_actual_ingress_retains_j_and_exact_channel_identity(actual_receipt_ingress):
    actual = actual_receipt_ingress
    with actual.open() as source:
        assert source.ingress_bytes == actual.ingress_bytes
        identity = source.recheck_current()
        value = identity.as_dict()
        assert value["schema_version"] == "deployment-receipt-ingress-identity-v1"
        assert value["source"]["source_kind"] == "ingress"
        assert value["source"]["schema_version"] == (
            "deployment-public-source-identity-v1"
        )
        assert set(value["source"]["root"]) == {"device", "inode"}
        assert set(value["source"]["file"]) == {"device", "inode"}
        assert set(value["root"]) == {"device", "inode"}
        assert set(value["receipts"]) == {"device", "inode"}
        assert len(value["source"]["backing_root_digest"]) == 64
        assert len(value["backing_root_digest"]) == 64
        value["receipts"]["inode"] = 0
        assert source.recheck_current().as_dict()["receipts"]["inode"] != 0
        assert source.list_available_receipt_digests() == ()


def test_ingress_lists_64_finals_in_filename_order_without_payload_reads(
    actual_receipt_ingress, monkeypatch
):
    actual = actual_receipt_ingress
    expected_hex = [f"{number:064x}" for number in reversed(range(64))]
    for digest_hex in expected_hex:
        actual.add_final(b"not-read", digest_hex=digest_hex)
    for number in range(32):
        actual.add_stage(number, b"stage-bytes-are-not-read")
    payload_reads = []
    with actual.open() as source:
        original = actual.f._open_final

        def guarded_open(*args, **kwargs):
            payload_reads.append((args, kwargs))
            return original(*args, **kwargs)

        monkeypatch.setattr(actual.f, "_open_final", guarded_open)
        values = source.list_available_receipt_digests()
    assert values == tuple(_selector(value) for value in sorted(expected_hex))
    assert len(values) == 64
    assert payload_reads == []


@pytest.mark.parametrize("finals,stages", [(65, 0), (0, 33), (65, 33)])
def test_ingress_listing_rejects_fixed_inventory_overflow(
    actual_receipt_ingress, finals, stages
):
    actual = actual_receipt_ingress
    for number in range(finals):
        actual.add_final(b"x", digest_hex=f"{number:064x}")
    for number in range(stages):
        actual.add_stage(number)
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open()


def test_ingress_lists_metadata_valid_intrinsically_invalid_final(
    actual_receipt_ingress,
):
    actual = actual_receipt_ingress
    payload = b"intrinsically-invalid-receipt"
    path = actual.add_final(payload)
    expected = _selector(path.stem)
    with actual.open() as source:
        assert source.list_available_receipt_digests() == (expected,)


def test_portable_public_fixture_also_binds_actual_j_and_inbox(
    actual_portable_receipt_ingress,
):
    actual = actual_portable_receipt_ingress
    actual.add_final()
    with actual.open() as source:
        assert source.ingress_bytes == actual.ingress_bytes
        assert source.list_available_receipt_digests() == (actual.receipt_digest,)


def test_malformed_unselected_metadata_denies_the_complete_ingress(
    actual_receipt_ingress,
):
    actual = actual_receipt_ingress
    actual.add_final()
    unsafe = actual.add_final(b"unselected", digest_hex="0" * 64)
    unsafe.chmod(0o640)
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
        "bad_ingress",
        "ingress_symlink",
        "ingress_hardlink",
        "source_root_symlink",
        "source_root_mode",
        "source_root_owner",
        "source_root_group",
        "extra_source_member",
        "extra_channel_member",
        "missing_namespace",
        "incoming_root_symlink",
        "incoming_root_mode",
        "incoming_root_owner",
        "incoming_root_group",
        "namespace_symlink",
        "namespace_mode",
        "namespace_owner",
        "namespace_group",
        "source_rw",
        "incoming_rw",
        "nested",
        "device",
        "backing_alias",
    ],
)
def test_ingress_open_rejects_invalid_j_or_actual_boundaries(
    actual_receipt_ingress, change
):
    actual = actual_receipt_ingress
    kwargs = {}
    if change == "bad_pin":
        kwargs["ingress_pin"] = "a" * 64
    elif change == "bad_recipe_pin":
        kwargs["recipe_pin"] = "a" * 64
    elif change == "bad_instance_pin":
        kwargs["instance_pin"] = "a" * 64
    elif change == "bad_profile_type":
        kwargs["profile_value"] = actual.profile.as_dict()
    elif change == "wrong_profile":
        kwargs["profile_value"] = profile(instance="9" * 32)
    elif change == "bad_ingress":
        payload = actual.ingress_bytes + b" "
        actual.ingress_path.chmod(0o640)
        actual.ingress_path.write_bytes(payload)
        actual.ingress_path.chmod(0o440)
        kwargs["ingress_pin"] = hashlib.sha256(payload).hexdigest()
    elif change == "ingress_symlink":
        actual.ingress_path.rename(actual.ingress_path.with_name("actual-ingress"))
        actual.ingress_path.symlink_to(actual.ingress_path.with_name("actual-ingress"))
    elif change == "ingress_hardlink":
        os.link(actual.ingress_path, actual.ingress_path.with_name("link"))
    elif change == "source_root_symlink":
        root = actual.ingress_path.parent
        root.rename(root.with_name("actual-ingress-root"))
        root.symlink_to(root.with_name("actual-ingress-root"), target_is_directory=True)
    elif change == "source_root_mode":
        actual.ingress_path.parent.chmod(0o700)
    elif change in {"source_root_owner", "source_root_group"}:
        root = actual.ingress_path.parent
        info = os.stat(root, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "source_root_owner" else 0,
            99 if change == "source_root_group" else 21201,
        )
    elif change == "extra_source_member":
        (actual.ingress_path.parent / "extra").write_bytes(b"")
    elif change == "extra_channel_member":
        (actual.actual(actual.incoming_root) / "extra").write_bytes(b"")
    elif change == "missing_namespace":
        actual.receipts_path.rmdir()
    elif change == "incoming_root_symlink":
        root = actual.actual(actual.incoming_root)
        root.rename(root.with_name("actual-incoming-root"))
        root.symlink_to(
            root.with_name("actual-incoming-root"), target_is_directory=True
        )
    elif change == "incoming_root_mode":
        actual.actual(actual.incoming_root).chmod(0o700)
    elif change in {"incoming_root_owner", "incoming_root_group"}:
        root = actual.actual(actual.incoming_root)
        info = os.stat(root, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "incoming_root_owner" else 20113,
            99 if change == "incoming_root_group" else 21201,
        )
    elif change == "namespace_symlink":
        actual.receipts_path.rename(actual.receipts_path.with_name("actual-receipts"))
        actual.receipts_path.symlink_to(
            actual.receipts_path.with_name("actual-receipts"), target_is_directory=True
        )
    elif change == "namespace_mode":
        actual.receipts_path.chmod(0o700)
    elif change in {"namespace_owner", "namespace_group"}:
        info = os.stat(actual.receipts_path, follow_symlinks=False)
        actual.metadata[(info.st_dev, info.st_ino)] = (
            99 if change == "namespace_owner" else 20113,
            99 if change == "namespace_group" else 21201,
        )
    elif change == "source_rw":
        actual.mount_lines[0] = actual.mount_lines[0].replace(" ro ", " rw ")
    elif change == "incoming_rw":
        actual.mount_lines[1] = actual.mount_lines[1].replace(" ro ", " rw ")
    elif change == "nested":
        actual.mount_lines.append(
            f"100 2 {actual.device} /nested {actual.receipts_root} "
            "ro - ext4 /dev/fake rw\n"
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
        "ingress",
        "bytes",
        "mode",
        "owner",
        "group",
        "incoming_root",
        "namespace",
        "unsafe_final",
        "platform",
    ],
)
def test_retained_ingress_recheck_rejects_source_or_channel_drift(
    actual_receipt_ingress, monkeypatch, change
):
    actual = actual_receipt_ingress
    with actual.open() as source:
        if change == "ingress":
            actual.replace_ingress()
        elif change == "bytes":
            actual.ingress_path.chmod(0o640)
            actual.ingress_path.write_bytes(b"x" * len(actual.ingress_bytes))
            actual.ingress_path.chmod(0o440)
        elif change == "mode":
            actual.ingress_path.chmod(0o640)
        elif change in {"owner", "group"}:
            info = os.stat(actual.ingress_path, follow_symlinks=False)
            actual.metadata[(info.st_dev, info.st_ino)] = (
                99 if change == "owner" else 0,
                99 if change == "group" else 21201,
            )
        elif change == "incoming_root":
            root = actual.actual(actual.incoming_root)
            root.rename(root.with_name("old-incoming"))
            root.mkdir(mode=0o750)
            actual.register(root, 20113, 21201)
            child = root / "receipts"
            child.mkdir(mode=0o750)
            actual.register(child, 20113, 21201)
        elif change == "namespace":
            actual.receipts_path.rename(actual.receipts_path.with_name("old-receipts"))
            actual.receipts_path.mkdir(mode=0o750)
            actual.register(actual.receipts_path, 20113, 21201)
        elif change == "unsafe_final":
            path = actual.add_final(b"x")
            path.chmod(0o640)
        else:
            monkeypatch.setattr(actual.m, "native_platform", lambda: "linux/arm64")
        with pytest.raises(actual.c.DeploymentSourceError):
            source.recheck_current()


def test_ingress_public_construction_copy_pickle_and_close_do_not_grant_authority(
    actual_receipt_ingress,
):
    actual, receipt_sources = actual_receipt_ingress, module("receipt_sources")
    with pytest.raises(TypeError):
        receipt_sources.ReceiptIngressSource()
    source = actual.open()
    for operation in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            operation(source)
    source.close()
    source.close()
    with pytest.raises(actual.c.DeploymentSourceError):
        source.list_available_receipt_digests()


def test_ingress_source_opens_only_j_and_inbox_without_crypto_or_ipc(
    actual_receipt_ingress, monkeypatch
):
    actual = actual_receipt_ingress
    receipt_contracts = module("receipt_contracts")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unrelated authority path was used")

    monkeypatch.setattr(receipt_contracts, "verify_receipt", forbidden)
    with actual.open() as source:
        assert source.ingress_bytes == actual.ingress_bytes
        assert source.list_available_receipt_digests() == ()
    receipt_sources = module("receipt_sources")
    assert not hasattr(receipt_sources, "verify_receipt")
    assert not hasattr(receipt_sources, "verify_detached")


@pytest.mark.parametrize("fail", [False, True])
def test_ingress_factory_closes_every_owned_descriptor(
    actual_receipt_ingress, monkeypatch, fail
):
    actual = actual_receipt_ingress
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
            actual.open(ingress_pin="a" * 64)
    else:
        with actual.open() as source:
            source.recheck_current()
    assert opened == set()


def test_ingress_requires_each_configured_protected_root(actual_receipt_ingress):
    actual = actual_receipt_ingress
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open(protected_roots=(Path("/run/deeptwin/missing-protected"),))


def test_optional_receipt_root_is_alias_checked_without_becoming_j_readiness(
    actual_receipt_ingress,
):
    actual = actual_receipt_ingress
    optional = Path("/run/deeptwin/deployment-verify-public")
    actual.actual(optional).mkdir(parents=True)
    actual.mount_lines.append(
        f"100 999 {actual.device} /vol2/alias {optional} ro - ext4 /dev/fake rw\n"
    )
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open()


def test_configured_protected_root_cannot_alias_the_incoming_backing(
    actual_receipt_ingress,
):
    actual = actual_receipt_ingress
    protected = Path("/run/deeptwin/configured-data")
    path = actual.actual(protected)
    path.mkdir(parents=True)
    actual.mount_lines.append(
        f"100 999 {actual.device} /vol2/protected {protected} rw - ext4 /dev/fake rw\n"
    )
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open(protected_roots=(protected,))


def test_actual_public_trust_is_retained_and_identity_snapshots_are_inert(
    actual_public_trust,
):
    actual = actual_public_trust
    source = actual.open()
    try:
        assert source.trust_bytes == actual.trust_bytes
        before = source.recheck_current().as_dict()
        assert before["schema_version"] == "deployment-public-source-identity-v1"
        assert before["source_kind"] == "trust"
        assert set(before["root"]) == {"device", "inode"}
        assert set(before["file"]) == {"device", "inode"}
        before["root"]["inode"] = 0
        assert source.recheck_current().as_dict()["root"]["inode"] != 0
    finally:
        source.close()
    source.close()
    with pytest.raises(actual.c.DeploymentSourceError):
        source.recheck_current()


def test_public_construction_copy_and_pickle_never_supply_source_authority(
    actual_public_trust,
):
    actual, receipt_sources = actual_public_trust, module("receipt_sources")
    with pytest.raises(TypeError):
        receipt_sources.PublicTrustSource()
    with actual.open() as source:
        for operation in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                operation(source)


@pytest.mark.parametrize("change", ["file", "root", "bytes", "mode", "owner", "group"])
def test_retained_public_trust_rejects_every_currentness_change(
    actual_public_trust, change
):
    actual = actual_public_trust
    with actual.open() as source:
        if change == "file":
            actual.replace_file()
        elif change == "root":
            root = actual.actual(actual.public_root)
            root.rename(root.with_name("old-root"))
            root.mkdir(mode=0o750)
            actual.register(root, 0, 20102)
            path = root / "trust-set.json"
            path.write_bytes(actual.trust_bytes)
            path.chmod(0o440)
            actual.register(path, 0, 20102)
        elif change == "bytes":
            actual.trust_path.chmod(0o640)
            actual.trust_path.write_bytes(actual.trust_bytes + b" ")
            actual.trust_path.chmod(0o440)
        elif change == "mode":
            actual.trust_path.chmod(0o640)
        else:
            info = os.stat(actual.trust_path, follow_symlinks=False)
            uid, gid = actual.metadata[(info.st_dev, info.st_ino)]
            actual.metadata[(info.st_dev, info.st_ino)] = (
                99 if change == "owner" else uid,
                99 if change == "group" else gid,
            )
        with pytest.raises(actual.c.DeploymentSourceError):
            source.recheck_current()


@pytest.mark.parametrize(
    "change",
    [
        "bad_pin",
        "bad_profile_type",
        "wrong_profile",
        "bad_trust",
        "file_symlink",
        "file_hardlink",
        "root_symlink",
        "rw",
        "nested",
        "device",
        "backing_alias",
    ],
)
def test_public_trust_open_fails_closed_for_invalid_inputs_and_boundaries(
    actual_public_trust, monkeypatch, change
):
    actual = actual_public_trust
    pin, profile_value = None, None
    if change == "bad_pin":
        pin = "a" * 64
    elif change == "bad_profile_type":
        profile_value = actual.profile.as_dict()
    elif change == "wrong_profile":
        profile_value = profile(instance="9" * 32)
    elif change == "bad_trust":
        payload = trust_bytes(profile(instance="9" * 32))
        actual.trust_path.chmod(0o640)
        actual.trust_path.write_bytes(payload)
        actual.trust_path.chmod(0o440)
        actual.trust_sha256 = actual.c.digest(payload)
    elif change == "file_symlink":
        actual.trust_path.rename(actual.trust_path.with_name("actual"))
        actual.trust_path.symlink_to(actual.trust_path.with_name("actual"))
    elif change == "file_hardlink":
        os.link(actual.trust_path, actual.trust_path.with_name("link"))
    elif change == "root_symlink":
        root = actual.actual(actual.public_root)
        root.rename(root.with_name("actual-root"))
        root.symlink_to(root.with_name("actual-root"), target_is_directory=True)
    elif change == "rw":
        actual.mount_lines[0] = actual.mount_lines[0].replace(" ro ", " rw ")
    elif change == "nested":
        actual.mount_lines.append(
            f"100 1 {actual.device} /nested {actual.public_root}/nested "
            "ro - ext4 /dev/fake rw\n"
        )
    elif change == "device":
        actual.mount_lines[0] = actual.mount_lines[0].replace(
            f" {actual.device} ", " 999:999 "
        )
    elif change == "backing_alias":
        actual.mount_lines[0] = actual.mount_lines[0].replace(
            " /vol1 ", " /vol2/child "
        )
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
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open(profile_value=profile_value, pin=pin)
    assert opened == set()


def test_public_trust_requires_configured_protected_roots(actual_public_trust):
    actual = actual_public_trust
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open(protected_roots=(Path("/run/deeptwin/missing-configured-root"),))


def test_unrelated_mount_order_and_optional_source_content_do_not_block_u(
    actual_public_trust,
):
    actual = actual_public_trust
    optional = "/run/deeptwin/deployment-receipt-ingress"
    path = actual.actual(optional)
    path.mkdir(parents=True)
    marker = path / "unrelated"
    marker.write_bytes(b"before")
    actual.mount_lines.append(
        "100 999 9:1 /receipt /run/deeptwin/deployment-receipt-ingress "
        "ro - ext4 /dev/receipt rw\n"
    )
    with actual.open() as source:
        before = source.recheck_current()
        actual.mount_lines.reverse()
        marker.write_bytes(b"after")
        assert source.recheck_current() == before


def test_optional_nested_mount_is_alias_only_for_public_trust(actual_public_trust):
    actual = actual_public_trust
    actual.mount_lines.extend(
        [
            (
                "100 999 9:1 /receipt /run/deeptwin/deployment-receipt-ingress "
                "ro - ext4 /dev/receipt rw\n"
            ),
            (
                "101 100 10:1 /nested "
                "/run/deeptwin/deployment-receipt-ingress/child "
                "ro - ext4 /dev/nested rw\n"
            ),
        ]
    )
    with actual.open() as source:
        actual.mount_lines[-1] = (
            f"101 100 {actual.device} /vol1/child "
            "/run/deeptwin/deployment-receipt-ingress/child "
            "ro - ext4 /dev/fake rw\n"
        )
        with pytest.raises(actual.c.DeploymentSourceError):
            source.recheck_current()


def test_platform_drift_invalidates_retained_u(actual_public_trust, monkeypatch):
    actual = actual_public_trust
    with actual.open() as source:
        monkeypatch.setattr(actual.m, "native_platform", lambda: "linux/arm64")
        with pytest.raises(actual.c.DeploymentSourceError):
            source.recheck_current()


@pytest.mark.parametrize("fail", [False, True])
def test_public_trust_factory_closes_all_fds(actual_public_trust, monkeypatch, fail):
    actual = actual_public_trust
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
            actual.open(pin="a" * 64)
    else:
        with actual.open() as source:
            source.recheck_current()
    assert opened == set()


def test_structure_only_public_source_does_not_touch_ipc_or_crypto(
    actual_public_trust, monkeypatch
):
    actual = actual_public_trust
    from app.workers import ipc_root

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unrelated authority path was opened")

    monkeypatch.setattr(ipc_root, "acquire_generation_metadata", forbidden)
    receipt_contracts = module("receipt_contracts")
    monkeypatch.setattr(receipt_contracts, "verify_receipt", forbidden)
    with actual.open() as source:
        assert source.trust_bytes == actual.trust_bytes
    receipt_sources = module("receipt_sources")
    assert not hasattr(receipt_sources, "verify_receipt")
    assert not hasattr(receipt_sources, "verify_detached")


def test_fresh_process_actual_public_trust_open_has_no_crypto_or_ipc_import(
    actual_public_trust,
):
    actual = actual_public_trust
    script = textwrap.dedent(
        """
        import builtins
        import importlib
        import os
        import sys
        from pathlib import Path
        from types import SimpleNamespace

        from app.operations.setup import OriginProfile
        from app.deployment import contracts as c
        from app.deployment import files as f
        from app.deployment import mounts as m

        base = Path(sys.argv[1])
        pin = sys.argv[2]
        public_root = Path("/run/deeptwin/deployment-verify-public")
        logical_roots = (public_root, *c.BUILTIN_ROOTS)
        actual_paths = tuple(base.joinpath(*path.parts[1:]) for path in logical_roots)
        real_stat, real_fstat = os.stat, os.fstat
        metadata = {}
        for index, path in enumerate(actual_paths):
            info = real_stat(path, follow_symlinks=False)
            metadata[(info.st_dev, info.st_ino)] = (0, 20102) if index == 0 else (20102, 20102)
        trust_path = actual_paths[0] / "trust-set.json"
        info = real_stat(trust_path, follow_symlinks=False)
        metadata[(info.st_dev, info.st_ino)] = (0, 20102)

        def observed(info):
            uid, gid = metadata.get((info.st_dev, info.st_ino), (info.st_uid, info.st_gid))
            values = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
            return SimpleNamespace(**(values | {"st_uid": uid, "st_gid": gid}))

        os.fstat = lambda fd: observed(real_fstat(fd))
        os.stat = lambda *args, **kwargs: observed(real_stat(*args, **kwargs))
        original_open_directory = f.open_directory
        f.open_directory = lambda path, **kwargs: original_open_directory(
            base.joinpath(*path.parts[1:]), **kwargs
        )
        device = real_stat(base).st_dev
        device_text = f"{os.major(device)}:{os.minor(device)}"
        lines = []
        for index, path in enumerate(logical_roots, 1):
            lines.append(
                f"{index} 999 {device_text} /vol{index} {path} "
                f"{'ro' if index == 1 else 'rw'} - ext4 /dev/fake rw\\n"
            )
        m.native_platform = lambda: "linux/amd64"
        m.read_mountinfo = lambda: m.parse_mountinfo("".join(lines).encode())

        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.startswith("nacl") or name == "receipt_crypto" or name.endswith("ipc_root"):
                raise AssertionError("forbidden authority import: " + name)
            return original_import(name, *args, **kwargs)
        builtins.__import__ = guarded_import

        receipt_sources = importlib.import_module("app.deployment.receipt_sources")
        profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=8080)
        with receipt_sources.open_public_trust_source(
            profile=profile, trust_sha256=pin, protected_roots=()
        ) as source:
            assert source.trust_bytes == trust_path.read_bytes()
            assert source.recheck_current().source_kind == "trust"
        assert not any(name == "nacl" or name.startswith("nacl.") for name in sys.modules)
        assert "app.deployment.receipt_crypto" not in sys.modules
        assert "app.workers.ipc_root" not in sys.modules
        print("fresh-retained-u-ok")
        """
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", script, str(actual.base), actual.trust_sha256],
        cwd=ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "fresh-retained-u-ok\n"


def test_consumption_source_is_independent_of_u_j_t_e_and_private_authority(
    actual_consumption_exchange, monkeypatch
):
    actual = actual_consumption_exchange

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unrelated source or authority path was used")

    receipt_contracts = module("receipt_contracts")
    monkeypatch.setattr(receipt_contracts, "verify_receipt", forbidden)
    with actual.open() as source:
        assert source.consumption_exchange_bytes == actual.consumption_exchange_bytes
        assert source.inspect_consumed() == ()
    receipt_sources = module("receipt_sources")
    assert not hasattr(receipt_sources, "verify_receipt")
    assert not hasattr(receipt_sources, "verify_detached")
