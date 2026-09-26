"""Deterministic tool bindings (owner decision 2026-09-26, specs/001-autonomous-release/
decisions.md; runtime.md §2 dated note).

A deterministic (model-free) node may name approved tool bindings — e.g. a byte-exact
store step. The compiler validates them against the compilation authority exactly as
for an agent node (known binding, authoritative definition, grant within the node's
grant set, an external-family tool's approval scope with an exact gate path), and at
runtime the node reaches its tool only through the same attempt dispatcher and compiled
tool transport as an agent: the grant, the execution-bound (v2) approval per attempt,
the budget claim and the ToolCall record are the ledger's, and a paired re-evaluation
isolates the recorded effect the same way.

The tool is the TEST-ACTOR tool `test_actor_notify` (app/tests/support/tool_gate.py):
it claims `external_irreversible` but performs no external effect.
"""

from contextlib import contextmanager
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.domain.graph_schema import GraphContractError
from app.runtime import extension_attempt_transport as xt
from app.runtime import node_attempts as na
from app.runtime import scheduler as sch
from app.runtime.graph import (
    compile_graph,
    resolve_compiled_tool_binding,
    structural_diversity_projection,
)
from app.services import run_approvals as ra
from app.services.paired_execution import PairedSide, execute_paired_round
from app.services.tool_effect_isolation import (
    ToolEffectSource,
    recorded_effect_bindings,
)
from app.tests.support.tool_gate import (
    GATE,
    SCOPE,
    STORE,
    STORE_HANDLER,
    TEST_ACTOR_TOOL,
    compiled_deterministic_tool_gated,
    deterministic_tool_gated_graph,
    register_test_actor_tool,
    tool_authority,
)
from app.tests.test_extension_attempt_transport import (  # noqa: F401 - fixture re-exports
    INSTANCE,
    SLOT,
    app_subject,
    channel,
    slot,
    staged,
    text_input,
    worker_tree,
)
from app.tests.test_graph_contract import (
    authority_with,
    compile_value,
    graph_value,
    parse,
    ref,
    trusted_tool,
)

EFFECT = "external_irreversible"


# ---------------------------------------------------------------- schema and compiler

def store_graph():
    """graph_value() whose deterministic `publish` also binds the read tool `source-read`."""
    raw = graph_value()
    publish = raw["nodes"][3]
    publish["config"] = {"handler_id": STORE_HANDLER, "tool_binding_ids": ["source-read"]}
    publish["grant_refs"] = [ref("grant", 6)]
    return raw


def test_a_deterministic_node_may_bind_an_authoritative_tool_like_an_agent():
    compiled = compile_value(store_graph())
    assert ("publish", "source-read", "text_profile", "1.0.0", "read", None) in compiled.tool_effects
    binding = resolve_compiled_tool_binding(compiled, "publish", "source-read")
    assert binding.node_id == "publish" and binding.approval_gate_node_id is None
    config = compiled.execution_graph.as_dict()["nodes"]
    publish = next(item for item in config if item["node_id"] == "publish")["config"]
    assert publish == {"handler_id": STORE_HANDLER, "tool_binding_ids": ["source-read"]}
    # the tool is used only by the deterministic node: it is still a used binding
    only_store = store_graph()
    only_store["nodes"][1]["config"]["tool_binding_ids"] = []
    assert compile_value(only_store).tool_effects == (
        ("publish", "source-read", "text_profile", "1.0.0", "read", None),)


def test_a_tool_free_deterministic_config_keeps_its_exact_canonical_bytes():
    # an explicit empty list is the same node as the earlier one-field config
    plain = graph_value()
    explicit = graph_value()
    explicit["nodes"][0]["config"] = {"handler_id": "artifact-normalizer-v1", "tool_binding_ids": []}
    assert parse(explicit).as_dict() == parse(plain).as_dict()
    assert parse(plain).as_dict()["nodes"][0]["config"] == {"handler_id": "artifact-normalizer-v1"}
    assert compile_value(explicit).graph_digest == compile_value(plain).graph_digest


@pytest.mark.parametrize("case", [
    "unknown_binding", "grant_outside_node", "extra_key", "not_a_list", "duplicate", "bad_id",
])
def test_the_compiler_refuses_a_deterministic_tool_binding_an_agent_could_not_hold(case):
    raw = store_graph()
    config = raw["nodes"][3]["config"]
    if case == "unknown_binding":
        config["tool_binding_ids"] = ["shell"]
    elif case == "grant_outside_node":
        raw["nodes"][3]["grant_refs"] = []
    elif case == "extra_key":
        config["code"] = "eval(x)"
    elif case == "not_a_list":
        config["tool_binding_ids"] = "source-read"
    elif case == "duplicate":
        config["tool_binding_ids"] = ["source-read", "source-read"]
    else:
        config["tool_binding_ids"] = ["../../store"]
    with pytest.raises(GraphContractError):
        compile_value(raw)


def test_the_authority_decides_a_deterministic_tool_binding_exactly_as_for_an_agent():
    raw = store_graph()
    raw["nodes"][1]["config"]["tool_binding_ids"] = []
    # a tool definition the authority does not hold
    with pytest.raises(GraphContractError, match="non-authoritative tool"):
        compile_graph(parse(raw), authority_with([trusted_tool(number=40)]))
    # a capability the authoritative tool lacks
    greedy = deepcopy(raw)
    greedy["tool_bindings"][0]["capabilities"] = ["write-anything"]
    with pytest.raises(GraphContractError, match="capability"):
        compile_value(greedy)
    # an external-family tool: the deterministic node must require its approval scope
    with pytest.raises(GraphContractError, match="approval scope"):
        compile_graph(parse(raw), tool_authority())
    gated = compiled_deterministic_tool_gated()
    assert gated.tool_effects == (
        (STORE, "source-read", TEST_ACTOR_TOOL["tool_id"], TEST_ACTOR_TOOL["version"], EFFECT, GATE),)
    assert resolve_compiled_tool_binding(gated, STORE, "source-read").approval_gate_node_id == GATE
    # without the exact gate path the scope cannot be supplied
    dangling = deterministic_tool_gated_graph()
    dangling["edges"] = [edge for edge in dangling["edges"] if edge["edge_id"] != "e6"]
    with pytest.raises(GraphContractError, match="approval"):
        compile_graph(parse(dangling), tool_authority())


def test_structural_projection_carries_the_tool_permission_not_the_binding_name():
    raw = store_graph()
    renamed = store_graph()
    renamed["tool_bindings"][0]["binding_id"] = "store-tool"
    renamed["nodes"][1]["config"]["tool_binding_ids"] = ["store-tool"]
    renamed["nodes"][3]["config"]["tool_binding_ids"] = ["store-tool"]
    assert structural_diversity_projection(parse(raw)) == structural_diversity_projection(parse(renamed))
    # binding the tool on the deterministic node is a real permission-axis difference
    plain = structural_diversity_projection(parse(graph_value()))
    bound = structural_diversity_projection(parse(raw))
    assert plain["permission_and_approval_placement"] != bound["permission_and_approval_placement"]


# ---------------------------------------------------------------- runtime dispatch

@pytest.fixture
def actor_tool(monkeypatch):
    return register_test_actor_tool(monkeypatch)


@pytest.fixture
def worker(actor_tool, staged):  # noqa: F811 - the imported fixture
    return SimpleNamespace(tool=actor_tool, box=staged[3])


@contextmanager
def gated(tmp_path):
    from app.tests.test_extension_candidates_persistent import owner

    with owner(tmp_path) as (app, _client, request, _profile, _arguments):
        approvals = ra.PersistentRunApprovals(app.state.domain_store, app.state.owner_authority)
        subject, run = app_subject(app)
        subject.approvals, subject.request, subject.run, subject.app = approvals, request, run, app
        subject.compiled = compiled_deterministic_tool_gated()
        yield subject


def transport_of(subject, payload=b"approved bytes"):
    return xt.ExtensionAttemptTransport.build(
        domain_store=subject.domain, instance_id=INSTANCE, slot_number=SLOT, operation="invoke_tool",
        artifact_inputs=(text_input(payload),), compiled=subject.compiled, node_id=STORE,
        binding_id="source-read", ledger=subject.ledger, approvals=subject.approvals)


def binding_of(subject, transport):
    return na.AttemptBinding.create(
        envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
        budget_policy_ref=subject.refs.budget, deadline_at_ms=subject.deadline,
        lease_duration_ms=60_000, model_calls=0, tool_calls=1, node_visits=1, loop_rounds=0,
        output_bytes=transport.output_bytes_bound, candidates=0, api_microunits=None,
        principal=subject.principal, grant=subject.grant)


def dispatcher_of(subject, transport=None):
    transport = transport or transport_of(subject)
    return na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={STORE: binding_of(subject, transport)}, transport=transport)


def registry(subject, calls):
    def produce(context, view):
        calls.append((context.node_id, context.attempt is not None))
        return subject.refs.result

    def store(context, view):
        # the deterministic store handler: its one route to the tool is the visit's attempt
        calls.append((context.node_id, context.attempt is not None))
        if context.attempt is None:
            return subject.refs.result
        return context.attempt.dispatch()

    return {"core.deterministic": store, "core.agent": produce, "core.human_gate": produce,
            "core.join": produce, "core.router": produce}


def scheduler_of(subject, calls, *, attempts="default"):
    return sch.build_scheduler(
        subject.compiled, ledger=subject.ledger, run_id=subject.run.run_id,
        handlers=registry(subject, calls), approvals=subject.approvals,
        attempts=dispatcher_of(subject) if attempts == "default" else attempts)


def decide(subject, decision="approved"):
    [entry] = [item for item in subject.approvals.execution_requests(subject.run.run_id)
               if item["state"] == "pending"]
    body = {"schema_version": "run-approval-command-v2", "command_id": str(uuid4()),
            "run_id": subject.run.run_id, "decision": decision,
            **{name: entry[name] for name in ("node_id", "approval_scope", "execution_id",
                                              "execution_node_id", "attempt_no", "inputs_digest")}}
    return subject.approvals.record_execution(subject.request, body)["approval_ref"]


def test_the_deterministic_store_calls_its_tool_only_through_the_approved_attempt(tmp_path, worker):
    with gated(tmp_path) as subject:
        calls = []
        visit = sch.execution_identity(subject.run.run_id, STORE, 0)
        waiting = scheduler_of(subject, calls).run()
        # the store node waits on its own first attempt's execution-bound decision
        assert waiting.awaiting_execution == ((GATE, SCOPE, visit, STORE, 1),)
        assert (STORE, True) not in calls and worker.tool["calls"] == 0
        assert subject.ledger.attempts_for_run(subject.run.run_id) == []
        ask = subject.ledger.execution_approval_requested(subject.run.run_id, GATE, SCOPE, visit, 1)
        assert ask["execution_node_id"] == STORE
        assert ask["inputs_digest"] == transport_of(subject).artifact_inputs_digest

        approval = decide(subject)
        done = scheduler_of(subject, calls).run()
        assert STORE in done.completed_node_ids and done.pending_node_ids == ()
        assert (STORE, True) in calls  # the handler ran with the attempt capability
        [attempt] = subject.ledger.attempts_for_run(subject.run.run_id)
        assert attempt["terminal_outcome"] == "succeeded"
        [call] = subject.ledger.tool_calls_for_attempt(attempt["spec"]["attempt_id"])
        assert call["approval_ref"] == approval and call["state"] == "succeeded"
        assert (call["tool_id"], call["effect_class"]) == (TEST_ACTOR_TOOL["tool_id"], EFFECT)
        assert call["created_at_ms"] == attempt["send_intent_at_ms"]  # one claim transaction
        assert worker.tool["calls"] == 1 and worker.box.get("served") == 1
        # the node's result is the accepted attempt's sealed result (the scheduler admits
        # nothing else for a bound visit), never the handler's own stand-in artifact
        assert dict(done.result_refs)[visit] != subject.refs.result


def test_a_rejected_store_attempt_stops_without_any_send(tmp_path, worker):
    with gated(tmp_path) as subject:
        calls = []
        scheduler_of(subject, calls).run()
        decide(subject, "rejected")
        with pytest.raises(sch.SchedulerError, match=f"approval_refused:{STORE}"):
            scheduler_of(subject, calls).run()
        assert worker.tool["calls"] == 0 and subject.ledger.attempts_for_run(subject.run.run_id) == []


def test_a_tool_bound_deterministic_node_cannot_bypass_the_attempt_transport(tmp_path, actor_tool):
    with gated(tmp_path) as subject:
        # no dispatcher at all: the tool would be reachable outside the ledger boundary
        with pytest.raises(sch.SchedulerError, match="requires its attempt dispatcher"):
            scheduler_of(subject, [], attempts=None)

        # a plain (model-attempt) transport under a deterministic node is refused
        def model_transport(permit, request, window):  # pragma: no cover - never dispatched
            raise AssertionError("unreachable")

        plain = na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={STORE: binding_of(subject, transport_of(subject))}, transport=model_transport)
        with pytest.raises(sch.SchedulerError):
            scheduler_of(subject, [], attempts=plain)
        # binding the tool-free deterministic entry node is refused as before
        intake = na.NodeAttemptDispatcher.build(
            ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
            bindings={"intake": binding_of(subject, transport_of(subject))}, transport=model_transport)
        with pytest.raises(sch.SchedulerError):
            scheduler_of(subject, [], attempts=intake)
        assert actor_tool["calls"] == 0


# ---------------------------------------------------------------- paired isolation

def test_a_past_store_send_is_replayed_in_isolation_and_nothing_is_sent_again(tmp_path, worker, monkeypatch):
    from app.tests.test_paired_tool_effects import (
        PLAIN,
        approved_plan,
        boundary,
        decisions,
        evaluate,
        sides,
    )

    with gated(tmp_path) as subject:
        scheduler_of(subject, []).run()
        decide(subject)
        scheduler_of(subject, []).run()
        [binding] = recorded_effect_bindings(subject.ledger, subject.run.run_id)
        assert binding["tool_id"] == TEST_ACTOR_TOOL["tool_id"] and binding["effect_class"] == EFFECT
        plan = approved_plan(subject, boundary("replay"))
        sent = {"dispatcher_build": 0}
        original = na.NodeAttemptDispatcher.build.__func__

        def counting(cls, *args, **kwargs):
            sent["dispatcher_build"] += 1
            return original(cls, *args, **kwargs)

        monkeypatch.setattr(na.NodeAttemptDispatcher, "build", classmethod(counting))
        baseline, candidate = sides()

        # the store handler of each isolated side makes the item's tool call through the
        # run's isolated effects (the paired runner's only route), keyed by the store node
        def rekey(side):
            def make(item, domain, effects):
                # the base sides call the tool from the writer; here only the store does
                handlers = side.handlers({key: value for key, value in item.items() if key != "notice"},
                                         domain, effects)
                inner = handlers["core.deterministic"]

                def store(context, view):
                    if context.node_id == STORE and "notice" in item:
                        return effects.invoke(TEST_ACTOR_TOOL["tool_id"], TEST_ACTOR_TOOL["version"],
                                              (("document_source", "text/plain", b"approved bytes"),))
                    return inner(context, view)

                return {**handlers, "core.deterministic": store, "core.human_gate": inner}
            return PairedSide(side.label, compile_value(linear_store_graph()), make, uses_tool_effects=True)

        item = {"text": "과거 저장이 있는 합성 업무", "notice": True, "past_tool_effects": [dict(binding)]}
        paired = execute_paired_round(
            plan, items=[PLAIN, item], baseline=rekey(baseline), candidate=rekey(candidate),
            evaluator=evaluate, reset_root=tmp_path / "reset", declared_changes=("writer",),
            round_value={"round_id": f"det-{uuid4()}", "round_index": 0,
                         "candidate": ref("change_candidate", 14920),
                         "mandatory_checks": ref("validation_report", 14925), "evidence": [],
                         "usage": ref("decision_record", 14927)},
            tool_effects=ToolEffectSource.build(domain_store=subject.domain, ledger=subject.ledger,
                                                decisions=decisions(subject)))
        assert paired.result.validity == "valid"
        for side in ("baseline", "candidate"):
            [effect] = paired.item_outcomes[1][f"{side}_effects"]
            assert effect["boundary"] == "replay"
            assert effect["tool_call_sha256"] == binding["tool_call_sha256"]
        # nothing reached the tool or the worker again, and no dispatcher was built
        assert worker.tool["calls"] == 1 and worker.box.get("served") == 1
        assert sent == {"dispatcher_build": 0}


def linear_store_graph():
    """intake -> writer -> publish where the deterministic publish (not the writer) binds
    the tool; an isolated side runs it with no transport at all (no dispatcher, no gate)."""
    from app.tests.test_graph_execution import linear_graph

    raw = linear_graph()
    raw["nodes"][1]["config"]["tool_binding_ids"] = []
    raw["nodes"][2]["config"] = {"handler_id": STORE_HANDLER, "tool_binding_ids": ["source-read"]}
    raw["nodes"][2]["grant_refs"] = [ref("grant", 6)]
    return raw
