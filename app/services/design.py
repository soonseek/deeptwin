"""Confirmed-work and lens-bound functional design contracts.

This layer accepts immutable design data; it does not call a model, execute a graph,
approve an environment, or interpret onboarding as a DeepTwin feedback episode.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from hashlib import sha256
from types import MappingProxyType

from ..domain.graph_schema import GraphContractError, GraphVersion
from ..domain.refs import (
    DomainContractError,
    EntityRef,
    canonical_json,
    positive_integer,
    uuid_string,
)
from ..generation_profiles import DesignGenerationPurpose, design_profile_for
from ..runtime.graph import (
    CompilationAuthority,
    compile_graph,
    structural_diversity_projection,
)
from .lenses import LensDecision, LensRef

WORK_MODEL_SCHEMA_VERSION = "work-model-v1"
WORK_MODEL_CONFIRMATION_SCHEMA_VERSION = "work-model-confirmation-v1"
DESIGN_DECISION_SCHEMA_VERSION = "design-decision-v1"
DESIGN_REQUEST_SCHEMA_VERSION = "design-generation-request-v1"
DESIGN_CANDIDATE_SCHEMA_VERSION = "design-candidate-v1"

CONFIRMED_DIMENSIONS = (
    "authority",
    "completion",
    "goal",
    "risk",
    "suitability",
    "unknowns",
)
DESIGN_SHAPES = frozenset({"single_agent", "deterministic", "multi_agent", "human_only"})
AUTHORITY_EFFECTS = frozenset({"read", "write", "external_effect", "human_approval"})
RISK_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
UNKNOWN_IMPACTS = frozenset({"no_effect", "design", "authority", "safety"})
UNKNOWN_STATES = frozenset({"resolved", "acknowledged", "blocking"})
EFFECT_AXES = frozenset({
    "responsibility",
    "dependency",
    "artifact",
    "memory",
    "permission",
    "approval",
    "evaluation",
    "model",
    "tool",
})
TARGET_COLLECTIONS = MappingProxyType({
    "node": ("nodes", "node_id"),
    "edge": ("edges", "edge_id"),
    "artifact_contract": ("artifact_contracts", "artifact_contract_id"),
    "model_binding": ("model_bindings", "binding_id"),
    "tool_binding": ("tool_bindings", "binding_id"),
    "memory_policy": ("memory_policies", "policy_id"),
    "completion": ("completion_criteria", "criterion_id"),
})

_LOCAL_ID = re.compile(r"[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*\Z")
_QUALIFIED_ID = re.compile(r"[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*\Z")
_MIME = re.compile(r"[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_FIELD_PATH = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){0,7}\Z")
_CONFIRMED_TOKEN = object()
_DECISION_TOKEN = object()
_REQUEST_TOKEN = object()


class WorkModelContractError(ValueError):
    """A work model or its exact confirmation is invalid."""


class DesignContractError(ValueError):
    """A design decision, request, or candidate is invalid."""


def _strict(value, fields, label, error=WorkModelContractError):
    if type(value) is not dict or set(value) != set(fields):
        raise error(f"Expected exact {label}")
    return value


def _list(value, label, maximum, *, minimum=0, error=WorkModelContractError):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise error(f"Expected bounded {label} list")
    return value


def _text(value, label, maximum, *, pattern=None, error=WorkModelContractError):
    if type(value) is not str or not value:
        raise error(f"Expected nonempty {label}")
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise error(f"Invalid {label} Unicode") from exc
    if len(encoded) > maximum or any(ord(character) < 32 or ord(character) == 127
                                     for character in value):
        raise error(f"Invalid or oversized {label}")
    if pattern is not None and pattern.fullmatch(value) is None:
        raise error(f"Invalid {label}")
    return value


def _identifier(value, label, *, qualified=False, error=WorkModelContractError):
    return _text(
        value,
        label,
        128,
        pattern=_QUALIFIED_ID if qualified else _LOCAL_ID,
        error=error,
    )


def _unique(values, key, label, error=WorkModelContractError):
    keys = [key(value) for value in values]
    if len(set(keys)) != len(keys):
        raise error(f"Duplicate {label}")


def _entity_ref(value, kind, label, error=WorkModelContractError):
    try:
        result = EntityRef.from_dict(value)
    except (DomainContractError, TypeError) as exc:
        raise error(f"Invalid {label}") from exc
    if result.kind != kind:
        raise error(f"Invalid {label} kind")
    return result


def _uuid(value, label, error=WorkModelContractError):
    try:
        return uuid_string(value)
    except DomainContractError as exc:
        raise error(f"Invalid {label}") from exc


def _version(value, label="version", error=WorkModelContractError):
    try:
        return positive_integer(value)
    except DomainContractError as exc:
        raise error(f"Invalid {label}") from exc


def _content_ref(kind, identifier, version, value):
    return EntityRef(kind, identifier, version, sha256(canonical_json(value)).hexdigest())


@dataclass(frozen=True, slots=True)
class WorkDeliverable:
    deliverable_id: str
    description: str
    media_types: tuple[str, ...]
    min_items: int
    max_items: int
    max_total_bytes: int

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"deliverable_id", "description", "media_types", "min_items",
                        "max_items", "max_total_bytes"}, "work deliverable")
        media_types = [
            _text(item, "media type", 255, pattern=_MIME)
            for item in _list(value["media_types"], "media types", 16, minimum=1)
        ]
        _unique(media_types, lambda item: item, "media type")
        minimum, maximum, max_bytes = (
            value["min_items"], value["max_items"], value["max_total_bytes"]
        )
        if (type(minimum) is not int or type(maximum) is not int
                or type(max_bytes) is not int or not 0 <= minimum <= maximum <= 1_000
                or not 1 <= max_bytes <= 2 ** 63 - 1):
            raise WorkModelContractError("Invalid deliverable bounds")
        return cls(
            _identifier(value["deliverable_id"], "deliverable ID"),
            _text(value["description"], "deliverable description", 4_096),
            tuple(sorted(media_types)),
            minimum,
            maximum,
            max_bytes,
        )

    def as_dict(self):
        return {
            "deliverable_id": self.deliverable_id,
            "description": self.description,
            "media_types": list(self.media_types),
            "min_items": self.min_items,
            "max_items": self.max_items,
            "max_total_bytes": self.max_total_bytes,
        }


@dataclass(frozen=True, slots=True)
class WorkAuthority:
    authority_id: str
    capability: str
    scope: str
    effect: str

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"authority_id", "capability", "scope", "effect"}, "work authority")
        effect = value["effect"]
        if type(effect) is not str or effect not in AUTHORITY_EFFECTS:
            raise WorkModelContractError("Invalid authority effect")
        return cls(
            _identifier(value["authority_id"], "authority ID"),
            _identifier(value["capability"], "authority capability", qualified=True),
            _text(value["scope"], "authority scope", 2_048),
            effect,
        )

    def as_dict(self):
        return {
            "authority_id": self.authority_id,
            "capability": self.capability,
            "scope": self.scope,
            "effect": self.effect,
        }


@dataclass(frozen=True, slots=True)
class WorkRisk:
    risk_id: str
    description: str
    severity: str
    mitigation_required: bool

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"risk_id", "description", "severity", "mitigation_required"},
                "work risk")
        if type(value["severity"]) is not str or value["severity"] not in RISK_SEVERITIES:
            raise WorkModelContractError("Invalid risk severity")
        if type(value["mitigation_required"]) is not bool:
            raise WorkModelContractError("Invalid risk mitigation requirement")
        return cls(
            _identifier(value["risk_id"], "risk ID"),
            _text(value["description"], "risk description", 4_096),
            value["severity"],
            value["mitigation_required"],
        )

    def as_dict(self):
        return {
            "risk_id": self.risk_id,
            "description": self.description,
            "severity": self.severity,
            "mitigation_required": self.mitigation_required,
        }


@dataclass(frozen=True, slots=True)
class WorkUnknown:
    unknown_id: str
    question: str
    impact: str
    status: str

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"unknown_id", "question", "impact", "status"}, "work unknown")
        if type(value["impact"]) is not str or value["impact"] not in UNKNOWN_IMPACTS:
            raise WorkModelContractError("Invalid unknown impact")
        if type(value["status"]) is not str or value["status"] not in UNKNOWN_STATES:
            raise WorkModelContractError("Invalid unknown status")
        return cls(
            _identifier(value["unknown_id"], "unknown ID"),
            _text(value["question"], "unknown question", 4_096),
            value["impact"],
            value["status"],
        )

    def as_dict(self):
        return {
            "unknown_id": self.unknown_id,
            "question": self.question,
            "impact": self.impact,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class WorkSuitability:
    recommended_shape: str
    rationale: str
    evidence_refs: tuple[EntityRef, ...]

    @classmethod
    def from_untrusted(cls, value):
        _strict(value, {"recommended_shape", "rationale", "evidence_refs"},
                "work suitability")
        shape = value["recommended_shape"]
        if type(shape) is not str or shape not in DESIGN_SHAPES:
            raise WorkModelContractError("Invalid design suitability")
        evidence = [
            _entity_ref(item, "source", "suitability evidence")
            for item in _list(value["evidence_refs"], "suitability evidence", 32, minimum=1)
        ]
        _unique(evidence, lambda item: (item.kind, item.id, item.version, item.sha256),
                "suitability evidence")
        return cls(shape, _text(value["rationale"], "suitability rationale", 4_096),
                   tuple(sorted(evidence, key=lambda item: item.as_dict()["id"])))

    def as_dict(self):
        return {
            "recommended_shape": self.recommended_shape,
            "rationale": self.rationale,
            "evidence_refs": [item.as_dict() for item in self.evidence_refs],
        }


@dataclass(frozen=True, slots=True)
class WorkModel:
    schema_version: str
    work_model_id: str
    version: int
    work_revision_ref: EntityRef
    semantic_origin: str
    goals: tuple[str, ...]
    deliverables: tuple[WorkDeliverable, ...]
    completion_conditions: tuple[str, ...]
    authorities: tuple[WorkAuthority, ...]
    risks: tuple[WorkRisk, ...]
    unknowns: tuple[WorkUnknown, ...]
    suitability: WorkSuitability
    source_refs: tuple[EntityRef, ...]

    @classmethod
    def from_untrusted(cls, value):
        fields = {
            "schema_version", "work_model_id", "version", "work_revision_ref",
            "semantic_origin", "goals", "deliverables", "completion_conditions",
            "authorities", "risks", "unknowns", "suitability", "source_refs",
        }
        _strict(value, fields, "work model")
        if value["schema_version"] != WORK_MODEL_SCHEMA_VERSION:
            raise WorkModelContractError("Unsupported work model schema")
        if value["semantic_origin"] != "work_understanding":
            raise WorkModelContractError("Work model must originate from work understanding")
        goals = [
            _text(item, "work goal", 4_096)
            for item in _list(value["goals"], "work goals", 32, minimum=1)
        ]
        completions = [
            _text(item, "completion condition", 4_096)
            for item in _list(value["completion_conditions"], "completion conditions", 64,
                              minimum=1)
        ]
        deliverables = [
            WorkDeliverable.from_untrusted(item)
            for item in _list(value["deliverables"], "work deliverables", 64, minimum=1)
        ]
        authorities = [
            WorkAuthority.from_untrusted(item)
            for item in _list(value["authorities"], "work authorities", 128)
        ]
        risks = [
            WorkRisk.from_untrusted(item)
            for item in _list(value["risks"], "work risks", 128)
        ]
        unknowns = [
            WorkUnknown.from_untrusted(item)
            for item in _list(value["unknowns"], "work unknowns", 128)
        ]
        source_refs = [
            _entity_ref(item, "source", "work source")
            for item in _list(value["source_refs"], "work sources", 256, minimum=1)
        ]
        suitability = WorkSuitability.from_untrusted(value["suitability"])
        _unique(goals, lambda item: item, "work goal")
        _unique(completions, lambda item: item, "completion condition")
        _unique(deliverables, lambda item: item.deliverable_id, "deliverable ID")
        _unique(authorities, lambda item: item.authority_id, "authority ID")
        _unique(risks, lambda item: item.risk_id, "risk ID")
        _unique(unknowns, lambda item: item.unknown_id, "unknown ID")
        _unique(source_refs, lambda item: (item.id, item.version, item.sha256), "source ref")
        source_keys = {(item.id, item.version, item.sha256) for item in source_refs}
        if any((item.id, item.version, item.sha256) not in source_keys
               for item in suitability.evidence_refs):
            raise WorkModelContractError("Suitability evidence is outside the work sources")
        return cls(
            WORK_MODEL_SCHEMA_VERSION,
            _uuid(value["work_model_id"], "work model ID"),
            _version(value["version"]),
            _entity_ref(value["work_revision_ref"], "work_revision", "work revision"),
            "work_understanding",
            tuple(goals),
            tuple(deliverables),
            tuple(completions),
            tuple(authorities),
            tuple(risks),
            tuple(unknowns),
            suitability,
            tuple(sorted(source_refs, key=lambda item: (item.id, item.version, item.sha256))),
        )

    def as_dict(self):
        return {
            "schema_version": self.schema_version,
            "work_model_id": self.work_model_id,
            "version": self.version,
            "work_revision_ref": self.work_revision_ref.as_dict(),
            "semantic_origin": self.semantic_origin,
            "goals": list(self.goals),
            "deliverables": [item.as_dict() for item in self.deliverables],
            "completion_conditions": list(self.completion_conditions),
            "authorities": [item.as_dict() for item in self.authorities],
            "risks": [item.as_dict() for item in self.risks],
            "unknowns": [item.as_dict() for item in self.unknowns],
            "suitability": self.suitability.as_dict(),
            "source_refs": [item.as_dict() for item in self.source_refs],
        }


@dataclass(frozen=True, slots=True, init=False)
class ConfirmedWorkTarget:
    work_model: WorkModel
    work_model_ref: EntityRef
    state: str
    confirmed_dimensions: tuple[str, ...]
    confirmed_by: EntityRef | None
    confirmation_ref: EntityRef | None
    _issuer_token: object = field(repr=False, compare=False)

    @property
    def design_disposition(self):
        return self.work_model.suitability.recommended_shape

    @property
    def blocked_unknown_ids(self):
        return tuple(sorted(item.unknown_id for item in self.work_model.unknowns
                            if item.status == "blocking"))


def _target(*, model, state, dimensions=(), confirmed_by=None, confirmation_ref=None, token=None):
    value = object.__new__(ConfirmedWorkTarget)
    for name, item in {
        "work_model": model,
        "work_model_ref": _content_ref(
            "work_model", model.work_model_id, model.version, model.as_dict()
        ),
        "state": state,
        "confirmed_dimensions": tuple(dimensions),
        "confirmed_by": confirmed_by,
        "confirmation_ref": confirmation_ref,
        "_issuer_token": token,
    }.items():
        object.__setattr__(value, name, item)
    return value


def confirm_work_model(work_model, confirmation):
    """Parse a work model, or bind an exact all-dimension human confirmation."""
    try:
        model = WorkModel.from_untrusted(work_model)
        prepared = _target(model=model, state="unconfirmed")
        if confirmation is None:
            return prepared
        fields = {
            "schema_version", "confirmation_id", "version", "work_model_ref",
            "confirmed_dimensions", "confirmed_by", "decision",
        }
        _strict(confirmation, fields, "work model confirmation")
        if confirmation["schema_version"] != WORK_MODEL_CONFIRMATION_SCHEMA_VERSION:
            raise WorkModelContractError("Unsupported work model confirmation")
        supplied_ref = _entity_ref(
            confirmation["work_model_ref"], "work_model", "confirmed work model"
        )
        if supplied_ref != prepared.work_model_ref:
            raise WorkModelContractError("Confirmation does not target the exact work model")
        dimensions = _list(
            confirmation["confirmed_dimensions"], "confirmation dimensions", 6, minimum=6
        )
        if tuple(dimensions) != CONFIRMED_DIMENSIONS:
            raise WorkModelContractError("Confirmation dimensions must be exact and complete")
        if confirmation["decision"] != "accepted":
            raise WorkModelContractError("Work model confirmation must be explicitly accepted")
        identifier = _uuid(confirmation["confirmation_id"], "confirmation ID")
        version = _version(confirmation["version"])
        actor = _entity_ref(confirmation["confirmed_by"], "actor", "confirming actor")
        normalized = {
            "schema_version": WORK_MODEL_CONFIRMATION_SCHEMA_VERSION,
            "confirmation_id": identifier,
            "version": version,
            "work_model_ref": supplied_ref.as_dict(),
            "confirmed_dimensions": list(CONFIRMED_DIMENSIONS),
            "confirmed_by": actor.as_dict(),
            "decision": "accepted",
        }
        return _target(
            model=model,
            state="confirmed",
            dimensions=CONFIRMED_DIMENSIONS,
            confirmed_by=actor,
            confirmation_ref=_content_ref("decision_record", identifier, version, normalized),
            token=_CONFIRMED_TOKEN,
        )
    except WorkModelContractError:
        raise
    except (DomainContractError, KeyError, TypeError, ValueError) as exc:
        raise WorkModelContractError("Invalid work model or confirmation") from exc


def _require_confirmed(target):
    if (type(target) is not ConfirmedWorkTarget or target.state != "confirmed"
            or target._issuer_token is not _CONFIRMED_TOKEN
            or target.confirmation_ref is None):
        raise DesignContractError("An exact confirmed work target is required")


@dataclass(frozen=True, slots=True)
class EffectTarget:
    kind: str
    identifier: str
    field_path: str

    def as_dict(self):
        return {"kind": self.kind, "id": self.identifier, "field": self.field_path}


@dataclass(frozen=True, slots=True)
class ProposedEffect:
    effect_id: str
    axis: str
    target: EffectTarget
    expected_value_sha256: str
    rationale: str
    contributing_lens_refs: tuple[str, ...]

    def as_dict(self):
        return {
            "effect_id": self.effect_id,
            "axis": self.axis,
            "target": self.target.as_dict(),
            "expected_value_sha256": self.expected_value_sha256,
            "rationale": self.rationale,
            "contributing_lens_refs": list(self.contributing_lens_refs),
        }


@dataclass(frozen=True, slots=True, init=False)
class FunctionalDesignDecision:
    decision_id: str
    version: int
    work_model_ref: EntityRef
    lens_decisions: tuple[LensDecision, ...]
    functional_claims: tuple[str, ...]
    proposed_effects: tuple[ProposedEffect, ...]
    conflicts: tuple[str, ...]
    abstentions: tuple[str, ...]
    _issuer_token: object = field(repr=False, compare=False)

    @property
    def atomic_lens_refs(self):
        return tuple(sorted((item.lens_ref for item in self.lens_decisions), key=str))

    def as_dict(self):
        return {
            "schema_version": DESIGN_DECISION_SCHEMA_VERSION,
            "decision_id": self.decision_id,
            "version": self.version,
            "work_model_ref": self.work_model_ref.as_dict(),
            "lens_decisions": [item.as_audit_dict() for item in self.lens_decisions],
            "functional_claims": list(self.functional_claims),
            "proposed_effects": [item.as_dict() for item in self.proposed_effects],
            "conflicts": list(self.conflicts),
            "abstentions": list(self.abstentions),
        }

    @property
    def decision_ref(self):
        return _content_ref(
            "design_decision", self.decision_id, self.version, self.as_dict()
        )


def _parse_effect(value, allowed_lenses):
    _strict(
        value,
        {"effect_id", "axis", "target", "expected_value_sha256", "rationale",
         "contributing_lens_refs"},
        "proposed effect",
        DesignContractError,
    )
    axis = value["axis"]
    if type(axis) is not str or axis not in EFFECT_AXES:
        raise DesignContractError("Invalid effect axis")
    target = _strict(
        value["target"], {"kind", "id", "field"}, "effect target", DesignContractError
    )
    kind = target["kind"]
    if type(kind) is not str or kind not in TARGET_COLLECTIONS:
        raise DesignContractError("Invalid effect target kind")
    field_path = _text(
        target["field"], "effect target field", 256,
        pattern=_FIELD_PATH, error=DesignContractError,
    )
    digest = value["expected_value_sha256"]
    if type(digest) is not str or _HASH.fullmatch(digest) is None:
        raise DesignContractError("Invalid expected effect digest")
    lens_refs = [
        _text(item, "contributing lens ref", 256, error=DesignContractError)
        for item in _list(value["contributing_lens_refs"], "contributing lens refs", 16,
                          minimum=1, error=DesignContractError)
    ]
    _unique(lens_refs, lambda item: item, "contributing lens ref", DesignContractError)
    if not set(lens_refs) <= allowed_lenses:
        raise DesignContractError("Effect cites a lens outside the qualified decision set")
    return ProposedEffect(
        _identifier(value["effect_id"], "effect ID", error=DesignContractError),
        axis,
        EffectTarget(
            kind,
            _identifier(target["id"], "effect target ID", error=DesignContractError),
            field_path,
        ),
        digest,
        _text(value["rationale"], "effect rationale", 4_096, error=DesignContractError),
        tuple(sorted(lens_refs)),
    )


def accept_design_decision(target, lens_decisions: Iterable[LensDecision], value):
    _require_confirmed(target)
    try:
        decisions = tuple(lens_decisions)
    except TypeError as exc:
        raise DesignContractError("A bounded lens decision list is required") from exc
    if not 1 <= len(decisions) <= 16:
        raise DesignContractError("At least one qualified proposed lens decision is required")
    if any(type(item) is not LensDecision for item in decisions):
        raise DesignContractError("Invalid lens decision")
    _unique(decisions, lambda item: str(item.lens_ref), "lens decision", DesignContractError)
    for item in decisions:
        if (item.state != "proposed" or item.path != "initial_design"
                or item.qualification_status != "qualified"
                or item.scope_hash != target.work_model_ref.sha256
                or not isinstance(item.lens_ref, LensRef)):
            raise DesignContractError("Lens decision is not qualified for the confirmed target")

    fields = {
        "decision_id", "version", "functional_claims", "proposed_effects",
        "conflicts", "abstentions",
    }
    _strict(value, fields, "design decision", DesignContractError)
    claims = [
        _text(item, "functional claim", 4_096, error=DesignContractError)
        for item in _list(value["functional_claims"], "functional claims", 32,
                          minimum=1, error=DesignContractError)
    ]
    _unique(claims, lambda item: item, "functional claim", DesignContractError)
    allowed_lenses = {str(item.lens_ref) for item in decisions}
    effects = [
        _parse_effect(item, allowed_lenses)
        for item in _list(value["proposed_effects"], "proposed effects", 64,
                          minimum=1, error=DesignContractError)
    ]
    _unique(effects, lambda item: item.effect_id, "effect ID", DesignContractError)
    contributed = {lens_ref for effect in effects for lens_ref in effect.contributing_lens_refs}
    if contributed != allowed_lenses:
        raise DesignContractError("Every qualified lens must have an explicit proposed effect")

    def notes(name):
        items = [
            _text(item, name, 4_096, error=DesignContractError)
            for item in _list(value[name], name, 32, error=DesignContractError)
        ]
        _unique(items, lambda item: item, name, DesignContractError)
        return tuple(items)

    result = object.__new__(FunctionalDesignDecision)
    for name, item in {
        "decision_id": _uuid(value["decision_id"], "design decision ID", DesignContractError),
        "version": _version(value["version"], error=DesignContractError),
        "work_model_ref": target.work_model_ref,
        "lens_decisions": tuple(sorted(decisions, key=lambda entry: str(entry.lens_ref))),
        "functional_claims": tuple(claims),
        "proposed_effects": tuple(effects),
        "conflicts": notes("conflicts"),
        "abstentions": notes("abstentions"),
        "_issuer_token": _DECISION_TOKEN,
    }.items():
        object.__setattr__(result, name, item)
    return result


@dataclass(frozen=True, slots=True, init=False)
class DesignGenerationRequest:
    request_id: str
    version: int
    work_target: ConfirmedWorkTarget
    decisions: tuple[FunctionalDesignDecision, ...]
    requested_candidate_count: int
    design_disposition: str
    decision_profile_digest: str
    candidate_profile_digest: str
    compilation_authority: CompilationAuthority = field(repr=False, compare=False)
    _issuer_token: object = field(repr=False, compare=False)

    def as_dict(self):
        return {
            "schema_version": DESIGN_REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "version": self.version,
            "work_model_ref": self.work_target.work_model_ref.as_dict(),
            "confirmation_ref": self.work_target.confirmation_ref.as_dict(),
            "decision_refs": [item.decision_ref.as_dict() for item in self.decisions],
            "requested_candidate_count": self.requested_candidate_count,
            "design_disposition": self.design_disposition,
            "decision_profile_digest": self.decision_profile_digest,
            "candidate_profile_digest": self.candidate_profile_digest,
            "compilation_authority_digest": self.compilation_authority.digest,
        }

    @property
    def request_ref(self):
        return _content_ref("decision_record", self.request_id, self.version, self.as_dict())


def create_generation_request(
    target,
    decisions: Iterable[FunctionalDesignDecision],
    *,
    request_id,
    requested_candidate_count,
    compilation_authority,
):
    _require_confirmed(target)
    if target.blocked_unknown_ids:
        raise DesignContractError("A blocking unknown prevents design generation")
    try:
        items = tuple(decisions)
    except TypeError as exc:
        raise DesignContractError("A bounded design decision list is required") from exc
    if not 1 <= len(items) <= 16:
        raise DesignContractError("At least one design decision is required")
    if any(type(item) is not FunctionalDesignDecision
           or item._issuer_token is not _DECISION_TOKEN
           or item.work_model_ref != target.work_model_ref for item in items):
        raise DesignContractError("Design decisions must belong to the confirmed work model")
    _unique(items, lambda item: item.decision_ref.as_dict()["id"], "design decision",
            DesignContractError)
    if type(requested_candidate_count) is not int or not 1 <= requested_candidate_count <= 6:
        raise DesignContractError("Initial candidate count must be between one and six")
    if type(compilation_authority) is not CompilationAuthority:
        raise DesignContractError("A trusted compilation authority snapshot is required")
    result = object.__new__(DesignGenerationRequest)
    values = {
        "request_id": _uuid(request_id, "generation request ID", DesignContractError),
        "version": 1,
        "work_target": target,
        "decisions": tuple(sorted(items, key=lambda item: item.decision_ref.id)),
        "requested_candidate_count": requested_candidate_count,
        "design_disposition": target.design_disposition,
        "decision_profile_digest": design_profile_for(
            DesignGenerationPurpose.DESIGN_DECISION
        ).digest,
        "candidate_profile_digest": design_profile_for(
            DesignGenerationPurpose.DESIGN_CANDIDATE
        ).digest,
        "compilation_authority": compilation_authority,
        "_issuer_token": _REQUEST_TOKEN,
    }
    for name, item in values.items():
        object.__setattr__(result, name, item)
    return result


@dataclass(frozen=True, slots=True)
class DesignCandidate:
    candidate_id: str
    version: int
    generation_request_ref: EntityRef
    work_model_ref: EntityRef
    decision_refs: tuple[EntityRef, ...]
    parent_candidate_refs: tuple[EntityRef, ...]
    generation_call_refs: tuple[EntityRef, ...]
    graph: GraphVersion
    graph_ref: EntityRef
    applied_effect_ids: tuple[str, ...]
    audit_lens_refs: tuple[str, ...]

    def as_dict(self):
        return {
            "schema_version": DESIGN_CANDIDATE_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "version": self.version,
            "generation_request_ref": self.generation_request_ref.as_dict(),
            "work_model_ref": self.work_model_ref.as_dict(),
            "decision_refs": [item.as_dict() for item in self.decision_refs],
            "parent_candidate_refs": [item.as_dict() for item in self.parent_candidate_refs],
            "generation_call_refs": [item.as_dict() for item in self.generation_call_refs],
            "graph_ref": self.graph_ref.as_dict(),
            "applied_effect_ids": list(self.applied_effect_ids),
            "audit_lens_refs": list(self.audit_lens_refs),
        }

    @property
    def candidate_ref(self):
        return _content_ref("design_candidate", self.candidate_id, self.version, self.as_dict())


def _resolve_effect(graph_value, target):
    collection_name, identity_name = TARGET_COLLECTIONS[target.kind]
    matches = [item for item in graph_value[collection_name]
               if item.get(identity_name) == target.identifier]
    if len(matches) != 1:
        raise DesignContractError("A proposed effect target is absent or ambiguous")
    current = matches[0]
    for part in target.field_path.split("."):
        if type(current) is not dict or part not in current:
            raise DesignContractError("A proposed effect field is absent")
        current = current[part]
    return current


def _validate_shape(request, graph):
    agents = sum(node.kind == "agent" for node in graph.nodes)
    disposition = request.design_disposition
    if disposition == "multi_agent" and agents < 2:
        raise DesignContractError("Graph does not honor multi-agent suitability")
    if disposition == "single_agent" and agents != 1:
        raise DesignContractError("Graph does not honor single-agent suitability")
    if disposition == "deterministic" and agents != 0:
        raise DesignContractError("Graph does not honor deterministic suitability")
    if disposition == "human_only":
        raise DesignContractError("Human-only suitability cannot be replaced by a generated graph")


def _accept_candidate(request, value):
    fields = {
        "schema_version", "candidate_id", "version", "generation_request_ref",
        "parent_candidate_refs", "generation_call_refs", "graph",
    }
    _strict(value, fields, "design candidate", DesignContractError)
    if value["schema_version"] != DESIGN_CANDIDATE_SCHEMA_VERSION:
        raise DesignContractError("Unsupported design candidate schema")
    request_ref = _entity_ref(
        value["generation_request_ref"], "decision_record", "generation request",
        DesignContractError,
    )
    if request_ref != request.request_ref:
        raise DesignContractError("Candidate belongs to a different generation request")
    parents = [
        _entity_ref(item, "design_candidate", "parent candidate", DesignContractError)
        for item in _list(value["parent_candidate_refs"], "parent candidate refs", 32,
                          error=DesignContractError)
    ]
    calls = [
        _entity_ref(item, "decision_record", "generation call", DesignContractError)
        for item in _list(value["generation_call_refs"], "generation call refs", 32,
                          minimum=1, error=DesignContractError)
    ]
    _unique(parents, lambda item: (item.id, item.version, item.sha256), "parent candidate",
            DesignContractError)
    _unique(calls, lambda item: (item.id, item.version, item.sha256), "generation call",
            DesignContractError)
    try:
        graph = GraphVersion.from_untrusted(value["graph"])
        compiled = compile_graph(graph, request.compilation_authority)
    except GraphContractError as exc:
        raise DesignContractError("Candidate graph violates the functional graph contract") from exc
    if graph.work_model_ref != request.work_target.work_model_ref:
        raise DesignContractError("Candidate graph targets a different work model")
    expected_decisions = tuple(item.decision_ref for item in request.decisions)
    if tuple(sorted(graph.decision_refs, key=lambda item: item.id)) != tuple(
        sorted(expected_decisions, key=lambda item: item.id)
    ):
        raise DesignContractError("Candidate graph does not bind the exact design decisions")
    _validate_shape(request, graph)
    graph_value = graph.as_dict()
    effects = tuple(effect for decision in request.decisions
                    for effect in decision.proposed_effects)
    for effect in effects:
        actual = _resolve_effect(graph_value, effect.target)
        if sha256(canonical_json(actual)).hexdigest() != effect.expected_value_sha256:
            raise DesignContractError("Candidate does not realize a declared lens effect")
    graph_ref = EntityRef("graph", graph.graph_id, graph.version, compiled.graph_digest)
    lens_refs = tuple(sorted({str(lens.lens_ref) for decision in request.decisions
                              for lens in decision.lens_decisions}))
    return DesignCandidate(
        _uuid(value["candidate_id"], "candidate ID", DesignContractError),
        _version(value["version"], error=DesignContractError),
        request_ref,
        graph.work_model_ref,
        tuple(sorted(graph.decision_refs, key=lambda item: item.id)),
        tuple(sorted(parents, key=lambda item: item.id)),
        tuple(sorted(calls, key=lambda item: item.id)),
        graph,
        graph_ref,
        tuple(effect.effect_id for effect in effects),
        lens_refs,
    )


def accept_design_candidates(request, values):
    if type(request) is not DesignGenerationRequest or request._issuer_token is not _REQUEST_TOKEN:
        raise DesignContractError("A framework-issued design generation request is required")
    candidates = _list(values, "design candidates", request.requested_candidate_count,
                       minimum=1, error=DesignContractError)
    accepted = tuple(_accept_candidate(request, item) for item in candidates)
    _unique(accepted, lambda item: item.candidate_id, "candidate ID", DesignContractError)
    projections = [sha256(canonical_json(structural_diversity_projection(item.graph))).hexdigest()
                   for item in accepted]
    if len(set(projections)) != len(projections):
        raise DesignContractError("Candidate batch contains a functionally duplicate graph")
    return accepted


__all__ = [
    "ConfirmedWorkTarget",
    "DesignCandidate",
    "DesignContractError",
    "DesignGenerationRequest",
    "FunctionalDesignDecision",
    "WorkModel",
    "WorkModelContractError",
    "accept_design_candidates",
    "accept_design_decision",
    "confirm_work_model",
    "create_generation_request",
]
