"""Owner-only HTTP lifecycle surface for durable service clients."""

import hashlib
import json
from itertools import cycle
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.api.service_clients import create_router
from app.domain.schemas import Actor
from app.services.service_clients import (
    PersistentServiceClientRegistry,
    ServiceClientDenied,
)
from app.storage import Store


def identifier():
    return str(uuid4())


def build(tmp_path, *, authenticated=True, random_bytes=None):
    store = Store(tmp_path)
    clock = [1_000]
    owner_request = object()
    owner = Actor(identifier(), "human", "local_session")
    random_bytes = random_bytes or (lambda size: next(cycle((b"a" * 32,))))
    verify_owner = lambda candidate: owner if candidate is owner_request else None
    registry = PersistentServiceClientRegistry(
        store,
        verify_owner=verify_owner,
        verify_recovery=lambda _candidate: False,
        clock=lambda: clock[0],
        random_bytes=random_bytes,
    )
    app = FastAPI()

    @app.middleware("http")
    async def bind_owner(request: Request, call_next):
        if authenticated:
            request.scope.setdefault("state", {})["authenticated_request"] = owner_request
        return await call_next(request)

    app.include_router(create_router(registry=registry, verify_owner=verify_owner))
    return TestClient(app), registry, store, clock, owner_request


def creation(client_id=None, **changes):
    value = {
        "client_id": client_id or identifier(),
        "name": "내 자동화",
        "scopes": ["command:work.revise", "events.read"],
        "allowed_network_profile": "portable_https",
        "expires_at": 2_000,
    }
    value.update(changes)
    return value


def test_create_returns_secret_once_while_reads_and_storage_never_do(tmp_path):
    values = iter((b"a" * 32,))
    client, _, store, _, _ = build(
        tmp_path, random_bytes=lambda size: next(values) if size == 32 else b"",
    )
    response = client.post("/api/v1/service-clients", json=creation())
    assert response.status_code == 201
    issued = response.json()
    assert issued["secret"].startswith("dt_sc_")
    assert issued["secret_available_once"] is True
    assert "credential_digest" not in json.dumps(issued)

    snapshot = client.get(
        f"/api/v1/service-clients/{issued['client']['client_id']}"
    )
    assert snapshot.status_code == 200
    assert snapshot.json() == issued["client"]
    assert issued["secret"] not in snapshot.text
    with store._connection() as db:
        serialized = json.dumps([
            dict(row) for row in db.execute("SELECT * FROM service_client_records")
        ])
        assert issued["secret"] not in serialized
        assert hashlib.sha256(issued["secret"].encode("ascii")).hexdigest() in serialized


def test_list_pagination_rotate_and_revoke_use_current_revisions(tmp_path):
    values = iter((b"a" * 32, b"b" * 32, b"c" * 32, b"d" * 32))
    client, registry, _, _, _ = build(
        tmp_path, random_bytes=lambda size: next(values) if size == 32 else b"",
    )
    created = [
        client.post("/api/v1/service-clients", json=creation()).json()
        for _ in range(3)
    ]
    expected_ids = sorted(value["client"]["client_id"] for value in created)

    first = client.get("/api/v1/service-clients?limit=2")
    assert first.status_code == 200
    assert [item["client_id"] for item in first.json()["items"]] == expected_ids[:2]
    cursor = first.json()["next_cursor"]
    second = client.get(f"/api/v1/service-clients?limit=2&cursor={cursor}")
    assert [item["client_id"] for item in second.json()["items"]] == expected_ids[2:]
    assert second.json()["next_cursor"] is None

    target = created[0]
    rotated = client.post(
        f"/api/v1/service-clients/{target['client']['client_id']}/rotate",
        json={"expected_revision": 1},
    )
    assert rotated.status_code == 200
    assert rotated.json()["client"]["revision"] == 2
    try:
        registry.authenticate(target["secret"], network_profile="portable_https")
    except ServiceClientDenied:
        pass
    else:  # pragma: no cover - security assertion
        raise AssertionError("predecessor credential remained active")

    revoked = client.post(
        f"/api/v1/service-clients/{target['client']['client_id']}/revoke",
        json={"expected_revision": 2},
    )
    assert revoked.status_code == 200
    assert revoked.json()["state"] == "revoked"
    assert revoked.json()["revision"] == 3


def test_strict_wire_and_query_rejection_precede_registry_and_entropy(tmp_path):
    random_calls = []
    client, _, store, _, _, = build(
        tmp_path,
        random_bytes=lambda size: random_calls.append(size) or b"a" * size,
    )
    invalid_bodies = (
        b'{"client_id":"a","client_id":"b"}',
        json.dumps(creation(extra=True)).encode(),
        json.dumps(creation(expires_at=True)).encode(),
        json.dumps(creation(expires_at=1.5)).encode(),
        b"\xef\xbb\xbf{}",
    )
    for body in invalid_bodies:
        response = client.post(
            "/api/v1/service-clients",
            content=body,
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
    assert random_calls == []
    with store._connection() as db:
        assert db.execute("SELECT COUNT(*) FROM service_client_records").fetchone()[0] == 0

    for query in ("limit=2&limit=3", "limit=0", "cursor=bad", "unknown=1"):
        assert client.get(f"/api/v1/service-clients?{query}").status_code == 400


def test_missing_browser_owner_is_uniformly_unauthenticated(tmp_path):
    client, _, _, _, _ = build(tmp_path, authenticated=False)
    for method, path, body in (
        ("get", "/api/v1/service-clients", None),
        ("post", "/api/v1/service-clients", creation()),
        ("get", f"/api/v1/service-clients/{identifier()}", None),
    ):
        response = getattr(client, method)(path, json=body) if body else getattr(client, method)(path)
        assert response.status_code == 401
        assert response.json()["code"] == "unauthenticated"
