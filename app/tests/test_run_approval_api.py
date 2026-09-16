"""The owner's browser session records run approvals through a fixed
first-party route (T040 slice 3 wiring; api.md fixed contribution seam).

Same-origin POST with CSRF from a real bootstrapped owner records one
decision per (run, gate node, scope); reads resolve the durable record;
exact replay returns the same receipt; a conflicting decision is 409; the
unauthenticated, wrong-origin and oversized paths refuse before any write;
the record survives a cold application reopen.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers

RUN_ID = "00000000-0000-4000-8000-00000000a0a1"


def command(**changes):
    value = {"command_id": str(uuid4()), "node_id": "owner-gate",
             "approval_scope": "release-output", "decision": "approved"}
    value.update(changes)
    return value


@pytest.mark.parametrize("mode", ["local", "https"])
def test_owner_records_reads_replays_and_survives_reopen(tmp_path, mode):
    profile, capability, arguments = configured(tmp_path, mode)
    application = create_app(tmp_path / "data", **arguments)
    path = profile.base_path + f"api/v1/runs/{RUN_ID}/approvals"
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        body = command()
        response = client.post(path, headers=headers(profile, csrf), json=body)
        assert response.status_code == 201, response.text
        receipt = response.json()
        assert receipt["state"] == "recorded" and receipt["decision"] == "approved"
        assert receipt["approval_ref"]["kind"] == "action_approval"
        assert receipt["links"]["self"] == path + "/owner-gate/release-output"
        assert receipt["links"]["events"] == profile.base_path + "api/v1/events"
        read = client.get(receipt["links"]["self"], headers=headers(profile))
        assert read.status_code == 200, read.text
        saved = read.json()
        assert saved["run_id"] == RUN_ID and saved["node_id"] == "owner-gate"
        assert saved["decision"] == "approved" and saved["command_id"] == body["command_id"]
        assert saved["approval_ref"] == receipt["approval_ref"]
        assert saved["actor_ref"]["kind"] == "actor"
        assert client.head(receipt["links"]["self"], headers=headers(profile)).content == b""
        assert client.post(path, headers=headers(profile, csrf), json=body).json() == receipt
        conflict = client.post(path, headers=headers(profile, csrf),
                               json=dict(body, decision="rejected"))
        assert conflict.status_code == 409 and conflict.json()["code"] == "conflict"
        events = client.get(receipt["links"]["events"], headers=headers(profile)).json()["events"]
        assert sum(e["event_type"] == "approval.decided" for e in events) == 1
        missing = client.get(path + "/owner-gate/other-scope", headers=headers(profile))
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"
        cookies = dict(client.cookies)
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        client.cookies.update(cookies)
        read = client.get(path + "/owner-gate/release-output", headers=headers(profile))
        assert read.status_code == 200 and read.json()["decision"] == "approved"


@pytest.mark.parametrize("change,status,code", [
    ({"decision": "maybe"}, 400, "invalid_input"),
    ({"node_id": "../gate"}, 400, "invalid_input"),
    ({"command_id": "bad"}, 400, "invalid_input"),
    ({"extra": True}, 400, "invalid_input"),
])
def test_closed_payloads_refuse_before_any_write(tmp_path, change, status, code):
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    path = profile.base_path + f"api/v1/runs/{RUN_ID}/approvals"
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        response = client.post(path, headers=headers(profile, csrf), json=command(**change))
        assert response.status_code == status, response.text
        assert response.json()["code"] == code
        assert client.get(path + "/owner-gate/release-output", headers=headers(profile)).status_code == 404


def test_unauthenticated_wrong_origin_and_oversized_requests_refuse(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    path = profile.base_path + f"api/v1/runs/{RUN_ID}/approvals"
    with TestClient(application, base_url=profile.http_origin) as client:
        assert client.post(path, headers=headers(profile, "x"), json=command()).status_code == 401
        csrf = bootstrap_client(client, profile, capability)
        foreign = dict(headers(profile, csrf), Origin="https://evil.example")
        assert client.post(path, headers=foreign, json=command()).status_code == 403
        assert client.post(path, headers=dict(headers(profile, csrf), **{"X-DeepTwin-CSRF": "wrong"}),
                           json=command()).status_code in {401, 403}
        oversized = command(approval_scope="s" * 9000)
        assert client.post(path, headers=headers(profile, csrf), json=oversized).status_code == 413
        assert client.get(path + "/owner-gate/release-output", headers=headers(profile)).status_code == 404
        bad_run = profile.base_path + "api/v1/runs/not-a-uuid/approvals"
        assert client.post(bad_run, headers=headers(profile, csrf), json=command()).status_code == 400


def test_the_fixed_composition_includes_the_approval_routes(tmp_path):
    profile, _capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin):
        composition = application.state.route_composition
        assert "run-approvals-v1" in composition.contribution_ids
        assert ("runs.approvals.record", "runs.approvals.read") == tuple(
            route for route in composition.route_ids if route.startswith("runs.approvals.")
        )
