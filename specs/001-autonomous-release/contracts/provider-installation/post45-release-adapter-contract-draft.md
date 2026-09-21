# Post45 release adapter — finite offline contract appendix (DRAFT)

2026-09-20. Design only. This appendix replaces the broad G1 inventory with the selected
decision-bearing subset below. It does not promote a contract, accept Task45, authorize a real
scan/build/key/publication, or establish support for an unmeasured release. Task45 R4 is reported
review-clean. Controller reports full72 finished13 failed/2915 passed/1 warning in3137.65s,
with all773 R4 bytes verified. R5 is active on four test-only paths (eleven old catalog-last
assumptions, one28-versus35 route count, one worker final-identify timing fixture). Task45 is NOT
accepted at that historical draft checkpoint. Controller subsequently accepted Task45 R5 at the
773-path manifest `d6cc1b4460d37b4cc0789c52e6e90b9a002c931f6796c8a51fa251c364b89ba6`;
production bytes did not change since R4. This records acceptance, not a fresh all-green72 result
or permission to dispatch installation work. The preflight-R1 corrections below remain advisory.

**Goal:** implement an actual bounded byte/parser/policy evaluator with explicitly synthetic
positive and refusal fixtures, then connect it to the installation draft's source/store/HTTP/B
vertical. No injected success verifier, expected-result map, or uploaded root is an input.

**Inputs read completely:** `post45-release-adapter-primary-research.md`, SHA-256
`f4934e28d72e61ba324c3105dc15d2bf9bf3d678b0b740feb8d2533f383d4fcf` initially; then the complete
added §8 native Grype tables, revised whole-file SHA-256
`cdd3e401aba193c85159154cc9180501753391d98596c0429fb5fac81ae73feb`; controller carrier preflight,
SHA-256 `ec3388c0ace7f9c55991cebf432c2142be95fe72ca009f5b778083d7c9bc9f6b`; the installation,
amended profile and source-outline drafts. Their canonical/advisory distinctions remain intact.
The primary research's source-text hashes are not scanner binary or production cohort approvals.

## 1. Decision and offline readiness

Select a **projection adapter**, not a general Syft/SPDX/Grype implementation. It validates the
closed project documents, selected native schema branches and all decision-bearing joins below.
It preserves complete raw documents. It does not recalculate CVSS, replay a scanner, infer legal
permission from SPDX, or treat a signature as proof that an observation actually happened.

Alternatives rejected: accepting arbitrary signed pass maps loses evidence; fully emulating every
ecosystem/matcher/configuration grows beyond this release; rejecting every nonempty scan needlessly
turns a low-risk reviewed finding into a new cohort restriction. This subset permits explicitly
reviewed Negligible/Low/Medium findings, never High/Critical/Unknown or missing severity.

**G1 is closed at the draft-contract level for the finite subset below.** The native Grype table
is incorporated exactly from the revised research §8; §6 below fixes Syft's different audit wrapper,
five selected catalogers, inactive configuration boundaries and diff-ID layer mapping. There is no
remaining permission to choose arbitrary native config, guessed producer aliases, or success maps.
The connected slice can be implemented and tested offline after controller design approval and
confirmation of the accepted Task45 base; this document is not that approval. Authentic-output compatibility and actual
release fit remain unproved, with explicit refusal rather than silent widening.

All new fields, limits, refusals and finite subsets here are recommendations; the canonical
requirement is authentic bytes/provenance/license/scan verification with independent trust, separate
from expiring qualification. Controller has selected the dedicated carrier direction, with its
mandatory lease/cancellation conditions. No new trust root or source18 mutation is introduced.
This appendix adds no trust architecture beyond the companion draft's separately provisioned
release-only public source; that proposed release trust is not an already approved real root.

## 2. Common types, parsing and byte domains

`H` = lowercase 64 hexadecimal SHA-256; `T` = integer 0..2^63-1 milliseconds; `U` = printable
ASCII 1..128 bytes; `Text` = UTF-8 1..4096 bytes without NUL; `Path` = existing R1 normalized
absolute image path, <=4096 bytes; `Rel` = existing R1 normalized relative source path. `S` is
exactly `{sha256:H,size_bytes:int}`. For retained references size is 1..the object role cap;
for external original identities it is 1..2^63-1 and does NOT claim that those bytes were uploaded.
UUID key/command identifiers use the source/installation contracts' existing UUID type, not `U`.

Project JSON uses the existing canonical codec unchanged: integer-only, duplicate/unknown keys
refused, no null unless expressly specified, depth32, <=10000 recursive items, <=65536-byte
string and <=1 MiB document, or the smaller role cap. All project arrays have an additional8192
element cap unless a smaller bound follows; these are ceilings, not promises that maximum cardinality
fits the byte/member limits. Review/provenance <=256 KiB; component map <=1 MiB within shared4 MiB
metadata. Never enlarge the domain codec to admit external floats or a larger map.
Canonical recursive-item counting is exactly refs.py: count the root, each container, each scalar,
each dictionary key and each dictionary value as visited; root depth0, every key/value/element
increments depth. Dictionary keys are not free. Aggregate decoded string bytes also stay <=1 MiB.
This is deliberately distinct from the external-parser member/element budget below.

External JSON has separate lexical/structural parsing: strict UTF-8, no BOM/trailing value,
duplicate keys rejected at every depth, depth64, <=262144 object members plus array elements,
<=1 MiB decoded string, numeric token <=128 bytes/64 significant digits, finite decimal exponent
in -308..308. Count one per key-value member and one per array element; nested values add their
own counts. Integers used in decisions must fit T or their narrower bound, and bool is not int.
Lexically check depth/tokens/decoded lengths before ordinary materialization; retain decimal
observations without float overflow/rounding in policy comparisons. No canonical reserialization
becomes an external object's identity. The original received bytes determine SHA-256 and size.

Native sources/config/CVSS use that parser, not ADR008 canonical JSON. Selected raw schema branches
are checked locally; no runtime URI fetch, schema download or external validator service. Embedded
base64 uses canonical RFC4648 padded encoding, strict decode/re-encode equality, and decoded256 KiB
per manifest/config. Decoded bytes count against their parent memory budget; no recursive JSON
decoding except those two explicitly named OCI fields.

The installation carrier retains48 MiB total raw evidence,32 KiB header,128 objects,8 MiB largest
individual report,60-second whole receive deadline. SPDX <=4 MiB; each Syft/Grype <=8 MiB; license
text <=8 MiB aggregate; other metadata <=4 MiB aggregate. Each license object <=8 MiB. Source and
dependency reports keep256 KiB each; filesystem report1 MiB. The existing64 MiB retained graph,
16 MiB blob,4096-node/depth256 limits still apply after all old ancestry is included.

## 3. Closed project documents and acyclic closure

This section selects the research §5 grammar with the following complete forms. No unlisted
extension keys are accepted. Descriptor lists follow carrier order; identity sets sort by the
named primary key and reject duplicates. A same-byte retained object occurs only once in the
carrier, with one role; multiple references may point to it.

```text
Envelope = {schema_version:"provider-release-review-envelope-v1",key_id:UUID,
 algorithm:"ed25519",payload:Review,signature:unpadded-base64url-64-bytes}
Review = {schema_version:"provider-release-review-v1",
 review_profile_id:"provider-artifact-review-v1",evidence_policy_sha256:H,issued_at_ms:T,
 reviewer:{id:U,name:Text,authority_basis:[S]},
 subject:{extension_id:ExtensionId,extension_version:ExtensionVersion,
   platform:"linux/amd64"|"linux/arm64",image_index:S,selected_manifest:S,config:S,
   layers:[S],build_identity_sha256:H,source_closure:S,dependency_closure:S,
   filesystem_inspection:S},
 objects:[{role:Role,sha256:H,size_bytes:int}],provenance:S,component_map:S,cohort:S,
 image_invocation:S,component_invocation:S,scope:"local-artifact-use-only",
 origin_review:Decision,license_review:Decision,
 finding_review:{image_scan:S,component_scan:S,rationale:Text,accepted:[Finding]}}
Decision = {rationale:Text,evidence:[S]}
Finding = {scan:"image"|"component",match_index:int0..8191,
           vulnerability_id:U,artifact_id:U,severity:"Negligible"|"Low"|"Medium"}
```

`Finding` is an explicit proposed addition to the research grammar: one row per admitted match,
ordered(scan image before component,match_index); no omitted/extra acceptance. Related records must
also have an allowed severity but do not get independent deduplication/waivers. A rationale covers
the exact scan bytes, not a future scan. Empty scans require `accepted:[]`, not a fabricated result.
Authority/decision evidence lists are nonempty <=128 and resolve to retained license/origin objects.
Review.evidence_policy_sha256 is exactly the SHA-256 of the closed code-owned canonical policy
bytes in the installation draft §3.1. Renderer, initializer and evaluator use that same value;
neither an uploaded hash nor this Markdown file defines its byte domain.

Sign ASCII `deeptwin:provider-release-review:v1\n` plus canonical bytes of the unsigned envelope
containing exactly schema_version,key_id,algorithm,payload. Verify with the existing Ed25519 code;
no trailing newline/DSSE/alternate serialization. The hash in trusted allowed_releases is of the
complete canonical envelope including signature. Current provisioned trust authorizes the key,
role, issuance window and exact release; the envelope never authorizes its own key.

```text
Map = {schema_version:"provider-component-map-v1",image_sbom:S,component_spdx:S,
 filesystem_report:S,dependency_report:S,source_report:S,components:[Component],
 file_links:[FileLink],image_projection:[Projection],component_projection:[Projection]}
Component = {spdx_id:U,class:"debian"|"python-wheel"|"cpython"|"rust-crate"|"first-party",
 name:U,version:U,purl:string0..2048,cpes:[string1..2048],syft_ids:[U],
 parent_spdx_ids:[U],files:[Path],inputs:[Input],license:License,
 scanner_scope:"third-party"|"first-party-not-covered"}
Input = {kind:"base"|"wheel"|"source"|"supplier",identity:S,evidence:[S]}
License = {concluded:Text,texts:[S],rationale:Text,obligations:[Obligation]}
Obligation = {kind:"notice"|"source-offer"|"redistribution"|"local-use",
 disposition:"fulfilled"|"not-applicable",rationale:Text,evidence:[S]}
FileLink = {path:Path,syft_file_ids:[U],spdx_file_id:U,components:[U]}
Projection = {input_id:U,grype_id:U,type:U,name:U,version:U,purl:string0..2048,
 cpes:[string1..2048],upstreams:[{name:U,version:string0..128}]}
```

Components/files are nonempty; CPEs<=8, parents<=32, inputs/license texts/evidence<=128. Exactly
four obligation kinds occur in listed order. Every disposition has rationale and nonempty retained
evidence, including why an obligation does not apply. Each component has nonempty files/inputs/
license texts. Third-party requires a PURL; first-party requires empty PURL/CPEs and the distinct
non-covered scope. No class is inferred just because an author selected its label.

```text
Cohort = {schema_version:"provider-scanner-cohort-v1",host_platform:"linux/amd64"|"linux/arm64",
 syft:Tool,grype:Tool,adapter_source:S,producer_recipe:S,
 schema_sources:[{uri:string1..2048,content:S}],
 db:{schema_version:6,archive_identity:S,content_identity:S,built_at_ms:T,
     acquisition:[S],distribution_metadata:S,status:S,providers:S},syft_run:Run}
Tool = {name:"syft"|"grype",version:U,archive_identity:S,executable_identity:S,
 acquisition:[S],version_output:S,config_input:S,resolved_config:S}
Run = {invocation_id:U,tool:"syft"|"grype",started_at_ms:T,finished_at_ms:T,
 argv:[string1..4096],environment:[{name:U,value:string0..4096}],cwd:string1..4096,
 inputs:[{name:U,identity:S}],output:S,stderr_utf8:string0..65536,
 exit_code:int0..255,diagnostics:[{kind:"warning"|"error",message:Text}]}
Invocation = {schema_version:"provider-scanner-invocation-v1",cohort:S,
 scan:"image"|"component",run:Run}
```

Tool versions are exactly Syft1.42.3 and Grype0.110.0. Source entries<=64; argv/environment/inputs/
diagnostics<=128. Two invocations only: image consumes image_sbom; component consumes SPDX. Each
has input identities `sbom,db,config,executable` exactly; Syft run inputs are `image_index,
selected_manifest,config,executable` exactly. Tool config/executable and DB identities equal cohort.
All runs require exit0 and diagnostics empty in this first subset; stderr may contain only empty
or whitespace bytes. This deliberately stricter warning policy may refuse authentic output and
must then be amended explicitly, never rewritten into a clean observation. Paths/argv come from
the selected recipe, not user-selected executable paths. Version output is retained factual evidence;
its string alone cannot authenticate a binary.

All support objects use existing `origin_evidence`, never a new carrier role. A support reference's
expected parser is determined by its referring field, not a caller-chosen parser name. Ambiguous
reuse across incompatible parsers refuses. Plain supplier/acquisition/authority prose has strict
UTF-8 <=65536 bytes and is an attributable statement, not a machine pass flag. Raw native status,
provider and config objects remain original JSON. License texts are strict UTF-8, nonempty and
unmodified; their sizes may exceed the per-JSON-string cap because they are separate raw blobs.

Reference graph order: leaves (raw reports/SPDX/config/schema/version/acquisition/license/supplier
documents) -> map and cohort -> two invocations -> review. Provenance references only original
input identities and three R1 report identities, not review/map/cohort/invocations. Map points to
reports/support, not cohort or review. Cohort's Syft output points to the SBOM, never an invocation.
Review's objects list equals exactly all other carrier descriptors. Every object must be reachable
from a typed review field by these reference edges, not merely listed in objects; no orphan, cycle,
same-digest role alias, external URI dereference or reference back to review is admitted.
External original identities are only the explicitly typed image/input/tool/DB archive identities;
all other S values must resolve to retained bytes. A purported missing retained input cannot be
reclassified as an external identity to escape closure.

## 4. Native inventory and SPDX selected branches

Source-derived versions and ID conversion are documented in the research. Native Syft keeps its
package IDs; SPDX import strips one `SPDXRef-`. Our own map must equal the core-derived projection;
it is not an author-controlled alias table. See the pinned [identifier decoder](https://raw.githubusercontent.com/spdx/tools-golang/v0.5.7/spdx/v2/common/identifier.go)
and [SPDX import](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/common/spdxhelpers/to_syft_model.go).

Syft accepted top-level shape is the tagged Document with required nonempty artifacts/files,
relationships, source, distro, descriptor and schema. Schema version is16.1.3; descriptor identifies
syft1.42.3. Validate the selected definitions `Document,Package,File,Location,Coordinates,Digest,
Relationship,Source,Descriptor` against their literal tagged schema structure; no runtime schema
loading. Package metadata branches selected are only DpkgDbEntry, PythonPackage, BinarySignature;
other branches refuse. These are exact inspected `$defs` selectors. Metadata discriminators are
exactly `dpkg-db-entry`, `python-package`, `binary-signature`, respectively; legacy aliases refuse.
Only source-defined scalar/array fields reachable through those selected schema definitions are
admitted, with unknown keys rejected recursively. Open native `metadata` is not a success escape.
Dpkg source/
version/architecture are decision fields, Python installed identity/files are decision fields,
binary classifier identity/location is decision-bearing. Additional schema-defined descriptive
metadata is retained but never changes class/coverage/identity. Unknown keys at those boundaries
refuse, including where upstream's schema is open. [Syft schema](https://raw.githubusercontent.com/anchore/syft/v1.42.3/schema/json/schema-latest.json).

Image source requires imageID/config digest, selected manifest digest, decoded config/manifest bytes,
OS/architecture and layers matching actual staged R1 OCI identity. Compressed layer digests/sizes
come from decoded manifest descriptors, not the native layers array. Native layer digest and file
location layerID are uncompressed diff IDs under the exact §6 rule. Native layer size is a member
size sum, not compressed descriptor size. No permissive equality to either digest domain is allowed.
File SHA-256/size/path matches independently measured R1 rows. Discovery location is not ownership.

SPDX is raw JSON meeting2.3 plus this closed project subset:

| Object | Allowed fields (all required unless `?`) and selected behavior |
| --- | --- |
| Document | spdxVersion=`SPDX-2.3`,dataLicense=`CC0-1.0`,SPDXID=`SPDXRef-DOCUMENT`,name,documentNamespace,creationInfo,packages,files,relationships,hasExtractedLicensingInfos. No external document refs/annotations/snippets/reviews. |
| creationInfo | creators[1..8 strings],created RFC3339UTC seconds. Creator is `Person: ` or `Organization: ` attributable reviewer, optional `Tool: ` producer. No implicit creator authority. |
| Package | SPDXID,name,versionInfo,downloadLocation,filesAnalyzed=false,licenseConcluded,licenseDeclared,copyrightText,primaryPackagePurpose,externalRefs,checksums?,supplier?,originator?. No packageVerificationCode or hidden nested files. |
| File | SPDXID,fileName,checksums exactly one SHA256,licenseConcluded,licenseInfoInFiles[1..32],copyrightText. File name is the normalized absolute image Path. |
| Checksum | algorithm=`SHA256`,checksumValue=H. |
| ExternalRef | referenceCategory=`PACKAGE-MANAGER`,referenceType=`purl`,referenceLocator=PURL; or category=`SECURITY`,type=`cpe23Type`,locator=CPE. No comment or alternate refs. |
| Relationship | spdxElementId,relationshipType,relatedSpdxElement; type only DESCRIBES or CONTAINS. No comments/external IDs. |
| ExtractedLicense | licenseId=`LicenseRef-` + U suffix,extractedText nonempty<=1 MiB,name optional. Its exact UTF-8 text hash/size must equal one retained license_text. |

This is a selected restriction, not all valid SPDX. `filesAnalyzed=false` is intentional: ownership
and checksums are explicitly verified through file rows/map, without inventing SPDX's SHA1 package
verification value. Exactly one CONTAINER root is described by the document and represents the
selected manifest; its one SHA256 checksum equals that manifest. All other packages are LIBRARY
or APPLICATION (CPython APPLICATION); root version/name equal release identity. Root CONTAINS each
top-level component; component nesting and file CONTAINS edges equal the map, form a DAG, and reach
every file/package. No GENERATED_FROM/OTHER edge can hide a package during import. Source/supplier
relationships use the map's typed original references. [SPDX2.3 schema](https://raw.githubusercontent.com/spdx/spdx-spec/v2.3/schemas/spdx-schema.json).

License expressions are deliberately a small grammar: one SPDX identifier or local LicenseRef;
or a parenthesized binary AND/OR expression; optional `WITH` exception only for an SPDX identifier.
Whitespace is a single ASCII space; expression length<=4096; depth<=16. The finite code-owned SPDX
identifier set is MIT,Apache-2.0,BSD-2-Clause,BSD-3-Clause,ISC,Python-2.0,MPL-2.0,Zlib,Unicode-3.0,
GPL-2.0-only,GPL-2.0-or-later,GPL-3.0-only,GPL-3.0-or-later,LGPL-2.1-only,LGPL-2.1-or-later,
LGPL-3.0-only,LGPL-3.0-or-later. Exceptions: Classpath-exception-2.0,GCC-exception-3.1,LLVM-exception.
Other IDs refuse or use truthful local LicenseRefs with full extracted text. This is a parser
subset, not an approval of any license's suitability; LicenseRefs resolve locally.
No `NONE`, `NOASSERTION`, external DocumentRef, arbitrary prose-as-expression or unresolved reference.
The reviewer selects an applicable branch where OR is used by supplying a concluded expression
with no OR; core verifies it is one syntactic permitted selection from declared expression, with
all AND terms preserved. SPDX concluded equals map concluded exactly. Declared supplier evidence
may differ only with an explicit retained authority/rights rationale; core does not establish the
truth or legal sufficiency of that rationale. A real rights holder/reviewer remains responsible.
SPDX identifiers are exactly `SPDXRef-` followed by1..120 ASCII letters/digits/dot/hyphen;
local license identifiers use `LicenseRef-` with the same suffix grammar. External DocumentRefs
and whitespace-bearing IDs refuse, even though the common U type would otherwise admit them.

Class joins and fixed projection:

- Debian: nonempty actual installed status, complete final file rows, full version/epoch/architecture,
  consistent Debian distro PURL; source upstream from native metadata or the single PURL upstream
  qualifier. Name/version/type=`deb`; retain upstream even when equal to binary name if pinned native
  metadata does so. No lossy normalization of epoch/revision.
- Python: exactly the seven selected dependency-report distributions for this platform, exact
  versions/wheel hashes/installed members; Python name normalization is lowercase and runs of
  `[-_.]` -> `-`. Native type=`python`; PURL type=`pypi`. RECORD omissions never replace R1 hashes.
- CPython: actual interpreter/native/library file containment from base evidence, exact version;
  native type=`binary`; SPDX-import type=`UnknownPackage` only for this exact class; generic/python
  PURL and explicit versioned Python CPEs. No arbitrary UnknownPackage admission.
- Rust: each shipped crate has cargo PURL and exact wheel/native-member/supplier-build linkage;
  SPDX type projects to `rust-crate`. Native Syft IDs may be empty for Rust and first-party only. A Cargo.lock
  without linkage is not evidence of shipped inclusion. No inferred crate list.
- First-party: only actual source-report/launcher/schema/recipe-generated bytes can classify here;
  no PURL/CPE, SPDX import UnknownPackage, no CVE coverage claim. A third-party input in its ancestry
  cannot be relabeled first-party. Legal/origin review remains mandatory.

PURL parsing is restricted to deb/debian,pypi,cargo,generic/python: exact version, no fragment,
no duplicate qualifier, UTF-8 percent decode once then canonical re-encode; only Debian qualifiers
arch,distro,upstream are allowed. Other classes have no qualifiers. All qualifier sets and versions
are checked against actual R1/map/native identities. For CPython admit exactly two CPE2.3 strings:
part a, vendor `python` or `python_software_foundation`, product python, exact component version,
remaining seven fields `*`; both occur once. Other native component CPEs are bounded ASCII strings
retained and compared exactly through projection, but do not select coverage (their CPE fallback
is disabled); first-party has none. No decoder collapses distinct escaping into one identity.
This is not an assertion that these feeds cover every CPython vulnerability.

Each Syft artifact and each non-root SPDX package has exactly one projection row, keyed by raw
input ID. First-party with no native Syft artifact exists only in component_projection. Native
grype_id=input_id; SPDX grype_id removes exactly one prefix. Name/version/PURL/CPE/upstream/type
are derived, never trusted from the map. Parent/file inverse sets must agree, cover every regular
R1 filesystem path including metadata/license/config and have no extra path. Symlinks/directories
remain R1 objects, not fake content-checksum files. Missing native discovery is not silently filled
by the signed map except the explicit Rust/first-party branches with real supporting origins.

## 5. Grype projection: every finding counts; diagnostics cannot authorize

Require native top-level matches,source,distro,descriptor; optional ignoredMatches/alertsByPackage
may be absent or empty arrays only. Null does not mean an empty array. descriptor requires name
grype,version0.110.0,timestamp,configuration,db. Source's native value remains bounded/retained;
the invocation's exact input hash is the SBOM join, not a path/name from source. The producer emits
an empty matches array, not an all-packages inventory. [Presenter](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/document.go).

Each match has the exact native boundary keys vulnerability,relatedVulnerabilities,matchDetails,
artifact. Every artifact's id/name/version/type/PURL/CPE/upstreams equals its core projection.
Artifact has exactly id,name,version,type,locations,language,licenses,cpes,purl,upstreams; no unknown
keys. Upstream is exactly {name:string,version?:string}; absent version projects to the map's empty
version string, not a new identity. Native image language equals its Syft artifact language;
SPDX-import language is python for pypi, rust for cargo and empty for deb/generic/first-party.
Native image locations equal the source artifact's distinct complete location objects as an
unordered set; each was already validated against R1. SPDX-import locations are exactly null:
the selected importer does not populate package LocationSet, and nil ToSlice serializes as null.
SPDX file ownership does not become discovery location. licenses is a required string array;
its native values are retained explanatory observations, not rights approval and not inputs to
SPDX/map license acceptance. Native normalization/LicenseRef-prefix removal therefore cannot alter
the explicit signed/SPDX legal decision. CPE/PURL/type/version identity checks still apply exactly.
For the selected Debian/Python/binary/Rust/unknown classes,
Grype package metadata must be absent (its converter supplies additional metadata for other
ecosystems); if authentic output contradicts this selected branch, refuse and review, do not drop
metadata. Debian upstreams follow its Dpkg conversion. [Package presenter](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/package.go),
[package conversion](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/pkg/package.go).
[LocationSet nil behavior](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/file/location_set.go),
[SPDX package construction](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/format/common/spdxhelpers/to_syft_model.go),
[language mapping](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/pkg/language.go).

Vulnerability/related metadata must have nonempty id and exact severity in Negligible/Low/Medium/
High/Critical/Unknown. Missing/Unknown/High/Critical refuses, irrespective of fix availability.
No deduplication, alias selection, patched-state shortcut or ignored-VEX waiver removes a row.
Every admitted match has its exact Finding acceptance in the signed review. CVSS, EPSS, risk,
descriptions, URLs, advisory/fix metadata remain finite bounded native observations, not inputs to
severity reduction or a zero-risk claim. Validate their tagged structural types; no need to
recompute vector mathematics. [Vulnerability metadata](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/vulnerability_metadata.go).

matchDetails must be a nonempty array of native detail objects; matcher is exactly dpkg-matcher,
python-matcher,rust-matcher or stock-matcher, and type is exact-direct-match,exact-indirect-match
or cpe-match. Dpkg/Python/Rust map to their corresponding component class; stock is only CPython
or first-party UnknownPackage (first-party has no CPE, so any positive stock match refuses).
Only stock permits cpe-match under this configuration. searchedBy/found payloads are bounded
native JSON used only to explain a finding. They cannot suppress it, establish scanned inventory,
prove a package's safety, or select source/component identity. Unknown native detail keys refuse;
unknown diagnostic fields inside searchedBy/found are retained as opaque observations because no
authorization decision reads them. Unknown matcher names refuse as unsupported execution scope.
This precise boundary avoids a complete matcher emulator while never turning an opaque field into
positive authority. The exact detail keys are type,matcher,searchedBy,found and optional
fix={suggestedVersion:string}; fix null refuses. [Match model](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/match.go),
[matcher names](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/match/matcher_type.go),
[detail types](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/match/type.go).

The following closed diagnostic structures make the selected nonempty finding fixture executable.
Strings use the raw string cap; arrays use the raw aggregate cap; numbers are finite decimals.
`?` means absent or the named type, never implicit null; no unknown keys. Metadata has required
id,dataSource,severity,urls:string[],cvss:Cvss[]; optional namespace,description:string and
knownExploited:KE[],epss:EPSS[],cwes:CWE[]. Vulnerability adds required fix,advisories,risk:number;
relatedVulnerabilities are Metadata only. Fix={versions:string[],state:string,available?:FA[]};
FA={version:string,date:string,kind?:string}; Advisory={id:string,link:string}.
Cvss={source?:string,type?:string,version:string,vector:string,metrics:Metrics,vendorMetadata:rawJSON};
Metrics={baseScore:number,exploitabilityScore?:number,impactScore?:number}.
KE={cve:string,knownRansomwareCampaignUse:string,vendorProject?:string,product?:string,
dateAdded?:string,requiredAction?:string,dueDate?:string,notes?:string,urls?:string[],cwes?:string[]}.
EPSS={cve:string,epss:number,percentile:number,date:string};
CWE={cve:string,cwe?:string,source?:string,type?:string}. vendorMetadata is bounded raw JSON and
never authorizes, reduces severity, changes identity or omits a finding. Arbitrary keys are allowed
only inside that explicitly opaque observation and searchedBy/found. URLs are never fetched.
[Native vulnerability/fix](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/vulnerability.go),
[native CVSS](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/cvss.go).

## 6. Closed native configuration, database and layer tables

Actual CLI configuration input and fully resolved native configuration are both retained; scans
must use one exact Grype pair. Byte identities join Tool,Run and report descriptor. Native embedded
resolved objects compare as parsed structural values (not by hashing reserialized floats).
The complete config object cannot be an arbitrary signed map. Required decision projection:

| Source branch | Mandatory selected values |
| --- | --- |
| Syft catalog | squashed scope; local oci-dir; selected platform; exclude/enrich empty; no user source-name/version/supplier alias; binary-overlap exclusion false; ownership true and ownership-overlap false; complete installed-package catalogers for Debian/Python/CPython plus file digest/ownership; no selection subtraction. |
| Syft files/licenses/Python | metadata selection all, SHA256 digest; license content all; no remote license search or unpinned guessing; no network/ambient config; app update false. |
| Grype filtering | SBOM only; output JSON; only-fixed/only-notfixed/by-cve false; excludes/ignores/VEX/VEX-add/ignore-states empty; fail threshold empty; no generated CPEs; timestamp true; no distro override; match-upstream-kernel-headers=true to prevent implicit default ignore insertion. |
| Grype DB | one hydrated v6 DB identity; auto-update false, require-update-check false, validate-by-hash-on-start true, validate-age true, max-built-age120h. |
| Grype matching | Python/Rust using-cpes false, stock true; Debian epoch strategy zero, EOL-CPE fallback false; external sources disabled; no app update. |

These settings are project selections based on tagged [catalog](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/catalog.go),
[file](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/file.go),
[Python](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/python.go),
[relationships](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/options/relationships.go),
[Grype options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/grype.go),
[DB options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/database.go)
and [match options](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/match.go).

### 6.1 Grype and DB: exact adopted source table

The complete §8.1–8.3 tables of `post45-release-adapter-primary-research.md`, revised hash
`cdd3e401aba193c85159154cc9180501753391d98596c0429fb5fac81ae73feb`, are incorporated as the exact
admitted field/type/value grammar, not background suggestions. No “derive suitable defaults” task
remains. Only substitute the fixed producer paths below. Its33 required config root keys, twelve
matcher objects, eleven DB keys and explicit empty-array/null equivalences are exhaustive.
`SortBy` is a capitalized nested object, native durations are integer nanoseconds, `from` is null,
and `match-upstream-kernel-headers` is true; registry auth is erased by upstream and its absence
does not prove a credential-free runner. All other fields/variants refuse.

Producer paths are fixed: cwd=`/work`, OCI=`/inputs/image`, SBOMs=`/inputs/image.syft.json` and
`/inputs/components.spdx.json`, configs=`/config/syft.json`,`/config/grype.json`, DB root=`/inputs/db`,
tools=`/tools/syft`,`/tools/grype`. These are observed producer paths, not paths opened by core.
Grype Run argv is exactly `/tools/grype`, `sbom:<selected SBOM path>`, `--config`,
`/config/grype.json`, `--output`, `json`. Environment is exactly LANG=C.UTF-8 and LC_ALL=C.UTF-8,
in name order; no ambient scanner config/registry/provider credentials. Isolation is an attributable
runner observation, not something JSON can prove. Fixed config path/DB identity ties both runs.

Grype config_input is JSON decoded through fangs/Viper using **mapstructure** tags, not YAML tags.
It uses exactly the adopted resolved config values but input spellings:
`externalSources` -> `external-sources`, nested
`searchUpstreamBySha1/baseUrl/rateLimit` -> `search-maven-upstream/base-url/rate-limit`,
omit `ignore-wontfix` entirely (and do not supply `ignore-states`),
`SortBy:{sort-by:"risk"}` -> root `sort-by:"risk"`;
durations use their exact string forms `300ms,120h,30s,300s,2h` at the corresponding pointers;
all E slice positions use[] and from=[]; registry.auth is omitted. All other keys/types are identical.
The raw input bytes are retained and structurally checked; its transport whitespace is not authority.
The omitted ignore-state input intentionally uses the tagged constructor's zero-value empty string;
both scan descriptors MUST still contain native `ignore-wontfix:""`. This avoids depending on the
upstream mismatch between YAML's ignore-states and JSON/mapstructure's ignore-wontfix spelling.
There is no permission for a hidden filter: extra CLI/env overrides refuse, native ignored/ignore
lists must be empty, and any nonempty resolved ignore-state value refuses.
Thus the input pointer is `external-sources.maven.search-maven-upstream=false`; the emitted
descriptor pointer remains `externalSources.maven.searchUpstreamBySha1=false`. The YAML spelling
`search-upstream` is not admitted. fangs uses Viper Unmarshal rather than UnmarshalExact, so an
unknown alias can otherwise be silently ignored: the project producer validates its closed input
keys before invocation, and core compares the complete resolved descriptor projection. Viper's
duration hook accepts the selected input strings; it does not change native JSON nanosecond types.
An explicit config path prevents discovery, but AutomaticEnv still makes the fixed sanitized
environment necessary. These are source-derived decoder facts, not observed scanner execution.
[Pinned fangs loader](https://raw.githubusercontent.com/anchore/fangs/94c22408c232/load.go),
[mapstructure tag default](https://raw.githubusercontent.com/anchore/fangs/94c22408c232/config.go),
[Viper1.21.0 decoding](https://raw.githubusercontent.com/spf13/viper/v1.21.0/viper.go),
[Grype input versus JSON tags](https://raw.githubusercontent.com/anchore/grype/v0.110.0/cmd/grype/cli/options/datasources.go).

Adopt exact DB schema `6.1.4` for this initial subset, while Cohort.db.schema_version remains the
model integer6. Standalone status and both report statuses require the adopted nonnull Status with
valid=true,error absent,from=`manual import`,path=`/inputs/db/6/vulnerability.db`, equal built/schema.
Provider maps and utility list are nonempty1..128, exact names/digests across all three views;
capture instants compare using the documented whole-second truncation of native map timestamps.
No native xxh64 provenance/integrity identifier is relabeled SHA256. Cohort archive/content SHA256
are separately measured identities. Distribution metadata is retained bounded raw JSON, not used
as an alternative status or a checksum oracle; its acquisition authenticity/feed completeness are
reviewer facts backed by the origin_review evidence. The exact actual DB/archive remains unprovided.

### 6.2 Syft: five-cataloger decision-bearing subset

Native descriptor.configuration is `configurationAuditTrail`, not the CLI options object. Exact
root keys are search,relationships,data-generation,packages,files,licenses,catalogers; extra MUST
be absent for this CLI path (WithTool receives no extra argument). The source transforms these
values itself. [Audit serializer](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/configuration_audit_trail.go),
[CLI call](https://raw.githubusercontent.com/anchore/syft/v1.42.3/cmd/syft/internal/commands/scan.go).

Let K be this exact sorted list: binary-classifier-cataloger,dpkg-db-cataloger,
file-digest-cataloger,file-metadata-cataloger,python-installed-package-cataloger. Native
catalogers is exactly `{requested:{default:K},used:K}`; selection/addition/removal are absent,
not arbitrary empty maps. This intentionally selects three installed/runtime package producers
and complete file bytes/metadata, not all Syft ecosystems. Source confirms these task names and
selection behavior. [Package factories](https://raw.githubusercontent.com/anchore/syft/v1.42.3/internal/task/package_tasks.go),
[file factories](https://raw.githubusercontent.com/anchore/syft/v1.42.3/internal/task/file_tasks.go),
[selection grammar](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/cataloging/selection.go).

| Native pointer under descriptor.configuration | Exact admitted shape/value |
| --- | --- |
| search | `{scope:"squashed"}` |
| relationships | `{package-file-ownership:true,package-file-ownership-overlap:false,exclude-binary-packages-with-file-ownership-overlap:false}` |
| data-generation | `{generate-cpes:true}` (Syft generated observations, not Grype missing-CPE generation) |
| files | `{selection:"all",hashers:["sha256"],content:{globs:null,skip-files-above-size:0}}` |
| licenses | `{include-content:"all",coverage:75}`;75 is a finite native number, not0.75 |
| packages | Exactly keys binary,dotnet,golang,java-archive,javascript,linux-kernel,nix,python |
| packages.python | `{guess-unpinned-requirements:false,search-remote-licenses:false,pypi-base-url:"https://pypi.org/pypi"}` |
| packages.binary | Exact ordered classifier-name array below |
| six other packages children | Bounded native JSON objects retained unchanged. No selected factory consumes those configuration branches; they cannot authorize identity, filtering, coverage or provenance. Unknown packages root key refuses. |

This nondecision carve-out is finite and source-grounded: the selected installed-Python and Debian
constructors have no package-config argument; only binary consumes packages.binary. Removing K's
exact used set or adding another cataloger is a refusal, never an invitation to interpret those
unused objects. File content/executable tasks are not selected; their raw config is not a substitute
for independent R1 bytes or license texts. The custom file config serializer emits zero content
despite the CLI's other content settings; executable config is not emitted. [File serializer](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/cataloging/filecataloging/config.go),
[installed Python constructor](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/pkg/cataloger/python/cataloger.go).

packages.binary is this ordered array (duplicates are intentional, not set-normalized):

```text
python-binary,python-binary-lib,pypy-binary-lib,go-binary,julia-binary,helm,redis-binary,
valkey-binary,nodejs-binary,busybox-binary,util-linux-binary,haproxy-binary,perl-binary,
php-composer-binary,httpd-binary,memcached-binary,traefik-binary,arangodb-binary,
postgresql-binary,mysql-binary,mysql-binary,mysql-binary,xtrabackup-binary,mariadb-binary,
rust-standard-library-linux,rust-standard-library-macos,ruby-binary,erlang-binary,
erlang-alpine-binary,erlang-library,swipl-binary,dart-binary,haskell-ghc-binary,
haskell-cabal-binary,haskell-stack-binary,consul-binary,hashicorp-vault-binary,nginx-binary,
bash-binary,openssl-binary,qt-qtbase-lib,gcc-binary,fluent-bit-binary,wordpress-cli-binary,
curl-binary,lighttpd-binary,proftpd-binary,zstd-binary,xz-binary,gzip-binary,sqlcipher-binary,
jq-binary,chrome-binary,ffmpeg-binary,ffmpeg-library,ffmpeg-library,elixir-binary,
elixir-library,istio-binary,istio-binary,grafana-binary,grafana-binary,envoy-binary,mongodb-binary,
java-binary,java-jdb-binary
```

These are the outer default classifier names, not nested Java matcher branches. Only resulting
python/python-binary(-lib) artifacts fit this initial adapter; another binary artifact refuses
instead of being dropped, including one already owned by Debian. This is a material compatibility
cost: a real base with separately discovered bash/openssl can fail this profile. Do not claim
support or remove evidence to make it fit. [Binary serializer](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/pkg/cataloger/binary/classifier_cataloger.go),
[default classifiers](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/pkg/cataloger/binary/classifiers.go),
[outer Java classifiers](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/pkg/cataloger/binary/classifiers_java.go).

Syft config_input is a closed JSON object used as YAML-compatible input. Its keys/values are:
`check-for-app-update:false`, `scope:"squashed"`, `from:["oci-dir"]`, platform=selected platform,
`exclude:[]`, `enrich:[]`, `default-catalogers:K`, `select-catalogers:[]`,
`package:{search-indexed-archives:false,search-unindexed-archives:false,exclude-binary-overlap-by-ownership:false}`,
`relationships:{package-file-ownership:true,package-file-ownership-overlap:false}`,
`file:{metadata:{selection:"all",digests:["sha256"]}}`,
`license:{content:"all",coverage:75}`,
`python:{search-remote-licenses:false,guess-unpinned-requirements:false,pypi-base-url:"https://pypi.org/pypi"}`,
`compliance:{missing-name:"keep",missing-version:"keep"}`,
`unknowns:{remove-when-packages-defined:false,executables-without-packages:true,unexpanded-archives:true}`.
No omitted/extra root key. Native missing name/version refuses in core rather than a producer
drop/stub. Syft Run argv is exactly `/tools/syft`,`scan`,`/inputs/image`,`--config`,
`/config/syft.json`,`--output`,`syft-json`; same fixed environment/cwd as Grype. No positional URI
network source, aliases or override flag. This binds observation to the source-reviewed fixed
producer recipe; a report cannot cryptographically prove the process used that file.

### 6.3 Exact image and location mapping

Syft v1.42.3 pins stereoscope0.1.22. Its NewLocationFromImage writes FileSystemID from
layer.Metadata.Digest; that field is obtained from Layer.DiffID(), so JSON location.layerID equals
an uncompressed config rootfs.diff_ids entry. The ordinal joins it to the compressed manifest
layer descriptor. Require unique diff IDs in this finite subset (duplicate IDs refuse) and same
ordered count/media types; never compare location directly to a compressed digest. Config imageID
is SHA256 of raw config; manifestDigest is SHA256 of raw manifest. [Location constructor](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/file/location.go),
[layer metadata](https://raw.githubusercontent.com/anchore/stereoscope/v0.1.22/pkg/image/layer_metadata.go),
[image metadata](https://raw.githubusercontent.com/anchore/stereoscope/v0.1.22/pkg/image/image_metadata.go).

Native layer size is the sum of cataloged member metadata sizes, not a compressed-byte or tar-byte
identity. Require nonnegative signed63-bit size and imageSize=sum(layer.size), retaining these as
observations; authoritative compressed size is the decoded manifest/R1 descriptor. Final regular
file hash/size equals R1. layerID must name the actual contributing layer; where R1 supplies no
per-file historical-layer observation, membership plus final byte/path consistency is all core
can establish, not an independent replay of whiteouts. The complete final filesystem comes from
R1's actual inspection. [Layer indexing](https://raw.githubusercontent.com/anchore/stereoscope/v0.1.22/pkg/image/layer.go).

Image source metadata allows exactly userInput,imageID,manifestDigest,mediaType,tags,imageSize,
layers,manifest,config,repoDigests,architecture,os plus optional architectureVariant,labels,annotations.
Required tags/repoDigests are arrays or null, never used as trust; optional labels/annotations are
bounded string maps, inert. userInput=`/inputs/image`; architecture amd64/arm64 and os linux join
platform; variant absent/empty for this subset. Each layer has exactly mediaType,digest,size.
Canonical image paths and accessPath resolve under R1 symlink rules; changed alias/hide annotation
cannot remove a final regular file from coverage. No unknown source metadata key is admitted.

Provider/feed presence and complete coverage of Debian/Python/Rust/CPython remain real producer/
reviewer facts backed by retained actual native provider records and acquisition documents. No
code-only list of ecosystem names or positive package count proves vulnerability-feed completeness.
The adapter can compare identities/times/native error conditions; it cannot authenticate an
external feed or infer coverage from an empty findings array.
This explicitly supersedes the research §8 suggestion of an unspecified required-provider-ID
policy: no hidden feed-name table is part of the executable subset. Exact nonempty cross-view
provider equality is machine-checked; attributable feed-support/currentness assessment is a
required origin_review rationale/evidence responsibility, bound to the immutable cohort and exact
allowlisted release. It is not a claim that any nonempty provider set proves ecosystem coverage.

For scan finished times f and issuance i: start<=finish<=i+300000; i-f<=86400000; DB built b satisfies
b<=start+300000 and max(0,start-b),max(0,i-b)<=432000000. Native RFC3339 timestamps parse with bounded
fraction/zone to exact integer milliseconds; submillisecond values are accepted only when exactly
representable or compared as rational times without rounding across a boundary. Later installation
does not repeat these comparisons against today; it checks current trust/allow/revoke policy.

## 7. Provenance and source/rights authority

SLSA statement is the raw in-toto Statement v1 envelope with exactly `_type,subject,predicateType,
predicate`; values `_type=https://in-toto.io/Statement/v1` and
predicateType=https://slsa.dev/provenance/v1. Exactly three subjects named image-index,
selected-manifest,image-config, each `digest:{sha256:H}` from the actual staged R1 graph.
Predicate has exactly buildDefinition and runDetails. [SLSA provenance v1](https://slsa.dev/spec/v1.1/provenance).

Chosen project buildDefinition is exactly `{buildType,externalParameters,internalParameters,
resolvedDependencies}`: buildType=`urn:deeptwin:build-type:provider-r1-offline-assembly:v1`;
internalParameters={}; externalParameters has exactly extension_id,extension_version,platform,
recipe,source_closure,dependency_closure,toolset (last four S). The first three S values join the
actual recipe/source/dependency bytes; toolset identifies the **retained R1 toolset manifest** below.
No R1 report or recipe field is added or reinterpreted.

The R1 source, dependency and filesystem reports each have toolset:S; SourceReport.recipe.toolset
must equal all three, and externalParameters.toolset must match. Retain that manifest as one
origin_evidence leaf, canonical <=65536 bytes: an array of1..128 exactly
{path:R,sha256:H,size_bytes:integer0..33554432} rows, sorted uniquely by path, total identified source
bytes<=33554432. Zero source bytes are permitted only for __init__.py. R is the unchanged R1
relative-path grammar (<=255 UTF-8 bytes). This is the R1 toolset's existing row grammar, not a
new observer-run report. Require its eight named roots deploy/provider_release/{__init__,contracts,
inputs,oci,build,inspect,capsule,service}.py and only .py repository paths in the remaining rows;
the real producer/finalizer, not core parsing a manifest, establishes complete static import closure
and absence of unresolved dynamic imports. Source hashes are external-original identities, not
a claim that core received/executed those .py bytes. The manifest itself MUST be received and hashed.

Each dependency object is exactly {uri:string,digest:{sha256:H}}; duplicate URIs refuse; order is
ascending UTF-8 URI bytes. Prefix every suffix below with `urn:deeptwin:r1:`. For path suffixes,
encode each UTF-8 path component with uppercase %HH except ASCII unreserved A–Z/a–z/0–9/-._~,
preserving separating slashes; core derives this spelling and never decodes/fetches arbitrary URIs.
Select DependencyReport.platforms' one entry matching the actual stage platform. Exact
buildDefinition.resolvedDependencies is the following union, no caller-chosen omissions/extras:

| URI suffix | Exact SHA-256 source |
| --- | --- |
| recipe | Canonical SourceReport.recipe bytes, also the actual InputTriple.build_recipe identity |
| source-bundle | SourceReport.source_bundle.sha256, equal to actual InputTriple.source_bundle |
| dependency-input-set | Canonical selected DependencySet bytes, equal to InputTriple.dependency_input_set |
| base-lock | SourceReport.recipe.base_lock.sha256 |
| dependency-lock | Selected DependencySet.lock.sha256 |
| base | Selected DependencySet.base.index.digest with its exact sha256: prefix removed |
| source/<encoded source_path> | Every SourceReport.files row's sha256 (launcher and schemas are included once here, without duplicate aliases) |
| wheel/<encoded filename> | Every selected DependencySet.artifacts row's wheel.sha256, exactly the seven selected distributions |
| toolset | Retained toolset manifest SHA-256 |
| observer | Manifest row deploy/provider_release/inspect.py.sha256 |

R1's existing exact source-layout/source-file and input/OCI validations still run before this
projection. This table projects those validated rows; it neither freezes a stale source list as
a substitute for checking them nor silently revises the R1 source44 profile.

runDetails has exactly builder,metadata,byproducts. Builder is exactly
{id:"urn:deeptwin:builder:provider-r1-observer:v1",version:{observer:H},builderDependencies:[...]};
version.observer equals the inspect.py row above. builderDependencies contains exactly the toolset
manifest entry (`urn:deeptwin:r1:toolset`) plus one entry per manifest row with URI
`urn:deeptwin:r1:tool/<encoded path>` and that row's sha256, sorted by URI. It is a **source-toolset
projection**, not a nonexistent recipe runtime list or proof of which interpreter executed.

Metadata is exactly {invocationId:canonical nonnil UUID,startedOn:string,finishedOn:string}.
Timestamps are valid RFC3339 UTC `YYYY-MM-DDTHH:MM:SSZ`, no fractions/offset aliases/leap seconds,
converted exactly to epoch milliseconds0..253402300799000. Require start<=finish<=review.issued_at_ms
and finish<=each of Cohort.syft_run.started_at_ms and both Grype invocation start times. These are
**attributable signed execution assertions** whose raw provenance digest is bound by the review;
there is no equality to an R1 run ID/time because those fields do not exist. BuildRecipe.created
remains the deterministic1970 image timestamp and is never used as observed execution time.
Byproducts are exactly three {name,digest:{sha256:H}} rows in order source-report,
dependency-report,filesystem-report, equal to the three actual retained raw report bytes.

No extra runtime-provenance schema/object is required for this byte-verification subset. Real
release origin_review.evidence must still support the accountable reviewer's actual producer
interpreter/distribution/executed-tool assertions; existing retained origin evidence carries that
authority responsibility. Core does not derive runtime authenticity from source-toolset hashes.
If a later contract requires independently machine-joined runtime execution, that is a new
bounded evidence profile, not permission to fabricate an R1 field here. No URI is fetched.

Preflight R1 history: the prior draft incorrectly joined SLSA metadata to nonexistent observer
fields and inferred a runtime list from BuildRecipe. F1 selects the minimal signed-assertion
formulation above while preserving frozen R1 report/recipe bytes. The source for these exact
existing fields is local provider-release-producer-draft.md §§4.1–4.4 and its explicit-input/fresh
finalization amendment; that producer proposal remains advisory, not an implemented producer claim.

The source_report/dependency_report/filesystem_report parsers reuse the frozen R1 selected grammar
and stage joins; this appendix does not grant authority to a newly authored equivalent report.
Original base/wheel/source identities may be external to the uploaded packet but are checked
against actual stage/receipt/R1 records. An external finalizer must actually possess and inspect
the original input_root; core cannot prove that fact from a consistent signed narrative. Likewise,
SPDX/source/license declarations are attributable reviewed assertions. Byte verification is
implementable; copyright permission, truthful supplier linkage, executed scans and release approval
can only come from real authorized producers/reviewers. No extra natural person is mandatory.

## 8. Callable contract, offline vectors and ownership

No new product file ownership beyond the installation draft is needed for this appendix. Put raw
parsing/projections/joins in `app/extensions/provider_installation_evidence.py`; closed envelopes
and typed immutable values in `provider_installation_contracts.py`; fixture construction in the
two already owned test fixture modules. If that becomes too large, controller must approve an
exact ownership amendment before splitting; no hidden unowned helper is assumed.

Existing proposed `parse_external_document(role,raw)->ExternalDocument` retains exact content_bytes
and detached as_dict. `evaluate_release(packet,source_files,stage,now_ms)->ReleaseAssessment`
must execute: packet closure -> independent current trust/signature -> stage/subject/R1 join ->
cohort/config/DB/run checks -> native inventory/SPDX/map reconciliation -> both scan/finding
policies -> license/provenance joins -> immutable assessment. It never accepts a caller-supplied
assessment or callback. The service's final writer rechecks exact source/current head/owner/time.
The assessment remains private, contains only core-derived facts and exact evidence references,
and is unusable outside that same service/store context.

Fixture labels live in fixture filenames/test metadata, not production review schemas. Generate
small internally consistent synthetic raw documents and ephemeral test signatures; synthetic
publisher/licensor/acquisition statements explicitly say SYNTHETIC TEST ONLY. Every hash is
computed from the actual synthetic bytes. Never call them output observed from Syft/Grype/R1.
Positive integration fixtures require real local stage/store operations and the complete selected
grammar; they cannot bypass any §6 check through monkeypatching an evaluator.

Required positive vectors under the frozen draft §6 subset:

1. Both platforms independently, seven selected Python distributions, nonempty Debian and CPython,
   at least one explicitly linked synthetic bundled crate, first-party source closure, both empty
   scan arrays, complete SPDX/file/license/supplier graph, exact ephemeral trust and issuance.
2. Same graph with one Medium finding including finite decimal CVSS and exact review acceptance;
   unchanged raw float spelling retained. Metadata observations cannot remove that finding.
3. Nonempty Debian source upstream, multiple file ownership, local extracted LicenseRef, declared
   OR branch concretely selected; exact same-byte evidence reused through one retained descriptor.
4. Old issuance-valid review consumed next day under still-current exact allow policy; expired
   qualification irrelevant to artifact evidence and no native/binding authority emitted.
5. Complete unchanged R1 source/dependency/filesystem grammars plus retained synthetic toolset
   manifest, exact observer/dependency/byproduct projection and independently supplied signed SLSA
   run metadata. Reports deliberately contain no invocation/timestamp fields; use a non1970 run
   assertion ordered before the synthetic scans. This must exercise the real evaluator successfully.

Required refusal mutations (re-sign/re-pin the bad synthetic packet when testing semantics so a
signature/allow mismatch cannot mask the intended reason):

| Class | Every enumerated mutation must be exercised |
| --- | --- |
| Envelope/closure | wrong current key/role/issuance/allow; bad signature; changed raw byte/size; unused object; missing retained reference; cycle; duplicate role/digest; same digest interpreted by incompatible parsers. |
| Raw limits | duplicate nested key; invalid UTF-8/surrogate; nonfinite/overflow numeric token; depth/member/string limit and +1; malformed/oversize embedded base64; ordinary canonical parser must not handle CVSS. |
| Inventory | empty/missing package inventory despite empty scans; wrong ID-prefix conversion; duplicate IDs; omitted/extra projection/package/file; wrong epoch/arch/PURL; changed file/wheel hash; first-party relabeling; unresolved native layer coordinate. |
| SPDX/license | second root; GENERATED_FROM/OTHER/external edge; multiple PURLs; forbidden purpose; broken inverse ownership; cycle; unresolved LicenseRef; NONE/NOASSERTION; illegal OR selection; missing text/obligation/supplier evidence. |
| Scan/config/DB | unknown decision config; filtering/overlap/VEX enabled; nonzero exit/diagnostic/stderr; mismatched raw resolved config; wrong tool/input/DB hash; stale issuance DB; High/Critical/Unknown/missing severity; nonempty ignored/alerts; absent/extra Finding acceptance. |
| Provenance | wrong R1 subject; omitted extra resolved input; synthetic expected report substituted for actual stage report; unsupported buildType; observer-toolset/byproduct mismatch or invalid signed run ordering; source closure from old topology. |
| Historical/current | valid old scan+current deny refuses; current allow does not grant runtime permission; missing real originals never asserted as proved by synthetic checks. |

Selected-codec boundary vectors additionally require: compressed layer digest substituted for
diff ID; duplicate diff IDs; compressed byte length substituted for native member-size sum;
SPDX locations [] substituted for native null; Grype root sort-by substituted for SortBy;
duration strings substituted for native nanoseconds; match-upstream-kernel-headers=false with
its default implicit ignore rules; empty/lost provider map; xxh64 coerced to SHA256; altered
provider fractional-second truncation; extra used cataloger; non-Python binary discovery;
canonical map at item/byte limit and+1 (including dictionary keys); reachable provenance removed.
Each tests the actual production parser/evaluator, not a mocked expected verdict. A raw
diagnostic-only value change must remain retained and signed but cannot change admission for an
otherwise freshly signed/exactly allowlisted graph; a decision-bearing value change must refuse.
F1 refusal vectors additionally re-sign/re-pin: toolset hash disagrees across a report/recipe;
missing/duplicate inspect.py row; wrong observer version; omitted/extra/wrong source-tool dependency;
wrong byproduct hash/order; malformed/nil run UUID; invalid/fractional/non-UTC run timestamp;
start>finish, finish>issuance or finish>scanner start; injected R1 timestamp/run field. A different
well-formed signed run assertion satisfying ordering is not falsely rejected for failing an
unavailable independent R1 clock equality. F2 rejects a signed review carrying any policy digest
other than installation draft §3.1, even when that altered review is exactly allowlisted.

The selected table permits offline implementation of the connected evaluator and positive service
transition in the same task after controller approval and exact accepted-base confirmation. Do not deliver only
lower-layer parsers/static dead code. A real image outside this finite subset is explicitly
unsupported until a separately reviewed compatibility amendment; synthetic positives do not erase
that restriction or imply that current real reports fit.

## 9. Executable-plan amendment and carrier proof

Use writing-plans Phase A–D from the companion draft with this appendix's complete selected
grammar and incorporated exact Grype table. No additional real authority is needed to implement
these deterministic codecs or construct labeled synthetic vectors. Do not run scanner binaries
or turn synthetic producer claims into an authentic release to fill a test fixture.

The controller-selected carrier requires actual `UploadLock.publish(service.execute, ...)` awaited
by the route. It owns/shields the synchronous publication task and retains its FD through HTTP
cancellation until that task finishes. Before publish, cancellation releases buffers/lease and
there are no writes. After publish, commit may finish despite disconnect; exact authenticated
retry/read retrieves durable result. A boundary finally close must not release the in-flight
lease. Only the independently authorized exact release closure may be presealed.

Required actual ASGI vectors extend A1–A7: no receive before auth; duplicate singleton/length/encoding
headers; every prefix/header/object split including multiple objects per chunk; exact caps/+1;
declared short/long/trailing/hash mismatch; one total deadline; disconnect/timeout lease reuse;
same/second-process contention; cancellation during actual publication retains lock until finish,
then byte-identical durable retry. Adapt WorkServiceError into installation's error family.
No plain run_in_threadpool shortcut, second buffer on contention, joined duplicate48 MiB copy,
generic upload registry or unrelated route limit widening.

## 10. Self-review and history of the G1 decision

The broad earlier G1 requested all nested scanner shapes. The first appendix revision closed the
project signature/map/SPDX/finding/provenance choices but truthfully left native config/DB/layer
source tables unresolved. Controller requested bounded tagged-source closure instead of another
research gate. Revised research §8 and this appendix §6 now resolve that finite gap: Grype's
actual wrapper/keys/durations/DB tables, Syft's selected catalogers/audit wrapper, and uncompressed
diff-ID layer coordinates are explicit. Earlier uncertainty is preserved here, not relabeled as
previously completed work. Source-derived native facts and chosen project restrictions are separate.

Self-review checked acyclic reachability (including the explicit review->provenance edge),
canonical-vs-raw limits, no filter/overlap bypass, exact native namespaces, and cancellation-safe
publication. G1 is closed for this draft's finite offline implementation contract, not for authentic
release compatibility. Controller installation preflight and exact accepted Task45 R5 base
confirmation are still required; current acceptance and earlier checkpoints are distinguished above. Real cohort
measurements/keys/legal permission are separate release gates. Earlier profile proposals remain
preserved, including release-time freshness and capability—not compulsory two-person—review.

Independent preflight subsequently identified F1–F4 despite that earlier G1 closure claim. This
R1 amendment corrects F1's nonexistent observer equality using the exact existing R1 toolset and
signed run assertions (§7), binds F2 to the installation draft's literal policy-byte contract (§3.1),
and follows its F3 exact test ownership/F4 source→evaluator→actual-authority sequence. R1 producer
schemas, old-history bytes and actual release authority remain unchanged. Self-review checked
the new toolset leaf's typed reachability, acyclic dependency projection, timestamp ordering,
policy digest equality consumers and their phase-specific tests. No tests/product edits ran here.

## 11. Genuine real-release gates (not ordinary offline coding prerequisites)

Authentic scanner binaries/config/status/provider/version/schema/acquisition and unchanged report
bytes; actual native scan execution against the same identified DB; original base/eight two-platform
wheels/source input_root; exact shipped Rust/supplier/build correspondence; measured per-report,
header, total, process-memory and retained-graph fit; legitimate rights review/release approval;
independently provisioned real public trust and supported deployment/distribution update path.
No authentic hashes, outputs, keys, licenses or measurements are manufactured by this appendix.

Trusted deployment prepares staged artifacts, fixed public-source trust and offered evidence.
The ordinary browser user selects the offered release; the product transports its packet and
shows verification/refusal. Users do not author signatures/scans/source files or run a CLI.
Qualification/native enrollment/provider permissions/binding remain later work; T087 stays open,
and whole-product50%±5 is unchanged.
