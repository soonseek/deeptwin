# Task47 gateway semantic request identity — proposed bounded correction

Status: DRAFT for independent interface preflight; not implementation authority until
controller promotion. This changes no user workflow, native authority, provider scope,
published canonical port schema/hash, or historical private protocol.

## Demonstrated conflict

Accepted literal appendix§7 requires every ArtifactDescriptor.request_id to equal the
canonical semantic request_id. Worker begin carries the full request, but the closed
provider-send-prepare-v1 table carries only operation_ref/request_sha256 and no
request_id. Operation UUID5 and SHA256 are non-invertible. The gateway has no DomainStore.
Messages could only guess from its untrusted incoming descriptor; bodyless Models has
no request descriptor at all from which to construct its response descriptor. Broker
message_id or dialogue_id substitutions violate the chosen semantic identity rule.

## Exact proposed replacement, limited to the new unregistered profile

In appendix§7's provider-send-prepare-v1 row, add one required field `request_id:U`
immediately after operation_ref. U retains the existing canonical nonnil UUID grammar.
All other required fields and closed-shape/control-byte constraints are unchanged:

`{schema,dialogue_id,seq,operation_ref,request_id,request_sha256,selected_handle_ref,
connection_sha256,connection_pin,credential_metadata,credential_record,endpoint,
after_id,body_descriptor,remaining_ms,deadline_at,reservation_ref}`.

Core derives request_id from the exact admitted canonical request, never from a worker
descriptor, exchange ID, record ID or caller override. Core verifies it with the
admitted operation/request_sha256 join before prepare. The gateway treats this as an
authenticated core projection; it cannot independently rehydrate that operation and
must not claim that it can. Gateway pins the canonical request UUID alongside exact
operation_ref/request_sha256/connection pins for the lifetime of this exchange.

prepare_sha256 continues to hash the exact complete Canon(prepare) bytes, now including
request_id. Add required immutable `request_id:U` to appendix§9's process-local
GatewayExchangeLease and to its registry's frozen value tuple. The lease's value comes
only from that validated prepare. Existing one-shot instance/session/object identity,
deadline, cancellation, lock ordering and cleanup rules remain unchanged.

For Messages, require body_descriptor.request_id == prepare.request_id before accepting
body bytes or issuing READY. For both Messages and bodyless Models, gateway response
descriptors use that pinned request_id. Core independently requires received response
descriptors to match its original admitted request_id, not merely the echoed prepare.
Every page of one catalog operation retains that semantic request UUID; fresh exchange,
dialogue, broker and batch identities remain separate and obey existing grammar.

Commit/cancel/result message field sets stay unchanged: their exchange_id and existing
dialogue/sequence/prepare digest joins resolve the already pinned identity. Descriptor
request_id rules on worker input/frozen/proposal/final streams remain unchanged.
Changing prepare identity without changing body descriptor refuses; coherently changing
both cannot alter the core's admitted operation/request join. A changed response
descriptor refuses acceptance and never publishes successful semantic output.

## Compatibility and ownership

This is a correction to Task47's unregistered new semantic dialogue, not a migration or
new version of an already activated service. Reject a new-profile prepare omitting the
field; no automatic legacy fallback. Old private B, credential service operations,
canonical port config/request/result schemas and idempotency hashes remain byte-identical.
Existing historical Task47 snapshots stay unchanged; a promoted master addendum will
explicitly incorporate this correction and its independent review.

Implementation stays within Task47's existing26owned files (send message/service/client,
runtime caller and their owned tests). No new product file, DB field, production factory,
authority producer, network endpoint, secret or native operation is introduced.

## Required focused proof

1. Real authenticated Messages prepare/body/response descriptors all use semantic UUID,
   intentionally different from operation/dialogue/broker/batch UUIDs.
2. Real authenticated bodyless Models GET constructs and validates a response descriptor
   with that same admitted semantic UUID, including a multi-page traversal.
3. Missing/malformed UUID, mismatched body descriptor, swapped dialogue/exchange and
   altered prepared/leased UUID fail closed with zero new write where detected before
   write; response mismatch after write withholds success and retains uncertainty.
4. Core rejects coherent worker/descriptor identity substitution against its exact
   admitted request. Full prepare digest changes on request_id change; commit of an old
   digest cannot adopt that changed prepared tuple.
5. Existing canonical port schema/hash and historical protocol tests stay unchanged.

These are additions to I8/I15's existing proofs, not substitutes for sequence, deadline,
replay, authority, cancellation or artifact integrity requirements.

## Controller recommendation

Adopt the explicit request_id field rather than weaken descriptors to broker/dialogue
IDs or give the gateway DomainStore authority. Cost is one additional UUID in prepare
and lease plus exact validation/tests; if wrong, the bounded unregistered contract and
fixtures need revision. No external or user-facing side effect occurs from this choice.
