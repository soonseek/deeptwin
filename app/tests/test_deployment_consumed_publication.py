import base64
import errno
import hashlib
import os

import pytest

from app.tests.deployment_receipt_source_fixture import (
    actual_consumption_exchange as actual_consumption_exchange,  # noqa: PLC0414
)
from app.tests.deployment_receipt_source_fixture import consumed_marker
from app.tests.deployment_source_fixture import (
    actual_sources as actual_sources,  # noqa: PLC0414
)
from app.tests.deployment_source_fixture import module, profile
from app.tests.test_deployment_publication import syscall_fixture


def _selector(number):
    return base64.urlsafe_b64encode(number.to_bytes(32, "big")).rstrip(b"=").decode()


def test_consumed_publication_returns_actual_durable_observation_and_replays(
    actual_consumption_exchange, monkeypatch
):
    syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    with actual.open() as source:
        first = source.publish_consumed(
            receipt_digest=receipt_digest,
            payload=marker,
        )
        second = source.publish_consumed(
            receipt_digest=receipt_digest,
            payload=marker,
        )
        assert first == second
        assert first.role == "consumed"
        assert first.receipt_digest == receipt_digest
        assert first.payload_sha256 == hashlib.sha256(marker).hexdigest()
        assert first.size_bytes == len(marker)
        observed = source.inspect_consumed()
        assert observed[0].file_identity == first.file_identity
        assert observed[0].payload == marker
    path = actual.consumed_path / (
        base64.urlsafe_b64decode(receipt_digest + "=").hex() + ".json"
    )
    assert path.read_bytes() == marker
    assert tuple(item.name for item in actual.consumed_path.iterdir()) == (path.name,)


def test_consumed_same_byte_replay_at_both_caps_allocates_no_stage(
    actual_consumption_exchange, monkeypatch
):
    syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    markers = []
    for number in range(1, 17):
        receipt_digest = _selector(number)
        marker = consumed_marker(receipt_digest)
        actual.add_final(marker)
        markers.append((receipt_digest, marker))
    for number in range(32):
        actual.add_stage(number)
    before = {item.name for item in actual.consumed_path.iterdir()}
    with actual.open() as source:
        result = source.publish_consumed(
            receipt_digest=markers[0][0], payload=markers[0][1]
        )
        assert result.file_identity == source.inspect_consumed()[0].file_identity
    assert {item.name for item in actual.consumed_path.iterdir()} == before


def test_consumed_existing_different_bytes_never_overwrite(
    actual_consumption_exchange, monkeypatch
):
    syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    before = consumed_marker(receipt_digest)
    after = consumed_marker(receipt_digest, outcome="unknown")
    with actual.open() as source:
        source.publish_consumed(receipt_digest=receipt_digest, payload=before)
        with pytest.raises(actual.c.DeploymentSourceError):
            source.publish_consumed(receipt_digest=receipt_digest, payload=after)
    final = next(actual.consumed_path.glob("*.json"))
    assert final.read_bytes() == before


def test_old_projection_codec_and_publisher_keep_consumed_role_closed(actual_sources):
    publication = module("publication")
    contracts = module("contracts")
    marker = consumed_marker(_selector(1))
    with pytest.raises(contracts.DeploymentSourceError):
        publication.validate_projection(
            role="consumed",
            request_digest=_selector(1),
            payload=marker,
            profile=profile(),
        )
    with (
        actual_sources.open_exchange() as source,
        pytest.raises(contracts.DeploymentSourceError),
    ):
        publication.publish(
            source,
            role="consumed",
            request_digest=_selector(1),
            payload=marker,
        )


def test_consumed_marker_is_validated_before_any_source_or_file_io(
    actual_consumption_exchange, monkeypatch
):
    actual = actual_consumption_exchange
    with actual.open() as source:
        monkeypatch.setattr(
            source,
            "_inspect_inventory",
            lambda: (_ for _ in ()).throw(AssertionError("source I/O was reached")),
        )
        with pytest.raises(actual.c.DeploymentSourceError):
            source.publish_consumed(receipt_digest=_selector(1), payload=b"{}")
    assert list(actual.consumed_path.iterdir()) == []


def test_consumed_short_writes_are_completed_exactly(
    actual_consumption_exchange, monkeypatch
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    original_write = os.write

    def short_write(fd, payload):
        return original_write(fd, payload[:7])

    monkeypatch.setattr(publication.os, "write", short_write)
    with actual.open() as source:
        result = source.publish_consumed(
            receipt_digest=receipt_digest,
            payload=marker,
        )
        assert result.size_bytes == len(marker)
    assert next(actual.consumed_path.glob("*.json")).read_bytes() == marker


@pytest.mark.parametrize(
    "fault", ["zero_write", "chown", "chmod", "file_fsync", "directory_fsync"]
)
def test_consumed_publication_faults_preserve_exact_visible_state_without_success(
    actual_consumption_exchange, monkeypatch, fault
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    with actual.open() as source:
        directory_fd = source._consumed.fd
        if fault == "zero_write":
            monkeypatch.setattr(publication.os, "write", lambda _fd, _raw: 0)
        elif fault == "chown":
            monkeypatch.setattr(
                publication.os,
                "fchown",
                lambda *_args: (_ for _ in ()).throw(OSError("private detail")),
            )
        elif fault == "chmod":
            monkeypatch.setattr(
                publication.os,
                "fchmod",
                lambda *_args: (_ for _ in ()).throw(OSError("private detail")),
            )
        else:
            original_fsync = os.fsync

            def fail_selected_fsync(fd):
                if (fault == "directory_fsync") == (fd == directory_fd):
                    raise OSError("private detail")
                return original_fsync(fd)

            monkeypatch.setattr(publication.os, "fsync", fail_selected_fsync)
        with pytest.raises(actual.c.PublicationUnavailable):
            source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
    finals = list(actual.consumed_path.glob("*.json"))
    stages = list(actual.consumed_path.glob(".stage-*.tmp"))
    if fault == "directory_fsync":
        assert len(finals) == 1 and finals[0].read_bytes() == marker
        assert stages == []
    else:
        assert finals == []
        assert len(stages) == 1


def test_consumed_precommit_source_drift_retains_stage_and_no_final(
    actual_consumption_exchange, monkeypatch
):
    syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    with actual.open() as source:
        original = source.recheck_current

        def drift_then_recheck():
            actual.replace_exchange()
            return original()

        monkeypatch.setattr(source, "recheck_current", drift_then_recheck)
        with pytest.raises(actual.c.DeploymentSourceError):
            source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
    assert list(actual.consumed_path.glob("*.json")) == []
    stages = list(actual.consumed_path.glob(".stage-*.tmp"))
    assert len(stages) == 1 and stages[0].read_bytes() == marker


def test_consumed_named_stage_swap_fails_closed_and_retains_both_objects(
    actual_consumption_exchange, monkeypatch
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    original_stage = publication._stage_payload

    def swapped_stage(directory, payload, *, policy):
        stage = original_stage(directory, payload, policy=policy)
        named = actual.consumed_path / stage.name
        displaced = actual.actual(actual.consumed_root) / "displaced-stage"
        named.rename(displaced)
        named.write_bytes(b"replacement")
        named.chmod(0o440)
        actual.register(named, 20102, 21201)
        return stage

    monkeypatch.setattr(publication, "_stage_payload", swapped_stage)
    with actual.open() as source, pytest.raises(actual.c.DeploymentSourceError):
        source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
    assert list(actual.consumed_path.glob("*.json")) == []
    assert (
        next(actual.consumed_path.glob(".stage-*.tmp")).read_bytes() == b"replacement"
    )
    assert (
        actual.actual(actual.consumed_root) / "displaced-stage"
    ).read_bytes() == marker


@pytest.mark.parametrize("code", [errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP])
def test_consumed_unsupported_no_replace_retains_fully_staged_file(
    actual_consumption_exchange, monkeypatch, code
):
    publication = module("publication")
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    monkeypatch.setattr(
        publication,
        "_rename_noreplace",
        lambda *_args: (_ for _ in ()).throw(OSError(code, "private detail")),
    )
    with actual.open() as source, pytest.raises(actual.c.PublicationUnavailable):
        source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
    assert list(actual.consumed_path.glob("*.json")) == []
    stages = list(actual.consumed_path.glob(".stage-*.tmp"))
    assert len(stages) == 1 and stages[0].read_bytes() == marker


@pytest.mark.parametrize("winner_matches", [True, False])
def test_consumed_eexist_race_retains_stage_and_accepts_only_exact_winner(
    actual_consumption_exchange, monkeypatch, winner_matches
):
    publication = module("publication")
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    winner = (
        marker if winner_matches else consumed_marker(receipt_digest, outcome="unknown")
    )

    def racing_publish(_fd, _stage, final):
        path = actual.consumed_path / final
        path.write_bytes(winner)
        path.chmod(0o440)
        actual.register(path, 20102, 21201)
        raise FileExistsError()

    monkeypatch.setattr(publication, "_rename_noreplace", racing_publish)
    with actual.open() as source:
        if winner_matches:
            result = source.publish_consumed(
                receipt_digest=receipt_digest, payload=marker
            )
            assert result.payload_sha256 == hashlib.sha256(marker).hexdigest()
        else:
            with pytest.raises(actual.c.DeploymentSourceError):
                source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
    assert next(actual.consumed_path.glob("*.json")).read_bytes() == winner
    stages = list(actual.consumed_path.glob(".stage-*.tmp"))
    assert len(stages) == 1 and stages[0].read_bytes() == marker


def test_consumed_postcheck_failure_keeps_visible_final_but_cannot_report_success(
    actual_consumption_exchange, monkeypatch
):
    syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    with actual.open() as source:
        original = source._inspect_inventory
        calls = 0

        def fail_final_check():
            nonlocal calls
            calls += 1
            if calls == 3:
                raise actual.c.DeploymentSourceError()
            return original()

        monkeypatch.setattr(source, "_inspect_inventory", fail_final_check)
        with pytest.raises(actual.c.DeploymentSourceError):
            source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
    assert next(actual.consumed_path.glob("*.json")).read_bytes() == marker
    assert list(actual.consumed_path.glob(".stage-*.tmp")) == []


@pytest.mark.parametrize("success", [True, False])
def test_consumed_publication_closes_every_temporary_descriptor(
    actual_consumption_exchange, monkeypatch, success
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    with actual.open() as source:
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
                source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
        else:
            source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
        assert opened == set()


@pytest.mark.parametrize("finals,stages", [(16, 0), (0, 32)])
def test_consumed_new_publication_denied_at_either_capacity_without_new_stage(
    actual_consumption_exchange, monkeypatch, finals, stages
):
    syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    for number in range(1, finals + 1):
        receipt_digest = _selector(number)
        actual.add_final(consumed_marker(receipt_digest))
    for number in range(stages):
        actual.add_stage(number)
    before = {item.name for item in actual.consumed_path.iterdir()}
    with actual.open() as source, pytest.raises(actual.c.DeploymentSourceError):
        source.publish_consumed(
            receipt_digest=_selector(99), payload=consumed_marker(_selector(99))
        )
    assert {item.name for item in actual.consumed_path.iterdir()} == before


def test_consumed_uses_concrete_source_recheck_immediately_before_commit(
    actual_consumption_exchange, monkeypatch
):
    publication = syscall_fixture(monkeypatch)
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    with actual.open() as source:
        events = []
        original_recheck = source.recheck_current
        original_commit = publication._commit_stage

        def observed_recheck():
            events.append("source-recheck")
            return original_recheck()

        def observed_commit(*args):
            assert events[-1] == "source-recheck"
            events.append("commit")
            return original_commit(*args)

        monkeypatch.setattr(source, "recheck_current", observed_recheck)
        monkeypatch.setattr(publication, "_commit_stage", observed_commit)
        source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
    assert events[:2] == ["source-recheck", "commit"]


@pytest.mark.parametrize("drift", ["k_source", "namespace_membership"])
def test_consumed_exact_replay_rejects_drift_during_final_inventory_read_and_closes_fds(
    actual_consumption_exchange, monkeypatch, drift
):
    actual = actual_consumption_exchange
    receipt_digest = _selector(1)
    marker = consumed_marker(receipt_digest)
    actual.add_final(marker)
    with actual.open() as source:
        original_read = actual.f._FinalFile.read_current
        reads = 0

        def drift_on_final_inventory_last_read(selected):
            nonlocal reads
            reads += 1
            if reads == 4:
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

        monkeypatch.setattr(
            actual.f._FinalFile,
            "read_current",
            drift_on_final_inventory_last_read,
        )
        monkeypatch.setattr(os, "open", track_open)
        monkeypatch.setattr(os, "close", track_close)
        with pytest.raises(actual.c.DeploymentSourceError):
            source.publish_consumed(receipt_digest=receipt_digest, payload=marker)
        assert reads == 4
        assert opened == set()
    final = next(actual.consumed_path.glob("*.json"))
    assert final.read_bytes() == marker
    assert list(actual.consumed_path.glob(".stage-*.tmp")) == []
