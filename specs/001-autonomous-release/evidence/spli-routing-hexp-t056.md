# Evidence — T056 closed: SPLI routing from the qualified lens cards and the H_exp revision (2026-09-23)

- Task: T056 — "qualified SPLI routing, frozen contrasting predictions, actual fresh evidence,
  abstain/decline and H_exp update". The freeze/evidence/conclusion contracts existed
  (evidence/inquiry-t056.md); questions and predictions were free caller text, and "question
  generation and evidence-grounded H_exp update" were recorded open.

## Frozen identities

```
12b8cd0d016d39eefd8c0c0922c0ba48afcc65635d22b539b7984d344772a26b  app/services/inquiry.py
ab2e2da57b736b73395c409b521f3ab1e82dc136e0bd6112d16049f12bba5406  app/tests/test_inquiry.py
```

## What landed (`app/services/inquiry.py`)

- `spli_questions(registry, lens_decisions)` — **routing reads the qualified cards, it does not
  write questions.** Each registry-vouched, qualified, proposed `post_alternative_spli` decision
  contributes its card's own distinguishing question; the card's expected contrast is the
  "if supported" prediction and its disconfirmation cue the "if refuted" one. A decision whose
  card is not the registry's current card, one from another registry instance, another path or an
  unqualified status stops the routing; two decisions over one card ask one question. Nothing is
  paraphrased or model-generated, so no question outruns the lens that grounds it.
- `open_routed_inquiry(...)` opens the existing frozen inquiry over exactly those questions and
  predictions (the difference/hypothesis/route-evidence binding checks are unchanged).
- `revise_expert_judgment(hypothesis_set, inquiry)` → `ExpertJudgmentRevision` (`h-exp-revision-v1`):
  the H_exp update a *concluded* inquiry grounds, for the inquiry's own confirmed judgment in its
  own difference's set — `supported_by_fresh_evidence` or `refuted_by_fresh_evidence` carrying the
  post-freeze evidence, `unchanged` for `unresolved`/`declined` (abstention keeps no evidence as
  if it had decided). The confirmed hypothesis set is not rewritten; the revision is the next,
  separate fact, and only a supported outcome can ground learn/protect changes (the compiler's
  existing rule).

## Tests (`app/tests/test_inquiry.py`): 13 passed (9 existing + 4 new, one parametrized ×4)

Routed questions equal the card's words and deduplicate; routing refuses foreign, malformed,
unvouched and non-registry inputs; each of the four outcomes revises (or keeps) the judgment with
the right evidence; an open inquiry or a set over another difference cannot revise.

## Not claimed

- Episode-tailored phrasing of a lens question by a model; the card's own question is used as is.
- Persisting inquiries and revisions in the growth chain, and the inquiry UI (T060).
