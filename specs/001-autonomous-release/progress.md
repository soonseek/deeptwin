# DeepTwin autonomous delivery progress

Updated: 2026-09-08. Status: active; ADR-014 revision 7 independently closed the V1/T086 design
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
| First use, input, providers, model control and persistence | 15 | 0.55 | 8.25 | Claude API-only and both Codex adapter modes, catalog/default routing and bounded conversation/provider components exist; the simplified T023 browser intake shell passes, while T025/T090 web credential-vault/gateway integration, budget UI and full browser speech qualification remain |
| Actual graph generation, criticism, selection and approval | 15 | 0.07 | 1.05 | Versioned lens registry is implemented; prototypes and offline critic contracts exist, but no full live graph path |
| Actual multi-agent runtime, framework tools and artifacts | 20 | 0.20 | 4.0 | Durable run/attempt, budget and root-command substrate plus a historical pure extension-contract checkpoint exist; ADR-014 shows that generic messages, memory-only lifecycle and source-tree helpers are not a completed SPI/SDK. T018-A/B/B2 contribute independently reviewed transport and bounded HTTP→coordinator handoff scope, while semantic ports, durable extension state/staging, graph scheduler, artifact streaming and real workers/tools remain |
| DeepTwin inquiry, repeated evaluations and promotion | 15 | 0.00 | 0.0 | Existing design/prototype, no demonstrated complete engine |
| Full-journey integration, security and effect evidence | 10 | 0.15 | 1.5 | The bounded shared permission/budget/runtime transaction and API slice plus exact build-input integrity are verified; T018-B2's six reproduced handoff/observation defects are closed with 127 focused passes and a 2,298-pass/1-skip app regression, but this is not whole-journey, both-target-architecture, worker-runtime or effect qualification |
| Web deployment, recovery/update, release documentation | 5 | 0.34 | 1.7 | T089 locks exact multi-architecture build inputs and T018-C adds an audited static state/network/IPC isolation skeleton; its control listener, profile split, images, initializers, Linux/Portainer behavior, recovery/update and clean self-hosted distribution remain unqualified |
| Total | 100 | — | 36.5 | User-facing estimate: roughly 35%; the design gate is closed while T018/T025/T087 and complete journey gates stay open |

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
  See evidence/extension-spi-pure-contracts.md.
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
  evidence/worker-dispatch-t018b2.md and evidence/static-topology-t018c.md. T018 remains open for
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
