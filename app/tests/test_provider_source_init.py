"""Controlled provider initializer evidence, explicitly not native deployment proof."""

import importlib
import os

import pytest

from app.deployment import contracts as c
from app.deployment import files as f
from app.tests.provider_source_init_fixture import CHANNELS, INPUT, TARGETS
from app.tests.provider_source_init_fixture import tree as tree  # noqa: PLC0414


def initializer():
    try:
        return importlib.import_module("app.operations.deployment_provider_source_init")
    except ModuleNotFoundError as error:
        assert error.name == "app.operations.deployment_provider_source_init"
        pytest.fail(
            "valid retained inputs cannot publish the required 18-file package: initializer missing"
        )


def test_first_initialization_and_identical_restart(tree):
    result = initializer().initialize_provider_sources()
    assert result == {
        "context_sha256": c.digest(tree.bundle[16][1]),
        "geometry_sha256": c.digest(tree.bundle[9][1]),
        "provider_recipe_sha256": c.digest(tree.bundle[10][1]),
    }
    docs = tree.actual(TARGETS[0]) / "documents"
    assert {p.name: p.read_bytes() for p in docs.iterdir()} == dict(tree.bundle)
    for path in (docs, *docs.iterdir()):
        info = tree.observed(tree.raw_stat(path))
        assert (info.st_uid, info.st_gid, info.st_mode & 0o7777) == (
            0,
            21201,
            0o750 if path == docs else 0o440,
        )
    assert not tree.live
    before = tree.snapshot()
    tree.effects.clear()
    assert initializer().initialize_provider_sources() == result
    assert tree.snapshot() == before
    assert tree.effects == []
    assert not tree.live
    assert tree.peak <= 256


@pytest.mark.parametrize("existing", [(0,), (1, 2, 3), (0, 1, 2, 3)])
def test_mixed_roots_and_metadata_only_populated_restart(tree, monkeypatch, existing):
    tree.install(existing)
    payloads = []
    for root, name, _ in CHANNELS:
        if TARGETS.index(root) in existing:
            payloads.append(
                tree.payload(name, raw=b'{"signature":"false","hash":"mismatch"}')
            )
            for state in range(3):
                payloads.append(
                    tree.payload(
                        name, number=state + 1, raw=b"", stage=True, state=state
                    )
                )
    before = {
        path: (path.read_bytes(), f.signature(tree.observed(tree.raw_stat(path))))
        for path in payloads
    }
    opening = os.open

    def no_payload_open(path, *a, **kw):
        parent = tree.paths.get(kw.get("dir_fd"))
        if parent is not None and any(
            parent == tree.actual(root) / name for root, name, _ in CHANNELS
        ):
            pytest.fail("initializer opened a channel payload")
        return opening(path, *a, **kw)

    monkeypatch.setattr(os, "open", no_payload_open)
    initializer().initialize_provider_sources()
    assert before == {
        path: (path.read_bytes(), f.signature(tree.observed(tree.raw_stat(path))))
        for path in payloads
    }
    assert all(
        not any(path.is_relative_to(tree.actual(TARGETS[i])) for i in existing)
        for _, path in tree.effects
    )
    assert not tree.live


def test_all_240_channel_entries_and_8192_byte_new_policies(tree):
    tree.install()
    for _, name, _ in CHANNELS:
        maximum = 64 if name == "receipts" else 16
        cap = {
            "requests": 65536,
            "receipts": 16384,
            "cancelled": 8192,
            "consumed": 8192,
        }[name]
        for n in range(1, maximum + 1):
            tree.payload(name, n, b"!" * cap)
        for n in range(1, 33):
            tree.payload(name, n, b"", stage=True, state=n % 3)
    before = tree.snapshot()
    initializer().initialize_provider_sources()
    assert tree.snapshot() == before
    assert tree.effects == []
    assert not tree.live
    assert tree.peak <= 256


@pytest.mark.parametrize("namespace", ["requests", "cancelled", "receipts", "consumed"])
@pytest.mark.parametrize(
    "bad",
    [
        "final_count",
        "stage_count",
        "size",
        "empty",
        "mode",
        "owner",
        "group",
        "name",
        "hardlink",
        "symlink",
    ],
)
def test_unsafe_channels_refused_without_effects(tree, namespace, bad):
    tree.install((1, 2, 3))
    cap = {"requests": 65536, "receipts": 16384, "cancelled": 8192, "consumed": 8192}[
        namespace
    ]
    if bad in ("final_count", "stage_count"):
        maximum = (
            (64 if namespace == "receipts" else 16) if bad == "final_count" else 32
        )
        for n in range(1, maximum + 2):
            tree.payload(namespace, n, stage=bad == "stage_count")
    else:
        path = tree.payload(
            namespace,
            raw=b"" if bad == "empty" else b"x" * (cap + 1) if bad == "size" else b"x",
        )
        if bad == "mode":
            path.chmod(0o600)
        if bad in ("owner", "group"):
            uid = 20113 if namespace == "receipts" else 20102
            tree.register(
                path, 99 if bad == "owner" else uid, 99 if bad == "group" else 21201
            )
        if bad == "name":
            path.rename(path.with_name("unknown"))
        if bad == "hardlink":
            os.link(path, tree.base / "outside")
        if bad == "symlink":
            other = tree.base / "outside"
            path.rename(other)
            path.symlink_to(other)
    with pytest.raises(c.DeploymentSourceError):
        initializer().initialize_provider_sources()
    assert tree.effects == []
    assert not tree.live


def test_shared_cold_read_pin_borrowed_root_and_inode_substitution(tree):
    tree.install((0,))
    from app.deployment._provider_source_files import _open_provider_bundle

    root = f.Directory.open(TARGETS[0], uid=0, gid=21201, mode=0o750)
    baseline = len(tree.live)
    try:
        with pytest.raises(c.DeploymentSourceError):
            _open_provider_bundle(root, context_sha256="0" * 64)
        assert len(tree.live) == baseline
        bundle = _open_provider_bundle(
            root, context_sha256=c.digest(tree.bundle[16][1])
        )
        assert bundle.read_current() == tree.bundle
        identities = bundle._object_identities()
        assert len(identities[1]) == 18
        path = tree.actual(TARGETS[0]) / "documents" / tree.bundle[0][0]
        path.rename(tree.base / "displaced")
        tree.write(TARGETS[0] / "documents" / path.name, tree.bundle[0][1], 0, 21201)
        with pytest.raises(c.DeploymentSourceError):
            bundle.read_current()
        bundle.close()
        assert len(tree.live) == baseline
        root.recheck_current()
    finally:
        root.close()
    assert not tree.live


def test_borrowed_root_closed_refuses_bundle_reads(tree):
    tree.install((0,))
    from app.deployment._provider_source_files import _open_provider_bundle

    root = f.Directory.open(TARGETS[0], uid=0, gid=21201, mode=0o750)
    bundle = _open_provider_bundle(root, context_sha256=c.digest(tree.bundle[16][1]))
    root.close()
    with pytest.raises(c.DeploymentSourceError):
        bundle.read_current()
    bundle.close()
    assert not tree.live


def test_cold_read_rechecks_earlier_leaf_after_later_read(tree, monkeypatch):
    tree.install((0,))
    from app.deployment._provider_source_files import _open_provider_bundle

    root = f.Directory.open(TARGETS[0], uid=0, gid=21201, mode=0o750)
    bundle = _open_provider_bundle(root, context_sha256=c.digest(tree.bundle[16][1]))
    read = f.read_exact
    changed = False

    def mutate(fd, cap):
        nonlocal changed
        raw = read(fd, cap)
        if not changed and tree.paths[fd].name == "source-pins.json":
            path = (
                tree.actual(TARGETS[0]) / "documents" / "original-prepare-recipe.json"
            )
            path.chmod(0o600)
            path.write_bytes(b"x" * len(tree.bundle[0][1]))
            path.chmod(0o440)
            changed = True
        return raw

    monkeypatch.setattr(f, "read_exact", mutate)
    try:
        with pytest.raises(c.DeploymentSourceError):
            bundle.read_current()
        assert changed
    finally:
        bundle.close()
        root.close()


@pytest.mark.parametrize("outcome", ["argv", "nonroot", "native", "success"])
def test_main_fixed_status_and_sanitized_output(tree, monkeypatch, capsys, outcome):
    init = initializer()
    argv, status, message = [], 0, ""
    if outcome == "argv":
        argv, status, message = ["secret-path"], 2, "deployment_source_invalid\n"
    elif outcome == "nonroot":
        monkeypatch.setattr(os, "geteuid", lambda: 42)
        status, message = 1, "deployment_source_unavailable\n"
    elif outcome == "native":

        def unavailable():
            raise c.DeploymentSourceUnavailable()

        monkeypatch.setattr(init.m, "native_platform", unavailable)
        status, message = 1, "deployment_source_unavailable\n"
    assert init.main(argv) == status
    captured = capsys.readouterr()
    assert (captured.out, captured.err) == ("", message)
    if status:
        assert not tree.effects
    assert not tree.live


def test_malformed_fourth_root_prevents_every_effect(tree):
    tree.write(TARGETS[3] / "unexpected", b"occupied", 0, 0)
    before = tree.snapshot()
    with pytest.raises(c.DeploymentSourceError):
        initializer().initialize_provider_sources()
    assert tree.snapshot() == before
    assert tree.effects == []
    assert not tree.live


class Interrupted(BaseException):
    pass


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Interrupted])
@pytest.mark.parametrize(
    "checkpoint,position",
    [
        ("mkdir", 1),
        ("mkdir", 2),
        ("mkdir", 3),
        ("mkdir", 4),
        ("mkdir", 5),
        ("fchown", 1),
        ("fchown", 18),
        ("fchown", 19),
        ("fchown", 20),
        ("fchown", 22),
        ("fchmod", 1),
        ("fchmod", 18),
        ("fchmod", 19),
        ("fchmod", 20),
        ("fchmod", 24),
        ("fsync", 1),
        ("fsync", 18),
        ("fsync", 19),
        ("fsync", 20),
        ("fsync", 25),
        ("write", 1),
        ("write", 18),
        ("rename", 1),
        ("create_open", 1),
        ("create_open", 18),
        ("reopen", 1),
        ("reopen", 4),
    ],
)
def test_publication_interrupts_preserve_primary_and_close_every_owned_fd(
    tree, monkeypatch, checkpoint, position, kind
):
    from app.deployment import publication as p

    init = initializer()
    target, name = {
        "write": (p, "_write_all"),
        "rename": (p, "_rename_noreplace"),
        "create_open": (os, "open"),
        "reopen": (init, "_reopen_owned_root"),
    }.get(checkpoint, (os, checkpoint))
    original = getattr(target, name)
    primary, secondary = kind("primary"), Interrupted("secondary cleanup")
    calls, fired, cleanup_failed = 0, False, False

    def inject(*args, **kwargs):
        nonlocal calls, fired
        relevant = checkpoint != "create_open" or args[1] & os.O_CREAT
        if relevant:
            calls += 1
            if calls == position:
                fired = True
                raise primary
        return original(*args, **kwargs)

    monkeypatch.setattr(target, name, inject)
    close = f.close_fd

    def secondary_close(fd):
        nonlocal cleanup_failed
        close(fd)
        if fired and fd >= 0 and not cleanup_failed:
            cleanup_failed = True
            raise secondary

    monkeypatch.setattr(f, "close_fd", secondary_close)
    with pytest.raises(BaseException) as caught:
        init.initialize_provider_sources()
    assert caught.value is primary
    assert fired and cleanup_failed
    assert not tree.live
    assert tree.peak <= 256


@pytest.mark.parametrize("position", [1, 2, 9, 18])
@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Interrupted])
def test_shared_partial_leaf_acquisition_cleanup_and_borrowed_root(
    tree, monkeypatch, position, kind
):
    tree.install((0,))
    from app.deployment._provider_source_files import _open_provider_bundle

    root = f.Directory.open(TARGETS[0], uid=0, gid=21201, mode=0o750)
    baseline = set(tree.live)
    read, close = f.read_exact, f.close_fd
    primary = kind("primary")
    calls, fired, secondary = 0, False, False

    def interrupt(fd, cap):
        nonlocal calls, fired
        calls += 1
        if calls == position:
            fired = True
            raise primary
        return read(fd, cap)

    def cleanup(fd):
        nonlocal secondary
        close(fd)
        if fired and fd >= 0 and not secondary:
            secondary = True
            raise Interrupted("secondary")

    monkeypatch.setattr(f, "read_exact", interrupt)
    monkeypatch.setattr(f, "close_fd", cleanup)
    try:
        with pytest.raises(BaseException) as caught:
            _open_provider_bundle(root, context_sha256=c.digest(tree.bundle[16][1]))
        assert caught.value is primary
        assert tree.live == baseline
        root.recheck_current()
    finally:
        root.close()


@pytest.mark.parametrize(
    "bad",
    [
        "pins",
        "source",
        "config_name",
        "platform",
        "readonly_ancestor",
        "alias",
        "nested_mount",
        "optional_backing",
        "optional_nested",
    ],
)
def test_protected_inputs_mounts_and_sources_fail_before_effects(
    tree, monkeypatch, bad
):
    init = initializer()
    if bad in ("pins", "source"):
        path = (
            tree.actual(INPUT / "provider-source-pins.json")
            if bad == "pins"
            else tree.actual(tree.originals[0][0] / tree.originals[0][1])
        )
        path.chmod(0o600)
        path.write_bytes(b"not expected")
        path.chmod(0o440)
    elif bad == "config_name":
        tree.actual(INPUT / "provider-source-pins.json").rename(
            tree.actual(INPUT / "renamed")
        )
    elif bad == "platform":
        monkeypatch.setattr(init.m, "native_platform", lambda: "linux/arm64")
    elif bad == "readonly_ancestor":
        tree.mount_lines[0] = tree.mount_lines[0].replace(" ro ", " rw ")
        from app.tests.provider_source_init_fixture import RELEASE

        for i, (relative, _) in enumerate(RELEASE, 300):
            tree.mount_lines.append(
                f"{i} 100 {tree.device} /leaf-{i} {c.RELEASE_ROOT / relative} ro - ext4 /dev/synthetic rw\n"
            )
    elif bad == "alias":
        tree.mount_lines[3] = tree.mount_lines[3].replace("/volume-103", "/volume-102")
    elif bad == "nested_mount":
        tree.mount_lines.append(
            f"300 102 {tree.device} /nested {TARGETS[0] / 'documents'} rw - ext4 /dev/synthetic rw\n"
        )
    elif bad == "optional_backing":
        tree.mount_lines.append(
            f"300 1 {tree.device} /volume-102 {c.OUTBOX_ROOT} rw - ext4 /dev/synthetic rw\n"
        )
    else:
        tree.mount_lines.extend(
            (
                f"300 1 {tree.device} /safe {c.OUTBOX_ROOT} rw - ext4 /dev/synthetic rw\n",
                f"301 300 {tree.device} /volume-102 {c.OUTBOX_ROOT / 'nested'} rw - ext4 /dev/synthetic rw\n",
            )
        )
    before = tree.snapshot()
    with pytest.raises(c.DeploymentSourceError):
        init.initialize_provider_sources()
    assert not tree.effects
    assert tree.snapshot() == before
    assert not tree.live


@pytest.mark.parametrize(
    "mutation", ["same_count_stage", "source_replace", "input_parent", "mount"]
)
def test_external_mutation_after_static_stage_is_never_rebased(
    tree, monkeypatch, mutation
):
    init = initializer()
    tree.install((1, 2, 3))
    stage_path = tree.payload("receipts", stage=True, raw=b"first")
    stage = init._stage_bundle
    changed = False

    def alter(*args):
        nonlocal changed
        result = stage(*args)
        if mutation == "same_count_stage":
            stage_path.write_bytes(b"other")
        elif mutation == "source_replace":
            root, name, gid, raw = tree.originals[0]
            tree.actual(root / name).rename(tree.base / "old-source")
            tree.write(root / name, raw, 0, gid)
        elif mutation == "input_parent":
            tree.actual(INPUT).rename(tree.base / "old-input")
            tree.setup_mkdir(tree.actual(INPUT), 0o750)
            tree.register(tree.actual(INPUT), 0, 0)
        else:
            tree.mount_lines.append(
                f"300 1 {tree.device} /safe {c.OUTBOX_ROOT} rw - ext4 /dev/synthetic rw\n"
            )
        changed = True
        return result

    monkeypatch.setattr(init, "_stage_bundle", alter)
    with pytest.raises(c.DeploymentSourceError):
        init.initialize_provider_sources()
    assert changed
    assert not (tree.actual(TARGETS[0]) / "documents").exists()
    assert any(
        path.name.startswith(".stage-") for path in tree.actual(TARGETS[0]).iterdir()
    )
    assert not tree.live


@pytest.mark.parametrize("replace", ["directory", "leaf"])
def test_staged_to_final_substituted_identity_refused_even_for_equal_bytes(
    tree, monkeypatch, replace
):
    init = initializer()
    commit = init._commit_bundle

    def substituted(publication):
        commit(publication)
        docs = tree.actual(TARGETS[0]) / "documents"
        if replace == "directory":
            docs.rename(tree.base / "old-docs")
            tree.setup_mkdir(docs, 0o750)
            tree.register(docs, 0, 21201)
            for name, raw in tree.bundle:
                tree.write(TARGETS[0] / "documents" / name, raw, 0, 21201)
        else:
            name, raw = tree.bundle[0]
            (docs / name).rename(tree.base / "old-leaf")
            tree.write(TARGETS[0] / "documents" / name, raw, 0, 21201)

    monkeypatch.setattr(init, "_commit_bundle", substituted)
    with pytest.raises(c.DeploymentSourceError):
        init.initialize_provider_sources()
    assert not tree.live
    assert not tree.actual(TARGETS[1] / "cancelled").exists()


def test_short_writes_and_static_failure_retry_preserve_partial_state(
    tree, monkeypatch
):
    from app.deployment import publication as p

    write = os.write
    monkeypatch.setattr(os, "write", lambda fd, raw: write(fd, raw[:7]))

    def fail(*_):
        raise c.DeploymentSourceUnavailable()

    monkeypatch.setattr(p, "_rename_noreplace", fail)
    with pytest.raises(c.DeploymentSourceUnavailable):
        initializer().initialize_provider_sources()
    before = tree.snapshot()
    assert len(tuple(tree.actual(TARGETS[0]).iterdir())) == 1
    tree.effects.clear()
    with pytest.raises(c.DeploymentSourceError):
        initializer().initialize_provider_sources()
    assert tree.snapshot() == before
    assert not tree.effects
    assert not tree.live


def test_measured_fd_overlap_includes_both_complete_bundles(tree, monkeypatch):
    init = initializer()
    observe = init._open_provider_bundle
    overlaps = []

    def observe_overlap(*args, **kw):
        before = sum(
            any(part.startswith(".stage-") for part in path.parts)
            for path in tree.paths.values()
        )
        result = observe(*args, **kw)
        after = sum("documents" in path.parts for path in tree.paths.values())
        overlaps.append((before, after, len(tree.live)))
        return result

    monkeypatch.setattr(init, "_open_provider_bundle", observe_overlap)
    init.initialize_provider_sources()
    assert len(overlaps) == 1
    assert overlaps[0][0] == overlaps[0][1] == 19
    assert tree.peak <= 256
    assert not tree.live
    print(
        f"measured peakFD={tree.peak}; staged/final overlap={overlaps[0]}; remainingFD=0"
    )


@pytest.mark.parametrize("kind", [KeyboardInterrupt, SystemExit, Interrupted])
@pytest.mark.parametrize(
    "point,position",
    [
        ("config", 1),
        ("config", 6),
        ("release", 1),
        ("release", 5),
        ("original", 1),
        ("original", 5),
        ("readback", 1),
        ("readback", 18),
        ("stage_directory", 1),
    ],
)
def test_input_original_and_staged_readback_acquisition_interrupts(
    tree, monkeypatch, kind, point, position
):
    init = initializer()
    from app.deployment import public_init_files as pf

    target, name = {
        "config": (pf._PublicInputFile, "_read_current"),
        "release": (pf._ReleaseInput, "read_current"),
        "original": (f.SourceFile, "read_current"),
        "readback": (f, "read_exact"),
        "stage_directory": (os, "fchown"),
    }[point]
    original, close = getattr(target, name), f.close_fd
    primary = kind("primary")
    calls, fired, secondary = 0, False, False

    def interrupt(*args, **kw):
        nonlocal calls, fired
        relevant = True
        if point == "readback":
            relevant = any(
                part.startswith(".stage-") for part in tree.paths[args[0]].parts
            )
        elif point == "stage_directory":
            relevant = tree.paths[args[0]].name.startswith(".stage-")
        if relevant:
            calls += 1
            if calls == position:
                fired = True
                raise primary
        return original(*args, **kw)

    def cleanup(fd):
        nonlocal secondary
        close(fd)
        if fired and fd >= 0 and not secondary:
            secondary = True
            raise Interrupted("secondary")

    monkeypatch.setattr(target, name, interrupt)
    monkeypatch.setattr(f, "close_fd", cleanup)
    with pytest.raises(BaseException) as caught:
        init.initialize_provider_sources()
    assert caught.value is primary
    assert fired and secondary
    assert not tree.live
    assert tree.peak <= 256


@pytest.mark.parametrize("namespace", ["requests", "cancelled", "receipts", "consumed"])
def test_stage_cap_plus_one_and_snapshot_same_count_change(
    tree, monkeypatch, namespace
):
    tree.install((1, 2, 3))
    cap = {"requests": 65536, "receipts": 16384, "cancelled": 8192, "consumed": 8192}[
        namespace
    ]
    stage = tree.payload(namespace, raw=b"x" * (cap + 1), stage=True)
    with pytest.raises(c.DeploymentSourceError):
        initializer().initialize_provider_sources()
    assert not tree.effects
    stage.write_bytes(b"old")
    from app.deployment._provider_source_files import _snapshot_provider_namespace

    root, _, uid = next(row for row in CHANNELS if row[1] == namespace)
    scan = f._scan_namespace

    def changed(*args, **kwargs):
        result = scan(*args, **kwargs)
        stage.write_bytes(b"new")
        return result

    monkeypatch.setattr(f, "_scan_namespace", changed)
    directory = f.Directory.open(root / namespace, uid=uid, gid=21201, mode=0o750)
    try:
        with pytest.raises(c.DeploymentSourceError):
            _snapshot_provider_namespace(directory, namespace=namespace)
        directory.recheck_current()
    finally:
        directory.close()
    assert not tree.live


def test_fresh_import_has_no_runtime_source_or_native_effect(monkeypatch):
    init = initializer()

    def forbidden(*_a, **_kw):
        pytest.fail("import attempted runtime input/native effect")

    monkeypatch.setattr(f.Directory, "open", forbidden)
    monkeypatch.setattr(init.m, "native_platform", forbidden)
    monkeypatch.setattr(os, "geteuid", forbidden)
    importlib.reload(init)


def test_valid_alternate_bundle_cannot_supply_its_own_initializer_pin(tree):
    from app.tests.provider_source_fixture import case

    _alternate_kwargs, alternate, _ = case(portable=True)
    from app.deployment.provider_source_contracts import validate_provider_source_bundle

    validate_provider_source_bundle(alternate)
    assert alternate != tree.bundle
    tree.install((0,))
    for name, raw in alternate:
        path = tree.actual(TARGETS[0]) / "documents" / name
        path.chmod(0o600)
        path.write_bytes(raw)
        path.chmod(0o440)
    from app.deployment._provider_source_files import _open_provider_bundle

    root = f.Directory.open(TARGETS[0], uid=0, gid=21201, mode=0o750)
    try:
        observed = _open_provider_bundle(
            root, context_sha256=c.digest(alternate[16][1])
        )
        assert observed.read_current() == alternate
        observed.close()
    finally:
        root.close()
    with pytest.raises(c.DeploymentSourceError):
        initializer().initialize_provider_sources()
    assert not tree.effects
    assert not tree.live


@pytest.mark.parametrize("staged", [False, True])
def test_bundle_cleanup_alone_attempts_all_children_and_never_borrowed_root(
    tree, monkeypatch, staged
):
    from app.deployment._provider_source_files import _open_provider_bundle
    from app.operations._provider_source_init_files import _stage_bundle

    if not staged:
        tree.install((0,))
    root = f.Directory.open(TARGETS[0])
    bundle = (
        _stage_bundle(root, tree.bundle)
        if staged
        else _open_provider_bundle(root, context_sha256=c.digest(tree.bundle[16][1]))
    )
    closer, attempts, primary = f.close_fd, [], Interrupted("cleanup only")
    owned = set(tree.live) - {root.fd}

    def close(fd):
        if fd >= 0:
            attempts.append(fd)
        closer(fd)
        if len(attempts) == 1:
            raise primary

    monkeypatch.setattr(f, "close_fd", close)
    try:
        with pytest.raises(BaseException) as caught:
            bundle.close()
        assert caught.value is primary
        assert set(attempts) == owned
        assert len(attempts) == len(owned) == 19
        bundle.close()
        assert len(attempts) == 19
        assert tree.live == {root.fd}
        root.recheck_current()
    finally:
        monkeypatch.setattr(f, "close_fd", closer)
        root.close()


def test_new_namespace_does_not_adopt_an_unexplained_external_payload(
    tree, monkeypatch
):
    init = initializer()
    install = init.pf._install_namespaces_retained
    inserted = False

    def contaminated(directory, **kwargs):
        nonlocal inserted
        result = install(directory, **kwargs)
        if not inserted:
            tree.payload("requests", raw=b"metadata safe but external")
            inserted = True
        return result

    monkeypatch.setattr(init.pf, "_install_namespaces_retained", contaminated)
    with pytest.raises(c.DeploymentSourceError):
        init.initialize_provider_sources()
    assert inserted
    assert not tree.actual(TARGETS[2] / "receipts").exists()
    assert not tree.live
