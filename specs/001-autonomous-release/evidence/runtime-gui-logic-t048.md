# Evidence — T048 (logic half): `app/static/runtime.mjs`, the run observation GUI logic

- Date: 2026-09-18
- Task: T048 [US3] "connect live graph/role visits/attempts/inputs/outputs … to common UI in
  `app/static/runtime.mjs` and `app/api/routes.py`; keep past attempts distinct (UX-AC04/10)" —
  the logic half over the `runs-v1` routes shipped in `runs-routes-browser-path.md`, mirroring
  the approvals logic half (`run-approvals-human-gate.md`): pure functions, no DOM wiring, no
  Playwright case (T049).

## Frozen identities

```
9d7cd49bca533a0a548f69b933b102e070e5a61d34851c767624b515d35f6b6e  app/static/runtime.mjs
6ea46f8bc0e2dd07603767744b7e2b0b3acd6486e9de001c9b13e89fc7682a3a  app/tests/runtime.test.mjs
9115b66c32311cf3560dae8434b1bf9b151bcb48bf4c3fb76e7e721d34fd4d1a  app/tests/test_runtime_gui_mirror.py
```

## What was built

- `app/static/runtime.mjs` (new, pure logic): the closed `PHASES` / `PHASE_LABELS` (Korean text
  states, never colour), `NODE_STATES` / `NODE_STATE_LABELS`, `INPUT_KINDS` and `ERROR_CODES`
  mirrored from the server; `runRoutes(basePath)` (deployment base grammar, refuses path
  injection); `runCommand` / `resumeCommand` (the closed bodies, exact four-field references of
  the pinned kinds, no `schema_version` from the client); `runView(receipt, basePath, {nodeIds})`
  — the honest view of one server receipt: the server-derived phase re-checked against the
  projection's own identities (a waiting, rejected or pending run is never complete; created ⇔
  nothing visited; running ⇔ pending), node states from `awaiting_human` / `rejected_human` /
  `pending_node_ids` / `completed_node_ids` only (both scope kinds kept per gate), one row per
  recorded visit (수행) carrying only its own result reference (a result for an unrecorded
  execution or a visit gap is refused), the sealed router activations as the "실제 전달" lines,
  the consumed approval references per gate, and an optional graph node universe that makes
  never-visited nodes visible (`미수행`); `accessibleRows(view)` — one text row per node spelling
  the state, the visits, the results, the awaiting and rejected scopes and the approval records;
  `createRunObserver({request, basePath, onChange})` — start / read / resume through the injected
  request only (reads never post), generation-ordered so a late reply never replaces a newer
  view and busy holds until every exchange returns, the closed error partition from the
  envelope code or the HTTP status, the error naming its target and clearing the view when it
  concerns another run, unchanged views never re-announced.
- `app/tests/test_runtime_gui_mirror.py` (new): pins `PHASES` (order), `PHASE_LABELS` (every
  phase, non-empty text), `INPUT_KINDS` (the create command's fields and kinds) and
  `ERROR_CODES` against `app/services/runs.py` / `app/api/runs.py`, as the records mirror does.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 8 SHOULD, 6 NIT), eleven scratch probes. Verified: no
legitimate server receipt makes `runView` throw; a waiting or pending run is never complete;
results bind only to recorded executions; nothing raw rides along. Closures, RED-first (node):

1. MUST — the observer had no ordering discipline: an overlapping read published a stale view
   and a false idle → generation-ordered exchanges, busy from the in-flight count.
2. MUST — the error partition was unreachable through the app's request helper (it throws only
   an HTTP status) and the module's comment claimed the wrong CSRF header → the partition falls
   back from the envelope code to the status; the comment states the adapter contract the DOM
   half must satisfy (`X-DeepTwin-CSRF` on POSTs; `app.mjs` still sends `X-CSRF-Token` — noted,
   not this module's caller yet).
3. SHOULD — a gate rejected on one scope and awaiting another lost its rejection → both scope
   lists per node, both spelled in the accessible row.
4. SHOULD — "attempts" conflated 수행 (visits) with 시도 (retries) and `거부됨` used the permission
   vocabulary → rows are visits with `loopIndex`; the header states where retries come from;
   `거절됨` for the owner's decision.
5. SHOULD — the positional loop index rested on an unstated server invariant → a visited node
   records every result or none (a gap is refused).
6. SHOULD — activations and consumed approvals were dropped → `routes` and per-node
   `approvalRefs` kept (identities and references only); activation targets extend the universe.
7. SHOULD — an error for another run left the previous run on screen → the error names its
   target and the view is cleared unless the failure concerns the shown run.
8. SHOULD — never-visited nodes were unrepresentable → the optional `nodeIds` universe; a
   receipt naming a node outside it is refused; without it the limit is documented.
9. SHOULD — the phase check was one-sided → the server's rule mirrored fully.
10. SHOULD — bad input threw synchronously → every exchange rejects and records the error.
11. NIT — identical polls no longer re-announce (screen readers); `onChange` validated; the
    mirror's private imports follow precedent; `시작 전` / `실행 중` name the head, not liveness
    (the DOM half pairs them with the stop events); node-level results are the aggregate, each
    visit row its own; the loop completed-and-pending case adopted as a test.

## Verification

- TDD: RED retained — `ERR_MODULE_NOT_FOUND` for the module (node) and `FileNotFoundError`
  (pytest mirror); GREEN after the module; the review's RED tests failed 9 of 13 before the
  closures; one publish-equality slip (a structurally equal view republished) caught by the test.
- Tests: `node --test app/tests/runtime.test.mjs` **13 passed** (routes, commands, honest view,
  never-complete phases, visits distinct, composition with `approvals.mjs` on a base path,
  accessible rows, the observer, the loop node, multi-scope gates with routes and approvals, the
  graph universe, overlapping exchanges, errors for another run); the other browser-logic suites
  unchanged (approvals 7, records 8, settings 4, chat 5); the Python mirror **4 passed**.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration (the node suites are
  run by hand, as for every `.mjs` slice).

## Boundaries kept

- No DOM wiring in `app.mjs` / `index.html`, no asset route for `runtime.mjs`, no Playwright case
  (T049); the shell's `api` helper is not yet a valid caller (CSRF header). No raw graph state:
  the view carries identities, references and counters only; the graph's node universe is
  caller-supplied. Retries (시도) are not in the run receipt. No model, tool or paid call.
