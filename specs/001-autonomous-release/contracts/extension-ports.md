# Extension semantic port schema contract

2026-09-08 · `extension-ports-v1` · Normative design contract; implementation and qualification are
owned by T087 and remain open.

## 1. Scope, ownership and exported artifacts

The authenticated worker envelope is transport only. The DeepTwin core owns every semantic port
contract below, including its operation names, base configuration/request/result/error shapes,
authority, effect, idempotency, cancellation, terminal-state and artifact semantics. An extension
author owns a manifest and permitted refinements; the author SDK never authors, registers or changes
a core port contract.

T087 MUST export four closed JSON Schema artifacts for each port under
`schemas/v1/extensions/ports/<port-name>/{config,request,result,error}.schema.json`. Their canonical
identifiers are
`https://deeptwin.local/schemas/v1/extensions/ports/<port-name>/<shape>.schema.json`, where
`<shape>` is exactly `config`, `request`, `result` or `error`. Each artifact has
`$schema=https://json-schema.org/draft/2020-12/schema`, `type=object`,
`additionalProperties=false`, and the required fields listed here. The installed author SDK ships
read-only copies or generated bindings whose digests equal the server-exported schemas; it does not
replace them.

The closed port names are:

1. `provider-port-v1`
2. `managed-provider-runner-port-v1`
3. `model-runtime-port-v1`
4. `tool-port-v1`
5. `artifact-codec-port-v1`
6. `lens-definition-port-v1`
7. `evaluator-definition-port-v1`
8. `evaluator-runtime-port-v1`
9. `storage-port-v1`
10. `credential-vault-port-v1`
11. `export-sink-port-v1`

Unknown ports, operations, terminal states, error codes or fields fail closed. A schema identifier
from one port or shape cannot validate another.

## 2. Common closed shapes

### 2.0 Exact type vocabulary and expansion rule

The following aliases are normative JSON Schema constraints, not prose hints. `identifier` is a
UTF-8 string matching `^[a-z][a-z0-9._:-]{0,127}$`; `short-text` is a 1–512 character NFC string
matching `^[^\u0000-\u001f\u007f-\u009f]{1,512}$`; `version-text` uses the same pattern with
`maxLength=128`. `media-type` is a deliberately strict lowercase, parameter-free subset matching
`^[a-z0-9][a-z0-9!#$&^_.+-]{0,126}/[a-z0-9][a-z0-9!#$&^_.+-]{0,126}$`. `https-uri` has
`format=uri`, `minLength=1`, `maxLength=2048`, scheme exactly `https`, a nonempty ASCII host, no
userinfo/fragment, normalized percent escapes/path and no explicit default port. `bool` is a JSON
boolean. `positive-int` is a JSON integer from 1 through
9,007,199,254,740,991; `nonnegative-int` is 0 through that maximum. `digest` is a lowercase
64-character SHA-256 hex string. `time` matches
`^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$` and must be a valid UTC
calendar instant. `uuid` matches
`^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$`.

`ref` is the closed `EntityRef` object
`{kind:identifier,id:uuid,version:positive-int,sha256:digest}` from `data-model.md`. It never means a
bare ID, URL or mutable head. `T|null` is a required field whose value is either exact `T` or JSON
null; no listed field is optional. `T[]` is an array of 0–256 exact `T` values; a row that says
`sorted unique` additionally requires canonical byte-order sorting and `uniqueItems=true`.
`identifier-map<T>` is a closed-by-key map of 0–64 properties whose names are `identifier`, values
are exact `T`, and keys are canonical byte-order sorted. `effect-class` is exactly
`none|read|write_reversible|external_reversible|external_irreversible|instance_critical_secret|instance_critical_storage`.
An envelope is rejected before semantic validation if canonical JSON exceeds 1,048,576 bytes, has
nesting deeper than 8, contains a string longer than 4,096 characters except a bounded URI, or has an
array/map beyond these caps. Artifact bytes remain out of band and use the per-request limits below.

Every field in §§2–3 is required. The notation `x?:T` used in §3 means required `x:T|null`, never an
omittable field. Every named object and array item is closed with `additionalProperties=false`.
T087 expands the common fields plus exactly one port row into each of the 44 artifacts: config uses
the exact §2.1 fields and that row's `port_config`; request uses §2.2 and a discriminated `oneOf` for
that row's operation/input arms; result uses §2.3 plus §3.8's matching operation×terminal output/
artifact arm; error uses §2.4 and that row's port-error enum. Discriminators are literal `operation`
and `terminal`. No generator may
infer a field, reuse prose such as “same fields”, or weaken a bound. Local `$defs` may de-duplicate
these exact aliases/objects byte-for-byte, but remote or dynamic `$ref` is forbidden.

`BindingSlotKeyV1` is one closed object and has exactly five fields:
`{port_contract_version:identifier,target_scope_fingerprint:digest,purpose:identifier,
binding_slot_id:identifier,capability_selector_digest:digest}`. Its digest is SHA-256 of the ADR-008
canonical JSON of that exact object. `extension_id` is deliberately not a key field. Every config,
resolved binding revision, bind/disable/rollback/retention command and result, stored head and public
event MUST carry or resolve the byte-identical object and recomputed digest. A four-field projection,
a digest computed without `port_contract_version`, or a sibling/nested version mismatch is invalid.

`ArtifactInputBindingV1` is the closed object
`{artifact_ref:ref,selector_ref:ref|null,declared_media_type:media-type,role:identifier}`. The artifact
ref resolves to one durable `Artifact`; its media type equals `declared_media_type`. A non-null
selector resolves to one immutable `ArtifactInputSelectorV1`, whose `source_artifact_ref` equals the
entry's `artifact_ref`, whose purpose equals the request purpose and whose digest is valid. Entries
are unique by canonical `(artifact_ref,selector_ref,role)` tuple. §3.9, not the generic array bound,
is the authority for whether each operation forbids, permits or requires entries and for its exact
minimum, maximum, role, media and selector relationship.

### 2.1 `config`

| Field | Exact type and meaning |
| --- | --- |
| `schema_id` | const canonical config schema ID for this port |
| `schema_version` | const `1` |
| `port_contract_version` | const matching closed port name |
| `extension_id` | `identifier`; stable extension identity |
| `installation_digest` | `digest`; exact verified installation-record digest |
| `qualification_ref` | `ref`; unexpired qualification for this context |
| `binding_revision_ref` | `ref`; exact immutable active binding revision |
| `binding_slot_key` | exact `BindingSlotKeyV1`; its nested `port_contract_version` equals the sibling common field and the resolved binding revision's key byte-for-byte |
| `binding_slot_key_digest` | `digest`; recomputed SHA-256 of ADR-008 canonical `binding_slot_key`, equal to the resolved binding revision/head digest |
| `extension_config` | closed refinement object with 0–64 `identifier` properties under §4, or exactly `{}` when no config refinement exists |
| `grant_refs` | sorted unique `ref[]`; exact grants, possibly empty |
| `credential_handle_refs` | sorted unique `ref[]`; opaque handles, possibly empty and never raw secrets |
| `resource_limits` | `{deadline_ms:positive-int<=600000,max_input_bytes:positive-int<=1048576,max_output_bytes:positive-int<=1048576,max_artifacts:nonnegative-int<=256,max_artifact_bytes:positive-int<=67108864,max_artifact_input_bytes:positive-int<=67108864}` |
| `port_config` | closed per-port object specified in §3 |

### 2.2 `request`

| Field | Exact type and meaning |
| --- | --- |
| `schema_id` | const canonical request schema ID for this port |
| `schema_version` | const `1` |
| `port_contract_version` | const matching closed port name |
| `request_id` | `uuid`; globally unique immutable request ID |
| `operation` | one closed operation enum from §3 |
| `installation_digest` | `digest`; exact value from validated config |
| `qualification_ref` | `ref`; exact value from validated config |
| `binding_revision_ref` | `ref`; exact value from validated config |
| `purpose_ref` | `ref`; immutable purpose/attempt/evaluation/export purpose |
| `actor_ref` | `ref`; authenticated system/worker actor, never extension-supplied human authority |
| `grant_refs` | sorted unique `ref[]`; exact subset of config grants required by the operation |
| `idempotency_key` | `digest`; SHA-256 of canonical `{port_contract_version,installation_digest,binding_revision_ref,purpose_ref,operation,grant_refs,artifact_inputs,input,extension_input}` and never reused for changed semantic input |
| `deadline_at` | `time`; later than acceptance and no later than config `deadline_ms` from acceptance |
| `cancellation_ref` | `ref\|null`; cancellation token or null |
| `artifact_inputs` | ordered `ArtifactInputBindingV1[]`; the operation-specific branch MUST impose the exact §3.9 profile and cannot inherit 0–256 as permission |
| `input` | closed operation-specific object specified in §3 |
| `extension_input` | closed refinement object with 0–64 `identifier` properties under §4, or exactly `{}` when none |

### 2.3 `result`

| Field | Exact type and meaning |
| --- | --- |
| `schema_id` | const canonical result schema ID for this port |
| `schema_version` | const `1` |
| `port_contract_version` | const matching closed port name |
| `request_id` | `uuid`; exact request ID |
| `operation` | exact requested operation |
| `terminal` | exactly `succeeded\|failed\|cancelled\|unknown` |
| `started_at` / `completed_at` | `time` / `time\|null`; observed start and terminal timestamps; completed_at is null only for `unknown` |
| `output` | closed operation-specific object on `succeeded`, otherwise `{}` |
| `extension_output` | closed refinement object with 0–64 `identifier` properties under §4 on `succeeded`, otherwise `{}` |
| `artifacts` | ordered array of `{artifact_ref:ref,media_type:media-type,role:identifier,content_digest:digest,byte_count:nonnegative-int,omissions_ref:ref\|null}`; exact operation×terminal cardinality and every role/media/omissions/ref equality are closed by §3.8 |
| `usage` | object `{input_units:nonnegative-int\|null,output_units:nonnegative-int\|null,billed_units:nonnegative-int\|null,unit_name:identifier\|null,provider_report_ref:ref\|null}`; never guessed |
| `effect` | `{effect_class:effect-class,effect_state:none\|not_committed\|committed\|unknown,effect_receipt_ref:ref\|null,remote_outcome:not_applicable\|confirmed\|unconfirmed\|unknown}` |
| `error` | `null` only when terminal=`succeeded`; otherwise the exact §2.4 error object |

`result.effect` is the sole effect/outcome truth. The embedded error does not repeat an effect state.
For every `failed|cancelled|unknown` result, `output={}`,
`extension_output={}` and `artifacts=[]` exactly. No automatic retry follows `unknown`. Partial,
late or staging bytes may be retained only as quarantined private evidence outside the semantic
result; they cannot become an authorized artifact merely because their bytes were sealed.

The result discriminator is closed: `succeeded` requires non-error output and `error=null`; `failed`
requires the exact error object with code other than `cancelled` or `external_effect_unknown`;
`cancelled` requires empty outputs, `error.code=cancelled` and `error.retry_class=never`; `unknown`
requires empty outputs, `error.code=external_effect_unknown`, `error.retry_class=never` and the
unknown effect tuple below. A failed result cannot use either special code. No port or refinement may
add a fifth terminal or relax these relations.

Effect families are `N=none|read`, `L=write_reversible`, and
`X=external_reversible|external_irreversible|instance_critical_secret|instance_critical_storage`.
In the following exhaustive table, `null` means JSON null and `ref` means a non-null exact receipt;
each parenthesized value is exactly `(effect_state,effect_receipt_ref,remote_outcome)`. Any tuple not
listed for a terminal+family is invalid.

| Terminal | `N` allowed effect tuples | `L` allowed effect tuples | `X` allowed effect tuples |
| --- | --- | --- | --- |
| `succeeded` | `(none,null,not_applicable)` | `(committed,ref,not_applicable)` | `(committed,ref,confirmed)` |
| `failed` | `(none,null,not_applicable)` | `(none,null,not_applicable)` or `(not_committed,ref,not_applicable)` | `(none,null,not_applicable)` or `(not_committed,ref,confirmed)` |
| `cancelled` | `(none,null,not_applicable)` | `(none,null,not_applicable)`, `(not_committed,ref,not_applicable)`, `(committed,ref,not_applicable)` or `(unknown,ref,not_applicable)` | `(none,null,not_applicable)`, `(not_committed,ref,confirmed)`, `(committed,ref,confirmed)`, or `(unknown,null\|ref,unconfirmed\|unknown)` |
| `unknown` | forbidden | `(unknown,ref,not_applicable)` | `(unknown,null\|ref,unconfirmed\|unknown)` |

Thus a successful external/instance-critical mutation cannot report unknown or unconfirmed effect,
and a semantic `failed` result can never carry an unknown/committed effect. `after_backoff` is valid
only on `failed` with one of its listed known-none/not-committed tuples; cancellation and unknown are
never retryable. A result that cannot prove a listed failed tuple uses `unknown`, is held, and is not
automatically retried.

### 2.4 `error`

| Field | Exact type and meaning |
| --- | --- |
| `schema_id` | const canonical error schema ID for this port |
| `schema_version` | const `1` |
| `port_contract_version` | const matching closed port name |
| `request_id` | `uuid`; exact request ID |
| `operation` | exact requested operation |
| `code` | exactly one core code below |
| `port_error_code` | exact row-specific port enum or `null`; non-null iff `code=port_specific_failure` |
| `extension_error_code` | `identifier\|null`; a manifest-frozen extension refinement code is permitted only when `code=port_specific_failure`, otherwise null |
| `message_class` | exactly `validation\|unsupported\|permission\|timeout\|cancelled\|capacity\|dependency\|integrity\|external_outcome\|port_failure\|internal`; no raw provider/secret/path/stack content |
| `retry_class` | exactly `never\|after_backoff\|after_requalification\|human_action_required` |
| `affected_refs` | sorted unique `ref[]`, possibly empty |
| `evidence_ref` | `ref\|null`; private failure evidence or null |

Core `code` is exactly one of `invalid_request`, `unsupported_operation`, `unsupported_capability`,
`permission_denied`, `deadline_exceeded`, `cancelled`, `resource_exhausted`,
`dependency_unavailable`, `integrity_failed`, `external_effect_unknown`,
`port_specific_failure`, `internal_failure`. Transport authentication/framing failure occurs before
this semantic schema and cannot be relabelled as a port success.

## 3. Port-specific closed definitions

The exact types and `x?:T` nullable notation are defined in §2.0. Each `port_config`, operation
`input`, successful `output`, and nested object is closed and rejects every unlisted field. Values in
capability arrays must be declared by the bound manifest/config; a syntactically valid undeclared
identifier is `unsupported_capability`, not an implicit capability.

### 3.1 Provider and model execution

| Port | Exact closed `port_config` | Exact operation: `input` → successful `output` | Closed port-error enum |
| --- | --- | --- | --- |
| `provider-port-v1` | `{provider_id:identifier,auth_mode:api,api_origin:https-uri,egress_policy_ref:ref,catalog_ttl_seconds:positive-int<=86400,supported_modalities:sorted unique identifier[],supported_input_media_types:sorted unique media-type[]}` | `capabilities`: `{}` → `{modalities:sorted unique identifier[],tool_calling:bool,usage_reporting:bool,cancellation:bool}`; `catalog`: `{catalog_epoch?:ref}` → `{catalog_ref:ref,complete:bool,models:{model_id:identifier,display_name:short-text,modalities:sorted unique identifier[],effort_values:sorted unique identifier[],capability_evidence_ref:ref}[]}`; `model_step`: `{frozen_turn_ref:ref,model_id:identifier,effort:identifier,requested_modalities:sorted unique identifier[],tool_definition_refs:sorted unique ref[],response_schema_ref?:ref}` → `{provider_id:identifier,model_id:identifier,content_block_refs:ref[],tool_proposal_refs:ref[],usage_report_ref?:ref,provider_response_ref:ref}`; `status`: `StatusOperation`; `cancel`: `CancelOperation` | `auth_failed\|catalog_incomplete\|model_unavailable\|rate_limited\|billing_blocked\|provider_protocol_error` |
| `managed-provider-runner-port-v1` | `{provider_id:identifier,runner_profile_ref:ref,binary_digest:digest,tool_bridge_profile_ref:ref,auth_volume_profile_ref:ref,supported_event_types:sorted unique identifier[],supported_input_media_types:sorted unique media-type[]}` | `preflight`: `{requested_model_id?:identifier,requested_effort?:identifier}` → `{observed_binary_digest:digest,runner_version:version-text,auth_state:disconnected\|pending\|authenticated\|expired\|failed,model_acceptance:accepted\|unsupported\|unknown,capability_evidence_ref:ref}`; `device_auth_start`: `{login_intent_ref:ref}` → `{login_operation_ref:ref,verification_url:https-uri,user_code:short-text,expires_at:time}`; `device_auth_status`: `{login_operation_ref:ref}` → `{state:pending\|completed\|cancelled\|expired\|failed}`; `device_auth_cancel`: `{login_operation_ref:ref}` → `{cancel_state:accepted\|already_terminal\|not_cancellable,observed_at:time}`; `run_start`: `{frozen_run_projection_ref:ref,model_id:identifier,effort:identifier,tool_definition_refs:sorted unique ref[]}` → `{runner_run_ref:ref,event_cursor:ref}`; `run_status`: `{runner_run_ref:ref,event_cursor?:ref}` → `{state:pending\|running\|succeeded\|failed\|cancelled\|unknown,normalized_event_refs:ref[],usage_report_ref?:ref}`; `run_cancel`: `{runner_run_ref:ref,reason_class:user_requested\|deadline\|budget\|superseded\|shutdown\|policy_revoked}` → `{cancel_state:accepted\|already_terminal\|not_cancellable,observed_at:time}` | `auth_required\|device_flow_expired\|runner_version_mismatch\|tool_bridge_failed\|runner_protocol_error` |
| `model-runtime-port-v1` | `{runtime_profile_ref:ref,model_catalog_ref:ref,supported_modalities:sorted unique identifier[],supported_efforts:sorted unique identifier[],supported_input_media_types:sorted unique media-type[]}` | `capabilities`: `{}` → `{model_ids:sorted unique identifier[],modalities:sorted unique identifier[],effort_values:sorted unique identifier[],tool_calling:bool}`; `model_step`: `{frozen_turn_ref:ref,model_id:identifier,effort:identifier,requested_modalities:sorted unique identifier[],tool_definition_refs:sorted unique ref[],response_schema_ref?:ref}` → `{runtime_profile_ref:ref,model_id:identifier,content_block_refs:ref[],tool_proposal_refs:ref[],usage_report_ref?:ref,runtime_response_ref:ref}`; `status`: `StatusOperation`; `cancel`: `CancelOperation` | `model_not_loaded\|model_incompatible\|inference_failed\|runtime_protocol_error` |

### 3.2 Tool and artifact codec

| Port | Exact closed `port_config` | Exact operation: `input` → successful `output` | Closed port-error enum |
| --- | --- | --- | --- |
| `tool-port-v1` | `{tool_definition_refs:sorted unique ref[],effect_policy_ref:ref,artifact_policy_ref:ref,network_policy_ref?:ref,filesystem_policy_ref?:ref}` | `describe_tools`: `{requested_tool_ids:sorted unique identifier[]}` → `{tools:{tool_id:identifier,version:version-text,argument_schema_ref:ref,result_schema_ref:ref,effect_class:effect-class,artifact_roles:sorted unique identifier[]}[]}`; `invoke_tool`: `{tool_id:identifier,tool_version:version-text,arguments_ref:ref,grant_ref:ref,expected_effect_class:effect-class,external_target_ref?:ref}` → `{tool_call_ref:ref,result_ref:ref}`; `status`: `StatusOperation`; `cancel`: `CancelOperation` | `tool_not_found\|tool_version_mismatch\|arguments_invalid\|effect_denied\|execution_failed\|effect_outcome_unknown` |
| `artifact-codec-port-v1` | `{input_media_types:sorted unique media-type[],output_media_types:sorted unique media-type[],selector_kinds:sorted unique identifier[],determinism:deterministic\|declared_nondeterministic,conversion_limits_ref:ref}` | `probe`: `{}` → `{media_type:media-type,supported_operations:sorted unique (decode_projection\|render_preview\|encode)[],limit_evidence_ref:ref}`; `decode_projection`: `{target_projection_schema_ref:ref}` → `{projection_artifact_ref:ref,omissions_ref:ref}`; `render_preview`: `{target_media_type:media-type,render_options_ref?:ref}` → `{preview_artifact_ref:ref,omissions_ref:ref}`; `encode`: `{target_media_type:media-type,encode_options_ref?:ref}` → `{encoded_artifact_ref:ref,omissions_ref:ref}`; `cancel`: `CancelOperation` | `media_unsupported\|selector_unsupported\|decode_failed\|render_failed\|encode_failed\|content_rejected` |

The successful `invoke_tool` output is exactly the two-field object shown above. An output-level
`effect_receipt_ref` or any alias is forbidden: the common
`result.effect.effect_receipt_ref` is the only effect-receipt truth for every terminal.

### 3.3 Lens and evaluator

`application-point` is exactly `initial_generation|critic_inquiry|post_alternative`. `decision` is
exactly `pass|fail|abstain|invalid`.

| Port | Exact closed `port_config` | Exact operation: `input` → successful `output` | Closed port-error enum |
| --- | --- | --- | --- |
| `lens-definition-port-v1` | `{definition_ref:ref,composition_contract_ref:ref,source_map_ref:ref,allowed_application_points:sorted unique application-point[]}` | `validate_definition`: `{definition_ref:ref,source_map_ref:ref}` → `{valid:bool,issue_refs:ref[]}`; `compose`: `{atomic_lens_refs:ref[],composition_policy_ref:ref}` → `{composition_ref:ref,conflict_refs:ref[],abstention_ref?:ref}`; `apply_decision`: `{work_model_ref:ref,application_point:application-point,composition_ref:ref,evidence_refs:ref[]}` → `{question_refs:ref[],decision_contribution_refs:ref[],abstention_ref?:ref}` | `definition_invalid\|composition_invalid\|source_missing\|application_point_unsupported` |
| `evaluator-definition-port-v1` | `{rubric_ref:ref,scoring_contract_ref:ref,abstention_policy_ref:ref,allowed_evidence_kinds:sorted unique identifier[]}` | `describe_rubric`: `{rubric_ref:ref}` → `{criteria_refs:ref[],scoring_contract_ref:ref,abstention_policy_ref:ref}`; `evaluate`: `{candidate_ref:ref,evidence_refs:ref[],evaluation_profile_ref:ref}` → `{evaluation_result_ref:ref,score_ref?:ref,decision:pass\|fail\|abstain\|invalid,unavailable_item_refs:ref[]}`; `abstain`: `{candidate_ref:ref,reason_code:identifier,unavailable_item_refs:ref[]}` → `{evaluation_result_ref:ref,decision:abstain}` | `rubric_invalid\|evidence_insufficient\|evaluation_failed\|evaluation_invalid` |
| `evaluator-runtime-port-v1` | `{rubric_ref:ref,scoring_contract_ref:ref,abstention_policy_ref:ref,allowed_evidence_kinds:sorted unique identifier[],runtime_profile_ref:ref,model_choice_ref?:ref,isolation_profile_ref:ref}` | `describe_rubric`: `{rubric_ref:ref}` → `{criteria_refs:ref[],scoring_contract_ref:ref,abstention_policy_ref:ref}`; `evaluate`: `{candidate_ref:ref,evidence_refs:ref[],evaluation_profile_ref:ref}` → `{evaluation_result_ref:ref,score_ref?:ref,decision:pass\|fail\|abstain\|invalid,unavailable_item_refs:ref[]}`; `abstain`: `{candidate_ref:ref,reason_code:identifier,unavailable_item_refs:ref[]}` → `{evaluation_result_ref:ref,decision:abstain}`; `status`: `StatusOperation`; `cancel`: `CancelOperation` | `rubric_invalid\|evidence_insufficient\|evaluation_failed\|evaluation_invalid\|runtime_unavailable\|evaluator_protocol_error` |

### 3.4 Instance-critical storage and vault

| Port | Exact closed `port_config` | Exact operation: `input` → successful `output` | Closed port-error enum |
| --- | --- | --- | --- |
| `storage-port-v1` | `{namespace_id:identifier,schema_version:version-text,transaction_profile_ref:ref,migration_profile_ref:ref,exclusive_owner_instance_id:identifier,accepted_value_media_types:sorted unique media-type[]}` | `capabilities`: `{}` → `{transaction_modes:sorted unique (read_only\|write_cas\|migration)[],max_object_bytes:positive-int<=67108864,cas:bool}`; `health`: `{}` → `{state:healthy\|degraded\|unavailable,evidence_ref:ref}`; `migrate_plan`: `{from_schema:version-text,to_schema:version-text,snapshot_ref:ref}` → `{migration_plan_ref:ref,reversible:bool}`; `read`: `{object_ref:ref,expected_revision?:positive-int,purpose_ref:ref}` → `{object_artifact_ref:ref,revision:positive-int}`; `write_cas`: `{object_ref:ref,expected_revision?:positive-int,next_revision:positive-int,transaction_key:digest}` → `{transaction_ref:ref,revision:positive-int,commit_ref:ref}` | `revision_conflict\|schema_mismatch\|migration_unsafe\|storage_corrupt\|storage_unavailable` |
| `credential-vault-port-v1` | `{vault_id:identifier,algorithm_profile_ref:ref,trust_root_ref:ref,supported_secret_types:sorted unique identifier[],exclusive_owner_instance_id:identifier}` | `capabilities`: `{}` → `{secret_types:sorted unique identifier[],rotation:bool,secure_erasure_profile_ref:ref}`; `health`: `{}` → `{state:healthy\|degraded\|unavailable,evidence_ref:ref}`; `store`: `{intent_ref:ref,record_id:identifier,expected_version?:positive-int,next_version:positive-int,secret_type:identifier,secret_ingress_ref:ref}` → `{record_ref:ref,opaque_handle_ref:ref,version:positive-int}`; `resolve_for_gateway`: `{opaque_handle_ref:ref,provider_request_intent_ref:ref}` → `{gateway_delivery_ref:ref}`; `retire`: `{record_ref:ref,expected_version:positive-int}` → `{retirement_receipt_ref:ref}`; `erase`: `{record_ref:ref,retirement_receipt_ref:ref}` → `{erasure_receipt_ref:ref,complete:bool}` | `secret_invalid\|key_unavailable\|record_conflict\|rotation_incomplete\|retirement_required\|erase_incomplete\|vault_unavailable` |

### 3.5 Export sink

| Port | Exact closed `port_config` | Exact operation: `input` → successful `output` | Closed port-error enum |
| --- | --- | --- | --- |
| `export-sink-port-v1` | `{destination_kind:identifier,network_policy_ref:ref,delivery_policy_ref:ref,supported_media_types:sorted unique media-type[]}` | `capabilities`: `{}` → `{destination_kind:identifier,media_types:sorted unique media-type[],cancellation:bool,status_query:bool}`; `prepare`: `{snapshot_ref:ref,target_ref:ref,consent_challenge_ref:ref}` → `{prepared_delivery_ref:ref,content_manifest_ref:ref}`; `transmit`: `{prepared_delivery_ref:ref,target_ref:ref,consent_decision_ref:ref}` → `{delivery_ref:ref,delivery_receipt_ref?:ref}`; `status`: `StatusOperation`; `cancel`: `CancelOperation` | `destination_invalid\|consent_required\|content_unsupported\|transmit_failed\|delivery_unknown` |

### 3.6 Exact reusable operation definitions

The local `$defs` names are exactly `status-operation-input-v1`, `status-operation-output-v1`,
`cancel-operation-input-v1` and `cancel-operation-output-v1`. `StatusOperation` expands byte-for-byte
to `status` input `{operation_ref:ref}` and successful output
`{observed_state:pending|running|succeeded|failed|cancelled|unknown,observed_at:time,
terminal_result_ref?:ref}`. `CancelOperation` expands byte-for-byte to `cancel` input
`{operation_ref:ref,reason_class:user_requested|deadline|budget|superseded|shutdown|policy_revoked}`
and successful output `{cancel_state:accepted|already_terminal|not_cancellable,observed_at:time}`.
The nullable `terminal_result_ref` is present with null when unavailable. These are fixed local core
definitions, not extension inheritance; a port without the named operation rejects it.

### 3.7 Per-operation effect, idempotency, cancellation and artifact constraints

Every request is idempotent by the §2.2 key. Read/describe/capability/status/probe/validation/
preparation operations require the exact `effect_class` fixed below and may be retried
only with the same key after a terminal `failed` whose error retry class permits it. A changed input
requires a new key. Write/external operations never retry an `unknown` outcome. `cancel` and the
runner-specific cancel operations report cancellation separately from remote/effect outcome.

| Operations | Required result effect class | Cancellation | Successful artifact/output invariant |
| --- | --- | --- | --- |
| `capabilities`, `catalog`, `preflight`, `device_auth_status`, `run_status`, `status`, `describe_tools`, `probe`, `validate_definition`, `describe_rubric`, `health` | `read` | query itself is not cancellable | referenced evidence/catalog/status bytes are already immutable and sealed |
| provider/model `model_step`, runner `run_start` | `external_irreversible` because provider usage/billing may survive cancellation | only when that port exposes `cancel`/`run_cancel`; late/unknown results retain their effect state | every returned content/tool-proposal/event/usage ref is sealed before `succeeded`; unknown remote usage is never guessed or retried |
| tool `invoke_tool` | exact core-validated ToolDefinition `effect_class`, which must equal request `expected_effect_class` | only through the port `cancel`; late/unknown results retain their effect state | result and effect receipt are sealed; a stronger/different runtime class fails before execution |
| codec `decode_projection`/`render_preview`/`encode`, lens `compose`/`apply_decision`, evaluator `evaluate`/`abstain` | `write_reversible` | codec/evaluator runtime only through exposed `cancel`; definition-only lens/evaluator operations have no cancel | every produced projection/preview/encoded/composition/decision/evaluation ref is sealed before `succeeded`; omissions and abstentions remain explicit |
| `device_auth_start` | `external_reversible` | only `device_auth_cancel` | login operation and expiry are returned; no credential is returned or logged |
| storage `migrate_plan`, `read` | `read` | no cancel operation | plan/object artifact is immutable; read never advances a revision |
| storage `write_cas` | `instance_critical_storage` | not cancellable after commit starts | exact expected/next revision and commit ref agree atomically |
| vault `store`, `resolve_for_gateway`, `retire`, `erase` | `instance_critical_secret` | not cancellable after secret ingress/commit starts | no raw secret appears in result/artifacts; version/retirement/erasure receipt is exact |
| export `prepare` | `read` | not cancellable | prepared content manifest is immutable and consent does not carry over to changed bytes/target |
| export `transmit` | `external_reversible\|external_irreversible` fixed by qualified destination config | `cancel` is best effort; unknown delivery is never auto-retried | receipt may be null only when delivery is unconfirmed/unknown and effect state reflects that |
| every `cancel`, `device_auth_cancel`, `run_cancel` | `none` | operation is the cancellation request | cancellation output is not proof that prior work/effect did not occur |

These core rules, not an extension-authored schema or manifest choice, constrain
`effect.effect_class`. The qualified manifest must repeat the applicable class as a consistency
claim, but can neither choose nor strengthen it; ToolDefinition and qualified export-destination
records are core-owned inputs to their explicitly dynamic rows. All other rows use the literal class
or listed closed union.
Artifact roles in §2.3 must occur in the operation's qualified manifest artifact-role set; an empty
set forbids artifacts even if the generic array bound would otherwise allow them.

### 3.8 Exhaustive operation, terminal and artifact-cardinality matrix

The 11 ports expose exactly 52 port-qualified operations. The result schema generator MUST evaluate
all 208 operation×four-terminal candidates, emit exactly the 127 allowed `oneOf` branches below and
reject the other 81 pairs. No candidate may be missing or duplicated. A query-class success reports remote `unknown` or
`cancelled` state inside its successful output where that output defines such a state; it does not
turn the query result itself into an `unknown` or `cancelled` terminal.

| Terminal class | Exact operations | Allowed result terminals |
| --- | --- | --- |
| `Q` deterministic/query/cancel acknowledgement | provider `capabilities,catalog,status,cancel`; managed runner `preflight,device_auth_status,device_auth_cancel,run_status,run_cancel`; model runtime `capabilities,status,cancel`; tool `describe_tools,status,cancel`; codec `probe,cancel`; lens `validate_definition,compose,apply_decision`; evaluator definition `describe_rubric,evaluate,abstain`; evaluator runtime `describe_rubric,abstain,status,cancel`; storage `capabilities,health,migrate_plan,read`; vault `capabilities,health`; export `capabilities,prepare,status,cancel` | `succeeded\|failed` |
| `C` cancellable work with an independently uncertain effect | provider `model_step`; model runtime `model_step`; tool `invoke_tool`; codec `decode_projection,render_preview,encode`; evaluator runtime `evaluate`; export `transmit` | `succeeded\|failed\|cancelled\|unknown` |
| `M` non-cancellable once mutation/start commit begins | managed runner `device_auth_start,run_start`; storage `write_cas`; vault `store,resolve_for_gateway,retire,erase` | `succeeded\|failed\|unknown` |

For every allowed terminal other than `succeeded`, `artifacts` is exactly `[]`. This includes every
cancelled codec operation: a cancelled `decode_projection`, `render_preview` or `encode` carrying even
one artifact is invalid. Successful artifact cardinality is also closed:

Only the `V`/`O` rows below authorize transferable byte artifacts in the common `artifacts` array.
Catalog, plan, rubric, evaluation, receipt, evidence, status and other output refs remain their typed
domain records even when immutable; their presence never implicitly authorizes an artifact entry.

| Port | `V` variable artifact operations | `O` exact-one artifact operations | Successful operations requiring `artifacts=[]` |
| --- | --- | --- | --- |
| provider | `model_step` | — | `capabilities,catalog,status,cancel` |
| managed provider runner | `run_status` | — | `preflight,device_auth_start,device_auth_status,device_auth_cancel,run_start,run_cancel` |
| model runtime | `model_step` | — | `capabilities,status,cancel` |
| tool | `invoke_tool` | — | `describe_tools,status,cancel` |
| artifact codec | — | `decode_projection,render_preview,encode` | `probe,cancel` |
| lens definition | — | — | all three operations |
| evaluator definition | — | — | all three operations |
| evaluator runtime | — | — | all five operations |
| storage | — | `read` | `capabilities,health,migrate_plan,write_cas` |
| credential vault | — | — | all six operations |
| export sink | — | — | all five operations |

`V` means 0 through the validated config's `resource_limits.max_artifacts`; `O` requires
`max_artifacts>=1`, `minItems=maxItems=1`, and the sole `artifact_ref` equals respectively the
successful output's `projection_artifact_ref`, `preview_artifact_ref`, `encoded_artifact_ref` or
`object_artifact_ref`. Every `V`/`O` item has unique `artifact_ref`; `media_type`, `content_digest` and
`byte_count` equal the durable Artifact's media type, content digest and size, and
`byte_count<=resource_limits.max_artifact_bytes`. The remaining metadata is exact, not a manifest-
chosen label:

| Successful operation | Exact common-result artifact metadata and equality |
| --- | --- |
| provider/model-runtime `model_step` | Exact ordered direct Artifact refs in `content_block_refs`; every role=`model_content`, every omissions_ref=null |
| managed-runner `run_status` | Exact ordered Artifact-producing normalized events; artifact_ref/media_type/omissions_ref equal that event and role=`runner_artifact` |
| tool `invoke_tool` | Exact ordered `ToolResultArtifactBindingV1[]` resolved by `result_ref`; each artifact_ref/role/media_type/omissions_ref equals that binding and satisfies the core ToolDefinition's `ToolArtifactOutputContractV1` role→allowed-media/omissions policy |
| codec `decode_projection` | Exact one; artifact_ref=`output.projection_artifact_ref`, role=`decoded_projection`, media_type equals the media declared by `input.target_projection_schema_ref`, omissions_ref=`output.omissions_ref` |
| codec `render_preview` | Exact one; artifact_ref=`output.preview_artifact_ref`, role=`render_preview`, media_type=`input.target_media_type`, omissions_ref=`output.omissions_ref` |
| codec `encode` | Exact one; artifact_ref=`output.encoded_artifact_ref`, role=`encoded_output`, media_type=`input.target_media_type`, omissions_ref=`output.omissions_ref` |
| storage `read` | Exact one; artifact_ref=`output.object_artifact_ref`, role=`storage_object`, media_type equals the durable Artifact, omissions_ref=null |

`ToolArtifactOutputContractV1` is the core-owned closed object
`{min_items:nonnegative-int<=256,max_items:nonnegative-int<=256,roles:{role:identifier,
allowed_media_types:sorted unique media-type[],omissions_policy:forbidden|optional|required}[]}` with
`min_items<=max_items`, unique roles and no empty media set. `ToolResultArtifactBindingV1` is exactly
`{artifact_ref,role,media_type,omissions_ref}`; it is sealed inside the typed `result_ref` and the
common `artifacts` array repeats it byte-for-byte while adding only the Artifact-equal digest/size.
An optional omissions ref, when present, resolves to an immutable omissions record for that exact
artifact and request purpose. A manifest may narrow the allowed role/media set but cannot rename a
role, change an omissions policy or weaken any equality. A config/binding unable to
satisfy an `O` row is rejected before dispatch. A manifest/refinement may narrow `V` or allowed roles
but cannot expand cardinality, turn an empty row into an artifact row or weaken exact-ref equality.

### 3.9 Exhaustive request artifact-input matrix

The request generator MUST evaluate all 52 port-qualified operations exactly once. Exactly eleven
operations use a non-empty-capable profile below and the other 41 use `E`; the row total is a schema
invariant, not commentary. `E` means `artifact_inputs` has `minItems=maxItems=0` and equals `[]`.
An operation refinement cannot change its profile.
Every other `ref` named in an operation `input` resolves only to the typed non-byte domain record
named there; it cannot resolve to `Artifact`/`ArtifactInputSelectorV1` or grant byte access. Thus an
`E` row cannot smuggle an artifact through a generically typed-looking ref.

| Port (operation count) | Non-empty-capable operations and exact profile | Operations requiring `E` |
| --- | --- | --- |
| provider (5) | `model_step:F-model` | `capabilities,catalog,status,cancel` |
| managed provider runner (7) | `run_start:F-runner` | `preflight,device_auth_start,device_auth_status,device_auth_cancel,run_status,run_cancel` |
| model runtime (4) | `model_step:F-model` | `capabilities,status,cancel` |
| tool (4) | `invoke_tool:T-tool` | `describe_tools,status,cancel` |
| artifact codec (5) | `probe:C-one`; `decode_projection:C-one-selected`; `render_preview:C-one-selected`; `encode:C-many` | `cancel` |
| lens definition (3) | — | `validate_definition,compose,apply_decision` |
| evaluator definition (3) | — | `describe_rubric,evaluate,abstain` |
| evaluator runtime (5) | — | `describe_rubric,evaluate,abstain,status,cancel` |
| storage (5) | `write_cas:S-one` | `capabilities,health,migrate_plan,read` |
| credential vault (6) | — | `capabilities,health,store,resolve_for_gateway,retire,erase` |
| export sink (5) | `prepare:X-export-prepare`; `transmit:X-export-transmit` | `capabilities,status,cancel` |
| **Total (52)** | **11 operations** | **41 operations** |

The profiles are core-owned and expand into the matching request operation arm as follows:

- `F-model`: `artifact_inputs` has 0–32 entries and is byte-for-byte equal, in order and length, to
  the `ArtifactInputBindingV1[]` sealed by `input.frozen_turn_ref`. Every role is `model_input`, each
  media type belongs to both the validated config's `supported_input_media_types` and the frozen
  model projection, and each selector equals the frozen projection selector. `F-runner` is identical
  except that it equals the array sealed by `input.frozen_run_projection_ref` and every role is
  `runner_input`. The frozen record, not an extension, determines the exact call cardinality.
- `T-tool`: `tool_id`+`tool_version` MUST resolve to exactly one ref in the config's
  `tool_definition_refs`. That core-owned `ToolDefinition` contains one closed
  `ToolArtifactInputContractV1`: either `{mode:none}` or
  `{mode:bounded,min_items:nonnegative-int<=32,max_items:nonnegative-int<=32,
  role:identifier,allowed_media_types:sorted unique media-type[],selector_policy:forbidden|optional|required}`
  with `min_items<=max_items`. The request length equals that interval, every entry has the literal
  role and a listed media type, and selector nullability exactly matches the policy. `arguments_ref`
  resolves to a closed non-artifact argument object and MUST contain no `Artifact` or selector ref at
  any depth; `artifact_inputs` is the sole byte-input authority. An extension manifest may only narrow
  a bound/media set already frozen in the ToolDefinition and cannot author or widen this contract.
- First-release core ToolDefinitions are fixed as: `public_fetch`, `browser_navigate`,
  `browser_observe`, `browser_interact` and `document_create_blank` use `{mode:none}`;
  `browser_upload` uses 1–16 `browser_upload` entries with selector forbidden and media in
  `{application/json,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,
  application/vnd.openxmlformats-officedocument.presentationml.presentation,
  application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,audio/mpeg,audio/wav,image/jpeg,
  image/png,image/webp,text/csv,text/markdown,text/plain,video/mp4}`;
  `multimodal_inspect` uses 1–16 `multimodal_input` entries with selector optional and media in
  `{application/pdf,audio/mpeg,audio/wav,image/jpeg,image/png,image/webp,video/mp4}`;
  `document_compose` uses 0–32 `document_source` entries with selector optional,
  `document_transform` and `document_extract` each use exactly one `document_source` entry with
  selector optional, and their media set is
  `{application/json,application/pdf,application/vnd.openxmlformats-officedocument.presentationml.presentation,
  application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,
  application/vnd.openxmlformats-officedocument.wordprocessingml.document,image/jpeg,image/png,
  image/webp,text/csv,text/markdown,text/plain}`. `pdf_render` uses exactly one `document_source`
  entry, selector optional, and media exactly `application/pdf`. Any other registered tool must have
  one explicit core-validated `ToolArtifactInputContractV1`; absence never defaults to 0–256.
- `C-one` has exactly one `codec_source` entry, selector null, and media in the codec config's
  `input_media_types`. `C-one-selected` is the same exact-one profile but selector is null or resolves
  to a selector kind in `selector_kinds`. `C-many` has 1–32 ordered, unique-by-`artifact_ref`
  `codec_source` entries, all selectors null and all media types in `input_media_types`. The codec
  `input` arms in §3.2 deliberately contain no `source_artifact_ref`, `source_refs` or `selector_ref`;
  `artifact_inputs` is their sole source authority.
- `S-one` has exactly one `storage_value` entry, selector null, and media in the storage config's
  `accepted_value_media_types`. The `write_cas` input deliberately has no `value_artifact_ref`; its
  sole value is `artifact_inputs[0].artifact_ref`.
- `X-export-prepare` has 1–256 ordered entries and is byte-for-byte equal to the
  `ArtifactInputBindingV1[]` sealed by `input.snapshot_ref`'s immutable `ExportSnapshotV1`. Every role
  is `export_payload`, every selector is null, every media type is in the export config's
  `supported_media_types`, and the order equals the snapshot content manifest. Successful prepare
  seals `PreparedDeliveryV1={snapshot_ref,target_ref,content_manifest_ref,artifact_input_bindings,
  aggregate_content_digest,expires_at}`. `X-export-transmit` repeats that prepared record's exact
  ordered artifact-input list and therefore the original snapshot bytes; its target_ref must also
  equal the prepared target. Both calls receive bytes only through T018's bounded digest/chunk/credit
  artifact stream. The extension service has no shared object-store mount, and a prepared ref alone
  never grants byte access or permits changed content after consent.

For every non-empty entry, the exact artifact exists and is readable under `purpose_ref` and grants;
its declared media equals the stored `Artifact.media_type`, and its byte size is no greater than
`resource_limits.max_artifact_bytes`. Resolved selected bytes across the request are no greater than
`resource_limits.max_artifact_input_bytes`; when selector is null, the entire artifact size counts.
Duplicate artifact refs, an extra/missing input, wrong role/media/selector, a conflicting ref hidden
in `input`/tool arguments, a frozen-list mismatch or an undeclared ToolDefinition profile fails before
dispatch. These checks do not change the 44 schema-artifact count or §3.8's independent result
operation×terminal/cardinality matrix.

## 4. Refinement and compatibility rules

An extension manifest may provide only three refinement schema refs: `extension_config_schema_ref`,
`extension_input_schema_refs` keyed by an existing operation, and `extension_output_schema_refs`
keyed by an existing operation. Each ref is local, digest-pinned, closed and free of remote/dynamic
`$ref`, executable validation, coercion or default insertion. Core validation runs the applicable
base schema first and then the refinement.

A refinement MUST NOT remove or rename a required field; add an operation, terminal state, core or
port error code; loosen a size/count/pattern/enum bound; change authority, effect, idempotency,
cancellation, retry or artifact meaning; accept an unknown field; inspect a raw credential; or make
an optional/nullable value authoritative. `extension_error_code` is allowed only from the manifest's
digest-frozen, closed per-operation enum and only underneath core `port_specific_failure`; it cannot
be interpreted as success or automatic retry.

Port compatibility is exact-major and explicit-minor. A new required operation, field or meaning
requires a new port contract version and requalification. Additive optional evidence can be
negotiated only when both core and manifest declare the version; silence never means support. These
rules apply equally to built-ins and third-party extensions.

## 5. Acceptance boundary

T087 must generate the 44 schema artifacts from these core-owned definitions, enumerate all 208
operation×candidate-terminal pairs exactly once, assert 127 accepted and 81 rejected with no missing/
duplicate pair, and
validate every operation's positive and required/missing/unknown/over-bound/wrong-type/wrong-port/
error/terminal/refinement case. It must assert `artifacts=[]` for every allowed non-success terminal,
including cancelled codec, and test each successful empty/`V`/`O` row, exact output-ref equality,
config count/byte limits, every literal/core ToolDefinition role-media-omissions relation and
codec target-media/output-omissions equality. It must generate every terminal×effect-family branch
from §2.3, reject every unlisted tuple and prove the error object has no second effect truth; in
particular succeeded external unknown/unconfirmed and failed unknown/committed/retryable conflicts
are invalid. It must also reject `invoke_tool` success when its closed output contains
`effect_receipt_ref` (even if equal to the common value) or any receipt alias. It must independently enumerate all
52 request operations, assert the 11 non-empty-capable/41 `E` split, and reject every extra, missing,
over-bound, wrong-role/media/selector, hidden/conflicting ref, frozen-list mismatch and missing/widened
ToolDefinition contract. Export prepare/transmit must repeat their exact snapshot/prepared artifact
lists and transfer bytes through bounded broker streaming; ref-only/shared-store/mount or changed-
content transmission fails. It round-trips all eleven configs through the exact five-field
`BindingSlotKeyV1`, recomputes its digest and rejects four-field keys, sibling/nested port-version
mismatch, wrong digest and binding-revision mismatch. It compares generated required/type/
enum/bound sets to this expansion source and
installs the author SDK out of tree to prove its bundled schema hashes and manifest validators match.
Before schema generation, a document-structure guard must enumerate exactly eleven normative
`*-port-v1` rows, require each row to occur inside a contiguous pipe table opened by an immediately
adjacent `Port` header/separator pair, and report zero isolated pipe rows; prose between rows fails.
R16/A13 additionally exercise a qualified out-of-tree tool through the real broker. T083 later
repeats the distribution proof on both clean hosts. This document is a design contract, not evidence
that any schema, package, service or test currently exists or passes.
