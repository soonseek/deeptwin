"""T038 — ONE owner-authorized LIVE design arc end to end, through the product's own routes:
live generation of up to three candidates for one design request (one call per round, up to
two supplementation rounds), live criticism of every admitted candidate, the honest pool, and —
only if the pool presents a candidate — the owner's selection through the design workspace
routes (`derivations` select → the derived version → its mandatory re-review, live), then
preparation (`preparations`).

Preparation is attempted twice for the re-reviewed version: first with NO critic
qualification (it must be refused: live criticism is not qualification), then with the
SIMULATED test-actor qualification (`design_arc_fixture.simulated_qualification`, owner-
authorized for independent-person steps, decisions.md 2026-09-25). A preparation that succeeds
is labelled as resting on that simulation; it is never a release qualification.

Runs only with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and `DEEPTWIN_LIVE_DESIGN_SELECTION=1`; never
in the ordinary suite (the file name carries `_live_`). The owner authorized a hard cap of
USD 3.00 in total across attempts. Earlier attempts' spend is read from `DEEPTWIN_LIVE_LEDGER`
(updated after every call). Before EVERY send the guard bounds: earlier attempts + this run's
provider-reported spend + the next call's worst case (its exact prompt length at one token per
character, and its full output cap), all at ceiling rates at or above the listed price of the
model used; while the arc runs it also keeps a reserve for the owner's re-review, so the
selection step can complete. A send past the cap is refused (recorded by the arc as a refused
call, never as a candidate). The drivers never retry; there is no fallback model.

`DEEPTWIN_LIVE_WORK=specified` (attempt 5) runs the SAME arc over a DIFFERENT, better-specified
work authored by the simulated owner (`design_specified_work`, labelled): explicit completion
conditions, artifact formats, approver inputs, sources and "nothing is regenerated". Unset, the
arc runs over the attempts 1–4 work (`design_arc_fixture._work_model`).

`DEEPTWIN_LIVE_REPLAY_GENERATION=<raw answer file>` answers the arc's generation turn with an
EARLIER live generation answer saved in the evidence, sending nothing (no spend, no retry of that
call); it is recorded as a replay with the file's sha256. Used when a run stopped in the product
after a completed live generation, so the same live graphs reach live criticism. Criticism, the
re-review and every other model call stay live.

`DEEPTWIN_LIVE_CATALOG_ONLY=<path>` writes the live catalog's model list to that path (outside
the evidence) and stops before any paid call. The model is the first one the catalog lists
unless `DEEPTWIN_LIVE_MODEL` names one; its identifier comes from the provider, never from this
file, and is redacted from the evidence. Raw model answers (model output only) go to
`DEEPTWIN_LIVE_EVIDENCE_DIR` the moment they arrive; the key is never printed or stored.
"""

import json
import os
from hashlib import sha256
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
from app.tests.design_arc_fixture import (
    SIMULATION,
    STAMP,
    _work_model,
    simulated_qualification,
)
from app.tests.design_specified_work import (
    AUTHOR,
    specified_decision,
    specified_work_model,
    specified_work_with_source,
)
from app.tests.test_claude_live_path import claude
from app.tests.test_design_arc import generate, post, read, work_with_source
from app.tests.test_design_generation import (
    design_authority,
    design_decision,
    proposed_lens,
)
from app.tests.test_runs_api import owner_app

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL")
EVIDENCE = Path(os.environ.get("DEEPTWIN_LIVE_EVIDENCE_DIR") or ".")
LEDGER = os.environ.get("DEEPTWIN_LIVE_LEDGER")
LABEL = os.environ.get("DEEPTWIN_LIVE_ATTEMPT") or "attempt1"
CATALOG_ONLY = os.environ.get("DEEPTWIN_LIVE_CATALOG_ONLY")
SPECIFIED = os.environ.get("DEEPTWIN_LIVE_WORK") == "specified"
REPLAY = os.environ.get("DEEPTWIN_LIVE_REPLAY_GENERATION")
CAP_USD = 3.00
MAX_ROUNDS = int(os.environ.get("DEEPTWIN_LIVE_ROUNDS") or 3)  # one request, up to two supplementation rounds
GENERATION_OUTPUT_TOKENS = int(os.environ.get("DEEPTWIN_LIVE_GENERATION_TOKENS") or 24_000)  # up to 3 graphs
CRITICISM_OUTPUT_TOKENS = 6_000
# kept free while the arc runs, so the owner's re-review (≈ 8 calls) can complete
REREVIEW_RESERVE_USD = float(os.environ.get("DEEPTWIN_LIVE_RESERVE_USD") or 1.00)
CANDIDATES = int(os.environ.get("DEEPTWIN_LIVE_CANDIDATES") or 3)
# at or above the listed per-token price of the model used (USD 4 / 20 per MTok)
CEILING_INPUT_USD_PER_MTOK = 5.0
CEILING_OUTPUT_USD_PER_MTOK = 25.0
REDACTED = "<live-catalog-model>"

pytestmark = pytest.mark.skipif(not KEY or os.environ.get("DEEPTWIN_LIVE_DESIGN_SELECTION") != "1",
                                reason="the live design selection needs the key and DEEPTWIN_LIVE_DESIGN_SELECTION=1")


def _cost(usage) -> float:
    inputs = sum(int(usage.get(name) or 0) for name in ("input_tokens", "cache_creation_input_tokens",
                                                          "cache_read_input_tokens"))
    return (inputs * CEILING_INPUT_USD_PER_MTOK + int(usage.get("output_tokens") or 0)
            * CEILING_OUTPUT_USD_PER_MTOK) / 1e6


def _records(subject, schema):
    """(record id, content) of every decision record of `schema`, in insertion order."""
    with subject.domain._connection() as db:
        rows = db.execute("SELECT id, body FROM domain_records WHERE kind='decision_record' ORDER BY rowid").fetchall()
    found = [(row["id"], json.loads(bytes(row["body"]))["content"]) for row in rows]
    return [(identifier, content) for identifier, content in found if content.get("schema_version") == schema]


def _prior() -> dict:
    if LEDGER and os.path.exists(LEDGER):
        with open(LEDGER, encoding="utf-8") as handle:
            return json.load(handle)
    return {"attempts": []}


class Guard:
    """Refuses a send whose worst case would take all attempts together past the cap (and,
    during the arc, into the re-review reserve); saves every raw answer before any admission."""

    def __init__(self, subject):
        self.subject = subject
        self.prior = _prior()
        self.prior_usd = sum(item["bound_usd"] for item in self.prior["attempts"] if item["label"] != LABEL)
        self.phase = "arc"
        self.refused = []
        self.sends = []

    def spent(self) -> float:
        return sum(_cost(content.get("usage") or {}) for _id, content in _records(self.subject, OUTCOME_SCHEMA))

    def ledger(self):
        if LEDGER:
            attempts = [item for item in self.prior["attempts"] if item["label"] != LABEL]
            attempts.append({"label": LABEL, "bound_usd": round(self.spent(), 6)})
            with open(LEDGER, "w", encoding="utf-8") as handle:
                json.dump({"cap_usd": CAP_USD, "rates_usd_per_mtok": [CEILING_INPUT_USD_PER_MTOK,
                                                                      CEILING_OUTPUT_USD_PER_MTOK],
                           "attempts": attempts}, handle, indent=2)

    def wrap(self, turn, cap_tokens, stage):
        def guarded(system, user):
            reserve = REREVIEW_RESERVE_USD if self.phase == "arc" else 0.0
            worst = ((len(system) + len(user)) * CEILING_INPUT_USD_PER_MTOK
                     + cap_tokens * CEILING_OUTPUT_USD_PER_MTOK) / 1e6
            bound = self.prior_usd + self.spent() + worst + reserve
            entry = {"n": len(self.sends) + 1, "phase": self.phase, "stage": stage,
                     "bound_usd_before_send": round(bound, 4),
                     "prompt_sha256": sha256(json.dumps({"system": system, "user": user}, ensure_ascii=False,
                                                        sort_keys=True).encode("utf-8")).hexdigest()}
            if bound > CAP_USD:
                self.refused.append({**entry, "refused": "the cap would be exceeded"})
                raise RuntimeError("the spend guard refused this send: the cap would be exceeded")
            self.sends.append(entry)
            try:
                raw = turn(system, user)
            finally:
                self.ledger()
            try:
                purpose = json.loads(raw).get("purpose")
            except (ValueError, AttributeError):
                purpose = None
            entry["answer_purpose"] = purpose
            name = f"{LABEL}-{entry['n']:02d}-{self.phase}-{stage}{'-' + purpose if purpose else ''}.txt"
            entry["raw_answer"] = name
            (EVIDENCE / name).write_text(raw, encoding="utf-8")  # saved first, before any admission
            return raw

        return guarded


def _redact(value, model):
    return json.loads(json.dumps(value, ensure_ascii=False).replace(model, REDACTED))


def test_one_live_design_arc_to_owner_selection(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=60,
                                                   max_design_output_tokens=GENERATION_OUTPUT_TOKENS))
    with owner_app(tmp_path, executor) as subject:
        assert claude(subject, "key", {"secret": KEY}).status_code == 200
        catalog = claude(subject, "catalog")
        assert catalog.status_code == 200, catalog.json()
        listed = catalog.json()["catalog"]["model_ids"]
        if CATALOG_ONLY:
            Path(CATALOG_ONLY).write_text(json.dumps(listed), encoding="utf-8")
            return
        model = MODEL or listed[0]
        assert model in listed, "the chosen model is not in the live catalog"
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        revision, sources = (specified_work_with_source if SPECIFIED else work_with_source)(subject)
        domain = subject.app.state.domain_store
        roots = domain.roots()
        target = (specified_work_model if SPECIFIED else _work_model)(domain, revision, sources)
        registry, lens = proposed_lens(target)
        decision = (specified_decision(target, registry, lens) if SPECIFIED
                    else design_decision(target, registry, lens, carry_value=True))
        request = create_generation_request(
            target, [decision],
            request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:live-design-selection:{LABEL}:{revision.id}")),
            requested_candidate_count=CANDIDATES, compilation_authority=design_authority())
        persist_design_request(domain, request, actor_ref=roots.actor, access_policy_ref=roots.access_policy,
                               retention_policy_ref=roots.retention_policy, created_at_utc=STAMP)
        guard = Guard(subject)
        replays = []
        if REPLAY:
            saved = Path(REPLAY).read_text(encoding="utf-8")

            def generation(system, user):  # nothing is sent: an earlier live answer, recorded as such
                replays.append({"replayed_raw_answer": Path(REPLAY).name,
                                "sha256": sha256(saved.encode("utf-8")).hexdigest(),
                                "prompt_sha256": sha256(json.dumps({"system": system, "user": user},
                                                                   ensure_ascii=False, sort_keys=True)
                                                        .encode("utf-8")).hexdigest()})
                return saved
        else:
            generation = guard.wrap(executor.model_turn(model, purpose="design_candidate"),
                                    GENERATION_OUTPUT_TOKENS, "generation")
        criticism = guard.wrap(executor.model_turn(model, purpose="design_criticism",
                                                   max_output_tokens=CRITICISM_OUTPUT_TOKENS),
                               CRITICISM_OUTPUT_TOKENS, "criticism")
        workspace = subject.app.state.first_party_exports["design-workspace.service"]
        # live criticism is not qualification: the arc runs with NO critic qualification
        workspace.open_request(request, registry=registry, criticism_turn=criticism, critic_model_id=model,
                               generation_turn=generation, generator_model_id=model)
        response = generate(subject, request.request_id, rounds=MAX_ROUNDS)
        run = response.json()
        view = read(subject, request.request_id)
        owner = None
        presented = view["pool"]["presented_candidate_ids"]
        if response.status_code == 201 and presented:
            guard.phase = "owner"
            chosen = presented[0]
            derived = post(subject, request.request_id, "derivations", {
                "schema_version": "design-derivation-command-v1", "action": "select",
                "parent_candidate_ids": [chosen], "instruction": None})
            owner = {"selected_candidate_id": chosen, "derivation_http_status": derived.status_code,
                     "derivation": derived.json()}
            if derived.status_code == 201:
                reviewed = post(subject, request.request_id, "reviews", {
                    "schema_version": "design-review-command-v1", "derivation_id": derived.json()["derivation_id"]})
                owner.update(review_http_status=reviewed.status_code, review=reviewed.json())
                version = reviewed.json().get("reviewed_candidate") if reviewed.status_code == 201 else None
                if version and version.get("verdict"):
                    body = {"schema_version": "design-prepare-command-v1", "candidate_id": version["candidate_id"]}
                    unqualified = post(subject, request.request_id, "preparations", body)
                    owner.update(prepare_without_qualification={"http_status": unqualified.status_code,
                                                                "body": unqualified.json()})
                    # the owner-authorized SIMULATED qualification (test actor), same turns
                    workspace.open_request(request, registry=registry, critic_qualification=simulated_qualification(),
                                           criticism_turn=criticism, critic_model_id=model,
                                           generation_turn=generation, generator_model_id=model)
                    simulated = read(subject, request.request_id)["preparation"]
                    prepared = post(subject, request.request_id, "preparations", body)
                    owner.update(simulated_preparation_view=simulated, simulation=SIMULATION,
                                 prepare_with_simulated_qualification={"http_status": prepared.status_code,
                                                                       "body": prepared.json()})
        final = read(subject, request.request_id)
        intents = {identifier: content for identifier, content in _records(subject, DESIGN_INTENT_SCHEMA)}
        calls = []
        for n, (_id, outcome) in enumerate(_records(subject, OUTCOME_SCHEMA), start=1):
            intent = intents.get(outcome["intent_ref"]["id"], {})
            send = next((item for item in guard.sends if item["prompt_sha256"] == intent.get("prompt_sha256")), {})
            calls.append({"n": n, "phase": send.get("phase"), "stage": send.get("stage"),
                          "answer_purpose": send.get("answer_purpose"), "raw_answer": send.get("raw_answer"),
                          "intent_purpose": intent.get("purpose"), "max_output_tokens": intent.get("max_output_tokens"),
                          "effort": intent.get("effort"), "bound_usd_before_send": send.get("bound_usd_before_send"),
                          **{key: outcome.get(key) for key in ("provider_message_id", "request_id", "state",
                                                               "stop_reason", "usage")},
                          "spend_usd_at_ceiling": round(_cost(outcome.get("usage") or {}), 6)})
        observed = {
            "label": LABEL, "model": model,
            "work": ({"scenario": "specified (attempt 5): release notes from one stored changelog",
                      "author": AUTHOR, "work_model": target.work_model.as_dict()}
                     if SPECIFIED else {"scenario": "attempts 1-4 work (YouTube research/script)"}),
            "generation_http_status": response.status_code, "run": run,
            "pool": final["pool"],
            "candidates": [{"candidate_id": item["candidate_id"], "presented": item["presented"],
                            "nodes": [(node["node_id"], node["kind"]) for node in item["graph"]["nodes"]],
                            "verdict": item["verdict"]} for item in final["candidates"]],
            "derivations": final["derivations"],
            "owner_path": owner,
            "refusals": workspace.criticism_refusals(request.request_id),
            "calls": calls,
            "guard_refusals": guard.refused,
            "replayed_generation": replays,
            "spend_usd_at_ceiling_this_attempt": round(guard.spent(), 6),
            "spend_usd_at_ceiling_earlier_attempts": round(guard.prior_usd, 6),
            "cap_usd": CAP_USD, "rereview_reserve_usd": REREVIEW_RESERVE_USD, "max_rounds": MAX_ROUNDS,
            "requested_candidate_count": CANDIDATES, "generation_output_tokens": GENERATION_OUTPUT_TOKENS,
            "ceiling_usd_per_mtok": [CEILING_INPUT_USD_PER_MTOK, CEILING_OUTPUT_USD_PER_MTOK],
            "evidence_id": str(uuid4()),
        }
        guard.ledger()
        text = json.dumps(_redact(observed, model), ensure_ascii=False, indent=2)
        (EVIDENCE / f"{LABEL}.json").write_text(text, encoding="utf-8")
        assert KEY not in text
        assert response.status_code == 201, text[:4000]
        assert guard.prior_usd + guard.spent() <= CAP_USD
        # the arc counts a send the guard refused as a call attempt; nothing was sent for it
        assert run["model_calls"] == (len(replays) + sum(1 for item in guard.sends if item["phase"] == "arc")
                                      + sum(1 for item in guard.refused if item["phase"] == "arc"))
