"""The code-owned run executor for the direct-adapter Claude profile.

`PersistentRuns` injects this executor. It compiles a stored graph against a
compilation authority built from this vault's own records, never from the
graph's claims:
- the owner-authored `model_choice` records sealed by `ClaudeConnection`
- the budget policies and observation contracts the vault holds
- no tool definitions and no grants: a graph that asks for tools or grants does
  not compile in this profile

The scheduler's handlers are:
- **deterministic** entry node: the run's work revision text becomes the source
  artifact.
- **deterministic, human_gate and join** nodes with inputs: forward their
  producer's artifact. A human gate still runs only on the owner's recorded
  approval, which the scheduler enforces.
- **agent**: one Claude Messages call through the official adapter, with the
  model the graph's binding names (an owner-chosen, catalog-listed model) and the
  upstream artifacts' text as input. The text output is sealed as the node's
  artifact, with the provider message id, model and usage beside it.
- **router and bounded_loop**: no decision logic in this profile; they fail the
  node rather than guess.

**Budget and billing safety:**
- Every model call first seals an intent record at an identity derived from the
  run and the visit. A resumed or replayed visit that finds its intent without
  an output does not call again: its outcome is unknown and the node fails, so
  nothing is billed twice.
- Calls per run are bounded by the run's `BudgetPolicy.max_model_calls` and by
  this process's `LiveLimits.max_model_calls`.
- Output tokens per call are bounded by `LiveLimits.max_output_tokens`, by the
  policy's output bytes and by the model's own limit.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from ..adapters.claude_api import (
    MessageTurn,
    ProviderStarted,
    ProviderTerminal,
    TextDelta,
    ToolRequested,
    UsageObserved,
)
from ..domain.refs import EntityRef
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, _writer
from ..runtime import scheduler as sch
from ..runtime.graph import CompilationAuthority, compile_graph
from .claude_connection import CHOICE_SCHEMA, ClaudeConnection
from .run_approvals import _stored_owner_actor_ref

__all__ = ["INTENT_SCHEMA", "OUTPUT_SCHEMA", "ClaudeRunExecutor", "LiveLimits"]

OUTPUT_SCHEMA = "claude-model-output-v1"
SOURCE_SCHEMA = "run-source-text-v1"
INTENT_SCHEMA = "claude-call-intent-v1"
OUTCOME_SCHEMA = "claude-call-outcome-v1"
APPROVAL_SCOPES = ("release-output",)
MAX_INPUT_CHARS = 60_000
MAX_AUTHORITY = 256


@dataclass(frozen=True, slots=True)
class LiveLimits:
    max_model_calls: int = 10
    max_output_tokens: int = 512

    def __post_init__(self):
        if type(self.max_model_calls) is not int or not 0 <= self.max_model_calls <= 10_000:
            raise ValueError("max_model_calls is out of bounds")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 32_000:
            raise ValueError("max_output_tokens is out of bounds")


class _NodeRefused(RuntimeError):
    """A handler refusal; the scheduler marks the node failed and keeps the reason private."""


def _stamp() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


class ClaudeRunExecutor:
    """Built by the host before the app exists; the `claude-connection-v1`
    contribution binds it once to the vault and the owner's connection."""

    def __init__(self, *, limits: LiveLimits | None = None, transport=None):
        # `transport` is the adapter's HTTP transport seam: None is the real network,
        # a test injects httpx2.MockTransport; it never carries a credential
        self.transport = transport
        self._domain = None
        self._connection = None
        self._limits = limits or LiveLimits()
        self._calls_lock = threading.Lock()
        self._process_calls = 0

    def bind(self, domain_store, connection):
        if type(domain_store) is not DomainStore or type(connection) is not ClaudeConnection:
            raise TypeError("Exact DomainStore and ClaudeConnection required")
        if self._domain is not None and (self._domain is not domain_store or self._connection is not connection):
            raise RuntimeError("The executor is already bound to another vault")
        self._domain, self._connection = domain_store, connection

    def _bound(self):
        if self._domain is None:
            raise RuntimeError("The executor is not bound to a vault")

    # --- compilation ------------------------------------------------------------------

    def _records(self, kind, *, owner_only=False, schema=None):
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            owner = _stored_owner_actor_ref(db)
            rows = db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind=? "
                "ORDER BY id, version LIMIT ?", (roots.genesis.id, kind, MAX_AUTHORITY + 1)).fetchall()
            if len(rows) > MAX_AUTHORITY:
                raise _NodeRefused("authority_bounds")
            found = []
            for row in rows:
                ref = EntityRef(kind, row["id"], row["version"], row["sha256"])
                record = self._domain._load(db, ref, roots)[0]
                if owner_only and record.body["actor_ref"] != owner:
                    continue
                content = record.body["content"]
                if schema is not None and (type(content) is not dict or content.get("schema_version") != schema):
                    continue
                found.append(record)
            return found

    def _authority(self) -> CompilationAuthority:
        choices = [(record.ref, tuple(record.body["content"]["capabilities"]))
                   for record in self._records("model_choice", owner_only=True, schema=CHOICE_SCHEMA)]
        return CompilationAuthority.from_trusted(
            model_choices=choices, tool_definitions=[], grant_refs=[],
            approval_scopes=list(APPROVAL_SCOPES),
            observation_contract_refs=[record.ref for record in self._records("observation_contract")],
            budget_policy_refs=[record.ref for record in self._records("budget_policy")],
            artifact_schema_refs=[])

    def compile(self, graph):
        self._bound()
        return compile_graph(graph, self._authority())

    # --- scheduling -------------------------------------------------------------------

    def scheduler(self, compiled, *, ledger, run_id, approvals, retry=False):
        del retry  # this executor binds no attempt dispatcher; there is nothing to retry
        self._bound()
        graph = compiled.execution_graph.as_dict()
        nodes = {node["node_id"]: node for node in graph["nodes"]}
        bindings = {item["binding_id"]: item for item in graph["model_bindings"]}
        predecessors = dict(compiled.activation_predecessors)
        run = ledger.get_run(run_id)
        spec = run["spec"]

        def upstream(context, view):
            refs = []
            sources = context.inputs or predecessors.get(context.node_id, ())
            for source in sources:
                count = view["counters"].get(source, 0)
                if count <= 0:
                    continue
                ref = view["results"].get(sch.execution_identity(run_id, source, count - 1))
                if ref is not None:
                    refs.append(ref)
            return refs

        def forward(context, view):
            refs = upstream(context, view)
            if refs:
                return refs[0]
            if nodes[context.node_id]["kind"] != "deterministic":
                raise _NodeRefused("no_input")
            return self._source_artifact(spec, run_id, context)

        def agent(context, view):
            return self._model_call(context, view, nodes[context.node_id], bindings, spec, run_id,
                                    upstream(context, view))

        def undecided(context, view):
            raise _NodeRefused("unsupported_node_kind")

        handlers = {"core.deterministic": forward, "core.human_gate": forward, "core.join": forward,
                    "core.agent": agent, "core.router": undecided, "core.bounded_loop": undecided}
        needed = {key for _, key in compiled.handler_keys}
        gated = any(node.kind == "human_gate" for node in compiled.nodes)
        return sch.build_scheduler(compiled, ledger=ledger, run_id=run_id,
                                   handlers={key: handlers[key] for key in needed},
                                   approvals=approvals if gated else None)

    # --- artifacts --------------------------------------------------------------------

    def _seal_artifact(self, *, record_id, text, role, content, parents=()):
        blob = self._domain.put_blob(text.encode("utf-8"), purpose="operational")
        with _writer(), self._domain._connection(write=True) as db:
            roots = self._domain._read_roots(db)
            existing = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind='artifact' "
                                  "AND id=?", (roots.genesis.id, record_id)).fetchone()
            if existing is not None:
                return EntityRef("artifact", record_id, existing["version"], existing["sha256"])
            record = ImmutableRecord.create(
                kind="artifact", id=record_id, version=1, created_at_utc=_stamp(), actor_ref=roots.actor,
                parent_refs=tuple(parents), purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={**content, "artifacts": [{"ordinal": 0, "role": role, "media_type": "text/markdown",
                                                   "blob": blob.as_dict()}]})
            self._domain._put_in_transaction(db, record)
            return record.ref

    def _text(self, ref) -> str:
        record = self._domain.get(ref)
        content = record.body["content"]
        items = content.get("artifacts") if type(content) is dict else None
        if not items:
            raise _NodeRefused("input_without_text")
        from ..domain.store import BlobRef

        data = self._domain.read_blob(BlobRef(**items[0]["blob"]), purpose="operational")
        return data.decode("utf-8")

    def _source_artifact(self, spec, run_id, context):
        revision = self._domain.get(EntityRef.from_dict(spec["work_revision_ref"]))
        text = revision.body["content"].get("text")
        if type(text) is not str or not text.strip():
            raise _NodeRefused("empty_work")
        return self._seal_artifact(
            record_id=str(uuid5(NAMESPACE_URL, f"deeptwin:run-source:{run_id}:{context.execution_id}")),
            text=text, role="source", parents=(revision.ref,),
            content={"schema_version": SOURCE_SCHEMA, "run_id": run_id, "node_id": context.node_id})

    # --- the model call ---------------------------------------------------------------

    def _choice(self, node, bindings):
        binding_id = node["config"]["model_binding_id"]
        ref = EntityRef.from_dict(bindings[binding_id]["model_choice_ref"])
        record = self._domain.get(ref)
        content = record.body["content"]
        with self._domain._connection() as db:
            owner = _stored_owner_actor_ref(db)
        if (content.get("schema_version") != CHOICE_SCHEMA or content.get("provider") != "claude"
                or record.body["actor_ref"] != owner):
            raise _NodeRefused("model_choice_not_owner_chosen")
        return content

    def _calls_in_run(self, db, roots, run_id) -> int:
        return db.execute("SELECT count(*) FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                          "AND instr(body, ?) > 0 AND instr(body, ?) > 0",
                          (roots.genesis.id, INTENT_SCHEMA.encode(), run_id.encode())).fetchone()[0]

    def _model_call(self, context, view, node, bindings, spec, run_id, inputs):
        from .runs import PersistentRuns

        choice = self._choice(node, bindings)
        policy = PersistentRuns._policy(self._domain.get(EntityRef.from_dict(spec["budget_policy_ref"])))
        texts = [self._text(ref) for ref in inputs] if inputs else []
        prompt = "\n\n".join(texts)[:MAX_INPUT_CHARS]
        if not prompt.strip():
            raise _NodeRefused("empty_input")
        adapter, binding, snapshot = self._connection.current()  # provider_unavailable without a key
        listed = {model.id: model for model in snapshot.models}
        model = listed.get(choice["model_id"])
        if model is None or model.max_tokens is None:
            raise _NodeRefused("model_not_in_current_catalog")
        max_tokens = min(self._limits.max_output_tokens, max(1, policy.max_output_bytes // 4), model.max_tokens)
        intent_id = str(uuid5(NAMESPACE_URL, f"deeptwin:claude-call:{run_id}:{context.execution_id}"))
        with _writer(), self._domain._connection(write=True) as db:
            roots = self._domain._read_roots(db)
            if db.execute("SELECT 1 FROM domain_records WHERE vault_id=? AND kind='decision_record' AND id=?",
                          (roots.genesis.id, intent_id)).fetchone() is not None:
                raise _NodeRefused("call_outcome_unknown")  # a sent call is never repeated
            if self._calls_in_run(db, roots, run_id) >= policy.max_model_calls:
                raise _NodeRefused("run_model_budget_exhausted")
            with self._calls_lock:
                if self._process_calls >= self._limits.max_model_calls:
                    raise _NodeRefused("process_model_budget_exhausted")
                self._process_calls += 1
            intent = ImmutableRecord.create(
                kind="decision_record", id=intent_id, version=1, created_at_utc=_stamp(), actor_ref=roots.actor,
                parent_refs=(), purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={"schema_version": INTENT_SCHEMA, "run_id": run_id, "node_id": context.node_id,
                         "execution_id": context.execution_id, "model_id": choice["model_id"],
                         "max_output_tokens": max_tokens})
            self._domain._put_in_transaction(db, intent)
        turn = MessageTurn(
            call_id=context.execution_id, agent_id=context.node_id,
            selection=self._connection.model_selection(choice["model_id"]),
            system=("You perform one role in a work graph. Your role: " + node["responsibility"]
                    + "\nProduce only this role's output for the material given."),
            messages=({"role": "user", "content": prompt},), max_tokens=max_tokens)
        started, usage, terminal, chunks = None, None, None, []
        for event in adapter.stream(turn, snapshot, binding, explicit_action=True):
            if isinstance(event, ProviderStarted):
                started = event
            elif isinstance(event, TextDelta):
                chunks.append(event.text)
            elif isinstance(event, UsageObserved):
                usage = event
            elif isinstance(event, ProviderTerminal):
                terminal = event
            elif isinstance(event, ToolRequested):
                pass  # no tools are offered; the terminal reports tool_required
        observed = {
            "provider_message_id": None if started is None else started.provider_message_id,
            "observed_model": None if started is None else started.observed_model,
            "usage": None if usage is None else {
                "input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens},
            "state": None if terminal is None else terminal.state,
            "stop_reason": None if terminal is None else terminal.stop_reason,
            "failure": None if terminal is None or terminal.failure is None else {
                "category": terminal.failure.category, "detail_code": terminal.failure.detail_code,
                "dispatch_effect": terminal.failure.dispatch_effect},
        }
        if terminal is None or terminal.state != "completed":
            self._seal_outcome(intent.ref, observed)
            raise _NodeRefused("model_call_not_completed")
        return self._seal_artifact(
            record_id=str(uuid5(NAMESPACE_URL, f"deeptwin:claude-output:{intent_id}")),
            text="".join(chunks), role="draft", parents=(intent.ref, *inputs),
            content={"schema_version": OUTPUT_SCHEMA, "run_id": run_id, "node_id": context.node_id,
                     "model_id": choice["model_id"], "intent_ref": intent.ref.as_dict(),
                     "output": json.loads(json.dumps(observed))})

    def _seal_outcome(self, intent_ref, observed):
        with _writer(), self._domain._connection(write=True) as db:
            roots = self._domain._read_roots(db)
            record = ImmutableRecord.create(
                kind="decision_record", id=str(uuid5(NAMESPACE_URL, f"deeptwin:claude-outcome:{intent_ref.id}")),
                version=1, created_at_utc=_stamp(), actor_ref=roots.actor, parent_refs=(intent_ref,),
                purpose="operational", access_policy_ref=roots.access_policy,
                retention_policy_ref=roots.retention_policy,
                content={"schema_version": OUTCOME_SCHEMA, "intent_ref": intent_ref.as_dict(), **observed})
            self._domain._put_in_transaction(db, record)
