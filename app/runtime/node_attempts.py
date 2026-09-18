"""Attempt dispatch through the scheduler (T040, resumption-plan Continuation).

A bound `agent` node visit maps to exactly one ledger attempt whose identities
(attempt, reservation, idempotency key, the three ledger commands and the
result observation) derive from the visit, so a restart reconciles by command
replay and never re-sends. The dispatcher, not the handler, owns the ledger
boundary: reserve → budgeted send intent → a code-owned transport under the
one-shot permit → `accept_result_and_settle`. The node's `EntityRef` is the
accepted `succeeded` result and nothing else: a transport response, a fault or
an unknown outcome is admitted as what it is (the reservation retained as
unknown usage) and fails the visit. The continuations are the ledger's own
proofs: an earlier attempt of the visit definitely never sent (a crash before
the send-intent barrier, reconciled at startup) always admits the next attempt
number of the same execution; an earlier attempt observed terminal with final
usage (`failed`, `timed_out`, `cancelled`, the remote terminal observed) admits
the next attempt only when the dispatcher was built for the owner's recovery
(`retry_after_terminal=True`) — never by default, never after an unknown
outcome. Both are bounded.

The transport is an injected callable `(permit, request, window) -> AttemptTransportResult`
(the window is the consumed one-shot permit window);
no worker-side operation exists yet (T087/T018), so the only transports today are
in-process fakes owned by tests. Effort, models and providers are not modelled
here at all (T042).
"""

from __future__ import annotations

import inspect
import uuid
from dataclasses import dataclass

from ..domain.permissions import Grant, Principal
from ..domain.refs import MAX_INTEGER, EntityRef, uuid_string
from .budgets import BudgetBook, BudgetDispatchRequest, BudgetExceeded, BudgetUsage
from .ledger import (
    REMOTE_TERMINALS,
    RESULT_REASONS,
    TERMINAL_OUTCOMES,
    USAGE_FINALITIES,
    AttemptSpec,
    DispatchPermit,
    LedgerError,
    OwnerIdentity,
    ResultObservation,
    RuntimeLedger,
)

__all__ = [
    "MAX_ATTEMPTS_PER_VISIT",
    "AttemptBinding",
    "AttemptDispatchError",
    "AttemptDispatchRequest",
    "AttemptTransportResult",
    "NodeAttemptDispatcher",
    "VisitAttempt",
    "attempt_identity",
    "reservation_identity",
]

_MAX_NODE_ID = 128
_MAX_BINDINGS = 256
# at most this many attempts per visit, unsent continuations and the owner's
# recovery retries together; each attempt reserves and finalizes its own budget
MAX_ATTEMPTS_PER_VISIT = 4


class AttemptDispatchError(RuntimeError):
    """A visit's attempt could not produce an accepted result; reason codes only."""


def _node_id(value):
    if type(value) is not str or not 1 <= len(value) <= _MAX_NODE_ID:
        raise ValueError("node id must be a bounded string")
    return value


def _count(name, value):
    if type(value) is not int or not 0 <= value <= MAX_INTEGER:
        raise ValueError(f"{name} must be a bounded nonnegative integer")
    return value


def _positive(name, value):
    if type(value) is not int or not 1 <= value <= MAX_INTEGER:
        raise ValueError(f"{name} must be a bounded positive integer")
    return value


def _ref(name, value, kind):
    if type(value) is not EntityRef or value.kind != kind:
        raise TypeError(f"{name} must be an exact {kind} reference")
    return value


def attempt_identity(run_id, node_id, loop_index, attempt_index):
    """The attempt of one visit: deterministic in run, node, loop and attempt index."""
    uuid_string(run_id)
    _node_id(node_id)
    _count("loop index", loop_index)
    _count("attempt index", attempt_index)
    return str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"deeptwin:attempt:{run_id}:{node_id}:{loop_index}:{attempt_index}",
    ))


def reservation_identity(attempt_id):
    uuid_string(attempt_id)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"deeptwin:reservation:{attempt_id}"))


def _command_identity(attempt_id, step):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"deeptwin:command:attempt:{attempt_id}:{step}"))


def _observation_identity(attempt_id):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"deeptwin:observation:{attempt_id}"))


@dataclass(frozen=True, slots=True)
class AttemptBinding:
    """What one bound node needs to reserve and budget an attempt: references and
    counters only; the envelope and profile are caller-supplied context."""

    envelope_ref: EntityRef
    profile_ref: EntityRef
    budget_policy_ref: EntityRef
    deadline_at_ms: int
    lease_duration_ms: int
    model_calls: int
    tool_calls: int
    node_visits: int
    loop_rounds: int
    output_bytes: int
    candidates: int
    api_microunits: int | None
    principal: Principal
    grant: Grant

    @classmethod
    def create(cls, *, envelope_ref, profile_ref, budget_policy_ref, deadline_at_ms,
               lease_duration_ms, model_calls, tool_calls, node_visits, loop_rounds,
               output_bytes, candidates, api_microunits, principal, grant):
        if type(principal) is not Principal or type(grant) is not Grant:
            raise TypeError("Exact principal and grant required")
        return cls(
            _ref("envelope_ref", envelope_ref, "execution_envelope"),
            _ref("profile_ref", profile_ref, "runtime_profile"),
            _ref("budget_policy_ref", budget_policy_ref, "budget_policy"),
            _positive("deadline_at_ms", deadline_at_ms),
            _positive("lease_duration_ms", lease_duration_ms),
            _count("model_calls", model_calls),
            _count("tool_calls", tool_calls),
            _count("node_visits", node_visits),
            _count("loop_rounds", loop_rounds),
            _count("output_bytes", output_bytes),
            _count("candidates", candidates),
            None if api_microunits is None else _count("api_microunits", api_microunits),
            principal,
            grant,
        )


@dataclass(frozen=True, slots=True)
class AttemptDispatchRequest:
    """What the transport learns: identities and references, never bytes."""

    run_id: str
    node_id: str
    execution_id: str
    attempt_id: str
    envelope_ref: EntityRef
    profile_ref: EntityRef
    deadline_at_ms: int


@dataclass(frozen=True, slots=True)
class AttemptTransportResult:
    """What a code-owned transport reports for one attempt, in the ledger's
    result vocabulary; admitted only through `accept_result_and_settle`."""

    outcome: str
    result_ref: EntityRef | None
    usage_finality: str
    remote_terminal_observed: str
    reason_code: str
    usage: BudgetUsage | None

    def __post_init__(self):
        if self.outcome not in TERMINAL_OUTCOMES:
            raise ValueError("Unsupported terminal outcome")
        if self.result_ref is not None and type(self.result_ref) is not EntityRef:
            raise TypeError("Result evidence must be an exact EntityRef")
        if self.usage_finality not in USAGE_FINALITIES:
            raise ValueError("Unsupported usage finality")
        if self.remote_terminal_observed not in REMOTE_TERMINALS:
            raise ValueError("Unsupported remote terminal observation")
        if self.reason_code not in RESULT_REASONS:
            raise ValueError("Unsupported typed result reason")
        if self.usage is not None and type(self.usage) is not BudgetUsage:
            raise TypeError("Exact BudgetUsage or None required")
        if (self.usage_finality == "final") != (self.usage is not None):
            raise ValueError("Final usage needs exact counters; otherwise none")


_UNKNOWN = AttemptTransportResult(
    outcome="outcome_unknown", result_ref=None, usage_finality="unknown",
    remote_terminal_observed="not_observed", reason_code="transport_unknown", usage=None,
)


class VisitAttempt:
    """The one-shot capability a bound node handler receives for its visit: one
    callable and its outcome. Handlers are code-owned registry entries, so this
    is a documented trust boundary, not a sandbox."""

    __slots__ = ("_accepted", "_committed", "_run", "_state")

    def __init__(self, run):
        self._run = run
        self._state = "ready"
        self._committed = None
        self._accepted = None

    @property
    def committed(self):
        """The accepted `succeeded` result reference once dispatched, else None."""
        return self._committed

    @property
    def accepted_attempt(self):
        """The id of the attempt whose accepted result `committed` is, else None."""
        return self._accepted

    def dispatch(self):
        if self._state != "ready":
            raise AttemptDispatchError("attempt_already_dispatched")
        self._state = "dispatching"
        self._committed, self._accepted = self._run()
        self._state = "committed"
        return self._committed

    def __reduce__(self):
        raise TypeError("VisitAttempt is not serializable")

    __copy__ = __deepcopy__ = None


class NodeAttemptDispatcher:
    """Binds agent nodes to ledger attempts; built only by `build`."""

    __slots__ = ("_bindings", "_book", "_ledger", "_owner", "_retry", "_transport")

    def __init__(self):
        raise TypeError("Use NodeAttemptDispatcher.build")

    @classmethod
    def build(cls, *, ledger, budget_book, owner, bindings, transport,
              retry_after_terminal=False):
        if type(retry_after_terminal) is not bool:
            raise TypeError("retry_after_terminal must be a bool")
        if type(ledger) is not RuntimeLedger:
            raise TypeError("Exact RuntimeLedger required")
        if type(budget_book) is not BudgetBook:
            raise TypeError("Exact BudgetBook required")
        if type(owner) is not OwnerIdentity:
            raise TypeError("Exact OwnerIdentity required")
        if type(bindings) is not dict:
            raise TypeError("Bindings must be a closed mapping of node id to AttemptBinding")
        if not 1 <= len(bindings) <= _MAX_BINDINGS:
            raise ValueError("Bindings must name between one and 256 nodes")
        for node_id, binding in bindings.items():
            _node_id(node_id)
            if type(binding) is not AttemptBinding:
                raise TypeError("Bindings must be exact AttemptBinding values")
        if not callable(transport) or isinstance(transport, str):
            raise TypeError("Transport must be callable")
        # a code-owned transport may state the most output bytes an attempt can
        # produce; every binding reserves at least that, or the ledger would settle
        # the attempt as an accounting overrun that blocks the whole budget session
        # (a present bound that fails to read propagates: it never turns the gate off)
        stated = None
        if inspect.getattr_static(transport, "output_bytes_bound", None) is not None:
            stated = transport.output_bytes_bound
        if stated is not None:
            if type(stated) is not int:
                raise TypeError("a transport's output bound is an exact count")
            if stated < 0:
                raise ValueError("a transport's output bound is never negative")
            for node_id, binding in bindings.items():
                if binding.output_bytes < stated:
                    raise ValueError(f"binding for {node_id} reserves less than the transport's output bound")
        dispatcher = object.__new__(cls)
        dispatcher._ledger = ledger
        dispatcher._book = budget_book
        dispatcher._owner = owner
        dispatcher._bindings = dict(bindings)
        dispatcher._transport = transport
        dispatcher._retry = retry_after_terminal
        return dispatcher

    @property
    def ledger(self):
        return self._ledger

    @property
    def node_ids(self):
        return frozenset(self._bindings)

    def for_visit(self, *, run_id, node_id, execution_id, loop_index):
        binding = self._bindings[node_id]
        uuid_string(run_id)
        uuid_string(execution_id)
        _count("loop index", loop_index)

        def run():
            return self._dispatch(run_id, node_id, execution_id, loop_index, binding)

        return VisitAttempt(run)

    def _dispatch(self, run_id, node_id, execution_id, loop_index, binding):
        ledger = self._ledger
        budget_session_id = ledger.get_run(run_id)["spec"]["budget_session_id"]
        for attempt_index in range(MAX_ATTEMPTS_PER_VISIT):
            request = AttemptDispatchRequest(
                run_id=run_id, node_id=node_id, execution_id=execution_id,
                attempt_id=attempt_identity(run_id, node_id, loop_index, attempt_index),
                envelope_ref=binding.envelope_ref, profile_ref=binding.profile_ref,
                deadline_at_ms=binding.deadline_at_ms,
            )
            outcome = self._dispatch_attempt(request, attempt_index + 1, binding,
                                             budget_session_id)
            if outcome is not None:
                return outcome, request.attempt_id
            # the ledger proved this attempt definitely never sent: the next
            # attempt number of the same execution is the honest continuation
        raise AttemptDispatchError("attempt_bound")

    def _dispatch_attempt(self, request, attempt_no, binding, budget_session_id):
        ledger, book = self._ledger, self._book
        attempt_id = request.attempt_id
        reservation_id = reservation_identity(attempt_id)
        spec = AttemptSpec(
            attempt_id, request.execution_id, attempt_no, binding.envelope_ref,
            binding.profile_ref, binding.budget_policy_ref, reservation_id,
            f"deeptwin:attempt:{request.run_id}:{request.node_id}:{attempt_id}",
            self._owner, binding.deadline_at_ms,
        )
        # a spent budget is refused before any row is reserved: runtime.md wants a
        # spend cap visible as the owner's decision, never a stranded open attempt
        self._require_budget(budget_session_id, binding)
        # replay-safe by the deterministic command id and the idempotency key;
        # the reserve snapshot (first or replayed) carries the revision the
        # send-intent CAS binds to, so an unobserved mutation refuses the send
        reserved = ledger.reserve_attempt(_command_identity(attempt_id, "reserve"), spec,
                                          lease_duration_ms=binding.lease_duration_ms)
        budget_request = BudgetDispatchRequest.create(
            session_id=budget_session_id, request_id=reservation_id,
            policy_ref=binding.budget_policy_ref, model_calls=binding.model_calls,
            tool_calls=binding.tool_calls, node_visits=binding.node_visits,
            loop_rounds=binding.loop_rounds, output_bytes=binding.output_bytes,
            candidates=binding.candidates, api_microunits=binding.api_microunits,
        )
        try:
            permit = ledger.commit_budgeted_send_intent(
                _command_identity(attempt_id, "send"), attempt_id, self._owner,
                expected_revision=reserved["revision"], budget_book=book,
                budget_request=budget_request, principal=binding.principal,
                grant=binding.grant,
            )
        except BudgetExceeded:
            raise AttemptDispatchError("attempt_budget_exceeded") from None
        except LedgerError:
            if self._definitely_unsent(attempt_id):
                return None
            raise
        if permit is None:
            if self._definitely_unsent(attempt_id):
                return None
            if self._retry and self._observed_terminal(attempt_id):
                # the owner's recovery: the ledger proved this attempt terminal,
                # observed and finally accounted, so the next attempt number of the
                # same execution is admitted (the reserve enforces the same proof)
                return None
            # exact replay: the send may have started in an earlier process, so
            # only a committed accepted result can resolve this visit; never re-send
            return self._committed_result(request, binding)
        if type(permit) is not DispatchPermit:
            raise AttemptDispatchError("permit_invalid")
        try:
            try:
                # the one-shot use of the permit: consumed once, revalidated
                # against the attempt, lease, run budget session and reservation;
                # the conservative window travels with the permit to the transport
                window = ledger.consume_dispatch_permit_window(permit, budget_book=book)
                result = self._transport(permit, request, window)
                if type(result) is not AttemptTransportResult:
                    raise TypeError("transport result must be an exact AttemptTransportResult")
                if result.result_ref is not None:
                    # a claimed result must resolve in the domain before it is
                    # observed; an unresolvable claim is a broken transport
                    ledger._verify_refs((result.result_ref,))
                observation = self._observation(attempt_id, result)
            except Exception:  # noqa: BLE001 - a transport fault is an unknown outcome
                result = _UNKNOWN
                observation = self._observation(attempt_id, result)
            accepted = ledger.accept_result_and_settle(
                _command_identity(attempt_id, "accept"), observation, budget_book=book,
                usage=result.usage,
            )
        finally:
            # an accepted result already revoked the permit; otherwise the
            # unconsumed permit must not outlive this visit in-process
            ledger.discard_dispatch_permit(permit)
        if accepted["classification"] != "accepted":
            raise AttemptDispatchError("attempt_not_accepted")
        if result.outcome != "succeeded":
            raise AttemptDispatchError(f"attempt_{result.outcome}")
        return result.result_ref

    @staticmethod
    def _observation(attempt_id, result):
        # the ledger's own observation rules apply (an unknown outcome claims no
        # known terminal); a result they refuse is a broken transport
        return ResultObservation(
            observation_id=_observation_identity(attempt_id), attempt_id=attempt_id,
            outcome=result.outcome, result_ref=result.result_ref,
            usage_finality=result.usage_finality,
            remote_terminal_observed=result.remote_terminal_observed,
            reason_code=result.reason_code,
        )

    def _require_budget(self, budget_session_id, binding):
        remaining = self._book.status(budget_session_id)["remaining"]
        for name in ("model_calls", "tool_calls", "node_visits", "loop_rounds", "output_bytes",
                     "candidates"):
            if getattr(binding, name) > remaining[name]:
                raise AttemptDispatchError("attempt_budget_exceeded")
        api = binding.api_microunits
        if api is not None and (remaining["api_microunits"] is None or api > remaining["api_microunits"]):
            raise AttemptDispatchError("attempt_budget_exceeded")

    def _observed_terminal(self, attempt_id):
        """The ledger's retry-safety proof, mirrored: terminal, the remote terminal
        observed, the usage final, no late evidence. A cancelled attempt is excluded
        here: its ledger finality is not the budget book's (nothing in tree settles
        a cancellation), so it is never a retry proof for the dispatcher."""

        row = self._ledger.get_attempt(attempt_id)
        if not (row["phase"] == "terminal"
                and row["terminal_outcome"] in {"failed", "timed_out"}
                and row["remote_terminal_observed"] == row["terminal_outcome"]
                and row["usage_finality"] == "final"):
            return False
        return not any(item["classification"] == "late"
                       for item in self._ledger.result_observations(attempt_id))

    def _definitely_unsent(self, attempt_id):
        row = self._ledger.get_attempt(attempt_id)
        return (row["dispatch_gate"] == "closed"
                and row["send_finality"] == "definitely_not_sent"
                and row["send_intent_at_ms"] is None)

    def _committed_result(self, request, binding):
        committed = self._ledger.lookup_committed_result(
            request.attempt_id, request.execution_id, binding.envelope_ref)
        if committed is None:
            raise AttemptDispatchError("attempt_unresolved")
        if committed["outcome"] != "succeeded" or committed["result_ref"] is None:
            raise AttemptDispatchError(f"attempt_{committed['outcome']}")
        return EntityRef.from_dict(committed["result_ref"])
