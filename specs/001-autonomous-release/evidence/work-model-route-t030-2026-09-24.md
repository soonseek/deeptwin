# The owner's common-work target: work-model draft and confirmation (T030, 2026-09-24)

Status: **a work model is drafted from a real work by a live model turn, admitted strictly,
and confirmed by the owner through the supported app.** T030 stays open. Lens design
decisions need qualified lenses (T035), and candidate generation from a confirmed target is
not yet routed.

## What landed

### `app/services/work_models.py` (`PersistentWorkModels`)

**Draft.**
- One owner-commanded model turn (`GenerationPurpose.WORK_UNDERSTANDING`), through
  `ClaudeRunExecutor.model_turn`, over the exact work revision's text.
- The model writes only the work's meaning: goals, deliverables, completion conditions,
  authorities, risks, unknowns, and the recommended shape with its rationale.
- The framework sets the identity, `work_revision_ref`, `semantic_origin`, `source_refs`
  and the suitability evidence. The sources are the revision's own retained originals.
- The answer is admitted only through `WorkModel.from_untrusted`. Any deviation is
  `model_output_invalid` (422), and nothing is sealed.
- A draft is one `work_model` record per command, with `understanding.completed` in the
  same transaction. A replay returns the same draft and never calls again.
- **A text-only revision is refused with `sources_required` (409).** FR-003's work model
  cites retained originals, and the framework never manufactures a source.
- The model reads the revision text only; the originals are cited, not parsed (no
  extraction happens).

**Confirmation.**
- The owner accepts or rejects the exact draft they read. A stale `work_model_ref` is a
  conflict.
- `accepted` binds all six dimensions through `confirm_work_model`.
- One decision per draft: a contrary decision is a conflict, and a repeat is idempotent.
- `approval.decided` is emitted.
- The confirmation names the work model by its design-space content ref, so it is stored in
  the design encoding (`encode_design_refs`), as every design-space record is.
- `confirmed_target(id)` rebuilds the issued `ConfirmedWorkTarget` for design generation.

### `work-models-v1` routes (3; installed routes 67 → 70)

- `POST /api/v1/work-models`
- `GET|HEAD /api/v1/work-models/{id}`
- `POST /api/v1/work-models/{id}/confirm`

All three have the shared exact preflight.

## Observed

**Offline (`test_work_models.py`, mock transport): 3 passed.**
1. Framework completion, the exact work text in the prompt, replay without a second call,
   read-back, a stale-ref conflict, acceptance with `approval.decided`, the one-decision
   rule, and the issued confirmed target.
2. A model answer that sets an owned identity is refused, and nothing is sealed.
3. Without a key nothing is sent. A text-only revision gets `sources_required`. Bodies are
   admitted exactly (an extra field is 400, a bad id is 400, an absent id is 404).

The route-count and composition suites were updated (**168 passed**).

**Live (`test_claude_live_work_model.py`, `claude-opus-5`): passed on the first attempt.**
- Message `msg_011CfNBXasfcfQ4NthEE3G4U`: 586 input / 888 output tokens, `end_turn`.
- The owner's confirmation followed.
- For "분기 보고서 초안을 세 문단으로 정리해 주세요", the model recorded three observable
  completion conditions and `single_agent` suitability.
- It marked two honest **blocking** unknowns: the target quarter, and whether source data is
  supplied. `create_generation_request` refuses a target with a blocking unknown, so design
  waits for the owner's answer instead of guessing.

## Still open

- Resolving unknowns (a revised work, then a new draft).
- The UI.
- Lens decisions, which need T035 qualification.
- Generation and criticism from a confirmed target through routes; approval → environment →
  graph → run.
