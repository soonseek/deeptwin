"""Budget binding of the gateway's catalog sends (T090, over T023's budget book).

Every provider send through the credential gateway names a budget reservation recorded
before the send. A model message is dispatched only by the runtime ledger's
`commit_budgeted_send_intent`, whose reservation (`budget_reservation`) the prepare
names. A model *list* page (the owner's explicit catalog refresh, or a runtime catalog
operation) is no run attempt, so it is bound here, with the same write-ahead pattern:

- A refresh opens one budget session under the fixed catalog-refresh policy
  (:func:`catalog_refresh_policy`). The policy is zero-cost and bounded. It is an API-mode
  policy whose currency cap is one micro-unit, while every page reserves zero micro-units
  (listing models is not billed), one loop round and the manifest's whole response bound
  in output bytes. At most `CATALOG_MAX_PAGES` pages fit, and a further page is refused
  ``BudgetExceeded``. At most one page is in flight (concurrency 1).
- Each page reserves and is marked ``dispatched`` in ONE budget transaction
  (:meth:`BudgetBook.reserve_and_dispatch`) before the prepare frame is written. The
  reservation is the may-have-sent barrier. The page's request id is derived from the
  session and the page ordinal, so a retried refresh finds the page it already reserved.
  If that page is still ``dispatched`` with no settlement (a crash between reservation
  and send, or during the send), it is settled ``unknown`` (retaining its full
  reservation) and is never re-sent.
- After the page's observation, the reservation is settled with the observed usage:
  zero micro-units, the observed response bytes, and one round when anything may have
  been sent. An outcome the requester cannot observe is settled ``unknown``.

The gateway independently refuses a lease without a reservation and journals each
consumed reservation, so one reservation is never used for two sends.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import canonical_json
from .budgets import BudgetBook, BudgetError, BudgetPolicy, ReservationConflict

CATALOG_MAX_PAGES = 10
CATALOG_WALL_SECONDS = 600
RESERVATION_SCHEMA = "gateway-send-reservation-v1"


class GatewaySendBudgetError(RuntimeError):
    """A page send refused by its budget binding, before any provider byte."""

    CODES = ("budget_refused", "outcome_unknown")

    def __init__(self, code):
        if code not in self.CODES:
            code = "budget_refused"
        self.code = code
        super().__init__(code)


def catalog_refresh_policy(max_response_bytes):
    """The fixed zero-cost, bounded policy of one catalog refresh."""
    return BudgetPolicy.create(
        profile="execution", provider_mode="api", max_model_calls=1, max_tool_calls=1,
        max_node_visits=1, max_loop_rounds=CATALOG_MAX_PAGES,
        max_output_bytes=CATALOG_MAX_PAGES * max_response_bytes, max_concurrency=1,
        max_wall_seconds=CATALOG_WALL_SECONDS, max_candidates=1, currency="USD",
        max_api_microunits=1)


@dataclass(frozen=True, slots=True)
class PageReservation:
    session_id: str
    request_id: str
    reservation_ref: dict


class GatewayCatalogBudget:
    """Write-ahead budget reservations for the gateway's model-list pages."""

    __slots__ = ("_book", "_page_bytes", "_policy")

    def __init__(self, budget_book, *, max_response_bytes=None):
        if type(budget_book) is not BudgetBook:
            raise TypeError("an exact BudgetBook is required")
        if max_response_bytes is None:
            from ..workers.provider_transport_manifest import claude_api_manifest

            max_response_bytes = claude_api_manifest().max_response_bytes
        if type(max_response_bytes) is not int or not 1 <= max_response_bytes <= 8 * 1024 * 1024:
            raise ValueError("a page response bound is required")
        self._book = budget_book
        self._page_bytes = max_response_bytes
        self._policy = catalog_refresh_policy(max_response_bytes)

    @property
    def policy(self) -> BudgetPolicy:
        return self._policy

    @property
    def book(self) -> BudgetBook:
        return self._book

    @staticmethod
    def session_id(scope):
        if type(scope) is not str or not 1 <= len(scope) <= 256:
            raise ValueError("a budget scope is required")
        return str(uuid5(NAMESPACE_URL, "deeptwin:gateway-catalog-budget:" + scope))

    def open(self, scope):
        """Start (or resume) the budget session of one refresh scope."""
        session_id = self.session_id(scope)
        try:
            self._book.start(session_id, self._policy)
        except BudgetError:
            raise GatewaySendBudgetError("budget_refused") from None
        return session_id

    @staticmethod
    def page_request_id(session_id, ordinal):
        if type(ordinal) is not int or not 0 <= ordinal < CATALOG_MAX_PAGES * 4:
            raise ValueError("page ordinal is invalid")
        return str(uuid5(NAMESPACE_URL, f"deeptwin:gateway-catalog-page:{session_id}:{ordinal}"))

    def reserve_page(self, session_id, ordinal) -> PageReservation:
        """Reserve and mark dispatched one page before its send; refuse beyond policy."""
        request_id = self.page_request_id(session_id, ordinal)
        try:
            state = self._book.reservation_state(request_id)
            if state == "dispatched":
                # reserved by an earlier attempt that never settled: its outcome is unknown,
                # the full reservation is retained and it is never sent again
                self._book.settle(request_id, usage_finality="unknown")
            if state is not None:
                raise GatewaySendBudgetError("outcome_unknown")
            reservation = self._book.reserve_and_dispatch(
                session_id, request_id, model_calls=0, tool_calls=0, node_visits=0,
                loop_rounds=1, output_bytes=self._page_bytes, api_microunits=0)
        except GatewaySendBudgetError:
            raise
        except ReservationConflict:
            raise GatewaySendBudgetError("outcome_unknown") from None
        except BudgetError:
            raise GatewaySendBudgetError("budget_refused") from None
        descriptor = {"schema": RESERVATION_SCHEMA, "session_id": session_id,
                      "request_id": request_id, "request_hash": reservation.request_hash,
                      "policy_id": self._policy.id, "endpoint": "models"}
        return PageReservation(session_id, request_id, {
            "kind": "validation_report", "id": request_id, "version": 1,
            "sha256": sha256(canonical_json(descriptor)).hexdigest()})

    def settle(self, reservation, *, observed=None, unknown=False):
        """Settle one page with its observed usage (zero cost), or as unknown."""
        if type(reservation) is not PageReservation:
            raise TypeError("an exact page reservation is required")
        if unknown or observed is None:
            return self._book.settle(reservation.request_id, usage_finality="unknown")
        sent = observed.phase != "not_sent"
        return self._book.settle(
            reservation.request_id, usage_finality="known", model_calls=0, tool_calls=0,
            node_visits=0, loop_rounds=1 if sent else 0,
            output_bytes=len(observed.body) if sent else 0, candidates=0, api_microunits=0)


__all__ = ["CATALOG_MAX_PAGES", "GatewayCatalogBudget", "GatewaySendBudgetError",
           "PageReservation", "catalog_refresh_policy"]
