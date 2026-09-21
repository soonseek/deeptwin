# Runtime retained provider source context

Controller contract, 2026-09-19. Spec authority: ../spec.md, provider-source-production.md and
provider-source-observation.md. Task35/36 acceptance and independent preflight precede explicit
Task37 dispatch. No native operations, user data, model calls or journal/admission changes authorized.

**Goal:** Open the actual fixed provider bundle and related filesystem roots at control startup,
retain their identity, and make bounded source-currentness checks available to a later consumer.
**Architecture:** A read-only retained reader joins the startup-pinned18-file bundle to the actual
five original source files, current OriginProfile and fixed provider channel directories. A minimal
existing startup contribution hookup owns/exports the handle without passing it to old preparation.
**Tech stack:** Existing CPython filesystem/mount helpers, source codecs and pytest; no dependency.

## 1. Selected smallest complete boundary

Include the actual startup hookup, not a factory whose emitted context pin is silently discarded.
The present chain is `server.create_app` → `build_startup_inputs` → catalog startup_keys →
`deployment_prepare.prepare_services`. `build_startup_inputs` snapshots only catalog-declared keys.
Task35 emits DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256 but current STARTUP_KEYS contains only the nine
original pins. This is a code-owned registration gap, not missing external authority.

Read-only startup integration means adding one key and one optional owned source export to the
existing contribution. It adds no HTTP route, permission, stage service, admission result, database
write, event, reconciliation action or credential/model binding. Old preparation receives exactly
its existing five source arguments; the new handle is never an alias for an ExchangeSource,
ReceiptIngressSource, ConsumptionExchangeSource, TopologySource or qualified provider.

Task35 and Task36 acceptance are prerequisites. Current normative contracts explicitly exclude a
runtime opener; Task37 needs its own promoted contract and scope. Nothing here widens Task35/36.

## 2. Exact ownership

| Path | Change | Scope |
| --- | --- | --- |
| app/deployment/provider_sources.py | NEW | Final retained ProviderSourceContext and fixed public factory; raw bundle/profile/original-source joins and whole-read guards. |
| app/tests/test_provider_sources.py | NEW | Actual temporary-tree factory/currentness/mount/metadata/lifetime tests, including old-reader optional-root integration. |
| app/tests/provider_source_reader_fixture.py | NEW | Real fixed-layout temporary trees with explicitly simulated ownership/native/mount samples; independent reader observations and mutation hooks. |
| app/tests/test_provider_source_startup.py | NEW | Registered pin snapshot, optional export, actual source ownership, cleanup and no-admission wiring. |
| app/deployment/source_common.py | MODIFY | Append four fixed provider roots; extract existing optional-alias mapping into one private function and leave _Source._mapping_for a behavior-preserving adapter. No old-entry/lifecycle changes. |
| app/api/deployment_prepare.py | MODIFY | Add provider pin constant to the end of STARTUP_KEYS; import/open/own/export the optional context in prepare_services. No router/service/reconcile changes. |
| app/api/first_party_catalog.py | MODIFY | Add exactly deployment-provider.source-context to the existing deployment contribution's provides tuple. No new contribution/descriptor/scope/route. |

Four new files, three narrowly modified files. Task36's shared _provider_source_files.py is read-only
and reused unchanged under provider-source-observation.md. No source codec/schema/recipe/Compose/export edits,
no changes to files.py/public_init_files.py/mounts.py/RetainedHandle, no initializer/helper refactor,
no first_party.py/server.py or descriptor edits, no old test edits. Any unexpected need for those
changes returns to controller review rather than expanding this tranche.

## 3. Public and private interfaces

Public provider_sources interface:

    PROVIDER_CONTEXT_STARTUP_KEY = "DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256"

    open_provider_source_context(
        *, profile: OriginProfile,
        context_sha256: str,
        protected_roots: tuple[Path, ...],
    ) -> ProviderSourceContext

    ProviderSourceContext.read_current() -> tuple[tuple[str, bytes], ...]
    ProviderSourceContext.recheck_current() -> None
    ProviderSourceContext.close() -> None

The returned tuple is precisely the18 ordered bundle files, not parsed caller dictionaries or a
new authority record. Each read performs the complete guard before returning immutable bytes.
`recheck_current` performs that guard without returning documents. No bare cached-bytes property,
public constructor, path parameter, document selector, FD accessor, transport callback, native
override, source URL, arbitrary policy or refresh/rebind method. Exact-type/hollow/subclass checks
reject unsupported handles; closed operations raise DeploymentSourceError. Copy/deepcopy/pickle
remain denied via retained-handle conventions. Python object identity is not an admission secret.

No new schema version, identity token, source record, signature or HMAC is introduced. Later code
must hold the actual handle and recheck it around its own effects; returned bytes are inert data,
not a lease for arbitrary future effects. This tranche grants no payload/operation capability.

Shared read-only interfaces are exactly provider-source-observation.md:
_open_provider_bundle(root, *, context_sha256) and
_snapshot_provider_namespace(directory, *, namespace). Import the accepted Task36 implementation
unchanged; no duplicate observer, filename/cap/policy tables or namespace snapshot algorithm.
Factory acquires/owns the static root and lends it to the shared bundle; bundle closes only children.
Runtime-specific channel-root retention, aggregate/within-call snapshots and normalized mount guards
live privately in provider_sources.py. They are not a new public configurable filesystem API.
The runtime never imports/calls the operations publication helper or source initializers.
Use Task36-corrected Directory/SourceFile for roots and original singleton sources, and unchanged
mount helpers. Do not subclass source_common._Source to fake its single-source field or aggregateclose.
This context owns a multi-document graph and implements explicit exhaustive cleanup.

## 4. Bootstrap and error behavior

At factory entry require exact OriginProfile, strict lowercase hex64 context_sha256, tuple of at
most64 absolute protected Paths of1..4096 UTF8 bytes with no `..`. Deduplicate protected roots
lexically with fixed contracts.BUILTIN_ROOTS; never resolve symlinks to bless them. Reconstruct the
supplied profile using OriginProfile.from_dict(profile.as_dict()) and compare complete content.
This is the startup-owned expected origin, not an HTTP body/profile override.

Call actual mounts.native_platform before filesystem acquisition: only linux/amd64 and linux/arm64;
Darwin/Windows/unsupported machine returns DeploymentSourceUnavailable. Do not use host uname
fallback, environment platform override, positive non-Linux mode or a fabricated Mount observation.
This reader is not the UID0 initializer: it neither requires root nor grants control identity from
the caller's UID. Source metadata/mount checks describe the fixed control mount view, not identity
of a stage operator or live sender. Real read permission failures remain closed failures.

`prepare_services` obtains profile from context.owner_authority.profile, protected roots and pin
from the already-frozen context.startup_inputs. It never reads os.environ directly or takes browser
input. Append the key after the nine historical STARTUP_KEYS, preserving their positional indexes.
Missing/invalid pin or DeploymentSourceError yields `deployment-provider.source-context: None`
without disabling old services. Do not open provider paths at all for an absent/invalid pin.
Valid configured pin plus invalid/missing sources also exports None; no synthetic empty handle,
automatic initializer, scan/discovery fallback or config reload. Process-control exceptions propagate.

When open succeeds, immediately register ownership with existing `_own_source(stack,resources,...)`
before constructing the unchanged PersistentDeploymentPrepare and ContributionServices. Add the
handle only to owned_resources and the new export. Keep existing deployment-prepare.service export
and original router unchanged. The catalog provides declaration must match exactly both exports.
Composition/startup/shutdown cleanup uses the existing owner; no reconcile call uses this context.
An environment change after build_startup_inputs cannot retarget it. A stale exported handle fails
on its next check, not by advancing any readiness/admission state.

Factory/read errors use existing fixed DeploymentSourceError/DeploymentSourceUnavailable codes,
not filenames, content, tracebacks or extra diagnostics. Structural/profile/pin/currentness conflicts
are invalid; unavailable native/filesystem reads retain unavailable where helper APIs distinguish it.
Map ordinary OSError to unavailable; do not catch arbitrary programming exceptions as success.
Preserve primary BaseException objects and attempt all owned closes on failed acquisition/read
construction. No logging or event emission is introduced.

## 5. Exact retained graph and joins

Static root is /run/deeptwin/provider-stage-sources, owner0:21201 mode0750, containing exactly
documents/. That directory is0:21201/0750 with exactly the following ordered files; every file is
regular, nonempty, single-link,0:21201/0440. All caps, full signatures and identities are checked.

| Filename | Cap B |
| --- | --- |
| original-prepare-recipe.json | 4096 |
| original-prepare-instance.json | 4096 |
| original-topology.json | 65536 |
| original-outgoing-exchange.json | 8192 |
| original-receipt-recipe.json | 4096 |
| original-receipt-instance.json | 4096 |
| original-trust-set.json | 16384 |
| original-receipt-ingress.json | 8192 |
| original-consumption-exchange.json | 8192 |
| geometry.json | 65536 |
| provider-recipe.json | 8192 |
| provider-instance.json | 8192 |
| provider-trust-set.json | 16384 |
| outgoing-exchange.json | 8192 |
| receipt-ingress.json | 8192 |
| consumption-exchange.json | 8192 |
| source-context.json | 16384 |
| source-pins.json | 8192 |

Read source-context.json first with its own bounded retained FD; require its SHA256 equals the
startup scalar. Its document names/hashes never direct path traversal: open only the code-owned
table above and return that exact order. Reuse its already-open leaf rather than open a duplicate.
Retain all18 leaf FDs, documents FD and static root FD. Aggregate bytes≤524288, not merely individual
caps. Keep full static signatures, exact membership and original path↔FD identity for lifetime.

Call `validate_provider_source_bundle(bundle_files)` on exact bytes, then parse context/pins/instance
and original prepare instance with the contract APIs. Required graph closure is not a local partial
parser or caller's successful validation flag:

1. Context digest and context_size match actual context, pins describe actual bytes; first16 context
   references have exact order/name/hash/size, no extra/self/pins reference. Epoch remains1.
2. Original recipes match unchanged code-owned recipes. Original prepare instance/profile/topology/
   capacity/platform and every exact slot geometry agree; original four IDs remain distinct.
3. Original outgoing ID equals prepare exchange ID; receipt instance pins bind actual prepare
   instance/trust bytes; original ingress and consumption IDs and all dependent digests bind actual
   bundle documents. Task35's explicit deferred original joins must be retained, not skipped.
4. Provider recipe matches the final code-owned recipe. Provider instance pins actual original
   instances, geometry, recipe and provider trust. Its four new IDs are disjoint from each other
   and the four original IDs. Do not generate another topology ID or source epoch.
5. Provider trust origin/instance/deployment profile and fixed adapter declaration agree; all three
   provider channel documents bind actual provider recipe/instance/geometry and directed exchange/
   ingress/trust hashes. This parses public declarations; it verifies no operator signature.
6. Complete original OriginProfile equals startup owner profile, not merely its instance ID;
   original instance/geometry platform equals actual sampled native platform.

Then retain the actual five historical public sources with SourceFile.open and hash pins derived
from their validated bundle copies; compare complete bytes, not just hashes. No old channel reader
is invoked: those readers may parse old payloads or expose publication methods.

| Actual root / leaf under /run/deeptwin | uid:gid | Bundle file |
| --- | --- | --- |
| extension-topology/topology.json | 0:20102 | original-topology.json |
| deployment-exchange/exchange.json | 0:21201 | original-outgoing-exchange.json |
| deployment-verify-public/trust-set.json | 0:20102 | original-trust-set.json |
| deployment-receipt-ingress/ingress.json | 0:21201 | original-receipt-ingress.json |
| deployment-consumption-exchange/consumption-exchange.json | 0:21201 | original-consumption-exchange.json |

Historical roots0750/leaves0440, original caps unchanged. No release/initializer-input files, base
Compose, expansion record, image, key secret or registry fetch is required at runtime: complete
source-byte joins are already defined without them. No new trust anchor is invented to fill a gap.

## 6. Fixed channel layout and meaningful currentness

Retain all three channel roots and four namespace directories with these exact ownership/mount
rules. Root and namespace mode0750, gid21201; roots have exactly their listed child directories.

| Root under /run/deeptwin | uid | Control mount | Namespace and policy tuple |
| --- | --- | --- | --- |
| provider-deployment-outbox | 20102 | rw | cancelled=(20102,20102,21201,16,32,8192); requests=(20102,20102,21201,16,32,65536) |
| provider-deployment-receipts | 20113 | ro | receipts=(20113,20113,21201,64,32,16384) |
| provider-deployment-consumed | 20102 | rw | consumed=(20102,20102,21201,16,32,8192) |

Policy order is writer_uid,primary_gid,pair_gid,final_limit,stage_limit,payload_cap. The accepted shared read-only helper owns these exact fixed policies; do not duplicate them,
modify old4096-byte policies or import initializer state. Keep exact hex64.json and nonnil canonical .stage-UUID.tmp grammar and scanner metadata
rules. Maximum96 entries per namespace,240 total; scan/stat only, no per-payload FD.

Crucial distinction from the one-shot initializer: channel inventory is mutable between successful
runtime checks. Pin channel root/namespace directory identities, owner/group/mode and mount mapping
for handle lifetime, but do NOT freeze channel file membership or namespace mtime at initial open.
An otherwise valid later publication/removal/stage transition must not permanently invalidate an
unchanged static source context. A channel snapshot is not a journal inventory/head snapshot. An ordinary read/check refusal leaves
this handle owned and without rebasing its immutable state; a later explicit check may retry fresh
channel observation. No automatic loop/reacquisition. Process-control interruption closes all owned
resources before propagating the same primary object.

Each complete read/check takes a fresh complete metadata snapshot of all four namespaces, including
all final AND stage names/stat signatures, using before/after bounded capture around _scan_namespace.
After static/original/mount checks, take the second complete snapshot and require equality within
this operation. This catches same-count stage replacement, unrelated concurrent publication and
cross-namespace movement during a read. No retry loop; caller receives the closed error. A later
explicit check may observe a new safe inventory, but it cannot refresh immutable source or retained
directory identities. No channel payload is ever opened, parsed, hashed, signature-checked, repaired,
deleted or returned. Metadata-safe wrong JSON/hash/signature bytes remain non-authorizing data.

The static bundle, actual original sources and protected directory identities never rebase.
Every public read checks native platform, exact bytes, names, full static signatures, path↔FD
bindings and relevant mount mapping before and after channel observation. A byte-identical new
inode, replaced documents directory, altered recipe/context or new mount is still stale and denied.
No new v2 requests/receipts/consumption markers, file leases or consumer semantics are defined here.

## 7. Mount and original-reader integration

Required exact mount roots are the four provider roots (ro,rw,ro,rw in the tables above) and five
original public roots (all ro). Require exact mountpoint, correct control read-only flag, no nested
mount/overlay, correct retained device, no prefix/backing overlap and no duplicate inode objects.
Do not add documents/ or original source leaves as separate protected paths below their own required
root: existing verify_boundaries deliberately rejects those overlaps. Their FD/name checks and
required-root no-descendant-mount rule cover them. Protected startup directories/builtin roots are
retained with search=True; preserve their existing observed modes/ownership and permit their intended
writable mounts, rather than imposing the initializer's read-only input requirement on app data.

Extract the existing mapping/optional-alias algorithm once into private
source_common._source_mount_observations(observed, required, protected_paths).
It receives one already-sampled bounded Mount tuple, existing required readonly mapping and lexical
protected paths; performs no sampling/acquisition/callback/lifecycle or configurable policy choice.
Use the one code-owned _OPTIONAL_SOURCE_ROOTS and unchanged mounts.verify_boundaries, retaining
all existing alias predicates and cross-optional-group semantics. Return (checked, optional):
checked has the unchanged verify_boundaries tuple shape; optional is immutable
(optional_root, (mountpoint, Mount, backing_path)) pairs sorted by root then mountpoint.

_Source._mapping_for reads mountinfo ONCE, calls this function with the same required/protected
values, and returns exactly its historical filtered checked tuple. Old readers do not start
retaining optional observations or change currentness/error/ownership/close behavior.
The new context samples once per observation, calls the same function and retains both checked
and optional tuples. Relevant optional additions/removals/replacement/nested changes invalidate
it; unrelated mount-table order/content do not. No manufactured receiver/fake _Source, duplicated
alias block, second sampling for retention, alternate sampler or generic observer framework.
No host/container label lookup or Docker proof.

Append these four literal Paths to source_common._OPTIONAL_SOURCE_ROOTS, preserving all old entries:

    /run/deeptwin/provider-stage-sources
    /run/deeptwin/provider-deployment-outbox
    /run/deeptwin/provider-deployment-receipts
    /run/deeptwin/provider-deployment-consumed

This makes old retained readers reject a provider-volume alias even when the provider pin is absent.
Independent nonalias provider mounts remain optional and do not change old source outputs. No
changes to _open_pinned_source or _Source.close are permitted. Only _mapping_for's thin extraction
adapter changes; it does not retrofit old lifecycle behavior or make provider roots mandatory for
old readers. Before extraction add expected-GREEN characterization/parity tests in the already
owned new test file for safe optional roots, nested/cross-group aliases, old return shape and one
sample per observation. Preserve all existing tests and ordinary behavior.

## 8. Resource lifetime and finite work

At most256 owned live FDs including transients. Fixed bundle20, old sources10, channel directories7,
and at most74 deduplicated builtin/additional protected directory FDs fit this bound. No FD per
channel entry, no recursive tree walk; mountinfo retains existing1MiB/4096-line limits. Track every
returned FD/handle locally immediately; failure at later acquisition, validation or first full read
closes all already-owned resources. No caller-owned handle is accepted or closed.

Reuse accepted Task36 factory cleanup, not copied unsafe acquisitions. New aggregate close is
idempotent, marks closed first and attempts all independent owned resources; primary failure wins,
otherwise first cleanup error propagates after all attempts. New factory cleanup catches BaseException
only to clean up and re-raise the original process-control object. The existing startup owner may
apply its already-defined sanitized aggregate-close policy; do not change that global policy.
No FD sweep/global manager, retry of attempted close, repair, rollback or arbitrary VM/SIGKILL
atomicity promise. No operation of this reader creates/chowns/chmods/fsyncs/renames/unlinks files.

## 9. TDD and narrow acceptance

Use TDD at explicit dispatch; this document reports no performed test. Missing Task35/36 imports
are prerequisite failures, not useful RED evidence. Keep original tests unchanged.

| Boundary | Decisive tests |
| --- | --- |
| Fixed factory | Valid actual18-file bundle plus five original roots and safe channels returns exact tuple; both original origin modes, both platforms, capacities1/16. No constructor/root/native/callback override; import has no I/O. |
| Bootstrap pin | Registered key copied once by build_startup_inputs; invalid/missing key opens nothing; later environment mutation ignored; wrong pin closes acquisition; full valid refreshed alternate context cannot pass an unchanged startup pin. |
| Full joins | A structurally valid wrong original/channel/trust/geometry document with downstream context/pins refreshed and selected as the configured pin still fails its actual source/profile/cross-document join. This distinguishes full graph validation from outer-hash checking. |
| Retention | Wrong root/leaf owner/mode/link/type, alias, membership/cap/aggregate overflow; changed raw bytes/signature, same-byte inode replacement, documents replacement, old-source replacement and platform change deny. Test at opening and later checks. |
| Channel currentness | Metadata-safe malformed payloads/all stage states succeed untouched with payload-open/parser spies; valid between-call publication/removal succeeds without context rotation; mutation during either snapshot or between snapshots fails, including same-count stage mutation. Namespace replacement always fails. |
| Bounds | Incoming64+32 and aggregate240 accepted; each final/stage/size boundary and overflow denied; cancel/consumed8192 accepted here while old4096 tests still pass;≤256 peak FDs. |
| Mounts | Correct control flags, required exact root, child overlay and backing/prefix/device alias failures, optional old/new nested-mount aliases; optional map replacement invalidates new reader; unrelated mount ordering/content irrelevant. Old reader behavior unchanged absent providers; present safe provider mounts accepted, aliases rejected. |
| Lifetime | Inject KeyboardInterrupt/SystemExit/custom BaseException at recorded bundle/original/channel/protected acquisition and initial guard checkpoints. Same primary survives secondary cleanup; all known independent closes attempted, no double-close or borrowed ownership. Successful real closes return FD count to baseline. |
| Startup integration | Existing five source objects remain exact old service dependencies; optional new sixth owned context exported only in-process, not passed to service/router/reconcile. Composition/factory/activation/shutdown failures release it through the actual existing application owner lifecycle. activate_startup alone does not own cleanup; no global activation/owner change. No new route, event, record, key/HTTP/Docker operation or source mutation. |

Fixture creates real bytes/directories/FDs; simulate logical-path mapping, uid/gid and native/mount
sampling only at test boundary. Do not stub the factory, full bundle validator or retained read checks
for positive reader tests. Use Task35's accepted independent bundle fixture plus literal expected
path/cap tables; do not generate expected bytes by calling the reader or initializer under test.
Startup tests may spy factory arguments for wiring, but at least one valid startup case uses the
real reader temporary tree. No native isolation/image proof follows from these simulations.

- [ ] Add actual-reader positive/negative tests; record assertion-level RED after dependencies are accepted.
- [ ] Compose the accepted shared read-only helper into the complete runtime factory; prove all graph/retention/metadata guards.
- [ ] Characterize old mapping behavior before extraction; share the private alias observer and append four optional root literals, preserving old return behavior.
- [ ] Add startup pin/ownership tests, then make the two small contribution wiring edits.
- [ ] Run focused and unchanged covering tests; review exact seven-file scope and absence of effects.

Focused future command:

    python -m pytest app/tests/test_provider_sources.py app/tests/test_provider_source_startup.py

Narrow unchanged covering families:

    python -m pytest app/tests/test_deployment_sources.py \
      app/tests/test_deployment_receipt_sources.py app/tests/test_deployment_source_files.py \
      app/tests/test_deployment_source_lifecycle.py app/tests/test_first_party_dependencies.py \
      app/tests/test_deployment_prepare_api.py app/tests/test_deployment_receipt_api.py

Run accepted Task35 source-contract/bundle tests as dependency coverage if the dispatch requires;
do not expand to a project audit or native run. Report exact commands/results, file manifest,
observable FD bound and controlled-test limitations; this contract claims no performed passing run.

## 10. End state and explicit non-authority

This delivers a startup-owned current byte source, not another temporary inert context schema.
There is a coherent bounded tranche: the complete immutable source graph and current mount layout
are already defined, and Task36 supplies the needed acquisition lifecycle. No unbuilt image digest,
future operator field or admitted journal operation is needed to read it correctly.

Not yet supplied: payload publication/consumption validation, per-publication retained leases,
transactional journal/history and globally unique slot reservation migration, inventory/head
snapshots, stage request/receipt signature verification, native operator or image identity,
installation acceptance, all-five-check qualification, binding/connection/model-choice admission,
approval/billing credential authorization or actual live-send issuer. Those must consume this
current handle under their own contracts; they cannot infer admission from a public trust document,
stable metadata, successful identify observation or a non-None startup export.

Old topology/profile/slot identities and all historical reservation semantics stay unchanged. No
second slot registry, replacement/reuse lifecycle or source-context rotation is added. Task30
stored_unbound credentials remain unbound; Task32 generation remains denied. Claude API-only and
Codex subscription plus optional API scope remain unchanged. Browser-visible controls/OSS graph
LLMOps/DeepTwin integration are not advanced by inventing readiness from this internal reader.

The exact seven-file scope includes the read-only startup hookup. A factory-only implementation
would leave the catalog registration gap open and cannot satisfy this task.
