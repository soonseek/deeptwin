"""Conditional local proof for semantic dialogues over owned extension frames.

The ``channel`` fixture intentionally substitutes only the macOS-only surfaces
documented by the adopted Task49 contract: temporary identities/root, a
fixture-owned socket alias, handshake peer verification, verified connect, and
mountinfo sampling.  Generation retention, readiness HMACs, authenticated frame
MAC/sequence validation, real sockets, owner issuance, and filesystem fences stay
real.  These tests are not Linux/native qualification or production activation.
"""

import json
import threading
import time
import types
from uuid import uuid4

import pytest

from app.tests.support.provider_semantic_harness import (
    canonical_provider_config,
    immutable_ref,
    owned_semantic_service,
)
from app.tests.test_provider_semantic_codec import page, valid_stream
from app.tests.test_extension_listener import (
    INSTANCE,
    channel,
    mountinfo,
    open_fds,
    seams,
)
from app.tests.test_provider_semantic_worker import request
from app.workers import broker, listener, provider_port_client as port_client
from app.workers import provider_port_service as port_service
from app.workers.provider_port_client import ProviderPortClient
from app.workers.provider_port_service import ProviderPortService
from app.workers.artifact_stream import StreamCancelled
from app.extensions.provider_semantic_contracts import ProviderSemanticError


def _authority():
    identity = {
        "qualification_ref": immutable_ref(digest="2"),
        "binding_revision_ref": immutable_ref(digest="3"),
        "egress_policy_ref": immutable_ref(digest="8"),
    }
    return immutable_ref(digest="9"), canonical_provider_config(
        immutable_ref(digest="a"), identity=identity
    )


def _model_request():
    return request(
        "model_step",
        {
            "frozen_turn_ref": immutable_ref("frozen_turn", "b"),
            "model_id": "model-1",
            "effort": None,
            "requested_modalities": ["text"],
            "tool_definition_refs": [],
            "response_schema_ref": None,
        },
    )


def _frozen_turn():
    return {
        "turn": {"model_id": "model-1"},
        "max_output_tokens": 8,
        "messages": [{"role": "user", "input_ordinals": [0]}],
    }


def test_owned_capabilities_preserves_whole_connection(channel, monkeypatch):
    root, spec = channel
    side = seams(monkeypatch, root, spec)
    baseline = open_fds()

    def resolve_slot(*, instance_id, slot_number):
        assert instance_id == INSTANCE and slot_number == 4
        return root, spec

    monkeypatch.setattr(port_client, "extension_channel", resolve_slot)
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="owned-worker"
    )
    box = {}

    def serve():
        side["worker_ident"] = threading.get_ident()
        try:
            owned = listener._accept_extension_authenticated(
                worker, deadline=broker.Deadline.after_ms(3000)
            )
            box["owner"] = owned
            ProviderPortService().serve_connection(owned, deadline=owned.deadline)
        except BaseException as error:  # noqa: BLE001 - surfaced in test thread
            box["error"] = error

    thread = threading.Thread(target=serve, daemon=False)
    thread.start()
    client = None
    try:
        operation_ref, config = _authority()
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        result = client.execute(
            request("capabilities", {}), operation_ref=operation_ref, config=config
        )
        assert result["terminal"] == "succeeded"
        assert result["output"] == {
            "modalities": ["text"],
            "tool_calling": False,
            "usage_reporting": True,
            "cancellation": True,
        }
        assert result["artifacts"] == []
    finally:
        try:
            if client is not None:
                client.abandon()
        finally:
            thread.join(5)
            worker.close()
    assert not thread.is_alive()
    assert "error" not in box, box.get("error")
    assert type(box["owner"]) is listener.ExtensionConnection
    assert box["owner"].closed
    assert open_fds() == baseline


def test_owned_all_five_operations_cross_real_owner_frames(channel, monkeypatch):
    """Conditional local owned-frame proof, not native/platform qualification."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    baseline = open_fds()

    def resolve_slot(*, instance_id, slot_number):
        assert instance_id == INSTANCE and slot_number == 4
        return root, spec

    monkeypatch.setattr(port_client, "extension_channel", resolve_slot)
    crossings = []
    original_write = listener.ExtensionConnection.write
    original_read = listener.ExtensionConnection.read_duplex

    def write_spy(owner, **values):
        crossings.append(("write", owner._read_only, values["message_type"]))
        return original_write(owner, **values)

    def read_spy(owner, *, deadline):
        crossings.append(("read", owner._read_only, None))
        return original_read(owner, deadline=deadline)

    monkeypatch.setattr(listener.ExtensionConnection, "write", write_spy)
    monkeypatch.setattr(listener.ExtensionConnection, "read_duplex", read_spy)
    operation_ref, config = _authority()

    def new_client():
        return ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )

    with owned_semantic_service(root, spec, side) as box:
        client = new_client()
        result = client.execute(
            request("capabilities", {}), operation_ref=operation_ref, config=config
        )
        assert result["terminal"] == "succeeded"
    assert "error" not in box, box.get("error")
    assert box["owner"].closed

    with owned_semantic_service(root, spec, side) as box:
        client = new_client()
        catalog_request = request("catalog", {"catalog_epoch": None})
        proposal = client.begin(
            catalog_request, operation_ref=operation_ref, config=config
        )
        next_proposal = client.observe(
            proposal,
            status=200,
            raw=page(["owned-model-1"], more=True),
            exchange_id=str(uuid4()),
        )
        assert next_proposal.after_id == "owned-model-1"
        catalog = client.observe(
            next_proposal,
            status=200,
            raw=page(["owned-model-2"]),
            exchange_id=str(uuid4()),
        )
        assert catalog.complete
        assert catalog.model_ids == ("owned-model-1", "owned-model-2")
    assert "error" not in box, box.get("error")
    assert box["owner"].closed

    frozen = _frozen_turn()
    model_request = _model_request()
    with owned_semantic_service(root, spec, side) as box:
        client = new_client()
        proposal = client.begin(
            model_request,
            frozen_content=frozen,
            input_bytes=(b"owned input",),
            operation_ref=operation_ref,
            config=config,
        )
        assert json.loads(proposal.body)["messages"][0]["content"] == [
            {"type": "text", "text": "owned input"}
        ]
        try:
            model = client.observe(
                proposal,
                status=200,
                raw=valid_stream("owned output"),
                exchange_id=str(uuid4()),
            )
        except BaseException as error:  # noqa: BLE001 - include peer failure
            raise AssertionError(box.get("error")) from error
        assert model.text_blocks == (b"owned output",)
        assert model.usage == {
            "input_tokens": {"state": "value", "value": 3},
            "output_tokens": {"state": "value", "value": 2},
            "cache_creation_input_tokens": {"state": "absent", "value": None},
            "cache_read_input_tokens": {"state": "absent", "value": None},
            "cache_creation": {"state": "absent", "value": None},
            "output_tokens_details": {"state": "absent", "value": None},
            "server_tool_use": {"state": "absent", "value": None},
            "inference_geo": {"state": "absent", "value": None},
            "service_tier": {"state": "absent", "value": None},
            "unknown_categories": [],
            "cache_zero_basis": "request_omits_cache_and_tools",
            "currency_cost_known": False,
        }
    assert "error" not in box, box.get("error")
    assert box["owner"].closed

    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    with owned_semantic_service(root, spec, side) as box:
        status = new_client().execute(
            request("status", {"operation_ref": target}),
            query_state=query,
            operation_ref=operation_ref,
            config=config,
        )
        assert status["output"]["observed_state"] == "running"
    assert "error" not in box, box.get("error")

    with owned_semantic_service(root, spec, side) as box:
        cancel = new_client().execute(
            request(
                "cancel",
                {"operation_ref": target, "reason_class": "user_requested"},
            ),
            query_state=query,
            operation_ref=operation_ref,
            config=config,
        )
        assert cancel["output"]["cancel_state"] == "accepted"
    assert "error" not in box, box.get("error")
    assert {item[1] for item in crossings} == {False, True}
    assert {item[0] for item in crossings} == {"read", "write"}
    assert all(box.get("owner") is None or box["owner"].closed for box in [box])
    assert open_fds() == baseline


@pytest.mark.parametrize("waiter_schedule", ["before_close", "after_close"])
def test_owned_cancel_waiter_consumes_committed_ack_across_reader_close(
    channel, monkeypatch, waiter_schedule
):
    """Committed cancel ACK is stable whether waiter runs before or after close."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    published = threading.Event()
    release_reader_close = threading.Event()
    release_waiter = threading.Event()
    reader_closed = threading.Event()
    real_event = threading.Event
    client_close_failures = []
    original_owner_close = listener.ExtensionConnection.close

    def fail_after_detached_client_close(owner):
        was_closed = owner.closed
        original_owner_close(owner)
        if owner._read_only and not was_closed:
            client_close_failures.append(owner)
            raise OSError("injected separate-reader cleanup failure")

    monkeypatch.setattr(
        listener.ExtensionConnection, "close", fail_after_detached_client_close
    )

    class ScheduledEvent:
        def __init__(self):
            self._event = real_event()

        def set(self):
            self._event.set()
            published.set()

        def is_set(self):
            return self._event.is_set()

        def wait(self, timeout=None):
            if not self._event.wait(timeout):
                return False
            if waiter_schedule == "after_close":
                return release_waiter.wait(timeout)
            return True

    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"cancel me",),
            operation_ref=operation_ref,
            config=config,
        )
        channel_state = client._channel
        reader_entered = threading.Event()
        reader_errors = []

        def reader():
            channel_state["owner_lock"].acquire()
            reader_entered.set()
            try:
                client._read_owned(channel_state, cancel_owner=True)
            except BaseException as error:  # noqa: BLE001 - exact primary asserted
                reader_errors.append(error)
                if waiter_schedule == "before_close":
                    assert release_reader_close.wait(2)
            finally:
                try:
                    client._close(channel_state)
                except BaseException:  # cleanup cannot replace reader primary
                    pass
                client._channel = None
                channel_state["owner_lock"].release()
                reader_closed.set()

        reader_thread = threading.Thread(target=reader, daemon=False)
        reader_thread.start()
        assert reader_entered.wait(1)
        monkeypatch.setattr(
            port_client,
            "threading",
            types.SimpleNamespace(
                Event=ScheduledEvent,
                Lock=threading.Lock,
                RLock=threading.RLock,
            ),
        )
        control_result = []
        control_errors = []

        def control():
            try:
                control_result.append(
                    client.control(
                        request(
                            "cancel",
                            {
                                "operation_ref": target,
                                "reason_class": "user_requested",
                            },
                        ),
                        query_state=query,
                    )
                )
            except BaseException as error:  # noqa: BLE001 - surfaced below
                control_errors.append(error)

        controller = threading.Thread(target=control, daemon=False)
        controller.start()
        assert published.wait(2)
        if waiter_schedule == "before_close":
            controller.join(2)
            assert not controller.is_alive()
            assert not reader_closed.is_set()
            release_reader_close.set()
        else:
            assert reader_closed.wait(2)
            release_waiter.set()
        reader_thread.join(2)
        controller.join(2)
        assert not reader_thread.is_alive() and not controller.is_alive()
        assert len(reader_errors) == 1
        assert type(reader_errors[0]) is StreamCancelled
        assert control_errors == []
        assert control_result[0]["output"]["cancel_state"] == "accepted"
        assert channel_state["connection"].owner.closed
        assert client_close_failures == [channel_state["connection"].owner]
        assert all(
            getattr(channel_state["connection"].owner, name) is None
            for name in ("_fence", "_codec", "_socket", "_generation")
        )
    assert "error" not in box, box.get("error")


def test_owned_text_cancel_authenticates_ack_before_closed_peer_stream_credit(
    channel, monkeypatch
):
    """A queued accepted ACK wins over credit to the already-closing sender."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    timeline = []
    reached = threading.Event()
    release = threading.Event()
    control_written = threading.Event()
    ack_written = threading.Event()
    server_closed = threading.Event()

    original_codec_write = broker.FrameCodec.write

    def trace_frame(codec, *args, **kwargs):
        payload = kwargs.get("payload", b"")
        result = original_codec_write(codec, *args, **kwargs)
        if b'"schema":"provider-semantic-control-v1"' in payload:
            timeline.append("control_wire")
            control_written.set()
        elif b'"schema":"provider-semantic-control-result-v1"' in payload:
            timeline.append("ack_wire")
            ack_written.set()
        elif reached.is_set() and b'"type":"artifact-credit"' in payload:
            timeline.append("credit_wire_after_ack")
        return result

    monkeypatch.setattr(broker.FrameCodec, "write", trace_frame)
    original_close = listener.ExtensionConnection.close

    def trace_close(owner):
        result = original_close(owner)
        if not owner._read_only:
            timeline.append("server_closed")
            server_closed.set()
        return result

    monkeypatch.setattr(listener.ExtensionConnection, "close", trace_close)

    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        proposal = client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"cancel during text",),
            operation_ref=operation_ref,
            config=config,
        )
        original_service_send = port_service._WorkerServiceStreamTransport.send
        offers = []

        def hold_text_offer(transport, payload):
            if b'"type":"artifact-offer"' in payload:
                offers.append(True)
                if len(offers) == 2:
                    reached.set()
                    assert release.wait(2)
            return original_service_send(transport, payload)

        monkeypatch.setattr(
            port_service._WorkerServiceStreamTransport,
            "send",
            hold_text_offer,
        )
        original_client_send = port_client._WorkerClientStreamTransport.send

        def hold_credit_until_peer_closes(transport, payload):
            if reached.is_set() and b'"type":"artifact-credit"' in payload:
                assert ack_written.wait(2)
                assert server_closed.wait(2)
                timeline.append("credit_attempt_after_close")
            return original_client_send(transport, payload)

        monkeypatch.setattr(
            port_client._WorkerClientStreamTransport,
            "send",
            hold_credit_until_peer_closes,
        )
        work_errors = []

        def observe():
            try:
                client.observe(
                    proposal,
                    status=200,
                    raw=valid_stream("cancelled output"),
                    exchange_id=str(uuid4()),
                )
            except BaseException as error:  # noqa: BLE001 - exact type below
                work_errors.append(error)

        worker = threading.Thread(target=observe, daemon=False)
        worker.start()
        assert reached.wait(2)
        control_results = []
        control_errors = []

        def control():
            try:
                control_results.append(
                    client.control(
                        request(
                            "cancel",
                            {
                                "operation_ref": target,
                                "reason_class": "user_requested",
                            },
                        ),
                        query_state=query,
                    )
                )
            except BaseException as error:  # noqa: BLE001 - surfaced below
                control_errors.append(error)

        controller = threading.Thread(target=control, daemon=False)
        controller.start()
        assert control_written.wait(2)
        release.set()
        worker.join(3)
        controller.join(3)
        assert not worker.is_alive() and not controller.is_alive()
        assert len(work_errors) == 1 and type(work_errors[0]) is StreamCancelled
        assert control_errors == []
        assert control_results[0]["output"]["cancel_state"] == "accepted"
        assert timeline.index("control_wire") < timeline.index("ack_wire")
        assert timeline.index("ack_wire") < timeline.index("server_closed")
        assert timeline.index("server_closed") < timeline.index(
            "credit_attempt_after_close"
        )
        assert "credit_wire_after_ack" not in timeline
        assert client._channel is None
    assert "error" not in box, box.get("error")


def test_owned_cancel_cannot_enter_after_settlement_before_artifact_write(
    channel, monkeypatch
):
    """The control publication/write order closes the post-settlement gap."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    settled_without_pending = threading.Event()
    release_artifact_write = threading.Event()
    lock_classified = threading.Event()
    server_closed = threading.Event()
    controller_ident = {}
    controller_lock_mode = []
    timeline = []
    original_close = listener.ExtensionConnection.close

    def trace_close(owner):
        result = original_close(owner)
        if not owner._read_only:
            timeline.append("server_closed")
            server_closed.set()
        return result

    monkeypatch.setattr(listener.ExtensionConnection, "close", trace_close)

    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        proposal = client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"cancel in settlement gap",),
            operation_ref=operation_ref,
            config=config,
        )
        channel_state = client._channel
        real_write_lock = channel_state["write_lock"]

        class ClassifiedWriteLock:
            def acquire(self, *, blocking=True, timeout=-1):
                if threading.get_ident() == controller_ident.get("value"):
                    if real_write_lock.acquire(blocking=False):
                        controller_lock_mode.append("acquired")
                        lock_classified.set()
                        return True
                    controller_lock_mode.append("blocked")
                    lock_classified.set()
                if not blocking:
                    return real_write_lock.acquire(blocking=False)
                return real_write_lock.acquire(timeout=timeout)

            def release(self):
                real_write_lock.release()

        channel_state["write_lock"] = ClassifiedWriteLock()
        original_stream_send = port_client._WorkerClientStreamTransport.send
        original_settle = client._settle_control_before_stream_write
        credits = []
        target_credit = {"active": False}

        def identify_text_credit(transport, payload):
            if b'"type":"artifact-credit"' in payload:
                credits.append(True)
                target_credit["active"] = len(credits) == 2
            try:
                return original_stream_send(transport, payload)
            finally:
                target_credit["active"] = False

        def pause_after_real_settlement(current):
            result = original_settle(current)
            if target_credit["active"]:
                assert current["pending_control"] is None
                timeline.append("settle_saw_no_pending")
                settled_without_pending.set()
                assert release_artifact_write.wait(2)
                timeline.append("artifact_write_resumes")
            return result

        monkeypatch.setattr(
            port_client._WorkerClientStreamTransport,
            "send",
            identify_text_credit,
        )
        monkeypatch.setattr(
            client, "_settle_control_before_stream_write", pause_after_real_settlement
        )
        reader_errors = []

        def observe():
            try:
                client.observe(
                    proposal,
                    status=200,
                    raw=valid_stream("gap-cancelled output"),
                    exchange_id=str(uuid4()),
                )
            except BaseException as error:  # noqa: BLE001 - exact type below
                reader_errors.append(error)

        reader = threading.Thread(target=observe, daemon=False)
        reader.start()
        assert settled_without_pending.wait(2)
        control_results = []
        control_errors = []

        def control():
            controller_ident["value"] = threading.get_ident()
            try:
                control_results.append(
                    client.control(
                        request(
                            "cancel",
                            {
                                "operation_ref": target,
                                "reason_class": "user_requested",
                            },
                        ),
                        query_state=query,
                    )
                )
            except BaseException as error:  # noqa: BLE001 - surfaced below
                control_errors.append(error)

        controller = threading.Thread(target=control, daemon=False)
        controller.start()
        assert lock_classified.wait(2)
        if controller_lock_mode == ["acquired"]:
            assert server_closed.wait(2)
        release_artifact_write.set()
        reader.join(3)
        controller.join(3)
        assert not reader.is_alive() and not controller.is_alive()
        assert controller_lock_mode == ["blocked"], timeline
        assert len(reader_errors) == 1 and type(reader_errors[0]) is StreamCancelled
        assert control_errors == []
        assert control_results[0]["output"]["cancel_state"] == "accepted"
        assert timeline.index("settle_saw_no_pending") < timeline.index(
            "artifact_write_resumes"
        )
        assert timeline.index("artifact_write_resumes") < timeline.index(
            "server_closed"
        )
        assert client._channel is None
    assert "error" not in box, box.get("error")


def test_owned_observe_lock_expiry_closes_before_return(channel, monkeypatch):
    """Observe owns cleanup even when owner-lock acquisition itself expires."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        proposal = client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"expire before observe lock",),
            operation_ref=operation_ref,
            config=config,
        )
        channel_state = client._channel
        owner = channel_state["connection"].owner
        expired = broker.Deadline(1.0)
        channel_state["deadline"] = expired
        channel_state["connection"].deadline = expired
        with pytest.raises(broker.DeadlineExceeded):
            client.observe(
                proposal,
                status=200,
                raw=valid_stream("must not publish"),
                exchange_id=str(uuid4()),
            )
        closed_at_return = owner.closed
        channel_at_return = client._channel
        client.abandon()
        assert closed_at_return
        assert channel_at_return is None
    assert box.get("error") is None


@pytest.mark.parametrize("unsolicited_count", [2, 6])
def test_control_stream_deferral_is_ordered_and_finitely_bounded(
    monkeypatch, unsolicited_count
):
    """Only one credit window plus terminal may precede a control ACK."""

    client = ProviderPortClient(service=ProviderPortService())
    pending = {"event": threading.Event(), "outcome": None}
    frames = [object() for _ in range(unsolicited_count)]
    remaining = list(frames)

    def read_owned(_channel, **kwargs):
        assert kwargs["wire_only"] is True
        if remaining:
            return remaining.pop(0)
        pending["outcome"] = ("observation", {"operation": "status"})
        pending["event"].set()
        return None

    monkeypatch.setattr(client, "_read_owned", read_owned)
    existing = object()
    channel_state = {
        "state_lock": threading.Lock(),
        "deadline": broker.Deadline.after_ms(500),
        "pending_control": pending,
        "deferred_frames": [existing],
    }
    available = port_client._MAX_DEFERRED_STREAM_FRAMES - 1
    if unsolicited_count <= available:
        client._settle_control_before_stream_write(channel_state)
        assert channel_state["deferred_frames"] == [existing, *frames]
    else:
        with pytest.raises(
            ProviderSemanticError,
            match="semantic stream exceeded control deferral bound",
        ):
            client._settle_control_before_stream_write(channel_state)
        assert channel_state["deferred_frames"] == [existing, *frames[:available]]
        assert not pending["event"].is_set()


@pytest.mark.parametrize("failing_resources", [("fence",), ("fence", "codec")])
def test_owned_self_reader_surfaces_cleanup_failure_after_observation(
    channel, monkeypatch, failing_resources
):
    """Self-reader reports local post-ACK cleanup failure immediately, once."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"cancel me",),
            operation_ref=operation_ref,
            config=config,
        )
        owner = client._channel["connection"].owner
        retained = {
            "fence": owner._fence,
            "codec": owner._codec,
            "socket": owner._socket,
            "generation": owner._generation,
        }
        attempts = []
        fence_type = type(retained["fence"])
        original_fence_close = fence_type.close
        original_codec_close = broker.FrameCodec.close

        def injected_fence_close(fence):
            if fence is retained["fence"]:
                attempts.append("fence")
                original_fence_close(fence)
                if "fence" in failing_resources:
                    raise OSError("injected first cleanup failure")
                return None
            return original_fence_close(fence)

        def injected_codec_close(codec):
            if codec is retained["codec"]:
                attempts.append("codec")
                original_codec_close(codec)
                if "codec" in failing_resources:
                    raise OSError("injected second cleanup failure")
                return None
            return original_codec_close(codec)

        monkeypatch.setattr(fence_type, "close", injected_fence_close)
        monkeypatch.setattr(broker.FrameCodec, "close", injected_codec_close)
        with pytest.raises(port_client._OwnedConnectionError) as caught:
            client.control(
                request(
                    "cancel",
                    {
                        "operation_ref": target,
                        "reason_class": "user_requested",
                    },
                ),
                query_state=query,
            )
        assert (
            caught.value.code
            == "owned_connection_cleanup_failed_after_control_observation"
        )
        assert attempts == ["fence", "codec"]
        assert owner.closed
        assert all(
            getattr(owner, name) is None
            for name in ("_fence", "_codec", "_socket", "_generation")
        )
        assert retained["fence"].closed
        assert retained["codec"].closed
        assert retained["socket"].fileno() == -1
        assert retained["generation"].closed
        client.abandon()
    assert "error" not in box, box.get("error")


@pytest.mark.parametrize("failure", ["payload", "post_frame_fence", "deadline"])
def test_owned_control_prepublication_failure_wakes_waiter_without_success(
    channel, monkeypatch, failure
):
    """Authenticated control failure before commit cannot publish an ACK."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    original_read_mountinfo = listener._read_mountinfo
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"cancel me",),
            operation_ref=operation_ref,
            config=config,
        )
        channel_state = client._channel
        client_owner = channel_state["connection"].owner
        if failure == "payload":
            original_encode = port_service.encode_op

            def malformed_control_result(value):
                if (
                    type(value) is dict
                    and value.get("schema")
                    == "provider-semantic-control-result-v1"
                ):
                    value = {**value, "request_id": str(uuid4())}
                return original_encode(value)

            monkeypatch.setattr(
                port_service, "encode_op", malformed_control_result
            )
        else:
            original_frame_read = port_client.ProviderPortClient._read_authenticated_frame
            drift = {"active": False, "samples": 0}

            def read_then_fail(current):
                frame = original_frame_read(current)
                if b'"schema":"provider-semantic-control-result-v1"' in frame.payload:
                    if failure == "post_frame_fence":
                        drift["active"] = True
                    else:
                        current["connection"].deadline = broker.Deadline(1.0)
                return frame

            def drifted_mountinfo():
                if drift["active"]:
                    drift["samples"] += 1
                    return mountinfo(root.pair_root, read_only=False)
                return original_read_mountinfo()

            monkeypatch.setattr(
                port_client.ProviderPortClient,
                "_read_authenticated_frame",
                staticmethod(read_then_fail),
            )
            if failure == "post_frame_fence":
                monkeypatch.setattr(listener, "_read_mountinfo", drifted_mountinfo)
        reader_entered = threading.Event()
        reader_errors = []

        def reader():
            channel_state["owner_lock"].acquire()
            reader_entered.set()
            try:
                client._read_owned(channel_state, cancel_owner=True)
            except BaseException as error:  # noqa: BLE001 - exact primary retained
                reader_errors.append(error)
                client._publish_failure(channel_state)
            finally:
                try:
                    client._close(channel_state)
                except BaseException:  # cleanup cannot replace reader primary
                    pass
                client._channel = None
                channel_state["owner_lock"].release()

        reader_thread = threading.Thread(target=reader, daemon=False)
        reader_thread.start()
        assert reader_entered.wait(1)
        with pytest.raises(port_client._OwnedConnectionError) as waiter_error:
            client.control(
                request(
                    "cancel",
                    {
                        "operation_ref": target,
                        "reason_class": "user_requested",
                    },
                ),
                query_state=query,
            )
        reader_thread.join(2)
        assert not reader_thread.is_alive()
        assert waiter_error.value.code == "owned_connection_unavailable"
        assert len(reader_errors) == 1
        assert channel_state["failed"]
        assert client_owner.closed
        if failure == "post_frame_fence":
            assert drift["samples"] >= 1
    assert "error" not in box, box.get("error")


@pytest.mark.parametrize(
    ("operation", "mutation"),
    [
        ("cancel", "not_dict"),
        ("cancel", "extra"),
        ("cancel", "missing"),
        ("cancel", "value"),
        ("cancel", "list"),
        ("cancel", "object"),
        ("status", "extra"),
        ("status", "missing"),
        ("status", "value"),
        ("status", "list"),
        ("status", "object"),
        ("status", "ref"),
    ],
)
def test_owned_control_inner_observation_is_closed_before_publication(
    channel, monkeypatch, operation, mutation
):
    """Authenticated malformed inner observations never commit success."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    original_encode = port_service.encode_op
    malformed_response_encoded = threading.Event()

    def malformed_inner_observation(value):
        if (
            type(value) is dict
            and value.get("schema") == "provider-semantic-control-result-v1"
        ):
            observation = value["observation"]
            if mutation == "not_dict":
                observation = []
            elif mutation == "extra":
                observation = {**observation, "unexpected": True}
            elif mutation == "missing":
                observation = dict(observation)
                observation.pop(
                    "cancel_state"
                    if operation == "cancel"
                    else "terminal_result_ref"
                )
            elif mutation in {"value", "list", "object"}:
                invalid_value = (
                    "unreviewed-state"
                    if mutation == "value"
                    else []
                    if mutation == "list"
                    else {}
                )
                observation = {
                    **observation,
                    ("cancel_state" if operation == "cancel" else "observed_state"):
                        invalid_value,
                }
            else:
                observation = {
                    **observation,
                    "observed_state": "succeeded",
                    "terminal_result_ref": {"not": "an immutable ref"},
                }
            value = {**value, "observation": observation}
            malformed_response_encoded.set()
        return original_encode(value)

    monkeypatch.setattr(
        port_service, "encode_op", malformed_inner_observation
    )
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=10_000,
        )
        client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"reject malformed control",),
            operation_ref=operation_ref,
            config=config,
        )
        channel_state = client._channel
        owner = channel_state["connection"].owner
        control_input = {"operation_ref": target}
        if operation == "cancel":
            control_input["reason_class"] = "user_requested"
        with pytest.raises(ProviderSemanticError):
            client.control(
                request(operation, control_input),
                query_state=query,
            )
        assert malformed_response_encoded.is_set()
        assert channel_state["failed"]
        assert owner.closed
        assert client._channel is None
    assert "error" not in box, box.get("error")


@pytest.mark.parametrize("failure", ["writer", "waiter_timeout"])
def test_owned_control_writer_or_active_reader_timeout_cannot_publish_success(
    channel, monkeypatch, failure
):
    """A failed writer or stalled active reader closes the unusable channel."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"fail control",),
            operation_ref=operation_ref,
            config=config,
        )
        channel_state = client._channel
        owner = channel_state["connection"].owner
        reader_entered = threading.Event()
        release_reader = threading.Event()
        reader_errors = []

        def reader():
            channel_state["owner_lock"].acquire()
            reader_entered.set()
            try:
                if failure == "writer":
                    client._read_owned(channel_state, cancel_owner=True)
                else:
                    assert release_reader.wait(2)
            except BaseException as error:  # noqa: BLE001 - bounded below
                reader_errors.append(error)
                client._publish_failure(channel_state)
            finally:
                channel_state["owner_lock"].release()

        reader_thread = threading.Thread(target=reader, daemon=False)
        reader_thread.start()
        assert reader_entered.wait(1)
        primary = RuntimeError("injected control writer primary")
        if failure == "writer":
            original_write = listener.ExtensionConnection.write

            def fail_control_write(current, **values):
                if (
                    current is owner
                    and b'"schema":"provider-semantic-control-v1"'
                    in values["payload"]
                ):
                    raise primary
                return original_write(current, **values)

            monkeypatch.setattr(
                listener.ExtensionConnection, "write", fail_control_write
            )
            with pytest.raises(RuntimeError) as caught:
                client.control(
                    request("status", {"operation_ref": target}),
                    query_state=query,
                )
            assert caught.value is primary
        else:
            short = broker.Deadline.after_ms(100)
            channel_state["deadline"] = short
            channel_state["connection"].deadline = short
            with pytest.raises(port_client._OwnedConnectionError) as caught:
                client.control(
                    request("status", {"operation_ref": target}),
                    query_state=query,
                )
            assert caught.value.code == "owned_connection_unavailable"
        release_reader.set()
        reader_thread.join(2)
        assert not reader_thread.is_alive()
        assert owner.closed
        assert client._channel is None
        assert channel_state["failed"]
        assert not any(
            pending is not None and pending[0] == "observation"
            for pending in [
                None
                if channel_state["pending_control"] is None
                else channel_state["pending_control"]["outcome"]
            ]
        )
    assert "error" not in box, box.get("error")


@pytest.mark.parametrize(
    "window",
    [
        "idle_uuid",
        "begin_descriptor",
        "begin_frozen",
        "begin_channel",
        "begin_stream",
        "observe_validation",
    ],
)
def test_owned_client_pre_guard_failures_close_without_masking_primary(
    channel, monkeypatch, window
):
    """Fallible post-open windows keep the exact primary and release the owner."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    baseline = open_fds()
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    captured = {}
    original_connect = listener._connect_extension_authenticated

    def capture_connect(*args, **kwargs):
        owner = original_connect(*args, **kwargs)
        captured["owner"] = owner
        return owner

    monkeypatch.setattr(
        port_client.listener,
        "_connect_extension_authenticated",
        capture_connect,
    )
    operation_ref, config = _authority()
    primary = RuntimeError(f"{window} primary")
    cleanup_failures = []
    original_owner_close = listener.ExtensionConnection.close

    def fail_after_client_cleanup(owner):
        was_closed = owner.closed
        original_owner_close(owner)
        if owner._read_only and not was_closed:
            cleanup_failures.append(owner)
            raise OSError("injected post-acquisition cleanup failure")

    monkeypatch.setattr(
        listener.ExtensionConnection, "close", fail_after_client_cleanup
    )
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        if window == "idle_uuid":
            monkeypatch.setattr(
                port_client,
                "uuid4",
                lambda: (_ for _ in ()).throw(primary),
            )
            with pytest.raises(RuntimeError) as caught:
                client.execute(
                    request("capabilities", {}),
                    operation_ref=operation_ref,
                    config=config,
                )
            assert caught.value is primary
        elif window == "begin_descriptor":
            monkeypatch.setattr(
                ProviderPortClient,
                "_description",
                staticmethod(
                    lambda *_args, **_kwargs: (_ for _ in ()).throw(primary)
                ),
            )
            with pytest.raises(RuntimeError) as caught:
                client.begin(
                    _model_request(),
                    frozen_content=_frozen_turn(),
                    input_bytes=(b"guard me",),
                    operation_ref=operation_ref,
                    config=config,
                )
            assert caught.value is primary
        elif window == "begin_frozen":
            monkeypatch.setattr(
                port_client,
                "canonical_json",
                lambda _value: (_ for _ in ()).throw(primary),
            )
            with pytest.raises(RuntimeError) as caught:
                client.begin(
                    _model_request(),
                    frozen_content=_frozen_turn(),
                    input_bytes=(b"guard me",),
                    operation_ref=operation_ref,
                    config=config,
                )
            assert caught.value is primary
        elif window == "begin_channel":
            monkeypatch.setattr(
                port_client,
                "threading",
                types.SimpleNamespace(
                    Event=threading.Event,
                    Lock=threading.Lock,
                    RLock=lambda: (_ for _ in ()).throw(primary),
                ),
            )
            with pytest.raises(RuntimeError) as caught:
                client.begin(
                    _model_request(),
                    frozen_content=_frozen_turn(),
                    input_bytes=(b"guard me",),
                    operation_ref=operation_ref,
                    config=config,
                )
            assert caught.value is primary
        elif window == "begin_stream":
            monkeypatch.setattr(
                port_client,
                "_WorkerClientStreamTransport",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(primary),
            )
            with pytest.raises(RuntimeError) as caught:
                client.begin(
                    _model_request(),
                    frozen_content=_frozen_turn(),
                    input_bytes=(b"guard me",),
                    operation_ref=operation_ref,
                    config=config,
                )
            assert caught.value is primary
        else:
            proposal = client.begin(
                _model_request(),
                frozen_content=_frozen_turn(),
                input_bytes=(b"guard me",),
                operation_ref=operation_ref,
                config=config,
            )
            owner = client._channel["connection"].owner
            with pytest.raises(ProviderSemanticError):
                client.observe(
                    proposal,
                    status="not-an-int",
                    raw=b"{}",
                    exchange_id=str(uuid4()),
                )
            captured["owner"] = owner
            assert client._channel is None
        assert captured["owner"].closed
        assert cleanup_failures == [captured["owner"]]
        assert all(
            getattr(captured["owner"], name) is None
            for name in ("_fence", "_codec", "_socket", "_generation")
        )
    assert box.get("error") is None
    assert open_fds() == baseline


@pytest.mark.parametrize("lock_name", ["write_lock", "owner_lock", "state_lock"])
def test_owned_control_lock_contention_is_bounded_and_cannot_succeed(
    channel, monkeypatch, lock_name
):
    """Held finite-state/I/O ownership locks expire under the original budget."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    operation_ref, config = _authority()
    target = immutable_ref(digest="c")
    query = {
        "operation_ref": target,
        "observed_state": "running",
        "observed_at": "2026-09-20T00:00:00.000Z",
        "terminal_result_ref": None,
    }
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"bounded lock",),
            operation_ref=operation_ref,
            config=config,
        )
        channel_state = client._channel
        short = broker.Deadline.after_ms(100)
        channel_state["deadline"] = short
        channel_state["connection"].deadline = short
        held = threading.Event()
        release = threading.Event()

        def hold_lock():
            lock = channel_state[lock_name]
            lock.acquire()
            held.set()
            assert release.wait(2)
            lock.release()

        holder = threading.Thread(target=hold_lock, daemon=False)
        holder.start()
        assert held.wait(1)
        started = time.monotonic()
        try:
            with pytest.raises((broker.BrokerError, port_client._OwnedConnectionError)):
                client.control(
                    request(
                        "status", {"operation_ref": target}
                    ),
                    query_state=query,
                )
        finally:
            release.set()
            holder.join(2)
        assert not holder.is_alive()
        assert time.monotonic() - started < 1.0
        assert channel_state["connection"].owner.closed
        assert client._channel is None
    assert box.get("error") is None


def test_lock_acquisition_rechecks_the_same_deadline_after_success(monkeypatch):
    """A lock acquired at expiry is released and cannot authorize progress."""

    clock = {"now": 1.0}
    monkeypatch.setattr(
        broker, "time", types.SimpleNamespace(monotonic=lambda: clock["now"])
    )
    deadline = broker.Deadline(2.0)

    class ExpiringLock:
        def __init__(self):
            self.released = False

        def acquire(self, *, timeout):
            assert timeout == 1.0
            clock["now"] = 2.0
            return True

        def release(self):
            self.released = True

    lock = ExpiringLock()
    with pytest.raises(broker.DeadlineExceeded):
        port_client._acquire(lock, deadline)
    assert lock.released


def test_service_claims_exact_owner_before_invalid_deadline_but_not_wrong_type(
    channel, monkeypatch
):
    """Type refusal borrows; exact-owner deadline refusal consumes and closes."""

    class NotAnOwner:
        def __init__(self):
            self.closed = False

        def close(self):
            self.closed = True

    borrowed = NotAnOwner()
    with pytest.raises(ProviderSemanticError):
        ProviderPortService().serve_connection(borrowed, deadline="invalid")
    assert not borrowed.closed

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    worker = listener.bind_worker_listener(
        root, spec, responder_boot_id="owned-worker"
    )
    box = {}

    def accept_owner():
        side["worker_ident"] = threading.get_ident()
        box["owner"] = listener._accept_extension_authenticated(
            worker, deadline=broker.Deadline.after_ms(3000)
        )

    accept = threading.Thread(target=accept_owner, daemon=False)
    accept.start()
    client_owner = listener._connect_extension_authenticated(
        root,
        spec,
        requester_boot_id="owned-control",
        deadline=broker.Deadline.after_ms(3000),
    )
    accept.join(3)
    server_owner = box["owner"]
    try:
        with pytest.raises(ProviderSemanticError):
            ProviderPortService().serve_connection(
                server_owner, deadline="invalid"
            )
        assert server_owner.closed
    finally:
        server_owner.close()
        client_owner.close()
        worker.close()


def test_fixed_slot_uses_original_absolute_deadline_and_owner_minimum(
    channel, monkeypatch
):
    """Opening cannot mint a new budget after connect/handshake."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    captured = {}
    original_connect = listener._connect_extension_authenticated

    def shorter_owner(*args, **kwargs):
        captured["connect_deadline"] = kwargs["deadline"]
        owner = original_connect(*args, **kwargs)
        owner.deadline = broker.Deadline(
            min(owner.deadline.end_monotonic, time.monotonic() + 1.0)
        )
        captured["owner"] = owner
        return owner

    monkeypatch.setattr(
        port_client.listener,
        "_connect_extension_authenticated",
        shorter_owner,
    )
    caller_end = time.monotonic() + 2.0
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        connection, effective = client._open(caller_end)
        assert captured["connect_deadline"].end_monotonic == caller_end
        assert effective.end_monotonic == captured["owner"].deadline.end_monotonic
        assert effective.end_monotonic < caller_end
        connection.close()
    assert box.get("error") is None


def test_fixed_slot_handshake_consumes_the_same_original_deadline(
    channel, monkeypatch
):
    """Connect/handshake work spends, but cannot replace, the caller budget."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    captured = {}
    original_handshake = listener.broker._extension_client_handshake

    def consuming_handshake(*args, **kwargs):
        deadline = kwargs["deadline"]
        captured["deadline"] = deadline
        captured["before"] = deadline.remaining()
        assert not threading.Event().wait(0.05)
        captured["after"] = deadline.remaining()
        return original_handshake(*args, **kwargs)

    monkeypatch.setattr(
        listener.broker, "_extension_client_handshake", consuming_handshake
    )
    caller_end = time.monotonic() + 2.0
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        connection, effective = client._open(caller_end)
        assert captured["deadline"].end_monotonic == caller_end
        assert effective.end_monotonic == caller_end
        assert captured["before"] - captured["after"] >= 0.04
        assert effective.remaining() < captured["before"]
        connection.close()
    assert box.get("error") is None


@pytest.mark.parametrize("boundary", ["expired_post_connect", "pre_fence"])
def test_owned_open_refuses_expired_post_connect_or_pre_fence(
    channel, monkeypatch, boundary
):
    """The first owned checkpoint cannot publish an expired or stale owner."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    captured = {}
    original_connect = listener._connect_extension_authenticated
    original_recheck = listener.ExtensionConnection.recheck

    def perturb_connect(*args, **kwargs):
        owner = original_connect(*args, **kwargs)
        captured["owner"] = owner
        if boundary == "expired_post_connect":
            owner.deadline = broker.Deadline(1.0)
        return owner

    def fail_pre_fence(owner):
        if boundary == "pre_fence" and owner is captured.get("owner"):
            raise listener.ListenerIntegrityError()
        return original_recheck(owner)

    monkeypatch.setattr(
        port_client.listener,
        "_connect_extension_authenticated",
        perturb_connect,
    )
    monkeypatch.setattr(listener.ExtensionConnection, "recheck", fail_pre_fence)
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        with pytest.raises(
            (broker.DeadlineExceeded, port_client._OwnedConnectionError)
        ) as caught:
            client._open(time.monotonic() + 2.0)
        if boundary == "pre_fence":
            assert caught.value.code == "owned_connection_unavailable"
        assert captured["owner"].closed
        assert all(
            getattr(captured["owner"], name) is None
            for name in ("_fence", "_codec", "_socket", "_generation")
        )
    assert box.get("error") is None


def test_owned_final_stream_ack_expiry_closes_without_publication(
    channel, monkeypatch
):
    """Expiry while the final descriptor ACK is in flight cannot publish output."""

    root, spec = channel
    side = seams(monkeypatch, root, spec)
    monkeypatch.setattr(
        port_client,
        "extension_channel",
        lambda *, instance_id, slot_number: (root, spec),
    )
    captured = {}
    original_owned = port_service._owned_connection

    def capture_adapter(owner, deadline):
        adapter = original_owned(owner, deadline)
        captured["adapter"] = adapter
        return adapter

    monkeypatch.setattr(port_service, "_owned_connection", capture_adapter)
    operation_ref, config = _authority()
    with owned_semantic_service(root, spec, side) as box:
        client = ProviderPortClient.for_extension_slot(
            instance_id=INSTANCE,
            slot_number=4,
            requester_boot_id="owned-control",
            deadline_ms=3000,
        )
        proposal = client.begin(
            _model_request(),
            frozen_content=_frozen_turn(),
            input_bytes=(b"expire final ack",),
            operation_ref=operation_ref,
            config=config,
        )
        original_send = port_client._WorkerClientStreamTransport.send
        expired = threading.Event()

        def expire_on_final_accept(transport, payload):
            if (
                not expired.is_set()
                and b'"type":"artifact-accepted"' in payload
            ):
                captured["adapter"].deadline = broker.Deadline(1.0)
                expired.set()
            return original_send(transport, payload)

        monkeypatch.setattr(
            port_client._WorkerClientStreamTransport,
            "send",
            expire_on_final_accept,
        )
        with pytest.raises((broker.BrokerError, port_client._OwnedConnectionError)):
            client.observe(
                proposal,
                status=200,
                raw=valid_stream("must not publish"),
                exchange_id=str(uuid4()),
            )
        assert expired.is_set()
        assert client._channel is None
    assert box["owner"].closed
    assert isinstance(box.get("error"), broker.DeadlineExceeded)
