"""The owner's read-only trace of one run (docs/ui/2026-09-26-product-ux-redesign.md §7;
experience.md §7: visits, attempts, inputs, outputs, hand-offs, tool and model calls).

Everything here is assembled from what the run already left durably; nothing is computed
to fill a gap, and nothing is executed, sent or re-read from a provider:

- the run manifest (inputs, start time) and the compiled graph it was bound to, through
  `PersistentRuns.observe_parts` (a read that never executes);
- the runtime ledger: one execution per node visit with the parent visits recorded at
  dispatch, the attempts of each visit (times, terminal outcome, the accepted result
  observation and its typed reason), the attempt journal's transitions, the tool call of
  an attempt (tool, version, effect class, declared inputs, state, sealed result,
  approval) and the checkpoint rows naming which attempt produced a visit's result
  (`run_trace.read_run_trace`);
- the budget book's reservation of each attempt (reserved counters, the settled actuals
  once finalized): a reserved currency amount is the conservative ceiling set before the
  send, shown as an estimate, never as a charge;
- the Claude executor's call records for a handler-run model node (the intent sealed
  before the send, the output or outcome sealed after, with the provider's reported model
  and token usage); that executor records no cost, so a cost is `unknown`;
- the owner's approval records (gate decisions and execution-bound decisions of each
  attempt) and the run's public stop events.

A value the runtime did not record is the literal string `not_recorded` (and a closed
reason in `gaps`). Hidden reasoning is never stored, so it is never shown; credential
material, raw provider payloads, request bodies and handler detail are not part of any
record read here. Owner session only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.public_events import EventEnvelope
from ..domain.refs import DomainContractError, EntityRef, uuid_string
from .owner_auth import OwnerAuthError
from .run_artifacts import _entries, artifact_identity
from .run_trace import RunTraceError, read_run_trace
from .runs import RunServiceError

__all__ = ["NOT_RECORDED", "PersistentRunTraces", "RunTraceReadError", "TRACE_SCHEMA"]

TRACE_SCHEMA = "run-trace-v1"
NOT_RECORDED = "not_recorded"
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "unavailable"})
# the Claude executor's call records (app/services/claude_run_executor.py)
_INTENT_SCHEMA = "claude-call-intent-v1"
_OUTPUT_SCHEMA = "claude-model-output-v1"
_OUTCOME_SCHEMA = "claude-call-outcome-v1"
_TITLE_CHARS = 120
_MAX_EVENT_ROWS = 10_000
# why a category is absent, in one closed vocabulary (the UI words them)
GAP_REASONS = {
    "attempt_tokens": "a model attempt through the attempt ledger records its budget reservation "
                      "and settlement, not the provider's token counts",
    "handoff_receipt": "the run records the parent visits and their exact results at dispatch; "
                       "a receiver acknowledgment of a hand-off is not recorded by this runtime",
    "handler_attempts": "a visit run in-process by the executor's handler has no ledger attempt; "
                        "its result and any call records are listed on the visit",
    "handler_error": "a handler failure is kept private by the scheduler (the node failed, "
                     "nothing else is recorded)",
    "model_cost": "the Claude executor records the provider's token usage but no cost",
    "reasoning": "hidden model reasoning is never stored",
}


class RunTraceReadError(ValueError):
    """Closed codes; ledger, store and executor detail never leak."""

    def __init__(self, code="unavailable"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RunServiceError as error:
            raise RunTraceReadError(error.code) from None
        except (RunTraceReadError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage/ledger detail stays private
            raise RunTraceReadError("unavailable") from None

    return invoke


def _utc_ms(value):
    if type(value) is not int or value < 0:
        return NOT_RECORDED
    return datetime.fromtimestamp(value / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _utc_seconds(value):
    if type(value) is not int or value < 0:
        return NOT_RECORDED
    return datetime.fromtimestamp(value, UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def _recorded(value):
    return NOT_RECORDED if value is None else value


class PersistentRunTraces:
    """Reads one run's trace for its owner; built once per app from the run services."""

    def __init__(self, domain_store, owner_authority, *, runs, approvals, ledger, budget_book):
        self._domain = domain_store
        self._owner = owner_authority
        self._runs = runs
        self._approvals = approvals
        self._ledger = ledger
        self._book = budget_book

    def _check(self, request):
        if request is None:
            raise RunTraceReadError("unauthenticated")
        self._owner.authenticate_bound(request.session)

    # ------------------------------------------------------------------ records

    def _record(self, ref):
        try:
            return self._domain.get(ref)
        except Exception:  # noqa: BLE001 - an unreadable record is reported, never guessed
            return None

    def _record_by_id(self, kind, identity):
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            row = db.execute(
                "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
                "ORDER BY version DESC LIMIT 1", (roots.genesis.id, kind, identity)).fetchone()
        if row is None:
            return None
        return self._record(EntityRef(kind, identity, row["version"], row["sha256"]))

    def _artifacts(self, result_ref):
        """The artifact entries one exact result record declares (the same ids the run's
        artifact routes serve), or [] for a result that is not an artifact list."""

        if result_ref is None:
            return []
        record = self._record(result_ref)
        if record is None:
            return []
        try:
            entries = _entries(record)
        except Exception:  # noqa: BLE001 - a malformed result is not an artifact list
            return []
        return [{
            "artifact_id": artifact_identity(result_ref, entry["ordinal"]),
            "role": entry["role"], "ordinal": entry["ordinal"],
            "declared_media_type": entry["media_type"],
            "size": entry["blob"].size, "sha256": entry["blob"].sha256,
            "result_ref": result_ref.as_dict(),
        } for entry in entries]

    # ------------------------------------------------------------------ pieces

    def _work(self, manifest):
        ref = manifest.inputs["work_revision_ref"]
        record = self._record(ref)
        content = record.body.get("content") if record is not None else None
        title = NOT_RECORDED
        if type(content) is dict and type(content.get("text")) is str:
            for line in content["text"].splitlines():
                if line.strip():
                    title = line.strip()[:_TITLE_CHARS]
                    break
        return {"work_revision_ref": ref.as_dict(), "work_id": ref.id, "revision": ref.version,
                "title": title}

    def _stops(self, manifest):
        """The run's public stop events (reason and time), from its own command's stream."""

        stops = []
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            rows = db.execute(
                "SELECT envelope FROM api_event_envelopes WHERE vault_id=? AND event_type='run.stopped' "
                "AND sequence>? ORDER BY sequence LIMIT ?",
                (roots.genesis.id, manifest.event_sequence, _MAX_EVENT_ROWS)).fetchall()
        for row in rows:
            envelope = EventEnvelope.from_bytes(bytes(row["envelope"]))
            if envelope.correlation_id != manifest.command_id:
                continue
            stops.append({"reason": envelope.public_metadata.get("reason_code", NOT_RECORDED),
                          "at_utc": envelope.recorded_at_utc,
                          "duration_ms": _recorded(envelope.public_metadata.get("duration_ms"))})
        return stops

    def _policy_currency(self, manifest):
        record = self._record(manifest.inputs["budget_policy_ref"])
        try:
            policy = record.body["content"]["policy"]
            return policy["provider_mode"], policy["currency"]
        except (AttributeError, KeyError, TypeError):
            return NOT_RECORDED, None

    def _reservation(self, attempt_spec):
        """The budget book's reservation of one attempt, with the cost it states."""

        try:
            row = self._book.reservation_record(attempt_spec["reservation_id"])
        except Exception:  # noqa: BLE001 - the book's detail stays private
            row = None
        if row is None:
            return NOT_RECORDED, {"state": "unknown", "basis": NOT_RECORDED}
        finalized = row["state"] == "finalized"
        reservation = {
            "state": row["state"], "usage_finality": _recorded(row["usage_finality"]),
            "reserved": {"model_calls": row["model_calls"], "tool_calls": row["tool_calls"],
                         "output_bytes": row["output_bytes"],
                         "api_microunits": _recorded(row["api_microunits"])},
            "settled": ({"model_calls": row["actual_model_calls"], "tool_calls": row["actual_tool_calls"],
                         "output_bytes": row["actual_output_bytes"],
                         "api_microunits": _recorded(row["actual_api_microunits"])}
                        if finalized else NOT_RECORDED),
            "reserved_at_utc": _utc_seconds(row["created_at"]),
            "settled_at_utc": _utc_seconds(row["settled_at"]),
        }
        if row["provider_mode"] == "subscription":
            cost = {"state": "unknown", "basis": "subscription_mode"}
        elif finalized and type(row["actual_api_microunits"]) is int:
            cost = {"state": "settled", "basis": "budget_settlement",
                    "microunits": row["actual_api_microunits"], "currency": row["currency"]}
        elif type(row["api_microunits"]) is int and row["api_microunits"] > 0:
            cost = {"state": "estimate", "basis": "reserved_ceiling",
                    "microunits": row["api_microunits"], "currency": row["currency"]}
        else:
            cost = {"state": "unknown", "basis": NOT_RECORDED}
        return reservation, cost

    def _tool_binding(self, compiled, node_id, tool_id, version):
        """The graph's tool binding this call's tool matches on its node: the designed
        definition and grant references (the compiler's projection, never a guess)."""

        for binding in compiled.tool_bindings:
            if binding.node_id == node_id and (binding.tool_id, binding.version) == (tool_id, version):
                return {"binding_id": binding.binding_id, "definition_ref": binding.definition_ref.as_dict(),
                        "grant_ref": binding.grant_ref.as_dict(),
                        "approval_gate_node_id": binding.approval_gate_node_id}
        return NOT_RECORDED

    def _tool_calls(self, compiled, node_id, attempt_id):
        calls = []
        for item in self._ledger.tool_calls_for_attempt(attempt_id):
            result_ref = None if item["result_ref"] is None else EntityRef.from_dict(item["result_ref"])
            calls.append({
                "tool_call_id": item["tool_call_id"], "tool_id": item["tool_id"], "version": item["version"],
                "effect_class": item["effect_class"], "state": item["state"],
                "declared_inputs": [dict(entry) for entry in item["artifact_inputs"]],
                "binding": self._tool_binding(compiled, node_id, item["tool_id"], item["version"]),
                "approval_ref": _recorded(item["approval_ref"]),
                "requested_at_utc": _utc_ms(item["created_at_ms"]),
                "settled_at_utc": _utc_ms(item["settled_at_ms"]),
                "result_ref": _recorded(item["result_ref"]),
                "result_artifacts": self._artifacts(result_ref),
            })
        return calls

    def _attempt(self, compiled, node_id, trace_attempt):
        attempt_id = trace_attempt.attempt_id
        row = self._ledger.get_attempt(attempt_id)
        observations = self._ledger.result_observations(attempt_id)
        accepted = next((item for item in observations if item["classification"] == "accepted"), None)
        result_ref = (None if accepted is None or accepted["result_ref"] is None
                      else EntityRef.from_dict(accepted["result_ref"]))
        reservation, cost = self._reservation(row["spec"])
        outcome = row["terminal_outcome"]
        error = None
        if outcome is not None and outcome != "succeeded":
            error = {"outcome": outcome,
                     "reason_code": NOT_RECORDED if accepted is None else accepted["reason_code"],
                     "remote_terminal_observed": row["remote_terminal_observed"]}
        journal = [{"transition": entry["transition"], "at_utc": _utc_ms(entry["at_ms"])}
                   for entry in self._ledger.attempt_journal(attempt_id)]
        return {
            "attempt_id": attempt_id, "attempt_no": trace_attempt.attempt_no,
            "phase": row["phase"], "terminal_outcome": _recorded(outcome),
            "reserved_at_utc": _utc_ms(row["created_at_ms"]),
            "sent_at_utc": _utc_ms(row["send_intent_at_ms"]),
            "transport_closed_at_utc": _utc_ms(row["local_transport_closed_at_ms"]),
            "updated_at_utc": _utc_ms(row["updated_at_ms"]),
            "ended_at_utc": (NOT_RECORDED if accepted is None else _utc_ms(accepted["observed_at_ms"])),
            "send_finality": row["send_finality"], "cancel_state": row["cancel_state"],
            "usage_finality": row["usage_finality"],
            "remote_terminal_observed": row["remote_terminal_observed"],
            "produced_visit_result": trace_attempt.produced_result,
            # this attempt's own accepted result: never the visit's later result
            "result_ref": NOT_RECORDED if result_ref is None else result_ref.as_dict(),
            "outputs": self._artifacts(result_ref),
            "error": error,
            "tool_calls": self._tool_calls(compiled, node_id, attempt_id),
            "budget_reservation": reservation,
            "cost": cost,
            "journal": journal,
        }

    def _model_calls(self, run_id, execution_id):
        """The Claude executor's call records for one visit (at most one per visit: a
        replayed visit never calls again)."""

        intent_id = str(uuid5(NAMESPACE_URL, f"deeptwin:claude-call:{run_id}:{execution_id}"))
        intent = self._record_by_id("decision_record", intent_id)
        if intent is None:
            return []
        content = intent.body["content"]
        if (type(content) is not dict or content.get("schema_version") != _INTENT_SCHEMA
                or content.get("run_id") != run_id or content.get("execution_id") != execution_id):
            return []
        output = self._record_by_id("artifact", str(uuid5(NAMESPACE_URL, f"deeptwin:claude-output:{intent_id}")))
        outcome = self._record_by_id("decision_record",
                                     str(uuid5(NAMESPACE_URL, f"deeptwin:claude-outcome:{intent_id}")))
        observed, ended, inputs, output_ref = None, NOT_RECORDED, NOT_RECORDED, None
        if output is not None and output.body["content"].get("schema_version") == _OUTPUT_SCHEMA:
            observed = output.body["content"].get("output")
            ended = output.body["created_at_utc"]
            output_ref = output.ref
            inputs = [ref for ref in output.body.get("parent_refs", [])
                      if EntityRef.from_dict(ref) != intent.ref]
        elif outcome is not None and outcome.body["content"].get("schema_version") == _OUTCOME_SCHEMA:
            observed = outcome.body["content"]
            ended = outcome.body["created_at_utc"]
        observed = observed if type(observed) is dict else {}
        usage = observed.get("usage")
        tokens = {"input": NOT_RECORDED, "output": NOT_RECORDED,
                  "cache_creation_input": NOT_RECORDED, "cache_read_input": NOT_RECORDED}
        if type(usage) is dict:
            tokens = {"input": _recorded(usage.get("input_tokens")),
                      "output": _recorded(usage.get("output_tokens")),
                      "cache_creation_input": _recorded(usage.get("cache_creation_input_tokens")),
                      "cache_read_input": _recorded(usage.get("cache_read_input_tokens"))}
        failure = observed.get("failure")
        return [{
            "call_id": intent_id,
            "recorded_by": "claude_run_executor",
            "provider": "claude",
            "model_label": _recorded(content.get("model_id")),
            "observed_model": _recorded(observed.get("observed_model")),
            "effort": _recorded(content.get("effort")),
            "max_output_tokens": _recorded(content.get("max_output_tokens")),
            "state": _recorded(observed.get("state")),
            "stop_reason": _recorded(observed.get("stop_reason")),
            "error": (None if failure is None else
                      {"category": failure.get("category"), "detail_code": failure.get("detail_code")}
                      if type(failure) is dict else NOT_RECORDED),
            "tokens": tokens,
            "started_at_utc": intent.body["created_at_utc"],
            "ended_at_utc": ended,
            "inputs": inputs,
            "output_ref": NOT_RECORDED if output_ref is None else output_ref.as_dict(),
            "cost": {"state": "unknown", "basis": NOT_RECORDED},
            "reasoning": "not_stored",
            "provider_message_id": _recorded(observed.get("provider_message_id")),
            "request_id": _recorded(observed.get("request_id")),
        }]

    def _approval_records(self, run_id, outcome):
        gates = []
        for node_id, refs in outcome["approvals"]:
            for raw in refs:
                ref = EntityRef.from_dict(raw)
                found = self._approvals.resolve(ref)
                record = self._record(ref)
                gates.append({"node_id": node_id,
                              "approval_scope": NOT_RECORDED if found is None else found.approval_scope,
                              "decision": NOT_RECORDED if found is None else found.decision,
                              "decided_at_utc": NOT_RECORDED if record is None else record.body["created_at_utc"],
                              "approval_ref": ref.as_dict(), "state": "consumed"})
        for node_id, scope in outcome["awaiting_human"]:
            gates.append({"node_id": node_id, "approval_scope": scope, "decision": NOT_RECORDED,
                          "decided_at_utc": NOT_RECORDED, "approval_ref": NOT_RECORDED, "state": "pending"})
        for node_id, scope in outcome["rejected_human"]:
            found = self._approvals.lookup(run_id, node_id, scope)
            record = None if found is None else self._record(found.approval_ref)
            gates.append({"node_id": node_id, "approval_scope": scope, "decision": "rejected",
                          "decided_at_utc": NOT_RECORDED if record is None else record.body["created_at_utc"],
                          "approval_ref": NOT_RECORDED if found is None else found.approval_ref.as_dict(),
                          "state": "rejected"})
        executions = []
        for ask in self._approvals.execution_requests(run_id):
            decided = NOT_RECORDED
            if ask["approval_ref"] is not None:
                record = self._record(EntityRef.from_dict(ask["approval_ref"]))
                decided = NOT_RECORDED if record is None else record.body["created_at_utc"]
            executions.append({"node_id": ask["node_id"], "approval_scope": ask["approval_scope"],
                               "execution_id": ask["execution_id"],
                               "execution_node_id": ask["execution_node_id"], "attempt_no": ask["attempt_no"],
                               "state": ask["state"], "decided_at_utc": decided,
                               "expires_at_utc": _utc_ms(ask["expires_at_ms"]),
                               "inputs_digest": _recorded(ask["inputs_digest"]),
                               "approval_ref": _recorded(ask["approval_ref"])})
        return {"gates": gates, "executions": executions}

    @staticmethod
    def _exit_nodes(graph):
        """The graph's declared final outputs (its completion criteria), or, when it
        declares none, its sinks (no outgoing triggering edge)."""

        criteria = [item["node_id"] for item in graph["completion_criteria"]]
        if criteria:
            return list(dict.fromkeys(criteria)), "completion_criteria"
        sources = {edge["source_node_id"] for edge in graph["edges"] if edge["kind"] != "observation"}
        return [node["node_id"] for node in graph["nodes"] if node["node_id"] not in sources], "graph_sinks"

    # ------------------------------------------------------------------ read

    @_closed
    def read(self, request, run_id, *, base_path, feedback=True) -> dict:
        """The run's trace. With `feedback` (the route), the owner's process feedback is
        attached: the run's own at `feedback.run`, each target's latest revision in
        `feedback.steps`, and on each attempt (or a visit without attempts) its current
        feedback, or null when it has none or it was cleared (`run_feedback.py`)."""

        self._check(request)
        try:
            run_id = uuid_string(run_id)
        except (DomainContractError, TypeError, ValueError):
            raise RunTraceReadError("invalid_input") from None
        receipt, manifest, compiled = self._runs.observe_parts(run_id, base_path=base_path)
        try:
            trace = read_run_trace(self._ledger, run_id, compiled)
        except RunTraceError:
            raise RunTraceReadError("unavailable") from None
        outcome = receipt["outcome"]
        graph = compiled.execution_graph.as_dict()
        design = {node["node_id"]: node for node in graph["nodes"]}
        by_execution = {item.execution_id: item for item in trace.executions}
        visits_by_node = {}
        timeline = []
        gaps = set()
        totals = {"model_calls": 0, "tool_calls": 0, "attempts": 0, "retries": 0,
                  "input_tokens": 0, "output_tokens": 0, "tokens_complete": True,
                  "cost_microunits": 0, "cost_currency": None, "cost_states": set()}
        mode, _currency = self._policy_currency(manifest)

        def producing_no(execution):
            for attempt in execution.attempts:
                if attempt.attempt_id == execution.producing_attempt_id:
                    return attempt.attempt_no
            return None

        visits_seen = {}
        for execution in trace.executions:
            visit_no = visits_seen.get(execution.node_id, 0) + 1
            visits_seen[execution.node_id] = visit_no
            attempts = [self._attempt(compiled, execution.node_id, item) for item in execution.attempts]
            model_calls = self._model_calls(run_id, execution.execution_id)
            if not attempts:
                gaps.add("handler_attempts")
            inputs = []
            for parent_id in execution.parents:
                parent = by_execution.get(parent_id)
                if parent is None:
                    continue
                inputs.append({
                    "from_node_id": parent.node_id, "from_execution_id": parent.execution_id,
                    "from_attempt_no": _recorded(producing_no(parent)),
                    "result_ref": NOT_RECORDED if parent.result_ref is None else parent.result_ref.as_dict(),
                    "artifacts": self._artifacts(parent.result_ref),
                })
            status = "completed" if execution.result_ref is not None else "no_result"
            if execution.result_ref is None and attempts and attempts[-1]["terminal_outcome"] not in (
                    NOT_RECORDED, "succeeded"):
                status = "failed"
            if execution.result_ref is None and not attempts:
                gaps.add("handler_error")
            visit = {
                "execution_id": execution.execution_id, "visit_no": visit_no,
                "loop_index": execution.loop_index, "status": status,
                "recorded_at_utc": _utc_ms(execution.created_at_ms),
                "result_ref": NOT_RECORDED if execution.result_ref is None else execution.result_ref.as_dict(),
                "outputs": self._artifacts(execution.result_ref),
                "produced_by_attempt_no": _recorded(producing_no(execution)),
                "inputs": inputs, "attempts": attempts, "model_calls": model_calls,
            }
            visits_by_node.setdefault(execution.node_id, []).append(visit)
            timeline.append({"at_utc": visit["recorded_at_utc"], "kind": "visit", "node_id": execution.node_id,
                             "execution_id": execution.execution_id, "visit_no": visit_no, "status": status})
            for attempt in attempts:
                totals["attempts"] += 1
                if attempt["attempt_no"] > 1:
                    totals["retries"] += 1
                timeline.append({"at_utc": attempt["reserved_at_utc"], "kind": "attempt",
                                 "node_id": execution.node_id, "execution_id": execution.execution_id,
                                 "visit_no": visit_no, "attempt_no": attempt["attempt_no"],
                                 "status": attempt["terminal_outcome"], "ended_at_utc": attempt["ended_at_utc"]})
                totals["tool_calls"] += len(attempt["tool_calls"])
                reserved = attempt["budget_reservation"]
                if (reserved != NOT_RECORDED and reserved["reserved"]["model_calls"] > 0
                        and attempt["sent_at_utc"] != NOT_RECORDED):
                    totals["model_calls"] += 1  # a sent model attempt is one model call
                    totals["tokens_complete"] = False  # a ledger attempt records no tokens
                    gaps.add("attempt_tokens")
                cost = attempt["cost"]
                totals["cost_states"].add(cost["state"])
                if cost["state"] in {"estimate", "settled"}:
                    totals["cost_microunits"] += cost["microunits"]
                    totals["cost_currency"] = cost["currency"]
            for call in model_calls:
                totals["model_calls"] += 1
                gaps.update({"model_cost", "reasoning"})
                totals["cost_states"].add("unknown")
                for name, key in (("input", "input_tokens"), ("output", "output_tokens")):
                    if type(call["tokens"][name]) is int:
                        totals[key] += call["tokens"][name]
                    else:
                        totals["tokens_complete"] = False
                timeline.append({"at_utc": call["started_at_utc"], "kind": "model_call",
                                 "node_id": execution.node_id, "execution_id": execution.execution_id,
                                 "visit_no": visit_no, "status": call["state"], "ended_at_utc": call["ended_at_utc"]})

        # the hand-offs the run recorded: each visit's recorded parents and their exact results
        handoffs = []
        edges = graph["edges"]
        for node_id, visits in visits_by_node.items():
            for visit in visits:
                for source in visit["inputs"]:
                    designed = [edge["edge_id"] for edge in edges
                                if edge["source_node_id"] == source["from_node_id"]
                                and edge["target_node_id"] == node_id and edge["kind"] != "observation"]
                    handoffs.append({
                        "from_node_id": source["from_node_id"], "from_execution_id": source["from_execution_id"],
                        "from_attempt_no": source["from_attempt_no"],
                        "to_node_id": node_id, "to_execution_id": visit["execution_id"],
                        "to_attempt_nos": [item["attempt_no"] for item in visit["attempts"]],
                        "artifacts": source["artifacts"], "result_ref": source["result_ref"],
                        "designed_edge_ids": designed, "receipt": NOT_RECORDED,
                    })
        if handoffs:
            gaps.add("handoff_receipt")

        states = {}
        for node_id in outcome["pending_node_ids"]:
            states[node_id] = "pending"
        for node_id in outcome["completed_node_ids"]:
            states[node_id] = "completed"
        for node_id in outcome.get("failed_node_ids", ()):
            states[node_id] = "failed"
        for node_id, _scope in outcome["awaiting_human"]:
            states[node_id] = "awaiting_approval"
        for entry in outcome["awaiting_execution"]:
            states[entry[3]] = "awaiting_approval"
        for node_id, _scope in outcome["rejected_human"]:
            states[node_id] = "rejected"
        for entry in outcome["rejected_execution"]:
            states[entry[3]] = "rejected"
        nodes = []
        for node in graph["nodes"]:
            node_id = node["node_id"]
            visits = visits_by_node.get(node_id, [])
            state = states.get(node_id, "not_visited")
            if state in {"pending", "not_visited"} and visits and visits[-1]["status"] == "failed":
                state = "failed"
            nodes.append({"node_id": node_id, "kind": node["kind"], "responsibility": node["responsibility"],
                          "state": state, "visits": visits})

        exit_ids, exit_basis = self._exit_nodes(graph)
        final_results = []
        for node_id in exit_ids:
            visits = visits_by_node.get(node_id, [])
            if not visits or visits[-1]["result_ref"] == NOT_RECORDED:
                continue
            last = visits[-1]
            for artifact in last["outputs"]:
                final_results.append({**artifact, "node_id": node_id, "execution_id": last["execution_id"],
                                      "visit_no": last["visit_no"],
                                      "produced_by_attempt_no": last["produced_by_attempt_no"]})
        stopped_at = [{"node_id": node["node_id"], "state": node["state"]} for node in nodes
                      if node["state"] in {"pending", "awaiting_approval", "failed", "rejected"}]

        stops = self._stops(manifest)
        ended = next((stop["at_utc"] for stop in reversed(stops)
                      if stop["reason"] in {"completed", "cancelled"}), None)
        cost_states = totals.pop("cost_states")
        if cost_states and cost_states <= {"settled"}:
            cost = {"state": "settled", "microunits": totals["cost_microunits"], "currency": totals["cost_currency"]}
        elif "estimate" in cost_states or "settled" in cost_states:
            cost = {"state": "estimate" if "unknown" not in cost_states else "partial_estimate",
                    "microunits": totals["cost_microunits"], "currency": totals["cost_currency"]}
        else:
            cost = {"state": "unknown", "microunits": NOT_RECORDED, "currency": None}
        totals.pop("cost_microunits")
        totals.pop("cost_currency")
        timeline.sort(key=lambda item: (item["at_utc"] if item["at_utc"] != NOT_RECORDED else "~"))
        value = {
            "schema_version": TRACE_SCHEMA,
            "run_id": run_id,
            "phase": receipt["phase"],
            "graph_ref": receipt["graph_ref"],
            "graph_digest": receipt["graph_digest"],
            "work": self._work(manifest),
            "budget_mode": mode,
            "started_at_utc": _utc_ms(manifest.started_at_ms),
            "ended_at_utc": _recorded(ended),
            "stops": stops,
            "totals": {**totals, "cost": cost},
            "exit": {"node_ids": exit_ids, "basis": exit_basis},
            "final_results": final_results,
            "stopped_at": stopped_at,
            "nodes": nodes,
            "handoffs": handoffs,
            "approvals": self._approval_records(run_id, outcome),
            "timeline": timeline,
            "gaps": [{"category": name, "reason": GAP_REASONS[name]} for name in sorted(gaps)],
            "links": {"self": f"{base_path.rstrip('/')}/api/v1/runs/{run_id}/trace",
                      "run": f"{base_path.rstrip('/')}/api/v1/runs/{run_id}",
                      "events": f"{base_path.rstrip('/')}/api/v1/events?run_id={run_id}"},
        }
        if feedback:
            self._attach_feedback(value, run_id, base_path)
        return value

    def _attach_feedback(self, value, run_id, base_path):
        """The owner's process feedback beside the facts it is about. It is the owner's own
        observation (a mark and a memo), never a recorded fact of the run and never an
        alternative; a cleared target keeps its latest revision in `steps` (state `cleared`)
        and shows null in place."""

        from .run_feedback import current_feedback

        current = current_feedback(self._domain, run_id)
        active = {}
        for item in current["steps"]:
            if item["state"] == "set":
                target = item["target"]
                active[(target["node_id"], target["visit_no"], target["attempt_no"])] = item
        for node in value["nodes"]:
            for visit in node["visits"]:
                visit["feedback"] = active.get((node["node_id"], visit["visit_no"], None))
                for attempt in visit["attempts"]:
                    attempt["feedback"] = active.get((node["node_id"], visit["visit_no"], attempt["attempt_no"]))
        value["feedback"] = current
        value["links"]["feedback"] = f"{base_path.rstrip('/')}/api/v1/runs/{run_id}/feedback"
