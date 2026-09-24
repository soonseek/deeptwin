# Competing explanations of an observed difference: the connected generator (T060, 2026-09-24)

Status: **the hypothesis generator is connected.** After the owner freezes their own version
and the framework observes the difference, the owner can explicitly ask for competing
explanations. One model turn proposes them, the framework admits them only through
`propose_hypotheses`, and every one stays `proposed`. T060 stays open: an inquiry (questions
and opposing predictions frozen before new evidence) needs a confirmed judgment hypothesis,
and confirming one needs real comparison or behavior evidence (growth.md §3), which this
slice never supplies.

## What landed

### `app/services/hypotheses.py` (`PersistentHypotheses`)

- **One set per sealed difference, sealed only when the owner asks.** The set is a
  `hypothesis` record (`hypothesis-set-record-v1`) whose parents are the difference record
  and the owner's model choice, with `hypothesis.updated` in the same transaction.
- A repeat, or a replay after a lost reply, never calls again.
- **What the model sees:**
  - the sealed observations, uncertainties, evidence scope and unreviewed scope
  - for text formats only (plain, markdown, CSV, JSON), both versions, bounded at 16,000
    characters each
  - a non-text original is described only by its observations
- The difference is re-issued from the store (`PersistentAlternativeDrafts.issued_difference`),
  re-observed deterministically, and must equal the sealed record exactly, or the request is
  a conflict. `observe_difference` now shares this re-issue path.
- **Admission.**
  - The response must be exactly `{"hypotheses": [2–8 items]}`, admitted through
    `propose_hypotheses`, so a lone causal family is refused.
  - Nothing is confirmed, supported or refuted.
  - No inquiry is opened and no change candidate is made.
  - The set lives in the episode interpretation store; no operational retrieval reads it.

### `hypotheses-v1` routes (2; installed routes 70 → 72)

- `GET|HEAD /api/v1/differences/{id}/hypotheses`: the set, or `not_generated`.
- `POST /api/v1/differences/{id}/hypotheses`: exact body with the owner's `model_choice_ref`.

### The observe page's difference panel (`inquiry.mjs`)

- After the difference, the panel reads the difference's hypothesis state.
- **When no set exists:** a transmission notice, then a model pick, then one explicit button.
  Without a connection it says why.
- **When a set exists:** each hypothesis appears with its family, claim, conditions and
  distinguishing predictions, marked `제안` (proposed), with the note that none is confirmed
  without real evidence.
- The panel still never asks the owner anything (no quiz, no stand-in answer).
- The difference view's `not_generated` reason now says generation happens only when the
  owner asks.

## Observed

**Offline:**
- `test_hypotheses.py`: 2 passed. This is a real Claude-executor run on the mock transport,
  followed by the owner's freeze and the observed difference.
  1. On request: sealed once, `hypothesis.updated`, the prompt carries the observations and
     both versions, and a repeat never calls again.
  2. A lone causal family is refused with `model_output_invalid`, and nothing is sealed. Exact
     bodies: an extra field is 400, an unknown difference is 404.
- `inquiry.test.mjs`: 3 passed. The browser inquiry case: 1 passed.
- The composition and route-count suites, the drafts API and the work models: **179 passed**.

**Live (`test_claude_live_hypotheses.py`, `claude-opus-5`, passed):**
- A real run wrote a meeting notice. The owner prefixed its first line with "[참석 필수]" and
  froze it. The framework observed one `text_change`.
- Message `msg_011CfNCS5SpwTtJYn3epYB5Z` (932 input / 1,448 output tokens) proposed **five
  competing hypotheses, one per family**, each with conditions and predictions that tell it
  apart:
  - **system:** the template has no attendance field
  - **expert_judgment:** mandatory meetings deserve a forcing marker, a learnable rule
  - **exception:** a one-off for this quarter's review
  - **alternative_error:** the plain tag breaks the markdown heading, and the body already
    asks for attendance
  - **no_generalization:** one tag is too little to generalize from
- All stayed `proposed`.
