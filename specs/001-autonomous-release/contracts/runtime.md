# Runtime, model and framework-tool contract

2026-09-07 · `runtime-v1` · Delegated design, not implemented/qualified behavior.
Normative companions: [spec](../spec.md), [data model](../data-model.md),
[experience](experience.md), [growth](growth.md), [operations](operations.md),
[verification](verification.md). Latest Claude scope is API-only.

## 1. Authority and interfaces

DeepTwin owns the task graph, inputs, model choices, scheduling, tool grants, artifacts,
handoffs, evidence and approval records. A provider generates model steps; it cannot grant
permissions, select a paid fallback, overwrite approved state or declare verification passed.
Ports are `ModelGateway`, `ToolDispatcher`, `ArtifactStore`, `RunLedger`, `GraphScheduler`,
`PolicyResolver`, `Evaluator` and `CredentialVault`; the vault receives its root through a
deployment-only `CredentialRootPort`. No GUI mode bypasses these boundaries.

`ModelGateway.step(FrozenTurn, CancelToken) -> typed events` and `cancel(call_id)` separate
transport from authority. Each FrozenTurn binds work/environment/node/execution/attempt,
provider/mode/account/catalog/model/effort, instruction profile, allowed input refs, output
schema, runtime-profile qualification, deadline, budget reservation and consent. Output
parsing never accepts new capability names or arbitrary host paths as execution authority.

Gateway profiles:

| Profile | Permitted inputs/outputs | Prohibited ambient capability |
| --- | --- | --- |
| `understanding` | work revision/source extracts → bounded work model JSON | tools, user config, persistent user memory |
| `design` | confirmed work + qualified atomic lens decisions → graph candidate | target user's diagnosis store, shared critic conclusions |
| `critic-*` | existing six-field PreparedInput boundary → contract response | tool use, generator lens identity/self-scores, other critics' verdicts |
| `execution-model-step` | node-granted inputs/tool results → tool request or final artifact specs | provider built-ins, local shell, direct store or browser access |
| `diagnosis` / `inquiry` | purpose-bound originals/alternatives/evidence → differences/hypotheses/questions | blanket operational memory writes, personal profile construction |
| `change-compiler-input` | verified behavior evidence + H_exp + typed change proposal | H_phi/S_phi, raw expert alternative as executable instruction |
| `sealed-evaluator` | frozen candidate outputs + isolated evaluator assets | candidate generator histories and answer leakage to candidate |

Profile qualification is version-specific; a no-tool critic stays no-tool when an execution
profile gains tools. Inputs are constructed from an allowlist, not an arbitrary data object
with selected keys blacklisted. Tool/web/upload content is untrusted data, never system text.

## 2. Graph contract and compilation

`GraphVersion` has a work-model ref, structural decisions, nodes, edges, artifact contracts,
memory policies, model bindings, grants, observation contract, completion criteria and finite
budget policy. Its public functional projection omits generator lens identity/self-scoring.

Node kinds: `agent`, `deterministic`, `router`, `join`, `human_gate`, `bounded_loop`.
Each has stable local ID, responsibility, input/output contracts, failure policy and references
to tools/models/memory as applicable. Tools invoked inside an agent appear as child executions
in the same trace; rendering a tool node does not falsely imply a separately reasoning agent.

Edge kinds: `artifact`, `control`, `approval`, `observation`. Artifact edges specify source
output slot, receiver input slot, mandatory/optional, multiplicity and exact accepted MIME/
schema types. Control edges express order/conditions; observations do not trigger execution.
Router predicates use a bounded typed expression language over validated facts, not `eval`
or generated executable source. LLM routing emits an enum that is schema-checked and audited.

Compile checks include unique IDs, existing endpoints, reachable required outputs, required
input producer, matching MIME/schema/cardinality, no approval bypass, memory/permission
compatibility, allowed model capability, explicit joins and bounded cycles. Arbitrary cycles
are rejected: every repeat has a loop ID, termination condition and hard iteration cap.
Graph syntax validity is not evidence of task suitability; the critic supplies separate review.

Join modes are `all_selected` (wait all activated branches), `any_success` (first valid success;
record all other cancellations/results), and `collect` (explicit min/max and failure handling).
The router seals its activation set for this run/loop visit before branches dispatch. A join
cannot finish against an open set. Winner selection uses a single ledger compare-and-swap
and a unique join-activation ID; simultaneous successful branches cannot schedule the successor
twice. If observation order ties, the frozen branch-ID ordering is the tie-break. Losing
results remain evidence but cannot replace the sealed winner or its successor's input.
Skipped branches are terminal `skipped`, not phantom inputs; a required producer failure
blocks its dependants. Independent branches may proceed within budget and isolation rules.
Multiple writers produce immutable versions; merging a shared board requires expected revision
and an explicit merger, not last-writer-wins loss.

The compiler maps approved functional nodes to LangGraph nodes, preserving node IDs and
generating only code-owned handlers. State contains immutable refs/counters, not secret-bearing
clients. Reducers merge results by execution ID and reject conflicting duplicate hashes.
Do not combine unconditional edges and dynamic goto for a node unless both are intended.
Graph recursion limits are an emergency cap in addition to domain loop budgets.

## 3. Generation and criticism before execution

Confirm a common work model from original sources. Route qualified micro-lenses, produce
their structured design decisions, compile functional candidates and review each independently.
Use the existing graph-generation and verification-selection contracts for the B1–B4 boundary.
Lens names are audit-only in ordinary UI, but their concrete design decisions must have
traceable structural effects. No fixed three-template substitution.

Bounded initial recommendation: up to 6 initial candidates, up to 2 further supplementation
rounds with at most 3 new candidates each; total at most 12 candidate versions per request,
including repaired versions. This is a design-generation cap, not the product growth plateau.
All proposals/rejections/critic calls consume the same explicit parent budget. One candidate
review comprises structure checks plus source review, counterexample proposal, independent
validity and candidate-response checks as applicable. Unknown/failed qualification cannot
be called passed. Show qualified candidates as they arrive; do not promise three in all cases.

Selection first eliminates mandatory failures/unresolved critical checks, then applies a
frozen task-specific quality ranking and diversity over role responsibility, dependency shape,
memory access, permission/approval placement and evaluation placement. Require at least two
meaningful structural axes of difference across the shown set. Names/layout/node count alone
do not qualify. If weights lack evidence, use declared ordinal criteria and explain ties;
never make numeric scores appear empirically calibrated. Repairs get new versions/reviews.

## 4. Execution, attempts and lifecycle

`Run` pins the approved environment and current work input. `NodeExecution` identifies one
logical visit (including loop index); `Attempt` identifies a retry of that visit. A repeat
visit is not a retry. Read models expose original and latest attempts separately.

Main attempt states: `reserved → preflighting → dispatching → running → validating →
succeeded|failed`; side states `awaiting_human`, `cancel_requested`, `cancelled`, `timed_out`,
`recovery_pending`, `quarantined`. Allowed transitions are version-checked. Producer success
requires complete valid output artifacts, checks and an immutable handoff-ready manifest,
not downstream execution completion or provider `end_turn` text. Validated artifact readiness
activates a consumer; delivery/receipt/consumption are separate states. Handoff failure blocks
the affected dependency or run completion without retroactively erasing producer output.
Whole-run success additionally requires its mandatory deliveries and completion criteria.

Before dispatch: atomic reserve ID/budget/event/ownership, verify current consent and bindings,
construct allowed input envelope and deadline, then send. Timeout covers queue admission,
preflight, process spawn/auth, stream, tool loop, parsing and terminal observation. Phase
timeouts never reset the whole deadline. A refusal is not retried to bypass it.

Cancellation first durably closes the dispatch gate, then requests owned transports/workers
to stop. Track `dispatch_blocked_at`, `local_transport_closed_at`, `owned_process_exit`,
`remote_terminal_observed`, `usage_finality` separately. A dead socket is not proof that
remote computation/billing stopped. Storage failure triggers in-memory emergency inhibition
plus visible recovery state; never claim durable cancellation if commit failed.

Late responses attach as quarantined evidence to the original request; they cannot restore a
terminal run, overwrite newer revisions or affect a completed evaluation counter. Startup
reconciles recorded attempts, child ownership and checkpoint cursors before new dispatch.
PID alone is insufficient ownership; use nonce/start-time identity. Never kill unrelated
user provider/browser processes. Uncertain irreversible results require reconciliation.

## 5. Artifacts and complete handoffs

Artifacts are bytes plus MIME, digest, size, provenance, access scope and availability. A role
can emit zero/one/many typed outputs; required slots cannot be satisfied by a fabricated path.
Partial model text is provisional until validated and sealed. PDF/image/table/document previews
are derived artifacts with their own digest and fidelity note. Preserve the original format.

`Handoff` binds producer execution/attempt, exact artifact refs, receiver execution/input slots,
schema check and delivery receipt. Receiver access resolves the full artifact within its
grant, even if a bounded model request uses selected extracts/pages. Extraction truncation and
actually supplied spans/pages are explicit; a filename/hash alone is not full consumption.
Further read requests can access remaining granted material through DeepTwin. The receiver's
decision/output can cite used parts. Availability, access, use and causal influence are four
different evidence levels; none is inferred merely from an edge on screen.

Provider payloads are typed `TextPart`, `ImagePart`, `DocumentPagePart`, `TablePart` and
`ArtifactHandlePart`, each bound to its exact artifact/derived projection and supplied ranges.
Claude maps supported image/document content and tool results to the official API blocks;
Codex maps supported image content to the version-qualified `codex exec --json --image` input, text/table
to bounded structured text, and PDF pages to rendered image parts when direct PDF input is
unsupported. An artifact handle alone is not a model-readable representation. Unsupported
modalities require an explicit compatible model choice or a disclosed supported conversion,
not silently describing an unseen image. Every tool result is linked by call ID and consumed
in a subsequent same-role step. Qualification includes visible markers in an actual PDF page,
image and table that cannot be answered from filename/caption alone, plus exact omissions.

Whole-role artifacts remain navigable during execution and replay. Alternatives bind these
exact originals and selectors (text/table/page/image/time) as in growth-v1. Data conversions
do not convert onboarding requests or critiques into an expert's own alternative.

## 6. Framework tool suite and permission model

`ToolDefinition` includes id/version, argument/result schemas, effect class, required grant,
network/filesystem scopes, timeout/byte/resource caps, the core-owned closed
`ToolArtifactInputContractV1`, core-owned `ToolArtifactOutputContractV1` role/media/omissions rules,
idempotency behavior, replay strategy,
implementation hash and qualification refs. The dispatcher, not the model, maps IDs to code. Tool
arguments contain no artifact/selector refs; ordered `ArtifactInputBindingV1[]` is the sole byte-input
authority. A model or extension cannot add a tool or widen its input profile by outputting a name/schema.

The authenticated bounded worker envelope is shared transport, not a semantic SPI. It carries the
request ID, exact manifest/port version, deadline, cancellation and purpose-minimized input/output
refs plus generic transport failure classes. Before dispatch, the core validates the requested
operation against this closed matrix; an absent or mismatched tuple is unsupported rather than
interpreted from extension-controlled schemas:

| Kind | Artifact | Port contract | Trust tier | Staging authority |
| --- | --- | --- | --- | --- |
| `provider` | OCI extension service | `provider-port-v1` | `runtime_worker` | deployment operator |
| `provider` built-in subscription runner | release-pinned OCI service | `managed-provider-runner-port-v1` | `managed_provider_runner` | deployment operator |
| `model_runtime` | OCI extension service | `model-runtime-port-v1` | `runtime_worker` | deployment operator |
| `tool` | OCI extension service | `tool-port-v1` | `runtime_worker` | deployment operator |
| `artifact_codec` | OCI extension service | `artifact-codec-port-v1` | `runtime_worker` | deployment operator |
| `lens` | code-free definition | `lens-definition-port-v1` | `definition_package` | authenticated owner or deployment operator |
| `evaluator` | code-free definition | `evaluator-definition-port-v1` | `definition_package` | authenticated owner or deployment operator |
| `evaluator` executable | OCI extension service | `evaluator-runtime-port-v1` | `runtime_worker` | deployment operator |
| `storage` | deployment-pinned OCI service | `storage-port-v1` | `deployment_trusted` | deployment operator |
| `credential_vault` | deployment-pinned OCI service | `credential-vault-port-v1` | `deployment_trusted` | deployment operator |
| `export_sink` | OCI extension service | `export-sink-port-v1` | `runtime_worker` | deployment operator |

Every semantic contract is core-owned. `extension-ports-v1` in `contracts/extension-ports.md` is the
normative field-complete config/request/result/error schema contract: it fixes the 44 schema IDs,
required fields, closed terminal/core/port error enums, the exhaustive 52-operation × terminal
result matrix, successful artifact cardinality, the separate exhaustive 52-operation request
artifact-input matrix (11 non-empty-capable, 41 exact-empty), exact result artifact metadata and one
terminal/effect/outcome truth, and allowed refinement rules. The summary
below fixes minimum effect, idempotency, cancellation, unknown-outcome and artifact meaning and does
not authorize an extension or SDK to author a replacement port contract:

| Port | Required operations and result meaning | Effect/idempotency/cancellation/artifact rule |
| --- | --- | --- |
| `provider-port-v1` | `capabilities`, `catalog`, `model_step`, `status`, `cancel`; model result separates content, tool proposals, usage and provider-reported identity | network/billing recipient is fixed by grant; request intent is idempotent; cancel and remote-usage confirmation are distinct; outputs use typed content/artifact refs |
| `managed-provider-runner-port-v1` | `preflight`, `device_auth_start/status/cancel`, `run_start/status/cancel`, normalized event stream; the managed agent loop remains runner-owned and never impersonates a raw provider model-step API | dedicated provider egress/auth volume only; run ID deduplicates start; local process cancellation and remote/subscription usage outcome remain distinct; normalized messages/tool/artifact/usage events enter the same runtime ledger |
| `model-runtime-port-v1` | `capabilities`, `model_step`, `status`, `cancel`; local/runtime result uses the same typed model-step projection | no unrelated external effect; exact request ID deduplicates dispatch; deadline/cancel is observed separately; unsupported modality fails before inference |
| `tool-port-v1` | `describe_tools`, `invoke_tool`, `status`, `cancel`; exact registered tool/version and validated arguments/results | declared read/write/external/irreversible effect and ToolDefinition replay policy are authoritative; unknown external outcome is held; produced files are sealed artifact refs |
| `artifact-codec-port-v1` | `probe`, `decode_projection`, `render_preview`, `encode`, `cancel`; selector/media support and omissions are explicit | bounded deterministic conversion where declared; object-store write is content-addressed; cancel leaves no completed artifact; originals, projections and previews have separate refs |
| `lens-definition-port-v1` | `validate_definition`, `compose`, `apply_decision`; emits typed questions/decision contributions/abstention | code-free and no external effect; canonical inputs are deterministic/idempotent; output is audit evidence and cannot grant operational authority |
| `evaluator-definition-port-v1` / `evaluator-runtime-port-v1` | `describe_rubric`, `evaluate`, `abstain`, executable form also `status`/`cancel`; evidence and unavailable items remain explicit | no operational mutation; exact candidate/evidence/profile ID deduplicates; executable cancellation is terminal; output is an EvaluationResult/evidence ref, never a promotion |
| `storage-port-v1` | `capabilities`, `migrate_plan`, `read`, `write_cas`, `health`; exact revision/transaction result | instance-critical transaction effect; idempotent transaction key and compare-and-swap; cancellation only before commit; no artifact/content authority is implied by storage access |
| `credential-vault-port-v1` | `capabilities`, `store`, `resolve_for_gateway`, `retire`, `erase`, `health`; secret remains opaque | instance-critical secret effect; intent ID deduplicates; cancellation only before commit; responses never contain raw secret or reusable handle outside the gateway scope |
| `export-sink-port-v1` | `capabilities`, `prepare`, `transmit`, `status`, `cancel`; prepare and transmit each receive the exact immutable snapshot/prepared artifact list through bounded broker streaming and result binds exact target/snapshot | external/possibly irreversible effect needs target-bound confirmation; request ID prevents duplicate send; unknown outcome blocks retry; a typed prepared/receipt ref is not byte access and no shared-store mount exists |

Extension-owned configuration or operation schemas may only refine the matching base schema under
the three extension refinement fields defined by `extension-ports-v1`; they cannot remove required
fields, add an operation/core or port error/terminal state, loosen a bound, or reinterpret authority,
effect, idempotency, cancellation, retry, artifact selector or failure meaning. The author SDK
authors manifests/refinements and consumes read-only core schema bindings; it never authors or
registers a port contract. Every manifest is
inert until exact bytes/descriptors, compatibility, port version, schemas, provenance/license,
capabilities and isolation are verified and qualified. Runtime-facing services receive only typed
projections through the broker; they never receive the application database, product session,
ambient host filesystem, provider credentials or network merely because the container can access
them. Built-ins pass the same semantic conformance suite and gain no shortcut from repository origin.

Artifact installation, qualification and binding are independent lifecycles. Executable
installations identify an operator-staged, digest-pinned OCI index with closed per-platform entries
and a service descriptor; each request selects exactly one platform entry and
signed deployment receipt; code-free installations identify bounded definition bytes. A verified
installation stays verified while qualifications are created, expire or are invalidated. Each new
qualification binds that exact installation plus platform/runtime/framework/API/schema/port,
conformance suite/version, declared and observed capabilities, results/evidence/scope and a maximum
seven-day expiry. New bytes require a new installation; expiry, platform/runtime/framework/API/
schema/port drift or permission change invalidates only the qualification and dependent bindings.

Installation heads are keyed by stable extension identity; qualification heads by installation
digest plus exact qualification-context fingerprint; and binding heads by the closed
`BindingSlotKeyV1={port_contract_version,target_scope_fingerprint,purpose,binding_slot_id,
capability_selector_digest}` and its ADR-008 canonical digest. Same-port bindings with different port
versions, slots or selectors coexist; only the byte-identical five-field object competes for one
active head. Port config, binding record/head, command/result/event and rollback-retention state use
that same object and recomputed digest; four-field or sibling-version-mismatched keys fail. Extension identity is the
candidate value rather than an implicit part of the key. Binding activation creates a new immutable
revision and atomically advances only that exact keyed head with the public event after resolving
config, grants and credential handles. Supersession, disable and rollback
preserve every older revision; rollback rechecks current qualification/scope/grants and cannot revive
latched authority or an unreachable old service. Older history alone does not grant rollback:
supersession/disable atomically creates an `ExtensionRollbackRetentionHead(state=retained)` for the
exact displaced binding revision, rollback atomically consumes it, and the owner may CAS-release it
through the exact API command while preserving every binding/installation record and current head.
Released/consumed targets cannot roll back and only retained heads populate retirement dependencies.
Executable replacement stages a distinct service
identity alongside the old, then handshake/qualification precede binding CAS. Removing the current
service is a current-uninstall arm that advances to an installation tombstone. Retiring the old
service is a distinct superseded-retirement arm that names an existing strict ancestor, rechecks
binding/rollback/environment dependencies and advances only its target-keyed retirement head while
the descendant current installation head stays byte-for-byte unchanged. Descriptor/request-declared dedicated socket/named-volume mounts
may be operator-created only at service creation; product/runtime-created, host-path, post-start and
unmanifested mounts are forbidden. Manifest, installation history/head, qualifications/head, bindings/head and
events commit through the domain DB/CAS transaction, rehydrate on startup and reconcile incomplete
receipt/handshake, expiry, revoked grant, stale head and runtime drift before any dispatch. Crash,
concurrent qualification/binding, stale CAS, suspend, revoke, rollback-retention release/consume,
current uninstall, ancestor retirement and rollback are mandatory tests. The positive lifecycle
must run A→B→owner release of every A retention head→retire A and prove A history remains while
A rollback is denied and B is unchanged. In a conformance slot with no active-environment refs, it
must then disable B, release the B retention created by disable, verify all dependency sets empty,
current-uninstall B into an exact tombstone and stage C from that tombstone at the next monotonic revision, proving C can
handshake, qualify, bind and dispatch while A/B remain unreachable.

`storage` and `credential_vault` additionally require authenticated operator action, backup/recovery
proof, exclusive ownership and restart/migration gates. `export_sink` cannot send until a human
confirms the exact recipient and snapshot. Uninstall preserves immutable event/artifact lineage and
reports every still-dependent environment version.

The framework core (`domain`, `services`, `runtime`, `operations`, `extensions`) does not import
browser/static/server presentation modules or FastAPI, Starlette or Jinja directly. Architecture
enforcement starts at all five `app/` roots, explicitly including `app/extensions/**`, and scans all
nested Python packages and their transitive in-repository import graph recursively. It rejects
literal and resolvable dynamic imports of the forbidden presentation dependencies. Its typed command, snapshot and public-event interfaces run
headlessly; the bundled browser and a separately installed HTTP/OpenAPI client process that cannot
import `app` must observe the same durable receipts, revisions, authority decisions and event order
for identical commands against the real server.

Provider credentials cross a narrower trusted boundary than general runtime extensions. A
`CredentialedProviderTransport` in the dedicated provider-gateway receives an opaque credential
handle plus a canonical provider request intent; it resolves the handle through `CredentialVault`,
checks connection/version/purpose/budget, binds the request to the manifest-qualified provider,
official HTTPS origin, method/path/body limits and recipient projection, then injects the required
authentication only at send time. It rejects unknown hosts, IPs, redirects, auth/header overrides,
proxy/netrc inheritance and handle/provider/scope mismatches. General provider/model workers never
receive the raw credential, authenticated request headers or gateway filesystem. Responses are
bounded, normalized and redacted before return, while private audit evidence records hashes/status
without credentials or raw provider errors. Fake-server conformance includes redirect/SSRF/header/
log/error/crash canaries and exact command/budget replay.

Normal gateway dispatch and persisted runtime state use opaque handles only. The sole raw-secret
exception is an authenticated create/rotate command after the API's 96-KiB request and 65,536-byte
UTF-8 secret caps: bounded no-store control-plane memory passes it once over the dedicated gateway
socket to `store_at`, then releases references best-effort. Snapshot GETs never open the vault or
gateway; create/rotate/revoke never performs provider check/catalog/model dispatch. Revoked/retired
records cannot authorize sends, and cleanup/remote provider revocation follow the API/OPS lifecycle.

The official Codex subscription runner is a separate `managed_provider_runner`: it owns one
dedicated auth profile and provider network boundary, never mounts the DeepTwin vault or persistent
work data, and receives only typed purpose projections over authenticated IPC. The first release
uses official `codex login --device-auth` and version-qualified `codex exec --json`; the runner owns
device code/token state and DeepTwin receives
only verification URL/user code/expiry, redacted status and results, not subscription tokens. It
exposes no DeepTwin callback and does not assume container loopback reaches the host. Callback/PKCE
is a future separately qualified runner profile. It is a built-in `provider` extension bound to the
separate `managed_provider_runner` trust/isolation tier and must pass the common manifest,
qualification, compatibility, event and binding lifecycle. That tier grants no Docker/operator,
credential-vault or work-data authority and is not a fallback for Claude API.

Each invocation uses a dedicated `CODEX_HOME`, DeepTwin-projected workspace, explicit model,
sandbox/approval policy and versioned DeepTwin-only tool bridge while ignoring ambient user config,
rules, hooks, skills, MCP and workspace content. JSONL is bounded and normalized before it enters the
runtime ledger. This is a managed provider agent loop, not a raw model-step equivalence claim. The
experimental App Server may be qualified only as a visibly labelled catalog/event preview and is not
a production execution dependency; failure cannot be replaced by a fabricated account model list.

First suite: `browser.navigate`, `browser.read`, `browser.screenshot`, `artifact.read`,
`document.create`, `table.create`, `image.compose`, `pdf.create`, `artifact.preview`.
Browser click/form actions are separately classified and require effect-aware grants; external
submission/publishing is not hidden inside a nominal read. Rich future media/code connectors
can be installed only through the same contract, not unrestricted ambient shell access.

Grants bind work/environment/node or named role, tool/version, source/target, action,
credential ref, expiry/use count, byte limits and human/policy authority. Revalidate at every
dispatch, including redirects and resource subrequests. User approval of a graph does not
approve a future unknown post, overwrite or credential upload. Present the exact object/action
for material external effects. Default is task sandbox writes and specifically granted reads.

Network GET is also outbound transmission: a grant binds both permitted recipient and allowed
source/projection categories. Browser URL/query/path/body generation must not receive private
diagnosis, alternatives, secrets or undeclared work content. Derived URLs inherit source tags;
only an explicitly permitted outbound projection can cross the broker. The broker inspects
the actual normalized request and source binding, including referer/cookies, not only domains.
Domain allowlisting or regex secret detection alone is not data-loss-prevention proof.

All agent-produced files are first written under an owned scratch root. Resolve paths through
directory descriptors/no-follow checks, reject traversal, symlinks, special files and path
collisions, then validate and import as immutable objects. Export outside the vault is a
separate human-selected destination; existing files require explicit replace confirmation.
No arbitrary shell, macro, active HTML or dynamic Python executes from a document/model.

The control plane never grants a worker the artifact store or a dynamic host/container mount.
It opens the exact immutable object, verifies digest/media type/declared size and transfers bytes
through the pair-specific socket using bounded frames, receiver credit/backpressure, an end digest
and cancellation. The worker writes only to owned scratch and returns output through the same
digest-first protocol. A short read, changed digest, over-limit stream, stalled consumer or peer
restart fails the attempt without silently substituting a path or sharing the whole volume.

Browser workers have clean dedicated profiles, no product cookie/key/DB access, blocked
service workers and no downloads outside owned staging. Under ADR-009/010 the first release uses
separate long-running Linux containers started by the external deployment authority: browser,
document, speech, evaluation and runtime-extension workers are `network_mode: none`; the networkless
backup-crypto worker receives only a bounded archive stream and opaque backup-key handle/root mount.
The public-fetch broker, credentialed-provider
gateway and Codex runner each have a distinct explicit egress network. The control plane coordinates
logical leases/dispatch/cancel over dedicated Unix-domain socket volumes but never receives a Docker
socket or starts/stops containers. Each IPC channel binds fixed peer UIDs, Linux `SO_PEERCRED`, a
per-boot channel nonce and bounded typed envelopes. Gateway/broker/runner can see only the bounded
request projection in memory and have no work-data persistent mount; “no work data” never means
they receive zero task bytes.

The browser container uses `browser-sandbox-v1`: non-root user namespaces, active Chromium
sandbox, a release-pinned seccomp profile permitting only required `clone`/`setns`/`unshare`,
`init: true`, bounded `/dev/shm`, pids/memory/CPU/file-descriptor limits, read-only root and owned
tmpfs/profile/scratch. `--no-sandbox`, privileged mode and `SYS_ADMIN` are forbidden. A positive
sandbox/userns probe and denial canaries are release tests; an unsupported host fails rather than
silently weakening the profile.

Supported HTTP(S) requests become typed broker fetch requests and return through controlled
fulfillment, never an unrestricted direct worker fetch. There is no proxy-port/CDP-network exception
or shared credential-vault mount. The former macOS sandbox research remains historical evidence
only; the selected server runtime independently tests process identity, mounts, file descriptors,
capabilities, seccomp/userns and egress.
A controlled egress broker enforces
public HTTPS destination resolution, forbidden private/link-local/loopback/metadata networks,
redirect revalidation, TLS certificate/SNI, method/port/domain/size limits and no inherited
auth/proxy credentials. Unsupported WS/SW/WebRTC/QUIC routes fail visibly; direct worker
network remains OS-denied even if interception misses them. Qualify cookie/CORS/origin/redirect
semantics for the supported browsing path; do not claim full-fidelity arbitrary browsing.
The product's own UI/API origin is never accessible to tool browsing. Explicit private-service
connectors require separate grants/adapters, not relaxing the default browser boundary.
Qualification tests direct/redirect/DNS-rebinding/WebSocket/serviceworker/download bypasses;
do not claim isolation based only on Playwright route interception. Unenforceable paths are
disabled and surfaced, not silently permitted.

Artifact tools render bounded declarative content, escaping text and resolving only granted
asset refs. URL fetches in PDF/SVG/HTML rendering are prohibited by default. Content sniffing,
decompression/pixel/page limits and isolated parsers handle hostile files. Formula-looking CSV
values remain data; optional safe spreadsheet export records any escaping transformation.

## 7. Model control and budgets

Provider connection, catalog availability, profile qualification, task compatibility and work
success are separate states. A catalog binds provider/mode/credential-account/workspace and
fetch time. A node choice pins catalog+model+supported effort/modalities. Unknown capability
cannot be guessed from a model name. Retired/unavailable choices require explicit reselection.
Work defaults populate new nodes only; changing them cannot mutate an approved environment.
Record requested/observed model and unreported effort explicitly. No automatic paid fallback.

All sessions need `BudgetPolicy` with finite model calls, tool calls, node visits, loop rounds,
wall time, output bytes and concurrency. Initial product recommendations, adjustable BEFORE
start within authority: execution 100 model steps/200 tool calls/200 visits/30 minutes;
design 64 model steps/12 candidates/20 minutes; growth 10 rounds/500 model steps/1000 tool calls/
120 minutes. Per model call deadline 180 seconds (bounded by remaining session); concurrency
2, additionally capped by available provider/runtime resources. Graph loops default max 5
visits per explicit loop. These safety caps are not sufficient-work or effect guarantees.

API additionally requires an explicit currency cap and a verified conservative reservation
estimate for input/max output/caching or a documented enforced provider spend limit. No
unbounded or zero-dollar default. Unknown usage keeps the reservation, not a zero-cost result.
Subscription uses call/time/concurrency caps and observed limits; do not claim a token/dollar
hard cap unavailable from that provider. Budgets reserve atomically across parallel branches,
include critic/repair/retries, and cannot grow by restarting. Growth budgets remain distinct
from quality/patience. Human waiting dispatches nothing; explicit resumed sessions retain
consumed budget and disclose expired wall-time limits instead of resetting invisibly.

SDK automatic retries are disabled; normalized transient reads may retry at most twice within
remaining budget/deadline. Model calls with uncertain server acceptance use a new audited
attempt only under the approved retry policy, accounting possible prior cost; effects with
uncertain outcome do not auto-retry. 429 spend cap/auth failure require user action, not
infinite retries or silent mode changes.

## 8. Memory and policy compilation

Operational retrieval filters scope, authority, effective time, compatibility, lifecycle and
purpose before supplying artifacts/knowledge. Memory read/write events identify exact refs,
query/selection versions, supplied spans and gaps. Draft diagnosis/alternative/inquiry/heldout
stores are not operating memory. Shared boards use revisioned immutable updates and explicit
merge policies; a role cannot overwrite another's evidence history.

Active knowledge remains canonical structured conditions/actions/exceptions with provenance,
not an ever-growing prompt. Compilation targets are allowlisted node instructions, retrieval
rules, tool restrictions, handoff schemas or graph/gate configuration. Compiler rejects autonomous
relaxation of constitutional/safety/authority/final-human-approval/current-test requirements,
unknown targets, direct H_phi/S_phi inputs and current-alternative leakage. Authorized changes
to ordinary work policies (e.g. removing redundant review or reallocating role grants) remain
valid candidates with before/after criteria, impact tests and exact-version approval. Every
compiled field has supporting behavior refs and a source/semantic leak check. Compatibility
and conflicts are evaluated before activation; conflicting authority is not averaged away.

## 9. Replay and evaluation

Three distinct operations: read-only event replay (no calls), offline snapshot reconstruction
(recorded responses, no paid calls), and new isolated comparative execution (real models/tools
within consent). Each has a visible mode and manifest. Original run and diagnosis manifests
remain sealed; comparison runs fork externalized node/task boundaries and trace changed inputs.
Live external writes are excluded from old-queue reruns unless a separately authorized safe
sandbox/idempotent boundary exists. Missing snapshots mean non-reproducible, not success.

See growth-v1 for floor/patience/heldout/promotion. Operational rollbacks restore a compatible
environment bundle, not already-sent emails or other historical external effects. Observation
telemetry is not the canonical reproducibility ledger. Cloud tracing/export is off by default.

## 10. Mandatory acceptance cases

### Durable transport evidence before semantic admission (partial T018/T040)

`WorkerCoordinator.exchange` issues process-local provenance only after the real authenticated
handshake, correlated MAC frame, response-type and receiver-declared output-stream checks.
Constructing `AuthenticatedWorkerResponse` is structural and grants no capture authority.
The exact response owns a private receipt with weak response/permit identity anchors, frozen
content fingerprint, coordinator generation/route and receiver-policy binding. Only the exact
coordinator may capture it. Active admission is bounded to one uncaptured response per route;
capture/abort releases admission and retains no global completed-response cache. A completed
receipt retains bounded metadata and its durable ref for same-object idempotence, never fresh
capture or read authority. These are host process boundaries, not an arbitrary-Python-code sandbox.

Capture validates the original committed command/attempt/envelope/profile/owner/fence. Current
lease/cancel/recovery state controls classification: only a clean, open, unexpired original
send-intent may become `running/transport_accepted`. Known original responses arriving after
cancellation, deadline, lease/fence change, terminalization or recovery uncertainty are retained
as `quarantined`; they do not reopen a gate or replace earlier transport evidence. Absent or
foreign original command identities cannot create attachments. Exact duplicates return the
committed capture ref without additional events or state changes.

Startup verifies capture journals, immutable records, permission descriptors, exact dispatch
bindings and every registered reachable blob before dispatch readiness. Valid pending-validation
captures keep their original nonterminal attempts recovery-pending with closed gates even when
the old process owner is gone. Uncaptured sent attempts retain the preexisting unknown-outcome
recovery branch. Cancelled/terminal/quarantined attempts receive no capture-based reopening.
Missing, corrupt or conflicting capture data produces a sanitized integrity gap and inhibits
dispatch. Current terminal/cancel/recovery state takes precedence over an old clean transport fact.

Private metadata lookup requires the current ledger session. A separate byte loader uses
`PolicyGate.read` with exact capture and transitive dependency grants, then rechecks grants,
session and ledger generation after loading. Captured bytes are never automatic model inputs.
The public capture event carries only `artifact_count` and `classification`.

A receive-before-attachment-commit crash still has unknown outcome: there is no durable worker
response ACK/redelivery protocol. Capture failure inhibits dispatch and checks durable identity;
it never retries or resends. This slice does not accept semantic results, unblock successors,
settle reservations or finalize usage. Durable extension qualification, source/result validation,
atomic semantic acceptance plus budget settlement, and scheduler integration remain dependencies;
T018/T039/T040/T041 remain open.

| ID | Test boundary and expected evidence |
| --- | --- |
| R01 | Compiler rejects missing producers/types, unbounded cycles, gate bypass and unsafe expressions |
| R02 | Real sequential, parallel, conditional, joined and repeated runs preserve visit vs retry IDs |
| R03 | Same-model independent critic inputs remain isolated despite execution profile tools |
| R04 | Codex subscription and Claude API each request and consume DeepTwin browser/PDF tool results |
| R05 | Per-node provider/model/effort/grants remain separate under concurrency and catalog mutation |
| R06 | Complete original DOCX/PDF/table/image survives handoff; extraction omissions are not hidden |
| R07 | Crash after reserve/send/result/artifact commit/checkpoint; no duplicate effects or lost committed result |
| R08 | Cancel/deadline covers preflight through terminal, with late/remote-unknown evidence and no redispatch |
| R09 | Browser egress, injected commands, path/symlink, renderer fetch and active SVG bypass suite |
| R10 | Atomic cross-branch budget reservation, retry costs, unknown usage and restart limits |
| R11 | Memory access/compiler firewall blocks diagnosis/alternatives/H_phi/heldout leakage |
| R12 | Replay is read-only, isolated comparison does not submit to a real external service |
| R13 | Exact-version human gate and promotion, expired grants, stale approvals and conflicting revisions |
| R14 | API snapshots/SSE expose only allowlisted fields; no checkpoint/private credential content |
| R15 | Insufficient qualified graph candidates remain visibly insufficient; no fake three-way result |
| R16 | Closed extension matrix and all 44 per-port base schemas reject every wrong kind/artifact/port/trust/staging/operation/refinement tuple. The generated 52-operation×four-terminal result matrix rejects every disallowed pair and enforces non-success `artifacts=[]`, cancelled-codec empty artifacts plus successful empty/variable/exact-one cardinality/ref/role/media/omissions/byte equality. Codec render/encode media equals the requested target and every codec omissions ref equals output. Tool results equal their core output contract. `result.effect` is the sole truth; every terminal×effect-family tuple is enumerated, succeeded external unknown and failed unknown/committed/retryable conflicts fail. `invoke_tool` success output is exactly `{tool_call_ref,result_ref}` and rejects output-level `effect_receipt_ref`/aliases; the common effect receipt remains the only receipt truth and `ToolResultArtifactBindingV1` remains under `result_ref`. The separately enumerated request matrix covers all 52 operations exactly once: 11 use their frozen/tool/codec/storage/export input profile and 41 require `artifact_inputs=[]`; export prepare/transmit repeat exact snapshot/prepared lists through bounded broker streaming, while extra/missing/wrong-role/media/selector/hidden competing refs, frozen-list mismatch and absent/widened ToolDefinition contracts fail before dispatch. All eleven configs round-trip one exact five-field `BindingSlotKeyV1` and digest; four-field, sibling-version, binding-ref, command/event or digest mismatch fails. Exact stage/replace/current-uninstall/superseded-retirement arms reject forbidden/missing/mixed fields, duplicate preconditions, future-record refs and request↔head/target/service/digest mismatches. One private out-of-tree OCI tool index with arm64+amd64 entries traverses signed operator staging, per-host selection, dedicated mount, handshake, invocation, restart rehydrate, requalification, slot/selector coexistence and same-slot supersession/rollback. A→B replacement creates exact A rollback-retention heads; owner exact-head release preserves immutable history and B's binding/installation heads but rejects later A rollback. Only then may ancestor-A retirement leave B byte-identical/dispatchable and advance A's retirement head. In a conformance slot with no active-environment refs, B disable→release-B-retention→dependency-zero→current-uninstall→exact tombstone→next-revision C stage/qualification/binding/dispatch also succeeds without A/B revival. Non-ancestor/dependency, stale/cross-slot/repeated retention release, released-target rollback, stale deployment head, cancel/replay/crash fail closed without core rebuild, runtime download, product Docker/mount authority or event/head split-brain |

All are required design-to-test mappings, not current passes. Actual semantic outcomes,
isolation evidence and unsupported boundaries must be reported separately from unit counts.
