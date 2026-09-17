# Evidence — Task 25 slice 1b: closed worker-private stage probe messages

- Date: 2026-09-18
- Task: Task 25 (worker-private probe channel; prerequisite for Task 24), slice 1b — pure
  probe message codecs. Contract: `contracts/extension-worker-probe.md` §2/§2a (drafted from
  the 2026-09-16 proposal, independent specification review ACCEPT WITH CHANGES folded in,
  commit 93321da). Plan entry: `resumption-plan.md` "### Task 25", bullet 1b.
- Reuses: `app.domain.wire.parse_json_object`/`WireLimits`, `app.domain.refs.canonical_json`,
  `broker._identifier`, `PORT_CONTRACTS["tool-port-v1"].operations`.

## Frozen identities

```
ce639fb74ca3b6be47252060c7290b405a735b6c224d99d7be56f0585a369d1b  app/workers/extension_probe_messages.py
8cca0fa654c5f8c01e75ae325535fd300a87759fddb92393d8f2ea75e53dcfe3  app/tests/test_extension_probe_messages.py
```

## What was built

- `app/workers/extension_probe_messages.py` (new; no existing production file changed):
  `ProbeRequest`, `ProbeComponent`, `ProbeRuntime`, `ProbeReply` (frozen dataclasses of
  validated scalars; the nonce travels as 32 raw bytes; digests and nonces are excluded from
  `repr`/`str` so no log line leaks them), `encode_probe_request` / `parse_probe_request`,
  `encode_probe_reply` / `parse_probe_reply`, and the single closed `ProbeMessageError`
  ("invalid probe message", never reflecting input; copy/pickle-safe).
- Grammar exactly as §2: payload caps 1024 B / 4096 B pre-envelope; `WireLimits(max_depth=4,
  max_items=128, max_members=16, max_string_bytes=128, max_integer=2**32-1)` with root depth 1;
  top level closed by `parse_json_object`, nested `component`/`runtime` closed by the codec;
  `canonical_json(value) == raw` recheck refuses whitespace, key order, escapes, trailing bytes,
  concatenation; lowercase hex64 digests; 43-char unpadded base64url nonce with canonical
  trailing bits (padding, standard alphabet, 42/44 chars, stray bits refused); BrokerId grammar
  for `service_identity`; `UInt32` 1..2^32-1 (0, bool, float, text refused);
  `platform ∈ {linux/amd64, linux/arm64}`; `port_contract_version` exactly `tool-port-v1`;
  `registered_operations` a codepoint-sorted unique subset of the tool port's operations,
  `[]` allowed. Encoders are keyword-only, take plain scalars (never a metadata reading,
  channel spec or registry object), refuse every out-of-grammar value before encoding, and
  `encode → parse → encode` is byte-identical. Parsers accept `bytes` only.

## Review (independent, adversarial) and closures

Verdict: ACCEPT; folded in RED-first before commit:

1. SHOULD — `port_contract_version` compared before type-checking, so an object whose
   `__ne__` raises escaped as `TypeError` → type check first; test with a `Weird` object on
   every encoder field.
2. SHOULD — default dataclass `repr` printed the nonce and digests → `field(repr=False)`;
   test asserts neither `repr` nor `str` contains them.
3. SHOULD — the URL-safe alphabet was only exercised by a random nonce (≈75 % per run) →
   deterministic `bytes([0xfb, 0xff]) * 16` case renders `-`/`_`, round-trips, and the
   standard-alphabet rendering of the same bytes is refused; positive boundaries `uid ∈ {1,
   2^32-1}` and a 64-char service identity.
4. NIT — `ProbeMessageError` not copy/pickle-safe → accepts and drops re-invocation args.
5. NIT — `_parse` wrapped its own error / unreachable `TypeError` → restructured; `_encode`
   guards `canonical_json` explicitly.
- Reviewer-verified conforming: depth accounting exactly consumed (a `max_depth=3` limit
  refuses a non-empty operations list), duplicate keys refused at every level, no exception
  other than `ProbeMessageError` reachable from either parser across 1000-deep nesting, lone
  surrogates, overlong UTF-8 and member bombs; the import boundary
  (`app.workers → app.extensions.port_contracts`) has precedent and no cycle.

## Verification

- TDD: RED retained — `ModuleNotFoundError: No module named
  'app.workers.extension_probe_messages'` / `1 error in 0.14s`; review closures RED first
  (repr leak assertion failed), then GREEN. Three initial test-case errors were the tests'
  own (a nonce whose standard-alphabet rendering equals the url-safe one, a float the test
  helper could not canonicalise, a legal identifier used as a negative) and were corrected as
  such, not by weakening the codec.
- Covering: **69 passed** (`test_extension_probe_messages.py`); with the channel and core
  import-boundary suites **143 passed**. Ruff check/format clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- Inert values only: no I/O, handshake, listener, fence, socket, service, observation,
  authentication or admission (slices 2a–3 remain); no image/packaging/registry claim; no GUI;
  the actual worker image and container/socket runtime are Docker/colima host authority.
