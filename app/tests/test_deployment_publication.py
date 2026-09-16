import base64
import errno
import hashlib
import os

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import (
    actual_sources as actual_sources,  # noqa: PLC0414
)
from app.tests.deployment_source_fixture import module, profile


def b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def request():
    value = {
        "schema": "deployment-request-v1",
        "domain": "deeptwin-deployment-request-v1",
        "request_id": "33333333-3333-4333-8333-333333333333",
        "kind": "extension_stage",
        "request_nonce": b64(b"n" * 32),
        "instance_id": profile().instance_id,
        "origin_profile_digest": b64(bytes.fromhex(profile().digest)),
        "effect_payload": {"opaque_task10_semantics": True},
        "preconditions": {},
        "created_by": {
            "kind": "actor",
            "id": "44444444-4444-4444-8444-444444444444",
            "version": 1,
            "sha256": "a" * 64,
        },
        "created_at": "2026-09-15T00:00:00.000Z",
        "expires_at": "2026-09-15T01:00:00.000Z",
    }
    value["request_digest"] = b64(hashlib.sha256(canonical_json(value)).digest())
    return value


def cancel():
    r = request()
    return {
        "schema": "deployment-cancellation-v1",
        "domain": "deeptwin-deployment-cancellation-v1",
        "request_id": r["request_id"],
        "request_digest": r["request_digest"],
        "instance_id": r["instance_id"],
        "origin_profile_digest": r["origin_profile_digest"],
        "lifecycle_revision": 2,
        "cancelled_at": "2026-09-15T00:01:00.000Z",
    }


def syscall_fixture(monkeypatch):
    p = module("publication")

    def rename(fd, stage, final):
        # Test-only no-clobber syscall substitute, not Linux qualification.
        os.link(stage, final, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        os.unlink(stage, dir_fd=fd)

    monkeypatch.setattr(p, "_rename_noreplace", rename)
    return p


@pytest.mark.parametrize("role,builder", [("request", request), ("cancel", cancel)])
def test_projection_codec_closed_binding_and_hash(role, builder):
    p = module("publication")
    value = builder()
    raw = canonical_json(value)
    projection = p.validate_projection(
        role=role,
        request_digest=value["request_digest"],
        payload=raw,
        profile=profile(),
    )
    assert projection.payload_sha256 == hashlib.sha256(raw).hexdigest()
    assert projection.request_digest == value["request_digest"]
    assert projection.size_bytes == len(raw)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "00000000-0000-0000-0000-000000000000"),
        ("request_nonce", "a" * 43),
        ("origin_profile_digest", "a" * 64),
        ("instance_id", "3" * 32),
        ("preconditions", {"x": 1}),
        ("kind", "execute"),
        ("created_at", "2026-02-30T00:00:00.000Z"),
        ("expires_at", "2026-09-15T00:00:00.000Z"),
        ("created_at", "2026-09-15T00:00:00Z"),
        ("extra", True),
        ("effect_payload", []),
        ("request_digest", b64(b"x" * 32)),
    ],
)
def test_invalid_common_request_denied(field, value):
    p, c = module("publication"), module("contracts")
    data = request()
    data[field] = value
    if field != "request_digest":
        data["request_digest"] = b64(
            hashlib.sha256(
                canonical_json({k: v for k, v in data.items() if k != "request_digest"})
            ).digest()
        )
    with pytest.raises(c.DeploymentSourceError):
        p.validate_projection(
            role="request",
            request_digest=data["request_digest"],
            payload=canonical_json(data),
            profile=profile(),
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("lifecycle_revision", True),
        ("lifecycle_revision", 3),
        ("cancelled_at", "2026-09-15T00:00:00+00:00"),
        ("nonce", "extra"),
    ],
)
def test_cancel_marker_exactness(field, value):
    p, c = module("publication"), module("contracts")
    data = cancel()
    data[field] = value
    with pytest.raises(c.DeploymentSourceError):
        p.validate_projection(
            role="cancel",
            request_digest=data["request_digest"],
            payload=canonical_json(data),
            profile=profile(),
        )


@pytest.mark.parametrize("role,builder", [("request", request), ("cancel", cancel)])
def test_real_publication_and_same_byte_replay(
    actual_sources, monkeypatch, role, builder
):
    syscall_fixture(monkeypatch)
    s, data = actual_sources, builder()
    raw = canonical_json(data)
    with s.open_exchange() as source:
        first = source.publish(
            role=role, request_digest=data["request_digest"], payload=raw
        )
        second = source.publish(
            role=role, request_digest=data["request_digest"], payload=raw
        )
        assert first == second
        directory = "requests" if role == "request" else "cancelled"
        path = s.actual(s.c.OUTBOX_ROOT / directory) / (
            base64.urlsafe_b64decode(data["request_digest"] + "=").hex() + ".json"
        )
        assert path.read_bytes() == raw
        assert first.file_identity.mode == 0o440
        assert first.file_identity.gid == 21201
        assert len(list(path.parent.iterdir())) == 1


def test_cancel_publication_with_missing_topology(actual_sources, monkeypatch):
    syscall_fixture(monkeypatch)
    s, data = actual_sources, cancel()
    s.actual(s.c.TOPOLOGY_ROOT / "topology.json").unlink()
    with s.open_exchange() as source:
        assert (
            source.publish(
                role="cancel",
                request_digest=data["request_digest"],
                payload=canonical_json(data),
            ).role
            == "cancel"
        )


def test_existing_different_cancel_bytes_never_overwritten(actual_sources, monkeypatch):
    syscall_fixture(monkeypatch)
    s, data = actual_sources, cancel()
    before = canonical_json(data)
    with s.open_exchange() as source:
        source.publish(
            role="cancel", request_digest=data["request_digest"], payload=before
        )
        data["cancelled_at"] = "2026-09-15T00:02:00.000Z"
        with pytest.raises(s.c.DeploymentSourceError):
            source.publish(
                role="cancel",
                request_digest=data["request_digest"],
                payload=canonical_json(data),
            )
        path = next(s.actual(s.c.OUTBOX_ROOT / "cancelled").iterdir())
        assert path.read_bytes() == before


@pytest.mark.parametrize("code", [errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP])
def test_no_replace_unavailability_leaves_only_stage(actual_sources, monkeypatch, code):
    p = module("publication")
    s, data = actual_sources, request()

    def unavailable(*args):
        raise OSError(code, "private host detail")

    monkeypatch.setattr(p, "_rename_noreplace", unavailable)
    with (
        s.open_exchange() as source,
        pytest.raises(
            s.c.PublicationUnavailable, match="^deployment_publication_unavailable$"
        ),
    ):
        source.publish(
            role="request",
            request_digest=data["request_digest"],
            payload=canonical_json(data),
        )
    entries = list(s.actual(s.c.OUTBOX_ROOT / "requests").iterdir())
    assert len(entries) == 1 and entries[0].name.startswith(".stage-")


def test_directory_fsync_failure_is_not_durable_success(actual_sources, monkeypatch):
    syscall_fixture(monkeypatch)
    s, data = actual_sources, request()
    original = os.fsync
    with s.open_exchange() as source:
        directory_fd = source._namespaces["request"].fd

        def fail_directory(fd):
            if fd == directory_fd:
                raise OSError("private detail")
            original(fd)

        monkeypatch.setattr(os, "fsync", fail_directory)
        with pytest.raises(s.c.PublicationUnavailable):
            source.publish(
                role="request",
                request_digest=data["request_digest"],
                payload=canonical_json(data),
            )
        monkeypatch.setattr(os, "fsync", original)
        assert (
            source.publish(
                role="request",
                request_digest=data["request_digest"],
                payload=canonical_json(data),
            ).size_bytes
            > 0
        )


@pytest.mark.parametrize("stage_count", [32, 33])
def test_stage_capacity_never_overflows(actual_sources, monkeypatch, stage_count):
    from uuid import UUID

    syscall_fixture(monkeypatch)
    s, data = actual_sources, request()
    for index in range(1, stage_count + 1):
        path = s.actual(s.c.OUTBOX_ROOT / "requests") / f".stage-{UUID(int=index)}.tmp"
        path.touch(mode=0o600)
        s.register(path, 20102, 20102)
    with pytest.raises(s.c.DeploymentSourceError), s.open_exchange() as source:
        source.publish(
            role="request",
            request_digest=data["request_digest"],
            payload=canonical_json(data),
        )
    assert len(list(s.actual(s.c.OUTBOX_ROOT / "requests").iterdir())) == stage_count


def test_final_capacity_allows_replay_but_not_seventeenth(actual_sources, monkeypatch):
    syscall_fixture(monkeypatch)
    s = actual_sources
    with s.open_exchange() as source:
        values = []
        for index in range(17):
            data = request()
            data["request_nonce"] = b64(bytes([index]) * 32)
            data["request_digest"] = b64(
                hashlib.sha256(
                    canonical_json(
                        {k: v for k, v in data.items() if k != "request_digest"}
                    )
                ).digest()
            )
            values.append(data)
        for data in values[:16]:
            source.publish(
                role="request",
                request_digest=data["request_digest"],
                payload=canonical_json(data),
            )
        source.publish(
            role="request",
            request_digest=values[0]["request_digest"],
            payload=canonical_json(values[0]),
        )
        with pytest.raises(s.c.DeploymentSourceError):
            source.publish(
                role="request",
                request_digest=values[16]["request_digest"],
                payload=canonical_json(values[16]),
            )
    assert len(list(s.actual(s.c.OUTBOX_ROOT / "requests").iterdir())) == 16


def test_exclusive_stage_creation_preserves_existing_stage(actual_sources, monkeypatch):
    p = syscall_fixture(monkeypatch)
    s, data = actual_sources, request()
    identity = "33333333-3333-4333-8333-333333333333"
    path = s.actual(s.c.OUTBOX_ROOT / "requests") / f".stage-{identity}.tmp"
    path.write_bytes(b"keep")
    path.chmod(0o600)
    s.register(path, 20102, 20102)
    monkeypatch.setattr(p, "uuid4", lambda: identity)
    with s.open_exchange() as source, pytest.raises(s.c.PublicationUnavailable):
        source.publish(
            role="request",
            request_digest=data["request_digest"],
            payload=canonical_json(data),
        )
    assert path.read_bytes() == b"keep"


def test_eexist_race_validates_existing_file_and_retains_stage(
    actual_sources, monkeypatch
):
    p = module("publication")
    s, data = actual_sources, request()

    def racing_publish(fd, stage, final):
        path = s.actual(s.c.OUTBOX_ROOT / "requests") / final
        path.write_bytes(canonical_json(data))
        path.chmod(0o440)
        s.register(path, 20102, 21201)
        raise FileExistsError()

    monkeypatch.setattr(p, "_rename_noreplace", racing_publish)
    with s.open_exchange() as source:
        assert (
            source.publish(
                role="request",
                request_digest=data["request_digest"],
                payload=canonical_json(data),
            ).size_bytes
            > 0
        )
    assert len(list(s.actual(s.c.OUTBOX_ROOT / "requests").iterdir())) == 2


def test_actual_fixed_libc_missing_symbol_fails_unavailable(monkeypatch):
    p, c = module("publication"), module("contracts")
    monkeypatch.setattr(p.m, "native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(p.ctypes, "CDLL", lambda *args, **kwargs: object())
    with pytest.raises(c.PublicationUnavailable):
        p._rename_noreplace(123, ".stage-x", "x.json")


def test_held_e_survives_t_mount_loss_for_cancellation(actual_sources, monkeypatch):
    syscall_fixture(monkeypatch)
    s, data = actual_sources, cancel()
    with s.open_exchange() as source:
        before = source.recheck_current()
        s.mount_lines = [
            line for line in s.mount_lines if str(s.c.TOPOLOGY_ROOT) not in line
        ]
        s.actual(s.c.TOPOLOGY_ROOT).rename(
            s.actual(s.c.TOPOLOGY_ROOT).with_name("gone")
        )
        assert source.recheck_current() == before
        assert (
            source.publish(
                role="cancel",
                request_digest=data["request_digest"],
                payload=canonical_json(data),
            ).role
            == "cancel"
        )
