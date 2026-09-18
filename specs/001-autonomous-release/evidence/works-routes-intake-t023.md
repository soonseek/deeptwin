# Evidence — the intake's server surface: the `works-v1` route contribution (T023/T025)

- Date: 2026-09-18
- Task: the Continuation's "the intake screen on the supported factory (T023/T025, §5.1.4)" —
  the route half. The preview's `/api/works` routes and the conversation routes answer 404 on the
  supported factory (probed), so the first work screen had no server-side draft there. api.md
  Intake row (`/works`, `/{id}`, `/revisions/{revision}`: create/edit); data-model.md
  `WorkRevision` (concurrent edits use `expected_revision`); experience.md §5.1 items 4–6 (the
  first work screen; drafts preserved) and §5.2 (the user's sentence is never overwritten). The
  precedent is the runs route slice (`runs-routes-browser-path.md`): the route lands before the
  DOM. The page itself is the next slice.

## Frozen identities

```
b331711ad04da5b1e4bfbcdd598b919b7f84c9e78764b78108e945564c6bc1bf  app/services/works.py
e52dab50df2fc5b66a24b7a5a6c1b942cb353a6b5386207f7e4d9c8ebc170a8c  app/api/works.py
11c23ecbe842a1e95b25a11d3cd9db9381f77dbec4c95602abcb0e4b5a3319e6  app/api/route_contributions/works-v1.json
b43dda22cf51df63f53137add3163bedb5fbe62c05578270414a0aa621bc7f6b  app/api/first_party_catalog.py
430e6581358a04f32e380afd438322b8951677eb749e8919d805b7839b17a834  app/api/web_boundary.py
cde3585de58a040271c4e9aaab80aa408631b139decee28341c6c5c94474bdd4  app/tests/test_works_api.py
ed3949268db4a7dea9e2933a0be906f4fdadf49a0a751b8fc63b73d93bc91580  app/tests/test_web_owner_integration.py
89a264e0f8299c345c7440754c2243a23bb4e4842e1d2c83653fd5b301996e76  app/tests/test_runs_api.py
377e1cc64b351fb8b37898538d9eff54e1bc3f3358937ef5f5f078b9b7b192d1  app/tests/test_first_party.py
```

(The `first_party_catalog.py`, `web_boundary.py`, `test_web_owner_integration.py`,
`test_runs_api.py` and `test_first_party.py` identities frozen in earlier route slices are
superseded.)

## What was built

- `app/services/works.py` (new): `PersistentWorks(domain_store, owner_authority)`. `create`
  authenticates the owner (POST + CSRF, re-checked inside the writer), validates the command
  (`work-create-command-v1`: a command id and the owner's text — one to 20 000 characters, at
  most 65 536 UTF-8 bytes, the record's own string bound), derives the work id from the command
  (uuid5) and seals version 1 as an immutable `work_revision` record (`work-revision-v1`:
  work id, revision, command id, text, empty `source_refs`, `input_origin = owner_text`).
  `revise` (`work-revise-command-v1`: command id, `expected_revision`, text) seals the next
  version with the previous revision as its parent, only when the latest revision is the
  expected one. A command names exactly one revision across every work: a replay returns the
  revision it sealed; the same command with different text, or naming another work or
  revision, is a conflict; a stale expectation is a conflict. `read` is the latest revision's
  projection (`work_id`, `revision`, `text`, `ref`, `created_at_utc`). Closed codes; storage
  detail never leaks.
- `app/api/works.py` (new): the preflight (`POST /api/v1/works`; `GET|HEAD /api/v1/works/{id}`;
  `POST …/{id}/revisions`; bounded JSON — 67 456 bytes, depth 2, four members, strings at the
  record's 64 KiB; exact methods; no query; no body on a read), the closed error envelope, the
  router (201 create/revise, 200 read, HEAD with GET's headers) and `work_services`. Descriptor
  `works-v1.json` (`works.create` / `works.read` / `works.revise`, `browser_session`,
  `work.command` / `work.read`); catalog entry before `runs-v1` (the composition's route count
  is 23; the pins updated).
- `app/api/web_boundary.py`: the work route classification, the body caps (the text bound plus
  the command's members for a POST, 0 otherwise — on the `Content-Length` branch and on the
  streaming loop alike), the preflight into `state["work_payload"]`, the error handler and the
  replay condition.
- The run creation route resolves a revision the works route sealed as the run's own
  `work_revision_ref` (pinned end to end over the real factory).

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 3 SHOULD, NITs); probes over the real factory. Verified
clean: no session → 401; a POST without CSRF, a foreign origin or a cross-site fetch refused; a
query on any method, a wrong content type, a trailing slash, an extra segment, a non-UUID or
nil id, a wrong method → the closed envelope; HEAD equals GET with the body blanked, `no-store`;
`read` has no service-level auth exactly as `runs.read` (the boundary authenticates every
non-public path); the composition order and pins; the deployment-prepare fixture unaffected;
eight concurrent creates of one command → eight identical 201s and one record; eight concurrent
revisions under one expectation → one 201, seven 409s, two records. Closures, RED-first:

1. MUST — the text bound was the character bound alone (up to 80 000 bytes at the wire), but
   the domain record's canonical string cap is 65 536 bytes: a text under the character bound
   and over it was refused as a 503 outage after the transaction rolled back → the wire and the
   service refuse it as invalid input; pinned at the boundary (16 384 four-byte characters
   admitted, 16 385 refused). The comment claiming the intake store's bound corrected.
2. MUST — a body without `Content-Length` (chunked) met the boundary's streaming cap without a
   work branch and answered a bare code → parity with the runs precedent; pinned (a chunked
   oversize POST → `too_large` in the full envelope; a chunked read with a body → invalid).
3. SHOULD — command ids were unique only per work and version (a creating command reused to
   revise another work, or a revising command reused as a create, was admitted) → a command
   names exactly one revision across every work, found by a scan of the revisions' canonical
   bodies (the key is exact in them — every quote inside a string is escaped — and every match
   is read back and checked; no index, linear in the vault's revisions; stated); pinned,
   including a text that spells another command's key.
4. SHOULD — the data-model deviation was undocumented → stated in the module: the text is
   inline under the record's 64 KiB bound (no `input_text_ref`), no `interpretation_edits`, no
   mutable `Work` head (the latest revision is read by version).
5. SHOULD — the byte cap is raw UTF-8 (an escaped-form client reaches it sooner) → stated at
   the constant.
6. NIT — `expected_revision` as a bool, a float, zero, a negative or a string pinned as
   invalid; the concurrency cases pinned. 7. NIT (recorded) — a NUL or whitespace-only text is
   admitted, as the legacy intake store admits it. 8. NIT (recorded, pre-existing) — the
   boundary's session envelope omits `correlation_id`.

## Verification

- TDD: RED retained — the routes answered 404 on the supported factory; GREEN after the service,
  the adapter, the descriptor, the catalog entry and the boundary wiring (13 tests on the first
  run); the review's RED tests failed for their stated reasons (the 503 outage; the bare code on
  a chunked body; the cross-work reuse admitted).
- Tests: `test_works_api.py` **23**; covering (works, owner integration, runs API, first party,
  approvals, shell assets, router composition, deployment receipt) **242**. Ruff: clean on the
  changed files.
- Full regression: **6333 passed, 2 skipped** (Linux-only), 369 subtests, 16m50s.

## Boundaries kept

- No page yet (the intake screen is the next slice); no source, file, event, understanding
  request or run creation from the intake; no `Work` head record; no model, tool or paid call.
