# DeepTwin autonomous delivery progress

Updated: 2026-09-13. Status: active; ADR-014 revision 7 independently closed the V1/T086 design
gate, while T089's exact multi-architecture build-input scope remains closed and isolated runtime
implementation remains active within its now accepted architecture boundary.

## Outcome and authority

Deliver a documented, self-hostable, web-based, open-source multi-agent framework target with evidence for the complete
design -> operation -> own alternative -> inquiry -> old-queue reevaluation -> human
environment promotion journey. Publication and the creator's final subjective acceptance
are separate. The current repository has no license and is not yet a legal open-source release;
T084 requires explicit copyright-owner approval. Unmet mandatory features or required external authorization prohibit claiming
the full release goal complete.

The user accepted autonomous recommended decisions and continuous work on 2026-09-07.
Keep existing changes, explicit product requirements and safe execution boundaries. The
user also requested approximate percent and, when supportable, remaining-time estimates.
The user then explicitly confirmed early stopping describes the PRODUCT reevaluation loop,
not development. This goal has no three-attempt development completion/stop rule.

## Approximate weighted progress

Weights represent final delivery work, not lines, test counts, subagent activity or elapsed
time. Completion fractions are engineering estimates supported by the listed evidence.
Communicate rounded to 5 percentage points; recalibrate if scope/evidence changes and explain
the change. Never force monotonic progress or hide an unresolved mandatory requirement.

| Work package | Weight | Estimated fraction | Contribution | Evidence/status |
|---|---:|---:|---:|---|
| Whole-product design, contracts and traceability | 20 | 1.00 | 20.0 | Constitution 3.0.1 and ADR-009–014 preserve identity. Independent reviews rejected revisions 1–6; revision 7 passed with P1=0/P2=0 and one nonblocking wording P3 against a 35/35 verified manifest. Final implementation-era hashes remain T075 |
| First use, input, providers, model control and persistence | 15 | 0.60 | 9.0 | Claude API-only and both Codex adapter modes, catalog/default routing and bounded conversation/provider components exist; the simplified T023 browser intake shell passes. The T090 control-plane arc is now implemented and once adversarially audited (REJECT findings fixed): vault core, credentialed provider transport, ingress wire checks, authenticated routes, and the control↔gateway frame channel with an HTTP→frames→vault end-to-end test. Real UDS endpoint qualification (Linux canary), T087 provider-transport manifest, budget binding, T023 UI continuation and full browser speech qualification remain |
| Actual graph generation, criticism, selection and approval | 15 | 0.20 | 3.0 | The offline design arc is now driven end to end and twice adversarially audited: generation over the untrusted model_turn boundary (design_live), the four criticism stages over the same boundary with fold-issued verdicts and per-call records (design_criticism_live), durable persistence with recomputed call provenance (persist_criticism_run), the honest ≤3 structurally-different selection pool with request binding, exact human DesignApproval + EnvironmentVersion preparation CAS (environments.py), and bounded 1–3-round supplementation orchestration (design_orchestration). The 2026-09-13 design-batch audit (REJECT: 2 critical — constructible verdicts reaching "prepared", fabricated runs persisting — plus 4 major, 4 minor) is fully closed with fold/driver-issued values, content-hash verdict binding, atomic persistence and environment-scoped approvals (evidence/design-batch-audit.md). Earlier graph/compiler audits stay closed. No provider adapter is bound (live calls are user-gated), no UI (T037/T038), no storage binding of proposals/approvals, and no real qualification (T033–T035) |
| Actual multi-agent runtime, framework tools and artifacts | 20 | 0.30 | 6.0 | Durable run/attempt, budget and root-command substrate plus a historical pure extension-contract checkpoint exist; T018-A/B/B2's audited transport and the bounded artifact byte route remain closed. New audited value-layer contracts (2026-09-13): sealed router activations with atomic first-applied join winners and batch tie-break (T041), provider-neutral FrozenTurn with eight profile input allowlists and authority-free step-output admission (T042 part), whole-artifact handoff readiness/delivery/receipt/use with four distinct evidence levels (T046), and the closed tool-dispatch boundary with exact-equality dedup, effect approvals recorded in envelopes and unknown-outcome holds (T047 core) — all four REJECT-audited and every finding closed with 22 regressions (evidence/us3-batch-audit.md). The LangGraph scheduler adapter (blocked on a main-checkout dependency edit), semantic ports integration, durable extension state/staging, real workers/tools, egress broker and all US3 UI/E2E remain |
| DeepTwin inquiry, repeated evaluations and promotion | 15 | 0.30 | 4.5 | The full US4–US6 offline value-layer chain now exists with issued-value contracts and tests: alternatives/diagnosis (audited 2026-09-12), inquiry, restore/learn/protect change compiler, frozen comparison plans/rounds, the §6.4 exact-decimal growth loop, sealed validation with permanent dataset exposure (FR-025), and human promotion with exact-hash activation CAS/rollback (FR-026); a second independent adversarial audit (2026-09-13) rejected the batch with 1 critical + 8 major + 9 minor and every code-level finding is closed with 15 RED-first regressions (evidence/us6-batch-audit.md). Storage binding/transactions, T058 knowledge registry, growth firewall tests, all UI (T060/T066), browser E2E (T067) and any real-user or live evidence remain |
| Full-journey integration, security and effect evidence | 10 | 0.15 | 1.5 | The bounded shared permission/budget/runtime transaction and API slice plus exact build-input integrity are verified; T018-B2's six reproduced handoff/observation defects are closed with 127 focused passes and a 2,298-pass/1-skip app regression, but this is not whole-journey, both-target-architecture, worker-runtime or effect qualification |
| Web deployment, recovery/update, release documentation | 5 | 0.34 | 1.7 | T089 locks exact multi-architecture build inputs and T018-C adds an audited static state/network/IPC isolation skeleton; its control listener, profile split, images, initializers, Linux/Portainer behavior, recovery/update and clean self-hosted distribution remain unqualified |
| Total | 100 | — | 45.7 | User-facing estimate: roughly 45% (45.7 unrounded); the design gate is closed while T018/T025/T087 and complete journey gates stay open. 2026-09-13 recalibrations: growth 0.00→0.30 (audited offline US4–US6 engine chain), graph/design 0.07→0.20 (audited offline design arc), runtime 0.24→0.30 (audited T041/T042/T046/T047 value-layer contracts), while storage/UI/E2E/live majorities stay open in all three |

Initial estimate: about 15%; immediately before ADR-009 the working estimate was about 34%.
The 2026-09-08 correction from a native macOS app to an open-source web framework invalidated
native packaging credit and reopened design consistency. The first T086 review later closed that
gate, but ADR-014's extension audit reopened it after finding six reusable-framework gaps. The
revision-7 formatting-only remediation passed a new independent review after six ADR-014
rejections; T089 plus the T018-A/B/B2/C
checkpoints retain their scoped build-input, internal transport and static-isolation evidence. The
honest rounded estimate remains roughly 35%; transport-neutral domain/provider/web UI work did not
regress. Whole-goal ETA remains unsupported until at least one complete story integration
establishes comparable implementation throughput. Claude
subscription approval is no longer a dependency after the user's
API-only correction. When enough comparable implementation tasks are verified, report a
range for remaining engineering work separately from real-account test/signing readiness;
do not turn unknown external readiness into a promised date.

## Current work

- [x] Record durable goal and latest autonomous delegation.
- [x] Reconcile current worktree and preserve existing dirty changes.
- [x] Restore existing Spec Kit 1.0.4 templates/scripts into this worktree without modifying
  the original checkout or changing the branch; write constitution v1.0.0, then amend to
  v2.0.0 for the user's explicit Claude API-only correction, v3.0.0 for the open-source
  web-framework identity and authority boundary, then v3.0.1 for the official browser-product clarification.
- [x] Reconcile the ADR-014 extension-framework additions through a fresh independent T086 review;
  revisions 1–6 were rejected; revision-7 canonical requirements/source/decision mapping repairs
  the isolated artifact-codec Markdown row and adds a structural guard while retaining the removed
  duplicate tool-output effect receipt, export byte route, exact result
  metadata, sole effect/outcome truth and exact
  five-field key, all-52 request profiles and separate durable
  rollback-retention/release state that makes ancestor retirement reachable without deleting binding history; final release-byte/
  result supersession reconciliation remains T075. The r7 review accepted with P1=0/P2=0.
- [x] Complete the amended experience, semantic extension/runtime, data, deployment, verification,
  SDK/client and release contracts by closing T086's independent post-remediation review.
- [x] Re-review all contracts against each other under the ADR-009–012 framework-core/web-control-
  plane/deployment/extension split; that first T086 Spec Kit pass, its three reviews and all six
  rejected ADR-014 reviews through r6 remain historical evidence, while revision 7 is the accepted
  current design gate.
- [x] Produce one dependency-ordered implementation/test plan before product code changes.
- [x] T002 rerun existing baseline suites and preserve pre-existing source fingerprints; Python729 pass, browser161/163 with two existing prototype scroll defects recorded.
- [x] T003 historical pre-web platform dependency lock and scoped build environment complete; its
  native packages are not current release dependencies. T089 owns exact build inputs; T081 owns
  final service images; T082 owns per-final-image SBOM, source-to-binary provenance, hermetic
  native-Linux repetition and authorized signing; T084 owns the 73 Codex/Rust missing license-text
  cases, notices, source offers, license selection and redistribution/legal/publication approval.
- [x] Storage/CAS, persistent permission firewall and bounded T016 transaction/API seam implemented
  with independent findings recorded; T025 still owns release auth, OriginProfile and first-owner authority.
  The service-client registry/bearer/route-composition slice passed an independent re-audit on
  2026-09-12 closing all six 2026-09-09 REJECT findings (two P1, three P2, one P3); see
  evidence/service-client-auth-reaudit-t025a2a3.md.
- [x] Preserve the former native N0 canary only as historical experiment evidence; ADR-009 requires
  a new self-hosted web worker/broker qualification and it contributes no release credit.
- [x] Historical unbranded Chromium candidate launched through Playwright and rendered DOM/canvas/
  PNG; it gives no current release credit. T089's browser build inputs are locked; T018/T079 own
  the actual worker/isolation and integrated-security gates, T081 owns final images, T082 owns their
  packaged provenance and signing, T083 owns clean-host distribution, and T084 owns redistribution
  notices/legal review.
- [x] T013/T014 finite budgets close concurrency, restart, deadline, unknown-use, retry,
  persisted-tamper and atomic budget-plus-send-intent boundaries; the 112-test budget scope and
  its independent audit pass, with bounded root HTTP orchestration closed under T016.
- [x] T014/T016 root transaction shares one permission/budget/runtime command boundary; T016's
  final evidence records 25 focused, 300 exact integration, 202 storage/domain and 68 browser checks.
  This does not qualify T025 release authentication or either deployment profile.
- [x] T019/T020 Claude direct-API adapter and fake-server contracts complete with 106 focused,
  152 cross-provider offline tests and an independent final adapter audit; this is not a claim of
  browser-product integration/durable-dispatch/live-account completion.
- [x] T022 dynamic provider catalog and immutable default/per-purpose/per-agent selection completed
  its recorded scope; T023 provider/conversation GUI integration is active.
- [x] ADR-009–014 web/extension framework design: constitution v3.0.1 keeps the product identity;
  canonical spec, plan, API/runtime/operations/experience/verification contracts and affected tasks
  contain the revision-7 ADR-014 remediation, including the separate extension-port contract, and
  the fresh independent r7 T086 review found P1=0/P2=0. Implementation
  and empirical release qualification remain separate.
- [ ] T087 historical pure-contract checkpoint: inert extension manifests/lifecycles/scoped bindings,
  deterministic schemas, a dependency-free Python kit/examples, and browser/headless command-port
  conformance pass. Immutable installation-record linkage, time/platform/capability-bound
  qualification, latched active-binding invalidation, atomic declared-capability binding and
  fail-closed denial logging have also passed the focused suite. Runtime dispatch remains
  deliberately unavailable. ADR-014 additionally requires core-owned semantic ports and 44 base
  schemas plus operation-terminal artifact cardinality, durable installation/retirement/
  qualification/binding/rollback-retention persistence, exact owner release and four deployment arms,
  operator-staged OCI services,
  browser management with slot/selector-keyed binding, two installable packages, recursive dependency
  enforcement including `app/extensions/**` and out-of-tree broker/client parity over T025's frozen
  HTTPS route-composition seam. The private conformance fixture has a separate T087 lock and is never a
  T089 core build input or T081 core/built-in image; arbitrary third-party extensions are not bundled.
  T018 broker qualification and T025 durable web authority/routes also keep
  T087 open.
  See evidence/extension-spi-pure-contracts.md. The executable slice of the 44 base schemas
  is additionally closed: deterministic generation to schemas/v1/extensions/ports/ with
  artifact-input uniqueness guards, and fail-closed trusted-context semantic validation whose
  focused suite passes 28 with full-context happy paths; see
  evidence/extension-port-schemas-t087a1.md (2026-09-12).
- [x] T089 exact Linux arm64+amd64 dependency, model, upstream build-input image,
  license/provenance-input and digest
  closure. Python/Node/Caddy index+platform descriptors, all model bytes, the corrected reproducible
  PCM-only downstream wheel, five per-service Python locks, Node Playwright-core/paired headless
  shell, browser Debian snapshot/source closure, ADR-013's signed three-executable-per-platform
  Codex minimal runner plus dated Bookworm OCI/Bash binary/member/source closure, and an age binary
  candidate with exact embedded-Go license inputs and loose-artifact native dual-platform X25519/
  rejection canaries now exist. The current v3 Codex child separates T089-owned build-input blockers
  from downstream release blockers, consumes an exact artifact-backed verifier replay receipt,
  and agrees with the regenerated locked aggregate. Both Docker target architectures pass
  offline browser package/runtime verification; the strict non-root sandbox/Korean PNG/PDF/trace
  canary passes on arm64. The final aggregate is `locked`; 223 Python deploy tests, 19 Node
  provenance tests, all verifier CLIs and an independent adversarial audit pass. Its Codex receipt
  binds 17 files and six signatures and rejects 257 recursive shape mutations, but is not a signed
  creator attestation. T082 still owns hermetic native-Linux repetition, per-final-image SBOM,
  source-to-binary provenance and signing; T084 owns the 73 Codex/Rust missing license texts,
  notices/source offers and redistribution/legal/publication decisions; T088 owns Codex native
  runner behavior. Final DeepTwin service-image locks remain T081; T082 qualifies their packaged
  provenance and signing.
- [ ] T018 now means authenticated isolated web-worker IPC and staged topology, not a native launcher.
  T018-A's UDS protocol v2, T018-B's exact-capability one-shot coordinator and T018-B2's bounded
  authenticated HTTP→root-command→registered-coordinator handoff with durable redacted observation
  pass independent
  P1/P2 re-audits; T018-C's static Compose isolation skeleton also passes an independent adversarial
  re-audit after eleven authority/network/resource regression bypasses were added to the oracle.
  B2's final independent focused set passes 127; current shared results are 2,298 application tests
  (one skip) and 298 deploy tests. Exact scope and hashes are in
  evidence/worker-broker-t018a.md, evidence/worker-coordinator-t018b.md and
  evidence/worker-dispatch-t018b2.md and evidence/static-topology-t018c.md. T018-F1 additionally
  implements the root-owned pair initializer and authenticated listener lifecycle with the ten
  static pair mounts and a root-only Linux canary; its focused suites pass 150 (one honest
  Linux-only skip, 21 subtests) and the canary refuses honestly on non-Linux hosts, while the
  actual Linux/root canary run and bounded artifact streaming remain open — see
  evidence/worker-ipc-foundation-t018f1.md (2026-09-12). The bounded digest/chunk/receiver-credit artifact stream state machine (offer/credit/chunk/end/accept, cancellation, owned scratch) is also implemented transport-agnostically with 26 unit tests; it runs over a real authenticated broker FrameCodec (FrameCodecTransport, 4 socketpair tests) and is now wired into the coordinator in both directions: `WorkerCoordinator.exchange` accepts declared `artifact_inputs` and an `artifact_output_policy` (both validated before permit consumption, the policy bound to the exact command id), streams the input batch after the request frame on a duplex route-declared message type, admits worker-returned outputs through an offer-driven `receive_offered_batch` bounded by the policy's media/count and byte ceilings with independent digest recomputation, and fails closed with `outcome_unknown` past the request frame (13 real-socketpair coordinator tests + 8 offered-batch stream tests). An independent adversarial audit (~50 executed probes) then ACCEPTED the slice with no peer-triggerable invariant violation; its three trusted-side findings are fixed with per-finding regression tests (foreign source exceptions now cancel and surface outcome_unknown; a failed offered batch aborts every previously admitted sink; ScratchFileSink abort is idempotent and reverses finalize), full regression 2,990 pass. The byte route's endpoints are also CAS-bound: app/runtime/artifact_cas.py streams exact registered DomainStore blobs (identity-checked against the descriptor, store-verified on read) and imports verified worker output back as registered content, with a store→stream→worker→stream→store end-to-end test over real authenticated codecs; full regression 2,996 pass. The dispatch layer now plumbs the route end to end (accept carries artifact inputs/output policy through the queue to exchange; returned artifacts must import into the CAS before clean transport acceptance, an import failure records outcome_unknown recovery; 2026-09-13, full regression 2,999 pass), though no live HTTP/semantic route supplies artifacts yet, and the Linux/root UDS canary run is still open (the 2026-09-12 Docker attempt was blocked by a host content-store fault) — see evidence/artifact-stream-t018f1.md. T018 remains open for
  actual Linux UID/peer paths, service images/initializers, actual worker implementations, bounded
  artifact streaming and semantic graph execution, runtime container/network/mount/browser
  enforcement including non-root Chromium sandbox/seccomp, and both clean deployment profiles.
  `T018-foundation` is the in-task prerequisite consisting only of actual Linux initializers/
  listeners/peer handshake, bounded artifact stream and staged sandbox/channel enforcement. T087,
  T090, T024, T043, T044, T070 and T081 then own their semantic integrations; `T018-final` consumes
  that evidence later to close the unchanged checkbox. Immutable final distribution and two-clean-
  host proof remain T081/T083, so T018-final is not a circular prerequisite.
- [ ] ADR-010 `local-no-terminal-v1` remains an explicit release gate, not a supported path yet.
  `deploy/compose.yaml` exists as an audited static, unqualified isolation skeleton; its existence
  does not establish a supported deployment path. No current Portainer CE descriptor or clean-host
  evidence proves that the CE single-file/UI workflow can supply the pinned Chromium seccomp profile
  without a host-file edit, CLI command or Business-only relative-path feature. T081 must produce and qualify a
  different no-terminal artifact/template path if CE cannot do so; the profile and release stay
  blocked rather than silently dropping the seccomp control.

## External readiness and honest completion

The user explicitly removed Claude subscription support on 2026-09-07 after the approval
condition was explained: Claude is API-only; Codex retains subscription and optional explicit
API. Claude subscription approval is therefore no longer a current release dependency.
See `decisions.md` ADR-007 and `provider-research.md`. Real connection/model/tool integration
and finite live API-test authorization still require evidence. No hidden API fallback is allowed.

The durable goal's initial text predates this correction. Latest user instructions and
constitution v3.0.1 supersede that historical phrase; do not block completion on a requirement
the user explicitly removed, or restore Claude subscription automatically after resuming.

Current work has not started paid APIs, live model evaluations, account permission changes,
publication, or destructive user data modifications.

## Resume protocol

Read this file, `decisions.md`, `spec.md`, `.specify/memory/constitution.md`, current tasks and
linked evidence before resuming. Inspect working-tree changes and active agents; do not
restart completed work. Write completed/failed/blocked evidence as work occurs. A checkpoint
is not task completion. The product's patience counter never determines whether development
ends. Only verified delivery or a genuine authority/external-state blocker ends autonomous work.
