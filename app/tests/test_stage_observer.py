"""Task 24 step (d): the control-side stage postcondition observer
(contracts/deployment-receipt-journal-v3.md §4 evidence blob, §5 observer).

`observe_stage_postcondition` connects to the staged worker's probe channel
under the module's own process boot ID, sends exactly two probes, verifies
every reply against the retained `ExpectedStageIdentity` and the kernel peer,
and returns the only constructor of `StagePostconditionEvidence`: the
canonical `extension-stage-postcondition-v1` bytes. Every deviation is a
closed error and nothing is produced.

The responder is the actual in-process `WorkerProbeService` through the
macOS seams of the listener tests (no peer credentials, no /proc, synthetic
mountinfo); the peer credentials are supplied by the connect seam so that
the observer's comparison is exercised. Positive Linux authentication, the
real worker image and the container are host gates, never claimed here.
"""

import hashlib
import importlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.deployment.prepare_contracts import b64
from app.domain.refs import canonical_json, parse_canonical
from app.extensions.lineage_contracts import parse_build_identity
from app.tests.test_extension_listener import open_fds
from app.tests.test_extension_probe import (  # noqa: F401 - fixture re-exports
    INSTANCE,
    SLOT,
    channel,
    open_service,
    serve_in_thread,
    slot,
    worker_tree,
)
from app.tests.test_extension_worker_metadata import GID, UID
from app.workers import broker, listener
from app.workers.extension_channel import extension_channel
from app.workers.extension_probe_messages import encode_probe_reply

REQUEST_ID = "12345678-1234-4234-8234-123456789abc"
REQUEST_BYTES = b'{"request":"bytes"}'
RECEIPT_BYTES = b'{"receipt":"bytes"}'


def module():
    try:
        return importlib.import_module("app.deployment.stage_observer")
    except ModuleNotFoundError:
        pytest.fail("Stage observer is missing")


@pytest.fixture
def observed(slot, monkeypatch):  # noqa: F811 - the imported fixture
    """The service's slot, with the observer's channel derivation redirected to
    the same test root and the connect seam supplying the slot's peer."""

    root, spec, side, tree = slot
    observer = module()

    def derived(*, instance_id, slot_number):
        # the real derivation validates the identity; only the root is redirected
        extension_channel(instance_id=instance_id, slot_number=slot_number)
        assert (instance_id, slot_number) == (INSTANCE, SLOT)
        return root, spec

    monkeypatch.setattr(observer, "extension_channel", derived)
    peer = {"value": broker.PeerCredentials(pid=4242, uid=UID, gid=GID)}

    def connect_verified(channel_spec, *, local_service, deadline):
        import socket

        path = listener._anchored_socket_path(-1, root, channel_spec.socket_name)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(path)
        return sock, broker._endpoint_identity(os.stat(path)), peer["value"]

    monkeypatch.setattr(listener.broker, "connect_verified", connect_verified)
    identity = parse_build_identity(tree["identity"].read_bytes())
    expected = observer.ExpectedStageIdentity(
        service_identity=spec.responder_service,
        build_identity_digest=identity.digest,
        port_schema_set_digest=identity.schema_set_digest,
        port_contract_version="tool-port-v1",
        platform="linux/amd64",
        uid=UID,
        gid=GID,
    )
    return root, spec, side, peer, expected


def digests():
    return b64(hashlib.sha256(REQUEST_BYTES).digest()), b64(
        hashlib.sha256(RECEIPT_BYTES).digest()
    )


def observe(identity, *, deadline_ms=3_000, **changes):
    observer = module()
    request_digest, receipt_digest = digests()
    arguments = {
        "request_id": REQUEST_ID,
        "request_digest": request_digest,
        "receipt_digest": receipt_digest,
        "request_bytes": REQUEST_BYTES,
        "receipt_bytes": RECEIPT_BYTES,
        "slot_number": SLOT,
        "instance_id": INSTANCE,
        "expected": identity,
        "deadline": broker.Deadline.after_ms(deadline_ms),
        **changes,
    }
    return observer.observe_stage_postcondition(**arguments)


def test_observation_against_the_actual_probe_service_yields_the_evidence_blob(observed):
    _root, spec, side, _peer, expected = observed
    observer = module()
    baseline = open_fds()
    service = open_service()
    try:
        box = {}
        thread = serve_in_thread(service, box, side)
        started = time.monotonic()
        evidence = observer.observe_stage_postcondition(
            request_id=REQUEST_ID,
            request_digest=digests()[0],
            receipt_digest=digests()[1],
            request_bytes=REQUEST_BYTES,
            receipt_bytes=RECEIPT_BYTES,
            slot_number=SLOT,
            instance_id=INSTANCE,
            expected=expected,
            deadline=broker.Deadline.after_ms(3_000),
        )
        elapsed = time.monotonic() - started
        thread.join(5)
        assert "error" not in box, box.get("error")
        assert box["served"] == 2
    finally:
        service.close()
    assert open_fds() == baseline
    assert type(evidence) is observer.StagePostconditionEvidence
    raw = evidence.content_bytes
    assert type(raw) is bytes and 1 <= evidence.size == len(raw) <= 8_192
    assert evidence.digest == hashlib.sha256(raw).hexdigest()
    assert canonical_json(parse_canonical(raw)) == raw
    value = parse_canonical(raw)
    assert value["schema_version"] == "extension-stage-postcondition-v1"
    assert value["request_id"] == REQUEST_ID
    assert (value["request_digest"], value["receipt_digest"]) == digests()
    assert value["request_blob_sha256"] == hashlib.sha256(REQUEST_BYTES).hexdigest()
    assert value["receipt_blob_sha256"] == hashlib.sha256(RECEIPT_BYTES).hexdigest()
    assert 1 <= value["attempt_ms"] <= 2_000 and value["attempt_ms"] >= int(elapsed * 1000) - 5
    assert value["comparison"] == "equal"
    connection = value["connection"]
    assert connection["channel_id"] == spec.channel_id
    assert len(connection["connection_id"]) == 64
    assert connection["requester_boot_id"] == observer._process_boot_id()
    assert set(connection["responder_boot_id"]) <= set("0123456789abcdef")
    assert (connection["peer_uid"], connection["peer_gid"]) == (UID, GID)
    assert value["expected"] == {
        "service_identity": spec.responder_service,
        "build_identity_digest": expected.build_identity_digest,
        "port_schema_set_digest": expected.port_schema_set_digest,
        "port_contract_version": "tool-port-v1",
        "platform": "linux/amd64",
        "uid": UID,
        "gid": GID,
    }
    probes = value["probes"]
    assert len(probes) == 2
    assert len({p["challenge"] for p in probes}) == 2
    ids = [p["request_message_id"] for p in probes] + [p["reply_message_id"] for p in probes]
    assert len(set(ids)) == 4
    for probe in probes:
        reply = probe["reply"]
        assert reply["service_identity"] == spec.responder_service
        assert reply["component"]["build_identity_digest"] == expected.build_identity_digest
        assert reply["runtime"]["registered_operations"] == ["describe_tools", "status"]  # T087 execute slices
    assert "observed_at" in value and value["observed_at"].endswith("Z")
    # the evidence is an inert frozen value: no live socket, no construction, no mutation
    with pytest.raises(TypeError):
        observer.StagePostconditionEvidence()
    with pytest.raises((AttributeError, TypeError)):
        evidence.content_bytes = b""
    assert "request" not in repr(evidence) and REQUEST_ID not in repr(evidence)


def test_the_process_boot_id_is_generated_once_and_is_hex64(observed):
    observer = module()
    first = observer._process_boot_id()
    assert len(first) == 64 and set(first) <= set("0123456789abcdef")
    assert observer._process_boot_id() == first


@pytest.mark.parametrize(
    "field, value",
    [
        ("build_identity_digest", "0" * 64),
        ("port_schema_set_digest", "0" * 64),
        ("platform", "linux/arm64"),
        ("uid", UID + 1),
        ("gid", GID + 1),
        ("service_identity", "ext-0123456789abcdef0123456789abcdef-05"),
    ],
)
def test_every_compared_field_mismatch_is_a_closed_mismatch_with_no_evidence(
    observed, field, value
):
    _root, _spec, side, _peer, expected = observed
    observer = module()
    wrong = observer.ExpectedStageIdentity(**{**expected.as_dict(), field: value})
    baseline = open_fds()
    service = open_service()
    try:
        box = {}
        thread = serve_in_thread(service, box, side)
        with pytest.raises(observer.StagePostconditionError) as error:
            observe(wrong)
        assert error.value.code == "probe_mismatch"
        assert str(error.value) == "probe_mismatch"
        thread.join(5)
    finally:
        service.close()
    assert "0" * 64 not in str(error.value)
    assert open_fds() == baseline


def test_a_peer_outside_the_slot_or_absent_is_refused(observed):
    _root, _spec, side, peer, expected = observed
    observer = module()
    baseline = open_fds()
    for value, code in (
        (broker.PeerCredentials(pid=4242, uid=UID + 1, gid=GID), "probe_mismatch"),
        (None, "probe_invalid"),
    ):
        peer["value"] = value
        service = open_service()
        try:
            box = {}
            thread = serve_in_thread(service, box, side)
            with pytest.raises(observer.StagePostconditionError) as error:
                observe(expected)
            assert error.value.code == code
            assert box.get("served") is None  # refused before any probe was sent
            thread.join(5)
        finally:
            service.close()
        assert open_fds() == baseline


@pytest.mark.parametrize("field", ["uid", "gid"])
def test_the_reply_side_uid_gid_comparison_is_its_own_check(observed, field):
    # the peer agrees with the expectation, so only the worker's self-reported
    # runtime uid/gid can be what mismatches, after the first reply
    _root, _spec, side, peer, expected = observed
    observer = module()
    other = {"uid": UID, "gid": GID, field: (UID if field == "uid" else GID) + 1}
    peer["value"] = broker.PeerCredentials(pid=4242, uid=other["uid"], gid=other["gid"])
    wrong = observer.ExpectedStageIdentity(**{**expected.as_dict(), **other})
    baseline = open_fds()
    service = open_service()
    try:
        box = {}
        thread = serve_in_thread(service, box, side)
        with pytest.raises(observer.StagePostconditionError) as error:
            observe(wrong)
        assert error.value.code == "probe_mismatch"
        thread.join(5)
        assert box.get("served") == 1  # one reply was read and compared
    finally:
        service.close()
    assert open_fds() == baseline


def test_a_responder_boot_id_outside_hex64_is_invalid_after_the_handshake(observed):
    root, spec, side, _peer, expected = observed
    observer = module()
    # legal for the listener grammar, outside the evidence pin
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="worker-boot-xyz")
    box = {}

    def accept_once():
        side["worker_ident"] = threading.get_ident()
        try:
            connection = listener._accept_extension_authenticated(
                worker, deadline=broker.Deadline.after_ms(5_000)
            )
            box["connection"] = connection
            time.sleep(0.5)
            connection.close()
        except BaseException as exception:  # noqa: BLE001 - surfaced to the test thread
            box["error"] = exception

    thread = threading.Thread(target=accept_once, daemon=True)
    thread.start()
    try:
        with pytest.raises(observer.StagePostconditionError) as error:
            observe(expected)
        assert error.value.code == "probe_invalid"
    finally:
        thread.join(6)
        worker.close()


def test_no_listener_is_unavailable_and_a_silent_responder_is_bounded_by_the_attempt(
    observed,
):
    root, spec, side, _peer, expected = observed
    observer = module()
    baseline = open_fds()
    with pytest.raises(observer.StagePostconditionError) as error:
        observe(expected)
    assert error.value.code == "probe_unavailable"
    assert open_fds() == baseline
    # a responder that completes the handshake and never replies: the whole
    # attempt is bounded to 2000 ms from before connect whatever the deadline
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="a" * 64)
    box = {}

    def accept_and_hold():
        side["worker_ident"] = threading.get_ident()
        try:
            connection = listener._accept_extension_authenticated(
                worker, deadline=broker.Deadline.after_ms(5_000)
            )
            box["connection"] = connection
            time.sleep(3)
            connection.close()
        except BaseException as exception:  # noqa: BLE001 - surfaced to the test thread
            box["error"] = exception

    thread = threading.Thread(target=accept_and_hold, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(observer.StagePostconditionError) as error:
            observe(expected, deadline_ms=10_000)
        elapsed = time.monotonic() - started
        assert error.value.code == "probe_deadline"
        assert 1.5 <= elapsed < 3.0, elapsed
    finally:
        thread.join(6)
        worker.close()
    assert open_fds() == baseline
    # a responder that accepts the transport and never answers the hello is
    # the same exhausted attempt, one packet earlier: still the deadline
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="c" * 64)
    hold = {}

    def accept_transport_only():
        try:
            sock = worker._accept_transport(broker.Deadline.after_ms(5_000))
            hold["socket"] = sock
            time.sleep(3)
            sock.close()
        except BaseException as exception:  # noqa: BLE001 - surfaced to the test thread
            hold["error"] = exception

    thread = threading.Thread(target=accept_transport_only, daemon=True)
    thread.start()
    started = time.monotonic()
    try:
        with pytest.raises(observer.StagePostconditionError) as error:
            observe(expected, deadline_ms=10_000)
        elapsed = time.monotonic() - started
        assert error.value.code == "probe_deadline"
        assert 1.5 <= elapsed < 3.0, elapsed
    finally:
        thread.join(6)
        worker.close()
    assert open_fds() == baseline


@pytest.mark.parametrize(
    "shape",
    ["wrong_challenge", "wrong_correlation", "reply_id_is_request_id", "artifact_type",
     "garbage_frame"],
)
def test_a_malformed_or_miscorrelated_reply_is_invalid(observed, shape):
    # an authenticated worker that answers wrongly is invalid, never merely
    # "unavailable": the correlation rules of the contract are each exercised
    root, spec, side, _peer, expected = observed
    observer = module()
    baseline = open_fds()
    worker = listener.bind_worker_listener(root, spec, responder_boot_id="b" * 64)

    def respond_badly():
        side["worker_ident"] = threading.get_ident()
        connection = listener._accept_extension_authenticated(
            worker, deadline=broker.Deadline.after_ms(5_000)
        )
        try:
            frame = connection.read(deadline=broker.Deadline.after_ms(2_000))
            if shape == "garbage_frame":
                connection._socket.sendall(b"\x00\x00\x00\x05hello")
                time.sleep(0.5)
                return
            challenge = b"\x00" * 32 if shape == "wrong_challenge" else parse_challenge(frame)
            payload = encode_probe_reply(
                request_blob_sha256=hashlib.sha256(REQUEST_BYTES).hexdigest(),
                receipt_blob_sha256=hashlib.sha256(RECEIPT_BYTES).hexdigest(),
                challenge=challenge,
                service_identity=spec.responder_service,
                build_identity_digest=expected.build_identity_digest,
                port_contract_version="tool-port-v1",
                port_schema_set_digest=expected.port_schema_set_digest,
                platform="linux/amd64",
                uid=UID,
                gid=GID,
                registered_operations=(),
            )
            request_id = frame.envelope.message_id
            connection.write(
                message_id=request_id if shape == "reply_id_is_request_id" else str(uuid4()),
                correlation_id=str(uuid4()) if shape == "wrong_correlation" else request_id,
                message_type=(
                    "extension-artifact-v1" if shape == "artifact_type"
                    else "extension-result-v1"
                ),
                payload=payload,
                deadline=broker.Deadline.after_ms(2_000),
            )
        finally:
            connection.close()

    thread = threading.Thread(target=respond_badly, daemon=True)
    thread.start()
    try:
        with pytest.raises(observer.StagePostconditionError) as error:
            observe(expected)
        assert error.value.code == "probe_invalid"
    finally:
        thread.join(6)
        worker.close()
    assert open_fds() == baseline


def parse_challenge(frame):
    from app.workers.extension_probe_messages import parse_probe_request

    return parse_probe_request(frame.payload).challenge


@pytest.mark.parametrize(
    "change",
    [
        {"request_id": "00000000-0000-0000-0000-000000000000"},
        {"request_digest": "A" * 42 + "B"},
        {"receipt_digest": "not-b32"},
        {"request_bytes": b""},
        {"receipt_bytes": "text"},
        {"slot_number": 17},
        {"instance_id": "xyz"},
        {"expected": {"uid": 1}},
        {"deadline": 1000},
    ],
)
def test_invalid_inputs_are_refused_before_any_socket(observed, change):
    _root, _spec, _side, _peer, expected = observed
    observer = module()
    baseline = open_fds()
    with pytest.raises(observer.StagePostconditionError) as error:
        observe(expected, **change)
    assert error.value.code == "probe_invalid"
    assert open_fds() == baseline


def test_expected_identity_is_a_closed_frozen_value():
    observer = module()
    value = observer.ExpectedStageIdentity(
        service_identity="ext-0123456789abcdef0123456789abcdef-04",
        build_identity_digest="a" * 64,
        port_schema_set_digest="b" * 64,
        port_contract_version="tool-port-v1",
        platform="linux/amd64",
        uid=22004,
        gid=22004,
    )
    assert value.as_dict()["uid"] == 22004
    with pytest.raises((AttributeError, TypeError)):
        value.uid = 1
    for bad in (
        {"platform": "linux/riscv64"},
        {"uid": 0},
        {"build_identity_digest": "A" * 64},
        {"service_identity": "Ext"},
        {"port_contract_version": "tool-port-v2"},
    ):
        with pytest.raises(observer.StagePostconditionError) as error:
            observer.ExpectedStageIdentity(**{**value.as_dict(), **bad})
        assert error.value.code == "probe_invalid"


def test_fresh_observer_import_loads_no_api_static_server_or_service_modules():
    root = os.fspath(Path(__file__).resolve().parents[2])
    program = """
import sys
import app.deployment.stage_observer
forbidden = {
    'app.api', 'app.static', 'app.server',
    'app.deployment.prepare_service', 'app.services.owner_auth', 'app.api.deployment_prepare',
}
loaded = {name for name in sys.modules if name in forbidden or name.startswith(('app.api.', 'app.static.', 'app.server.'))}
assert not loaded, loaded
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        cwd=root,
        env={**os.environ, "PYTHONPATH": root, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
