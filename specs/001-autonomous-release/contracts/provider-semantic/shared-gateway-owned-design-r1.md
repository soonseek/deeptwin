# Task50 draft — owned shared gateway dialogue prerequisite

Status: **DRAFT, NOT ADOPTED.** Architectural design for independent review. This
document authorizes no implementation, installation, binding, provisioning or
activation. Root owns adoption and the later finite TDD plan.

## 1. Intended outcome and recommendation

The browser-first graph framework needs its already implemented semantic worker,
credentialed gateway and durable attempt machinery to become one admitted runtime
path. Task49 accepted only the conditional owned **worker** transport. The next
unit should make the existing gateway's real prepare/commit/body/result and vault
operations traverse owned authenticated connections through one explicit ingress.

Recommend **owned shared gateway dialogues on a fixed, inert cp-provider profile**.
This is an executable prerequisite: a real accepted connection routes a bounded
first message to the existing encrypted vault or provider-send engine; a real
owned client crosses prepare/body/commit/HTTP/result/cancel. It is not merely a
constructor, and it does not claim that the generic gateway owner possesses the
extension owner's currentness fences.

The outcome is conditional local integration with controlled stores and HTTP,
not the complete runtime integration. `ProviderAttemptTransport` still expects
Task47 fixture channel names. Replacing those expectations now would require an
admitted installation/qualification/binding producer that does not exist for the
semantic worker. Section 9 specifies that next join without manufacturing it.

Product intent remains unchanged: browser-based OSS, no end-user CLI, Claude
API-only, mandatory user-owned Codex subscription with separately chosen optional
API, framework-owned tools and multimodal artifacts. Work descriptions/uploads
are source material; feedback is the user's whole/partial alternative artifact.
Philosophy-grounded difference inquiry, actual paired prior-queue replay with
quality-floor/three-plateau termination and human exact-version promotion remain
required. Purpose-specific understanding/design/critic behavior cannot be replaced
by this transport or relabeled as execution-model-step or graph approval.

## 2. Scopes compared

| Scope | Connected result | Cost and limitation | Decision |
| --- | --- | --- | --- |
| A. Owned shared gateway ingress | Existing vault and semantic-send engines share the code-owned cp-provider profile, one first-frame reader and real owned lifecycle. Controlled HTTP delivery is observable. | Refactors bounded credential fragmentation and send frame adapters; adds cancellation/read/close proofs. Runtime admission remains separate. | **Recommended**, the smallest coherent behavior-bearing prerequisite. |
| B. Distinct semantic-send service/channel | Separates the two `credential_op` grammars at topology level. | Requires a new service identity, pair root/group/socket, boot material and deployment/source identity changes absent from current provisioning. It does not solve semantic installation/C/binding. | Defer; unnecessary new topology for this unit. |
| C. Full semantic artifact admission, current identities and gateway | Same-store replacement, full semantic qualification, binding, worker and gateway dispatch. | Source18/release-source44/private metadata and B four-vector evidence cannot establish this. Requires new artifact/profile evidence, ADR-014 replacement/capacity behavior, genuine current producers and native authority. | Too broad for one finite next unit; explicitly retained downstream. |

An owner-only wrapper with no shared ingress was considered inside A and rejected:
both wire protocols use `credential_op`/`credential_result`; envelope type alone
cannot choose a handler, and the accepted owner must survive the actual dialogue.

## 3. Verified source facts and dependencies

| Dependency / source pointer | Actual present behavior | Treatment |
| --- | --- | --- |
| `app/workers/listener.py:241`, `:377`, `:1159` | Generic `AuthenticatedConnection` owns generation/socket/codec; connect verifies readiness and endpoint inode before handshake, accept checks retained generation and authenticates peer. It retains no original deadline and has no extension fences. Cleanup can skip the socket or mask a primary failure. | Repair only this owner's acquisition/lifetime and add bounded duplex read. |
| `listener.py:1247`; `semantic_connection.py`; Task49 master | `ExtensionConnection` owns populated-generation/readiness/mount checks and retained deadline. Worker `for_extension_slot`/`serve_connection` use it. | Accepted worker behavior stays unchanged. Do not generalize its guarantees to the generic owner. |
| `provider_send_client.py:125`; `provider_send_service.py:351` | Raw factories receive no original deadline; client setup before its main guard can leak. Service polls a raw socket while its HTTP thread runs. | Shared frame engine gets private raw/owned adapters; owner polling must preserve cancel readiness. |
| `credential_channel.py:_read_logical/_write_logical` | First-frame ownership and fragmentation grammar live here: 16,384-byte plain threshold, 24,576-byte fragment-frame bound, `MAX_OP_PAYLOAD_BYTES=102400`. | Extract connection-oriented private helpers here once; keep raw signatures and grammar. |
| `credential_gateway_service.py:_dispatch/serve_one` | Exact v2 operations; legacy store/delete refused; vault result/error shape is already closed. No semantic-send routing. | Preserve dispatch and raw entry; add owned entry and a private already-read logical handoff. |
| `deploy/security/service-ids.json:pairs.cp-provider`, `deploy/compose.yaml:provider` | Static candidate: control 20102, provider 20103, pair 21101, root `/run/deeptwin/ipc/cp-provider`, socket `worker.sock`; explicitly unqualified skeleton. | New code-owned inert profile agrees with these facts. No claim of running/provisioned service. |
| `app/deployment/contracts.py:CONTROL/IPC_ROOT` | Existing code-owned control identity and common root; no gateway ChannelSpec factory. | Reuse control/root constants. New module owns the missing fixed gateway application profile. |
| `test_provider_send_gateway.py:authenticated_spec`; `provider_attempt_transport.py:85,312,355,588,612` | Existing raw conditional fixtures and runtime checks name `credential-gateway`/`task47-provider-send`, worker `semantic-worker`/`task47-semantic-worker`. | Preserve these exact compatibility seams and runtime checks. New profile is explicitly different. |
| `provider_geometry.py`; `provider_conformance_resolver.py`; `provider_installation_service.py:rehydrate` | Same-store verified history and original geometry exist for the private transformer. A parsed geometry/view alone grants no execution authority. | Reuse for future admission; no second registry or inferred semantic qualification. |
| `provider_metadata.py`; `provider_source_contracts.py:PROVIDER_RECIPE`; `provider-conformance.md` §4 | Fixed `claude-text-transform-v1`; literal source18/release-source44 chain and B's four vectors cover supplied text/catalog transforms. | Byte identities/history remain literal; never promote them to full semantic proof. |
| `ProviderSemanticAuthority` / `ProviderSemanticContextLoader` | Conditional dictionaries are checked against real records, but there is no genuine current admitted semantic source/installation/binding producer in composition. | Future concrete producer/consumer contract in §9; no always-success factory now. |

These pointers were read as source, not accepted merely because the dependency
inventory named them. The mandatory masters remain authoritative, especially
provider-owned-semantic-connection, provider-semantic-execution (including its
identity/currency/failure amendments), installation historical-integrity rules,
private-provider-worker and ADR-014. No runtime code reads scratch or Markdown.

## 4. Proposed ownership set and exact interfaces

This is a candidate ownership set for a later plan, not permission to edit it now.
Eight product files, three test modules and one test-only harness are sufficient.

| File | Proposed responsibility |
| --- | --- |
| `app/workers/listener.py` (modify) | Generic owner deadline, one-reader duplex/poll, all-resource close, acquisition unwind. Extension owner untouched. |
| `app/workers/gateway_channel.py` (new) | Fixed inert shared gateway profile and exact identity checks. No I/O or credentials. |
| `app/workers/gateway_connection.py` (new, private exports) | Raw/owned frame adapters and bounded locks for the existing gateway engines. No exposed owner socket/codec. |
| `app/workers/credential_channel.py` (modify) | Single connection-based fragmentation implementation; raw compatibility wrappers; fixed owned credential client factory. |
| `app/workers/credential_gateway_service.py` (modify) | Owned service entry and internal already-read logical dispatch. Preserve vault grammar. |
| `app/workers/provider_send_client.py` (modify) | Fixed owned factory, shared engine, deadline from acquisition through close, serialized commit/cancel/reader state. |
| `app/workers/provider_send_service.py` (modify) | Owned entry/shared engine; already-read prepare handoff; owner polling with existing HTTP lease semantics. |
| `app/workers/provider_gateway_ingress.py` (new) | Exact shared first-frame routing and one-dialogue lifecycle. Gateway-side only. |
| `app/tests/test_authenticated_gateway_connection.py` (new) | Generic owner lifetime, acquisition, duplex, failure precedence. |
| `app/tests/test_provider_gateway_channel.py` (new) | Literal profile and unchanged static topology correspondence, no bypass arguments. |
| `app/tests/test_provider_gateway_owned.py` (new) | Connected owned vault/send/router and cancellation/cleanup proofs. |
| `app/tests/support/provider_gateway_harness.py` (new) | Controlled Unix listener, temp generation, explicit host seams and joined thread cleanup only. |

Proposed public signatures (annotations describe contracts, not new authorities):

```python
# gateway_channel.py; no path, peer, spec, callback or environment override
def gateway_channel() -> tuple[ipc_root.PairRootSpec, broker.ChannelSpec]: ...

# listener.py; factory signatures stay as they are
def connect_authenticated(root, spec, *, requester_boot_id, deadline): ...
WorkerListener.accept_authenticated(*, requester_boot_id, deadline) -> AuthenticatedConnection
AuthenticatedConnection.deadline: broker.Deadline  # read-only retained value
AuthenticatedConnection.read(*, deadline) -> broker.ReceivedFrame
AuthenticatedConnection.read_duplex(
    *, deadline: broker.Deadline, idle_timeout_ms: int | None = None
) -> broker.ReceivedFrame | None
AuthenticatedConnection.write(*, message_id, correlation_id, message_type, payload, deadline) -> None
AuthenticatedConnection.close() -> None

# Existing raw constructors/entries stay compatible; these are additive factories.
CredentialGatewayClient.for_gateway(*, requester_boot_id: str, deadline_ms: int = 5000)
ProviderSendClient.for_gateway(*, requester_boot_id: str, deadline_ms: int = 30000)
ProviderSendClient.abandon() -> None
CredentialGatewayService.serve_connection(owner: listener.AuthenticatedConnection, *, deadline) -> None
ProviderSendService.serve_connection(owner: listener.AuthenticatedConnection, *, deadline) -> None

# Gateway-side composition of existing exact services; no listener creation/root init.
class ProviderGatewayIngress:
    def __init__(self, credential_service: CredentialGatewayService,
                 send_service: ProviderSendService): ...
    def serve_one(self, worker_listener: listener.WorkerListener, *,
                  requester_boot_id: str, deadline: broker.Deadline) -> None: ...
    def serve_connection(self, owner: listener.AuthenticatedConnection, *,
                         deadline: broker.Deadline) -> None: ...
```

`AuthenticatedConnection` becomes factory-issued (ordinary constructor/copy/pickle
refused); source search found only its two internal constructions. Retain `session`,
`closed`, `codec_closed` and context management. `codec_closed` remains valid after
close even when private resource fields are detached. Exact type is an API check,
not a Python isolation claim. Issuance still requires real listener/handshake APIs.

`gateway_channel()` defines application profile `provider-gateway-channel-v1`,
channel `cp-provider`, protocol `credential-gateway-v1`, requester `control`,
responder **`provider`**, direction `control-to-provider`; root is
`IPC_ROOT / "cp-provider"`, responder UID/GID 20103, pair GID 21101, socket
`worker.sock`. Request/result message tuples remain the existing credential ones;
frame 65,536 bytes, in-flight 1, queue 16, operation 30,000 ms. Pair root and endpoint
modes remain `PairRootSpec`/`ChannelSpec` values (outer 0710, endpoint 02710,
socket 0660). These are new fixed code declarations agreeing with the candidate
topology, **not previously implemented provisioning**. A test compares them to
the checked-in static files, but production does not load those files as trust.

Owned factories obtain this profile internally and use
`listener.connect_authenticated(..., deadline=the_original_deadline)`. Local
requester boot is caller's process boot, not a peer/path choice. They have no
general connection-factory parameter. Existing direct/raw constructors remain
conditional unit seams and cannot be selected by app composition implicitly.

Ingress borrows the exact services, requires their same exact vault object and
the credential service's spec to equal the fixed gateway spec, and does not close
their vault/root. It owns each accepted connection. `serve_one` validates the
exact listener root/spec before accept; it does not borrow its private socket.
`serve_connection` validates the owner's session `channel_spec_sha256` against
the fixed spec digest and `local_service == "provider"`. Client checks use the
same independently obtained fixed spec and local side `control`. Session lacks
protocol/channel fields: do not invent attributes; use its authenticated spec
digest, then validate received envelope tuples normally.

No executable launcher, `create_app` registration, HTTP/browser route, environment
test mode, root initializer or Compose mutation is included. A future bootstrap
must establish the approved generation/listener and trusted requester-boot
relationship. Existing credential configuration specifies credential storage,
not that IPC topology or boot provisioning.

## 5. First-message routing and compatibility

One serial ingress call owns the read cursor. It obtains exactly one actual
`ReceivedFrame` with `credential_op`, correlation `None`. The router MUST check
`len(first_frame.payload) <= 24_576` before the initial JSON decode, then decode
that payload once using the existing strict decoder. After decoding, if its schema
is not `credential-fragment-v1`, the router MUST check
`len(first_frame.payload) <= 16_384` before selecting any plain handler or calling
`_serve_logical`/`_dispatch`. This ordinary-message check applies to every plain
credential-v2, legacy-refusal and semantic-prepare arm below. Either excess closes
without dispatch or vault mutation. Both checks measure the original authenticated
payload bytes, never a re-encoded dictionary or decoded string length. These are
the existing credential logical-frame limits assigned explicitly to the new
router handoff; the shared helper retains those same limits for its own entries.
The router neither manufactures a new envelope nor pushes bytes back into the
socket, and this check introduces no second decoder or fragmentation grammar.

1. Plain `provider-send-prepare-v1`, payload at most 16,384 bytes: pass the actual
   first frame and decoded header to the send engine's private
   `_serve_dialogue(connection, *, start_frame, header, deadline)`. Existing
   complete prepare/header/body validators remain responsible for closed fields,
   seq 0, descriptors, semantic request ID/digest and deadline. Keep existing
   `_prepare_wire_deadline` and descriptor checks before body receipt, and the
   complete `prepare_from_header` validation after receipt but before prepare
   admission/ready. No second initial read or JSON decode, new header parser or
   admission based on the router's schema selection alone.
2. Plain `credential-op-v2`: only after the router's original-payload 16,384-byte
   check above, hand the first decoded logical request to the vault
   engine's private `_serve_logical(connection, *, message_id, request, deadline)`.
   Existing `_dispatch` is the sole operation/field validator and preserves
   sanitized errors. Unknown v2 operation produces its existing unsupported
   result; unknown keys on known operations retain invalid-metadata behavior.
3. `credential-fragment-v1`: commit to the credential branch immediately. The
   existing fragmentation implementation consumes that already-read/decoded
   first frame plus remaining frames. It verifies all transfer IDs, indexes,
   counts, correlations, lengths and unique message IDs. Decode the reconstructed
   logical JSON once; require credential-v2 or the closed legacy-refusal shapes.
   A fragmented semantic prepare is **refused**, never rerouted after assembly.
4. Only after the same original-payload 16,384-byte check, preserve exact legacy
   `store` and `delete` shapes for explicit unsupported
   responses (`submit`/`delete` still cannot mutate). Any other schema/absent-schema
   grammar, wrong initial type/correlation, commit/cancel/stream frame first,
   malformed JSON, or oversized plain prepare closes without dispatch.

The router's closed legacy shapes are the existing client's `{op, intent_id,
provider, secret_b64, rotate_from}` with `op=store`, and `{op, handle}` with
`op=delete`. Their values remain untrusted and are discarded by the existing
unsupported handler; no new legacy admission is added. Existing raw `serve_one`
continues its own prior unsupported-operation behavior, even for inputs the new
router refuses before dispatch.

After branch selection it is one vault operation OR one send dialogue until close;
no cross-mode switch or second conversation. A service-local nonblocking serial
latch refuses a concurrent ingress call without touching the active owner's
reader. An already accepted competing owner is closed on rejection.

Private credential helpers in `credential_channel.py` become:

```python
_write_logical_connection(connection, *, payload, message_id,
                          message_type, correlation_id, deadline) -> None
_read_logical_connection(connection, *, message_type, correlation_id, deadline,
                         first_frame=None, first_value=None) -> tuple[str, bytes, dict]
```

Only router/internal raw wrappers pass the optional actual first-frame/value pair;
they must be both present or both absent. The helper validates the first envelope
as well as later ones; it never trusts a routing label to skip checks. Raw
`_read_logical(sock, codec, ...) -> (id, bytes)` and `_write_logical(...)` delegate
to this one grammar through a borrowing raw adapter. A plain first value is reused;
fragments reuse the first fragment decode and decode reconstructed bytes exactly
once. Raw credential service/client use the connection helper internally to avoid
an unnecessary second logical decode. No second JSON or fragmentation algorithm.

The send stream adapters likewise replace raw `sock/codec` use with private
connection methods while retaining exact asymmetric credential message types,
sequence/correlation checks and artifact descriptor/hash/credit limits. Raw and
owned entrypoints execute the same application engine; only the raw adapter has
raw resources. Client modules must still import no vault/gateway implementation.

## 6. Ownership, deadlines, races and failures

### Generic owner's actual guarantees

Retain the exact generation lease, authenticated session, codec and socket from
acquisition through final response/acknowledgement or abandonment. Retain one
deadline bounded by `spec.max_operation_ms` **before** readiness/acquire/connect
or accept/handshake. All later reads/writes/polls take the minimum of supplied and
retained ends. Local filesystem acquisition has deadline checks before/after its
bounded stages; existing nonblocking generation locks remain nonblocking. Do not
claim that Python can interrupt every OS filesystem syscall at the instant of expiry.

Generic owner guarantees acquisition-time readiness/endpoint and authenticated
peer/session plus generation retention. It does **not** gain `recheck()`, mount
checks, populated-generation checks, source measurements or continuing readiness
identity checks. Its already accepted stream may outlive listener close, as
`deploy/tests/test_worker_listener.py:test_accepted_connection_owns_generation_after_listener_close`
requires. It cannot be passed to Task49's exact `ExtensionConnection` adapter.

One nonblocking reader latch covers `read` and `read_duplex`; competing read fails
before bytes are consumed and does not close the legitimate reader's owner.
`read` may delegate to `read_duplex` with no idle timeout. Duplex receives bounded
prefix/body outside the codec lock, then calls real `FrameCodec.decode` once for
MAC/session/sequence checking. No private socket/codec property or readiness FD
escapes. `idle_timeout_ms` is exact int 1..10 (not bool), or None: return None only
when no prefix byte became readable before that poll slice; EOF/error/partial
prefix/body is never idle. Once any prefix begins, finish one bounded frame under
the original deadline or close. A short poll cannot silently consume half a frame.

Use an owner-local deadline-bounded writer latch. Within it encode using the
existing codec, then the existing internal `broker._send_exact(socket,
struct.pack(">I", len(raw)) + raw, deadline)` under the effective deadline, releasing
the codec's internal lock before socket waits. A failed encoded write closes the
owner permanently; advanced send sequence cannot be reused/retried. This avoids
read/close blocking behind a codec lock held over socket I/O. Broker wire bytes and
MAC algorithms remain unchanged. Check closed/deadline before and after each
operation and before returning a frame. No broker-wide lock/refactor is required.
`write_packet` is not suitable here: it accepts a mapping and canonicalizes it,
whereas `FrameCodec.encode` already returns authenticated encoded bytes. The
internal socket remains exclusively inside the listener owner.

### Acquisition and all-resource unwind

In both generic factories, establish local resource slots before the first
fallible acquisition and guard everything through result ownership transfer.
Include generation/readiness, accepted/connected socket, session/codec creation,
owner construction and post-acquisition deadline checks. On failure, close every
acquired codec/socket/generation exactly once as applicable; preserve the original
BaseException. `_accept_transport` must also own/unwind an accepted socket if
validation or listener-timeout restoration fails before return. Restore the
listening socket timeout on every exit without replacing the primary exception.

Owner close latches/detaches its finite resources first, shuts down the socket to
wake readers/writers, attempts codec/socket/generation close independently, then
raises the first cleanup failure only if no operation failure is active. Ignore
only known benign shutdown-not-connected/already-closed OS cases. Repeated close
is harmless; context exit preserves an active exception including process-control
exceptions. No cleanup exception string/path/secret becomes a wire diagnostic.

`ProviderSendClient.prepare` guards UUID/header encoding as well as acquisition.
It clears previous session observation before a new attempt; a failed acquisition
cannot leave a previous ready session as this attempt's identity. Ownership is
transferred to its dialogue state only after complete ready validation. `abandon`
detaches and closes an active dialogue without resend. Raw compatibility gets
all-resource primary-preserving cleanup too, but raw factory handshake timing is
not falsely claimed to be bounded by the client's deadline.

### Commit, cancel and publication

Client state is explicit and serialized: preparing → ready → committing/receiving
→ complete/closed. Claim commit-vs-ready-cancel under one bounded state lock before
either sends; whichever claims first determines the branch. Write sequence updates
are under one bounded write lock. During commit/result streams there is one reader
owner; concurrent cancel sends its exact frame then waits on a bounded event, never
calls read. The reader consumes cancellation acknowledgements and delivers them
once, with exact dialogue/exchange/sequence checks, while preserving stream frames.
Do not hold state/write locks while waiting for peer/ack. Duplicate/concurrent
cancel attempts serialize with a bounded control lock and cannot share one stale
acknowledgement; a terminal close wakes waiters with a fixed failure/terminal state.

Pin the observable ordering in tests: before a valid cancel acknowledgement is
fully authenticated/validated, transport failure yields no claimed accepted
cancellation. After the reader commits a valid acknowledgement to its one-shot
control slot, later terminal/EOF/close must not replace that slot with a guessed
`False` or make a waiter wait again. The waiter returns that exact cancellation
observation; a cleanup failure remains a separate local dialogue failure recorded
for the commit/exchange owner. In the ready-cancel arm, which itself owns final
close, expose a private sanitized cleanup exception retaining the exact immutable
`ProviderSendCancellation` in a `cancellation_observation` attribute rather than
silently succeeding or erasing it. Define that subclass locally in
`provider_send_client.py` over existing `ProviderSendError`; it adds no wire field,
retry, independent authority or general exception payload. Its only allowed
message is `provider send cleanup failed after cancellation observation`.

The service retains IPC owner and live HTTP lease through cancellation delivery,
final response stream acknowledgement and cleanup. Ready-cancel's accepted result
requires the pending exchange already removed. During running HTTP the request
sets the existing cancel event and shuts down the registered HTTP connection/socket
before its acknowledgement; reported phase comes from the existing first-write
event, not the ack's delivery. After terminal HTTP observation the result stream
may acknowledge a too-late cancellation according to existing service state; it
cannot assert that already observed remote work was undone. IPC owner close must
not trigger a fresh provider send or discard the lease's possible-write phase.

The service keeps its existing single HTTP thread/lease issuer and polls
`connection.read_duplex(..., idle_timeout_ms=10)` while also checking its completion
queue. A silent peer must not prevent a completed HTTP exchange from producing a
result; a cancel frame must not wait behind a blocking full-deadline read. Once
the service finishes polling it alone reads any response-stream credit/control.
Cancellation already framed but not processed before HTTP completion is handled
by the result-stream grammar, or by deterministic terminal closure when there is
no stream. No remote cancellation-success claim follows from a local close.

The only deadline shrinks: caller cap, retained owner end, prepare remaining_ms,
prepare UTC expiry, ready receipt-time bound, commit remaining_ms and HTTP lease
end. Keep Task47's checks around real vault locks/SQLite/custody/first HTTP write.
There is no new cleanup, cancellation, per-page or response-transfer window.

Every service exit separately attempts, as applicable: ready abandon, live lease
cancel/HTTP shutdown, bounded thread join, ingress-owner close, and serial-latch
release. One failure cannot prevent later attempts. If the HTTP thread cannot be
joined within the remaining original window, retain its actual lease/thread
ownership, mark send service unusable and mark ingress unusable for further
dialogues; report cleanup failure, not successful teardown or a healthy next call.
It may finish later through its existing owned HTTP cleanup; do not release or
close borrowed vault/root while it still runs. Tests must release blocked fixture
threads in teardown and prove eventual exit; no silent daemonization.

Use existing `ProviderSendError`, `GatewayServiceError`, broker and listener
categories. Local owned-send mappings: deadline → `deadline_exceeded`; malformed
authenticated grammar/identity → `integrity_failed`; unavailable acquisition →
`dependency_unavailable`; cleanup-only fault → `internal_failure`. Preserve a more
specific already observed Task47 cause/phase. No new wire enum or schema field.
Generic owner preserves original broker/listener exceptions; adaptation is at the
gateway engine boundary. Process-control BaseExceptions propagate after cleanup.

Cleanup-only failure must not erase a complete observed HTTP/result body or turn
possible write into `not_sent`: when client exchange has a validated observation,
raise existing `ProviderSendError` with its bounded status/body/media/phase and
cancel flag retained plus `internal_failure`; do not return nominal success. If
no result was authenticated after commit, phase remains conservative
`may_have_sent`/unknown; never fabricate a gateway observation. A service-side
failure after final frame delivery cannot retract peer evidence; close locally,
surface a sanitized failure and never issue a second contradictory result.

## 7. Conditional positive path and finite acceptance

Tests must call the proposed real entrypoints, not a stubbed `prepare`, fake
owner, direct service shortcut or always-denied construction check. Host seams
are confined to tests: temp root/UID/GID, synthetic metadata ownership, macOS
anchored-path/peer sampling. Actual temp files, generation locks/readiness HMAC,
handshake protocol, codec MAC/sequence, Unix socket I/O, stream credit/hash and
close are real. No new production test-mode switch. Explicitly call this
conditional local proof, not Linux SO_PEERCRED/mount/native qualification.

Required independently observable positive sequence on the same ingress instance:

1. Use owned `CredentialGatewayClient.for_gateway` to store a synthetic sentinel
   into a real temporary encrypted `CredentialVault`, including a value requiring
   fragmentation. Query/snapshot its redacted exact metadata on separate owned
   connections; inspect stored ciphertext and absence of plaintext in responses.
2. Create the existing exact `ProviderSendService(CredentialedProviderTransport(...))`
   using that same vault and a test-only loopback binding. Use owned send factory,
   prepare/body/ready/commit/result stream to perform exactly one captured POST.
   Assert zero HTTP before commit, exact `/v1/messages`, semantic request UUID on
   descriptors, body hash/bytes, synthetic auth header only at controlled upstream,
   actual returned SSE bytes and phase. Close owners and join every thread.
3. Bodyless Models GET and cursor GET traverse separate owned dialogues; assert
   empty bodies, exact escaped cursor and request-bound descriptors. No provider
   network call or credential import outside test data.
4. Retire the same credential over the vault branch, then a new send must produce
   the existing observed custody refusal and zero additional HTTP. This proves
   both routes share the actual vault, not two unconnected mocks.

Finite proof groups for the plan (parameterize meaningful boundaries; no broad
stress/rerun loop):

| Group | Required assertions |
| --- | --- |
| G1 profile | Exact literals agree with static cp-provider; old raw fixture names unchanged; missing real root/unsupported platform fails closed; no path/peer/callback override. |
| G2 owner issuance | Real connect/accept return exact owners; retained deadline includes handshake; inject failure after each newly owned resource and timeout restoration; every finite resource attempted, primary preserved. |
| G3 duplex | Reader silent while another thread writes succeeds; completed HTTP with silent core still returns; second reader rejected without bytes consumed/closing first; idle returns None only before prefix; partial prefix/body EOF/MAC/replay/oversize close. |
| G4 owner lifetime | Close wakes blocked I/O, attempts all resources despite each close failure, repeated close harmless, generation rotation denied until last owner closes, accepted stream survives listener close, no claimed extension fence. |
| G5 vault routing | Through the actual ingress, valid canonical `store_at` payloads of 16,383 and exactly 16,384 authenticated bytes dispatch/store successfully; a valid 16,385-byte plain request closes with zero `_dispatch`/store calls and no record, while those identical 16,385 logical bytes sent as correct credential fragments store successfully. Preserve max secret/102,400-byte logical cap, fragmented snapshot, invalid fragment index/count/ID/correlation/truncation/extra fields and no partial store; legacy refusals and v2 sanitized error codes remain exact. Measure original payload length; no re-encoding as the oracle. |
| G6 branch exclusivity | Prove the common pre-decode guard on initial payload lengths 24,576 (passes that size guard; remaining grammar still applies) and 24,577 (zero JSON decode/dispatch). Oversized initial and continuation fragments close before their decode; malformed fragments remain refused. For both closed legacy-refusal arms prove the exact 16,384-byte plain boundary retains unsupported response, and 16,385 bytes closes before `_dispatch`; v2 and semantic prepare share the same ordinary bound. Wrong first type/correlation/schema, stream/commit/cancel first, fragmented prepare, v2→send and send→v2 switching never reaches the other handler or HTTP; first frame consumed/decode once, continuation not lost. |
| G7 send path | Real encrypted POST and Models cursor path above, exact original grammar/descriptors; wrong semantic request ID/prepare hash/exchange/seq, swapped credential pin and revoked record fail at existing boundary without a second send. |
| G8 races | Deterministic barriers for ready cancel vs commit in both orders; cancel during blocked HTTP headers and body; cancel during response stream; two concurrent cancels; terminal/EOF wakes waiters. Assert one reader, monotonic phase and no deadlock/resend. |
| G9 deadlines | Acquisition/handshake delay, body receipt delay, ready delay, shorter commit, vault contention and partial frame consume one end. No polling/ack/join extends it; local loopback count/lease state prove no late send. |
| G10 failure precedence | UUID/header failure after acquire, write/read/decode failure plus close failure, cleanup-only fault after valid result, HTTP-thread join expiry and subsequent unusable ingress. Keep observed bytes/phase and process-control primary; all local errors sanitized. |

Reuse existing `provider_semantic_harness.controlled_upstream` and encrypted-vault
fixtures rather than a new HTTP implementation. Assertions use independent literal
body/path/descriptor/session values, safe stage/error categories and captured
call counts. Do not record secrets/paths/raw headers in diagnostic logs.

Run the three new modules plus the directly affected existing suites once after
changes settle: `test_provider_send_gateway.py`, `test_credential_gateway_service.py`,
`deploy/tests/test_worker_listener.py`, `test_provider_semantic_owned_connection.py`,
and `test_provider_semantic_vertical.py`. Root's plan may name narrower regression
nodes when their coverage is explicit. Preserve existing runtime/ledger/replay
assertions in the vertical suite; it remains the **old conditional** path, not
evidence that cp-provider works with admitted runtime. Broader final branch/native
checks are separate decisions; no tests were run to author this draft.

## 8. Historical reliability observation and preservation

Carry forward the controller's exact Task49 ruling: accept worker ownership on
reviewed current bytes and final20 **615 passed / 1 inherited warning**, while the
intermediate nominal fresh-catalog failure remains historically unexplained.
Only two GET captures existed instead of four; distinct terminal identity alone
was insufficient. The original peer/terminal diagnostics were unavailable and the
exact temp evidence is gone. A later pass and the concurrent-cancel repairs do not
explain that nominal failure. It is not a waived current code finding and not a
claim that the historical cause was fixed.

Connected acceptance must retain the existing four-capture + distinct-terminal
test and its sanitized terminal/peer diagnostics. On recurrence, preserve those
diagnostics and exact temporary evidence before **any further pytest run**, then
diagnose the failing stage. No retry, longer budget or flaky label is added. This
observation remains open for connected integration and whole-branch/native-fit
review; it blocks release if a recurring fault is unexplained.

No changes to private metadata/profile identity, source18/release-source44 bytes,
B vector/version/manifest, verified installation history, legacy tool schemas,
semantic wire hashes, domain schema exports, same-store journal/CAS, budgets,
output capture, runtime operation replay, or provider/account/model UI are in this
unit. Historical read paths retain original evidence/signature integrity without
fresh source/probe/current-clock admission. Old records are neither migrated nor
reinterpreted as full semantic conformance.

## 9. Exact downstream runtime identity join (deferred, not implemented)

The future behavior is not `expected = observed`. Introduce the following only
with the corresponding real same-store admission/C/binding producer, under its
own reviewed ownership:

```python
# Proposed future module: app/extensions/provider_runtime_admission.py
# Nonconstructible value; no caller dict, passed boolean, arbitrary source factory.
class ProviderRuntimeAdmission:
    installation_ref: EntityRef
    binding_ref: EntityRef
    binding_head_hash: str
    qualification_ref: EntityRef
    instance_id: str
    slot_number: int
    geometry_sha256: str
    service_identity: str
    core_boot_id: str
    # Immutable expected worker ChannelSpec + exact admitted artifact/profile joins.

def resolve_provider_runtime_admission(
    prepare_service, db, *, config_ref: EntityRef, operation_ref: EntityRef,
    core_boot_id: str
) -> ProviderRuntimeAdmission: ...

def require_current_provider_runtime_admission(
    prepare_service, db, admission: ProviderRuntimeAdmission
) -> None: ...
```

Producer runs inside the already active same-store writer, calls the mandatory
composed prepare journal exactly once, and joins the **current** verified semantic
installation/head to its retained candidate/descriptor/lineage/platform and
original geometry. It verifies exact active binding slot/head/revision, current
semantic qualification, purpose/grants and connection handle against the current
config/request, with established lock order. It derives slot/channel/service/UIDs
from geometry and descriptor equality using `extension_channel`; the observed
worker cannot select them. Parsed geometry or `VerifiedInstallationView` alone
does not construct this value. Missing semantic artifact/C/binding denies before
worker connect, credential delivery or budgeted send.

The exact producer will need canonical binding-head/qualification accessors added
in that same unit; today's dictionary `ProviderSemanticAuthority` is not a
substitute. `ProviderSemanticContextLoader.load` consumes the resulting retained
admission and repeats the current check before dispatch/each catalog page and
before committing provider send. It supplies expected worker identity to
`ProviderPortClient.for_extension_slot`; gateway identity is the fixed code-owned
gateway spec qualified by the future gateway bootstrap, not credential config.

`ProviderAttemptTransport._authenticated_session` becomes a verifier taking
`value`, `expected_spec`, `expected_requester_boot_id`, and the exact just-acquired
owner's authenticated session/readiness binding. Check all eight observation
fields: protocol/channel, connection ID, both boots, sender/receiver/direction.
Protocol/channel/services/direction come from admitted geometry/fixed gateway
profile; requester boot comes from core startup. Connection ID is checked against
that exact freshly owned authenticated session; it is not predictable from the
installation. Responder boot comes from fresh authenticated readiness at connect
and must remain bound to that owner/session, **not a historical stage boot**.
For the extension side require owner currentness fences; for generic gateway do
not assert such fences unless a separately adopted bootstrap/lifetime contract
provides them. Worker and gateway connection IDs must differ. Observations remain
evidence sealed under existing Task47 records, not independent admission.

The future gateway expectation also checks its exact code profile and local boot
against the owned acquisition; the new fixed profile must never be accepted by
rewriting the old Task47 raw fixture values or adding them as production aliases.
Historical record reads need no new connection and preserve their original tuples.

Before that producer can return a value, new semantic metadata/image/source/
release interpretation and full-operation evidence must be admitted with their
own literal identity. For the same stable extension identity, ADR-014 requires
distinct-service replacement while old service remains reachable, handshake and
qualification, then binding CAS, rollback retention and explicit later retirement.
Current provider verification has a one-record capacity guard; do not silently
increase cap1 or label an unrelated new identity as replacement to evade it. A
future capacity/lifecycle amendment must preserve historical heads and prove the
finite replacement case. No automatic binding or second registry.

Actual release originals, native observer/trust/current source provisioning,
two-platform image inclusion/execution qualification, legitimate user accounts,
account canaries and full browser journey are independent remaining evidence.
This design supplies none. The safe next unit can proceed conditionally without
those authorities; actual activation cannot.

## 10. Self-review and handoff

The recommendation contains a real owned frame/HTTP/vault path, identifies the
only owner guarantees available, preserves old fixture identities and credentials,
and has a single fragmentation grammar/reader. Runtime/admission work is a named
dependency with exact producer/consumer joins, not a hidden always-denied endpoint
or a fake passed authority. Cleanup-only observations and commit/cancel races are
explicit; host simulation, catalog uncertainty and native gates remain visible.

No genuine missing design choice requires a user question under the delegated
recommended-decision policy. Root should obtain independent design review of the
finite interfaces and proof set, particularly original-deadline acquisition,
router fragmentation, exact owner/session checks and race/cleanup linearization.
After adoption root writes the finite plan. No implementation plan or product
changes are made by this draft.
