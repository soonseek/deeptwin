# Encrypted credential custody — initial production-backend correction

2026-09-19. Implementation contract for a partial T025/T090 correction, subordinate to
ADR-008/ADR-012, operations §3 and the credential lifecycle in api.md. This does not qualify
a deployment, enable a provider, or replace the later canonical connection/send authority.

## Outcome and boundary

Replace the existing raw-file `CredentialVault` entry point with encrypted fresh-layout
storage, exact metadata-based reconciliation and persistent retirement denial. Exercise the
real authenticated credential channel with synthetic temporary records. An unused encrypted
codec beside an operational plaintext backend is not completion. No plaintext fallback.

Ordinary serving startup never creates a root, initializes an unknown directory, migrates
Keychain/raw files or deletes orphans. Existing raw `index.json`/`secrets` layouts and unknown
layouts fail with `maintenance_required` before any mutation; all existing bytes remain.
This task implements deployment-only initial genesis, not real deployment or root maintenance.
Tests own their temporary directories only. No real credential discovery/enrollment/send.

## Initial layout and ownership

Two separate deployment-supplied directories, neither browser-configurable:

```text
root-volume/manifest.json                  # 0400
root-volume/root.key                       # 0400, exactly 32 bytes
root-volume/init.lock                      # 0600, empty fixed inode, initializer only
records-volume/layout.json                 # 0600
records-volume/lifecycle.lock              # 0600, empty fixed inode
records-volume/mutation.lock               # 0600, empty fixed inode
records-volume/journal.sqlite              # 0600, bounded nonsecret journal
records-volume/generations/<generation_id>/records/<record_id>/<version>.json
records-volume/staging/                    # encrypted bytes only
```

Directories 0700, writable files/SQLite sidecars 0600, exact deployment-configured owner/group,
no symlinks or hardlinked regular files, component-wise no-follow opens and bounded reads.
Reject wrong ownership/modes rather than repair them. No caller paths as record identity.
Reject identical, aliased or ancestor/descendant root and records directory targets before
genesis mutation; revalidate directory identities under exclusion. Their key/data separation
cannot be satisfied by two names for the same inode or by placing one inside the other.
The future service profile uses provider UID/GID 20103; local tests explicitly use the test
process owner and do not claim native UID/read-only-mount qualification. Do not change static
service images/topology or qualification locks in this slice.

Root manifest exact fields: schema_version=`credential-root-v1`, key_id, vault_id, storage_id,
generation_id, created_at, integrity_tag. IDs are distinct canonical nonnil UUIDs (vault_id is
the exact configured vault ID); timestamps are real UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`.
Integrity tag is canonical unpadded base64url HMAC-SHA256 under the root over ADR-008 canonical
`{domain:"deeptwin-credential-root-v1",manifest:<all fields except integrity_tag>}`. key_id is
random, never a key hash. Layout exact fields: schema_version=`credential-layout-v1`, vault_id,
storage_id, generation_id, key_id, root_manifest_sha256. Root binds storage_id: a serving
instance cannot silently attach the same root to an independently initialized nonce journal.

Deployment-only `initialize_credential_root(root_directory, records_directory, *, vault_id,
expected_uid, expected_gid)` exclusively initializes absent/empty approved targets, writes
full bytes with O_EXCL, fsyncs files and directories and returns only nonsecret metadata.
It accepts an already complete valid pair as verify-only/no-op. Partial initialization or
mismatched pairs fail without replacing either root or records. Acquire checked fixed root
`init.lock` EX first, then checked records `lifecycle.lock` EX, each with the same finite busy
bound. Root exclusion is required even when competing initializers name different records
directories. A complete root's binding must be checked before initializing any other records
directory. A directory containing only its validated empty initializer lock is still an
uninitialized target; any partial key/manifest/layout/journal is not. Losing processes never
remove lock files. There is no cross-volume atomicity claim: partial genesis requires explicit
operator recovery. Serving verifies but does not mutate or acquire the root init lock.

Serving opens both preexisting directories and verifies the pair. Hold a shared lifecycle
flock for the actual vault lifetime; close/context exit releases it. Future maintenance needs
exclusive lifecycle ownership. Every mutable operation and coherent read uses an independently
opened mutation-lock FD, bounded nonblocking acquisition (5-second maximum), thread-safe and
cross-process. A timeout is a typed busy error, not retry-to-success. Never unlink lock inodes.
Do not hold a user/API session lock while waiting for this gateway lock.

## Root and envelope implementation

The gateway-private root handle exposes only record sealing/authenticated opening and close;
no key getter, general-purpose MAC, printable secret or environment-variable key. Control
imports wire/client contracts only, never root/vault implementations. Use existing pinned
PyNaCl 1.6.2 `nacl.secret.Aead`, not a new algorithm/library or an SDK-generated key store.

Immutable record envelope exact keys: `header`, `nonce_b64u`, `ciphertext_b64u`. Header exact
keys: schema=`credential-record-v1`, algorithm_id=`xchacha20poly1305-ietf`, key_id, vault_id,
record_id, record_version, provider, auth_mode, created_at. Header bytes are ADR-008 canonical
AAD. record_id is canonical nonnil UUID; version is integer, not bool, 1..2^63-1. provider/mode
pairs are exactly claude/api and codex/api for this input policy, never Claude subscription.
Use the root manifest's key/vault IDs; preserve accepted metadata exactly.

Fresh nonce is exactly 24 random bytes. Store separately only `encrypted.ciphertext` (tag
included), not the combined nonce+ciphertext return. JSON is canonical UTF-8; nonce and
ciphertext use canonical unpadded base64url. Envelope <=96 KiB; ciphertext/tag 16..65,552 bytes.
Reject duplicate/unknown keys, noncanonical bytes, unknown algorithms/versions, bad scalar/
integer/timestamp/base64 encodings, truncation, swapped identity/header/ciphertext and tag
failure. Return no plaintext before complete authentication and bound identity validation.
ADR-008's 64-KiB string bound applies to the header/AAD, not to the base64 ciphertext field:
the latter can be 87,403 ASCII characters at the permitted maximum. Use a separately bounded
exact-envelope codec with sorted compact UTF-8 spelling and the 96-KiB whole-envelope ceiling;
do not inadvertently lower the secret ceiling by passing the envelope through the domain
record string limiter. Test an actual 65,536-byte accepted secret and its complete round trip.

API-key input policy retains 1..65,536 UTF-8 bytes, no C0/DEL characters; no raw value in repr,
exceptions, journal, receipt, logs or errors. Persist no plaintext-derived hash, equality
fingerprint, prefix or suffix. Ciphertext hashes and nonsecret metadata fingerprints are allowed.
Python memory release is best-effort, not secure-erasure proof.

## Bounded credential-channel fragmentation

The existing broker frame remains at 65,536 bytes, including its outer base64/JSON/MAC.
Do not widen broker limits, ChannelSpec, handshake identity or another service's allowance.
A maximum key cannot fit in one such frame. Add a credential-local logical-message codec
inside the existing channel module, reused by its gateway service, not a second ingress API.

A canonical encoded credential operation/result is at most 102,400 bytes. Send it as one
ordinary credential_op/credential_result frame only when at most 16,384 bytes. Larger values
use 2..7 authenticated frames with this exact canonical object as each frame payload:

```json
{"schema":"credential-fragment-v1","transfer_id":"<canonical nonnil UUID>","total_bytes":88200,"index":0,"count":6,"chunk_b64u":"<canonical unpadded base64url bytes>"}
```

Fields are exact; integers are not bool. total_bytes is 16,385..102,400; count equals
ceil(total_bytes/16,384), index is contiguous 0..count-1. Every decoded chunk is exactly16,384
bytes except the last, whose length is the exact remaining positive length. Each fragment
is itself strictly bounded/canonical; reject unknown/duplicate keys, invalid encodings,
oversize strings and inconsistent identity/count/length before vault dispatch.

The first frame's message_id equals transfer_id. Later message_ids are fresh and distinct
within the transfer. All fragments have the same expected credential message type and use
the same actual codec/socket/authenticated session. A request's first correlation_id is null,
and later fragments correlate to transfer_id. Every response fragment correlates to the
original logical request's first message_id. Its own transfer_id is the first response's
message_id. Ordinary one-frame messages retain their existing correlation rules.

One connection serves one logical operation/result, not multiplexed transfers. Bind the
first frame then read only its exact bounded continuation. Reject reordered, duplicate,
interleaved/wrong-transfer, wrong-type, wrong-correlation, count/size mismatch, early close
and timeout before invoking the vault. MAC/counter/peer checks remain the real broker's.
One original absolute Deadline covers all fragments; never reset it per frame. No full-message
digest, plaintext-derived fingerprint, chunk journal, disk staging or request logging.
Existing broker frame digests/MAC are transient authenticated transport metadata, not retained
credential evidence. Do not route keys through the artifact/CAS digest stream.

Reassemble bounded bytes in transient memory, then strict-decode one complete operation and
invoke the vault exactly once. Return a private logical-message tuple/value, not a forged
BrokerFrame whose envelope claims sizes/digests for different bytes. A partial received
operation has not been admitted by the vault; query unknown remains nonterminal because a
separately delayed accepted call can still commit. This changes transport, not secret-ingress
intent/nonce semantics. No automatic retries or fresh logical command IDs.

Use the same logical codec for bounded results, preserving their original request correlation
and secret-free projection. An over-limit snapshot/result is a typed refusal, not truncation;
this slice does not introduce snapshot pagination. Old v1 operation writes/delete remain
unsupported after decoding. A one-frame payload above16,384 bytes is refused rather than
bypassing the logical codec's fixed threshold. No new message type or production test bypass.

Tests traverse a real authenticated socket pair with an actual65,536-byte secret through
the v2 client, gateway and encrypted store/query. Verify byte-identical authenticated private
open, no persisted plaintext/hash, original receipt/no second ingestion on replay. Cover
threshold below/at/above16,384, maximum logical bytes and overflow, malformed/wrong/replayed
fragment metadata and frame correlations, incomplete/slow transfer and response fragmentation.
Assert no vault mutation before complete admission and no deadline extension. Helpers/processes
remain bounded/owned. Broker-wide tests stay unchanged; run their focused family as regression
if the existing channel fixture exposes an assumption. No broker.py edits are authorized.

## Exact command and record lifecycle

Introduce versioned `credential-op-v2` wire messages on the existing authenticated pair, with
closed per-operation keys and bounded strict decoding. Existing v1 `store/delete` cannot
retain plaintext storage/immediate erasure semantics: refuse as unsupported with a sanitized
typed result. Do not expose a generic raw HTTP or root/decrypt operation.

`store_at` carries command_id, record_id, record_version, provider, auth_mode, created_at,
nullable predecessor (exact record_id/version/ciphertext_sha256), and canonical base64url
secret ingress. Nonsecret intent identity is the canonical digest of these metadata fields
(plus operation/schema), excluding secret bytes entirely. Caller preallocation is not binding
authority. One command/target ingests at most once. A repeated already-known command returns
the existing exact metadata-bound receipt or conflict, without decrypting/comparing/validating
another secret as replay evidence; pending/lost commands never ingest newly supplied bytes.
The caller must use `query_record` after ambiguous submission, not resend different secrets.

`query_record` carries command_id and the same exact nonsecret target/fingerprint. It returns
the matching stored receipt, pending, secret_input_lost or conflict; it never decrypts for a
query. Synchronize with the mutation lock: an in-flight store is busy/pending, not conclusive
absence. An unseen command is `unknown`, explicitly nonterminal even after lock acquisition:
a received/queued store may not have acquired that lock yet and can still commit afterwards.
Retain the original command; unknown never authorizes a new ID, replacement secret or terminal
loss. Only a durably journaled pending command whose completed/recovered operation demonstrably
lost its ingress can become secret_input_lost. A future cancel/fence protocol is a separate
operation, not inferred from this query. No claim of safe retry follows merely from HTTP
timeout, mutation-lock exclusion or a query against a different deployment.

Stored receipts include record identity, provider/mode, ciphertext digest, original command,
and state=`stored_unbound`. They are private gateway/control metadata, not browser projections.
Keep the immutable original receipt separate from effective lifecycle state: a query after
retirement reports cleanup_pending and cannot present the old receipt as currently bindable.
This slice does not produce configured/active provider binding. A rotation predecessor remains
unchanged until a separate canonical binding CAS and retirement flow; storing a candidate key
alone cannot revoke the currently bound one or activate the candidate.

`retire` carries its own command_id, exact record reference and one reason from
`owner_delete`, `superseded`, `unbound_orphan`. Under the journal lock append an immutable,
idempotent retirement intent and change effective state to cleanup_pending. Changed replay
conflicts; an existing retirement cannot be reversed by reopen, old receipt or another store.
No ciphertext is unlinked. Root rotation/erasure capabilities explicitly remain unavailable;
`erase` cannot claim erasure_completed. Future maintenance owns removal of all managed copies.

Provider resolution remains unavailable for stored/unbound or retired entries. Do not add
`activate=True`, caller-authenticated booleans, in-process callbacks or a test bypass flag to
manufacture a current provider binding. The later canonical send resolver supplies genuine
binding/request authority. Private cryptographic self-checks may open a stored record inside
the gateway without authorizing a provider send. Preserve transport's header/origin/response
tests using clearly test-only synthetic custody seams, not production activation exceptions.

## Recoverable publication and bounded journal

Use one gateway-owned SQLite journal under checked path/sidecar discipline (foreign keys,
explicit transaction and finite busy bounds). Tables track exact nonsecret intents/targets,
consumed nonces, record receipts and irreversible retirement intents. Maximum 4096 commands,
2048 records and 8192 reserved nonces for this initial layout; capacity fails before accepting
or decoding secret bytes into the vault mutation and before encryption, never prunes nonce/
retirement history. The bounded authenticated IPC frame may already hold encoded secret in
transient memory; this is not a new two-phase receive protocol. Journal metadata binds layout/root.
These are initial service bounds, not a claim of unlimited lifetime or completed maintenance.

Under mutation exclusion validate metadata/replay first, reserve `(key_id,nonce)` uniquely and
persist the pending command before encryption. Try random nonce generation at most 8 times;
collision exhaustion fails closed. Reserved nonces stay burned on every failure/crash.
Encrypt bounded memory, write exclusive encrypted staging, fsync, publish immutable destination
without overwrite, fsync its directories, then seal the matching journal receipt. Publication
uses O_EXCL destination creation, bounded full ciphertext write and file/directory fsync; retain
the staging file. No hardlink intermediate, staging unlink, overwrite or platform-specific
rename API is required. This is not atomic file publication: until full identity/AEAD verification
and the journal receipt, destination bytes are not a stored record. A partial destination fails
closed as corruption/maintenance-required and is retained without repair or overwrite on reopen.
No plaintext or plaintext hash reaches SQLite/WAL/staging. Keep locks through actual completion.

On reopen under exclusion, preflight the complete bounded journal and managed ciphertext tree
without publication or journal state changes. Authenticate identities/copies, validate nonce
history, receipts, retirements and all ambiguities before applying any recovery action. A
global failure must leave command states, receipts and managed ciphertext inventory unchanged.
Only after that preflight succeeds: a valid exact published pending record completes its original
receipt. If the destination is absent but one complete staging envelope exactly binds the
pending intent, its reserved nonce and authenticated metadata, resume publication from those
same ciphertext bytes, not another secret ingestion/encryption/nonce. The same exact-copy
recovery is permitted for a previously stored record whose destination is missing, only when
the retained unique staging copy authenticates and matches its immutable original receipt.
Keep that receipt, nonce and effective retirement state unchanged. Missing/corrupt/ambiguous
copies of an already receipted record require maintenance without relabeling it as ingress
loss; only a pending, never-receipted command can become secret_input_lost.
Ambiguous staging fails
closed; staging existence is never silently called irrecoverable loss. A command whose bytes
are irrecoverably missing becomes secret_input_lost; valid
unexpected encrypted files are quarantined/non-dispatchable and retained only when their
authenticated key/nonce is already durably reserved in the bound journal. An authenticated
unexpected ciphertext with an absent nonce reservation means lost nonce history: fail
`maintenance_required`, preserve all bytes, and do not automatically insert/burn the nonce
or reconstruct history. Test both known-reserved quarantine and absent-reservation refusal.
Never auto-delete
staging/orphans. Partial/corrupt/global journal ambiguity fails closed. Recovery may validate
AEAD and exact nonsecret identities inside the gateway, never use supplied replacement secret.
Distinguish ciphertext publication, custody receipt, provider binding and model dispatch.

## Acceptance

TDD demonstrates existing raw storage/hash defect, then genuine encrypted store/reopen/query/
retire through the actual gateway channel with synthetic bytes. Include independent-process
nonce/command/mutation races, delayed store versus query, collision exhaustion/restart,
crashes before and after nonce reservation/staging/publication/receipt, a partial destination
write (retained fail-closed with no receipt/overwrite), exact staged-ciphertext resumption,
no duplicate record,
and persistent retirement denial. Validate strict envelope mutation/swap/bounds and inspect
every temporary file/sidecar/receipt/error for plaintext and its digest absence.

Test missing/wrong root, ownership/mode/symlink/hardlink, swapped pair, partial/concurrent init,
legacy layouts unchanged, existing-pair no-op, close/FD release, and lifecycle maintenance
exclusion. Include same-root/different-records and same-records/different-root initializers,
plus a delayed accepted store before mutation-lock acquisition followed by unknown query and
its legitimate later commit. Preserve real framed channel/MAC tests; do not present disabled peer checking as
native Linux qualification. Import-boundary tests must prove no control-plane root/vault import.
No actual API calls, user keys, external maintenance, migrations, package installs or image edits.
Independent spec/quality review required. T025/T090 and release custody qualification stay open.
