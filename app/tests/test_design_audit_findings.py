"""Per-finding regression tests for the 2026-09-13 design-pillar adversarial audit.

Each test reproduces one audited defect (F1-F8) and pins its fix.
"""

import dataclasses
import json

import pytest

from app.domain.refs import canonical_json
from app.domain.store import DomainStore
from app.services.design import (
    DesignCandidate,
    DesignContractError,
    accept_design_candidates,
    is_accepted_candidate,
)
from app.services.design_criticism import (
    DesignCriticismError,
    critic_candidate_projection,
    fold_candidate_criticism,
    prepare_candidate_review,
)
from app.services.design_live import DesignGenerationError, run_candidate_generation
from app.services.design_persistence import (
    DesignPersistenceError,
    decode_design_refs,
    encode_design_refs,
    persist_generation_result,
)
from app.storage import Store
from app.tests.test_design_criticism import _review, live_pair
from app.tests.test_design_generation import candidate, graph_value, prepared, ref
from app.tests.test_design_live import MODEL_ID, model_json, scripted_model

STAMP = "2026-09-13T00:00:00.000000Z"


def accepted_pair(base_graph, other_graph, request):
    return accept_design_candidates(request, [
        candidate(request, base_graph),
        candidate(request, other_graph, suffix=232),
    ])


# ------------------------------------------------------------------ F1


def test_projection_surfaces_grants_memory_grants_and_handler_configs():
    target, _lens, decision, request, _graph = prepared()
    dref = decision.decision_ref.as_dict()
    base = graph_value(target, dref)
    granted = graph_value(target, dref, graph_suffix=205)
    granted["nodes"][0]["grant_refs"] = [ref("grant", 211), ref("grant", 212)]
    base_candidate, granted_candidate = accepted_pair(base, granted, request)

    base_projection = critic_candidate_projection(base_candidate)
    granted_projection = critic_candidate_projection(granted_candidate)
    assert base_projection != granted_projection

    flattened = canonical_json(granted_projection).decode("utf-8")
    assert "grant:" in flattened  # node grants are visible
    extra_grant = ref("grant", 212)
    assert extra_grant["sha256"] in flattened

    # Memory read grants, tool grants, deterministic handlers and non-artifact
    # edge payloads are all visible to the critic.
    base_flat = canonical_json(base_projection).decode("utf-8")
    assert "memory_read_grant:" in base_flat
    assert "tool_grant:" in base_flat
    assert "handler:artifact-finalizer-v1" in base_flat
    assert "artifact.publish" in "\n".join(base_projection["control"]["notes"])


# ------------------------------------------------------------------ F2


def test_a_forged_candidate_never_inherits_acceptance_authority():
    request, real = live_pair()
    assert is_accepted_candidate(real)

    with pytest.raises(TypeError):
        dataclasses.replace(real, candidate_id=real.candidate_id)
    with pytest.raises(TypeError):
        DesignCandidate(
            real.candidate_id, real.version, real.generation_request_ref,
            real.work_model_ref, real.decision_refs, real.parent_candidate_refs,
            real.generation_call_refs, real.graph, real.graph_ref,
            real.applied_effect_ids, real.audit_lens_refs,
        )

    forged = object.__new__(DesignCandidate)
    for name in (
        "candidate_id", "version", "generation_request_ref", "work_model_ref",
        "decision_refs", "parent_candidate_refs", "generation_call_refs",
        "graph", "graph_ref", "applied_effect_ids", "audit_lens_refs",
    ):
        object.__setattr__(forged, name, getattr(real, name))
    object.__setattr__(forged, "_issuer_token", object())
    assert not is_accepted_candidate(forged)

    with pytest.raises(DesignCriticismError):
        critic_candidate_projection(forged)
    with pytest.raises(DesignCriticismError):
        prepare_candidate_review(forged, request)
    with pytest.raises(DesignCriticismError):
        fold_candidate_criticism(forged, request, _review(real, request, ["pass"]), [])


# ------------------------------------------------------------------ F3


def test_design_ref_shaped_strings_round_trip_and_cannot_poison_records(tmp_path):
    for text in (
        "design-ref:evil",
        "design-ref:node:injected@1#" + "a" * 64,
        "design-ref-literal:x",
    ):
        value = {"note": text}
        assert decode_design_refs(encode_design_refs(value)) == value

    domain = DomainStore(Store(tmp_path / "vault"))
    roots = domain.initialize_vault()
    _target, _lens, _decision, request, graph = prepared()
    graph = json.loads(json.dumps(graph))
    # The writer node's responsibility is not effect-bound, so acceptance holds.
    graph["nodes"][1]["responsibility"] = (
        "design-ref:node:injected@1#" + "a" * 64
    )
    model_turn, _ = scripted_model(model_json(graph))
    result = run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)
    persisted = persist_generation_result(
        domain, request, result,
        actor_ref=roots.actor, access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, created_at_utc=STAMP,
    )
    stored = domain.get(persisted.graph_record_refs[0])
    decoded = decode_design_refs(stored.body["content"]["design"])
    assert canonical_json(decoded) == canonical_json(
        result.candidates[0].graph.as_dict()
    )


# ------------------------------------------------------------------ F4


def test_fold_requires_exact_criteria_coverage():
    request, candidate_ = live_pair()
    with pytest.raises(DesignCriticismError):
        fold_candidate_criticism(candidate_, request, {
            "candidate_id": candidate_.candidate_id,
            "candidate_version": str(candidate_.version),
        }, [])
    alien = _review(candidate_, request, ["pass"])
    alien["findings"][0]["criterion_id"] = "alien:criterion"
    with pytest.raises(DesignCriticismError):
        fold_candidate_criticism(candidate_, request, alien, [])
    partial = _review(candidate_, request, ["pass"])
    partial["findings"] = partial["findings"][:1]
    with pytest.raises(DesignCriticismError):
        fold_candidate_criticism(candidate_, request, partial, [])
    complete = _review(candidate_, request, ["pass"])
    verdict = fold_candidate_criticism(candidate_, request, complete, [])
    assert verdict.status == "passed"


# ------------------------------------------------------------------ F5


def test_a_producerless_artifact_contract_is_a_typed_error():
    target, _lens, decision, request, _graph = prepared()
    dref = decision.decision_ref.as_dict()
    orphaned = graph_value(target, dref)
    orphaned["artifact_contracts"].append({
        "artifact_contract_id": "orphan-contract",
        "media_types": ["text/plain"],
        "schema_ref": None,
        "min_items": 1,
        "max_items": 1,
        "max_total_bytes": 1_024,
    })
    accepted = accept_design_candidates(request, [candidate(request, orphaned)])
    with pytest.raises(DesignCriticismError):
        critic_candidate_projection(accepted[0])


# ------------------------------------------------------------------ F6


def test_duplicate_graph_identity_is_rejected_at_acceptance():
    target, _lens, decision, request, _graph = prepared()
    dref = decision.decision_ref.as_dict()
    base = graph_value(target, dref)
    twin_identity = graph_value(target, dref)  # same graph_id
    twin_identity["nodes"][0]["grant_refs"] = [ref("grant", 211), ref("grant", 212)]
    with pytest.raises(DesignContractError):
        accepted_pair(base, twin_identity, request)


def test_storage_conflicts_surface_as_persistence_errors(tmp_path):
    domain = DomainStore(Store(tmp_path / "vault"))
    roots = domain.initialize_vault()
    _target, _lens, _decision, request, graph = prepared()
    model_turn, _ = scripted_model(model_json(graph))
    result = run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)
    persist_generation_result(
        domain, request, result,
        actor_ref=roots.actor, access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, created_at_utc=STAMP,
    )
    with pytest.raises(DesignPersistenceError):
        persist_generation_result(
            domain, request, result,
            actor_ref=roots.actor, access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            created_at_utc="2026-09-13T01:00:00.000000Z",  # different bytes, same ids
        )


# ------------------------------------------------------------------ F7


def test_a_lone_surrogate_response_is_a_typed_generation_error():
    _target, _lens, _decision, request, graph = prepared()
    # A raw lone surrogate in the response text fails record minting, typed.
    raw = model_json(graph)[:-2] + ', "x": "\ud800"}]}'  # still not valid shape
    raw = json.dumps({"candidates": [{"graph": graph}]})
    raw = raw[:-1] + "\ud800" + raw[-1]  # inject after closing content? invalid JSON
    # Build a valid response whose parsed text carries a lone surrogate AND whose
    # raw string carries one: append it inside an ignored JSON string is not
    # possible under the strict shape, so place it in the graph responsibility
    # via a real (unescaped) surrogate character in the raw JSON text.
    body = json.dumps({"candidates": [{"graph": graph}]}, ensure_ascii=False)
    raw = body.replace("공개 출처를", "공개 출처를\ud800", 1)
    model_turn, _ = scripted_model(raw)
    with pytest.raises(DesignGenerationError):
        run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)

    # The escaped variant survives the raw hash but is rejected, typed, by the
    # graph text contract during acceptance.
    escaped = json.loads(json.dumps(graph))
    escaped["nodes"][0]["responsibility"] = "x\ud800"
    model_turn, _ = scripted_model(model_json(escaped))
    with pytest.raises(DesignContractError):
        run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)


# ------------------------------------------------------------------ F8


def test_reserved_encoded_key_names_are_rejected_not_lossy():
    with pytest.raises(DesignPersistenceError):
        encode_design_refs({"foo_ref_encoded": "x"})
    with pytest.raises(DesignPersistenceError):
        encode_design_refs({
            "foo_ref": {"kind": "graph", "id": "g", "version": 1, "sha256": "a" * 64},
            "foo_ref_encoded": "x",
        })
