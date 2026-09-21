"""Credential gateway service over authenticated broker frames (T090).

Gateway side only: v2 encrypted store/query/retire and safe metadata. Logical
operations use bounded authenticated fragments, with no partial vault admission.
Legacy write/delete, root access, decryption and provider binding are unavailable.
The control-plane client never imports this module.
"""

from __future__ import annotations

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
    _read_logical,
    _write_logical,
)
from .credential_vault import CredentialVault, CredentialVaultError

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
        if operation in ("store", "delete"):
            raise CredentialVaultError("unsupported_operation")
        keys = {
            "store_at": {"schema", "op", "metadata", "secret_b64u"},
            "query_record": {"schema", "op", "metadata"},
            "retire": {"schema", "op", "command_id", "record", "reason"},
            "snapshot": {"schema", "op"},
            "health": {"schema", "op"},
            "capabilities": {"schema", "op"},
        }
        if type(operation) is not str or operation not in keys:
            raise CredentialVaultError("unsupported_operation")
        if request.get("schema") != "credential-op-v2" or set(request) != keys[operation]:
            raise CredentialVaultError("invalid_metadata")
        if operation == "store_at":
            return self._vault.store_at(metadata=request["metadata"], secret_b64u=request["secret_b64u"])
        if operation == "query_record":
            return self._vault.query_record(metadata=request["metadata"])
        if operation == "retire":
            return self._vault.retire(command_id=request["command_id"], record=request["record"], reason=request["reason"])
        if operation == "snapshot":
            return {"credentials": self._vault.snapshot()}
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
        """Answer exactly one complete logical operation on the authenticated codec."""

        message_id, incoming = _read_logical(sock, codec, message_type=REQUEST_TYPE,
            correlation_id=None, deadline=deadline)
        try:
            request = decode_op(incoming)
            deadline.require()
            result = self._dispatch(request)
            response = {"ok": True, "result": result}
            payload = encode_op(response)
        except (CredentialVaultError, GatewayServiceError) as exc:
            # Sanitized by construction: vault errors never carry secret bytes.
            response = {"ok": False, "code": exc.code}
            payload = encode_op(response)
        if wire_log is not None:
            wire_log.append(("out", payload))
        _write_logical(
            sock, codec,
            message_id=str(uuid4()),
            correlation_id=message_id,
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
