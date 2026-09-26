# T077 — SIMULATED dress rehearsal of the release-v7 pipeline (2026-09-25/26)

**This is a simulation. It is NOT a release qualification, NOT a scoped pass and NOT evidence that the critic is qualified.** The owner asked for the steps that need independent people to be simulated (decisions.md, "2026-09-25 — Owner delegations recorded"). Every one of those roles was played by a simulated actor. release-v7 excludes each of them: `dataset.authoring.excluded_as_author_reviewer_or_judge` names "any model or session with repository access", and the judge must not share the critic's provider family (`judge.judge_binding`). The pinned profile records judge separation as **not established**. Under the design this caps the run at `not_judged`, and the product gate stays closed. The gate returned `unqualified` for both runs.

## Actors (all simulated)

| Role | Who actually did it |
|---|---|
| simulated-author | This Claude Code session. It has full repository access and also wrote the T077 dispatcher, so it can read the harness, the verifiers and the calibration cases. |
| simulated-reviewer | The same Claude Code session. No second person was involved. |
| simulated-sealer | The same Claude Code session. |
| simulated-judge (offline run) | A deterministic stub (`SimulatedJudgeStub`) written by the same session. It answers `supported` with stub provider ids, and no provider answers it. |
| simulated-judge (live subset) | The Claude judge (`verifiers/claude_judge.py`) over the Claude API. It is the critic's own provider family, and the same session configured it. |

## What was built

- **T077 dispatcher**: `evals/deeptwin/qualification/dispatch.py` (`q01-t077-dispatcher-1`). It is new code that only calls the pinned harness, verifier and gate. No file pinned by any FROZEN.json was edited (`test_release_design_frozen.py` passes).
  - It refuses to start unless all of these hold:
    - the manifest verifies against the committed sha256, the running harness and the running verifier;
    - the `git_commit` ref's tree contains the manifest sha256 (checked with `git grep`);
    - the journal belongs to this manifest.
  - It keeps a persisted **attempt ledger** outside the repository:
    - `prior_attempts` must equal the ledger's entries for the configuration digest;
    - a set that any recorded manifest used, under any configuration, is refused (dataset sha, expectations sha, case ids or case shas);
    - the set is **marked spent** before the first dispatch, and the outcome is recorded after the verdict.
  - It dispatches the planned slots in journal order with concurrency 1, no retry and no fallback. The next slot is always `planned_slots[len(journal)]`, so a restart resumes and never re-dispatches.
  - It enforces the **USD hard stop** twice:
    - before each trial, it checks spent + the judge reserve + the trial's worst case;
    - on every call, the rig guard (`SpendMeter`, persisted as `spend.jsonl`) checks again. A crossing call is never sent.
    - In both cases it writes the stop entry via `q01_harness.journal_stop`. An owner cap (`max_slots`) also ends the run with a journalled stop.
  - It verifies each journalled trial **once**, in process, after the last dispatch. It then builds the suite, the suite record and the gate state.
  - It writes a report covering every item of the design's `reporting` list.
- **Offline tests** (`evals/deeptwin/tests/test_t077_dispatcher.py`, 10 tests): they use the fake provider server and the `DevCritic`/`DevJudge` fixtures.
  - A full run of 39 trials passes, and the gate caps it at `scoped_pass`.
  - Every report section is present.
  - A USD stop before a trial gives `incomplete`, `run_stopped`, `suite_incomplete`, and the harness refuses the next dispatch.
  - A call that would cross the stop is never sent.
  - After a crash between trials, a new process resumes with 39 review calls in total (none re-dispatched) and the suite passes.
  - A slot journalled by a crashed process is not re-dispatched, and the suite is `incomplete`.
  - Spent sets are refused in four cases: the same manifest again, attempt 2 on the same set, a hidden attempt 1, and another configuration.
  - The attempt ledger numbers attempts across two sets: attempt 2 records `prior_outcomes: ["incomplete"]`.
  - A bad committed sha or commit ref is refused, and so is a same-family judge.
  - Set and profile checks: `test_t077_rehearsal_sets.py` (5 tests).
- **Simulated rehearsal material**, in `evals/deeptwin/qualification/rehearsal_t077/`:
  - `simulated_sets.py` authors two sets. `sim-orchard` is an invented orchard co-op's harvest-share notice. `sim-ferry` is an invented island ferry's timetable-change leaflet.
  - Each set has 13 cases: 2 accept (one of them a Q4 alternative), 3 required defects (Q1, Q2 and Q3), 2 rejected, 2 valid (a Q5 pair), 2 unresolved and 2 insufficient. This meets the v7 composition check.
  - The expectations follow `sealed_expectation.schema.json`, with one judge item per case.
  - `simulated_independence_profile.json` has `simulated: true`, `established: false` and `judge: null`. No product code and no gate names it.
  - `committed_manifests.json` holds the manifest sha256s. The bundles, expectations, manifests, journals, trials, ledger and reports are outside the repository, under `/home/user/deeptwin-t077-rehearsal/`.

## Commits and pinned values

- The manifest sha256s were committed before any dispatch in `bfeca2b1102587cfe2f428db68f2c3ffb3894315`. That commit is the `commit_ref` of both runs, and the dispatcher checked that it contains the sha256.

| Item | sha256 |
|---|---|
| offline manifest (`sim-orchard`) | `1b6022d11a8fb2043d98e488351e635e292a6de4d0446333c9365ad51c08918f` |
| live manifest, dispatched (`sim-ferry`, `judge_model: null`) | `1157d37c79f16d3cbe48264ab57baec162328f5808ee9fd8f1fb1cede24684b3` |
| live manifest declaring the Claude judge honestly (refused) | `93bc0273eb524b58ecf99aa65ef027fcef27d173f2627ff1b6f1c918a9ebacd4` |
| `sim-orchard` dataset / expectations | `df808624…11c4a6` / `98964885…c689b2` |
| `sim-ferry` dataset / expectations | `4d5f991b…e2ba4a` / `c1fc468a…21aaa2` |
| simulated profile | `c66885571a0d3c6c5be00fcea89508c3a8b3c79522ec146c168ea529c7ef1e6d` |

## Run 1: offline, `sim-orchard`, all 39 slots (fake provider server, zero cost)

- **Setup:**
  - The critic ran through the pinned harness, the Claude rig and the product adapter to `claude_mock.MockClaude`. The fake server was admitted as a named test double for this run only (`rehearsal.admitted`); release-v7 admits none.
  - The critic answers were scripted by `SimulatedCritic`. The judge was the stub.
  - The critic configuration digest was `09b9f021…56e51`.
- **Dispatch:** 39 of 39 slots were dispatched, and 114 fake provider requests were made. The journal head was `da87da1a…c6f7c`, with 40 entries and no stop.
- **Per case:** all 13 cases, across all 6 boundary classes, passed 3 of 3 repetitions at trial level. There were no misses, false rejections, abstentions, invalid trials or judge disagreements. The materials form 2 clusters (11 cases share the full originals, and 2 cases have the missing-limit originals).
- **Suite outcome:** `not_judged`, with the reason `judge_separation_not_established`, which comes from the pinned profile.
- **Suite record:** `028cdf67…f000e4`, attempt 1. It records critic and judge transport as `provider_reported`, `run_stopped: false` and 306 provider ids.
- **Gate:** `unqualified` / `suite_not_judged`.
- **Spend:** 114 calls. The *estimated* $1.396 is computed from the fake server's invented token counts at the calibration plan's prices. **Nothing was paid.**
- **Probes after the run:**
  - Running the same manifest again was refused with `attempt_ledger:attempt_already_decided`.
  - An attempt-2 manifest on the same set was refused by the manifest check with `sealed_set_already_spent_by_a_prior_attempt`, `case_id_already_spent_by_a_prior_attempt` and `case_sha256_already_spent_by_a_prior_attempt`.

## Run 2: live subset, `sim-ferry`, owner cap 2 cases × 3 repetitions

- **Setup:**
  - The Claude API rig used the owner-configured key, which was read from the environment only after an explicit flag. The key was never printed or written; the output directory was scanned for it with `assert_secret_absent` and it was absent.
  - There was no injected transport, no retry and no model fallback. The USD hard stop was 3.00.
  - The configuration was effort `medium`, critic `max_tokens` 8000 and `max_proposed_chains` 0. The configuration digest was `6cc7fbbe…4d6f4d6`.
  - The provider catalog listed the pinned model with the efforts high, low, max, medium and xhigh.
- **Same-family judge declared honestly:** the manifest naming the Claude judge's model as `judge_model` was **refused before anything was sent**, with `judge:shares_the_critic_provider_or_model`.
- **Dispatched manifest:**
  - This manifest names no provider judge model. The Claude judge was still asked every item, and its raw answers are in the judge logs, but the verifier counts none of them (`not_judged`, `judge_transport_identity: not_attested`).
  - This is the correct classification: judge separation is not established, and a same-family judge can never count under v7.
- **Dispatch:** 6 of 39 slots were dispatched, then the owner-cap stop was journalled (`owner cap: 6 of 39 planned slots dispatched`, journal head `8a25b62e…f82537`).
- **Served identity:** every critic call was provider-reported as served by `claude-opus-5` with distinct `req_…` and `msg_…` ids, for example `req_011CfR4vzU4uAmGtkDbEHo41` / `msg_011CfR4w1EiGX8RPxogU8By7`.

Per-case results. The slots were dispatched in order; wall time was about 45–80 s per trial.

| Case | Boundary | rep 1 | rep 2 | rep 3 |
|---|---|---|---|---|
| `fb-good` (`q01-8e1aa61446`) | accept_without_false_rejection | fail: Q2 `fail` (false rejection) | fail: Q2 `unresolved` (abstention) | not_judged: every rule passed, item not counted |
| `fb-q1` (`q01-a49c85cf5a`) | required_defect (Q1) | fail: output contract (review output rejected by the product parser) | fail: Q1 found, but Q2 `fail` (false rejection) | fail: Q1 found, but Q2 `fail` (false rejection) |

- Each trial proposed 3 counterexamples. None was driven (limit 0), and the verifier accepted `proposed_not_driven` = 3.
- The Claude judge answered `supported` for all 5 judged items (logged only).
- **Suite outcome:** `fail`, because a fail takes precedence over `incomplete` (`missing_repetition`, `run_stopped`).
- **Suite record:** `f6046944…e3b9222c`, `run_stopped: true`, `judge_separation_established: false`.
- **Gate:** `unqualified` / `suite_fail`.
- **Spend:** 16 calls (11 critic, 5 judge). The provider reported 51,515 input and 37,114 output tokens, which comes to **≈ $1.19 estimated** at the calibration plan's prices ($1.10 critic, $0.09 judge). That is under the 3.00 stop, and the stop was never reached. The provider's billing record is authoritative and was not checked.

## What the pipeline caught

1. **A same-family judge.** The honestly declared Claude judge was refused by the manifest check before dispatch. In the dispatched run its answers were logged but never counted.
2. **Judge separation.** Both runs were capped because the profile does not establish separation: the offline run was `not_judged` and the gate closed.
3. **The owner cap as a stop.** The live run's stop was journalled, the harness refuses any further dispatch, and `run_stopped` is in the record.
4. **An output-contract error was a fail, not invalid.** `fb-q1` rep 1's review was rejected by the product parser (`model_output_invalid`), and it was scored as a fail of that repetition, as the design requires.
5. **Spent sets.** Rerunning, a second attempt, a hidden attempt 1 and another configuration on a spent set were all refused. The last two are refused by the dispatcher's ledger, not by the frozen manifest check.
6. **An authoring gap the simulated reviewer missed.**
   - The live critic failed or abstained on Q2 for 4 of 6 trials, arguing (in Korean, following the pinned Korean instruction) that the final output `leaflet`, and the web notice, are not declared in `artifacts`, so their producer, consumer and access are not recorded. The `sim-ferry` Q2 criterion text asks for exactly that.
   - The simulated author expected Q2 to be `pass` only. The candidate template (inherited in shape from the development fixture) never declares the last stage's output.
   - This is at least a debatable expectation. A real independent reviewer would have had to resolve it before sealing; after sealing it cannot be excluded (`composition.exclusions`).
   - The rehearsal's "misses" are therefore not critic errors in any reliable sense.
7. **A must_be_new violation found only by review.** A check added after sealing (`test_t077_rehearsal_sets.py`) found two template phrases shared by `sim-orchard` and `sim-ferry`: "Keep every earlier version next to the new one" and "Simulated tool contract (design only)". Because `sim-orchard` was dispatched first, `dataset.must_be_new` would bar `sim-ferry`. The spent-set digest and case-id checks cannot see this, as the design's `open` list says.

## What the pipeline could not catch (known open items)

- **Fabricated provider identity passes code checks.** The offline fake server's ids and the stub judge's ids look `provider_reported`, and the offline record says so. Only the manual two-way reconciliation with the provider's records would reveal that no such requests exist. It was **not performed** for either run.
- **Nothing is independent.** The author, reviewer and sealer are one repository-access session. Its answer table (`SimulatedCritic`) was written by the same session.

## Release-design notes N1–N5 (evidence/release-designs-t076-2026-09-25.md)

- N1–N4 are unchanged: the frozen verifier and harness are untouched.
- N5's "no T077 dispatcher exists" is now "a dispatcher exists but is **not pinned** by any design version". Until a later version pins it, it drives no release run. The design's own `open` item still stands.
- The other N5 items still stand: the operator-disk limits, reconciliation being manual only, no sealed set, no independent judge, and verdict-to-configuration binding.

## Open items

- A real T077 run still needs all of the following:
  - an independent author and reviewer, with the set held outside the repository;
  - a judge from another provider (or an attested human path, which v7 lacks) in a committed successor profile;
  - owner authority for that run;
  - a design version that pins the dispatcher;
  - the manual two-way provider reconciliation.
- The simulated sets are now spent development data, and they carry the two defects above (the Q2 artifact gap and the shared template phrases).
- The rehearsal reports and journals live on the operator's disk, under `/home/user/deeptwin-t077-rehearsal/`:

| File | sha256 |
|---|---|
| offline `report.json` | `4ddf6a42…b0e4e7` |
| live `report.json` | `0de7da95…e066d6` |
| attempt ledger | `4b564e78…7c2a246` |
