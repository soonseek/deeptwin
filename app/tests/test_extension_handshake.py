"""Task 25 slice 2a: the private extension handshake continuation
(contracts/extension-worker-probe.md §1/§4; proposal §2).

The existing `server_handshake` needs the requester boot ID a priori; a
fresh control observer cannot know it. The extension server wrapper reads
the proposed requester boot ID from the actual bounded hello, validates its
grammar and inequality with the responder ID, reconstructs the complete
expected hello and verifies the existing HMAC proof against it, then runs
the unchanged challenge/finish/session continuation. Packets are capped at
4096 B. The public wrappers keep their exact semantics.

macOS honesty: peer credentials are unavailable here, so the wrappers are
asserted to fail closed; the continuation is exercised over a real
socketpair with the existing `verify_peer=False` implementation seam, which
is handshake logic, never positive Linux authentication.
"""

import secrets
import socket
import sys
import threading

import pytest

from app.workers import broker
from app.workers.extension_channel import extension_channel

INSTANCE = "0123456789abcdef0123456789abcdef"
_ROOT, SPEC = extension_channel(instance_id=INSTANCE, slot_number=3)
EXTENSION_HANDSHAKE_PACKET_BYTES = 4096


def boot_id():
    return secrets.token_hex(32)


def deadline():
    return broker.Deadline.after_ms(5_000)


def run_client(sock, secret, *, requester_boot_id, responder_boot_id, spec=SPEC, box):
    def body():
        try:
            box["session"] = broker._extension_client_handshake_impl(
                sock,
                spec,
                secret,
                requester_boot_id=requester_boot_id,
                responder_boot_id=responder_boot_id,
                deadline=deadline(),
                verify_peer=False,
            )
        except BaseException as error:  # noqa: BLE001 - surfaced to the test thread
            box["error"] = error

    thread = threading.Thread(target=body, daemon=True)
    thread.start()
    return thread


def test_the_server_learns_a_fresh_requester_boot_id_from_the_actual_hello():
    secret = broker.BootSecret.generate()
    responder = boot_id()
    for _ in range(2):
        # two different control boots authenticate in turn: no allowlist, no
        # prior knowledge of the requester ID on the worker side
        requester = boot_id()
        client, server = socket.socketpair()
        box = {}
        try:
            thread = run_client(
                client,
                secret,
                requester_boot_id=requester,
                responder_boot_id=responder,
                box=box,
            )
            session = broker._extension_server_handshake_impl(
                server,
                SPEC,
                secret,
                responder_boot_id=responder,
                deadline=deadline(),
                verify_peer=False,
            )
            thread.join(5)
            assert not thread.is_alive()
        finally:
            client.close()
            server.close()
        assert "error" not in box, box.get("error")
        assert type(session) is broker.AuthenticatedSession
        assert session.requester_boot_id == requester
        assert session.responder_boot_id == responder
        assert session.local_service == SPEC.responder_service
        assert session.channel_spec_sha256 == broker._spec_digest(SPEC)
        peer = box["session"]
        assert peer.connection_id == session.connection_id
        assert (
            peer.requester_boot_id == requester
            and peer.local_service == SPEC.requester_service
        )


def test_the_public_handshake_still_requires_its_expected_requester_id():
    # the existing wrapper's semantics are untouched: a mismatching expected
    # requester ID fails exactly as before
    secret = broker.BootSecret.generate()
    responder, requester = boot_id(), boot_id()
    client, server = socket.socketpair()
    box = {}
    thread = None
    try:
        thread = run_client(
            client,
            secret,
            requester_boot_id=requester,
            responder_boot_id=responder,
            box=box,
        )
        with pytest.raises(broker.AuthenticationError):
            broker._server_handshake_impl(
                server,
                SPEC,
                secret,
                requester_boot_id=boot_id(),  # not the one the client uses
                responder_boot_id=responder,
                deadline=deadline(),
                verify_peer=False,
            )
    finally:
        client.close()
        server.close()
        if thread is not None:
            thread.join(5)
            assert not thread.is_alive()


def _hello_from(client_boot, responder, secret, spec=SPEC, challenge=None):
    challenge = challenge or secrets.token_bytes(broker.AUTH_CHALLENGE_BYTES)
    hello = broker._hello_base(spec, "requester-hello", client_boot, responder)
    hello["requester_challenge"] = broker._canonical_b64(challenge)
    hello["proof"] = broker._proof(
        secret,
        broker._auth_context(
            spec,
            phase="requester-hello",
            requester_boot_id=client_boot,
            responder_boot_id=responder,
            requester_challenge=challenge,
            responder_challenge=None,
            role="requester",
        ),
    )
    return hello


def _serve(server, secret, responder, **overrides):
    return broker._extension_server_handshake_impl(
        server,
        SPEC,
        secret,
        responder_boot_id=responder,
        deadline=deadline(),
        verify_peer=False,
        **overrides,
    )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda hello, responder: hello.update(
            requester_boot_id=responder
        ),  # equal boots
        lambda hello, responder: hello.update(
            requester_boot_id=boot_id()
        ),  # a genuine proof for boot A relabelled as boot B
        lambda hello, responder: hello.update(requester_boot_id="bad boot id!"),
        lambda hello, responder: hello.update(requester_boot_id=""),
        lambda hello, responder: hello.update(requester_boot_id=None),
        lambda hello, responder: hello.pop("requester_boot_id"),
        lambda hello, responder: hello.update(channel_id="cp-other"),
        lambda hello, responder: hello.update(proof="0" * 64),
        lambda hello, responder: hello.update(phase="requester-finish"),
        lambda hello, responder: hello.update(extra=1),
    ],
)
def test_a_hello_that_does_not_prove_its_own_boot_id_is_refused(mutate):
    secret = broker.BootSecret.generate()
    responder = boot_id()
    hello = _hello_from(boot_id(), responder, secret)
    mutate(hello, responder)
    client, server = socket.socketpair()
    try:
        writer = threading.Thread(
            target=lambda: broker.write_packet(client, hello, deadline()), daemon=True
        )
        writer.start()
        with pytest.raises(broker.AuthenticationError) as failure:
            _serve(server, secret, responder)
        writer.join(5)
        assert not writer.is_alive()
    finally:
        client.close()
        server.close()
    # every rejection after the hello was read is an unknown-outcome effect,
    # exactly as the public path classifies the same failures
    assert failure.value.dispatch_effect == "outcome_unknown"


def test_a_replayed_old_hello_cannot_answer_the_fresh_challenge():
    # a hello captured from an earlier genuine connection passes the hello
    # check (it proves its own boot id) but the replayer cannot produce the
    # finish for the responder's fresh challenge: the best it holds is a
    # GENUINE finish proof for some other responder challenge
    secret = broker.BootSecret.generate()
    responder, requester = boot_id(), boot_id()
    challenge = secrets.token_bytes(broker.AUTH_CHALLENGE_BYTES)
    captured = _hello_from(requester, responder, secret, challenge=challenge)
    client, server = socket.socketpair()
    box = {}
    try:

        def replay():
            broker.write_packet(client, captured, deadline())
            response = broker.read_packet(client, deadline())
            box["phase"] = response.get("phase")
            old_responder_challenge = secrets.token_bytes(broker.AUTH_CHALLENGE_BYTES)
            stale = broker._hello_base(SPEC, "requester-finish", requester, responder)
            stale["requester_challenge"] = captured["requester_challenge"]
            stale["responder_challenge"] = broker._canonical_b64(
                old_responder_challenge
            )
            stale["proof"] = broker._proof(
                secret,
                broker._auth_context(
                    SPEC,
                    phase="requester-finish",
                    requester_boot_id=requester,
                    responder_boot_id=responder,
                    requester_challenge=challenge,
                    responder_challenge=old_responder_challenge,
                    role="requester",
                ),
            )
            broker.write_packet(client, stale, deadline())

        thread = threading.Thread(target=replay, daemon=True)
        thread.start()
        with pytest.raises(broker.AuthenticationError) as failure:
            _serve(server, secret, responder)
        thread.join(5)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()
    # the hello itself was accepted (the responder answered), the finish was not
    assert box["phase"] == "responder-hello"
    assert failure.value.dispatch_effect == "outcome_unknown"


def test_handshake_packets_are_capped_at_4096_bytes():
    secret = broker.BootSecret.generate()
    responder = boot_id()
    hello = _hello_from(boot_id(), responder, secret)
    hello["padding"] = "x" * 5000
    client, server = socket.socketpair()
    try:
        writer = threading.Thread(
            target=lambda: broker.write_packet(client, hello, deadline()), daemon=True
        )
        writer.start()
        with pytest.raises(broker.ProtocolViolation):
            _serve(server, secret, responder)
        writer.join(5)
        assert not writer.is_alive()
    finally:
        client.close()
        server.close()
    # the client side refuses an oversized responder packet the same way
    client, server = socket.socketpair()
    box = {}
    try:
        thread = run_client(
            client,
            secret,
            requester_boot_id=boot_id(),
            responder_boot_id=responder,
            box=box,
        )
        broker.read_packet(server, deadline())
        broker.write_packet(server, {"padding": "x" * 5000}, deadline())
        thread.join(5)
        assert not thread.is_alive()
    finally:
        client.close()
        server.close()
    assert type(box.get("error")) is broker.ProtocolViolation


def test_only_the_extension_profile_is_accepted():
    secret = broker.BootSecret.generate()
    responder = boot_id()
    other = broker.ChannelSpec(
        channel_id="control-document",
        requester_service="control",
        responder_service="document",
        request_direction="control-to-document",
        protocol_id="document-command-v1",
        requester_uid=10_001,
        requester_gid=10_002,
        responder_uid=10_003,
        responder_gid=10_004,
        pair_gid=10_005,
        pair_root=SPEC.pair_root,
        socket_name="document.sock",
        root_uid=10_003,
        root_gid=10_005,
        socket_uid=10_003,
        socket_gid=10_005,
        requester_message_types=("execute",),
        responder_message_types=("completed", "failed"),
    )
    client, server = socket.socketpair()
    try:
        with pytest.raises(broker.ChannelConfigurationError):
            broker._extension_server_handshake_impl(
                server,
                other,
                secret,
                responder_boot_id=responder,
                deadline=deadline(),
                verify_peer=False,
            )
        with pytest.raises(broker.ChannelConfigurationError):
            broker._extension_client_handshake_impl(
                client,
                other,
                secret,
                requester_boot_id=boot_id(),
                responder_boot_id=responder,
                deadline=deadline(),
                verify_peer=False,
            )
    finally:
        client.close()
        server.close()


@pytest.mark.skipif(
    sys.platform == "linux", reason="positive peer credentials are a Linux gate"
)
def test_the_wrappers_fail_closed_without_peer_credentials():
    secret = broker.BootSecret.generate()
    client, server = socket.socketpair()
    try:
        with pytest.raises(broker.PeerCredentialError):
            broker._extension_server_handshake(
                server, SPEC, secret, responder_boot_id=boot_id(), deadline=deadline()
            )
        with pytest.raises(broker.PeerCredentialError):
            broker._extension_client_handshake(
                client,
                SPEC,
                secret,
                requester_boot_id=boot_id(),
                responder_boot_id=boot_id(),
                deadline=deadline(),
            )
    finally:
        client.close()
        server.close()


def test_the_wrappers_expose_no_test_seams():
    import inspect

    for name in ("_extension_server_handshake", "_extension_client_handshake"):
        parameters = inspect.signature(getattr(broker, name)).parameters
        assert "verify_peer" not in parameters and "challenge_factory" not in parameters
        assert "requester_boot_id" not in parameters or name.endswith(
            "client_handshake"
        )
