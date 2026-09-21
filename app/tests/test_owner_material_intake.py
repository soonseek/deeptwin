"""Original storage over the actual supported owner boundary and canonical vault."""
import base64
import hashlib
import json
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import owner_app, post


def material_work(subject, text=""):
    return post(subject, {"schema_version": "work-create-command-v2", "command_id": str(uuid4()),
                          "text": text, "input_origin": "owner_material"})


def metadata(data=b"original", **changes):
    return {"schema_version": "owner-source-upload-v1", "command_id": str(uuid4()),
            "expected_revision": 1, "name": "자료.pdf", "declared_media_type": "application/pdf",
            "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), **changes}


def upload(subject, work, data=b"original", meta=None):
    meta = meta or metadata(data)
    encoded = base64.urlsafe_b64encode(json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode()).rstrip(b"=").decode()
    return subject.client.post(subject.path + "/" + work["work_id"] + "/sources", content=data,
        headers={**headers(subject.profile, subject.csrf), "content-type": "application/octet-stream",
                 "X-DeepTwin-Source-Metadata": encoded})


def events(subject):
    with subject.domain._connection() as db:
        return [(r[0], bytes(r[1])) for r in db.execute("SELECT event_type,envelope FROM api_event_envelopes ORDER BY sequence")]


def test_file_first_commits_exact_lineage_then_reads_and_downloads_original(tmp_path):
    # Missing v2 creation/upload or wrong blob/source/revision relation breaks this journey.
    with owner_app(tmp_path) as subject:
        created = material_work(subject)
        assert created.status_code == 201, created.text
        work = created.json()
        assert work["text"] == "" and work["source_refs"] == []
        data = b"%PDF-1.7\nnot a validated PDF\x00"
        meta = metadata(data)
        response = upload(subject, work, data, meta)
        assert response.status_code == 201, response.text
        saved = response.json()
        assert saved["revision"] == 2 and saved["text"] == ""
        assert len(saved["source_refs"]) == 1
        source = subject.domain.get(EntityRef.from_dict(saved["source_refs"][0]))
        content = source.body["content"]
        assert content["schema_version"] == "owner-upload-source-v1"
        assert content["upload_command_id"] == meta["command_id"]
        artifact = subject.domain.get(EntityRef.from_dict(content["artifact_ref"]))
        assert artifact.body["content"]["format_validation"] == "not_performed"
        assert artifact.body["content"]["rights"] is None
        base = subject.path + "/" + work["work_id"]
        download = subject.client.get(base + "/sources/" + source.ref.id + "/content", headers=headers(subject.profile))
        assert download.status_code == 200 and download.content == data
        assert download.headers["content-type"] == "application/octet-stream"
        assert download.headers["content-disposition"].startswith("attachment;")
        assert "filename*=UTF-8''" in download.headers["content-disposition"]
        assert download.headers["x-content-type-options"] == "nosniff"
        head = subject.client.head(base + "/sources/" + source.ref.id + "/content", headers=headers(subject.profile))
        assert head.content == b"" and head.headers == download.headers
        assert subject.client.get(base, headers=headers(subject.profile)).json() == saved
        assert subject.client.get(base + "/revisions/1", headers=headers(subject.profile)).json() == work
        receipt = subject.client.get(subject.path + "/commands/" + meta["command_id"], headers=headers(subject.profile))
        assert receipt.status_code == 200 and receipt.json() == saved
        emitted = events(subject)
        assert [kind for kind, _ in emitted][-3:] == ["work.created", "source.stored", "work.revised"]
        source_event = json.loads(emitted[-2][1])
        assert content["acquisition_event_sequence"] == source_event["sequence"]


def test_replay_after_text_edits_preserves_original_receipt_and_sources(tmp_path):
    with owner_app(tmp_path) as subject:
        created = material_work(subject)
        assert created.status_code == 201, created.text
        work = created.json()
        meta = metadata()
        saved = upload(subject, work, meta=meta).json()
        revision_path = subject.path + "/" + work["work_id"] + "/revisions"
        for version, schema in [(2, "work-revise-command-v1"), (3, "work-revise-command-v2")]:
            response = post(subject, {"schema_version": schema, "command_id": str(uuid4()),
                                     "expected_revision": version, "text": "새 설명"}, revision_path)
            assert response.status_code == 201, response.text
            assert response.json()["source_refs"] == saved["source_refs"]
        before = events(subject)
        assert upload(subject, work, meta=meta).json() == saved
        assert events(subject) == before
        assert upload(subject, work, b"changed!", meta).status_code == 400
        assert upload(subject, work, meta={**meta, "name": "other.pdf"}).status_code == 409
        assert post(subject, {"schema_version": "work-revise-command-v2", "command_id": meta["command_id"],
                             "expected_revision": 4, "text": "x"}, revision_path).status_code == 409


def test_empty_text_rules_and_create_receipt_replay_bind_version_origin(tmp_path):
    with owner_app(tmp_path) as subject:
        command = {"schema_version": "work-create-command-v2", "command_id": str(uuid4()),
                   "text": "", "input_origin": "owner_material"}
        created = post(subject, command)
        assert created.status_code == 201, created.text
        assert subject.client.get(subject.path + "/commands/" + command["command_id"], headers=headers(subject.profile)).json() == created.json()
        assert post(subject, command).json() == created.json()
        assert post(subject, {**command, "input_origin": "owner_text"}).status_code == 400
        assert post(subject, {**command, "text": "x"}).status_code == 409
        target = subject.path + "/" + created.json()["work_id"] + "/revisions"
        assert post(subject, {"schema_version": "work-revise-command-v2", "command_id": str(uuid4()),
                             "text": "", "expected_revision": 1}, target).status_code == 400


@pytest.mark.parametrize("data,name,mime,indicated", [
    (b"", "빈 파일", "application/octet-stream", None),
    (b"unknown\x00\xff", "아직 모르는 형식.bin", "application/x-custom", None),
    (b"<svg onload='evil()'></svg>", "active.svg", "image/svg+xml", "image/svg+xml"),
    (b"<!doctype html><html><script>evil()</script>", "active.html", "text/html", "text/html"),
    (b"PK\x03\x04not docx", "pretend.docx", "application/octet-stream", "application/zip"),
    (b"%PDF-1.7 <svg>", "ambiguous.pdf", "application/pdf", None),
])
def test_zero_unknown_unicode_active_and_ambiguous_originals_are_never_parsed(tmp_path, monkeypatch, data, name, mime, indicated):
    import app.ingestion
    def forbidden(*args, **kwargs):
        pytest.fail("Original storage invoked extraction")
    monkeypatch.setattr(app.ingestion, "extract", forbidden)
    with owner_app(tmp_path) as subject:
        work = material_work(subject, "자료 검토").json()
        result = upload(subject, work, data, metadata(data, name=name, declared_media_type=mime))
        assert result.status_code == 201, result.text
        source_id = result.json()["source_refs"][0]["id"]
        target = subject.path + "/" + work["work_id"] + "/sources/" + source_id
        detail = subject.client.get(target, headers=headers(subject.profile)).json()
        assert detail["artifact"]["media_indication"]["media_type"] == indicated
        assert detail["artifact"]["format_validation"] == "not_performed"
        assert subject.client.get(target + "/content", headers=headers(subject.profile)).content == data
        other = material_work(subject).json()
        assert subject.client.get(subject.path + "/" + other["work_id"] + "/sources/" + source_id + "/content", headers=headers(subject.profile)).status_code == 404
        assert subject.client.get(target + "/content", headers={**headers(subject.profile), "Range": "bytes=0-1"}).status_code == 400


@pytest.mark.parametrize("change", [
    {"size": True}, {"size": -1}, {"size": 10485761}, {"expected_revision": True}, {"expected_revision": 0},
    {"command_id": "00000000-0000-0000-0000-000000000000"}, {"name": "../a"}, {"name": ".."},
    {"name": "x\u202ehtml"}, {"name": "a\n"}, {"name": "가" * 86}, {"declared_media_type": "Text/Plain"},
    {"declared_media_type": "text/plain; charset=utf8"}, {"declared_media_type": "*/plain"},
    {"sha256": "A" * 64}, {"extra": "not allowed"},
])
def test_closed_upload_metadata_refuses_invalid_fields(tmp_path, change):
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        response = upload(subject, work, meta=metadata(**change))
        assert response.status_code == 400, response.text


def test_replay_remains_valid_at_twenty_source_capacity(tmp_path):
    with owner_app(tmp_path) as subject:
        first = material_work(subject).json()
        original_meta = metadata()
        original = upload(subject, first, meta=original_meta).json()
        latest = original
        for expected in range(2, 21):
            result = upload(subject, latest, b"", metadata(b"", expected_revision=expected))
            assert result.status_code == 201, result.text
            latest = result.json()
        assert len(latest["source_refs"]) == 20
        before = events(subject)
        assert upload(subject, latest, meta=metadata(expected_revision=21)).status_code == 413
        assert upload(subject, first, meta=original_meta).json() == original
        assert events(subject) == before


def test_fifty_mib_capacity_counts_canonical_originals_and_still_admits_replay(tmp_path):
    with owner_app(tmp_path) as subject:
        first = material_work(subject).json()
        data = b"x" * 10485760
        original_meta = metadata(data)
        result = upload(subject, first, data, original_meta)
        assert result.status_code == 201, result.text
        receipt = result.json()
        for expected in range(2, 6):
            result = upload(subject, first, data, metadata(data, expected_revision=expected))
            assert result.status_code == 201, result.text
        before = events(subject)
        assert upload(subject, first, b"x", metadata(b"x", expected_revision=6)).status_code == 413
        assert upload(subject, first, data, original_meta).json() == receipt
        assert events(subject) == before


def test_final_relation_failure_rolls_back_every_relation_but_keeps_unattached_cas(tmp_path, monkeypatch):
    from app.services import owner_material_journal
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        meta = metadata()
        before = events(subject)
        original = owner_material_journal.save
        def fail(*args):
            raise RuntimeError("controlled receipt failure after relation and events")
        monkeypatch.setattr(owner_material_journal, "save", fail)
        assert upload(subject, work, meta=meta).status_code == 503
        assert events(subject) == before
        with subject.domain._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind IN ('source','artifact')").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM domain_blobs").fetchone()[0] == 1
        assert subject.client.get(subject.path + "/commands/" + meta["command_id"], headers=headers(subject.profile)).status_code == 404
        monkeypatch.setattr(owner_material_journal, "save", original)
        assert upload(subject, work, meta=meta).status_code == 201


def test_text_command_reuse_for_upload_is_refused_before_body_and_v2_origin_is_typed(tmp_path):
    with owner_app(tmp_path) as subject:
        command = {"schema_version": "work-create-command-v2", "command_id": str(uuid4()), "text": "x", "input_origin": "owner_text"}
        response = post(subject, command)
        assert response.status_code == 201, response.text
        assert upload(subject, response.json(), meta=metadata(command_id=command["command_id"])).status_code == 409
        assert post(subject, {**command, "input_origin": {}}).status_code == 400


def test_historical_v1_command_without_journal_replays_without_rewriting_or_events(tmp_path):
    from app.domain.store import _writer
    from app.tests.test_works_api import create
    with owner_app(tmp_path) as subject:
        command_id = str(uuid4())
        saved = create(subject, command_id=command_id).json()
        ref = EntityRef.from_dict(saved["ref"])
        original = subject.domain.get(ref).body_bytes
        # Model the existing pre-journal record, whose canonical v1 body is unchanged.
        with _writer(), subject.domain._connection(write=True) as db:
            db.execute("DELETE FROM owner_material_commands WHERE command_id=?", (command_id,))
        before = events(subject)
        assert create(subject, command_id=command_id).json() == saved
        assert subject.domain.get(ref).body_bytes == original and events(subject) == before
        assert upload(subject, saved, meta=metadata(command_id=command_id)).status_code == 409


def test_download_rechecks_revocation_after_blob_read(tmp_path, monkeypatch):
    from app.domain.store import DomainStore
    with owner_app(tmp_path) as subject:
        work = material_work(subject).json()
        saved = upload(subject, work).json()
        original = DomainStore._blob_bytes
        def revoke_after_read(self, *args, **kwargs):
            data = original(self, *args, **kwargs)
            response = subject.client.post(subject.profile.base_path + "session/logout", json={"command_id": str(uuid4())},
                                           headers=headers(subject.profile, subject.csrf))
            assert response.status_code == 200
            return data
        monkeypatch.setattr(DomainStore, "_blob_bytes", revoke_after_read)
        response = subject.client.get(subject.path + "/" + work["work_id"] + "/sources/" + saved["source_refs"][0]["id"] + "/content",
                                      headers=headers(subject.profile))
        assert response.status_code == 401 and response.content != b"original"
