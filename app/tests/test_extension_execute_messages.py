"""T087/T018 slice: the closed execute request/reply grammar carried on the
extension channel's existing request/result message types
(contracts/extension-worker-probe.md §3: the first authenticated application
frame selects the mode by its exact request schema).

`extension-execute-v1` carries identities and references only (attempt,
execution, operation, envelope/profile refs, deadline, a fresh nonce);
`extension-execute-result-v1` carries the runtime ledger's result vocabulary
(outcome, usage finality, remote terminal observation, typed reason, exact
usage counters iff final) and, for a succeeded `status`, the worker's own
reading as the output. Canonical strict JSON, byte-equal on reparse.
"""

import json
import os
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef, canonical_json
from app.runtime import ledger as ledger_module
from app.runtime.budgets import BudgetUsage
from app.workers import extension_execute_messages as xm
from app.workers.extension_probe_messages import (
    MAX_REQUEST_BYTES as PROBE_REQUEST_BYTES,
)
from app.workers.extension_probe_messages import (
    encode_probe_request,
)


def ref(kind):
    return EntityRef(kind, str(uuid4()), 1, "c" * 64)


def request_fields(**changes):
    values = {
        "attempt_id": str(uuid4()),
        "execution_id": str(uuid4()),
        "operation": "status",
        "envelope_ref": ref("execution_envelope"),
        "profile_ref": ref("runtime_profile"),
        "remaining_ms": 1_500,
        "challenge": os.urandom(32),
    }
    return {**values, **changes}


def output():
    return {
        "service_identity": "deeptwin-extension-worker",
        "component": {
            "build_identity_digest": "a" * 64,
            "port_contract_version": "tool-port-v1",
            "port_schema_set_digest": "b" * 64,
        },
        "runtime": {"platform": "linux/amd64", "uid": 1000, "gid": 1000,
                    "registered_operations": ["status"]},
    }


def usage_fields():
    return {"model_calls": 0, "tool_calls": 0, "node_visits": 1, "loop_rounds": 0,
            "output_bytes": 120, "candidates": 0, "api_microunits": None}


def reply_fields(**changes):
    values = {
        "attempt_id": str(uuid4()),
        "operation": "status",
        "challenge": os.urandom(32),
        "outcome": "succeeded",
        "usage_finality": "final",
        "remote_terminal_observed": "succeeded",
        "reason_code": "provider_terminal",
        "usage": usage_fields(),
        "output": output(),
    }
    return {**values, **changes}


def test_vocabulary_is_pinned_to_the_runtime_ledger():
    # the worker package never imports the runtime; the closed sets are mirrored
    assert xm.OUTCOMES == ledger_module.TERMINAL_OUTCOMES
    assert xm.USAGE_FINALITIES == ledger_module.USAGE_FINALITIES
    assert xm.REMOTE_TERMINALS == ledger_module.REMOTE_TERMINALS
    assert xm.REASONS == ledger_module.RESULT_REASONS
    assert xm.USAGE_FIELDS == tuple(BudgetUsage.create(**usage_fields()).as_dict())
    assert xm.OPERATIONS == frozenset({"describe_tools", "invoke_tool", "status", "cancel"})


def test_request_round_trips_canonically_and_is_bounded():
    fields = request_fields()
    raw = xm.encode_execute_request(**fields)
    assert len(raw) <= xm.MAX_REQUEST_BYTES
    parsed = xm.parse_execute_request(raw)
    assert parsed.attempt_id == fields["attempt_id"]
    assert parsed.execution_id == fields["execution_id"]
    assert parsed.operation == "status"
    assert parsed.envelope_ref == fields["envelope_ref"]
    assert parsed.profile_ref == fields["profile_ref"]
    assert parsed.remaining_ms == 1_500
    assert parsed.challenge == fields["challenge"]
    assert "challenge" not in repr(parsed) or fields["challenge"].hex() not in repr(parsed)
    value = json.loads(raw)
    assert value["schema_version"] == xm.REQUEST_SCHEMA == "extension-execute-v1"
    assert set(value) == {"schema_version", "attempt_id", "execution_id", "operation",
                          "envelope_ref", "profile_ref", "remaining_ms", "challenge",
                          "artifact_batch_id", "artifact_inputs", "tool"}
    assert xm.peek_schema(raw) == xm.REQUEST_SCHEMA
    probe = encode_probe_request(request_blob_sha256="a" * 64, receipt_blob_sha256="b" * 64,
                                 challenge=os.urandom(32))
    assert xm.peek_schema(probe) == "extension-stage-probe-v1"
    assert PROBE_REQUEST_BYTES <= xm.MAX_REQUEST_BYTES


@pytest.mark.parametrize("change", [
    {"operation": "model_step"},  # not a tool-port-v1 operation
    {"operation": "STATUS"},
    {"attempt_id": "not-a-uuid"},
    {"envelope_ref": ref("runtime_profile")},  # wrong kind
    {"profile_ref": ref("execution_envelope")},
    {"remaining_ms": 0},
    {"remaining_ms": 30_001},  # the channel's operation cap
    {"challenge": b"x" * 31},
])
def test_request_encoding_refuses_values_outside_the_grammar(change):
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_request(**request_fields(**change))


def test_request_parsing_refuses_non_canonical_or_foreign_bytes():
    raw = xm.encode_execute_request(**request_fields())
    value = json.loads(raw)
    with pytest.raises(xm.ExecuteMessageError):
        xm.parse_execute_request(json.dumps(value, indent=1).encode())  # not canonical
    with pytest.raises(xm.ExecuteMessageError):
        xm.parse_execute_request(json.dumps({**value, "extra": 1}, separators=(",", ":"),
                                            sort_keys=True).encode())
    with pytest.raises(xm.ExecuteMessageError):
        xm.parse_execute_request(json.dumps({**value, "schema_version": "extension-stage-probe-v1"},
                                            separators=(",", ":"), sort_keys=True).encode())
    with pytest.raises(xm.ExecuteMessageError):
        xm.parse_execute_request(b"{" + b" " * xm.MAX_REQUEST_BYTES + b"}")
    with pytest.raises(xm.ExecuteMessageError):
        xm.parse_execute_request(raw.decode())  # str, not bytes
    with pytest.raises(xm.ExecuteMessageError):
        xm.peek_schema(b'{"schema_version":"something-else-v1"}')
    with pytest.raises(xm.ExecuteMessageError):
        xm.peek_schema(b"not json")


def test_reply_round_trips_with_output_and_usage_only_when_final():
    fields = reply_fields()
    raw = xm.encode_execute_reply(**fields)
    assert len(raw) <= xm.MAX_REPLY_BYTES
    parsed = xm.parse_execute_reply(raw)
    assert parsed.attempt_id == fields["attempt_id"]
    assert parsed.operation == "status" and parsed.outcome == "succeeded"
    assert parsed.usage_finality == "final"
    assert parsed.remote_terminal_observed == "succeeded"
    assert parsed.reason_code == "provider_terminal"
    assert parsed.challenge == fields["challenge"]
    assert parsed.usage == usage_fields()
    assert BudgetUsage.create(**parsed.usage).as_dict() == usage_fields()
    assert parsed.output == output()
    assert json.loads(raw)["schema_version"] == xm.REPLY_SCHEMA == "extension-execute-result-v1"
    assert xm.peek_schema(raw) == xm.REPLY_SCHEMA
    # a typed refusal: no output, final zero usage
    refused = xm.encode_execute_reply(**reply_fields(
        outcome="failed", remote_terminal_observed="failed", reason_code="validation_failed",
        usage={**usage_fields(), "output_bytes": 0}, output=None,
    ))
    parsed = xm.parse_execute_reply(refused)
    assert parsed.outcome == "failed" and parsed.output is None
    assert parsed.usage["output_bytes"] == 0
    # unknown: no usage, no output
    unknown = xm.encode_execute_reply(**reply_fields(
        outcome="outcome_unknown", usage_finality="unknown",
        remote_terminal_observed="not_observed", reason_code="transport_unknown",
        usage=None, output=None,
    ))
    parsed = xm.parse_execute_reply(unknown)
    assert parsed.usage is None and parsed.output is None


@pytest.mark.parametrize("change", [
    {"outcome": "ok"},
    {"usage_finality": "final", "usage": None},  # final needs counters
    {"usage_finality": "unknown"},  # counters without finality
    {"outcome": "succeeded", "output": None},  # success needs the output
    {"outcome": "failed", "remote_terminal_observed": "failed", "output": output()},
    # the ledger's rule: an unknown outcome cannot claim a known remote terminal
    {"outcome": "outcome_unknown", "usage_finality": "unknown", "usage": None, "output": None,
     "remote_terminal_observed": "failed", "reason_code": "transport_unknown"},
    {"outcome": "failed", "remote_terminal_observed": "succeeded", "output": None},
    {"usage": {**usage_fields(), "model_calls": -1}},
    {"usage": {**usage_fields(), "extra": 1}},
    {"usage": {**usage_fields(), "api_microunits": "5"}},
    {"output": {**output(), "runtime": {**output()["runtime"], "registered_operations": ["nope"]}}},
    {"output": {**output(), "service_identity": "Bad Identity"}},
    {"reason_code": "because"},
    {"operation": "invoke_tools"},
])
def test_reply_encoding_refuses_values_outside_the_grammar(change):
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_reply(**reply_fields(**change))


def tool_entry(**changes):
    # a worker cannot reference control-side schema records: an entry carries the digests
    # of its argument and result schemas (control resolves and seals them later)
    return {
        "tool_id": "read_text", "version": "1.0.0",
        "argument_schema_sha256": "a" * 64, "result_schema_sha256": "b" * 64,
        "effect_class": "read", "artifact_roles": ["source"], **changes,
    }


def test_describe_tools_reply_carries_the_ports_contract_tool_shape_or_an_empty_catalogue():
    # T087 second operation: `describe_tools` → {tools:[{tool_id,version,argument_schema_ref,
    # result_schema_ref,effect_class,artifact_roles}]} (extension-ports.md §3.2); the output
    # shape is selected by the reply's operation, so a status shape under describe_tools (or
    # the reverse) is outside the grammar
    empty = xm.parse_execute_reply(xm.encode_execute_reply(**reply_fields(
        operation="describe_tools", output={"tools": []},
        usage={**usage_fields(), "output_bytes": len(canonical_json({"tools": []}))})))
    assert empty.operation == "describe_tools" and empty.output == {"tools": []}
    entry = tool_entry()
    full = xm.parse_execute_reply(xm.encode_execute_reply(**reply_fields(
        operation="describe_tools", output={"tools": [entry]})))
    assert full.output == {"tools": [entry]}
    assert full.output["tools"][0]["argument_schema_sha256"] == "a" * 64
    for change in [
        {"operation": "describe_tools", "output": output()},
        {"operation": "status", "output": {"tools": []}},
        {"operation": "describe_tools", "output": {}},
        {"operation": "describe_tools", "output": {"tools": [], "extra": 1}},
        {"operation": "describe_tools", "output": {"tools": {}}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(tool_id="Bad Id")]}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(effect_class="wild")]}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(artifact_roles=["b", "a"])]}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(artifact_roles=["a", "a"])]}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(version="")]}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(argument_schema_sha256="x")]}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(result_schema_sha256="B" * 64)]}},
        {"operation": "describe_tools", "output": {"tools": [{**tool_entry(), "extra": 1}]}},
        {"operation": "describe_tools", "output": {"tools": [tool_entry(), tool_entry()]}},  # ids unique
        {"operation": "describe_tools", "output": {"tools": [tool_entry(tool_id="b"), tool_entry(tool_id="a")]}},
        {"operation": "invoke_tool", "output": {"tools": []}},  # no output grammar yet: no success
    ]:
        with pytest.raises(xm.ExecuteMessageError):
            xm.encode_execute_reply(**reply_fields(**change))
    # the same refusals on parse: a foreign encoder cannot smuggle the shape
    forged = json.loads(xm.encode_execute_reply(**reply_fields(operation="describe_tools", output={"tools": []})))
    forged["output"] = output()
    with pytest.raises(xm.ExecuteMessageError):
        xm.parse_execute_reply(canonical_json(forged))


def test_the_tool_table_is_bounded_by_the_bytes_the_reply_can_carry():
    # review closure: eight grammar-maximal entries validate but cannot be encoded under the
    # 4096 B reply cap, so the worker would fail to answer instead of refusing at validation;
    # the binding bound is canonical bytes, checked where the table is validated
    def maximal(index):
        return tool_entry(
            tool_id=f"t{index}" + "x" * 62, version="v" * 64,
            argument_schema_sha256="c" * 64, result_schema_sha256="d" * 64,
            artifact_roles=[f"r{role}" + "y" * 62 for role in range(8)],
        )
    assert xm.MAX_TOOLS_BYTES + 1_024 <= xm.MAX_REPLY_BYTES  # the rest of the reply always fits
    one = xm._output({"tools": [maximal(0)]}, "describe_tools")
    assert len(canonical_json(one)) <= xm.MAX_TOOLS_BYTES
    too_many = next(count for count in range(2, xm.MAX_TOOLS + 1)
                    if len(canonical_json({"tools": [maximal(index) for index in range(count)]})) > xm.MAX_TOOLS_BYTES)
    assert too_many == 4  # pinned: a bound drift is visible
    with pytest.raises(xm.ExecuteMessageError):
        xm._output({"tools": [maximal(index) for index in range(too_many)]}, "describe_tools")
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_reply(**reply_fields(operation="describe_tools",
                                               output={"tools": [maximal(index) for index in range(too_many)]}))
    # the roles list has its own bound, distinct from the table's
    with pytest.raises(xm.ExecuteMessageError):
        xm._output({"tools": [tool_entry(artifact_roles=[f"r{n:03d}" for n in range(xm.MAX_ROLES + 1)])]},
                   "describe_tools")


def artifact_input(**changes):
    return {"ordinal": 0, "media_type": "text/plain", "declared_size": 5, "sha256": "d" * 64,
            "role": "source", **changes}


def test_the_request_declares_its_artifact_inputs_for_the_bounded_stream():
    # T018/T087 artifact leg: the request names the bytes that will follow it over the
    # channel's artifact type — descriptors only (ordinal, media, size, digest, role) under
    # a fresh batch id; the bytes themselves travel only over the digest/chunk/credit stream
    batch = str(uuid4())
    items = [artifact_input(), artifact_input(ordinal=1, media_type="application/json", declared_size=0,
                                              sha256="e" * 64, role="arguments")]
    tool = {"tool_id": "text_profile", "version": "1.0.0"}
    raw = xm.encode_execute_request(**request_fields(operation="invoke_tool", tool=tool, artifact_batch_id=batch,
                                                     artifact_inputs=items))
    assert len(raw) <= xm.MAX_REQUEST_BYTES == 4_096
    parsed = xm.parse_execute_request(raw)
    assert parsed.artifact_batch_id == batch
    assert [item.as_dict() for item in parsed.artifact_inputs] == items
    request_id = str(uuid4())
    descriptors = parsed.artifact_descriptors(request_id)
    assert [(d.batch_id, d.request_id, d.ordinal, d.count, d.media_type, d.declared_size, d.sha256)
            for d in descriptors] == [(batch, request_id, 0, 2, "text/plain", 5, "d" * 64),
                                      (batch, request_id, 1, 2, "application/json", 0, "e" * 64)]
    # no inputs: no batch id, an empty list, and the old wire shape still parses
    plain = xm.parse_execute_request(xm.encode_execute_request(**request_fields()))
    assert plain.artifact_batch_id is None and plain.artifact_inputs == ()
    assert plain.artifact_descriptors(request_id) == []
    assert json.loads(xm.encode_execute_request(**request_fields()))["artifact_inputs"] == []
    for change in [
        {"artifact_batch_id": batch},  # a batch id without items
        {"artifact_inputs": items},  # items without a batch id
        {"artifact_batch_id": "nope", "artifact_inputs": items},
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(ordinal=1)]},  # not the exact sequence
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(), artifact_input()]},
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(ordinal=n) for n in range(xm.MAX_ARTIFACT_INPUTS + 1)]},
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(declared_size=xm.MAX_INPUT_BYTES + 1)]},
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(declared_size=xm.MAX_INPUT_BYTES),
                                                         artifact_input(ordinal=1, declared_size=1)]},  # total
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(media_type="Text/Plain")]},
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(sha256="D" * 64)]},
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(role="Bad Role")]},
        {"artifact_batch_id": batch, "artifact_inputs": [{**artifact_input(), "extra": 1}]},
        {"artifact_batch_id": batch, "artifact_inputs": [artifact_input(declared_size=-1)]},
        {"artifact_batch_id": batch, "artifact_inputs": "nope"},
    ]:
        with pytest.raises(xm.ExecuteMessageError):
            xm.encode_execute_request(**request_fields(operation="invoke_tool", tool=tool, **change))
    forged = json.loads(raw)
    forged["artifact_inputs"][0]["ordinal"] = 1
    with pytest.raises(xm.ExecuteMessageError):
        xm.parse_execute_request(canonical_json(forged))


def test_invoke_tool_names_its_tool_in_the_request_and_answers_with_the_tools_result():
    # T087 first real tool: the request names the exact tool (id, version) it invokes — only
    # for invoke_tool; the reply's output is {tool_id, version, result} with the tool's own
    # bounded JSON result, sealed control-side as the attempt's artifact
    tool = {"tool_id": "text_profile", "version": "1.0.0"}
    raw = xm.encode_execute_request(**request_fields(operation="invoke_tool", tool=tool))
    parsed = xm.parse_execute_request(raw)
    assert parsed.tool == xm.ToolSelection(tool_id="text_profile", version="1.0.0")
    assert xm.parse_execute_request(xm.encode_execute_request(**request_fields())).tool is None
    assert json.loads(xm.encode_execute_request(**request_fields()))["tool"] is None
    for change in [
        {"operation": "invoke_tool"},  # invoke_tool names its tool
        {"operation": "status", "tool": tool},  # a query names none
        {"operation": "invoke_tool", "tool": {"tool_id": "Bad Id", "version": "1.0.0"}},
        {"operation": "invoke_tool", "tool": {"tool_id": "text_profile", "version": ""}},
        {"operation": "invoke_tool", "tool": {"tool_id": "text_profile"}},
        {"operation": "invoke_tool", "tool": {**tool, "arguments": {}}},  # no argument grammar yet
        {"operation": "invoke_tool", "tool": "text_profile"},
    ]:
        with pytest.raises(xm.ExecuteMessageError):
            xm.encode_execute_request(**request_fields(**change))
    result = {"byte_count": 5, "char_count": 5, "line_count": 1, "word_count": 1, "sha256": "e" * 64, "utf8": True}
    output = {"tool_id": "text_profile", "version": "1.0.0", "result": result}
    reply = xm.parse_execute_reply(xm.encode_execute_reply(**reply_fields(
        operation="invoke_tool", output=output,
        usage={**usage_fields(), "tool_calls": 1, "output_bytes": len(canonical_json(output))})))
    assert reply.output == output
    assert "invoke_tool" in xm.OUTPUT_OPERATIONS
    for change in [
        {"operation": "invoke_tool", "output": {"tools": []}},
        {"operation": "invoke_tool", "output": {"tool_id": "text_profile", "version": "1.0.0"}},
        {"operation": "invoke_tool", "output": {**output, "extra": 1}},
        {"operation": "invoke_tool", "output": {**output, "result": []}},
        {"operation": "invoke_tool", "output": {**output, "result": "x"}},
        {"operation": "invoke_tool", "output": {**output, "tool_id": "Bad Id"}},
        {"operation": "status", "output": output},
        {"operation": "describe_tools", "output": output},
    ]:
        with pytest.raises(xm.ExecuteMessageError):
            xm.encode_execute_reply(**reply_fields(**change))


def test_a_tool_result_is_closed_over_the_wire_limits_at_encode_as_at_parse():
    # review closure: a handler result the reply cannot carry must be refused where it is
    # built, not by control's parser (which would make a deterministic tool unknown)
    def reply(result):
        output = {"tool_id": "text_profile", "version": "1.0.0", "result": result}
        return reply_fields(operation="invoke_tool", output=output, usage={**usage_fields(), "tool_calls": 1})
    nested = {"a": {"b": {"c": {"d": {"e": 1}}}}}  # five levels under the result
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_reply(**reply(nested))
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_reply(**reply({"text": "x" * 129}))
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_reply(**reply({f"k{n:02d}": n for n in range(17)}))
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_reply(**reply({"n": 1.5}))  # no floats on the wire
    xm.parse_execute_reply(xm.encode_execute_reply(**reply({"a": {"b": {"c": 1}}})))
