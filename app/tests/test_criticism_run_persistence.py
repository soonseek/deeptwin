"""Durable persistence of one driven criticism run (design pillar).

The driven run's call records are not trusted as presented: the persistence
path recomputes every stage's prompt hash from the candidate, request,
registry and the run's own chains, requires the exact call sequence the
chains imply (review, proposal, one validity per chain, one response per
non-None chain response), a single model identity, and the exact request
binding — then stores each call record and the recomputed-fold verdict
record parented to the candidate record and every call record. A forged
hash, a dropped call, or a forged verdict never becomes a durable record.
"""

import dataclasses

import pytest

from app.domain.store import DomainStore
from app.services.design_criticism_live import (
    CriticismCallRecord,
    run_candidate_criticism,
)
from app.services.design_live import run_candidate_generation
from app.services.design_persistence import (
    DesignPersistenceError,
    decode_design_refs,
    persist_criticism_run,
    persist_generation_result,
)
from app.storage import Store
from app.tests.test_design_criticism_live import (
    MODEL_ID,
    ScriptedCritic,
    scripted_chain,
)
from app.tests.test_design_generation import prepared, proposed_lens
from app.tests.test_design_live import model_json, scripted_model

STAMP = "2026-09-13T07:00:00.000000Z"


@pytest.fixture
def vault(tmp_path):
    domain = DomainStore(Store(tmp_path / "vault"))
    roots = domain.initialize_vault()
    return domain, roots


def headers(roots):
    return {
        "actor_ref": roots.actor,
        "access_policy_ref": roots.access_policy,
        "retention_policy_ref": roots.retention_policy,
        "created_at_utc": STAMP,
    }


def driven_persisted(domain, roots):
    _target, _lens, _decision, request, graph = prepared()
    model_turn, _calls = scripted_model(model_json(graph))
    generation = run_candidate_generation(
        request, model_turn=model_turn, model_id=MODEL_ID,
    )
    persisted = persist_generation_result(
        domain, request, generation, **headers(roots),
    )
    candidate = generation.candidates[0]
    registry, _lens2 = proposed_lens(request.work_target)
    import json as _json

    from app.services.design_criticism import prepare_candidate_proposal

    proposal_input = prepare_candidate_proposal(candidate, request, registry)
    rule = _json.loads(proposal_input.prompt)["input"]["lens_pack"]["rules"][0]
    manifest = _json.loads(proposal_input.manifest_json)
    review, proposal, validity, response = scripted_chain(
        candidate, request, rule, manifest["criterion_ids"],
        request.work_target.work_model.work_model_id,
    )
    run = run_candidate_criticism(
        candidate, request, registry,
        model_turn=ScriptedCritic([review, proposal, validity, response]),
        model_id=MODEL_ID,
    )
    return request, candidate, registry, run, persisted


def test_a_driven_run_persists_with_its_exact_call_chain(vault):
    domain, roots = vault
    request, candidate, registry, run, persisted = driven_persisted(domain, roots)
    candidate_ref = persisted.candidate_record_refs[0]
    result = persist_criticism_run(
        domain, candidate_ref, candidate, request, registry, run,
        **headers(roots),
    )
    assert len(result.call_refs) == 4
    stored = domain.get(result.criticism_ref)
    content = decode_design_refs(stored.body["content"]["design"])
    assert content["verdict"] == run.verdict.as_dict()
    assert [item["call_id"] for item in content["call_records"]] == [
        record.call_id for record in run.call_records
    ]
    # every call record is durable and parented under the candidate record
    for ref, record in zip(result.call_refs, run.call_records):
        call_body = domain.get(ref).body
        assert call_body["parent_refs"][0]["id"] == candidate_ref.id
        call_content = decode_design_refs(call_body["content"]["design"])
        assert call_content["purpose"] == record.purpose
        assert call_content["prompt_sha256"] == record.prompt_sha256


def test_a_forged_prompt_hash_never_persists(vault):
    domain, roots = vault
    request, candidate, registry, run, persisted = driven_persisted(domain, roots)
    forged_first = CriticismCallRecord(
        call_id=run.call_records[0].call_id,
        version=1,
        request_ref=run.call_records[0].request_ref,
        purpose="review",
        profile_digest=run.call_records[0].profile_digest,
        model_id=MODEL_ID,
        prompt_sha256="ab" * 32,  # not the rendered review prompt
        response_sha256=run.call_records[0].response_sha256,
    )
    forged = dataclasses.replace(
        run, call_records=(forged_first, *run.call_records[1:]),
    )
    with pytest.raises(DesignPersistenceError):
        persist_criticism_run(
            domain, persisted.candidate_record_refs[0], candidate, request, registry,
            forged, **headers(roots),
        )


def test_a_dropped_or_reordered_call_never_persists(vault):
    domain, roots = vault
    request, candidate, registry, run, persisted = driven_persisted(domain, roots)
    dropped = dataclasses.replace(run, call_records=run.call_records[:-1])
    with pytest.raises(DesignPersistenceError):
        persist_criticism_run(
            domain, persisted.candidate_record_refs[0], candidate, request, registry,
            dropped, **headers(roots),
        )
    reordered = dataclasses.replace(
        run,
        call_records=(run.call_records[1], run.call_records[0],
                      *run.call_records[2:]),
    )
    with pytest.raises(DesignPersistenceError):
        persist_criticism_run(
            domain, persisted.candidate_record_refs[0], candidate, request, registry,
            reordered, **headers(roots),
        )


def test_a_forged_verdict_never_persists(vault):
    domain, roots = vault
    request, candidate, registry, run, persisted = driven_persisted(domain, roots)
    from app.services.design_criticism import CandidateVerdict

    forged = dataclasses.replace(run, verdict=CandidateVerdict(
        candidate_id=run.verdict.candidate_id,
        candidate_version=run.verdict.candidate_version,
        status="passed",
        reasons=("조작된 사유",),
    ))
    with pytest.raises(DesignPersistenceError):
        persist_criticism_run(
            domain, persisted.candidate_record_refs[0], candidate, request, registry,
            forged, **headers(roots),
        )
    with pytest.raises(DesignPersistenceError):
        persist_criticism_run(
            domain, persisted.candidate_record_refs[0], candidate, request, registry,
            object(), **headers(roots),
        )
