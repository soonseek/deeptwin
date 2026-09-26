# US2 — T038: generation → criticism → selection, 0/1/2/3 / revision / cancel (2026-09-26)

Status: **the design arc now runs end to end through the product's own route, drivers and
persistence, from the work page's design workspace, in a real browser: 0, 1, 2 and 3 presented
candidates with the real count and every exclusion reason, a refused model call recorded as a
refusal, an owner's edit realized by a revision call and re-reviewed from scratch, and the owner's
cancel stopping the arc before its next model call. ONE live run (real generation + real
criticism for one request) went through the same route over the owner's Claude connection.**
The deterministic cases use scripted TEST-ACTOR model turns and a SIMULATED qualification; they
are never presented as live, and none of this is a release qualification (decisions.md
2026-09-25). T038 is **not ticked**: the live critic's answer was refused by the contract, so no
live verdict or live selection exists yet (see "Not ticked"); the release qualification is T077
and stays open; the product gate stays closed.

## What landed

- **`POST /api/v1/design-requests/{id}/generations`** (`design_requests.generate`,
  `design-generation-command-v1 {command_id, max_rounds 1..3}`) —
  `PersistentDesignWorkspace.generate` runs the arc for one registered request:
  - per round, one `run_candidate_generation` call through the host-registered generation turn;
    the accepted candidates persisted by `persist_generation_result`, each criticized by
    `run_candidate_criticism` and persisted by `persist_criticism_run`; the honest pool
    (`assemble_selection_pool`) re-assembled after each round;
  - it stops at three structurally different passed candidates or at the owner's round limit;
    a shortfall ends as the real count (never padded);
  - a refused generation or criticism call (malformed output, contract violation) is recorded as
    a refusal of that round, never as a candidate; a candidate whose criticism did not complete
    stays `unreviewed` and is never presented;
  - each run persists one `design_generation_run` record (outcome `filled | shortfall |
    cancelled`, rounds, model calls, the generator/critic identities, refusals, the candidates it
    produced and those left unreviewed), parented to the request; an exact command replay
    returns the stored run and calls nothing; a second concurrent run is a `conflict`.
- **`POST …/cancellations`** (`design_requests.cancel`) — the owner stops a running arc. Every
  model call goes through a counting wrapper that refuses to send once cancel is set: a call
  already sent is not recalled, what completed stays recorded, the rest stays unreviewed.
- **Edit re-review** — `review` of an `edit` derivation, when a generation turn is registered,
  makes one revision call (`run_candidate_generation(revision=(parent, instruction))`: the
  payload carries the exact accepted parent graph and the owner's instruction, one candidate is
  asked for, the framework mints the new graph identity, the candidate's parent is the exact
  parent candidate). The call, graph and candidate hang off the derivation record (not the
  request), so the pool never counts them; the candidate is criticized from scratch, no verdict
  inherited. A merge still has no generation turn: `derived_graph_not_generated`.
- `persist_design_request` persists an issued request before its first round; later rounds reuse
  exactly that record (a stored request with other content is refused).
- **Workspace UI** (`app/static/workspace.mjs`): a `후보 생성` section — the generator and critic
  identities, `후보 생성·평가 실행 (최대 3회)`, `생성 취소` (enabled only while running), every
  recorded run's text (e.g. `통과한 구조적으로 다른 후보가 0개뿐입니다 (생성 3회 한도). 채워 넣지
  않았습니다. … 거절된 호출 1개: 1회차 생성 — model response is not valid JSON.`); the review
  button enabled for what the instance realizes (`review.realizes`); a qualified record outside the
  release designs is labelled `시뮬레이션(테스트 행위자) 자격이며 출시 자격이 아닙니다`
  (`preparation.simulated_qualification`).
- Routes: 134 → 137 installed (with T048's `runs.environments`); pins and
  docs/release/api-compatibility.md regenerated.

## TEST-ACTOR scenarios (SIMULATED; `app/tests/design_arc_fixture.py`)

The lens decision is qualified only by the fixture evidence verifier (`proposed_lens`); the critic
qualification is the TEST-ACTOR record of the test-only V3-verifying design id
(`actor_record` under `actor_v3_design`). Production has neither. The generator and critic are
scripts (`test-actor-generator`, `test-actor-critic`, named on every verdict); the critic rejects a
graph that carries the fixture defect.

| scenario | scripted rounds | observed |
|---|---|---|
| zero | malformed answer; two defective graphs | 3 rounds, `shortfall`, 0 presented, 2 rejected (`review_fail`), 1 refused generation call |
| one | one passed graph, then duplicates | 3 rounds, 1 presented, 2 `structural_duplicate` |
| two | two different passed graphs, then a duplicate | 3 rounds, 2 presented |
| three | three different passed graphs | 1 round, `filled`, 3 presented, 7 model calls |
| cancel | three graphs; the 2nd review waits for the owner's cancel | `cancelled`, 4 model calls, 1 presented, 2 `unreviewed` |
| revision (on `three`) | edit → revision call | new candidate, parent = the edited one, `final-script` size halved, passed from scratch, then prepared (`prepared`, `not_activated`) |

## Observed (offline)

- `test_design_arc.py`: 4 passed — 0/1/2/3 with counts, reasons, verdict identities and exact call
  counts, replay; edit → revision → re-review and merge still unavailable; cancel before the next
  call (4 calls, 2 unreviewed); generation unavailable without turns, bad `max_rounds` refused.
- `workspace.test.mjs`: 10 passed (4 new: the unavailable reason, generate/cancel posting and
  their states, the run texts, edit re-review and the simulated label).
- **`app/tests/browser-design.test.mjs`: 1 passed in real Chrome** against the real supported
  server (`app/tests/fixtures/design_arc_server.py`) on `work.html`: a real work saved with an
  original; zero → one → two → three → revision (edit, re-review, prepare) → merge refusal →
  cancel, all from the page, no page errors.

## The ONE live run (2026-09-26)

`app/tests/test_claude_live_design_arc.py` (`DEEPTWIN_LIVE_DESIGN_ARC=1`, key from
`DEEPTWIN_LIVE_ANTHROPIC_API_KEY`, never printed). The model was the first one the live catalog
listed (its identifier came from the provider; not written in code or here). One request, one
candidate per call, `max_rounds=1`, no retry, no fallback, NO critic qualification (live criticism
is not qualification). Hard cap USD 3.00 enforced by a spend guard before every send (spend so far
from provider-reported usage + the next call's prompt length and output cap, at ceiling rates of
USD 10/50 per MTok in/out).

| call | purpose | provider message id | request id | state / stop | input / output tokens |
|---|---|---|---|---|---|
| 1 | design_candidate (cap 12,000, effort medium) | `msg_011CfRHheVvjmfEdBKVzE8eo` | `req_011CfRHhddqdM3XQuudEmyG3` | completed / end_turn | 5,708 / 4,275 |
| 2 | design_criticism, review (cap 6,000, effort medium) | `msg_011CfRHkFWuQsJXjmVdfYuY5` | `req_011CfRHkF2Nt9V9MHLRPpGUn` | completed / end_turn | 5,043 / 3,211 |

- **Generation: accepted.** The framework admitted one real candidate: `research`, `verify`,
  `writer` (agents), `publish_gate` (human gate), `publish_handoff` (deterministic).
- **Criticism: refused.** The critic's review answer violated the critic contract
  (`the review response violates the contract`); the arc recorded it as a refused criticism call,
  made no further call, and left the candidate `unreviewed`. Pool: **0 presented of 1** — an honest
  shortfall, no verdict fabricated or inherited.
- Spend: 10,751 input + 7,486 output tokens. At the listed price of the model used (USD 4 / 20 per
  MTok) that is **USD ≈ 0.19**; the guard's ceiling bound was USD 0.48. No guard refusal. Total
  live spend for T038: **USD ≈ 0.19 of the 3.00 cap** (one attempt).
- The raw model text was not saved (only digests are sealed), so why the review violated the
  contract is not established; that and a complete live verdict remain open (see Open).

## Not ticked

The 0/1/2/3, revision and cancel paths are exercised in `app/tests/browser-design.test.mjs` with
the product's own generation, criticism, persistence and selection code, scripted model turns and
the simulation labelled; no fixture verdict is presented as live. But T038 says *real*
generation → critique → selection: the one authorized live run produced a real accepted candidate
and a real critic call whose answer the contract refused, so there is no live verdict and no live
selection. T038 therefore stays open for a live critique that completes and a live selection (and,
in any case, none of this is a release qualification: no critic or lens is qualified in
production, `V3_VERIFYING_DESIGN_IDS` is empty and V3 is unverified; T077).

## Open

- The live critic's review did not satisfy the contract in the one authorized attempt, so no live
  verdict exists yet for a live candidate; no live candidate has been selected or prepared.
- No production path registers a design request with generation/criticism turns: the host still
  has to call `open_request` (the owner's Claude connection is not wired to the workspace by a
  route), and a request is not restorable after a restart (T037's open item).
- A merge has no generation turn that realizes it.
- Preparation stays impossible in production (T077).
