# Evidence — owner-recorded run approvals and scheduler human gates (T040 slice 3)

- Date: 2026-09-16
- Scope: `app/services/run_approvals.py` (new) — the first real producer
  of `action_approval` records — and `human_gate` support in
  `app/runtime/scheduler.py` (runtime.md §2 approval edges / §4
  `awaiting_human`; FR-026 authenticated human approval; the
  resumption ruling that a caller-declared boolean is never approval
  evidence).

## Why this slice

Every earlier consumer of `action_approval` (promotion, environments,
retention, knowledge, tools) referenced the record by fixture ref;
nothing in the codebase ever produced one. A human gate implemented on a
handler-returned reference would therefore have repeated the pattern the
2026-09-15 reconciliation reopened T064/T065 for. The persistent owner
session from Task 7 is the only authenticated human authority available,
so the approval writer is built on it.

## What was built

- **`PersistentRunApprovals(domain_store, owner_authority)`** — binds the
  exact `DomainStore` and `PersistentOwnerAuthority` (identity-checked,
  as the candidate registry does).
  - `record(request, payload)`: closed command
    `{schema_version: run-approval-command-v1, command_id, run_id,
    node_id, approval_scope, decision: approved|rejected}` validated
    before any work; a POST with verified CSRF, exact host and origin;
    `authenticate_bound` re-run inside the final writer (`_writer()` +
    the store's write connection). One immutable `action_approval`
    record per (run, node, scope) — identity
    `uuid5("deeptwin:run-approval:<run>:<node>:<scope>")` — with content
    `{schema_version: run-approval-v1, run_id, node_id, approval_scope,
    decision, command_id, decided_at_utc, event_sequence}`, authored by
    the owner's human actor ref (never the system root), plus the
    `approval.decided` public event (`decision` only) in the same
    transaction. Exact replay of the same command returns the same
    receipt; a different command or decision for the same key conflicts
    and never overwrites.
  - `lookup(run_id, node_id, scope)`: resolves the record through
    `domain_records` (kind, id) → exact `EntityRef` → store load, and
    returns the frozen `RunApproval` or `None`; a record whose content
    disagrees with its key is `unavailable`.
- **Scheduler `human_gate`** — gate nodes compile with a static
  `interrupt_before`; `run()` checks pending gates BEFORE every resume:
  all scopes approved → resume (the consumed refs appear in
  `outcome.approvals`); any rejection → `SchedulerError
  ("approval_rejected:<node>")` with the gate never executed; any
  absence → `outcome.awaiting_human == ((node, scope), …)` and no
  invoke. The gate body re-verifies every scope as defense in depth. A
  gated graph refuses to build without the exact
  `PersistentRunApprovals`; an ungated graph refuses one.

## Verification (TDD)

- RED: both test modules failed on the absent service, then GREEN.
- `app/tests/test_run_approvals.py` (17): durable record + event +
  human actor ref + lookup keying; exact replay vs. conflicting
  decision/command; GET/CSRF/origin/host refusals before any write;
  closed payload validation (9 shapes) before any write; a failing
  event write rolls the record back with no canary leak; exact
  store/authority binding.
- `app/tests/test_graph_execution.py` (+4, 26 total): a gate waits for
  the owner (twice) and runs after the recorded approval with the
  consumed ref reported; a rejection fails the gate without running it;
  approvals are keyed by run/node/scope (other run, other scope, other
  node do not unlock); a gated graph requires the real service.
- Focused suites (graph execution, approvals, checkpoints, web owner
  integration, candidate persistence, graph contract): **265 passed**.
- Ruff lint/format clean on the new/changed modules; diffcheck clean.
  Authoring fixes: event timestamps need the 6-digit UTC form; the
  supported server reconciles its ledger only when worker dispatch is
  configured, so the gate fixture performs that startup step itself;
  `run()` must consult approvals before resuming past a static
  interrupt.

## Frozen identities

```
52452d778f07ac9f5ed73e2edc8414456809c4bf34f83a6e068d5c8c2333cf3f  app/runtime/scheduler.py
a791de23af489cd0fa269011b9129fab8110bedd189d43f0b4fb8063e7f52084  app/services/run_approvals.py
4f6e630abfacca86d478d858a814605ab1cbb28bb6f077d582623253b95e3391  app/tests/test_run_approvals.py
1a92f3d5ba92a43e4861ee38ecc23185d3f545b68639c53a31980638745f689b  app/tests/test_graph_execution.py
```

## Limits

- No HTTP route exposes `record` yet (the API/UI wiring is a later
  slice); no `approval.requested` event is emitted when a gate starts
  waiting; consumed approvals are reported from memory, not the journal;
  promotion/environment approvals (T065) still validate their own
  `action_approval` refs and are not yet routed through this producer.

## HTTP route wiring (same day) — the browser path to approvals

- New fixed first-party contribution `run-approvals-v1` (`app/api/route_contributions/
  run-approvals-v1.json`, adapter `app/api/run_approvals.py`, catalog entry in
  `first_party_catalog.py` with scopes `approval.manage`/`approval.read`, providing
  `run-approvals.service`): `POST /api/v1/runs/{run_id}/approvals` with the closed body
  `{command_id, node_id, approval_scope, decision}` (run id taken from the path, schema
  version added server-side) and `GET|HEAD /api/v1/runs/{run_id}/approvals/{node_id}/
  {approval_scope}`. The web boundary preflights the route before persistent auth (4 KiB
  POST cap, zero-body reads, closed segment grammar, JSON only) and maps the closed error
  codes (400/401/403/404/409/413/503) with the shared sanitized error shape.
- Tests (`app/tests/test_run_approval_api.py`, 7 incl. local + HTTPS profiles): record →
  read/HEAD → exact replay → conflicting decision 409 → single `approval.decided` event →
  404 for an unrecorded scope → cold application reopen still reads the record; closed
  payloads (bad decision, path-like node id, bad command id, extra field) refuse with
  `invalid_input` before any write; unauthenticated 401, foreign origin 403, wrong CSRF,
  oversized 413, malformed run id 400; the fixed composition now carries 14 routes and the
  `runs.approvals.record`/`runs.approvals.read` route ids (pinned assertion updated in
  `test_web_owner_integration.py`).
- API suites touched by the boundary change (approval, owner integration, candidate,
  deployment prepare): **128 passed**. Ruff lint clean (web_boundary keeps its HEAD lint
  state); `ruff format` applied to the new adapter; diffcheck clean.
- Limit: no UI element calls the route yet; that is the records/experiments GUI work
  (T060/T066), and `approval.requested` is still not emitted when a gate starts waiting.

```
4b014231197fe806635e940ecec2a0fca980bff4ac0ffb380bca468367bb04a2  app/api/run_approvals.py
889154c42b407f054300b0f957a43abf509fe4ea17e7d2b3dc410d2700079300  app/api/route_contributions/run-approvals-v1.json
76c76141af87633404ed384797c51b8bdc0679d011394045c53e22b931a2b0a3  app/api/first_party_catalog.py
fa281e6b3dd29695697773051e4a308b321da364be67b076cc924a27b7a2fbe1  app/api/web_boundary.py
bee13ccd81e3109e928c21fe402efce49ac2806da8de6b794c826f3b07660131  app/tests/test_run_approval_api.py
```

## GUI logic (same day) — `app/static/approvals.mjs` (T066/UX-AC06 logic half)

- Pure browser-side logic over the fixed routes: `approvalRoutes(runId)` (canonical UUID +
  local-identifier segments, refuses path injection), `approvalCommand(...)` (the closed
  `{command_id, node_id, approval_scope, decision}` body mirrored from the service; extra
  fields refuse), `awaitingHumanView(outcome)` (narrows the scheduler projection to run id,
  completed node ids and the pending `(node, scope)` gates with their read paths — no
  counters/result refs), `receiptSummary(receipt)` (closed projection; requires an
  `action_approval` ref and the fixed read route as `links.self`), and
  `remainingGates(view, receipts)` (a gate clears only on an `approved` receipt for that
  exact run/node/scope — a foreign run or a rejection never clears it).
- `node --test app/tests/approvals.test.mjs`: **5/5** (RED first on the missing module);
  unit .mjs set (approvals, records, settings, chat, owned-fixture-lifecycle): all pass.
- Limit: no DOM wiring in `app.mjs`/`index.html` yet and no browser (Playwright) case;
  this is the logic layer the T066 experiments/versions views will call.

```
a0edd21ab9e2d57ef910b782602438aacd9f787e370b42bf7a51e1ea3bf90d59  app/static/approvals.mjs
6f842a8a87568e9b3c836821adf502d7080453b3df0c0451aaa24f8894cd7c89  app/tests/approvals.test.mjs
```

### Route slice: full-regression finding and correction

The first full run with the route contribution reported 12 failures: `test_first_party` pins the installed route count (12 → 14 base + the synthetic example), and `test_deployment_receipt_api::test_actual_five_source_ownership_survives_failures` (11 parametrized cases) takes `INSTALLED[-1]` as the deployment-prepare contribution. The catalog now lists run-approvals BEFORE deployment-prepare (core → extension-candidates → run-approvals → deployment-prepare; the approvals contribution has no dependencies, so the order is valid) and the pinned composition order plus the route count were updated; the receipt-API test itself is unchanged. Affected suites (receipt API, first party, owner integration, approval API, first-party dependencies): **177 passed**. Updated identities:

```
c4a45ef6a8bdff021760052fe655013030c8b97c036a6ac8823a93ac99264dd2  app/api/first_party_catalog.py
ebda0d3c582ef7b4e96b2f79746f18744562db33fd53f6984fd037947e464747  app/tests/test_first_party.py
eb547add23644225305d73b20f15054b08f6f8fe22a7365dcbb3d3794ebd03d5  app/tests/test_web_owner_integration.py
```

Clean full regression of the route-contribution tree (catalog reordered, no edits during the run): **5704 passed, 1 skipped, 1 warning, 369 subtests passed in 668.79s**, exit 0.

## Independent review (2026-09-17) and closures

Verdict before the fixes: spec FAIL / quality FAIL. Important: (F1) a fan-in with producers of
unequal depth ran twice — the first visit against an open input set and a phantom repeat with
its own ledger execution; (F2) a human gate inside a bounded loop passed every later visit on
one approval and then died on the resume bound; (F3) the approval reader accepted the newest
`action_approval` version by any actor, so a version-2 record authored by the system root
passed a gate; (F4) `approvals.mjs` rejected the server's real receipt links under the
default local profile base path. Minor: delimiter-prone identity (F5), no run/target binding
(F6, pre-approval possible), cap counts controller visits (F7), receipt `state` ignored and
plain objects accepted by `remainingGates` (F8), memory-only consumed approvals (F9).

Closures (RED first: 5 Python + 2 node failures, then GREEN): a fan-in runs once after every
activated producer completed — routers keep the sealed activation as a closed
`<router>.activation.<target>` counter so the fan-in distinguishes "never activated" from
"open"; routers, joins and human gates inside loop regions are refused at build; the reader
pins `version == 1` and requires the record's actor to be the persistent owner's human actor
(a forged newer version or a root-authored record is `unavailable`, and the scheduler refuses
the gate); the identity is canonical-JSON based; the GUI honours the deployment base path,
requires `state === "recorded"`, and `remainingGates` accepts only summaries it issued.
F6/F7/F9 are documented limits. Affected suites 108 passed; node 7/7; lint/format/diffcheck
clean.

```
8070782870976babbed6e982875aa3381c029ca4078e88f1580deceb1f5b7c20  app/runtime/scheduler.py
7bc143a01fa692d7ab3108902aa72f04fc7c42e8bd83607241945b119f7d8c7d  app/services/run_approvals.py
3c0e3f8e996ee290521abdc6c921da852e3eef738c894bb14035b1d85fca8616  app/static/approvals.mjs
eae1f23e3132e98fc2f5f12716d2c25a29c0a63306dd4bbfc743c33e15af95c9  app/tests/test_graph_execution.py
a498c272c65bf25d0bfb81c8ba8aa30b3d335673897cf8e7811ca9315ce73e09  app/tests/test_run_approvals.py
641c51135f485c0a49b7ca0b7fcd0199d437e38e4bc5c9985d4fcc12c454b620  app/tests/approvals.test.mjs
```

Review-closure full regression (same command): **5715 passed, 1 skipped, 1 warning, 369 subtests passed in 670.24s (0:11:10)**, exit 0.
