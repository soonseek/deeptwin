# Domain foundation first slice — T004/T005/T006

2026-09-07. Implemented common immutable bytes/references, actor provenance syntax,
separate observation metadata, acyclic initial record formats, 70 exact event metadata
allowlists and versioned JSON schema exports. This is not domain persistence, session
authentication, full per-feature content schemas or complete runtime authority.

## Test-first evidence

Interpreter initially `/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python`.
Commands used `-m pytest app/tests/test_domain_contracts.py`, then added
`app/tests/test_domain_events.py` and `app/tests/test_domain_schema_exports.py`.

- First domain test collection failed because `app.domain` did not exist; then 58 passed.
- Independent spec review reproduced CPython's uncontrolled oversized-integer ValueError.
  New positive/negative 5000-digit cases plus optional locator fields: 3 failures, then
  bounded parse_int/ObjectRef implementation passed. The canonical UTF-8 vector hash was
  independently calculated with Node crypto before accepting the vector (not guessed).
- Reviewer and root found circular first actor/policy hashes. New two genesis-chain tests
  failed for missing factory methods, then passed with actual computable hashes. ADR-008
  changes only bootstrap representation; parsed JSON does not install roots or confer authority.
- Event tests first failed for missing module. Payload-canary cases exercise every registered
  event type; their parameterized count is not hundreds of independent user journeys.
- Quality review found whole-string UTF-8 allocation before rejection. The 8 MiB regression
  measured 8,389,477 added peak bytes before correction and passed below 1 MiB after an early
  character-count guard. This is a narrow resource regression, not a product memory benchmark.
- Growth enum drift was corrected: loop events now use the exact seven growth stop reasons;
  comparison validity is valid/invalid/pending, separate from critic not_checked. New tests
  failed before correction. Together focused domain/event tests: 774 passed.
- Export tests first failed for a missing module; two now pass and match checked-in JSON.
  A separate reviewer also checked Draft202012 schema structure, five real-hash records and
  15 malformed roots using the already available jsonschema library (no new install).
- Integrated baseline environment run before the final memory/enum/export additions:
  1501 passed, 1 existing warning in 10.44s. Later fresh locked-environment integration:
  1505 passed, 1 warning in 10.74s, explicitly excluding the concurrently developing
  `test_domain_storage.py` (not part of this slice).

## Review and scope

Independent specification reviewer rechecked oversized integers and acyclic roots: original
two findings closed, no new important defect within this slice. Independent quality reviewer
rechecked memory guard and exact enums: finding closed. Source implementation and root chain
do not treat fake placeholder refs as resolved records; resolution belongs to storage tests.

Fresh task-agent creation worked for the first spec review, then hit the active agent/thread
limit. A reviewed agent was reused for isolated export implementation; root and a different
reviewer cover integration/quality. No claim of a fresh-context implementer for every task.
This preserves useful separate review without inventing compliance with a tooling ideal.

T004 module/import scaffolding is complete, using stdlib-only additions and secret-free
test dependency comments. The later storage and permission slices now supply the previously
open missing-reference, foreign-vault, spoofed-human and verified-object authority cases.
Together with exact event/schema-export tests, that closes the bounded T005/T006 foundation.
On 2026-09-07 the exact fresh environment reran the combined contract, event, export, storage
and permission set: **867 passed in 2.51s**; the subsequent whole-app run was **1,627 passed,
1 existing warning in 13.15s**. CanonicalValue envelopes do not replace each feature's typed
graph/alternative/approval payload schema. No existing B1 encoding was changed.

Current foundation source hashes are recorded below. Storage and permission implementation
hashes remain in their own evidence files.

| File | SHA-256 |
|---|---|
| `app/domain/refs.py` | `260a8c2df1f5413480d21142a1be6043363033e4ec9f8005c3987e4f007c203a` |
| `app/domain/schemas.py` | `2a577d1e199affdfc2be7a07c5fd2e1d234b0bb4cd56516a3d662770852470da` |
| `app/domain/events.py` | `d0af278cc2e1df21f255148af10c5de141f1a13cc4eda2c76ec29c99a261ddbc` |
| `app/domain/schema_exports.py` | `20af66ebffcb1387ddcb30dfa082c10c652e5215419d80c50ff156bd01e6548f` |
| `schemas/v1/domain-envelopes.schema.json` | `f14304fc8dc9a939d3786f9ea134c51cd37fab9a253005853c9328c30ca0a4d4` |
| `schemas/v1/event-metadata.schema.json` | `2a535958b976e9518084bbc91483d7eab8f9bc81f593810d62806fcadc813e3f` |

No live models, actual human alternatives, operational approvals, native package claims,
publication or commits arise from these development fixtures.
