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

## 2026-09-26 (attempt 5): a different, better-specified work — nothing passed

**Attempt 5 uses a DIFFERENT work from attempts 1–4.** Attempts 1–4 all designed the YouTube
research → script work (`test_work_model_confirmation.work_model`). Attempt 4's two candidates
followed every design rule and passed every review finding, but were excluded as
`insufficient_evidence` on unresolved counterexamples about points that work's completion
conditions left open (must the fact-check consult the originals? how is the first 30 seconds
marked? may the verifier share the researcher's model?). That pointed at an under-specified work
description, not at defective candidates. So attempt 5 designs a new work whose conditions can be
checked. Its results are therefore **not comparable** one-to-one with attempts 1–4.

A new owner authorization covered this attempt under its **own USD 3.00 cap**, with its own
ledger (`attempt5-ledger.json`). It allowed up to 2 candidates, with USD 1.00 reserved for the
re-review. The critic contract, the fold, the critic prompt and the generation rules (a)–(h)
were **not** changed.

### The work (SIMULATED owner — the test actor; labelled)

`app/tests/design_specified_work.py` was authored by the test actor as a simulated owner
(`AUTHOR`, and the work text starts with `[시험 행위자(가상 소유자)가 작성한 업무 설명 …]`). It is
not a real owner's work.

The task is to write the public release notes for version 2.4.0 from one stored changelog
(`changelog-2.4.0.md`, uploaded as the work's only original). The changelog has six entries
`CL-101…106`, each marked `공개: 예|아니오`.

The work model the critic reads states:
- **Sources and permissions.** The only source is that file, passed through unchanged; no web.
  Storage is `document.create` after approval, and one owner approves under `artifact.publish`.
- **What counts as verified.**
  - Every item line is `- [CL-###] …`, its ID is a public entry, and every name, number and
    version on the line appears in that entry.
  - Every public ID appears exactly once. No private ID or private content appears anywhere.
  - The only non-item line is the title.
- **Who verifies, and how.** A verifier role other than the writer compares the **original file
  itself** with the draft. It uses a **different model choice**.
- **Report format.** `application/json`, with per line `{line, cited_ids, verdict, reason}`, the
  missing IDs, the exposed IDs, and the overall verdict. The overall verdict is pass only when
  every line passes and both lists are empty.
- **What may be regenerated.** Nothing within a run. A fail ends the run without storing anything.
- **What the approver sees.** The verified draft, its report and the original file. The stored
  notes are byte-identical to the approved copy.
- **Out of scope.** Style, tone, length, translation, and the accuracy of the changelog itself
  (the owner's ground truth).
- There are no unknowns, and there is one high risk (unsupported or private line), mitigated by
  conditions 0–3.

The test actor's decision (same lens `L-P032-01`, fixture-qualified as before) asks for one
effect: the node `verifier`'s responsibility, verbatim. The authority snapshot
(`design_authority()`) is unchanged. It offers two model choices, the `browser_read` tool and the
`document_create` tool, and the `artifact.publish` approval scope.

Offline test: `app/tests/test_design_specified_work.py`. It checks that the work is confirmed
over a real saved work and stored original, and that the prompt carries its conditions and the
effect.

### Run 1 (`attempt5`): live generation completed, then the product crashed

**Settings.**
- Same product path: `test_claude_live_design_selection.py` with `DEEPTWIN_LIVE_WORK=specified`.
- 2 candidates, 1 round, generation cap 28,000 tokens, criticism cap 6,000.
- USD 1.00 reserve; ceiling USD 5 / 25 per MTok.
- The catalog's first model (id redacted).
- No retry and no fallback. The key was never printed.

**What happened.** The generation call completed with 2 graphs, and both were admitted. Then the
generation route answered **503 `unavailable`** before any critic call.
- Cause: `design_criticism._control` serialized a control edge's `condition`, a nested frozen
  mapping, with `canonical_json`, which raised.
- Both live graphs use a **router** on a `verification_verdict` fact, which is rule (e)'s first
  option and the first router in any live candidate so far.

**Fix.** The projection now thaws node configs and edge data before serializing
(`app/services/design_criticism.py`). This is a crash fix only. The contract, the fold and the
prompt are unchanged, and a graph without nested values projects byte-identically. Regression
test: `test_a_router_candidate_projects_for_the_critic`, which replays this answer offline.

### Run 2 (`attempt5b`): the same live graphs, live criticism

The first run's call succeeded, so it was **not re-sent**. The runner's new
`DEEPTWIN_LIVE_REPLAY_GENERATION` answers the generation turn with the saved live answer
`attempt5-01-arc-generation.txt` (sha256 `5952d003…dd69`).
- Nothing is sent and nothing is spent for that turn, and the replay is recorded in
  `attempt5b.json` → `replayed_generation`.
- The replayed prompt differs from the original only in framework-minted identities, because
  the work, request and model ids are new in each test app.
- Everything else was live, under the same ledger. The guard counted run 1's USD 0.406 as earlier
  spend.

**Outcome.** Run `9687344d-8552-578a-a1ce-95f7e482b0c3` ended in **`shortfall`**, with 0
presented of 2.
- Evidence id: `90785b02-dfd2-46ff-9538-612739c837d3`.

**The graphs (both).** Every node's role:
- `intake` (deterministic passthrough of the file);
- `writer` (agent, model choice …213);
- `verify-join` → `verifier` (agent, model choice …215), reading the bundle of the unaltered file
  and the draft;
- `verdict-router` (pass → `review-join`, fail → `halt-no-publish`);
- `review-join` → `publish-gate` (human gate), whose inputs are the file, the draft and the
  report, and which emits the approved copy;
- `publisher` (**agent**, bound to `document_create`).

The second graph adds a deterministic `verdict-checker` that recomputes the verdict from the
report before the router.

**Candidate `a8b679a2`: rejected.**
- Review: claim, effect, disposition, and completion 0, 3 and 4 **pass**.
  - `work:completion:1` is **unresolved**: the verifier does not explicitly check "exactly once",
    or private *content* beyond private IDs.
  - `work:completion:2` **fails**: the verifier's responsibility omits `cited_ids` and the rule
    for the overall verdict.
- Counterexamples: all 3 were judged **valid** and failed.
  - `ce-verdict-rule-unbound`: same as the completion 2 failure.
  - `ce-verifier-scope-gap`: the title-only rule and private content are not checked.
  - `ce-publisher-model-byte-fidelity`: the storing role is model-driven, and nothing checks that
    the stored bytes equal the approved copy.

**Candidate `3639d49e`: all 8 review findings passed.**
- Its first counterexample, `cx-verdict-override`, was judged **valid** and failed. The checker's
  recomputed verdict never requires the verifier's own overall verdict to be pass.
- It was therefore headed for rejection. Its other two counterexamples were not judged:
  `cx-publisher-model-rewrite` and `cx-verifier-indirect-input`.
- The guard **refused** the next validity call. Its bound was USD 3.038, over the 3.00 cap
  including the reserve. The criticism was refused, the candidate stays **unreviewed**, and the
  refusal is recorded in `guard_refusals`.

**Owner path.** Nothing was presented, so none of the owner steps took place:
- no selection;
- no re-review;
- no unqualified preparation (which must be refused);
- no simulated-qualification preparation.

The simulated qualification was **not used**.

**Analysis.** The better-specified work did what was intended: the critic's verdicts became
**decisive** (`valid` / `fail`) instead of `unresolved`. The failures are real and checkable:
- **The test actor's own effect text caused part of it.** The required `verifier` responsibility,
  which must be copied verbatim, lists the report's content more loosely than condition 2 (no
  `cited_ids`, no overall-verdict rule). A candidate that realizes the effect exactly is therefore
  judged against a stricter condition. This is a defect of the attempt-5 work/decision authoring,
  not of the candidates.
- **The work conflicts with the authority.** It requires byte-identical storage, but the authority
  offers storage only as a tool, and tools bind only to agents. So the storing role is necessarily
  model-driven, which both critics flagged. A work that is fully specified must also be
  satisfiable under its authority: a code-owned storing handler, or an explicit post-store check
  against the approved copy.
- **The verifier's scope must cover every clause of the conditions it owns:** exactly once,
  private content, the title-only rule.

This attempt made no change after the run.

### Calls (provider-reported; all `completed / end_turn`; no cache tokens; bound = the guard's ceiling-rate bound before the send, incl. the USD 1.00 reserve)

| # | run | purpose | provider message id | request id | input / output tokens | bound USD | spend USD (ceiling) |
|---|---|---|---|---|---|---|---|
| 1 | attempt5 | design_candidate (2 graphs, cap 28,000) | `msg_011CfRRn2YXzEa3teQHpPGgf` | `req_011CfRRn1gw81Dqtmx2xhf57` | 8,291 / 14,585 | 1.7919 | 0.4061 |
| — | attempt5b | design_candidate: **replay of #1**, nothing sent | — | — | — | — | 0 |
| 2 | attempt5b | review (`a8b679a2`): 6 pass, 1 unresolved, 1 fail | `msg_011CfRSGNNB9kkZqdQyPX3RA` | `req_011CfRSGMa3ZR852emZLyRci` | 8,738 / 4,371 | 1.6376 | 0.1530 |
| 3 | attempt5b | counterexample_proposal (3) | `msg_011CfRSK4kcDBUuixfS8EQfE` | `req_011CfRSK4Ha6fSbqawP9eJUN` | 10,298 / 3,800 | 1.8042 | 0.1465 |
| 4 | attempt5b | validity `ce-verdict-rule-unbound`: valid | `msg_011CfRSNh7TezLqrw5JyLxHE` | `req_011CfRSNgXExeZuF76SCA82u` | 9,394 / 1,954 | 1.9459 | 0.0958 |
| 5 | attempt5b | candidate_response: fail | `msg_011CfRSQ1gCRgifpQwMcfmg4` | `req_011CfRSQ1Dubm4aZVxXhUtir` | 10,516 / 1,591 | 2.0572 | 0.0924 |
| 6 | attempt5b | validity `ce-verifier-scope-gap`: valid | `msg_011CfRSR3V83qzLDZnMbipTN` | `req_011CfRSR38Xi3pn9yNhW9Fqc` | 9,268 / 2,046 | 2.1321 | 0.0975 |
| 7 | attempt5b | candidate_response: fail | `msg_011CfRSSYRC2EipXJuBRcsRu` | `req_011CfRSSXSQJWBMTNszU4NQh` | 10,511 / 1,778 | 2.2463 | 0.0970 |
| 8 | attempt5b | validity `ce-publisher-model-byte-fidelity`: valid | `msg_011CfRSThLF5PmZoPNyf9uQC` | `req_011CfRSTgiXtkZBq8xKqDznP` | 9,289 / 1,957 | 2.3269 | 0.0954 |
| 9 | attempt5b | candidate_response: fail | `msg_011CfRSV82aQwkRDWxWoQp15` | `req_011CfRSV7ZnrjRmSAnCyjdge` | 10,514 / 1,787 | 2.4391 | 0.0972 |
| 10 | attempt5b | review (`3639d49e`): 8 × pass | `msg_011CfRSWHmEpphmiPzw18HU4` | `req_011CfRSWHQfGx1gTVjDBtu3T` | 9,168 / 4,550 | 2.5168 | 0.1596 |
| 11 | attempt5b | counterexample_proposal (3) | `msg_011CfRSZ45Z99FoSukuRjrsv` | `req_011CfRSZ3ULwBkXKibPcGquW` | 10,728 / 3,556 | 2.6900 | 0.1425 |
| 12 | attempt5b | validity `cx-verdict-override`: valid | `msg_011CfRSbYPCyrVumApHEETcy` | `req_011CfRSbXLCjaoqLFQtP1FLF` | 9,936 / 2,555 | 2.8291 | 0.1136 |
| 13 | attempt5b | candidate_response: fail | `msg_011CfRSdGjRpyruPEFuGTVGJ` | `req_011CfRSdGCRhTQtBypc5UPGS` | 11,241 / 1,735 | 2.9603 | 0.0996 |
| — | attempt5b | validity (next counterexample): **refused by the guard**, not sent | — | — | — | 3.0382 | 0 |

**Spend.** Attempt 5 sent 13 calls, with 127,892 input and 46,265 output tokens. That is about
USD 1.437 at the listed 4 / 20 and **USD 1.796 at the ceiling 5 / 25**: USD 0.406 in run 1 and
USD 1.390 in run 2. This is against attempt 5's USD 3.00 cap, and USD 1.204 of it is unused. Of
that, USD 1.00 was the re-review reserve, which was never reached. No call was retried.

Earlier attempts are counted separately, each under its own cap:
- attempts 1–2: USD 2.677 at ceiling;
- attempt 3: USD 1.009;
- attempt 4: USD 1.371.

**Evidence.** Everything is under `evidence/t038-live-arc-2026-09-26/`:
- run 1: `attempt5.json` (the 503) and `attempt5-01-arc-generation.txt` (the live graphs);
- run 2: `attempt5b.json` and 12 raw answers `attempt5b-NN-arc-criticism-<purpose>.txt`;
- the shared ledger `attempt5-ledger.json`.

The JSON, the ledger and all raw answers were checked key-free and contain no model id.

**T038 is not ticked.** Again no live candidate passed live criticism. So there was no owner
selection, no live re-review of a derived version, and no refused-unqualified or
simulated-qualification preparation. The 0/1/2/3, revision and cancel paths remain exercised
offline in `app/tests/browser-design.test.mjs`. That is the single test *"0/1/2/3 presented, a
refused call, an edit re-reviewed and prepared, and cancel — in the real browser"*, run with
scripted test-actor turns and the simulated qualification labelled. The live half of T038 is
still open.

## 2026-09-26 (attempt 6): corrected work and a deterministic store step — nothing passed

The owner authorized one more live attempt (decisions.md, 2026-09-26, "Owner decisions after
T038 attempt 5"). It has its **own USD 3.00 cap** and its own ledger
(`attempt6-ledger.json`), and allows up to 2 candidates with USD 1.00 reserved for the
re-review. The critic contract, the fold and the critic prompt were **not** changed.

### What changed before the run

- **Product: deterministic tool bindings** (owner decision). A deterministic (model-free) node
  may now name approved tool bindings. The graph schema accepts
  `{handler_id, tool_binding_ids}`. The compiler validates those bindings against the
  authority exactly as it does for an agent's.
  - At runtime the node reaches its tool only through the same attempt dispatcher and
    compiled tool transport as an agent. Grants, per-attempt execution-bound approvals, budget
    claims and ToolCall records all go through that path.
  - Contract note: `contracts/runtime.md` §2 (dated). Tests:
    `app/tests/test_deterministic_tool_bindings.py`.
  - The generation grammar (`design_live._OUTPUT_SCHEMA`) now states the option.
  - The critic projection lists a deterministic node's tool binding as a control note, with
    its definition, operations and grant. Graphs without such a binding project
    byte-identically.
- **The work (SIMULATED owner, labelled)** fixes its author's own two attempt-5 defects
  (`app/tests/design_specified_work.py`).
  - The required `verifier` responsibility now states completion condition 2 exactly: inputs,
    model separation, report fields and the verdict rule. It also names every clause of
    conditions 0 and 1. The report covers every non-empty draft line, the title included.
  - Condition 4 and the storage authority now say the store is a model-free deterministic
    step. It hands the approved bytes to `document.create` unchanged.
  - Offline tests in `test_design_specified_work.py` check the alignment. They also check
    that a deterministic store bound to the authority's `document_create` tool is admitted and
    is shown to the critic.

### Run (`attempt6`, `test_claude_live_design_selection.py`, same product path)

**Settings.**
- `DEEPTWIN_LIVE_WORK=specified`.
- 2 requested candidates, 1 round, generation cap 28,000 tokens, criticism cap 6,000.
- USD 1.00 re-review reserve; ceiling USD 5 / 25 per MTok.
- The catalog's first model (id redacted).
- No retry and no fallback. The key was never printed.

**Generation.** The live generation returned **1** graph, which was admitted. The storing role
is now a **deterministic** node `store` bound to `document_create`, the first live use of the new
binding. The graph's nodes are:
- `intake` (deterministic);
- `writer` (agent, …213);
- `verify-join` → `verifier` (agent, …215);
- `verdict-router`, with pass → `approval-join` → `publish-gate` (human gate) → `store`
  (deterministic + tool), and fail → `halt` (deterministic).

**Criticism of `ff39eef8`.**
- **Review: all 8 findings pass.** These are claim, effect, disposition and completion 0–4,
  including condition 2's inputs, model and report, and condition 4's model-free store.
- **Counterexamples (4):**
  - Two were **rejected** by the validity judge:
    - `cx-verifier-input-mediated-by-join`: the join is declared transformation-free;
    - `cx-gate-output-not-constrained-to-verified-bytes`: the deterministic store stores only
      the gate's approved version.
  - Both attempt-5 defects are therefore gone: no verifier-text finding, and no
    model-driven-storage finding.
  - Two stayed **unresolved**:
    - `cx-fail-verdict-reaches-approval-via-data-handoff`: `approval-join`'s data handoffs from
      the verifier and bundle are unconditional, and only control edge e6 carries
      `verification_verdict eq pass`.
    - `cx-verdict-fact-unbound-to-report`: no node is declared to emit the routing fact from
      the report's overall verdict.
  - Neither was proven, and neither was refuted from what the candidate declares.

**Outcome.** Run `fa2d8f13-9cb9-524b-8e10-2251c0ffbd1e` ended in **`shortfall`**, 0 of 1
presented. The candidate was excluded as `insufficient_evidence`, with 2 unresolved validity
judgements. Evidence id: `f8c21eca-599f-49d9-9f6b-5af26c2edbe9`.

**Owner path.** Nothing was presented, so none of the owner steps took place: no selection, no
re-review, no unqualified preparation (which must be refused) and no simulated-qualification
preparation. The simulated qualification was **not used**. The guard refused nothing.

**Analysis.** The two author defects are fixed, and the live critic no longer raises them. The
remaining open points are about **how the graph binds its routing fact to the verifier's report**
and whether a join's unconditional data inputs can bypass the router. Both are generation/graph
questions. The critic itself left them undecided: not a failure, and not a pass. No change was
made after the run. A further attempt needs the owner's authorization.

### Calls (provider-reported; all `completed / end_turn`; no cache tokens; bound = the guard's ceiling-rate bound before the send, incl. the USD 1.00 reserve)

| # | purpose | provider message id | request id | input / output tokens | bound USD | spend USD (ceiling) |
|---|---|---|---|---|---|---|
| 1 | design_candidate (1 graph, cap 28,000) | `msg_011CfRXo4ScPwCTKxoTgEdqB` | `req_011CfRXo3YnF46mHXuLRBha3` | 9,197 / 10,556 | 1.7978 | 0.3099 |
| 2 | review (`ff39eef8`): 8 × pass | `msg_011CfRXuuzoH8XsqtaQdcu7S` | `req_011CfRXuuPLhEEbH26ERQYVy` | 8,856 / 4,317 | 1.5449 | 0.1522 |
| 3 | counterexample_proposal (4) | `msg_011CfRXxSApFavw8UmBb2WkE` | `req_011CfRXxREGGF8Xhe3sRsV6J` | 10,417 / 4,783 | 1.7107 | 0.1717 |
| 4 | validity `cx-fail-verdict-reaches-approval-via-data-handoff`: unresolved | `msg_011CfRY1YpkQNVdYq9DickJf` | `req_011CfRY1YHkZ4UsLr5Hd9M6H` | 9,643 / 2,612 | 1.8788 | 0.1135 |
| 5 | validity `cx-verdict-fact-unbound-to-report`: unresolved | `msg_011CfRY3LFmQkcvQD8uy8SNF` | `req_011CfRY3KqD6N5L61E3dwW2X` | 9,482 / 1,870 | 1.9904 | 0.0942 |
| 6 | validity `cx-verifier-input-mediated-by-join`: rejected | `msg_011CfRY4bxrKpv7p4MLNuUra` | `req_011CfRY4bX43WdRacd7GVVdE` | 9,562 / 2,089 | 2.0854 | 0.1000 |
| 7 | validity `cx-gate-output-not-constrained-to-verified-bytes`: rejected | `msg_011CfRY65W5wnJygw1ftWSec` | `req_011CfRY64jSYs8brh5PTFrXy` | 9,380 / 1,852 | 2.1831 | 0.0932 |

**Spend.** Attempt 6 sent 7 calls, with 66,537 input and 28,079 output tokens. That is
**USD 1.035 at the ceiling 5 / 25**, against attempt 6's USD 3.00 cap, leaving USD 1.965 unused.
No call was retried or refused. Earlier attempts are counted separately under their own caps.

**Evidence** (under `evidence/t038-live-arc-2026-09-26/`):
- `attempt6.json`;
- 7 raw answers `attempt6-NN-arc-<stage>[-<purpose>].txt`; the generation answer's sha256 is
  `d6b7028f…af1f`;
- `attempt6-ledger.json`.

All were checked key-free, with no model id.

**T038 is not ticked.** No live candidate passed live criticism. So there was no owner
selection, no live re-review of a derived version, and no refused-unqualified or
simulated-qualification preparation. The 0/1/2/3, revision and cancel paths remain exercised
offline in `app/tests/browser-design.test.mjs`, the single test *"0/1/2/3 presented, a refused
call, an edit re-reviewed and prepared, and cancel — in the real browser"*. It uses scripted
test-actor turns, with the simulated qualification labelled.

## 2026-09-26 (attempt 7): two live candidates pass, a live selection, the re-review is unresolved

The owner authorized one more live attempt on attempt 6's terms (decisions.md, 2026-09-26,
"Owner decision after T038 attempt 6"). It has its **own USD 3.00 cap** and its own ledger
(`attempt7-ledger.json`), 2 requested candidates and USD 1.00 reserved for the re-review. The
critic contract, the fold and the critic prompts were **not** changed.

### What changed before the run (offline, commit "T038 attempt 7 prep")

- **Generator design rules (i)–(j)** (`app/services/design_live.py`, `_CRITIC_DESIGN_RULES`).
  They state a property of the graph grammar itself: an artifact edge carries no condition and
  triggers its target, and a router has no artifact output.
  - (i) A check's pass decision is a declared **deterministic verdict step in the data path**.
    It reads the check report (through a join that also carries the checked content and the
    originals, unaltered). Only when the report's overall verdict field is the passing value
    does it emit those inputs byte for byte under its own verified-package contract.
    Otherwise it fails with `fail_run`. The gate and the release read only that package, and
    no artifact edge crosses from before the verdict step to after it.
  - (j) A router that decides on a verdict reads the report through its own artifact edge,
    and its decision fact is the report's overall verdict field. Its passing arm never leads
    to a node fed from before the router; when the path after the decision needs such
    artifacts, (i) is used instead.
  - Rule (e) now points to (i)–(j) for its router option.
- **Candidate count.** Attempt 6 got 1 of 2 graphs. The output schema said only "between one
  and the requested number", and the profile forbids renaming one topology. The first-round
  prompt (not a revision) now asks for the requested number of **structurally different**
  graphs, returning fewer only when no further structurally different graph satisfies every
  rule, and gives generic examples of structural variation.
- **The work (SIMULATED owner, labelled)** (`app/tests/design_specified_work.py`). Condition 3
  and the work text now state how a fail verdict blocks: a declared model-free decision step
  reads the report's overall verdict field, and only what it passes on reaches approval and
  storage. The verifier effect text is unchanged.
- **Offline tests.** In `test_design_live.py`: the rules and the count rule reach the prompt,
  with no task wording. In `test_design_specified_work.py`: condition 3's wording;
  attempt 6's saved answer still replays and is admitted; and a verdict-step rework of
  attempt 6's graph is admitted, with no crossing artifact edge, and projected for the critic.
  All of design_live, design_criticism, design_criticism_live, design_arc,
  design_specified_work, deterministic_tool_bindings, design_generation and graph_contract
  pass, one file per process, with the key unset.

### Run (`attempt7`, `test_claude_live_design_selection.py`, same product path)

**Settings.** These were the same as attempt 6:
- `DEEPTWIN_LIVE_WORK=specified`, 2 requested candidates, 1 round;
- generation cap 28,000 tokens, criticism cap 6,000;
- USD 1.00 re-review reserve, ceiling USD 5 / 25 per MTok;
- the catalog's first model, id redacted;
- no retry and no fallback, and the key was never printed.

**Generation.** The live generation returned **2** graphs, and both were admitted. Both follow
(i): neither graph has a router.
- `b9c93c06`: `intake` → `writer` → `draft-join` → `verifier` → `verdict-join` (bundle + report)
  → `verdict` (deterministic, `fail_run`) → `publish-gate` → `store` (deterministic +
  `document_create`).
- `120ba5fe`: the same, plus a deterministic `structure-precheck` on the draft bundle. The
  verdict step reads both reports.

**Arc criticism.**
- `b9c93c06`: review **8 × pass**. 1 counterexample (`cx-report-consistency-unchecked`),
  **rejected**. Verdict **passed**.
- `120ba5fe`: review **8 × pass**. 2 counterexamples (`cx-overall-verdict-inconsistency`,
  `cx-verifier-source-via-join`), both **rejected**. Verdict **passed**.
- The pool presented **2** (passed 2, excluded 0). The run's recorded outcome is `shortfall`
  only against the pool size of 3. Run `cca40bfa-3752-556e-ae18-863307b7c1d7`.
- This is **the first live selection pool with presented live candidates**. Attempt 6's two
  unresolved points (unconditional data into approval; an undeclared routing fact) were not
  raised again.

**Owner path (SIMULATED owner, the test actor; labelled).**
- **Selection.** The first presented candidate, `120ba5fe`, was selected through
  `derivations` (`select`), HTTP 201. That created the derived version `727719dc`.
- **Live re-review** (`reviews`, HTTP 201; 4 live calls in the owner phase):
  - review 8 × pass;
  - `cx-inconsistent-verifier-report` **rejected**;
  - `cx-unlabeled-bundle-items` **unresolved**. The draft bundle's two text/markdown items carry
    no declared labels, so whether the handlers keep item identity is not stated.
  - The re-reviewed version is therefore **`insufficient_evidence`**. The same graph passed in
    the arc; the live critic's second pass raised a point the first did not.
- **Preparation without qualification.** Refused: HTTP 409 `not_approvable`, *"only a passed
  design version is approvable"*. It was refused, but because the version did not pass, not
  on the qualification check.
- **Preparation with the SIMULATED qualification.** The view showed
  `simulated_qualification: true` and `approvable: true` for the environment. The call was
  still refused with HTTP 409 on the same reason. **Nothing was prepared.**
- The guard refused nothing.

### Calls (provider-reported; all `completed / end_turn`; no cache tokens; bound = the guard's ceiling-rate bound before the send, incl. the USD 1.00 reserve in the arc phase)

| # | phase | purpose | provider message id | request id | input / output tokens | bound USD | spend USD (ceiling) |
|---|---|---|---|---|---|---|---|
| 1 | arc | design_candidate (2 graphs, cap 28,000) | `msg_011CfRdnGt8bLCakBJFJmcAD` | `req_011CfRdnG4H3JTakg71M1fs1` | 10,078 / 12,423 | 1.8109 | 0.3610 |
| 2 | arc | review (`b9c93c06`): 8 × pass | `msg_011CfRdtpem24kGQisf2uor9` | `req_011CfRdtp43HgUXDTZEwrjw2` | 9,163 / 3,741 | 1.5971 | 0.1393 |
| 3 | arc | counterexample_proposal (1) | `msg_011CfRdw2VTPe7emrA1LdQju` | `req_011CfRdw1zw1VsMigDmj6N9U` | 10,725 / 2,606 | 1.7500 | 0.1188 |
| 4 | arc | validity `cx-report-consistency-unchecked`: rejected | `msg_011CfRdxtWnZLJWYj4cwzQvZ` | `req_011CfRdxsQoyKeVLVTsPimGj` | 10,023 / 1,784 | 1.8666 | 0.0947 |
| 5 | arc | review (`120ba5fe`): 8 × pass | `msg_011CfRdzFMCgW4fkmzpPUUaj` | `req_011CfRdzEkUh2Gp2Wh4J9D63` | 9,664 / 4,247 | 1.9564 | 0.1545 |
| 6 | arc | counterexample_proposal (2) | `msg_011CfRe2o2Fb3D8tgCCnEbQL` | `req_011CfRe2nYySXmNknyftiT7C` | 11,226 / 3,536 | 2.1245 | 0.1445 |
| 7 | arc | validity `cx-overall-verdict-inconsistency`: rejected | `msg_011CfRe5HLPo61HvTH48nMsL` | `req_011CfRe5GjgTZ2DcMvv8tiPa` | 10,356 / 1,858 | 2.2645 | 0.0982 |
| 8 | arc | validity `cx-verifier-source-via-join`: rejected | `msg_011CfRe6dSuDVoF5PbyHAjcx` | `req_011CfRe6cz7Yk183zzZUPEej` | 10,283 / 1,882 | 2.3619 | 0.0985 |
| 9 | owner | re-review (`727719dc`): 8 × pass | `msg_011CfRe82fvj4SCtzfp8TmiS` | `req_011CfRe81bggtUwxSB97evgD` | 9,664 / 5,072 | 1.4521 | 0.1751 |
| 10 | owner | counterexample_proposal (2) | `msg_011CfReAzgSv3zM9dFDHFh2T` | `req_011CfReAyvZCtwfpNuL5fAbu` | 11,226 / 3,234 | 1.6408 | 0.1370 |
| 11 | owner | validity `cx-inconsistent-verifier-report`: rejected | `msg_011CfReDDPk7i3dByi7DMp4z` | `req_011CfReDCtUKZaPvFvLEjmH4` | 10,406 / 2,075 | 1.7741 | 0.1039 |
| 12 | owner | validity `cx-unlabeled-bundle-items`: unresolved | `msg_011CfReEdsuvEEtK1fAMpgPz` | `req_011CfReEdNuTXXGr4frRZ1kv` | 10,348 / 2,130 | 1.8771 | 0.1050 |

**Spend.** Attempt 7 sent 12 calls, with 123,162 input and 44,588 output tokens. That is
**USD 1.731 at the ceiling 5 / 25**: 1.210 in the arc and 0.521 in the re-review. This is
against attempt 7's USD 3.00 cap, leaving USD 1.269 unused. No call was retried or refused.

**Evidence** (under `evidence/t038-live-arc-2026-09-26/`):
- `attempt7.json` (evidence id `83875e05-0c38-4328-8369-fd036c5a972e`);
- 12 raw answers `attempt7-NN-<phase>-<stage>[-<purpose>].txt`; the generation answer's sha256
  is `bdfba8d0…0d38`;
- `attempt7-ledger.json`.

All were scanned: key-free, with no model id.

**T038 is not ticked.** Real live generation → live critique → a live-presented pool → the
(simulated) owner's selection → a live re-review all happened, for the first time. But the
re-reviewed version was `insufficient_evidence`. So both preparations were refused as "only a
passed design version is approvable":
- the unqualified refusal did not exercise the qualification check;
- the preparation with the labelled simulated qualification did not happen.

The full path the task requires (… → refused unqualified preparation → preparation with the
labelled simulated qualification) therefore did not complete live. The 0/1/2/3, revision and
cancel paths stay covered offline in `app/tests/browser-design.test.mjs`.

**Analysis.** The two graph-design points attempt 6 left unresolved are gone. Both candidates
passed live criticism. What remains is one point the re-review raised: aggregate bundles whose
items are not labelled, so which item is the draft rests on handler behaviour. That points to
a generic rule for a later attempt: a join's aggregate contract declares each item's role
(for example, per-item labels or one slot per original). Criticism is also not stable across
two passes over the identical graph: `120ba5fe` passed, and `727719dc`, its unedited
selection (the same functional graph under a new version identity), was unresolved. No change was made after the run. A further attempt needs the
owner's authorization.

## 2026-09-26 (attempt 8): a passed live re-review, both preparations — the full path live

The owner authorized one more live attempt on exactly the terms of attempts 6 and 7
(decisions.md, 2026-09-26, "Owner decision after T038 attempt 7"). It has its **own USD 3.00
cap** and its own ledger (`attempt8-ledger.json`), 2 requested candidates and USD 1.00 reserved
for the re-review. The critic, its contract, the fold and the critic prompts were **not**
changed.

### What changed before the run (offline, commit "T038 attempt 8 prep")

- **Generator design rule (k)** (`app/services/design_live.py`, `_CRITIC_DESIGN_RULES`): every
  item handed on declares its role.
  - The grammar cannot label items inside a contract. An artifact contract
    (`app/domain/graph_schema.py`, `ArtifactContract`) declares only `media_types`, `min_items`,
    `max_items` and `max_total_bytes`; `schema_ref` stays null; a slot carries exactly one
    contract. So an item's role can only be carried by the slot it travels in.
  - The rule therefore uses the closest expressible form. A join, and a step that passes several
    items on unaltered (the verdict step of (i), a gate), declares **one output slot per original
    item**, each under its own new contract with `min_items`/`max_items` 1, named for the item's
    role. Each item goes by its own artifact edge to a consumer input slot of that role, and the
    consumer's responsibility names the slot it reads each item from. Items of different roles
    never share a multi-item slot or contract.
  - Rules (f) and (i) now point to (k): the join's and the verdict step's pass-through outputs
    are per-item slots, not one bundle or "verified-package" contract.
- **The work (SIMULATED owner, labelled)** is unchanged, including its label.
- **Offline tests.** In `test_design_live.py`: rule (k) and the (f)/(i) pointers reach the
  first-round and revision prompts, with no task wording. In `test_design_specified_work.py`:
  attempt 7's saved answer still replays (both graphs admitted); a one-slot-per-item rework of
  attempt 7's first graph (draft join, verdict join and verdict step) is admitted, every contract
  holds one item, and the critic projection carries the per-role contracts. The attempt 5 and 6
  replay tests still pass. All of design_live, design_criticism, design_arc,
  design_specified_work, deterministic_tool_bindings, design_generation, graph_contract and
  design_criticism_live pass, one file per process, with the key unset.

### Run (`attempt8`, `test_claude_live_design_selection.py`, same product path)

**Settings.** The same as attempts 6 and 7:
- `DEEPTWIN_LIVE_WORK=specified`, 2 requested candidates, 1 round;
- generation cap 28,000 tokens, criticism cap 6,000;
- USD 1.00 re-review reserve, ceiling USD 5 / 25 per MTok;
- the catalog's first model, id redacted;
- no retry and no fallback, and the key was never printed.

**Generation.** The live generation returned **2** graphs, and both were admitted. Both follow
rule (k): every contract in both graphs has `max_items` 1, and every join and the verdict step
hand on one slot per item (`source`, `draft`, `report`, …).
- `e2f0d731`: `source-intake` → `writer` → `verify-join` (slots `joined-source`,
  `joined-draft`) → `verifier` → `verdict-join` (slots `report`, `draft`, `source`) → `verdict`
  (deterministic, slots `verified-draft`, `verified-report`, `verified-source`) → `publish-gate`
  → `store` (deterministic + `document_create`) → `audit-join` → `store-audit` (deterministic
  byte-equality audit).
- `8fdc10cd`: the same, plus a deterministic `structure-precheck`, whose report travels in its
  own slot through the verdict step.

**Arc criticism.**
- `e2f0d731`: review **8 × pass**. 2 counterexamples, both **rejected**:
  `cx-approval-edge-e16-unbound` (the approval edge's id is not among the handoffs, but the gate
  and the store's approval scope are declared) and `cx-verifier-source-via-join` (the join is
  declared transformation-free; the verifier reads the source and the draft each in its own
  slot). Verdict **passed**.
- `8fdc10cd`: review **8 × pass**. 3 counterexamples: `ce-report-verdict-consistency-unenforced`
  **rejected**; `ce-approval-edge-mismatch` **unresolved**; the third (`ce-post-hoc-byte-audit`)
  was **not sent**: the spend guard refused its validity call (bound USD 3.0048 including the
  USD 1.00 reserve, over the 3.00 cap). The arc recorded the refusal, and the candidate was
  excluded as `unreviewed`.
- The pool presented **1** (passed 1, excluded 1 `unreviewed`). The run's recorded outcome is
  `shortfall` against the pool size of 3. Run `7ca1b161-080a-5ba7-88e5-a8ec7ce1e44e`.
- Attempt 7's re-review point (`cx-unlabeled-bundle-items`) was not raised again in any of the
  three criticisms.

**Owner path (SIMULATED owner, the test actor; labelled).** Every step went through the
workspace routes:

| step | route | HTTP | outcome |
|---|---|---|---|
| selection of `e2f0d731` (the one presented) | `derivations` (`select`) | 201 | derivation `628a7039`, derived version `1adbf820`, re-review required |
| live re-review of `1adbf820` (4 live calls) | `reviews` | 201 | review 8 × pass; `cx-store-audit-after-write` **rejected**; `cx-verifier-source-via-join` **rejected**; verdict **passed** |
| preparation, no critic qualification | `preparations` | 409 | `not_approvable`: *"the critic configuration is not qualified (unknown: no_suite_record)"*, refused by the **qualification check** |
| preparation view with the SIMULATED qualification | (read) | 200 | `simulated_qualification: true`, `approvable: true` (test-actor V3-verifying design id) |
| preparation with the SIMULATED qualification | `preparations` | 201 | `prepared`: environment `a155b153` version 1 over graph `cddc84d0` (sha256 `93bc7207…e8cf`), approval record `e5b54dc6`, `activation: not_activated` |

The preparation rests on the owner-authorized SIMULATED test-actor qualification (decisions.md
2026-09-25). It is labelled so in the evidence (`simulation`), and it is **not** a release
qualification.

### Calls (provider-reported; all `completed / end_turn`; no cache tokens; bound = the guard's ceiling-rate bound before the send, incl. the USD 1.00 reserve in the arc phase)

| # | phase | purpose | provider message id | request id | input / output tokens | bound USD | spend USD (ceiling) |
|---|---|---|---|---|---|---|---|
| 1 | arc | design_candidate (2 graphs, cap 28,000) | `msg_011CfRfNJREKD36BZafcjLcN` | `req_011CfRfNHdM6pD4JoRxnvYuh` | 10,452 / 21,025 | 1.8173 | 0.5779 |
| 2 | arc | review (`e2f0d731`): 8 × pass | `msg_011CfRfZMvryfQuYWMMGznz2` | `req_011CfRfZLczFW7g3TTDTnJgQ` | 11,302 / 4,372 | 1.8307 | 0.1658 |
| 3 | arc | counterexample_proposal (2) | `msg_011CfRfc2QTCPPrEiZSPDo87` | `req_011CfRfc1wAmZZ2N8ejEH6Uz` | 12,864 / 3,956 | 2.0101 | 0.1632 |
| 4 | arc | validity `cx-approval-edge-e16-unbound`: rejected | `msg_011CfRfesHrREo2u82qy68MC` | `req_011CfRferettKRPdvhJjxYL6` | 11,960 / 2,456 | 2.1679 | 0.1212 |
| 5 | arc | validity `cx-verifier-source-via-join`: rejected | `msg_011CfRfgZBjbxQY21u7oTw1T` | `req_011CfRfgYihYE8SY6UW9fQph` | 11,916 / 2,003 | 2.2889 | 0.1097 |
| 6 | arc | review (`8fdc10cd`): 8 × pass | `msg_011CfRfhzyoGmPxadFu3U3Dv` | `req_011CfRfhzMb33p7qkvNskmJo` | 12,373 / 4,000 | 2.4014 | 0.1619 |
| 7 | arc | counterexample_proposal (3) | `msg_011CfRfkYfLngGZEPhpMvbnc` | `req_011CfRfkXLxa8pS48U88xGMF` | 13,935 / 5,243 | 2.5769 | 0.2008 |
| 8 | arc | validity `ce-approval-edge-mismatch`: unresolved | `msg_011CfRfp35xuBXQbZV86U24u` | `req_011CfRfp2cSHcSb7APovGL6U` | 12,908 / 2,260 | 2.7706 | 0.1210 |
| 9 | arc | validity `ce-report-verdict-consistency-unenforced`: rejected | `msg_011CfRfqc86f1L3gQRMKs5Ka` | `req_011CfRfqbXNcgBbEbK17wVKw` | 13,071 / 1,891 | 2.8945 | 0.1126 |
| — | arc | validity `ce-post-hoc-byte-audit`: **refused by the guard, not sent** | — | — | — | 3.0048 | 0 |
| 10 | owner | re-review (`1adbf820`): 8 × pass | `msg_011CfRfrz4UUa6XK7WCN4RiR` | `req_011CfRfryZxSZmJEfynvaQ9H` | 11,296 / 4,562 | 1.9869 | 0.1705 |
| 11 | owner | counterexample_proposal (2) | `msg_011CfRfuju2e9kae5AuRWo4E` | `req_011CfRfuip2ovK7yDicdLLAv` | 12,858 / 4,469 | 2.1710 | 0.1760 |
| 12 | owner | validity `cx-store-audit-after-write`: rejected | `msg_011CfRfxrppvqA8kZixY7FfD` | `req_011CfRfxr5vQLmeWjtteK1cH` | 11,928 / 1,882 | 2.3426 | 0.1067 |
| 13 | owner | validity `cx-verifier-source-via-join`: rejected | `msg_011CfRfzCRZYZ5f8jG6NZf7b` | `req_011CfRfzBwnxqmCk81sdA9qu` | 11,899 / 2,596 | 2.4481 | 0.1244 |

**Spend.** Attempt 8 sent 13 calls, with 158,762 input and 60,715 output tokens. That is
**USD 2.312 at the ceiling 5 / 25**: 1.734 in the arc and 0.578 in the re-review. This is
against attempt 8's USD 3.00 cap, leaving USD 0.688 unused. No call was retried. The guard
refused one arc send, and nothing was sent for it. That refusal kept the reserve for the
re-review, which then completed.

**Evidence** (under `evidence/t038-live-arc-2026-09-26/`):
- `attempt8.json` (evidence id `b265f2dd-dc1d-49ae-990d-18f6aee109f2`);
- 13 raw answers `attempt8-NN-<phase>-<stage>[-<purpose>].txt`; the generation answer's sha256
  is `3f1f504d…3a32a3`;
- `attempt8-ledger.json`.

All were scanned: key-free, and none contains any model identifier from the live catalog.

**T038 is ticked.** These steps all happened through the product's routes:
- live generation → live critique → a live-presented pool;
- the (simulated) owner's selection → a **passed** live re-review;
- preparation refused for lack of critic qualification;
- preparation with the labelled simulated qualification.

Live: every model call (generation, criticism, re-review). Simulated and labelled: the owner
(the test actor's work, lens decision, selection and approval) and the critic qualification
used for the second preparation. The 0/1/2/3, revision and cancel paths stay covered offline in
`app/tests/browser-design.test.mjs`, which passed again after the run.

**Analysis.** Both live graphs followed rule (k), and the unlabelled-bundle point did not recur.
The critic raised one point twice (rejected once, unresolved once): how the critic projection
cites approval edges. The control notes name an approval edge by its own id, which is not among
the artifact handoffs. The point did not decide this run. Clarifying it in the critic projection
would need its own decision, because the critic side was held fixed here. None of this is a
release qualification: no critic or lens is qualified in production, `V3_VERIFYING_DESIGN_IDS`
is empty and V3 is unverified (T077).

## Not ticked (history before attempt 8)

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
or (simulated-qualification) preparation took place. Attempt 7 (above) changed that up to the
re-review. Two live candidates passed live criticism and were presented. The simulated owner
selected one, and it was re-reviewed live. But the re-review came out `insufficient_evidence`,
so neither preparation (unqualified, or with the simulated qualification) reached the
qualification check. T038 stays open for a re-reviewed version that passes and completes both
preparations. In any case none of this is a release
qualification: no critic or lens is qualified in production, `V3_VERIFYING_DESIGN_IDS` is empty
and V3 is unverified (T077).

Attempt 8 (above) closed this: a live candidate passed live criticism, was selected by the
simulated owner, passed its live re-review, was refused preparation without qualification, and
was prepared with the labelled simulated qualification. T038 is ticked on that run.

## Open

- (Until attempt 8) no live candidate had passed live criticism and been selected and prepared.
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
  - Attempt 5 (2026-09-26 (attempt 5), above) used a different, better-specified work. The
    critic's verdicts became decisive: both candidates failed on valid counterexamples, with none
    unresolved.
    - Part of the failure came from the test actor's own verbatim effect text, which is looser
      than condition 2.
    - Part came from byte-identical storage that the authority cannot guarantee, because storage
      happens only through a tool, and tools bind only to agents.
    - Attempt 5's cap has USD 1.204 left, and a further attempt needs the owner's authorization.
  - Attempt 6 (2026-09-26 (attempt 6), above) fixed both author defects and used the new
    deterministic store binding. The live candidate passed all 8 review findings, and 2 of its
    4 counterexamples were rejected. It was excluded as `insufficient_evidence` on 2 unresolved
    counterexamples about binding the routing fact to the report, and about the join's
    unconditional data inputs.
    - Attempt 6's cap has USD 1.965 left, and a further attempt needs the owner's
      authorization.
  - Attempt 7 (2026-09-26 (attempt 7), above) added rules (i)–(j) and the count rule. Both
    live candidates passed live criticism and were presented, and the simulated owner selected
    one.
    - The live re-review of the selected version stayed `insufficient_evidence`, on unlabelled
      bundle items. So both preparations were refused as not approvable, and nothing was
      prepared.
    - Attempt 7's cap has USD 1.269 left, and a further attempt needs the owner's
      authorization.
  - Attempt 8 (2026-09-26 (attempt 8), above) added rule (k): one slot per handed-on item.
    The full path completed live, with the simulated owner and the simulated qualification
    labelled. Attempt 8's cap has USD 0.688 left.
- Production cannot create a design request: no lens is qualified, so no `DesignSource` is
  configured, and the page and the route say so. A production source would also need the owner's
  model turns wired from the Claude connection and a production functional-decision step (T030).
  The test actor's source is SIMULATED.
- A request registered by host code without a stored basis (the older fixtures) is not
  restorable.
- A merge has no generation turn that realizes it.
- Preparation stays impossible in production (T077).
