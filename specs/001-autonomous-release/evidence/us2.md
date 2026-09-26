# US2 — T038: generation → criticism → selection, 0/1/2/3 / revision / cancel (2026-09-26)

Status: **the design arc now runs end to end through the product's own route, drivers and
persistence, from the work page's design workspace, in a real browser: 0, 1, 2 and 3 presented
candidates with the real count and every exclusion reason, a refused model call recorded as a
refusal, an owner's edit realized by a revision call and re-reviewed from scratch, and the owner's
cancel stopping the arc before its next model call. ONE live run (real generation + real
criticism for one request) went through the same route over the owner's Claude connection.**
The deterministic cases use scripted TEST-ACTOR model turns and a SIMULATED qualification; they
are never presented as live, and none of this is a release qualification (decisions.md
2026-09-25). T038 is **not ticked**: a live critique now completes (2026-09-26, later — the
first run's contract refusal was diagnosed and its cause fixed in the critic prompt), but the live
critic rejected the one live candidate, so nothing was presented and no live selection exists
(see "Not ticked"); the release qualification is T077 and stays open; the product gate stays
closed.

**Update 2026-09-26 (later): live review diagnosis, restorable requests, creation from the work
page** — see the section of that name below.

**Update 2026-09-26 (latest): one live design arc to the owner's selection.** Two attempts were
made under a USD 3.00 cap. Attempt 1 generated 2 candidates live; attempt 2 generated 1 after
one generation-prompt improvement. All 3 were criticized live with 0 contract refusals, and all 3
were **rejected**. Nothing was presented, so there was no owner selection, no re-review and no
preparation. T038 stays **not ticked**. See the section "ONE live design arc to the owner's
selection".

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
  contract was not established then; it is diagnosed in the update below.

## 2026-09-26 (later): live review diagnosis, restorable requests, creation from the work page

### 1. The live review's contract failure: diagnosed, fixed in the prompt

- **Persisted diagnosis.** A completed critic answer the contract refuses now raises
  `CriticismStageRefused` (`app/services/design_criticism_live.py`). The closed message is kept
  (`the review response violates the contract`), and two things go with it: the model's own
  answer (up to 64,000 UTF-8 bytes, with a truncation flag; model output only, never the prompt,
  a key or a header) and the exact rule it broke. The rule comes from
  `diagnose_contract_violation`, which replays the pinned contract's own checks.
  `app/critic_contract.py` is pinned by the release FROZEN manifests and was **not edited**; the
  contract still reduces every reason to one message. Any disagreement with `parse_response` is
  reported, never resolved in the answer's favour. The workspace persists a
  `design_criticism_refusal` record on the candidate before the refusal propagates. The run's
  refusal entry carries `purpose`, `violation` and `refusal_record_id`, and
  `criticism_refusals(request_id)` reads them back.
- **Replay.** The first run's raw review text could not be recovered: only digests had been
  sealed, and its store was a test temporary. So ONE new live review of a freshly generated
  candidate was run (`app/tests/test_claude_live_design_review.py`, `_live_`). It read the key
  from `DEEPTWIN_LIVE_ANTHROPIC_API_KEY`, never printed, and used the first model the live
  catalog listed. The hard cap was **USD 1.50 in total** across attempts, checked before every
  send against a ledger of earlier attempts at ceiling rates of USD 5 / 25 per MTok (above the
  listed USD 4 / 20).
- **Root cause: two contract rules the prompt did not state.**
  1. The critic wrapped its JSON answer in a markdown code fence (`json` fence). This is the
     first violation: `json: Expecting value at line 1 column 1`.
  2. Inside the answer, it cited the criteria document under the design decision's id (the
     prefix of the criterion ids, `00000000-…-221`) instead of the criteria document's own `id`
     field (`review:…`). The contract refuses that citation as not visible. The model even noted
     the right id in its own uncertainty.
  The general profile does say "Return only the JSON…", but neither rule was stated where the
  critic reads the citation rules.
- **Fix, in the prompt only** (like the earlier `_CITATION_RULE` fix): `_CITATION_RULE` now
  states that a citation's `document_id` and `version` are exactly the cited document's own `id`
  and `version` fields: the criteria document's own id, never a criterion id or part of one. A new
  `_OUTPUT_RULE` states that the answer is the JSON object alone: first character `{`, last `}`,
  no fence. The contract validation is unchanged: a fenced answer and a misnamed citation are
  still refused, each with its exact reason (tested).
- **Confirmation.** The same live-generated graph was replayed offline through the product's
  own admission (its raw generation answer had been saved first). There was no model call, and
  the framework gave it a new identity. It was then criticized live once more with the fixed
  prompt, and **every stage completed and was admitted by the contract**: the review, a
  counterexample proposal with 4 counterexamples, 4 validity calls and 2 candidate responses, with
  0 refusals. The folded verdict is **rejected** (`counterexample_fail:cx-thumbnail-unchecked`,
  `validity_unresolved:cx-downstream-writers-mutate-bundle`). The live critic judged that the
  candidate never checks the thumbnail (a completion condition), and one validity stayed
  unresolved. The pool therefore presents **0 of 1** (excluded: `rejected:…`), so **no live
  selection was possible**: the owner-selection step in the test runs only when the pool presents
  a candidate.

| run | call | purpose | provider message id | request id | state / stop | input / output tokens |
|---|---|---|---|---|---|---|
| diagnose | 1 | design_candidate (cap 10,000) | `msg_011CfRKCbGPV4WqkjQHvPqPE` | `req_011CfRKCaUm4iyapGe7ioiQF` | completed / end_turn | 5,707 / 4,214 |
| diagnose | 2 | review (cap 6,000), **refused**: `json: Expecting value at line 1 column 1` | `msg_011CfRKF5v8KnVEpndGR1iwa` | `req_011CfRKF5RbwqUwvxLzKifN4` | completed / end_turn | 4,985 / 3,511 |
| confirm | 1 | review: all 5 findings `pass` | `msg_011CfRKPzKHAWkGCYb3dGMVQ` | `req_011CfRKPyeLkBgNngqwENx7e` | completed / end_turn | 5,111 / 2,723 |
| confirm | 2 | counterexample proposal (4) | `msg_011CfRKReBcm4RTHEL2ZTqhL` | `req_011CfRKRdjLAKjRqw3mTuYEj` | completed / end_turn | 6,666 / 3,620 |
| confirm | 3 | validity `cx-thumbnail-unchecked`: valid | `msg_011CfRKU8xJUPnPykTQTSJVj` | `req_011CfRKU8Vm3pUe5XzNzstz3` | completed / end_turn | 5,751 / 2,093 |
| confirm | 4 | response: **fail** | `msg_011CfRKVdbkuGXJLXL7swk2y` | `req_011CfRKVcznUoEh7dQwCb6RU` | completed / end_turn | 7,092 / 2,233 |
| confirm | 5 | validity `cx-post-write-citation-unverified`: valid | `msg_011CfRKX77FqKhXuiDYQpwRM` | `req_011CfRKX6akStNx4FGGX2aRd` | completed / end_turn | 5,733 / 2,117 |
| confirm | 6 | response: mitigate | `msg_011CfRKYUCYQ3xu4KuVazpSe` | `req_011CfRKYTmjwgc8dTbbJwsiL` | completed / end_turn | 7,103 / 2,080 |
| confirm | 7 | validity `cx-downstream-writers-mutate-bundle`: unresolved | `msg_011CfRKZwMCpZDop2w3pQbmZ` | `req_011CfRKZv5KCHnptY76nuFgk` | completed / end_turn | 5,622 / 1,724 |
| confirm | 8 | validity `cx-shared-model-research-writer`: rejected | `msg_011CfRKbETPgEgAX1EaembcP` | `req_011CfRKbDhz5xhi1cijJeLXy` | completed / end_turn | 5,655 / 1,846 |

- Run ids:
  - diagnose: `64ce2464-e658-5500-ba8e-eb1dc4004022` (candidate `a399df0b-…`, refusal record
    `55c22f07-9039-5db1-b40e-b3fc2023a9c7`);
  - confirm: `60e31d3a-cbad-5ddd-bc3b-ff1245da1f95` (candidate `60d566fb-…`, criticism record
    `c4cde83f-8a09-4b5a-9aa9-aee76a536a96`, 8 critic calls plus 1 replayed generation).
- **Spend:** 59,425 input + 26,161 output tokens over 10 calls. At the listed price (USD 4 / 20
  per MTok) the diagnosis run cost ≈ USD 0.197 and the confirmation ≈ USD 0.564, **≈ USD 0.76 of
  the 1.50 cap in total**. The guard's ceiling-rate bound was USD 0.951, and it refused no send.
  The earlier 2026-09-26 run (USD ≈ 0.19) was under its own, separate 3.00 authorization.
- Evidence, model identity redacted: `evidence/t038-live-review-2026-09-26/` holds
  `diagnose.json`, `confirm.json`, the refused raw review `diagnose-02-criticism.txt`, the eight
  confirmation answers and the spend `ledger.json`.
- Variance: in the diagnosis run, the same critic's (refused) review had failed the candidate on
  its `shape:disposition` criterion. In the confirmation, its review passed every criterion and
  the counterexample chain rejected the candidate instead. One confirmation does not measure the
  critic, and nothing here is a qualification.

### 2. Design requests are restorable after a restart

`app/services/design_requests.py`: creating a request persists one immutable
`design_request_basis` record beside the request record. Its parents are the request record and
the work-model record. It holds:

- the lens evidence each lens decision was issued from, and the lens decisions' audit;
- the functional decision's exact content;
- the exact compilation authority;
- the requested count.

`restore_request` rebuilds a request **only** by re-running every issuing gate over stored,
verified records:

1. the confirmed target, from the stored work model and the owner's stored confirmation
   (`PersistentWorkModels.confirmed_target`);
2. each lens decision, re-issued by the host's lens registry with its own evidence verifier (the
   audit must be equal and the decision still `proposed`);
3. `accept_design_decision`;
4. `CompilationAuthority.from_trusted` (the digest must be equal);
5. `create_generation_request`.

The re-issued request must equal the stored record byte for byte. The workspace rebuilds a
persisted request on read and on list. Anything that does not resolve answers `not_restorable`
with the exact reason, and the list shows it under `unrestorable`. A request registered by host
code with `open_request` and no stored basis stays unrestorable. The compilation authority is
verified by its digest against the request; its refs are not re-resolved against the store,
because the fixture authority's refs are synthetic.

### 3. Creating a request from the work page, only where a qualified lens decision exists

- **The route.** `POST /api/v1/design-requests` (`design_requests.create`,
  `design-request-create-command-v1 {command_id, work_model_id}`). Routes go from 137 to **138**
  installed; the pins and docs/release/api-compatibility.md are updated. It creates a request
  from the owner's **accepted** work model through the host's `DesignSource`, which is trusted
  code supplying the lens registry, lens evidence, functional decision, authority and turns.
  - A work model the owner has not accepted answers `not_designable`.
  - Lens decisions that are not `proposed` answer `not_designable` with each lens's state and
    reason (e.g. `L-P032-01 abstained (qualification_record_untrusted)`).
  - An exact replay creates nothing new.
- **Production configures no source.** `GET /api/v1/design-requests` answers
  `creation: {available: false, reason}`, and the command answers `not_designable` with exactly:
  *no qualified lens decision exists for this work model: no lens is qualified in this
  installation (every lens is a document candidate and no qualification record has been issued),
  so a design request cannot be created*.
- **The page.** The work page's design workspace (`app/static/workspace.mjs`, `설계 요청 만들기`)
  shows that sentence in Korean with the exact reason, and no button. With a source configured,
  it first asks for an accepted work model, then offers `이 작업 모델로 설계 요청 만들기`, names the
  source (the test actor's is labelled `SIMULATED lens qualification`) and shows the new request.

### Tests (offline, this update)

- `test_design_criticism_live.py`: 7 passed, 3 of them new (the raw answer and exact violation
  per stage; the bounded keep and diagnosis/contract agreement; the two live causes stated in the
  prompt and still refused).
- `test_design_arc.py`: 5 passed, 1 new (a refused review answer persisted with its violation).
- `test_design_requests.py`: 3 passed, all new:
  - production's exact refusal;
  - creation only from an accepted work model and a qualified lens;
  - create → generate → **restart**. After the restart the request is refused without a source,
    refused when the verifier no longer trusts the qualification, and rebuilt with the source
    (same pool, then select and re-review).
- Regression: all `test_design_*.py`, `test_environments.py`, `test_web_owner_integration.py`,
  `test_first_party.py` (138 installed + example), `test_criticism_run_persistence.py`,
  `test_critic_lens_pipeline.py` and `test_work_models.py`: 252 passed, 2 live files skipped.
- node: `workspace.test.mjs` 12 passed (2 new); work, work-model, work-conversation and
  run-start 45 passed.
- Real Chrome, **`app/tests/browser-design-request.test.mjs`: 2 passed.**
  - With the SIMULATED source (`design_arc_server.py --design-source simulated`): the owner
    drafts the work model (mocked transport) and accepts it on the work page, creates the request
    from the page, and generates. 3 candidates are presented, every verdict names the scripted
    critic, and the request is served again after a reload.
  - With no source (`--design-source none`, production's state): the page states the exact
    reason and offers no button.
- `browser-design.test.mjs`, `browser-design-workspace.test.mjs` and
  `browser-run-start-t048.test.mjs`: 4 passed.

## 2026-09-26 (latest): ONE live design arc to the owner's selection — nothing passed

The owner authorized one more live design arc, end to end through the product's own paths, under
a hard cap of **USD 3.00 in total**. It covers:

- live generation of up to 3 candidates (one request, up to 2 supplementation rounds);
- live criticism of each candidate, then pool assembly;
- if a candidate passes, the owner's selection through the workspace routes: `derivations`
  select, the derived version, and its mandatory **live** re-review;
- preparation, first with no critic qualification (it must be refused), then with the
  SIMULATED test-actor qualification (decisions.md 2026-09-25, independent-person steps). A
  preparation there would be labelled as resting on that simulation and would not be a release
  qualification.

Also in the authorization: one prompt-level change to the generation instructions if a clear
systematic defect appeared, and one more attempt inside the same cap.

**Runner.** `app/tests/test_claude_live_design_selection.py` (`_live_`,
`DEEPTWIN_LIVE_DESIGN_SELECTION=1`).
- **Key.** Read from `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and put into server memory through the
  owner's connection route. It is never printed or stored, and the evidence is asserted
  key-free.
- **Model.** The first model the live catalog listed. Its identifier is redacted from the
  evidence (`<live-catalog-model>`) and appears in no code or commit. There is no retry and no
  fallback.
- **Spend guard.** Before every send, the guard adds up three amounts, all at **ceiling rates of
  USD 5 / 25 per MTok** in/out (above the model's listed USD 4 / 20):
  - earlier attempts (read from the ledger);
  - this attempt's provider-reported usage;
  - the next call's worst case: its exact prompt length at one token per character, plus its
    full output cap.
- **Reserve.** In attempt 1 the guard also held back USD 1.00 while the arc ran, so that the
  owner's re-review could complete.
- **Refusals.** A send the guard refuses is recorded by the arc as a refused call.
- **Raw answers.** Each answer is saved the moment it arrives, before admission, and holds model
  output only.
- **Evidence.** Everything is under `evidence/t038-live-arc-2026-09-26/`: `attempt1.json`,
  `attempt2.json`, 26 raw answers `attemptN-NN-arc-<stage>-<purpose>.txt` and `ledger.json`.

### Attempt 1 (current generation prompt; 3 requested, max 3 rounds, output caps 24,000 / 6,000)

Run `f8c2a7c1-06f8-56bb-836c-7ff721eacd7b`, outcome **`shortfall`**, 3 rounds, 0 presented of 2.

- **Generation.** Round 1 made one live call. The model returned **2** graphs (it may return 1
  to 3), and the framework admitted both:
  - `fd01da78-…`: research, verifier, writer, publish-gate (human gate), release (deterministic);
  - `bdc3a06d-…`: research, writer, checker, publish-gate, release.
- **Criticism.** Both candidates were criticized live, 8 calls each. All 16 answers were admitted
  by the contract; there were **0 contract refusals**. Both were **rejected**:
  - `fd01da78-…`: `counterexample_fail:cx-thumbnail-no-artifact-no-check`,
    `review_unresolved:shape:disposition` and three `validity_unresolved` (`cx-dossier-overwrite`,
    `cx-script-post-approval-mutation`, `cx-shared-grant-research-verifier`).
  - `bdc3a06d-…`: `review_fail` on `…221:claim:0`, `…221:effect:research-responsibility` and
    `shape:disposition`; `counterexample_fail` on `cx-writer-mutates-dossier`,
    `cx-citation-map-undeclared` and `cx-thumbnail-promise-undefined`;
    `review_unresolved:work:completion:0`; `validity_unresolved:cx-post-check-script-writers`.
- **Supplementation.** Rounds 2 and 3 were **refused by the spend guard**. The bound was USD
  3.2836 including the reserve, so nothing was sent. The arc recorded them as refused generation
  calls (`the model boundary failed`). Nothing was presented, so the owner path did not run.

### Analysis (from the saved raw texts and verdicts)

The live critic is **not** too strict here: its findings name real design properties of the
graphs. The failures are **systematic candidate defects**, and the same two recur in all three
live candidates so far (the earlier confirmation run included):

1. **Shared write access.** The critic's projection (`design_criticism._artifacts`) lists every
   node with an output slot under an artifact contract as a *writer* of that artifact. The
   generator reused contracts downstream:
   - a gate or release node re-emits the `script` contract it received;
   - a verifier re-emits the research dossier;
   - the writer re-emits the dossier to the checker.
   The critic then reads, correctly, that the gate, release, verifier or writer can alter
   research output or the approved script. This breaks `…221:claim:0` and the effect, and puts
   `shape:disposition` in doubt.
2. **Completion conditions left to responsibility text.** The thumbnail-promise condition
   ("첫 30초와 썸네일 약속…") and the citation linkage had no checking node other than their
   producer, and no declared artifact (citation map, thumbnail promise). The earlier
   confirmation's `cx-thumbnail-unchecked` was the same defect.

The critic contract, the fold and the critic prompt were **not** changed.

### The one prompt-level improvement (generation only)

`app/services/design_live.py` gains `_CRITIC_DESIGN_RULES`, appended to the generation system
prompt. It tells the generator the rules it is judged by:

- **(a) one writer per artifact:** each contract is produced by exactly one node, and a node
  that verifies, approves, forwards or releases emits its result under its own new contract;
- **(b) independent, declared checks:** every completion condition, and every risk with
  `mitigation_required`, is checked by a node other than its producer, and the check's result
  and its inputs are declared artifacts. A node with two predecessors is a join.

Admission is unchanged. `test_design_live.py` has a new test that the rules are stated.

### Attempt 2 (improved prompt; 1 requested, 1 round, output caps 12,000 / 6,000, no reserve)

The remaining budget set these limits. After attempt 1, USD 1.381 of the cap was left at
ceiling rates, which is not enough for a 3-candidate arc plus a re-review (≈ USD 0.7 per
criticized candidate at ceiling). The reserve was dropped so that the arc could send at all.
The re-review would therefore have completed only if the budget allowed, and the guard would
have refused its calls otherwise.

Run `21ac3f75-80a5-510b-845e-b86a103144e9`, outcome **`shortfall`**, 0 presented of 1.

- **Generation.** One live call. The framework admitted `d42f4501-…`: research, writer,
  fact-check, hook-check (agents), review-join (join), publish-gate (human gate) and release
  (agent). It has separate `citation-map` and `hook-thumbnail-brief` artifacts and the dossier
  has a single writer. Both rules were followed.
- **The review improved.** For the first time, **all 5 review findings passed**:
  `…221:claim:0`, the effect, `shape:disposition`, `work:completion:0` and `work:completion:1`.
  The thumbnail counterexample (`ce-first-30s-undefined`) was judged **rejected**, i.e.
  invalid.
- **Still rejected**, on deeper defects:
  - `counterexample_fail:ce-factcheck-no-dossier`: fact-check cannot read the dossier, so an
    omitted counter-evidence item passes;
  - `counterexample_fail:ce-release-post-approval-drift`: release regenerates the PDF after
    approval, and nothing checks it afterwards;
  - `validity_unresolved:ce-unverified-claims-pass-join`: a fact-check report that lists
    unverified claims does not block the join.
  These findings are specific and grounded in the graph, so again they are not critic
  strictness. 9 calls, 0 refusals, 0 guard refusals. The criticism record is
  `b204fad0-3654-40d6-aed6-a037ee99b7ec`.
- **Owner path.** Nothing was presented, so there was **no selection, no re-review and no
  preparation**, and nothing to label.

### Calls (provider-reported; all `completed / end_turn`; bound = the guard's ceiling-rate bound before the send, attempt 1 including the USD 1.00 reserve)

| attempt | # | purpose | provider message id | request id | input / output tokens | bound USD |
|---|---|---|---|---|---|---|
| 1 | 1 | design_candidate (cap 24,000) | `msg_011CfRMxZGJXq9sVUFaJiyim` | `req_011CfRMxYTB2cA2hxtEJHMWV` | 5,711 / 7,895 | 1.6646 |
| 1 | 2 | review (`fd01da78`) | `msg_011CfRN2ukD8DwNMHmfdbRwJ` | `req_011CfRN2uJAJR66aPRL8ffRe` | 5,169 / 3,578 | 1.4333 |
| 1 | 3 | counterexample_proposal | `msg_011CfRN5HN2Qqf7AEGsquZPe` | `req_011CfRN5GfbdVUGutvQj1D8J` | 6,727 / 3,955 | 1.5622 |
| 1 | 4 | counterexample_validity | `msg_011CfRN7wyo37bwWhuo9cBBP` | `req_011CfRN7vtYxpCjduexpoUh6` | 5,880 / 2,245 | 1.6905 |
| 1 | 5 | counterexample_validity | `msg_011CfRN9YNXJDPW2bUAcQxFL` | `req_011CfRN9XvEfkCRH1YzKhKPW` | 5,671 / 1,713 | 1.7737 |
| 1 | 6 | counterexample_validity | `msg_011CfRNAofKRShNQAjcgHkwp` | `req_011CfRNAo6a87Ec68LrxhGCe` | 5,722 / 1,640 | 1.8449 |
| 1 | 7 | candidate_response | `msg_011CfRNC1rZR2GbzF6QiFyrG` | `req_011CfRNC1QGza21FnGYwgzKf` | 6,850 / 2,037 | 1.9295 |
| 1 | 8 | counterexample_validity | `msg_011CfRNDM8xNAriuY5gwUoMB` | `req_011CfRNDLYz2UbdCEeK1kqCj` | 5,762 / 2,444 | 2.0004 |
| 1 | 9 | review (`bdc3a06d`) | `msg_011CfRNF3W85RsKpLfYokSgq` | `req_011CfRNF33aczjHBiQaxo1go` | 5,143 / 2,946 | 2.0818 |
| 1 | 10 | counterexample_proposal | `msg_011CfRNH38rJC9aQ9f6KqPJk` | `req_011CfRNH246q9v4ak9trp9Hy` | 6,701 / 3,747 | 2.1948 |
| 1 | 11 | counterexample_validity | `msg_011CfRNKWn4URuYHmLkDyyKF` | `req_011CfRNKW4trRjDXXdQvm6L3` | 5,907 / 1,799 | 2.3179 |
| 1 | 12 | candidate_response | `msg_011CfRNLnBJJ5c6XrAA5Hg6c` | `req_011CfRNLmVrgr5rnk5YwugQa` | 7,299 / 1,474 | 2.4107 |
| 1 | 13 | counterexample_validity | `msg_011CfRNMkNgUuuBUPc7qeV5z` | `req_011CfRNMjiUmVpgerAKg2cpx` | 5,738 / 2,254 | 2.4639 |
| 1 | 14 | candidate_response | `msg_011CfRNPFg4z1g25tJkhjcwM` | `req_011CfRNPFGGK9TkHUN8xBpsG` | 7,039 / 1,805 | 2.5657 |
| 1 | 15 | counterexample_validity | `msg_011CfRNQNoyfLKUmuktXxkQr` | `req_011CfRNQNPfmLWbtXDoQXEyn` | 5,650 / 1,416 | 2.6278 |
| 1 | 16 | candidate_response | `msg_011CfRNRNCnPxPkZRykhbkXd` | `req_011CfRNRMmVWTT6RBTrMpyXm` | 6,624 / 1,440 | 2.7046 |
| 1 | 17 | counterexample_validity | `msg_011CfRNSLdZe8m2jSuXdUR7i` | `req_011CfRNSKKgAjgqJyf821VJ3` | 5,572 / 1,737 | 2.7600 |
| 1 | — | round 2 generation: **guard refused, not sent** | — | — | — | 3.2836 |
| 1 | — | round 3 generation: **guard refused, not sent** | — | — | — | 3.2836 |
| 2 | 1 | design_candidate (cap 12,000) | `msg_011CfRNgdPGC8LD1vPSMSnJb` | `req_011CfRNgcnHzEcijyMCt8KVT` | 6,012 / 9,544 | 1.9890 |
| 2 | 2 | review (`d42f4501`): 5 × pass | `msg_011CfRNne2sj14u2F5uSJuZT` | `req_011CfRNndB2m2XYkShyFRv3A` | 7,391 / 2,697 | 2.1177 |
| 2 | 3 | counterexample_proposal (4) | `msg_011CfRNpKbfarsXKa8KqaqXd` | `req_011CfRNpK9cxH6WasccT4hoY` | 8,949 / 4,005 | 2.2357 |
| 2 | 4 | validity `ce-factcheck-no-dossier`: valid | `msg_011CfRNs2T7aHiajN9gchgww` | `req_011CfRNs1RMLGDzSPaxW9KsZ` | 8,066 / 1,855 | 2.3755 |
| 2 | 5 | response: **fail** | `msg_011CfRNtMWrpVzbR5vWGDuBd` | `req_011CfRNtLqSGptfvCTppSE8x` | 9,458 / 2,044 | 2.4808 |
| 2 | 6 | validity `ce-unverified-claims-pass-join`: unresolved | `msg_011CfRNugZcYgw9vwJKk5knp` | `req_011CfRNufiWwZk1L6dgp2P6K` | 7,905 / 1,985 | 2.5586 |
| 2 | 7 | validity `ce-release-post-approval-drift`: valid | `msg_011CfRNw5NbZWyQjumFGaGGX` | `req_011CfRNw4v4MbWmxMY6hKBmN` | 7,879 / 2,200 | 2.6475 |
| 2 | 8 | response: **fail** | `msg_011CfRNxciXiLpLP4QBnCt3g` | `req_011CfRNxcGjfqaLZt815eVn7` | 9,157 / 1,980 | 2.7589 |
| 2 | 9 | validity `ce-first-30s-undefined`: rejected | `msg_011CfRNyw9pFemDutbnZWrch` | `req_011CfRNyvWNro9cCXHnzgNh2` | 7,845 / 1,467 | 2.8367 |

**Spend.** 26 calls were sent, with no cache tokens.

| | input tokens | output tokens | listed USD 4 / 20 | ceiling USD 5 / 25 |
|---|---|---|---|---|
| Attempt 1 | 103,165 | 44,125 | ≈ 1.295 | 1.619 |
| Attempt 2 | 72,662 | 27,777 | ≈ 0.846 | 1.058 |
| **Total** | | | **≈ 2.14** | **2.677** (of the 3.00 cap) |

The guard refused 2 sends and none went past the cap. USD 0.323 remains at ceiling rates, which
is not enough for another criticized candidate, so there is no further attempt.

## 2026-09-26 (attempt 3): design-hygiene rules, one more live arc — nothing passed

A new owner authorization covered one more live attempt under its **own USD 3.00 cap**. That cap
is independent of the cap on attempts 1–2, whose spend is stated separately below. The
authorization also covered one generation-side change that generalizes attempt 2's three
rejection reasons. The critic contract, the fold and the critic prompt were **not** changed.

### The generation change (`app/services/design_live.py`, `_CRITIC_DESIGN_RULES` (c)–(e))

These are general principles, with no task wording:

- **(c) a check reads what it verifies.** Every checking node has an artifact input edge for
  each exact artifact it verifies or compares against. A summary or a map derived from that
  artifact is not enough.
- **(d) nothing changes after approval unchecked.** The content a human gate approves is the
  content released. No node after an approval regenerates, rewrites, reformats or alters it.
  If a later derived artifact is unavoidable, a node other than its producer re-checks it
  against the approved content before release, and that report is an input of the release path.
- **(e) a check that finds unresolved problems blocks.** The findings must decide the graph's
  path, and a report is not enough. Either a router on a declared verdict fact sends only the
  passing value onward (a failing value loops back through a bounded loop or ends the run), or
  the check's failure policy stops its dependants and every downstream join uses
  `failure_handling block`.

Test: `test_design_live.py::test_the_generator_is_told_the_design_hygiene_rules` covers both
the first-round and the revision prompt, and checks that rules (c)–(e) use no task words.
Offline, the design/generation/profile tests gave 568 passed and 4 skipped.

### Run (`test_claude_live_design_selection.py`, same product path)

**Settings.**
- `DEEPTWIN_LIVE_ATTEMPT=attempt3`, with its own ledger `attempt3-ledger.json`, so the
  guard's earlier-attempts term is 0 for this cap.
- 1 candidate requested, 1 round, generation cap 16,000 output tokens, criticism cap 6,000.
- USD 1.00 re-review reserve held while the arc ran.
- The guard used ceiling rates of USD 5 / 25 per MTok.
- The model was the catalog's first; its id is redacted.
- No retry and no fallback. The key was never printed, and the evidence was checked key-free.

**Outcome.** Run `f1e96834-34df-5ca9-8d54-305f196ab9fa` ended in **`shortfall`**, with 0
presented of 1.
- Criticism record: `67da8dc8-5970-4298-a7f5-a8c673860bd6`.
- Evidence id: `1728bfbb-0005-40f9-83c8-a742ba3d5660`.
- There were 0 contract refusals and 0 guard refusals.

**Candidate** `7f0c447c-a447-4d4f-b7b0-9aa732ff55f1`:
- Nodes: research (agent), writer (agent), **fact-check (join)**, hook-check (agent),
  review-join (join), publish-gate (human gate), **release (join)**.
- The review passed `…221:claim:0`, the effect, `shape:disposition` and `work:completion:1`.
  `work:completion:0` stayed **unresolved**.
- Rejected for:
  - `counterexample_fail:cx-factcheck-no-agent` (valid, then fail). Fact-check is a **join**:
    it has no model and no role, yet it is the producer of the fact-check report and carries
    the semantic check.
  - `validity_unresolved:cx-script-unpinned-release`. Release reads the script straight from
    the writer (`e-writer-release-script`), and nothing ties the fact-checked script, the
    approval and the released script to the same content.
  - `validity_unresolved:cx-hook-first30-undefined`. The script contract has no timing
    markers, and the script may be PDF-only for a text-only hook-check.
- The `cx-gate-no-report-access` counterexample was judged invalid.

**Owner path.** Nothing was presented, so there was **no selection, no re-review and no
preparation** (neither the refused unqualified one nor the simulated-qualification one), and
nothing to label.

**Analysis.** Rules (c) and (e) were followed literally:
- fact-check now reads the dossier, script and citation map;
- a failure stops its dependants, and the joins use `block`. The validity answer for
  `cx-gate-no-report-access` confirms that fact-check "fails and halts the run on any
  unverified claim".

But rule (c) gave the checker inputs from two producers, and the structure rule says a node
with more than one triggering predecessor must be a join. So the model made the **checker
itself** a join, which cannot perform a check. It did the same with release, which also has
two predecessors: the approval and the writer's script. So the new defect comes from how the
new rules interact with the existing structure rule. It is not critic strictness.

The next generation-side rule would be:
- a join only aggregates;
- a check or release that needs several inputs is a join followed by an agent (or
  deterministic) node;
- release takes the approved content through the gate path, never from the producer directly.

This attempt made no change after the run.

### Calls (provider-reported; all `completed / end_turn`; no cache tokens; bound = the guard's ceiling-rate bound before the send, including the USD 1.00 reserve)

| # | purpose | provider message id | request id | input / output tokens | bound USD | spend USD (ceiling) |
|---|---|---|---|---|---|---|
| 1 | design_candidate (cap 16,000) | `msg_011CfRPj4eUc5ENUdzDU9cpG` | `req_011CfRPj3p7V9ME5eLv9enMg` | 6,391 / 11,192 | 1.4766 | 0.3118 |
| 2 | review (`7f0c447c`) | `msg_011CfRPrG3mYChkHJvWLUrnF` | `req_011CfRPrFT3mBeGU5AinnZrJ` | 6,553 / 3,112 | 1.5322 | 0.1106 |
| 3 | counterexample_proposal (4) | `msg_011CfRPtCZETbcGWCdSN7AUW` | `req_011CfRPtBdfCm4Jwf6LcKtWv` | 8,113 / 4,611 | 1.6563 | 0.1558 |
| 4 | validity `cx-factcheck-no-agent`: valid | `msg_011CfRPwLvLzbagAbaNj59BJ` | `req_011CfRPwLLNNYn5qHwqo5vQs` | 7,104 / 2,163 | 1.8057 | 0.0896 |
| 5 | response: **fail** | `msg_011CfRPxsSvG8aFT9BkWk3VH` | `req_011CfRPxrytFLiqjibtxxz6s` | 8,646 / 1,646 | 1.9150 | 0.0844 |
| 6 | validity `cx-script-unpinned-release`: unresolved | `msg_011CfRPywUnkDcTbxLcmJxVN` | `req_011CfRPyw2VaMCB2dqRAWCeM` | 7,058 / 2,140 | 1.9791 | 0.0888 |
| 7 | validity `cx-gate-no-report-access`: rejected | `msg_011CfRQ1QcD83etLU7FtA841` | `req_011CfRQ1Q9vMCpQLZ6mqgnPW` | 7,037 / 1,869 | 2.0674 | 0.0819 |
| 8 | validity `cx-hook-first30-undefined`: unresolved | `msg_011CfRQ2fHYNFs9DuQsRDmzD` | `req_011CfRQ2ehZfw2Ff5VFmgi52` | 7,095 / 2,025 | 2.1498 | 0.0861 |

**Spend.** Attempt 3 sent 8 calls, with 57,997 input and 28,758 output tokens. That is about
USD 0.807 at the listed 4 / 20 and **USD 1.009 at the ceiling 5 / 25**, against this attempt's
USD 3.00 cap. USD 1.991 of the cap is unused, and it was not spent on a retry.

Attempts 1–2 are counted separately, under the earlier cap: USD 2.677 at ceiling (≈ 2.14 listed).
Across all three attempts the total is USD 3.686 at ceiling (≈ 2.95 listed).

**Evidence.** Everything is under `evidence/t038-live-arc-2026-09-26/`: `attempt3.json`,
`attempt3-ledger.json` and 8 raw answers `attempt3-NN-arc-<stage>-<purpose>.txt`.

**T038 is not ticked.** No live candidate has passed live criticism, so the full path has not
completed live: selection, the live re-review, refused unqualified preparation and
simulated-qualification preparation.

## 2026-09-26 (attempt 4): joins only aggregate, release pinned to the approval — nothing passed

A new owner authorization covered one more live attempt under its **own USD 3.00 cap**. That cap
is independent of the caps on attempts 1–2 and attempt 3, whose spend is stated separately
below. The authorization allowed up to 2 candidates if the guard permitted, with USD 1.00 kept
in reserve for the re-review. It also covered one generation-side change that generalizes
attempt 3's three rejection reasons. The critic contract, the fold and the critic prompt were
**not** changed.

### The generation change (`app/services/design_live.py`, `_CRITIC_DESIGN_RULES` (f)–(h))

These are general principles, with no task wording:

- **(f) a join only aggregates.** A join has no model and performs nothing, so it never
  carries a check, review, approval or release. A check, review or release that needs inputs
  from several producers is a join followed by an agent or deterministic node that performs
  it. The join emits its own new aggregate contract, a bundle of the exact, unaltered inputs.
  The performing node's single triggering predecessor is that join.
- **(g) release takes exactly what was approved, through the gate's path.** The human gate
  receives the exact content it approves, with the check reports, and emits it unaltered under
  its own approved-content contract. The releasing node reads that content from the gate: its
  artifact edge and its approval edge both come from the same gate. It never takes a fresh copy
  from the producer or from any node before the gate.
- **(h) a check reads the artifact in a format it can inspect.** The checked contract's media
  types are ones the checker's capabilities can read, and the checker's responsibility names
  the format. If the producer's format is not inspectable, a conversion node before the check
  emits an inspectable rendition, and the check, the approval and the release all use that
  same content.

Rule (b)'s last sentence used to say that a node needing artifacts from two predecessors *is* a
join. It now says such a node is *preceded by* a join, per rule (f).

Test: `test_design_live.py::test_the_generator_is_told_joins_only_aggregate_and_release_is_pinned`
covers the first-round and the revision prompt. It also checks that rules (f)–(h) use none of
the task's words (dossier, fact-check, thumbnail, research, script, pdf, video, youtube,
citation, hook). Offline, the design/generation/profile tests gave 212 passed and 4 skipped.

### Run (`test_claude_live_design_selection.py`, same product path)

**Settings.**
- `DEEPTWIN_LIVE_ATTEMPT=attempt4`, with its own ledger `attempt4-ledger.json`, so the
  guard's earlier-attempts term is 0 for this cap.
- **2 candidates requested** and 1 round, with no supplementation.
- Output caps: 28,000 tokens for generation and 6,000 for criticism. Before the generation
  call, the guard's worst-case bound was USD 1.784 including the reserve, so it allowed 2
  candidates.
- USD 1.00 re-review reserve held while the arc ran.
- The guard used ceiling rates of USD 5 / 25 per MTok.
- The model was the catalog's first; its id is redacted (`<live-catalog-model>`).
- No retry and no fallback. The key was never printed. The JSON, the ledger and all raw
  answers were checked key-free.

**Outcome.** Run `15ca5ce4-99af-5f17-82ce-e4ea5c05277f` ended in **`shortfall`**, with 0
presented of 2.
- Evidence id: `6b0fb04d-efba-437e-adde-3f53c2c1c817`.
- There were 0 contract refusals, 0 guard refusals and 0 unreviewed candidates.

**The rules were followed.** The model returned 2 graphs, and the framework admitted both.
- `2f4cebd8-d984-49fd-b118-8eb480cc13f8`:
  - research and writer (agents);
  - **j-fact (join) → fact-check (agent)**, where fact-check reads the join's
    `fact-check-bundle` (dossier, script draft, citation map);
  - hook-check (agent);
  - **j-gate (join)** → `review-bundle` → **publish-gate (human gate)**, which emits
    `approved-script`;
  - **publisher (deterministic)**, whose artifact edge and approval edge both come from the
    gate.
- `0738d0ac-4d20-4144-923c-4ee6eddc45e3` has the same shape with a single checker:
  - **j-verify (join) → verifier (agent)**, where the verifier reads a `verification-bundle`
    (dossier, draft, citation map, thumbnail promise);
  - j-gate → publish-gate → publisher, as above.
- In both graphs:
  - every contract is `text/markdown`, so no check reads a format it cannot inspect;
  - no join carries a check;
  - nothing reaches release except through the gate.

**The criticism improved again.** For both candidates:
- **all 5 review findings passed**: `…221:claim:0`, the effect, `shape:disposition`,
  `work:completion:0` and `work:completion:1`;
- **no counterexample was judged valid**, and no response failed.

Each candidate was still excluded as `insufficient_evidence`, on two validity answers that
stayed **unresolved**.

`2f4cebd8`, criticism record `621f5508-5475-450d-815c-5d99f5640fbb`:
- `cx-dossier-only-verification` (unresolved). Fact-check compares the script with the
  dossier only and has no tools, so a dossier that misstates a source would pass. The validity
  answer says this gap is real. Whether `work:completion:0` demands re-verification against
  the sources, or only a traceable link through the dossier, it says "is not settled by the
  criteria text".
- `cx-counterevidence-dropped` (unresolved). The writer has no obligation to reflect
  counter-evidence. The review bundle does not carry the dossier, so the gate cannot see what
  was dropped. The answer calls it "interpretive" whether the effect requires this downstream.
- `cx-uncited-claim-gap` was judged invalid (rejected).

`0738d0ac`, criticism record `bb1b8310-3de2-4083-a0a6-e7fdf511afa6`:
- `cx-first30-undefined-duration` (unresolved). The script has no timing markers for the
  opening segment. The validity answer calls the chain "a plausible risk, not a demonstrated
  effect".
- `cx-verifier-shares-research-model` (unresolved). The verifier and research use the same
  model choice, so a correlated misjudgment is possible. The answer calls it "a possible
  general risk … not a demonstrated violation".
- `cx-research-claims-precede-script` was judged invalid (rejected).

**Owner path.** Nothing was presented, so none of the owner steps took place:
- no selection;
- no re-review;
- no preparation, neither the unqualified one (which must be refused) nor the
  simulated-qualification one.

There was therefore nothing to label.

**Analysis.** Attempt 3's structural defects are gone: neither candidate has a fail verdict.
What keeps them out now is the critic's `unresolved` on residual risks that the work model's
criteria do not settle:
- whether the checker re-verifies against the original sources;
- whether contrary evidence is used downstream;
- an unmarked opening segment;
- whether the checker and the producer are independent models.

These are real properties of the graphs, not critic strictness. The fold correctly treats an
unresolved counterexample as insufficient evidence.

The next generation-side principles would be:
- a checker that verifies against a source can itself read the originals that source cites,
  or a second, independent check does;
- whatever a check or gate must weigh, such as recorded contrary evidence, is in the bundle it
  receives;
- a check that locates part of an artifact has that part declared (marked) by the producer;
- a checker uses a different model choice from the producer's when the authority offers one.

This attempt made no change after the run.

### Calls (provider-reported; all `completed / end_turn`; no cache tokens; bound = the guard's ceiling-rate bound before the send, including the USD 1.00 reserve)

| # | purpose | provider message id | request id | input / output tokens | bound USD | spend USD (ceiling) |
|---|---|---|---|---|---|---|
| 1 | design_candidate (2 graphs, cap 28,000) | `msg_011CfRQg7RwP2r5BCbRkctTy` | `req_011CfRQg6SQB9Z7bRTJMyjB2` | 6,812 / 14,982 | 1.7841 | 0.4086 |
| 2 | review (`2f4cebd8`): 5 × pass | `msg_011CfRQpX9Rcc16b3GDmrNpU` | `req_011CfRQpWbBfCtCKy7hM8uG6` | 6,788 / 2,884 | 1.6354 | 0.1060 |
| 3 | counterexample_proposal (3) | `msg_011CfRQrL5imgMJD6P7gf15a` | `req_011CfRQrK3TWu1gesWn52MFu` | 8,348 / 3,658 | 1.7551 | 0.1332 |
| 4 | validity `cx-dossier-only-verification`: unresolved | `msg_011CfRQtsSvFPf8S5ua81Utj` | `req_011CfRQtry9SPcawvbwHqoCD` | 7,411 / 2,331 | 1.8829 | 0.0953 |
| 5 | validity `cx-uncited-claim-gap`: rejected | `msg_011CfRQvZL45CW6CG3HxR5qq` | `req_011CfRQvYgcVe55QGvUfLB17` | 7,253 / 1,645 | 1.9764 | 0.0774 |
| 6 | validity `cx-counterevidence-dropped`: unresolved | `msg_011CfRQwffbKY4o6dSfKrLcc` | `req_011CfRQwfCJRxS3dEvVeLNQ3` | 7,358 / 2,210 | 2.0548 | 0.0920 |
| 7 | review (`0738d0ac`): 5 × pass | `msg_011CfRQyEFvEAawkEQVQXSMh` | `req_011CfRQyDpdVwE24k9euB3Wa` | 6,287 / 2,772 | 2.1339 | 0.1007 |
| 8 | counterexample_proposal (3) | `msg_011CfRQzxooTVTMYteCycdy1` | `req_011CfRQzxJnRbJtcQQ4apvPS` | 7,847 / 3,262 | 2.2483 | 0.1208 |
| 9 | validity `cx-first30-undefined-duration`: unresolved | `msg_011CfRR3Bmi4oj8jtZYnhd8V` | `req_011CfRR3AcFuT3nHThD34vt1` | 6,840 / 1,370 | 2.3626 | 0.0685 |
| 10 | validity `cx-research-claims-precede-script`: rejected | `msg_011CfRR4BtRwbPKVKJ3Y8qZZ` | `req_011CfRR4BEVnSWe22DmYb5de` | 6,896 / 2,064 | 2.4316 | 0.0861 |
| 11 | validity `cx-verifier-shares-research-model`: unresolved | `msg_011CfRR5dyrxiXkCepWWumWd` | `req_011CfRR5dZ3vo661o6AbVYEK` | 6,772 / 1,948 | 2.5165 | 0.0826 |

**Spend.** Attempt 4 sent 11 calls, with 78,612 input and 39,126 output tokens. That is about
USD 1.097 at the listed 4 / 20 and **USD 1.371 at the ceiling 5 / 25**, against this attempt's
USD 3.00 cap. USD 1.629 of the cap is unused, and it was not spent on a retry.

Earlier attempts are counted separately, each under its own cap:
- attempts 1–2: USD 2.677 at ceiling (≈ 2.14 listed);
- attempt 3: USD 1.009 at ceiling (≈ 0.807 listed).

Across all four attempts the total is USD 5.057 at ceiling (≈ 4.04 listed).

**Evidence.** Everything is under `evidence/t038-live-arc-2026-09-26/`: `attempt4.json`,
`attempt4-ledger.json` and 11 raw answers `attempt4-NN-arc-<stage>-<purpose>.txt`.

**T038 is not ticked.** No live candidate has passed live criticism, so the full path has not
completed live. That path is selection, the live re-review, the refused unqualified
preparation and the simulated-qualification preparation.

## Not ticked

The 0/1/2/3, revision and cancel paths are exercised in `app/tests/browser-design.test.mjs` with
the product's own generation, criticism, persistence and selection code, scripted model turns and
the simulation labelled; no fixture verdict is presented as live. T038 says *real*
generation → critique → selection. After this update a live critique **completes**: the
confirmation run made 8 critic calls, all admitted, and folded a verdict. But the live critic
**rejected** the one live candidate, so the pool presented nothing and **no live selection** was
made. The candidate criticized in that run was also the live-generated graph replayed through
admission, not a second live generation. T038 therefore stays open for a live selection of a
live-generated candidate that passes live criticism. The 2026-09-26 (latest) arc changed nothing here, although it was
run end to end through the product's routes. All 3 live-generated candidates were rejected by
live criticism. The improved generation prompt's candidate passed every review finding, but
two counterexamples failed it and a third stayed unresolved. So no owner selection, re-review
or (simulated-qualification) preparation took place. In any case none of this is a release
qualification: no critic or lens is qualified in production, `V3_VERIFYING_DESIGN_IDS` is empty
and V3 is unverified (T077).

## Open

- No live candidate has passed live criticism, so none has been selected or prepared.
  - After the 2026-09-26 (latest) arc, USD 0.323 of its 3.00 cap remains at ceiling rates, which
    is too little for another criticized candidate. A further attempt needs a new owner
    authorization.
  - The attempt-2 defects were generalized into rules (c)–(e), and attempt 3 was run
    (2026-09-26 (attempt 3), above). They were followed. But the checker and the release became
    **joins**: a node with two predecessors must be a join, and a join cannot check. The next
    generation-side rule: a join only aggregates, and a multi-input check or release is a join
    followed by an agent or deterministic node. Release takes the approved content through the
    gate path. Attempt 3's cap has USD 1.991 left, and a further attempt needs the owner's
    authorization.
  - Those rules were added as (f)–(h), and attempt 4 was run (2026-09-26 (attempt 4), above).
    - They were followed. Both live candidates passed every review finding, with no valid
      counterexample.
    - Each was still excluded on two **unresolved** counterexamples. They concern residual
      risks the criteria do not settle: checker independence from the source and from the
      producer's model, contrary evidence the gate cannot see, and an unmarked opening
      segment.
    - Attempt 4's cap has USD 1.629 left, and a further attempt needs the owner's
      authorization.
- Production cannot create a design request: no lens is qualified, so no `DesignSource` is
  configured, and the page and the route say so. A production source would also need the owner's
  model turns wired from the Claude connection and a production functional-decision step (T030).
  The test actor's source is SIMULATED.
- A request registered by host code without a stored basis (the older fixtures) is not
  restorable.
- A merge has no generation turn that realizes it.
- Preparation stays impossible in production (T077).
