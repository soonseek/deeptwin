# Evidence — adversarial audit of the US3 batch (scheduling, gateway,
# handoffs, tools)

- Date: 2026-09-13
- Verdict: **REJECT** — 4 high, 8 medium, 4 low; every code-level finding
  closed with regression tests (`app/tests/test_us3_audit_findings.py`,
  22 tests; RED evidenced by the auditor's reproduction scripts).

## Frozen identities (post-fix)

```
f94afbad8b1b683a32d6fce50eb804c49b8f132d2a3fd9095cb1da0ae0fcb832  app/runtime/gateway.py
97c9c33ef27b15be442aa182f5316db48c6f9b50d7d054b38a70f125c2e8f8ef  app/runtime/tools.py
11bca050a35d8fe9b9c1cc0442373a2aae0bd8c8c9cc78fcd24a182c8e6b0e19  app/runtime/scheduling_state.py
e17caca585ebb3efef66a7a8d200d8ff4a21d6d34d45738cfc266aff1e3061a3  app/services/handoffs.py
7929cd700750ed028d3fe5674766a497754f1d2afa5d119897e0218ab3b5e56f  app/tests/test_us3_audit_findings.py
```

## Findings fixed

- **F1 (high)** Dedup replay bypassed all validation — a reused request id
  now validates the retry fully and must equal the stored dispatch (tool,
  version, arguments, grant, approval); anything else refuses as
  laundering.
- **F2 (high)** The any_success winner re-pointed after the successor was
  scheduled — the first APPLIED success now wins permanently; simultaneous
  observations ingest through `apply_simultaneous_results`, which realizes
  the frozen branch-order tie-break BEFORE the single decision.
- **F3 (high)** Collect inputs mutated after completion — a completed join
  is sealed: later results are evidence only.
- **F4 (high)** Host-path regex evasion (backslash, drive letters, URL
  schemes, percent-encoding, UNC, trailing `..`, NUL, poisoned dict keys)
  — replaced with `carries_host_path` (normalizing, percent-decoding,
  segment-checking), applied to values AND keys in the gateway and to tool
  arguments and filesystem scopes.
- **F5** Activation ids are canonical-JSON hashes — delimiter-proof.
- **F6/F7** Admitted step outputs are detached copies; branch-result
  artifact refs are validated EntityRefs (or None) and evidence entries
  are rebuilt, so post-admit caller mutation reaches nothing.
- **F8** Collect exposes `satisfied` — completing below the explicit
  minimum is never silent (all_selected likewise reports satisfaction).
- **F9** Nesting depth bounded (32) — hostile depth is a typed refusal,
  not a RecursionError; non-finite floats and unbounded ints refuse.
- **F10** Final-artifact slots/media are host-path scanned.
- **F11** NodeVisit/Attempt carry issuer tokens and consumers require
  them — a bare shell no longer escapes as AttributeError or mints
  attempts.
- **F12** The DispatchEnvelope records the matched grant and the effect
  approval that authorized the dispatch.
- **F13** Delivery requires every bound artifact to be supplied or
  explicitly truncated (structured truncation entries with indexes) —
  nothing vanishes silently.
- **F14** Argument key names are bounded at registration.
- **F15/F16** documented: cited parts echo supplied spans exactly (subset
  claims belong to a structured-span layer); `blocked_dependants` maps are
  graph-derived data owned by the compiler/ledger seam; the gateway-grant→
  dispatcher binding remains a caller seam.

## Auditor's verified negatives (retained)

Exact-set output checks, no-tool profile refusals, handoff state machine
single-shots, unknown-outcome holds, final-outcome immutability,
issued-value replace failures, and the documented storage seams all held.

## Verification

- 22 regression tests (RED = auditor's reproduction scripts
  audit_{sched,gateway,tools_handoffs}.py); legacy suites updated
  (tie-break via batch ingestion, structured truncations, satisfied flag).
- `ruff check` clean; full regression **3278 passed, 2 skipped**
  (was 3256).
