"""The owner's explicit catalog refresh over the gateway's provider-send path (T090).

:class:`GatewayCatalogLister` is the control-plane side of one refresh. It names the
bound record (nonsecret custody metadata and reference) in a `provider-send-prepare-v1`
dialogue for the `models` endpoint, one dialogue per page, through a
:class:`~app.workers.provider_send_client.ProviderSendClient`. The gateway resolves the
credential from its own custody, injects it at send time and only for the record its
binding head binds (checked at claim time); the control plane never sees the key and
imports no vault code. Pages are parsed and joined by the semantic codec's bounded
catalog traversal. Failures are reduced to three sanitized codes; no provider byte is
returned.

Nothing but :meth:`~app.api.credential_commands.CredentialActs.refresh_catalog` calls
this, and only on the owner's explicit refresh act.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid4, uuid5

from .credential_commands import CatalogListError

_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_MODELS = 200
_MAX_PAGES = 10
_PAGE_MS = 20_000


def _canonical_digest(value):
    from ..domain.refs import canonical_json

    return sha256(canonical_json(value)).hexdigest()


class GatewayCatalogLister:
    """Read the provider's model list for one bound record through the gateway."""

    __slots__ = ("_client_factory",)

    def __init__(self, client_factory):
        if not callable(client_factory):
            raise TypeError("a provider-send client factory is required")
        self._client_factory = client_factory

    def __call__(self, *, provider, metadata, record, binding_revision, refresh_id):
        from ..workers.credential_contracts import fingerprint
        from ..workers.provider_semantic_codec import (
            CatalogTraversal,
            advance_catalog,
            parse_model_page,
        )
        from ..workers.provider_send_messages import ProviderSendError, prepare_message

        if provider != "claude" or metadata.get("provider") != provider:
            raise CatalogListError("binding_refused")
        head = {"provider": provider, "revision": binding_revision, "record": record}
        head_digest = _canonical_digest(head)
        # nonsecret wire labels for this one refresh; they confer no authority (the gateway
        # decides by its own binding head and custody)
        operation_ref = {"kind": "model_catalog", "id": refresh_id, "version": 1,
                         "sha256": _canonical_digest({"refresh": refresh_id, **head})}
        handle_ref = {"kind": "model_catalog", "id": metadata["command_id"],
                      "version": binding_revision, "sha256": head_digest}
        pin = {"locator": {"kind": "connection",
                           "id": str(uuid5(NAMESPACE_URL, "deeptwin:credential-connection:" + provider))},
               "revision_digest": head_digest, "provider_id": "claude_api", "account_id": "owner",
               "credential_metadata_sha256": fingerprint(metadata)}
        traversal, after_id = CatalogTraversal(), None
        for _page in range(_MAX_PAGES):
            deadline_at = (datetime.now(UTC) + timedelta(milliseconds=_PAGE_MS)).isoformat(
                timespec="milliseconds").replace("+00:00", "Z")
            client = self._client_factory()
            try:
                prepared = prepare_message(operation_ref=operation_ref, request_id=str(uuid4()),
                    request_sha256=_canonical_digest({"catalog_refresh": refresh_id,
                                                      "after_id": after_id, **head}),
                    selected_handle_ref=handle_ref, connection_pin=pin,
                    credential_metadata=metadata, credential_record=record, endpoint="models",
                    after_id=after_id, body=b"", remaining_ms=_PAGE_MS, deadline_at=deadline_at,
                    reservation_ref=None)
                ready = client.prepare(prepared)
                lease = client.commit(ready["exchange_id"], ready["prepare_sha256"], str(uuid4()))
                observed = client.exchange(lease)
            except ProviderSendError as exc:
                if exc.failure_class == "permission_denied" and exc.phase in (None, "not_sent"):
                    raise CatalogListError("binding_refused") from None
                raise CatalogListError("provider_unavailable") from None
            finally:
                try:
                    client.abandon()
                except Exception:  # noqa: BLE001, S110 - the dialogue is over either way
                    pass
            if observed.failure_class == "permission_denied" and observed.phase == "not_sent":
                # the gateway refused custody: its binding head does not bind this record
                raise CatalogListError("binding_refused")
            if observed.status in (401, 403):
                raise CatalogListError("provider_rejected")
            if (observed.failure_class is not None or observed.status is None
                    or not 200 <= observed.status < 300):
                raise CatalogListError("provider_unavailable")
            try:
                page = parse_model_page(observed.body)
                traversal = advance_catalog(traversal, page)
            except (ValueError, TypeError):
                raise CatalogListError("provider_unavailable") from None
            if traversal.complete:
                break
            after_id = page.last_id
        else:
            raise CatalogListError("provider_unavailable")
        models = list(traversal.model_ids)
        if (not 1 <= len(models) <= _MAX_MODELS
                or any(_MODEL.fullmatch(model) is None for model in models)):
            raise CatalogListError("provider_unavailable")
        return models


__all__ = ["GatewayCatalogLister"]
