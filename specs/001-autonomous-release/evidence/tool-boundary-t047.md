# Evidence — T047 (core): tool dispatcher boundary

- Date: 2026-09-13
- Task: T047 [US3] partial — schema-registered dispatcher, grants, effect
  approvals and replay policies in app/runtime/tools.py; argument
  ref-smuggling and host-path injection denial in
  app/tests/test_tool_boundary.py (runtime.md §6, FR-014/FR-032). The
  symlink/race/renderer/egress halves are runtime/adapter concerns
  (T043/T044) and remain.

## Frozen identities

```
c1e6f2ff2435889532d936584e9a2f101d57eee50861d984a96652235119a7e3  app/runtime/tools.py
8396da9beb8fdfa981fc3d928a19224c0b3e0691c13f5343d03c5076f885d5e7  app/tests/test_tool_boundary.py
```

## What was built

- **Closed registry** — `register_tool` is the only path that adds a
  tool; an id/version registers exactly once; every definition carries
  argument keys/types, result schema id, effect class
  (read/write/external/irreversible), the required grant, bounded
  filesystem/network scopes (path-free), timeout and byte caps,
  idempotency, replay policy, implementation hash and qualification ref.
  An unregistered tool or unknown version is UNSUPPORTED at dispatch —
  never interpreted from anything a model outputs.
- **Argument discipline** — arguments must match the declared keys and
  types exactly (nothing widens the profile at dispatch); `*_ref` keys
  are unregistrable and ref-valued arguments refuse — the ordered
  artifact-input bindings are the sole byte-input authority; every
  string argument refuses absolute/parent/home host paths.
- **Grants and effects** — the presented grant must equal the
  definition's required grant; external and irreversible effects require
  an explicit `action_approval`; read/write tools refuse a superfluous
  approval.
- **Replay policy is authoritative** — an already-dispatched request
  never replays unless the tool is `dedup_by_request`, in which case the
  ORIGINAL envelope returns; an unknown external outcome holds the
  request and blocks every retry until `record_outcome` reconciles it;
  final outcomes never change.
- Issued values throughout; the registry is an immutable value (storage
  owns single-writer transactions, as with the growth and design stores).

## Verification

- TDD: module absent first (collection error); 7 tests green.
- `ruff check` clean; full regression **3256 passed, 2 skipped**
  (was 3249).
