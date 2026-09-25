# T067 — US6 G-06..G-15 end to end: recovery, loop, heldout and approval cases (2026-09-25)

Status: **T067 stays open.** G-06 to G-13 and rollback are exercised end to end against the
supported app. **G-14 and G-15 are not exercised**, because the product has no surface for
them yet (see below).

**Evidence label: every fact below is synthetic and was authored by the test actor.** No
actual user, alternative, candidate, validation or approval exists. None of this is evidence
of real growth, of a real lens effect, or of an actual user's decision (growth.md §9,
"완료 증거").

## What was built

- **`app/tests/growth_chain_fixture.py`** seeds a durable US6 chain only through the
  framework functions the product uses:
  - `freeze_comparison_plan` and `persist_comparison_plan`.
  - Every round comes from `execute_paired_round` on the real scheduler. Each (side, item)
    run gets its own fresh vault. A code-owned evaluator scores the rounds, and each round is
    persisted against its stored plan.
  - The loop advances one round at a time through `advance_and_persist_loop`, with CAS
    revisions. Each round's outcome is taken from the recorded round, and the budget comes
    from the runs' own traces.
  - Candidates are frozen with `freeze_candidate`. Sealed validation runs over separately
    executed rounds on its own plan and queue (`run_validation`). Ledgers and reports are
    persisted.

  The seeded lineages use the synthetic §6.4 numbers:

  | Lineage | Rounds | Recorded end |
  | --- | --- | --- |
  | PLATEAU | 0.80 → invalid (candidate run crashed) → 0.81 → invalid (evaluator unresolved) → 0.805 → 0.81 | `plateau_reached` |
  | BELOW | 0.71 → 0.72 → 0.72, then the budget ends | `below_floor_exhausted` |
  | OLD (evaluator A) | 0.80 → 0.81, then the evaluator changes | `lineage_changed` |
  | NEW (evaluator B, new plan and lineage) | 0.82 | running |

  The seeded candidates:

  | Candidate | What it has |
  | --- | --- |
  | EARLY | The plateau's best candidate right after the early stop. Its only report is a shadow report, from its tuning round. |
  | P, R | Each passed its own sealed validation. |
  | Q | Failed heldout transfer, with a stated reason. |
  | Q′ | Q edited after Q's report was reviewed. |

- **`app/tests/fixtures/growth_server.py`** is the supported app (`create_app`, with the
  owner session and the `versions-v1` routes) over that chain.
  - `--resume --port P` restarts it over the same store and session root. It seeds
    nothing.
  - Before it serves, it checks the restart obligations: each lineage's newest loop
    revision resumes; a late duplicate of the last applied round is refused; a second
    writer advancing from the older revision collides; the growth record and round counts
    are unchanged.
- **`app/tests/browser-growth.test.mjs`** runs in real Chromium against that server.
  - The owner bootstraps, adopts the operating environment (API: the page has no adopt
    control), and works the versions page.
  - The server is then terminated and restarted over the same store.
- **`app/tests/test_growth_e2e.py`** covers, over the supported app with the same seeded
  chain, the parts the browser cannot reach.

## Per-case outcome

| Case | What was exercised | Surface | Result | Evidence label |
| --- | --- | --- | --- | --- |
| G-06 | Six PLATEAU rounds under one lineage, with the baseline environment shown. Each baseline run sits next to its paired candidate run, and the two are distinct runs from isolated vaults. The validity shown equals the recorded one. Valid rounds show their metrics and utility; invalid rounds show their reasons and no score. The crashed round keeps only its one completed pair, and its reason names only the failure class (`run failed (SchedulerError)`). The page states that no artifacts are read side by side. | browser | pass | synthetic/test-actor |
| G-07 | PLATEAU ends `plateau_reached` with the recorded explanation. Best is 0.81 from round 2: the tie at round 5 keeps the earlier one. The reference is 0.8 from round 0, and there are three valid non-improvements. BELOW ends `below_floor_exhausted`: no reference and no count. | browser | pass | synthetic/test-actor |
| G-08 | Six rounds completed and two invalid, so the count is exactly 3. Neither invalid round shows a score. The consumed budget (`isolated_runs 12, node_visits 36`) includes the invalid rounds. At the service level: a late result on a terminal loop is refused, a duplicate round id is refused, and a forked writer from an older revision collides. The resumed head is unchanged. | browser + service (`test_growth_e2e`) | pass | synthetic/test-actor |
| G-09 | The server is terminated and restarted over the same store. The restart adds no round and no loop record, so nothing is dispatched again. Every lineage resumes equal to its seeded state, including counters, best, reference and budget. A late duplicate is refused ("a round result can never apply twice"). A re-dispatched writer from the older revision collides ("already written with different content"). The experiments and rounds sections read identically, character for character, before and after, and the promotion state is identical. An approval applied before the restart is still consumed after it (409). The test signs in again if the restart ended the session. | browser + service at restart | pass | synthetic/test-actor |
| G-10 | OLD shows `lineage_changed` with count 1. NEW shows running, count 0, one round, best 0.82. NEW's group contains none of OLD's baseline runs, because the baseline was run again under the new plan. At the service level: a candidate bound to the changed evaluation policy is a different bundle, and an approval and passed report of the old bundle cannot back it (`record_promotion_decision` refuses). | browser + service | pass | synthetic/test-actor |
| G-11 | EARLY shows `passed (shadow)` with no approve control, and the page states why. An approve recorded through the route over it still cannot activate (409). The separately validated P shows approve but no apply control. An apply without any approval is refused, and the state is unchanged. | browser + API | pass | synthetic/test-actor |
| G-12 | Q shows `failed (sealed_offline)` with the heldout reason and no approve control. Q′ has no report and is not listed. After review, the ledger reclassified `sealed-q` as `tuning` (seen; there are no unseen datasets left), and the sealed-offline run of Q′ on it was refused ("an unseen pass requires unexposed sealed data"). The same refusal applies to unedited Q, and the reclassified ledger resumes from the store. | browser (listing) + service (ledger and refusal) | pass | synthetic/test-actor |
| G-13 | In the browser: the owner approves P and R, then applies R. P's apply then fails with the conflict message, and R stays current. After a reasoned rollback the adopted version is current again, and P's old approval **still fails**. That is the product bug fixed below. R's consumed approval fails too, and nothing else is promoted. At the service level: a bundle with a prompt changed after approval is refused by `record_promotion_decision`, and P's decision never activates the tampered bundle. The state is unchanged. | browser + service | pass | synthetic/test-actor |
| Rollback | Rollback without a reason is refused in the page. With a reason, it restores the adopted version, marks R as `되돌림으로 내림`, and states that already-sent or published effects are not undone. `external_effects_reverted` is false. | browser | pass | synthetic/test-actor |
| G-14 | **Not exercised: there is no product surface.** Paired execution runs code-owned handler registries in isolated vaults only. A plan's `tool_effect_policy` is a frozen reference; no replay, isolated-copy or sandbox path for past sends or publications exists. So no queue containing external effects can be re-run, honestly or otherwise. | — | not exercised | — |
| G-15 | **Not exercised: there is no product surface.** A comparison plan has no lens axis. Lens versions are only one reference inside a frozen candidate bundle, and nothing runs or records a with-lens / without-lens / mixed comparison under equal access, information, cost and evaluator conditions. | — | not exercised | — |

No case above uses actual user evidence.

## Product bug found and fixed (G-13)

`PersistentVersions.activate` checked only that the approval's expected environment was
current. Consider P and R, both approved against version A. R is applied (A→R) and then
rolled back (R→A). A is current again, and **P's old approval applied** — it had been given
over a state that no longer held.

`test_growth_e2e.py::test_g13_an_approval_given_before_the_version_changed_never_applies_later`
failed first: it got 200 where 409 was expected.

The fix is in `app/services/versions.py`. An approval is refused (conflict) when the newest
promotion revision was written after the owner decided. The owner re-reviews and approves
again, and that fresh approval applies, which the same test checks. The approval schema
stays as it is. The check fails safe: if the clock skews, the result is a refusal that asks
for a fresh approval, never an apply.

## Product surface change

The experiments line now shows the budget the loop recorded as consumed (`budgetText`,
`app/static/versions.mjs`). Before this, G-09 and G-08 budget continuity could not be seen
on the page. `versions.test.mjs` has one new test.

## Observed (2026-09-25, offline)

- `CONTROL_PYTHON=$PWD/.venv/bin/python CONTROL_PLAYWRIGHT_MODULE=/opt/node22/lib/node_modules/playwright/index.mjs node --test app/tests/browser-versions.test.mjs app/tests/browser-growth.test.mjs`
  — **9 passed**: browser-versions 1, and browser-growth 8 (G-06, 07, 08, 10, 11, 12,
  13 with rollback, and 09).
- `node --test app/tests/versions.test.mjs app/tests/experiments.test.mjs` — **9 passed**.
- `.venv/bin/python -m pytest -p no:cacheprovider` over comparisons, the growth suites
  (audit findings, chain store, e2e, firewall, loop, store), paired execution, promotion,
  promotion approvals, us6 audit findings, validation, versions api, web shell assets and
  router composition — **177 passed**. This includes the 5 new `test_growth_e2e.py` tests.

## Not claimed

- **No production growth driver.** Nothing in the supported server dispatches growth
  rounds by itself; the chain is seeded before serving.
  - "No duplicate dispatch" is therefore shown as: the restart creates no round or loop
    revision, and the store and loop refuse a late duplicate and a re-dispatched writer.
  - There is no stored dispatch reservation (growth.md §7 "dispatch 전 요청·예산 예약") and
    no `recovery_pending` state. Neither is tested.
- **Budget accounting of a crashed round.** Only the completed pair's runs are counted. The
  crashed run's partial node visits are not in `consumed`.
- **Pending rounds.** Paired execution records only valid or invalid rounds, so a
  `pending` round is not part of this chain.
- **The dataset ledger is not shown in the GUI.** For G-12, the reclassification is
  service-level evidence.
