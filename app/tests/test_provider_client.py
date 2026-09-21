from base64 import b64decode, b64encode
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.refs import canonical_json, parse_canonical
from app.domain.store import _writer
from app.extensions.provider_conformance_contracts import (
    ConformanceCapture,
    ConformanceError,
    parse_capture,
)
from app.extensions.provider_conformance_vectors import SUITE_SHA256, fixed_vectors
from app.tests.provider_conformance_fixture import (
    _provider_conformance_worker,
    staged_conformance_app,
)
from app.workers import provider_client
from app.workers.broker import Deadline
from app.workers.provider_client import compare_capture, run_fixed_suite


def _frame_bytes(frame):
    return b"".join(b64decode(part) for part in frame["payload_chunks"])


def test_fixed_suite_uses_six_actual_authenticated_connections_and_literal_comparison(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        guard_calls = []
        with _provider_conformance_worker(staged.actual, monkeypatch) as (_, worker):
            capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000),
                                      guard=lambda: guard_calls.append(None))
        assert type(capture) is ConformanceCapture
        value = parse_canonical(capture.content_bytes)
        assert [attempt["role"] for attempt in value["attempts"]] == [
            "identify-before", "text-basic-v1", "text-refusal-v1",
            "catalog-two-pages-v1", "catalog-negative-capability-v1", "identify-after"]
        assert all(attempt["failure"] is None for attempt in value["attempts"])
        assert worker.completion_count == 6
        assert len(guard_calls) == 48
        assert value["suite_sha256"] == SUITE_SHA256
        comparison = compare_capture(subject, capture)
        assert comparison.completion == "matched" and comparison.reason == "compared"
        assert comparison.covered_subchecks == (
            "text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
            "catalog-negative-capability-v1")
        value["attempts"][0]["connection"]["peer_uid"] = (
            value["attempts"][0]["connection"]["peer_uid"] + 1) % (2**32)
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(value)))

        forged = parse_canonical(capture.content_bytes)
        vector_attempt = forged["attempts"][1]
        removed = vector_attempt["frames"].pop(0)
        assert removed["direction"] == "sent"
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(forged)))

        stopped = parse_canonical(capture.content_bytes)
        stopped["attempts"][0]["failure"] = "deadline"
        with pytest.raises(Exception):
            parse_capture(canonical_json(stopped))

        empty_stop = parse_canonical(capture.content_bytes)
        empty_stop["attempts"] = empty_stop["attempts"][:2]
        empty_stop["attempts"][1]["frames"] = []
        empty_stop["attempts"][1]["failure"] = "protocol_error"
        empty_comparison = compare_capture(subject, parse_capture(canonical_json(empty_stop)))
        assert empty_comparison.completion == "incomplete"
        assert empty_comparison.reason == "protocol_error"

        boundary = parse_canonical(capture.content_bytes)
        boundary["attempts"][-1]["failure"] = "connection_unavailable"
        boundary_comparison = compare_capture(subject, parse_capture(canonical_json(boundary)))
        assert boundary_comparison.completion == "incomplete"
        assert boundary_comparison.covered_subchecks == tuple(
            vector["role"] for vector in boundary["attempts"][1:5])

        repeated = parse_canonical(capture.content_bytes)
        first = parse_canonical(b64decode(
            repeated["attempts"][0]["frames"][0]["payload_chunks"][0]))["challenge"]
        for frame in repeated["attempts"][-1]["frames"]:
            control = parse_canonical(b64decode(frame["payload_chunks"][0]))
            control["challenge"] = first
            frame["payload_chunks"] = [b64encode(canonical_json(control)).decode("ascii")]
        repeated["attempts"][-1]["failure"] = "protocol_error"
        repeated_comparison = compare_capture(subject, parse_capture(canonical_json(repeated)))
        assert repeated_comparison.completion == "mismatch"
        assert repeated_comparison.reason == "identity_mismatch"

        duplicate_batch = parse_canonical(capture.content_bytes)
        vector_frames = duplicate_batch["attempts"][1]["frames"]
        start = provider_client.provider_messages.parse_control(_frame_bytes(vector_frames[0]))
        plan_batch = start["plan"]["batch_id"]
        projection_frame = next(frame for frame in vector_frames
            if frame["direction"] == "received" and frame["message_type"] == provider_client.RESULT
            and provider_client.provider_messages.parse_control(_frame_bytes(frame)).get("schema") ==
                "provider-transform-projection-v1")
        projection = provider_client.provider_messages.parse_control(_frame_bytes(projection_frame))
        old_batch = projection["body"]["batch_id"]
        projection["body"]["batch_id"] = plan_batch
        projection_frame["payload_chunks"] = provider_client._payload_chunks(
            provider_client.provider_messages.encode_control(projection))
        for frame in vector_frames:
            if (frame["message_type"] == provider_client.ARTIFACT
                    and frame["correlation_id"] == projection_frame["message_id"]):
                message = parse_canonical(_frame_bytes(frame))
                if message.get("batch_id") == old_batch:
                    message["batch_id"] = plan_batch
                    frame["payload_chunks"] = provider_client._payload_chunks(canonical_json(message))
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(duplicate_batch)))

        def control(frame):
            return provider_client.provider_messages.parse_control(_frame_bytes(frame))

        wrong_identity = parse_canonical(capture.content_bytes)
        identity_frame = next(frame for frame in wrong_identity["attempts"][0]["frames"]
                              if frame["direction"] == "received")
        identity = control(identity_frame)
        identity["service_identity"] = "wrong-service"
        identity_frame["payload_chunks"] = provider_client._payload_chunks(
            provider_client.provider_messages.encode_control(identity))
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(wrong_identity)))

        wrong_ready = parse_canonical(capture.content_bytes)
        ready_frame = next(frame for frame in wrong_ready["attempts"][1]["frames"]
            if frame["direction"] == "received"
            and frame["message_type"] == provider_client.RESULT
            and control(frame).get("schema") == "provider-transform-ready-v1")
        ready = control(ready_frame)
        ready["phase"] = "inputs"
        ready_frame["payload_chunks"] = provider_client._payload_chunks(
            provider_client.provider_messages.encode_control(ready))
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(wrong_ready)))

        later_attempts = parse_canonical(canonical_json(wrong_ready))
        ready_index = next(index for index, frame in enumerate(later_attempts["attempts"][1]["frames"])
                           if frame["message_id"] == ready_frame["message_id"])
        later_attempts["attempts"][1]["frames"] = (
            later_attempts["attempts"][1]["frames"][:ready_index + 1])
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(later_attempts)))

        wrong_projection = parse_canonical(capture.content_bytes)
        projection_frame = next(frame for frame in wrong_projection["attempts"][1]["frames"]
            if frame["direction"] == "received"
            and frame["message_type"] == provider_client.RESULT
            and control(frame).get("schema") == "provider-transform-projection-v1")
        projection = control(projection_frame)
        projection["endpoint"] = "models"
        projection["body"] = None
        projection_frame["payload_chunks"] = provider_client._payload_chunks(
            provider_client.provider_messages.encode_control(projection))
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(wrong_projection)))

        wrong_stream = parse_canonical(capture.content_bytes)
        stream_frame = next(frame for frame in wrong_stream["attempts"][1]["frames"]
            if frame["direction"] == "received"
            and frame["message_type"] == provider_client.ARTIFACT)
        stream_frame["payload_chunks"] = provider_client._payload_chunks(b"{}")
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(wrong_stream)))

        wrong_final = parse_canonical(capture.content_bytes)
        final_frames = wrong_final["attempts"][1]["frames"]
        plan_batch = control(final_frames[0])["plan"]["batch_id"]
        final_frame = next(frame for frame in final_frames if frame["direction"] == "received"
            and frame["message_type"] == provider_client.RESULT
            and control(frame).get("schema") == "provider-transform-final-v1")
        final = control(final_frame)
        old_batch = final["result"]["batch_id"]
        final["result"]["batch_id"] = plan_batch
        final_frame["payload_chunks"] = provider_client._payload_chunks(
            provider_client.provider_messages.encode_control(final))
        for frame in final_frames:
            if (frame["direction"] == "received" and frame["message_type"] == provider_client.ARTIFACT
                    and frame["correlation_id"] == final_frame["message_id"]):
                message = parse_canonical(_frame_bytes(frame))
                if message.get("batch_id") == old_batch:
                    message["batch_id"] = plan_batch
                    frame["payload_chunks"] = provider_client._payload_chunks(canonical_json(message))
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(wrong_final)))


@pytest.mark.parametrize("schema,field", [
    ("provider-transform-projection-v1", "body"),
    ("provider-transform-final-v1", "result"),
])
def test_final_failed_attempt_rejects_duplicate_batch_local_suffix(
        tmp_path, monkeypatch, schema, field):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        with _provider_conformance_worker(staged.actual, monkeypatch):
            capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000), guard=lambda: None)
        value = parse_canonical(capture.content_bytes)
        value["attempts"] = value["attempts"][:2]
        attempt = value["attempts"][-1]
        attempt["failure"] = "protocol_error"
        frames = attempt["frames"]
        plan_batch = provider_client.provider_messages.parse_control(
            _frame_bytes(frames[0]))["plan"]["batch_id"]
        index = next(index for index, frame in enumerate(frames)
            if frame["direction"] == "received" and frame["message_type"] == provider_client.RESULT
            and provider_client.provider_messages.parse_control(_frame_bytes(frame))["schema"] == schema)
        control = provider_client.provider_messages.parse_control(_frame_bytes(frames[index]))
        old_batch = control[field]["batch_id"]
        control[field]["batch_id"] = plan_batch
        frames[index]["payload_chunks"] = provider_client._payload_chunks(
            provider_client.provider_messages.encode_control(control))
        # Keep a coherent stream after the duplicate control: stale correlations/hashes must
        # not be the reason the impossible continuation is refused.
        for frame in frames[index + 1:]:
            if (frame["message_type"] == provider_client.ARTIFACT
                    and frame["correlation_id"] == frames[index]["message_id"]):
                message = parse_canonical(_frame_bytes(frame))
                if message.get("batch_id") == old_batch:
                    message["batch_id"] = plan_batch
                    frame["payload_chunks"] = provider_client._payload_chunks(canonical_json(message))
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(value)))

        attempt["frames"] = frames[:index + 1]
        stopped = compare_capture(subject, parse_capture(canonical_json(value)))
        assert stopped.completion == "mismatch"
        assert stopped.vectors == (("text-basic-v1", "mismatch"),
            ("text-refusal-v1", "not_observed"), ("catalog-two-pages-v1", "not_observed"),
            ("catalog-negative-capability-v1", "not_observed"))
        assert stopped.covered_subchecks == ()


def test_final_failed_acquired_sample_rejects_retained_local_frames(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        with _provider_conformance_worker(staged.actual, monkeypatch):
            capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000), guard=lambda: None)
        for field in ("peer_uid", "generation_id", "connection_id"):
            value = parse_canonical(capture.content_bytes)
            attempt = value["attempts"][-1]
            connection = attempt["connection"]
            connection[field] = ((connection[field] + 1) % (2**32) if field == "peer_uid" else
                "0" * 64 if field == "generation_id" else
                value["attempts"][0]["connection"]["connection_id"])
            attempt["failure"] = "identity_mismatch"
            with pytest.raises(ConformanceError, match="^unavailable$"):
                compare_capture(subject, parse_capture(canonical_json(value)))
            attempt["frames"] = []
            stopped = compare_capture(subject, parse_capture(canonical_json(value)))
            assert stopped.completion == "mismatch"
            assert stopped.reason == "identity_mismatch"
            assert stopped.covered_subchecks == tuple(vector.vector_id for vector in fixed_vectors())


def test_final_failed_attempt_rejects_ids_that_could_not_be_recorded(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        with _provider_conformance_worker(staged.actual, monkeypatch):
            capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000), guard=lambda: None)
        for schema, field in (("provider-transform-start-v1", "plan"),
                              ("provider-transform-inputs-v1", None),
                              ("provider-transform-response-v1", "body")):
            value = parse_canonical(capture.content_bytes)
            value["attempts"] = value["attempts"][:2]
            attempt = value["attempts"][-1]
            attempt["failure"] = "protocol_error"
            frames = attempt["frames"]
            index = next(index for index, frame in enumerate(frames)
                if frame["direction"] == "sent" and frame["message_type"] == provider_client.REQUEST
                and provider_client.provider_messages.parse_control(_frame_bytes(frame))["schema"] == schema)
            control = provider_client.provider_messages.parse_control(_frame_bytes(frames[index]))
            target = control if field is None else control[field]
            target["batch_id"] = control["dialogue_id"]
            frames[index]["payload_chunks"] = provider_client._payload_chunks(
                provider_client.provider_messages.encode_control(control))
            attempt["frames"] = frames[:index + 1]
            with pytest.raises(ConformanceError, match="^unavailable$"):
                compare_capture(subject, parse_capture(canonical_json(value)))
        value = parse_canonical(capture.content_bytes)
        value["attempts"] = value["attempts"][:1]
        attempt = value["attempts"][0]
        attempt["failure"] = "protocol_error"
        attempt["frames"][-1]["message_id"] = attempt["frames"][0]["message_id"]
        with pytest.raises(ConformanceError, match="^unavailable$"):
            compare_capture(subject, parse_capture(canonical_json(value)))


def test_capture_comparison_rejects_mutated_retained_bytes_without_live_io(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        with _provider_conformance_worker(staged.actual, monkeypatch):
            capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000), guard=lambda: None)
        raw = bytearray(capture.content_bytes)
        raw[-2] ^= 1
        assert sha256(bytes(raw)).hexdigest() != sha256(capture.content_bytes).hexdigest()
        from app.extensions.provider_conformance_contracts import ConformanceError, parse_capture
        try:
            corrupted = parse_capture(bytes(raw))
        except ConformanceError:
            pass
        else:
            assert compare_capture(subject, corrupted).completion != "matched"


def test_actual_connector_unsupported_platform_is_honest_incomplete(tmp_path, monkeypatch):
    anchored_socket_path = provider_client.listener._anchored_socket_path
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        monkeypatch.setattr(provider_client.listener, "_anchored_socket_path", anchored_socket_path)
        monkeypatch.setattr(provider_client.listener.sys, "platform", "unsupported-test-platform")
        capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000), guard=lambda: None)
        value = parse_canonical(capture.content_bytes)
        assert len(value["attempts"]) == 1
        assert value["attempts"][0]["connection"] is None
        assert value["attempts"][0]["failure"] == "connection_unavailable"
        comparison = compare_capture(subject, capture)
        assert comparison.completion == "incomplete"
        assert comparison.reason == "connection_unavailable"


def test_acquired_wrong_peer_identity_is_retained_before_refusal(tmp_path, monkeypatch):
    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        actual_connect = provider_client.listener._connect_extension_authenticated

        class WrongPeer:
            def __init__(self, connection):
                self._connection = connection
                peer = connection.peer
                self.peer = SimpleNamespace(pid=peer.pid, uid=(peer.uid + 1) % (2**32),
                                            gid=peer.gid)

            def __getattr__(self, name):
                return getattr(self._connection, name)

        monkeypatch.setattr(provider_client.listener, "_connect_extension_authenticated",
            lambda *args, **kwargs: WrongPeer(actual_connect(*args, **kwargs)))
        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=1,
                                          allow_error=True):
            capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000),
                                      guard=lambda: None)
        value = parse_canonical(capture.content_bytes)
        assert len(value["attempts"]) == 1
        assert value["attempts"][0]["connection"] is not None
        assert value["attempts"][0]["connection"]["peer_uid"] != subject.uid
        assert value["attempts"][0]["failure"] == "identity_mismatch"
        comparison = compare_capture(subject, capture)
        assert comparison.completion == "mismatch"
        assert comparison.reason == "identity_mismatch"


def test_recording_reserves_wire_frame_and_canonical_archive_before_retention():
    payload = b"x" * 800_000
    envelope = SimpleNamespace(message_id=str(uuid4()), correlation_id=None,
                               message_type=provider_client.RESULT)

    class Connection:
        writes = 0

        def write(self, **kwargs):
            self.writes += 1

        def read(self, **kwargs):
            return SimpleNamespace(envelope=envelope, payload=payload)

    counter = {"ids": set(), "frames": 0, "wire_bytes": 0,
               "archive_bytes": provider_client._ARCHIVE_OVERHEAD}
    connection = Connection()
    recording = provider_client._RecordingConnection(connection, counter)
    with pytest.raises(provider_client._Stop, match="observation_limit"):
        recording.write(message_id=envelope.message_id, correlation_id=None,
                        message_type=envelope.message_type, payload=payload, deadline=None)
    assert connection.writes == 0 and recording.frames == [] and counter["frames"] == 0

    with pytest.raises(provider_client._Stop, match="observation_limit"):
        recording.read(deadline=None)
    assert recording.frames == [] and counter["frames"] == 0

    counter["frames"] = 256
    small = provider_client._RecordingConnection(Connection(), counter)
    with pytest.raises(provider_client._Stop, match="observation_limit"):
        small.write(message_id=str(uuid4()), correlation_id=None,
                    message_type=provider_client.REQUEST, payload=b"{}", deadline=None)


@pytest.mark.parametrize("case,serve_count", [
    ("correlation", 1), ("projection", 2), ("model", 2), ("result", 2), ("stream", 2),
    ("projection_batch_reuse", 2), ("final_batch_reuse", 2),
])
def test_actual_worker_wrong_frames_are_retained_as_mismatch_without_continuation(
        tmp_path, monkeypatch, case, serve_count):
    from app.workers import provider_messages, provider_service

    vectors = fixed_vectors()
    actual_write = provider_service._Dialogue.write
    actual_stream = provider_service._Dialogue.stream
    actual_read = provider_service._Dialogue.read
    actual_description = provider_service._Dialogue.description

    def read(dialogue, *args, **kwargs):
        message_id, value = actual_read(dialogue, *args, **kwargs)
        if kwargs.get("first") and value.get("schema") == "provider-transform-start-v1":
            dialogue._task45_plan_batch = value["plan"]["batch_id"]
            dialogue._task45_description_count = 0
        return message_id, value

    def description(dialogue, raw):
        value = actual_description(dialogue, raw)
        if case in {"projection_batch_reuse", "final_batch_reuse"} \
                and hasattr(dialogue, "_task45_plan_batch"):
            dialogue._task45_description_count += 1
            target = 1 if case == "projection_batch_reuse" else 2
            if dialogue._task45_description_count == target:
                value = {**value, "batch_id": dialogue._task45_plan_batch}
        return value

    def write(dialogue, value, *, correlation=None):
        value = dict(value)
        if case == "correlation" and value.get("schema") == "provider-worker-identity-v1":
            correlation = str(uuid4())
        if case == "projection" and value.get("schema") == "provider-transform-projection-v1":
            value = {**value, "endpoint": "models", "body": None}
        if case == "model" and value.get("schema") == "provider-transform-projection-v1":
            forged = canonical_json({"model": "wrong-worker-model", "max_tokens": 32,
                "stream": True, "messages": [{"role": "user", "content": [
                    {"type": "text", "text": "hello conformance\n"}]}]})
            value["body"] = {**value["body"], "size": len(forged),
                "sha256": sha256(forged).hexdigest()}
            message_id = actual_write(dialogue, value, correlation=correlation)
            dialogue._task45_forged_projection = (message_id, value["body"], forged)
            return message_id
        if case == "result" and value.get("schema") == "provider-transform-final-v1":
            forged = vectors[1].expected_result_bytes
            value["result"] = {**value["result"], "size": len(forged),
                "sha256": sha256(forged).hexdigest()}
            message_id = actual_write(dialogue, value, correlation=correlation)
            dialogue._task45_forged_final = (message_id, value["result"], forged)
            return message_id
        return actual_write(dialogue, value, correlation=correlation)

    def stream(dialogue, announcing, descriptions, *, raw=None):
        projection = getattr(dialogue, "_task45_forged_projection", None)
        if projection is not None and announcing == projection[0]:
            return actual_stream(dialogue, announcing, [projection[1]], raw=(projection[2],))
        forged = getattr(dialogue, "_task45_forged_final", None)
        if forged is not None and announcing == forged[0]:
            return actual_stream(dialogue, announcing, [forged[1]], raw=(forged[2],))
        if case == "stream" and raw and raw[0] == vectors[0].expected_result_bytes:
            return actual_stream(dialogue, announcing, descriptions, raw=(b"x" + raw[0][1:],))
        return actual_stream(dialogue, announcing, descriptions, raw=raw)

    with staged_conformance_app(tmp_path, monkeypatch) as staged:
        monkeypatch.setattr(provider_service._Dialogue, "write", write)
        if case in {"projection_batch_reuse", "final_batch_reuse"}:
            monkeypatch.setattr(provider_service._Dialogue, "read", read)
            monkeypatch.setattr(provider_service._Dialogue, "description", description)
        if case in {"model", "result", "stream"}:
            monkeypatch.setattr(provider_service._Dialogue, "stream", stream)
        with _writer(), staged.domain._connection(write=True) as db:
            subject = staged.prepare._provider_conformance_subject(db, staged.installation_ref)
        with _provider_conformance_worker(staged.actual, monkeypatch, serve_count=serve_count,
                                          allow_error=True) as (_, worker):
            capture = run_fixed_suite(subject, deadline=Deadline.after_ms(60000),
                                      guard=lambda: None)
        assert worker.completion_count <= serve_count
        value = parse_canonical(capture.content_bytes)
        assert [attempt["role"] for attempt in value["attempts"]] == (
            ["identify-before"] if case == "correlation" else
            ["identify-before", "text-basic-v1"]), value
        controls = []
        for frame in value["attempts"][-1]["frames"]:
            if frame["message_type"] in {provider_client.REQUEST, provider_client.RESULT}:
                controls.append((frame["direction"], provider_messages.parse_control(b64decode(
                    "".join(frame["payload_chunks"])))))
        if case in {"projection", "projection_batch_reuse"}:
            projections = [control for direction, control in controls if direction == "received"
                           and control.get("schema") == "provider-transform-projection-v1"]
            assert projections, (controls, value["attempts"][-1]["failure"])
            if case == "projection":
                assert projections[0]["endpoint"] == "models"
        comparison = compare_capture(subject, capture)
        assert comparison.completion == "mismatch", (value, comparison)
        assert value["attempts"][-1]["failure"] in {"identity_mismatch", "protocol_error"}
        if case in {"projection", "projection_batch_reuse"}:
            supplied = [control for direction, control in controls if direction == "sent"
                        and control.get("schema") == "provider-transform-response-v1"]
            assert supplied == []
