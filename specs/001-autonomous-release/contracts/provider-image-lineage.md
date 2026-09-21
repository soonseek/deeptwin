# Provider image lineage and exact descriptor joins

Controller contract, 2026-09-19. This bounded pure-value tranche follows the accepted private
provider worker interface in `private-provider-worker.md`. It does not promote any installation.
Spec authority remains `../spec.md`, especially the extension and model execution boundaries.
Independent preflight is required before implementation.

## Outcome and boundaries

Add the missing provider-specific two-platform image lineage parser and descriptor/schema-byte
join. Downstream staging must be able to distinguish the exact private transformer build from a
tool build without weakening the old tool parsers. These are inert structural declarations:
no OCI fetch/extraction, image build, native observation, signature verification, license/security
scan, deployment, qualification, binding, catalog selection, secret handling or live provider call.
Do not add routes, registration side effects, journal tables, initialization or production activation.

The broader provider staging draft is not this task's requirements. Its continuation/migration/
source-publication/observer/API work will have separate concrete contracts. In particular its
provider-request side-table sketch omitted vault_id and cannot be implemented verbatim.

## Ownership and public interfaces

Create exactly four source/test/schema files; existing files remain byte-identical:

- `app/extensions/provider_lineage.py`: pure parser, immutable value and exact join.
- `app/extensions/provider_lineage_schema_exports.py`: deterministic schema functions.
- `schemas/v2/extensions/provider-build-lineage-v2.schema.json`: exported schema bytes.
- `app/tests/test_provider_lineage.py`: independent fixtures and positive/negative vectors.

Public interfaces:

```python
class ProviderLineageError(ValueError): ...
class ProviderLineage:  # frozen slots, no public constructor
    content_bytes: bytes
    @property
    def digest(self) -> str: ...
    def as_dict(self) -> dict: ...
    def selected_platform(self, platform: str) -> dict: ...
    def selected_platform_digest(self, platform: str) -> str: ...

def parse_provider_lineage(raw: bytes) -> ProviderLineage: ...
def validate_provider_descriptor_lineage(
    lineage: ProviderLineage,
    descriptor: ExtensionServiceDescriptor,
    *,
    instance_id: str,
    slot_number: int,
    schema_bytes: tuple[bytes, bytes, bytes, bytes],
) -> None: ...

def provider_lineage_schema() -> dict: ...
def exported_schemas() -> dict[str, dict]: ...
```

The fixed error message is `invalid provider lineage value`, never untrusted values or raw
validator exceptions. Preserve active process-control exceptions; do not catch BaseException.
Direct construction of ProviderLineage raises TypeError. All public projection/join methods
revalidate stored canonical bytes, including forged, hollow, corrupted and subclass instances;
type identity alone is not validation. Returned mappings/lists are detached.

Consume unchanged public `ExtensionServiceDescriptor.from_mapping`, `metadata_ref`,
`descriptor_schema`, domain canonical JSON/wire primitives, PORT_SCHEMA_SHAPES, and Task33's
`parse_provider_build_identity` / `validate_provider_schema_bytes`. Reuse exported provider
identity schema via provider_build_identity_schema() rather than reproducing its field validation.
Do not call old parse_lineage on
rewritten bytes or fabricate old BuildIdentity/LineageEvidence objects to gain acceptance.

## Exact content schema

Schema document has Draft2020-12, id
`urn:deeptwin:schemas:v2:extensions:provider-build-lineage-v2`, and a comment stating that
structural values grant no authentication, qualification, installation, binding, measurement,
trust or execution authority. Reuse provider_build_identity_schema() exactly once as the local
$defs/provider_identity resource, with position-specific platform restrictions in allOf alongside
local $ref at the two use sites. Never duplicate its $id or field schema, and never retrieve any
remote schema. Each factory returns a fresh detached schema. Export filename is
`provider-build-lineage-v2.schema.json`; UTF8 sorted keys, two-space indent, final newline.

Top-level fields, closed and required:

```text
schema_version = extension-build-lineage-v2
extension_id = same ASCII ID grammar and 128-character bound as existing descriptor
extension_version = canonical major.minor.patch, each component <= 2**31-1, <=32 UTF8 bytes
port_contract_version = provider-port-v1
launch_profile = provider-private-transform-v1
index = unchanged descriptor OCI index object
platforms = exactly two ordered entries: linux/amd64, then linux/arm64
```

Each platform entry has exactly:
`measured_platform_entry`, `build_identity`, `extraction_evidence_sha256`.
Measured entry is the complete existing descriptor OCI platform object, platform fixed for its
position. Preserve manifest/config/layer media types, sha256-prefixed digests, sizes1..2**40,
layers1..128, positions1..N and ordered layers (repeated layer digests are valid).
Build identity is the corresponding exact Task33 provider v2 identity, including
worker_profile=claude-text-transform-v1. Require extension_id/version/port and platform equal
the enclosing lineage. Source/build/dependency inputs and executable hashes may differ across
platforms; do not incorrectly require a shared executable hash or fabricate platform equivalence.
Extraction evidence is lowercase hex64 and is only a declared hash; it proves no extraction.

Parser requires exact bytes, canonical JSON, duplicate/unknown fields refused at every closed
level, valid UTF8, no NaN/infinity/floats/bool-as-int. Before schema validation use WireLimits:
max_bytes65536, max_depth8, max_items4096, max_members16, max_string_bytes256,
max_integer2**40. Existing provider identity's narrower bounds remain enforced.
Size/shape/canonical failures produce only the fixed ProviderLineageError.

selected_platform returns exactly:
```python
{
    "platform": platform,
    "index_digest": value["index"]["digest"],
    "manifest_digest": entry["manifest"]["digest"],
    "config_digest": entry["config"]["digest"],
    "ordered_layer_digests": [layer["digest"] for layer in entry["layers"]],
}
```
Only exact strings linux/amd64 or linux/arm64 are valid. Projection digest is lowercase SHA256
of its canonical JSON; lineage digest is SHA256 of its exact canonical content bytes.

## Join, schema measurements and non-claims

The validator accepts only exact ProviderLineage and exact ExtensionServiceDescriptor types,
reparses their stored canonical bytes, validates instance_id as exact lowercase hex32 and
slot_number as exact int1..16 (not bool). Compare full extension ID/version/port, complete OCI
index object and both ordered measured platform entries against the descriptor. Require
descriptor.evidence.provenance_ref == metadata_ref("provenance", lineage.content_bytes).
The exact descriptor command is:

```python
{
    "protocol_id": "deeptwin-extension-worker-v1",
    "argv": [
        "/opt/deeptwin-extension/bin/worker",
        "--instance-id", instance_id,
        "--slot-number", str(slot_number),
    ],
}
```

schema_bytes must be an exact tuple of four exact bytes in config/request/result/error order.
For BOTH embedded identities call the Task33 provider schema-byte validator: role, declared
length and SHA256 must match each actual supplied byte string. These are the unchanged semantic
provider-port-v1 schema bytes, not private transformation wire schemas. Passing hashes does not
assert the private transformer implements every semantic provider operation.

This join deliberately does not prove descriptor service/socket/UID/mount/resource declarations
equal a retained deployment topology, prove network/secret policy at runtime, or authorize a slot.
Those actual topology/policy joins belong to future staging. Instance/slot here only fix argv;
do not describe this validator's None return as an execution permit or qualified result.
Return None on a fully valid structural join. Revalidation covers mutated raw content and false
subclasses; no caller boolean/callback/trust token bypass.

## Required verification

Use independent synthetic OCI hashes/bytes and literal expected projections/body fields.
Test both platforms with different identities, repeated ordered layer hashes, all supported
existing layer media types and 128-layer boundary while respecting the total wire cap.
Descriptor fixtures may reuse unchanged candidate_payload scaffolding, but provider lineage,
identity and expected output must be explicitly constructed in this test file, not generated by
the production parser under test. Read actual four shipped provider schema files as test inputs.

Genuine RED requires the missing new parser and a concrete valid join/projection assertion.
Then cover:
- Exact type/constructor/immutability/detachment, independent SHA checks; explicitly exercise
  hollow/forged/subclass objects on digest, as_dict, selected_platform, selected_platform_digest
  and the join. Translate dependent provider identity and Candidate errors to the fixed
  ProviderLineageError; do not copy old accessors that trust stored bytes without revalidation.
- Old tool v1 rejected here and new provider v2 rejected by unchanged old tool parser.
- Missing/extra/reordered/duplicate platforms; embedded platform/ID/version/port/profile
  mismatches; nonsequential layers, bad OCI media/digests/size, wrong launch/schema.
- Noncanonical/duplicate/unknown JSON, invalid UTF8, nonfinite/floating/bool/integer/cap violations.
- Independently mutate descriptor ID/version/port/index and each manifest/config/layer field,
  provenance kind/hash/size, argv order/path/extra flags/protocol and expected instance/slot.
- Independently mutate either platform's schema role/order/hash/size and any supplied schema
  bytes/type/count/order; reject embedded tool identities. ProviderBuildIdentity subclass rejection
  belongs to the unchanged Task33 identity validator tests: no Task34 API accepts such an object.
- JSON Schema export parity, Draft2020-12 validity and fresh schema mutation isolation.
- No changes to existing tool/candidate schemas, test oracles or Task33 code; fresh module import
  has no runtime/worker-service/credential/http/SDK imports or side effects.

Cover the new file plus unchanged test_provider_identity.py, test_extension_lineage_contracts.py,
test_extension_candidates.py and test_extension_port_schemas.py. All four filenames exist.
No broad suite/native/live calls.
The controller supplies the accepted Task33 full manifest at explicit dispatch; until then this
task is queued, not authorized. In addition to four product paths, the writer may write only its
evidence report .superpowers/sdd/resumption-plan/task-34-report.md. Record exact RED/GREEN and
covering commands/results, limitations, four final hashes and all out-of-scope manifest equality.
Acceptance requires independent spec and quality review.
