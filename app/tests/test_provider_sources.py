"""Actual retained reader tests; ownership/mount/native facts are simulated."""

import copy
import importlib
import json
import os
import pickle
from pathlib import Path

import pytest

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import mounts as m
from app.operations.setup import OriginProfile
from app.tests.deployment_source_fixture import (
    actual_sources as actual_sources,  # noqa: PLC0414
)
from app.tests.provider_source_fixture import case, refresh_outer
from app.tests.provider_source_reader_fixture import (
    CHANNELS,
    ORIGINALS,
    STATIC,
    ReaderTree,
    reader_module,
)
from app.tests.provider_source_reader_fixture import (
    reader_tree as reader_tree,  # noqa: PLC0414
)


def test_real_retained_reader_returns_exact_bundle(reader_tree):
    with reader_tree.open() as source:
        assert source.read_current() == reader_tree.bundle
        assert source.recheck_current() is None
    assert not reader_tree.live


@pytest.mark.parametrize("fault", [None, "nested", "cross"])
def test_old_mapping_characterization(actual_sources, monkeypatch, fault):
    s = actual_sources
    optional = "/run/deeptwin/deployment-receipts"
    s.mount_lines.append(f"90 1 {s.device} /safe {optional} ro - ext4 /fake rw\n")
    if fault == "nested":
        s.mount_lines.append(
            f"91 90 {s.device} /vol2 {optional}/child ro - ext4 /fake rw\n"
        )
    elif fault == "cross":
        s.mount_lines.append(
            f"91 1 {s.device} /safe/child /run/deeptwin/deployment-consumed rw - ext4 /fake rw\n"
        )
    if fault:
        with pytest.raises(c.DeploymentSourceError):
            s.open_exchange()
        return
    with s.open_exchange() as source:
        observed = m.parse_mountinfo("".join(s.mount_lines).encode())
        calls = []
        monkeypatch.setattr(m, "read_mountinfo", lambda: (calls.append(1), observed)[1])
        expected = m.verify_boundaries(
            observed, source._required, tuple(p.path for p in source._protected)
        )
        assert source._mapping_for(source._required) == expected
        assert calls == [1]


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("platform", ["linux/amd64", "linux/arm64"])
@pytest.mark.parametrize("capacity", [1, 16])
def test_complete_origins_platforms_and_capacities(
    tmp_path, monkeypatch, portable, platform, capacity
):
    tree = ReaderTree(
        tmp_path, monkeypatch, portable=portable, platform=platform, capacity=capacity
    )
    with tree.open() as source:
        assert source.read_current() == tree.bundle
    assert not tree.live


@pytest.mark.parametrize(
    "changes",
    [
        {"context_sha256": "A" * 64},
        {"context_sha256": None},
        {"protected_roots": []},
        {"protected_roots": (Path("relative"),)},
        {"protected_roots": (Path("/a/../b"),)},
        {"protected_roots": (Path("/x"),) * 65},
        {"protected_roots": (Path("/" + "x" * 4096),)},
        {"profile": None},
    ],
)
def test_invalid_entry_opens_nothing(reader_tree, changes):
    with pytest.raises(c.DeploymentSourceError):
        reader_tree.open(**changes)
    assert not reader_tree.opens


def test_actual_nonlinux_sampler_refuses_before_open(reader_tree, monkeypatch):
    native = importlib.reload(m).native_platform
    monkeypatch.setattr(m.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(m, "native_platform", native)
    with pytest.raises(c.DeploymentSourceUnavailable):
        reader_tree.open()
    assert not reader_tree.opens


@pytest.mark.parametrize(
    "fault",
    ["pin", "profile", "platform", "actual", "valid_other_graph", "deferred_join"],
)
def test_cold_join_refusal_closes(reader_tree, fault):
    tree = reader_tree
    changes = {}
    if fault == "pin":
        changes["context_sha256"] = "f" * 64
    elif fault == "profile":
        changes["profile"] = OriginProfile.local(
            instance_id=tree.profile.instance_id, path_id="3" * 32, port=8080
        )
    elif fault == "platform":
        tree.platform = "linux/arm64"
    elif fault == "actual":
        root, name, gid, _ = ORIGINALS[0]
        tree.write(root / name, b"unrelated", 0, gid)
    elif fault == "valid_other_graph":
        _, alternate, _ = case(capacity=16)
        from app.deployment.provider_source_contracts import (
            validate_provider_source_bundle,
        )

        validate_provider_source_bundle(alternate)
        tree.install_bundle(alternate)
        changes["context_sha256"] = c.digest(alternate[16][1])
    else:
        value = json.loads(tree.bundle[3][1])
        value["exchange_id"] = "12345678-1234-4234-8234-123456789012"
        alternate = refresh_outer(tree.bundle, 3, value)
        tree.install_bundle(alternate)
        changes["context_sha256"] = c.digest(alternate[16][1])
    with pytest.raises(c.DeploymentSourceError):
        tree.open(**changes)
    assert not tree.live


@pytest.mark.parametrize(
    "fault",
    [
        "bytes",
        "same_inode_bytes",
        "documents",
        "original",
        "namespace",
        "protected",
        "platform",
    ],
)
def test_static_retention_never_rebases(reader_tree, fault):
    tree = reader_tree
    with tree.open() as source:
        if fault in {"bytes", "same_inode_bytes"}:
            path = tree.actual(STATIC / "documents/geometry.json")
            raw = path.read_bytes()
            if fault == "same_inode_bytes":
                path.unlink()
            tree.write(
                STATIC / "documents/geometry.json",
                raw if fault == "same_inode_bytes" else raw + b" ",
                0,
                21201,
            )
        elif fault == "original":
            root, name, gid, _ = ORIGINALS[0]
            path = tree.actual(root / name)
            raw = path.read_bytes()
            path.rename(path.with_name("old"))
            tree.write(root / name, raw, 0, gid)
            path.with_name("old").unlink()
        elif fault == "platform":
            tree.platform = "linux/arm64"
        else:
            logical = {
                "documents": STATIC / "documents",
                "namespace": CHANNELS[0][0] / "cancelled",
                "protected": c.BUILTIN_ROOTS[0],
            }[fault]
            path = tree.actual(logical)
            path.rename(path.with_name(path.name + "-old"))
            tree.directory(
                logical,
                20102 if fault != "documents" else 0,
                20102 if fault == "protected" else 21201,
            )
        for _ in range(2):
            with pytest.raises(c.DeploymentSourceError):
                source.read_current()
        assert tree.live
    assert not tree.live


@pytest.mark.parametrize(
    "fault",
    [
        "mode",
        "owner",
        "gid",
        "hardlink",
        "symlink",
        "empty",
        "cap",
        "extra",
        "root_mode",
    ],
)
def test_invalid_static_metadata_refuses(reader_tree, fault):
    tree = reader_tree
    path = tree.actual(STATIC / "documents/source-pins.json")
    if fault == "mode":
        path.chmod(0o640)
    elif fault in {"owner", "gid"}:
        tree.register(
            path, 1 if fault == "owner" else 0, 1 if fault == "gid" else 21201
        )
    elif fault == "hardlink":
        os.link(path, tree.base / "linked")
    elif fault == "symlink":
        other = tree.base / "elsewhere"
        path.rename(other)
        path.symlink_to(other)
    elif fault in {"empty", "cap"}:
        tree.write(
            STATIC / "documents/source-pins.json",
            b"" if fault == "empty" else b"x" * 8193,
            0,
            21201,
        )
    elif fault == "extra":
        tree.write(STATIC / "extra", b"x", 0, 21201)
    else:
        tree.actual(STATIC).chmod(0o755)
    with pytest.raises(c.DeploymentSourceError):
        tree.open()
    assert not tree.live


def test_safe_channel_changes_between_calls_and_no_payload_opens(reader_tree):
    tree = reader_tree
    with tree.open() as source:
        for _, namespace, _, _, _, cap in CHANNELS:
            final = tree.payload(namespace, raw=b"x" * cap)
            for state in range(3):
                tree.payload(namespace, state + 1, stage=True, state=state, raw=b"")
            assert source.read_current() == tree.bundle
            final.unlink()
            source.recheck_current()
        payload_dirs = tuple(tree.actual(root / name) for root, name, *_ in CHANNELS)
        assert not any(path.parent in payload_dirs for path, _ in tree.opens)
        assert not any(flags & (os.O_CREAT | os.O_TRUNC) for _, flags in tree.opens)
    assert not tree.live


@pytest.mark.parametrize(
    "point", ["during_scan", "between", "same_stage", "cross_namespace"]
)
def test_whole_operation_channel_snapshot_refusal_then_explicit_retry(
    reader_tree, monkeypatch, point
):
    tree = reader_tree
    stage = tree.payload("cancelled", stage=True)
    source = tree.open()
    module = reader_module()
    original = (
        f._scan_namespace
        if point == "during_scan"
        else module._snapshot_provider_namespace
    )
    count = 0

    def change(*args, **kw):
        nonlocal count
        result = original(*args, **kw)
        count += 1
        if count == (1 if point == "during_scan" else 4):
            if point == "same_stage":
                stage.unlink()
                tree.payload("cancelled", stage=True, raw=b"changed")
            elif point == "cross_namespace":
                stage.rename(tree.actual(CHANNELS[1][0] / "requests") / stage.name)
            else:
                tree.payload("cancelled", 2)
        return result

    with monkeypatch.context() as patch:
        patch.setattr(
            f if point == "during_scan" else module,
            "_scan_namespace"
            if point == "during_scan"
            else "_snapshot_provider_namespace",
            change,
        )
        with pytest.raises(c.DeploymentSourceError):
            source.read_current()
    assert source.read_current() == tree.bundle
    source.close()
    assert not tree.live


@pytest.mark.parametrize("namespace", [row[1] for row in CHANNELS])
@pytest.mark.parametrize(
    "overflow",
    ["final", "stage", "bytes", "zero", "bad_name", "owner", "mode", "hardlink"],
)
def test_channel_boundaries(reader_tree, namespace, overflow):
    tree = reader_tree
    _root, _, _uid, _, limit, cap = next(row for row in CHANNELS if row[1] == namespace)
    if overflow in {"final", "stage"}:
        for number in range(1, (limit if overflow == "final" else 32) + 1):
            tree.payload(namespace, number, stage=overflow == "stage")
        with tree.open() as source:
            source.recheck_current()
        tree.payload(namespace, 100, stage=overflow == "stage")
    else:
        path = tree.payload(
            namespace,
            raw=b"x" * (cap + 1)
            if overflow == "bytes"
            else b""
            if overflow == "zero"
            else b"x",
        )
        if overflow == "bad_name":
            path.rename(path.with_name("unknown"))
        elif overflow == "owner":
            tree.register(path, 0, 21201)
        elif overflow == "mode":
            path.chmod(0o640)
        elif overflow == "hardlink":
            os.link(path, tree.base / "linked")
    with pytest.raises(c.DeploymentSourceError):
        tree.open()
    assert not tree.live


def test_maximum_inventory_and_protected_roots_fd_bound(reader_tree):
    tree = reader_tree
    roots = tuple(Path(f"/protected/p{n}") for n in range(64))
    for path in roots:
        tree.directory(path, 20102, 20102)
        tree.mount(path, False)
    for _, namespace, _, _, limit, cap in CHANNELS:
        for n in range(1, limit + 1):
            tree.payload(namespace, n, raw=b"x" * cap)
        for n in range(1, 33):
            tree.payload(namespace, n, stage=True)
    with tree.open(protected_roots=roots) as source:
        assert source.read_current() == tree.bundle
        assert len(tree.live) == 111
        assert tree.peak <= 256
        print(
            f"Task37 measured peak FDs={tree.peak}; retained={len(tree.live)}; channel entries=240"
        )
    assert not tree.live


@pytest.mark.parametrize(
    "fault",
    [
        "rw_static",
        "ro_outbox",
        "missing",
        "nested",
        "backing",
        "device",
        "optional_nested",
        "optional_cross",
    ],
)
def test_mount_refusals(reader_tree, fault):
    tree = reader_tree
    if fault == "rw_static":
        tree.mount_lines[0] = tree.mount_lines[0].replace(" ro ", " rw ")
    elif fault == "ro_outbox":
        tree.mount_lines[6] = tree.mount_lines[6].replace(" rw ", " ro ")
    elif fault == "missing":
        tree.mount_lines.pop(0)
    elif fault == "nested":
        tree.mount(STATIC / "documents", True)
    elif fault == "backing":
        tree.mount_lines[1] = tree.mount_lines[1].replace(
            "/volume-101", "/volume-100/child"
        )
    elif fault == "device":
        tree.mount_lines[0] = tree.mount_lines[0].replace(tree.device, "99:99")
    else:
        optional = Path("/run/deeptwin/deployment-outbox")
        tree.mount(optional, False, "/safe")
        if fault == "optional_nested":
            tree.mount(optional / "requests", False, "/volume-100")
        else:
            tree.mount(Path("/run/deeptwin/deployment-receipts"), True, "/safe/child")
    with pytest.raises(c.DeploymentSourceError):
        tree.open()
    assert not tree.live


@pytest.mark.parametrize("change", ["nested", "remove", "replace", "add"])
def test_optional_normalization_is_retained_unrelated_mounts_ignored(
    reader_tree, change
):
    tree = reader_tree
    optional = Path("/run/deeptwin/deployment-outbox")
    tree.mount(optional, False)
    with tree.open() as source:
        tree.mount_lines.reverse()
        tree.mount(Path("/unrelated"), False)
        assert source.read_current() == tree.bundle
        if change == "nested":
            tree.mount(optional / "requests", False)
        elif change == "remove":
            tree.mount_lines[:] = [
                line for line in tree.mount_lines if f" {optional} " not in line
            ]
        elif change == "replace":
            tree.mount_lines[:] = [
                line.replace("/synthetic", "/new-device")
                if f" {optional} " in line
                else line
                for line in tree.mount_lines
            ]
        else:
            tree.mount(Path("/run/deeptwin/deployment-receipts"), True)
        with pytest.raises(c.DeploymentSourceError):
            source.read_current()


@pytest.mark.parametrize(
    "root",
    [
        "provider-stage-sources",
        "provider-deployment-outbox",
        "provider-deployment-receipts",
        "provider-deployment-consumed",
    ],
)
@pytest.mark.parametrize("alias", [False, True])
def test_old_reader_observes_all_provider_optional_roots(actual_sources, root, alias):
    s = actual_sources
    s.mount_lines.append(
        f"90 1 {s.device} {'/vol2' if alias else '/safe'} /run/deeptwin/{root} ro - ext4 /fake rw\n"
    )
    if alias:
        with pytest.raises(c.DeploymentSourceError):
            s.open_exchange()
    else:
        with s.open_exchange() as source:
            source.recheck_current()


class Stop(BaseException):
    pass


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
@pytest.mark.parametrize(
    "checkpoint", ["bundle", "original", "channel", "protected", "guard"]
)
def test_acquisition_interruptions_preserve_primary_and_close_all(
    reader_tree, monkeypatch, kind, checkpoint
):
    tree, module = reader_tree, reader_module()
    primary = kind("primary")
    if checkpoint == "bundle":
        original = module._open_provider_bundle

        def fail(*args, **kw):
            # Root is already owned; bundle's own acquisition cleanup is Task36.
            raise primary

        monkeypatch.setattr(module, "_open_provider_bundle", fail)
    elif checkpoint == "guard":
        monkeypatch.setattr(
            module.ProviderSourceContext,
            "recheck_current",
            lambda self: (_ for _ in ()).throw(primary),
        )
    else:
        original = f.Directory.open.__func__
        target = {
            "original": ORIGINALS[2][0],
            "channel": CHANNELS[2][0],
            "protected": c.BUILTIN_ROOTS[2],
        }[checkpoint]

        def fail(cls, path, **kw):
            if path == target:
                raise primary
            return original(cls, path, **kw)

        monkeypatch.setattr(f.Directory, "open", classmethod(fail))
    with pytest.raises(kind) as caught:
        tree.open()
    assert caught.value is primary
    assert not tree.live


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Stop])
def test_read_interruption_closes_and_secondary_cleanup_cannot_mask(
    reader_tree, monkeypatch, kind
):
    source = reader_tree.open()
    primary = kind("primary")
    closed = f.Directory.close
    calls = []

    def close(directory):
        calls.append(directory.path)
        closed(directory)
        if len(calls) == 1:
            raise Stop("secondary")

    monkeypatch.setattr(f.Directory, "close", close)
    monkeypatch.setattr(source, "_snapshot", lambda: (_ for _ in ()).throw(primary))
    with pytest.raises(kind) as caught:
        source.read_current()
    assert caught.value is primary
    assert len(calls) == 24
    assert not reader_tree.live
    source.close()
    assert len(calls) == 24


def test_close_attempts_all_and_propagates_first(reader_tree, monkeypatch):
    source = reader_tree.open()
    closed = f.Directory.close
    primary = Stop("close")
    calls = []

    def close(directory):
        calls.append(directory.path)
        closed(directory)
        if len(calls) == 1:
            raise primary

    monkeypatch.setattr(f.Directory, "close", close)
    with pytest.raises(Stop) as caught:
        source.close()
    assert caught.value is primary
    assert not reader_tree.live
    source.close()
    assert len(calls) == 24


def test_handle_type_hollow_closed_and_copy_refusals(reader_tree):
    cls = reader_module().ProviderSourceContext
    with pytest.raises(TypeError):
        cls()

    class Child(cls):
        pass

    for hollow in (object.__new__(cls), object.__new__(Child)):
        with pytest.raises(c.DeploymentSourceError):
            hollow.read_current()
    source = reader_tree.open()
    for clone in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError):
            clone(source)
    source.close()
    with pytest.raises(c.DeploymentSourceError):
        source.recheck_current()


def test_import_performs_no_source_or_mount_io(monkeypatch):
    import subprocess
    import sys

    script = """import importlib, sys
from app.deployment import files as f, mounts as m
assert 'app.deployment.provider_sources' not in sys.modules
def forbidden(*args, **kwargs):
    raise AssertionError('import performed source acquisition')
f.Directory.open = forbidden
m.read_mountinfo = forbidden
m.native_platform = forbidden
importlib.import_module('app.deployment.provider_sources')
print('imported')
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert (result.returncode, result.stdout, result.stderr) == (0, "imported\n", "")


def test_new_mapping_single_sample_and_shared_parity(reader_tree, monkeypatch):
    from app.deployment.source_common import _source_mount_observations

    tree = reader_tree
    optional = Path("/run/deeptwin/deployment-outbox")
    tree.mount(optional, False)
    tree.mount(optional / "requests", False)
    with tree.open() as source:
        observed = tuple(
            reversed(m.parse_mountinfo("".join(tree.mount_lines).encode()))
        )
        calls = []
        monkeypatch.setattr(m, "read_mountinfo", lambda: (calls.append(1), observed)[1])
        mapping = source._mounts()
        assert calls == [1]
        checked, extras = _source_mount_observations(
            observed, reader_module()._REQUIRED, tuple(c.BUILTIN_ROOTS)
        )
        assert mapping == (checked, extras)
        assert tuple((root, entry[0]) for root, entry in extras) == (
            (optional, optional),
            (optional, optional / "requests"),
        )


@pytest.mark.parametrize("number", range(18))
def test_each_fixed_bundle_file_cap_is_enforced(reader_tree, number):
    # Literal contract caps; never derive the expected boundary from the reader.
    caps = (
        4096,
        4096,
        65536,
        8192,
        4096,
        4096,
        16384,
        8192,
        8192,
        65536,
        8192,
        8192,
        16384,
        8192,
        8192,
        8192,
        16384,
        8192,
    )
    name = reader_tree.bundle[number][0]
    reader_tree.write(STATIC / "documents" / name, b"x" * (caps[number] + 1), 0, 21201)
    with pytest.raises(c.DeploymentSourceError):
        reader_tree.open()
    assert not reader_tree.live


def test_factory_primary_survives_cleanup_failure(reader_tree, monkeypatch):
    primary, secondary = Stop("primary"), Stop("secondary")
    opened, closed = f.Directory.open.__func__, f.Directory.close
    calls = []

    def open_directory(cls, path, **kw):
        if path == c.BUILTIN_ROOTS[2]:
            raise primary
        return opened(cls, path, **kw)

    def close(directory):
        calls.append(directory.path)
        closed(directory)
        if len(calls) == 1:
            raise secondary

    monkeypatch.setattr(f.Directory, "open", classmethod(open_directory))
    monkeypatch.setattr(f.Directory, "close", close)
    with pytest.raises(Stop) as caught:
        reader_tree.open()
    assert caught.value is primary
    assert len(calls) == 16
    assert not reader_tree.live


def test_close_refusal_attempts_every_independent_handle(reader_tree, monkeypatch):
    source = reader_tree.open()
    selected = source._handles[-1]
    attempts = []
    real_close = f.Directory.close

    def refused(directory):
        attempts.append(directory.path)
        if directory is selected:
            raise Stop("OS refused close")
        return real_close(directory)

    monkeypatch.setattr(f.Directory, "close", refused)
    with pytest.raises(Stop):
        source.close()
    assert len(attempts) == 24
    assert reader_tree.live == {selected.fd}
    source.close()
    assert len(attempts) == 24
    real_close(selected)
    assert not reader_tree.live


def test_channel_change_during_post_snapshot_work_cannot_escape(
    reader_tree, monkeypatch
):
    """A whole check must finish its observations with the complete channel capture."""
    source = reader_tree.open()
    module = reader_module()
    snapshot = module._snapshot_provider_namespace
    sample = m.read_mountinfo
    captures, mutated = [], []

    def capture(*args, **kw):
        value = snapshot(*args, **kw)
        captures.append(value)
        return value

    def mounts():
        if len(captures) == 8:
            reader_tree.payload("cancelled")
            mutated.append(True)
        return sample()

    monkeypatch.setattr(module, "_snapshot_provider_namespace", capture)
    monkeypatch.setattr(m, "read_mountinfo", mounts)
    try:
        try:
            source.read_current()
        except c.DeploymentSourceError:
            assert mutated
        else:
            assert not mutated, "Channel mutation after the closing snapshot escaped"
    finally:
        source.close()
