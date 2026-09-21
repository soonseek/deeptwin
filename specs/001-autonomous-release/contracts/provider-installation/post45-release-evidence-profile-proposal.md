# Post45 release evidence — one finite artifact-review profile

2026-09-20. **Advisory preparation only.** This proposes `provider-artifact-review-v1` to close
§3 of `post45-installation-boundary-proposal.md`; it does not promote either note, approve a
release, provision trust, accept Task45, or authorize actual tools/scans/keys/native work. Only
this file is written. Primary documentation was researched; no product files, moving Task45
files, imports, SQL, tests, real artifact downloads, scans, native runs or commits were performed.

The original R1 producer/review remain advisory. Their repaired explicit `input_root` dependency
is retained; their source/dependency/filesystem reports establish byte observations, not security
or licensing decisions. Canonical constitution/runtime/ADR-014 installation-versus-qualification
boundaries continue to govern. Task45 is referenced solely through its fixed promoted contract,
not its changing implementation. The old tool/v3 durable-qualification proposal is not authority.
Brainstorming informed the alternatives; writing-plans informed dependencies only. This is the
delegated architectural decision artifact, not a full implementation plan or an execution handoff.

## 1. Decision: retained observations, one attributable release decision

Use one release-workspace profile for **one selected immutable Linux image platform per packet**:

`actual R1 inputs and independent OCI inspection -> observed build provenance + final-image Syft
inventory -> independently reviewed SPDX component/license inventory -> two Grype scans against
one fixed database -> independently authorized release review -> core byte/graph/policy checks`.

Here independence means independently provisioned trust, separated capabilities and a fresh
verification execution over actual bytes, **not two different natural persons**. Release evidence
is reusable evidence about issuance-time facts; current deployment admission policy, not a daily
human re-review, determines whether that immutable approved release may be newly installed. The
2026-09-20 amendment in §10 records why the earlier recommendations changed.

The two scans cover the final-image inventory and the reviewed component inventory respectively;
the latter includes bundled components that image cataloging may miss. They are two inputs to one
profile, not interchangeable approval services. No mutable URL is a runtime input. Original base,
wheels, source materials, scanner binaries and database stay in the release workspace. Core retains
bounded public evidence bytes and checks their joins; it neither executes the image nor reruns
the scanner. A release review authenticates who examined which retained evidence and input graph.
It cannot make absent observations, unsupported coverage, or unavailable copyright permission true.

This permits artifact-only verification development before native observer enrollment. It does not
establish ABI loading, worker execution, isolation, full provider-port semantics, model capability,
qualification or binding. The private transform worker remains distinct from a provider port.

## 2. Exact producer cohort and accepted formats

All names beginning `provider-` below are **proposed project producers**, not existing software.
No generic verifier callback, caller-supplied `passed` dictionary or hand-authored scanner output is
an accepted positive producer.

| Actual producer to invoke in the future release workspace | Accepted retained result | Inputs and selection rule |
| --- | --- | --- |
| R1 byte builder and independently invoked R1 inspector | Existing proposed `provider-source-closure-v1`, `provider-dependency-closure-v1`, `provider-filesystem-inspection-v1`, recipe/dependency records and ProviderLineage | Actual explicit `source_root`, `input_root`, completed `release_root`; future accepted45 source closure re-enumerated, not R1's stale 44-file list. |
| `provider-release-observer-v1`, wrapping actual builder/inspector calls | in-toto Statement v1 with SLSA provenance v1 predicate; one selected image manifest subject plus index/config subjects | Captures actual reads, producer/tool identities, invocation and outputs; cannot accept an already-successful observation object. |
| Syft **1.42.3** | Raw native Syft JSON, schema ID `anchore.io/schema/syft/json/16.1.3/document` | Explicit local `oci-dir:` source, exact selected platform and `squashed` scope; final image, not source directory or a registry tag. |
| Authorized release reviewer using `provider-license-review-v1` authoring/validation code | SPDX **2.3 JSON** review document, actual license/notice text bytes, source-evidence references and attributable review rationale | Actual installed inventory, sources/locks and supplier evidence for bundled components; no automatic permissive-license inference. The maintainer may also have assembled the release. |
| Grype **0.110.0**, twice | Two complete raw native Grype JSON documents, exact tagged presenter format; raw version/config/DB status/provider metadata and invocation records | Explicit `sbom:` input for the exact Syft document and exact SPDX review document; one locally imported database cohort, no filtering or network resolution. |
| Independently delegated `provider_artifact_review` authority | One signed project release-review statement binding the above bytes, exact subject graph, profile/policy, reviewer and issuance facts | Attributable authorized review; signing capability is unavailable to builder/inspector processes and is not derived from browser upload. No compulsory second person. |

Syft's [CLI reference](https://oss.anchore.com/docs/reference/syft/cli/) identifies 1.42.3;
its [version-tagged JSON schema](https://raw.githubusercontent.com/anchore/syft/v1.42.3/schema/json/schema-latest.json)
identifies 16.1.3. Do not select today's moving `schema-latest` from the main branch. Grype's
[CLI reference](https://oss.anchore.com/docs/reference/grype/cli/) identifies 0.110.0 and local
database import. Its accepted JSON is pinned to the actual
[document presenter](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/document.go)
and [descriptor](https://raw.githubusercontent.com/anchore/grype/v0.110.0/grype/presenter/models/descriptor.go),
not an invented upstream JSON-schema version. A project adapter must enumerate that tagged
format and reject unrecognized decision-bearing shapes; changing tool/format versions is a new
reviewed profile cohort, not a permissive parser fallback.

Version strings alone are insufficient. Before a real cohort is admitted, retain authenticated
upstream acquisition evidence, exact archive/executable SHA-256, executable platform, full version
output, configuration bytes, relevant schema bytes/hashes and project-wrapper source/recipe hashes.
These hashes are not supplied by this note. Pin one execution host platform per cohort; scanning
an ARM image on an AMD scanner host is static analysis, not native ARM evidence. Stop if these
versions cannot actually consume the selected reports/database; do not auto-upgrade or claim the
pair has been exercised here. Scanner executable acquisition and execution require later authority.

The R1 builder stays in-process/no-subprocess. The new external review runner owns the explicitly
bounded scanner processes in a separate release workspace. This is a proposed new boundary, not
permission to smuggle subprocess/network behavior into R1 or into core. No Docker/Engine is needed
for these local file/SBOM inputs. [Supported Syft targets](https://oss.anchore.com/docs/guides/sbom/scan-targets/)
and [Grype SBOM inputs](https://oss.anchore.com/docs/guides/vulnerability/scan-targets/) document these
input forms; the future runner must select them explicitly and prohibit source autodetection.

## 3. Source/build provenance: what was observed versus who accepts it

Use `_type=https://in-toto.io/Statement/v1` and
`predicateType=https://slsa.dev/provenance/v1`, following
[SLSA provenance v1](https://slsa.dev/spec/v1.1/provenance). The proposed build type is a fixed
project URI for R1 offline assembly. Its closed external parameters identify extension/version,
platform, recipe, source closure and dependency-set identities. Resolved dependencies name actual
source tar, base index/selected manifest/config/layers, exact selected wheel archives, launcher,
schemas and toolset by content digest. Run details identify the observer/builder version and
actual invocation/start/finish. Byproducts reference actual inspection reports. No release review,
candidate receipt, stage or future installation hash is embedded back into image/build inputs.

The observer produces this statement during the real operation, not by converting an unsigned
policy into a retrospective build-success story. The authorized review workflow reopens original inputs,
reruns R1 inspection and confirms fresh reports against stored report bytes and lineage. The final
capsule operation still takes explicit `input_root` and freshly rechecks it. A missing/replaced base
or wheel refuses finalization even when signatures and all supplied reports are internally consistent.

Source origin also needs evidence, not just an internally consistent hash: retain the exact source
snapshot and revision/export provenance, upstream base/wheel acquisition records, supplier identity
and any available upstream attestations. The reviewer states which origin evidence was examined and
its limitations. This profile accepts that attributable supply-chain review, **not a SLSA level or
cryptographic proof of every upstream build**. A source revision string alone does not prove origin;
a base supplier's attestation does not cover the new provider source/wheel assembly. Missing origin
evidence for a required input blocks approval rather than becoming `unknown-but-signed`.

R1's expected base is CPython 3.12.14-slim-bookworm, with seven selected distributions/eight wheel
archives across its two-platform producer. Those declarations are not availability. The actual
`input_root/base/` OCI graph, exact `input_root/wheels/<filename>` bytes and the two input projections
remain mandatory. This profile adds no substitute source download, wheel rebuild or interpreter
change. If supplying bundled-component evidence would require such a rebuild, stop for a separately
reviewed input/profile change; do not silently change frozen wheel digests.

## 4. Inventory, vulnerability observations and deterministic policy

Syft runs with no ambient configuration, app-update check or remote enrichment; fixed resolved
cataloger/config bytes are cohort inputs. Capture package-file ownership, SHA-256 file metadata and
license contents; retain cataloging errors. Do not silently drop missing-name/version packages.
Syft exposes these choices in its [configuration reference](https://oss.anchore.com/docs/reference/syft/configuration/).
The reviewer joins Syft image manifest/config/layers and platform to actual R1 bytes; `source.id`
is not assumed to equal the image manifest digest. The tagged
[image metadata structure](https://raw.githubusercontent.com/anchore/syft/v1.42.3/syft/source/image_metadata.go)
supplies the actual identity fields to check.

Coverage obligations are project policy, not claims that Syft discovers everything:

- Enumerate the complete installed Debian package set from the retained final filesystem metadata,
  the seven wheel distributions from R1 dependency evidence and the pinned CPython distribution.
  Reconcile each with the image SBOM, including versions, architecture and paths. Unexpected,
  duplicate-conflicting or omitted runtime packages refuse; an empty SBOM is never a clean result.
- Independently reconcile bundled libraries/components against supplier source/lock/build evidence.
  The SPDX review includes each identified third-party component, exact version and supported
  ecosystem/PURL or justified CPython CPE, containment/dependency relationships and the precise member
  hashes it belongs to. It includes installed packages too, so the second scan is a complete reviewed
  component view, not a partial replacement for the image scan.
- In particular, `rpds-py` distribution detection does not establish its embedded Rust inventory.
  Syft documents Cargo lock and cargo-auditable discovery, but their existence in these particular
  wheels is unverified. Require actual exact-wheel-to-source/build evidence and component/license
  material. An unrelated upstream Cargo.lock or a human guessing the crate list is insufficient.
  Missing evidence blocks this profile's real positive result.
- Only Debian packages, PyPI distributions, Rust crates and the identified CPython binary family
  are admitted third-party component classes initially. Other embedded ecosystems, an unidentified native
  component or an unsupported matcher/feed are a profile refusal, not a zero-findings result.
- First-party provider source/launcher/schema material is separately identified by exact source
  hashes in the SPDX document and provenance review. It has no invented PyPI/CVE identity. Its
  origin/license/byte-closure review is mandatory, but this profile makes no scanner-coverage or
  vulnerability-free claim for unpublished first-party code. The reviewed scope must say so;
  third-party code cannot be relabeled first-party to avoid a required matcher or supplier record.

The relevant documented capabilities are [DPKG](https://oss.anchore.com/docs/capabilities/dpkg/),
[Python](https://oss.anchore.com/docs/capabilities/python/),
[Rust](https://oss.anchore.com/docs/capabilities/rust/) and
[binary packages](https://oss.anchore.com/docs/capabilities/binary/). Documentation supports selecting
these adapters; it does not prove this artifact's coverage. A finite coverage reconciliation is an
attributable review input whose references core can check, not an assertion core can derive merely
from a hash. The native CPython/rpds execution gate remains entirely separate.

Run Grype on both exact retained SBOMs with identical resolved config and DB identity. Disable
DB auto-update, external sources and app-update checks; keep hash/age validation. No ignores,
excludes, VEX, only-fixed/only-not-fixed or severity filtering. Do not use exit status as the policy
decision. Retain matches, related vulnerabilities, match details, artifact identities, alerts and
ignored-match fields; any suppressed findings or coverage/EOL/error alert refuses this first
profile. Required matcher/feed support must be established by the actual cohort evidence. These
controls are grounded in [Grype configuration](https://oss.anchore.com/docs/reference/grype/configuration/).

Proposed deterministic vulnerability policy: reject any High/Critical or unknown/unrecognized
severity in either report; admit Negligible/Low/Medium only with the authorized review's explicit
acceptance of the complete retained finding set. No exceptions/false-positive waivers in v1. A known
affected package remains a finding regardless of fix availability. A zero-match report means only
no matches for the reconciled component identities against this exact database and tool profile;
it is not a claim of no vulnerabilities, malware or future advisories. Reviewer acceptance cannot
override a missing component, DB stale at release issuance, malformed report or the High/Critical
threshold. Later admission applies the currently provisioned allowed-release policy as well.

Database selection is finite: one Grype schema-v6 archive selected from the official distribution
for the admitted scanner, acquired and frozen before the offline run. Retain original distribution
metadata, archive SHA-256, extracted database content hash, schema/build time, raw `db status -o json`
and `db providers -o json`, plus the acquisition provenance. The
[database architecture](https://oss.anchore.com/docs/architecture/grype-db/) documents the distribution
metadata and schema separation. A matching checksum proves content identity, not trusted origin;
the reviewer must approve the acquisition evidence. Never label an arbitrary locally generated DB
as upstream. No database file is uploaded to core or opened there as SQL.

**Release-time validity recommendation:** DB build age must be at most 120 hours at each scan and
at review issuance; both scans must finish within 24 hours before issuance. Review follows scans
and inspection; DB build precedes scans, with at most five minutes clock tolerance. These are
proposed issuance thresholds, not requirements that the same publisher scan and review every day
for every later installation. Authenticate the issuance statement and its exact observations;
an authenticated timestamp records the reviewer's claim, not an independent trusted timestamp.
There is no implied timestamp service or retroactive approval of a once-unknown signer.

At each **new installation admission**, require the actual retained bytes/joins and release-time
policy to verify, plus a valid independently provisioned current trust/allowed-release policy
snapshot explicitly accepting the exact release-review digest, subject/platform and evidence
profile. Check signer authorization for that issuance and present revocation/distrust constraints;
an expired old signing credential alone neither proves revocation nor grants perpetual acceptance.
The current policy must explicitly allow historical statements where appropriate. No 24-hour age
limit is applied to the immutable scan/review at admission. Denied release/signature/profile,
expired current admission policy or replaced startup source refuses new verification. Historical
verified installations and audit records are not rewritten when admission policy changes.

The proposed companion source must therefore bind finite allowed-release/review digests, relevant
key/delegation and revocation facts, policy generation and its explicit validity interval. Its
producer/reader contract must reconcile these fields before promotion; this note adds no third
file, new source18 content or ad hoc hot-reload route. With the earlier frozen-startup design,
an authorized deployment update/recreation is required to install a changed policy snapshot.
That cost occurs on policy expiry, release addition or actual trust/risk change, not the day after
every artifact review. No universal snapshot lifetime is invented here: deployment security must
choose and disclose it, along with its update responsibility. A frozen valid snapshot is current
only relative to that provisioned policy, not an online guarantee that no revocation occurred
elsewhere. If instantaneous revocation knowledge is required, the frozen source alone is insufficient
and a separately reviewed update mechanism is a prerequisite, not an assumed feature.

Retain available provider feed identities/update metadata. DB build time does not prove every
upstream feed was current; missing required providers or reported update failure refuses issuance.
Do not manufacture missing feed timestamps. Display the actual scan/DB dates and release-time
scope when old evidence is consumed; do not label it a current vulnerability scan. Later discovered
risk may cause a trusted allowed-release policy withdrawal and separately governed active-use
action. Any periodic vulnerability-currentness requirement for qualification/runtime needs its own
producer, freshness rule and qualification/binding invalidation consumer; this profile supplies none.
Canonical maximum-seven-day qualification expiry is not proof that a new CVE scan already happens.
Historical replay checks issuance facts without rerunning tools or present admission clocks.

## 5. License review and genuine authority

The license artifact is an SPDX 2.3 JSON document validated against the
[official tagged schema](https://raw.githubusercontent.com/spdx/spdx-spec/v2.3/schemas/spdx-schema.json),
with the profile's additional completeness constraints. It is authored from actual observations
by the authorized reviewer, not emitted as an automatic permissive-license conclusion by Syft.
Use package/file SHA-256, document/package/file IDs and relationships to connect every component to
the retained inventories and license/notice texts. For bundled material, retain precise source and
supplier evidence references. Deduplicate identical text bytes by digest, not by deleting notices.

Record supplier declarations separately from the reviewer's conclusions. SPDX distinguishes
`licenseDeclared`, `licenseConcluded` and unresolved `NOASSERTION`; those are evidence semantics,
not grants of permission. See [SPDX package fields](https://spdx.github.io/spdx-spec/v2.3/package-information/).
Every runtime component needs a concluded expression or LicenseRef backed by actual text, an
attributable rationale and a disposition for notice/source-offer/redistribution obligations under
the specified local artifact-use scope. `NONE`, `NOASSERTION`, missing text, unresolved conflicting
claims or unmet obligations deny this first profile. No hard-coded list of SPDX identifiers can
decide legal compatibility by itself. A LicenseRef is an identifier, not an exemption.

The signed review binds the SPDX bytes, all referenced public evidence, reviewed use scope,
reviewer identity, actual authority basis and conclusion. Core verifies this attribution under
the independently bootstrapped release-review role and recomputes structural completeness; it
does not become a copyright lawyer or holder by validating JSON. The project review tool can
record a real holder's permission and its scope, but cannot supply that permission. Constitution
T084 project LICENSE/public release approval remains a separate holder decision. Local restricted
verification need not assert public redistribution permission; if local use authority itself is
absent, even that positive review is blocked. Nothing here grants publication authorization.

Separate three properties, without imposing a headcount rule:

- **Trust/capability separation:** deployment security admits the release-review role outside the
  evidence-upload channel. Builder, inspector, scanner and browser-owner capabilities cannot create
  that delegation. The review-signing step is separately authorized, with no key or signing handle
  available to builder/inspector/scanner processes. A maintainer may operate all these workflows;
  uploading their public key alongside a release still cannot create trust in a receiving instance.
- **Verification-execution independence:** a fresh inspector invocation reopens original immutable
  inputs and final image bytes, recomputes R1 reports and reruns the pinned scanning workflow without
  consuming builder success flags or cached expected results. Distinct invocation/evidence boundaries
  are required; distinct computers or people are not. Merely choosing a second key does not supply
  this independent execution or fill missing evidence.
- **Attributable judgment:** the authorized maintainer/reviewer makes the source-origin, license/
  obligations and allowed-low/medium-findings decisions over the actual retained material. Record
  their identity, capacity and authority basis. Competence/accountability are review responsibilities,
  not a fictitious credential check that core can infer. The same person may be assembler and
  reviewer, or an authorized signer may sign an accountable review produced by their organization.

The same natural person can also own a self-hosted instance; trust there must still be provisioned
through the separate deployment authority path, not owner upload. Core authenticates delegation,
bytes and statements; it cannot establish human diligence or organizational independence from a
signature. Two-person review can be a stricter deployment policy, but is not a canonical prerequisite
or this minimal profile's default. This admits ordinary small OSS maintainer workflows at the cost
of less protection against a dishonest sole maintainer; independently provisioned recipient trust,
raw evidence, fresh verification execution and recipient policy checks remain mandatory. No new
scanner/builder approval roots or real release authority are approved by this note.

## 6. Retention, caps, graph joins and reproduction

Keep upstream raw JSON bytes unchanged and content-addressed. Grype JSON includes numeric
CVSS/risk values; do not force it through ADR-008's float-free project-wire codec, round findings,
or replace it with a summary. Use a bounded external-format parser, reject duplicate keys,
non-finite numbers, invalid UTF-8 and unresolved decision-bearing fields. Put only digest/length/
format/identity references and deterministic policy results in project-canonical records. The
[Grype JSON guide](https://oss.anchore.com/docs/guides/vulnerability/json/) describes the actual
finding structure. This is a new external-evidence codec seam, not an ADR-008 reinterpretation.

Proposed selected-platform import caps: Syft raw JSON 8 MiB; each of two Grype documents 8 MiB;
SPDX review 4 MiB; license/notice public support bytes 8 MiB total; provenance 256 KiB; signed
review 256 KiB; all other metadata/log/public-origin evidence 4 MiB. **Entire packet, including
the R1 reports, at most 48 MiB**; at most 128 logical public objects, JSON depth64, 262144 total
JSON members/items per document, individual text string at most1 MiB. These are explicit refusal
limits, not measured artifact sizes. They replace neither R1's separate archive/tree limits nor
the store's total graph cap. Raw objects may need a reviewed chunked-blob representation; do not
infer existing record/string caps can already hold them.

Before promotion/real-positive acceptance, measure complete actual reports and the full existing
stage/candidate/source plus proposed evidence graph against all caps, including the existing
64 MiB graph budget. R1's 8192 filesystem rows/1 MiB report may fail before these larger caps help.
Do not truncate reports, remove findings/license text, inline large reports into a small canonical
record, or silently raise caps. A concrete measured incompatibility needs a narrow reviewed cap/
carrier correction. Real report sizes have not been established by this task or by toy fixtures.

Public core graph joins are exact: candidate/descriptor -> ProviderLineage -> selected manifest,
config, ordered layers, BuildIdentity, recipe/source/dependency reports -> actual selected filesystem
report; release review -> those identities plus raw provenance/SBOMs/scans/license material/cohort/
DB metadata -> exact profile/policy and reviewer delegation. Each scan's invocation binds input
SBOM byte digest because its JSON source metadata alone is not a reliable input-byte receipt.
Every match artifact must resolve to the corresponding SBOM identity. Every reviewed component/
license reference must resolve; report substitution across platforms, candidates or DBs refuses.
Private original inputs are attested external dependencies, not falsely presented as retained core
blobs. No core fetch follows their origin URLs. Source18 and original topology identities do not change.

The outer review is downstream of all observations, so no self-hash or image-to-review-to-image
cycle is introduced. It need not contain an instance stage ID: core joins its immutable release
subject to the exact current stage under the owner command. Different stage/instance authority
cannot be inferred from release reuse. Planned post45 verification-history and B-current-verified-
descendant joins remain exactly the coordinated future change described in the installation-boundary
proposal; this document supplies no v6 SQL, second registry, weakened head check or new C authority.

Reproduction requires retained original inputs, wrapper/tool/config bytes and the exact DB archive
outside core. Compare reproduced selected OCI digests, R1 report bytes and normalized full package/
finding sets. Preserve both runs' raw reports; invocation timestamps or source-path metadata can
differ, so do not falsely demand whole-report byte equality or discard the original. No claim of
bit-reproducible upstream base/wheel builds follows from reproducible assembly. Core historical
replay checks retained evidence and issuance policy without executing tools or needing private
original inputs; that is audit replay, not independently repeating the release investigation.

## 7. What can advance offline, and what genuinely cannot

After a separately reviewed contract, code can safely implement the real R1 producer/inspector,
observation wrapper, pinned-format readers, inventory/subject joins, deterministic policy evaluator,
review authoring validator, retained public-evidence intake and the connected existing-store
installation transition. Controlled bytes can exercise those production seams and failure paths;
real format fixtures can exercise adapters once lawfully obtained. No production API accepts a
test-only success flag. Until real cohort inputs are available, do not report the scanner runner,
coverage reconciliation, report-size fit or actual release as validated. This is useful connected
offline engineering, but not a substitute positive release or a supported native profile.

The real acceptance gate requires the actual pinned base and eight wheel archives, accepted45
source closure and original-input finalization; exact scanner binaries/config/schema and DB cohort;
source/supplier evidence for all bundled components (especially rpds); full reports that fit;
authorized accountable release review (which may be by the assembler); lawful use/required
copyright-holder decisions; separately provisioned release-review trust. None is supplied or newly
authorized here. If a required supplier
inventory/build link cannot be obtained for frozen bytes, this particular real profile remains
blocked. The remedy is a separately approved input/profile decision, never signing over the absence.
Native collector enrollment, runtime-release approval, keys, real platform execution, live permission
and paid/provider calls remain later qualification blockers, not prerequisites for coding this seam.

Alternatives ruled out: (1) signature over five pass flags loses raw facts and coverage; (2) Syft/
Grype alone cannot grant license permission or establish source origin; (3) final-image packages
alone miss potentially bundled components; (4) a second scanner/license engine adds policy/version
surface without resolving absent source or authority; (5) fresh online scanning inside core crosses
the immutable/public-evidence boundary; (6) full Q1/native enrollment first unnecessarily blocks
artifact-only code development. Recommend this single two-inventory/one-review profile, with the
listed genuine input/authority gates left visibly unfulfilled until actual evidence exists.

## 8. Ordinary maintainer-to-user distribution path

1. The authorized maintainer's release workflow builds/inspects exact artifacts, produces the raw
   reports and SPDX review, makes the attributable decisions, and signs one immutable release
   packet. The same person may assemble and review, using the separated execution/signing steps.
   The packet can be distributed with the approved product release to many users over time.
2. The independently trusted product/deployment distribution supplies the allowed release and
   signer policy, stages the digest-pinned image and provides the instance-specific operator receipt
   through its supported installation/update workflow. It does not trust roots from a candidate
   upload. Actual staging remains outside core under ADR-014; this is a distribution dependency,
   not permission for browser/core OCI downloads or an assertion that setup is already implemented.
3. The ordinary user chooses the already offered/staged release in the product UI. Core consumes
   its public signed packet, validates current admission policy and the byte/evidence/stage joins,
   and reports artifact verification separately from qualification/activation. The user need not
   author a scan, SPDX conclusion or license attestation, hold a release key, or run a CLI command.
   If the trusted deployment workflow has not staged the release or supplied current policy, UI
   reports that missing prerequisite; it cannot turn the user into a release authority to proceed.

Thus no next-day publisher re-review or user-authored evidence is required. A later withdrawal/new
release can require a supported deployment-policy update; the current frozen-source proposal cannot
promise seamless live updates. Completing that product distribution/setup experience remains future
work, not a claim that the docs-only proposal already delivers end-user installation.

## 9. Canonical constraints versus delegated recommendations

| Decision | Authority/status and consequence |
| --- | --- |
| Separate immutable installation from expiring/current qualification and binding | Binding canonical `contracts/runtime.md:223–237` and `decisions.md` ADR-014 (especially 595–599). Neither daily human release review nor daily installation evidence expiry appears there. Preserve verified history as qualifications expire. |
| Operator staging, authorized signatures, no executable owner-import/core download, browser product | Binding canonical runtime extension matrix and ADR-014 staging/product boundaries. Uploaded evidence cannot supply its own authority. The exact new release trust source remains a proposed mechanism, not an existing canonical source. |
| Genuine license/source evidence; copyright-holder publication approval | Canonical scope/constitution and `decisions.md:668–670` preserve these obligations. SPDX parsing and an authorized reviewer cannot grant rights they do not possess. |
| Named scanner/schema cohort, two inventories/scans, four third-party ecosystem classes and source coverage rules | Delegated proposed engineering choice to make observations finite and testable. No canonical requirement names Syft/Grype or mandates this exact coverage mechanism; real-input feasibility remains a gate. |
| High/Critical/unknown refusal, no waivers; license completeness rules; 120-hour DB/24-hour scan-to-issuance/five-minute tolerance | Proposed profile policy, not canonical constants. Conservative and reproducible, but can reject a usable release; changing them needs explicit profile review rather than false citation to canonical requirements. |
| Current finite allowed-release policy, historical-signer acceptance and revocation semantics | Proposed minimal admission design under canonical trust separation. Snapshot lifetime/update operations need an explicit deployment contract; instantaneous revocation is not provided by a frozen root. |
| Fresh verification execution and separated signing capability, but no compulsory second natural person | Proposed minimal assurance implementation. Canonical documents require honest evidence/authority boundaries, not a two-person rule. Stricter organizations may impose one through their own policy. |
| 48 MiB packet/report caps, bounded external JSON codecs and fixed retained graph joins | Proposed resource/implementation design. It must fit actual reports and the existing store graph; it is not evidence that real artifacts already fit. |

No delegated recommendation in this note is promoted simply because it uses “require” or “deny”:
those words specify the proposed profile's behavior if later approved. No real trust establishment,
human approval, download, scan, key use, publication or deployment change is authorized here.

## 10. Amendment history — release reuse and assurance separation

**2026-09-20 initial proposal (304 lines before this amendment):** §4 required scans and review
within 24 hours of each fresh installation, with DB age 120 hours at admission. §5 required a reviewer
distinct from the assembly author/runner and browser uploader. The intent was bounded currentness
and protection against builder self-assertion; neither rule was traced to a canonical daily-review
or two-person requirement.

**2026-09-20 revision:** move scanner/DB age gates to release issuance, retain authentic raw evidence
and present independently provisioned allowed-release/trust/revocation policy at admission, and
separate capability/execution independence from natural-person identity. Ordinary maintainers can
publish one attributable reviewed artifact for later users; immutable source/scan/license evidence
does not become a claim about today's vulnerability landscape. This follows the canonical
installation/qualification lifecycle distinction instead of importing qualification expiry into
artifact review.

**Costs retained explicitly:** old release scans may omit later advisories; a frozen policy cannot
learn unprovisioned revocations; policy withdrawal/expiry may need authorized deployment recreation;
a sole maintainer offers less organizational separation than two-person review. These require honest
scope disclosure and a real policy/update responsibility, not stronger-sounding signatures. The raw
evidence, original `input_root`, bundled-component coverage, real report-fit, authorized use/holder
decisions and independent trust-provisioning gates remain unchanged. No downstream advisory,
canonical contract or product file is amended by this revision.
