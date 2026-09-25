"""Owner-commanded readings of retained originals over the supported factory (T023).

A stored original is never read implicitly. The owner reads one exact source; the sealed
`extraction` record says `complete`, `partial` (with what was not read) or `unreadable`
(with why). PDF/DOCX go through the isolated document worker (the in-thread harness runs
the real service); without it nothing is sealed and the reader is `reader_unavailable`.
No network, key or model call.
"""

import base64
import hashlib
import io
import json
from uuid import uuid4

import pytest

from app.tests.test_web_owner_integration import headers
from app.tests.test_work_exports_api import synthetic_pdf, worker_app

READINGS = "api/v1/source-readings"


def post(subject, path, body):
    return subject.client.post(subject.profile.base_path + path, json=body,
                               headers=headers(subject.profile, subject.csrf))


def get(subject, path):
    return subject.client.get(subject.profile.base_path + path, headers=headers(subject.profile))


def material_work(subject, text=""):
    created = post(subject, "api/v1/works", {"schema_version": "work-create-command-v2", "command_id": str(uuid4()),
                                              "text": text, "input_origin": "owner_material"})
    assert created.status_code == 201, created.text
    return created.json()


def attach(subject, work, data, *, name, media):
    meta = {"schema_version": "owner-source-upload-v1", "command_id": str(uuid4()),
            "expected_revision": work["revision"], "name": name, "declared_media_type": media,
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    encoded = base64.urlsafe_b64encode(json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode()
                                       ).rstrip(b"=").decode()
    saved = subject.client.post(f"{subject.path}/{work['work_id']}/sources", content=data,
                                headers={**headers(subject.profile, subject.csrf),
                                         "content-type": "application/octet-stream",
                                         "X-DeepTwin-Source-Metadata": encoded})
    assert saved.status_code == 201, saved.text
    return saved.json()


def read_body(source_ref, command_id=None):
    return {"schema_version": "source-reading-command-v1", "command_id": command_id or str(uuid4()),
            "source_ref": source_ref}


def reading_count(subject):
    with subject.domain._connection() as db:
        return db.execute("SELECT count(*) FROM domain_records WHERE kind='extraction'").fetchone()[0]


def event_types(subject):
    with subject.domain._connection() as db:
        return [row[0] for row in db.execute("SELECT event_type FROM api_event_envelopes ORDER BY sequence")]


def docx_bytes(paragraphs):
    from docx import Document

    document = Document()
    for text in paragraphs:
        document.add_paragraph(text)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_a_text_original_is_read_only_on_command_complete_and_replay_safe(tmp_path):
    with worker_app(tmp_path, worker=False) as subject:
        work = attach(subject, material_work(subject), "분기 보고서 초안: 매출 표를 요약".encode(), name="메모.txt",
                      media="text/plain")
        source_ref = work["source_refs"][0]
        # storing never read it
        listed = get(subject, f"{READINGS}/{work['work_id']}")
        assert listed.status_code == 200, listed.text
        assert listed.json()["reader_attached"] is False
        [entry] = listed.json()["sources"]
        assert entry["reading"] is None and entry["name"] == "메모.txt" and entry["original_state"] == "stored"
        assert reading_count(subject) == 0
        body = read_body(source_ref)
        read = post(subject, f"{READINGS}/{work['work_id']}", body)
        assert read.status_code == 201, read.text
        view = read.json()
        assert view["state"] == "complete" and view["reasons"] == [] and view["method"] == "utf8-text-v1"
        assert view["text"] == "분기 보고서 초안: 매출 표를 요약" and view["source_ref"] == source_ref
        assert event_types(subject)[-1] == "ingestion.completed"
        # the exact replay returns the same reading and seals nothing more
        assert post(subject, f"{READINGS}/{work['work_id']}", body).json() == view
        assert reading_count(subject) == 1
        # the same command id naming anything else is a conflict
        other = post(subject, f"{READINGS}/{work['work_id']}", {**body, "source_ref": {**source_ref, "version": 2}})
        assert other.status_code == 409
        listed = get(subject, f"{READINGS}/{work['work_id']}").json()
        assert listed["sources"][0]["reading"]["state"] == "complete"
        assert "text" not in listed["sources"][0]["reading"] and listed["sources"][0]["reading"]["excerpt"]
        latest = get(subject, f"{READINGS}/{work['work_id']}/{source_ref['id']}")
        assert latest.status_code == 200 and latest.json() == view


@pytest.mark.parametrize(("data", "name", "media", "state", "reasons"), [
    ("앞부분은 읽힘 ".encode() + b"\xff\xfe" + "뒷부분도 읽힘".encode(), "섞인.txt", "text/plain", "partial",
     ["invalid_encoding"]),
    (b"binary\x00\x01\x02", "blob.txt", "text/plain", "unreadable", ["unsupported_format"]),
    (b"   \n\t ", "blank.md", "text/markdown", "unreadable", ["no_text"]),
    (b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "그림.png", "image/png", "unreadable", ["unsupported_format"]),
    ("가".encode() * 30_000, "긴.txt", "text/plain", "partial", ["truncated"]),
])
def test_partial_and_unreadable_originals_say_exactly_what_was_not_read(tmp_path, data, name, media, state, reasons):
    with worker_app(tmp_path, worker=False) as subject:
        work = attach(subject, material_work(subject, "설명"), data, name=name, media=media)
        read = post(subject, f"{READINGS}/{work['work_id']}", read_body(work["source_refs"][0]))
        assert read.status_code == 201, read.text
        view = read.json()
        assert (view["state"], view["reasons"]) == (state, reasons)
        if state == "unreadable":
            assert view["text"] == "" and event_types(subject)[-1] == "ingestion.failed"
        else:
            assert view["text"] and len(view["text"].encode()) <= 60_000
        # the original itself is untouched: it still downloads byte for byte
        content = subject.client.get(f"{subject.path}/{work['work_id']}/sources/{work['source_refs'][0]['id']}/content",
                                     headers=headers(subject.profile))
        assert content.status_code == 200 and content.content == data


def test_a_pdf_without_the_document_worker_is_not_sealed_and_says_the_reader_is_unavailable(tmp_path):
    with worker_app(tmp_path, worker=False) as subject:
        work = attach(subject, material_work(subject), synthetic_pdf(["page one"]), name="a.pdf",
                      media="application/pdf")
        refused = post(subject, f"{READINGS}/{work['work_id']}", read_body(work["source_refs"][0]))
        assert refused.status_code == 503
        assert refused.json()["code"] == "reader_unavailable" and refused.json()["retryability"] == "retryable"
        assert refused.json()["reason"] == "reader_unavailable"
        assert reading_count(subject) == 0
        assert get(subject, f"{READINGS}/{work['work_id']}").json()["sources"][0]["reading"] is None


def test_the_document_worker_reads_pdf_pages_and_docx_and_names_pages_without_text(tmp_path):
    with worker_app(tmp_path) as subject:
        work = material_work(subject)
        work = attach(subject, work, synthetic_pdf(["first page text"], []), name="두쪽.pdf", media="application/pdf")
        work = attach(subject, work, docx_bytes(["문단 하나", "문단 둘"]), name="문서.docx",
                      media="application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        work = attach(subject, work, b"%PDF-1.7\nnot really a pdf", name="broken.pdf", media="application/pdf")
        pdf, docx, broken = work["source_refs"]
        pdf_view = post(subject, f"{READINGS}/{work['work_id']}", read_body(pdf)).json()
        assert pdf_view["state"] == "partial" and pdf_view["reasons"] == ["pages_without_text"]
        assert pdf_view["page_count"] == 2 and pdf_view["pages_without_text"] == 1
        assert "first page text" in pdf_view["text"]
        docx_view = post(subject, f"{READINGS}/{work['work_id']}", read_body(docx)).json()
        assert docx_view["state"] == "complete" and "문단 하나" in docx_view["text"] and "문단 둘" in docx_view["text"]
        broken_view = post(subject, f"{READINGS}/{work['work_id']}", read_body(broken)).json()
        assert broken_view["state"] == "unreadable" and broken_view["reasons"] == ["corrupt"]
        states = [entry["reading"]["state"] for entry in get(subject, f"{READINGS}/{work['work_id']}").json()["sources"]]
        assert states == ["partial", "complete", "unreadable"]


def test_readings_admit_only_this_works_exact_sources_and_exact_bodies(tmp_path):
    with worker_app(tmp_path, worker=False) as subject:
        first = attach(subject, material_work(subject), b"one", name="one.txt", media="text/plain")
        second = attach(subject, material_work(subject), b"two", name="two.txt", media="text/plain")
        foreign = second["source_refs"][0]
        assert post(subject, f"{READINGS}/{first['work_id']}", read_body(foreign)).status_code == 404
        forged = {**first["source_refs"][0], "sha256": "0" * 64}
        assert post(subject, f"{READINGS}/{first['work_id']}", read_body(forged)).status_code == 404
        extra = {**read_body(first["source_refs"][0]), "state": "complete"}
        assert post(subject, f"{READINGS}/{first['work_id']}", extra).status_code == 400
        assert get(subject, f"{READINGS}/{first['work_id']}?x=1").status_code == 400
        assert get(subject, f"{READINGS}/not-a-uuid").status_code == 400
        assert get(subject, f"{READINGS}/{uuid4()}").status_code == 404
        assert get(subject, f"{READINGS}/{first['work_id']}/{first['source_refs'][0]['id']}").status_code == 404
        no_csrf = subject.client.post(subject.profile.base_path + f"{READINGS}/{first['work_id']}",
                                      json=read_body(first["source_refs"][0]), headers=headers(subject.profile))
        assert no_csrf.status_code in {401, 403}
        subject.client.cookies.clear()
        assert get(subject, f"{READINGS}/{first['work_id']}").status_code == 401
        assert reading_count(subject) == 0


def test_the_understanding_request_carries_only_the_readings_the_owner_made(tmp_path):
    from app.domain.refs import EntityRef
    from app.tests.test_claude_live_path import connected
    from app.tests.test_work_models import app_with, authored, draft_body, messages
    from app.tests.test_work_models import post as model_post

    spy, context = app_with(tmp_path, authored())
    with context as subject:
        choice = connected(subject)
        subject.path = subject.profile.base_path + "api/v1/works"
        work = attach(subject, material_work(subject, "분기 보고서 초안을 정리하는 업무"), "매출 표 원문".encode(),
                      name="표.txt", media="text/plain")
        work = attach(subject, work, b"\x89PNG\r\n\x1a\n" + b"\x00" * 16, name="그림.png", media="image/png")
        with subject.domain._connection() as db:
            sha = db.execute("SELECT sha256 FROM domain_records WHERE kind='work_revision' AND id=? AND version=?",
                             (work["work_id"], work["revision"])).fetchone()[0]
        revision = EntityRef("work_revision", work["work_id"], work["revision"], sha)
        reading = post(subject, f"{READINGS}/{work['work_id']}", read_body(work["source_refs"][0])).json()
        drafted = model_post(subject, "api/v1/work-models", draft_body(revision, choice))
        assert drafted.status_code == 200, drafted.text
        [(_request, raw)] = messages(spy)
        sent = json.loads(json.loads(raw)["messages"][0]["content"])["work_revision"]
        assert sent["text"] == "분기 보고서 초안을 정리하는 업무"
        assert sent["sources"] == [
            {"name": "표.txt", "reading_state": "complete", "reasons": [], "text": "매출 표 원문"},
            {"name": "그림.png", "reading_state": "not_read"},
        ]
        with subject.domain._connection() as db:
            parents = [row[0] for row in db.execute(
                "SELECT target_kind FROM domain_edges WHERE source_kind='work_model'")]
        assert "extraction" in parents
        del reading


def test_text_read_from_an_original_the_owner_deleted_is_no_longer_shown_or_sent(tmp_path):
    with worker_app(tmp_path, worker=False) as subject:
        work = attach(subject, material_work(subject, "설명"), "지울 원문".encode(), name="지울.txt", media="text/plain")
        source_ref = work["source_refs"][0]
        assert post(subject, f"{READINGS}/{work['work_id']}", read_body(source_ref)).json()["state"] == "complete"
        request_id = str(uuid4())
        preview = post(subject, f"api/v1/works/{work['work_id']}/deletions/preview", {
            "schema_version": "source-deletion-preview-command-v1", "request_id": request_id,
            "source_ids": [source_ref["id"]], "reason_code": "user_requested"})
        assert preview.status_code == 200, preview.text
        deleted = post(subject, f"api/v1/works/{work['work_id']}/deletions", {
            "schema_version": "source-deletion-command-v1", "request_id": request_id,
            "source_ids": [source_ref["id"]], "reason_code": "user_requested",
            "preview_sha256": preview.json()["preview_sha256"], "confirmed": True})
        assert deleted.status_code in {200, 201}, deleted.text
        # the read text was byte-identical to the original: one address, one tombstone
        assert [item["former_kind"] for item in _tombstones(subject)] == ["original"]
        [entry] = get(subject, f"{READINGS}/{work['work_id']}").json()["sources"]
        assert entry["original_state"] == "deleted" and entry["reading"]["text_state"] == "deleted"
        assert "excerpt" not in entry["reading"]
        gone = get(subject, f"{READINGS}/{work['work_id']}/{source_ref['id']}")
        assert gone.status_code == 410 and gone.json()["code"] == "deleted"
        again = post(subject, f"{READINGS}/{work['work_id']}", read_body(source_ref)).json()
        assert again["state"] == "unreadable" and again["reasons"] == ["deleted"] and again["text"] == ""


def _tombstones(subject):
    with subject.domain._connection() as db:
        return [json.loads(row[0])["content"] for row in db.execute(
            "SELECT body FROM domain_records WHERE kind='decision_record' AND instr(body, ?) > 0",
            (b"blob-erasure-v1",))]
