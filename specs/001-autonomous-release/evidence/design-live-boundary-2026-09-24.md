# The design arc's live model boundary (2026-09-24)

Status: **a real model's design candidate is accepted by the framework, and live four-stage
criticism reaches a framework verdict.** The live chain runs generation → acceptance → review →
counterexample proposal → validity, all through the owner's connection. The first complete
verdict is `insufficient_evidence` (not selectable). T030, T036 and T038 stay open: production
producers, routes and UI are not wired.

## What landed

- **`ClaudeRunExecutor.model_turn(model_id, *, purpose, max_output_tokens=None)`** is the design
  drivers' `model_turn(system, user) -> str` over the owner's connection.
  - Each call spends one unit of the process cap it shares with run nodes.
  - Before sending, it seals a `claude-design-call-intent-v1` record: purpose, model, cap, effort
    and prompt digest (never the prompt).
  - After the call, it seals the outcome record.
  - It asks for `effort: medium` when the catalog lists it.
  - Only a completed call returns text; truncation or failure raises, and the drivers treat that
    as terminal.
  - A separate per-call cap applies: `LiveLimits.max_design_output_tokens` (default 16000).
  - Run nodes and design turns share one streaming helper.
- **Generation prompt (`design_live.py`).** The prompt used to say "no identifiers, no
  references" while the graph schema requires them, and it showed the model only the compilation
  authority's digest. Now:
  - The framework fills the fields it owns (`schema_version`, `graph_id`, `version`, the
    work-model and decision refs, and the observation-contract and budget-policy refs when the
    authority lists exactly one). A value the model does supply is still admitted strictly.
  - The payload carries the authority itself, each tool's required approval scope, and the
    required lens effects with their exact values.
  - The system prompt gives a worked two-node example, every enum and per-kind config shape, and
    the compiler's structural rules.
- **An effect can carry its exact expected value (`design.py`).** `expected_value` is optional,
  and its canonical hash must equal `expected_value_sha256`. A hash-only effect stays verifiable
  but cannot be authored from a prompt.
- **Tests.**
  - `test_claude_design_turn.py` (2), on the mock transport.
  - Framework-fill and strict-ref tests in `test_design_live.py`.
  - Carried-value tests in `test_design_generation.py`.
  - The design, critic, environment, Claude and runs suites: **616 passed**.
- **Live test `test_claude_live_design.py`.** It runs only with the key and
  `DEEPTWIN_LIVE_DESIGN=1`. It saves the model's raw text the moment it arrives.

## Live attempts (`claude-opus-5`, reviewed fixture request, 3 candidates asked)

| # | Message | Result | Out tokens |
| --- | --- | --- | --- |
| 1 | `msg_011CfMqchkDZMrpn9vuft1Pa` | refused: invalid node failure policy (enum not in prompt) | 12,201 |
| 2 | `msg_011CfMqoAmCEujzh1ZVcDfaa` | refused: tool bindings in the authority's definition shape | 11,843 |
| 3 | `msg_011CfMr1aDvcvpL7VxCfRBTf` | incomplete: `max_tokens` at 16k | 16,000 |
| 4 | `msg_011CfMrEPEjCMcy5t29Cu2JP` | completed; the admission crashed outside the caught errors, and the raw text was lost (the test now saves it first) | 15,426 |
| 5 | `msg_011CfMrTiH5B9C8ZmJJieftd` | **all three graphs pass the compiler**; refused because the lens effect's value was paraphrased (twice) or its target node was absent (once) | 17,983 |
| 6 | `msg_011CfMriSNGynb9R7wi3HAA5` | failed: the adapter's 180 s per-call deadline (the runtime contract) | unknown |

After attempt 5, the required effects were lifted into the payload with a verbatim instruction.
The change to one candidate per call had already gone into commit 5e25b95 with the rest of that
slice. The owner then approved continuing (2026-09-24), and the retries below used it.
Attempt 6 then ran into the deadline, because three full graphs take longer than 180 s. The
contract's deadline is kept. The next step asks for **one candidate per call** and lets the
orchestrator's bounded supplementation rounds fill the pool. That retry was held, pending the
owner's go-ahead.

### One candidate per call, then live criticism

| # | Result | Calls (in / out tokens) |
| --- | --- | --- |
| 7 | **accepted**: research → fact_check → script → publish_gate; lens effect realized exactly; 56 s | 1 (5,544 / 4,229) |
| 8 | accepted again; the critic's review was refused because citations were prose (`roles[0].id=research`), not the contract's visible JSON-Pointer locations | 2 |
| 9 | accepted; review and counterexample proposal **passed**; validity was refused because it cited the counterexample document itself, which the contract does not admit as evidence | 4 |
| 10 | accepted; the **whole chain completed**: review, a proposal of 3 counterexamples, 3 validity checks. Verdict `insufficient_evidence`: validity was unresolved for each counterexample (`ce-join-write-mutation`, `ce-no-script-verification`, `ce-script-no-source-access`), so the candidate is not selectable | 6 (35,724 / 19,780) |

**Fixes for the refusals.** Replaying the saved raw responses offline (free) found the exact
contract errors, so each fix cost no extra call. The critic prompt now states the citation
grammar:
- cite only originals (by their section locations), the criteria or the candidate (by JSON
  Pointer)
- never cite the counterexample or validity documents

**Reading the verdict.** The critic proposed plausible failure modes. The validity stage could
not settle them from the candidate's declared structure, and the framework's fold correctly
refuses to present the candidate as passed. A selectable candidate needs either a design that
closes those counterexamples, or evidence the validity stage can resolve. That is design work
for the supplementation round, not a prompt fix.

In attempt 5, the model designed three different, sensible graphs:
- a research → verify → script → human publish gate → package chain
- a parallel source and audience research joined before drafting and fact-checking
- a router-based coverage check with deep research on insufficient evidence

## Spend

About $3.95 across all live calls so far, counting attempt 6 at its worst case. The budget is
$20.

## Still open

- A live candidate whose criticism passes; a supplementation round against the counterexamples.
- Production producers of the work model, lens decisions and design decisions.
- Routes, persistence wiring, owner approval → environment → the `graph` record → run.
- UI.
