# Deployment receipt public sources v1 — finite producer and retained readers

Normative source-only contract consuming deployment-receipts.md and the accepted prepare-source
contract. This specifies a later implementation slice, not implemented or qualified behavior. No
wire redesign, journal migration, signing/job implementation or Task10 scope change is implied.

## 1. Inputs and acyclic artifact graph

B/S/R/I/T/E/P/X/A retain their exact Task9 meanings and bytes. Reuse pure render_prepare_sources
on original B/S/R/I to reconstruct them; do not read live T, acquire an IPC lease or call its initializer.
New Q/V/U/J/K/PR/XR/AR are distinct artifacts. All except XR are closed ADR008 JSON, exact UTF8,
no self-digest. Hashes are SHA256 lowercasehex64; UUIDs canonical nonnil; all integer types exact.
XR uses Task9's deterministic sorted compact JSON exception preserving finite base CPU fractions.
Pure API: render_receipt_sources(B_bytes,S_bytes,R_bytes,I_bytes,Q_bytes,V_bytes,U_bytes) returns
frozen ReceiptSourceArtifacts(prepare_artifacts,trust_bytes,ingress_bytes,consumption_exchange_bytes,
pins_bytes,expanded_compose_bytes,expansion_record_bytes); prepare_artifacts is the existing exact result.

Q=`deploy/security/deployment-receipt-recipe-v1.json`, cap4096/depth6/items128, exact:
```text
{schema_version:"deployment-receipt-recipe-v1",recipe_id:"stage-receipt-channels-v1",
 prepare_recipe:{path:"deploy/security/deployment-prepare-recipe-v1.json",
 sha256:"03490ee7c676a0c78915fdef3ec48c52d6b88838ad71bce001ad2fe72f5e67b7",size_bytes:606},
 renderer_id:"deeptwin-receipt-source-expand-v1",initializer_id:"deeptwin-receipt-public-init-v1",
 incoming_final_limit:64,consumed_final_limit:16,staging_limit:32,
 receipt_bytes_max:16384,consumption_bytes_max:4096}
```
The R hash/size above were read from current exact bytes. Q's supported values are build-owned
constants, not an arbitrary policy/command/mount fragment supplied by an operator. R already pins B/S.

V=`receipt-instance.json`, cap4096/depth4/items64, exact:
`{schema_version:"deployment-receipt-instance-v1",prepare_instance_sha256:HexDigest,
trust_set_sha256:HexDigest,receipt_ingress_id:UUID,consumption_exchange_id:UUID}`.
The two new IDs differ from each other and original I.topology_id/I.exchange_id. They are persisted
operator inputs, not renderer-generated UUIDs. V binds exact I and exact public U input. U is precisely
deployment-receipts§4, cap16384; preserve its exact bytes. Its instance/profile must match I's actual
OriginProfile. Only fixed deeptwin-stage-operator-v1/1.0.0/current-profile is allowed. No private input.

J and K are defined below. PR=`receipt-source-pins.json`, cap4096/depth4/items96, exact:
```text
{schema_version:"deployment-receipt-source-pins-v1",instance_id:hex32,origin_profile_digest:HexDigest,
 prepare_recipe_sha256,prepare_instance_sha256,prepare_exchange_sha256,
 receipt_recipe_sha256,receipt_instance_sha256,trust_sha256,ingress_sha256,consumption_exchange_sha256}
```
Every untyped hash above is HexDigest of the whole named artifact. XR=`compose-receipt-expansion.json`,
cap1048576/depth32/items10000, is reconstructed X plus only §3 additions. AR=
`receipt-expansion-record.json`, cap4096/depth4/items128, exact:
```text
{schema_version:"deployment-receipt-expansion-record-v1",scope:"receipt_channels_only",
 base_compose_sha256,base_service_ids_sha256,prepare_recipe_sha256,prepare_instance_sha256,
 prepare_topology_sha256,prepare_exchange_sha256,prepare_pins_sha256,prepare_expansion_sha256,
 prepare_record_sha256,receipt_recipe_sha256,receipt_instance_sha256,trust_sha256,ingress_sha256,
 consumption_exchange_sha256,pins_sha256,expanded_compose_sha256,expanded_compose_size_bytes:1..1048576}
```
Graph: B/S→R; B/S/R/I→T/E/P/X/A; I/U→V; R/I/E/Q/V/U→J; E/Q/V/U/J→K;
Q/V/U/J/K→PR; X/PR→XR; all outputs→AR. Q never hashes XR, V never hashes J/K/PR,
U has no J/K/recipe/expansion reference. Keep original A/X distinct from AR/XR; no historical rewrite.

## 2. Exact J/K and fixed filesystem layout

J cap8192/depth8/items256/string256:
```text
{schema_version:"deployment-receipt-ingress-v1",ingress_id:UUID,revision:1,
 instance_id:hex32,origin_profile_digest:HexDigest,
 prepare_recipe_digest:HexDigest,prepare_instance_digest:HexDigest,outgoing_exchange_digest:HexDigest,
 receipt_recipe_digest:HexDigest,receipt_instance_digest:HexDigest,trust_set_digest:HexDigest,
 writer:{service_identity:"deployment-receipt-job",uid:20113,gid:20113,pair_gid:21201},
 reader:{service_identity:"control",uid:20102,gid:20102,pair_gid:21201},
 incoming:{volume_name:"dt-INSTANCE-deployment-receipts",
 container_path:"/run/deeptwin/deployment-receipts",owner_uid:20113,group_gid:21201,
 root_mode:"0750",namespace_mode:"0750",final_file_mode:"0440",
 writer_read_only:false,control_read_only:true,namespaces:["receipts"]}}
```
K cap8192/depth8/items256/string256:
```text
{schema_version:"deployment-consumption-exchange-v1",exchange_id:UUID,revision:1,
 instance_id:hex32,origin_profile_digest:HexDigest,outgoing_exchange_digest:HexDigest,
 receipt_recipe_digest:HexDigest,receipt_instance_digest:HexDigest,
 trust_set_digest:HexDigest,receipt_ingress_digest:HexDigest,
 control:{service_identity:"control",uid:20102,gid:20102},
 reader:{service_identity:"deployment-receipt-job",uid:20113,gid:20113,pair_gid:21201},
 outgoing:{volume_name:"dt-INSTANCE-deployment-consumed",
 container_path:"/run/deeptwin/deployment-consumed",owner_uid:20102,group_gid:21201,
 root_mode:"0750",namespace_mode:"0750",final_file_mode:"0440",
 control_read_only:false,reader_read_only:true,namespaces:["consumed"]}}
```
INSTANCE is exact I OriginProfile.instance_id, never a literal runtime placeholder or caller name.

| Logical volume (physical dt-INSTANCE- prefix) | Fixed /run/deeptwin/ path | UID:GID/modes | Control |
| --- | --- | --- | --- |
| deployment-verify-public | deployment-verify-public/trust-set.json |root0:20102 dir0750/file0440|RO|
| deployment-receipt-ingress-public | deployment-receipt-ingress/ingress.json |root0:21201 dir0750/file0440|RO|
| deployment-consumption-exchange-public | deployment-consumption-exchange/consumption-exchange.json |root0:21201 dir0750/file0440|RO|
| deployment-receipts | deployment-receipts/receipts/ |20113:21201 dirs0750/finals0440|RO|
| deployment-consumed | deployment-consumed/consumed/ |20102:21201 dirs0750/finals0440|RW|

Each source root contains exactly its named single-link regular file; each channel root exactly
its one ordinary child namespace on the same mount. No additional groups/IDs: reuse reserved21201.
Future job gets20113:20113+21201, J/K/source+old outbox+consumed RO, inbox RW; no control group20102,
U/private-key discovery, work root or Docker credential. Its signer/key mounts remain a separate task.

## 3. Finite XR additions and operational public initializer

Parse only reconstructed exact X, never operator-provided Compose fragments. Preserve all original
service/volume/network/config bytes structurally and array order; reject key/path/env collisions.
Append the five volumes/mounts in the table order, each volume explicit physical name, long syntax
type=volume/nocopy=true and exact RO/RW. Existing control21201 group is reused, not duplicated.
Append control dependency deployment-receipt-public-init:service_completed_successfully and env:
DEEPTWIN_RECEIPT_RECIPE_SHA256, DEEPTWIN_RECEIPT_INSTANCE_SHA256,
DEEPTWIN_DEPLOYMENT_TRUST_SHA256, DEEPTWIN_RECEIPT_INGRESS_SHA256,
DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256, from PR. No replacement of Task10's four old pins.

Add only one executable service: deployment-receipt-public-init, image
`${DEPLOYMENT_RECEIPT_PUBLIC_INIT_IMAGE:?exact @sha256 image required}`, entrypoint
["python","-m","app.operations.deployment_receipt_public_init"], command=[], user0:0,
group_add=["21201"], restart=no, init=true, privileged=false, read_only=true, network_mode=none,
cap_drop=[ALL], cap_add=[CHOWN,FOWNER,FSETID], security_opt=[no-new-privileges:true], tty=false,
stdin_open=false, pids_limit32, mem_limit64m, cpus0.25, nofile soft/hard256. Only the five NEW volumes
RW, no old T/E/IPC/data/session/private signing mounts. No fake receipt-job service is added.

Four exact external configs under /run/deeptwin/receipt-init-input/: prepare-instance.json,
receipt-instance.json, trust-set.json, receipt-source-pins.json. Config names are respectively
dt-INSTANCE-receipt-prepare-instance, dt-INSTANCE-receipt-instance, dt-INSTANCE-receipt-trust,
dt-INSTANCE-receipt-pins; explicit uid/gid0:0/mode0440. Image precreates this root0:0 parent0750.
Its directory has exactly these files. Image packages B/S/R/Q at their fixed relative paths under
/opt/deeptwin; release files root0:0 regular/single-link0444|0644, ancestors0750|0755 and image RO,
same narrow checks as existing initializer. No cwd/env/CLI file-path, UID, policy or signer override.

`initialize_receipt_public_sources()` requires Linux effectiveUID0 and fixed inputs. Check actual
ownership/currentness, Q/R/B/S hashes and V I/U hashes, recompute all outputs and require exact PR.
XR emits the exact capability restriction above; initializer success alone does not prove the
container's complete kernel capability set or mount provenance. Those are actual packaging/profile
qualification gates, not a caller-supplied capabilities argument or a parsed positive proof.
Observe only its five new mounted roots RW plus input/release boundaries; reject mutual aliases,
nested mounts or overlap. It cannot prove hidden aliases to old roots it does not mount; exact
operator topology plus subsequent control-visible reader checks cover that separate requirement.
For genuinely empty mounted root0:0/0755, establish declared metadata and exclusive-stage/no-replace
publish source files; create/fsync channel child before handing ownership to20113/20102. Existing
initialized roots verify-only; reject partial/extra/unsafe entries and abandoned staging at init.
Existing valid channel finals remain; no delete/repair/overwrite. File+directory fsync, no multi-volume
atomicity claim. Exact return `{trust_sha256,ingress_sha256,consumption_exchange_sha256}` matches PR.
Initializer verifies every retained final's digest/schema/profile under the64/16 bounds, not signature
authority or DB disposition; incomplete staging denies without reading/recovering private stage bytes.

U must be genuinely operator/root-provisioned public input, not browser supplied. This function
does not create/verify possession of a matching seed or sign evidence. No calls to Task9 IPC init,
absence checks, generation rotation, live T/E readers or worker sockets. Reconstructing X is pure.
XR is topology-only, not ready-to-run issuer deployment: images/config ownership/one-shot ordering
need qualification. Existing X still names old prepare init; external rollout MUST NOT recreate/run
it on occupied slots. Do not advertise whole-stack XR apply as a safe restart algorithm.

## 4. Concrete independent reader interfaces and observations

All factories use fixed paths and actual OriginProfile; no path/UID/callback/test-mode argument:
```text
open_public_trust_source(*,profile,trust_sha256,protected_roots) -> PublicTrustSource
open_receipt_ingress_source(*,profile,receipt_recipe_sha256,receipt_instance_sha256,
 ingress_sha256,protected_roots) -> ReceiptIngressSource
open_consumption_exchange_source(*,profile,receipt_recipe_sha256,receipt_instance_sha256,
 consumption_exchange_sha256,protected_roots) -> ConsumptionExchangeSource
```
Each separately opens only its own source and channel; J never opens U/K/T, K never opens U/J/T/E.
Compare Q pin with compiled supported Q and V pin with source fields. Historical R/I/E/U/J digest
relationships are parsed facts until the later actual journal compares its retained bytes/pins and
all exact constructed source instances. Opening one source does not authenticate another source.
No positive topology/slot-absence check or live E dependency occurs after an external effect.

Each class rejects public construction/copy/pickle/closed reuse and exposes read-only exact
trust_bytes/ingress_bytes/consumption_exchange_bytes respectively, `recheck_current()` and `close()`.
`PublicSourceIdentity={schema_version:"deployment-public-source-identity-v1",source_kind:
"trust"|"ingress"|"consumption",root:ObjectIdentity,file:ObjectIdentity,backing_root_digest:HexDigest}`.
ObjectIdentity reuses actual nonnegative signed64 device/positive signed64 inode helper.
U recheck returns this shape. J/K recheck returns respectively
`{schema_version:"deployment-receipt-ingress-identity-v1",source:PublicSourceIdentity,
root:ObjectIdentity,receipts:ObjectIdentity,backing_root_digest:HexDigest}` and
`{schema_version:"deployment-consumed-identity-v1",source:PublicSourceIdentity,
root:ObjectIdentity,consumed:ObjectIdentity,backing_root_digest:HexDigest}`.
Backing hashes use each relevant source/channel mount's decoded backing-root text, not mount IDs.
These serializable observations are not constructible authority; consumers use the owning readers.

J.list_available_receipt_digests() returns≤64 B32 selectors in filename-hex order after bounded
namespace metadata/currentness checks. This does not verify signatures/read all payloads or import
anything. J.open_receipt(receipt_digest:B32) returns closeable ReceiptFileLease with receipt_bytes,
receipt_digest, file_identity and recheck_current(); retain FD/signature and recheck named entry,
whole bytes/hash and source before returning/using it. It validates selected wire shape/instance/U
digest syntactically, not request equality, trust signature, deadline or disposition. No caller filename.
Pure/common wire support is a dependency; do not duplicate deployment-receipts parsing in the reader.

Reuse Linux-only mountinfo caps1MiB/4096entries/8KiBline. Source/inbox mounts RO, consumed RW, namespaces
not nested mounts; reject symlink/hardlink/owner/mode/device/inode/backing overlap and pathname swaps.
Always protect actual configured data/session/bootstrap/other roots; missing configured root denies.
Observe other fixed T/E/IPC/new roots when mounted only for alias checks, not readiness/continuity;
their absence or changed nonoverlapping content cannot invalidate an otherwise independent reader.
Keep relevant own/protected mount continuity and actual platform stable, ignore unrelated order.
No stat/mountinfo claim of Docker volume identity, no private file reads and no mount repair.

## 5. Bounded namespace and consumed projection rules

Final names=[a-f0-9]{64}.json, stages=.stage-<nonnilUUID>.tmp; unknown names inhibit that source.
Inbox≤64final/32stage, payload1..16384; consumed≤16final/32stage, payload1..4096. Final0440/singlelink;
stage size0..cap with writerUID and allowed (primaryGID,0600)|(21201,0600)|(21201,0440).
Thus primaryGID is20113 for incoming and20102 for consumed; do not reuse old20102 staging ownership.
Listing/rechecks inspect bounded metadata. Selected reads verify digest and complete canonical bytes;
consumed rechecks may validate all≤16markers. Never clean or count unsafe entries as missing.

K.publish_consumed(*,receipt_digest:B32,payload:bytes) returns
`{role:"consumed",receipt_digest,payload_sha256:HexDigest,size_bytes:1..4096,file_identity:FileIdentity}`.
Exact marker bytes are `{schema:"deployment-consumption-v1",domain:"deeptwin-deployment-consumption-v1",
consumption_id:UUID,request_id:UUID,request_digest:B32,receipt_digest:B32,
winning_lifecycle_revision:2,consumed_at:Time,outcome:"failed"|"unknown"}`. No success marker/nonce/key.
K binds instance via its source, later journal verifies every marker field against committed records.
Filename consumed/<decoded-receipt-digest-hex>.json; marker payload hash differs from receipt digest.
Primitive establishes file observation only; later consumer must hold its SQLite writer and recheck
current U/J/K and committed consumption before publication/ackCAS. Source task has no DB/owner API.
Fixed Linux renameat2(RENAME_NOREPLACE), exclusive stage0600→group21201/final0440→file fsync,
recheck actual source immediately before rename, directory fsync, exact existing-byte verification
and final source recheck. Unsupported syscall denies; no replace/link/unlink fallback or cleanup.
Existing final same bytes can acknowledge without allocating a new stage; other bytes fail closed.
K.inspect_consumed() returns a tuple of at most16 frozen inert ConsumedFileObservation objects,
each with receipt_digest:B32, payload:bytes and file_identity:FileIdentity, sorted by filenamehex.
It uses the actual owning K handles, fresh source/namespace and named-entry FD/whole-byte checks,
the closed consumed codec, exact decoded selector filename and pre/post currentness. No caller
path, payload, policy or reconstructed identity is input. Closing K rejects subsequent inspection.
The later journal uses this bounded inventory to compare existing finals to committed consumption
rows, including pending rows after a publication-before-ack crash. Inspection does not authorize
import, repair, acknowledgement or consumption. Implement it with the same bounded scanner used
by K rechecks/publication, not a second filesystem walk implementation or recursive recheck loop.
Future job's incoming writer must use the same mechanical sequence with UID20113/cap64, but this
task implements no signer or control-side inbox publisher. Enumeration is not automatic import/UI.

## 6. Narrow reuse, file boundaries and qualification

files.py:69–272 already supplies no-follow Directory/SourceFile/read_exact/identities. Reuse these.
files.py:277–310 hardcodes20102/16/48 and eagerly reads finals: factor a private fixed namespace-policy
scanner supporting old outgoing, incoming and consumed constants; retain old inspect_namespace wrapper
behavior. Separate metadata enumeration from bounded selected reads; no policy from source/HTTP text.
publication.py:128–179 rename/write/existing routines and:183–240 publication mechanics are reusable;
factor private stage/existing/commit primitives parameterized only by build-owned role policy. Keep
source recheck between stage and commit in each concrete wrapper, not an arbitrary proof callback.
Existing request/cancel codec/API/observation and bytes remain unchanged; do not generalize role names.
mounts.py:225–258 helpers already accept required/protected maps. Factor sources.py:59–151 neutral
pinned-source lifecycle from its old recipe assertion; retain old wrappers/assertions and add new
optional fixed-root alias observations. No copying complete source/namespace/syscall implementations.
New receipt_source_contracts.py/receipt_render.py/receipt_sources.py/receipt_publication.py own Q/V/J/K,
producer, concrete readers and consumed codec; new operations/deployment_receipt_public_init.py owns
external orchestration. Extract only shared public-init file primitives, never import/call old IPC init.

Focused required tests: deterministic regeneration/old-X subtree invariance; every fixed-field/hash
collision; public input provenance; partial init verify-only; UID20113/20102 and64/16 boundary parity;
retained-file swaps, RO inversion/aliases/unsupported OS, bounded selector enumeration, same/different
byte no-clobber/crash observations; unchanged Task9 tests. This contract does not establish their results.
Mandatory deployment qualification: pin/qualify public-init image and safe external rollout scheduling
that does not rerun the inherited prepare initializer. The pure/source implementation can proceed
without pretending that those images, a signer or the fixed adapter already exist. No wire TBD remains.

## 7. Parent clarifications and integration boundary

All artifact parsers reject duplicate/unknown fields, BOM/trailing bytes, noncanonical JSON and
bool-as-integer. Q/V/PR/AR string cap is256; their listed byte/depth/item bounds also apply. U and
common receipt limits come only from deployment-receipts.md. Constants in Q are build-owned;
first dispatch freezes its exact canonical bytes and exports their digest, not a configurable
policy. Original R/B/S and their hashes are unchanged. No artifact hashes itself.

Pure receipt parsing must expose one closed structure-only function independently of verification.
The ingress reader checks selected receipt structure, instance/profile/origin and declared U digest
against its actual pinned J; it cannot check request equality/deadline or authenticate the signature
without the actual request and U. These are later verifier/consumer duties, never synthesized by J.
Initializer verification of retained incoming files uses the same structure-only parser; K markers
use the same consumed codec as publication. Public initializer neither requires nor discovers keys.

`receipt_sources.DeploymentReceiptInvalid(DeploymentSourceError)` is a fixed source-family subtype
with code/message `deployment_receipt_invalid`. Only safely opened, current, whole-digest-matching
selected bytes rejected by intrinsic parse_receipt produce this subtype, with no returned lease.
Missing/unsafe/replaced files, hash mismatch and source/J instance/profile/U binding failures retain
the existing source errors. No arbitrary exception or reflected payload/path becomes this subtype.
The later HTTP importer can thereby map malformed selected wire to400 and source loss/drift to503
without rereading unsafely or parsing error text. Structure-only parsing still performs no crypto.

ReceiptFileLease is created only by the exact owning ingress reader, retains its actual opened FD,
initial complete byte/signature snapshot and filename-derived digest, and borrows that reader.
Before exposing or rechecking bytes it rejects a closed owner/lease. Close is idempotent and closes
only its own FD. Closing the source invalidates outstanding leases. No public constructor, copy,
pickle, returned serializable FileIdentity or raw descriptor supplies admission authority.
All source identity snapshots are frozen observations with as_dict returning fresh inert mappings;
actual consumers use exact retained source instances and recheck, never reconstruct them from JSON.

ReceiptFileLease.recheck_current() -> app.deployment.files.FileIdentity returns its same frozen
file observation after owning-ingress currentness, held FD, named entry, exact bytes and complete
receipt digest all revalidate. It never returns a validity boolean or refreshes/rebinds the lease.
Closed, missing, replaced or changed objects raise the existing closed DeploymentSourceError family.
No caller-supplied observation is accepted. receipt_bytes performs this full recheck before exposing
its original immutable bytes. The returned identity remains inert and cannot reopen a lease.

Shared namespace policies are private build-owned constants, not manifest-selected limits/UIDs.
Retain the existing inspect_namespace(directory,cap) call signature and behavior for request/cancel.
Incoming metadata enumeration does not read stage bytes or silently accept malformed final metadata.
Selected reads enforce whole signed-receipt hash, complete canonical bytes and fresh named-entry
binding. New K publication shares syscall/write/existing primitives; it never calls the old public
publish wrapper with a new role or removes any old exact-type/currentness check.

The neutral retained-source base may be extracted from sources.py only with identical behavior for
existing T/E wrappers. All three new public source roots and two channel roots join build-owned
optional alias observations for every reader. Optional means their presence is checked for alias
safety, not that their contents/readiness become dependencies. No root allowlist comes from U/J/K.
Shared initializer file helpers contain no IPC import or call; importing or invoking the old
initialize_prepare_sources to initialize new volumes is forbidden. Existing prepare root-init
credential, generation and source behavior stays unchanged.

The generated XR is inert deployment topology. The existing X/prepare-init dependency remains
structurally preserved, so running XR as a whole on populated slots is not a supported rollout
procedure yet. A qualified external sequence must initialize only the five new roots, then start
control with its independently pinned tuple without rerunning occupied-slot initialization. This
release gate is mandatory and cannot be replaced by fixture success, an image-variable label or a
claim that the framework can mutate host deployment configuration itself.

No HTTP route, automatic receipt import, private seed, external job, installation, qualification,
budget settlement or scheduler authority belongs in this source slice. Browser discovery/import
and actual one-use disposition are later consumers. The wire/public-verifier prerequisite may be
reviewed separately before source implementation; their connected consumer remains required.

A missing previously acknowledged consumed final is loss of physical projection evidence, not
erasure of durable consumption. The later consumer denies new receipt import if K is missing,
unsafe, changed, uninspectable or its bounded inventory disagrees with committed consumption.
After receipt_sources is durably enrolled, every request-file publication attempt and restart
also requires actual retained K matching that enrollment and a fresh full inventory comparison,
even if enrollment came from succeeded evidence with zero consumptions. Before enrollment,
request publication retains its original T/E requirements without K; first import still requires
U/J/K and an inventory matching the then-empty consumption set. Never enroll merely to publish.

Consumed publication always requires actual U/J/K and inventory checks. Request publication
requires its existing T/slot/E/TTL checks plus K after enrollment, not new live U/J dependencies.
Cancellation publication remains E-only and independent of this K gate; E's own required
currentness/protected-root/alias safety checks are never bypassed. GET/HEAD, exact replay, local
cancel and expiry remain independent of live sources against an intact historical journal.
A valid new prepare can still commit its reservation and frozen201 pending reply under existing
T/E admission; a failed post-commit K gate leaves its request file pending.

Every observed final must match a committed consumption with pending/published intent; every
published intent must retain its exact final. A pending intent without a final is ordinary pending
work. Missing published, alien or differing finals deny positive projection/import with
dependency_unavailable, never local cancel/expiry. Do not mark an intact journal corrupt, regress
its ack, silently recreate a missing acknowledged final, reenroll K or free reservations. No new
durable loss latch, repair operation or retry scheduler is introduced. The source layer has no DB
state with which to make this comparison; the service must repeat it under its actual writer
before request publication and before ackCAS, checking TTL again after inspection. A failure
after file visibility leaves honest pending recovery, not cross-filesystem atomicity.

## 8. Pure producer prerequisite interfaces

Implement the independently testable producer/codec prerequisite before retained readers and
external initialization. No reader or initializer stub is substituted for those later components.
Pure module receipt_source_contracts.py exports the exact Q `RECEIPT_RECIPE` dict, canonical bytes
`RECEIPT_RECIPE_BYTES` and computed `RECEIPT_RECIPE_SHA256`. These are build-owned constants; every
parser checks the supported recipe pin, not a caller-defined shape of equivalent policy.

```text
parse_receipt_recipe(raw:bytes)->dict
parse_receipt_instance(raw:bytes)->dict
parse_ingress(raw:bytes,*,profile,receipt_recipe_sha256,receipt_instance_sha256)->dict
parse_consumption_exchange(raw:bytes,*,profile,receipt_recipe_sha256,
                           receipt_instance_sha256)->dict
```

parse_receipt_instance checks exact V structure and distinct nonnil new IDs; equality to actual
I/U hashes and distinctness from I.topology_id/I.exchange_id occur when render_receipt_sources has
the complete input set. J/K parsers check every exact constant/field/bound, actual inert profile,
Q/V pins and derived own volume/layout identities; historical I/E/U/J digest fields not available
to that parser remain validated digest facts, not authenticated cross-source relationships.
The producer reconstructs the whole graph and validates all those relations with complete bytes.

receipt_render.py owns the exact render_receipt_sources seven-byte-input API and frozen
ReceiptSourceArtifacts from§1. No source path, environment, configuration fragment, profile override,
random generation, file write, mount read, socket or effect is accepted. It derives profile from
actual validated I and reparses U with receipt_contracts.parse_trust_set. All malformed wire/source
inputs normalize to the existing closed DeploymentSourceError, preserving no raw text or paths.

receipt_publication.py initially owns
`validate_consumed_marker(*,receipt_digest:str,payload:bytes)->dict`, a pure fixed consumed marker
codec with no instance/owner/DB authority. It checks every field in§5, exact Time, decoded32byte
selectors and receipt_digest equality, at cap4096/depth4/items32/string256. Reuse parse_json_object/
WireLimits, existing ADR008/B32/UUID/time helpers and reject unknown/duplicate/noncanonical fields.
The returned fresh parsed dict is inert. Later actual K publication uses this same function; it
must not create a second marker grammar or add a consumed role to the old public request/cancel API.

This prerequisite creates recipeQ plus producer/codec source and their tests only. It leaves
existing Task9 sources/files/publication/initializer modules unchanged. The next reader/initializer
step owns the explicitly documented shared primitive extraction and actual five-root I/O; complete
Task9 and Task10 covering verification will be required there. Neither pure step creates a live
public root, ready signing job, installed extension or qualified rollout.
