# Retained provider outbox publication

Controller contract, 2026-09-19. State: independent preflight READY after B1 combined-observation correction; no implementation before
explicit dispatch and accepted Tasks36/37/38. Authority: ../spec.md FR-032, ../decisions.md ADR-014,
provider-source-context.md, provider-source-observation.md and provider-prepare-protocol.md.
This is Task39, the publisher-only delivery previously labeled39A in an advisory. The database,
migration, actual owner producer, routes, slot lease and qualification remain separate reviewed work.

Goal: a real source-bound fixed-path, no-replace request/cancellation publisher, independently
testable on controlled trees. It consumes the actual retained source context, not a fake exchange
or a caller-supplied admission flag. It does not run on startup or accept browser commands itself.
No native/host/data/key/Docker/live-model/commit/push authority is granted.

## Ownership: three new files, three narrow existing-file changes

| Path | Change / responsibility |
| --- | --- |
| app/deployment/provider_publication.py | NEW: fixed-root lease, staged attempt and exact-byte idempotent publication. No database or authentication. |
| app/tests/test_provider_publication.py | NEW: real controlled-tree lease, payload/currentness/cap/race/crash-window tests. |
| app/tests/test_provider_publication_lifecycle.py | NEW: independent deterministic FD/interruption tests of actual publisher dependencies only; no slot/IPC acquisition scope. |
| app/deployment/provider_sources.py | MODIFY: private combined publication observation accessor and minimum private guard return plumbing only; public read-only API unchanged. |
| app/deployment/_provider_source_files.py | MODIFY: expose the existing code-owned namespace-policy selection as one private resolver used by its scanner and new publisher; no new policy table. |
| app/deployment/publication.py | MODIFY: ONLY _existing_for_policy and _stage_payload ownership/primary-preserving cleanup described below; ordinary bytes/modes/errors unchanged. _commit_stage owns no FD and stays unchanged. |

These three modifications are explicit review scope, not generic filesystem hardening.
The original slot-helper corrections belong to a separately reviewed later integrated producer.
Do not alter files.py/public_init_files.py/RetainedHandle or re-open Task36's completed scope.
Do not copy the old publication algorithm to avoid fixing a bounded cleanup defect.

## Interfaces and retention

Keep ProviderSourceContext's public read_current/recheck_current/close interfaces and outputs unchanged and read-only. Add only the accessor and minimum private guard return plumbing needed for:

    ProviderSourceContext._provider_publication_observation() -> tuple[
        tuple[FileIdentity, FileIdentity, FileIdentity],
        tuple[tuple[str, _ProviderNamespaceSnapshot], ...],
    ]

First tuple order is provider-deployment-outbox root, requests, cancelled. Second tuple contains
exactly four frozen shared namespace snapshots in requests, cancelled, receipts, consumed order.
The complete currentness guard captures all four before snapshots, checks static/original sources,
mounts/protected roots/identities, captures all four after snapshots, verifies equality and aggregate
capacity, and returns one of those equal validated sets. Derive the identity triple from actual
owned handles under that same successful guard; never take a detached snapshot after the guard.
No FD export, path override, rebind or caller replacement. Identities are comparison data, not
standalone admission. Exact type, hollow/subclass and closed-handle checks remain mandatory.
Existing ordinary-error/process-control behavior and ownership remain unchanged. No startup,
fixture, or other Task37 behavior becomes writable. Snapshots are observations, not reusable authority.

In shared _provider_source_files.py add:

    _provider_namespace_policy(namespace: str) -> files._NamespacePolicy

Only four existing literal names are supported; return the existing immutable policy selected
by the scanner. Do not widen public namespace grammar, expose arbitrary paths or duplicate limits.
Shared scanner continues enforcing fixed directory path/owner/mode. Runtime publisher selects only
requests/cancelled; receipts/consumed remain opaque metadata-only to this task.

provider_publication.py owns:

    open_provider_outbox_lease(
        context: ProviderSourceContext, *, profile: OriginProfile,
        expected_payloads: tuple[tuple[str, bytes], ...],
    ) -> ProviderOutboxLease

    ProviderOutboxLease.observe_existing(
        *, role: str, request_digest: str,
    ) -> PublicationObservation | None

    ProviderOutboxLease.stage(
        *, role: str, request_digest: str,
    ) -> ProviderPublicationAttempt

    ProviderOutboxLease.commit(
        attempt: ProviderPublicationAttempt,
    ) -> PublicationObservation

    ProviderOutboxLease.close() -> None
    ProviderPublicationAttempt.close() -> None

Roles are exactly request/cancel. expected_payloads is <=32 unique (role,digest) pairs, extracted
from complete verified provider journal intents bythe later integrated producer; tuple elements are (role, canonical bytes).
Each cancellation must join its corresponding request from that same tuple. Reparse with Task38;
compare context digest/ID/epoch, profile, inventory digest and request fields to actual context bytes.
Do not accept old tool bytes or a synthetic ExchangeSource. Full candidate/history authority stays
inthe later integrated producer; this primitive cannot establish it from caller bytes.

Factory owns three newly opened Directory objects at the fixed root/requests/cancelled paths.
Use Directory.open with20102:21201/0750 and no creation. Compare their actual identities to the
context's combined observation identities before and after acquisition/currentness. Enclose factory
acquisition and verification in its own four-namespace baseline/final observation. Retain context
as borrowed, never explicitly close it. Its own process-control guard may self-close under its
existing contract; publisher cleanup must not override that behavior. Lease close closes only its own directories and attempts.
Opening own FDs avoids borrowing an FD that context.close could release and the OS could reuse.
All reads/commit recheck both own directory currentness and the still-open actual context, including
whole mount/protected-root/static-byte guards. Context closure invalidates every lease operation.

MaxTask39 additions:3 persistent directory FDs +1 staged FD +1 existing-final read FD; no root discovery
or unbounded handle registry. At most one active attempt per lease. An attempt is exact-type,
nonconstructible, lease-bound and one-shot; close is idempotent. Closing a lease also closes a live
attempt. Do not close a caller's/context's FD, reopen a failed source or refresh retained identity.
No constructor/path/platform override is public. Use the context's actual supported Linux gate and
the existing native NOREPLACE primitive; unsupported platforms fail closed before acquisition.
Tests patch the same explicit native/mount/metadata observation seams as accepted37, never install
a production positive-mode bypass. Fixed ordinary errors are DeploymentSourceError or
PublicationUnavailable as in existing publication; map Task38 DeploymentPrepareError into that fixed
family, with no raw values/private bytes/paths escaping in diagnostics. Reconstruct and validate the
exact OriginProfile, including hollow-object refusal; exact type alone is insufficient.

Opening/observing scans all outgoing final entries with shared metadata policies. Each final must
have an expected role+digest and its exact expected canonical bytes. Unknown, malformed, wrong-byte
or wrong-context final denies publication without deletion. A metadata-safe interrupted stage remains
opaque and untouched. Incoming/consumed payloads are NEVER parsed or blessed by this publisher.
Per-namespace96 and aggregate240 entry bound still apply through context; request16+stage32,
cancel16+stage32, request65536B/cancel8192B, exact hex64.json and existing stage UUID grammar.
The service also requires every journal-published outgoing final to be observed; missing files are
source dependency failure, not permission to republish a terminal acknowledgment.

Reuse publication._stage_payload/_commit_stage/_existing_for_policy/_rename_noreplace with the
resolver's fixed policies. Filename = decoded B32 digest hex + .json. Existing exact final means
idempotent observation/fsync, not a fresh stage. Different final never overwritten. New stage is
exclusive/no-follow0600, bounded write, group21201,0440,file fsync, signature validation; commit is
actual Linux renameat2 NOREPLACE, directory fsync, exact final re-read and context recheck. No fallback
rename, hardlink overwrite, arbitrary unlink, chown of occupied files, broad cleanup or retry loop.
FileExistsError observes exact existing bytes once. An abandoned own stage may remain; never erase
another writer's stage, and do not add a stage scavenger. Exhausted stage budget refuses new attempts.

At each lease operation obtain a combined guarded observation before outgoing byte reads/effects,
compare its identity triple to lease-owned directories, and retain all four snapshots as baseline.
At exit obtain another combined guarded observation and compare all four against that baseline.
Allow only the following bounded transitions; preserve every unrelated entry's complete signature:
- Observation changes no entries; absent-target None requires successful closing validation.
- Stage adds only the identified own stage to an initially absent target.
- Successful commit removes that stage and adds the target final with its retained file identity
  and exact bytes. Account for legitimate directory and renamed-inode timestamps without dropping
  unrelated entry signatures.
- EEXIST may leave the own stage and introduce/retain only the target final with exact required
  metadata and bytes. Different bytes or other changes refuse. No retry, overwrite, unlink or
  adoption of another writer's stage. A valid target arriving between completed stage and commit
  calls may be present at commit entry and encountered by the single no-replace attempt.
Safe changes between complete calls are freshly rescanned, not compared against an obsolete
membership baseline. Outgoing finals must still match immutable expected bytes. Metadata snapshots
themselves grant no payload validity. Incoming/consumed mutation between the two successful guards
of ONE operation must fail even when each guard independently observes a stable state.
Ordinary source failures close transient FDs; the lease remains closable. Process-control exceptions
close all its owned resources and propagate the identical primary object, even if cleanup raises.

Correct only deterministic ownership checkpoints inTask39's reused helpers: successful directory/
stage/file FD acquisition; pre/post reads and writes; transfer to returned owner; commit/existing-file
observation; aggregate close after one child close fails. Catch BaseException only for cleanup,
attempt all owned closes, preserve active primary; without primary raise first cleanup failure after
all attempts. Preserve ordinary OSError/publication mapping. No impossible atomicity promise for
arbitrary interpreter interruption between kernel return and Python ownership assignment or SIGKILL.
Old publisher close result semantics remain ordinary-error compatible. Metadata/slot acquisition
is not a Task39 dependency; its complete later-producer obligation requires separate reviewed scope.

## Exact publication scope and source joins

This clarifies the interfaces above; it does not make all publication.py writable.

**Existing publication.py allowed surfaces: only _existing_for_policy and _stage_payload.**
_existing_for_policy must preserve the active read/stat/fsync/mismatch primary if closing its owned
read FD raises. _stage_payload must retain clear local-versus-returned _StagedFile ownership through
write/chown/chmod/fsync/stat/validation/return and preserve active primary during local cleanup.
These are the only old helpersTask39 needs to modify. _commit_stage owns NO FD: it borrows directory
and stage, so it receives no cleanup rewrite. _StagedFile.close, _rename_noreplace, _write_all,
_existing, _publish_projection, publish, publish_cancellation_v2 and all validators remain unchanged.
The new lease/attempt caller owns aggregate cleanup around borrowed _commit_stage and calls
_StagedFile.close with primary preservation. No broad old-publisher lifecycle claim follows.

Existing ordinary success/failure behavior remains exact: same bytes, names,0600→0440 sequence,
group, NOREPLACE behavior, fsync ordering, exact-existing comparison, fixed errors and unchanged
stage-left-behind policy. Characterization tests cover each before new process-control tests.
Task36's accepted open_regular/Directory lower-level guarantees are dependencies by contract;
read accepted APIs as needed but do not add another fix to its files.

### expected_payloads exact grammar/bounds

At factory entry, before opening additional directories, require exact tuple of0..32 exact2-tuples.
Each pair is (role, raw) with exact str role request|cancel and exact nonempty bytes. At most16
requests and16 cancellations, request<=65536B, cancel<=8192B, aggregate raw bytes<=1,179,648B.
Reject subclasses, malformed pair lengths, excess counts/bytes before parsing/materialization.
Require canonical order (role rank request=0,cancel=1; within each rank decoded request_digest hex
ascending). No duplicate (role,request_digest), duplicate request IDs across request entries, or
more than one cancellation per request. Every cancellation has exactly one request in the tuple
with the same ID AND digest; a cancellation-only tuple is invalid. Empty tuple can observe an empty
outgoing namespace but cannot stage; unexpected final then refuses as usual.

All entries undergo Task38 canonical parsers/limits. No truncation/sorting/deduplication to accept
an invalid caller tuple.the later integrated producer constructs this order from verified journal;Task39 grants no admission
merely because a caller can construct it. Raw aggregate bound counts only the supplied bytes;
bounded tuple/object counts and each parser's own depth/items/string limits additionally apply.
Tests include both16+16 maximum and17 of either role, aggregate cap+1, wrong ordering, duplicate IDs,
same ID/different digest, unmatched cancellation and malformed-but-metadata-safe occupied final.
The aggregate ceiling follows mathematically from the two role-count/per-payload ceilings; a
cap+1 vector necessarily also violates a constituent bound. Do not invent a valid isolated overflow
or weaken another cap merely to reach an otherwise unreachable test branch.

### Request-to-actual-source joins performed byTask39

Obtain18 bytes from the actual retained context read_current; that complete reader already verifies
Task35 bundle graph, independently startup-pinned context, actual five old source leaves, original
profile, mounts/protected roots and channel identities.Task39 never feeds self-read bytes back into a
caller-expected constructor or treats an expected_payloads hash as its context pin.

For EACH supplied request, in addition to Task38 parser:

1. Its exact OriginProfile instance/digest agrees with the lease profile and actual context's original
   profile. Compare source_context object to context_id/epoch and SHA256/len of ACTUAL
   source-context.json; compare geometry object to SHA256/len of ACTUAL geometry.json.
   stage_profile is the existing fixed claude-text-transform-v1. No caller ID can rotate the context.
2. Parse canonical embedded preserved_inventory via Task38 inventory parser, recompute its digest,
   and compare instance/origin/topology ID/topology hash to ACTUAL original-topology.json/profile.
   Validate every listed slot/service identity against that original topology. Head digest's pure
   storage-v3 equation is checked by38; row existence/event/head authority remains deferred.
3. Find exactly one of<=16 original slots matching new_service_effect.service_identity and its
   exact single socket_mounts entry; named_volume_mounts remains empty. selected_platform_entry.platform
   equals the original topology platform. Selected slot AND candidate extension_id are absent from
   embedded inventory. The validated bundle geometry is the exact projection of this same topology,
   not a caller-provided second slot map. These checks use actual effect fields only.
4. Reconstruct each cancellation using make_provider_cancellation(matching_request_bytes,
   profile=profile,cancelled_ms=parsed cancelled_at), compare complete canonical bytes. This closes
   ID/digest/profile/context/inventory/revision/time bindings, not just a shared outer hash.
5. Each later observation/stage/commit rechecks the same actual context and owned directory identities;
   payloads remain byte-identical to the factory's immutable tuple. No context refresh or payload
   replacement method; newly arrived unrecognized outgoing final refuses. Incoming/consumed remain
   metadata-only and interrupted stages remain opaque.

Do NOT infer candidate manifest/descriptor/provenance authenticity, OCI image digests, network/resource
declaration contents, UID/GID/broker/argv constraints NOT carried in the effect, absent actual installed
head, actual vault membership, inventory completeness, event existence or owner approval from these
checks. Those needthe later integrated producer's real candidate+CAS+DomainStore+journal and full38 source-join validator.
Structural inventory capacity0..16 atTask39 is notthe later integrated producer's zero/one supported-history admission. Context/
geometry and exact byte coherence are the publisher's entire source-bound claim. It performs no
slot metadata acquisition, DB migration, owner authentication, native stage or provider execution.


## Additional lifetime and behavior precision

observe_existing returns None only for an absent target after the complete expected-outgoing
inventory/source checks; otherwise it returns the exact existing, reread/fsynced observation.
stage requires an absent target and no active attempt. If the target already exists, refuse with
DeploymentSourceError; the caller uses observe_existing for that case. A concurrent final appearing
after staging is handled by commit's one no-replace attempt and exact existing-byte comparison.

A returned attempt is owned by its lease. commit is one-shot even if it fails: close/relinquish
that genuine owned attempt's FD on every exit, preserve the original primary, leave any honest stage/final disk
state and permit no second commit on the same attempt. Closing the attempt also clears that lease's
active-attempt ownership once. Lease.close marks closed before closing an active attempt and all
three owned directories, attempting all with primary-preserving aggregate cleanup. The borrowed
context remains owned by its original caller. Cross-lease or forged arguments must not close another
lease's attempt or caller-owned FD. No rollback/unlink on failed publication.

The shared _provider_namespace_policy resolver must validate exact selector type/name and return
the existing immutable policy; shared snapshot calls it and uses the same one fixed path mapping.
Do not duplicate policy literals or expose configurability. The combined context observation
performs the actual guard and derives identities and equal validated snapshots from that guard,
not caller tokens, saved dictionaries or detached post-guard samples. Public source reader API
stays unchanged and read-only.

## TDD, concrete acceptance and scope

- Before altering the two old publication helper bodies, add expected-GREEN ordinary
  characterizations in test_provider_publication_lifecycle.py. Prove exact bytes/names/modes/group,
  success/error classes, fsync sequence and left-behind stage behavior. This test module imports
  old helpers directly and is independent of provider fixtures for those old-helper tests.
- Reproduce the actual primary-masking failure with returned real FDs: read/stat/fsync failure plus
  secondary close failure in _existing_for_policy; write/chown/chmod/fsync/stat/validation failures
  plus secondary close failure in _stage_payload. Test KeyboardInterrupt/SystemExit/custom
  BaseException, exact original object, all still-owned close attempts, no double-close; distinguish
  close refusal from successful physical release. Existing old tests remain unchanged.
- Build actual accepted Task37 controlled source tree and Task38 valid canonical request/cancel
  fixtures. Use literal independently expected wire bytes and source facts; do not stub successful
  context checks or use publisher-produced values as expected results. Record meaningful RED.
- Test actual observe/stage/commit request and cancellation paths, exact-existing idempotence,
  same/different-byte final races, one-shot/cross-lease/forged/closed attempt refusal, borrowed
  context survives lease close and context closure invalidates operations, three owned identities.
- Enforce every expected_payloads grammar/count/order/canonical/profile/context/geometry/inventory/
  original-slot/cancellation binding above. Test0/16+16 entries,17ofeach, all caps, duplicate/sameID
  differentdigest/unmatchedcancel and unknown or malformed occupied final. Aggregate overflow is
  necessarily also constituent overflow; do not invent an impossible independent boundary.
- Test complete within-operation metadata stability except the exact owned stage/final transition;
  safe between-call updates are rescanned. Specifically mutate receipts/consumed between two
  successful context guards of ONE operation and require refusal; corresponding safe updates
  BETWEEN completed calls remain allowed. Do not stub successful context guards. Test unrelated stage replacement during operation,
  source/leaf/directory/mount replacement, symlink/hardlink/wrongmetadata and capacity exhaustion.
  Incoming/consumed payloads and other stages remain unread/unmodified; no cleanup scavenging.
- Track actual operation-owned FD peak: three lease directories plus at most one stage and one
  existing-read FD (excluding already-owned context and bounded lower-level transient opens).
  Include transient peak measurement and return to baseline on acquisition/operation/close failures;
  retained context lifetime plus caller-owned baseline is reported separately. At most256 total
  including the source context. No FD sweep or arbitrary VM/SIGKILL atomicity claim.
- Fresh import and unused factory have no filesystem/network/DB/model/credential effect. Actual
  publication tests simulate only allowed ownership/native/mount/fixed-path/syscall observations;
  real FD/name/bytes/fsync/rename/lifecycle behavior remains tested, not native qualification.

Freeze six hashes/full source manifest after self-review. Run once on frozen bytes with tracing
disabled and no cache provider:

    <workspace>/.venv/bin/python -B -m pytest
      app/tests/test_provider_publication.py app/tests/test_provider_publication_lifecycle.py
      app/tests/test_deployment_publication.py app/tests/test_deployment_source_lifecycle.py
      app/tests/test_provider_sources.py app/tests/test_provider_source_startup.py
      -q -p no:cacheprovider

Report all commands, RED/GREEN/failures, scoped diffs, exact hashes/outside preservation, measured
FD bounds and controlled-evidence limitations. Independent spec/quality review gates acceptance.
No source/domain/schema/API route/SQLite migration or slot-metadata operation is part of Task39.
