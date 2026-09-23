"""Real fixed-file measurements; OS ownership/mount facts are simulated."""

import pytest
from app.tests.test_extension_worker_metadata import worker_tree, _tracking
from app.workers import extension_metadata as em
from app.workers.broker import Deadline
from app.tests._provider_worker_fixture import provider_tree


def test_legacy_fd_cleanup_and_deadline_then_poison(worker_tree, monkeypatch):
    live, _ = _tracking(monkeypatch)
    source = em.open_worker_metadata_source()
    assert len(live) == 13
    with pytest.raises(em.WorkerMetadataDeadline):
        source.read_current(deadline=Deadline(0.0001))
    assert not source.closed and len(live) == 13
    worker_tree.worker.chmod(0o755)
    with pytest.raises(em.WorkerMetadataInvalid):
        source.read_current(deadline=Deadline.after_ms(1000))
    assert source.closed and not live


def test_legacy_partial_acquisition_cleanup(worker_tree, monkeypatch):
    live, _ = _tracking(monkeypatch)
    worker_tree.schemas[-1].unlink()
    with pytest.raises(em.WorkerMetadataUnavailable):
        em.open_worker_metadata_source()
    assert not live


def test_legacy_schema_exports_are_byte_identical():
    import json
    from pathlib import Path
    from app.extensions.lineage_schema_exports import exported_schemas

    root = Path(__file__).resolve().parents[2] / "schemas/v1/extensions"
    for name, value in exported_schemas().items():
        assert (root / name).read_bytes() == (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()


def test_provider_real_files_reread_and_replacement_poison(provider_tree, monkeypatch):
    from app.workers import provider_metadata as pm

    live, _ = _tracking(monkeypatch)
    source = pm.open_provider_metadata_source()
    assert len(live) == 13
    result = source.read_current(deadline=Deadline.after_ms(1000))
    assert (
        result.build_identity.as_dict()["worker_profile"] == "claude-text-transform-v1"
    )
    assert len(live) == 13
    path = provider_tree["identity"]
    raw = path.read_bytes()
    path.unlink()
    path.write_bytes(raw)
    path.chmod(0o444)
    with pytest.raises(pm.ProviderMetadataInvalid):
        source.read_current(deadline=Deadline.after_ms(1000))
    assert source.closed and not live


def test_provider_deadline_does_not_poison(provider_tree):
    from app.workers import provider_metadata as pm

    with pm.open_provider_metadata_source() as source:
        with pytest.raises(pm.ProviderMetadataDeadline):
            source.read_current(deadline=Deadline(0.0001))
        assert not source.closed
        assert source.read_current(deadline=Deadline.after_ms(1000)).uid == 22001


def test_legacy_read_sampling_seam_still_observes_every_leaf(worker_tree, monkeypatch):
    original = em._read_bounded
    sampled = []

    def read(fd, cap, deadline):
        sampled.append(fd)
        return original(fd, cap, deadline)

    monkeypatch.setattr(em, "_read_bounded", read)
    with em.open_worker_metadata_source() as source:
        source.read_current(deadline=Deadline.after_ms(1000))
    assert len(sampled) == 10


@pytest.mark.parametrize(
    "mutation",
    [
        "worker_bytes",
        "schema_bytes",
        "identity_bytes",
        "mode",
        "directory_mode",
        "unlink",
        "hardlink",
        "symlink",
        "platform",
        "credentials",
        "owner",
        "mount",
    ],
)
def test_provider_every_drift_poisons_and_releases(
    provider_tree, monkeypatch, mutation
):
    import os
    from app.workers import provider_metadata as pm

    live, _ = _tracking(monkeypatch)
    source = pm.open_provider_metadata_source()
    if mutation in ("worker_bytes", "schema_bytes", "identity_bytes"):
        path = provider_tree[
            {"worker_bytes": "worker", "identity_bytes": "identity"}.get(
                mutation, "schemas"
            )
        ]
        if mutation == "schema_bytes":
            path = path[0]
        mode = path.stat().st_mode & 0o777
        raw = bytearray(path.read_bytes())
        raw[0] ^= 1
        path.chmod(0o644)
        path.write_bytes(raw)
        path.chmod(mode)
    elif mutation == "mode":
        provider_tree["worker"].chmod(0o755)
    elif mutation == "directory_mode":
        (provider_tree["prefix"] / "bin").chmod(0o775)
    elif mutation == "unlink":
        provider_tree["identity"].unlink()
    elif mutation == "hardlink":
        os.link(provider_tree["identity"], provider_tree["root"] / "alias")
    elif mutation == "symlink":
        path = provider_tree["identity"]
        moved = provider_tree["root"] / "moved"
        path.rename(moved)
        path.symlink_to(moved)
    elif mutation == "platform":
        monkeypatch.setattr(pm, "_native_platform", lambda: "linux/arm64")
    elif mutation == "credentials":
        monkeypatch.setattr(pm, "_credentials", lambda: (22001, 22002, 22001, 22001))
    elif mutation == "owner":
        # an owner that truly differs from the tree's actual owner, also when run as root
        actual = provider_tree["worker"].stat()
        monkeypatch.setattr(pm, "_expected_owner", lambda: (actual.st_uid + 1, actual.st_gid + 1))
    elif mutation == "mount":
        monkeypatch.setattr(pm, "_read_mountinfo", lambda: ())
    with pytest.raises(pm.ProviderMetadataError):
        source.read_current(deadline=Deadline.after_ms(1000))
    assert source.closed and not live


def test_provider_partial_acquire_busy_cleanup_and_transient_bound(
    provider_tree, monkeypatch
):
    import os
    from app.workers import provider_metadata as pm

    live, _ = _tracking(monkeypatch)
    peak = [0]
    original = os.read

    def read(fd, size):
        assert size <= 65536
        peak[0] = max(peak[0], len(live))
        return original(fd, size)

    monkeypatch.setattr(os, "read", read)
    with pm.open_provider_metadata_source() as source:
        source._lock.acquire()
        try:
            with pytest.raises(pm.ProviderMetadataBusy):
                source.close()
            with pytest.raises(pm.ProviderMetadataBusy):
                source.read_current(deadline=Deadline.after_ms(1000))
        finally:
            source._lock.release()
        source.read_current(deadline=Deadline.after_ms(1000))
    assert not live and peak[0] == 26
    provider_tree["schemas"][-1].unlink()
    with pytest.raises(pm.ProviderMetadataUnavailable):
        pm.open_provider_metadata_source()
    assert not live


def test_unpatched_provider_factory_fails_closed_on_unsupported_host():
    import platform
    from app.workers import provider_metadata as pm

    if platform.system() == "Linux":
        pytest.skip("Do not access host /opt on Linux")
    with pytest.raises(pm.ProviderMetadataUnsupportedPlatform):
        pm.open_provider_metadata_source()
