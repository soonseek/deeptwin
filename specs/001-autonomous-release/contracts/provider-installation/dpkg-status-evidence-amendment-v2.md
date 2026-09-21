# Task46 retained dpkg status evidence — controller amendment draft

2026-09-20. Design/preflight only; requires controller adoption before the sole writer implements.
Bounded Debian inventory proof repair; no producer/native qualification. Controller selected retained
status evidence and the narrow ownership exception. No product/tests/canonical snapshots edited.

## 1. Basis, selected approach, and precedence

Read: canonical `contracts/provider-installation-verification.md`; adapter §§2–4/6–8;
installation §3.1/ownership/carrier; R1 producer §§4/4.4; complete scratch
`task-46-dpkg-status-source-reference.md`. Paths under `specs/001-autonomous-release/` are implied
for canonical contracts. The tagged-source note is human evidence, never runtime expected truth.
Syft 1.42.3 discards raw Status from dpkg-db-entry and only filters lowercase `deinstall` substrings.
Neither an absent metadata.status nor surviving that filter proves the required installed state.

Select one retained status leaf joined to complete staged R1; reject weaker non-deinstall or metadata.status.
Do not emulate dpkg/Syft, acquire images/wheels, replay containers, or implement an evidence producer.
This intentionally strict project subset may refuse authentic Debian databases, including legitimate
removed/residual records. Supporting such databases requires a separately reviewed amendment.

On adoption, append this amendment's normative content to the canonical master contract (controller
owns that edit). It supersedes only adapter §3 Map, §4 status/file-containment clauses, the typed
leaf parsing consequence of §2/§3, and installation §3.1 policy deltas specified here. All other
incorporated requirements remain. Preserve all eight frozen snapshots and their recorded hashes;
do not change their bytes or describe them as already containing this correction. The draft alone
does not override the master. Existing image Source.metadata behavior remains adapter §6.3.

## 2. Exact new reference, byte domain, and staged source join

Replace Map.schema_version with `provider-component-map-v2`; add exactly required `dpkg_status:S`
to adapter §3's otherwise unchanged closed Map. There is exactly one selected source, fixed path
`/var/lib/dpkg/status`; there is no uploaded path, format selector, list, or per-package status copy.
`S={sha256:H,size_bytes:int1..1048576}` identifies exact raw Debian-control bytes, retained once as
the existing `origin_evidence` role. Map -> dpkg_status is a typed leaf edge; Review -> Map and its
exact descriptor closure bind it. It is not external or authority prose; incompatible parser reuse refuses.

Count it within existing 128 objects, 48 MiB total, 4 MiB aggregate metadata, 1 MiB origin object,
32 KiB header and retained graph limits; none increases. Its decoded text is not one canonical
JSON string. Canonical map limits remain 1 MiB/depth32/items10000/string65536. No new role, source
file, exported schema, trust root, key, signature domain, policy-upload or acquisition interface.

After the existing real stage/subject/R1 joins, require exactly one final FsEntry at that path:
kind=file, nlink=1, positive size and SHA-256 exactly S and independently recomputed raw bytes.
Every ancestor is an actual directory in that same complete R1 filesystem (no symlink parent).
Use the unmodified R1 absolute-path and sorted-unique full-root grammar. No host path is opened.
Report platform/index/entry/build/upstream identities join the real stage, never a replacement expected report.

Examine every R1 filesystem row, including symlinks, for alternate cataloger inputs: refuse any
other path ending `/lib/dpkg/status`; any descendant of a path ending `/lib/dpkg/status.d`; and
any path ending `/lib/opkg/status` or matching `/lib/opkg/info/<single component>.control` suffix.
An empty actual status.d directory is allowed; a symlink/non-directory at that directory path
refuses. Match suffixes at path-component boundaries at every depth, not only under /var.
Use only retained R1 rows/target text and existing virtual-root/component resolution (at most40 hops).
Check direct links and directory-prefix aliases: substitute each link's lexical prefix for its
resolved target prefix in retained descendant paths, carrying both spellings through bounded chains.
Across the entire assessment allow at most8192 unique derived alias paths, separate from original
R1 rows; each derived path is at most4096 UTF-8 bytes. Check before materialization/queue insertion;
same-path deduplication spends no additional budget. Saturation/overflow refuses unknown source
reachability rather than silently dropping states; at-cap completion without another new path is allowed.
Apply the source suffix tests to lexical and substituted paths; an ancestor alias cannot erase a
`/lib/dpkg` or `/lib/opkg` match. Refuse an alias to selected/alternate status, an alias exposing
status.d/opkg inputs, or a symlink in an actual cataloger-source path's ancestor chain.
Missing/cyclic/escaping/over-limit resolution refuses under this amendment only when the chain
affects or leaves ambiguous cataloger-source reachability. Complete R1 absence can establish that
an unrelated dangling target reaches no retained source; retain old R1 policy for that link.
No new global target-existence rule, host traversal or independently observed native walk is claimed.

## 3. Deterministic raw-control subset (not a general Debian parser)

Preserve content_bytes without reserialization, newline conversion, trimming or replacement UTF-8.
Before materialization: 1..1048576 bytes, strict UTF-8, no BOM, CR, NUL, TAB, DEL or other C0 except
LF; at most65536 physical lines, each at most4096 bytes excluding LF; final byte must be LF.
One empty LF line separates paragraphs; optionally one empty line follows the last paragraph;
no leading empty line or repeated blank separators. At least1 and at most8192 paragraphs.
Each paragraph has at most26 fields and4096 physical lines (tighter aggregate/byte limits win).
Paragraph/field order is preserved but never selects which records count.

Field lines are `Name: value`: exact case-sensitive name, colon and exactly one ASCII space;
value has no leading/trailing ASCII space. Mandatory nonempty Package, Status, Version, Architecture
occur exactly once. All duplicate field names, including case-folded duplicates, refuse. No comments,
stanza garbage, lowercase aliases, empty mandatory values or duplicate-record last-wins behavior.
Allowed optional names are exactly Source, Multi-Arch, Essential, Protected, Priority, Section,
Installed-Size, Maintainer, Original-Maintainer, Homepage, Description, Depends, Pre-Depends,
Provides, Recommends, Suggests, Enhances, Breaks, Conflicts, Replaces, Conffiles, Built-Using.
Unknown names refuse rather than being dropped. Optional values may be empty and are preserved.
Only Description and Conffiles permit continuation: a line starting ASCII space continues that
field; preserve remaining bytes including further spaces. Other/orphan continuations refuse.
The continuation ` .` is retained literally, not converted to a blank paragraph. Folded text is
never reparsed as fields, so a continuation containing `Status:` cannot supply the required key.

Package is 2..128 ASCII bytes matching `[a-z0-9][a-z0-9+.-]+`, without an `:arch` suffix.
Version is 1..128 ASCII bytes matching `(?:[0-9]+:)?[0-9][A-Za-z0-9.+~:-]*`; literal full-token
equality preserves epoch/revision and claims no Debian version ordering.
Architecture is exactly the selected stage's `amd64` or `arm64`, or `all`. Multi-Arch, when present,
is exactly `no`, `same`, `foreign`, or `allowed`; it never changes the architecture restriction.
Foreign architecture records, repeated (Package,Architecture), and a second architecture for the
same Package all refuse. Multi-Arch declarations themselves are allowed; coinstalled multiarch
and foreign-architecture images are outside this subset, never silently projected to one member.

Status must be exactly `install ok installed` in every paragraph. Missing, empty, extra whitespace,
case variants, `hold ok installed`, any deinstall/purge/config-files/not-installed state, unpacked,
half-installed/configured, triggers-awaited/pending, error flags or unknown tokens refuse the whole
packet. Do not filter those records out, even if Syft omitted them or the remaining scan is empty.
Every admitted paragraph is therefore installed and participates in the complete bijection below.

Source, if present, is nonempty `Name` or `Name (Version)` using the tokens above and exact spacing;
require native metadata.source=Name and metadata.sourceVersion=explicit Version or binary Version
for the bare form. This is an explicit project equality, not a claim about upstream defaults.
When Source is absent, impose no newly invented default; retain adapter §4's existing native/PURL
upstream checks. Other optional fields are bounded retained observations, never identity overrides,
inventory filters, file ownership evidence or admission authority. Do not infer dpkg execution.

## 4. Complete inventory and metadata-file containment

For each paragraph derive key (Package,Version,Architecture). Require an exact nonempty bijection
to all Syft artifacts of type=deb, foundBy=dpkg-db-cataloger, metadataType=dpkg-db-entry. Package/name
and metadata.package equal Package; package.version and metadata.version equal full Version;
metadata.architecture and decoded Debian PURL arch equal Architecture. No extra raw record, native
Debian artifact, duplicated identity/ID or missing record is admitted. Exactly one Map Debian
component and one non-root SPDX package correspond to each such artifact; syft_ids has exactly
that one ID. Name/version/PURL, native and SPDX projections, licenses and complete owned-file joins
still satisfy adapter §4. This is a bijection, not a subset/count check; other classes are unchanged.

Each native Debian artifact has exactly one location whose path and accessPath both equal
`/var/lib/dpkg/status`, with layerID naming the matching Syft file coordinate's admitted diff ID.
Other evidence locations obey existing native/R1 rules and cannot name another cataloger source.
Metadata location is not ownership. Exactly one corresponding Syft regular File row has SHA256
and size equal raw status/R1, and its layerID satisfies adapter §6.3's existing
membership rule; do not pretend the R1 report proves unavailable per-file layer history.

Narrow explicit exception to §4's component-file inverse: the status path has exactly one FileLink,
with that one native Syft file ID, its real SPDX file ID, and `components:[]`. No component
files/metadata.files/native package-file-ownership edge may claim this status file; such a graph
refuses this subset. Discovery-location relationships alone do not become ownership edges.
The container root has exactly one CONTAINS edge directly to this SPDX file. Its checksum, license
conclusion/info and retained license text/rights evidence still satisfy the normal file checks.
Root containment grants no package/class/scan coverage; every other regular R1 path retains exact
nonempty component inverse coverage. No blanket unowned-file exemption is introduced.
Root direct-file edges to other paths, orphan status, or fake first-party status ownership refuse.

## 5. Exact policy and callable consequences

In installation §3.1's literal object set policy_revision=2 and interpretation_id=
`provider-release-adapter-preflight-r2-dpkg-status-v1`. Set coverage.component_map=
`provider-component-map-v2` and coverage.file_coverage=
`exact-r1-regular-file-inverse-dpkg-status-root-v2`; add coverage.debian_status=
`retained-dpkg-control-installed-bijection-v1`. All other policy keys/values remain exact.
These IDs select this complete bounded grammar; no runtime selector is accepted. Derive the new
canonical bytes/digest via existing code-owned functions. Renderer, initializer, sources and signed
Review must agree. Reject old/foreign policy digests and v1 maps for new admission, even if signed
and allowlisted. Historical record loading is unchanged; this grants no migration/reverification.

Public evaluate_release(packet,source_files,stage,now_ms) and private assessment remain unchanged.
Implement typed raw-leaf parsing inside owned provider_installation_evidence.py, with immutable
raw bytes and derived records; do not send this leaf through JSON parse_external_document or accept
a parser/verdict callback. Extend existing Map validation in owned contracts/evidence as needed.
Policy: app/deployment/installation_release_contracts.py; tests: owned fixture/contract/evidence/service/API files.
Task46 remains exactly34 new/28 modified product paths; no helper module/producer is assumed.

## 6. Required executable vectors and fixture cross-joins

Use actual production parsing/evaluation and real temporary stage/store/source publication. Fixture
raw status is labeled synthetic by fixture metadata, not by illegal native fields. Hash its actual
bytes into the synthetic final filesystem, Syft File, SPDX checksum, Map reference, exact carrier
descriptor and signed closure; regenerate all dependent report/provenance/allow identities. If the
fixture includes OCI members, use those same status bytes and refresh OCI identities/diff IDs too.
Never mutate an already staged immutable report; stage the coherent fixture before evaluation.

Positive vectors: both platforms; native architecture plus distinct `all` package; Multi-Arch:same
without coinstallation; exact epoch/revision; explicit/absent Source; folded Description/Conffiles; root containment;
all existing empty/Medium finding, license/provenance, next-day current-trust positives preserved.
Check retained bytes unchanged, including field order, continuation bytes and trailing newline.

Refusal vectors (one mutation each, re-sign/re-pin semantic cases): missing/null/extra Map key or
v1 map; wrong role/missing leaf/unused second status/ambiguous parser reuse; byte/hash/size mismatch;
wrong R1 kind/nlink/ancestor/path; Syft hash/size or SPDX checksum disagreement; missing/duplicate/wrong status location,
accessPath, layerID; each alternate status/status.d/opkg/alias path, even without a native artifact.
Regression: unrelated `/etc/mtab -> /proc/mounts` absent target obeys old R1 policy; direct status
alias and ancestor alias exposing a source under an otherwise nonmatching physical path refuse.
Alias tests exercise exact8192/+1 unique derived paths, duplicate reuse, and4096/+1-byte derived paths.
Exercise every Status case in §3; no records; duplicate record; omitted/extra record, Syft artifact,
SPDX package, Map component or projection; name/epoch/version/arch/Source mismatch; foreign arch,
same-name coinstallation, invalid Multi-Arch; invented metadata.status; status falsely package-owned,
orphaned/root-link omission; second arbitrary root-contained file. Each must refuse with no authority.
Parser vectors: unknown/duplicate/case-duplicate fields; malformed separator; blank mandatory field;
identity fold; orphan fold; CRLF/BOM/NUL/TAB/invalid UTF-8; comment; no final LF; repeated separators;
exact byte/line/paragraph/field limits and +1 at parser level (tighter semantic/aggregate limits win).
A valid diagnostic change passes with coherent graph rebuild/re-signing and changed raw bytes retained.
Test old-policy rejection through renderer/source/evaluator and service/API with no authority write; matching v2
policy/map must complete the actual same-store verified2 transition and existing descendant checks.

Load-bearing conflict: closed Map, unretained status and component-only file inverse require these
explicit amendments. No existing producer emitting this leaf is asserted. Real extraction, truthful
full R1 observation, native compatibility and release authority remain separate gates.
