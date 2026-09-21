# Claude provider protocol check — 2026-09-19

## Scope and method

Read-only verification of the concrete `claude-text-no-tools-v1` claims in
`.superpowers/sdd/resumption-plan/provider-dialogue-contract-draft.md` against current, public
Anthropic documentation. No credentials, API requests, model selection/ranking, pricing research, or
implementation testing were used. Anthropic documentation is the only external source.

## Findings

### 1. Endpoint, required headers, and request body

- `POST /v1/messages` and `GET /v1/models` are the documented endpoints. Direct API requests require
  `anthropic-version` and `content-type: application/json`; authentication is `Authorization: Bearer`
  unless `x-api-key` is set. Anthropic calls `x-api-key` a legacy fallback that is still supported.
  `anthropic-workspace-id` is required for a multi-workspace API key and optional for other API keys.
  ([API overview](https://platform.claude.com/docs/en/api/overview))
- The Messages schema requires `model`, `max_tokens`, and `messages`; `stream` is optional at the API
  level and selects SSE when true. A top-level `system` field is supported; there is no system role in
  the ordinary input-message sequence. `max_tokens` is an absolute maximum and the model may stop
  earlier. The API currently permits zero, so the draft's `1..8192` rule is a valid stricter profile
  choice, not an Anthropic constraint. ([Create a Message](https://platform.claude.com/docs/en/api/messages/create))
- Therefore the exact body in draft lines 116-124 (`model`, `max_tokens`, `stream=true`, optional
  `system`, `messages`, with tool/thinking/cache/beta fields omitted) is supported as a deliberately
  narrow request profile.

**Activation design question:** draft lines 108-111 and 172-175 must freeze an exact
`anthropic-version` and workspace-selection rule. The documented fact is only that a multi-workspace
API key requires `anthropic-workspace-id`; “prove a single-workspace key before any send” would be an
architectural strategy, not an Anthropic requirement, and no local authoritative key-type producer
currently exists. Viable future strategies include such an authoritative producer, or an explicit
owner-selected workspace frozen in the canonical connection, sent as the documented header, and checked
against the actual `anthropic-workspace-id` response identity (including catalog responses). Do not infer
key type from a key prefix and do not authorize a live probe merely to classify a credential.

### 2. SSE event grammar, terminals, and refusal

- The documented flow is one `message_start`, then each content block's start/delta(s)/stop, one or
  more `message_delta` events, and final `message_stop`. Any number of `ping` events can be interspersed;
  an `error` event can also arrive. Anthropic warns that future event types may be added and recommends
  handling unknown types gracefully. `message_delta.usage` counts are cumulative.
  ([Streaming Messages](https://platform.claude.com/docs/en/build-with-claude/streaming))
- The same streaming reference documents a `fallback` content block at each model boundary during
  server-side fallback; unlike ordinary blocks it can have start/stop with no delta. This profile forbids
  server-side fallback, so a fallback block or observed serving-model drift must be refused rather than
  accumulated as ordinary text.
- `end_turn` is the natural completion reason. `max_tokens` means truncation. Other documented terminal
  reasons include `stop_sequence`, `tool_use`, `pause_turn`, `refusal`, and
  `model_context_window_exceeded`; treating only `end_turn` as success is a sound stricter profile.
  ([Stop reasons](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons))
- Streaming classifier refusals place `stop_reason: refusal` and `stop_details` on `message_delta`, and
  usage is still returned. Separately, the current Message response schema/example permits refusal
  metadata/content with `stop_reason: end_turn`. A check of stop reason alone is therefore insufficient.
  ([Streaming refusals](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/handle-streaming-refusals),
  [Message response schema](https://platform.claude.com/docs/en/api/messages/create))

**Activation-critical amendment:** draft lines 164-170 must explicitly (a) accept and ignore valid
`ping` events at documented inter-event positions, (b) map stream `error` to non-success, (c) inspect
`stop_details` and reject refusal content/metadata even when the terminal reason is `end_turn`, and
(d) reject `fallback` blocks/model drift, and (e) define the pinned treatment of unknown event types.
Fail-closed unknown-event handling is a valid local security profile, although it is stricter than
Anthropic's forward-compatibility recommendation.

### 3. Usage optionality and reconstruction

- A completed Message has a `usage` object. In streamed data, the initial Message and later cumulative
  `message_delta.usage` divide the observable counters. The current `MessageDeltaUsage` schema makes
  `output_tokens` numeric while `input_tokens`, `cache_creation_input_tokens`, and
  `cache_read_input_tokens` are nullable. Cache counters therefore cannot safely be defaulted to zero.
  ([Messages type reference](https://platform.claude.com/docs/en/api/typescript/messages),
  [Streaming Messages](https://platform.claude.com/docs/en/build-with-claude/streaming))
- Draft lines 187-190 are conservative in making the entire four-counter value null unless all required
  counters are observed. This preserves the “never fabricate zero” rule, but “missing final usage” in
  line 169 is not precise enough for an implementation because usage is split and message deltas can be
  plural.

**Activation-critical amendment:** define “fully observed” as validated counters reconstructed from
`message_start.message.usage` plus the latest cumulative `message_delta.usage`; emit the four-integer
usage object only if all four are non-null, otherwise emit `usage=null`. Retain observed counters
privately on non-success where the existing settlement contract allows it.

### 4. Models pagination and model evidence

- `GET /v1/models` accepts optional `after_id`, `before_id`, and `limit`; `limit` defaults to 20 and is
  documented as 1 through 1000. The response contains `data`, nullable `first_id`, boolean `has_more`,
  and nullable `last_id`; `last_id` is the next forward `after_id` cursor.
  ([List Models](https://platform.claude.com/docs/en/api/models/list))
- Thus the draft's `limit=1000`, forward-only `after_id`, 20-page ceiling, duplicate/cursor-loop checks,
  and incomplete-on-limit behavior are bounded and feasible. The official schema describes model IDs
  only as strings: it does not guarantee the draft's safe-ID regex, nor explicitly promise the draft's
  “nonempty when more” invariant. Those are defensible fail-closed local validations, but must not be
  presented as Anthropic guarantees; a future valid-but-rejected ID must yield `catalog_incomplete`, not
  a complete prefix.
- Current `ModelInfo` explicitly exposes nullable `capabilities`, including structured effort support
  and supported effort levels. This is direct provider-reported metadata, not inference from the model
  ID and not independent qualification evidence. Draft line 180 is correct: absent/null capability or
  effort data is unknown, not evidence of suitability.
  ([Models types](https://platform.claude.com/docs/en/api/models))

## Disposition

The proposal is supportable after the three activation-critical amendments above. No discrepancy
requires widening tools, enabling thinking, accepting partial catalogs, fabricating usage, or performing
a live API experiment. The safe-ID and pagination hardening should be labeled local profile constraints;
they are not blockers if rejection deterministically produces `catalog_incomplete`.
