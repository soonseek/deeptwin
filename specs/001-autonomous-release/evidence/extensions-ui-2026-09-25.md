# Settings > Extensions screen (T087 extension UI / T078 inspection list), 2026-09-25

Status: **a first Settings > Extensions screen over the extension routes this server has.
It is not the complete T087 UI or the T078 list.** No task is ticked. The screen reads and
acts only through the existing fixed contributions (`extension-candidates-v1`,
`provider-installation-v1`, `provider-conformance-v1` with the transport-qualification
routes). It adds no route and changes none. Branch `extensions-ui` from `codex/ui-structure`
(contains a76a53a).

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
- **T087 routes that do not exist are not built.** These are
  `/extensions/{id}/bindings…`, rollback-retention release, qualifications, retirements, the
  extension-deployment request projection, a code-free lens/evaluator definition import,
  and any list route. Because there is no list route, the screen can reach a candidate or an
  installation only by its id or through the qualification state's run. Every T078 item
  that depends on these routes is shown as not supplied rather than invented. Examples are
  the five-field slot key and digest, slot/selector, coexistence and competition, exact
  expected-head bind/disable/rollback, immutable history, retention state and warned release.
- **T078's own acceptance work is not done.** That covers the accessibility, 360/1024/wide,
  IME and three-mode checks and `browser-accessibility.test.mjs`/`ui-review.md`. It is still
  gated on the complete T087 UI and the frozen T081 candidate.
