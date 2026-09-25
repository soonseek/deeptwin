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

The attachment object itself lives in `app.workers.credential_attachment`, because the
gateway service reads the very same object to learn which requester boot label to expect
(the control plane and the gateway never generate or override it).

This module imports no vault code.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from ..workers.credential_attachment import SCHEMA, CredentialGatewayConfiguration
from .credential_catalog import GatewayCatalogLister
from .credential_commands import CredentialCommandLedger
from .credential_routes import (
    CredentialSeams,
    credential_seams,
    install_credential_ingress,
)

LEDGER_NAME = "credential-commands.sqlite3"


class CredentialAttachment:
    """The live client and ledger the supported factory composed."""

    __slots__ = ("catalog_lister", "client", "ledger", "ledger_path")

    def __init__(self, *, client, ledger, ledger_path, catalog_lister=None):
        if type(ledger) is not CredentialCommandLedger:
            raise TypeError("an exact credential command ledger is required")
        if catalog_lister is not None and type(catalog_lister) is not GatewayCatalogLister:
            raise TypeError("an exact gateway catalog lister is required")
        self.client, self.ledger, self.ledger_path = client, ledger, ledger_path
        self.catalog_lister = catalog_lister


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
    from ..workers.provider_send_client import ProviderSendClient

    ledger = CredentialCommandLedger(path)
    client = CredentialGatewayClient.for_gateway(requester_boot_id=configuration.requester_boot_id)
    boot = configuration.requester_boot_id
    # the owner's explicit catalog refresh: one provider-send dialogue per page on the same
    # verified gateway endpoint (the gateway resolves the key; this process never sees it)
    lister = GatewayCatalogLister(lambda: ProviderSendClient.for_gateway(requester_boot_id=boot))
    return CredentialAttachment(client=client, ledger=ledger, ledger_path=path, catalog_lister=lister)


def credential_services(context):
    from .first_party import ContributionServices

    from ..runtime.gateway_send_budget import GatewayCatalogBudget

    attachment = context.credential_gateway
    lister = None
    if attachment is not None and attachment.catalog_lister is not None:
        # every catalog page is bound to a reservation in the host's budget book (T090)
        lister = attachment.catalog_lister.with_budget(
            GatewayCatalogBudget(context.components.budget_book))
    seams = (CredentialSeams() if attachment is None
             else credential_seams(attachment.client, attachment.ledger,
                                   catalog_lister=lister))
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
