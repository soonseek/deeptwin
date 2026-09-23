# T073 slice — explicit deletion of stored originals with tombstones (2026-09-23)

Status: **deletion of originals landed; T073 stays open.** Still open: deleting records other
than originals, backup create/restore from the GUI (T070/T081), and backup cleanup.

## Store (`app/domain/store.py`), no schema migration

- **Tombstone.** An explicit deletion leaves one immutable tombstone per content address. It is
  a `decision_record` with `blob-erasure-v1` content at `erasure_identity(vault, purpose,
  sha256)`, an identity derived from the address alone, so every reader finds it with one
  lookup.
  - It carries the contract's minimal tombstone fields: `object_id`, `former_kind`,
    `deleted_at`, `deletion_request_id`, `affected_refs` and `reason_code`. It also carries the
    preview digest and the blob's address as flat fields, never as a blob reference.
  - It never contains the deleted content or the file name.
  - A row at the tombstone identity that is not exactly this blob's tombstone is `CorruptRecord`,
    never a pass.
- **`_erase_in_transaction(db, blob, tombstone)`** seals the tombstone inside the caller's
  writer. It accepts only a registered blob, refuses legacy-linked content, and checks the exact
  identity and fields. **`remove_erased_bytes(blob)`** unlinks the file only once a committed
  tombstone exists, fsyncs the directory, and returns True only after confirming absence.
  Because the bytes go after the commit, a rollback never leaves a hole.
- **Readers.**
  - `_blob_bytes` raises `ErasedBlob`.
  - `_check_graph` skips an erased blob (the tombstone stands in), so every record that named
    it still reads back.
  - A new record that references the deleted bytes directly is refused.
  - `put_blob` of the same bytes is refused, so a deletion is never silently undone under old
    records.
- **Backup** (`app/operations/backup.py`) archives and verifies only live originals. A
  restored vault keeps the tombstone and answers `ErasedBlob`.

## Service and routes (`app/services/source_deletions.py`, works-v1)

- `POST /api/v1/works/{id}/deletions/preview`: the exact scope, computed by the server.
  - Each original: name, media type, size, digest, and how many revisions name it.
  - Other sources holding the same bytes, since content-addressed storage keeps one copy.
  - Every affected record: the holders of the blob, the records that name those, and every
    work revision naming the source.
  - What the deletion cannot reach: backups made before it, copies already exported or sent,
    and copies outside this instance.
  - `preview_sha256` over all of it, plus the request id and reason. Nothing is deleted.
- `POST /api/v1/works/{id}/deletions`: requires `confirmed: true` and the exact digest.
  - It recomputes the scope in the writer; any change is `409`.
  - It seals one tombstone per distinct blob plus `retention.deleted {object_count,
    byte_count}` in one transaction, then removes the bytes and reports `bytes_removed` per
    original. It never reports removal it did not confirm.
  - An exact replay returns the same deletion (`bytes_removed: null`, meaning not
    re-observed); another request over deleted bytes conflicts.
  - Reasons are `user_requested` and `rights_request`.
- `GET …/sources/{id}` now states `original_state` (`stored`/`deleted`). `…/content` of a
  deleted original is `410 deleted`. Installed routes went from 60 to 62.

## GUI

- `app/static/source-deletion.mjs` is mounted on the work screen as `#work-deletion`
  (optional).
  - It lists originals with their state; nothing is preselected.
  - A reason, then a preview that shows the server's scope, shared copies and what the
    deletion cannot reach.
  - A separate consent box, off by default. A stale preview is refused and cleared.
  - The result says per original whether removal was confirmed or is pending.
- The records page and both guides now describe this. The records page no longer says there
  is no deletion screen.

## Observed

- `test_source_deletions.py`: **3 passed**.
  - Preview before deletion; consent refused when implicit, with a wrong digest or with
    another reason.
  - After deletion: the bytes are gone from disk, content returns 410, metadata says
    `deleted`, the work and source records still read, and the tombstone carries no name.
  - The `retention.deleted` metadata, replay, conflict, and refusal of re-storing the bytes.
  - A source shared with another work is stated, and that work's source reads deleted too.
  - A change after the preview conflicts and nothing is removed.
  - The wire is closed; no session is refused.
- `test_backup.py`: **15 passed**, including a deleted original that stays deleted through
  backup and restore.
- Broad regression: domain storage, owner material, works, exports, route counts, runs,
  consents, server, events and runtime ledger, **1199 passed**.
- `source-deletion.test.mjs`: 5 passed. `work.test.mjs` + `work-export.test.mjs`: 39 passed.
  `records-page.test.mjs`: 3 passed.
- `browser-records.test.mjs`: **3 passed** in real Chromium. The new case: file stored through
  the work screen → preview removes nothing → consent is required → deletion → the download
  returns 410 and the list says `삭제됨` → the records log shows `retention.deleted`.
- `browser-owner-material-intake.test.mjs` keeps its one known Linux-only failure (the download
  suggested-filename), which was recorded before this change.

All of this is synthetic test-actor evidence.
