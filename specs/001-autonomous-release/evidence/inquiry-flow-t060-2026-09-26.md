# The owner's inquiry over an observed difference: opening, owner input, judgment, proposals, audit (T060, 2026-09-26)

Status: **the inquiry is connected end to end on the observe page.** Opening, questions, owner
answers and skips, owner-supplied evidence, the owner's judgments, change candidate proposals
and the audit detail all run over the supported server and in real Chromium. The human side is
a **simulation**: under the owner's 2026-09-25 decision (decisions.md), a scripted test actor
types every answer, skip, evidence item and judgment through the real screens, and each is
labelled `test-actor:`. No real user answered anything, and nothing here is a release
qualification or a growth result.

## What landed

### `app/services/difference_inquiries.py` (`PersistentDifferenceInquiries`)

- **One inquiry per sealed difference, opened only by the owner.** Opening requires the
  difference's hypothesis set. It freezes the questions in an `inquiry` record
  (`difference-inquiry-record-v1`, version 1, `frozen_at`) and emits `inquiry.frozen`
  (`question_count`, `prediction_count`). A repeat returns the same inquiry and never
  re-freezes.
- **Where the questions come from:**
  - They are derived deterministically from each competing hypothesis's own distinguishing
    predictions (up to two per hypothesis), each with the contrast it draws fixed before any
    answer: "supports X" / "weakens X".
  - A hypothesis without predictions gets one question asking for a distinguishing case.
  - The difference's uncertainties and its unreviewed scope ("missing evidence") add more.
  - All questions use the work's own terms; none is a philosophy, personality or values
    question.
- **Model-proposed questions, as proposals only.** If the owner picks a model when opening,
  one model turn (`purpose: inquiry_questions`) may add up to four questions.
  - They are admitted exactly as `{"questions":[{"text","hypothesis_ids"}]}`: ids must name
    real hypotheses.
  - Any answer-, evidence- or judgment-shaped field refuses the whole output
    (`model_output_invalid`), and nothing opens.
  - They are labelled `model_proposal` and carry no invented prediction. The prompt digest is
    stored so the audit can find the executor's sealed call intent.
- **Owner inputs.** Each is appended as the next version of the inquiry record, with
  `origin: owner_input`, the owner's actor ref, a timestamp and its command id. A replayed
  command changes nothing.
  - **Answer:** the owner's typed text; blank text is refused. It emits `inquiry.evidence`.
  - **Skip:** carries no text and emits `inquiry.declined {deferred: true}`. Every question is
    optional, and an unanswered question stays unanswered; nothing fills it.
  - **Evidence:** the owner's text plus up to 8 source references. It is sealed as its own
    `artifact` record (`inquiry-evidence-v1`) and observed strictly after `frozen_at`.
  - **Judgment:** `confirmed`, `refuted` or `unresolved`, and emits `hypothesis.updated`.
    - Confirming or refuting must cite this inquiry's own evidence (`evidence_required`).
    - Confirming needs every competitor examined first (`competitors_unexamined`), and a
      hypothesis is judged only once (`already_judged`).
    - The authority is the diagnosis contract itself: the issued difference is re-observed,
      the set is re-issued through `propose_hypotheses`, and every judgment is replayed through
      `HypothesisSet.resolve`. The single-cause shortcut and recycled compared material stay
      refused there too.
- **Change candidate proposals** (`change-candidate-proposal-v1`) come only from a confirmed
  hypothesis:
  - `system` gives a restore proposal, `expert_judgment` a learn proposal, `exception` a
    protect proposal.
  - `alternative_error` and `no_generalization` conclude with no change and state why.
  - Each proposal carries `state: proposed`, `compiled: false`, `applied: false`, the cited
    evidence refs, `change_scope` equal to the difference's evidence scope, and a
    `predicted_impact_scope` of `pending_investigation`.
  - Each one states what compilation still needs. Restore needs the parent environment,
    compatibility and rollback refs of T057's system-repair path. Learn and protect need a
    supported qualified-lens inquiry.
  - A leak check flags any proposal text that copies the owner's own new lines
    (`copies_owner_wording`).
- **The audit** (`GET …/audit`):
  - A timeline: difference observed, hypotheses proposed (actor model, requested by the owner),
    then each owner act with who, what, when and its origin.
  - The model turns: the hypothesis turn found by re-rendering its prompt digest, and the
    question turn by its stored digest. Each shows its sealed intent ref, request time and
    outcome (state, stop reason, provider message id, usage).
  - Owner-input counts, and `inputs_not_from_owner`: every answer, skip, evidence item or
    judgment whose origin or actor is not the owner.

### `inquiries-v1` routes (6; installed routes 128 → 134)

| Method | Route | Purpose |
| --- | --- | --- |
| `GET`/`HEAD` | `/api/v1/inquiries/{difference_id}` | read the inquiry |
| `POST` | `/api/v1/inquiries/{difference_id}` | open |
| `POST` | `/api/v1/inquiries/{difference_id}/answers` | answer or skip |
| `POST` | `/api/v1/inquiries/{difference_id}/evidence` | add evidence |
| `POST` | `/api/v1/inquiries/{difference_id}/judgments` | record a judgment |
| `GET`/`HEAD` | `/api/v1/inquiries/{difference_id}/audit` | read the audit |

- All bodies are exact and checked by the shared `/api/v1` preflight.
- Errors repeat the closed code as `reason`, because the browser session keeps only its
  generic codes.
- The pinned route counts and the route-id list are updated in the five composition tests.

### The observe page (`app/static/inquiry.mjs`)

- After the competing explanations are shown, an **탐구** section appears.
- **While not opened:** why it is closed, an optional model pick ("모델 제안 없이" by default)
  and one explicit **탐구 열기** button.
- **Once open:**
  - The frozen questions, each with its origin label and state (답하지 않음 / 건너뜀 / 내 답),
    an optional answer box, **답 저장** and **건너뛰기**.
  - The evidence list and form.
  - Per-hypothesis judgment controls with evidence citation.
  - The change candidate proposals, marked "제안 · 적용되지 않음", with their leak-check line
    and next step.
  - **감사 상세 보기**.
- The difference view's `inquiry` and `change_candidates` reasons now describe this flow.

## Observed

### Offline

**`test_difference_inquiries.py`, 5 passed.** This is a real Claude executor on a mock
transport, followed by the owner's freeze, the difference and scripted competing
explanations.

1. The full flow:
   - Opening without a model makes no model call.
   - Answer q1, skip q2; a replayed skip is idempotent.
   - The evidence is timestamped after the freeze.
   - Confirming without evidence gives 422 `evidence_required`, and confirming before the
     competitor is examined gives 409 `competitors_unexamined`.
   - Refuting `system-0` and then confirming `expert_judgment-1` yields one learn proposal
     that is not applied and passes the leak check.
   - Judging the same hypothesis again gives 409 `already_judged`.
   - The audit shows the owner-input counts 1/1/1/2, `inputs_not_from_owner` 0 and the
     completed hypothesis turn.
   - Events: `inquiry.frozen` and `inquiry.declined`. No model call happens after the
     hypotheses.
2. An answer-shaped model question output gives 422 `model_output_invalid`, and nothing opens.
3. A model question proposal is admitted as `model_proposal` with no invented prediction. No
   answer, evidence or judgment exists, and the audit lists both model turns with their intents.
4. Opening before any hypotheses gives 409 `hypotheses_required`, and answering before
   opening gives 409 `not_opened`. Bodies are exact (400), and an unknown question or evidence
   gives 404.
5. A proposal whose text copies the owner's new line is flagged `copies_owner_wording`
   (protect proposal).

**Other offline suites:**
- `inquiry.test.mjs`: **5 passed**, 2 of them new.
  1. The inquiry opens only on the click, with `model_choice_ref: null` unless a model is
     picked.
  2. An empty answer box sends nothing, and a skip sends `text: null`. Evidence sources are
     split by line, a judgment cites the checked evidence, and the proposal and audit render.
- `browser-inquiry.test.mjs`: **2 passed** in real Chromium.
  - The existing no-quiz case.
  - The new **test-actor full flow** over `fixtures/inquiry_server.py` (the Claude executor on
    an in-process scripted transport):
    - freeze a draft
    - **경쟁 설명 만들기** (scripted turn)
    - open with a model (scripted question turn) — every question shows unanswered, and the
      API answers list is `[]`
    - answer q1, skip q2, add evidence with two sources
    - premature confirm refused with the reason
    - refute `system-0`, confirm `expert_judgment-1`
    - "학습 변경 제안 · 제안 · 적용되지 않음"
    - the audit shows 답 1 · 건너뜀 1 · 근거 1 · 판단 2 and "소유자 입력이 아닌 사람 답: 0",
      with both model turns completed
  - The final API state has exactly q1 (the typed text) and q2 (skipped), both
    `owner_input`. No model-proposed question has an answer. There are no page errors.
- `browser-alternatives.test.mjs`: 3 passed.
- All node unit tests: 300 passed.
- The affected Python suites (inquiries, hypotheses, drafts API, composition and route counts,
  domain events, inquiry contract): **907 passed**.
- The full non-live Python regression: see the T060 note in tasks.md.

### Live (`test_claude_live_inquiry_questions.py`, passed)

The run used the owner connection's first listed model, with output caps of 256 tokens for the
writer and 2,500 for design turns.

- A real run wrote a meeting notice. The test actor prefixed its first line with "[참석 필수]"
  and froze it.
- Message `msg_011CfR7MvJUkcuiC3yxvdjRb` (934 input / 1,429 output tokens) proposed five
  competing hypotheses, one per family.
- Opening with the same model, message `msg_011CfR7P2ud5L7UP7gG2Ggyy` (2,658 input / 517
  output tokens) proposed **four questions in work language**. Each names the hypotheses it
  separates:
  - Was mandatory attendance new this quarter?
  - Where does the notice template put such tags?
  - Did recipients ask whether it was mandatory?
  - How were recent optional-meeting notices marked?
- They were admitted as `model_proposal` beside 11 derived questions.
- `answers`, `evidence` and `judgments` stayed empty, and the owner-input counts were all 0.
- Spend was three calls totalling well under the $0.50 cap. The writer's usage was not
  collected.

## What this does not establish

- **No real human feedback.** Every owner act above is a scripted test actor, per the
  2026-09-25 decision.
  - A confirmation here rests on evidence the (simulated) owner typed. It is the owner's
    judgment, not a paired comparison or behavior run.
  - growth.md's comparison and re-evaluation evidence (T061+) is still required before any
    change is tested or promoted.
- **Proposals are not compiled candidates.** Nothing here calls `compile_change_candidate` or
  `compile_system_restore`, forks an environment or applies anything.
- **The lens-based SPLI inquiry is not opened.** It needs a confirmed expert judgment plus
  registry-qualified lens decisions (T056 contract), and none is qualified here. The panel
  says so.
- **Records are stored with `purpose: operational`**, like the hypothesis set. Moving the
  inquiry and interpretation records to a dedicated interpretation or audit purpose is not
  done.
