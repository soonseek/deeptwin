"""The owned shared vault ingress and send dialogue over the fixed gateway profile
(Task51 G5–G10; design §5–§6).

One serial ingress call owns the read cursor of one accepted owner: it reads
exactly one authenticated first frame, checks the original payload's length
before the single decode, routes a plain credential-v2 request, a fragmented
credential transfer or the closed legacy shapes to the existing vault engine —
one first-frame decode, one dispatch, real vault mutations as the oracle — and
closes without dispatch on anything else. The fixed client factory obtains the
profile internally; tests substitute only the module-local profile resolution
into an owned temporary root.
"""

from __future__ import annotations

import threading
import time
from uuid import uuid4

import pytest

from app.tests.support.provider_gateway_harness import (
    CONTROL_BOOT,
    connect_owner,
    fixed_profile_into,
    gateway_pair,
    served_gateway,
)
from app.tests.support.provider_semantic_harness import encrypted_credential
from app.tests.test_credential_custody import metadata
from app.workers import broker, listener
from app.workers.credential_channel import (
    CredentialGatewayClient,
    GatewayServiceError,
    encode_op,
)
from app.workers.credential_gateway_service import CredentialGatewayService
from app.workers.provider_gateway import CredentialedProviderTransport
from app.workers.provider_send_service import ProviderSendService

BOOT_SECRET = broker.BootSecret(b"k" * broker.AUTH_SECRET_BYTES)


def binding(port=1):
    from app.tests.support.transport_manifest import loopback_binding

    return loopback_binding(port)


def services(vault, spec):
    from app.workers.provider_gateway_ingress import ProviderGatewayIngress

    credential = CredentialGatewayService(vault, spec, BOOT_SECRET)
    send = ProviderSendService(CredentialedProviderTransport(vault, binding()))
    return credential, send, ProviderGatewayIngress(credential, send)


def spy(monkeypatch, owner, name):
    """Count calls of `owner.name`; a slotted instance is spied through its class,
    counting only this instance's calls. Observation only: the real call runs."""
    calls = []
    import types

    if isinstance(owner, types.ModuleType):
        original = getattr(owner, name)

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(owner, name, counting)
        return calls
    cls = type(owner)
    original = getattr(cls, name)

    def counting_method(self, *args, **kwargs):
        if self is owner:
            calls.append(1)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(cls, name, counting_method)
    return calls


def secret_of_payload_length(target):
    """A store request whose canonical payload is exactly `target` bytes."""
    meta = metadata()
    low, high = 1, 65_536
    while low < high:
        mid = (low + high) // 2
        length = len(encode_op({"schema": "credential-op-v2", "op": "store_at", "metadata": meta,
                                    "secret_b64u": __import__("app.workers.credential_contracts",
                                                           fromlist=["b64u"]).b64u(b"s" * mid)}))
        if length < target:
            low = mid + 1
        else:
            high = mid
    from app.workers.credential_contracts import b64u

    for size in (low - 1, low, low + 1, low + 2):
        if size < 1:
            continue
        secret = b"s" * size
        if len(encode_op({"schema": "credential-op-v2", "op": "store_at", "metadata": meta,
                              "secret_b64u": b64u(secret)})) == target:
            return meta, secret
    raise AssertionError(f"no secret yields a {target}-byte payload")


def test_plain_store_query_and_retire_cross_the_owned_ingress_with_one_decode_and_one_dispatch(tmp_path, tmp_path_factory, monkeypatch):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        dispatches = spy(monkeypatch, credential, "_dispatch")
        client = CredentialGatewayClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(3)
            queried = client.query_record(metadata=meta)
            assert queried["record_id"] == record["record_id"]
            assert dispatches == [1]
            new_meta = metadata()
            stored = client.store_at(metadata=new_meta, secret=b"another-synthetic-secret")
            assert stored["record_version"] == 1
            assert vault.query_record(metadata=new_meta)["record_id"] == stored["record_id"]  # the vault is the oracle
            reference = {key: stored[key] for key in ("record_id", "record_version", "ciphertext_sha256")}
            retired = client.retire(command_id=str(uuid4()), record=reference, reason="superseded")
            assert retired
            assert served.join() == []
        assert len(dispatches) == 3


def test_a_fragmented_store_and_snapshot_reuse_the_first_fragment_decode_exactly_once(tmp_path, tmp_path_factory, monkeypatch):
    from app.workers import credential_channel

    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, _meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        decodes = spy(monkeypatch, credential_channel, "decode_op")
        dispatches = spy(monkeypatch, credential, "_dispatch")
        client = CredentialGatewayClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        big_meta = metadata()
        with served_gateway(root, spec, ingress) as served:
            served.serve(2)
            stored = client.store_at(metadata=big_meta, secret=b"x" * 40_000)  # four fragments
            assert vault.query_record(metadata=big_meta)["record_id"] == stored["record_id"]
            after_store = len(decodes)
            listing = client.snapshot()
            assert any(item.get("record_id") == stored["record_id"] for item in listing)
            assert served.join() == []
        assert len(dispatches) == 2
        # exact counts: the store's four fragments decoded once each by the gateway (the
        # first through the router, the rest through the helper) plus the reconstruction
        # once, plus the client's one reply decode — a doubled first-fragment decode is a
        # count of seven; the snapshot is one request decode and one reply decode
        assert after_store == 6
        assert len(decodes) == after_store + 2


def test_closed_legacy_shapes_are_answered_unsupported_and_never_mutate(tmp_path, tmp_path_factory, monkeypatch):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        dispatches = spy(monkeypatch, credential, "_dispatch")
        client = CredentialGatewayClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(2)
            with pytest.raises(GatewayServiceError) as refused:
                client.submit(intent_id=str(uuid4()), provider="claude", secret=b"legacy", rotate_from=None)
            assert refused.value.code == "unsupported_operation"
            with pytest.raises(GatewayServiceError) as refused:
                client.delete(record["record_id"])
            assert refused.value.code == "unsupported_operation"
            assert served.join() == []
        assert vault.query_record(metadata=meta)["record_id"] == record["record_id"]
        assert len(dispatches) == 2


def raw_dialogue(root, spec, *, payload, message_type="credential_op", correlation_id=None, second=None):
    """A control-side owner sending an arbitrary first frame (and optionally a second),
    returning what came back: the reply payload, or the transport failure."""
    owner = connect_owner(root, spec)
    try:
        owner.write(message_id=str(uuid4()), correlation_id=correlation_id, message_type=message_type,
                    payload=payload, deadline=broker.Deadline.after_ms(3_000))
        if second is not None:
            owner.write(message_id=str(uuid4()), correlation_id=None, message_type="credential_op",
                        payload=second, deadline=broker.Deadline.after_ms(3_000))
        try:
            return owner.read(deadline=broker.Deadline.after_ms(3_000)).payload
        except broker.BrokerError as error:
            return error
    finally:
        owner.close()


@pytest.mark.parametrize("length", [16_383, 16_384])
def test_a_plain_request_at_or_under_the_ordinary_bound_is_served(tmp_path, tmp_path_factory, monkeypatch, length):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, _meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        dispatches = spy(monkeypatch, credential, "_dispatch")
        meta, secret = secret_of_payload_length(length)
        payload = encode_op({"schema": "credential-op-v2", "op": "store_at", "metadata": meta,
                                 "secret_b64u": __import__("app.workers.credential_contracts", fromlist=["b64u"]).b64u(secret)})
        assert len(payload) == length
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            reply = raw_dialogue(root, spec, payload=payload)
            assert served.join() == []
        assert isinstance(reply, bytes) and b'"ok":true' in reply
        assert dispatches == [1]
        assert vault.query_record(metadata=meta)["record_version"] == 1


def test_a_plain_request_over_the_ordinary_bound_is_refused_before_dispatch_but_its_fragments_are_served(tmp_path, tmp_path_factory, monkeypatch):
    from app.workers import credential_channel

    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, _meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        dispatches = spy(monkeypatch, credential, "_dispatch")
        meta, secret = secret_of_payload_length(16_385)
        from app.workers.credential_contracts import b64u

        payload = encode_op({"schema": "credential-op-v2", "op": "store_at", "metadata": meta, "secret_b64u": b64u(secret)})
        assert len(payload) == 16_385
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            reply = raw_dialogue(root, spec, payload=payload)
            errors = served.join()
        assert isinstance(reply, broker.BrokerError)  # closed without a reply
        assert dispatches == []
        assert len(errors) == 1 and isinstance(errors[0], GatewayServiceError)
        assert vault.query_record(metadata=meta)["state"] == "unknown"  # nothing stored
        # the identical logical bytes, correctly fragmented, are served
        client = CredentialGatewayClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            stored = client.store_at(metadata=meta, secret=secret)
            assert served.join() == []
        assert vault.query_record(metadata=meta)["state"] != "unknown"
        assert stored["record_id"] == meta["record_id"]
        assert dispatches == [1]
        assert credential_channel.MAX_OP_PAYLOAD_BYTES >= 16_385


def test_the_first_frame_bound_is_checked_before_the_decode_and_fragments_beyond_it_are_rejected(tmp_path, tmp_path_factory, monkeypatch):
    from app.workers import credential_channel

    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, _meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        decodes = spy(monkeypatch, credential_channel, "decode_op")
        dispatches = spy(monkeypatch, credential, "_dispatch")
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            reply = raw_dialogue(root, spec, payload=b"{" + b" " * 24_575 + b"}")  # 24 577 bytes
            errors = served.join()
        assert isinstance(reply, broker.BrokerError) and dispatches == []
        assert decodes == []  # rejected before the single decode
        assert len(errors) == 1 and "out of bounds" in str(errors[0])
        # a canonical 24 576-byte plain request reaches the remaining grammar (decoded once)
        # and is refused there as an ordinary message over the bound: zero dispatch
        from app.workers.credential_contracts import b64u

        meta, secret = secret_of_payload_length(24_576)
        canonical = encode_op({"schema": "credential-op-v2", "op": "store_at", "metadata": meta, "secret_b64u": b64u(secret)})
        assert len(canonical) == 24_576
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            reply = raw_dialogue(root, spec, payload=canonical)
            errors = served.join()
        assert isinstance(reply, broker.BrokerError) and dispatches == []
        assert len(decodes) == 1 and "ordinary message is out of bounds" in str(errors[0])
        assert vault.query_record(metadata=meta)["state"] == "unknown"


def test_a_fragmented_prepare_a_stream_frame_first_and_a_second_conversation_are_closed_without_dispatch(tmp_path, tmp_path_factory, monkeypatch):
    from app.workers.credential_channel import _write_logical

    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, send, ingress = services(vault, spec)
        dispatches = spy(monkeypatch, credential, "_dispatch")
        prepares = spy(monkeypatch, send, "prepare")
        # a fragmented semantic prepare is refused after assembly, never rerouted
        prepare = encode_op({"schema": "provider-send-prepare-v1", "seq": 0, "filler": "x" * 20_000})
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            owner = connect_owner(root, spec)
            try:
                _write_logical(owner._socket, owner._codec, payload=prepare, message_id=str(uuid4()),
                               message_type="credential_op", correlation_id=None,
                               deadline=broker.Deadline.after_ms(3_000))
                with pytest.raises(broker.BrokerError):
                    owner.read(deadline=broker.Deadline.after_ms(3_000))
            finally:
                owner.close()
            errors = served.join()
        assert dispatches == [] and prepares == []
        assert len(errors) == 1
        # a commit frame first (a correlated frame) is not a first frame
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            reply = raw_dialogue(root, spec, payload=encode_op({"schema": "provider-send-commit-v1"}),
                                 correlation_id=str(uuid4()))
            errors = served.join()
        assert isinstance(reply, broker.BrokerError) and dispatches == [] and len(errors) == 1
        # after one served operation the owner is closed: a second conversation meets EOF
        query = encode_op({"schema": "credential-op-v2", "op": "query_record", "metadata": meta})
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            owner = connect_owner(root, spec)
            try:
                owner.write(message_id=str(uuid4()), correlation_id=None, message_type="credential_op",
                            payload=query, deadline=broker.Deadline.after_ms(3_000))
                first = owner.read(deadline=broker.Deadline.after_ms(3_000))
                assert b'"ok":true' in first.payload
                with pytest.raises(broker.BrokerError):
                    owner.write(message_id=str(uuid4()), correlation_id=None, message_type="credential_op",
                                payload=query, deadline=broker.Deadline.after_ms(3_000))
                    owner.read(deadline=broker.Deadline.after_ms(3_000))
            finally:
                owner.close()
            assert served.join() == []
        assert dispatches == [1]


def test_the_ingress_serves_one_dialogue_at_a_time_and_validates_its_listener_and_owner(tmp_path, tmp_path_factory, monkeypatch):
    from app.workers.provider_gateway_ingress import ProviderGatewayIngress

    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, send, ingress = services(vault, spec)
        # composition: the same exact vault, the credential service's spec is the gateway's
        other_send = ProviderSendService(CredentialedProviderTransport(
            __import__("app.workers.credential_vault", fromlist=["CredentialVault"]).CredentialVault(
                **__import__("app.tests.test_credential_root", fromlist=["initialized"]).initialized(tmp_path_factory.mktemp("other"))),
            binding()))
        with pytest.raises(GatewayServiceError):
            ProviderGatewayIngress(credential, other_send)
        with pytest.raises(GatewayServiceError):
            ProviderGatewayIngress(object(), send)
        worker = listener.bind_worker_listener(root, spec, responder_boot_id="provider-boot-a")
        try:
            # a first owner is being served (the ingress waits on its first frame); a second
            # ingress call is refused without touching the first owner's reader, and the
            # competing accepted owner is closed
            first_box, second_box = {}, {}
            first_thread = threading.Thread(target=lambda: first_box.update(
                error=_serve(ingress, worker)), daemon=True)
            first_thread.start()
            first_client = connect_owner(root, spec)
            for _ in range(200):  # the first dialogue holds the latch before the second competes
                if ingress._latch.locked():
                    break
                time.sleep(0.01)
            assert ingress._latch.locked()
            second_thread = threading.Thread(target=lambda: second_box.update(
                error=_serve(ingress, worker)), daemon=True)
            second_thread.start()
            second_client = connect_owner(root, spec)
            second_thread.join(5)
            assert not second_thread.is_alive()
            assert isinstance(second_box["error"], GatewayServiceError)
            with pytest.raises(broker.BrokerError):  # the competing owner was closed on rejection
                second_client.read(deadline=broker.Deadline.after_ms(1_000))
            second_client.close()
            # the first dialogue is intact
            query = encode_op({"schema": "credential-op-v2", "op": "query_record", "metadata": meta})
            first_client.write(message_id=str(uuid4()), correlation_id=None, message_type="credential_op",
                               payload=query, deadline=broker.Deadline.after_ms(3_000))
            assert b'"ok":true' in first_client.read(deadline=broker.Deadline.after_ms(3_000)).payload
            first_client.close()
            first_thread.join(5)
            assert first_box["error"] is None
            # a listener of another root/spec is refused before accept
            with gateway_pair(tmp_path_factory.mktemp("elsewhere"), monkeypatch) as (other_root, other_spec):
                other_worker = listener.bind_worker_listener(other_root, other_spec, responder_boot_id="provider-boot-b")
                try:
                    fixed_profile_into(monkeypatch, root, spec)
                    with pytest.raises(GatewayServiceError):
                        ingress.serve_one(other_worker, requester_boot_id=CONTROL_BOOT,
                                          deadline=broker.Deadline.after_ms(500))
                finally:
                    other_worker.close()
        finally:
            worker.close()


def _serve(ingress, worker):
    try:
        ingress.serve_one(worker, requester_boot_id=CONTROL_BOOT, deadline=broker.Deadline.after_ms(4_000))
    except Exception as error:  # noqa: BLE001 - the refusal is the fact under test
        return error
    return None


# --- the owned send dialogue (G7–G10; design §6 "Commit, cancel and publication") -----------

from app.tests.support.provider_semantic_harness import (
    connection_values,
    controlled_upstream,
)
from app.tests.test_provider_send_gateway import binding as http_binding
from app.tests.test_provider_send_gateway import (
    prepared,
    prepared_catalog,
)
from app.workers.provider_send_client import (
    ProviderSendCleanupAfterCancellation,
    ProviderSendClient,
)
from app.workers.provider_send_messages import ProviderSendError


def send_services(vault, spec, port):
    from app.workers.provider_gateway_ingress import ProviderGatewayIngress

    credential = CredentialGatewayService(vault, spec, BOOT_SECRET)
    send = ProviderSendService(CredentialedProviderTransport(vault, http_binding(port)))
    return credential, send, ProviderGatewayIngress(credential, send)


def test_an_owned_prepare_body_commit_and_result_capture_the_actual_request(tmp_path, tmp_path_factory, monkeypatch):
    sent_body = b'{"model":"synthetic","messages":[]}'
    expected_sse = b"event: ping\ndata: {}\n\n"
    with controlled_upstream(response=(200, "text/event-stream", expected_sse)) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path, b"synthetic-owned-secret") as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            message = prepared(meta, record, handle, pin, body=sent_body, remaining_ms=5_000)
            ready = client.prepare(message)
            assert ready["prepare_sha256"] == message.prepare_sha256
            assert captures == []  # after ready and before commit
            assert client.authenticated_session_observation[0] == "credential-gateway-v1"
            lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            observed = client.exchange(lease)
            assert served.join() == []
        assert len(captures) == 1
        method, path, headers, captured_body = captures[0]
        assert (method, path, captured_body) == ("POST", "/v1/messages", sent_body)
        assert headers["x-api-key"] == b"synthetic-owned-secret".decode("ascii")
        assert observed.body == expected_sse
        assert observed.phase == "terminal_observed" and observed.status == 200
        assert client._channel is None  # the dialogue is closed after the result


def test_owned_bodyless_catalog_pages_and_a_retired_credential_refuses_the_next_send(tmp_path, tmp_path_factory, monkeypatch):
    raw = b'{"data":[],"first_id":null,"last_id":null,"has_more":false}'
    with controlled_upstream(response=(200, "application/json", raw)) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        credential_client = CredentialGatewayClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(4)
            first = prepared_catalog(meta, record, handle, pin)
            ready = client.prepare(first)
            observed = client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
            assert observed.body == raw and captures[-1][0] == "GET"
            assert captures[-1][1].startswith("/v1/models") and captures[-1][3] == b""
            page = prepared_catalog(meta, record, handle, pin, after_id="msg_01 &x")
            ready = client.prepare(page)
            client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
            assert captures[-1][0] == "GET" and captures[-1][1].startswith("/v1/models?")
            assert "after_id=msg_01" in captures[-1][1] and " " not in captures[-1][1]
            # the same vault, the same ingress: retire through the credential branch, then the
            # next send is refused with no additional HTTP request
            credential_client.retire(command_id=str(uuid4()), record=record, reason="owner_delete")
            ready = client.prepare(prepared_catalog(meta, record, handle, pin))
            # custody is refused at delivery: the gateway reports a refused, not-sent result
            refused = client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
            assert refused.phase == "not_sent" and refused.status is None and refused.failure_class is not None
            errors = served.join()
        assert len(captures) == 2  # zero additional HTTP requests
        assert errors == []


def test_ready_cancel_and_commit_claim_one_state_and_the_loser_is_refused(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(2)
            # ready-cancel first: the commit after it is refused locally, nothing sent
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            cancelled = client.cancel(ready["exchange_id"], "user_requested")
            assert cancelled.accepted is True and cancelled.phase == "not_sent"
            assert client._channel is None
            with pytest.raises(ProviderSendError, match="no ready"):
                client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            assert send.status(ready["exchange_id"]) == "unknown"  # the pending exchange was removed
            # commit first: a cancel after the result meets the fixed terminal state (the
            # exchange already closed the dialogue), never a guessed acknowledgement
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            observed = client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
            assert observed.phase == "terminal_observed"
            late = client.cancel(ready["exchange_id"], "user_requested")
            assert late.accepted is False and late.phase == "terminal_observed"
            assert served.join() == []
        assert len(captures) == 1


def test_a_cancel_during_a_blocked_http_exchange_is_acknowledged_once_and_owns_the_cleanup(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n"), blocked=True) as (port, captures, entered, release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress, deadline_ms=6_000) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=4_000))
            outcome, failures = [], []

            def commit():
                try:
                    outcome.append(client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))))
                except BaseException as error:  # noqa: BLE001 - the failure class is the fact
                    failures.append(error)

            thread = threading.Thread(target=commit, daemon=True)
            thread.start()
            assert entered.wait(2)
            assert client.status(ready["exchange_id"]) == "running"
            # two concurrent cancels: each gets its own exact acknowledgement, never a stale one
            acks = []

            def cancel_once():
                try:
                    acks.append(client.cancel(ready["exchange_id"], "user_requested"))
                except ProviderSendError as error:
                    acks.append(error)  # the deterministic terminal closure, when no stream follows

            cancels = [threading.Thread(target=cancel_once, daemon=True) for _ in range(2)]
            for worker in cancels:
                worker.start()
            for worker in cancels:
                worker.join(5)
                assert not worker.is_alive()
            assert len(acks) == 2 and acks[0] is not acks[1]  # each its own outcome, never a shared stale one
            accepted = [ack for ack in acks if type(ack).__name__ == "ProviderSendCancellation" and ack.accepted]
            # at least one validated acknowledgement; a second cancel that reaches the gateway
            # while its exchange is still running is acknowledged exactly as well
            assert 1 <= len(accepted) <= 2 and all(ack.phase == "may_have_sent" for ack in accepted)
            for other in (ack for ack in acks if ack not in accepted):
                assert isinstance(other, ProviderSendError) or (other.accepted is False and other.phase == "terminal_observed")
            thread.join(6)
            release.set()
            assert not thread.is_alive()
            # a cancel framed during the result stream may be acknowledged after the client's
            # deterministic terminal closure: the gateway's post-delivery failure is tolerated
            # (design §6), never a second outcome for the client
            errors = served.join()
            assert len(errors) <= 1 and all(isinstance(error, ProviderSendError) for error in errors)
        # over frames the gateway reports the cancelled exchange as its result (the raw
        # over-frames precedent): the observation, not an exception
        assert failures == [] and len(outcome) == 1
        assert outcome[0].cancel_observed is True and outcome[0].phase == "may_have_sent"
        assert outcome[0].failure_class is not None and outcome[0].status is None
        assert len(captures) == 1


def test_a_ready_cancel_whose_cleanup_fails_keeps_the_exact_cancellation(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            owner = client._channel["connection"]
            original_close = type(owner).close

            def failing_close(self):
                original_close(self)
                if self is owner:
                    raise OSError("OWNER CLOSE")

            monkeypatch.setattr(type(owner), "close", failing_close)
            with pytest.raises(ProviderSendCleanupAfterCancellation) as failure:
                client.cancel(ready["exchange_id"], "user_requested")
            monkeypatch.setattr(type(owner), "close", original_close)
            assert str(failure.value) == "provider send cleanup failed after cancellation observation"
            assert failure.value.cancellation_observation.accepted is True
            assert failure.value.cancellation_observation.phase == "not_sent"
            assert failure.value.failure_class == "internal_failure"
            assert client._channel is None and owner.closed
            assert served.join() == []
        assert captures == []


def test_eof_before_an_acknowledgement_is_never_a_claimed_cancellation(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n"), blocked=True) as (port, _captures, entered, release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress, deadline_ms=6_000) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=4_000))
            failures = []
            thread = threading.Thread(target=lambda: failures.append(_failure(
                lambda: client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))))), daemon=True)
            thread.start()
            assert entered.wait(2)
            # the gateway never answers the cancel: its acknowledgement path is cut before
            # any frame — the client's abandon closes the dialogue and the waiter sees the
            # terminal state, never a guessed acknowledgement
            original = ProviderSendService.cancel

            def silent_cancel(self, exchange_id, reason):
                if self is send:
                    client.abandon()
                return original(self, exchange_id, reason)

            monkeypatch.setattr(ProviderSendService, "cancel", silent_cancel)
            with pytest.raises(ProviderSendError):
                client.cancel(ready["exchange_id"], "user_requested")
            release.set()
            thread.join(6)
            assert not thread.is_alive()
            served.join()
        assert len(failures) == 1 and failures[0] is not None


def _failure(call):
    try:
        call()
    except BaseException as error:  # noqa: BLE001 - the failure is the fact
        return error
    return None


def test_an_unjoinable_http_thread_marks_the_send_service_and_the_ingress_unusable(tmp_path, tmp_path_factory, monkeypatch):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, send, ingress = send_services(vault, spec, 1)
        handle, pin, _, _ = connection_values(meta, record)
        entered, release = threading.Event(), threading.Event()

        def surviving_exchange(self, lease):
            entered.set()
            release.wait(5)
            raise ProviderSendError("test-owned surviving exchange")

        monkeypatch.setattr(ProviderSendService, "exchange", surviving_exchange)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=1_500)
        try:
            with served_gateway(root, spec, ingress, deadline_ms=1_200) as served:
                served.serve(1)
                ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=1_200))
                with pytest.raises(ProviderSendError) as failure:
                    client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
                assert failure.value.failure_class in ("deadline_exceeded", "dependency_unavailable")
                assert entered.wait(2)
                errors = served.join()
            assert len(errors) == 1 and isinstance(errors[0], ProviderSendError)
            assert send._usable is False and ingress.usable is False
            # a further dialogue is refused rather than started beside the retained thread
            with served_gateway(root, spec, ingress) as served:
                served.serve(1)
                with pytest.raises(ProviderSendError):
                    client.prepare(prepared(meta, record, handle, pin, remaining_ms=1_200))
                errors = served.join()
            assert len(errors) == 1 and isinstance(errors[0], GatewayServiceError)
        finally:
            release.set()  # the retained HTTP thread is released and its exit proven
        retained = [thread for thread in threading.enumerate() if thread.name == "provider-send-exchange"]
        for thread in retained:
            thread.join(2)
            assert not thread.is_alive()


def legacy_store_of_payload_length(target):
    """The existing client's legacy store shape whose canonical payload is exactly `target` bytes."""
    import base64

    base = {"op": "store", "intent_id": "11111111-1111-4111-8111-111111111111", "provider": "claude",
            "secret_b64": base64.b64encode(b"s" * 3).decode("ascii"), "rotate_from": ""}
    slack = target - len(encode_op(base))
    assert slack >= 0
    value = {**base, "rotate_from": "r" * slack}  # the untrusted string absorbs the exact remainder
    assert len(encode_op(value)) == target
    return value


@pytest.mark.parametrize("length", [16_384, 16_385])
def test_the_closed_legacy_arms_keep_unsupported_at_the_bound_and_refuse_over_it(tmp_path, tmp_path_factory, monkeypatch, length):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        dispatches = spy(monkeypatch, credential, "_dispatch")
        payload = encode_op(legacy_store_of_payload_length(length))
        assert len(payload) == length
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            reply = raw_dialogue(root, spec, payload=payload)
            errors = served.join()
        if length == 16_384:
            assert isinstance(reply, bytes) and b'"code":"unsupported_operation"' in reply
            assert dispatches == [1] and errors == []
        else:
            assert isinstance(reply, broker.BrokerError) and dispatches == []
            assert len(errors) == 1 and "ordinary message is out of bounds" in str(errors[0])
        assert vault.query_record(metadata=meta)["record_id"] == record["record_id"]


@pytest.mark.parametrize("length", [16_384, 16_385])
def test_a_plain_prepare_enters_the_send_engine_at_the_bound_and_is_refused_over_it(tmp_path, tmp_path_factory, monkeypatch, length):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, _meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, send, ingress = services(vault, spec)
        dialogues = spy(monkeypatch, send, "_serve_dialogue")
        filler = "x" * (length - len(encode_op({"schema": "provider-send-prepare-v1", "seq": 0, "filler": ""})))
        payload = encode_op({"schema": "provider-send-prepare-v1", "seq": 0, "filler": filler})
        assert len(payload) == length
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            reply = raw_dialogue(root, spec, payload=payload)
            errors = served.join()
        assert isinstance(reply, broker.BrokerError)
        if length == 16_384:
            assert dialogues == [1]  # the engine's own validators refuse the shape from there
            assert len(errors) == 1 and isinstance(errors[0], ProviderSendError)
        else:
            assert dialogues == [] and len(errors) == 1 and isinstance(errors[0], GatewayServiceError)


def test_an_oversized_continuation_fragment_is_rejected_before_its_decode(tmp_path, tmp_path_factory, monkeypatch):
    from app.workers import credential_channel
    from app.workers.credential_contracts import b64u

    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, _meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        credential, _send, ingress = services(vault, spec)
        decodes = spy(monkeypatch, credential_channel, "decode_op")
        dispatches = spy(monkeypatch, credential, "_dispatch")
        transfer = "11111111-1111-4111-8111-111111111111"
        first = encode_op({"schema": "credential-fragment-v1", "transfer_id": transfer, "total_bytes": 40_000,
                           "index": 0, "count": 3, "chunk_b64u": b64u(b"a" * 16_384)})
        oversized = b"{" + b" " * 24_575 + b"}"  # 24 577 bytes: refused before its decode
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            owner = connect_owner(root, spec)
            try:
                owner.write(message_id=transfer, correlation_id=None, message_type="credential_op",
                            payload=first, deadline=broker.Deadline.after_ms(3_000))
                owner.write(message_id=str(uuid4()), correlation_id=transfer, message_type="credential_op",
                            payload=oversized, deadline=broker.Deadline.after_ms(3_000))
                with pytest.raises(broker.BrokerError):
                    owner.read(deadline=broker.Deadline.after_ms(3_000))
            finally:
                owner.close()
            errors = served.join()
        assert dispatches == [] and len(decodes) == 1  # the first fragment only
        assert len(errors) == 1 and "fragment is not bound" in str(errors[0])


def test_the_raw_entry_refuses_a_non_strict_reconstruction_before_any_reply(tmp_path):
    # the one behaviour the shared grammar moved on the raw entry, pinned: a fragment
    # transfer reconstructing to non-strict JSON closes the codec with no reply
    import socket as socket_module

    from app.tests.test_credential_gateway_service import authenticated_pair
    from app.workers.credential_channel import _write_logical

    with encrypted_credential(tmp_path) as (vault, _meta, _record), authenticated_pair(tmp_path) as (left, cc, right, sc, spec, boot):
        service = CredentialGatewayService(vault, spec, boot)
        wire, outcome = [], {}

        def serve():
            try:
                service.serve_one(right, sc, deadline=broker.Deadline.after_ms(3_000), wire_log=wire)
            except BaseException as error:  # noqa: BLE001 - the category is the fact
                outcome["error"] = error

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        _write_logical(left, cc, payload=b"{" + b"\n" * 20_000 + b"}", message_id=str(uuid4()),
                       message_type="credential_op", correlation_id=None, deadline=broker.Deadline.after_ms(3_000))
        thread.join(5)
        assert not thread.is_alive()
        assert type(outcome["error"]) is GatewayServiceError
        assert wire == [] and sc.closed
        assert type(right) is socket_module.socket



# --- stage C review closures: linearized control under contention (design §6) ---------------

def _outcome(call):
    try:
        return call()
    except BaseException as error:  # noqa: BLE001 - the outcome is the fact
        return error


def gated_service_cancel(monkeypatch, send, *, entered, release):
    """The gateway's own cancel is held between the client's cancel frame and its
    acknowledgement: the exact window in which a competing local call can run."""
    original = ProviderSendService.cancel

    def gated(self, exchange_id, reason):
        if self is send:
            entered.set()
            assert release.wait(5)
        return original(self, exchange_id, reason)

    monkeypatch.setattr(ProviderSendService, "cancel", gated)


def test_a_losing_commit_never_closes_the_in_flight_ready_cancel(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        entered, release = threading.Event(), threading.Event()
        gated_service_cancel(monkeypatch, send, entered=entered, release=release)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            acks = []
            cancel = threading.Thread(target=lambda: acks.append(_outcome(
                lambda: client.cancel(ready["exchange_id"], "user_requested"))), daemon=True)
            cancel.start()
            assert entered.wait(2)  # the ready-cancel has claimed and is blocked in its acknowledgement read
            # the runtime's shape: the dispatch thread enters commit while the controller's cancel
            # is in flight — the loser is refused locally and touches nothing of the winner
            for _ in range(2):  # and the refusal is repeatable
                with pytest.raises(ProviderSendError, match="not ready to commit"):
                    client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            assert client._channel is not None and client._channel["state"] == "cancelling"
            release.set()
            cancel.join(5)
            assert not cancel.is_alive()
            assert type(acks[0]).__name__ == "ProviderSendCancellation"
            assert acks[0].accepted is True and acks[0].phase == "not_sent"
            assert client._channel is None
            assert send.status(ready["exchange_id"]) == "unknown"  # the validated observation was kept
            assert served.join() == []
        assert captures == []


def test_a_duplicate_commit_is_refused_without_closing_the_committing_dialogue(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}"), blocked=True) as (port, captures, entered, release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress, deadline_ms=6_000) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=4_000))
            outcomes = []
            thread = threading.Thread(target=lambda: outcomes.append(_outcome(
                lambda: client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))))), daemon=True)
            thread.start()
            assert entered.wait(2)
            with pytest.raises(ProviderSendError, match="not ready to commit"):
                client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            assert client.status(ready["exchange_id"]) == "running"  # the first commit is untouched
            release.set()
            thread.join(6)
            assert not thread.is_alive()
            assert served.join() == []
        assert type(outcomes[0]).__name__ == "ProviderSendObservation"
        assert outcomes[0].status == 200 and outcomes[0].body == b"{}"
        assert len(captures) == 1


def test_a_failed_cancel_frame_write_closes_the_dialogue_and_maps_the_fault(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(2)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            owner = client._channel["connection"]
            original_write = type(owner).write

            def failing_write(self, **kwargs):
                if self is owner:
                    raise broker.TransportUncertain(dispatch_effect="may_have_started")
                return original_write(self, **kwargs)

            monkeypatch.setattr(type(owner), "write", failing_write)
            with pytest.raises(ProviderSendError) as failure:
                client.cancel(ready["exchange_id"], "user_requested")
            monkeypatch.setattr(type(owner), "write", original_write)
            assert failure.value.failure_class == "dependency_unavailable"
            assert client._channel is None and owner.closed  # never a dead cancelling dialogue
            # the reused client (the runtime holds one for the process lifetime) starts the next
            # dialogue instead of "already active" for ever
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            observed = client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
            assert observed.status == 200
            errors = served.join()
        assert len(errors) == 1 and isinstance(errors[0], ProviderSendError)  # the cut first dialogue
        assert len(captures) == 1


def test_an_expired_deadline_is_mapped_on_every_owned_entry(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        # prepare under an anchor already in the past: the owned client's own class, never the
        # broker's raw exception
        with pytest.raises(ProviderSendError) as failure:
            client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000),
                           deadline_end_monotonic=time.monotonic() - 1.0)
        assert failure.value.failure_class == "deadline_exceeded"
        assert client._channel is None
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=400))
            time.sleep(0.5)  # the ready deadline elapses before any control call
            with pytest.raises(ProviderSendError) as failure:
                client.cancel(ready["exchange_id"], "user_requested")
            assert failure.value.failure_class == "deadline_exceeded"
            with pytest.raises(ProviderSendError) as failure:
                client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            assert failure.value.failure_class in ("deadline_exceeded", "no_dialogue") or "no ready" in str(failure.value)
            client.abandon()
            served.join()
        assert captures == []


@pytest.mark.parametrize("fault", [OSError, RuntimeError])
def test_a_ready_cancel_cleanup_failure_of_any_local_kind_keeps_the_cancellation(tmp_path, tmp_path_factory, monkeypatch, fault):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            owner = client._channel["connection"]
            original_close = type(owner).close

            def failing_close(self):
                original_close(self)
                if self is owner:
                    raise fault("OWNER CLOSE")

            monkeypatch.setattr(type(owner), "close", failing_close)
            with pytest.raises(ProviderSendCleanupAfterCancellation) as failure:
                client.cancel(ready["exchange_id"], "user_requested")
            monkeypatch.setattr(type(owner), "close", original_close)
            assert failure.value.cancellation_observation.accepted is True
            assert failure.value.cancellation_observation.phase == "not_sent"
            assert failure.value.__cause__ is None
            assert client._channel is None and owner.closed
            assert served.join() == []
        assert captures == []


@pytest.mark.parametrize("fault", [OSError, RuntimeError])
def test_an_exchange_cleanup_failure_of_any_local_kind_keeps_the_observation(tmp_path, tmp_path_factory, monkeypatch, fault):
    payload = b"event: ping\ndata: {}\n\n"
    with controlled_upstream(response=(200, "text/event-stream", payload)) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
            owner = client._channel["connection"]
            original_close = type(owner).close

            def failing_close(self):
                original_close(self)
                if self is owner:
                    raise fault("OWNER CLOSE")

            monkeypatch.setattr(type(owner), "close", failing_close)
            with pytest.raises(ProviderSendError) as failure:
                client.exchange(lease)
            monkeypatch.setattr(type(owner), "close", original_close)
            assert str(failure.value) == "provider send cleanup failed after the observation"
            assert failure.value.failure_class == "internal_failure"
            assert failure.value.status == 200 and failure.value.body == payload
            assert failure.value.phase == "terminal_observed" and failure.value.media_type == "text/event-stream"
            assert failure.value.__cause__ is None
            assert client._channel is None and owner.closed
            assert served.join() == []
        assert len(captures) == 1


def test_abandon_swallows_any_local_cleanup_failure(tmp_path, tmp_path_factory, monkeypatch):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, 1)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            owner = client._channel["connection"]
            original_close = type(owner).close

            def failing_close(self):
                original_close(self)
                if self is owner:
                    raise RuntimeError("OWNER CLOSE")

            monkeypatch.setattr(type(owner), "close", failing_close)
            client.abandon()
            monkeypatch.setattr(type(owner), "close", original_close)
            assert client._channel is None and owner.closed
            served.join()


def test_a_malformed_acknowledgement_from_the_gateway_is_an_integrity_failure(tmp_path, tmp_path_factory, monkeypatch):
    import app.workers.provider_send_service as service_module

    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        original = service_module.encode_op

        def corrupting_encode(value):
            if value.get("schema") == "provider-send-cancelled-v1":
                return b'{"schema":"provider-send-cancelled-v1",'  # the peer's frame is not strict JSON
            return original(value)

        monkeypatch.setattr(service_module, "encode_op", corrupting_encode)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            with pytest.raises(ProviderSendError) as failure:
                client.cancel(ready["exchange_id"], "user_requested")
            assert failure.value.failure_class == "integrity_failed"
            assert client._channel is None
            served.join()
        assert captures == []


def test_a_peer_that_closes_before_its_acknowledgement_is_never_a_claimed_cancellation(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        original = ProviderSendService.cancel

        def failing_cancel(self, exchange_id, reason):
            if self is send:
                raise ProviderSendError("test-owned gateway cancel failure")  # the gateway closes with no ack
            return original(self, exchange_id, reason)

        monkeypatch.setattr(ProviderSendService, "cancel", failing_cancel)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            with pytest.raises(ProviderSendError) as failure:
                client.cancel(ready["exchange_id"], "user_requested")
            assert failure.value.failure_class == "dependency_unavailable"  # the real peer EOF, mapped
            assert client._channel is None
            errors = served.join()
        assert len(errors) == 1 and str(errors[0]) == "test-owned gateway cancel failure"
        assert captures == []


def test_a_cancel_during_a_body_blocked_exchange_is_acknowledged_may_have_sent(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "text/event-stream", b"event: ping\ndata: {}\n\n"), blocked=True, block_phase="body") as (port, captures, entered, release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress, deadline_ms=6_000) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=4_000))
            outcomes = []
            thread = threading.Thread(target=lambda: outcomes.append(_outcome(
                lambda: client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))))), daemon=True)
            thread.start()
            assert entered.wait(2)  # the headers are out, the body is held
            cancelled = client.cancel(ready["exchange_id"], "user_requested")
            assert cancelled.accepted is True and cancelled.phase == "may_have_sent"
            thread.join(6)
            release.set()
            assert not thread.is_alive()
            errors = served.join()
        assert all(isinstance(error, ProviderSendError) for error in errors) and len(errors) <= 1
        assert type(outcomes[0]).__name__ == "ProviderSendObservation"
        assert outcomes[0].cancel_observed is True and outcomes[0].phase == "may_have_sent"
        assert len(captures) == 1


def test_a_cancel_during_the_owned_result_stream_is_a_terminal_acknowledgement(tmp_path, tmp_path_factory, monkeypatch):
    import app.workers.provider_send_client as client_module

    response = b"event: ping\ndata: {}\n\n" + b"x" * 70_000
    with controlled_upstream(response=(200, "text/event-stream", response)) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        credit_ready, release_credit, cancel_written = (threading.Event() for _ in range(3))
        original_send = client_module._CoreStreamTransport.send
        held = []

        def hold_first_result_credit(transport, payload):
            if transport.channel is not None and not held and b'"type":"artifact-credit"' in payload:
                held.append(True)
                credit_ready.set()
                assert release_credit.wait(2)
            return original_send(transport, payload)

        monkeypatch.setattr(client_module._CoreStreamTransport, "send", hold_first_result_credit)
        original_write = listener.AuthenticatedConnection.write

        def observe_cancel_write(connection, **kwargs):
            result = original_write(connection, **kwargs)
            if b'"schema":"provider-send-cancel-v1"' in kwargs["payload"]:
                cancel_written.set()
            return result

        monkeypatch.setattr(listener.AuthenticatedConnection, "write", observe_cancel_write)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            committed, cancelled = [], []
            commit = threading.Thread(target=lambda: committed.append(_outcome(
                lambda: client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))), daemon=True)
            commit.start()
            assert credit_ready.wait(2)
            cancel = threading.Thread(target=lambda: cancelled.append(_outcome(
                lambda: client.cancel(ready["exchange_id"], "user_requested"))), daemon=True)
            cancel.start()
            assert cancel_written.wait(2)
            release_credit.set()
            commit.join(3)
            cancel.join(3)
            assert not commit.is_alive() and not cancel.is_alive()
            assert type(committed[0]).__name__ == "_RemoteLease"
            assert type(cancelled[0]).__name__ == "ProviderSendCancellation"
            assert cancelled[0].accepted is False and cancelled[0].phase == "terminal_observed"
            assert client.exchange(committed[0]).body == response
            assert served.join() == []
        assert len(captures) == 1


def test_the_send_service_publishes_its_usability(tmp_path, tmp_path_factory, monkeypatch):
    with gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, _meta, _record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, send, _ingress = send_services(vault, spec, 1)
        assert send.usable is True
        with pytest.raises(AttributeError):
            send.usable = False  # a read-only fact, never a caller's decision


def test_a_stream_transport_deadline_during_the_body_is_mapped_to_the_deadline_class(tmp_path, tmp_path_factory, monkeypatch):
    body = b"x" * 40_000  # several chunks
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        original_write = listener.AuthenticatedConnection.write
        fired = []

        def faulting_write(self, **kwargs):
            if b'"type":"artifact-chunk"' in kwargs["payload"] and not fired:
                fired.append(1)
                raise broker.DeadlineExceeded(dispatch_effect="outcome_unknown")
            return original_write(self, **kwargs)

        monkeypatch.setattr(listener.AuthenticatedConnection, "write", faulting_write)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            with pytest.raises(ProviderSendError) as failure:
                client.prepare(prepared(meta, record, handle, pin, body=body, remaining_ms=5_000))
            # the stream engine's wrapper never hides the broker's own category from the owned client
            assert failure.value.failure_class == "deadline_exceeded"
            assert client._channel is None
            served.join()
        assert captures == []


def test_a_malformed_result_stream_frame_is_an_integrity_failure(tmp_path, tmp_path_factory, monkeypatch):
    import app.workers.provider_send_service as service_module

    with controlled_upstream(response=(200, "application/json", b"{}" * 10)) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        original_send = service_module._GatewayStreamTransport.send

        def corrupting_send(self, payload):
            return original_send(self, payload.replace(b'"type":"artifact-chunk"', b'"type":"artifact-chonk"'))

        monkeypatch.setattr(service_module._GatewayStreamTransport, "send", corrupting_send)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            with pytest.raises(ProviderSendError) as failure:
                client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
            assert failure.value.failure_class == "integrity_failed"
            assert client._channel is None
            served.join()
        assert len(captures) == 1


def test_a_stale_caller_never_closes_a_successor_dialogue(tmp_path, tmp_path_factory, monkeypatch):
    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(2)
            first = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            first_channel = client._channel
            first_owner = first_channel["connection"]
            original_write = listener.AuthenticatedConnection.write

            def failing_write(self, **kwargs):
                if self is first_owner and b"provider-send-cancel-v1" in kwargs["payload"]:
                    raise broker.TransportUncertain(dispatch_effect="may_have_started")
                return original_write(self, **kwargs)

            monkeypatch.setattr(listener.AuthenticatedConnection, "write", failing_write)
            original_cleanup = ProviderSendClient._close_quietly
            successor = {}

            def interleaved_cleanup(self, channel=None):
                if channel is first_channel and not successor:
                    # the interleaving: between the stale cancel's fault and its cleanup, another
                    # thread ends the first dialogue and the runtime's next send prepares the
                    # second — the stale caller's cleanup must be bound to its own dialogue
                    successor["abandoned"] = True
                    client.abandon()
                    successor["ready"] = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
                    successor["channel"] = client._channel
                return original_cleanup(self, channel)

            monkeypatch.setattr(ProviderSendClient, "_close_quietly", interleaved_cleanup)
            with pytest.raises(ProviderSendError) as failure:
                client.cancel(first["exchange_id"], "user_requested")
            monkeypatch.setattr(listener.AuthenticatedConnection, "write", original_write)
            monkeypatch.setattr(ProviderSendClient, "_close_quietly", original_cleanup)
            assert failure.value.failure_class == "dependency_unavailable"
            assert first_owner.closed
            assert client._channel is successor["channel"] and successor["channel"]["state"] == "ready"
            ready = successor["ready"]
            observed = client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4())))
            assert observed.status == 200
            errors = served.join()
        assert len(errors) == 1 and isinstance(errors[0], ProviderSendError)  # the abandoned first dialogue
        assert len(captures) == 1


def test_the_state_claim_order_is_the_wire_order(tmp_path, tmp_path_factory, monkeypatch):
    import app.workers.provider_send_client as client_module

    with controlled_upstream(response=(200, "application/json", b"{}")) as (port, captures, _entered, _release), \
            gateway_pair(tmp_path_factory.mktemp("pair"), monkeypatch) as (root, spec), \
            encrypted_credential(tmp_path) as (vault, meta, record):
        fixed_profile_into(monkeypatch, root, spec)
        _credential, _send, ingress = send_services(vault, spec, port)
        handle, pin, _, _ = connection_values(meta, record)
        client = ProviderSendClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=5_000)
        with served_gateway(root, spec, ingress) as served:
            served.serve(1)
            ready = client.prepare(prepared(meta, record, handle, pin, remaining_ms=5_000))
            channel = client._channel
            claimed, cancel_started = threading.Event(), threading.Event()
            commit_thread = {}
            original_enter = client_module._bounded.__enter__

            def paused_enter(self):
                # the commit thread, after its state claim and before its frame: a cancel
                # started here must not reach the wire first
                if (self._lock is channel["write_lock"] and threading.current_thread() is commit_thread.get("thread")
                        and not claimed.is_set()):
                    claimed.set()
                    cancel_started.wait(2)
                    time.sleep(0.3)
                return original_enter(self)

            monkeypatch.setattr(client_module._bounded, "__enter__", paused_enter)
            wire = []
            original_write = listener.AuthenticatedConnection.write

            def observing_write(self, **kwargs):
                result = original_write(self, **kwargs)
                for name in ("provider-send-commit-v1", "provider-send-cancel-v1"):
                    if name.encode() in kwargs["payload"]:
                        wire.append(name)
                return result

            monkeypatch.setattr(listener.AuthenticatedConnection, "write", observing_write)
            outcomes, acks = [], []
            thread = threading.Thread(target=lambda: outcomes.append(_outcome(
                lambda: client.exchange(client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))))), daemon=True)
            commit_thread["thread"] = thread
            thread.start()
            assert claimed.wait(3)
            cancel = threading.Thread(target=lambda: acks.append(_outcome(
                lambda: client.cancel(ready["exchange_id"], "user_requested"))), daemon=True)
            cancel.start()
            cancel_started.set()
            thread.join(6)
            cancel.join(6)
            assert not thread.is_alive() and not cancel.is_alive()
            assert wire[:2] == ["provider-send-commit-v1", "provider-send-cancel-v1"]
            # the claim winner's frame leads: the commit observes its own exchange, never a
            # transport failure standing in for the loser's cancel
            assert type(outcomes[0]).__name__ == "ProviderSendObservation", (outcomes, acks, served.join())
            assert type(acks[0]).__name__ == "ProviderSendCancellation"
            errors = served.join()
        assert len(errors) <= 1 and all(isinstance(error, ProviderSendError) for error in errors)
        # the cancel that follows the commit on the wire is answered by the gateway's own
        # exchange: either before the HTTP write (not sent, cancel observed) or after it
        assert len(captures) <= 1
        if not captures:
            assert outcomes[0].phase == "not_sent" and outcomes[0].cancel_observed is True
