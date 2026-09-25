"""T073 × T023: deleting an original erases the text read from it.

A reading keeps its text as its own content-addressed blob, never inside the record.
The source-deletion preview lists every reading of the original (and the work-model
drafts made from them); on consent each reading's text gets its own tombstone and its
bytes are removed after the commit, exactly as the original's. The reading records stay
as metadata answering `deleted`, nothing derived is shown or sent again, and a backup
taken afterwards does not carry the text (one taken before still does — the preview says
so). A synthetic canary is scanned for byte by byte in the store's database files and
blob directories, and in the backup archives. No network, key or model call (the model
turn below is a local mock transport).
"""

import json
from pathlib import Path
from uuid import uuid4

from app.domain.refs import EntityRef
from app.tests.test_source_readings import (
    READINGS,
    attach,
    get,
    material_work,
    post,
    read_body,
)

CANARY = "CANARY-읽힌글자-5e1d"
# the BOM makes the kept text differ from the original's bytes: two content addresses
ORIGINAL = b"\xef\xbb\xbf" + f"분기 메모 {CANARY} 끝".encode()
READ_TEXT = f"분기 메모 {CANARY} 끝"


def preview_body(source_id, request_id):
    return {"schema_version": "source-deletion-preview-command-v1", "request_id": request_id,
            "source_ids": [source_id], "reason_code": "user_requested"}


def confirm_body(view):
    return {"schema_version": "source-deletion-command-v1", "request_id": view["request_id"],
            "source_ids": [item["source_id"] for item in view["items"]], "reason_code": view["reason_code"],
            "preview_sha256": view["preview_sha256"], "confirmed": True}


def files_holding(root: Path, needle: bytes, *, skip=()):
    """Every regular file under root whose bytes contain needle (database, WAL, blobs)."""
    found = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and not any(part in path.parts for part in skip) and needle in path.read_bytes():
            found.append(path.relative_to(root).as_posix())
    return found


class PlainPort:
    """A test crypto port: the archive in the clear behind the age header, so the
    backup file itself can be scanned. Only the test uses it."""

    def encrypt(self, archive, *, key_mode, recipient=None):
        from app.operations.backup import CIPHERTEXT_HEADER

        return CIPHERTEXT_HEADER + archive

    def decrypt(self, ciphertext, *, key_mode, identity=None):
        from app.operations.backup import CIPHERTEXT_HEADER

        return ciphertext[len(CIPHERTEXT_HEADER):]


def backup(vault: Path, out: Path):
    from app.operations.backup import create_backup

    out.mkdir()
    outcome = create_backup(vault, out, key_mode="instance_backup_key", server_release="1.0.0", crypto=PlainPort())
    assert outcome.state == "ready", outcome.failure
    return outcome


def test_deleting_an_original_erases_its_readings_text_and_later_backups_lack_it(tmp_path):
    from app.tests.test_work_exports_api import worker_app

    needle = CANARY.encode()
    with worker_app(tmp_path, worker=False) as subject:
        data = tmp_path / "data"
        work = attach(subject, material_work(subject, "설명"), ORIGINAL, name="메모.txt", media="text/plain")
        source_ref = work["source_refs"][0]
        first_body = read_body(source_ref)
        reading = post(subject, f"{READINGS}/{work['work_id']}", first_body)
        assert reading.status_code == 201, reading.text
        reading = reading.json()
        assert reading["state"] == "complete" and reading["text"] == READ_TEXT and reading["text_state"] == "kept"
        record = subject.domain.get(EntityRef.from_dict(reading["reading_ref"]))
        blob = record.body["content"]["text_blob_ref"]
        assert "text" not in record.body["content"] and blob["size"] == len(READ_TEXT.encode())
        # the text lives only in its own blob (and the original), never in the database files
        held = files_holding(data, needle)
        assert f"domain-cas/operational/{blob['sha256']}" in held
        assert not [name for name in held if not name.startswith("domain-cas/")], held
        before = backup(data, tmp_path / "before")

        request_id = str(uuid4())
        preview = post(subject, f"api/v1/works/{work['work_id']}/deletions/preview",
                       preview_body(source_ref["id"], request_id))
        assert preview.status_code == 200, preview.text
        view = preview.json()
        [item] = view["items"]
        assert item["readings"] == [{"reading_id": reading["reading_ref"]["id"], "source_id": source_ref["id"],
                                     "state": "complete", "kept_characters": len(READ_TEXT),
                                     "read_at_utc": reading["read_at_utc"], "text_state": "stored"}]
        assert item["work_models_from_its_readings"] == [] and item["reading_text_shared_with_other_readings"] == []
        assert reading["reading_ref"] in view["affected_refs"]
        assert view["backups"] == {"made_after": "hold_neither_the_original_nor_text_read_from_it",
                                   "made_before": "still_hold_both_owner_held_and_not_rewritten"}
        assert "backups_made_before_this_deletion" in view["not_reached"]
        assert CANARY not in preview.text  # the preview names what goes, never its content
        # a reading made after the preview changes the scope: the old preview is stale
        again = post(subject, f"{READINGS}/{work['work_id']}", read_body(source_ref))
        assert again.status_code == 201
        stale = post(subject, f"api/v1/works/{work['work_id']}/deletions", confirm_body(view))
        assert stale.status_code == 409
        assert files_holding(data, needle)  # nothing was erased by a refused deletion
        view = post(subject, f"api/v1/works/{work['work_id']}/deletions/preview",
                    preview_body(source_ref["id"], str(uuid4()))).json()
        assert len(view["items"][0]["readings"]) == 2

        deleted = post(subject, f"api/v1/works/{work['work_id']}/deletions", confirm_body(view))
        assert deleted.status_code == 200, deleted.text
        [result] = deleted.json()["deleted"]
        assert result["bytes_removed"] is True
        # both readings kept the same text: one content address, one tombstone, removed
        assert [entry["text_removed"] for entry in result["readings"]] == [True, True]
        assert deleted.json()["backups"] == view["backups"]

        # nothing of the text is left in any store file: database, WAL or blob directory
        assert files_holding(data, needle) == []
        assert not (data / "domain-cas" / "operational" / blob["sha256"]).exists()
        with subject.domain._connection() as db:
            tombstones = [json.loads(row[0])["content"] for row in db.execute(
                "SELECT body FROM domain_records WHERE kind='decision_record' AND instr(body, ?) > 0",
                (b"blob-erasure-v1",))]
        kinds = sorted(item["former_kind"] for item in tombstones)
        assert kinds == ["original", "source_reading_text"]
        assert CANARY not in json.dumps(tombstones, ensure_ascii=False)

        # readers answer deleted; the reading records stay as metadata
        [entry] = get(subject, f"{READINGS}/{work['work_id']}").json()["sources"]
        assert entry["original_state"] == "deleted"
        assert entry["reading"]["text_state"] == "deleted" and entry["reading"]["state"] == "complete"
        assert "excerpt" not in entry["reading"] and "text" not in entry["reading"]
        latest = get(subject, f"{READINGS}/{work['work_id']}/{source_ref['id']}")
        assert latest.status_code == 410 and latest.json()["code"] == "deleted"
        assert CANARY not in latest.text
        assert subject.domain.get(record.ref).ref == record.ref  # the record reads back; the tombstone stands in
        replay = post(subject, f"{READINGS}/{work['work_id']}", first_body)
        assert replay.status_code == 201 and replay.json()["text_state"] == "deleted"
        assert CANARY not in replay.text
        fresh = post(subject, f"{READINGS}/{work['work_id']}", read_body(source_ref)).json()
        assert fresh["state"] == "unreadable" and fresh["reasons"] == ["deleted"] and fresh["text"] == ""

        # a backup taken afterwards does not carry the text; the one taken before still does
        after = backup(data, tmp_path / "after")
        assert needle not in after.ciphertext_path.read_bytes()
        assert not any(blob["sha256"] in ref["path"] for ref in after.manifest["item_refs"])
        assert needle in before.ciphertext_path.read_bytes()


def test_the_preview_lists_work_model_drafts_made_from_a_reading_and_they_stop_receiving_it(tmp_path):
    from app.tests.test_claude_live_path import connected
    from app.tests.test_work_models import app_with, authored, draft_body, messages
    from app.tests.test_work_models import post as model_post

    spy, context = app_with(tmp_path, authored())
    with context as subject:
        choice = connected(subject)
        subject.path = subject.profile.base_path + "api/v1/works"
        work = attach(subject, material_work(subject, "분기 보고서 정리"), ORIGINAL, name="메모.txt",
                      media="text/plain")
        source_ref = work["source_refs"][0]
        assert post(subject, f"{READINGS}/{work['work_id']}", read_body(source_ref)).status_code == 201
        with subject.domain._connection() as db:
            sha = db.execute("SELECT sha256 FROM domain_records WHERE kind='work_revision' AND id=? AND version=?",
                             (work["work_id"], work["revision"])).fetchone()[0]
        revision = EntityRef("work_revision", work["work_id"], work["revision"], sha)
        drafted = model_post(subject, "api/v1/work-models", draft_body(revision, choice))
        assert drafted.status_code == 200, drafted.text
        work_model_id = drafted.json()["work_model_id"]
        view = post(subject, f"api/v1/works/{work['work_id']}/deletions/preview",
                    preview_body(source_ref["id"], str(uuid4()))).json()
        assert view["items"][0]["work_models_from_its_readings"] == [work_model_id]
        assert any(ref["kind"] == "work_model" and ref["id"] == work_model_id for ref in view["affected_refs"])
        assert post(subject, f"api/v1/works/{work['work_id']}/deletions", confirm_body(view)).status_code == 200
        # a later draft no longer receives the erased text
        assert model_post(subject, "api/v1/work-models", draft_body(revision, choice)).status_code == 200
        first, second = [json.loads(json.loads(raw)["messages"][0]["content"]) for _request, raw in messages(spy)]
        assert CANARY in json.dumps(first, ensure_ascii=False)
        assert second["work_revision"] == {"text": "분기 보고서 정리"}
        assert CANARY not in json.dumps(second, ensure_ascii=False)
