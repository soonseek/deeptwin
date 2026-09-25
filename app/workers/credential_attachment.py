"""The credential gateway attachment: one nonsecret deployment object, read by both sides (T090).

The deployment names the credential gateway endpoint once, in the exact object
`{"schema": "deeptwin-credential-gateway-attachment-v1", "pair_root", "requester_boot_id"}`.
The control plane reads it (`app.server --credential-gateway-config`) to connect as the
requester under that boot label; the gateway service reads the *same* object
(`app.workers.credential_gateway_main --attachment-config`) and accepts only a handshake
whose authenticated requester hello carries that label. Neither side generates or
overrides it, so the two cannot disagree without every handshake failing closed.

The boot label is not a secret and not a trust root on its own: the per-boot pair
secret written by the root-only IPC initializer (`ipc_root.initialize_pair_root`)
authenticates the handshake, and the kernel's SO_PEERCRED identity separates the pair
group's members. The label binds each session transcript to the configured pairing.

This module performs no I/O beyond reading the one bounded file it is handed, and
imports no vault, route or web code.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

SCHEMA = "deeptwin-credential-gateway-attachment-v1"
MAX_ATTACHMENT_BYTES = 4_096
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

__all__ = ["MAX_ATTACHMENT_BYTES", "SCHEMA", "CredentialGatewayConfiguration", "read_bounded_file"]


@dataclass(frozen=True, slots=True)
class CredentialGatewayConfiguration:
    """The operator's nonsecret naming of the gateway endpoint."""

    pair_root: str
    requester_boot_id: str

    def __post_init__(self):
        if (type(self.pair_root) is not str or not 1 <= len(self.pair_root.encode("utf-8")) <= 4096
                or not self.pair_root.startswith("/") or ".." in Path(self.pair_root).parts):
            raise ValueError("credential gateway pair root is invalid")
        if type(self.requester_boot_id) is not str or _BOOT_ID.fullmatch(self.requester_boot_id) is None:
            raise ValueError("credential gateway requester boot id is invalid")

    @classmethod
    def from_mapping(cls, value) -> CredentialGatewayConfiguration:
        if type(value) is not dict or set(value) != {"schema", "pair_root", "requester_boot_id"}:
            raise ValueError("credential gateway configuration is not the exact attachment object")
        if value["schema"] != SCHEMA:
            raise ValueError("credential gateway configuration schema is unsupported")
        return cls(pair_root=value["pair_root"], requester_boot_id=value["requester_boot_id"])


def read_bounded_file(path, maximum: int) -> bytes:
    """One regular, non-symlink file of at most `maximum` bytes, read whole."""

    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("configuration path is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= maximum:
            raise ValueError("configuration file is invalid")
        chunks, remaining = [], maximum + 1
        while remaining > 0:
            chunk = os.read(descriptor, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if not 1 <= len(raw) <= maximum:
            raise ValueError("configuration file is invalid")
        return raw
    finally:
        os.close(descriptor)
