"""Owner-started runs over the exact bound store and ledger (the connected
browser path: resumption-plan Continuation, US3/T048 route layer).

A run names its inputs by reference: a stored `graph` record (the functional
graph a design produced) and the run's `work_revision`, `environment`,
`run_consent` and `budget_policy` records. The service seals the run manifest
(kind `run_manifest`, keyed by the owner command: the inputs, the compiled
digests, the budget session, the start time and the `run.started` event
sequence) and emits `run.started` into the browser's event stream in the same
transaction; then, outside the store's writer (the ledger and the store share
one database), starts the budget session from the policy record's own
content, creates the ledger run by the same command id and executes the
scheduler to completion or to a human gate. A replay of the command reuses
the sealed manifest whatever happened after it (a crash before the ledger run
or before the execution is completed on replay); a command reused with any
different input is a conflict.

Execution is exclusive per run in this process (a concurrent resume is a
conflict, never a second execution). Reading is a no-execution projection of
the durable head. Resuming runs the head again: a completed head is never
re-run, a rejected gate is reported as such, and a head left by a failed
execution is executed again as a new execution. `run.stopped` is emitted once
per ended execution — completion once per run, `cancelled` once for a rejected
gate, `infrastructure_failure` per failed execution — and its duration is
measured from the run's start. The resume command id is a receipt label, not a
ledger command.

The compilation authority and the handler registry are code-owned host wiring
injected as the run executor (`compile(graph) -> CompiledGraph`,
`scheduler(compiled, *, ledger, run_id, approvals) -> GraphScheduler`), never
page or model input; without one the service is honestly unavailable. The
projection is `SchedulerOutcome` verbatim — bounded identities, references and
counters, never raw graph state. The budget session is started but nothing
reserves or settles against it here (attempt dispatch does that), and the POST
blocks its worker thread for the whole execution.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.graph_schema import GraphContractError, GraphVersion
from ..domain.public_events import (
    EventEnvelope,
    _append_event_in_transaction,
    _assert_event_schema,
    _event_cursor_in_transaction,
    _event_stream,
)
from ..domain.refs import DomainContractError, EntityRef, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from ..runtime.budgets import BudgetBook, BudgetPolicy
from ..runtime.graph import CompiledGraph
from ..runtime.ledger import RevisionConflict, RunSpec, RuntimeLedger
from ..runtime.scheduler import GraphScheduler, SchedulerError, SchedulerOutcome
from .design_persistence import DesignPersistenceError, decode_design_refs
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority
from .run_approvals import PersistentRunApprovals, _authenticate_owner, _owner_actor_ref

__all__ = ["PersistentRuns", "RunServiceError", "manifest_identity", "projection", "run_identity"]

MANIFEST_SCHEMA = "run-manifest-v1"
COMMAND_SCHEMA = "run-create-command-v1"
RESUME_SCHEMA = "run-resume-command-v1"
PHASES = ("created", "running", "awaiting_human", "rejected", "cancelled", "completed")
CANCEL_SCHEMA = "run-cancel-command-v1"
CODES = frozenset({
    "invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
    "too_large", "unavailable",
})
_INPUT_KINDS = {
    "graph_ref": "graph",
    "work_revision_ref": "work_revision",
    "environment_ref": "environment",
    "consent_ref": "run_consent",
    "budget_policy_ref": "budget_policy",
}
_POLICY_FIELDS = (
    "profile", "provider_mode", "max_model_calls", "max_tool_calls", "max_node_visits",
    "max_loop_rounds", "max_output_bytes", "max_concurrency", "max_wall_seconds",
    "currency", "max_api_microunits", "max_candidates",
)


class RunServiceError(ValueError):
    """Closed codes; storage and scheduler detail never leaks."""

    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (RunServiceError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage/scheduler errors must not disclose detail
            raise RunServiceError("unavailable") from None

    return invoke


def run_identity(command_id: str) -> str:
    uuid_string(command_id)
    return str(uuid5(NAMESPACE_URL, f"deeptwin:run:{command_id}"))


def manifest_identity(command_id: str) -> str:
    uuid_string(command_id)
    return str(uuid5(NAMESPACE_URL, f"deeptwin:run-manifest:{command_id}"))


def _budget_session_identity(command_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:run-budget-session:{command_id}"))


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uuid(value) -> str:
    try:
        return uuid_string(value)
    except (DomainContractError, TypeError, ValueError):
        raise RunServiceError("invalid_input") from None


def _ref(value, kind) -> EntityRef:
    try:
        ref = EntityRef.from_dict(value)
    except (DomainContractError, TypeError, ValueError):
        raise RunServiceError("invalid_input") from None
    if ref.kind != kind:
        raise RunServiceError("invalid_input")
    return ref


@dataclass(frozen=True, slots=True)
class RunManifest:
    run_id: str
    command_id: str
    inputs: dict  # name -> EntityRef, the five named inputs
    graph_digest: str
    authority_digest: str
    budget_session_id: str
    started_at_ms: int
    event_sequence: int
    manifest_ref: EntityRef

    @property
    def graph_ref(self) -> EntityRef:
        return self.inputs["graph_ref"]


def projection(outcome: SchedulerOutcome) -> dict:
    """The bounded JSON of a scheduler outcome: identities, references, counters."""

    if type(outcome) is not SchedulerOutcome:
        raise RunServiceError("unavailable")
    return {
        "run_id": outcome.run_id,
        "graph_digest": outcome.graph_digest,
        "completed_node_ids": list(outcome.completed_node_ids),
        "execution_ids": [list(item) for item in outcome.execution_ids],
        "result_refs": [[execution_id, ref.as_dict()] for execution_id, ref in outcome.result_refs],
        "counters": dict(outcome.counters),
        "activations": [[router, target, list(branches)]
                        for router, target, branches in outcome.activations],
        "awaiting_human": [list(item) for item in outcome.awaiting_human],
        "approvals": [[node, [ref.as_dict() for ref in refs]] for node, refs in outcome.approvals],
        "pending_node_ids": list(outcome.pending_node_ids),
        "rejected_human": [list(item) for item in outcome.rejected_human],
    }


def _phase(outcome: SchedulerOutcome, *, cancelled: bool = False) -> str:
    """The run's honest phase from its durable head: cancelled by the owner,
    waiting on a gate, stopped by a rejected gate, finished (nothing pending),
    not started, or running."""

    if cancelled:
        return "cancelled"
    if outcome.awaiting_human:
        return "awaiting_human"
    if outcome.rejected_human:
        return "rejected"
    if not outcome.pending_node_ids:
        return "completed" if outcome.counters else "created"
    return "running"


class PersistentRuns:
    """Creates, executes, resumes and reads owner runs; built once per app."""

    def __init__(self, domain_store, owner_authority, *, ledger, budget_book, approvals,
                 executor=None):
        if (type(domain_store) is not DomainStore
                or type(owner_authority) is not PersistentOwnerAuthority
                or owner_authority._domain is not domain_store
                or type(ledger) is not RuntimeLedger or type(budget_book) is not BudgetBook
                or type(approvals) is not PersistentRunApprovals
                or approvals._domain is not domain_store):
            raise RunServiceError("unavailable")
        if executor is not None and not (
            callable(getattr(executor, "compile", None))
            and callable(getattr(executor, "scheduler", None))
        ):
            raise TypeError("A run executor exposes compile() and scheduler()")
        self._domain = domain_store
        self._owner = owner_authority
        self._ledger = ledger
        self._book = budget_book
        self._approvals = approvals
        self._executor = executor
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    @property
    def available(self) -> bool:
        return self._executor is not None

    # ----------------------------------------------------------------- inputs

    def _record(self, db, roots, ref: EntityRef):
        try:
            return self._domain._load(db, ref, roots)[0]
        except Exception:  # noqa: BLE001 - an unresolvable input is not found
            raise RunServiceError("not_found") from None

    @staticmethod
    def _graph(record) -> GraphVersion:
        content = record.body.get("content")
        if (type(content) is not dict or content.get("design_kind") != "functional_graph"
                or "design" not in content):
            raise RunServiceError("invalid_input")
        try:
            return GraphVersion.from_untrusted(decode_design_refs(content["design"]))
        except (DesignPersistenceError, GraphContractError, DomainContractError,
                TypeError, ValueError):
            raise RunServiceError("invalid_input") from None

    def _compile(self, graph: GraphVersion) -> CompiledGraph:
        if self._executor is None:
            raise RunServiceError("unavailable")
        try:
            compiled = self._executor.compile(graph)
        except (GraphContractError, DomainContractError, TypeError, ValueError):
            raise RunServiceError("invalid_input") from None
        if type(compiled) is not CompiledGraph:
            raise RunServiceError("unavailable")
        return compiled

    @staticmethod
    def _policy(record) -> BudgetPolicy:
        content = record.body.get("content")
        if (type(content) is not dict or content.get("schema_version") != "budget-policy-binding-v1"
                or type(content.get("policy")) is not dict):
            raise RunServiceError("invalid_input")
        body = content["policy"]
        if (set(body) != {"schema_version", *_POLICY_FIELDS}
                or body["schema_version"] != "budget-policy-v1"):
            raise RunServiceError("invalid_input")
        try:
            policy = BudgetPolicy.create(**{name: body[name] for name in _POLICY_FIELDS})
        except (TypeError, ValueError):
            raise RunServiceError("invalid_input") from None
        if policy.id != content.get("policy_hash"):
            raise RunServiceError("invalid_input")
        return policy

    # --------------------------------------------------------------- manifest

    @staticmethod
    def _manifest_from(record, run_id: str) -> RunManifest:
        content = record.body["content"]
        if content.get("schema_version") != MANIFEST_SCHEMA or content.get("run_id") != run_id:
            raise RunServiceError("unavailable")
        return RunManifest(
            run_id=run_id, command_id=content["command_id"],
            inputs={name: EntityRef.from_dict(content["inputs"][name]) for name in _INPUT_KINDS},
            graph_digest=content["graph_digest"], authority_digest=content["authority_digest"],
            budget_session_id=content["budget_session_id"],
            started_at_ms=content["started_at_ms"], event_sequence=content["event_sequence"],
            manifest_ref=record.ref,
        )

    def _manifest_by_command(self, db, roots, command_id: str) -> RunManifest | None:
        """The sealed manifest of one command, whatever happened after it."""

        row = db.execute(
            "SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='run_manifest' "
            "AND id=? AND version=1",
            (roots.genesis.id, manifest_identity(command_id)),
        ).fetchone()
        if row is None:
            return None
        ref = EntityRef("run_manifest", manifest_identity(command_id), 1, row["sha256"])
        return self._manifest_from(self._record(db, roots, ref), run_identity(command_id))

    def _manifest_by_run(self, db, roots, run_id: str) -> RunManifest | None:
        try:
            run = self._ledger.get_run(run_id)
        except KeyError:
            return None
        spec = RunSpec.from_dict(run["spec"])
        manifest = self._manifest_from(self._record(db, roots, spec.manifest_ref), run_id)
        if manifest.budget_session_id != spec.budget_session_id:
            raise RunServiceError("unavailable")
        return manifest

    def _prepare(self, manifest: RunManifest) -> tuple[CompiledGraph, GraphScheduler]:
        """The run's scheduler over its durable head, rebuilt from the stored graph
        by the injected executor; refused if the executor no longer matches."""

        if self._executor is None:
            raise RunServiceError("unavailable")
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            graph = self._graph(self._record(db, roots, manifest.graph_ref))
        compiled = self._compile(graph)
        if (compiled.graph_digest != manifest.graph_digest
                or compiled.authority_digest != manifest.authority_digest):
            raise RunServiceError("unavailable")
        scheduler = self._executor.scheduler(
            compiled, ledger=self._ledger, run_id=manifest.run_id, approvals=self._approvals
        )
        if type(scheduler) is not GraphScheduler:
            raise RunServiceError("unavailable")
        return compiled, scheduler

    def _cancelled(self, run_id: str) -> bool:
        return self._ledger.get_run(run_id)["phase"] == "cancelled"

    def _cancellation(self, run_id: str) -> dict:
        """The two facts experience.md §9 keeps apart: whether new dispatch is
        closed, and per live attempt whether its gate is closed — never a claim
        that the remote work stopped."""

        return {
            "requested": self._cancelled(run_id),
            "attempts": [
                {
                    "attempt_id": item["spec"]["attempt_id"],
                    "execution_id": item["spec"]["execution_id"],
                    "phase": item["phase"],
                    "cancel_state": item["cancel_state"],
                    "dispatch_gate": item["dispatch_gate"],
                    "remote_terminal_observed": item["remote_terminal_observed"],
                }
                for item in self._ledger.attempts_for_run(run_id)
            ],
        }

    def _receipt(self, manifest: RunManifest, outcome, *, command_id, base_path) -> dict:
        root = base_path.rstrip("/")
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            cursor = _event_cursor_in_transaction(
                db, vault_id=roots.genesis.id, sequence=manifest.event_sequence, event_types=()
            )
        cancellation = self._cancellation(manifest.run_id)
        if cancellation["requested"]:
            # a cancelled run waits on nobody; an earlier rejection stays a past fact
            outcome = replace(outcome, awaiting_human=())
        return {
            "command_id": command_id,
            "run_id": manifest.run_id,
            "graph_ref": manifest.graph_ref.as_dict(),
            "graph_digest": manifest.graph_digest,
            "phase": _phase(outcome, cancelled=cancellation["requested"]),
            "cancellation": cancellation,
            "outcome": projection(outcome),
            "links": {
                "self": f"{root}/api/v1/runs/{manifest.run_id}",
                "approvals": f"{root}/api/v1/runs/{manifest.run_id}/approvals",
                "events": f"{root}/api/v1/events",
            },
            "event_cursor": cursor,
        }

    @staticmethod
    def _stop_recorded(db, roots, manifest: RunManifest, reason: str) -> bool:
        """Whether this run already carries a `run.stopped` with that reason: the
        stop events since the run started, decoded from the durable stream."""

        rows = db.execute(
            "SELECT envelope FROM api_event_envelopes WHERE vault_id=? AND "
            "event_type='run.stopped' AND sequence>? ORDER BY sequence",
            (roots.genesis.id, manifest.event_sequence),
        ).fetchall()
        for row in rows:
            envelope = EventEnvelope.from_bytes(row["envelope"])
            if (envelope.correlation_id == manifest.command_id
                    and envelope.public_metadata.get("reason_code") == reason):
                return True
        return False

    def _stop_event(self, actor_ref, manifest: RunManifest, reason: str, *, once=False) -> None:
        stamp = _stamp()
        with _writer(), self._domain._connection(write=True) as db:
            roots = self._domain._read_roots(db)
            if once and self._stop_recorded(db, roots, manifest, reason):
                return
            _append_event_in_transaction(
                db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
                actor_kind="human", actor_ref=actor_ref, event_type="run.stopped",
                object_refs=(), correlation_id=manifest.command_id, causation_id=None,
                status="succeeded", error_code=None,
                public_metadata={"reason_code": reason,
                                 "duration_ms": max(0, _now_ms() - manifest.started_at_ms)},
                private_evidence_refs=(), retention_class="core", policy_ref=roots.access_policy,
            )

    def _lock(self, run_id: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(run_id, threading.Lock())

    def _execute(self, actor_ref, manifest, scheduler, *, resume=False) -> SchedulerOutcome:
        """Run the durable head, exclusively per run and outside any store writer.
        A head that is complete, waiting, rejected or cancelled is reported,
        never re-run; resuming a cancelled run is a conflict."""

        lock = self._lock(manifest.run_id)
        if not lock.acquire(blocking=False):
            raise RunServiceError("conflict")  # another execution of this run is live
        try:
            before = scheduler.observe()
            if self._cancelled(manifest.run_id):
                if resume:
                    raise RunServiceError("conflict")
                return before
            phase = _phase(before)
            if phase == "rejected":
                # the owner's rejection ends the run: `cancelled`, durably once
                self._stop_event(actor_ref, manifest, "cancelled", once=True)
                return before
            if phase in {"completed", "awaiting_human"}:
                return before
            try:
                outcome = scheduler.run()
            except SchedulerError as error:
                if str(error).startswith("approval_rejected:") or self._cancelled(manifest.run_id):
                    # the owner's rejection or cancellation ended the run
                    self._stop_event(actor_ref, manifest, "cancelled", once=True)
                    return scheduler.observe()
                self._stop_event(actor_ref, manifest, "infrastructure_failure")
                raise RunServiceError("unavailable") from None
            if self._cancelled(manifest.run_id):
                # the owner cancelled while this execution ran: it ended the run, once
                self._stop_event(actor_ref, manifest, "cancelled", once=True)
            elif _phase(outcome) == "completed":
                self._stop_event(actor_ref, manifest, "completed", once=True)
            return outcome
        finally:
            lock.release()

    # ---------------------------------------------------------------- commands

    @staticmethod
    def _validate_create(payload) -> dict:
        if (type(payload) is not dict
                or set(payload) != {"schema_version", "command_id", *_INPUT_KINDS}
                or payload["schema_version"] != COMMAND_SCHEMA):
            raise RunServiceError("invalid_input")
        return {"command_id": _uuid(payload["command_id"]),
                **{name: _ref(payload[name], kind) for name, kind in _INPUT_KINDS.items()}}

    def _seal(self, db, roots, actor_ref, command: dict) -> tuple[RunManifest, BudgetPolicy]:
        records = {name: self._record(db, roots, command[name]) for name in _INPUT_KINDS}
        graph = self._graph(records["graph_ref"])
        compiled = self._compile(graph)
        policy = self._policy(records["budget_policy_ref"])
        run_id = run_identity(command["command_id"])
        started_at_ms = _now_ms()
        stamp = _stamp()
        event_sequence = _event_stream(db, roots.genesis.id)["next_sequence"]
        inputs = {name: command[name] for name in _INPUT_KINDS}
        record = ImmutableRecord.create(
            kind="run_manifest", id=manifest_identity(command["command_id"]), version=1,
            created_at_utc=stamp, actor_ref=actor_ref, parent_refs=(command["graph_ref"],),
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            content={
                "schema_version": MANIFEST_SCHEMA,
                "run_id": run_id,
                "command_id": command["command_id"],
                "inputs": {name: ref.as_dict() for name, ref in inputs.items()},
                "graph_digest": compiled.graph_digest,
                "authority_digest": compiled.authority_digest,
                "budget_session_id": _budget_session_identity(command["command_id"]),
                "started_at_ms": started_at_ms,
                "event_sequence": event_sequence,
            },
        )
        self._domain._put_in_transaction(db, record)
        event = _append_event_in_transaction(
            db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
            actor_kind="human", actor_ref=actor_ref, event_type="run.started", object_refs=(),
            correlation_id=command["command_id"], causation_id=None, status="succeeded",
            error_code=None,
            public_metadata={"node_count": len(graph.nodes), "edge_count": len(graph.edges)},
            private_evidence_refs=(), retention_class="core", policy_ref=roots.access_policy,
        )
        if event.sequence != event_sequence:
            raise RunServiceError("unavailable")
        manifest = RunManifest(
            run_id=run_id, command_id=command["command_id"], inputs=inputs,
            graph_digest=compiled.graph_digest, authority_digest=compiled.authority_digest,
            budget_session_id=_budget_session_identity(command["command_id"]),
            started_at_ms=started_at_ms, event_sequence=event_sequence, manifest_ref=record.ref,
        )
        return manifest, policy

    @_closed
    def create(self, request, payload, *, base_path) -> dict:
        _authenticate_owner(self._owner, request)
        command = self._validate_create(payload)
        if self._executor is None:
            raise RunServiceError("unavailable")
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            _assert_event_schema(db, roots.genesis.id)
            actor_ref = _owner_actor_ref(db, actor)
            manifest = self._manifest_by_command(db, roots, command["command_id"])
            if manifest is not None:
                # a replay reuses the sealed manifest; any different input is a conflict
                if any(manifest.inputs[name] != command[name] for name in _INPUT_KINDS):
                    raise RunServiceError("conflict")
                policy = self._policy(self._record(db, roots, command["budget_policy_ref"]))
            else:
                manifest, policy = self._seal(db, roots, actor_ref, command)
        try:
            self._ledger.get_run(manifest.run_id)
        except KeyError:
            # replay-safe by the session id (same policy) and the command id
            self._book.start(manifest.budget_session_id, policy)
            spec = RunSpec(manifest.run_id, command["work_revision_ref"], command["environment_ref"],
                           command["consent_ref"], "live", command["budget_policy_ref"],
                           manifest.budget_session_id, manifest.manifest_ref)
            self._ledger.create_run(command["command_id"], spec)
        _compiled, scheduler = self._prepare(manifest)
        outcome = self._execute(actor_ref, manifest, scheduler)
        return self._receipt(manifest, outcome, command_id=command["command_id"],
                             base_path=base_path)

    @_closed
    def resume(self, request, run_id, payload, *, base_path) -> dict:
        _authenticate_owner(self._owner, request)
        if (type(payload) is not dict or set(payload) != {"schema_version", "command_id"}
                or payload["schema_version"] != RESUME_SCHEMA):
            raise RunServiceError("invalid_input")
        command_id = _uuid(payload["command_id"])  # a receipt label, not a ledger command
        run_id = _uuid(run_id)
        with _writer(), self._domain._connection(write=True) as db:
            # the live session is re-checked inside the writer, as every owner command is
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            manifest = self._manifest_by_run(db, roots, run_id)
        if manifest is None:
            raise RunServiceError("not_found")
        _compiled, scheduler = self._prepare(manifest)
        outcome = self._execute(actor_ref, manifest, scheduler, resume=True)
        return self._receipt(manifest, outcome, command_id=command_id, base_path=base_path)

    @_closed
    def cancel(self, request, run_id, payload, *, base_path) -> dict:
        """Cancel the run: the durable run phase first, then each live attempt's
        dispatch gate, then `run.stopped(cancelled)` once. A completed run cannot be
        cancelled (conflict); the receipt states what was closed, never that the
        remote work stopped."""

        _authenticate_owner(self._owner, request)
        if (type(payload) is not dict or set(payload) != {"schema_version", "command_id"}
                or payload["schema_version"] != CANCEL_SCHEMA):
            raise RunServiceError("invalid_input")
        command_id = _uuid(payload["command_id"])
        run_id = _uuid(run_id)
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            actor_ref = _owner_actor_ref(db, actor)
            manifest = self._manifest_by_run(db, roots, run_id)
        if manifest is None:
            raise RunServiceError("not_found")
        # the durable closure never depends on the executor: the run's phase, then
        # every live attempt's gate, then the stop event — under the run lock when
        # no execution is live (so completion cannot slip in between the check and
        # the closure); a live execution ends the run itself, once
        lock = self._lock(run_id)
        held = lock.acquire(blocking=False)
        try:
            if held and not self._cancelled(run_id) and self._completed(manifest):
                raise RunServiceError("conflict")  # a finished run has nothing to cancel
            self._ledger.cancel_run(command_id, run_id)
        finally:
            if held:
                lock.release()
        self._close_attempts(command_id, run_id)
        self._stop_event(actor_ref, manifest, "cancelled", once=True)
        _compiled, scheduler = self._prepare(manifest)
        return self._receipt(manifest, scheduler.observe(), command_id=command_id,
                             base_path=base_path)

    def _completed(self, manifest: RunManifest) -> bool:
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            return self._stop_recorded(db, roots, manifest, "completed")

    def _close_attempts(self, command_id: str, run_id: str, *, passes: int = 3) -> None:
        """Request the cancel of every live attempt of the run; an attempt that moved
        between the snapshot and the request is re-read and requested again
        (bounded), with one deterministic command per (cancel command, attempt)."""

        for _ in range(passes):
            conflict = False
            for item in self._ledger.attempts_for_run(run_id):
                if item["phase"] == "terminal" or item["cancel_state"] != "none":
                    continue
                attempt_id = item["spec"]["attempt_id"]
                try:
                    self._ledger.request_cancel(
                        str(uuid5(NAMESPACE_URL,
                                  f"deeptwin:command:run-cancel:{command_id}:{attempt_id}")),
                        attempt_id, expected_revision=item["revision"],
                    )
                except RevisionConflict:
                    conflict = True
            if not conflict:
                return
        raise RunServiceError("unavailable")

    @_closed
    def read(self, run_id, *, base_path) -> dict:
        run_id = _uuid(run_id)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            manifest = self._manifest_by_run(db, roots, run_id)
        if manifest is None:
            raise RunServiceError("not_found")
        _compiled, scheduler = self._prepare(manifest)
        outcome = scheduler.observe()  # a read never executes
        return self._receipt(manifest, outcome, command_id=manifest.command_id,
                             base_path=base_path)
