"""Control-plane side of the credential gateway channel (T090).

This module deliberately imports no vault code: the control plane may import it
to speak `credential_op`/`credential_result` frames without ever seeing the
vault implementation. The service side lives in
:mod:`app.workers.credential_gateway_service`.
"""

from __future__ import annotations

import base64
import json
from uuid import uuid4

from . import broker

REQUEST_TYPE = "credential_op"
RESULT_TYPE = "credential_result"
MAX_OP_PAYLOAD_BYTES = 96 * 1024 + 4_096


class GatewayServiceError(RuntimeError):
    """Sanitized gateway-channel failure; never carries secret bytes."""


def encode_op(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def decode_op(payload: bytes) -> dict:
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_OP_PAYLOAD_BYTES:
        raise GatewayServiceError("gateway payload is out of bounds")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GatewayServiceError("gateway payload is not strict JSON") from exc
    if type(value) is not dict:
        raise GatewayServiceError("gateway payload is not an object")
    return value


class CredentialGatewayClient:
    """Control-plane client; speaks frames only and never sees the vault."""

    __slots__ = ("_deadline_ms", "_transport_factory")

    def __init__(self, transport_factory, *, deadline_ms: int = 5_000) -> None:
        if not callable(transport_factory):
            raise GatewayServiceError("a transport factory is required")
        if type(deadline_ms) is not int or not 1 <= deadline_ms <= 600_000:
            raise GatewayServiceError("client deadline is out of bounds")
        self._transport_factory = transport_factory
        self._deadline_ms = deadline_ms

    def _call(self, request: dict) -> dict:
        deadline = broker.Deadline.after_ms(self._deadline_ms)
        sock, codec = self._transport_factory()
        try:
            message_id = str(uuid4())
            codec.write(
                sock,
                message_id=message_id,
                correlation_id=None,
                message_type=REQUEST_TYPE,
                payload=encode_op(request),
                deadline=deadline,
            )
            frame = codec.read(sock, deadline=deadline)
            if (
                frame.envelope.message_type != RESULT_TYPE
                or frame.envelope.correlation_id != message_id
            ):
                raise GatewayServiceError("gateway response frame is not bound")
            response = decode_op(frame.payload)
        except broker.BrokerError as exc:
            raise GatewayServiceError("gateway channel failed") from exc
        finally:
            codec.close()
            try:
                sock.close()
            except OSError:
                pass
        if response.get("ok") is not True:
            raise GatewayServiceError("credential operation rejected")
        result = response.get("result")
        if type(result) is not dict:
            raise GatewayServiceError("gateway result is malformed")
        return result

    def submit(
        self,
        *,
        intent_id: str,
        provider: str,
        secret: bytes,
        rotate_from: str | None,
    ) -> dict:
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
        return self._call({"op": "delete", "handle": handle})

    def snapshot(self) -> list:
        result = self._call({"op": "snapshot"})
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
