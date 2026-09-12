# Historical V0 native-boundary whole-design review (superseded by ADR-009)

2026-09-07 · Historical status only. This review was suitable for the then-assumed native
architecture, but the user's 2026-09-08 correction defines DeepTwin as an open-source web
framework. Native App Sandbox/XPC/launcher/DMG findings below are preserved as an audit trail and
MUST NOT qualify the current release. The current gate is `web-framework-design-review.md`.

## Method and authority

Root read the constitution, requirements, contracts and relevant paper sections; independent
reviewers examined UX/runtime and data/growth/evaluation boundaries. Spec Kit read-only analysis
ran after tasks generation, with the prerequisite script confirming spec/plan/tasks. That
analysis made no file edits. Subsequent corrections used the user's existing explicit delegated
decision authority as a separate editing phase. No mandatory hooks were configured.

Current requirement correction: Claude API-only, Codex subscription plus explicitly selected
optional API; old goal wording/INT-025 Claude clause is superseded. Product plateau is not
development stopping. Real human promotion, evidence validity and no implicit paid/public
authority remain unchanged.

## Findings and disposition

| ID | Severity | Finding | Resolution and review |
| --- | --- | --- | --- |
| RT1 | High | Producer completion could wait on receiver that needs producer success | Separate artifact seal/handoff-ready from delivery/use; runtime §4/5 and T046; independently rechecked |
| RT2 | High | Join activation set/winner race underspecified | Seal per-visit branch set; atomic winner and one successor; T041; independently rechecked |
| RT3 | High | Read URL could exfiltrate private data | Source/projection plus recipient grants, actual-request broker enforcement; T043/047; independently rechecked |
| RT4 | High | Proxy/routing alone did not force egress | Choose network-less App Sandbox XPC worker + host fetch/fulfill; SB-01–07 empirical gate, no SBPL fallback; design choice reviewed, runtime not yet tested |
| RT5 | Medium | Multimodal receiver might see only filename/text | Typed image/page/table parts and exact supplied/omitted range evidence, T042/046; independently rechecked |
| RT6 | Medium | Blanket policy-relaxation ban could block legitimate improvement | Separate nondelegable safety/authority from authorized ordinary-work changes; T057/058; independently rechecked |
| DM1 | High | Content hash could contain itself | Body→digest→reference envelope, defined mutable metadata exclusion and test vectors; root corrected |
| DM2 | High | Internal backup ciphertext hash circularity | BackupReceipt external to authenticated inner manifest; root corrected |
| DM3 | High | Bootstrap required the session it should issue | Sole one-use launcher capability exchange exception, expiry/Origin/atomic consume; root corrected |
| DM4 | High | Rename durability omitted parent sync | Destination directory sync plus SQLite FULL/macOS fullfsync qualification; root corrected |
| DM5 | Medium | All timeout labels treated invalid despite observed capability failure | Separate terminal cause from completed comparison validity; growth and verifier agree; root corrected |
| C1 | High | Actual conversation implementation absent from task assignment | T023 ChatMessage/ProposedCommand/UI/authority tests + schema/plan paths; independent re-review confirmed scope closure |
| C2 | High | Production critic lens routing implicit | T036 qualified routing/composition/LensPack/CE/independent validity-response and isolation tests; independent re-review confirmed scope closure |
| M1 | Medium | Full-loop skeleton had no owned task | Removed unassigned promise; every story has explicit integration tests |
| M2 | Medium | Phase9 logging could imply late instrumentation | Per-feature events required before first live trial; T068 is comprehensive audit |
| M3 | Medium | Calibration/final qualification freeze could reuse seen cases | T035 calibration and T076 release-v1 separate versions/datasets; exposure history preserved |

Final independent UX review reported no new High/Critical design defect. Remaining native,
provider, semantic/effect and signing risks are not waived: their concrete tests must pass
before corresponding support/completion claims. Root reconciled the medium task clarifications.

## Spec Kit analysis and coverage

Initial formal analysis: 44 requirement keys (34 FR + 10 buildable SC), 85 tasks, 100% having
at least one mapped task, 0 critical, 2 high detailed-coverage gaps (C1/C2), no unmapped tasks.
Both gaps corrected and independently re-reviewed. Mapping coverage is NOT implementation
coverage. IDs T001–T085 are unique/sequential; 85/85 use valid checklist form.
US task counts: 8,12,11,5,6,7,7; shared setup/foundation/final: 29. All stories remain P1.

| Requirement | Assigned tasks |
| --- | --- |
| FR-001 | T018, T025, T081, T083 |
| FR-002 | T023, T024, T026 |
| FR-003 | T026, T030 |
| FR-004 | T029, T030, T076, T077 |
| FR-005 | T028, T037, T038 |
| FR-006 | T031, T032, T033, T034, T035, T036, T076, T077 |
| FR-007 | T036, T038 |
| FR-008 | T037, T038 |
| FR-009 | T016, T023, T037, T054, T078 |
| FR-010 | T020, T022, T026, T049, T077 |
| FR-011 | T014, T020, T021, T022 |
| FR-012 | T022, T023, T042 |
| FR-013 | T012, T028, T039, T040, T041, T048 |
| FR-014 | T018, T043, T044, T047 |
| FR-015 | T045, T046, T053 |
| FR-016 | T050, T051, T052, T053 |
| FR-017 | T008, T010, T051, T059 |
| FR-018 | T055, T060 |
| FR-019 | T029, T056, T060 |
| FR-020 | T010, T057, T059 |
| FR-021 | T057, T058 |
| FR-022 | T051, T061, T067 |
| FR-023 | T061, T067 |
| FR-024 | T014, T062, T063, T067 |
| FR-025 | T061, T064, T067 |
| FR-026 | T065, T066, T067 |
| FR-027 | T006, T012, T025, T068 |
| FR-028 | T071, T073, T074 |
| FR-029 | T010, T016, T020, T069, T070, T071, T079 |
| FR-030 | T008, T012, T025, T070, T072, T083 |
| FR-031 | T002, T035, T075, T077, T085 |
| FR-032 | T003, T006, T047, T058, T084 |
| FR-033 | T001, T075 |
| FR-034 | T075, T085 |
| SC-001 | T026, T049, T077, T083 |
| SC-002 | T075, T085 |
| SC-003 | T027, T028, T036, T038 |
| SC-004 | T044, T045, T046, T049 |
| SC-005 | T035, T076, T077 |
| SC-006 | T050, T054, T059, T060 |
| SC-007 | T062, T063, T067 |
| SC-008 | T064, T065, T067 |
| SC-009 | T068, T071, T074, T079 |
| SC-010 | T075, T083, T085 |

## Gate outcome and next work

At the time, V0 permitted implementation against that baseline. ADR-009 revoked this as the
current architecture gate; only transport-neutral results may carry forward. Web-framework-
dependent work requires the V1 review, with no approved constitutional exceptions.
T002 baseline checks and T003 exact dependencies come next; then typed domain/storage/authority
and native feasibility. Test-first changes receive specification and quality review. No new
product code, paid calls, signing/account changes or publication occurred during V0.

Evidence snapshots of source documents are point-in-time; subsequent edits create a new
snapshot/decision, not a retroactive alteration of review history. Whole-product completion
still requires the later gates. Academic review, actual user satisfaction and generalized
lens effectiveness cannot be invented to close a checkbox.
