# DeepTwin resumption integration work steps

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> for task execution and independent task-scoped review. This is a work-step breakdown of
> the existing canonical plan, not a replacement roadmap or a reduced release scope.

**Goal:** Restore finite verification and remove concrete integration defects before connecting
the actual browser/design/runtime journey.

**Architecture:** Preserve the current worktree, immutable domain/ledger authority and provider
boundaries. Fix observable failures with RED/GREEN tests; never count a value constructor as
real provider, worker, evaluation or human execution.

**Tech Stack:** Existing Python 3.12, pytest, Node test runner, Playwright and LangGraph.

**Spec:** `specs/001-autonomous-release/spec.md`; exact task authority remains `tasks.md`.

## Global Constraints

- Claude API-only; Codex subscription and explicitly selected optional API remain required.
- No new paid/live model calls, credential discovery/export, real microphone input or public push.
- Use synthetic audio, local controlled HTTP/worker fixtures and temporary test stores.
- Do not modify or terminate unrelated user processes or the old Claude session.
- The supported product is the browser UI; development commands are not end-user instructions.
- Preserve the existing branch and main-checkout untracked files. No automatic commits or push;
  review the current diff plus newly created files, not an empty HEAD-to-HEAD comparison.
- Keep T024/T042 and downstream whole-story tasks open unless all their original acceptance is met.
- Missing authority/actual evidence must remain explicit; no automatic billing/model fallback.

### Task 1: Preserve provider-advertised model effort through the frozen turn (T022/T042)

**Files:** Modify `app/runtime/gateway.py`; test in
`app/tests/test_model_payloads.py` and new `app/tests/test_gateway_catalog_integration.py`.
Do not edit other production modules unless a concrete existing interface defect is demonstrated.

**Interfaces:** Consume the current real `ModelCatalog.validate_choice(choice)` result;
`freeze_turn(value) -> FrozenTurn` remains a structural value builder, not a credential,
catalog-currentness or execution authorization issuer. `effort` is a provider-advertised bounded
string or `None` (no explicit override). Preserve the exact value, never coerce it to medium.
The existing catalog service continues to reject unsupported/removed choices and stale bindings.

- [x] Add RED tests for dynamic advertised values (`xhigh`, `max`, a future fixture ID), `None`,
  legacy low/medium/high, wrong types and bounds. The provider identifiers are synthetic fixtures,
  not claims about a public model catalog. Example behavior:

  ```python
  @pytest.mark.parametrize('effort', ['xhigh', 'max', 'fixture-next', None])
  def test_frozen_turn_preserves_explicit_provider_effort(effort):
      assert freeze_turn(turn_value(effort=effort)).effort == effort
  ```

- [x] Add real local Store/ModelCatalog integration tests using the controlled Codex catalog
  fixture: advertise an extra effort, explicitly refresh, validate the exact choice, then freeze
  its returned effort. No network is involved. Unsupported efforts, model removal, binding change
  and explicit `None` must retain the catalog's existing behavior. Invalid shape tests include
  `True`, integers, dict/list, empty string and strings longer than the catalog's 80-character bound.
- [x] Run the new tests and record the relevant pre-fix failure. Preserve existing payload and
  US3 authority tests; do not loosen their grants/path/provenance assertions.
- [x] Replace the stale fixed effort enum check with the catalog-compatible nullable bounded
  string grammar and update `FrozenTurn.effort` annotation/documentation. Remove the unused
  internal enum only after checking callsites. Do not widen provider modes or tool authority.
- [x] Run `python -B -m pytest app/tests/test_model_payloads.py
  app/tests/test_gateway_catalog_integration.py app/tests/test_model_catalog.py
  app/tests/test_model_selection.py app/tests/test_us3_audit_findings.py -q -p no:cacheprovider`.
  Record exact results and limitations, then obtain independent spec/quality review.

Task-scoped result: RED 9 failed / 22 passed; GREEN 31 passed; final focused gateway/catalog/
selection/authority suite 77 passed. Independent reviewer: spec PASS, quality PASS, no findings,
31 tests independently passed. This is not a live provider or whole T042 completion claim.

### Task 2: End browser speech fixture cleanup within a finite deadline (T024 verification)

**Files:** `app/tests/browser-speech-input.test.mjs`, `app/tests/fixtures/speech_server.py`,
and a focused test helper/test if needed under `app/tests/helpers/` / `app/tests/`.
Production SSE code may change only if the diagnosis demonstrates its own shutdown defect.

**Interfaces:** The Node fixture owns the exact spawned child and browser. Cleanup must close
browser resources before waiting for graceful fixture exit; startup and teardown have finite
deadlines, bounded diagnostics, and clean listeners/timers. Termination may target only the
newly spawned child object, not a global PID search or another provider/browser session.

- [x] Diagnose the observed hang before changing behavior. The old process has no established
  HTTP connection, this UI opens no SSE stream, and the finite SSE response is not a streaming
  response. An SSE-caused shutdown deadlock is therefore not established. The first four cases
  passed on the original Node runtime and all 18 passed on a bounded Node 24 rerun; the exact
  intermittent stall remains unresolved. Correct the demonstrated unbounded lifecycle waits,
  not a conjectural production SSE problem.
- [x] Write failing lifecycle regressions with real temporary child processes: a child that
  deliberately ignores SIGTERM must be terminated within finite grace/force-stop bounds; an
  already-exited child (including signal exit) must not wait for a past exit event; startup
  failure must settle and release resources. Assert no surviving owned child. These tests use
  no microphone permission, SSE assumption or live models, and must fail against the original
  unbounded cleanup behavior.
- [x] Add minimal test-harness lifecycle protection, close browser/client resources before server
  termination, and bound owned-child teardown and individual browser cases. Preserve actual
  assertion failures and make forced cleanup visible; do not hide failures through skips or
  retries. Do not change production server code without an independently reproduced defect.
- [x] Run focused lifecycle tests and the speech browser suite with the existing installed
  Playwright module and project Python. Use a finite outer timeout for the newly spawned suite.
  Run the broader browser suite once the focused suite passes, capturing explicit terminal totals.
- [x] Record the exact failure/pass output and independent task review. Synthetic capture and
  controlled recognition do not qualify production STT or the full T024 contract.

Task-scoped results: exact old cleanup logic timed out in both bounded counterfactual cases;
new lifecycle regressions 4/4 and synthetic speech browser cases 18/18 passed. A true external
owner observed exit 0 in 78.576 seconds under a 180-second wall-clock deadline; Node's
`--test-timeout` itself is only a test timeout, not a process-termination guarantee. Independent
review: spec PASS / quality PASS, with disclosed browser-close timeout limitation (waiting is
bounded, but this Browser API does not prove browser-process termination after a close timeout).
The parent completed the broader eight-file browser/lifecycle regression: 81 passed, no failures,
cancelled or skipped cases, exit 0 in 257.056 seconds under a separate owned process group and
600-second outer timeout. Neither this nor the successful speech run proves cleanup of arbitrary
detached browser descendants on an unobserved timeout path.

### Task 3: Persist actual LangGraph checkpoint and pending-write recovery in the runtime ledger (T040 partial)

**Files:** New `app/runtime/checkpoints.py` and `app/tests/test_langgraph_checkpoints.py`.
Do not edit ledger schema, worker dispatch, production UI or extension ports for this task.

**Interfaces:** `LedgerCheckpointSaver` implements the installed synchronous
`BaseCheckpointSaver` contract (`get_tuple`, `put`, `put_writes`, bounded `list`). Bind one exact
`RuntimeLedger`, existing run ID, graph digest and compilation-authority digest. Freeze the run's
environment/manifest refs into the adapter journal binding. These are identity checks, not a new
source of graph approval or execution authority. A fixed `langgraph-v1` runtime-checkpoint
namespace is the sole durable journal; an in-memory reconstructed index is disposable. Each
checkpoint/pending-write batch is one versioned cursor record committed through existing ledger
CAS. No second SQLite database, duplicate acknowledgment truth or full-history copy per record.

- [x] Add failing tests using a real installed `StateGraph`, genuine temporary Store/DomainStore/
  RuntimeLedger and refs/counters-only local deterministic nodes. Verify sequential node IDs and
  output refs, close/reopen and resume, and a parallel-step failure where a completed sibling's
  pending writes survive restart without rerunning that sibling. This tests saver recovery, not
  production workers, model quality or full scheduler readiness.
- [x] Implement exact checkpoint IDs/parents/channel values+versions/metadata and pending-write
  semantics. Preserve installed `WRITES_IDX_MAP` reserved negative indexes and normal write-index
  identity; identical normal duplicates are idempotent and conflicting values fail. Do not turn
  `put_writes` into a no-op or restore only the latest state. Lock local mutations; foreign-writer
  CAS conflicts halt the instance, not silently reload/overwrite another head.
- [x] Keep serialization bounded and non-executable: no pickle fallback or arbitrary object
  reconstruction. Use a closed safe JSON/control-record grammar for this initial ordinary-channel
  profile; reject unsupported object/channel/subgraph/async features explicitly. Application
  channels contain exact EntityRefs and bounded counters only; no text, credentials, clients,
  callbacks or arbitrary config metadata is persisted. Preserve required LangGraph control
  metadata while sanitizing error details; unsupported interrupt payloads must not silently turn
  into approved human actions. Root namespace only; no copy/delete/prune or time-travel dispatch.
  The initial application profile is explicitly `results` (execution UUID -> exact EntityRef)
  and `counters` (bounded node/visit identifier -> nonnegative integer). Permit only the installed
  LangGraph control-channel shapes needed for ordinary root StateGraph execution; a `__start__`
  payload must satisfy the same application profile. Code-owned node IDs may be supplied as a
  bounded allowlist for branch-control validation. This profile can be versioned later; it must
  not masquerade as support for arbitrary user graph state.
- [x] Restore only a fully committed, digest-verified journal prefix after the ledger session has
  reconciled. Limit each cursor to the existing 1 MiB bound and total history to explicit finite
  limits (initial development profile: at most 4096 records and 16 MiB cumulative cursor bytes).
  A limit is a visible error, never truncation or automatic deletion. Validate record grammar,
  parent/write references and binding on read as well as write.
- [x] Cover wrong thread/run/graph/authority/environment or manifest binding; unreconciled/stale
  ledger session; missing/corrupt journal records; duplicate checkpoint IDs; conflicting normal
  writes; concurrent saver instances; failed commit; bounds; returned-state mutation; unsupported
  data. A failed saver write must not return an acknowledged checkpoint or silently advance the
  dependent node. Show runtime public events do not contain private state/error/config canaries.
- [x] Run focused tests plus `app/tests/test_runtime_ledger.py` and existing graph-contract tests;
  record RED/GREEN, exact limitations and independent spec/quality review. Do not mark T040/T039
  complete: fresh dispatch, approved graph-to-handler mapping, semantic result admission, durable
  joins/loops, artifact handoffs and browser integration remain required.

Task-scoped result: initial 135-test suite passed but independent review rejected missing
LangGraph no-output completion support. The correction accepts `(__no_writes__, None)` only
as a pending completion marker; all application/checkpoint placements and non-null values stay
rejected, including tampered read-side records. Real SQLite next-checkpoint failure/restart
proves the completed no-op is not rerun. Correction RED 2 failed / 43 passed; parent final
148 passed in 24.30 seconds. Independent focused rereview: spec PASS / quality PASS, no
remaining findings. This accepts the bounded adapter only; T039/T040/T041 remain open.

### Task 4: Reject missing semantic result context before connecting worker admission (T087-A1 correction)

**Files:** `app/extensions/port_schema_generator.py`,
`app/tests/test_extension_port_schema_generation.py`, and optionally a focused
`app/tests/test_extension_result_context.py`. Generated schema bytes must remain unchanged;
this corrects the Python semantic validator, not the frozen port grammar.

**Observed defect:** existing `validate_port_payload(..., shape='result', context={})` accepts
provider catalog success, tool invoke success and storage read success (including an artifact)
without request/config/durable-artifact context. Existing tests reject only omitted context and
one codec happy path supplies only the request. `_validate_result_semantics` and artifact-lineage
checks use optional `context.get(...)` guards. All current executable callsites are tests; this
is a pre-integration fail-closed defect, not evidence of an exploited live endpoint.

**Interfaces:** Keep `validate_port_payload` and the 44 generated schemas stable. Require the
actual operation-specific comparison inputs before a result can pass semantic validation.
A Mapping remains an internal trusted-caller interface, NOT proof of authenticated/store-issued
authority; durable-context construction/extension heads/worker admission remain separate tasks.

- [x] RED-test empty, missing, explicit-null and wrong-type contexts against otherwise valid
  successful results, including empty-output catalog and real-metadata storage/codec artifacts.
  For targeted mutations first show a complete controlled context passes; do not obtain a negative
  pass merely because some unrelated prerequisite is absent.
- [x] Require common exact request and validated-config binding plus artifact-record mapping,
  including explicit empty mapping for zero-artifact outputs. Validate matching port/operation/
  request ID and config/request installation/qualification/binding identity before their
  comparisons. Bounds must not become optional. Missing malformed context raises the sanitized
  `PortSchemaValidationError`, not accidental KeyError/TypeError.
  Reuse the existing config/request semantic routines with their required qualification, binding
  revision/head, validated/accepted timestamps, actor, purpose, grants, input/selector/artifact
  records and applicable frozen-source fields; do not weaken them to just matching IDs. Validate
  embedded config/request shapes before indexing them. This rechecks supplied controlled context
  but still does not mint its authenticity or replace a future durable resolver.
- [x] For successful managed-runner `run_status`, require its ordered normalized-event artifact
  bindings even if empty. For tool `invoke_tool`, require its sealed ordered result bindings and
  core ToolDefinition output contract even if the output has zero artifacts. For codec
  `decode_projection`, require the resolved target projection media; render/encode compare the
  request target media. For export transmit, require the frozen target effect class rather than
  conditionally skipping it. Non-success errors still require manifest-frozen extension-error
  context and exact request lineage. Do not change terminal/effect/retry/cardinality semantics.
- [x] Enforce existing durable artifact media/digest/size/count/byte limits and exact result
  bindings on every applicable path. Preserve the validator's trust boundary: matching fixture
  dictionaries are test data, not real durable storage or execution authority. Do not create
  fake current binding heads, live worker results or semantic acceptance in RuntimeLedger.
- [x] Update the old request-only codec fixture and related negative tests to complete valid
  context before checking the intended mismatch. Add focused positive/negative cases for all
  affected result-context branches; retain the exhaustive static operation/terminal schema tests.
  Run focused port tests and byte-determinism checks, record RED/GREEN and independent review.
  T087 remains open, as does authenticated durable semantic result admission.

Task-scoped result: initial RED 1 failed, expanded RED 18 failed / 2 passed, then parent
78 focused passed. Independent review rejected malformed nested-context TypeErrors and
bool/float Artifact-size equivalence. Review RED 8 failed / 3 passed; final implementation
89 focused passed. The same independent reviewer confirmed both Important and both Minor
findings closed, spec PASS / quality PASS, and independently ran 12 relevant regressions
(51 deselected). Signature and all 44 schema bytes remain unchanged. Supplied bindings still
do not prove durable source lineage or authenticity; full semantic worker admission remains open.

Final integrated review found and then accepted the correction for a malformed
`resolved_arguments` ref-shaped `kind` leaking TypeError. Arguments reuse the existing bounded
domain canonical encoding, not envelope-specific field-name/string/depth semantics. Scanning
the validated JSON projection also closes a tuple-contained hidden-reference bypass. Normal
argument content remains accepted. Final focused port/schema suite: 97 passed; integrated
reviewer independently ran 9 relevant regressions, spec PASS / quality PASS, no remaining
findings. Parent final full-Python regression: 3535 passed, 2 skipped, 369 subtests passed,
one existing upstream warning, 201.36 seconds. This scoped four-task batch is accepted;
the whole-product integration and qualification tasks remain open.

### Task 5: Preserve exact nullable catalog effort in every model execution port (T042/T087 partial)

**Files:** `app/extensions/port_schema_generator.py`, the affected generated files under
`schemas/v1/extensions/ports/`, `contracts/extension-ports.md` in this feature, and
`app/tests/test_gateway_catalog_integration.py` plus a new focused
`app/tests/test_extension_model_effort.py`. Preserve all earlier uncommitted changes.

**Interfaces:** Add the exact core alias `effort-value`: a JSON UTF-8 string of 1–80 characters,
preserved byte-for-byte without trimming, case folding, Unicode normalization or identifier-only
restrictions. This matches the existing catalog/FrozenTurn shape; it is data, never a command,
capability or permission. Required `effort` and `requested_effort` fields accept this value or
explicit null (no explicit override). Capability arrays contain only non-null effort values and
retain existing sorted/unique/array bounds. Catalog validation still owns advertised availability.
This is a pre-release contract correction; preserve historical ADR-014 frozen review manifests
and disclose that their exact-byte acceptance does not automatically qualify amended schemas.

- [x] Observe RED for null and advertised non-identifier values on provider/model-runtime
  `model_step`, managed runner `run_start`/`preflight`, and all effort capability arrays.
- [x] Reconcile the type vocabulary, all three normative port rows, generator and affected
  generated schemas together. Do not alter other identifiers, model IDs, provider modes, effects,
  artifact profiles, result-context enforcement or the 44/52/208/127/81 invariants.
- [x] Test actual local Store/ModelCatalog -> validate_choice -> freeze_turn -> port request
  validation, using complete controlled config/request/frozen-record context and exact frozen
  effort projection. Include explicit null, ordinary values, case/space/punctuation/non-ASCII,
  non-NFC data and JSON-escaped control characters within the catalog grammar; no coercion.
  Clearly label constructed port/source refs as fixture context, not durable authority or a
  production dispatcher. Reject omitted fields, null capability-array items, wrong types, empty,
  81-character values, unsupported/removed catalog choices and stale account bindings.
- [x] Run focused gateway/catalog/selection/port suites, deterministic generation/contract
  structure parity and Ruff on changed Python. Record exact affected schema files/digests,
  RED/GREEN and limitations; obtain independent spec/quality review. Keep T042/T087 open.

Task-scoped result: clean RED 52 failed / 76 passed; implementer final 301 passed in27.20s,
parent independently 301 passed in27.33s. Fresh task review spec PASS / quality PASS, no findings.
Six generated schemas changed, with the 44/52/208/127/81 invariants preserved. This establishes
representation, not an actual provider dispatcher or durable binding qualification.

### Task 6: Durably capture authenticated worker responses without semantic success (T018/T040 partial)

**Files:** New `app/domain/worker_response.py` (pure closed content/schema) and
`app/runtime/worker_response_capture.py` (bounded capture orchestration/read boundary);
modify `app/runtime/{worker_coordinator,worker_dispatch,ledger}.py`,
`app/domain/{refs,schemas,schema_exports,store,permissions,events}.py`, affected generated
`schemas/v1/` domain/event exports and one capture schema. Tests in new
`app/tests/test_worker_response_capture.py` plus narrowly updated existing worker/ledger/
domain/permission tests. Update this feature's data-model/runtime contract for the exact new
record, event and recovery branch. Do not edit API/UI/provider/budget policy implementations.

**Architecture and authority:** Authenticated framing is not semantic acceptance. The actual
`WorkerCoordinator.exchange` must mint bounded process-local provenance only after its real
handshake/correlation/frame/output checks. An externally constructed `AuthenticatedWorkerResponse`
cannot mint capture authority. Preserve the existing response interface where possible; a
coordinator-owned identity registry/opaque receipt binds exact response, consumed permit, route,
generation and receiver output policy. Capture through an exact coordinator-owned method; no
serialization/reconstruction of dispatch permits. Keep provenance bounded and release it after
capture/abort. Reject changed identity/content; exact duplicate durable capture is idempotent.

**Closed record:** ordinary `domain-v1`, kind `worker_response_capture`, version1, immutable
`content.capture_schema_version=worker-response-capture-v1`. Content fields are command_id,
attempt_id, permit_id (UUID); execution_envelope_ref and runtime_profile_ref (typed EntityRef);
lease_fence (positive bounded integer); connection_id (SHA256); requester_boot_id/worker_boot_id
(broker boot grammar); channel_id/requester_service/responder_service (ChannelSpec grammar);
message_id/correlation_id (UUID); message_type (broker grammar); payload_blob (exact BlobRef);
artifacts (ordered 0–256 entries of closed `{descriptor: ArtifactDescriptor, blob: BlobRef}`).
No raw payload, path, credential, provider error or hidden-reasoning field appears in the record
metadata or logs. Preserve exact normalized worker payload bytes in the private blob partition,
without JSON parsing/reformatting. Source sensitivity is not cleared by transport authentication.

The host derives purpose/access/retention from the exact verified operational envelope and its
registered descriptor. actor_ref is the verified host-system root actor, not a copied human
author. parent_refs includes that envelope; episode metadata derives from its descriptor.
Other refs become ordinary dependency links. Metadata inheritance issues NO grant to the capture.
Core retention remains manual-only; no TTL, cleanup, silent deletion or automatic export.

**Transaction:** register verified payload/artifact blobs first (respect existing 16 MiB per
blob / 64 MiB reachable-graph defaults as well as stream caps; no automatic limit widening).
In one existing ledger/DomainStore SQLite writer transaction validate the exact committed
command/attempt/envelope/profile/owner/fence, insert immutable capture+dependency indexes,
register its permission descriptor, append a versioned `response_captured` journal reference,
and emit `attempt.response_captured` with only classification (`pending_validation|quarantined`)
and artifact_count. Only eligible clean/open/unexpired send_intent attempts may also append the
existing transport observation and become running/transport_accepted. Keep legacy redacted
observation wire shape readable; capture journal is the new exact-ref source, not another mutable
capture table. Cancelled, expired, terminal or recovery-uncertain known original attempts retain
quarantined capture and never reopen or replace earlier observations. Absent/foreign command
identity is rejected before creating an attachment. One capture per command; changed duplicate
conflicts, exact duplicate returns the committed ref without extra events/state transitions.

Add narrow caller-owned DomainStore put and persistent HostPolicy registration helpers, retaining
all existing type/root/vault/graph/blob/dependency/taint checks. Helpers validate the exact bound
active transaction; they must not publish new in-memory authority before commit or leave it after
rollback. Preserve ordinary public wrappers and process-local policy behavior. A new entity kind
and journal transition need no DDL change because current columns are TEXT; keep old migration
checksums unchanged and version new serialized payloads explicitly.

**Recovery/read:** startup validates every applicable capture journal/record/registered blob and
its exact command binding before opening global dispatch. A valid previously pending-validation
capture keeps its original nonterminal attempt recovery_pending/gate closed without requiring a
now-dead process owner; no capture never gains that branch. Cancelled/terminal/quarantined attempts
remain so. Missing/corrupt/conflicting data fails closed with an explicit sanitized gap. Current
dispatch status must prioritize terminal/cancel/recovery state over an old clean transport fact.
A private session-bound metadata lookup identifies the committed capture; a separate bytes loader
uses PolicyGate.read with exact capture/dependency grants, preserving post-read revalidation.
Do not grant captured blobs to runtime/model inputs automatically or expose a public raw reader.
The receive-before-capture-commit crash interval remains unknown because there is no durable
worker response ACK/redelivery protocol; never claim lossless or exactly-once delivery.

- [x] RED: actual controlled socketpair handshake + FrameCodec + worker response through
  WorkerDispatchService loses replayable bytes on reopen under existing implementation.
- [x] Implement closed schema and transaction helpers with normal/foreign/no-transaction,
  rollback/taint/dependency regression tests; schema/runtime parity and backward storage reads.
- [x] Integrate real coordinator-issued provenance and durable dispatcher capture. Test exact
  unusual payload bytes, zero outputs, multiple media, equal bytes under ordered distinct
  descriptors, malformed/reordered descriptors, foreign/forged/mutated receipts and limits.
- [x] Use real SQLite rollback fault injection at record/descriptor/journal/event/state writes;
  demonstrate no record/journal/descriptor/state split. Use a bounded owned subprocess for
  pre-commit and post-commit process exits and reopen inspection; no retry/resend. Capture
  uncertainty inhibits dispatch until durable identity is reconciled. Do not disable production
  no-trigger/schema checks merely to get fault fixtures through; inject after actual admission
  at the capture transaction or use controlled connection fault hooks.
- [x] Race cancellation/deadline with response receipt; preserve late evidence, terminal state
  and closed gate. Test restart with missing/corrupt blobs/refs, duplicates, changed bytes and
  stale sessions; no owner resurrection, no successor, accepted result or budget settlement.
  Assert reservations and usage finality do not become settled/final merely from capture.
- [x] Test permission-denied/foreign-purpose/revoked grants, raw content absent from public
  events/status/errors/repr, immutable returned values and real byte-for-byte authorized replay.
- [x] Run focused worker/coordinator/broker/artifact/ledger/budget/domain/permission regressions,
  schema parity and changed-file Ruff. Report OS-peer bypass in socketpair fixtures, storage caps,
  receive-before-commit gap and remaining semantic/extension/budget/scheduler dependencies.
  Obtain independent spec/quality review. T018/T039/T040/T041 remain open.

Task6 accepted after fix round1: both Important findings addressed, independent spec PASS/quality
PASS. Parent frozen-source full regression:3755passed,2skipped,369subtests,one unchanged upstream
warning in241.65s, exit0. The amended API fixture now uses real authenticated exchange; all45
terminal-separator schema/runtime parity cases pass. No semantic/settlement/scheduler/Linux claim.

### Task 7: Real durable web first-owner/session to existing command admission (T025 partial)

**Authority:** ADR008/009, ADR010's bootstrap/session-root paragraphs, ADR012's password profile;
`contracts/api.md` §1 and `contracts/operations.md` §2; data-model OwnerAccount/Authenticator/
BrowserSession/SessionRootReceipt. Read the task-specific source assessment at
`.superpowers/sdd/resumption-plan/owner-admission-next-design.md`. This implements the already
approved web authority prerequisite, not a new product direction or a complete T025 claim.

**Outcome:** Through the supported server factory and actual ASGI boundary, an offline-generated
origin-bound capability creates the sole durable owner and a real browser session. That session
authenticates the existing HostPolicy/RootCommandCoordinator path, survives permitted cold restart
as a browser cookie (not a revived Python capability), and is revoked by logout. No provider call,
worker grant, human approval, environment promotion or deployment privilege follows from login.

**Files:** New `app/operations/session_root.py`, `app/services/owner_auth.py`,
`app/api/session_routes.py`, `app/api/web_boundary.py`, focused auth-schema/admission helpers if
the service otherwise becomes monolithic, and fixed `app/api/route_contributions/core-v1.json`.
Modify `app/server.py`, `app/api/session.py`, `app/api/routes.py`, `app/api/transaction.py`,
`app/domain/permissions.py`, relevant event/schema exports, auth/setup tests and explicit historical
preview fixture imports. New `test_session_root.py`, `test_owner_admission.py` and
`test_web_owner_integration.py`. Add canonical auth storage/schema and route details to data-model
and API/operations contracts. Do not change provider adapters, runtime semantics, UI layout,
extension/deployment receipt implementation or old migration checksums.

**Serving boundary:** Make the supported `create_app`/`main` require a complete nonsecret deployment
configuration and separately mounted, already initialized session root. Missing config/root is a
startup failure, never an implicit historical LocalSessionAuthority/host-Codex fallback. Preserve
the old preview only behind an explicitly named `create_development_app` and clearly historical
fixture entry point; migrate its approximately17 import callsites mechanically, without portraying
their old cookies/fragment bootstrap as web qualification. The supported CLI entry must not mint or
print capabilities. It must not instantiate the development host's CodexConnection, credentials or
STT merely to initialize authentication. Missing managed services remain explicit unavailable
dependencies. Share existing nonprivileged services/routes where applicable; do not duplicate the
command service or create a new fake success route. This backend slice does not claim final UI,
legacy route migration, TLS edge, staged services or browser-story completion.

The administrative supported `main` takes required `--data-dir`, `--deployment-config`,
`--session-root-dir`, `--expected-uid`, and `--expected-gid`; validate bounded strict config and
nonnegative integer IDs before store/root admission. These are service deployment inputs, not
end-user instructions. Bind only the canonical container listener `0.0.0.0:8080` (the Compose
internal `http://control:8080` target); no configurable host/port, implicit preview listener,
startup browser opening, token/fragment output or public host publish. Call Uvicorn with
`workers=1`, `reload=False`, `proxy_headers=False`, `forwarded_allow_ips=""`, `access_log=False`.
The existing separate development fixtures keep their owned loopback/ephemeral listeners. Tests
capture this invocation rather than actually binding a public listener. This does not qualify the
edge or container network; the actual portable forwarded/TLS adapter is still pending.

Also migrate the existing no-account-action branch of `browser-codex-connection.test.mjs`, which
currently spawns `python -m app.server --port 0`, to a clearly named owned historical test fixture
`app/tests/fixtures/development_server.py`. That fixture may use the existing development authority
and loopback bootstrap URL solely for the unchanged preview regression; supported main never does.
Do not weaken its original no-account-check assertions or silently drop this browser case.

**Root and startup:** Reuse strict OriginProfile/CapabilityVerifier/base64url primitives. Session
root init is a deployment-only operation tested on explicit temporary directories: absent only,
exact32 random bytes, independent random key/generation labels, closed versioned nonsecret manifest,
directory-relative no-follow single-link files, exact expected UID/GID/modes, O_EXCL and file/directory
fsync. Exact valid existing state is verify-only/no-op; partial/malformed/symlink/ownership/epoch/
generation mismatch never replaces files. Serving has only a read/verify capability, not an init
method. Root bytes never enter configuration JSON/env/DB/log/repr/ordinary artifacts. Compare exact
instance/origin/root generation/configured epoch with durable auth control before admission. Initial
genesis is explicit epoch1; other/recovery mismatches fail closed until the separately planned
request-bound signed recovery path exists. Do not accept a verifier callback that fabricates it.

Use the same initialized DomainStore as policy/ledger/commands; factor initialization order instead
of constructing a fake owner callback. Keep auth state in a separately versioned and strictly
verified additive private SQLite component, not ordinary work/export records. Freeze exact tables/
columns/closed states and exported nonsecret schemas in this task's implementation documentation.
Bind the singleton control row to vault/instance/origin/root generation+epoch and persist clock
floors. Verify schema/checksums/row identities on reopen. Owner's real human actor record is authored
by the existing system root in the owner commit, never relabels that root, and contains no password,
hash, token digest or root. Public auth events are explicitly registered bounded counts/enums only.

**Two bootstrap commits:** Preserve both normative requirements. First commit consumes the exact
verifier before any Argon operation; second commit atomically creates OwnerAccount, the encoded
Authenticator, BrowserSession, human actor/descriptor and sanitized event. No raw capability or
password is ever persisted. Claim-commit failure causes no hash. Hash failure, queued timeout after
consumption, owner-commit failure or crash leaves consumed/unusable claim and no usable partial
owner/session; reopen classifies `setup_incomplete`, never restores the verifier or automatically
retries password work. Owner-commit success with lost HTTP response permits ordinary password login,
not raw-token replay. Repeated bootstrap never revokes the successfully created session. Record
claim opening/deadline/attempt count durably; process restart cannot replenish10minutes/five guesses.
Count a guess only after well-formed bounded input/exact origin/canonical capability admission;
malformed transport/shape requests do zero auth state or password work. A well-formed wrong verifier
consumes one guess; a matching fifth guess may win. No unauthenticated reset or capability GET.

**Password admission:** Exact argon2-cffi25.1.0, Argon2id19 salt16/tag32/memory65536KiB/time3/
parallelism4; validate stored encoded parameters before native verification. No weaker or unlisted
rehash profile. Enforce one serving-process owner for this instance via an OS-released exclusive
lock on a nonsecret explicitly owned control file, so the shared in-process FIFO gate is actually
deployment-wide; a second serving process fails startup. This initial single-control-plane process
constraint is explicit, not a claim that a Python semaphore coordinates several processes.
At most one native hash plus three FIFO waiters;10second queue admission. Reserve bounded capacity
before consuming a valid bootstrap; never release the native slot on cancellation until the native
operation really ends. Shutdown likewise retains the serving-process lock until surviving native
hash work ends (or the actual owning process exits); closing an app must not allow a second serving
process to overlap its still-running hash. Hash outside every SQLite writer. Independent source/account buckets each
burst5/refill1per6seconds; unknown names share one sentinel. Use bounded maps (1024 keys each,
idle expiry60seconds), no eviction of live saturated keys; full maps reject rather than replenish
allowance. Trusted source is actual socket peer/explicit fixed trusted edge, never forwarding-header
text. Persist bootstrap window/attempts; ordinary rate buckets are process-local under exclusive
serving ownership, not claimed restart-proof global abuse accounting.

`login_name` is an exact nonempty Unicode-scalar string of at most128 UTF-8 bytes, no control
characters or leading/trailing whitespace; no silent casefold/normalization. A newly chosen owner
password must contain at least15 Unicode scalar characters, with no mixed-character composition
rule; exact UTF-8 input≤1024bytes, never trimmed/normalized or logged. Login accepts a bounded
nonempty candidate and returns the same credential failure for a shorter incorrect password,
rather than leaking an account-specific policy branch. The minimum follows NIST SP800-63B-4
single-factor guidance (https://pages.nist.gov/800-63-4/sp800-63b/authenticators/), checked2026-09-15;
this does not claim full NIST conformity, a compromised-password corpus, MFA or phishing resistance.
Request body≤8192bytes before buffering/hash.
Uniform401 for valid-size unknown account/bad password; use the same bounded hash lane and a fixed
monotonic response-time floor (initial250ms, no timing-equality claim, no additional secret-dependent
delay). Record measured canary timings and resource caps. Uniform429 starts no excess hash.
Recheck owner/authenticator revision/epoch after hashing before issuing a new session.

**Sessions and routes:** Exact external routes relative to the configured base path are
`POST /session/bootstrap` with `{login_name,password,raw_capability_b64u}`;
`POST /session/login` with `{login_name,password}`;
authenticated `GET|HEAD /session`; and `POST /session/logout` with `{command_id}`.
Bootstrap/login are the only unauthenticated session-establishment mutations. Use shared strict
raw JSON/query/singleton-header parsing; forbid unknown/duplicate/BOM/invalid UTF-8/nonfinite/
trailing/oversize input before state/hash work. No old `/api/session` cookie/header aliases on the
supported path. Logout has an exact private command/digest replay receipt: same already-revoked
token+command+profile/epoch may return only its prior logout result, never authenticate another
operation; changed command use or epoch rejects. Commit revocation/event before local identity
retirement or cookie clearing. Preserve other active browser sessions on a new login unless the
exact presented prior same-owner session is rotated; global revoke-others/password change stay
pending under T025.

Raw session token is32 random bytes; only SHA256 digest persists. Idle12h/absolute7d, persisted UTC
clock floors, exact owner/auth/recovery epoch, and current revocation checks. Use existing exact
AuthenticatedSession/AuthenticatedRequest integration types, but only the persistent authority
registers bounded identity objects after actual cookie validation. Forged/copied/same-field and old
app-generation objects fail. Cold restart may validate the persisted browser cookie and issue a
fresh identity, never resurrect the previous object. Bound the identity cache; no process-global
unbounded token storage. Derive CSRF exactly from canonical JSON
`{domain:"deeptwin-csrf-v1",origin_base,session_token_b64url,recovery_epoch}` using the32-byte root's
HMAC-SHA256; return canonical base64url/no-pad from authenticated no-store GET without storing raw
token or minting another session. Mutation header is exactly one `X-DeepTwin-CSRF`.
Local cookie=`deeptwin_session`, exact random base path, HttpOnly/SameSite=Strict/no Domain/no Secure;
HTTPS=`__Host-deeptwin_session`, Path=/, Secure/HttpOnly/SameSite=Strict/no Domain. No profile fallback.

**Actual consumers:** Supported server calls FirstPartyRouteComposer exactly once for its existing
six versioned route declarations (GET/HEAD event/snapshot/command-read plus POST commands). Factor
the existing route installer into an APIRouter factory without duplicate registration; descriptor
is fixed build-installed core code, never operator/user Python. Nonversioned session routes are a
separate fixed mount; do not widen the composer's `/api/v1` contract. Apply exact configured origin/
scheme/host/port/base prefix, reject ambiguous raw path encodings/sibling prefixes and forwarded
origin/prefix spoofing before authentication. Strip the local prefix exactly once using code-owned
ASGI routing, not untrusted proxy headers. Protect every work/API/download/event route; only fixed
static setup/login shell and minimal health are unauthenticated. Preserve no-store/security headers
on errors and HEAD. HTTPS ASGI tests are not actual TLS edge evidence. Until the separately
qualified pinned-edge transport adapter exists, proxied internal HTTP must not be treated as HTTPS
by trusting forwarding headers; unsupported transport fails closed and the portable-edge gate stays
open. Do not quietly alter the canonical internal edge deployment topology to make a fixture pass.

At command commit, revalidate the actual persistent session/owner/authenticator using the SAME
RootCommandCoordinator SQLite writer before replay/intent and mutations. A separate earlier read
cannot close logout/revocation races. Reuse a transaction-aware bound method of the same session
authority with exact DomainStore transaction identity checks; do not swap in an arbitrary supplied
actor/context. Preserve HostPolicy's issuer identity and independent grants. Cover affected human
permission mutation paths likewise; no nested writer or uncommitted cache publication.

**Concrete internal interfaces and state:** Supported `create_app(data_dir, *,
deployment_config, session_root_dir, expected_uid, expected_gid,
runtime_dispatch_resolver=None, worker_dispatch_factory=None)` receives the exact existing
`build_bootstrap_configuration(...)` three-field mapping; UID/GID/path are trusted deployment
inputs, never HTTP fields. Preserve `create_development_app(data_dir, port=4193, ...)` for the old
preview. `initialize_session_root(directory, *, profile, recovery_epoch, expected_uid,
expected_gid)` is deployment-only; `open_session_root(...) -> SessionRootHandle` is read-only,
with `receipt`, `derive_csrf(token_b64u) -> str` and `close()` and no raw-key getter. Genesis files
are exactly `root.key` (32bytes,0400) and `manifest.json` (canonical JSON,0400) in a0700directory;
manifest fields are `{schema_version:"session-root-v1",generation_id,key_id,instance_id,
origin_profile_digest,recovery_epoch,created_at,state:"initial_genesis",integrity_tag}`. Generation/
key IDs are random UUIDs, timestamps exact UTC milliseconds; no raw-key digest or private key field.
`integrity_tag` is canonical base64url/no-pad HMAC-SHA256 under root.key over canonical JSON
`{domain:"deeptwin-session-root-manifest-v1",manifest:<all preceding manifest fields except integrity_tag>}`.
Verify it before opening a handle; pin the complete canonical manifest SHA256 in private auth
control on first startup and compare it on every reopen. The public receipt omits the integrity
tag; key/generation IDs remain independent random labels. This detects same-size key corruption,
manifest corruption and changed previously pinned pairs, not an administrator who can replace all
trusted files and DB state. A pre-existing empty owned directory may be the absent state; one
missing sibling is partial failure. Do not expose a general-purpose root-MAC oracle.

`PersistentOwnerAuthority` owns the root handle and the exact DomainStore. Its service methods are
`bootstrap(*, login_name, password, raw_capability_b64u, source_key)`,
`login(*, login_name, password, source_key, prior_cookie=None)`,
`authenticate_request(...) -> AuthenticatedRequest`,
`authenticate_bound(session, *, db=None) -> Actor`,
`session_view(request, *, token_b64u)`, `logout(request, *, command_id, token_b64u)` and `close()`.
HTTP adapters supply verified source/profile transport and release raw strings in finally blocks;
service methods still enforce their own closed scalar bounds. The optional db path validates the
active caller-owned writer; standalone bound validation is read-only. `OwnerAuthError` exposes only
closed error classes, never raw source exceptions. `BootstrapExchange` remains internal request-
response data with secret fields excluded from repr; only route adapters set cookies/return CSRF.

Use `owner_auth_*` private tables: migrations(version,checksum); control(singleton vault/instance/
origin/root-generation/key/manifest-digest/epoch binding, opening/deadline, clock floor, row revision/hash);
bootstrap_claims(epoch,verifier,attempts,state,claim_id,consumed/completed times, revision/hash);
accounts(owner_id,actor_ref,login_name,state,auth/recovery epochs,created/updated,revision/hash);
authenticators(owner_id,revision,previous_revision,kind/profile,encoded_hash,created/revoked,hash);
sessions(session_id,owner_id,token_digest,authenticator_revision,auth/recovery epochs,origin digest,
created/last_seen/idle_expires/absolute_expires/revoked,revision/hash);
commands(command_id,session_id,kind,request_digest,response_json,created_at,epoch,hash); and
audit(sequence,kind,entity IDs/time,previous_hash,hash). Control/claim/account singleton uniqueness,
token digest and command uniqueness and foreign keys are DDL constraints. Credential history uses
the exact previous-revision FK/CHECK. Mutable control/claim/account/session revisions advance only
through code-owned same-writer SQL CAS (`SET revision=old+1 WHERE identity=? AND revision=old`),
checking exactly one changed row; fixed table/identity/column allowlists reject unknown members.
Preserve the shared database's existing no-trigger invariant. Do not add auth triggers or relax
event/command/budget/ledger/service-client verifiers to permit them. Validate revision/hash/epoch
and related identity before every authority read/write and on reopen. This is service-transition
monotonicity under the shared writer, not protection against an administrator rewriting the DB.
Hashes are canonical closed-row integrity checks, not MACs or protection from a host administrator.
Claim states=`available|consumed|completed|expired|exhausted`; consumed without account is the
derived `setup_incomplete` gate. Account state=`active|disabled`; authenticators/sessions revoke
through timestamps/revisions, never delete historical rows. No raw password/token/root/capability.
The verifier is nonsecret configuration; it remains private auth state, never a work export.

The required transaction sequence is the following (each named operation belongs to the owner
service or exact DomainStore boundary above, not a caller-provided success callback):

```text
validate closed request and trusted transport; reserve bounded FIFO admission
BEGIN IMMEDIATE: verify available exact claim; consume claim; audit; COMMIT
perform exact admitted Argon2 outside all DB writers
BEGIN IMMEDIATE: recheck consumed claim and unchanged root/epoch/owner absence
  stage human actor/descriptor + owner + authenticator + session + event + claim completion
COMMIT
publish authority-owned session identity; send cookie and derived CSRF
```

Root tests call the actual initializer and loader; ASGI tests use actual cookie storage:

```python
configuration = build_bootstrap_configuration(
    profile=profile, verifier_b64u=derive_capability_verifier(capability),
)
initialize_session_root(root_dir, profile=profile, recovery_epoch=1,
                        expected_uid=os.getuid(), expected_gid=os.getgid())
application = create_app(data_dir, deployment_config=configuration,
                         session_root_dir=root_dir,
                         expected_uid=os.getuid(), expected_gid=os.getgid())
with TestClient(application, base_url=profile.http_origin) as client:
    created = client.post(profile.base_path + "session/bootstrap", json={
        "login_name": "owner", "password": "synthetic owner passphrase",
        "raw_capability_b64u": capability,
    }, headers={"Origin": profile.http_origin, "Sec-Fetch-Site": "same-origin"})
    assert created.status_code == 201
    snapshot = client.get(profile.base_path + "api/v1/snapshot",
                          headers={"Sec-Fetch-Site": "same-origin"})
    assert snapshot.status_code == 200
```

These temporary current-UID fixtures exercise backend authority, not the release container UID or
TLS peer boundary. Run new tests first with
`python -B -m pytest app/tests/test_session_root.py app/tests/test_owner_admission.py
app/tests/test_web_owner_integration.py -q -p no:cacheprovider`; preserve the first actual RED and
then repeat after each implementation section. Run the named existing regression families after
the new suite is green. No implicit retry, skip or user-authentication lambda makes it pass.

- [x] RED for actual supported entry accepting historical/missing auth rather than the required
  deployment-origin first-owner path; add root/claim/session integration tests before production code.
- [x] Implement closed private auth storage/root gate and actual two-commit bootstrap. Real SQLite
  fault points at claim and owner/actor/descriptor/session/event writes; bounded pre/postcommit child
  exits; reopens prove consumed-incomplete versus fully committed owner, with no secret persistence.
- [x] Test exact real Argon parameters on a small real-hash set; deterministic one-active/three-FIFO/
  fifth-rejected/queue-timeout/cancellation and independent source/sentinel buckets. Malformed/wrong-
  origin requests perform zero store/hash/command work; no expensive worker under a SQLite writer.
- [x] Compose actual server and session routes for both profiles. Bootstrap and login-issued cookies
  reach actual HostPolicy and existing authorized root-command transaction with controlled domain/
  worker prerequisites; do not monkeypatch owner verification or seed authenticated identities.
  Missing runtime resolver remains an explicit dependency denial. Test concurrent logout between
  early authentication and writer admission leaves no command/budget/event/permit mutation.
- [x] Test cold app reopen, expiry, root/profile/epoch/schema tamper, copied/stale identities,
  bootstrap replay, logout replay, revoked cookies, no-store/error/HEAD, exact HMAC and cookie/header/
  path/port/forwarding matrices. Root/key/password/token canaries absent from all public projections,
  ordinary snapshots/exports, repr and captured logs; only encoded password hash in private auth store.
  At this partial checkpoint, exercise the actual current auth/work/event/snapshot and ordinary
  domain-record projections plus existing export-category/private-auth exclusions. The current
  export module is a pure supplied-item manifest builder, not a DB collector/archive path; do not
  manufacture an exported archive or label a constructed manifest as end-to-end export evidence.
  Full collector/archive canary qualification remains mandatory under T071. Intentional session
  cookie and CSRF establishment/read channels are allowed; other projections never carry secrets.
- [x] Run focused new and existing setup/wire/router/domain/permission/command/server regressions,
  schema parity and changed-file Ruff; obtain independent spec/quality review. Keep whole T025/T026,
  UI, recovery, external TLS/Linux deployment and all provider/extension/runtime story gates open.

Task-scoped result: initial4RED; final169covering tests after review corrections. Independent review
found the nullable predecessor CHECK and missing current-surface
canary evidence; both fixed and rereviewed ADDRESSED, no new breakage. Parent final full regression
3859passed/2skipped/369subtests/1unchangedwarning in259.89s. Controlled historical browser81pass
in262.920s before the narrowly scoped storage/test fix; no browser/server/route source changed in
that fix. Final diffcheck passed. Deferred Minor: full retained-history/FK scans before rate
admission; upstream Starlette/AnyIO warning. These remain for long-retention/release review.
This completes Task7's bounded backend prerequisite, not whole T025/T026, final owner UI/TLSedge,
service clients/recovery, T071 collector, Linux/provider/extension or full-browser story gates.
No commits, push or live-account operations.

### Task 8: Actual owner to durable inert executable candidate registration (T087 partial)

**Authority:** ADR014, data-model §3.1 and the exact bounded wire/storage contract at
`contracts/extension-candidates.md`. Read that complete contract first. It is normative for this
slice; the earlier SDD candidate/plan draft files are superseded and not requirements. This adds
a real producer/consumer to the supported web path, not another installation-value constructor.

**Outcome:** The actual supported bootstrap/login cookie can register a complete executable
extension candidate, read it back through the fixed API, and recover identical immutable content
and command receipt after cold restart. Registration is explicitly unqualified. No source fetch,
image/container action, socket creation/reservation, grant, installation, qualification, binding,
model call or dispatch occurs. Stage prepare remains unavailable until its real deployment-owned
topology/inventory/receipt prerequisites exist. No fabricated managed-absence resolver.

**Files:** New `app/extensions/candidate_contracts.py`,
`app/extensions/candidate_schema_exports.py`, `app/extensions/persistence.py`,
`app/api/extension_candidates.py`, fixed
`app/api/route_contributions/extension-candidates-v1.json`, and focused tests
`test_extension_candidates.py`, `test_extension_candidates_persistent.py`,
`test_extension_candidate_api.py` plus a shared synthetic fixture if needed. Focused pure
contract/storage-schema helpers are permitted to avoid a monolithic file.
If formatting makes the immutable-content crosschecker unwieldy, one focused
`app/extensions/candidate_records.py` may own anchor/index/blob/receipt integrity loading;
`persistence.py` retains auth/transaction orchestration and `candidate_storage.py` owns closed
DDL/CAS. This is a responsibility split, not a line-count target or new public authority facade.
Modify supported `app/server.py` composition, `app/api/web_boundary.py` cheap preflight/route-local
body cap, `app/domain/events.py` and its schema exports/artifact. Update current
`test_web_owner_integration.py` exact route-set assertion to preserve the original six plus two
new declarations. Do not loosen that assertion or exact composer descriptor-set validation.
No edits to the old generic command argument grammar, global DomainStore reference scanner,
accepted migration checksums, historical v1 extension parser/schema artifacts or six effort schemas.

New structural JSON schemas live under `schemas/v1/extensions/` with explicit filenames
`manifest-v2.schema.json`, `service-descriptor-v1.schema.json`,
`candidate-registration-v1.schema.json`, `candidate-anchor-v1.schema.json`,
`candidate-api-v1.schema.json` and the bounded support/ref definitions as necessary.
Use a new generator rather than modifying historical v1 generation. Schema validity is structural;
document runtime-only byte/aggregate/digest/ref/ordering relationships and authority limits.
Update canonical data-model/API/extension-ports with pointers to the new exact contract and
implementation schema details, preserving historical design/qualification manifests.

**Source interfaces:** Pure frozen `ExecutableExtensionManifest`,
`ExtensionServiceDescriptor` and a bundle parser consume the complete contract. Returning detached
mappings must not permit mutation of hashed bytes. Reuse the core port catalog, tuple/refinement
validators and domain canonical primitives. A constructed candidate is deliberately inert, not
a private issuer pretending to grant stage authority. No arbitrary dynamic Python loading.

`PersistentCandidateRegistry(domain_store, owner_authority)` binds exact initialized DomainStore
and exact PersistentOwnerAuthority. `register(request, payload)` and
`read(request, candidate_id)` are the concrete API consumers; service methods validate their
request/session/actor/scalar invariants, not only route adapters. POST requires actual mutating
AuthenticatedRequest with CSRF. Revalidate the real current owner/session inside the final writer
before idempotency or state mutation. The exact real actor must agree with the request; no wrapper,
copied session, caller actor ID or supplied authentication/get_head callback replaces it.
Construction may initialize the inert private schema before first-owner bootstrap, but cannot
create an owner or require an already-created owner merely to start the setup/login service.

**Storage:** Manifest/descriptor/registration/support MetaRefs are opaque canonical blob content.
The small `extension_manifest` domain anchor contains only the actual BlobRefs in the contract.
Do not place MetaRefs directly under domain `*_ref(s)` keys or weaken the scanner. Use actual
same-vault operational blobs and actual persisted owner/root-policy references. The registration
blob's actor/identity/digests must agree with anchor/header/index and all loaded content.

Preseal through existing `DomainStore.put_blob` after initial real authentication, outside the
final writer: it opens its own writer and cannot be nested. Pre-check known full capacity and
exact replay before unnecessary sealing. Then same-writer revalidate auth+capacity and atomically
insert domain anchor/associations, registration index, capacity state, one public event and the
exact receipt. Unattached registered blob rows/files can remain inert after failure; no deletion
or DB/filesystem-atomicity claim. The committed64MiB unique-content cap is not a global disk quota.
No image is fetched and even a valid metadata URL is never followed.

Use additive version1 private `extension_candidate_*` schema/control/index/command/content-accounting
tables tied to the exact vault and deployment instance. Freeze their exact columns, keys, FK/CHECK,
row/hash and command namespace in canonical documentation and tests. Use closed table/column
identifiers, preserve no-trigger policy, verify shape/checksum and record/index/blob/actor consistency
on reopen/read. Candidate command IDs are unique within this named registration journal; changed
canonical input under the same ID is conflict, and reauthentication precedes replay. Mutable control/
capacity counters use same-writer expected-revision CAS with exactly one changed row. No fake
installation table/head or managed-absence API is introduced in this slice.

**HTTP/composition:** Fixed POST registration and GET|HEAD candidate read routes are declared in
the new first-party contribution. Supported factory composes exactly core+candidate descriptor names
once; historical preview remains separate and gets no candidate route. Do not add a new UI or
a dynamic factory loader. Preserve the six original route declarations.
Admit at most1MiB only on the exact candidate POST, with shared strict raw-wire and pure candidate
preflight before auth/state work. Preserve all other request caps. Query allowlist is empty, UUID/
method/media/body/path/origin/CSRF checks remain closed. HTTP response links add the local prefix
once, while stored receipts remain canonical. Candidate error/success fields are exact in the
contract; secret-bearing input, exception text and host paths do not appear in events/errors.
This does not qualify portable TLS, missing final owner UI or end-user installation.

- [x] Add RED real supported owner-cookie POST before source implementation; no current live
  registration route exists. Then actual POST201/readback, exact replay/changed409, event count,
  local-prefix links and HTTPS ASGI cookie profile. Reopen all service/app objects and read
  identical bytes/receipt/actor attribution through the same real authority.
- [x] Test complete synthetic two-platform ordinary-tool bundle and all executable catalog tuples.
  Reject v1/definition tuples, mixed/unknown/duplicate fields, wrong refs/digests/sizes/kinds,
  missing/unused/duplicate leaves and attempted future authority fields. Preserve historical
  generic v1 behavior/schema bytes and never treat source labels as qualification.
- [x] Test version/range/operation/refinement rules, raw Unicode/numeric/byte/depth/item bounds,
  unsafe/mutable URI/image/path forms, unordered sets/platforms/layer positions. Preserve ordered
  argv and repeated valid ordered layers. Test structural schema parity including end-line
  separators and bool-as-integer; distinguish additional semantic/runtime checks honestly.
- [x] Implement real domain-backed anchor plus private registration/command/capacity state.
  Fault content/anchor/association/index/event/receipt/precommit; no partial visible registration
  survives. Explicitly identify possible inert presealed blob rows/files. Exact lost-response replay
  produces no extra event/candidate. Test competing requests and detached input/read mutations.
- [x] Test copied/stale/old-generation and revoked-after-early-auth sessions against the actual
  final writer, with no registration/event/receipt on rejection. Unknown IDs/malformed wire/query/
  method/media/CSRF/origin fail with proper closed statuses and HEAD no body. Schema-invalid input
  performs zero auth/registry work; no authority replacement fixtures.
- [x] Test count1024 and unique-content64MiB bounds using controlled finite fixtures; exact replay/
  shared content consume no extra capacity. No eviction/truncation/cleanup. Corrupt schema/checksum/
  row/index/blob/foreign-vault bindings fail on reopen/read/register, never report absence.
- [x] Assert constructor/register/read/replay create no ChannelSpec/worker/process/network/image/
  grant/installation/qualification/binding/runtime profile/stage request. No stage endpoint is
  exposed merely to show an unavailable stub. Actual ordinary projections/events remain secret-free
  and metadata strings remain inert. Full source/license/runtime/port qualification stays open.
- [x] Run focused new candidate tests plus current web-owner/root/admission, domain storage/schema/
  events, router composition and historical extension/refinement families. Record exact commands,
  RED/GREEN/results/durations, changed-file Ruff and schemas/diffchecks; no full-suite duplication.
  Parent independently reviews the task and runs final fullPython regression after source freeze.

**Preflight rulings:** The shared reference scanner requires actual EntityRef/BlobRef, so use opaque
candidate blobs and real-ref anchor. Existing put_blob owns a transaction, so preseal outside the
final writer with explicit inert-orphan limits. Composer verifies all JSON names in its root, so
pin the complete supported set without widening the historical preview. Candidate registration
cannot allocate missing deployment topology. These decisions preserve source integrity without
granting execution. Cost if wrong: rework candidate layout/composition/sequencing, not host authority.
Task7's retained-history pre-rate verification cost and upstream warning remain ledgered Minors for
long-retention/dependency qualification; do not use this task to rewrite authentication.

**Supplemental acceptance correction — reusable-core dependency gate:** Parent's resolved recursive
AST check found four inherited imports the old shallow test missed: permissions→api.session,
owner_auth→api.session/views, service_client_auth→api.wire. Candidate persistence needs those same
shared values/event writer, but ADR014 forbids presentation imports from the reusable core. Correct
this dependency before accepting Task8; it is not permission to redesign auth/event/wire behavior.
Finish the candidate-specific tests first, then perform this bounded mechanical extraction before
source freeze and the independent task review. No separate next implementation starts meanwhile.

Additional files: create `app/domain/request_identity.py`, `app/domain/wire.py`,
`app/domain/public_events.py`, `app/tests/test_core_import_boundary.py` and a focused test scanner
helper if needed. Modify `app/api/session.py`, `app/api/wire.py`, `app/api/views.py`,
`app/domain/permissions.py`, `app/services/owner_auth.py`, `app/services/service_client_auth.py`,
new candidate persistence imports, and `app/tests/test_client_conformance.py`.
Parent saved all seven additional existing-file before snapshots before edits. Canonical candidate
contract should note the shared core ownership without changing its wire/storage acceptance.

- [x] RED: replace the old shallow scan with recursive absolute/relative import resolution, covering
  ordinary modules and package `__init__.py`, alias/from-import spelling, nested core packages and
  forbidden `app.api`, `app.static`, `app.server`, FastAPI, Starlette and Jinja2 targets. Include
  synthetic nested/relative failure fixtures and allowed sibling/stdlib cases; prove the actual
  current source scan fails, not just a mock tree. Include literal dynamic import spellings or
  explicitly reject dynamic module loading in reusable core; this static gate is not a runtime
  sandbox or arbitrary malicious-source proof. Do not fix the test by excluding affected modules.
- [x] Move SessionBoundaryError/RequestDenied, exact AuthenticatedSession/AuthenticatedRequest and
  `authenticate_in_transaction` to request_identity, with API session re-exporting the same objects.
  Keep historical LocalSessionAuthority/bootstrap/HTTP-header plumbing in API session. Preserve the
  exact persistent-bound-method guard and same-writer behavior; no wrapper classes/copied sessions.
- [x] Move the existing strict bounded wire codec to domain/wire and retain the API import facade.
  Move pure event envelopes/cursors/storage/journal and transaction helpers from views to
  domain/public_events; keep `render_sse` and HTTP response framing in API views. Relative imports
  point to shared core types. Preserve event DDL/checksum/constants/record bytes and denial/rollback
  behavior exactly. The800-line event module is an existing single-module move, not permission for
  a larger event redesign or speculative new abstraction. Explicit facades, no sys.modules alias
  tricks or dynamic API imports to hide dependency edges.
- [x] Update core consumers to shared modules; current API callers remain compatible. Add identity
  tests, e.g. `app.api.session.AuthenticatedRequest is app.domain.request_identity.AuthenticatedRequest`,
  the same for AuthenticatedSession/RequestDenied, wire limits/error and event envelope/journal.
  Show actual login/candidate command identity and existing SSE behavior remain unchanged. Record
  an AST-body equivalence check for moved definitions against parent snapshots as migration evidence;
  changed import paths/location and removal of SSE rendering are deliberate, functional rewrites are not.
- [x] Cover `test_core_import_boundary.py`, `test_client_conformance.py`, `test_wire.py`,
  `test_local_session.py`, `test_public_events.py`, `test_service_client_auth.py`,
  `test_api_command_transaction.py`, current owner/root/admission/candidate families and relevant
  domain/event/schema tests. Record exact RED/GREEN and changed-file Ruff. Parent's final full
  Python run follows the combined source freeze, not the intermediate candidate milestone.

Ruling: the canonical reusable-core prohibition controls over the earlier plan's physical API
module locations. Preserve logical interfaces via identity aliases while relocating pure shared
definitions; no authentication/security policy is weakened. Cost if wrong: bounded extraction/
import and regression rework. This correction is part of Task8 acceptance rather than a parked
structural flaw propagated into another dependent implementation.

#### Review conflict correction — common composition and transitive architecture gate

The original task's feature-specific startup wiring and four-root direct-import scanner conflict
with canonical tasks.md287–293/412–424. Correct them in Task8 before acceptance; do not weaken
ADR014 or merely rename extension-specific server edits as T025. Candidate serialization, storage,
authority, route declarations and migration/schema bytes remain unchanged.

- [x] Replace candidate-specific imports/construction/factory closures and descriptor/scope names
  in supported server startup with a bounded T025-owned common first-party dependency contribution
  seam. A fixed build-owned catalog may declare exact installed descriptor names and concrete
  first-party factories; no user/operator-selected catalog, dynamic import, arbitrary module/path,
  late registration, lifecycle hook or external extension executable is loaded. Contribution-owned
  API code receives the actual frozen shared application context (domain/owner/core services and
  existing routing inputs) and constructs its own candidate registry/router. The common adapter
  validates the complete fixed descriptor/factory set, invokes the existing FirstPartyRouteComposer
  once and publishes only immutable, unique contribution-owned service exports after successful
  composition. Keep shared infrastructure/type ownership clear; do not replace explicit
  dependencies with a mutable global service locator. Existing app.state.candidate_registry may
  become an internal immutable contribution export with all tests adapted; HTTP behavior stays exact.
  New helper files may be app/api/first_party.py and app/api/first_party_catalog.py, plus focused
  common seam tests. Keep app/api/router_composition.py behavior unchanged unless a concrete missing
  generic validation requires an explicit parent snapshot/ruling. A catalog registration plus the
  contribution's API module/descriptor must suffice without changing server/composition code.
- [x] RED-test supported real-cookie candidate registration through that common seam, absence of
  extension-specific server knowledge, actual same domain/owner identity, duplicate exports and
  missing/mismatched/late contributions. Demonstrate a controlled additional build-installed
  contribution through the same generic path with server/composition source unchanged; it remains
  a test fixture, never an arbitrary external plugin loader. Preserve cold reopen, exact six+two
  production routes, no eager providers/workers, startup failure cleanup and historical preview.
- [x] Extend the AST gate to domain/services/runtime/operations/extensions and recursively follow
  resolvable repository-local imports outside those roots (including parent package __init__ files,
  relative/import-from aliases, imported packages and ordinary cycles). Resolve without importing
  or executing scanned modules. Standard-library/external non-presentation dependencies are leaf
  nodes; do not traverse site-packages. Reject reachable API/static/server/FastAPI/Starlette/Jinja
  and resolvable dynamic-import bypasses. Preserve the explicit non-sandbox limitation.
- [x] RED-test an operations direct violation and a core -> ordinary app helper -> API chain,
  package initializer leakage, indirect dynamic import and cycles/allowed chains; demonstrate the
  current actual five-root closure passes or report actual new edges before broad source changes.
  Do not silence reachable violations or reduce the closure to preserve a green result.
- [x] Run test_core_import_boundary.py, test_client_conformance.py, new common seam tests,
  test_router_composition.py, test_web_owner_integration.py and all three candidate families.
  Record exact RED/GREEN plus changed-file static checks and append fix report. Parent runs the
  final full regression only after source freeze, then scoped independent rereview of these two
  Important findings. Keep review Minors separately recorded; this is not a warning/performance
  cleanup or a whole-T087 completion claim.

Task8 accepted after the original review and corrected two Important plan/spec conflicts.
Final independent scoped review: both ADDRESSED, no new Critical/Important. Parent frozen full
regression4126passed/1Linuxskip/369subtests/1existingwarning317.38s, exit0. Additional optional
Claude SDK tests are now collected (106offlinecases), not live-account evidence. Full T025/T087,
near-capacity performance, specific bound-fixture refinements and final product journey remain open.

### Task 9: Real finite deployment source I/O without lifecycle authority (T025/T087)

**Spec:** contracts/deployment-prepare-sources.md, including the exact source shapes, independent
source factories, fixed /opt/deeptwin release layout, §9 projection-only codec and X-only finite-float
serialization exception. This is the accepted source-I/O prerequisite, not a new design round.
Follow all Global Constraints. Existing whole T025/T087 and final two-host/packaging gates stay open.

**Files:**
- Create app/deployment/__init__.py (inert package), contracts.py, render.py, mounts.py, files.py,
  sources.py and publication.py as the focused responsibilities specified in contract§10.
- Create app/operations/deployment_prepare_init.py and
  deploy/security/deployment-prepare-recipe-v1.json.
- Modify only app/workers/ipc_root.py for the metadata-only lease extraction/addition; preserve
  existing secret-bearing lease and initializer behavior and tests.
- Create app/tests/deployment_source_fixture.py, test_deployment_source_contracts.py,
  test_deployment_source_render.py, test_deployment_source_files.py,
  test_deployment_sources.py, test_deployment_publication.py,
  test_deployment_prepare_init.py and test_ipc_metadata_lease.py.
- Parent owns contracts/deployment-prepare-sources.md and resumption bookkeeping.
- Do not modify server.py, route composer/catalog, domain/auth/candidate stores, current
  deploy/compose.yaml, static service-ids, old schemas/checksums or historical build evidence.
  If a concrete missing interface needs any other existing source edit, report before writing.

**Interfaces:** Implement the exact concrete exported function/type boundary in contract§10.
Sources read real files/held FDs/current mount state, not caller-provided observations. Parsing/
rendering returns inert values only. Task10 will hold these concrete independent source objects and
call publication under its own writer; no HTTP endpoint/journal/DB-owned lifecycle is introduced.
Error types expose constant sanitized codes only (invalid source, source unavailable/busy,
publication unavailable); no raw paths/payloads/mount text in messages. Details stay in private
test assertions, not public events. Existing IpcRootError types remain compatible.

- [x] Read the full source contract, exact base files, OriginProfile/canonical/EntityRef and
  existing IPC root helpers. Freeze unchanged B/S input identities:
  B sha256=6a18faa38379724a18466f39b42f66c4405fe11eb790b8e9c21addd39cbd152e size25731;
  S sha256=4330b2080d5579847909fb086ebde6144b1fc54fdee6251a97383acd1e5565f4 size9544.
  Create the exact canonical R from these bytes, never regenerate B/S. No dependency changes.

- [x] RED-test pure exact parsing/determinism and then implement contracts/render. Test example
  (fixture makes exact OriginProfile/UUID values and supplies the actual B/S/R bytes):

  ```python
  def test_same_instance_is_byte_deterministic(release_inputs, instance_bytes):
      first = render_prepare_sources(*release_inputs, instance_bytes)
      assert first == render_prepare_sources(*release_inputs, instance_bytes)
      assert json.loads(first.expanded_compose_bytes)["services"]["control"]["cpus"] == 1.0
      assert first.topology_bytes == canonical_json(json.loads(first.topology_bytes))
  ```

  Cover local/portable OriginProfile and both OCI platforms, capacity1/16, bool/zero/17, duplicate/
  unknown/noncanonical/deep/oversize bytes, distinct nonnil IDs, modified derived values and hashes.
  Assert all original X subtrees structurally unchanged except the enumerated control additions;
  old B/S bytes/hash unchanged; no created extension service; exact groups/mounts/config IDs,
  one-shot restrictions, acyclic recomputation of P/A and two-instance template invariance.
  Test X preserves only allowed known finite base floats while R/I/T/E/P/A still reject all floats.
  Test no random/time/network/Docker subprocess call during rendering.

- [x] RED-test metadata lease before implementation. Use actual temporary IPC files/locks and
  existing low-level fixture metadata substitution where host privileges require it:
  ```python
  def test_metadata_lease_never_reads_secret(initialized_pair, monkeypatch):
      def forbidden(*args, **kwargs):
          raise AssertionError("secret content read")
      monkeypatch.setattr(ipc_root, "_read_exact_secret", forbidden)
      with ipc_root.acquire_generation_metadata(initialized_pair) as lease:
          lease.recheck_current()
          assert not hasattr(lease, "secret")
  ```
  Add wrong/missing/replaced lock, exclusive contention, swapped endpoint/root/boot metadata,
  hardlink/symlink/size/mode, known listener/socket absence and permission-denial tests. Assert
  close idempotence, closed/copy/pickle denial, failure FD cleanup and unchanged acquire_generation
  byte-authentication behavior. Metadata reading never creates BootSecret or hashes secret bytes.

- [x] RED-test mount and file readers, then implement bounded actual OS adapters. Use actual
  temporary FDs/bytes, only low-level fstat/mountinfo/platform fixture seams where necessary.
  Add strict escape grammar/size/line/items/duplicates/RO-vs-superblock flags, malformed separators,
  exact/nested/overlapping/backing-root aliases and allowed unrelated mount-order changes.
  Files: nofollow ancestor/root/file, hardlinks, exact modes/UID/GID/membership, truncation/growth,
  path swap while held, renamed same-byte root, wrong independent pin/instance/recipe, missing
  configured protected root. Deny unexpected namespace files and staged/final count overflow.
  Assert production factories have no caller paths/UID/proof callback or non-Linux positive mode.

- [x] RED-test independent source factories/currentness then implement sources. Instantiate actual
  concrete readers over genuine files with synthetic low-level Linux observations, preserving
  source-owned inode/currentness checks. Acquire exact derived slot with actual metadata lock.
  Observe stable outbox identity and compare after namespace swap. Changed T denies a new slot
  and request caller admission, but E still independently opens on restart and can publish cancel.
  Changed E blocks all publications; no alias to session/data/builtinIPC/source/other exchange.
  No source constructor issues an installation, qualification, WorkerRouteBinding or owner token.

- [x] RED-test closed file projections/no-clobber then implement publication. Request codec validates
  the exact common shape/hash/source binding only; kind-specific semantic authority is explicitly
  Task10's requirement, not a fake validator here. Test cancellation's exact closed marker.
  ```python
  def test_existing_different_bytes_are_never_overwritten(exchange_fixture, request_projection):
      source = exchange_fixture.open_actual_source()
      before = exchange_fixture.seed_conflicting_final(request_projection)
      with pytest.raises(DeploymentSourceError):
          source.publish(role="request", request_digest=request_projection.digest,
                         payload=request_projection.payload)
      assert exchange_fixture.read_final(request_projection) == before
  ```
  Fixture methods operate real files, not a mocked successful source. Cover final same-byte replay,
  mismatched request digest/full-payload hash distinction, invalid role/UUID/base64/foreign instance,
  cancel schema/clock encoding, exclusive stage creation, mode/group ordering and fsync order.
  Syscall ENOSYS/EINVAL/EOPNOTSUPP/missing symbol fail unavailable with no overwrite fallback;
  EEXIST follows exact file checks. Crash before/after rename and fsync failure never returns a
  false durable-success observation. No stage cleanup or root repair. Production rename is fixed
  Linux libc symbol with RENAME_NOREPLACE=1; fixture syscall behavior is not Linux qualification.
  No external worker, model, socket connection, deployment process or arbitrary path is executed.

- [x] RED-test actual fixed main/root-init orchestration then implement initializer. It loads
  /opt/deeptwin release files and fixed operator I/P configs, verifies all pins/actual mounts and
  UID0/Linux before effects. Fixed pure subroutines may take temporary FDs in tests, but no
  operational argv/env path/UID/config override or caller-cwd release search exists.
  Test genuinely empty mounted roots initialization, exact existing roots verify-only, wrong/
  partial/stale/staging/extra roots deny without chmod/overwrite/cleanup, and valid outbox files
  survive restart. Root creates namespace dirs before handing root to20102:21201; fsync each.
  Reuse existing initialize_pair_root only in external initializer; no control imports initializer.
  Assert bootstrap/session/provider/signing/receipt/private roots never opened. No real chown,
  root service, namedvolume, image/pull or Docker action is performed in development fixtures.

- [x] Cover new tests plus test_ipc_root.py, test_worker_boundary.py where their actual files live,
  core import boundary/client conformance and current candidate/owner supported startup smoke.
  Discover exact existing test names with rg, don't invent missing paths. Run focused families
  while iterating; record RED/GREEN failures and migration details. Finish one covering run,
  changed/new Python Ruff, B/S hash parity, source schema/canonical parity and git diff --check.
  Parent owns final full Python regression after source freeze; do not duplicate it.
- [x] Self-review actual modified/new file diff, source/FD cleanup and failure behavior, then report
  .superpowers/sdd/resumption-plan/task-9-report.md with exact files/commands/output/limitations.
  No commits/push. Independent review follows source freeze; do not launch your own reviewer.

Acceptance is actual producer/source/file I/O with explicit limited observations, not an installed
tool or supported owner preparation workflow. Task10 immediately consumes it with the actual
seven-table owner/domain journal and prepare/cancel routes. A packaged initializer image, actual
Linux mounts/rename syscall, final Compose/profile qualification and both host gates remain open.

### Task 10: Actual owner stage prepare/cancel, journal and startup recovery (T025/T087)

**Execution phases (2026-09-15 scope-preserving split):** The original implementer escalated
the combined contract/storage/transaction/composition/HTTP scope after completing its foundation.
Use three sequential independently reviewed phases. A: closed pure stage/request/domain-anchor/
schema contracts and exact seven-table schema, typed rows and CAS primitives. B: retained whole
journal integrity, actual owner/source/candidate transactions, lifecycle and publication/recovery.
C: common dependencies/resource ownership/activation and the supported real HTTP chain. A does
not establish a usable prepare service; B does not establish a browser route. Task10 and the
original acceptance checkboxes remain incomplete until all three phases and their integrated
verification are accepted. No service stubs, relaxed authority checks or reduced release scope.

**Spec:** contracts/deployment-prepare-journal.md (all12sections) and accepted
contracts/deployment-prepare-sources.md. The journal contract fixes exactDDL/stagewire/owner/source/
absence/expiry/replay/HTTP and the narrow common composition/resource/activation amendment.
Follow Global Constraints; this first-only slice does not close fullT025/T087 or install anyworker.

**Files:**
- Create app/deployment/prepare_contracts.py (purestage), prepare_schema_exports.py (fourartifacts),
  prepare_storage.py (sevenexacttables/rowhash/CAS), prepare_records.py (retainedanchor/blob/event/
  commandintegrity), prepare_lifecycle.py (closedwritertransitions), prepare_service.py (actual
  owner/candidate/source transaction and boundedreconciliation).
- Create app/domain/deployment_request.py (pureanchorcontentvalidator/schema); modify
  app/domain/refs.py, schemas.py, schema_exports.py, events.py fornewkind/content/exports/expiry.
  Modify app/operations/audit.py only toaddexpiry toexistingdeployment lifecyclecoverage.
- Create app/api/deployment_prepare.py and app/api/route_contributions/deployment-prepare-v1.json.
  Modify app/api/first_party.py, first_party_catalog.py, web_boundary.py, app/server.py only for
  contract§11commonseam/fixedHTTPadapter. app/api/router_composition.py staysbyte-identical.
- Generate four schemas/v1/deployment/*.schema.json named incontract§9; regenerateonly current
  schemas/v1/domain-envelopes.schema.json and event-metadata.schema.json. Preserve44port,
  oldcandidate schemas, B/S and historicalbuildinputs/checksums.
- Create app/tests/deployment_prepare_fixture.py, test_deployment_prepare_contracts.py,
  test_deployment_prepare_storage.py, test_deployment_prepare.py,
  test_deployment_prepare_integrity.py, test_deployment_prepare_publication.py, test_deployment_prepare_api.py,
  test_first_party_dependencies.py. Adjust test_first_party.py fordeclaredexports and
  test_web_owner_integration.py forexactnewrouteIDs/count withoutweakeningexistingassertions.
- Parent owns newcontracts, extension-candidates.md amendment and bookkeeping. Otherexistingedits
  needconcreteparentruling/snapshotfirst. No dependencychange, commits/push, hostroots/mounts/
  credentials/liveproviders/Docker/unrelatedprocess or maincheckout changes.

**Interfaces:** PersistentDeploymentPrepare(domain_store,owner_authority,candidate_registry,*,
topology_source,exchange_source) in prepare_service.py binds exactactualinstances. Independently
unavailableT/E may beNone, neverpositiveeligibility. No callerclock/proof/installationgetter.
prepare(authenticated_request,payload)->dict; read(authenticated_request,request_id)->dict;
cancel(authenticated_request,request_id,payload)->dict; reconcile_startup()->None.
DeploymentPrepareError(code) usescontractclosedcodes. Ownjournalcorruption givesunavailable
concreteservice, notfakeemptystate/table recreation; unexpectedbugs failstartup. Methodsretain
actualowner checksbeforeprivate state disclosure. No in-lifetime revival of corruptjournal.

FixedAPIfunctions prepare_services(context,*,dependencies), reconcile_prepare_startup(own_exports).
Requireonly extension-candidates.registry and provideonly deployment-prepare.service. Actualsame
registry/domain/owner, sourcesopenindependently viafrozenstartupinputs, localExitStack then common
ownedresources. GenericStartupInputs/declarations/publication/activate_startup matchcontract§11.
Use Task9 validate_projection(*,role,request_digest,payload,profile)->Projection plusfullclosedstage
andactualadmission; E.exchange_bytes/slotlease.topology_bytes areinert notcurrentnessproof.

- [x] Read fullcontracts and actualTask9acceptedinterfaces/report plusowner/candidate/domain/
  event/composer. Parent snapshots existingpaths beforedispatch. No historicalin-memory
  ExtensionRegistry ismanagedabsence. No newdependency orliveplatformcallneeded.

- [x] RED-test exactseven-table schema/enrollment andpurewire; implement storage/content/schema.
  ```python
  def test_deleted_private_schema_does_not_restore_absence(prepared_store):
      prepared_store.drop_only_private_tables_in_fixture()
      with pytest.raises(DeploymentPrepareError):
          prepared_store.reopen_and_prepare_new()
      assert prepared_store.actual_domain_request_count() == 1
  ```
  Fixturedeletion affectsown temporarySQLiteonly. Coverwhollyabsent vs partialschema/renamedindex/
  trigger/checksum, NULLpredecessor rawSQL, wrongvault, missing/extraanchor/index/history/head/
  command/outbox/event/blob, rowhash/JSON/scalar/FK corruption andcoldreopen. BoundqueriesLIMITmax+1.
  Newdomainkindversion1/purpose/ID/parent/BlobRef constraints andactualrefs checked; nohashcycles.
  FournewJSONschemas +currentdomain/event artifacts validate/regenerateexactly withcontractURNs.

- [x] RED-test closedstage reconstruction thenimplementactualcandidate/source matching. Actual
  candidate_records.load_candidate anditsblobs provideoneCandidateBundle; preserveMetaRefs,
  OCIindex/selectedmanifest/config/orderedlayers includingrepetitions. Requirebothplatforms,
  ordinarycorecatalogtuple, allidentity/UID/GID/channel/protocol/socket/mount equality, networknone,
  emptygrants/secrets, exactowned_scratch, fixedisolation, allfourresourcebudgets. Rejectextra/
  futurefields, tombstonehead, preconditions, wrongslot, arbitrarysourceclaims. Preservecandidate
  bytes. No imagefetch/tagresolution. TTLexplicit/no nonce reuse; calendar/b64/hex/type/depth/
  bytecaps andJSONschema-runtime positive/negative parity. Pureparsinggrantsnothing.

- [x] RED-test actualprepare/read/replay thenimplement coherenttransaction:
  ```python
  def test_prepare_commits_once_and_replays(deployment_fixture):
      service, owner, payload = deployment_fixture.actual_service_owner_input()
      first = service.prepare(owner, payload)
      assert service.prepare(owner, payload) == first
      assert deployment_fixture.actual_counts() == {
          "requests":1,"lifecycle":1,"heads":1,"commands":1,"outbox":1}
  ```
  Genuineowner/sourceFD/IPC locks/SQLite, lowlevelLinuxobservationfixturesonly. Exactfinalwriter
  calls owner.authenticate_bound, registry._verify and candidate_records.load_candidate.
  Presealrequest/T/E beforehand, no nestedpublicread/putblob writers. Finalrevocation/copiedowner/
  sourcepin/inode/currentness/clock/history/barrier checks; actualinstallation/qualification/
  bindingrecords globallydenynewabsence. TwoSQLiteconnection same-slot/same-target race1winner.
  Faultafteranchor/reservation/event/head/command/outbox rollsbackallauthoritytogether; inert
  presealedorphansmayremain. No successfulreply beforecommit.

- [x] RED-test lifecycle/time/replay thenimplement prepare_lifecycle:
  ```python
  def test_expired_cancel_commits_expiry_before_conflict(deployment_fixture):
      prepared = deployment_fixture.prepare_actual()
      deployment_fixture.advance_actual_clock_past_deadline()
      with pytest.raises(DeploymentPrepareError, match="conflict"):
          deployment_fixture.cancel_actual(prepared)
      assert deployment_fixture.head_state(prepared) == ("expired",2)
      assert deployment_fixture.cancel_command_count() == 0
  ```
  Realclockcheckpointdurablebeforebusiness, rollback/restartcannotreviveobservedexpiry; overflow/
  explicitTTL/sameinstantms+microseconds. Prepared->cancelled/expiredonce, exactsystemactor/event,
  no reopening/release. Changedcommand/body/route/namespace/revision/digestconflicts, freshvalid
  ownersessionexactreplay works. GET/exactreplay no deploymentcheckpoint/expiry/flush (existing
  authclockmaintenanceunchanged). Matchingexpiredcancel commits before409, notrollbackexception.

- [x] RED-test journalownedpublication/recovery thenimplementboundedreconcile. SameSQLitewriter
  holdsactualcommittedoutbox/E/T/time/lifecycle checks throughno-clobberIO andackCAS. Econtinuity
  immutablefromactualFDs, no pin/namespace reenrollment. Real cancel-beforepublish, publish-before-
  cancel andcrash-afterrename-beforeack preservebytes/barriers/honestpending/suppressed. Tloss
  includingrestart permitsEcancelmarker butnewrequestadmissiondenied; Edriftblocksprojections
  withoutblockinglocalcancel. PostcommitIOunavailable returnsfrozen201pending, notfalse500retry.
  max16items/cancelfirst/one-secondsoftbudget withkernel-latencylimitation; no receipt/slotrelease.
  Actualpublicevents closedrevision/ObjectRefs/status, no nonce/key/path/rawsourcecanaries in
  events/logs/repr/errors. OwnerrequestGET deliberatelycontainsitsauthorizedimmutablebytes.

- [x] RED-test commondependencies/resources/startup thenimplementcontract§11. Samecontext/
  exactregistry, immutabledeclaredsubset, missing/forward/cyclic/duplicateprovides/exportmismatch
  beforeeffects, no repeatfactoryorlocator. Frozenallowlistedstartupvalues/keyonlyinvalidmarkers;
  malformedfeaturepins preserveother routes, actualdata/session/configprotectedpathsforwarded.
  Resourcescloseonce reverseorder for factorylocalerror, invalidreturn/export/router/laterfactory/
  inclusionfailure, shutdown andworkerstartfailure; tryallowners/preserveoriginalerror.
  No filepublication duringconstructor/composition. One-shot/reentrysafe hostactivate_startup only
  aftercompletecomposition beforeworker/HTTP. Expectedsourcefailurecontained; laterworkerfailure
  cannotundoauthorizedfiles. Lowercomposerbytes/passivityunchanged; oldfixturedeclarationsupdated.

- [x] RED-test real supportedHTTPchain thenimplement fixeddescriptor/router/WebBoundary:
  localprefix+HTTPS bootstrap/login->candidatePOST->prepare->GET/HEAD->cancel usingactualsources/
  journal/commondependency, notmocksuccessservice. Exact4096POST andzeroGETHEADbodies beforeauth,
  chunked/nolength/duplicates/unknown/query/path/method/media/Origin/CSRF/headernegatives. No
  bearer serviceclient route. Compareinitial/replaybodybytes, GET/HEADsameheaders/noHEADbody,
  frozencommand/currentGETstates, prefixonce, failedpublication201 andexpiry409commit.
  Sourceabsent503 leavesowner/candidateworking; candidatePOST neverstages/publishes. Assert
  oneactualregistry construction, nofeaturekeys/types/imports inserver.

- [x] FocusedRED/GREEN whileiterating, thenonecoveringrun: allnewprepare/dependencytests,
  acceptedTask9source/IPC, existingfirstparty/router/owner/candidate/domain/event/schema/opsaudit/
  clientconformancefamilies. Discoverexactpathswithrg. Changed/newRuff, fournew+twoupdatedschema
  parity, unchanged44port/oldcandidate/B/S/lowercomposer hashes andgitdiffcheck. Parentownsfull
  regression afterfreeze; no duplicatereviewersuites.
- [x] Self-reviewactualdiff/newfiles, report .superpowers/sdd/resumption-plan/task-10-report.md
  withexactfiles/RED/GREEN/failures/commands/covering/limitations; freezesourceforindependentreview.
  No commit/push.

Actualfirst-onlyprepare/cancel/source/journal/HTTP/recovery isthisslice, notdeployment success.
Next signedreceipt/non-successoneuse plusactualpostconditions/installation/qualification/binding
remain beforesemanticacceptance+budgetsettlement/scheduler/fullbrowserjourney. No placeholder
successfacade maybridge them.

### Task 11: Version the public receipt verifier's control dependency candidate

Execute after Task10A/B/C acceptance. This independently verifiable build-input step prepares the
public verifier without changing historical T089 files or installing packages during another task.
Contract: `contracts/deployment-receipt-dependencies.md` (complete exact fields/pins/closures/errors).

**Files:** Create `deploy/locks/requirements-control-plane-receipt-v1-linux.lock`,
`deploy/manifests/python-wheel-artifacts-receipt-v1.addendum.json`,
`deploy/locks/verify_receipt_dependency_candidate.py`,
`deploy/tests/test_receipt_dependency_candidate.py`. No other production/dependency files change.

**Interfaces:** Consume the four exact fixed historical files in contract§2 and existing read-only
`deploy.locks.verify_build_inputs.parse_lock(Path)->dict`. Produce
`verify_candidate(root:Path)->dict` with the exact inert summary and `ReceiptDependencyError` fixed
code/text from§4. Candidate lock is a complete18package profile; artifact metadata alone does not
prove wheel bytes or final image inclusion. No shared-core authority or runtime import is added.

- [x] Snapshot the four historical inputs and accepted B/S/source baselines. Parent records exact
  pre-task hashes and confirms no implementation/test writer remains active. Tests use real copied
  inputs under temporary fixture roots, not positive mocked digests or altered original manifests.
- [x] Write a first RED test requiring the new actual verifier and two candidate files. The
  missing implementation must produce an import/file failure, not a skip or hardcoded successful
  summary. Core positive assertions are:

  ```python
  result = verify_candidate(repo_root)
  assert result["status"] == "candidate_not_release_qualified"
  assert result["package_count"] == 18
  assert result["target_platforms"] == ["linux/amd64", "linux/arm64"]
  assert result["lock_sha256"] == sha256(
      (repo_root / "deploy/locks/requirements-control-plane-receipt-v1-linux.lock").read_bytes()
  ).hexdigest()
  ```

- [x] Create the complete sorted lock by retaining every actual base requirement/hash and adding
  only `pynacl==1.6.2` with the two exact contract§3 hashes. Create the exact10field addendum with
  four immutable base refs, actual candidate lock hash/size and exact pinned PyNaCl wheel records
  whose sole difference from base is control-plane usage. Reuse pinned records; no resolution,
  network, download or claims of freshly verified archive bytes. Preserve source/license fields.
- [x] Implement the five ordered verification steps in contract§4 using fixed descendant paths,
  bounded real reads, strict JSON, existing lock grammar, exact base-pins/delta/artifact relationships
  and per-platform closure/hash-use equality. No application code imports this build tool. Optional
  main has no arguments and prints only the exact inert summary/fixed error. GREEN the first test.
- [x] Add RED/GREEN mutations for each fixed base (even with recomputed claimed ref), every closed
  addendum structure/type/limit, path/symlink/nonregular input, metadata mutation, duplicate/missing/
  swapped architecture, provider substitution, malformed/changed/extra/missing lock requirement
  and unused hash. Every rejection asserts `ReceiptDependencyError` fixed message and no canary
  reflection; an external-path canary test proves it is never opened. Valid-fixture rehashing may
  update candidate refs only, never expected baseline pins. Test actual content, not file existence.
- [x] Run the new focused suite; verify unchanged snapshots and existing aggregate membership.
  Run deploy/tests/test_receipt_dependency_candidate.py plus the existing
  deploy/tests/test_build_input_verifier.py and deploy/tests/test_build_input_lock_verifier.py once,
  static-check new Python and git diff --check. Record commands/results and
  all new artifact/source hashes. No old generator/aggregate rewrite, wheel download/install,
  image build, copyright decision or push. Report
  `.superpowers/sdd/resumption-plan/task-11-report.md`, freeze and obtain independent spec/quality
  review. Task11 does not close T081/T084/T087 or establish receipt verification implementation.

### Task 12: Verify canonical first-stage receipts with public Ed25519 keys

Execute after Task11 acceptance, with no other current-turn dependency writer/test. The explicitly
preserved pre-resumption speech-test process below is not a dependency-install blocker. Contract:
`contracts/deployment-receipts.md`, including exact common/stage/trust bytes and section8 APIs.
The dependency contract remains binding. This is the pure verification prerequisite, not receipt
admission, operator execution, installation, qualification or a web endpoint.

**Files:** Create `app/deployment/receipt_contracts.py`, `app/deployment/receipt_crypto.py`,
`app/deployment/receipt_schema_exports.py`; `app/tests/test_deployment_receipt_contracts.py`,
`app/tests/test_deployment_receipt_crypto.py`, `app/tests/test_deployment_receipt_schema_exports.py`;
`app/tests/fixtures/deployment-receipt-ed25519-v1.json` and developer-only
`app/tests/helpers/receipt_ed25519_fixtures.mjs`; the two structural artifacts
`schemas/v1/deployment/receipt-stage-v1.schema.json` and
`schemas/v1/deployment/public-trust-set-v1.schema.json`.
Modify only `app/requirements.txt` to add the explicit development PyNaCl pin. Parent snapshots it.
No candidate/prepare/source/domain/port/API/HTTP/old-schema/DDL or historical release-input edit.

**Interfaces:** exact pure signatures from wire§8. `parse_receipt(bytes)->dict` owns intrinsic
validation without request/U/signature authority; `parse_trust_set(bytes,*,profile)->dict` is still
inert. `verify_receipt(bytes,*,request_bytes,trust_bytes,trust_sha256,profile)->dict` reparses every
actual byte document, authenticates its signature before typed request-binding classification,
then checks every request relation/time bound. `verify_detached(key,message,
signature)->bytes` uses PyNaCl1.6.2 VerifyKey and checks returned bytes, not truthiness.
`ReceiptWireError` is defined in receipt_contracts; local import of crypto only inside verify_receipt
keeps structure-only parse imports independent of PyNaCl. Structural exports never grant authority.

Private `_ReceiptRequestMismatch(ReceiptWireError)` retains the same receipt_invalid code/message;
one `_check_request_binding(receipt,request,*,profile)->None` implements the wire§8 relation
partition. Verify first, then propagate that subtype for later importer409; intrinsic/trust/time
failures remain ordinary wire errors. No duplicated caller relation checker or third public code.

- [x] Record installed Python/CFFI/pycparser versions without inspecting credentials. Confirm the
  candidate metadata/profile is accepted and no other current-turn writer/test is using the shared
  environment. Parent identified the53-hour-old pre-resumption browser-speech-input.test.mjs /
  fixtures/speech_server.py process tree (root95119,node95122/95396,python95835) as the already
  documented preserved test. Do not terminate/change/wait for that unrelated tree. It does not
  use PyNaCl; adding only the absent package with --no-deps and unchanged CFFI/pycparser is allowed.
  Recheck that PyNaCl is still absent and stop if any existing package would be replaced.
  Obtain the compatible macOSarm64CPython3.12 PyNaCl1.6.2 wheel using the exact official filename/
  SHA256 from the primary-source report; verify actual downloaded bytes before installation. Use
  isolated temporary staging and hash-required/no-dependencies installation into the existing
  project venv. No unpinned resolution or existing package replacement. Record actual hash/version/
  import; add the direct dev requirement only. If native artifact is unavailable/incompatible,
  do not skip crypto tests or claim verification; report the exact dependency issue to parent.
- [x] Add RED tests for both parsers, intrinsic closed-field/type/b64/calendar/outcome rules and
  fresh-process structure-only import without nacl. Then implement schemas and bounded parsing
  using existing canonical_json/WireLimits/ref/B32/profile helpers. Integer and textual roundtrip
  checks stay exact; signature64 decoding is new without weakening32byte decoding. Use no dynamic
  import selected by a receipt and no source/database/current-time dependency. Basic assertions:

  ```python
  value = parse_receipt(fixture["receipt_utf8"].encode("utf-8"))
  assert canonical_json(value) == fixture["receipt_utf8"].encode("utf-8")
  bad = {**value, "unknown": "must-not-be-reflected"}
  with pytest.raises(ReceiptWireError, match="^receipt_invalid$"):
      parse_receipt(canonical_json(bad))
  ```

- [x] Preserve all five RFC8032§7.1 PureEd25519 public-key/message/signature vectors, including the
 1023byte message; no private seeds and no ph/ctx substitution. Add RED verification/tamper/length/
  scalar/point rejection tests, implement VerifyKey detached public verification, then GREEN with
  the actual installed native library. Fixed error codes distinguish malformed input from actual
  BadSignatureError, not arbitrary raw provider exceptions. No homemade curve arithmetic.
- [x] Create the developer-only Node Ed25519 fixture generator and capture its public-only output
  into the static JSON fixture. It accepts no external key/path/network and never writes/prints a
  private key. Generate one isolated ephemeral test key in memory; emit actual canonical request/U/
  receipt/preimage, public key, signature and expected validity label. Include both deployment
  profiles, every allowed outcome arm and correctly signed invalid cross-request/profile/tuple/
  key-adapter/time/fact cases. Do not use real operator keys or add signing to application modules.
  A public-only verify mode reads fixture JSON on stdin and checks the same preimages/signatures
  with Node crypto. Both implementations independently reconstruct the exact ADR008 preimage;
  the Node test canonicalizer is fixture-only and is never imported by production code.
  Implement the exact developer-only `--session` protocol in wire§9 as well: one ephemeral
  memory-only key/U followed by bounded exact-request stdin cases, finite64case/128KiBframe caps,
  no arbitrary overrides/external key/path/network. Reuse the same fixture builder, derive valid
  times from request.created_at and exercise two distinct actual make_request outputs under one U.
  Test ordering/unknown input/bounds/EOF and finite owned-child cleanup in the crypto test file.
  This permits later real service integration without a static nonce/time substitution or a
  production signing interface; no separate test service or file is added.
- [x] Add RED relational tests using actual static signed fixtures, then implement verify_receipt:
  reparse accepted request bytes, independently compare U pin, resolve exact key/adapter/profile,
  canonicalize all22 unsigned fields, call actual crypto and compare returned message bytes, then
  use the one private binding helper for identities/StageResult tuples and check time inequalities.
  Test validly signed mismatch→private subtype; tampered mismatch→signature error; intrinsic
  malformed/fixed-arm/trust/time failures→ordinary wire error. No
  bypass from a parsed dict or a freshly constructed type. Happy path assertion:

  ```python
  verified = verify_receipt(
      case["receipt_utf8"].encode(), request_bytes=case["request_utf8"].encode(),
      trust_bytes=case["trust_utf8"].encode(), trust_sha256=case["trust_sha256"],
      profile=profile,
  )
  assert verified == parse_receipt(case["receipt_utf8"].encode())
  # No authoritative domain entity, installation, source lease or lifecycle write occurs.
  ```

- [x] Independently mutate each signed field without resigning; all must fail. Validly signed bad
  relational cases must also fail, not merely tampered signatures. Cover all field/array/type/bounds,
  duplicates/BOM/whitespace/Unicode/pad bits/nilUUID, cross-request identities, trust uniqueness,
  all outcome/observed-time variants and no default profile or grace. Clock independence is explicit:
  pure validity is unchanged by current host time; actual import-time expiry belongs to the consumer.
- [x] Export exactly two named structural schemas, compare fresh regeneration bytes, and check
  shape-validation parity with runtime on structural valid/invalid cases under FormatChecker.
  Relational/crypto cases may be structurally valid; label that distinction instead of weakening
  cryptographic checks or claiming JSONSchema authenticates signatures. Verify all existing schema
  and44port bytes plus Task9/10accepted hashes unchanged.
- [x] Run focused codec/crypto/schema tests and independent Node public verification. Run one
  covering selection including accepted prepare contracts and dependency candidate tests; static
  check new Python/Node and git diff --check. Record exact RED/GREEN/import/artifact/hash evidence
  and limitations in `.superpowers/sdd/resumption-plan/task-12-report.md`, freeze and obtain fresh
  independent spec/quality review. Parent owns the final integrated regression after freeze.
  No mounted sources, actual signing job/key, receipt admission or release gate is claimed complete.

### Task 13: Build the finite public receipt source expansion and consumed codec

Execute after Task12 acceptance. Read the complete
`contracts/deployment-receipt-sources.md` and `contracts/deployment-receipts.md`. This task creates
the exact independently testable producer/codec prerequisite. Actual retained readers, public
initializer I/O, journal migration and signer/job are separate next integrations, not placeholders.

**Files:** Create `app/deployment/receipt_source_contracts.py`,
`app/deployment/receipt_render.py`, `app/deployment/receipt_publication.py`,
`deploy/security/deployment-receipt-recipe-v1.json`,
`app/tests/test_deployment_receipt_source_contracts.py`,
`app/tests/test_deployment_receipt_source_render.py`,
`app/tests/test_deployment_consumed_codec.py`. No existing production/dependency/schema file edits.

**Interfaces:** Consume accepted Task9 `render_prepare_sources(B,S,R,I)` and Task12
`parse_trust_set(U,profile=...)`. Produce the source contract§8 four exact pure parsers and
RECEIPT_RECIPE/RECEIPT_RECIPE_BYTES/RECEIPT_RECIPE_SHA256, plus
`render_receipt_sources(B,S,R,I,Q,V,U)->ReceiptSourceArtifacts` exact frozen fields in§1.
`validate_consumed_marker(*,receipt_digest,payload)->dict` is the one pure grammar later K uses.
No parsed document or frozen result is source/currentness/consumption authority. Normalize
malformed source/wire inputs to the existing closed DeploymentSourceError, not raw values.

- [x] Write RED tests requiring exact Q and V parsing, malformed/noncanonical/unknown fields,
  bool integers, nil/duplicate IDs, bad hashes and fixed supported recipe. Implement exact source
  constants and parsers with the declared byte/depth/item/string limits. Freeze canonical Q bytes
  without a terminal newline and its actual SHA256. R remains606bytes and its accepted hash;
  do not generate a new R or version its old slots implicitly.
- [x] Write RED tests for the seven-input pure renderer using complete synthetic I/V/U inputs and
  actual frozen B/S/R/Q. Cover local/portable profiles,1/16slots and both selected Linux platforms.
  Implement ordered reconstruction: Task9 prepare artifacts unchanged; validate U and V against
  actual I/U bytes; derive J; derive K from exact E/U/J/Q/V; derive PR; append only the fixed XR
  additions to reconstructed X; derive AR last. No output hashes itself. Core assertions include:

  ```python
  old = render_prepare_sources(B, S, R, I)
  result = render_receipt_sources(B, S, R, I, Q, V, U)
  assert result.prepare_artifacts == old
  assert result.trust_bytes == U
  assert render_receipt_sources(B, S, R, I, Q, V, U) == result
  x = json.loads(old.expanded_compose_bytes)
  xr = json.loads(result.expanded_compose_bytes)
  for name, service in x["services"].items():
      if name != "control":
          assert xr["services"][name] == service
  ```

- [x] Verify control's old mounts/array order, env and dependencies are unchanged, with exactly
  five appended mounts/env pins and one new dependency. Verify all old volumes/configs/networks,
  exact five physical names/layouts/RO flags and four external configs, no collisions or arbitrary
  input fragments. The sole added service is the fixed public initializer with exact identity,
  caps/resources/network/entrypoint and only new roots. Preserve finite CPU fractions using the
  existing deterministic expansion JSON exception, not a weakened domain canonicalizer. Never
  add a dummy signer/job or claim XR is a safe whole-stack rollout on occupied slots.
- [x] Add RED/GREEN mutations of every derived relationship, wrong recipe/base/instance/trust pin,
  conflicting new/old IDs, wrong profile/adapter/key list, array shape and artifact bounds. Assert
  all PR/AR digest/size fields equal actual complete output bytes, all exact field sets and no
  back-reference cycles. Validate J/K with their independent parsers and tamper one field at a
  time. Foreign syntactically valid unavailable counterpart digests remain inert facts in those
  standalone parsers; full renderer cross-validation must reject mismatched complete inputs.
- [x] Add RED tests for consumed codec with actual canonical payload, then implement its exact
  nine fields and signature from source§5/8. Return a fresh parsed dict only, no file observation
  wrapper or consumed authority. Basic behavior:

  ```python
  raw = canonical_json(marker)
  assert validate_consumed_marker(receipt_digest=marker["receipt_digest"], payload=raw) == marker
  with pytest.raises(DeploymentSourceError):
      validate_consumed_marker(receipt_digest=foreign_digest, payload=raw)
  ```

  Cover complete decoded selector versus whole payload hash distinction, revision2 only, failed/
  unknown outcomes only, UUID/b64/calendar/null/unknown/duplicate/bounds, exact byte roundtrip and
  safe errors. No consumed marker with success, nonce, key or caller-selected instance. Test this
  codec separately from filesystem publication; no implicit new role in old validate_projection.
- [x] Add fresh-process import/behavior checks showing the pure producer/parsers require no nacl
  load, actual filesystem source, environment, mount, socket or database authority. Use real input
  bytes and independent expected structures, not mocked positive source objects. Run focused tests,
  then one covering selection of the three new files plus Task12 contracts/schema exports and the
  existing Task9 source-contract/render tests. Static-check new Python and git diff --check.
  Record complete RED/GREEN/recipe/output/source hashes and untouched B/S/R/X/old-source evidence in
  `.superpowers/sdd/resumption-plan/task-13-report.md`; freeze for independent spec/quality review.
  No public roots initialized, package/image selected, operator key generated or lifecycle admitted.

Next source I/O slice must consume these actual accepted parsers/producer rather than duplicate
their grammars. It will implement genuine retained U/J/K, receipt leases, consumed publication/
inspection and external public initialization with the narrowly planned shared primitive reuse,
followed by actual journal/HTTP admission. Pure producer acceptance does not close that dependency.

Task13 accepted within pure scope:246covering and parent112new-file tests pass, clean independent
spec/quality review. Historical clean renderer/consumed RED runs were not established; checked
implementation steps do not retroactively assert them. Explicit limitation remains in report/ledger;
no source/initializer/admission/installation/whole-story gate is closed by this result.

### Task 14: Retain actual public trust with shared bounded file/source mechanics

Execute only after Task13 acceptance. Read complete `contracts/deployment-receipt-sources.md` and
`contracts/deployment-receipts.md`. This is the first actual source-I/O slice: useful retained U
and a shared scanner/lifecycle, not stub J/K factories, initializer, receipt import or deployment.

**Files:** Modify `app/deployment/files.py`, `app/deployment/sources.py` and
`app/tests/test_deployment_sources.py` only for the scoped extraction/additive alias assertions.
Create `app/deployment/source_common.py`, `app/deployment/receipt_sources.py`,
`app/tests/deployment_receipt_source_fixture.py`, `app/tests/test_deployment_namespace_scanner.py`,
`app/tests/test_deployment_receipt_sources.py`. No other production/test/dependency/schema edits.

**Interfaces:** Consume actual FileIdentity/Directory/SourceFile/RetainedHandle/read_exact and
mounts validation plus Task12 parse_trust_set and Task13 pure source artifacts. Produce
`open_public_trust_source(*,profile,trust_sha256,protected_roots)->PublicTrustSource`, inert
`trust_bytes`, `recheck_current()->PublicSourceIdentity`, idempotent close, exact source§4 identity.
PublicTrustSource constructor/copy/pickle cannot supply authority. No placeholder other readers.

Private files.py interfaces: `_NamespacePolicy(writer_uid,primary_gid,pair_gid,final_limit,
stage_limit,payload_cap)` frozen dataclass; `_FinalEntry(name,signature)` and
`_NamespaceScan(finals:tuple,stages:int)` frozen observations; `_scan_namespace(directory,*,policy)`
returns the scan, `_open_final(directory,entry,*,policy)` returns an actual `_FinalFile` whose
`read_current()->bytes` checks held FD/name/signature and whose close releases only its FD.
Fixed policies are request(20102,20102,21201,16,32,65536),
cancel(20102,20102,21201,16,32,4096), incoming(20113,20113,21201,64,32,16384),
consumed(20102,20102,21201,16,32,4096). No manifest/HTTP-selected policy or proof callback.

Private source_common interfaces: neutral `_Source` with `_mapping_for(own)`, `_mounts()`,
`_recheck_base()` and close; `_validate_source_startup(*,profile,source_sha256,protected_roots)->str`
returns actual native platform; `_open_pinned_source(cls,*,profile,source_sha256,protected_roots,
root,name,gid,cap,required)` returns its actual retained object. Preserve current old wrapper
`_open_common` signature and its R/I checks; remove only those old-recipe checks from neutral base.
Move ObjectIdentity/_observed to source_common and re-export from sources; unchanged OutboxIdentity
shape, old factories/exact types, SlotMetadataLease and IPC logic stay in sources.py.

- [x] Write failing scanner tests using actual temporary directories/files and narrowly controlled
  ownership observations. Enumerate metadata only, cap names at final_limit+stage_limit, sorted
  hex filenames; reject unsafe unselected finals and all invalid UUID/stage names, hardlinks,
  symlinks, non-regular/empty/oversized finals and invalid owner/group/modes. Exercise16/32,
  64/32,65/33 boundaries and zero-size valid stages. Guard os.read/open_regular during pure scan:

  ```python
  scan = files._scan_namespace(directory, policy=files._INCOMING_NAMESPACE)
  assert len(scan.finals) == 64
  assert scan.stages == 32
  assert tuple(item.name for item in scan.finals) == tuple(sorted(expected_names))
  assert payload_reads == []
  ```

  Implement private scanner/final reader from existing file primitives. A final handle captures
  initial signature/FD, rechecks the original named entry before/after bounded whole-byte reads,
  rejects changed membership/metadata observed during inventory and closes on every failed open.
- [x] Preserve `inspect_namespace(directory,cap)` exactly as eager old20102/16/32 compatibility
  wrapper with its supplied old cap and `(tuple[(name,bytes)],stage_count)` return. Do not change
  old cap API, role grammar, order or cleanup semantics. Assert actual old files are read and
  concurrent swaps fail; run existing source-file tests after extraction.
- [x] Extract neutral source lifecycle without IPC/crypto/render/initializer imports. Retain own/
  mandatory built-in/configured root continuity and optional-root alias distinction. One private
  build-owned optional list contains old T/E/outbox/xs01..xs16 plus the exact five receipt roots
  from source§2. New roots when mounted affect alias safety only, not contents/readiness/continuity.
  Add old T/E tests: observed new-root backing alias denies, removing a nonoverlapping optional
  root does not invalidate an existing E; missing configured protected roots always deny.
- [x] Add real retained U fixture from exact rendered synthetic I/V/U and actual temporary files;
  only OS metadata/mount observations may be controlled. Open fixed public root0:20102/0750 and
  trust-set.json0:20102/0440 singlelink on genuine observed RO source. Parse actual U/profile/pin,
  retain its FD/root/protected handles and expose unchanged bytes/identity after currentness.
  The five-field FileIdentity and two-field ObjectIdentity must not be conflated. Test:

  ```python
  source = open_public_trust_source(profile=profile, trust_sha256=sha256(U).hexdigest(),
                                  protected_roots=protected_roots)
  assert source.trust_bytes == U
  before = source.recheck_current().as_dict()
  assert before['source_kind'] == 'trust'
  before['root']['inode'] = 0
  assert source.recheck_current().as_dict()['root']['inode'] != 0
  source.close()
  with pytest.raises(DeploymentSourceError):
      source.recheck_current()
  ```

- [x] Cover bad U/pin/profile, root/file same-byte replacement, byte/signature/metadata change,
  symlink/hardlink, RW inversion, nested mounts/device/backing aliases, platform drift and FD cleanup
  at each failed open. J/K/T/E absence/nonoverlapping content changes and unrelated mount order
  cannot block U. Prove no old IPC metadata opened, no source constructor/copy/pickle authority,
  no PyNaCl import or signature verification during structure-only source use.
- [x] Run one final covering command on frozen source:

  ```sh
  /Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -B -m pytest -q -p no:cacheprovider app/tests/test_deployment_namespace_scanner.py app/tests/test_deployment_receipt_sources.py app/tests/test_deployment_source_files.py app/tests/test_deployment_sources.py app/tests/test_deployment_publication.py app/tests/test_deployment_prepare_publication.py app/tests/test_deployment_prepare_api.py --tb=short
  ```

  Run Ruff/format on new/changed files and git diff --check; compare original B/S/R/pure outputs/
  schemas/old API against frozen predecessor hashes. Source helper files intentionally change only
  through this exact diff, never falsely claim their old hashes remain unchanged. Report complete
  RED/GREEN/commands/output/limitations in `.superpowers/sdd/resumption-plan/task-14-report.md` and
  freeze for independent spec/quality review. Parent full regression follows acceptance as scoped.
  No initializer image selection/build, source host mounts, signer/private key, journal migration,
  installation or final Linux/two-host qualification is part of this task.

Task14 scoped acceptance: initial independent review found three contract defects; fixround1
corrected all three and added the missing fresh-process import/open proof. Independent scoped
rereview accepted all four findings with no new breakage. Final188covering tests plus parent6
original-defect regressions pass; inherited warning retained. Parent post-fix full regression:
5004passed,1LinuxSO_PEERCREDskip,369subtests,1inheritedwarning,419.26s,exit0,147hashes unchanged.
No Linux/install/whole-story gate is closed.

### Task 15: Read finite incoming receipts through actual retained file leases

Execute after Task14 acceptance; read complete `contracts/deployment-receipt-sources.md` and
`contracts/deployment-receipts.md`. Build actual J and selected receipt file leases, not an import
endpoint, signature/admission authority, automatic inbox processing or an incoming writer.

**Files:** Modify `app/deployment/receipt_sources.py`,
`app/tests/deployment_receipt_source_fixture.py`, `app/tests/test_deployment_receipt_sources.py`.
Create `app/tests/test_deployment_receipt_file_leases.py`. Task14 shared files/base, pure contracts,
old T/E, SQL/API/schema/dependency/initializer files remain unchanged unless a concrete interface
defect is separately ruled on and snapshotted by parent.

**Interfaces:** Consume Task14 `_scan_namespace`, `_open_final`, actual neutral pinned source,
Task13 `parse_ingress` and Task12 structure-only `parse_receipt`. Add exact source§4 factory
`open_receipt_ingress_source(*,profile,receipt_recipe_sha256,receipt_instance_sha256,
ingress_sha256,protected_roots)->ReceiptIngressSource`. Its `ingress_bytes` are inert originalbytes;
`recheck_current()->ReceiptIngressIdentity`, `list_available_receipt_digests()->tuple[str,...]`,
`open_receipt(receipt_digest:str)->ReceiptFileLease`, close idempotent. Identity/as_dict exact§4.
Lease has original `receipt_bytes`, B32 `receipt_digest`, frozen `file_identity`, idempotent close
and `recheck_current()->FileIdentity` exactly§7. No public constructor/copy/pickle grants a lease.
Add `receipt_sources.DeploymentReceiptInvalid(DeploymentSourceError)` exactly source§7, preserving
closed code/message deployment_receipt_invalid. Only intrinsically invalid selected bytes after
safe current FD/name/hash checks receive it; unsafe/missing/drifted/J-mismatched sources do not.

- [x] RED tests open genuine J-only+inbox fixture with actual Task13 output. Source is root0:21201/
  0750+ingress.json0440/RO; incoming root and receipts child are20113:21201/0750/RO as viewed by
  control. Validate compiledQ/V/pin/profile/exact source grammar. Implement factory with owned
  retained handles and fixed paths. No U/K/T/E contents, readiness, slot metadata or positive
  absence evidence is needed; optional mounts only affect alias safety.
- [x] Implement one private `_scan_receipts()->(ReceiptIngressIdentity,_NamespaceScan)` that checks
  source/root/child/device/mount/protected continuity and exact child membership before/after
  metadata scan. Public recheck/list select its results without recursive public calls. With64
  valid finals and32validstages, listing returns B32s in filenamehex order without reading any
  payload or stage;65/33 or one unsafe unselected entry rejects. Test explicit assertions:

  ```python
  values = source.list_available_receipt_digests()
  assert values == tuple(expected_b32_in_filename_hex_order)
  assert len(values) == 64
  assert payload_reads == []
  ```

  A metadata-valid final with invalid payload may list; selecting it must fail. Do not turn
  metadata enumeration into signature verification or silently skip malformed metadata.
- [x] RED selected-file tests use Task12 public fixture bytes, not a positive source stub. Decode
  exact B32 selector to lowerhex filename internally; no path/filename input. Open actual final FD,
  retain signature and original whole bytes/hash, call parse_receipt and bind actual J's instance,
  origin/profile/U digest. No request/nonce equality, signature validation, clock/deadline or DB
  disposition can be decided at J. Bracket selected read with source and named-entry checks:

  ```python
  lease = source.open_receipt(receipt_digest)
  initial = lease.file_identity
  assert lease.receipt_bytes == receipt_bytes
  assert lease.recheck_current() == initial
  assert lease.receipt_digest == receipt_digest
  source.close()
  with pytest.raises(DeploymentSourceError):
      _ = lease.receipt_bytes
  lease.close()
  lease.close()
  ```

- [x] Exercise wrong padding/padbits/type/slash/hex selectors, missing final, filename/full-byte
  hash mismatch, BOM/duplicate/noncanonical/unknown receipt fields, structurally valid foreign
  J bindings, bad metadata and selected signature/byte changes. A structurally valid unverified
  signature stays an inert observation; guard verify_receipt/nacl import to prove no hidden check.
  Assert intrinsic invalid wire receives DeploymentReceiptInvalid only after whole-digest and
  currentness checks, while unsafe/hash/J-binding failures remain other source-family errors.
  No lease escapes either failure; these tests preserve later wire400/source503 classification.
- [x] Fault/swap tests change held/named file, root, namespace, source pin, owner/link/mode or same
  length bytes at every open/read/recheck boundary. Recheck never refreshes/rebinds; failure raises
  closed source errors without leaking payload/path/key text. Owner close invalidates leases but
  each lease owns only its FD; failed creation closes FD, copied observations cannot reopen it.
  Keep platform/RO/nested/backing/protected alias tests and malformed unselected metadata denial.
- [x] Run one final covering command on frozen code, then scoped Ruff/format/diffcheck:

  ```sh
  /Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -B -m pytest -q -p no:cacheprovider app/tests/test_deployment_receipt_sources.py app/tests/test_deployment_receipt_file_leases.py app/tests/test_deployment_namespace_scanner.py app/tests/test_deployment_receipt_contracts.py app/tests/test_deployment_sources.py --tb=short
  ```

  Report exact changedfiles/RED/GREEN/commands/output/source hashes and unsupported-host limits in
  `.superpowers/sdd/resumption-plan/task-15-report.md`; independent review precedes successor.
  No native host mount/Docker, signer, incoming publication, U key enrollment, SQL import or actual
  receipt authenticity is established by these source fixtures.

Task15 scoped acceptance: independent review found a rejecting-parser currentness gap; fixround1
reuses the actual lease recheck before classifying either parse outcome. Fresh scoped rereview:
onefinding addressed, no newbreakage. Final249covering tests4.78s and parent7targeted cases0.86s
pass; fourfinal/144untouchedhashes verified. Prior247/118results are pre-fix. No signature/import/
admission/installation/Linux/whole-story authority is inferred. Task16 may proceed.

### Task 16: Inspect and publish actual consumed projections through retained K

Execute after Task15 acceptance; read complete `contracts/deployment-receipt-sources.md`.
This adds real K inventory/publication with shared no-clobber mechanics, not durable consumption
authority, signature verification, external installation or a third role in old E APIs.

**Files:** Modify `app/deployment/receipt_sources.py`, `app/deployment/receipt_publication.py`,
`app/deployment/publication.py`, `app/tests/deployment_receipt_source_fixture.py`,
`app/tests/test_deployment_receipt_sources.py`. Create
`app/tests/test_deployment_consumed_publication.py`, `app/tests/test_deployment_consumed_inspection.py`.
No SQL/HTTP/initializer/old schema/recipe/base/dependency edits. Retain old test semantics.

**Interfaces:** Add exact factory `open_consumption_exchange_source(*,profile,
receipt_recipe_sha256,receipt_instance_sha256,consumption_exchange_sha256,protected_roots)`.
ConsumptionExchangeSource exposes inert `consumption_exchange_bytes`,
`recheck_current()->ConsumedIdentity`, `inspect_consumed()->tuple[ConsumedFileObservation,...]`,
`publish_consumed(*,receipt_digest,payload)->ConsumedPublicationObservation`, idempotent close.
All frozen fields/identity mappings exactlysource§4–5. Consumed observation is
`(receipt_digest,payload,file_identity)`; publication is
`(role='consumed',receipt_digest,payload_sha256,size_bytes,file_identity)` in receipt_publication.py.
Consume the one Task13 `validate_consumed_marker` grammar and Task14scanner/finalFD primitives.

Shared publication.py private extraction: `_existing_for_policy(directory,filename,payload,*,policy)`
returns actualFileIdentity; `_stage_payload(directory,payload,*,policy)->_StagedFile` owns FD/name;
`_commit_stage(directory,stage,filename)->None` does no-replace/directory fsync. Keep existing
`_rename_noreplace`/`_write_all` monkeypatch locations and `_existing(directory,filename,payload,cap)`
old20102wrapper. Policies are fixed build-owned objects; no source-check/proof callback parameter.

- [x] RED K factory/inventory tests use real pinnedK+consumed roots independently of U/J/T/E.
  Validate source0:21201/0750/0440RO and channel20102:21201/0750RW, Q/V/profile/currentness and
  exact fixedlayout. Implement private `_inspect_inventory()->(ConsumedIdentity,tuple)` using
  actual source/root/namespace pre/postchecks, one metadata scanner and bounded actual finalreads.
  It never invokes public recheck recursively; public recheck/inspect select one result each.
- [x] Inventory has at most16 immutable observations sortedfilenamehex. Marker.receipt_digest
  must equal filename-decoded selector, but marker payload hash need not equal receipt digest:

  ```python
  observed = source.inspect_consumed()
  assert observed[0].receipt_digest == receipt_digest
  assert observed[0].payload == marker_bytes
  assert sha256(marker_bytes).digest() != parse_base64url_32(receipt_digest)
  assert source.inspect_consumed() == observed
  ```

  Cover unknown/stale/malformed/foreign-selector markers,17final/33stage, size/link/mode/owner,
  root/file swaps, closedsource, actual fixed source identity and no stage-byte reads. Guard public
  recheck during private inventory to detect recursion. Listing cannot invent DB acknowledgement.
- [x] RED publication tests distinguish actual durable file observations from authority. Extract
  only mechanical stage/existing/commit helpers; old/new concrete wrappers visibly perform exact
  source-type/codec/currentness admission. `_stage_payload` creates exclusive0600, writesfully,
  chowns21201, chmods0440, fsyncs and validates expected UID/signature/name. Explicit concrete
  source recheck occurs after staging immediately before commit; `_commit_stage` uses only fixed
  Linux renameat2(RENAME_NOREPLACE), tolerates EEXIST only for later exact winner verification,
  then directoryfsync. Closing stages never unlinks; unsupported semantics fail closed.
- [x] New K wrapper verifies canonical marker before I/O, inventory/capacity and finalname from
  receipt selector, does source checks before/after operations, and verifies actual existing bytes
  with file+directoryfsync before returning observation. Same-byte replay at16final/32stage uses
  no newstage; different bytes never overwrite.17th/33rd invalid namespace denies even replay.
  EEXIST race retains staged file and accepts only exact winner bytes. Basic evidence assertion:

  ```python
  result = source.publish_consumed(receipt_digest=receipt_digest, payload=marker_bytes)
  assert result.role == 'consumed'
  assert result.receipt_digest == receipt_digest
  assert result.payload_sha256 == sha256(marker_bytes).hexdigest()
  assert result.size_bytes == len(marker_bytes)
  assert source.inspect_consumed()[0].file_identity == result.file_identity
  ```

- [x] Inject short/zero writes, chown/chmod, file/directoryfsync, precommit drift, namedstage swap,
  rename unsupported/EEXIST and postcheck failures. Inspect exact leftover stage/final state;
  failed durability cannot report success. No cleanup/link/replace fallback. Keep old request/
  cancel bytes/codec/observation/type checking and actual same-writer Task10 publication tests;
  consumed role stays invalid in old validate_projection/publish. No stub/subclass grants source.
- [x] Run one final frozen covering then scoped Ruff/format/diffcheck and predecessor byte checks:

  ```sh
  /Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -B -m pytest -q -p no:cacheprovider app/tests/test_deployment_consumed_codec.py app/tests/test_deployment_consumed_publication.py app/tests/test_deployment_consumed_inspection.py app/tests/test_deployment_receipt_sources.py app/tests/test_deployment_receipt_file_leases.py app/tests/test_deployment_publication.py app/tests/test_deployment_prepare_publication.py --tb=short
  ```

  Full evidence/frozen hashes in `.superpowers/sdd/resumption-plan/task-16-report.md`, independent
  review before successor. A missing acknowledged consumed final can only be recognized by later
  actual DB-aware consumer; this layer cannot repair, reconsume, erase durable history or release
  a reservation. No actual Linux/image/two-host qualification claimed from substituted syscalls.

Task16 accepted after I1 ordering correction and clean independent scoped re-review. Final
seven-file covering: 280 passed, one inherited warning; parent four late-read regressions pass.
All seven final and 143 untouched predecessor hashes verified; original 276/111 runs are pre-fix.
M1 named-stage test specificity and M2 inherited warning remain deferred for final review.
No source observation creates DB consumption, installation, or Linux/image qualification.

### Task 17: Initialize only the five new public receipt roots

Execute after Task16 acceptance; read full `contracts/deployment-receipt-sources.md`. Implement
the fixed external public initializer and share old mechanical file helpers. Do not invoke the
old initializer, touch IPC generations/slots, generate signing keys, build/run images or apply XR.

**Files:** Create `app/deployment/public_init_files.py`,
`app/operations/deployment_receipt_public_init.py`,
`app/tests/test_deployment_receipt_public_init.py`. Modify
`app/operations/deployment_prepare_init.py` only to retain its private helper wrappers over shared
mechanics; extend `app/tests/deployment_receipt_source_fixture.py`. No old orchestration, topology/
recipe/base/DDL/HTTP/SQL/dependency/image edit. Snapshot all current existing bytes before dispatch.

**Interfaces:** `initialize_receipt_public_sources()` has no parameters and returns exactly
`{trust_sha256,ingress_sha256,consumption_exchange_sha256}` from actual verifiedPR. Fixed module
main rejects extra arguments and emits closed diagnostics, never configurable path/UID/capabilities.
Share `_read_at(directory,name,*,cap,modes)`, `_release(relative,cap)`, `_empty(directory)`,
`_install_source(directory,name,raw,gid)`, `_install_namespaces(directory,*,names,uid,gid)` in
public_init_files; old wrappers retain signatures/sequence, oldoutbox namespaces('cancelled',
'requests') order/UID20102/GID21201. New module imports no old initializer or IPC code.

New private `_PublicInputFile.open(directory,name,*,cap,modes)` owns retained regularFD/signature,
`read_current()->bytes` checks original FD/name/whole bytes, close releases its FD;
`_ReleaseInput.open(relative,cap)` also owns validated ancestorhandles. Shared old byte helpers
open/read/close these primitives with unchanged accepted boundaries. New initializer
`_open_inputs()->_ReceiptInitInputs` retains four inputfiles and B/S/R/Q releasefiles/ancestors,
`recheck_current()->None` repeats actual metadata/bytes/exact4filemembership, close closes all.

Test fixture `deployment_receipt_source_fixture.py` additionally exposes
`snapshot_targets()->immutable comparable value` recording exact target names/metadata/inodes/bytes,
and `make_partial_source()->None` that corrupts only its own temporary source for a negative test.
These are test helpers, never parameters or callbacks into the production initializer.

- [x] RED tests require Linux actual effectiveUID0 and fixed roots/input/releasepaths from source§3.
  Exercise using real temporaryfiles/descriptors and controlled low-level observations only; never
  run sudo, mounts, Docker or actual host initialization. Four configs are0:0/0440 parent0750;
  release files0:0/0444|0644 with0750|0755 ancestors beneath fixed /opt/deeptwin. Individual config
  files may be RO bind mounts: verify each file against its own relevant mount, not parentdevice.
- [x] Share mechanics without source/core duplication; new retained inputs survive pure render
  until final verification. Validate actual PR exactly against Task13render(B,S,R,I,Q,V,U), all
  file hashes/native platform and V I/Urelations. No cwd/env/CLI authority. Use no private seed,
  signer possession/crypto, old T/E reader or slot absence claim. PublicU is input, not generated.
- [x] Preflight ALL five new RWmounted roots and release/inputRO boundaries before any write;
  reject nested/mutual identity/backing aliases. Only genuinely empty root0:0/0755 can initialize.
  Existing source roots verify exactfile/bytes/mode; existing channels verify exactchild/ownership
  and complete validfinals using common scanner/read/receipt-or-consumed codec. Incoming64 and
  consumed16 bounds apply; any stage/extra/partial/handed-off-empty root inhibits without repair.
  No assertion of hidden old-root alias safety when oldroots are not mounted; final topology and
  control reader checks remain separate gates. Tests snapshot every target before rejected input:

  ```python
  before = fixture.snapshot_targets()
  fixture.make_partial_source()
  partial = fixture.snapshot_targets()
  with pytest.raises(DeploymentSourceError):
      initialize_receipt_public_sources()
  assert fixture.snapshot_targets() == partial
  assert before != partial
  ```

- [x] Recheck retained inputs/relevant mounts immediately before effects and across commits.
  Initialize only emptyroots: exclusive stage/no-replace/sourcefilefsync/directoryfsync, child
  create/fsync before20113or20102 ownershiphandoff. If intentional metadata changes invalidate a
  handle, close/reopen with declared finalmetadata; never mutate retainedidentity in place. Keep
  newchannel ordering and oldoutbox/source wrapper behavior exact. Finalverify all inputs, mounts,
  source/channels and retainedfiles before returning the three digests equal toPR.
- [x] Fault tests at each create/write/chown/chmod/file/directoryfsync/sourcecommit/sourcecheck
  verify honest partialvolume states, no cleanup/overwrite/multivolumeatomicity claim. Completed
  roots verify-only; a later run may initialize still-genuinely-empty roots, but partialroot blocks.
  Preserve incoming/consumed validfinal byte+inode exactly;65/17, malformed digest/grammar, bad
  metadata/mount, config/release swap or changedinput during effects cannot return success.
- [x] Trap oldinitializer/IPC imports and initialization/generation/acquire calls. Assert actual
  opens remain fixed five targets, input/releasefiles and necessaryancestors; deny any oldT/E/
  outbox/IPC/data/session/privatekey open. Existing credential/slotgeneration/initializer tests
  run unchanged. Pure marker grammar has no instance field: bind through actualK, never invent
  a field or claim source alone knows DB disposition. Actual complete capset is not inferred from
  effectiveUID0; emitted container restriction remains a packagingqualification requirement.
- [x] Run one final frozen covering plus scoped Ruff/format/diffcheck and unchangedoldartifact
  verification:

  ```sh
  /Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -B -m pytest -q -p no:cacheprovider app/tests/test_deployment_receipt_public_init.py app/tests/test_deployment_prepare_init.py app/tests/test_deployment_receipt_source_render.py app/tests/test_deployment_source_render.py app/tests/test_deployment_consumed_inspection.py deploy/tests/test_ipc_root_initializer.py --tb=short
  ```

  Report full RED/GREEN/commands/output/frozen source/effect limits in
  `.superpowers/sdd/resumption-plan/task-17-report.md` for independent review. Parent runs full
  new+old source/prepare integration after freeze. Final images/config ownership and safe external
  rollout that never reruns old occupied-slot initialization remain mandatory; XR whole-stack
  application is not a safe restart algorithm and is not authorized by these passing tests.

### Task 18: Add pure v2 command/marker codecs and immutable receipt record shapes

Execute after Task17 acceptance. Read complete `contracts/deployment-receipt-journal.md` and
receipt wire/source contracts; this is a structure-only prerequisite for the actual v2 migration
and same-service importer. It must not install v2, admit a receipt, publish a marker or create a
runtime authority merely because a value validates.

**Files:** Create `app/deployment/prepare_v2_contracts.py`,
`app/deployment/prepare_v2_schema_exports.py`, `app/domain/deployment_receipt.py`;
`app/tests/test_deployment_prepare_v2_contracts.py`,
`app/tests/test_deployment_prepare_v2_schema_exports.py`,
`app/tests/test_deployment_receipt_domain.py`;
`schemas/v1/deployment/prepare-api-v2.schema.json`,
`schemas/v1/deployment/cancellation-v2.schema.json`.
Modify `app/domain/refs.py`, `app/domain/schemas.py`, `app/domain/schema_exports.py`,
`schemas/v1/domain-envelopes.schema.json` only for two new registered kinds/body variants.
Existing domain/schema tests may gain exact assertions; parent snapshots any such file first.
No accepted v1 prepare/candidate/receipt/port schema bytes, SQL/records/lifecycle/service/HTTP,
old source/publisher/dependency/initializer changes.

**Interfaces:** journal§9 exact `parse_cancel_v2(request_id,value)->dict`,
`parse_receipt_import(request_id,value)->dict`,
`parse_cancellation_v2(*,request_digest,payload,profile)->dict`,
`cancellation_v2(request,transitioned_ms,*,profile)->bytes`. Same closed DeploymentPrepareError
family; plain return values remain inert. New schema exporter follows existing exported_schemas/
write_schemas pattern with distinct prepare-api-v2/cancellation-v2 URNs and fixed paths. New domain
module exposes `receipt_content_schema()`, `consumption_content_schema()`,
`validate_receipt_body(body)->None`, `validate_consumption_body(body)->None`, consumed by existing
normal ImmutableRecord validation/export. These structural functions perform no store/source read.

- [ ] Snapshot permitted existing files and all old schema/B/S/R source baselines. RED closed
  input tests reject missing/extra/bool/noncanonical UUID/B32/type/size/depth values, route UUID
  mismatch and unsupported revisions. Valid cancel/import parse1..3, but do not claim each is
  currently eligible; successful stored cancel/import state matching remains the later service.
  Reuse accepted canonical/wire/time/ref helpers with no second JSON canonicalizer.
- [ ] RED marker tests require exact v2 schema/domain, actual profile/instance/origin/request
  digest and strict revision2|3, exact eight fields/cap4096/calendar. Implement the one parser and
  revision3-only emitter using an actually parsed accepted request, then GREEN. Existing v1
  parser/emitter/schema remain2-only and byte-identical. No dependency on the future v2 publisher;
  it will call this parser locally, avoiding prepare_contracts→publication import cycles.
- [x] RED schema cases cover current GETv2 five states/revision1..3 and exact nullable receipt/
  consumption state combinations, historical prepare/cancel receipts and new revision3/import
  receipts, strict request inputs and inherited closed errors. Current GET always has two new
  fields; frozen old command receipts never gain them. Reuse old structural helpers with fresh
  dicts and no mutation of old schema globals. Structural validation cannot prove cross-record
  correspondence, signature, currentness or approval. Explicitly test this distinction.
- [ ] RED real ImmutableRecord/body cases for exact journal§4 receipt and consumption shapes.
  Receipt: operational/version1/id=request_ref.id, exact parent=[request_ref], four BlobRefs,
  receipt/U caps16384 and J/K8192, one shared vault and closed content. Both complete canonical
  anchor bodies are capped at8192bytes, not merely their content subobjects. Consumption:
  operational/version1/hostUUID, exact parents=[request_ref,receipt_ref], both version1 and
  receipt.id=request.id, actual actor_ref equals envelope actor_ref, winning revision2,
  transaction_id canonical commandUUID, public_event_id canonicalUUID, failed|unknown and
  exact calendar consumed_at as wire Time (24 characters, three fractional digits), with
  created_at_utc exactly the same validated text zero-padded to six fractional digits. Do not
  accept six-digit content, round/truncate, or compare the unlike representations literally.
  No blobs. Validate
  all duplicated refs/header relations and preserve generic reserved-reference validation.
  A structurally supplied event UUID is not proof that an event exists; later same-writer service
  must use its actual append result and full DomainStore graph/index verification.
- [x] Add real temporary DomainStore roundtrip/graph rejection tests using existing actual roots/
  request fixture and public receipt blob bytes. No importer, signature-positive mock or handbuilt
  journal admission. Existing graph checks reject missing/foreign refs and blobs; structural
  failures are fixed DomainContractError without payload canaries. No new authorization bypass.
- [x] Regenerate only new two deployment schemas and the changed domain-envelope artifact through
  normal exporters; compare all other schema bytes unchanged. Exact output is sorted indented
  UTF8 plus newline, not signed canonical wire. Test import order/fresh structure-only process
  remains independent of nacl/source/owner/HTTP modules except existing inert helper dependencies.
- [x] Final frozen covering: three new suites plus existing prepare-contract/schema, domain
  contract/storage/permission/schema and receipt wire/schema suites discovered with rg; run once
  with project Python, tracing disabled, -B/-p no:cacheprovider. Scoped Ruff/format/diffcheck,
  regenerate parity and preserved artifacts. Report exact files/RED/GREEN/commands/results/hashes
  to `.superpowers/sdd/resumption-plan/task-18-report.md`, then independent review. No v2 DB/API
  activation, live source, host operation or fullT025/T087 completion.

Task18 implementation/review gate accepted after I1 correction and clean scoped rereview.
The three remaining unchecked test bullets retain M2's specifically missing depth/uppercase UUID/
marker-field and complete-body-cap coverage as deferred final-review work; do not re-execute this
accepted implementation merely from those checkboxes. M1 actor-version restriction and M3 inherited
warning/legacy formatting remain explicitly deferred. Final464covering and parent4time regressions
are current; initial460 and broader394integration are pre-fix. No v2 activation or whole-story claim.

### Task 19: Preserve actual E inventory and no-clobber publication across cancellation versions

Execute after Task18 acceptance, consuming the accepted Task16 shared publication mechanics and
Task14 retained-source base. Read journal§6/9, prepare-source contract and actual source/publication
reports before editing. This is file/version compatibility, not v2 lifecycle authority or import.

**Files:** Modify only `app/deployment/publication.py`, `app/deployment/sources.py`; create
`app/tests/test_deployment_cancellation_v2_publication.py`. Existing source fixtures/tests may
change only for necessary additional fixed fixture data after parent snapshot. Do not edit v1
codecs/artifacts, pure Task18 grammar, SQL/service/API, consumed publisher, initializer or B/S/R/X.

**Interfaces:** journal§9 `validate_cancellation_v2(*,request_digest,payload,profile)->Projection`,
`_validate_retained_projection(*,role,request_digest,payload,profile)->Projection`,
`publish_cancellation_v2(source,*,request_digest,payload)->PublicationObservation`, and
`ExchangeSource.publish_cancellation_v2(self,*,request_digest,payload)` concrete delegate.
Observations retain role='cancel', existing B32 request selector, whole payload hash/size and
actual FileIdentity. No new role/namespace, serialized authority or caller-selected version flag.

- [x] Snapshot actual post-Task17 source/publication bytes and fixed artifacts. RED a real E
  temporary-file chain: prepare actual v1 request, build Task18 v2 marker, publish through actual
  E, close/reopen E, inspect/recheck existing files and publish a different request's v1 marker.
  It must fail before the new inventory/publisher seam exists, never skip with a v2 stub.
- [x] Implement v2 projection wrapper calling the one Task18 parse_cancellation_v2 via local
  import; normalize its closed errors to existing DeploymentSourceError and return only actual
  selector/digest/size observations. No duplicated marker grammar, callback or import cycle.
  Existing public validate_projection and publish(role=request|cancel) remain v1-only.
- [x] Implement finite retained-inventory dispatch: request delegates unchanged v1; cancellation
  safely discriminates bounded canonical schema-v1/v2 then delegates exact fixed codec. Unknown,
  mixed/oversized/noncanonical/unsafe payload rejects. E._recheck_outbox uses this internal
  checker for every retained final, including cold factory open. No configurable codec registry.
- [x] Implement explicit v2 publisher with exact ExchangeSource/currentness, same old cancellation
  role policy and Task16 shared existing/stage/commit primitives. Preserve visible recheck between
  stage and no-clobber commit and after actual publication observation. Never call public v1
  publish with a fake role or erase old type/currentness checks. No duplicated syscall/write loop.
- [x] RED/GREEN mixed-version fixtures: old v1 request/cancel APIs reject v2 input but operate
  normally when another request has a valid v2 final; malformed unselected v2 final denies E;
  v1/v2 filenames remain request-digest selectors and existing different bytes never overwrite.
  Exact existing v2 replay fsyncs and returns same observation, even at16final capacity, while
  new17th/stage33 fail. No filesystem tombstone/automatic cleanup or reservation release.
- [x] Fault checks prove missing/replaced source/namespace/name/bytes, changed profile/pin, unsafe
  mode/uid/link, wrong selector and unsupported no-replace fail in closed source family. Hold
  actual temporary FDs; inject failures before stage, after write/fsync, before rename and after
  visibility. Source loss cannot be hidden by a valid parsed Projection; closing E invalidates
  publish. Preserve no-clobber/crash semantics and test-only Linux syscall qualification limits.
- [x] Final frozen covering: new cancellation-v2 suite plus old test_deployment_publication,
  test_deployment_sources, Task18 pure contracts/schema, Task16 consumed-publication/inspection,
  actual prepare publication/API and initializer suites. Discover exact files with rg, project
  Python -B pytest/tracingdisabled/no cache; no duplicated full-project command. Scoped Ruff/
  formatting/diffcheck and old artifact parity. Report `.superpowers/sdd/resumption-plan/task-19-report.md`
  with exact final hashes, RED/GREEN/results and unsupported host limits; independent review.
  No v2 schema install, owner import, signed execution, installer/image or whole-story completion.

Task19 accepted after independent spec/quality PASS: final385covering and parent213integration,
one inherited warning each. Frozen3/159untouched/68schema hashes verified. Replay-file fsync
assertion precision and inherited warning remain deferred minors; actual shared production replay
performs file and directory fsync. No lifecycle/import/host qualification follows.

### Task 20: Upgrade and consume receipts through the same actual prepare service

Execute after Task19 acceptance. Complete normative contract:
`contracts/deployment-receipt-journal.md` (all13sections), plus receipt wire/source contracts and
accepted Task10B/C reports. This is one coordinated storage/records/lifecycle/service change:
no independently instantiated import service, second transaction/clock or temporary incomplete
compatibility state is an accepted handoff. No accepted/effect/installation state is added.

**Files:** Modify `app/deployment/prepare_storage.py`, `prepare_records.py`,
`prepare_lifecycle.py`, `prepare_service.py`. Create
`app/tests/deployment_v1_history_fixture.py`, `app/tests/deployment_receipt_import_fixture.py`,
`app/tests/test_deployment_receipt_migration.py`,
`app/tests/test_deployment_receipt_journal_integrity.py`,
`app/tests/test_deployment_receipt_import.py`,
`app/tests/test_deployment_receipt_journal_reconciliation.py`.
Permitted integration edits after parent snapshots: `app/tests/deployment_prepare_fixture.py`,
`app/tests/test_deployment_prepare.py`, `test_deployment_prepare_integrity.py`,
`test_deployment_prepare_publication.py`, `test_deployment_prepare_storage.py`,
`test_deployment_prepare_api.py`; only concrete registry install arguments, true pre-deployment
fixture setup and legitimate current-GETv2 expectations. Preserve all old wire/replay/negative
assertions. No domain/source/publisher/API production, generic composition, dependency/initializer,
schema artifact or historical B/S/R change unless parent rules on a demonstrated interface defect.

One narrow test expectation correction is also authorized: in test_deployment_prepare_integrity
::test_install_routing_preserves_absent_schema_initialization, the actual upgraded constructor
and records.install must produce exact storage.SHAPE_V2, not old SHAPE. Preserve empty rows,
not_found and absence/anchor guards; all old low-level v1 schema/install expectations stay strict.

**Interfaces:** exact journal§7–11 APIs and eleven literal DDL in§2, originalC1 and C2§12. Same
PersistentDeploymentPrepare, sameRLock/highest/unavailable/DomainStore/owner/candidate registry,
three borrowed optional exact source arguments and import_receipt(request,request_id,payload).
Current GETv2 always includes receipt/consumption fields; historical frozen responses stay exact.
prepare_v2_contracts/domain kinds and E v2 publisher already exist; do not recreate their logic.

**Owned test-session prerequisite (Task12 deferred M2):** Before signed import tests reuse a
long-lived Node session, create `app/tests/deployment_receipt_session_fixture.py` and
`app/tests/test_deployment_receipt_session_fixture.py`; narrowly modify
`app/tests/test_deployment_receipt_crypto.py` to reuse the same bounded session and remove its
unbounded read_frame/write_frame session path. Parent snapshots that existing file first.
This adds test infrastructure only, not a production signer or a second import service.

The shared fixture exposes `OwnedReceiptSession(profile)` as a context manager, immutable
`trust_bytes` while open, `case(request_bytes:bytes,*,case_name:str)->dict` returning the exact
public response frame, and idempotent `close()`. Consume the unchanged Node --session protocol
and existing configured-or-PATH runtime resolution. Enter owns exactly one newly created child;
no caller process/PID, private key, timestamp or arbitrary signing input is accepted. The importer
fixture and existing two-request crypto test share this one implementation:

```python
with OwnedReceiptSession(profile) as session:
    trust_bytes = session.trust_bytes
    response = session.case(request_bytes, case_name="valid_failed_absent")
    assert set(response) == {"receipt_b64", "unsigned_preimage_b64"}
# Actual receipt/request/U signature and admission checks remain with their normal consumers.
```

- [x] First add clean RED cases for complete-frame timeout after partial stdout, stdout EOF while
  stderr stays open, output overflow, stalled input write, and child ignoring graceful shutdown.
  Use only newly owned bounded subprocesses; no unrelated process inspection/signals. Implement
  binary nonblocking/selector pipe I/O with one monotonic five-second exchange deadline covering
  the entire bounded write and complete reply, not just initial readiness. Frames are at most
  131072 bytes excluding newline; stderr capture at most4096 bytes. No blocking readline or
  unbounded stderr.read. On close/failure use finite EOF wait0.5s, terminate wait0.5s, then owned
  child kill/reap wait2s; a failed reap is an explicit fixture error, never a cleanup-success claim.
  Close all owned pipes/selectors on every path. Tests may shorten private test-only timeout
  constants, never alter request/receipt timestamps or production clocks.
- [x] GREEN the failure paths plus real Node one-U/two-actual-request verification; test normal
  EOF/reap and idempotent close. Preserve old crypto vectors, negative semantics and public
  fixtures exactly. Add both the new session suite and existing crypto suite to Task20's final
  covering command, with controlled runtime override and ordinary PATH coverage where available.
  These tests prove only owned test-process lifetime, not external signing-job behavior.

- [x] Before any production edit, snapshot permitted files and accepted old DDL/schema/hash
  baselines. RED actual owner/domain v1-history migration cases using journal§13 fixture:
  empty and16mixed states, actual v1 storage install before anchors, candidate registration,
  source identity, normal blobs/anchors and lifecycle helper events/cursors. Restore the
  test-only pre-deployment catalog before ordinary upgraded constructor invocation. No service
  monkeypatch/version knob, copied old service, stored auth fixture or fake published ack.
- [x] Add exact build-owned v1/v2 layouts. Preserve v1 public constants and v1-only install/
  validate_row helpers. Actual insert/advance/verify/validate_current_row select observed exact
  schema, with migration scalar/UTF8/count preflight before any fullchecksum materialization.
  Reuse SQL CHECK/hash/scalar mechanics; fournew suffixes alone use storage-v2 hashes.
  Bound every role and association exactly, no marker-only dispatch/cache or arbitrary layouts.
- [x] Implement records.install(domain,db,profile,*,candidate_registry) as sole upgraded entry:
  bound actual registry + bounded preflight/fulloldhistory before any DDL. Exactv1 rebuild uses
  same FK-on writer/defer_foreign_keysON, ordered per-PK delete/drop/ninecreate/exactrestore/
  migration2insert/fullnewhistory/FKcheck, no rename/executescript/FKOFF. Empty first proves
  three-kind/event absence; exactv2 verifies without writes; partial/corrupt denies. Constructor
  unconditionally upgrades even with sourcesNone, never enrolls/expires/publishes there.
- [x] Real disk rollback faults after each DELETE/DROP/CREATE/restore/migration insert/commit
  prove exactv1 rollback, no partialv2 and unchanged oldbytes/hashes/events/cursors/refs. Reopen
  and concurrent constructors observe exactcommitted shape. Test all malformed scalar/checksum/
  extra schema/FK/orphan histories deny beforeDDL. Oldlowlevelinstall rejects actualv2 honestly.
- [x] Extend shared records loader/fullverifier without duplicate walker. Three anchor/index
  bijections/allversions, source singleton iff receipt, true source/U/signature/admissiontime
  historical checks, exact predecessor/command/event/state/outbox/ack relationships. Check
  bounded SQLvalues before materializing anchors/blobs/associations; allcaps§8. Missinglive
  sources cannot change historical validread or reinterpret oldreceipt undernewkey.
- [x] Refactor actual lifecycle through one _append_transition and _store_command. Use actual
  event append result for consumption, no injectedID/hashcycle. Finite prepared1→cancelled2/
  expired2/receipt_pending2/rejected2; pending2→cancelled3/expired3 only. Actualoldv1 helperpaths
  remain valid for historicalfixture. Exactstate/outcome/eventmatrix, frozen replies, current
  GETbody and v1/v2 markerselection. Recompute projections from actual committedrecords.
- [x] Refactor command admission by fixed logical operation; lookup/replay by retained
  namespace before head interpretation. Actual owner/revocation/CSRF remains required even
  replay; exact replay returns without sources/clockadvance/expiry/flush. Wrongbody/route/actor/
  operation conflicts. Freshcancel namespace derives validprepared/pending head only.
- [x] RED real signed import: matching-head earlyexpiry commits onlyexpiry409 beforeliveI/O;
  stalewronghead/digest neverexpires another head. Otherwise actualU/J/K, boundedKinventory,
  Jlease, fullsignature/requestverify then preseal4blobs. Finalsamewriter repeatsauth/replay/
  fullhistory/head/time/managedkindabsence/source+leasecurrentness and signature fromactualbytes.
  Never reacquireTslot/liveT/E or treat operatorfacts as qualifiedeffect. Onecommit attaches
  receipt, event/history/head/command/index and onlyfailed/unknown consumption/Kintent. Pending
  success getszero consumption/install; suppresspendingrequest inalloutcomes. Leaseclosesalways.
- [x] Test exact private mismatch409 vs otherwire/selectedmalformed400 vs source503 precedence,
  noerrortextguessing. WrongliveJbind503 mayprecedecrypto; forgedmismatch400 never409. Clock
  monotoniccheckpoint/highsample/finaldeadline/rollback, no lateevidence shortcut. Fault every
  authoritativewrite leaves no partialentity/event/index/head/reply/intent; only presealedorphans
  allowed. Import/import/cancel/expiry competingconnections retain firstwinner/reservations.
- [x] One existing reconciliation budget/cancellationpriority, thenconsumed, thenrequest/expiry;
  pending-success dueexpiry remainseligible afterrequestsuppression. Newconsumed item verifies
  actualU/J/K/history/marker underwriter throughfilepublication+returnidentitychecks+ackCAS.
  EnrolledKgatebeforepositive requestpublish andack, TTLaslateasrequired; beforeenrollment noK
  dependency. Cancel staysintactE-only; expectedsourcefailure remains pendingwithoutcorruptionlatch.
  Missingpublished/alien/differingfinals neverrepair/regressack/reenroll/release. Crash-afterrename,
  capacity/replay, missingKacrossrestart/successzero-consumption andclockcrossinginventory tests.
- [x] Final covering includes allnewmigration/integrity/import/reconciliation, everyexisting
  prepare/source/publication/owner/candidate/domain/event/schema/commonHTTP test family once on
  frozenbytes. Exactpaths withrg; projectPython/tracingdisabled/-B/nocache, scopedRuff/format/
  artifactparity/diffcheck. No fullprojectduplicate; parent owns fullregression afterfreeze.
  Report `.superpowers/sdd/resumption-plan/task-20-report.md` with exact RED/GREEN/faults/commands/
  outputs/hashes andv1fixture vs actualoldadmission limits. Independentreview/fixes beforeTask21.
  Oldbinary aftercommit failsclosed; no rollbackpromise/userstoremigration/actualoperatorcall.

Task20 accepted within its coordinated scope: amended2884 covering and fresh parent full5456
passed,1LinuxSO_PEERCREDskip,1inheritedwarning,369subtests613.50s. Independent spec/quality review
Approved with no Critical/Important; signed-session clean-exit/stderr test-oracle and inherited
warning remain tracked minor follow-ups. Exact14final/156untouched/68schema hashes verified.
The deterministic initial-source-snapshot race correction retains the existing writer, pre-I/O
checkpoint, outside-SQL preseals and all final rechecks. No install/qualification or release claim.

### Task 21: Connect owner receipt import through the existing web contribution

Execute after Task20 acceptance. Read complete receipt-journal§6/11/12 and actual accepted C
common-composition contract/report. Extend the one installed deployment contribution; no second
importer/service/registry/router framework or user-CLI workflow. Real postcondition acceptance,
installation, qualification/binding and graph/runtime integration remain later dependencies.

**Files:** Modify `app/api/deployment_prepare.py` and
`app/api/route_contributions/deployment-prepare-v1.json` for the newfixedroute/parser and concrete
factoryinputs. Inspect `app/api/first_party_catalog.py` and `app/api/web_boundary.py`; change them
only if their existing shared-key/prefix/delegated-preflight wiring does not satisfy the tested
new-route contract. Their unchanged behavior is acceptable when actual integration tests prove it;
no mandatory cosmetic hunk. Create
`app/tests/test_deployment_receipt_api.py`. Necessary scoped fixtures/expectations may modify
`app/tests/deployment_prepare_fixture.py`, `deployment_receipt_import_fixture.py`,
`test_deployment_prepare_api.py`, `test_first_party_dependencies.py`, `test_first_party.py`,
`test_web_owner_integration.py`, with exact parent snapshots. No generic first_party.py/server
production seam change, SQL/service/domain/source/publisher/dependency/initializer edits, lower
composer changes or newservice locator. Concrete interface defects require parent ruling first.

**Interfaces:** same `prepare_services(context,*,dependencies)` consumes only actual
extension-candidates.registry and exports only deployment-prepare.service. It constructs once
and borrows exact Task20service APIs. Same `reconcile_prepare_startup(own_exports)` and common
one-shotactivation/ownership. Append five fixed receiptstartupkeys from journal§11 to existing
fourpreparekeys; do not reread wholeenv or discovercredentials/privatepaths.

- [x] Snapshot all permitted files and current v1/v2 schemas/source/B/S/R baseline. RED actual
  localprefix andportable HTTP: ownerbootstrap/login→candidate→prepare→actualincoming signed
  receiptselector→import200→GET/HEAD→exactreplay/restart. Positivepath uses actualsourcefactories,
  realDomainStore/journal/service andpublicfixturecrypto, no mocksuccessfulimport/auth callback.
- [x] Open U/J/K independently from common frozenallowlistedinputs and exact protectedroots.
  InvalidU doesnot skipJ/K; invalidsharedQ/V deniesJ/K notU/T/E. IndependentT/E behavior preserved.
  Each successfulopenedsource isowned immediately byfactoryExitStack; result transfers exact
  sourceobjects once into commonowned_resources; service onlyborrows. Partialfailure/laterfactory/
  return/export/router/hostshutdown pathscloseonceinreverse withoriginalerrorpreserved. No source
  enrollment/expiry/publication duringfactory; actualone-shotstartup handlesreconciliation.
- [x] Add browser_session-only manage POST
  `/api/v1/deployment/requests/{request_id}/receipts` with route_id
  `deployment.requests.receipts.import`; bodyexactjournal§6,4096/depth4/items32/members8/string256,
  noquery/path/key/bytesupload andnormalraw-path/Origin/Host/FetchMetadata/CSRF/sessionadmission.
  Fixedpreflight delegatespureparse_receipt_import; canceldelegatesparse_cancel_v2, GETreturns
  actualcurrentv2state. No service-client bearer ordiscovery/list/import-all route.
- [x] Canonical frozenimport200 body hasno links, exactpending_postconditions or
  consumed_non_success disposition, revision2/actualcursor. Existingprepare/cancel stored
  responses keepbyteidentity/prefixonce; GET/HEAD includev2fields evenforoldrequests. Strict
  newwire/errors andlimittransportincludingchunked/no-length denybeforebusiness. No synthesized
  receipt onmissingfile/invalidsignature/unknownexception; actualclosederrorcodes asjournal§12.
- [x] Cover succeeded evidence→receipt_pending withnoinstallation/consumption; failed/unknown→
  rejected withexactoneconsumption/pendingKintent; pendingcancel3→v2Efile/reopen; dueexpiry409commit;
  cancel/importfirstwinner; changedreplay409 vs exactreplaywithoutsource/clock/flush. HEADsame
  content-length/type/securityheaderswithzero body. CandidatePOSTstillneverstages orimports.
- [x] Realcoldrestart verifiesforward-onlyv2databaseandhistoricalresponsebytes. With missingU/J/K,
  ordinaryowner/candidate/read/replay/localcancel/expiryremainavailable; physicalcancelusesintactE.
  EnrolledKfailureleavesnewpositiveprojectionpending, notjournalcorruption. Startupfilescanappear
  onlyaftercompletecomposition; laterworkerfailure cannotundoalreadycommitted/publicationevidence.
- [x] Finalcovering newreceiptAPIplusallprepareAPI, firstparty/dependency/router/boundary/owner/
  candidate/serviceclient/session andreceiptmigration/import/reconciliation/source families on
  frozenbytes. ScopedRuff/format/diffcheck/artifactparity, unchangedgenericcomposition/lowerrouter
  hashes. Report `.superpowers/sdd/resumption-plan/task-21-report.md` withexactcommands/output/
  hashes/RED/GREEN/limits. ParentownsfullPython+proportionatebrowser andindependentreview.
  No realoperator/signingkey/install/image/two-hostqualification orwholeUIjourneyclaim.

### Task 22: Closed immutable image identity and lineage values

Execute only after Task21 acceptance. Read complete
`contracts/extension-lineage-values.md`; that contract is the exact structural specification,
not the advisory reports' earlier build-only eligibility recommendation. This is one cohesive
codec/schema/structural-join deliverable within T087, not success installation or a new authority.

**Files:** Create `app/extensions/lineage_contracts.py`,
`app/extensions/lineage_schema_exports.py`, `app/tests/test_extension_lineage_contracts.py`,
`schemas/v1/extensions/build-identity-v1.schema.json`, and
`schemas/v1/extensions/build-lineage-v1.schema.json`. All must be absent before dispatch.
No existing production/test/schema changes; reuse actual candidate types/schema builders,
domain wire/canonical helpers and `PORT_SCHEMA_SHAPES`. No loader, source, HTTP, database,
image builder/extractor, initializer, runtime or qualification/binding edit. Parent snapshot
the complete accepted baseline and68 existing schemas first; do not modify any frozen history.

**Interfaces:** Exact §5 class/parser/digest/projection/schema-byte/descriptor-join interfaces
and §6 deterministic schema exports. Runtime parsers and joins are pure and return inert values
or None, not issued success/trust tokens. All inputs/caps/grammars/errors are literal §2–5 values.
Use current `ExtensionServiceDescriptor` and existing full `index`/`platforms` schemas; no copied
subset that loses size/media/position or only checks the selected platform. The source-level
package boundary remains free of app.api/static/server imports.

- [x] First tests independently build both-platform structural values from existing
  `app.tests.extension_candidate_fixture.candidate_payload()` metadata; create a local test
  identity helper with input SHA256/size refs, entrypoint ref and actual current four schema
  bytes in fixed role order. These are synthetic declarations, not a real built image. Establish
  RED on missing parsers/joins before implementation, retain complete command/output.
  The following assertions must be present with helper inputs defined in the new test file:

  ```python
  raw = canonical_json(identity_mapping)
  value = parse_build_identity(raw)
  assert value.content_bytes == raw
  assert value.digest == hashlib.sha256(raw).hexdigest()
  assert value.input_digest == hashlib.sha256(canonical_json(identity_mapping["inputs"])).hexdigest()
  assert value.schema_set_digest == hashlib.sha256(canonical_json(identity_mapping["port_schemas"])).hexdigest()
  detached = value.as_dict()
  detached["entrypoint"]["sha256"] = "0" * 64
  assert value.content_bytes == raw
  ```

- [x] Implement bounded canonical decoding and immutable byte-backed values, sanitized exact
  errors, independently validated embedded identity, both-platform/order/size/media relations.
  Derive detached selected projection and hash without caching mutable dictionary truth. Reuse
  existing wire depth/item semantics and schema grammar; source-byte validation hashes actual
  supplied bytes, not regenerated semantically equivalent JSON. Validate all exact class/scalar
  inputs; no constructor or successful validator grants runtime authority.
- [x] RED-first join tests create actual existing candidate descriptors with the lineage's
  MetaRef and exact five argv values. Require both complete platform entries and index equality.
  Mutate each nonselected-platform media/size/digest/order and provenance MetaRef independently;
  all must fail even when other digest strings match. Preserve repeated layer digests and test
  maximum128 layers/platform within total cap. Slot1/16 accept canonical strings; booleans,
  out-of-range/leading-zero/extra/missing/semantic args and wrong instance deny. Example:

  ```python
  descriptor = ExtensionServiceDescriptor.from_mapping(descriptor_mapping)
  assert validate_descriptor_lineage(lineage, descriptor, instance_id="1" * 32, slot_number=1) is None
  changed = descriptor.as_dict()
  changed["platforms"][1]["config"]["size_bytes"] += 1
  with pytest.raises(LineageContractError, match="^invalid lineage value$"):
      validate_descriptor_lineage(lineage, ExtensionServiceDescriptor.from_mapping(changed),
                                  instance_id="1" * 32, slot_number=1)
  ```

- [x] Add strict shape/type/Unicode/BOM/duplicate/noncanonical/unknown-field and exact cap edge
  cases, including version component overflow, numeric booleans, incorrect schemas/role order,
  truncated/oversized actual schema bytes, and real shipped result schema>65536bytes. Expected
  hashes/projections must be independent test computations, not values taken from subject methods.
  Report whether broad wire caps are redundant above narrower valid grammar; do not fake an
  invalid scalar as a valid cap-edge positive or widen the grammar to reach a test bound.
- [x] Implement deterministic new-only exports and byte-parity tests, runtime/schema shape
  agreement and invariant that accepted current68 schemas did not change. Code generation is
  developer artifact production, not runtime filesystem behavior or evidence qualification.
- [x] Self-review all five new files; Ruff/format/diffcheck, baseline/schema integrity, then
  freeze before the complete covering command (projectPython, all tracing disabled, -B and
  -p no:cacheprovider): `app/tests/test_extension_lineage_contracts.py
  app/tests/test_extension_candidates.py app/tests/test_extension_candidates_persistent.py
  app/tests/test_extension_candidate_api.py app/tests/test_extension_port_schemas.py
  app/tests/test_extension_port_schema_generation.py app/tests/test_core_import_boundary.py
  app/tests/test_deployment_prepare_contracts.py app/tests/test_deployment_receipt_contracts.py`.
  Verify actual filenames before run, no silent substitution. Final exact report
  `.superpowers/sdd/resumption-plan/task-22-report.md`; parent owns independent review.
  T025/T087/wholeUI remain open; no realimage/native/cryptographic-origin/scan/build/live result.
Task-scoped result: implementation covering 475 passed; independent review returned "Needs fixes"
with two Important findings — hollow/corrupt exact-class instances (absent or non-bytes stored state)
leaked `AttributeError` through `validate_schema_bytes`, `validate_descriptor_lineage` and
`selected_platform`, and the mandated shortened-argv join vector was absent. Fix round 1
(2026-09-16): a `_stored_bytes` state guard plus `AttributeError`/`IndexError` in the sanitizing
boundary, 12 hollow-state regressions (RED 6 failed first) across all three classes, and three
shortened argv vectors (slot value omitted, pair omitted, bare executable). Covering suite
490 passed; Ruff lint/format/diffcheck clean. Minor warning noise remains the inherited
Starlette deprecation. Task 22 accepted; no real build, image provenance or installation claim.


### Task 23: Actual fixed-file extension worker measurement

Execute only after Task22 acceptance. Read complete `contracts/extension-worker-metadata.md`
and `contracts/extension-lineage-values.md`. This is the actual local reader prerequisite for
an authenticated live observation, not admission, installation, qualification or readiness.

**Files:** Create only `app/workers/extension_metadata.py` and
`app/tests/test_extension_worker_metadata.py`, after absence checks. No existing production,
test, schema, startup, router, database, deployment, container or initializer edits. Parent freezes
the accepted baseline including Task22 first. Do not modify historical identity/candidate/receipt
bytes. Tests may create only temporary trees and files, not real fixed paths or mounts.

**Interfaces:** Exact metadata-contract§1 factory/retained source/frozen reading and§2 closed
error names; pure Task22 `parse_build_identity`/`validate_schema_bytes`; existing `broker.Deadline`.
Reuse only compatible low-level file/mount helpers named in§4; no caller-pinned `SourceFile`,
absence-only IPC lease, expected-observation callback or production test mode. Preserve package
import boundaries. Baseline ownership of thirteen FDs and every transient/error path are testable.

- [x] Write actual temporary-tree fixtures with fixed relative leaves and real shipped schema
  bytes; test-only redirection/sampling preserves actual inode/mode/type/bytes for filesystem
  assertions. Establish RED on absent public factory before code. Clearly label synthetic
  platform/owner/mount values, not Linux qualification. Include these assertions with fixture
  `worker_tree` defined in the new test file:

  ```python
  source = open_worker_metadata_source()
  try:
      result = source.read_current(deadline=Deadline.after_ms(1000))
      assert result.build_identity.content_bytes == worker_tree.identity_bytes
      assert result.platform == "linux/amd64"
      assert (result.uid, result.gid) == (22001, 22001)
      assert source.read_current(deadline=Deadline.after_ms(1000)) == result
  finally:
      source.close()
  assert source.closed
  source.close()
  with pytest.raises(WorkerMetadataClosed):
      source.read_current(deadline=Deadline.after_ms(1000))
  ```

- [x] Implement fixed no-argument acquisition and actual complete file measurement with
  independent streamed worker hashing, actual identity/schema bytes and measured process/mount
  observations. Apply exact metadata-contract modes/owners/size/fd/deadline limits. No directory
  enumeration, executable-byte return, expected pin, platform fallback, or authority token.
- [x] Implement named/retained-FD fences before/after each fresh complete read; exact actual
  signatures and baseline content; source poisoning on integrity/unavailable failure, safe retry
  only for caller deadline/busy. Serialize with nonblocking lock, attempt all closes, preserve
  active exceptions, unwind partial acquisitions on BaseException. Test source noncopyability.
- [x] RED-first mutation/error tests exercise byte-identical replacement, unlink/truncate/growth/
  edit/chmod, changed ancestor, symlink/hardlink/FIFO/directory inputs, actual schema/worker mismatch,
  exact byte caps, process/mount drift and visible alias. Retain unrelated mount-order and /opt
  sibling acceptance. Check real retained/transient FD counts, partial-open/close errors, deadlines
  and concurrent read/close without touching other processes or real system resources.
- [x] Self-review/final Ruff/format/diffcheck and unchanged baseline/schema parity, freeze both
  new files before complete covering command with projectPython, tracing disabled, -B, -q and
  -p no:cacheprovider: `app/tests/test_extension_worker_metadata.py
  app/tests/test_extension_lineage_contracts.py app/tests/test_deployment_sources.py
  app/tests/test_core_import_boundary.py deploy/tests/test_worker_boundary.py
  deploy/tests/test_worker_listener.py`. Record full terminal output, warnings/skips/limitations
  in `.superpowers/sdd/resumption-plan/task-23-report.md`; parent owns independent spec/quality
  review and proportional fresh verification. No whole-suite/browser repetition by default.
  T025/T087, real Linux/image/native/boot/probe/observer/installation and wholeUI remain open.
Task-scoped result (2026-09-16): `app/workers/extension_metadata.py` and
`app/tests/test_extension_worker_metadata.py` implemented RED-first (ImportError on the absent
module, then 53 passed). Thirteen retained descriptors, fresh-chain reopen and full byte/digest/
signature/process/mount recheck per read, closed error family, poison-on-integrity, busy/deadline
semantics, non-copyable handle; ten post-open mutations, symlink/hardlink/FIFO/directory leaves,
caps, six mount rejections and drift cases covered with real temporary files (simulated Linux
facts). Covering command 264 passed / 1 Linux skip / 21 subtests; Ruff lint/format/diffcheck
clean. Evidence: `evidence/extension-worker-metadata-task23.md`. Independent review returned spec FAIL / quality PASS with two Important findings — a mount
below the prefix at a non-chain name was accepted, and a BaseException in the factory tail leaked
the 13 retained descriptors — plus five Minors (leaf-open OSError classified invalid, no deadline
check between identity/schema chunks, mount state sampled only after the reads, `__exit__` could
replace a propagating exception with busy, broad Invalid mapping). Fix round 1 (same day): every
mount at or below the prefix refuses on or off the named chain; the factory tail unwinds on any
BaseException; leaves open directly so OSError stays unavailable; identity/schema reads check the
deadline around every chunk; mount state is sampled before and after the reads and retained
descriptors are re-fstat'ed at the final fence; `__exit__` preserves a propagating exception.
RED 6 failed → GREEN; suite 60 passed; Ruff lint/format/diffcheck clean. Task 23 accepted for its
bounded reader scope. T025/T087, real Linux/image/native/boot/probe/observer/installation and
whole UI remain open.


### Task 24: Stage postcondition acceptance and installation head (T087 partial) — DRAFT REJECTED 2026-09-18

The autonomous loop drafted a three-phase entry on 2026-09-18 (evidence value → installation
record/head → success consumption, with a fixed-file "observer" over the socket mount and an
owner route accepting an evidence body). Independent specification review REJECTED it before any
code. The rejected draft is not retained here so that no reader dispatches it; the findings that
must shape the redraft are:

1. **Postcondition is a component handshake, not a file read.** `open_worker_metadata_source()`
   pins `/opt/deeptwin-extension` on the calling process's own root mount and samples its own
   uname/uid/mountinfo (extension-worker-metadata §1/§4/§6); from the control process it can
   never observe a staged service, and `socket_mounts[0]` is the `broker_pair` volume holding
   `worker.sock`, not the worker image tree. The normative arm-specific stage postcondition is a
   control-side authenticated probe over that socket in which the worker reports its own
   `WorkerMetadataReading`, compared to the request tuple and `validate_descriptor_lineage`
   (api.md handshakes, runtime.md "handshake/qualification precede binding CAS", data-model
   §3.1 descriptor row, lineage-values §1). Today the core can make **no** such observation: the
   three probe slices in the private proposal
   `.superpowers/sdd/resumption-plan/worker-probe-integration-proposal.md` (channel values,
   private listener/boot-ID handshake, worker probe service) are a prerequisite task.
2. **Evidence is never a request body.** receipts §6 / journal §1: the owner route accepts
   digest selectors only; the service performs the observation itself in its preseal phase (as
   it does `J.open_receipt`) and only the observer module can construct evidence.
3. **Success is `accepted`, on a journal v3.** The lifecycle state is `accepted` (data-model
   `DeploymentRequestLifecycle`); DDL_V2 allows revision 3 only for `cancelled|expired`, the
   consumption anchor pins revision 2 and outcome ∈ {failed, unknown}, and §12 freezes C2
   forward-only. Task 20 added `_V2` constants and preserved C1 byte-exact; this step needs a
   `deployment-receipt-journal` **v3 contract** (migration row 3, `DDL_V3/CHECKSUM_V3`, C1/C2
   preserved, consumption anchor v2 with `outcome:"succeeded"` + `effect_ref`, verifier rules
   for `accepted3`, admission rows `receipt_pending2 + consume` and `accepted3 + any → 409`,
   no K marker for success, `prepare-api-v3` with `disposition:"consumed_success"` and a
   defined frozen consume-200 body, the `deployment.requests.consume` route in §6/§11, a
   registered `deployment.request_accepted` event next to `extension.staged`).
4. **Absent-only head.** receipts §2/§3 and journal §1 pin the first consumer to
   `expected_installation_head:{state:"absent"}` → revision 1; no uninstall arm produces a
   tombstone, so a tombstone CAS branch would be a fabricated-row fixture. It arrives with
   uninstall-current.
5. **The record is the domain kind `extension_installation`.** The first-only guard
   (`prepare_service.py` managed-kind absence query) and the reference scanner depend on it;
   `ENTITY_KINDS` and `app/extensions/contracts.py::ExtensionInstallation`
   (`extension-installation-v1`, with `verification_refs` and `scan_refs`) already exist and
   need an explicit supersede/coexist ruling plus a versioned content validator under
   `app/domain/` and regenerated envelope exports (Task 10 precedent). Evidence is presealed as
   an operational blob referenced from the installation anchor so the whole-journal verifier can
   recompute it.

**Status (2026-09-18):** every redraft step is implemented, independently reviewed and
evidenced — (a) `contracts/deployment-receipt-journal-v3.md`
(`evidence/receipt-journal-v3-contract-task24a.md`); (b) Task 25; (c) the domain anchors and the
v3 constants/codecs (`extension-installation-domain-task24c1.md`,
`prepare-v3-constants-task24c2.md`); (d) the observer (`stage-observer-task24d.md`); (e) the v3
storage and migration, the acceptance writer and the service transaction
(`journal-v3-storage-task24e1.md`, `acceptance-writer-task24e2a.md`,
`consume-transaction-task24e2b.md`); (f) the route (`consume-route-task24f.md`). The boundary
statements below stand; the live end-to-end run remains the Docker/colima host gate. Continue
with the Continuation section (T040 scheduler/ledger/worker integration). 2026-09-18: the first
Continuation slice, the atomic semantic acceptance + budget settlement
(`RuntimeLedger.accept_result_and_settle`, `runtime-result-settlement-t040.md`), is complete; the
Task 6 boundary (transport evidence releases no unknown-use reservation) is preserved. The second
slice, attempt dispatch through the scheduler (`NodeAttemptDispatcher`, `build_scheduler(attempts=)`,
`scheduler-attempt-dispatch-t040.md`), is complete. The third, the worker's first real operation
(`status`) behind the closed execute grammar and the real AF_UNIX attempt transport
(`worker-execute-transport-t087.md`; contract `extension-worker-probe.md` §2b), replaces the injected
transport for that operation. The connected browser path's route layer landed as the `runs-v1`
contribution (`runs-routes-browser-path.md`: create / read / resume a run of a stored graph through the
scheduler with an injected code-owned executor; no DOM yet). The run GUI's logic half
(`app/static/runtime.mjs`, `runtime-gui-logic-t048.md`) is complete, and the supported factory serves
every shell module with the shell on `X-DeepTwin-CSRF` (`shell-assets-supported-factory.md`); the cancel
route landed (`run-cancel-route.md`: a durable run phase, live attempts' gates closed, never a claim of remote
termination) and the owner's recovery (`run-recover-route.md`: the retry after a sent attempt on the ledger's
proof, at most four attempts per visit); the checkpoint↔attempt binding landed
(`checkpoint-attempt-binding-t040.md`), closing T040; the run trace's attempt layer landed
(`run-trace-attempt-layer-t048.md`: attempts per visit, the result attributed to the producing attempt only,
one closed read boundary, pending-write results); the shell's supported session client landed
(`shell-session-client-supported.md`: `session.mjs` — base path from the location, the token from `GET {base}session`,
the request adapter for the observer and the approvals module); the run view's DOM half landed over it
(`run-panel-dom-t048.md`: `run-panel.mjs`, not yet mounted — the shell has no run source); the worker's
`describe_tools` landed over its empty tool table (`worker-describe-tools-t087.md`); the artifact input leg of the
execute exchange landed over T018's bounded stream (`worker-artifact-input-leg-t018-t087.md`: declared inputs,
profile-gated admission, typed unknown on a broken stream; no registered consumer yet). The run source landed
as the public snapshot's run list (`run-list-source-t048.md`; a creation surface is blocked on the consent/design
line — no production path records a run consent, environment or work revision). The shell mount landed as the
public observation page (`observe-page-mount-t048.md`: `observe.html` beside the `/` stub, the session established
from the cookie, the list and panel mounted). The first real tool landed (`worker-text-profile-tool-t087.md`: `text_profile` and `invoke_tool` over the leg,
control mirroring the table and verifying the reply). Next: worker-returned output artifacts (the reverse leg), then
the owner setup/login UI (T025) so the observation page is reachable without a bootstrap client, then the
`ToolCall` record and effect gate for a tool call.

Redraft order (each independently reviewed before the next): (a) journal-v3 contract document;
(b) worker-probe prerequisite task; (c) pure record/head/consumption-v2 codecs, absent-only;
(d) evidence value inside the observer module with an in-process socket responder test;
(e) the one-writer consume transaction against the actual observer, with fault injection at every
stage; (f) route + prepare-api-v3. Boundary statements to keep verbatim: `staged ≠ verified`,
no qualification/binding/enable/dispatch, no replace/uninstall/retire arm, one-writer atomicity,
expiry precedence, and the live end-to-end run (container, socket, worker) is Docker/colima host
authority reported as a gate, never claimed; no GUI (UX-AC11 remains open).

### Task 25: Worker-private probe channel (prerequisite for Task 24; T018-foundation transport, T087 worker startup)

Drafted 2026-09-18 from the advisory
`.superpowers/sdd/resumption-plan/worker-probe-integration-proposal.md` (2026-09-16) after the
Task 24 draft was rejected for lacking any actual control-side observation of a staged service.
Independent specification review (2026-09-18): ACCEPT WITH CHANGES for slice 1a only; the changes
are folded in below. This establishes the authenticated observation a later stage postcondition
consumes; it adds no installation consumer, semantic execution, qualification, binding, dispatch
permit or admission proof. ADR-010/T018 own authenticated isolated transport (tasks.md
`T018-foundation`: actual Linux IPC initializers/listeners, peer-credential/channel handshake, a
prerequisite for T087); ADR-014/T087 owns extension lifecycle persistence and the worker service
startup over that transport. Slices 1–2 are T018-foundation; slice 3 is T087 worker startup.

**Authority:** `contracts/extension-worker-metadata.md` (§1 factory/retained source, §3 FD
budget: 13 retained + ≤32 transient, §4 actual observations; §6 names the "startup/private
probe/peer/HMAC composition, populated endpoint fence" gates this task *addresses* — it is not
authority that they are done), `contracts/extension-lineage-values.md` §1/§5 (descriptor join,
argv structure), `contracts/extension-candidates.md` (SocketMount `broker_pair`,
`deeptwin-extension-worker-v1` protocol identity vs `deeptwin-worker-ipc-v2` framing),
`contracts/deployment-prepare-sources.md` (control identity, packaging gate),
`app/deployment/contracts.py::slot` and `::CONTROL`, existing `broker.ChannelSpec`,
`ipc_root.PairRootSpec`, `WorkerListener`, and the Task 23 metadata source.

**Slices (each RED-first with retained output and independently reviewed; none starts before the
previous is accepted):**

- **1a. Fixed channel values and argv parser (pure; inert values with no production importer
  until slice 3, on the Task 22 precedent).** Create `app/workers/extension_channel.py` and
  `app/tests/test_extension_channel.py`. `extension_channel(*, instance_id, slot_number) ->
  tuple[PairRootSpec, ChannelSpec]` derives every value from `deployment.contracts.slot` (service
  `ext-I-NN`, channel `cp-ext-I-NN`, responder uid/gid 22000+N, pair gid 23000+N, socket mount
  `/run/deeptwin/ipc/xsNN`, `worker.sock`, `deeptwin-extension-worker-v1`) and from
  `deployment.contracts.CONTROL` (requester `control`, uid/gid 20102) — the tests assert against
  those two objects, never against literals restated in the new module. `pair_root` is the slot
  root's `endpoint` (never the outer root, `listener._validate_pair_channel`), direction
  `control-to-ext-I-NN`, root/socket owner responder + pair gid, modes 0o2710/0o660, requester
  types `("extension-artifact-v1","extension-request-v1")`, responder types
  `("extension-artifact-v1","extension-result-v1")`, frame 65536, in-flight 1, queue 16,
  operation 30000 ms as the explicit `extension-channel-profile-v1` constants (no framing
  change; `WorkerRouteBinding`-satisfiable). `parse_worker_argv(argv) -> (instance_id,
  slot_number)` accepts exactly five elements with elements 1..4 exactly
  `--instance-id`, hex32 (reuse `slot()`'s instance grammar, no third regex), `--slot-number`,
  `1..16` without leading zeros; argv[0] is not compared — the executable's packaging is an
  image gate. No I/O, no authority, no existing production edits.
- **1b. Probe message codecs** (`extension-stage-probe-v1` request ≤1024 B,
  `extension-stage-probe-result-v1` reply ≤4096 B, canonical strict JSON, hex64 digests, 43-char
  base64url nonce, `registered_operations` a sorted unique subset of
  `PORT_CONTRACTS["tool-port-v1"].operations`, `[]` permitted, envelope use of
  `FrameEnvelope` message_type/message_id/correlation_id, at most two probes per connection).
  Gated on a short accepted contract document `contracts/extension-worker-probe.md` normalising
  proposal §1–§4: these names exist nowhere in `contracts/` today and the proposal itself calls
  the reply grammar "a proposed correction, not an accepted schema change".
- **2a. Broker handshake continuation.** Private `_extension_server_handshake` /
  `_extension_client_handshake` in `app/workers/broker.py` around one shared continuation of the
  existing hello/challenge/session code (4096 B packet caps, fresh requester boot ID read from the
  actual hello and verified against the reconstructed expected hello, no verify-peer or
  challenge-factory callback, no second MAC/KDF). Public `server_handshake`/`client_handshake`
  stay byte-identical in semantics; every existing caller of `_server_handshake_impl` stays green.
- **2b. Populated-generation fence.** Private `ipc_root._retain_populated_generation(root,
  generation)`: borrowed generation plus an owned no-follow boot-secret FD and fixed ancestry
  observations, constant-time secret compare; the absence-only `MetadataGenerationLease` is
  untouched.
- **2c. Listener accept/connect and fences.** Private `_accept_extension_authenticated`,
  `_connect_extension_authenticated`, the listener fence over `_verify_record` (readiness
  bytes/HMAC/socket inode) rechecked before and after each probe, peer credentials taken at
  connect (they are fixed per connection, not a post-probe observation), and the mount-mapping /
  no-alias fence via the existing bounded mount helpers (slot mount RO for control, RW for the
  worker, no nested/alias mounts — matching `deploy/compose.yaml` today). Real
  `secrets.token_hex(32)` boot IDs once per process; the learned requester ID is an authenticated
  process label, never an owner account or authorization.
  *Test honesty for slices 2a–2c on this macOS host:* the new wrappers expose no `verify_peer`,
  so (i) socketpair/HMAC vectors exercise the shared post-peer continuation directly, (ii) the
  wrappers are asserted to fail closed with `PeerCredentialError` off-Linux, (iii) accept/connect
  paths use the existing `_server_handshake_impl(verify_peer=False)` monkeypatch pattern of
  `deploy/tests/test_worker_listener.py`, and (iv) the positive run with separate processes,
  pair groups and an RO requester mount needs a provisioned Linux host and is skipped here and on
  generic CI — reported as a gate, never claimed. Slice acceptance is the continuation / vector /
  fail-closed set.
- **3. Worker probe service and fixed entrypoint (T087 worker startup).** Create
  `app/workers/extension_probe.py` (`open_worker_probe_service(*, instance_id, slot_number)`,
  `serve_one(deadline)`, `close()`: opens the Task 23 metadata source before binding, relies on
  the existing listener identity check for uid/gid/pair-gid, owns one boot ID/source/listener, at
  most two probes per connection with distinct message ids/nonces and identical request/receipt
  digests, reply built from an actual `read_current` per probe; a new private router created in
  this slice whose semantic registry is empty — `registered_operations=[]`, no placeholder
  handlers, not the T087 semantic registry) and `app/workers/extension_worker.py` (`main()`
  parsing only the fixed argv). FD budget ≤64 total including the source's 13 retained + ≤32
  transient (45 peak), leaving ≤19 for generation/listener/connection/fence descriptors —
  enumerated in the test. No semantic handler, artifact stream, retry or failure-success
  envelope. Control-side probe *use* (deriving slot and blob digests from retained
  prepare/receipt records, same-writer admission) is Task 24's observer, not this task.

**Status (2026-09-18):** slices 1a, 1b, 2a, 2b, 2c and 3 are implemented, independently
reviewed and evidenced (`evidence/extension-channel-task25-1a.md` …
`evidence/extension-probe-service-task25-3.md`); the gates named under "Acceptance and
non-claims" stay open. Next is Task 24 step (a), the journal-v3 contract.

**Ordering with Task 24(a):** slice 1a has no authority gap and touches no existing code, so it
runs now; the `contracts/extension-worker-probe.md` document precedes 1b and is referenced by the
journal-v3 contract (Task 24 step (a)) for the evidence blob it records; then 1b → 2a → 2b → 2c → 3.

**Acceptance and non-claims:** RED-first per slice with retained command output; independent
review per slice; no edits to frozen candidate/receipt/identity bytes or accepted migration
checksums; `app/workers` imports nothing from `app.api`/`app.static`/`app.server`. Explicit
non-claims: no Linux/OCI image qualification; the fixed image entrypoint (`main()`, `bin/worker`)
must actually be implemented and packaged/qualified in its declared image — a generated
image-variable string is not evidence that that image or entrypoint exists; no allowed-manifest
or identity trust; no worker semantic registry; no control observer or admission; no guarantee of
life after response or DB atomicity; final admission still needs its own same-writer
authority/currentness contract; no extra human/key authority, metadata mount or core fixture lock;
no GUI. The actual worker image, native architectures and container/socket runtime are
deployment-operator/host authority (Docker/colima gate) and are reported, never claimed.

## Continuation

After these tasks, continue T040's scheduler/ledger/worker integration and the core semantic-port
dependencies, then the connected browser path under the unchanged canonical plan. A transport
response alone cannot satisfy artifact/semantic success. The checkpoint task is a tested partial
foundation, not a replacement for actual dispatch or the whole scheduler. The seven-story scope
and final release gates are unchanged.

Task5 reconciled the nullable bounded catalog/FrozenTurn effort and all affected execution-port
representations together, including complete controlled catalog -> frozen turn -> port request
tests. Do not invent a default effort ID or coerce `None` to medium. The six amended schema
digests require fresh qualification; historical ADR014 manifests stay unchanged. Actual provider
adapter compatibility, durable model-choice/source binding and production dispatch remain under
T042/T087, not claims established by the representation tests.

Task6 now provides authenticated, bounded, purpose-scoped durable response capture with exact
attempt/command/worker binding and crash recovery. That transport evidence remains distinct from
semantic admission: it does not issue node success, unblock successors or release unknown-use
reservations. Preserve this accepted boundary in the next runtime integration slices.

Task7 first replaces the historical session source at the real web command boundary. Then build
T025's signed deployment request/receipt authority and T087's actual durable lifecycle admission;
an in-memory registry or caller-constructed verification context cannot supply those prerequisites.
Then resolve actual durable extension qualification/binding heads and frozen source/result
records to construct validation context. Connect semantic result acceptance and budget
settlement in one shared transaction before ledger-reconciled scheduler dispatch and the
supported browser journey. The current public `accept_result` and `settle` methods each own a
transaction; calling them sequentially is not the required atomic integration. These are pending
dependencies, not implementation or production qualification claims.
