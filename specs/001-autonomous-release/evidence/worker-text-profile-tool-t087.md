# Evidence — T087: the worker's first real tool (`text_profile`) and `invoke_tool` over the artifact leg

- Date: 2026-09-18
- Task: the Continuation's "a real tool / `invoke_tool` over the leg" (T087). `invoke_tool` is
  tool-port-v1's call of a registered tool (extension-ports.md §3.2; terminal class C; effect
  from the ToolDefinition; the artifact-input list is the sole byte-in). The worker's table gains
  a real deterministic read-effect tool; control names it, streams exactly what it takes, and
  verifies what the reply claims against the facts it already holds. Contract amended:
  `contracts/extension-worker-probe.md` §2 (registry), §2b (the `tool` field, the invoke_tool
  output, the entry digests, the tool's contract and definitions, control's verification), §6.

## Frozen identities

```
f75b8b270811ac4d96df4433e292546d386eecd300977cfec9baaf73b56c5d99  app/workers/extension_execute_messages.py
14c9aeb498c2dbb9f719e0541b0ec09f7558cd6cb18c855c71d8adf7978ba09c  app/workers/extension_probe.py
8c9a2b0ee27e7a90351c4443dc86d4fde8e5b7db0a016c28d29d1e45a0a7a884  app/runtime/extension_attempt_transport.py
f65037cab6f1fdde4f886666187107cc1f4e913a4654b4b64961606354252858  app/tests/test_extension_execute_messages.py
f711478807e1a633120bef8a7671d808639dab1d15af9b0aa66f52b154ed5ea5  app/tests/test_extension_execute.py
7ef245406845624ea9929a10ddbef96d8690ad5099b787dc6a3eb3474af66838  app/tests/test_extension_attempt_transport.py
ab646f461b0e8f711bc76ec3eb8bf9b54f3623861af6d24d00d11ca10cf891c8  app/tests/test_extension_probe.py
200dfb0c17fcbbd8cea4bb5096ae71940dfc5f81152b32376c1eea64a6821622  app/tests/test_stage_observer.py
5a540d277226b9505a75292b6f49adfe643ab57f78818a6e5c3a638334287179  app/tests/test_deployment_consume.py
ddcc68004c688304d98e316cfbf85d6d6bb9b1193685e230e1f79b347874ac36  specs/001-autonomous-release/contracts/extension-worker-probe.md
```

(The identities of these files frozen in `worker-artifact-input-leg-t018-t087.md` are superseded.)

## What was built

- `app/workers/extension_probe.py`: `TEXT_PROFILE_ENTRY` — tool `text_profile` 1.0.0, effect
  `read`, exactly one `document_source` `text/plain` input (strict UTF-8), its argument and
  result schemas in code named by their digests; `_TOOLS = (TEXT_PROFILE_ENTRY,)`;
  `tool_descriptions()`. `_tool_contract_admits(request)` — the named tool and version are in the
  table and the declared inputs are exactly the tool's — consulted by the router's admission
  **before any artifact byte is read** and by the operation. `_text_profile(raw)` with stated
  definitions a non-Python worker can repeat under the same result-schema digest: bytes; code
  points (a BOM kept and counted); `\n`-terminated segments plus one final unterminated segment;
  runs between ASCII whitespace; the bytes' sha256. `_invoke_tool_operation`: a call outside the
  contract is `failed`/`validation_failed` with zero usage; bytes that are not a text are the
  tool's own terminal failure (`provider_terminal`, one tool call); success carries
  `{tool_id, version, result}` with one tool call and measured bytes. `registered_operations` is
  `["describe_tools", "invoke_tool", "status"]`.
- `app/workers/extension_execute_messages.py`: the request's `tool` (`ToolSelection`, required
  iff `invoke_tool`, refused otherwise; arguments have no wire grammar yet — the first tool takes
  none); the reply output for `invoke_tool` is `{tool_id, version, result}` with the result
  closed over the wire limits where it is built (a reply the parser would refuse is never sent);
  a `describe_tools` entry carries `argument_schema_sha256`/`result_schema_sha256` instead of
  references — a correction to the previous slice: a worker cannot reference control-side
  schema records.
- `app/runtime/extension_attempt_transport.py`: `build(..., tool=)` (required iff
  `invoke_tool`, validated through the wire grammar); a static mirror of the worker's table
  (`TOOL_INPUT_CONTRACTS`, `TOOL_EFFECTS`, pinned equal to the worker's entry by test) refuses at
  build a call declaring other inputs — never streamed into a worker that would refuse it before
  reading a byte, which control could only see mid-stream as an unknown outcome. Verification of
  a tool call: the reply's tool id and version are the ones control named; the result's digest and
  byte count agree with the streamed input control holds (the rest is the worker's claim, sealed
  as such); usage is exactly one tool call (none when refused before it ran: `validation_failed`,
  `permission_denied`), no model call, measured bytes; an in-process read-effect tool has no
  `outcome_unknown` or `cancelled` terminal (a dodge of the verification). The sealed artifact is
  the result; the ports contract's `ToolCall` record and `{tool_call_ref, result_ref}` stay
  control-side items (§6).

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 7 SHOULD, 4 NIT); sixteen probes over the real socket pair.
Verified clean: the registry order in every pin; the `tool`/`version` grammars; the request's
`tool` refused for queries and required for `invoke_tool`; the worker's reason codes and usage
claims match what control verifies on the happy path; the six refusal cases answer before any
byte is read; `describe_tools` with one entry is 297 B under its 3072 B bound; a 1 MiB input
profiles in milliseconds. Closures, RED-first:

1. MUST — control lost the worker's honest refusal: a call declaring the wrong inputs was refused
   by the worker at once, but control streamed regardless and met the reply mid-stream, so a
   definitive `validation_failed` became `outcome_unknown` → the static table mirror at build
   (pinned to the worker's entry); the RED test builds two inputs / a wrong role / a wrong media /
   none / another tool / another version and asserts the refusal at build.
2. MUST — control sealed a result for a tool it did not name (`other_tool 9.9.9` became the
   node's result) → the reply's tool id and version are checked against the named tool; pinned.
3. SHOULD — the result was trusted verbatim (a forged digest, a negative byte count) → the two
   facts control holds (the input's digest and size) are cross-checked; the rest is stated as the
   worker's claim (§2b); pinned with a forged digest.
4. SHOULD — the encode side bounded bytes only, so a handler result nested too deep, a long
   string or too many members encoded on the worker and was refused by control's parser →
   closed over the wire limits where the output is built; pinned (depth, string, members, a float).
5. SHOULD — the expected-tool-calls rule keyed only on `validation_failed` → "zero iff refused
   before the call (`validation_failed`, `permission_denied`), else one"; pinned (a `deadline`
   failure claiming no call is a mismatch; a `permission_denied` refusal settles as failed).
6. SHOULD — an explicit `outcome_unknown` or `cancelled` for a read-effect tool was accepted (a
   dodge of the usage verification) → refused for the control-measured operations; pinned; the
   class-C pass-through for external-effect tools listed open in §6.
7. SHOULD — the effect gate and grant check are only the entry's claim → stated open in §6 with
   the class-C terminals, the tool table learned from `describe_tools`, and the schema validation.
8. SHOULD — the tool's counts had Python-specific meanings (`splitlines`, Unicode `split`) →
   the definitions above, in code, contract and a test (CR, VT, U+2028 do not break lines; NBSP
   does not separate words; a BOM is a code point).
9. SHOULD — stale text (§2b "no registered operation takes inputs", the depth-6 justification,
   module docstrings, test comments) → corrected.
10. NIT — the parametrized refusal test's identical branches collapsed. 11. NIT — the admission
    seam dropped where the real tool admits the inputs (kept only for the three-input route, with
    its reason). 12. NIT — the tool-table byte bound's search result pinned (four maximal entries).
    13. NIT — the entry's roles are a tuple; `tool_descriptions()` produces the wire list.

## Verification

- TDD: RED retained — no `tool` field, no `tool=` at build, the registry pins at two operations,
  `describe_tools` over an empty table; GREEN after the grammar, the tool, the operation, the
  transport and the contract (three fixture adjustments on the way: the request field-set pin,
  a placeholder tool in control's declaration round trip, a reserved tool call in the bindings);
  the review's RED tests failed for their stated reasons (no `TOOL_INPUT_CONTRACTS`; the swapped
  tool sealed; the forged digest sealed; the nested result encoded; the uncalled failure accepted).
- Tests: execute messages **+2**, execute **+4** (incl. a six-case refusal set and the counts'
  definitions), transport **+7**; covering (messages, execute, transport) **78**; (probe, probe
  messages) **97**; (stage observer, deployment consume, deployment acceptance) **84**; (dispatch,
  runs API, artifact stream) **80** — in separate processes (the descriptor checks are
  order-sensitive across suites, pre-existing). Ruff: clean on every changed Python file.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- One tool, no arguments, no external effect; no `cancel`; no output artifacts from the worker;
  no `ToolCall` record, effect gate or grant check for a tool call (open, §6); the worker never
  touches the store; no model, tool or paid call beyond the in-process read. The live
  container/socket/worker run stays the host gate.
