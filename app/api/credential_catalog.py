"""The owner's explicit catalog refresh over the gateway's provider-send path (T090).

:class:`GatewayCatalogLister` is the control-plane side of one refresh. It names the
bound record (nonsecret custody metadata and reference) in a `provider-send-prepare-v1`
dialogue for the `models` endpoint, one dialogue per page, through a
:class:`~app.workers.provider_send_client.ProviderSendClient`. The gateway resolves the
credential from its own custody, injects it at send time and only for the record its
binding head binds (checked at claim time); the control plane never sees the key and
imports no vault code. Pages are parsed and joined by the semantic codec's bounded
catalog traversal. Failures are reduced to sanitized codes; no provider byte is
returned.

Budget binding (T090): every page is bound to a budget reservation recorded before its
prepare frame is written (:class:`~app.runtime.gateway_send_budget.GatewayCatalogBudget`,
one zero-cost bounded session per refresh) and settled with the observed usage after.
A lister without a budget sends nothing (``budget_refused``); a page beyond the policy,
or a page an earlier attempt of the same refresh already reserved, is refused before any
provider byte. The gateway refuses an unqualified transport manifest
(``transport_unqualified``) and a reservation a send already consumed.

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


class _NotSent:
    """The observation of a page the requester knows was not sent."""

    phase = "not_sent"
    body = b""


def _canonical_digest(value):
    from ..domain.refs import canonical_json

    return sha256(canonical_json(value)).hexdigest()


class GatewayCatalogLister:
    """Read the provider's model list for one bound record through the gateway."""

    __slots__ = ("_budget", "_client_factory")

    def __init__(self, client_factory, *, budget=None):
        from ..runtime.gateway_send_budget import GatewayCatalogBudget

        if not callable(client_factory):
            raise TypeError("a provider-send client factory is required")
        if budget is not None and type(budget) is not GatewayCatalogBudget:
            raise TypeError("an exact gateway catalog budget is required")
        self._client_factory = client_factory
        self._budget = budget

    def with_budget(self, budget):
        """The same lister, bound to the host's budget book (the composition step)."""
        return type(self)(self._client_factory, budget=budget)

    @staticmethod
    def _refused(failure_class, phase):
        """The sanitized code of a gateway refusal before any provider byte, or None."""
        if phase not in (None, "not_sent"):
            return None
        return {"permission_denied": "binding_refused",
                "unsupported_capability": "transport_unqualified",
                "resource_exhausted": "budget_refused"}.get(failure_class)

    def __call__(self, *, provider, metadata, record, binding_revision, refresh_id):
        from ..workers.credential_contracts import fingerprint
        from ..workers.provider_semantic_codec import (
            CatalogTraversal,
            advance_catalog,
            parse_model_page,
        )
        from ..runtime.gateway_send_budget import GatewaySendBudgetError
        from ..workers.provider_send_messages import ProviderSendError, prepare_message

        if provider != "claude" or metadata.get("provider") != provider:
            raise CatalogListError("binding_refused")
        if self._budget is None:
            # no budget binding composed: no page may be sent
            raise CatalogListError("budget_refused")
        try:
            session_id = self._budget.open("credential-catalog-refresh:" + refresh_id)
        except GatewaySendBudgetError:
            raise CatalogListError("budget_refused") from None
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
        for page_index in range(_MAX_PAGES):
            deadline_at = (datetime.now(UTC) + timedelta(milliseconds=_PAGE_MS)).isoformat(
                timespec="milliseconds").replace("+00:00", "Z")
            # write-ahead: the page's reservation is recorded (reserved and dispatched in
            # one budget transaction) before the prepare frame exists
            try:
                reservation = self._budget.reserve_page(session_id, page_index)
            except GatewaySendBudgetError:
                raise CatalogListError("budget_refused") from None
            observed, committing = None, False
            try:
                client = self._client_factory()
                try:
                    prepared = prepare_message(operation_ref=operation_ref, request_id=str(uuid4()),
                        request_sha256=_canonical_digest({"catalog_refresh": refresh_id,
                                                          "after_id": after_id, **head}),
                        selected_handle_ref=handle_ref, connection_pin=pin,
                        credential_metadata=metadata, credential_record=record,
                        endpoint="models", after_id=after_id, body=b"", remaining_ms=_PAGE_MS,
                        deadline_at=deadline_at, reservation_ref=reservation.reservation_ref)
                    ready = client.prepare(prepared)
                    # from the commit frame on, the gateway may have sent unless it says not
                    committing = True
                    lease = client.commit(ready["exchange_id"], ready["prepare_sha256"],
                                          str(uuid4()))
                    observed = client.exchange(lease)
                finally:
                    try:
                        client.abandon()
                    except Exception:  # noqa: BLE001, S110 - the dialogue is over either way
                        pass
            except ProviderSendError as exc:
                # nothing crossed to the provider only when the gateway says so (or the
                # dialogue never reached a commit); otherwise the usage is unknown
                self._budget.settle(reservation, observed=_NotSent(),
                                    unknown=committing and exc.phase != "not_sent")
                code = self._refused(exc.failure_class, exc.phase)
                raise CatalogListError(code or "provider_unavailable") from None
            self._budget.settle(reservation, observed=observed)
            refused = self._refused(observed.failure_class, observed.phase)
            if refused is not None and observed.phase == "not_sent":
                # the gateway refused before any provider byte: its binding head does not
                # bind this record, its transport is unqualified, or the reservation is spent
                raise CatalogListError(refused)
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
