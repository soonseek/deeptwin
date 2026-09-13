# Evidence — adversarial audit of the operations batch (retention, export,
# audit, documents, artifacts)

- Date: 2026-09-13
- Verdict: **REJECT** — 2 high, 6 medium, 5 low; every code finding closed
  with regressions (`app/tests/test_ops_audit_findings.py`, 14 tests; RED
  = auditor's reproduction scripts audit_repro{,_docs}.py). Modules
  audit.py and artifacts.py survived clean (nits only).

## Frozen identities (post-fix)

```
2257f10337fc8d3d7deb3265c41aac0568b6805a52b471c5beb0a9cd61bb7769  app/operations/export.py
92e3a8b091d7f5c3aa8f2beafe79114bec896715d5bb51784bce62c678a5172d  app/operations/retention.py
3722e9463afbdd10ca544056f7a50cf1f03b1bcf3b8ea51aa844b78af9042554  app/adapters/documents.py
0fbc8b21f908dc7db98863dea13da10f25c0680d0c2c9437391ad50591d967de  app/tests/test_ops_audit_findings.py
```

## Findings fixed

- **F1 (high)** The canary scan was JSON-escape blind — secrets carrying
  quotes, backslashes or newlines (PEM keys!) bypassed the refusal → the
  scan now walks the DECODED field strings of the manifest dict (keys and
  values, recursively) with the encoded payload kept as a second belt.
- **F2 (high)** Tombstones lacked the contract's mandated fields and
  dropped the validated actor evidence → `Tombstone` now carries
  `deleted_at`, `deletion_request_id`, `reason_code` (closed set) and
  `evidence_ref`; `delete_items` requires all three as parameters.
- **F3** Duplicate ids inflated the human-shown deletion preview →
  refused.
- **F4** "LRU" was creation-order eviction — the docstring and comment now
  state the creation-order approximation honestly and name the access
  layer as the owner of real usage recency.
- **F5** The manifest omitted six contract header fields → `bundle_id`
  (UUIDv5 of request+created_at), `created_at`, `app_release`,
  `export_policy_ref` (the request's redaction policy, now carried),
  `pseudonym_map_scope` and `reproduction_limits` are all present;
  the receipt binds `manifest.bundle_id`.
- **F6** Colliding `relative_path` and duplicate `export_id` → both
  unique within a manifest.
- **F7** Tab/CR-prefixed formulas missed the safe-spreadsheet escaping →
  prefixes extended.
- **F8** `validate_format` had no hostile-file bounds → 64MiB input cap
  before reading and a 10k central-directory entry cap before parsing.
- **F9** C0 control characters leaked raw python-docx ValueErrors → all
  C0 controls except \n and \t refuse at `_text` time (CSV cells keep
  their own NUL-only rule so tab/CR data can be escaped, not refused).
- **F10** Linked export ids bounded (1..128); canaries type-checked.
- **F11** `bundle_id` no longer aliases `request_id` (see F5).
- **F12** The reopened title is verified (`title_verified` in the render
  report).
- **F13** NUL inside JSON strings now refuses in both render and
  validate (the parsed object is re-walked); the render output path is
  documented as the caller's authority.

## Auditor's verified negatives (retained)

Non-ASCII canaries detected (ensure_ascii=False), retention two-step and
revision staleness held, raw-inclusion and source-hash discipline held,
path traversal refused through triple-decode, audit registry genuinely
free-text-free, artifacts module fully clean, and every list input is
detached at issue time.

## Verification

- 14 regression tests (RED = auditor reproductions); legacy suites
  updated to the new delete/build signatures. One test-authoring slip
  (a literal NUL byte written into test source) was caught by the Python
  compiler and fixed to an escape sequence.
- `ruff check` clean; full regression **3334 passed, 2 skipped**
  (was 3320).
