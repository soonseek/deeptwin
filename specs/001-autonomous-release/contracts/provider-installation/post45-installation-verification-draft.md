# Provider installation verification — implementation preflight draft

> **DRAFT ONLY.** Controller independent preflight follows Task45 acceptance. No execution,
> canonical promotion, T087 closure or real authority is granted. If later dispatched for native
> single-writer execution, use `superpowers:executing-plans`; no helper/reviewer dispatch or commit
> is authorized by this document. Checkboxes below describe future work, not completed tests.

**Goal:** Connect actual staged-provider history and independently provisioned release evidence
to one immutable verified installation revision2 in the existing store, with historical replay and
fresh B on its exact verified descendant.

**Architecture:** Fixed two-file public-source producer/initializer/retained loader, bounded public
evidence intake, deterministic core validation, one immediate v5-to-v6 installation-history
extension and atomic owner command/event/head transition. A separately versioned B admission arm
captures the actual current verified head while preserving its original stage subject and history.

**Tech Stack:** Existing CPython, canonical JSON, Ed25519 implementation, retained filesystem
helpers, DomainStore/SQLite writer, FastAPI owner boundary and synthetic pytest fixtures. Core adds
no scanner executable, network fetch, native collector, external database or new dependency.

**Spec:** Canonical `specs/001-autonomous-release/{spec.md,data-model.md,decisions.md}` and
`contracts/{runtime.md,extension-ports.md,provider-source-production.md,provider-source-context.md,
provider-receipt-consumption.md,provider-conformance.md}`. Architectural inputs are the three
same-directory post45 proposals listed below; they remain advisory, not canonical authority.

## Status and exact reading baseline

**Historical checkpoint, before Task45 acceptance (2026-09-20):** Task43/44 are accepted.
Controller reports Task45 R4 scoped-review clean; full72 finished
13 failed/2915 passed/1 warning in3137.65s and all773 R4 bytes were verified. R5 is active on four
test-only paths: eleven old catalog-last assumptions, one stale28-versus35 route count and one
worker final-identify timing fixture. Four matched vectors can coexist with final-identify deadline/
zero frames; the R5 full-capture/six-completion precondition is not a product relaxation. Task45 is
NOT accepted. Only read-only source/document inspection was performed here; no product/test
execution or edits. Whole-product estimate remains50%±5.

**Preflight R1 current status:** that paragraph records the earlier checkpoint, not the current
acceptance gate. Controller has accepted Task45 R5 at773-path manifest
`d6cc1b4460d37b4cc0789c52e6e90b9a002c931f6796c8a51fa251c364b89ba6`; no production bytes changed
since R4. No fresh all-green72 result is asserted. Independent installation preflight subsequently
found F1–F4; this revision resolves their contract/scope/sequence issues for controller re-review.
The prior frozen drafts are preserved in installation-preflight-r1-before/. No product dispatch
or canonical promotion follows from acceptance of Task45 alone.

| Exact input | SHA-256 |
| --- | --- |
| `contracts/provider-conformance.md` | `d0b7998c67645512c13755a2aecfc60b40f48e48eaeea8a7781bb0eb3f28e16f` |
| `.superpowers/sdd/resumption-plan/task-45-r4-candidate.sha256` (773-path manifest) | `398e305c820851ae2a46b4f0cab33206119de0f8ad53157c66905c74a2655e8d` |
| `post45-installation-boundary-proposal.md` | `fed372d8c2cb1cb9c70b172cc6623e42b17c31e07c57513611916aa0aae71d6b` |
| `post45-release-evidence-profile-proposal.md` (amended) | `bd0e3c2af17882c3193e13edfd61b46928830fbe847c01e1df02336c12517dab` |
| `post45-release-source-contract-outline.md` | `8974ed3456a513976390cb6db7d1a90336face63e3da276966092e4b60d52f10` |
| `app/deployment/prepare_storage.py` | `aa00f60fa72baac2cbaaca0218bcdd9825707e515ab12b42598d92d693a8e1d8` |
| `app/deployment/prepare_records.py` | `1a28a688c44fe17f463b9a8f2313917668d7316fbbcef483e56a0aa6c02641ca` |
| frozen `app/extensions/provider_conformance_resolver.py` | `72a866232ad2daaf2247898a41c7cfc9a48af2b1fc4dad78a02913cceee3231b` |

The current B contract differs from the earlier3e80 snapshot through the documented §10 fixture
amendment; this draft does not reinterpret that as installation-verification authority. Frozen B
and shared interfaces were read with controller permission, not modified or independently tested.

**Preflight readiness:** storage/source/B decisions below are concrete recommendations. Controller
selected the dedicated48 MiB carrier direction with the mandatory conditions now incorporated in
§4; this is not measured real-release support. The new `post45-release-adapter-contract-draft.md`
closes G1 for a finite project envelope/map/SPDX/finding/provenance/native config/DB/layer subset,
including its incorporated exact Grype source table and explicit Syft subset. §11 separates that
draft-level offline contract closure from real-evidence and acceptance gates. Implementation remains
gated on controller independent installation preflight and exact accepted-base confirmation; no success callback or signed pass
map may substitute for the evaluator.

## Global constraints

- Canonical installation, qualification and binding remain separate. Verified artifact history
  survives qualification expiry; canonical qualification expiry is at most seven days.
- Only one existing provider stage1 -> one verified2 successor. Existing tool stages are unchanged.
  No replacement, uninstall, retirement, new topology/source18 epoch, second registry or new kind.
- No receipt key, IPC HMAC, candidate upload, B match or repository origin grants release trust.
- Raw immutable evidence is retained. No claimed scan pass, expected inspector dictionary,
  fabricated production key/cohort, unsupported-profile success or self-authorizing uploaded root.
- Release-time scan/DB freshness is separate from current independently provisioned admission
  policy. No daily human artifact re-review. No claim that an old scan reflects current CVEs.
- Maintainer may assemble and review. Separate verification execution and signing capabilities;
  two different natural persons are not a default prerequisite.
- Preserve every old record/blob/edge/event/reply/hash namespace and old migration C1–C5.
  Same store, owner, source18 and writer; no recursive journal verification or lock-order inversion.
- Ordinary users select an offered release in the browser. Trusted deployment supplies staging,
  evidence delivery and public trust. No user-authored source/signature/scan/CLI setup wizard.
- Native qualification, binding, provider credentials/model calls, runtime image downloads, paid
  calls, publication and real deployment/security changes remain outside this slice.

## Review focus

1. A new verified head must not invalidate historical stage/B/consumption/inventory proofs.
2. An internally consistent signed packet with missing originals, incomplete component coverage or
   wrong source/profile cannot become a substitute for real release evidence.
3. A source change or stage-to-verified race during B must freeze an incomplete result, not rebase
   the captured admission or lose source-less replay.
4. Migration failure, foreign-key oddities and graph/packet limits must preserve typed old rows,
   rowids, replies, references and current heads without partial authority.
5. Large evidence intake must authenticate before reading it, remain bounded, and leave no verified
   record/event/head on interruption; no old route acquires its larger body limit.

## 1. Selected decisions and dependency order

`accepted45 + controller approval of adapter appendix -> source bytes/retention + public packet codecs ->
v6 composed historical/current installation verification -> owner HTTP commit -> descendant B ->
full replay/race/export regression evidence -> controller preflight/acceptance`.

Source, migration, consumer and B changes are ONE coordinated ownership unit: accepting only a
source factory or a parser is not completion. Real R1 OCI production/scanner runs/release signing
remain external release-producer prerequisites; implementing those entire build pipelines is not
smuggled into this core installation slice. The release-source renderer/initializer is implemented
here. Core's public packet intake is its actual downstream evidence consumer.

No B result is required merely to verify immutable artifact release evidence. B is an independent
conformance evidence producer and future C dependency. Its current-stage restriction must nevertheless
be coordinated here so a verified installation is not permanently unable to obtain fresh B.

Alternatives: full Q1/native bootstrap first adds absent enrollment authority without helping this
artifact transition; reject. Replacing B's old subject in place corrupts historical meanings; reject.
A new B registry duplicates control/recovery/ownership; reject. Explicit new B admission variants
in its current family preserve the exact stage index without hiding the verified identity; select §7.

## 2. Precise prospective ownership

All paths below are exact proposed scope, not permission to edit now. App paths are repository
relative. No unspecified “related files.” Canonical promotion belongs to controller after preflight.
Any additional path need stops this draft's scope rather than being silently absorbed.

| New path | Responsibility |
| --- | --- |
| `app/deployment/installation_release_contracts.py` | Two closed source codecs/policy rules, exact §3.1 evidence-policy bytes/digest functions, and fixed recipe/layout constants. |
| `app/deployment/installation_release_render.py` | Pure outer renderer preserving exact original provider expansion. |
| `app/deployment/installation_release_sources.py` | Actual retained two-file source, borrowed source18, whole-read/currentness/lifetime guards. |
| `app/deployment/installation_release_schema_exports.py` | Three schemas: trust, context and outer expansion record. |
| `app/operations/installation_release_init.py` | Fixed-root no-replace initializer; independent recomputation and exhaustive ownership. |
| `app/operations/_installation_release_init_files.py` | Private fixed two-file publication only, not a generic filesystem framework. |
| `deploy/security/installation-release-source-recipe-v1.json` | Exact code-owned source recipe identity, no invented image hash. |
| `app/extensions/provider_installation_contracts.py` | Closed command/header, packet roles, review-envelope projections, reply and verified2 value. |
| `app/extensions/provider_installation_evidence.py` | Bounded external-format parsing, raw observations/subject/license/cohort joins and deterministic release-policy evaluation; gated by §11. |
| `app/extensions/provider_installation_records.py` | Same-store verified2 creation/replay and composed history arm, no standalone journal. |
| `app/extensions/provider_installation_service.py` | Exact owner/source associations, authentication, preseal/final writer/CAS/read. |
| `app/extensions/provider_installation_schema_exports.py` | Command header, verified2 record, reply and review-envelope structural exports. |
| `app/api/provider_installation.py` | Two browser routes/factory and bounded binary-envelope reception. |
| `app/api/route_contributions/provider-installation-v1.json` | Exactly execute/read declarations, browser_session scopes. |
| `app/tests/installation_release_fixture.py` | Real temporary source trees and raw source inputs; explicitly simulated native/mount samples. |
| `app/tests/provider_installation_fixture.py` | Actual temp owner/store/stage/B/app fixture; ephemeral test-only signer; retained public evidence fixture construction. |
| `app/tests/test_installation_release_contracts.py` | Closed codecs, schema parity and source-policy vectors. |
| `app/tests/test_installation_release_render.py` | Actual old-render projection, collisions and recipe/pin joins. |
| `app/tests/test_installation_release_sources.py` | Actual retained reader, cross-root aliases/currentness/lifetime. |
| `app/tests/test_installation_release_init.py` | Fixed publication and partial-root/refusal/crash ownership. |
| `app/tests/test_provider_installation_contracts.py` | Packet/record/reply/envelope/domain/export vectors. |
| `app/tests/test_provider_installation_evidence.py` | Actual bounded raw parser/graph/policy evaluation, not mock pass callbacks. |
| `app/tests/test_provider_installation_storage.py` | Immediate v5-v6 migration, corruption, row/hash/FK/event inventory and rollback. |
| `app/tests/test_provider_installation_service.py` | Real owner/stage/source/evidence -> verified2/event/head/replay. |
| `app/tests/test_provider_installation_api.py` | Real authenticated binary upload/read composition, boundaries and no CLI path. |
| `app/tests/test_provider_installation_lifecycle.py` | Acquisition, cancellation, source/head races, preseal and commit failures. |
| `app/tests/test_provider_conformance_verified.py` | Explicit descendant command/intents/reports/recovery/currentness plus unchanged legacy B. |
| `schemas/v2/deployment/installation-release-trust-v1.schema.json` | Exact first file. |
| `schemas/v2/deployment/installation-release-context-v1.schema.json` | Exact second file. |
| `schemas/v2/deployment/installation-release-expansion-v1.schema.json` | Outer expansion identity/projection. |
| `schemas/v2/extensions/provider-installation-input-v1.schema.json` | Canonical packet header, not the binary/raw report encoding. |
| `schemas/v2/extensions/provider-installation-reply-v1.schema.json` | Frozen success/read reply. |
| `schemas/v2/extensions/provider-installation-record-v2.schema.json` | Exact verified2 domain envelope. |
| `schemas/v2/extensions/provider-release-review-v1.schema.json` | Signed review-envelope grammar after §11 closure. |

| Modified path | Exact permitted delta |
| --- | --- |
| `app/deployment/prepare_storage.py` | Literal immediate v6 extension/migration, composed installation head acceptance, one verification table, bounds/digest/CAS arm. Old layouts/checksums unchanged. |
| `app/deployment/prepare_records.py` | Install v6 after v5; separate historical stage loading/current-head composition, kind-version inventory/bounds. |
| `app/deployment/provider_receipt_records.py` | Provider historical stage loader no longer independently assumes current head=stage; preserve all stage evidence/event/consumption predicates. |
| `app/deployment/prepare_service.py` | Read-only exact-writer verification/descendant resolver delegates; no broader command behavior. |
| `app/deployment/source_common.py` | Add exactly new source root to finite optional-root alias observations; old shape/behavior preserved. |
| `app/api/deployment_prepare.py` | Append one frozen startup pin; own/export new optional source borrowing existing provider source. Old services unchanged. |
| `app/api/first_party_catalog.py` | New source export and one installation contribution; existing B dependencies stay same. |
| `app/api/web_boundary.py` | Exact new family early auth/lock/binary body receive/error dispatch and new B command parser arm. Old route limits/auth unchanged. |
| `app/domain/extension_installation.py` | Add verified2-only branch,64 KiB body cap for that branch; old8 KiB stage validators unchanged. |
| `app/domain/schema_exports.py` | Add verified2 installation branch; old branches byte-identical. |
| `schemas/v1/domain-envelopes.schema.json` | Regenerate only installation verified2 and descendant B body branches. |
| `app/extensions/provider_conformance_contracts.py` | Explicit new command/reply/admission values; old subject/old parsers unchanged branches. |
| `app/extensions/provider_conformance_resolver.py` | Historical stage subject remains exact; new actual-current verified admission resolver/guard. |
| `app/extensions/provider_conformance_records.py` | Explicit new intent/report history and graph checks; old record/reply/raw comparison retained. |
| `app/extensions/provider_conformance_service.py` | New arm creation/guard/finalization/recovery with exact staged index and verified admission. |
| `app/extensions/provider_conformance_schema_exports.py` | Add explicit new command/body/reply variants. |
| `app/domain/provider_conformance.py` | Exact variant-dependent validators/parents, no loosening old21-field subject. |
| `app/api/provider_conformance.py` | New command preflight and reply variant support on same routes,4096/8192 limits retained. |
| `schemas/v2/extensions/provider-conformance-input-v1.schema.json` | Add new explicit command arm, preserve old arm exactly. |
| `schemas/v2/extensions/provider-conformance-reply-v1.schema.json` | Add new explicit reply arm, preserve old arm exactly. |
| `schemas/v2/extensions/provider-conformance-record-v1.schema.json` | Add explicit descendant content schemas under unchanged entity header versions1/2. |
| `app/tests/test_first_party.py` | Exact two-route addition with old assertions preserved. |
| `app/tests/test_provider_source_startup.py` | New optional-source/export/ownership cases and two-route count addition; preserve accepted45 fixture cases. |
| `app/tests/test_web_owner_integration.py` | Phase C current composition only:37 routes/eight contributions, append exact installation execute/read route IDs; preserve previous35 routes/order and all owner cleanup assertions. |
| `app/tests/test_deployment_receipt_migration.py` | Phase C ordinary successful constructor ends at C1–C6/SHAPE_V6; preserve literal C1–C5 and old row/type/rowid/event/reply snapshots. |
| `app/tests/test_deployment_journal_v3_migration.py` | Phase C successful current startup/layout snapshots advance to C1–C6/V6 only; historical v3/v4/v5 intermediate/failure checks stay exact. |
| `app/tests/test_provider_prepare_migration.py` | Phase C successful current reopen/layout expects V6; preserve old data, rollback and intermediate migration assertions. |
| `app/tests/test_provider_receipt_migration.py` | Phase C successful current reopen/layout expects V6; preserve deliberate V5 semantic-failure checkpoint and its [V4,V5] observations/rollback exactly. |

No DomainStore, EntityKind, events.py/event-metadata, B SQL/storage, worker/client/vector/schema,
provider source18/renderer, old locks, topology or native files are owned. `extension.verified`
already exists with extension_kind/trust_tier/revision metadata; reuse that event contract.
The global export command may emit other files; all unowned emitted bytes must remain identical.

## 3. Public source vertical (closed source contract by exact reference)

Adopt all closed field/type/bound tables of the exact hashed source outline §§2–4 without change:
root `/run/deeptwin/installation-release-sources`, two files16/8 KiB, aggregate24 KiB,0..4 keys,
0..1 exact allowed review, three0..16 deny arrays, deny wins, current snapshot interval, historical
issuance-key intervals, old instance/origin/topology/platform/context/geometry joins. No field comes
from owner payload. No source signature is its own root; deployment pin/provisioning supplies trust.
The outline's formerly deferred policy-byte identity is resolved by §3.1; no source field is added.

Proposed exact callable interfaces, all values immutable unless an API dict is explicitly returned:

```python
parse_release_trust(raw: bytes) -> ReleaseTrust
parse_release_context(raw: bytes) -> ReleaseContext
validate_release_sources(files: tuple[tuple[str, bytes], ...], *,
                         provider_files: tuple[tuple[str, bytes], ...], profile: OriginProfile) -> None
render_installation_release_sources(*, base_compose_bytes, base_service_ids_bytes,
    original_prepare_recipe_bytes, original_prepare_instance_bytes,
    original_receipt_recipe_bytes, original_receipt_instance_bytes, original_trust_bytes,
    provider_recipe_bytes, provider_instance_bytes, provider_trust_bytes,
    release_trust_bytes: bytes, initializer_image: str) -> InstallationReleaseArtifacts
initialize_installation_release_sources() -> dict
open_installation_release_sources(*, profile: OriginProfile, context_sha256: str,
    provider_source_context: ProviderSourceContext, protected_roots: tuple[Path, ...]) -> InstallationReleaseSource
InstallationReleaseSource.read_current() -> tuple[tuple[str, bytes], ...]
InstallationReleaseSource.recheck_current() -> None
InstallationReleaseSource.close() -> None
```

`ReleaseTrust`/`ReleaseContext` hold exact canonical content_bytes and return detached as_dict;
no public constructors. `InstallationReleaseArtifacts` fields are `provider_artifacts`,
`bundle_files` (exact ordered two), `context_sha256`, `expanded_compose_bytes`,
`expansion_record_bytes`. Initializer reply is exactly `{context_sha256:H}`.

Expansion record is closed `{schema_version:"installation-release-expansion-v1",
recipe_id:"installation-release-source-recipe-v1",original_expansion:S(1048576),
release_context:S(8192),release_trust:S(16384),expanded_compose:S(1048576)}`; no self digest.
Source recipe is closed `{schema_version:"installation-release-source-recipe-v1",
renderer_id:"installation-release-render-v1",initializer_id:"installation-release-init-v1",
layout_id:"installation-release-source-layout-v1",file_count:2,aggregate_bytes_max:24576}`.
Fixed filenames/metadata and allowed additions are code-owned. New volume/init service/configs,
control read-only mount/pin/dependency are stripped to recover old expansion. Runtime never uses
the expansion record as evidence that an image was built or a root was approved.

Register `DEEPTWIN_INSTALLATION_RELEASE_CONTEXT_SHA256` after existing startup keys and export
`installation-release.source-context`. Fixed source inputs use the initializer's declared config
mounts; no path parameters/fallback discovery. Borrowed source18 is never closed by the new source;
every new owned FD/parent/mount observation is closed attempt-all with primary exception preserved.
Opening failure exports None while old services/historical reads remain usable. Actual optional-root
alias checks must operate in both reader directions, including same-byte inode and nested-overlay
changes. No fake native platform is admitted by production.

### 3.1 Closed code-owned evidence-policy bytes (F2)

`app/deployment/installation_release_contracts.py` owns exactly the following object. Produce its
bytes with existing canonical_json: sorted UTF-8 keys, compact separators, no final newline;
no Markdown/source-file/recipe hash and no external input. This is a versioned interpretation
contract with concrete codec/tool/coverage/time/limit choices, not merely a version-marker digest.
All omitted fields are forbidden. New semantics, including a different selected native projection,
require a reviewed policy_revision and interpretation ID change, not an uploaded override.

```python
def installation_evidence_policy_bytes() -> bytes:
    return canonical_json({
        "schema_version": "provider-installation-evidence-policy-v1",
        "policy_revision": 1,
        "review_profile_id": "provider-artifact-review-v1",
        "interpretation_id": "provider-release-adapter-preflight-r1-v1",
        "review": {
            "envelope": "provider-release-review-envelope-v1",
            "payload": "provider-release-review-v1",
            "algorithm": "ed25519",
            "signature_prefix": "deeptwin:provider-release-review:v1\n",
            "scope": "local-artifact-use-only",
            "trust": "independent-current-exact-allow-deny-wins-v1",
            "role": "provider_artifact_review",
        },
        "codecs": {
            "canonical": "domain-canonical-v1",
            "canonical_max_bytes": 1048576,
            "canonical_max_depth": 32,
            "canonical_max_recursive_items": 10000,
            "canonical_max_string_bytes": 65536,
            "raw": "provider-external-json-v1",
            "raw_max_depth": 64,
            "raw_max_members_elements": 262144,
            "raw_max_string_bytes": 1048576,
            "raw_max_numeric_token_bytes": 128,
            "raw_max_significant_digits": 64,
            "raw_min_exponent": -308,
            "raw_max_exponent": 308,
            "embedded_oci_max_bytes": 262144,
        },
        "carrier": {
            "codec": "provider-installation-binary-v1",
            "max_raw_bytes": 50331648,
            "max_header_bytes": 32768,
            "max_objects": 128,
            "receive_deadline_ms": 60000,
            "max_scan_bytes": 8388608,
            "max_image_sbom_bytes": 8388608,
            "max_spdx_bytes": 4194304,
            "max_review_bytes": 262144,
            "max_provenance_bytes": 262144,
            "max_map_bytes": 1048576,
            "max_metadata_total_bytes": 4194304,
            "max_license_total_bytes": 8388608,
            "max_source_report_bytes": 262144,
            "max_dependency_report_bytes": 262144,
            "max_filesystem_report_bytes": 1048576,
        },
        "native": {
            "syft_version": "1.42.3",
            "syft_schema_version": "16.1.3",
            "syft_projection": "syft-five-cataloger-audit-v1",
            "catalogers": ["binary-classifier-cataloger", "dpkg-db-cataloger",
                           "file-digest-cataloger", "file-metadata-cataloger",
                           "python-installed-package-cataloger"],
            "grype_version": "0.110.0",
            "grype_projection": "grype-mapstructure-json-db-v1",
            "db_schema_version": "6.1.4",
            "layer_coordinates": "config-diff-id-v1",
            "warnings": "refuse",
            "nonwhitespace_stderr": "refuse",
            "ignored_matches": "refuse",
            "filter_overrides": "refuse",
            "unknown_decision_fields": "refuse",
        },
        "coverage": {
            "component_map": "provider-component-map-v1",
            "spdx": "spdx-2.3-closed-components-v1",
            "classes": ["debian", "python-wheel", "cpython", "rust-crate", "first-party"],
            "python_distributions_per_platform": 7,
            "first_party": "reviewed-not-cve-covered",
            "non_python_binary": "refuse",
            "license_grammar": "provider-spdx-license-subset-v1",
            "file_coverage": "exact-r1-regular-file-inverse-v1",
            "allowed_severities": ["Negligible", "Low", "Medium"],
            "finding_acceptance": "every-match-index-exact-v1",
            "feed_coverage": "attributable-origin-review-not-inferred-v1",
        },
        "issuance": {
            "scan_max_age_ms": 86400000,
            "db_max_age_ms": 432000000,
            "clock_skew_ms": 300000,
            "later_admission": "current-trust-allow-deny-not-daily-review-v1",
        },
        "provenance": {
            "statement": "https://in-toto.io/Statement/v1",
            "predicate": "https://slsa.dev/provenance/v1",
            "build_type": "urn:deeptwin:build-type:provider-r1-offline-assembly:v1",
            "projection": "r1-toolset-exact-dependencies-v1",
            "run_metadata": "signed-assertion-utc-seconds-ordered-v1",
            "r1_report_mutation": "forbidden",
            "runtime_execution_proof": "not-derived-from-source-toolset",
        },
    })


def installation_evidence_policy_sha256() -> str:
    return sha256(installation_evidence_policy_bytes()).hexdigest()
```

Import canonical_json from app.domain.refs and sha256 from hashlib; do not introduce a second
codec. The interpretation IDs refer exactly to this draft and the companion adapter's fixed
tables, including opaque-diagnostic boundaries; they do not permit runtime policy selection.
No production digest is written here: it is deterministically derived from these literal bytes.
The existing source recipe remains a distinct object with a distinct purpose/digest.

Renderer, initializer and evaluator import both functions from this one owned module. Renderer
places that digest in the context; initializer independently recomputes it while validating its
real inputs, not by copying an input context/hash. Context/source validation refuses a differing
digest. Evaluator recomputes and requires equality with context and signed Review.evidence_policy_sha256.
No caller parameter, uploaded policy object, environment override or mutable dict supplies policy.
These exported pure byte/digest functions are the inspection/fixture interface; no fourth public
source file, policy-upload route or additional schema export is introduced.

Phase A contract fixture compares decoded bytes to an independently written exact literal object
above, checks canonical reserialization, calls twice, and verifies SHA-256 equality. Renderer and
real initializer outputs must carry that digest and byte-identical context; source tests reject an
otherwise well-formed foreign digest. Phase B checks an exact allowlisted/re-signed foreign-policy
review is refused, while matching source/review/code values pass evaluation. Phase C proves the
same mismatch cannot create an authority row/head/event. Mutating a detached decoded fixture dict
must not change subsequent policy bytes. No test asserts a guessed real-release hash.

## 4. Public evidence command and raw carrier

H/U/T/EntityRef/BlobRef retain existing domain meanings; source types use §3. All project JSON
is canonical. Large upstream JSON remains raw bytes under a separate bounded external parser; it
must not pass through the domain's float-free1 MiB JSON codec. Default DomainStore blob cap is
16 MiB; selected individual report cap is8 MiB, so **no generic blob-limit or chunk registry change**.

Routes: `POST /api/v1/extensions/provider-installation`,
`GET|HEAD /api/v1/extensions/provider-installation/{command_id}`. Session/origin/CSRF/scope rules
are the existing owner boundary; no queries or content-encoding. GET/HEAD body must be empty.

Controller-selected design direction: a finite binary envelope for POST, without base64/string
amplification or a generic upload registry. The selection and its conditions are recorded in
`post45-carrier-controller-preflight.md` (SHA-256
`ec3388c0ace7f9c55991cebf432c2142be95fe72ca009f5b778083d7c9bc9f6b`). It does not establish actual
report fit, peak memory or production throughput. Media type is
`application/vnd.deeptwin.provider-installation-v1`. First8 bytes are
ASCII `DTPIV1` followed by two zero bytes; next4 are unsigned big-endian header length1..32768;
then canonical header followed by unencoded raw objects in header order, no trailing bytes.
Content-Length must equal12+header length+sum declared sizes and be at most50364428 bytes
(48 MiB+32768+12). No archives, multipart, filenames, URLs or transparent decompression.

Closed header:

```text
{schema_version:"provider-installation-command-v1", command_id:U,
 staged_installation_ref:EntityRef(extension_installation,1),
 objects:[{role:Role,sha256:H,size_bytes:positive integer}]}   #12..128 unique digests
```

`Role` is one of `release_review`, `provenance`, `image_sbom`, `component_license_review`,
`image_scan`, `component_scan`, `source_report`, `dependency_report`, `filesystem_report`,
`cohort_manifest`, `invocation`, `license_text`, `origin_evidence`. First ten roles occur exactly
once in that order; remaining objects sort by(role,sha256); invocation occurs exactly twice;
license_text/origin_evidence occur0..116 times combined, subject to128 total. A shared identical
text object appears once; signed reference lists may reference it repeatedly. The signed review's
exact object descriptor closure excludes its own `release_review` descriptor and must equal the
header remainder: an extra harmless object is rejected, not quietly presealed.

Caps: profile's8 MiB image SBOM,8 MiB each scan,4 MiB SPDX review,256 KiB provenance/review,
8 MiB total license text,4 MiB aggregate remaining metadata/origin/invocation plus R1's256 KiB
source/dependency and1 MiB filesystem individual limits. Aggregate48 MiB wins. Header descriptors
are not trusted before all hashes/roles/actual bytes and signature policy are checked. The adapter
appendix fixes project review/cohort/map/invocation/coverage grammar and its §6 native source
table. Canonical project objects remain within
the unchanged1 MiB/depth32/10000-recursive-item/65536-byte-string limits and their smaller role caps. In
particular, the component map is <=1 MiB and10000 recursive items (including keys and containers,
exactly as refs.py counts); an8192 outer-row ceiling
does not claim8192 nested rows fit. External raw report parsing has separate bounds and decimals.

Preserve global origin/path/singleton-header checks, then exact method/family/media/length preflight.
Reject query/encoding/conflicting length/oversized declaration before allocation. Authenticate before
ANY ASGI receive, then acquire existing nonblocking process-shared `UploadLock`; contention returns
capacity without a second receiving buffer. Map its WorkServiceError into the installation error
family, never the work-material upload reply. Reuse its existing no-follow ownership checks.

Use one monotonic60-second deadline across every fragment, not per object. Parse the12-byte prefix
and bounded canonical header incrementally; validate complete role/hash/size/aggregate declarations
before collecting payloads. Handle all split/coalesced chunk boundaries, exact wire length and
incremental per-object hashes; no trailing bytes/decompression/whole-body immutable concatenation
or duplicate joined packet plus copied payloads. Real memory/throughput remains unmeasured.

The endpoint MUST await `upload_lock.publish(service.execute, ...)`, not plain run_in_threadpool.
The existing publish operation owns/shields the task and retains its FD until the actual synchronous
operation finishes. Before publish, cancellation/disconnect releases buffers/lease with no writes.
After publish starts, service verification/publication can finish and commit despite disconnect;
authenticated exact retry/read obtains the durable result. Boundary cleanup may call close but
must NOT release an in-flight lease. Attempt-all BaseException cleanup preserves this ownership
and primary errors. Do not promise physical CAS rollback. Reauthenticate in service transactions.
Only the independently authorized exact one-allowed-release closure can be presealed; internally
consistent caller hashes alone do not bound accepted orphan content. No orphan registry/cleanup
workflow is introduced. B and old candidate/deployment body limits remain unchanged.

Command identity is SHA256(canonical header); the actual object hashes make raw bytes part of that
identity. Replays must still receive a well-formed matching envelope on POST but perform no source
read, clock admission, scan, signature reevaluation or worker probe after authenticated stored
identity/actor match. GET retrieves the exact frozen reply with no upload. A changed object/hash,
actor or stage under the same command ID conflicts. Failed admission creates no verification
command/result/event/head, so an uncommitted ID may be retried with corrected input.

Successful reply is exactly `{schema_version:"provider-installation-reply-v1",command_id:U,
staged_installation_ref:EntityRef(...,1),verified_installation_ref:EntityRef(...,2),
state:"verified",revision:2,release_review_sha256:H,release_source_context_sha256:H,
verified_at_ms:T,event_cursor:existing opaque cursor,
links:{self:"/api/v1/extensions/provider-installation/"+U,events:"/api/v1/events"}}` <=8192 bytes.
POST and read return200 (including replay); route projects base_path without altering stored reply.
Errors are closed invalid_input400, unauthenticated401, access_denied403, not_found404, conflict409,
too_large413, capacity429, unavailable503; fixed non-reflective message and existing error envelope.

## 5. Service, verified record and graph

```python
parse_installation_header(raw: bytes) -> InstallationCommand
parse_installation_reply(raw: bytes) -> dict
parse_external_document(role: str, raw: bytes) -> ExternalDocument
evaluate_release(packet: ReleasePacket, *, source_files: tuple[tuple[str, bytes], ...],
                 stage: VerifiedStageView, now_ms: int) -> ReleaseAssessment
PersistentDeploymentPrepare._installation_stage_view(db, stage_ref: EntityRef) -> VerifiedStageView
PersistentProviderInstallation(domain_store, owner_authority, *, prepare_service, release_source)
  .execute(authenticated_request, packet: ReleasePacket) -> dict
  .read(authenticated_request, command_id: str) -> dict
  .rehydrate(db, installation_ref: EntityRef) -> VerifiedInstallationView
verify_installation_extensions(domain, db, roots, profile, journal) -> None
```

`ExternalDocument` retains exact content_bytes and exposes a detached parsed observation via as_dict;
only image_sbom/component_license_review/image_scan/component_scan/provenance roles are accepted.
It is structural data, never an authority verdict. `ReleasePacket` holds only received immutable
header/object bytes, not a passed flag. `VerifiedStageView`
is allocated only by the actual prepare delegate inside the exact active writer after full journal
verification, with stage record/ref, candidate/lineage bytes, current head and retained source18.
Name the already planned read-only stage delegate `_installation_stage_view`; implement its
unchanged-stage1/current-v5 path in Phase B so evaluator tests consume an actual accepted stage.
Phase C extends that same delegate to the composed v6 historical/current view; it does not create
a second resolver or allow fixtures to construct trusted views. It asserts the existing active
writer, calls the actual journal once and never starts a nested transaction or takes prepare's RLock.
`ReleaseAssessment` is private immutable evaluated data: review digest, ordered verified evidence
bytes/descriptors, release/profile/source identities and issuance evaluation facts. It has no public
constructor; service always calls the real evaluator itself and does not accept this type from
API/constructors. A Python type is not itself authority: final writer recomputes relevant joins.

Constructor requires exact DomainStore/PersistentOwnerAuthority/PersistentDeploymentPrepare and
same domain/owner associations. `release_source` is the actual startup export, borrowing exactly
prepare's `_provider_context`, or None. No alternate stores, callbacks, signature-verifier injection
or owner policy dictionary. Read-only delegates assert writer and call `_journal(db)` once without
acquiring prepare's RLock; preserve existing prepare-RLock -> writer and B writer-only ordering.

Flow: authenticate/header replay -> actual current staged graph/source/policy admission -> bounded
real packet verification -> preseal only the exact authenticated closed evidence and source bytes
using existing `put_blob` -> final writer reauthenticate/full journal/head/source/time/policy guards ->
put verified2 record -> append event -> freeze reply/insert verification row -> CAS existing head ->
full composed verification. Event precedes its referencing row because the new event FK is immediate;
all changes remain in one transaction, with no partially committed event/row/head.
No final transaction calls public `put_blob`, nested service locks or external I/O beyond existing
bounded store/source reads. A preseal failure/race may leave unreferenced CAS bytes, as with existing
evidence flows, but never authority. Since preseal happens only after an exact allowed signed closure,
arbitrary failed-upload bytes cannot be registered as evidence. The live source allows one fixed
closure; repeat races deduplicate. Changed source snapshots are an authorized deployment operation,
not an unbounded user-chosen orphan-retention namespace. Do not claim physical CAS rollback.

Fresh core time is actual wall-clock milliseconds, not caller input; require it at least the
existing deployment control clock floor and stage installed time, and in the current policy window.
Advance that existing control clock floor through its normal private CAS in the final writer.
Rollback undoes it; replay never samples or advances clocks. Do not add a separate verification clock
registry. Descendant B admission must also be at or after verified_at_ms, besides its existing B floor.

Verified record uses the SAME installation id as stage, entity kind `extension_installation`,
header version2, operational purpose, actor/current access/retention policies and timestamp=verified
time. Exact parent_refs=[stage_ref]. Closed content:

```text
{schema_version:"provider-installation-verified-v1", state:"verified", revision:2,
 stage_ref:EntityRef(extension_installation,1), previous_record_digest:H,
 extension_id:ExtensionId, extension_version:ExtensionVersion,
 platform:Platform, image_index_sha256:H, selected_manifest_sha256:H,
 service_descriptor_sha256:H, command_id:U, verified_at_ms:T,
 release_context_blob_ref:BlobRef, release_trust_blob_ref:BlobRef,
 release_source_context_sha256:H, release_review_sha256:H, evidence_policy_sha256:H,
 evidence:[{role:Role,blob_ref:BlobRef}]}   # exact header order,12..128
```

Body<=65536 bytes; stage bodies stay<=8192. `previous_record_digest==stage_ref.sha256`; all ref
ids/vault/purpose and graph identities agree. `release_source_context_sha256` is explicitly the new
release context pin; old provider source18 pin is inside that exact context and stage. No old field
name acquires a new meaning. Evidence refs are directly in content so DomainStore discovers/validates actual blobs;
do not hide BlobRefs in an opaque manifest blob and assume graph traversal checks them.

Direct unique entity edges are actor/access/retention plus stage (=4); repeated stage parent/content
refs deduplicate. Direct blobs are exactly the two sources plus the evidence descriptors, deduplicated
by full BlobRef, <=130. Compare exact computed association sets, not an upper-bound-only check.
Domain graph limits stay4096 nodes/depth256/64 MiB. No digest-only substitute for retained bytes.

Emit existing `extension.verified` with object_ref=verified2, private_evidence_refs=(verified2,),
actor=authenticated owner, status=succeeded, observed/recorded time=verified_at, correlation=command,
causation=actual historical extension.staged event, metadata exactly extension_kind=provider,
trust_tier=the candidate's checked existing tier,revision=2. One event per new verification and no
event on migration/replay/rejection. Existing public event contract is not widened.

## 6. Same-store v6 and old-history compatibility

Keep `deployment_prepare_installations` EXACTLY as stage1 acceptance index and all old request,
receipt, consumption/lifecycle/command rows unchanged. Broaden ONLY existing installation_heads
revision constraint to `revision IN (1,2)`, keeping its five columns and FKs. Add one table
`deployment_prepare_installation_verifications`, cap1, for the one provider successor/command.
It is an index of the same domain installation and command, not another installation registry.

Exact new row columns, all NOT NULL:

```text
request_id TEXT PRIMARY KEY -> deployment_prepare_provider_requests(request_id)
extension_id TEXT UNIQUE -> deployment_prepare_installations(extension_id)
vault_id TEXT; kind TEXT CHECK='extension_installation'; installation_id TEXT UNIQUE
version INTEGER CHECK=2; anchor_digest TEXT H
command_id TEXT UNIQUE U; actor_ref TEXT canonical actor EntityRef <=1024
command_json TEXT canonical header <=32768; input_digest TEXT H
reply_json TEXT canonical reply <=8192; http_status INTEGER CHECK=200
event_id TEXT UNIQUE -> api_event_envelopes(event_id)
verified_ms INTEGER T; previous_head_hash TEXT H; hash TEXT H
FOREIGN KEY(vault_id,kind,installation_id,version,anchor_digest)
 -> domain_records(vault_id,kind,id,version,sha256)
FOREIGN KEY(extension_id,request_id)
 -> deployment_prepare_installations(extension_id,request_id)
```

All H lengths64, U lengths36; extension_id uses old1..128 grammar; timestamp SQL CHECK uses T.
Scalar validation rejects bool/REAL/BLOB-for-TEXT/typed NULL independently of SQLite affinity.
No success row can exist without exact event, command/header, retained domain record and stage.
Full normalized literal DDL is assembled as `DDL_V6=(new migrations allowing1..6,
*DDL_V5[1:12],new installation_heads,*DDL_V5[13:],new verification table)`; all reused statements
remain the exact old strings. C6=H(canonical_json(list(DDL_V6))); C1–C5 literals/values unchanged.
This defines the exact construction/column constraints, not an invented precomputed checksum.

Row hash namespace remains byte-identical for every old row, including revision1 heads. Only the
new verification table and revision2 installation heads use `deployment-prepare-storage-v6` in
the existing `{namespace,table,row-without-hash}` formula. A revision2 head keeps exact extension/
request and names the verified2 record digest; it must have exactly one matching verification row.
Add a private CAS arm allowing only revision1 ->2/anchor digest replacement, checking exact prior
hash/revision/request/extension; no generic arbitrary head advance. Store previous_head_hash in the
verification row and compare it to the exact deterministic old revision1 head from stage fields.

Immediate migration requires active writer, verified exact v5 shape/C1–C5 and foreign_keys=ON.
Preflight incoming FK descriptors against the actual schema: no external FK may reference the
rebuilt migrations or installation_heads tables (none is required by the frozen B index). Reject
unexpected schemas/triggers/indexes/case aliases rather than dropping them. Snapshot all bounded
old row values/types and immediate rowids; defer FK checks, empty/drop/recreate only migrations
and installation_heads, restore exact old rows/rowids/hashes, add empty verification table/C6,
then verify full schema/data/FKs. Failure rolls back all changes under existing transaction ownership.
Do not disable foreign_keys, rename a referenced parent opportunistically or mutate C1–C5. Earlier
v1..v4 still traverse their unchanged immediate migrations, verifying each before v5->v6.

Composed journal algorithm is mandatory:

1. Validate stage inventory (<=16 stage1 records) and verified inventory (<=1 version2), total<=17;
   all other installation versions/shapes are rejected. Stage anchors keep8 KiB limit; verified2
   alone gets64 KiB. Every record must biject to its owning stage/verification row.
2. Historical provider/tool stage loaders validate ALL previous record, postcondition, receipt,
   consumption, actor/policy and event predicates, but do not equate an independently read current
   head to stage1. Remove that local assumption only in favor of the obligatory composed check.
3. For each stage derive its exact historical stage-head fields/hash. Verify actual current SQL
   head is this stage1 or, provider-only, its one complete verified2 descendant. Verify descendant
   bytes/graph/source issuance evidence/row/event/previous-head/command/reply without live sources.
4. Keep `item["installation"]` as immutable historical stage view (ref,record,anchor,row,historical
   head). Add `item["installation_current"]` with actual ref/record/head and optional verification
   row. No caller-supplied historical-head object is authority; only this full journal builds views.
5. Run existing provider preserved-inventory verification using historical stage/event-sequence
   views; unchanged old tool inventory is reproduced byte-for-byte. Count verified events separately
   from old deployment lifecycle events. Return journal only after every composed check succeeds.

No `journal -> verification -> journal` recursion: `verify_installation_extensions` receives the
already loaded private journal under writer, never calls the public prepare service. Its replay
validator parses retained source/evidence and issuance time, not current mount/key policy. New
service read/rehydrate call `_journal` once and select its already-verified result.

## 7. Explicit B variants — no ambiguous stage/verified identity

Select an **explicit new command and content/reply schemas in the existing B family**. Keep the
old21-field `ConformanceSubject` and its SHA256 meaning exactly unchanged. Keep worker capture,
suite, vectors/requester/comparator and literal oracle bytes unchanged.

| Layer | Legacy arm (unchanged) | New verified-descendant arm |
| --- | --- | --- |
| POST input | Existing `{command_id,installation_ref:stage1}` | `{schema_version:"provider-conformance-command-v2",command_id,staged_installation_ref:stage1,expected_verified_installation_ref:verified2}`. Both refs same installation id. |
| Fresh admission | Current SQL head MUST equal exact stage1 | Core resolves actual same-store verified2 descendant/current head and compares expected ref; owner cannot supply the admission object. |
| Entity header | Intent version1, report version2 | Same entity header versions1/2; new CONTENT schema IDs only, not ambiguous header version3. |
| Stage subject | Original21 fields and original context digest | Original value nested as `stage_subject`; original digest named `stage_context_sha256`. |
| New admission | Absent | `ConformanceVerifiedAdmission` below, with separate `admission_sha256`. |
| SQL index | Existing installation_* fields identify stage1 | Same fields EXPLICITLY index staged_installation_ref, never verified2; request_sha256 identifies new exact command. |
| Replay | Existing bytes, zero probe | Exact new stored bytes, zero probe; original API ID/different variant conflicts. |
| Rehydrated result | Existing stage subject/capture/comparison | New immutable result additionally exposes admission/stage/current-verified refs for future C. |

Why keep B SQL unchanged: one pending run per exact stage-derived installation id remains the right
exclusion key; both variants refer to the same immutable artifact installation lineage. The current
verified ref and head hash are authoritative **in the immutable intent**, with checked graph edges,
not silently stored under a version1 SQL ref. New/old row-to-body mappings are selected by exact
content schema, not guessed by which head exists now. B DDL/checksum/old rows therefore stay exact.
Alternative new column/index migration offers easier SQL inspection but duplicates a durable ref
and changes a second storage family without needed new cardinality. Alternative new subject digest
would force raw capture/worker-client semantics changes for unchanged artifact identity; reject.

Closed durable `ConformanceVerifiedAdmission`:

```text
{schema_version:"provider-conformance-verified-admission-v1",
 stage_subject:<exact original21-field durable projection>, stage_context_sha256:H,
 staged_installation_ref:EntityRef(extension_installation,1),
 verified_installation_ref:EntityRef(extension_installation,2),
 installation_head_hash:H, release_review_sha256:H, verification_source_context_sha256:H}
```

All refs/overlapping image/service/source/port fields are derived from actual composed journal.
`stage_subject.installation_ref==staged_installation_ref`; verified content.stage_ref equals that
ref; current head names verified2; stage_context_sha256=H(old stage_subject); admission_sha256 is
H(canonical entire NEW admission). No stage_context/admission digest alias is permitted.

New exact callable interfaces:

```python
resolve_verified_admission(prepare_service, db, staged_ref, expected_verified_ref) -> ConformanceVerifiedAdmission
require_current_verified_admission(prepare_service, db, admission, source_context) -> None
historical_verified_admission(prepare_service, db, admission_bytes: bytes) -> ConformanceVerifiedAdmission
```

Allocation only from verified journal under exact writer; private frozen runtime value also holds
the original exact ConformanceSubject with uid/gid for the unchanged requester. Historical creation
proves retained verified ancestry/event order but does not demand current live sources/head. Fresh
guard compares actual stage+verified+head hash+source18 against captured admission at every existing
B guard point and finalization. Release source is not a fresh B prerequisite: B's artifact reference
is already verified history; current qualification/trust policy remains a later C decision.

New intent content fields EXACTLY:
`schema_version="provider-conformance-intent-v2",command_id,request_sha256,
staged_installation_ref,verified_installation_ref,admission,admission_sha256,
suite_version,suite_sha256,requester_version,comparator_version,admitted_ms,deadline_ms`.
Times/constants unchanged, intent<=16384 bytes. Exact parents=(stage1,verified2). Stage subject's
candidate/request/receipt refs add the same old graph edges plus verified2:8 unique entity edges,
0 direct blobs. Old intent7 edges/8192 cap unchanged.

New report content fields EXACTLY old report fields except schema_version=`provider-conformance-report-v2`,
replace `installation_ref,context_sha256` with
`staged_installation_ref,verified_installation_ref,admission_sha256,stage_context_sha256`.
All completion/reason/vector/recovery rules remain exact. Parents=(intent1,stage1,verified2),6 unique
entity edges and0/1 observation blobs;64 KiB cap. Raw capture is compared against unchanged stage
subject; its original context hash must equal stage_context_sha256, never admission_sha256.

New reply is old reply shape with schema_version=`provider-conformance-reply-v2`, replace
installation_ref/context_sha256 with staged_installation_ref/verified_installation_ref/
stage_context_sha256/admission_sha256. State/counters/cursor/links/constants/8192 cap unchanged.
New `RehydratedVerifiedConformance` fields exactly `intent_ref,report_ref,admission,comparison,
capture_bytes`; old `RehydratedConformance` fields/type remain unchanged. Future C branches explicitly
and demands the new verified admission for fresh qualification, comparing its actual current
verified ref/head/context; no boolean `matched` shortcut or private-worker/provider-port equivalence.

Old command against a now-verified installation: exact replay succeeds source-less; a NEW legacy
command conflicts before probing. New descendant command may run after B expiry/restart. Stage->
verified during an already admitted legacy B leaves its old subject untouched, and its fresh guard
causes incomplete/source_changed (or the existing accurately observed failure), never matched by
rebasing. Recovery validates new command request digest/refs/actor using its exact variant; deadline,
one-pending semantics and durable interrupted report remain. New schema branches do not rewrite
old pending intents or terminal rows on startup.

## 8. Finite proof cases and fixture contract

Tests use actual temporary DomainStore/owner/bootstrap/source18/stage/route composition. Extend
the existing `staged_conformance_app(tmp_path,monkeypatch)` through NEW fixture code, not by changing
its accepted definition. No production verifier callback, client substitute or accepted-key default.
Tests may simulate filesystem UID/mount/native samples at the established low-level fixture seam.
Ephemeral Ed25519 test keys sign actual controlled bytes and are provisioned into actual temp source
files; test keys never enter source recipes/product defaults/real release assets.

Two lower-layer fixtures avoid forward dependencies in the phased tests. `release_source_case(request,
tmp_path,monkeypatch)` in `installation_release_fixture.py` yields `files,source_root,source_pin` using
only the source renderer/initializer/loader; its closed parameters are `valid` (default) and
`deny_empty`, P1 through P10, and foreign_policy. P parameters select only the PA source projection
below; malformed-source cases expose raw bytes for the expected parser/open refusal rather than
fabricating a successfully opened source. It does not import or instantiate the installation service or HTTP app.
`release_documents()` in `provider_installation_fixture.py` yields an immutable role-to-raw-bytes
mapping from the §11 frozen vectors; it does not open a store, instantiate a service, or evaluate
evidence. That module must keep full-app imports inside the full-app fixture, so the raw fixture
can collect independently during Phase B.
`release_evaluation_case(request,tmp_path,monkeypatch)` in that same owned fixture module yields
packet,source_files,stage,now_ms. It uses the accepted provider receipt/staging fixture and the
real `_installation_stage_view` delegate under the actual writer to obtain stage, with no new
installation service/API or factory import. It constructs real signed raw evidence and Phase A
source bytes, then calls the production evaluator directly in Phase B tests. It does not insert
verified rows/events or return an expected verdict. Its closed indirect parameters are P1 through
P10 plus valid, foreign_policy and wrong_toolset; each mutation is defined below/in the appendix.

The new pytest fixture `installation_case(request,tmp_path,monkeypatch)` yields `domain,prepare,b_service,
verification_service,client,auth_headers,stage_ref,packet,source_root,source_pin,files`. `packet` is
an actual ReleasePacket created by real codecs from explicit controlled raw evidence and a real
test signature. It contains no expected outcome. `files` maps fixed fixture evidence roles to bytes.
Fixture support methods are `post_packet(packet)->HTTP response`, `snapshot()->immutable database/
event/head/blob-ref snapshot`, `restart_without_release_source()->new actual app/client`, and
`rebuild_packet(changes:dict[role,bytes])->ReleasePacket`; rebuilding recomputes descriptors and
test signature but cannot make invalid source/coverage observations valid. The raw normalization
vectors needed for complete fixture implementation are the explicit companion appendix. Its closed indirect
parameters are `valid` (default), `deny_empty`, `high_finding`, `framed_worker`, P1 through P10,
foreign_policy and wrong_toolset; all source bytes
and allow-review hashes are prepared before real startup. `framed_worker` additionally owns the
existing real framed-worker fixture. The high-finding variant signs and allows the exact bad packet,
so its failure cannot be caused only by an allow-hash mismatch.

`snapshot()` fields are `authority` (typed journal rows/current heads/domain record refs/event bytes,
excluding unattached CAS files), `old_record_bytes` (the fixture's preexisting record bytes by ref),
`verified_refs` (all provider verified2 refs) and `verified_event_count` (actual extension.verified
events). The fixture does not implement an alternative verifier; these are bounded direct test
observations. New fixture modules explicitly import pytest, uuid4 and the named production codecs.

Required case groups (parameterize every enumerated item and each named boundary, not one
representative; the ID ranges label finite groups, not a promised collected-test count):

| IDs | Concrete setup/mutation | Required result |
| --- | --- | --- |
| S1–S6 | Correct source; missing pin; missing file; extra file; same-byte inode replacement; altered actual source18 | Correct retained export only for S1; fresh verification unavailable/closed otherwise; old service/history unaffected. |
| S7–S11 | Cross-root backing alias; nested overlay; changed mount during read; partial initializer tree; cleanup BaseException at each newly owned FD boundary | Refuse without rebasing/repair; all new resources closed and primary preserved. |
| P1–P7 | Empty allowed list; deny-over-allow by key/review/manifest; missing allow key; expired snapshot; future-invalid snapshot | No verified record/head/event; denial is not zero checks passed. |
| P8–P10 | Old review with issuance-fresh DB under current explicit allow; same review not allowed; unchanged release consumed next day | P8/P10 can verify without rescan/review; P9 refuses; reported scan date remains historical. |
| E1–E9 | Wrong signature/key/role/profile; altered raw scan with unchanged descriptor; re-signed wrong image/index/platform; missing required object | Reject before authority/extra raw storage. |
| E10–E16 | High/Critical/unknown finding; filtered/suppressed result; missing bundled component link; NOASSERTION license; wrong Grype input SBOM digest | Reject even with valid test signature; no pass-map substitute. |
| E17–E22 | Actual JSON numeric CVSS; duplicate key; nonfinite number; trailing raw bytes; individual/aggregate cap boundary; exact manifest-extra object | Valid numeric observation preserved raw; malformed/over-limit/extra closure refused. |
| H1–H8 | Foreign-key target/action/extra index/trigger/case alias; typed NULL/REAL scalar; checksum mismatch; orphan stage/verified/event; version3; duplicate successor | Full migration/journal refuses; no destructive repair. |
| H9–H12 | v5 populated provider+old tool+B rows; interruption at each migration statement; immediate rowid preservation; source-less postmigration replay | Exact old cells/hashes/events/replies preserved; rollback complete; empty new table after migration. |
| V1–V7 | Authenticated full packet; duplicate same command; changed actor/input; second verification command; concurrent CAS; source replaced after preseal; owner revoked before commit | One actual verified2/head/event; exact replay; conflicts/refusals leave authority unchanged. |
| V8–V11 | Missing/replaced actual presealed blob; complete graph exceeds64 MiB; store/commit failure; success response lost | Missing/oversize/failure closed; committed lost-response replay exact without reevaluation. |
| B1–B6 | Historical old B after verified2; new legacy B; valid new descendant B; wrong expected verified ref; stage->verified mid-old-B; wrong new admission digest/head | Old replay zero-probe; new legacy conflicts; new arm runs exact worker suite; other arms refuse/incomplete without rebase. |
| B7–B11 | New pending recovery after deadline/restart; new report/cursor corruption; same command different variant; source-less new B replay; new B after old evidence expires | Exact actor/recovery/reply/graph behavior; new fresh run possible, without issuing C/qualification. |
| A1–A7 | Missing session/CSRF/Origin before body; wrong media; compressed body; length mismatch/disconnect; oversized header/body; base_path; GET/HEAD body/query | Early auth/closed bounds, lease cleanup, exact path projection and old route limits unchanged. |
| A8–A14 | Duplicate singleton/length headers; every prefix/header/object split and multi-object chunk; exact cap/+1; total deadline across fragments; same/second-process contention; cancellation before publish; cancellation during actual owned publication | No receive before authorization; exact framing/hash closure; no second receiving buffer; prepublish no writes; publish lease retained until real thread completion, then byte-identical authenticated durable retry. |

P-group ownership is explicitly split; the table's verified-state outcomes are Phase C only:

| Case | Phase A: source syntax/projection only | Phase B: production evaluator only | Phase C: actual authority outcome |
| --- | --- | --- | --- |
| P1 empty allow | Valid closed source with empty allow; literal bytes/pin preserved | Refuses admission | No verified row/head/event |
| P2/P3/P4 deny key/review/manifest over allow | Valid closed overlapping deny+allow arrays; no claimed verdict | Each denial wins | Same authority snapshot before/after |
| P5 absent allow key | Parser/source validation refuses malformed key reference | Malformed source cannot become evaluator input via the production parse boundary | Intake unavailable/refused; no authority change |
| P6 expired/P7 not-yet-valid snapshot | Well-formed ordered intervals parse; inverted/ill-typed intervals refuse; no wall-clock admission decision | Actual chosen now_ms outside interval refuses | No verified row/head/event |
| P8 old review with issuance-fresh DB | Historical issuance interval and exact allow descriptors serialize/round-trip; no scan or result needed | Assessment succeeds using issuance-time scan/DB checks and current policy | One real verified2/head/event with historical scan dates |
| P9 same review unallowed | Empty/different exact allow is syntactically valid | Refuses even with valid signature | No authority change |
| P10 next-day consumption | Same immutable review descriptor in valid current source; no result assertion | Assessment succeeds without replacing scan/review | One real verified2/head/event on a fresh staged fixture, not replay/rescan |

Use PA/PB/PC prefixes for tests of each phase's projection of P1–P10. P5 has no fabricated
well-typed evaluator source: its PB check exercises the real source parse boundary. Source tests
must collect/pass with new service/API imports made to fail; no fake service fills that dependency.
F1 provenance and F2 policy equality/refusal tests run in B; repeat their authority refusal and
complete positive packet in C. S tests in A assert retained-source availability/cleanup, not
verified row/event absence; their actual unavailable-source authority consequences are tested in C.

Add explicit guards making production source reads/clock/evaluator/requester fail if replay invokes
them. For real B-positive tests use the existing actual framed worker fixture (including honest
platform simulation), not a comparator result stub. Actual R1 `input_root` absence remains a producer
test/real release gate: the core cannot detect a publisher's nonexistent private original by parsing
an invented consistent report. Do not write a core test that falsely claims it can.

## 9. Future implementation sequence (single coordinated task)

The writing-plans structure describes the future executable slice. §11 records the closed finite
adapter contract and genuine pre-dispatch/release gates, not a placeholder function or permission
to start with unimplemented evidence. No commit steps are authorized. Exact tests below use §8
and the adapter appendix's native/project fixture grammar; all owned test files must be independently
reviewable and execute production paths. Controller design approval and confirmation of the exact
already accepted Task45 R5 base remain required; this revision does not rerun its acceptance.

### Phase A — source publication and retained consumer

Files: the new deployment/source/init/schema modules and their four tests; narrow source_common,
deployment_prepare/catalog/startup test edits listed in §2. Consumes actual old renderer/source18.
Produces exactly §3 interfaces and actual startup-owned source export.
Catalog/startup changes in A are ONLY the source export, optional-root ownership and startup pin.
Do not create/register/import the new route contribution/factory or update route counts here:
the existing seven contributions/35 routes remain until C supplies the real API and service.

- [ ] Write S1–S11 and PA1–PA10 syntax/source projections above; pin literal two-file membership,
  old projection and §3.1 policy-byte/renderer/initializer equality with service/API imports disabled.
- [ ] Run `pytest app/tests/test_installation_release_contracts.py app/tests/test_installation_release_render.py app/tests/test_installation_release_sources.py app/tests/test_installation_release_init.py -q` and record the expected missing-new-interface failures.
- [ ] Implement §3.1 literal policy functions, fixed source codecs/render/initializer/retained reads
  and actual startup source ownership, leaving route registration/counts unchanged.
- [ ] Run those exact tests plus `app/tests/test_provider_source_startup.py`; compare old bundle bytes.

Minimal source-codec test body (helper is the actual new codec, no fake evaluator). The HTTP deny
assertion belongs to Phase C; Phase A does not depend on an unimplemented service.

```python
@pytest.mark.parametrize("release_source_case", ["deny_empty"], indirect=True)
def test_empty_allow_is_well_formed_source(release_source_case):
    case = release_source_case
    trust = parse_release_trust(case.files["release_trust"])
    assert trust.as_dict()["allowed_releases"] == []
    assert trust.content_bytes == case.files["release_trust"]
```

This particular fixture parameter must deliberately provision an empty allow before opening the
real source; it is not a post-startup source mutation. Other fixture variants provision actual
valid/denied source bytes with recomputed pins, never overwrite a live source to fake currentness.

### Phase B — raw evidence/codecs and verified2 domain branch

Files: contracts/evidence/schema exports/domain installation and their contract/evidence tests.
Consumes §11-frozen real-format vectors and exact signed public packet grammar; produces
ReleasePacket/Assessment and the verified2 record shape. Include only the already owned
prepare_service.py read-only stage1 delegate needed to project accepted stage history. No new
verified-installation authority/event commit or service/API registration occurs in this phase;
the fixture's accepted old staging operation is not a fabricated trusted-view constructor.

- [ ] Write E1–E22 and PB1–PB10 against retained bytes, actual stage projection and exact test
  signatures; include complete F1 signed-run/toolset projection and F2 policy-digest mutations;
  pin old8 KiB stage behavior. These assert assessment/refusal, not verified rows or event counts.
- [ ] Run `pytest app/tests/test_provider_installation_contracts.py app/tests/test_provider_installation_evidence.py -q` and record initial missing-interface failures.
- [ ] Implement the exact read-only stage1 journal projection, actual parsers and all byte/subject/
  policy joins; no injected verifier or pass map and no dependency on Phase C's new service/API.
- [ ] Run the same files and compare generated schemas; old installation/B branches stay exact.

```python
def test_external_scan_preserves_original_numeric_observations(release_documents):
    raw = release_documents["image_scan"]
    parsed = parse_external_document("image_scan", raw)
    assert parsed.content_bytes == raw
    assert type(parsed.as_dict()["matches"]) is list
```

The raw scan vector contains an actual numeric CVSS member, not a float-free replacement. The
high-finding signature/policy test below is a Phase C vertical, not a fake Phase B service result.
For PB8/PB10 call evaluate_release with release_evaluation_case.packet/source_files/stage/now_ms
and require a real ReleaseAssessment return with the same retained historical scan bytes; PB1–PB7/
PB9/foreign_policy/wrong_toolset require the actual source/evaluator refusal. No verified-state
assertion, service stub or caller-constructed VerifiedStageView is part of those B tests.

### Phase C — immediate migration, composed history and owner HTTP service

Files: prepare_storage/records/provider_receipt_records/prepare_service; new verification records/
service and storage/service/lifecycle/API tests; new API/route contribution and web_boundary/catalog.
Also exactly the five added F3 regression paths in §2, plus the already owned first-party/startup
tests. Current success snapshots move to C1–C6/SHAPE_V6; historical intermediate/failure snapshots
do not. Append contribution provider-installation-v1, factory app.api.provider_installation:create_router,
route IDs extensions.provider-installation.execute then extensions.provider-installation.read.
Its route methods/paths/auth/scopes are §4 (execute extension.manage, read extension.read).
Only now change current composition to eight contributions/37 unique routes, preserving previous
seven-contribution/35-route order exactly. No bulk V5->V6 or35->37 substitution is authorized.
Consumes phases A/B and actual accepted45 store graph. Produces the actual authenticated browser
vertical and verified2/history/head/event/receipt with exact old replay. Its full-app fixture uses
legacy B only; new descendant B is introduced in Phase D.

- [ ] Write H1–H12/V1–V11/A1–A14 and PC1–PC10, including F1/F2 positive/refusal authority snapshots,
  old provider/tool/B records, each migration/commit failure and actual app/session/base_path/body
  admission boundaries. Add narrowly changed current-success regression expectations in the five
  F3 paths; leave test_provider_receipt_migration.py's V5 semantic-failure [V4,V5] checkpoint intact.
- [ ] Run `pytest app/tests/test_provider_installation_storage.py app/tests/test_provider_installation_service.py app/tests/test_provider_installation_lifecycle.py app/tests/test_provider_installation_api.py -q` and record expected failures.
- [ ] Implement §6 literal v6 construction/migration/composition, then §5 service/record/CAS/event.
- [ ] Implement §4 early-auth bounded binary reception and the actual service/route contribution;
  obey the controller-selected cancellation-safe UploadLock.publish carrier conditions. This
  design decision does not grant product dispatch before controller installation preflight approval.
- [ ] Run the same tests; inspect complete before/after snapshots, not just state labels.
- [ ] Run `pytest app/tests/test_web_owner_integration.py app/tests/test_deployment_receipt_migration.py app/tests/test_deployment_journal_v3_migration.py app/tests/test_provider_prepare_migration.py app/tests/test_provider_receipt_migration.py app/tests/test_first_party.py app/tests/test_provider_source_startup.py -q`; verify literal C1–C5, historical V5 failure/rollback and old row/type/rowid/event/reply bytes are unchanged while only ordinary current success reaches C6/V6 and37 routes.

```python
@pytest.mark.parametrize("installation_case", ["high_finding"], indirect=True)
def test_changed_scan_cannot_hide_behind_signature(installation_case):
    case = installation_case
    response = case.post_packet(case.packet)
    assert response.status_code == 409
    assert case.snapshot().verified_refs == ()


def test_verified_is_same_identity_next_revision(installation_case):
    case = installation_case
    before = case.snapshot()
    response = case.post_packet(case.packet)
    assert response.status_code == 200
    result = response.json()
    assert result["verified_installation_ref"]["id"] == case.stage_ref.id
    assert result["verified_installation_ref"]["version"] == 2
    after = case.snapshot()
    assert after.old_record_bytes == before.old_record_bytes
    assert after.verified_event_count == before.verified_event_count + 1
    replay = case.post_packet(case.packet)
    assert replay.content == response.content
    assert case.snapshot().authority == after.authority
```

### Phase D — explicit descendant B and connected regression

Files: exact B modified paths/schemas and verified-B tests. Consumes the actual owner HTTP/source/
service vertical and composed history from Phase C. Produces the new durably guarded B arm;
no new B SQL or worker behavior.

- [ ] Write B1–B11 with the actual app/session/framed worker, then run `pytest app/tests/test_provider_conformance_verified.py -q` to record expected failures.
- [ ] Implement §7 explicit
  variant parsers/resolver/guard/records/service/recovery/reply/export branches.
- [ ] Run those tests plus the accepted45 exact controller72-command manifest,
  preserving its original command spelling/environment/order. Do not replace the full baseline by
  selected B tests or regenerate an approximate test list from this draft.
- [ ] Run all new tests and affected old provider-source/deployment/schema/catalog suites, compare
  exact ownership manifest and old exports, and submit recorded outputs for independent preflight.
  The exact seven-file Phase C regression command above is included again in this final connected
  gate; do not drop those five newly owned regression files from the manifest or run coverage.

```python
@pytest.mark.parametrize("installation_case", ["framed_worker"], indirect=True)
def test_descendant_command_names_both_identities(installation_case):
    case = installation_case
    installed = case.post_packet(case.packet).json()
    command = {"schema_version": "provider-conformance-command-v2",
        "command_id": str(uuid4()), "staged_installation_ref": case.stage_ref.as_dict(),
        "expected_verified_installation_ref": installed["verified_installation_ref"]}
    response = case.client.post("/api/v1/extensions/provider-conformance",
        json=command, headers=case.auth_headers)
    assert response.status_code == 200
    value = response.json()
    assert value["schema_version"] == "provider-conformance-reply-v2"
    assert value["staged_installation_ref"] == case.stage_ref.as_dict()
    assert value["verified_installation_ref"] == installed["verified_installation_ref"]
    assert value["state"] == "matched"
```

This variant executes inside the actual framed-worker fixture. A source-less restart replay case
must disable worker/source access and still return byte-identical stored response; separate fresh
descendant runs require the real source18 and current head, not cached admissions.

## 10. Ordinary distribution and authority costs

Maintainer's authorized workflow produces raw build/source/SBOM/scan/license evidence and signs
one exact release review; it may be the same person who assembled it. Trusted deployment packages
the allow policy, fixed source/pin and already-staged image/receipt. The browser user selects that
offered release; the product transports the packet and calls the actual route. No user must author
source JSON, provide signing keys, run scans or invoke a CLI. A missing trusted setup/artifact is
reported as unavailable evidence, not converted into an owner “approve everything” control.

Frozen sources require authorized deployment update/recreation for policy changes/expiry and cannot
discover instant external revocation. Policy-generation rollback protection is not invented here.
Immutable installed evidence says what was reviewed at issuance; active-use current vulnerability
policy needs a later real producer/qualification consumer. One allow/one verification and two B
variants keep scope finite but intentionally exclude release replacement/catalog management.

## 11. Adapter amendment, finite G1 closure and real prerequisites

**G1 amendment history:** the earlier draft identified missing signed review/cohort/invocation/map
grammar and a carrier decision. Primary research now supplies tagged format/ID/config facts
(`post45-release-adapter-primary-research.md`, SHA-256
initially `f4934e28d72e61ba324c3105dc15d2bf9bf3d678b0b740feb8d2533f383d4fcf`, then the complete
added §8 and revised hash `cdd3e401aba193c85159154cc9180501753391d98596c0429fb5fac81ae73feb`). The new
`post45-release-adapter-contract-draft.md` chooses exact project signature and acyclic closure,
SPDX subset/license branch rules, class/ID/file joins, scan severity/attributable acceptance,
provenance, parser/canonical limits and synthetic vector contract. These remain advisory pending
controller review; no canonical promotion occurred. CVSS/matcher diagnostics are retained, not
used to authorize exemptions or fabricate a scanned inventory.

**G1 closed at draft-contract level:** the first appendix revision still lacked exact native
config/DB/layer tables. Controller requested tagged-source resolution instead of carrying another
research gate. The appendix now incorporates the complete literal Grype configuration/status/provider
grammar and selects Syft's five catalogers, audit wrapper and raw-vs-canonical codecs. Stereoscope
layerID is explicitly the uncompressed diff ID, not the compressed manifest digest; native layer
size is not a compressed descriptor size. Its finite nonempty finding/SPDX/license/provenance and
acyclic byte joins can be implemented with labeled synthetic fixtures. No native scanner sample,
production key or actual cohort measurement was fabricated or needed to close this offline design.
Unknown decision-bearing fields refuse. No arbitrary signed config, permissive digest-domain
matching, fake callback or pass dictionary is admitted. This is the chosen narrow adapter, not
support for every upstream schema branch or the still-unmeasured real release.

The controller selected the48 MiB dedicated authenticated carrier direction and its mandatory
conditions, now in §4. It is no longer an unmade design choice; actual real-report/header/graph fit
and memory/throughput still need measurement. This is not permission to start product work before
controller independent installation preflight; Task45 R5 acceptance is now recorded above.

Actual external gates remain separate: real original base/eight wheels/source closure and R1
independent finalization; approved scanner binaries/config/database and truthful observations;
bundled-component supplier/build link evidence; measured per-report/header/full-graph fit;
authorized rights/release review and separately provisioned public trust; actual source/init image
and supported setup/update packaging. No production key/hash/date/measurement is invented here.
Synthetic fixtures test algorithms and exact authority flow, not that those real producers exist
or that the frozen real images are supported. Missing originals cannot be detected by a signature
alone; the real external finalizer/reviewer must actually possess and inspect them.

Task45 R5 acceptance is satisfied by the controller-reported manifest; exact approved-base
confirmation and installation-design approval remain prior dispatch gates. Real native
collector/key/enrollment/runtime/permission/full-provider semantics remain later C/binding gates,
not prerequisites for offline implementation of this reviewed core slice. T087 remains open.

## 12. Self-review result

**Preflight R1 resolution history:** independent review found F1 (P1) and F2–F4 (P2) after the
previous G1 closure claim. That earlier claim did not resolve these newly identified deterministic
issues. This revision selects F1 signed execution assertions and exact retained R1 toolset/byproduct
projection, F2 literal canonical policy bytes in the already owned contracts module, F3 exactly five
added current-layout/route regression paths, and F4 PA/PB/PC dependencies with route registration
only in C. These are draft corrections for controller re-review, not promotion or passed tests.

- F1: no R1 run/time/runtime-list field is invented; original report schemas and deterministic1970
  recipe timestamp remain unchanged. Complete positive and wrong-toolset/byproduct/run assertions
  are specified in the adapter, with C repeating actual authority outcomes.
- F2: one literal policy object/serializer/digest source is shared across renderer, initializer,
  context validation and evaluator; source/review/code parity and foreign-hash refusal are assigned
  to the phases where those consumers exist. No actual cohort/key/hash is fabricated.
- F3: scope adds only the five named tests; ordinary success moves to C6/V6 and37 routes while
  historical C1–C5 bytes, V5 failure checkpoints, old rows/types/rowids/events/replies remain exact.
- F4: source tests have no new service/API import; evaluator tests consume real accepted-stage
  journal projection through the already planned read-only delegate implemented in B; only C
  registers routes and proves actual verified2/head/event/refusal. No forward service mock remains.

- Canonical separation/source18/same-store/browser boundaries are preserved; new numbers, carrier,
  field names, v6/B variants and source policy are explicitly recommendations pending promotion.
- Source -> intake -> actual evaluator -> domain/store/head/event -> B/C-consumable evidence is
  connected. No source-only parser is claimed as delivered installation verification.
- Old stage1/B bytes/digests/replies/index semantics remain explicit; new command/body/reply
  variants unambiguously name stage and verified identities, with durable finalization guards.
- Migration/graph/lifetime/race/replay cases are mapped to owned tests, with no execution claim.
- The controller-selected carrier includes the actual cancellation-safe publication lease; native
  raw JSON and project canonical objects do not silently share incompatible bounds or byte domains.
- G1 is closed for the explicitly selected offline adapter; genuine size/cohort/authority gates
  remain explicit. **This draft is ready for controller design preflight, not implementation
  dispatch.** No tests/product changes ran here, and no authentic release compatibility is claimed.
