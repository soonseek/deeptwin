# Evidence — deletion decisions (T069 residual) and design-store evidence resolution

- Date: 2026-09-18
- Scope: the last caller-declared `{"actor_id", "authenticated": True,
  "evidence"}` shape on an approval path (`delete_items`, app/operations/retention.py,
  T069 / OPS-AC06) is replaced by owner-recorded decisions of kind `deletion`;
  `persist_design_approval` (app/services/design_store.py) now resolves its
  evidence in the vault it writes to (follow-up from
  `owner-decisions-design-approval.md`); the module-scoped real owner session
  used by value-level suites becomes a shared helper.
- Builds on: `owner-decisions-design-approval.md`, `retention-t069.md`.

## Frozen identities

```
566f6020d4fb44ee85edc4247bcc46644dea6da04752fd9c76adab85ef49b7ba  app/operations/retention.py
926459c42d24a69b0f18122112979f3edddaa346b3e244442abfc40cc84a4b8e  app/services/design_store.py
b5e6eee737e3be1e182c21d598f1a181ab2535c7388f3da2a3c6a81a9b9baa34  app/services/environments.py
2c4bdc7fd55be300f5cd412fd45fbdbc61743e619e6b0d953b145516607ff127  app/services/owner_decisions.py
ef68462d0278cdf5f9eded600c33f89e12300a6d4d95935f32d0c700ff8f0b37  app/tests/owner_session.py
e43b82bad92f8f207e4b00deed50805335734a603429410b079f35c0f3d6a050  app/tests/test_retention.py
bc28659c61ed3fe2d6a2f7691ba8946d1acd2289d841f8d864323e58ae975c03  app/tests/test_ops_audit_findings.py
48b044c53cd4ca218fd198a873f4d2b36df1695de0ad2846dc90cb884075ca42  app/tests/test_design_store.py
3506c62c9b9046ed0024c4a29684f9f258f89be356efcc9c299354fde055d6b8  app/tests/test_environments.py
d118666bb73e303f3621a08d082f5af8d92096b3bb0b436f162091d24c4fa241  app/tests/test_owner_decisions.py
```

## What was built

- Retention: `RetentionLedger` carries a `ledger_id` issued at open;
  `DeletionPreview` carries it and its digest now covers the ledger identity,
  scope, revision, byte total and the derived/approval impact the preview
  shows. `deletion_subject(preview, reason_code)` is the exact subject the
  human approves (ledger id, preview digest, revision, item ids, bytes,
  reason). `delete_items(ledger, preview, *, approval, reason_code)` requires
  the preview to be from this ledger and revision and an issued
  `OwnerDecision` of kind `deletion` whose subject equals that subject with
  decision `approve`; tombstone `actor_id`, `evidence_ref`, `deleted_at` and
  `deletion_request_id` come from the owner's record (actor ref, approval
  ref, decided stamp, command id). The reason code is the only caller input
  and is bound by the subject. One decision cannot apply to another ledger
  (identity), another revision, another scope, another reason, or twice.
- Design store: `persist_design_approval(domain_store, approval, *,
  decisions, **headers)` requires a `PersistentOwnerDecisions` bound to the
  same store (`bound_to`), resolves `approver_evidence` through it and
  refuses unless the decision is kind `design_approval`, `approve`, over
  `design_approval_evidence_subject(approval)` (rebuilt from the approval;
  identities now include `entity_kind`, so a kind-swapped copy is refused),
  by the same actor and stamp. Nothing refused is written.
- `app/tests/owner_session.py` — `OwnerSession(name).fixture()` opens one
  real owner app per test module (module scope, autouse) and `decide(kind,
  subject, decision)` records decisions; test_environments (`design_owner`)
  and test_retention (`retention_owner`) use it, importing modules re-export
  the fixture name. A session-scoped teardown of the TestClient hung pytest
  at exit earlier; module scope closes each app right after its module.

## Review (independent, adversarial) and closures

Verdict on the first cut: ACCEPT with three SHOULDs, folded in RED-first:

1. The preview digest did not cover the shown impact and nothing identified
   the ledger — one decision deleted on two ledgers with equal items, bytes
   and revision → `ledger_id` + impact in the digest; test
   `test_a_decision_binds_this_ledger_and_the_impact_the_human_saw`.
2. Reference kinds were outside the design subject, so a kind-swapped copy
   of an approval persisted a second record for one decision → `entity_kind`
   in every identity; tampered-copy cases in test_design_store.
3. A `count == 0` assertion against the shared owner vault passed only by
   file order → before/after snapshot of this flow's records.
- NITs: foreign-store comment reworded (refusal happens at `bound_to`,
  before any resolution); approver id / stamp tamper cases added; stale
  docstrings and `retention-t069.md` amended; `PersistentOwnerDecisions.bound_to`
  replaces the private-attribute check.
- Recorded, not changed: `app/static/records.mjs` `deletionRequestPayload`
  still mirrors the retired actor payload; no Python route imports
  `operations.retention` yet, so it is unwired — when the deletion route
  lands it must carry an owner-decision command id instead.

## Verification

- TDD: `ImportError` on `deletion_subject`, `TypeError` on the `decisions`
  keyword, attribute errors on `ledger_id` / `bound_to` / `entity_kind` first,
  then GREEN.
- Covering command (retention, ops audit, design store, environments, design
  audit 2, owner decisions, records mirror): **66 passed, 1 inherited
  warning, 9.34s**. Ruff check/format clean on every changed file. Node
  `records.test.mjs` passes unchanged.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No `{"authenticated": True}` caller-declared shape remains on any approval
  path (`grep '"authenticated"' app` → only session state strings and the
  port-schema generator's trusted actor record, which is not this ruling).
- No route or GUI calls these producers yet; no model/tool/paid call; no
  publication; no license decision.
