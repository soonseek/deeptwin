"""Test-only support for the T087 tool-gate scheduler slice (2026-09-25).

`test_actor_notify` 1.0.0 is a TEST-ACTOR tool: it is registered in the extension
worker's code-owned tool table and in control's mirror of it ONLY by
`register_test_actor_tool`, for the duration of a test (a pytest monkeypatch) or of
a test fixture process (app/tests/fixtures/tool_gate_server.py). The production
table is unchanged: it holds no external-effect tool. The tool claims the ports'
`external_irreversible` effect class so the compiled graph must gate it, but it
performs no external effect at all: it reads its one `document_source` text input
and answers a deterministic reading (`notified`, the input's sha256 and size). It
can be told to fail its next N calls (a terminal `failed` with one tool call and
final usage) to exercise the owner's recovery retry; an input starting with
`fail-once` fails only the first call made on it.

`tool_gated_graph()` is `linear_graph()` with a human gate (`tool-gate`) between
`intake` and `writer` that supplies the tool's approval scope to the writer, whose
`source-read` binding names the test-actor tool.
"""

from __future__ import annotations

from hashlib import sha256
from types import MappingProxyType

from app.domain.refs import canonical_json
from app.runtime import extension_attempt_transport as xt
from app.runtime.gates import tool_approval_scope
from app.workers import extension_probe as ep

TEST_ACTOR_TOOL = {"tool_id": "test_actor_notify", "version": "1.0.0"}
KEY = (TEST_ACTOR_TOOL["tool_id"], TEST_ACTOR_TOOL["version"])
SCOPE = tool_approval_scope(*KEY)
GATE = "tool-gate"
EFFECT = "external_irreversible"
_RESULT_SCHEMA = {"type": "object", "additionalProperties": False,
                  "required": ["notified", "sha256", "byte_count"],
                  "properties": {"notified": {"const": True},
                                 "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                                 "byte_count": {"type": "integer", "minimum": 0}}}
ENTRY = MappingProxyType({
    "tool_id": KEY[0], "version": KEY[1],
    "argument_schema_sha256": sha256(canonical_json(ep.TEXT_PROFILE_ARGUMENT_SCHEMA)).hexdigest(),
    "result_schema_sha256": sha256(canonical_json(_RESULT_SCHEMA)).hexdigest(),
    "effect_class": EFFECT, "artifact_roles": ("document_source",),
})
_INPUT = xt.TOOL_INPUT_CONTRACTS[("text_profile", "1.0.0")]
# an input starting with this fails the tool's first call on it (the recovery retry case)
FAIL_ONCE = b"fail-once"


def register_test_actor_tool(monkeypatch):
    """Register the test-actor tool in the worker's table (describe/admit/invoke) and
    in control's mirror (inputs, outputs, effect, output bound). Returns the tool's
    shared state: `calls` (invocations that reached the tool) and `fail_next`."""

    state = {"calls": 0, "fail_next": 0, "failed_once": set()}
    original = ep._OPERATIONS["invoke_tool"]

    def invoke(service, request, deadline, inputs):
        if request.tool is None or (request.tool.tool_id, request.tool.version) != KEY:
            return original(service, request, deadline, inputs)
        if not ep._tool_contract_admits(request) or len(inputs) != 1:
            return ep._tool_failed("validation_failed", 0)
        _declaration, raw = inputs[0]
        state["calls"] += 1
        digest = sha256(raw).hexdigest()
        if raw.startswith(FAIL_ONCE) and digest not in state["failed_once"]:
            state["failed_once"].add(digest)  # a `fail-once` input fails its first call only
            return ep._tool_failed("provider_terminal", 1)
        if state["fail_next"] > 0:
            state["fail_next"] -= 1
            return ep._tool_failed("provider_terminal", 1)
        output = {"tool_id": KEY[0], "version": KEY[1], "artifacts": [],
                  "result": {"notified": True, "sha256": sha256(raw).hexdigest(), "byte_count": len(raw)}}
        return {
            "outcome": "succeeded", "usage_finality": "final",
            "remote_terminal_observed": "succeeded", "reason_code": "provider_terminal",
            "usage": {**ep._ZERO_USAGE, "tool_calls": 1, "output_bytes": len(canonical_json(output))},
            "output": output, "artifacts": (),
        }

    monkeypatch.setattr(ep, "_OPERATIONS", MappingProxyType({**ep._OPERATIONS, "invoke_tool": invoke}))
    monkeypatch.setattr(ep, "_TOOLS", (*ep._TOOLS, ENTRY))
    monkeypatch.setattr(ep, "TOOL_INPUT_CONTRACTS", MappingProxyType({**ep.TOOL_INPUT_CONTRACTS, KEY: _INPUT}))
    monkeypatch.setattr(xt, "TOOL_INPUT_CONTRACTS", MappingProxyType({**xt.TOOL_INPUT_CONTRACTS, KEY: _INPUT}))
    monkeypatch.setattr(xt, "TOOL_OUTPUT_CONTRACTS", MappingProxyType({**xt.TOOL_OUTPUT_CONTRACTS, KEY: ()}))
    monkeypatch.setattr(xt, "TOOL_EFFECTS", MappingProxyType({**xt.TOOL_EFFECTS, KEY: EFFECT}))
    monkeypatch.setattr(xt, "TOOL_OUTPUT_BOUNDS", MappingProxyType({**xt.TOOL_OUTPUT_BOUNDS, KEY: (0, 0)}))
    return state


def tool_gated_graph():
    from app.tests.test_graph_contract import (
        approval_edge,
        artifact_edge,
        input_slot,
        node,
        output_slot,
    )
    from app.tests.test_graph_execution import linear_graph

    raw = linear_graph()
    writer = next(item for item in raw["nodes"] if item["node_id"] == "writer")
    writer["required_approval_scopes"] = [SCOPE]
    raw["nodes"].insert(1, node(GATE, "human_gate", "사람이 외부 도구 호출을 시도마다 승인한다",
                                inputs=[input_slot("candidate", "text-document")],
                                outputs=[output_slot("approved", "text-document")],
                                config={"approval_scopes": [SCOPE]}))
    raw["edges"] = [edge for edge in raw["edges"] if edge["edge_id"] != "e1"] + [
        artifact_edge("e1a", "intake", "draft", GATE, "candidate", "text-document"),
        artifact_edge("e1b", GATE, "approved", "writer", "source", "text-document"),
        approval_edge("e6", GATE, "writer", SCOPE),
    ]
    return raw


def tool_authority():
    from app.tests.test_graph_contract import authority_with, trusted_tool

    return authority_with([trusted_tool(EFFECT, tool_id=KEY[0], version=KEY[1])])


def compiled_tool_gated():
    from app.tests.test_graph_contract import compile_value

    return compile_value(tool_gated_graph(), compilation_authority=tool_authority())


# 2026-09-26 owner decision (deterministic tool bindings): the same test-actor tool bound
# to a DETERMINISTIC node — a byte-exact store step after the gate — instead of an agent.
STORE = "publish"
STORE_HANDLER = "byte-exact-store-v1"


def deterministic_tool_gated_graph():
    """`linear_graph()` whose deterministic `publish` node is the tool caller: the writer
    binds no tool, a human gate (`tool-gate`) between writer and publish supplies the
    tool's approval scope, and publish's config names the `source-read` binding."""
    from app.tests.test_graph_contract import (
        approval_edge,
        artifact_edge,
        input_slot,
        node,
        output_slot,
        ref,
    )
    from app.tests.test_graph_execution import linear_graph

    raw = linear_graph()
    writer = next(item for item in raw["nodes"] if item["node_id"] == "writer")
    writer["config"]["tool_binding_ids"] = []
    store = next(item for item in raw["nodes"] if item["node_id"] == STORE)
    store["responsibility"] = "승인된 산출물을 바이트 그대로 저장한다"
    store["config"] = {"handler_id": STORE_HANDLER, "tool_binding_ids": ["source-read"]}
    store["grant_refs"] = [ref("grant", 6)]
    store["required_approval_scopes"] = [SCOPE]
    raw["nodes"].insert(2, node(GATE, "human_gate", "사람이 저장 도구 호출을 시도마다 승인한다",
                                inputs=[input_slot("candidate", "text-document")],
                                outputs=[output_slot("approved", "text-document")],
                                config={"approval_scopes": [SCOPE]}))
    raw["edges"] = [edge for edge in raw["edges"] if edge["edge_id"] != "e2"] + [
        artifact_edge("e2a", "writer", "draft", GATE, "candidate", "text-document"),
        artifact_edge("e2b", GATE, "approved", STORE, "approved", "text-document"),
        approval_edge("e6", GATE, STORE, SCOPE),
    ]
    return raw


def compiled_deterministic_tool_gated():
    from app.tests.test_graph_contract import compile_value

    return compile_value(deterministic_tool_gated_graph(), compilation_authority=tool_authority())
