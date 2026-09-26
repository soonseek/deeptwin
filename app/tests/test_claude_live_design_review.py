"""T038 — the LIVE review diagnosis: one real review of a freshly generated candidate, with
every raw model answer saved the moment it arrives, so a contract refusal of the critic's
answer can be read (the first live design-arc run kept only digests).

Runs only with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and `DEEPTWIN_LIVE_DESIGN_REVIEW=1`; never in
the ordinary suite (the file name carries `_live_`). The owner authorized a hard cap of
USD 1.50 for this diagnosis in total, across attempts: the spend of earlier attempts is read
from `DEEPTWIN_LIVE_LEDGER` (a JSON file this test updates after every call), and before EVERY
send a guard bounds earlier attempts + this run's spend so far (provider-reported usage) + the
next call's worst case (its exact prompt length, one token per character, and its output
cap) at ceiling rates at or above the listed price of the model, and refuses to send past the
cap. The drivers never retry; there is no fallback model.

Two modes, one request each, `max_rounds=1`, one candidate:
- default: live generation, then live criticism of what it admits;
- `DEEPTWIN_LIVE_GENERATION_REPLAY=<saved raw generation answer>`: the confirmation run — the
  SAME graph the earlier attempt's model generated is replayed offline through the product's
  own admission (no model call; the candidate gets a new framework identity), then criticized
  live. When the pool presents it, the owner's selection (`derivations`, action `select`) is
  made through the route.

The lens decision is the fixture's (SIMULATED lens qualification) and there is NO critic
qualification: live criticism is not qualification. The key goes in through the owner's
connection route (server memory only) and is never printed, stored or asserted on. Raw
answers and non-secret evidence go to `DEEPTWIN_LIVE_EVIDENCE_DIR`.
"""

import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest

from app.services.claude_run_executor import (
    DESIGN_INTENT_SCHEMA,
    OUTCOME_SCHEMA,
    ClaudeRunExecutor,
    LiveLimits,
)
from app.services.design import create_generation_request
from app.services.design_persistence import persist_design_request
from app.tests.design_arc_fixture import STAMP, _work_model
from app.tests.test_claude_design_turn import records
from app.tests.test_claude_live_path import claude
from app.tests.test_design_arc import generate, post, read, work_with_source
from app.tests.test_design_generation import design_authority, design_decision, proposed_lens
from app.tests.test_runs_api import owner_app

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL")
EVIDENCE = Path(os.environ.get("DEEPTWIN_LIVE_EVIDENCE_DIR") or ".")
LEDGER = os.environ.get("DEEPTWIN_LIVE_LEDGER")
REPLAY = os.environ.get("DEEPTWIN_LIVE_GENERATION_REPLAY")
CAP_USD = 1.50
GENERATION_OUTPUT_TOKENS = 10_000
CRITICISM_OUTPUT_TOKENS = 6_000
# at or above the listed per-token price of the model used (USD 4 / 20 per MTok)
CEILING_INPUT_USD_PER_MTOK = 5.0
CEILING_OUTPUT_USD_PER_MTOK = 25.0

pytestmark = pytest.mark.skipif(not KEY or os.environ.get("DEEPTWIN_LIVE_DESIGN_REVIEW") != "1",
                                reason="the live review diagnosis needs the key and DEEPTWIN_LIVE_DESIGN_REVIEW=1")


def _cost(usage) -> float:
    inputs = sum(int(usage.get(name) or 0) for name in ("input_tokens", "cache_creation_input_tokens",
                                                          "cache_read_input_tokens"))
    return (inputs * CEILING_INPUT_USD_PER_MTOK + int(usage.get("output_tokens") or 0)
            * CEILING_OUTPUT_USD_PER_MTOK) / 1e6


def _prior() -> dict:
    if LEDGER and os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as handle:
            return json.load(handle)
    return {"attempts": []}


class Guard:
    """Refuses a send whose worst case would take all attempts together past the cap, and
    saves every raw answer before the drivers see it."""

    def __init__(self, subject, label):
        self.subject = subject
        self.label = label
        self.prior = _prior()
        self.prior_usd = sum(item["bound_usd"] for item in self.prior["attempts"])
        self.refused = []
        self.saved = []

    def spent(self) -> float:
        return sum(_cost(item.get("usage") or {}) for item in records(self.subject, OUTCOME_SCHEMA))

    def ledger(self):
        if LEDGER:
            attempts = [item for item in self.prior["attempts"] if item["label"] != self.label]
            attempts.append({"label": self.label, "bound_usd": round(self.spent(), 6)})
            with open(LEDGER, "w", encoding="utf-8") as handle:
                json.dump({"cap_usd": CAP_USD, "attempts": attempts}, handle, indent=2)

    def wrap(self, turn, cap_tokens, stage):
        def guarded(system, user):
            bound = self.prior_usd + self.spent() + ((len(system) + len(user)) * CEILING_INPUT_USD_PER_MTOK
                                                     + cap_tokens * CEILING_OUTPUT_USD_PER_MTOK) / 1e6
            if bound > CAP_USD:
                self.refused.append({"stage": stage, "bound_usd": round(bound, 4)})
                raise RuntimeError("the spend guard refused this send: the cap would be exceeded")
            try:
                raw = turn(system, user)
            finally:
                self.ledger()
            path = EVIDENCE / f"{self.label}-{len(self.saved) + 1:02d}-{stage}.txt"
            path.write_text(raw, encoding="utf-8")  # saved first, before any admission
            self.saved.append(str(path))
            return raw

        return guarded


def test_one_live_review_of_a_fresh_candidate(tmp_path):
    label = "confirm" if REPLAY else "diagnose"
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=12,
                                                   max_design_output_tokens=GENERATION_OUTPUT_TOKENS))
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
            target, [decision], request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:live-review:{label}:{revision.id}")),
            requested_candidate_count=1, compilation_authority=design_authority())
        persist_design_request(domain, request, actor_ref=roots.actor, access_policy_ref=roots.access_policy,
                               retention_policy_ref=roots.retention_policy, created_at_utc=STAMP)
        guard = Guard(subject, label)
        if REPLAY:
            replayed = Path(REPLAY).read_text(encoding="utf-8")
            generation, generator_id = (lambda system, user: replayed), "replayed-live-generation"
        else:
            generation = guard.wrap(executor.model_turn(model, purpose="design_candidate"),
                                    GENERATION_OUTPUT_TOKENS, "generation")
            generator_id = model
        criticism = guard.wrap(executor.model_turn(model, purpose="design_criticism",
                                                   max_output_tokens=CRITICISM_OUTPUT_TOKENS),
                               CRITICISM_OUTPUT_TOKENS, "criticism")
        workspace = subject.app.state.first_party_exports["design-workspace.service"]
        workspace.open_request(request, registry=registry, criticism_turn=criticism, critic_model_id=model,
                               generation_turn=generation, generator_model_id=generator_id)
        response = generate(subject, request.request_id, rounds=1)
        run = response.json()
        view = read(subject, request.request_id)
        selection = None
        if view["pool"]["presented_candidate_ids"]:
            chosen = view["pool"]["presented_candidate_ids"][0]
            derived = post(subject, request.request_id, "derivations", {
                "schema_version": "design-derivation-command-v1", "action": "select",
                "parent_candidate_ids": [chosen], "instruction": None})
            selection = {"http_status": derived.status_code, "body": derived.json()}
        outcomes = records(subject, OUTCOME_SCHEMA)
        observed = {
            "label": label, "http_status": response.status_code, "model": model, "generator": generator_id,
            "run": run, "pool": view["pool"],
            "candidates": [{"candidate_id": item["candidate_id"], "presented": item["presented"],
                            "nodes": [(node["node_id"], node["kind"]) for node in item["graph"]["nodes"]],
                            "verdict": item["verdict"]} for item in view["candidates"]],
            "selection": selection,
            "refusals": workspace.criticism_refusals(request.request_id),
            "critic_qualification": view["preparation"]["critic_qualification"],
            "calls": [{key: outcome.get(key) for key in ("provider_message_id", "request_id", "state", "stop_reason",
                                                         "usage")} for outcome in outcomes],
            "intents": [{key: item[key] for key in ("purpose", "max_output_tokens", "effort")}
                        for item in records(subject, DESIGN_INTENT_SCHEMA)],
            "raw_answers": guard.saved,
            "spend_bound_usd_this_run": round(guard.spent(), 6),
            "spend_bound_usd_earlier_attempts": round(guard.prior_usd, 6),
            "guard_refusals": guard.refused, "cap_usd": CAP_USD, "evidence_id": str(uuid4()),
        }
        guard.ledger()
        (EVIDENCE / f"{label}.json").write_text(json.dumps(observed, ensure_ascii=False, indent=2), encoding="utf-8")
        assert KEY not in json.dumps(observed)
        assert response.status_code == 201, observed
        assert guard.prior_usd + guard.spent() <= CAP_USD
        assert run["model_calls"] == len(outcomes) + (1 if REPLAY else 0)
