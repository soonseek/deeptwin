# V1 web-framework design review — historical result, ADR-014 reopening and r7 reclosure

2026-09-08 · Status: **HISTORICAL FIRST DESIGN CLEAR; T086 RECLOSED BY INDEPENDENT ADR-014 R7 REVIEW**.

Sections 1–6 preserve the first constitution v3.0.1/ADR-009–012 review in its historical context.
That result no longer closes the current architecture gate: the later extension-framework audit and
ADR-014 reopened T086. This record does not claim implementation, release qualification, measured
DeepTwin effect, OSI-license approval, publication or creator acceptance. Those remain separate
tasks and evidence gates.

## 1. Product identity and authority

The target DeepTwin release is a self-hostable open-source **web framework** with an official browser control plane.
The current repository has no license and is not yet legally an open-source release.
Its reusable server-side core owns graph compilation and execution, evidence, authority, budgets,
events, evaluation and the DeepTwin growth loop. The browser control plane is the default product
experience for non-developers and uses the same versioned command/event contracts available to
supported extensions. DeepTwin is not a native desktop application, a thin provider wrapper, a
fixed workflow, a hosted-only dashboard or a command-line product.

The active boundary has four parts:

1. a transport-neutral framework core;
2. the bundled browser control plane;
3. isolated framework-owned workers plus a versioned extension SPI; and
4. reproducible self-hosted deployment, followed by a separate first-owner browser setup.

Portainer CE and Docker/Compose are external deployment/operator authorities. They may install or
operate the stack, but they are not DeepTwin's product UI, launcher or runtime control plane. The
product never receives a Docker socket, Portainer credentials or equivalent host-container power.

## 2. Resolved findings

| ID | Severity | Finding resolved by the active design | Resolution |
| --- | --- | --- | --- |
| W01 | Critical | V0 selected a macOS native launcher, App Sandbox and XPC boundary | V0 is marked historical; ADR-009 and this V1 web-framework gate supersede it |
| W02 | Critical | “Web app” could collapse the reusable framework into one UI | Constitution II, FR-001/032 and the plan split core, browser control plane, workers/extensions and deployment |
| W03 | Critical | A generic “installer/launcher” obscured the self-hosted web journey | Both profiles use a common deployment helper only; first-owner setup and all product work happen in the browser |
| W04 | Critical | One image tag could silently identify different service bytes | Every service is locked by platform-specific manifest/image digest; tags are display-only and the exact source commit plus Compose digest are recorded |
| W05 | Critical | Local and portable origins left session and CSRF semantics ambiguous | One canonical OriginProfile, exact URL normalization, host-only or `__Host-` cookie rules and an exact HMAC CSRF contract now cover both profiles |
| W06 | Critical | Deployment mutation lacked an authenticated, replay-safe authority boundary | Immutable requests, physically separated signing/verification roots, signed receipts, lifecycle CAS and receipt-consumption recovery are specified |
| W07 | High | Provider status/catalog reads might accidentally touch secrets or make network calls | They are persisted redacted snapshots with zero vault, gateway, provider, refresh or network effect |
| W08 | High | Secret create/rotate/revoke could combine unrelated connection/runtime effects | Strict bounded ingress, intent-to-vault CAS and non-dispatchable retirement/cleanup states isolate mutation; connection checks and catalog refresh are separate commands |
| W09 | High | Local credential deletion could be misrepresented as external revocation | Local erasure and its exclusions are explicit; provider-side revocation is never implied |
| W10 | High | Browser speech had no deterministic offline worker contract | Exact PCM conversion plus separately identified downstream engine construction/transcribe parameters, rejected decode/VAD/download paths, chunk/tail rules, edit fence, digest validation, networkless execution and ephemeral-only retention are fixed |
| W11 | High | Codex subscription use risked making Codex the product host | It is a built-in managed-provider runner reached through the web framework; official device authentication is isolated and API mode remains an explicit alternative |
| W12 | High | Agent tool use and non-text artifacts lacked an enforceable service boundary | Browser/document/speech/evaluation workers are isolated, artifacts stream through authenticated bounded UDS, and provenance remains in the framework core |
| W13 | High | Initial owner setup, maintenance and recovery authority could be conflated | One-use bootstrap delivery, initial genesis, authenticated maintenance and receipt-gated recovery/update are distinct contracts |
| W14 | High | Task order could package an onboarding subset as a full release | T086→T089 build-input closure→T018/T025/T087 is explicit; T090, story integration and effect gates precede T081 final image locks, then T082 provenance, T079 security and T083 clean-host proof |
| W15 | Medium | New terminology risked replacing the user's simple browser journey | The primary journey remains: describe/upload/speak → compare graph proposals → run/observe artifacts → provide own alternative → evaluate/reevaluate → human promotion |

## 3. Deployment profiles fixed by the design

### `local-no-terminal-v1`

- macOS arm64, Docker Desktop and Portainer CE GUI;
- immutable source reference and service image locks;
- lowercase 128-bit instance ID and unpredictable path on the exact `.localhost` origin;
- browser-first owner setup with no DeepTwin CLI requirement;
- host-only HttpOnly session cookie and exact-origin CSRF enforcement.

### `portable-compose-v1`

- Linux amd64, Docker Engine/Compose and a release-pinned `edge` service;
- dedicated hostname and operator-supplied TLS Docker secrets;
- HTTPS terminated by the locked edge service, with no implicit ACME or unspecified proxy;
- `/` base path required by the `__Host-deeptwin_session` cookie;
- the same core/API/event contracts and source/Compose/service digest identity as the local profile.

The common browser deployment helper validates and emits the canonical OriginProfile. It is not a
DeepTwin launcher and does not become a second product surface. If Portainer CE cannot apply the
locked source, security options or Chromium seccomp profile entirely through the declared
no-terminal path, the local profile and release are blocked; a CLI/manual-host workaround does not
count as qualification.

## 4. Cross-artifact consistency result

The following active artifacts agree on the product identity, authority boundaries, two deployment
profiles, provider/vault behavior, offline speech, managed Codex runner, worker isolation, artifact
transport and dependency order:

- constitution v3.0.1;
- `spec.md`, `plan.md`, `research.md`, `decisions.md`, `data-model.md` and `quickstart.md`;
- experience, growth, verification, runtime, API and operations contracts;
- `tasks.md` and `source-traceability.md`.

Original non-destructive review results:

- Spec Kit prerequisite and artifact discovery: pass;
- task IDs: 90 present, 90 unique; 22 complete and 68 open before closing T086;
- functional requirements: FR-001–034 all mapped to work;
- success criteria: SC-001–010 all mapped to work;
- independent deployment/authority review: CLEAR, excluding this ledger and final hashes;
- independent provider/extension review: CLEAR, excluding this ledger and final hashes;
- independent speech/vault/auth review: DESIGN CLEAR, excluding this ledger and final hashes.

At that first review point, no unresolved material contradiction had been reported in its narrower
design scope. ADR-014 later disproved that as a current closure claim. Historical native experiments
remain labeled as history and contribute no web-release evidence.

## 5. Gates intentionally still open

T086 does not close any of the following:

- T089 exact Linux arm64+amd64 build-input closure was open at this review point and is now
  represented by the current locked aggregate; this T086 review does not itself attest that lock;
- T081/T082 final DeepTwin service-image locks and their build-input provenance linkage;
- T018/T025/T087/T088/T090 implementation and qualification of workers, authority, extension and
  provider transport boundaries;
- US1–US7 production implementation and complete journey integration;
- real provider, browser-tool, document/PDF/image and multi-agent artifact execution evidence;
- semantic effect, independent critic-error, old-queue reevaluation and plateau behavior evidence;
- clean-host Portainer/Compose deployment, backup/recovery/update and supply-chain qualification;
- accessibility/usability testing and the creator's final subjective acceptance;
- copyright-owner selection of an OSI-approved repository license, publication or external signing.

In particular, the portable edge and receipt jobs are specified but not yet built or tested, and
Portainer CE support for the complete immutable source/security/seccomp combination is an empirical
release risk. These are open implementation gates rather than hidden design assumptions.

## 6. Gate disposition

This was the first review's disposition: T086 could be marked complete after its final hash and
mechanical checks. It is preserved only to explain the historical checkbox transition. The later
ADR-014 audit is exactly the kind of identity/authority-boundary discovery that reopens the gate, so
this paragraph no longer authorizes current closure.

## 7. ADR-014 post-review audit and current disposition

The adversarial extension-framework audit found six P1/P2 design gaps in the first review:

1. the generic isolated-worker envelope was treated as if it supplied per-kind semantic SPI rules;
2. artifact installation, qualification and binding were conflated, preventing durable requalification and safe rollback;
3. executable extension discovery had no external, digest-pinned operator staging/receipt contract;
4. the official browser client had no `Settings > Extensions` observability/control contract;
5. source-tree helpers and an in-process client were presented instead of two installable packages and actual separate-process server parity;
6. dependency enforcement was shallow and did not recursively exclude API/static/server or direct FastAPI/Starlette/Jinja presentation coupling.

ADR-014 and [the remediation ledger](extension-framework-design-remediation.md) amend the canonical
spec, plan, data model, runtime/API/operations/experience/verification contracts, task DAG and source
trace. They also close secondary specification hazards: a kind-specific deployment request/receipt
tagged union; an acyclic manifest→service-descriptor digest direction; a distinct managed-provider-
runner semantic port; keyed immutable installation/qualification/binding/rollback-retention heads;
an explicit owner release that preserves history while removing rollback authority; non-destructive
replacement ordering; exact operator-created dedicated mount semantics; and separated core,
conformance-fixture and arbitrary third-party supply-chain locks.

Current gate result: **OPEN**. T086 remains unchecked until a fresh independent reviewer examines
the manifest-frozen amended artifacts and records `adr014-independent-review.md` with no P1/P2
identity or architecture contradiction. This historical review file is an input, not the new
verdict. No tests or
runtime effects were executed by this documentation remediation. T084 separately blocks any legal
open-source/publication claim until the copyright owner explicitly approves a repository license.

## Revision-2 supersession note

The first independent review requested above subsequently rejected ADR-014 revision 1 with five
P1/P2 blockers (IR-01–05). This historical file and the frozen revision-1 manifest remain evidence of
that sequence; they are not edited into a clear verdict. The corrected review input is frozen in
`adr014-review-input-manifest-r2.md`, and only a new independent
`adr014-independent-review-r2.md` with no P1/P2 contradiction may close T086.

## Revision-3 supersession note

The revision-2 independent review also rejected the design on reachable superseded-service
retirement, operation-terminal artifact cardinality, route-composition ownership and HTTP-loopback
client boundaries. Revision-3 rescan then found that immutable binding history still lacked a
separate rollback-retention release transition; the canonical input now includes that exact state,
owner command/event/UI and A→B→release→retire test. Those verdict/input bytes remain historical. The corrected canonical input is
frozen separately in `adr014-review-input-manifest-r3.md`; only a new independent
`adr014-independent-review-r3.md` with no P1/P2 contradiction may close T086. This file does not
self-approve that result.

## Revision-4 supersession note

The revision-3 review subsequently rejected two P2 inconsistencies: the nested extension config key
omitted `port_contract_version`, and the generic request `artifact_inputs` array left all 52
operations unconstrained. Revision 4 uses one exact five-field `BindingSlotKeyV1`+digest everywhere
and enumerates all 52 request operations into nine core-owned non-empty-capable profiles and 43 exact-
empty profiles, including sole-ref and first-release fetch/browser/multimodal/document rules. The
corrected canonical bytes are frozen in `adr014-review-input-manifest-r4.md`; only a separate
`adr014-independent-review-r4.md` with no P1/P2 contradiction may close T086. Earlier manifests and
review outcomes remain history, and this historical review file does not self-approve revision 4.

## Revision-5 supersession note

The revision-4 independent review found no P1 but rejected three P2 contradictions: export-sink had
no byte-bearing request path, result artifact metadata was not field-complete, and result/error effect
states could disagree under unsafe terminal tuples. Revision 5 assigns export prepare/transmit exact
snapshot/prepared 1–256 `export_payload` lists over T018 bounded streaming, closes operation-specific
role/media/omissions/ref equalities, and makes `result.effect` the sole truth under an exhaustive
terminal×effect-family table. The request split is now 11 non-empty-capable/41 exact-empty. It also
clarifies T018-foundation as the IPC/stream/sandbox prerequisite and T018-final as the convergence
gate after downstream semantic integration, while T083 retains two-clean-host proof. Corrected bytes
are frozen only in `adr014-review-input-manifest-r5.md`; a separate
`adr014-independent-review-r5.md` with no P1/P2 contradiction is required to close T086. r1–r4
inputs/verdicts remain immutable history, and this historical review does not self-approve revision 5.

## Revision-6 supersession note

The revision-5 independent review found no P1/P3 and rejected one P2 contradiction: the common effect
receipt was declared sole truth while successful `invoke_tool` output allowed a second nullable
receipt. Revision 6 removes that output field, fixes invoke success to exactly
`{tool_call_ref,result_ref}`, rejects the removed field and aliases even when values match, and keeps
`ToolResultArtifactBindingV1` under `result_ref`. All r5 matrices, lifecycle, T018 DAG and legal
boundaries are unchanged. Corrected bytes are frozen only in
`adr014-review-input-manifest-r6.md`; a separate `adr014-independent-review-r6.md` with no P1/P2
contradiction is required to close T086. r1–r5 inputs/verdicts remain immutable history, and this
historical review does not self-approve revision 6.

## Revision-7 supersession note

The revision-6 independent review found no P1/P3 and rejected one P2 formatting defect: receipt
prose interrupted the §3.2 Markdown table, isolating the artifact-codec row. Revision 7 moves the
unchanged prose below the consecutive tool/codec rows and adds a structural guard requiring all
eleven port rows to remain in contiguous header/separator tables with zero isolated pipe rows. No
operation, schema, profile, effect, lifecycle, DAG or count changes. Corrected bytes are frozen only
in `adr014-review-input-manifest-r7.md`; a separate `adr014-independent-review-r7.md` with no P1/P2
contradiction is required to close T086. r1–r6 inputs/verdicts remain immutable history, and this
historical review does not self-approve revision 7.

## Revision-7 independent disposition

The separate `adr014-independent-review-r7.md` subsequently verified the exact 35-entry frozen
manifest twice, found eleven valid port rows and zero isolated rows, and returned **ACCEPT** with
P1=0, P2=0 and one nonblocking historical-wording P3. T086 is therefore closed for design. This
paragraph and the corresponding task/checklist/progress changes are post-verdict bookkeeping, not a
change to the accepted semantic inputs. T018/T025/T087, implementation, release, effect, license and
human-acceptance gates remain open.
