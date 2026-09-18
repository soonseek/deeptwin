"""Task 25 slice 3: the worker probe service and the fixed image entrypoint
(contracts/extension-worker-probe.md §3–§5; T087 worker startup over the
T018-foundation transport).

`open_worker_probe_service(*, instance_id, slot_number)` opens the Task 23
metadata source before binding one listener under one fresh boot ID;
`serve_one(deadline)` accepts one authenticated probe connection, answers at
most two probes (distinct message ids and nonces, identical digest pair)
with replies built from an actual `read_current` each, rechecks every fence
before the first read and after each reply, and closes after the second
reply. The private router's semantic registry is empty: the reply says
`registered_operations=["status"]` since the T087 execute slice (see
test_extension_execute.py). `extension_worker.main()` parses only the fixed
argv and serves until stopped.

macOS honesty: the listener, source and fences run through the same seams
as the slice 2c and Task 23 tests (no peer credentials, no /proc, synthetic
mountinfo, a temporary fixed-file tree) — service and probe logic, never
positive Linux authentication, a real worker image or a container.
"""

import copy
import hashlib
import os
import pickle
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.deployment import mounts as m
from app.domain.refs import DomainContractError, uuid_string
from app.extensions.port_contracts import PORT_SCHEMA_SHAPES
from app.tests.test_extension_lineage_contracts import shipped_schema_bytes
from app.tests.test_extension_listener import (  # noqa: F401 - fixture re-export
    INSTANCE,
    channel,
    deadline,
    open_fds,
    seams,
)
from app.tests.test_extension_worker_metadata import (
    GID,
    UID,
    WORKER_BYTES,
    _identity_bytes,
    _write,
)
from app.workers import broker, extension_worker, listener
from app.workers import extension_metadata as em
from app.workers import extension_probe as ep
from app.workers.extension_probe_messages import (
    ProbeMessageError,
    encode_probe_request,
    parse_probe_reply,
)

SLOT = 4
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@pytest.fixture
def worker_tree(tmp_path_factory, monkeypatch):
    """The Task 23 fixed-file tree, placed outside the pair root (which must
    stay exactly the initializer's layout)."""

    root = tmp_path_factory.mktemp("ext") / "root"
    prefix = root / "opt" / "deeptwin-extension"
    identity_bytes = _identity_bytes(WORKER_BYTES)
    _write(prefix / "bin" / "worker", WORKER_BYTES, 0o555)
    _write(prefix / "identity" / "build-identity-v1.json", identity_bytes, 0o444)
    for role, raw in zip(PORT_SCHEMA_SHAPES, shipped_schema_bytes(), strict=True):
        _write(prefix / "ports" / "tool-port-v1" / f"{role}.schema.json", raw, 0o444)
    for directory in (
        root,
        root / "opt",
        prefix,
        prefix / "bin",
        prefix / "identity",
        prefix / "ports",
        prefix / "ports" / "tool-port-v1",
    ):
        directory.chmod(0o755)
    info = root.stat()
    device = f"{os.major(info.st_dev)}:{os.minor(info.st_dev)}"
    table = m.parse_mountinfo(
        f"1 1 {device} / {root} ro,relatime shared:1 - tmpfs tmpfs rw\n".encode()
    )
    monkeypatch.setattr(em, "EXTENSION_ROOT", root)
    monkeypatch.setattr(em, "EXTENSION_PREFIX", prefix)
    monkeypatch.setattr(em, "_expected_owner", lambda: (os.getuid(), os.getgid()))
    monkeypatch.setattr(em, "_native_platform", lambda: "linux/amd64")
    monkeypatch.setattr(em, "_credentials", lambda: (UID, UID, GID, GID))
    monkeypatch.setattr(em, "_read_mountinfo", lambda: table)
    return {
        "identity_digest": hashlib.sha256(identity_bytes).hexdigest(),
        "identity": prefix / "identity" / "build-identity-v1.json",
        "worker": prefix / "bin" / "worker",
    }


@pytest.fixture
def slot(channel, worker_tree, monkeypatch):  # noqa: F811 - the imported fixture
    """The service derives its channel from the slot; the test's pair root
    and pair group stand in for the fixed mount and identities."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)

    def derived(*, instance_id, slot_number):
        assert (instance_id, slot_number) == (INSTANCE, SLOT)
        return root, spec

    monkeypatch.setattr(ep, "extension_channel", derived)
    return root, spec, side, worker_tree


def open_service():
    return ep.open_worker_probe_service(instance_id=INSTANCE, slot_number=SLOT)


def serve_in_thread(service, box, side, *, deadline_ms=3_000):
    def body():
        side["worker_ident"] = threading.get_ident()
        try:
            box["served"] = service.serve_one(broker.Deadline.after_ms(deadline_ms))
        except BaseException as error:  # noqa: BLE001 - surfaced to the test thread
            box["error"] = error

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread


def connect(root, spec):
    return listener._connect_extension_authenticated(
        root, spec, requester_boot_id="control-boot-" + "c" * 20, deadline=deadline()
    )


def probe(client, *, request=DIGEST_A, receipt=DIGEST_A, challenge=None,
          message_id=None, correlation_id=None, message_type="extension-request-v1",
          payload=None):
    challenge = os.urandom(32) if challenge is None else challenge
    message_id = str(uuid4()) if message_id is None else message_id
    payload = (
        encode_probe_request(
            request_blob_sha256=request, receipt_blob_sha256=receipt, challenge=challenge
        )
        if payload is None
        else payload
    )
    client.write(
        message_id=message_id,
        correlation_id=correlation_id,
        message_type=message_type,
        payload=payload,
        deadline=deadline(),
    )
    return message_id, challenge


def test_service_opens_source_before_listener_and_answers_two_probes(slot, monkeypatch):
    root, spec, side, tree = slot
    order = []
    real_open = em.open_worker_metadata_source
    real_bind = listener.bind_worker_listener

    def spied_open():
        order.append("source")
        return real_open()

    def spied_bind(*args, **kwargs):
        order.append("listener")
        return real_bind(*args, **kwargs)

    monkeypatch.setattr(em, "open_worker_metadata_source", spied_open)
    monkeypatch.setattr(listener, "bind_worker_listener", spied_bind)
    baseline = open_fds()
    service = open_service()
    try:
        assert order == ["source", "listener"]
        assert type(service) is ep.WorkerProbeService and not service.closed
        record = service.listener.record
        assert len(record.responder_boot_id) == 64
        assert set(record.responder_boot_id) <= set("0123456789abcdef")
        reads = []
        real_read = em.WorkerMetadataSource.read_current

        def spied_read(self, *, deadline):
            reading = real_read(self, deadline=deadline)
            reads.append(reading)
            return reading

        monkeypatch.setattr(em.WorkerMetadataSource, "read_current", spied_read)
        box = {}
        thread = serve_in_thread(service, box, side)
        client = connect(root, spec)
        try:
            ids = []
            for _ in range(2):
                message_id, challenge = probe(client)
                frame = client.read(deadline=deadline())
                envelope = frame.envelope
                assert envelope.message_type == "extension-result-v1"
                assert envelope.correlation_id == message_id
                uuid_string(envelope.message_id)
                ids.extend((message_id, envelope.message_id))
                reply = parse_probe_reply(frame.payload)
                assert reply.challenge == challenge
                assert reply.request_blob_sha256 == reply.receipt_blob_sha256 == DIGEST_A
                assert reply.service_identity == spec.responder_service
                assert reply.component.build_identity_digest == tree["identity_digest"]
                assert reply.component.port_contract_version == "tool-port-v1"
                assert reply.runtime.platform == "linux/amd64"
                assert (reply.runtime.uid, reply.runtime.gid) == (UID, GID)
                # the code-owned registry carries `status` (T087 execute slice)
                assert reply.runtime.registered_operations == ("describe_tools", "invoke_tool", "status")
            assert len(set(ids)) == 4
            assert len(reads) == 2  # one actual read per probe, never readiness
            assert reply.component.port_schema_set_digest == (
                reads[1].build_identity.schema_set_digest
            )
            thread.join(5)
            assert not thread.is_alive()
            assert "error" not in box, box.get("error")
            assert box["served"] == 2
            # the worker closed after the second reply (a hung worker would
            # be a deadline, not a closed transport)
            with pytest.raises(broker.TransportClosed):
                client.read(deadline=broker.Deadline.after_ms(1_000))
        finally:
            client.close()
        assert not service.closed  # the service outlives its connections
    finally:
        service.close()
    assert service.closed
    assert open_fds() == baseline
    with pytest.raises(ep.ProbeServiceClosed):
        service.serve_one(deadline())
    service.close()  # idempotent


def test_a_requester_that_stops_after_one_probe_ends_the_connection_cleanly(slot):
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box = {}
        thread = serve_in_thread(service, box, side)
        client = connect(root, spec)
        probe(client)
        client.read(deadline=deadline())
        client.close()
        thread.join(5)
        assert "error" not in box, box.get("error")
        assert box["served"] == 1
        assert not service.closed
    finally:
        service.close()


@pytest.mark.parametrize(
    "violation",
    [
        "third_probe",
        "repeated_challenge",
        "different_digests",
        "artifact_type",
        "correlated_request",
        "nil_message_id",
        "duplicate_message_id",
        "malformed_payload",
        "oversized_payload",
        "reply_id_reused",
    ],
)
def test_per_connection_rule_violations_close_with_a_sanitized_error(slot, violation):
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box = {}
        thread = serve_in_thread(service, box, side)
        client = connect(root, spec)
        try:
            first_id, first_challenge = probe(client)
            first_reply = client.read(deadline=deadline())
            if violation == "third_probe":
                # the worker closes after its second reply: a third probe is
                # never read, so the requester's next read fails instead of
                # the service raising
                probe(client)
                client.read(deadline=deadline())
                thread.join(5)
                assert not thread.is_alive()
                assert "error" not in box and box["served"] == 2, box.get("error")
                try:
                    probe(client)  # the write may already see the closed peer
                except broker.BrokerError:
                    pass
                with pytest.raises(broker.TransportClosed):
                    client.read(deadline=broker.Deadline.after_ms(1_000))
                return
            elif violation == "repeated_challenge":
                probe(client, challenge=first_challenge)
            elif violation == "different_digests":
                probe(client, receipt=DIGEST_B)
            elif violation == "artifact_type":
                probe(client, message_type="extension-artifact-v1")
            elif violation == "correlated_request":
                probe(client, correlation_id=first_id)
            elif violation == "nil_message_id":
                probe(client, message_id="00000000-0000-0000-0000-000000000000")
            elif violation == "duplicate_message_id":
                probe(client, message_id=first_id)
            elif violation == "malformed_payload":
                probe(client, payload=b'{"schema_version":"extension-stage-probe-v1"}')
            elif violation == "oversized_payload":
                probe(client, payload=b"{" + b" " * 1_100 + b"}")
            else:
                # all four ids of a connection are distinct: a request may not
                # reuse the worker's own reply id either
                probe(client, message_id=first_reply.envelope.message_id)
            thread.join(5)
            assert not thread.is_alive()
            error = box.get("error")
            assert type(error) is ep.ProbeServiceError
            assert str(error) == "probe service error"
            assert DIGEST_A not in repr(error) and first_id not in repr(error)
            with pytest.raises(broker.TransportClosed):
                client.read(deadline=broker.Deadline.after_ms(1_000))
        finally:
            client.close()
        assert not service.closed  # a bad requester never poisons the service
    finally:
        service.close()


def test_a_drifted_fixed_file_between_probes_poisons_and_closes_the_service(slot):
    root, spec, side, tree = slot
    baseline = open_fds()
    service = open_service()
    box = {}
    thread = serve_in_thread(service, box, side)
    client = connect(root, spec)
    try:
        probe(client)
        client.read(deadline=deadline())
        tree["identity"].chmod(0o644)  # a mode drift is integrity, not a reread
        probe(client)
        thread.join(5)
        assert type(box.get("error")) is ep.ProbeServiceError
        assert service.closed  # the poisoned source takes the service with it
        with pytest.raises(broker.TransportClosed):
            client.read(deadline=broker.Deadline.after_ms(1_000))
    finally:
        client.close()
        service.close()
    assert open_fds() == baseline  # the self-close released every descriptor


def test_a_listener_whose_record_is_gone_closes_the_service(slot):
    # the listener's own fences fail before the transport accept; a worker
    # listener cannot be re-bound, so the service must close rather than let
    # the entrypoint spin on an instant failure forever
    root, _spec, side, _tree = slot
    baseline = open_fds()
    service = open_service()
    try:
        (root.endpoint_path / "listener.json").unlink()
        started = time.monotonic()
        with pytest.raises(ep.ProbeServiceError):
            side["worker_ident"] = threading.get_ident()
            service.serve_one(broker.Deadline.after_ms(5_000))
        assert time.monotonic() - started < 1.0
        assert service.closed
    finally:
        try:
            service.close()
        except ep.ProbeServiceError:
            pass
    assert open_fds() == baseline


def test_a_transport_only_requester_is_bounded_by_the_connection_window(slot):
    # the 2000 ms accepted-connection window starts at the transport accept
    # and covers the handshake too, whatever the accept deadline was
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box = {}
        thread = serve_in_thread(service, box, side, deadline_ms=10_000)
        raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            started = time.monotonic()
            raw.connect(listener._anchored_socket_path(-1, root, spec.socket_name))
            thread.join(8)
            elapsed = time.monotonic() - started
            assert not thread.is_alive()
            assert 1.5 <= elapsed < 3.0, elapsed
            assert type(box.get("error")) is ep.ProbeServiceError
        finally:
            raw.close()
        assert not service.closed
    finally:
        service.close()


def test_a_silent_requester_is_bounded_by_the_connection_deadline(slot):
    root, spec, side, _tree = slot
    service = open_service()
    try:
        box = {}
        started = time.monotonic()
        thread = serve_in_thread(service, box, side, deadline_ms=10_000)
        client = connect(root, spec)
        try:
            thread.join(8)
            assert not thread.is_alive()
            elapsed = time.monotonic() - started
            assert 1.5 <= elapsed < 3.0, elapsed  # the 2000 ms window, not 10 s
            assert type(box.get("error")) is ep.ProbeServiceError
        finally:
            client.close()
        assert not service.closed
    finally:
        service.close()


def test_overlapping_serve_or_close_is_busy_and_wrong_deadlines_are_refused(slot):
    root, spec, side, _tree = slot
    service = open_service()
    try:
        with pytest.raises(ep.ProbeServiceError):
            service.serve_one("soon")
        box = {}
        thread = serve_in_thread(service, box, side)
        time.sleep(0.2)  # the accept is now blocking inside serve_one
        with pytest.raises(ep.ProbeServiceBusy):
            service.serve_one(deadline())
        with pytest.raises(ep.ProbeServiceBusy):
            service.close()
        client = connect(root, spec)
        client.close()
        thread.join(5)
        assert not thread.is_alive()
    finally:
        service.close()
    assert service.closed


def test_service_is_nonconstructible_uncopyable_and_errors_are_closed(slot):
    service = open_service()
    try:
        with pytest.raises(TypeError):
            ep.WorkerProbeService()
        for clone in (copy.copy, copy.deepcopy, pickle.dumps):
            with pytest.raises(TypeError):
                clone(service)
        assert repr(service) == "WorkerProbeService(closed=False)"
        with pytest.raises(AttributeError):
            service.listener = None  # the owned listener sources service_identity
    finally:
        service.close()
    # __exit__ never replaces a propagating exception with its own
    with pytest.raises(KeyError), open_service() as inner:
        inner._lock.acquire()  # close() would report busy
        raise KeyError("body")
    inner._lock.release()
    inner.close()
    for kind, code in (
        (ep.ProbeServiceError, "probe service error"),
        (ep.ProbeServiceBusy, "probe service busy"),
        (ep.ProbeServiceClosed, "probe service closed"),
    ):
        assert str(kind()) == code and str(kind("secret")) == code
        assert issubclass(kind, ep.ProbeServiceError)


def test_open_failure_after_the_source_releases_every_descriptor(slot, monkeypatch):
    baseline = open_fds()

    def refused(*args, **kwargs):
        raise listener.ListenerIntegrityError()

    monkeypatch.setattr(listener, "bind_worker_listener", refused)
    with pytest.raises(ep.ProbeServiceError):
        open_service()
    assert open_fds() == baseline


def test_registry_is_code_owned_and_private(slot):
    router = ep._Router()
    assert router.operations() == ("describe_tools", "invoke_tool", "status")  # the T087 execute slices' operations
    assert not hasattr(router, "register")
    with pytest.raises(TypeError):
        pickle.dumps(router)


def test_descriptor_budget_is_enumerated_and_within_sixty_four(slot, monkeypatch):
    root, spec, side, _tree = slot
    baseline = open_fds()
    service = open_service()
    try:
        retained = len(open_fds() - baseline)
        peak = {"fds": 0}
        real = em._read_bounded

        def sampled(fd, cap, deadline):
            peak["fds"] = max(peak["fds"], len(open_fds() - baseline))
            return real(fd, cap, deadline)

        monkeypatch.setattr(em, "_read_bounded", sampled)
        box = {}
        thread = serve_in_thread(service, box, side)
        client = connect(root, spec)
        try:
            probe(client)
            client.read(deadline=deadline())
            probe(client)
            client.read(deadline=deadline())
            thread.join(5)
        finally:
            client.close()
        assert box.get("served") == 2, box.get("error")
    finally:
        service.close()
    assert open_fds() == baseline
    # enumerated: 13 retained by the source; the listener's generation lease
    # (pair root, endpoint, generation lock: 3), its endpoint, listener lock
    # and listening socket (3). A served connection adds the accepted socket
    # (1), the re-acquired generation (3), the populated fence's boot-secret
    # descriptor (1) and the read's transient descriptors (7 directories +
    # 6 leaves = 13; the source's own bound is 32). The sample is process
    # wide, so it also counts the requester living in this same process:
    # its connected socket (1), its verified generation (3) and fence (1)
    worker_retained = 13 + 3 + 3
    worker_connection = 1 + 3 + 1
    read_transient = 7 + 6
    requester_in_process = 1 + 3 + 1
    assert retained == worker_retained, retained
    assert peak["fds"] == (
        worker_retained + worker_connection + read_transient + requester_in_process
    ), peak
    assert worker_retained + worker_connection + 32 <= 64  # the contract's worst case


def test_workers_import_nothing_from_the_api_static_or_server_packages():
    # a fresh interpreter: what these two modules pull in, and nothing else
    program = (
        "import sys; import app.workers.extension_probe, app.workers.extension_worker; "
        "print(sorted(n for n in sys.modules "
        "if n.startswith(('app.api', 'app.static', 'app.server'))))"
    )
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        capture_output=True,
        text=True,
        check=True,
        cwd=Path(ep.__file__).resolve().parents[2],
        timeout=60,
    )
    assert result.stdout.strip() == "[]"


def test_main_refuses_argv_before_opening_anything(monkeypatch):
    def never(**_kwargs):
        raise AssertionError("no service may open for an invalid argv")

    monkeypatch.setattr(extension_worker, "open_worker_probe_service", never)
    assert extension_worker.main(["worker", "--instance-id", "x", "--slot-number", "4"]) == 2
    assert extension_worker.main(["worker"]) == 2
    assert extension_worker.main("worker --instance-id x") == 2


def test_main_serves_until_stopped_and_exits_nonzero_when_poisoned(monkeypatch):
    calls = []

    class Fake:
        closed = False

        def serve_one(self, deadline):
            assert type(deadline) is broker.Deadline
            calls.append("serve")
            if len(calls) == 1:
                raise ep.ProbeServiceError()  # one bad requester: keep serving
            if len(calls) == 2:
                extension_worker._request_stop()
                return 2
            raise AssertionError("served after stop")

        def close(self):
            calls.append("close")
            self.closed = True

    opened = []

    def fake_open(*, instance_id, slot_number):
        opened.append((instance_id, slot_number))
        return Fake()

    monkeypatch.setattr(extension_worker, "open_worker_probe_service", fake_open)
    argv = ["worker", "--instance-id", INSTANCE, "--slot-number", "4"]
    assert extension_worker.main(argv) == 0
    assert opened == [(INSTANCE, 4)]
    assert calls == ["serve", "serve", "close"]

    class Poisoned(Fake):
        def serve_one(self, deadline):
            self.closed = True
            raise ep.ProbeServiceError()

    monkeypatch.setattr(extension_worker, "open_worker_probe_service", lambda **_k: Poisoned())
    assert extension_worker.main(argv) == 1

    def cannot_open(**_kwargs):
        raise ep.ProbeServiceError()

    monkeypatch.setattr(extension_worker, "open_worker_probe_service", cannot_open)
    assert extension_worker.main(argv) == 1


def test_main_leaves_a_blocking_accept_at_once_on_sigterm(monkeypatch):
    # the accept retries after EINTR, so a handler that only sets a flag is
    # honoured at the accept deadline (30 s in the image, longer than a
    # container stop grace); the stop must interrupt the wait itself
    calls = []

    class Blocking:
        closed = False

        def serve_one(self, deadline):
            calls.append("serve")
            time.sleep(5)  # stands in for the blocking accept
            raise AssertionError("the wait was not interrupted")

        def close(self):
            calls.append("close")
            self.closed = True

    monkeypatch.setattr(
        extension_worker, "open_worker_probe_service", lambda **_k: Blocking()
    )
    previous = signal.getsignal(signal.SIGTERM)
    timer = threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM))
    timer.start()
    started = time.monotonic()
    try:
        argv = ["worker", "--instance-id", INSTANCE, "--slot-number", "4"]
        assert extension_worker.main(argv) == 0
    finally:
        timer.cancel()
    assert time.monotonic() - started < 2.0
    assert calls == ["serve", "close"]
    assert signal.getsignal(signal.SIGTERM) is previous  # restored


def test_probe_request_grammar_is_the_codec_grammar():
    with pytest.raises(ProbeMessageError):
        encode_probe_request(request_blob_sha256="x", receipt_blob_sha256=DIGEST_A, challenge=b"1" * 32)
    with pytest.raises(DomainContractError):
        uuid_string("00000000-0000-0000-0000-000000000000")
