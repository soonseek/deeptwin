"""Provider-neutral frozen turns and step-output authority (US3, T042 part).

A :class:`FrozenTurn` binds one model step completely before transport:
work/environment/node/execution/attempt identity, the provider path,
catalog/model/effort, the instruction-profile digest, the ALLOWLISTED typed
input parts, the output schema, runtime-profile qualification, deadline,
budget and consent. Inputs are constructed from the profile's allowlist —
never an arbitrary object with selected keys blacklisted. Non-text parts
(actual page, image, table) carry an explicit marker binding them to their
artifact, and extraction omissions are declared on the part, never hidden
(R06). Step-output parsing never accepts new capability names or arbitrary
host paths as execution authority: tool requests exist only for the
execution profile, only for tools the turn granted, and only with path-free
arguments (runtime.md §1). Values are issued, never constructed. Transport
itself (the actual provider adapters and the Codex tool-step bridge) stays
a separate concern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..domain.refs import DomainContractError, EntityRef

PROVIDERS = frozenset({"claude_api", "codex_subscription", "codex_api"})
EFFORTS = frozenset({"low", "medium", "high"})
PART_TYPES = frozenset({"text", "image", "page", "table"})
# Inputs are allowlisted per profile; the critic's six-field boundary
# carries no domain refs at all.
GATEWAY_PROFILES: dict[str, frozenset[str]] = {
    "understanding": frozenset({"work_revision", "source", "extraction"}),
    "design": frozenset({"work_model", "design_decision"}),
    "critic": frozenset(),
    "execution-model-step": frozenset({"artifact", "handoff"}),
    "diagnosis": frozenset({
        "original_execution", "own_alternative", "artifact",
    }),
    "inquiry": frozenset({
        "difference", "hypothesis", "comparison_result", "artifact",
    }),
    "change-compiler-input": frozenset({
        "hypothesis", "comparison_result", "change_candidate",
    }),
    "sealed-evaluator": frozenset({
        "artifact", "evaluation_dataset", "rubric",
    }),
}
_TOOL_PROFILES = frozenset({"execution-model-step"})
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z"
)
_HOST_PATH = re.compile(r"(^[/~])|(\.\./)|(^\.\.$)")
_ISSUE_TOKEN = object()


class GatewayError(ValueError):
    """A frozen turn or a step output is invalid or over-authorized."""


def _issue(cls, **fields):
    value = object.__new__(cls)
    for name, item in fields.items():
        object.__setattr__(value, name, item)
    return value


def _ref(value, kinds, label):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise GatewayError(f"invalid {label} reference") from exc
    if result.kind not in kinds:
        raise GatewayError(f"invalid {label} reference kind")
    return result


def _text(value, label, maximum=128):
    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= maximum:
        raise GatewayError(f"{label} is out of bounds")
    return value


@dataclass(frozen=True, slots=True, init=False)
class InputPart:
    """One typed input part; non-text parts carry their binding marker."""

    part_type: str
    ref: EntityRef
    marker: str | None
    omissions: tuple[str, ...]


@dataclass(frozen=True, slots=True, init=False)
class FrozenTurn:
    """One completely bound model step; transport carries it verbatim."""

    profile: str
    work_ref: EntityRef
    environment_ref: EntityRef
    node_id: str
    execution_id: str
    attempt_index: int
    provider: str
    account_id: str
    catalog_ref: EntityRef
    model_id: str
    effort: str
    instruction_profile_digest: str
    inputs: tuple[InputPart, ...]
    granted_tools: tuple[str, ...]
    output_schema_id: str
    runtime_profile_ref: EntityRef
    deadline_seconds: int
    budget_ref: EntityRef
    consent_ref: EntityRef
    _issuer_token: object = field(repr=False, compare=False)


def _parse_part(value, allowed_kinds) -> InputPart:
    if type(value) is not dict or set(value) != {
        "type", "ref", "marker", "omissions",
    }:
        raise GatewayError("expected the exact input part object")
    part_type = value["type"]
    if part_type not in PART_TYPES:
        raise GatewayError("unknown input part type")
    ref = _ref(value["ref"], allowed_kinds, "input part")
    marker = value["marker"]
    if part_type == "text":
        if marker is not None:
            raise GatewayError("a text part carries no marker")
    elif type(marker) is not str or not 1 <= len(marker.encode("utf-8")) <= 256:
        # The actual page/image/table is bound to its artifact through an
        # explicit marker — never an unlabeled blob (R04–R06).
        raise GatewayError("a non-text part requires its binding marker")
    omissions = value["omissions"]
    if (
        type(omissions) is not list or len(omissions) > 32
        or any(
            type(item) is not str
            or not 1 <= len(item.encode("utf-8")) <= 1_024
            for item in omissions
        )
    ):
        raise GatewayError("part omissions are out of bounds")
    return _issue(
        InputPart,
        part_type=part_type,
        ref=ref,
        marker=marker,
        omissions=tuple(omissions),
    )


def freeze_turn(value) -> FrozenTurn:
    """Bind one model step completely, from the profile's allowlist."""

    if type(value) is not dict or set(value) != {
        "profile", "work_ref", "environment_ref", "node_id", "execution_id",
        "attempt_index", "provider", "account_id", "catalog_ref", "model_id",
        "effort", "instruction_profile_digest", "inputs", "granted_tools",
        "output_schema_id", "runtime_profile_ref", "deadline_seconds",
        "budget_ref", "consent_ref",
    }:
        raise GatewayError("expected the exact frozen turn object")
    profile = value["profile"]
    if profile not in GATEWAY_PROFILES:
        raise GatewayError("unknown gateway profile")
    allowed_kinds = GATEWAY_PROFILES[profile]
    provider = value["provider"]
    if provider not in PROVIDERS:
        # A provider is a transport, never a fallback decision: unknown or
        # "free fallback" paths do not exist.
        raise GatewayError("unknown provider path")
    effort = value["effort"]
    if effort not in EFFORTS:
        raise GatewayError("unknown effort level")
    execution_id = value["execution_id"]
    if type(execution_id) is not str or _UUID.fullmatch(execution_id) is None:
        raise GatewayError("execution id is not a canonical UUID")
    attempt_index = value["attempt_index"]
    if type(attempt_index) is not int or not 0 <= attempt_index <= 1_000:
        raise GatewayError("attempt index is out of bounds")
    digest = value["instruction_profile_digest"]
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        raise GatewayError("instruction profile digest is invalid")
    deadline = value["deadline_seconds"]
    if type(deadline) is not int or not 1 <= deadline <= 86_400:
        raise GatewayError("the deadline is out of bounds")
    inputs_value = value["inputs"]
    if type(inputs_value) is not list or len(inputs_value) > 128:
        raise GatewayError("turn inputs are out of bounds")
    inputs = tuple(_parse_part(item, allowed_kinds) for item in inputs_value)
    tools_value = value["granted_tools"]
    if (
        type(tools_value) is not list or len(tools_value) > 32
        or any(type(item) is not str for item in tools_value)
        or len(set(tools_value)) != len(tools_value)
    ):
        raise GatewayError("granted tools are out of bounds")
    if tools_value and profile not in _TOOL_PROFILES:
        # A no-tool profile stays no-tool even when an execution profile
        # gains tools; qualification is profile-version-specific.
        raise GatewayError(f"the {profile} profile never carries tools")
    return _issue(
        FrozenTurn,
        profile=profile,
        work_ref=_ref(value["work_ref"], {"work_revision"}, "work"),
        environment_ref=_ref(
            value["environment_ref"], {"environment"}, "environment",
        ),
        node_id=_text(value["node_id"], "node id"),
        execution_id=execution_id,
        attempt_index=attempt_index,
        provider=provider,
        account_id=_text(value["account_id"], "account id"),
        catalog_ref=_ref(value["catalog_ref"], {"model_catalog"}, "catalog"),
        model_id=_text(value["model_id"], "model id"),
        effort=effort,
        instruction_profile_digest=digest,
        inputs=inputs,
        granted_tools=tuple(tools_value),
        output_schema_id=_text(value["output_schema_id"], "output schema id"),
        runtime_profile_ref=_ref(
            value["runtime_profile_ref"], {"runtime_profile"},
            "runtime profile",
        ),
        deadline_seconds=deadline,
        budget_ref=_ref(value["budget_ref"], {"budget_policy"}, "budget"),
        consent_ref=_ref(value["consent_ref"], {"run_consent"}, "consent"),
        _issuer_token=_ISSUE_TOKEN,
    )


def _scan_for_host_paths(value, label) -> None:
    if type(value) is str:
        if _HOST_PATH.search(value):
            # An arbitrary host path in model output never becomes
            # execution authority.
            raise GatewayError(f"{label} carries a host path")
        return
    if type(value) is dict:
        if len(value) > 64:
            raise GatewayError(f"{label} is out of bounds")
        for key, item in value.items():
            if type(key) is not str:
                raise GatewayError(f"{label} keys must be text")
            _scan_for_host_paths(item, label)
        return
    if type(value) is list:
        if len(value) > 128:
            raise GatewayError(f"{label} is out of bounds")
        for item in value:
            _scan_for_host_paths(item, label)
        return
    if value is not None and type(value) not in (int, bool, float):
        raise GatewayError(f"{label} carries an unknown value type")


def validate_step_output(turn, output) -> dict:
    """Admit one parsed step output without minting any new authority."""

    if (
        type(turn) is not FrozenTurn
        or getattr(turn, "_issuer_token", None) is not _ISSUE_TOKEN
    ):
        raise GatewayError("a frozen turn is required")
    if type(output) is not dict:
        raise GatewayError("expected the parsed step output object")
    if not {"kind"} <= set(output):
        raise GatewayError("the step output declares no kind")
    for forbidden in ("capabilities", "grants", "permissions", "paths"):
        if forbidden in output:
            # Output parsing never accepts new capability names.
            raise GatewayError(
                "step output can never mint capabilities or grants"
            )
    kind = output["kind"]
    if kind == "tool_request":
        if set(output) != {"kind", "tool", "arguments"}:
            raise GatewayError("expected the exact tool request object")
        if turn.profile not in _TOOL_PROFILES:
            raise GatewayError(
                f"the {turn.profile} profile never requests tools"
            )
        tool = output["tool"]
        if tool not in turn.granted_tools:
            # Only the tools this exact turn granted exist at all.
            raise GatewayError("the tool is outside this turn's grants")
        arguments = output["arguments"]
        if type(arguments) is not dict:
            raise GatewayError("tool arguments must be an object")
        _scan_for_host_paths(arguments, "tool arguments")
        return {"kind": kind, "tool": tool, "arguments": arguments}
    if kind == "final_artifacts":
        if set(output) != {"kind", "artifacts"}:
            raise GatewayError("expected the exact final artifacts object")
        artifacts = output["artifacts"]
        if type(artifacts) is not list or not 1 <= len(artifacts) <= 32:
            raise GatewayError("final artifacts are out of bounds")
        for item in artifacts:
            if type(item) is not dict or set(item) != {"slot", "media_type"}:
                raise GatewayError("a final artifact spec is malformed")
            _text(item["slot"], "artifact slot")
            _text(item["media_type"], "artifact media type")
        return {"kind": kind, "artifacts": artifacts}
    raise GatewayError("unknown step output kind")


__all__ = [
    "EFFORTS",
    "GATEWAY_PROFILES",
    "PART_TYPES",
    "PROVIDERS",
    "FrozenTurn",
    "GatewayError",
    "InputPart",
    "freeze_turn",
    "validate_step_output",
]
