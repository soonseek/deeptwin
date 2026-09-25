"""T073: the owner's explicit deletion of a stored original (operations.md §5.1).

A preview states exactly what would go and what it touches; the deletion needs
explicit consent bound to that preview's digest; it leaves one tombstone per
content address and the `retention.deleted` event, removes the bytes only after
the commit, and every reader then answers `deleted` while the records that named
the original stay readable. Nothing is deleted automatically, nothing is undone,
and the deleted bytes are not silently stored again.
"""

import json
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.domain.store import ErasedBlob, erasure_identity
from app.tests.test_owner_material_intake import events, material_work, metadata, upload
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import owner_app

DATA = b"%PDF-1.7\nsynthetic original to delete\x00" * 8


def call(subject, work_id, path, body):
    return subject.client.post(f"{subject.path}/{work_id}/{path}", json=body,
                               headers=headers(subject.profile, subject.csrf))


def preview_body(source_ids, request_id=None, reason="user_requested"):
    return {"schema_version": "source-deletion-preview-command-v1", "request_id": request_id or str(uuid4()),
            "source_ids": source_ids, "reason_code": reason}


def confirm_body(preview, **changes):
    return {"schema_version": "source-deletion-command-v1", "request_id": preview["request_id"],
            "source_ids": [item["source_id"] for item in preview["items"]], "reason_code": preview["reason_code"],
            "preview_sha256": preview["preview_sha256"], "confirmed": True, **changes}


def stored_source(subject, data=DATA):
    work = material_work(subject).json()
    saved = upload(subject, work, data, metadata(data)).json()
    source_ref = EntityRef.from_dict(saved["source_refs"][0])
    return work, saved, source_ref


def test_preview_then_explicit_deletion_leaves_a_tombstone_and_readable_records(tmp_path):
    with owner_app(tmp_path) as subject:
        work, saved, source_ref = stored_source(subject)
        base = f"{subject.path}/{work['work_id']}"
        preview = call(subject, work["work_id"], "deletions/preview", preview_body([source_ref.id]))
        assert preview.status_code == 200, preview.text
        view = preview.json()
        [item] = view["items"]
        assert item["name"] == "자료.pdf" and item["size"] == len(DATA) and item["state"] == "stored"
        assert item["revisions_naming_it"] == 1
        kinds = {ref["kind"] for ref in view["affected_refs"]}
        assert {"artifact", "source", "work_revision"} <= kinds
        assert "backups_made_before_this_deletion" in view["not_reached"]
        # a preview deletes nothing
        assert subject.client.get(base + f"/sources/{source_ref.id}/content",
                                  headers=headers(subject.profile)).content == DATA
        # consent is explicit and bound to the exact preview
        assert call(subject, work["work_id"], "deletions", confirm_body(view, confirmed=False)).status_code == 400
        assert call(subject, work["work_id"], "deletions",
                    confirm_body(view, preview_sha256="0" * 64)).status_code == 409
        assert call(subject, work["work_id"], "deletions",
                    confirm_body(view, reason_code="rights_request")).status_code == 409
        deleted = call(subject, work["work_id"], "deletions", confirm_body(view))
        assert deleted.status_code == 200, deleted.text
        result = deleted.json()
        assert result["deleted"] == [{"source_id": source_ref.id, "size": len(DATA), "sha256": item["sha256"],
                                      "bytes_removed": True, "readings": []}]
        # the bytes are gone from disk; every reader says deleted
        path = tmp_path / "data" / "domain-cas" / "operational" / item["sha256"]
        assert not path.exists()
        content = subject.client.get(base + f"/sources/{source_ref.id}/content", headers=headers(subject.profile))
        assert content.status_code == 410 and content.json()["code"] == "deleted"
        meta = subject.client.get(base + f"/sources/{source_ref.id}", headers=headers(subject.profile))
        assert meta.status_code == 200 and meta.json()["original_state"] == "deleted"
        # the records that named it stay and read back (the tombstone stands in for the bytes)
        assert subject.client.get(base, headers=headers(subject.profile)).json() == saved
        assert subject.domain.get(source_ref).ref == source_ref
        roots = subject.domain.roots()
        tombstone_id = erasure_identity(roots.genesis.id, "operational", item["sha256"])
        with subject.domain._connection() as db:
            row = db.execute("SELECT body FROM domain_records WHERE kind='decision_record' AND id=?",
                             (tombstone_id,)).fetchone()
        tombstone = json.loads(row[0])["content"]
        assert tombstone["former_kind"] == "original" and tombstone["reason_code"] == "user_requested"
        assert "자료.pdf" not in json.dumps(tombstone, ensure_ascii=False)  # no deleted content or name
        assert [kind for kind, _ in events(subject)][-1] == "retention.deleted"
        emitted = json.loads(events(subject)[-1][1])
        assert emitted["public_metadata"] == {"object_count": 1, "byte_count": len(DATA)}
        # exact replay is the same deletion; another request over deleted bytes conflicts
        again = call(subject, work["work_id"], "deletions", confirm_body(view))
        assert again.status_code == 200 and again.json()["deleted"][0]["bytes_removed"] is None
        assert call(subject, work["work_id"], "deletions/preview", preview_body([source_ref.id])).status_code == 409
        # the same bytes are not silently stored again under the old address
        with pytest.raises(ErasedBlob):
            subject.domain.put_blob(DATA, purpose="operational")


def test_the_scope_is_exact_and_changes_since_the_preview_conflict(tmp_path):
    with owner_app(tmp_path) as subject:
        work, _saved, source_ref = stored_source(subject)
        other_work, _other_saved, other_source = stored_source(subject)  # the same bytes, another work
        view = call(subject, work["work_id"], "deletions/preview", preview_body([source_ref.id])).json()
        [item] = view["items"]
        assert item["shared_with_other_sources"] == [other_source.id]  # one stored copy, stated
        # a source not listed by this work is not in its scope
        assert call(subject, work["work_id"], "deletions/preview",
                    preview_body([other_source.id])).status_code == 404
        # the work changes after the preview: the recomputed scope differs
        second = b"another original"
        upload(subject, {"work_id": work["work_id"]}, second, metadata(second, expected_revision=2))
        assert call(subject, work["work_id"], "deletions", confirm_body(view)).status_code == 409
        assert (tmp_path / "data" / "domain-cas" / "operational" / item["sha256"]).exists()
        fresh = call(subject, work["work_id"], "deletions/preview", preview_body([source_ref.id])).json()
        assert call(subject, work["work_id"], "deletions", confirm_body(fresh)).status_code == 200
        # the other work's source held the same bytes: it now reads deleted too, as the preview said
        content = subject.client.get(f"{subject.path}/{other_work['work_id']}/sources/{other_source.id}/content",
                                     headers=headers(subject.profile))
        assert content.status_code == 410


def test_the_deletion_wire_is_closed(tmp_path):
    with owner_app(tmp_path) as subject:
        work, _saved, source_ref = stored_source(subject)
        for bad in ({}, {**preview_body([source_ref.id]), "extra": 1}, preview_body([]),
                    preview_body([source_ref.id], reason="because"), preview_body(["not-a-uuid"]),
                    {**preview_body([source_ref.id]), "schema_version": "x"}):
            assert call(subject, work["work_id"], "deletions/preview", bad).status_code == 400, bad
        assert call(subject, work["work_id"], "deletions/other", preview_body([source_ref.id])).status_code in {400, 404}
        subject.client.cookies.clear()
        assert call(subject, work["work_id"], "deletions/preview",
                    preview_body([source_ref.id])).status_code in {401, 403}
