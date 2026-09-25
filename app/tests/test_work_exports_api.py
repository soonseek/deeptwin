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
from contextlib import contextmanager
from hashlib import sha256
from types import SimpleNamespace
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
        assert reasons["alternatives"] == "not_recorded"  # collected, and this work has none
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


def test_frozen_alternatives_of_the_work_are_exported_as_scope_only(tmp_path):
    from app.domain.schemas import ImmutableRecord

    with owner_app(tmp_path) as subject:
        work = create(subject, text="대안이 있는 업무").json()
        other = create(subject, text="다른 업무").json()
        domain = subject.domain
        roots = domain.roots()
        def first_revision(work_id):
            with domain._connection() as db:
                row = db.execute("SELECT sha256 FROM domain_records WHERE kind='work_revision' AND id=? "
                                 "AND version=1", (work_id,)).fetchone()
            return {"kind": "work_revision", "id": work_id, "version": 1, "sha256": row["sha256"]}

        def alternative(boundary_id, text):
            record = ImmutableRecord.create(
                kind="own_alternative", id=str(uuid4()), version=1, created_at_utc="2026-09-23T00:00:00.000000Z",
                actor_ref=roots.actor, parent_refs=(), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content={"run_id": str(uuid4()), "original_artifact_id": str(uuid4()), "coverage": "partial",
                         "selectors": [{"kind": "text_span", "locator": {"start": 0, "end": 3}}],
                         "unreviewed_scope": "나머지", "secret_text": text,
                         "boundary_work_revision_ref": first_revision(boundary_id)})
            domain.put(record)
            return record

        mine = alternative(work["work_id"], "대안 본문 비밀")
        alternative(other["work_id"], "다른 업무의 대안")
        shown = preview(subject, work["work_id"], ["alternatives"]).json()
        [item] = shown["items"]
        assert item["relative_path"] == "alternatives/own-versions.json"
        assert item["content_mode"] == "metadata_only"
        receipt = confirm(subject, work["work_id"], shown)
        assert receipt.status_code == 201, receipt.text
        bundle = subject.client.get(f"{subject.path}/{work['work_id']}/exports/{receipt.json()['bundle_id']}",
                                    headers=headers(subject.profile))
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            [name] = [n for n in archive.namelist() if n.endswith("own-versions.json")]
            exported = json.loads(archive.read(name))
        assert [entry["alternative_id"] for entry in exported] == [mine.ref.id]
        assert exported[0]["coverage"] == "partial" and exported[0]["content"] == "내 버전 내용 미포함"
        assert "대안 본문 비밀" not in bundle.content.decode("latin-1")


def test_the_runs_of_the_work_are_exported_with_their_stops_consents_and_approvals(tmp_path):
    """Runs of this work only, through the real run, consent and approval routes: a gated
    run approved and completed, and a run whose execution failed; identities, times and
    closed codes only. A run recorded after the preview makes the consent stale."""
    from app.runtime import scheduler as sch
    from app.tests import test_runs_api as runs_api
    from app.tests.test_graph_contract import graph_value
    from app.tests.test_graph_execution import linear_graph
    from app.tests.test_works_api import CREATE

    class Failing(runs_api.Executor):
        failing = False

        def scheduler(self, compiled, **kwargs):
            if not self.failing:
                return super().scheduler(compiled, **kwargs)

            def explode(context, view):
                raise RuntimeError("synthetic handler failure")

            handlers = {key: explode for key in ("core.deterministic", "core.agent", "core.join",
                                                  "core.human_gate", "core.router")}
            return sch.build_scheduler(compiled, ledger=kwargs["ledger"], run_id=kwargs["run_id"],
                                       handlers=handlers, approvals=None)

    executor = Failing()
    with runs_api.owner_app(tmp_path, executor) as subject:
        works = subject.profile.base_path + "api/v1/works"
        work = runs_api.post(subject, {"schema_version": CREATE, "command_id": str(uuid4()),
                                       "text": "실행이 있는 업무"}, works).json()
        other = runs_api.post(subject, {"schema_version": CREATE, "command_id": str(uuid4()),
                                        "text": "다른 업무"}, works).json()

        def start(raw, work_ref):
            graph_ref = runs_api.graph_record(subject, raw)
            return runs_api.post(subject, runs_api.command(
                subject, graph_ref, work_revision_ref=work_ref,
                consent_ref=runs_api.consent_for(subject, graph_ref, work_ref=work_ref)))

        gated = start(graph_value(), work["ref"])
        assert gated.status_code == 201 and gated.json()["phase"] == "awaiting_human", gated.text
        run_path = gated.json()["links"]["self"]
        approved = runs_api.post(subject, {"command_id": str(uuid4()), "node_id": "owner-gate",
                                           "approval_scope": "release-output", "decision": "approved"},
                                 run_path + "/approvals")
        assert approved.status_code == 201, approved.text
        resumed = runs_api.post(subject, {"command_id": str(uuid4())}, run_path + "/resume")
        assert resumed.json()["phase"] == "completed", resumed.text
        executor.failing = True
        assert start(linear_graph(), work["ref"]).status_code == 503  # the execution failed
        executor.failing = False
        assert start(linear_graph(), other["ref"]).status_code == 201  # another work's run

        exports = SimpleNamespace(**{**vars(subject), "path": works})
        shown = preview(exports, work["work_id"], ["events"]).json()
        [runs_item] = [item for item in shown["items"] if item["relative_path"] == "events/runs.json"]
        assert runs_item["content_mode"] == "metadata_only"
        assert runs_item["label"] == "실행 2개 (실패 1개) · 실행 동의 2개 · 승인 결정 1개"
        receipt = confirm(exports, work["work_id"], shown)
        assert receipt.status_code == 201, receipt.text
        bundle = subject.client.get(f"{works}/{work['work_id']}/exports/{receipt.json()['bundle_id']}",
                                    headers=headers(subject.profile))
        with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
            exported = json.loads(archive.read("events/runs.json"))
        first, second = exported
        assert first["run_id"] == gated.json()["run_id"]
        assert set(first) == {"run_id", "started_at_utc", "work_revision", "stops", "consent", "approvals"}
        assert [stop["reason_code"] for stop in first["stops"]] == ["completed"]
        assert [(item["node_id"], item["decision"]) for item in first["approvals"]] == [("owner-gate", "approved")]
        assert [stop["reason_code"] for stop in second["stops"]] == ["infrastructure_failure"]
        assert second["approvals"] == [] and second["consent"]["revoked_at_utc"] is None
        assert "synthetic handler failure" not in bundle.content.decode("latin-1")

        # a run recorded after the preview: the consent no longer matches what the owner saw
        again = preview(exports, work["work_id"], ["events"]).json()
        assert start(linear_graph(), work["ref"]).status_code == 201
        stale = confirm(exports, work["work_id"], again)
        assert stale.status_code == 409 and stale.json()["code"] == "conflict"


# --- T074 gap: the secret scan over raw originals --------------------------------------

SECRET_KEY = "sk-ant-api03-SYNTHETIC-scan-canary-0123456789abcdefghij-AA"
SECRET_AWS = "aws_secret_access_key=SYNTHETIC-scan-wJalrXUtnFEMI-K7MDENG"


def _bundle(subject, work_id, receipt):
    response = subject.client.get(f"{subject.path}/{work_id}/exports/{receipt['bundle_id']}",
                                  headers=headers(subject.profile))
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        return response, {name: archive.read(name) for name in archive.namelist()}


def _preview_acked(subject, work_id, findings_sha, *, include_raw=True):
    return post(subject, {"schema_version": PREVIEW, "request_id": str(uuid4()), "categories": ["originals"],
                          "include_raw": include_raw, "acknowledged_findings_sha": findings_sha},
                f"{subject.path}/{work_id}/exports/preview")


def test_a_raw_original_with_a_secret_is_withheld_and_the_value_never_shown(tmp_path):
    with owner_app(tmp_path) as subject:
        text = f"분기 보고서\n키는 {SECRET_KEY} 이고\n  {SECRET_AWS}\n"
        work = create(subject, text=text).json()
        shown_response = preview(subject, work["work_id"], ["originals", "events"], include_raw=True)
        assert shown_response.status_code == 200, shown_response.text
        shown = shown_response.json()
        scan = shown["secret_scan"]
        assert [(f["relative_path"], f["kind"], f["line"], f["column"]) for f in scan["findings"]] == [
            ("originals/revision-1.txt", "anthropic_api_key", 2, 4),
            ("originals/revision-1.txt", "aws_secret_access_key", 3, 3)]
        assert scan["confirmed"] is False and len(scan["findings_sha"]) == 64
        [original] = [item for item in shown["items"] if item["category"] == "originals"]
        assert original["content_mode"] == "metadata_only"
        assert original["relative_path"] == "originals/revision-1.json"
        assert any(entry == {"category": "originals", "reason": "redacted",
                             "claim": "비밀로 보이는 값이 있어 작업 설명 원문 1개를 제외했다."}
                   for entry in shown["missing"])
        for value in (SECRET_KEY, SECRET_AWS, "SYNTHETIC-scan"):
            assert value not in shown_response.text
        # the unconfirmed export leaves the raw original out of the bundle
        done = confirm(subject, work["work_id"], shown)
        assert done.status_code == 201, done.text
        assert "SYNTHETIC-scan" not in done.text
        _, members = _bundle(subject, work["work_id"], done.json())
        assert set(members) == {"manifest.json", "originals/revision-1.json", "events/work-history.json"}
        assert all(b"SYNTHETIC-scan" not in data for data in members.values())
        manifest = json.loads(members["manifest.json"])
        assert {item["content_mode"] for item in manifest["items"]} == {"metadata_only"}


def test_only_the_exact_confirmed_finding_set_includes_the_raw_original(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject, text=f"설명\n{SECRET_KEY}\n").json()
        first = preview(subject, work["work_id"], ["originals"], include_raw=True).json()
        findings_sha = first["secret_scan"]["findings_sha"]
        # a confirmation that is not this finding set is refused; so is one without raw
        assert _preview_acked(subject, work["work_id"], "0" * 64).status_code == 409
        assert _preview_acked(subject, work["work_id"], findings_sha, include_raw=False).status_code == 400
        assert _preview_acked(subject, work["work_id"], "not-a-digest").status_code == 400
        # the preview without the confirmation cannot be exported as if it had one
        assert confirm(subject, work["work_id"], first, acknowledged_findings_sha=findings_sha).status_code == 409
        acked_response = _preview_acked(subject, work["work_id"], findings_sha)
        assert acked_response.status_code == 200, acked_response.text
        acked = acked_response.json()
        assert SECRET_KEY not in acked_response.text  # even confirmed, the preview never shows it
        assert acked["secret_scan"]["confirmed"] is True
        assert acked["secret_scan"]["findings_sha"] == findings_sha
        assert acked["items"][0]["content_mode"] == "raw"
        assert acked["preview_sha"] != first["preview_sha"]
        # the confirmation must be carried by the export itself, bound into the digest
        assert confirm(subject, work["work_id"], acked).status_code == 409
        done = confirm(subject, work["work_id"], acked, acknowledged_findings_sha=findings_sha)
        assert done.status_code == 201, done.text
        assert SECRET_KEY not in done.text
        _, members = _bundle(subject, work["work_id"], done.json())
        assert SECRET_KEY.encode() in members["originals/revision-1.txt"]
        assert SECRET_KEY.encode() not in members["manifest.json"]
        stored = subject.domain.get(EntityRef.from_dict(
            _manifest_record(subject, done.json()["bundle_id"]).body["content"]["bundle_artifact_ref"]))
        consent = subject.domain.get(EntityRef.from_dict(stored.body["parent_refs"][0]))
        assert consent.body["content"]["export_consent"]["confirmed_secret_findings_sha"] == findings_sha


def test_a_new_revision_changes_the_finding_set_and_the_old_confirmation_no_longer_holds(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject, text=f"설명 {SECRET_KEY}").json()
        findings_sha = preview(subject, work["work_id"], ["originals"], include_raw=True).json()[
            "secret_scan"]["findings_sha"]
        revised = post(subject, {"schema_version": REVISE, "command_id": str(uuid4()),
                                 "expected_revision": 1, "text": f"바뀐 설명 {SECRET_AWS}"},
                       f"{subject.path}/{work['work_id']}/revisions")
        assert revised.status_code == 201
        assert _preview_acked(subject, work["work_id"], findings_sha).status_code == 409


def test_the_instance_own_session_token_and_capability_are_recognised_by_digest(tmp_path):
    from base64 import urlsafe_b64encode

    with owner_app(tmp_path) as subject:
        capability = urlsafe_b64encode(b"S" * 32).rstrip(b"=").decode()  # the fixture's capability
        token = next(value for value in subject.client.cookies.values() if len(value) == 43)
        unrelated = "A" * 42 + "Q"
        work = create(subject, text=f"쿠키 {token}\n초대 {capability}\n무관 {unrelated}\n").json()
        response = preview(subject, work["work_id"], ["originals"], include_raw=True)
        assert response.status_code == 200, response.text
        kinds = [(f["kind"], f["line"]) for f in response.json()["secret_scan"]["findings"]]
        assert kinds == [("instance_session_token", 1), ("instance_bootstrap_capability", 2)]
        assert token not in response.text and capability not in response.text


def test_a_metadata_only_export_is_not_scanned_and_unchanged(tmp_path):
    with owner_app(tmp_path) as subject:
        work = create(subject, text=f"설명 {SECRET_KEY}").json()
        shown = preview(subject, work["work_id"], ["originals"]).json()
        assert shown["secret_scan"] is None
        assert shown["items"][0]["label"] == "작업 설명 1판 (원문 제외)"
        assert confirm(subject, work["work_id"], shown).status_code == 201


# --- T074: attached PDFs scanned through the document worker, redacted or excluded ------

PDF_SECRET = "aws_secret_access_key=SYNTHETIC-pdf-wJalrXUtnFEMI-K7MDENG"


def synthetic_pdf(*lines_per_page):
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    drawing = canvas.Canvas(buffer, pagesize=(612, 792))
    for lines in lines_per_page:
        drawing.setFont("Helvetica", 12)
        for index, line in enumerate(lines):
            drawing.drawString(72, 700 - 20 * index, line)
        drawing.showPage()
    drawing.save()
    return buffer.getvalue()


@contextmanager
def worker_app(tmp_path, *, worker=True):
    """The supported app with the isolated document worker (in-thread harness: the real
    service, frame codec and handshake) or without any worker."""
    from starlette.testclient import TestClient

    from app.server import create_app
    from app.tests.support.document_worker_harness import in_thread_client
    from app.tests.test_web_owner_integration import bootstrap_client, configured

    client_codec = in_thread_client()[0] if worker else None
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments, document_worker=client_codec)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        yield SimpleNamespace(app=app, client=client, profile=profile, csrf=csrf, codec=client_codec,
                              domain=app.state.domain_store, path=profile.base_path + "api/v1/works")


def attach(subject, work, data, *, name, media="application/pdf", expected):
    from app.tests.test_owner_material_intake import metadata, upload

    response = upload(subject, work, data, metadata(data, name=name, declared_media_type=media,
                                                    expected_revision=expected))
    assert response.status_code == 201, response.text
    return response.json()


def sources_preview(subject, work_id, **extra):
    return post(subject, {"schema_version": PREVIEW, "request_id": str(uuid4()), "categories": ["originals"],
                          "include_raw": True, "include_source_originals": True, **extra},
                f"{subject.path}/{work_id}/exports/preview")


def test_an_attached_pdf_with_a_secret_is_exported_only_as_a_verified_redacted_copy(tmp_path):
    clean = synthetic_pdf(["Synthetic clean page."])
    secret = synthetic_pdf(["First page, nothing here."], ["Second page holds", f"key {PDF_SECRET} inline."])
    with worker_app(tmp_path) as subject:
        work = create(subject, text="첨부 원본이 있는 합성 업무").json()
        attach(subject, work, clean, name="clean-CANARY-name.pdf", expected=1)
        attach(subject, work, secret, name="secret-CANARY-name.pdf", expected=2)
        attach(subject, work, b"%PDF-1.7\nnot really a pdf\n", name="damaged.pdf", expected=3)
        attach(subject, work, b"\x89PNG\r\n\x1a\n" + b"\0" * 32, name="image.png", media="image/png", expected=4)
        # attached originals are a raw inclusion: never without include_raw
        assert post(subject, {"schema_version": PREVIEW, "request_id": str(uuid4()), "categories": ["originals"],
                              "include_raw": False, "include_source_originals": True},
                    f"{subject.path}/{work['work_id']}/exports/preview").status_code == 400
        response = sources_preview(subject, work["work_id"])
        assert response.status_code == 200, response.text
        shown = response.json()
        assert shown["include_source_originals"] is True
        # the worker extracted page 2's text; the finding is shown by kind and location only
        assert [(f["relative_path"], f["page"], f["kind"], f["line"]) for f in shown["secret_scan"]["findings"]] == [
            ("originals/sources/source-2.pdf", 2, "aws_secret_access_key", 2)]
        assert PDF_SECRET.split("=")[1] not in response.text and "CANARY-name" not in response.text
        items = {item["relative_path"]: item for item in shown["items"]}
        assert items["originals/sources/source-1.pdf"]["content_mode"] == "raw"
        redacted = items["originals/sources/source-2.redacted.pdf"]
        assert redacted["content_mode"] == "redacted" and "원본과 같지 않음" in redacted["label"]
        assert "originals/sources/source-2.pdf" not in items
        assert not any("source-3" in path or "source-4" in path for path in items)
        claims = [(entry["reason"], entry["claim"]) for entry in shown["missing"] if entry["category"] == "originals"]
        assert ("redacted", ("첨부 PDF 2은 비밀 의심 값을 덮은 이미지 사본으로만 넣었다. 사본은 원본과 같지 않고 "
                            "텍스트 층·메타데이터·링크가 없다.")) in claims
        assert ("unavailable", "문서 격리 작업자가 첨부 PDF 3을 읽지 못해(content_rejected) 검사할 수 없어 넣지 않았다.") in claims
        assert ("unavailable", "첨부 원본 4은 비밀 검사를 할 수 없는 형식이라 넣지 않았다.") in claims
        # the preview is deterministic over the redacted bytes: the same request, the same digest
        again = sources_preview(subject, work["work_id"], request_id=shown["request_id"]).json()
        assert again["preview_sha"] == shown["preview_sha"]
        receipt = confirm(subject, work["work_id"], shown, include_source_originals=True)
        assert receipt.status_code == 201, receipt.text
        download, members = _bundle(subject, work["work_id"], receipt.json())
        assert members["originals/sources/source-1.pdf"] == clean
        copy = members["originals/sources/source-2.redacted.pdf"]
        assert copy.startswith(b"%PDF-") and copy != secret
        for value in (PDF_SECRET, PDF_SECRET.split("=")[1], "CANARY-name"):
            assert value.encode() not in download.content
        # re-extracted independently through the worker: the copy has no text layer at all
        extracted = subject.codec.extract_pdf_text(copy)
        assert extracted.page_count == 2 and extracted.pages == ("", "")
        manifest = json.loads(members["manifest.json"])
        assert manifest["redaction_summary"] == {"originals": 1}
        assert "가림 사본은 원본과 같지 않아 원본을 재현하지 않는다." in manifest["reproduction_limits"]
        modes = {item["relative_path"]: item["content_mode"] for item in manifest["items"]}
        assert modes["originals/sources/source-2.redacted.pdf"] == "redacted"
        # the owner confirms that exact finding set: the original PDF is exported as chosen
        digest = shown["secret_scan"]["findings_sha"]
        acked = sources_preview(subject, work["work_id"], acknowledged_findings_sha=digest).json()
        assert acked["secret_scan"]["confirmed"] is True
        assert {item["relative_path"]: item["content_mode"] for item in acked["items"]}[
            "originals/sources/source-2.pdf"] == "raw"
        done = confirm(subject, work["work_id"], acked, include_source_originals=True,
                       acknowledged_findings_sha=digest)
        assert done.status_code == 201, done.text
        assert _bundle(subject, work["work_id"], done.json())[1]["originals/sources/source-2.pdf"] == secret
        # a confirmation without the choice it previewed is a different preview: refused
        assert confirm(subject, work["work_id"], shown).status_code == 409


def test_the_export_never_parses_a_pdf_in_the_control_plane(tmp_path, monkeypatch):
    """With every PDF parser entry point of this process poisoned, the worker PROCESS
    (the unmodified service behind the harness's plain socket) still scans and redacts."""
    import secrets
    import subprocess
    import sys
    import tempfile
    from pathlib import Path

    from starlette.testclient import TestClient

    from app.server import create_app
    from app.tests.support.document_worker_harness import process_client
    from app.tests.test_web_owner_integration import bootstrap_client, configured

    data = synthetic_pdf(["page", f"key {PDF_SECRET}"])
    directory = Path(tempfile.mkdtemp(prefix="dt-t074-export-"))
    path = directory / "document.sock"
    secret = secrets.token_bytes(32)
    process = subprocess.Popen([sys.executable, "-B", "-m", "app.tests.support.document_worker_harness", str(path)],
                               cwd=Path(__file__).resolve().parents[2], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    process.stdin.write(secret.hex().encode() + b"\n")
    process.stdin.close()
    try:
        assert process.stdout.readline().strip() == b"ready"
        for name in ("pypdfium2", "pypdfium2_raw", "pypdf", "PIL", "PIL.Image", "reportlab"):
            monkeypatch.setitem(sys.modules, name, None)
        profile, capability, arguments = configured(tmp_path)
        app = create_app(tmp_path / "data", **arguments, document_worker=process_client(path, secret))
        with TestClient(app, base_url=profile.http_origin) as client:
            subject = SimpleNamespace(app=app, client=client, profile=profile,
                                      csrf=bootstrap_client(client, profile, capability),
                                      domain=app.state.domain_store, path=profile.base_path + "api/v1/works")
            work = create(subject, text="격리 확인 업무").json()
            attach(subject, work, data, name="secret.pdf", expected=1)
            shown = sources_preview(subject, work["work_id"]).json()
            assert [item["content_mode"] for item in shown["items"] if "sources" in item["relative_path"]] == [
                "redacted"]
            assert confirm(subject, work["work_id"], shown, include_source_originals=True).status_code == 201
    finally:
        process.kill()
        process.wait(5)
        path.unlink(missing_ok=True)
        directory.rmdir()


def test_without_a_document_worker_attached_pdfs_are_excluded_with_the_reason(tmp_path):
    with worker_app(tmp_path, worker=False) as subject:
        work = create(subject, text="작업자 없는 합성 업무").json()
        attach(subject, work, synthetic_pdf([f"key {PDF_SECRET}"]), name="secret.pdf", expected=1)
        shown = sources_preview(subject, work["work_id"]).json()
        assert not any(item["relative_path"].startswith("originals/sources/") for item in shown["items"])
        assert {"category": "originals", "reason": "unavailable",
                "claim": "문서 격리 작업자가 연결되지 않아 첨부 PDF 1의 내용을 검사할 수 없어 넣지 않았다."} in shown["missing"]
        assert shown["secret_scan"]["findings"] == []  # nothing was read, nothing is claimed clean or found


# --- T074: design candidates, recorded verdicts, derivations, approvals and lenses --------

def test_the_design_records_of_the_work_are_exported_as_recorded_with_their_lenses(tmp_path):
    from app.services.critic_qualification import critic_qualification_from_suite
    from app.tests.design_workspace_fixture import (
        CRITIC_ID,
        GENERATOR_ID,
        open_seeded_for_work,
    )
    from app.tests.test_environments import CRITIC_DIGEST, actor_record, actor_v3_design

    with actor_v3_design():
        # TEST-ACTOR qualification of the test-only V3-verifying design id; no real one exists
        qualified = critic_qualification_from_suite(actor_record(), CRITIC_DIGEST)
    with worker_app(tmp_path, worker=False) as subject:
        work = create(subject, text="설계가 있는 합성 업무").json()
        other = create(subject, text="설계가 없는 다른 업무").json()
        revised = attach(subject, work, synthetic_pdf(["source"]), name="source.pdf", expected=1)
        revision = EntityRef.from_dict(revised["ref"])
        sources = [EntityRef.from_dict(item) for item in revised["source_refs"]]
        request, roles = open_seeded_for_work(subject.app, revision, sources, criticism_turn=True,
                                              critic_qualification=qualified)
        design = subject.profile.base_path + "api/v1/design-requests/" + request.request_id
        derived = post(subject, {"schema_version": "design-derivation-command-v1", "command_id": str(uuid4()),
                                 "action": "select", "parent_candidate_ids": [roles["base"].candidate_id],
                                 "instruction": None}, design + "/derivations")
        assert derived.status_code == 201, derived.text
        edit = post(subject, {"schema_version": "design-derivation-command-v1", "command_id": str(uuid4()),
                              "action": "edit", "parent_candidate_ids": [roles["reshaped"].candidate_id],
                              "instruction": "소유자 지시 CANARY-instruction"}, design + "/derivations")
        assert edit.status_code == 201, edit.text
        reviewed = post(subject, {"schema_version": "design-review-command-v1", "command_id": str(uuid4()),
                                  "derivation_id": derived.json()["derivation_id"]}, design + "/reviews")
        assert reviewed.status_code == 201, reviewed.text
        chosen = reviewed.json()["reviewed_candidate"]["candidate_id"]
        prepared = post(subject, {"schema_version": "design-prepare-command-v1", "command_id": str(uuid4()),
                                  "candidate_id": chosen}, design + "/preparations")
        assert prepared.status_code == 201, prepared.text

        shown = preview(subject, work["work_id"], ["evaluation_evidence"]).json()
        items = {item["relative_path"]: item for item in shown["items"]}
        assert set(items) == {"evaluation/design-requests.json", "evaluation/lenses.json"}
        assert items["evaluation/design-requests.json"]["label"] == (
            f"설계 요청 1개 · 후보 5개 · 기록된 평가 5개(평가자 {CRITIC_ID}, 다시 검증하지 않음) · 파생 2개 · 설계 승인 1개")
        assert all(item["content_mode"] == "metadata_only" for item in shown["items"])
        [gap] = [entry for entry in shown["missing"] if entry["category"] == "evaluation_evidence"]
        assert gap["reason"] == "unavailable" and "완료 판정" in gap["claim"]
        receipt = confirm(subject, work["work_id"], shown)
        assert receipt.status_code == 201, receipt.text
        download, members = _bundle(subject, work["work_id"], receipt.json())
        exported = json.loads(members["evaluation/design-requests.json"])
        [value] = exported["requests"]
        assert value["request_id"] == request.request_id and value["work_revision"] == revision.version
        assert [call["generator_model_id"] for call in value["generation_calls"]] == [GENERATOR_ID, GENERATOR_ID]
        by_id = {item["candidate_id"]: item for item in value["candidates"]}
        rejected = by_id[roles["rejected"].candidate_id]["verdict"]
        assert rejected["basis"] == "recorded" and rejected["re_verified_by_export"] is False
        assert rejected["status"] == "rejected" and rejected["critic"]["model_ids"] == [CRITIC_ID]
        assert by_id[chosen]["derived_by"] == derived.json()["derivation_id"]
        assert by_id[chosen]["verdict"]["status"] == "passed"
        assert all(item["graph"]["content"] == "그래프 본문 미포함" for item in value["candidates"])
        actions = {item["action"]: item for item in value["derivations"]}
        assert actions["edit"]["instruction"] == "지시 내용 미포함" and actions["edit"]["re_review_required"] is True
        [approval] = value["design_approvals"]
        assert approval["candidate_id"] == chosen and approval["critic_qualification"]["status"] == "qualified"
        assert b"CANARY-instruction" not in download.content
        [lens] = json.loads(members["evaluation/lenses.json"])
        assert (lens["lens_id"], lens["version"], lens["definition_state"]) == ("L-P032-01", "draft-1", "current")
        assert lens["referenced_by"] == ["candidate_audit", "criticism_lens_use"]
        assert lens["review"]["adoption_status"] == "not_adopted" and lens["definition"]["neutral_name"]
        # another work of the vault: none of this is its export
        assert not preview(subject, other["work_id"], ["evaluation_evidence"]).json()["items"]


# --- T074: growth rounds, scoped by the environment the work's runs ran in --------------

def test_growth_rounds_are_exported_by_the_environment_scope_rule(tmp_path):
    from app.tests import growth_chain_fixture as chain
    from app.tests import test_runs_api as runs_api
    from app.tests.test_graph_execution import linear_graph
    from app.tests.test_works_api import CREATE

    with runs_api.owner_app(tmp_path, runs_api.Executor()) as subject:
        works = subject.profile.base_path + "api/v1/works"
        work = runs_api.post(subject, {"schema_version": CREATE, "command_id": str(uuid4()),
                                       "text": "비교가 있는 합성 업무"}, works).json()
        idle = runs_api.post(subject, {"schema_version": CREATE, "command_id": str(uuid4()),
                                       "text": "실행이 없는 업무"}, works).json()
        graph_ref = runs_api.graph_record(subject, linear_graph())
        started = runs_api.post(subject, runs_api.command(
            subject, graph_ref, work_revision_ref=work["ref"],
            consent_ref=runs_api.consent_for(subject, graph_ref, work_ref=work["ref"])))
        assert started.status_code == 201, started.text
        seeded = chain.seed_environment_rounds(subject.domain, tmp_path / "reset", subject.refs.environment)
        exports = SimpleNamespace(**{**vars(subject), "path": works})
        shown = preview(exports, work["work_id"], ["evaluation_evidence"]).json()
        [item] = shown["items"]
        assert item["relative_path"] == "evaluation/rounds.json"
        assert item["label"] == ("이 작업의 실행 환경에서 한 비교 2개 · 실험 1개 (판정·지표·항목 결과만, "
                                 "산출물 내용 제외 · 다른 환경의 비교 1개는 범위 밖)")
        receipt = confirm(exports, work["work_id"], shown)
        assert receipt.status_code == 201, receipt.text
        download, members = _bundle(exports, work["work_id"], receipt.json())
        value = json.loads(members["evaluation/rounds.json"])
        assert value["environments"] == [{"id": subject.refs.environment.id,
                                          "version": subject.refs.environment.version}]
        assert value["outside_scope_round_count"] == 1
        assert [item["round_id"] for item in value["rounds"]] == seeded["round_ids"]
        assert [item["validity"] for item in value["rounds"]] == seeded["validities"] == ["valid", "invalid"]
        assert value["rounds"][0]["utility"] == "0.8"
        assert all(item["item_outcomes"] is None and item["item_outcomes_state"] == "no_tool_effects"
                   for item in value["rounds"])
        assert value["rounds"][0]["outputs"][0]["node_results"] == "노드 결과 내용 미포함"
        [experiment] = value["experiments"]
        # the invalid round is completed but never counted as progress
        assert experiment["lineage_id"] == seeded["lineage_id"]
        assert experiment["completed_round_ids"] == seeded["round_ids"]
        assert experiment["non_improving_valid_count"] == 0
        assert b"quality=" not in download.content and "합성 업무" not in download.content.decode("latin-1")
        # a work none of whose runs used that environment carries no round
        assert not preview(exports, idle["work_id"], ["evaluation_evidence"]).json()["items"]


def test_a_round_item_outcome_keeps_its_boundaries_and_drops_everything_else():
    """The G-14 per-item outcome shape `paired_execution` records (see
    test_paired_tool_effects): only closed outcome, reasons and each effect's boundary
    identity survive into the export — never a tool's inputs or result."""
    from app.services.work_export_records import _item_outcomes

    effect = {"tool_id": "test_actor_notify", "version": "1.0.0", "effect_class": "external_send",
              "boundary": "replay", "inputs_digest": "a" * 64, "tool_call_sha256": "b" * 64,
              "output": "원 결과 내용", "run_id": "r"}
    exported = _item_outcomes([
        {"item_index": 0, "outcome": "compared", "reasons": [], "past_tool_effects": [],
         "baseline_effects": [], "candidate_effects": []},
        {"item_index": 1, "outcome": "not_comparable", "reasons": ["the replay boundary is not approved"],
         "past_tool_effects": [effect], "baseline_effects": [effect], "candidate_effects": [effect]}])
    assert exported[0]["outcome"] == "compared"
    assert exported[1]["reasons"] == ["the replay boundary is not approved"]
    assert exported[1]["past_tool_effects"] == [{key: effect[key] for key in (
        "tool_id", "version", "effect_class", "boundary", "tool_call_sha256", "inputs_digest")}]
    assert _item_outcomes(None) is None
