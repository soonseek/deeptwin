# Extension image identity and lineage value contract

2026-09-16 · first ordinary-tool profile · structural values only.
Authority: FR-031/032, ADR-014, operations§2.1, API§1 extension postconditions and
extension-candidates.md. This contract fixes the small immutable value layer needed by
later actual image measurement and live observation. It grants no installation, trust,
qualification, binding, filesystem access or execution authority. No operator action is performed.

## 1. Selected boundary and existing compatibility

Use acyclic per-platform BuildIdentity and full two-platform LineageEvidence. The identity is
written after the worker binary and before OCI assembly; its embedded input hashes are declared
inputs, not proof that a build executed or was reproduced. The lineage records actual measured
OCI metadata only when produced by a separately qualified external verifier; parsing supplied
bytes does not establish that provenance. A digest of extraction evidence is an audit pointer.

Minimum future artifact verification combines an authenticated allowed image manifest, actual
OCI/fixed-file measurements and independent authenticated live-component postconditions. A fresh
rebuild of every third-party image is not required by this profile. Stronger build-execution and
reproducibility evidence remain distinct optional claims. Required SBOM/license/security review,
actual semantic/runtime qualification and binding gates remain unchanged.

There is no new HTTP route, import kind or candidate rewrite. The lineage is the existing
`provenance` support document; its exact MetaRef is shared by manifest and service descriptor.
Ordinary candidate registration still stores bounded untrusted bytes. Historical candidate,
receipt, prepare, cancellation, database and schema artifacts remain byte-identical.

## 2. Strict bytes, scalar grammar and caps

Inputs to the parsers are exact `bytes`, nonempty strict canonical ADR-008 UTF-8 JSON.
Reject BOM, invalid Unicode/surrogates, duplicate or unknown fields at any level, trailing bytes,
noncanonical whitespace/order/escapes, floats/nonfinite values, null, boolean integers and wrong
containers. Use the existing `parse_json_object`/`WireLimits` and `canonical_json` semantics;
root depth is1, item counts are those defined by the existing wire walker. Errors expose only
`LineageContractError("invalid lineage value")`, never raw input, paths or differing values.

| Record | Byte cap | Max depth | Max items | Max object members | Max string bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| BuildIdentity | 8192 | 4 | 128 | 16 | 256 |
| LineageEvidence | 65536 | 8 | 4096 | 16 | 256 |

All integers are exact Python/JSON integers, never booleans; max wire integer is2^40.
`Hex` is exactly64 lowercase hexadecimal characters. `OciDigest` is `sha256:` followed by Hex.
`Id` is existing candidate `[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?`, full-match, at most128bytes.
`Version` is existing canonical three-part decimal semantic version, at most32bytes, each part
0..2147483647 with no leading zero except zero itself. No prerelease/build suffix in this profile.
Platform order is exactly `linux/amd64`, `linux/arm64`; schema-role order exactly
`config`, `request`, `result`, `error` from `PORT_SCHEMA_SHAPES`.

## 3. Per-platform BuildIdentity

```text
BuildIdentity = {
 schema_version:"extension-build-identity-v1",
 extension_id:Id,extension_version:Version,
 platform:"linux/amd64"|"linux/arm64",port_contract_version:"tool-port-v1",
 inputs:{schema_version:"extension-build-inputs-v1",
         source_bundle:SizedBytes,build_recipe:SizedBytes,dependency_input_set:SizedBytes},
 entrypoint:{sha256:Hex,size_bytes:integer1..16777216},
 port_schemas:[SchemaFile(config),SchemaFile(request),SchemaFile(result),SchemaFile(error)]
}
SizedBytes = {sha256:Hex,size_bytes:integer1..1073741824}
SchemaFile(role) = {role:exact_role,sha256:Hex,size_bytes:integer1..262144}
```

Total declared schema bytes≤1048576. Each embedded identity in a lineage must also satisfy its
own complete BuildIdentity byte/structural limits. Hashes are over complete bytes, without a
self-digest: identity SHA256(exact identity bytes); input identity SHA256(canonical(inputs));
schema-set SHA256(canonical(port_schemas)). These hashes are distinct and are not EntityRefs.
The two platforms may have different entrypoint/input/identity hashes. Never require equality
of platform binaries or identities merely because their extension/version/index matches.

Fixed later measurement paths, not input fields:
`/opt/deeptwin-extension/bin/worker`,
`/opt/deeptwin-extension/identity/build-identity-v1.json`, and
`/opt/deeptwin-extension/ports/tool-port-v1/{config,request,result,error}.schema.json`.
Worker≤16MiB, identity≤8192B, schemas as above. Later actual readers must independently verify
fixed file bytes/metadata/currentness; this pure layer performs no file open or path discovery.

## 4. Full two-platform lineage

```text
LineageEvidence = {
 schema_version:"extension-build-lineage-v1",
 extension_id:Id,extension_version:Version,port_contract_version:"tool-port-v1",
 launch_profile:"extension-fixed-slot-argv-v1",
 index:OciDescriptor(index),
 platforms:[PlatformLineage(linux/amd64),PlatformLineage(linux/arm64)]
}
PlatformLineage = {
 measured_platform_entry:PlatformEntry,
 build_identity:BuildIdentity,
 extraction_evidence_sha256:Hex
}
PlatformEntry = {platform,manifest:OciDescriptor(manifest),config:OciDescriptor(config),
 layers:[{position:integer1..128,media_type:ExactMedia(layer),digest:OciDigest,
          size_bytes:integer1..1099511627776}, ...]}
OciDescriptor(kind) = {media_type:ExactMedia(kind),digest:OciDigest,
                      size_bytes:integer1..1099511627776}
```

ExactMedia(index/manifest/config) are the existing OCI `application/vnd.oci.image.KIND.v1+json`;
layer is `application/vnd.oci.image.layer.v1.tar`, `...tar+gzip` or `...tar+zstd` only.
Reuse the existing candidate descriptor schema definitions without modifying them. Each entry
has1..128 layers with positions exactly1..N; preserve order and repeated digests. No deduplication,
inferred size/media or selected-architecture-only validation. Both entry and embedded identity
platform equal the ordered platform; embedded extension ID/version/port equal the lineage root.
No references to future descriptor/manifest/request/receipt/catalog/installation are permitted.

Derive selected projection, never store a competing field in the lineage:
`{platform,index_digest,manifest_digest,config_digest,ordered_layer_digests}` using the exact
selected measured entry and whole lineage index. Hash is SHA256(canonical(projection)).
Selection rejects every nonexact platform, including absent/unknown/case-folded values.

## 5. Pure interfaces and structural joins

`app/extensions/lineage_contracts.py` exports:

```python
parse_build_identity(raw: bytes) -> BuildIdentity
parse_lineage(raw: bytes) -> LineageEvidence
validate_schema_bytes(identity: BuildIdentity, schema_bytes: tuple[bytes, bytes, bytes, bytes]) -> None
validate_descriptor_lineage(lineage: LineageEvidence, descriptor: ExtensionServiceDescriptor,
                            *, instance_id: str, slot_number: int) -> None
```

Both value classes hold only immutable canonical `content_bytes`; `digest` is its full SHA256;
`as_dict()` returns a detached value. BuildIdentity exposes `input_digest` and `schema_set_digest`.
LineageEvidence exposes `selected_platform(platform)` as the detached projection and
`selected_platform_digest(platform)` as its canonical hash. Construction/returned values are
structural metadata, never issued verification capabilities or a trusted observation token.

Schema-byte validation requires exactly four bytes values in role order, each actual size/hash
equal the declared record. It does not regenerate JSON or treat semantically equivalent schema
bytes as equal. Caller-supplied bytes remain caller-supplied; later actual readers own provenance.

Descriptor join requires exact supported class inputs and valid current structural bytes, exact
extension ID/version/tool port and complete index plus BOTH full PlatformEntries. Its
`evidence.provenance_ref` must equal existing `metadata_ref("provenance", lineage.content_bytes)`.
No partial dictionary match. `instance_id` is exact lowercase32hex, `slot_number` exact integer1..16.
Require command exactly `{protocol_id:"deeptwin-extension-worker-v1",argv:[
"/opt/deeptwin-extension/bin/worker","--instance-id",instance_id,"--slot-number",str(slot_number)]}`.
No leading-zero slot, extra args, config/env fields, shell or semantic flags. This is structural
equality only: it does not prove the actual prepared slot/owner, effective container command or
execution. Those remain concrete service/observer/operator responsibilities. No new broker/route
or topology lease is created, and the absence-only prepare lease is not reused after staging.

## 6. Deterministic exports and verification

`app/extensions/lineage_schema_exports.py` supplies `build_identity_schema()`, `lineage_schema()`
and `exported_schemas()`; export names `build-identity-v1.schema.json`, `build-lineage-v1.schema.json`
under `schemas/v1/extensions/`, $ids `urn:deeptwin:schemas:v1:extensions:` plus basename without
`.schema.json`. Draft2020-12, explicit structural-only authority comment. Runtime adds canonical
byte limits, version bounds, complete order/identity/digest joins; generated files do not imply
authentication or actual measurement. Deterministic formatting: ensure_ascii=False,sort_keys=True,
indent=2, trailing LF. Existing68 schema artifacts must not change.

RED/GREEN tests must cover independent literal/hash vectors, maximum layer count/repetition,
all scalar/shape/cap/order/unknown-field mutations, both-platform size/media/digest tampering,
noncanonical bytes, detached mutation, computed input/schema/projection hashes, exact argv/slot
and MetaRef, actual current four shipped tool schema bytes (result is larger than64KiB), and
export/runtime agreement. Construct real existing candidate descriptors, not a successful
verification callback. Hash vectors are computed independently in tests, not expected from the
method under test. No I/O, clock, network, database, source pin, environment or external job is
performed by runtime parsers. Whole-image measurement/source enrollment/live observation and
atomic successful installation are subsequent separately contracted integrations, not this result.
