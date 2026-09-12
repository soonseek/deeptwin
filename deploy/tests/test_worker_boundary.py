from __future__ import annotations

import ast
import copy
import hashlib
import hmac
import inspect
import json
import os
import pickle
import socket
import struct
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock
from uuid import uuid4

from app.workers import broker

REQUESTER_BOOT_ID = "control-boot-test"
RESPONDER_BOOT_ID = "browser-boot-test"


def _distinct_id(*excluded: int) -> int:
    for candidate in range(20_001, 20_016):
        if candidate not in excluded:
            return candidate
    raise RuntimeError("test identity range exhausted")


def channel_spec(root: Path) -> broker.ChannelSpec:
    current_uid, current_gid = os.getuid(), os.getgid()
    responder_uid = current_uid or _distinct_id(current_uid)
    requester_uid = _distinct_id(current_uid, responder_uid)
    pair_gid = next(
        (group for group in (current_gid, *os.getgroups()) if group > 0),
        _distinct_id(current_gid),
    )
    requester_gid = _distinct_id(current_gid, pair_gid)
    responder_gid = _distinct_id(current_gid, pair_gid, requester_gid)
    return broker.ChannelSpec(
        channel_id="control-browser",
        requester_service="control",
        responder_service="browser",
        request_direction="control-to-browser",
        protocol_id="browser-command-v1",
        requester_uid=requester_uid,
        requester_gid=requester_gid,
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
        pair_root=root,
        socket_name="browser.sock",
        root_uid=responder_uid,
        root_gid=pair_gid,
        socket_uid=responder_uid,
        socket_gid=pair_gid,
        requester_message_types=("cancel", "execute"),
        responder_message_types=("failed", "result"),
        max_queue_depth=2,
    )


def session_pair(
    spec: broker.ChannelSpec,
) -> tuple[broker.AuthenticatedSession, broker.AuthenticatedSession]:
    left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    secret = broker.BootSecret(b"k" * 32)
    server_output: list[broker.AuthenticatedSession] = []
    server_errors: list[BaseException] = []

    def serve() -> None:
        try:
            server_output.append(broker._server_handshake_impl(
                right,
                spec,
                secret,
                requester_boot_id=REQUESTER_BOOT_ID,
                responder_boot_id=RESPONDER_BOOT_ID,
                deadline=broker.Deadline.after_ms(1_000),
                verify_peer=False,
            ))
        except broker.BrokerError as error:
            server_errors.append(error)

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        client = broker._client_handshake_impl(
            left,
            spec,
            secret,
            requester_boot_id=REQUESTER_BOOT_ID,
            responder_boot_id=RESPONDER_BOOT_ID,
            deadline=broker.Deadline.after_ms(1_000),
            verify_peer=False,
        )
    finally:
        thread.join(2)
        left.close()
        right.close()
    if thread.is_alive():
        raise RuntimeError("synthetic handshake did not terminate")
    if server_errors:
        raise server_errors[0]
    if len(server_output) != 1:
        raise RuntimeError("synthetic handshake did not return a server session")
    return client, server_output[0]


def session() -> broker.AuthenticatedSession:
    return session_pair(channel_spec(Path("/tmp/deeptwin-test-session")))[0]


class ContractTests(unittest.TestCase):
    def test_constants_are_exact(self) -> None:
        self.assertEqual(broker.PROTOCOL_VERSION, "deeptwin-worker-ipc-v2")
        self.assertEqual(broker.MAX_FRAME_BYTES, 65_536)
        self.assertEqual(broker.AUTH_SECRET_BYTES, 32)
        self.assertEqual(broker.AUTH_CHALLENGE_BYTES, 32)

    def test_channel_spec_is_exact_and_frozen(self) -> None:
        spec = channel_spec(Path("/tmp/deeptwin-test-pair"))
        with self.assertRaises(FrozenInstanceError):
            spec.channel_id = "other"  # type: ignore[misc]
        with self.assertRaises(broker.ChannelConfigurationError):
            channel_spec(Path("relative"))
        with self.assertRaises(broker.ChannelConfigurationError):
            broker.ChannelSpec(**{
                **{name: getattr(spec, name) for name in spec.__dataclass_fields__},
                "requester_uid": True,
            })
        with self.assertRaises(broker.ChannelConfigurationError):
            broker.ChannelSpec(**{
                **{name: getattr(spec, name) for name in spec.__dataclass_fields__},
                "requester_message_types": ("execute", "cancel"),
            })
        with self.assertRaises(broker.ChannelConfigurationError):
            broker.ChannelSpec(**{
                **{name: getattr(spec, name) for name in spec.__dataclass_fields__},
                "max_in_flight": 2,
            })
        with self.assertRaises(broker.ChannelConfigurationError):
            broker.ChannelSpec(**{
                **{name: getattr(spec, name) for name in spec.__dataclass_fields__},
                "max_in_flight": True,
            })
        invalid_overrides = (
            {"requester_uid": 0},
            {"responder_uid": 0},
            {"requester_gid": 0},
            {"responder_gid": 0},
            {"pair_gid": 0},
            {"requester_uid": spec.responder_uid},
            {"requester_gid": spec.responder_gid},
            {"pair_gid": spec.requester_gid},
            {"root_uid": spec.requester_uid},
            {"socket_uid": spec.requester_uid},
            {"root_gid": spec.requester_gid},
            {"socket_gid": spec.requester_gid},
            {"root_mode": 0o700},
            {"root_mode": 0o2770},
            {"socket_mode": 0o600},
            {"socket_mode": 0o666},
        )
        for override in invalid_overrides:
            with self.subTest(override=override), self.assertRaises(
                broker.ChannelConfigurationError
            ):
                broker.ChannelSpec(**{
                    **{name: getattr(spec, name) for name in spec.__dataclass_fields__},
                    **override,
                })

    def test_secret_and_session_are_immutable_redacted_and_not_picklable(self) -> None:
        secret = broker.BootSecret(b"s" * 32)
        authenticated = session()
        self.assertNotIn("ssss", repr(secret))
        self.assertNotIn("kkkk", repr(authenticated))
        self.assertFalse(hasattr(secret, "__dict__"))
        self.assertFalse(hasattr(authenticated, "__dict__"))
        with self.assertRaises(AttributeError):
            secret.value = b"x" * 32  # type: ignore[attr-defined]
        with self.assertRaises(AttributeError):
            authenticated.responder_boot_id = "other"
        with self.assertRaises(TypeError):
            pickle.dumps(secret)
        with self.assertRaises(TypeError):
            pickle.dumps(authenticated)
        with self.assertRaises(TypeError):
            copy.copy(authenticated)
        with self.assertRaises(TypeError):
            copy.deepcopy(authenticated)
        with self.assertRaises(TypeError):
            copy.copy(secret)
        with self.assertRaises(broker.ChannelConfigurationError):
            broker.BootSecret(b"short")
        with self.assertRaises(broker.AuthenticationError):
            broker.AuthenticatedSession(
                "1" * 64,
                REQUESTER_BOOT_ID,
                RESPONDER_BOOT_ID,
                b"k" * 32,
                channel_spec_sha256="2" * 64,
                local_service="control",
            )

    def test_errors_expose_only_stable_code_and_effect(self) -> None:
        error = broker.TransportUncertain(dispatch_effect="may_have_started")
        self.assertEqual(str(error), "transport_uncertain")
        self.assertEqual(error.dispatch_effect, "may_have_started")
        self.assertNotIn("/", repr(error))

        private_body = b'{"private":"secret",}'
        with self.assertRaises(broker.ProtocolViolation) as malformed:
            broker._decode_canonical_json(private_body)
        self.assertIsNone(malformed.exception.__cause__)
        self.assertIsNone(malformed.exception.__context__)
        self.assertNotIn("private", repr(malformed.exception))

        with self.assertRaises(broker.EndpointViolation) as missing:
            broker.validate_endpoint(channel_spec(Path("/private/missing/secret")))
        self.assertIsNone(missing.exception.__cause__)
        self.assertIsNone(missing.exception.__context__)
        self.assertNotIn("missing", repr(missing.exception))


class EndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="deeptwin-worker-test-")
        self.root = Path(self.temporary.name).resolve(strict=True)
        spec = channel_spec(self.root)
        if os.getuid() == 0:
            os.chown(self.root, spec.root_uid, spec.root_gid)
        elif os.stat(self.root).st_gid != spec.root_gid:
            os.chown(self.root, -1, spec.root_gid)
        os.chmod(self.root, 0o2710)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _socket(self, name: str = "browser.sock") -> socket.socket:
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.root / name))
        spec = channel_spec(self.root)
        if os.getuid() == 0:
            os.chown(self.root / name, spec.socket_uid, spec.socket_gid)
        elif os.stat(self.root / name).st_gid != spec.socket_gid:
            os.chown(self.root / name, -1, spec.socket_gid)
        os.chmod(self.root / name, 0o660)
        return server

    def test_exact_socket_inode_is_accepted(self) -> None:
        server = self._socket()
        try:
            identity = broker.validate_endpoint(channel_spec(self.root))
            self.assertGreater(identity.inode, 0)
            self.assertEqual(identity.mode, 0o660)
            self.assertEqual(identity.uid, channel_spec(self.root).responder_uid)
        finally:
            server.close()

    def test_regular_file_symlink_and_wrong_mode_are_rejected(self) -> None:
        regular = self.root / "browser.sock"
        regular.write_bytes(b"not a socket")
        os.chmod(regular, 0o660)
        with self.assertRaises(broker.EndpointViolation):
            broker.validate_endpoint(channel_spec(self.root))
        regular.unlink()

        target = self.root / "target.sock"
        server = self._socket("target.sock")
        try:
            os.symlink(target.name, regular)
            with self.assertRaises(broker.EndpointViolation):
                broker.validate_endpoint(channel_spec(self.root))
            regular.unlink()
            os.rename(target, regular)
            os.chmod(regular, 0o666)
            with self.assertRaises(broker.EndpointViolation):
                broker.validate_endpoint(channel_spec(self.root))
        finally:
            server.close()

    def test_pair_root_symlink_is_rejected(self) -> None:
        real = self.root / "real"
        real.mkdir(mode=0o2710)
        link = self.root / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(broker.EndpointViolation):
            broker.validate_endpoint(channel_spec(link))

    def test_intermediate_directory_symlink_and_parent_traversal_are_rejected(self) -> None:
        real_parent = self.root / "real-parent"
        real_parent.mkdir(mode=0o2710)
        pair = real_parent / "pair"
        pair.mkdir(mode=0o2710)
        linked_parent = self.root / "linked-parent"
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        with self.assertRaises(broker.EndpointViolation):
            broker.validate_endpoint(channel_spec(linked_parent / "pair"))

        spec = channel_spec(self.root)
        object.__setattr__(spec, "pair_root", self.root / "child" / "..")
        with self.assertRaises(broker.ChannelConfigurationError):
            spec.__post_init__()

    @unittest.skipUnless(
        sys.platform == "linux" and hasattr(socket, "SO_PEERCRED"),
        "Linux SO_PEERCRED is the only release qualification path",
    )
    def test_verified_connect_rejects_wrong_linux_primary_identity(self) -> None:
        server = self._socket()
        server.listen(1)
        accepted: list[socket.socket] = []

        def accept() -> None:
            connection, _ = server.accept()
            accepted.append(connection)

        thread = threading.Thread(target=accept)
        thread.start()
        try:
            self.assertGreater(broker.validate_endpoint(channel_spec(self.root)).inode, 0)
            with self.assertRaises(broker.PeerCredentialError):
                broker.connect_verified(
                    channel_spec(self.root),
                    local_service="control",
                    deadline=broker.Deadline.after_ms(2_000),
                )
        finally:
            thread.join(2)
            for connection in accepted:
                connection.close()
            server.close()


class FramingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.left, self.right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)

    def tearDown(self) -> None:
        self.left.close()
        self.right.close()

    def test_packet_round_trip_uses_big_endian_length_and_canonical_json(self) -> None:
        broker.write_packet(
            self.left,
            {"z": "한글", "a": 1},
            broker.Deadline.after_ms(1_000),
        )
        self.assertEqual(
            broker.read_packet(self.right, broker.Deadline.after_ms(1_000)),
            {"a": 1, "z": "한글"},
        )

    def test_zero_oversize_truncated_duplicate_and_noncanonical_frames_fail(self) -> None:
        cases = [
            struct.pack(">I", 0),
            struct.pack(">I", broker.MAX_FRAME_BYTES + 1),
            struct.pack(">I", 5) + b"{}",
            struct.pack(">I", 13) + b'{"a":1,"a":2}',
            struct.pack(">I", 8) + b'{"a": 1}',
        ]
        for wire in cases:
            left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
            with self.subTest(wire=wire[:8]):
                left.sendall(wire)
                left.shutdown(socket.SHUT_WR)
                with self.assertRaises(broker.BrokerError):
                    broker.read_packet(right, broker.Deadline.after_ms(200))
            left.close()
            right.close()

    def test_deep_json_and_invalid_frame_limit_fail_closed(self) -> None:
        nested: object = 0
        for _ in range(40):
            nested = {"x": nested}
        body = json.dumps(nested, separators=(",", ":")).encode()
        self.left.sendall(struct.pack(">I", len(body)) + body)
        with self.assertRaises(broker.ProtocolViolation):
            broker.read_packet(self.right, broker.Deadline.after_ms(200))
        with self.assertRaises(broker.ProtocolViolation):
            broker.write_packet(
                self.left,
                {"a": 1},
                broker.Deadline.after_ms(200),
                max_frame_bytes=True,
            )

    def test_expired_deadline_distinguishes_send_from_receive(self) -> None:
        expired = broker.Deadline(1.0)
        with self.assertRaises(broker.DeadlineExceeded) as send_error:
            broker.write_packet(self.left, {"a": 1}, expired)
        self.assertEqual(send_error.exception.dispatch_effect, "definitely_not_sent")
        with self.assertRaises(broker.DeadlineExceeded) as receive_error:
            broker.read_packet(self.right, expired)
        self.assertEqual(receive_error.exception.dispatch_effect, "outcome_unknown")


class HandshakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = channel_spec(Path("/tmp/deeptwin-handshake"))

    def _handshake(
        self,
        *,
        client_spec: broker.ChannelSpec | None = None,
        server_spec: broker.ChannelSpec | None = None,
        client_secret: broker.BootSecret | None = None,
        server_secret: broker.BootSecret | None = None,
        client_requester_boot_id: str = REQUESTER_BOOT_ID,
        client_responder_boot_id: str = RESPONDER_BOOT_ID,
        server_requester_boot_id: str = REQUESTER_BOOT_ID,
        server_responder_boot_id: str = RESPONDER_BOOT_ID,
    ) -> tuple[broker.AuthenticatedSession, broker.AuthenticatedSession]:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        shared = broker.BootSecret(b"a" * 32)
        output: list[broker.AuthenticatedSession] = []
        errors: list[BaseException] = []

        def serve() -> None:
            try:
                output.append(broker._server_handshake_impl(
                    right,
                    server_spec or self.spec,
                    server_secret or shared,
                    requester_boot_id=server_requester_boot_id,
                    responder_boot_id=server_responder_boot_id,
                    deadline=broker.Deadline.after_ms(1_000),
                    challenge_factory=lambda size: b"s" * size,
                    verify_peer=False,
                ))
            except broker.BrokerError as exc:
                errors.append(exc)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            client = broker._client_handshake_impl(
                left,
                client_spec or self.spec,
                client_secret or shared,
                requester_boot_id=client_requester_boot_id,
                responder_boot_id=client_responder_boot_id,
                deadline=broker.Deadline.after_ms(1_000),
                challenge_factory=lambda size: b"r" * size,
                verify_peer=False,
            )
        finally:
            thread.join(2)
            left.close()
            right.close()
        if errors:
            raise errors[0]
        self.assertEqual(len(output), 1)
        return client, output[0]

    def test_mutual_handshake_derives_same_redacted_session(self) -> None:
        client, server = self._handshake()
        self.assertEqual(client.connection_id, server.connection_id)
        self.assertEqual(client.requester_boot_id, REQUESTER_BOOT_ID)
        self.assertEqual(client.responder_boot_id, RESPONDER_BOOT_ID)
        self.assertEqual(server.requester_boot_id, REQUESTER_BOOT_ID)
        self.assertEqual(server.responder_boot_id, RESPONDER_BOOT_ID)
        self.assertNotIn("aaaa", repr(client))
        self.assertNotIn("verify_peer", inspect.signature(broker.client_handshake).parameters)
        self.assertNotIn("verify_peer", inspect.signature(broker.server_handshake).parameters)
        self.assertNotIn(
            "challenge_factory", inspect.signature(broker.client_handshake).parameters
        )
        self.assertNotIn(
            "challenge_factory", inspect.signature(broker.server_handshake).parameters
        )

    def test_secret_channel_role_and_boot_context_are_bound(self) -> None:
        with self.assertRaises(broker.BrokerError):
            self._handshake(server_secret=broker.BootSecret(b"b" * 32))
        changed = channel_spec(Path("/tmp/deeptwin-handshake"))
        object.__setattr__(changed, "channel_id", "control-document")
        with self.assertRaises(broker.BrokerError):
            self._handshake(server_spec=changed)
        changed_limit = channel_spec(Path("/tmp/deeptwin-handshake"))
        object.__setattr__(changed_limit, "max_queue_depth", 3)
        with self.assertRaises(broker.BrokerError):
            self._handshake(server_spec=changed_limit)
        changed_group = channel_spec(Path("/tmp/deeptwin-handshake"))
        alternative = _distinct_id(
            changed_group.pair_gid,
            changed_group.requester_gid,
            changed_group.responder_gid,
        )
        object.__setattr__(changed_group, "pair_gid", alternative)
        object.__setattr__(changed_group, "root_gid", alternative)
        object.__setattr__(changed_group, "socket_gid", alternative)
        with self.assertRaises(broker.BrokerError):
            self._handshake(server_spec=changed_group)
        with self.assertRaises(broker.BrokerError):
            self._handshake(server_responder_boot_id="replacement-browser-boot")
        with self.assertRaises(broker.BrokerError):
            self._handshake(server_requester_boot_id="replacement-control-boot")

    def test_client_does_not_succeed_without_responder_finish_ack(self) -> None:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        secret = broker.BootSecret(b"a" * 32)
        requester = b"r" * 32
        responder = b"s" * 32
        response = broker._hello_base(
            self.spec,
            "responder-hello",
            REQUESTER_BOOT_ID,
            RESPONDER_BOOT_ID,
        )
        response.update({
            "requester_challenge": broker._canonical_b64(requester),
            "responder_challenge": broker._canonical_b64(responder),
            "proof": broker._proof(secret, broker._auth_context(
                self.spec,
                phase="responder-hello",
                requester_boot_id=REQUESTER_BOOT_ID,
                responder_boot_id=RESPONDER_BOOT_ID,
                requester_challenge=requester,
                responder_challenge=responder,
                role="responder",
            )),
        })
        try:
            with (
                mock.patch.object(
                    broker,
                    "read_packet",
                    side_effect=[
                        response,
                        broker.TransportClosed(dispatch_effect="outcome_unknown"),
                    ],
                ),
                self.assertRaises(broker.TransportClosed),
            ):
                broker._client_handshake_impl(
                    left,
                    self.spec,
                    secret,
                    requester_boot_id=REQUESTER_BOOT_ID,
                    responder_boot_id=RESPONDER_BOOT_ID,
                    deadline=broker.Deadline.after_ms(500),
                    challenge_factory=lambda size: b"r" * size,
                    verify_peer=False,
                )
        finally:
            left.close()
            right.close()

    def test_public_handshake_closes_on_unexpected_failure(self) -> None:
        class EntropyFailure(Exception):
            pass

        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        credentials = broker.PeerCredentials(pid=1, uid=os.getuid(), gid=os.getgid())
        try:
            with (
                mock.patch.object(broker, "_verify_peer", return_value=credentials),
                mock.patch.object(
                    broker.secrets,
                    "token_bytes",
                    side_effect=EntropyFailure("synthetic entropy failure"),
                ),
                self.assertRaises(EntropyFailure) as failure,
            ):
                broker.client_handshake(
                    left,
                    self.spec,
                    broker.BootSecret(b"a" * 32),
                    requester_boot_id=REQUESTER_BOOT_ID,
                    responder_boot_id=RESPONDER_BOOT_ID,
                    deadline=broker.Deadline.after_ms(500),
                )
            self.assertEqual(type(failure.exception), EntropyFailure)
            self.assertEqual(str(failure.exception), "synthetic entropy failure")
            self.assertEqual(left.fileno(), -1)
        finally:
            left.close()
            right.close()

    def test_public_handshake_marks_wire_failure_as_not_dispatched(self) -> None:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        credentials = broker.PeerCredentials(pid=1, uid=os.getuid(), gid=os.getgid())
        try:
            with (
                mock.patch.object(broker, "_verify_peer", return_value=credentials),
                mock.patch.object(
                    broker,
                    "read_packet",
                    side_effect=broker.TransportUncertain(
                        dispatch_effect="outcome_unknown"
                    ),
                ),
                self.assertRaises(broker.TransportUncertain) as failure,
            ):
                broker.client_handshake(
                    left,
                    self.spec,
                    broker.BootSecret(b"a" * 32),
                    requester_boot_id=REQUESTER_BOOT_ID,
                    responder_boot_id=RESPONDER_BOOT_ID,
                    deadline=broker.Deadline.after_ms(500),
                )
            self.assertEqual(failure.exception.dispatch_effect, "definitely_not_sent")
            self.assertIsNone(failure.exception.__cause__)
            self.assertIsNone(failure.exception.__context__)
            self.assertEqual(left.fileno(), -1)
        finally:
            left.close()
            right.close()

    def test_handshake_enforces_spec_operation_deadline(self) -> None:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        short = channel_spec(Path("/tmp/deeptwin-handshake"))
        object.__setattr__(short, "max_operation_ms", 20)
        started = time.monotonic()
        try:
            with self.assertRaises(broker.BrokerError):
                broker._client_handshake_impl(
                    left,
                    short,
                    broker.BootSecret(b"a" * 32),
                    requester_boot_id=REQUESTER_BOOT_ID,
                    responder_boot_id=RESPONDER_BOOT_ID,
                    deadline=broker.Deadline.after_ms(2_000),
                    verify_peer=False,
                )
        finally:
            elapsed = time.monotonic() - started
            left.close()
            right.close()
        self.assertLess(elapsed, 0.5)


class ApplicationFrameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.spec = channel_spec(Path("/tmp/deeptwin-frame"))
        self.message_id = str(uuid4())

    def _codecs(
        self,
    ) -> tuple[
        broker.FrameCodec,
        broker.FrameCodec,
        broker.AuthenticatedSession,
        broker.AuthenticatedSession,
    ]:
        requester, responder = session_pair(self.spec)
        return (
            broker.FrameCodec(self.spec, requester, local_service="control"),
            broker.FrameCodec(self.spec, responder, local_service="browser"),
            requester,
            responder,
        )

    def _frame(self, sender: broker.FrameCodec) -> bytes:
        return sender.encode(
            message_id=self.message_id,
            correlation_id=None,
            message_type="execute",
            payload=b"{\"job\":1}",
        )

    def test_application_frame_round_trip_preserves_original_bytes(self) -> None:
        sender, receiver, _, _ = self._codecs()
        received = receiver.decode(self._frame(sender))
        self.assertEqual(received.payload, b"{\"job\":1}")
        self.assertEqual(received.envelope.message_id, self.message_id)
        self.assertEqual(received.envelope.payload_bytes, 9)

    def test_public_codec_wire_round_trip_and_failure_latch(self) -> None:
        sender, receiver, _, _ = self._codecs()
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sender.write(
                left,
                message_id=self.message_id,
                correlation_id=None,
                message_type="execute",
                payload=b'{"job":1}',
                deadline=broker.Deadline.after_ms(1_000),
            )
            received = receiver.read(
                right, deadline=broker.Deadline.after_ms(1_000)
            )
            self.assertEqual(received.payload, b'{"job":1}')
            self.assertEqual(sender.next_send_sequence, 2)
            self.assertEqual(receiver.next_receive_sequence, 2)
        finally:
            left.close()
            right.close()

        failed_sender, _, _, _ = self._codecs()
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        right.close()
        try:
            with self.assertRaises(broker.TransportUncertain) as failure:
                failed_sender.write(
                    left,
                    message_id=str(uuid4()),
                    correlation_id=None,
                    message_type="execute",
                    payload=b"x",
                    deadline=broker.Deadline.after_ms(1_000),
                )
            self.assertEqual(failure.exception.dispatch_effect, "may_have_started")
            self.assertTrue(failed_sender.closed)
        finally:
            left.close()

        _, failed_receiver, _, _ = self._codecs()
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            left.sendall(struct.pack(">I", 20) + b"{}")
            left.close()
            with self.assertRaises(broker.BrokerError) as failure:
                failed_receiver.read(
                    right, deadline=broker.Deadline.after_ms(1_000)
                )
            self.assertEqual(failure.exception.dispatch_effect, "outcome_unknown")
            self.assertTrue(failed_receiver.closed)
        finally:
            left.close()
            right.close()

    def test_sequence_replay_direction_type_mac_and_canonical_form_fail(self) -> None:
        sender, receiver, _, _ = self._codecs()
        raw = self._frame(sender)
        receiver.decode(raw)
        with self.assertRaises(broker.ProtocolViolation):
            receiver.decode(raw)
        self.assertTrue(receiver.closed)

        _, wrong_receiver, requester_session, _ = self._codecs()
        wrong_direction = broker._encode_application_frame(
            self.spec,
            requester_session,
            sender="browser",
            receiver="control",
            sequence=1,
            message_id=str(uuid4()),
            correlation_id=None,
            message_type="result",
            payload=b"result",
        )
        with self.assertRaises(broker.ProtocolViolation):
            wrong_receiver.decode(wrong_direction)

        tamper_sender, tamper_receiver, _, _ = self._codecs()
        changed = json.loads(self._frame(tamper_sender))
        changed["payload_b64"] = "e30="
        tampered = json.dumps(
            changed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        with self.assertRaises(broker.ProtocolViolation):
            tamper_receiver.decode(tampered)

        canonical_sender, canonical_receiver, _, _ = self._codecs()
        with self.assertRaises(broker.ProtocolViolation):
            canonical_receiver.decode(self._frame(canonical_sender) + b" ")

        codec, _, _, _ = self._codecs()
        with self.assertRaises(broker.ProtocolViolation):
            codec.encode(
                message_id=self.message_id,
                correlation_id=None,
                message_type="undeclared",
                payload=b"x",
            )
        self.assertEqual(codec.next_send_sequence, 1)

    def test_boolean_sequence_and_duplicate_codec_claim_fail_closed(self) -> None:
        sender, receiver, requester_session, _ = self._codecs()
        value = json.loads(self._frame(sender))
        value.pop("mac")
        value["sequence"] = True
        value["mac"] = hmac.new(
            requester_session._material(),
            b"frame\x00" + broker._canonical_json(value),
            hashlib.sha256,
        ).hexdigest()
        boolean_sequence = broker._canonical_json(value)
        with self.assertRaises(broker.ProtocolViolation):
            receiver.decode(boolean_sequence)

        first_session, second_session = session_pair(self.spec)
        first_codec = broker.FrameCodec(
            self.spec, first_session, local_service="control"
        )
        with self.assertRaises(broker.ProtocolViolation):
            broker.FrameCodec(self.spec, first_session, local_service="control")
        with self.assertRaises(broker.AuthenticationError):
            broker.FrameCodec(self.spec, second_session, local_service="control")
        with self.assertRaises(TypeError):
            copy.copy(first_codec)
        with self.assertRaises(TypeError):
            copy.deepcopy(first_codec)
        with self.assertRaises(TypeError):
            pickle.dumps(first_codec)
        with self.assertRaises(AttributeError):
            first_codec._next_receive = 1
        with self.assertRaises(AttributeError):
            first_codec.local_service = "browser"


class AdmissionTests(unittest.TestCase):
    def test_queue_full_timeout_cleanup_and_single_release(self) -> None:
        gate = broker.AdmissionGate(max_queue_depth=1)
        with self.assertRaises(broker.DeadlineExceeded):
            gate.acquire(broker.Deadline(1.0))
        self.assertEqual(gate.in_flight, 0)
        first = gate.acquire(broker.Deadline.after_ms(1_000))
        self.assertEqual(gate.in_flight, 1)
        with self.assertRaises(broker.DeadlineExceeded):
            gate.acquire(broker.Deadline(1.0))
        self.assertEqual(gate.queued, 0)
        queued_deadline = broker.Deadline.after_ms(1_000)
        acquired: list[broker.AdmissionLease] = []

        def wait() -> None:
            acquired.append(gate.acquire(queued_deadline))

        thread = threading.Thread(target=wait)
        thread.start()
        limit = time.monotonic() + 1.0
        while gate.queued != 1 and time.monotonic() < limit:
            time.sleep(0.001)
        with self.assertRaises(broker.BrokerBusy):
            gate.acquire(broker.Deadline.after_ms(100))
        first.release()
        thread.join(1)
        self.assertEqual(len(acquired), 1)
        acquired[0].release()
        with self.assertRaises(broker.ProtocolViolation):
            acquired[0].release()
        self.assertEqual(gate.in_flight, 0)

    def test_fifo_order_is_stable(self) -> None:
        gate = broker.AdmissionGate(max_queue_depth=2)
        held = gate.acquire(broker.Deadline.after_ms(1_000))
        order: list[int] = []

        def worker(identity: int) -> None:
            with gate.acquire(broker.Deadline.after_ms(2_000)):
                order.append(identity)

        first = threading.Thread(target=worker, args=(1,))
        second = threading.Thread(target=worker, args=(2,))
        first.start()
        limit = time.monotonic() + 1.0
        while gate.queued != 1 and time.monotonic() < limit:
            time.sleep(0.001)
        second.start()
        limit = time.monotonic() + 1.0
        while gate.queued != 2 and time.monotonic() < limit:
            time.sleep(0.001)
        held.release()
        first.join(2)
        second.join(2)
        self.assertEqual(order, [1, 2])

    def test_waiter_expiring_as_capacity_opens_is_not_admitted(self) -> None:
        class WakeupDeadline:
            def __init__(self) -> None:
                self.remaining_calls = 0

            def require(self, *, dispatch_effect: str = "definitely_not_sent") -> float:
                del dispatch_effect
                return 1.0

            def remaining(self) -> float:
                self.remaining_calls += 1
                return 1.0 if self.remaining_calls == 1 else 0.0

        gate = broker.AdmissionGate(max_queue_depth=1)
        held = gate.acquire(broker.Deadline.after_ms(1_000))
        outcomes: list[type[BaseException]] = []

        def wait() -> None:
            try:
                gate.acquire(WakeupDeadline())  # type: ignore[arg-type]
            except broker.DeadlineExceeded as error:
                outcomes.append(type(error))

        thread = threading.Thread(target=wait)
        thread.start()
        limit = time.monotonic() + 1.0
        while gate.queued != 1 and time.monotonic() < limit:
            time.sleep(0.001)
        held.release()
        thread.join(1)
        self.assertEqual(outcomes, [broker.DeadlineExceeded])
        self.assertEqual(gate.in_flight, 0)
        self.assertEqual(gate.queued, 0)

    def test_interrupted_waiter_is_removed_from_fifo(self) -> None:
        gate = broker.AdmissionGate(max_queue_depth=1)
        held = gate.acquire(broker.Deadline.after_ms(1_000))
        with (
            mock.patch.object(
                threading.Condition,
                "wait",
                side_effect=KeyboardInterrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            gate.acquire(broker.Deadline.after_ms(1_000))
        self.assertEqual(gate.queued, 0)
        held.release()
        replacement = gate.acquire(broker.Deadline.after_ms(1_000))
        replacement.release()
        self.assertEqual(gate.in_flight, 0)


class PeerAndDependencyBoundaryTests(unittest.TestCase):
    def test_pair_group_is_not_accepted_as_peer_primary_identity(self) -> None:
        spec = channel_spec(Path("/tmp/deeptwin-peer-identity"))
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            with mock.patch.object(
                broker,
                "peer_credentials",
                return_value=broker.PeerCredentials(
                    pid=123,
                    uid=spec.responder_uid,
                    gid=spec.pair_gid,
                ),
            ), self.assertRaises(broker.PeerCredentialError):
                broker._verify_peer(left, spec, spec.requester_service)
            expected = broker.PeerCredentials(
                pid=123,
                uid=spec.responder_uid,
                gid=spec.responder_gid,
            )
            with mock.patch.object(
                broker,
                "peer_credentials",
                return_value=expected,
            ):
                self.assertEqual(
                    broker._verify_peer(left, spec, spec.requester_service), expected
                )
        finally:
            left.close()
            right.close()

    def test_linux_peer_credentials_or_explicit_non_linux_failure(self) -> None:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            if sys.platform == "linux" and hasattr(socket, "SO_PEERCRED"):
                credentials = broker.peer_credentials(left)
                self.assertGreater(credentials.pid, 0)
                self.assertEqual(credentials.uid, os.getuid())
                self.assertEqual(credentials.gid, os.getgid())
            else:
                with self.assertRaises(broker.PeerCredentialError):
                    broker.peer_credentials(left)
        finally:
            left.close()
            right.close()

    def test_module_has_no_authority_store_network_process_or_fd_passing_dependency(self) -> None:
        path = Path(broker.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "subprocess", "requests", "httpx", "sqlite3", "pickle", "marshal",
            "logging", "docker", "app.domain", "app.runtime", "app.api",
            "app.storage", "app.adapters", "app.extensions",
        }
        imports: set[str] = set()
        attributes: set[str] = set()
        calls: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module or "")
            elif isinstance(node, ast.Attribute):
                attributes.add(node.attr)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                calls.add(node.func.id)
        self.assertFalse(any(
            item == forbidden or item.startswith(forbidden + ".")
            for item in imports for forbidden in forbidden_modules
        ))
        self.assertTrue({"sendmsg", "recvmsg", "SCM_RIGHTS"}.isdisjoint(attributes))
        self.assertTrue({"eval", "exec", "print", "__import__"}.isdisjoint(calls))
        source = path.read_text(encoding="utf-8")
        self.assertNotIn("AF_INET", source)
        self.assertNotIn("shell=True", source)


if __name__ == "__main__":
    unittest.main()
