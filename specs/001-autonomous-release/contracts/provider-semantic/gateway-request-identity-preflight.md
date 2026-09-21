# Task47 gateway request identity — independent interface preflight

Verdict: **READY for controller promotion of this bounded correction.**

Findings: **0 Critical, 0 Important, 0 Minor.** No blocking ambiguity identified.
This is a design/interface verdict, not R1 implementation acceptance or closure of I8/I15.

## Reviewed authority and limits

Read the complete proposed amendment at
`.superpowers/sdd/resumption-plan/task-47-gateway-request-identity-amendment.md`, SHA-256
`3458cadbcd89b1d6fe4875146c3f96a0bc2e044adb5e95c140eb47c6b6e904c8`.
Read the current accepted master completely and checked the literal appendix's descriptor,
prepare/digest, channel routing and lease requirements in §§7/9 against retained authority.
No moving product/test code was inspected, no test was run, no helper was used, and no file
other than this review was written.

## Assessment

The demonstrated contradiction is real. Appendix §7 requires the semantic request UUID in
every stream descriptor, but its original closed gateway prepare has only operation_ref and
request_sha256. Neither value supplies the UUID to a gateway without DomainStore access.
A bodyless Models exchange has no request-body descriptor from which even an untrusted UUID
could be observed. Adding a required explicit request_id is sufficient to resolve this without
changing the gateway's authority or weakening the descriptor identity rule.

The amendment supplies a complete implementable ownership chain: the core derives the UUID
from its admitted canonical request and checks the exact operation/digest join; authenticated
prepare carries it; the exact prepare digest covers it; the issued lease and registry's frozen
tuple pin it; the gateway uses it for response descriptors; and core compares the response to
its original admitted UUID. Messages additionally checks the request-body descriptor before
body acceptance/READY. A coherent worker/descriptor substitution therefore cannot redefine the
core admission. The gateway is explicitly not asked to authenticate a DomainStore fact that it
cannot resolve.

Keeping commit/cancel/result field sets unchanged is sound: their existing authenticated
dialogue/sequence, exchange and prepare-digest joins select the pinned exchange. The added
field is not another spend permit or replay key. Catalog pages retain one semantic request UUID
while per-exchange/dialogue/broker/batch identities remain distinct, so bodyless and multi-page
operations are both expressible. Original deadline, one-shot object/session identity, lock
ordering, response-integrity and cleanup requirements remain binding.

Compatibility is appropriately bounded. The affected dialogue is Task47's new unregistered
profile; rejecting prepares without the newly required field requires no deployed-service
migration or fallback. Canonical port schemas, canonical semantic-key bytes, historical private
B and credential-op service semantics remain unchanged. The proposed extra UUID can fit within
the existing control cap; an otherwise over-limit prepare must still refuse. No bound is widened.

## Required proof and promotion boundary

The amendment's five named proof groups are adequate for this correction: distinct semantic
and transport UUIDs in authenticated Messages; authenticated bodyless and multi-page Models;
missing/malformed/mismatched and cross-dialogue/exchange identities; prepared/leased mutation
and exact digest conflict; core rejection of coherent substituted identities; and preservation
of old canonical schema/hash/protocol vectors. Before-write rejection must count zero new writes;
after-write response mismatch must withhold success and preserve uncertainty. These are required
future implementation evidence, not results established by this preflight.

Controller promotion should incorporate these exact reviewed amendment bytes explicitly while
preserving the original snapshot hashes. R1 must still implement and prove all remaining I8/I15
requirements, including sequence, original correlation, descriptor grammar, absolute deadline,
durable replay, current authority, cancellation and resource cleanup. This correction waives none
of the original independent review findings and grants no production/live/native authority.
