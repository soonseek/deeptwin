"""Durable persistence for the live design-generation chain.

Design-layer references live in content-hash space, not the store's record-body hash
space, so they can never satisfy the DomainStore's exact record-edge check.  The
persistence codec therefore encodes design refs as tagged strings inside record content
(and renames ``*_ref``/``*_refs`` keys, which the store reserves for real record edges),
while real storage lineage uses ``parent_refs`` between the stored records themselves.
"""

import json

import pytest

from app.domain.refs import canonical_json
from app.domain.store import DomainStore
from app.services.design_live import run_candidate_generation
from app.services.design_persistence import (
    DesignPersistenceError,
    decode_design_refs,
    encode_design_refs,
    persist_generation_result,
)
from app.storage import Store
from app.tests.test_design_generation import prepared
from app.tests.test_design_live import MODEL_ID, model_json, scripted_model

STAMP = "2026-09-13T00:00:00.000000Z"


@pytest.fixture
def vault(tmp_path):
    domain = DomainStore(Store(tmp_path / "vault"))
    roots = domain.initialize_vault()
    return domain, roots


def generated():
    _target, _lens, _decision, request, graph = prepared()
    model_turn, _ = scripted_model(model_json(graph))
    result = run_candidate_generation(request, model_turn=model_turn, model_id=MODEL_ID)
    return request, result


def persist(domain, roots, request, result):
    return persist_generation_result(
        domain,
        request,
        result,
        actor_ref=roots.actor,
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        created_at_utc=STAMP,
    )


def test_design_ref_codec_round_trips_and_leaves_foreign_shapes_alone():
    value = {
        "work_model_ref": {"kind": "work_model", "id": "w", "version": 2, "sha256": "a" * 64},
        "decision_refs": [
            {"kind": "design_decision", "id": "d", "version": 1, "sha256": "b" * 64},
        ],
        "lens_decisions": [{"lens_ref": "L-P032-01@draft-1#" + "c" * 64}],
        "target": {"kind": "node", "id": "research", "field": "responsibility"},
        "nested": [{"inline": {"kind": "graph", "id": "g", "version": 1, "sha256": "d" * 64}}],
        "plain": ["text", 7, None, True],
    }
    encoded = encode_design_refs(value)
    payload = json.loads(canonical_json(encoded).decode("utf-8"))
    assert "work_model_ref" not in payload
    assert "decision_refs" not in payload
    flattened = canonical_json(payload).decode("utf-8")
    assert '"kind": "work_model"' not in flattened
    assert payload["target"] == value["target"]  # not a full ref shape: untouched
    assert payload["plain"] == value["plain"]
    assert decode_design_refs(encoded) == value


def test_generation_chain_persists_with_exact_lineage_and_content(vault):
    domain, roots = vault
    request, result = generated()
    persisted = persist(domain, roots, request, result)

    request_record = domain.get(persisted.request_record_ref)
    call_record = domain.get(persisted.call_record_ref)
    assert len(persisted.graph_record_refs) == 1
    assert len(persisted.candidate_record_refs) == 1
    graph_record = domain.get(persisted.graph_record_refs[0])
    candidate_record = domain.get(persisted.candidate_record_refs[0])

    assert request_record.ref.kind == "decision_record"
    assert request_record.ref.id == request.request_id
    body = request_record.body
    assert body["content"]["design_kind"] == "design_generation_request"
    assert canonical_json(decode_design_refs(body["content"]["design"])) == \
        canonical_json(request.as_dict())

    body = call_record.body
    assert canonical_json(decode_design_refs(body["content"]["design"])) == \
        canonical_json(result.call_record.as_dict())
    assert body["parent_refs"] == [persisted.request_record_ref.as_dict()]

    accepted = result.candidates[0]
    assert graph_record.ref.kind == "graph"
    assert graph_record.ref.id == accepted.graph.graph_id
    assert canonical_json(decode_design_refs(graph_record.body["content"]["design"])) == \
        canonical_json(accepted.graph.as_dict())

    assert candidate_record.ref.kind == "design_candidate"
    assert candidate_record.ref.id == accepted.candidate_id
    assert canonical_json(decode_design_refs(candidate_record.body["content"]["design"])) == \
        canonical_json(accepted.as_dict())
    assert candidate_record.body["parent_refs"] == [
        persisted.graph_record_refs[0].as_dict(),
        persisted.call_record_ref.as_dict(),
    ]


def test_persisting_twice_is_idempotent(vault):
    domain, roots = vault
    request, result = generated()
    first = persist(domain, roots, request, result)
    second = persist(domain, roots, request, result)
    assert first == second


def test_a_foreign_request_or_result_binding_is_rejected(vault):
    domain, roots = vault
    request, result = generated()
    from app.services.design import create_generation_request
    from app.tests.test_design_generation import design_authority

    foreign = create_generation_request(
        request.work_target,
        list(request.decisions),
        request_id="00000000-0000-4000-8000-000000000777",
        requested_candidate_count=3,
        compilation_authority=design_authority(),
    )
    with pytest.raises(DesignPersistenceError):
        persist(domain, roots, foreign, result)


def test_type_guards_reject_foreign_objects(vault):
    domain, roots = vault
    request, result = generated()
    with pytest.raises(DesignPersistenceError):
        persist(object(), roots, request, result)
    with pytest.raises(DesignPersistenceError):
        persist(domain, roots, object(), result)
    with pytest.raises(DesignPersistenceError):
        persist(domain, roots, request, object())


# ---------------------------------------------- criticism verdict persistence


from dataclasses import replace

from app.services.design_criticism import fold_candidate_criticism
from app.services.design_persistence import persist_candidate_criticism
from app.tests.test_design_criticism import _chain, _review

RECORD_ID = "00000000-0000-4000-8000-000000000555"


def criticized(request, result):
    candidate = result.candidates[0]
    review = _review(candidate, request, ["pass", "pass"])
    chains = [_chain(
        candidate, request, validity_status="valid", response_status="mitigate",
    )]
    verdict = fold_candidate_criticism(candidate, request, review, chains)
    return candidate, review, chains, verdict


def test_criticism_verdict_persists_with_candidate_lineage(vault):
    domain, roots = vault
    request, result = generated()
    persisted = persist(domain, roots, request, result)
    candidate, review, chains, verdict = criticized(request, result)

    ref = persist_candidate_criticism(
        domain,
        persisted.candidate_record_refs[0],
        candidate,
        request,
        verdict,
        review,
        chains,
        actor_ref=roots.actor,
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        created_at_utc=STAMP,
        record_id=RECORD_ID,
    )
    record = domain.get(ref)
    assert record.ref.kind == "decision_record"
    assert record.ref.id == RECORD_ID
    body = record.body
    assert body["parent_refs"] == [persisted.candidate_record_refs[0].as_dict()]
    design = decode_design_refs(body["content"]["design"])
    assert design["verdict"]["status"] == "passed"
    assert canonical_json(design["review"]) == canonical_json(review)
    assert canonical_json(design["chains"]) == canonical_json(chains)

    again = persist_candidate_criticism(
        domain,
        persisted.candidate_record_refs[0],
        candidate,
        request,
        verdict,
        review,
        chains,
        actor_ref=roots.actor,
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        created_at_utc=STAMP,
        record_id=RECORD_ID,
    )
    assert again == ref


def test_a_forged_verdict_cannot_be_persisted(vault):
    domain, roots = vault
    request, result = generated()
    persisted = persist(domain, roots, request, result)
    candidate, _review_result, chains, verdict = criticized(request, result)
    forged = replace(verdict, status="passed", reasons=())
    tampered_review = _review(candidate, request, ["fail"])
    with pytest.raises(DesignPersistenceError):
        persist_candidate_criticism(
            domain,
            persisted.candidate_record_refs[0],
            candidate,
            request,
            forged,
            tampered_review,  # recomputed fold would reject; verdict says passed
            chains,
            actor_ref=roots.actor,
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            created_at_utc=STAMP,
            record_id=RECORD_ID,
        )


def test_the_candidate_record_binding_is_verified(vault):
    domain, roots = vault
    request, result = generated()
    persisted = persist(domain, roots, request, result)
    candidate, review, chains, verdict = criticized(request, result)
    with pytest.raises(DesignPersistenceError):
        persist_candidate_criticism(
            domain,
            persisted.request_record_ref,  # not the candidate record
            candidate,
            request,
            verdict,
            review,
            chains,
            actor_ref=roots.actor,
            access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy,
            created_at_utc=STAMP,
            record_id=RECORD_ID,
        )
