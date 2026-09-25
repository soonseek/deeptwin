# Settings > Extensions screen (T087 extension UI / T078 inspection list), 2026-09-25

Status: **a Settings > Extensions screen over the extension routes this server has, now
including bindings, rollback retention and the inventory lists. It is not the complete T087 UI
or the T078 list.** No task is ticked. The first slice (below, "What landed") read and acted only
through the existing contributions and added no route. The later slice the same day
(§"Bindings, rollback retention and inventory lists") adds the `extension-bindings-v1`
contribution and a candidate list route, and wires the screen to them. Branches `extensions-ui`
(first slice) and `ext-bindings` (later slice), both from `codex/ui-structure` (the later one
contains f133fb1).

## What landed

- `app/static/extensions.mjs` (`createExtensionsPanel`, `bootExtensions`) is mounted at
  `#settings-extensions` in `settings.html` and catalogued in `app/api/assets.py`. The
  settings hub has a new `extensions` entry, `확장` → `./settings.html#settings-extensions`,
  optional like every other entry. Styles are in `styles.css` (label/value grid, one column
  at ≤600px).
- **What the server supplies.** A list covers each item in T078's Settings > Extensions
  text. Each row is marked `제공됨` or `제공되지 않음`, and each row names the route that
  supplies the item or says that no route does (`SUPPLY`). Supplied: source, license,
  kind/port, qualification (installation verification, conformance run, transport
  qualification state), failure (the conformance `state` and each route's refusal code) and
  candidate-metadata import. Not supplied: binding, the five-field `BindingSlotKeyV1` and
  its digest, logical slot and capability selector, same-port coexistence and same-slot
  competition, bind/disable/rollback, immutable binding history, rollback-retention state,
  owner-only retention release, affected environments, trust tier, and deployment-request
  and staging status. Items that are not supplied are shown as `제공되지 않음(이 서버가 보내지
  않음)`. They have no control, and the screen never builds a slot key or head from labels.
- **First read.** `GET …/provider-transport-qualification` → if the state names an eligible
  run, or a sealed qualification's run, `GET …/provider-conformance/{run}`. A v2 reply
  supplies the installation head: the staged revision-1 ref and the verified revision-2 ref
  of one installation (`headFrom`).
- **Candidate (inspection + code-free import).** `GET …/candidates/{id}` is rendered with
  `candidateFacts`. The rows are: the state, `registered_unqualified`, which the screen says
  is unverified; candidate, command and registration digests; manifest and service-descriptor
  digests; extension id and version; kind; port contract version; artifact form; source (kind,
  locator shown but never fetched, provenance ref); license expression, text ref and the
  license text itself; declared compatibility; grants, secrets and filesystem needs; the
  network/resource/isolation declaration refs; service identity; image repository and index
  digest, never fetched; declared platforms; registrant and time; support documents. Trust,
  installation/qualification, binding/slot key and environments are shown as not supplied.
  Registration sends a picked JSON file of exactly `{manifest, service_descriptor, documents}`
  (plus an optional `command_id`) to `POST …/candidates`. The screen adds only a fresh
  command id. A malformed or oversize file is refused on the page without a request. An
  answer the screen could not read is resent under the same command id. A 409 is shown as a
  conflict.
- **Provider installation verification.** `GET …/provider-installation/{command_id}` is
  rendered with `installationFacts`. The screen reads only the header of a picked
  release-evidence packet: prefix, length, header JSON, and total size equal to the declared
  object sizes (`packetHeader`). It shows the staged installation ref the packet names, which
  is the expected revision-1 head. The file's exact bytes are posted with
  `application/vnd.deeptwin.provider-installation-v1`. The packet carries its own command id,
  so a resend is exact replay. No object in the packet is parsed or run in the browser.
- **Conformance.** `GET …/provider-conformance/{id}` is rendered with `conformanceFacts`
  (v1 staged or v2 verified). The fields are: state (pending, matched, mismatch or
  incomplete); vector counts; suite; context and admission digests; result ref. The failure
  cause code is shown as not supplied because the reply has none. `읽은 헤드로 적합성 검사
  실행` posts `provider-conformance-command-v2` with exactly the head last read:
  `staged_installation_ref` and `expected_verified_installation_ref` (`conformanceCommand`).
  Without a read head the button is `aria-disabled`, and clicking it only shows why. A 409 is
  shown as a conflict and the head does not change. The screen asks the owner to read again
  and never retries with another head. A 5xx or network failure is resent unchanged under the
  same command id.
- **Transport qualification.** The state is read-only here. The link
  `./records.html#records-credentials` leads to the existing qualification act.
- **Operator staging.** A handoff description: staging is the instance operator's authority
  outside the product, by signed deployment request and receipt. A receipt alone is not
  "available". No route supplies deployment-request status. The screen shows no host,
  container or command-line instruction, and a unit test and the browser test assert that
  none of those words appear.
- All server text reaches the DOM through `textContent` and attributes. The fake element in
  the unit tests throws on `innerHTML`.

## Evidence

| Case | Surface | Result | Label |
|---|---|---|---|
| Rendering and command bodies | `app/tests/extensions.test.mjs` (node, fake DOM/fetch/session) | **9/9 pass.** Covered: the supply list and which rows are not supplied; no bind/disable/rollback/release control; no host/CLI wording; the first read following the qualification state to the run and adopting its v2 head; a run refused on the page without a head; the run body equal to the head read; conflict text with the head unchanged; a new command id after a conflict; exact resend after a 503; 202 pending; candidate facts, including not-supplied fields when the reply lacks them; registration body and local refusals (bad JSON, extra field, >1 MiB); packet-header acceptance and refusals (truncated, verified-ref stage, a shell script); packet bytes sent unchanged with the media type and CSRF; installation reply rendering and head; head only from one installation's revision 1→2 refs; a non-UUID id refused before any request | synthetic |
| Real browser, real server | `app/tests/browser-extensions.test.mjs` (Chromium `chrome` channel; `app/tests/fixtures/extensions_server.py` = `create_app`, nothing seeded) | **1/1 pass.** The hub `extensions` link opens the section. The real qualification read shows `unqualified`, `verified_installation_missing` and gateway `unavailable`, plus the credentials link. The supply rows match `SUPPLY`. The binding block has 8 not-supplied rows. No binding-act buttons and no host/CLI words. The run button is `aria-disabled`; a forced click shows `noHead` and sends no POST. The synthetic candidate file (`extension_candidate_fixture.candidate_payload`) registers. The screen's facts equal the server's own GET: manifest and registration digests, `tool-port-v1`, `tool`, source, license and its text, both platforms. Trust, installation, binding and environments are marked `data-supplied=false`. A fixed-command-id file registers, and its changed twin under the same id is shown as the route's 409 conflict with the view unchanged. Candidate read by id works. A structurally valid packet (`packet_header`, synthetic bytes) naming a nonexistent staged installation: its staged id is shown, the POST body is byte-equal to the file with the vendor media type, and the real route refuses it 409, shown as a conflict. An unknown installation command id is shown as `not_found` | synthetic, test actor |

Other suites run on this branch and still passing are listed in the commit report
(test_extension_*, test_provider_installation*, test_provider_conformance*,
test_provider_transport_qualification_routes, test_web_shell_assets (the catalogue now
includes `extensions.mjs`), test_web_owner_integration, test_first_party,
test_product_wording_t023, all node unit tests, browser credentials, grants and retention).
browser-retention was updated for the new hub entry and its link target. It needs
`DEEPTWIN_AGE_RUNTIME_ROOT` and was run with the age directory present on this host.

## Bindings, rollback retention and inventory lists (2026-09-25, later)

What the domain already had: the pure `BindingSlotKeyV1` value and digest
(`app/extensions/port_contracts.py`), the closed port catalog with each port's trust tier, and the
durable candidate, installation (staged revision 1, verified revision 2), conformance-run and sealed
provider-transport-qualification records. The legacy in-memory `ExtensionRegistry`/`ExtensionBinding`
(`contracts.py`, `registry.py`) is not durable, has no slot key and no rollback retention, and is not
used here. No durable binding, retention or `ExtensionQualification` record existed.

What landed:

- **Records** (`app/domain/extension_binding.py`, validated from `domain.schemas` for these three
  content schemas only): `extension-binding-revision-v1` (record id derived from the slot key
  digest, record version = binding revision, so the slot's history is the record's versions and its
  head is the newest), `extension-rollback-retention-revision-v1` (id from slot digest + target
  binding record digest; revision 1 `retained`, revision 2 `released` or `consumed`) and
  `extension-binding-command-record-v1` (replay). All use the existing `extension_binding` domain
  kind. Stored field names avoid the `_ref` suffix for non-entity pointers because the domain store
  indexes every `*_ref` as an entity edge; the API projections use the contract names.
- **Service** (`app/extensions/binding_service.py`, `PersistentExtensionBindings`): bind (absent or
  disabled head) and supersede (active head), disable, rollback and release, each with the exact
  expected current head `{revision,binding_record_digest,state}` (`null` for an absent slot) and a
  `409 binding_head_stale` without any write when it moved. A supersession or disable creates the
  displaced active revision's `retained` head in the same transaction. A rollback names a strict
  backward ancestor and its exact retained head, re-checks that revision's qualification
  (`qualification_not_current` otherwise), consumes the retention, appends a new active revision
  (`rollback_of`) and retains the head it displaces if that was active. The release is the closed
  `ReleaseExtensionRollbackRetention` of contracts/api.md: all ten body fields, path digests equal
  to the body, a strict-ancestor target, target installation and service tuple equal to the
  retention record, exact retention head; the result is exactly the contract's twelve fields with
  the nine request fields byte-equal. It changes neither the binding head nor any installation and
  deletes no history; a released target cannot be rolled back. Bind/supersede/disable/rollback
  append `extension.binding_changed` in the same transaction. Command ids are replay-safe (same
  request: the committed result; another request, or another act, under the id: `command_conflict`).
- **Qualification.** The only durable qualification this server has is the sealed
  `provider-transport-qualification-record-v1` over a matched verified-installation conformance run.
  A bind names it by exact ref; the production resolver re-checks it as current (shipped manifest
  digest and the run's verified-installation admission unchanged) and derives the verified
  installation, its `{extension_id,revision,installation_record_digest}` and the five-field service
  tuple from the staged anchor. So only `provider-port-v1` is bindable; any other port is refused
  (`qualification_missing`, or `selector_unsupported` for its selector).
- **Slot key.** The server computes the key: `POST …/binding-slot-keys` takes the port, the
  `binding_slot_id`, the target scope without `instance_id` (the server adds its own) and the
  closed capability selector, and returns the exact key, its digest, the normalized selector and
  scope and the slot's current head. Only the provider selector family
  `{selector_kind:provider_role,provider_id,auth_mode:api,account_binding_ref}` is admitted (its
  fields are fixed by the contracts; other families' field types are not). **Slice definition:**
  `target_scope_fingerprint` is the canonical digest of
  `{schema_version:"extension-binding-target-scope-v1",instance_id,environment_id,work_id,node_id,purpose}`;
  the contracts fix the key field but not its derivation. Bind recomputes the key digest, the
  selector digest and the scope fingerprint, and requires the scope's purpose to equal the key's
  and its instance to be this one; a bind's `provider_id` must equal the qualification's provider.
- **Routes** (`extension-bindings-v1`, `app/api/extension_bindings.py`; 8 routes) plus
  `extensions.candidates.list` (`GET /api/v1/extensions/candidates?limit&after`) in
  `extension-candidates-v1`: 128 installed routes (was 119). `GET …/installations` and
  `GET …/bindings` are bounded pages (`limit` 1–50, default 20, `after` cursor, `next_after`);
  `GET …/bindings/{digest}` is the slot inspection: key, digest, logical slot, selector, scope,
  kind/trust tier, head, current extension/installation/qualification (with whether it is current),
  immutable history with backward `previous_ref`/`supersedes_ref`/`rollback_of_ref`, every
  retention head with its history and, while `retained`, the server's `release_warning` text,
  coexisting slots of the same port/scope/purpose, same-slot holders and
  `affected_environments` (`target_environment_id` from the scope; `bound_environment_versions`
  is always `[]` because no environment version records a binding revision yet, stated in
  `basis`). The installation list carries the trust tier from the port contract
  (`trust_tier_basis:"port_contract"`), service tuple, platform, the staging deployment request
  and receipt refs with the request's own read link, the linked candidate, and the slots whose
  current head names that installation. **Deviation:** contracts/api.md places bindings under
  `/extensions/{id}/…`; that segment would collide with the fixed `candidates`,
  `provider-installation`, `provider-conformance` and `provider-transport-qualification`
  segments, so the paths are `/extensions/bindings…` and the extension id travels in each body.
  Every refusal has a fixed code and the exact text the screen shows (`REFUSALS`; a pytest keeps
  the screen's `BINDING_ERRORS` equal).
- **Screen** (`app/static/extensions.mjs`): the supply list now marks binding, slot key, slot and
  selector, coexistence/competition, bind/disable/rollback, history and retention, release, affected
  environments (with its limit), trust tier and staging as supplied; `platform` (no compatibility
  judgement), `other_ports` (no qualification record) and `requests` (no list of requests that
  produced no installation) stay not supplied. New: candidate and installation lists with "next
  page", a staging-request read over the linked route, the binding-slot list, slot read and view
  (facts, history, retentions), disable, rollback per retained revision, a release that opens a
  separate confirmation showing the server's warning verbatim and the unchanged current binding,
  and a bind form whose key comes only from the server's computation and whose qualification is the
  sealed one in the transport-qualification state (without it, the bind is refused on the page with
  no request). Every act carries exactly the key and heads last read; a 409 shows the server's text
  and changes nothing on the page; an unread answer is resent with the same body.

| Case | Surface | Result | Label |
|---|---|---|---|
| Records, CAS, competition, coexistence, disable, rollback, release, replay, paging | `app/tests/test_extension_bindings.py` (real `create_app`, owner cookie/CSRF; the resolver is a test resolver over real `validation_report` records and test-validator installation records) | **7/7 pass.** Wire refusals (query, body, CSRF, duplicate keys, bad digests); server-computed key equals the recomputed five-field key; four-field key, mismatched digest, other-instance scope, other extension, other provider refused; stale head refused with no write; a second candidate with the absent head refused and the first unchanged; sibling slot coexists; supersede retains A; disable retains B; rollback refused for a non-current qualification, a stale head and a non-ancestor target, then consumes A's retention; consumed retention refused; release refused for tuple mismatch, stale head, blank reason, path/body mismatch, cross-slot and current targets; release result has exactly the contract fields and changes only the retention; replay equal, changed body `command_conflict`, repeat refused, released target cannot roll back; `extension.binding_changed` metadata per revision; binding/installation/candidate list paging; the domain validator refuses inexact content; the screen's texts equal `REFUSALS` | synthetic, test actor |
| Real qualified provider path | `app/tests/test_extension_bindings_qualified.py` (`installation_case`: verified installation through the app, 4/4 matched run through the framed worker, transport qualification sealed through its route; production resolver) | **1/1 pass.** Staged then verified installation listed with trust tier and staging refs; bind over the sealed qualification; a non-qualification ref and another extension id refused; slot shows the verified installation, qualification current, service tuple; `binding_unchanged`; disable → rollback (qualification re-checked current) → disable → release of the retained revision with the real service tuple; history read back unchanged after a cold reopen without the release source | synthetic release tree, test actor |
| Screen | `app/tests/extensions.test.mjs` (node, fake DOM/fetch) | **14/14 pass** (5 new): inventory paging and facts, staging-request read over the server's link, slot facts as sent, disable body/stale head/new id/exact resend, server key and bind body, bind refused here without a sealed qualification, rollback body, release only from its confirmation with the warning verbatim and the contract's ten body fields | synthetic |
| Real browser | `app/tests/browser-extensions.test.mjs` | **2/2 pass.** Case 1 (nothing seeded) now also checks the empty real lists, the real slot-key computation, the bind refused on the page with no POST, an unknown slot's `not_found` text, and the registered candidate's trust tier from the real list. Case 2 (`extensions_server.py --synthetic-bindings`: synthetic installations and the test resolver; real binding routes/records/CAS): set-up binds A, supersedes with B, binds a sibling slot; the screen's key/digest/selector equal the server's GET; coexistence, holders and retention shown; a competing disable after the read makes the page's rollback a 409 `binding_head_stale` with the server text and no change; after a re-read the rollback succeeds (revision 4, A's retention consumed); the release confirmation shows the server's warning, the POST has exactly the ten contract fields, the retention becomes `released` while head and four history rows are unchanged; disable to revision 5; the staging-request read goes to the real deployment route, which refuses the synthetic stand-in, shown with its code's text | synthetic, test actor |

Also run on this branch, one file per process: every `test_extension_*.py`,
`test_provider_installation*.py`, `test_provider_conformance*.py`,
`test_provider_transport_qualification_routes.py`, `test_web_owner_integration.py`,
`test_first_party.py`, `test_web_shell_assets.py`, `test_deployment_prepare.py`, the domain schema
tests and the route-count pins (`test_runs_api.py`, `test_works_api.py`,
`test_provider_source_startup.py`), plus `test_deployment_receipt_api.py`,
`test_provider_receipt_service.py`, `test_router_composition.py` and
`test_product_wording_t023.py`: 49 files, 1,737 passed, 0 failed (3 skipped, pre-existing). All
37 node unit test files pass (298 tests). Browser: `browser-extensions.test.mjs` 2/2.

Consequences to know: a binding record is an `extension_binding` domain record, so the existing
deployment first-only guards (which refuse a new stage prepare while any `extension_qualification`
or `extension_binding` record exists) now refuse a further provider stage after the first bind.
That is the existing conservative guard (no replace/retire path exists), not a new rule. The
synthetic installation records of the browser fixture's binding mode are outside the deployment
journal, so that fixture cannot be restarted and its deployment reads refuse; the cold-reopen
proof is the qualified pytest case.

## Not done / not driven

- **No verified-installation path in a browser.** The standalone server cannot compose a
  staged installation, so it cannot compose a verified installation, a matched or mismatched
  verified-installation conformance run, or a transport qualification either. Those need
  `installation_case`'s pytest-owned release tree, monkeypatched publication/source fixtures
  and the retained framed conformance worker. As a result, the browser drives neither a
  successful `provider-installation` execute, nor `runConformance` against a real head, nor
  the matched/mismatch/incomplete displays. The browser test sees them only as refusals.
  They are unit-tested with reply shapes that follow `parse_installation_reply` and
  `parse_reply`.
- **T087 routes and records still missing** (after the later slice): durable
  `ExtensionQualification` records (five checks, expiry, qualification-context heads) for any port,
  so only the provider port is bindable; selector families other than the provider's; the
  contract's distinct binding/retention event names (`extension.rollback_retention_*`,
  superseded/disabled/rolled_back are not registered event types; bind/disable/rollback emit
  `extension.binding_changed`, a release emits no event); environment versions that bind binding
  revisions; startup reconciliation of expiry and revoked grants and the dispatch path reading these
  binding heads (the provider semantic context still takes its binding records as injected
  authority); retirements, current uninstall, replace and the extension-deployment request
  projection; qualifications as a route; a list of deployment requests that produced no
  installation; a code-free lens/evaluator definition import. The screen marks the items that
  depend on them as not supplied.
- **T078's own acceptance work is not done.** That covers the accessibility, 360/1024/wide,
  IME and three-mode checks and `browser-accessibility.test.mjs`/`ui-review.md`. It is still
  gated on the complete T087 UI and the frozen T081 candidate.
