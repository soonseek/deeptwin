"""US3 provider-neutral frozen turns and step-output authority (T042 part).

A FrozenTurn binds work/environment/node/execution/attempt, the provider
path, catalog/model/effort, the instruction-profile digest, an ALLOWLISTED
set of typed input parts, the output schema, runtime-profile qualification,
deadline, budget and consent — inputs are constructed from the profile's
allowlist, never an arbitrary object with a blacklist. Non-text parts
(actual page, image, table) carry an explicit marker binding them to their
artifact, and extraction omissions are declared, never hidden (R06). Step
output parsing never accepts new capability names or arbitrary host paths
as execution authority: tool requests exist only for the execution profile,
only for granted tools, and only with path-free arguments (runtime.md §1).
"""

import dataclasses

import pytest

from app.runtime.gateway import (
    GATEWAY_PROFILES,
    FrozenTurn,
    GatewayError,
    freeze_turn,
    validate_step_output,
)
from app.tests.test_alternatives import ref

EXECUTION_ID = "00000000-0000-4000-8000-00000000ab01"


def part(kind="text", suffix=1201, **overrides):
    value = {
        "type": kind,
        "ref": ref("artifact", suffix),
        "marker": None if kind == "text" else f"{kind}:{suffix}:p1",
        "omissions": [],
    }
    value.update(overrides)
    return value


def turn_value(**overrides):
    value = {
        "profile": "execution-model-step",
        "work_ref": ref("work_revision", 1210),
        "environment_ref": ref("environment", 1211),
        "node_id": "writer-node",
        "execution_id": EXECUTION_ID,
        "attempt_index": 0,
        "provider": "claude_api",
        "account_id": "acct-primary",
        "catalog_ref": ref("model_catalog", 1212),
        "model_id": "claude-sonnet-5",
        "effort": "medium",
        "instruction_profile_digest": "ab" * 32,
        "inputs": [part(), part("image", 1202)],
        "granted_tools": ["deeptwin_browser", "deeptwin_pdf"],
        "output_schema_id": "execution-step-v1",
        "runtime_profile_ref": ref("runtime_profile", 1213),
        "deadline_seconds": 300,
        "budget_ref": ref("budget_policy", 1214),
        "consent_ref": ref("run_consent", 1215),
    }
    value.update(overrides)
    return value


def test_a_frozen_turn_binds_everything_and_is_issued():
    turn = freeze_turn(turn_value())
    assert type(turn) is FrozenTurn
    assert turn.profile == "execution-model-step"
    assert len(turn.inputs) == 2
    with pytest.raises(TypeError):
        dataclasses.replace(turn, granted_tools=("shell",))
    with pytest.raises(GatewayError):
        freeze_turn({"unexpected": True})
    with pytest.raises(GatewayError):
        freeze_turn(turn_value(provider="free_fallback"))
    with pytest.raises(GatewayError):
        freeze_turn(turn_value(deadline_seconds=0))


@pytest.mark.parametrize(
    "effort",
    ["low", "medium", "high", "xhigh", "max", "fixture-next", "e" * 80, None],
)
def test_frozen_turn_preserves_nullable_bounded_provider_effort(effort):
    assert freeze_turn(turn_value(effort=effort)).effort == effort


@pytest.mark.parametrize("effort", [True, 1, {}, [], "", "e" * 81])
def test_frozen_turn_rejects_effort_outside_nullable_bounded_string_grammar(effort):
    with pytest.raises(GatewayError):
        freeze_turn(turn_value(effort=effort))


def test_profiles_allowlist_their_inputs():
    assert set(GATEWAY_PROFILES) == {
        "understanding", "design", "critic", "execution-model-step",
        "diagnosis", "inquiry", "change-compiler-input", "sealed-evaluator",
    }
    understanding = turn_value(
        profile="understanding",
        inputs=[part(suffix=1220, ref=ref("work_revision", 1220)),
                part(suffix=1221, ref=ref("source", 1221))],
        granted_tools=[],
    )
    assert freeze_turn(understanding).profile == "understanding"
    with pytest.raises(GatewayError):
        # the understanding profile never receives operational artifacts
        freeze_turn(turn_value(
            profile="understanding",
            inputs=[part(suffix=1222)],  # kind artifact
            granted_tools=[],
        ))
    with pytest.raises(GatewayError):
        # H_phi material never reaches the change compiler input
        freeze_turn(turn_value(
            profile="change-compiler-input",
            inputs=[part(suffix=1223, ref=ref("own_alternative", 1223))],
            granted_tools=[],
        ))


def test_only_the_execution_profile_carries_tools():
    for profile, inputs in (
        ("understanding", [part(ref=ref("work_revision", 1230))]),
        ("critic", []),
        ("sealed-evaluator", [part(ref=ref("evaluation_dataset", 1231))]),
    ):
        with pytest.raises(GatewayError):
            freeze_turn(turn_value(
                profile=profile, inputs=inputs,
                granted_tools=["deeptwin_browser"],
            ))


def test_non_text_parts_require_markers_and_declare_omissions():
    with pytest.raises(GatewayError):
        freeze_turn(turn_value(inputs=[part("image", 1240, marker=None)]))
    with pytest.raises(GatewayError):
        freeze_turn(turn_value(inputs=[part("table", 1241, marker="")]))
    disclosed = freeze_turn(turn_value(inputs=[
        part("page", 1242, omissions=["2쪽 표의 병합 셀은 추출되지 않았다"]),
    ]))
    assert disclosed.inputs[0].omissions == (
        "2쪽 표의 병합 셀은 추출되지 않았다",
    )


def test_step_output_never_mints_capabilities_or_host_paths():
    turn = freeze_turn(turn_value())
    accepted = validate_step_output(turn, {
        "kind": "tool_request",
        "tool": "deeptwin_browser",
        "arguments": {"url_ref": "source:1", "action": "read"},
    })
    assert accepted["tool"] == "deeptwin_browser"
    with pytest.raises(GatewayError):
        validate_step_output(turn, {
            "kind": "tool_request", "tool": "local_shell",
            "arguments": {},  # a tool outside the granted set
        })
    for poisoned in (
        {"path": "/etc/passwd"},
        {"file": "../../secrets.env"},
        {"target": "~/private"},
    ):
        with pytest.raises(GatewayError):
            validate_step_output(turn, {
                "kind": "tool_request", "tool": "deeptwin_pdf",
                "arguments": poisoned,
            })
    with pytest.raises(GatewayError):
        # new capability names never become authority
        validate_step_output(turn, {
            "kind": "tool_request", "tool": "deeptwin_pdf",
            "arguments": {}, "capabilities": ["admin"],
        })
    final = validate_step_output(turn, {
        "kind": "final_artifacts",
        "artifacts": [{"slot": "final-script", "media_type": "text/markdown"}],
    })
    assert final["artifacts"][0]["slot"] == "final-script"


def test_no_tool_profiles_refuse_tool_requests_entirely():
    critic = freeze_turn(turn_value(
        profile="critic", inputs=[], granted_tools=[],
    ))
    with pytest.raises(GatewayError):
        validate_step_output(critic, {
            "kind": "tool_request", "tool": "deeptwin_browser",
            "arguments": {},
        })
