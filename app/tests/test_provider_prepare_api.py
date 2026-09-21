"""Reachable composed browser boundary backed by the real owner and publisher."""

from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from app.deployment.provider_prepare_api_schema_exports import (
    provider_prepare_api_schema,
)
from app.domain.refs import canonical_json
from app.tests.provider_prepare_fixture import provider_context
from app.tests.test_provider_publication import final_path
from app.tests.test_web_owner_integration import headers


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("kind,limit", [("receipt", 8192), ("read", 73728)])
def test_actual_response_formatters_enforce_canonical_byte_boundaries(
    tmp_path, monkeypatch, portable, kind, limit
):
    from copy import deepcopy
    from inspect import getclosurevars

    from app.api.provider_deployment_prepare import PATH, create_router
    from app.deployment import provider_prepare_lifecycle as lifecycle
    from app.deployment.prepare_contracts import DeploymentPrepareError

    def read_padding(size):
        # Eight bounded strings reach the aggregate runtime limit without
        # tripping the independent per-string domain codec limit first.
        quotient, remainder = divmod(size, 8)
        sizes = [quotient + (index < remainder) for index in range(8)]
        return ["é" * (count // 2) + "x" * (count % 2) for count in sizes]

    with provider_context(tmp_path.resolve(), monkeypatch, portable=portable) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        with actual.domain._connection() as db:
            item = actual.service._journal(db)["requests"][receipt["request_id"]]
        kwargs = (
            {}
            if kind == "read"
            else {"command_id": receipt["command_id"], "cursor": ""}
        )
        # Test-only oversized formatter inputs derived from verified actual
        # history. These are not claims that padded requests/cursors are legal.
        changed = deepcopy(item)
        if kind == "read":
            changed["request"]["padding"] = read_padding(0)
        base = lifecycle._body(changed, **kwargs)
        extra = limit - len(canonical_json(base))
        padding = "é" * (extra // 2) + "x" * (extra % 2)
        if kind == "read":
            changed["request"]["padding"] = read_padding(extra)
        else:
            kwargs["cursor"] = padding
            assert len(padding) <= 4096
        boundary = deepcopy(lifecycle._body(changed, **kwargs))
        assert len(canonical_json(boundary)) == limit
        if kind == "read":
            changed["request"]["padding"][0] += "x"
        else:
            kwargs["cursor"] += "x"
        with pytest.raises(DeploymentPrepareError) as caught:
            lifecycle._body(changed, **kwargs)
        assert caught.value.code == "unavailable"

        router = create_router(
            service=actual.service, base_path=actual.profile.base_path
        )
        selected = [route for route in router.routes if route.path == PATH and route.methods == {"POST"}]
        assert len(selected) == 1
        project = getclosurevars(selected[0].endpoint).nonlocals["response"]
        # Exercise the actual service-bound projection independently: a non-root
        # base path adds UTF-8 bytes to all three links after the service bound.
        projected = deepcopy(boundary)
        expansion = 3 * len(actual.profile.base_path.rstrip("/").encode())
        if expansion:
            reduced = extra - expansion
            reduced_padding = "é" * (reduced // 2) + "x" * (reduced % 2)
            if kind == "read":
                projected["request"]["padding"] = read_padding(reduced)
            else:
                projected["event_cursor"] = reduced_padding
        response = project(projected)
        assert len(response.body) == limit
        if kind == "read":
            projected["request"]["padding"][0] += "x"
        else:
            projected["event_cursor"] += "x"
        with pytest.raises(DeploymentPrepareError) as caught:
            project(projected)
        assert caught.value.code == "unavailable"


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("link", ["self", "cancel", "events"])
def test_rehashed_frozen_response_links_must_bind_actual_id_and_base_path(
    tmp_path, monkeypatch, portable, link
):
    import json
    import sqlite3

    from app.deployment import prepare_storage as storage

    with provider_context(tmp_path.resolve(), monkeypatch, portable=portable) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        with sqlite3.connect(actual.domain.path) as db:
            db.row_factory = sqlite3.Row
            row = dict(
                db.execute(
                    "SELECT * FROM deployment_prepare_commands WHERE command_id=?",
                    (actual.payload["command_id"],),
                ).fetchone()
            )
            frozen = json.loads(row["receipt_json"])
            assert receipt["request_id"] in frozen["links"]["self"]
            if link == "events":
                frozen["links"][link] = "/wrong-base/api/v1/events"
            else:
                frozen["links"][link] = frozen["links"][link].replace(
                    receipt["request_id"], str(uuid4())
                )
            row["receipt_json"] = storage.encoded(frozen)
            row["hash"] = storage.digest("commands", row)
            db.execute(
                "UPDATE deployment_prepare_commands SET receipt_json=?,hash=? WHERE command_id=?",
                (row["receipt_json"], row["hash"], row["command_id"]),
            )
        result = actual.client.get(
            actual.profile.base_path
            + "api/v1/deployment/provider-requests/"
            + receipt["request_id"],
            headers=headers(actual.profile),
        )
        assert result.status_code == 503
        assert str(frozen["links"][link]) not in result.text


@pytest.mark.parametrize("portable", [False, True])
def test_real_read_projection_refuses_base_path_different_from_actual_profile(
    tmp_path, monkeypatch, portable
):
    import asyncio

    from starlette.requests import Request

    from app.api.provider_deployment_prepare import PATH, create_router

    with provider_context(tmp_path.resolve(), monkeypatch, portable=portable) as actual:
        receipt = actual.service.prepare_provider(actual.request, actual.payload)
        router = create_router(service=actual.service, base_path="/wrong-base/")
        request = Request(
            {"type": "http", "state": {"authenticated_request": actual.read_request}}
        )
        selected = [route for route in router.routes if route.path == PATH + "/{request_id}" and route.methods == {"GET", "HEAD"}]
        assert len(selected) == 1
        response = asyncio.run(selected[0].endpoint(request, receipt["request_id"]))
        assert response.status_code == 503
        assert (
            actual.service.read_provider(actual.read_request, receipt["request_id"])[
                "request_id"
            ]
            == receipt["request_id"]
        )


@pytest.mark.parametrize("portable", [False, True])
def test_real_http_prepare_read_head_cancel_and_frozen_replay(
    tmp_path, monkeypatch, portable
):
    with provider_context(tmp_path, monkeypatch, portable=portable) as actual:
        validator = Draft202012Validator(provider_prepare_api_schema())
        path = actual.profile.base_path + "api/v1/deployment/provider-requests"
        response = actual.client.post(
            path, headers=headers(actual.profile, actual.csrf), json=actual.payload
        )
        assert response.status_code == 201, response.text
        receipt = response.json()
        assert validator.is_valid(receipt)
        assert receipt["links"]["self"] == path + "/" + receipt["request_id"]
        current = actual.client.get(
            receipt["links"]["self"], headers=headers(actual.profile)
        )
        assert current.status_code == 200
        assert validator.is_valid(current.json())
        assert final_path(
            actual.tree, "request", receipt["request_digest"]
        ).read_bytes() == canonical_json(current.json()["request"])
        assert (
            actual.client.head(
                receipt["links"]["self"], headers=headers(actual.profile)
            ).content
            == b""
        )
        actual.context.close()
        replay = actual.client.post(
            path, headers=headers(actual.profile, actual.csrf), json=actual.payload
        )
        assert replay.status_code == 201 and replay.content == response.content
        assert (
            actual.client.get(
                receipt["links"]["self"], headers=headers(actual.profile)
            ).status_code
            == 200
        )
        cancelled = actual.client.post(
            receipt["links"]["cancel"],
            headers=headers(actual.profile, actual.csrf),
            json={
                "command_id": str(uuid4()),
                "request_digest": receipt["request_digest"],
                "expected_revision": 1,
            },
        )
        assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
        assert validator.is_valid(cancelled.json())
        assert (
            actual.client.post(
                path, headers=headers(actual.profile, actual.csrf), json=actual.payload
            ).content
            == response.content
        )


def test_provider_boundary_closed_errors_for_wire_auth_origin_and_suffix_failures(
    tmp_path, monkeypatch
):
    with provider_context(tmp_path, monkeypatch) as actual:
        path = actual.profile.base_path + "api/v1/deployment/provider-requests"
        good_headers = headers(actual.profile, actual.csrf)
        validator = Draft202012Validator(provider_prepare_api_schema())
        cases = [
            (path + "?unknown=1", {"json": actual.payload}, good_headers, 400),
            (path, {"json": {**actual.payload, "slot_id": True}}, good_headers, 400),
            (path, {"json": {**actual.payload, "unknown": 1}}, good_headers, 400),
            (
                path,
                {"content": b"{}"},
                {**good_headers, "content-type": "text/plain"},
                400,
            ),
            (
                path,
                {"content": b"x" * 4097},
                {**good_headers, "content-type": "application/json"},
                413,
            ),
            (
                path,
                {"content": b'{"command_id":"a","command_id":"b"}'},
                {**good_headers, "content-type": "application/json"},
                400,
            ),
            (
                path,
                {"json": actual.payload},
                {**good_headers, "Origin": "https://elsewhere.invalid"},
                403,
            ),
            (path, {"json": actual.payload}, headers(actual.profile), 403),
            # Known receipt route still refuses a malformed selector.
            (path + "/" + str(uuid4()) + "/receipts", {"json": {}}, good_headers, 400),
            (path + "/" + str(uuid4()) + "/unknown", {"json": {}}, good_headers, 400),
            (path + "/malformed/cancel", {"json": {}}, good_headers, 400),
        ]
        for target, body, request_headers, status in cases:
            response = actual.client.post(target, headers=request_headers, **body)
            assert response.status_code == status, response.text
            assert validator.is_valid(response.json()), response.text
        response = actual.client.get(
            path + "/" + str(uuid4()), headers=headers(actual.profile)
        )
        assert response.status_code == 404 and validator.is_valid(response.json())
        response = actual.client.request(
            "GET",
            path + "/" + str(uuid4()),
            headers=headers(actual.profile),
            content=b"x",
        )
        assert response.status_code == 400 and validator.is_valid(response.json())
        actual.client.cookies.clear()
        response = actual.client.post(path, headers=good_headers, json=actual.payload)
        assert response.status_code == 401 and validator.is_valid(response.json())
