# Implementation matrix — DRAFT (2026-09-23)

Status: **draft as of 2026-09-23. This is not the final T075 deliverable.**
T075 (`specs/001-autonomous-release/tasks.md`, open) closes only after the final design edits,
with refreshed source hashes, the supersession map and the stable-weight progress-numerator,
uncertainty and ETA-support audit, and its final refresh follows T083. The final deliverable is
`specs/001-autonomous-release/evidence/implementation.md`, which does not exist yet. This draft
replaces nothing and closes nothing. It claims no checkbox, test result or live result beyond what
it cites.

## Method

- **Requirement IDs.** FR-001…FR-034 and SC-001…SC-010 come from
  `specs/001-autonomous-release/spec.md`. UX-AC01…UX-AC11 come from
  `specs/001-autonomous-release/contracts/experience.md`. That is 55 rows.
- **Claiming tasks.** These come from the task entries in `specs/001-autonomous-release/tasks.md`
  at the committed state of branch `codex/ui-structure`. Range and list forms are expanded, so
  `FR-010–012/029` counts for FR-010, FR-011, FR-012 and FR-029. `[x]` means closed and `[ ]`
  means open. A task marked **†** is not cited by ID in tasks.md. It comes from the T001
  requirement→task assignment table in `design-review.md` (V0 history: "Mapping coverage is NOT
  implementation coverage"). † tasks still count toward status, so a requirement is not shown as
  finished while an assigned task is open.
- **Test files.** These are the repository-relative files under `app/tests`, `deploy/tests` or
  `evals` that the claiming tasks or their evidence files name, or that contain the ID itself.
  "named, absent" marks a file that tasks.md names but that does not exist in the checkout.
- **Evidence files.** These are file names under `specs/001-autonomous-release/evidence/` that
  the claiming tasks cite, that name the task ID, or that contain the requirement ID. "absent"
  marks a named file that does not exist yet.
- **Status** is one of four values:
  - `verified-local`: every claiming task is closed, and a named test file and evidence file exist
    that record passing runs.
  - `partial`: at least one claiming task is open, and the remaining work is local engineering.
  - `missing`: no test and no evidence file was found.
  - `gated`: closure needs live providers, a human or copyright-owner decision, fresh hosts or
    real-user data. The last column names which one, together with any open local work.
- **Fresh local run (2026-09-23, this checkout, offline).** The test files behind the four
  `verified-local` rows were run with
  `.venv/bin/python -m pytest -q app/tests/test_domain_contracts.py app/tests/test_domain_permissions.py app/tests/test_alternatives.py app/tests/test_growth_firewall.py app/tests/test_change_compiler.py app/tests/test_knowledge.py app/tests/test_memory_compilation.py app/tests/test_alternative_drafts_api.py`.
  Result: **179 passed, 1 warning**. The run used the working tree, which carries uncommitted
  changes from concurrent work outside this file. While this draft was being written, uncommitted
  files appeared: `app/api/versions.py`, `app/services/versions.py`, `app/static/versions.mjs`,
  `app/static/versions.html`, `app/static/versions-page.mjs`, `app/tests/test_versions_api.py`
  and `app/tests/versions.test.mjs`, along with edits to several `app/api/*` and `app/tests/*`
  files. They look like T066 work in progress. **This matrix reflects the committed tasks.md and
  evidence only and gives that work no credit.** No other suite was run for this draft. Every other pass count below comes from the cited
  evidence file and is historical until rerun.

## Matrix

| Req | Requirement (paraphrase) | Claiming tasks | Test files | Evidence files | Status | Gate / open reason |
| --- | --- | --- | --- | --- | --- | --- |
| FR-001 | Self-hosted OSS web framework; no-terminal deploy; browser UI is the product | T086[x], T018[ ], T087[ ], T025[ ], T084[ ], T081[ ]†, T083[ ]† | deploy/tests/test_worker_boundary.py, deploy/tests/test_compose_topology.py, app/tests/test_router_composition.py, app/tests/start.test.mjs, app/tests/browser-owner-lifecycle-t025.test.mjs | adr014-independent-review-r7.md, web-framework-design-review.md, static-topology-t018c.md, first-screen-setup-login-t025.md, password-change-t025-2026-09-23.md | gated | Fresh hosts (T083) and copyright-owner license approval (T084). Local work also open: T018, T025, T087, T081 |
| FR-002 | Take description, multiple materials and live voice; separate original/edit/read scope/interpretation | T023[ ], T026[ ], T080[ ], T024[ ]† | app/tests/test_works_api.py, app/tests/work.test.mjs, app/tests/test_speech_api.py, app/tests/test_speech_sessions.py, app/tests/browser-speech-input.test.mjs; named, absent: app/tests/test_speech_segments.py, app/tests/browser-first-use-release.test.mjs | works-routes-intake-t023.md, intake-page-t023.md, speech-qualification-t024.md; us1.md absent | gated | Live providers (T026 understanding checks). Also open: T023 sources/files/mic/understanding, T024 PCM session migration, T080 |
| FR-003 | Confirm goal, completion, authority, risk, unknowns and single/deterministic fit before design | T030[ ], T026[ ]† | app/tests/test_work_model_confirmation.py, app/tests/test_design_generation.py | design-generation-graph-t030-status.md, graph-compiler-reaudit-t027t030.md | gated | Live providers (T026). T030 open: no provider bound to the generation path |
| FR-004 | Versioned single/mixed micro-lenses must actually shape structure decisions | T029[x], T030[ ], T036[ ], T076[ ]†, T077[ ]† | app/tests/test_lens_registry.py, app/tests/test_critic_lens_pipeline.py, app/tests/test_design_generation.py, app/tests/test_environments.py | lens-registry.md, critic-lens-pipeline-t036.md, design-review-t036a.md, environments-t036b.md | gated | Live comparisons and release heldout (T076/T077). T030 and T036 open |
| FR-005 | Compare candidates as graphs with role/artifact/handoff/memory/tool/permission/cost differences | T028[x], T030[ ], T037[ ], T038[ ]† | app/tests/test_graph_contract.py; named, absent: app/tests/browser-design.test.mjs | graph-compiler-reaudit-t027t030.md; us2.md absent | gated | Live generation (T038). T037 graph comparison UI not present (`app/static/graph.mjs` absent) |
| FR-006 | Critic judges raw evidence independently of generator scores; same-model independence verified empirically | T035[ ], T036[ ], T031[x]†, T032[x]†, T033[ ]†, T034[ ]†, T076[ ]†, T077[ ]† | app/tests/test_critic_lens_pipeline.py, app/tests/test_critic_lineage.py, app/tests/test_provider_lifecycle.py, app/tests/test_design_criticism_live.py; named, absent: evals/deeptwin/verifiers/critic.py, evals/deeptwin/tests/test_critic_verifier.py | critic-lens-pipeline-t036.md, critic-lineage-t032.md, provider-lifecycle-t031.md, design-criticism-live.md (offline scripted, see below); live-qualification.md absent | gated | Live critic trials (T035/T077). Q01 harness (T033) and verifier (T034) absent |
| FR-007 | Select three structurally different gate-passing candidates; show shortfall and supplement limits | T028[x], T036[ ], T038[ ]† | app/tests/test_graph_contract.py, app/tests/test_design_review.py; named, absent: app/tests/test_design_selection.py | design-review-t036a.md, graph-compiler-reaudit-t027t030.md | gated | Live generation (T038). T036 ranking/supplementation open |
| FR-008 | Link exact select/merge/edit/approval versions to the executed configuration | T036[ ], T037[ ], T038[ ]† | app/tests/test_owner_decisions.py, app/tests/test_design_review.py, app/tests/test_environments.py, app/tests/test_environment_records.py | owner-decisions-design-approval.md, design-review-t036a.md, environment-record-t048.md | gated | Live generation (T038). T036 and T037 open |
| FR-009 | Workspace, conversation and graph share work, artifacts, alternatives, approvals and history | T016[x], T023[ ], T037[ ], T054[x]†, T078[ ]† | app/tests/test_server_api_v1.py, app/tests/test_works_api.py, app/tests/test_conversation.py, app/tests/browser-alternatives.test.mjs | server-api-v1.md, works-routes-intake-t023.md, us4.md | partial | T023 conversation, T037 graph view and T078 UI QA open |
| FR-010 | Full LLM journey on Claude API alone and on the managed Codex subscription runner | T020[x], T022[x], T090[ ], T088[ ], T026[ ]†, T049[ ]†, T077[ ]† | app/tests/test_claude_api.py, app/tests/test_model_catalog.py, app/tests/test_model_selection.py, app/tests/test_provider_transport.py; named, absent: app/tests/test_codex_subscription_runner.py | claude-api.md, model-catalog-selection.md, credential-vault-t090.md, claude-provider-protocol-check-2026-09-19.md (docs-only) | gated | Live providers and a Codex subscription account (T026/T049/T077). Also open: T088 runner, T090 transport |
| FR-011 | Codex API is a separate explicit choice with no auto-switch; Claude API billing/limits shown | T014[x], T020[x], T021[x], T022[x], T090[ ], T088[ ] | app/tests/test_codex_api_mode.py, app/tests/test_claude_api.py, app/tests/test_runtime_budgets.py | codex-api-mode.md, claude-api.md, runtime-budgets.md | partial | T090 credentialed transport and T088 runner open |
| FR-012 | Manage available models, per-agent settings, actual executed model and change history | T020[x], T022[x], T090[ ], T088[ ], T023[ ]†, T042[ ]† | app/tests/test_model_catalog.py, app/tests/test_model_selection.py, app/tests/test_model_payloads.py | model-catalog-selection.md, gateway-frozen-turns-t042.md | partial | T023 model GUI, T042 frozen turns, T088 and T090 open |
| FR-013 | Execution supports sequence/parallel/branch/join/finite loop/approval/stop; events match UI | T014[x], T028[x], T040[x], T090[ ], T080[ ], T012[x]†, T039[x]†, T041[x]†, T048[ ]† | app/tests/test_graph_execution.py, app/tests/test_scheduler_attempt_dispatch.py, app/tests/test_langgraph_checkpoints.py, app/tests/test_runtime_ledger.py, app/tests/runtime.test.mjs | scheduler-t040-slice1.md, join-modes-t041.md, scheduling-retry-t039.md, checkpoint-attempt-binding-t040.md, run-panel-dom-t048.md | partial | T048 and T049 browser cases, T080 performance and T090 open. Routers, joins and gates inside loops are still refused (join-modes-t041.md) |
| FR-014 | Agents use framework-controlled browser/file tools with permission, effect, failure and recovery records | T018[ ], T090[ ], T047[x], T043[ ]†, T044[x]† | app/tests/test_tool_boundary.py, app/tests/test_egress_broker.py, app/tests/test_document_tools.py, deploy/tests/test_worker_boundary.py | tool-boundary-t047.md, egress-broker-t043.md, document-tools-pdf-png-t044.md, linux-root-canary-t018-2026-09-23.md | partial | T043 sandboxed Chromium, T018 runtime isolation and T090 open |
| FR-015 | Inspect role artifacts, partial locations, attempts, IO versions, handoffs and lineage in native format | T045[ ], T053[x], T046[x]† | app/tests/test_artifacts_service.py, app/tests/test_run_artifacts_api.py, app/tests/artifacts.test.mjs, app/tests/test_handoffs.py, app/tests/test_run_trace.py | run-artifacts-t045.md, artifacts-service-t045.md, handoffs-t046.md, run-trace-attempt-layer-t048.md | partial | T045: PDF/DOCX page previews through the codec worker and a vault-wide artifact index are open |
| FR-016 | Accept whole/partial own artifacts as alternatives; no required explanation or instructions | T051[x], T053[x], T050[x]†, T052[x]† | app/tests/test_alternatives.py, app/tests/test_alternative_drafts_api.py, app/tests/alternatives.test.mjs, app/tests/alternative-file.test.mjs, app/tests/browser-alternatives.test.mjs | own-alternatives-t050.md, own-version-editor-t052-2026-09-23.md, us4.md | verified-local | Synthetic test-actor evidence only. The own-alternatives-t050.md header still says "T050/T051 remain open" (see below) |
| FR-017 | Seal originals; keep alternatives/diagnosis/experiments separate and out of operational retrieval | T006[x], T010[x], T051[x], T008[x]†, T059[x]† | app/tests/test_domain_contracts.py, app/tests/test_domain_storage.py, app/tests/test_domain_permissions.py, app/tests/test_alternatives.py, app/tests/test_growth_firewall.py | domain-foundation.md, domain-storage.md, domain-permissions.md, domain-permissions-persistent.md, growth-firewall-t059.md | verified-local | None locally. Fresh 2026-09-23 run of the named files included |
| FR-018 | Separate observed differences from system/expert/one-off/error hypotheses; no unsupported single cause | T055[x], T060[ ]† | app/tests/test_diagnosis.py, app/tests/test_difference_observer.py, app/tests/test_run_trace.py, app/tests/browser-inquiry.test.mjs | format-differences-t055.md, run-trace-t055.md, inquiry-observation-t060-2026-09-23.md | partial | T060: no hypothesis generator is connected, so hypotheses show `not_generated`. Page/image/time regions wait on the codec worker |
| FR-019 | Lens inquiry updates judgment hypotheses through sourced questions and new evidence; no sensitive profiles | T029[x], T056[x], T060[ ]† | app/tests/test_inquiry.py, app/tests/test_lens_registry.py, app/tests/test_growth_firewall.py | spli-routing-hexp-t056.md, inquiry-t056.md, lens-registry.md | partial | T060 UI: the inquiry shows `not_opened` in the browser case |
| FR-020 | Philosophy interpretation is audit-only, never a direct basis or input for interventions | T010[x], T057[x], T059[x]† | app/tests/test_domain_permissions.py, app/tests/test_change_compiler.py, app/tests/test_growth_firewall.py | domain-permissions.md, change-compiler-admissions-t057.md, growth-firewall-t059.md | verified-local | None locally. Fresh 2026-09-23 run of the named files included |
| FR-021 | Distinguish restore/learn/protect; typed changes with per-field provenance checks | T057[x], T058[x] | app/tests/test_change_compiler.py, app/tests/test_knowledge.py, app/tests/test_memory_compilation.py | change-compiler-admissions-t057.md, knowledge-registry-t058.md | verified-local | None locally. Fresh 2026-09-23 run of the named files included |
| FR-022 | Re-evaluate downstream artifacts, roles and work affected by a partial alternative | T051[x], T061[x], T067[ ]† | app/tests/test_paired_execution.py, app/tests/test_comparisons.py, app/tests/test_alternatives.py; named, absent: app/tests/browser-growth.test.mjs | paired-execution-t061.md, us6-batch-audit.md; us6.md absent | partial | T067 end-to-end cases open |
| FR-023 | Rerun baseline/candidate on related prior queues; keep every round's gains, regressions and invalid runs | T061[x], T067[ ]† | app/tests/test_paired_execution.py, app/tests/test_comparisons.py | paired-execution-t061.md, comparisons-t061.md | partial | T067 open. Round persistence is missing (T066 note) |
| FR-024 | Product-only early stop after ≥3 non-improving rounds past adequate quality; record reasons | T014[x], T063[x], T062[x]†, T067[ ]† | app/tests/test_growth_loop.py, app/tests/test_growth_store.py | growth-loop-t062-t063.md | partial | T067 open. The evidence header still says T062/T063 remain open |
| FR-025 | Separate tuning, held-out and post-deployment data; check leakage, scope and regression | T061[x], T064[x], T067[ ]† | app/tests/test_validation.py, app/tests/test_comparisons.py | validation-evaluator-binding-t064.md, validation-t064.md | partial | T067 open |
| FR-026 | Human approval of the exact candidate; versioned activation, limited/retired states and rollback | T065[x], T066[ ]†, T067[ ]† | app/tests/test_promotion.py, app/tests/test_promotion_approvals.py, app/tests/test_run_approvals.py | promotion-approvals-t065.md, promotion-t065.md | partial | T066 blocked: frozen candidate bundles and validation reports have no store resume path |
| FR-027 | Log from the first observable control event on; never backfill pre-observation install events | T006[x], T016[x], T025[ ], T068[x], T012[x]† | app/tests/test_event_coverage.py, app/tests/test_domain_events.py, app/tests/test_public_events.py | event-coverage-t068.md, domain-foundation.md, server-api-v1.md | partial | T025 open (deployment-control recovery port) |
| FR-028 | Selective export previewing redaction, exclusions and limits; never auto-sent to the creator | T071[x], T073[ ]†, T074[ ]† | app/tests/test_export.py, app/tests/test_work_exports_api.py, app/tests/work-export.test.mjs, app/tests/records.test.mjs; named, absent: app/tests/browser-records.test.mjs | export-t071.md, work-export-t073-2026-09-23.md, records-gui-logic-t073.md; us7.md absent | partial | T073 log/backup/retention screens and the T074 E2E open |
| FR-029 | Collect no secrets, hidden reasoning or unrelated activity; manage retention, deletion, permissions, integrity | T008[x], T010[x], T016[x], T018[ ], T020[x], T023[ ], T090[ ], T025[ ], T088[ ], T071[x], T069[x]†, T070[ ]†, T079[ ]† | app/tests/test_domain_permissions.py, app/tests/test_retention.py, app/tests/test_export.py, app/tests/test_credential_vault.py, app/tests/test_claude_api.py | domain-permissions-persistent.md, retention-t069.md, deletion-decisions-t069.md, credential-vault-t090.md | partial | T018, T023, T025, T070, T088 and T090 open. T079 security review not started |
| FR-030 | Preserve user data and approvals through failures, restarts, updates and recovery; state unsupported restores | T008[x], T087[ ], T025[ ], T040[x], T072[ ], T012[x]†, T070[ ]†, T083[ ]† | app/tests/test_domain_storage.py, app/tests/test_graph_execution.py, app/tests/test_backup.py, app/tests/test_backup_key_init.py; named, absent: app/tests/test_update_recovery.py | domain-storage.md, checkpoint-attempt-binding-t040.md, backup-age-t070-2026-09-23.md, backup-key-init-ops-ac07.md | gated | Fresh hosts for update/migration/restore (T083). T072 not started. T070 needs the networkless worker service |
| FR-031 | Separate evidence levels (source, format, real run, independence, lens utility, satisfaction); mocks ≠ real | T002[x], T029[x], T035[ ], T080[ ], T075[ ]†, T077[ ]†, T085[ ]† | app/tests/test_lens_registry.py | baseline.md, lens-registry.md, us4.md | gated | Live providers (T035/T077) and real-user satisfaction data |
| FR-032 | Swap providers, tools, formats, lenses, stores and exports through closed core-owned port contracts | T086[x], T006[x], T087[ ], T047[x], T058[x], T084[ ], T003[x]† | app/tests/test_extension_port_schemas.py, app/tests/test_extension_port_schema_generation.py, app/tests/test_tool_boundary.py, app/tests/test_knowledge.py; named, absent: app/tests/test_extension_architecture.py, test_extension_binding_slots.py, test_extension_client_blackbox.py, test_extension_deployment.py, test_extension_rollback_retention.py, test_extension_route_registration.py (all under app/tests/) | adr014-independent-review-r7.md, extension-port-schemas-t087a1.md, tooldefinition-effect-gate-t087.md, tool-boundary-t047.md | gated | Copyright-owner license approval (T084). T087 largely open, with six named test files absent |
| FR-033 | Cross-review the whole design first; auto-decide routine recommendations; keep impact and rationale | T001[x], T086[x], T075[ ]† | none (process requirement) | design-review.md, adr014-independent-review-r7.md, adr014-review-input-manifest-r7.md | partial | T075 source-hash and supersession refresh open |
| FR-034 | Report approximate whole-task progress; give a remaining-time range once evidence supports it | T075[ ], T085[ ] | none | none (progress.md is maintained, but no evidence file audits it) | missing | T075 progress-numerator/ETA audit and T085 not done |
| SC-001 | Both deployment profiles on empty hosts with pinned image locks; browser US1–US7; live providers; out-of-tree extension | T026[ ], T049[ ], T077[ ], T083[ ] | deploy/tests/test_compose_topology.py, deploy/tests/test_build_input_lock_verifier.py | t089-supply-chain-verification.md, static-topology-t018c.md; deployment-report.md absent | gated | Fresh hosts (T083) and live providers (T026/T049/T077) |
| SC-002 | Each FR links to design location, task, acceptance test and result or unknown state | T075[ ], T085[ ]† | none | design-review.md (V0 map), this draft | partial | This draft only. The final T075 matrix is open |
| SC-003 | Three candidates differing on ≥2 structural axes; no false pass or false trio on shortfall | T027[x], T038[ ], T028[x]†, T036[ ]† | app/tests/test_graph_contract.py, app/tests/test_design_review.py; named, absent: app/tests/browser-design.test.mjs | graph-compiler-reaudit-t027t030.md, design-review-t036a.md; us2.md absent | gated | Live generation (T038). T036 open |
| SC-004 | Browser and real PDF/table/document/image lineage kept from producer through handoff to consumer | T044[x], T049[ ], T045[ ]†, T046[x]† | app/tests/test_document_tools.py, app/tests/test_handoffs.py, app/tests/test_run_artifacts_api.py; named, absent: app/tests/browser-runtime.test.mjs | document-tools-t044.md, document-tools-pdf-png-t044.md, handoffs-t046.md, run-artifacts-t045.md; us3.md absent | gated | T049 needs finite authorized Claude/Codex paths. T043 browser tool and T045 open |
| SC-005 | Same-model critic tests check isolation, grounding, defects, alternatives, abstention and joint failure | T038[ ], T077[ ], T035[ ]†, T076[ ]† | app/tests/test_critic_lens_pipeline.py, app/tests/test_critic_lineage.py | critic-lens-pipeline-t036.md, critic-lineage-t032.md; live-qualification.md absent | gated | Live critic trials and new release heldout (T035/T076/T077) |
| SC-006 | Alternative, missing-original, leak, new-evidence and out-of-scope cases satisfy FR-016–022 | T054[x], T077[ ], T050[x]†, T059[x]†, T060[ ]† | app/tests/browser-alternatives.test.mjs, app/tests/test_alternatives.py, app/tests/test_growth_firewall.py, app/tests/browser-inquiry.test.mjs | us4.md, growth-firewall-t059.md, inquiry-observation-t060-2026-09-23.md | gated | Real-user data (us4.md: "Actual-user alternatives: none recorded") and live runs (T077). T060 open |
| SC-007 | Distinguish plateau, improvement, small gains, errors, baseline change, restart, budget exhaustion; no false stop | T062[x], T067[ ], T063[x]† | app/tests/test_growth_loop.py, app/tests/test_growth_store.py; named, absent: app/tests/browser-growth.test.mjs | growth-loop-t062-t063.md; us6.md absent | partial | T067 open |
| SC-008 | Versions match from frozen candidate through validation, human approval and apply to rollback | T067[ ], T064[x]†, T065[x]† | app/tests/test_validation.py, app/tests/test_promotion.py, app/tests/test_promotion_approvals.py | validation-evaluator-binding-t064.md, promotion-approvals-t065.md | partial | T066 persistence blocker and T067 open |
| SC-009 | Extract required record categories with leak checks, scoping, redaction and gaps; no auto-send | T074[ ], T068[x]†, T071[x]†, T079[ ]† | app/tests/test_event_coverage.py, app/tests/test_export.py, app/tests/test_work_exports_api.py; named, absent: app/tests/browser-records.test.mjs, app/tests/test_release_security.py | event-coverage-t068.md, export-t071.md, work-export-t073-2026-09-23.md; us7.md and security-review.md absent | partial | T074 and T079 open |
| SC-010 | Final report separates implementation, live tests, real use, effects and external approvals | T085[ ], T075[ ]†, T083[ ]† | none | release-report.md absent | gated | External approvals (license, signing: T084/T082), fresh hosts (T083) and real-user evaluation |
| UX-AC01 | Fresh instance, browser only: input → understanding → real lenses → distinct graphs → first run | T023[ ], T037[ ], T078[ ] | app/tests/start.test.mjs, app/tests/work.test.mjs, app/tests/browser-owner-lifecycle-t025.test.mjs | first-screen-setup-login-t025.md, intake-page-t023.md, observe-page-mount-t048.md | gated | Fresh instance and live lens generation. T023, T037 and T078 open |
| UX-AC02 | Editing survives view switches, refresh and server restart; GET never executes; conflicts preserved | T078[ ] | app/tests/browser-alternatives.test.mjs, app/tests/test_public_events.py, app/tests/test_local_session.py | us4.md, local-session.md | partial | T078 open. us4.md covers refresh and stale-tab conflict, but no server-restart case was found |
| UX-AC03 | Claude-API-only and Codex-subscription-only users each complete the full journey | T023[ ], T078[ ] | app/tests/test_claude_api.py, app/tests/test_codex_api_mode.py, app/tests/test_provider_connections.py | claude-api.md, codex-api-mode.md | gated | Live providers and real billing/credit paths. The T023 provider GUI is open |
| UX-AC04 | Real browser tool and PDF creation; per-attempt IO; the next role receives the exact file | T048[ ], T078[ ] | app/tests/runtime.test.mjs, app/tests/test_run_trace.py, app/tests/test_document_tools.py | runtime-gui-logic-t048.md, run-panel-dom-t048.md, run-trace-attempt-layer-t048.md | partial | T043 browser tool, T048 and T049 open |
| UX-AC05 | Unexplained whole/partial alternative → differences and explanations → lens evidence → typed change | T052[x], T060[ ], T078[ ] | app/tests/browser-alternatives.test.mjs, app/tests/browser-inquiry.test.mjs, app/tests/alternatives.test.mjs | own-version-editor-t052-2026-09-23.md, inquiry-observation-t060-2026-09-23.md, us4.md | partial | T060 has no explanation/hypothesis generator connected |
| UX-AC06 | Paired prior-queue runs → rounds → plateau/limits → final check → exact human approval and rollback | T066[ ], T078[ ] | app/tests/approvals.test.mjs, app/tests/test_paired_execution.py | run-approvals-human-gate.md, paired-execution-t061.md | partial | T066 persistence blocker. `app/static/experiments.mjs` absent. `versions.mjs` exists only as uncommitted concurrent work, with no evidence file |
| UX-AC07 | Never hide out-of-scope impact, unanswered items, extraction loss, bad critiques or alternative errors | T060[ ], T078[ ] | app/tests/browser-inquiry.test.mjs | inquiry-observation-t060-2026-09-23.md | partial | T060 and T078 open |
| UX-AC08 | Records from the first observed control event; scoped, redacted export preview; sharing never required | T073[ ], T078[ ] | app/tests/records.test.mjs, app/tests/work-export.test.mjs, app/tests/test_work_exports_api.py | records-gui-logic-t073.md, work-export-t073-2026-09-23.md | partial | T073 log/backup/retention screens open |
| UX-AC09 | Real mic: explicit start, provisional/final transcript, Korean IME, cancel/deny/restart; no raw audio or external STT | T024[ ], T078[ ] | app/tests/browser-speech-input.test.mjs, app/tests/test_speech_api.py, app/tests/test_speech_sessions.py; named, absent: app/tests/test_speech_segments.py | speech-qualification-t024.md | partial | T024 ADR-011 migration open. Real microphone hardware check pending at T078/T083 |
| UX-AC10 | Scoped, safe recovery from missing connection, human wait, model limits, unconfirmed writes, save failure | T048[ ], T078[ ] | app/tests/test_graph_execution.py, app/tests/test_runtime_ledger.py, app/tests/runtime.test.mjs | run-recover-route.md, run-cancel-route.md, runtime-ledger.md | partial | T048 and T078 open |
| UX-AC11 | Settings > Extensions shows exact binding key+digest, slots, heads, retirement; keyboard/screen-reader | T087[ ], T078[ ], T083[ ] | app/tests/test_extension_port_schemas.py; named, absent: app/tests/test_extension_binding_slots.py, app/tests/test_extension_rollback_retention.py | extension-port-schemas-t087a1.md, extension-framework-design-remediation.md | gated | Fresh hosts (T083). `app/static/extensions.mjs` absent. T087 open |

## Invalid / failed / missing evidence

### A. Requirements with no test

| Req | Finding |
| --- | --- |
| FR-033 | Process requirement. Its evidence is design reviews only, and no automated test exists or is expected. |
| FR-034 | No test and no evidence file. `progress.md` holds a weighted estimate, but the T075 numerator audit has not been done. |
| SC-002 | No test. This draft is the only matrix artifact. |
| SC-010 | No test. `release-report.md` absent. |

### B. Test files named in tasks.md that do not exist

| Task | Missing file(s) |
| --- | --- |
| T024 | app/tests/test_speech_segments.py |
| T025 | app/tests/test_owner_sessions.py, app/tests/test_session_security.py, app/tests/test_deployment_control.py (`test_credential_vault.py` and `test_bootstrap_delivery.py` exist) |
| T026 | app/tests/browser-first-use-release.test.mjs |
| T034 | evals/deeptwin/verifiers/critic.py, evals/deeptwin/tests/test_critic_verifier.py (only `evals/deeptwin/tasks/v01-q01/Task.md`, `q01_materials.py` and `q01_lenses.json` exist; T033's `evals/deeptwin/harness/` is absent) |
| T036 | app/tests/test_design_selection.py |
| T038 | app/tests/browser-design.test.mjs |
| T049 | app/tests/browser-runtime.test.mjs |
| T067 | app/tests/browser-growth.test.mjs |
| T072 | app/tests/test_update_recovery.py |
| T074 | app/tests/browser-records.test.mjs |
| T078 | app/tests/browser-accessibility.test.mjs |
| T079 | app/tests/test_release_security.py |
| T087 | app/tests/test_extension_architecture.py, test_extension_binding_slots.py, test_extension_client_blackbox.py, test_extension_deployment.py, test_extension_rollback_retention.py, test_extension_route_registration.py |
| T088 | app/tests/test_codex_subscription_runner.py |

Evidence files named by tasks.md but absent: us1.md, us2.md, us3.md, us6.md, us7.md,
live-qualification.md, ui-review.md, security-review.md, performance.md, deployment-report.md,
release-report.md and implementation.md. UI modules named by open tasks but absent:
`app/static/graph.mjs`, `app/static/workspace.mjs` (T037), `app/static/experiments.mjs`,
`app/static/versions.mjs` (T066; present only as an uncommitted working-tree file at the time
of writing) and `app/static/extensions.mjs` (T087).

### C. Requirements whose only evidence is synthetic, test-actor or offline

| Req | Nature of evidence |
| --- | --- |
| FR-016, SC-006, UX-AC05 | us4.md: "Synthetic, test-actor evidence of the mechanism only … Actual-user alternatives: none recorded." |
| FR-018, FR-019, UX-AC05, UX-AC07 | inquiry-observation-t060-2026-09-23.md: "synthetic evidence from a scripted test actor". Hypotheses are `not_generated` and the inquiry is `not_opened`. |
| FR-006, SC-005 | design-criticism-live.md says, despite its name: "Offline: the boundary is a scripted callable; no provider transport is bound and no live/paid call occurs". No live critic trial exists. |
| FR-010, FR-011, UX-AC03 | claude-api.md and codex-api-mode.md use fake-server, offline tests only. claude-provider-protocol-check-2026-09-19.md is a docs-only read with no API request. |
| FR-026, SC-008, UX-AC06 | Approvals come from owner-session test fixtures (promotion-approvals-t065.md, run-approvals-human-gate.md). No real human promotion has occurred. |
| FR-022–FR-025 | paired-execution-t061.md uses code-owned evaluators over fixture runs in fresh vaults. No real prior-queue data exists. |
| FR-004, FR-031 | lens-registry.md records scholarly/effect/independence evidence as outstanding (T030/T035/T036/T056/T076/T077). |

### D. Evidence files that report a failure, a stale status or an open blocker

| Evidence file | Finding |
| --- | --- |
| work-export-t073-2026-09-23.md | "The 8 browser-*.test.mjs files (79 failing cases) fail the same way without this change; they need a real browser environment and are tracked under the regression task." This is an **open failure** in the browser suites on that host. Several export categories are stated as `unavailable`. |
| environment-record-t048.md, prepare-reconcile-budget-2026-09-23.md | Load-sensitive failures in `app/tests/test_provider_prepare_reconciliation.py` are fixed at cause. Under four busy processes one real-clock case still fails by design (17/1). The file records an **open product risk**: reconcile starvation on a slow host needs a contract change. |
| provider-suite-flakes-2026-09-22.md | Order/timing failures in the full run, resolved (fixture-only fixes, then a wholly green run recorded). Kept here for history. |
| worker-ipc-foundation-t018f1.md | `t018_foundation_linux_canary.py` gives "FAIL: native Linux SO_PEERCRED is required" on macOS (honest refusal). The Linux run is in linux-root-canary-t018-2026-09-23.md, and T018 stays open. |
| backup-age-t070-2026-09-23.md | "the checkbox stays open": there is no networkless backup-crypto service (T081), no GUI (T073) and no backup-before-migration gate (T072). The age-dependent tests **skip** without `DEEPTWIN_AGE_RUNTIME_ROOT`, and CI has no binary. |
| inquiry-observation-t060-2026-09-23.md | "T060 stays open": real hypotheses, inquiries and candidates wait on a connected generator. |
| own-alternatives-t050.md | **Stale status.** The header says "T050/T051 remain open (no domain persistence, no editors/UI…)", but both checkboxes are `[x]`. No later evidence file closes T050/T051 explicitly. The later editors are in own-version-editor-t052-2026-09-23.md. Needs reconciliation in final T075. |
| growth-loop-t062-t063.md | **Stale status.** It says "T062/T063 remain open (no live paired execution …, no persistence …)", but both are `[x]`. There is no later closing evidence file. |
| graph-compiler-reaudit-t027t030.md | The audit verdict was REJECT, with findings fixed. It states "T027/T028/T030 stay open for the live pipeline", but T027/T028 are `[x]`. **Stale or contradictory.** |
| diagnosis-t055.md, inquiry-t056.md, change-compiler-t057.md, comparisons-t061.md | Headers say "remains open". Each is superseded by a later closing file: format-differences-t055.md, spli-routing-hexp-t056.md, change-compiler-admissions-t057.md, paired-execution-t061.md. The supersession map (T075) should record this. |
| local-session.md, domain-permissions.md, dependency-installation.md | These record earlier open states for T016, T010 and T003, now superseded by server-api-v1.md, domain-permissions-persistent.md and the ADR-009 banner/T089. |
| us6-batch-audit.md, run-approvals-human-gate.md, extension-worker-metadata-task23.md | Review verdicts were REJECT or "spec FAIL" before fixes. The files record the findings as closed with regression tests. |
| credential-vault-t090.md | "T090 remains open": no gateway route, SSRF/redirect canaries or lost-response/race persistence yet. |
| static-topology-t018c.md, linux-root-canary-t018-2026-09-23.md | "not runtime-qualified and T018 remains open". |
| join-modes-t041.md | T041 is `[x]`, but "routers/joins/gates inside loops stay refused" is a recorded limitation. |
| vouched-transport-effect-journal.md | A free retry after a committed send intent "stays open as a ledger trust-model change". |
| web-framework-design-review.md | "The current repository has no license and is not yet legally an open-source release" (T084 gate). |
| first-screen-setup-login-t025.md, observe-page-mount-t048.md, run-list-source-t048.md, run-panel-dom-t048.md | "T049's browser case stays open". Some slices note that Playwright was not installed on that host. |

## Summary

### Counts per status (55 rows)

| Status | FR (34) | SC (10) | UX-AC (11) | Total |
| --- | --- | --- | --- | --- |
| verified-local | 4 (FR-016, 017, 020, 021) | 0 | 0 | 4 |
| partial | 17 | 4 (SC-002, 007, 008, 009) | 8 | 29 |
| gated | 12 | 6 (SC-001, 003, 004, 005, 006, 010) | 3 (UX-AC01, 03, 11) | 21 |
| missing | 1 (FR-034) | 0 | 0 | 1 |

Gated FRs: FR-001, 002, 003, 004, 005, 006, 007, 008, 010, 030, 031, 032.
Partial FRs: FR-009, 011, 012, 013, 014, 015, 018, 019, 022, 023, 024, 025, 026, 027, 028, 029, 033.

Task totals in tasks.md: 90 tasks, 52 closed and 38 open.

### Open tasks and their stated blockers

The blockers are those tasks.md states, including the 2026-09-23 notes where present.

| Task | Stated blocker / remaining scope |
| --- | --- |
| T018 | Actual Linux UID/peer paths, service images/initializers, real workers, runtime isolation enforcement, Chromium sandbox/seccomp and both clean profiles. `T018-final` waits for downstream owners and T083. |
| T087 | Per-execution approval binding, a production graph that binds a tool gate, per-tool input count/role binding and every other port. Durable lifecycle, routes, SDK/client and the `Settings > Extensions` UI are all absent. |
| T023 | Sources/files, microphone, understanding requests and the provider/key/model GUI. Cannot close provider mutation before T025/T090. |
| T090 | Needs the T018-foundation, T025 vault/deployment and T087 provider ports. No gateway route yet. |
| T024 | ADR-011 PCM PUT/SSE migration. Needs the T018-foundation speech channel. |
| T025 | **Deployment-control recovery port**: `app/services/deployment_control.py`, `app/operations/deployment_control.py`, typed `credential_client.py` and their tests (the password-change evidence re-checked this on 2026-09-23). |
| T088 | Server-owned Codex device-auth runner. Needs T025/T087. |
| T026 | Staged-topology US1 integration with authorized actual-provider checks (live gate). |
| T030 | Real candidate generation over a bound provider. |
| T033 / T034 / T035 | Q01 harness, independent verifier, and calibration with authorized live trials. |
| T036 | design_review / critic-lens production routing (environments approval part landed 2026-09-17). |
| T037 | Graph comparison UI not started. |
| T038 | Real generation→critique→selection browser E2E (live). |
| T042 / T043 | Frozen multimodal turns / Codex step bridge; sandboxed Chromium navigation. |
| T045 | PDF/DOCX page previews through the codec worker; vault-wide artifact index. |
| T048 | Consent expiry/revocation, the design arc's production path, run creation from the intake page and T049's browser case. |
| T049 | Controlled browser/PDF/table/image E2E, then finite authorized Claude/Codex paths. |
| T060 | **No connected explanation/hypothesis generator**. Hypotheses show `not_generated`, the inquiry `not_opened`, and there is no change candidate. |
| T066 | **US6 persistence blocker**: frozen candidate bundles and validation reports have no store resume path (and no round persistence), so the approval/rollback UI has nothing durable to decide over. |
| T067 | G-06–G-15 browser growth cases (after T066). |
| T070 | Networkless backup-crypto worker service (T081) and the GUI/migration gates (T072/T073). |
| T072 | Update/recovery integration of the T025 `DeploymentControlPort` (T025 port still open). |
| T073 | Log, backup and retention screens (backup needs the T070 worker; retention needs a persistent ledger service). |
| T074 | Records/export browser E2E. |
| T075 | This matrix's final form, source-hash/supersession refresh and the progress/ETA audit (after T083). |
| T076 / T077 | Release qualification freeze; authorized live comparisons. |
| T078 / T079 | UI and security qualification against the frozen T081 candidate. |
| T080 | Performance/STT measurements. |
| T081 / T082 | Final distribution/images; checksums, SBOM and signing (signing needs external authority). |
| T083 | Two fresh hosts (macOS Portainer CE, Linux Compose). |
| T084 | **Pending copyright-owner license approval**. No LICENSE/NOTICE added. The publishable-tree scrub and the Compose gaps it found (backup service without backup-key volume/init, ipc-root-init boot-secret regeneration) remain open. |
| T085 | Final regression, quickstart acceptance and release report. |

## Later the same day: slices landed after this draft was written

These change no row's status: every claiming task named below is still open. They narrow the
open-work notes of the rows they touch. Each slice's evidence file holds its observed runs.

| Task | Slice | Rows touched | Evidence |
| --- | --- | --- | --- |
| T066 | Persisted paired rounds are re-issued exactly and shown paired (baseline/candidate runs, validity and reasons, a score only on valid rounds, unreadable rounds listed). Plus a real-browser wiring check of the versions page | FR-022, FR-023, FR-026, UX-AC06 | versions-t066-2026-09-23.md |
| T043 | Pinned HTTPS transport behind the egress broker: literal-address sockets, SNI and certificate bound to the hostname, no proxy or redirect following, streamed byte limit | FR-014 | egress-transport-t043-2026-09-23.md |
| T048 | Run-consent revocation and expiry (v2). One current-consent check before start, resume, recover and replay | FR-013, FR-019, UX-AC04 | run-consent-revocation-t048-2026-09-23.md |
| T074 | Records in real Chromium: export preview, bound consent, raw only by choice, secret canaries absent, stale preview refused, the records log. **Fixed** the log's event time field, so the log now renders against the real server | FR-027, FR-028, SC-009 | browser-records-t074-2026-09-23.md |
| T084 | Workstation paths scrubbed from 40 documents; the pinned lens source awaits re-review | FR-001, FR-032 | publishable-scrub-t084-2026-09-23.md |
| T070 | **Fixed**: the backup now carries and verifies the content-addressed originals. The database-only archive could not back up any vault that held an original | FR-029, FR-030 | backup-age-t070-2026-09-23.md |
| T073 | Explicit deletion of stored originals: server preview, consent bound to its digest, tombstones, `retention.deleted`, readers answer `deleted`, backups carry only live originals. Work-screen panel and a real-browser case | FR-027, FR-029, FR-030 | source-deletion-t073-2026-09-23.md |

**Hash note.** The T084 scrub changed the bytes of four plan/UI files and two provider
documents whose earlier hashes are pinned in historical review-input manifests. The final T075
refresh must use the current bytes and cite that scrub as the supersession.
