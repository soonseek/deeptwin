# Evidence — T059 growth firewall adversarial tests

- Date: 2026-09-13
- Task: T059 [US5] cross-purpose retrieval/prompt/derived-input adversarial
  tests including hidden heldout and sensitive personal-profile rejection
  (G-05, OPS-AC09; growth.md §4, runtime.md §8).

## Frozen identities

```
10ece0293953dfdc6b925eacfeec3846b1b1e007884a8cf92f4155eddf67c46f  app/tests/test_growth_firewall.py
7d681324e7ae659cb7dc0985d0d5a6a74b610592e9ec37a4ee12cd130434ac6b  app/runtime/compiler.py
9ba2dcd56978e0837d6425637d75715d62206a16f9354beb522db10b5c5c6252  app/runtime/memory.py
```

## Firewalls exercised (8 tests, TDD)

- **Cross-purpose fencing** — a tuning-purpose knowledge entry is never
  supplied to an operation query (explicit `purpose_mismatch` gap), and vice
  versa (pinned existing behavior).
- **Zero-width evasion (NEW, was RED)** — forbidden spans carrying
  zero-width space (U+200B), word joiner (U+2060) or BOM are still caught in
  BOTH policy compilers: `_normalized` now NFKC-folds and strips Unicode
  format (Cf) characters before span comparison. This closes the
  zero-width-space evasion the US6 batch audit recorded as a known limit.
- **Compatibility-variant evasion (NEW, was RED)** — fullwidth compatibility
  text (ＸＸＸ) normalizes onto the forbidden ASCII span and is refused.
- **Judge/heldout internals (NEW, was RED)** — `evaluation_dataset` and
  `rubric` refs are now forbidden policy-compilation provenance in
  app/runtime/memory.py (the knowledge registry's whitelist already refused
  them); candidate/tuning surfaces never touch sealed answers or judge
  material.
- **Hidden heldout** — every peek path (tuning, candidate authoring, report
  review) burns the sealed dataset: subsequent `run_validation` refuses an
  unseen claim and the burned manifest cannot re-enter under a fresh name
  (pinned).
- **Personal-profile rejection** — diagnosis accepts only the five behavior
  hypothesis families ("user_philosophy_profile"/"personality"/
  "political_alignment"/"moral_grade" are refused), and the knowledge
  registry's closed purpose set refuses a "profiling" purpose (pinned;
  growth.md §4: 사용자 철학·성격·정치/종교·도덕 등급 프로필은 만들지 않는다).

## Verification

- TDD: the three NEW behaviors observed failing first (4 RED runs), then
  green after the `_normalized` strengthening and the forbidden-kind
  extension; the rest pin existing firewall behavior.
- `ruff check` clean (2 autofixes in the test file).
- Full regression `python -m pytest app/tests deploy/tests -q` —
  **3188 passed, 2 skipped, 369 subtests passed** (was 3180).

## Notes

- Remaining known limit: punctuation-insertion inside a span (e.g. added
  commas) still evades verbatim matching; the modules document
  whitespace/format-normalized *verbatim* matching as their scope — semantic
  paraphrase detection is out of scope for this layer by design.
- US5 remaining: T060 inquiry UI (browser).
