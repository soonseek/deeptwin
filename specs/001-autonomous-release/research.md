# Architecture decisions and research

2026-09-08 · Design decisions amended by the user's web-framework identity correction through
ADR-009–012 and the delegated ADR-014 extension-framework remediation, not implementation evidence.
Current provider scope: Claude API-only; Codex subscription plus explicit optional API.

## R1. Keep the working product, separate its layers

Retain Python 3.12 for the core/non-browser services, FastAPI/Starlette, SQLite and the existing
local web frontend. The isolated browser worker uses Node.js 24.20.0 LTS with dependency-free
`playwright-core` 1.63.0 because the matching Python package is not published; this does not move
graph, permission, artifact or approval authority out of the Python framework core. The
working first-use modules own real intake and revisions; the control prototype is a visual
reference and test fixture, not an executable runtime. Integrate its useful interaction
patterns into `app/static`, replacing synthetic data with typed read models. Do not make
two competing product databases, independent chat histories or separately deployed modes.

The architecture is a self-hosted modular web monolith with owned worker processes: web UI/API,
application services, domain contracts, ledger/object store, scheduler, provider ports,
tool workers, evaluation workers. The initial scale scope is one instance without requiring
Redis or a cloud control plane, while deployment/bootstrap, first-owner setup and browser use
remain separate. A native macOS window or provider UI is not a product surface.

Alternatives rejected: rewriting the tested first-use path in a new JS stack; shipping the
synthetic graph as the runtime; using Claude Code/Codex UI as the user's product.

## R2. LangGraph for orchestration, DeepTwin for authority

Use a compiled LangGraph `StateGraph` adapter for approved node/edge execution, finite
branching/joins and persisted interruption. Do not install Deep Agents as a second planner
or use a free-form agent to silently redesign the approved graph during a run. The paper
§6.1 explicitly permits LangGraph and restricts replay to externalized node/task boundaries.

LangGraph's graph API supports state, nodes, conditional edges and parallel supersteps.
Compilation is not DeepTwin's authorization, artifact-contract or semantic verifier; these
must run before and during dispatch. Private state channels are not a security boundary
for streaming, so the GUI consumes DeepTwin's allowlisted events, never raw graph state.
[Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)

Persist opaque immutable refs and scheduling cursors in a single-instance SQLite checkpointer;
the DeepTwin ledger remains the authority for attempts, budgets, tool effects and approvals.
Official docs position SQLite for lightweight/local uses and Postgres for production
services. Our bounded single-instance deployment therefore needs explicit crash,
concurrency and recovery qualification; this is not a claim of distributed production
readiness. Never substitute an in-memory checkpointer in the installed product.
[Checkpointers](https://docs.langchain.com/oss/python/langgraph/checkpointers)

Interrupted nodes restart from their beginning on resume. Store the approval challenge
before interrupting and perform no irreversible effect before the resumed approval is
validated. Ledger idempotency guards remain mandatory even with a checkpointer. Use stable
thread IDs and interrupt-ID-bound decisions, not an arbitrary new input that simulates
approval. [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)

Checkpoint/ledger commits are not one atomic distributed transaction. A scheduling cursor
may lag a committed result; repeat visits return that exact ledger result without a second
provider/tool dispatch. An effect with unknown outcome is quarantined, never automatically
retried. Checkpoints can only be rebuilt from verified state; no hidden model reasoning rewind.

## R3. Provider-neutral model step and owned tools

See [provider research](provider-research.md) for current official references and P01–P15.
Claude uses the official direct API SDK, Models API and client-tool messages. Codex subscription
uses the documented non-interactive CLI path (`codex login --device-auth` plus version-qualified
`codex exec --json`) in a distinct managed-provider runner. That command is an agent loop, not a raw
provider-neutral model-step endpoint: DeepTwin therefore controls the outer graph, projected input
workspace, exact model, sandbox/approval policy, explicit framework-tool bridge, budgets, artifacts
and lifecycle, but does not claim to replace or observe Codex's internal reasoning loop. The runner
uses a dedicated `CODEX_HOME`, ignores ambient user configuration/rules, receives no user's normal
workspace, hooks, skills or MCP configuration, and emits only bounded normalized JSONL/results.

The App Server command, including its default stdio transport, is documented as experimental and
unsupported for production workloads. It may be qualified later as an explicitly labelled preview
for richer catalog/event UI; it is not the first-release execution dependency and cannot be used to
claim production model-step parity. Existing environmentless text understanding also does not
qualify the managed execution profile. Original B1 prepared-input and critic parser contracts remain
unchanged, and tool-free critic profiles stay tool-free.

Optional Codex API is a separate explicit official OpenAI API transport with application-owned
configuration/credentials, catalog binding and billing consent; it must not mutate or reuse the
subscription runner's auth directory. Do not implement token reuse or an undocumented ChatGPT
endpoint. The selected mode is recorded before live qualification, with no user-visible automatic
provider/mode fallback.

## R4. Instance truth, immutable evidence and purpose partitions

The paper §6.2–6.3 supports SQLite transitions and content-addressed large objects. Extend
the existing store by additive migrations, preserve input/revision IDs, and register
existing bytes as immutable objects without overwriting old records. Markdown/YAML exports
are read/review/import artifacts, never a second concurrently writable canonical store.

Separate operational, diagnosis, inquiry-audit, development-evaluation and sealed-evaluation
purposes with purpose-checked refs. A hash proves neither truth, possession nor permission.
Raw credentials never enter these stores. No user-wide philosophy profile is constructed.
Ordinary SQLite is not encrypted storage; host/operator compromise remains a stated
threat limitation. See [operations](contracts/operations.md) for retention and backup.

## R5. Bounded real tools, not unrestricted host execution

The first tool suite covers controlled browser navigation/extraction/screenshot, immutable
file reads, structured document/table/image/PDF creation, and their safe previews. Agents
can combine these over real graphs. A typed registration interface permits new tools, but
arbitrary shell/Python from model output, ambient desktop automation and unreviewed plugins
are not silently enabled. Each new capability needs a manifest, permissions, artifact
contract and tests. This implements broad extensibility without claiming every tool exists.

Use a DeepTwin-owned Node Playwright Chromium headless-shell profile in an isolated worker, never the user's
DeepTwin UI browser or normal browser cookies. Restrict egress, methods, redirects, downloads
and origins through an authenticated broker. The former macOS App Sandbox/XPC design in
[sandbox research](sandbox-research.md) is historical after ADR-009; it does not qualify the
web worker. No direct browser network/proxy exception. Isolate renderers from product
credentials/data, disable active document content, preserve raw files separately. Browser
request routing alone is not a proof against DNS rebinding or all browser network paths;
the controlled egress broker and its bypass tests are part of release qualification.
See [runtime](contracts/runtime.md). The earlier [packaging research](packaging-research.md) is
ADR-009-before history; only general checksum/license/reproducibility lessons remain applicable,
not its native bundle, launcher or XPC choices.

PDF: safe structured layout generation with reportlab, bounded pypdf extraction and
PDFium rendering. DOCX: python-docx extraction/generation, a semantic HTML preview marked
as derived, not claimed identical Word pagination. CSV/JSON: data-preserving table views,
never formula execution. PNG/JPEG: bounded Pillow decoding; SVG: reject active content and
render in an isolated converter, never mount uploaded SVG in the privileged DOM. Complex
office conversion can be an additional reviewed adapter, not an undeclared prerequisite.

## R6. Open-source web distribution and accessibility

The target DeepTwin release is a self-hostable open-source web framework. The browser UI is the product surface;
an embedded WebView, `.app`, DMG or native launcher is not required. ADR-010 selects one Linux-
container topology and two release profiles. `local-no-terminal-v1` uses Docker Desktop plus the
existing Portainer CE Docker Desktop Extension as an external authenticated operator UI on
qualified macOS arm64; `portable-compose-v1` uses Docker Engine/Compose on qualified Linux x86_64
with a release-pinned edge terminating HTTPS from operator-provided certificate/key Docker secrets.
The initial portable profile has no implicit ACME or unqualified external proxy dependency. Both use the same immutable source commit, exact Compose digest and
service-keyed image-lock set; each lock has its own OCI multi-architecture index and verifies the
host's distinct pinned platform manifest/config/layers.
Portainer can deploy a stack from a web editor/upload/Git source, but its Docker-level authority is
a host trust boundary, not a DeepTwin plugin. A failed GUI path cannot be relabelled successful by
having the ordinary user run Compose commands.
That general stack-source capability is **not** evidence that Portainer CE's single-file/UI path can
materialize and apply DeepTwin's pinned Chromium seccomp JSON. No current repository artifact or
clean-host result proves that delivery without a host-file edit, CLI command or Business-only
relative-path feature. ADR-010 therefore leaves `local-no-terminal-v1` and the release blocked at
T081 unless a qualified no-terminal artifact/template mechanism is demonstrated.
[Docker Compose production](https://docs.docker.com/compose/how-tos/production/)
[Portainer stack deployment](https://docs.portainer.io/sts/user/docker/stacks/add)
[Docker extension security model](https://docs.docker.com/extensions/extensions-sdk/architecture/security/)

The product process never mounts the Docker socket. It inspects/creates digest-bound deployment
requests and receipts through `DeploymentControlPort`; the operator surface performs image,
container, volume and TLS effects. Networkless non-root browser/document/speech workers communicate
over authenticated Unix sockets. Chromium additionally needs a verified user-namespace sandbox,
release-pinned seccomp allowance, init, bounded shared memory and resource limits; `--no-sandbox`,
privileged mode and developer-only `SYS_ADMIN` relaxation are not release paths.
[Playwright Docker guidance](https://playwright.dev/docs/docker)

First-owner bootstrap uses a deployment-created one-use capability and a same-origin web
session. Local-only deployment binds loopback; network deployment requires an explicit trusted
host/origin and HTTPS boundary. Browser microphone capture uses `MediaDevices.getUserMedia`,
which is a secure-context, permission-controlled feature; the UI must expose capture state,
stop tracks and recover from denial rather than relying on native app permissions.
[W3C Media Capture](https://www.w3.org/TR/mediacapture-streams/)

The selected first STT profile captures 16 kHz mono PCM through an AudioWorklet and runs the
separately named PCM-only downstream `deeptwin-faster-whisper==1.2.1+deeptwin.1` (derived from
upstream faster-whisper 1.2.1) with CPU int8 and the multilingual small model pinned to revision
`2ec96c5472da50d38d40c0cfe0602af2e94b4c8a`. faster-whisper is not a true streaming decoder:
rolling provisional windows and a separate final utterance pass are our application behavior and
must be measured. The downstream wheel rejects non-NumPy media decode, VAD, remote model/tokenizer
fallback and runtime downloads, so unused PyAV/FFmpeg/ONNX Runtime/Silero model payloads do not
enter the speech image. The speech image contains the pinned model/read-only weights and has no
network; there is no runtime auto-download or hidden external STT fallback.
[faster-whisper 1.2.1 release](https://github.com/SYSTRAN/faster-whisper/releases/tag/v1.2.1)
[pinned multilingual small model](https://huggingface.co/Systran/faster-whisper-small/tree/2ec96c5472da50d38d40c0cfe0602af2e94b4c8a)

The portable provider credential vault uses PyNaCl 1.6.2 XChaCha20-Poly1305 with a versioned
envelope/AAD and a deployment-created root separate from work data. Owner passwords use
argon2-cffi 25.1.0 with the RFC 9106 second-recommended Argon2id cost profile. Exact package/model,
license/provenance-input and upstream build-input image hashes are now recorded by the T089 lock;
final multi-architecture DeepTwin service images remain T081 work, with their packaged provenance
and signing under T082. Naming these versions is not proof of deployment qualification.
[PyNaCl changelog](https://github.com/pyca/pynacl/blob/main/CHANGELOG.rst)
[libsodium XChaCha20-Poly1305](https://doc.libsodium.org/secret-key_cryptography/aead/chacha20-poly1305)
[RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html)

Use progressive disclosure: one current work surface; graphs are the functional comparison
and control surface; detailed events/lenses/permissions expand on demand. Chat, workspace and
graph share IDs and commands, not competing workflows. Preserve keyboard access, focus and
screen-reader text equivalents for meaningful graph nodes and artifact selections.

## R7. Dependency baseline and locking

Read-only environment inspection found Python 3.12, `langgraph==1.2.11`,
`langgraph-checkpoint-sqlite==3.1.1`, `langchain-core==1.6.2`, `langsmith==0.12.2` in the
existing venv. `app/requirements.txt` pins FastAPI 0.141.1, uvicorn 0.52.4, python-docx 1.2.0
and pydantic 2.13.5. These are observed development versions, not a complete release lock.
Anthropic SDK and Playwright Python were not installed there at inspection. pywebview/py2app
observations are historical and are no longer release dependencies.

T003 closed the pre-web dependency baseline but not ADR-010–012 additions. The current T089 lock
resolves exact compatible wheels/upstream build-input images/model files for both declared
architectures and records platform hashes plus technical license/provenance inputs. Add only
the chosen direct packages; retain explicit langchain-core and transitive LangSmith without
activating cloud tracing. The full `langchain` agent factory is not used by this direct
StateGraph/provider-adapter architecture, so it is not added solely for a skill template.
No silent latest upgrades on app launch; migrations and runtime profiles are versioned. Final
DeepTwin service-image indexes and platform manifests cannot exist until the services are
implemented and therefore are produced by T081, then linked back to T089's build-input lock digest;
T082 qualifies their SBOM, source-to-binary provenance, hermetic native-Linux verification and
authorized signing, while T084 owns notices, source offers and legal/publication disposition.

Research skill and LangChain ecosystem/dependency/graph/persistence/HITL skills informed
selection. Their cloud-tracing defaults do not override local-first/no-automatic-transmission
requirements. Exact new server/worker dependency versions are an implementation lock task, not an unresolved
product behavior; their compatibility must be evidenced before release.

## R8. Evidence, remaining risks and decision closure

The architecture choices above are made. Remaining uncertainties are testable release risks:
Codex model-step tool protocol, real Claude integration under finite authorization, isolated
Chromium sandbox/STT/browser secure-context permissions, crash recovery, production credential vault,
semantic critic reliability, lens effect and both fresh-host web distribution profiles. They have named tests and may require implementation
changes; they are not permission to mark mandatory capabilities complete without evidence.

The paper's narrow research-preview scope (CLI, one provider, limited formats) is not our
product scope: later direct user requirements explicitly extend it. The paper's evidence
firewall, no automatic promotion, independent verification and privacy constraints remain.
Actual publication, paid account actions, signing credentials and real human acceptance are
not inferred from automatic technical-decision delegation.

## R9. Semantic extensions remain separate from transport, UI and deployment authority

ADR-014 rejects the earlier assumption that a generic authenticated worker envelope is a complete
extension SPI. Transport carries bounded identity, references, deadlines and cancellation; a closed
core-owned matrix separately fixes each extension kind's artifact form, semantic port version,
trust tier, staging authority, operations, schemas, effects, idempotency, cancellation, outcomes and
artifact rules. This is what lets an out-of-tree implementation substitute without importing the
browser/API presentation layer or redefining authority.

Executable extensions are externally operator-staged, digest-pinned OCI services. The product may
prepare a typed deployment request and consume a signed receipt, but it has no Docker socket,
runtime downloader, container controller or host-path/post-start/unmanifested mount authority.
Descriptor/request-declared dedicated socket or named-volume mounts are created only by the operator
at service creation. Replacement is parallel and non-destructive through handshake, qualification
and binding CAS. Current uninstall advances an installation tombstone, while old-service retirement
names a strict ancestor and advances a target-keyed retirement head only after the descendant current
head and zero binding/rollback/environment dependencies are rechecked. Immutable binding history is
not itself rollback eligibility: supersession/disable creates a target-binding-keyed retained head,
and an exact owner release command preserves that history while making the target ineligible for
rollback and therefore eligible for retirement once the other dependencies are empty. Code-free definitions alone may
be imported in bounded form by the authenticated owner.

Verified installation bytes, context-keyed qualification and exact five-field `BindingSlotKeyV1`+
digest binding plus target-binding-keyed rollback retention are separate immutable histories
with atomic heads/events and startup
reconciliation. Different same-port slots coexist and only exact same-slot candidates compete. The
four deployment operations have separate closed request/result arms and one-way digest causality.
The eleven semantic ports have 44 core-owned field-complete base schemas, a closed 52-operation×
terminal/result-artifact matrix and a separate all-52 request-artifact-input matrix (eleven core-profile
non-empty-capable operations and 41 exact-empty operations). Export prepare/transmit each receive the
exact immutable snapshot/prepared artifact list as bounded IPC bytes rather than refs or a shared
store. Result role/media/omissions metadata is operation-closed, including codec target-media and
output-omissions equality and core-owned tool output contracts; `result.effect` alone defines the
exhaustive terminal/effect/outcome truth, so embedded errors cannot disagree and unknown effects are
never retryable failures. The author SDK authors only
manifests/refinements. The authoring SDK and HTTP/OpenAPI client are separately installable, and the
client must prove actual-server parity through T025's composed durable TLS bearer route from a process
that cannot import `app`. The recursive core boundary includes `app/extensions/**`. T087's private out-of-tree conformance fixture has its own source,
OCI descriptor, SBOM/provenance and license inventory; it is neither a T089 core build input nor a
T081 core/built-in image lock, and arbitrary third-party extensions are never bundled by implication.

T018 therefore has two gates inside its existing task, not a new task split: foundation proves the
actual Linux listener/handshake, bounded artifact stream and staged sandbox/channel needed by
semantic integrations; final closure consumes those downstream integrations. T083 continues to own
the two-clean-host release repetition, avoiding a T018↔semantic-worker dependency cycle.

The project targets an OSI-licensed open-source release, but the current repository has no license.
T084 therefore remains a legal/publication gate requiring explicit copyright-owner approval; these
architecture decisions alone do not make the repository legally open source.
