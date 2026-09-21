# Provider source initialization and dependency lifetime

Controller contract, 2026-09-19. Spec authority: ../spec.md and provider-source-production.md.
This fixes Task36 ownership, interfaces and controlled verification. Independent preflight and
accepted Task35 plus explicit controller dispatch are required; this document is not operational
deployment authority. No user data, native host initialization, keys, image build or live provider
calls are authorized.


Deliver the fixed-path initializer that recomputes Task35's actual renderer outputs, retains and
compares original public sources, preflights all four provider roots, publishes the immutable
18-file bundle and initializes virgin channel roots. Already-owned populated channels receive
metadata-only observation and no payload reads or repairs. Result remains exactly the three source
digests, with no readiness, payload validity, installation or admission claim.

Create SIX new owned files and modify only TWO existing-file lifecycle surfaces:

| New path | Responsibility |
| --- | --- |
| `app/operations/deployment_provider_source_init.py` | Fixed entrypoint, retained inputs/original sources, mount guards, root-state orchestration and new channel policies. |
| `app/operations/_provider_source_init_files.py` | Only private staged bundle-directory publication and retained publication identities. No duplicate final-bundle observation or namespace snapshot implementation. |
| `app/deployment/_provider_source_files.py` | Shared fixed read-only bundle observation and complete namespace snapshots under provider-source-observation.md; reused unchanged by later runtime reader. No publication. |
| `app/tests/test_provider_source_init.py` | End-to-end controlled initializer and focused helper failure vectors in one test module. |
| `app/tests/provider_source_init_fixture.py` | Real temporary tree plus explicitly simulated ownership/mount/native observations, failure hooks and FD accounting. |
| `app/tests/test_deployment_source_lifecycle.py` | Independent tests for the exact existing factory/cleanup corrections; no imports from the provider initializer or either provider fixture. |

| Existing path | Only allowed changes |
| --- | --- |
| `app/deployment/files.py` | Resource ownership/cleanup in `open_directory`, `open_regular`, `Directory.open/recheck_current`, `SourceFile.open/close`, exactly as enumerated below. |
| `app/deployment/public_init_files.py` | Resource ownership/cleanup in `_PublicInputFile.open`, `_ReleaseInput.open/close`, `_install_namespaces_impl`, exactly as enumerated below. |

The controller has applied this narrow lifecycle ownership to the shared source-production contract.
No other existing helper or source expansion is authorized.
Task35 stays at its strict nineteen new paths with no existing-file edits.
Do not edit Task35's `app/tests/provider_source_fixture.py`; import its accepted
pure fixture API only if it exists at handoff, otherwise construct bounded literal source inputs
in the new initializer fixture. No Task33/34/35 production file, old initializer/test, other helper,
schema or recipe export is a Task36 edit. Existing wire/source bytes and ordinary error, metadata,
hash, currentness and payload-policy behavior remain unchanged in the two lifecycle exceptions.

## Prerequisites and fixed interfaces

Task35 must be accepted and its APIs callable before meaningful initializer RED/GREEN evidence.
The independent existing-helper lifecycle tests do not depend on Task35.
A missing queued Task35 import is not evidence that an initializer assertion has failed.
Consume only contract-specified production APIs:

* `provider_source_render.render_provider_sources(**ten_named_raw_byte_inputs)` and its exact
  `ProviderSourceArtifacts` fields, including `original_artifacts`, `bundle_files`, `pins_bytes`.
* `provider_source_contracts.validate_provider_source_bundle(bundle_files)` and
  `parse_provider_pins(raw)`. Do not rely on uncontracted Task35 constant names/private factories.
* Original `contracts.parse_instance(raw)` and `OriginProfile.from_dict(...)`, rederived from retained
  original instance bytes. The renderer already owns cross-document/recipe validation.

Public initializer signatures are exactly:

    initialize_provider_sources() -> dict[str, str]
    main(argv: list[str] | None = None) -> int

`argv=None` reads `sys.argv[1:]`; any nonempty argument list returns2 with only
`deployment_source_invalid` on stderr, before opening resources. Empty argv executes the fixed
initializer. Success0; closed failure1, stderr only the existing fixed error code. No stdout result
dump, arbitrary-root option, schema/pin override, callback, fake native mode or injected authority.
The no-argument initializer returns precisely context_sha256, geometry_sha256, provider_recipe_sha256.

Recommended INTERNAL interfaces (not public admission APIs):

    _open_inputs() -> _InitInputs                  # owned, retained raw files + recomputed output
    _open_original_sources(inputs) -> tuple       # five retained exact SourceFiles
    _observe_boundaries(inputs, originals) -> tuple
    _preflight_targets(inputs, originals) -> _InitState
    _recheck_guard(state) -> None
    _reopen_owned_root(state, root_key, uid, gid) -> None

Private operations filesystem helper:

    _stage_bundle(root: Directory, expected_files: tuple) -> _BundlePublication
    _commit_bundle(publication: _BundlePublication) -> None

Import shared _open_provider_bundle(root, *, context_sha256) and
_snapshot_provider_namespace(directory, *, namespace) from app.deployment._provider_source_files;
read complete provider-source-observation.md for their exact ownership/cold-read/identity API.
The initializer's pin is digest(rerendered_artifacts.context_bytes), never derived from target bytes.
Require full observed bundle == rerendered_artifacts.bundle_files for existing and published roots.
After rename compare shared observer's _object_identities() to still-retained publication directory/
leaf identities, then exact bytes; close publication handles only after successful transfer.

Bundle handles expose only `recheck_current()/close()` plus internal state needed for transfer;
constructors remain internal. Root arguments are exact retained `Directory` handles acquired by
the fixed orchestrator, never caller paths. Validate the exact fixed target path and expected18-file
shape before writes. No payload parser or consumer is added. Helper receives no trust callback.

## Exact reuse and important non-reuse

| Existing interface | Reuse / restriction |
| --- | --- |
| `public_init_files._ReleaseInput.open(relative, cap)` | Five fixed release files; keeps file and ancestor FDs, signatures and names. Recheck before/after every effect. Narrow lifecycle correction below. |
| `public_init_files._PublicInputFile.open(directory,name,cap=...,modes=(0o440,))` | Six root-owned input config files. It hardcodes gid0, so it cannot read the final gid21201 bundle leaves. |
| `files.Directory.open`, `SourceFile.open/read_current` | Root and original single-file public-source retention; SourceFile requires exactly one leaf and is unsuitable for documents/. |
| `files.open_regular/read_exact/stat_at/stat_fd/signature/validate_regular/close_fd` | The new private helper's fixed bundle leaves, bounded bytes and retained-name/FD comparisons. |
| `public_init_files._empty` | Only top-level target roots with at most one/two namespace children; never use its64-member scan for incoming payload directories. |
| `public_init_files._install_namespaces_retained` | Virgin outbox/receipts/consumed only, exact fixed names and owners. Preserve the established cancelled-before-requests order. |
| `files._NamespacePolicy`, `files._scan_namespace` | NEW policies with metadata-only scans; scanner returns finals/signatures but only a stage count, so add complete external snapshots. Never use `_open_final`, `inspect_namespace` or receipt payload readers. |
| `publication._write_all`, `publication._rename_noreplace` | Exact writes and Linux same-parent no-replace directory commit. No fallback to overwrite rename; unavailable native syscall is closed unavailable. |
| `mounts.native_platform/read_mountinfo/verify_boundaries/containing/backing/verify_device` | Real production platform/mount/device checks; fixture replaces sampling only. No native runner or Docker integration. |
| Old initializer modules | Read for patterns only. Do not import/call their initialize/main functions or reuse their payload-parsing channel classes. |

`_install_source_retained` and `_RetainedTargetFile` both assume their parent contains exactly one
file. They cannot implement the18-file directory by looping. The new private helper is necessary.
`Directory.recheck_current` preserves path/device/inode/uid/gid/mode, but not contents/mtime/ctime;
the new root/namespace snapshots must explicitly retain `signature(stat_fd(...))` too.

## Acquisition and complete preflight

1. Check euid0 and supported Linux platform. Open six fixed config inputs and five fixed release
   inputs from §5; cap aggregate2MiB. Retain parent and file handles immediately as ownership permits.
   Recompute `render_provider_sources` using the ten exact raw byte inputs; compare config pins
   byte-for-byte; call the complete bundle validator. Parse returned pins, not caller dictionaries.
   Compare original instance platform with sampled native platform. No output bytes are written yet.
2. Retain exact original sources and compare actual bytes with renderer originals:

   | Root / filename | uid:gid | Expected output |
   | --- | --- | --- |
   | extension-topology / topology.json | 0:20102 | original_artifacts.prepare_artifacts.topology_bytes |
   | deployment-exchange / exchange.json | 0:21201 | original_artifacts.prepare_artifacts.exchange_bytes |
   | deployment-verify-public / trust-set.json | 0:20102 | original_artifacts.trust_bytes |
   | deployment-receipt-ingress / ingress.json | 0:21201 | original_artifacts.ingress_bytes |
   | deployment-consumption-exchange / consumption-exchange.json | 0:21201 | original_artifacts.consumption_exchange_bytes |

   Roots are under /run/deeptwin, mode0750; leaves0440/single-link. Their bytes, parents and names
   remain retained until success/cleanup. Never initialize/repair them or open original channel
   payloads, slot sockets, generation files, secrets or application state.
3. Normalize mount boundaries for four new writable roots and five original readonly source roots.
   Protected paths passed to verify_boundaries contain retained release ancestors at or below
   c.RELEASE_ROOT (handle.path.is_relative_to(c.RELEASE_ROOT)), the five release leaves, and the
   input directory/leaves. Keep / and /opt retained and current through _ReleaseInput, but never
   pass these above-release-root ancestors as alias-protected paths. Require readonly containing
   mounts for protected release paths including the release root and intermediate directories;
   a readonly leaf bind must not hide a writable release ancestor. Do not
   include an original source's child file as a separate protected descendant of that same required
   root in `verify_boundaries`: its prefix-alias rule would reject every valid deployment. Validate
   the original leaves through retained SourceFile and containing mount/device instead.
   Include metadata observations for any present builtin/old deployment/slot mounts and their
   nested mounts when comparing alias/backing overlap, without opening their data. Preserve the
   whole relevant normalized mapping; unrelated mount-table ordering is not an error.
4. Open all four target roots and classify each as virgin0:0/0755+empty or completely owned.
   Existing static root must contain exactly documents/ with all18 correct bytes/metadata.
   Existing channel roots must contain exactly their prescribed namespace directories, with correct
   root/namespace signatures and bounded metadata-safe files. Any invalid later root prevents all
   writes to earlier virgin roots. Collect aggregate channel entries≤240 before effects.
5. Recheck all raw inputs, old source bytes, mount observations, target identities and complete
   owned-root snapshots. Only then begin publication. State changes are narrowly tracked per root;
   never rerun permissive preflight to accept unexplained external changes as a new baseline.

## Populated-channel snapshots and restart invariant

The shared read-only helper owns NEW `_NamespacePolicy` values, in positional order
writer_uid,primary_gid,pair_gid,final_limit,stage_limit,payload_cap:

    request  = (20102,20102,21201,16,32,65536)
    cancel   = (20102,20102,21201,16,32,8192)
    incoming = (20113,20113,21201,64,32,16384)
    consumed = (20102,20102,21201,16,32,8192)

Shared `_snapshot_provider_namespace` captures directory signature and sorted `(name, stat signature)` for ALL
entries, bounded by policy.final_limit+stage_limit; calls unchanged `_scan_namespace`; repeats the
full snapshot and requires equality. It returns detached immutable metadata including final/stage
counts. Repeat this operation at every guard and compare the entire result with the retained
baseline, not merely stage count. A same-count stage replacement, mutation or rename must fail.
At most96 entries per namespace and240 total; retain directory FDs, never one FD per channel file.

All final/stage grammar/uid/gid/mode/nlink/size rules come from unchanged scanner with new policies.
Recognized final files may contain malformed JSON, false signatures, mismatched hashes or unrelated
bytes; stages may be empty/interrupted. Do not open/read them. Snapshot stability is a filesystem
observation, not payload authenticity. Already-owned roots never receive chmod/chown/unlink/rename/
write/repair. Success cannot be used as provider admission. Future consumers validate payloads
independently, so populated restart needs no context, recipe or epoch rotation.

## Static directory publication and staged ownership

`_stage_bundle` accepts only a retained virgin provider-stage-sources root and exact validated18
expected files. Create one .stage-{fresh UUID}.tmp directory0700 with no-follow/exclusive operations;
no collision retry. Retain root entry↔directory FD identity. Write bounded files in contract order
with O_EXCL/O_NOFOLLOW, set0:21201/0440, fsync and compare exact bytes/hash/size/name/signature.
The helper keeps descriptors needed to prove every file remains the one staged. Set staged directory
0:21201/0750 and fsync it. It returns an internal publication handle, not an installed-source value.

Before commit, the orchestrator rechecks all untouched inputs/sources/mounts/channel snapshots and
the staged publication. Its only permitted root change is that exact own stage entry. The original
root device/inode remains mandatory. `_commit_bundle` no-replace-renames stage to documents, fsyncs
root, sets root0:21201/0750 and retains the original object identity throughout. Reopen the root under
its new metadata and require the original device/inode; validate/adopt the complete documents tree,
then update ONLY this root's known state. Existing roots/channel baselines are never refreshed.

Reopening `documents/` must preserve the staged directory's device/inode and all18 retained leaf
identities, not merely rediscover equal bytes at a replaced path. The old staged-path Directory
handle cannot be blindly rechecked after rename; transfer/rebind only after identity proof.
Reuse `_take_directory` only where its exact fixed0750 assumptions hold, or keep this transfer
inside the private publication handle. Do not fabricate a SourceFile for a multi-file parent.

Create virgin channel roots after static bundle success, in outbox→receipts→consumed order, using
`_install_namespaces_retained` with unchanged filesystem effects and corrected failure cleanup.
Reopen each changed root and compare original object
identity; retain new namespace handles and initial metadata snapshots. Complete the full guard
between roots and at completion. A completed root can coexist with a later untouched virgin root.
Failure leaves honest partial disk state; close owned FDs but do not remove stage trees or undo
root metadata. A later invocation refuses incomplete static/namespace roots without repair.

Budget: at most256 live FDs,18 static leaves and524,288 static bytes; raw input aggregate2MiB;
metadata scans bounded above. Holding the five release-input ancestor chains, six config FDs,
five SourceFiles, four roots, documents/leaves and four namespaces is well below256; tests must
measure peak acquisition including transient rechecks and partial failures. All loop cardinalities
come from fixed lists or bounded scanners; no unbounded retry, recovery or directory traversal.

## Narrow existing-helper lifecycle correction

These are actual dependency factories, not alternative Task36 acquisition implementations.
Their existing exception handlers omit process-control failures after acquisition; several close
paths can also skip later resources or mask the primary failure. Outer initializer cleanup cannot
own descriptors that a failing factory never returned. Correct these exact surfaces in place.

| Surface | Minimal correction and deterministic interruption checkpoint |
| --- | --- |
| `files.open_directory` | Track the current descriptor and the just-acquired child separately until ownership transfers. Transfer child ownership before attempting to close the previous descriptor; mark the previous close attempt relinquished before calling it, avoiding an unsafe double-close. On a later component-open failure or interruption while closing the prior descriptor, attempt closure of every still-owned descriptor. Preserve existing OSError/AttributeError→`DeploymentSourceUnavailable` mapping; other exceptions propagate unchanged. |
| `files.open_regular` | Cover returned child FD through stat/regular validation and all failure exits; interrupt at `stat_fd` or `validate_regular` after real open returns. Preserve existing OSError/DeploymentSourceError→`DeploymentSourceError` mapping. |
| `Directory.open` | Retained FD remains factory-owned through validation and initial `recheck_current`; close it on any failure. Interrupt at validation/initial recheck, including nested transient acquisition. Existing mapped failures remain mapped exactly. |
| `Directory.recheck_current` | Its temporary reopened FD closes on success and failure without replacing a validation/currentness/process-control primary error. Keep OSError→unavailable and all identity comparisons unchanged. Interrupt at validation after the transient open. |
| `SourceFile.open` | Factory owns root plus optional leaf until full `read_current` succeeds; failure attempts both closures even if one fails. Interrupt at membership/stat/signature/initial retained read after relevant ownership is recorded. Keep existing ordinary invalid mapping. |
| `SourceFile.close` | Mark closed before attempts; attempt leaf and root even when leaf close raises. With no primary supplied by a caller, re-raise the first cleanup failure after all attempts; repeated close remains a no-op. |
| `_PublicInputFile.open` | Own returned leaf through signature capture and initial whole-byte read; close for every failure, retaining existing ordinary invalid mapping and caller ownership of its directory. Interrupt at signature/initial `_read_current`. |
| `_ReleaseInput.open` | Own each recorded ancestor and optional source through final `read_current`; attempt all on every failure. Interrupt at a later ancestor factory, mode check, leaf factory, source read or retained ancestor recheck. Preserve existing ordinary invalid mapping; do not close caller-owned resources. |
| `_ReleaseInput.close` | Mark closed before attempts; try source plus every recorded ancestor even if an earlier close fails; first cleanup failure wins only when there is no prior operation failure. Keep ordinary closure order and idempotence. |
| `_install_namespaces_impl` | Preserve mkdir/open/chown/chmod/fsync/adoption/root-change order and wrappers. Protect each returned raw child FD until adoption; on failure try every retained namespace, even if a prior cleanup raises. Inner cleanup cannot mask a chown/chmod/fsync/adoption primary. Interrupt at each operation after open and on later namespace creation/root metadata steps with earlier namespaces retained. |

The lifecycle contract is exception-safe ownership at these explicit acquisition, validation,
publication and cleanup boundaries. It is not atomicity against interruption at arbitrary VM
instructions, kernel SIGKILL, interpreter death, or a substituted syscall that opens a descriptor
and raises without returning it. Tests raise at the next callable after successful acquisition has
returned and ownership has been recorded; they do not claim a guarantee the runtime cannot supply.

For every factory failure, preserve the same primary process-control exception object, including
`KeyboardInterrupt`, `SystemExit` and a custom `BaseException`; do not translate to a closed-source
code or `ExceptionGroup`. An ordinary primary keeps its existing mapped class/code even if cleanup
also fails. Each independent owned close is attempted once; never retry a descriptor after a close
attempt, because an interrupted close can have completed and the FD number can have been reused.
Cleanup cannot promise an OS resource was closed when the OS itself refuses closure; distinguish
attempt-all from return-to-baseline measured with successful real closes.

Use explicit bounded local ownership/cleanup paths. A local loop may remember its first cleanup
exception and finish the other closes, then propagate it only if no primary exists. The new
initializer/helper must preserve their primary around invoking aggregate `.close()` as well.
No new public cleanup API, process-global manager, `/proc`/FD sweep, descriptor guessing or thread/
signal machinery. No production fault hook. Keep `close_fd`'s existing OSError suppression unchanged.

`RetainedHandle`, its context-manager `__exit__`, `Directory.close` and `_PublicInputFile.close`
need no modification: they respectively have no acquisition and single-resource close semantics.
The new initializer uses explicit primary-preserving aggregate cleanup, not an assumption that
generic `with` suppresses a secondary close failure. `_install_source_impl`, `_RetainedTargetFile`,
`_read_at`, `_release`, namespace scanners/policies, payload readers and old initializer orchestration
are outside this edit. This is not a repository-wide lifecycle hardening claim.

## Independent lifecycle tests and preserved legacy behavior

`test_deployment_source_lifecycle.py` uses `tmp_path`, direct imports of the two existing modules
and bounded local test utilities. It must run without Task35/36 new production files. No dependency
on provider fixtures, renderer, initializer, environment root access or mounted deployments.
Use real regular files/FDs; isolate simulated UID/GID only where fixed-root factories require it.
Record returned FD identities and close attempts locally; do not sweep all process descriptors.

Characterize ordinary behavior BEFORE changing factories: success bytes/identity; invalid path,
symlink/hardlink, owner/group/mode/cap denial; exact ordinary mapped exception class and fixed code;
source pin mismatch and same-byte name/inode replacement denial; returned ownership (parent remains
open for `_PublicInputFile`); namespace names/order/owners/modes/fsync sequence; retain=False and
retain=True return/ownership shapes. Existing `close_fd` suppresses OSError as before. These cases
must be green both before and after the lifecycle patch, not rewritten to bless changed behavior.

Then parameterize each matrix checkpoint over three primary sentinel types and first/later failure
positions. Verify same exception object escapes, all recorded owned FDs are closed, borrowed FDs
stay usable, and no disk repair/unlink occurs. A cleanup-failure spy closes the actual selected FD
first and then raises a second sentinel: remaining owned closes still run, original primary wins.
Test aggregate `.close()` without a primary too: first cleanup sentinel escapes only after all
other closures; second `.close()` does nothing. A refusal-to-close test asserts all attempts and
error precedence, then lets test teardown close its deliberately retained resource; it does not
claim successful OS closure. For path walking, interrupt prior-FD close after child acquisition and
prove the child is not leaked or double-closed. For namespaces, interrupt after one child has been
adopted and while the next raw FD is owned; prove both are attempted without rollback.

## Dispatch conditions

1. Independent architecture/interface preflight must be READY; explicit controller dispatch supplies
   the accepted Task35 manifest and exact beforecopies of the two existing lifecycle files.
2. Inspect accepted Task35 outputs at handoff and use only the specified APIs. A missing fixture
   convenience function does not justify editing Task35 files or inventing production constants.
   Initializer-owned fixed path/cap tables mirror §§4–5 and are compared with accepted rendering.
3. Native image identity, provisioning, real mount isolation and admission remain excluded; no
   external operation is required to implement or test this temporary-tree tranche.

## TDD sequence and decisive vectors

Use the repository-selected Python test runner; commands below describe future checks, not tests
performed by this document. The independent lifecycle step needs only ownership promotion; the
initializer steps additionally need accepted Task35. No commits are authorized.

- [ ] Characterize legacy ordinary behavior using the independent lifecycle test; run it before any helper edits.
- [ ] Add one interruption/cleanup vector per matrix row and record meaningful failing assertions.
- [ ] Correct only enumerated lifecycle surfaces; rerun independent lifecycle and unchanged old tests.
- [ ] Execute each initializer row below as test→meaningful RED→minimal implementation→GREEN.
- [ ] Run the narrow covering list, inspect scope diff and report limitations for controller review.

| Step | First meaningful RED | GREEN implementation and additional decisive vectors |
| --- | --- | --- |
| 1. Entry/input boundary | Valid fixed temporary-tree call cannot create the expected18-file package because initializer is missing; do not count missing Task35 as RED. | Fixed argv/euid/native guards; actual retained release/config inputs; renderer recomputation and pin mismatch; exact sanitized0/1/2 behavior; fresh import performs no I/O/effects. |
| 2. Complete no-write preflight | A malformed fourth target must leave all earlier virgin roots byte/inode/mode-identical. | Valid fixed tree with retained / and /opt passes; protected release root/intermediate directory writable behind readonly leaf binds refuses; original-source bytes/profile/platform/pins; protected file/ancestor/parent replacement; alias/backing/prefix/nested mount cases; no repair of occupied roots. |
| 3. Static bundle | First run produces exact independent18-file oracle, docs directory and modes; old sources remain unchanged. | Stage directory and leaf race checks; short writes; failures at mkdir/open/chown/chmod/readback/file-fsync/dir-fsync/rename/root-reopen; preserve staged directory/leaf identity across rename; partial states refused on retry. |
| 4. Virgin channels | Correct root/namespace creation order and identities after static publication. | Mixed completed/virgin roots; outbox two namespaces retained in order; failure before/after each namespace/root metadata step; no unexpected opens of old payload/IPC/private trees. |
| 5. Populated restart | Metadata-safe invalid JSON/false-signature/mismatched-hash bytes and all three stage metadata states survive unchanged. | Spy fails any channel payload open/read or receipt/JSON/crypto parser call; same-count stage mutation fails; additions/removals/mode/owner/inode/root changes fail boundedly; no loop/cleanup/context rotation. |
| 6. Bounds and lifetime | Incoming64final+32stage and total240 metadata-safe entries succeed; cap+1 fails before writes. | All file-size/final/stage count edges, final zero-length denied/stage empty accepted; cancel/consumed8192 accepted here with old4096 policies untouched; ≤256 peak FDs and return-to-baseline after deterministic acquisition/publication checkpoints, including primary plus secondary cleanup failures. |

Fixture uses real temp-tree bytes, directory operations, FDs, signatures, rename/fsync and cleanup.
Only ownership/uid sampling, logical-path mapping, native/mount observations and unavailable Linux
no-replace syscall may be simulated in tests. Fixtures carry an explicit "not native evidence"
description. Test inputs/expected filenames/modes come from literal contract data and independently
validated Task35 fixtures; never generate the expected tree by calling the initializer under test.
Track mutating syscalls for all original trees and occupied roots, and forbid them, including changes
that might preserve final bytes. Test-only metadata registration must not mask real inode replacement.

Independent primary: `python -m pytest app/tests/test_deployment_source_lifecycle.py`.
Initializer primary: `python -m pytest app/tests/test_provider_source_init.py`.
Narrow covering command after GREEN:

    python -m pytest app/tests/test_provider_source_init.py \
      app/tests/test_deployment_source_lifecycle.py \
      app/tests/test_deployment_prepare_init.py \
      app/tests/test_deployment_receipt_public_init.py \
      app/tests/test_deployment_source_files.py \
      app/tests/test_provider_source_render.py

No broad suite/native/Linux/Docker/network/credential tests. Retain existing old malformed-payload
and interrupted-stage rejection tests unchanged: those old initializers deliberately validate old
payloads, while the NEW provider initializer makes only metadata assertions.

Completion report must include exact RED/GREEN/covering commands/results, six new-file and two
modified-file hashes, an enumerated lifecycle-only diff for the two exceptions, all other
out-of-scope manifest equality, measured FD bound, every resolved compatibility ruling and the
honest controlled-filesystem limitation. It cannot claim installed sources, built images, qualified
operator/worker, five-check qualification, credential binding, generation or live provider authority.
