# Specification quality checklist

2026-09-08 · Agent-reviewed after the user's explicit web-framework correction. ADR-014 independent
reviews rejected revisions 1–6; revision-7 formatting-only remediation passed a fresh independent
review and T086 is closed for design.
This checklist checks requirement quality, not completed software or actual user acceptance.

- [x] Product identity and seven complete user journeys are explicit; no onboarding-only scope.
- [x] Browser UI, self-hosted web deployment and framework-owned workers are explicit; no native desktop wrapper, DMG, embedded WebView or product launcher is required.
- [x] Instance deployment and first-user browser onboarding are separate, and the official baseline retains a non-developer deployment path.
- [x] Requirements distinguish user corrections, paper evidence and delegated recommendations.
- [x] Claude API-only supersedes old Claude subscription language without removing Codex subscription.
- [x] Tests/scenarios cover positive, negative, missing-evidence, cancellation and recovery behavior.
- [x] Own alternative artifacts differ from comments, onboarding, synthetic data and optional explanations.
- [x] Partial evidence/change/impact scope and downstream prior-queue reevaluation remain distinct.
- [x] Lenses apply in initial generation, critic inquiry and eligible post-alternative exploration.
- [x] Information isolation and empirical judgment-error independence are separately required.
- [x] Product-only plateau has fixed floor/delta/patience and does not authorize promotion or development stop.
- [x] Independent GUI, real graphs, original multimodal artifacts, models and framework tools have acceptance tests.
- [x] Records begin at the first framework-observable deployment/setup event; privacy, optional export and no automatic transmission are explicit.
- [x] All 34 FR and 10 SC map to implementation/test tasks; no unfilled requirement placeholders.
- [x] Scope/risks and human/paid/external readiness are recorded without assuming unavailable evidence.
- [x] Ordinary review fixes are delegated; core changes/new authority are not silently permitted.
- [x] The shared worker envelope is transport only; every extension kind binds a closed core-owned semantic port/trust/staging tuple and wrong tuples fail closed.
- [x] Verified installation, context-keyed qualification, port/scope/purpose/slot/selector-keyed binding histories and target-binding-keyed rollback-retention heads are durable and atomically reconciled; different slots coexist, exact same-slot candidates compete by CAS, and owner release removes rollback eligibility without deleting history.
- [x] Executable extensions use externally operator-staged digest-pinned OCI services and receipts; bounded browser import is code-free only, with no product Docker/container authority.
- [x] Stage/replace/current-uninstall/superseded-retirement have separate closed request/result arms; common `preconditions={}`; strict-ancestor retirement follows an explicit A→B→release-retained-rollback→retire-A path, preserves the descendant current head and advances only a target retirement head after dependency recheck; exact request equality and one-way causality forbid future refs.
- [x] All eleven semantic ports have mechanically complete core-owned schemas, one exact five-field `BindingSlotKeyV1`+digest across config/binding/commands/events, and a 52-operation×terminal result matrix; every allowed non-success result, including cancelled codec, has `artifacts=[]`, while success empty/variable/exact-one cardinality and ref/role/byte limits are closed; the author SDK cannot author a core port.
- [x] The separate request matrix evaluates all 52 operations exactly once: eleven use closed frozen/tool/codec/storage/export artifact-input profiles and 41 require `artifact_inputs=[]`; export prepare/transmit receive the exact snapshot/prepared 1–256 `export_payload` bytes through bounded broker streaming, while ref-only/shared-store paths, codec/storage/tool competing refs and extra/missing/wrong-role/media/selector/frozen/export-list inputs fail before dispatch.
- [x] Result artifact role/media/omissions/ref rules are closed per operation, including codec target-media/output-omissions equality and core-owned tool output contracts; `result.effect` is the sole effect/outcome truth, embedded errors cannot disagree, and every unlisted terminal/effect tuple or unsafe unknown/retry combination fails.
- [x] Tool `invoke_tool` success output is exactly `{tool_call_ref,result_ref}`; output-level `effect_receipt_ref` and aliases are forbidden even when equal to the common receipt, while ToolResult artifact bindings remain sealed under `result_ref`.
- [x] All eleven normative `*-port-v1` rows remain inside contiguous Markdown tables with valid header/separator pairs; the structure guard reports zero isolated pipe rows and rejects prose inserted between rows.
- [x] `Settings > Extensions`, a separately installable author SDK and separately installable HTTP/OpenAPI client are explicit product/framework contracts.
- [x] Recursive core dependency enforcement starts at domain/services/runtime/operations/extensions, explicitly includes `app/extensions/**`, and rejects direct or indirect API/static/server and FastAPI/Starlette/Jinja presentation imports.
- [x] T025 owns common ServiceClient authority and a frozen first-party router-composition seam; T087 owns one fixed extension route contribution without server edits and actual portable-HTTPS parity; HTTP loopback tests pre-parser bearer-route denial with no real bearer.
- [x] T018's unchanged checkbox has a non-circular in-task split: T018-foundation precedes semantic integration, T018-final consumes downstream integration evidence, and T083 alone retains two-clean-host repetition.
- [x] Open-source target status is separated from current legal status: no repository license exists and T084 requires explicit copyright-owner approval.
- [x] A fresh independent reviewer found no P1/P2 contradiction in the amended ADR-014 revision-7 artifacts and closed T086; `evidence/adr014-independent-review-r7.md` records the frozen-manifest verdict.

Result: the revision-7 ADR-014 requirements are migrated into the plan/contracts/tasks and the
design gate is closed. The first T086 DESIGN CLEAR, rejected ADR-014 revisions 1–6 and native
packaging plan are historical; revision 7 is the accepted current design. No implementation,
test, effect, legal open-source status or
release qualification is implied.
