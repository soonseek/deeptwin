# T023 shared conversation and exact-command evidence

Checked: 2026-09-08. Scope: work-bound messages, proposed commands, challenges,
button/chat validation and browser payload controller. This evidence does not claim
provider execution, graph execution, user-alternative capture or product-wide T023
completion. No provider, network, paid API, Keychain or user credential was accessed.

## Implemented boundary

- Messages retain exact work revision, order, semantic origin, actor kind and referenced
  entity versions. Ordinary text such as `응` remains an ordinary message and cannot mint
  an alternative, command or approval.
- A model-originated command proposal has no human authority. The server issues a short-lived
  challenge to the authenticated local human and binds validation to the exact command and
  immutable target. Button and chat routes share the same validator.
- Browser payloads never supply actor or authority. Session middleware derives the local human;
  unknown/duplicate JSON fields, query smuggling, stale revisions, cross-work objects and
  non-current targets fail closed.
- Validation returns `executed: false`. This slice creates an auditable validation receipt but
  deliberately does not dispatch a provider, tool or runtime action.
- A chat response message and its validation now share one `BEGIN IMMEDIATE` transaction. A
  failed response leaves no message, validation, event, command-state or challenge-state change.

## Failure-first correction and verification

An independent audit reproduced one material integration defect: a valid token/target combined
with the wrong response text returned HTTP 409, but the earlier two-call API implementation had
already committed a `command_request` message and `chat_message_recorded` event. A regression
assertion first failed on that side effect. The route now calls
`record_and_validate_chat_invocation`, which stages the message and validation in one transaction.

Root verification:

```text
PYTHONDONTWRITEBYTECODE=1 \
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q \
  app/tests/test_conversation.py app/tests/test_conversation_api.py \
  app/tests/test_server_api_v1.py
51 passed, 1 existing Starlette/AnyIO deprecation warning

PYTHONDONTWRITEBYTECODE=1 \
/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv/bin/python -m pytest -q \
  app/tests/test_conversation.py app/tests/test_conversation_api.py \
  app/tests/test_model_selection.py app/tests/test_model_selection_api.py \
  app/tests/test_usage_settings.py app/tests/test_server_api_v1.py
73 passed, 1 existing Starlette/AnyIO deprecation warning
```

Ruff reported `All checks passed` for the conversation service, route and tests.

A separate agent then re-audited the corrected tree without editing it. Its focused conversation
run passed **26/26** and its conversation/server regression passed **122/122**. Independent
canaries observed:

- wrong response, token, target, work revision and cross-work path: HTTP 409 and byte-for-byte
  equivalent message/validation/event/command/challenge projections before and after;
- success: exactly one message and validation plus ordered `chat_message_recorded` and
  `command_invocation_validated` events committed together;
- identical and changed chat retries after success: HTTP 409 and no new state/event;
- button failure: no change; button success and exact replay: one stable receipt;
- an injected exception after validation staging but before transaction commit: complete rollback.

The final audit verdict for this bounded conversation/validation slice was **CLEAR**.

## Reviewed hashes

| File | SHA-256 |
| --- | --- |
| `app/services/conversation.py` | `209094bdd9e35044998309cbbf3a6ac226e6ec9331fa9b9e2da2dd7d1e4ee219` |
| `app/api/conversation_routes.py` | `d2af663139fb4a40ab7f73e0a18ac2cbcc5576637f7782cd4037662069f360f6` |
| `app/tests/test_conversation.py` | `7ed54c5a07cab906b76e23b17bbbea1aef5abe1c59119f3bfb6b627c294e8a11` |
| `app/tests/test_conversation_api.py` | `afba4b4a5334e064e74373839769e7eed60bbf23ed958cbeca01be5e858a072b` |

`app/server.py` is a shared integration surface and continued changing after this bounded review;
its final release hash belongs in the later integrated evidence rather than this table.

## Remaining T023 work

The conversation service is complete only as a bounded T023 component. Provider credential GUI,
dynamic connection/catalog wiring, final same-space UI recovery and combined browser regression
must pass before T023 can be checked. Later command execution must independently enforce current
permission, budget and adapter authority; a validation receipt is never execution proof.
