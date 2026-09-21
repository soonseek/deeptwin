# Populated requester connection lifetime

Controller contract, 2026-09-19; accepted 2026-09-20 after independent review and fixture-only R1.
Evidence: task-42-report.md, task-42-review.md, task-42-r1-review.md and accepted720 manifest;
strict supplemental checkpoint-RED chronology deviation is retained in the SDD ledger.
Authority: ../spec.md FR-032, ADR-014,
existing extension-worker-probe and provider worker contracts. This is Task42: a bounded repair of
existing requester-side resource ownership before the later provider receipt/observer consumer.
The earlier task-42 advisory filenames describe that subsequent consumer direction, not this
contract's implementation scope. Receipt/migration/observer code is not included here.

## Exact ownership and non-effects

Modify only app/workers/listener.py, app/workers/ipc_root.py, app/workers/broker.py, limited to the
surfaces below and tiny private finite cleanup helpers if necessary. Add only
app/tests/test_provider_stage_connection_lifecycle.py. No existing test edits or new public API.
Only extra evidence write: .superpowers/sdd/resumption-plan/task-42-report.md.

Preserve all signatures, actual protocols/bytes, modes/owners/no-follow, peer/HMAC, deadline,
error classes and dispatch-effect semantics. No dependencies, SQL, source/context/publisher,
schemas, worker semantic operations, credential/billing/qualification/binding or UI changes.
No responder accept/WorkerListener-wide cleanup, initializer/secret generation or rotation,
unused context-manager sweep, FD scanner, generic ownership manager or global close-policy change.
No commits/push, native/root/Docker/real user data/real keys/live model/network actions.
Controlled local temporary FD/socket/lock tests and synthetic secret material are permitted.

## Actual reached chain

_connect_extension_authenticated -> verify_listener -> acquire_generation -> GenerationLease;
then _retain_populated_generation -> PopulatedGenerationFence; broker.connect_verified ->
broker._open_root; endpoint checks/handshake/FrameCodec construction -> ExtensionConnection;
then recheck/read/write/close. Requester success transfers generation, fence, socket and codec
to exactly one completed connection. VerifiedListener and the connection never both own generation.

Task40's _open_absolute_directory/_open_regular_at/_validate_layout and metadata lease changes
are accepted dependencies and stay unchanged. Do not infer populated-connection safety from them.
No new provider observer is required to expose these existing concrete defects.

## Exact allowed surfaces and required behavior

| Surface | Required correction and preserved boundary |
| --- | --- |
| ipc_root.acquire_generation | Track local pair/lock/endpoint and temporary secret FD across layout, shared flock, secret read, endpoint checks, BootSecret and GenerationLease construction. Temporary secret-close failure must not mask an active primary or skip remaining closes. Transfer only to a fully closeable returned lease; no secret-format or shared-lock change. |
| GenerationLease.close | Mark closed once; attempt LOCK_UN then endpoint/lock/pair closes in existing order despite an earlier failure. Preserve existing OSError suppression; raise first remaining cleanup failure only after all attempts. Repeat close inert. |
| PopulatedGenerationFence.recheck_current | Only its temporary current-root cleanup becomes primary preserving. Existing borrowed generation and retained secret stay caller-owned. Preserve exact metadata/secret/HMAC comparisons and ordinary IpcRootError/OSError mapping. |
| ipc_root._retain_populated_generation | Before transfer own secret FD locally; after transfer a failed initial recheck closes the completed fence. Preserve primary even if cleanup fails; never close borrowed generation. |
| listener._read_file_at | Own readiness FD through read/stat/validation; cleanup preserves primary. Same limits, exact bytes, metadata and ListenerError/OSError mapping. |
| listener.verify_listener | Locally acquired generation remains owned through _verify_record and VerifiedListener construction. Failed verification/construction closes it without masking primary. Successful wrapper owns it once. |
| listener._connect_extension_authenticated | Track verified generation, fence, socket AND created codec until completed connection transfer. Failure attempts every owned close without double-close or masking primary. Preserve actual error boundary: errors from verify_listener before its try remain as before; reached IpcRootError inside its try maps to ListenerIntegrityError. |
| ExtensionConnection.recheck/read/write | Existing error mappings/dispatch effects remain. Operation failure closes the connection with original process-control object or mapped ordinary failure preserved; no refresh, retry or replacement. |
| ExtensionConnection.close | Mark closed once; attempt fence, codec, socket, generation in existing order even if any earlier close raises. Raise first unsuppressed cleanup error after all attempts when called without a primary. Repeat close inert. |
| broker._open_root | Record each acquired child before attempting parent release. Failed child open, parent-close, final fstat or validation releases/attempts every locally owned FD. Return only final validated FD; ordinary OSError/metadata failure remains EndpointViolation. |
| broker.connect_verified | Own root FD and socket across endpoint/proc-root checks, socket creation/validation, deadline/connect, peer checks and final timeout reset. Keep successful socket locally owned until transient-root cleanup finishes, so its failure cannot lose an unreturned socket. BrokerError passthrough and OSError/TimeoutError to TransportClosed unchanged. |

PopulatedGenerationFence.close, VerifiedListener.close and _extension_connection construction are
read-only dependencies unless a concrete defect is separately ruled on before expanding ownership.
The fence owns one FD with existing OSError suppression; wrapper construction acquires no native FD.
FrameCodec.close owns no native FD, but its failure must never skip socket/generation cleanup.
Keep global _close_fd/_close_socket suppression unchanged. Tiny cleanup helpers may operate only
these finite already-owned sets, not discover arbitrary resources or accept authority tokens.

Catch BaseException for cleanup only. Preserve KeyboardInterrupt, SystemExit and a custom
BaseException by object identity. With no primary attempt every owned close then raise first
unsuppressed cleanup failure. Detach ownership before one close attempt; never retry a descriptor
that may have closed and been reused. Track acquisition instances rather than numeric FD values.
Distinguish close releases-then-raises from raises-before-release: the latter proves all required
attempts, not guaranteed kernel release. No SIGKILL or arbitrary VM/kernel-return atomicity promise.

## Tests and evidence

First add expected-GREEN characterizations of actual generation/connection acquisition, identity,
lock lifetime, read/write framing, currentness, successful return and normal refusal/error mappings.
Existing app/tests/test_extension_listener.py channel fixture may be imported unchanged. Its
seams helper REPLACES broker.connect_verified; that helper cannot prove the broker corrections.
New broker tests must execute actual connect_verified/_open_root with controlled lower OS/native
observation seams and real owned sockets/FDs. No successful mocked ownership chain.

Reproduce concrete RED before each repair: secret/readiness read primary plus secondary close;
generation unlock/first close skipping later FDs; populated-fence post-transfer initial-recheck
failure; broker child-before-parent transfer; successful socket then transient-root close failure;
handshake/codec/connection construction interruption; recheck/read/write failure plus cleanup
failure; codec.close failure that formerly skipped socket.close. Parameterize all three control
sentinels. Assert identical primary, each owned close attempted once, borrowed sentinel untouched,
success transfers exactly its owned set, repeat close inert and held lock released when actual
close succeeded. Include each aggregate close position, not only the first.

Use synthetic temporary roots and real sockets/FDs/locks. Track only resources acquired by the
tested call, never process-wide /proc or /dev/fd sweeps; legacy covering tests remain unchanged.
No actual native qualification or measured real peer isolation is claimed by simulated seams.
Prove ordinary old successful/refused peer/mode/no-follow/HMAC/framing/deadline paths remain exact.
Readiness record content continuity must not be relabeled unchanged readiness-file inode.

Freeze three exact beforecopies, four final hashes and full app/deploy/schemas manifest. Self-review
the actual diff and all failure/transfer paths. Run one final frozen covering command:

    LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false
    /Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -B -m pytest
      app/tests/test_provider_stage_connection_lifecycle.py
      app/tests/test_extension_listener.py app/tests/test_stage_observer.py
      app/tests/test_provider_worker.py app/tests/test_ipc_populated_fence.py
      deploy/tests/test_worker_listener.py deploy/tests/test_worker_boundary.py
      -q -p no:cacheprovider

If the frozen covering run exposes a regression, preserve its exact result and hashes, obtain a
bounded controller ruling, fix within scope and freeze again before one new covering run. The
single-run rule applies per final code freeze; it does not authorize ignoring failures or claiming
an earlier passing run covers amended source. Ordinary broker mappings preserve absent private
exception cause/context as well as their stable code/effect; from-None alone does not erase context.

Report exact RED/GREEN/fixture failures/commands/output, ownership accounting, four hashes/full
manifest and preservation. Independent spec/quality preflight and final review gate acceptance.
This task fixes reached requester lifetimes; it does not supply provider receipt admission,
native operator, installation verification, qualification, model readiness or whole-story success.
