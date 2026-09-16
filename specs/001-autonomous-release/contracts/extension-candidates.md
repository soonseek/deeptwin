# Inert executable extension candidates (v2)

Implementation contract for the bounded T087 registration prerequisite. This document freezes bounded candidate
serialization and owner-authenticated registration; it does not authorize executable staging,
installation, qualification, topology changes or dispatch. It supplements data-model §3.1 and
ADR-014 without changing historical v1 values. Every external statement is untrusted metadata.

## Version and source decision

The new path uses **`extension-manifest-v2`**, executable-only in this slice, and **`extension-service-descriptor-v1`**. Keep historical `extension-manifest-v1` and `ExtensionManifest` parser/schema readable exactly as-is. Add distinct `ExecutableExtensionManifest` and `ExtensionServiceDescriptor` types; the candidate admission path accepts only their exact new schemas. No v1 coercion, inferred port, copied `verified` state or in-place schema rewrite. Code-free v2 representation requires a separate explicit union addition; current code-free historical behavior is unchanged.

The manifest's artifact reference points to the descriptor digest. The descriptor has **no manifest digest/ref**. Support documents are leaves: their text/JSON is not traversed as a source of authoritative references to a descriptor, manifest, installation, request or receipt. The candidate registration record points backward to both immutable documents. The deployment request then binds manifest/descriptor digests and the derived exact selected-platform projection. No self-hash field is placed in either document; their content digests are external identities.

Owner registration means “preserve this bounded versioned metadata for deployment review.” It does not mean source authenticated, image available, license approved, installed, qualified or executable. The source locator is inert display/audit text, never fetched. Candidate parsing creates no ChannelSpec, WorkerRouteBinding, process, mount, grant or runtime profile. Source/provenance/license statements remain unverified until their real owners establish them.

## Common types and caps

All defined contract objects below are closed (`additionalProperties=false`); every named field is required unless explicitly nullable. Uninterpreted SBOM/provenance leaf objects are the explicit exception: their bounded JSON is evidence, not a new authoritative schema. Raw canonical UTF-8 uses existing ADR-008 `canonical_json`/`parse_canonical`, no duplicate/unknown/BOM/trailing/float/surrogate input. Limits are an additional bounded candidate profile:

- Each manifest/descriptor ≤262,144 bytes; each support document ≤65,536 bytes; complete registration payload ≤1,048,576 bytes, depth≤32/items≤10,000. Runtime serialization tests must enforce aggregate limits, not only each child.
- `Id`: existing extension identifier grammar `[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?`, 1–128 ASCII bytes. `BrokerId`: existing broker grammar `[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*`, 1–64 bytes. Keep the distinct grammars rather than silently normalizing names.
- `Version`: existing numeric `major.minor.patch`, ≤32 ASCII bytes; component integers 0–2^31−1; no tags/ranges/build suffixes. Closed inclusive min/max pairs compare numerically. Schema/port IDs use their registered exact strings.
- `HexDigest`: 64 lowercase hex. `OciDigest`: exact `sha256:` plus HexDigest. No truncation, mutable tag, URL query or base64 conversion here. Future common deployment fields use their separate checked b64u32 conversion.
- `MetaRef`: exact `{document_kind,sha256,size_bytes}`; kind is one of `service_descriptor|license|provenance|sbom|network_declaration|resource_declaration|isolation_declaration`; digest HexDigest; bytes positive within the matching cap. This is an **inert content reference**, not an EntityRef, permission grant or installation ref. Resolve actual bytes from the same candidate store and recompute digest/size/kind; no missing-ref success.
- Use existing `EntityRef` only for actual already-stored actor and policy roots in host registration metadata. There are no existing domain `network_policy`/`resource_profile`/`extension_service_descriptor` EntityRef kinds to pretend to resolve. These are requested-declaration references, not semantic-port grant/config refs with similar names. No deployment request accepts these values until its separate exact source/admission contract is implemented.
- Nonnegative integral limits reject bools. Ordered arrays retain order; set-like arrays are sorted+unique by their explicit key. Ref arrays sort by `(document_kind,sha256)`.

For this version, `schema_versions` uses the code-owned set containing `app.domain.schemas.SCHEMA_VERSION`
(`domain-v1`), not values discovered in uploaded documents. New registered versions require a later
explicit code/catalog update; a declaration is never compatibility qualification.

`source.locator` is an inert ASCII HTTPS URI: exact lowercase `https` scheme, explicit canonical
host, optional canonical decimal port1..65535, no userinfo/query/fragment/backslash/control/space,
and empty or absolute path. Host is lowercase DNS labels1..63bytes/total253 (no leading/trailing
hyphen or trailing dot), canonical IPv4, or bracketed compressed lowercase IPv6 without zone or
IPv4-mapped addresses. Path uses URI unreserved/sub-delim characters, colon, at-sign, slash and
uppercase two-hex percent escapes; no malformed escape or literal/percent-decoded dot segment,
control, slash or backslash hidden inside a segment. Never resolve/fetch the host at parsing or
registration. Allowed metadata hosts do not become runtime egress permissions.

`image_repository` has an explicit same-form host/optional port plus one or more slash-separated
lowercase repository components. Component grammar is
`[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*`; preserve multiple hyphens and double underscores.
No scheme/tag/digest/userinfo/query/fragment/percent escape/empty or dot segment. The512-byte cap
includes host and path. This uses the repository-name component convention of the primary
[Distribution reference implementation](https://raw.githubusercontent.com/distribution/reference/main/regexp.go),
checked2026-09-15; explicit canonical host/port and bounded length are this framework's profile.

## Exact manifest-v2

```text
{
 schema_version: "extension-manifest-v2",
 extension_id: Id,
 extension_version: Version,
 extension_kind: member of existing EXTENSION_KINDS,
 port_contract_version: exact existing PORT_CONTRACTS key,
 artifact: {artifact_form: existing catalog artifact form, service_descriptor_ref: MetaRef(service_descriptor)},
 source: {kind: "third_party"|"built_in"|"operator_deployment", locator: safe HTTPS URI ≤2048 bytes,
          provenance_ref: MetaRef(provenance)},
 license: {expression: nonempty control-free text ≤256 bytes, text_ref: MetaRef(license)},
 compatibility: {framework_min: Version, framework_max: Version,
                 extension_api_min: Version, extension_api_max: Version,
                 schema_versions: sorted unique 1..16 registered schema-version strings ≤64 bytes},
 refinements: {config: ClosedRefinement,
               operations: sorted unique 0..52 [{operation: registered operation for this port,
                  request: ClosedRefinement, result: ClosedRefinement,
                  extension_error_codes: sorted unique 0..64 Id}]},
 requirements: {grant_ids: sorted unique 0..64 Id,
                network_policy_ref: MetaRef(network_declaration),
                resource_profile_ref: MetaRef(resource_declaration),
                isolation_profile_ref: MetaRef(isolation_declaration),
                filesystem_needs: sorted unique subset of ["owned_scratch","declared_named_volumes"],
                secret_needs: sorted unique 0..16 Id},
 migration_policy: "none"|"compatible"|"required",
 uninstall_policy: "retain_records"|"block_if_bound"
}
```

`ClosedRefinement` is an exact bounded schema object accepted by existing `validate_refinement_schema`, additionally ≤65,536 canonical bytes. For no extra fields use `{"type":"object","properties":{},"additionalProperties":false}`. Missing operation entries mean this same empty request/result refinement and no extension errors. Config/request/result refinements apply only to the existing three namespaced extension fields; do not add operation/effect/terminal/core-error definitions. Use `PORT_CONTRACTS[port].operations` and existing `PORT_SCHEMA_IDS`; do not copy a new port catalog into the manifest.

Validate the exact kind/artifact/port/trust/staging tuple using existing `validate_port_tuple`, deriving trust tier and staging authority **from the core catalog**, never from source.kind or a manifest claim. Exclude `code_free_definition`. This parser can represent all executable catalog forms; a later bounded stage profile is intended for the ordinary `tool-port-v1` / `oci_extension_service` / runtime-worker class. Release-pinned runner and deployment-trusted storage/vault remain unsupported for owner stage admission until their separate source gates exist. A `built_in` label does not pass those gates.

All descriptor identity and requirement refs equal the manifest values. Source provenance ref and license text ref equal the descriptor's corresponding evidence refs. Every compatibility range is internally ordered; compatibility is a declared requirement, not proof that the actual deployment passed. No optional invented `qualified`, `installation_id`, `binding_ref`, `grant_ref` or source-verification flag is accepted.

## Exact acyclic service descriptor

```text
{
 schema_version: "extension-service-descriptor-v1",
 extension_id: Id, extension_version: Version, port_contract_version: registered port,
 service_identity: BrokerId,
 image_repository: canonical registry-host/repository without tag/digest/credentials/query ≤512 bytes,
 index: OciDescriptor(index),
 platforms: sorted unique 1..2 PlatformEntry,
 command: {argv: ordered 1..32 control-free UTF-8 strings, each 1..256 bytes,
           protocol_id: BrokerId},
 uid: integer 1..2^32−1, gid: integer 1..2^32−1,
 network_policy_ref: MetaRef(network_declaration),
 resource_profile_ref: MetaRef(resource_declaration),
 isolation_profile_ref: MetaRef(isolation_declaration),
 secret_needs: sorted unique 0..16 Id,
 broker_endpoint: {channel_id: BrokerId, requester_service: BrokerId,
                   responder_service: BrokerId, protocol_id: BrokerId,
                   requester_uid: integer 1..2^32−1, requester_gid: integer 1..2^32−1,
                   pair_gid: integer 1..2^32−1, socket_mount_id: BrokerId, socket_name: BrokerId},
 socket_mounts: sorted unique 1..4 SocketMount by mount_id,
 named_volume_mounts: sorted unique 0..8 DataMount by mount_id,
 evidence: {sbom_ref: MetaRef(sbom), provenance_ref: MetaRef(provenance), license_ref: MetaRef(license)}
}
```

`OciDescriptor` is `{media_type,digest,size_bytes}`; `digest=OciDigest`, `size_bytes` integer 1..2^40. Exact allowed media: index=`application/vnd.oci.image.index.v1+json`; manifest=`application/vnd.oci.image.manifest.v1+json`; config=`application/vnd.oci.image.config.v1+json`; layer=`application/vnd.oci.image.layer.v1.tar` or `...tar+gzip` or `...tar+zstd`. These are metadata bounds, not an allowed download budget. No Docker manifest-list fallback in this new executable descriptor profile: canonical descriptor requires one OCI index. Existing upstream build-input support for Docker lists remains unchanged.

`PlatformEntry` is `{platform,manifest,config,layers}`. Platform exact `linux/amd64|linux/arm64`; manifest/config are matching OciDescriptors; `layers` is ordered 1..128 `{position,media_type,digest,size_bytes}` with positions exactly 1..N. Layer repetition is not automatically rejected: ordering/digest equality must preserve the descriptor rather than deduplicate it. Index appears once outside platforms. Both platforms must be present for a candidate advertised for the two-host release; a single-platform candidate may be stored as inert unsupported metadata, but is not a positive stage candidate in this bounded first profile.

`SocketMount` is `{mount_id,volume_name,container_path,read_only,purpose}` with BrokerId names, exact `container_path="/run/deeptwin/ipc/"+mount_id`, `read_only=false`, `purpose="broker_pair"`. It identifies a requested dedicated named volume, never a host path. `DataMount` has the same fields with container_path=`"/var/lib/deeptwin-extension/"+mount_id`, boolean read_only and purpose=`"extension_state"`. Distinct IDs, volume names and container paths across both arrays; no empty/relative/dot/encoded/separator/path override values. A later ordinary-tool stage profile is intended to require exactly one socket mount and `named_volume_mounts=[]`; registration may preserve the other bounded declarations but approves none.

`broker_endpoint.responder_service == service_identity`, endpoint protocol equals command protocol, requester differs from responder, requester UID/GID differs from service UID/GID, pair_gid differs from both service groups; socket_mount_id resolves exactly one SocketMount. These mirror the existing ChannelSpec's data checks **without constructing it**, since ChannelSpec includes real paths/ownership and does not represent candidate metadata. The descriptor has no `pair_root` host path, raw channel key, worker nonce or active route. For the first profile, protocol_id is the normative ADR-014 `deeptwin-extension-worker-v1` transport identity, not a claim that an operational channel for it is implemented; `deeptwin-worker-ipc-v2` remains the existing broker framing version, not the semantic port ID. These three identities must not be conflated.

Command argv is operator-visible image configuration, not host execution. The first argv element must be an absolute normalized **image-internal** path with no dot segments, e.g. `/opt/extension/worker`; no shell-string interpolation, host path mount, env map, setup hook or pre/post-start command field exists. The product never runs it. This metadata check cannot prove what an image binary does; later operator image/entrypoint and isolation qualification must establish that.

### Requested policy documents

Use these exact small leaf declarations for the bounded ordinary-tool candidate; they express requested constraints, not grant authority:

- Network: `{schema_version:"extension-network-declaration-v1",network_mode:"none"}`.
- Resources: `{schema_version:"extension-resource-declaration-v1",memory_bytes,cpu_millicores,pids_limit,tmpfs_bytes}`; positive integers with memory 16MiB..4GiB, CPU 100..4000, pids 1..256, tmpfs 1MiB..1GiB and tmpfs≤memory. Expansion requires an explicit versioned profile; these limits never imply host capacity qualification.
- Isolation: `{schema_version:"extension-isolation-declaration-v1",read_only_rootfs:true,no_new_privileges:true,cap_drop:["ALL"],seccomp_profile:"runtime-default",privileged:false,host_namespaces:[]}`. This is a declared baseline only; runtime-default is not a claim of a qualified pinned seccomp implementation. Future exact isolation profiles bind their real qualification evidence before execution.

The owner candidate must have network none, no secrets, no grant IDs and owned_scratch only in this later bounded stage profile. Candidate representation for other requirements is not permission to stage them. Support license is UTF-8 text; SBOM/provenance are bounded strict canonical JSON objects preserved as untrusted evidence, with no schema-derived authority. A source-verification or license-approval consumer is still missing: reject attempted `verified=true` authority fields rather than infer trust from document presence.

## Actual registration boundary

The fixed first-party browser route is `POST /api/v1/extensions/candidates`, relative to the
deployment origin base. It accepts exactly `{command_id,manifest,service_descriptor,documents}`.
The whole body is bounded by1MiB before buffering; strict raw JSON parsing rejects duplicate keys,
unknown top-level fields, invalid Unicode/nonfinite numbers, BOM and trailing bytes. HTTP JSON need
not arrive canonical; stored documents are canonicalized once and then verified byte-for-byte.
No generic command argument grammar is widened to accommodate this route.

`documents` is1..32 entries of exact `{document_kind,content}`. License content is a string
whose exact UTF-8 bytes are preserved. Other leaves are bounded strict JSON objects; policy leaves
must have their exact schemas above. Recompute each MetaRef digest/size/kind. Reject duplicate,
unknown, unused or missing leaves; reference reuse within one bundle is allowed. The descriptor
is supplied separately, not duplicated in documents. Parse freezes nested data; mutating a caller's
dict/list or a returned mapping cannot change registered bytes.

The service receives the actual persistent-owner `AuthenticatedRequest` and exact DomainStore. It revalidates
the persistent owner/session in the same SQLite writer before idempotency lookup and registration.
Neither a constructed CandidateRef, copied/stale session, caller actor ID nor a callback can grant
authority. Registration does not require an operational worker, image fetch, extension grant or
legacy in-memory registry. The product remains usable as a web service.

A new registration atomically commits domain anchor/associations, the private registration index,
capacity state, one redacted event and an exact command receipt. Host-created registration metadata is
`{schema_version:"extension-candidate-registration-v1",candidate_id,extension_id,manifest_digest,
service_descriptor_digest,support_refs,registered_by,registered_at,source_class:"owner_proposal",
command_id}`. UUID candidate ID and actual human actor ref come from the host. Timestamp is exact
UTC milliseconds. Support refs are sorted unique actual MetaRefs. Metadata's digest is external;
no self-referential hash and no forward link to a future installation.

The small domain anchor is an `extension_manifest` immutable record whose exact content is
`{schema_version:"extension-candidate-anchor-v1",candidate_id,manifest_blob_ref,
service_descriptor_blob_ref,registration_blob_ref,support_documents}`. Support documents is sorted
by `(document_kind,sha256)` and contains exact `{document_kind,blob_ref}` entries. Every `*_ref` in
the anchor is an actual same-vault operational BlobRef. Manifest/descriptor/registration/support
bytes are opaque blobs; their nested MetaRefs are validated by candidate persistence, never
embedded directly into domain content or passed off as EntityRefs. Preserve DomainStore's global
reserved-reference scanner. Anchor actor and policies are actual persisted owner/root refs.

Reuse `DomainStore.put_blob()` before the final registration writer, after initial actual session
validation. That existing method owns its own writer and must not be nested inside the final
transaction. Revalidate current session and capacity inside the final writer, then commit all
anchor/index/association/event/receipt state together. Pre-check known full capacity before
presealing; exact command replay should return before unnecessary sealing. Already registered
unattached blob rows as well as sealed files can remain after failure or revoked-session rejection;
they grant no candidate/execution authority. This64MiB committed unique-content limit is not a
global disk/orphan-retention quota. No silent cleanup or claim of DB/filesystem atomicity.

Return HTTP201 with exactly `{command_id,state:"registered_unqualified",event_cursor,links,
candidate_ref,registration_digest}`; this is the candidate route's explicit success state, not a
new generic command-result state or an installation state. `event_cursor` comes from the same
committed event transaction. `links` is exactly `{self,events}`, with canonical stored values
`/api/v1/extensions/candidates/{candidate_id}` and `/api/v1/events`; the HTTP adapter projects the
configured local base prefix once, as the current core routes do. No new session/hash is required
to render links and no caller-provided URL is used.
`candidate_ref` is `{candidate_id,manifest_digest,service_descriptor_digest}`.
GET|HEAD `/api/v1/extensions/candidates/{candidate_id}` authenticates the same owner and returns
the exact registration receipt plus `registration`, `manifest`, `service_descriptor` and
`documents`. HEAD returns no body. Unknown IDs return404; invalid/stale identity never sees data.
All responses/errors use the supported boundary's no-store/security headers. Names and document
strings are data, never HTML or code.

The fixed contribution declares `extensions.candidates.create` as POST with `extension.manage`
and `extensions.candidates.read` as GET/HEAD with `extension.read`, both `browser_session` only.
These build-owned scope labels are composer metadata, not grants; the concrete service still
requires the actual active owner. Supported startup composes the exact core+candidate descriptor
set once. Historical preview does not gain these routes or use a core-only view of that directory.

Closed candidate error codes are `invalid_input`(400), `unauthenticated`(401), `access_denied`(403),
`not_found`(404), `conflict`(409), `too_large`(413), `capacity`(429), `unavailable`(503). Candidate
route bodies are exactly `{code,message,retryability,affected_refs:[],correlation_id}` using a fixed
safe message, `retryability:"not_retryable"` and a host-created UUID correlation ID. A429 here means
capacity/admission was denied, not a promised timed retry. Existing session/transport boundary errors
retain their existing closed schemas; no raw exception/source path is added.

Same command ID and identical canonical registration input under the same actual owner returns the
exact committed201 receipt, without a second event or candidate. A changed body is409. Revalidate
auth before replay. Cold reopen preserves receipt, frozen bytes and original actor attribution.
An exception before commit rolls back anchor associations/registration/index/event/receipt together.
Previously presealed domain blobs may remain inert as described above; no automatic deletion or
authority from orphan rows/files.

Private schema/index migrations are additive with exact schema/checksum/row/hash/identity and
foreign-key verification, preserving old checksums and the shared no-trigger invariant. Immutable
candidate records use the domain store; a private index is not a second content authority.
Initial capacity is at most1024 committed candidates and64MiB cumulative unique candidate content
per instance. Same-command replay consumes no new capacity. Exceeding either bound returns a closed
capacity error; never eviction, truncation or an incomplete registered candidate. Indexed candidates
are not installations and cannot supply a managed-absence verdict.

Public event `extension.candidate_registered` contains only registered extension-kind/port identity,
candidate count1 and bounded byte count. No source locator, license/SBOM/provenance text, password,
token/hash, raw root or private auth row is placed in event metadata. Exact event and public schema
exports must match runtime parsing. Ordinary release/export permission remains separately scoped.

## Implemented private storage profile (version 1)

The code-owned schema is `app/extensions/candidate_storage.py`. Its five ordered DDL strings
are hashed as `sha256(canonical_json(list(DDL)))`; the version-1 checksum is
`6f5cd856b54e8805dbbd44c07887f503c625d1c3733f22fb86920b83e85c6715`. Exact columns, keys, foreign keys and checks:

```sql
CREATE TABLE extension_candidate_migrations(version INTEGER PRIMARY KEY CHECK(version=1),checksum TEXT NOT NULL);
CREATE TABLE extension_candidate_control(singleton INTEGER PRIMARY KEY CHECK(singleton=1),
        vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id), instance_id TEXT NOT NULL,
        candidate_count INTEGER NOT NULL CHECK(candidate_count BETWEEN 0 AND 1024),
        content_bytes INTEGER NOT NULL CHECK(content_bytes BETWEEN 0 AND 67108864),
        revision INTEGER NOT NULL CHECK(revision>=1), hash TEXT NOT NULL);
CREATE TABLE extension_candidate_index(candidate_id TEXT PRIMARY KEY,
        vault_id TEXT NOT NULL REFERENCES extension_candidate_control(vault_id),
        kind TEXT NOT NULL CHECK(kind='extension_manifest'), version INTEGER NOT NULL CHECK(version=1),
        anchor_digest TEXT NOT NULL, manifest_digest TEXT NOT NULL, descriptor_digest TEXT NOT NULL,
        registration_digest TEXT NOT NULL, actor_ref TEXT NOT NULL, command_id TEXT NOT NULL UNIQUE,
        hash TEXT NOT NULL, FOREIGN KEY(vault_id,kind,candidate_id,version,anchor_digest)
        REFERENCES domain_records(vault_id,kind,id,version,sha256));
CREATE TABLE extension_candidate_commands(command_id TEXT PRIMARY KEY,
        candidate_id TEXT NOT NULL UNIQUE REFERENCES extension_candidate_index(candidate_id),
        namespace TEXT NOT NULL CHECK(namespace='extension-candidate-register-v1'),
        actor_ref TEXT NOT NULL, request_digest TEXT NOT NULL, document_order TEXT NOT NULL,
        receipt TEXT NOT NULL, event_sequence INTEGER NOT NULL CHECK(event_sequence>=1), hash TEXT NOT NULL);
CREATE TABLE extension_candidate_contents(sha256 TEXT PRIMARY KEY,
        vault_id TEXT NOT NULL REFERENCES extension_candidate_control(vault_id),
        purpose TEXT NOT NULL CHECK(purpose='operational'), size INTEGER NOT NULL CHECK(size BETWEEN 1 AND 1048576),
        hash TEXT NOT NULL, FOREIGN KEY(vault_id,purpose,sha256) REFERENCES domain_blobs(vault_id,purpose,sha256));
```

Non-migration row hashes are lowercase SHA-256 of
`canonical_json({"namespace":"extension-candidate-storage-v1","table":suffix,"row":all_columns_except_hash})`.
Only suffixes `control`, `index`, `commands`, `contents` and their exact code-owned columns
are accepted. Hashes detect corruption, not an administrator rewriting all associated digests.
Reopen and operations check exact SQLite SQL shape, migration row, row hashes, foreign keys
and vault/instance binding. No triggers, extra candidate indexes/views/tables are accepted.
Control starts at revision1/count0/bytes0 before bootstrap without creating an owner.
A new registration updates it with `WHERE singleton=1 AND revision=expected_revision`,
requiring exactly one changed row. No eviction, cleanup, installation head or absence verdict.

`actor_ref`, `document_order` and `receipt` contain canonical JSON text. Journal namespace is
`extension-candidate-register-v1`. `request_digest` hashes the complete canonical input object
including command ID and original documents-array order. `document_order` holds only ordered
MetaRefs, used to reconstruct that input from actual anchor-associated blobs. It is not a
second content authority. Registration and anchor support arrays remain sorted by
`(document_kind,sha256)`. The loader verifies all actual blob/ref/digest/actor/header/index
relationships, canonical request/receipt, complete host-derived event envelope and accounting.
Current owner reauthentication precedes read/replay. A later event stream generation preserves
the original receipt cursor; its vault/stream/sequence/filter must still agree with the retained
event and its generation cannot be in the future. Missing/corrupt required event content fails
closed; this slice adds no event-retention exemption.

Committed `content_bytes` sums unique operational blob digests for manifests, descriptors,
registrations and support leaves. Domain envelope/index/SQLite overhead and unattached presealed
rows/files are excluded. Shared bytes count once across candidates and roles; new registration
metadata normally adds bytes. The public `extension.candidate_registered` event requires exactly
`extension_kind`, `port_contract_version`, `candidate_count` (integer1) and `byte_count`
(integer1..1,114,112). Event bytes sum that candidate's logical manifest+descriptor+registration+
support roles before cross-candidate/role deduplication. The bound includes1MiB input plus a
conservative64KiB host-registration allowance. Uploaded strings never enter event metadata.

The distinct generated files in `schemas/v1/extensions/` are `manifest-v2.schema.json`,
`service-descriptor-v1.schema.json`, `candidate-registration-v1.schema.json`,
`candidate-anchor-v1.schema.json` and `candidate-api-v1.schema.json`.
Generator: `python -B -m app.extensions.candidate_schema_exports`.
Refinement keyword objects are recursively closed; local-ref/type/range relationships and Draft
semantics additionally use the existing refinement validator. UTF-8 byte/depth/item/aggregate
limits, canonical URI/host/IP syntax, numeric version ordering, sets/layer positions, derived
paths and cross-document refs/digests/identity/storage/authority are runtime checks. Structural
schemas do not prove these relationships or grant authority. API schemas allow canonical and
one-local-prefix receipt links; only the deployment profile supplies that prefix.

Shared request identity/transaction authentication belongs to `app/domain/request_identity.py`,
strict wire decoding to `app/domain/wire.py`, and event envelopes/cursors/journal/transaction
helpers to `app/domain/public_events.py`. API session/wire/views explicitly re-export the same
objects; SSE remains in API views. The extraction preserves definitions, event DDL/checksum
and wire bytes. The source gate starts from domain/services/runtime/operations/extensions,
follows repository-local import closure (including ordinary helpers and package initializers),
resolves absolute/relative/from-import aliases and terminates cycles without executing modules.
External non-presentation dependencies remain leaves; reachable presentation imports and explicit
dynamic loading APIs, including helper re-exports, fail the check. It is a static architectural
check, not a malicious-Python sandbox.

The supported startup uses the common `app/api/first_party.py` adapter and its frozen
`ApplicationContext` containing actual core components, owner authority and routing inputs.
The build-owned `app/api/first_party_catalog.py` tuple is the complete installed descriptor/factory
set; no request, deployment configuration, operator path or late registration selects it.
Each fixed contribution receives the same context and owns its dependency construction. The
Task10 common-seam extension in deployment-prepare-journal.md§11 additionally passes only a frozen
declared subset of earlier private factory exports to explicitly dependent fixed factories.
No public export is available before complete composition. Candidate
API code constructs the actual registry and publishes `extension-candidates.registry` through
the immutable `first_party_exports` mapping only after all route composition succeeds. Service
identities are frozen in the publication; the durable services themselves retain their normal
mutable state. Factories do not consume an ambient/global service locator. Descriptor/factory
pairing, uniqueness, passive routers, exact installed files, duplicate service exports and
one-shot composition fail closed through the common adapter and unchanged route composer.
Adding a build-installed contribution changes its API module/descriptor and the fixed catalog,
not feature-specific server or route-composition source. Task10's explicitly scoped common resource
ownership/startup-context extension may amend the generic adapter/server cleanup once, without
embedding any deployment type, pin name or factory branch; lower router composition stays unchanged.
Factories may return their own concrete closeable resources to common publication ownership;
this is fixed teardown, not descriptor-defined lifecycle hooks. Missing source configuration is
not positive authority and cannot remove ordinary owner/candidate routes. This common seam does not provide deployment
topology, runtime extension loading, stage authority or whole-T025/T087 completion.

## Missing topology is an execution blocker, not missing metadata

Current `deploy/security/service-ids.json` and Compose have fixed built-in channels only;
`cp-runtime` already belongs to its built-in peer. There is no reserved third-party slot inventory.
Candidate volume/UID/channel names are inert requests, even if they resemble existing names.
Registration creates no stage request, socket reservation, mount, installation, qualification,
runtime profile, binding, secret access or dispatch authority.

Before positive stage preparation, a separate deployment-owned finite topology must establish
instance-bound physical volumes/control mounts/peer identities/channel permissions and applicable
network/resource profiles, with collision/currentness checks and durable reservation CAS.
Operator-created workers can then attach only to already provisioned control-side slots.
No vacancy means external deployment reconfiguration, never runtime post-start mounts or sharing
the built-in pair. Replacement needs distinct coexistence capacity. The static unqualified skeleton
does not establish deployed state.

Source verification, license approval, OCI availability, runtime compatibility, handshake,
qualification, staged receipt handling and the complete browser Settings experience remain separate
mandatory work. Labels such as `built_in` and complete evidence files cannot bypass those gates.
