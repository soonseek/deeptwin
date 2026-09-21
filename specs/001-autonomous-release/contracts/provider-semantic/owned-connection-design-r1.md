# Task48 — owned semantic-worker connection prerequisite

**DRAFT for controller and independent design review, 2026-09-21.**
This is a design, not implementation authority, a TDD plan, artifact admission,
native qualification, release approval or browser activation. Task47 is accepted
offline as recorded in `task-47-acceptance.md`; that acceptance is not reopened.
**R1 design revision:** addresses preflight I1/I2 and M1/M2 under root's explicit
rulings; pending the same reviewer's re-review. Root selected choice A. This revision
does not authorize product edits or assert those future tests have passed.

## 1. Recommended next unit and user outcome

Implement the missing **owned extension-connection path in the existing semantic
worker/client**, including cancellation-compatible reads, exact deadline propagation,
currentness checks and complete cleanup. Demonstrate all five existing semantic
operations through actual authenticated owned connections. Keep the same
`ProviderPortService` semantic engine and codec; add no second worker implementation.

This is the smallest behavior-bearing prerequisite to a packaged semantic service.
Its direct downstream consumer is the future semantic worker service, which must
open its own versioned metadata source, bind the slot listener, accept an
`ExtensionConnection`, and call this same engine. Its core-side downstream consumer
is the future admitted slot connector and `ProviderAttemptTransport` composition.
The next unit ends before a new metadata profile, listener executable, image,
candidate, source bundle or native authority is introduced.

The intended product remains web-based OSS with no end-user CLI. Claude remains
API-only; mandatory end-user-owned Codex subscription and explicitly optional Codex
API work remain separate. Framework-owned tools/multimodal artifacts, graph
generation and criticism, human alternatives/philosophy inquiry, actual paired
prior-queue replay, three-plateau stopping and human version promotion are unchanged.
An owned transport does not authorize design/critique work to masquerade as
`execution-model-step`, nor create a user environment before graph approval.

## 2. Evidence and authority used

Read canonical `provider-semantic-execution.md`, its selected design §§2–9 and
literal appendix §§3,7–11, `provider-installation-verification.md`,
`provider-conformance.md` (especially §§3–7), `provider-image-lineage.md`,
`private-provider-worker.md`, and ADR-014 in `decisions.md`. The canonical master
retains the adopted request-ID, uppercase currency and failure-class corrections.
This proposal changes none of their wire/hash/record semantics.

Concrete code observations:

| Existing surface | Current behavior and consequence |
| --- | --- |
| `workers/provider_port_service.py::serve_authenticated(sock, codec, deadline=...)` | Actual five-operation engine takes raw transport; router and streams directly read/write it. No metadata owner or extension connection is retained. |
| `workers/provider_port_client.py::_open/_close` | Factory is called without the already-created absolute deadline and returns `(sock, codec)`; cleanup does not own a populated-generation fence. |
| `provider_port_client.py::_read_authenticated_frame` | Reads prefix/body with `select/recv`, then calls `FrameCodec.decode`; this intentionally avoids holding codec's shared lock across peer waits so concurrent cancellation writes can proceed. |
| `workers/listener.py::ExtensionConnection` | Owns socket, codec, generation lease and populated-generation fence. `recheck()` verifies current generation, authenticated readiness record, socket identity and mount policy. Its read/write do not themselves call `recheck()`. Close attempts fence, codec, socket, generation, preserving the first failure. |
| `workers/broker.py::FrameCodec.read/write` | Both hold the same RLock during wire I/O. Replacing the special client read with ordinary `connection.read()` without considering that lock can stall the cancellation path. |
| `workers/provider_service.py::ProviderWorkerService` | Private transformer opens fixed metadata before listener publication; owns a service lock/source/listener; accepts an owned connection and measures image metadata during phases. Its service/main/identity are not the semantic engine. |
| `workers/provider_worker.py` | Fixed private entrypoint only, with stop unwinding and sanitized exit codes. Repointing it would falsely change the meaning of existing measured private identities. |
| `workers/provider_send_client.py` / `provider_send_service.py` | Accepted gateway prepare/commit/cancel/result engine also uses raw sockets/codecs; service owns HTTP exchange/lease lifetime, but not an outer listener connection. |
| `listener.AuthenticatedConnection` | Generic gateway-capable connection retains generation/socket/codec; unlike ExtensionConnection, it has no `recheck`, populated-generation fence, retained listener record or extension mount policy. Do not claim those properties by wrapping it. Its current close can skip socket close if codec close fails. |
| `workers/credential_gateway_service.py` | Existing separate custody operation service is not a first-message router for semantic sends. Adding send dispatch here requires a new reviewed composition decision. |
| `runtime/provider_attempt_transport.py` | Worker observations are explicitly checked against `task47-semantic-worker` / `semantic-worker`, gateway against `task47-provider-send` / `credential-gateway`. Real `extension_channel()` derives per-slot channel/service identity; no admitted geometry-to-session mapping is present. |

The last row is a hard downstream integration dependency. An owned-worker test must
not rename the real slot to the Task47 fixture identity, loosen session comparison,
or claim the unchanged dispatcher already consumes the deployed slot. Retain its
accepted offline regression separately.

Exact downstream callsites are worker model-step at
`provider_attempt_transport.py:312–315`, gateway model-step at `:355–358`,
worker catalog at `:588–591`, and gateway catalog at `:612–615`; the shared checker
is `:85`. Both clients retain the observed tuple
`(protocol_id, channel_id, connection_id, requester_boot_id, responder_boot_id,
sender, receiver, direction)`. A future adapter must validate the complete expected
role/direction/boot relationship, not select an expected identity from that observation.
For the worker, verified same-store provider request/receipt/installation history
already joins `instance_id`, exact retained `geometry.json`, slot ID, descriptor,
and service. `provider_geometry.slot(n)` and `deployment.contracts.slot(I,n)` derive
`ext-{I}-{n:02}` / `cp-ext-{I}-{n:02}`, UID/GID and pair GID; unchanged
`extension_channel()` turns them into the actual ChannelSpec. Current listener
record and proven handshake then supply current boot/generation observations;
historical stage boot is not assumed current. This must be joined to the current
admitted installation/binding, whose genuine semantic producer is still missing.
The semantic `connection` projection currently binds provider/account/credential
revision/record, **not** gateway IPC topology. Gateway expected transport identity
therefore needs its actual provisioned core/gateway channel source and owning
service composition; neither provider source18 nor that credential snapshot alone
is evidence for a new gateway channel. No producer is invented here.

## 3. Choices and tradeoffs

| Choice | Benefit | Cost / ruling |
| --- | --- | --- |
| **A. Owned semantic worker connection prerequisite (recommended now)** | Real behavior, small source ownership set, preserves accepted engine and all installation history; solves a concrete prerequisite for actual service assembly. | Does not install, measure, qualify or register the semantic worker. Gateway and geometry-to-session composition remain explicit dependencies below. |
| B. Narrowly versioned new semantic candidate admission | Distinct semantic identity, fresh suite and release evidence can coexist with historical private records; reuses the same DomainStore and lifecycle. | Changes fixed identity/lineage/source18/geometry joins, receipt/stage/release policy and bounded journal admission. A new extension identity is not automatically selected or bound. Cannot silently increase cap1 or use a second registry. |
| C. Explicit replacement under the existing stable extension identity | Preserves one logical extension lineage and uses ADR-014 replacement/CAS semantics. | Must keep the old service reachable while staging a distinct service identity, qualify before binding supersession, preserve retention and explicitly retire later. Current private finite admission path is not a completed replacement implementation. In-place repointing is disallowed. |

Recommend A now; favor a narrowly versioned profile for the subsequent admission
contract, with B versus C determined by the actual extension identity decision.
If semantic work is a successor of the **same stable extension identity**, use C;
a new profile/version does not permit fresh-stage to evade replacement. If it is a
genuinely different extension identity, B may coexist but still competes only through
the exact five-field binding key and expected-head CAS. Both reuse existing
same-store records, heads, backward ancestry and transaction ownership. Neither
choice authorizes multiple provider admissions inside the existing cap1 profile.

## 4. Exact proposed next-unit interfaces and ownership

Names below are proposed, not existing APIs. All paths are relative to this worktree.

```python
# app/workers/listener.py: new method, existing owner; not a socket getter
class ExtensionConnection:
    def read_duplex(self, *, deadline: broker.Deadline) -> broker.ReceivedFrame: ...

# app/workers/provider_port_client.py: concrete fixed-slot construction
class ProviderPortClient:
    @classmethod
    def for_extension_slot(cls, *, instance_id: str, slot_number: int,
                           requester_boot_id: str,
                           deadline_ms: int = 30_000) -> ProviderPortClient: ...

# app/workers/provider_port_service.py: one dialogue, ownership transfer
class ProviderPortService:
    def serve_connection(self, connection: listener.ExtensionConnection,
                         *, deadline: broker.Deadline) -> None: ...
```

`for_extension_slot` derives the exact root/spec using unchanged
`extension_channel(instance_id=..., slot_number=...)`. No path, socket, metadata,
success callback or expected-native-facts argument. The factory checks selectors
and boot ID but grants no deployment/admission authority. Its private connector
calls `_connect_extension_authenticated(root, spec, requester_boot_id=...,
deadline=original_deadline)` for every new operation, returning the actual owner.
Future production assembly must obtain those selectors from the exact verified
installation and current binding, not a browser request or environment override.

The existing constructor/direct unit seam and raw `serve_authenticated` entry remain
available with their existing signatures for accepted offline callers. They are not
promoted into a deployment path. Internally, both paths feed the **same** semantic
dialogue engine through private read/write adapters; no duplicated business logic
or alternate parser. A new private `app/workers/semantic_connection.py` can house
those adapters to avoid service/client cross-imports. Its owned adapter accepts only
the exact `ExtensionConnection` type; no public arbitrary adapter factory.

Ownership transfer rules:

1. Connector retains everything it acquires until it successfully returns the owner;
   failed connect unwinds with the existing listener guarantees. Client takes ownership
   immediately on return, before deadline/type/post-open checks can fail.
2. `serve_connection` takes ownership at entry of an exact connection, including the
   deadline-validation failure path. Caller retains ownership of its listener and
   any future metadata source. Reject non-owner types without claiming to own them.
3. Before connect, compute the minimum of the client cap's original monotonic end
   and the optional trusted caller's absolute monotonic anchor. That caller anchor
   already includes the canonical request/configuration and runtime bounds; this
   adapter creates no wall-clock conversion or new authority. After acquisition,
   also take the minimum with the owner's retained deadline. The service takes the
   minimum of its supplied deadline and retained connection deadline. Connect,
   handshake, frames, streams, cancellation and cleanup share those bounds; parsing
   config or a first frame never creates a new time window. See §4.3.
4. Owned adapter retains a strong reference to the whole owner throughout the
   dialogue. It never exports `_socket`, `_codec`, generation or fence. Every frame
   write/read is fenced before and after, including all stream controls and the final
   batch acknowledgement. Before publishing/returning a complete observation or
   proposal, the sole reader performs the final owner/deadline checkpoint. A different
   control waiter returns the already-committed observation under §4.1, without
   rechecking an intentionally closed owner. Image measurement is not supplied here.
5. One reader owns frame assembly; writes remain serialized by the existing protocol
   lock. `read_duplex` performs bounded prefix/body acquisition without the codec's
   shared lock during waits, enforces the exact codec frame cap before allocation,
   then calls the same authenticated `decode`. It does not parse unverified payloads.
   Add an owner-local nonblocking read exclusion shared by ordinary `read` and
   `read_duplex`; a second simultaneous reader is refused, never consumes a prefix.
   Close must not wait for that reader lock. The helper stays inside listener ownership,
   where private fields are already held; do not re-export them to clients.
6. Check currentness before/after the entire frame and after final stream completion.
   A blocked peer remains bounded by the original deadline; this does not claim
   instantaneous detection of an external mutation during a syscall. A post-read
   fence failure discards that frame and cannot become a successful semantic result.
7. Every terminal/error/cancel/abandon path attempts owner close once through one
   detached closed latch. Preserve the primary BaseException; without a primary,
   surface the first cleanup failure after attempting all resources. Do not close
   the borrowed listener/source from a one-dialogue engine. Do not manufacture a
   semantic success or a new send from a close failure.

The service's new entry is deliberately a **connection-consuming service seam**,
not a fixed-image worker main. Testing an accepted connection exercises authentic
frames and lifetime but cannot claim metadata/image identity that has not been built.

### 4.1 Control observation linearization and cleanup — I1

The existing `_read_owned` publishes `pending["observation"]` and sets its Event
before raising StreamCancelled on accepted cancellation. The awakened `control`
waiter may run before or after `begin`/`observe` closes the owner. R1 therefore fixes
the acknowledgement's linearization point as follows:

1. The sole frame reader authenticates the frame, validates the entire closed
   control-result payload and all dialogue/request/sequence joins, then runs a
   final deadline → currentness → deadline checkpoint.
2. It atomically commits one bounded, detached pending outcome (observation or
   sanitized error) and signals that pending Event. The observation commit is the
   linearization point. Sequence/cancel-latch and pending outcome updates are
   serialized; readers/waiters never see a half-filled outcome or two publications.
   A short pending-state critical section does no I/O, fence, parsing or cleanup.
   Recheck the deadline before committing success after any lock acquisition.
3. If validation/currentness/deadline fails before publication, commit no success:
   wake the waiter with the sanitized local error. The reader retains its primary
   exception, detaches the failed owner and attempts every close. Unexpected
   BaseException retains identity on the reader path; the other thread receives
   only the fixed local failure, not the exception's message or traceback.
4. A waiter consumes the committed outcome after Event synchronization. It does
   not recheck the owner or deadline to reinterpret a previously committed
   observation. Thus an acknowledgement committed in budget is not made invalid
   merely because the waiter is scheduled after close or after the deadline.
   No Event means the wait remains bounded by the original deadline; timeout
   marks the channel unusable, wakes/stops its reader through owner close and
   grants no resend. Cleanup cannot overwrite an already-committed outcome.

Accepted cancellation is an immutable **observation of acknowledgement**, not
cleanup completion, remote rollback or a guarantee every local call returns
successfully. Explicit schedules and root's refined ruling:

| Schedule | Acknowledgement and local failure behavior |
| --- | --- |
| Reader publishes; separate waiter returns before reader closes | Waiter returns the bounded acknowledgement. Reader raises/preserves its StreamCancelled primary and attempts all cleanup. A later close failure cannot retract that observation or replace the primary. |
| Reader publishes and closes; separate waiter resumes afterward | Waiter returns the same committed acknowledgement without checking the now-closed owner. Reader reports/preserves its own failure independently. |
| `control()` acquires `owner_lock` and is itself the sole reader | It commits the acknowledgement, then owns immediate close/detach. If cleanup succeeds, return the acknowledgement. If no primary exists and cleanup fails, that same call surfaces the first sanitized cleanup error, marked locally as occurring after acknowledgement observation. The observation is not rewritten to cancel rejection or remote rollback. |
| Pre-publication frame/fence/deadline failure | No successful outcome is published. The waiter receives the fixed error; reader cleanup preserves its primary. |

The self-reader case is an explicit correction to an overbroad reading of “waiter
always returns committed observation.” Current `control():419–439` can both read
and close in one call; it cannot return success and raise a cleanup error in that
same invocation. R1 chooses immediate error delivery. Do not defer cleanup errors
to a later `abandon()`: the runtime already calls abandon in `finally`, where a
delayed error could replace an unrelated primary/result. No new helper thread,
background finalizer, reconnect or cleanup-error queue is introduced.

If a concurrent control failure loses the race to a committed observation, it may
close the channel but must not mutate that outcome. If a channel fails while a
control is pending and no observation committed, publish the fixed error and signal
it as part of failure ownership. All publications use the same one-shot pending
state, not competing assignment from arbitrary callbacks. A timed-out state-lock
acquisition latches the channel unusable and cannot authorize success; publication
logic must check that latch before committing. Lock holders do only finite local
state operations and never wait for readers, writers, close or Events.

### 4.2 Acquisition guards and all retained owners — M1

The accepted connect-side unwind already attempts every acquired resource while
preserving the primary. Do not assume the accept side does: its sequential close
currently allows an early failure to skip later handles, and its newly-created
codec is not independently tracked if `_extension_connection` construction fails.
Within the already-scoped `listener.py`, initialize and track **socket, codec,
populated-generation fence and generation lease** as distinct acquired resources.
Before construction, the acquisition scope owns them. Transfer them only after a
fully initialized exact owner has successfully been produced, clearing all four
local ownership entries together. On any earlier failure, detach the finite local
set and attempt every close, preserving the active primary. On any later failure,
close the returned owner; never close the borrowed WorkerListener as a substitute.

Immediately guard the client owner returned by `_open`, before UUID creation,
descriptor construction, frozen-content encoding, channel/lock/stream construction
or post-open deadline checks. Move `begin():213–234` under that ownership guard.
Once `observe` selects the active exact channel, include its pre-read raw/status/
exchange validation and descriptor/UUID work (`:293–302`) under the same guard.
Idle `execute` has its own post-open UUID window and must also be covered. `control`
must initialize its pending local before a fallible step so final cleanup cannot
raise an unbound-local error or clear another operation's pending slot.

Generation tests account for **every** holder: WorkerListener, accepted peer,
requester owner, their generation leases and populated-fence secret descriptors.
Closing one semantic owner does not imply replacement succeeds while another
holder remains. Assert replacement refusal with each remaining holder, then
release all fixture-owned holders explicitly before proving replacement succeeds.
The service never closes its caller's listener to make that assertion pass.

Preserve the existing readiness distinction: connection `recheck` verifies retained
authenticated record **content**, current socket identity, generation and mount;
it does not retain the original readiness inode. Identical readiness bytes at a new
inode are rejected by **accept** against WorkerListener's retained inode. Tests may
not claim existing connection-level rejection of that same mutation. Changed record
content/MAC, socket identity and generation have their own connection-level vectors;
no new readiness-inode retention field is proposed.

### 4.3 Adapter checkpoints, locks and sanitized failures — M2

The private owned adapter has one stored effective absolute Deadline and exposes
internal `checkpoint()`, `read()`, `write(...)`, and `close()` operations to the
shared dialogue engine. `checkpoint()` is exactly deadline.require → owner.recheck
→ deadline.require; no authority callback. Read/write checkpoint before forwarding
and after completion, and the semantic parser/reader checkpoints again immediately
before publishing a control result, proposal or final observation. The same checks
cover idle-operation result streams and final ACK. The caller monotonic-anchor
contract is §4 rule3; no newly parsed request/config extends it.

Channel write-lock and operation-owner-lock waits use the remaining effective
deadline and check it immediately after acquisition. Reentrant acquisition by the
same owner is allowed; lock timeout is DeadlineExceeded. Electing a control reader
and the connection-level reader exclusion remain nonblocking. Pending-state locks
hold only finite state operations, with bounded acquisition; no lock is held while
waiting for an Event. All Event/select/socket waits use remaining time. No5s or30s
fallback applies after expiry, including lock acquisition before cleanup.

Avoiding the new read lock alone does not bound close: existing codec.close takes
the codec RLock, which ordinary codec.read/write may hold during socket waits. The
concrete listener-side resolution is to latch closed/detach once, then attempt an
owner-internal `socket.shutdown(SHUT_RDWR)` to wake socket waits **before** acquiring
the codec close lock. Shutdown is interruption, not a change to final ownership
release order: attempt fence → codec → socket → generation, retaining all failures.
Only OSError errno ENOTCONN/EBADF from shutdown is treated as an already-disconnected/
closed condition; any other shutdown failure is retained as the first cleanup
failure while all closes are
still attempted. No private socket leaves the owner and no helper thread is used.
Ordinary owner read/write and new duplex read must cap passed I/O deadlines by the
retained owner deadline; the semantic adapter additionally supplies its smaller
effective bound. The new semantic route always uses duplex receive.

After shutdown, an ordinary read or backpressured write unwinds and releases the
codec lock; the original deadline is also its bound if shutdown is ineffective.
Do not claim Python forcibly preempts a hung native syscall or a suspended thread.
Deadline checks after lock/cleanup detect an overrun and prohibit success; they do
not turn an overrun into proved bounded completion. Controlled ordinary-read/close,
backpressure/close and failed-shutdown tests must observe actual thread completion,
all resource attempts and original-deadline behavior. A surviving thread fails the
local fit proof; no detached worker or fabricated cleanup success is acceptable.

Failure mapping is local, not a wire/schema extension. In `semantic_connection.py`,
use one private ProviderSemanticError subclass with fixed sanitized codes
`owned_connection_unavailable`, `owned_connection_cleanup_failed`, and
`owned_connection_cleanup_failed_after_control_observation`:

- ListenerError from connect/accept/currentness maps to unavailable, raised from
  None after all necessary cleanup; never expose paths/native exception text.
- BrokerError, including DeadlineExceeded, keeps its established sanitized class
  and effect semantics. Value/protocol errors keep ProviderSemanticError behavior.
- A first cleanup failure with no primary maps to the cleanup code; the self-reader
  case uses the after-control-observation code only once acknowledgement committed.
  That fixed code conveys post-observation local failure, not remote rejection.
- With a primary, cleanup cannot replace it. Unexpected BaseException is re-raised
  as the same object after all close attempts. Known ListenerError translation is
  the explicit API-boundary mapping above, not accidental cleanup masking.

`begin`/`observe`/`control`/`abandon` and the service propagate these sanitized local
errors. Existing `execute` catches ProviderSemanticError/BrokerError and keeps its
existing failed result shape for ordinary mapped operation failures. Do not swallow
an owned cleanup failure into that ordinary result: explicitly re-raise the private
cleanup subtype before the existing catch so first cleanup failure is surfaced.
For an unexpected primary, execute still propagates it unchanged. Raw/direct
constructors/signatures and their established behavior remain compatible; these
new codes describe the owned route, not a new public protocol enum.

Owned idle operations must replace the raw FrameCodecTransport call at client
`:484–486`; service `_send_final`'s raw fallback at `:347–350` must likewise use the
private owner adapter through existing ConnectionStreamTransport. Merely passing
the adapter as a FrameCodec is invalid because that transport requires exact codec
type. No artifact-stream module change or unfenced idle branch is permitted.

## 5. Runtime and error behavior within this unit

`begin`, `observe`, `execute`, `control`, `abandon` keep existing request/result
shapes. The owned route uses the existing frame router, request IDs, correlation,
sequence and bounded artifact protocol. Capabilities, status and cancel retain
their existing non-HTTP behavior; catalog and model_step produce the same proposals
and normalized observations as Task47. No wire discriminator/schema changes.

During input/proposal/result streaming, status/cancel must still be handled by the
single protocol reader and the existing pending-control discipline. A thread waiting
for a frame must not hold the codec lock needed to send cancel. Cancellation cannot
be reinterpreted as remote rollback; disconnect or timeout cannot grant replay.

Connection/generation/readiness/mount drift closes the owned dialogue and propagates
the existing sanitized transport/semantic failure. The engine does not create durable
records or claim the provider did not send. `abandon` never reconnects. Reopening a
client or service loses live operation state; existing core retained terminal and
unknown/no-resend behavior remains the authority. No new recovery writer or table.

This unit does not modify `ProviderAttemptTransport`. Its exact accepted encrypted
gateway/dispatcher/ledger regression must remain green; new worker tests use the
owned path directly. A later composition must add live worker rechecks at gateway
commit boundaries and resolve the slot identity into the current admitted context.
That is not implied by checking currentness while transferring a worker frame.

## 6. Concrete file map

| Proposed source ownership | Change |
| --- | --- |
| MODIFY `app/workers/listener.py` | Owner-local duplex receive/exclusion; accept-acquisition tracking/unwind; deadline capping and shutdown-before-codec-close interruption; same-primary all-resource cleanup. Preserve ordinary connection APIs and all existing fences. |
| NEW `app/workers/semantic_connection.py` | Private frame adapters; owned route retains/fences/closes exact ExtensionConnection; legacy raw adapter preserves old entry semantics. No authority or runtime imports. |
| MODIFY `app/workers/provider_port_client.py` | Concrete fixed-slot factory, immediate guards for all post-acquisition/pre-parse windows, bounded locks, one-shot fenced control publication and explicit self-reader cleanup behavior; original deadline and owner retained across every phase. Existing raw/direct callers remain valid. |
| MODIFY `app/workers/provider_port_service.py` | Ownership-transferring `serve_connection` and shared engine adaptation; same parser/state machine. |
| NEW `app/tests/test_provider_semantic_owned_connection.py` | Real owner/frame/client/service happy paths and drift/deadline/cancel/cleanup vectors. |
| MODIFY `app/tests/test_extension_listener.py` | Focused one-reader/duplex/close regressions; existing listener expectations preserved. |
| MODIFY `app/tests/support/provider_semantic_harness.py` | Test-only context manager for real temporary generation/listener connections with the precise conditional platform substitutions in §6.1; no product import of fixture. |

This is an initial exact source proposal for root to validate before a TDD ownership
manifest. No broker change is proposed: reuse authenticated `FrameCodec.decode` and
its existing cap, with the bounded wire-reading code moved under the owning listener.
No schema exports, release files, private worker/main/metadata, DomainStore, API
registration or database migration is in this implementation unit.

### 6.1 Conditional local fixture contract — I2

The macOS positive path reuses the existing listener fixture's explicitly limited
substitutions. This supersedes the original draft's overly narrow “only mount facts”
wording. Permit only the following test-owned setup substitutions, plus targeted
failure/barrier injection for the enumerated negative/cleanup tests:

| Test-only seam | Exact extent and what it does not prove |
| --- | --- |
| Temporary root and fixture UID/GID | Real temporary PairRootSpec/generation initialization; fixture `ipc_root.METADATA_UID`, process identity sampler and ChannelSpec owner/group fields match the test process. This does not prove deployed service credentials or isolation. Deterministic test entropy supplies actual synthetic HMAC key bytes, not a successful authentication verdict. |
| Fixed-slot factory resolution | Monkeypatch the test process's client-module `extension_channel` binding to return that prepared temporary `(root,spec)` only for the exact expected instance/slot; assert the arguments. Retain slot-derived channel/service/message/profile fields. No product path argument, public factory override, env/test mode or request field is added. |
| Off-Linux socket anchor | Existing test `_anchored_socket_path` replacement uses a short `/private/tmp` alias for the real temporary endpoint, because macOS has no Linux `/proc/self/fd` anchor. Its symlink is fixture-owned and removed on teardown. This does not prove the production anchored connector. |
| Peer verification | Existing test wrappers invoke the actual extension client/server handshake implementations with `verify_peer=False`. All challenge/MAC/session/sequence processing remains real. This intentionally omits kernel SO_PEERCRED verification and proves no native peer PID/UID/GID. |
| Verified-connect seam | Existing test replacement makes a real AF_UNIX connect and returns actual stat-derived socket identity plus peer=None. This exercises the subsequent exact socket identity comparison but is not proof of production `connect_verified`, kernel peers or `/proc` anchoring. |
| Mount sampler | Thread-specific synthetic mountinfo supplies the worker read-write and requester read-only views. The real mount parser/fence comparison executes; the fixture proves conditional comparison behavior, not actual mount namespace enforcement. |

Keep real temporary files, descriptors, generation/shared-flock retention, populated
fences, listener readiness bytes/HMAC, actual accepted/connected ExtensionConnection,
handshake implementations, FrameCodec MAC/sequence validation, socket I/O and stream
grammar. Never patch a parser/owner recheck to return success, bypass the actual
retention mechanism, fabricate received frames or fake the semantic result. A
negative may alter sampler input to trigger a real fence refusal; it may not fake
that refusal's final verdict. Record the enabled substitutions with each local run.

Run positive five-operation/duplex/lifetime tests under this contract and label them
**conditional local owned-frame proof**. They are not native Linux peer/connector,
actual mount, release or C evidence. Separately run an **unmodified production
unsupported-host refusal** check with those monkeypatches out of scope; on macOS the
real platform/peer/anchor path must refuse before any semantic success. Do not skip
all positives, count the peer bypass as a native pass, or use refusal alone as the
positive proof. Future supported-platform repetition is an activation dependency;
no native/container operation or new product override is authorized by R1.

## 7. Dependencies beyond the chosen unit — explicit, not hidden wiring

| Dependency | Required concrete work / downstream consumer | Now? |
| --- | --- | --- |
| Owned semantic worker frames | §4 interfaces consumed by new semantic worker service and admitted slot client | Recommended next implementation |
| Semantic metadata and fixed-image service | Distinct code-owned semantic build identity/parser/source, source-before-listener acquisition, fresh boot, serial service lock, real metadata reads around phases/final ACK, poison-versus-peer error policy, stop/main cleanup; consumes `serve_connection` | Separate packaging design after this proof |
| Gateway owning connection/service assembly | Deadline-aware connect/accept; retain owner through prepare/commit/HTTP/control/result; all-resource close preserving primary; decide gateway generation/readiness/currentness retention under its own topology; explicit custody/send routing; vault lifetime outlives all exchanges; surviving HTTP thread poisons service and is not reported closed | Separate finite gateway composition prerequisite; no generic owner falsely called an extension fence |
| Admitted runtime session mapping | Current installation/source/slot geometry determines expected worker service/channel; its retained listener/handshake verifies current boots. Separate provisioned core/gateway channel source determines expected gateway identity. Join both authenticated sessions and current binding/permission context; recheck worker at each commit and final currentness boundary, including catalog pages. Replace fixture-only literals only with reviewed exact authority | Required before owned worker enters production dispatcher |
| Artifact admission and semantic evidence | New exact release/profile and suite subject in same store; legacy preservation and capacity migration reviewed explicitly | §8–9 future contract |
| Native/current authority | Real observer enrollment, current native C, binding/head, permissions/connection, compatibility/text scope, reservation provenance | Genuine activation gate; no new authority here |
| Product adapters/browser | Purpose-preserving design/critique input adapters and graph approval flow; ordinary browser path consumes approved provider context | Separate product behavior; existing `(system, user)` callables do not automatically gain execution semantics |

The gateway's generic owner cannot simply be stuffed into a socket tuple. The later
gateway unit must also resolve first-message ownership and resource closure after
failed accept, prepare, READY, commit, partial body, cancel, result transfer and
process stop. No credential is delivered before its existing one-shot commit/lease;
new routing must preserve legacy custody operations and `resolve_for_gateway` denial.

## 8. Admission assumptions that a later version must inventory

These remain unchanged by the chosen unit. They explain why full admission is too
coupled for the next task.

| Fixed assumption / exact consumer | Necessary future change, with history preserved |
| --- | --- |
| `provider_identity_schema_exports.py`, identity v2; `provider_metadata.py` | v2 fixes `claude-text-transform-v1`; new semantic identity must not reinterpret it. New parser/source profile observes exact semantic files; shared six-file measurement alone does not measure imported modules. |
| `provider_lineage.py` / schema export | `extension-build-lineage-v2`, `provider-private-transform-v1`, two ordered platform entries and private identity joins need a separately versioned semantic alternative. Unchanged base provider-port schema bytes remain byte measurements, not full qualification. |
| `provider_source_contracts.py`, `provider_source_schema_exports.py`, `provider_sources.py`, renderer and `deploy/security/deployment-provider-source-recipe-v1.json` | Exact 18 names/order, 524288 aggregate, epoch1, `private-provider-source-channels-v1`, `provider-source-bundle-v1`, worker profile and all embedded digests need a new closed version. Historical source18 is retained, not regenerated as current bytes. |
| `provider_geometry.py`, `extension_channel.py`, `provider_prepare_contracts.py` | Original instance/topology/slots and derived UID/GID/socket/mount/channel/argv must join actual new candidate. Preserve physical slot uniqueness; no independent registry or arbitrary free slot assumption. |
| `provider_stage_observer.py`, `provider_receipt_records.py`, receipt/prepare schema exports | Current identify/probe and expected-stage identity are private-profile joins. Semantic service needs a distinct identify observation/challenge and actual geometry/session comparison, not `implemented_transforms=[catalog,text]` renamed to five operations. |
| `provider_installation_contracts.py` carrier | `application/vnd.deeptwin.provider-installation-v1`, prefix DTPIV1, 32768 header, 50331648 raw bytes, exact role caps/graph closure remain fixed; future semantic packet must either fit unchanged generic roles or introduce explicit new version, never overload roles. |
| `provider_installation_evidence.py`, `installation_release_contracts.py` / sources/render | R1 fixes `provider-private-build-recipe-v1`, `provider-private-source44-v1`, exact launcher, CPython isolated launch policy, locked bases/wheels and precise protected filesystem membership. Semantic imports are outside that44-file set; all executed modules/launcher/source digest and final-image evidence must be recomputed for a new profile. |
| Release policy/evidence | Preserve accepted revision2 / `provider-release-adapter-preflight-r2-dpkg-status-v1`, actual retained Map/status/inventory/provenance/signature joins and authentic release authority. No policy widening to accept missing source/native evidence. |
| `prepare_storage.py`, prepare/provider records, installation records | v4/v5/v6 retain exact DDL/checksums; provider context/profile/epoch and request/receipt/verification caps are finite, verification cap1. New capacity/association requires an explicit same-store version/migration with historical checks, not an edited cap constant or second registry. |
| `provider_conformance_*`, `domain/provider_conformance.py`, `workers/provider_client.py` | Old B suite/requester/oracle/subject/transcript and fresh verified-descendant branch remain private; immutable historical replay does not gain semantic coverage. |

Future migration must recalculate reachable-record/blob closure for the new graph.
The accepted 54,657,024 < 67,108,864 bound is specifically cap1; do not carry that
proof into a graph admitting additional candidates/evidence unchanged. Existing
retained release validation uses retained source and original verification time;
fresh current policy/clock/source re-evaluation cannot rewrite old verified history.

## 9. Full semantics and future conformance subject

Use a **fresh semantic suite identity/version**; proposed label
`claude-api-text-semantic-conformance-v1` is a draft label, not an accepted schema.
Do not increment old private B's coverage in place. Future subject must bind actual
same-store installation/candidate/request/receipt/release refs, exact profile/build
and four schema bytes, selected OCI platform/image/descriptor, geometry/slot/service,
current worker and gateway authenticated observations, native/runtime/framework
context, the code-owned suite manifest/requester/comparator identities, and exact
config/connection/permission/capability/reservation context for exercised semantics.
The reviewed contract must specify historical versus fresh joins and record bounds.

Actual retained observations must cover all five operations, canonical envelope
checks, frozen disclosure and exact request body, encrypted prepare/commit/custody
path, captured HTTP bytes, actual parsed outputs and usage, real dispatcher result
and provisional ledger accounting, cancellation before/after possible write,
restart unknown/no-resend, source/session/config/credential drift and negative
authority/stream cases. The oracle must independently compare actual bytes; no
worker or harness `passed=true` can become authority. Preserve nullable/unknown
usage and reservation; no fabricated zero currency.

Controlled local HTTP and synthetic authority can establish conditional behavior
with that subject structure. They do not establish paid-provider compatibility,
native platform fit or C. Actual account canaries, release originals/scans/signatures,
observer enrollment and current permissions are separate genuine prerequisites.

## 10. Independent acceptance observations for the next implementation

No tests were run for this design. Root should turn these requirements into a finite
TDD plan after review, not mechanically inherit a previous whole-suite command.

| Proof | Independently observable result |
| --- | --- |
| Owned positive path | Temporary real generation/listener and actual authenticated connect/accept yield exact ExtensionConnection objects. Service consumes owner. Exercise capabilities, status, cancel, text and two-page catalog using literal expected proposal/output bytes; verify connection/generation fences survive all intermediate phases and are closed at end. |
| All-frame ownership | Instrument real owner method calls/FD lifetime, not success callbacks. Confirm no raw tuple is extracted; every stream/control/final-ACK frame crosses the owner adapter. After final operation FD count returns to baseline. |
| Cancellation duplex | Hold worker response/proposal/result at deterministic finite barriers while a real cancel/status frame is sent. Prove cancel frame reaches its peer before releasing the blocked response; no second reader, stolen frame or surviving thread. Include partial prefix/body and malformed authenticated frame. |
| Deadline propagation | Consume budget during connect/handshake and before final ACK. Assert remaining time is reduced and no phase creates a fresh30s budget; connection refusal leaves zero leaked owner resources. |
| Currentness negatives | Exercise real populated-generation retention with all holders accounted for (§4.2): replacement stays refused until listener and both peer owners release; fresh generation cannot reuse the old session. Mutate changed readiness content/MAC, socket or generation in temporary fixtures at phase boundaries, including between read and post-read check. Test identical readiness bytes/new inode at accept only. Platform substitutions are exactly §6.1; unsupported-host refusal is separate. |
| Error ownership | Inject primary BaseException at acquisition return, read/decode, write, stream and close; observe all cleanup attempts and primary identity. Without primary, first cleanup error surfaces. Wrong exact owner type, double close and abandon are handled deterministically. |
| Restart/no resend | Disconnect during proposal/observation and after possible external effect in accepted Task47 tests; a restarted owned client does not automatically resume/reconnect. Existing durable replay returns retained terminal or unknown with zero second send. |
| Legacy worker and B | Existing private service/main/metadata/messages/identity/lineage tests and fixed B suite retain their meanings. Run fresh actual legacy B then source-less exact replay/restart; old frozen reply and suite subject remain identical, no worker probe on replay. |
| Installation history | Existing same-store staged1→verified2 and fresh verified B, retained release corruption rejection, source-removed historical read/POST replay, deliberate old-layout refusal checks remain unchanged. Do not claim new semantic installation from these passes. |
| Accepted Task47 regression | Run affected semantic worker/client/cancel/vertical tests on the original real encrypted gateway/store/dispatcher path. This preserves accepted offline behavior but is separately labeled from the new owned-slot proof. |
| Boundary guard | Production imports no fixture; default app still registers no semantic provider or send route. Four base schema bytes, private profile/release/source18 and all persistent schema/record meanings are unchanged. |

R1 adds the following mandatory finite obligations to that acceptance matrix:

| Review obligation | Deterministic proof required before acceptance |
| --- | --- |
| I1, waiter before close | Barrier after fenced publication lets separate control waiter return; release reader cleanup afterward. Accepted cancel remains observed; reader retains its exact StreamCancelled/other primary even when a resource close raises. Every close is attempted and failed owner is detached. |
| I1, waiter after close | Hold waiter after Event publication until reader completes close. Same committed bounded acknowledgement returns with no owner recheck. Include a close failure; reader and waiter outcomes remain independently correct. |
| I1, self-reader | Make control acquire idle owner_lock and read its own authenticated acknowledgement. With successful close, it returns acknowledgement. With first/second close failures and no primary, it immediately raises the first sanitized after-control-observation cleanup error, attempts all resources and detaches; no later abandon error delivery or retry. |
| I1, unpublished failures | Fail payload validation, post-frame fence and final deadline checkpoint separately, before publication. Waiter is signaled with the fixed error, never accepted/succeeded; reader preserves its primary and no stale pending slot can be reused. Also cover control writer failure and waiter timeout with an active reader. |
| I2, conditional scope | Assert fixed instance/slot arguments and enumerate fixture substitutions; verify actual bad MAC/sequence, handshake challenge and real owner/retention failures. Run a separately scoped unmodified unsupported-host refusal. No inferred native compatibility. |
| M1, acquisition | Fail before codec construction, after codec construction/before owner return, and immediately after successful owner acquisition. Add earlier-resource close failure to each path; verify codec/socket/fence/generation are all attempted and original primary retained, listener remains caller-owned. |
| M1, pre-guard client windows | Inject failure in UUID generation, input descriptor/frozen encoding, channel/stream construction, observe prevalidation and idle execute post-open work. Owned connection always detaches/closes; no unbound pending local or lock-release masking. |
| M2, explicit budget | Caller anchor shorter than client cap; owner deadline shorter than caller; expired post-connect, pre/post fence, after lock acquisition, final stream ACK and control publication. No wall-clock recomputation or renewed budget. A waiter scheduled late returns only an already-committed outcome. |
| M2, locks and close | Hold write/owner/pending-state locks through the effective deadline to prove bounded refusal, not success; test ordinary read concurrent with close and write under real socket backpressure. Shutdown wakes I/O before codec close waits; failed shutdown still attempts all closes under original I/O budget. Threads must actually finish. |
| M2, public shape | Listener/currentness errors become fixed owned-connection errors, ordinary execute returns existing failed shape, cleanup subtype propagates immediately (including self-reader post-observation code), and unexpected primary BaseException preserves identity. No path/exception text or false remote cancel rejection escapes. |
| All-frame coverage | Include idle capabilities/status/cancel result stream and service final fallback, not only model router. Every artifact/control/ACK traverses the owner-aware adapter and final publication checkpoint. |

## 11. Unresolved decisions and self-review

**Root selected the worker-only ownership prerequisite.** R1 resolves the review's
I1/I2 and M1/M2 design obligations inside the same seven-file proposal. Same-reviewer
re-review and a concrete root-owned TDD plan remain before implementation dispatch;
this draft does not call the result deployed or ask to enlarge gateway scope.

**Later authority decisions, not guessed here:** whether semantic candidate retains
the old stable extension identity (thus explicit replacement) or is genuinely
distinct; exact versioned admission capacity/migration; production gateway listener
routing and currentness source; authentic release/native observer enrollment and
supported platform measurements. Q1/D2 background proposals are not trust enrollment.
These decisions do not prevent the bounded offline owned-worker proof.

Self-review:

- The chosen unit performs actual semantic operations over real owned frames; it
  is neither a schema-only deliverable nor a wrapper that drops resource ownership.
- Duplex receive is explicit because ordinary FrameCodec.read can block cancellation.
  Shared listener read exclusion needs careful regression coverage; no broad broker
  rewrite or weakening of authentication/sequence limits is proposed.
- R1 makes observation publication distinct from cleanup: separate waiter schedules
  return the committed acknowledgement; self-reader cleanup failure is immediate
  local failure after observation. No deferred abandon error can mask runtime work.
- R1 names accept-side ownership holes, pre-guard client windows, actual shutdown/
  codec-lock behavior, deadline checkpoints and ListenerError mapping. It preserves
  readiness-record versus accept-inode semantics and counts every generation holder.
- R1 enumerates macOS peer/process/anchor/connect/mount fixture substitutions and
  separates conditional local positives from unmodified production refusal. It
  does not label those substitutions native platform evidence.
- Metadata measurement and per-slot runtime identity remain visible unsolved
  deployment dependencies. The draft makes no fake metadata or production C claim.
- Gateway ownership is inventoried but not partially implemented behind an assertion
  that wrapping a socket provides extension currentness.
- Candidate/history/cap1/profile semantics are preserved. Future admission cannot
  repurpose private B or fresh-stage over an existing stable extension head.
- No implementation plan, canonical promotion, native operation, account canary,
  production activation, new dependency or commit is part of this design task.
