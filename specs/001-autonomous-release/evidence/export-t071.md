# Evidence — T071 export: previewed scope, honest redaction, acyclic hashes

- Date: 2026-09-13
- Task: T071 [US7] snapshot preview/redaction/pseudonyms/rights/
  missing-evidence manifest and safe archive validation in
  app/operations/export.py; no self-referential archive hash
  (operations.md ExportRequest/Manifest/Receipt; FR-028/029).

## Frozen identities

```
e7e7b9788c0518f6000da301eafecd148428a08e5024e1a8d8a435c4597b6135  app/operations/export.py
c2d11451b960d115e7ed035f942d3b55c8a5e5916f8ce64aa83868a50c1b0f98  app/tests/test_export.py
```

## What was built

- `create_export_request` — a closed category set in which hidden
  reasoning and credentials DO NOT EXIST as selectable items; raw
  originals enter a bundle only through explicit `include_raw_refs`;
  redaction policy and author consent are bound refs.
- `build_export_manifest` —
  - `source_sha256` exists ONLY under explicit `source_hash_included`
    (exported-bytes hash and original-source hash stay distinct; absence
    stays absence);
  - raw content-mode items refuse when the request selected no raw refs;
  - missing-evidence reasons are the closed seven (not_selected /
    redacted / deleted / unavailable / not_recorded / access_denied /
    rights_restricted) — redaction, non-selection and real record gaps
    are never one error;
  - archive paths are restricted relative paths (traversal, absolute,
    drive, NUL and backslash forms refuse via the shared
    `carries_host_path`);
  - a supplied secret canary appearing ANYWHERE in the canonical manifest
    refuses the whole build;
  - a per-kind redaction summary is derived from the items themselves.
- `seal_export` — the receipt is a record OUTSIDE the archive binding
  `manifest_sha256` + `bundle_sha256`; the manifest's own dict contains no
  bundle hash by construction (no circular hash structure), asserted in
  tests.
- Nothing transmits anything anywhere (FR-028: 자동 전송 없음).

## Verification

- TDD: module absent first (collection error); 11 tests green.
- `ruff check` clean; full regression **3307 passed, 2 skipped**
  (was 3296).

## Notes

- The staging state machine (selecting→preview_ready→generating→
  validating→ready) and the actual archive writer/validator are the
  storage/worker half; pseudonym-map generation for events.jsonl rides
  the event-export seam (T068/T073/T074).
