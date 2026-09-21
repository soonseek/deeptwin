# Post45 release-only public source — contract outline

2026-09-20. **Advisory, not promoted or implemented.** This closes the proposed two-file source
shape for the installation-boundary and amended release-evidence proposals. It does not authorize
real keys, scans, downloads, deployment changes, publication, native enrollment or qualification.
Only this file is written; the previous proposals remain unchanged. Task45 is treated solely as
the fixed promoted conformance contract, not inspected moving product code or accepted behavior.

Brainstorming supplies the architectural boundary and alternatives; writing-plans supplies
dependency discipline, not a full task plan. Ordinary recommendations are selected under delegated
design authority. The explicit docs-only scope governs; no implementation or promotion is dispatched.

## 1. Selected seam and authority

Recommend exactly one companion immutable root:

`/run/deeptwin/installation-release-sources`

with a sole `documents/` directory containing ordered files `release-trust.json` and
`installation-release-context.json`. The first is a
public, independently provisioned release-trust/admission policy; the second joins its exact bytes
to the old source18 and the code-owned evidence policy. Neither contains raw scans, license text,
OCI bytes, private keys, native observations or a precomputed verification result. Those reports
remain immutable release evidence delivered separately and retained by the future consumer.

The smallest useful policy allows **zero or one selected provider release** for this deployment
platform. Zero is an intentional deny-new-verification policy, not an empty successful installation.
It matches the existing one-provider/optional-one-tool topology and one staged-to-verified successor
slice. Multiple releases, hot rotation, replacement/uninstall and arbitrary policy plugins are out
of scope. Four review keys permit bounded issuance-key history; key count is not a two-person rule.

Authority originates in trusted deployment provisioning and its startup pin, not a self-signature
inside either file. The renderer can validate a supplied public root's syntax and joins but cannot
approve the root. A browser upload containing these documents never replaces the actual source.
The maintainer may assemble and review a release; independent verification execution and separated
signing capability remain required by the proposed evidence profile, not different natural persons.

## 2. Common closed types and file limits

These are proposed types, not a claim that new codecs already exist. Both files use existing
ADR-008 canonical JSON rules, exact raw-byte SHA-256 and no duplicate/unknown/missing fields, null,
floats, BOM or invalid UTF-8. Exact integers exclude booleans. Object fields below are exhaustive;
no extension dictionaries or union arms are implied. No field is a path or runtime fetch URL.

| Type | Exact proposed rule |
| --- | --- |
| `H` | String of exactly64 lowercase hexadecimal characters, SHA-256 of the stated exact bytes. |
| `U` | Existing canonical nonnil UUID grammar; use the accepted UUID parser, not a new normalizer. |
| `I` | Existing instance ID, exactly32 lowercase hexadecimal characters. |
| `T` | Exact epoch-millisecond integer0..253402300799999, matching the conformance contract's time domain; no local timezone or float conversion. |
| `N` | Exact policy generation integer1..2147483647; an identifier/order declaration, not proof that no newer policy exists. |
| `B32` | Canonical unpadded base64url encoding of32 bytes with round-trip/pad-bit checks; public Ed25519 key bytes only. |
| `S(C)` | Exactly `{sha256:H,size_bytes:int1..C}`. The consumer must receive/recompute actual bytes; a descriptor is not evidence availability. |
| `ExtensionId` | Existing descriptor ASCII identifier grammar and128-byte bound, as referenced by canonical `provider-image-lineage.md:84`; reuse that validator unchanged. |
| `ExtensionVersion` | Canonical major.minor.patch, each integer0..2147483647, total at most32 UTF-8 bytes; existing lineage rule, no prerelease aliases. |
| `DeploymentProfileId` | Exact existing startup OriginProfile deployment-profile value and its canonical validation, additionally at most128 UTF-8 bytes; no new profile is introduced. |
| `Platform` | Literal `linux/amd64` or `linux/arm64`; equality to actual old geometry/platform is required, not evidence of native qualification. |

Proposed caps: trust file16 KiB, context file8 KiB, aggregate24 KiB. General parser bounds are
depth8, at most4096 total members/items, at most32 fields per object and string length1024 bytes;
field-specific bounds override these. The larger external-format report caps in the evidence
proposal do not apply to these source documents. Every array below has canonical sorted unique
members under its stated key; duplicate public keys with different IDs also refuse.

Root and `documents/` are fixed owner0:21201/mode0750; both files are regular, nonempty,
single-link owner0:21201/mode0440. Control mounts the root read-only and retains the original group
membership; no new control UID, writable trust root or user-owned host-file fallback. These are
recommendations adapted from the accepted provider-source pattern, not claims of a real mount.

## 3. `release-trust.json` — exact public trust/admission policy

Top-level type: `InstallationReleaseTrustV1`. All fields required.

| Field | Type / bound | Meaning and required join |
| --- | --- | --- |
| `schema_version` | Literal `installation-release-trust-v1` | Only accepted source-policy shape. |
| `instance_id` | `I` | Exact old instance and startup profile instance. |
| `origin_profile_digest` | `H` | Recomputed existing complete OriginProfile digest; not merely origin host or instance equality. |
| `deployment_profile_id` | `DeploymentProfileId` | Exact same startup/old-source profile. |
| `policy_generation` | `N` | Explicit provisioning generation for this instance/source scope. |
| `valid_from_ms` | `T` | Inclusive beginning of this snapshot's new-admission authority. |
| `valid_until_ms` | `T`, greater than `valid_from_ms` | Exclusive end of new-admission authority; no implicit infinite default or fixed daily refresh. |
| `keys` | Array0..4 of `ReviewKey`, sorted by `key_id` | Presently provisioned keys usable for explicitly allowed historical/new review statements; no transitive delegated keys. |
| `allowed_releases` | Array0..1 of `AllowedRelease` | Explicit exact release to which this snapshot grants potential admission, subject to all evidence checks/denials. |
| `revoked_key_ids` | Array0..16 of `U`, sorted | Deny new admission under these key IDs, including earlier-issued reviews. A revoked key need not remain in `keys`. |
| `revoked_review_sha256` | Array0..16 of `H`, sorted | Deny these exact signed review-envelope bytes. |
| `revoked_manifest_sha256` | Array0..16 of `H`, sorted | Deny all reviews of these selected platform manifests; not an instruction to uninstall anything. |

Nested `ReviewKey` has exactly these fields:

| Field | Type / bound | Meaning |
| --- | --- | --- |
| `key_id` | `U` | Matches the actual signed release-review envelope. |
| `algorithm` | Literal `ed25519` | No inferred algorithm or caller-selected verifier. |
| `public_key` | `B32` | Actual separately approved public key; never generated from source hashes. |
| `role` | Literal `provider_artifact_review` | No receipt, native observer, qualification issuer or runtime-dispatch authority. |
| `review_profile_id` | Literal `provider-artifact-review-v1` | Only the evidence profile in the amended advisory, once separately frozen. |
| `issuance_not_before_ms` | `T` | Inclusive allowed review-issuance interval start. |
| `issuance_not_after_ms` | `T`, greater than preceding field | Exclusive issuance interval end; may precede current admission time when an exact old review is explicitly allowed. |

Nested `AllowedRelease` has exactly these fields:

| Field | Type / bound | Meaning and required join |
| --- | --- | --- |
| `extension_id` | `ExtensionId` | Equals actual candidate/descriptor/lineage and historical stage identity. |
| `extension_version` | `ExtensionVersion` | Same actual release version, not a floating selector. |
| `platform` | `Platform` | Equals context, geometry, selected stage platform and review subject. |
| `image_index_sha256` | `H` | Exact immutable multi-platform index identity in the stage and review. |
| `selected_manifest_sha256` | `H` | Exact selected platform manifest in that index, stage and review. |
| `release_review` | `S(262144)` | Hash/length of the actual complete signed review envelope; signature bytes included, no payload-only ambiguity. |
| `key_id` | `U` | Exactly one entry in `keys`; its role/profile/issuance interval must admit this review. |

No raw layer/config list is duplicated into this small allow entry: the exact review digest binds
the signed statement's complete manifest/config/ordered-layer/lineage/evidence graph, whose actual
bytes are still mandatory at intake under the release-evidence profile. Checking these two image
digests alone is not verification. Policy cannot change the signed report's subject or replace
raw findings with a trusted allow decision.

Default deny. All denials win over an allow entry; retaining an allowed entry plus an explicit
revocation is a valid denied policy, not parser success becoming admission. Empty `keys` requires
empty `allowed_releases`. A present allow with an absent key is malformed. Revocation arrays are
finite local policy facts, not evidence of a global online revocation query. A current allow entry
explicitly accepts the stated historical statement under its issuance key interval; expired old
issuance authority is not itself a current revocation, and a once-unknown key is not blessed merely
by an alleged old timestamp. No other release inherits acceptance from sharing the signer.

## 4. `installation-release-context.json` — exact source/consumer join

Top-level type: `InstallationReleaseContextV1`. All fields required.

| Field | Type / bound | Meaning and required join |
| --- | --- | --- |
| `schema_version` | Literal `installation-release-context-v1` | New file version only, not original source epoch. |
| `recipe_id` | Literal `installation-release-source-recipe-v1` | Code-owned renderer/initializer contract, not caller policy. |
| `layout_id` | Literal `installation-release-source-layout-v1` | Exactly the two names/order/metadata/caps in this outline. |
| `instance_id` | `I` | Exact startup/old source/trust instance. |
| `origin_profile_digest` | `H` | Exact reconstructed startup and old source/trust OriginProfile digest. |
| `deployment_profile_id` | `DeploymentProfileId` | Exact startup/old source/trust deployment profile. |
| `topology_id` | `U` | Copy and compare the original topology ID, never generate a new one. |
| `topology_revision` | Literal integer1 | Unchanged old topology revision for this finite profile. |
| `platform` | `Platform` | Exact old geometry/original instance and runtime sampled platform. |
| `provider_source_context` | `S(16384)` | Actual old `source-context.json`, including its original epoch1 and first16 ordered document descriptors. |
| `provider_geometry` | `S(65536)` | Actual old `geometry.json`, validated through the complete borrowed source18 graph. |
| `release_trust` | `S(16384)` | Actual first file in this new two-file root. Filename is code-owned, never selected by this descriptor. |
| `review_profile_id` | Literal `provider-artifact-review-v1` | Required consumer evidence profile, equal to every review-key delegation and submitted signed review. |
| `evidence_policy_sha256` | `H` | Exact code-owned canonical profile-policy bytes; evaluator compares its own bytes, not an uploaded policy or arbitrary threshold object. |

No context ID, new topology identity, source18 epoch, source-pin file, native collector/runtime
release document, stage/head ref or installation result is added. Startup key proposed as
`DEEPTWIN_INSTALLATION_RELEASE_CONTEXT_SHA256` holds SHA-256 of this exact context. The context
never contains its own digest, startup pin, expanded Compose hash or future installation hash.
Canonical construction is actual old source18 + approved trust bytes + code-owned policy ->
context bytes -> startup pin -> additive deployment output, with no cycle.

`evidence_policy_sha256` identifies the fixed interpretation of reports, tool/schema selection,
coverage, issuance validity and caps. It is not the digest of the current allow list. The actual
scanner binaries/database/input cohort remains pinned by immutable review evidence; selecting a
current allowed review does not assert that those tools ran today. New parser/policy semantics need
a reviewed code/profile release, not editing this hash to an unrecognized value.

## 5. Actual producer, startup retention and old source18

The future outer renderer invokes the existing provider renderer with its exact ten named raw
inputs (`provider-source-production.md:89–94`), then validates its actual18 output bytes. It takes
explicit approved trust-policy bytes and exact initializer-image input; it derives context from
those real bytes and code-owned policy. It emits two fixed documents, startup pin and additive
deployment output. Removing only declared additions must recover the complete old expansion byte/
structure contract. All18 old files, IDs, slots, epoch, recipes and output hashes retain their old
meaning; the outer expansion has a new identity. Do not extend the old renderer's input dictionary.

The fixed-path initializer independently recomputes the context from the actual old source bundle,
trust input and code-owned policy, compares the supplied context, and publishes exactly this root
with no-replace/retained-identity/fsync behavior. It never writes old roots, opens core storage,
fetches images or acquires signing keys. Its actual image digest is a required deployment input,
not a hash fabricated from the recipe. A partially initialized/different existing tree refuses;
there is no repair/rebind pathway hidden in initialization.

Startup snapshots the one catalog-registered pin, borrows the actual `ProviderSourceContext` and
opens a separately owned retained two-file handle. Whole reads validate exact bytes/membership,
metadata, path-to-FD identity, protected roots and mount/backing relationships. New root presence
must join the old finite optional-root alias observer in both directions without changing old
return shapes. Native availability is the existing Linux reader condition, not a fabricated
positive non-Linux mode or qualification claim. No moving Task45 implementation is needed to
state these accepted source contracts.

Expose only fixed `read_current`, `recheck_current` and `close` behavior to the actual installation
consumer; no arbitrary path/key lookup, cached lease, generic callback, refresh or public constructor.
Missing/invalid/stale source denies fresh verification, while same-store historical rehydration
remains available. New acquisition/read/shutdown paths need attempt-all, primary-error-preserving
cleanup; Task44's earlier lifetime fixes do not prove new factories correct. A source-only export
with no actual verification consumer would not deliver the connected next slice.

## 6. Current policy, immutable evidence and shared history

At fresh admission and immediately before commit, the consumer checks source currentness, exact
borrowed source18/profile equality, current core time within the trust-policy validity interval,
allowed review/subject/key joins and all denials. Then it verifies the actual immutable signature,
provenance/SBOM/scan/license bytes and release-time policy. The amended evidence proposal's 24-hour
scan-to-issuance/120-hour DB-at-issuance conditions are **not age limits at every later installation**.
Display original scan/DB dates; no stale scan becomes a current-risk claim.

The signature authenticates issuance assertions, not an independent clock. Current provisioning
explicitly admits that exact review under its issuance interval and present local trust constraints.
Within a live handle, file or mount replacement refuses even when content is identical. Across
restart, the trusted deployment controls the new pin; `policy_generation` alone is neither remote
freshness nor rollback resistance. This outline does not invent a second policy registry or claim
a complete cross-restart anti-rollback mechanism. A requirement to reject every older trusted
snapshot would need an explicitly reviewed durable-generation consumer or external provisioning
guarantee before such a claim could be made.

This source is frozen until authorized deployment update/recreation. New allow/revoke facts or
policy expiry can require that update; everyday consumption of an already allowed release does not
require daily publisher review. A valid local snapshot does not discover revocations elsewhere.
Immediate revocation awareness needs a separately reviewed update path; active-use vulnerability
refresh/revocation belongs to a separately specified qualification/binding consumer. This source
does not autonomously suspend a service, erase verified history or grant seven-day native validity.

Successful verification retains both exact source documents, startup pin, evaluation/issuance
facts, actual release evidence and owner-command/head preconditions in the **same** installation
history/event family, and atomically creates the proposed verified revision2 from exact stage1.
The source contains no stage/head reference: release-policy provisioning may precede a stage and
cannot itself assert that one exists. The active writer proves the real candidate/request/receipt/
stage graph and expected current head. Missing evidence or a concurrent head change leaves it
unchanged. Exact command replay and historical reads consume retained issuance/source evidence,
not today's absent/expired trust root, and preserve all older bytes/events/replies.

Existing v5 stage-only history and the fixed Task45 fresh-stage resolver must change together in
the separately reviewed verification slice: historical stage1 remains the exact anchor; current
head may be its one proven verified2 descendant. Future fresh B must join both, without weakening
head checks or reinterpreting old subject hashes. Old B is still historical; later C needs its own
fresh B after expiry/restart. This outline adds no SQL, new registry, C evidence or accepted45 claim.

## 7. Ordinary browser-user path

The authorized maintainer produces one immutable reviewed release packet from real artifacts.
Trusted product/deployment packaging approves the receiving instance's signer/allowed-release
policy, creates the two-file source/pin and stages the exact image with its instance-specific
operator receipt. This is outside core and can be automated by the supported setup/update workflow;
it is not implemented by this advisory or replaced by an owner-uploaded trust file.

The user selects the offered, already staged provider release in the browser. Product transport
supplies its published public evidence; core verifies source policy and exact stage/evidence joins,
then shows `verified` separately from qualification/activation. Users do not author signatures,
scan reports, license conclusions or CLI commands. Absent trusted setup/evidence is shown as a
specific prerequisite, never repaired by asking an ordinary user to pretend to be a publisher.
Completing the supported distribution/setup flow remains future product work; no runtime image
download, real release publication or native collector action is authorized here.

## 8. Fixed recommendations, unresolved values and promotion gates

| Item | Status / why it matters |
| --- | --- |
| Immutable installation versus expiring qualification; exact operator stage; browser owner cannot supply executable/trust authority; same-store history | Canonical runtime223–237, ADR-014, receipt-consumption/source contracts. Non-negotiable boundaries for the later contract. |
| Two files/root, field names,0..4 keys/0..1 allow/0..16 denials,16+8 KiB caps, metadata, single startup pin | Delegated recommendations selected here. They are a finite proposed grammar, not canonical constants or deployed configuration. |
| Key role, no different-person requirement, issuer-time policy versus current allowed-release snapshot | Follow the amended release-evidence advisory. Canonical authority separation does not itself mandate these exact fields, issuance thresholds or a two-person review. |
| Public keys/key IDs, approved exact review/manifest/index digests, issuance intervals, snapshot validity/generation and revocations | Must come from actual authorized release/provisioning inputs. Cannot honestly be filled with invented keys, an arbitrary default lifetime or claims of current revocation knowledge. Syntax and deny behavior can be coded offline. |
| `evidence_policy_sha256` | Compute only after the exact profile-policy document and interpretation are frozen. Actual tool/cohort/schema/config hashes belong to real review evidence; no digest is supplied by this outline. |
| Old context/geometry digests, instance/origin/topology/platform and trust/context lengths | Deterministically recomputed from the actual selected source18 and approved input bytes. They are not hand-entered startup facts or a source18 mutation. |
| Initializer/control image references and truthful supported setup/update path | Actual release packaging and deployment inputs remain unavailable/not authorized here; source-code hashes are not image approval. A controlled source update, not runtime hot reload, is the recommended initial path. |
| Source/report/graph size fit | Proposed small source bounds are not measured release-cohort evidence. Measure actual canonical policy/context, raw reports and complete retained graph before real-positive acceptance; the earlier48 MiB evidence/64 MiB graph and R1 report/tree caps remain independent constraints. Do not truncate or silently widen them. |
| Signed-review format/cohort, actual source/build/wheel/bundled-component evidence, legal authority and raw reports | The amended evidence profile defines the selected direction, not a completed producer. Freeze and exercise its actual producer/consumer joins before claiming real verification; missing `input_root` or rpds supplier evidence remains a real blocker. |
| Atomic history transition/current-verified B; source-source alias/lifetime/startup integration | Required coordinated future implementation dependencies, not facts implied by this schema. Must be reviewed with accepted45 after sole-writer completion; no moving product files need inspection now. |

Contract acceptance must cover a real fixed-root producer/initializer/reader-to-verifier chain;
changed inode/mount/source18; malformed/expired/empty policy; exact historical signer acceptance;
deny-over-allow; wrong review/platform/index/key; missing original producer input; missing retained
raw evidence; publication/commit interruption; atomic stage1-to-verified2 and fresh B descendant
joins; and source-less historical replay. Controlled offline fixtures can establish these code
paths without real native qualification. They cannot supply approved roots, real reports, report-fit
measurements or legal/release authority. This is an outline for that contract, not its promotion.
