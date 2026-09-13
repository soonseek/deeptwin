# Evidence — adversarial audit of the design batch (criticism_live,
# criticism persistence, design_review, environments)

- Date: 2026-09-13
- Verdict: **REJECT** — 2 critical, 4 major, 4 minor; all code findings
  closed. Auditor's reproduction scripts (r1–r7) served as the RED
  evidence for the regression tests in
  `app/tests/test_design_audit_findings2.py` (7 tests).

## Frozen identities (post-fix)

```
7566bfd4237c5c6b921f09cea8093cdcb8ca0fdb743f70c810b3fadbce4be452  app/services/design_criticism.py
8c38cb15d2a9fdbf334cb7ec543a36cdcff69bdf5594bf8224ef56125e0f1381  app/services/design_criticism_live.py
776de34486719904086822ff4ebb819cd31bebf7d8e3133f0751cd6c70608354  app/services/design_review.py
49cddd2087450c5c7df296da515c5876e89500befb3b2e05f31c11309ff361a3  app/services/environments.py
fd0822db03c9f2eea9eea5ce3c9056a1a2d5d2dcf7b418e61c5c09528954823d  app/services/design_persistence.py
303dc390848ed032135313cb2731bc2e72303123d09cc79139f3cbe597e90e0f  app/tests/test_design_audit_findings2.py
```

## Findings fixed

- **F1 (critical)** An unreviewed candidate reached "prepared" through a
  plainly constructed CandidateVerdict → `CandidateVerdict` is now a
  fold-issued value (init disabled, issuer token, `is_issued_verdict`);
  the pool, the approval and the persistence path all require issuance.
- **F2 (critical)** A wholly fabricated criticism run persisted as durable
  "model-generated" evidence → `CriticismCallRecord` and
  `CriticismRunResult` are driver-issued values; `persist_criticism_run`
  requires `is_issued_criticism_run` + per-record issuance;
  `response_sha256` is now documented as the boundary's attestation (raw
  responses are not retained beyond their hash).
- **F3 (major)** Non-atomic persist left orphan call records after a
  refused run → the candidate-record binding and the fold recompute now
  run BEFORE the first put (`_validate_candidate_criticism`), verified by
  `test_a_refused_run_stores_nothing`.
- **F4 (major)** One approval prepared unlimited environments →
  `DesignApproval` binds one `environment_id` (inside its content hash);
  `prepare_environment_version` refuses a foreign environment; the
  EnvironmentState storage-CAS seam is documented in the module docstring.
- **F5 (major)** Verdicts bound candidates by name only → `CandidateVerdict`
  carries `candidate_sha` (the graph content hash) and every consumer uses
  `verdict_binds_candidate`; a verdict earned by design A never pools or
  approves design B.
- **F6 (major)** No request binding in pool/merge; self-merge accepted →
  `assemble_selection_pool(request, entries)` and
  `derive_design_version(request, action, parents)` require every
  candidate/parent to bind the exact request; derivation parents must be
  distinct.
- **F7 (minor)** Caller entry order chose the presented duplicate → the
  pool processes entries in deterministic (candidate_id, version) order.
- **F8 (minor)** SelectionPool lacked the issuer token → added.
- **F9 (minor)** `EnvironmentError` shadowed the builtin (is OSError) →
  renamed `EnvironmentContractError`.
- **F10 (minor)** Approvals were unlinked from their review basis →
  `DesignApproval.verdict_sha` names the exact verdict content in the
  durable approval (and its sha).

## Auditor's verified negatives (retained)

Non-str/oversized model responses, bool-as-head confusion, truthy
authentication, profile-digest divergence, >16-counterexample runaway,
prompt content in exceptions, replace() on issued values, idempotent puts,
forged/dropped/reordered call records, and absent activation paths were all
tried and correctly defended.

## Verification

- 7 new regression tests (RED evidenced by the auditor's reproduction
  scripts; all now green) + updated legacy suites (fold-earned verdicts in
  test fixtures, request-bound pool/derivation calls, TypeError on forgery
  construction).
- `ruff check` clean; full regression
  **3221 passed, 2 skipped, 369 subtests** (was 3215).
