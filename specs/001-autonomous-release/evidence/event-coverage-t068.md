# Evidence — T068: aggregate event coverage closed

- Date: 2026-09-13
- Task: T068 [US7] audit and close aggregate event coverage for every OPS
  §4.2 category, including the explicitly named lifecycles; public
  projections expose no record handle/secret/provider raw body (FR-027).

## Frozen identities

```
1e7637e66da79589c9f3dd199563f9ee38dfd0239c4c8a5e79041d945bc383c9  app/operations/audit.py
08013867e6aadccb5a09d2bdcb5bf60f816ea6f541b9c8278cb9e49090e98976  app/domain/events.py
ff850eb10d10c3c5b441b2016d8d6d8edd9d358a4ed1fc22b40564e247f4df23  app/tests/test_event_coverage.py
```

## What was built

- **Closed the gaps** — events.py gains the registrations T068 names:
  `deployment.request_prepared/request_cancelled/receipt_committed`,
  `auth.recovery_started/completed/failed`,
  `credential.retired/cleanup_completed/erasure_confirmed/erasure_failed`,
  `managed_login.started/completed/cancelled/failed`,
  `speech.interrupted/raw_unavailable` (85 → 101 registered types); the
  exported `schemas/v1/event-metadata.schema.json` was regenerated
  deterministically through the existing writer.
- **The audit itself** — `REQUIRED_COVERAGE` maps all 19 §4.2 requirement
  groups to the concrete event types that satisfy them;
  `audit_event_coverage` returns every missing requirement instead of
  passing silently (verified by gutting a category in the test).
- **Secret-free projections** — the registry is an allowlist of counts,
  flags and closed enums ONLY (no free-text field exists anywhere, so no
  handle/secret/raw body can enter an event; boolean presence flags like
  `key_present` carry no content); `public_projection` validates payloads
  against the allowlist and refuses unknown fields and out-of-enum values
  outright.

## Verification

- TDD: modules/tests written RED-first (audit module absent, lifecycle
  events unregistered), then green; the schema-export regression caught
  the registry change and the export was regenerated.
- `ruff check` clean on the new files; events.py's 3 pre-existing lint
  findings (import order, the deliberate `del _registry` pattern) were
  verified present at HEAD and left as-is, matching the server.py
  precedent.
- Full regression **3320 passed, 2 skipped** (was 3314).

## Process note

- During the pre-existence check a shared-stash rule violation occurred
  (a path stash was pushed and the working edits briefly reverted); the
  entry was recovered by SHA (`git stash apply <sha>` + verified content
  + drop) and the stack left clean. `git show HEAD:path` alone was always
  sufficient — recorded as the standing method.
