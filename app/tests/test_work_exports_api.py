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
