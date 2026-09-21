# Complete existing slot-metadata lifetime

Controller contract, 2026-09-19. State: independent preflight READY; no implementation before
explicit dispatch after accepted Tasks37/38/39. Existing approved runtime/deployment work only.
Authority: ../spec.md FR-032 and ../decisions.md ADR-014, with accepted Task36 Directory lifetime.
This corrects concrete existing original-tool acquisition defects and is also needed by the later
provider producer. It installs no provider service, DB schema, route, worker, image or host state.
The integrated v4/history/owner producer remains separately reviewed work, not part of this task.

## Exact four-file scope

| Path | Allowed change |
| --- | --- |
| app/workers/ipc_root.py | Only the six listed metadata acquisition/temporary cleanup/transfer/recheck/close surfaces and tiny private finite cleanup helpers, no public API addition. |
| app/deployment/sources.py | Only TopologySource.acquire_slot and SlotMetadataLease.close ownership cleanup. |
| app/deployment/prepare_service.py | Only PersistentDeploymentPrepare._acquire locally acquired lease cleanup before successful return. |
| app/tests/test_provider_slot_lifecycle.py | NEW independent real-FD characterizations and interruption tests. |

No existing test changes, signature/output/mode/path/admission changes, generic FD framework,
dependency upgrade, root/native/Docker/user data/key/live-model/network action, commits or push.
Preserve accepted provider context/publisher and inherited source files. Directory/SourceFile and
RetainedHandle stay unchanged. One code writer; no subagents from implementer.
Only extra evidence write: .superpowers/sdd/resumption-plan/task-40-report.md.

## Concrete dependency chain and bounded repair

The Task40 call chain is actual current code, not a proposed general ownership framework:

    PersistentDeploymentPrepare._acquire
      → TopologySource.acquire_slot
        → Directory.open (accepted36 dependency)
        → ipc_root.acquire_generation_metadata
          → _open_absolute_directory
          → _validate_layout → endpoint os.open + _open_regular_at
          → _open_regular_at (lock, then secret metadata)
          → endpoint os.open
          → transfer four FDs into MetadataGenerationLease
          → MetadataGenerationLease.recheck_current
            → _open_absolute_directory (temporary current-root FD)
        → transfer metadata lease + Directory into SlotMetadataLease
        → SlotMetadataLease.recheck_current
      → final retained topology digest comparison

Outer sources.py cleanup cannot recover an inaccessible inner lease: currently
acquire_generation_metadata sets all local descriptors=-1 before initial recheck, but catches only
IpcRootError/OSError. KeyboardInterrupt/SystemExit/custom BaseException there bypasses lease.close.
The two raw openers have the same catch gap; directory traversal additionally closes its parent
before recording the opened child as owned. These are concrete prerequisites ofTask40's stated guarantee.

### Exact permitted Task40 changes (no signature changes)

| Actual surface | Minimal correction / deterministic checkpoint |
| --- | --- |
| ipc_root._open_absolute_directory | Track opened root and each child while locally owned; record child ownership before attempting parent close. BaseException at next child open, parent-close call or final fstat closes/attempts all still-owned descriptors and preserves primary. On success transfer only final descriptor. |
| ipc_root._open_regular_at | After successful os.open, any failure at fstat/type/nlink/owner/mode/size checks releases the local descriptor; success transfers it. Preserve IpcRootError and OSError→IpcRootIntegrityError mapping exactly. |
| ipc_root._validate_layout | Only its transient endpoint-validation finally needs primary-preserving cleanup. If _validate_directory raises and endpoint close also raises, preserve validation primary; outer acquisition still owns its pair. Lock/secret metadata descriptors remain opened/closed as before; no content read. |
| ipc_root.acquire_generation_metadata | Catch BaseException for ownership unwind. Keep local four-FD ownership until a fully closeable lease receives it; after transfer, initial recheck failure closes THAT lease. Before transfer, close all local secret/endpoint/lock/pair descriptors. Cleanup failure never masks original IpcRootError, translated OSError or same process-control object. No double-close of transferred FDs. |
| MetadataGenerationLease.recheck_current | Only temporary current_fd cleanup becomes primary-preserving. Existing retained FDs remain owned by caller's lease; ordinary recheck refusal does not auto-close/refresh/poison it.Task40's enclosing acquisition/operation owner closes on failure. |
| MetadataGenerationLease.close | Mark closed, attempt LOCK_UN (OSError still ignored), then attempt all four owned descriptors in existing secret/endpoint/lock/pair order even if unlock or one close raises BaseException. Raise first unsuppressed cleanup error only after all attempts when no earlier primary exists. Repeat close is inert. |
| TopologySource.acquire_slot | Locally own acquired Directory and metadata lease until a completely closeable SlotMetadataLease receives both; final recheck failure unwinds transferred owner. Catch BaseException for cleanup, preserve existing ordinary Busy→DeploymentSourceBusy and other known failures→DeploymentSourceError. |
| SlotMetadataLease.close | Attempt metadata.close AND directory.close even if first raises. Mark closed once; preserve active acquisition/operation primary at call sites. No source close or changes to borrowed topology. |
| PersistentDeploymentPrepare._acquire | Retain an acquired slot lease locally through final topology digest validation; any failure before return closes it. Preserve busy→capacity, source error→dependency_unavailable, invalid slot→not_found and existing ordinary return. |

Tiny private cleanup blocks/helpers inside ipc_root.py may implement these exact finite owned sets;
no new module/public API, generic FD tracker, global manager, process FD scan or ownership token.
ipc_root._close_fd keeps its current OSError suppression. Its ordinary semantics must not change
globally merely to make new tests easier. Metadata __enter__/__exit__ are NOT used byTask40's explicit
try/finally ownership and remain out of scope; do not advertise a new global context-manager promise.
GenerationLease/acquire_generation, initialize_pair_root/_create_regular/secret rotation,
PopulatedGenerationFence/_retain_populated_generation bodies and worker execution remain untouched.
Shared raw openers/_validate_layout incidentally improve cleanup for their existing callers; do not
expand into auditing or rewriting those callers' whole lifetime.

Guarantee is at the named successful-acquisition/subsequent-call/transfer checkpoints. Detach an
owned descriptor before its one close attempt so a close that releases then raises cannot cause
a dangerous retry against a reused descriptor number. If an injected close raises before actually
releasing, prove all remaining close attempts and same primary; do NOT promise the kernel released
the failed descriptor or blindly retry it. No zero-leak promise against SIGKILL or arbitrary VM
interrupt between os.open returning and assignment/ownership bookkeeping.

### Exact Task40 test proof

NEW app/tests/test_provider_slot_lifecycle.py is independent of provider initializer/publication
fixtures. Use isolated real descriptors and the established IPC layout fixture with simulated
ownership observations; no real root/native/user-data setup. Instrument only descriptors acquired
by the tested call; keep a separate sentinel borrowed FD open. Parameterize KeyboardInterrupt,
SystemExit and a custom BaseException with exact object identity assertions:
Track acquisition/ownership instances, not only numeric FD values: legitimate later opens can
reuse a number without constituting a second close attempt on the previous owner.

* Raw directory: root acquired then next child open fails; child acquired then parent close
  releases-and-raises; final fstat fails. Verify every owned child/root close attempted, no duplicate
  close and sentinel untouched. Raw regular: fstat/validation failure immediately after open.
* _validate_layout: endpoint validation primary plus secondary endpoint close error. Verify primary
  survives, endpoint closes and outer pair closes. Ordinary missing/mode/owner/link/size refusals
  retain the same sanitized IpcRootIntegrityError class/code.
* Metadata acquisition: pair/layout/lock-open/shared-flock/secret-open/endpoint-open/stat checkpoints;
  most importantly inject at initial lease.recheck_current AFTER local FDs were transferred.
  Verify all four retained descriptors closed and shared lock released, not just empty local slots.
* Returned metadata recheck: temporary current-root validation primary plus close secondary; caller
  still owns retained four and explicitly closes them. Metadata close: unlock or each close failure
  must not skip later closes; repeated close does not repeat unlock/close.
* Whole actual _acquire chain: metadata failure propagates through actual acquire_slot; mapping/final
  slot recheck failures and final topology digest failure clean all acquired levels, preserve same
  process-control object and leave the original topology/source/context owned by their caller.
* Secondary-close tests distinguish releases-then-raises (physical live-set empty) from
  raises-before-release (all required attempts observed, no false physical-release assertion).
  No /proc enumeration or global FD assumption.
* Ordinary success preserves exact slot tuple, metadata identities/lock, no endpoint listing and
  no _read_exact_secret call. Busy and missing/changed metadata preserve existing error translation.
  Old tool request/projection/replay bytes remain unchanged by these resource-only corrections.

Run unchanged app/tests/test_ipc_metadata_lease.py, test_deployment_sources.py and relevant old
prepare/publication suites; also test_ipc_populated_fence.py and deploy/tests/test_ipc_root_initializer.py
because the two corrected raw openers/_validate_layout are shared. The latter are covering tests,
NOT authorization to alter populated/secret/initializer operation semantics.

## TDD and acceptance gate

Before altering any existing body, add expected-GREEN characterizations for actual normal acquisition,
lock lifetime, metadata identity, no secret read/listing, ordinary Busy/missing/owner/mode/link/size
refusal and service error translation. Then reproduce actual deterministic failure, including the
post-transfer inaccessible metadata owner and secondary cleanup masking, before corresponding fix.
A test fixture error is not RED evidence. Use actual temporary files/descriptors/locks; only the
existing UID/GID/mount/path observations may be simulated. No successful mocked ownership chain.

Freeze three exact beforecopies, four final hashes and the full app/deploy/schemas manifest;
verify all out-of-scope files unchanged. After self-review run once on frozen bytes:

    LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false
    /Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -B -m pytest
      app/tests/test_provider_slot_lifecycle.py app/tests/test_ipc_metadata_lease.py
      app/tests/test_deployment_sources.py app/tests/test_deployment_prepare.py
      app/tests/test_deployment_prepare_publication.py app/tests/test_ipc_populated_fence.py
      deploy/tests/test_ipc_root_initializer.py -q -p no:cacheprovider

Report commands, all observed RED/GREEN/fixture failures/warnings, exact old mapping preservation,
actual descriptor accounting/lock release and simulated evidence boundaries. Independent spec and
quality review gates acceptance. This does not claim global IPC/context-manager safety, actual
native isolation, provider readiness, qualification, billing authority or whole T042/T087 completion.
