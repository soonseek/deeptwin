# Claude semantic execution — accepted bounded design

2026-09-20. **Design accepted; Task46 scoped acceptance and exact ownership reconciliation are
complete. Task47 in resumption-plan.md is the bounded implementation authority.** This is the next connected provider behavior unit, not a
replacement product, production activation, release approval or whole T087/T090 completion.
Claude remains API-only. Managed Codex subscription remains mandatory separate work; no automatic
subscription-to-API fallback is authorized.

## Normative snapshots and explicit amendment

The following independently reviewed snapshots in `provider-semantic/` are incorporated:

1. [Semantic execution design](provider-semantic/post46-semantic-vertical-contract-draft.md),
   §§2–9: narrow full-operation worker/gateway/runtime behavior, ownership and proof sequence.
2. [Literal record/wire appendix](provider-semantic/post46-semantic-wire-record-appendix-draft.md),
   §§1–11: exact fields, codecs, bounds, state machines, custody and result joins. It takes
   precedence over the main snapshot's earlier illustrative sketches.
3. [Read-observation and cancellation amendment](provider-semantic/post46-read-observation-amendment-draft.md),
   §§1–5: explicitly adopted for the code-owned `claude-api-text-semantic-v1` profile of
   `provider-port-v1` only. This is the narrow exception now recorded in extension-ports§3.7.
   Fresh capabilities/catalog/status request identities obtain fresh observations; exact same-ID
   request/config replay remains immutable. Cancel is separately target-monotonic. Model-step
   semantic-key fencing, unknown-outcome no-resend and all existing semantic hash/schema bytes
   remain unchanged. No arbitrary input flag enables the exception.
4. [Gateway semantic request identity correction](provider-semantic/gateway-request-identity-amendment.md),
   explicitly adopted during Task47 R1 after [independent interface preflight](provider-semantic/gateway-request-identity-preflight.md)
   found no blocking issues. It adds required `request_id:U` to the new closed
   `provider-send-prepare-v1` and immutable local lease/registry tuple. Core derives it
   from the admitted request; the gateway pins it and uses it for all descriptors,
   including bodyless Models. Exact prepare digest covers it. This correction takes
   precedence only over the original appendix§7/§9 field omission; all other bounds,
   schema/hash identities, authority, sequence, cancellation and proof rules remain.
5. [Reservation currency type correction](provider-semantic/reservation-currency-amendment.md),
   explicitly adopted after [independent interface preflight](provider-semantic/reservation-currency-preflight.md)
   found no blocking issues. Only reservation.currency changes from lowercase identifier I
   to the exact existing API BudgetPolicy representation: three ASCII uppercase letters.
   Byte-exact equality to the frozen policy remains mandatory; no case conversion, default
   currency, new budget branch, exact-cost claim or settlement is introduced.
6. [Gateway local failure classification correction](provider-semantic/gateway-failure-class-amendment.md),
   explicitly adopted during Task47 R2 after [independent design preflight](provider-semantic/gateway-failure-class-preflight.md)
   found no blocking issues. One required nullable finite failure_class field is added
   to the new provider-send-result-v1 and provider-semantic-response-v1 only. It retains
   observed local cause without exception text, guessed retryability or remote-effect
   claims. Existing cancellation precedence, original deadline/no-wire fallback,
   bounded actual private bytes and full cleanup obligations remain binding.

The snapshots retain historical DRAFT and unapproved statements as provenance; this master
supersedes only their design/canonical-amendment approval gate. Their Task46 acceptance,
ownership reconciliation, implementation evidence and actual activation gates remain in force.
Historical relative links to scratch/canonical sources are provenance: authoritative current
product contracts are adjacent `extension-ports.md`, `runtime.md` and the existing specification;
the six normative snapshots above are the exact incorporated versions. Items4–6's DRAFT/
not-authority status is retained provenance and superseded only by this explicit adoption;
the corrections' implementation and behavioral proof remain subject to Task47 formal review.

The retained [official-source note](provider-semantic/post46-claude-api-source-reference.md)
supplies format research, not real capability/currentness/pricing or provider authorization.
The [independent review](provider-semantic/post46-semantic-design-preflight.md) preserves the
initial three P2 findings and clean bounded R1 re-review. No product/test code may load these
Markdown files or ignored scratch to obtain a verdict, policy value or synthetic authority.

| Snapshot | SHA-256 |
| --- | --- |
| Semantic design |7177e9cd27e1813f6b42344437e73593ef0ba1537714acfbefe6fd76bd02c513|
| Literal appendix |dcf68d94934aac3e0dc1078a9620f4cdb7c6c12c70682f32681c8ca19b410fd4|
| Read/cancel amendment |3599b84bbb08e5fdf93675f67dffb657d9cfcb48d2153c8904d231d5d97c4ebe|
| Source reference |62764974a8f702d386fb36848a105181c9f2f50bc1831d465d1ecd9a3a260f4b|
| Review with R1 |396390b65fef39bb3b1ae897a40211dcb53d01c32c24235d5a3c5eaa0079db4f|
| Gateway request identity correction |3458cadbcd89b1d6fe4875146c3f96a0bc2e044adb5e95c140eb47c6b6e904c8|
| Gateway identity preflight |8707a6299cf3380af4c093675c314db8caeabedc5fb94cc56c64745e9768fa4b|
| Reservation currency correction |abc13f808136b18b2c0d9eb4a81821861d04ecbb02410006e977f34f7de70632|
| Reservation currency preflight |731eae011c4ba7d6b6ea51ef88c99607018082ee694d253f43d79b1fed62682a|
| Gateway failure classification correction |cdab83d07f32a488e500523f77753912c6a9efa973c276b59d48ff2615d78292|
| Gateway failure classification preflight |540612c38357cc2f05ab221696d69855e0eeae4b6a99b800cf3b638b4b748a68|

## Decisions, costs and dispatch boundary

F1 is resolved by an explicit profile-scoped read-observation exception, not changed hash bytes
or invented purpose/binding versions. Cost: fresh UUID discipline and additional immutable
observations. F2 supplies one optional absolute custody budget through controllable locks,
SQLite and complete metadata checks, preserving old defaults and every integrity check. Cost:
two narrow support-file changes, contention refusals and timing/resource regressions. F3 uses
the exact immutable connection snapshot as the sole authorized opaque handle, pinned through
config/binding, authenticated prepare, lease and actual encrypted delivery. Cost: changed
credential/connection revisions require matching new handles/config/bindings.

Task47 R1 additionally exposed an unimplementable descriptor-identity omission: the
gateway cannot invert operation UUID5/SHA256 to obtain a semantic request UUID and
has no DomainStore. The adopted minimal correction carries that UUID explicitly;
it does not weaken descriptor identity to broker/dialogue IDs or expand gateway trust.
Cost is one required UUID in the new prepare/lease and the five specified proof groups.
The original snapshots stay byte-identical; no activated protocol migration, new product
file, production issuer or Task47 implementation acceptance is implied.
The same composed fixture exposed an empty intersection between reservation.currency:I
and the existing API BudgetPolicy uppercase currency. Item5 fixes only that field type,
preserving policy equality, all reservation authority joins and held provisional cost.
Cost is a narrow validator/schema correction and its required positive/negative proofs.

Task47 R2 exposed a second closed-wire omission: local gateway failure categories
required by appendix §10 cannot be derived from HTTP status/phase/cancellation.
Item6 adds only the finite cause field and its durable copy. Ruling: preserve observed
causes explicitly instead of overloading fields or guessing exception strings. Cost
if wrong is scoped new-profile validator/wire/schema rework, not weakened authority
or legacy migration. Expiry never grants another transfer window; missing results
cannot create gateway evidence, and possible effects retain conservative accounting.
The design preflight closes no implementation finding; R2 proofs and review remain.

Task46 is now accepted at807-source hash db384ceb994654c40ae0388d3358e18f7edff90ee01197ce99f514fa9adf9318.
Controller reconciled19 absent new paths/seven exact existing beforecopies and published Task47's
finite implementation brief. One new sole writer may implement it with RED/GREEN evidence and
independent review; no concurrent Task46 product writer remains. Do not label a source-only or always-denied path
complete: controlled proof must use actual encrypted custody, authenticated streams, captured
local HTTP bytes, real store/ledger and provisional accounting.

No production composition/HTTP registration, real key, paid provider request, native collector,
new dependency, root/container/image/scanner operation, release signing/publication or actual
user-store change is authorized here. Synthetic authority is test-owned and cannot enter
production assembly. Genuine C/binding/current permissions and connection producers, reviewed
text/compatibility/reservation evidence, new artifact admission, native/transport fit and browser
integration remain explicit later work. Missing exact currency retains budget reservation even
for valid text; it is never fabricated as zero. Whole-product estimate remains about50% including
design, and the full graph/lens/paired-queue/human-promotion journey remains incomplete.
