# Provider semantic read observations and local cancel — scoped amendment DRAFT

2026-09-20. Advisory response to F1 of [independent preflight](post46-semantic-design-preflight.md). Controller accepts the correction direction in principle; these exact words are **not promoted canonical rules**. No product/canonical/test edit, test execution, network, native authority or activation is authorized here.

## 1. Existing rule, gap and proposed applicability

Canonical `specs/001-autonomous-release/contracts/extension-ports.md` §2.2 fixes idempotency_key as SHA256 of canonical `{port_contract_version,installation_digest,binding_revision_ref,purpose_ref,operation,grant_refs,artifact_inputs,input,extension_input}`. Request UUID, deadline and observation time are excluded. §3.7 currently says every request is idempotent by that key and allows read retries only after eligible failure. `app/extensions/port_schema_generator.py` implements those exact hash bytes. The prior semantic appendix extended a unique semantic-key command index to all five operations.

Consequently a successful status of running could never be refreshed for an unchanged target: same-ID replay stays running and a fresh ID conflicts. Fresh capabilities/catalog have the same gap. Repeated cancel has a related but different problem: its first accepted acknowledgement must replay, yet a new cancellation request after target termination should observe already_terminal. Treating cancel as an arbitrary fresh read would fail to constrain the cancellation action itself.

**Recommended narrow canonical ruling:** add an explicit §3.7 exception only for `provider-port-v1` bound to code-owned `claude-api-text-semantic-v1`, enumerating `capabilities`, `catalog`, `status` as fresh read observations and `cancel` as the local monotonic cancellation protocol below. The trusted semantic composition selects this profile from exact validated config/installation identity; no extension_input flag, user-selected policy or arbitrary manifest claim enables the exception. Do not apply it to any other provider profile/port, runner cancellation, tools, storage, exports, credential custody, private B or Task46 commands. Wider harmonization requires another explicit decision.

Promotion must record this scoped exception in canonical extension-ports§3.7 and a cross-reference at provider§3.1; §2.2's hash definition and all exported port-v1 schema bytes remain unchanged. This document is the proposed text/decision, not that edit. Dispatch is blocked until the controller explicitly approves/promotes the ruling and reconciles accepted46 scope. No new external authority is needed merely to decide these core semantics.

## 2. Normative proposed rules: identity and fresh reads

1. Every request retains its globally immutable UUID, original canonical body and unchanged semantic key. Persist the operation anchor by that UUID and pin its config_ref. Before new admission, compare full canonical request bytes (not hash alone) and exact config_ref against any existing anchor.
2. Same UUID + identical request bytes/config is replay of that one observation/action. Return its exact immutable terminal, timestamps and references after authenticated owner/purpose read authorization; perform no new worker, gateway, upstream, native probe, permit, budget reservation or deadline extension. If still in-flight, return only retained/current command disposition, not a second execution or newly sealed observation. After owner loss without a terminal, disposition is unavailable/unknown; fresh status may observe it. Replay never fabricates a succeeded result.
3. Same UUID with changed bytes/config is failed invalid_request/validation/never, empty output/artifacts, zero execution; preserve the original anchor/result. Canonical hash collisions or changed bodies retaining an ID/key are not accepted.
4. A **fresh UUID** for capabilities/catalog/status may share the existing semantic key and creates a separate immutable observation. No semantic-key unique index is created for these three operations. It is neither replay of the prior observation nor permission to retry an external model effect. Old observation bytes stay unchanged.
5. Fresh capabilities reports current admitted implementation capabilities without HTTP. Fresh catalog performs the bounded actual GET traversal under the new request's own deadline, current connection/handle/current authorization and same profile caps; no Messages or budget-free model permit. Fresh status samples the actual same-purpose target state under its owner's operation mutex or retained ledger state after owner loss. No made-up new purpose/grant/binding/catalog_epoch is needed just to refresh.
6. Fresh requests require the normal current admission checks: authenticated actor, exact purpose/grants/config/installation, current qualified binding/head/connection pins and unexpired deadline/profile evidence applicable to that operation. Status/cancel additionally require an exact authorized target operation_ref in the same vault/purpose and provider/binding context; they cannot inspect/control another caller's operation. A revoked/expired admission may refuse a fresh request while historical owner-authorized replay remains possible. This amendment creates no revocation bypass or native C authority.
7. Status output observed_at is the core observation instant for this UUID. Its terminal_result_ref is the exact already sealed terminal when known, otherwise null. pending/running require a live current-owner state; after owner loss an unresolved committed operation is unknown, never inferred unsent from absent terminal. Fresh status can therefore observe running→terminal or running→restart-unknown while old status replays running.
8. Read operation result pairs/effect classes/artifact restrictions remain canonical: succeeded/failed only, effect_class=read, no artifacts; returned evidence refs are sealed. Failed observations are immutable too. No automatic retry; a new explicitly admitted UUID can make a fresh read even after failed/expired observation under this scoped exception. The initial request's deadline is never reset.

## 3. Normative proposed rules: cancel is not a generic refreshable effect

Cancel remains an acknowledgement with succeeded/failed only, effect_class=none and no artifacts. It never proves remote rollback or a model's terminal result. Same UUID/bytes/config replays exactly under §2, including its original accepted timestamp. Fresh UUID is a fresh acknowledgement of the target's **current local cancellation disposition**, subject to fresh authorization; it does not independently authorize another cancellation effect.

| Current authoritative target state under target mutex | Fresh cancel outcome / action |
| --- | --- |
| An accepted, sealed model terminal exists | succeeded/already_terminal; no latch change, forwarding, new model result or send |
| Live same-owner cancellable target, no prior cancel intent | Durably insert the one intent and this cancel operation; set one-way Event; accepted; at most one best-effort gateway control |
| Live same-owner target, prior intent and Event already set | accepted at this fresh observation time; no second forwarding/action and no reason replacement |
| Prior intent but no live owner or Event never became set | not_cancellable; retain uncertainty, no reconstructed Event, replay or resend |
| Valid target exists but local phase is not cancellable | not_cancellable; no action |
| Unknown/mismatched/unauthorized target ref | failed canonical invalid_request or permission_denied as applicable; never not_cancellable as an existence oracle |

All rows sample after the same core target-operation mutex is acquired within the requesting cancel's remaining absolute deadline; lock timeout refuses without a new intent/action. Terminal observation wins if already accepted before that acquisition. If the cancel obtains the mutex first, accepted is an acknowledgement of the local latch, and the model may still finish successfully afterward. A later fresh cancel then returns already_terminal. A repeated reason (or different reason_class) cannot undo/escalate the first cancellation action. Never manufacture a new model request or model budget/send permit.

The target-scoped durable fence is an existing-kind validation_report with literal `provider-semantic-cancel-intent-v1` content `{schema_version,target_operation_ref,first_cancel_operation_ref,first_request_sha256,reason_class,core_boot_id}`. Types are the literal appendix's R/R/H/canonical-cancel-reason/U. ID uses its §2 UUID5 function with owner_uuid=target request UUID and ordinal0. parent_refs are sorted unique target_operation_ref and first_cancel_operation_ref. First cancel operation references only its earlier target, so the graph stays acyclic. Insert operation+intent in one domain_records transaction; exact unique identity prevents concurrent second intents across processes. No separate cancellation registry/table.

The current single owner of the live target serializes intent insertion→Event.set→optional one-way gateway control enqueue→acknowledgement under its operation mutex, without holding the mutex across network I/O. Gateway control may be lost; at-most-once publication is a deliberate best-effort choice, not a remote-cancellation guarantee. A failed enqueue still acknowledges a set local Event; local transport cancellation/closure governs safety. Do not retry gateway control after uncertain delivery/restart. A crash after intent insert but before latch/acknowledgement leaves the fence intact and target uncertain: fresh cancel reports not_cancellable if no authoritative terminal, same-ID replay does not invent an acknowledgement. Existing reconciliation/late-result rules decide the original model outcome.

The original model result remains governed by its own observations: cancellation before possible write can prove none; after possible write it retains unknown/unconfirmed effect unless a genuine complete terminal is accepted. Cancel can never transform unknown billing into zero, release a provisional reservation, or permit resend. Unknown remote outcome stays no-resend even if later fresh status/cancel succeeds.

## 4. External-effect identity remains unchanged

`model_step` keeps the immutable semantic-key index and actual ledger send-intent/permit fencing. Same-ID exact replay sends zero; different UUID under the same model semantic key conflicts in this profile, never dispatches twice. Changed model semantic input requires a new key and all fresh authorization; it is not a retry of an unknown prior effect. All external-effect rules outside this profile stay untouched.

The implementation's index switch is closed and code-owned:

```text
model_step                 -> request UUID anchor + unique semantic-key index
capabilities/catalog/status-> request UUID anchor only; fresh UUID is a new read
cancel                     -> request UUID anchor + one intent per exact target
anything else              -> reject under this profile, never default to read
```

The three amended operations still recompute/check semantic_key using existing validator bytes. Nothing adds request_id to the hash, salts it, changes the port version, broadens effect enums or mutates old histories. Historical global-index artifacts from this draft were never implemented; there is no production migration claim. Accepted private B/install histories are not these semantic records.

## 5. Finite implementation/proof scope after approval

Owned prospective code remains the two semantic drafts' existing new records/context/contracts, worker/runtime service and tests. No additional product module is required by F1; canonical promotion is a controller-owned prerequisite, not covert implementation scope.

- `test_fresh_status_observes_terminal_but_old_request_replays`: real controlled model remains running; query Q1; complete/accept model; fresh Q2 with same semantic key observes terminal; exact Q1 returns original running/timestamp, zero fresh I/O.
- `test_fresh_status_after_restart_is_unknown_without_resend`: Q1 running; crash after model send intent; restart; fresh Q2 unknown/null unless genuine terminal retained; Q1 remains exact; model send counter stays1.
- `test_read_ids_refresh_without_changing_semantic_hash`: capabilities/catalog IDs Q1/Q2 share canonical hash, retain different operation anchors and actual catalog page observations; Q1 replay cannot contact the server; changed Q1 body/config conflicts.
- `test_cancel_refresh_is_target_deduplicated`: first cancel accepted; another fresh cancel with same/different reason while live accepted and at most one forward; target finalizes; fresh cancel already_terminal; original acknowledgement exact.
- `test_cancel_intent_crash_has_no_second_action`: stop after durable intent before Event.set; restart; fresh cancel not_cancellable, no latch recovery/gateway forward; original model unknown/no resend. Check race where terminal wins before mutex and where latch wins first.
- `test_model_semantic_key_fence_unchanged`: same request exact replay, different ID same key, lost acknowledgement and unknown outcome all cause no second model permit/send; changed bytes under same UUID conflicts.
- `test_observation_exception_is_profile_scoped`: wrong profile/port or caller-supplied extension_input cannot select fresh-read behavior; old canonical schema/hash vectors remain byte-identical.

Tests are required future evidence, not executed here. Fixtures use actual record transactions, worker/control state, guarded local upstream and ledger, not passed maps.

## 6. Rationale, costs and approval status

Rejected: adding observation time/request UUID to the canonical semantic hash (changes established byte meaning); rotating purpose/binding to defeat dedup (false authority changes); globally exempting all reads/cancels (unreviewed other-port semantics); keeping permanent first-observation replay (unusable status/refresh); treating each cancel as a new remote effect (unnecessary repeated effect/uncertainty).

Chosen: the narrow provider profile can obtain useful fresh observations while exact request replay and external-effect fencing remain strong. Cost: more immutable read records, explicit client UUID discipline and a profile-scoped canonical exception requiring future harmonization if reused elsewhere. Cancel is deliberately local/best-effort and target-monotonic, so a lost first forwarding is not automatically retried; this preserves uncertainty rather than claiming cancellation completion.

Chronology: original draft/appendix froze all-operation semantic-key uniqueness; independent preflight found F1 and declared NOT READY; controller accepted this correction direction; this amendment and revised appendix now request bounded exact-text re-review. **Canonical promotion remains outstanding.** F2/F3 are code-owned conditional consumer corrections in the companion drafts; no change here grants real C/binding/current connection, release, credential or upstream authority.
