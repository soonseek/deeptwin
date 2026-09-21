# Post45 carrier — controller preflight

2026-09-20. Advisory design decision only. Task45 R4 full72 is still running with one failure
marker and no final traceback; this note does not accept Task45 or dispatch product implementation.

## Decision and reason

Accept the draft's dedicated authenticated binary carrier as the recommended design direction,
not as measured release support. Keep the proposed 48 MiB aggregate, 32 KiB header, 128 objects,
8 MiB maximum individual report and 60-second receive deadline. The existing default DomainStore
blob limit remains16 MiB and full graph remains64 MiB. No old route limit changes, base64 wrapper,
general-purpose upload registry, or end-user source-file/CLI workflow is introduced.

This is a code-owned release-evidence transport, distinct from the user's work-material upload.
The browser user selects an offered trusted release; deployment/distribution provides its evidence.
Actual report/graph fit and trusted release production remain separate gates; rejection must be
honest if a real packet exceeds the selected profile. These bounds do not prove peak process memory
or production throughput. If the actual release does not fit, revisit the profile explicitly.

## Required implementation precision before dispatch

1. Retain global origin/path/singleton-header checks, then exact family/media/length preflight,
   then authenticate before any ASGI body receive. Reject malformed or conflicting lengths,
   transfer/content encodings, unsupported method/query, or an oversized declared body before
   allocation. Keep this as an exact new family; do not expand unrelated route admission.
2. Acquire existing `UploadLock` after authentication. It is nonblocking and process-shared;
   contention returns capacity, not a second receiving buffer. Reuse its existing no-follow
   ownership checks. Map its `WorkServiceError` into this route's closed installation error
   shape instead of accidentally emitting the work-upload response family.
3. Use a single monotonic receive deadline across all fragments, not60 seconds per object.
   Parse the 12-byte prefix and bounded canonical header incrementally; validate roles, unique
   digests, positive sizes and all aggregate limits before collecting object bytes. Exact wire
   length and per-object hashes must match, including when prefix/header/object boundaries fall
   inside one ASGI chunk. No trailing bytes or decompression. Avoid repeated whole-body immutable
   concatenation or retaining both a joined full packet and copied individual payloads.
4. The endpoint must await `upload_lock.publish(service.execute, ...)`, as the existing source
   upload endpoint does, rather than plain `run_in_threadpool`. `UploadLock.publish` shields its
   owned task and retains the FD until the actual thread finishes. HTTP cancellation does not
   prove synchronous verification/publication stopped. Boundary cleanup may call close, but must
   not release the lease early while the owned operation is still active.
5. Cancellation before publish releases all receive buffers/lease with no domain writes. After
   publish starts, the service may complete and commit despite HTTP disconnect; the next exact
   authenticated retry/read retrieves the durable result. Do not promise physical CAS-blob
   rollback. Admission and final transaction rechecks remain mandatory.
6. Preseal only the independently authenticated allowed release's exact evidence closure. Fixed
   one-allow policy plus one-verification capacity must actually bound accepted/unattached content;
   matching a caller's internally consistent hashes alone is insufficient. No new orphan registry
   or cleanup/deletion workflow is authorized by this carrier decision.

## Focused proof required

Actual ASGI tests: unauthorized never calls receive; malformed prefix/length/duplicate headers;
every prefix/header/object split and multi-object chunk; exactly-at-cap and one-byte-over;
declared-short/long, trailing bytes, digest mismatch; disconnect and timeout with lease reuse;
same-process and second-process lock contention; cancellation during actual owned publication
retains the lease until completion, followed by byte-identical authenticated receipt/retry.
Use bounded synthetic byte fixtures and temporary stores, not real credentials or release approval.

## Read-only source evidence

- `app/api/web_boundary.py`: source upload authenticates before receiving; creates UploadLock;
  final cleanup closes it. Other existing body limits must remain unchanged.
- `app/api/owner_material_upload.py`: finite total receive deadline, bytearray and SHA256,
  disconnect and declared-size checks are the existing pattern, not a reusable release parser.
- `app/api/works.py`: upload route calls `request.state.upload_lock.publish(intake.publish, ...)`.
- `app/services/owner_material_upload_lock.py`: nonblocking flock; publish creates/shields actual
  thread task; close refuses premature release while that task is not done.
- `app/domain/store.py`: default blob16 MiB and graph64 MiB are separate limits.

No product files or test processes changed by this preflight. G1 adapter grammar/research and
independent plan preflight are still required before the complete next slice is executable.
