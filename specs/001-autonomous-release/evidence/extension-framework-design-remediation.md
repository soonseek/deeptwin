# ADR-014 extension-framework design remediation

2026-09-08 · Status: **revision-7 independently accepted after six rejected revisions; T086 closed
for design with P1=0/P2=0**.

## Scope and claim boundary

This is a documentation-only response to a read-only adversarial audit of DeepTwin's V1 framework
identity and extension boundary. It changes no active T018-B2 implementation or test, runs no
product tests, qualifies no extension, builds no image and publishes nothing. The first T086 review
remains historical evidence; it is not silently rewritten as if it had considered ADR-014.

The canonical identity itself passed: the reusable server core, bundled official browser product/
reference client, isolated workers and external deployment authority remain distinct. Legal status
also remains honest: the repository has no project license and T084 still requires explicit
copyright-owner approval before an open-source release or redistribution claim.

## Findings and remediation map

| ID | Severity | Concrete pre-remediation evidence | ADR-014 design remediation | Implementation/evidence owner still open |
| --- | --- | --- | --- | --- |
| X01 | P1 | `contracts/runtime.md` treated nine kinds as one protocol; `sdk/python/deeptwin_ext/protocol.py:9-29` exposes only generic `describe/invoke/health`; `app/extensions/contracts.py:210-243` accepted broad protocol combinations and extension-owned schemas | Shared envelope is transport only. Runtime §6 now owns a closed kind/artifact/port/trust/staging matrix and per-kind operations/base schemas/effect/idempotency/cancel/outcome/artifact semantics; managed provider runner has a distinct agent-loop port | T087 implementation and staged-topology R16 engineering proof; T083 repeats the final clean-host V8 proof; T086 independent design review |
| X02 | P1 | `app/extensions/registry.py:1,58-67` stores lifecycle in memory; `:191-196` qualifies only `verified`, while `app/extensions/contracts.py:536-545` cannot return qualified/enabled state to verified | Data model separates durable verified artifact installation from repeatable qualifications, binding revisions/heads and rollback-retention revisions/heads; DB/CAS record+head+event transaction, startup reconcile, atomic supersession/rollback and exact owner release are specified | T087 persistence/migrations/crash/concurrency implementation; T025 authority integration |
| X03 | P1 | `app/extensions/registry.py:154-165` changes staging state but stores no artifact; operations formerly allowed product binding only after unspecified deployment staging; T018 forbids runtime-created mounts and T081 only named fixed images | Executable extensions are acyclic digest-pinned OCI service descriptors staged only by external deployment authority with a closed kind-specific request payload, signed one-use receipt, actual handshake and qualification; only descriptor/request-declared dedicated mounts are operator-created at service start, with no product download/Docker/host-path/post-start/unmanifested mount/core rebuild | T087 staged integration and private two-platform conformance-fixture lock; T081 core distribution schema only; T083 two-clean-host out-of-tree tool proof; OPS-AC11 |
| X04 | P2 | The prior experience contract and `plan.md` UI tree had no extension lifecycle screen despite constitution II requiring framework capabilities to be web-governable | Experience §6.4 and UX-AC11 define `Settings > Extensions`, exact state/evidence and code-free import plus qualified bind/disable/rollback and warned rollback-retention release; executable staging remains visibly operator-only | T087 UI/routes and T078 accessibility/usability evidence |
| X05 | P2 | `sdk/python/README.md:3-10` is authoring-only, has no install metadata; `app/tests/test_extension_sdk.py:12-15` injects a source path; `app/tests/test_client_conformance.py:113-156` compares in-process objects while `app/api/service_clients.py:1` remains unmounted | Plan/API/tasks split installable extension-author and HTTP/OpenAPI packages; staged proof uses another process/environment with no `app` import against actual T025 routes. Final T083 repeats client parity on portable HTTPS and confirms HTTP-only loopback does not expose bearer automation; extension staging still runs on both | T087 package/engineering parity, T025 routes, T083 final clean-host parity/denial |
| X06 | P2 | `app/tests/test_client_conformance.py:91-110` uses non-recursive `glob("*.py")` and forbids only API/static module names | Recursive architecture enforcement covers every core subpackage and forbids API/static/server presentation plus direct FastAPI/Starlette/Jinja imports | T087 architecture test and release regression |

The first independent ADR-014 review rejected the revision-1 remediation. That verdict is not
overwritten or relabelled as clear. Revision 2 addresses its exact blockers:

| ID | Severity | Rejected ambiguity | Revision-2 remediation | Still-open proof owner |
| --- | --- | --- | --- | --- |
| IR-01 | P1 | A head keyed only by port/scope/purpose made independent same-port extensions overwrite one another | Data model, API, runtime, operations, UI and tasks use a stable core-consumer binding slot plus a closed core-owned capability-selector digest. Different slots/selectors coexist; exact same-slot candidates alone compete by expected-head CAS, with extension ID as the candidate | T087 slot/coexistence/stale-head/rollback implementation and R16; T083 clean-host repetition |
| IR-02 | P1 | One vague extension deployment payload mixed current/target fields, allowed future refs and left old/new result presence and digest direction cyclic; revision-2 scans also caught an unconstrained common `preconditions` bag and result observations not normatively equality-bound to request identities/digests | Data-model §3.2/API §1/OPS §2 define four request plus four result closed schemas. Every extension envelope has constant `preconditions={}` and the arm is its sole condition authority. Stage has no current, current uninstall has no new artifact, replace uses committed current head+next revision, and superseded retirement has no future installation ref. Every non-absent observation is request-bound to its new/current/target tuple. Digest/ref order is descriptor→manifest→request→receipt→installation-or-retirement head→consumption/event | T087 schemas, duplicate-precondition and tuple-mismatch rejection, receipt/handshake/transaction/crash/race tests; T083 repetition |
| IR-03 | P2 | Port summaries, reused prose and untyped nested members did not let an out-of-tree author mechanically build interoperable config/request/result/error schemas | New normative `contracts/extension-ports.md` fixes 44 schema IDs, exact primitive/collection/nesting/byte bounds, every common and per-port/nested required field, discriminated operation inputs/outputs, terminal/core+port errors, core effect/idempotency/cancel/artifact meaning and refinement rules. Named local definitions expand byte-for-byte. The SDK authors manifests/refinements only and consumes hash-equal base bindings | T087 schema generation/conformance and separately installed SDK test |
| IR-04 | P2 | Recursive reusable-core scan omitted `app/extensions/**` | Plan/runtime/tasks now name all five roots and require transitive scanning of `app/extensions/**` plus API/static/server/FastAPI/Starlette/Jinja and dynamic-import bypass rejection | T087 `app/tests/test_extension_architecture.py`; T079/T083 regression |
| IR-05 | P2 | Common service-client route/auth/storage/server work and extension-specific parity had no exact owner/path | Revision 2 assigned common authority to T025 and extension parity to T087, but left their actual mount seam overlapping; IR2-03 below supersedes that incomplete assignment | T025 common route tests; T087 black box; T083 portable-HTTPS parity plus loopback denial |

The revision-2 independent review also rejected the amended design. Revision 3 addresses its four
exact blockers plus the rollback-retention reachability gap found while independently rescanning the
IR2-01 remediation; no rejection is overwritten:

| ID | Severity | Revision-2 blocker | Revision-3 documentation remediation | Still-open proof owner |
| --- | --- | --- | --- | --- |
| IR2-01 | P1 | After A→B replacement, current-only remove could name only B; revision-3 rescan also found that immutable rollback history had no explicit eligibility-release transition, so zero retained dependencies were unreachable | Four exact deployment arms split current uninstall from superseded retirement. Separate rollback-retention revision/heads make authority explicit: supersession/disable creates `retained`, rollback consumes it and owner exact-head release preserves history/current heads while forbidding that target rollback. Retirement then names a strict ancestor, rechecks zero dependencies and advances only A's retirement head. Current uninstall is reached by disable→release-retention→dependency-zero, and its tombstone is an exact stage precondition so reinstall remains reachable | T087 A→B→release-A-retentions→retire-A and no-environment B-disable→release→uninstall→C-restage persistence/dispatch/rollback/crash tests; UX-AC11; R16; OPS-AC11; V8 |
| IR2-02 | P2 | Result schema left artifacts 0..256 for every operation/terminal, including cancelled codec | `extension-ports.md` now enumerates 52 operations into exact allowed terminal classes and success empty/V/O cardinality; every allowed failed/cancelled/unknown has `artifacts=[]`, with codec cancellation, exact-one refs, role/count/byte negatives assigned to T087 | T087 generated schema/semantic-validator 208-combination coverage; T083 packaged repetition |
| IR2-03 | P2 | T025 and T087 both implicitly owned server route mounting | T025 owns a frozen build-installed first-party router-composition seam and the sole `app/server.py` call; T087 owns one fixed extension route module/descriptor registered through it without editing either T025 file. Arbitrary extensions cannot add HTTP routes | T025 generic seam/auth tests; T087 extension contribution and real-server black box |
| IR2-04 | P2 | Client quickstart could be read as sending bearer automation over local HTTP | Portable HTTPS alone runs real bearer parity. Local HTTP sends no real bearer and uses a fixed non-secret canary to prove route non-registration/pre-parser denial and no cookie/plaintext fallback | T087 staged HTTPS engineering proof; T083 both-host final repetition |

The revision-3 independent review found no P1 but rejected two remaining P2 inconsistencies.
Revision 4 addresses both without relabelling the earlier result:

| ID | Severity | Revision-3 blocker | Revision-4 documentation remediation | Still-open proof owner |
| --- | --- | --- | --- | --- |
| IR3-01 | P2 | The canonical binding-head key had five fields, including `port_contract_version`, while the field-complete extension config nested only four and relied on an ambiguous sibling | `BindingSlotKeyV1` is now one exact closed five-field object plus ADR-008 canonical digest across all eleven configs, binding records/heads, commands/results/events, UI and rollback retention. Config sibling/nested port version, resolved binding and digest must match byte-for-byte; four-field and cross-version forms fail | T087 config/schema roundtrip, hash, coexistence, stale-head and retention tests; T078 UI preservation; R16/V8 |
| IR3-02 | P2 | Generic `artifact_inputs:0..256` left all 52 request operations unconstrained and codec/storage carried competing refs | Extension-ports §3.9 enumerates all 52 operations: nine use exact frozen/model-runner, core ToolDefinition, codec or storage profiles and 43 require `[]`. It fixes count, role, media, selector, byte and sole-ref relationships, removes codec/storage competing refs and gives first-release fetch/browser/multimodal/document tool mappings | T087 generated request-schema/semantic-validator positives and extra/missing/conflicting/frozen/profile negatives; T083 packaged repetition; R16/V8 |

The revision-4 independent review found no P1 but rejected three P2 contradictions. Revision 5
addresses only those findings and preserves every earlier frozen input and verdict:

| ID | Severity | Revision-4 blocker | Revision-5 documentation remediation | Still-open proof owner |
| --- | --- | --- | --- | --- |
| IR4-01 | P2 | Export `prepare`/`transmit` promised exact snapshot transmission but were exact-empty requests, leaving no bounded IPC byte route | Two core profiles require the exact ordered 1–256 `export_payload` bindings of `ExportSnapshotV1`/`PreparedDeliveryV1`; both calls receive those bytes only through T018 digest/chunk/receiver-credit streaming. Refs, shared-store mounts and changed post-preview bytes fail. The all-52 split is 11/41 | T018-foundation bounded stream; T087 generated request/equality/negative tests; T083 clean-host repetition |
| IR4-02 | P2 | Result artifact `role`, `media_type` and `omissions_ref` were generic and codec outputs could contradict target media or omissions | Extension-ports §3.8 closes the operation-role/media/omissions/ref sets, codec target-media/output-omissions equalities and core-owned `ToolArtifactOutputContractV1`/binding shape; all unlisted or contradictory metadata fails | T087 generated schema/semantic validator; R16/OPS-AC11/V8; T083 repetition |
| IR4-03 | P2 | Result and error independently carried effect state and terminal branches admitted unsafe unknown/retry combinations | `result.effect` is the sole truth, error has no duplicate state, and the exhaustive terminal×effect-family tuple table rejects everything unlisted, including succeeded external unknown/unconfirmed and failed unknown/retryable | T087 schema/semantic tuple tests; runtime R16; T083 repetition |

The critical-path rescan also clarified the unchanged T018 task without creating or shrinking a task:
`T018-foundation` is the actual Linux initializer/listener/peer-handshake, bounded artifact stream and
staged sandbox/channel prerequisite; `T018-final` consumes downstream semantic worker/graph/tool and
T081 integration evidence. T083 alone owns the two-clean-host repetition. This removes a circular
reading in which T018 had to be fully closed before the work needed to close it.

The revision-5 independent review found no P1/P3 and rejected one P2 contradiction. Revision 6 is a
narrow correction:

| ID | Severity | Revision-5 blocker | Revision-6 documentation remediation | Still-open proof owner |
| --- | --- | --- | --- | --- |
| IR5-01 | P2 | `result.effect.effect_receipt_ref` was the sole receipt truth, but successful `invoke_tool` output also allowed a nullable receipt with no equality | Successful tool output is exactly `{tool_call_ref,result_ref}`. Any output-level `effect_receipt_ref` or alias is forbidden even when equal; the common effect object remains authoritative and `ToolResultArtifactBindingV1` remains sealed under `result_ref` | T087 generated schema/forbidden-field tests; R16/OPS-AC11/V8; T083 repetition |

The revision-6 independent review found no P1/P3 and rejected one P2 formatting defect. Revision 7
changes no semantic contract:

| ID | Severity | Revision-6 blocker | Revision-7 remediation | Still-open proof owner |
| --- | --- | --- | --- | --- |
| IR6-01 | P2 | Receipt prose split the §3.2 Markdown table, leaving `artifact-codec-port-v1` as an isolated pipe row | Tool and codec rows are consecutive; the unchanged receipt prose follows the completed table. A structural check requires exactly eleven `*-port-v1` rows, each inside a contiguous pipe table whose header is immediately followed by the separator, and rejects prose inserted between rows | T086/r7 static structure check; T087 generator repeats the guard |

The r7 static AWK structure check treats `| Port |` as opening a normative table only when the next
line is its `| --- |` separator, closes the table at the first non-pipe line, and requires every
``| `*-port-v1` |`` row to occur while that table is open. Recorded result:
`port_rows=11 isolated_rows=0`. This is document-structure evidence only, not generated-schema or
runtime qualification.

The audit also caught secondary design hazards while remediation was being written. An
`ExtensionServiceDescriptor` must not contain the manifest digest when the manifest contains its
descriptor digest; the design now uses a one-way manifest→descriptor link and binds both in the
staging request. The built-in Codex managed runner keeps extension kind `provider` but uses
`managed-provider-runner-port-v1`, because its preflight/device-auth/agent-loop event contract is not
a raw provider `model_step` API. Deployment requests/receipts are now a kind-specific closed tagged
union rather than a generic release-shaped payload. Immutable heads have explicit stable keys and
backward-only revision links. Replacement stages a distinct service, qualifies it and then CAS-
supersedes the binding before target-keyed ancestor retirement; current uninstall remains separate. Descriptor-declared dedicated mounts
are distinguished from forbidden product/runtime-created mounts. The conformance fixture uses one
OCI index/descriptor with closed arm64 and amd64 platform entries, each selected exactly by its host.

Supply-chain ownership is also disjoint: T081/T082 lock and attest only DeepTwin core/built-in
images; T087 owns the private conformance-fixture source, two-platform descriptor, SBOM/provenance and
license inventory; arbitrary future operator-supplied descriptors never become core release locks.
ADR-014 adds no T089 core build input, so that historical build-input gate remains closed. T084 still
controls any publication and legal/license closure.

## Gate disposition

T086 is closed for design. Its reviewer used `adr014-review-input-manifest-r7.md` and recorded the
separate `adr014-independent-review-r7.md` without overwriting frozen r1/r2/r3/r4/r5/r6 inputs or
rejected verdicts. It verified at least:

1. the runtime matrix is exhaustive and wrong tuples fail closed;
2. request/receipt kind payloads form a closed tagged union with exactly one precondition truth and without digest cycles;
3. requalification and rollback are reachable without reinstalling verified bytes or reviving stale authority;
   immutable binding history is distinct from retained rollback authority, and exact owner release
   makes strict-ancestor retirement reachable without deleting history;
4. T087 owns lifecycle persistence while T018 owns only broker transport/execution;
5. T087 staged proof does not depend circularly on T081/T083 final distribution;
6. browser authority never expands into executable staging;
7. SDK/client packaging and recursive dependency checks demonstrate a reusable core; and
8. current legal/readiness wording continues to distinguish an open-source target from an approved release;
9. keyed heads, non-destructive replacement and exact mount semantics are unambiguous; and
10. core, private conformance-fixture and arbitrary third-party supply-chain locks cannot be conflated.
11. independent same-port bindings coexist unless all slot-key fields match;
12. four deployment arms, strict-ancestor retirement, preserved current head, target retirement CAS, request↔observation equality and digest order are closed;
13. all 44 port schema artifacts are mechanically author-implementable with exact bounds and no untyped/prose-reused field, without SDK ownership of core contracts;
14. `app/extensions/**` is inside the recursive dependency boundary; and
15. T025's frozen route-composition seam and T087 fixed extension contribution have exact, non-overlapping paths;
16. all 208 operation×candidate-terminal pairs emit exactly 127 allowed branches and reject 81,
    with closed artifact cardinality including cancelled codec `artifacts=[]`; and
17. real bearer parity is portable-HTTPS-only while local HTTP proves pre-parser non-exposure without a real credential.
18. all eleven configs and every binding/command/result/event/retention surface preserve the exact
    five-field `BindingSlotKeyV1` and recomputed digest, rejecting four-field/cross-version forms; and
19. all 52 request operations are covered once by the 11 non-empty-capable/41 exact-empty artifact-
    input matrix, including frozen-list equality, sole-ref rules and explicit core ToolDefinitions.
20. export prepare/transmit receive exact snapshot/prepared `export_payload` bytes over bounded IPC,
    never through refs alone or a shared store;
21. result role/media/omissions/ref sets and codec/tool equalities are field-complete;
22. `result.effect` is the sole truth and every terminal/effect/outcome tuple outside the closed table
    fails, including unsafe unknown/retry combinations; and
23. T018-foundation is the prerequisite, T018-final is a downstream convergence gate, and T083 keeps
    two-clean-host ownership without a dependency cycle.
24. successful tool invocation output is exactly `{tool_call_ref,result_ref}`; output-level effect
    receipt fields/aliases fail and the common effect receipt remains the only truth without changing
    ToolResult artifact bindings.
25. all eleven normative port rows are structurally inside contiguous Markdown tables, with zero
    isolated pipe rows; inserting prose between table rows makes the structure check fail.

The separate `adr014-independent-review-r7.md` verified these items against the exact 35-entry
manifest and accepted revision 7 with P1=0/P2=0. T086 is complete for design. T087, T078, T079,
T081, T083 and T084 remain open regardless of the documentation result.
