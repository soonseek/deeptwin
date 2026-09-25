"""Supported-factory wiring of the credential routes: the `credentials-v1`
contribution (T090).

The deployment names the credential gateway endpoint in an optional, exact
attachment configuration: the verified `cp-provider` pair root and the requester
boot label the gateway expects. When it is named, startup checks it against the
fixed gateway profile (`app.workers.gateway_channel`), opens the control-plane
command ledger in the instance state directory (0600) and builds the frame-only
client whose every call runs the listener's verified connect and authenticated
handshake (readiness record, socket inode, SO_PEERCRED, boot-secret MAC). A
configuration naming anything else fails the start. When it is not named, the
routes are composed unbound and answer an honest `503 dependency_unavailable`:
there is no fallback, no in-process vault and no ledger file.

This module imports no vault code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter

from .credential_commands import CredentialCommandLedger
from .credential_routes import (
    CredentialSeams,
    credential_seams,
    install_credential_ingress,
)

SCHEMA = "deeptwin-credential-gateway-attachment-v1"
LEDGER_NAME = "credential-commands.sqlite3"
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


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


class CredentialAttachment:
    """The live client and ledger the supported factory composed."""

    __slots__ = ("client", "ledger", "ledger_path")

    def __init__(self, *, client, ledger, ledger_path):
        if type(ledger) is not CredentialCommandLedger:
            raise TypeError("an exact credential command ledger is required")
        self.client, self.ledger, self.ledger_path = client, ledger, ledger_path


def open_credential_attachment(configuration, *, state_directory) -> CredentialAttachment:
    """Check the named endpoint against the fixed profile, then open the ledger and client."""

    from ..workers import gateway_channel
    from ..workers.credential_channel import CredentialGatewayClient

    if type(configuration) is not CredentialGatewayConfiguration:
        raise TypeError("an exact credential gateway configuration is required")
    root, _spec = gateway_channel.gateway_channel()
    if Path(configuration.pair_root) != root.pair_root:
        # only the verified cp-provider pair root is a credential gateway endpoint
        raise ValueError("credential gateway endpoint is not the verified pair root")
    directory = Path(state_directory)
    if not directory.is_absolute() or directory.is_symlink() or not directory.is_dir():
        raise ValueError("credential ledger directory is invalid")
    path = directory / LEDGER_NAME
    ledger = CredentialCommandLedger(path)
    client = CredentialGatewayClient.for_gateway(requester_boot_id=configuration.requester_boot_id)
    return CredentialAttachment(client=client, ledger=ledger, ledger_path=path)


def credential_services(context):
    from .first_party import ContributionServices

    attachment = context.credential_gateway
    seams = (CredentialSeams() if attachment is None
             else credential_seams(attachment.client, attachment.ledger))
    return ContributionServices(create_router(seams=seams), {})


def create_router(*, seams):
    router = APIRouter()
    install_credential_ingress(router, seams=seams)
    return router


__all__ = [
    "LEDGER_NAME",
    "SCHEMA",
    "CredentialAttachment",
    "CredentialGatewayConfiguration",
    "create_router",
    "credential_services",
    "open_credential_attachment",
]
