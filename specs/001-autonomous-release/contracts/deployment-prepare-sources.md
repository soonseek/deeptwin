# Deployment prepare sources v1

Normative source-I/O boundary for resumption Task9 and its subsequent owner/journal consumer.
This contract does not claim implementation, packaged images, real mount qualification or installed
workers. Canonical tasks T025/T087 and the full release gates remain open. Parent sequencing and
trust rulings are recorded in the resumption ledger. Browser users are not asked to operate a CLI.

## 1. Artifacts, hashing and deterministic order

R/I/T/E/P/A are closed canonical ADR008 JSON, reject duplicate/unknown fields and bool
integers, and have no self-digest. X alone is the deterministic Compose JSON exception below. All hashes below are SHA256 lowercasehex64 over exact complete
bytes. `SizedInput={path,sha256,size_bytes}`; paths here are the exact installed release paths, not
arbitrary filesystem locators. UUIDs are canonical nonnil; instance IDs are existing lowercasehex32.

**Release recipe R**, new `deploy/security/deployment-prepare-recipe-v1.json`, <=4096bytes,
depth6/items128, exact fields:

```text
{schema_version:"deployment-prepare-recipe-v1",
 recipe_id:"ordinary-tool-slots-v1",
 base_compose:{path:"deploy/compose.yaml",sha256:HexDigest,size_bytes:1..1048576},
 base_service_ids:{path:"deploy/security/service-ids.json",sha256:HexDigest,size_bytes:1..65536},
 renderer_id:"deeptwin-prepare-expand-v1",
 initializer_id:"deeptwin-prepare-source-init-v1",
 slot_capacity_max:16,
 slot_budget:{memory_bytes:1073741824,cpu_millicores:1000,pids_limit:128,tmpfs_bytes:134217728}}
```

These budget values are the first profile's fixed operator allowance, not measured host capacity.
No arbitrary resource policy, UID, mount, Compose fragment, command or template is an input to R.
The recipe's hashes must match the **unchanged raw bytes** of the two current release inputs. Never
rewrite them to absorb the recipe, and never replace historical frozen build-input evidence.

**Instance input I**, `prepare-instance.json`, <=4096bytes/depth6/items128, exact fields:

```text
{schema_version:"deployment-prepare-instance-v1",
 origin_profile:<exact existing OriginProfile>,
 topology_id:UUID,exchange_id:UUID,
 platform:"linux/amd64"|"linux/arm64",slot_capacity:integer1..16}
```

IDs are external-operator-selected explicit persisted inputs, not generated anew by the renderer.
topology_id and exchange_id must differ. No timestamp/RNG/deployment credential is used during pure
rendering. Browser owners cannot submit I, R or replacement source pins through the application.

From exact B (base Compose), S (base service identities), R and I, produce **T** (`topology.json`)
using §8's complete `extension-topology-v1` shape, with R's hash as
deployment_recipe_digest and S's hash as static_service_identity_digest. Its slot_budget is R's
fixed budget, its OriginProfile identity/digest/platform come from I. Its cap remains65536bytes,
depth12/items2048. Production source directory is0750, independent of T's IPC root layout.

Produce **E** (`exchange.json`) exactly as §3 below. Then produce **P**, `prepare-source-pins.json`,
<=4096bytes/depth4/items64:

```text
{schema_version:"deployment-prepare-source-pins-v1",
 instance_id:hex32,origin_profile_digest:HexDigest,
 recipe_sha256:HexDigest,instance_sha256:HexDigest,
 topology_sha256:HexDigest,exchange_sha256:HexDigest}
```

Finally produce **X**, `compose-topology-expansion.json`, the deterministic full Compose object with
only §2's changes, bytes <=1MiB/depth32/items10000. X is serialized as strict UTF8 JSON
using sorted keys, compact separators, ensure_ascii=false and allow_nan=false, preserving the
verified base's finite CPU fractions (0.25/0.5/1.0). X is not a domain canonical document: do not
weaken ADR008's no-float rule to accommodate it. Verify B's exact recipe hash before parsing X's
base, reject duplicate keys/nonfinite values, and preserve its original numeric CPU values. This is explicitly a **topology-only
expansion**: inherited release image/TLS/profile variables and the new initializer-image variable
still require existing release/operator resolution. It is not a ready-to-run final service-image
manifest. Preserve both the unchanged base-template bytes/hash and X's distinct bytes/hash.

**Expansion record A**, `prepare-expansion-record.json`, <=4096bytes/depth4/items64:

```text
{schema_version:"deployment-prepare-expansion-record-v1",scope:"topology_only",
 base_compose_sha256,base_service_ids_sha256,recipe_sha256,instance_sha256,
 topology_sha256,exchange_sha256,pins_sha256,
 expanded_compose_sha256,expanded_compose_size_bytes:integer1..1048576}
```

A is an unqualified build/expansion record, not a signature or runtime observation. Compute A last.
The graph is B/S→R; B/S/R/I→T/E→P→X→A. Neither T nor E contains X/P/A hashes; X includes T/E pins
but not its own hash. Thus source/expanded-Compose hash cycles cannot arise. Publish R/P/X/A hashes
through the privileged operator deployment record; do not trust an A file supplied by a candidate.
Both required hosts retain the same B/S/R bytes, one common two-platform OCI source index and each
instance's exact I/T/E/P/X/A plus descriptor variant; no silent arbitrary per-host base Compose.

## 2. Exact finite expansion, not arbitrary fragments

The renderer rejects unknown base hashes or collisions and returns inert files; it performs no
Docker/Portainer/network/process operation. Every original service/volume/network/config subtree
is structurally unchanged except the following enumerated additions to control. Preserve existing
array order; append new groups/mounts in numerical slot order. Fail on a preexisting conflicting key,
never override it. The original B/S files themselves remain byte-for-byte unchanged.

1. Add control supplementary group21201 and slot groups23001..23000+capacity. Add RO mounts for
   topology-public, exchange-public and each IPC slot; add the RW outgoing mount. Add dependency
   `deployment-prepare-root-init: {condition:"service_completed_successfully"}`. Add literal
   environment pins from P under `DEEPTWIN_PREPARE_RECIPE_SHA256`, `DEEPTWIN_PREPARE_INSTANCE_SHA256`,
   `DEEPTWIN_TOPOLOGY_SHA256`, `DEEPTWIN_EXCHANGE_SHA256`. Task10 supported startup reads these exact
   optional nonsecret inputs without modifying the existing bootstrap-configuration shape. They are
   operator configuration, not values discovered from either source file or writable outbox text.
2. Add logical volumes `extension-topology-public`, `deployment-exchange-public`, `deployment-outbox`
   and `ipc-xs01`..`ipc-xsNN`. Each has explicit `name` derived below, never implicit Compose project
   prefixing. All control/initializer volume entries use exact fixed container paths, nocopy=true
   and exact RO/RW flags; no bind mount/host path or candidate-selected name is generated.
3. Add one root-only, network-none, read-only-image one-shot service `deployment-prepare-root-init`.
   Its image is the required `${DEPLOYMENT_PREPARE_INIT_IMAGE:?exact @sha256 image required}` release input, which
   must resolve to an exact @sha256 image before real deployment. Fixed entrypoint is
   `["python","-m","app.operations.deployment_prepare_init"]`, command=[], user0:0,
   restart=no, init=true, privileged=false, cap_drop=[ALL], cap_add=[CHOWN,FOWNER,FSETID],
   group_add=["21201", "23001", ..., str(23000+capacity)] in exact numeric slot order
   (outbox read/search plus search of each responder-owned endpoint during restart metadata checks),
   security_opt=[no-new-privileges:true], tty=false, stdin_open=false, pids_limit32, mem_limit64m,
   cpus0.25, nofile soft/hard256. No DAC_OVERRIDE/DAC_READ_SEARCH or wider endpoint modes are added.
   The slot groups do not permit listing or writing responder-owned endpoints; known-name search
   remains permission-checked and only ENOENT means absent. It mounts only the new public sources/outbox/slots RW and its
   operator input configs RO; no old state, session, credential, signing or receipt volume.
4. Add two exact external Compose config resources for I and P, named
   `dt-<instance>-prepare-instance` and `dt-<instance>-prepare-pins`, mounted into that initializer
   at `/run/deeptwin/prepare-init-input/prepare-instance.json` and
   `/run/deeptwin/prepare-init-input/prepare-source-pins.json`, UID/GID0:0 mode0440. The initializer
   image precreates the root-owned0:0 parent directory0750. R/B/S are release-packaged under the fixed image installation root
   `/opt/deeptwin` (paths in R relative to that root) and verified against pins. No cwd search,
   environment path override or arbitrary CLI filename is accepted.
   Actual Compose config ownership/support remains a platform gate; do not substitute a host bind.

All added physical volumes have the names/paths below. For slot number n formatted two digits:
service `ext-<instance>-NN`, channel `cp-ext-<instance>-NN`, UID/GID22000+n, pair GID23000+n;
mount ID xsNN, volume `dt-<instance>-ipc-xsNN`, path `/run/deeptwin/ipc/xsNN`, socket worker.sock,
protocol deeptwin-extension-worker-v1. Existing PairRootSpec governs root0:pairGID0710,
endpoint responderUID:pairGID02710 and root-owned generation metadata0640. The descriptor must
already equal these declarations. No extension service is created by this recipe.

Existing `ipc-root-init` service and its command list remain untouched. `ipc_root.py` currently
exposes `initialize_pair_root` as a function (`:522`); no packaged module CLI is established by its
Compose flags (`compose.yaml:394`). The new entrypoint/function must actually be implemented and
packaged/qualified in its declared image before a runnable deployment can be claimed. A generated
image-variable string is not evidence that that image or entrypoint exists.

## 3. Exact independently pinned outgoing exchange source

Reserve receipt-job UID/GID20113 and exchange group21201. The static file ends at
service20112 and pair21110 (`deploy/security/service-ids.json:17,31`); no concrete conflict found.
Reserve these in R's versioned profile, without modifying S or creating any job now. The future
reader identity is `deployment-receipt-job`; it must use supplementary21201 and an RO outbox mount.
That identity reservation gives it no signing key or Docker access.

E cap8192bytes/depth8/items256; exact fields and constant values:

```text
{schema_version:"deployment-outgoing-exchange-v1",
 exchange_id:UUID,revision:1,instance_id:hex32,origin_profile_digest:HexDigest,
 deployment_recipe_digest:HexDigest,instance_configuration_digest:HexDigest,
 control:{service_identity:"control",uid:20102,gid:20102},
 reader:{service_identity:"deployment-receipt-job",uid:20113,gid:20113,pair_gid:21201},
 outgoing:{volume_name:"dt-<instance>-deployment-outbox",
   container_path:"/run/deeptwin/deployment-outbox",
   owner_uid:20102,group_gid:21201,root_mode:"0750",namespace_mode:"0750",
   final_file_mode:"0440",control_read_only:false,reader_read_only:true,
   namespaces:["cancelled","requests"]}}
```

E does not reference T, a request, a receipt, future evidence, or an expanded Compose digest.
Recipe and instance hashes point backward to R/I. Source UUID/pin persists across normal restarts.
Changing it is unsupported maintenance, never an automatic new outbox for old pending requests.

| Object | Physical volume / fixed control path | UID:GID / mode | Control mount |
| --- | --- | --- | --- |
| topology source | dt-INSTANCE-extension-topology-public / /run/deeptwin/extension-topology | root0:20102 /0750; topology.json0440 | RO |
| exchange source | dt-INSTANCE-deployment-exchange-public / /run/deeptwin/deployment-exchange | root0:21201 /0750; exchange.json0440 | RO |
| outgoing root | dt-INSTANCE-deployment-outbox / /run/deeptwin/deployment-outbox |20102:21201 /0750| RW |
| outgoing namespaces | same volume / cancelled and requests |20102:21201 /0750| RW |
| outgoing final files | same namespaces / exact digest.json |20102:21201 /0440, regular/single-link| RW volume, read-only file |

INSTANCE means the exact lowercasehex32, not a literal placeholder accepted at runtime. A source
root contains exactly its one named JSON file, and outgoing root exactly its two namespace dirs.
No source manifest lives inside writable outbox. Initializer receives these same paths RW; future
receipt job may mount exchange source and outbox RO and receives only21201, not control's20102 group.
Control's supplementary21201 permits setting new projection-file group21201 using fchown(-1,21201)
before final fchmod0440/fsync. Root/namespace ownership and mode are only established externally;
control must not mkdir/chmod/chown roots to fix failed source checks.

Filenames stay `requests/<decoded-request-digest-hex>.json` and
`cancelled/<decoded-request-digest-hex>.json`. Staging names inside the corresponding directory are
`.stage-<nonnil UUID>.tmp`, exclusive-create0600, later group21201/final0440. Each directory is bounded
to16 final names plus32 staging names; extra/unknown/symlink entries inhibit projection, never
auto-clean them. Final payload caps are64KiB request and4KiB cancellation. No consumed namespace,
receipt inbox or signing/public-key volume is initialized here. A future receipt channel must be a
different volume with opposite writer/reader ownership, never an alias or an RW inbox for control.

## 4. Operational producer, restart and packaging boundary

Minimal implementation surfaces:

- Pure `render_prepare_sources(base_compose_bytes,base_service_ids_bytes,recipe_bytes,instance_bytes)`
  returns exact T/E/P/X/A bytes under fixed output names. The result is ordinary inert data, not
  a verified topology handle or installation permission.
- New `app/operations/deployment_prepare_init.py` provides fixed `main()` (no path/UID/fragment
  CLI overrides) and `initialize_prepare_sources()` using the fixed input/source/outgoing/slot
  paths and fixed `/opt/deeptwin` release root. Only the external root-init service calls it; supported control never imports/calls its
  initializer. Tests call factored low-level file routines with real temporary directories.

The operational function requires Linux UID0, validates exact no-follow root-owned operator input
files and R/B/S/P hashes, recomputes T/E from I and compares P, validates actual mounted boundaries
and aliases as below, then handles only its explicitly mounted **new** volumes. New IPC pairs use
existing initialize_pair_root in this external lifecycle, not copied key code. Its boot-secret
generation stays that existing IPC contract; no signing/session/credential secret is generated by
the public-source writer. Existing initialized IPC generations use existing initializer locking;
this is not permission to rotate a live channel behind its lease.

For a genuinely empty source volume, establish its specified ownership/mode and publish only the
expected canonical JSON file with exclusive staging, no-replace rename, file+directory fsync.
For a genuinely empty outgoing volume, establish root and exactly two empty namespace directories
with specified ownership/mode and fsync. Create children before handing root ownership to control;
without DAC_OVERRIDE the root job's21201 group then permits read/search, not further directory writes.
Existing roots are **verify-only**, never broad chmod,
overwrite, truncate or cleanup. An existing outbox with valid bounded projections is preserved;
the initializer does not decide their DB lifecycle or replace them. Existing valid source bytes
must equal this exact pin. A wrong/partial/extra file fails closed. Independent empty roots can be
initialized after other roots were already installed exactly; there is no multi-volume atomicity
claim. Abandoned staging/partial ownership failures require explicit external recovery, not clearing
the directory or reporting readiness. No control start until the one-shot initializer succeeds.

The writer's result contains only `{topology_sha256,exchange_sha256}` matching P. It is a bounded
initialization result, not independent mount provenance or a deployment receipt. Source file/digest
verification and root-init image packaging are different gates. Unit tests with temporary owner
metadata do not make the current skeleton a deployed Linux/Portainer qualification.

## 5. Retained-FD readers and publication boundary

Concrete topology/exchange sources are constructed by supported startup from the fixed production
paths, exact independently supplied P pins and actual OriginProfile. No public proof constructor,
`approved=True`, arbitrary source callback or candidate path is accepted. A parsed E is only data.
The shared low-level reader walks every component without symlinks, retains directory/file FDs,
verifies exact file type/single link/owner/group/mode/size and pre/post-read stat identity, checks
exact source directory membership, recomputes its pin and reopens the named path to detect swaps.
Validate recipe/instance/origin bindings against startup, not merely self-consistency inside E.

For Linux mountinfo implement/use the bounded strict parser:1MiB/4096entries/8KiB line, exact escape
decoding. Require sources on distinct RO mountpoints, outbox on its exact RW mountpoint and no
nested mounts below these roots; namespaces are ordinary child directories in the same outbox mount.
Use actual fd identities and mount mappings to reject aliases/overlap among topology, exchange,
outbox, IPC pairs and protected control-visible mounts. Protected mounts include actual data/session
root, built-in IPC, bootstrap/operator config and any configured public trust or other exchange root;
do not open private keys to check directory relationships. Reject same device/inode identities and
same-filesystem backing-root overlap, not just identical path strings. Deny namespace symlinks,
unexpected entries, wrong file groups, RO outbox/RW source inversion, replacement of a held path and
unexplained mount-map changes. Fresh pathname/mount checks accompany each bounded publication.

Stat/mountinfo proves only namespace/ownership facts observed in this process. It does not establish
Docker named-volume names, no-host-bind provenance or absence of hidden mounts in other containers.
Those remain trusted external-operator declarations validated against the release recipe. No tool
here calls Docker to upgrade that claim. Pinning E is necessary but is not a Docker-state proof.

Source-I/O Task9 can implement genuine file reads and no-clobber projection writes independently.
Its internal publication method accepts only closed role(request/cancel), canonical payload bytes
and matching request digest; it derives the basename, verifies E and actual writable namespace,
and uses fixed Linux renameat2(RENAME_NOREPLACE=1). It returns a file-publication observation only.
It is not an owner-command endpoint or lifecycle authority. Task10 alone calls it while holding the
same SQLite writer after verifying the already committed outbox row, current lifecycle, time and
source bindings. No request source file is generated from browser input by the I/O module itself.

Cancellation publication verifies stable E/outbox but does not reopen T or require its current
positive admission. Missing/drifted T denies new prepare/request publication, not owner/candidate,
authenticated read/cancel or a cancellation projection through unchanged E. Missing/drifted E
leaves all projections pending/suppressed as appropriate; it does not prevent the local cancel
commit. Published bytes are never redirected to another exchange after restart.

## 6. Immutable DB dependency for the journal task

Retain seven-table design, but add these exact columns to its not-yet-frozen control DDL:
`exchange_id TEXT NOT NULL UNIQUE`, `exchange_revision INTEGER NOT NULL CHECK(exchange_revision=1)`,
`exchange_purpose TEXT NOT NULL CHECK(exchange_purpose='operational')`,
`exchange_sha256 TEXT NOT NULL CHECK(length(exchange_sha256)=64)`,
`exchange_size INTEGER NOT NULL CHECK(exchange_size BETWEEN 1 AND 8192)`,
`exchange_identity_json TEXT NOT NULL CHECK(length(exchange_identity_json) BETWEEN 2 AND 4096)`;
add FOREIGN KEY(vault_id,exchange_purpose,exchange_sha256) REFERENCES
domain_blobs(vault_id,purpose,sha256). UUID exactness is checked at runtime, like topology_id.

Add `exchange_blob_ref:<actual operational BlobRef>` to deployment-request-anchor-v1. Preseal E
alongside T/request bytes after initial owner/source checks; first enrollment binds both pins in
the same request/control/reservation/lifecycle/event/command/outbox commit. Verify size/hash and
every request anchor's T/E refs against the one immutable control binding and actual source docs.
No extra exchange table or duplicated JSON authority is needed. Schema checksum includes these
columns from v1 initially; no already-shipped checksum is altered by this proposal.

exchange_identity_json is a canonical private **observed continuity binding**, not another operator
document: `{schema_version:"deployment-outbox-identity-v1",root:{device,inode},
requests:{device,inode},cancelled:{device,inode},backing_root_digest:HexDigest}`. Integers are exact
nonnegative device/positive inode within signed64-bit; backing_root_digest hashes the UTF8 decoded
mountinfo backing-root field. The startup-owned reader obtains these from its freshly verified FDs
and mount map inside first reservation admission, never from HTTP or a caller proof object. Its
row checksum binds them with E. Subsequent publication compares fresh observations to the immutable
binding, including after restart. Do not persist transient mount IDs or assume a retained integer
alone is current evidence. This detects replacement of roots/namespaces despite unchanged E bytes.
Device/inode discontinuity after host/VM/storage recreation conservatively blocks publication until
a future explicit maintenance path; no automatic re-enrollment is promised. It does not defend
against an administrator who can clone/forge filesystem or DB state.

Only control clock/revision fields are mutable. A changed exchange UUID/hash/path mapping/instance
or freshly observed root/namespace identity
cannot update the enrolled control tuple or republish old requests, even if a new source is valid
in isolation. Request/cancel marker publication requires the exact enrolled E pin plus current
physical reader checks. Local read/cancel verifies retained domain blobs without needing live
source roots. A future explicit migration/reconciliation is required for exchange relocation;
changing startup config or reconstructing empty tables is not such authority.

## 7. Remaining boundary, not an authority shortcut

No unresolved numeric-ID conflict was found. This closes source field/path/mode/pin and hash-cycle
choices; it does not provide a release-pinned initializer image, final packaged entrypoint or actual
Linux mount/Portainer evidence. Task9 is source producer/readers/publication I/O and Task10 is owner/journal integration.
Neither task may advertise real supported stage preparation until the genuine source, journal
and actual deployment configuration meet.
Keep template/expansion and syscall-fixture/host-qualification evidence separate. A renderer success,
initializer return value, E constructor or copied BlobRef never grants installation or execution.


## 8. Exact topology and metadata-only reservation observation

T is the following closed object; all displayed scalar placeholders denote their exact validated
values, not runtime literal strings. Size/depth/item caps are in §1.

```text
{schema_version:"extension-topology-v1",
 instance_id:hex32, origin_profile_digest:HexDigest,
 topology_id:canonical_non_nil_UUID, revision:1,
 deployment_recipe_digest:HexDigest,
 static_service_identity_digest:HexDigest,
 platform:"linux/amd64"|"linux/arm64",
 control:{service_identity:"control",uid:20102,gid:20102},
 slots:[{slot_number:integer1..16,service_identity:BrokerId,uid:positive_uint32,
   gid:positive_uint32,channel_id:BrokerId,pair_gid:positive_uint32,
   socket_mount:{mount_id:BrokerId,volume_name:BrokerId,container_path:string,
     read_only:false,purpose:"broker_pair"},
   socket_name:"worker.sock",protocol_id:"deeptwin-extension-worker-v1",
   resource_budget:{memory_bytes:1073741824,cpu_millicores:1000,
     pids_limit:128,tmpfs_bytes:134217728}}]}
```

Slots are ordered contiguous1..capacity, exactly derived by §2; an independent renderer/parser
must reject modified derived values, not accept a self-consistent arbitrary namespace. Static
identity source S is pinned unchanged. The recipe declares the exact fixed reserve IDs, not
candidate authority or measured free capacity. The initial consumer permits ordinary executable
tool, network none, empty grants/secrets, owned_scratch only, one exact slot socket and zero data
mounts; requested resources must fit all four budget dimensions. It re-reads actual candidate bytes
in its own transaction; the source reader does not register, rewrite or grant a descriptor.

A topology admission lease holds metadata-only shared nonblocking locks over actual PairRootSpec
roots/endpoint/known regular metadata. Factor reuse in app/workers/ipc_root.py without changing its
existing secret-bearing acquire_generation/initialize_pair_root behavior. No read of boot-secret
content, no BootSecret object or generation digest derived from its bytes. Opening/statting the
known secret metadata is allowed; never serialize a secret/path/FD as a positive proof. Validate
generation.lock identity against the named current file after locking, along with root/endpoint
identity and metadata. Recheck these before returning/using the lease; close every FD/unlock on
failure and normal close. Leases cannot be copied, pickled or reused after close.

Check known worker.sock and listener.json absence with no-follow known-name operations. Only
ENOENT means absent; permission/I/O errors are unknown and deny admission. Search-only0710/02710
IPC roots must never be treated as listable empty directories. No control-side mkdir/chmod/chown
or boot-secret rotation. Metadata leasing proves participating generation rotation exclusion and
observed names only, never no running containers or future host effects.

T drift prevents new topology admission/request publication; unchanged E still supports local
request read/cancel and cancellation marker publication. Source checks cannot grant a reusable
installation/qualification/worker-route object or freeze future external host effects.

## 9. Closed file-projection role and Linux observations

The source-I/O publisher accepts only role "request" or "cancel", exact canonical bytes, a
canonical unpadded base64url32 request digest and the owning retained exchange source. It derives
all paths. Its observation records role/request_digest/payload_sha256/size_bytes and an exact
published file identity, not lifecycle, user approval, receipt acceptance or execution success.

For request bytes (maximum65536), require exact common top-level keys:
schema,domain,request_id,kind,request_nonce,request_digest,instance_id,origin_profile_digest,
effect_payload,preconditions,created_by,created_at,expires_at.
schema/domain are deployment-request-v1/deeptwin-deployment-request-v1; this initial projection
supports kind extension_stage, preconditions={}, canonical nonnil request UUID, nonce32b64u,
actual instance/origin binding, exact UTCmilliseconds calendar-valid timestamps with
created_at<expires_at, and created_by a structurally valid EntityRef of kind actor. The I/O
codec cannot establish that record's human owner status; Task10 loads the actual actor. The digest is
SHA256 of canonical fields excluding only request_digest, encoded canonical unpadded base64url32.
Its effect_payload remains a bounded canonical object here: deployment-prepare-journal.md §9's
exact stage validator and actual candidate/inventory authority are mandatory before publishing. This I/O
shape/hash check is explicitly not full request/effect admission or an external API.

Cancel bytes (maximum4096) have exactly:
```text
{schema:"deployment-cancellation-v1",domain:"deeptwin-deployment-cancellation-v1",
 request_id:canonical_non_nil_UUID,request_digest:canonical_b64u32,
 instance_id:hex32,origin_profile_digest:canonical_b64u32,
 lifecycle_revision:2,cancelled_at:UTCmilliseconds}
```
Origin uses the checked base64 encoding of the same OriginProfile digest bytes, not hex and never
recursive conversion of EntityRefs/OCI digests. A marker does not contain nonce, signature or
operator claims. Its payload hash covers the complete marker; it does not define request_digest.

No overridable libc path/symbol/flags: Linux-only renameat2 with RENAME_NOREPLACE=1 between retained
same-namespace dir FDs. No replacing rename, link-then-unlink, check-then-overwrite or macOS success
fallback. ENOSYS/EINVAL/EOPNOTSUPP/missing symbol yields sanitized publication-unavailable and
leaves publication intent pending in its later caller. EEXIST verifies exact final bytes, mode,
owner, single link and identity; differing bytes fail closed. Never remove or repair an existing
file. Staging failures can leave bounded inert stage files; do not silently clean them. File fsync
before rename and directory fsync after rename; failure never asserts acknowledged durability.
A same-byte retry may acknowledge a previously published file only after full revalidation+fsync.

Read /proc/self/mountinfo with the stated cap before splitting lines. Reject duplicate IDs,
malformed mandatory/separator fields, invalid or noncanonical escapes (only \\040,\\011,\\012,\\134),
relative backing-root/mountpoints, zero/negative invalid IDs and unbounded optional fields.
Ignore ordering changes when comparing exact relevant normalized mount identities; compare source
mount, namespaces' backing relationship and protected roots, not mutable unrelated host mounts.
Require native Linux machine mapping x86_64→linux/amd64 or aarch64/arm64→linux/arm64; unknown denies.
Mount RO/RW is this namespace's actual mount flags, not the superblock's ability to write elsewhere.
Reject nested exact mounts under T/E/outbox/slots and overlapping same-filesystem backing roots.
Do not claim a real Docker volume name or no-bind provenance from text fields.

Production factory uses only fixed T/E/outbox/slot paths plus trusted startup-owned protected root
configuration; there is no browser/source callback/UID override. Test-only temporary path and OS
observations must be confined to fixtures/private low-level helpers, not a supported runtime mode.
Protect /var/lib/deeptwin, fixed built-in IPC roots and every configured session/bootstrap/public
trust/other exchange root. Do not require nonexistent optional future roots; if configured but
missing/unreadable, deny the source check. Inspect directory metadata, not private key contents.
Actual FD currentness and source pin checks must repeat at bounded admission/publication time.

## 10. Implementation interface boundary for Tasks9 and10

Module ownership:
- app/deployment/contracts.py: bounded pure schemas/parsers/names and serialization distinction.
- app/deployment/render.py: pure fixed-input expansion.
- app/deployment/mounts.py: pure strict mount parser and actual bounded Linux observations.
- app/deployment/files.py: retained no-follow source/namespace file identities.
- app/deployment/sources.py: concrete startup-owned topology/exchange readers and closeable leases.
- app/deployment/publication.py: closed projection codec/no-clobber output observation.
- app/operations/deployment_prepare_init.py: external fixed root initializer main only.
- app/workers/ipc_root.py: reused metadata-only lease; no presentation dependencies.

Use concrete exported interfaces:
render_prepare_sources(base_compose_bytes, base_service_ids_bytes, recipe_bytes, instance_bytes)
-> immutable PrepareSourceArtifacts (topology_bytes, exchange_bytes, pins_bytes,
expanded_compose_bytes, expansion_record_bytes).
open_topology_source(*, profile:OriginProfile, recipe_sha256:str, instance_sha256:str,
topology_sha256:str, protected_roots:tuple[Path,...]) -> TopologySource.
open_exchange_source(*, profile:OriginProfile, recipe_sha256:str, instance_sha256:str,
exchange_sha256:str, protected_roots:tuple[Path,...]) -> ExchangeSource.
Each factory independently opens its fixed roots, verifies and retains concrete sources;
construction on an unsupported platform fails closed. Task10 holds their exact instances, not
objects accepted from an HTTP argument. Separate factories are intentional: if T is unavailable
on restart, actual unchanged E can still be opened for cancellation projection. No bundle-level
constructor may turn failed T into failed E or advertise positive topology without reading T.
TopologySource.acquire_slot(slot_number:int) -> closeable SlotMetadataLease; it contains exact
inert topology_bytes, selected parsed slot and the held metadata lease, with recheck_current().
ExchangeSource.recheck_current() -> immutable OutboxIdentity observations (as §6, actual FDs).
ExchangeSource.exchange_bytes is read-only retained exact canonical content for presealing;
it is inert bytes, never a replacement for currentness or final-writer source revalidation.
ExchangeSource.publish(*, role:str, request_digest:str, payload:bytes) -> PublicationObservation.
Publication can verify E/outbox, but request callers MUST also recheck their topology lease and
committed lifecycle/time under the Task10 writer; cancel projection deliberately does not depend T.
A returned observation is not a lifecycle mutation. Closed/foreign/copied handles cannot mint
authority. No arbitrary callback/passed proof can replace the readers' own system checks.
initialize_prepare_sources() -> {topology_sha256,exchange_sha256}; fixed inputs and Linux UID0.
acquire_generation_metadata(spec:PairRootSpec) -> closeable MetadataGenerationLease, with
recheck_current(), pair_identity and endpoint_identity; no secret field/generation digest.

Root initialization and reader construction are distinct. Initializer may create only genuinely
empty already-mounted fixed new volumes, never root directories chosen by a caller. The initializer
image must package app plus R/B/S under /opt/deeptwin and precreate its fixed input directory; Task9
code tests do not supply/qualify this final image. The existing frozen base and evidence are
unchanged. No root job, mount, Docker action, signing key, live paid model or listener is executed
on the development host as part of source implementation.

Release R/B/S files are root0:0 regular single-link files with exact mode0444 or0644, their fixed
caps/bytes/hashes, never writable by group/other. All walked release ancestor directories are
root0:0 exact0750 or0755 with no symlinks. The effective image mount for /opt/deeptwin must be
observed read-only; do not apply the source-root no-nested-mount rule to the whole filesystem /.
This packaging-mode allowance applies only to public release inputs. Operational I/P files remain
root0:0 mode0440 and their fixed input parent0750. No automatic mode repair or different-path
fallback; actual image ownership/mount qualification remains separate from temporary-file tests.

A genuinely empty new mounted volume is eligible for this initializer only with root UID0:GID0
and exact0755 before handoff. Empty roots at any handed-off/mixed ownership/mode, including0700,
deny rather than being repaired. This is this v1 deployment precondition, not an assumption that
every Docker/Portainer platform creates0755. The new orchestration checks it before calling the
unchanged external IPC initializer; no global widening or rewrite of IPC initialization behavior.
