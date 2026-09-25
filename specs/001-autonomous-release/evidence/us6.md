# T067 — US6 G-06..G-15 end to end: recovery, loop, heldout and approval cases (2026-09-25)

Status: **T067 stays open.** G-06 to G-13 and rollback are exercised end to end against the
supported app. G-14 was added on 2026-09-25 (see "G-14" below). **G-15 is not exercised**,
because the product has no surface for it yet, and it needs a qualified lens.

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
| G-14 | (Updated 2026-09-25; see the G-14 section below.) First, the owner performs a real gated send: an approved attempt, the real dispatcher and extension transport, and the test-actor tool over the worker socket. A queue then names that ToolCall by its record digest, and the owner approves the REPLAY and SINK boundaries on the versions page (an owner decision over each exact boundary, 2026-09-25). Three paired rounds then run in isolated vaults. With an approved **replay**, both sides get the recorded result, bound to the ToolCall digest, and the round is valid. With an approved **isolated sink**, both sides deliver to the sink; the candidate's changed notice is visible, and the round is valid. With an **unapproved** boundary, that item is `not comparable`, with its reason, and the round is invalid and unscored. The page shows each item's outcome and the boundary each call used. During the rounds, none of these counts moves: the tool's invocation counter, the production transport factory, the worker channel, the authenticated connection and the dispatcher factory. At the service level, these cases are also not comparable: a digest mismatch, a missing call, a missing, rejected or later-rejected owner decision, an approval of another boundary or another policy, a test-actor record in the owner-decision shape, changed inputs under replay, no bound source, an unreadable policy, and the gated production graph itself (the scheduler refuses it). | browser + service (`test_paired_tool_effects`) | pass | synthetic/test-actor |
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

## G-14 — past external effects under isolation (2026-09-25)

**Evidence label: synthetic/test-actor.** The owner is a scripted test actor. The tool is
the TEST-ACTOR `test_actor_notify` 1.0.0: it claims `external_irreversible` and performs no
external effect. It is registered only in the test processes, and the production tool table
has no external-effect tool. No model, network or paid call is made.

### What was built

- **`app/services/tool_effect_isolation.py`** enforces the plan's `tool_effect_policy`.
  - The policy is an `observation_contract` record, frozen with the plan. For each tool and
    version it names one boundary: `replay` or `isolated_sink`. Each boundary must be
    approved by the owner. (Superseded on 2026-09-25 by "G-14 approvals" below: the
    approval was first a test-actor `decision_record` embedded in the boundary; it is now
    an authenticated owner decision over the exact boundary, and a policy that embeds an
    approval is invalid.)
  - `recorded_effect_bindings(ledger, run_id)` produces a queue item's
    `past_tool_effects`: each external-effect ToolCall of the original run, with the
    sha256 of its exact ledger record.
  - Before either side runs, each binding is read again from the ledger and its digest is
    checked. The item is **not comparable**, with its stated reason, in any of these cases:
    - the digest differs (replay binding mismatch), or the call is missing;
    - the policy cannot be read, or has no boundary for the tool;
    - the boundary is missing an approval, is rejected, or carries an approval of another
      boundary;
    - replay has no settled result without artifacts to hand back.
  - During a run, the only tool capability is `IsolatedToolEffects.invoke`, which works
    only inside the isolated vault:
    - **Replay** hands back the recorded reply output. The sealed record carries the
      replayed ToolCall id and digest. The isolated call's declared inputs must equal the
      recorded call's inputs; if they differ, the item is not comparable.
    - **Isolated sink** keeps the would-be inputs in the isolated vault and returns a
      receipt that says `isolated_sink_only`.
  - A call that no boundary admits makes the item not comparable. The module does not
    import the extension transport.
- **`app/services/paired_execution.py`** changes:
  - `execute_paired_round(..., tool_effects=ToolEffectSource)` accepts the effect source.
  - `PairedSide.uses_tool_effects` controls whether a side receives the capability.
  - Isolated runs still get no attempt dispatcher, no transport, no channel and no approval
    service. The gated graph of the original environment therefore cannot be scheduled in
    isolation: the scheduler refuses it (`run failed (SchedulerError)`).
  - A not-comparable item is skipped and stated as `item i: not comparable: <reason>`, so
    the round is invalid. The other items still run.
  - `PairedRound.item_outcomes` records each item's outcome (`compared`, `not_comparable`,
    `invalid` or `failed`), with its reasons, the past effects it named, and the boundary
    each side's calls used.
- **Persistence and display.** `persist_round_outputs` stores the item outcomes when a round
  involves tool effects, and `resume_round_item_outcomes` reads them back. Output items now
  carry the queue position they ran for. `versions-v1` rounds carry `item_outcomes`.
  `experiments.mjs` lists, per item, the outcome and the boundary text: "기록 재생: ToolCall
  기록 …의 결과 · 실제 서비스로 다시 보내지 않음" for replay, or "격리 싱크 …에 보관" for the
  sink.

### Observed (2026-09-25, offline)

- **`app/tests/test_paired_tool_effects.py` — 12 passed.** Each test starts with a real
  original send: the tool-gated graph runs on the real scheduler, the owner approves the exact
  attempt, and the real extension transport calls the in-process worker over its real socket.
  After that, the tests count the tool's invocations, the worker's served exchanges,
  `ExtensionAttemptTransport.build`, `extension_channel`,
  `listener._connect_extension_authenticated` and `NodeAttemptDispatcher.build`. None of
  these counts moves in any case:
  - replay (valid; the replayed output equals the recorded output; the digests are bound);
  - digest mismatch, and a binding that names another call;
  - no approval, a rejected approval, and a foreign approval;
  - the sink, with a changed candidate send (the baseline's inputs digest equals the
    recorded call's; the candidate's differs);
  - changed inputs under replay;
  - no bound source, and an all-not-comparable queue (no round is recorded);
  - an unreadable policy;
  - the gated production graph (refused);
  - persistence of the item outcomes.

  A control test shows that the same counters do move during a real send.
- **`app/tests/browser-growth-effects.test.mjs` — 1 passed, in real Chromium** against
  `app/tests/fixtures/growth_effects_server.py`.
  - The owner saves a work item, starts the gated run, approves attempt 1 on the observe
    screen and resumes. The run completes, and the tool is called once.
  - The fixture's test-owned driver then runs three rounds over the queue [an item with no
    effects, the item with the past send]:
    - REPLAY and SINK are valid, and UNAPPROVED is invalid: "item 1: not comparable: the
      replay boundary for test_actor_notify 1.0.0 is not approved".
    - The versions page shows each item's outcome and each side's boundary text. The
      SINK baseline and candidate show different input digests.
  - The counters, installed before the original send, are nonzero after it. They are
    identical before and after the rounds, and the original run still has its one attempt.
- The following all pass: browser-growth (8), browser-tool-gate, browser-versions, the
  node experiments/versions tests (11), and the growth, paired, comparison, promotion,
  validation, versions, tool-gate and tool-binding suites (230 passed, including the 12 new
  tests).

### Not claimed

- ~~**No owner route or screen records a boundary approval.**~~ Closed on 2026-09-25; see
  "G-14 approvals" below.
- **No production growth driver exists.** The rounds are run by the test-owned driver
  after the real send.
- **The isolated sides are code-owned wiring** (intake → writer → publish). They declare
  their tool call through `IsolatedToolEffects`; they are not the original environment's
  compiled gated graph. That graph is shown to be unschedulable in isolation. It is not
  projected into an isolated variant.
- **Replay hands back only a reply output without artifacts.** A recorded result with
  output artifacts is not comparable under replay.
- **No real external service exists.** "No duplicated side effect" is shown at the
  test-actor tool, the worker connection and the transport factory, not against a live
  provider.

### G-14 approvals — a boundary is approved only by the owner (2026-09-25)

**Evidence label: synthetic/test-actor** (the owner is a scripted test actor in a real
browser session; the values are synthetic).

- **What changed.** A boundary approval is now an owner decision
  (`app/services/owner_decisions.py`, new subject kind `tool_effect_boundary`), recorded by
  `PersistentOwnerDecisions.record` from an authenticated, CSRF-verified owner request, like
  design approvals and deletions. The subject is exact
  (`tool_effect_isolation.boundary_subject`): the policy record's id, version and sha256; the
  boundary itself (tool id, version, effect class, `replay` or `isolated_sink`, sink id);
  and the boundary's digest. One record per command id: an exact replay returns the same
  decision; the same id with another decision or boundary is a `conflict`.
- **How the runner reads it.** `ToolEffectSource.build` now requires the owner-decision
  reader bound to the same store. `PersistentOwnerDecisions.decisions_over(kind, subject)`
  returns only records authored by the owner's human actor with their own `approval.decided`
  event. The latest decision decides: approve admits the boundary; reject gives "… was
  rejected by the owner"; no decision gives "… is not approved". A policy boundary that
  embeds an `approval_ref` is refused as invalid, so a test-actor `decision_record` can no
  longer approve anything. `record_boundary_approval` remains only as a thin helper over the
  same owner path: it needs `PersistentOwnerDecisions` and an authenticated owner request.
- **Owner routes** (`versions-v1`, +2 routes, pinned counts updated):
  - `GET /api/v1/versions/tool-effect-boundaries` lists every persisted comparison plan with
    its policy's boundaries and the standing state of each: `pending`, `approved`,
    `rejected` or `unreadable`. A plan whose policy cannot be read is listed with its reason.
  - `POST /api/v1/versions/tool-effect-boundaries/decisions` takes `{command_id,
    plan_record_ref, tool_id, version, boundary_sha256, decision}` and authenticates first.
    It resolves the boundary from the stored plan and policy. A digest that is not the
    stored boundary's gives 409; an unknown plan or tool gives 404.
- **Screen.** A new "도구 효과 경계" section on the versions page (`experiments.mjs`
  `renderBoundaries`, wired in `versions.mjs`) shows each tool's required boundary with what
  it means:
  - replay: 과거 호출의 기록된 결과를 그대로 돌려줍니다 (the recorded result is returned);
  - sink: 보내려던 내용을 격리된 실행의 보관소 안에만 남깁니다 (the send stays inside the
    isolated vault);
  - for both: 실제 서비스로 보내지 않습니다 (nothing goes to a real service).

  It also shows the boundary digest, the state and the decision time, with
  "경계 승인" / "경계 거절" buttons.

Observed (offline):

- `test_paired_tool_effects.py` — **16 passed**. The unapproved cases now cover six ways a
  boundary is not approved: none, rejected, approved then rejected, only another boundary
  approved, the same boundary approved in another policy, and an owner-decision-shaped
  record authored by the test actor. A new test checks the owner-only path: an embedded
  approval is invalid, and there is no path without `PersistentOwnerDecisions` or without
  an authenticated request. It also checks replay-safety, conflicts and the reader
  requirement. The counters still never move.
- `test_tool_effect_approvals_api.py` — **3 passed**. It covers list, approve, replay,
  conflicts (another decision or boundary under the same id; a wrong digest), 404s, the
  CSRF refusal, a later reject replacing an approve, per-plan isolation, and
  `ToolEffectSource` reading exactly these decisions. It also covers the unreadable-policy
  listing and exact route shapes.
- `browser-growth-effects.test.mjs` — **1 passed, real Chromium**.
  - The approval is now made on the screen. After the owner's real gated send, the driver
    persists the three plans.
  - On the versions page, the owner sees each pending boundary and its meaning. The owner
    clicks "경계 승인" for REPLAY's replay and for SINK's isolated sink. After a reload, the
    route reads back REPLAY and SINK as approved (one `action_approval` each), and UNAPPROVED
    as pending.
  - Only then does the driver run the rounds, reading approvals through the owner-decision
    reader. REPLAY and SINK are valid, and UNAPPROVED is invalid ("… is not approved").
  - All counters are unchanged from before the plans to after the rounds.
- browser-growth (8) and browser-versions (1, which now also states that there are no
  boundaries to approve) pass. The node versions/experiments tests pass: 14, including 3 new
  boundary-panel tests.
- A serial Python run of the paired, growth, comparison, promotion, versions, owner-decision,
  environments, retention, design-store/workspace, web-owner-integration, first-party,
  runs/works API, provider-startup, tool-gate-scheduler and web-shell-asset suites gave
  **388 passed**.

Still not claimed: there is no production growth driver (the rounds are still run by the
test-owned driver), and G-15 is not exercised.
