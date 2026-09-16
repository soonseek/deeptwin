"""Failure-first contract for masked API-key provider connections.

The fixtures in this module are deliberately local.  They never open macOS
Keychain, start Codex, instantiate a provider SDK, or make a network request.
Only ``InMemoryCredentialVault`` is injected into the product application.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.adapters.keychain import (
    CredentialAccessDenied,
    CredentialError,
    CredentialNeedsUnlock,
    CredentialNotFound,
    InMemoryCredentialVault,
)
from app.server import create_development_app as create_app
from app.services.provider_connections import (
    ProviderConnectionConflict,
    ProviderConnections,
    ProviderCredentialUnavailable,
)
from app.tests.local_http import LocalTestClient

ORIGIN = "http://127.0.0.1:4193"
FETCH = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
PUBLIC_FIELDS = {
    "connection_id",
    "provider",
    "mode",
    "auth_mode",
    "state",
    "key_present",
    "checked_at",
    "catalog_ref",
    "billing_state",
    "version",
    "cleanup_pending",
}
PRIVATE_FIELD_FRAGMENTS = (
    "key",
    "secret",
    "credential",
    "handle",
    "binding_ref",
    "hash",
)


class TrackingVault(InMemoryCredentialVault):
    """Observable test vault with fail-before-effect operation switches."""

    def __init__(self):
        super().__init__()
        self.calls = []
        self.fail_operation = None
        self.failure_canary = "vault-private-error-canary"

    def store(self, provider, secret):
        return super().store(provider, secret)

    def store_at(self, ref, secret):
        provider = ref.provider
        self.calls.append(("store", provider))
        if self.fail_operation == "store":
            raise CredentialError(self.failure_canary + " " + secret)
        return super().store_at(ref, secret)

    def rotate(self, ref, secret):
        self.calls.append(("rotate", ref.provider))
        if self.fail_operation == "rotate":
            raise CredentialError(
                self.failure_canary + " " + ref.identifier + " " + secret
            )
        return super().rotate(ref, secret)

    def open(self, ref):
        self.calls.append(("open", ref.provider))
        return super().open(ref)

    def delete(self, ref):
        self.calls.append(("delete", ref.provider))
        if self.fail_operation == "delete":
            raise CredentialError(self.failure_canary + " " + ref.identifier)
        return super().delete(ref)

    @property
    def refs(self):
        return tuple(self._items)

    def secret_for(self, ref):
        return bytes(self._items[ref]).decode("utf-8")


class QuietCodex:
    """A lifecycle-compatible boundary that must not be consulted here."""

    def __init__(self):
        self.calls = []

    def snapshot(self):
        self.calls.append("snapshot")
        raise AssertionError("credential mutation consulted Codex subscription state")

    def close(self):
        pass


class QuietCatalog:
    """Records every catalog/selection action without any provider transport."""

    def __init__(self):
        self.calls = []

    def snapshot(self, *args, **kwargs):
        self.calls.append(("snapshot", args, kwargs))
        raise AssertionError("credential mutation read a provider catalog")

    def refresh(self, *args, **kwargs):
        self.calls.append(("refresh", args, kwargs))
        raise AssertionError("credential mutation refreshed a provider catalog")

    def validate_choice(self, *args, **kwargs):
        self.calls.append(("validate", args, kwargs))
        raise AssertionError("credential mutation dispatched model selection")


def application(data_dir, vault):
    """Build the expected product wiring with only injected local test doubles."""

    catalog = QuietCatalog()
    runtime_dispatches = []

    def forbidden_runtime_dispatch(*args, **kwargs):
        runtime_dispatches.append((args, kwargs))
        raise AssertionError("credential mutation attempted runtime dispatch")

    app = create_app(
        data_dir,
        port=4193,
        understanding_provider_ready=False,
        codex_factory=lambda _store: QuietCodex(),
        model_catalog_factory=lambda _store, _codex: catalog,
        runtime_dispatch_resolver=forbidden_runtime_dispatch,
        credential_vault=vault,
    )
    return app, catalog, runtime_dispatches


def body(provider, secret, expected_version=0, *, suffix="one"):
    return {
        "expected_version": expected_version,
        "key": secret,
        "workspace_id": f"workspace-{suffix}" if provider == "claude" else None,
        "project_id": f"project-{suffix}" if provider == "codex" else None,
        "organization_id": f"organization-{suffix}" if provider == "codex" else None,
    }


def path(provider, mode="api"):
    return f"/api/v1/connections/{provider}/{mode}"


def auth(client):
    return {"X-CSRF-Token": client.csrf_token}


def assert_error(response, status, code):
    assert response.status_code == status, response.text
    value = response.json()
    assert set(value) == {
        "code",
        "message",
        "retryability",
        "affected_refs",
        "correlation_id",
    }
    assert value["code"] == code
    assert value["affected_refs"] == []
    return value


def assert_public_view(
    value, *, provider, state, version, cleanup_pending=False, key_present=None
):
    assert set(value) <= PUBLIC_FIELDS
    assert {"provider", "mode", "state", "key_present", "version"} <= set(value)
    assert value["provider"] == provider
    assert value["mode"] == "api"
    assert value["state"] == state
    expected_key = state == "configured" if key_present is None else key_present
    assert value["key_present"] is expected_key
    assert value["version"] == version
    assert value["cleanup_pending"] is cleanup_pending
    assert not any(
        fragment in name.casefold()
        for name in set(value) - {"key_present"}
        for fragment in PRIVATE_FIELD_FRAGMENTS
    )


def database_projection(app):
    """Render logical SQLite values, never the injected vault's private storage."""

    result = []
    with sqlite3.connect(app.state.store.path) as db:
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            result.append((table, db.execute(f"SELECT * FROM {quoted}").fetchall()))
    return repr(result)


@pytest.mark.parametrize(
    ("provider", "first_key", "second_key", "vault_provider"),
    (
        (
            "claude",
            "sk-ant-api03-provider-connection-first",
            "sk-ant-api03-provider-connection-second",
            "claude",
        ),
        (
            "codex",
            "sk-proj-provider-connection-first",
            "sk-proj-provider-connection-second",
            "codex_api",
        ),
    ),
)
def test_api_key_connection_create_rotate_delete_is_cas_versioned_and_durable(
    tmp_path, provider, first_key, second_key, vault_provider
):
    vault = TrackingVault()
    data_dir = tmp_path / provider
    app, catalog, runtime_dispatches = application(data_dir, vault)

    with LocalTestClient(app, base_url=ORIGIN) as client:
        endpoint = path(provider)
        empty = client.get(endpoint)
        assert empty.status_code == 200, empty.text
        assert_public_view(
            empty.json(), provider=provider, state="not_configured", version=0
        )

        created = client.put(endpoint, json=body(provider, first_key), headers=auth(client))
        assert created.status_code == 200, created.text
        assert_public_view(created.json(), provider=provider, state="configured", version=1)
        assert [call[0] for call in vault.calls] == ["store"]
        first_ref = vault.refs[0]
        assert first_ref.provider == vault_provider
        assert vault.secret_for(first_ref) == first_key

        stale = client.put(
            endpoint,
            json=body(provider, "stale-key-must-not-enter-vault", suffix="stale"),
            headers=auth(client),
        )
        assert_error(stale, 409, "stale_state")
        assert [call[0] for call in vault.calls] == ["store"]

        rotated = client.put(
            endpoint,
            json=body(provider, second_key, expected_version=1, suffix="two"),
            headers=auth(client),
        )
        assert rotated.status_code == 200, rotated.text
        assert_public_view(rotated.json(), provider=provider, state="configured", version=2)
        # Rotation is deliberately staged: create a new item, atomically move the
        # durable pointer, then retire the old item. Calling vault.rotate() would
        # destroy the old key before the SQLite commit can be known durable.
        assert [call[0] for call in vault.calls] == ["store", "store", "delete"]
        assert len(vault.refs) == 1
        second_ref = vault.refs[0]
        assert second_ref != first_ref
        assert vault.secret_for(second_ref) == second_key
        with (
            pytest.raises(CredentialNotFound),
            InMemoryCredentialVault.open(vault, first_ref),
        ):
            pass

        stale_delete = client.request(
            "DELETE", endpoint, json={"expected_version": 1}, headers=auth(client)
        )
        assert_error(stale_delete, 409, "stale_state")
        assert [call[0] for call in vault.calls] == ["store", "store", "delete"]

    reopened, reopened_catalog, reopened_dispatches = application(data_dir, vault)
    with LocalTestClient(reopened, base_url=ORIGIN) as client:
        endpoint = path(provider)
        restored = client.get(endpoint)
        assert restored.status_code == 200, restored.text
        assert_public_view(
            restored.json(), provider=provider, state="configured", version=2
        )
        assert not any(call[0] == "open" for call in vault.calls)

        deleted = client.request(
            "DELETE", endpoint, json={"expected_version": 2}, headers=auth(client)
        )
        assert deleted.status_code == 200, deleted.text
        assert_public_view(
            deleted.json(), provider=provider, state="not_configured", version=3
        )
        assert vault.refs == ()
        assert [call[0] for call in vault.calls] == [
            "store", "store", "delete", "delete"
        ]

    assert catalog.calls == reopened_catalog.calls == []
    assert runtime_dispatches == reopened_dispatches == []


def test_connection_get_is_side_effect_free_and_never_opens_the_vault(tmp_path):
    vault = TrackingVault()
    app, catalog, runtime_dispatches = application(tmp_path, vault)
    secret = "sk-ant-api03-read-boundary-canary"
    with LocalTestClient(app, base_url=ORIGIN) as client:
        endpoint = path("claude")
        response = client.put(
            endpoint, json=body("claude", secret), headers=auth(client)
        )
        assert response.status_code == 200, response.text
        credential_identifier = vault.refs[0].identifier
        vault.calls.clear()
        before_database = database_projection(app)
        before_events = json.dumps(app.state.store.events(), sort_keys=True)

        first = client.get(endpoint)
        second = client.get(endpoint)

        assert first.json() == second.json()
        assert_public_view(
            first.json(), provider="claude", state="configured", version=1
        )
        assert vault.calls == []
        assert database_projection(app) == before_database
        assert json.dumps(app.state.store.events(), sort_keys=True) == before_events
        exposed = "\n".join(
            (
                first.text,
                second.text,
                before_events,
                repr(app.state.provider_connections),
            )
        )
        assert secret not in exposed
        assert sha256(secret.encode()).hexdigest() not in exposed
        assert credential_identifier not in exposed
    assert catalog.calls == []
    assert runtime_dispatches == []


def test_default_model_catalog_is_rebound_without_refresh_or_secret_read(tmp_path):
    vault = TrackingVault()
    app = create_app(
        tmp_path,
        port=4193,
        understanding_provider_ready=False,
        codex_factory=lambda _store: QuietCodex(),
        credential_vault=vault,
    )
    with LocalTestClient(app, base_url=ORIGIN) as client:
        endpoint = path("claude")
        assert app.state.model_catalog.snapshot("claude", "api")["status"] \
            == "unavailable"
        created = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-catalog-binding"),
            headers=auth(client),
        )
        assert created.status_code == 200, created.text
        assert app.state.model_catalog.snapshot("claude", "api")["status"] \
            == "unqueried"
        assert not any(call[0] == "open" for call in vault.calls)

        removed = client.request(
            "DELETE", endpoint, json={"expected_version": 1}, headers=auth(client)
        )
        assert removed.status_code == 200, removed.text
        assert app.state.model_catalog.snapshot("claude", "api")["status"] \
            == "unavailable"
        assert not any(call[0] == "open" for call in vault.calls)


def test_raw_key_and_fingerprints_never_enter_sqlite_browser_events_or_errors(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    secret = "sk-proj-never-persist-or-render-this-value"
    digest = sha256(secret.encode()).hexdigest()
    with LocalTestClient(app, base_url=ORIGIN) as client:
        endpoint = path("codex")
        created = client.put(
            endpoint, json=body("codex", secret), headers=auth(client)
        )
        assert created.status_code == 200, created.text
        credential_identifier = vault.refs[0].identifier
        surfaces = [
            created.text,
            client.get(endpoint).text,
            client.get("/").text,
            json.dumps(app.state.store.events(), ensure_ascii=False),
            repr(app.state.provider_connections),
        ]
        for surface in surfaces:
            assert secret not in surface
            assert digest not in surface
            assert credential_identifier not in surface

        # The protected configuration may retain only its backend CredentialRef.
        # Raw key bytes and fingerprints never belong in SQLite, including WAL.
        assert secret not in database_projection(app)
        assert digest not in database_projection(app)
        for suffix in ("", "-wal", "-shm"):
            candidate = app.state.store.path.with_name(app.state.store.path.name + suffix)
            if candidate.exists():
                raw = candidate.read_bytes()
                assert secret.encode() not in raw
                assert digest.encode() not in raw

        vault.fail_operation = "store"
        failed = client.put(
            endpoint,
            json=body("codex", "replacement-error-key", 1, suffix="failed"),
            headers=auth(client),
        )
        assert_error(failed, 503, "dependency_unavailable")
        assert vault.failure_canary not in failed.text
        assert credential_identifier not in failed.text
        assert "replacement-error-key" not in failed.text
        restored = client.get(endpoint)
        assert_public_view(
            restored.json(), provider="codex", state="blocked", version=1,
            key_present=True,
        )
        assert vault.refs == (next(iter(vault._items)),)


def test_vault_failures_leave_connection_version_events_and_secret_state_unchanged(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        endpoint = path("claude")
        before_events = app.state.store.events()
        vault.fail_operation = "store"
        failed_create = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-failed-create"),
            headers=auth(client),
        )
        assert_error(failed_create, 503, "dependency_unavailable")
        assert vault.refs == ()

        assert app.state.store.events() == before_events
        assert_public_view(
            client.get(endpoint).json(),
            provider="claude",
            state="blocked",
            version=0,
        )

        vault.fail_operation = None
        created = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-kept-after-failure"),
            headers=auth(client),
        )
        assert created.status_code == 200
        ref = vault.refs[0]
        saved_events = app.state.store.events()

        vault.fail_operation = "store"
        failed_rotate = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-failed-rotate", 1, suffix="failed"),
            headers=auth(client),
        )
        assert_error(failed_rotate, 503, "dependency_unavailable")
        assert vault.refs == (ref,)
        assert vault.secret_for(ref) == "sk-ant-api03-kept-after-failure"
        assert app.state.store.events() == saved_events
        assert client.get(endpoint).json()["version"] == 1

        vault.fail_operation = "delete"
        pending_delete = client.request(
            "DELETE", endpoint, json={"expected_version": 1}, headers=auth(client)
        )
        assert pending_delete.status_code == 200, pending_delete.text
        assert_public_view(
            pending_delete.json(), provider="claude", state="not_configured",
            version=2, cleanup_pending=True,
        )
        assert vault.refs == (ref,)
        assert len(app.state.store.events()) == len(saved_events) + 1
        assert_public_view(
            client.get(endpoint).json(), provider="claude",
            state="not_configured", version=2, cleanup_pending=True,
        )

        # Cleanup is an explicit retry. GET never opens or deletes the vault.
        vault.fail_operation = None
        retried = client.request(
            "DELETE", endpoint, json={"expected_version": 2}, headers=auth(client)
        )
        assert retried.status_code == 200, retried.text
        assert_public_view(
            retried.json(), provider="claude", state="not_configured", version=2,
        )
        assert vault.refs == ()


@pytest.mark.parametrize(
    ("error_type", "code", "state"),
    (
        (CredentialNeedsUnlock, "credential_needs_unlock", "needs_unlock"),
        (CredentialAccessDenied, "credential_access_blocked", "blocked"),
    ),
)
def test_keychain_operational_state_is_specific_and_visible_without_secret_echo(
    tmp_path, error_type, code, state
):
    class StateVault(TrackingVault):
        def store_at(self, ref, secret):
            self.calls.append(("store", ref.provider))
            raise error_type("private-keychain-state-canary " + secret)

    vault = StateVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        secret = "sk-ant-api03-operational-state-secret"
        failed = client.put(
            path("claude"),
            json=body("claude", secret),
            headers=auth(client),
        )

        assert_error(failed, 503, code)
        assert secret not in failed.text
        assert "private-keychain-state-canary" not in failed.text
        assert_public_view(
            client.get(path("claude")).json(),
            provider="claude",
            state=state,
            version=0,
        )


def test_credential_error_override_expires_after_another_service_commits_new_version(
    tmp_path,
):
    class ToggleVault(TrackingVault):
        locked = True

        def store_at(self, ref, secret):
            self.calls.append(("store", ref.provider))
            if self.locked:
                raise CredentialNeedsUnlock("private-vault-state " + secret)
            return super().store_at(ref, secret)

    vault = ToggleVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN):
        first = ProviderConnections(app.state.store, credential_vault=vault)
        second = ProviderConnections(app.state.store, credential_vault=vault)

        with pytest.raises(CredentialNeedsUnlock):
            first.configure(
                "claude",
                "api",
                0,
                "sk-ant-api03-first-observation",
                workspace_id="workspace-one",
                project_id=None,
                organization_id=None,
            )
        assert first.get("claude", "api")["state"] == "needs_unlock"

        vault.locked = False
        committed = second.configure(
            "claude",
            "api",
            0,
            "sk-ant-api03-second-service",
            workspace_id="workspace-two",
            project_id=None,
            organization_id=None,
        )
        assert committed["state"] == "configured"
        assert committed["version"] == 1

        refreshed = first.get("claude", "api")
        assert refreshed["state"] == "configured"
        assert refreshed["version"] == 1
        assert refreshed["key_present"] is True


def test_database_insert_failure_cleans_up_the_new_vault_item_and_rolls_back(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    secret = "sk-ant-api03-db-rollback-canary"
    with LocalTestClient(app, base_url=ORIGIN) as client:
        with app.state.store._connection() as db:
            assert db.execute(
                "SELECT 1 FROM sqlite_master "
                "WHERE type='table' AND name='provider_connections'"
            ).fetchone() is not None
            db.execute(
                "CREATE TRIGGER fail_provider_connection_insert "
                "BEFORE INSERT ON provider_connections BEGIN "
                "SELECT RAISE(ABORT, 'private-db-failure-canary'); END"
            )
        before_events = app.state.store.events()

        failed = client.put(
            path("claude"), json=body("claude", secret), headers=auth(client)
        )

        assert_error(failed, 503, "storage_failed")
        assert "private-db-failure-canary" not in failed.text
        assert secret not in failed.text
        assert vault.refs == ()
        assert [call[0] for call in vault.calls] == ["store", "delete"]
        assert app.state.store.events() == before_events
        assert_public_view(
            client.get(path("claude")).json(),
            provider="claude",
            state="not_configured",
            version=0,
        )


def test_rotation_database_failure_keeps_old_key_and_pointer_current(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    endpoint = path("claude")
    with LocalTestClient(app, base_url=ORIGIN) as client:
        created = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-still-current"),
            headers=auth(client),
        )
        assert created.status_code == 200, created.text
        old_ref = vault.refs[0]
        events = app.state.store.events()
        with app.state.store._connection() as db:
            db.execute(
                "CREATE TRIGGER fail_provider_connection_rotation "
                "BEFORE INSERT ON provider_connections BEGIN "
                "SELECT RAISE(ABORT, 'private-rotation-db-canary'); END"
            )

        failed = client.put(
            endpoint,
            json=body(
                "claude", "sk-ant-api03-must-be-compensated", 1, suffix="new"
            ),
            headers=auth(client),
        )

        assert_error(failed, 503, "storage_failed")
        assert vault.refs == (old_ref,)
        assert vault.secret_for(old_ref) == "sk-ant-api03-still-current"
        assert [call[0] for call in vault.calls] == ["store", "store", "delete"]
        assert app.state.store.events() == events
        assert_public_view(
            client.get(endpoint).json(),
            provider="claude",
            state="configured",
            version=1,
        )


def test_exact_json_query_csrf_and_session_boundaries_fail_before_vault_access(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    endpoint = path("claude")
    secret = "sk-ant-api03-request-boundary-canary"

    with TestClient(app, base_url=ORIGIN, raise_server_exceptions=False) as raw:
        unauthenticated = raw.put(
            endpoint,
            json=body("claude", secret),
            headers=FETCH,
        )
        assert_error(unauthenticated, 401, "unauthenticated")
        assert secret not in unauthenticated.text

    with LocalTestClient(app, base_url=ORIGIN) as client:
        valid = body("claude", secret)
        invalid_requests = [
            client.put(endpoint, json=valid),
            client.put(endpoint + "?unexpected=1", json=valid, headers=auth(client)),
            client.get(endpoint + "?unexpected=1"),
            client.put(
                endpoint,
                json={**valid, "unexpected": True},
                headers=auth(client),
            ),
            client.put(
                endpoint,
                json={key: value for key, value in valid.items() if key != "project_id"},
                headers=auth(client),
            ),
            client.put(
                endpoint,
                json={**valid, "expected_version": True},
                headers=auth(client),
            ),
            client.put(
                endpoint,
                content=(
                    '{"expected_version":0,"expected_version":0,'
                    f'"key":"{secret}","workspace_id":null,'
                    '"project_id":null,"organization_id":null}'
                ),
                headers={**auth(client), "content-type": "application/json"},
            ),
            client.put(
                endpoint,
                content=json.dumps(valid),
                headers={**auth(client), "content-type": "text/plain"},
            ),
            client.request(
                "DELETE",
                endpoint,
                json={"expected_version": 0, "key": secret},
                headers=auth(client),
            ),
            client.put(
                endpoint,
                json=valid,
                headers={**auth(client), "Origin": "https://evil.example"},
            ),
        ]
        for response in invalid_requests:
            assert_error(response, 400 if response is not invalid_requests[0]
                         and response is not invalid_requests[-1] else 403,
                         "invalid_input" if response is not invalid_requests[0]
                         and response is not invalid_requests[-1] else "access_denied")
            assert secret not in response.text

        raw_duplicate_delete = client.request(
            "DELETE",
            endpoint,
            content='{"expected_version":0,"expected_version":0}',
            headers={**auth(client), "content-type": "application/json"},
        )
        assert_error(raw_duplicate_delete, 400, "invalid_input")
        assert vault.calls == []
        assert_public_view(
            client.get(endpoint).json(),
            provider="claude",
            state="not_configured",
            version=0,
        )


@pytest.mark.parametrize(
    "endpoint",
    (
        "/api/v1/connections/claude/subscription",
        "/api/v1/connections/codex/subscription",
        "/api/v1/connections/unknown/api",
        "/api/v1/connections/claude/unknown",
    ),
)
def test_wrong_provider_or_cross_mode_connection_is_rejected_without_vault_use(
    tmp_path, endpoint
):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        response = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-cross-mode-canary"),
            headers=auth(client),
        )
        expected = (404, "not_found") if "/unknown/api" in endpoint else (
            400,
            "invalid_input",
        )
        assert_error(response, *expected)
        assert vault.calls == []


def test_tampered_connection_integrity_row_fails_closed_without_opening_secret(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        endpoint = path("claude")
        created = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-tamper-canary"),
            headers=auth(client),
        )
        assert created.status_code == 200, created.text
        with app.state.store._connection() as db:
            columns = {
                row[1]: row[2].casefold()
                for row in db.execute("PRAGMA table_info(provider_connections)")
            }
            integrity_column = next(
                (
                    name
                    for name in (
                        "record_hash",
                        "payload_hash",
                        "connection_hash",
                        "binding_hash",
                    )
                    if name in columns
                ),
                None,
            )
            assert integrity_column is not None, (
                "provider_connections needs an authenticated canonical-row digest"
            )
            replacement = (
                b"0" * 32 if "blob" in columns[integrity_column] else "0" * 64
            )
            quoted = '"' + integrity_column.replace('"', '""') + '"'
            db.execute(
                f"UPDATE provider_connections SET {quoted}=? "
                "WHERE provider='claude' AND mode='api'",
                (replacement,),
            )
        vault.calls.clear()

        failed = client.get(endpoint)

        assert_error(failed, 503, "storage_failed")
        assert vault.calls == []
        assert "tamper" not in failed.text.casefold()


@pytest.mark.parametrize(
    "mutation",
    (
        "DELETE FROM provider_connections WHERE provider='claude' AND mode='api'",
        (
            "UPDATE provider_connection_heads SET version=0 "
            "WHERE provider='claude' AND mode='api'"
        ),
    ),
)
def test_deleted_or_rolled_back_connection_head_never_revives_old_state(
    tmp_path, mutation
):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        endpoint = path("claude")
        assert client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-head-integrity"),
            headers=auth(client),
        ).status_code == 200
        with app.state.store._connection() as db:
            db.execute(mutation)
        vault.calls.clear()

        failed = client.get(endpoint)

        assert_error(failed, 503, "storage_failed")
        assert vault.calls == []


def test_after_insert_tamper_rolls_back_database_and_staged_secret(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        with app.state.store._connection() as db:
            db.execute(
                "CREATE TRIGGER alter_provider_connection_after_insert "
                "AFTER INSERT ON provider_connections BEGIN "
                "UPDATE provider_connections SET state='not_configured' "
                "WHERE provider=NEW.provider AND mode=NEW.mode "
                "AND version=NEW.version; END"
            )
        before = app.state.store.events()

        failed = client.put(
            path("claude"),
            json=body("claude", "sk-ant-api03-trigger-tamper"),
            headers=auth(client),
        )

        assert_error(failed, 503, "storage_failed")
        assert vault.refs == ()
        assert [call[0] for call in vault.calls] == ["store", "delete"]
        assert app.state.store.events() == before


def test_forged_cleanup_row_cannot_delete_another_connections_current_key(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        created = client.put(
            path("codex"),
            json=body("codex", "sk-proj-cleanup-scope-canary"),
            headers=auth(client),
        )
        assert created.status_code == 200, created.text
        current_ref = vault.refs[0]
        forged = {
            "schema_version": 1,
            "provider": "claude",
            "mode": "api",
            "credential_provider": current_ref.provider,
            "credential_identifier": current_ref.identifier,
            "retired_at_version": 2,
            "state": "pending",
        }
        digest = sha256(
            json.dumps(
                forged,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        with app.state.store._connection() as db:
            db.execute(
                "INSERT INTO provider_credential_cleanup VALUES (?,?,?,?,?,?,?)",
                (
                    "claude",
                    "api",
                    current_ref.provider,
                    current_ref.identifier,
                    2,
                    "pending",
                    digest,
                ),
            )
        vault.calls.clear()

        failed = client.request(
            "DELETE",
            path("claude"),
            json={"expected_version": 0},
            headers=auth(client),
        )

        assert_error(failed, 503, "storage_failed")
        assert vault.calls == []
        assert vault.refs == (current_ref,)
        codex = client.get(path("codex"))
        assert codex.status_code == 200
        assert_public_view(
            codex.json(), provider="codex", state="configured", version=1
        )


def test_reentered_app_routes_mutate_the_lifespan_current_catalog(tmp_path):
    vault = TrackingVault()
    catalogs = []

    class ReentryCatalog(QuietCatalog):
        def __init__(self):
            super().__init__()
            self.sources = {}

        def replace_api_source(self, provider, mode, source):
            self.calls.append(("replace", provider, mode, source is not None))
            if source is None:
                self.sources.pop((provider, mode), None)
            else:
                self.sources[(provider, mode)] = source

    def catalog_factory(_store, _codex):
        result = ReentryCatalog()
        catalogs.append(result)
        return result

    app = create_app(
        tmp_path,
        port=4193,
        understanding_provider_ready=False,
        codex_factory=lambda _store: QuietCodex(),
        model_catalog_factory=catalog_factory,
        credential_vault=vault,
    )
    with LocalTestClient(app, base_url=ORIGIN):
        pass
    with LocalTestClient(app, base_url=ORIGIN) as client:
        response = client.put(
            path("claude"),
            json=body("claude", "sk-ant-api03-reentry-current"),
            headers=auth(client),
        )
        assert response.status_code == 200, response.text
        assert len(catalogs) == 2
        assert catalogs[0].sources == {}
        assert set(catalogs[1].sources) == {("claude", "api")}
        assert app.state.model_catalog is catalogs[1]


def test_deleted_cleanup_history_fails_closed_and_cannot_hide_an_orphan(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    endpoint = path("claude")
    with LocalTestClient(app, base_url=ORIGIN) as client:
        first = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-retired-one"),
            headers=auth(client),
        )
        assert first.status_code == 200
        vault.fail_operation = "delete"
        second = client.put(
            endpoint,
            json=body(
                "claude",
                "sk-ant-api03-current-two",
                expected_version=1,
                suffix="two",
            ),
            headers=auth(client),
        )
        assert second.status_code == 200
        assert second.json()["cleanup_pending"] is True
        assert len(vault.refs) == 2
        with app.state.store._connection() as db:
            db.execute(
                "DELETE FROM provider_credential_cleanup "
                "WHERE provider='claude' AND mode='api'"
            )
        vault.calls.clear()

        read = client.get(endpoint)
        mutation = client.request(
            "DELETE",
            endpoint,
            json={"expected_version": 2},
            headers=auth(client),
        )

        assert_error(read, 503, "storage_failed")
        assert_error(mutation, 503, "storage_failed")
        assert vault.calls == []
        assert len(vault.refs) == 2


def test_database_and_compensation_failure_leaves_a_recoverable_orphan(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    endpoint = path("claude")
    with LocalTestClient(app, base_url=ORIGIN) as client:
        with app.state.store._connection() as db:
            db.execute(
                "CREATE TRIGGER fail_staged_connection_insert "
                "BEFORE INSERT ON provider_connections BEGIN "
                "SELECT RAISE(ABORT, 'private-double-failure'); END"
            )
        vault.fail_operation = "delete"

        failed = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-recoverable-orphan"),
            headers=auth(client),
        )

        assert_error(failed, 503, "storage_failed")
        assert len(vault.refs) == 1
        pending = client.get(endpoint)
        assert_public_view(
            pending.json(),
            provider="claude",
            state="not_configured",
            version=0,
            cleanup_pending=True,
        )
        with app.state.store._connection() as db:
            assert db.execute(
                "SELECT COUNT(*) FROM provider_credential_allocations"
            ).fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM provider_orphan_cleanup"
            ).fetchone()[0] == 0
            db.execute("DROP TRIGGER fail_staged_connection_insert")

        vault.fail_operation = None
        retried = client.request(
            "DELETE",
            endpoint,
            json={"expected_version": 0},
            headers=auth(client),
        )

        assert retried.status_code == 200, retried.text
        assert_public_view(
            retried.json(),
            provider="claude",
            state="not_configured",
            version=0,
        )
        assert vault.refs == ()
        with app.state.store._connection() as db:
            assert db.execute(
                "SELECT COUNT(*) FROM provider_orphan_cleanup"
            ).fetchone()[0] == 1


@pytest.mark.parametrize("invalid_key", ("", 123, "key-with-\x00-nul"))
def test_invalid_key_is_rejected_before_allocation_or_vault_access(
    tmp_path, invalid_key
):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    with LocalTestClient(app, base_url=ORIGIN) as client:
        events = app.state.store.events()

        response = client.put(
            path("claude"),
            json=body("claude", invalid_key),
            headers=auth(client),
        )

        assert_error(response, 400, "invalid_input")
        assert vault.calls == []
        assert vault.refs == ()
        assert app.state.store.events() == events
        with app.state.store._connection() as db:
            assert db.execute(
                "SELECT COUNT(*) FROM provider_credential_allocations"
            ).fetchone()[0] == 0
            assert db.execute(
                "SELECT COUNT(*) FROM provider_connections"
            ).fetchone()[0] == 0


@pytest.mark.parametrize(
    ("secret", "with_vault", "error_type"),
    (
        ("bad\x00private-traceback-canary", True, ValueError),
        ("valid-private-traceback-canary", False, ProviderCredentialUnavailable),
    ),
)
def test_validation_and_vault_errors_scrub_secret_from_service_tracebacks(
    tmp_path, secret, with_vault, error_type
):
    vault = TrackingVault() if with_vault else None
    store_app = create_app(
        tmp_path,
        port=4193,
        understanding_provider_ready=False,
        codex_factory=lambda _store: QuietCodex(),
        model_catalog_factory=lambda _store, _codex: QuietCatalog(),
        credential_vault=vault,
    )
    subject = ProviderConnections(store_app.state.store, credential_vault=vault)

    with pytest.raises(error_type) as caught:
        subject.configure(
            "claude",
            "api",
            0,
            secret,
            workspace_id=None,
            project_id=None,
            organization_id=None,
        )

    traceback = caught.value.__traceback__
    inspected = 0
    while traceback is not None:
        module = traceback.tb_frame.f_globals.get("__name__", "")
        if module in {
            "app.services.provider_connections",
            "app.adapters.keychain",
        }:
            inspected += 1
            assert secret not in repr(tuple(traceback.tb_frame.f_locals.values()))
        traceback = traceback.tb_next
    assert inspected >= 1


def test_stale_mutation_does_not_retry_or_destroy_a_recoverable_orphan(tmp_path):
    vault = TrackingVault()
    app, _, _ = application(tmp_path, vault)
    endpoint = path("claude")
    with LocalTestClient(app, base_url=ORIGIN) as client:
        with app.state.store._connection() as db:
            db.execute(
                "CREATE TRIGGER fail_staged_connection_insert "
                "BEFORE INSERT ON provider_connections BEGIN "
                "SELECT RAISE(ABORT, 'private-orphan-preflight'); END"
            )
        vault.fail_operation = "delete"
        failed = client.put(
            endpoint,
            json=body("claude", "sk-ant-api03-preflight-orphan"),
            headers=auth(client),
        )
        assert_error(failed, 503, "storage_failed")
        assert len(vault.refs) == 1
        orphan_ref = vault.refs[0]
        events = app.state.store.events()
        vault.fail_operation = None
        vault.calls.clear()

        stale = client.put(
            endpoint,
            json=body(
                "claude",
                "sk-ant-api03-stale-must-have-no-effect",
                expected_version=1,
                suffix="stale",
            ),
            headers=auth(client),
        )

        assert_error(stale, 409, "stale_state")
        assert vault.calls == []
        assert vault.refs == (orphan_ref,)
        assert app.state.store.events() == events
        with app.state.store._connection() as db:
            assert db.execute(
                "SELECT COUNT(*) FROM provider_credential_allocations"
            ).fetchone()[0] == 1
            assert db.execute(
                "SELECT COUNT(*) FROM provider_orphan_cleanup"
            ).fetchone()[0] == 0


def test_catalog_authority_fails_closed_when_durable_connection_is_corrupt(tmp_path):
    class LocalClaudeSource:
        def connection_state(self, _binding):
            return "catalog_current"

        def fetch_catalog(self, binding, *, explicit_action):
            assert explicit_action is True
            return SimpleNamespace(
                models=(
                    SimpleNamespace(
                        id="claude-local-fixture",
                        display_name="Claude local fixture",
                        capabilities={"text_input": True},
                    ),
                ),
                binding_id=binding.binding_id,
                catalog_id="local-claude-catalog",
                fetched_at_ms=time.time_ns() // 1_000_000,
                max_age_ms=60_000,
                credential_generation=0,
                binding_generation=0,
                request_epoch=1,
            )

    vault = TrackingVault()
    app = create_app(
        tmp_path,
        port=4193,
        understanding_provider_ready=False,
        codex_factory=lambda _store: QuietCodex(),
        credential_vault=vault,
    )
    with LocalTestClient(app, base_url=ORIGIN) as client:
        connections = app.state.provider_connections
        connections._adapters[("claude", "api")] = LocalClaudeSource()
        response = client.put(
            path("claude"),
            json=body("claude", "sk-ant-api03-authority-ledger"),
            headers=auth(client),
        )
        assert response.status_code == 200, response.text
        catalog = app.state.model_catalog.refresh("claude", "api")
        assert catalog["status"] == "ready"
        choice = {
            "provider": "claude",
            "mode": "api",
            "catalog_id": catalog["catalog_id"],
            "model": "claude-local-fixture",
            "effort": None,
        }
        assert app.state.model_catalog.validate_choice(choice)["model"] \
            == "claude-local-fixture"

        with app.state.store._connection() as db:
            db.execute(
                "UPDATE provider_connections SET record_hash=? "
                "WHERE provider='claude' AND mode='api'",
                ("0" * 64,),
            )

        assert_error(client.get(path("claude")), 503, "storage_failed")
        assert app.state.model_catalog.snapshot("claude", "api")["status"] \
            == "error"
        with pytest.raises(ValueError):
            app.state.model_catalog.validate_choice(choice)


def test_committed_connection_survives_derived_catalog_publication_failure(tmp_path):
    class FailingCatalog(QuietCatalog):
        def bind_connection_authority(self, authority):
            self.authority = authority

        def replace_api_source(self, provider, mode, source):
            self.calls.append(("replace", provider, mode, source is not None))
            raise sqlite3.OperationalError("derived-catalog-failure")

    vault = TrackingVault()
    catalog = FailingCatalog()
    app = create_app(
        tmp_path,
        port=4193,
        understanding_provider_ready=False,
        codex_factory=lambda _store: QuietCodex(),
        model_catalog_factory=lambda _store, _codex: catalog,
        credential_vault=vault,
    )
    with LocalTestClient(app, base_url=ORIGIN) as client:
        response = client.put(
            path("claude"),
            json=body("claude", "sk-ant-api03-catalog-cache-failure"),
            headers=auth(client),
        )

        assert response.status_code == 200, response.text
        assert_public_view(
            response.json(), provider="claude", state="configured", version=1
        )
        assert len(vault.refs) == 1
        assert len(catalog.calls) >= 2
        current = client.get(path("claude"))
        assert_public_view(
            current.json(), provider="claude", state="configured", version=1
        )


def test_stale_catalog_publication_cannot_replace_latest_durable_binding(tmp_path):
    vault = TrackingVault()
    app = create_app(
        tmp_path,
        port=4193,
        understanding_provider_ready=False,
        codex_factory=lambda _store: QuietCodex(),
        credential_vault=vault,
    )
    with LocalTestClient(app, base_url=ORIGIN) as client:
        connections = app.state.provider_connections
        first = client.put(
            path("claude"),
            json=body("claude", "sk-ant-api03-first-publication"),
            headers=auth(client),
        )
        assert first.status_code == 200
        stale_source = connections.api_sources()[("claude", "api")]
        second = client.put(
            path("claude"),
            json=body(
                "claude",
                "sk-ant-api03-current-publication",
                expected_version=1,
                suffix="current",
            ),
            headers=auth(client),
        )
        assert second.status_code == 200
        current_source = connections.api_sources()[("claude", "api")]

        with pytest.raises(ValueError, match="Stale"):
            app.state.model_catalog.replace_api_source(
                "claude", "api", stale_source
            )

        assert app.state.model_catalog._source("claude", "api")[1].binding_id \
            == current_source[1].binding_id


def test_same_store_instances_serialize_staged_secret_and_stale_cleanup(tmp_path):
    class BlockingVault(TrackingVault):
        def __init__(self):
            super().__init__()
            self.staged = threading.Event()
            self.release = threading.Event()

        def store_at(self, ref, secret):
            result = super().store_at(ref, secret)
            self.staged.set()
            if not self.release.wait(5):
                raise AssertionError("test did not release staged credential")
            return result

    vault = BlockingVault()
    app, _, _ = application(tmp_path, vault)
    first = ProviderConnections(app.state.store, credential_vault=vault)
    second = ProviderConnections(app.state.store, credential_vault=vault)
    with ThreadPoolExecutor(max_workers=2) as pool:
        configured = pool.submit(
            first.configure,
            "claude",
            "api",
            0,
            "sk-ant-api03-shared-lock-current",
            workspace_id=None,
            project_id=None,
            organization_id=None,
        )
        assert vault.staged.wait(2)
        stale_delete = pool.submit(second.delete, "claude", "api", 0)
        time.sleep(0.05)
        assert not stale_delete.done()
        vault.release.set()
        assert configured.result(timeout=5)["version"] == 1
        with pytest.raises(ProviderConnectionConflict):
            stale_delete.result(timeout=5)

    assert len(vault.refs) == 1
    assert first.get("claude", "api")["state"] == "configured"
