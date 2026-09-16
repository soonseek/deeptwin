"""Mixed cancellation-version inventory and no-clobber publication through actual E."""

import base64
import errno
import hashlib
import json
import os
from uuid import UUID

import pytest

from app.deployment.prepare_v2_contracts import cancellation_v2
from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import (
    actual_sources as actual_sources,  # noqa: PLC0414
)
from app.tests.deployment_source_fixture import module, profile
from app.tests.test_deployment_prepare_v2_contracts import accepted_request
from app.tests.test_deployment_publication import cancel, request, syscall_fixture


def _final_path(actual, request_digest):
    name = base64.urlsafe_b64decode(request_digest + "=").hex() + ".json"
    return actual.actual(actual.c.OUTBOX_ROOT / "cancelled") / name


def _different_legacy_cancel():
    value = request()
    value["request_nonce"] = (
        base64.urlsafe_b64encode(b"different legacy request".ljust(32, b"!"))
        .rstrip(b"=")
        .decode()
    )
    value["request_digest"] = (
        base64.urlsafe_b64encode(
            hashlib.sha256(
                canonical_json(
                    {
                        key: item
                        for key, item in value.items()
                        if key != "request_digest"
                    }
                )
            ).digest()
        )
        .rstrip(b"=")
        .decode()
    )
    marker = cancel()
    marker.update(
        {
            "request_id": value["request_id"],
            "request_digest": value["request_digest"],
        }
    )
    return value, marker


def _v2_case(number=1, *, revision=3):
    from app.deployment.prepare_contracts import make_request
    from app.tests.test_deployment_prepare_contracts import matching_bundle

    bundle, topology, slot = matching_bundle()
    accepted = make_request(
        bundle=bundle,
        topology=topology,
        slot=slot,
        profile=profile(),
        request_id=f"{number:08x}-1234-4234-8234-{number:012x}",
        nonce=number.to_bytes(32, "big"),
        actor_ref={
            "kind": "actor",
            "id": "87654321-4321-4321-8321-cba987654321",
            "version": 1,
            "sha256": "b" * 64,
        },
        created_ms=1_700_000_000_000,
        ttl_seconds=60,
    )
    raw = cancellation_v2(accepted, 1_700_000_000_000 + number, profile=profile())
    if revision == 2:
        value = json.loads(raw)
        value["lifecycle_revision"] = 2
        raw = canonical_json(value)
    return accepted, raw


def _add_final(actual, request_digest, payload):
    path = _final_path(actual, request_digest)
    path.write_bytes(payload)
    path.chmod(0o440)
    actual.register(path, 20102, 21201)
    return path


def test_real_exchange_retains_v1_request_and_mixed_cancellations_after_cold_reopen(
    actual_sources, monkeypatch
):
    syscall_fixture(monkeypatch)
    actual = actual_sources
    accepted = accepted_request(profile())
    request_raw = canonical_json(accepted)
    v2_raw = cancellation_v2(accepted, 1_700_000_000_123, profile=profile())

    with actual.open_exchange() as exchange:
        exchange.publish(
            role="request",
            request_digest=accepted["request_digest"],
            payload=request_raw,
        )
        observation = exchange.publish_cancellation_v2(
            request_digest=accepted["request_digest"], payload=v2_raw
        )
        assert observation.role == "cancel"
        assert observation.request_digest == accepted["request_digest"]
        assert observation.payload_sha256 == hashlib.sha256(v2_raw).hexdigest()
        assert observation.size_bytes == len(v2_raw)
        assert _final_path(actual, accepted["request_digest"]).read_bytes() == v2_raw

    legacy_request, legacy = _different_legacy_cancel()
    legacy_raw = canonical_json(legacy)
    with actual.open_exchange() as reopened:
        identity = reopened.recheck_current()
        assert identity == reopened.recheck_current()
        reopened.publish(
            role="request",
            request_digest=legacy_request["request_digest"],
            payload=canonical_json(legacy_request),
        )
        reopened.publish(
            role="cancel",
            request_digest=legacy["request_digest"],
            payload=legacy_raw,
        )
    assert _final_path(actual, legacy["request_digest"]).read_bytes() == legacy_raw


def test_retained_inventory_closes_with_pinned_e_current_after_last_final_read(
    actual_sources, monkeypatch
):
    actual = actual_sources
    accepted, raw = _v2_case()
    _add_final(actual, accepted["request_digest"], raw)
    with actual.open_exchange() as exchange:
        original_read = actual.f._FinalFile.read_current
        replaced = False

        def replace_e_after_retained_read(selected):
            nonlocal replaced
            result = original_read(selected)
            if not replaced:
                replaced = True
                source_path = actual.actual(actual.c.EXCHANGE_ROOT / "exchange.json")
                displaced = actual.base / "displaced-exchange.json"
                source_path.rename(displaced)
                source_path.write_bytes(actual.output.exchange_bytes)
                source_path.chmod(0o440)
                actual.register(source_path, 0, 21201)
            return result

        monkeypatch.setattr(
            actual.f._FinalFile, "read_current", replace_e_after_retained_read
        )
        with pytest.raises(actual.c.DeploymentSourceError):
            exchange.recheck_current()
        assert replaced
        assert os.stat(actual.base / "displaced-exchange.json").st_nlink == 1


def test_v2_projection_wrapper_is_closed_and_old_public_v1_apis_reject_v2(
    actual_sources, monkeypatch
):
    publication = module("publication")
    actual = actual_sources
    accepted, raw = _v2_case()
    projection = publication.validate_cancellation_v2(
        request_digest=accepted["request_digest"], payload=raw, profile=profile()
    )
    assert projection == publication.Projection(
        "cancel",
        accepted["request_digest"],
        hashlib.sha256(raw).hexdigest(),
        len(raw),
    )
    with pytest.raises(
        actual.c.DeploymentSourceError, match="^deployment_source_invalid$"
    ):
        publication.validate_projection(
            role="cancel",
            request_digest=accepted["request_digest"],
            payload=raw,
            profile=profile(),
        )
    syscall_fixture(monkeypatch)
    with actual.open_exchange() as exchange:
        with pytest.raises(actual.c.DeploymentSourceError):
            exchange.publish(
                role="cancel",
                request_digest=accepted["request_digest"],
                payload=raw,
            )
        assert list(actual.actual(actual.c.OUTBOX_ROOT / "cancelled").iterdir()) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", "deployment-cancellation-v3"),
        ("domain", "deeptwin-deployment-cancellation-v1"),
        ("instance_id", "3" * 32),
        ("origin_profile_digest", "A" * 43),
    ],
)
def test_complete_canonical_v2_marker_mutants_deny_projection_and_actual_e(
    actual_sources, field, value
):
    publication = module("publication")
    actual = actual_sources
    accepted, raw = _v2_case()
    marker = json.loads(raw)
    marker[field] = value
    malformed = canonical_json(marker)
    with pytest.raises(
        actual.c.DeploymentSourceError, match="^deployment_source_invalid$"
    ):
        publication.validate_cancellation_v2(
            request_digest=accepted["request_digest"],
            payload=malformed,
            profile=profile(),
        )
    _add_final(actual, accepted["request_digest"], malformed)
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open_exchange()


@pytest.mark.parametrize("change", ["noncanonical", "oversized"])
def test_retained_dispatch_rejects_noncanonical_or_oversized_v2(actual_sources, change):
    actual = actual_sources
    accepted, raw = _v2_case()
    malformed = raw + (b"\n" if change == "noncanonical" else b" " * 4097)
    _add_final(actual, accepted["request_digest"], malformed)
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open_exchange()


@pytest.mark.parametrize("mutation", ["mode", "uid", "link", "wrong_selector", "bytes"])
def test_unsafe_or_wrong_selected_v2_final_denies_actual_e(actual_sources, mutation):
    actual = actual_sources
    accepted, raw = _v2_case()
    path = _add_final(actual, accepted["request_digest"], raw)
    if mutation == "mode":
        path.chmod(0o640)
    elif mutation == "uid":
        actual.register(path, 20103, 21201)
    elif mutation == "link":
        os.link(path, actual.base / "outside-retained-final-link")
    elif mutation == "wrong_selector":
        other, _other_raw = _v2_case(2)
        path.rename(_final_path(actual, other["request_digest"]))
    else:
        path.chmod(0o640)
        path.write_bytes(b"{}")
        path.chmod(0o440)
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open_exchange()


@pytest.mark.parametrize("change", ["profile", "pin"])
def test_changed_startup_profile_or_pin_denies_actual_e(actual_sources, change):
    sources = module("sources")
    actual = actual_sources
    arguments = {
        "profile": profile(instance="3" * 32) if change == "profile" else profile(),
        "recipe_sha256": actual.pins["recipe_sha256"],
        "instance_sha256": actual.pins["instance_sha256"],
        "exchange_sha256": (
            "0" * 64 if change == "pin" else actual.pins["exchange_sha256"]
        ),
        "protected_roots": (),
    }
    with pytest.raises(actual.c.DeploymentSourceError):
        sources.open_exchange_source(**arguments)


@pytest.mark.parametrize(
    "change",
    ["source_missing", "source_replaced", "namespace_missing", "namespace_replaced"],
)
def test_valid_projection_cannot_hide_source_or_namespace_loss_before_stage(
    actual_sources, monkeypatch, change
):
    publication = module("publication")
    syscall_fixture(monkeypatch)
    actual = actual_sources
    accepted, raw = _v2_case()
    projection = publication.validate_cancellation_v2(
        request_digest=accepted["request_digest"], payload=raw, profile=profile()
    )
    assert projection.request_digest == accepted["request_digest"]
    with actual.open_exchange() as exchange:
        if change.startswith("source"):
            path = actual.actual(actual.c.EXCHANGE_ROOT / "exchange.json")
            if change.endswith("missing"):
                path.unlink()
            else:
                path.rename(actual.base / "displaced-source")
                path.write_bytes(actual.output.exchange_bytes)
                path.chmod(0o440)
                actual.register(path, 0, 21201)
        else:
            path = actual.actual(actual.c.OUTBOX_ROOT / "cancelled")
            path.rename(actual.base / "displaced-cancelled")
            if change.endswith("replaced"):
                path.mkdir(mode=0o750)
                actual.register(path, 20102, 21201)
        with pytest.raises(actual.c.DeploymentSourceError):
            exchange.publish_cancellation_v2(
                request_digest=accepted["request_digest"], payload=raw
            )
    active = actual.actual(actual.c.OUTBOX_ROOT / "cancelled")
    assert not active.exists() or list(active.iterdir()) == []


def test_closing_e_invalidates_explicit_v2_publication(actual_sources, monkeypatch):
    syscall_fixture(monkeypatch)
    actual = actual_sources
    accepted, raw = _v2_case()
    exchange = actual.open_exchange()
    exchange.close()
    with pytest.raises(actual.c.DeploymentSourceError):
        exchange.publish_cancellation_v2(
            request_digest=accepted["request_digest"], payload=raw
        )
    assert list(actual.actual(actual.c.OUTBOX_ROOT / "cancelled").iterdir()) == []


def _add_stage(actual, number):
    path = actual.actual(actual.c.OUTBOX_ROOT / "cancelled") / (
        f".stage-{UUID(int=number + 1)}.tmp"
    )
    path.touch(mode=0o600)
    actual.register(path, 20102, 20102)
    return path


@pytest.mark.parametrize("other_finals,stages", [(15, 0), (0, 32)])
def test_exact_v2_replay_fsyncs_at_either_capacity_and_new_publication_fails(
    actual_sources, monkeypatch, other_finals, stages
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_sources
    target, target_raw = _v2_case(1)
    target_path = _add_final(actual, target["request_digest"], target_raw)
    for number in range(2, other_finals + 2):
        accepted, raw = _v2_case(number)
        _add_final(actual, accepted["request_digest"], raw)
    for number in range(stages):
        _add_stage(actual, number)
    before = {path.name for path in target_path.parent.iterdir()}
    with actual.open_exchange() as exchange:
        fsynced = []
        original_fsync = os.fsync

        def observed_fsync(fd):
            fsynced.append(fd)
            return original_fsync(fd)

        monkeypatch.setattr(publication.os, "fsync", observed_fsync)
        replay = exchange.publish_cancellation_v2(
            request_digest=target["request_digest"], payload=target_raw
        )
        repeated = exchange.publish_cancellation_v2(
            request_digest=target["request_digest"], payload=target_raw
        )
        assert repeated == replay
        assert replay.file_identity.inode == os.stat(target_path).st_ino
        assert exchange._namespaces["cancel"].fd in fsynced
        newcomer, newcomer_raw = _v2_case(99)
        with pytest.raises(actual.c.DeploymentSourceError):
            exchange.publish_cancellation_v2(
                request_digest=newcomer["request_digest"], payload=newcomer_raw
            )
    assert {path.name for path in target_path.parent.iterdir()} == before


def test_thirty_third_stage_denies_cold_e_without_cleanup(actual_sources):
    actual = actual_sources
    for number in range(33):
        _add_stage(actual, number)
    before = {
        path.name
        for path in actual.actual(actual.c.OUTBOX_ROOT / "cancelled").iterdir()
    }
    with pytest.raises(actual.c.DeploymentSourceError):
        actual.open_exchange()
    assert {
        path.name
        for path in actual.actual(actual.c.OUTBOX_ROOT / "cancelled").iterdir()
    } == before


def test_existing_v2_different_bytes_never_overwrite(actual_sources, monkeypatch):
    syscall_fixture(monkeypatch)
    actual = actual_sources
    accepted, before = _v2_case()
    changed = json.loads(before)
    changed["cancelled_at"] = "2023-11-14T22:13:21.123Z"
    after = canonical_json(changed)
    with actual.open_exchange() as exchange:
        exchange.publish_cancellation_v2(
            request_digest=accepted["request_digest"], payload=before
        )
        with pytest.raises(actual.c.DeploymentSourceError):
            exchange.publish_cancellation_v2(
                request_digest=accepted["request_digest"], payload=after
            )
    assert _final_path(actual, accepted["request_digest"]).read_bytes() == before


@pytest.mark.parametrize("winner_matches", [True, False])
def test_v2_eexist_race_retains_stage_and_accepts_only_exact_winner(
    actual_sources, monkeypatch, winner_matches
):
    publication = module("publication")
    actual = actual_sources
    accepted, payload = _v2_case()
    changed = json.loads(payload)
    changed["cancelled_at"] = "2023-11-14T22:13:21.123Z"
    winner = payload if winner_matches else canonical_json(changed)

    def racing_publish(_fd, _stage, final):
        path = actual.actual(actual.c.OUTBOX_ROOT / "cancelled") / final
        path.write_bytes(winner)
        path.chmod(0o440)
        actual.register(path, 20102, 21201)
        raise FileExistsError()

    monkeypatch.setattr(publication, "_rename_noreplace", racing_publish)
    with actual.open_exchange() as exchange:
        if winner_matches:
            result = exchange.publish_cancellation_v2(
                request_digest=accepted["request_digest"], payload=payload
            )
            assert result.payload_sha256 == hashlib.sha256(payload).hexdigest()
        else:
            with pytest.raises(actual.c.DeploymentSourceError):
                exchange.publish_cancellation_v2(
                    request_digest=accepted["request_digest"], payload=payload
                )
    assert _final_path(actual, accepted["request_digest"]).read_bytes() == winner
    stages = list(
        actual.actual(actual.c.OUTBOX_ROOT / "cancelled").glob(".stage-*.tmp")
    )
    assert len(stages) == 1 and stages[0].read_bytes() == payload


def test_v2_named_stage_swap_isolated_from_membership_guard(
    actual_sources, monkeypatch
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_sources
    accepted, payload = _v2_case()
    original_stage = publication._stage_payload
    displaced = actual.base / "displaced-stage-outside-relevant-roots"

    def swapped_stage(directory, raw, *, policy):
        stage = original_stage(directory, raw, policy=policy)
        named = actual.actual(actual.c.OUTBOX_ROOT / "cancelled") / stage.name
        named.rename(displaced)
        named.write_bytes(b"replacement")
        named.chmod(0o440)
        actual.register(named, 20102, 21201)
        return stage

    monkeypatch.setattr(publication, "_stage_payload", swapped_stage)
    with (
        actual.open_exchange() as exchange,
        pytest.raises(actual.c.DeploymentSourceError),
    ):
        exchange.publish_cancellation_v2(
            request_digest=accepted["request_digest"], payload=payload
        )
    assert list(actual.actual(actual.c.OUTBOX_ROOT / "cancelled").glob("*.json")) == []
    named = next(actual.actual(actual.c.OUTBOX_ROOT / "cancelled").glob(".stage-*.tmp"))
    assert named.read_bytes() == b"replacement"
    assert displaced.read_bytes() == payload


def test_malformed_v2_is_rejected_before_stage_or_source_io(
    actual_sources, monkeypatch
):
    publication = module("publication")
    actual = actual_sources
    accepted, payload = _v2_case()
    value = json.loads(payload)
    value["domain"] = "deeptwin-deployment-cancellation-v1"
    with actual.open_exchange() as exchange:
        monkeypatch.setattr(
            publication,
            "_stage_payload",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("stage I/O was reached")
            ),
        )
        with pytest.raises(actual.c.DeploymentSourceError):
            exchange.publish_cancellation_v2(
                request_digest=accepted["request_digest"],
                payload=canonical_json(value),
            )
    assert list(actual.actual(actual.c.OUTBOX_ROOT / "cancelled").iterdir()) == []


@pytest.mark.parametrize(
    "fault", ["after_write", "after_fsync_before_rename", "after_visibility"]
)
def test_v2_fault_phases_preserve_honest_visible_state_without_success(
    actual_sources, monkeypatch, fault
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_sources
    accepted, payload = _v2_case()
    with actual.open_exchange() as exchange:
        if fault == "after_write":
            monkeypatch.setattr(
                publication.os,
                "fchown",
                lambda *_args: (_ for _ in ()).throw(OSError("private detail")),
            )
            expected = actual.c.PublicationUnavailable
        elif fault == "after_fsync_before_rename":
            monkeypatch.setattr(
                publication,
                "_commit_stage",
                lambda *_args: (_ for _ in ()).throw(actual.c.DeploymentSourceError()),
            )
            expected = actual.c.DeploymentSourceError
        else:
            original_recheck = exchange.recheck_current
            calls = 0

            def fail_after_visibility():
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise actual.c.DeploymentSourceError()
                return original_recheck()

            monkeypatch.setattr(exchange, "recheck_current", fail_after_visibility)
            expected = actual.c.DeploymentSourceError
        with pytest.raises(expected):
            exchange.publish_cancellation_v2(
                request_digest=accepted["request_digest"], payload=payload
            )
    finals = list(actual.actual(actual.c.OUTBOX_ROOT / "cancelled").glob("*.json"))
    stages = list(
        actual.actual(actual.c.OUTBOX_ROOT / "cancelled").glob(".stage-*.tmp")
    )
    if fault == "after_visibility":
        assert len(finals) == 1 and finals[0].read_bytes() == payload
        assert stages == []
    else:
        assert finals == []
        assert len(stages) == 1 and stages[0].read_bytes() == payload


@pytest.mark.parametrize("code", [errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP])
def test_v2_unsupported_no_replace_retains_fully_staged_file(
    actual_sources, monkeypatch, code
):
    publication = module("publication")
    actual = actual_sources
    accepted, payload = _v2_case()
    monkeypatch.setattr(
        publication,
        "_rename_noreplace",
        lambda *_args: (_ for _ in ()).throw(OSError(code, "private detail")),
    )
    with (
        actual.open_exchange() as exchange,
        pytest.raises(
            actual.c.PublicationUnavailable,
            match="^deployment_publication_unavailable$",
        ),
    ):
        exchange.publish_cancellation_v2(
            request_digest=accepted["request_digest"], payload=payload
        )
    assert list(actual.actual(actual.c.OUTBOX_ROOT / "cancelled").glob("*.json")) == []
    stages = list(
        actual.actual(actual.c.OUTBOX_ROOT / "cancelled").glob(".stage-*.tmp")
    )
    assert len(stages) == 1 and stages[0].read_bytes() == payload


@pytest.mark.parametrize("success", [True, False])
def test_v2_publication_closes_every_operation_descriptor(
    actual_sources, monkeypatch, success
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_sources
    accepted, payload = _v2_case()
    with actual.open_exchange() as exchange:
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
        if not success:
            monkeypatch.setattr(
                publication,
                "_rename_noreplace",
                lambda *_args: (_ for _ in ()).throw(OSError(errno.ENOSYS, "no")),
            )
            with pytest.raises(actual.c.PublicationUnavailable):
                exchange.publish_cancellation_v2(
                    request_digest=accepted["request_digest"], payload=payload
                )
        else:
            exchange.publish_cancellation_v2(
                request_digest=accepted["request_digest"], payload=payload
            )
        assert opened == set()
