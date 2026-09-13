"""Credential gateway service and client over authenticated broker frames (T090).

The control plane's :class:`CredentialGatewayClient` never imports the vault: it
speaks one `credential_op` frame per authenticated connection and receives one
`credential_result` frame back. The gateway-side
:class:`CredentialGatewayService` dispatches the closed operation set — store,
delete (retire followed by verified erase), snapshot, health, capabilities — to
the vault and answers with redacted results only. The raw secret crosses the
channel exactly once, in the store direction; no response, success or error,
ever carries secret bytes, and `resolve_for_gateway` is deliberately not an
operation this channel exposes: resolution stays inside the gateway for the
provider transport alone.
"""

from __future__ import annotations

import base64
import json
import socket
from uuid import uuid4

from . import broker
from .credential_vault import CredentialVault, CredentialVaultError

_OPERATIONS = frozenset({"store", "delete", "snapshot", "health", "capabilities"})
_REQUEST_TYPE = "credential_op"
_RESULT_TYPE = "credential_result"
MAX_OP_PAYLOAD_BYTES = 96 * 1024 + 4_096


class GatewayServiceError(RuntimeError):
    """Sanitized gateway-channel failure; never carries secret bytes."""


def _encode(value: dict) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _decode(payload: bytes) -> dict:
    if type(payload) is not bytes or not 1 <= len(payload) <= MAX_OP_PAYLOAD_BYTES:
        raise GatewayServiceError("gateway payload is out of bounds")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GatewayServiceError("gateway payload is not strict JSON") from exc
    if type(value) is not dict:
        raise GatewayServiceError("gateway payload is not an object")
    return value


class CredentialGatewayService:
    """One vault's frame-served operation surface inside the gateway boundary."""

    __slots__ = ("_secret", "_spec", "_vault")

    def __init__(
        self,
        vault: CredentialVault,
        spec: broker.ChannelSpec,
        secret: broker.BootSecret,
    ) -> None:
        if (
            type(vault) is not CredentialVault
            or type(spec) is not broker.ChannelSpec
            or type(secret) is not broker.BootSecret
            or _REQUEST_TYPE not in spec.requester_message_types
            or _RESULT_TYPE not in spec.responder_message_types
        ):
            raise GatewayServiceError(
                "an exact vault, channel and boot secret are required"
            )
        self._vault = vault
        self._spec = spec
        self._secret = secret

    def _dispatch(self, request: dict) -> dict:
        operation = request.get("op")
        if operation not in _OPERATIONS:
            raise CredentialVaultError("unsupported gateway operation")
        if operation == "store":
            raw = request.get("secret_b64")
            if type(raw) is not str:
                raise CredentialVaultError("store payload is malformed")
            try:
                secret = base64.b64decode(raw, validate=True)
            except (ValueError, base64.binascii.Error) as exc:  # type: ignore[attr-defined]
                raise CredentialVaultError("store payload is malformed") from exc
            record = self._vault.store(
                request.get("intent_id"),
                request.get("provider"),
                secret,
                rotate_from=request.get("rotate_from"),
            )
            return {
                "handle": record.handle,
                "provider": record.provider,
                "state": record.state,
            }
        if operation == "delete":
            handle = request.get("handle")
            record = self._vault._record(handle) if type(handle) is str else None
            if record is not None and record["state"] == "active":
                self._vault.retire(handle)
            outcome = self._vault.erase(handle)
            return {"handle": handle, "state": outcome}
        if operation == "snapshot":
            entries = [
                {
                    "handle": handle,
                    "provider": record["provider"],
                    "state": record["state"],
                }
                for handle, record in sorted(
                    self._vault._index["records"].items()
                )
                if record["state"] != "erasure_completed"
            ]
            return {"credentials": entries}
        if operation == "health":
            return self._vault.health()
        return self._vault.capabilities()

    def serve_one(
        self,
        sock: socket.socket,
        codec: broker.FrameCodec,
        *,
        deadline: broker.Deadline,
        wire_log: list | None = None,
    ) -> None:
        """Answer exactly one operation frame on an authenticated codec."""

        frame = codec.read(sock, deadline=deadline)
        if frame.envelope.message_type != _REQUEST_TYPE:
            raise GatewayServiceError("unexpected gateway request frame")
        try:
            result = self._dispatch(_decode(frame.payload))
            response = {"ok": True, "result": result}
        except (CredentialVaultError, GatewayServiceError):
            # Sanitized by construction: vault errors never carry secret bytes.
            response = {"ok": False, "code": "credential_operation_rejected"}
        payload = _encode(response)
        if wire_log is not None:
            wire_log.append(("out", payload))
        codec.write(
            sock,
            message_id=str(uuid4()),
            correlation_id=frame.envelope.message_id,
            message_type=_RESULT_TYPE,
            payload=payload,
            deadline=deadline,
        )


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
                message_type=_REQUEST_TYPE,
                payload=_encode(request),
                deadline=deadline,
            )
            frame = codec.read(sock, deadline=deadline)
            if (
                frame.envelope.message_type != _RESULT_TYPE
                or frame.envelope.correlation_id != message_id
            ):
                raise GatewayServiceError("gateway response frame is not bound")
            response = _decode(frame.payload)
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
    "CredentialGatewayClient",
    "CredentialGatewayService",
    "GatewayServiceError",
]
