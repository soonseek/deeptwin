# The direct-adapter Claude live path (2026-09-24)

Status: **the product path to a real Claude call exists and is proven offline against a mock
transport. The one owner-authorized live call waits for the key.** T048, T090 and T087 stay
open. This is not the release isolation boundary.

## Decision

The owner authorized real, budget-capped Claude API calls and chose the direct-adapter profile
over the release architecture:

- The key and the provider call share the control-plane process.
- The key lives in server memory only.
- The call goes through the existing, offline-verified official-SDK adapter
  (`app/adapters/claude_api.py`).

The release path is not replaced. It remains open: a separate credential gateway and provider
worker, with authority from extension installation, qualification and binding records (T090 and
T087).

Budget authorized by the owner:
- at most 10 calls
- 512 output tokens per call
- $1 in total

Default model: `claude-opus-5`.

## What landed

### Owner's connection (`claude-connection-v1`, five routes)

`app/services/claude_connection.py` and `app/api/claude_connection.py`. Installed routes went
from 62 to 67.

- `POST /api/v1/connections/claude/key` stores the key in an `InMemoryCredentialVault`.
  - The key is never written to disk, the DB, a log, an event or a response.
  - A restart forgets it.
  - Storing it makes no provider call.
- `GET` returns `key_present`, `key_storage: server_memory_only` and the last catalog's model
  ids. It never returns the key, a hash or a handle.
- `POST …/forget` drops the key.
- `POST …/catalog` is the owner's explicit, free `GET /v1/models` read.
- `POST …/model-choice` seals an owner-authored `model_choice` record (`claude-model-choice-v1`)
  for a model the refreshed catalog actually listed, with `model.selected`.

### Code-owned run executor (`app/services/claude_run_executor.py`)

`main()` now wires this executor. The run route was unavailable in production before.

- **Compile authority.** Built from the vault's own records: the owner's `model_choice` records,
  budget policies and observation contracts. There are no tools and no grants, so a graph that
  asks for them does not compile.
- **Handlers.**
  - A deterministic entry node seals the run's work revision text as the source artifact.
  - Deterministic, human-gate and join nodes forward their producer's artifact.
  - An **agent** node makes one Messages call with the model its binding names and the upstream
    text as input, then seals the text as the node's artifact (viewable through the run
    artifact routes), with the provider message id, observed model, usage and stop reason.
  - Routers and loops fail the node instead of guessing.
- **No double billing.** Before sending, the executor seals an intent record at an identity
  derived from the run and the visit. A replayed or resumed visit that finds its intent does not
  call again.
- **Budgets.** Calls per run are bounded by the run's `BudgetPolicy.max_model_calls`. Calls per
  process are bounded by `DEEPTWIN_LIVE_MAX_MODEL_CALLS` (default 10). Output tokens per call are
  bounded by `DEEPTWIN_LIVE_MAX_OUTPUT_TOKENS` (default 512), by the policy's output bytes and by
  the model's own limit.
- **Failed calls.** A call that does not complete seals an outcome record and fails the node.

### Records page

It gained a Claude connection panel (`claude-connection.mjs`):
- a masked key field, cleared right after sending
- store, forget and catalog-read buttons
- a model choice from the refreshed list

## Observed (offline, mock transport, no network, no key)

- `test_claude_live_path.py`: **3 passed**.
  1. Store the key (not in the response), read the catalog, refuse an unlisted model, choose the
     model (`model.selected`), create a real work, graph, consent and run. Exactly one Messages
     request goes out, with `x-api-key` present only at send time, `max_tokens=64`, and the work
     text in the prompt. The writer's artifact records the model, usage and stop reason, and the
     model's text reads back through the run artifact route. Replaying the command sends nothing
     new. The key appears in no stored record or event.
  2. With the process cap at 1, the second run's agent node fails without sending (`run.stopped`
     `infrastructure_failure`, 503).
  3. After forgetting the key, nothing is sent.
- `claude-connection.test.mjs`: 3 passed. `records-page.test.mjs`: 3 passed.
- Route-count, composition, server, extension-architecture and works/runs suites: 237 passed.
- Browser (records, owner lifecycle): 4 passed.
- Adapter offline suite `test_claude_api.py`: 106 passed. The environment has `anthropic`
  1.4.0 (locked) and `httpx2` 2.13.0, one minor above the provider lock's 2.12.0.

## The live call (pending the key)

`app/tests/test_claude_live_call.py` runs only when the operator sets
`DEEPTWIN_LIVE_ANTHROPIC_API_KEY`. The owner adds it in the environment settings, and it is
never pasted in chat. The test makes:
- one free catalog read
- **one** Messages call on `DEEPTWIN_LIVE_MODEL` (default `claude-opus-5`) with
  `max_output_tokens=64`

It goes through the same product path and writes non-secret evidence (model, message id, usage,
an output excerpt) to `DEEPTWIN_LIVE_EVIDENCE_PATH`. `api.anthropic.com` is reachable from this
environment: an unauthenticated probe returned 401.

## Known limits

- **Failure classification.** A node failure, including a budget stop, ends the run as
  `infrastructure_failure` with HTTP 503. This is the existing run service's classification, not
  a statement about the provider.
- **Scope.** There is no design generator: the graph is supplied, as a test actor would. There
  are no tools, no streaming to the UI, and no key persistence.
