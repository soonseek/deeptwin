# Provider installation verification — accepted finite implementation contract

2026-09-20. **Design accepted for offline implementation; product implementation is not yet
accepted.** This is Task46 within the existing seven-story plan, not a replacement release scope.
It adds one same-store staged-provider revision1 → verified revision2 transition and explicit
fresh conformance of that verified descendant. It grants no native qualification, provider binding,
credential/model send, artifact publication or actual release-signing authority.

## Normative snapshots and precedence

The implementation-era [retained dpkg amendment](provider-installation/dpkg-status-evidence-amendment-v2.md)
§§2–6 is adopted on 2026-09-20 and takes precedence for its expressly named Map/status/file-inverse
and policy deltas. Its historical draft/controller-gate wording is superseded by this adoption.
It does not change source18, R1 report bytes, carrier roles/limits, task ownership or real authority.
The original eight snapshots below remain byte-identical; this is an explicit subsequent amendment.

The `provider-installation/` directory preserves the exact independently reviewed documents,
including their historical filenames, dated draft/not-accepted statements and correction history.
This promotion supersedes only their former controller-design/Task45 dispatch gates. It does not
rewrite history, claim implementation success or promote unrelated future producer/native work.
Canonical spec.md/runtime.md/ADR-014 remain the product authority. Within this finite slice use:

1. `provider-installation/post45-installation-verification-draft.md`, §§1–9: complete task scope,
   fixed source interfaces/policy object, carrier, evaluator/service/history/v6/B variants and
   phased proof. §§10–12 retain limits and correction history.
2. `provider-installation/post45-release-adapter-contract-draft.md`, §§2–9: selected byte and
   signature/reachability/native/provenance grammar and required vectors. Its corrected §7
   signed-run assertions and exact toolset projection supersede the earlier nonexistent-run join.
3. `provider-installation/post45-release-source-contract-outline.md`, §§2–6: closed source
   grammar/currentness; formerly deferred policy bytes are resolved by installation §3.1.
4. `provider-installation/post45-release-adapter-primary-research.md` §8 is incorporated only as
   expressly selected by adapter §6. The adapter's fixed choices supersede research suggestions.
5. `provider-installation/post45-carrier-controller-preflight.md` supplies the actual existing
   UploadLock.publish boundary. Installation/adapter now incorporate its conditions.

The preserved `provider-release-producer-draft.md` supplies the exact R1 report/recipe/toolset
grammar referenced by the adapter and its explicit-input/fresh-finalization amendment. That use
does NOT authorize building/scanning/signing/publishing a real producer. The two other proposals
are background rationale only; their open recommendations do not override the final contract.
No production/test code may load ignored scratch or these Markdown files to obtain an expected
verdict, a policy value or synthetic release authority. Implement code-owned literal contracts
and independent fixtures as specified. No new dependency is required.

| Frozen document | SHA-256 |
| --- | --- |
| Installation contract snapshot |106064830e5d7dcc5712f8eb733bf81faa00515405aa47f26b5c4c3344587e08|
| Adapter contract snapshot |c8abd143091391e2e403dac0ca2bfa36c2934eb54d41805f2384e23264d01a24|
| Source outline |8974ed3456a513976390cb6db7d1a90336face63e3da276966092e4b60d52f10|
| Primary format research |cdd3e401aba193c85159154cc9180501753391d98596c0429fb5fac81ae73feb|
| Carrier preflight |ec3388c0ace7f9c55991cebf432c2142be95fe72ca009f5b778083d7c9bc9f6b|
| R1 producer grammar/background |e207e736c9096d4c52552c8a91295e07d57d1f54f5b179257dbb185a779d9c0f|
| Release-evidence background proposal |bd0e3c2af17882c3193e13edfd61b46928830fbe847c01e1df02336c12517dab|
| Installation-boundary background proposal |fed372d8c2cb1cb9c70b172cc6623e42b17c31e07c57513611916aa0aae71d6b|

## Review and approved baseline

Initial independent preflight was spec-compatible but NOT READY: F1 absent R1 run metadata,
F2 undefined shared policy bytes, F3 five missing existing-test paths and F4 phase-forward
dependencies. Design R1 addresses all four. Scoped independent re-review: spec COMPATIBLE,
executable READY for this finite offline slice, no remaining/new P0/P1/P2/P3 findings.
Complete before/change/review evidence remains in `.superpowers/sdd/resumption-plan/`.

Task45 accepted773-path baseline is
`d6cc1b4460d37b4cc0789c52e6e90b9a002c931f6796c8a51fa251c364b89ba6`, unchanged HEAD
`a2f85d578c47a0e59c1850ac1840cf8baceb0d96`. Its distinct completed RED exact72 and amended GREEN
cover are recorded in evidence/resumption-2026-09-20.md; this promotion asserts no new full72 pass.
Task46 owns exactly34 new and28 modified paths from the final installation §2, including the
five narrow current-layout/route regressions. Beforecopies and baseline are controller-owned.
Expected completed inventory is807 paths:745 old unchanged,28 permitted modifications,34 new.

## Execution and acceptance boundary

### Historical integrity versus fresh admission — explicit clarification, 2026-09-20

Installation snapshot§6 requires complete retained descendant/issuance integrity on every
composed history load. Its §4 prohibition on replay signature reevaluation is narrowed here:
deterministic verification of a retained signature and retained evidence under the exact retained
source snapshot and original `verified_ms` is allowed and required for historical integrity.
It is not a fresh release-admission decision. This explicitly supersedes only the blanket reading
that would omit cryptographic validation of corrupted retained evidence; it does not permit live
source/current-policy/current-clock evaluation, a rescan, a worker probe or rewritten history.

Provide a distinct read-only `validate_retained_release(packet, *, source_files, stage,
verified_ms) -> None` in the owned evidence module. Its caller is the mandatory private composed
journal, which loads exact registered source/evidence blobs, derives the historical stage view,
and cross-checks the recorded verification timestamp/record/index/event. No caller-supplied pass
map, guessed timestamp, current head-as-stage or arbitrary historical view is trusted. Shared
pure authentication/byte/semantic helpers with fresh evaluation are allowed; the historical
entry does not call public `evaluate_release`, construct a new ReleaseAssessment or issue any
command/head/event/reply/clock update. It validates the exact supported retained policy identity
and original admission/issuance relations; it does not substitute today's provisioned policy.

Exact POST replay and GET still perform authenticated owner/purpose checks and this mandatory
history integrity check. Preserve guards making live source readers, admission clock, public
fresh evaluator and requester fail if replay calls them. Frozen replies/timestamps remain
byte-identical even after current source removal/revocation/expiry. In contrast, changed retained
review signature, source identity, verification timestamp, graph/blob or semantic evidence must
refuse historical loading without creating authority. Tests must distinguish these two cases.
The service calls its composed journal once, with no journal→validator→journal recursion.

This is a narrow amendment within the existing62paths. The evidence-file review hold permits
the shared pure-validation refactor and this historical entry; both require changed-byte review.
It grants no new real signature, native observation, live provider or release authority.

A source/publication → B actual evidence evaluation → C same-store v6/HTTP authority → D verified
descendant conformance form one connected acceptance unit. Phase-specific tests must run against
the dependencies they actually have; no source-only completion, fake evaluator or future-service
stub supplies missing authority. No helper/subagent/commit is authorized for the sole implementer.

Use real temporary owners/stores/framed workers and explicit test-only signatures. Preserve
historical records, replies, C1–C5, ordinary old schema branches and deliberate V5 failure tests.
The final baseline command is the exact controller72 command retained with Task45; its spelling,
environment and order remain fixed. Run all new tests and explicitly affected old regressions,
record raw output/exit/time and obtain independent task-scoped spec/quality review before acceptance.
Do not call expected refusal, skipped native checks or synthetic evidence a real release pass.

Actual original inputs/finalizer, native scanner/tool/DB/cohort truth and compatibility, supplier/
rights review, real trust/image provisioning, measured limits and supported clean-host/browser
distribution remain separate genuine gates. The finite scanner subset may refuse a real release;
do not omit evidence or widen it silently to obtain a positive result. T087 and all incomplete
whole-story tasks stay open. Ordinary users will use the browser, not author source/signature
files or operate a CLI. Whole-product estimate remains about50%±5 including design.

## Fixture identity clarification — 2026-09-20

The adapter's typed `Component.inputs` identities have one finite mapping in this profile:
`base` is the selected platform DependencySet.base.index projected from OCI digest/size to S
(strip the exact `sha256:` prefix); it is not an interchangeable selected manifest/config/layer.
`source` equals SourceReport.source_bundle; `wheel` equals an actual selected platform
distribution wheel S, with the existing class-specific exact distribution/parent joins;
`supplier` resolves to its retained strict-UTF8 supplier evidence. The supplier narrative remains
an attributable statement, not an independently proved build fact. Every Input.evidence list
retains its original nonempty typed support requirements. This aligns the base/source/wheel
identity domains with adapter§7's explicit provenance projection and R1§4.1–4.3; it creates no
alternate external identity, source acquisition, legal authority or authentic scan claim.
Coherently signed/re-pinned substitution of a base manifest/config/layer for base.index must
refuse. All existing selected-platform ancestry, native/R1 joins and real-source limitations
remain mandatory. Original snapshots and literal policy revision remain unchanged.

Adapter §8's synthetic-hash rule applies to retained synthetic objects and their byte identities.
The explicitly typed external-original identities in adapter §§2–3/7 remain external: in particular,
R1 §4.1's exact pinned dependency-wheel/base declarations are preserved, not replaced with invented
hash preimages. Their presence does not assert acquisition or observation of those original bytes.
Every retained report, canonical lock projection, synthetic OCI object and supporting blob must
still have its own hash/size computed from the actual bytes it represents. Only the contract's
already enumerated external identity fields may remain unresolved to packet bytes; a missing
retained object cannot be reclassified to escape closure. Synthetic records/statements are labeled
as such and prove no real wheel installation, base inspection, native scan or release eligibility.
This resolves the blanket fixture wording against the specific external-identity grammar without
changing the frozen snapshots or production admission policy.

## Retained installed-state evidence amendment — adopted 2026-09-20

The tagged native parser discards Status and only filters values containing lowercase `deinstall`;
it cannot establish the stronger installed predicate in the original adapter. The complete human
source reference is retained in [Syft dpkg/image source evidence](provider-installation/syft-dpkg-image-source-reference.md),
SHA256 `dafa45da3ed88d85ab4d90338bb14c8609c75ec0580d1f741d3ae0ac95924475`.
This is inspection evidence, not a runtime schema or proof of an observed scanner execution.

Controller read the complete194-line amendment and checked its R1/policy/file-inverse interfaces.
Adopt its exact §§2–6 from the byte-preserved snapshot, SHA256
`3aa42b57fd79cbe0101300e009eb68888a558a712b6b952a675e41a9b3ad2ecd`:

- Map v2 has one required retained raw `dpkg_status` leaf joined to the real staged R1 file and
  all admitted Debian identities. No invented native Status field or weaker substring proof.
- The deliberately strict raw-control subset refuses every non-installed/removed/residual or
  unsupported record. This may refuse authentic releases; no general Debian compatibility claim.
- Only that metadata file has explicit root-level SPDX containment and empty component ownership;
  all other file coverage, license and origin rules remain. No arbitrary unowned-file exemption.
- Source-path alias analysis is bounded by40 hops,8192 unique derived paths and4096 UTF-8 bytes
  per path. It does not introduce a global existence requirement for unrelated dangling symlinks.
- The exact policy changes to revision2 and interpretation
  `provider-release-adapter-preflight-r2-dpkg-status-v1`, with the three named coverage deltas.
  Old policy/map is refused for new admission; historical record loading remains unchanged.
- The sole writer implements the amendment within the same62 owned product paths and reruns the
  affected source/renderer/evaluator/service/API and new boundary vectors before final review.

The cost is an explicit policy/fixture extension and narrower compatibility, rather than a claim
that absent evidence was verified. No native producer, trusted deployment, license approval,
release key or external acquisition is supplied or authorized by this amendment. Task46 remains
unaccepted until its connected implementation and independent review pass.

## Complete graph byte bound — explicit proof clarification, 2026-09-20

Independent static closure review confirmed a conflict in the installation snapshot's §8
V8–V11 table: a **coherent installation graph larger than64 MiB is unreachable for this
closed cap1 profile**. The original snapshot remains unchanged. Only that literal test vector
is superseded by the split proof below; no production limit, complete graph check, admission
rule or other V8–V11 case is weakened.

`DomainStore._check_graph` counts each distinct reachable BlobRef once. It does not count every
CAS file/database row, record-body byte or event, or recursively traverse identities inside
opaque retained blobs. The exact ancestry is verified2 -> stage1 -> provider request/receipt ->
one candidate, with the receipt pointing to the same request. Candidate/owner/bootstrap roots
cannot supply additional arbitrary parents or blobs; old B and consumption records are not
ancestors. The following conservative bound assumes no deduplication:

| Reachable blob group | Maximum bytes |
| --- | ---: |
| All installation packet objects |50331648|
| Candidate manifest and descriptor, each262144 |524288|
| Candidate registration, canonical input bound |1048576|
| Up to32 candidate support documents, each65536 |2097152|
| Exact provider source18 aggregate |524288|
| Provider request |65536|
| Preserved inventory |16384|
| Provider receipt |16384|
| Stage postcondition |8192|
| Release trust/context |24576|
| **Conservative total** |**54657024**|

This is strictly below the unchanged **67108864** graph-byte limit; tighter bundle constraints
are not needed for the argument. The source caps/closed associations are enforced by the
candidate, provider-source, request/receipt/stage and installation codecs/loaders. Identity-only
source archives, retained inventory descriptions and unrelated CAS files cannot inflate this
graph. Any future limit/association change requires renewed closure review.

Required proof for this vector is now:

1. A separately labelled **shared DomainStore** test with the literal production constants:
   four distinct actual16 MiB blobs under valid ordinary immutable records, and an aggregate
   record reaching all four, must succeed at64 MiB. A new parent reaching that aggregate plus
   one distinct actual one-byte blob must refuse at64 MiB+1. Assert rollback of the new record
   and reference indexes; distinguish unattached presealed CAS bytes from committed authority.
   Do not lower any cap or simulate successful verification. Use an existing owned new test file.
2. Separate coherent installation proof through the real final `_put_in_transaction` and
   complete graph check, with exact reachable reference/blob observations and the finite bound
   recorded/asserted from code-owned limits and association shapes. Keep genuine missing/
   replaced blob, store/commit failure, exact replay and rollback tests unchanged.
3. Report these as shared-guard and installation-closure evidence, **not** a successful exercise
   of an impossible coherent installation overflow. Do not add forbidden ancestry, pad unrelated
   CAS, or relabel malformed-history rejection as that original vector.

The scoped independent review is retained in the controller's `task-46-graph-bound-review.md`;
it confirmed54657024<67108864 and no legal additional ancestry, but executed no tests and issued
no Task46 acceptance. Actual literal-bound execution and final connected review remain required.
The same62 product paths and all native/live/release authority boundaries remain unchanged.

## B historical replay and fresh-run proof — terminology clarification, 2026-09-20

The installation snapshot's §7/§8 B7–B11 wording "B expiry" / "old evidence expires" does not
introduce a B evidence TTL. The accepted `provider-conformance.md` explicitly gives B no evidence
expiry policy; future C owns qualification freshness and its maximum seven-day expiry. Keep that
boundary unchanged. Original snapshots remain byte-identical.

For this bounded unit, the additional temporal proof is: complete a real legacy B run; advance
controlled service and worker-client clocks beyond that retained run's admission deadline while
the independent sources remain valid; preserve its exact historical reply with no new probe;
perform actual installation verification and a fresh explicit verified B under a new command ID.
Assert the new actual six-connection/four-vector execution and its distinct retained reply. This
proves fresh-run independence past an old run deadline, not qualification or evidence expiry.
Pending-run deadline recovery/restart is a separate required case, not a substitute for it.

The connected independent reviewer and controller checked this interpretation against the accepted
B contract. No new timestamp field, TTL, qualification authority, source relaxation or scope is
introduced. Final execution and connected review remain required before Task46 acceptance.
