# Evidence — T065 closure: owner-recorded promotion approvals

- Date: 2026-09-17 (slice started 2026-09-16)
- Task: T065 [US6] authenticated exact-hash approval / activation CAS /
  rollback compatibility (FR-026; growth.md `PromotionDecision` "사람의
  인증된 명시 결정", G-11, G-13, §7). Reopened on 2026-09-15 because
  `record_promotion_decision` accepted a caller-declared
  `{"authenticated": True}` approver. This slice replaces that boolean with
  authoritative owner-session evidence and closes the task.
- Builds on: `run-approvals-human-gate.md` (persistent owner authority as the
  only approval author), `promotion-t065.md` (value-level CAS/rollback).

## Frozen identities

```
bf0ae8dfc2843f5b748a558b6e55ddbd147a72d7f4f79efbf31f62959d547b71  app/services/promotion_approvals.py
0b76cf7028732c156258dcaa923ad5547f904ff5b3ffdab3019d8ab27fb0ad34  app/services/promotion.py
c3f274f3985b3dc59a017936afa3151e60cde298e15c03a0501531dd7a7c0486  app/services/run_approvals.py
637461508cf71ae3669a63a6471d2511d3d86fd74d7a3fae444f71160553cd04  app/services/validation.py
847e09ae9bfea06d49e9252c69785d6e760e47a101f35e209202fa3c6c692a00  app/tests/test_promotion_approvals.py
7a54563cc65da71e6b200a699e18e32dd223b0006ac3b8bf41e3e9b8cf84de00  app/tests/test_promotion.py
49477ad5a7f51b5ff18738f8a36a8c9b4d9168f36c2e251888d7df933e64e203  app/tests/test_us6_audit_findings.py
4551a408395765f5fca8981d637827ab1834072a95b2b4117b846390a7ef1458  app/tests/test_run_approvals.py
eda1e331d82dec18b658fd37b2b4e7f311e274d72791f3878ae0a00a06920b12  app/tests/test_growth_store.py
```

## What was built

- `app/services/promotion_approvals.py` — `PersistentPromotionApprovals`
  (`record(request, payload)`, `resolve(ref)`), the producer of issued
  `PromotionApproval` values. The persistent owner session is
  re-authenticated with `authenticate_bound` inside the final writer
  (authentication precedes command parsing, so an unauthenticated caller
  learns nothing about the grammar). One immutable `action_approval` record
  per command (identity uuid5 over the command id; exact replay returns the
  same value, any other body under the same command conflicts, nothing is
  overwritten). Content schema `promotion-approval-v1` binds the exact
  candidate bundle identity, the validation report the human decided over
  and the expected current environment — each stored as `(id, version,
  sha256)` identity fields with the kind fixed by field name, because the
  store verifies every exact reference it finds in record content against
  the vault and bundle/report identities are content-derived values that may
  precede any stored record. An approve/reject appends `approval.decided`
  (`approved`/`rejected`) in the same transaction; a defer appends no decided
  event and stores `event_sequence: null`. `resolve` re-validates stored
  content with the writer's grammar (exact key set, closed decision, UUID
  command id, canonical stamp, identity derived from the command, the named
  `approval.decided` event actually present, owner actor as author) — a
  record the owner's actor authored with malformed content never resolves.
- `app/services/promotion.py` — `record_promotion_decision` takes
  `{candidate, validation_report, scope, approval, expected_current_environment,
  rollback_bundle}`. Decision, decision time and approver come only from the
  issued approval; the approval must bind exactly `candidate.bundle_ref`, the
  content-derived reference of the report in hand and the expected current
  environment, else `PromotionError`. `activate_candidate` consumes by the
  approval record's hash (`approver_evidence.sha256`) instead of the decision
  object's content hash, so the same approval re-wrapped with another scope
  or rollback bundle after a rollback is refused (review F1); the persisted
  `consumed_decisions` shape (64-hex strings) is unchanged.
- `app/services/validation.py` — `validation_report_ref(report)`: the
  content-derived reference previously computed inline in promotion.
- `app/services/run_approvals.py` — owner authentication, actor-ref lookup
  and the bound-pair check extracted as module helpers shared with the
  promotion producer; authentication now precedes command parsing.

## Review (independent, adversarial) and closures

Verdict on the first cut: REJECT. All findings closed RED-first:

1. REJECT F1 — consumed-approval bypass via a re-wrapped decision object
   after rollback → consume by approval evidence;
   `test_f2b_a_consumed_approval_never_returns_under_another_decision_object`.
2. SHOULD — approval did not bind the validation report → `validation_report`
   in command, content and `PromotionApproval`; constructor checks it.
3. SHOULD — `resolve` trusted loosely validated content → `_parse_content`
   grammar + derived-identity + event-presence checks; 13-case parametrised
   refusal test writing owner-authored malformed records directly.
4. SHOULD — public event ambiguity: the closed catalog
   (`app/domain/events.py`) has no promotion kind on `approval.decided` and no
   `deferred` value. Recorded, not silently omitted: promotion and run
   decisions share the `approval.decided` shape and a defer is visible only
   through its record. A catalog change is a contract decision left open.
5. SHOULD — F16 stamp rejection lost coverage → tampered `decided_at_utc` on
   an issued approval is refused by the constructor (three malformed stamps).
6. SHOULD — process-global lazily created owner session with `atexit`
   teardown → module-scoped autouse fixture `promotion_owner` imported by the
   three value-level suites; opened before their first test, closed right
   after their last. (A session-scoped conftest teardown was tried first and
   hung the process at exit on the TestClient lifespan; discarded.)
7. NIT — `functools.wraps` on the closed-error decorator. 8. NIT — auth-first
   ordering in both producers, with tests.

## Verification

- TDD: `ModuleNotFoundError` on the absent module, then GREEN; each review
  closure RED first (import error / assertion) then GREEN.
- Covering command (promotion approvals, promotion, US6 audit findings,
  growth store, run approvals + API, validation, scheduler):
  **126 passed, 1 warning (inherited Starlette/AnyIO) in 32.41s**.
- Ruff check/format clean on every changed file.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No caller-declared boolean remains on the promotion path. The same
  `{"authenticated": True}` shape still exists off this path in
  `app/services/environments.py` (DesignApproval, T036 — prepares a design,
  does not operationally promote) and `app/operations/retention.py`
  (deletion actor, T069). Both are recorded as follow-ups, not T065 blockers.
- No route or GUI element calls the promotion producer yet; §8 promotion
  screen disclosure remains UI work.
- No model, tool or paid call; no publication; no license decision.
