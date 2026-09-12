"""T018-F1 bounded digest/chunk/receiver-credit artifact stream acceptance tests."""

from __future__ import annotations

import base64
import hashlib
import json
import queue
import threading

import pytest

from app.workers import broker
from app.workers.artifact_stream import (
    MAX_CHUNK_BYTES,
    ArtifactDescriptor,
    ArtifactStreamError,
    BytesSink,
    BytesSource,
    ScratchFileSink,
    StreamCancelled,
    StreamLimits,
    _encode,
    receive_artifact,
    receive_batch,
    send_artifact,
    send_batch,
)

BATCH = "123e4567-e89b-42d3-a456-426614174000"
REQUEST = "123e4567-e89b-42d3-a456-426614174111"


def descriptor(data: bytes, *, ordinal=0, count=1, media_type="text/plain",
               batch_id=BATCH, request_id=REQUEST, size=None, sha=None):
    return ArtifactDescriptor(
        batch_id=batch_id,
        request_id=request_id,
        ordinal=ordinal,
        count=count,
        media_type=media_type,
        declared_size=len(data) if size is None else size,
        sha256=hashlib.sha256(data).hexdigest() if sha is None else sha,
    )


class PairedTransport:
    """Two synchronized byte queues wiring a sender thread to a receiver thread."""

    def __init__(self, outbound: queue.Queue, inbound: queue.Queue):
        self._out = outbound
        self._in = inbound

    def send(self, payload: bytes) -> None:
        self._out.put(payload)

    def receive(self) -> bytes:
        try:
            return self._in.get(timeout=3)
        except queue.Empty as exc:
            raise ArtifactStreamError("transport starved") from exc


def make_pair():
    a, b = queue.Queue(), queue.Queue()
    return PairedTransport(a, b), PairedTransport(b, a)


class ScriptedTransport:
    """Feed a receiver a fixed list of encoded frames; record what it sends back."""

    def __init__(self, incoming: list[bytes]):
        self._incoming = list(incoming)
        self.sent: list[dict] = []

    def send(self, payload: bytes) -> None:
        self.sent.append(json.loads(payload.decode("ascii")))

    def receive(self) -> bytes:
        if not self._incoming:
            raise ArtifactStreamError("scripted transport exhausted")
        return self._incoming.pop(0)


def run_pair(desc, data, sink, *, limits=None):
    """Run send and receive concurrently; return the receiver's outcome."""
    sender_side, receiver_side = make_pair()
    errors: dict[str, BaseException] = {}

    def do_send():
        try:
            send_artifact(sender_side, desc, BytesSource(data), limits=limits)
        except BaseException as exc:  # noqa: BLE001
            errors["send"] = exc

    def do_recv():
        try:
            receive_artifact(receiver_side, desc, sink, limits=limits)
        except BaseException as exc:  # noqa: BLE001
            errors["recv"] = exc

    ts = threading.Thread(target=do_send)
    tr = threading.Thread(target=do_recv)
    tr.start(); ts.start()
    ts.join(5); tr.join(5)
    assert not ts.is_alive() and not tr.is_alive(), "stream deadlocked"
    return errors


# ----------------------------------------------------------------------------- happy paths


def test_single_chunk_roundtrip_preserves_bytes_and_digest():
    data = b"hello deeptwin"
    sink = BytesSink()
    errors = run_pair(descriptor(data), data, sink)
    assert errors == {}
    assert sink.value == data


def test_multi_chunk_stream_needs_several_credit_rounds():
    data = bytes((i * 37) % 256 for i in range(70_000))
    sink = BytesSink()
    limits = StreamLimits(max_chunk_bytes=4_096, credit_window_chunks=2)
    errors = run_pair(descriptor(data), data, sink, limits=limits)
    assert errors == {}
    assert sink.value == data and len(sink.value) == 70_000


def test_zero_length_artifact_completes_without_chunks():
    data = b""
    sink = BytesSink()
    errors = run_pair(descriptor(data), data, sink)
    assert errors == {}
    assert sink.value == b""


def test_ordered_batch_streams_every_artifact():
    payloads = [b"first", b"second-artifact", bytes(range(50)) * 3]
    descs = [
        descriptor(p, ordinal=i, count=len(payloads)) for i, p in enumerate(payloads)
    ]
    sinks = [BytesSink() for _ in payloads]
    sender_side, receiver_side = make_pair()
    errors: dict[str, BaseException] = {}

    def do_send():
        try:
            send_batch(sender_side, descs, [BytesSource(p) for p in payloads])
        except BaseException as exc:  # noqa: BLE001
            errors["send"] = exc

    def do_recv():
        try:
            receive_batch(receiver_side, descs, sinks)
        except BaseException as exc:  # noqa: BLE001
            errors["recv"] = exc

    tr = threading.Thread(target=do_recv); ts = threading.Thread(target=do_send)
    tr.start(); ts.start(); ts.join(5); tr.join(5)
    assert errors == {}
    assert [s.value for s in sinks] == payloads


# ----------------------------------------------------------------------------- sender integrity


def test_source_digest_mismatch_fails_and_cancels_without_finalizing():
    data = b"the real bytes"
    wrong = descriptor(data, sha="0" * 64)  # declared digest does not match the source
    sink = BytesSink()
    errors = run_pair(wrong, data, sink)
    assert isinstance(errors.get("send"), ArtifactStreamError)
    assert isinstance(errors.get("recv"), StreamCancelled)
    with pytest.raises(ArtifactStreamError):
        _ = sink.value  # never finalized


def test_declared_size_larger_than_source_is_a_short_read():
    data = b"only twelve!"
    lying = descriptor(data, size=len(data) + 10, sha=hashlib.sha256(data).hexdigest())
    sink = BytesSink()
    errors = run_pair(lying, data, sink)
    assert isinstance(errors.get("send"), ArtifactStreamError)
    assert isinstance(errors.get("recv"), (ArtifactStreamError, StreamCancelled))


# ----------------------------------------------------------------------------- receiver defenses (scripted attacker)


def credit_seen(scripted):
    return [m for m in scripted.sent if m["type"] == "artifact-credit"]


def test_offer_mismatch_is_rejected_before_any_credit():
    data = b"payload"
    expected = descriptor(data)
    other = descriptor(data, media_type="application/pdf")
    offer = _encode({"type": "artifact-offer", **other.as_offer_fields()})
    scripted = ScriptedTransport([offer])
    sink = BytesSink()
    with pytest.raises(ArtifactStreamError, match="offer does not match"):
        receive_artifact(scripted, expected, sink)


def test_chunk_beyond_granted_credit_is_terminal():
    data = b"x" * 10_000
    desc = descriptor(data)
    limits = StreamLimits(max_chunk_bytes=1_024, credit_window_chunks=1)
    offer = _encode({"type": "artifact-offer", **desc.as_offer_fields()})
    # Offer, then a chunk that overshoots the 1,024-byte first-window credit.
    overshoot = _encode({
        "type": "artifact-chunk", "batch_id": BATCH, "ordinal": 0,
        "offset": 0, "data": base64.b64encode(b"x" * 2_000).decode(),
    })
    scripted = ScriptedTransport([offer, overshoot])
    sink = BytesSink()
    with pytest.raises(ArtifactStreamError):
        receive_artifact(scripted, desc, sink, limits=limits)


def test_out_of_order_chunk_offset_is_terminal():
    data = b"y" * 500
    desc = descriptor(data)
    offer = _encode({"type": "artifact-offer", **desc.as_offer_fields()})
    bad_offset = _encode({
        "type": "artifact-chunk", "batch_id": BATCH, "ordinal": 0,
        "offset": 8, "data": base64.b64encode(b"y" * 10).decode(),
    })
    scripted = ScriptedTransport([offer, bad_offset])
    sink = BytesSink()
    with pytest.raises(ArtifactStreamError, match="next expected byte"):
        receive_artifact(scripted, desc, sink)


def test_over_limit_chunk_length_is_terminal():
    data = b"z" * 40_000
    desc = descriptor(data)
    offer = _encode({"type": "artifact-offer", **desc.as_offer_fields()})
    huge = _encode({
        "type": "artifact-chunk", "batch_id": BATCH, "ordinal": 0,
        "offset": 0, "data": base64.b64encode(b"z" * (MAX_CHUNK_BYTES + 1)).decode(),
    })
    scripted = ScriptedTransport([offer, huge])
    sink = BytesSink()
    with pytest.raises(ArtifactStreamError):
        receive_artifact(scripted, desc, sink)


def test_end_digest_disagreement_is_terminal_and_aborts():
    data = b"consistent"
    desc = descriptor(data)
    offer = _encode({"type": "artifact-offer", **desc.as_offer_fields()})
    chunk = _encode({
        "type": "artifact-chunk", "batch_id": BATCH, "ordinal": 0,
        "offset": 0, "data": base64.b64encode(data).decode(),
    })
    lying_end = _encode({
        "type": "artifact-end", "batch_id": BATCH, "ordinal": 0,
        "size": len(data), "sha256": "1" * 64,
    })
    scripted = ScriptedTransport([offer, chunk, lying_end])
    sink = BytesSink()
    with pytest.raises(ArtifactStreamError, match="digest disagrees"):
        receive_artifact(scripted, desc, sink)
    assert scripted.sent[-1]["type"] != "artifact-accepted"


def test_sender_cancel_propagates_as_stream_cancelled():
    data = b"partial"
    desc = descriptor(data)
    offer = _encode({"type": "artifact-offer", **desc.as_offer_fields()})
    cancel = _encode({"type": "artifact-cancel", "batch_id": BATCH, "reason": "sender_fault"})
    scripted = ScriptedTransport([offer, cancel])
    sink = BytesSink()
    with pytest.raises(StreamCancelled):
        receive_artifact(scripted, desc, sink)


# ----------------------------------------------------------------------------- sender-side credit defenses


def send_only(desc, data, incoming):
    """Drive send_artifact against scripted receiver replies."""
    scripted = ScriptedTransport(incoming)
    send_artifact(scripted, desc, BytesSource(data))
    return scripted


def test_backward_credit_watermark_is_rejected():
    data = b"a" * 100
    desc = descriptor(data)
    first = _encode({"type": "artifact-credit", "batch_id": BATCH, "ordinal": 0,
                     "consumed_through": 0, "credit_through": 60})
    backward = _encode({"type": "artifact-credit", "batch_id": BATCH, "ordinal": 0,
                        "consumed_through": 0, "credit_through": 40})
    with pytest.raises(ArtifactStreamError, match="backward"):
        send_only(desc, data, [first, backward])


def test_nonadvancing_credit_while_bytes_remain_is_a_stall():
    data = b"b" * 100
    desc = descriptor(data)
    # Grants 60, sender ships 60, then repeats 60 forever: a stalled consumer.
    first = _encode({"type": "artifact-credit", "batch_id": BATCH, "ordinal": 0,
                     "consumed_through": 0, "credit_through": 60})
    repeat = _encode({"type": "artifact-credit", "batch_id": BATCH, "ordinal": 0,
                      "consumed_through": 60, "credit_through": 60})
    with pytest.raises(ArtifactStreamError, match="stalled"):
        send_only(desc, data, [first, repeat])


def test_credit_over_declared_size_is_rejected():
    data = b"c" * 20
    desc = descriptor(data)
    inflated = _encode({"type": "artifact-credit", "batch_id": BATCH, "ordinal": 0,
                        "consumed_through": 0, "credit_through": 999})
    with pytest.raises(ArtifactStreamError):
        send_only(desc, data, [inflated])


# ----------------------------------------------------------------------------- framing bounds and encoding


def test_max_chunk_double_encoded_stays_within_broker_frame_limit():
    raw = b"\xa5" * MAX_CHUNK_BYTES
    message = _encode({
        "type": "artifact-chunk", "batch_id": BATCH, "ordinal": 0,
        "offset": 0, "data": base64.b64encode(raw).decode(),
    })
    # The broker re-base64s the whole payload inside a JSON envelope.
    envelope_payload = base64.b64encode(message).decode()
    assert len(message) < broker.MAX_FRAME_BYTES
    assert len(envelope_payload) + 1_024 < broker.MAX_FRAME_BYTES


def test_noncanonical_base64_and_floats_are_rejected():
    desc = descriptor(b"data")
    offer = _encode({"type": "artifact-offer", **desc.as_offer_fields()})
    # A float where an integer offset is required.
    floaty = b'{"type":"artifact-chunk","batch_id":"' + BATCH.encode() + \
        b'","ordinal":0,"offset":0.0,"data":"AAAA"}'
    scripted = ScriptedTransport([offer, floaty])
    with pytest.raises(ArtifactStreamError):
        receive_artifact(scripted, desc, BytesSink())


# ----------------------------------------------------------------------------- descriptor and batch validation


@pytest.mark.parametrize("kwargs", [
    {"batch_id": "not-a-uuid"},
    {"ordinal": 5, "count": 3},
    {"media_type": "TEXT/PLAIN"},
    {"sha": "z" * 64},
    {"size": 64 * 1024 * 1024 + 1, "sha": "0" * 64},
])
def test_descriptor_rejects_invalid_fields(kwargs):
    with pytest.raises(ArtifactStreamError):
        descriptor(b"payload", **kwargs)


def test_batch_rejects_wrong_ordinal_sequence():
    descs = [descriptor(b"a", ordinal=0, count=2), descriptor(b"b", ordinal=0, count=2)]
    with pytest.raises(ArtifactStreamError, match="exact ordered sequence"):
        send_batch(make_pair()[0], descs, [BytesSource(b"a"), BytesSource(b"b")])


def test_batch_aggregate_over_total_limit_is_rejected():
    big = b"q" * 4096
    descs = [descriptor(big, ordinal=i, count=2) for i in range(2)]
    limits = StreamLimits(max_total_bytes=4096)
    with pytest.raises(ArtifactStreamError, match="aggregate"):
        receive_batch(make_pair()[1], descs, [BytesSink(), BytesSink()], limits=limits)


# ----------------------------------------------------------------------------- owned scratch sink


def test_scratch_file_sink_persists_bytes_and_abort_unlinks(tmp_path):
    data = b"scratch bytes" * 100
    desc = descriptor(data)
    sink = ScratchFileSink(str(tmp_path), "artifact-0.bin")
    errors = run_pair(desc, data, sink)
    assert errors == {}
    assert (tmp_path / "artifact-0.bin").read_bytes() == data


def test_scratch_file_sink_aborts_on_bad_stream(tmp_path):
    data = b"doomed"
    wrong = descriptor(data, sha="0" * 64)
    sink = ScratchFileSink(str(tmp_path), "doomed.bin")
    run_pair(wrong, data, sink)
    assert not (tmp_path / "doomed.bin").exists()


# ------------------------------------------------------- offer-driven receiving


def offered_policy(**overrides):
    from app.workers.artifact_stream import OfferedBatchPolicy

    fields = {
        "request_id": REQUEST,
        "allowed_media_types": ("text/plain", "application/pdf"),
        "max_artifacts": 4,
    }
    fields.update(overrides)
    return OfferedBatchPolicy(**fields)


def run_offered(descs, payloads, policy, *, limits=None):
    from app.workers.artifact_stream import receive_offered_batch

    sender_side, receiver_side = make_pair()
    errors: dict[str, BaseException] = {}
    outcome: dict[str, object] = {}

    def do_send():
        try:
            send_batch(sender_side, descs, [BytesSource(p) for p in payloads], limits=limits)
        except BaseException as exc:  # noqa: BLE001
            errors["send"] = exc

    def do_recv():
        try:
            outcome["admitted"] = receive_offered_batch(
                receiver_side, policy, lambda _descriptor: BytesSink(), limits=limits,
            )
        except BaseException as exc:  # noqa: BLE001
            errors["recv"] = exc

    ts = threading.Thread(target=do_send)
    tr = threading.Thread(target=do_recv)
    tr.start(); ts.start()
    ts.join(5); tr.join(5)
    assert not ts.is_alive() and not tr.is_alive(), "offered stream deadlocked"
    return errors, outcome


def test_offered_batch_round_trips_without_prior_descriptors():
    payloads = [b"first artifact", bytes((i * 13) % 256 for i in range(40_000)), b""]
    descs = [
        descriptor(data, ordinal=index, count=len(payloads))
        for index, data in enumerate(payloads)
    ]
    limits = StreamLimits(max_chunk_bytes=4_096, credit_window_chunks=2)
    errors, outcome = run_offered(descs, payloads, offered_policy(), limits=limits)
    assert errors == {}
    admitted = outcome["admitted"]
    assert [entry[0] for entry in admitted] == descs
    assert [entry[1].value for entry in admitted] == payloads


def test_offered_batch_rejects_a_foreign_request_id():
    data = b"foreign"
    descs = [descriptor(data)]
    errors, outcome = run_offered(
        descs, [data], offered_policy(request_id="123e4567-e89b-42d3-a456-426614174999"),
    )
    assert isinstance(errors.get("recv"), ArtifactStreamError)
    assert "send" in errors
    assert "admitted" not in outcome


def test_offered_batch_rejects_a_disallowed_media_type():
    data = b"binary"
    descs = [descriptor(data, media_type="application/octet-stream")]
    errors, _ = run_offered(descs, [data], offered_policy())
    assert isinstance(errors.get("recv"), ArtifactStreamError)
    assert "send" in errors


def test_offered_batch_rejects_a_count_beyond_the_policy():
    payloads = [b"a", b"b", b"c"]
    descs = [
        descriptor(data, ordinal=index, count=len(payloads))
        for index, data in enumerate(payloads)
    ]
    errors, _ = run_offered(descs, payloads, offered_policy(max_artifacts=2))
    assert isinstance(errors.get("recv"), ArtifactStreamError)
    assert "send" in errors


def test_offered_batch_rejects_an_aggregate_beyond_total_bytes():
    payloads = [b"x" * 600, b"y" * 600]
    descs = [
        descriptor(data, ordinal=index, count=len(payloads))
        for index, data in enumerate(payloads)
    ]
    limits = StreamLimits(max_total_bytes=1_000)
    errors, _ = run_offered(descs, payloads, offered_policy(), limits=limits)
    assert isinstance(errors.get("recv"), ArtifactStreamError)
    assert "send" in errors


def test_offered_batch_rejects_a_changed_batch_identity_mid_stream():
    from app.workers.artifact_stream import receive_offered_batch

    first = descriptor(b"one", ordinal=0, count=2)
    imposter = descriptor(
        b"two", ordinal=1, count=2, batch_id="123e4567-e89b-42d3-a456-426614174333",
    )
    accepted_digest = first.sha256
    scripted = ScriptedTransport([
        _encode({"type": "artifact-offer", **first.as_offer_fields()}),
        _encode({
            "type": "artifact-chunk", "batch_id": first.batch_id, "ordinal": 0,
            "offset": 0, "data": base64.b64encode(b"one").decode("ascii"),
        }),
        _encode({
            "type": "artifact-end", "batch_id": first.batch_id, "ordinal": 0,
            "size": 3, "sha256": accepted_digest,
        }),
        _encode({"type": "artifact-offer", **imposter.as_offer_fields()}),
    ])
    with pytest.raises(ArtifactStreamError, match="batch identity"):
        receive_offered_batch(scripted, offered_policy(), lambda _d: BytesSink())
    assert scripted.sent[-1]["type"] == "artifact-cancel"


def test_offered_batch_policy_validates_its_own_fields():
    from app.workers.artifact_stream import OfferedBatchPolicy

    with pytest.raises(ArtifactStreamError):
        OfferedBatchPolicy(
            request_id="not-a-uuid",
            allowed_media_types=("text/plain",),
            max_artifacts=1,
        )
    with pytest.raises(ArtifactStreamError):
        OfferedBatchPolicy(
            request_id=REQUEST, allowed_media_types=(), max_artifacts=1,
        )
    with pytest.raises(ArtifactStreamError):
        OfferedBatchPolicy(
            request_id=REQUEST, allowed_media_types=("Nope",), max_artifacts=1,
        )
    with pytest.raises(ArtifactStreamError):
        OfferedBatchPolicy(
            request_id=REQUEST, allowed_media_types=("text/plain",), max_artifacts=0,
        )
    with pytest.raises(ArtifactStreamError):
        receive_offered_batch_with_bad_policy()


def receive_offered_batch_with_bad_policy():
    from app.workers.artifact_stream import receive_offered_batch

    receive_offered_batch(ScriptedTransport([]), object(), lambda _d: BytesSink())


def test_pushback_transport_replays_the_first_payload_once():
    from app.workers.artifact_stream import PushbackTransport

    inner = ScriptedTransport([b"second", b"third"])
    transport = PushbackTransport(inner, first=b"first")
    assert transport.receive() == b"first"
    assert transport.receive() == b"second"
    transport.send(_encode({"type": "artifact-cancel", "batch_id": BATCH}))
    assert inner.sent[-1]["type"] == "artifact-cancel"
    assert transport.receive() == b"third"
    with pytest.raises(ArtifactStreamError):
        PushbackTransport(inner, first="not-bytes")


# --------------------------------------------------- audit findings F1-F3


class EvilSource:
    """A caller-supplied source that fails with a non-stream exception."""

    def read(self, size: int) -> bytes:
        raise ValueError("boom from a caller-supplied source")


def test_a_non_stream_source_failure_cancels_and_wraps_terminally():
    data = b"payload"
    desc = descriptor(data)
    scripted = ScriptedTransport([
        _encode({
            "type": "artifact-credit", "batch_id": BATCH, "ordinal": 0,
            "consumed_through": 0, "credit_through": len(data),
        }),
    ])
    with pytest.raises(ArtifactStreamError):
        send_artifact(scripted, desc, EvilSource())
    assert scripted.sent[-1]["type"] == "artifact-cancel"


def test_a_mid_batch_failure_aborts_every_previously_admitted_sink():
    from app.workers.artifact_stream import receive_offered_batch

    first = descriptor(b"one", ordinal=0, count=2)
    duplicate = descriptor(b"two", ordinal=0, count=2)
    scripted = ScriptedTransport([
        _encode({"type": "artifact-offer", **first.as_offer_fields()}),
        _encode({
            "type": "artifact-chunk", "batch_id": first.batch_id, "ordinal": 0,
            "offset": 0, "data": base64.b64encode(b"one").decode("ascii"),
        }),
        _encode({
            "type": "artifact-end", "batch_id": first.batch_id, "ordinal": 0,
            "size": 3, "sha256": first.sha256,
        }),
        _encode({"type": "artifact-offer", **duplicate.as_offer_fields()}),
    ])
    sinks = []

    def factory(_descriptor):
        sink = BytesSink()
        sinks.append(sink)
        return sink

    with pytest.raises(ArtifactStreamError):
        receive_offered_batch(scripted, offered_policy(), factory)
    assert len(sinks) == 1
    with pytest.raises(ArtifactStreamError):
        _ = sinks[0].value  # the orphaned first artifact must be aborted, not kept


def test_scratch_sink_abort_reverses_a_finalized_file_and_is_idempotent(tmp_path):
    sink = ScratchFileSink(str(tmp_path), "kept.bin")
    sink.write(0, b"bytes")
    sink.finalize()
    assert (tmp_path / "kept.bin").exists()
    sink.abort()
    assert not (tmp_path / "kept.bin").exists()
    sink.abort()  # idempotent: no fd double-close, no OSError


def test_scratch_sink_double_abort_is_idempotent(tmp_path):
    sink = ScratchFileSink(str(tmp_path), "gone.bin")
    sink.write(0, b"x")
    sink.abort()
    sink.abort()
    assert not (tmp_path / "gone.bin").exists()
