# Claude text-first semantic vertical — DRAFT contract and gated implementation plan

> **For agentic workers:** Design preparation only. Do not execute this document. After controller reconciliation, written promotion and Task46 acceptance, use `superpowers:executing-plans` with the authorized sole-writer scope; no helpers or commits are authorized here.

**Goal:** Execute all five `provider-port-v1` operations for one explicitly narrow Claude API text profile through a real worker, dedicated gateway and existing runtime result consumer, with behavior-bearing controlled-upstream proof.

**Architecture:** Keep the worker credential-free and network-free. Core resolves and streams immutable inputs, obtains the worker's bounded proposal, sends through the dedicated credential gateway, streams the observed response back, independently validates/seals the result, and accepts it through the existing ledger. Production composition exposes no activation or send until real C/binding/current-connection authority exists.

**Tech stack:** Existing Python, DomainStore/RuntimeLedger/BudgetBook, authenticated broker and artifact stream, pure Claude protocol code, worker-side HTTP transport. No new SDK, dependency, source root, signer, native layout or credential storage/cryptographic mechanism; the missing lease-bound delivery consumer is explicitly in scope.

**Spec:** [Readiness map](post46-provider-readiness-map.md); canonical [ports](../../../specs/001-autonomous-release/contracts/extension-ports.md) §§2–3; [runtime](../../../specs/001-autonomous-release/contracts/runtime.md) §§6–7; tasks T018/T087/T090 and mandatory distinct T088. Task46 installation contract remains independent and unchanged.

## 1. Status, scope and promotion gates

2026-09-20. Parent adopts the semantic vertical as a **planning direction only**. Task45 is accepted; Task46 is implementing its promoted contract, not accepted. This draft neither assigns Task47 nor claims executable promotion, a real release, qualification or model readiness.

The new shapes and profiles below are **recommended code-owned choices**, not pre-existing canonical schema or authority. Canonical port/config/request/result/error fields and old private B bytes do not change. The companion [literal appendix](post46-semantic-wire-record-appendix-draft.md) freezes record/wire/codec/ID/lease details and takes precedence over this document's earlier illustrative field sketches. R1 additionally requires explicit canonical approval of the [scoped read/cancel amendment](post46-read-observation-amendment-draft.md): fresh read identity is not implied by current §3.7. All three require bounded controller preflight before implementation; §10 distinguishes actual authority gates from design approval. Ordinary choices are resolved here, not deferred to a browser-user interview.

Global constraints:

- Keep Claude API-only and mandatory Codex subscription in whole-product scope. This unit implements neither managed-runner/device-auth/`codex exec` nor Codex API execution/fallback.
- No Task46 moving implementation is a design dependency. Exact stable paths were read; one broad symbol-search accidentally exposed the moving `provider_conformance_service.py` class declaration only, was reported, and was not used. Do not repeat that broad search during preflight.
- No product composition registration, new HTTP routes, route-count edits, production image replacement, C issuer, binding activation, native collector or release-source changes in this unit.
- Existing domain codec remains 1 MiB/depth32/10,000 recursive items/65,536-byte strings/signed63-bit integers. Semantic port envelopes retain their stricter canonical limits: 1 MiB/depth8/4,096-character strings/256 collection entries/53-bit safe positive integers.
- Existing broker frame/profile, UID/GID/HMAC, source18, retained stage/verified/B histories and C1–C5 remain unchanged. A new semantic dialogue is not the old private B suite.
- Browser users never provide qualification maps, report/signature files, host paths or CLI arguments. Test-only upstreams/credentials are never shipped as deployment defaults.

Review focus, each covered in §9:

1. An in-flight slow response must still allow bounded cancellation/status; a serial blocking `send()` is insufficient.
2. Valid text with missing currency usage must remain a real result with held reservation, not fabricated zero cost.
3. A complete catalog page without model capability evidence must not make a model eligible.
4. A retained response or duplicate command must not cause a second send after restart or lost reply.
5. Worker-authored refs, authority booleans or an arbitrary callback cannot become trusted core facts.

R1 focus adds fresh status/catalog observations without changing semantic hash bytes, cancellation acknowledgement versus target-monotonic action, one absolute deadline through actual custody locks/SQLite/full validation, and config/binding opaque-handle equality through exact encrypted record delivery. Named proofs below cover each.

## 2. Selected scope and alternatives

Recommend **execution-model-step, text inputs/output, no tools, no explicit effort override**, with all five provider operations. Use `provider_id="claude_api"`; `auth_mode="api"`; request modalities exactly `["text"]`, tools exactly `[]`, effort and response_schema_ref exactly null. Capabilities reports text, tool_calling=false, usage_reporting=true (nullable observed usage remains possible), cancellation=true (local best effort, never remote rollback).

Select at most four `text/plain` input Artifacts, selectors null, aggregate input at most 262,144 bytes, at most four text output Artifacts with aggregate at most 524,288 bytes, proposed max_output_tokens 1–8192 selected in the frozen call and within returned model limits. A single upstream response remains at most 1 MiB. Use the minimum of remaining ledger/budget time, config deadline and existing 30-second extension operation cap. The 4/4 and30s caps are provisional integration-fit choices; the broader180s product target is unchanged, not silently redefined. Oversized/slow real profiles may refuse and require measured widening.

These caps narrow canonical maxima, not measured real-release fit. Reason: exercise actual model behavior using existing framing/parser limits without broad modality, selectors, tool dispatch or new topology. Cost if too narrow: some real models/large contexts/slow responses cannot activate this profile; no silent truncation or unsupported-as-success fallback is allowed.

Rejected alternatives: calling the legacy SDK in core (breaks credential/network boundary); promoting the private transform worker unchanged (does not supply full semantic operations); inventing a C pass to wire live execution (grants absent authority). Text-first does not complete all provider capability or whole-product requirements.

## 3. Exact canonical envelope reuse

Use existing exported `schemas/v1/extensions/ports/provider-port-v1/{config,request,result,error}.schema.json` and `app/extensions/port_schema_generator.py::validate_port_payload(port, shape, value, *, context=None, refinement_schema=None)`. Do not regenerate different base bytes or introduce an extension refinement; all three extension_* objects are `{}`.

| Shape | Existing fields to preserve exactly |
| --- | --- |
| config | schema_id, schema_version, port_contract_version, extension_id, installation_digest, qualification_ref, binding_revision_ref, binding_slot_key, binding_slot_key_digest, extension_config, grant_refs, credential_handle_refs, resource_limits, port_config |
| request | schema_id, schema_version, port_contract_version, request_id, operation, installation_digest, qualification_ref, binding_revision_ref, purpose_ref, actor_ref, grant_refs, idempotency_key, deadline_at, cancellation_ref, artifact_inputs, input, extension_input |
| result | schema_id, schema_version, port_contract_version, request_id, operation, terminal, started_at, completed_at, output, extension_output, artifacts, usage, effect, error |
| error | schema_id, schema_version, port_contract_version, request_id, operation, code, port_error_code, extension_error_code, message_class, retry_class, affected_refs, evidence_ref |

Existing `BindingSlotKeyV1` stays exactly `{port_contract_version,target_scope_fingerprint,purpose,binding_slot_id,capability_selector_digest}`. The key's canonical digest and all config/head/revision joins remain exact. `ref` is the existing four-field EntityRef, never an ID/path/URL. Nullable fields remain required with null, not omitted.

| Operation | Exact input → output on success | Behavior in this profile |
| --- | --- | --- |
| capabilities | `{}` → `{modalities,tool_calling,usage_reporting,cancellation}` | Fixed implementation capabilities, not model-name-derived capabilities; no upstream request. |
| catalog | `{catalog_epoch:ref|null}` → `{catalog_ref,complete,models:[{model_id,display_name,modalities,effort_values,capability_evidence_ref}]}` | Explicit refresh only. Retain actual raw page and connection provenance; model eligibility requires separately resolved exact evidence, not raw listing alone. See below. |
| model_step | `{frozen_turn_ref,model_id,effort:null,requested_modalities:["text"],tool_definition_refs:[],response_schema_ref:null}` → `{provider_id,model_id,content_block_refs,tool_proposal_refs:[],usage_report_ref,provider_response_ref}` | One bounded actual request, response normalization, exact model join and retained output. |
| status | `{operation_ref}` → `{observed_state,observed_at,terminal_result_ref}` | Exact same-purpose operation record; read retained state plus current local in-flight state. Unknown remote state is inside successful output, not an unknown query terminal. |
| cancel | `{operation_ref,reason_class}` → `{cancel_state,observed_at}` | Accepted/already_terminal/not_cancellable only; request acknowledgement is distinct from original model_step outcome. |

Query/cancel operations have only succeeded/failed terminals and no artifacts; model_step has all four canonical terminals. Effect classes are read for capabilities/catalog/status, none for cancel, external_irreversible for model_step. All non-success outputs/extension outputs are `{}` and artifacts `[]`.

Under the proposed **profile-scoped canonical amendment only**, capabilities/catalog/status get one immutable observation per fresh request UUID with unchanged semantic hash; exact UUID/bytes/config replays and changed content under the same UUID conflicts. Cancel replay preserves its acknowledgement, while a fresh UUID observes terminal/already-terminal or the one target-scoped cancellation intent without a second cancellation action. Model-step semantic-key dedup and unknown-no-resend stay unchanged. Appendix§3 and the amendment freeze the normative cases; current canonical wording alone does not authorize this exception.

Controller-selected catalog adapter: actual forward cursor pagination with limit100, at most20pages/256unique models, retaining every raw page and strict cursor/duplicate/order/byte/deadline checks. Exhaustion or malformed traversal never yields complete=true. Complete traversal with missing/null capability/limits/text-scope/profile evidence remains complete availability, but those models are ineligible with retained reasons; no fabricated capability or compatibility facts. Appendix §4 is exact. The earlier one-page32-model refusal is withdrawn as needlessly restrictive; the old private20-page/1000-model parser is neither changed nor reused as the new semantic authority.

## 4. Code-owned record/context seam

### 4.1 Frozen call, not a new authority registry

`app/runtime/gateway.py::freeze_turn(value)->FrozenTurn` supplies structural allowlisting only. Its existing exact input fields are `profile,work_ref,environment_ref,node_id,execution_id,attempt_index,provider,account_id,catalog_ref,model_id,effort,instruction_profile_digest,inputs,granted_tools,output_schema_id,runtime_profile_ref,deadline_seconds,budget_ref,consent_ref`. InputPart is exactly `{type,ref,marker,omissions}`. It currently permits 128 parts and does not seal F-model bindings.

Recommend one new **content variant of the existing frozen_turn kind**, not mutation of old records. Its closed content is `{schema_version,turn,execution_envelope_ref,purpose_ref,grant_refs,artifact_input_bindings,messages,max_output_tokens,instruction_projection}`. `turn` is the exact existing freeze_turn input object; this variant requires profile=execution-model-step/provider=claude_api/effort=null/granted_tools=[] and 1–4 text Artifact InputParts with null marker/empty omissions. `execution_envelope_ref` joins the exact existing AttemptDispatchRequest.envelope_ref. `purpose_ref` and sorted grant_refs join the port request, not the worker's choices.

`artifact_input_bindings` uses canonical `{artifact_ref,selector_ref:null,declared_media_type:"text/plain",role:"model_input"}` entries in exact InputPart order. `messages` is 1–4 closed `{role:system|user|assistant,input_ordinals:[int]}` entries; each ordinal occurs exactly once in increasing concatenated order, only entry0 may be system, at least one user entry exists. Resolve/read/hash UTF-8 bytes under grants before sealing; never turn an unrelated non-byte ref into input authority.

`instruction_projection` is the new variant's explicit `{profile_id,system_artifact_ref:ref|null}`; if non-null it equals entry0's sole system Artifact, otherwise no system message is permitted. This variant defines instruction_profile_digest as SHA-256 of canonical instruction_projection; **a new variant-specific meaning**, not rewriting any old FrozenTurn digest. Appendix §2 closes it; no supplied arbitrary text is assumed to be a previously approved profile.

`max_output_tokens` is selected before send and participates in the immutable frozen call digest and reservation. Lower resource/model limits further restrict it. Use the appendix's new semantic serializer/codec, reusing only pure framing primitives where compatible. Old private prepare_text/Catalog/Text acceptance remains unchanged; its profile token never appears as qualification evidence or the new semantic contract version.

### 4.2 Retained observations and issued context

Use closed new content variants under existing `validation_report` for operation anchor, provider response/usage/effect evidence and catalog capability observation; existing model_catalog and artifact kinds for catalog/output. Appendix §2 supplies final literal tags/types and supersedes the following earlier explanatory field sketches; generic `content:dict` is not adequate validation. No new EntityRef kind or qualification/binding table is needed.

| Proposed record | Required closed content (common immutable envelope remains existing domain-v1) |
| --- | --- |
| operation anchor | schema_version, request (exact canonical request), config_digest, frozen_turn_ref:null-or-ref, execution_envelope_ref:null-or-ref, core_boot_id, request_digest |
| provider response evidence | schema_version, operation_ref, request_digest, proposal_sha256, upstream_status:null-or-int, response_blob_ref:null-or-BlobRef, response_sha256:null-or-digest, response_size, observed_model:null-or-identifier, stop_reason:null-or-existing-private-stop-enum, transport_phase:not_sent\|may_have_sent\|terminal_observed, cancellation_observed:bool |
| usage evidence | schema_version, operation_ref, response_evidence_ref, input_tokens:null-or-int, output_tokens:null-or-int, cache_read_input_tokens:null-or-int, cache_creation_input_tokens:null-or-int, currency_cost_known:false |
| effect evidence | schema_version, operation_ref, response_evidence_ref, request_digest, effect_state (canonical enum), remote_outcome (canonical enum), source:gateway_observation |
| normalized terminal | schema_version, operation_ref, result (exact canonical result), private_response_evidence_ref:null-or-ref |
| catalog content | schema_version, operation_ref, provider_id, connection_snapshot_ref, account_id, fetched_at, raw_page_blob_ref, raw_page_sha256, complete:bool, eligible_models (canonical output rows), excluded_models:[{model_id,reason:capability_unknown\|profile_unsupported}] |
| capability observation | schema_version, provider_id, connection_snapshot_ref, model_id, observed_at, supported_modalities, advertised_effort_values (exact canonical effort-value[]), observation_evidence_ref, profile_digest |
| connection snapshot | schema_version, connection_locator (existing navigation-only ObjectRef), connection_revision_digest, provider_id, account_id, credential_record (existing `{record_id,record_version,ciphertext_sha256}`) |
| semantic config snapshot | schema_version, config (exact canonical config), connection_snapshot_ref |
| provider output Artifact | schema_version, operation_ref, ordinal, blob_ref (existing BlobRef), media_type:text/plain, content_digest, byte_count; all digest/size fields equal the registered blob |

All refs resolve and rehash; all lists/maps have selected profile caps; response_size is zero when response_blob_ref is null, otherwise exact BlobRef.size/digest (an observed empty body is distinct from absent observation); no raw secret fields. The response record precedes usage/effect; those precede normalized terminal, avoiding cycles. A new deterministic operation anchor exists before status/cancel can reference it. No record's signature/schema/tag grants production authority. `connection` is only an ObjectRef locator in current refs.py, not an immutable EntityRef kind; the new snapshot is a validation_report variant and cannot turn navigation into currentness authority. Its current connection producer remains an activation dependency. Preserve provider-advertised effort values exactly when evidence exists even though this profile accepts only null override; do not guess or normalize them.

Recommended concrete interface boundary: `ProviderSemanticContext` is a private immutable core projection; `load_semantic_context(store:DomainStore, *, config_ref:EntityRef, request_ref:EntityRef, now_utc:str)->ProviderSemanticContext` resolves exact records and recomputes every ref/digest. It does not accept a dict, callable verifier, `passed`, `authenticated` or `readable` from request/worker input. Dedicated core permission/current-head checks derive the validator context fields below; fixture-only records are not a production fallback.

Existing validator requires config context `{validated_at,qualification_record,binding_revision_record,binding_head_record}`; request adds `{config,accepted_at,actor_record,purpose_record,grant_records,artifact_records,selector_records,input_records}`; F-model adds `frozen_record`; result adds `{request,extension_error_codes}` plus existing artifact records. Its `qualified/active/authenticated/readable` fields are **trusted projections, not producers**. This unit can test their exact joins against explicitly synthetic sealed records; it cannot honestly supply production C/binding/head/permission producers that do not yet exist.

## 5. Worker → gateway → worker dialogue

Recommend new modules/dialogue alongside, not replacement of `provider_service.py`, `provider_client.py`, `provider_messages.py` or accepted B. Reuse existing frame message types, auth, correlation, descriptor/chunk/credit/receipt primitives. New dialogue discriminators must be isolated from private B. No raw provider response or body is embedded into semantic envelopes; bytes move through bounded artifact streams.

One active model dialogue owns the existing extension channel. Core remains the only requester of both worker and credential gateway; **no worker→gateway socket, shared database or new mount**. During response waiting, the worker accepts bounded status/cancel control exchanges within this dialogue, not a second model call. Query-only idle operations can use their own normal one-shot dialogue. Pending status is core-derived from the retained operation anchor before the worker begins.

Recommended closed application messages (new names, not canonical port schemas): begin `{schema,operation_ref,config,request}`; proposal `{schema,operation_ref,request_digest,endpoint:messages|models,body_descriptor:null-or-existing-ArtifactDescriptor}`; observation `{schema,operation_ref,request_digest,status:complete|refused|truncated|unknown,upstream_status:null-or-int,body_descriptor:null-or-descriptor}`; control `{schema,operation_ref,request}` where request is exact status/cancel; control_result `{schema,operation_ref,result}`; final `{schema,operation_ref,request_digest,result_descriptor}`. Each discriminator is a different literal schema value; no optional keys. Stream descriptors use the existing grammar, never a second digest convention.

Bound application control payloads to 16 KiB and one active dialogue; profile-small config/request must actually fit or refuse pre-send. At most one pending control exchange, no unbounded queue. Each envelope ID/correlation is fresh and bound to the operation/dialogue; finalization rejects trailing frames, duplicate finals, changed descriptor/operation/request digest or cross-dialogue chunks. Use one monotonic deadline over the entire operation, including streaming and finalization.

The worker returns proposals and observations, not durable EntityRefs or a final authoritative effect receipt. Core seals bytes and constructs/validates the semantic result. The worker can return a schema-shaped proposal for canonical output, but core must replace no caller-chosen refs: resolve exact streamed bytes and issue all output/evidence refs itself. This is consistent with workers never owning DomainStore.

## 6. Dedicated gateway send and cancellation

`CredentialGatewayService`'s current closed credential-op-v2 dispatch remains unchanged; store_at/query_record/retire and secret ingress do not acquire send authority. Add a **separate application dialogue on the already authenticated gateway boundary**. It is not a new trust root or topology. Do not send 1 MiB request/response bodies through the 96 KiB credential-fragment codec.

`ProviderBinding` and `CredentialedProviderTransport.send(*,handle,method,path,headers,body)->GatewayResponse` supply low-level validation/HTTP code, not a working authorized custody-send chain. **Current CredentialVault.resolve_for_gateway always raises provider_binding_unavailable**, and capabilities reports provider_resolution=false. Preserve that historical denial. Add a streaming/cancellable transport method and a distinct gateway-only, lease-bound custody delivery method; do not monkeypatch the old resolver or replace the vault with a fake.

Proposed `exchange(*, lease:GatewayExchangeLease, body:bytes)->GatewayExchangeObservation`: exact local classes, no arbitrary success callback. The lease fixes request_digest, operation_ref, selected opaque handle and its connection pin/credential metadata/record, provider/origin/method/path/header projection, body digest/size, response cap and monotonic deadline, with one-shot ownership and a cancellation flag. Appendix§2 selects the immutable connection snapshot EntityRef itself as the sole opaque handle: config and resolved binding handle arrays must both equal `[connection_ref]`; account/provider/current revision, CM fingerprint and exact CR version/hash all join. Gateway consumes the authenticated core's exact projection, never independently chooses another valid record or resolves latest-by-record-ID. Canonical claude_api maps explicitly to stored provider claude, not arbitrary string equivalence.

Gateway protocol recommendation: prepare fixed request/body → gateway ready after local metadata/header validation → core rechecks current connection/config/binding/lease/budget and sends commit → one exchange → bounded response/effect observation. No upstream network I/O before commit; repeated commit/prepare cannot dispatch twice. A gateway restart loses the one-shot lease and cannot resume a send. Only the authenticated core channel can issue commit/cancel; worker-provided fields cannot choose auth headers, credential, target or budget.

The **new actual issuer chain**, shared by behavioral fixtures and eventual activation, is:

1. Concrete core context resolver loads sealed records/permissions and joins the real consumed ledger window; it never accepts a caller's bool verdict. Production has no registered C/binding resolver/composition in this tranche. Test composition alone supplies explicitly synthetic sealed authority records to that same loader.
2. Gateway's new service authenticates the existing core channel, validates complete prepare bytes/body digest/credential metadata and binds them to its actual channel session. It creates only a pending exchange, not a secret or send capability.
3. Matching one-shot commit, still within the original deadline/session, atomically removes that pending exchange and privately issues `GatewayExchangeLease` into an identity registry owned by the service instance. Identity, exact frozen values, cancellation state and session must all match at consumption. Deserialized/lookalike dataclasses, a duplicate commit, a lease from another service instance, and lease reuse fail.
4. `CredentialVault.delivery_for_exchange(lease:GatewayExchangeLease)` is a new gateway-only context manager. It consumes the registered lease once; `_operation(custody_budget=...)` follows the existing exclusion/check order with the optional shared absolute deadline/Event seam in appendix§9.1, not stacked historical5s waits. It verifies the selected-handle projection, root identity, exact metadata fingerprint/record/ciphertext hash, committed stored_unbound receipt, no retirement/cleanup/lost/pending state, and unchanged published payload. It decrypts through actual `CredentialRoot.open(payload,metadata)` and exposes bytes only to the gateway exchange scope. It creates no handle or bound custody state. Keep exclusion through the bounded first request-write boundary; failure/cancel destroys delivery. Release before long response collection; revocation after write remains uncertain/committed-effect.
5. The transport injects the auth header and attempts one request on its owned connection. Scope exit drops secret/header references and consumes/closes delivery regardless of error; do not claim Python provides cryptographic memory erasure. The returned observation has only bounded response/status/phase bytes, never secret material or a reusable authorization token.

A private registry/value constructor is an in-process core/gateway discipline, not a sandbox against arbitrary code in those trusted processes. The production activation gate is the missing supported composition and genuine C/binding/currentness producer, not secrecy of a Python token or a test environment flag. Tests construct real encrypted custody and new authenticated dialogues; none patch `resolve_for_gateway`, `_root.open` or `_query` to return successful secrets.

Core's durable send-intent barrier precedes commit publication. Credential version/usability is checked inside the gateway immediately before auth injection/write. Core revocation before commit refuses; a revoke/cancel racing **after** commit may leave an effect and is reported accordingly, not claimed atomically prevented. Explicit final core currentness and ledger fences are still checked on admission. Appendix §§7–9 freeze exact wire/session/lease/lock rules; the old channel does not already implement them.

Use exact text endpoint POST `/v1/messages` and code-constructed catalog GET `/v1/models?limit=100[&after_id=...]`; no caller URL/query/redirect/alternate origin. API-key-only headers are anthropic-version=2023-06-01, content-type=application/json and gateway-injected x-api-key. No Authorization/workspace/cache/tool/effort overrides. Appendix/source note pin actual upstream facts; loopback routing remains available only through test-owned composition, not a supported production config.

A cancellable exchange owns its HTTP connection; a reader collects bounded chunks while a control loop observes cancellation/deadline and closes it. One absolute budget covers RLock/flock/SQLite busy/progress/full metadata validation plus stream/HTTP checkpoints. Existing no-budget custody operations keep their defaults/checks; no schema or receipt migration. Delivery introduces no helper thread. All owned threads must actually unwind/join before closure; marking unknown is not permission to abandon one. Controlled cleanup overrun fails the profile-fit proof. Finite local filesystem/crypto calls are checkpointed but not claimed forcibly preemptible; real platform interruption remains measured activation work. Never block the only cancellation path on response.read; closing transport is not remote-cancellation proof. No response retry, proxy environment, credential exception chain or raw non-2xx error is returned.

## 7. Runtime acceptance, effects and cost

Add `ProviderAttemptTransport.__call__(permit:DispatchPermit,request:AttemptDispatchRequest,window:ConsumedDispatchWindow)->AttemptTransportResult`, the exact callable shape already consumed by NodeAttemptDispatcher. Constructor dependencies are concrete DomainStore/RuntimeLedger/BudgetBook and the code-owned semantic context/worker/gateway clients, not `verifier=lambda:True` or arbitrary provider callback. Resolve the frozen call whose execution_envelope_ref equals request.envelope_ref; join run/node/execution/attempt/profile and deadline fields. No `tool_binding` reinterpretation is allowed.

Reuse `RuntimeLedger.commit_budgeted_send_intent(...,expected_revision,budget_book,budget_request,principal,grant)`; consume its issued window once with `consume_dispatch_permit_window`; recheck `assert_consumed_dispatch_window`. Existing principal/grant check is runtime/read of the envelope, **not authorization of external provider spend**. Keep it and additionally require the scoped current provider context at the gateway commit boundary. Reuse `accept_result_and_settle(command_id,observation,*,budget_book,usage)`; never split acceptance and settlement into separate calls.

| Observation | Semantic result and accounting |
| --- | --- |
| Locally refused before commit/write | failed with known-none effect; output/artifacts empty. Appropriate canonical error; no remote token/currency claim. |
| Complete valid response, requested model exact, supported stop/content | succeeded; sealed text refs and exact model_content artifact array; committed + effect receipt + confirmed response outcome. Token counts only as observed; missing currency remains unknown. |
| Complete provider response but unsupported content/model mismatch/protocol problem after possible effect | Do not encode committed effect in failed. Use unknown with external_effect_unknown and empty semantic artifacts; retain private evidence. This deliberately conservative profile can withhold usable text. |
| Cancel acknowledged before write | Cancel query succeeds; original model_step cancelled with none/null/not_applicable effect and empty artifacts. |
| Cancel after possible write without proved remote terminal | Cancel query succeeds; original cancelled with unknown/null/unconfirmed effect (or unknown original if no canonical cancel observation survives); no retry or fabricated zero usage. |
| Lost response, truncation, transport death/restart after commit | unknown; completed_at=null, external_effect_unknown/never, unknown remote effect, no semantic artifact. Retain reservation. |

`usage` retains exact canonical five fields. Map observed input/output token counts to input_units/output_units with unit_name=tokens; billed_units stays null because token totals are not billed currency; provider_report_ref resolves sealed usage evidence. Preserve the cache categories in that evidence without folding/guessing them. Missing usage fields stay null. A confirmed response is not confirmation of an exact monetary charge.

Existing BudgetBook API reservations require a positive conservative currency estimate and currency cap. Production estimate/capability provenance is an actual missing producer, not supplied by this draft. Controlled fixtures may use an explicit synthetic finite tariff/estimate, labelled test-only, to exercise budget limits. **For every actual API response without authoritative exact currency usage, choose usage_finality=provisional and usage=None** even on succeeded. Existing ResultObservation/accept_result_and_settle admit succeeded with provisional usage and hold the reservation; NodeAttemptDispatcher can expose its retained succeeded result. Do not relabel API as subscription or pass api_microunits=0/None as final API usage.

Seal text using existing `store_received_artifact`/DomainStore primitives and the appendix's closed provider-output Artifact variant; references, media/digest/size must agree. One Artifact per returned text block, exact ordered content_block_refs and role=model_content/omissions_ref=null. Appendix §§2–3 freeze ID domain and strict request-identity replay. Partial/late outputs stay quarantined outside semantic artifacts. Accepted owner replay resolves the old terminal, never creates a new permit, sends, changes cost finality or extends expiry.

## 8. Production closed, same behavior executable in tests

Recommend **no production factory/export/HTTP registration for this service in this tranche**. A deployable core cannot discover it from environment, candidate bytes or test flags. Its actual modules implement worker/gateway/runtime behavior; tests explicitly construct them using real temporary store, broker channels, vault and controlled upstream. Absence of production composition is an intentional missing activation consumer, not a pretend production assessor that forever emits unsupported.

Test-only composition lives under app/tests/support and is the only place that creates synthetic qualification/binding/capability/currentness inputs. It seeds complete immutable test records with test provenance, exercises the real context loader/semantic equality checks and real gateway/worker/ledger path, and records actual bytes sent/received. It does not inject a pass callback into a production verifier. Import-boundary tests forbid production imports of this support file and prove default assembly registers no provider-send route/service.

These synthetic records establish **conditional semantic behavior**, not actual C. A later separately promoted activation unit supplies genuine same-store C/binding/current permission/connection/cost producers and production composition for the same implementation. This avoids two engines or a hidden bypass. It is not an authorization to implement those producers now.

## 9. Proposed ownership and gated proof sequence

Exact paths are recommendations to reconcile after Task46 acceptance; none are edited by this design task. Keep old private-worker/B files unchanged to avoid rewriting their evidence. Do not add speculative browser routes that can only deny.

| Proposed paths | Responsibility |
| --- | --- |
| NEW app/extensions/provider_semantic_contracts.py | Narrow profile, closed record/wire content constants and validators; no trust issuer. |
| NEW app/extensions/provider_semantic_records.py | Frozen-call/operation/catalog/response/usage/effect/result and output-Artifact sealing/rehydration. |
| NEW app/extensions/provider_semantic_context.py | Concrete record resolution + semantic validator projections, distinguishing data from absent production authority producers. |
| NEW app/workers/provider_port_messages.py, provider_port_service.py, provider_port_client.py | Distinct full-operation finite worker dialogue; reuse pure private transforms, not private service semantics. |
| NEW app/workers/provider_semantic_codec.py | Selected current Models/SSE/text-body codec, separate from accepted B's private accumulators. |
| NEW app/workers/provider_send_messages.py, provider_send_service.py, provider_send_client.py | Dedicated gateway prepare/commit/cancel/observation dialogue; no credential-op-v2 widening. |
| NEW app/runtime/provider_attempt_transport.py | Exact existing dispatcher callable, frame/stream orchestration, guarded send and ledger result consumer. |
| MODIFY app/workers/provider_gateway.py | Add cancellable exchange without changing historical send behavior or admitting arbitrary request authority. |
| MODIFY app/workers/credential_vault.py | Add scoped actual encrypted delivery for an exact issued exchange lease; preserve unqualified resolve_for_gateway denial and every old custody/receipt operation. Pure lease type/issuance checks belong to provider_send_messages.py; no core import of vault/decryption code. |
| MODIFY app/workers/credential_files.py and app/workers/credential_journal.py | Optional shared absolute CustodyBudget through existing RLock caller/flock and SQLite busy/progress/full metadata checks; historical None defaults unchanged; no journal schema/receipt-state change or detached thread. |
| MODIFY app/domain/schemas.py and app/domain/schema_exports.py; derived schemas/v1/domain-envelopes.schema.json | Closed proposed content-variant validation/export only. Last two are Task46-owned now: defer inspection/editing and scope reconciliation until its freeze. No EntityRef kind/old content rewrite. |
| NEW app/tests/support/provider_semantic_harness.py | Explicit synthetic records/vault/local upstream, deterministic barriers and captured raw bytes; never production-imported. |
| NEW app/tests/test_provider_semantic_contracts.py, test_provider_semantic_records.py, test_provider_semantic_worker.py, test_provider_send_gateway.py, test_provider_attempt_transport.py, test_provider_semantic_vertical.py | Finite proof below; include import/non-registration boundary. |
| NEW app/tests/test_provider_semantic_codec.py | Exact primary-source-shaped synthetic codec/pagination/usage vectors from appendix. |

Plan gates: bounded re-review all three drafts, explicit promotion of the scoped read/cancel canonical ruling, then reconcile owned paths against accepted46. These are preparation steps, not permission to run tests now. Each subsequent task uses failing named test → minimal implementation → passing targeted test → scoped regression review; no commits or helper dispatch are prescribed.

### A. Closed records and context projections

- [ ] Pin `test_frozen_f_model_exact_order_and_instruction_digest`: seal real input bytes; vary one ordinal/ref/selector/media/purpose/grant/profile digest and require rejection before any socket opens.
- [ ] Pin `test_records_rehash_and_acyclic_refs`: response → usage/effect → terminal closure; altered persisted body, fabricated worker ref, self-reference, wrong blob size, repeated ordinal and non-success artifact all refuse.
- [ ] Pin `test_read_ids_refresh_without_changing_semantic_hash` and `test_observation_exception_is_profile_scoped`: request-UUID anchor uniqueness for reads versus model semantic index; fresh read IDs work only for the named profile/operations, old hash/schema vectors stay exact, same-ID changed body/config refuses.
- [ ] Pin `test_bound_handle_is_exact_connection_snapshot`: config/binding sole handle equals the exact snapshot R; every account/provider/revision/CM-fingerprint/CR change refuses before preparation; rehydrated old record cannot silently resolve a latest credential.
- [ ] Implement the exact new variants and context loader; prove no old semantic schema bytes or old record validation branch changes.

### B. Gateway and full-operation worker

- [ ] Pin `test_actual_text_roundtrip_all_five_operations`: independent fixture writes known UTF-8 input, captures real POST body, sends a native-shaped SSE sequence, and compares retained text bytes, exact operation outputs, usage and effects; also capabilities/catalog/status/cancel.
- [ ] Pin `test_cancel_while_upstream_blocks`: a barrier-controlled server waits after observing POST; status returns running, cancel is acknowledged before the operation deadline, original effect remains uncertain, every thread/socket closes.
- [ ] Pin `test_gateway_prepare_commit_revoke_and_replay`: zero requests before commit; wrong handle/version/body/origin/header denies; duplicate commit sends once; revocation before commit sends zero; cancellation after commit never claims definitely-unsent.
- [ ] Pin `test_real_encrypted_custody_delivery_only_for_issued_lease`: create a real test CredentialRoot/Vault, store_at actual sentinel bytes, retain the actual ciphertext receipt, prepare/commit through authenticated frames, decrypt through the new delivery method and observe the sentinel only at the controlled upstream; copied/foreign/replayed leases and retired/tampered records fail, while old resolve_for_gateway still denies. No fake vault or resolver monkeypatch is allowed.
- [ ] Pin `test_two_encrypted_credentials_cannot_swap_bound_handle`: actually store A/B; swap handle/connection revision/CM/CR/prepare/lease separately and coherent B mapping under bindingA; require zero sends for each. Exact A decrypts/sends once; B sentinel never appears.
- [ ] Pin `test_delivery_uses_one_deadline_through_custody`:100ms remaining with real independent RLock holder, flock holder and SQLite exclusive lock; cancellation during full metadata validation/progress; each aborts with zero write and no surviving thread/lease/lock. Add malformed sibling refusal and budget=None legacy behavior vectors. Implement optional files/journal seam without reducing any validation.
- [ ] Pin `test_gateway_no_secret_or_egress_escape`: sentinel test credential appears only in the controlled upstream auth header, never worker frames/logs/exceptions/results; redirects/proxy/header injection and wrong destination refuse.
- [ ] Implement finite dialogues/exchange; prove actual bounded pagination, distinguish complete availability from unknown/ineligible capability, refuse exhausted/invalid traversal, and reject unsupported model_step before commit.

### C. Real runtime consumer, cost and replay

- [ ] Pin `test_success_with_provisional_cost_retains_reservation`: real API-mode budget, one issued/consumed permit, actual controlled send, succeeded text result, usage_finality=provisional/usage=None; reservation remains held. Never set unknown currency to zero.
- [ ] Pin `test_crash_after_commit_never_resends`: restart core/gateway at each commit/send/response/seal/accept boundary; old command returns retained result or unknown, never reissues a permit or sends again.
- [ ] Pin `test_fresh_status_observes_terminal_but_old_request_replays`, `test_fresh_status_after_restart_is_unknown_without_resend`, `test_cancel_refresh_is_target_deduplicated` and `test_cancel_intent_crash_has_no_second_action`: actual target state changes, old result bytes preserved, new query ID observes current state, cancellation fence never resends/replaces the original model action.
- [ ] Pin `test_terminal_matrix_and_artifact_quarantine`: all 20 provider operation×terminal candidates; exactly 12 allowed canonical pairs, other8 refused; non-success artifacts empty; late/sealing-failed evidence never becomes authorized output.
- [ ] Pin `test_same_dispatcher_accepts_exact_provider_result`: use real NodeAttemptDispatcher/RuntimeLedger/BudgetBook; correct frozen call joins return the sealed result; changed envelope/attempt/catalog/connection/lease/budget joins reject; no tool-binding or raw SDK shortcut.
- [ ] Pin `test_default_assembly_cannot_reach_test_authority`: no support imports/test flags/service export/new routes in production assembly; authentic C is not claimed by synthetic record contents.
- [ ] Implement consumer and run targeted + affected legacy regressions under the eventual controller command. Only after scoped review can the **offline semantic tranche** be accepted; never infer native/live readiness or whole T087/T090 completion.

## 10. Controller choices, closure and real gates

The final255-line official-source note was read completely. The first independent preflight was **NOT READY** on F1–F3; its report remains unchanged. This R1 proposes exact corrections below and in the appendix/amendment for the same reviewer's bounded re-review, not an accepted executable dispatch.

- Replace one-page32 refusal with <=20pages/256unique actual forward paging. Reason: canonical arrays and existing foundations support a useful finite traversal. Cost: retain more raw evidence and test cursor/duplicate/order failure boundaries.
- Isolate new codec rather than alter accepted private B. Reason: new nullable nested ModelInfo and usage shapes differ from old transforms. Cost: some duplicated pure normalization logic; no old evidence meaning changes.
- Select reviewed conservative estimate for offline positive budget proof, not an invented counting margin and not a requirement for both canonical alternatives. A documented enforced provider spend limit remains a different allowed future branch. Cost: real review/estimate producer remains needed; unknown currency retains reservations even on valid text.
- Adopt dated, bounded, explicitly reviewed text-policy scope rather than source-URL-as-truth. Cost: future/new model IDs and expired policy do not auto-enable; existing Models API capabilities/limits still remain primary per-model observations.
- Keep4input/4output/30s as provisional integration-fit limits. Broader product180s target and all mandatory provider/managed Codex scope remain unchanged.
- Preserve old resolver denial; new positive tests traverse the actual issued lease, encrypted ciphertext/root.open, stream, worker, guard and ledger. No fake vault, monkeypatched resolver, production fixture selector or callback pass map.
- F1: replace all-operation semantic-key uniqueness with an explicitly approved profile-scoped read observation exception; cancel separately uses target-monotonic intent, while model effects keep semantic-key dedup. Reason: changing status/catalog must be observable without false purpose/binding changes. Cost: fresh UUID discipline, additional immutable observations and a narrow canonical amendment; no other port is silently generalized.
- F2: thread an optional absolute CustodyBudget through controllable custody waits/full checks instead of retaining independent5s budgets or abandoning a blocked helper. Reason: existing software waits contradicted the promised deadline. Cost: two narrow support-file edits, cancellation-aware SQLite checkpoints and immediate busy refusal instead of waiting/retry in the new path, plus extra contention regressions; uninterruptible real platform calls remain honest fit gates.
- F3: use this profile's exact immutable connection snapshot as its opaque handle, with a fingerprinted CM and exact CR plus current account/provider/revision. Reason: reuses existing record vocabulary and removes handleA→credentialB ambiguity without a registry. Cost: any connection/credential revision requires a new handle/config/binding; real current-connection/binding issuer remains absent.

Remaining gates are concrete actual producers/authority, not missing parser fields: authorized text-scope/reservation review; current native C/binding/permission/connection producers; genuine release inputs/rights/keys/scans/fit and new-artifact admission beyond Task46's cap1; supported-platform cancellation/transport measurements and authorized upstream compatibility. None is fabricated by synthetic reports or source documentation. Offline implementation can progress once design preflight and accepted46 scope reconciliation complete; production activation cannot.

R1 self-review: F1 exact read/cancel applicability, unchanged hash/result bytes and no-second-model-effect cases are explicit; F2 old defaults/all checks versus new absolute budget and no-thread-abandonment are distinguished; F3 selected handle equality is pinned through actual encrypted delivery with two-credential swaps. Scope adds only the two custody support files prospectively, no production authority. The scoped canonical ruling and bounded re-review remain gates; no product/canonical/test edits, execution, network/native work, helper or commit occurred.
