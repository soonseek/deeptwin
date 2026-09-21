"""The shared first-frame ingress of the provider gateway (Task51; design §5).

Gateway side only. One serial ingress call owns the read cursor of one
accepted owner: it obtains exactly one authenticated `credential_op` first
frame with no correlation, checks the original payload's length before the
single strict decode, and commits to one branch — a plain credential-v2
request or the closed legacy shapes (after the ordinary-message bound) to the
vault engine's already-read handoff, a credential fragment transfer to the
same engine's fragmentation grammar, a plain provider-send prepare to the send
engine's already-read handoff — or closes without dispatch. After the branch
it is one vault operation or one send dialogue until close; a concurrent
ingress call is refused without touching the active owner's reader, and an
already accepted competing owner is closed on rejection. The ingress borrows
the exact services and their one vault; it owns each accepted owner and never
closes the borrowed vault or root.
"""

from __future__ import annotations

import threading

from . import broker, credential_channel
from .credential_channel import (
    REQUEST_TYPE,
    GatewayServiceError,
    _read_logical_connection,
)
from .credential_gateway_service import CredentialGatewayService
from .listener import AuthenticatedConnection, WorkerListener
from .provider_send_service import ProviderSendService

__all__ = ["ProviderGatewayIngress"]

_FIRST_FRAME_BOUND = 24_576
_ORDINARY_BOUND = 16_384
# the existing client's exact legacy shapes (`secret_b64`, not the v2 `secret_b64u`)
_LEGACY_STORE_KEYS = frozenset({"op", "intent_id", "provider", "secret_b64", "rotate_from"})
_LEGACY_DELETE_KEYS = frozenset({"op", "handle"})


class ProviderGatewayIngress:
    """Gateway-side composition of the exact credential and send services."""

    __slots__ = ("_credential", "_latch", "_root", "_send", "_spec", "_usable")

    def __init__(self, credential_service: CredentialGatewayService, send_service: ProviderSendService) -> None:
        from . import gateway_channel as profile

        if (type(credential_service) is not CredentialGatewayService
                or type(send_service) is not ProviderSendService):
            raise GatewayServiceError("exact credential and send services are required")
        if send_service.vault is not credential_service.vault:
            raise GatewayServiceError("the services must share one exact vault")
        root, spec = profile.gateway_channel()
        if credential_service.spec != spec:
            raise GatewayServiceError("the credential service is not bound to the gateway channel")
        self._credential = credential_service
        self._send = send_service
        self._root, self._spec = root, spec
        self._latch = threading.Lock()
        self._usable = True

    @property
    def usable(self) -> bool:
        return self._usable

    def serve_one(self, worker_listener: WorkerListener, *, requester_boot_id: str,
                  deadline: broker.Deadline) -> None:
        """Accept one owner on the exact gateway listener and serve its one dialogue."""
        if type(worker_listener) is not WorkerListener or type(deadline) is not broker.Deadline:
            raise GatewayServiceError("an exact worker listener and deadline are required")
        if worker_listener.root_spec != self._root or worker_listener.spec != self._spec:
            raise GatewayServiceError("the listener is not the gateway's")
        owner = worker_listener.accept_authenticated(requester_boot_id=requester_boot_id, deadline=deadline)
        self._serve_owned(owner, deadline=deadline)

    def serve_connection(self, owner: AuthenticatedConnection, *, deadline: broker.Deadline) -> None:
        """Serve one dialogue on an already accepted owner of the gateway channel; the
        ingress owns the owner from here and closes it."""
        if type(owner) is not AuthenticatedConnection or type(deadline) is not broker.Deadline:
            raise GatewayServiceError("an exact issued owner and deadline are required")
        self._serve_owned(owner, deadline=deadline)

    def _serve_owned(self, owner, *, deadline) -> None:
        try:
            if (owner.session.channel_spec_sha256 != broker._spec_digest(self._spec)
                    or owner.session.local_service != self._spec.responder_service):
                raise GatewayServiceError("the owner is not this gateway's responder")
            if not self._usable:
                raise GatewayServiceError("the gateway ingress is unusable after an unsafe cleanup")
            if not self._latch.acquire(blocking=False):
                # a concurrent ingress call: refused without touching the active dialogue's
                # reader; the competing owner is closed below
                raise GatewayServiceError("the gateway serves one dialogue at a time", code="busy")
            try:
                self._route(owner, deadline)
            finally:
                # a send dialogue whose HTTP thread could not be joined marks the send
                # service unusable; the ingress refuses further dialogues rather than start
                # another request beside a thread it no longer bounds
                if not self._send.usable:
                    self._usable = False
                self._latch.release()
        finally:
            try:
                owner.close()
            except (broker.BrokerError, OSError):
                pass

    def _route(self, owner, deadline) -> None:
        try:
            first = owner.read(deadline=deadline)
        except broker.BrokerError as exc:
            raise GatewayServiceError("gateway first frame failed") from exc
        if first.envelope.message_type != REQUEST_TYPE or first.envelope.correlation_id is not None:
            raise GatewayServiceError("gateway first frame is not bound")
        # the original authenticated payload bytes decide, before and after the one decode
        if len(first.payload) > _FIRST_FRAME_BOUND:
            raise GatewayServiceError("gateway fragment is out of bounds")
        value = credential_channel.decode_op(first.payload)  # exactly once; its own closed error
        schema = value.get("schema")
        if schema == "credential-fragment-v1":
            # the credential branch, committed immediately: the fragmentation grammar consumes
            # the already-read first fragment and the remaining frames; a fragmented
            # semantic prepare is refused after assembly, never rerouted
            message_id, _payload, request = _read_logical_connection(
                owner, message_type=REQUEST_TYPE, correlation_id=None, deadline=deadline,
                first_frame=first, first_value=value)
            if request.get("schema") == "credential-op-v2" or self._legacy_shape(request):
                self._credential._serve_logical(owner, message_id=message_id, request=request,
                                                deadline=deadline)
                return
            raise GatewayServiceError("gateway reconstructed message is not a credential operation")
        if len(first.payload) > _ORDINARY_BOUND:
            raise GatewayServiceError("gateway ordinary message is out of bounds")
        if schema == "provider-send-prepare-v1":
            self._send._serve_dialogue(owner, start_frame=first, header=value, deadline=deadline)
            return
        if schema == "credential-op-v2" or self._legacy_shape(value):
            self._credential._serve_logical(owner, message_id=first.envelope.message_id, request=value,
                                            deadline=deadline)
            return
        raise GatewayServiceError("gateway first frame is not a known operation")

    @staticmethod
    def _legacy_shape(value) -> bool:
        """The existing client's closed legacy shapes, preserved for their exact
        unsupported responses (the values stay untrusted and are discarded there)."""
        keys = set(value)
        return ((keys == _LEGACY_STORE_KEYS and value.get("op") == "store")
                or (keys == _LEGACY_DELETE_KEYS and value.get("op") == "delete"))
