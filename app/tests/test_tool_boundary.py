"""US3 tool dispatcher boundary: closed registry, grants, effects, replay.

The dispatcher, not the model, maps tool ids to code: an unregistered tool
or an unknown version is unsupported, never interpreted, and nothing an
extension or model outputs can add a tool or widen its input profile. Tool
arguments carry no artifact or selector refs — the ordered artifact-input
bindings are the sole byte-input authority — and no argument smuggles a
host path. The required grant must match exactly; external and
irreversible effects require an explicit effect approval; replay policy is
authoritative (an irreversible tool never re-dispatches the same request,
a dedup tool returns the same envelope); and an unknown external outcome
holds the request — retry is blocked until reconciliation (runtime.md §6,
FR-014/FR-032; T047 core slice).
"""

import dataclasses

import pytest

from app.runtime.tools import (
    ToolBoundaryError,
    dispatch_tool,
    open_tool_registry,
    record_outcome,
    register_tool,
)
from app.tests.test_alternatives import ref

REQUEST = "00000000-0000-4000-8000-00000000ee01"
REQUEST2 = "00000000-0000-4000-8000-00000000ee02"


def definition(**overrides):
    value = {
        "tool_id": "deeptwin_pdf_render",
        "version": 1,
        "argument_keys": {"page_range": "str", "dpi": "int"},
        "result_schema_id": "pdf-render-result-v1",
        "effect_class": "write",
        "required_grant": ref("grant", 1401),
        "filesystem_scopes": ["workspace/artifacts"],
        "network_scopes": [],
        "timeout_seconds": 60,
        "max_result_bytes": 8_388_608,
        "idempotency": "dedup_by_request",
        "replay": "safe",
        "implementation_sha256": "cd" * 32,
        "qualification_ref": ref("extension_qualification", 1402),
    }
    value.update(overrides)
    return value


def request(**overrides):
    value = {
        "tool_id": "deeptwin_pdf_render",
        "version": 1,
        "request_id": REQUEST,
        "arguments": {"page_range": "1-4", "dpi": 144},
        "grant_ref": ref("grant", 1401),
        "effect_approval_ref": None,
        "artifact_inputs": [ref("artifact", 1403)],
    }
    value.update(overrides)
    return value


def registry():
    return register_tool(open_tool_registry(), definition())


def test_the_registry_is_closed_and_exact():
    state = registry()
    with pytest.raises(ToolBoundaryError):
        register_tool(state, definition())  # same id+version never twice
    with pytest.raises(ToolBoundaryError):
        # unknown tool: unsupported, never interpreted
        dispatch_tool(state, request(tool_id="model_invented_tool"))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(version=9))
    with pytest.raises(ToolBoundaryError):
        register_tool(state, definition(effect_class="vibes"))


def test_arguments_never_carry_refs_or_host_paths():
    state = registry()
    envelope, state = dispatch_tool(state, request())
    assert envelope.tool_id == "deeptwin_pdf_render"
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "1-4", "dpi": 144,
                       "artifact_ref": ref("artifact", 1404)},
        ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "/etc/passwd", "dpi": 144},
        ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "../../secrets", "dpi": 144},
        ))
    with pytest.raises(ToolBoundaryError):
        # undeclared argument keys widen the input profile: refused
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "1-4", "dpi": 144, "shell": "rm"},
        ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            request_id=REQUEST2,
            arguments={"page_range": "1-4", "dpi": "144"},  # wrong type
        ))


def test_the_grant_must_match_exactly():
    state = registry()
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(grant_ref=ref("grant", 1499)))


def test_external_and_irreversible_effects_require_approval():
    state = register_tool(registry(), definition(
        tool_id="deeptwin_send_email", effect_class="irreversible",
        replay="never", idempotency="none",
    ))
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(state, request(
            tool_id="deeptwin_send_email", request_id=REQUEST2,
        ))
    envelope, state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2,
        effect_approval_ref=ref("action_approval", 1405),
    ))
    assert envelope.effect_class == "irreversible"
    # a write tool never demands an approval it does not need
    _envelope, _state = dispatch_tool(state, request())


def test_replay_policy_is_authoritative():
    state = register_tool(registry(), definition(
        tool_id="deeptwin_send_email", effect_class="irreversible",
        replay="never", idempotency="none",
    ))
    _envelope, state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2,
        effect_approval_ref=ref("action_approval", 1405),
    ))
    with pytest.raises(ToolBoundaryError):
        # an irreversible request never re-dispatches
        dispatch_tool(state, request(
            tool_id="deeptwin_send_email", request_id=REQUEST2,
            effect_approval_ref=ref("action_approval", 1405),
        ))
    first, state = dispatch_tool(state, request())
    again, state = dispatch_tool(state, request())  # dedup_by_request
    assert again == first


def test_an_unknown_outcome_blocks_retry_until_reconciled():
    state = register_tool(registry(), definition(
        tool_id="deeptwin_send_email", effect_class="external",
        replay="requires_confirmation", idempotency="none",
    ))
    _envelope, state = dispatch_tool(state, request(
        tool_id="deeptwin_send_email", request_id=REQUEST2,
        effect_approval_ref=ref("action_approval", 1405),
    ))
    state = record_outcome(state, REQUEST2, "unknown")
    with pytest.raises(ToolBoundaryError):
        # unknown external outcome: held, never silently retried
        dispatch_tool(state, request(
            tool_id="deeptwin_send_email", request_id=REQUEST2,
            effect_approval_ref=ref("action_approval", 1405),
        ))
    state = record_outcome(state, REQUEST2, "failed")
    with pytest.raises(ToolBoundaryError):
        record_outcome(state, REQUEST2, "succeeded")  # outcomes are final
    with pytest.raises(ToolBoundaryError):
        record_outcome(state, "00000000-0000-4000-8000-00000000ee09",
                       "succeeded")


def test_values_are_issued_never_constructed():
    state = registry()
    envelope, state = dispatch_tool(state, request())
    with pytest.raises(TypeError):
        dataclasses.replace(envelope, effect_class="read")
    with pytest.raises(TypeError):
        dataclasses.replace(state, dispatched=())
    with pytest.raises(ToolBoundaryError):
        dispatch_tool(object(), request())
    with pytest.raises(ToolBoundaryError):
        register_tool(object(), definition())
