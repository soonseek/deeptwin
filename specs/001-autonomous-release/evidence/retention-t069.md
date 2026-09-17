# Evidence — T069 retention: manual-only core, bounded pruning, tombstones

- Date: 2026-09-13
- Task: T069 [US7] manual-only core retention, bounded cache/debug pruning
  and explicit deletion preview/tombstone/impact in
  app/operations/retention.py (operations.md OPS-D04/D05,
  §RetentionPolicy, OPS-AC06).

## Frozen identities

```
6aad57b1f5e3c584c8b197eb71589e90d6c2f2a454426de95ad4804011f7205c  app/operations/retention.py
621b65637dee17307afd3a2af480aa856c0c3351c6ed405490c2e9e32add217e  app/tests/test_retention.py
```

## What was built

- `freeze_retention_policy` — `core_mode` is `manual_only` and NO other
  mode exists (the contract's exact defaults: cache 14d/1GiB,
  diagnostics 30d/100MiB, both configurable within bounds).
- Classification discipline — an irreplaceable tool observation can never
  be classified as cache or diagnostics (OPS-D05: 다시 얻을 수 없는 관찰
  증거는 캐시가 아님).
- `prune` — touches ONLY cache and diagnostics: age-window expiry plus
  LRU byte-cap eviction within the window; core entries are never
  auto-deleted; the returned `PruneReport` (classification, count, bytes,
  windows) is the record the caller persists as a core event.
- Explicit deletion is a two-step human act:
  - `preview_deletion` states the exact scope, byte total and the
    derived/approval impact against the ledger's current revision, and
    content-hashes itself;
  - `delete_items` requires that exact issued preview against the
    UNCHANGED ledger revision (stale previews refuse — the human must be
    re-shown the scope) and an authenticated actor with `action_approval`
    evidence; every deleted item leaves a `Tombstone` carrying its
    classification, bytes, actor and impact — never a silent hole;
  - a consumed preview cannot delete twice (the revision moved).
- Issued values throughout; the ledger's single-writer transaction is the
  storage layer's, as with every other ledger in this codebase.

## Verification

- TDD: module absent first (collection error); 7 tests green.
- `ruff check` clean; full regression **3296 passed, 2 skipped**
  (was 3289).

## Amendment 2026-09-18 — deletion actor replaced by owner-recorded decisions

The paragraph above describing `delete_items` with "an authenticated actor with
`action_approval` evidence" is superseded: the caller-declared actor object is gone.
`delete_items(ledger, preview, *, approval, reason_code)` now requires an issued
`OwnerDecision` (kind `deletion`) over exactly `deletion_subject(preview, reason_code)`;
the preview digest covers the ledger identity, scope, bytes and the derived/approval
impact the human saw; tombstone actor/evidence/time/request id come from the owner's
record. See `deletion-decisions-t069.md`.
