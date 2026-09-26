# Canonical data model

2026-09-07 · `domain-v1` · Design under delegation. No schema migration has run.
Use this with runtime-v1, growth-v1 and OPS-002; shared fields here resolve naming aliases,
not permission to omit their richer evidence. All versions are explicit and migrations tested.

## 1. Common types and invariants

`EntityRef = {kind, id, version, sha256}` addresses an immutable content version. IDs are
opaque app-generated UUIDs, versions positive integers and SHA-256 lowercase 64 hex.
Compute immutable content body → digest → reference envelope, in that order. A record's own
`ref/sha256` never appears in its digest preimage. The content body includes schema version,
stable identity/version, creation/actor, parent content refs, purpose and policy refs plus
domain content; canonical UTF-8 JSON uses sorted keys, no NaN/Infinity and decimal strings.
Mutable availability/access-observation/redaction-view metadata lives outside that immutable
body; a changed original policy/content creates a new version. Artifact digests cover exact
bytes separately from the metadata record digest. Publish test vectors to avoid self-reference.
Integer/decimal validation rejects bool-as-number, negative counts and unbounded strings.
`Ref` in growth-v1 maps to EntityRef; existing B1 ref formats keep compatibility adapters.

`ObjectRef` from OPS-002 is an event/navigation locator: mutable setup/session records may
not have a content hash yet. It MUST NOT substitute for EntityRef in approval, model input,
artifact delivery, comparison or knowledge compilation. A versionless UI selection is resolved
and frozen server-side before a state-changing command. IDs/hashes alone confer no access.

Immutable records share `schema_version`, `created_at_utc`, `actor_ref`, `parent_refs`,
`purpose`, `access_policy_ref`, `retention_policy_ref`, `availability`, `redaction_state`.
Refs resolve within one vault and authorize by purpose before loading bytes. Deleted/missing
content yields an explicit gap, not empty text. Availability and permission are independent.

`Actor` is `human|system|provider|service_client|test_actor` with trusted origin. A service client
binds its own principal record and scope and can never be projected as a human decision. UI display
names and model messages cannot assert human identity. A model-created example may be stored as synthetic,
never upgraded into a real human alternative or approval by changing its label.

Purpose partitions: `operational`, `diagnosis`, `inquiry_audit`, `evaluation_development`,
`evaluation_sealed`, `release_evidence`. Sealed evaluation ground truth and provider secrets
never enter a runtime projection. Inquiry audit is episode-scoped, not a person-profile index.

### 1.1 Acyclic vault bootstrap (ADR-008, implementation review correction)

Ordinary actor/policy refs cannot create their own first hash dependencies. A fresh vault
therefore has one `domain-genesis-v1` record with `kind=vault_genesis`, `id=vault_id`, version1,
UTC creation time and fixed `local-deny-by-default-v1` profile, and no content refs. Three
strict `domain-bootstrap-v1` records (system actor, initial access policy, retention policy)
point only to that exact genesis. Their payloads are fixed host-system provenance,
`deny-by-default-v1`, and OPS manual-core-retention defaults respectively. These roots contain
no human approval, provider connection, external dispatch permission or user-learning evidence.
All ordinary records use the common header above and can reference these already sealed roots.
Subsequent policy/actor versions use ordinary headers and existing refs, not another bootstrap.

Only the host store's atomic first initialization may install this root set into an empty
domain vault. JSON parsing/hash validity alone grants no initialization authority. Import,
restore, provider/model content, and normal create-record API cannot mint a new root, replace
an existing root set, or label synthetic actors as humans. Store resolves all refs within
the bound vault, rejects foreign/missing roots and transitive cycles, and keeps new/restored
dispatch disabled pending appropriate explicit authority. This is an engineering correction,
not a user-approved operating environment. The pure-schema chain test uses actual hashes;
storage atomicity/authorization is independently tested in T007–010/T015–016.

## 2. Storage ownership and atomicity

Keep the existing `intake.sqlite3` database and legacy tables/IDs. Add a versioned migration
ledger and new normalized domain tables with immutable JSON bodies, content hashes and
foreign-key/indexed relationships. Existing file BLOBs remain readable during migration;
copy to verified CAS in staging, register refs, compare bytes/hashes, only then switch new
reads. Do not silently delete old bytes or rewrite revisions. Public APIs use stable IDs.

Content objects live under an app-owned content-addressed store with 0600 files, partitioned
by access purpose. Use staging → write/fsync → validate/hash → atomic rename → synchronize
the destination parent directory → DB reference commit under verified SQLite synchronous=FULL
(and macOS fullfsync where supported). Qualify this on the target filesystem rather than
claiming universal hardware power-loss guarantees. A failed DB commit leaves an unreferenced object eligible for explicit reconciliation,
not an apparently successful artifact. DB refs never point to uncommitted partial files.
No automatic core-object deletion based only on temporary absence of a reference.

The DB owns logical state. YAML/Markdown/JSON exports are immutable projections; import creates
a new reviewed version. Canonical bytes and indexes are not independently editable truths.
WAL/foreign keys/busy timeout and explicit transactions are configured and measured. Parallel
provider work does not imply parallel uncontrolled writers; a bounded writer service serializes
state changes. Checkpoint DB contains cursors/refs, never credentials or canonical approvals.

Within one transaction: (a) reserve request+budget+dispatch intent+event, (b) accept a terminal
result+artifacts already sealed+budget reconciliation+event, (c) count one comparison and update
best/reference/patience, (d) compare-and-swap exact active environment+approval+activation event.
Unique `(vault,command_id)` and `(series,round_result_id)` constraints reject double application.

No cross-process/remote exactly-once guarantee is claimed. Write-ahead intent and an immutable
idempotency key prevent local duplicate dispatch; unknown remote outcome remains unknown.
On restart inspect leases/ownership and ledger before checkpoint replay. A stored result can
satisfy a repeated node visit only if its exact execution ID and envelope hashes match.

## 3. Intake, provider and environment records

### Authenticated worker transport capture (partial T018/T040)

`worker_response_capture` is an ordinary immutable `domain-v1` version1 record. Its ID is
the exact committed dispatch command UUID. Closed content is versioned
`worker-response-capture-v1`: `command_id`, `attempt_id`, `permit_id`, typed
`execution_envelope_ref`/`runtime_profile_ref`, original `lease_fence`, authenticated
`connection_id`, `requester_boot_id`/`worker_boot_id`, `channel_id`,
`requester_service`/`responder_service`, `message_id`/`correlation_id`/`message_type`,
one exact `payload_blob`, and ordered zero-to-256 `{descriptor, blob}` artifacts.
The descriptor retains the stream's exact batch/request/ordinal/count/media/size/hash.
Equal artifact bytes may share a BlobRef while retaining distinct ordered descriptors.

The host derives purpose/access/retention from the exact verified operational execution
envelope and episode metadata from its registered permission descriptor. The capture's
actor is the verified host-system root; its parent is the envelope, with the runtime profile
as an ordinary content dependency. Dependency taint is inherited, without issuing any read
grant. Exact payload bytes are stored without parsing or reformatting. Common record metadata
contains no raw payload, path, credential, provider error, or hidden reasoning.

The canonical attachment is an append-only `response_captured` attempt-journal entry with
`schema_version=worker-response-capture-journal-v1`, `command_id`, exact `capture_ref`, and
`classification=pending_validation|quarantined`. One original command has at most one capture;
changed duplicates conflict. This adds TEXT values, not a new mutable capture table or DDL
migration. Existing migration checksums and redacted `transport_observed` wire shapes remain.

The record, dependency indexes, permission descriptor, capture journal, count/enum-only
`attempt.response_captured` event, and eligible transport state change share one existing
SQLite writer transaction. Physical blob registration precedes attachment, retaining the
16 MiB per-blob default and 64 MiB reachable-graph ceiling. Failure may leave registered,
unattached private blobs; core retention remains manual-only, without automatic deletion.

| Entity/table | Required fields beyond common header | Integrity rules |
| --- | --- | --- |
| `OwnerAccount` | actor_ref, login_name, state, created/updated, recovery_epoch | first bootstrap only; recovery replaces authenticator and revokes every old session/service client/unconsumed human capability/pending approval or consent challenge, not historical actor identity/evidence |
| `Authenticator` | owner_ref, kind/version, password_hash_or_binding, parameters, created/rotated/revoked | initial profile is argon2-cffi 25.1.0 Argon2id v19, salt16/tag32/memory65536KiB/time3/parallelism4; encoded parameters retained; raw password absent; successful-login rehash is stronger-only; future WebAuthn/SSO adapters cannot silently inherit qualification |
| `BrowserSession` | owner_ref, token_digest, cookie_profile/path, canonical_origin, csrf_epoch, created/last_seen/idle_expires/absolute_expires/revoked, auth/recovery epoch, network profile | raw token is 32 random bytes and only SHA-256 digest persists; idle 12h/absolute 7d; loopback uses random-host/path-scoped HttpOnly Strict cookie, HTTPS uses Secure `__Host-` cookie; both use exact session-root HMAC profile; login/recovery rotates; browser cookie and service-client bearer namespaces never fall back |
| `SessionRootReceipt` | schema/version, generation_id, key_id(non-secret random label), recovery_epoch, created_at, state(initial_genesis/maintained), deployment_receipt_ref? | root bytes are absent; absent root permits one O_EXCL+fsync initial genesis matching exact config epoch, while an exact valid existing genesis makes init a verify-only no-op; malformed/ownership/epoch mismatch fails and never replaces it. Maintenance requires a request-bound deployment receipt; equal root/config/DB epoch permits normal service, while a valid receipt plus strictly greater root epoch permits only restricted startup and one atomic DB epoch advance/revocation; rollback/skipped mismatch fails closed |
| `Work` / existing works | id, title_ref, current_revision, created/updated | mutable pointer only; previous revisions retained |
| `WorkRevision` / revisions | work_id, revision, input_text_ref, source_refs, interpretation_edits, input_origin | original explanation is not feedback; concurrent edits use expected_revision |
| `ChatMessage` / chat_messages | work_id, content_ref, referenced_entity_refs, semantic_origin, actor, sequence, optional_command_ref | shared across all views; source/role references frozen, chat is not automatically alternative/approval |
| `ProposedCommand` / proposed_commands | message_ref, command_kind, exact_target_ref, structured_args_ref, proposer, required_authority, validation_state | model proposal has no human authority; domain command validates target and challenge before execution |
| `Source` / sources | artifact_ref, source_kind, supplied_by, acquisition_event, rights_ref | uploaded/downloaded originals immutable; no document instruction authority |
| `Extraction` / extractions | source_ref, parser_version, supplied_spans/pages, omitted_ranges, status, derived_artifact_ref | full/partial/unreadable explicit; no false full-read claim |
| `SpeechSession` | work_id, input_revision, state, engine distribution/hash/model/profile+model revision, media_type/sample metadata, byte/time/chunk limits, retention_mode, next_sequence, started/finalized/cancelled/expired timestamps, provisional/final/user-owned segment refs | `stt-local-ko-v1` is 16kHz mono PCM s16le → exact-range `<i2` validation → contiguous float32 `/32768.0` → pinned PCM-only `deeptwin-faster-whisper` small CPU-int8 and accepts only `ephemeral_only`; raw bytes/int16 ndarray, media decode, VAD and remote fallback are rejected; raw audio has no application-level durable store and worker restart loses it, while host-admin/swap/crash capture is outside the claim; durable modes are rejected until separately versioned/qualified; state is created/capturing/finalizing/finalized/cancelled/failed/expired; late/final segments cannot overwrite user-owned edits/new work |
| `SpeechUtterance` | session_ref, utterance_id, sequence, sample_start/end_exclusive, boundary_reason, state, final_command_id?, final_segment_ref?, created/finalized | ranges are consecutive within one session; state open/finalizing/finalized/interrupted; browser_silence/manual_stop/track_ended/max_duration are typed reasons; finalization is idempotent and silence may start a next utterance without ending the session |
| `SpeechChunk` | session_ref, utterance_ref, sequence, command_id, content_digest, byte_count, sample_start/end_exclusive, tail_kind, received_at, volatile_staging_ref?, state | payloads are consecutive non-overlapping PCM ranges; ordinary chunks are 16,000 samples/32,000 bytes and only an utterance-final tail may be 1..16,000 real samples with no padding; unique session+sequence and command ID; RFC 9530 digest replay stable, changed duplicate/gap/overlap conflicts; uncommitted tmpfs bytes are accepted only after digest match and erased at cancel/finalize/expiry/crash |
| `SpeechSegment` | session_ref, utterance_id, segment_revision, source_chunk_start/end, kind(provisional/stable_hint/final/user_owned), engine_profile_ref, text_ref, token/timestamp refs, target_anchor/span, edit_epoch, supersedes_ref?, created_at, application_state | only a newer same-utterance result may supersede provisional display; stable_hint requires two agreeing rolling windows but remains provisional; final text applies only by exact work-revision/edit-epoch CAS, otherwise remains a pending transcript; user edits create a fence no late result may cross |
| `WorkModel` / work_models | work_revision, goals, completion, input/output contracts, roles/risks/unknowns, source citations, confirmation | source interpretations separate; user confirmation targets exact content |
| `ProviderConnection` / provider_connections | provider, mode, binding_ref, auth_state, key_present, checked_at, credential_handle, erasure_state? | handle backend-only; Claude api only; Codex subscription/api separate; GET returns a persisted redacted snapshot only; `revoked_pending_erasure` immediately blocks catalog/send and cannot be re-enabled by restart |
| `CredentialEnvelope` / deployment credential files | schema, algorithm_id, key_id, vault_id, record_id/version, provider, auth_mode, created_at, nonce_b64u, ciphertext_and_tag_b64u | `credential-record-v1`/`xchacha20poly1305-ietf`; ADR-008 canonical clear header is AAD; UTF-8 JSON≤96KiB with exact keys/canonical unpadded base64url, decoded nonce=24B and `encrypted.ciphertext`+tag=16..65,552B; `(key_id,nonce)` unique globally and nonce is not duplicated in ciphertext bytes; duplicate/unknown keys, invalid UTF-8/encoding/version, reuse, truncation or header/ciphertext swap fails closed; immutable generations rotate atomically |
| `CredentialMutationIntent` | command_id, mutation_kind(create/rotate/revoke_erase/retire), nonsecret_envelope_fingerprint, connection/record target+expected version, state, stored_record_ref?, binding_revision?, terminal_receipt_ref? | pending control intent precedes gateway `store_at`; exact gateway query distinguishes a stored receipt, durable pending ingress and nonterminal unknown. Unknown/absence never permits a fresh command or replacement secret because delayed admission may still commit. Only a durably journaled pending, never-receipted gateway command with demonstrably irrecoverable ingress becomes terminal `secret_input_lost`, after which explicit fresh command+re-entry may retry; previously receipted missing ciphertext instead requires exact recovery/maintenance. Exact idempotent record then provider-binding CAS; valid create orphan, rotated predecessor and delete target become non-dispatchable `cleanup_pending`; delete first reaches `revoked_pending_erasure` and invalidates dependent catalogs/selections; only maintenance exclusion plus verified removal of all locally managed superseded/staging copies reaches `erasure_completed`; restart/rollback never restores retired provider authority or reuses new secret under a consumed command ID |
| `ServiceClient` / service_clients | client_id, owner_ref, name, allowed_network_profile, state(active/revoked), current_credential_revision, created/updated/revoked_at, row_revision | durable principal and CAS head; cannot bootstrap, impersonate a human approval, manage deployment/other clients, or exceed its immutable grant revisions |
| `ServiceClientCredentialRevision` / service_client_credentials | client_ref, revision, credential_digest, scope_refs, issued/expires/last_used/revoked, backward-only previous_ref, row_revision | raw bearer is returned exactly once and never stored; expiry is no later than 24 hours; rotate appends then atomically advances the client head and revokes the predecessor, while recovery/revoke invalidates every active revision. Authentication updates last_used through bounded CAS and applies exact-client, trusted-network and per-client/routing rate buckets before command dispatch |
| `OriginProfile` | deployment_profile_id, lowercase 32-hex-character 128-bit instance_id, mode(local_loopback/portable_https), scheme, canonical host, effective integer port, normalized trailing-slash base_path/origin_base, digest | digest is SHA-256 of ADR-008 canonical preceding fields excluding itself; port always records 80/443 even if omitted while origin_base omits defaults; local path is `/<hex32>/`, portable uses dedicated host+`/`; ambiguous URL forms rejected; ID is DNS-label-safe; edge/control-plane/bootstrap/session/CSRF/receipt bind one digest; no capability/TLS secret |
| `BuildInputLockManifest` | schema_version, generated_at, resolver/tool versions, target runtimes/glibc/platforms, artifacts[], upstream_image_locks[], model/component locks[], license/provenance refs, build_input_lock_set_digest | T089 build input only; `build_input_lock_set_digest` is derived from the canonical manifest excluding only itself; every artifact has exact source, version, size, digest, platforms and redistribution status; every upstream image lock accepts an OCI index or Docker manifest list and records `{media_type,digest,size_bytes}` for the top descriptor and every selected platform manifest/config/layer descriptor; SBOM/attestation artifacts are kept separately as `provenance_descriptors[]:{media_type,digest,size_bytes,artifact_type?}` and never mistaken for runnable platforms; it never stands in for an unbuilt DeepTwin service image |
| `PlatformSupportManifest` | schema_version, release_id/source_commit, compose_digest, data_schema_version, build_input_lock_set_digest, tested host/runtime/browser profiles, required capabilities, `image_locks[]`, edge_profile, evidence refs | T081 final distribution output; each final image lock requires an OCI index v1 and is `{image_id,services[],index:{media_type,digest,size_bytes},platforms[{platform,manifest:{media_type,digest,size_bytes},config:{media_type,digest,size_bytes},layers[{position,media_type,digest,size_bytes}]}],provenance_descriptors[]}`; portable edge records image/version/config digest, operator-TLS-secret mode and SSE/header canaries; one digest is never reused as if all service/platform images were identical |
| `DeploymentRequest` | common envelope: schema/domain (`deployment-request-v1`/`deeptwin-deployment-request-v1`), request_id, closed kind, canonical-base64url 32-byte request_nonce, request_digest, instance_id, origin_profile_digest, exact kind-specific `effect_payload`, closed `preconditions`, created_by/at, expires_at. Release/update/recovery use their exact branch-specific precondition object and payload; every extension branch requires `preconditions={}` and carries its sole arm conditions inside the §3.2 `effect_payload` | immutable closed tagged union; request_digest is SHA-256 of ADR-008 canonical exact fields excluding itself; a payload from another kind, a mixed field or a duplicated precondition is rejected. Product may prepare/display/export only and no product owner/service client authority executes host effects; no extension request names a future installation or retirement record/head |
| `DeploymentRequestLifecycle` | request_ref/digest, revision, previous_revision?, state(prepared/cancelled/receipt_pending/accepted/rejected/expired), transition_actor/time, cancelled_at?, receipt_consumption_ref? | mutable CAS state is outside immutable request digest; cancel wins against receipt unless acceptance committed first; restart preserves winner and `deployment.request_cancelled` |
| `DeploymentReceipt` | common envelope: schema/domain (`deployment-receipt-v1`/`deeptwin-deployment-receipt-v1`), request ref/digest/nonce/kind, instance/origin digests, deployment profile, operator adapter/version, exact matching kind-specific `effect_result`, started/completed, outcome/failure class, claimed/verified/unverified facts, key_id/trust_set_digest, trust_class, signature. Release result binds old/new release/schema/image-lock/epoch; extension result is exactly one §3.2 stage/replace/uninstall-current/retire-superseded schema and never names a future installation or retirement record/head | immutable closed tagged union matching the request kind; Ed25519 signs ADR-008 canonical exact fields excluding signature; public key32/nonce32/digest32/signature64 use strict base64url-no-padding and strict schema; dedicated job signs, versioned deployment trust set verifies, separate exchange volumes use opposite mounts/digest filenames/atomic rename/tombstone; reject mixed-kind/browser upload/stale/replay/cross-instance/origin; signature authenticates authority statement but component handshakes/migration/qualification/dependency gates prove product-used state; raw capability/TLS/private signing key absent |
| `DeploymentReceiptConsumption` | consumption_id, receipt_ref/digest, request_ref/digest, winning_lifecycle_revision, consumed_at, transition/effect_ref, actor/system_ref, transaction_id, public_event_id | unique(receipt_ref) gives one-use/replay authority without mutating signed receipt. Successful stage/replace/uninstall-current consumption commits only after exact postcondition evidence, atomically with the immutable installation record, installation head and event. Successful retire-superseded instead creates the target-keyed service-retirement record/head and event while compare-and-swapping the unchanged current installation head plus zero-dependency proof. Failed/unknown receipts atomically consume only into their closed lifecycle/event and create no success record/head; an unknown target state blocks rollback/rebinding until a new observed-state reconciliation event resolves it. The event carries transaction/head IDs but does not content-reference consumption, so no digest cycle exists |
| `ModelCatalogSnapshot` / catalogs | connection_binding, fetched_at, complete, model entries, capability_evidence | pagination must complete; nullable capability not guessed; no static fake account list |
| `ModelChoice` / model_choices | node/purpose, catalog_ref, model_id, effort/thinking, requested modalities, selection_authority | exact binding/compatibility; default vs override; immutable per environment |
| `RuntimeProfile` / runtime_profiles | adapter/version, instruction/tool/isolation hashes, qualification_refs, permitted_purposes | declared profile != observed preflight; changing any material component requires recheck |
| `DesignDecision` / design_decisions | work_model_ref, atomic_lens_refs, composition_ref, functional_claims, proposed effects, conflicts/abstentions | lens identity is audit evidence; functional effects alone projected to critic |
| `DesignCandidate` / candidates | work_model_ref, decision_refs, graph_ref, parent_candidate_refs, generation_call_refs, review_refs | repairs/merges are new immutable versions with independent review |
| `GraphVersion` / graphs | nodes, typed edges, artifact schemas, model/grant/memory/observation refs, completion/budget refs | runtime-v1 compiler + semantic review; no executable arbitrary predicates |
| `EnvironmentVersion` / environments | graph_ref, instructions, compiled knowledge refs, models/tools/grants, scope, compatibility, rollback_ref | full executable bundle hash; no private lens interpretation in operational payload |
| `EnvironmentHead` / environment_heads | environment_id, active_version_ref?, revision | only authorized activation CAS; draft selection not active growth promotion |

### 3.1 Framework extension records and trust tiers

The implemented inert owner-registration prerequisite uses the distinct
[`extension-manifest-v2` candidate contract](contracts/extension-candidates.md), its acyclic
descriptor, actual operational blob refs and an `extension_manifest` domain anchor. That contract
freezes the private version-1 index/command/content-accounting DDL, checksum, row hashes and CAS.
Historical v1 manifests remain readable unchanged; candidate registration grants no installation,
qualification, binding or stage authority.

An extension is code/configuration bound to one core-owned semantic port version, not any uploaded
file, prompt, SKILL.md, model-proposed tool name or generic worker message. The transport envelope
authenticates and bounds delivery; `ExtensionPortContract` defines the kind-specific meaning. The
closed kind/artifact/port/trust/staging matrix is normative in runtime-v1 and these records preserve
its durable authority:

`BindingSlotKeyV1` is the single closed key value
`{port_contract_version,target_scope_fingerprint,purpose,binding_slot_id,
capability_selector_digest}`. `binding_slot_key_digest` is SHA-256 of its ADR-008 canonical JSON.
The same object and recomputed digest are stored or resolved by every port config, binding record/
head, command/result/event and rollback-retention record; a four-field projection or independently
rebuilt UI key is not the same key. `extension_id` remains a candidate value and is excluded.

| Entity | Required fields | Integrity rules |
| --- | --- | --- |
| `ExtensionPortContract` | extension_kind, port_contract_version, allowed artifact/trust/staging tuples, operations, base config/request/result/error schema IDs+digests, effect classes, idempotency/cancel/outcome/artifact semantics, compatibility range | core-owned and versioned independently from an extension; the field-complete eleven-port/44-schema source is `contracts/extension-ports.md`. An extension schema may only refine the matching base schema and cannot redefine authority, effect, selector, operation, terminal/error state or retry meaning; the SDK never authors this record |
| `ExtensionServiceDescriptor` | descriptor version, extension ID/version and port-contract version, service/image ID, one OCI index media type/digest/size, closed `platforms[]` entries each with platform and manifest/config/ordered-layer descriptors, command/protocol, non-root UID, resource/isolation/network/secret declarations, broker endpoint identity and exact dedicated socket/named-volume mounts, SBOM/provenance/license refs | executable extensions only; it does not contain the manifest digest. The manifest points one-way to this descriptor digest, and the staging request binds both digests to avoid a digest cycle. Each staging request selects and binds exactly one platform entry from the same index/descriptor; the two required hosts therefore exercise one extension identity/index with arm64 and amd64 entries. Exact immutable OCI bytes/platform and descriptor-declared mounts are bound to the receipt and handshake; no mutable tag, host path, runtime download, product/runtime-initiated post-start or unmanifested mount, or product-controlled container action |
| `ExtensionManifest` | extension_id/version/kind, port_contract_version, definition digest or service-descriptor ref, source/provenance/license, framework/API/schema compatibility ranges, config/operation refinement schemas, declared grants/resources/network/filesystem/secret needs, isolation profile, migration/uninstall policy | manifest is inert data; discovery/import cannot execute code or grant authority; kind/artifact/port/trust tuple must be in the closed matrix; all bytes and schemas are frozen |
| `ExtensionInstallation` / `ExtensionInstallationHead` | manifest and artifact/service descriptor digests, actor/time, staging authority, external deployment request/receipt/postcondition refs where applicable, state/revision, verification/scan refs, previous-record digest; head key=`extension_id` | immutable artifact-level history. `discovered → staged → verified` and failed/suspended/revoked/uninstalled are distinct; verified does not transition to qualified/enabled and can receive later qualifications. Stage/replace appends a new installation; uninstall-current appends an uninstall tombstone and advances the same stable-identity head. A later stage may CAS from that exact tombstone and next monotonic revision without treating the removed service as current. A superseded service retirement never advances this head. Every head change and public event commit atomically |
| `ExtensionServiceRetirement` / `ExtensionServiceRetirementHead` | exact superseded installation ref and five-field service tuple, extension ID, immutable expected current installation head, descendant-proof ref, zero-dependency snapshot ref/digest, deployment request/receipt/postcondition refs, state(`retired`), revision, actor/time; head key=`superseded_installation_ref.installation_record_digest` | separately records physical retirement of a non-current executable service. Initial V1 head is absent→revision1 only. The current installation head must remain the same descendant and its service reachable; active binding, retained rollback and active-environment dependency sets must still be empty at receipt consumption. It cannot mark the installation bytes unverified, rewrite ancestry, retire a current/non-ancestor service or authorize uninstall |
| `ExtensionQualification` / `ExtensionQualificationHead` | exact verified installation record/digest, platform/runtime/framework/API/schema/port refs, conformance suite/version, declared/observed capability digests, permission/isolation/egress/secret/compatibility results, non-passing failure codes, qualified scope, evidence verification, qualified/expiry times, previous qualification ref and recheck trigger; head key=`installation_digest + qualification_context_fingerprint` where the fingerprint covers exact platform/runtime/framework/API/schema/port/capability/scope | multiple immutable qualifications and independent context heads may reference one verified installation. Unknown/failure/unverified evidence cannot pass; expiry or changed runtime/platform/framework/API/schema/port/capability invalidates only the matching context head and dependent binding. A fresh qualification never mutates or reinstalls the artifact |
| `ExtensionBindingRevision` / `ExtensionBindingHead` | extension_id plus installation/qualification refs, port kind/version, instance/environment/work/node/purpose scope, exact `BindingSlotKeyV1` and digest, core-owned `capability_selector`, config ref, opaque credential/grant refs, revision, expected previous head, backward-only `previous_ref`/`supersedes_ref` and optional `rollback_of_ref`, state; head key=`binding_slot_key_digest` | activation, disable, supersession and rollback append a new immutable revision and atomically CAS exactly that slot head with the corresponding public event. Same key means competing candidates and has exactly one active head; a different port version, slot ID or selector digest coexists even under the same port/scope/purpose. Config key/digest and binding record/head are byte-identical. `extension_id` identifies the candidate and is never silently derived into the slot key. A prior revision never gains a forward pointer; rollback rechecks current qualification, reachable service and grants rather than reviving stale authority; active environment versions bind immutable revisions |
| `ExtensionRollbackRetentionRevision` / `ExtensionRollbackRetentionHead` | exact `BindingSlotKeyV1` and recomputed digest, exact `target_binding_revision_ref`, target extension/installation ref and five-field service tuple, state(`retained`,`released`,`consumed`), revision, expected previous retention head, backward-only previous ref, observed current binding head, actor/time/reason, command/event refs; head key=`binding_slot_key_digest + target_binding_revision_ref.binding_record_digest` | every supersession or disable that displaces an active binding atomically creates revision 1 `retained` for that exact old binding revision. A rollback requires that retained head, consumes it in the same transaction as the new active binding revision/event, and creates a distinct retained head for the newly displaced binding. The owner-only release command below CAS-advances `retained → released` without changing installation/binding heads or deleting history. Released/consumed history is not a retirement dependency and cannot authorize rollback; four-field/cross-port/digest-mismatched, stale, cross-slot, current-target or mismatched installation/service requests fail closed |

Manifest, installation history/head, target-keyed service-retirement history/head, qualification/head,
binding history/head, rollback-retention history/head and their public event sequence commit in the
applicable DB/CAS transaction.
Startup rehydrates them and reconciles incomplete
staging receipts, expiry, runtime/platform/framework changes, revoked grants and stale keyed heads before
dispatch. Crash or concurrent qualification/binding may leave an explicit pending/failed record but
cannot expose a binding without its committed event or expose an event without the binding.

Executable replacement is non-destructive: the operator stages the new digest under a distinct
service identity while the old service remains reachable, then DeepTwin handshakes, qualifies and
CAS-supersedes the keyed binding. The old service becomes a superseded retirement target, not the
current installation head. A later `extension_retire_superseded` request can retire exactly that
ancestor while leaving the new head unchanged, but only after active-binding, retained-rollback and
active-environment dependencies are all absent at both preparation and consumption. Removing the
actual current service is the different `extension_uninstall_current` arm and advances the
installation head to an uninstall tombstone. An in-place destructive replacement is unsupported; if an
operator performs one outside the contract, the UI records `rollback_unavailable`/outage instead of
claiming binding rollback.

#### Binding slots and capability selectors

`binding_slot_id` is a stable identifier assigned by a core consumer or environment definition to a
logical dependency slot, such as one graph node's browser-read tool, an environment's default model
provider, or the instance's primary storage. It is not generated from an extension ID, installation
digest or display name. `capability_selector_digest` is the canonical digest of one closed core-owned
selector:

| Port family | Closed selector fields |
| --- | --- |
| provider | `{selector_kind:provider_role,provider_id,auth_mode,account_binding_ref?}` |
| managed provider runner | `{selector_kind:managed_provider_role,provider_id,runner_profile_ref}` |
| model runtime | `{selector_kind:model_runtime,runtime_profile_ref,required_modalities[]}` |
| tool | `{selector_kind:tool,tool_id,tool_version,operation}` |
| artifact codec | `{selector_kind:artifact_codec,direction,media_type,operation}` |
| lens | `{selector_kind:lens_application,application_point,lens_role}` |
| evaluator | `{selector_kind:evaluator_role,rubric_ref,evaluation_stage}` |
| storage / credential vault | `{selector_kind:instance_singleton,capability:primary_storage\|credential_vault}` |
| export sink | `{selector_kind:export_destination,destination_kind,operation}` |

Nullable selector fields are present as null when inapplicable. Selector arrays are sorted before
canonical hashing. Two qualified extensions targeting the same port/scope/purpose coexist when they
occupy distinct slot IDs or selectors. They compete only when all five head-key components are exact;
then a different `extension_id`, or a new version/digest of the same stable extension ID, may become
the candidate only through the expected-head CAS. Instance-critical storage/vault use the fixed
singleton slot and selector and therefore cannot coexist as active primaries. Disable and rollback
address the exact slot key, not all bindings owned by an extension.

### 3.2 Exact extension deployment tagged unions

The common deployment envelope is defined above and in `contracts/api.md`. For every extension kind,
the common-envelope `preconditions` field is the closed constant empty object `{}`. It has no
extension precondition semantics and cannot mirror, override or supplement the arm. The arm's
`effect_payload` is the sole precondition authority and is exactly one closed object below
(`additionalProperties=false`). Any current/head/next-revision or future-record field outside that
payload, including under `preconditions`, is rejected. A field listed as forbidden MUST be absent,
not null. `expected_current_head` is
`{extension_id,revision,installation_record_digest}` and always describes already committed state.
`selected_platform_entry` is the exact descriptor entry
`{platform,index_digest,manifest_digest,config_digest,ordered_layer_digests[]}`. `new_service_effect` is
`{service_identity,socket_mounts[],named_volume_mounts[],network_policy_ref,resource_profile_ref}` and
contains only descriptor-declared effects. A request-bound **service tuple** is exactly
`{service_identity,manifest_digest,service_descriptor_digest,selected_platform_entry_digest,
image_manifest_digest}`. An already committed installation reference is exactly
`{extension_id,revision,installation_record_digest}`.

`zero_dependency_snapshot_ref` resolves an immutable `ExtensionDependencySnapshot` whose exact
content is `{extension_id,target_installation_record_digest,observed_current_head,
active_binding_refs:[],retained_rollback_refs:[],active_environment_refs:[],observed_at}`; the three
arrays MUST be present and empty. Its companion `zero_dependency_snapshot_digest` is the canonical
digest of those bytes. `retained_rollback_refs` is derived only from rollback-retention heads in
state `retained` whose target installation is the snapshot target; immutable binding history and
`released`/`consumed` retention revisions remain queryable but do not populate it. A retained head is
made absent only by a successful rollback consumption or the exact owner release transaction below,
never by deleting history or inferring that a supersession was old enough. `current_descendant_proof_ref`/`current_descendant_proof_digest` resolve a
frozen backward-lineage traversal proving that the request's current head belongs to the same
`extension_id`, has a greater installation revision than the retirement target and reaches that
target through immutable previous-record links. These artifacts are evidence, not authority: the
core repeats the head CAS, lineage traversal and zero-dependency query when consuming a receipt.
`expected_installation_head` is a closed stage-only union: `{state:"absent"}` for first installation,
or `{state:"uninstalled",revision,installation_record_digest}` for an exact committed uninstall
tombstone. The first form requires next installation revision 1; the second requires tombstone
revision + 1. Neither represents a reachable current service.

| Kind / request schema ID | Required `effect_payload` fields | Forbidden fields |
| --- | --- | --- |
| `extension_stage` / `deeptwin.extension-stage-request.v1` | `schema_id`, `extension_id`, `manifest_digest`, `service_descriptor_digest`, `selected_platform_entry`, `new_service_effect`, exact `expected_installation_head`, `expected_next_installation_revision` from the stage-union rule | every reachable-current/superseded installation or retirement field, old/current service field, dependency/lineage/uninstall/retirement field |
| `extension_replace` / `deeptwin.extension-replace-request.v1` | `schema_id`, `extension_id`, `manifest_digest`, `service_descriptor_digest`, `selected_platform_entry`, `new_service_effect`, `expected_current_head`, `expected_next_installation_revision` equal to current revision + 1, `old_service_identity_must_remain_reachable:true` | absent-head marker, every superseded-installation/retirement/dependency/uninstall field and every future installation/head ref |
| `extension_uninstall_current` / `deeptwin.extension-uninstall-current-request.v1` | `schema_id`, `extension_id`, `expected_current_head`, `expected_next_installation_revision` equal to current revision + 1, exact `service_to_uninstall`, `zero_dependency_snapshot_ref`, `zero_dependency_snapshot_digest`, `uninstall_reason` | absent-head marker, manifest/descriptor/platform/new-service fields, every superseded-installation/descendant-proof/retirement field and every future installation/head ref |
| `extension_retire_superseded` / `deeptwin.extension-retire-superseded-request.v1` | `schema_id`, `extension_id`, `expected_current_head`, exact `superseded_installation_ref`, exact `service_to_retire`, `current_descendant_proof_ref`, `current_descendant_proof_digest`, `zero_dependency_snapshot_ref`, `zero_dependency_snapshot_digest`, `expected_retirement_head_state:"absent"`, `expected_next_retirement_revision:1`, `retirement_reason` | `expected_next_installation_revision`, absent-head marker, manifest/descriptor/platform/new-service fields, current-uninstall fields and every future installation/retirement record/head ref |

`new_service_effect.service_identity` in replace MUST differ from the service identity reachable from
`expected_current_head`. Stage rejects any reachable current service; it accepts only never-installed
absence or an exact uninstalled tombstone so the stable extension identity is reinstallable. Uninstall-current resolves
`expected_current_head` and requires `service_to_uninstall` to equal that installation's five-field
tuple; its dependency snapshot targets the same digest. Retire-superseded requires
`superseded_installation_ref` to be a strict ancestor of the still-current expected head,
`service_to_retire` to equal that ancestor's tuple, an absent retirement head and a dependency
snapshot targeting the ancestor. The current service therefore remains current while the old
physical service is retired. For stage/replace/uninstall-current the sole arm precondition includes
the next installation revision; retire-superseded has no next installation revision and instead
preconditions the unchanged current head plus target-keyed absent retirement head/revision 1. None is
a duplicate common-envelope bag or a reference to a record that cannot exist until after the receipt.

`binding_slot_key` is exact `BindingSlotKeyV1`; every carried `binding_slot_key_digest` equals its
recomputed canonical digest. `expected_current_binding_head` is exactly
`{revision,binding_record_digest,state}` with state in `active|disabled`; and
`target_binding_revision_ref` is exactly `{revision,binding_record_digest}`.
`ReleaseExtensionRollbackRetention` is the closed owner command
`{command_id,extension_id,binding_slot_key,binding_slot_key_digest,expected_current_binding_head,
target_binding_revision_ref,target_installation_ref,target_service_tuple,expected_retention_head:{revision,
retention_record_digest,state:"retained"},reason}`. The target binding must be a strict backward
ancestor of the exact current binding head for the same `BindingSlotKeyV1`, and its installation and
five-field service tuple must equal the retention revision. The closed result is exactly
`{command_id,extension_id,binding_slot_key,binding_slot_key_digest,expected_current_binding_head,
target_binding_revision_ref,target_installation_ref,target_service_tuple,expected_retention_head,
new_retention_revision,new_retention_record_digest,state:"released"}`; all nine repeated request
identity/head/ref fields are byte-for-byte equal. Success atomically commits
that immutable revision, its keyed head and `extension.rollback_retention_released`; it preserves the
binding head, installation head, binding history and service reachability. Missing/mixed/unknown
fields, a current or cross-slot target, stale heads, repeated release and tuple mismatch are rejected
without mutation. This is the reachable A→B→release-A-retention→retire-A path; releasing means A can
no longer be selected by rollback, while its historical binding record remains visible.

The matching `effect_result` is exactly one of four separate closed result arms:

| Result schema ID | Required fields and arm constraints | Forbidden fields |
| --- | --- | --- |
| `deeptwin.extension-stage-result.v1` | `schema_id`, `extension_id`, request-equal `expected_installation_head`, request-equal `expected_next_installation_revision`, `old_service:{presence:absent}`, outcome-constrained `new_service` | every reachable-current/superseded/retirement ref, dependency/uninstall field and any field not listed |
| `deeptwin.extension-replace-result.v1` | `schema_id`, `extension_id`, request-equal `expected_current_head`, request-equal `expected_next_installation_revision`, outcome-constrained `old_service`, outcome-constrained distinct `new_service` | every superseded/retirement/dependency/uninstall field, future installation/head ref and any field not listed |
| `deeptwin.extension-uninstall-current-result.v1` | `schema_id`, `extension_id`, request-equal `expected_current_head`, `expected_next_installation_revision`, `service_to_uninstall`, `zero_dependency_snapshot_ref`, `zero_dependency_snapshot_digest`, outcome-constrained `old_service`, `new_service` | target/new-artifact/platform/service-effect, superseded/retirement field, future installation/head ref and any field not listed |
| `deeptwin.extension-retire-superseded-result.v1` | `schema_id`, `extension_id`, request-equal `expected_current_head`, `superseded_installation_ref`, `service_to_retire`, `current_descendant_proof_ref`, `current_descendant_proof_digest`, `zero_dependency_snapshot_ref`, `zero_dependency_snapshot_digest`, `expected_retirement_head_state:"absent"`, `expected_next_retirement_revision:1`, outcome-constrained `current_service`, `target_service_before`, `target_service_after` | every next-installation/new-artifact/current-uninstall field, future installation/retirement record/head ref and any field not listed |

The stage result has exactly six fields; replace exactly six; uninstall-current exactly nine; and
retire-superseded exactly fourteen. They are not a shared optional-field bag. A service
observation is exactly one tagged arm:

- `{presence:"absent"}`;
- `{presence:"present",service_identity,manifest_digest,service_descriptor_digest,
  selected_platform_entry_digest,image_manifest_digest,reachable_after_effect,observed_at}`; or
- `{presence:"unknown",expected_service_identity,expected_manifest_digest,
  expected_service_descriptor_digest,expected_selected_platform_entry_digest,
  expected_image_manifest_digest,failure_class,observed_at}`.

The absent arm forbids all identity/digest/time fields; the present arm requires them all and
`reachable_after_effect` is boolean; besides `presence`, the unknown arm permits only the seven
listed diagnostic/expected fields. Its four expected digests and expected identity are assertions copied from the
request-bound tuple, not observations of service state. In every extension receipt, result
`extension_id`, every repeated head/ref/revision/digest/service tuple and its schema ID equal the
matching request values byte-for-byte. Define the request-bound **new tuple** as
`{service_identity=new_service_effect.service_identity,manifest_digest=request.manifest_digest,
service_descriptor_digest=request.service_descriptor_digest,
selected_platform_entry_digest=SHA256(ADR-008 canonical selected_platform_entry),
image_manifest_digest=selected_platform_entry.manifest_digest}`. Define the request-bound **current
tuple** by resolving the already committed installation record whose exact digest is in
`expected_current_head`, and the request-bound **superseded tuple** by resolving the exact committed
`superseded_installation_ref`. Uninstall's `service_to_uninstall` equals the current tuple and
retirement's `service_to_retire` equals the superseded tuple field-for-field at both preparation and
receipt verification. A present `new_service` must equal the new tuple field-for-field; an
unknown `new_service` must repeat all five new-tuple values in its `expected_*` fields. A present
`old_service` must equal the current tuple field-for-field; an unknown `old_service` must repeat all
five current-tuple values in its `expected_*` fields. Retirement `current_service` is similarly
bound to the current tuple and both target observations are bound to the superseded tuple. There is no
operator-selected identity/digest in a result.

The receipt `outcome` for these arms is exactly `succeeded|failed|unknown`, with these exhaustive
presence constraints:

- stage always has `old_service=absent`; succeeded requires new present, failed permits new absent or
  unknown, and unknown requires new unknown;
- replace succeeded requires current-tuple old present with `reachable_after_effect=true` and a
  distinct new-tuple new present; failed requires old present/unknown and new absent/present/unknown,
  with any present/unknown arm bound as above; unknown requires at least one unknown arm and every
  non-absent arm remains tuple-bound;
- uninstall-current never permits old absent: succeeded requires current-tuple old present and new
  absent; failed requires old present/unknown and new present/unknown; unknown requires old
  present/unknown and new unknown. Every present/unknown new arm is bound to the current tuple;
- retire-superseded succeeded requires current-tuple `current_service` present and reachable,
  superseded-tuple `target_service_before` present and `target_service_after` absent. Failed requires
  current present/unknown, target-before present/unknown and target-after present/unknown. Unknown
  requires current present/unknown, target-before present/unknown and target-after unknown. Neither
  failed nor unknown may report target absence, and no present/unknown arm may name an unrelated
  service.

Any equality mismatch, missing tuple source, stale/changed current-head resolution, non-ancestor
retirement target, nonempty dependency set or cross-arm observation rejects the receipt before
postcondition/consumption. Results may repeat only request-bound already committed head/installation
refs; no request or receipt contains a future installation, retirement record or head ref.

Digest and authority causality is one-way. Stage/replace/uninstall-current use existing descriptor/
manifest/current-head/dependency inputs → request → signed receipt → independent postcondition
evidence → immutable installation record/tombstone → installation head → receipt consumption/event.
Retire-superseded uses the existing superseded installation, preserved current head, descendant proof
and zero-dependency snapshot → request → signed receipt → independent current-service/target-absence/
dependency-recheck evidence → immutable service-retirement record → target-keyed retirement head →
receipt consumption/event, while CAS-verifying that the installation head is unchanged. Neither a
receipt nor an earlier artifact references a future record. Event and consumption share already
allocated non-content transaction/event IDs but do not content-hash each other. Startup reconciliation
either completes the exact arm transaction or leaves the receipt unconsumed and non-dispatchable.

Kinds are `provider`, `model_runtime`, `tool`, `artifact_codec`, `lens`, `evaluator`, `storage`,
`credential_vault` and `export_sink`. Executable kinds use digest-pinned OCI extension services
staged by the external deployment operator; code-free lens/evaluator definitions may be bounded-
imported by the authenticated product owner. Instance-critical `storage` and `credential_vault`
ports additionally require backup/recovery compatibility, exclusive ownership and restart/migration
gates. `export_sink` cannot transmit until a separate exact target-bound confirmation. A model
catalog entry is provider data, not executable code.

A binding cannot introduce a grant or credential handle absent from the manifest. A trusted
binding verifier resolves every opaque grant/config/credential reference against the exact current
qualification, port contract and scope before the registry commits the binding head. A supplied
digest, built-in label, signed staging receipt or role name is never sufficient execution authority.

Trust tiers are `deployment_trusted` (storage/credential-vault only), `runtime_worker`,
`definition_package`, and `managed_provider_runner`. The last is still a `provider` extension: it
may own one official subscription auth volume and dedicated provider egress but no Docker/operator
authority, DeepTwin credential root/records, work DB/artifact volume or untyped IPC. The built-in
Codex runner passes the same semantic port/qualification/binding/event lifecycle and cannot borrow
the broader `deployment_trusted` tier.

`DesignApproval` initially authorizes configuring a design. `RunConsent` authorizes a specific
execution or bounded policy. `ActionApproval` authorizes a material external action. Growth's
`PromotionDecision` authorizes a validated version for scope. They share identity/target/expiry
fields, not interchangeable effects. UI may present several together but stores distinct grants.

## 4. Execution, tools and artifacts

| Entity/table | Required fields | Integrity rules |
| --- | --- | --- |
| `Run` / runs | work_revision, environment_ref, consent_ref, mode, budget_ref, manifest_ref, status/revision | mode live/replay/snapshot/isolated-comparison fixed; original manifests sealed |
| `NodeExecution` / node_executions | run_id, node_id, visit_id, loop_indices, parent_execution_refs, status | a repeat visit differs from a retry; no synthetic elapsed progress |
| `Attempt` / attempts | execution_id, attempt_no, envelope_ref, reservation_id, profile_ref, lease/owner, status | preflight through terminal deadline; duplicate/late responses cannot replace accepted result |
| `ArtifactInputSelectorV1` | source_artifact_ref, selector_kind(`whole`,`text_span`,`table_range`,`page_region`,`image_region`,`time_range`,`structured_path`), locator_ref, purpose_ref, selected_byte_count, selector_digest | immutable; source/purpose/digest must equal the request entry and purpose; selection cannot escape the exact artifact/version or conceal omitted bytes |
| `ArtifactInputBindingV1` | artifact_ref, selector_ref or null, declared_media_type, role | closed four-field value shared by frozen projections and extension requests; artifact/media/selector/purpose equality and per-operation cardinality come from extension-ports §3.9 |
| `FrozenTurn` / turns | attempt_ref, purpose, input refs/projection_hash, ordered `artifact_input_bindings`, model_choice, output_schema, grants, deadline/budget | complete prompt projection privately auditable without secrets/hidden reasoning; a provider/model request repeats the exact ordered artifact-input list rather than supplying a second ref authority |
| `FrozenRunProjection` | run/attempt/purpose refs, projection_hash, ordered `artifact_input_bindings`, tool_definition_refs, model choice, grants, deadline/budget | managed-runner `run_start` repeats its exact ordered artifact-input list; changed order/ref/selector/media/role requires a new projection and idempotency key |
| `ToolArtifactInputContractV1` | closed `{mode:none}` or `{mode:bounded,min_items,max_items,role,allowed_media_types,selector_policy}` | core-owned inside a ToolDefinition; min≤max≤32; extensions may narrow but never author/widen it; absence is invalid rather than generic 0–256 |
| `ToolArtifactOutputContractV1` | min/max items and unique role entries with exact allowed media types and omissions policy | core-owned inside ToolDefinition; extensions may narrow but never rename roles, widen media/cardinality or change forbidden/optional/required omissions |
| `ToolResultArtifactBindingV1` | artifact_ref, role, media_type, omissions_ref or null | immutable ordered actual-output mapping sealed by ToolResult; the semantic result repeats all four fields and adds only Artifact-equal digest/size |
| `ToolDefinition` | tool/version, argument/result schemas, effect/grant/scopes/caps, exact `artifact_input_contract` and `artifact_output_contract`, idempotency/replay, implementation hash, qualification refs | arguments contain no artifact/selector refs; the artifact-input list is the sole byte-input authority, result metadata is field-complete, and built-in fetch/browser/multimodal/document profiles are fixed by extension-ports §§3.8–3.9 |
| `ToolCall` / tool_calls | attempt_ref, tool/version, args_ref, ordered `artifact_input_bindings`, grant_ref, effect_class, idempotency_key, state/result_ref | arguments and artifact inputs canonicalized/validated against the exact ToolDefinition; write-ahead intent; side-effect uncertainty retained |
| `ExportSnapshotV1` | snapshot_ref, export request/policy refs, target-independent ordered `artifact_input_bindings`, content_manifest_ref, aggregate_content_digest, created_at | immutable; contains 1–256 `export_payload` bindings with null selectors and exact manifest order/media/digest/size; refs alone grant no sink byte access |
| `PreparedDeliveryV1` | snapshot_ref, target_ref, content_manifest_ref, exact ordered `artifact_input_bindings`, aggregate_content_digest, expires_at | prepare output; transmit repeats the exact list and target, so changed bytes require a new prepare and consent; neither record implies shared-store/mount access |
| `Artifact` / artifacts | bytes_ref, media_type, size, digest, producer_ref, source/derivation_refs, rights, availability | required bytes must exist; malicious/unsupported formats don't acquire execution rights |
| `ArtifactProjection` | original_ref, projection_ref, converter/version, fidelity, selected/omitted ranges | preview/extract not original; sanitized copies get new hashes |
| `Handoff` / handoffs | source_execution/attempt, artifact_refs, target_execution, input_slots, validation, delivered_at, receipts | full artifact access distinguished from supplied extracts and observed use |
| `MemoryEvent` | execution_ref, store/policy/query refs, considered/selected/supplied refs, action, result | each retrieval scope-checked, rejected/omitted refs logged without unauthorized content |
| `DecisionRecord` | execution_ref, decision_kind, result, explicit support_refs, alternatives/uncertainties | externally provided concise basis, not reconstructed hidden chain of thought |
| `BudgetReservation` / reservations | policy_ref, request_id, maximums, observed_usage, finality, status | reserve before parallel dispatch; unknown spend retains reservation; no reset on restart |
| `ApprovalChallenge` / challenges | kind, exact_target_ref, action/scope, expected_version, expires_at, nonce, state | one-use authenticated human decision; model cannot mint/resolve approval |
| `ProviderUsageReport` / attempt journal `provider_usage` (2026-09-26) | attempt_id, input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens (each a bounded integer, or null = not reported), observed_model?, provider_message_id?, provider_request_id? | what the provider reported to the attempt's transport; journaled at most once per attempt and only in the transaction that accepts the attempt's result (a duplicate or late observation adds none); never changes the classification, the budget settlement or the send accounting; never an estimate, payload, text or credential; no ledger schema change (the closed transition vocabulary grew by one), and the offline v1→v2 migration preserves and re-verifies it |
| Claude run call records (`claude-call-intent-v1`, `claude-model-output-v1`, `claude-call-outcome-v1`; additive 2026-09-26) | intent (before the send): run, node, visit, model named, output cap, effort, `ceiling_rates` (the deployment's configured rates applying to this run, or null); output or outcome (after): provider message id, request id, observed model, reported `usage`, `cost` {`state`, `basis`[, `method`, `microunits`, `currency`, `rates`]} | cost basis: `subscription_mode` (no money) under a subscription budget; `reserved_ceiling` estimate = recorded tokens × configured ceiling rates rounded up, only for an API-priced budget in the rates' currency and never for a reported cache class without a rate; else `not_recorded`. The executor never settles against the budget book; ceiling rates are operator configuration (`DEEPTWIN_LIVE_CEILING_*`), never a price the product knows |

`ToolResult` statuses: succeeded/failed/denied/timed_out/cancelled/outcome_unknown. The enclosing
semantic result's `effect` object is the only effect/outcome truth; an embedded error carries no
duplicate effect state. Terminal×effect-family tuples and retry compatibility are exact in
extension-ports §2.3. The `tool-port-v1` `invoke_tool` success output is exactly
`{tool_call_ref,result_ref}`; `effect_receipt_ref` is forbidden there because the enclosing
`result.effect.effect_receipt_ref` is the sole receipt location. `ToolResultArtifactBindingV1`
remains sealed by `result_ref` and is unaffected by that removal.
Successful local execution still needs artifact/semantic verification. Runtime state and
evaluation validity are separate: malformed agent output can be a genuine capability failure,
whereas judge infrastructure failure is invalid/no-score.

## 5. DeepTwin and evaluation entities

growth-v1 §3 is the field authority for OriginalExecution, OwnAlternative, Selector,
Difference, Hypothesis, Inquiry, ChangeCandidate, ComparisonPlan, ComparisonResult,
LoopState and PromotionDecision. Map them to `original_executions`, `alternatives`,
`differences`, `hypotheses`, `inquiries`, `change_candidates`, `comparison_plans`,
`comparison_results`, `loop_states`, `promotion_decisions`. No second counter algorithm.

Additional records:

| Entity | Required fields | Integrity rules |
| --- | --- | --- |
| `LensDefinition` | source refs/version, atomic claim, applicability, distinguishing questions, opposing predictions, confounders, anti_claims, allowed_uses, review/effect statuses | separate scholarly fidelity, use qualification and observed effect; no philosophical personas |
| `LensComposition` | component refs, each responsibility, conflicts, resolution/abstention, decision trace | no average of philosophical interpretations or majority-based truth |
| `InquiryAudit` | episode_ref, H_phi/S_phi, lens refs, frozen questions/predictions, new_evidence_refs | unavailable to change compiler and operation; no user-level aggregation |
| `KnowledgeCandidate` | type, condition/action/exception, behavior evidence per field, owner/scope/time, lifecycle axes, conflicts, compilation target | source lineages propagate; prompts are derived, not truth |
| `EvaluationDataset` | case refs, provenance/rights, partition, exposure events, sealed_at?, task/rubric refs | viewed/tuned cases cannot become unseen by renaming IDs |
| `EvaluationProfile` | criteria/gates/metric/min_delta/floor/regressions, validity rubric, scorer version, calibration, comparison rules | frozen before scores; no uncalibrated universal numeric quality claim |
| `ValidationReport` | candidate hash, dataset/evaluator refs, per-gate results, evidence, missing/invalid, scope/limitations | K0–K7 distinct; no auto activation from a score |
| `IndependenceProfile` | task/error scope, comparison baseline, joint-error criteria, sample/precision, confounders, analysis, stop/exclusion rules | prior registration and valid heldout evidence needed; role separation alone insufficient |
| `Qualification` | component/runtime/model/lens hashes, permitted scope, checks/results, failed/unknown, revalidation triggers | a missing mandatory result is not passed; no implicit inheritance to new version |

`KnowledgeCandidate` has separate `validation_state`, `deployment_mode` and `lifecycle_state`.
Validated+shadow+current is possible, and does not mean active. Runtime selects only compatible,
authorized active knowledge; a source withdrawal suspends dependent evidence claims without
rewriting historical results. Lens-source changes prompt audit re-review, not automatic deletion
of operational rules independently supported by behavior evidence (paper §5.4–5.5).

## 6. Event registry and UI projections

OPS-002 EventEnvelope/PublicEventView/PrivateEvidence/RecordGap fields remain authoritative.
Schema-registered event types use `category.action`: setup.started/component_progress/failed;
auth.bootstrap_claimed/login_succeeded/login_failed/logout/session_revoked/recovery_started/recovery_completed;
service_client.created/rotated/revoked/denied;
deployment.request_prepared/request_cancelled/receipt_imported/verified/rejected;
connection.checked/changed/revoked; managed_login.requested/pending/completed/cancelled/expired/failed;
credential.retirement_recorded/cleanup_pending/erasure_completed/failed;
catalog.refreshed/invalidated; model.selected/mismatch;
work.created/revised; source.stored; ingestion.completed/failed;
speech.started/segment/stopped/interrupted/raw_unavailable;
understanding.requested/completed; design.proposed/repaired/selected; review.completed/invalid;
run.started/stopped; attempt.reserved/dispatched/terminal; tool.requested/terminal;
artifact.sealed/missing; handoff.delivered/acknowledged; memory.read/written;
alternative.saved; difference.observed; hypothesis.updated; inquiry.frozen/evidence/declined;
lens.selected/composed/abstained; candidate.created/frozen; evaluation.started/result;
loop.updated/stopped; validation.completed; approval.requested/decided;
promotion.applied/failed; rollback.applied; retention.changed/pruned/deleted;
export.previewed/created; backup.created/verified; update.started/failed;
recovery.reconciled; security.denied; record.gap.
Extension lifecycle adds extension.discovered/staged/verified/installation_failed/suspended/
revoked/uninstalled, extension.qualification_created/invalidated, extension.binding_activated/
superseded/disabled/rolled_back, extension.rollback_retention_created/released/consumed,
extension.deployment_requested/receipt_accepted/receipt_rejected/
handshake_failed, extension.current_uninstall_requested/receipt_accepted/uninstalled/rejected/unknown,
and extension.superseded_retirement_requested/receipt_accepted/retired/rejected/unknown. Current-
uninstall events carry the request-bound current head/service tuple and resulting tombstone-head
revision. Superseded-retirement events carry the unchanged current head, exact target installation/
service tuple, target-keyed retirement-head revision and dependency-snapshot digest. Public payloads expose only safe IDs,
versions, kinds, states and failure classes; manifests, configuration, service-client identity,
provider errors, secret handles and private qualification evidence stay behind scoped detail reads.
Binding activation/supersession/disable/rollback payloads additionally carry the exact
`BindingSlotKeyV1`, its recomputed digest, old/new extension candidate IDs and committed head revision so a stale event cannot
be applied to a sibling same-port slot. Rollback-retention events carry that key, target binding and
installation refs, old/new retention state/revision and the unchanged current binding head; they
never claim deletion of the immutable binding history or host-service removal.

The notation abbreviates fully qualified enum names, not acceptance of arbitrary strings.
Each exact type has an allowlisted payload schema. IDs/enums/counts/bytes/durations can be
public metadata. Filenames, URLs, input bodies, actor-entered labels, raw errors and private
refs are absent from public events and obtained only from authorized detail endpoints.

Events share atomic per-vault sequence and causal refs, with provider time separate from
local observed/recorded time. UI follows resumable cursor reads; duplicate sequence is ignored,
gaps request an authoritative snapshot, and bounded buffers cannot silently drop core events.
Raw LangGraph stream/checkpoint or provider envelopes are never proxied to the browser.

## 7. Backup encryption and import boundaries

Use the established age file format via a pinned, verified official `age` implementation, not a custom
cryptographic framing implementation. The upstream provides versioned releases, explicit
recipients/identities, streaming composition and signature-verification guidance. This is the
chosen implementation dependency, not evidence that our backup wrapper is qualified.
[age upstream](https://github.com/FiloSottile/age)

Profile `age-x25519-v1`: per-vault native age identity in a protected `backup-key` volume that is
cryptographically and operationally separate from provider credential records/root; public
recipient is protected configuration. Only the networkless `backup-crypto-worker` mounts this root
read-only. Encryption streams a consistent archive through owned pipes; decryption passes a
portable user identity through a one-shot owned descriptor referenced only by code-owned fixed argv,
never caller-controlled args/env/logs or a persistent plaintext identity file. The initial upstream
age binary still contains other formats internally, so the wrapper validates native X25519 syntax
before spawn and exposes no arbitrary option/path/PATH surface. No SSH identity discovery, scrypt,
plugins, post-quantum/tag recipients or network key lookup is reachable.
Portable recovery explicitly adds a separate user-held native age identity/recipient and
verifies a roundtrip before success. The supported product flow is handled in the browser UI;
V1 exposes no end-user CLI recovery path.
Do not claim post-quantum protection for this profile or host-loss recovery for instance-backup-key-only
keys. New nonce/key behavior is handled by age; invoke only pinned code-owned arguments.

OPS BackupManifest describes inner metadata; ciphertext hash and encryption profile live in
an external receipt to avoid self-referential hashes. Only decrypted/authenticated complete
archives enter validation. `Authenticator`, `BrowserSession`, `ServiceClient` credentials/bindings,
pending challenges/capabilities and credential handles never restore authority; historical approval
records remain evidence only and a new owner must rebind connections and reactivate an exact
environment from `restored_review`. Reject symlinks/hardlinks, absolute/traversal paths, oversized
expansion, duplicate paths, incompatible schemas, missing/changed referenced bytes and
executable hooks. Restore to a new staging vault with all dispatch disabled. Credentials and
new effect authority are never restored from a backup or imported log bundle.

## Task7 private owner-auth schema (additive component version1)

This private SQLite component shares the exact initialized DomainStore used by HostPolicy,
the runtime ledger and root commands. It is outside ordinary work records/exports. Its code-owned
DDL and complete object set are in `app/services/owner_auth_storage.py`; its own canonical DDL
checksum is stored in `owner_auth_migrations`. Historical domain/runtime migrations are unchanged.

| Exact table | Exact columns, in DDL order |
| --- | --- |
| `owner_auth_migrations` | version, checksum |
| `owner_auth_control` | singleton, vault_id, instance_id, origin_digest, generation_id, key_id, manifest_digest, epoch, opened_at, deadline, clock_floor, revision, hash |
| `owner_auth_bootstrap_claims` | epoch, verifier, attempts, state, claim_id, consumed_at, completed_at, revision, hash |
| `owner_auth_accounts` | owner_id, singleton, actor_ref, login_name, state, auth_epoch, recovery_epoch, created_at, updated_at, revision, hash |
| `owner_auth_authenticators` | owner_id, revision, previous_revision, kind, profile, encoded_hash, created_at, revoked_at, hash |
| `owner_auth_sessions` | session_id, owner_id, token_digest, authenticator_revision, auth_epoch, recovery_epoch, origin_digest, created_at, last_seen, idle_expires, absolute_expires, revoked_at, revision, hash |
| `owner_auth_commands` | command_id, session_id, kind, request_digest, response_json, created_at, epoch, hash |
| `owner_auth_audit` | sequence, kind, entity_id, observed_at, previous_hash, hash |

Time columns are UTC epoch milliseconds. Authenticator kind=`password`, exact profile=
`argon2id-v19-m65536-t3-p4-s16-h32`; only its encoded hash persists. Session tokens are32 random
bytes and only SHA256 hex digests persist. Account state=`active|disabled`; claim state=
`available|consumed|completed|expired|exhausted`. Consumed with no account derives `setup_incomplete`.
Private command kind=`logout`; audit kind=`opened|guess|claim|owner|login|logout`. No rows are
deleted during revocation. Closed error classes contain no native/storage exception text.

DDL enforces singleton/identity/digest/command uniqueness, foreign keys and backward authenticator
revision references: revision1 requires a NULL predecessor; every revision greater than1 requires
an explicitly non-NULL predecessor equal to revision−1. Integrity verification independently checks
this relationship on retained rows, including reopen; SQLite's NULL-valued CHECK result is not proof
of valid history. Mutable rows use fixed-table/column/identity SQL CAS: exactly old revision+1,
matching old identity+revision, exactly one changed row. There are no auth triggers; the shared
database's no-trigger invariant remains intact. Canonical closed-row SHA256 and the audit hash
chain detect corruption, not an administrator rewriting trusted DB state. Reopen and authority
admission verify the schema, migration checksum, hashes, root/config binding and real human actor.

The human actor is an ordinary immutable `actor` record authored by the existing system root,
with content exactly `{id:<owner_id>,kind:"human",origin:"local_session"}`; it never relabels a root.
Its descriptor, account, authenticator, first session, completed claim and sanitized `owner.created`
event commit together after the separate claim commit. Other public auth events are
`session.created` and `session.revoked`, each with only bounded `session_count` metadata.

Root manifest fields are exactly `{schema_version:"session-root-v1",generation_id,key_id,
instance_id,origin_profile_digest,recovery_epoch,created_at,state:"initial_genesis",integrity_tag}`.
IDs are independent random UUIDs; `created_at` is UTC milliseconds with Z. `integrity_tag` is
canonical base64url HMAC-SHA256 under root.key over canonical JSON
`{domain:"deeptwin-session-root-manifest-v1",manifest:<all manifest fields except integrity_tag>}`.
The public receipt omits the tag; private control pins SHA256 of the complete canonical manifest.
`schemas/v1/owner-auth-public.schema.json` exports nonsecret receipt/profile/state definitions;
schema parsing never issues authority. Root bytes/raw capability/password/session token never enter
the DB or ordinary artifacts. Replacing all root files and trusted DB state remains outside the
host-administrator threat boundary.

## 8. Acceptance and migration evidence

Tests must cover immutable-version conflicts, byte/ref corruption, missing evidence,
cross-vault and cross-purpose reads, spoofed actors, partial alternative selectors, cyclic
lineage rejection, late/out-of-order events, duplicate result/counter application, checkpoint
lag, credential-vault failure, snapshot consistency and backup tamper/truncation/key-loss recovery.
Every supported schema migration has fresh/legacy/rollback fixtures and preserves existing
user-owned records. Existing 729-test results are historical until rerun after integration.
