# Implementation Plan: DeepTwin web-based open-source multi-agent framework release candidate

**Branch**: `codex/ui-structure` | **Date**: 2026-09-07 | **Spec**: [spec.md](spec.md)

**Input**: `specs/001-autonomous-release/spec.md`. Feature resolver name is
`001-autonomous-release`; it does not rename the actual Git branch.

**Status**: ADR-009–013 established the web-framework/deployment/speech/vault/Codex direction, and a
2026-09-08 adversarial extension-framework audit reopened T086. ADR-014 is the delegated design
remediation for semantic ports, durable lifecycle, operator-staged OCI extension services, browser
management, distributable SDK/client and recursive dependency enforcement. The earlier V0 native
review and the first T086 DESIGN CLEAR remain historical evidence. The first ADR-014 independent
reviews rejected revisions 1–6; revision 7 repaired only the isolated Markdown port-table row and
added an eleven-row structure guard while preserving every revision-6 semantic contract. A fresh
independent review accepted its exact 35-entry manifest with P1=0/P2=0 and closed T086. This is not
a claim of implemented or empirically qualified behavior.

## Summary

Deliver the full independent browser journey: deploy/first setup/input/STT → work understanding → real
lens-informed graph proposals/independent criticism → prepare/run → role-specific original
artifacts/handoffs → own whole/partial alternative → evidence-based DeepTwin inquiry/change
→ previous-queue comparisons and product-only plateau → separate validation → exact human
environment promotion. Optional selective log export is available throughout, not a final step.

Reuse the working Python web app, add immutable typed domain records and application
services, use LangGraph as an orchestration adapter, provider-neutral transports and
DeepTwin-owned isolated browser/document/file workers. Current provider scope is Claude API-only,
Codex subscription through a server-owned managed adapter/runner, with separately selected optional
Codex API. Three browser UI modes share one store, permission boundary, graph and command service.
The shared isolated-worker envelope carries bounded transport facts only. Core-owned semantic port
contracts keep each extension kind substitutable, while externally staged OCI extension services,
durable qualification/binding records and separate extension-author/HTTP-client distributions keep
the reusable framework from collapsing into the bundled control plane or its release image.
The core also owns field-complete per-port config/request/result/error schemas, an exhaustive
52-operation request artifact-input matrix, and one exact five-field `BindingSlotKeyV1`+digest across
config/binding/commands/events; independent same-port capabilities coexist unless that full key matches.

## Product Boundary

The target DeepTwin release is a self-hosted, web-based, open-source multi-agent server framework plus its bundled, supported
browser control plane. The browser UI is the official end-user product surface and first-party
reference client; the reusable core does not make that supported surface optional. Docker Engine/
Desktop, Compose and Portainer are external deployment/operator mechanisms. Native launchers,
DMGs and embedded WebViews are not release artifacts, and internal CLIs/workers are never exposed as
the user journey. Claude runs only through an explicitly connected API. Codex subscription runs
through the instance-owned isolated managed adapter/runner, while Codex API remains a separate
explicit choice. Framework-managed browser/external tools and multi-format artifact workers execute
server-side, with grants, side effects and lineage visible in the browser product. Executable
third-party extensions are operator-staged digest-pinned OCI services connected by exact descriptors
and signed deployment receipts; the product has no Docker socket, runtime downloader, host-path or
post-start/unmanifested mount authority, or container-control method. The external operator may
create only descriptor/request-declared dedicated socket or named-volume mounts during service
staging. Code-free definitions may be bounded-imported in the browser.
`Settings > Extensions` observes qualification and bindings without acquiring deployment authority.
External automation uses the same OpenAPI command/event contract through a separately installable
client, not browser automation or an end-user CLI.
T025 owns `app/services/service_clients.py`, `app/services/service_client_auth.py`,
`app/api/service_clients.py`, durable migration/schema, bearer authentication, authorization/rates,
and the frozen first-party router-composition port in `app/api/router_composition.py` invoked once by
`app/server.py`. T087 owns `app/api/extension_routes.py` plus the fixed
`app/api/route_contributions/extensions-v1.json` descriptor and registers through that seam without
editing server/composition code. Its out-of-process client/server parity suite uses the actual HTTPS
surface; arbitrary operator/user extensions cannot contribute HTTP routes.

## Technical Context

**Language/Version**: Python 3.12 server and non-browser workers; Node.js 24.20.0 LTS for the
isolated browser worker; browser-native JavaScript ES modules for the bundled control plane.
The browser UI is the supported official end-user product/control surface. No embedded WebView,
native desktop launcher, deployment console, developer CLI or internal runner can replace its
user-journey acceptance.

**Primary Dependencies**: existing FastAPI 0.141.1, uvicorn 0.52.4, pydantic 2.13.5,
python-docx 1.2.0; observed LangGraph 1.2.11, checkpoint-sqlite 3.1.1, langchain-core 1.6.2.
Add exact tested Anthropic SDK, Node `playwright-core` 1.63.0 plus paired Chromium headless shell,
safe PDF/image tools, PyNaCl 1.6.2,
argon2-cffi 25.1.0 and the explicitly named PCM-only downstream
`deeptwin-faster-whisper==1.2.1+deeptwin.1` from upstream faster-whisper 1.2.1, plus the pinned
multilingual small model under post-ADR release locks. No runtime package/model download and no
automatic LangSmith/cloud tracing.

**Storage**: existing intake.sqlite3 extended by additive tested migrations; immutable
purpose-partitioned content-addressed objects; separate nonauthoritative checkpoint cursors.
Extension manifest/installation and target-keyed service-retirement histories/heads, qualifications,
slot/selector-keyed binding revisions/heads, target-binding-keyed rollback-retention revisions/heads
and public events use the arm's atomic DB/CAS transaction
and rehydrate/reconcile before dispatch after restart. Separate stage/replace/current-uninstall/
superseded-retirement arms preserve one-way input→request→receipt→postcondition→record/head→
consumption/event order. Retirement of a strict ancestor leaves the descendant current installation
head unchanged. Immutable binding history does not itself retain rollback authority: supersession/
disable creates an exact retained eligibility head, and an owner-only CAS release preserves history
while making ancestor retirement reachable once the other dependency sets are empty.
Both first release profiles use the gateway-owned ADR-012 encrypted-file `CredentialVault`; the
existing host Keychain adapter is development/history evidence, not a release binding. Provider
credentials and backup age identities use separate roots/workers. Plain SQLite is not represented
as encrypted.

**Testing**: pytest; Node test runner plus Playwright actual browser checks; fault injection;
controlled local network fixtures; existing B1–B3 regressions; independently versioned
semantic/effect evals; clean self-hosted deployment/browser/microphone/worker tests; an out-of-tree
OCI tool extension; 44 core-owned per-port schema artifacts, exhaustive 52-operation×terminal/result-
artifact cardinality plus exact role/media/omissions/effect tuples and 52-operation request-artifact
profiles (11 non-empty-capable/41 exact-empty, including export prepare/transmit bounded byte streams),
exact five-field binding-key roundtrip/hash negatives and refinement rejection; recursive
architecture scans including `app/extensions/**`; and a separate-process HTTP client parity test
with no `app` import against mounted T025 bearer-authenticated HTTPS routes plus an HTTP-only
loopback non-secret canary proving the bearer route is absent/denied before bearer parsing. Paid/live calls
require a finite authorized plan; fake transports cannot qualify them.

**Target Platform**: one self-hosted single-node Linux-container topology with two required
deployment profiles: `local-no-terminal-v1` on qualified macOS arm64 Docker Desktop + Portainer CE
UI, and `portable-compose-v1` on qualified Linux x86_64 Docker Engine/Compose with the pinned edge
terminating HTTPS from operator-supplied TLS secrets.
Both clean-host paths and exact browser/runtime versions are recorded. The current macOS development
host is not the product boundary; untested combinations are not claimed.

**Project Type**: self-hostable open-source web framework target with a bundled, supported official
end-user browser control plane that is also the first-party reference implementation, initially
one authorized operator/user per instance, with replaceable runtime/
provider/storage/tool ports and isolated workers. Each port has core-owned versioned semantics;
the generic worker transport is not the SPI. Deployment bootstrap, extension-service staging,
first-user setup and normal browser use are separate.

**Performance Goals**: on the declared test hardware with 20-node/40-edge graphs and
1000-event view pages, browser command acknowledgment p95 <500 ms excluding model/file parsing;
core event visible p95 <1 second after commit; no typing/graph selection main-thread stall
>200 ms in the measured interaction test. These are engineering acceptance targets, not
measured results. STT provisional updates target p95 <2 seconds and finalization <3 seconds
for the bounded Korean speech fixture; disclose measured hardware/engine limits and do not
equate these targets with recognition accuracy.

**Constraints**: no automatic provider/billing fallback, broad user filesystem access,
unrecorded external effects, raw private stream export, expert-alternative/H_phi leakage,
automatic operational promotion, end-user CLI, product-side executable extension installation,
generic-schema-as-semantic-port or synthetic-result-as-live substitution.
All model/tool/loop budgets finite. Security and mandatory correctness are not traded for speed.

**Scale/Scope**: one authorized human on the first single-instance profile; up to 20 nodes,
40 edges, 2 parallel model steps
by default, 1000 paginated event rows, 10 MiB initial source-file limit. Larger workspaces use
pagination/lazy artifact reads and explicit compatible limits, not silent truncation.
A declared first test workload can be bounded without omitting any US1–US7 stage.

## Constitution Check

Pre-research check: no proposed exception to constitution v3.0.1.
The original post-design check was recorded as clear, but ADR-014's audit found that the reusable
extension boundary was underspecified and reopens T086. The amended design proposes no
constitutional exception: semantic ports remain in the core, the browser is still the official
product, and external deployment authority stages executable services. A new independent review
must confirm the amended source/task mappings before T086 closes. Completed transport-neutral work
and T089's exact build-input locks remain evidence for their scopes. ADR-014 adds no core release
build input, so T089 stays closed. T081 creates only final DeepTwin core/built-in service image locks;
T087 owns a separately locked private out-of-tree conformance-fixture OCI descriptor/source/SBOM/
provenance set, and arbitrary future operator-supplied third-party descriptors never enter the core
release lock.

| Principle | Design enforcement | Release evidence gate |
| --- | --- | --- |
| I intent/evidence | spec + source-traceability + latest ADR-009–014 supersession/decisions | reopened V1/T086 and SC-002 |
| II open web product | browser experience/API/deployment/semantic-extension contracts, common ViewContext | UX-AC01/02/11, web deployment and external-client acceptance |
| III real graph/tools/models | runtime compiler/dispatcher/artifact lineage and semantic extension ports | R01–R16, V3/V4/V8 |
| IV providers/billing | Claude API-only, Codex explicit modes, CredentialVault/CredentialRootPort | P01–P15, no fallback |
| V own alternatives | exact original/selectors, purpose partitions | G-01/02/05, UX-AC05/07 |
| VI lenses/critics | atomic source definitions, isolated critique, heldout qualification | B4/C, V3/V6 |
| VII product growth/human | growth-v1 fixed series/patience, typed approval/CAS | G-06–G-15, V5 |
| VIII logs/export | OPS event registry, manual core retention, optional export | OPS-AC04–AC09 |
| IX honest/non-destructive | evidence ledger, separate fixture/live/human claims | all reports + final release matrix |

Skills are execution aids, not independent product requirements. Use Superpowers design/
planning/review/TDD practices alongside Spec Kit's canonical requirements/contracts/tasks.
LangChain Skills inform relevant runtime modules; eval-engineering governs concrete Tasks
and verifier/harness isolation. PDF and visual QA skills apply when creating actual artifacts/
screens. A skill's routine interview/commit/cloud-tracing defaults never override the user's
delegated choices, no-publication boundary or self-hosted web design.

## Project Structure

### Documentation (this feature)

```text
specs/001-autonomous-release/
├── spec.md
├── plan.md
├── decisions.md
├── progress.md
├── research.md
├── provider-research.md
├── packaging-research.md
├── sandbox-research.md
├── source-traceability.md
├── data-model.md
├── quickstart.md
├── checklists/requirements.md
├── contracts/{experience,runtime,extension-ports,api,growth,operations,verification}.md
├── tasks.md
└── evidence/{design-review,web-framework-design-review,extension-framework-design-remediation,
              adr014-review-input-manifest,adr014-review-input-manifest-r2,
              adr014-review-input-manifest-r3,adr014-independent-review-r3,
              adr014-review-input-manifest-r4,adr014-independent-review-r4,
              adr014-review-input-manifest-r5,adr014-independent-review-r5,
              adr014-review-input-manifest-r6,adr014-independent-review-r6,
              adr014-review-input-manifest-r7,adr014-independent-review-r7,
              implementation,release-report}.md
```

### Source Code (repository root)

```text
app/
├── server.py, storage.py, ingestion.py                 # retained integration
├── codex_*.py, critic_*.py, generation_profiles.py     # preserve B1 contracts
├── domain/{refs,schemas,events,permissions}.py
├── services/{conversation,design,design_review,environments,runs,artifacts,alternatives,inquiry,growth,promotion}.py
├── services/{provider_connections,credential_client,service_clients,service_client_auth,deployment_control}.py
├── runtime/{graph,ledger,budgets,gateway,provider_transport,worker_coordinator,tools,memory,compiler}.py
├── adapters/{claude_api,codex_step,codex_api,keychain,browser,documents}.py
├── operations/{setup,deployment_control,extension_deployment,backup,export,retention,recovery,updates}.py
├── workers/{broker,provider_gateway,credential_vault,credential_root,public_fetch}.py
├── workers/{browser,speech,documents,evaluation,runtime_extension,codex_runner,backup_crypto}.py
├── extensions/{contracts,ports,registry,persistence,runner}.py
├── api/{routes,views,commands,session,service_clients,codex_routes,speech_routes,extension_routes,router_composition}.py
├── api/route_contributions/extensions-v1.json
├── static/{app,chat,workspace,graph,artifacts,alternatives,experiments,settings,extensions}.mjs
├── static/{styles.css,index.html,speech-input.mjs,...}
└── tests/{test_service_clients,test_service_client_routes,test_router_composition,
           test_extension_route_registration,test_extension_architecture,
           test_extension_client_blackbox,test_*.py,browser-*.test.mjs,fixtures/}
deploy/
├── compose.yaml, env.example, healthcheck
├── bootstrap/index.html, portainer/stack-template.json
├── locks/, manifests/, extensions/, sbom/, migrations/
├── images/{edge,control-plane,provider-gateway,fetch-broker,browser-worker,document-worker}/
├── images/{speech-worker,evaluation-worker,runtime-extension-worker,codex-runner,backup-crypto}/
├── jobs/{vault-init,vault-maintenance,session-root-init,session-root-maintenance,backup-key-init,deployment-receipt-root-init,deployment-receipt-job}/
├── security/{browser-seccomp.json,service-ids.json}
└── tests/
schemas/v1/extensions/{ports/<port>/{config,request,result,error},deployment}/ # core-owned extension schemas
schemas/                                              # all other exported versioned JSON schema
sdk/python/deeptwin_ext/{pyproject.toml,src/,tests/}   # independently installable author SDK
sdk/python/deeptwin_client/{pyproject.toml,src/,tests/} # independently installable HTTP/OpenAPI client
examples/extensions/                                 # inert, least-privilege extension examples
evals/deeptwin/                                        # existing Task/Harbor/effect assets
docs/lenses/                                          # existing source-based lens library
docs/release/                                         # deploy/support/security/licenses
control-prototype/                                    # reference fixture, not product runtime
```

**Structure Decision**: `domain/`, `services/`, `runtime/`, `operations/` and `extensions/` form the
reusable framework core; `api/` and `static/` are the bundled web control plane.
The core must not import presentation modules or web presentation frameworks directly; recursive
architecture enforcement starts at each of those five roots, including every nested
`app/extensions/**` package and transitive import edge. “Reference implementation” describes the reusable
core boundary; it does not make the official browser product optional. Modularize added work inside the existing app,
keeping compatibility adapters for working services. Do not rewrite unrelated dirty prototype files. Every parallel
agent gets disjoint module ownership; root integrates server/static/schema boundaries.
The paths are intended implementation destinations, not claims that these files already exist.

## Ordered delivery and validation

1. Close all-design contracts, source/acceptance matrix, dependency-ordered tasks and independent
   consistency review. ADR-014 reopens this gate until semantic extension ports, durable lifecycle,
   staging/distribution, browser management, client packaging and recursive architecture checks are
   independently reviewed. Resolve high-impact contradictions before dependent work claims closure.
2. Foundation: baseline regressions, post-web exact dependency/model lock, typed refs/events/CAS,
   authenticated web commands, transactional budgets/leases, purpose firewall and **T018-foundation**:
   actual Linux IPC initializers/listeners/peer handshake, bounded artifact chunk/credit stream and
   externally staged sandbox/channel enforcement. This bounded foundation is the prerequisite for
   T087/T090/T024/T043/T044/T070 runtime integration; it is not the full T018 checkbox.
3. US1 provider/first-use: Claude API key/catalog, Codex separate modes, per-role choices,
   same-space intake/understanding, browser-captured STT and web first-user setup.
4. US2 real graph generation/criticism/selection: preserve B1, implement B4 then bounded
   qualification; atomic lens decisions and graph compiler, diverse validated candidates.
5. US3 execution/tools/artifacts: real graph scheduling and owned tool model-step loop,
   multi-format complete handoffs, controls and interruption/restart.
6. US4–US6 DeepTwin: exact whole/partial own alternatives, competing hypotheses and eligible
   SPLI, evidence-only change compilation, related prior-queue comparisons, plateau/heldout/
   human exact-version promotion and rollback.
7. US7 operations: complete deployment-to-growth events, safe preview/redaction/export, retention,
   backup/restore/update. Foundational logging exists before earlier stages; export UI is later.
8. End-to-end failure/security/semantic/effect qualification, out-of-tree extension and external
   client parity, reproducible web distribution and fresh-deployment evidence, release documentation
   and honest remaining-readiness report. **T018-final** closes the unchanged T018 checkbox only after
   the downstream tasks have connected their semantic workers/graph/artifact paths to the foundation
   and the integrated isolation gates pass. It is therefore a downstream convergence gate, not a
   circular prerequisite for implementing those workers. T083 retains the two-clean-host repetition.

US phases are independently testable through controlled fixture boundaries, not independently
complete products. Follow each story's assigned integration tests and qualify each actual
boundary; label all fixture substitutes and do not count them as real integration. No scope reduction
to onboarding-only MVP. User-requested finish means all mandatory stories, not a prototype.

Before each implementation item write the behavior test, observe its relevant failure, make
the minimal change, rerun focused tests and integrate regressions. Then separate specification
review from quality/security/UI review. Do not commit/push/publish just because a skill suggests
it. Existing user changes remain unowned.

## Risk register and authority checkpoints

| Risk | Chosen handling | Evidence required before support claim |
| --- | --- | --- |
| Browser network/data escape | networkless non-root Chromium worker, active sandbox/pinned seccomp, bounded UDS IPC and mediated fetch | positive sandbox assertion plus direct/redirect/DNS/WS/service-worker forbidden sink receipts 0 |
| Web session/remote exposure | offline-generated one-use verifier exchange, trusted-host/origin/proxy checks, CSRF, secure cookies and TLS boundary | both ADR-010 clean deployments; no unauthenticated domain mutation |
| Codex model-step/multimodal | version-qualified environmentless bridge, explicit structured tool loop | R04/05/06, P13/P15 |
| API usage | explicit user credential/connection + finite product budget; separately authorized development live plan | actual provider tests and usage ledger, no invented spend |
| Crash across DB/object/checkpoint | write-ahead intent, CAS+idempotent replay, unknown-outcome hold | R07/08/10, migration/backup tests |
| Critic shared judgment errors | source reconstruction + independent validity/response + prespecified qualification | V3 IndependenceProfile and honest heldout statistics |
| Lens/DeepTwin empirical effect | source fidelity separate from controlled effectiveness | V5/V6, real evidence not synthetic-user substitute |
| Web distribution/microphone | ADR-010 two-profile distribution plus AudioWorklet PCM and pinned local `deeptwin-faster-whisper` worker | both clean deployments, supported-browser/origin permission, Korean latency/edit/accuracy-limit evidence |
| Supply chain/clean-host/human evidence | versioned source/image artifacts, checksums, SBOM/provenance and independent clean-host checks | no unverified artifact portrayed as a qualified release |
| Extension system collapses into core/UI image | closed semantic port matrix, durable installation/qualification/binding, operator-staged OCI service receipt, browser observability, out-of-tree tool and separate-process client proof | no generic envelope or core rebuild portrayed as a reusable extension framework |

The development goal remains active while meaningful safe work exists. Product patience does
not stop this plan. User feedback arriving during work can supersede prior decisions; update
affected documents/tasks/evidence, not the entire scope blindly.

## Complexity Tracking

No approved constitutional exceptions. Separate ledger/checkpoint, provider/tool mediation,
purpose partitions and artifact projections are necessary for concrete privacy/replay/approval
requirements, not extra standalone services. If a simpler implementation preserves all contracts,
choose it under delegation and record the affected tests/decision.
