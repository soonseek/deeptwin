"""Actual composed authenticated browser boundary for provider receipt commands."""

from uuid import uuid4
import pytest
from jsonschema import Draft202012Validator
from app.domain.refs import canonical_json
from app.deployment.provider_receipt_schema_exports import provider_receipt_api_schema
from app.tests.provider_receipt_fixture import (
    provider_receipt_context,
    signed_receipt,
    install_receipt,
    provider_worker,
)
from app.tests.test_web_owner_integration import headers


@pytest.mark.parametrize("portable", [False, True])
def test_authenticated_http_import_consume_read_and_frozen_replay(
    tmp_path, monkeypatch, portable
):
    with provider_receipt_context(
        tmp_path.resolve(), monkeypatch, portable=portable
    ) as actual:
        path = actual.profile.base_path + "api/v1/deployment/provider-requests"
        h = headers(actual.profile, actual.csrf)
        prepared = actual.client.post(path, headers=h, json=actual.payload)
        assert prepared.status_code == 201
        before = prepared.json()
        current = actual.client.get(
            before["links"]["self"], headers=headers(actual.profile)
        )
        digest = install_receipt(
            actual, signed_receipt(actual, current.json()["request"])
        )
        value = {
            "command_id": str(uuid4()),
            "request_digest": before["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        imported = actual.client.post(
            before["links"]["self"] + "/receipts", headers=h, json=value
        )
        assert imported.status_code == 200, imported.text
        assert imported.content == canonical_json(imported.json())
        validator = Draft202012Validator(provider_receipt_api_schema())
        assert validator.is_valid(imported.json())
        for field in imported.json():
            assert not validator.is_valid(
                {key: val for key, val in imported.json().items() if key != field}
            )
        assert not validator.is_valid({**imported.json(), "authority": True})
        consume = {**value, "command_id": str(uuid4()), "expected_revision": 2}
        with provider_worker(actual, monkeypatch):
            accepted = actual.client.post(
                imported.json()["links"]["consume"], headers=h, json=consume
            )
        assert accepted.status_code == 200, accepted.text
        assert validator.is_valid(accepted.json())
        actual.context.close()
        assert (
            actual.client.post(path, headers=h, json=actual.payload).content
            == prepared.content
        )
        assert (
            actual.client.post(
                before["links"]["self"] + "/receipts", headers=h, json=value
            ).content
            == imported.content
        )
        assert (
            actual.client.post(
                imported.json()["links"]["consume"], headers=h, json=consume
            ).content
            == accepted.content
        )
        current = actual.client.get(
            before["links"]["self"], headers=headers(actual.profile)
        )
        assert current.status_code == 200 and current.json()["state"] == "accepted"
        assert validator.is_valid(current.json())
        assert (
            actual.client.head(
                before["links"]["self"], headers=headers(actual.profile)
            ).content
            == b""
        )
        # A fresh composed application/owner/service reads the same persisted DB.
        # No worker remains and the original retained source has been closed.
        from fastapi.testclient import TestClient
        from app.server import create_app

        cookies = actual.client.cookies
        actual.client.__exit__(None, None, None)
        restarted = create_app(actual.data, **actual.arguments)
        with TestClient(restarted, base_url=actual.profile.http_origin) as client:
            client.cookies.update(cookies)
            assert restarted.state.domain_store is not actual.domain
            assert (
                client.post(path, headers=h, json=actual.payload).content
                == prepared.content
            )
            assert (
                client.post(
                    before["links"]["self"] + "/receipts", headers=h, json=value
                ).content
                == imported.content
            )
            assert (
                client.post(
                    imported.json()["links"]["consume"], headers=h, json=consume
                ).content
                == accepted.content
            )
            read = client.get(before["links"]["self"], headers=headers(actual.profile))
            assert read.status_code == 200 and read.json()["state"] == "accepted"


def test_new_endpoints_keep_closed_wire_auth_and_family_boundaries(
    tmp_path, monkeypatch
):
    with provider_receipt_context(
        tmp_path.resolve(), monkeypatch, slot_id=2, legacy_staged=True
    ) as actual:
        base = actual.profile.base_path + "api/v1/deployment/provider-requests/"
        h = headers(actual.profile, actual.csrf)
        value = {
            "command_id": str(uuid4()),
            "request_digest": actual.legacy_request["request_digest"],
            "receipt_digest": "A" * 43,
            "expected_revision": 1,
        }
        for suffix in ("receipts", "consume"):
            target = base + actual.legacy_request["request_id"] + "/" + suffix
            payload = {**value, "expected_revision": 1 if suffix == "receipts" else 2}
            assert (
                actual.client.post(target, headers=h, json=payload).status_code == 404
            )
            for data, status in (
                ({**payload, "expected_revision": True}, 400),
                ({**payload, "proof": {}}, 400),
                ({}, 400),
            ):
                assert (
                    actual.client.post(target, headers=h, json=data).status_code
                    == status
                )
            assert (
                actual.client.post(
                    target + "?unknown=1", headers=h, json=payload
                ).status_code
                == 400
            )
            assert (
                actual.client.post(
                    target, headers=headers(actual.profile), json=payload
                ).status_code
                == 403
            )
            assert (
                actual.client.post(
                    target,
                    headers={**h, "Origin": "https://invalid.example"},
                    json=payload,
                ).status_code
                == 403
            )
            assert (
                actual.client.post(
                    target, headers={**h, "content-type": "text/plain"}, content=b"{}"
                ).status_code
                == 400
            )
            assert (
                actual.client.post(
                    target,
                    headers={**h, "content-type": "application/json"},
                    content=b"x" * 4097,
                ).status_code
                == 413
            )
        actual.client.cookies.clear()
        assert (
            actual.client.post(
                base + str(uuid4()) + "/receipts", headers=h, json=value
            ).status_code
            == 401
        )


def test_pending_cancel_is_reachable_and_exact_ten_declarations(tmp_path, monkeypatch):
    import json
    from pathlib import Path

    root = Path(__file__).parents[2]
    route = "app/api/route_contributions/deployment-prepare-v1.json"
    private_copy = root / ".superpowers/sdd/resumption-plan/task-43-before" / route
    real_read_bytes = Path.read_bytes

    def portable_read(path):
        if path == private_copy:
            raise FileNotFoundError("private review evidence is not shipped")
        return real_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", portable_read)
    current = json.loads((root / route).read_bytes())
    assert current["routes"][:8] == [
        {
            "route_id": "deployment.requests.prepare",
            "methods": ["POST"],
            "path": "/api/v1/deployment/requests",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
        {
            "route_id": "deployment.requests.cancel",
            "methods": ["POST"],
            "path": "/api/v1/deployment/requests/{request_id}/cancel",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
        {
            "route_id": "deployment.requests.read",
            "methods": ["GET", "HEAD"],
            "path": "/api/v1/deployment/requests/{request_id}",
            "auth_policy": "browser_session",
            "required_scope": "deployment.read",
        },
        {
            "route_id": "deployment.requests.receipts.import",
            "methods": ["POST"],
            "path": "/api/v1/deployment/requests/{request_id}/receipts",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
        {
            "route_id": "deployment.requests.consume",
            "methods": ["POST"],
            "path": "/api/v1/deployment/requests/{request_id}/consume",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
        {
            "route_id": "deployment.provider-requests.prepare",
            "methods": ["POST"],
            "path": "/api/v1/deployment/provider-requests",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
        {
            "route_id": "deployment.provider-requests.cancel",
            "methods": ["POST"],
            "path": "/api/v1/deployment/provider-requests/{request_id}/cancel",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
        {
            "route_id": "deployment.provider-requests.read",
            "methods": ["GET", "HEAD"],
            "path": "/api/v1/deployment/provider-requests/{request_id}",
            "auth_policy": "browser_session",
            "required_scope": "deployment.read",
        },
    ]
    assert current["routes"][8:] == [
        {
            "route_id": "deployment.provider-requests.receipts",
            "methods": ["POST"],
            "path": "/api/v1/deployment/provider-requests/{request_id}/receipts",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
        {
            "route_id": "deployment.provider-requests.consume",
            "methods": ["POST"],
            "path": "/api/v1/deployment/provider-requests/{request_id}/consume",
            "auth_policy": "browser_session",
            "required_scope": "deployment.manage",
        },
    ]
    assert len(current["routes"]) == 10
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        base = actual.profile.base_path + "api/v1/deployment/provider-requests"
        h = headers(actual.profile, actual.csrf)
        prepared = actual.client.post(base, headers=h, json=actual.payload).json()
        request = actual.client.get(
            prepared["links"]["self"], headers=headers(actual.profile)
        ).json()["request"]
        digest = install_receipt(actual, signed_receipt(actual, request))
        value = {
            "command_id": str(uuid4()),
            "request_digest": prepared["request_digest"],
            "receipt_digest": digest,
            "expected_revision": 1,
        }
        imported = actual.client.post(
            prepared["links"]["self"] + "/receipts", headers=h, json=value
        )
        assert imported.status_code == 200
        cancel = {**value, "command_id": str(uuid4()), "expected_revision": 2}
        cancelled = actual.client.post(
            imported.json()["links"]["cancel"], headers=h, json=cancel
        )
        assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
        assert cancelled.content == canonical_json(cancelled.json())
        assert Draft202012Validator(provider_receipt_api_schema()).is_valid(
            cancelled.json()
        )
        actual.context.close()
        assert (
            actual.client.post(
                imported.json()["links"]["cancel"], headers=h, json=cancel
            ).content
            == cancelled.content
        )
