"""T038 — the ONE owner-authorized LIVE design-arc run: real generation and real
criticism for one design request, through the product's own route
(`POST /api/v1/design-requests/{id}/generations`) and drivers, over the owner's Claude
connection (`ClaudeRunExecutor.model_turn`).

Runs only with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and `DEEPTWIN_LIVE_DESIGN_ARC=1`; never in
the ordinary suite (the file name carries `_live_`). The owner authorized a hard cap of
USD 3.00 for this step, total across attempts. It makes:
- one catalog read (`GET /v1/models`, free);
- one generation round (`max_rounds=1`, one candidate per call) and the criticism of what
  it admits (review, counterexample proposal, then validity and response per
  counterexample) — the drivers never retry, and there is no fallback model;
- before EVERY call a spend guard bounds the run's spend so far (from the provider-reported
  usage the executor sealed) plus the worst case of the next call (its exact prompt length,
  one token per character, and its output cap) at deliberately high ceiling rates, and
  refuses to send if that bound exceeds the cap. A refused send is recorded by the arc as a
  refused call, never as a candidate.
The model is `DEEPTWIN_LIVE_MODEL` if the operator names one, else the first model the live
catalog lists; its identifier comes from the provider, never from this file.

The design request uses the fixture lens decision (SIMULATED lens qualification) and NO
critic qualification: this run is live generation and criticism, not a qualification, and
its verdict is shown as the recorded conclusion of the named live model. The key goes in
through the owner's connection route (server memory only) and is never printed, stored or
asserted on. Non-secret evidence goes to `DEEPTWIN_LIVE_EVIDENCE_PATH` when set.
"""

import json
import os
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.services.claude_run_executor import DESIGN_INTENT_SCHEMA, OUTCOME_SCHEMA, ClaudeRunExecutor, LiveLimits
from app.services.design import create_generation_request
from app.services.design_persistence import persist_design_request
from app.tests.design_arc_fixture import STAMP, _work_model
from app.tests.test_claude_design_turn import records
from app.tests.test_claude_live_path import claude
from app.tests.test_design_arc import generate, read, work_with_source
from app.tests.test_design_generation import design_authority, design_decision, proposed_lens
from app.tests.test_runs_api import owner_app

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL")
EVIDENCE = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")
CAP_USD = 3.00
GENERATION_OUTPUT_TOKENS = 12_000
CRITICISM_OUTPUT_TOKENS = 6_000
# ceilings at or above the highest listed per-token prices, so a bound is never an underestimate
CEILING_INPUT_USD_PER_MTOK = 10.0
CEILING_OUTPUT_USD_PER_MTOK = 50.0

pytestmark = pytest.mark.skipif(not KEY or os.environ.get("DEEPTWIN_LIVE_DESIGN_ARC") != "1",
                                reason="the live design arc needs the key and DEEPTWIN_LIVE_DESIGN_ARC=1")


def _usage_cost(usage) -> float:
    inputs = sum(int(usage.get(name) or 0) for name in ("input_tokens", "cache_creation_input_tokens",
                                                          "cache_read_input_tokens"))
    return (inputs * CEILING_INPUT_USD_PER_MTOK + int(usage.get("output_tokens") or 0) * CEILING_OUTPUT_USD_PER_MTOK) / 1e6


class SpendGuard:
    """Refuses a send whose worst case would take the run past the cap."""

    def __init__(self, subject):
        self.subject = subject
        self.refused = []

    def spent(self) -> float:
        return sum(_usage_cost(item.get("usage") or {}) for item in records(self.subject, OUTCOME_SCHEMA))

    def wrap(self, turn, cap_tokens, stage):
        def guarded(system, user):
            bound = self.spent() + ((len(system) + len(user)) * CEILING_INPUT_USD_PER_MTOK
                                    + cap_tokens * CEILING_OUTPUT_USD_PER_MTOK) / 1e6
            if bound > CAP_USD:
                self.refused.append({"stage": stage, "bound_usd": round(bound, 4)})
                raise RuntimeError("the spend guard refused this send: the cap would be exceeded")
            return turn(system, user)

        return guarded


def test_one_live_design_arc_generation_and_criticism(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=12, max_design_output_tokens=GENERATION_OUTPUT_TOKENS))
    with owner_app(tmp_path, executor) as subject:
        assert claude(subject, "key", {"secret": KEY}).status_code == 200
        catalog = claude(subject, "catalog")
        assert catalog.status_code == 200, catalog.json()
        listed = catalog.json()["catalog"]["model_ids"]
        model = MODEL or listed[0]
        assert model in listed, "the chosen model is not in the live catalog"
        revision, sources = work_with_source(subject)
        domain = subject.app.state.domain_store
        roots = domain.roots()
        target = _work_model(domain, revision, sources)
        registry, lens = proposed_lens(target)
        decision = design_decision(target, registry, lens, carry_value=True)
        request = create_generation_request(
            target, [decision], request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:live-design-arc:{revision.id}")),
            requested_candidate_count=1, compilation_authority=design_authority())
        persist_design_request(domain, request, actor_ref=roots.actor, access_policy_ref=roots.access_policy,
                               retention_policy_ref=roots.retention_policy, created_at_utc=STAMP)
        guard = SpendGuard(subject)
        generation = guard.wrap(executor.model_turn(model, purpose="design_candidate"), GENERATION_OUTPUT_TOKENS,
                                "generation")
        criticism = guard.wrap(executor.model_turn(model, purpose="design_criticism",
                                                   max_output_tokens=CRITICISM_OUTPUT_TOKENS),
                               CRITICISM_OUTPUT_TOKENS, "criticism")
        workspace = subject.app.state.first_party_exports["design-workspace.service"]
        workspace.open_request(request, registry=registry, criticism_turn=criticism, critic_model_id=model,
                               generation_turn=generation, generator_model_id=model)
        response = generate(subject, request.request_id, rounds=1)
        run = response.json()
        view = read(subject, request.request_id)
        outcomes = records(subject, OUTCOME_SCHEMA)
        observed = {
            "http_status": response.status_code, "model": model, "run": run,
            "pool": view["pool"],
            "candidates": [{"candidate_id": item["candidate_id"], "presented": item["presented"],
                            "nodes": [(node["node_id"], node["kind"]) for node in item["graph"]["nodes"]],
                            "verdict": item["verdict"]} for item in view["candidates"]],
            "critic_qualification": view["preparation"]["critic_qualification"],
            "calls": [{key: outcome.get(key) for key in ("provider_message_id", "request_id", "state", "stop_reason",
                                                         "usage")} for outcome in outcomes],
            "intents": [{key: item[key] for key in ("purpose", "max_output_tokens", "effort")}
                        for item in records(subject, DESIGN_INTENT_SCHEMA)],
            "spend_bound_usd_at_ceiling": round(guard.spent(), 6),
            "guard_refusals": guard.refused,
            "cap_usd": CAP_USD,
        }
        if EVIDENCE:
            with open(EVIDENCE, "w", encoding="utf-8") as handle:
                json.dump(observed, handle, ensure_ascii=False, indent=2)
        assert KEY not in json.dumps(observed)
        assert response.status_code == 201, observed
        assert observed["spend_bound_usd_at_ceiling"] <= CAP_USD
        assert run["model_calls"] == len(outcomes)
