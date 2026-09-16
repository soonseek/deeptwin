# Deployment receipt wire v1 — public verification boundary

Normative wire preparation for the next integration after deployment-prepare-journal v1.
This document does not implement receipt ingress, lifecycle migration, signer/job, installation,
qualification or a supported deployment. Source producer/readers and the exact journal migration
must have their own complete implementation contracts before their dispatch. Existing stage
preparation/cancellation v1 bytes and history remain unchanged.

## 1. Authority and cryptographic boundary

The fixed core validates canonical receipt bytes against the actual immutable request and the
independently pinned public trust source. A cryptographic check authenticates an operator's signed
statement; it cannot prove container state, grant runtime trust, create an installation, qualify
a semantic port or replace an independent component handshake. A parsed or signature-checked
Python value is inert, including if copied or independently constructed. The later persistent
consumer must repeat actual owner, source, request, lifecycle, clock and same-writer checks.

Pure Ed25519 is the sole algorithm, not Ed25519ph or Ed25519ctx. Use PyNaCl1.6.2 VerifyKey on decoded
public key bytes and a detached signature over exact ADR008 canonical bytes of every receipt field
except signature. No new cryptographic implementation, secret-bearing provider import or signing
function in the control verifier. The installed package's VerifyKey.verify returns verified
message bytes or raises BadSignatureError; verify the expected message bytes, not truthiness.
[Official PyNaCl signing API](https://pynacl.readthedocs.io/en/latest/signing/)

Public keys are32bytes and signatures64bytes. Use RFC8032§7.1 public test vectors independently of
the application protocol. Application fixtures also verify exact canonical preimages across
Python and an independent implementation; a public synthetic key is never a deployment trust key.
[RFC8032](https://www.rfc-editor.org/rfc/rfc8032.html#section-7.1)

Dependency placement is explicit: current service-roots' provider entry and provider Linux lock
contain PyNaCl1.6.2, but the frozen control roots/lock and development venv do not. Preserve the
content-bound historical T089 input family unchanged. A future implementation adds a separately
versioned candidate complete control lock and wheel addendum/verifier plus development test input,
using verified artifacts. The eventual image builder must explicitly consume that candidate and
establish a new qualified input/image lineage; a candidate lock alone is not image inclusion.
Historical lock manifests/provenance are not rewritten or claimed current. No package installation
or active build-input change is established by this contract.

## 2. Encoding, bounds and common receipt

Every object is closed ADR008 canonical JSON: no floats/bool integers, duplicate/unknown fields,
invalid UTF8/BOM/trailing bytes or alternate canonical serialization. Reuse current domain wire/
ref helpers; never introduce a second canonicalizer or recursively convert nested digests.

UUID = canonical nonnil UUID. Id = existing extension Id grammar1..128.
HexDigest = lowercasehex64. B32/B64 = canonical unpaddedbase64url32/64bytes, including pad-bit
roundtrip. Time = calendar-valid ASCII YYYY-MM-DDTHH:MM:SS.mmmZ through year9999.
The common receipt maximum is16384UTF8bytes/depth12/items512/string1024; narrower limits below
also apply. Hash of the complete signed canonical receipt is external to that receipt. BlobRef
and filename use the hex encoding; common digest fields use B32. No future domain record ref
appears in bytes available to the operator.

The exact23fields are:
```text
{schema:"deployment-receipt-v1",domain:"deeptwin-deployment-receipt-v1",
 request_id:UUID,request_digest:B32,request_nonce:B32,kind:"extension_stage",
 instance_id:hex32,origin_profile_digest:B32,
 deployment_profile_id:"local-no-terminal-v1"|"portable-compose-v1",
 operator_adapter:"deeptwin-stage-operator-v1",operator_version:"1.0.0",
 effect_result:StageResult,
 started_at:Time,completed_at:Time,outcome:"succeeded"|"failed"|"unknown",
 failure_class:null|Failure,claimed_facts:[Fact],verified_facts:[Fact],unverified_facts:[Fact],
 key_id:UUID,trust_set_digest:B32,trust_class:"instance_operator",signature:B64}
```

This first consumer supports only the actual first-installation stage arm in prepare-journal§9.
The other canonical deployment kinds remain mandatory later; unknown/mixed/other arms are rejected,
not accepted as a generic effect_result object. Request ID/digest/nonce/kind/instance/origin match
the exact request; deployment_profile_id matches the actual OriginProfile. request_digest hashes
the request excluding only itself, while receipt digest hashes the entire signed receipt.

The operator_adapter/version above identify the planned fixed first-party adapter and its initial
implementation version, not a Docker, Portainer, OS or framework version. No existing binary is
claimed. Both deployment profiles use that adapter contract; the actual pinned trust entry binds
exactly the current profile. Its future qualified issuer must report its actual fixed adapter
identity/version from installed code, with no input override. No adapter string selects Python
code, a URL, a command or a dynamic module. A future real external issuer/observation adapter must
implement that protocol before producer qualification can be claimed. No existing Portainer/Linux
integration is implied by introducing its name.

Failure is exactly:
operator_refused|precondition_failed|image_unavailable|effect_failed|observation_unavailable|
deadline_exceeded|operator_interrupted|internal_error.
Succeeded requires null; failed requires one Failure. Unknown requires observation_unavailable,
deadline_exceeded, operator_interrupted or internal_error. Unknown observations below use that
same four-member subset; for an unknown outcome it equals the common failure_class. A failed
outcome may name effect_failed while its unknown observation names observation_unavailable.

Fact is exactly:
request_binding|image_identity|mount_configuration|service_presence|service_reachability|
network_configuration|resource_configuration|operator_preconditions.
Each list is sorted unique0..8; the three are pairwise disjoint with total≤8. Unlisted means
unspecified, not passed. "verified_facts" means verified by the signing operator, never core
qualification. No fact-list membership discharges a product postcondition or changes runtime trust.

## 3. Stage result and time equalities

StageResult is exactly the six-field canonical data-model§3.2 arm:
```text
{schema_id:"deeptwin.extension-stage-result.v1",extension_id:Id,
 expected_installation_head:{state:"absent"},expected_next_installation_revision:1,
 old_service:{presence:"absent"},new_service:Absent|Present|Unknown}
Absent={presence:"absent"}
Present={presence:"present",service_identity:Id,manifest_digest:HexDigest,
 service_descriptor_digest:HexDigest,selected_platform_entry_digest:HexDigest,
 image_manifest_digest:"sha256:"+HexDigest,reachable_after_effect:boolean,observed_at:Time}
Unknown={presence:"unknown",expected_service_identity:Id,expected_manifest_digest:HexDigest,
 expected_service_descriptor_digest:HexDigest,expected_selected_platform_entry_digest:HexDigest,
 expected_image_manifest_digest:"sha256:"+HexDigest,failure_class:UnknownFailure,observed_at:Time}
```

Every repeated field equals the actual request. The new service tuple is request new_service_effect's
service_identity, request manifest/service_descriptor digests, SHA256(canonical selected_platform_entry),
and selected_platform_entry.manifest_digest retaining its OCI prefix. Unknown values are copied
expected assertions, not observations. No operator-selected alternative tuple or future installation/
head ref is valid. Absent has no identity/time fields, including null variants.

Exact outcome matrix: old is always Absent; succeeded requires Present; failed permits Absent or
Unknown; unknown requires Unknown. Canonical stage success does not require reachable_after_effect
true; actual postconditions remain necessary. Do not import generic worker-effect terminal rules.

Pure checks require request.created_at≤started_at≤completed_at<request.expires_at and every present/
unknown observed_at between started_at and completed_at. Pure parsing verifies no current time.
Actual import additionally requires completed_at≤actual durable now<request.expires_at, with
prepare-journal's monotonic checkpoint policy and no skew grace or caller clock. Late evidence
remains unconsumed, no success/failed/unknown shortcut, and reservations remain held.

## 4. Independently pinned public trust U

U maximum16384bytes/depth8/items512/string256, exact fields:
```text
{schema:"deployment-public-trust-set-v1",domain:"deeptwin-deployment-public-trust-set-v1",
 version:1,instance_id:hex32,origin_profile_digest:B32,
 keys:[{key_id:UUID,algorithm:"ed25519",public_key:B32,
        trust_class:"instance_operator",adapter_ids:["deeptwin-stage-operator-v1"]}],
 adapters:[{operator_adapter:"deeptwin-stage-operator-v1",operator_version:"1.0.0",
            deployment_profile_id:CurrentProfileId}]}
```

Keys1..8 sorted by unique key_id, public keys also unique. Every key's adapter_ids is exactly the
displayed one-item array, and adapters is exactly one current-profile entry. There is no arbitrary
future-adapter bag despite the general bounded key list. The key ID, public key, class and fixed
adapter/version/profile must resolve together. Runtime extension trust tiers are separate from
instance_operator statement provenance.

U has no self-digest. Startup independently pins hex SHA256 of complete U bytes; the receipt's
trust_set_digest is B32 of those exact digest bytes. No key discovery, issuer URL, default key,
runtime trust rotation or automatic re-enrollment. Pinning U is deployment configuration, not a
permission available to the browser owner. Public-only tests cannot prove possession of a real
matching private signing seed.

## 5. Source and producer requirements retained for the next contract

Public trust source fixed path:
 /run/deeptwin/deployment-verify-public/trust-set.json
on distinct dt-INSTANCE-deployment-verify-public, root0:20102dir0750/file0440, controlRO.

Receipt ingress manifest J fixed path:
 /run/deeptwin/deployment-receipt-ingress/ingress.json
on distinct dt-INSTANCE-deployment-receipt-ingress-public, root0:21201dir0750/file0440, control/jobRO.
J binds actual historical prepare R/I/E, actual U, instance/profile and exact receipt writer20113/
reader20102/pair21201. Inbox is separate dt-INSTANCE-deployment-receipts at
/run/deeptwin/deployment-receipts; root/receipts namespace20113:21201mode0750, finals0440singlelink;
controlRO/jobRW. Filename is receipts/<complete-receipt-digest-hex>.json, not request digest.
Bound to64final+32stage entries. Control never writes, deletes or tombstones that inbox.

Consumed projection uses separately fixed K and dt-INSTANCE-deployment-consumed, not a new child
inside immutable v1 E. K binds historical E and current enrolled U/J, and actual retained root/
namespace continuity. Output root/consumed namespace20102:21201mode0750/finals0440, controlRW/jobRO;
16final+32stage. Exact manifest/producer/observer schemas must be frozen in the separate source
contract before implementation; the prior architectural report is design input, not a ready brief.

All sources require genuine no-follow retained FDs, bounded exact membership and byte/pin checks,
actual RO/RW mount observations, no nested/backing aliases to protected data/session/IPC/T/E/other
exchange/configured roots, and fresh pathname checks. Stat/mountinfo are local namespace observations,
not proof of Docker named-volume names or absence of host binds. No private key read for separation.

A dedicated external public-source initializer touches only its explicitly new mounted volumes,
existing roots verify-only. It never reruns Task9 IPC initialization/absence checks, rotates a
generation after operator effects, edits T/E or supplies fake signer readiness. Private seed/root
genesis and the real external signer/job remain separate required deliverables. Any finite receipt
expansion is separately versioned and preserves the historical base and prepare artifacts.

## 6. Persistent consumer requirements, not implemented by a verifier

Later owner-only import accepts digest selectors, never browser-uploaded receipt bytes/key/path.
Actual source reads and signature/request checks precede presealing. The final shared DomainStore
writer revalidates actual session/CSRF, command replay, journal/request/head/time and retained U/J/K
bindings before immutable receipt attachment and lifecycle/command/event/outbox commit.

Do not reacquire the old slot-absence lease: an operator effect may legitimately populate it.
Historical request/T/E bindings remain mandatory; losing physical T/E does not invalidate independent
intact receipt sources or authorize changing them. A signature-checked value cannot replace those
actual checks, and verification alone creates no authoritative domain entity.

Succeeded attaches immutable signed evidence as receipt_pending, with no consumption, installation,
qualification, binding or execution. Failed/unknown atomically create rejected lifecycle, exact
one-use consumption/domain index/event/command and consumed outbox intent. All outcome branches retain
the reservation. Unknown does not become a safe absent slot. A different signed receipt cannot
overwrite an admitted first receipt. GET and exact command replay do not reimport or reinterpret
evidence under a new key.

Future verified private migration preserves all v1 rows/hashes/anchors/receipts and extends only the
specified lifecycle/checks. prepared1 may become cancelled2/expired2/receipt_pending2/rejected2;
receipt_pending2 may become cancelled3/expired3 in the non-success-consumer slice. No accepted state
until real postconditions exist. Cancellation-v2 permits the new revision3 marker; existing v1
revision2 marker bytes remain identical. Cancel that wins first rejects later import/consumption.
Exact DDL/event/API/replay/time/error matrices remain required before that task's dispatch.

The later read/cancel response extension must have a separately named prepare-api-v2 structural
artifact and explicit schema export. Preserve the accepted prepare-api-v1 and cancellation-v1
artifact bytes plus all historical command replies; unchanged HTTP route paths do not imply an
old closed read schema validates new additive fields/states. A cancellation-v2 artifact handles
revision3 while existing revision2 markers remain v1. This is a pre-release API evolution with
honest versioned schema identity, not a claim of backward-compatible closed response validation.

Physical consumed files are post-commit no-clobber/fsynced projections of actual one-use consumption,
not DB authority. Same-writer rechecks/ackCAS and bounded recovery preserve pending crash semantics;
there is no DB/filesystem atomicity. Do not erase the canonical physical tombstone requirement
because v1 E lacks a consumed namespace.

## 7. Verification and limitations

Minimum pure tests: every common field altered after signing, wrong key/signature length/pad bits,
noncanonical JSON, mixed/unknown schema/algorithm/adapter/class/profile, cross-request nonce/digest,
outcome/observation/time/ref equality and all forbidden/null fields. Valid signature with wrong
trust/profile/tuple must fail. Valid pure parsing with a synthetic key is still inert.

Minimum later source/consumer tests: real temporary files/FDs and SQLite, wrong/replaced/aliased/RW
sources, exact selector basenames and namespace bounds, source loss preserves local reads/cancel,
same-command replay, cancellation/import/expiry races, one-use under two connections, faults after
each authority write, unchanged v1 bytes through migration and restart, no installation on
non-success or pending success, and deterministic consumed-file crash recovery.

This is a staged implementation sequence, not removal of release/update/recovery/replace/uninstall/
retirement, final UI, producer packaging or Linux/two-host requirements. No live key, signing job,
mount, process, provider call or deployment is run to define this wire.

## 8. Pure codec implementation interface

New app/deployment/receipt_contracts.py owns receipt/trust parsing and relational checks;
receipt_crypto.py owns only detached public-key verification; receipt_schema_exports.py owns
closed structural exports. No imports of provider credentials, signing service, domain storage,
owner authority, source readers, HTTP adapter or receipt lifecycle. Reuse existing canonical_json,
parse_json_object/WireLimits, uuid_string, OriginProfile and parse_base64url_32. Receipt-only64byte
signature decoding additionally enforces86characters ending in[AQgw] and exact decode/reencode;
never broaden the existing32byte helper or install a second canonical JSON implementation.

ReceiptWireError is defined in receipt_contracts.py; receipt_crypto imports that exception.
receipt_contracts imports verify_detached locally only inside verify_receipt, avoiding a module
cycle and leaving structure-only parsing usable without loading PyNaCl. Initializer/ingress use
that parser, not the crypto verifier. A fresh-process import test verifies the boundary; no fake
cryptographic success replaces actual verification tests. No external initializer is qualified here.

Exact interfaces (every returned dict/bytes is inert):

```python
parse_receipt(raw: bytes) -> dict
parse_trust_set(raw: bytes, *, profile: OriginProfile) -> dict
verify_receipt(raw: bytes, *, request_bytes: bytes, trust_bytes: bytes,
               trust_sha256: str, profile: OriginProfile) -> dict
verify_detached(public_key: bytes, message: bytes, signature: bytes) -> bytes
```

parse_receipt performs every intrinsic field/shape/bound/canonicality/outcome/fact-list/time check
possible without a request/U: started_at≤completed_at and any observed_at within those endpoints,
old service absent, initial revision1, the exact result arm and outcome/failure matrix. It does not
check a declared signature or resolve trust/key/nonce/deadline. Later ingress callers compare its
instance/origin/profile/declared trust digest to their actual pinned J; the parser grants no lease.

parse_trust_set additionally requires the exact OriginProfile type and internally consistent profile
fields, matches instance/origin/current deployment profile and checks all key/adapter uniqueness/
sort rules. It never establishes that these bytes came from the independently pinned live U.

verify_receipt reparses all raw inputs rather than accepting preconstructed parsed objects. It
parses the request through the accepted prepare_contracts.parse_request(request_bytes,profile=...),
checks actual trust_bytes SHA256 against the explicit lowerhex64 trust_sha256, and checks every
cross-document equality/time condition in sections2–4. The fixed verification order is intrinsic
receipt/request/trust parsing, trust pin/key/adapter resolution, actual detached signature check,
request binding, then request-relative time checks. A forged mismatching statement must fail
signature verification before it can be classified as a request conflict. trust_sha256 is a pure expected binding;
the actual future source consumer obtains it from deployment configuration and retained U, not
from the receipt. The canonical preimage includes all22 unsigned fields, excludes only signature,
and remains bytes. Resolve the exact key/adapter tuple then call verify_detached; require returned
message bytes to equal that preimage. Return a fresh parsed receipt, no authority-bearing wrapper.
No current time, filesystem, database, network, browser session or callback participates here.

One private `_check_request_binding(receipt,request,*,profile)->None` owns all request relations:
request ID/digest/nonce/kind, instance/origin/deployment profile, extension/first-installation arm
and repeated service/manifest/descriptor/platform/image tuple. It raises private
`_ReceiptRequestMismatch(ReceiptWireError)` with the SAME fixed public code/message
`receipt_invalid`; verify_receipt lets that subtype propagate only after successful signature
verification. No public third error code, authority wrapper, duplicated importer relation checker
or error-text classification is introduced. Intrinsic fixed-arm rejection remains ordinary
receipt_invalid before this helper. Intrinsic outcome/fact/time rules, request-relative
created/start/completed/expires relations and trust/key/adapter/pin failures are also ordinary
receipt_invalid; actual import-clock expiry remains the later service's matching-head409 branch.
The later importer maps only this private mismatch subtype to409 and other wire failures to400.
Actual source admission may fail first with503; this classification cannot override a failed J
instance/profile/U binding. Pure callers still observe only the two public codes below.

ReceiptWireError(ValueError) has exactly two fixed codes/messages, with no reflected values:
`receipt_invalid` for structural/relational/pin failures and `receipt_signature_invalid` for actual
BadSignatureError. Invalid raw key/signature type/length is receipt_invalid before PyNaCl. Do not
catch arbitrary programming failures and return success; missing PyNaCl is a dependency failure,
not evidence that a valid signature was checked. Neither code is a new HTTP error by itself.

Bounds use the existing WireLimits counting convention (root depth1, members/list elements count
toward max_items, UTF8 string lengths) and the declared12/512/1024 receipt or8/512/256 trust values.
max_members is at most32 for both and all nested objects are schema-closed. Intrinsic canonicality
is checked by canonical_json(parsed)==raw. Every integer field here is strict integer and bounded
by its explicit schema; bool remains valid only at reachable_after_effect. Calendar validation is
not a regex-only claim. Schema validation uses Draft202012 with FormatChecker for timestamps.

The two exports are schemas/v1/deployment/receipt-stage-v1.schema.json and
public-trust-set-v1.schema.json, IDs urn:deeptwin:schemas:v1:deployment:receipt-stage-v1 and
urn:deeptwin:schemas:v1:deployment:public-trust-set-v1. `exported_schemas()->dict` returns those
filename/schema mappings; `write_schemas(destination)->None` writes sorted indentedUTF8 plus one
terminal newline, exactly like existing structural exporters. Reuse their object/text/UUID/B32/
timestamp helpers without changing their bytes. Export comments explicitly distinguish structural
validation from request/trust/signature/currentness authority; schemas cannot promise relational
or cryptographic validation. Preserve all existing v1 artifacts and44port contracts unchanged.

Crypto conformance tests use the five public-only RFC8032§7.1 vectors plus a separately labeled
negative corpus; never store the RFC private seeds. Complete synthetic application fixtures may
be generated once with an independent Node crypto Ed25519 implementation in an isolated test
process, then retain only public key, raw request/U/receipt and exact unsigned preimage. Never
write its temporary private key to a fixture/report, treat it as a deployment key, or add signing
code to application modules. The fixture generator is developer-test-only, takes no external key,
uses no network and exports no key material except the synthetic public key. The two independent
implementations must verify the same stored preimage/signature. Tamper tests require no new signing.
Cross-request/profile/tuple/time invalid-but-validly-signed cases belong in the same public fixture
set; labels state why each is invalid. Valid signatures alone do not prove relational checks ran.

## 9. Developer-only fixture session for actual request integration

The Node fixture helper also has an explicit `--session` mode for later tests that first open
real temporary U/J/K sources and then prepare real requests. Static signed examples alone cannot
bind a fresh host-generated request ID/nonce/time. This mode is test infrastructure, never an
application signing API, production issuer, external operator or proof of effects.

Use newline-delimited JSON over owned subprocess stdin/stdout. Each frame is at most131072UTF8
bytes excluding the newline; decoded request bytes at most65536; at most64case commands follow
exactly one init command. Reject overflow before unbounded buffering. EOF ends the process and
releases its only key reference. Tests own and close this exact child with finite deadlines;
never inspect or terminate another process. The fixed protocol is:

```text
in  {op:"init",profile:OriginProfile.as_dict()}
out {trust_b64:UnpaddedBase64urlOfCanonicalPublicU}
in  {op:"case",request_b64:UnpaddedBase64urlOfExactRequestBytes,case:FixedFixtureCaseName}
out {receipt_b64:UnpaddedBase64urlOfCanonicalReceipt,
     unsigned_preimage_b64:UnpaddedBase64urlOfCanonicalUnsignedReceipt}
```

Init generates one ephemeral Ed25519 keypair and one synthetic key ID in process memory and
returns public U only. Every case in that process uses that same key and U; no key rotation or
second init is accepted. The finite case-name enum includes all valid outcome arms and the same
explicitly named invalid cases used by static fixtures. Factor that fixture builder once within
the helper. Case inputs cannot override a key, path, URL, arbitrary message, timestamp, trust
document or arbitrary receipt fields. Derive valid started/completed/observed times from the
request's own created_at; actual imports still enforce their real durable clock and deadline.
Negative fixture names perform predefined mutations, never arbitrary caller-supplied patches.
Unknown fields/op/case, malformed/bounds violations and bad ordering terminate with nonzero exit
and fixed stderr `receipt_fixture_invalid`; no input/private-key reflection or partial success.

The existing no-argument static public fixture generation and public-only `--verify` mode remain
separate. No mode accepts an external key, reads an external path, contacts a network or writes a
private key. Public U/receipt/preimage bytes may be retained in fixtures. Node's fixture-only
canonicalizer and private-key memory are never imported by application code. Session tests prove
one U binds two real-shaped distinct requests, proper ordering/caps/cleanup and actual Python
verification of its outputs; later actual service/source tests establish their own admission.
