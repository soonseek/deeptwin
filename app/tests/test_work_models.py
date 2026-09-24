"""The owner's common-work target over the supported app (FR-003), against a mock transport.

A work model is drafted by one explicit model turn over the owner's Claude connection
from an exact work revision; the framework completes identities and source refs and
admits the draft strictly. The owner then accepts or rejects that exact draft. No real
network, key or paid call.
"""

import json
from uuid import uuid4

import httpx2

from app.domain.refs import EntityRef
from app.tests.test_claude_api import Spy, complete_text_stream, model, model_page, response
from app.tests.test_claude_design_turn import EFFORTS
from app.tests.test_claude_live_path import WORK_TEXT, connected, messages, real_work
from app.tests.test_owner_material_intake import metadata
from app.tests.test_runs_api import events, owner_app
from app.tests.test_web_owner_integration import headers
from app.tests.test_work_model_confirmation import work_model
from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits

AUTHORED = ("goals", "deliverables", "completion_conditions", "authorities", "risks", "unknowns")


def authored(**changes):
    raw = work_model()
    value = {key: raw[key] for key in AUTHORED}
    value["suitability"] = {key: raw["suitability"][key] for key in ("recommended_shape", "rationale")}
    value.update(changes)
    return json.dumps({"work_model": value}, ensure_ascii=False)


def transport(answer):
    def responder(request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model(capabilities=EFFORTS)]))
        return response(request, body=complete_text_stream(answer), headers={"content-type": "text/event-stream"})

    spy = Spy(responder)
    return spy, httpx2.MockTransport(spy)


def app_with(tmp_path, answer):
    spy, mock = transport(answer)
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5), transport=mock)
    return spy, owner_app(tmp_path, executor)


def post(subject, path, body):
    return subject.client.post(subject.profile.base_path + path.lstrip("/"), json=body,
                               headers=headers(subject.profile, subject.csrf))


def get(subject, path):
    return subject.client.get(subject.profile.base_path + path.lstrip("/"), headers=headers(subject.profile))


def sourced_work(subject):
    """A work with text and one retained original, as the intake produces it."""
    import base64
    base = subject.profile.base_path + "api/v1/works"
    created = subject.client.post(base, json={"schema_version": "work-create-command-v2",
                                              "command_id": str(uuid4()), "text": WORK_TEXT,
                                              "input_origin": "owner_material"},
                                  headers=headers(subject.profile, subject.csrf)).json()
    data = b"%PDF-1.7\nretained original\x00"
    meta = base64.urlsafe_b64encode(json.dumps(metadata(data), ensure_ascii=False,
                                               separators=(",", ":")).encode()).rstrip(b"=").decode()
    saved = subject.client.post(f"{base}/{created['work_id']}/sources", content=data,
                                headers={**headers(subject.profile, subject.csrf),
                                         "content-type": "application/octet-stream",
                                         "X-DeepTwin-Source-Metadata": meta})
    assert saved.status_code == 201, saved.text
    value = saved.json()
    with subject.domain._connection() as db:
        row = db.execute("SELECT sha256 FROM domain_records WHERE kind='work_revision' AND id=? AND version=?",
                         (value["work_id"], value["revision"])).fetchone()
    return EntityRef("work_revision", value["work_id"], value["revision"], row["sha256"]), value["source_refs"]


def draft_body(work_ref, choice, command_id=None):
    return {"schema_version": "work-model-draft-command-v1", "command_id": command_id or str(uuid4()),
            "work_id": work_ref.id, "revision": work_ref.version, "model_choice_ref": choice}


def confirm_body(work_model_ref, decision="accepted"):
    return {"schema_version": "work-model-confirm-command-v1", "command_id": str(uuid4()),
            "work_model_ref": work_model_ref, "decision": decision}


def test_a_drafted_work_model_is_framework_completed_replay_safe_and_owner_confirmed(tmp_path):
    spy, context = app_with(tmp_path, authored())
    with context as subject:
        choice = connected(subject)
        work, sources = sourced_work(subject)
        body = draft_body(work, choice)
        drafted = post(subject, "api/v1/work-models", body)
        assert drafted.status_code == 200, drafted.text
        view = drafted.json()
        assert view["state"] == "unconfirmed" and view["confirmation_ref"] is None
        stored = view["work_model"]
        # the framework, not the model, set every identity and source reference
        assert stored["work_revision_ref"] == work.as_dict() and stored["source_refs"] == sources
        assert stored["suitability"]["evidence_refs"] == sources
        assert stored["semantic_origin"] == "work_understanding" and stored["version"] == 1
        # the prompt carried the exact work text, and the call was the design boundary's
        [(_request, raw)] = messages(spy)
        assert "분기 보고서 초안" in json.dumps(json.loads(raw), ensure_ascii=False)
        # a replay returns the same draft and never calls again
        assert post(subject, "api/v1/work-models", body).json() == view
        assert len(messages(spy)) == 1
        read = get(subject, f"api/v1/work-models/{view['work_model_id']}")
        assert read.status_code == 200 and read.json() == view

        # the owner confirms only the exact draft they read
        stale = {**view["work_model_ref"], "sha256": "0" * 64}
        assert post(subject, f"api/v1/work-models/{view['work_model_id']}/confirm",
                    confirm_body(stale)).status_code == 409
        confirmed = post(subject, f"api/v1/work-models/{view['work_model_id']}/confirm",
                         confirm_body(view["work_model_ref"]))
        assert confirmed.status_code == 200, confirmed.text
        assert confirmed.json()["state"] == "confirmed" and confirmed.json()["confirmation_ref"]
        assert [item["public_metadata"] for item in events(subject, "approval.decided")][-1] == {"decision": "approved"}
        # one decision per draft: a contrary decision is a conflict, a repeat is idempotent
        assert post(subject, f"api/v1/work-models/{view['work_model_id']}/confirm",
                    confirm_body(view["work_model_ref"], "rejected")).status_code == 409
        assert post(subject, f"api/v1/work-models/{view['work_model_id']}/confirm",
                    confirm_body(view["work_model_ref"])).json()["state"] == "confirmed"
        # the issued confirmed target design generation will start from
        target = subject.client.app.state.first_party_exports["work-models.service"].confirmed_target(
            view["work_model_id"])
        assert target.state == "confirmed" and target.work_model_ref.as_dict() == view["work_model_ref"]
        assert target.confirmed_by is not None and target.design_disposition == "multi_agent"


def test_a_model_answer_outside_the_contract_is_refused_and_nothing_is_sealed(tmp_path):
    # the model tries to set an identity the framework owns
    _spy, context = app_with(tmp_path, json.dumps({"work_model": {"work_model_id": "x"}}))
    with context as subject:
        choice = connected(subject)
        refused = post(subject, "api/v1/work-models", draft_body(sourced_work(subject)[0], choice))
        assert refused.status_code == 422 and refused.json()["code"] == "model_output_invalid"
        with subject.domain._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind='work_model'").fetchone()[0] == 0


def test_without_a_key_no_draft_is_made_and_bodies_are_admitted_exactly(tmp_path):
    spy, context = app_with(tmp_path, authored())
    with context as subject:
        choice = connected(subject)
        # a text-only revision has no retained original to ground a work model
        text_only = post(subject, "api/v1/work-models", draft_body(real_work(subject), choice))
        assert text_only.status_code == 409 and text_only.json()["code"] == "sources_required"
        work, _sources = sourced_work(subject)
        assert post(subject, "api/v1/connections/claude/forget", {}).json()["key_present"] is False
        refused = post(subject, "api/v1/work-models", draft_body(work, choice))
        assert refused.status_code == 503 and refused.json()["code"] == "provider_unavailable"
        assert messages(spy) == []
        extra = {**draft_body(work, choice), "model_id": "anything"}
        assert post(subject, "api/v1/work-models", extra).status_code == 400
        assert get(subject, "api/v1/work-models/not-a-uuid").status_code == 400
        assert get(subject, f"api/v1/work-models/{uuid4()}").status_code == 404
        absent = {**draft_body(work, choice), "revision": 99}
        assert post(subject, "api/v1/work-models", absent).status_code == 404
