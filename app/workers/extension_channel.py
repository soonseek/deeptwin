"""Fixed extension worker channel values and the fixed image argv parser
(Task 25 slice 1a; T018-foundation transport values for the worker-private
probe over the slot's `broker_pair` socket mount).

Every slot and control identity value is derived from
`deployment.contracts.slot` (the slot's service, channel, uid/gid, pair gid,
socket mount and protocol identity) and `deployment.contracts.CONTROL` (the
control requester) — none of them is restated here; only the application
profile constants and the fixed argv shape are defined in this module. The
pair root of the channel is the slot root's `endpoint`, never the outer root. These are routing facts: inert values with no I/O, authority or
live channel; the worker probe service (slice 3) is their first importer.
The explicit `extension-channel-profile-v1` constants below are an
application profile over the existing framing, not a framing change.
"""

from __future__ import annotations

from pathlib import Path

from ..deployment.contracts import CONTROL, DeploymentSourceError, slot
from . import broker
from .ipc_root import PairRootSpec

EXTENSION_CHANNEL_PROFILE = "extension-channel-profile-v1"
# the message types and protocol identity are the broker's profile constants
# (its extension handshake checks the same values); the slot supplies the
# protocol identity, which must equal the broker's
REQUESTER_MESSAGE_TYPES = broker.EXTENSION_REQUESTER_MESSAGE_TYPES
RESPONDER_MESSAGE_TYPES = broker.EXTENSION_RESPONDER_MESSAGE_TYPES
MAX_FRAME_BYTES = broker.MAX_FRAME_BYTES
MAX_IN_FLIGHT = 1
MAX_QUEUE_DEPTH = 16
MAX_OPERATION_MS = 30_000
_ARGV_LENGTH = 5
_INSTANCE_FLAG = "--instance-id"
_SLOT_FLAG = "--slot-number"


class ExtensionChannelError(ValueError):
    """The slot identity or argv is not the fixed extension worker shape."""


def _slot(instance_id, slot_number) -> dict:
    if type(slot_number) is not int:
        # deployment.contracts.integer refuses bool/float too; this pre-check
        # exists only to name the slot number in the closed error
        raise ExtensionChannelError("slot number must be an exact integer")
    try:
        return slot(instance_id, slot_number)
    except DeploymentSourceError:
        raise ExtensionChannelError("invalid extension slot identity") from None


def extension_channel(
    *, instance_id, slot_number
) -> tuple[PairRootSpec, broker.ChannelSpec]:
    """The pair root and channel of one extension slot, from the slot alone."""

    values = _slot(instance_id, slot_number)
    root = PairRootSpec(
        pair_root=Path(values["socket_mount"]["container_path"]),
        responder_uid=values["uid"],
        responder_gid=values["gid"],
        pair_gid=values["pair_gid"],
    )
    spec = broker.ChannelSpec(
        channel_id=values["channel_id"],
        requester_service=CONTROL["service_identity"],
        responder_service=values["service_identity"],
        request_direction=f"{CONTROL['service_identity']}-to-{values['service_identity']}",
        protocol_id=values["protocol_id"],
        requester_uid=CONTROL["uid"],
        requester_gid=CONTROL["gid"],
        responder_uid=values["uid"],
        responder_gid=values["gid"],
        pair_gid=values["pair_gid"],
        pair_root=root.endpoint_path,
        socket_name=values["socket_name"],
        root_uid=values["uid"],
        root_gid=values["pair_gid"],
        socket_uid=values["uid"],
        socket_gid=values["pair_gid"],
        requester_message_types=REQUESTER_MESSAGE_TYPES,
        responder_message_types=RESPONDER_MESSAGE_TYPES,
        max_frame_bytes=MAX_FRAME_BYTES,
        max_in_flight=MAX_IN_FLIGHT,
        max_queue_depth=MAX_QUEUE_DEPTH,
        max_operation_ms=MAX_OPERATION_MS,
    )
    return root, spec


def parse_worker_argv(argv) -> tuple[str, int]:
    """`[executable, --instance-id, I, --slot-number, N]` exactly; argv[0] is
    the image's packaging concern and is not compared here."""

    if (
        type(argv) is not list
        or len(argv) != _ARGV_LENGTH
        or any(type(item) is not str for item in argv)
        or argv[1] != _INSTANCE_FLAG
        or argv[3] != _SLOT_FLAG
    ):
        raise ExtensionChannelError("invalid worker argv")
    number = argv[4]
    # bounded before any conversion: "1".."16" is at most two ASCII digits
    # with no leading zero, so int() never sees an unbounded string
    if (
        not 1 <= len(number) <= 2
        or not number.isascii()
        or not number.isdigit()
        or number != str(int(number))
    ):
        raise ExtensionChannelError("invalid worker argv")
    values = _slot(argv[2], int(number))
    return argv[2], values["slot_number"]
