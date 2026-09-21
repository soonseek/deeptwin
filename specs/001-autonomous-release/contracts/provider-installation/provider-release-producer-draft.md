# Private provider release preparation — provisional producer contract

2026-09-19 R1: explicit finalization inputs and fresh inspection. Advisory design only. No dispatch, signing, native image qualification or product change
authorized. This is one complete release-preparation delivery, not separately shippable codecs.
It supplies operator advisory F1; F2 enrollment/access enforcement and B's effect ledger stay separate.

**Goal:** turn retained, exact source/base/wheel inputs into two actual OCI images, independent
offline filesystem reports, provider lineage, an unsigned allow-policy body, and finally a checked
operator capsule when the external release authority supplies a real signature and candidate.
**Architecture:** no Docker/BuildKit, subprocess, package resolver, imported worker execution or
network is needed by the producer. Compose OCI bytes offline; inspect those bytes independently;
never generate passing evidence from a requested digest or builder-returned summary.
**Stack:** locked CPython3.12 producer, standard-library archive/hash readers and existing pure
identity/lineage/candidate/source validators. Signature verification remains established Ed25519.
**Authority:** FR-032/ADR-010/014, private-provider-worker.md, provider-image-lineage.md,
extension-lineage-values.md, extension-candidates.md, frozen deploy input locks; operator R1 advisory
and provider-operator-profile-ruling.md. This does not promote either advisory to a contract.

## 1. Concrete inspected inputs and boundaries

Accepted provider_worker.main parses the five-element worker argv; argv[0] is packaging-owned.
provider_service imports claude_protocol (pure supplied-byte SSE/JSON), not provider_gateway/SDK.
provider_identity imports jsonschema; deployment.contracts imports operations.setup, which imports
idna. _fixed_image_metadata imports both metadata profiles; extensions.__init__ imports its pure
contracts/registry/schema exports. These real imports cannot be dropped to obtain a smaller image.
Read-only AST traversal found39 repository modules, including initializers; no application import
was executed. Reachable external non-stdlib roots are jsonschema and idna, not PyNaCl or Anthropic.
Static traversal is an input enumeration, not proof of all dynamically executed imports.

Current pyproject pins jsonschema4.26.0/idna3.19; uv.lock supplies the seven-distribution candidate
closure below. Frozen release wheel manifests/locks do NOT already contain the jsonschema closure.
Add a separately reviewed private-worker dependency addendum/lock; neither copy the gateway SDK
closure nor rewrite service-roots.json, old requirements, upstream-images.json or aggregate lock.
uv.lock is a candidate selection source, not proof that fetched wheels or Linux imports were checked.

Frozen CPython base input is upstream-images.json image_id=python-service-base,3.12.14-slim-bookworm,
selected linux/amd64 and linux/arm64 runnable descriptors. Require its exact pinned index/manifest/
config/layer bytes and report joins, not a mutable tag. Existing base provenance covers its stated
descriptor/SBOM subjects; it is not final private-worker qualification. Final hashes are outputs.

Proposed release wheel cohort (actual local lock declarations; acquisition not performed):

| Distribution | Version | Wheel SHA256 | Bytes |
| --- | --- | --- | ---: |
| attrs |26.1.0|c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309|67548|
| idna |3.19|815e7be7a7806d54abb586dc943addc79e8b2ee16915059658cbeff4b1b43bf4|68550|
| jsonschema |4.26.0|d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce|90630|
| jsonschema-specifications |2025.9.1|98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe|18437|
| referencing |0.37.0|381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231|26766|
| rpds-py,amd64 |2026.6.3|ecabd69db66de867690f9797f2f8fa27ba501bbc24540cbdbdc649cd15888ba6|366189|
| rpds-py,arm64 |2026.6.3|55927d532399c2c646100ff7feb48eaa940ad70f42cd68e1328f3ded9f81ca24|368180|
| typing-extensions |4.16.0|481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8|45571|

Pure wheels are exact uv.lock py3-none-any filenames; rpds is cp312-cp312-manylinux_2_17_x86_64.
manylinux2014_x86_64 or cp312-cp312-manylinux_2_17_aarch64.manylinux2014_aarch64. No sdist/extras,
musl/macOS wheel, format-nongpl dependency expansion, pip invocation or installation hook.
METADATA/WHEEL/RECORD and byte hashes must agree with these selections before installation.
Requires-Dist evaluation for this frozen CPython3.12/no-extras profile must yield exactly these seven
names/versions; unexpected requirement or marker is a refusal, not runtime resolution.

## 2. Complete delivery ownership and immutable source list

Proposed NEW paths only; existing runtime/parser/lock/schema files remain read-only:

| Path | Responsibility |
| --- | --- |
| deploy/provider_release/__init__.py | inert package |
| deploy/provider_release/contracts.py | closed recipe/input/report/policy/capsule codecs and joins |
| deploy/provider_release/inputs.py | retained no-follow source/wheel/base inputs; frozen lists |
| deploy/provider_release/oci.py | finite OCI/ZIP/tar readers and logical filesystem replay |
| deploy/provider_release/build.py | deterministic source/dependency inputs and OCI overlay builder |
| deploy/provider_release/inspect.py | reopen/replay actual final OCI bytes; independent report producer |
| deploy/provider_release/capsule.py | actual signature/graph joins and immutable capsule publication |
| deploy/provider_release/service.py | prepare_release/finalize_capsule orchestration, no native runner |
| deploy/provider_release/worker | exact launcher below, sole new executable image input |
| deploy/locks/requirements-provider-private-v1-linux.lock | additive seven-distribution hash lock |
| deploy/manifests/provider-private-inputs-v1.json | additive complete wheel/base/source-profile selections |
| deploy/tests/test_provider_release_contracts.py | codecs/cycles/joins |
| deploy/tests/test_provider_release_inputs.py | exact source list/wheels/mutation/currentness |
| deploy/tests/test_provider_release_oci.py | malformed archives/layers/whiteouts/diffIDs/limits |
| deploy/tests/test_provider_release_build_inspect.py | real temporary OCI production+independent inspection |
| deploy/tests/test_provider_release_capsule.py | complete closure/signature/publication negative vectors |

The source payload contains exactly the39 files below, unchanged bytes, plus the new launcher and
the four existing schemas/v1/extensions/ports/provider-port-v1/{config,request,result,error}.schema.json.
No tests, pyproject, whole app tree, __pycache__, core DB/API/store, gateway or credential code.

```text
app/__init__.py
app/adapters/{__init__,claude_protocol}.py
app/deployment/{__init__,contracts,files,mounts}.py
app/domain/{__init__,events,refs,wire}.py
app/extensions/{__init__,candidate_contracts,candidate_schema_exports,contracts,lineage_contracts,
 lineage_schema_exports,port_contracts,port_schema_generator,provider_identity,
 provider_identity_schema_exports,registry,schema_exports}.py
app/operations/{__init__,setup}.py
app/workers/{__init__,_fixed_image_metadata,artifact_stream,artifact_stream_transport,broker,
 extension_channel,extension_metadata,ipc_root,listener,provider_messages,provider_metadata,
 provider_service,provider_transform,provider_worker}.py
```

Braces expand to literal paths; wrapping whitespace is not a path. Exactly44 input files.
Recompute each source hash from retained bytes. AST import closure must remain inside this list/
stdlib/exact dependency roots, including function-local imports and package initializers; drift
refuses this profile and requires reviewed source-list revision. Never strip imports or synthesize
empty __init__ files. Native packaged import/operation tests remain needed for dynamic behavior.

## 3. Code-owned launch and layout

Launch policy ID `provider-cpython-isolated-v1`. Image entrypoint is exactly
`["/opt/deeptwin-extension/bin/worker"]`, Cmd=[]; descriptor retains existing exact instance/slot
argv. Launcher exact LF UTF8 bytes, including final newline:

```python
#!/usr/local/bin/python3.12 -ISB
import sys
sys.path[:] = ["/opt/deeptwin-extension/lib", "/opt/deeptwin-extension/site", "/usr/local/lib/python3.12", "/usr/local/lib/python3.12/lib-dynload"]
from app.workers.provider_worker import main
raise SystemExit(main())
```

No env shebang, shell, -m cwd lookup or inherited PYTHONPATH. -I/-S/-B disable environment/user/site
initialization and bytecode writes; runtime native acceptance must confirm this exact shebang on
both images. Private lib contains only app/, private site only the selected wheels. No .pth,
sitecustomize/usercustomize, .pyc, executable scripts or stdlib-shadowing top-level modules there.
CPython binary/stdlib/ELF dependencies remain the exact pinned base; no freezer/interpreter download.
Env exactly ordered `["LANG=C.UTF-8","LC_ALL=C.UTF-8","PATH=/usr/local/bin:/usr/bin:/bin"]`, cwd=/.
Image User=65532:65532 (safe non-slot default); actual stage overrides only to verified original
slot uid:gid and exact existing groups. Runtime isolation/mount/resources still require the external
operator; image metadata alone cannot establish no network/overlays. Recommend Init=false because
this worker owns signal handling and no unmanifested init executable mount is needed.

Image-owned directories /opt,/opt/deeptwin-extension and every new ancestor are root:root0755;
bin/worker0555; all other regular payload/dependency/schema/identity files0444, root:root,single-link.
app paths map to /opt/deeptwin-extension/lib/app/...; wheel members to .../site/; schemas to
.../ports/provider-port-v1/; identity to .../identity/build-identity-v2.json. /usr/local/bin/python3.12
must resolve to a regular ELF matching architecture in the unchanged base, not a candidate overlay.
Runtime /tmp may be the separately declared bounded scratch; it never enters sys.path.

## 4. Scalars, exact record grammars and finite bounds

All records below closed canonical ADR008 JSON, no floats/duplicate/unknown keys/bool integers.
H=lowercasehex64; S={sha256:H,size_bytes:positive}; UUID=existing canonical nonnil UUID; P is exactly
linux/amd64 then linux/arm64 wherever two-element arrays appear. Existing BuildIdentity/OCI types
retain their exact parsers/caps. Relative path R has normalized UTF8 components, no empty/dot/dotdot,
control, backslash, leading slash or NUL,<=255B. Absolute A is /+R or /,<=1024B. Modes are integers.
All report parsers depth16/items65536/members32/string1024/integer2**40, subject to tighter fields.
Source/dependency reports<=262144B each; filesystem report<=1MiB each; policy/capsule<=65536B each.
Input source tar<=16MiB;44 files; each app/launcher<=1MiB except accepted worker cap16MiB; actual
existing schema caps262144B each/sum1MiB. Wheel archive<=16MiB, expanded<=64MiB each/256MiB total.
Source report max44 File rows; dependency max4096 installed rows/platform; filesystem max8192 rows.
File body streaming64KiB; no layer-size allocations. Byte caps override otherwise valid row counts.

### 4.1 Pre-image recipe and dependency input records

`BuildRecipe={schema_version:"provider-private-build-recipe-v1",builder_id:"provider-oci-build-v1",
inspector_id:"provider-oci-inspect-v1",source_layout:"provider-private-source44-v1",
launch_policy:"provider-cpython-isolated-v1",base_lock:S,toolset:S,dependency_sets:[{platform:P,input:S}],
overlay_format:"ustar-uncompressed-v1",created:"1970-01-01T00:00:00Z"}`;<=16384B.
toolset identifies canonical sorted `{path:R,sha256:H,size_bytes}` rows for the eight producer .py
files AND their code-owned transitive repository parser/helper imports,<=128 files/32MiB; exclude its
own manifest/generated reports. Derive/recheck the complete static import set from these fixed roots,
including package initializers; unresolved dynamic imports refuse this tool profile, never copy a
whole checkout. Tool interpreter/distribution provenance is separate release evidence: this source
toolset hash is not an authenticated executed-tool claim. base_lock hashes actual frozen upstream lock.
Recipe does not contain source-bundle/image/report/policy/capsule hashes. No self-pinned constant.

`DependencySet={schema_version:"provider-private-dependency-input-set-v1",platform:P,
python:{implementation:"CPython",version:"3.12.14",abi:"cp312",glibc_floor:"2.28"},
roots:["idna==3.19","jsonschema==4.26.0"],base:{index:OCIIndex,entry:PlatformEntry},
lock:S,artifacts:[{name,version,filename:R,wheel:S}]}`;<=32768B.
Exactly seven artifacts sorted normalized distribution name, exact table1 versions; wheel filename
is a single component, matches selected platform tags. lock hashes the additive raw hash lock.
No source recipe/report/image output ref here; this record precedes identities and images.
Addendum file exact shape is `{schema_version:"provider-private-inputs-v1",
status:"candidate_not_release_qualified",source_layout:"provider-private-source44-v1",
base_lock:S,platforms:[DependencySet]}`. Both embedded sets are also emitted as canonical individual
bytes; their S values bind identities. Hash lock is normalized distribution-name order, one LF-ended
line/name, `name==version` then sorted ` --hash=sha256:<H>` tokens (two for rpds, one otherwise).
No self-reference: create raw lock before sets, sets before addendum/recipe. Verify this projection,
not an arbitrary input directory's manifest claiming different dependencies.

`InputTriple={schema_version:"extension-build-inputs-v1",source_bundle:S,build_recipe:S,
dependency_input_set:S}` is the accepted identity.inputs shape, not a new competing type.

### 4.2 Source report — actual byte enumeration, no execution attestation

`SourceReport={schema_version:"provider-source-closure-v1",producer_id:"provider-oci-build-v1",
toolset:S,source_bundle:S,recipe:BuildRecipe,
platform_inputs:[{platform:P,inputs:InputTriple}],files:[SourceFile]}`.
`SourceFile={source_path:R,image_path:A,sha256:H,size_bytes:nonnegative,mode:0444|0555}`.
Exactly44 sorted source_path rows with mapping§3; zero bytes allowed only for package initializers.
source_bundle identifies the actual deterministic tar of these source paths/bytes, NOT this report.
Hash canonical recipe bytes for both input triples; source_bundle same for both; dependency input
hashes equal actual separately retained DependencySet bytes. No identity file or evidence report
is packed into that source tar. Verify actual source tar/rows before emitting this report.

### 4.3 Dependency report — actual verified wheel installation inventory

`DependencyReport={schema_version:"provider-dependency-closure-v1",producer_id:"provider-oci-build-v1",
toolset:S,platforms:[{platform:P,input:DependencySet,distributions:[Distribution]}]}`.
`Distribution={name,version,wheel:S,files:[InstalledFile]}`;
`InstalledFile={path:A,sha256:H,size_bytes:nonnegative,mode:0444}`.
Exactly seven distributions/name order; files path-sorted, unique across distributions and under
private site. Compare every actual extracted wheel member to RECORD (self-RECORD allowed its defined
empty hash/size); no unrecorded ZIP member or installed row. No .data remapping/scripts/symlinks/
encrypted entries/duplicate path/absolute path. Preserve license/dist-info/package resources.
Normalize installed modes only as declared; never execute setup.py or package hooks. The producer
emits rows from actual verified member bytes, not RECORD alone. Same-name files in two wheels refuse.
Wheel metadata must confirm no missing active dependency or incompatible Requires-Python; required
seven-node graph is idna:none,attrs:none,typing-extensions:none,rpds-py:none,
jsonschema:{attrs,jsonschema-specifications,referencing,rpds-py},
jsonschema-specifications:{referencing},referencing:{attrs,rpds-py,typing-extensions}.
This inventory authenticates bytes only after policy signing, not package safety or license approval.

### 4.4 Filesystem report — independently observed final image

`FilesystemReport={schema_version:"provider-filesystem-inspection-v1",
inspector_id:"provider-oci-inspect-v1",toolset:S,platform:P,index:OCIIndex,entry:PlatformEntry,
build_identity:ProviderBuildIdentityV2,source_closure:S,dependency_closure:S,
launch_policy:"provider-cpython-isolated-v1",config:ObservedConfig,filesystem:[FsEntry]}`.
`ObservedConfig={architecture:"amd64"|"arm64",os:"linux",entrypoint:[fixed worker],cmd:[],
env:[three fixed strings],working_dir:"/",user:"65532:65532",stop_signal:"SIGTERM",
diff_ids:[OciDigest]}`; diff_ids exactly each uncompressed layer hash in order, max128.
FsEntry is a closed tagged union, sorted unique path:
`{path:A,kind:"directory",uid:U32,gid:U32,mode:int0..4095}`;
`{path:A,kind:"file",uid,gid,mode,size_bytes:0..2**33,sha256:H,nlink:int1..8192}`;
`{path:A,kind:"symlink",uid,gid,mode,target:UTF8<=1024B}`.
Represent hard-linked regular names as file rows sharing measured inode-group content and correct
nlink; no invented host inode number. Resolve links inside the logical image, never the host.
Protected /opt/deeptwin-extension subtree has no symlink/hardlink/alias; mode/owner exact§3.
No boolean passed/qualified result field: the producer either emits complete observed rows after
all required comparisons or emits no report and returns a fixed error.

Recompute index/entry from actual OCI bytes; re-read identity and four schema files from the final
logical filesystem, call accepted provider parsers and schema-byte validator. Compare launcher and
every SourceFile/InstalledFile to actual image bytes; require exactly their union + identity + derived
parent directories under the protected prefix. No stale inherited private prefix, additional file,
SDK, import overlay or entrypoint shadow. Outside that prefix require exact pinned base final-tree
equality, except /opt ancestor creation/mode normalization to0755 if absent; never silently edit base.
Require every file/link/directory row from the replayed full root, not just the six metadata files.
Read actual ELF headers for CPython and rpds native members: ELF64/little-endian, e_machine62 for
amd64 or183 for arm64, appropriate EXEC/DYN type; dependencies must resolve inside pinned base/private
site. This catches wrong architecture, not ABI/loadability or arbitrary native-library safety.
The report includes actual source/dependency report S values; neither upstream report refers back.
Build identity.inputs joins source recipe and each dependency input, entrypoint/schemas measured;
extension/version/platform equal explicit build inputs. Reporter never accepts an expected report
dict or builder success flag. Parsing supplied report bytes alone remains structural, not inspection.

## 5. Actual OCI byte production and independent replay

Read frozen base descriptor graph and all selected blobs with size/hash checks. Index must contain
the two exact runnable entries; preserve its extra upstream attestation entries only as base input
metadata, not final runnable images. Final index is new and exactly two ordered platform manifests.
OCI raw JSON may use its native serialization; verify raw digests before duplicate-key/type checks.
Never reserialize an upstream object to make its hash match. New OCI JSON is sorted compact UTF8.

Builder installs selected wheel bytes into its logical overlay, app/schema/launcher bytes, and
generates each accepted BuildIdentity BEFORE image assembly. Write one deterministic USTAR layer:
root owners/numeric IDs, mtime0, uname/gname empty, sorted normalized paths, two512B terminators then
standard10240B padding; no PAX/link/device/whiteout entries emitted. SHA256(raw tar)=overlay diffID
and digest, media type application/vnd.oci.image.layer.v1.tar. No compression/tool-version ambiguity.
Final manifest reuses ordered raw base layers then adds overlay; max128 layers remains. Final config
copies base rootfs.diff_ids/history, appends overlay diffID and
`{created:"1970-01-01T00:00:00Z",created_by:"provider-oci-build-v1"}`; replaces runtime config with exact
User/Env/Entrypoint/Cmd/WorkingDir/StopSignal above. No inherited Volumes/Healthcheck/OnBuild/ports.
Top fields exactly architecture,os,created,config,rootfs,history; created fixed as recipe. Reject base
history/diffID inconsistencies; never claim an ignored inherited config setting was enforced.
Produce OCI-layout1.0.0 with index.json and blobs/sha256/<H>; every descriptor resolves actual bytes.

Inspector must reopen published output using new retained readers, not reuse builder's filesystem
map or rows. Check full raw graph, compressed hashes and uncompressed diffIDs; replay all base layers
and overlay independently. Input profile supports tar and gzip only; zstd is a deliberate producer
profile refusal, not a change to accepted descriptor grammar. Gzip CRC/footer/trailing concatenated
data rules are explicit: one member, complete footer, no extra trailing bytes. Per blob<=1GiB, each
platform selected compressed/raw closure<=4GiB, non-layer JSON<=1MiB; uncompressed stream<=8GiB total,
tar<=65536 entries read/platform, logical final rows<=8192, normal parser data chunks64KiB.
Bound wall time per prepare call300s monotonic and concurrent call count1; output/FD limits256.

Never tar.extractall or follow source archive links on the host. Logical tar replay handles regular
files, directories, in-image symlinks/hardlinks and OCI whiteouts; opaque whiteout removes lower-layer
children, not same-layer additions. Reject dangling/cyclic hardlinks, traversing symlink parents,
duplicate effective same-layer paths, escaping root, devices/FIFOs/sockets/sparse payloads. Retain
base symlink text, resolve with<=40 hops inside virtual root. PAX input only path/linkpath/size/mtime/
uid/gid, bounded64KiB, with strict numeric/path overrides; unknown extensions refuse this profile.
For archive directory spelling only, remove bounded leading ./ prefixes and one trailing / before
comparison; recognize . or ./ as root. Never normalize away an interior dotdot component, collapsed
empty component or conflicting effective path. Symlink targets may use .. only when the bounded
in-image resolution stays within root; never resolve via a host realpath/open call.
Whole base bytes are verified before replay. A legitimate upstream archive using unsupported features
is a concrete profile incompatibility, not a reason to skip inspection or rewrite the old base lock.

Publish new output only to an empty dedicated caller-selected release output directory with safe
retained parents, no overwrite; stage files/fsync then publish completed layout/report manifest.
Reject input/output overlap. On failure close all owned FDs, preserve primary BaseException, leave
no advertised complete release; interrupted temporary outputs never become policy/capsule inputs.

Exact input layout: input_root/base/ is the pinned base OCI layout; input_root/wheels/<exact filename>
contains eight distinct wheels; input_root/requirements-provider-private-v1-linux.lock and
input_root/provider-private-inputs-v1.json are the validated additive projections. No directory search.
Completed release root contains these13 fixed files, in manifest order:
`source.tar,recipe.json,dependency-inputs/amd64.json,dependency-inputs/arm64.json,reports/source.json,
reports/dependency.json,reports/filesystem-amd64.json,reports/filesystem-arm64.json,provider-lineage.json,
unsigned-policy.json,toolset.json,image/oci-layout,image/index.json` plus image/blobs/sha256/<H>.
`preparation.json` is canonical<=8192B, closed `{schema_version:"provider-release-preparation-v1",
extension_id,extension_version,files:[{name,sha256,size_bytes}]}`; exactly those13 entries, no self-hash.
Its graph closes over exactly the final two-platform OCI blobs (<=261 unique,<=8GiB total); reject
unlisted files or referenced missing blobs. toolset.json is the canonical128-row-max inventory,<=65536B.
Publish preparation.json LAST after all output/parent fsyncs. inspect_release reopens these paths and
compares every output hash; initial prepare uses the same inspector against its private incomplete
tree, requiring the known pre-inspection inputs but never advertising that tree as a completed release.

## 6. Acyclic joins and policy/capsule completion

```text
raw source44 + wheel bytes/metadata + frozen base bytes + producer toolset
  -> source tar / DependencySet[2] -> BuildRecipe -> SourceReport / DependencyReport
  -> BuildIdentity[2] -> image layers/configs/manifests -> final index
  -> independent FilesystemReport[2] -> provider lineage
  -> candidate descriptor/manifest + external allow-policy signature -> operator capsule
```

Source/dependency reports are pre-image inventories, not claims of prior final-image inspection.
Filesystem reports bind final index and their upstream reports; lineage.extraction_evidence_sha256
is the actual filesystem report byte hash. Do NOT embed lineage/report/index/policy/capsule into the
image: that would introduce image→report→image cycles. Candidate provenance_ref is actual completed
provider lineage; lineage contains full two-platform graph and accepted BuildIdentities, never candidate
or policy refs. This preserves existing normative schemas with no coerced tool identity.

Policy body exactly operator advisory fields except signature: schema_version literal
provider-allowed-image-policy-v1, explicit policy_id/key_id UUIDs, extension_id/version, existing
launch_profile=provider-private-transform-v1, full index/platforms, source/dependency report S,
filesystem_evidence exactly two S in platform order, launch_policy=provider-cpython-isolated-v1.
Signer signs canonical body; signature is canonical base64url64-byte Ed25519 with no padding.
Producer emits unsigned body only. finalize_capsule accepts actual signed policy bytes and provisioned
release public-key trust bytes, verifies exact key/signature and compares every body byte to its
independently recomputed body. Never create/sign with a test key or accept a verifier bool in production.
Finalization requires the same explicit input_root as independent inspection; it must reopen and
verify the actual base graph/eight wheels/additive projections and release under the same fixed
input profile, no-follow/currentness and non-overlap rules. Run the actual independent inspector,
compare both freshly produced report bytes with the published reports and lineage extraction hashes,
then reconstruct the policy body from that verified graph. Retain verified readers and recheck
currentness through final use/publication. No inferred sibling path, cache, locator callback or
signed-report-only substitution. Missing original inputs refuse finalization even with a valid
signature and internally consistent published reports. These raw inputs are not added to capsules
or required of the later operator capsule consumer; this is the producer's fresh-inspection boundary.
Release trust is external configured authority; a matching public key uploaded alongside a policy
does not become trusted. Key bootstrap is separate from instance receipt keys/F2 enrollment.
Proposed fixed verifier source: /run/deeptwin/provider-operator-enrollment/release-trust.json,
canonical<=8192B `{schema_version:"provider-release-trust-v1",keys:[{key_id:UUID,
algorithm:"ed25519",public_key:B64U32}]}`;1..8 keys sorted unique ID, canonical unpadded43-character
public-key encoding. Root-owned immutable no-follow file0440 under root-owned0750 ancestors, readable
only by the provisioned verifier group. Actual retained bytes/owner/currentness are mandatory; no
trust argument or client key upload. External bootstrap of this file remains required, not inferred
from the new schema or from a successful signature under an untrusted key.

Candidate input is real complete CandidateBundle bytes assembled by its existing authoring boundary
from emitted lineage and measured graph, with genuine supplied license/SBOM/policy documents. This
producer neither invents license approval nor registers it in DomainStore. Reparse full bundle and
validate descriptor/lineage/four schemas/original18 source documents and exact instance/slot tuple.
No dependency on a future request digest: capsule is reusable immutable release input for exact
candidate/context, not authorization to prepare/stage it. Native request validation remains operator A.

Capsule manifest/layout exactly operator advisory R1: candidate +four schemas +selected OCI closure
+signed policy +four actual reports. Exactly no other object leaves; two capsules select the same
common index but their own platform closure. Hash/size/codec-check every object after re-opening it;
deduplicate identical raw digest bytes only, preserving array roles/layer repetitions.<=141 leaves,
4GiB+4784128B total object bytes, manifest<=65536B. Reports contain audit hashes, not recursively
fetched source tar/wheel/toolset objects; their actual report bytes are included. Complete source/
wheel/base inputs remain in the release workspace for replay/provenance, not exposed core CAS.

## 7. Interfaces and connected acceptance

`prepare_release(*, source_root, input_root, output_root, extension_id, extension_version,policy_id,key_id)
 -> ReleasePreparation` opens exact filenames/profiles itself; returned immutable object exposes
output paths/descriptors, never a qualification boolean. input_root holds pinned base OCI layout,
eight wheel files and additive lock; no arbitrary fetch callback. Two platform outputs per call.
`inspect_release(*, input_root, release_root)->tuple[bytes,bytes]` recomputes observations from actual
base/wheel/source/report/image readers; no expected measured row arguments.
`finalize_capsule(*, input_root, release_root, candidate_bytes, source_documents, signed_policy_bytes,
platform, output_root)->Capsule` uses code-owned installed release trust, no caller public-key list.
Unsigned policy construction takes explicit policy_id/key_id; they are identifiers, not trust grants.
Fixed error codes invalid_input,unsupported_profile,input_unavailable,input_changed,too_large,
invalid_archive,graph_mismatch,filesystem_mismatch,policy_untrusted,publication_failed; no raw secrets/
artifact contents in diagnostics. OSError normalized, KeyboardInterrupt/SystemExit propagated after
bounded all-owned cleanup. A missing input never falls back to installed packages/image cache/network.

One acceptance sequence: verify actual44-file source set and real controlled wheel/base bytes;
construct both tiny complete OCI layouts; close/reopen independently; derive actual filesystem reports;
parse completed lineage; build a valid test candidate; externally sign fixture policy; re-open and
verify complete capsule. Changing builder-returned metadata without changing bytes must not fool the
inspector. Changing source, wheel member, schema, config, imported module, layer order/diffID, report
graph or policy with recomputed outer hashes must fail at its independent join. Tests use explicit
test roots/trust fixture, not production bypass or real keys.

Required negative vectors: all44 inputs versus omitted package initializer/function-local import;
SDK/HTTP extra package; wrong rpds architecture; missing active typing-extensions dependency; wheel
RECORD/ZIP mismatch/collision/.pth; TAR/PAX/gzip bombs/traversal/whiteout ordering/hardlink alias;
wrong identity/schema/input triple; unexpected private-prefix file; base tree mutation outside
prefix; stale report or inspector-returned dict; duplicate/noncanonical/over-limit codecs; absent
policy signature/wrong trust key; every capsule missing/unlisted evidence edge; file replacement
between hash and use; FD acquire/close/BaseException/fsync/publication failures; unchanged old locks.
Include a complete release with correctly signed, unchanged reports/policy whose original wheel
or base input is missing, replaced or incompatible: actual finalization must refuse before capsule
publication. Restore genuine controlled archive inputs to establish the positive path; do not
replace the inspector with an expected report dict or an authorization flag.
No test invokes target Python, native Docker, a model, credentials, network, SQL or core admission.

## 8. Genuine remaining conflicts/gates, not implicit success

No normative identity cycle was found with the ordering above. The following are real gates:

1. Additive seven-package input manifest must be reviewed against actual acquired wheel metadata,
   license resources and pinned artifact bytes; uv declarations alone do not complete T089/T084.
   No version/hash should be guessed from the host environment. This is missing release preparation,
   not permission to update old locks or use the gateway image.
2. No raw pinned base/wheel bytes were read here. Actual archive grammar/final-tree/report caps may
   expose a concrete incompatibility. Refuse and report it; review a narrow parser/profile correction
   before freeze rather than assume arbitrary base archives fit or weaken existing source contracts.
3. New image assembly is byte production, not native CPython/rpds loader execution. Both Linux
   architectures still need actual import/private-worker/socket/identify/transform tests, filesystem
   and sandbox verification, SBOM/license/provenance release review and authenticated signing.
   Pin the producer's interpreter and imported validation/signature libraries as tool dependencies,
   separate from the seven-package worker. Existing receipt Ed25519 verification may supply the
   trusted verifier; its PyNaCl dependencies must not leak into the private image. No source-toolset
   checksum alone proves those tools ran or passed native qualification.
4. F2 profile ruling retains trusted Portainer CE administration locally, prefers same-host Unix
   access portably, and keeps actual provisioning/admission feasibility OPEN. No image/report can
   establish engine access exclusion or eliminate trusted administrator interference.
5. Task43 is provisional until reconciled with accepted control integration. Capsules do not assert
   all-five-check qualification, durable binding, model choice, credential activation or live send.

These gaps are named producer/native/release work, not a demand that ordinary users operate a CLI.
This proposed delivery is useful before native gates: it produces and independently inspects actual
bounded OCI byte artifacts from real local inputs and refuses missing/untrusted inputs honestly.
