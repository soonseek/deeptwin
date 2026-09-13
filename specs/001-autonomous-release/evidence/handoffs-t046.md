# Evidence — T046 whole-artifact handoffs

- Date: 2026-09-13
- Task: T046 [US3] whole-artifact handoff readiness/delivery/receipt and
  observed-use lineage in app/services/handoffs.py; no producer/consumer
  acknowledgment deadlock (runtime.md §5, R06).

## Frozen identities

```
5fae5389c57c64ba598982aa62aecc7d607eb259b7a36dff5393f35b95a18b6f  app/services/handoffs.py
e916481979ec0d10c63f93316109bdadc7638841066d8f49576fd9b4e42c33a8  app/tests/test_handoffs.py
```

## What was built

- `create_handoff` — binds producer execution/attempt, exact bounded
  artifact refs (no duplicates), receiver execution/input slot and the
  schema check ref.
- Separated evidence states, each a single-shot transition:
  - `mark_ready` — producer success is COMPLETE at readiness; it never
    waits on any downstream acknowledgment (no deadlock), and later
    failures never retroactively erase it;
  - `record_delivery` — discloses the actually supplied spans per bound
    artifact and every truncation, explicitly;
  - `record_receipt` — the receiver's separate acknowledgment, never
    inferred and never before delivery;
  - `record_use` — cited parts must lie within the supplied spans; an
    empty citation (a filename/hash alone) is never full consumption.
- `evidence_level` — none → availability (ready/delivered) → access
  (receipt) → use (cited parts). Causal influence is a different proof:
  the module has no function that mints it (asserted in tests).
- Issued-value pattern; foreign objects and out-of-order or repeated
  transitions refuse.

## Verification

- TDD: module absent first (collection error); 6 tests green.
- `ruff check` clean; full regression **3249 passed, 2 skipped**
  (was 3243).

## Notes

- The provider payload mapping half of §5 (TextPart/ImagePart/... to
  Claude blocks and Codex inputs) partially exists in gateway.py's typed
  parts; the adapter-side mapping remains with T042's Codex bridge.
