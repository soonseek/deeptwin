# Evidence — Task 24 step (c1): installation anchor and success consumption codecs

- Date: 2026-09-18
- Task: Task 24 redraft step (c) "pure record/head/consumption-v2 codecs, absent-only", first
  half (c1): the domain anchors. Contract: `contracts/deployment-receipt-journal-v3.md` §4
  (installation anchor, consumption anchor v2, coexist ruling) and §7. Precedent: journal v2 §4/§8
  and `app/domain/deployment_receipt.py`.

## Frozen identities

```
5fb0151b656b24d82f3b9dc95c88a90b00321262d1d79b6b818bb27376a2735f  app/domain/extension_installation.py
95124ad86218a28dd87ab2a730c28bcce20b699f0c35bd41f76ed6f0ccaad8a0  app/domain/deployment_receipt.py
8a9d0315140c54c834bb87544a267d1d836e51956d1e3b80ec37d56c67842b92  app/domain/schemas.py
e094b56d87a3cb213627a2586c3ccdc25fc5b87e66e116860dc18b025b5c49b5  app/domain/schema_exports.py
88594b484c32734c636d41a767e17066f5980970c80596bc4ca1cc51024b4f33  schemas/v1/domain-envelopes.schema.json
e394c6f0b76d8c49b0297deb2cbf2eb7104c11910cdade1bfab1da7cdd21c862  app/tests/test_extension_installation_domain.py
655cb21585a9be2a4f1429d7ba435fc59a598a93f31315d01082569d99485cc1  app/tests/test_deployment_prepare.py
864c2439ec0e29a3114724d320bbfe87bce4a830cdc89a7620b0bf9aae74c67f  app/tests/test_extension_lineage_contracts.py
```

## What was built

- `app/domain/extension_installation.py` (new): `installation_content_schema()` — the closed
  `extension-installation-anchor-v1` content (17 fields, `additionalProperties:false`, all
  required; Id/BrokerId/hex64/`sha256:`+hex64 grammars through the candidate `text()` helper whose
  lookahead anchoring refuses a trailing newline; platform enum; three-fractional-digit Time;
  `state:"staged"`, `revision:1`, `previous_record_digest:null`, `staging_authority:
  "deployment-receipt-v1"`) — and `validate_installation_body(body)`: version 1, purpose
  operational, ordered parents `[request_ref, receipt_ref]`, `receipt.id == request.id`, actor
  equality, `created_at_utc` = padded `installed_at`, operational evidence blob 1..8192 B, UUID
  consume command id, integer revision, 8192-byte body cap; one closed message.
- `app/domain/deployment_receipt.py`: `consumption_content_variants()` (v1 with two parents, v2
  `deployment-receipt-consumption-anchor-v2` with `winning_lifecycle_revision:3`,
  `outcome:"succeeded"`, `effect_ref` of kind `extension_installation` and three parents);
  `consumption_content_schema()` is the `oneOf`; `validate_consumption_body` dispatches on
  `schema_version` and requires the effect as the exact third parent for v2. v1 behaviour is
  unchanged (precedent suite green; v1 with an effect or three parents, v2 with two parents or a
  receipt as effect are refused).
- `app/domain/schemas.py`: kind dispatch for `extension_installation`.
- `app/domain/schema_exports.py` and the regenerated `schemas/v1/domain-envelopes.schema.json`:
  a new `extension_installation` envelope branch (two ordered parents, version 1, operational)
  and the consumption branch as a `oneOf` pairing each content variant with its exact parent
  arity. The other three exported schemas are byte-identical.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES; all folded in RED-first:

1. MUST — the local `^…$` patterns admitted a trailing LF in `extension_id`/`service_identity`
   (jsonschema uses `re.search`, where `$` matches before a final newline; confirmed through
   `ImmutableRecord.create`) → the canonical `text()` helper with its lookahead anchoring; three
   trailing-LF cases added to the schema test; export regenerated.
2. SHOULD — the export admitted a v1 consumption with three parents and a v2 with two → the
   branch is a `oneOf` pairing content variant and parent arity (`consumption_content_variants`);
   tests assert the arity per variant and the two crossed shapes refused, the corrected v1 admitted.
3. SHOULD — `different_ids` and the cap case passed partly through the parent rule → the
   `different_ids` parents now match the mutated content (only the id rule refuses); the 8192 cap
   is exercised on the validator directly with matching parents (the closed content and headers
   cannot exceed it on their own).
4–5. NIT — the runtime effect kind/version and integer-revision checks are unreachable behind the
   schema; kept as defence with the comment corrected.
- Judged, not flagged: the codec cannot know host generation of the anchor id (the contract asks
  no refusal); floats are refused by `canonical_json` before the schema; `True` is refused by the
  schema's integer type.

## Verification

- TDD: RED retained — `ModuleNotFoundError: No module named 'app.domain.extension_installation'`
  and `DID NOT RAISE DomainContractError` ×14; closures RED first (trailing-LF admitted,
  `KeyError: 'oneOf'` on the export branch), then GREEN. Three test-side corrections (the record
  API exposes `.ref`/`.body`/`.as_dict()`; `_constant` carries a type; the export's top-level
  `$ref` is `Record`).
- Covering: **145 passed** — installation domain 30, receipt domain, domain schema exports,
  receipt journal integrity and reconciliation, receipt import. Ruff clean on the new/changed
  codec files; `schemas.py`/`schema_exports.py` keep exactly their pre-existing I001/C408 findings
  (verified against HEAD).
- Full regression (`app/tests deploy/tests`, watchdog 1500 s): **5997 passed, 2 failed, 2
  skipped** on the codec change; both failures were pre-existing tests that the accepted contract
  necessarily touches, adapted afterwards and re-run green with their whole modules (170 passed
  across `test_deployment_prepare.py`, `test_extension_lineage_contracts.py`, the installation
  domain and the domain export suites); no `app/` code changed after the full run:
  1. `test_existing_68_schema_artifacts_remain_byte_identical` pins the 68 pre-Task-22 artifacts
     against a local manifest; `schemas/v1/domain-envelopes.schema.json` is now regenerated by
     this step as journal v3 §4/§7 require → the test names that one authorised regeneration (the
     export stays pinned to the live `domain_schema()` by `test_domain_schema_exports`) and keeps
     the other 67 byte-identical.
  2. `test_any_actual_historical_managed_kind_denies_new_first_only_prepare[extension_installation]`
     inserted a free-form `extension_installation` row to prove the global guard; the row is now
     admitted with the anchor codec monkeypatched out for that kind only (the guard denies on any
     row of the kind, whatever its schema; the codec is proven by its own suite).

## Boundaries kept

- Pure codecs only: no storage layout, migration, service, observer, consume transaction,
  installation head, route or event registration (those are (c2)–(f)); valid structure grants no
  installation, acceptance or head authority; `extension-installation-v1` (registry shape) is
  untouched and coexists per the contract's ruling; no GUI.
