# Evidence — the owner's run consent: the `run-consents-v1` route contribution (T048)

- Date: 2026-09-22
- Task: the Continuation's "run creation from the intake once the consent/design line records a
  run consent and an environment" (resumption-plan; T048's open "run creation from the intake").
  Of the five records `POST /api/v1/runs` names, `work_revision` gained its producer with
  `works-v1`; `run_consent` had neither a schema nor a producer anywhere (every reference a
  consumer; every test fabricating `{"fixture": "run_consent"}`), and unlike `environment` it
  does not wait on the unrouted design line — so it is the first missing link. data-model.md §3
  ("`RunConsent` authorizes a specific execution or bounded policy … distinct grants"; the `Run`
  row's `consent_ref`); experience.md §6.3 (`업무 시작` fixes the input/environment version and this
  run's allowed actions, usage and model path; never out-of-scope external writes, automatic
  billing changes or continued promotion; "the server verifies each effect, version and scope
  independently"); runtime.md ("verify current consent … before dispatch"). The precedents are
  the owner decisions producer (`owner-decisions-design-approval.md`: one immutable record per
  command with its `approval.decided` event in the same transaction, exact replay, conflict on
  any other body) and the works route slice (`works-routes-intake-t023.md`).

## Frozen identities

```
9c17b36f7507edc5892701644ead050ef78fe46b87fee2078d214db97a6d3c1e  app/services/run_consents.py
ba12ebb16eb9586070c6501fcb541f9141c25d3d38dc9829864017aea2f8ba0b  app/api/run_consents.py
469a7a173afd24097fad1865f37439627a18c28b3c489e950a544cbae8e80676  app/api/route_contributions/run-consents-v1.json
57717f64747250ded463e16c22156db965f17d6a3ca528dcd301a49e8aa7f5c3  app/api/first_party_catalog.py
dfb868621adfc43678ee1fec68184226005974acb1d214150a4b2d9c0bcd2db9  app/api/web_boundary.py
ba699b53695a2b1d1fd0f7643af05d13fdf09036d5b939b4a81a787e6dcad2a9  app/tests/test_run_consents.py
3bdecee01ee871998dd572d4479ba82480ac2ba79b3ce0bc6b60df4067a94b7b  app/tests/test_web_owner_integration.py
11501e7c34365813e5e54d438c874d6846911b2c991ba56652268fe57678f207  app/tests/test_runs_api.py
d91b658ef85796525d51a3cafd086dbff04605366946d396ef335a72b92853ea  app/tests/test_works_api.py
2c2a365e82449deb24a78ee5f01ce696ada9492ae42dc4a57d40dc9c0532ff20  app/tests/test_first_party.py
3785a9fcc17a29c2b861e71488633a590983d01e5b142b1fe1fb0b1f17ef08c2  app/tests/test_provider_source_startup.py
```

(The `first_party_catalog.py`, `web_boundary.py`, `test_web_owner_integration.py`,
`test_runs_api.py`, `test_works_api.py`, `test_first_party.py` and
`test_provider_source_startup.py` identities frozen in earlier route slices are superseded.)

## What was built

- `app/services/run_consents.py` (new): `PersistentRunConsents(domain_store, owner_authority)`
  over the exact bound pair. `record` authenticates the owner first (POST + CSRF, re-checked
  inside the writer), validates the command (`run-consent-command-v1`: a command id and four
  exact references — `graph_ref`, `work_revision_ref`, `environment_ref`, `budget_policy_ref`,
  each a four-field `EntityRef` whose kind is the slot's), derives the consent id from the
  command (uuid5), and inside one writer transaction resolves each reference in this vault
  (the exact kind, id, version and digest, else `not_found`; a slot holding a record of another
  kind is `invalid_input`; the graph must be a `functional_graph` design), seals one immutable
  `run_consent` record (`run-consent-v1`: the command id, the four references verbatim,
  `decided_at_utc`, the bound `event_sequence`) authored by the owner's human actor, and
  appends `approval.decided` (`approved`) whose object refs are the consent and its four
  inputs and whose correlation is the command — the sequence it claimed or the transaction
  fails. Exact replay returns the same consent; the same command over any other input is a
  `conflict`; nothing is overwritten. `read` is the projection (`consent_id`, `ref`,
  `command_id`, `decided_at_utc`, the four references). Closed codes; storage detail never
  leaks.
- `app/api/run_consents.py` (new): the preflight (`POST /api/v1/run-consents`;
  `GET|HEAD …/{consent_id}`; bounded JSON — 4 096 bytes, depth 3, eight members, strings at
  256 bytes; exact reference shapes; exact methods; no query; no body on a read), the closed
  error envelope (400/401/403/404/409/413/503), the router (201 record, 200 read, HEAD with
  GET's headers) and `consent_services` (`run-consents.service`). Descriptor
  `run-consents-v1.json` (`run_consents.record` / `run_consents.read`, `browser_session`,
  `work.command` / `work.read`); catalog entry before `runs-v1` (the composition's route count
  is 39; the pins updated in five modules).
- `app/api/web_boundary.py`: the consent route classification, the body caps (4 096 for a POST,
  0 otherwise — on the `Content-Length` branch and on the streaming loop alike), the preflight
  into `state["consent_payload"]`, the error handler and the replay condition.
- `POST /api/v1/runs` accepts the sealed consent as its `consent_ref` (pinned end to end over
  the real factory with the fake executor: the run completes). The run route still resolves the
  consent by identity only; verifying that the consent names exactly the run's inputs is the
  next slice (the design line's `environment` record follows).

## Review (independent, adversarial) and closures

- **ACCEPT WITH CHANGES** (1 MUST, 4 SHOULD, 4 NIT), folded in RED-first. MUST — a read or a
  replay trusted any stored `run_consent` row: a row written by the vault's root actor under
  another command with no decided event was served as the owner's consent, and the replay
  branch never repaired it → the precedent's whole discipline on every read (`_load`: the
  owner's human actor, the identity derived from the content's command, the exact content key
  set and stamp grammar, the `approval.decided` event the row names with the command as its
  correlation) and the replay branch also requires the content's command (pinned with the
  forged row, the wrong stamp and the unbound sequence: all `unavailable`, no event). SHOULD —
  a consent could be minted over inputs the run refuses (a functional graph without its design;
  a budget policy that is not a policy binding) → the consent resolves its inputs with the run
  route's own readers (pinned RED first); the environment ⇄ graph coherence, the expiry, the
  run mode and the run route's verification recorded as deliberately deferred in the module
  docstring and below; the edges pinned (no CSRF → 403; every absent input → 404; a non-graph
  change under the same command → 409, conflict before not found; the methods and shapes off
  the two routes → 400; the exact 4 096-byte bound → 413 over it; no refusal emits an event).
  NIT — the "learns nothing about the grammar" claim reworded (the boundary's wire preflight
  runs before the session, as on every route); a dead exact-reference check dropped; a
  foreign-authored row reads as `unavailable` (the precedent's class); HEAD carries GET's
  length (deliberate, as `runs-v1`).

## Verification

- TDD: RED retained (the service module absent; the route 404 on the supported factory), GREEN
  after the service, the adapter, the descriptor, the catalog entry and the boundary wiring.
- Tests: `test_run_consents.py` **4** (one consent per command over the exact inputs with its
  decided event, replay, conflict, read/HEAD, not found; only stored records of the right kinds
  and a functional graph; the wire's exact command, bounds, query, body-on-read, anonymous;
  the sealed consent starts the run it names); the route, catalog and owner-integration
  neighbours **197** (consents 7, runs, works, approvals, owner decisions, first party, owner
  integration). Ruff: clean on the new modules; no finding introduced in the modified ones.
- Full regression on the frozen identities above: **9,348 passed, 1 failed, 2 skipped** (Linux-only),
  369 subtests, 1h23m. The one failure — `test_provider_conformance_lifecycle.py::…final_wall_deadline…`
  — is the conformance final-wall case the merged-tree reconciliation already recorded as
  timing-sensitive under the 80-minute load (the retained worker's `text-refusal-v1` attempt
  reported `protocol_error` before the final-wall jump); it touches nothing of this unit and
  passed alone three times after the run (24–35 s each). Recorded under the same disposition,
  not chased here; the eleven identities above were unchanged across the run.

## Boundaries kept

- No page, DOM or `runtime.mjs` change; no `environment`, `graph` or `budget_policy` producer;
  no run-route verification of the consent's content (next); no expiry, mode or allowed-action
  vocabulary on the consent yet (recorded open below); no model, tool or paid call.

## Open

- The consent carries no expiry and no explicit allowed-actions/model-path statement beyond the
  exact environment and budget policy it names (experience §6.3's "allowed actions, usage,
  model path" are fixed by those records); runtime.md's "verify current consent before
  dispatch" waits on the run route's verification slice.
