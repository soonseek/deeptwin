# Evidence — T044 (partial): bounded document creation with render inspection

- Date: 2026-09-13
- Task: T044 [US3] partial — bounded declarative DOCX/CSV/JSON creation
  and safe format validation in app/adapters/documents.py with ACTUAL
  render inspection, never file-exists-only checks (SC-004; runtime.md §6
  artifact tools). PDF and image rendering are explicitly deferred: the
  needed libraries (reportlab/PIL) are absent and the dependency manifest
  (pyproject.toml) lives outside this worktree — the same dependency
  boundary that defers T040's langgraph adapter.

## Frozen identities

```
394633867f86a6817f7c87bd23d8fc35c0c9e4f16c87fcf4e8d4ab93ab121806  app/adapters/documents.py
e9be088d2612712d13ddd6f459abcd65261ceb51e5f0e068331ec63f62599dc5  app/tests/test_document_tools.py
```

## What was built

- `render_docx` — bounded declarative spec (title, ≤500 paragraphs, ≤32
  tables of ≤100×50 rectangular cells, per-text byte bounds, NUL refusal)
  rendered via python-docx, then **reopened**: every declared table cell
  and paragraph is read back from the produced bytes and compared; the
  report's paragraph/table counts, inspected cells, byte length and
  SHA-256 all come from the produced file, never from intent.
- `render_csv` — formula-looking values (`=`, `+`, `-`, `@`) remain data
  by default (round-trip verified by reopening); the optional
  safe-spreadsheet export prefixes an apostrophe and records EVERY
  transformation as (row, column, kind).
- `render_json` — bounded depth (32), finite numbers only, canonical
  UTF-8, parse-back equality verified.
- `validate_format` — sniffs real bytes: a DOCX must be a ZIP with
  `[Content_Types].xml` and a `word/` part (a plain ZIP refuses); CSV must
  be NUL-free UTF-8; JSON must parse; unsupported formats (pdf, images)
  refuse explicitly — never silently accepted.
- Nothing fetches URLs or resolves external references.

## Verification

- TDD: module absent first (collection error); 6 tests green, including
  reopening the produced DOCX with python-docx inside the test and
  reading the declared Korean paragraph back out of the real file.
- `ruff check` clean; full regression **3289 passed, 2 skipped**
  (was 3283).
