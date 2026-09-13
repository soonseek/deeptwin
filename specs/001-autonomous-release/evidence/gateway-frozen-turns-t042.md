# Evidence — T042 (part): frozen turns, profile allowlists, output authority

- Date: 2026-09-13
- Task: T042 [US3] partial — provider-neutral multimodal frozen turns and
  the actual-page/image/table marker contracts in app/runtime/gateway.py
  and app/tests/test_model_payloads.py (runtime.md §1, R04–R06). The Codex
  environmentless tool-step bridge (app/adapters/codex_step.py) remains.

## Frozen identities

```
12da69cc6e120e39bea39a977b3fd563478b2c6364d156b9af9457ba4150adce  app/runtime/gateway.py
3c91404fcabd5026620245ce69f100cb847d81467557a38a344324324e0597fb  app/tests/test_model_payloads.py
```

## What was built

- `FrozenTurn` (issued) — one completely bound model step:
  work/environment/node/execution/attempt identity, provider path (the
  three real paths only — no fallback path exists), catalog/model/effort,
  instruction-profile digest, allowlisted typed inputs, granted tools,
  output schema id, runtime-profile qualification ref, bounded deadline,
  budget and consent refs.
- **Profile input allowlists** — eight profiles, each with the exact ref
  kinds its inputs may carry (understanding never sees operational
  artifacts; the change-compiler input never sees own_alternative
  material; the critic boundary carries no domain refs at all). Inputs are
  constructed FROM the allowlist, never blacklisted out of an arbitrary
  object. Only `execution-model-step` may carry tools — a no-tool profile
  stays no-tool.
- **Marker contracts (R04–R06)** — non-text parts (image/page/table) must
  carry an explicit marker binding them to their artifact ref; extraction
  omissions are declared per part, bounded and preserved — never hidden.
- `validate_step_output` — output parsing never mints authority:
  `capabilities`/`grants`/`permissions`/`paths` keys refuse outright; tool
  requests exist only for the execution profile and only for tools this
  exact turn granted; every argument string is scanned recursively and
  absolute/parent/home host paths refuse; final-artifact specs are exact
  bounded slot/media pairs; unknown kinds refuse.

## Verification

- TDD: module absent first (collection error); 6 tests green (binding +
  issuance, allowlists, tool-profile exclusivity, markers/omissions,
  capability/path refusal, no-tool profile refusing tool requests).
- `ruff check` clean; full regression **3243 passed, 2 skipped**
  (was 3237).

## Notes

- Remaining for T042: the Codex environmentless tool-step bridge
  (adapter-side), and wiring FrozenTurn into the actual provider adapters
  (ClaudeAPIAdapter already exists with its own stream contract).
