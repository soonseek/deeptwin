"""T073 server half: the owner exports one work — actual-content preview, consent
bound to that exact preview, a sealed bundle and an external receipt.

`POST …/works/{id}/exports/preview` reads what the export would contain now and
stores nothing; `POST …/works/{id}/exports` requires `confirmed: true` and the
preview's exact digest, and refuses (`conflict`) when the work changed after the
owner saw the preview; `GET …/works/{id}/exports/{bundle_id}` returns the owner's
bundle. Raw originals appear only by explicit selection; selected categories this
server does not collect are stated as `unavailable`, unselected ones as
`not_selected`. The manifest inside the bundle never carries the bundle's hash.
"""

import io
import json
import zipfile
from hashlib import sha256
from uuid import uuid4

from app.domain.refs import EntityRef
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import REVISE, create, owner_app, post

PREVIEW = "work-export-preview-v1"
CONFIRM = "work-export-confirm-v1"


def preview(subject, work_id, categories, *, include_raw=False, request_id=None):
    return post(subject, {"schema_version": PREVIEW, "request_id": request_id or str(uuid4()),
                          "categories": categories, "include_raw": include_raw},
                f"{subject.path}/{work_id}/exports/preview")


def confirm(subject, work_id, shown, **overrides):
    body = {"schema_version": CONFIRM, "request_id": shown["request_id"],
            "categories": shown["categories"], "include_raw": shown["include_raw"],
            "preview_sha": shown["preview_sha"], "confirmed": True}
    body.update(overrides)
    return post(subject, body, f"{subject.path}/{work_id}/exports")


def test_the_preview_shows_actual_content_and_states_every_gap(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject, text="비밀스러운 원문 설명").json()
        shown = preview(subject, work["work_id"], ["originals", "events", "alternatives"])
        assert shown.status_code == 200, shown.text
        value = shown.json()
        assert value["exportable"] is True
        items = {item["relative_path"]: item for item in value["items"]}
        assert set(items) == {"originals/revision-1.json", "events/work-history.json"}
        # without explicit raw inclusion the original text is not in the export
        assert items["originals/revision-1.json"]["content_mode"] == "metadata_only"
        reasons = {entry["category"]: entry["reason"] for entry in value["missing"]}
        assert reasons["alternatives"] == "unavailable"
        assert reasons["tool_observations"] == "not_selected"
        assert "비밀스러운" not in shown.text
        # previews store nothing: the same request previews the same digest
        again = preview(subject, work["work_id"], ["originals", "events", "alternatives"],
                        request_id=value["request_id"])
        assert again.json()["preview_sha"] == value["preview_sha"]
        raw = preview(subject, work["work_id"], ["originals"], include_raw=True).json()
        assert raw["items"][0]["content_mode"] == "raw"
        assert raw["items"][0]["relative_path"] == "originals/revision-1.txt"
        nothing = preview(subject, work["work_id"], ["tool_observations"]).json()
        assert nothing["exportable"] is False and nothing["items"] == []


def test_confirmation_binds_the_previewed_bytes_and_seals_a_receipted_bundle(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject, text="원문 설명입니다").json()
        shown = preview(subject, work["work_id"], ["originals", "events"], include_raw=True).json()
        implicit = confirm(subject, work["work_id"], shown, confirmed=False)
        assert implicit.status_code == 400
        wrong = confirm(subject, work["work_id"], shown, preview_sha="0" * 64)
        assert wrong.status_code == 409
        done = confirm(subject, work["work_id"], shown)
        assert done.status_code == 201, done.text
        receipt = done.json()
        assert receipt["item_count"] == 2
        assert confirm(subject, work["work_id"], shown).status_code == 409  # one bundle per request
        download = subject.client.get(
            f"{subject.path}/{work['work_id']}/exports/{receipt['bundle_id']}",
            headers=headers(subject.profile))
        assert download.status_code == 200, download.text
        assert download.headers["content-type"] == "application/zip"
        data = download.content
        assert sha256(data).hexdigest() == receipt["bundle_sha256"] == download.headers[
            "x-deeptwin-bundle-sha256"]
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = set(archive.namelist())
            assert names == {"manifest.json", "originals/revision-1.txt", "events/work-history.json"}
            assert archive.read("originals/revision-1.txt").decode() == "원문 설명입니다"
            manifest_bytes = archive.read("manifest.json")
            manifest = json.loads(manifest_bytes)
        # the manifest never carries the bundle's own hash; the receipt binds both
        assert receipt["bundle_sha256"] not in manifest_bytes.decode()
        assert {item["relative_path"] for item in manifest["items"]} == names - {"manifest.json"}
        assert {entry["reason"] for entry in manifest["missing_evidence"]} == {"not_selected"}
        # the owner's consent is a sealed record bound to the exact preview digest
        stored = subject.domain.get(EntityRef.from_dict(
            _manifest_record(subject, receipt["bundle_id"]).body["content"]["bundle_artifact_ref"]))
        consent = subject.domain.get(EntityRef.from_dict(stored.body["parent_refs"][0]))
        assert consent.body["content"]["export_consent"]["preview_sha"] == shown["preview_sha"]


def _manifest_record(subject, bundle_id):
    with subject.domain._connection() as db:
        row = db.execute("SELECT sha256 FROM domain_records WHERE kind='export_manifest' AND id=?",
                         (bundle_id,)).fetchone()
    return subject.domain.get(EntityRef("export_manifest", bundle_id, 1, row["sha256"]))


def test_a_work_changed_after_the_preview_refuses_the_stale_consent(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject).json()
        shown = preview(subject, work["work_id"], ["originals"], include_raw=True).json()
        revised = post(subject, {"schema_version": REVISE, "command_id": str(uuid4()),
                                 "expected_revision": 1, "text": "바뀐 설명"},
                       f"{subject.path}/{work['work_id']}/revisions")
        assert revised.status_code == 201
        stale = confirm(subject, work["work_id"], shown)
        assert stale.status_code == 409 and stale.json()["code"] == "conflict"


def test_the_export_wire_is_closed(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject).json()
        base = f"{subject.path}/{work['work_id']}/exports"
        for body in (
            {"schema_version": PREVIEW, "request_id": str(uuid4()), "categories": ["credentials"],
             "include_raw": False},
            {"schema_version": PREVIEW, "request_id": str(uuid4()), "categories": ["events"],
             "include_raw": True},  # raw inclusion is only about originals
            {"schema_version": PREVIEW, "request_id": "x", "categories": ["events"], "include_raw": False},
            {"schema_version": PREVIEW, "request_id": str(uuid4()), "categories": [], "include_raw": False},
            {"schema_version": PREVIEW, "request_id": str(uuid4()), "categories": ["events"],
             "include_raw": False, "hidden_reasoning": True},
        ):
            assert post(subject, body, base + "/preview").status_code == 400, body
        unknown = preview(subject, str(uuid4()), ["events"])
        assert unknown.status_code == 404
        missing = subject.client.get(f"{base}/{uuid4()}", headers=headers(subject.profile))
        assert missing.status_code == 404
        anonymous = subject.client.post(base + "/preview", json={
            "schema_version": PREVIEW, "request_id": str(uuid4()), "categories": ["events"],
            "include_raw": False})
        assert anonymous.status_code in {401, 403}
