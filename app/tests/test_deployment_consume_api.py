"""Task 24 step (f): the owner-session consume route and the prepare-api-v3
read (contracts/deployment-receipt-journal-v3.md §6 by way of journal v2 §11).

`POST /api/v1/deployment/requests/{request_id}/consume` (route identity
`deployment.requests.consume`, browser session, `deployment.manage`) parses the
consume body through the same bounded preflight as the other deployment
commands, runs the service transaction against the actual in-process staged
worker and returns the frozen 200 body; GET/HEAD show the accepted3 head with
the installation summary and validate against the prepare-api-v3 artifact.
"""

from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from app.deployment import prepare_v3_schema_exports as v3_exports
from app.domain.refs import canonical_json
from app.tests import test_deployment_receipt_api as receipt_api
from app.tests.test_deployment_consume import StagedWorker, lineage_bundle
from app.tests.test_web_owner_integration import headers


@pytest.fixture
def lineage_candidate(monkeypatch):
    bundle = lineage_bundle()
    monkeypatch.setattr(receipt_api, "matching_bundle", lambda: bundle)
    return bundle


def consume_body(case):
    return {
        "command_id": str(uuid4()),
        "request_digest": case.current["request_digest"],
        "receipt_digest": case.command["receipt_digest"],
        "expected_revision": 2,
    }


def validator(schema):
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_owner_consume_route_commits_accepted3_and_reads_the_v3_head(
    tmp_path, monkeypatch, lineage_candidate
):
    with receipt_api.http_case(tmp_path, monkeypatch) as case:
        imported = case.client.post(
            case.import_path, json=case.command, headers=headers(case.profile, case.csrf)
        )
        assert imported.status_code == 200, imported.text
        worker = StagedWorker(case.physical, case.profile, monkeypatch)
        worker.start()
        consume_path = case.request_path + "/consume"
        body = consume_body(case)
        try:
            response = case.client.post(
                consume_path, json=body, headers=headers(case.profile, case.csrf)
            )
        finally:
            worker.stop()
        assert response.status_code == 200, response.text
        result = response.json()
        assert result == {
            "command_id": body["command_id"],
            "request_id": case.prepared.json()["request_id"],
            "receipt_digest": body["receipt_digest"],
            "outcome": "succeeded",
            "disposition": "consumed_success",
            "revision": 3,
            "installation": result["installation"],
            "event_cursor": result["event_cursor"],
        }
        assert response.content == canonical_json(result)  # frozen, unprefixed, no links
        assert validator(v3_exports.consume_receipt_schema()).is_valid(result)
        assert validator(v3_exports.api_schema()).is_valid(result)
        current = case.client.get(case.request_path, headers=headers(case.profile))
        head = case.client.head(case.request_path, headers=headers(case.profile))
        assert current.status_code == head.status_code == 200 and head.content == b""
        for name in (
            "content-type",
            "content-length",
            "cache-control",
            "content-security-policy",
            "x-content-type-options",
            "referrer-policy",
            "x-frame-options",
        ):
            assert head.headers[name] == current.headers[name]
        state = current.json()
        assert state["state"] == "accepted" and state["revision"] == 3
        assert state["receipt"]["disposition"] == "consumed_success"
        assert state["installation"] == result["installation"]
        assert state["consumption_publication_state"] is None
        assert state["links"]["self"] == case.request_path
        assert validator(v3_exports.read_schema()).is_valid(state), state
        # exact replay is the frozen body; a fresh consume of the accepted head is 409
        replay = case.client.post(
            consume_path, json=body, headers=headers(case.profile, case.csrf)
        )
        assert replay.status_code == 200 and replay.content == response.content
        again = case.client.post(
            consume_path, json=consume_body(case), headers=headers(case.profile, case.csrf)
        )
        assert again.status_code == 409, again.text
        assert again.json()["code"] == "conflict"
        composition = case.app.state.route_composition
        assert "deployment.requests.consume" in composition.route_ids


@pytest.mark.parametrize(
    "shape",
    ["query", "wrong_revision", "missing_receipt_digest", "extra_member", "get_method",
     "oversize", "not_json"],
)
def test_consume_preflight_denies_closed_shapes_before_the_service(
    tmp_path, monkeypatch, lineage_candidate, shape
):
    observed = []
    from app.deployment import stage_observer

    monkeypatch.setattr(
        stage_observer, "observe_stage_postcondition",
        lambda **kwargs: observed.append(kwargs) or (_ for _ in ()).throw(AssertionError()),
    )
    with receipt_api.http_case(tmp_path, monkeypatch) as case:
        imported = case.client.post(
            case.import_path, json=case.command, headers=headers(case.profile, case.csrf)
        )
        assert imported.status_code == 200, imported.text
        consume_path = case.request_path + "/consume"
        body = consume_body(case)
        common = {"headers": headers(case.profile, case.csrf)}
        if shape == "query":
            response = case.client.post(consume_path + "?x=1", json=body, **common)
        elif shape == "wrong_revision":
            response = case.client.post(consume_path, json={**body, "expected_revision": 1}, **common)
        elif shape == "missing_receipt_digest":
            response = case.client.post(
                consume_path, json={k: v for k, v in body.items() if k != "receipt_digest"}, **common
            )
        elif shape == "extra_member":
            response = case.client.post(consume_path, json={**body, "extra": 1}, **common)
        elif shape == "get_method":
            response = case.client.get(consume_path, headers=headers(case.profile))
        elif shape == "oversize":
            response = case.client.post(
                consume_path, json={**body, "command_id": "x" * 5000}, **common
            )
        else:
            response = case.client.post(
                consume_path, content=b"not json", headers={**common["headers"], "content-type": "application/json"}
            )
        # the preflight closes every wrong shape as 400 before routing, GET included,
        # exactly as it does for the receipts route; an oversize body is the
        # transport gate's 413, as for the receipts route
        expected = {"oversize": {413}}.get(shape, {400})
        assert response.status_code in expected, (shape, response.status_code, response.text)
        assert observed == []
        current = case.client.get(case.request_path, headers=headers(case.profile))
        assert current.json()["state"] == "receipt_pending"


def test_consume_of_an_unknown_request_is_not_found_only_after_auth(
    tmp_path, monkeypatch, lineage_candidate
):
    with receipt_api.http_case(tmp_path, monkeypatch) as case:
        path = case.path + "/" + str(uuid4()) + "/consume"
        body = consume_body(case)
        # genuinely unauthenticated: no session cookie, but the transport headers
        # present, so the authentication step itself is what refuses
        cookies = dict(case.client.cookies)
        case.client.cookies.clear()
        unauthenticated = case.client.post(
            path, json=body, headers=headers(case.profile, case.csrf)
        )
        assert unauthenticated.status_code == 401, unauthenticated.text
        assert unauthenticated.json()["code"] == "unauthenticated"
        for name, value in cookies.items():
            case.client.cookies.set(name, value)
        response = case.client.post(path, json=body, headers=headers(case.profile, case.csrf))
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"
