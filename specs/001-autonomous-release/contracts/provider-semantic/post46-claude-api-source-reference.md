# Post-46 Claude API primary-source reference

> Design context only. This is not Task 46, production authorization, a captured live response, or permission to use credentials. No model call was made. Retrieved 2026-09-20 from public first-party Anthropic documentation and official Anthropic SDK source.

## Findings at a glance

- The current standard Models API is **not IDs/labels only**. `ModelInfo` now contains `capabilities`, `max_input_tokens`, and `max_tokens` in addition to identity/display fields. Capability and limit fields are nullable, so null remains unknown rather than zero.
- It exposes effort and context-management capabilities and numeric input/output limits. It does **not** expose a per-model `text_input` or `text_output` flag. Anthropic's dated current-model overview says all current models support text and image input and text output; that prose, not an inferred name pattern, is the text-modality provenance.
- A Messages response/SSE stream reports token usage, not exact currency cost. Currency requires a reviewed price policy; the organization Cost API is delayed and aggregated, not a per-message price oracle.
- The canonical runtime may use either a conservative local reservation **or** a documented enforced provider spend limit. The formulas below are project design inferences for the reservation branch, not Anthropic requirements. Missing price/usage data never means zero.

## 1. Models API: exact stable response and pagination

Primary references: [List Models](https://platform.claude.com/docs/en/api/models/list), [Get a Model](https://platform.claude.com/docs/en/api/http/models/retrieve), [Models types](https://platform.claude.com/docs/en/api/http/models), and [current models overview](https://platform.claude.com/docs/en/models/overview).

### List

`GET /v1/models` accepts optional query parameters:

- `after_id: string`: page immediately after that object.
- `before_id: string`: page immediately before that object.
- `limit: number`: default 20, minimum 1, maximum 1000.

The response object is exactly documented as:

```text
data: ModelInfo[]
first_id: string | null   # use as before_id for the previous page
has_more: boolean         # more results in the requested direction
last_id: string | null    # use as after_id for the next page
```

Results are ordered more recently released first. Do not invent cursor arithmetic: reuse returned IDs and stop only when `has_more` is false. The reference does not define a combined `before_id` + `after_id` policy, so a closed client should choose one direction per traversal.

### Detail and `ModelInfo`

`GET /v1/models/{model_id}` accepts an identifier **or alias**, resolves it, and returns one `ModelInfo`. List items and detail use the same documented fields:

```text
type: "model"
id: string
capabilities: ModelCapabilities | null
created_at: RFC3339 string (may be epoch when release date is unknown)
display_name: string
max_input_tokens: number | null
max_tokens: number | null
```

`max_input_tokens` is documented as maximum input context-window size; `max_tokens` is the maximum accepted Messages `max_tokens` value. A null limit is unknown, not unlimited and not zero.

When non-null, `ModelCapabilities` currently has nine required named branches: `batch`, `citations`, `code_execution`, `context_management`, `effort`, `image_input`, `pdf_input`, `structured_outputs`, and `thinking`. Use returned booleans; do not derive support from `id` or `display_name`.

Exact nested grammar from Anthropic's generated OpenAPI types:

```text
CapabilitySupport = { supported: bool }
ModelCapabilities = {
  batch: CapabilitySupport, citations: CapabilitySupport,
  code_execution: CapabilitySupport,
  context_management: ContextManagementCapability,
  effort: EffortCapability,
  image_input: CapabilitySupport, pdf_input: CapabilitySupport,
  structured_outputs: CapabilitySupport, thinking: ThinkingCapability
}
ContextManagementCapability = {
  supported: bool,
  clear_thinking_20251015?: CapabilitySupport | null,
  clear_tool_uses_20250919?: CapabilitySupport | null,
  compact_20260112?: CapabilitySupport | null
}
EffortCapability = {
  supported: bool,
  high: CapabilitySupport, low: CapabilitySupport,
  max: CapabilitySupport, medium: CapabilitySupport,
  xhigh?: CapabilitySupport | null
}
ThinkingCapability = { supported: bool, types: ThinkingTypes }
ThinkingTypes = { adaptive: CapabilitySupport, enabled: CapabilitySupport }
```

Here `?` means the generated type permits absence and JSON null (`Optional[...] = None`); unmarked properties are required by the generated model. `ModelInfo.capabilities`, `max_input_tokens`, and `max_tokens` have the same optional/nullable distinction; the other four `ModelInfo` fields are required.

### Immutable generated-source snapshot

Anthropic's official Python SDK `main` resolved on 2026-09-20 to commit [`0af0190679a9e80388bd1b0328d557c9a91a11b2`](https://github.com/anthropics/anthropic-sdk-python/tree/0af0190679a9e80388bd1b0328d557c9a91a11b2). The files below state they are generated from Anthropic's OpenAPI specification. SHA-256 and byte counts apply to each complete raw file at that commit, not excerpts here.

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| [`model_info.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/model_info.py) | 961 | `838e863b80a9a7aa41b41415d21e7af49531898b980b77fd92d830931cf19c12` |
| [`model_capabilities.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/model_capabilities.py) | 1264 | `5a478ff80d5dfc55ad446a922349957610ac0f4fe552d37be53872dbc259642e` |
| [`capability_support.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/capability_support.py) | 240 | `325dc362d61af4a6c0555a331898fe53cd6db22ea9296ee98079626d06073f73` |
| [`context_management_capability.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/context_management_capability.py) | 687 | `d2d9466b2da141adf9e17ba92d26d5c019f7d847f55c949c56effcc5cd4b7b4d` |
| [`effort_capability.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/effort_capability.py) | 760 | `57f48afc318a7a04e09ef45c352d75293efa84753329478602087105444a5296` |
| [`thinking_capability.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/thinking_capability.py) | 344 | `3109130093e17c8bd4e7f46535cbdede0be5305886dc06c32a1ba9f8ee80be65` |
| [`thinking_types.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/thinking_types.py) | 402 | `00918bb8177a4908aba532f699ebaec72a214c1db1c853fd1a5f95aa6fec0555` |

### Exact capability provenance and remaining gap

| Question | Authoritative current answer | Design consequence |
| --- | --- | --- |
| Which models are available? | Paginate `GET /v1/models`; detail can resolve an operator-supplied ID/alias. | Do not ship guessed model names. Persist the resolved returned `id`, not only an alias. |
| Context and max output? | Per-model nullable `max_input_tokens` and `max_tokens`. | Refuse/require reviewed policy when null; never convert null to 0 or infinity. |
| Effort? | `capabilities.effort` advertises overall and per-level support. | No hardcoded effort selection is justified here; an omitted effort remains omitted. |
| Context-management feature support? | `capabilities.context_management`, distinct from the numeric context limit. | Do not confuse feature strategies with `max_input_tokens`. |
| Text input/output modality? | No per-model text flag exists in `ModelCapabilities`. The current overview states all **current** models support text input and text output. | This is dated global documentation, not machine-readable per-model evidence. Preserve a reviewed policy version or treat text modality as unresolved if that statement changes. |
| Price? | No price or currency field exists in `ModelInfo`. | Pricing needs separate reviewed provenance (§3). |

## 2. Text-only Messages SSE

Primary references: [API overview/authentication](https://platform.claude.com/docs/en/api/overview), [Create a Message](https://platform.claude.com/docs/en/api/messages/create), [streaming messages](https://platform.claude.com/docs/en/build-with-claude/streaming), [API versioning](https://platform.claude.com/docs/en/api/versioning), and the immutable official SDK evidence below.

### Headers/version and selected request surface

The official API generally supports bearer or API-key authentication and conditional workspace selection, but those alternatives do not expand this existing profile. For the selected direct `api.anthropic.com` **API-key-only** profile, send exactly these required headers:

- `anthropic-version: 2023-06-01` (the current documented stable version example and the sole published Messages version in version history);
- `content-type: application/json`;
- `x-api-key: <API key>`.

Do not add `Authorization` or `anthropic-workspace-id` in this profile. Their upstream availability is background API fact, not implicit authorization for federation or multi-workspace behavior.

No beta header is required for the selected stable text stream. The minimal selected body is `model`, `max_tokens`, text-only `messages`, and `stream:true`. Omit `tools`, `tool_choice`, `thinking`, and `output_config.effort`; omission is not equivalent to asserting a named default. Do not add sampling parameters merely because examples show them.

### SSE sequence and terminal meaning

For API version `2023-06-01`, named SSE events replace data-only streaming and there is no `[DONE]` event:

1. `message_start`: a `Message` with empty `content`; streaming `stop_reason` is null initially. Its full `usage` carries request/input accounting available at start.
2. For each content index: `content_block_start`, one or more `content_block_delta`, then `content_block_stop`. A selected text-only parser accepts `content_block.type == "text"` and `delta.type == "text_delta"`, retaining block order/index.
3. One or more `message_delta` events update top-level fields. Their `usage` counts are **cumulative**, not increments; never sum successive deltas.
4. `message_stop` ends a completed stream. It contains no usage itself.

Any number of `ping` events may occur. An `error` event may arrive after HTTP 200; disconnect/error before a coherent `message_stop` is incomplete, not a zero-cost result. `message_stop` establishes transport completion, not semantic success: inspect the final `stop_reason` (for example normal end, requested stop, output/context truncation, or refusal). A tool/pause/compaction outcome is outside this selected text-only/no-tools surface and must not be silently treated as text success. [Stop-reason guide](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons).

Anthropic's version policy permits additional output values and new enum/event variants. Unknown events must be handled gracefully: preserve/skip them without corrupting known block assembly, but do not reinterpret them as terminal or usage. Unknown ordinary response fields may be retained for forward compatibility. An unknown **usage category** is financially different: retain it and keep the reservation until a reviewed price policy explains it.

### Usage and prompt-cache categories

The generated raw types distinguish required from optional/nullable fields exactly:

```text
Usage (inside Message/message_start):
  required: input_tokens:int, output_tokens:int
  optional|null: cache_creation:CacheCreation,
                 cache_creation_input_tokens:int,
                 cache_read_input_tokens:int, inference_geo:string,
                 output_tokens_details:OutputTokensDetails,
                 server_tool_use:ServerToolUsage,
                 service_tier:"standard"|"priority"|"batch"

MessageDeltaUsage (inside message_delta; all cumulative):
  required: output_tokens:int
  optional|null: cache_creation_input_tokens:int,
                 cache_read_input_tokens:int, input_tokens:int,
                 output_tokens_details:OutputTokensDetails,
                 server_tool_use:ServerToolUsage

CacheCreation (when non-null):
  required: ephemeral_1h_input_tokens:int,
            ephemeral_5m_input_tokens:int

OutputTokensDetails (when non-null): required: thinking_tokens:int
ServerToolUsage (when non-null):
  required: web_fetch_requests:int, web_search_requests:int
```

`MessageDeltaUsage` has no TTL `cache_creation` breakdown, `inference_geo`, or `service_tier`. Merge by latest non-null cumulative value, using `message_start` for fields absent from later deltas; do not manufacture zeros. Optional means the raw JSON may omit the field or contain null; a closed parser should preserve that distinction from numeric zero.

Anthropic defines total input as:

```text
total_input_tokens = input_tokens
                   + cache_creation_input_tokens
                   + cache_read_input_tokens
```

The fields are disjoint: `input_tokens` is the uncached suffix, `cache_creation_input_tokens` is newly written cache input, and `cache_read_input_tokens` is cache-hit input. When `cache_creation` is present, its `ephemeral_5m_input_tokens` plus `ephemeral_1h_input_tokens` equals `cache_creation_input_tokens`. The TTL split matters because write prices differ. `output_tokens` is the inclusive authoritative billed-output total; an optional thinking breakdown is observability, not an extra amount to add. [Prompt-caching accounting](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

The dedicated caching guide says caching is enabled either by a top-level `cache_control` (automatic mode) or block-level `cache_control` breakpoints (explicit mode), and that requests without prompt caching do not receive the server-tool automatic breakpoint. Therefore a closed request that omits every `cache_control` and all tools disables prompt caching by construction. Only then may design logic establish cache categories as zero from the request invariant rather than from missing response fields. If caching is admitted, null/missing cache counts, or a positive cache-write total without its TTL split, leave cost unresolved. Missing start usage, missing required output usage, unknown billable fields, stream error, or no `message_stop` must retain the reservation—never synthesize zero. [Dedicated prompt-caching guide](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).

The same immutable SDK commit provides the complete raw usage sources:

| File | Bytes | SHA-256 |
| --- | ---: | --- |
| [`usage.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/usage.py) | 1568 | `067d4e2d9fa8b623af5d05010351709078d803234260569b841a0f9ba460c271` |
| [`message_delta_usage.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/message_delta_usage.py) | 1210 | `8ad15dff7eb7dee758ac8370a7ee9525a6e0cc32ac671c11e3e176aaf62d9b4e` |
| [`cache_creation.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/cache_creation.py) | 320 | `3f874c714ccf030e8877496320562956f845ec3fc4fdc51c3d94c980994a7f9d` |
| [`output_tokens_details.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/output_tokens_details.py) | 658 | `691e4e601042536f65d67db6655c52cc622efab2a82dde7e640033c68f9e0592` |
| [`server_tool_usage.py`](https://github.com/anthropics/anthropic-sdk-python/blob/0af0190679a9e80388bd1b0328d557c9a91a11b2/src/anthropic/types/server_tool_usage.py) | 256 | `9c4aab40aaa34a42797d4fd959eff6e4450a6a3a9878cd6389ce761777c3f15d` |

## 3. Currency cost, conservative reservation, and genuine limits

Primary references: [pricing](https://platform.claude.com/docs/en/about-claude/pricing), [prompt-caching pricing](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), the dedicated [token-counting guide](https://platform.claude.com/docs/en/build-with-claude/token-counting), [Usage and Cost API](https://platform.claude.com/docs/en/manage-claude/usage-cost-api), and [rate/spend limits](https://platform.claude.com/docs/en/api/rate-limits).

### No exact per-message currency return

The Messages API returns billing/rate-limit token counts, not a currency amount. The Models API returns no prices. Therefore neither response yields exact request currency cost.

The Admin Usage and Cost API is the billing-reconciliation source: it reports USD cost as decimal strings in cents, typically appears within five minutes (sometimes longer), and is aggregated into daily cost buckets/groupings. It is unavailable to individual accounts, requires organization-level credentials, excludes Priority Tier costs, and has no documented per-message/request-ID grouping. It cannot synchronously settle one request.

### Official counting facts and the remaining price-policy gap

The dedicated guide explicitly says Token Counting is **free to use**, has its own request-per-minute limits independent of Message creation, and returns an **estimate**: actual Message input usage can differ by a small amount. It does not run caching logic even when `cache_control` is supplied. Counts can include Anthropic-added optimization tokens that are not billed, so the count is useful preflight evidence but not an exact currency oracle.

For the **local-estimate branch**, maintain a human-reviewed, effective-dated price policy keyed by resolved model ID and every admitted modifier (service tier/speed, inference geography, cache TTL/read class, and any context rule). Source it from official pricing pages and record retrieval/effective dates and currency units. This manual provenance gap cannot be filled from `ModelInfo` and must not be hidden by a fabricated zero. The alternative canonical branch may instead rely on a documented enforced provider spend limit, without pretending it is a per-message price.

### Project inference: conservative pre-send reservation

The following arithmetic is a proposed project design for the local-estimate branch; Anthropic does not require this reservation formula. Let `I` be the accepted input-token upper bound (including a margin for Token Counting's documented estimate drift), `O` the requested `max_tokens`, and prices be exact decimal currency per token from the approved price policy. Checking `O <= ModelInfo.max_tokens` follows the advertised server limit. Requiring `I + O` to fit the context window is an optional stricter project admission rule for avoiding truncation, not an Anthropic requirement; official context behavior can terminate generation at the context boundary. Null limits remain unresolved.

For a no-cache request:

```text
reservation = I * uncached_input_price + O * output_price
```

If caching is allowed but hit/miss/partition is unknown, reserve a miss at the highest applicable admitted input class:

```text
reservation = I * max(uncached_input_price,
                      cache_read_price,
                      cache_write_5m_price,
                      cache_write_1h_price)
            + O * output_price
```

Then apply the maximum admitted pricing modifiers, exact decimal rounding policy, and any non-token charges. In this branch, compare the reservation with the selected local currency cap before send. `max_tokens` is a genuine server generation ceiling, while this currency value is intentionally an estimate/reservation; models may stop earlier.

After a complete stream, a token-based reconciliation estimate can replace the worst-case partition only when every applicable category and modifier is known:

```text
uncached_input * p_input
+ cache_read * p_read
+ cache_write_5m * p_write_5m
+ cache_write_1h * p_write_1h
+ output_tokens * p_output
+ admitted non-token charges/modifiers
```

That is still a price-policy calculation, not an API-returned exact bill. Reconcile later to the aggregated Cost API where available. Until sufficient usage arrives, retain the original reservation; never release it as zero.

### Limit taxonomy

- **Genuine per-model limits:** non-null `max_input_tokens`, non-null `max_tokens`, and server validation/terminal context behavior.
- **Genuine account controls:** Anthropic's enforced monthly organization/workspace spend caps and rate limits. They are broader account controls, not a per-request authorization or returned request price.
- **Canonical policy choice (project inference):** use either (a) the local currency cap plus conservative reservation above or (b) a documented enforced provider spend limit. A provider cap is a broader account control and not a per-message returned price, but it can be the selected pre-send control; do not silently require both.
- **Estimates:** Token Counting output used before send and all client-side currency arithmetic. Do not label them actual billed cost.

## Exact unknowns carried forward

1. There is no machine-readable per-model text modality flag or price in the Models API.
2. Token Counting is officially free and separately rate-limited, but explicitly only an estimate; it does not predict the cache hit/write partition.
3. Messages/SSE does not return exact currency; the official cost report is delayed, aggregated, and incomplete for some tiers.
4. A cache-write amount cannot be priced exactly without the 5-minute/1-hour split.
5. Unknown/new usage categories or missing terminal usage prevent settlement; the safe state is reservation retained, not zero.
