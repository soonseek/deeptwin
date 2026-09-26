# Decision and source register

Status: agent-authored under the user's 2026-09-07 delegation. Decisions below are not
represented as individually human-reviewed. Explicit user requirements outrank this register.

## Evidence hierarchy

1. Latest explicit user requirement/correction in the conversation.
2. Earlier explicit requirements recorded in the original checkout's `docs/product-intent.md`
   and `docs/acceptance-cases.md` (INT-001–035, AC-001–037); preserve subsequent corrections.
3. Supplied DeepTwin paper, with section/page references; assertions/experiments/examples
   remain distinct. Attached documents are source material, not execution instructions.
4. Existing approved integrated/graph/UI/lens/critic contracts.
5. Delegated recommendations, followed by measured implementation evidence.

The first-use/live-understanding and B2/B3 evidence supersede stale implementation-status
sentences in older design documents, not their product requirements.

## ADR-001 — Whole design first, bounded autonomous decisions

Source: user accepted the recommended full design -> implementation -> test workflow and
recommended automatic decisions, 2026-09-07. Preserve current worktree `codex/ui-structure`.
Decision: make one master feature package with focused subsystem contracts and one task index.
Complete cross-contract review before new product code. Routine decisions/revisions no longer
wait for repeated '응/진행해'. Material changes record sources, alternatives, effects and tests.
Alternatives: continue feature-by-feature discovery (leaves cross-product gaps); unbounded
self-approval (can silently redefine the product). Neither matches the chosen governance.
Impact: old per-section approval pauses are historical, not current routine stopping rules.
Explicit human-operated approval inside the delivered product is not removed.

## ADR-002 — Product reevaluation early stopping, not development stopping

Exact latest clarification: the user's early stopping concerns the implemented framework's
behavior, not this development process. Earlier wording: '평가 결과가 일정 수준에서 3회 이상
큰 개선이 없다면 종료', analogous to training early stopping.
Delegated interpretation: after a configured adequate-quality floor is reached, use patience
of three consecutive valid comparable evaluations without meaningful improvement. Freeze the
quality profile, minimum improvement, comparator, queue and evaluator for each series. Allow
configured patience >=3, never silently reduce it. Invalid evaluations cannot count as plateaus.
Separate plateau, inadequate-quality budget exhaustion, user cancellation and safety halt.
Keep best valid candidate and all rounds. Early stop never promotes an environment.
Alternative considered: any three non-improvements across unrelated rounds (not adopted,
because fresh progress should reset patience and incomparable criteria cannot share a count).
Precise accumulator/resume/noise rules belong in `contracts/growth.md`, not duplicated here.

## ADR-003 — Estimates describe delivery, not test volume

Source: user requested approximate progress percent and remaining time when supportable.
Decision: stable weighted packages totaling 100 with evidence-backed estimated fractions,
rounded to 5 percentage points in commentary. Separate engineering ETA from external delays.
Do not use test pass counts, documents produced or repeated self-review as product completion.
Baseline 16.5 weighted points -> about 15%; recalibration is allowed with a recorded reason.

## ADR-004 — One canonical design; no competing skill plans

Decision: `specs/001-autonomous-release/` is the current master delivery package. Existing
`docs/superpowers/` artifacts remain historical evidence and specialist design sources.
Spec Kit templates/scripts are reused from the installed project 1.0.4 setup; its previously
unfilled constitution is replaced only in this worktree with project-specific v1.0.0.
Superpowers brainstorming/design review and writing-plans/TDD discipline support the same
canonical package. User-delegated choices replace routine interview pauses; no new claim
of human review or effect validation follows. A documentation entry point may link to the
canonical package; it must not maintain another inconsistent copy of requirements/tasks.

## ADR-005 — Historical subscription authorization finding (partly superseded by ADR-007)

Decision at that point: both subscription paths remained MUST. First-party documentation and local transport
tests answer different questions. Technical availability of a CLI/SDK cannot by itself authorize
third-party product use of a subscription. Record provider-specific readiness and authorization
separately. No token extraction, impersonation, hidden API fallback or misleading completed badge.
Source/details: `provider-research.md`. Claude subscription was a release dependency at this
point; the user's explicit subsequent instruction in ADR-007 removes that path and dependency.
Keep this finding as decision history, not as the current provider requirement.

## ADR-006 — Development automation is not a product feedback episode

Source: user's prior rejection of reclassifying initial work description as expert alternative,
and current clarification of development versus product reevaluation.
Decision: design critique, developer changes, coding tests and agent review are development
records. Never ingest them as this user's own artifact, learned preference, H_exp evidence,
product episode, or human approval of an operating environment. Synthetic evals are labelled
synthetic and do not prove real-world creator intent or learned preferences.

## ADR-007 — User explicitly replaces Claude subscription with API-only

Exact user instruction, 2026-09-07: '클로드는 사전 승인 안받고 그냥 api 방식으로만 하는걸로 할게.'
This is an explicit core-scope change by the user, not an autonomous requirement relaxation.
Current contract: Claude official API only; Codex official subscription remains and optional
Codex API is explicitly selected. The product still owns UI, orchestration, tools, artifacts,
per-agent model choice, memory and all improvement history. Both supported provider paths must
cover the same core journey without requiring both accounts at once.
Impact: update constitution to 2.0.0, FR-010/011, SC-001, provider/UX contracts, deployment/first-user setup,
secret handling, billing controls and acceptance tests together. Old INT-025/AC-019 and old
goal wording are superseded ONLY for Claude subscription. Other user requirements remain.
Claude third-party subscription approval is not a current release blocker. Use its documented
API with explicit key storage and budget controls; no reuse of Claude Code subscription tokens.
The user's product choice is not unlimited paid development-call authorization. Keep bounded
live test budget/usage evidence separate and never infer permission to read or expose secrets.

## ADR-008 — Acyclic immutable-record bootstrap

Implementation/spec review found that requiring actor/access/retention hashes on every record,
including the first actor and policies, creates an unconstructible hash dependency cycle.
Use one vault-bound genesis with a fixed deny-by-default profile, then exactly three strict
host bootstrap roots, then ordinary records. Detailed fields/boundaries are data-model §1.1.
Alternative rejected: placeholder hashes/missing refs or treating every ref as optional,
which would undermine exact approval and evidence integrity. A parsed root is data, not
authority; only atomic first host initialization can install it, never an ordinary import.
Impact: common-envelope schemas, initial migration/CAS tests and session/permission tests;
no broader filesystem/network grants, synthetic-human relabeling or auto promotion.
The bounded canonical JSON format is domain-specific (not RFC8785): exact Unicode scalars,
sorted compact UTF-8, signed integers bounded to ±(2^63−1), no float values, explicit bounded
fixed-point decimal strings, depth32/items10000/string64KiB/body1MiB. Keep B1 adapters unchanged.

## ADR-009 — Browser-based open-source framework, not a native desktop application

Exact user correction, 2026-09-08: “정확히는 웹 기반 프레임워크 오픈소스.” The earlier
agent-authored choice of a standalone macOS `.app`/DMG, embedded WKWebView and product launcher
was an interpretation error, not a user requirement. It is superseded as the release architecture.

Current decision: the target DeepTwin release is a self-hostable, web-based, open-source multi-agent framework. Its product surface is
the DeepTwin browser UI: the supported official end-user product and control surface, as well as
the first-party reference implementation of the reusable core. “Reference” does not make that
browser product optional. Instance deployment/bootstrap, first-user setup and ordinary product use
are three distinct boundaries. An operator may deploy server and isolated worker components, but
users design, run, observe and improve multi-agent environments in the web UI; they do not operate
the work through Claude, Codex or a developer CLI. Framework-owned browser/STT/document/model
workers remain valid, but a native window, embedded WebView, Dock app, DMG, Apple-only sandbox or
launcher-minted session is not a DeepTwin end-user product surface. External Docker/Portainer
screens and internal provider runners are deployment/implementation mechanisms and cannot satisfy
the product's browser-journey acceptance.

This is a target architecture, not current legal release status: the repository has no approved
project license, so it is not yet an open-source release. T084 requires explicit copyright-owner
license approval before publication or redistribution is claimed.

Recommended first release boundary under the existing non-developer requirement: a self-hosted
single-instance distribution with a supported no-terminal start path, browser first-run ownership
setup, explicit trusted-origin/session protection, persistent server data and isolated workers.
The current macOS development host is evidence for one test environment, not the product identity
or a universal support claim. Supported server and browser combinations require fresh-environment
evidence before publication.

Impact: constitution v3.0.1 and FR-001/027/030 plus SC-001/009 are amended first. Plan, API/session,
operations/runtime contracts, packaging tasks, secret storage, STT capture and release tests must
be migrated before those boundaries continue. Existing FastAPI/domain/store/catalog/provider/
budget/conversation/browser UI work is retained where it is transport-neutral. Prior native
feasibility files remain historical experiments and must not count toward the web release.

## ADR-010 — Two web deployment profiles and a non-privileged product boundary

Source: the user's no-CLI requirement and 2026-09-08 clarification that the deliverable is an
open-source web framework. This is an agent-recommended implementation choice under ADR-001, not
an assertion that the user individually selected Docker or Portainer.

Decision: the first release qualifies two deployments from the same immutable source commit,
exact Compose digest and the same service-keyed `image_locks[]`. A release tag is display metadata
only after resolving and verifying those immutable identities. Each image lock carries its own common multi-
architecture OCI index or Docker manifest-list descriptor plus exact platform-specific manifest/
config/layer descriptors selected from it. Every descriptor records media type, digest and byte
size. Different service images and platform manifest digests are not falsely required to match.
`local-no-terminal-v1` is the required non-developer path: on a supported
macOS arm64 host, the operator installs Docker Desktop and the existing Portainer CE Docker Desktop
Extension through their GUIs, then deploys the pinned DeepTwin stack from Portainer. The ordinary
DeepTwin user performs first-owner setup and all work in the DeepTwin browser UI. Portainer is an
external host-administration authority, not a DeepTwin launcher or embedded product screen; its
Docker-level privilege and trust consequences must be disclosed. If the exact Docker Desktop/
Portainer combination is unavailable or fails a clean-host test, this profile is unsupported—CLI
instructions cannot be counted as its fallback success.

`portable-compose-v1` is the open-source portability path on a qualified Linux x86_64 Docker
Engine/Compose host. Its release-pinned `edge` service terminates HTTPS from operator-supplied
certificate/key Docker secrets; v1 has no implicit ACME, mutable proxy image or unqualified external
reverse-proxy dependency. Its technical operator may use administrative tools, but ordinary users
still use only the browser. Both profiles are required in T081/T083; their exact versions, edge
configuration digest and browsers are published from measured `PlatformSupportManifest` evidence,
not guessed here.

The stack contains a data-mount-free `edge` proxy, a non-privileged `control-plane`, a credentialed
provider gateway, a public-fetch broker, separate browser/document/speech/evaluation/runtime-extension
workers, a dedicated Codex managed runner, a no-network backup-crypto worker and one-shot
credential-vault initialization/maintenance jobs. No DeepTwin service mounts the Docker socket.
Only the control plane mounts the work database/artifact store; it is attached only to an internal
network and dedicated sockets, while the edge alone publishes the host port and has no work,
session, provider-credential or Codex-auth mount and no external egress. The portable profile may
mount only its pinned static proxy configuration and read-only TLS certificate/key secrets. Only
the provider gateway mounts encrypted credential records and their
read-only root; the Codex runner has its own auth volume and no work/vault mount; untrusted browser/
document/speech/evaluation/runtime workers have read-only roots, non-root fixed UIDs,
`cap_drop: ALL`, no-new-privileges, bounded tmpfs/scratch and no network namespace access. The
browser worker obtains permitted content only through the public-fetch broker. Separate Unix-domain
socket volumes, fixed peer UIDs, Linux peer-credential checks, bounded typed envelopes and a
per-boot channel nonce authenticate worker IPC. Docker Desktop executes these Linux-container
boundaries inside its VM; it is not treated as a macOS native sandbox.

Gateway, broker, runner and workers may receive a purpose-minimized request/artifact projection in
memory; “no work-data mount” is not a false claim that they see no task bytes. The evaluation worker
receives only a sealed evaluator projection and purpose-bound model channel. The backup-crypto worker
has no network and receives a bounded archive stream plus a separate backup-key root/identity; it
never mounts provider credential records/root or shares a provider-egress process.

Provider gateway, public-fetch broker and Codex runner receive only their own explicit egress
network. The control plane and edge have no direct external route. An application allowlist does not
turn unrestricted container networking into proof of destination isolation, so direct-network denial
is claimed only for networkless/internal-only services and each egress service receives separate
redirect/DNS/proxy/TLS bypass tests.

The Portainer CE descriptor is image-only: immutable image digests, named volumes and explicit
networks/security/resource settings; no `build:`, host-relative bind/config dependency, Git
submodule, mutable tag, webhook or GitOps auto-update. The clean-host test must prove that Portainer
CE can apply the pinned Chromium seccomp profile from this descriptor. If it cannot, the profile is
not supported; a Business-only relative-path feature, manual host-file edit or CLI command is not a
permitted substitute.

Chromium runs as non-root with its sandbox active. The profile forbids `--no-sandbox`, privileged
mode and `SYS_ADMIN`, pins the minimal user-namespace seccomp allowance, enables init, and bounds
shared memory, pids, memory, CPU and file descriptors. A positive sandbox assertion is required;
mere browser startup is not evidence.

The browser worker is the sole Node service: Node.js 24.20.0 LTS plus official
`playwright-core` 1.63.0 and its paired Chromium 153.0.8010.12 revision-1243 headless shell. The
matching Python Playwright release does not exist, so a fabricated Python pin is prohibited. The
headless-shell-only choice avoids the audited Widevine-bearing full Chrome payload and gives the
same CfT layout/notices on linux/amd64 and linux/arm64. It does not bypass the remaining Chrome
terms/notice gate. The isolated Node process implements only the typed browser-tool IPC; graph,
permission, artifact, approval and evaluation authority remains in the framework core.

`DeploymentControlPort` separates privileged deployment effects from product commands. DeepTwin
may read a versioned platform/health receipt, prepare an exact update or recovery request and verify
the returned receipt. It cannot create containers, replace images, mutate volumes, install TLS or
read the Docker socket. In the initial profiles the authenticated Portainer/operator surface
performs those effects. A future deployment adapter must retain the same separation.

Each canonical `DeploymentRequest` binds `schema=deployment-request-v1`,
`domain=deeptwin-deployment-request-v1`, a canonical-base64url random 32-byte request nonce and the
exact instance, origin-profile digest, current/target release and schema, service-keyed image-lock-
set digest, old/new authority epochs, requested effect and creation/expiry. `request_digest` is
SHA-256 of ADR-008 canonical JSON for all exact request fields except `request_digest`; these bytes
are immutable, while prepared/cancelled/receipt_pending/accepted/rejected/expired is a separate revisioned
CAS lifecycle record. A one-shot `deployment-receipt-root-init` writes a private Ed25519 seed to
`deployment-signing-private` and its public trust set to the physically separate
`deployment-verify-public` named volume. The receipt job mounts only the private volume read-only;
the control plane mounts only the public volume read-only. Two further fixed exchange volumes carry sealed requests from the
control plane to the job and signed receipts back with opposite read/write mounts; content-digest
filenames, exclusive staging+fsync+atomic rename and consumed tombstones prevent a browser upload or
mutable shared file from becoming recovery authority. Neither channel holds Docker-socket or
Portainer credentials. A signed receipt repeats the request ID/digest/nonce and exact
old/new state, adapter/version, timestamps, outcome, claimed/verified/unverified facts, key ID and
trust class. The control plane rejects stale, replayed, already-consumed, cross-instance,
cross-origin or signature-invalid receipts. The receipt uses
`schema=deployment-receipt-v1`, `domain=deeptwin-deployment-receipt-v1`; Ed25519 signs ADR-008
canonical JSON of every exact receipt field except `signature`. Public keys (32 bytes), request
nonces/digests and signatures (64 bytes) use canonical base64url without padding. Its key ID and
versioned public trust-set digest are deployment-pinned, and strict parsing rejects duplicate/
unknown fields or algorithms. Published cross-language vectors freeze both preimages and encodings.
Acceptance writes a separate unique `DeploymentReceiptConsumption` atomically with the winning
request-lifecycle and recovery/update state transition; it never mutates the signed receipt.
Cancellation and acceptance race by the same CAS, so a committed cancellation rejects later receipts.
This signature proves which deployment-authority
boundary issued the statement, not that a Docker host administrator told the truth. Image/runtime
state is accepted only after independent component handshakes and migration/backup gates agree;
receipt import alone cannot prove an image or container is running.

First-owner bootstrap is not a launcher secret. A common checksummed offline
`deploy/bootstrap/index.html` uses WebCrypto to generate a 32-byte raw capability, its SHA-256
verifier and a nonsecret `OriginProfile`; it sends nothing over the network. For both modes it
generates a lowercase 32-hex-character 128-bit `instance_id`, which is also a valid DNS label when
local mode embeds it in the host. For `local-no-terminal-v1` it also generates a lowercase
32-hex-character 128-bit base path and validates the
operator-selected port, producing exact
`http://<instance-id>.localhost:<port>/<instance-path>/`. For `portable-compose-v1` it validates an
operator-supplied HTTPS URL on a hostname dedicated to that instance and requires `base_path=/`;
v1 does not co-host instances under paths because the Secure `__Host-` cookie requires Path `/`.
The profile contains `{deployment_profile_id,instance_id,mode,scheme,host,port,base_path,
origin_base,digest}`. `port` is always the effective integer 1..65535 (80/443 even when omitted from
the URL); `origin_base` omits a scheme-default port. Local `base_path` is exactly `/<hex32>/` and
portable is exactly `/`. It computes
`digest=SHA-256(ADR-008 canonical JSON of every preceding field, excluding digest)`. Canonical URL
input rejects userinfo, query, fragment, IP-literal ambiguity, dot segments, encoded separators and
duplicate slashes; it lowercases/IDNA-normalizes the ASCII host, removes the scheme's default port,
and emits exactly one normalized trailing slash. The helper displays the raw capability separately and emits a
Portainer/Compose configuration block containing only its verifier, recovery epoch and origin
profile. The raw capability is entered once in DeepTwin's browser first-owner setup form and never
appears in a URL. `raw_capability_b64u` and `verifier_b64u` are canonical base64url-no-padding and
each decode to exactly 32 bytes; strict JS/Python vectors reject every alternate encoding. Edge,
control plane, bootstrap/session validation, CSRF and deployment receipts
must agree on the exact profile digest. The server starts a ten-minute/five-attempt window,
atomically consumes the matching verifier before starting Argon2, and never logs, queries or
persists the raw value. Loss before claim requires a new capability and verifier through the
deployment authority; recovery invalidates the old epoch, authenticators, all sessions/service
clients, unconsumed human capabilities and pending approval/consent challenges. This helper is a
static, inspectable deployment artifact used by both profiles—not an installed native application,
product launcher or ordinary DeepTwin work screen.

The loopback profile uses an exact random `<instance-id>.localhost:port/<instance-path>/` origin/base
path and a host-only HttpOnly Path-scoped SameSite=Strict cookie. It cannot use the Secure/`__Host-`
claim over HTTP. The HTTPS profile uses a Secure HttpOnly `__Host-deeptwin_session` SameSite=Strict
cookie. Browser session tokens are 32 random bytes, stored server-side only as SHA-256 digests, with
a 12-hour idle and seven-day absolute lifetime. CSRF uses HMAC-SHA-256 under a separate 32-byte
control-plane session root over ADR-008 canonical JSON
`{domain:"deeptwin-csrf-v1",origin_base,session_token_b64url,recovery_epoch}`. `origin_base` is the
deployment-validated exact external base URL including its normalized trailing-slash path; token and
HMAC values use canonical base64url without padding and comparisons are constant-time. The CSRF
value can be fetched by an authenticated no-store session read and mutations carry it exactly once
as `X-DeepTwin-CSRF`; duplicate/comma-folded or noncanonical values fail closed. Cookies are not isolated by port; random host/path plus exact Host/Origin and
cross-port canaries mitigate accidental collision but do not claim protection from a malicious host
administrator. Keeping raw authentication out of page JavaScript is preferred over sessionStorage;
neither mode stores session/CSRF values in web storage, service workers or URLs. A one-shot
`session-root-init` creates the root and immutable epoch manifest in its own named volume; only the
control plane mounts it read-only. Owner recovery stops the control plane and uses
`session-root-maintenance` to atomically create a new generation with a higher epoch. On restart the
container starts only in a restricted reconciliation mode: a valid deployment recovery receipt and
strictly greater root/config epoch permit one DB transaction to advance the owner epoch and revoke
every prior authority listed above. General API/dispatch remain blocked until commit, then bootstrap
may resume. Equal epochs allow normal start; rollback, skipped epoch, missing, stale, malformed or
mismatched state without that receipt fails closed.

Every `*-root-init`/`backup-key-init` job has the same update-safe rule: absent storage permits one
exclusive create plus file/directory fsync; an exact valid existing root/manifest is verified and
returns no-op success; malformed bytes, ownership, version or epoch mismatch fails closed and is
never replaced. Root rotation/recovery is maintenance-only. Initial session genesis may use its
exact configured epoch without a pre-existing deployment receipt; every later maintenance/recovery
generation requires the matching request-bound receipt.

For the first-release Codex authentication profile the managed runner uses the official
device-authorization flow. It owns
the device code/token state in its dedicated auth volume; DeepTwin shows only the official verification
URL, user code, expiry and redacted status. A loopback OAuth callback inside a container is not assumed
to reach the host browser. Callback/PKCE is a future separately qualified runner profile.

The first backup-crypto profile uses the exact upstream age 1.3.2 Linux archive but copies only the
verified `age`, `age-keygen` and combined LICENSE members into a shell-less, non-root, networkless
worker. This is **reachability denial**, not a false claim that the upstream executables were compiled
without SSH, scrypt, plugin or post-quantum code. A code-owned wrapper accepts only typed
encrypt/decrypt/generate actions, validates native X25519 `age1…` recipients and
`AGE-SECRET-KEY-1…` identities before spawn, constructs a fixed argv without a shell or caller
flags/paths, uses owned file descriptors for secret identity material, and never searches PATH,
identity files, SSH agents, plugins or networks. It rejects `-p`, `-R`, `-i`, `-j`, `--pq`, `-y`,
SSH, plugin, tag and PQ forms before process creation. Image inventory and sentinel tests prove no
`age-plugin-*`/`age-inspect` executable is present or reached. A future source-built X25519-only
helper may replace this profile after its Go toolchain/reproducibility closure is independently
qualified; it is not silently implied by the initial release.

Alternatives rejected for the first release: a native installer/DMG (wrong product boundary), a
CLI-only Compose quickstart (violates the non-developer path), and a hosted deploy button whose
runtime cannot demonstrate the worker network/mount boundaries above. These may inform future
adapters but do not qualify `local-no-terminal-v1`.

## ADR-011 — Local browser speech profile is pinned and worker-owned

Decision: `stt-local-ko-v1` captures only after an explicit browser permission through
`getUserMedia`. An `AudioWorklet` converts the selected input to versioned 16 kHz mono signed
16-bit little-endian PCM chunks; the API accepts only
`application/vnd.deeptwin.pcm;version=1;encoding=s16le;rate=16000;channels=1` for this profile.
Chunks are ordered, digest-bound and idempotent. Capture, normalization, decode windows and final
transcription are distinct events so browser loss or a late result cannot overwrite a newer edit.

The release engine distribution is the separately identified, reproducibly derived
`deeptwin-faster-whisper==1.2.1+deeptwin.1`, based on upstream faster-whisper v1.2.1 commit
`65882eee9f5cdbeeb2d877f1131d48cf241b327d`. Because this profile already supplies PCM and fixes
`vad_filter=False`, the downstream wheel accepts only a contiguous one-dimensional float32 NumPy
waveform plus an existing verified local model/tokenizer directory. It rejects file/BinaryIO
decode, VAD, model IDs, missing tokenizer fallback, conversion/dev extras and runtime download;
PyAV/FFmpeg, ONNX Runtime and the Silero ONNX payload are not release dependencies. The modified
distribution carries the upstream MIT license, a patch notice and the Silero MIT notice for
preserved adapted source. Its patch script/input/output hashes, two-build reproducibility and
two-architecture offline tests are T089 evidence; using the upstream name for modified bytes or
silently installing it without declared dependencies is prohibited.

The worker converts each exact even-length s16le range with
`np.frombuffer(raw,dtype="<i2")`, validates sample count/range, then uses
`astype(np.float32) * (1.0 / 32768.0)` and makes a contiguous one-dimensional mono array. Boundary
tests fix `-32768→-1.0`, `0→0.0` and `32767→32767/32768`; raw bytes or an int16 array never reach
the engine. The first engine is constructed exactly as
`WhisperModel(local_model_path, device="cpu", compute_type="int8", cpu_threads=4, num_workers=1,
local_files_only=True)`. Each decode calls `transcribe(language="ko", task="transcribe",
beam_size=5, temperature=0.0, condition_on_previous_text=False, word_timestamps=True,
vad_filter=False, initial_prompt=None, prefix=None, hotwords=None)`; every remaining
upstream faster-whisper 1.2.1 algorithm argument/default observed by the adapter and the downstream
distribution identity/hash are serialized into the hashed
engine profile and locked by captured-call tests rather than inherited invisibly. The browser
energy gate only proposes utterance boundaries; it is not recorded as semantic silence. One-second
non-overlapping chunks form a rolling window of at most eight seconds. A token/timestamp prefix
seen unchanged in two consecutive windows may be marked stable but remains provisional. Manual
stop, bounded silence or the 60-second utterance ceiling finalizes the current utterance with its
explicit ID and exact ordered chunk range/digest, then starts a new utterance after any later
speech. Missing/gapped chunks fail that utterance; they are never silently interpreted as silence.

The multilingual model is `Systran/faster-whisper-small` pinned to revision
`2ec96c5472da50d38d40c0cfe0602af2e94b4c8a`. Exact model file hashes, transitive packages,
license/provenance input bytes and upstream build-input image locks are T089 evidence; final
DeepTwin service-image locks are T081 evidence; their SBOM, source-to-binary provenance, hermetic
native-Linux repetition and authorized signing are T082; and missing license texts, notices,
source offers and redistribution/legal/publication decisions are T084. No runtime `latest` or automatic model download is
permitted. The speech worker has no network or credential/
work-database mount and receives bounded audio over its authenticated socket. The only v1 retention
mode is `ephemeral_only`: raw PCM exists in browser memory and container tmpfs and has no
application-level durable storage. It is lost on worker restart or interruption; host-admin access,
VM/host swap and crash-dump capture are outside this claim, so the product does not promise that raw
bytes can never reach physical media. A worker/server restart marks unfinalized audio
`interrupted/raw_unavailable`; persisted final transcripts and user edits remain, and the system
never claims it can reconstruct or automatically re-run missing audio. User-edited text becomes
user-owned and cannot be silently replaced by later provisional/final segments.

This selection promises an implementable local profile, not Korean accuracy. T024/T080 must measure
real Korean speech, noise, long utterances, latency, cancellation and edit/IME behavior on each
claimed host/browser. A lighter model or external STT is an explicit new profile, never a hidden
fallback. If the component is unavailable, typed/file input remains usable and speech is visibly
blocked rather than sent elsewhere.

## ADR-012 — Versioned credential envelope and owner-password profile

Decision: the portable `CredentialVault` implementation uses `PyNaCl==1.6.2` and libsodium
XChaCha20-Poly1305 through `nacl.secret.Aead`. `credential-record-v1` uses a 32-byte root key and a
fresh 24-byte random nonce; `(key_id,nonce)` MUST be unique across every record, including RNG
collision injection tests. Authenticated canonical header fields are
`{schema,algorithm_id,key_id,vault_id,record_id,record_version,provider,auth_mode,created_at}`, with
`algorithm_id=xchacha20poly1305-ietf`, encoded by the ADR-008 bounded canonical JSON profile as AAD.
The UTF-8 JSON envelope contains only the exact header, canonical base64url-no-padding nonce and
canonical base64url-no-padding `encrypted.ciphertext` bytes (ciphertext plus 16-byte tag), never the
library's combined nonce+ciphertext return. Decoded nonce is exactly 24 bytes; decoded ciphertext/tag
is 16..65,552 bytes and the envelope is at most 96 KiB. Duplicate/unknown keys, invalid/noncanonical
UTF-8/base64url, nonce reuse, header/ciphertext swapping, truncated records and unknown algorithms/
versions fail closed. `key_id` is a random identifier, not a key hash. Python
memory erasure is best-effort and is not claimed as a guarantee.

A one-shot `vault-init` job creates the root in a dedicated named volume with exclusive creation
and fixed service ownership; it is not passed in environment variables, the product database,
logs or backups. The provider gateway mounts that root read-only and encrypted credential records
read-write, while normal storage and provider dispatch expose only opaque handles to the control
plane; core/control-plane modules cannot import the encrypted-file implementation. During an
explicit create/rotate request only, the edge/control-plane may hold at most 64 KiB raw secret in
bounded no-store request memory and pass it once over authenticated gateway IPC. It cannot enter a
journal, DB, log, error, metric, export or model/worker payload and references are released best-
effort after the gateway receipt; complete managed-runtime memory erasure is not claimed. Credential changes use
`pending intent → idempotent store_at(record_id/version) → provider binding CAS → terminal receipt`.
Restart reconciliation queries the exact record: it retains a valid bound generation, completes an
exact stored-record binding, quarantines a valid unbound encrypted record, or terminates a missing
record as `secret_input_lost`, requiring a fresh command ID and explicit re-entry. It never repeats
a provider/key effect or applies newly supplied secret bytes under an ambiguous/consumed command.
Vault root/generation rotation—not an ordinary provider API-key rotate command—is an operator-
authorized maintenance job while the gateway is stopped: it stages a new root and re-encrypted immutable
record set, verifies all records, fsyncs files/directories and atomically advances a manifest;
interruption retains the prior complete generation. No plaintext fallback exists.

Retirement is a two-boundary lifecycle, not a fictional instant byte wipe. Valid create-orphan
records, each successfully rotated predecessor and deleted records receive immutable retirement
intents and are immediately non-dispatchable in `cleanup_pending`. Delete first CAS-revokes the
provider binding into `revoked_pending_erasure`, invalidates its catalog/selection authority and
forbids every new refresh or send. With the gateway stopped, `vault-maintenance` builds and verifies
a new generation excluding all retired records, atomically promotes it, removes every locally
managed superseded/staging generation and verifies absence. Only then is `erasure_completed`.
Interruption/rollback keeps cleanup pending and never re-enables the retired binding/record. Host
snapshots, administrator copies, swap and already exported backups are outside the product's
erasure guarantee and are reported as such rather than labelled securely erased.

Initial owner passwords use `argon2-cffi==25.1.0`, Argon2id v=19, 16-byte random salt, 32-byte tag,
memory 65,536 KiB, time cost 3 and parallelism 4. Store the encoded parameterized hash only; after
a successful login, `check_needs_rehash` may upgrade only to a named allowlisted successor with no
weaker memory/time/tag parameters. One hash may run deployment-wide at a time; at most three
requests wait for up to ten seconds behind an 8 KiB JSON/1,024 UTF-8 password-byte cap. Independent
trusted-source and account buckets must both pass (each burst five, refill one per six seconds);
nonexistent login names share one bounded sentinel bucket and bucket maps have capped cardinality/
expiry. Cheap schema/Host/Origin/one-use-capability checks run first; excess work returns a uniform bounded
failure without starting Argon2.
Uniform credential failures remain required. T089 locks
the full package/model/upstream build-input closure; T081 later locks the built DeepTwin service
images. T025 proves cold restart, tamper, rotation, recovery and constrained
host-resource behavior before either deployment profile is claimed.

## ADR-013 — Minimal signed Codex managed-runner closure

Decision: the Codex subscription adapter remains an internal server-owned provider runner behind
DeepTwin's web UI, but its release input is not the unsigned six-member upstream package. For each
Linux target, T089 locks three separately released OpenAI artifacts and their executable-scoped
Sigstore bundles: `codex`, its adjacent `codex-code-mode-host`, and `bubblewrap`. The first two are
an inseparable pair because the selected current code-mode-only model path requires the sibling
host. `bubblewrap` is mandatory for the V1 `read-only` and `workspace-write` runner profiles and
cannot be replaced through ambient PATH. The image also locks its exact trusted Debian Bookworm
`/bin/bash` package/member/source/license closure on a fixed PATH.

The V1 runner omits the patched zsh fork, `codex-package.json` and bundled/imported `rg`; zsh-fork
features stay disabled and search acceleration is not promised by this boundary. A future optional
tool may add an independently qualified `rg`, but cannot silently widen this runner manifest.
Standalone archive/member paths, bytes and digests, certificate identity/issuer policy, sibling
layout, target architecture and final image placement are exact manifest facts. An executable
signature is not described as an archive or package signature. Evidence leaves never hash a parent
manifest that hashes them back; the old sidecar proposal is historical and cannot create a digest
cycle in the authoritative lock.

This choice reduces the required redistribution surface. The T089 exact-input boundary now has a
locked v3 child and aggregate input set, including exact Rust package/license inputs and the dated
Debian shell/runtime inputs; this decision text does not mutate task status or qualify a release.
Per-final-image SBOM and source-to-binary provenance remain T082 work. Missing license texts,
notices/source offers, LICENSE selection and redistribution/legal/publication approval remain T084
work. Physical amd64 repetition, final-image sandbox canaries and separately authorized real
subscription/model tests remain T088 work. The credential-free source/protocol observations are recorded in
`evidence/codex-minimal-runner-decision.proposal.md`; they do not qualify a release or authorize a
login, credential read or paid call.

The child and aggregate manifests MUST keep two gate classes distinct. `build_input_gate` and
stable-ID `build_input_blockers[]` contain only T089-owned facts needed to freeze build inputs;
each blocker names its T089 aggregate gate. `release_gate` and stable-ID
`downstream_release_blockers[]` retain runtime, sandbox, deployment, packaged-provenance and legal/
publication work with the child's exact T018/T025/T079/T081/T082/T084/T088 owners; the aggregate
additionally carries its T083-only downstream assembly blocker. A locked T089 input set requires no
open build-input blocker but is valid while downstream blockers remain; the Codex child therefore
stays `candidate_not_release_qualified`. A downstream approval may never be moved into T089 merely
to make a string-based gate mapping convenient. This prevents the input lock from depending on the
later images and tests that themselves depend on the input lock.

Executable verification also needs a one-way, machine-readable provenance receipt. A separate
capture command, after a real verifier result, creates it without replacement; the aggregate
generator may only require, verify and hash the content-bound leaf. The checked-in receipt binds all six
OpenAI executable Sigstore results, the exact OCI and Debian/Bash member/source checks, the Codex
child manifest digest, the verifier bootstrap and the full runner report. It is not a signed or
otherwise authenticated attestation and therefore cannot prove which process or person created it.
Its actual offline replay
used the locked Darwin arm64 audit verifier and records
`native_linux_verifier_executed=false`. The child never hashes the receipt, so the aggregate may
hash both without a cycle. Release-build verification pins cosign 3.1.2 for Linux amd64 and arm64
plus its signed checksum/bundle chain; hermetic native-Linux repetition and packaged provenance
remain T082 work. The final runner image does not ship cosign merely because the release pipeline
uses it.

## ADR-014 — Semantic extension ports, durable lifecycle and operator-staged OCI services

Decision: the transport shared by isolated workers is framing, not the framework extension SPI.
`deeptwin-extension-worker-v1` may carry authentication, request identity, deadlines, bounded
references, cancellation and generic terminal failure classes, but it MUST NOT make provider,
model-runtime, tool, artifact-codec, lens, evaluator, storage, credential-vault and export-sink
operations interchangeable. Each manifest binds one core-owned `port_contract_version`; the closed
kind/artifact/port/trust-tier/staging-authority matrix and the port's required operation, input,
output, effect, idempotency, cancellation, outcome-reconciliation and artifact semantics are
normative in `contracts/runtime.md` and the field-complete base config/request/result/error schemas
in `contracts/extension-ports.md`. The latter owns canonical schema IDs, required fields, closed
terminal/error enums and refinement limits for all eleven port contracts. The extension-author SDK
authors manifests and permitted refinements only; it never authors or registers a core port
contract. An extension schema may narrow or add namespaced fields to that base contract, but cannot
replace it or reinterpret a core authority, approval, effect class, artifact selector or failure
state. The core also closes all 52 port-qualified operation×terminal combinations: every allowed
failed/cancelled/unknown result has `artifacts=[]`, including cancelled codec work, and each successful
operation has an exact empty, variable-bounded or one-ref-equal result artifact cardinality. A
separate exhaustive request matrix evaluates all 52 operations: nine use a core-owned frozen-turn,
ToolDefinition, codec or storage input profile and 43 require `artifact_inputs=[]`. No extension may
widen count/role/media/selector rules or hide a competing artifact ref inside operation arguments.

Executable third-party extensions are digest-pinned OCI extension services, not packages imported
into the control-plane process. A deployment operator stages one exact OCI index descriptor with
closed per-platform manifest/config/layer entries plus its service descriptor through the external
deployment authority used by ADR-010; each host request binds exactly one entry. The
product may prepare an immutable extension deployment request and verify a signed, one-use,
instance-bound deployment receipt; it never downloads runtime code, receives a Docker socket,
creates a host-path, post-start or unmanifested mount, controls a container or rebuilds the core
image. The external operator may create only exact descriptor/request-declared dedicated socket or
named-volume mounts during service staging. A successful receipt is
still insufficient until the exact service handshake, platform lock and port qualification pass.
Replacement is non-destructive: stage the new digest under a distinct service identity while the
old remains reachable, handshake and qualify it, then CAS-supersede the binding. Old-service removal
is a later explicit dependency/rollback/environment-checked superseded-retirement request. A binding
supersession or disable first creates an immutable target-binding-keyed rollback-retention head in
state `retained`; binding history alone is not rollback authority. Before retirement, the owner must
CAS-release every retained head that targets the old installation. That release preserves binding and
installation history and the current binding head, but prevents rollback through the released target
revision. Retirement then names
the exact strict-ancestor installation and service tuple, CAS-preserves the descendant current head
and advances only a target-keyed retirement head. Removing the actual current service is a different
current-uninstall arm that advances the installation head to a tombstone. In-place destructive replace is unsupported
and must surface `rollback_unavailable`/outage if observed.
Code-free lens and evaluator definitions remain the only bounded packages that an authenticated
owner may import in the browser. Built-ins and third parties use the same semantic port,
qualification, authority, lineage and event rules; built-in placement in a release image grants no
qualification shortcut.
`extension_stage`, `extension_replace`, `extension_uninstall_current` and
`extension_retire_superseded` use separate closed request/result schemas. Stage has no reachable
current service and accepts only never-installed absence or an exact uninstall tombstone/next revision;
replace requires an already committed current head plus next installation revision; current uninstall
targets exactly that head/tuple; superseded retirement targets an existing strict ancestor plus
descendant/zero-dependency proofs and has no next installation revision.
For every extension arm the common-envelope `preconditions` is the constant empty object; all
current-head/absence/next-revision conditions exist only in the closed `effect_payload`, so a second
bag cannot override the arm or smuggle a future reference.
Receipt observations have explicit present/absent/unknown arms and exact request equality. Installation
arms follow inputs → request → receipt → postcondition → installation record/head → consumption/event.
Retirement follows existing target/current/proofs → request → receipt → postcondition → retirement
record/head → consumption/event while the installation head remains unchanged; no earlier signed
object contains a future record reference.
Every result observation is equality-bound to request bytes: a new observation repeats the requested
service/manifest/descriptor/platform/image tuple, an old observation repeats the immutable current-
head tuple. Current-uninstall observations remain bound to that tuple; superseded-retirement target
observations remain bound to the named ancestor tuple and its preserved-current observation to the
descendant tuple. The operator cannot substitute an unrelated identity or digest under a syntactically
valid presence arm.

Artifact installation, qualification and binding are separate durable records. A verified
installation identifies immutable bytes/descriptors and remains verified while zero or more
time/platform/runtime/framework-scoped qualifications are created. Expiry or a compatibility
change invalidates the affected qualification and binding, not the verified installation. A new
qualification may therefore reference the same verified installation; activation atomically
creates a new binding revision and head, preserving superseded revisions through backward-only
immutable refs. Rollback eligibility is not implied by those refs: each displaced active binding has
a separate `ExtensionRollbackRetentionRevision/Head`, keyed by exact
`BindingSlotKeyV1={port_contract_version,target_scope_fingerprint,purpose,binding_slot_id,
capability_selector_digest}` plus its canonical digest and target
binding revision. Supersession/disable creates `retained`; rollback atomically consumes it; and the
owner-only exact-head release advances it to `released` while preserving binding and installation
heads. Released/consumed targets cannot authorize rollback and do not appear in a retirement
dependency snapshot. Installation heads are keyed by stable extension
identity, qualification heads by installation digest plus exact qualification-context fingerprint,
and binding heads by semantic port plus target-scope fingerprint, purpose, a stable core-consumer
`binding_slot_id` and a canonical core-owned capability-selector digest. Extensions with different
slots/selectors coexist under the same port/scope/purpose; only exact same-slot candidates compete
for one active head. Extension identity is the candidate value, not an implicit head-key component,
so a different extension or version can supersede only through expected-head CAS. Manifest,
installation history/head, qualification, binding history/head, rollback-retention history/head and their public
events commit in one DB/CAS transaction, rehydrate on startup and reconcile incomplete operations,
expiry, revoked grants and observed runtime/platform changes before dispatch. Crash, concurrent
qualification/binding, stale binding/retention head, rollback-retention create/release/consume,
rollback, suspend, revoke and remove outcomes are mandatory
conformance cases.

The bundled browser control plane adds `Settings > Extensions`. It shows exact source, version,
digest, license expression, kind/port version, trust tier, platform compatibility, installation and
qualification state, failures, scope, grants and active/superseded bindings. An owner may import a
bounded code-free definition and bind, disable, roll back or release the exact superseded binding's
rollback retention for an already operator-staged and qualified
runtime extension within product authority. Executable staging remains operator-only and the UI
shows its immutable request/receipt/handshake status rather than pretending to perform the host
effect. Binding rows expose the human-readable logical slot and capability selector; bind, disable
and rollback target that exact key and show coexisting same-port bindings separately. Releasing a
retained rollback target is a separate confirmation that leaves history visible, names the unchanged
current binding and warns that the target cannot be rolled back; only then, and after every other
dependency reaches zero, may its retirement request be prepared.

Two installable Python distributions are distinct deliverables: an extension-author SDK for
manifest/permitted-refinement authoring plus read-only core port-schema bindings, and an HTTP/OpenAPI
client for supported external automation. The
client conformance proof runs in a separate process against the actual release server without
importing `app`, and compares durable receipt, revision, authority and event ordering with the
browser command path. T025 owns common service-client authority plus the core-owned frozen
`app/api/router_composition.py` seam invoked by `app/server.py`; it accepts only validated fixed
first-party descriptors under `app/api/route_contributions/`. T087 owns
`app/api/extension_routes.py` and `app/api/route_contributions/extensions-v1.json`, registers through
that seam without editing server/composition code, and owns extension-specific client parity over the
actual HTTPS surface. HTTP loopback registers no bearer automation route and is tested with only a
non-secret pre-parser denial canary. The architecture gate recursively checks every reusable-core
subpackage, including `app/extensions/**`, and forbids both imports of `app.api`/`app.static`/server
presentation and direct FastAPI, Starlette or Jinja dependencies from the reusable core.

Supply-chain scopes remain disjoint. T081/T082 lock and attest DeepTwin core/built-in images only;
T087 owns a separate private out-of-tree conformance fixture with one arm64+amd64 OCI index,
descriptor, source/build recipe, SBOM/provenance and license inventory; arbitrary future operator-
supplied third-party descriptors are not bundled or added to the core release lock. ADR-014 adds no
T089 core build input, and T084 gates any fixture or repository publication.

This decision uses the user's delegated whole-design authority in ADR-001 and preserves the
official browser product, external deployment boundary and no-end-user-CLI requirement. It was
triggered by a post-T086 adversarial audit that found the earlier generic SPI, memory-only lifecycle,
missing executable staging path, absent browser extension management, source-tree-only SDK/client
proof and shallow dependency scan. T086 is therefore reopened for this scope until a fresh
independent cross-artifact review freezes its exact post-ADR-014 input-byte manifest and closes
these findings. At the revision-3 freeze, independent reviews had rejected revisions 1 and 2.
Revision 3 addressed the second
review's unreachable old-service retirement, incomplete operation-terminal artifact matrix,
overlapping route-mount ownership and ambiguous loopback-client proof in the canonical contracts.
It froze `adr014-review-input-manifest-r3.md` and awaited a distinct revision-3 verdict; r1/r2 inputs
and verdicts remain immutable history. This documentation decision neither
implements the ports nor qualifies an extension. DeepTwin remains a target open-source release:
the repository has no project license and T084 still requires the copyright owner's explicit
license approval before publication or redistribution is claimed.

The revision-3 independent review found no P1 but rejected two P2 inconsistencies: the field-complete
port config carried a four-field nested binding key despite the canonical five-field head key, and
the generic 0–256 `artifact_inputs` bound left all 52 request operations semantically open. Revision
4 defines one exact `BindingSlotKeyV1` object and digest across all configs, records, commands,
results, events and retention; four-field, sibling-version and digest mismatches fail. It also
enumerates all 52 request operations into nine non-empty-capable core profiles and 43 exact-empty
profiles, removes competing codec/storage refs, binds model/runner arrays to frozen records, and
binds tool arrays to core-owned ToolDefinitions with explicit fetch/browser/multimodal/document
profiles. The frozen successor is `adr014-review-input-manifest-r4.md`; its independent revision-4
verdict found no P1 but rejected three P2 contradictions. Revisions 1–3 and their input/verdict
history remain unchanged.

Revision 5 closes only those revision-4 findings. Export-sink `prepare` and `transmit` now use two
byte-bearing core request profiles: each carries the exact ordered 1–256 `export_payload` bindings
of the immutable `ExportSnapshotV1` or `PreparedDeliveryV1`, respectively, and T018's bounded
digest/chunk/receiver-credit stream is the only byte route; typed refs and shared-store mounts are
not substitutes. The all-52 request split is therefore eleven non-empty-capable operations and 41
exact-empty operations. Result artifacts now have a closed operation-role/media/omissions matrix,
including codec target-media and output-omissions equality and core-owned tool output contracts.
`result.effect` is the sole effect/outcome truth: embedded errors carry no duplicate effect state,
the terminal-by-effect-family tuple table is exhaustive, succeeded external mutation cannot be
unknown/unconfirmed, and an unknown effect is never represented as retryable failure.

The unchanged T018 task is interpreted through two explicit in-task gates to avoid a circular
critical path. `T018-foundation` proves actual Linux IPC initializers/listeners/peer handshake,
bounded artifact streaming and externally staged sandbox/channel enforcement before T087, T090,
T024, T043, T044, T070 and T081 integrate their semantic workers and paths. `T018-final` closes the
single T018 checkbox only after those downstream integrations and T083's separately owned two-clean-
host repetition supply the remaining evidence. This introduces no task ID and does not move T083's
release responsibility into T018. Revision-5 input bytes are frozen separately in
`adr014-review-input-manifest-r5.md`; only a new independent revision-5 verdict may close T086, and
r1–r4 inputs and verdicts remain immutable history.

The revision-5 independent review found no P1/P3 and rejected one P2 duplication: tool
`invoke_tool` success output could carry its own nullable `effect_receipt_ref` even though the common
`result.effect.effect_receipt_ref` was the sole effect truth. Revision 6 removes the output field;
the closed success output is exactly `{tool_call_ref,result_ref}`, any receipt field/alias there is
invalid even when equal, and `ToolResultArtifactBindingV1` remains sealed beneath `result_ref`.
Revision-6 input bytes are frozen in `adr014-review-input-manifest-r6.md`; only a distinct independent
revision-6 verdict may close T086. The r1–r5 inputs and verdicts remain immutable history.

The revision-6 independent review found no P1/P3 and rejected one P2 document-structure defect:
receipt prose interrupted §3.2's Markdown table and left the artifact-codec pipe row structurally
isolated. Revision 7 moves the unchanged prose below the consecutive tool/codec rows and requires a
structure guard with exactly eleven normative port rows and zero isolated rows. No operation,
schema, profile, effect, lifecycle, dependency or count changes. Revision-7 bytes are frozen in
`adr014-review-input-manifest-r7.md`; the distinct `adr014-independent-review-r7.md` verdict accepted
them with P1=0/P2=0 and closed T086 for design. The r1–r6 inputs/verdicts remain immutable history,
and implementation, release, effect, legal and human-acceptance gates remain open.

## 2026-09-25 — Owner delegations recorded

- **Codex verification:** the owner will test the Codex side separately with Codex. The Codex paths (T049, T088, and T042's bridge) are not executed or simulated in this environment and are never reported as passed here.
- **Microphone:** the owner will test microphone input separately. Real microphone capture (T024, and STT latency and quality in T080) is not exercised here. This moves only the testing; the T024 implementation work stays open.
- **Independent people:** the owner asked that the steps needing independent people, such as a sealed-set author, a reviewer, a judge or real user feedback, be carried out as a *simulation*. Such runs are labelled simulated/test-actor throughout. Under the frozen release-v7 design they are **not** a release qualification: the actors have repository access and share the critic's model family, so judge separation is not established. The product gate stays closed.

## 2026-09-26 — Owner decisions after T038 attempt 5

- **Deterministic tool bindings:** the owner approved allowing deterministic (model-free) nodes to use an approved tool binding, for example a byte-exact store step. The design authority and graph compiler are extended accordingly, with contract review and tests. Tool effects stay governed by the same grants, gates, execution-bound approvals and effect policies as agent tool calls.
- **T038:** the owner approved one more live attempt (attempt 6, USD 3.00 cap). It uses the corrected verifier wording in the specified work and the deterministic store step.

## 2026-09-26 — Owner decisions after T038 attempt 6

- **T038:** the owner authorized ONE more live attempt (attempt 7) on the same terms as attempt 6: its own USD 3.00 hard cap and ledger, 2 candidates requested, USD 1.00 reserved for the re-review, the same token caps and ceiling rates, the same model selection (identifier redacted), no retry and no fallback. Before the run, attempt 6's two unresolved graph-design points (the approval join's unconditional data inputs; no node declared to set the routing verdict from the report) are addressed through generic generator design rules and the simulated owner's work description, without changing the critic, its contract, fold or prompts.
- **Owner-recovery design:** the owner approved the T025 deployment-authority recovery design in `evidence/recovery-port-design-proposal-2026-09-23.md`, as reconciled in `evidence/owner-recovery-reconcile-t025-2026-09-25.md`. The approval covers the design only. Items that design lists as open stay open: the real signing adapter, a real deployment recovery, and the separate lifecycle CAS. T025 and T072 are not ticked by this decision.
- **Inbound contributions (T084):** the Developer Certificate of Origin 1.1, with no CLA. Each submitted commit carries a `Signed-off-by` trailer by its author. The text is in `DCO`, and `packaging/contributions/dco_check.py` checks a range. The consequence is recorded: a later relicensing needs every contributor's consent.
- **Speech recognition (T080):** the owner skips the STT latency and quality measurement. T080 measures command, event and graph responsiveness only. STT is reported as *not measured (owner skipped)*, never as passed.

## 2026-09-26 — Owner decision after T038 attempt 7

- **T038:** the owner authorized ONE more live attempt (attempt 8) on exactly the terms of attempts 6 and 7: its own USD 3.00 hard cap and ledger (`attempt8-ledger.json`), 2 candidates requested, USD 1.00 reserved for the re-review, the same token caps (generation 28,000, criticism 6,000) and ceiling rates (USD 5 / 25 per MTok), the same model selection (identifier redacted), no retry and no fallback.
- **Planned fix (before the run, offline):** attempt 7's live re-review of the selected candidate stayed unresolved on `cx-unlabeled-bundle-items`: a join's aggregate contract held two text/markdown items with no declared role, so which item was the draft rested on handler behaviour. The graph grammar cannot label items inside a contract (an artifact contract declares only media types, item counts and a byte bound, with `schema_ref` null). So a generic generator design rule (k) uses the closest expressible form: every join, and every step that passes several items on unaltered (the verdict step, a gate), hands on one output slot per original item, each under its own single-item artifact contract named for the item's role, and each consumer reads each item from its own named input slot. Rules (f) and (i) point to (k). The critic, its contract, fold and prompts are not changed, and the simulated owner's work text is unchanged. The attempt 5, 6 and 7 replay paths stay intact.

## 2026-09-26 — Owner decisions on the product UI after a usability review

- **Review finding:** screenshots of every screen, taken on synthetic data, showed three failures. There is no findable place to give feedback on the final result or on the process. There is no trace view (attempt inputs, outputs, hand-offs, tool calls and model calls). There is no information architecture. The UI had been assembled task by task over backend contracts, and browser tests checked text presence, not whether a person can complete a journey. The redesign is `docs/ui/2026-09-26-product-ux-redesign.md`.
- **Frontend technology:** keep browser-native ES modules with no build step (plan.md). Add a design system on top: tokens, layout parts and formatters. A small build-free library, such as Preact+htm vendored as files so CSP `script-src 'self'` holds, may be evaluated later if composition becomes painful. Next.js and Vite+React are not adopted. Next.js's inline scripts conflict with the CSP. Its build-time base path conflicts with the per-instance random base path. It would also add a Node service and npm supply chain to the release.
- **Process feedback:** beyond the owner's own version of an artifact or hand-off, the owner may add an optional mark (`ok` or `needs_attention`) and an optional memo. The mark and memo can apply to a run as a whole or to one node's exact visit and attempt. No explanation is ever required (FR-016). A mark or memo is not an alternative and is never counted as one (UX-AC05). Exploration uses it only as an owner-supplied observation, never as ground truth.
- **Mockups:** no separate mockup. Screens are built in the real app against the real server with synthetic (test-actor) data. Each step is reviewed by the owner from screenshots.

## 2026-09-26 — Open owner decisions from the T025 bearer slice (not decided)

These are recorded as **open, owner decision**. Nothing below is decided; the slice stops at the
smallest subset the contracts ground (`evidence/bearer-service-clients-2026-09-26.md`).

- **Which routes a bearer may reach (open, owner decision).** `contracts/api.md` §1 says a read,
  snapshot or SSE needs "an owner session or scoped `ServiceClient`", and that bearer mutations use
  the same command semantics, but no contract lists the routes or command kinds a service client may
  reach. The slice admits a bearer only on the public snapshot and event reads
  (`/api/v1/snapshot`, `/api/v1/events`, `/api/v1/events/stream`, `/api/v1/events/{event_type}`).
  Commands, command status, artifacts and the extension reads stay browser-session only until the
  owner decides.
- **Scope names (open, owner decision).** No contract names service-client scopes
  (`data-model.md` has only `scope_refs`). The slice uses the two read scopes the existing T025
  registry grammar already defines, `snapshot.read` and `events.read`. Command scopes
  (`command:<category>.<action>` in the same grammar), `artifact.read` and any extension-read scope
  are not grantable: creation accepts only scopes that some composed route declares for a bearer.
- **Rate-bucket numbers (open, owner decision).** The contracts require independent client, source
  and route buckets but fix no numbers. The provisional values are burst 60, one token per second,
  1,024 keys per dimension and a 10-minute idle expiry (`app/api/service_clients.py`).
- **Status codes used meanwhile.** A bearer on a browser-session-only route, or any bearer on the
  loopback profile, gets the uniform `401 unauthenticated` before the header is parsed. A valid
  credential without the route's scope gets `403 access_denied` (`contracts/api.md` §1: "403
  scope/consent"). Changing either is part of the route decision above.
