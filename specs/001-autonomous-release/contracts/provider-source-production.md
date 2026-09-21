# Provider source production: immutable bundle and additive renderer

Controller contract, 2026-09-19. Independent preflight required before implementation.
Spec authority: ../spec.md. This promotes the reviewed architecture proposal, not an operational
deployment authorization. Original tool/source releases, source document bytes, wire contracts,
packaging and ordinary validation behavior stay intact. Task35 is strictly nineteen new files
with no existing-file changes. Task36 may modify only the enumerated resource-lifetime surfaces
in app/deployment/files.py and app/deployment/public_init_files.py, in addition to its six new
files listed in section1. All other existing source and test files remain byte-identical.

## Implementation tranche boundaries

Task35 implements the pure geometry, source document codecs, exact bundle validator and complete
additive renderer (all sections other than actual filesystem initialization). Task36 implements
the real initializer under section6, its private filesystem helper and controlled temporary-tree
fixture/tests, plus independent lifecycle tests and the section1 narrow corrections to its existing
dependency factories. Task35's nineteen-path scope is unchanged. Neither task alone
claims a built/runnable image or actual deployment. The renderer names the fixed Task36 entrypoint
as a required consumer; until Task36 and image packaging/native validation are accepted, its
Compose output is a candidate source artifact, not a runnable product claim.

The combined design below is normative for their relationship. Task-specific file ownership is
specified in each brief; an initializer file is NOT a Task35 edit. No runtime source opener,
journal migration, owner API, stage operator, worker-image build or live provider call is authorized.
Plain CPython exact-image packaging follows the separately recorded image-trust requirements;
these source digests do not authenticate the selected initializer image.

The owned-channel-layout-v1 policy is deliberate: initializer verifies immutable source bytes and
safe owned filesystem layout, but never parses or approves channel payloads. Populated restarts do
not require changing the immutable context. Every future request/receipt consumer must independently
validate payload bytes, references, signatures, inventory and authority before admission. Preserve
all metadata-safe final/staging files untouched; refuse unsafe or concurrently changing layout.

## Selected independently testable tranche

Implement an actual pure provider source renderer and an actual fixed-path UID0 initializer,
tested against real temporary files/directories with explicitly simulated ownership/mount/native
sampling. Deliver all source documents, their final publication locations and the additive Compose
service that runs the implemented initializer. No runtime source opener, journal migration, owner
API, operator stage execution, worker-image build, qualification or provider send is added.

Unbuilt images do not block authoring this code. The new initializer has its own code-owned
version ID, exactly like the existing initializers. An immutable initializer image reference is
a required deployment-instance input; tests supply a visibly synthetic reference. No fake digest,
default image, installed-operator claim or successful test-authority mode enters production.

The complete original tool/receipt expansion is the renderer's baseline. Original topology ID,
OriginProfile, slots, recipes, public documents, original volume definitions and initializer services
stay unchanged. Add four provider volumes and one initializer service. Provider static documents
live together in one atomically published directory, solving the missing-dependency-location problem
without ten separate single-file roots. The complete bundle is immutable after publication.

## 1. Exact ownership and public interfaces

Production ownership is divided strictly by task. Task35 creates only its nineteen approved paths:
four pure modules and recipe below, ten section3 schemas, three pure test modules and their fixture.
Task36 creates three new production files and three test/fixture files, plus only the two explicitly
enumerated existing-file lifecycle changes. Its detailed contract is provider-source-initialization.md.

| New production file | Task | Responsibility / interface |
| --- | --- | --- |
| app/deployment/provider_geometry.py | 35 | Final ProviderGeometry value, derive_provider_geometry, parse_provider_geometry, validate_provider_geometry_sources (§2). |
| app/deployment/provider_source_contracts.py | 35 | Fixed recipe/layout constants; strict document parsers; pure source graph validation. |
| app/deployment/provider_source_schema_exports.py | 35 | Fresh deterministic schemas for all ten new document types listed in §3, exported_schemas(). |
| app/deployment/provider_source_render.py | 35 | render_provider_sources(...) -> ProviderSourceArtifacts; no I/O or process/network imports. |
| deploy/security/deployment-provider-source-recipe-v1.json | 35 | Exact canonical recipe bytes below; compare to code-owned recipe, not arbitrary caller policy. |
| app/operations/deployment_provider_source_init.py | 36 | initialize_provider_sources() -> dict; main(argv=None) -> int; fixed paths only, no override/test-mode flags. |
| app/operations/_provider_source_init_files.py | 36 | Private staged18-file bundle publication and retained publication identities only; no duplicate read-only observer/snapshot implementation. |
| app/deployment/_provider_source_files.py | 36 | Shared fixed read-only retained bundle observer and complete namespace snapshots; exact contract provider-source-observation.md, reused by later runtime reader; no publication. |

Task35 creates app/tests/test_provider_geometry.py, app/tests/test_provider_source_contracts.py,
app/tests/test_provider_source_render.py and app/tests/provider_source_fixture.py. Its schemas are
the ten section3 filenames under schemas/v2/deployment/. Task36 does not edit any Task35 file.
Task36 creates app/tests/test_provider_source_init.py, app/tests/provider_source_init_fixture.py
and app/tests/test_deployment_source_lifecycle.py. Lifecycle tests are independent of provider
initializer/renderer/fixture imports. Existing interfaces and ordinary validation/error/byte/
metadata/hash/currentness/payload-policy behavior stay unchanged. No other existing source/test,
v1 schema, tool packaging or Task33/34 changes; no broad RetainedHandle/context-manager changes.

| Existing file | Task36-only lifecycle edit surface |
| --- | --- |
| app/deployment/files.py | open_directory, open_regular, Directory.open/recheck_current, SourceFile.open/close: track returned descriptors through ownership transfer; cleanup after failure including BaseException; attempt all owned cleanup without masking a primary. Preserve close_fd semantics, ordinary error mappings, validation, namespace policies/scanner. |
| app/deployment/public_init_files.py | _PublicInputFile.open, _ReleaseInput.open/close, _install_namespaces_impl: protect partially acquired resources and aggregate cleanup; preserve ordinary errors, ownership, publication/mutation order, bytes and metadata checks. No change to _install_source_impl, _RetainedTargetFile, _read_at, _release or public signatures. |

Renderer keyword-only inputs, all mandatory:

    base_compose_bytes, base_service_ids_bytes,
    original_prepare_recipe_bytes, original_prepare_instance_bytes,
    original_receipt_recipe_bytes, original_receipt_instance_bytes, original_trust_bytes,
    provider_recipe_bytes, provider_instance_bytes, provider_trust_bytes

ProviderSourceArtifacts is a frozen inert value with exact fields:

    original_artifacts          # unchanged ReceiptSourceArtifacts
    geometry_bytes
    exchange_bytes, ingress_bytes, consumption_exchange_bytes
    context_bytes, pins_bytes
    bundle_files                # exact tuple[(filename,bytes),...] in §4 order
    expanded_compose_bytes
    expansion_record_bytes

No supplied result object is an authority input. Initializer recomputes artifacts from retained
raw inputs; validation reparses exact bytes, not cached dictionaries or caller booleans.
Expected input aggregate cap2MiB; generated Compose cap1MiB; bundle aggregate cap524,288 B.
All errors use existing DeploymentSourceError family and its fixed non-reflective codes.
Pure invalid inputs map to deployment_source_invalid. Real source/native unavailability may map
to deployment_source_unavailable. main returns0 on success,1 on closed failure,2 on nonempty argv;
stderr contains only the fixed code. Preserve process-control exceptions after closing resources.

## 2. Final geometry, integrated into this producer

ProviderGeometry has immutable canonical content_bytes, digest, as_dict(), slot(n); no public
constructor. Methods revalidate exact type and stored bytes, reject forged/hollow/subclass objects
and return detached containers. Invalid geometry raises ProviderGeometryError with exact text
"invalid provider geometry"; source producer maps it to DeploymentSourceError.

    derive_provider_geometry(*, original_recipe_bytes, original_instance_bytes,
                             original_topology_bytes) -> ProviderGeometry
    parse_provider_geometry(raw) -> ProviderGeometry
    validate_provider_geometry_sources(geometry, *, original_recipe_bytes,
                                       original_instance_bytes,
                                       original_topology_bytes) -> None

Verify the original recipe using unchanged contracts.parse_recipe; parse the original instance and
reconstruct OriginProfile; parse topology with that original profile, original recipe hash and
instance platform. Explicitly match instance topology ID and slot_capacity. No native host query.
For each n=1..capacity require exactly unchanged contracts.slot(instance_id,n). The renderer obtains
these original topology bytes from unchanged render_receipt_sources, never makes another UUID.

Closed geometry fields:

    schema_version = provider-stage-geometry-v1
    original_recipe = {sha256:hex64,size_bytes:606}
    original_instance = {sha256:hex64,size_bytes:int1..4096}
    original_topology = {sha256:hex64,size_bytes:int1..65536}
    origin_profile = exact original OriginProfile.as_dict()
    instance_id = hex32
    topology_id = canonical nonnil UUID
    topology_revision = 1
    platform = linux/amd64 | linux/arm64
    control = {service_identity:control,uid:20102,gid:20102}
    slots = complete ordered original slot objects, length1..16

OriginProfile keeps its exact existing fields/rules and recomputed digest. Instance IDs agree.
Every slot remains: service ext-{instance}-{nn}; uid/gid22000+n; channel cp-ext-{instance}-{nn};
pair_gid23000+n; mount xs{nn}, volume dt-{instance}-ipc-xs{nn}, path /run/deeptwin/ipc/xs{nn},
read_only=false,purpose=broker_pair; socket worker.sock; protocol deeptwin-extension-worker-v1;
resource budget memory1073741824/cpu1000/pids128/tmpfs134217728. All strings/ordering/fields must
equal the old slot() output. Transport identity does not assert provider semantic execution.

Geometry has no current/free/reserved state. Future journal admission must retain original topology
FK/reservation uniqueness and all cancelled/expired/rejected reservations. There is no second slot
registry, replacement/recycling, selected slot, source currentness token or source opener here.
A parsed geometry with consistent declared hashes is inert until joined to actual source bytes.

## 3. Exact document graph, grammar and pins

Each new document uses schema_version and is closed at every level. Runtime bytes use unchanged
domain canonical_json. UUID means existing canonical nonnil UUID; H means lowercase hex64; B32 is
canonical unpadded base64url32 with round-trip/pad-bit validation. Exact integers exclude bool.
No floats, duplicate keys, unknown fields, invalid UTF8, BOM, noncanonical input or null fields.
SHA256 always hashes exact raw canonical bytes. Preserve original documents under their old parsers.

New source documents use max_depth12/items4096/members32/string1024/int2**40 before semantic
validation. Individual caps below override the general cap; geometry remains65,536 B, all remaining
new documents≤16,384 B except recipe8,192, instance8,192, channels8,192, pins8,192 and record8,192.
The strict shape validators narrow integer/string fields further as specified. All hashes are
computed from supplied bytes or code-owned constant bytes, never accepted as unverified substitutes.

Export ten Draft2020-12 schemas, each with ID urn:deeptwin:schemas:v2:deployment:{filename-stem};
fresh detached dictionaries; sorted keys, two-space indent and final newline. Public factories are
provider_geometry_schema(), provider_recipe_schema(), provider_instance_schema(),
provider_trust_schema(), provider_exchange_schema(), provider_ingress_schema(),
provider_consumption_schema(), provider_context_schema(), provider_pins_schema(),
provider_expansion_record_schema(); exported_schemas() maps these exact filenames:

    provider-stage-geometry-v1.schema.json
    provider-source-recipe-v1.schema.json
    provider-source-instance-v1.schema.json
    provider-public-trust-set-v1.schema.json
    provider-outgoing-exchange-v1.schema.json
    provider-receipt-ingress-v1.schema.json
    provider-consumption-exchange-v1.schema.json
    provider-source-context-v1.schema.json
    provider-source-pins-v1.schema.json
    provider-source-expansion-record-v1.schema.json

### Fixed recipe — actual new implementation IDs

Exact recipe fields/constants:

    schema_version = deployment-provider-source-recipe-v1
    recipe_id = private-provider-source-channels-v1
    original_prepare_recipe = {
      path:deploy/security/deployment-prepare-recipe-v1.json,
      sha256:03490ee7c676a0c78915fdef3ec48c52d6b88838ad71bce001ad2fe72f5e67b7,
      size_bytes:606
    }
    original_receipt_recipe = {
      path:deploy/security/deployment-receipt-recipe-v1.json,
      sha256:3417fbc488ab745019b909564282cc9ff971c99fa2d5ba592e4faeb2f742e173,
      size_bytes:487
    }
    renderer_id = deeptwin-provider-source-expand-v1
    initializer_id = deeptwin-provider-source-init-v1
    layout_id = provider-source-bundle-v1
    worker_profile = claude-text-transform-v1
    channel_bootstrap_policy = owned-channel-layout-v1
    bundle_file_limit = 18
    bundle_bytes_max = 524288
    request_bytes_max = 65536
    cancellation_bytes_max = 8192
    receipt_bytes_max = 16384
    consumption_bytes_max = 8192

The original prepare recipe already pins unchanged base Compose SHA256
6a18faa38379724a18466f39b42f66c4405fe11eb790b8e9c21addd39cbd152e,size25731 and service IDs
4330b2080d5579847909fb086ebde6144b1fc54fdee6251a97383acd1e5565f4,size9544. The renderer invokes
the existing complete original renderer, which verifies both actual inputs. The new recipe hash
is computed from its exact new canonical document. No unexplained future-image hash belongs in it.

### Deployment instance and public trust declaration

Provider instance exact fields:

    schema_version = deployment-provider-source-instance-v1
    original_prepare_instance_sha256:H
    original_receipt_instance_sha256:H
    geometry_sha256:H
    provider_recipe_sha256:H
    provider_trust_sha256:H
    context_id:UUID
    exchange_id:UUID
    ingress_id:UUID
    consumption_exchange_id:UUID
    initializer_image:string

Every digest matches actual supplied/derived bytes. The four new UUIDs are pairwise distinct and
different from all four original topology/exchange/ingress/consumption UUIDs. Original instance and
receipt instance IDs are derived through the existing seven-input renderer; no caller profile,
new topology ID, slot, path or permissions input.

initializer_image is an explicit fully qualified immutable reference, never an interpolation:
registry/repository@sha256:H, ASCII≤584 B, exactly one @. Registry≤253 B consists of lowercase
DNS labels, each1..63 ASCII bytes matching [a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?,
dot-separated, with optional port canonical decimal1..65535. The host is localhost, a dotted
hostname, or a single label with an explicit port: a non-localhost host must contain a dot or
carry an explicit port. Bare single-label registry names without a port are rejected rather than
silently selecting a default registry. Repository has one or more slash-separated components, each
[a-z0-9]+(?:[._-][a-z0-9]+)*, combined≤255 B. No scheme, userinfo, whitespace, tag, query,
fragment, dollar, braces, backslash, dot components or empty components. It selects the initializer
image only. It is an operator declaration; the renderer does not fetch or verify OCI contents.
Local code/tests do not require a real image build. No worker image or stage action is emitted.

Provider trust document exact fields:

    schema_version = deployment-provider-public-trust-set-v1
    version = 1
    instance_id:hex32
    origin_profile_digest:H
    keys:[{key_id:UUID,algorithm:ed25519,public_key:B32,
           trust_class:instance_operator,
           adapter_ids:[deeptwin-provider-stage-operator-v1]}] #1..8
    adapter:{operator_adapter:deeptwin-provider-stage-operator-v1,
             operator_version:1.0.0,
             deployment_profile_id:exact original OriginProfile deployment_profile_id}

Require exact original instance/origin, unique sorted key IDs and unique public keys. Keys are
public declarations supplied explicitly; no key generation/secret/signature validation. The adapter
name reserves the fixed protocol identity for future operator code; it does not claim that code is
implemented, installed or qualified. This source producer publishes data, never admits that trust
into journal/API/runtime. Old operator-v1 trust is neither widened nor reused as provider trust.

### Channel documents

For all three, common exact fields are schema_version, document_id:UUID, revision:1, instance_id,
origin_profile_digest:H, geometry_sha256:H, provider_recipe_sha256:H, provider_instance_sha256:H.
document_id is the instance's corresponding exchange/ingress/consumption UUID. Common identities
are original control={service_identity:control,uid:20102,gid:20102} and declared operator endpoint
={service_identity:deployment-receipt-job,uid:20113,gid:20113,pair_gid:21201}.
Reusing its source-channel filesystem identity is not implementing or authenticating an operator.

Outgoing schema_version=deployment-provider-outgoing-exchange-v1 adds control, reader=operator,
and outgoing={volume_name,container_path,owner_uid:20102,group_gid:21201,root_mode:0750,
namespace_mode:0750,final_file_mode:0440,control_read_only:false,reader_read_only:true,
namespaces:[cancelled,requests]}. Exact volume/path comes from §4.

Ingress schema_version=deployment-provider-receipt-ingress-v1 adds outgoing_exchange_sha256,
trust_sha256, writer=operator, reader={service_identity:control,uid:20102,gid:20102,pair_gid:21201},
incoming={volume_name,container_path,owner_uid:20113,group_gid:21201,root_mode:0750,
namespace_mode:0750,final_file_mode:0440,writer_read_only:false,control_read_only:true,
namespaces:[receipts]}.

Consumption schema_version=deployment-provider-consumption-exchange-v1 adds
outgoing_exchange_sha256,trust_sha256,receipt_ingress_sha256,control,reader=operator,
outgoing={volume_name,container_path,owner_uid:20102,group_gid:21201,root_mode:0750,
namespace_mode:0750,final_file_mode:0440,control_read_only:false,reader_read_only:true,
namespaces:[consumed]}.

No channel document references context/pins/Compose, preventing cycles. Exact mode values above
are four-character strings, not octal JSON numbers. Unknown keys or reordered fixed namespace lists
refuse. parsers validate their full cross-document bindings through validate_provider_source_bundle.

### Context, pins and expansion record

Context exact fields:
schema_version=deployment-provider-source-context-v1, context_id, epoch:1, instance_id,
origin_profile_digest, topology_id, topology_revision:1, geometry_sha256,
worker_profile:claude-text-transform-v1, layout_id:provider-source-bundle-v1,
documents:[{name,sha256,size_bytes}] for exactly the first16 filenames of §4, in that order.
All references bind complete actual bytes. It contains no pins or self-reference.

Pins exact fields:
schema_version=deployment-provider-source-pins-v1, instance_id,origin_profile_digest,context_id,
context_sha256,context_size_bytes,provider_recipe_sha256,provider_instance_sha256,geometry_sha256.
They are derived from actual context and documents. No input pins bypass recomputation.

Expansion record exact fields:
schema_version=deployment-provider-source-expansion-record-v1,scope=provider_sources_only,
renderer_id=deeptwin-provider-source-expand-v1,initializer_id=deeptwin-provider-source-init-v1,
original_expansion_sha256,original_expansion_size_bytes,original_expansion_record_sha256,
provider_recipe_sha256,provider_instance_sha256,geometry_sha256,context_sha256,pins_sha256,
initializer_image,expanded_compose_sha256,expanded_compose_size_bytes.
The record is an output artifact, not included in the source bundle or hashed by its context.
Sizes are exact positive integers within respective caps. No self-hash or reverse dependency.

Public parser names: parse_provider_recipe, parse_provider_instance, parse_provider_trust,
parse_provider_exchange, parse_provider_ingress, parse_provider_consumption,
parse_provider_context, parse_provider_pins, parse_provider_expansion_record.
Each signature is exactly (raw: bytes) -> dict: structural validation plus derivable constants,
not acceptance of reference hashes. No reference/profile/callback overrides. One complete
validate_provider_source_bundle(bundle_files: tuple[tuple[str, bytes], ...]) -> None requires
exact tuple/string/bytes types, reparses every file, recomputes geometry,
checks exact filenames/caps/hashes/IDs/recipe/layout/channel/context/pins and original relationships.
It validates retained original input/documents with unchanged original parsers; it makes no native
currentness claim and does not require base Compose bytes merely to validate the source bundle.
No caller may supply a dict of already-validated documents to skip this join.

Independently reproduce the original renderer's deferred source joins: original outgoing exchange
ID equals the prepare instance exchange ID; original receipt instance prepare/trust pins equal the
actual prepare-instance/trust bytes; original ingress ID equals receipt-instance receipt_ingress_id
and all its prepare/exchange/receipt/trust digests equal actual bundle bytes; original consumption
ID equals receipt-instance consumption_exchange_id and all its exchange/receipt/trust/ingress
digests equal actual bundle bytes. Require the four original IDs mutually distinct. Geometry
separately binds topology ID, capacity, recipe, profile and platform to actual prepare sources.
Test each deferred edge with a structurally valid alternate document and refreshed downstream
context/pins so rejection cannot be explained only by a stale outer hash.

## 4. Where every dependency lives

New roots are fixed; names are not input fields:

| Compose volume key | Container root | Initialized owner/group/mode | Control mount |
| --- | --- | --- | --- |
| provider-stage-sources | /run/deeptwin/provider-stage-sources | 0:21201,0750 | read-only |
| provider-deployment-outbox | /run/deeptwin/provider-deployment-outbox | 20102:21201,0750 | writable |
| provider-deployment-receipts | /run/deeptwin/provider-deployment-receipts | 20113:21201,0750 | read-only |
| provider-deployment-consumed | /run/deeptwin/provider-deployment-consumed | 20102:21201,0750 | writable |

Each volume's actual name is dt-{original_instance_id}-{volume_key}. Static root has exactly one
child, documents/, owner0:21201/mode0750. Its18 files are owner0:21201/mode0440, regular,
single-link, no symlinks/aliases, no overlays below the root:

| Ordered filename under documents/ | Exact bytes | Cap B |
| --- | --- | --- |
| original-prepare-recipe.json | original input | 4096 |
| original-prepare-instance.json | original input | 4096 |
| original-topology.json | original renderer's topology | 65536 |
| original-outgoing-exchange.json | original renderer's exchange | 8192 |
| original-receipt-recipe.json | original input | 4096 |
| original-receipt-instance.json | original input | 4096 |
| original-trust-set.json | original input | 16384 |
| original-receipt-ingress.json | original renderer's ingress | 8192 |
| original-consumption-exchange.json | original renderer's consumption exchange | 8192 |
| geometry.json | final geometry projection | 65536 |
| provider-recipe.json | exact new recipe input | 8192 |
| provider-instance.json | exact new instance input | 8192 |
| provider-trust-set.json | exact new public trust input | 16384 |
| outgoing-exchange.json | new provider exchange | 8192 |
| receipt-ingress.json | new provider ingress | 8192 |
| consumption-exchange.json | new provider consumption exchange | 8192 |
| source-context.json | new complete context | 16384 |
| source-pins.json | new pins | 8192 |

No image, key secret, copy of DB, Compose file or expansion record belongs inside the bundle.
A future opener has a complete fixed location for every dependency: start from startup context pin,
read source-context.json and exact files, compare all bytes, then check native file/mount ownership.
No generic path or source URL resolver is needed. Epoch1 is immutable; rotation needs its own contract.

Outbox has exactly cancelled/ and requests/, receipts exactly receipts/, consumed exactly consumed/;
namespace owner/group matches its root and mode0750. The selected owned-channel-layout-v1 policy
initializes only virgin roots and inspects already-owned populated namespaces read-only. Reuse the
unchanged files._scan_namespace metadata-only mechanism with these NEW code-owned _NamespacePolicy
constants in the shared read-only helper; never modify or reuse the narrower old cancellation/consumed
policy as if it allowed new bytes:

| Provider policy / namespace | writer_uid / primary_gid / pair_gid | Final limit | Stage limit | Per-file cap B |
| --- | --- | --- | --- | --- |
| _PROVIDER_REQUEST_NAMESPACE / requests | 20102 / 20102 / 21201 | 16 | 32 | 65536 |
| _PROVIDER_CANCEL_NAMESPACE / cancelled | 20102 / 20102 / 21201 | 16 | 32 | 8192 |
| _PROVIDER_INCOMING_NAMESPACE / receipts | 20113 / 20113 / 21201 | 64 | 32 | 16384 |
| _PROVIDER_CONSUMED_NAMESPACE / consumed | 20102 / 20102 / 21201 | 16 | 32 | 8192 |

Final names are exactly lowercase hex64.json, regular/single-link, writer-owned/pair-group/mode0440,
size1..cap. Staging names use the existing .stage-{canonical-nonnil-UUID}.tmp grammar and must be
regular/single-link, writer-owned, size0..cap; allowed (group,mode) pairs are (primary_gid,0600),
(pair_gid,0600), (pair_gid,0440). All existing scanner signature/name/directory rechecks apply.
The namespace scan maximum is96 entries; the four channel namespaces together allow at most240
entries (48+48+96+48). The18 static document files are a separate bound.

This check does not open/read channel payload bytes or assert filename-to-payload hash agreement,
cryptographic signature authenticity, JSON validity, matching context, complete publication or
receipt/request admission. Metadata-safe malformed or unrelated content and interrupted staging
files are preserved untouched. Initializer success reports only the source digests and safe observed
layout, never valid payloads or readiness. Future consumers must validate every payload and its
context/authority before admission, and handle staging states under their own protocol. Ordinary
populated restarts therefore need no recipe/context/epoch rotation. The new8192-byte consumed-marker
cap reserves the future rich provider marker profile; historical4096-byte tool policy stays unchanged.

## 5. Complete pure rendering algorithm and additive Compose boundary

1. Call unchanged render_receipt_sources with the seven original inputs; retain its entire returned
   artifacts byte-for-byte. Verify new recipe constant, instance, trust, derive final geometry and
   compare all input declarations. Reject duplicate source IDs and invalid image reference.
2. Derive provider exchange → ingress → consumption, then ordered16 document references → context
   → pins. Assemble18 exact bundle files and validate the whole bundle. No random IDs/times.
3. Parse the exact original expanded Compose returned by that renderer. Add only the four new
   volumes, six new external configs and the new provider initializer service described below.
   Extend control.volumes by the four mounts; add the single required environment pin
   DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256=context hash and depends_on provider-source-root-init.
   Require original control group_add contains21201 exactly once; do not mutate it.
4. Preserve every original volume/config/service, and every control field/list entry except the
   explicit additions. Reject all name, target, prefix and config collisions. Never rerender an
   arbitrary caller-expanded Compose or silently merge conflicting declarations.
5. Emit sorted compact UTF8 Compose JSON with ensure_ascii=False/allow_nan=False under existing
   1MiB bound and the exact expansion
   record. Strip the permitted additions from a detached mapping and require equality to the
   original expansion; original artifact bytes are returned unchanged.
   Compose is not a new source document: preserve its legitimate finite CPU fractions and existing
   floats. Do not pass Compose through the domain integer-only canonical_json codec or apply the
   new documents' no-float rule to it; match the unchanged receipt renderer's byte codec.

New initializer service key provider-source-root-init:
image=provider_instance.initializer_image;
entrypoint=[python,-m,app.operations.deployment_provider_source_init]; command=[];
user=0:0; group_add=[21201]; restart=no; init=true; privileged=false; read_only=true;
network_mode=none; cap_drop=[ALL]; cap_add=[CHOWN,FOWNER,FSETID];
security_opt=[no-new-privileges:true]; tty=false; stdin_open=false;pids_limit32;mem_limit64m;cpus0.25;
ulimits.nofile soft/hard256. It depends_on both deployment-prepare-root-init and
deployment-receipt-public-init with service_completed_successfully. Control adds the same condition
for provider-source-root-init. No worker/operator service is created.

Initializer mounts the four new volumes writable and the five existing public source volumes
read-only: extension-topology-public, deployment-exchange-public, deployment-verify-public,
deployment-receipt-ingress-public, deployment-consumption-exchange-public, at their original paths.
No slot, old outbox/receipts/consumed, database, provider gateway socket, Docker socket or secret mount.
Use existing long mount form type=volume,volume.nocopy=true; never shadow a nested old source path.

Six external configs, named dt-{instance_id}-provider-source-{suffix}, mounted under fixed
/run/deeptwin/provider-source-init-input/, uid0,gid0,mode0440:

    suffix original-prepare-instance -> original-prepare-instance.json
    suffix original-receipt-instance -> original-receipt-instance.json
    suffix original-trust           -> original-trust-set.json
    suffix instance                 -> provider-instance.json
    suffix trust                    -> provider-trust-set.json
    suffix pins                     -> provider-source-pins.json

The initializer image includes fixed files under /opt/deeptwin:
deploy/compose.yaml, deploy/security/service-ids.json, the unchanged original prepare/receipt
recipes, and deploy/security/deployment-provider-source-recipe-v1.json. Files are regular root-owned
0444 or0644 under read-only release ancestors0750/0755; no symlink or inode aliases. Their exact
content is validated against recipe constants. Packaging that includes these files is ordinary code
work; an actually built/verified image and its explicit reference remain deployment inputs.

## 6. Actual initializer and temporary-tree acceptance

The no-argument initializer requires euid0 and a supported Linux native platform matching original
instance platform. Retain fixed release files and six config inputs through existing
public_init_files._ReleaseInput/_PublicInputFile mechanisms; retain their original parent entries.
Input directory is0:0/0750 with exactly six config files. Recompute the full renderer output and
require byte equality with supplied provider-source-pins.json. No trusted-looking pins shortcut.

Open and retain the five original public source files using existing bounded SourceFile mechanics:
topology.json,exchange.json,trust-set.json,ingress.json,consumption-exchange.json at their old roots.
Compare each to original renderer output, preserving its original UID/GID/mode rules. These are
read-only dependencies, not targets to initialize or repair. Recheck them throughout. An existing
tool has no files rewritten, owner changed, socket opened or installation state advanced.

Preflight ALL four targets before any mutation. Verify distinct mount roots/backings/devices as
appropriate using existing mounts/files mechanics; forbid aliases, prefix overlays, duplicate inode
objects and overlap with protected release/config/old source paths, builtin roots and any present
old deployment/slot roots. All original/protected mounts must be read-only; new target mounts writable.
Retain the mapping and recheck it and every original name/FD signature before/after each publication.
No new runtime source opener or changes to source_common._OPTIONAL_SOURCE_ROOTS are needed: this
initializer explicitly includes these boundaries in its own fixed validation set.

Accepted target states only:
(a) genuinely empty Docker-created root0:0/0755, or
(b) completely initialized, correct owned root with the exact immutable bundle or exact namespace
set whose empty/populated contents satisfy only the metadata policies in §4.
Mixed roots are allowed only if each whole root independently matches (a) or (b).
Any partial static-bundle stage directory, wrong owner/mode/name, unknown namespace or unsafe leaf,
hardlink/symlink, changed input/source, stale retained descriptor or conflicting context refuses.
Recognized regular channel staging files are allowed and preserved, not confused with an incomplete
static-bundle directory. A changed channel payload is not inspected for validity by this initializer.
Never chown, chmod, truncate, delete or replace an occupied/conflicting root to make it match.

For virgin static root, keep it root-owned and create a fresh hidden .stage-{UUID}.tmp directory
mode0700 by no-follow/exclusive directory operations. Write all18 exact files with O_EXCL/O_NOFOLLOW,
set final0:21201/0440, fsync each and verify hash/size/name/FD identity. Set staged directory0:21201/
0750, fsync, then no-replace rename that directory to documents and fsync root. Set/validate root
0:21201/0750 and retain/recheck complete published tree. A failure may leave staging or an incomplete
root; do not delete arbitrary remnants or claim rollback. A retry refuses that partial root.
This directory publication is new bounded code in the initializer's private filesystem helper;
do not misuse the existing
one-file helper, which requires its root to have exactly one file.

Create empty namespace roots using _install_namespaces_retained with unchanged filesystem effects
and narrowly corrected resource lifetime after all preflight checks, only for virgin roots, in
outbox→receipts→consumed order; use exact owners/groups/modes above.
Reopen newly initialized roots after ownership changes with the same device/inode identity.
For every owned namespace, retain its directory and perform the unchanged metadata scanner with
the exact new policy. Preserve a bounded name/signature snapshot for every final AND staging entry:
the existing scanner's returned staging count alone is insufficient to compare stages across later
guards. The shared read-only metadata wrapper records and compares names/stat signatures before
and after the scanner and across each subsequent guard; it reads no file content and changes no
shared scanner. Recheck namespace/root signatures and complete snapshots before/after every effect
and at completion. Observed concurrent changes refuse boundedly; no automatic retry loop or repair.
Already-complete roots receive no writes, preserving inode/mtime/mode/bytes, including invalid or
unparsed-but-metadata-safe payloads and interrupted regular staging files. Verify all four
roots and protected inputs again, then return exactly
{context_sha256,geometry_sha256,provider_recipe_sha256}. No ready marker or event; missing any root
prevents success. At explicit acquisition, validation, publication and cleanup call boundaries,
all returned and recorded owned FDs/handles receive cleanup on success/failure/BaseException.
Attempt each independent owned close even if another fails; secondary cleanup cannot mask a
primary operation error. Preserve the same primary process-control object and ordinary class/code
mappings. If cleanup alone fails, propagate its first failure after all other attempts. Never retry
an attempted close or close borrowed resources. This is exception-safe ownership, not atomicity
against arbitrary VM interruption, interpreter/kernel death or a substituted syscall that acquires
an FD but never returns it. Deterministic tests inject after acquisition returns and ownership is
recorded. OS refusal of close proves attempt-all, not successful closure. No process-wide FD scan/
manager, descriptor guessing, production injection hook or shared RetainedHandle change.
Set finite≤256 live FDs,18 static leaves,≤96 entries per channel namespace,≤240 total channel entries
and524,288 static bytes; reject overflow before writes. Channel scanning retains directory FDs and
bounded stat observations, not one open FD per payload. No input-driven traversal and no unbounded
retry or recovery loop.

Tests call the real initializer using the existing fixture pattern: map fixed paths into a temporary
tree and simulate uid/gid, native/mount sampling and unavailable no-replace syscall only at the test
boundary. Exercise real file creation, retained descriptors, signatures, writing, rename/fsync and
cleanup. Production factory has no root argument, injectable verifier or synthetic success flag.
Tests must label simulated ownership/mounts; they do not prove Linux isolation or image inclusion.

## 7. Required tests and honest end state

| Test boundary | Required observations |
| --- | --- |
| Geometry/source contracts | Both original origin modes/platforms/capacities1/16; original topology/recipe identity preserved; all derived slot facts; actual source joins; strict malformed/canonical/type/cap cases; detached immutable values; export parity. |
| Renderer | Independent exact18-file oracle and SHA checks; correct graph order/no self-cycle; all three source IDs plus context fresh/disjoint; original expansion byte-identical; only allowlisted Compose additions; exact image/config/root mapping; no worker/operator/secret mounts. |
| Image-reference grammar | Accept localhost, registry:5000, and a dotted registry with the required repository and digest; reject a bare non-localhost single-label host without a port and a64-byte DNS label. No registry access or image authenticity claim. |
| Complete bundle | Reparse original documents and all new docs; hash/size/role/order/context/profile/geometry swaps fail; both wrong and structurally valid alternate topology mismatches fail at source joins; no ambient source defaults. |
| Initializer positive | Real temporary-tree first initialization and byte/inode-preserving identical rerun; mixed wholly initialized/virgin roots; populated restarts preserve metadata-safe malformed JSON, unrelated/unparsed bytes, incorrect payload/hash/signature claims, and interrupted regular staging files without opening/reading payloads or approving them; exact18 static files and modeled modes/owners; native metadata explicitly simulated. |
| Initializer negative | No writes before full preflight; wrong original source, replaced FD/name/parent/mount during reads/publication; unknown namespace/name, nonregular/multilink file, wrong owner/group/mode, oversize or excess final/stage entries; hardlink/symlink/alias/overlay; bad source key/recipe/pin/image; mutation of a staging file while stage count stays constant; concurrent addition/removal/replacement causes bounded refusal without retry/repair; crash before/after document directory rename, namespace publication and fsync leaves no reported success. |
| Channel policy bounds | All four new policies at their final/stage/file-size boundaries, incoming96-entry and aggregate240-entry acceptance plus overflow denial; final minimum1 versus empty staging allowed; all three existing stage group/mode states; new cancel/consumed8192-byte metadata acceptance while old4096-byte tool policies and tests remain unchanged; no context rotation on populated restart. |
| Dependency lifecycle | Independent temporary-tree tests for every section1 acquisition/cleanup surface; ordinary success/error/mode/hash/currentness behavior characterized before edits and unchanged afterward; KeyboardInterrupt/SystemExit/custom BaseException after recorded acquisitions; preserve primary object despite cleanup failure; attempt all owned closes, never borrowed resources or retry; close-alone first failure after all attempts; path-walk and retained/raw namespace handoffs covered. |
| Regression/containment | Original source document/recipe/render/init output bytes and ordinary behavior unchanged; only section1 two-file lifecycle diff permitted; existing tests byte-identical; imports have no runtime/admission effects; no DB/journal/API/opener/operator/Docker/HTTP/key use; fail nonroot/unsupported native platform without fake mode. |

Focused new tests: test_provider_geometry.py, test_provider_source_contracts.py,
test_provider_source_render.py, test_provider_source_init.py, test_deployment_source_lifecycle.py,
all under app/tests/. Fixtures provider_source_fixture.py and provider_source_init_fixture.py
are separate support modules, not test commands. Unchanged covering tests are
test_deployment_source_render.py, test_deployment_source_contracts.py,
test_deployment_source_files.py, test_deployment_prepare_init.py,
test_deployment_receipt_source_render.py and test_deployment_receipt_public_init.py.
Task35's six-family run stays unchanged. Task36 runs its two new test modules plus
test_deployment_source_files.py, test_deployment_prepare_init.py,
test_deployment_receipt_public_init.py and accepted test_provider_source_render.py.
No broad suite or native calls for this tranche.
Independent fixtures must not generate expected documents by invoking the producer under test.

Acceptance proves a complete, deterministically rendered source package and implemented initializer
that installs it correctly under controlled filesystem tests. It does not prove actual source
installation, built-image contents, an admitted operator, provider stage acceptance or any of the
five qualification checks. Task30 credentials remain stored_unbound; Task32 generation stays denied.
Claude API-only and Codex subscription plus optional API product scope remain unchanged.

The next code dependencies are concrete: package the implemented initializer/worker with measured
closure, implement source opening and journal-v4 continuation, and implement the exact provider
stage request/receipt operator plus authoritative payload validation in every consumer. The current
source initializer already preserves populated owned channels through non-authorizing metadata
checks; later payload validation does not require recipe/context rotation. Those consumers need separately
reviewed contracts, not invented source flags. Unbuilt images and absent operator code are work we
can implement; actual native builds, provisioning, live signed effects and qualification evidence
are separate operational activities. This source-producer task need not wait for those activities.
