"""The fixed inert shared gateway profile (Task51; contracts/provider-owned-shared-gateway.md §4).

One pure declaration of the `cp-provider` topology: the pair root the control
side and the provider worker share, and the credential-gateway channel over it.
The values agree with the checked-in static service identities, which
production never loads as trust; nothing here performs I/O, binds a listener
or initializes a generation, and no argument can override the profile. A
future bootstrap must establish the generation, the listener and the trusted
requester-boot relationship; this module only names the shape they must have.
"""

from __future__ import annotations

from ..deployment.contracts import CONTROL, IPC_ROOT
from . import broker
from .ipc_root import PairRootSpec

PROFILE_ID = "provider-gateway-channel-v1"
CHANNEL_ID = "cp-provider"
PROTOCOL_ID = "credential-gateway-v1"
PROVIDER_SERVICE = "provider"
PROVIDER_UID = 20_103
PROVIDER_GID = 20_103
PAIR_GID = 21_101
SOCKET_NAME = "worker.sock"
REQUESTER_MESSAGE_TYPES = ("credential_op",)
RESPONDER_MESSAGE_TYPES = ("credential_result",)
MAX_FRAME_BYTES = 65_536
MAX_IN_FLIGHT = 1
MAX_QUEUE_DEPTH = 16
MAX_OPERATION_MS = 30_000

__all__ = ["PROFILE_ID", "gateway_channel"]


def gateway_channel() -> tuple[PairRootSpec, broker.ChannelSpec]:
    """The pair root and channel of the shared provider gateway, from nothing."""

    root = PairRootSpec(
        pair_root=IPC_ROOT / CHANNEL_ID,
        responder_uid=PROVIDER_UID,
        responder_gid=PROVIDER_GID,
        pair_gid=PAIR_GID,
    )
    spec = broker.ChannelSpec(
        channel_id=CHANNEL_ID,
        requester_service=CONTROL["service_identity"],
        responder_service=PROVIDER_SERVICE,
        request_direction=f"{CONTROL['service_identity']}-to-{PROVIDER_SERVICE}",
        protocol_id=PROTOCOL_ID,
        requester_uid=CONTROL["uid"],
        requester_gid=CONTROL["gid"],
        responder_uid=PROVIDER_UID,
        responder_gid=PROVIDER_GID,
        pair_gid=PAIR_GID,
        pair_root=root.endpoint_path,
        socket_name=SOCKET_NAME,
        root_uid=PROVIDER_UID,
        root_gid=PAIR_GID,
        socket_uid=PROVIDER_UID,
        socket_gid=PAIR_GID,
        root_mode=0o2710,
        socket_mode=0o660,
        requester_message_types=REQUESTER_MESSAGE_TYPES,
        responder_message_types=RESPONDER_MESSAGE_TYPES,
        max_frame_bytes=MAX_FRAME_BYTES,
        max_in_flight=MAX_IN_FLIGHT,
        max_queue_depth=MAX_QUEUE_DEPTH,
        max_operation_ms=MAX_OPERATION_MS,
    )
    return root, spec
