"""Design requests the owner creates from a confirmed work model, and their restoration
after a restart (T038; FR-005).

A `DesignGenerationRequest` is issued only over an exact confirmed work target, at least
one functional design decision bound to QUALIFIED lens decisions, and a trusted
compilation authority. Those issuance inputs are in-process capabilities: they cannot be
stored and trusted back. This module therefore persists the request's *basis* — the
evidence each lens decision was issued from, the functional decision's exact content, the
exact compilation authority and the requested count — as one immutable
`design_request_basis` record parented to the request record, and rebuilds a request only
by re-running every issuing gate over stored, verified records:

- the confirmed target from the stored work model and the owner's stored confirmation
  (`PersistentWorkModels.confirmed_target`), equal to the request's work model and
  confirmation refs;
- each lens decision re-issued by the host's lens registry (`LensRegistry.decide`, with
  its own evidence verifier) from the stored evidence, equal to the stored audit and still
  `proposed` (qualified and supported);
- the functional decision re-accepted by `accept_design_decision`, equal to the request's
  decision ref;
- the compilation authority re-admitted by `CompilationAuthority.from_trusted`, equal to
  the request's authority digest;
- the request re-issued by `create_generation_request` and equal, byte for byte, to the
  stored request record.

Anything that does not resolve refuses with its exact reason; nothing is inferred.

Who may create one is a host decision: a `DesignSource` (trusted code, never page input)
names the lens registry, the lens evidence for a confirmed target, the functional
decision for it, the compilation authority and the model turns. Production configures
none — no lens is qualified (every lens is a document candidate and no qualification
record exists) — so creation answers `not_designable` with that reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, canonical_json
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from ..runtime.graph import CompilationAuthority, GraphContractError
from .design import (
    DesignContractError,
    DesignGenerationRequest,
    accept_design_decision,
    create_generation_request,
)
from .design_persistence import decode_design_refs, encode_design_refs
from .lenses import (
    ApplicabilityAssessment,
    LensError,
    LensQualification,
    LensRef,
    RouteEvidence,
)

BASIS_SCHEMA = "design-request-basis-v1"
PRODUCTION_REASON = (
    "no qualified lens decision exists for this work model: no lens is qualified in this "
    "installation (every lens is a document candidate and no qualification record has been "
    "issued), so a design request cannot be created"
)


class DesignRequestError(ValueError):
    """A request cannot be created or restored; `reason` is the exact cause."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class DesignSource:
    """Host-trusted inputs for creating (and restoring) design requests.

    `lens_evidence(target)` returns `(lens_ref, route, assessment, qualification)` tuples
    for a confirmed target; `design_decision(target, lens_decisions)` returns the
    functional decision's content; `compilation_authority()` the trusted snapshot. The
    turns are what the workspace serves the request with."""

    registry: object
    lens_evidence: object
    design_decision: object
    compilation_authority: object
    label: str
    criticism_turn: object | None = None
    critic_model_id: str | None = None
    generation_turn: object | None = None
    generator_model_id: str | None = None
    critic_qualification: object | None = None
    requested_candidate_count: int = 3


def basis_id(request_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:design-request-basis:{request_id}"))


def request_id_for(command_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"deeptwin:design-request:{command_id}"))


def _lens_ref(value: LensRef) -> dict:
    return {"lens_id": value.lens_id, "version": value.version, "content_hash": value.content_hash}


def _evidence_value(lens_ref, route, assessment, qualification) -> dict:
    if route.path != "initial_design" or len(route.evidence_hashes) != 1:
        raise DesignRequestError("a design request's lens evidence is on the initial_design path only")
    return {
        "lens_ref": _lens_ref(lens_ref),
        "route": {"path": route.path, "scope_hash": route.scope_hash,
                  "authorized_source_hashes": list(route.authorized_source_hashes),
                  "work_revision_hash": route.evidence_hashes[0]},
        "assessment": {"status": assessment.status, "evidence_hashes": list(assessment.evidence_hashes),
                       "existing_process_duplicate": assessment.existing_process_duplicate},
        "qualification": None if qualification is None else {
            "path": qualification.path, "scope_hash": qualification.scope_hash,
            "status": qualification.status,
            "qualification_record_hash": qualification.qualification_record_hash},
    }


def _evidence_objects(value):
    lens_ref = LensRef(**value["lens_ref"])
    route = value["route"]
    rebuilt_route = RouteEvidence.create(
        path=route["path"], scope_hash=route["scope_hash"],
        authorized_source_hashes=tuple(route["authorized_source_hashes"]),
        work_revision_hash=route["work_revision_hash"], purpose_confirmed=True,
        deliverables_confirmed=True, completion_confirmed=True, observable_conditions=True)
    assessment = ApplicabilityAssessment.create(
        lens_ref=lens_ref, status=value["assessment"]["status"],
        evidence_hashes=tuple(value["assessment"]["evidence_hashes"]),
        existing_process_duplicate=value["assessment"]["existing_process_duplicate"])
    qualification = None if value["qualification"] is None else LensQualification.create(
        lens_ref=lens_ref, **value["qualification"])
    return lens_ref, rebuilt_route, assessment, qualification


def decide_lenses(source: DesignSource, target):
    """(evidence values, issued decisions, qualified decisions) for a confirmed target."""

    values, decisions = [], []
    for lens_ref, route, assessment, qualification in source.lens_evidence(target):
        values.append(_evidence_value(lens_ref, route, assessment, qualification))
        decisions.append(source.registry.decide(lens_ref, route, assessment, qualification))
    qualified = [item for item in decisions if item.state == "proposed"
                 and item.qualification_status == "qualified" and item.scope_hash == target.work_model_ref.sha256]
    return values, decisions, qualified


def not_designable_reason(decisions) -> str:
    if not decisions:
        return PRODUCTION_REASON
    states = ", ".join(f"{item.lens_ref.lens_id} {item.state} ({item.reason})" for item in decisions)
    return f"no qualified lens decision exists for this work model: {states}"


def _audit(decision) -> dict:
    value = decision.as_audit_dict()
    return {**value, "evidence_hashes": list(value["evidence_hashes"])}


def _decision_value(decision) -> dict:
    value = decision.as_dict()
    return {name: value[name] for name in ("decision_id", "version", "functional_claims", "proposed_effects",
                                           "conflicts", "abstentions")}


def issue_request(source: DesignSource, target, *, request_id: str):
    """Issue a request over the confirmed target, or refuse with the exact reason."""

    if target.blocked_unknown_ids:
        raise DesignRequestError("a blocking unknown in the confirmed work model prevents design: "
                                 + ", ".join(target.blocked_unknown_ids))
    values, decisions, qualified = decide_lenses(source, target)
    if not qualified:
        raise DesignRequestError(not_designable_reason(decisions))
    used = [values[decisions.index(item)] for item in qualified]
    try:
        decision = accept_design_decision(target, qualified, source.design_decision(target, qualified),
                                          registry=source.registry)
        authority = source.compilation_authority()
        request = create_generation_request(target, [decision], request_id=request_id,
                                            requested_candidate_count=source.requested_candidate_count,
                                            compilation_authority=authority)
    except (DesignContractError, GraphContractError, LensError) as error:
        raise DesignRequestError(f"the design request could not be issued: {error}") from None
    basis = {
        "schema_version": BASIS_SCHEMA,
        "request_id": request.request_id,
        "work_model_id": target.work_model.work_model_id,
        "lens_evidence": used,
        "lens_audit": [_audit(item) for item in qualified],
        "design_decision": _decision_value(decision),
        "compilation_authority": authority.as_dict(),
        "requested_candidate_count": request.requested_candidate_count,
        "source_label": source.label,
    }
    return request, basis


def persist_basis(domain, request_record_ref: EntityRef, work_model_record_ref, basis, *, actor_ref,
                  created_at_utc) -> EntityRef:
    record_id = basis_id(basis["request_id"])
    content = {"design_kind": "design_request_basis", "design": encode_design_refs(basis)}
    with _writer(), domain._connection(write=True) as db:
        roots = domain._read_roots(db)
        row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                         "AND id=? AND version=1", (roots.genesis.id, record_id)).fetchone()
        if row is not None:
            ref = EntityRef("decision_record", record_id, 1, row["sha256"])
            if canonical_json(domain._load(db, ref, roots)[0].body["content"]) != canonical_json(content):
                raise DesignRequestError("another basis is already stored for this request")
            return ref
        record = ImmutableRecord.create(
            kind="decision_record", id=record_id, version=1, created_at_utc=created_at_utc, actor_ref=actor_ref,
            parent_refs=(request_record_ref, work_model_record_ref), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy, content=content)
        domain._put_in_transaction(db, record)
        return record.ref


def stored_basis(domain, request_record_ref: EntityRef):
    """The verified basis record of a stored request, or None when it has none."""

    record_id = basis_id(request_record_ref.id)
    with domain._connection() as db:
        roots = domain._read_roots(db)
        row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
                         "AND id=? AND version=1", (roots.genesis.id, record_id)).fetchone()
        if row is None:
            return None
        record = domain._load(db, EntityRef("decision_record", record_id, 1, row["sha256"]), roots)[0]
    content = record.body.get("content")
    if (type(content) is not dict or content.get("design_kind") != "design_request_basis"
            or request_record_ref.as_dict() not in record.body["parent_refs"]):
        raise DesignRequestError("the stored basis is not this request's")
    return decode_design_refs(content["design"])


def _authority(value) -> CompilationAuthority:
    return CompilationAuthority.from_trusted(
        model_choices=[(EntityRef.from_dict(item["model_choice_ref"]), tuple(item["capabilities"]))
                       for item in value["model_choices"]],
        tool_definitions=[(EntityRef.from_dict(item["definition_ref"]), EntityRef.from_dict(item["required_grant_ref"]),
                           tuple(item["capabilities"]), item["tool_id"], item["version"], item["effect_class"])
                          for item in value["tool_definitions"]],
        grant_refs=[EntityRef.from_dict(item) for item in value["grant_refs"]],
        approval_scopes=list(value["approval_scopes"]),
        observation_contract_refs=[EntityRef.from_dict(item) for item in value["observation_contract_refs"]],
        budget_policy_refs=[EntityRef.from_dict(item) for item in value["budget_policy_refs"]],
        artifact_schema_refs=[EntityRef.from_dict(item) for item in value["artifact_schema_refs"]],
    )


def restore_request(source: DesignSource | None, work_models, stored_request: dict, basis) -> DesignGenerationRequest:
    """Rebuild the exact issued request from its stored records, or refuse with the reason."""

    if basis is None:
        raise DesignRequestError("this request has no stored basis (it was registered by host code before "
                                 "requests were restorable), so it cannot be rebuilt")
    if source is None:
        raise DesignRequestError(PRODUCTION_REASON.replace("so a design request cannot be created",
                                                           "so the stored request cannot be rebuilt"))
    if basis.get("schema_version") != BASIS_SCHEMA or basis.get("request_id") != stored_request["request_id"]:
        raise DesignRequestError("the stored basis does not belong to this request")
    try:
        target = work_models.confirmed_target(basis["work_model_id"])
    except Exception:  # noqa: BLE001 - the exact cause is below
        raise DesignRequestError("the owner's confirmation of the work model no longer resolves") from None
    if (target.work_model_ref.as_dict() != stored_request["work_model_ref"]
            or target.confirmation_ref.as_dict() != stored_request["confirmation_ref"]):
        raise DesignRequestError("the confirmed work model does not match the stored request")
    lens_decisions = []
    for value, audit in zip(basis["lens_evidence"], basis["lens_audit"], strict=True):
        try:
            decision = source.registry.decide(*_evidence_objects(value))
        except (LensError, KeyError, TypeError) as error:
            raise DesignRequestError(f"a stored lens decision cannot be re-issued: {error}") from None
        if canonical_json(_audit(decision)) != canonical_json(audit) or decision.state != "proposed":
            raise DesignRequestError(f"the lens decision {decision.lens_ref.lens_id} is no longer qualified "
                                     f"({decision.state}: {decision.reason})")
        lens_decisions.append(decision)
    try:
        functional = accept_design_decision(target, lens_decisions, basis["design_decision"],
                                            registry=source.registry)
        authority = _authority(basis["compilation_authority"])
        request = create_generation_request(target, [functional], request_id=stored_request["request_id"],
                                            requested_candidate_count=basis["requested_candidate_count"],
                                            compilation_authority=authority)
    except (DesignContractError, GraphContractError, KeyError, TypeError) as error:
        raise DesignRequestError(f"the stored request cannot be re-issued: {error}") from None
    if authority.digest != stored_request["compilation_authority_digest"]:
        raise DesignRequestError("the stored compilation authority does not match the request")
    if canonical_json(request.as_dict()) != canonical_json(stored_request):
        raise DesignRequestError("the re-issued request differs from the stored request")
    return request


__all__ = [
    "BASIS_SCHEMA",
    "PRODUCTION_REASON",
    "DesignRequestError",
    "DesignSource",
    "basis_id",
    "decide_lenses",
    "issue_request",
    "not_designable_reason",
    "persist_basis",
    "request_id_for",
    "restore_request",
    "stored_basis",
]
