# T022 model catalog and selection evidence

Status: implementation and independent final review complete. No live provider request, paid call,
login mutation, Keychain read, or public action was performed.

## Implemented boundary

- `ModelCatalog` keeps three distinct mode keys: Claude API, Codex ChatGPT subscription, and the
  separately selected Codex API mode. Snapshot reads are local and lazy. Only an explicit
  `refresh` crosses an injected provider boundary, with `explicit_action=True` for API adapters.
  There is no subscription/API fallback.
- Codex subscription entries come from every complete app-server `model/list` page. Claude and
  Codex API entries come from their isolated adapter snapshots. Production source contains no
  current account model name. Source provider/mode identity, collection bounds, duplicate model
  IDs, multiple subscription defaults, reasoning shapes, and capability claim shapes are rejected
  at aggregation rather than repaired or guessed.
- Each immutable snapshot binds provider, auth/billing mode, opaque credential/account binding,
  opaque workspace/project/organization binding, retrieval time and bounded API validity, a local
  request epoch, the separately preserved adapter request epoch when supplied, source catalog and
  credential/binding generations, raw capability claims, per-model claim digests, and a
  whole-catalog digest-derived ID. The local epoch remains monotonic even when a restarted adapter's
  in-memory source epoch begins again; the two are not mislabeled as one authority.
- A saved choice must contain its model and explicitly selected effort/thinking mode in its original
  catalog. Before use, that immutable provenance is revalidated through a fresh current catalog for
  the same provider/mode/connection/workspace, so a fresh same-model catalog does not force a user
  to resave, while removed models and unknown capabilities fail closed. API validity uses an
  injected clock and the current catalog's persisted `fetched_at_ms`/`max_age_ms`.
- A work policy supports a global default plus purpose and agent overrides with deterministic
  `agent > purpose > default` precedence. Each run/purpose/agent stores its effective immutable
  provider/mode/catalog/model/effort/thinking choice, resolution source, required capabilities, and
  policy version. Later catalog/default changes cannot rewrite that historical record.
- `freeze_for_run` resolves optimistically, then starts `BEGIN IMMEDIATE`, rechecks the policy, the
  original catalog integrity/provenance, the exact current validation catalog, expiry, model,
  connection, and workspace before inserting. The transaction fences concurrent local catalog
  refresh writes. API connection-state checks are local adapter reads and never fetch a catalog.
- Existing one-choice work/understanding APIs remain compatible. Historical legacy tables and
  records are not relabeled or rewritten. Provider discovery describes Claude as API-only and
  Codex as subscription-default plus an isolated optional API mode without probing credentials or
  claiming execution readiness.

This follows the official [Codex app-server documentation](https://learn.chatgpt.com/docs/app-server),
which directs rich clients to call `model/list` and use returned effort/modality fields, and the
official [Codex authentication documentation](https://learn.chatgpt.com/docs/auth), which separates
ChatGPT subscription authentication from usage-billed API-key authentication. Claude catalog rows
follow Anthropic's official [List Models API](https://platform.claude.com/docs/en/api/models/list),
including pagination and nullable capability information.

## Failure-first and adversarial evidence

1. The original T022 contract began at **9 failures / 1 pass** because multi-mode catalog sources
   and work policy APIs did not exist.
2. Projection tampering and frozen required-capability coverage then produced **2 failures**;
   digest validation and exact requirement freezing closed them. Thinking shape/selection coverage
   produced **2 further failures** before positive-claim validation was added.
3. Independent review reproduced three defects: an old catalog ID could be combined with a model
   added only in the new catalog; a current catalog refresh between resolve and insert could freeze a
   removed model; and expired API catalog state could validate indefinitely. Regression tests now
   reject the first two and enforce current-catalog validity while allowing a fresh same-model
   catalog to revalidate the saved choice.
4. The resumed implementer review added source identity, duplicate/default/capability shape,
   workspace mutation, independent epoch provenance, and original capability-provenance cases.
   The first run was **17 passed / 5 failed**, and a separate newer-current/original-corruption case
   failed **0/1**. All now pass.
5. Freeze adversarial cases replace the current state, payload, API connection state, workspace, or
   original payload after resolve and before the write transaction. All reject the insert, leave
   `run_model_choices` empty, and prove that no second provider fetch occurs.
6. A final independent audit copied a complete previously valid payload A into current storage row
   B while retaining B's authoritative columns. Snapshot, validation, and freeze all accepted the
   retired model before the fix (**0/3**). Stored reads now compare payload identity against row ID,
   provider, mode, retrieval time, connection/workspace binding, local request epoch, and capability
   digest; all three surfaces now reject the cut-and-paste.
7. The implementer then tested the adjacent head-pointer rollback: changing only current state to a
   valid older row was accepted by snapshot, validation, and freeze (**0/3**). Current reads now
   require the catalog row's local epoch to equal the durable latest epoch for that exact
   provider/mode/binding. Snapshot reports error and validation/freeze reject on all three surfaces.
8. A different agent then reran both three-surface manipulations (**6/6 fail-closed**), mutated each
   of the eight authoritative row columns independently, ran four service instances through
   concurrent epochs 2–9 and a restart/refresh to epoch 10, and exercised all six cross-mode
   catalog-choice combinations plus Claude subscription. It reported **CLEAR** without editing the
   implementation or evidence.

## Exact verification results

Focused catalog/selection/provider/API command:

```text
PYTHONPATH=. <workspace>/.venv/bin/pytest -q \
  app/tests/test_model_catalog_selection_v2.py app/tests/test_model_catalog.py \
  app/tests/test_model_selection.py app/tests/test_providers.py \
  app/tests/test_model_selection_api.py
```

Result: **65 passed**, 1 existing Starlette/AnyIO deprecation warning, no failure.

Bounded Claude/Codex adapter, connection, understanding, and critic integration command:

```text
PYTHONPATH=. <workspace>/.venv/bin/pytest -q \
  app/tests/test_claude_api.py app/tests/test_codex_api.py \
  app/tests/test_codex_api_mode.py app/tests/test_codex_connection.py \
  app/tests/test_understanding.py app/tests/test_codex_understanding.py \
  app/tests/test_critic_contract.py app/tests/test_critic_trial.py \
  app/tests/test_critic_audit.py app/tests/test_codex_critic.py
```

Result: **512 passed, 1 skipped**, 1 existing deprecation warning, no failure.

Final broad Python command while a separate T023 API test was deliberately red/incomplete:

```text
PYTHONPATH=. <workspace>/.venv/bin/pytest -q app/tests \
  --ignore=app/tests/test_conversation_api.py
```

Result: **1,996 passed, 1 skipped**, 1 existing deprecation warning, no failure. The unignored command
at the same point stopped during collection because the concurrently added T023 API test imported a
route module that its owner had not created yet. A complete pre-T023-red run had passed 1,993 / 1
skipped. Neither concurrent red phase is presented as a T022 failure or silently called green.

Full six-file Chromium command:

```text
env CONTROL_PYTHON=<workspace>/.venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
PYTHONDONTWRITEBYTECODE=1 \
<node-runtime>/dependencies/node/bin/node \
  --test --test-concurrency=2 \
  app/tests/browser-codex-connection.test.mjs app/tests/browser-first-use.test.mjs \
  app/tests/browser-model-selection.test.mjs app/tests/browser-speech-input.test.mjs \
  app/tests/browser-state-review.test.mjs app/tests/browser-understanding.test.mjs
```

Result: **68 passed**, no skip or failure, in 141251.607291 ms.

After the final storage-row/head hardening, the directly related browser file was rerun at the final
T022 hashes:

```text
env CONTROL_PYTHON=<workspace>/.venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
PYTHONDONTWRITEBYTECODE=1 \
<node-runtime>/dependencies/node/bin/node \
  --test --test-concurrency=1 app/tests/browser-model-selection.test.mjs
```

Result: **8 passed**, no skip or failure, in 24978.86375 ms.

The earlier work-switch browser observation remains candidly recorded: a prior
`browser-model-selection.test.mjs` run produced **6 passed / 1 failed**, and its exact isolated retry
produced **0/1**, observing `medium` before the expected `low`. A separate UI owner then made the
work-switch loading marker synchronous and added a named regression. The final 68-case run above
passed both the original restoration case and the new marker regression; no T022 static file was
changed to obtain that result.

Compile and lint commands:

```text
PYTHONPATH=. <workspace>/.venv/bin/python -m compileall -q \
  app/model_catalog.py app/model_selection.py app/providers.py \
  app/tests/test_model_catalog_selection_v2.py
<workspace>/.venv/bin/ruff check \
  app/model_catalog.py app/model_selection.py app/providers.py \
  app/tests/test_model_catalog_selection_v2.py app/tests/test_model_catalog.py \
  app/tests/test_model_selection.py app/tests/test_providers.py \
  app/tests/test_model_selection_api.py
```

Result: compile passed; Ruff reported **All checks passed**.

## Exact reviewed hashes

| File | SHA-256 |
| --- | --- |
| `app/model_catalog.py` | `b411302245642268be79a58df585f0bce07034253f665c9d2ba959faabf5ec7e` |
| `app/model_selection.py` | `9cae2a63a26e3dece5f3e9e965e71d0e2647783aa8361f7db41e051badd13f83` |
| `app/providers.py` | `fcd451809633d9ec0fbe109205d1001d88ea0c3a7323b86046007e3dc524b22e` |
| `app/tests/test_model_catalog.py` | `4e2caded1d1cfedfcad9ebf83e95133c9f390743f0edafdd2d9498ce8a62ab87` |
| `app/tests/test_model_catalog_selection_v2.py` | `efdd117e886fa504384456f4246c8068d456bb4f8f3e0bc4fde8e4b8dec8625d` |
| `app/tests/test_model_selection.py` | `e37d9e0879e82a0aec7bf8585ea165ab740a103ce44032820e28085b74f4fa45` |
| `app/tests/test_providers.py` | `da351aba1b7640e9ca5a3d97db7d09e2996e9e0c3a66757554f88b636ff5b6b0` |
| `app/tests/test_model_selection_api.py` | `b7e1d5857285f90eba5293dff7998bf3a7475d590f7c63fd5e4299afa6769f3c` |

## Honest remaining scope

- This layer can check adapter `connection_state`, binding, workspace, source catalog metadata, and
  expiry without credential access. Existing adapters do not expose a pure public method returning
  the currently issued catalog ID. Therefore an out-of-band adapter refresh that supersedes a
  service snapshot after the last fence can only be rejected by the adapter's mandatory
  pre-dispatch issued-snapshot validation. T023/T042 wiring must preserve that final authority check;
  this service must not imitate it by reading Keychain state or private adapter fields.
- SQLite `BEGIN IMMEDIATE` atomically fences local catalog writes, but cannot lock an independent
  in-memory provider adapter. A provider invalidation immediately after the local fence is likewise
  a pre-dispatch adapter rejection, not permission to execute with the frozen history record.
- T023 must expose API credentials/bindings and per-agent/purpose selection through the GUI and
  command/session authorization boundary. The existing UI still uses its older Codex-only route.
- T042/provider qualification must bind frozen choices to actual graph turns, compare requested and
  observed model/effort, and prove multimodal/tool behavior. Catalog presence is not execution proof.
- Codex `/v1/models` rows do not positively establish modality or reasoning effort in this adapter,
  so those capabilities remain unknown and fail closed. Nullable Claude capabilities do the same.
- Digests detect ordinary persisted-row corruption and cross-binding mistakes; they are not keyed
  integrity against an attacker able to rewrite the entire local database and all references.
