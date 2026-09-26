"""TEST-ACTOR design arc (T038, T048): design requests over a REAL saved work, served
by the design workspace with scripted generation and criticism turns, so the product's
own arc (`PersistentDesignWorkspace.generate` → `run_candidate_generation` →
`persist_generation_result` → `run_candidate_criticism` → `persist_criticism_run` →
the honest pool) runs end to end without a model.

SIMULATED, never a release qualification (decisions.md 2026-09-25, "Independent
people"): the lens decision is qualified only by the fixture evidence verifier
(`proposed_lens`, `FixtureEvidenceVerifier`), and the critic qualification is the
TEST-ACTOR record of the test-only V3-verifying design id (`test_environments.
actor_record` under `actor_v3_design`). Production has neither: no lens is qualified
and `V3_VERIFYING_DESIGN_IDS` is empty. The generator and the critic are scripts
(`test-actor-generator`, `test-actor-critic`) whose outputs are shown under those
names; no verdict here is live.

Scenarios (one design request each, all over the same work model):

- `zero`: every round's graph carries a mandatory defect the critic rejects, and one
  round's model output is malformed (a refused call) — 0 presented, an honest shortfall.
- `one`: one passed graph, then only structural duplicates — 1 presented.
- `two`: two different passed graphs, then a duplicate — 2 presented.
- `three`: three different passed graphs in one round — 3 presented, one round.
- `cancel`: three graphs; the critic's second candidate waits until the owner cancels,
  so its criticism stops before the next call and the rest stay unreviewed.

Every scenario's generator also answers a revision (an owner's edit) by changing the
parent graph's `final-script` contract, which the critic then passes from scratch.
"""

from __future__ import annotations

import copy
import json
import threading
import time
from uuid import NAMESPACE_URL, uuid5

from app.domain.refs import EntityRef
from app.domain.schemas import ImmutableRecord
from app.services.design import confirm_work_model, create_generation_request
from app.services.design_persistence import persist_design_request
from app.tests.design_workspace_fixture import _shapes
from app.tests.test_design_generation import design_authority, design_decision, proposed_lens
from app.tests.test_design_orchestration import auto_critic
from app.tests.test_work_model_confirmation import confirmation, work_model

GENERATOR_ID = "test-actor-generator"
CRITIC_ID = "test-actor-critic"
STAMP = "2026-09-26T00:00:00.000000Z"
DEFECT = "필수 검증 단계 없음(시험용 결함)"
SCENARIOS = ("zero", "one", "two", "three", "cancel")
SIMULATION = {
    "label": "SIMULATED (test-actor) qualification — not a release qualification",
    "lens": "fixture evidence verifier (proposed_lens); no production lens is qualified",
    "critic": "test-actor V3-verifying design id under actor_v3_design; V3 is unverified in production",
}


def _free(graph):
    """A scripted model answer: the framework mints the identity fields itself."""

    value = copy.deepcopy(graph)
    for name in ("graph_id", "version"):
        value.pop(name, None)
    return value


def _defective(graph):
    value = copy.deepcopy(graph)
    value["nodes"][-1]["responsibility"] = f"{value['nodes'][-1]['responsibility']} {DEFECT}"
    return value


def _answer(*graphs):
    return json.dumps({"candidates": [{"graph": _free(item)} for item in graphs]}, ensure_ascii=False)


def _revised(parent):
    value = _free(parent)
    for contract in value["artifact_contracts"]:
        if contract["artifact_contract_id"] == "final-script":
            contract["max_total_bytes"] = max(1024, contract["max_total_bytes"] // 2)
    return json.dumps({"candidates": [{"graph": value}]}, ensure_ascii=False)


class ScriptedGenerator:
    """One scripted answer per round (the last repeats); a revision request is answered
    from the parent graph in the payload. Counts its calls."""

    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = 0

    def __call__(self, system, user):
        self.calls += 1
        payload = json.loads(user)
        if "revision" in payload:
            return _revised(payload["revision"]["parent_graph"])
        return self.rounds.pop(0) if len(self.rounds) > 1 else self.rounds[0]


class ScriptedCritic:
    """`auto_critic` that rejects a candidate whose roles carry the fixture defect.
    With `hold_after`, the review of that many-th candidate waits (bounded) until the
    owner has cancelled the running generation — so cancel is exercised deterministically."""

    def __init__(self, *, cancelled=None, hold_after=None):
        self._pass = auto_critic()
        self._cancelled = cancelled
        self._hold_after = hold_after
        self.reviews = 0
        self.calls = 0

    def __call__(self, system, user):
        self.calls += 1
        payload = json.loads(user)["input"]
        if "lens_pack" not in payload:
            self.reviews += 1
            if self._hold_after is not None and self.reviews == self._hold_after:
                deadline = time.monotonic() + 60
                while not self._cancelled() and time.monotonic() < deadline:
                    time.sleep(0.05)
        answer = self._pass(system, user)
        if DEFECT in user and "lens_pack" not in payload:
            review = json.loads(answer)
            review["findings"][0]["status"] = "fail"
            review["findings"][0]["reason"] = "필수 결함"
            return json.dumps(review, ensure_ascii=False)
        return answer


def _work_model(domain, revision_ref, source_refs):
    roots = domain.roots()
    raw = copy.deepcopy(work_model())
    raw["work_model_id"] = str(uuid5(NAMESPACE_URL, f"deeptwin:test-actor-arc-work-model:{revision_ref.id}"))
    raw["work_revision_ref"] = revision_ref.as_dict()
    raw["source_refs"] = [ref.as_dict() for ref in source_refs]
    raw["suitability"]["evidence_refs"] = [ref.as_dict() for ref in source_refs]
    prepared = confirm_work_model(raw, None)
    target = confirm_work_model(raw, confirmation(prepared.work_model_ref.as_dict()))
    record = ImmutableRecord.create(
        kind="work_model", id=raw["work_model_id"], version=1, created_at_utc=STAMP, actor_ref=roots.actor,
        parent_refs=(revision_ref,), purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content=target.work_model.as_dict())
    domain.put(record)  # idempotent: one work model per revision, shared by every scenario
    return target


def _rounds(scenario, target, decision):
    base, reshaped, third = _shapes(target, decision)
    if scenario == "zero":
        return ["not json: a malformed model answer", _answer(_defective(base)), _answer(_defective(reshaped))]
    if scenario == "one":
        return [_answer(base), _answer(base), _answer(base)]
    if scenario == "two":
        return [_answer(base, reshaped), _answer(base)]
    return [_answer(base, reshaped, third)]


def open_scenarios(app, revision_ref, source_refs, *, scenarios=SCENARIOS, critic_qualification=None):
    """Persist one design request per scenario over the work's actual revision and
    register each with the app's design workspace, with its scripted turns."""

    domain = app.state.domain_store
    roots = domain.roots()
    workspace = app.state.first_party_exports["design-workspace.service"]
    target = _work_model(domain, revision_ref, source_refs)
    registry, lens = proposed_lens(target)
    decision = design_decision(target, registry, lens)
    opened = {}
    for scenario in scenarios:
        request = create_generation_request(
            target, [decision],
            request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:test-actor-arc:{scenario}:{revision_ref.id}")),
            requested_candidate_count=3, compilation_authority=design_authority())
        persist_design_request(domain, request, actor_ref=roots.actor, access_policy_ref=roots.access_policy,
                               retention_policy_ref=roots.retention_policy, created_at_utc=STAMP)
        critic = (ScriptedCritic(cancelled=lambda rid=request.request_id: workspace.cancel_requested(rid),
                                 hold_after=2) if scenario == "cancel" else ScriptedCritic())
        generator = ScriptedGenerator(_rounds(scenario, target, decision))
        workspace.open_request(request, registry=registry, critic_qualification=critic_qualification,
                               criticism_turn=critic, critic_model_id=CRITIC_ID,
                               generation_turn=generator, generator_model_id=GENERATOR_ID)
        opened[scenario] = {"request": request, "generator": generator, "critic": critic}
    return opened


def simulated_qualification():
    """The TEST-ACTOR critic qualification (SIMULATED; see the module docstring)."""

    from app.services.critic_qualification import critic_qualification_from_suite
    from app.tests.test_environments import CRITIC_DIGEST, actor_record, actor_v3_design

    with actor_v3_design():
        return critic_qualification_from_suite(actor_record(), CRITIC_DIGEST)


def seed_for_work(app, work_id, *, scenarios=SCENARIOS, qualified=True):
    """The scenarios over the saved work's latest revision (the browser fixtures' seed)."""

    work = app.state.first_party_exports["works.service"].read(work_id)
    revision = EntityRef.from_dict(work["ref"])
    sources = [EntityRef.from_dict(item) for item in work.get("source_refs", [])]
    opened = open_scenarios(app, revision, sources, scenarios=scenarios,
                            critic_qualification=simulated_qualification() if qualified else None)
    return {"work_revision_ref": revision.as_dict(), "generator": GENERATOR_ID, "critic": CRITIC_ID,
            "simulation": SIMULATION,
            "requests": {name: item["request"].request_id for name, item in opened.items()}}


def run_in_thread(function, *args):
    """Start `function(*args)` in a daemon thread; returns (thread, box) with the result."""

    box = {}

    def target():
        try:
            box["value"] = function(*args)
        except Exception as error:  # noqa: BLE001 - the test reads it
            box["error"] = error

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    return thread, box
