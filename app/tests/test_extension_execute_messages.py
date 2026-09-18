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
                          "envelope_ref", "profile_ref", "remaining_ms", "challenge"}
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
    return {
        "tool_id": "read_text", "version": "1.0.0",
        "argument_schema_ref": ref("artifact").as_dict(), "result_schema_ref": ref("artifact").as_dict(),
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
    assert type(full.output["tools"][0]["argument_schema_ref"]) is dict
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
        {"operation": "describe_tools", "output": {"tools": [tool_entry(argument_schema_ref="x")]}},
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
            argument_schema_ref=EntityRef("deployment_receipt_consumption", str(uuid4()), 2**32 - 1, "c" * 64).as_dict(),
            result_schema_ref=EntityRef("deployment_receipt_consumption", str(uuid4()), 2**32 - 1, "c" * 64).as_dict(),
            artifact_roles=[f"r{role}" + "y" * 62 for role in range(8)],
        )
    assert xm.MAX_TOOLS_BYTES + 1_024 <= xm.MAX_REPLY_BYTES  # the rest of the reply always fits
    one = xm._output({"tools": [maximal(0)]}, "describe_tools")
    assert len(canonical_json(one)) <= xm.MAX_TOOLS_BYTES
    with pytest.raises(xm.ExecuteMessageError):
        xm._output({"tools": [maximal(index) for index in range(4)]}, "describe_tools")
    with pytest.raises(xm.ExecuteMessageError):
        xm.encode_execute_reply(**reply_fields(operation="describe_tools",
                                               output={"tools": [maximal(index) for index in range(4)]}))
    # the roles list has its own bound, distinct from the table's
    with pytest.raises(xm.ExecuteMessageError):
        xm._output({"tools": [tool_entry(artifact_roles=[f"r{n:03d}" for n in range(xm.MAX_ROLES + 1)])]},
                   "describe_tools")
