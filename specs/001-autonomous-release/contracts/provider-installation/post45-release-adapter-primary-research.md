# Post45 G1 — primary-source adapter research and finite grammar recommendation

2026-09-20. Advisory research for `post45-installation-verification-draft.md` §11 G1,
`post45-release-evidence-profile-proposal.md` and `post45-release-source-contract-outline.md`.
Only this note is written. Research used upstream documentation/source text and local advisory
documents. No binaries, release archives, database, image, wheels, signing keys, scanner/native
execution, product changes or tests were obtained/run. Task45 R4/full72 acceptance remains the
controller's gate; this note neither accepts it nor changes its frozen scope. Research skill used
by the delegated background researcher; no further delegation was needed.

**Recommendation:** keep the selected upstream versions; define a closed project mapping alongside
the unchanged raw reports; disable Syft's optional package-overlap relationship generation; forbid
SPDX relationships that cause conversion to omit runtime components. Core can then check exact
IDs and byte/path/PURL joins without pretending Grype JSON contains a full scanned inventory.
Controller may approve offline adapter implementation with clearly synthetic schema-valid vectors.
Authentic scanner/cohort samples, original inputs, supplier coverage and measured fit remain
separate real-release gates. This research is a proposed appendix foundation, not a claim that all
external-format branches or a real producer have already been validated.

## 1. Confirmed upstream pins, including source-text observations

The Syft v1.42.3 schema exists and declares `anchore.io/schema/syft/json/16.1.3/document`, using
JSON Schema 2020-12. Grype v0.110.0 exists and its own `go.mod` selects Syft v1.42.3; that Syft
version selects SPDX tools-golang v0.5.7. Thus the proposed pair has no discovered version mismatch.
This verifies source compatibility declarations, not binary provenance or exercised interoperability.
[Syft schema](https://raw.githubusercontent.com/anchore/syft/v1.42.3/schema/json/schema-latest.json),
[Grype dependencies](https://raw.githubusercontent.com/anchore/grype/v0.110.0/go.mod),
[Syft dependencies](https://raw.githubusercontent.com/anchore/syft/v1.42.3/go.mod).

The following SHA-256 values were calculated from retrieved **source text**, not release artifacts.
They make this research's reading baseline reviewable; they are not approved tool/image/config/DB
digests. A later source pin should retain these actual bytes, their acquisition record and the
complete selected dependency closure rather than trust a moving tag alone.

| Tagged source | Observed SHA-256 |
| --- | --- |
| [Syft schema](https://raw.githubusercontent.com/anchore/syft/v1.42.3/schema/json/schema-latest.json) | `0b95379994eab7abaf4c4a3171ffab6f316b9d0c0e6f0a3ff935ba6a1953057f` |
| [Grype document presenter](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/document.go) | `3bb196c265a964c2bd6f7cbb72aedb8be1b7b054e65df76b0a45662709edbab2` |
| [Grype descriptor](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/descriptor.go) | `3c069fc19886c8964a90645ca8298dadf6a63177d63684fb8911ca00a3e001d1` |
| [SPDX 2.3 schema](https://raw.githubusercontent.com/spdx/spdx-spec/v2.3/schemas/spdx-schema.json) | `239208b7ac287b3cf5d9a9af23f9d69863971102a5e1587a27a398b43490b89b` |
| [Syft SPDX conversion](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/common/spdxhelpers/to_syft_model.go) | `126122137d5fc94e2ae50fe46ddea92c280852c98692b09f6f670a98b3d18748` |
| [Grype package conversion](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/pkg/package.go) | `47ef1b96e0d1569a763478f7df680e8142b3318a3526dac2e0088f7bf2e98375` |
| [SPDX tools identifier decoder](https://raw.githubusercontent.com/spdx/tools-golang/v0.5.7/spdx/v2/common/identifier.go) | `7f039c4e24d8bbe4164493680046225dfd047f939028df4474e970dbd96d9a0a` |

SPDX's tagged schema declares draft-07 and ID `http://spdx.org/rdf/terms/2.3`; require the actual
document's `spdxVersion` to equal `SPDX-2.3`. SLSA provenance v1 uses predicate URI
`https://slsa.dev/provenance/v1` within an in-toto Statement v1, with `buildDefinition` and
`runDetails`. Its parameter objects and build type intentionally require producer-specific
semantics. Completeness of dependencies is not automatically guaranteed by the format. The
project's complete-input rule, specific build URI, signature envelope and policy are additional
requirements, not assertions imposed by SLSA. No SLSA assurance level is established here.
[SPDX schema](https://raw.githubusercontent.com/spdx/spdx-spec/v2.3/schemas/spdx-schema.json),
[SLSA provenance v1](https://slsa.dev/spec/v1.1/provenance).

## 2. Native report facts that the adapter must preserve

Syft's top-level fields are `artifacts`, `artifactRelationships`, optional `files`, `source`,
`distro`, `descriptor`, `schema`. Packages have IDs, identity, discovery locations, licenses,
PURL/CPEs and optional typed metadata; relationships link parent and child IDs. File rows have an
ID and location, with optional metadata/digests. Locations distinguish canonical `path`, access
path and layer ID. File digests are optional upstream: requiring SHA-256 coverage is our policy.
The schema contains open/untyped portions; schema validation alone is not a closed admission parser.
[Tagged Syft schema](https://raw.githubusercontent.com/anchore/syft/v1.42.3/schema/json/schema-latest.json).

Image metadata contains `imageID`, `manifestDigest`, `manifest`, `config`, ordered layer metadata,
OS and architecture; the source ID is derived separately. Raw manifest/config fields are Go byte
slices, hence JSON base64 strings. Decode them boundedly, hash their actual bytes, and parse the
OCI manifest/config graph. Compare compressed layer descriptors with the manifest and uncompressed
diff IDs with config/R1; do not identify these two digest domains by assumption. The complete
stereoscope layer-coordinate mapping must be included in the later source/fixture pin.
[Image metadata](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/source/image_metadata.go),
[Image source conversion](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/source/stereoscopesource/image_source.go).

Grype's native document has required `matches`, `source`, `distro`, `descriptor`, and optional
`ignoredMatches`, `alertsByPackage`. `matches` is allocated as an empty array for zero matches.
The presenter iterates findings, not every input package: absent artifact IDs are not receipts that
those packages were scanned. `descriptor` has name/version, optional configuration/DB/timestamp;
configuration and DB are Go `any`, so naming this presenter does not close their nested grammar.
[Document](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/document.go),
[Descriptor](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/descriptor.go).

Each match carries `vulnerability`, `relatedVulnerabilities`, `matchDetails`, `artifact`.
Details include matcher/type, dynamic `searchedBy`/`found` and optional fix. Artifact fields are
ID/name/version/type/locations/language/licenses/CPEs/PURL/upstreams, with optional metadata type
and metadata. Keep every field; do not reduce artifact equality to name/version.
[Match](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/match.go),
[Artifact](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/package.go).

Vulnerability data includes fix/advisories and floating-point risk. Metadata also carries CVSS,
optional EPSS, exploited-vulnerability information and CWEs; severity itself can be omitted when
metadata is missing. Require recognized severity for a policy-bearing finding, including related
vulnerability records under the proposed conservative policy. Preserve finite numbers as parsed
external JSON; never rewrite the raw report into the integer-only project canonical format.
[Vulnerability](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/vulnerability.go),
[Metadata](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/vulnerability_metadata.go).

`alertsByPackage` currently represents distro EOL and contains package, alerts, message and optional
metadata. It is not an exhaustive scanner-error channel. Capture actual stderr/exit/error observations
as well. Native source can be image metadata inherited from an SBOM or a file path; neither is the
hash of the SBOM bytes that Grype consumed. An invocation must bind those exact input bytes.
[Alerts](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/alert.go),
[Source](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/source.go),
[SBOM provider](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/pkg/syft_sbom_provider.go).

## 3. Exact ID conversion and omission hazards

1. **Native Syft:** decoder `OverrideID` preserves `artifacts[].id`; Grype copies that ID. Require
   `image_scan.matches[].artifact.id == image_sbom.artifacts[].id`, with one resolvable package.
   Repeated matches may legitimately reference that same package.
   [Syft decoder](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/syftjson/to_syft_model.go),
   [Grype conversion](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/pkg/package.go).
2. **SPDX:** tools-golang strips one leading `SPDXRef-` on `ElementID` decode; Syft preserves the
   resulting ID and Grype copies it. For an admitted package `SPDXRef-component7`, expected component
   scan ID is `component7`, not a PURL hash and not the full SPDX ID. This is a symbolic mapping
   vector, not an observed scan. IDs are document-scoped; the joined key includes the input SBOM hash.
   [Identifier decoding](https://raw.githubusercontent.com/spdx/tools-golang/v0.5.7/spdx/v2/common/identifier.go),
   [SPDX import](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/common/spdxhelpers/to_syft_model.go).
3. SPDX import removes one described CONTAINER/FILE root into source metadata. It also skips targets
   of `GENERATED_FROM`, ignores some external/unmapped relationships, takes the first PURL external
   reference and can infer distro from the first qualifying PURL. Proposed subset: exactly one
   CONTAINER document root; no other FILE/CONTAINER runtime packages, external-document references,
   `GENERATED_FROM`, `OTHER` or unresolved edges; exactly one PURL per ordinary third-party package;
   every Debian distro qualifier must agree. Keep supplier-source links in the project map instead.
   [Import decisions](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/common/spdxhelpers/to_syft_model.go).
4. Grype's SBOM provider removes some packages linked by `ownership-by-file-overlap` before matching;
   Debian is considered a comprehensive distro feed. Empty `ignoredMatches` does not detect this.
   Syft exposes separate ownership and overlap controls. Select ownership=true, overlap=false,
   reject overlap relationships at intake, and independently reconcile shared files in our component
   map. This changes a cataloging option, not the raw report after generation. If another removal is
   discovered in the pinned path, refuse pending a narrow adapter amendment.
   [Removal rule](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/pkg/package.go),
   [Syft controls](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/relationships.go).

The proposed component map enumerates **all** input packages and expected IDs even if there are
no findings. A pinned conversion projection can be computed from the raw SBOM in core and compared
with invocation observations. That proves consistency with the selected conversion rules, not
independent execution of the external scanner. Real execution remains an attributable producer fact.

## 4. Package/file/PURL joins and class-specific limits

R1's advisory already defines filesystem rows keyed by absolute image path; regular rows carry
SHA-256/size/mode, dependency rows map selected wheel hashes to installed files, and source rows map
source paths to image paths. Reuse those actual fields, not a second file digest authority. Re-enumerate
the accepted source closure; do not freeze the obsolete 44-row list. A package location is discovery
evidence, not a complete ownership list. Join Syft file IDs through ownership relationships and
resolved image coordinates; compare byte hashes with final regular filesystem rows. Symlinks resolve
inside the logical image, and their path/target are not hashed as if they were regular file content.
[Local R1 row definitions](provider-release-producer-before-r1.md#43-dependency-report--actual-verified-wheel-installation-inventory).

| Class | Proposed exact reconciliation | Limit/refusal |
| --- | --- | --- |
| Debian | Status/name/full version including epoch and Debian revision/architecture plus installed file records -> final filesystem rows -> Syft `deb` package and reviewer SPDX package. PURL has type `deb`, namespace `debian`, matching name/version, exact architecture and consistent Debian distro qualifier. Preserve source package/version as `upstream` when present and compare imported upstreams. | Package-manager file checksum claims do not replace independently measured SHA-256. Missing status/list/source-version evidence, contradictory distro or architecture, or a package dropped during conversion refuses. |
| Seven Python distributions | Select exactly the seven actual dependency-report distributions for this platform; compare normalized distribution names, exact versions, selected wheel digest, METADATA/RECORD paths and every installed member's final bytes. PURL type `pypi`; Syft/Grype type `python`. Map each wheel to one reviewed package, permitting multiple explicit discovery locations only when identities and ownership reconcile. | Seven distributions per platform is not eight simultaneously installed wheels. RECORD can omit its own hash/size; use actual R1 bytes there. An arbitrary missing hash is not filled by a guessed digest. No version guessing or remote enrichment. |
| CPython | Base interpreter/library paths and full pinned version -> Syft `binary` package(s), generic Python PURL and exact declared CPE(s) -> reviewed SPDX CPython package(s). Every final native interpreter/library member has explicit containment in the map. | SPDX generic PURL import can yield `UnknownPackage`, not `binary`: admit this only for the exactly identified CPython branch, with versioned approved CPEs and stock matcher enabled. Never accept arbitrary unknown packages or manufacture a PyPI Python identity. |
| Bundled Rust | Exact selected `rpds-py` wheel digest + its native member SHA-256 -> attributable supplier source/build evidence -> each shipped crate's exact name/version/PURL `pkg:cargo/...` -> SPDX crate -> expected Grype `rust-crate` artifact ID. Parent package CONTAINS crate; both map to the containing native member. | A Cargo.lock alone can include dev/build/non-shipped crates and does not prove inclusion in this wheel. No actual crate list, supplier build linkage or cargo-auditable payload was obtained here. Missing linkage is a real release refusal. |
| First-party | Actual source report/launcher/schema image paths and hashes -> SPDX files and an explicitly first-party package plus provenance inputs. | Keep PURL/CPE empty, no fictitious CVE identity. Its origin/license/byte review is mandatory; no scanner-coverage or vulnerability-free claim. Cannot relabel third-party files as first-party. |

Debian source and architecture metadata can be reconstructed from SPDX PURL qualifiers by the
pinned importer; Grype applies PURL-derived upstream/distro enhancement for non-Syft SBOMs.
[SPDX metadata import](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/common/spdxhelpers/to_syft_model.go),
[PURL enhancements](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/pkg/purl_provider.go).
Python RECORD is CSV; paths can be relative, its digest encoding is URL-safe base64 without padding,
and empty hash/size values are permitted by the packaging standard. R1's stricter installation
layout, actual member hashing and refusal rules still govern this profile.
[Installed Python records](https://packaging.python.org/en/latest/specifications/recording-installed-packages/).

Syft's Python binary classifiers explicitly use generic Python PURLs and Python CPE families.
SPDX conversion derives type from PURL type; `generic` is not a recognized package type, and backfill
does not replace a nonempty `UnknownPackage`. Grype's stock matcher performs ecosystem/CPE matching.
This supports the narrow CPython exception above, but not the availability of suitable DB records.
[Classifiers](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/pkg/cataloger/binary/classifiers.go),
[Package types](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/pkg/type.go),
[Backfill](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/internal/backfill.go),
[Stock matcher](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/matcher/stock/matcher.go).
Rust discovery supports Cargo.lock and cargo-auditable binaries; that capability does not establish
their presence in this wheel or complete licenses for its embedded crates.
[Rust capability](https://oss.anchore.com/docs/capabilities/rust/).

## 5. Proposed closed project grammar (not upstream fields)

Everything in this section is a **project recommendation pending controller review**. Reuse the
draft's packet roles/counts and 48 MiB/128-object bounds. No new trust root, registry or packet role
is needed. Put the larger component map in exactly one `origin_evidence` object with the schema
below, referenced by the signed review. Keep the review under 256 KiB and all metadata/origin objects
within the existing shared 4 MiB limit; measured fit is still unknown.

Notation: `H` is lowercase 64-hex SHA-256; `T` is integer epoch milliseconds 0..2^63-1; `S` is
`{sha256:H,size_bytes:integer 1..role_limit}`. `U` is nonempty printable ASCII ≤128 bytes;
`Text` is nonempty UTF-8 ≤4096 bytes; paths reuse R1's validated absolute/relative grammar.
All project objects reject unknown keys, floats, duplicate keys and null unless explicitly allowed.
Arrays are bounded by 8192 entries unless a smaller limit follows, and total raw/canonical caps
always win. Identifier arrays are sorted unique; descriptor arrays use packet order; file rows
sort by path; duplicate package definitions refuse, while duplicate references from findings are
allowed. These are type descriptions, not fabricated positive JSON samples.

For raw external JSON retain the draft's proposed depth64, 262144 total members/items per document
and 1 MiB per decoded string, plus 8 MiB Syft/each Grype, 4 MiB SPDX and 256 KiB provenance/review
caps. Enforce bounds while parsing, including decoded base64 allocations, rather than after an
unbounded materialization. Count object members and array elements consistently in the fixture
contract. Reject duplicate keys, invalid UTF-8, NaN/infinity and numeric overflow. Finite decimals
in CVSS/EPSS/risk/config remain legal external observations; the ordinary float-free domain codec
must not parse these documents. Project canonical records carry references and integer policy
facts. These resource limits are project proposals, not upstream schema guarantees or measured fit.

**Review envelope, exactly:**

```text
{schema_version:"provider-release-review-envelope-v1", key_id:U,
 algorithm:"ed25519", payload:Review, signature:canonical unpadded base64url of 64 bytes}
Review = {schema_version:"provider-release-review-v1",
 review_profile_id:"provider-artifact-review-v1", evidence_policy_sha256:H,
 issued_at_ms:T, reviewer:{id:U,name:Text,authority_basis:[S]},
 subject:{extension_id:existing ExtensionId,extension_version:existing ExtensionVersion,
          platform:"linux/amd64"|"linux/arm64",image_index:S,selected_manifest:S,
          config:S,layers:[S],build_identity_sha256:H,
          source_closure:S,dependency_closure:S,filesystem_inspection:S},
 objects:[{role:existing Role,sha256:H,size_bytes:positive integer}],
 component_map:S,cohort:S,image_invocation:S,component_invocation:S,
 scope:"local-artifact-use-only",origin_review:Decision,license_review:Decision,
 finding_review:{image_scan:S,component_scan:S,rationale:Text}}
Decision = {rationale:Text,evidence:[S]}
```

`authority_basis`/decision evidence are nonempty, ≤128 references to retained `origin_evidence` or
`license_text`; reviewed component conclusions live in the map/SPDX, not pass flags. Subject graph
is compared with retained stage/lineage/R1 bytes; S entries naming original OCI input objects are
identity references, not false claims that all image bytes are uploaded. `objects` must equal the
packet remainder excluding the review itself, including all referenced public support. No unused
object, dangling reference, recursive review reference or duplicate digest role is accepted.

Sign exactly ASCII `deeptwin:provider-release-review:v1\n` followed by the project's existing
canonical UTF-8 bytes of the **whole unsigned envelope** `{schema_version,key_id,algorithm,payload}`.
No trailing newline, no alternative serialization, no DSSE claim. Hash the actual complete canonical
envelope including signature for `release_review`. Reject noncanonical encoding by round trip;
reuse the existing Ed25519 verifier and project canonical codec rather than silently adopt a new
JSON canonicalization or signature implementation. The source's separate allowed-release/key
policy authorizes this signature; the signer field cannot authorize itself.

**Component map, exactly:**

```text
{schema_version:"provider-component-map-v1",image_sbom:S,component_spdx:S,
 filesystem_report:S,dependency_report:S,source_report:S,
 components:[{spdx_id:U,class:"debian"|"python-wheel"|"cpython"|"rust-crate"|"first-party",
   name:U,version:U,purl:string<=2048,cpes:[string<=2048],
   syft_ids:[U],parent_spdx_ids:[U],files:[Path],
   inputs:[{kind:"base"|"wheel"|"source"|"supplier",identity:S,evidence:[S]}],
   license:{concluded:Text,texts:[S],rationale:Text,
     obligations:[{kind:"notice"|"source-offer"|"redistribution"|"local-use",
       disposition:"fulfilled"|"not-applicable",rationale:Text,evidence:[S]}]},
   scanner_scope:"third-party"|"first-party-not-covered"}],
 file_links:[{path:Path,syft_file_ids:[U],spdx_file_id:U,components:[U]}],
 image_projection:[{input_id:U,grype_id:U,type:U,name:U,version:U,purl:string<=2048,
   cpes:[string<=2048],upstreams:[{name:U,version:string<=128}]}],
 component_projection:[same projection row]}
```

`components` is nonempty and keyed by document-scoped SPDX ID. CPEs ≤8/package; parents ≤32;
inputs/evidence/texts ≤128; obligations exactly the four named kinds. Every runtime component has
nonempty files and source/origin evidence, complete license conclusion and text; first-party fields
also use actual declared release identity/version. A bundled crate can lack a Syft ID only with its
exact wheel-member supplier/build linkage. Package-file containment is many-to-many; `components`
and `file_links` must be inverse. File links cover every regular R1 runtime file, including license
and metadata files; classify non-component generated identity/config files through their actual
first-party recipe/source authority, not a blanket exclusion. Directories/symlink aliases remain
R1 filesystem facts rather than SPDX file-content checksum substitutions.

SPDX file SHA256 checksums equal final filesystem row hashes; package archive checksums, where used,
equal selected wheel/material identities, not a hash of installed directory concatenation. Map
package file IDs and relationships explicitly. `license.concluded` equals SPDX `licenseConcluded`;
supplier `licenseDeclared` remains distinct. `NONE`, `NOASSERTION`, unresolved LicenseRef/text,
conflicting claims or unmet obligations refuse. A structurally valid review records an attributable
rights conclusion; it does not establish copyright permission itself.
[SPDX package semantics](https://spdx.github.io/spdx-spec/v2.3/package-information/).

Projection IDs are recomputed under §3, not accepted as arbitrary reviewer aliases. Each non-root
SPDX package appears exactly once in `component_projection`, including first-party with its explicit
non-coverage classification. Each Syft package appears once in `image_projection`; extra packages
outside the five classes refuse. For every reported match compare ID, type, name, version, parsed
PURL, CPEs and upstreams to this derived projection. Locations/licenses/metadata are checked against
the pinned conversion branch separately. Do not expect SPDX import to preserve Syft discovery
locations or rich metadata that SPDX never supplied.

**Cohort and the two scan invocations, exactly:**

```text
Cohort = {schema_version:"provider-scanner-cohort-v1",host_platform:U,
 syft:Tool,grype:Tool,adapter_source:S,producer_recipe:S,
 schema_sources:[{uri:string<=2048,content:S}],
 db:{schema_version:6,archive_identity:S,content_identity:S,built_at_ms:T,
     acquisition:[S],distribution_metadata:S,status:S,providers:S},
 syft_run:Run}
Tool = {name:"syft"|"grype",version:U,archive_identity:S,executable_identity:S,
        acquisition:[S],version_output:S,config_input:S,resolved_config:S}
Run = {invocation_id:U,tool:"syft"|"grype",started_at_ms:T,finished_at_ms:T,
       argv:[string<=4096],environment:[{name:U,value:string<=4096}],
       cwd:string<=4096,inputs:[{name:U,identity:S}],output:S,
       stderr_utf8:string<=65536,exit_code:integer 0..255,
       diagnostics:[{kind:"warning"|"error",message:Text}]}
Invocation = {schema_version:"provider-scanner-invocation-v1",cohort:S,
              scan:"image"|"component",run:Run}
```

Require exactly Syft 1.42.3/Grype 0.110.0, one selected execution-host platform, version/config/schema
bytes and actual acquisition references. Tool archives/executables and DB bytes remain external
identities; their small public acquisition/version/config/status/provider evidence is retained.
`schema_sources` ≤64; argv/environment ≤128; inputs ≤128; diagnostics ≤128; schema URIs are labels,
never runtime fetch destinations. Preserve raw status/provider/config objects as `origin_evidence`
with pinned codec IDs; do not treat them as arbitrary canonical maps. Cohort's `syft_run` avoids
adding a third packet invocation role. Its input is the selected OCI graph and output is image SBOM;
the two invocation objects bind exact image/SPDX bytes and raw scan outputs, respectively. Cohort
does not reference the invocations or review, preserving an acyclic graph. The scan invocation
input list includes the exact DB identity; all times/paths/config observations must agree.

The observer's SLSA statement is a separate raw object with exactly three named SHA-256 subjects
for selected manifest/index/config. Proposed fixed build type is
`urn:deeptwin:build-type:provider-r1-offline-assembly:v1`; external parameters are exactly extension
ID/version, selected platform and recipe/source/dependency input identifiers. Internal parameters
are empty. Resolved dependencies enumerate actual R1 source/base/wheel/launcher/schema/tool inputs
under fixed semantic URI labels with SHA-256. Builder has fixed observer ID, tool versions and
builder-dependency identities; run metadata has invocation ID/start/finish, and byproducts name the
three actual R1 reports. These are project restrictions on SLSA, not upstream mandatory fields.
It records actual operations and cannot retroactively turn an expected report into an observation.

## 6. Selected configuration decisions and remaining nested-format work

The full resolved config bytes must be frozen, not only these selected fields. The minimum proposed
settings are:

| Tool | Mandatory selected behavior | Tagged evidence |
| --- | --- | --- |
| Syft | Explicit local OCI-directory input, selected platform, squashed scope, no exclusions; record complete resolved cataloger list; ownership=true, overlap=false. File metadata selection=all, SHA-256; license content=all. | [Catalog config](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/catalog.go), [file config](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/file.go), [license config](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/license.go) |
| Syft | App update disabled; no remote enrichment; Python remote-license search=false and guess-unpinned-requirements=false. No ambient config selection or environment overlays. | [Python options](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/python.go), [catalog options](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/catalog.go) |
| Grype | Explicit `sbom:` inputs; JSON output; identical resolved config/DB; `only-fixed=false`, `only-notfixed=false`, empty ignores/exclude/VEX/VEX-add/ignore states/fail threshold; `by-cve=false`; no missing-CPE generation; timestamps on. | [Grype options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/grype.go) |
| Grype | DB auto-update=false, require-update-check=false for offline runs, hash validation=true, age validation=true, max age=120h; no external sources/app update. | [DB options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/database.go), [external sources](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/datasources.go) |
| Grype | Python/Rust CPE fallback=false; stock CPE matching=true for CPython; Debian missing epoch strategy=zero, no EOL CPE fallback. All actual provider/feed support must be evidenced. | [Matcher configuration](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/match.go) |

The actual JSON config spelling is not always YAML spelling: examples include JSON
`externalSources`, `ignore-wontfix` and `only-notfixed`. Duration serialization and optional/null
values must follow the exact tagged code and eventual producer sample. A native JSON document
cannot itself prove that ambient configuration/network/keys were absent; those are recorded runner
conditions and reviewed execution boundaries, not cryptographic facts derived from a boolean.

**Finite G1 remainder before calling the appendix fully frozen:** enumerate the selected Syft
metadata union branches and Grype's actual `searchedBy`/`found`, configuration, DB status/provider,
CVSS and package-metadata shapes from their tagged transitive sources; pin the remaining bytes,
including stereoscope layer ID semantics; freeze the chosen SPDX structural subset and config
serialization. Reject unknown branches rather than accept an untyped success dictionary. This is
bounded codec/fixture work and may use explicitly synthetic inputs offline. No claim is made that
this note already exhaustively specifies those dynamic nested upstream fields.

## 7. Refusal vectors and acceptance gates

These are proposed deterministic **synthetic vector categories**, not reports of tests run:

- Right signature but wrong exact packet closure, input SBOM byte digest, manifest/platform/layer
  order, config, review-policy digest or separately provisioned allow entry: refuse.
- Right names but duplicate IDs, duplicate conflicting PURLs, wrong Debian source version/epoch/
  architecture/distro, unresolved file ownership or a hash for a different wheel: refuse.
- Syft ID rewritten during join; component Grype ID still includes `SPDXRef-`; missing/extra
  projected package; ID collision; unmatched reported artifact or altered CPE/upstream: refuse.
- Runtime package hidden by `GENERATED_FROM`, a second root, `OTHER` overlap, external SPDX edge,
  duplicate PURL reference or ignored unsupported conversion metadata: refuse.
- Empty findings with an empty/missing required inventory; bundled crate with no exact wheel/build
  link; CPython CPE absent/unversioned/wrong family; unrelated `UnknownPackage`: refuse.
- Nonempty ignored matches/alerts/errors, nonzero execution code, unsupported matcher/feed,
  excluded path, only-fixed flag, VEX or missing severity: refuse. Warnings require a finite pinned
  non-coverage-affecting code classification; unclassified warning refuses, not all stderr text.
- High/Critical/unknown finding in either scan, including unknown related metadata under the
  selected policy, or absent authorized acceptance of permitted findings: refuse. A known affected
  package remains a finding when no fix exists; lack of a fix neither exempts it nor independently
  rejects a permitted severity that has the required review.
- Missing license text, unresolved LicenseRef, substituted supplier evidence, unmet obligation or
  first-party relabeling: refuse regardless of signature.
- DB build after scan beyond the five-minute tolerance, older than 120h at scan/issuance, scan
  finishing more than 24h before issuance, incomplete provider acquisition/update evidence: refuse.
  Later admission does not reapply scan age relative to today; it checks current provisioned policy.
- Duplicate JSON keys, invalid UTF-8/non-finite numbers, unknown decision-bearing fields, unresolved
  reference, bad canonical signature encoding, per-object/48 MiB/full-graph cap violation: refuse.

The required gates remain deliberately separate:

| Gate | What is still missing / what it permits |
| --- | --- |
| Controller/offline contract gate | Review the recommendations above, remaining finite nested codec shapes, byte domain, signed map role and carrier. Approve the completed appendix and synthetic fixture contract. This can permit ordinary offline parser, evaluator, source/storage/history/B integration without real scanner execution. |
| Offline verification gate | Implement actual parsers/joins with marked synthetic valid and refusal vectors; no mock pass callbacks. Exact source/contract review and Task45 acceptance remain controller-owned. This note ran no tests. |
| Real producer/cohort gate | Obtain authorized authentic scanner binaries/config/version/schema/database/acquisition/status/provider evidence and real unchanged report samples; demonstrate the actual two scans and ID/config/coverage joins. Source version pins alone do not satisfy it. |
| Real input/coverage gate | Actual original base, eight two-platform wheel archives, accepted source closure and fresh R1 input-root finalization; exact-wheel supplier/build/license links for bundled crates and all other native content. The declared CPython 3.12.14 base and wheel availability were not independently obtained or proved by this research. Missing supplier linkage blocks this release, not all offline engineering. |
| Size/authority/distribution gate | Measure actual reports/header/retained graph against all proposed caps; provide legitimate local-use/rights review and independent public trust; actual initializer/control image identities and supported staging/setup/update transport. No measurements, production keys, signatures or release approval exist in this note. |
| Later native qualification/binding | Actual enrollment/runtime/native/permission/provider semantics remain separate; artifact verification grants none of them. T087 is not closed. |

If later authentic output differs from this source-derived grammar, stop at that mismatch and
review a narrow version/config/adapter change. Do not silently upgrade the tools, reconstruct
“observed” samples, widen the allowed ecosystems or approve a signed absence of required originals.

## 8. Bounded follow-up: exact Grype configuration and DB JSON tables

This section closes the configuration/DB field-shape research named in §6. It does not expand the
matcher/CVSS or other upstream format work. The tables are derived from tagged source; they are
not observed scanner output. Source-derived synthetic vectors may implement these tables offline.
The selected values in the right-hand columns are a proposed code-owned subset, not a claim that
an authentic cohort or suitable DB archive has been acquired.

### 8.1 Actual descriptor wrapper and serialization rules

The CLI passes its `*options.Grype` directly to `NewDocument` as configuration, after mutating
ignore rules and clearing registry credentials. It passes `dbInfo(status,vp)` as DB metadata.
Therefore `descriptor.configuration` is the Grype-options object below, not the entire clio
configuration, a `{grype:...}` wrapper, or the config command's YAML. The native presenter uses
`encoding/json.Encoder`, HTML escaping disabled, optional one-space indentation and a final newline.
[CLI presentation call](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/commands/root.go),
[JSON presenter](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/json/presenter.go).

| JSON field | Native type/presence | Proposed admitted form |
| --- | --- | --- |
| `descriptor.name`, `descriptor.version` | Required strings | Exactly `grype`, `0.110.0` |
| `descriptor.configuration` | `any`, omitted for nil; actual CLI supplies nonnil options object | Required, exact §8.2 keys/types/values |
| `descriptor.db` | `any`, omitted for nil; CLI supplies §8.3 object | Required, exact §8.3 |
| `descriptor.timestamp` | String omitted if empty; timestamp-enabled run emits local-zone RFC3339 text | Required nonzero RFC3339 timestamp; compare parsed instant to invocation interval, not literal UTC spelling |

[Descriptor tags](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/descriptor.go),
[Timestamp creation](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/document.go).

Grype's `go.mod` requests Go1.25.8. Under that tagged standard encoder, a named field `SortBy`
tagged `json:",inline"` retains the key **`SortBy`**; `inline` does not flatten it. The anonymous
`DatabaseCommand` embeds its exported fields directly. Nil slices encode `null`; empty allocated
slices encode `[]`, except `omitempty` fields disappear. `time.Duration` is an int64 count of
nanoseconds, so these JSON durations are numbers, not YAML strings such as `120h`.
[Go version pin](https://raw.githubusercontent.com/anchore/grype/v0.110.0/go.mod),
[Go1.25.8 JSON encoder](https://raw.githubusercontent.com/golang/go/go1.25.8/src/encoding/json/encode.go),
[Go1.25.8 time type](https://raw.githubusercontent.com/golang/go/go1.25.8/src/time/time.go).

### 8.2 Closed `descriptor.configuration` object

All keys in the following table are **required**, including zero-valued booleans/strings and
null-valued slices; none of these root fields has `omitempty`. Unknown keys refuse. `E` below
means exactly `[]` or `null`, both representing zero elements; omission is different and refuses.
These two encodings are explicitly admitted rather than normalized by rewriting the raw report.
Every scan must match the same selected resolved-config value after this one empty-slice
equivalence. The native field set and zero/default initialization follow the tagged options struct.
[Grype options and defaults](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/grype.go).

| Exact root key(s) | JSON type | Proposed value; relevant upstream default difference |
| --- | --- | --- |
| `output` | Array of strings or null | Exactly `["json"]`; not the constructor's nil slice |
| `file`, `distro`, `output-template-file`, `ignore-wontfix`, `platform`, `fail-on-severity`, `name`, `default-image-pull-source` | String each | Each `""`; SBOM input source/platform are bound outside these overrides |
| `pretty`, `add-cpes-if-none`, `check-for-app-update`, `only-fixed`, `only-notfixed`, `show-suppressed`, `by-cve` | Boolean each | Each false; upstream app-update default is true |
| `ignore`, `exclude`, `vex-documents`, `vex-add` | Array or null | E; any element refuses without needing an ignored-rule object codec |
| `from` | Array of strings or null | Exactly null: empty input is flattened to nil by `PostLoad`; explicit `sbom:` positional input |
| `match-upstream-kernel-headers` | Boolean | **true**, overriding upstream false; explanation below |
| `timestamp` | Boolean | true, also upstream default |
| `search`, `externalSources`, `match`, `registry`, `SortBy`, `fix-channel`, `alerts`, `db`, `exp`, `dev` | Object each | Exactly the nested shapes/values below |

Nested structures are closed and every listed field is required, except the specifically omitted
registry-auth field. Values in braces describe the selected JSON, not executed results.

| Root field | Complete selected nested object | Source/default notes |
| --- | --- | --- |
| `search` | `{"scope":"squashed","unindexed-archives":false,"indexed-archives":true}` | [Search options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/search.go), [Syft inherited defaults](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/cataloging/archive_search.go). These do not authorize scanning a non-SBOM source. |
| `externalSources` | `{"enable":false,"maven":{"searchUpstreamBySha1":false,"baseUrl":"https://search.maven.org/solrsearch/select","rateLimit":300000000}}` | [Exact JSON spellings](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/datasources.go); nested search defaults true upstream but select false explicitly; rate is 300ms. URL remains inert with external sources disabled. |
| `registry` | `{"insecure-skip-tls-verify":false,"insecure-use-http":false,"ca-cert":""}` | [Registry tags](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/registry.go); `auth` has `omitempty` and is cleared by CLI before output. Its omission is required, but cannot prove no credentials were used. Runner inputs/environment supply that observation. |
| `SortBy` | `{"sort-by":"risk"}` | [Named field](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/grype.go), [sort object](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/sort_by.go), [risk default](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/sort.go). No root `sort-by` field is emitted by this struct. |
| `fix-channel` | `{"redhat-eus":{"apply":"never","versions":">= 8.0"}}` | [Options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/fix_channels.go), [default](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/distro/fix_channel.go) is `auto`; select never for this non-RHEL profile. |
| `alerts` | `{"enable-eol-distro-warnings":true}` | [Alert option/default](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/alerts.go); do not suppress native alert production. |
| `exp` | `{}` | [Empty experimental struct](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/experimental.go) |
| `dev` | `{"db":{"debug":false}}` | [Developer struct](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/grype.go), promoted through [anonymous DatabaseCommand](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/database_command.go) |

`match` has exactly these twelve keys/objects; all subfields are required, including fields
promoted from anonymous `matcherConfig`. This freezes all matcher configuration even though the
admitted component classes remain the earlier four third-party classes plus first-party.
[Complete matcher option types/defaults](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/match.go).

| `match` key(s) | Exact selected object |
| --- | --- |
| `java`, `dotnet`, `javascript`, `python`, `ruby`, `rust`, `hex` | `{"using-cpes":false}` each |
| `jvm`, `stock` | `{"using-cpes":true}` each |
| `golang` | `{"using-cpes":false,"always-use-cpe-for-stdlib":true,"allow-main-module-pseudo-version-comparison":false}` |
| `dpkg` | `{"using-cpes":false,"missing-epoch-strategy":"zero","use-cpes-for-eol":false}` |
| `rpm` | `{"using-cpes":false,"missing-epoch-strategy":"auto","use-cpes-for-eol":false}` |

`db` has exactly the following eleven fields. All duration values below are integer nanoseconds;
do not admit numeric strings or fractional durations. `cache-dir` is the one public, sanitized
absolute release-workspace DB root selected by the cohort, identical across both invocations.
[DB options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/database.go),
[Distribution defaults](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/db/v6/distribution/client.go),
[Installation defaults](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/db/v6/installation/curator.go).

| `db` key | Type | Selected value |
| --- | --- | --- |
| `cache-dir` | String | Cohort's exact absolute DB root; no inference from the receiver's filesystem |
| `update-url` | String | `https://grype.anchore.io/databases` (inert during offline run) |
| `ca-cert` | String | `""` |
| `auto-update` | Boolean | false (upstream scan default true) |
| `validate-by-hash-on-start` | Boolean | true |
| `validate-age` | Boolean | true |
| `max-allowed-built-age` | Integer | `432000000000000` =120h |
| `require-update-check` | Boolean | false |
| `update-available-timeout` | Integer | `30000000000` =30s |
| `update-download-timeout` | Integer | `300000000000` =300s |
| `max-update-check-frequency` | Integer | `7200000000000` =2h |

Its additional Go field `ID` has `json:"-"` and is never emitted. The table is the complete admitted set.
Standalone DB commands use `DefaultDatabaseCommand`, which changes require-update-check to true
and forces hash validation; the scan constructor does not use that override. Record the resolved
configuration/argv for those utility observations independently; never guess utility defaults from
the scan descriptor. [DB command defaults](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/database_command.go).

**Execution-path correction:** upstream false `match-upstream-kernel-headers` appends three built-in
ignore rules, even if they match no package. Therefore the literal no-ignore subset above requires
true. Setting it does not allow otherwise unsupported packages. Any other populated ignore list
refuses. Registry auth is explicitly erased before descriptor emission, so an absent `auth` cannot
be an authentication/secret-absence proof. These source facts amend §6's incomplete option list.
[Actual option mutations](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/commands/root.go).

### 8.3 DB status, scan provider map and standalone provider list

The scan's `descriptor.db` has exactly `{status:Status|null,providers:ProviderMap|null}`. `dbInfo`
allocates `{}` when a provider exists, then attempts `DataProvenance()`; errors are ignored there.
An empty provider map can therefore be a lost metadata observation, not proof of an empty valid
feed set. The admitted subset requires nonnull status and a nonempty map, with all joins below.
[DB wrapper](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/commands/root.go).

`Status` is identical in `descriptor.db.status` and standalone `grype db status -o json` because
both use `ProviderStatus.MarshalJSON`. This method, not the struct's original field tags, adds
`valid` and converts errors to strings. [Custom status/provenance serializers](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/vulnerability/provider.go),
[Status command](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/commands/db_status.go).

| Status field | Exact native JSON behavior | Proposed subset |
| --- | --- | --- |
| `schemaVersion` | Required string, including `""` if unavailable | Exactly `"6.1.4"` for the initial selected cohort; see below |
| `valid` | Required boolean; true iff Go Error is nil | Exactly true; not a substitute for configuration or SHA-256 checks |
| `from` | String omitted when empty | Required `"manual import"` for the selected local archive-import workflow |
| `built` | RFC3339 string omitted when zero time; no fractional-second output | Required nonzero timestamp, equal across status/descriptor/cohort after instant conversion |
| `path` | String omitted when empty | Required `<cache-dir>/6/vulnerability.db`, compared as an observed producer path |
| `error` | Error string omitted if empty | Must be absent; no `{}` error value or null |

Grype's v0.110.0 code constants are model6/revision1/addition4, but status reports the actual DB
description. Requiring exact `6.1.4` is a finite **project subset choice**, not a claim that the
tool rejects every other v6 database or that an exact archive is available. An approved later
cohort may deliberately change it. Local archive import records the source as literal `manual
import`; acquisition-origin URL is proved separately, not taken from `from`.
[Schema constants](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/db/v6/db.go),
[Status/import operations](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/db/v6/installation/curator.go).

There is **no checksum field** in Status. Grype's `import.json` integrity digest uses `xxh64:`;
it is not the wrapper's SHA-256 DB/archive identity. A true `valid` reflects checks under the
actual curator configuration. Keep SHA-256 measurements separately bound by the runner/cohort;
do not invent them from status/provider JSON.
[Import integrity metadata](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/db/v6/import_metadata.go).

| Native view | Complete field shape | Null/omission and exact cross-view join |
| --- | --- | --- |
| Scan `providers` map | `{provider_id:{captured?:string,input?:string}}` | Provider IDs are map keys; zero captured time and empty input string are omitted. Entries may be `{}` upstream. No name/version/processor fields occur here. |
| `db providers -o json` | Array of `{name:string,version:string,processor:string,dateCaptured:string|null,inputDigest:string}` | All five keys always present; nil date pointer emits null. Empty native result is null from the nil slice, not guaranteed `[]`. Time uses Go RFC3339Nano. |
| Cross-view mapping | key=`name`; `captured` corresponds to `dateCaptured`; `input` equals `inputDigest` | Custom map serializer formats whole seconds; compare `captured` to the standalone time with subsecond fraction removed, preserving the instant/offset semantics. Version/processor are checked against the retained standalone list/cohort only. |

[Provider map conversion](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/db/v6/vulnerability_provider.go),
[Map serialization](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/vulnerability/provider.go),
[Standalone list conversion/presenter](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/commands/db_providers.go),
[Go timestamp serialization](https://raw.githubusercontent.com/golang/go/go1.25.8/src/time/time.go).

Proposed closed subset: 1..128 distinct provider names matching `[A-Za-z0-9][A-Za-z0-9._-]{0,127}`;
exact provider-name set equality across the utility list and both scan maps; no missing/null/zero
capture timestamp; nonempty version/processor each ≤256 UTF-8 bytes. Preserve `inputDigest`/`input`
as identical nonempty algorithm-prefixed strings ≤256 bytes, split once at `:` into printable
nonempty algorithm/value. They are provider provenance identifiers, not our SHA-256 `H` type and
not evidence of collision resistance or source authenticity. Upstream explicitly models a
self-describing digest and its source tests include xxh64, so forcing 64-hex SHA-256 here would be
an incompatible invented format. Feed-support policy still checks the required provider IDs for
each component class; extra retained feeds need not be discarded.
[Provider model](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/db/v6/models.go),
[Upstream synthetic provider examples](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/commands/db_providers_test.go).

No view reports a universal last-successful-refresh/failure flag. Do not invent one. Original
distribution/acquisition evidence and attributable feed-completeness review remain separate facts;
DB build age and captured timestamps do not independently prove every upstream feed was current.
This closes the bounded native wrapper/config/status/provider grammar table, while authentic
values/execution remain the real cohort gate already recorded in §7.
