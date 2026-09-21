# Owner material intake — originals-only implementation contract

2026-09-19. A connected slice of US1/T023, subordinate to `api.md`, `experience.md`
and `data-model.md`; not a substitute for extraction, understanding or the graph journey.

## User outcome and scope

On the supported work page, the owner can start with an explanation **or files**, without
connecting a model. Original files become part of an immutable work revision, survive refresh
and download byte-for-byte. Later text edits retain them. The page distinguishes an original
being stored from its contents being read. No upload starts a parser, model, extension, URL
fetch or external tool. Uploaded instructions have no instruction authority.

Reuse `PersistentWorks`, the existing works route contribution, owner boundary, DomainStore
CAS and public-event transaction. Do not use the legacy `Store.add_file`/`ingestion.extract`,
add a second file store, or rewrite historical v1 records. Existing graph/tool qualification
and exact-action approval work remains required and independent of this slice.

## Wire and bounded receiving

One original per `POST /api/v1/works/{work_id}/sources`; raw `application/octet-stream`.
Singleton case-insensitive `X-DeepTwin-Source-Metadata` is canonical unpadded base64url JSON:

```json
{"schema_version":"owner-source-upload-v1","command_id":"<canonical nonnil UUID>","expected_revision":1,"name":"자료.pdf","declared_media_type":"application/pdf","size":0,"sha256":"<64 lowercase hex digits>"}
```

The example's size/digest are placeholders, never valid evidence for actual bytes. Exactly
these seven fields; no duplicate JSON keys. Header <=2048 ASCII bytes, decoded <=1536 bytes,
depth <=2. Revision is an integer, not bool, >=1. Size is an integer, not bool, 0..10,485,760.
Name is 1..255 UTF-8 bytes, not `.`/`..`, with no slash, backslash, Unicode control/format/
surrogate characters. Preserve accepted spelling only as display text, never as a path.
Declared MIME is <=127 ASCII bytes, lowercase type/subtype, no whitespace/parameters/wildcard;
tokens start alphanumeric and then use alphanumerics or `!#$&^_.+-`. Browser empty/unsupported
MIME declarations use `application/octet-stream`. Declared MIME is not verified format.

Initial visible limits: 10 MiB/file, 20 sources/work, 50 MiB original bytes/work. Count all
attached sources against current immutable records, not client counters. Configurable larger
limits and extraction/archive limits remain open acceptance, not silently claimed complete.
Zero-byte and unsupported-format originals are allowed. No truncation.

The upload path is a distinct body-admission branch: cheap exact path/method/header/length
checks, existing persistent session/Origin/CSRF authentication, then receiving. Do not raise
the general JSON body cap. Reject duplicate metadata/length, content encoding, malformed
metadata and declared length mismatches. Bound actual bytes in a bytearray, verify exact count
and digest, and enforce a 60-second monotonic total receive deadline including slow chunks.
Stop on disconnect/cancellation. This is bounded memory followed by CAS, not disk streaming.

After authentication acquire a nonblocking OS lock on the separate fixed
`owner-material-upload.lock` in the canonical app-owned data directory; retain it through
publication and commit. Follow existing checked no-follow parent/file discipline: correct
owner, private modes, regular empty single-link file and independently opened FD. Do not use
the serving owner's `owner-auth.lock`, repair ownership or unlink/recreate lock inodes.
Independent processes sharing the same local vault must contend; return 429 with bounded
Retry-After immediately. Always close in finally. No SQLite writer while waiting on network.
If HTTP cancellation occurs while a noncancelled threadpool publication/commit is running,
retain lock ownership until that actual operation finishes, not merely until its awaiter exits.
This does not add multi-host/network-filesystem support.

## Durable lineage and atomicity

Add closed versioned content profiles using existing domain kinds:

- `source-original-artifact-v1`: exact BlobRef, size/digest, display filename, declared MIME,
  byte-based media indication, `format_validation=not_performed`, `owner_upload` origin,
  `stored` availability, unknown rights. No invented license, parser or producer claim.
- `owner-upload-source-v1`: exact artifact ref, work ID, upload command, supplied-by actor,
  source kind upload, acquisition event sequence, display filename and nullable unknown rights.
- `work-revision-v2`: real text, existing work/version/parent ancestry and ordered source refs,
  input origin `owner_material` for attachments/file-first, `owner_text` for text edits.

Feature-specific schema validation must not invalidate unrelated historical generic records.
Generated schema changes require normal generator verification; historical qualification
manifests are not silently rewritten to agree with changed schema bytes.

Create-v2 uses exactly schema_version, command_id, text, input_origin at the existing create
route (`work-create-command-v2`). Empty text is allowed only with owner_material. File-first
creates this honest empty draft and then uploads; failure/cancel may leave the draft, never a
fabricated explanation. Keep v1 nonempty rules. Revise-v2 uses schema_version, command_id,
expected_revision, text (`work-revise-command-v2`); empty text is allowed only when sources
already exist. Both revise versions preserve every existing source. Version/origin affect
command fingerprints; v1 replay remains compatible.

Use a bounded indexed command journal in the existing vault DB, with command IDs unique
across text and upload mutations; consult historical text commands as necessary. An upload
fingerprint binds work, expected revision, filename, MIME, size and verified digest. Same
command/same input returns the original receipt even after later revisions. Changed target,
metadata or bytes conflicts. No second namespace that accepts a reused text command.

Authenticate and check work plus existing command identity before costly receive. For an unseen
command, require current expected revision. A matching committed replay remains admissible
after later revisions; do not reject its original expected revision against the current head.
If replay bytes are sent, still verify exact body size/digest; the separate receipt read need
not resend bytes. Check replay before latest-revision CAS again in the final writer.
Reauthenticate before CAS publication.
Call existing `put_blob(..., purpose="operational")` outside the final relation transaction.
Within one final domain writer: reauthenticate; check replay/CAS/capacity/blob registration;
write artifact+source+new work revision; append source.stored and work.revised; persist exact
receipt. Allocate acquisition event identity without a digest reference cycle. Replayed
commands emit nothing new. New text changes emit existing work.created/revised events, without
backfilling old history. Do not emit ingestion events when extraction was never attempted.

Rollback leaves no new work/source/event/receipt relation. An already sealed unattached CAS
blob may remain for later explicit reconciliation; never opportunistically delete canonical
objects or claim attachment success. Keep existing finite DB busy bounds.

## Readback and browser behavior

Add authenticated GET/HEAD `/{work_id}/revisions/{revision}`,
`/{work_id}/sources/{source_id}`, and `/{work_id}/sources/{source_id}/content` below
`/api/v1/works`, plus exact receipt lookup `/api/v1/works/commands/{command_id}`. The latter
works before a create response returns a work ID; route matching must not treat `commands`
as a work UUID. All inputs and outputs remain bounded. Verify source membership in
the work's retained revisions before resolving a BlobRef. No arbitrary hash/ref downloads.
Recheck revoked sessions. Original content is an attachment with safe ASCII/UTF-8 filename
encoding, octet-stream, nosniff/no-store and existing CSP. HEAD matches headers without a body.
No inline HTML/SVG/PDF, active preview, object-URL rendering or arbitrary range support.

Inspect at most the first 4096 bytes for PDF/PNG/JPEG/ZIP/HTML/SVG signatures; optional bounded
UTF-8 validation proves encoding only. Record method/version/confidence separately from
declared MIME. ZIP is not DOCX, PDF signature is not validated PDF. Detected ambiguity remains
unknown; bounded signature inspection cannot prove absence of embedded formats/polyglots.
No archive expansion; decompression safety is explicitly unvalidated.

Extend the existing same-work surface and approved palette/type system, not a new wizard or
settings console. Accessible `자료 추가`, file selection/list, per-file status/retry/cancel/
download. Show initial limits and `원본 보관됨` only after commit; show `내용 읽기는 아직
지원되지 않습니다` separately. No fake reading progress or model dependency.

The supported session client currently sends JSON only and keeps CSRF private. Extend that
same closure with a narrowly typed source-upload method: raw bounded bytes, fixed metadata
header and octet-stream, exact same-deployment work-source POST path and optional cancellation
signal. Do not expose the token, duplicate session acquisition in the work page, accept caller
header/credential overrides or turn the generic JSON request into arbitrary raw HTTP. Preserve
JSON callers and existing 401/command-403 session invalidation. Test both base-path profiles,
wrong routes and headers, exact bytes, cancellation and token non-disclosure.

Text save and sequential uploads share a revision fence. Save a pending explanation first,
or create the empty material-origin draft. Do not overwrite newer unsaved edits with a late
upload response. Keep pending File objects in page memory, never localStorage; refreshed pages
reload committed originals. Preserve draft/selections on conflicts; show saved revision
separately, then use a new command after explicit rebase, never auto-overwrite another tab.

Lost response/abort is not rollback. Show `저장 상태 확인 중`; query exact receipt or retry
identical command+bytes. A receipt not yet found is not proof that an in-flight commit cannot
still finish: retain the same command descriptor, never retire it and mint a replacement only
because a lookup returned 404. Contention/retry keeps the exact command identity. A committed
attachment stays committed. Future understanding freezes
the exact WorkRevision→Source→Artifact→BlobRef lineage under explicit transmission authority;
this slice must not mark content as read or invent extraction coverage.

Persist a bounded immutable pending-command descriptor in the existing deployment-scoped
draft state: schema, operation, original target/expected revision, command ID and exact
text/origin or upload metadata. Keep it until the exact receipt is resolved; never reconstruct
a retry from the latest draft/revision or downgrade create-v2 to v1. No credentials, cookies,
CSRF tokens or file bytes in this descriptor. Retain current unsaved draft separately.
After refresh, recover even a lost file-first create response by command lookup or exact
create-v2 replay, without creating a second draft. Upload recovery can query its receipt;
uncommitted byte retry requires reselecting and verifying the same original. Migrate existing
pending v1 state only when its exact original command is reconstructible; otherwise show an
unresolved draft, never silently invent replay authority.

## Acceptance evidence

Use real temporary owner/DomainStore API tests: file-first and explanation-first, multiple
originals, refresh and identical download, zero-byte/unknown/Unicode/active-format bytes,
attachment retention through edits, historical v1, exact replay after later edits, command
reuse/changed bytes rejection, concurrent-tab CAS, rollback/events, auth revocation mid-upload,
source membership/HEAD, overflow/slow/disconnect/duplicate headers and finite lock contention.
Lock tests include separate independent processes and abrupt holder exit.
Replay a committed upload after the work reaches its file/byte cap: replay creates no extra
source/revision/event and is not rejected for capacity. Verify lost file-first create response
then refresh, and lost upload response plus newer unsaved text then refresh. Recover exact
receipts without duplicate drafts or overwriting text; revise-v2 retry retains its original
expected revision after later uploads. Exercise cancellation during an actual delayed commit
and prove the upload lock remains held until that commit terminates.

Add work-page logic tests and one bounded controlled-browser end-to-end path with actual
temporary persistence, reload/download and unsaved edit/cancel behavior. Verify keyboard,
360/1024/wide layouts and light/dark screenshots. No live provider/microphone/user files.
Independent spec+quality review gates completion. This accepts originals-only intake, not
whole T023/US1, arbitrary media extraction, design generation or release qualification.
