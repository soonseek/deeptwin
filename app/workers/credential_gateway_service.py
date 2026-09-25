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
    _read_logical_connection,
    _write_logical_connection,
    encode_op,
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
            "bind_head": {"schema", "op", "provider", "revision", "state", "record"},
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
        if operation == "bind_head":
            return self._vault.bind_head(provider=request["provider"], revision=request["revision"],
                                         state=request["state"], record=request["record"])
        if operation == "snapshot":
            return {"credentials": self._vault.snapshot()}
        if operation == "health":
            return self._vault.health()
        return self._vault.capabilities()

    @property
    def spec(self) -> broker.ChannelSpec:
        return self._spec

    @property
    def vault(self) -> CredentialVault:
        """The exact vault served (borrowed by the ingress, never closed through it)."""
        return self._vault

    def serve_one(
        self,
        sock: socket.socket,
        codec: broker.FrameCodec,
        *,
        deadline: broker.Deadline,
        wire_log: list | None = None,
    ) -> None:
        """Answer exactly one complete logical operation on the authenticated codec (the
        raw entry: the same engine through a borrowing adapter). One behaviour moved with
        the shared grammar: a fragment transfer whose reconstruction is not strict JSON is
        refused before any reply (the codec closed, `GatewayServiceError` raised) where the
        raw entry once answered a sanitized rejection; every plain request keeps its reply."""
        from .gateway_connection import _RawConnection

        self._serve_connection(_RawConnection(sock, codec), deadline=deadline, wire_log=wire_log)

    def serve_connection(self, owner, *, deadline: broker.Deadline) -> None:
        """Answer exactly one complete logical operation on a factory-issued owner of
        this gateway's channel (the owner's session digest must be this spec's, its local
        side the responder). The owner stays the caller's to close."""
        from .listener import AuthenticatedConnection

        if type(owner) is not AuthenticatedConnection or type(deadline) is not broker.Deadline:
            raise GatewayServiceError("an exact issued owner and deadline are required")
        if (owner.session.channel_spec_sha256 != broker._spec_digest(self._spec)
                or owner.session.local_service != self._spec.responder_service):
            raise GatewayServiceError("the owner is not this gateway's responder")
        self._serve_connection(owner, deadline=deadline)

    def _serve_connection(self, connection, *, deadline, wire_log=None) -> None:
        message_id, _incoming, request = _read_logical_connection(connection, message_type=REQUEST_TYPE,
            correlation_id=None, deadline=deadline)
        self._serve_logical(connection, message_id=message_id, request=request, deadline=deadline,
                            wire_log=wire_log)

    def _serve_logical(self, connection, *, message_id, request, deadline, wire_log=None) -> None:
        """The already-read logical handoff: one dispatch of one decoded request, one
        bounded reply correlated to it. `_dispatch` stays the sole operation/field
        validator; its sanitized codes are the only failure the wire carries."""
        try:
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
        _write_logical_connection(
            connection,
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
