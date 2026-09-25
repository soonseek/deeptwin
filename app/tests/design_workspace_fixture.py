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
"""

from app.services.design_criticism_live import run_candidate_criticism
from app.services.design_live import run_candidate_generation
from app.services.design_persistence import (
    persist_criticism_run,
    persist_generation_result,
)
from app.tests.test_design_generation import graph_value
from app.tests.test_design_live import model_json
from app.tests.test_design_orchestration import ScriptedRounds, auto_critic, graphs

GENERATOR_ID = "test-actor-generator"
CRITIC_ID = "test-actor-critic"
STAMP = "2026-09-25T00:00:00.000000Z"


def headers(roots):
    return {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
            "retention_policy_ref": roots.retention_policy, "created_at_utc": STAMP}


def seed_design_request(domain):
    """Persist the seeded request; returns (request, registry, candidates by role)."""

    roots = domain.roots()
    request, registry, base, reshaped, third = graphs()
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
