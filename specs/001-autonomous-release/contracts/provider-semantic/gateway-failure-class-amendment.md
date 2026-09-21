# Gateway failure classification correction — proposed bounded amendment

2026-09-20. DRAFT for independent interface preflight; not implementation authority
until explicitly adopted by contracts/provider-semantic-execution.md. This concerns
only Task47's new, not activated claude-api-text-semantic-v1 provider-send dialogue
and its new response record. Original normative snapshots remain byte-identical.

## 1. Demonstrated conflict and exact delta

The literal appendix §10 requires distinct deadline, permission, capacity,
unsupported, integrity and dependency outcomes. Its §7 closed send-result fields
carry only status, HTTP status, response descriptor, phase and cancellation. Those
fields cannot identify an actual local gateway failure without guessing from an
exception string, overloading an existing field, or discarding the distinction.

Add exactly one REQUIRED nullable field, `failure_class`, to the existing closed
`provider-send-result-v1`. Its value is null or exactly one of:

`permission_denied`, `deadline_exceeded`, `resource_exhausted`,
`unsupported_capability`, `integrity_failed`, `dependency_unavailable`,
`cancelled`, `internal_failure`.

Add the same REQUIRED nullable field and exact value set to the new durable
`provider-semantic-response-v1` content (appendix §2). Core copies a received,
validated gateway classification exactly; an absent/untrusted gateway result
cannot supply a claimed gateway cause. Core-local failures are represented by the
existing terminal error, not fabricated gateway evidence. Rehydration validates
the closed enum and consistency below. No other existing record variant, EntityRef
kind, table, migration, worker-observation field or provider-port schema/hash changes.
No optional downgrade or old-peer field omission is accepted for this new profile.

All other send-result fields retain their exact names and meanings, especially
`response_descriptor` (not body_descriptor). The existing 16384-byte application
bound, authenticated session/correlation/sequence, descriptor identity, integrity,
single exchange consumption and original deadline remain binding.

## 2. Meaning and coherence

This field reports a sanitized gateway-local observed failure category. It is not
an upstream diagnostic, remote outcome proof, authority grant or retry permission.
Classify from deliberate typed/stage-local branches, never by matching raw exception
messages. Unclassified local exceptions map to internal_failure, not a guessed
permission/dependency/deadline reason. Never transmit exception text, key material,
credential paths, response snippets or arbitrary error objects in this field.

For a normally completed upstream HTTP exchange, failure_class is null, including
non-2xx responses. The existing HTTP status and exact private bytes are the
evidence; provider rejection is not misreported as a local custody failure.
Wire status complete requires failure_class=null. A non-null local failure cannot
be marked wire complete. `cancel_observed=true` is an observed control latch, not
proof that cancellation caused the failure: it may coexist with another category
or a completed response. failure_class=cancelled requires cancel_observed=true.

Phase derives from actual effect/response evidence independently of the category.
not_sent cannot have an upstream HTTP status or upstream response descriptor/raw
blob. A valid observed HTTP response may retain its status and bounded bytes even
if a later deadline, capacity, media or stream failure prevents semantic success;
classification must not erase that evidence or turn it into success. Wire status
refused is known pre-send refusal and requires phase=not_sent; truncated/unknown
retain their existing incomplete/uncertain meanings. Unknown transport outcome
without an observed classified local cause may retain failure_class=null.

Existing response phase terminal_observed is not by itself valid semantic success:
HTTP status, complete raw bytes, independent normalization and terminal joins still
govern success. No failure marker can make a possibly sent model request retryable.

## 3. Canonical error precedence and evidence

Core uses appendix §10's existing code/message_class/retry_class mappings for these
eight categories only after checking authenticated identity, exact field grammar,
coherence and applicable actual effect evidence. In particular:

- A model request that may have caused an external effect without a proven valid
  success remains external_effect_unknown/external_outcome/never for non-cancellation
  outcomes regardless of local deadline, dependency or capacity category. Preserve
  the existing appendix §8/§10 observed-cancellation branch: cancelled status/error,
  unknown effect, null effect-ref and unconfirmed remote outcome after possible
  write. An acknowledgement never proves remote rollback. A fully verified valid
  success still follows the original success/acceptance race rules.
- Known pre-send classified failures use the corresponding §10 mapping. A known
  unsent unclassified failure is internal_failure, not external_effect_unknown.
- Read-only Models traversal retains its §10 catalog_incomplete behavior for parse/
  traversal incompleteness and the specific §10 mapping for observed local errors;
  it does not invent a model-spend effect. No failed traversal publishes a partial
  active catalog or retries the same request UUID.
- Untrusted/malformed send results never become an authorized cause. Core seals
  its own integrity/uncertainty failure using actual trusted effect observations;
  missing gateway result is not evidence that no send occurred.

Retain only actual bounded upstream bytes via the existing authenticated response
stream and private raw blob. Do not synthesize a body from an exception. Never
extend the original deadline to manufacture an error response or drain extra bytes.
Failure before a valid prepare/READY/exchange identity, or loss of the authenticated
result channel, may prevent any wire result: close safely; core handles its own
observed failure, retaining conservative effect accounting and immutable terminal
behavior. Do not fabricate exchange IDs, gateway causes or successful cleanup.

## 4. Required bounded proofs and scope

Use existing26 owned paths and controlled encrypted/authenticated local fixtures.
No new permission, production issuer, live key/request, retry or dependency.

1. Actual authenticated gateway/client local failure reaches core and durable
   rehydration with the same permitted category; concrete deadline, custody denial,
   capacity/media and dependency branches are distinguished, not string-classified.
2. Missing/extra/unknown/non-string category and inconsistent complete/refused/
   cancellation/not_sent combinations are rejected at actual receivers; preserve
   control-size, correlation and exact response_descriptor checks.
3. Complete HTTP success and non-2xx responses carry null; partial real response
   bytes/status survive a classified failure when validly deliverable within bounds.
   No synthesized exception body or secret appears in wire, logs or exported data.
4. Known unsent errors, actual post-write model failure, read-only catalog failure
   and missing/untrusted result select distinct conservative canonical outcomes;
   same-UUID history stays immutable and no automatic resend occurs.
5. Existing positive model/catalog flow, cancellation during result streams, original
   deadline, credential-currentness and private-record/effect/usage joins remain
   covered. Passing this design preflight is not implementation acceptance.
