"""Design requests created from the owner's confirmed work model, and restored after a
restart from stored, verified records only (T038; FR-005).

The lens decision is SIMULATED (the fixture evidence verifier of `actor_source`); the
generator and critic are TEST-ACTOR scripts. Production configures no design source: the
same command answers `not_designable` with the exact reason (no lens is qualified)."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.server import create_app
from app.services.claude_run_executor import ClaudeRunExecutor, LiveLimits
from app.services.design_requests import PRODUCTION_REASON, basis_id
from app.tests.design_arc_fixture import actor_source
from app.tests.test_claude_live_path import connected
from app.tests.test_design_arc import generate, read
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers
from app.tests.test_work_models import authored, confirm_body, draft_body, sourced_work, transport

ROOT = "api/v1/design-requests"


@contextmanager
def instance(tmp_path, arguments, profile, capability=None, *, answer=None):
    """One app over the same data directory; `capability` bootstraps, else the owner logs in."""

    _spy, mock = transport(answer or authored())
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=5), transport=mock)
    app = create_app(tmp_path / "data", **arguments, run_executor=executor)
    with TestClient(app, base_url=profile.http_origin) as client:
        if capability is not None:
            csrf = bootstrap_client(client, profile, capability)
        else:
            response = client.post(profile.base_path + "session/login", headers=headers(profile),
                                   json={"login_name": "owner", "password": "synthetic owner passphrase"})
            assert response.status_code == 200, response.text
            csrf = response.json()["csrf_token"]
        yield SimpleNamespace(app=app, client=client, profile=profile, csrf=csrf, domain=app.state.domain_store,
                              workspace=app.state.first_party_exports["design-workspace.service"])


def post(subject, path, body):
    return subject.client.post(subject.profile.base_path + path, json=body, headers=headers(subject.profile,
                                                                                          subject.csrf))


def listing(subject):
    response = subject.client.get(subject.profile.base_path + ROOT, headers=headers(subject.profile))
    assert response.status_code == 200, response.text
    return response.json()


def create(subject, work_model_id, command_id=None):
    return post(subject, ROOT, {"schema_version": "design-request-create-command-v1",
                                "command_id": command_id or str(uuid4()), "work_model_id": work_model_id})


def confirmed_work_model(subject, *, accept=True):
    if not hasattr(subject, "choice"):
        subject.choice = connected(subject)
    choice = subject.choice
    work, _sources = sourced_work(subject)
    drafted = post(subject, "api/v1/work-models", draft_body(work, choice))
    assert drafted.status_code == 200, drafted.text
    view = drafted.json()
    if accept:
        confirmed = post(subject, f"api/v1/work-models/{view['work_model_id']}/confirm",
                         confirm_body(view["work_model_ref"]))
        assert confirmed.status_code == 200 and confirmed.json()["state"] == "confirmed", confirmed.text
    return view["work_model_id"]


def test_production_states_exactly_why_no_design_request_can_be_created(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    with instance(tmp_path, arguments, profile, capability) as subject:
        listed = listing(subject)
        assert listed["creation"] == {"available": False, "reason": PRODUCTION_REASON, "source": None}
        assert listed["requests"] == [] and listed["unrestorable"] == []
        work_model_id = confirmed_work_model(subject)
        refused = create(subject, work_model_id)
        assert refused.status_code == 409, refused.text
        assert refused.json()["code"] == "not_designable" and refused.json()["reason"] == PRODUCTION_REASON
        assert "no lens is qualified" in PRODUCTION_REASON
        assert listing(subject)["requests"] == []


def test_a_request_is_created_only_from_an_accepted_work_model_and_a_qualified_lens(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    with instance(tmp_path, arguments, profile, capability) as subject:
        unaccepted = confirmed_work_model(subject, accept=False)
        subject.workspace.configure_design_source(actor_source())
        refused = create(subject, unaccepted)
        assert refused.status_code == 409 and refused.json()["reason"].startswith("the owner has not accepted")
        work_model_id = confirmed_work_model(subject)
        # the lens evidence names a qualification record the verifier does not trust
        subject.workspace.configure_design_source(actor_source(qualified=False))
        untrusted = create(subject, work_model_id)
        assert untrusted.status_code == 409
        assert untrusted.json()["reason"] == ("no qualified lens decision exists for this work model: "
                                              "L-P032-01 abstained (qualification_record_untrusted)")
        assert create(subject, str(uuid4())).json()["code"] == "not_designable"
        assert post(subject, ROOT, {"schema_version": "design-request-create-command-v1",
                                    "command_id": str(uuid4()), "work_model_id": "x"}).status_code == 400


def test_a_created_request_generates_and_is_restored_after_a_restart(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    command_id = str(uuid4())
    with instance(tmp_path, arguments, profile, capability) as subject:
        work_model_id = confirmed_work_model(subject)
        subject.workspace.configure_design_source(actor_source(scenario="three"))
        assert listing(subject)["creation"]["available"] is True
        created = create(subject, work_model_id, command_id)
        assert created.status_code == 201, created.text
        request_id = created.json()["request_id"]
        assert created.json()["requested_candidate_count"] == 3
        # an exact replay creates nothing new
        assert create(subject, work_model_id, command_id).json() == created.json()
        run = generate(subject, request_id)
        assert run.status_code == 201 and run.json()["outcome"] == "filled", run.text
        before = read(subject, request_id)
        assert before["pool"]["presented_count"] == 3
        assert subject.domain.get  # the basis is a stored record parented to the request
        with subject.domain._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_records WHERE id=?", (basis_id(request_id),)).fetchone()[0] == 1
    # restart: nothing is registered by host code; without a source the stored request is refused
    with instance(tmp_path, arguments, profile) as subject:
        listed = listing(subject)
        assert listed["requests"] == []
        assert listed["unrestorable"] == [{"request_id": request_id, "code": "not_restorable",
                                           "reason": listed["unrestorable"][0]["reason"]}]
        assert "cannot be rebuilt" in listed["unrestorable"][0]["reason"]
        refused = subject.client.get(subject.profile.base_path + f"{ROOT}/{request_id}", headers=headers(profile))
        assert refused.status_code == 409 and refused.json()["code"] == "not_restorable"
    # restart with a source whose verifier no longer trusts the qualification: refused
    with instance(tmp_path, arguments, profile) as subject:

        class Distrusting:
            def verify_route(self, route):
                return True

            def verify_assessment(self, assessment, route):
                return True

            def verify_qualification(self, qualification):
                return False

            def verify_composition_input(self, item, decision):
                return True

        subject.workspace.configure_design_source(actor_source(verifier=Distrusting()))
        reason = listing(subject)["unrestorable"][0]["reason"]
        assert reason == "the lens decision L-P032-01 is no longer qualified (abstained: qualification_record_untrusted)"
    # restart with the host's source: rebuilt from the stored records, the same pool, and it still works
    with instance(tmp_path, arguments, profile) as subject:
        subject.workspace.configure_design_source(actor_source(scenario="three"))
        listed = listing(subject)
        assert [item["request_id"] for item in listed["requests"]] == [request_id] and listed["unrestorable"] == []
        after = read(subject, request_id)
        assert after["pool"] == before["pool"] and after["candidates"] == before["candidates"]
        assert after["request"] == before["request"]
        chosen = after["pool"]["presented_candidate_ids"][0]
        derived = post(subject, f"{ROOT}/{request_id}/derivations", {
            "schema_version": "design-derivation-command-v1", "command_id": str(uuid4()), "action": "select",
            "parent_candidate_ids": [chosen], "instruction": None})
        assert derived.status_code == 201, derived.text
        reviewed = post(subject, f"{ROOT}/{request_id}/reviews", {
            "schema_version": "design-review-command-v1", "command_id": str(uuid4()),
            "derivation_id": derived.json()["derivation_id"]})
        assert reviewed.status_code == 201 and reviewed.json()["reviewed_candidate"]["verdict"]["status"] == "passed"
