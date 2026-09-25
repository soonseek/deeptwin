"""The fixed `cp-backup` profile and its attachment object (T070; operations.md §5.2).

One pure declaration of the backup-crypto channel: the pair root the control plane
(requester, `control` 20102) and the networkless backup-crypto worker (responder,
`backup` 20111, pair group 21109) share, exactly as deploy/security/service-ids.json
and the root-only IPC initializer in deploy/compose.yaml name it. Nothing here
performs I/O beyond reading the one bounded attachment file it is handed, binds a
listener or initializes a generation, and no argument can override the profile.

The deployment names the endpoint once, in the exact nonsecret object
`{"schema": "deeptwin-backup-crypto-attachment-v1", "pair_root", "requester_boot_id"}`.
The control plane reads it (`app.server --backup-worker-config`) to connect as the
requester under that boot label; the worker reads the same object
(`app.workers.backup_crypto_main --attachment-config`) and accepts only a handshake
carrying that label. The per-boot pair secret written by `ipc_root.initialize_pair_root`
authenticates every handshake; SO_PEERCRED separates the pair group's members.

The channel carries only the typed backup stream (`app.workers.backup_stream`):
requests, bounded chunks of an archive or ciphertext, and an end frame binding the
body's size and SHA-256. It never carries a key file, a path or a vault handle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..deployment.contracts import CONTROL, IPC_ROOT
from . import broker
from .ipc_root import PairRootSpec

PROFILE_ID = "backup-crypto-channel-v1"
CHANNEL_ID = "cp-backup"
PROTOCOL_ID = "backup-crypto-v1"
BACKUP_SERVICE = "backup"
BACKUP_UID = 20_111
BACKUP_GID = 20_111
PAIR_GID = 21_109
SOCKET_NAME = "worker.sock"
REQUESTER_MESSAGE_TYPES = ("backup_chunk", "backup_end", "backup_request")
RESPONDER_MESSAGE_TYPES = ("backup_chunk", "backup_end", "backup_result")
MAX_FRAME_BYTES = 65_536
MAX_IN_FLIGHT = 1
MAX_QUEUE_DEPTH = 4
# one connection carries one whole archive each way; age itself is bound to 600 s
MAX_OPERATION_MS = 900_000
ATTACHMENT_SCHEMA = "deeptwin-backup-crypto-attachment-v1"
MAX_ATTACHMENT_BYTES = 4_096
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

__all__ = ["ATTACHMENT_SCHEMA", "PROFILE_ID", "BackupWorkerConfiguration", "backup_channel"]


def backup_channel() -> tuple[PairRootSpec, broker.ChannelSpec]:
    """The pair root and channel of the backup-crypto worker, from nothing."""

    root = PairRootSpec(
        pair_root=IPC_ROOT / CHANNEL_ID,
        responder_uid=BACKUP_UID,
        responder_gid=BACKUP_GID,
        pair_gid=PAIR_GID,
    )
    spec = broker.ChannelSpec(
        channel_id=CHANNEL_ID,
        requester_service=CONTROL["service_identity"],
        responder_service=BACKUP_SERVICE,
        request_direction=f"{CONTROL['service_identity']}-to-{BACKUP_SERVICE}",
        protocol_id=PROTOCOL_ID,
        requester_uid=CONTROL["uid"],
        requester_gid=CONTROL["gid"],
        responder_uid=BACKUP_UID,
        responder_gid=BACKUP_GID,
        pair_gid=PAIR_GID,
        pair_root=root.endpoint_path,
        socket_name=SOCKET_NAME,
        root_uid=BACKUP_UID,
        root_gid=PAIR_GID,
        socket_uid=BACKUP_UID,
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


@dataclass(frozen=True, slots=True)
class BackupWorkerConfiguration:
    """The operator's nonsecret naming of the backup-crypto endpoint."""

    pair_root: str
    requester_boot_id: str

    def __post_init__(self):
        if (type(self.pair_root) is not str or not 1 <= len(self.pair_root.encode("utf-8")) <= 4096
                or not self.pair_root.startswith("/") or ".." in Path(self.pair_root).parts):
            raise ValueError("backup worker pair root is invalid")
        if type(self.requester_boot_id) is not str or _BOOT_ID.fullmatch(self.requester_boot_id) is None:
            raise ValueError("backup worker requester boot id is invalid")

    @classmethod
    def from_mapping(cls, value) -> BackupWorkerConfiguration:
        if type(value) is not dict or set(value) != {"schema", "pair_root", "requester_boot_id"}:
            raise ValueError("backup worker configuration is not the exact attachment object")
        if value["schema"] != ATTACHMENT_SCHEMA:
            raise ValueError("backup worker configuration schema is unsupported")
        return cls(pair_root=value["pair_root"], requester_boot_id=value["requester_boot_id"])

    def check_profile(self) -> None:
        """Only the verified `cp-backup` pair root is a backup-crypto endpoint."""

        root, _spec = backup_channel()
        if Path(self.pair_root) != root.pair_root:
            raise ValueError("backup worker endpoint is not the verified pair root")
