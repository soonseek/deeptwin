# T056 — inquiry contracts with frozen opposing predictions (US5)

Date: 2026-09-13
Status: implemented and unit-verified contract slice; **T056 remains open**
(no live SPLI question generation, no H_exp update mechanics, no persistence,
no UI)

## Exact scope

`app/services/inquiry.py` implements the freeze-before-evidence discipline of
contracts/growth.md and G-03/04:

- `open_inquiry(difference, hypothesis_set, registry, lens_decisions,
  questions, opposing_predictions, frozen_at)`: opens only over the exact
  difference whose hypothesis set holds at least one **confirmed
  expert-judgment** hypothesis; every lens decision must be vouched by the
  exact supplied `LensRegistry` instance (a decision from another registry is
  foreign), carry the `post_alternative_spli` path and a `qualified`
  qualification status. Questions and opposing predictions freeze at
  `frozen_at`; each prediction pair must actually oppose (identical texts are
  rejected) and bind a real question index.
- `observe_evidence`: evidence stamped at or before the freeze is rejected
  (strictly-after ordering), evidence kinds are observable records only, and
  the existing alternative or original artifact can never be renamed into new
  evidence (the `new E_phi` rename guard).
- `conclude_inquiry`: `supported`/`refuted` require actual fresh evidence;
  `declined` and `unresolved` are legitimate without any (the abstain/decline
  path); a concluded inquiry is final — further observation or conclusion is a
  typed error.

Tests: `app/tests/test_inquiry.py` (6) — frozen opening; confirmed-H_exp and
registry-vouched SPLI gating incl. the foreign-registry case; opposition and
index discipline; freeze-ordering and rename-guard evidence rules; outcome
evidence requirements with decline-without-evidence; strict shapes.

```text
python -m pytest -q app/tests/test_inquiry.py
6 passed
ruff check app/services/inquiry.py app/tests/test_inquiry.py
All checks passed
python -m pytest app/tests deploy/tests -q   (full shared regression, 2026-09-13)
3,107 passed, 2 skipped, 369 subtests passed, 1 known warning
```

## Frozen content identities (SHA-256)

```text
4416f6d5c29bbe3e18a74885a59e4510d02ab04e7290ec04f008fee975f309b6  app/services/inquiry.py
708315c52ea979108dc68a90007e0dd31c3fc71dd0ca230484f4fb734deb841b  app/tests/test_inquiry.py
```

## Not claimed

No live model generates SPLI questions, the H_exp update after an inquiry
outcome is not yet implemented, nothing persists to the domain store, and the
inquiry UI (T060) does not exist. No independent audit of the US4/US5 contract
slices (alternatives/diagnosis/inquiry) has run.
