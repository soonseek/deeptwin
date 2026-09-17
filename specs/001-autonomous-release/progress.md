# DeepTwin autonomous delivery progress

Updated: 2026-09-16 (Asia/Seoul). Status: implementation resumed on the existing worktree after the user's
handoff and fresh baseline verification. ADR-014 revision 7 closed the design gate; T089's
build-input scope remains closed. No whole-product implementation or release qualification is
implied. See `evidence/resumption-2026-09-15.md` and the scoped `resumption-plan.md` work steps.

## Current resumption checkpoints

| Scoped correction | Current evidence/status |
| --- | --- |
| Provider-advertised effort -> frozen turn -> port request representation | Nullable exact values reconciled across six generated schemas; independent review accepted and parent301 focused tests pass. Actual provider/dispatcher and durable qualification remain T042/T087 |
| Finite speech fixture lifecycle | Implemented, independently reviewed; parent 81 controlled browser/lifecycle cases pass. Production STT and timeout-path detached browser termination are not claimed |
| Real LangGraph ledger-backed checkpoint/pending-write recovery | Partial adapter and no-output correction independently reviewed; parent 148 focused tests pass. Full scheduler remains open |
| Mandatory result validation context | Final review corrections accepted; 97 focused tests pass, integrated reviewer independently ran 9 relevant regressions. Durable context/source-lineage and production admission remain open |
| Authenticated response capture/recovery | Accepted after schema parity/authenticated API fixture corrections; independent spec/quality PASS and full3755passed. Semantic acceptance, settlement, scheduler and Linux qualification remain open |
| Real persistent first-owner/session -> command authority | Task7 bounded backend accepted after independent review/fixes; real bootstrap-cookie-to-command and same-writer revocation verified. Final full3859passed. Final owner UI/TLSedge/service-client/recovery and whole T025 remain open |
| Actual owner -> inert executable candidate registration | Task8 accepted: durable real-cookie registration/read/replay/cold-reopen, corruption/fault/concurrency/capacity, shared-core extraction and fixed common composition independently reviewed. Final full4126passed; no installation/execution authority |
| Finite deployment source I/O | Task9 accepted after independent restart-permission correction/review: actual finite producer, metadata-only IPC lease, independent retained-file readers and no-clobber publication. Final full4304passed; owner prepare/cancel journal, images and host qualification remain separate |
| Actual owner -> deployment prepare/read/cancel | Task10 A/B/C accepted within scope. C cleanup finding corrected:192post-fix covering plus parent real-file regression; independent rereview clean. Pre-fix full4588Python/32browser evidence retained separately. Next public receipt verification/source/import; installation/effect and whole-journey gates stay open |
| Separate receipt-verifier dependency candidate | Task11 accepted:200covering tests/314subtests, ancestor-symlink correction independently reviewed. Historical release inputs unchanged; no Linux image qualification |
| Pure public signed-receipt verification | Task12 accepted after four reviewed corrections;321final covering plus parent10targeted/1PATH-runtime cases. Its bounded-session follow-up is resolved by Task20; year-format/style debt remains. Pure verifier alone grants no source/admission/installation authority |
| Pure public-source expansion and consumed marker | Task13 accepted:246covering and parent112new-code tests, independent review clean. Exact old expansion retained; clean RED-history limitation explicit. No actual source I/O |
| Retained public-trust source and shared file checks | Task14 accepted after3defect fixes and fresh-process import proof; independent rereview4addressed/no new breakage,188final covering plus parent6regressions. Post-fix full5004passed/1Linuxskip/369subtests/1inheritedwarning; no ingress/consumption source or initializer qualification claimed |
| Retained incoming receipt files | Task15 accepted after rejecting-parser currentness correction and clean scoped rereview; final249covering plus parent7regressions,4final/144untouchedhashes checked. No signature/admission/import or deployment authority |
| Consumed-result files and no-overwrite publication | Task16 accepted after final-read ordering correction and clean scoped rereview; final280covering/parent4regressions, seven final/143untouched hashes verified. Two deferred minors remain; no DB consumption or installation authority |
| Public receipt-root initialization | Task17 accepted after two scoped fix rounds: final239covering/parent491integration plus four actual regressions; independent review clean, retained bindings/membership/metadata verified. No host initialization or image rollout authorized |
| Receipt v2 command and immutable record structures | Task18 implementation/review gate accepted after timestamp correction: final464covering/parent4time regressions, six exports verified, scoped review clean. Three minor follow-ups remain explicit; no migration/import/approval authority |
| Mixed cancellation-version file compatibility | Task19 accepted:385covering/parent213integration pass with one inherited warning; independent spec/quality review clean, two nonblocking warning/test-precision notes retained. Shared actual source/publication path only; v2 lifecycle/import still separate |
| Same-service verified receipt migration/import | Task20 accepted:2884covering plus fresh full5456passed/1Linuxskip/369subtests/1inheritedwarning, independent spec/quality Approved. Concurrent-import race corrected and frozen-byte parity verified. Two nonblocking test-oracle/warning notes retained. Succeeded receipts remain pending evidence, not installation or release |
| Existing owner web route for receipt import | Task21 accepted:2922affected-family,32browser and fresh full5494passed/1Linuxskip/369subtests/1inheritedwarning, independent spec/quality Approved with0Critical/0Important. Actual owner/import/read/HEAD/replay/restart/source ownership connected; two test-maintenance/warning minors retained. No whole UI/installation or release claim |
| Closed image identity and full lineage values | Task22 accepted after review fix round 1: hollow-state sanitization and shortened-argv vectors added, covering490passed, Ruff/format/diffcheck clean. Pure canonical codecs and full two-platform structural joins grant no measured provenance, trusted source or installation authority |
| Fixed-file extension worker metadata source | Task23 accepted after review fix round 1 (2 Important + 5 Minor closed RED-first): 60 focused tests, 13 retained descriptors with fresh-chain recheck, every mount at/below the prefix refused, closed errors, poison/busy/deadline semantics on real temporary files as simulated Linux facts. No Linux/OCI/image/installation or readiness claim |
| Owner-recorded run approvals (first action_approval producer) | app/services/run_approvals.py: POST+CSRF+origin request re-authenticated inside the final writer; one immutable action_approval per (run, node, scope) authored by the owner's human actor plus approval.decided in one transaction; exact replay, conflicts never overwrite; 17 tests over a real bootstrapped owner; wired to the fixed first-party route contribution run-approvals-v1 (POST /api/v1/runs/{run}/approvals, GET/HEAD read; 7 API tests incl. HTTPS profile and cold reopen). No UI element calls it yet; T065 promotion approvals not yet routed through it |
| Run trace read-back and slicing (T055 reopened scope) | app/services/run_trace.py over real scheduler runs: ordered executions with recorded parents and durable result refs from the checkpoint journal (never cursor bytes), observation gaps, exact graph-binding refusal, boundary slicing into ancestors/dependants/excluded nodes; 6 tests. Format-aware artifact differences over slices remain open |
| Owner-recorded promotion approvals (T065 closed) | app/services/promotion_approvals.py: the persistent owner session records one immutable action_approval per command bound to the exact candidate bundle hash, validation report and expected environment (approve/reject with approval.decided, defer without); record_promotion_decision accepts only these issued values, activation consumes by approval record so a re-wrapped approval never re-applies after rollback; resolve re-validates stored content. Independent review REJECT→all 8 findings closed RED-first; 126 covering tests. No route/GUI yet; environments.py/retention.py still carry off-path authenticated booleans |
| Owner decisions over an exact subject; design approval evidence (T036 environments part) | app/services/owner_decisions.py: shared owner-session producer of action_approval records over a closed subject kind + plain-JSON subject + canonical digest (no reference/blob shapes, bounded), approve/reject with approval.decided, exact replay/conflict, strict resolve incl. event correlation; environments.py record_design_approval now accepts only an issued OwnerDecision whose subject equals design_approval_subject(value) (caller-declared approver gone). Review REJECT (blob-shape gap) → 5 closures RED-first; 86 covering tests. Follow-ups: design_store evidence resolution in the same vault; retention deletion actor (T069) |
| Deletion decisions (T069 residual) + design-store evidence resolution | app/operations/retention.py delete_items takes only an owner-recorded `deletion` decision over deletion_subject(preview, reason); ledgers carry an issued identity and the preview digest covers ledger, scope, bytes and shown impact, so one decision never applies to another ledger; design_store.persist_design_approval resolves the evidence through the owner-decision reader bound to the same store (kind/decision/subject incl. entity kinds/approver/stamp); shared OwnerSession test helper (module-scoped real owner app). Review ACCEPT + 3 SHOULDs folded in; 66 covering tests. No caller-declared `authenticated: True` remains on any approval path. records.mjs deletionRequestPayload still mirrors the retired actor payload (unwired; to follow the route) |
| Human-gate approval requests bound to real runs (scheduler review F6) | app/runtime/gates.py + RuntimeLedger.request_gate_approval: when the scheduler stops at a gate it records one replayable ledger command per (run, node, scope) — identity derived from those values — and one public approval.requested event; PersistentRunApprovals.record refuses any approval whose gate was never requested (unknown run, other node/scope), reading the request through the shared gates.gate_request_recorded helper; scheduler resume/replay never re-asks. Review ACCEPT; decoy-approval coverage restored. Follow-ups: a read listing pending gate requests per run (the closed event catalog carries only approval_kind), gate requests never expire (runs have no retired phase) |
| Restart-invariant scheduler projection (scheduler review F9) | GraphScheduler._project rebuilds consumed gate approvals from the owner's durable records and sealed router activations from the durable activation markers (identity re-derived), instead of process memory; a fresh scheduler instance or a reopened store projects an outcome equal to the first with zero re-execution; approvals-service errors are normalised to SchedulerError; router revisits refused loudly. Review ACCEPT + 2 SHOULD/3 NIT folded in; 59 covering tests |
| Task 24 plan draft (T087 next step) | Drafted, independently reviewed and REJECTED before any code: postcondition must be a socket handshake probe (prerequisite task), evidence never a request body, success needs a journal-v3 contract (`accepted3`), absent-only head, record kind `extension_installation`. resumption-plan.md now carries the corrected redraft order; next iterations produce the journal-v3 contract and the probe prerequisite task |
| Task 25 slice 1a: fixed extension worker channel values + argv parser | app/workers/extension_channel.py: (PairRootSpec, ChannelSpec) derived only from deployment.contracts.slot/CONTROL (endpoint pair root, responder+pair-gid ownership, extension-channel-profile-v1 constants), fixed five-element argv parser bounded before int(); 45 tests incl. listener rule for all 16 slots, WorkerRouteBinding construction, digest stability, fresh-interpreter import boundary. Review ACCEPT, closures folded in. Inert values: no I/O, handshake, listener, probe message, image or admission claim (slices 1b–3 open; 1b gated on a probe contract) |
| Task 25 slice 1b: closed probe message codecs | contracts/extension-worker-probe.md accepted (spec review ACCEPT WITH CHANGES folded in); app/workers/extension_probe_messages.py: request/reply encode/parse over canonical strict JSON with the exact §2 wire limits and canonical-bytes recheck, hex64/base64url-nonce/BrokerId/UInt32/platform/operation-subset grammar, keyword-only scalar encoders, byte-identical round trip, single closed error, values hide nonces/digests from repr; 69 tests (143 with channel + import boundary). Review ACCEPT, 3 SHOULD/2 NIT folded in. Inert values; slices 2a–3 (handshake, fences, listener, worker service) open |
| Task 25 slice 2a: extension handshake continuation | broker.py: shared responder continuation `_server_continue` (public handshake semantics byte-identical), extension server/client wrappers that learn the requester boot ID from the actual proven hello (peer verified before any read, 4096 B packet cap, full profile check, post-read rejections `outcome_unknown`), seamless wrappers leave socket cleanup to slice 2c; 17 tests over real socketpairs (relabelled hello, genuine stale finish vs fresh challenge, caps both sides, fail-closed without peer credentials on every host) + every existing handshake consumer suite: 234 passed. Review ACCEPT, 4 SHOULD/4 NIT folded in. Positive Linux authentication remains a gate |
| Task 25 slice 2b: populated-generation fence | ipc_root.PopulatedGenerationFence / _retain_populated_generation: borrows a held GenerationLease, owns one no-follow boot-secret descriptor, rechecks named vs held root/endpoint/lock/secret identities and constant-time compares the reread secret on every fence; permits populated endpoint files (absence-only lease untouched); BaseException unwind; _read_exact_secret no longer leaves partial secret bytes in traceback frames. Review REJECT (traceback leak, half-built AttributeError, fd leak, tests passing via stat compare) → all closed RED-first with load-bearing reread cases and traceback-locals assertions; 110 passed / 1 root-only skip |
| Task 25 slice 2c: extension listener accept/connect and fences | listener.py: `_extension_mount_fence` over deployment.mounts (side-specific ro/rw, no nested or same-device alias mounts; compose shape passes), `ExtensionConnection` (owning socket/codec/generation/populated fence/record/peer; `recheck()` closes on any fence failure), `_accept_extension_authenticated` (record + readiness/socket identity re-verified, mount fence before accept and after handshake, requester boot id learned from the proven hello) and `_connect_extension_authenticated` (readiness, fences, exact socket inode, peer retained); 13 tests over a real bound listener through the macOS seams, 165 with neighbours. Review ACCEPT, 4 SHOULD/4 NIT folded in. Probe rules and the worker service remain slice 3 |
| Task 25 slice 3: worker probe service and fixed entrypoint | `app/workers/extension_probe.py`: `open_worker_probe_service` (metadata source before the listener, fresh `token_hex(32)` boot id), `WorkerProbeService.serve_one` (one connection in its own 2000 ms window from the transport accept, ≤2 probes with distinct ids/nonces and an identical digest pair, an actual `read_current` per reply, fences rechecked before the first read and after each reply, closes after the second reply; a poisoned source or a listener that no longer verifies closes the service), private `_Router` with an empty registry; `app/workers/extension_worker.py::main` (fixed argv only, exit 0/1/2, SIGTERM interrupts a blocking accept). 26 tests incl. an enumerated descriptor budget (19 retained, 37 worker-owned peak, worst case 56 ≤ 64) and a fresh-interpreter import-boundary check; 275 with neighbours. Review ACCEPT WITH CHANGES: MUST + 4 SHOULD + 4 NIT all folded in RED-first. Task 25 complete; Task 24(a) journal-v3 contract next |
| Task 24 step (a): deployment receipt journal v3 contract | `contracts/deployment-receipt-journal-v3.md`: thirteen-statement DDL_V3 with frozen C3 (C1/C2 preserved), v2→v3 migration with stated deferred-FK reliance, `extension-stage-postcondition-v1` evidence blob built only by the observer with `expected` pinned to retained candidate lineage, `extension-installation-anchor-v1` (absent-only head, coexist ruling for `extension-installation-v1`), consumption anchor v2 (`succeeded` + `effect_ref`), admission matrix with the global first-only guard stated as it exists (≤1 accepted3 per journal), `deployment.requests.consume` route + frozen 200 body, prepare-api-v3, `deployment.request_accepted` next to `extension.staged`, storage/records/lifecycle API additions. Independent specification review ACCEPT WITH CHANGES (2 MUST, 6 SHOULD, 3 NIT) folded in; C3 re-verified from the fenced text. Specification only; next (c) pure codecs |
| Task 24 step (c1): installation anchor and success consumption codecs | `app/domain/extension_installation.py` (`extension-installation-anchor-v1` content schema + body validator: ordered request/receipt parents, matching ids, actor, padded time, operational evidence blob ≤8192, integer revision 1, cap), consumption anchor v2 in `deployment_receipt.py` (`oneOf` variants, `effect_ref` as third parent, v1 unchanged), kind dispatch, envelope export branches pairing content variant with parent arity, `domain-envelopes.schema.json` regenerated. 30 tests; 145 with receipt/export/journal/import neighbours. Review ACCEPT WITH CHANGES (MUST: trailing-LF anchoring → canonical `text()`; SHOULD: export arity pairing, test isolation) folded in RED-first. Next (c2): DDL_V3 constants, `parse_consume`, prepare-api-v3 exports |
| LangGraph scheduling adapter (T040 slices 1–3) | app/runtime/scheduler.py: closed code-owned handler registry, deterministic ledger-reconciled node visits via command replay, sealed router activations and bounded-loop controllers routed by Command (closed facts, termination expression, hard cap fails loudly, every iteration a new visit), opaque saver cursors, no streaming, sanitized failures; human gates stop before the node and resume only on owner-recorded approvals (rejection fails, absence reports awaiting_human); 16 real StateGraph+SQLite tests incl. restart after failure, restart inside a loop and gate wait/approve/reject. independent review (2026-09-17) found 4 Important (double fan-in visit, gate in loop, forged newer approval version, GUI base path) — all closed RED-first; retry/budget/semantic admission remain open |

These are scoped engineering checkpoints, not whole user-story completion or a release claim.

Prior four-task batch verification: **3535 Python tests passed, 2 skipped, 369 subtests passed**
in 201.36 seconds, freshly repeated before continuation in201.43s, with one unchanged upstream
Starlette/AnyIO warning; the separate eight-file
controlled browser/lifecycle regression passed **81 cases**. Changed Python static checks and
three JavaScript syntax checks pass. All task-scoped and final integrated reviews accepted their
recorded scopes after corrections. Continued Task5 separately passed301 tests in27.33s and
independent spec/quality review. Initial continuation full run found one outdated API fixture
(3709passed/1failed); independent Task6 review also found terminal-newline schema disagreement.
Both were fixed and independently rereviewed: spec PASS/quality PASS. Final frozen-source full run:
**3755 passed,2 skipped,369 subtests passed** in241.65s, exit0, one unchanged Starlette/AnyIO warning.
This is the latest integrated verification before Task7 changes, not whole-story qualification.
No automatic commit, push or live-provider qualification.

Task7 continued that baseline with actual persistent owner admission and one reviewed correction.
Final frozen-source Python run: **3859 passed,2 skipped,369 subtests passed**,259.89s,exit0,
one unchanged Starlette/AnyIO warning. Controlled historical browser regression:81passed,exit0,
262.920s; the subsequent fix touched only private-auth storage, new tests and documentation.
Independent review/reviewfix gates accepted the bounded source. These results are not final owner
UI/TLSedge, full export collector, Linux/provider or whole-story evidence. Retained-history auth
verification cost is a deferred Minor to address before production long-retention qualification.

Task8 corrected the inherited reusable-core dependency gate and shared request/wire/event imports,
then resolved two Important review findings: feature-specific startup wiring and an incomplete
transitive AST gate. The supported server now uses a fixed generic contribution seam; all five
core roots and reachable local helpers are checked. Independent scoped rereview accepted both.
Final frozen full Python regression: **4126passed,1skipped,369subtests passed**,317.38s,exit0,
one unchanged upstream warning. The skip is Linux SO_PEERCRED. Three hash-pinned missing optional
development packages enabled106offline Claude API tests; no live provider or production credentials
were used. Historical2skip totals included a missing-SDK module and must not be called bothLinuxonly.
Forty-one source hashes stayed unchanged during final verification; git diff --check passed.
Whole T025/T087, final release/static-lint hygiene and retained-history/capacity qualification remain open.

Task9 source I/O is now independently reviewed after correcting a plan-mandated initializer group
omission. Credential-aware actual-file tests cover1/16slots and missing-group denial. Final parent
frozen regression: **4304passed,1LinuxSO_PEERCREDskip,369subtests,1existingwarning**,291.53s,exit0.
Twenty-two frozen hashes verified unchanged. Earlier4300pass pre-fix result remains historical.
No source metadata, generated Compose expansion or file publication is installation authority.
Task10 subsequently connected actual owner/domain/candidate sources to durable prepare/read/cancel.

Task10 phase A now has exact seven-table primitives, pure stage/request/domain-anchor contracts and
six structural exports, with actual temporary domain/owner/candidate foundation tests. Corrected-byte
covering1759passed/1existingLinuxskip/21subtests/1existingwarning; parent pre-review-fix full4372passed,
1Linuxskip,369subtests,1warning in296.54s. Independent review found one Important: cancellation
reconstruction did not invoke its shared codec. The correction now requires an explicit profile and
validates through that codec. Independent scoped rereview accepted the fix; final parent broader
boundary regression1245passed/1existingwarning14.10s, no skips, and18finalA+22Task9hashes unchanged.
Phase A is accepted, not a usable endpoint. The4372full result remains explicitly pre-fix evidence.
Phases B/C are now also accepted for actual authority/lifecycle/recovery and the supported HTTP
path, including the final narrow resource-ownership correction. Whole bounded Task10 is complete;
signed receipt, actual installation/runtime and original whole-story gates remain open.

The separately versioned control dependency candidate is now accepted: final200tests plus314
subtests, real ancestor-symlink regressions and clean independent scoped rereview. Four historical
T089 inputs remain unchanged; the candidate is explicitly not release-qualified. Next is actual
public Ed25519 receipt parsing/verification and verified local package installation. This does not
yet establish receipt lifecycle, operator execution, final image inclusion or whole-product completion.

Task12 initial public Ed25519 implementation and verified additive local PyNaCl installation now
have a frozen whole-Python regression:4823passed,1LinuxSO_PEERCREDskip,369subtests,1inheritedwarning,
458.32s. Independent review found four concrete fixture/contract/portability issues; a scoped fix
round is active, so this result is explicitly pre-fix and Task12 is not accepted yet. Native
verification uses actual installed PyNaCl and independent Node public verification, not a mocked
success. Source admission, actual deployment effects and whole-story integration remain open.

Task12 is now accepted after fixing all four Important findings and clean scoped independent
rereview. Final affected five-file selection321passed2.59s; parent targeted10passed1.06s and ordinary
PATH-Node public verification1passed0.66s. All11final and historical build/source hashes verified.
Ruff lint passes; at Task12 acceptance three minor follow-ups were recorded: platform-year formatting,
owned-child complete-frame deadlines, and formatter compliance. Task20 later resolves the bounded
deadline concern while retaining its separately identified clean-exit test-oracle note. The4823whole-suite result remains pre-fix;
it is not relabeled post-fix. Next Task13 adds pure receipt-source expansion/consumed codec only.

Task13 pure receipt-source producer/consumed codec is accepted:246focused covering tests and parent
112new-code regressions pass, independent spec/quality review clean,7new/135predecessorhashes verified.
Exact Q487bytes and generated input/output bindings preserve the previous expansion; no source I/O
or initializer actually runs. Separate clean pre-implementation RED evidence for renderer/codec was
not established and remains disclosed; acceptance does not manufacture that history. Next Task14
adds actual retained public-trust reads and shared bounded file mechanics; whole-story gates stay open.

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

Current conservative estimate: **40–45% including design**. Eight overstated completion markers
were reopened (T039/T041/T055/T056/T057/T061/T064/T065) without discarding their tested partial code.
This is a scope-accounting correction, not a claim that existing functionality regressed. The
table below preserves the **2026-09-13 historical estimate (46.2%)**; it is not current runnable
product coverage. A new full weighted numerator is pending integrated execution evidence.

Two historical table notes are superseded: LangGraph/checkpoint-sqlite are installed and import
successfully in the development environment, so a main-checkout dependency edit does not block
T040 implementation. Design/growth storage and knowledge modules exist; their presence does not
close real worker/evaluator/human integration. Actual design/execution UI remains disconnected.

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
| Full-journey integration, security and effect evidence | 10 | 0.20 | 2.0 | The bounded shared permission/budget/runtime transaction and API slice plus exact build-input integrity are verified; T018-B2's handoff/observation defects stay closed. New audited operations value layers (2026-09-13): manual-only retention with complete tombstones (T069), export manifests with decoded-string canary scanning and acyclic hashes (T071), the closed §4.2 event-coverage audit with 101 registered types and secret-free projections (T068), bounded document rendering with reopen inspection (T044 part), and purpose-scoped artifacts (T045 part) — REJECT-audited (2 high incl. an escape-blind canary bypass) and every finding closed with 14 regressions (evidence/ops-batch-audit.md). Whole-journey, both-target-architecture, worker-runtime, backup crypto (dependency-blocked) and effect qualification remain |
| Web deployment, recovery/update, release documentation | 5 | 0.34 | 1.7 | T089 locks exact multi-architecture build inputs and T018-C adds an audited static state/network/IPC isolation skeleton; its control listener, profile split, images, initializers, Linux/Portainer behavior, recovery/update and clean self-hosted distribution remain unqualified |
| Total | 100 | — | 46.2 | User-facing estimate: roughly 45% (46.2 unrounded); the design gate is closed while T018/T025/T087 and complete journey gates stay open. 2026-09-13 recalibrations: growth 0.00→0.30, graph/design 0.07→0.20, runtime 0.24→0.30, journey/security 0.15→0.20 (audited operations value layers), while storage/UI/E2E/live majorities stay open across the board |

Initial estimate: about 15%; immediately before ADR-009 the working estimate was about 34%.
The 2026-09-08 correction from a native macOS app to an open-source web framework invalidated
native packaging credit and reopened design consistency. The first T086 review later closed that
gate, but ADR-014's extension audit reopened it after finding six reusable-framework gaps. The
revision-7 formatting-only remediation passed a new independent review after six ADR-014
rejections; T089 plus the T018-A/B/B2/C
checkpoints retain their scoped build-input, internal transport and static-isolation evidence. The
pre-2026-09-13 rounded estimate was roughly 35%; transport-neutral domain/provider/web UI work did not
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
  See evidence/extension-spi-pure-contracts.md. The 44 base schemas have deterministic generation
  to schemas/v1/extensions/ports/ and artifact-input uniqueness guards. The historical 28-test
  scope is recorded in evidence/extension-port-schemas-t087a1.md (2026-09-12); it did not establish
  mandatory complete result context. That defect and subsequent review findings are corrected
  in evidence/resumption-2026-09-15.md, with 97 focused tests and independent review. Neither
  static schemas nor trusted-context validation closes durable semantic admission.
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
