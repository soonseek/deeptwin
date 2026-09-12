# T009/T010 purpose and compiler firewall — bounded implementation evidence

2026-09-07 · process-local slice; persistent/session integration remains open.

The implementation in `app/domain/permissions.py` separates immutable `Actor` provenance
from live host-issued `Principal` objects. A copied dataclass, JSON actor/grant, provider/test
actor, unknown/revoked local session or object from another policy engine has no authority.
Exact subject, action, immutable ref, purpose, episode, policy revision and bounded expiry
must all match before a loader runs, and are checked again before loaded bytes are returned.

The policy registers storage-verified record descriptors before access. It recursively binds
explicit parent/content refs and fails closed before loading if any required ref lacks an exact
grant. Runtime purposes cannot widen through a new grant. Inquiry audit is only directly
readable by an authenticated human in its exact episode. Raw own alternatives, `H_phi/S_phi`,
sealed evaluation truth, declared secrets and transitively derived records are marked sensitive
and cannot become operational/compiler inputs by changing a label.

Compiler input uses a fixed typed projection with only condition, action, exception, prediction,
target, change kind and per-field behavioral support refs. It requires a separately trusted
verification receipt, exact available non-sensitive support, compiler-scoped grants and an
unprotected target. Model-authored `verified=true`, private metadata and raw alternative text
are never projected. Source withdrawal immediately invalidates grants/projections. This policy
boundary does not prove the truth or effect of projected text; later independent verification
and the full growth loop remain mandatory.

Failure-first state was observed as **34 failed** because the module did not exist. The first
implementation run had one remaining inquiry/human-scope failure; after separating human
episode access from runtime taint denial, **34 passed in 0.09s**. The exact fresh environment
then ran **1,598 app tests in 12.59s**, with one pre-existing Starlette/AnyIO deprecation warning.

Current hashes:

| File | SHA-256 |
|---|---|
| `app/domain/permissions.py` | `8896077179745c1d9750729ddbe5b6151e783bfd4e8df2e4b79dac274c76b279` |
| `app/tests/test_domain_permissions.py` | `21eb58dc7f62504c69125178149f289a403e2a8043e3d81716cc8f8041dd0996` |

Limits: this registry is deliberately process-local. It is not yet stored atomically beside
records/events, connected to `DomainStore` metadata-only lookup, or enforced by the local HTTP
session/command boundary. Direct human-scoped projections for non-text alternatives and typed
diagnosis inputs still need dedicated schemas; denying their raw use does not remove those
product requirements. No user database, credential, model call or network service was used.
