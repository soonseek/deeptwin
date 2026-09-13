"""Credential gateway service over authenticated broker frames (T090).

Gateway side only: dispatches the closed `credential_op` set — store, delete
(retire of an active record followed by verified erase), redacted snapshot,
health and capabilities — to the vault and answers with redacted results.
`resolve_for_gateway` is deliberately not a channel operation: resolution stays
inside the gateway for the provider transport alone. The control-plane client
lives in :mod:`app.workers.credential_channel` and never imports this module.
"""

from __future__ import annotations

import base64
import socket
from uuid import uuid4

from . import broker
from .credential_channel import (
    MAX_OP_PAYLOAD_BYTES,
    REQUEST_TYPE,
    RESULT_TYPE,
    CredentialGatewayClient,
    GatewayServiceError,
    decode_op,
    encode_op,
)
from .credential_vault import CredentialVault, CredentialVaultError

_OPERATIONS = frozenset({"store", "delete", "snapshot", "health", "capabilities"})


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
            or REQUEST_TYPE not in spec.requester_message_types
            or RESULT_TYPE not in spec.responder_message_types
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
        if frame.envelope.message_type != REQUEST_TYPE:
            raise GatewayServiceError("unexpected gateway request frame")
        try:
            result = self._dispatch(decode_op(frame.payload))
            response = {"ok": True, "result": result}
        except (CredentialVaultError, GatewayServiceError):
            # Sanitized by construction: vault errors never carry secret bytes.
            response = {"ok": False, "code": "credential_operation_rejected"}
        payload = encode_op(response)
        if wire_log is not None:
            wire_log.append(("out", payload))
        codec.write(
            sock,
            message_id=str(uuid4()),
            correlation_id=frame.envelope.message_id,
            message_type=RESULT_TYPE,
            payload=payload,
            deadline=deadline,
        )


__all__ = [
    "MAX_OP_PAYLOAD_BYTES",
    "CredentialGatewayClient",
    "CredentialGatewayService",
    "GatewayServiceError",
]
