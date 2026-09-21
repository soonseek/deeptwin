# Post45 installation boundary — release evidence to the existing installation head

2026-09-20. Advisory architectural decision/map only; not a promoted contract, implementation
plan, Task45 acceptance, trust provisioning, native enrollment or release approval. Task43/44
are accepted dependencies. Task45's promoted `contracts/provider-conformance.md` is a planned
producer/consumer contract here, not inspected or accepted implementation. This note writes only
this file; no product changes, imports, tests, SQL, network, native operations, keys or commits.

## Decision and exact next slice

Recommend **one connected provider installation-verification slice** after accepted45:

`independently provisioned release trust -> retained startup source -> bounded signed release
evidence intake -> actual43 stage/candidate graph -> verified installation revision2 in the SAME
history/head -> fresh fixed-vector B on that exact verified descendant -> historical read/replay`.

Its positive artifact is an actual immutable `extension_installation` version2/state `verified`,
linked backward to the exact staged version1, with the existing stable-extension head advanced
atomically with its command receipt and event. This verifies immutable artifact/release evidence;
it grants no qualification, semantic port, model use, credential resolution, billing or dispatch.
The one-provider/optional-one-tool stage topology remains. Do not implement replacement, uninstall,
retirement, another registry or all binding lifecycle arms in this slice.

**A new independently provisioned release-trust source must precede the positive verification
commit. Native qualification enrollment and the full Q1 qualification bootstrap need not precede
artifact-only installation verification.** They remain prerequisites for C. Receipt keys authorize
stage statements only. Existing candidate metadata and Task45 `matched` cannot supply release trust.

This is a proposed contract boundary, not a claim its missing inputs already exist. Before promotion,
close the finite producer and evidence-policy definitions in §3; acceptance must include the actual
byte/source/store/HTTP vertical in §7. A disconnected parser, exported unused source handle, empty
installation registry, callback returning success or permanently denied generic importer would not
meet the recommendation. Offline synthetic integration can establish that vertical without native
collector evidence, while all real-environment positive claims remain separately blocked.

Alternatives considered:

| Approach | Consequence | Decision |
| --- | --- | --- |
| Full Q1 five-file bootstrap first | Couples artifact verification to absent collector enrollment and signed core runtime release; source production is useful but does not advance an installation by itself. | Keep Q1's publication pattern and future C role separation; narrow the immediate prerequisites. |
| Minimal release bootstrap + actual verification + shared history/B adaptation | One artifact-level transition with a concrete existing stage producer and future C consumer; no native-observer privileges needed for code development. | Recommended connected slice. |
| Qualify/bind from B or old in-memory registry results | Omits authenticated release evidence, independent native checks and complete semantic-port behavior. | Reject. |

The brainstorming skill supplies the architectural alternatives/scope decision; writing-plans
supplies dependency and ownership discipline only. The delegated docs-only scope overrides their
default interviews, implementation-plan artifact and commit workflow. No implementation is dispatched.

## 1. Authority and snapshot hierarchy

Canonical requirements are `.specify/memory/constitution.md` II/IV/IX and Execution Boundaries;
`specs/001-autonomous-release/spec.md` FR-001/010/031/032/033, US1–US7 and SC-001/010;
`contracts/runtime.md` extension matrix and installation/qualification/binding separation;
`contracts/extension-ports.md` core-owned provider operations and exact five-field BindingSlotKeyV1;
`data-model.md` §3.1; and `decisions.md` ADR-014. They require an official browser product, honest
evidence levels, separate immutable lifecycle records, same-store heads/events and no executable
runtime download or core Engine access. Neither this note nor an advisory overrides them.

`contracts/provider-receipt-consumption.md` supplies Task43's fixed stage/v5 semantics; its original
active/unaccepted header is historical implementation-dispatch text. Task43/44 acceptance is an
input from the controller's accepted baseline, not inferred from that header. The promoted45
contract explicitly supplies B's current-stage admission, immutable raw-evidence history and C
obligations. No moving Task45 new file was read. Of its eleven modified existing paths, only
`provider-conformance-before/app/deployment/prepare_service.py` was read, using its accepted44 copy.
Other source observations below are unchanged accepted43/44 dependencies, not actual45 code:

| Exact inspected input | SHA-256 |
| --- | --- |
| `specs/001-autonomous-release/contracts/provider-conformance.md` | `3e80a8ea358cf107f0d851ec245132bd5619a4921cb93ee876ceecfd6b25d167` |
| `.superpowers/sdd/resumption-plan/provider-conformance-before/app/deployment/prepare_service.py` | `ebf08947548017ea4eba636d432b89a220adb19ddcccab701869ed8a68de2892` |
| `app/deployment/prepare_records.py` | `1a28a688c44fe17f463b9a8f2313917668d7316fbbcef483e56a0aa6c02641ca` |
| `app/deployment/prepare_storage.py` | `aa00f60fa72baac2cbaaca0218bcdd9825707e515ab12b42598d92d693a8e1d8` |
| `app/deployment/provider_receipt_records.py` | `09c30339a0be7c0832e426d738e2c8575c575ebd50e0e160d655446bbc0db20c` |
| `app/domain/extension_installation.py` | `b488d6d35aa8b12d922a0456c80c1acc5eac26110fb5361f638e23c1b2e5aec5` |

All six requested advisory documents were read completely:

- `durable-qualification-next-step.md` is old tool-port/v3 advice. Its trust warning and lifecycle
  distinction remain useful; its two-tool scope, stage-only assessment recommendation, v3 migration
  starting point and old line/API references are not the post45 provider plan.
- `post43-conformance-qualification-bridge.md` remains advisory. Its D2 split between core and native
  observations is retained; provisional43 status and proposed B fields/caps are superseded where
  the promoted45 contract now fixes them. Its five-minute B freshness is a proposed C rule.
- `qualification-bootstrap-options.md` recommends Q1 but is NOT promoted. Full five-file source,
  CoreBootContext, collector enrollment and C profiles do not exist by virtue of this advice. §2
  below explicitly narrows its release prerequisite without silently changing a canonical source.
- `provider-release-producer-draft.md` R1 and `provider-release-producer-review.md` are advisory.
  The scoped R1 review resolved the missing `input_root` finalization dependency in the design;
  it did not accept implementation, real archives, scans, license approval, keys or release signing.
- `native-runtime-identity-research.md`, including its appendix, is research/advice. Its stock
  sibling-PID refusal is a code-derived blocker, not a native result. The socket/pidfd alternatives
  require a new reviewed contract and real canaries; no workaround is included here.

## 2. Minimal new source, with explicit Q1 compatibility

Propose an **installation-release source**, separate from the immutable18-file provider bundle:
one fixed read-only root `/run/deeptwin/installation-release-sources`, containing exactly
`documents/release-trust.json` and `documents/installation-release-context.json`. These are proposed
names, not existing files or a frozen grammar. Trust is public, bounded, instance/origin/profile
scoped, with finite release-review key/delegation entries and validity limits. Context binds the
trust bytes, code-owned verification-policy/profile version, original topology ID and exact
provider context/geometry digest. No new topology identity, source18 epoch or slot is introduced.

Producer -> fixed initializer -> retained reader -> actual verifier are one connected source seam.
An outer renderer invokes the existing provider renderer with its exact ten raw inputs, preserves
all18 output bytes and proves that stripping only the declared new service/volume/config/mount/pin
additions yields the complete old expansion. It emits its own new recipe/output identity. The
initializer independently recomputes those two documents, performs fixed-root no-replace publication
and never writes old roots. The new initializer image is an explicit release input, not a fabricated
hash of source code or a default trusted image.

The runtime reader consumes a catalog-registered frozen startup pin, the actual borrowed source18
handle and exact OriginProfile; its constructor is not a caller-provided policy dictionary. Recheck
actual ordered source bytes, retained inode/metadata and mount/backing identity before admission and
again before final commit. Register the new root in the old finite optional-root alias observer and
test both reader directions. Preserve the old return shape and old source bytes. New live mounts,
same-byte inode replacement, backing aliases or nested overlays cannot silently rebase either handle.
All newly acquired handles get attempt-all/primary-preserving cleanup; Task44's three corrected
store surfaces do not establish lifecycle safety of a new source factory automatically.

This adopts Q1's immutable companion-volume mechanism, not its full qualification payload. Later C
can borrow this same release source and add a separately versioned Q1 qualification source for
native signer/enrollment/core-runtime facts; it must compare shared release identities explicitly.
Do not copy the release keys into a competing source or widen their role to native observer. The
old five-file Q1 text would need explicit advisory/contract reconciliation at that later gate.
No later file may be appended to this two-file root or source18 under the old pin. A real deployment
creation/recreation to install any new root is external work, not authorized by implementing its
offline producer/reader.

Missing source denies fresh verification but leaves historical read/replay available. The first
profile has no hot rotation/rebind. Expiry/replaced policy denies new authority; historical issuance
remains auditable. Immediate revocation is not fabricated from expiry: active-use invalidation and
externally authorized disable/recreation need their explicit later mechanism.

## 3. Finite authority origins and actual evidence availability

| Origin | What it may establish | Present availability / explicit limit |
| --- | --- | --- |
| Existing same-vault core authority | Owner command, actual candidate/request/receipt/stage graph, policies, one shared installation head and atomic evidence/event history. | Accepted43/44 code. Browser owner transports evidence but cannot choose trusted keys or issue a release review. |
| Deployment security provisioning | Independently approved public release roots and exact delegated statement/policy/platform scope, supplied before startup. | New source contract/code/provisioning required. Stage `instance_operator` trust, HMAC and an uploaded matching key establish none of this. |
| Artifact release reviewer | Attributable signed review of exact artifact graph, independently produced inspection/provenance/license/scan evidence under one enumerated review profile. | No admitted real provider release review found in inspected sources. Role is proposed `provider_artifact_review`; neither `native_qualification_observer` nor final qualification issuer. |
| Core artifact verifier | Recompute closed evidence/subject joins and policy decision, then issue verified installation in DomainStore. | New production implementation; no supplied verifier callback/pass map. Signature verification authenticates bytes under the bootstrapped role, not safety by itself. |
| Later dedicated native collector + core C evaluator | Collector signs enumerated native observations; core combines them with current permissions/full semantic evidence to issue qualification. | Not part of this slice. Enrollment, keys, Engine/proc visibility and positive platform evidence are unavailable/not authorized. |

No sixth authority is inferred from source code hashes, native PID strings, candidate metadata,
worker replies, renderer output or successful synthetic tests.

The verifier needs actual bounded public evidence bytes, not hash-only references: the same retained
candidate/descriptor/ProviderLineage and schemas; source/dependency inspection reports; selected
platform final-filesystem report; SBOM and license material; source/build provenance review; security
scan observations; and a signed release-review statement binding all of them to the exact OCI
index/selected manifest/config/ordered layers, BuildIdentity inputs, inspector/profile and policy.
The selected filesystem report must match lineage's actual extraction-evidence hash. Other-platform
claims remain separate; inspecting one selected platform does not prove native support for both.

The provider-release R1 producer can be the byte producer for source/dependency/filesystem reports.
Its finalizer must reopen the original base graph and wheels through explicit `input_root`, perform
fresh independent inspection and compare retained report bytes before signing-workflow output. The
core does not redo that external image inspection by trusting an uploaded report parser: it trusts
only a specifically delegated review attestation to that inspection, and independently checks the
retained byte/graph joins it can check. The attestation boundary and signer assumptions must be
documented. Core receives bounded reports/public support bytes, never OCI layers, executable uploads,
arbitrary URLs, paths or runtime fetch instructions. The release authority, not the browser owner,
approves the actual artifact examination.

**Pre-contract producer gap:** the R1 draft supplies no complete security-scan observation grammar,
scan policy, authenticated provenance-review decision or license-approval evidence producer. Its
unsigned image allow-policy is not these missing decisions. Freeze one finite release review profile
with exact accepted producer IDs/versions, raw scan result coverage, scanner/database identity and
freshness, source/build subject joins and an attributable license decision for the actual material.
Unknown/incomplete findings cannot pass; no `checks={...passed}` substitute. This profile must be
implemented by an actual producer and exercised against controlled byte inputs in the acceptance
vertical. An approved signature over invented successful observations would not establish it.

Real pinned base/wheel bytes, final release artifacts, approved public roots and those review/scan/
license decisions were not obtained by this task. Repository lock declarations and inert candidate
support leaves establish only expected identities. Task45 also changes some core files named in the
old release-producer source list; re-enumerate the accepted45 import/source closure and recompute
future release hashes rather than reusing its old44-file inventory blindly. Existing images/locks
and historical installation bytes must not be rewritten. Copyright-owner T084 release permission
remains separate from a local artifact verification mechanism and cannot be issued by this code.

## 4. Shared v5 history transition and fresh B after verification

The current source has a real structural barrier, not just a missing API:

- `prepare_records.verify` checks a bijection of ALL `extension_installation` records to stage rows,
  compares heads to stage anchors only at revision1, and `_anchor_dimensions` caps that kind at16.
- `prepare_storage.DDL_V5` reuses the stage-only installations/head layout: installation version1,
  one stage row per extension, head revision1. C1–C5 are existing immutable layout identities.
- Both `prepare_records._load_installation` and `provider_receipt_records.load_installation` require
  today's installation head to equal the historical stage anchor. The domain validator accepts only
  staged version1 bodies. Simply inserting version2 would make old services/history unavailable.
- Planned45 §3 resolves only a current staged revision1 and §6 rehydrates through that shared
  journal. Thus a new head would also break B unless these consumers change together.

Propose one reviewed immediate v5->v6 same-writer migration, not a second registry. Retain stage rows
as immutable acceptance indexes; add a bounded verification-history arm in the SAME deployment
family and broaden the EXISTING stable-extension head to reference either its exact stage1 or its
one verified2 descendant. For this finite first arm, at most one verification successor per accepted
provider, no generic arbitrary revision/replace support. Keep existing tool stages unchanged. A
contract must freeze literal new DDL/checksum/hash namespaces, caps, incoming-FK handling and migration
rollback before coding; this note deliberately supplies no guessed SQL.

One composed verifier owns complete bijections: stage anchors to accepted request/receipt/
consumption/events; verified successors to exact stage, evidence, command and verification event;
one current head to the terminal allowed history member. Separate historical stage proof from the
current-head check without dropping either. Legacy stage loaders retain their exact byte/graph/
event predicates and consume the composed history's checked ancestry/current-head result. No
recursive `journal -> verification -> journal` or caller-asserted history object. Installation
kind counts/byte/edge/blob caps expand only for the explicit successor arm; orphan/version3/extra
event/extra verification rows remain rejected.

Preserve every old record/blob/edge, stage row/hash, typed NULL, rowid where contract-required,
request lifecycle, consumption.effect_ref, event sequence/cursor and frozen reply. Migration itself
creates no verified record or invented old event. Only a fresh authenticated command consumes
current release evidence and CAS-advances stage1->verified2. Failure leaves stage/head unchanged.
Store command input includes exact expected head and exact bounded evidence identity; same
command/actor/input replays the original result before source/clock work, conflicts refuse, and
evidence/head/command/event commit atomically. Historical rehydration uses retained issuance-source
bytes and rules, not today's missing/expired source or a new native probe.

**B refresh is in this SAME coordinated slice, not deferred until C.** C may need new B evidence
after the proposed five-minute freshness limit, restart or qualification expiry. Keeping B's fresh
resolver permanently staged-only would strand every verified installation.

Preserve old45 stage anchors, 21-field subject projections, context digests, suite bytes, intent/
report records, tables' historical meaning and frozen replies. Add a separately versioned fresh
admission context/profile that records BOTH exact historical stage ref and the actual admitted
current installation ref/head. Admit only (a) the existing current stage1 or (b) the specifically
verified current version2 whose exact parent is that stage1 and whose artifact/source/service fields
all match. The new profile's digest binds the verified ref; never reinterpret an old digest as
having done so. Continue resolving IDs/UID/GID/slot through the actual journal, with no DTO factory.
Every scheduled B guard compares the captured exact head and source; drift makes the run incomplete
or leaves pending under45's existing owner/store rules. An in-flight staged-profile B can become
incomplete when verification wins the head race; its replay never silently upgrades its context.

Task45's accepted files, new closed record/export branch and any required conformance storage
transition must be reconciled at that contract gate; no compatibility-by-assumption and no blanket
`revision >= 1` check. A post-verification B run executes the same six real authenticated connections
and independent four-vector oracle. Its result remains a private-transform subset. Historical B
rehydration proves the stage ancestor and original raw comparisons without demanding today's head;
fresh admission separately proves the current verified descendant. C consumes both joins.

## 5. Dependency order through later qualification/binding

| Order | Producer -> consumer | Required shared history/currentness |
| --- | --- | --- |
| 0 | Accepted45 -> frozen follow-on contract | Reconcile actual accepted implementation to planned45; preserve all old B histories and shared44 lifetime semantics. No work on moving45 paths. |
| 1 | Actual release byte/scan/provenance/license producer + independent reviewer -> closed evidence verifier | Freeze finite observation/policy definitions and intake byte closure. Controlled producers/signatures prove mechanism; real approved release inputs remain an external gate. |
| 2 | Minimal independently provisioned source producer/initializer -> actual startup verifier source | Original source18 exact equality; finite outer mount projection, alias/currentness and ownership proof; no dynamic owner trust. |
| 3 | Same-store historical stage + authenticated evidence -> installation2/head/event; coordinated B resolver -> fresh evidence | v5 migration, actual owner route, exact-head transaction, read/reopen/replay and B-after-verification must pass as one connected milestone. Steps1–3 are dependencies within the recommended slice, not isolated dead-code deliveries. |
| 4 | Later Q1 enrollment/core-runtime source + core permission resolver + complete provider semantic producer + independent native observer -> C intent/intake/evaluator | Exact verified descendant/stage ancestor and actual B rehydration; larger qualification context includes runtime/platform/framework/API/schema/port/capability/scope/config/grants/handles/policy. Resolve currently unbuilt runtime identity and live-generation joins. |
| 5 | C all-five decision -> qualification record/context head/event -> exact binding command -> real port consumer | Permission/isolation/egress/secret/compatibility all required; expiry at most7days and no later than evidence/policy limits. Separate BindingSlotKeyV1 head CAS, current grants/config/handles/service and later dispatch enforcement. |

Artifact verification does not require B to pass; B cannot verify licenses/artifact scans. Retaining
a B reference as supplemental evidence must not make it an approval prerequisite or substitute.
Later C requires complete matched B under its explicit policy, plus all missing coverage. Its own
expiry/freshness rules cannot be inferred from B. A qualification refresh references the same
verified installation and creates new qualification history; it does not advance installation again.

Native identity remains a real later blocker: the research appendix derives peer PID zero for stock
sibling PID namespaces while current transport requires positive PID. No relaxed constructor, host
PID/shared namespace change, handle-transfer workaround or synthetic native success is authorized.
Rootful Linux is a proposed enrolled-collector profile, not demonstrated support; rootless/Desktop
non-ECI remain conditional and ECI has no established positive profile. Enrollment and both required
deployment-platform canaries must be handled explicitly. A collector report cannot supply the missing
`provider-port-v1` capabilities/catalog/model_step/status/cancel/effect implementation; private
catalog/text, a narrower selector or renamed private port cannot satisfy it.

## 6. Prospective ownership, not a grant to edit now

New paths proposed for a later finite contract:

- `app/deployment/installation_release_contracts.py`, `installation_release_render.py`,
  `installation_release_sources.py`, `installation_release_schema_exports.py`: closed source and
  byte joins, additive outer renderer, retained reader and detached schemas.
- `app/operations/installation_release_source_init.py` and its narrowly scoped private publication
  helper: independently recomputed fixed-root publication; no arbitrary filesystem API.
- `app/extensions/installation_verification_contracts.py`, `installation_verification_evidence.py`,
  `installation_verification_service.py`: finite signed-evidence policy, actual byte evaluation,
  authenticated command/final writer/replay. History storage remains owned by deployment modules.
- `app/deployment/installation_verification_records.py`: bounded same-family successor/graph/event
  verification; no second installation head or duplicate journal owner.
- `app/api/installation_verification.py`, its fixed route contribution, exact v2 source/input/
  record/reply schema files, and focused source/migration/evidence/HTTP/lifecycle test files.
- External release production belongs to the already-proposed `deploy/provider_release/` family,
  expanded only with the concrete review/scan producer profile needed by §3. Its real artifact/tool
  inputs and evidence-origin contract must be resolved before an implementation ownership freeze.

Existing paths needing coordinated prospective changes: `app/deployment/prepare_storage.py`,
`prepare_records.py`, `provider_receipt_records.py`, `provider_prepare_records.py` (historical
inventory projection audit), `prepare_service.py`; `app/domain/extension_installation.py` and narrow
domain schema/event exports; `app/deployment/source_common.py`; `app/api/first_party_catalog.py`,
`web_boundary.py` and the chosen startup contribution; exact shared migration/schema/route tests.
Task45's planned resolver/contracts/records/service/domain/export/tests require the versioned B
admission change after acceptance. These names derive from its CONTRACT, not inspected moving code.
The future contract must enumerate exact files and bounded deltas, including no-op exclusions; this
map is not a wildcard ownership grant. No edits to worker/broker/listener, original recipe/Compose
template, source18 schemas/bytes, geometry, slot identity, credentials or model catalog are proposed.

## 7. Consumer acceptance and STOP boundaries

The defining controlled acceptance is actual candidate/source18 -> actual43 stage -> actual45 B
history -> new release-source producer/initializer/reader -> genuine bounded controlled artifact
observations and separately signed synthetic review -> authenticated installation command ->
verified2 plus existing head/event -> new actual B run on that verified descendant -> close/reopen
without sources/worker -> byte-identical old stage/B/verification replay and rehydration. No injected
successful verifier, fake journal, synthetic head, manually inserted verified row or registry flag.
Physical/native observations in these fixtures must be labeled simulated; cryptography, byte joins,
source files, records, route composition and transactions exercise their real implementation.

Required rejection and compatibility cases:

1. Owner-uploaded trust, receipt/observer key used as release key, wrong delegation/policy/platform,
   expired trust, altered review or refreshed outer hashes cannot verify. Missing actual report,
   scan coverage, license decision, provenance input or selected-image join leaves stage unchanged.
2. Same-vault/source/candidate/service/artifact mismatches, foreign refs, stale expected head,
   source inode/mount/backing changes and final-writer races refuse without partial head/event.
3. v5 with mixed tool/provider stage history and preexisting B matched/mismatch/incomplete/pending
   records migrates without changing old bodies/replies/events/C1–C5. Missing/orphan successors,
   head skips, corrupted history or unknown profiles refuse; every write-failure checkpoint rolls
   back. Migration-only restart manufactures no verification result.
4. Old B replay remains readable after verified2. A fresh versioned B run works on exactly that
   current verified descendant; unrelated descendants, altered artifacts and stale heads fail.
   A concurrent head advance cannot make an old staged run appear current. Future C can obtain
   refreshed B without reinstallation; no five-minute freshness claim is hardcoded into B itself.
5. Restart with absent release/provider sources still reads/replays retained history without new
   clocks/RNG/probes; fresh verification fails unavailable. Missing source never becomes a trusted
   empty source. Interrupted commands and ambiguous finalization never imply a verified state.
6. Verified2 never emits qualification/binding/model-ready authority. Incomplete provider semantics
   and unsupported native profiles remain visible blockers even when artifact verification succeeds.

STOP promotion if the evidence producer/profile/byte closure is undefined, trust bootstrap is only
an uploaded key, migration cannot retain old history, B cannot refresh on verified descendants, or
the finite input caps cannot hold genuine required evidence. Resolve those contract issues locally;
do not substitute success assertions. STOP real-environment positive verification until approved
release roots and genuine artifact/provenance/license/scan evidence exist. STOP qualification until
separately enrolled native observations, runtime identity/currentness, permission resolution and
complete semantic coverage exist. Native enrollment/keys/release approval/paid calls/publication
are not authorized by this proposal.

Offline code can advance safely: after those contract definitions are frozen, implement the actual
source-to-store vertical and exercise it with controlled archive/report bytes and test-only signing
material. Production accepts only independently provisioned roots and genuinely supplied evidence;
an unavailable real deployment remains unavailable. This is testable implementation of an artifact
transition, not proof that a real installation is verified, a supported native profile works or any
of the seven whole-product journeys is complete.
