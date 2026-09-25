# Tasks: DeepTwin web-based open-source multi-agent framework release candidate

**Input**: this feature's spec, plan, research, data model, source trace and seven contracts.
**Status**: the first ADR-009–012/T086 web-framework review is historical and T089's exact multi-
architecture build-input closure remains closed. ADR-014 reopened T086; revision 7 subsequently
closed that design gate. Implementation resumed on 2026-09-15 with the earlier transport-neutral
code preserved and the evidence-based completion corrections recorded below.
**Tests**: explicitly required by the user and spec. Write/observe relevant failures first,
then implement, run focused tests, integrate regressions and record evidence. Existing passes
are historical until rerun. Do not modify a test merely to make a deficient implementation pass.

Each task has an exact destination; paths are repository-relative unless explicitly marked as
private local evidence. Tasks can be split into
smaller substeps with the same acceptance scope. A checkbox requires linked evidence, not code
existence. `[P]` applies only after earlier shared prerequisites and with disjoint file ownership.

2026-09-15 resumption reconciliation: T039/T041/T055/T056/T057/T061/T064/T065 are reopened
without discarding their tested partial implementations. The preceding completed markers
overstated real scheduling, inquiry, paired execution, leak checks or trusted evaluation/human
approval integration. See `evidence/resumption-2026-09-15.md`. This changes completion accounting,
not the accepted feature scope; deterministic value-layer passes remain valid only for their
recorded boundaries.
No task authorizes publication, new paid calls, credential extraction or destructive user changes.
Every feature's completion includes its required event emissions and public/private evidence
tests BEFORE that feature's first live trial. T068 is the comprehensive coverage audit, not
the first deployment of logging after user work has already occurred.

Cross-cutting product boundary: every task targets a self-hosted, web-based, open-source multi-agent framework whose
bundled browser UI is the supported end-user product/control surface. Docker/Compose/Portainer are
external deployment/operator mechanisms; native launchers, DMGs, embedded WebViews and end-user CLI
flows are excluded. Claude is API-only. Codex subscription uses the server-owned managed adapter/
runner, with Codex API as a separate explicit option. Agent browser/external-tool execution and
multi-format original artifacts remain framework-managed capabilities surfaced and audited in the
browser UI.

## Phase 1: Setup and design gate

Goal: close the whole design before new product implementation and preserve known baseline.

- [x] T001 Review all contracts/source mappings and record resolved defects plus V0 decision in specs/001-autonomous-release/evidence/design-review.md; run Spec Kit analysis after this task list is validated (FR-033).
- [x] T086 Re-run the complete Spec Kit cross-artifact and independent architecture review against
  constitution v3.0.1/ADR-009–014 and record the fresh result separately in
  specs/001-autonomous-release/evidence/adr014-independent-review-r7.md before dependent work claims
  design closure (FR-001/032/033). `web-framework-design-review.md` and its first 2026-09-08 DESIGN
  CLEAR remain historical inputs. ADR-014 independent reviews rejected revisions 1–6 and remain
  historical. Revision 7 subsequently closed this gate without changing the implementation,
  release, effect, legal or human-acceptance gates. Close all six original ADR-014 findings plus the five
  revision-1 and four revision-2 review blockers: semantic port
  matrix, durable requalification/binding, external operator-staged OCI services, browser extension
  management, separately installable extension-author/HTTP clients with real-server parity, and
  recursive core dependency enforcement including `app/extensions/**`; stable binding slots and
  core-owned capability selectors; exact separate stage/replace/current-uninstall/superseded-
  retirement request/result arms, separate rollback-retention heads plus owner release, reachable
  A→B→release→strict-ancestor-retirement with preserved history/current head,
  and acyclic request→receipt→postcondition→record/head→consumption/event order; field-complete base
  schemas, exhaustive operation×terminal result artifact cardinality and a separate all-52-operation
  request artifact-input contract (11 non-empty-capable/41 exact-empty), including exact byte-bearing
  export-sink snapshot/prepared-delivery profiles over bounded broker streaming; closed result
  role/media/omissions metadata and one exhaustive terminal/effect/outcome truth; exact
  `{tool_call_ref,result_ref}` tool success output with any output-level effect receipt forbidden; one exact five-field
  `BindingSlotKeyV1` object+digest across config/binding/command/result/event/retention; exact
  T025 router-composition/T087 route-contribution ownership; and portable-HTTPS-only bearer client
  parity with HTTP-loopback pre-parser route denial. Verify no manifest↔service-
  descriptor digest cycle and distinct managed-provider-runner semantics.
  Run a document-structure guard that enumerates exactly eleven normative `*-port-v1` rows and
  proves each is inside a contiguous Markdown pipe table whose header is immediately followed by its
  separator; prose between port rows or any isolated pipe row fails before schema generation.
  Before review, freeze the exact post-ADR-014 input bytes in
  evidence/adr014-review-input-manifest-r7.md; the frozen r1/r2/r3/r4/r5/r6 manifests are not overwritten, the
  review output is not its own input and T075's later implementation-era manifest cannot substitute.
  Do not mark complete until a fresh independent
  reviewer finds no P1/P2 design contradiction;
  implementation, release, effect, license and human-acceptance gates remain separately open.
  Evidence: `evidence/adr014-independent-review-r7.md` records the independent ACCEPT against the
  exact 35-entry r7 manifest (`57c80f1cec6bf674d91f0cd3da802f93fbca1386574558e546ad39c90676f08f`),
  with P1=0, P2=0 and one nonblocking status-wording P3. This checkbox and its status prose are
  post-verdict bookkeeping; no accepted semantic input was changed.
- [x] T002 Snapshot existing dirty-file ownership and rerun baseline Python/browser suites without live calls; record actual results/commands in specs/001-autonomous-release/evidence/baseline.md (FR-031).
- [x] T003 Resolve exact tested platform dependencies in app/requirements-release.lock and the historical packaging manifest, including hashes/licenses; use a scoped build environment and no runtime latest installs (R7, OPS-AC10).
  Evidence: evidence/dependency-lock.md. Exact 67-runtime/80-combined Python closure is locked. Seven native source/archive selections remain historical experiment evidence after ADR-009 and are not web-release dependencies; worker isolation, supply-chain notices and distribution qualification remain in T018/T079/T081–T084.
- [x] T089 Resolve and lock the complete ADR-010–013 Linux arm64+amd64 release **build-input** closure
  in deploy/locks/ and deploy/manifests/. Include existing server/LangGraph/Anthropic/document/PDF/
  image dependencies and native libraries; PyNaCl 1.6.2/libsodium; argon2-cffi 25.1.0;
  upstream faster-whisper 1.2.1 plus the separately named reproducible PCM-only
  `deeptwin-faster-whisper 1.2.1+deeptwin.1`, CTranslate2/tokenizer/NumPy and actual transitives;
  lock the exact input/patch/output hashes and tests proving PyAV/FFmpeg/ONNX Runtime/Silero ONNX
  are intentionally absent while upstream and Silero license notices remain;
  every `Systran/faster-whisper-small` revision file/hash/license; exact Node 24 LTS,
  `playwright-core` 1.63.0/npm provenance, paired Chromium headless-shell and Debian runtime/font closure,
  edge/proxy/base images and browser seccomp; the ADR-013 minimal Codex managed-runner closure of
  separately signed `codex` + adjacent `codex-code-mode-host` + OpenAI `bubblewrap` for both targets,
  an exact trusted Debian Bookworm `/bin/bash` closure and fixed PATH, while omitting zsh-fork,
  `codex-package.json` and mandatory `rg`; separately labelled App Server preview assets only if retained;
  and official age 1.3.2 including Linux binaries, archive/member hashes, Go module notices and
  plugin/network-discovery denial. For each upstream base/tool/third-party image used to build or run
  the distribution, pin one multi-architecture OCI index or Docker manifest-list descriptor and
  every selected platform manifest/config/layer descriptor, including media type, digest and byte
  size. Produce wheel/binary/upstream-image/model hashes, SBOM, license and
  provenance inputs as one `BuildInputLockManifest` with a content-derived
  `build_input_lock_set_digest`; fail on source-only or missing-architecture closure and prohibit
  runtime installs/model downloads. Separate stable-ID `build_input_blockers[]` owned by T089 from
  `downstream_release_blockers[]` owned by T018/T025/T079/T081–T084/T088; locking the input set requires
  the former to be empty and MUST remain possible while the latter keep every release claim open.
  This task MUST NOT claim final DeepTwin service-image digests:
  T081 owns those only after the mandatory implementations exist. T003's macOS lock is historical
  pre-web evidence and cannot satisfy this task.
  Evidence: `deploy/manifests/build-input-lock.json` is structurally verified `locked` with semantic
  digest `2fb6fd8b108ce31f1cc49a9d9ffd3a335584cde677b63de6dceb683731708b24` and file SHA-256
  `212eb478026a2e38b40d882c2525fcee6a3945ed258dbb0d89b615489e62e0bd`. The content-bound
  Codex receipt binds all 17 input files and six Sigstore outcomes; 257 recursive report-shape
  mutations are rejected. Root and independent verification passed 223 Python deploy tests,
  19 Node provenance tests, all aggregate/component/Rust verifier CLIs and deterministic
  same-timestamp regeneration without receipt mutation. The receipt is not a signed creator
  attestation, and the separately owned T018/T025/T079/T081–T084/T088 release gates remain open;
  see `evidence/t089-supply-chain-verification.md`.
- [x] T004 Create module/test scaffolding and secret-free offline configuration in app/domain/__init__.py, app/runtime/__init__.py, app/services/__init__.py, app/adapters/__init__.py, app/operations/__init__.py and app/requirements-dev.txt; preserve existing imports/tests.

## Phase 2: Foundational contracts and authority

Goal: durable evidence/permission/dispatch substrate. All story implementations depend on this
phase. Web session and isolated-worker feasibility are tested here before extensive integration.

- [x] T005 [P] Add strict ref/schema/immutable version/decimal/actor fixtures in app/tests/test_domain_contracts.py, including missing/cross-vault refs and spoofed human actors (data-model §1). Integrated missing/foreign/spoof tests are completed across the contract, storage and permission suites; evidence/domain-foundation.md records the 867-test focused run.
- [x] T006 Implement typed immutable refs/schemas/event registry in app/domain/refs.py, app/domain/schemas.py and app/domain/events.py; export versioned schemas under schemas/v1/ (FR-017/027/032). Evidence: evidence/domain-foundation.md; runtime/export parity and exact event allowlists pass.
- [x] T007 Add migration/CAS/crash/snapshot tests preserving legacy revision/file IDs in app/tests/test_domain_storage.py (data-model §2, OPS-AC05/07). Evidence: evidence/domain-storage.md and evidence/domain-storage-review.md; 57 focused tests pass after four reproduced review defects were fixed.
- [x] T008 Implement additive migration ledger, content-addressed staging/sealing and indexed entity relationships in app/domain/store.py and app/storage.py; no old-byte deletion or second writable truth (FR-029/030). Evidence: evidence/domain-storage.md and evidence/domain-storage-review.md; 84 focused, 898 related and 1,882 app tests pass, with an independent final storage audit. Shared command/domain/budget/runtime atomicity remains T014/T016.
- [x] T009 [P] Add purpose/actor/object/firewall tests in app/tests/test_domain_permissions.py for operational/diagnosis/inquiry/heldout boundaries (G-05, R11). Evidence: evidence/domain-permissions.md; 34 process-local boundary tests pass.
- [x] T010 Implement grant/purpose/ref authorization and explicit compiler-input projections in app/domain/permissions.py (FR-017/020/029). Evidence: evidence/domain-permissions.md and evidence/domain-permissions-persistent.md; 69 focused and 248 shared tests pass, an independent final review cleared the persistent descriptor/grant/projection and same-transaction authorization boundaries, and the independently reviewed 23-test T016 coordinator suite confirms the private integration seam. Authenticated HTTP command enforcement remains owned by T016.
- [x] T011 Add reserve/send/result/cancel/late-result/lease/checkpoint fault tests in app/tests/test_runtime_ledger.py, preserving unknown effects instead of retrying (R07/08). Evidence: evidence/runtime-ledger.md; 35 focused tests and an independent final audit pass.
- [x] T012 Implement durable run/execution/attempt ownership, dispatch gates and idempotent result acceptance in app/runtime/ledger.py (runtime §4). The bounded ledger scope is complete; cross-module budget/permission/dispatcher atomicity remains T014/T016 integration, not an exactly-once claim.
- [x] T013 [P] Add concurrent budget reservation, unknown usage, retries/deadlines and restart tests in app/tests/test_runtime_budgets.py (R10, P10/11). Evidence: evidence/runtime-budgets.md; 61 focused tests and an independent final audit pass.
- [x] T014 Implement finite shared budgets/deadlines/reservations in app/runtime/budgets.py; apply separate product design/execution/growth policies and no automatic API cap (FR-011/013/024). Evidence: evidence/runtime-budgets.md; 112 focused tests pass and an independent final audit cleared the atomic budget+send-intent, restart, cap-reset, path and trigger boundaries at recorded hashes.
- [x] T015 [P] Preserve process-local session/bootstrap/Origin/CSRF/GET-no-dispatch/SSE-canary
  feasibility tests in app/tests/test_local_session.py and app/tests/test_public_events.py (A01–A04).
  Evidence: evidence/local-session.md; 52 focused Python and 63 browser tests pass. This was not an
  ADR-009 loopback or HTTPS release profile; all release auth/first-owner coverage remains T025.
- [x] T016 Implement strict command envelopes/idempotency/public projections and resumable event
  reads with the preserved process-local session feasibility in app/api/session.py,
  app/api/commands.py, app/api/views.py and app/server.py (FR-009/027/029). Evidence:
  evidence/server-api-v1.md; 25 focused, 300 exact integration, 202 storage/domain and 68 browser
  checks pass. This does not qualify either ADR-009 release session profile in T025.
- [x] T017 Preserve the former native worker/packaging feasibility canaries as explicitly superseded historical experiments in packaging/macos/tests/test_native_boundary.py and specs/001-autonomous-release/evidence/native-feasibility.md. They do not qualify the ADR-009 web release.
- [ ] T018 Implement and qualify ADR-010's self-hosted boundary in app/workers/broker.py,
  app/runtime/worker_coordinator.py, deploy/compose.yaml, deploy/security/browser-seccomp.json and
  deploy/tests/test_worker_boundary.py: data-mount-free edge as the only published port (portable
  mode may mount only pinned config and read-only TLS secrets); internal/no-egress
  control plane; separate provider/fetch/Codex egress; networkless browser/document/speech/evaluation/
  runtime-extension workers; pair-specific UDS, fixed UID/peer credential/channel nonce, typed size/
  backpressure/restart reconciliation. Prove non-root Chromium userns+sandbox is active with pinned
  seccomp/init/shm/pids/memory/CPU/FD limits and reject `--no-sandbox`, privileged, SYS_ADMIN,
  Docker-socket, direct network, product/runtime-initiated host-path/post-start/unmanifested mount and
  wrong-peer bypasses. Descriptor/request-declared dedicated extension sockets/named volumes are
  created only by the external operator at service staging. Artifacts stream by digest/
  bounded IPC rather than sharing the whole store; the product manages logical work, never container
  lifecycle. No native launcher, DMG or embedded-WebView dependency (FR-001/014/029).
  T018-A/B/B2/C checkpoints: the independently reviewed authenticated bounded UDS protocol v2 uses
  distinct requester/responder boot identities; the exact-capability coordinator rechecks the
  selected operational-read grant, immutable envelope, budget/lease/deadline and worker generation
  around one non-retrying exchange; and the Compose artifact now records an independently audited,
  deliberately non-runtime-qualified IPC/network/state isolation skeleton. B2 additionally closes
  the bounded authenticated HTTP→root-command→registered-coordinator handoff and durable redacted
  transport observation/status/fail-closed uncertainty across `app/runtime/{ledger,worker_dispatch}.py`,
  `app/api/{transaction,routes}.py` and `app/server.py`. The focused coordinator suite passes 15 tests,
  broker+static topology passes 75 plus 21 subtests (one non-Linux skip), B2's final independent
  focused set passes 127, and the latest shared suites pass 2,298 application (one skip) and 298
  deploy tests. See
  evidence/worker-broker-t018a.md, evidence/worker-coordinator-t018b.md and
  evidence/worker-dispatch-t018b2.md and evidence/static-topology-t018c.md. The checkbox remains open
  for actual Linux UID/peer paths and service images/initializers, actual worker implementations,
  bounded artifact streaming and semantic graph execution, runtime container/network/mount/resource
  enforcement, non-root Chromium sandbox/seccomp qualification and both clean deployment profiles.
  Interpret this unchanged task through two in-task gates, not two new tasks. `T018-foundation`
  requires actual Linux IPC initializers/listeners, peer-credential/channel handshake, bounded
  digest/chunk/receiver-credit artifact streaming and externally staged sandbox/channel enforcement;
  only that foundation is a prerequisite for T087/T090/T024/T043/T044/T070/T081 semantic/runtime
  integration. `T018-final` is the later convergence point: after those owners connect real semantic
  workers, graph/artifact paths and staged isolation, and after T083 supplies its separately owned
  two-clean-host repetition, this single checkbox may close. The whole T018 checkbox is not a
  reverse prerequisite for its downstream semantic implementations, and T083 retains clean-host
  ownership. 2026-09-22: the owned shared gateway prerequisite (the resumption plan's Task 51,
  adopted contract `contracts/provider-owned-shared-gateway.md`) landed over this foundation —
  the fixed `cp-provider` profile, the factory-issued authenticated owner with a retained
  deadline, one reader latch, bounded duplex reads and an identity-bound close, one shared
  frame/fragment grammar for the vault and send engines behind a serial ingress, and the owned
  send dialogue with linearized commit/cancel control (the claim order is the wire order, a
  losing caller never closes a claimant or a successor, every transport fault mapped to the
  closed failure classes); three independent adversarial reviews and one re-review folded in
  RED first (evidence/owned-shared-gateway-task51.md). Still no launcher, route, deployment or
  live provider activation from it.
- [ ] T087 Implement ADR-014's versioned semantic extension framework in app/extensions/, the domain 2026-09-18 slice: the worker's code-owned operation registry now carries `status` (an actual metadata reading) behind the closed `extension-execute-v1` grammar, with the control-side transport sealing the output (evidence/worker-execute-transport-t087.md); `describe_tools` landed the same day over the worker's empty code-owned tool table (evidence/worker-describe-tools-t087.md), and the artifact input leg of the execute exchange landed over T018's bounded stream (evidence/worker-artifact-input-leg-t018-t087.md: declared inputs, profile-gated admission, no registered consumer yet); the first real tool `text_profile` and `invoke_tool` landed over the leg (evidence/worker-text-profile-tool-t087.md: control mirrors the table, verifies the reply's tool, digest, size and usage); the reverse leg landed with the second tool `text_normalize` (evidence/worker-output-artifacts-t018-t087.md: output artifacts offered before the reply, admitted under the mirrored output contract, verified, imported as registered content and sealed); the `ToolCall` record and the effect gate landed (evidence/tool-call-record-effect-gate-t087.md: a ledger row per attempt, write-ahead intent, settled from what control observed, the approval recorded for external effects); the `output_bytes` reservation from the tool's bound landed (evidence/output-bytes-reservation-t087.md: the transport states and enforces its output bound, the dispatcher refuses a binding under it); the approval's verification landed (evidence/tool-call-approval-verification-t087.md: the recorded decision for the run, node and tool scope, exact record, before the send); `cancel`, tool arguments, the vouched dispatch effect is journaled by the dispatcher (evidence/vouched-transport-effect-journal.md; a free retry after a committed send intent stays open as a ledger trust-model change); the tool boundary's effect vocabulary is the ports contract's (evidence/tool-effect-vocabulary-t047-t087.md; the `tool.requested` event's own vocabulary now is the ports contract's seven classes too — 2026-09-23, pinned by test_domain_events, event-metadata export regenerated); the ToolDefinition-backed gate landed (evidence/tooldefinition-effect-gate-t087.md: the authority's definition carries the class, a bound external tool requires its derived scope through a human gate, the transport refuses a disagreeing mirror); per-execution approval binding, a production graph that binds a tool gate, the ports contract's per-tool input count/role binding and every other port remain open. 2026-09-25 slice: the per-execution approval binding and the per-tool input declaration landed (evidence/tool-execution-binding-t087-2026-09-25.md: a `run-approval-v2` decision binds the gate's run/node/scope plus the execution id, executing node and attempt number, v1 stays readable and is refused for dispatch; the transport verifies the exact attempt before the channel and the ledger admits one approval for one attempt's call; each tool declares a `ToolArtifactInputContractV1` checked by the dispatcher at build and before the connection and re-checked by the worker); a production graph that binds a tool gate, the scheduler consuming v2 decisions, an HTTP route for v2 decisions, the atomic approval-use/budget/send claim, the compiled ToolDefinition carrying the input declaration, selectors on the wire and every other port remain open. 2026-09-25 (later): the owner route for v2 decisions landed (evidence/execution-approval-route-t087-2026-09-25.md: the ledger records its own ask per attempt — gate, execution, attempt, the executing node from its execution row, the inputs digest; `GET|POST /api/v1/runs/{run}/approvals/executions` lists the asks and records the owner's decision only when every field equals the ask, replay-safe, conflicting on change; the transport refuses a decision that does not answer this attempt's ask or its inputs digest; `approvals.mjs` shows the exact execution/attempt); no production caller of the ask, the scheduler consuming v2, the atomic claim, expiry and tool arguments remain open. 2026-09-25 (approval screen): the observe page renders the v2 asks from `GET …/approvals/executions` with approve/reject posted to `POST …/approvals/executions`, a retry attempt marked as needing its own decision and a superseded one as authorizing nothing (evidence/approval-screen-2026-09-25.md; unit-tested only — no supported path produces a v2 ask for a browser case yet). 2026-09-25 (scheduler/gate passage): the scheduler consumes v2 decisions per attempt and the claim is atomic (evidence/tool-gate-scheduler-t087-2026-09-25.md: a gated external-tool node's gate scope is no longer a v1 scope; before the handler the scheduler records the ledger's ask for exactly the attempt the dispatcher would send next, with the transport's inputs digest — the first production caller of `request_execution_approval` — and pauses (`awaiting_execution`) until the owner's decision for that attempt; rejected, expired or recovery-superseded stops the visit with a recorded reason (`refuse_execution_approval`); a retry is a new ask; approval use, ToolCall intent, budget reservation and send intent commit in one ledger transaction (`ToolDispatchClaim`), a crash between claim and send is reconciled with no send; asks and v2 decisions carry a server-set bounded expiry refused at the claim and listed/shown `expired`; a real-browser E2E with a test-registered test-actor tool approves, rejects and retries through the approval screen). Still open: no production graph or worker tool binds a tool gate (the path is driven only with the test-actor tool), re-asking after an expiry, tool arguments/selectors, and every other port.
  store/migrations, schemas/v1/extensions/, app/api/extension_routes.py,
  app/api/route_contributions/extensions-v1.json,
  app/operations/extension_deployment.py, app/static/extensions.mjs,
  sdk/python/deeptwin_ext/ and sdk/python/deeptwin_client/ (FR-001/030/032; A13; R16; UX-AC11).
  Replace the generic-envelope-as-SPI assumption with the closed kind↔artifact↔port-contract-version
  ↔trust-tier↔staging-authority matrix and core-owned per-kind operation/base schema/effect/
  idempotency/cancel/outcome/artifact semantics. Generate the 44 exact core-owned
  `schemas/v1/extensions/ports/<port>/{config,request,result,error}.schema.json` artifacts from
  `contracts/extension-ports.md`, including exact scalar/collection/nesting/byte bounds, typed nested
  objects, closed operation input/output arms and terminal/core/port errors. Generate and enumerate
  all 208 operation×candidate-terminal pairs, emitting exactly 127 allowed branches and rejecting
  exactly 81 disallowed pairs with no missing or duplicate candidate;
  enforce `artifacts=[]` for all allowed non-success terminals (especially cancelled codec) and every
  success empty/variable/exact-one output-ref/role/count/byte invariant. Separately enumerate all 52
  request operations and enforce the 11 non-empty-capable frozen/tool/codec/storage/export profiles
  plus 41 exact `artifact_inputs=[]` profiles from §3.9. Export `prepare` and `transmit` must receive
  the exact ordered snapshot/prepared-delivery artifact bindings via the T018 bounded stream; refs or
  shared-store mounts cannot substitute. Codec and storage operation input objects carry no
  competing source/value ref; tool arguments recursively carry no artifact/selector ref; provider/
  model/runner lists equal their frozen records. Test extra/missing/over-bound/wrong-role/media/
  selector, hidden/conflicting ref, frozen/export-list mismatch and missing/widened core ToolDefinition
  profiles, including explicit public-fetch/browser/multimodal/document mappings. Test these plus every required,
  missing, unknown, over-bound, wrong-type, wrong-operation and refinement case in
  `app/tests/test_extension_port_schemas.py`. Validate the closed result role/media/omissions
  matrix, codec target-media/output-omissions equalities and tool output contracts. Treat
  `result.effect` as the sole outcome truth, forbid an error-level duplicate state, generate every
  allowed terminal/effect-family tuple and reject every unlisted tuple, including succeeded external
  unknown/unconfirmed and failed unknown/retryable. Reject an `invoke_tool` success output containing
  `effect_receipt_ref` or an alias even when it equals the common effect receipt; preserve
  `ToolResultArtifactBindingV1` under `result_ref`;
  repeat the eleven-row/zero-isolated-pipe contract-source structure guard before generating schemas;
  the author SDK writes manifests/permitted refinements and only consumes hash-equal read-only base
  bindings. Extension schemas may refine but never replace them.
  Reject all wrong tuples, including a tool using a deployment port, and keep the provider API port
  distinct from the built-in managed-provider-runner agent-loop port.

  T087 owns durable manifest, verified artifact installation history/head, target-installation-keyed
  service-retirement history/head, repeatable qualification history/head, binding revision/head,
  target-binding-keyed rollback-retention revision/head and
  public-event persistence in the applicable DB/CAS transaction. Key
  installation heads by stable extension identity, qualification heads by installation digest plus
  exact qualification-context fingerprint, and binding heads by semantic port plus exact target-
  exact five-field `BindingSlotKeyV1` and its canonical digest. Every config, binding record/head,
  command/result/event and rollback-retention record must preserve that same object+digest; test all
  eleven config roundtrips plus four-field, sibling/nested port-version, binding-ref and digest
  mismatches. Different port versions/slots/selectors under the same scope/purpose coexist; only exact
  same-slot candidates compete, and extension identity remains the candidate rather than an implicit
  key. Carry the exact key and old/new candidate through commands, stale-head/concurrency events,
  rollback, UI projections and `app/tests/test_extension_binding_slots.py`. Supersession/disable must
  atomically create a `retained` head for the displaced exact binding revision; rollback consumes it.
  Implement the closed owner-only release command/result/event and fixed extension route in
  `app/extensions/persistence.py`, `app/api/extension_routes.py` and
  `app/tests/test_extension_rollback_retention.py`: exact five-field slot+digest/current binding/target binding+
  installation/expected retention head, `retained→released` CAS, unchanged binding/installation heads,
  preserved immutable history, and rejection of current/cross-slot/stale/repeated/mismatched release
  or rollback through released/consumed targets. Keep a
  verified installation independent from qualification/binding so expiry or runtime/platform/
  framework/API/schema/port/capability change permits a fresh qualification without reinstalling
  bytes; implement atomic binding supersession/disable/rollback, startup rehydrate/reconcile and
  crash/concurrency/stale-head/suspend/revoke/uninstall/retirement tests. T018 owns only authenticated isolated
  transport/execution, not extension lifecycle persistence.

  Implement code-free owner import plus read/bind/disable/rollback/rollback-retention-release routes
  after T025 authority, and
  `Settings > Extensions` source/license/port/trust/qualification/failure/scope/grant/affected-
  environment observability. Executable extension staging remains external deployment-operator
  authority: consume exact manifest plus acyclic OCI service descriptor and verified one-use signed
  deployment receipt, then require arm-specific postcondition and qualification. Implement the four
  separate closed request/result schema pairs from data-model §3.2 in
  `schemas/v1/extensions/deployment/` and `app/operations/extension_deployment.py`: stage has no
  reachable current service and accepts only never-installed absence or an exact uninstall tombstone
  with monotonic next revision; replace uses expected current head+next revision, current-uninstall targets exactly
  the current tuple and appends a tombstone, while superseded-retirement names an existing strict
  ancestor and preserves the descendant current head. No arm accepts a future record ref. For all extension kinds require the common-envelope
  `preconditions` to be the closed constant `{}` and reject duplicated/overriding/future state there;
  the arm `effect_payload` is the only precondition truth. Enforce exact request↔result equality for
  extension ID/applicable revision/arm, every repeated head/target/proof/snapshot digest and each
  new/current/superseded five-field service tuple. Current-uninstall never accepts old absent;
  retirement failure/unknown never accepts target-after absent. Enforce present/absent/unknown arms
  and one-way request→receipt→postcondition→record/head→consumption/event transactions in
  `app/tests/test_extension_deployment.py`, including A stage→B replace→release every A rollback-
  retention head→retire A with B binding/installation heads byte-identical/dispatchable, A history
  preserved and A rollback denied; then, in a conformance slot with no active-environment refs,
  disable B→release the resulting B retention→verify all dependency sets empty→B current-uninstall→
  C stage from the exact B
  tombstone at the next monotonic revision, with C handshake/qualification/binding/dispatch and no
  revival of A/B. Also cover non-ancestor/cross-extension target, remaining binding/
  rollback/environment dependency, stale preserved/retirement head, tuple mismatch, current-vs-
  ancestor arm confusion, failure/unknown reconciliation and cancel/replay/crash atomicity; product code never
  downloads images/code, controls Docker/containers, creates host-path/post-start/unmanifested
  mounts or rebuilds core. Only the external operator may create descriptor/request-declared
  dedicated socket/named-volume mounts during service staging. Replacement stages a new digest under
  a distinct service identity while the old one remains reachable, then handshakes, qualifies and
  CAS-supersedes the binding; ancestor retirement is the later dependency-checked request and current
  uninstall remains a separate destructive arm.

  Produce separate PEP 517 package roots, metadata and wheel/sdist artifacts for the Python
  extension-author and HTTP/OpenAPI client; install each into a fresh environment rather than
  importing the repository source tree. The
  alternate-client test must install the client in another process/environment that cannot import
  `app`, call T025's actually mounted TLS-bearer HTTPS server routes through its frozen router-
  composition seam, and match the browser path's durable
  receipt/revision/authority/event ordering across restart/concurrency in
  `app/tests/test_extension_client_blackbox.py`. T087 owns extension-specific client methods,
  `app/api/extension_routes.py`, `app/api/route_contributions/extensions-v1.json` and
  `app/tests/test_extension_route_registration.py`; it must register through T025's seam without
  editing `app/server.py` or `app/api/router_composition.py`. It does not own common service-client
  credential/auth/rate-limit/server composition.
  (2026-09-23: the boundary test landed and the real tree has no violation — evidence/extension-architecture-boundary-t087-2026-09-23.md.)
  Enforce the core boundary in `app/tests/test_extension_architecture.py` by recursively walking the
  transitive import graph from `app/domain/**`, `app/services/**`, `app/runtime/**`,
  `app/operations/**` and `app/extensions/**`; reject direct/indirect API/static/server presentation,
  FastAPI/Starlette/Jinja and resolvable dynamic-import bypasses.
  With T018, invoke one repository-out-of-tree OCI tool fixture through the actual broker without a
  core rebuild. T087 owns its separate private conformance-fixture source/build recipe, one exact OCI
  index descriptor with closed Linux arm64+amd64 platform manifest/config/layer entries, manifest/
  service descriptor, SBOM/provenance and license inventory; each host request binds one entry,
  this is neither a T089 core build input nor a T081 core image lock, and T084 gates any publication.
  T081/T083 later own the core distribution and two clean-host repetition and are not prerequisites
  for closing T087. T025 owns common authenticated command/deployment receipt primitives plus the
  frozen service-client auth/router-composition seam; T087 alone owns its fixed extension route
  contribution, extension commands/lifecycle store and client parity over that actual surface.

  Historical pure-contract checkpoint (2026-09-08): inert manifests, non-durable lifecycle values,
  exported schemas, source-tree Python helpers/examples and unmounted in-process client surfaces
  passed their recorded tests in evidence/extension-spi-pure-contracts.md. That checkpoint is
  preserved but does not satisfy ADR-014 or make this task complete. Runtime integration waits only
  for `T018-foundation`; semantic worker/graph integration then feeds `T018-final` rather than waiting
  for the whole T018 checkbox. Durable authenticated routes wait for T025; T086 must independently clear the amended design
  before T087 claims architectural completion.

## Phase 3: US1 — Browser first use, providers and speech (P1)

Independent test: clean web instance and new test vault, browser UI only, description/files/STT, exact model path and stored
understanding; failure/restart preserves input. Fixture and live proofs remain separate.

- [x] T019 [P] [US1] Add Claude API-only/secret/catalog/SSE/stop/retry fake-server contracts in app/tests/test_claude_api.py (P01–P12). Evidence: evidence/claude-api.md; 106 focused and 152 Claude/Codex cross-mode offline tests pass at the recorded hashes, with no live network, Keychain, or paid calls and an independent adversarial adapter audit.
- [x] T020 [US1] Implement the credential-vault abstraction plus a local Keychain adapter and direct Claude API connection/catalog/model-step adapter in app/adapters/keychain.py and app/adapters/claude_api.py, with hidden retries off and no subscription discovery (FR-010–012/029). Evidence: evidence/claude-api.md; direct API-only action guards, credential/catalog invalidation, bounded SSE/tool handling, redaction and fixed transport policy pass the final independent adapter audit. A production web-deployment secret-store binding, product command/consent, durable dispatch/budget and live-provider E2E remain later integration work and are not claimed here.
- [x] T021 [US1] Implement explicitly isolated optional Codex API mode and auth/catalog boundary tests in app/adapters/codex_api.py and app/tests/test_codex_api_mode.py; do not mutate shared subscription credentials (FR-011). Evidence: evidence/codex-api-mode.md; 44 focused and 106 Codex+Claude offline tests pass, with a separate final audit at the recorded hashes and no live calls.
- [x] T022 [US1] Extend actual catalog/capability/default/per-purpose/per-agent choices in app/model_catalog.py, app/model_selection.py and app/providers.py; remove current Claude-subscription readiness wording without relabeling old history (FR-010/FR-011/FR-012). Evidence: evidence/model-catalog-selection.md; 65 focused, 512 bounded integration and 8 browser checks pass, followed by an independent clear row/pointer/epoch/provider-mode review.
- [ ] T023 [US1] 2026-09-18 slice: the intake's server surface on the supported factory landed — `works-v1` (`POST /api/v1/works`, `GET|HEAD …/{id}`, `POST …/{id}/revisions`) sealing immutable `work_revision` records under owner commands (evidence/works-routes-intake-t023.md); 2026-09-19: the first work screen landed over it (`work.html`/`work.mjs`, evidence/intake-page-t023.md: the §5.1 notices, the prompt, a browser-only draft said as such, idempotent saves settled in order, the draft's base revision, conflict with reopen or rebase); sources/files, the microphone, understanding requests and provider/key/model GUI stay open. Add provider/key/model/budget GUI and same-space first-input recovery in
  app/static/index.html, app/static/settings.mjs, app/static/app.mjs and app/api/routes.py; implement secret-safe provider
  command receipts plus `pending intent → gateway store_at → binding CAS → terminal receipt` in
  app/services/provider_connections.py with lost-response/concurrent/restart/orphan-quarantine/
  changed-envelope tests in app/tests/test_provider_connections.py, never journaling or comparing
  key material or reapplying a newly supplied secret under a consumed command ID. Raw create/rotate
  secrets may exist only in bounded no-store request/UDS memory until the gateway receipt; forbid
  journal/log/error/export/metric copies and release references best-effort after response. GET
  connection/status/catalog must be persisted redacted snapshot only with zero vault/gateway/
  provider/network/refresh; only explicit mutation refreshes. UI shows create/rotate/delete durable
  state, `secret_input_lost`, cleanup pending/failure, and distinguishes local DeepTwin erasure from
  provider-side API-key revocation; test changed binding invalidates old catalog/model choice and no
  credential mutation implicitly checks, refreshes or runs a model. Implement actual shared conversation/messages/referenced-object commands in
  app/services/conversation.py and app/static/chat.mjs, with ambiguous/spoofed approval rejection
  tests in app/tests/test_conversation.py; preserve mixed text/file/source revisions, partial/
  unreadable ingestion states and input recovery without mandatory multi-account setup or implicit
  inference. Replace the loopback prototype's “이 컴퓨터에 저장됨/이 컴퓨터의 Codex 로그인과
  공유” and native-app/install-launcher wording with exact instance-scoped storage and managed-runner state; never
  imply that the user's browser device, local CLI or provider app is the DeepTwin host/product
  (FR-002/FR-009/FR-029, API §4, UX-AC01/03).
- [ ] T090 [US1] Implement `CredentialedProviderTransport` and its dedicated gateway in
  app/runtime/provider_transport.py and app/workers/provider_gateway.py with fake-server tests in
  app/tests/test_provider_transport.py: opaque handle resolution, exact provider/origin/method/path/
  projection/budget binding, auth injection at send time, redirect/SSRF/header/proxy/log/error/
  crash canaries, T087-qualified provider-transport manifest/binding, idempotent
  `query_record`/`store_at`/binding reconciliation, bounded redacted responses and no
  credential exposure to provider/model workers or control-plane imports of the vault implementation.
  Explicit create/rotate ingress may pass a raw secret once through bounded no-store control-plane
  request memory to authenticated gateway UDS after exactly one decimal Content-Length ≤96 KiB,
  no Transfer-/Content-Encoding and ≤65,536-byte UTF-8 secret checks; missing/duplicate/framing/
  oversize fails before intent/vault. Normal dispatch/storage uses opaque handles only.
  Test GET/status/catalog snapshot zero vault/gateway/provider/network effect; strict malformed-wire
  zero-effect canaries; create/rotate/delete lost-response and race cases; missing-record
  `secret_input_lost`; create orphan/rotated predecessor/delete retirement; revoke-before-send,
  restart/rollback cleanup and `cleanup_pending → erasure_completed` only after verified removal of
  all locally managed superseded/staging copies. Create/rotate/delete themselves make zero provider
  check/catalog/model/runtime calls; rotate invalidates the predecessor catalog/model authority and
  a new catalog exists only after explicit refresh. UI/tests distinguish local erasure from remote
  provider credential revocation (FR-010–014/029, runtime §6).
  2026-09-25 (open, tests only): the credential-v2 gateway now runs on a real UDS under the kernel's
  SO_PEERCRED identities — root-only Linux test starts gateway and control as separate processes
  under the fixed `cp-provider` UIDs/GIDs (no handshake/connect seams) and drives store/query/replay/
  snapshot/retire; a wrong-UID or wrong-GID requester holding the pair group is refused by the
  gateway with zero vault effect, and an impostor responder is refused by the requester before any
  byte. Channel-level lost-response (create/rotate/retire), same-command races, distinct-command
  rotation races, delete-racing-rotate, `secret_input_lost` for lost create/rotate ingress, zero-effect
  reads and zero provider effect for create/rotate/delete over the owned ingress are pinned
  (evidence/credential-vault-t090.md §2026-09-25). Still open: the HTTP routes still speak the refused
  v1 store/delete shapes (no v2 route), no production bootstrap wires the listener/profile, T087
  provider-transport manifest/budget binding, catalog invalidation and erasure/maintenance.
  2026-09-25 (open, routes): the HTTP create/rotate/delete routes now speak credential-v2 end
  to end. A control-plane command ledger allocates command ids for each `intent_id` act. A secret
  is sent once per command. Ambiguity is recovered by `query_record`, or by same-command retire
  replay. `secret_input_lost` is terminal, and GET reads the ledger only. Covered by 10 full-stack
  tests (evidence/credential-vault-t090.md §2026-09-25 routes). Production wiring, binding CAS,
  catalog invalidation, the unknown-command fence and erasure are still open.
  2026-09-25 (open, wiring + UI): the supported `create_app` composes the credential routes as the
  `credentials-v1` contribution. When the deployment names the gateway endpoint
  (`--credential-gateway-config`, which must be the verified `cp-provider` pair root), startup opens
  the 0600 ledger in the instance state directory and a client over the verified connect/handshake.
  Unnamed, the routes answer 503 with zero effect. A root-only test runs the real factory in a
  control-identity child against a gateway child over a real UDS (SO_PEERCRED): HTTP create, GET,
  rotate, GET, delete and GET. The records page gains a credentials panel (redacted list, add,
  rotate, delete saying the provider key is not revoked, and command_pending/secret_input_lost/
  unavailable states) with node tests (evidence/credential-vault-t090.md §2026-09-25 wiring). The
  gateway-side bootstrap (listener, generation, trusted requester boot), binding CAS, catalog
  invalidation, the unknown-command fence and erasure are still open.
  2026-09-25 (open, gateway entrypoint): `python -m app.workers.credential_gateway_main` is the
  gateway process. It opens the configured vault (never initializes it), validates the root-made
  `cp-provider` generation and binds the listener as the provider identity, and serves
  credential-v2 with the requester boot label read from the same attachment object as the control
  plane (no new trust root). SIGTERM finishes the current dialogue and exits 0, and the logs carry
  event and class names only. Root-only tests start the real entrypoint and the real `create_app`
  under their kernel identities: HTTP create/list/rotate/delete, wrong boot label refused with
  zero effect, SIGTERM mid-dialogue, and a command pending across a gateway restart resolved by
  query. The command ledger is a stated out-of-scope backup category, and export/retention are
  unchanged with reasons given (evidence/credential-vault-t090.md §2026-09-25 gateway entrypoint).
  Compose/image wiring of the entrypoint (the pinned base-compose hash), vault genesis in
  deployment, binding CAS, catalog invalidation, the unknown-command fence, T087 send composition
  and erasure are still open.
- [ ] T024 [US1] Migrate browser MediaDevices/AudioWorklet capture and the existing cumulative
  whisper.cpp POST path to ADR-011's versioned non-overlapping one-second PCM PUT/SSE sessions in
  app/speech.py, app/speech_sessions.py, app/api/speech_routes.py, app/workers/speech.py and
  app/static/speech-input.mjs. Implement RFC 9530 Content-Digest/idempotent sample ranges,
  `SpeechUtterance` finalize boundaries, `SpeechSegment` revisions/edit-epoch CAS, two-window stable
  hint, separate final pass and `ephemeral_only` browser-memory/container-tmpfs staging; ordinary
  chunks are exactly 16,000 samples and one utterance-final tail of 1..16,000 real unpadded samples
  is allowed. Gaps fail the utterance rather than becoming silence; silence finalize can start the
  next utterance. Precheck headers/range, hash uncommitted streamed bytes, commit/enqueue only after
  Content-Digest match; state the host/swap/crash-capture limit and ensure restart marks unfinalized audio interrupted/raw-unavailable and never
  overwrites user edits. Keep the old POST for one major compatibility window only through the
  same auth/CSRF/digest semantics and a separate ≤1,920,000-byte cumulative cap. Map its existing
  sequence/utterance/final query exactly into a per-utterance accumulator, require its prior body as
  exact prefix, append only the suffix, emit only complete 16,000-sample internal chunks, and on
  final emit one remaining tail or zero-tail finalize. Identical non-final is replay; identical final
  may finalize with zero suffix; changed prefix conflicts and restart fails. The bundled UI cannot
  use it. Construct exactly `WhisperModel(local_model_path,device="cpu",compute_type="int8",
  cpu_threads=4,num_workers=1,local_files_only=True)` and call `transcribe(language="ko",
  task="transcribe",beam_size=5,temperature=0.0,condition_on_previous_text=False,
  word_timestamps=True,vad_filter=False,initial_prompt=None,prefix=None,hotwords=None)`, capturing all
  other upstream faster-whisper 1.2.1 defaults plus the downstream distribution/hash in the hashed
  profile. Convert each even-length exact s16le range through validated `<i2` to contiguous 1-D
  float32 times `1/32768.0`; test -32768/0/32767 boundaries and reject raw bytes/int16 arrays.
  Test network-disabled/missing local model, non-NumPy/path/BinaryIO input, VAD enablement,
  permission denial, insecure origin, Korean IME/edit, queue/cancel/finalize/partial-tail/empty-tail/
  track-ended/restart/gap/overlap and no external fallback. RFC 9530 cases include duplicate/trailer
  field, duplicate/member/extra algorithm or params, malformed SF/base64, 31/33-byte digest,
  Content-Encoding, mismatch staging erase/no metadata commit, and identical-vs-changed replay in app/tests/test_speech_api.py,
  app/tests/test_speech_segments.py and app/tests/browser-speech-input.test.mjs. UI copy must
  distinguish microphone capture in the current browser from transcription in the instance-owned
  worker rather than claiming both happen on “이 컴퓨터” (UX-AC09, API §2).
- [ ] T025 [US1] Implement web first-owner/auth/deployment-authority foundations in
  (2026-09-18: the instance's first screen landed — `app/static/start.html`/`start.mjs` at the supported `/`, the setup form on an ownerless instance and the login form otherwise, decided by the public setup state on `/health`; evidence/first-screen-setup-login-t025.md. The deployment-authority recovery port (`deployment_control`, typed `credential_client`) stays open — its receipt/trust-set/generation formats are not fixed by any reviewed contract, so a concrete design proposal awaits a decision (evidence/recovery-port-design-proposal-2026-09-23.md); the offline bootstrap vectors and §5.1.4 guidance were already in place and the real-browser owner lifecycle case landed 2026-09-23 (2026-09-23: password change and revoke-others landed — `POST session/password` rotates the session and ends every session on the old password, `POST session/revoke-others`, account panel on the records page; evidence/password-change-t025-2026-09-23.md).)
  app/operations/setup.py, app/services/deployment_control.py,
  app/operations/deployment_control.py, app/services/service_clients.py,
  app/services/service_client_auth.py, app/api/service_clients.py, app/api/session.py,
  app/api/wire.py, app/api/router_composition.py, app/server.py, DB migrations and exported v1 schemas.
  The common offline `deploy/bootstrap/index.html` must generate strict base64url-no-pad 32-byte
  capability/verifier plus lowercase-hex instance/path IDs and an exact `OriginProfile` for both
  local random-host/path and portable dedicated-host `/`; freeze JS/Python URL/default-port/IDNA/
  digest/capability vectors and reject ambiguous or cross-profile inputs. Portainer/Compose sees
  only verifier/epoch/profile; raw capability is one-time form input, never GET/log/query.
  Implement the 10-minute/five-attempt bootstrap, `OwnerAccount`, exact Argon2id profile and cheap-
  first admission: 8-KiB JSON request/1,024 UTF-8 password-byte cap, independent trusted-source and
  account buckets each burst5/refill1 per 6s, bounded expiring maps plus unknown-account sentinel,
  then one deployment-wide hash, FIFO three waiters and 10s admission. Add login/logout/password,
  32-byte sessions, idle12h/absolute7d and exact session-root HMAC CSRF carried once as
  `X-DeepTwin-CSRF`; test duplicate/comma-folded/noncanonical fields, cookie/Host/Origin/cross-port/
  proxy spoofing and all security headers for both profiles. The common strict JSON/query/header
  parser must reject invalid UTF-8/BOM/duplicate/unknown/top-level/nonfinite/trailing/oversize and
  perform zero mutation/vault/network/Argon work on rejection.
  Persist `ServiceClient` principals and immutable credential revision/head records; implement owner-
  only create/rotate/revoke, expiry≤24h, one-time bearer display, digest-only storage, last-used CAS,
  recovery revocation and predecessor invalidation. Implement a frozen core-owned first-party route-
  composition port in `app/api/router_composition.py` and invoke it exactly once from `app/server.py`.
  It loads only fixed build-installed descriptors from `app/api/route_contributions/*.json`, validates
  unique contribution/route IDs, exact `/api/v1`, auth policy/scope, `app.api.*` factory allowlist,
  rejects duplicates/missing factories/late mutation, and never loads operator/user extension code.
  Mount/register the common routes through that seam; authenticate only an exact single TLS Bearer header with no browser-cookie fallback,
  enforce allowed-network profile and scope before the command service, and apply bounded independent
  client/source/route rate buckets. Add cold-restart, generic composition/route-registration,
  descriptor/path/module/auth/scope/duplicate/freeze failure, create/rotate/revoke/expiry,
  concurrent rotate/use/recovery and rate-limit tests in `app/tests/test_service_clients.py` and
  `app/tests/test_service_client_routes.py` and `app/tests/test_router_composition.py`. T087 owns
  `app/api/extension_routes.py`, its fixed contribution descriptor and extension black-box parity only
  after this common surface is real; T087 does not edit server/composition files.
  Implement update-safe `session-root-init` and stopped-control-plane maintenance: absent→O_EXCL+
  fsync, exact valid existing→verify/no-op, malformed/ownership/epoch mismatch→fail without replace;
  initial genesis is explicit, later recovery requires the matching immutable request-bound signed
  receipt, separate lifecycle/consumption CAS and strictly higher epoch before restricted atomic
  revocation of every authenticator, BrowserSession, ServiceClient, unconsumed human/bootstrap
  capability+verifier and pending approval/consent challenge while historical evidence stays
  non-authoritative. Implement request/receipt canonical preimages, Ed25519/base64url/trust-set vectors,
  separate sealed request/signed receipt channels and prepare/cancel/import/verify/consume logic;
  test bad key/signature/schema, stale/replay, cross-instance/origin, cancel-vs-import and crash.
  Implement `CredentialVault`/`CredentialRootPort` only in app/workers/credential_vault.py and
  credential_root.py with typed app/services/credential_client.py: exact ADR-012 envelope/global
  nonce, update-safe init, crash-safe rotation and retirement maintenance, no control-plane import/
  mount or env/DB/plaintext fallback. Test create-orphan/rotate-predecessor/delete cleanup, rollback,
  all locally managed generation removal before erasure complete, cold restart/tamper/RNG collision,
  and recovery in app/tests/test_owner_sessions.py, test_session_security.py,
  test_bootstrap_delivery.py, test_deployment_control.py and test_credential_vault.py
  (FR-001/027/029/030).
  2026-09-25 (open): owner-recovery restricted reconciliation start — recovery trust-set v2/request/receipt/recovered-root contracts and schemas/v2/deployment exports (app/deployment/recovery_contracts.py, recovery_schema_exports.py), a configuration+root at N+1 over a DB at N verified against the receipt then reconciled in one DB transaction (app/services/deployment_control.py): epoch N+1 control row bound to the request/nonce/receipt, every authenticator/session/service client revoked, earlier bootstrap claims and open challenges expired, pending v1 gate requests expired, open run consents revoked, `auth.recovery_completed`; private-auth storage v2 (one control row per epoch, v1 rebuilt in place); the recovered owner re-binds the same actor. Execution-bound run-approval-v2 decisions recorded before the latest recovery are refused as `superseded` by lookup_execution/resolve. Offline tests only (in-test Ed25519 keys): test_deployment_control, test_owner_sessions, test_session_security plus the owner/session/service-client/run-approval/run-consent/first-party/tool-binding/transport/conformance-storage/schema-export suites, 554 passed serially (evidence/owner-recovery-reconcile-t025-2026-09-25.md). Stays open: the stopped-control-plane maintenance tool and operator recovery adapter (prepare/seal/import/verify/consume/cancel), recovery UI, a real deployment recovery, CredentialVault/credential_client.
  2026-09-25 (open, maintenance tool + recovery screen): `python -m app.operations.deployment_control {status,prepare,cancel,import}` (app/operations/deployment_control.py, operator tooling only) runs with the control plane stopped (serving lock; `busy` otherwise): prepare seals the `owner_recovery` request with a fresh nonce from the root/config/DB at the same epoch N, bound to the new capability's non-secret verifier; import verifies the externally signed receipt against the recovery trust set, binds the verifier, journals `importing`, advances the session root to N+1 and rewrites the deployment configuration (temp+fsync+rename); cancel ends a prepared request (its receipt is then refused), an import in progress cannot be cancelled; re-runs are idempotent and a crash between any two steps completes on re-run. `/health` adds `recovered: true` after a recovery and start.mjs shows the honest recovered re-setup (and a no-form reconciling state). Tests: test_deployment_control_tool.py (round trip into a real reconciling start, busy, cancel, wrong/forged/foreign/replayed receipts, crash at each step), start.test.mjs, and the real-browser browser-owner-recovery-t025.test.mjs (tool + restart + re-setup with the new capability; old session/capability/password refused) — evidence/owner-recovery-reconcile-t025-2026-09-25.md §later. Stays open: a real instance-operator signing adapter (signing exists only in tests), a real deployment recovery, a separate lifecycle/consumption CAS and request/receipt channels, CredentialVault/credential_client; the recovery design file stays "proposal only" (no approval record in the repo beyond a test docstring).
- [ ] T088 [US1] Implement the server-owned Codex subscription runner with the official documented
  `codex login --device-auth` and version-qualified `codex exec --json` paths for the first-release
  Codex authentication/execution profile: verification URL, user code, expiry, bounded status/cancel/reconnect
  and credential separation in app/services/codex_subscription.py and app/api/codex_routes.py;
  DeepTwin exposes authenticated start/status/cancel only, no unauthenticated provider callback and
  no assumption that a container loopback callback reaches the host browser. Callback/PKCE requires
  a future separately qualified runner profile. Register the built-in runner as a `provider`
  extension in the distinct `managed_provider_runner` trust/isolation tier with a versioned manifest,
  isolation profile, qualification and binding; it gets no deployment/vault/work-data authority and
  must pass the same T087 lifecycle/compatibility/event conformance rather than receiving ambient privilege.
  Run against a DeepTwin-projected workspace and dedicated `CODEX_HOME` with explicit model,
  sandbox/approval and versioned DeepTwin-only MCP/IPC configuration; ignore ambient user config/rules,
  hooks, skills, MCP and workspace content, parse bounded JSONL into normalized events and fail closed on
  unknown/mismatched models or incomplete terminals. Treat this as a managed-provider agent loop rather
  than raw model-step parity. App Server is an optional experimental preview for catalog/event UX only,
  never a production execution dependency; without it show the runner-preflight-reported default plus exact user-entered model
  IDs only after actual runner preflight, never a fabricated account catalog.
  Emit exact managed-login requested/pending/completed/cancelled/expired/failed events and add fake-
  runner lifecycle/token-canary tests in app/tests/test_codex_subscription_runner.py; the
  browser UI never becomes a disguised Codex/CLI shell. Remove the release path's ambient host-PATH/
  existing-user-auth discovery through `app/codex_connection.py`; if retained for development
  compatibility it stays explicitly disabled outside that profile (FR-010–012/029).
- [ ] T026 [US1] Run first-use/model/secret/UI integration against the staged ADR-010 service
  topology for both local-loopback and portable-HTTPS origin modes, and authorized actual-provider understanding checks in
  app/tests/browser-first-use-release.test.mjs; verify Claude API and the exact server-side Codex
  device-authorization runner separately, mixed text/readable+unreadable files/source revisions/STT,
  T087-qualified runner binding, and record server/browser matrix, scope and remaining live
  authorization in specs/001-autonomous-release/evidence/us1.md. This qualifies US1 integration
  against staged topology, not the immutable clean-host distribution reserved for T081/T083
  (FR-002, SC-001).

## Phase 4: US2 — Real lens-informed graph design and critique (P1)

Independent test: fixed synthetic work → real design decisions/candidates → separate critique
→ graph comparison and exact preparation; missing candidates/qualification are visible.

- [x] T027 [P] [US2] Add graph schema, producers/types/gates/cycles/join contract tests in app/tests/test_graph_contract.py (R01, SC-003).
- [x] T028 [US2] Implement graph functional schema/compiler and structural-diversity projection in app/runtime/graph.py and app/domain/graph_schema.py; preserve original node/edge responsibility (FR-005/FR-007/FR-013).
- [x] T029 [US2] Load/version the existing 17 atomic lens definitions, use qualifications/composition/conflict/abstention rules in app/services/lenses.py and app/tests/test_lens_registry.py; preserve academic/effect status distinctions (FR-004/019/031). Evidence: evidence/lens-registry.md; 26 focused and 1,875 full app tests pass after independent adversarial review, while production graph/qualification verification and actual scholarly/effect/independence evidence remain T030/T035/T036/T056/T076/T077.
- [ ] T030 [US2] Implement common-work confirmation → lens design decisions → real functional
  candidate generation in app/services/design.py and app/generation_profiles.py, with explicit tests
  in app/tests/test_work_model_confirmation.py and app/tests/test_design_generation.py proving
  goal/completion/authority/risk/unknown confirmation, single/deterministic suitability, immutable
  accepted target and rejection of fixed three-template substitution or onboarding-as-feedback
  (FR-003–005).
- [x] T031 [US2] Complete B4 lifecycle deadline/cancel from preflight through actual owned process termination in app/codex_understanding.py, app/codex_rpc.py and app/tests/test_provider_lifecycle.py; retain B1 prepared-input contract (verification §5).
- [x] T032 [US2] Bind counterexample/validity/candidate-response exact hashes and parent provenance in app/critic_audit.py and app/tests/test_critic_lineage.py; reject forged cross-call evidence (B4).
- [ ] T033 [US2] Build the real isolated Q01 harness adapter/environment under evals/deeptwin/tasks/v01-q01/ and evals/deeptwin/harness/ after reading eval-engineering implementation/environment references; preserve exact Task truth and keep verifier/World Skill/secrets out of agent inputs (B4). 2026-09-24 (open): project-owned task.toml/instruction.md/environment (10 frozen, label-free development cases) and evals/deeptwin/harness/ drive review→proposal→validity→response through a caller `(system, user) -> str` transport over the product render_criticism_prompt + OfflineRunner/Ledger (authored-counterexample lineage added to app/critic_audit.py), with per-call hash manifests, fresh per-trial state, pre-dispatch leak scan and a readiness check on the same read path; offline tests only (evidence/q01-harness-verifier-t033-t034-2026-09-24.md). Stays open: the eval-engineering references are not present in this checkout, isolation is accidental-use prevention (not an OS sandbox), Harbor is not adopted and no live trial ran.
- [ ] T034 [US2] Implement independent semantic verifier and six boundary outcome classes in evals/deeptwin/verifiers/critic.py and evals/deeptwin/tests/test_critic_verifier.py; invalid/no-score is not an agent capability zero (B4). 2026-09-24 (open): verifier with six boundary classes (accept, required defect, rejected counterexample, valid counterexample, unresolved specific claim, insufficient evidence), independent source-derived expectations, Q8 evidence re-derivation from the durable ledger, rule checks first and an explicit SemanticJudge interface; no judge/undetermined → not_judged (score null), invalid → no score (evidence/q01-harness-verifier-t033-t034-2026-09-24.md). Stays open: no semantic judge (human or model) is implemented or qualified, so no trial can yet reach a scored semantic pass outside synthetic fixtures.
- [x] T035 [US2] Freeze initial calibration/scoped qualification/IndependenceProfile and bounded proposed live RunPlan in evals/deeptwin/qualification/calibration/; seek only genuinely missing live authority, execute authorized trials, record joint errors/abstention/valid alternatives without inventing guarantees; any observed/tuned cases cannot be release heldout (FR-006/031, V2/V3). 2026-09-24 (open): prepared offline, live calibration not yet run — frozen evals/deeptwin/qualification/calibration/run_plan.json (claude/api critic and same-model judge, the 10 development cases once each, max 2 proposed chains, per-call max tokens, call/trial/run deadlines, concurrency 1, no automatic retry or model fallback, hard spend stop USD 6.00 at $5/$25 per million input/output tokens) and independence_profile.json (shared provider and model: correlated errors possible, independence not established; observed development cases, never release heldout), both hash-pinned by run_calibration.py; Claude API rig (evals/deeptwin/harness/claude_rig.py) and judge (evals/deeptwin/verifiers/claude_judge.py) with mock-transport tests only; gated entry evals/deeptwin/tests/test_q01_live_calibration.py. No scored live call has been made.
  2026-09-24: the initial calibration was executed live under the frozen, pinned plan and
  independence profile (critic and judge share a model; independence not established). The
  complete tuned result is 6/10, suite `fail`, so nothing qualifies. Run 1 exposed two unstated
  critic-contract rules and a verifier case-key bug, both fixed. All cases are observed/tuned
  development data and never heldout — evidence/q01-live-calibration-t035-2026-09-24.md.
  2026-09-25 closed: joint errors (0 of 1 measurable; 2 not measurable), abstention (15/72 review
  findings unresolved, 2 where a decision was expected; 0/9 proposals abstained) and valid alternatives
  (2/2 accepted) derived from the recorded result by analyze_observed.py; nothing qualifies (6/10 fail),
  independence not established — evidence/q01-live-calibration-t035-2026-09-24.md.
- [ ] T036 [US2] Implement independent candidate reviews, hard gates/ranking/diversity and bounded supplementation in app/services/design_review.py and app/tests/test_design_selection.py; explicitly connect production critic qualified lens routing/composition→LensPack→counterexample→independent validity/response, record contribution/abstention and test input isolation in app/tests/test_critic_lens_pipeline.py. Add immutable select/merge/edit versions, mandatory re-review, exact `DesignApproval`, and preparation of the same `EnvironmentVersion` by CAS in app/services/environments.py with stale/hash/run-binding tests; this prepares a design but does not operationally promote it. Q01 fixtures are not this production implementation and unknown critical qualification cannot pass (FR-004/FR-006/FR-007/FR-008, Constitution VI). 2026-09-17: the environments.py approval now accepts only owner-session-recorded decisions over the exact design subject (app/services/owner_decisions.py; evidence/owner-decisions-design-approval.md); design_review/critic-lens production routing remains open.
  2026-09-25: critic qualification gate — `app/services/critic_qualification.py` derives an issued
  state from a release suite record (frozen release design, suite `pass`, judge separation established,
  exact configuration digest); calibration, fail/incomplete, unestablished judge, another configuration
  or no record are not qualified, and `design_approval_subject` (v2) refuses a passed verdict unless the
  critic is qualified and binds the qualification into the approval. No real release suite has passed
  (T077), so no design is approvable in production today; storing suite records remains T077.
  2026-09-25: each criticism run records the contract-validated proposal status and per-lens
  contribution (exact counterexample ids) / exclusion / abstention with reasons, persisted in the
  criticism record (`lens_use`).
- [ ] T037 [US2] Implement large readable graph comparison, same-focus differences, model/tool details and edit/merge/review/prepare commands in app/static/graph.mjs and app/static/workspace.mjs (UX-AC01, FR-005/FR-008/FR-009).
- [ ] T038 [US2] Exercise real generation→critique→selection and 0/1/2/3 valid-candidate/revision/cancel paths in app/tests/browser-design.test.mjs and specs/001-autonomous-release/evidence/us2.md; no fixture scores presented as live (SC-003/SC-005).

## Phase 5: US3 — Actual graph execution, tools and artifacts (P1)

Independent test: accepted graph with mixed shapes actually browses a controlled source,
creates files and passes full artifacts to later roles; trace survives cancel/restart.

- [x] T039 [P] [US3] Add sequential/parallel/router/closed-join/loop/retry/restart scheduling tests in app/tests/test_graph_execution.py (R02/07/08). Existing tests manually exercise scheduling-state transitions; the 2026-09-16 scheduler slices add real StateGraph+SQLite sequential/parallel/router/join/loop/restart execution coverage; 2026-09-23: retry within a visit over the real scheduler landed (`test_a_retry_inside_a_loop_visit_is_the_next_attempt_of_that_visit`: a loop's second visit fails its first attempt, a restart re-sends nothing, the owner's recovery sends attempt 2 of that same execution, iteration 0 never re-runs and the loop proceeds; evidence/scheduling-retry-t039.md).
- [x] T040 [US3] Implement LangGraph scheduling adapter with persistent opaque cursors and ledger-reconciled idempotent nodes in app/runtime/scheduler.py; never stream raw private graph state (FR-013/030). 2026-09-16/18 slices: StateGraph adapter over the ledger checkpoint journal, bounded loops, human gates on owner-recorded approvals, and gate approval requests recorded as replayable ledger commands with `approval.requested` (evidence/scheduler-t040-slice1.md, run-approvals-human-gate.md, gate-approval-requests-f6.md). 2026-09-18: the atomic semantic acceptance + budget settlement landed as `RuntimeLedger.accept_result_and_settle` (evidence/runtime-result-settlement-t040.md) and attempt dispatch through the scheduler as `NodeAttemptDispatcher` + `build_scheduler(attempts=)` (evidence/scheduler-attempt-dispatch-t040.md; the transport is an injected callable — the worker-side operation is T087/T018, frozen turns/adapters T042). 2026-09-18: the real worker transport landed (`app/runtime/extension_attempt_transport.py` over the worker's `status` operation, evidence/worker-execute-transport-t087.md). 2026-09-18: retry after a sent attempt landed as the owner's recovery (`runs.recover`, evidence/run-recover-route.md: the ledger's retry-safety proof, at most four attempts per visit) and the checkpoint↔attempt binding landed (evidence/checkpoint-attempt-binding-t040.md: each result row names its accepted attempt, re-verified on every read, the run's next reserve and startup). T040 complete; the run trace's attempt layer (T048), worker operations beyond `status` (T087) and the browser E2E (T049) stay with their tasks.
- [x] T041 [US3] Implement sealed branch activation, atomic join winner, visit-vs-attempt IDs and dependency-scoped failure in app/runtime/scheduling_state.py and app/tests/test_graph_execution.py (runtime §2/4). Existing issued-value transitions preserve the in-memory decision; 2026-09-23: the scheduler now runs every join mode (`all_selected`, `any_success` with the branch-ID tie-break, `collect` min..max, `block`/`collect_failures`), the join's ledger execution record is the single compare-and-swap adopted on restart and by a concurrent writer (one successor from one selection), and a producer consumed only by failure-tolerant joins fails as durable evidence instead of ending the run; LangGraph's late pending writes no longer halt the saver (evidence/join-modes-t041.md). A fatal failure still stops the run at its step; routers/joins/gates inside loops stay refused.
- [ ] T042 [US3] Implement provider-neutral multimodal frozen turns and Codex environmentless tool-step bridge in app/runtime/gateway.py and app/adapters/codex_step.py; add actual-page/image/table marker contracts in app/tests/test_model_payloads.py (R04–R06).
- [ ] T043 [US3] Implement controlled egress fetch and sandboxed Chromium navigation/read/screenshot via typed IPC in app/adapters/browser.py and app/runtime/egress.py; enforce source/recipient grants, DNS/IP/redirect and byte limits (R09, PK-06/07).
  2026-09-23 slice: the pinned HTTPS transport behind the broker (literal-address sockets, SNI/cert
  bound to the hostname, no proxy/redirect following, streamed byte limit) —
  evidence/egress-transport-t043-2026-09-23.md. Chromium worker, typed IPC and dispatch wiring remain.
- [x] T044 [P] [US3] Implement bounded declarative DOCX/CSV/JSON/PDF/image creation and safe format validation in app/adapters/documents.py and app/tests/test_document_tools.py; use PDF skill and actual render inspection, not file-exists-only checks (SC-004). 2026-09-13: DOCX/CSV/JSON (evidence/document-tools-t044.md); 2026-09-23: PDF (text layer + per-character rasterized ink) and PNG (sampled pixels) with active-content/encryption/bomb refusal, over the T089-locked document-worker libraries (evidence/document-tools-pdf-png-t044.md). The Korean CID font is referenced, not embedded.
- [ ] T045 [US3] Implement purpose-scoped artifact storage/preview/range reads and multi-format viewers in app/services/artifacts.py and app/static/artifacts.mjs; preserve originals and disclose derived/unsupported coverage (FR-015). 2026-09-23 slice: the owner reads a run's artifacts through runs-v1 (`…/runs/{run}/artifacts`, metadata, the original whole or one byte range, a derived preview with digest/fidelity/coverage for text, JSON and CSV; images left to the browser; PDF/DOCX disclosed as needing the isolated codec worker, never parsed in the control plane) and the viewer is mounted on the observe page (evidence/run-artifacts-t045.md). PDF/DOCX page previews through the codec worker and a vault-wide artifact index stay open.
- [x] T046 [US3] Implement whole-artifact handoff readiness/delivery/receipt and observed-use lineage in app/services/handoffs.py and app/tests/test_handoffs.py; no producer/consumer acknowledgment deadlock (R06).
- [x] T047 [US3] Implement schema-registered dispatcher/grants/effect approvals and replay policies in app/runtime/tools.py; test path/symlink/race/injection/renderer/egress denial in app/tests/test_tool_boundary.py (FR-014/FR-032).
  2026-09-23: side channels landed — in-flight-envelope-keyed `open_in_scope` (no symlink at any
  depth, mid-walk swap, hardlink/fifo/oversize refusal, exclusive writes), `admit_network`
  (declared hosts through the egress broker) and `admit_tool_result` (no active content, sniffed
  formats) — evidence/tool-boundary-t047.md.
- [ ] T048 [US3] Connect live graph/role visits/attempts/inputs/outputs/tools/cancel/recovery to common UI in app/static/runtime.mjs and app/api/routes.py; keep past attempts distinct (UX-AC04/10). 2026-09-18 slice: the route layer landed — `runs-v1` (`POST /api/v1/runs`, `GET|HEAD /api/v1/runs/{run_id}`, `POST …/resume`) over `PersistentRuns` with the injected code-owned run executor (evidence/runs-routes-browser-path.md); the logic half of `app/static/runtime.mjs` landed (evidence/runtime-gui-logic-t048.md) and the supported factory now serves every shell module with the shell on `X-DeepTwin-CSRF` (evidence/shell-assets-supported-factory.md); the cancel and recovery routes landed (`runs.cancel`, `runs.recover`; evidence/run-cancel-route.md, evidence/run-recover-route.md); the attempt layer in the run trace landed (`TraceAttempt`, `producing_attempt_id`; evidence/run-trace-attempt-layer-t048.md: past attempts distinct, the result attributed only to the attempt the bound row names); the supported session client landed (`app/static/session.mjs`, evidence/shell-session-client-supported.md: base path from the location, the token from `GET {base}session`, the observer's request adapter); the run view's DOM half landed (`app/static/run-panel.mjs`, evidence/run-panel-dom-t048.md: rows per node and per past attempt, commands gated by the server's admission, refusals re-read and retained); the run source landed as the public snapshot's run list (`app/static/run-list.mjs`, evidence/run-list-source-t048.md; a creation surface waits on the consent/design line: no production path records a run consent, environment or work revision); the mount landed as the public observation page on the supported factory (`app/static/observe.html`/`observe.mjs`, evidence/observe-page-mount-t048.md: the owner session established from the cookie, the list and panel mounted, honest text without one); the login UI landed (T025, evidence/first-screen-setup-login-t025.md); the intake's server surface landed (`works-v1`, evidence/works-routes-intake-t023.md) and the intake page over it (evidence/intake-page-t023.md); the owner's run consent landed (`run-consents-v1`, evidence/run-consent-record-t048.md: one immutable `run_consent` per command over the exact graph, work revision, environment and budget policy records, the owner's `approval.decided` in the same transaction, replay/conflict, the run route accepting it); the run route verifies that its consent names exactly its inputs and spends it on one run (evidence/run-consent-verification-t048.md); the `environment` record has its producer (evidence/environment-record-t048.md: one record per prepared version, cut from its own head); consent revocation and expiry landed 2026-09-23 (evidence/run-consent-revocation-t048-2026-09-23.md: a revoked or expired consent starts no run, and resume/recover/replay under it refuse); the design arc's own production path, run creation from the intake page and T049's browser case stay open. 2026-09-25: the observe page's approval screen landed (`app/static/approval-screen.mjs`, evidence/approval-screen-2026-09-25.md: the selected run's pending gates and execution-bound asks by exact identity, approve/reject through the owner routes with CSRF, the panel re-read after each decision; a gate approved and one rejected in real Chromium); the run-creation surface and T049 stay open. 2026-09-25 (tool gate): the run view and approval screen follow execution-bound waits (`awaiting_execution`/`rejected_execution` in the runs projection and `runtime.mjs`, an `expired` state and each ask's time limit on the screen) and a gated tool call is approved, rejected and retried through the screen in real Chromium (evidence/tool-gate-scheduler-t087-2026-09-25.md); the run-creation surface and T049 stay open.
- [ ] T049 [US3] Run actual controlled browser/PDF/table/image producer→consumer E2E, then finite authorized Claude/Codex paths, in app/tests/browser-runtime.test.mjs and specs/001-autonomous-release/evidence/us3.md (SC-001/004).

## Phase 6: US4 — Whole or partial own artifacts (P1)

Independent test: a prior original exists; a real GUI action submits test-actor own content,
whole/partial selectors bind exact original, unreviewed area and impact remain separate.

- [x] T050 [P] [US4] Add original chronology/actor/selector/alignment/partial-scope tests in app/tests/test_alternatives.py, including onboarding/comments/empty drafts as non-alternatives (G-01/02).
- [x] T051 [US4] Implement immutable alternative drafts/freeze/original links and separate evidence/change/impact scopes in app/services/alternatives.py (FR-016/017/022).
- [x] T052 [US4] Implement in-place text and table own-version editors with revision-safe autosave in app/static/alternatives.mjs; reasons/instructions not mandatory and synthetic full preview not human whole-work (UX-AC05).
  2026-09-23: drafts as immutable revisions (stale save = conflict, never overwrite), explicit
  freeze through `accept_own_alternative` with changed-line/cell selectors (whole only when ticked),
  editor on the observe page — evidence/own-version-editor-t052-2026-09-23.md.
- [x] T053 [US4] Add PDF/image/structured/time selector and alternative-file flows to app/static/artifacts.mjs and app/api/routes.py; unsupported semantic alignment remains explicit (FR-015/016).
  2026-09-23: `alternative-files` route (runs-v1) with format-bound page/image region, JSON
  pointer and time selectors stored `unresolved`, whole-only where no selector exists; form in
  `alternative-file.mjs` — evidence/own-version-editor-t052-2026-09-23.md.
- [x] T054 [US4] Test three-view switch/refresh/conflict/stale-range recovery in app/tests/browser-alternatives.test.mjs and record synthetic-vs-real evidence in specs/001-autonomous-release/evidence/us4.md (SC-006).
  2026-09-23: real-browser cases against the supported server (three views incl. observed
  differences, autosave, refresh resume, explicit partial freeze, stale-tab conflict → new draft or
  reload, keyboard table edit); evidence labeled synthetic test-actor only, actual-user evidence
  absent — evidence/us4.md.

## Phase 7: US5 — Difference investigation and grounded change (P1)

Independent test: preserved original/alternative → observed difference → competing explanations,
eligible lens questions frozen before new evidence → typed candidate or justified no-change.

- [x] T055 [US5] Implement format-aware differences/trace slicing and system/expert/exception/error/no-generalization hypotheses in app/services/diagnosis.py and app/tests/test_diagnosis.py; no unsupported single-cause claim (FR-018). Recorded observation contracts exist; trace read-back and boundary slicing over real scheduler runs now exist (evidence/run-trace-t055.md); 2026-09-23: the framework observes format-aware differences itself — text line spans, CSV cells/rows, exact JSON paths, whole-artifact for formats it does not parse — against the exact output a sliced boundary produced (evidence/format-differences-t055.md). Page/image/time regions wait on the codec worker.
- [x] T056 [US5] Implement qualified SPLI routing, frozen contrasting predictions, actual fresh evidence, abstain/decline and H_exp update in app/services/inquiry.py and app/tests/test_inquiry.py (FR-019, G-03/04). Inquiry state contracts exist; question generation and evidence-grounded H_exp update remain open as stated in evidence/inquiry-t056.md. 2026-09-23: routing reads the qualified SPLI lens cards' own distinguishing questions, expected contrasts and disconfirmation cues (never generated text), and a concluded inquiry yields an `ExpertJudgmentRevision` — supported/refuted by fresh evidence or unchanged on abstention (evidence/spli-routing-hexp-t056.md).
- [x] T057 [US5] Implement restore/learn/protect typed patch compilation with per-field behavior provenance and semantic/source leak checks in app/runtime/compiler.py and app/tests/test_change_compiler.py; prevent H_phi/current-alternative copying (FR-020/021). Reconcile mandatory supported-inquiry admission with growth §4's system-repair path and make leak checking non-optional before completion. 2026-09-23: leak checking is mandatory on every compilation and growth §4's system-repair path is a second, recorded admission (a `system` hypothesis confirmed over its competitors grounds a `restore` only, over its own confirmation basis) (evidence/change-compiler-admissions-t057.md).
- [x] T058 [US5] Implement active conditional knowledge registry, authority/scope/time/conflict/revalidation and prompt-derived compilation in app/runtime/memory.py and app/services/knowledge.py; ordinary authorized workflow changes remain possible (FR-021/032).
- [x] T059 [US5] Run cross-purpose retrieval/prompt/derived-input adversarial tests including hidden heldout and sensitive personal-profile rejection in app/tests/test_growth_firewall.py (G-05, OPS-AC09).
- [ ] T060 [US5] Connect observation/competing evidence/new questions/change candidates and audit details in app/static/inquiry.mjs, app/api/routes.py and app/tests/browser-inquiry.test.mjs; no forced philosophy quiz or fabricated human answer (UX-AC05/07).
  2026-09-23 slice: the observed difference is sealed per frozen alternative and shown with
  hypotheses `not_generated`, inquiry `not_opened`, no change candidate and no input control
  (real-browser case); real hypothesis/inquiry/candidate display waits on a connected generator —
  evidence/inquiry-observation-t060-2026-09-23.md.
  2026-09-24: the hypothesis generator is connected — on the owner's explicit request one model
  turn over the owner's Claude connection proposes competing explanations of a sealed difference,
  admitted only through `propose_hypotheses` (a lone causal family refused), sealed once per
  difference, all `proposed` (`hypotheses-v1`, observe-page panel; a live set proposed all five
  families) — evidence/hypotheses-generator-t060-2026-09-24.md. Inquiry opening and confirmation
  still need real evidence.

## Phase 8: US6 — Previous queues, product plateau and human promotion (P1)

Independent test: frozen comparable paired runs, all plateau/invalid/restart cases, separate
heldout validation and exact authenticated human promotion; no automatic operating change.

- [x] T061 [US6] Implement frozen related-queue/baseline/candidate/reset/evaluator/budget plans and isolated paired execution in app/services/comparisons.py and app/tests/test_comparisons.py; trace partial-scope downstream effects (FR-022/FR-023/FR-025). Frozen plan/result recording exists; real paired queue execution remains open as stated in evidence/comparisons-t061.md. 2026-09-23: isolated paired execution landed — every (side, item) run on the real scheduler in its own fresh vault and ledger, a code-owned evaluator's exact decimals, the round recorded against the frozen plan (invalid with reasons, measured only when fully valid), and per-item changed/unexplained downstream nodes (evidence/paired-execution-t061.md).
- [x] T062 [P] [US6] Add exact decimal plateau tests for every growth §6.4 sequence, first-floor=0, cumulative small gains, real failure vs invalid, duplicate/restart/lineage changes in app/tests/test_growth_loop.py (SC-007).
- [x] T063 [US6] Implement best_observed/progress_reference/patience/stop-reason state and atomic one-result application in app/services/growth.py; product-only no-development-stop semantics (FR-024).
- [x] T064 [US6] Implement candidate freeze, dataset exposure tracking and heldout/boundary/regression/shadow/limited gates in app/services/validation.py and app/tests/test_validation.py; seen data never relabeled unseen (FR-025). Evidence-free caller-declared passes must not issue authoritative qualification; bind actual evaluator execution/results before closing. 2026-09-23: gate evidence is the framework-recorded comparison rounds themselves; a pass needs valid rounds run for this exact change candidate, so no evidence-free or caller-declared pass qualifies (evidence/validation-evaluator-binding-t064.md).
- [x] T065 [US6] Implement authenticated exact-hash approval/activation CAS/rollback compatibility in app/services/promotion.py and app/tests/test_promotion.py; preserve separate validation/deployment/lifecycle axes (FR-026). Closed 2026-09-17: the caller-declared approver is gone — decisions are backed only by owner-session-recorded `action_approval` records from app/services/promotion_approvals.py bound to the exact bundle hash, validation report and expected environment, consumed by approval record on activation (evidence/promotion-approvals-t065.md). The off-path `authenticated: True` shapes in environments.py (T036) and retention.py (T069) were replaced on 2026-09-17/18 by owner-recorded decisions over exact subjects (app/services/owner_decisions.py; evidence/owner-decisions-design-approval.md, evidence/deletion-decisions-t069.md).
- [ ] T066 [US6] Implement paired execution/round/artifact comparison, actual stop explanations and human version approval/rollback UI in app/static/experiments.mjs and app/static/versions.mjs (UX-AC06).
  2026-09-23 blocker recorded: the US6 chain (recorded comparison rounds → loop → frozen candidate
  bundle → validation report → promotion) exists as issued in-memory values, but frozen candidate
  bundles and validation reports have no store resume path (only loop/ledger/report/promotion-state
  writes), so a version approval/rollback UI would have nothing real to decide over; the durable
  candidate/report resume (and round persistence) must land first.
  2026-09-23 slice (same day): the durable chain resume landed and, over it, the versions surface
  (`versions-v1`: adopt, candidates with gates, approve/reject/defer, exact-revision apply,
  reasoned rollback, experiments with the recorded stop reason; `versions.mjs`) —
  evidence/versions-t066-2026-09-23.md. Paired-round/artifact comparison views remain.
  2026-09-23 paired rounds: persisted rounds re-issued exactly and shown paired (baseline ↔
  candidate run, validity/reasons, score only on valid rounds, unreadable listed) in
  `experiments.mjs`. A side-by-side artifact reading remains: round runs are design
  run_manifest refs with no path to runs-v1 artifacts.
  2026-09-25 side-by-side: a round keeps what each side produced before its isolated vaults are
  removed (`persist_round_outputs`: per item both sides' node results, bounded with truncation
  stated, and the changed / out-of-scope nodes), `versions-v1` rounds carry it, and
  `experiments.mjs` shows the two side by side with changes marked (browser G-06 case, E2E and
  unit tests). A round without kept outputs says so. No production path executes rounds yet.
- [ ] T067 [US6] Run G-06–G-15 end-to-end recovery/loop/heldout/approval cases in app/tests/browser-growth.test.mjs and specs/001-autonomous-release/evidence/us6.md; label test-actor/synthetic vs actual user evidence (SC-007/SC-008).
  2026-09-25: G-06–G-13 and rollback exercised end to end in real Chromium against the
  supported server, over a durable chain seeded through the real services. The rounds come
  from isolated paired execution; the server is restarted over the same store.
  Service-only parts are in app/tests/test_growth_e2e.py. All evidence is
  synthetic/test-actor; there is no actual user evidence.
  G-13 bug fixed: after apply and rollback, a stale approval applied again. An approval
  decided before the newest promotion revision is now refused.
  G-14 (replay of past external effects) and G-15 (lens on/off comparison) have no product
  surface and are recorded as not exercised, so T067 stays open (evidence/us6.md).

## Phase 9: US7 — Complete records and optional creator feedback (P1)

Independent test: setup-to-promotion records, selectable raw/redacted/metadata export with
preview, missing evidence and no network send; backup/restore without original deletion.

- [x] T068 [US7] Audit and close aggregate event coverage for every OPS §4.2 category/failure/
  rejection in app/operations/audit.py and app/tests/test_event_coverage.py, including auth recovery,
  service-client, extension qualification/binding, deployment request/cancel/receipt, managed-login
  lifecycle, credential retirement/cleanup/erasure/failure and speech interrupted/raw-unavailable;
  public projections expose no record handle/secret/provider raw body. Prerequisite feature tasks
  emit their events before live trials (FR-027).
- [x] T069 [US7] Implement manual-only core retention, bounded cache/debug pruning and explicit deletion preview/tombstone/impact in app/operations/retention.py and app/tests/test_retention.py (OPS-AC06).
- [ ] T070 [US7] Implement consistent age encryption through a networkless backup-crypto worker and
  separate `BackupKeyPort`/backup-key volume in app/operations/backup.py, app/workers/backup_crypto.py
  and app/tests/test_backup.py. Never mount provider credential root/records there; exclude restored
  provider/session/backup/deployment-receipt private roots, Codex auth volume/token,
  authenticators/sessions/service clients,
  pending challenges, every unconsumed human/bootstrap capability+verifier and credential handle;
  use exact `instance_backup_key|portable_recovery` manifest modes, require new-owner
  `restored_review` and explicit environment reactivation, and test portable one-shot identity,
  key/volume loss, corruption, stream interruption and external receipt. `backup-key-init` follows
  absent O_EXCL+fsync / exact-existing verify-no-op / malformed fail-without-replace semantics and
  is tested across stack-update reruns (OPS-AC07).
  2026-09-23: the code-owned age caller (`app/workers/backup_crypto.py`, locked-digest verified,
  native X25519 only, identity via owned fd) and `app/operations/backup.py` (closed table
  classification, consistent snapshot, restore proof before `ready`, external receipt, exact key
  modes, staged `restored_review` restore) landed with 12 real-age tests; open until the separate
  networkless worker service boundary (T081) and GUI/migration gates (T072/T073) exist —
  evidence/backup-age-t070-2026-09-23.md. Same day: the content-addressed originals are now
  archived and verified on restore (the database-only archive could not back up any vault with an
  original; 14 tests).
- [x] T071 [US7] Implement snapshot preview/redaction/pseudonyms/rights/missing-evidence manifest and safe archive validation in app/operations/export.py and app/tests/test_export.py; no self-referential archive hash (FR-028/029).
- [ ] T072 [US7] Integrate the T025 `DeploymentControlPort` into verified web-release update/recovery
  guidance, backup-before-migration and safe state in app/operations/updates.py,
  app/operations/recovery.py and app/tests/test_update_recovery.py. Bind exact manifest/origin/image-
  lock/epoch request, lifecycle CAS and unique receipt consumption to the same migration/recovery
  transaction; test cancel-vs-receipt, replay/restart, missing component handshake and backup gate.
  No runtime pip/npm, browser-uploaded recovery receipt or silent new-data loss (FR-030).
- [ ] T073 [US7] Implement anywhere-accessible log/export/backup/retention GUI with actual included-content preview and consent in app/static/records.mjs and app/static/settings.mjs; no mandatory final export step (UX-AC08).
  2026-09-23 slice: work export end to end — actual-content preview (stores nothing, digest over
  exact bytes), explicit consent bound to that digest, stale-preview refusal, sealed consent/
  manifest/bundle records and receipt, owner download; work-page panel `work-export.mjs`. Logs/
  backup/retention screens remain — evidence/work-export-t073-2026-09-23.md.
  2026-09-23 deletion: stored originals are deleted only through a server-computed preview and
  consent bound to its digest; one tombstone per content address, bytes removed after commit,
  readers answer `deleted`, records stay readable, backups carry only live originals; work-screen
  panel and real-browser case — evidence/source-deletion-t073-2026-09-23.md. Deleting other
  records, GUI backup/restore and backup cleanup remain.
  2026-09-25 secret scan: a raw-original export is scanned at preview time (credential shapes and
  the instance's own session tokens/bootstrap capability by stored digest); a finding is shown by
  kind and location only and its original is withheld unless the owner confirms that exact finding
  set, bound into the preview digest and the consent record; the export panel shows the findings
  and the confirmation — evidence/us7.md. Logs/backup/retention screens remain.
- [ ] T074 [US7] Run setup/source/candidate/lens/failed-run/alternative/round/approval export, secret canaries, PDF redaction and interrupted restore cases in app/tests/browser-records.test.mjs and specs/001-autonomous-release/evidence/us7.md (SC-009).
  2026-09-23 partial: work export (actual preview, bound consent, raw only by choice, secret
  canaries absent, stale preview refused) and the records page in real Chromium; fixed the log
  reading `recorded_at_utc` where the projection carries `observed_at_utc` —
  evidence/browser-records-t074-2026-09-23.md. Other categories, PDF redaction and restore remain.
  2026-09-25 partial: in real Chromium against the supported server, the work export now carries
  and previews the work's runs (completed, gated+approved, failed), their consents/approvals, the
  frozen alternative and the source list; the bundle is verified member by member; canaries
  (provider key, password, capability, CSRF, session cookie, credential-looking text, PDF name/
  body, alternative text) are absent from the bundles and every response; a run after the
  preview is refused as stale. Fixed: runs were silently missing from `events`. Interrupted
  restore passes at the service level with real age (15/15). Not exercised: candidate/lens/round
  export (no supported producer; not work-scoped), PDF redaction (the pipeline has none and
  excludes PDF bytes), browser restore (no backup worker) — evidence/us7.md.
  2026-09-25 secret scan (gap closed): raw originals are scanned before export; the credential
  typed into the work text is found by kind and location, never shown, withheld from the bundle
  unless the owner confirms that exact finding set, and absent from every export preview/receipt
  response; the manifest canary check now gets the withheld values. CSRF values cannot be checked
  (the server stores no token to derive them from). Candidate/lens/round export, PDF redaction and
  browser restore remain as above — evidence/us7.md.

## Phase 10: Integrated qualification and release evidence

All US phases are required. This is not permission to stop at an onboarding MVP or to change
unmet features to out-of-scope. Empirical user/effect/signing evidence stays separate.

- [ ] T075 Produce the complete requirement→task→test→observed-result matrix and all invalid/failed/missing evidence in specs/001-autonomous-release/evidence/implementation.md; refresh source hashes/supersession map after final design edits and audit the stable-weight progress numerator, uncertainty and ETA-support state (FR-034, SC-002).
  2026-09-25 draft: generated matrix (`tools/implementation_matrix.py` → evidence/implementation-matrix.md,
  44 requirements, 52/90 tasks done) and evidence/implementation.md listing every failed/invalid/missing
  evidence area, the equal-weight checked-task numerator and why no ETA is supported for blocked tasks.
  Final refresh after T085.
- [x] T076 Freeze and audit final release qualification version/IndependenceProfile/effect evaluation designs in evals/deeptwin/qualification/release-v1/ and evals/deeptwin/effects/ before any release-heldout access; use new datasets not exposed in T035 calibration, preserve both versions, and do not invent actual user alternatives or universal independence thresholds (V3/V6).
  2026-09-25: release-v1 designs frozen before any heldout material exists
  (`evals/deeptwin/qualification/release-v1/{qualification_design,independence_profile}.json`,
  `evals/deeptwin/effects/lens-effects-v1.json`, hash manifest `FROZEN.json`, guarded by
  `evals/deeptwin/tests/test_release_design_frozen.py`): a new sealed set authored by someone
  other than the verifier's developer, 2+ cases per boundary class (a scoped choice, no rate),
  3 repetitions, every case must pass, an independent judge (human or another provider) required
  — neither available now, so release-v1 cannot execute yet; the lens-effect comparison keeps
  the no-lens baseline whole and claims no superiority. Independent audit of v1 found
  identity, single-use, storage, coverage, contract-error, reporting, V3 and §8-arm gaps; release-v2
  (`release-v2/`, `lens-effects-v2.json`, manifest pinning v1 too) addresses them without editing v1
  (evidence/release-designs-t076-2026-09-25.md). Still open: no sealed set, no independent judge, V3 unverified.
  2026-09-25 audit 2 of v2: AUDIT FAIL (B1 calibration-bound verifier, B2 run identity in configuration, B3 v2
  unable to pass, B4 pass semantics, B5 attempts, B6 pre-dispatch tamper, B7/B8 effect data and baselines);
  release-v3 addresses all eight without editing v1/v2, and the product gate now reads only v3 suite records
  (a pass while V3 is unverified is `scoped_pass`, not a qualification). v3 needs its own independent audit;
  its data-driven verifier is not implemented yet.
  2026-09-25 sealed verifier: `evals/deeptwin/verifiers/sealed_critic.py` (`q01-sealed-verifier-1`) loads
  sha256-pinned sealed expectations and a sealed materials bundle at verify time, keeps critic.py's outcome and
  boundary classes (shared code moved unchanged to `verifiers/q01_core.py`), applies the v3 suite precedence
  (fail > incomplete > not_judged > pass) and builds schema-valid suite records; `q01_release_manifest.py` checks
  pre-dispatch manifests and the harness refuses a release dispatch (`run_release_trial`) without a verifying
  committed manifest. 203 tests on developer-authored synthetic dev data only
  (evidence/sealed-verifier-t076-2026-09-25.md). Still open: no sealed set, author or reviewer, no independent
  judge, V3 unverified, harness case-order/spend/single-use/ledger enforcement, and an independent audit of the verifier.
  2026-09-25 audit 3 of v3: AUDIT FAIL (BF1 forged V3/record hash could reach `qualified`, BF2 degenerate,
  reused or cherry-picked results not bound to the manifest, BF3 lens pack treated as dataset material).
  release-v4 (`release-v4/`, `lens-effects-v4.json`, pre-dispatch manifest schema v2, suite record v3,
  `release-v4/FROZEN.json` pinning v1..v4, all manifests, the gate, the verifier modules and the harness)
  answers them without editing v1..v3: the gate reads only `q01-release-v4`, recomputes `record_sha256`,
  caps every v4 pass at `scoped_pass` (`V3_VERIFYING_DESIGN_IDS` is empty; approval tests use a
  test-actor hook); `q01-sealed-verifier-2` fixes 3 repetitions, accepts only issued, unaltered, distinct-trial
  results bound to the manifest, configuration and judge, always re-checks the manifest and derives judge
  separation and V3 from the pinned profile; the harness takes the lens pack from the configuration and checks
  it at every call (evidence/release-designs-t076-2026-09-25.md). Still open: verdict-to-configuration binding in
  design approval, a multi-arm effect dispatcher, no sealed set, author, reviewer or independent judge, V3
  unverifiable under v4, and an independent audit of v4.
  2026-09-25 audit 4 of v4: AUDIT FAIL (B1 best 3 of N trials passed: the repetition slot was caller-assigned
  at verify time and nothing enumerated a manifest's trials; B2 a spent sealed set could be rerun under a
  verifying manifest). release-v5 (`release-v5/`, `lens-effects-v5.json`, pre-dispatch manifest schema v3,
  suite record v4, `release-v5/FROZEN.json` pinning v1..v5, all manifests, the gate, the verifier modules and
  the harness; v4's code hashes are checked against `fb718b6`) answers them without editing v1..v4: the
  harness writes an append-only, hash-chained dispatch journal per manifest (trial id and its PreDispatch slot
  before the first call, only the next of `run_identity.planned_slots`); `q01-sealed-verifier-3` takes the
  repetition from the journalled slot, requires the results to equal the journal and the journal to follow the
  planned slots, and puts the journal head in the suite record; the manifest check refuses a set a prior
  attempt (or a lens arm's prior attempt, or a listed qualification set) already spent; plus N1-N7 (ledger
  selection re-check, `proposed_not_driven`, commit reference and its audit item, judge separation, the gate
  refusing schema-invalid v5 records with a pytest-only test-actor hook, lens-effect checks, a bundle key
  allowlist) (evidence/release-designs-t076-2026-09-25.md). Still open: verdict-to-configuration binding, a
  multi-arm dispatcher with an arm-aware journal, no sealed set, author, reviewer or independent judge, V3
  unverifiable under v5, operator-disk trust limits of the journal, and an independent audit of v5.
  2026-09-25 audit 5 of v5: AUDIT FAIL (X1 the critic's transport and model were never attested: the harness
  echoed the selected model, so a scripted turn that ignored the configured model reached `scoped_pass`, and the
  judge only declared its identity). release-v6 (`release-v6/`, `lens-effects-v6.json`, pre-dispatch manifest
  schema v4, suite record v5, `release-v6/FROZEN.json` pinning v1..v6, every manifest, the gate, the verifier,
  the harness and the attested transport and judge path; v5's code hashes are checked against `4aed36d`, and an
  absent freeze commit now xfails explicitly) answers it without editing v1..v5. The Claude rig's attested turn
  returns the served model, message id and request id that the product adapter parsed from the provider
  response. The runner binds them into the durable ledger, and the harness and `q01-sealed-verifier-4` make a
  release trial invalid (`transport_identity_unattested`) unless every call is provider-reported as exactly the
  configured model, so a scripted callable can never complete one. Judge verdicts count only from durable raw
  judge-provider replies with the reported `judge_model` and request id. Also fixed: a scanned
  `trial_base_dir`, prior attempts with case ids and case sha256s, no gate test hook, a provider-family alias
  table, and a journalled stop written by the T077 dispatcher (evidence/release-designs-t076-2026-09-25.md).
  Still open: the T077 dispatcher itself, provider attestation checked against provider records only after the
  verdict, no attested human-reviewer path, second-manifest cherry-picking and hand-built record provenance
  (organizational), verdict-to-configuration binding, no sealed set, author, reviewer or independent judge, V3
  unverifiable, and an independent audit of v6.
  2026-09-25 audit 6 of v6: AUDIT FAIL (Y1 judge shopping: a journalled trial could be re-verified with the
  judge asked again until it passed, and `verify_suite` never read the judge log, even the repo's own `_full`
  fixture did it; Y2 the request-id anchor was defeatable: no code required distinct ids or the adapter's `req_`
  form, so one reused id for every call, or `x`, passed). release-v7 (`release-v7/`, `lens-effects-v7.json`,
  pre-dispatch manifest schema v5, suite record v6, `release-v7/FROZEN.json` pinning v1..v7, every manifest, the
  gate, the verifier and the harness but no longer the product adapter, which is pinned per attempt through
  `run_identity.harness`; v6's code hashes are checked against `c3204d6`) answers them without editing v1..v6:
  `q01-sealed-verifier-5` judges each trial at most once (an `O_EXCL` judge log under the trial base
  directory, `trial_already_judged`), `verify_suite` re-reads every judge log and requires every critic and
  judge id in the adapter's forms (message id required for critic calls) and distinct across the suite, the
  suite record carries per-trial judge-log digests and the provider-id digest, and the post-verdict audit
  reconciles ids with the provider's records in both directions. Also: `run_identity.critic_transport`
  (an injected rig transport is refused for release), spent-set and transport wording, fixtures that never
  re-judge (evidence/release-designs-t076-2026-09-25.md). Still open: in-process constructed replies, fake
  servers, a deleted-and-rejudged log and a re-asking judge wrapper are caught only by the manual two-way
  provider reconciliation; the T077 dispatcher; no sealed set, author, reviewer or independent judge; V3
  unverifiable; and an independent audit of v7.
  2026-09-25 closed: audit 7 of release-v7 = AUDIT PASS (no blocking; N1–N5 carried to the next
  version/T077); release-v1..v6 preserved byte-identical; execution stays T077
  (evidence/release-designs-t076-2026-09-25.md).
- [ ] T077 Execute authorized bounded actual-provider/critic/multimodal/lens-controlled comparisons and audit all failures/suspicious passes in specs/001-autonomous-release/evidence/live-qualification.md; lack of applicable authority remains explicit, not waived (SC-001/005/006).
- [ ] T078 After T087's extension UI and the frozen T081 candidate exist, perform final visual/
  keyboard/screen-reader/360px/1024px/
  wide/IME/three-mode usability checks and actual rendered artifact QA in
  app/tests/browser-accessibility.test.mjs and specs/001-autonomous-release/evidence/ui-review.md.
  Include `Settings > Extensions` source/license/port/qualification/binding/failure/affected-
  environment inspection, server-supplied exact five-field slot key (including port version)+digest,
  logical slot/capability-selector and same-port coexistence/same-slot competition, exact expected-head
  code-free import/bind/disable/rollback, separate immutable-history/
  rollback-retention state and warned owner-only release, plus operator-only staging handoff
  without exposing Docker/CLI as product UX; use relevant frontend/critique/PDF skills
  (UX-AC01–11).
- [ ] T079 Against the frozen T081 candidate, run integrated fault/security/isolation/permissions/secret/license/dependency checks in
  app/tests/test_release_security.py and specs/001-autonomous-release/evidence/security-review.md;
  include random-host/path cookie cross-port and XSS/artifact canaries, forwarding-header spoofing,
  Chromium sandbox positive probe, UDS wrong-peer/backpressure, control-plane/Docker-socket/direct-
  egress, gateway/backup-root separation, wrong extension tuple/schema, executable runtime download/
  dynamic-mount/core-rebuild bypass, receipt/handshake confusion and no automatic transmission
  (OPS-AC04–11).
- [ ] T080 Measure browser command/event/graph/STT responsiveness under plan.md workload and preserve
  server/browser/hardware/sample/latency evidence in specs/001-autonomous-release/evidence/performance.md.
  For STT freeze Korean fixture length/transcript, speech/silence/noise, cold vs warm model, CPU/
  thread/concurrent load and sample count; report recognition error separately from provisional/final
  latency, fix material UI stalls and disclose every unmeasured quality claim (FR-002/013/031).
  2026-09-25: browser responsiveness measured under the declared workload (20-node/40-edge run,
  1,000+ events) in real Chromium against the real server — command ack p95 127 ms, event visible
  after commit p95 60 ms, no long task while typing or opening the run, records log pages p95
  99 ms (evidence/performance.md). STT unmeasured (no engine; no microphone input); there is no
  push event view or graph canvas to measure; clean hosts (T083) not measured.
- [ ] T081 Build the reproducible open-source web distribution and versioned service images under
  deploy/ for both ADR-010 profiles. The Portainer CE no-terminal descriptor/workflow must verify an
  immutable source commit plus exact Compose digest (tag is display-only) and service-keyed OCI
  index+platform manifest/config/layer locks, using named volumes/explicit networks/security/
  resources with no `build:`, host-relative bind/config, submodule, mutable Git ref, GitOps or
  webhook. Prove the exact CE UI can supply the pinned Chromium seccomp; if its immutable source or
  security profile cannot be applied without terminal/host edits, this mandatory profile is release-
  blocked until a different no-terminal artifact-upload/template path is designed and qualified.
  Package common `deploy/bootstrap/index.html`, both exact OriginProfiles and pinned portable HTTPS
  edge with read-only operator TLS secrets/no implicit ACME. Add update-safe
  `deployment-receipt-root-init`/`deployment-receipt-job`, physically separate private-signing/
  public-verify volumes with job-private-only/CP-public-only mounts, versioned trust set, sealed-request/
  signed-receipt volumes, atomic exchange and exact PlatformSupportManifest edge/image locks.
  Build/export every final DeepTwin core/built-in service image for Linux amd64+arm64 from T089's
  exact `build_input_lock_set_digest`; produce its multi-architecture OCI index v1 in the local/private
  qualification registry or export plus
  exact platform manifest/config/layer media type/digest/size descriptors, and populate the final
  `PlatformSupportManifest.image_locks[]`, preserving SBOM/attestation descriptors separately from
  runnable platform manifests. Package the ADR-014 acyclic `ExtensionServiceDescriptor` schema and
  all core-owned `extension-ports-v1` schema artifacts plus the external operator staging/receipt
  workflow without baking a third-party extension or the private
  T087 conformance fixture into the core image or giving the product a Docker socket. Arbitrary
  future operator-supplied descriptors never enter the core release lock. Build the Linux amd64 portable path and verify dependency closure, manifests, migrations,
  licenses, health/component handshakes and no developer absolute paths. Scaffolding may begin after
  T089/T018-foundation/T025, but this checkbox closes only when final images contain every required implemented
  DeepTwin core/built-in service and worker plus the testable configuration/schema inputs named in
  Dependencies. T078/T079/T083 qualify the candidate after it is frozen; public publication remains
  gated by T084 and explicit copyright-owner license approval.
- [ ] T082 Produce checksums, per-final-DeepTwin-image SBOM/provenance, the exact T089
  `build_input_lock_set_digest` linkage and release-verification scripts for source and packaged
  artifacts under deploy/manifests/; execute external artifact signing only with applicable
  authority and never portray unsigned/unverified output as qualified.
- [ ] T083 Test two fresh hosts independently: macOS arm64 Docker Desktop+Portainer CE entirely
  through the no-terminal operator UI, and Linux amd64 Docker Engine/Compose with the release-pinned
  edge terminating HTTPS from operator TLS secrets. On both, verify the common bootstrap helper,
  exact OriginProfile/CSRF/cookie isolation, first browser setup, microphone/providers/tools,
  edge/internal network, worker crash/restart, browser close and update/migration/restore flow.
  Exercise request cancel/import races, bad/replayed/cross-instance receipt, trust-set and independent
  component gates; verify the common service-keyed OCI index-lock/source/Compose/schema set plus each
  expected platform manifest/config/layer digest. On both, run one shared
  bounded US1→US7 browser smoke through graph preparation, run/artifact handoff, own alternative,
  inquiry/change, prior-queue comparison, exact test-actor promotion and export. Reuse frozen
  qualified semantic/effect fixtures rather than claiming a second OS effect evaluation; record exact runtime/Portainer/browser limits in deploy/tests/ and
  specs/001-autonomous-release/evidence/deployment-report.md. Do not duplicate semantic lens/effect
  evaluation merely for OS coverage, but do run every deployment/security boundary on both
  (SC-001). On both hosts, externally stage the same repository-out-of-tree tool OCI extension by
  exact descriptor and signed receipt, prove actual T018 broker invocation plus restart,
  requalification, different-slot coexistence, same-slot binding rollback and
  A→B→release-A-retention→retire-A preserved-current behavior in `Settings > Extensions`, then
  B-disable→release-B-retention→B-uninstall→exact-tombstone→C-restage/dispatch, with no active-
  environment refs in that conformance slot. Verify all packaged core port-schema digests and
  operation-terminal result cardinality plus the 52-operation request artifact-input profiles and
  five-field binding-key schema/digest, and on the portable HTTPS host run the separately
  installed HTTP/OpenAPI client process with no `app` import against the actual T025-composed TLS-
  bearer server routes to match browser durable receipts/revisions/authority/events. On the HTTP-only
  loopback host send no real bearer; use only a fixed non-secret Authorization canary to verify that
  bearer automation is unregistered or denied before bearer parsing and no cookie/plaintext fallback exists
  (R16, OPS-AC11, UX-AC11, V8).
- [ ] T084 Prepare browser user guide, instance-operator deployment/backup guide, framework
  architecture/contribution/extension-authoring/API-compatibility/security/third-party notices and
  source-license inventory in docs/release/, LICENSES/ and NOTICE; prepare the repository license
  recommendation and require the copyright owner's explicit license approval before adding/
  publishing it; scrub developer usernames, absolute workstation/temp paths and private source
  locations from publishable source/docs/evidence. Document and verify the boundary among (1) the
  official browser product/control surface, (2) external instance deployment/operator tooling,
  (3) server-owned internal CLI/worker implementation artifacts and (4) optional API/SDK integration;
  separately document the installable extension-author SDK, installable HTTP/OpenAPI client and
  external operator OCI-extension staging boundary. Include their license/NOTICE/source-offer
  closure, but publish none before the copyright owner's explicit repository-license approval. The
  browser guide and quickstart must not expose a native-app or end-user CLI journey. No user
  private PDFs/data/keys/history may leak and no automatic public push is allowed
  (FR-001/032).
  2026-09-23: drafts landed in docs/release/ (browser user guide incl. account panel, operator
  deployment/backup guide, architecture, contributing, extension authoring, API compatibility,
  security, third-party notices from lock/manifest metadata with unknowns marked, surface
  boundaries, source-license inventory, license recommendation). No LICENSE/NOTICE added: the
  copyright owner's explicit license approval is required and pending; the publishable-tree scrub
  and the Compose gaps it found (backup service without backup-key volume/init, ipc-root-init
  boot-secret regeneration) remain open.
  2026-09-23 scrub: workstation paths replaced with placeholders in 40 tracked documents (test
  canaries kept); `docs/lenses/source-map.md` is pinned by the reviewed lens bundle and awaits a
  re-review — evidence/publishable-scrub-t084-2026-09-23.md.
  2026-09-24: the owner approved Apache-2.0; `LICENSE`, `LICENSES/Apache-2.0.txt`, `NOTICE` and
  the `pyproject.toml` license metadata landed (evidence/license-approval-apache-2.0-2026-09-24.md).
  SPDX headers, per-image notices/source offers, the inbound-contribution mechanism, the Compose
  gaps and the pinned lens file remain open.
  2026-09-25: SPDX coverage via `REUSE.toml` (Apache-2.0 default, upstream files under
  `LicenseRef-Upstream-Terms`); `reuse lint` compliant 1671/1671, guarded by
  `app/tests/test_reuse_compliance.py`. Per-image notices/source offers, inbound-contribution
  mechanism, Compose gaps, pinned lens file and quoted-text rights remain open.
- [ ] T085 Run full regression plus quickstart.md acceptance, reconcile every checkbox/result and produce specs/001-autonomous-release/evidence/release-report.md separating engineering/live/effect/human/signing readiness and checking final progress/ETA claims against actual task evidence; mark the goal complete only if the latest required delivery is genuinely achieved (FR-034, SC-010).

## Dependencies and parallel work

T001 is preserved V0 history; ADR-014 reopened the all-design architecture gate and revision 7's
fresh independent review closed T086 with P1=0/P2=0. Its first DESIGN CLEAR and rejected revisions
1–6 are historical. T002–T004 precede foundational
implementation, and completed transport-neutral work is not discarded.
Within foundations, test then implementation pairs are T005→T006, T007→T008, T009→T010,
T011→T012, T013→T014; T018 and T087 follow the common authority and schema foundation.
T015→T016 is the preserved local-profile command/session foundation, while T017 is completed
historical native-feasibility evidence and is not a prerequisite for either web task. Ledger/
budgets/session integrate after refs/store/permissions. No two agents edit shared server/schema files.

The current web-release critical path re-enters T086, then uses the already closed T089 build-input
scope and proceeds through T018-foundation/T025/T087. T018-foundation means actual Linux IPC
initializers/listeners/peer handshake, bounded artifact stream and staged sandbox/channel enforcement;
it is not the whole T018 checkbox. T090 requires the qualified T018-foundation IPC, T025 vault/
deployment foundation and T087 semantic provider ports. T023 may build conversation/UI
against fakes earlier but cannot close provider mutation before T025/T090. T024 requires the
T018-foundation speech channel; T043/T044/T070 and T088 likewise integrate through that foundation
with their own semantic worker responsibilities; T088 also requires T025/T087. T026 follows
T023/T024/T025/T087/T088/T090 and is staged-
topology US1 evidence only. T081 may scaffold containers from T089's build-input lock after
T089/T018-foundation/T025, but final closure waits for every mandatory service/story implementation through
T073 plus T087/T088/T090 and packages T087's extension-service descriptor/receipt schema and
operator workflow. It freezes the candidate and uniquely closes only DeepTwin core/built-in service
`image_locks[]`; it does not bundle or lock arbitrary third-party services or T087's separately
locked private conformance fixture. T082 follows the final T081 artifact and binds its core-image
provenance to T089's build-input lock. T078 final UX qualification follows both T087's extension UI
and the frozen T081 candidate; T079 security qualification also runs against that candidate, so
neither is a prerequisite for T081.
T083 follows complete US1–US7 integration/evidence (T026/T067/T074), semantic/live and UI gates
(T076–T079), T087's locally integrated out-of-tree extension/client proof, and T081/T082. T083—not
T087—owns two-host extension repetition plus portable-HTTPS client parity/loopback denial, avoiding a
T087↔T081/T083 cycle. T075's
final matrix refresh follows T083, while T084 documentation and T085 final report follow the final
artifact/evidence. Dependency arrows gate completion, not harmless contract-first test work.
After the downstream semantic/runtime owners and T081 have connected their paths, `T018-final`
reconciles the unchanged T018 acceptance set; T083 alone retains the two-clean-host repetition used
for final closure. Thus T018-final is a convergence gate and never a prerequisite of the work whose
evidence it consumes.

After foundations: US1 supplies actual provider bindings; US2 supplies approved graphs; US3
supplies original execution; US4 supplies alternatives; US5 supplies changes; US6 proves
comparisons/promotion. US7 export depends on all event categories but retention/backup modules
can be built independently against frozen store contracts. Integration retains this order.
Separate story test fixtures let components be tested before predecessors' live qualification,
but fixture-only predecessors cannot establish whole-journey completion.

Parallel examples (after common prerequisites, with explicit file ownership):

- US1: T019 Claude fake tests alongside T024 isolated STT tests; integration is root-owned.
- US2: T027 graph tests alongside lens registry source work; B4 ledger/harness/verifier get
  separate files, and no scored C run precedes their checks.
- US3: T039 scheduler tests alongside T044 document tools; gateway and sandbox broker integrate
  after each independently passes its contract.
- US4: selector/backend tests alongside artifact-editor UI using frozen API fixtures.
- US5: diagnostic unit cases alongside inquiry UI; compiler/permissions are reviewed separately.
- US6: T062 plateau pure-state tests alongside validation fixtures; activation waits for both.
- US7: backup, export and retention modules can be separate owners after store/ref contracts.

## Implementation strategy and evidence rules

For each task: read its contracts and existing code → write the smallest behavior test and
observe a relevant failure → implement → focused checks → separate spec/quality review → record
exact result and limitations. Run story E2E then whole regression at integration points. Tests
of irreversible effects use dedicated fixtures/sandboxes, never the user's active services.

The suggested first increment is US1 on the completed foundation, followed by each story's
explicitly assigned integration tests; any substitute boundary is fixture-labeled and does not
prove the real predecessor. US1 is not a release scope or stopping point. The final delivery
requires all seven stories. Development commands are internal agent work, not end-user
deployment or product-use instructions. Checkpoints preserve state without asking routine approval again.

Record task estimates/throughput when evidence exists and update weighted progress.md (FR-034).
Stop and request direction only for genuinely new authority/core-intent changes; meanwhile
continue safe independent tasks. Do not convert the product's three-round plateau into a
development retry limit or mark an unmet requirement complete to finish the session.
