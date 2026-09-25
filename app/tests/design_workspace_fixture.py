"""TEST-ACTOR seed for the design workspace (T037): one persisted design request whose
candidates, graphs, criticism calls and verdicts are real records written by the real
persistence functions — produced by scripted test-actor model turns, never by a model.

The generator and the critic are code-owned scripts (`test-actor-generator`,
`test-actor-critic`); their verdicts are recorded as what those scripts concluded and
are labelled with those identities wherever they are shown. No score or verdict here is
live. The seeded pool is deliberately short: four candidates across two generation
rounds — two passed and structurally different (presented), one rejected for a
mandatory defect, and one passed structural duplicate — so the pool states the real
count (2 of 3) and every exclusion's reason.

`seed_for_work` (T074) seeds the same pool over a REAL work: a `work_model` record
(authored by the vault's test actor, parented to the work's actual revision and naming
its actual stored sources) whose design ref the request names, so the work's export can
find the request through the store's own records.
"""

import copy
from uuid import NAMESPACE_URL, uuid5

from app.domain.schemas import ImmutableRecord
from app.services.design import confirm_work_model, create_generation_request
from app.services.design_criticism_live import run_candidate_criticism
from app.services.design_live import run_candidate_generation
from app.services.design_persistence import (
    persist_criticism_run,
    persist_generation_result,
)
from app.tests.test_design_generation import (
    design_authority,
    design_decision,
    graph_value,
    proposed_lens,
)
from app.tests.test_design_live import model_json
from app.tests.test_design_orchestration import ScriptedRounds, auto_critic, graphs
from app.tests.test_work_model_confirmation import confirmation, work_model

GENERATOR_ID = "test-actor-generator"
CRITIC_ID = "test-actor-critic"
STAMP = "2026-09-25T00:00:00.000000Z"


def headers(roots):
    return {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
            "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}


def seed_design_request(domain, designed=None):
    """Persist the seeded request; returns (request, registry, candidates by role)."""

    roots = domain.roots()
    request, registry, base, reshaped, third = graphs() if designed is None else designed
    duplicate = graph_value(request.work_target, request.decisions[0].decision_ref.as_dict(), graph_suffix=207)
    generation = ScriptedRounds([model_json(base, reshaped, third), model_json(duplicate)])
    rounds = [run_candidate_generation(request, model_turn=generation, model_id=GENERATOR_ID) for _ in range(2)]
    first, second = rounds
    # of two structural duplicates the pool presents the one first in its deterministic
    # (candidate id) order, never the one a caller names
    same_shape = sorted((first.candidates[0], second.candidates[0]), key=lambda item: item.candidate_id)
    roles = {"base": same_shape[0], "reshaped": first.candidates[1], "rejected": first.candidates[2],
             "duplicate": same_shape[1]}
    critic = auto_critic(reject_ids=frozenset({roles["rejected"].candidate_id}))
    for result in rounds:
        persisted = persist_generation_result(domain, request, result, **headers(roots))
        for candidate, record_ref in zip(result.candidates, persisted.candidate_record_refs):
            run = run_candidate_criticism(candidate, request, registry, model_turn=critic, model_id=CRITIC_ID)
            persist_criticism_run(domain, record_ref, candidate, request, registry, run, **headers(roots))
    return request, registry, roles


def open_seeded(app, *, criticism_turn=False, critic_qualification=None):
    """Seed the app's vault and register the request with its design workspace."""

    domain = app.state.domain_store
    request, registry, roles = seed_design_request(domain)
    workspace = app.state.first_party_exports["design-workspace.service"]
    workspace.open_request(request, registry=registry, critic_qualification=critic_qualification,
                           criticism_turn=auto_critic() if criticism_turn else None,
                           critic_model_id=CRITIC_ID if criticism_turn else None)
    return request, roles


def _shapes(target, decision):
    """The three structurally different graphs `graphs()` builds, over `target`."""

    base = graph_value(target, decision.decision_ref.as_dict())
    reshaped = graph_value(target, decision.decision_ref.as_dict(), graph_suffix=205)
    for contract in reshaped["artifact_contracts"]:
        if contract["artifact_contract_id"] == "final-script":
            contract["max_items"] = 1
            contract["media_types"] = ["text/markdown"]
    third = graph_value(target, decision.decision_ref.as_dict(), graph_suffix=206)
    for contract in third["artifact_contracts"]:
        if contract["artifact_contract_id"] == "research-notes":
            contract["max_items"] = 1
            contract["min_items"] = 1
            contract["max_total_bytes"] = 524_288
    return base, reshaped, third


def seed_for_work(domain, revision_ref, source_refs):
    """TEST-ACTOR work model over the work's actual revision and sources, and the seeded
    design request over it; returns (request, registry, candidates by role)."""

    roots = domain.roots()
    raw = copy.deepcopy(work_model())
    raw["work_model_id"] = str(uuid5(NAMESPACE_URL, f"deeptwin:test-actor-work-model:{revision_ref.id}"))
    raw["work_revision_ref"] = revision_ref.as_dict()
    raw["source_refs"] = [ref.as_dict() for ref in source_refs]
    raw["suitability"]["evidence_refs"] = [ref.as_dict() for ref in source_refs]
    prepared = confirm_work_model(raw, None)
    target = confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))
    domain.put(ImmutableRecord.create(
        kind="work_model", id=raw["work_model_id"], version=1, created_at_utc=STAMP, actor_ref=roots.actor,
        parent_refs=(revision_ref,), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content=target.work_model.as_dict()))
    registry, lens = proposed_lens(target)
    decision = design_decision(target, registry, lens)
    request = create_generation_request(
        target, [decision], request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:test-actor-design:{revision_ref.id}")),
        requested_candidate_count=3, compilation_authority=design_authority())
    return seed_design_request(domain, (request, registry, *_shapes(target, decision)))


def open_seeded_for_work(app, revision_ref, source_refs, *, criticism_turn=False, critic_qualification=None):
    """`seed_for_work` and register the request with the app's design workspace."""

    request, registry, roles = seed_for_work(app.state.domain_store, revision_ref, source_refs)
    workspace = app.state.first_party_exports["design-workspace.service"]
    workspace.open_request(request, registry=registry, critic_qualification=critic_qualification,
                           criticism_turn=auto_critic() if criticism_turn else None,
                           critic_model_id=CRITIC_ID if criticism_turn else None)
    return request, roles
