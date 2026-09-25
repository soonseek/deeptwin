"""Control-plane side of the credential gateway channel (T090).

This module deliberately imports no vault code: the control plane may import it
to speak `credential_op`/`credential_result` frames without ever seeing the
vault implementation. The service side lives in
:mod:`app.workers.credential_gateway_service`.
"""

from __future__ import annotations

import base64
from uuid import uuid4

from . import broker
from .credential_contracts import (
    CredentialVaultError,
    b64u,
    canonical,
    strict_json,
    unb64u,
    uuid_value,
)

REQUEST_TYPE = "credential_op"
RESULT_TYPE = "credential_result"
MAX_OP_PAYLOAD_BYTES = 96 * 1024 + 4_096
_CHUNK_BYTES = 16_384
_FRAGMENT_KEYS = {"schema", "transfer_id", "total_bytes", "index", "count", "chunk_b64u"}


class GatewayServiceError(RuntimeError):
    """Sanitized gateway-channel failure; never carries secret bytes.

    ``sent`` is False only when the failure happened before any byte of the request
    left this process (the connection or handshake failed): the gateway cannot have
    admitted the command. Every other failure is ambiguous and must be recovered by
    query or same-command replay, never by a new secret under the same command."""
    def __init__(self, message="credential operation rejected", *, code="credential_operation_rejected",
                 sent=True):
        self.code = code
        self.sent = sent is not False
        super().__init__(message)


def encode_op(value: dict) -> bytes:
    try:
        payload = canonical(value)
        if len(payload) > MAX_OP_PAYLOAD_BYTES:
            raise ValueError
        return payload
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise GatewayServiceError("gateway payload is out of bounds") from None


def decode_op(payload: bytes) -> dict:
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_OP_PAYLOAD_BYTES:
        raise GatewayServiceError("gateway payload is out of bounds")
    try:
        value = strict_json(payload, MAX_OP_PAYLOAD_BYTES)
    except CredentialVaultError:
        raise GatewayServiceError("gateway payload is not strict JSON") from None
    if type(value) is not dict:
        raise GatewayServiceError("gateway payload is not an object")
    return value


def _write_logical_connection(connection, *, payload, message_id, message_type, correlation_id, deadline):
    """Bounded transport-only fragments over one connection; no digest, persistence or
    new semantic intent. The one fragmentation grammar; the raw entry borrows it."""
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_OP_PAYLOAD_BYTES:
        raise GatewayServiceError("gateway payload is out of bounds")
    if len(payload) <= _CHUNK_BYTES:
        connection.write(message_id=message_id, correlation_id=correlation_id,
            message_type=message_type, payload=payload, deadline=deadline)
        return
    count = (len(payload) + _CHUNK_BYTES - 1) // _CHUNK_BYTES
    seen = {message_id}
    for index in range(count):
        identity = message_id
        if index:
            for _ in range(8):
                identity = str(uuid4())
                if identity not in seen:
                    break
            else:
                raise GatewayServiceError("fragment identity exhausted")
            seen.add(identity)
        fragment = dict(schema="credential-fragment-v1", transfer_id=message_id,
            total_bytes=len(payload), index=index, count=count,
            chunk_b64u=b64u(payload[index * _CHUNK_BYTES:(index + 1) * _CHUNK_BYTES]))
        connection.write(message_id=identity,
            correlation_id=(message_id if index and correlation_id is None else correlation_id),
            message_type=message_type, payload=encode_op(fragment), deadline=deadline)


def _write_logical(sock, codec, *, payload, message_id, message_type, correlation_id, deadline):
    """The raw `(sock, codec)` entry: the same grammar through a borrowing adapter."""
    from .gateway_connection import _RawConnection

    _write_logical_connection(_RawConnection(sock, codec), payload=payload, message_id=message_id,
        message_type=message_type, correlation_id=correlation_id, deadline=deadline)


def _fragment(value):
    if type(value) is not dict or set(value) != _FRAGMENT_KEYS or value["schema"] != "credential-fragment-v1":
        raise GatewayServiceError("invalid credential fragment")
    uuid_value(value["transfer_id"])
    total, count, index = value["total_bytes"], value["count"], value["index"]
    if (type(total) is not int or not _CHUNK_BYTES < total <= MAX_OP_PAYLOAD_BYTES
            or type(count) is not int or count != (total + _CHUNK_BYTES - 1) // _CHUNK_BYTES
            or type(index) is not int or not 0 <= index < count):
        raise GatewayServiceError("invalid credential fragment")
    length = _CHUNK_BYTES if index < count - 1 else total - index * _CHUNK_BYTES
    return unb64u(value["chunk_b64u"], length, length)


def _read_logical_connection(connection, *, message_type, correlation_id, deadline,
                             first_frame=None, first_value=None):
    """Return (first message ID, original bytes, first decoded value), never a forged
    broker envelope. A router that already read and decoded the first frame passes the
    actual pair (both or neither); the helper still validates its envelope and reuses
    its decode — the one fragmentation grammar, one decode per frame."""
    if (first_frame is None) != (first_value is None):
        raise GatewayServiceError("a first frame and its value travel together")
    try:
        first = connection.read(deadline=deadline) if first_frame is None else first_frame
        if first.envelope.message_type != message_type or first.envelope.correlation_id != correlation_id:
            raise GatewayServiceError("gateway logical message is not bound")
        if len(first.payload) > 24_576:
            raise GatewayServiceError("gateway fragment is out of bounds")
        value = decode_op(first.payload) if first_value is None else first_value
        identity = first.envelope.message_id
        if value.get("schema") != "credential-fragment-v1":
            if len(first.payload) > _CHUNK_BYTES:
                raise GatewayServiceError("gateway ordinary message is out of bounds")
            return identity, first.payload, value
        data = bytearray(_fragment(value))
        if value["index"] != 0 or value["transfer_id"] != identity:
            raise GatewayServiceError("gateway fragment is not bound")
        seen = {identity}
        for index in range(1, value["count"]):
            frame = connection.read(deadline=deadline)
            if (frame.envelope.message_type != message_type
                    or frame.envelope.correlation_id != (identity if correlation_id is None else correlation_id)
                    or frame.envelope.message_id in seen or len(frame.payload) > 24_576):
                raise GatewayServiceError("gateway fragment is not bound")
            seen.add(frame.envelope.message_id)
            part = decode_op(frame.payload)
            chunk = _fragment(part)
            if any(part[name] != value[name] for name in ("transfer_id", "total_bytes", "count")) or part["index"] != index:
                raise GatewayServiceError("gateway fragment is not bound")
            data.extend(chunk)
        if len(data) != value["total_bytes"]:
            raise GatewayServiceError("gateway logical message is out of bounds")
        deadline.require()
        reconstructed = bytes(data)
        return identity, reconstructed, decode_op(reconstructed)  # the reconstructed bytes, decoded once
    except CredentialVaultError:
        connection.close()
        raise GatewayServiceError("invalid credential fragment") from None
    except BaseException:
        connection.close()
        raise


def _read_logical(sock, codec, *, message_type, correlation_id, deadline):
    """The raw `(sock, codec)` entry: (first message ID, original bytes) through the one
    grammar; the borrowing adapter closes the codec on failure as before."""
    from .gateway_connection import _RawConnection

    identity, payload, _value = _read_logical_connection(_RawConnection(sock, codec),
        message_type=message_type, correlation_id=correlation_id, deadline=deadline)
    return identity, payload


class CredentialGatewayClient:
    """Control-plane client; speaks frames only and never sees the vault."""

    __slots__ = ("_connect", "_deadline_ms", "_transport_factory")

    def __init__(self, transport_factory, *, deadline_ms: int = 5_000, _connect=None) -> None:
        if _connect is None and not callable(transport_factory):
            raise GatewayServiceError("a transport factory is required")
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 600_000:
            raise GatewayServiceError("client deadline is out of bounds")
        self._transport_factory = transport_factory
        self._deadline_ms = deadline_ms
        self._connect = _connect

    @classmethod
    def for_gateway(cls, *, requester_boot_id: str, deadline_ms: int = 5_000) -> CredentialGatewayClient:
        """The fixed owned client over the shared gateway profile: each call connects as the
        control side of the `cp-provider` channel under the call's own deadline, with the
        caller's process boot as the requester boot. No profile, path or peer override."""
        from . import gateway_channel as profile
        from . import listener

        if type(requester_boot_id) is not str or not requester_boot_id:
            raise GatewayServiceError("a requester boot id is required")

        def connect(deadline):
            root, spec = profile.gateway_channel()
            try:
                return listener.connect_authenticated(root, spec, requester_boot_id=requester_boot_id,
                                                      deadline=deadline)
            except listener.ListenerError as exc:
                # adapted at the engine boundary: the listener's categories stay its own
                raise GatewayServiceError("gateway channel failed") from exc

        return cls(None, deadline_ms=deadline_ms, _connect=connect)

    def _open(self, deadline):
        if self._connect is not None:
            return self._connect(deadline)
        from .gateway_connection import _RawConnection

        sock, codec = self._transport_factory()
        return _RawConnection(sock, codec, owns_socket=True)

    def _call(self, request: dict) -> dict:
        deadline = broker.Deadline.after_ms(self._deadline_ms)
        try:
            connection = self._open(deadline)
        except (broker.BrokerError, GatewayServiceError, OSError) as exc:
            # nothing of the request was written: the gateway cannot have admitted it
            raise GatewayServiceError("gateway channel failed", sent=False) from exc
        try:
            message_id = str(uuid4())
            _write_logical_connection(
                connection,
                message_id=message_id,
                correlation_id=None,
                message_type=REQUEST_TYPE,
                payload=encode_op(request),
                deadline=deadline,
            )
            _, _payload, response = _read_logical_connection(connection, message_type=RESULT_TYPE,
                correlation_id=message_id, deadline=deadline)
            deadline.require()
        except broker.BrokerError as exc:
            raise GatewayServiceError("gateway channel failed") from exc
        finally:
            try:
                connection.close()
            except (broker.BrokerError, OSError):
                pass
        if response.get("ok") is not True:
            codes = {"unsupported_operation", "busy", "conflict", "capacity_exhausted", "nonce_exhausted", "maintenance_required", "invalid_metadata", "invalid_encoding", "invalid_secret", "storage_failure"}
            code = response.get("code")
            if type(code) is not str or code not in codes:
                code = "credential_operation_rejected"
            raise GatewayServiceError("credential operation rejected", code=code)
        if set(response) != {"ok", "result"}:
            raise GatewayServiceError("gateway result is malformed")
        result = response.get("result")
        if type(result) is not dict:
            raise GatewayServiceError("gateway result is malformed")
        return result

    def store_at(self, *, metadata: dict, secret: bytes) -> dict:
        if type(secret) is not bytes:
            raise GatewayServiceError("secret bytes are required")
        return self._call(dict(schema="credential-op-v2", op="store_at", metadata=metadata, secret_b64u=b64u(secret)))

    def query_record(self, *, metadata: dict) -> dict:
        return self._call(dict(schema="credential-op-v2", op="query_record", metadata=metadata))

    def retire(self, *, command_id: str, record: dict, reason: str) -> dict:
        return self._call(dict(schema="credential-op-v2", op="retire", command_id=command_id, record=record, reason=reason))

    def submit(
        self,
        *,
        intent_id: str,
        provider: str,
        secret: bytes,
        rotate_from: str | None,
    ) -> dict:
        """The closed legacy v1 store shape, which the gateway refuses as unsupported.
        Retained only for the gateway's refusal pins; no route calls it."""
        if type(secret) is not bytes:
            raise GatewayServiceError("secret bytes are required")
        return self._call({
            "op": "store",
            "intent_id": intent_id,
            "provider": provider,
            "secret_b64": base64.b64encode(secret).decode("ascii"),
            "rotate_from": rotate_from,
        })

    def delete(self, handle: str) -> dict:
        """The closed legacy v1 delete shape (refused as unsupported; no route calls it)."""
        return self._call({"op": "delete", "handle": handle})

    def snapshot(self) -> list:
        result = self._call({"schema": "credential-op-v2", "op": "snapshot"})
        entries = result.get("credentials")
        if type(entries) is not list:
            raise GatewayServiceError("gateway snapshot is malformed")
        return entries


__all__ = [
    "MAX_OP_PAYLOAD_BYTES",
    "REQUEST_TYPE",
    "RESULT_TYPE",
    "CredentialGatewayClient",
    "GatewayServiceError",
    "decode_op",
    "encode_op",
]
