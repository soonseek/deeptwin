# DeepTwin autonomous delivery progress

Updated: 2026-09-22 (Asia/Seoul). Status: Claude Code additions inspected; continuous implementation
resumed from the existing worktree at a2f85d5 with the six inherited dirty files preserved. The
subsequent task-scoped changes below are also uncommitted. ADR-014 revision 7 closed the design gate; T089's
build-input scope remains closed. No whole-product implementation or release qualification is
implied. See `evidence/resumption-2026-09-15.md` and the scoped `resumption-plan.md` work steps.

## Current resumption checkpoints

### Latest snapshot — the run consent record landed (2026-09-22)

- The consent line's first link landed: `run-consents-v1` seals the owner's `run_consent` over
  the exact records a run names, with the owner's decided event (`evidence/run-consent-record-t048.md`),
  and the run route now starts a run only under the consent that names exactly its inputs,
  one consent per run (`evidence/run-consent-verification-t048.md`). The provider suites' order/
  timing failures were chased at cause (test fixtures only): the full regression is wholly
  green again — **9,350 passed / 0 failed / 2 skipped** (`evidence/provider-suite-flakes-2026-09-22.md`).
  Next: the design line's `environment` record; run creation from the intake page. No
  deployment, model activation or browser journey is claimed.

### Earlier snapshot — Task51 owned shared gateway landed (2026-09-22)

- Task51 (the owned shared gateway prerequisite, G1–G10) landed under this loop's review cycle:
  the fixed profile, the generic authenticated owner, the shared vault/send ingress and the owned
  send dialogue with linearized control, three stage reviews plus a re-review of the stage C
  closures folded in RED-first, one full regression (**9,341 passed / 1 failed / 2 skipped**; the
  failure a pre-existing 1-in-16 flake of a design-store pin, fixed at cause), committed and
  pushed. See `evidence/owned-shared-gateway-task51.md`. Semantic artifact admission and the
  current binding that connect it to the runtime remain next; no deployment, model activation or
  browser journey is claimed.

### Earlier snapshot — Task49 accepted; Task51 shared gateway implementation next

- Task47 final regression completed on the independently reviewed source: **1,341 passed,
  1 inherited warning in 475.89 seconds**, exit 0. All 826 source hashes were unchanged
  before/after the run. Independent R5 spec/quality review passed with no remaining
  Critical/Important findings. See `evidence/resumption-2026-09-21.md`.
- This closes the bounded Claude semantic worker/gateway/dispatcher task, not native
  qualification, production activation, managed Codex, or the connected browser journey.
  The earlier R0–R5 chronology below is retained history, not the current task state.
- Task48's worker-only connection design passed independent R1 review with no
  remaining findings and is adopted in `contracts/provider-owned-semantic-connection.md`.
  Task49's owned connection implementation passed independent R2 spec/quality
  review with all findings closed. Root ran the required20-file regression once:
  **615 passed, 1 inherited warning in935.97 seconds**, exit0. All828 source hashes
  were unchanged;820 outside the eight scoped paths remain unchanged.
  This accepts real worker ownership, cancellation-compatible reads, deadline/
  currentness checks and cleanup within conditional local tests. The original
  intermediate catalog-refresh failure remains historically unexplained; its node
  passed in final20, but that does not diagnose the old cause. Root's explicit
  evidence disposition retains it for connected integration and final review.
  Task50 gateway ownership/routing design passed independent R1 review and is
  adopted; Task51's finite12-path TDD plan is ready for implementation. Actual
  semantic artifact admission and current binding still must connect these
  components to the runtime. No deployment,
  model activation or complete browser experience is claimed from these steps.

### User-visible delivery checkpoints (current, not checklist counts)

| User action | Current boundary | Remaining connected proof |
| --- | --- | --- |
| Open the web app and describe/upload work | Owner/intake/original-file persistence exists | Provider setup, speech and actual understanding flow in the same browser journey |
| Compare generated multi-agent graphs | Graph/design/critic modules exist in partial/offline form | Real purpose-preserving generation and independent critique, graph comparison and exact approval |
| Run agents with selected models and inspect each artifact | Scheduler, worker transport, custody and conditional Claude semantic path have tested components | Genuine current provider binding, managed Codex, tool/multimodal workers and graph runtime UI |
| Supply one's own whole/partial alternative artifact | Partial domain/service work exists | Connected original/alternative comparison and philosophy-grounded inquiry, not instruction-style feedback |
| Re-evaluate prior queues and approve a better environment version | Partial evaluation/promotion modules exist | Actual paired replay, quality floor plus three-plateau termination, human exact-version approval |
| Export a redacted feedback bundle when desired | Remains part of delivery scope | Whole-flow log completeness and user-controlled export; no automatic transmission |

- Whole-product estimate remains **about50% ±5 including design**; the connected browser journey
  is not complete. Graph/lens/paired-queue/human-promotion integration remains mandatory.
- Task46 installation verification/source/history and verified-descendant execution is accepted
  within its reviewed offline scope. Final807 hash db384ceb994654c40ae0388d3358e18f7edff90ee01197ce99f514fa9adf9318;
  root verified34new+32modified=66owned and741 outside paths unchanged. No commits/push.
- Exact72 remained93fail/2834pass/3error. Corrections had independent compatible/clean review.
  Final22 completed548pass/1fail; the last test-only C6/V6 expectation correction then passed122
  whole API→FD tests, all806 other paths unchanged. Root reconciled all96 original failed/error
  nodes to passing latest cover. There is no newly all-green22/72 run; evidence is explicitly combined.
- The original final-wall2-of6 cause remains unknown despite the current combined pass. This is
  retained for integrated/native-fit/final review, not claimed fixed or production-qualified.
  One inherited Starlette deprecation remains. ColdHTTP GET proof is status/fields; POST/cancel
  have exact canonical-byte equality. No full GET-byte assertion is invented.
- Task47's conditional Claude API semantic worker/gateway/dispatcher R0 was frozen
  for its initial independent review:826 paths,19new+7modified and800 outside paths unchanged, manifest
  e0c6f5a0cf3fd8d583a6498b76a47bd4ce39f228309657471ace91c551c6a125. Initial35 new/166 legacy
  focused tests passed; later completion evidence includes codec12, records6, read/cancel2,
  authenticated router2 and actual dispatcher1. These are combined focused evidence, not a final35
  or whole-task acceptance. Independent review found15 Important defects in canonical admission,
  independent result validation, replay/status/cancel/catalog composition, literal wire conformance,
  absolute deadlines, custody/lease cleanup, HTTP/SSE handling and required behavioral proofs.
  The sole writer has submitted formal R1 fixes under the unchanged26path scope; earlier
  completeness claims are superseded by this review, not accepted. Exact R0 copies are retained.
  Two literal interface conflicts were independently confirmed and corrected in the accepted master:
  new gateway prepare/lease must explicitly carry semantic request_id for descriptor identity.
  Reservation currency must use the existing uppercase API BudgetPolicy grammar and exact equality.
  Each amendment/preflight is retained separately; original snapshot hashes stay unchanged.
  These resolve design contradictions only, not R1 implementation or full operation acceptance.
  Current R1 focused evidence includes authenticated two-page catalog refresh through durable
  catalog/result sealing and actual model dispatch, accepted-state status/cancel, malformed
  post-write unknown outcomes and pre-write currency refusal, six composed restart boundaries,
  credential rotation/retirement, full-scan cancellation and authenticated session/fence refusal.
  R1 review baseline was frozen: manifest84d26ab93aec1347f5e9df29a254065f0ac83c7b8539d75a2babdfb25e15e984,
  23owned changes versusR0,800outside unchanged. Root checked report and held hashes; the same
  independent reviewer completed re-review:3addressed (I3/I10/I13),12Important remain.
  Remaining gaps include nested/admission checks, historical replay/query authority, complete
  failure classification, exact wire/deadline/stream ownership, first-write ordering and cache
  contradiction handling. R2 implementation was held for the same reviewer's scoped re-review,
  against all26 preserved R1 beforecopies and a per-residual consumer/test checklist.
  R2 manifest3e683af2089c7c7a91249167e3318cf3c8087411e0040f2b7ec7e9ab0ba35b2c covers826paths,
  19owned changed versusR1 and800outside unchanged. All26 held hashes and exact R2 copies verified;
  reportc14826677771bab649e79a608f46721ec234ad47842c9e44afa372a81d408f71 preserves R1 history.
  A third demonstrated wire omission was independently preflighted and explicitly corrected:
  new send-result/private response carry required nullable finite failure_class without raw
  diagnostics or changed cancellation/deadline/effect rules. Original snapshots stay unchanged.
  R2 focused cover includes controller6, gateway29, connected vertical27 and portable failure-class2
  passes, plus per-finding runs. These are selected/combined evidence, not a new whole-suite pass.
  Independent R2 review completed:3addressed (I2/I11/I14),9Important remain; priorI3/I10/I13
  stay credited. Remaining selected-profile joins, error closure, concurrent ownership,
  expired query replay, catalog admission, wire validation, actual I/O deadlines and
  blocked-stream controls enter R3 with the original sole writer and exact R2 beforecopies.
  The writer's R2 none-unmatched claim is superseded. R3 fixes are now held for scoped
  independent re-review:826paths,13changed/800outside unchanged, manifest
  67cbb9b3468bfd00476dcaef168ab7c4a9bb88b6bde1590e030949faae3cce5a.
  Root verified26held hashes, exact report prefix, all22contract/reference hashes and
  latest separate model12/catalog10/router7/preservation9/authority-order4 passing logs.
  The same reviewer completed R3:3addressed (I6/I8/I12),6Important remain
  (I1/I4/I5/I7/I9/I15),0Critical. Success/cancel races, pre-owner failure sealing,
  remaining stage-local causes and shortest wire/lease deadlines need correction.
  A fresh stronger sole implementer completed R4 fixes and holds all26 paths for the
  same reviewer's scoped re-review. Final826 manifest89e304f50d099c9f7f36c2dac05b0afc35e51be81a32bec28a916a3a0a4d119e;
  9owned changed/800outside unchanged. Root verified exact R3 report prefix/26held
  hashes and all22contract/reference hashes. Family180pass/6fail was followed by
  diagnosed code/fixture corrections; all6failed nodes have latest passing focused
  cover, final16pass10.38s. This is combined evidence, not a new all-green family run.
  R4 independent review completed:5addressed,1Important remains (I5 new fresh grant-
  subset regression),0Critical. Original R3 counterexamples are fixed. A fresh stronger
  writer owns final R5: restore canonical exact-ref subset admission for model/catalog,
  preserve non-subset refusal, same-ID identity and R4 owner ordering. No acceptance
  or final35 yet; source snapshots and all mixed historical evidence remain retained.
  R5 is now held for the same reviewer's final scoped check:2owned files changed,
  826-path manifestd9009207d9f10d510a372ed392a70cbfd9bc5863e07fc748715cbc8780eff419.
  Proper-subset/non-subset4pass8.91s and ownership/replay18pass23.16s are verified
  focused results, not a new whole-suite run. All800outside and22authorities unchanged.
  R5 independent review now PASS: final I5 addressed,0remaining/new Critical/Important,
  all prior14credits preserved. Root read full75-line report and rechecked source.
  Final35 subsequently completed once on the held d9009207… source:1,341passed,
  1warning475.89s. Conditional offline acceptance is now recorded separately.
  No native/live/production/browser-readiness inference follows.
  Whole browser/graph/lens/paired-evaluation journey remains incomplete.
  Earlier focused evidence was combined; the final35 above is a fresh all-green selection.
  R1 all-closed claim remains superseded. No production activation or paid/live call.
  See evidence/resumption-2026-09-20.md and scratch task-46-acceptance.md for exact scope/limitations.

### Retained earlier credit-restored chronology (superseded checkpoint states)

- Whole-product estimate: **about50% ±5 including design**. This is not a test-count or
  completed-work-step ratio; the allocation below remains unchanged.
- Accepted baseline: Task45 provider conformance after clean R4 production and R5 test-repair
  independent reviews; all773 final source hashes independently verified. Scoped checks cover actual
  fixed-worker HTTP/restart/replay, a two-service single-dispatch race, admission/finalization
  rollback,64-run capacity recovery, retained-history forgery and primary-error preservation.
- Task45 evidence and limits: R4 scoped independent review is clean after the stopping-boundary
  corrections; original findings are addressed. The exact72-module regression completed on
  the verified773-path R4 freeze (session90316):13failed/2915passed/1warning in3137.65s(52:17).
  R5 changed only four test/fixture paths, preserving all production bytes. Final amended cover:
  166passed/1explicit unchanged-capacity deselection plus5HTTP/service compatibility passes;
  all13 failed nodes now pass. Independent R5 review approved all3 regression causes,0open.
  Controller accepts this combined scoped evidence, not a new all-green exact72 result. The precise
  historical worker exception remains unproved; a controlled timing path and strengthened complete-input
  precondition have separate RED/GREEN evidence. The earlier interrupted72attempt's
  exit1/partial output remains separately retained, not a completed passing cover.
  Intermediate runs are separate evidence, not one all-green
  final run. They use controlled synthetic fixtures, not paid models or native qualification.
- Usable journey boundary is unchanged: start/work pages persist text and original uploads;
  production speech input, provider/model setup and input-to-design generation are not yet
  connected there. Graph-centered execution, artifact comparison/lens inquiry and real prior-queue
  improvement-to-human-promotion still need end-to-end integration.
- Task46 installation/source/carrier/adapter design passed independent preflight after four bounded
  corrections and is promoted for offline implementation; it is not implementation acceptance.
  The exact source baseline and28beforecopies are verified;34new/28modified paths are scoped.
  Current implementation has complete synthetic evidence assessment and focused actual storage,
  HTTP and verified-descendant execution proof. Connected R0 product review is now dispatched:
  all42 non-test product files held,62 scoped copies independently hash-verified,807paths/34new
  and745 outside-scope files unchanged. Four test-only paths are still completing exact migration,
  command-replay and source-race proof; this is not a final test freeze or acceptance. The retained
  dpkg-status amendment is now explicit in the canonical installation master. The next Claude
  model-call vertical design passed bounded independent R1 review after three corrections;
  `contracts/provider-semantic-execution.md` adopts the exact read/cancel amendment and frozen
  snapshots. Implementation still waits for accepted46 scope reconciliation; no provider is activated.
  Task46's complete synthetic evidence assessment now has a237-test selected pass. Early independent
  B review found a status-file symlink-resolution escape and a native/canonical codec limit mismatch.
  The original two findings were corrected; R1 review identified two additional shared-path cases
  (resolution exhaustion and protected ancestor aliases). These now have targeted RED/GREEN evidence:
  24passed/205deselected in25.69s. The frozen R2 evidence module hash is
  ccf976735c970932595be7ab8cf48bf6aa93c202297625e0b79e6165016acfc6; bounded independent R2 review
  is clean with all B findings addressed. A/C/D connected review is still required.
  Actual same-store service and source-less historical replay have2focused passes, binary authenticated
  HTTP POST/read/HEAD/replay have2, receiver boundaries18, and the composed v6 migration suite5.
  These are separate intermediate results, not complete final-byte or whole-task acceptance.
  Actual cancellation-before/during-publication and source-less app restart have focused passes;
  the first explicit verified-descendant fixed-worker execution and legacy-head refusal also pass.
  Early A review found a missing post-metadata root fsync. A-R1 closes that defect at held helper
  hash f4e74f1ae06fdcc82f06f94fcbbbd0cbf4c060a87b72102be37dd472b2d659a6, with7initializer passes.
  The late clock-order defect now refuses admission before durable intent when current time precedes
  actual installation verification; targeted RED/GREEN proves no worker and unchanged authority.
  Exact old-tool/provider/completed-B V5 coexistence, during-read source changes and same-ID input
  proof now pass focused checks. Connected R0 review found three additional P2 defects (SQL timestamp
  bound, malformed generated schema and pre-count history loading); R1 closes all three with no new
  actionable finding. All807 source/test paths are frozen at manifest
  91dfa646c13e8fb80e5728f3e4606738d0729e62363ae0f67a344f8d39ae5919. Final11 completed exit0:
  435passed/1 inherited warning in1042.20s; all807 postrun hashes unchanged. Root completed the
  unchanged ordered exact72 sequentially (session25969, log task-46-final72-r1.log):
  93failed/2834passed/3errors/1 inherited warning in3053.55s, exit1. Final807 hashes remain exactR1.
  Task46 is not accepted. Diagnosis reconciled all96 outcomes across16 modules; the same writer
  is repairing one product boundary and narrowly updating eight test files (four new ownership
  additions, total66 scoped paths). Every repair has an immutable exact R1 beforecopy. Legacy/
  empty history read compatibility now has genuine RED2failed/2passed then GREEN4passed;
  verified-history and stage-view issuance still require the exact active writer. Remaining
  stale schema/export/current-layout expectations and held-V2 fixture isolation are in progress.
  The original final-wall worker2-of6 failure remains unexplained; its one diagnostic passed,
  which is not proof of a fix. Finite cover completed548passed/1failed/1warning1612.22s:
  95/96 original outcomes now pass, including final-wall and both actual FD peaks last in the
  same process. Sole remaining coldV1HTTP test still expects currentC5/V5 after actualC6/V6
  migration; historical before/after snapshot and login pass, later HTTP equality checks await
  a narrow test-only expectation correction. All807 bytes stayed frozen through the run.
  Independent nine-path review is spec-compatible/quality-clean; one-file follow-up remains.
  No automatic rerun, skipped test or completed-story claim. The intermediate11 run
  ended422passed/1failed before the corrections and is not final-byte cover. The literal
  shared DomainStore64MiB/+1 test passes; the canonical master separately records the coherent
  installation graph ceiling54657024<67108864, not a fabricated installation overflow test.
  Historical integrity is now
  explicitly separated from fresh admission in the installation master; no live evaluation on replay.
  No real trust keys, native deployment,
  credentials, live provider requests, image publication or whole-product release were authorized
  or performed by this continuation. Whole-project completion time is not yet supportably estimated.
  Current accepted evidence is recorded in `evidence/resumption-2026-09-20.md`.

### Retained implementation chronology

Starting resumption audit: 223 focused Python tests passed (one inherited Starlette warning), and 58 Node
shell-logic tests passed. These are fresh scoped checks, not a new full-suite or browser E2E
claim. Claude's separately recorded 6351-pass full suite predates the inherited dirty slice.
Task26's reproduced connection leak is corrected and independently reviewed; final113covering
tests passed on unchanged bytes, while its first unexplained checkpoint failure is retained.
Task27 compiled-tool dispatch coherence and legacy-effect containment are accepted after an
independent review correction for exact permit-window issuer identity (249 covering tests and
7 parent-focused tests passed). Task28's separate whole-second checkpoint timestamp correction
is also accepted (163 covering tests and 4 parent-focused tests; strict stored grammar preserved).
Task29's actual file-first original intake is accepted after the independently reproduced
late-receipt/reselected-file duplicate-upload defect was corrected and rereviewed. Unchanged
backend246Python, amended44Node/3actual-owner-browser, parent6backend/4race tests pass.
See `evidence/resumption-2026-09-19.md`. Task30 encrypted-custody correction is accepted after
independent review found and R1 fixed false ciphertext-loss and mutation-before-global-validation.
Initial161coveringpass/1upstreamwarning; amended87coveringpass/no warnings and parent7regressions.
All17finalhashes andoutsidepreservation verified. This replaces actual plaintext/hash storage;
native isolation/SQLiteVFS safety, real enrollment/provider binding and live sends remain open.
Task31 shared node dispatch-context prerequisite is accepted: 337 scoped tests and 3 parent
checks passed; independent spec/quality review approved, original bytes/check ordering preserved.
Task32 tagged-subject/offline migration is accepted after independent R1 review closed two
preflight defects: complete ToolCall references and projected target capacity before mutation.
Earlier501pass/5fail and522pass/oneexistingwarning evidence remains recorded. R1 affected-family
cover279passed/no warnings; parent6R1checks passed (plus3initialfreeze checks). All639sourcehashes
verified, threeR1fileschanged/636unchanged. Actual temporary post-migration capture/settlement/
replay/new-node proof passed; no actual user store was migrated or generation call authorized.
Task33 private Claude text/catalog worker is accepted after independent review found and R1
corrected malformed-SSE final publication and interruption-cleanup masking. Initial756 and
amended243 scoped tests pass;657source manifest verified. Task34 pure provider image lineage/
descriptor joins are also accepted: independent spec/quality Approved,297coveringpass and all657
baselinefiles preserved. Task35 exact provider source bundles/additive deployment artifacts are
accepted:246coveringpass, independent spec/quality Approved,661baselinefiles preserved. Task36
is accepted after independent spec compliant/quality Approved, with no findings. Its controlled
server initialization/lifecycle frozen six-family cover passed506tests27.90s,
peak tracked ownedFD91/final0; controller verified2authorizedchanges+6new/678outsideunchanged.
Task37 runtime source/startup integration is accepted: independent spec compliant/quality Approved,
frozen nine-family549passed79.09s/one inheritedStarlettewarning, measuredpeak113FD/111retained.
Controller freshly verified690paths=683unchanged+3modified+4new and allsevenhashes. Maincheckout
remains clean; no native/live/admission claim. Task38 pure provider prepare/cancel protocol is
accepted after R2 independent spec/quality Approved. R1five-family366passed4.33s/no warnings;
R2test-only68passed2.98s/no warnings;700hashes verified. AllthreeImportant plus import-proof
minor closed. The pre-acceptance source_documents correction preserves every named source ref
without changing the generic reference walker. Task39 publisher is accepted after independent
spec/quality Approved, frozen506coveringpass33.33s/oneinheritedwarning, fresh703manifest verified.
Task40 existing slot-lifetime correction is accepted after independent spec/quality Approved:
263coveringpass/1unchangedroot-requiredskip/1inheritedwarning;704hashesverified.
Task41 actual owner/history/publication integration is accepted after independent-review fix round1;
the reviewer reproduced primary process-control masking by secondary finalizer DB failure and
identified missing required provider-path integration tests. R1 addresses both with one production
finalizer correction and five fixture/test changes. Its fresh eight-family cover reports199passed/
one inherited warning; controller independently matched all719 post-run hashes. Scoped independent
re-review approved both findings with no new Critical/Important breakage. These results are not a
whole-product qualification. Task42 requester lifetime is accepted after independent review and
one fixture-only R1 correction: production-cover315passed/2inheritedskips/21subtests, then amended
lifecycle203passed/no warnings;720hashes verified. Full per-checkpoint historical RED chronology
was not met for supplemental cases and remains disclosed. Task43 connected provider receipt/
observer/installation/history/API implementation is in progress after full preflight and actual42
dependency reconciliation. Focused evidence now covers genuine signed import, two authenticated
worker identifies, same-writer staged installation/history, real root/portable HTTP and source-closed
restart/replay. Populated v4 migration reports29 injected destructive checkpoints rolled back;
expiry, two-service races and consumed-publication recovery have focused checks. This is not final
acceptance: initial frozen45-family cover reported1487passed/2failed/one inherited warning.
The failures exposed timing-dependent test assumptions; a bounded two-test amendment preserves all
production bytes and the separate deadline-refusal checks. Four focused checks and the amended
three-family51-test cover pass; controller freshly verified749/749 frozen source hashes.
Independent review found a missing successful-consume reconciliation call and a shipped test's
private scratch dependency. R1 is assigned to the original writer, also closing explicitly
required historical-column-order and observer/migration/schema boundary coverage gaps.
R1's exact eight-family covering run passed95 tests with one inherited warning in405.89s;
controller verified749/749 post-run hashes. Scoped independent re-review passed all I1/I2/S1/S2
findings with no new breakage; Task43 is accepted within its recorded synthetic scope.
No all-green45-family result is claimed. Task44's bounded shared-store cleanup passed its exact
cover:193passed/one inheritedwarning290.22s; controller verified750/750 post-run hashes.
Independent review found no product defect but one required checkpoint-membership assertion missing.
The original writer corrected only the new lifecycle test:2affectedtests passed0.23s. Scoped R1
review passed with no new breakage; Task44 is accepted. Its final750-path manifest preserves both
product hashes and749other paths. This does not claim whole-store/native durability or safe replay
after an ambiguous commit. Task45 fixed-provider conformance is actively being implemented after
full preflight and two bounded design corrections. The worker reports green pure contracts,
same-writer subject resolution, six real fixed-vector connections and actual HTTP/history/replay
through source-less same-store restart. Negative-case hardening and the final frozen cover/review
are still pending; these intermediate synthetic results are not task acceptance, native platform
evidence or live-model operation. It does not activate credentials or qualify model dispatch.
Task41's initial32-family run recorded1040passed/63failed.
All63 failures were isolated to three obsolete/contaminating test functions; their approved
test-only corrections passed a fresh ordered421-test cover (one inherited warning). All initial27
implementation/new-test/schema files remained byte-identical; final30-path/719-file preservation
was verified. These are distinct runs, not a fresh all-green32-family or whole-product test claim.
No actual provider owner/admission/qualification approval follows from the lower-layer acceptance.
This is not live activation, qualification or canonical
model-choice authority. Overall delivery
estimate remains roughly 50% (including design), not the passing-test or checklist ratio.
Remaining are canonical tool authority and exact-action approval, encrypted provider/model
integration and the actual browser input-to-graph-to-execution journey. Current accepted
start/work pages save text and uploaded originals; STT, provider/model setup and
design generation remain unconnected there. Run observation is a
list projection, not the final graph-centered UX. Existing reusable modules do not close those
whole-story gates. Tasks.md currently has 40/90 tasks checked; that ratio is not product coverage.

| Scoped correction | Current evidence/status |
| --- | --- |
| File-first original intake on the actual owner work page | Task29 accepted after late-receipt duplicate-upload fix and independent rereview;246Python/44Node/3actual-owner-browser, parent6backend/4race checks. Exact originals/download/refresh/recovery and six responsive screenshots; no extraction/understanding or wholeUS1 claim |
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
| Task 24 step (c2): v3 storage constants, consume codec and prepare-api-v3 | `prepare_storage.py` gains `DDL_V3` (thirteen literal statements, seven byte-identical from v1/v2), `CHECKSUM_V3` = frozen C3, `TABLES_V3`/`CAPS_V3`/`NULLABLE_V3` (constants only; layout/insert/migration untouched); `prepare_v3_schema_exports.py` (consume input pinned to revision 2, installation summary, frozen consume 200 body, read schema with the accepted3 arm, `prepare-api-v3` artifact generated, v1/v2 artifacts unchanged); `prepare_v3_contracts.parse_consume`. 15 tests incl. a CHECK-matrix over the real DDL and a fresh-interpreter import boundary; 197 with neighbours. Review ACCEPT WITH CHANGES (3 SHOULD, NITs) folded in. Next (d): `app/deployment/stage_observer.py` against the in-process `WorkerProbeService` |
| Task 24 step (d): control-side stage postcondition observer | `app/deployment/stage_observer.py`: `observe_stage_postcondition` (inputs validated before any socket; one 2000 ms attempt from before connect under the process boot id; hex64 session ids; kernel peer == slot uid/gid; two probes with fresh challenges/ids, final probe ≤500 ms; every reply verified verbatim, compared field by field with the frozen `ExpectedStageIdentity`, fences rechecked; closed codes probe_unavailable/mismatch/deadline/invalid; no failure produces evidence) and the inert `StagePostconditionEvidence` (`extension-stage-postcondition-v1` canonical bytes). 29 tests against the actual in-process `WorkerProbeService` through the macOS seams; 68 with probe/listener neighbours. Review ACCEPT WITH CHANGES (4 SHOULD, 3 NIT) folded in RED-first. Next (e): coordinated storage v3 + consume transaction |
| Task 24 step (e1): v3 storage layout and v2→v3 migration | `prepare_storage.py`: `SHAPE_V3/COLUMNS_V3`, frozen `_V3` layout, three-shape `_layout`, `digest` storage-v3 suffixes, row grammar for the new columns, `_rebuild_v2_as_v3` (snapshot/delete/drop/create/restore of the four recreated parents under deferred FKs with the populated children in place, `(3,C3)`, equality proofs); `prepare_records.py`: `install` chains v1→v2→v3 in one writer, absent-schema guard and verify preflight for `extension_installation`, heads↔installations and anchors↔installations bijections, explicit closure until (e2). 7 tests (constructor upgrade, fault after every write, commit-without-restores refused, exact `(3,C3)`/old helpers reject v3, orphan anchor, consumed-receipt v2 journal migrating with children in place); three pre-existing tests adapted (v1→v2 test lands on v3; foreign installation anchor is an integrity denial). Review ACCEPT WITH CHANGES folded in. Next (e2): `_load_installation`, accepted3 rules, `consume_receipt` |
| Task 24 step (e2a): acceptance writer, accepted3 rules, events, v3 read | `records.accept_stage` (exact receipt_pending2 head with a succeeded receipt, revision 2, digests, the global guard, time inside the import→deadline window, the presealed evidence blob re-parsed through `stage_observer.parse_stage_evidence` and agreed with the request/receipt/admitted slot/window; then installation anchor + absent-only head, acceptance transition with the frozen consume reply and `deployment-consume-v1` command, `extension.staged` event, success consumption v2, index rows); `_load_consumption` v2, `_load_installation` (anchor, evidence, head, linkage, staged event byte-equal and next in sequence), per-item rules; lifecycle `accepted` transition/event fields/verify arm/`read_body` v3; `deployment.request_accepted` registered and the event export regenerated. 36 tests on the real store; 212 with neighbours. Review ACCEPT WITH CHANGES (3 MUST: slot comparison, `observed_at` bounds, time precondition; 2 SHOULD; 4 NIT) folded in RED-first. Next (e2b): service `consume_receipt` with the observer, lineage-derived `expected` (also in the verifier), fault injection |
| Task 24 step (e2b): service consume transaction | `PersistentDeploymentPrepare.consume_receipt` (`consume` replay operation; first writer: head/digest/revision/succeeded receipt/global guard, clock, expiry precedence, `records.expected_stage_identity`; the observer between the writers with mismatch 409 / others 503; `put_blob` preseal; final writer repeats every check, re-derives and requires the expectation, re-parses the evidence, `accept_stage`, full verification, one commit); `expected_stage_identity` (candidate → provenance lineage → descriptor join → embedded identity digests; slot identity/uid/gid) also in the verifier; observer clock aligned to the owner's. 21 tests against the actual in-process staged worker on the source fixture's slot (happy path, replay, accepted3+any 409, mismatch, unavailable/deadline/invalid 503, no-lineage candidate, due-head expiry before any socket, final-writer recheck after a cancel, fault at each of eight authority writes with only the orphan blob left, prepared head 409); the acceptance tests moved to the lineage-joined candidate. Review ACCEPT WITH CHANGES folded in. Next (f): route `deployment.requests.consume` + prepare-api-v3 GET |
| Task 24 step (f): owner consume route and prepare-api-v3 read | `app/api/deployment_prepare.py`: the preflight admits `consume` (POST only, the shared bounded limits, `parse_consume` pinning revision 2, the body filtered to the required members), `POST …/{request_id}/consume` → `service.consume_receipt` with the frozen unprefixed reply; the contribution descriptor gains `deployment.requests.consume` (browser session, `deployment.manage`); the composition pins updated (15 routes; 16 with the example contribution). 9 HTTP tests against the actual staged worker (frozen body validated against the consume/api schemas, GET/HEAD accepted head validated against prepare-api-v3 with seven equal headers, exact replay bytes, 409 afterwards, seven closed shapes 400/413 before the service, 401 → 404 ordering). Review ACCEPT WITH CHANGES (2 SHOULD, 5 NIT) folded in. Task 24 (a)–(f) complete; next: Continuation — T040 scheduler/ledger/worker integration |
| T040 slice: atomic semantic acceptance + budget settlement | `app/runtime/budgets.py`: typed `BudgetUsage`, `BudgetBook._settle_in_transaction` on a caller-owned transaction (exact transaction/Row guard, optional session binding, dispatched only, unknown retained with audit, known finalized/overage, returns the stored settlement; public `settle` delegates). `app/runtime/ledger.py`: `accept_result_and_settle` — exact book on the same vault, usage iff the observation is final (provisional/unknown retain the reservation), counters rebuilt before any write, one `BEGIN IMMEDIATE` transaction that classifies the result, refuses a reservation shared by another attempt, binds the run's budget session and settles an accepted result's reservation; deadline quarantine retains a dispatched reservation as unknown; duplicate/late/reused settle nothing; budget failure rolls the acceptance back; exact replay by command kind. 12 tests. Review ACCEPT WITH CHANGES (5 SHOULD, 5 NIT) folded in RED-first (evidence/runtime-result-settlement-t040.md). Next: worker/attempt dispatch through the scheduler |
| T040 slice 4: attempt dispatch through the scheduler | `app/runtime/node_attempts.py`: `AttemptBinding`, `AttemptDispatchRequest`, `AttemptTransportResult`, one-shot `VisitAttempt`, `NodeAttemptDispatcher` (visit-derived attempt/reservation/command identities; reserve → budgeted send intent bound to the reserve revision → code-owned transport under the one-shot permit → `accept_result_and_settle`; send replay resolves only through the committed result, never re-sends; fault/inexact/unresolvable results are `outcome_unknown` with the reservation retained; permit discarded when the acceptance did not commit; a proven never-sent attempt continues with the next attempt number, bounded). `scheduler.py`: `NodeContext.attempt`, `build_scheduler(attempts=)` (exact dispatcher, same ledger, agent nodes only), the bound node's returned ref must equal the committed result. 9 tests over the real StateGraph + SQLite ledger + budget book; no worker/provider (in-process fake transport). Review ACCEPT WITH CHANGES (4 SHOULD, 5 NIT) folded in RED-first (evidence/scheduler-attempt-dispatch-t040.md). T040's listed open items are closed; the worker-side operation and the real transport remain T087/T018/T042 |
| T087/T018 slice: worker execute operation + real attempt transport | `app/workers/extension_execute_messages.py`: `extension-execute-v1` / `extension-execute-result-v1` on the channel's existing request/result types (identities, refs, `remaining_ms`, nonce; the ledger's result vocabulary mirrored and pinned; usage iff final, output iff succeeded, unknown claims no known terminal). `extension_probe.py`: the router over the code-owned table `_OPERATIONS` (`status` from an actual reading; unregistered → typed refusal); mode selected by the first frame's schema; one execute per connection. `app/runtime/extension_attempt_transport.py`: the real AF_UNIX transport under the consumed permit window (exhausted window never connects), one request/reply with correlation/nonce/operation checks, control-measured `status` usage, succeeded output sealed control-side as an `artifact` keyed by the send command, typed errors carrying the dispatch effect. `node_attempts.py`: the window travels to the transport; observations built inside the fault boundary. Contract §1/§2/§2b/§3/§4/§6 amended. 36 tests over the real socket + StateGraph + ledger + book; covering 266. Review ACCEPT WITH CHANGES (2 MUST, 5 SHOULD, 4 NIT) folded in RED-first (evidence/worker-execute-transport-t087.md). Next: connected browser path per Continuation; T087 semantic operations beyond `status` |
| Connected browser path: `runs-v1` route contribution | `app/services/runs.py` `PersistentRuns`: owner-named input references (stored graph, work revision, environment, consent, budget policy), the `run_manifest` sealed by command with `run.started` in one transaction, budget session + ledger run by the same command outside the writer, exclusive per-run execution to completion or a gate, replay reusing the manifest whatever happened after it, conflicts on any differing input, no-execution read, resume, durable once-only `run.stopped` (completed / cancelled / infrastructure_failure), phases from the head. `app/api/runs.py` + `runs-v1.json`: `runs.create` / `runs.read` / `runs.resume` (browser session, work scopes) behind the web boundary's preflight and caps; `create_app(run_executor=)` injects the code-owned compilation authority + handler registry (503 without). `scheduler.observe()` and outcome identities `pending_node_ids` / `rejected_human`. 19 HTTP tests; covering 365. Review ACCEPT WITH CHANGES (3 MUST, 4 SHOULD, 6 NIT) folded in RED-first (evidence/runs-routes-browser-path.md). Next: `app/static/runtime.mjs` (T048 DOM) or the attempt layer/cancel per Continuation |
| T048 logic half: `app/static/runtime.mjs` | Pure run-observation logic over `runs-v1`: closed phases/labels/input kinds/error codes mirrored from the server (Python drift test), route builders, closed create/resume commands, `runView` (server phase re-checked against the projection's identities, node states from identities only, visit rows with their own results, activations and consumed approvals kept, optional graph node universe for 미수행), `accessibleRows` (text states, both gate scope kinds), `createRunObserver` (injected request, generation-ordered, busy from in-flight count, closed error partition from code or status, errors target-scoped, no redundant announcements). `node --test` 13; mirror 4. Review ACCEPT WITH CHANGES (2 MUST, 8 SHOULD, 6 NIT) folded in RED-first (evidence/runtime-gui-logic-t048.md). Next: the DOM half (asset route, `api` helper CSRF header, run view in the shell) or cancel/recovery routes |
| Supported factory serves the browser modules; shell on `X-DeepTwin-CSRF` | `app/api/assets.py`: closed module catalogue, whole-file responses, closed `unavailable` envelope, parameterless endpoints; the supported session router serves every module publicly (GET/HEAD) beside the setup/login stub; the boundary refuses any query on asset paths; the preview shares the catalogue and admits `x-deeptwin-csrf` beside `x-csrf-token`; `app.mjs` sends the supported header. 5 + 1 tests; covering 229/138. Review REJECT→ACCEPT WITH CHANGES (query-parameter bypass closed, Range/envelope, caching deviation stated) folded in RED-first (evidence/shell-assets-supported-factory.md). Next: the run view in the shell against the supported routes (CSRF source, base path; T048 DOM) or cancel/recovery routes |
| Run cancellation: `runs.cancel` | `ledger.cancel_run` (replayable, durable `cancelled` phase; a cancelled run admits no new execution or attempt) + `attempts_for_run`; `PersistentRuns.cancel`: durable closure under the run lock when idle (a completed run is a conflict), each live attempt's gate requested with retry on a moved revision, `run.stopped(cancelled)` once, a live execution ends the run itself once; resume of a cancelled run is 409, create replay reports it; every receipt carries `cancellation` (requested + per-attempt gate/remote facts); the public snapshot accepts every run phase; `runtime.mjs` phase `취소됨` and the two a11y rows. Ledger 2 + routes 6 + node 14; covering 312/137. Review ACCEPT WITH CHANGES (2 MUST, 3 SHOULD, 2 NIT) folded in RED-first (evidence/run-cancel-route.md). Next: recovery/retry route or the shell's run view |
| Owner recovery: `runs.recover` — retry after a sent attempt | `NodeAttemptDispatcher.build(retry_after_terminal=)`: on the owner's recovery only, the next attempt number of the same execution when the ledger proves the earlier one terminal (failed/timed_out), remote-observed, finally accounted, without late evidence — never by default, never after unknown; `MAX_ATTEMPTS_PER_VISIT` (4) bounds unsent continuations and retries; a spent budget refuses before any reserve. `PersistentRuns.recover` (completed/cancelled → 409, the head re-run under the run lock with the retrying executor); `runs.recover` route; receipt attempt rows carry `attempt_no`; `runtime.mjs` cancel/recover routes and `시도 N` rows. Dispatch +4, routes +2, node 14; covering 249/140. Review ACCEPT WITH CHANGES (0 MUST, 4 SHOULD, 5 NIT) folded in RED-first (evidence/run-recover-route.md). Next: the shell's run view against the supported routes, or the attempt layer in the run trace |
| T040 complete: checkpoint↔attempt binding | `AttemptBindings` registry (per run, in memory, bounded) handed by `build_scheduler` to `LedgerCheckpointSaver`; after the visit's `committed == result` gate the execution is registered with its accepted attempt (`VisitAttempt.accepted_attempt`); the saver binds each pending-writes row carrying exactly that execution's result through `write_checkpoint(attempt_id=)` (attempt id, revision at write, execution, envelope digest); the ledger re-verifies every bound row of the run on the next reserve and at startup, not only the head. Checkpoints +1, dispatch +2, ledger +4; covering 185/145. Review ACCEPT WITH CHANGES (0 MUST, 3 SHOULD, 3 NIT) folded in RED-first (evidence/checkpoint-attempt-binding-t040.md). Next: the run trace's attempt layer (T048) or the shell's run view |
| T048: run trace attempt layer | `TraceAttempt` and `TraceExecution.attempts` / `producing_attempt_id` in `app/services/run_trace.py`: each visit's attempts as the ledger recorded them, the durable result attributed only to the attempt the bound checkpoint row names (three honest states: no attempts / attributed / unattributed); one closed read boundary (every ledger or storage failure is `RunTraceError`); results also from the head's pending writes (a crash between the bound row and the merging checkpoint is not a gap); `RuntimeLedger.bound_checkpoints_for_run` reads and re-verifies the bound rows in one transaction | 2026-09-18 | Independent review ACCEPT WITH CHANGES (1 MUST leak, 3 SHOULD, 3 NIT) folded in RED-first; run trace +4, ledger +1; covering 252; Ruff clean (ledger 18/18 pre-existing) | evidence/run-trace-attempt-layer-t048.md |
| T048/T025: the shell's supported session client | `app/static/session.mjs` (new, catalogued public asset): the deployment base path derived from the document location, the CSRF token from `GET {base}session` kept private in the closure, and the request adapter the run observer and approvals module need (same-origin, `X-DeepTwin-CSRF` on commands, JSON, paths confined to this API, the closed partition on thrown errors, a 401 or a command's 403 drops the session); the client's wire shape exercised against the real supported factory | 2026-09-18 | Independent review ACCEPT WITH CHANGES (2 SHOULD, 5 NIT) folded in RED-first; node 9 (+30 unchanged), mirror 4, covering 115; Ruff clean | evidence/shell-session-client-supported.md |
| T048: the run view's DOM half | `app/static/run-panel.mjs` (new, catalogued): status (a `running` head reads 미완료), one text row per node and per past attempt, closed error text by server code, three commands gated by the server's own admission (resume on created/running, cancel while open, recover only on running), one fresh command id per click, a refused command re-read at once with the refusal retained; `runtime.mjs` lists every attempt as a row, keeps the view on a refused cancel/recover, ignores a superseded late failure, and cannot be left busy by a throwing renderer | 2026-09-18 | Independent review ACCEPT WITH CHANGES (2 MUST gating/text honesty, 5 SHOULD, 6 NIT) folded in RED-first; node 43, Python pins 13, covering 142; Ruff clean | evidence/run-panel-dom-t048.md |
| T087: worker `describe_tools` | The worker's second code-owned operation: `describe_tools` answers from its code-owned tool table (`_TOOLS`, empty today), never the port catalogue; the reply's output grammar is selected by the operation (`{tools:[…]}` per extension-ports.md §3.2 with the wire's stated narrowings, bounded by canonical bytes so the reply always carries it); control measures the usage of both read-class queries and refuses a completed query claiming unknown usage; `registered_operations` is `["describe_tools", "status"]`; contract §2/§2b/§4/§6 amended | 2026-09-18 | Independent review ACCEPT WITH CHANGES (6 SHOULD, 4 NIT) folded in RED-first; covering 47 + 97 + 48; Ruff clean | evidence/worker-describe-tools-t087.md |
| T018/T087: artifact input leg of the execute exchange | The bounded digest/chunk/receiver-credit stream rides the extension channel's `extension-artifact-v1` type: the request declares ≤ 8 inputs (≤ 1 MiB), control streams them after the request frame from fresh sources per attempt, the worker admits them into bounded in-memory sinks before running the operation and only for a registered operation whose port profile takes request artifacts (E-profile queries refuse before any byte); a stream violation closes without a reply and control records the typed `transport_stream` → `outcome_unknown`; no registered consumer yet (test-only handler under `invoke_tool`); contract §2b/§3/§4/§6 amended | 2026-09-18 | Independent review ACCEPT WITH CHANGES (2 MUST, 4 SHOULD, 3 NIT) folded in RED-first; covering 58 / 139 / 63 / 42; Ruff clean | evidence/worker-artifact-input-leg-t018-t087.md |
| T048: the run panel's run source | `app/static/run-list.mjs` (new, catalogued): the public snapshot's durable run rows as the honest source of runs to observe (no production path records a run consent, environment or work revision yet, so no creation surface): exact validation mirroring the route's version string, the ledger's durable phases and the server's item bound; a select with nothing auto-selected, generation-ordered refreshes, a failed re-read keeps the last honest list and the choice; wired to the run panel through the session client | 2026-09-18 | Independent review ACCEPT WITH CHANGES (1 MUST bound, 3 SHOULD, 5 NIT) folded in RED-first; node 44, mirror 4, covering 144; Ruff clean | evidence/run-list-source-t048.md |
| T048/T025: the shell mount on the supported factory | `app/static/observe.html` + `observe.mjs` (new, catalogued public assets): a public observation page under the deployment base path with relative asset paths, whose module establishes the owner session the browser holds and only then mounts the run list and the run panel; without a session it states the fact (the setup/login screen still pending) and mounts nothing; a boot failing outside the exchange still reaches the status line; `/` stays the setup/login stub | 2026-09-18 | Independent review ACCEPT WITH CHANGES (3 SHOULD, 7 NIT) folded in RED-first; node 31, shell assets 7, covering 190; Ruff clean | evidence/observe-page-mount-t048.md |
| T087: the worker's first real tool `text_profile` and `invoke_tool` | The worker's table holds `text_profile` 1.0.0 (read effect; one `document_source` text/plain input, strict UTF-8; byte/code-point/line/word counts and digest with stated definitions); `invoke_tool` names its tool in the request, refuses calls outside the tool's contract before reading a byte, and answers `{tool_id, version, result}`; control mirrors the table at build (a mismatched call is refused, never lost as unknown), checks the reply's tool and the result's digest/size against the input it holds, verifies exactly one tool call and refuses unknown/cancelled from a read-effect tool; entries carry schema digests, not refs | 2026-09-18 | Independent review ACCEPT WITH CHANGES (2 MUST, 7 SHOULD, 4 NIT) folded in RED-first; covering 78 / 97 / 84 / 80; Ruff clean | evidence/worker-text-profile-tool-t087.md |
| T018/T087: worker-returned output artifacts and `text_normalize` | The reverse leg: a tool's output artifacts travel as an offered batch on the artifact type before the reply; the reply binds each (ordinal, role, media, size, digest); control admits them only under the named tool's mirrored output contract, verifies the bindings and the result's digests/sizes/`changed` against the bytes it holds, imports each as registered content and seals the blob references into the attempt's artifact, counting artifact bytes as output; the second real tool `text_normalize` (NFC, LF, BOM removed; an oversized output is its own failure); the previous slice's unlanded contract closures landed here (stated) | 2026-09-18 | Independent review ACCEPT WITH CHANGES (2 MUST, 3 SHOULD, 4 NIT) folded in RED-first; covering 89 / 97 / 68 / 80; Ruff clean | evidence/worker-output-artifacts-t018-t087.md |
| T025: the instance's first screen (setup/login) | `app/static/start.html` + `start.mjs` served at the supported factory's `/`: an ownerless instance shows the first-owner setup form (the one-time capability typed in, never in a URL; a 15+ character password), an owned instance the login form; `/health` reports the public setup state (`owner`, the claim's state, `expired` past the deadline) behind the closed error boundary; client bounds mirror the server's; a session leads to the observation page; the observation page now names the start screen | 2026-09-18 | Independent review ACCEPT WITH CHANGES (1 MUST, 7 SHOULD, 8 NIT) folded in RED-first; node 19, shell assets 13, covering 115; Ruff clean | evidence/first-screen-setup-login-t025.md |
| T087: the ToolCall record and the effect gate | `runtime_tool_calls` in the ledger — one write-ahead intent per attempt (tool/version, the mirror's effect class, the ordered inputs, the approval), replayable and idempotent for the same intent, settled once (succeeded with the sealed result / failed / unknown, unknown re-settleable), orphaned intents settled at startup from the attempt's own terminal outcome; the transport records the intent before the request frame and settles it from what it observed (a vouched non-send is failed, any fault unknown); the gate requires an `action_approval` for external or instance-critical effects and refuses one for a read; vocabularies pinned to the ports contract | 2026-09-18 | Independent review ACCEPT WITH CHANGES (6 SHOULD, 5 NIT) folded in RED-first; covering 81 / 178 / 97 / 208; Ruff: no new findings | evidence/tool-call-record-effect-gate-t087.md |
| T087: the output_bytes reservation from the tool's bound | the transport states `output_bytes_bound` (the reply frame's ceiling plus the tool's stated growth over its inputs, never over the leg's ceiling) and enforces the artifact part against what it received (an inflating worker is a mismatch, never an accounting overrun); the dispatcher refuses a binding reserving less at build; a policy cap under the bound refuses before any row | 2026-09-18 | Independent review ACCEPT WITH CHANGES (1 MUST, 3 SHOULD, 4 NIT) folded in RED-first; covering 74 / 41; Ruff: no new findings | evidence/output-bytes-reservation-t087.md |
| T023/T025: the intake's server surface (`works-v1`) | the supported factory gains `POST /api/v1/works`, `GET|HEAD /api/v1/works/{id}` and `POST …/{id}/revisions`: an owner command seals each revision as an immutable `work_revision` record (the run's own input kind), a command names exactly one revision across every work, a stale expected revision is a conflict, the text bound is the record's own 64 KiB; the boundary's caps, preflight and envelope wired | 2026-09-18 | Independent review ACCEPT WITH CHANGES (2 MUST, 3 SHOULD) folded in RED-first; works 23, covering 242; Ruff clean | evidence/works-routes-intake-t023.md |
| T023/T025: the intake page (`work.html`/`work.mjs`) | the first work screen after login on the supported factory: the §5.1 notices with a detail, `어떤 일을 맡기고 싶으세요?`, a browser-only draft said as such, saves as work revisions under commands bound to their text and settled before a newer draft, the draft's base revision carried across reloads (another screen's save is a conflict with reopen or rebase), a vanished work forgotten without the draft, materials and microphone honestly absent; the start screen lands here | 2026-09-19 | Two independent reviews (REJECT → rewrite → ACCEPT WITH CHANGES) folded in RED-first; node 21 (+37), Python 140; Ruff clean | evidence/intake-page-t023.md |
| T087: the approval's verification for a tool call | before a byte leaves, the transport reads the owner's recorded decision for the run, node and tool scope (a delimiter-proof uuid5 scope) through the approvals service and requires an approval that is the exact record named; a rejection, another node's or run's approval, a forged digest or a later version is refused before the channel, the connection and the ToolCall intent | 2026-09-19 | Independent review ACCEPT WITH CHANGES (5 SHOULD) folded in RED-first; transport 41, covering 124; Ruff: no new findings | evidence/tool-call-approval-verification-t087.md |
| T040/T087: the transport's vouched dispatch effect journaled | when a transport fault vouches `definitely_not_sent` or `may_have_started`, the dispatcher records it as the attempt's transport observation before accepting the unknown outcome, so the dispatch status carries the vouched effect; the ledger's trust model (a committed send intent is possibly sent) is unchanged — a free retry after it stays open; an unreadable vouch is a plain fault; the crash window reconciles as unknown | 2026-09-19 | Independent review ACCEPT WITH CHANGES (1 MUST, 2 SHOULD) folded in RED-first; dispatcher 21, covering 157; Ruff clean | evidence/vouched-transport-effect-journal.md |
| T047/T087: one effect vocabulary for tools | the in-memory tool boundary takes the ports contract's seven effect classes as its closed set and the ports' external family as its approval rule (equal to the ledger's set); the earlier four names are refused (a legacy `external` never stated reversibility); an N-family tool never records an unknown outcome; runtime.md's tool-port row corrected | 2026-09-19 | Independent review ACCEPT WITH CHANGES (2 MUST, 3 SHOULD) folded in RED-first; boundary+audit 39, covering 147; Ruff clean | evidence/tool-effect-vocabulary-t047-t087.md |
| T087: the ToolDefinition-backed effect gate | the compilation authority's trusted tool definition carries the tool's identity and effect class (ports vocabulary; one class per tool; the worker's identifier grammar); an external-family definition's approval scope is derived and a node bound to such a tool must require it (bound by structure to a human gate's approval edge); `CompiledGraph.tool_effects` states the facts; the transport takes the class from the binding, refuses a disagreeing mirror and looks the decision up under the graph's gate | 2026-09-19/22 | Independent review ACCEPT WITH CHANGES (5 SHOULD) folded in RED-first; graph contract+transport+design generation 134, transport 48 | evidence/tooldefinition-effect-gate-t087.md |
| Merged tree reconciliation | the parallel orchestration's tasks 27–50 (uncommitted, verified only by subsets) brought to one green full run: 81 fixed-date time bombs, 3 core import boundary violations, 2 stale route pins, 6 detached-field assertions, 1 schema branch, and an in-process module reload that poisoned every later `create_app` (82 setup errors) — each reproduced then fixed at its cause | 2026-09-22 | full run 1: 9,104 passed / 95 failed / 82 errors → run 2: 9,201 passed / 0 failed / 82 errors → run 3: 9,280 passed / 3 failed (timing-dependent, pass alone) / 0 errors | evidence/merged-tree-reconciliation-2026-09-22.md |
| Task 51: the owned shared gateway prerequisite (G1–G10) | the fixed `cp-provider` profile; the factory-issued authenticated owner with a retained deadline, one reader latch, bounded duplex reads and an identity-bound close; one shared frame/fragment grammar for the vault and send engines behind a serial ingress (one first-frame decode, one dispatch, the legacy shapes closed); the owned send dialogue with linearized commit/cancel control — the claim order is the wire order, a losing caller never closes a claimant or a successor, every transport and stream fault mapped to the closed failure classes, a cleanup failure of any local kind never erases a validated cancellation or observation | 2026-09-22 | three independent adversarial stage reviews (A/B ACCEPT WITH CHANGES, C REJECT) and a re-review of the C closures (ACCEPT WITH CHANGES) folded in RED-first; profile 3 + owner 16 + owned 40; full regression 9,341 passed / 1 failed (a pre-existing 1-in-16 flake of a design-store pin, fixed at cause) / 2 skipped | evidence/owned-shared-gateway-task51.md |
| T048: the owner's run consent (`run-consents-v1`) | `POST /api/v1/run-consents` seals one immutable `run_consent` per command over the exact graph, work revision, environment and budget policy records a run names (each resolved in this vault with its declared kind and readable by the run route's own readers), authored by the owner's human actor with its `approval.decided` event in the same transaction; exact replay, conflict on any other body; a stored row is consent evidence only with the writer's whole discipline; `GET|HEAD …/{consent_id}`; the run route accepts the sealed consent | 2026-09-22 | independent review ACCEPT WITH CHANGES (1 MUST: reads trusted any stored row) folded in RED-first; consents 7, route/catalog/owner-integration neighbours 197; full regression 9,348 passed / 1 failed (the recorded timing-sensitive conformance final-wall case, passes alone) / 2 skipped | evidence/run-consent-record-t048.md |
| T048: the run route verifies its consent; one consent, one run | `POST /api/v1/runs` starts a run only under a `run_consent` that resolves with the writer's whole discipline and names exactly the run's graph, work revision, environment and budget policy (403 otherwise); a consent another command already sealed a manifest under is spent (409); nothing sealed or emitted on a refusal; a sealed command's replay reuses its manifest; the route tests seal real consents | 2026-09-22 | independent review ACCEPT WITH CHANGES (single-use, the pins, the deferred list) folded in RED-first; consents 8, runs+works 58, neighbours 192; full regression 9,348 passed / 2 failed (the parallel orchestration's provider suites, order/timing-dependent, pass alone) / 2 skipped | evidence/run-consent-verification-t048.md |
| The provider suites' order/timing failures chased at cause | two cross-cutting causes reproduced and fixed in the test fixtures — a 3 GB heap from the reader tree's unbounded per-open ledger whose cyclic collection paused a later test's IPC for 13–30 s (recording now opt-in; the receipt context collects in its own teardown), and the fixture worker's 5 s budget that became a 5 s per-socket timeout under a frozen clock (now the listener's 30 s window; the late-finalization case waits for the worker) — plus three test expectations wrong about transport outcomes and one macOS socket-close join; no product change | 2026-09-22 | full regression **9,350 passed / 0 failed / 2 skipped**, longest GC pause 0.25 s (was 30 s) | evidence/provider-suite-flakes-2026-09-22.md |
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

Current conservative estimate: **about 50% ±5 including design** (2026-09-21). This reflects the
new persistent owner/run/worker/shell integrations, not a completed end-user journey. Eight previously overstated completion markers
were reopened (T039/T041/T055/T056/T057/T061/T064/T065) without discarding their tested partial code.
This is a scope-accounting correction, not a claim that existing functionality regressed. The
table below preserves the **2026-09-13 historical estimate (46.2%)**; it is not current runnable
product coverage. The following current rough allocation updates only evidence-supported partial
engineering credit; it does not replace the separate full-story acceptance gates.

### Current rough allocation — 2026-09-21, after accepted Task47

Same original weights; fractions are estimates, not test-pass ratios. Accepted Tasks41–47 strengthen
provider staging/history, fixed private conformance, installation verification and finite cleanup inside the existing partial
infrastructure allocation; they do not yet close an additional browser journey. This bounded
infrastructure acceptance does not justify a material whole-product percentage increase. Task47's
accepted conditional execution receives no completed-browser-journey credit. Keep the same rounded estimate;
contributions are below.

| Work package | Weight | Rough fraction | Contribution | Current evidence boundary |
| --- | ---: | ---: | ---: | --- |
| Whole-product design and traceability |20|1.00|20.0|Accepted product design; implementation-era source/hash reconciliation and final coverage audit still required |
| First use, input, providers and persistence |15|0.65|9.8|Actual owner/intake/original-file flow plus tested provider foundations; browser model setup, production STT and input-to-understanding still unconnected |
| Graph generation, criticism and approval |15|0.20|3.0|Existing offline/value-layer work only; no added credit for a connected live graph-design experience |
| Runtime, framework tools and artifacts |20|0.40|8.0|Accepted scheduler/attempt transport, source/publisher/cleanup and custody prerequisites; canonical provider binding/exact-action authority and graph runtime UI remain |
| DeepTwin inquiry, paired evaluation and promotion |15|0.30|4.5|Retain partial module credit; actual lens-grounded inquiry, paired queue execution and connected human promotion remain |
| Full-journey integration, security and effect evidence |10|0.20|2.0|No increased whole-story/native/live credit from scoped temporary tests |
| Web distribution, recovery and release docs |5|0.34|1.7|Retain existing input-lock/static boundary credit; no final images/clean-host/signing/release completion |
| Total |100|—|about49|User-facing rounded estimate remains about50% ±5, including design |

The modest change from the historical46.2 estimate reflects actual intake and runtime prerequisites,
not a claim that the end-user journey is half connected. Whole-goal ETA remains unsupported: no
complete integrated story yet supplies comparable delivery throughput, and native/live/owner
approval readiness cannot be converted to an invented finish date.

### Historical allocation — 2026-09-13, retained unchanged

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
