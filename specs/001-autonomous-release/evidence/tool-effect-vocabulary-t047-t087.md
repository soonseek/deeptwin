# Evidence — one effect vocabulary for tools (T047/T087)

- Date: 2026-09-19
- Task: the first step of the Continuation's "ToolDefinition-backed gate (T087; the tool
  boundary's four-class effect vocabulary must first be reconciled with the ports contract's
  seven)". extension-ports.md: `effect-class` is exactly `none | read | write_reversible |
  external_reversible | external_irreversible | instance_critical_secret |
  instance_critical_storage`, families N/L/X, the external family requires an explicit
  approval; runtime.md §6: the ToolDefinition's effect class is authoritative. The ledger's
  ToolCall and the extension transport's gate already used the seven; the T047 in-memory tool
  boundary kept `read | write | external | irreversible`.

## Frozen identities

```
1ab4f2d653e38b480f62cae1f37dd7c6215d1b9a014ad32f8cc45669fdde90f4  app/runtime/tools.py
40d951312c1dd28caad5804a71000b006f87a37c822cdc97f29f9f61cbad3995  app/tests/test_tool_boundary.py
67cdfc040337347cb651290151f8286614c52a6a7c637ac5b6ed2fa68488be4a  app/tests/test_us3_audit_findings.py
```

(The identities frozen in the T047 core-slice evidence and the US3 audit evidence are
superseded.)

## What was built

- `app/runtime/tools.py`: `EFFECT_CLASSES` is the ports contract's closed set, taken from
  `app/extensions/port_contracts.py` (the runtime already imports that module; it imports
  only the domain's references); `APPROVAL_EFFECTS` is the ports' external family (X),
  pinned equal to the ledger's `TOOL_APPROVAL_EFFECTS`, and the dispatch's approval rule
  reads it; the earlier four names are refused at registration (a legacy `external` never
  stated reversibility — mapping it to either sibling would decide the stronger fact on the
  caller's behalf — and a second spelling would shadow the closed set; no production code
  registers a tool, so nothing migrates); a non-string effect is refused as a boundary error;
  `record_outcome` refuses an `unknown` outcome for an N-family tool (the ports forbid an
  unknown effect there: nothing external could be in doubt, so nothing is held). The five test
  registrations moved to the ports names.
- `specs/001-autonomous-release/contracts/runtime.md`: the `tool-port-v1` row names the ports'
  effect classes instead of the four.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 3 SHOULD, NITs). Verified clean: the family never
changes replay or the unknown-outcome hold in the boundary (approval is the only
family-keyed branch); no consumer compared against the legacy strings; the import direction
adds no cycle; the ledger's sets are literals so the equality pin is meaningful. Closures,
RED-first:

1. MUST — the first draft mapped a legacy `external` to `external_reversible`: a silent
   downgrade of the class the next slice will carry into the compilation authority → the
   legacy names are refused outright; pinned (`write`, `external`, `irreversible`, an
   uppercase name, a list, `None`, an integer).
2. MUST — accepting two vocabularies widened the closed registry (ten spellings for seven
   classes, consulted before the closed set) with no production caller → the compatibility
   map deleted; the test registrations migrated; pinned (`LEGACY_EFFECT_CLASSES` absent).
3. SHOULD — an N-family tool (`none`, `read`) accepted an `unknown` outcome the ports forbid,
   and was then held → refused; pinned for both.
4. SHOULD — `none` for a tool is canon-consistent (the ports allow all seven for
   `invoke_tool`): kept.
5. SHOULD — runtime.md's tool-port row still listed the four → corrected. Recorded, open:
   `app/domain/events.py` carries a third vocabulary for the `tool.requested` event
   (`read | local_write | external_write`); the moment an envelope's class is emitted there the
   mismatch bites.
6. NIT — one approval name; the exports carry it; the boundary and test headers reworded
   (`replay="never"`, not "irreversible", is what never re-dispatches).

## Verification

- TDD: RED retained — the vocabulary pins and the migrated assertion failed against the four
  names; GREEN after the ports set and the approval family; the review's RED tests (the legacy
  names refused; the N-family unknown refused) failed for their stated reasons.
- Tests: boundary **+4** (the vocabulary, every X-family effect requiring an approval, no other
  effect taking one, the N-family unknown refused), one audit registration migrated; (boundary,
  audit) **39**; (ledger, transport, graph contract) **147**. Ruff: clean on the changed files.
- Full regression: **6351 passed, 2 skipped** (Linux-only), 369 subtests, 17m04s.

## Boundaries kept

- The compilation authority's trusted tool definitions still carry no effect class, and the
  transport's mirror is still the effect source (the next slice); the `tool.requested` event
  vocabulary is open; no model, tool or paid call.
