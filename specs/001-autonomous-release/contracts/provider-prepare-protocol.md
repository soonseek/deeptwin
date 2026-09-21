# Provider preparation protocol and pure source joins

Controller contract, 2026-09-19. Authority: ../spec.md FR-032, ../decisions.md ADR-014,
provider-image-lineage.md and provider-source-production.md. This is the bounded Task38
dependency of the existing provider staging lifecycle, not runtime admission or a new product scope.
State: independent preflight READY after the candidate-absence/head-digest corrections.
No implementation until explicit dispatch.
The normative sources below are accepted Task34/35 code; Task37 is a later service integration
dependency, not an import requirement for these pure codecs.

Select protocol-first over a table-only migration or a broad service rewrite: the actual service
cannot reconstruct provider requests with its tool-only v1 codec. Freeze the exact wire and byte
joins first; the following integrated producer must own migration, replay and publication together.
No SQL from an advisory becomes normative here. User-approved autonomous continuation governs
technical recommendations; existing product scope and security/operational gates are unchanged.

## Protocol and file ownership

Ten NEW files; existing source, old schema exports and tests remain byte-identical:

| Path | Responsibility |
| --- | --- |
| app/deployment/provider_prepare_contracts.py | Closed parsers, structural candidate/source/inventory joins and deterministic request/cancellation constructors. No I/O, clock, RNG, DB or current-handle admission. |
| app/deployment/provider_prepare_schema_exports.py | Fresh deterministic seven schema exports; no old schema widening or domain-record registration. |
| app/tests/test_provider_prepare_contracts.py | Independent fixtures/oracles, deferred-edge failures, v1/v2 separation, geometry/lineage joins and all bounds. |
| schemas/v2/deployment/provider-preserved-inventory-v1.schema.json | Frozen inventory byte grammar. |
| schemas/v2/deployment/provider-stage-request-v2.schema.json | Closed provider effect_payload. |
| schemas/v2/deployment/provider-request-v2.schema.json | Complete request envelope. |
| schemas/v2/deployment/provider-prepare-input-v1.schema.json | Owner command input grammar. |
| schemas/v2/deployment/provider-cancel-input-v1.schema.json | Owner cancellation selector grammar. |
| schemas/v2/deployment/provider-cancellation-v1.schema.json | Provider cancellation publication grammar. |
| schemas/v2/deployment/provider-request-anchor-v2.schema.json | Immutable domain content grammar; not registered by this task. |

Schema IDs are urn:deeptwin:schemas:v2:deployment:{filename-stem}, Draft2020-12, sorted UTF8 JSON,
two-space indent/final newline. Exported schemas are detached. Runtime bytes are domain canonical_json;
raw parsers reject duplicate/unknown fields, noncanonical JSON, invalid UTF8, floats/bool-as-int,
invalid UUID/hash/base64/time encodings. UUID is canonical nonnil, H lowercase hex64, B32 canonical
unpadded base64url32; source/document hashes are H, unchanged envelope request digest/nonce are B32.
Wire preflight bounds: request65536/depth16/items8192/members32/string1024/int2**40; inventory16384,
anchor8192, cancellation8192; command input4096/depth4/items32/members8/string256. Narrow field
grammars still apply. Errors use existing DeploymentPrepareError fixed codes, never raw data.
Schema factories are provider_inventory_schema, provider_stage_schema, provider_request_schema,
provider_prepare_input_schema, provider_cancel_input_schema, provider_cancellation_schema and
provider_request_anchor_schema; exported_schemas() maps precisely the seven filenames above.

Public interfaces:

    parse_provider_prepare(value: dict) -> dict
    parse_provider_cancel(request_id: str, value: dict) -> dict
    parse_provider_inventory(raw: bytes) -> dict
    parse_provider_request(raw: bytes, *, profile: OriginProfile) -> dict
    parse_provider_cancellation(raw: bytes, *, profile: OriginProfile) -> dict
    validate_provider_anchor_content(content: dict) -> None
    make_provider_request(
        *, candidate_bundle: CandidateBundle,
        source_bundle_files: tuple[tuple[str, bytes], ...],
        provider_schema_bytes: tuple[bytes, bytes, bytes, bytes],
        inventory_bytes: bytes, slot_number: int, profile: OriginProfile,
        request_id: str, nonce: bytes, actor_ref: dict,
        created_ms: int, ttl_seconds: int,
    ) -> bytes
    validate_provider_request_sources(
        raw: bytes, *, candidate_bundle: CandidateBundle,
        source_bundle_files: tuple[tuple[str, bytes], ...],
        provider_schema_bytes: tuple[bytes, bytes, bytes, bytes],
        inventory_bytes: bytes, profile: OriginProfile,
    ) -> None
    make_provider_cancellation(
        request_bytes: bytes, *, profile: OriginProfile, cancelled_ms: int,
    ) -> bytes

The bytes/candidate parameters are inert inputs. The later service supplies them from verified CAS,
candidate registry and actual source handle; no constructor output proves that origin by itself.
No `authorized`, `verified`, `already_validated`, trust callback or generic RecordRef admission.

### Exact closed fields

Prepare input is {command_id,kind:"extension_stage",candidate_id,slot_id:int1..16,
expires_in_seconds:int60..86400,source_context_sha256:H}. The last field is an expected-current
selector compared to the startup handle, not an override. Preserve old prepare input unchanged.
Cancel input is {command_id,request_digest:B32,expected_revision:1}; parser binds path request_id.
Only prepared revision1 cancellation is supported by this producer, not post-receipt cancellation.

Inventory is exactly {schema_version:"deployment-provider-preserved-inventory-v1",vault_id:UUID,
instance_id:hex32,origin_profile_digest:H,topology_id:UUID,topology_sha256:H,
at_event_sequence:int0..2**40,installations:[entry0..16]}.
Each entry is exactly {installation_ref,extension_id,request_ref,head_revision:1,head_digest:H,
slot_id:int1..16,service_identity,accepted_event_id:UUID,staged_event_id:UUID}.
The refs have the existing exact EntityRef shape, respective kinds extension_installation and
deployment_request, version1. head_digest is the actual existing v3 installation-head row hash,
not installation_ref.sha256. Its exact preimage is:

    {namespace:"deployment-prepare-storage-v3",table:"installation_heads",
     row:{extension_id:entry.extension_id,request_id:entry.request_ref.id,
          revision:entry.head_revision,
          installation_anchor_digest:entry.installation_ref.sha256}}

Require head_digest == lowercase SHA256(domain canonical_json(preimage)) in the pure inventory
parser. Every preimage value is supplied in the entry; no DB/storage import or row-existence claim.
Pin an independent expected digest and reject a mismatching hash even if outer hashes are refreshed.
IDs follow existing extension/Broker grammars. Sort by extension_id
then installation_ref.id; no duplicate extension/installation/request/slot/event IDs. Structural
parser accepts0..16; first producer admits only0..1 legacy staged installations because v3's actual
first-only producer cannot honestly supply a larger supported history. No qualified/bound entries.
Inventory identity/geometry must match the actual source bundle. Every service_identity derives
from the original slot(); an inventory cannot occupy the selected never-reserved target slot.
Additionally make_provider_request and validate_provider_request_sources must require the reparsed
candidate manifest.extension_id absent from all inventory extension_id values. A preserved same
extension in another slot contradicts the absent/revision1 stage; reject it even with refreshed
inventory/request hashes. This does not replace later actual reservation/history checks.
The source bundle contains no vault ID: this pure parser checks vault UUID grammar only; actual
vault agreement is established by the later real DomainStore producer/anchor/index joins, not
inferred from profile or asserted by an arbitrary caller.

Provider request keeps exactly v1 envelope fields, with schema="deployment-request-v2",
domain="deeptwin-deployment-request-v2", kind="extension_stage", preconditions={}. Time/actor/nonce
and digest algorithm remain explicit: B32(SHA256(canonical_json(all fields except request_digest))).
Duration is60..86400 whole seconds, timestamp milliseconds canonical UTC. New effect_payload is
exactly the v1 stage effect fields except schema_id="deeptwin.extension-stage-request.v2", plus:

    stage_profile = "claude-text-transform-v1"
    source_context = {context_id:UUID,epoch:1,sha256:H,size_bytes:int1..16384}
    geometry = {sha256:H,size_bytes:int1..65536}
    preserved_inventory = exact parsed inventory object
    preserved_inventory_sha256 = SHA256(actual inventory_bytes)

Existing effect fields remain extension_id,manifest_digest,service_descriptor_digest,
selected_platform_entry,new_service_effect,expected_installation_head={state:"absent"},
expected_next_installation_revision=1. There is no future installation ref or alternate precondition
bag. Request binds actual source context, final geometry and inventory bytes, not their caller hashes.
The new parser validates digest/profile with its own closed schema; it must not call the tool-only
validate_projection after changing a discriminator back to v1. Source-join validation derives the
unique matching slot from the exact original geometry and descriptor tuple, bounded to16 slots.

Reparse CandidateBundle; require provider-port-v1/provider/oci_extension_service/runtime_worker,
the actual four provider schema bytes and Task34 parse_provider_lineage plus
validate_provider_descriptor_lineage. Join descriptor's service UID/GID, broker tuple, single socket
mount, no named-volume mounts, exact private worker argv, no-network/secret/grant policy and resource
budget to the same original slot facts as v1. Preserve no extra secrets/grants, filesystem_needs=
[owned_scratch], read-only-rootfs/no-new-privileges/cap_drop ALL/runtime-default seccomp/no host
namespaces. Task34 alone does not perform these topology/policy joins; this constructor must.
Never call old stage_for_candidate with a rewritten provider object. These are declared constraints,
not measured runtime policy or proof of semantic operation support.

Cancellation fields are exactly {schema:"deployment-provider-cancellation-v1",
domain:"deeptwin-deployment-provider-cancellation-v1",request_id,request_digest,instance_id,
origin_profile_digest:B32,source_context_sha256:H,preserved_inventory_sha256:H,
lifecycle_revision:2,cancelled_at}. Derive every binding from parsed request bytes. Expiry suppresses
a pending request as old lifecycle does, but emits no cancellation marker. Require cancellation
time at or after creation and strictly before expiry; the service owns authoritative clock sampling.
Cancellation/expiry never free a reservation or allow re-preparing the same extension; exact
command replay is distinct.

Anchor content is exactly {schema_version:"deployment-provider-request-anchor-v2",request_id,
request_blob_ref,source_documents,preserved_inventory_blob_ref,candidate_ref,
topology_id,topology_revision:1,slot_id,reservation_revision:1,prepare_command_id}.
source_documents is the exact ordered18 entries {name,blob_ref}, using Task35 filenames/
caps. Every BlobRef is operational and has the same vault_id; request cap65536, inventory16384.
Candidate_ref keeps extension_manifest/version1. Envelope remains domain kind deployment_request,
version1, ID=request_id, parent_refs=[candidate_ref], actual owner/access/retention roots.
The later domain validator registers a new content discriminator, not an invented version2 history
record. Keeping all18 refs in the anchor gives the actual domain graph/CAS associations ownership
of the source bytes; do not rely on unindexed hashes inside source-context.json to retain them.

R1 controller ruling (before acceptance/release): the named wrapper collection is source_documents,
not a reserved *_refs field. Preserve the exact eighteen {name,blob_ref} wrappers and every
constraint above. The unchanged generic DomainStore reference walker must discover all nested
blob_ref values; no provider-specific exception or reference-grammar relaxation is allowed.
Task38 tests exercise that existing pure walker; actual put/load/graph retention belongs to Task41.
No accepted/released wire record is migrated by this pre-acceptance correction.

## Acceptance and non-effects

Independent tests must prove: both original origin modes/platforms and capacities1/16; correct old
slot geometry; source graph/hash/ID/profile mismatches with refreshed downstream hashes; Task34
lineage/schema/argv joins plus each missing topology/network/resource check; inventory duplicate/
sort/vault/type/cap errors; source/context/request/nonce/actor/timestamp digest sensitivity; selected
slot excluded from inventory; preconditions with any member refused; exact canonical wire bytes;
v1 tool parser rejects provider request and new parser rejects v1; old tools' fixtures unchanged.
No I/O import/side effect, schema retrieval or DB/API registration. Tests should read only accepted
literal schema fixtures where needed; synthetic build hashes are labeled, not native evidence.

Focused future command: python -m pytest app/tests/test_provider_prepare_contracts.py.
Narrow covering: accepted test_provider_lineage.py, test_provider_source_contracts.py,
test_deployment_prepare_contracts.py and
test_deployment_source_contracts.py. No tests run for this advisory. A missing upstream module is
a dependency failure, not a protocol assertion RED. Promotion freezes these exact schemas before
the service/migration task; no table is installed by Task38.


## Actual dependency interfaces and explicit guardrails

Read accepted app/extensions/provider_lineage.py, app/extensions/candidate_contracts.py,
app/deployment/provider_source_contracts.py, provider_geometry.py, prepare_contracts.py and
prepare_schema_exports.py; old domain refs/blob/anchor validators are read-only references.
ProviderLineage lives in app/extensions/, not app/deployment/. CandidateBundle lives in
app/extensions/candidate_contracts.py; its content_bytes is authoritative inert input.
Require exact CandidateBundle and reparse bounded content_bytes using parse_canonical/parse_bundle;
do not trust caller-replaced manifest/descriptor/documents cache fields or an overridable accessor.
This creates no registry ownership proof. Profile is an actual exact OriginProfile value;
validate its own invariants rather than accepting a duck-typed digest/instance object.

Use validate_provider_source_bundle on the exact ordered eighteen-byte tuple. Revalidate the
original source graph; compare full original topology/profile/platform/instance to the supplied
profile, provider context and inventory; geometry derives from the original topology. Schema input
is exactly tuple(four bytes) in the accepted provider identity order, not fetched from a URI.
Locate provenance via the candidate's actual metadata ref; parse_provider_lineage plus
validate_provider_descriptor_lineage performs structural schema/image/command joins. Add the
separate slot/network/resource/isolation checks specified above; neither accepted helper grants
runtime or native authority.

Parsers return detached dicts; make_provider_request and make_provider_cancellation return canonical
bytes, unlike the historical tool make_request which returns a dict. Request-source validation
reconstructs the complete canonical request from its own parsed selector/actor/nonce/timestamps
plus independently supplied bundle/schema/inventory bytes and compares exact bytes. It must not
accept mismatching inventory merely because a caller recomputed the outer digest.
The anchor validator checks exact names/order/caps, UUID/entity/blob grammar and same vault across
all operational BlobRefs. EntityRef has no vault_id: candidate_ref/installation_ref/request_ref
vault membership is a later real DomainStore graph check, never inferred here or added to their
closed shape. It does not open CAS or register a domain handler.

Reuse scalar/schema constructors and canonical codecs when compatible without changing old
schemas/validators, but do not duplicate the complete tool-only projection/constructor merely to
rewrite its discriminator. Provider-specific policy joins may be explicit; no generic new staging
framework or wider kind switch is needed. Errors must remain fixed DeploymentPrepareError;
too-large inputs use too_large, malformed values invalid_input. Public boundaries preserve
KeyboardInterrupt/SystemExit and normalize ordinary malformed data failures, including hollow
exact objects and integer conversion limits, without exposing source data.

## Non-effects and evidence boundaries

All ten files are new; no existing production/schema/test file is writable. No source opener,
filesystem API, DB table/migration, service/route/catalog registration, credentials, clock/RNG,
runtime qualification/binding, cancellation publication or real request issuance is implemented.
All future v4 DDL/producer details remain advisory until their own exact contract and review.
No new live/paid model, native/Docker/root, key, actual data or public push action.
Synthetic lineage/image digests establish structural fixtures only.

The follow-on service must retain global original-slot reservations including terminal requests,
reconstruct supported old inventory from actual history, bind source bytes through real CAS and
owner authority, and preserve legacy v1 request/replay behavior. This pure layer accepts structural
inventory 0..16; the first actual producer is separately limited to supported 0..1 legacy staged
installation histories. Pure parse success is never an admission shortcut.
