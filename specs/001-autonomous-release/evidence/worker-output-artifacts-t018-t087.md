# Evidence — T018/T087: worker-returned output artifacts (the reverse leg) and `text_normalize`

- Date: 2026-09-18
- Task: the Continuation's "worker-returned output artifacts". The bounded stream now carries a
  tool's output artifacts back to control (runtime.md L350-355: the stream is the only byte
  route; "produced files are sealed artifact refs"; extension-ports.md: every produced ref is
  sealed before `succeeded`, artifacts are `[]` for every other terminal). The consumer is a
  second real tool, `text_normalize`, whose derived text is its output artifact. Contract
  amended: `contracts/extension-worker-probe.md` §2 (registry), §2b (the invoke_tool output's
  bindings, the reverse leg, the second tool, control's verification), §6 (open items).
- **Correction to the previous slice's record:** `worker-text-profile-tool-t087.md` states that
  its contract closures (the tool's definitions, control's verification sentence, the depth
  wording, the stale "no registered operation takes inputs" text, the mirror-at-build sentence)
  were folded in; the patch that carried them aborted before writing the contract, so they were
  not in commit `a653526`. They are landed by this slice; the code side of those closures was
  in that commit as evidenced. The frozen contract identity below supersedes that file's.

## Frozen identities

```
67cbf541abe37fdbb600b2dbc552e0b3eb0aa9c92bdd180fafc21a55ab109a5b  app/workers/extension_execute_messages.py
b85b029dc62cf652a5f8f151e2b559fef48cb9298676004d07e43af1d575ddcc  app/workers/extension_probe.py
da6d7f8bf14596137f8a8eb8633331e2ff4385d6a84b13c7ed706021e3bc4ac4  app/runtime/extension_attempt_transport.py
d7f705266303541091e02dd7312fa4ce240d5847ce12f96ff2470d985ddc261f  app/tests/test_extension_execute_messages.py
0126394706f6c0d8602a88dec5772278f944d4e6361e57c8e3def454f83b8cd8  app/tests/test_extension_execute.py
5eacf101790cf7475094c07afa6974ba377f09d2aba8035c3daacbe6d209d439  app/tests/test_extension_attempt_transport.py
6bb2492d505c96a9307f48e89ef9c87630e577fb4549b6c84e19ee4e4e72a65b  specs/001-autonomous-release/contracts/extension-worker-probe.md
```

(The identities of these files frozen in `worker-text-profile-tool-t087.md` are superseded.)

## What was built

- `app/workers/extension_execute_messages.py`: the `invoke_tool` output is `{tool_id, version,
  result, artifacts}` — `artifacts` binds each output artifact (≤ 8: ordinal, role, media type,
  exact size, digest; the same grammar as the declared inputs, the exact ordered sequence, sizes
  and their sum ≤ 1 MiB).
- `app/workers/extension_probe.py`: `TEXT_NORMALIZE_ENTRY` — tool `text_normalize` 1.0.0, effect
  `read`, one `document_source` text/plain input, one `normalized_text` text/plain output;
  `_text_normalize(raw)`: strict UTF-8, one leading BOM removed, CRLF and a lone CR to LF, then
  NFC; the result names the input and output digests and sizes and whether anything changed; an
  output over the 1 MiB ceiling (NFC can triple UTF-8 bytes) is the tool's own terminal failure,
  never no answer. The table is `(text_normalize, text_profile)` in identifier order with a
  per-tool input contract table. `_serve_execute` streams a handler's output artifacts as an
  offered batch on the artifact type (a fresh batch id, the request's message id) **before** the
  reply frame; usage counts the reply and the artifact bytes.
- `app/runtime/extension_attempt_transport.py`: the mirror gains `TOOL_OUTPUT_CONTRACTS` and
  `TOOL_OUTPUT_BOUNDS` (growth factor and ceiling per tool). After the input stream, an artifact
  frame correlated to the request is admitted only for a tool whose output contract is non-empty,
  through `receive_offered_batch` under a policy from that contract (media types, count, the
  ceiling) into bounded sinks; then the reply is read. Control refuses received artifacts on
  anything but a succeeded tool call; verifies the bindings equal exactly the contract over what
  it admitted (ordinal, role, per-ordinal media, size, digest) and, for `text_normalize`, that
  the result's input digest and size match what it streamed and its output digest, size and
  `changed` match what it admitted; the measured output includes the artifact bytes. `_seal`
  imports each admitted artifact as registered content (`store_received_artifact`, the
  content-addressed store) and seals the blob references beside the output
  (`artifacts: [{ordinal, role, media_type, blob}]`) in the attempt's artifact.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (2 MUST, 3 SHOULD, 4 NIT); ten probes over the real socket pair.
Verified clean: a worker that streams artifacts and then answers a failure is refused and nothing
is imported; two artifacts with the right media seal two readable blobs; a media swap between
ordinals is caught whether the bindings mirror the swap or claim the contract; an empty input
yields a sealed empty artifact honestly marked unchanged; artifacts offered under `status` are
refused; a non-UTF-8 input is the tool's own failure; `domain.put` validates blob references
inside content (a correction to the review prompt's assumption). Closures, RED-first:

1. MUST — NFC can triple UTF-8 bytes, so a legal input under the ceiling could derive an output
   the reply cannot carry; the worker then failed to answer and a deterministic read tool settled
   as `outcome_unknown`, unretryable → the tool answers its own terminal failure; the RED test
   derives 1.2 MB from a 400 kB input and asserts the typed failure and a reply within the grammar.
2. MUST — `sha256_out`, `byte_count_out` and `changed` were sealed unverified although control
   held the bytes → checked against the admitted artifact and the streamed input; pinned with
   three lies.
3. SHOULD — an under-reserved `output_bytes` settles as an overrun that blocks the budget session
   and nothing told a caller the expected size → `TOOL_OUTPUT_BOUNDS` states each tool's growth
   factor and ceiling; the reservation from it is an open item (§6).
4. SHOULD — "is a refusal" read as a typed failure where the code records `outcome_unknown` →
   the contract says so and why it is honest (control observed no reply it could call a terminal).
5. SHOULD — stale "one-tool" text → corrected in the docstrings, the grammar comment and §2.
6. NIT — batch-id freshness is not asserted (stated); 7. NIT — output contracts' roles are pinned
   unique; 8. NIT — the output ceiling reuses the input constant (naming); 9. NIT — open items
   stated in §6: optional outputs (an omissions policy), the data-model `Artifact` entity for the
   sealed output, an unreferenced content-addressed blob after a seal failure.

## Verification

- TDD: RED retained — the bindings absent from the output grammar, no `text_normalize`, no
  `TOOL_OUTPUT_CONTRACTS`, the worker never offering a batch; GREEN after the grammar, the tool,
  the serve loop's send, the control transport's receive/verify/seal and the contract; the review's
  RED tests failed for their stated reasons (`succeeded` on the oversized output; the three lies
  sealed; no `TOOL_OUTPUT_BOUNDS`).
- Tests: execute messages **+1**, execute **+4**, transport **+8**; covering (messages, execute,
  transport) **89**; (probe, probe messages) **97**; (stage observer, deployment consume,
  coordinator artifacts, artifact CAS) **68**; (dispatch, runs API, artifact stream) **80** — in
  separate processes (the descriptor checks are order-sensitive across suites, pre-existing).
  Ruff: clean on every changed Python file.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- Both legs bounded to 1 MiB in memory (no scratch volume); two read-effect tools with no
  arguments; no `cancel`; no `ToolCall` record, effect gate or grant check for a tool call (open,
  §6); the worker never touches the store; no model, tool or paid call beyond the in-process
  readings. The live container/socket/worker run stays the host gate.
