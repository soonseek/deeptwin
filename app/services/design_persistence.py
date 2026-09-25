"""Persist the live design-generation chain as immutable domain records.

Design-layer references are content hashes over design dictionaries; the DomainStore's
record references hash the whole stored body.  The two spaces can never coincide, and the
store reserves ``*_ref``/``*_refs`` content keys and ref-shaped dictionaries for *real*
record edges, which it verifies against the vault graph.  This module therefore encodes
design references as tagged strings (and suffixes the reserved key names) inside record
content, keeping them honest content data, while actual storage lineage is expressed with
``parent_refs`` between the stored records: request → generation call → graph → candidate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import uuid4

from ..domain.refs import EntityRef, canonical_json
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError
from .design import DesignGenerationRequest
from .design_criticism import (
    DesignCriticismError,
    fold_candidate_criticism,
)
from .design_live import DesignGenerationResult

_REF_KEYS = frozenset({"kind", "id", "version", "sha256"})
_ENCODED_PREFIX = "design-ref:"
_LITERAL_PREFIX = "design-ref-literal:"
_KEY_SUFFIX = "_encoded"
_ENCODED_REF = re.compile(
    r"design-ref:(?P<kind>[a-z_]+):(?P<id>[^@#]+)@(?P<version>0|[1-9][0-9]*)"
    r"#(?P<sha256>[0-9a-f]{64})\Z"
)


class DesignPersistenceError(ValueError):
    """The design chain cannot be persisted as presented."""


def _encode_ref(value: dict) -> str:
    if set(value) != _REF_KEYS:
        raise DesignPersistenceError("a design reference must carry exactly four fields")
    kind, identifier, version, sha = (
        value["kind"], value["id"], value["version"], value["sha256"]
    )
    if (
        type(kind) is not str or type(identifier) is not str
        or type(version) is not int or type(sha) is not str
        or "@" in identifier or "#" in identifier
    ):
        raise DesignPersistenceError("a design reference field is malformed")
    encoded = f"{_ENCODED_PREFIX}{kind}:{identifier}@{version}#{sha}"
    if _ENCODED_REF.fullmatch(encoded) is None:
        raise DesignPersistenceError("a design reference field is malformed")
    return encoded


def encode_design_refs(value: object) -> object:
    """Encode design refs as tagged strings; suffix reserved ``*_ref(s)`` key names."""

    if type(value) is dict:
        if _REF_KEYS <= set(value):
            return _encode_ref(value)
        out: dict[str, object] = {}
        for name, child in value.items():
            encoded = encode_design_refs(child)
            if type(name) is str and name.endswith(_KEY_SUFFIX):
                # A reserved encoded name in source content would collide with or
                # shadow a real encoded key; fail closed rather than losing data.
                raise DesignPersistenceError(
                    "design content may not use reserved encoded key names"
                )
            if type(name) is str and name.endswith(("_ref", "_refs")):
                out[name + _KEY_SUFFIX] = encoded
            else:
                out[name] = encoded
        return out
    if type(value) is list:
        return [encode_design_refs(item) for item in value]
    if type(value) is str and value.startswith((_ENCODED_PREFIX, _LITERAL_PREFIX)):
        # Free text that merely looks like an encoded reference is escaped so the
        # decode below is a true inverse and can never mint a ref from prose.
        return _LITERAL_PREFIX + value
    return value


def decode_design_refs(value: object) -> object:
    """Exact inverse of :func:`encode_design_refs`."""

    if type(value) is dict:
        out: dict[str, object] = {}
        for name, child in value.items():
            decoded = decode_design_refs(child)
            if type(name) is str and name.endswith(_KEY_SUFFIX):
                base = name[: -len(_KEY_SUFFIX)]
                if base.endswith(("_ref", "_refs")):
                    name = base
            out[name] = decoded
        return out
    if type(value) is list:
        return [decode_design_refs(item) for item in value]
    if type(value) is str and value.startswith(_LITERAL_PREFIX):
        return value[len(_LITERAL_PREFIX):]
    if type(value) is str and value.startswith(_ENCODED_PREFIX):
        match = _ENCODED_REF.fullmatch(value)
        if match is None:
            raise DesignPersistenceError("an encoded design reference is malformed")
        return {
            "kind": match["kind"],
            "id": match["id"],
            "version": int(match["version"]),
            "sha256": match["sha256"],
        }
    return value


@dataclass(frozen=True, slots=True)
class PersistedGenerationResult:
    request_record_ref: EntityRef
    call_record_ref: EntityRef
    graph_record_refs: tuple[EntityRef, ...]
    candidate_record_refs: tuple[EntityRef, ...]


def persist_generation_result(
    domain_store: DomainStore,
    request: DesignGenerationRequest,
    result: DesignGenerationResult,
    *,
    actor_ref: EntityRef,
    access_policy_ref: EntityRef,
    retention_policy_ref: EntityRef,
    created_at_utc: str,
) -> PersistedGenerationResult:
    """Persist request, call, graphs and candidates with real parent lineage."""

    if (
        type(domain_store) is not DomainStore
        or type(request) is not DesignGenerationRequest
        or type(result) is not DesignGenerationResult
    ):
        raise DesignPersistenceError("exact store, request and result are required")
    call = result.call_record
    if call.request_ref != request.request_ref:
        raise DesignPersistenceError("the call record does not bind this request")
    for candidate in result.candidates:
        if (
            candidate.generation_request_ref != request.request_ref
            or candidate.generation_call_refs != (call.call_ref,)
        ):
            raise DesignPersistenceError("a candidate does not bind this exact call")

    def store(kind, identifier, version, design_kind, design, parents):
        try:
            record = ImmutableRecord.create(
                kind=kind,
                id=identifier,
                version=version,
                created_at_utc=created_at_utc,
                actor_ref=actor_ref,
                parent_refs=tuple(parents),
                purpose="operational",
                access_policy_ref=access_policy_ref,
                retention_policy_ref=retention_policy_ref,
                content={
                    "design_kind": design_kind,
                    "design": encode_design_refs(design),
                },
            )
        except (TypeError, ValueError) as exc:
            raise DesignPersistenceError("the design chain record is invalid") from exc
        try:
            return domain_store.put(record)
        except StorageError as exc:
            raise DesignPersistenceError(
                "the design chain record could not be stored"
            ) from exc

    request_ref = store(
        "decision_record",
        request.request_id,
        request.version,
        "design_generation_request",
        request.as_dict(),
        (),
    )
    call_ref = store(
        "decision_record",
        call.call_id,
        call.version,
        "design_generation_call",
        call.as_dict(),
        (request_ref,),
    )
    graph_refs = []
    candidate_refs = []
    for candidate in result.candidates:
        graph_ref = store(
            "graph",
            candidate.graph.graph_id,
            candidate.graph.version,
            "functional_graph",
            candidate.graph.as_dict(),
            (call_ref,),
        )
        graph_refs.append(graph_ref)
        candidate_refs.append(store(
            "design_candidate",
            candidate.candidate_id,
            candidate.version,
            "design_candidate",
            candidate.as_dict(),
            (graph_ref, call_ref),
        ))
    return PersistedGenerationResult(
        request_record_ref=request_ref,
        call_record_ref=call_ref,
        graph_record_refs=tuple(graph_refs),
        candidate_record_refs=tuple(candidate_refs),
    )


def _validate_candidate_criticism(
    domain_store, candidate_record_ref, candidate, request,
    verdict, review, chains,
) -> None:
    """Everything a forged run could lie about, checked before any put."""

    if type(domain_store) is not DomainStore:
        raise DesignPersistenceError("an exact domain store is required")
    if type(candidate_record_ref) is not EntityRef:
        raise DesignPersistenceError("an exact candidate record ref is required")
    from .design_criticism import is_issued_verdict

    if not is_issued_verdict(verdict):
        raise DesignPersistenceError("a fold-issued candidate verdict is required")
    try:
        recomputed = fold_candidate_criticism(candidate, request, review, chains)
    except DesignCriticismError as exc:
        raise DesignPersistenceError(
            "the criticism results cannot be folded for persistence"
        ) from exc
    if recomputed != verdict:
        raise DesignPersistenceError(
            "the presented verdict does not match the recomputed fold"
        )
    stored = domain_store.get(candidate_record_ref)
    body = stored.body
    if (
        body["kind"] != "design_candidate"
        or body["id"] != verdict.candidate_id
        or str(body["version"]) != verdict.candidate_version
        or canonical_json(decode_design_refs(body["content"]["design"]))
        != canonical_json(candidate.as_dict())
    ):
        raise DesignPersistenceError(
            "the candidate record does not bind this exact verdict"
        )


def persist_candidate_criticism(
    domain_store: DomainStore,
    candidate_record_ref: EntityRef,
    candidate,
    request,
    verdict,
    review: dict,
    chains: list,
    *,
    actor_ref: EntityRef,
    access_policy_ref: EntityRef,
    retention_policy_ref: EntityRef,
    created_at_utc: str,
    record_id: str | None = None,
    call_records: list | None = None,
    call_record_refs: tuple = (),
    lens_use: dict | None = None,
) -> EntityRef:
    """Persist one candidate's criticism and its verdict, parented to the candidate.

    The verdict is never trusted as presented: the fold is recomputed from the
    supplied review and chains and must equal it exactly, so a forged selectability
    state cannot become a durable record.
    """

    _validate_candidate_criticism(
        domain_store, candidate_record_ref, candidate, request,
        verdict, review, chains,
    )
    identifier = record_id if record_id is not None else str(uuid4())
    design = {
        "verdict": verdict.as_dict(),
        "review": review,
        "chains": chains,
    }
    if call_records is not None:
        design["call_records"] = call_records
    if lens_use is not None:
        design["lens_use"] = lens_use
    try:
        record = ImmutableRecord.create(
            kind="decision_record",
            id=identifier,
            version=1,
            created_at_utc=created_at_utc,
            actor_ref=actor_ref,
            parent_refs=(candidate_record_ref, *call_record_refs),
            purpose="operational",
            access_policy_ref=access_policy_ref,
            retention_policy_ref=retention_policy_ref,
            content={
                "design_kind": "candidate_criticism",
                "design": encode_design_refs(design),
            },
        )
    except (TypeError, ValueError) as exc:
        raise DesignPersistenceError("the criticism record is invalid") from exc
    try:
        return domain_store.put(record)
    except StorageError as exc:
        raise DesignPersistenceError(
            "the criticism record could not be stored"
        ) from exc


@dataclass(frozen=True, slots=True)
class PersistedCriticismRun:
    criticism_ref: EntityRef
    call_refs: tuple


def _expected_prompt_hashes(candidate, request, registry, chains):
    from hashlib import sha256 as _sha256

    from .design_criticism import (
        prepare_candidate_proposal,
        prepare_candidate_response,
        prepare_candidate_review,
        prepare_candidate_validity,
    )
    from .design_criticism_live import render_criticism_prompt

    def prompt_hash(prepared):
        system, user = render_criticism_prompt(prepared)
        return _sha256(
            canonical_json({"system": system, "user": user})
        ).hexdigest()

    expected = [
        ("review", prompt_hash(prepare_candidate_review(candidate, request))),
        ("counterexample_proposal", prompt_hash(
            prepare_candidate_proposal(candidate, request, registry),
        )),
    ]
    for chain in chains:
        expected.append(("counterexample_validity", prompt_hash(
            prepare_candidate_validity(
                candidate, request, chain["counterexample"],
            ),
        )))
        if chain["response"] is not None:
            expected.append(("candidate_response", prompt_hash(
                prepare_candidate_response(
                    candidate, request, chain["counterexample"],
                    chain["validity"],
                ),
            )))
    return expected


def persist_criticism_run(
    domain_store: DomainStore,
    candidate_record_ref,
    candidate,
    request,
    registry,
    run,
    *,
    actor_ref,
    access_policy_ref,
    retention_policy_ref,
    created_at_utc: str,
    record_id: str | None = None,
) -> PersistedCriticismRun:
    """Persist one driven criticism run: every call record plus the verdict.

    The run is never trusted as presented: every stage prompt hash is
    recomputed from the candidate, request, registry and the run's own
    chains, the call sequence must be exactly what the chains imply, all
    calls must share one model identity and the exact request binding, and
    the verdict is recomputed by persist_candidate_criticism. A forged
    hash, a dropped or reordered call, or a forged verdict never becomes a
    durable record.
    """

    from .design_criticism_live import (
        is_issued_call_record,
        is_issued_criticism_run,
    )

    if type(domain_store) is not DomainStore:
        raise DesignPersistenceError("an exact domain store is required")
    if not is_issued_criticism_run(run) or not all(
        is_issued_call_record(record) for record in run.call_records
    ):
        # Only the driver issues runs and records; a constructed or
        # field-swapped look-alike never becomes durable evidence.
        raise DesignPersistenceError("a driver-issued criticism run is required")
    # F3: everything a forged run could lie about is checked BEFORE the
    # first put, so a refused run leaves nothing durable behind.
    _validate_candidate_criticism(
        domain_store, candidate_record_ref, candidate, request,
        run.verdict, run.review, list(run.chains),
    )
    try:
        expected = _expected_prompt_hashes(
            candidate, request, registry, list(run.chains),
        )
    except Exception as exc:
        raise DesignPersistenceError(
            "the criticism run's stages cannot be re-rendered"
        ) from exc
    actual = [
        (record.purpose, record.prompt_sha256) for record in run.call_records
    ]
    if actual != expected:
        raise DesignPersistenceError(
            "the call records do not match the run's own stage sequence"
        )
    model_ids = {record.model_id for record in run.call_records}
    if len(model_ids) != 1 or any(
        record.request_ref != request.request_ref
        for record in run.call_records
    ):
        raise DesignPersistenceError(
            "the call records do not bind one model and this exact request"
        )
    call_refs = []
    for record in run.call_records:
        try:
            stored = ImmutableRecord.create(
                kind="decision_record",
                id=record.call_id,
                version=record.version,
                created_at_utc=created_at_utc,
                actor_ref=actor_ref,
                parent_refs=(candidate_record_ref,),
                purpose="operational",
                access_policy_ref=access_policy_ref,
                retention_policy_ref=retention_policy_ref,
                content={
                    "design_kind": "criticism_call",
                    "design": encode_design_refs(record.as_dict()),
                },
            )
        except (TypeError, ValueError) as exc:
            raise DesignPersistenceError(
                "a criticism call record is invalid"
            ) from exc
        try:
            call_refs.append(domain_store.put(stored))
        except StorageError as exc:
            raise DesignPersistenceError(
                "a criticism call record could not be stored"
            ) from exc
    criticism_ref = persist_candidate_criticism(
        domain_store,
        candidate_record_ref,
        candidate,
        request,
        run.verdict,
        run.review,
        list(run.chains),
        actor_ref=actor_ref,
        access_policy_ref=access_policy_ref,
        retention_policy_ref=retention_policy_ref,
        created_at_utc=created_at_utc,
        record_id=record_id,
        call_records=[record.as_dict() for record in run.call_records],
        call_record_refs=tuple(call_refs),
        lens_use={
            "proposal_status": run.proposal_status,
            "rules": [
                {**use, "counterexample_ids": list(use["counterexample_ids"])}
                for use in run.lens_use
            ],
        },
    )
    return PersistedCriticismRun(
        criticism_ref=criticism_ref, call_refs=tuple(call_refs),
    )


__all__ = [
    "DesignPersistenceError",
    "PersistedCriticismRun",
    "PersistedGenerationResult",
    "decode_design_refs",
    "encode_design_refs",
    "persist_candidate_criticism",
    "persist_criticism_run",
    "persist_generation_result",
]
