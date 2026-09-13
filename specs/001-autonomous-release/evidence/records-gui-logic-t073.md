# Evidence — T073 (logic half): records GUI logic and consent binding

- Date: 2026-09-13
- Task: T073 [US7] logic slice — app/static/records.mjs: anywhere-
  accessible log/export/backup/retention sections, export consent bound
  to the ACTUAL previewed content, deletion bound to its exact preview,
  closed backup key modes with the recovery secret never stored, and no
  mandatory final export step (UX-AC08).

## Frozen identities

```
23b4913b08d9adb6e20557070b90296b64c0d3560a9f625298dbf24150feb8c3  app/static/records.mjs
05c13d158f1f64dfaba21d4d54bb05de3de778937429b9d6940214d288a7b9fd  app/tests/records.test.mjs
54854fcf83d4faa9df568eab3e400c1147514b974cc56eecf1892a2dabeed2c8  app/tests/test_records_contract_mirror.py
```

## What was built

- **recordsRoutes** — logs/export/backup/retention as plain routes,
  every one `available: "everywhere"` with no prerequisite field: the
  GUI never sequences the records sections.
- **exportRequestPayload** — mirrors `create_export_request`: 1..8
  unique categories from the closed set (hidden_reasoning/credentials
  are not selectable at all), ≤64 raw-inclusion refs, canonical
  UUID/UTC-stamp validation, sorted categories, exact server key set.
- **previewSummary / exportConsent** — the consent screen must hold the
  ACTUAL preview: per-category item counts plus every omission with a
  closed-set reason; consent requires `confirmed: true` AND the exact
  `preview_sha` of what was shown — a stale or absent preview refuses.
- **deletionRequestPayload** — binds `preview_sha` + `ledger_revision`
  from the deletion preview, closed `DELETION_REASONS`, duplicate ids
  refused client-side too.
- **backupSettingsPayload** — closed key modes
  (`instance_backup_key|portable_recovery`); portable requires the
  one-shot masked input to have happened; ANY unexpected field
  (secret/recoverySecret/identity/…) refuses — settings never store a
  recovery secret under any name.
- **completionGate** — UX-AC08: `{complete: true, exportRequired:
  false, exportOffered: true}` regardless of whether anything was
  exported.
- **Drift protection** — test_records_contract_mirror.py parses the
  .mjs constant lists and compares them set-for-set against
  `app.operations.export.EXPORT_CATEGORIES`/`MISSING_REASONS`,
  `app.operations.retention.DELETION_REASONS` and the manifest
  key-mode pair, so the GUI copy cannot drift from the server contract
  inside the Python regression.

## Verification (TDD)

- RED: records.mjs absent (ERR_MODULE_NOT_FOUND), then GREEN.
- `node --test app/tests/records.test.mjs`: **8/8 pass**; unit .mjs
  set (records+settings+chat): **17/17 pass**.
- Python: mirror tests 4/4; `ruff check` clean; full regression
  **3421 passed, 2 skipped** (was 3417).
- The full Playwright browser .mjs suite (pre-existing, does not import
  records.mjs) was launched with the recorded baseline environment and
  runs long; its outcome is environmental qualification independent of
  this pure-logic slice.

## Notes

- T073 stays `[ ]`: the DOM wiring of these sections into
  index.html/app.mjs/settings.mjs and the T074 browser-records test
  arc remain.
