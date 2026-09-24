# Evidence — T033/T034: isolated Q01 harness and independent critic verifier

- Date: 2026-09-24
- Status: **partial, offline only.** Harness, frozen environment, readiness check and
  verifier landed with offline tests. T033 and T034 stay open (reasons below); T035
  (calibration/qualification/live RunPlan) was not started. No live trial ran, no
  provider or model was contacted, and no environment variable holding a key was read.

## What landed

### T033 — harness and environment (`evals/deeptwin/harness/`, `evals/deeptwin/tasks/v01-q01/`)

- `tasks/v01-q01/task.toml` — a plain project-owned description (schema
  `deeptwin-q01-task-1`); explicitly **not** a Harbor task (Harbor is not installed or adopted).
- `tasks/v01-q01/instruction.md` — the exact agent instruction from Task.md "Agent input"
  (review and proposal) and the validity/response judgement instructions from its call
  table, one section per stage. A test compares every section byte for byte with Task.md;
  the harness pins its SHA-256 and refuses an unreviewed instruction.
- `tasks/v01-q01/environment/` — `manifest.json` plus ten frozen case files, one per row
  of the Task.md development boundary table (the Q8 row is a harness/verifier fault
  condition, exercised by tests, not a case). Cases are built from `q01_materials.py`
  (`q01_source` / `q01_counterexample`), carry no label, expected status or kind name, and
  are named by a stable hash of (candidate id, counterexample id), sorted by that hash.
- `harness/q01_cases.py` — materialization and regeneration of the frozen files.
- `harness/q01_harness.py`:
  - `TaskReader` — the only agent-material read path: an allowlist of `instruction.md`,
    `environment/manifest.json` and the listed case files with matching hashes; Task.md,
    task.toml, verifier, tests, World Skill, absolute paths, traversal and symlinks are
    refused; every read or refusal is logged into the trial record.
  - Stage driving reuses the reviewed product path: `critic_contract.prepare_input` for the
    visible projection, `design_criticism_live.render_criticism_prompt` for the product
    `(system, user)` pair (the stage section of `instruction.md` is appended to the system
    prompt; the user payload is the prepared prompt byte for byte), and
    `critic_trial.OfflineRunner` + `critic_audit.Ledger` for freezing, journaling,
    dispatch, timeout, cancellation and output classification. The caller transport is a
    plain `(system, user) -> str`, wrapped in an `OfflineTransport` adapter.
  - Order per trial: review → proposal (lineage: review) → authored boundary
    counterexample validity → response → each model-proposed counterexample validity →
    response (request lineage with exact hashes; cap `max_proposed_chains`, default 16).
  - Per-call input manifest: system/user/schema/instruction SHA-256, the prepared contract
    manifest (document hashes), visible input keys, lineage kind/parent/hash, case file
    hash, byte counts and the model-identity note.
  - Fresh state per trial: a new trial directory (`exist_ok=False`), ledger, run id and
    runtime tree; a trial object runs once.
  - Every agent input is scanned before dispatch for control-plane fragments (Task.md,
    task.toml, World Skill, verifier and test sources) and all case ids; the allowed
    corpus comes only from trusted sources (pinned instruction, product profiles, a fresh
    materialization), so an altered case file cannot whitelist itself. A hit makes the
    trial `invalid` / `isolation_boundary` with no call dispatched.
  - Outcomes, per Task.md: all valid → `completed`, `output_contract: valid`; a
    contract-violating model output → `completed`, `output_contract: model_output_invalid`
    (the trial stops there); transport/fixture error or non-text → `invalid` with the
    runner's general cause; cancel/timeout/interrupt, reservation, audit, freeze/selection,
    input-contract or environment refusals → `invalid` with a general cause. The harness
    never scores: `semantic: not_checked`, `score: null` always.
  - `readiness()` uses the same `TaskReader`: environment readable with matching hashes,
    frozen cases equal to a fresh materialization, no label keys, control-plane probes
    refused, environment material and every pre-model stage input (review, proposal,
    authored validity) free of control-plane content, visible inputs allowlisted per purpose.
- `app/critic_audit.py` — a narrow extension of the T032 journal:
  `register_authored_evidence(run_id, candidate…, item, source)` plus an authored branch
  of `reserve_with_lineage` (validity only, `parent_request_id=None`, hash registered for
  the same run and candidate). Authored boundary counterexamples are therefore never
  registered as proposal output (B plan §5.3); forged hash, other run, other candidate and
  other purposes refuse. Existing lineage behaviour is unchanged.

### T034 — verifier (`evals/deeptwin/verifiers/critic.py`)

- Six boundary outcome classes (interpretation recorded under "Decisions"):
  `accept_without_false_rejection`, `required_defect`, `rejected_counterexample`,
  `valid_counterexample`, `unresolved_specific_claim`, `insufficient_evidence`.
- Expectations keyed by (candidate id, counterexample id) and derived by the implementer
  from the materials, each with a written basis; a test re-checks those source facts
  directly. The verifier does not import the harness or any generator conclusion.
- Judgement order: (1) trial validity — harness state, durable ledger present and equal
  to the record, every journal call and authored item covered by the record, prompt /
  schema / manifest re-derived with `prepare_input`, system prompt hash re-rendered, raw
  hash/bytes and parser output re-derived with `parse_response`, lineage hashes, frozen
  materials equal to `q01_materials`, access log and answer-marker leakage; (2) output
  contract; (3) rule checks: allowed finding statuses per criterion, validity/response
  statuses and required cited source/candidate locations; (4) semantic items only via
  the explicit `SemanticJudge` interface.
- Verdicts: `pass` (1.0) / `fail` (0.0) only; `not_judged` (no judge or `undetermined`)
  and `invalid` (any evidence, isolation, judge or verifier fault) have `score: null` and
  `agent_capability_scored: false`. No live judge is implemented; a deterministic
  `FixtureJudge` exists only in the test file for synthetic fixtures.
- `verify_suite` requires all ten cases; any invalid → invalid, any fail → fail, any
  not_judged → not_judged.

## Observed tests (2026-09-24, this worktree)

```
.venv/bin/python -m pytest -p no:cacheprovider -q evals/deeptwin/tests
81 passed   (test_q01_harness.py 44, test_critic_verifier.py 37)

.venv/bin/python -m pytest -p no:cacheprovider -q app/tests/test_critic*.py app/tests/test_design*.py \
    app/tests/test_lens*.py evals/deeptwin/tests -k "not test_claude_live_"
570 passed, 1 warning   (489 existing + 81 new; baseline before the change: 489 passed)
```

The full `app/tests` suite was not run to completion in this session (stopped at ~22%
with no failure for time); only the focused suites above are claimed.

Covered offline: materialization/drift, label-free cases, exact instruction, readiness
and its failure on tampered/drifted/leaking material, reader refusals (incl. symlink),
four-stage driving over the product render with hash manifests, no control-plane text or
case id in any agent input for every case, fresh state, proposed-chain lineage and cap,
responses under rejected/unresolved validity, contract-invalid output, transport error,
non-text output, cancellation, timeout, unknown case, changed selection, pre-dispatch
leak blocking, authored-lineage refusals; verifier PASS/NOT_JUDGED/FAIL/INVALID for every
boundary class, judge faults, degenerate critics (reject-all, fail-all), injected
instructions in output, evidence loss/tampering/suppression, altered materials and
answer leaks.

## Decisions the spec left open

- **Six classes.** Task.md and T034 do not enumerate them; they are read from the
  distinct expected boundaries of the Task.md development table (Q1–Q3 defect, Q4
  alternative, Q5 rejected / valid / unresolved, Q6 insufficient). The Q8 row is not a
  class: it is the trial-validity layer (`invalid`, no score).
- **Response stage for every validity status.** The product driver skips the response
  after a non-valid validity; the Q01 harness drives it, because the Task.md boundary
  judges the response under rejected and unresolved validity (the contract then forces
  `unresolved`, and a `fail` becomes `model_output_invalid`).
- **Proposal instruction** is the common review instruction (Task.md gives none separately).
- **Stop on first contract-invalid output**; later stages are not spent.
- **Model identity** is declared by the harness from the frozen selection
  (`selection_declared_not_transport_reported`), because a `(system, user) -> str`
  transport reports none.
- **Allowed statuses on non-targeted criteria**: accept cases require Q1–Q4 `pass` and
  forbid `fail` on Q5–Q8; defect cases leave criteria they do not target unconstrained
  except where the material shows the property intact (e.g. c86 Q2/Q3, c53 Q1/Q2).
- **c18 Q1 must be `unresolved`**, following Task.md, even though the candidate's
  "keep source certainty" rule could be argued to pass.
- **Leak scan fails closed**: a model output that happens to quote ≥24 characters of
  control-plane prose into a later stage input invalidates the trial (no score).

## Honest limits

- No live trial, no scored semantic run, no provider contact; the pass paths are shown
  only with synthetic scripted outputs and the offline fixture judge.
- No semantic judge (human or model) is implemented, configured or qualified; every real
  trial currently ends `not_judged` at best.
- Isolation is accidental-use prevention (allowlisted reads, hash checks, text scans), not
  an OS/container sandbox; hashes detect corruption, not an adversary who rewrites raw,
  hash and parsed output consistently.
- The eval-engineering implementation/environment references named by T033 are not in
  this checkout; Harbor is neither installed nor adopted (B plan §5.2 boxes stay open).
- Expected boundaries were derived by the same implementer who wrote the harness; an
  independent human review of `EXPECTED` is still required. These are development cases
  seen by the developer and can never be release heldout.
- T035 (calibration, qualification, IndependenceProfile, bounded live RunPlan) not done.
