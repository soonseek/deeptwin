"""HTTP contract for the authenticated T016 public API surface.

All state lives in a temporary local vault.  These tests never start a provider,
tool, browser login, credential read, or network dispatch.
"""

import json
from hashlib import sha256
import os
import sqlite3
import time
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.api.views import _append_event_in_transaction
import app.api.routes as api_routes
from app.api.routes import ResolvedDispatch
from app.api.transaction import DispatchAuthorization
from app.domain.refs import ObjectRef, canonical_json
from app.domain.schemas import Actor, ImmutableRecord
from app.runtime.budgets import BudgetDispatchRequest, BudgetPolicy
from app.runtime.ledger import AttemptSpec, ExecutionSpec, OwnerIdentity, RunSpec
from app.runtime.worker_coordinator import (
    AuthenticatedWorkerResponse,
    WorkerCoordinator,
    WorkerRouteBinding,
)
from app.runtime.worker_dispatch import WorkerDispatchBusy, WorkerDispatchService
import app.server as server_module
import app.storage as storage_module
from app.server import create_app
from app.tests.local_http import LocalTestClient
from app.workers import broker


ORIGIN = "http://127.0.0.1:4193"
FETCH = {"Origin": ORIGIN, "Sec-Fetch-Site": "same-origin"}
STAMP = "2027-01-15T08:00:00.000000Z"


def identifier():
    return str(uuid4())


def immutable(domain, roots, kind, *, content=None):
    record = ImmutableRecord.create(
        kind=kind,
        id=identifier(),
        version=1,
        created_at_utc=STAMP,
        actor_ref=roots.actor,
        parent_refs=(),
        purpose="operational",
        access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy,
        content={"fixture": kind} if content is None else content,
    )
    domain.put(record)
    return record


def append_public_event(application, *, byte_count=17):
    domain = application.state.domain_store
    roots = domain.roots()
    with domain._connection(write=True) as db:
        return _append_event_in_transaction(
            db,
            vault_id=domain.vault_id,
            observed_at_utc=STAMP,
            recorded_at_utc=STAMP,
            actor_kind="system",
            actor_ref=roots.actor,
            event_type="artifact.sealed",
            object_refs=(ObjectRef("artifact", identifier(), 1, "b" * 64),),
            correlation_id=identifier(),
            causation_id=None,
            status="succeeded",
            error_code=None,
            public_metadata={"byte_count": byte_count},
            private_evidence_refs=(roots.actor,),
            retention_class="core",
            policy_ref=roots.access_policy,
        )


def command_payload(command_id=None):
    return {
        "schema_version": "command-v1",
        "command_id": command_id or identifier(),
        "command_type": "attempt.dispatch",
        "target": {"kind": "attempt", "id": identifier()},
        "expected_revision": 1,
        "target_hash": "a" * 64,
        "args": {
            "grant_id": identifier(),
            "resource_sha256": "b" * 64,
            "budget_request_sha256": "c" * 64,
        },
    }


def dispatch_channel(pair_root):
    return broker.ChannelSpec(
        channel_id="control-document",
        requester_service="control",
        responder_service="document",
        request_direction="control-to-document",
        protocol_id="document-command-v1",
        requester_uid=10_001,
        requester_gid=10_002,
        responder_uid=10_003,
        responder_gid=10_004,
        pair_gid=10_005,
        pair_root=pair_root,
        socket_name="document.sock",
        root_uid=10_003,
        root_gid=10_005,
        socket_uid=10_003,
        socket_gid=10_005,
        requester_message_types=("execute",),
        responder_message_types=("completed", "failed"),
        max_queue_depth=1,
    )


def table_count(application, table):
    with sqlite3.connect(application.state.store.path) as db:
        return db.execute("SELECT count(*) FROM " + table).fetchone()[0]


def assert_error(response, *, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {
        "code", "message", "retryability", "affected_refs", "correlation_id",
    }
    assert body["code"] == code
    assert body["retryability"] in {"retryable", "not_retryable"}
    assert body["affected_refs"] == []
    assert isinstance(body["message"], str) and body["message"]
    assert isinstance(body["correlation_id"], str)
    uuid4().__class__(body["correlation_id"])
    return body


def test_default_app_initializes_one_shared_vault_without_changing_legacy_identity(tmp_path):
    first = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    with LocalTestClient(first, base_url=ORIGIN) as client:
        created = client.post(
            "/api/works", json={"text": "preserved legacy body"},
            headers={"X-CSRF-Token": client.csrf_token},
        ).json()
        vault_id = first.state.domain_store.vault_id
        assert first.state.permission_host.vault_id == vault_id
        assert first.state.permission_gate._host is first.state.permission_host
        assert first.state.budget_book.path == first.state.domain_store.path
        assert first.state.runtime_ledger.vault_id == vault_id
        assert first.state.root_commands.vault_id == vault_id

    reopened = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    with LocalTestClient(reopened, base_url=ORIGIN) as client:
        works = client.get("/api/works").json()
        assert [work["id"] for work in works] == [created["id"]]
        assert works[0]["text"] == "preserved legacy body"
        assert reopened.state.domain_store.vault_id == vault_id
        assert table_count(reopened, "api_commands") == 0
        assert table_count(reopened, "api_event_envelopes") == 0
        assert table_count(reopened, "runtime_budget_reservations") == 0


def test_arbitrary_ancestor_symlink_is_not_hidden_by_temp_path_normalization(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    marker = real / "existing-user-data.txt"
    marker.write_text("preserve me", encoding="utf-8")
    alias = tmp_path / "caller-owned-alias"
    alias.symlink_to(real, target_is_directory=True)
    before = tuple(sorted(item.name for item in real.iterdir()))
    with pytest.raises(ValueError):
        create_app(alias / "vault", port=4193, understanding_provider_ready=False)
    assert tuple(sorted(item.name for item in real.iterdir())) == before
    assert marker.read_text(encoding="utf-8") == "preserve me"
    assert not (real / "vault").exists()


@pytest.mark.parametrize("replacement_has_database", (False, True))
def test_validated_ancestor_swap_cannot_redirect_store_initialization(
        tmp_path, monkeypatch, replacement_has_database):
    validated = tmp_path / "validated"
    validated.mkdir()
    moved = tmp_path / "validated-moved"
    target_database = validated / "vault" / "intake.sqlite3"
    real_store = server_module.Store
    replacement_hash = None

    def swap_before_store(path, *args, **kwargs):
        nonlocal replacement_hash
        validated.rename(moved)
        validated.mkdir()
        if replacement_has_database:
            target_database.parent.mkdir(mode=0o700)
            with sqlite3.connect(target_database) as db:
                db.execute("CREATE TABLE user_canary(value TEXT NOT NULL)")
                db.execute("INSERT INTO user_canary VALUES ('preserve')")
            target_database.chmod(0o600)
            replacement_hash = sha256(target_database.read_bytes()).hexdigest()
        return real_store(path, *args, **kwargs)

    monkeypatch.setattr(server_module, "Store", swap_before_store)
    with pytest.raises(ValueError):
        create_app(
            validated / "vault",
            port=4193,
            understanding_provider_ready=False,
        )

    if replacement_has_database:
        assert sha256(target_database.read_bytes()).hexdigest() == replacement_hash
        with sqlite3.connect(target_database) as db:
            assert db.execute("SELECT value FROM user_canary").fetchone() == (
                "preserve",
            )
            assert db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='works'"
            ).fetchone() is None
    else:
        assert not target_database.exists()
        assert not (validated / "vault").exists()


@pytest.mark.parametrize("replacement_has_database", (False, True))
def test_sqlite_path_swap_after_handle_precreation_cannot_touch_replacement(
        tmp_path, monkeypatch, replacement_has_database):
    validated = tmp_path / "validated"
    validated.mkdir()
    moved = tmp_path / "validated-moved"
    target_database = validated / "vault" / "intake.sqlite3"
    real_connect = storage_module.sqlite3.connect
    swapped = False
    replacement_hash = None

    def swap_at_sqlite_open(database, *args, **kwargs):
        nonlocal swapped, replacement_hash
        if kwargs.get("uri") is True and "mode=rw" in str(database) and not swapped:
            swapped = True
            validated.rename(moved)
            target_database.parent.mkdir(parents=True, mode=0o700)
            if replacement_has_database:
                with real_connect(target_database) as db:
                    db.execute("CREATE TABLE user_canary(value TEXT NOT NULL)")
                    db.execute("INSERT INTO user_canary VALUES ('preserve')")
                target_database.chmod(0o600)
                replacement_hash = sha256(target_database.read_bytes()).hexdigest()
        return real_connect(database, *args, **kwargs)

    monkeypatch.setattr(storage_module.sqlite3, "connect", swap_at_sqlite_open)
    with pytest.raises((ValueError, sqlite3.Error)):
        create_app(
            validated / "vault",
            port=4193,
            understanding_provider_ready=False,
        )
    assert swapped is True
    if replacement_has_database:
        assert sha256(target_database.read_bytes()).hexdigest() == replacement_hash
        assert tuple(path.name for path in target_database.parent.iterdir()) == (
            "intake.sqlite3",
        )
        with real_connect(target_database) as db:
            assert db.execute("SELECT value FROM user_canary").fetchone() == (
                "preserve",
            )
            assert db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='works'"
            ).fetchone() is None
    else:
        assert not target_database.exists()
        assert list(target_database.parent.iterdir()) == []


@pytest.mark.parametrize("swap_stage", ("model_catalog", "requests", "domain"))
@pytest.mark.parametrize("replacement_has_database", (False, True))
def test_post_store_swap_cannot_redirect_any_followup_startup_writer(
        tmp_path, monkeypatch, swap_stage, replacement_has_database):
    """The Store's retained identity, not a later pathname, owns all startup writes."""
    validated = tmp_path / "validated"
    validated.mkdir()
    moved = tmp_path / "validated-moved"
    target_database = validated / "vault" / "intake.sqlite3"
    captured_store = []
    replacement_hash = None
    swapped = False

    def swap(store):
        nonlocal replacement_hash, swapped
        if swapped:
            return
        captured_store.append(store)
        validated.rename(moved)
        target_database.parent.mkdir(parents=True, mode=0o700)
        if replacement_has_database:
            with sqlite3.connect(target_database) as db:
                db.execute("CREATE TABLE user_canary(value TEXT NOT NULL)")
                db.execute("INSERT INTO user_canary VALUES ('preserve')")
            target_database.chmod(0o600)
            replacement_hash = sha256(target_database.read_bytes()).hexdigest()
        swapped = True

    if swap_stage == "model_catalog":
        real_factory = server_module.ModelCatalog

        def factory(store, codex):
            swap(store)
            return real_factory(store, codex)

        monkeypatch.setattr(server_module, "ModelCatalog", factory)
    elif swap_stage == "requests":
        real_factory = server_module.Requests

        def factory(store):
            swap(store)
            return real_factory(store)

        monkeypatch.setattr(server_module, "Requests", factory)
    else:
        real_factory = server_module.initialize_api_v1

        def factory(store, sessions):
            swap(store)
            return real_factory(store, sessions)

        monkeypatch.setattr(server_module, "initialize_api_v1", factory)

    with pytest.raises((ValueError, sqlite3.Error)):
        create_app(
            validated / "vault",
            port=4193,
            understanding_provider_ready=False,
        )

    assert swapped is True and len(captured_store) == 1
    # A failed constructor releases both retained capabilities; the old integer
    # values cannot silently become the application's long-lived authority.
    assert captured_store[0]._verified_directory_fd is None
    assert captured_store[0]._verified_database_fd is None
    if replacement_has_database:
        assert sha256(target_database.read_bytes()).hexdigest() == replacement_hash
        assert tuple(path.name for path in target_database.parent.iterdir()) == (
            "intake.sqlite3",
        )
        with sqlite3.connect(target_database) as db:
            assert db.execute("SELECT value FROM user_canary").fetchone() == (
                "preserve",
            )
            assert db.execute(
                "SELECT count(*) FROM sqlite_master WHERE name<>'user_canary'"
            ).fetchone() == (0,)
    else:
        assert not target_database.exists()
        assert list(target_database.parent.iterdir()) == []


def test_verified_store_handles_live_until_lifespan_shutdown(tmp_path):
    application = create_app(
        tmp_path / "vault", port=4193, understanding_provider_ready=False,
    )
    store = application.state.store
    directory_fd = store._verified_directory_fd
    database_fd = store._verified_database_fd
    assert type(directory_fd) is type(database_fd) is int
    assert os.fstat(directory_fd).st_ino == os.stat(store.data_dir).st_ino
    assert os.fstat(database_fd).st_ino == os.stat(store.path).st_ino

    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = client.post(
            "/api/works",
            json={"text": "retained identity"},
            headers={"X-CSRF-Token": client.csrf_token},
        )
        assert response.status_code == 201
        assert store._verified_directory_fd == directory_fd
        assert store._verified_database_fd == database_fd

    assert store._verified_directory_fd is None
    assert store._verified_database_fd is None
    with pytest.raises(OSError):
        os.fstat(directory_fd)
    with pytest.raises(OSError):
        os.fstat(database_fd)


def test_repeated_lifespan_rebuilds_closed_services_and_keeps_routes_live(tmp_path):
    application = create_app(
        tmp_path / "vault", port=4193, understanding_provider_ready=False,
    )
    original = {
        name: getattr(application.state, name)
        for name in (
            "codex", "model_catalog", "model_selections", "speech",
            "speech_sessions", "understanding",
        )
    }
    with LocalTestClient(application, base_url=ORIGIN) as client:
        work = client.post(
            "/api/works", json={"text": "lifespan reentry"},
            headers={"X-CSRF-Token": client.csrf_token},
        ).json()

    assert original["speech"]._closed is True
    assert original["speech_sessions"]._closed is True
    assert original["understanding"]._closed is True

    with LocalTestClient(application, base_url=ORIGIN) as client:
        current = {
            name: getattr(application.state, name) for name in original
        }
        assert all(current[name] is not original[name] for name in original)
        assert current["model_catalog"].codex is current["codex"]
        assert current["model_selections"].catalog is current["model_catalog"]
        assert current["speech"]._closed is False
        assert current["speech_sessions"]._closed is False
        assert current["understanding"]._closed is False
        started = client.post(
            "/api/speech/sessions",
            json={"work_id": work["id"], "revision": work["revision"]},
            headers={"X-CSRF-Token": client.csrf_token},
        )
        assert started.status_code == 201, started.text

    assert current["speech"]._closed is True
    assert current["speech_sessions"]._closed is True
    assert current["understanding"]._closed is True


def test_repeated_lifespan_builds_fresh_dispatcher_and_keeps_execution_unclaimed(
        tmp_path):
    generations = []
    profile = {}

    def factory(api):
        number = len(generations) + 1
        route = WorkerRouteBinding(
            profile_ref=profile["record"].ref,
            channel_spec=dispatch_channel(tmp_path / "worker-pair"),
            request_message_type="execute",
            response_message_types=("completed", "failed"),
        )
        coordinator = WorkerCoordinator(
            domain_store=api.domain_store,
            permission_gate=api.permission_gate,
            runtime_ledger=api.runtime_ledger,
            budget_book=api.budget_book,
            route=route,
            boot_secret=broker.BootSecret(bytes([number]) * broker.AUTH_SECRET_BYTES),
            requester_boot_id=f"control-generation-{number}",
            worker_boot_id=f"document-generation-{number}",
        )
        dispatcher = WorkerDispatchService(
            runtime_ledger=api.runtime_ledger,
            coordinators=(coordinator,),
        )
        generations.append((dispatcher, coordinator))
        return dispatcher

    application = create_app(
        tmp_path / "vault",
        port=4193,
        understanding_provider_ready=False,
        worker_dispatch_factory=factory,
    )
    domain = application.state.domain_store
    roots = domain.roots()
    profile["record"] = immutable(domain, roots, "runtime_profile")
    application.state.permission_host.register_record(profile["record"])

    for expected in (1, 2):
        with LocalTestClient(application, base_url=ORIGIN) as client:
            assert len(generations) == expected
            current, coordinator = generations[-1]
            assert application.state.worker_dispatch is current
            assert current.started is True
            assert coordinator._requester_boot_id == f"control-generation-{expected}"
            assert coordinator._worker_boot_id == f"document-generation-{expected}"
            assert client.get("/api/bootstrap").json()["capabilities"]["execution"] is False
        assert application.state.worker_dispatch is None
        assert current.started is False
        assert all(not thread.is_alive() for thread in current._threads)

    assert generations[0][0] is not generations[1][0]
    assert generations[0][1] is not generations[1][1]


def test_json_event_page_and_sse_emit_only_public_views_with_bound_cursors(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    append_public_event(application)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        page_response = client.get(
            "/api/v1/events", params=[("event_type", "artifact.sealed"), ("limit", "1")]
        )
        assert page_response.status_code == 200, page_response.text
        assert page_response.headers["cache-control"] == "no-store"
        assert page_response.headers["x-content-type-options"] == "nosniff"
        page = page_response.json()
        assert set(page) == {
            "events", "next_cursor", "snapshot_required", "gap", "links",
        }
        assert page["snapshot_required"] is False and page["gap"] is None
        assert len(page["events"]) == 1
        assert set(page["events"][0]) == {
            "event_id", "sequence", "observed_at_utc", "event_type", "object_refs",
            "status", "public_metadata",
        }
        serialized = json.dumps(page, sort_keys=True)
        for forbidden in (
            "private_evidence_refs", "actor_ref", "policy_ref", "vault_id",
        ):
            assert forbidden not in serialized

        stream = client.get(
            "/api/v1/events/stream",
            params=[("event_type", "artifact.sealed"), ("limit", "1")],
            headers={"Accept": "text/event-stream"},
        )
        assert stream.status_code == 200, stream.text
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["cache-control"] == "no-store"
        assert stream.headers["x-content-type-options"] == "nosniff"
        assert stream.headers["x-deeptwin-event-cursor"] == page["next_cursor"]
        assert "event: public_event\n" in stream.text
        assert "id: " + page["next_cursor"] + "\n" in stream.text
        for forbidden in (
            "private_evidence_refs", "actor_ref", "policy_ref", "vault_id",
        ):
            assert forbidden not in stream.text
        linked = client.get("/api/v1/events/artifact.sealed", params={"limit": "1"})
        assert linked.status_code == 200, linked.text
        assert [event["event_type"] for event in linked.json()["events"]] == [
            "artifact.sealed"
        ]


def test_event_cursor_duplicates_mismatch_and_unbounded_filters_fail_closed(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    append_public_event(application)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        page = client.get("/api/v1/events").json()
        cursor = page["next_cursor"]
        cases = (
            client.get("/api/v1/events?cursor=x&cursor=y"),
            client.get(
                "/api/v1/events", params={"cursor": cursor},
                headers={"Last-Event-ID": cursor},
            ),
            client.get("/api/v1/events", params={"limit": "101"}),
            client.get("/api/v1/events", params={"event_type": "raw.secret"}),
            client.get("/api/v1/events", params={"unknown": "1"}),
            client.get("/api/v1/snapshot", params={"unknown": "1"}),
        )
        for response in cases:
            assert_error(response, status=400, code="invalid_input")
        duplicate_header = super(LocalTestClient, client).request(
            "GET",
            "/api/v1/events",
            headers=[
                ("Sec-Fetch-Site", "same-origin"),
                ("Last-Event-ID", cursor),
                ("Last-Event-ID", cursor),
            ],
        )
        assert_error(duplicate_header, status=400, code="invalid_input")


def test_http_event_resume_reports_a_durable_gap_and_requires_snapshot(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    append_public_event(application, byte_count=1)
    append_public_event(application, byte_count=2)
    append_public_event(application, byte_count=3)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        old_cursor = client.get("/api/v1/events", params={"limit": "1"}).json()[
            "next_cursor"
        ]
        domain = application.state.domain_store
        with domain._connection(write=True) as db:
            db.execute(
                "UPDATE api_event_streams SET generation=generation+1,"
                "first_available_sequence=3,gap_reason='deleted' WHERE vault_id=?",
                (domain.vault_id,),
            )
        resumed = client.get("/api/v1/events", params={"cursor": old_cursor})
        assert resumed.status_code == 200, resumed.text
        body = resumed.json()
        assert body["events"] == []
        assert body["snapshot_required"] is True
        assert body["gap"] == {
            "reason": "deleted", "from_sequence": 2, "to_sequence": 2,
        }
        head = client.head("/api/v1/events", params={"cursor": old_cursor})
        assert head.status_code == 200
        assert head.content == b""
        assert head.headers["x-deeptwin-snapshot-required"] == "true"


def test_snapshot_is_one_public_state_projection_and_its_cursor_is_resumable(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    append_public_event(application)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        work = client.post(
            "/api/works", json={"text": "PRIVATE-BODY-CANARY"},
            headers={"X-CSRF-Token": client.csrf_token},
        ).json()
        uploaded = client.post(
            f"/api/works/{work['id']}/files?name=PRIVATE-NAME-CANARY.txt&expected_revision=1",
            content=b"PRIVATE-FILE-CANARY",
            headers={"Content-Type": "text/plain", "X-CSRF-Token": client.csrf_token},
        )
        assert uploaded.status_code == 201

        response = client.get("/api/v1/snapshot")
        assert response.status_code == 200, response.text
        snapshot = response.json()
        assert set(snapshot) == {"snapshot_version", "event_cursor", "state", "links"}
        assert snapshot["snapshot_version"] == "public-snapshot-v1"
        assert snapshot["state"]["works"] == [{
            "id": work["id"], "revision": 2, "file_count": 1,
        }]
        serialized = json.dumps(snapshot, sort_keys=True)
        for forbidden in (
            "PRIVATE-BODY-CANARY", "PRIVATE-NAME-CANARY", "PRIVATE-FILE-CANARY",
            "private_evidence_refs", "actor_ref", "policy_ref", "vault_id", "spec",
        ):
            assert forbidden not in serialized

        resumed = client.get(
            "/api/v1/events", params={"cursor": snapshot["event_cursor"]}
        )
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["events"] == []


def test_snapshot_rejects_corrupt_public_fields_without_reflecting_them(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    secret = "/Users/private/SNAPSHOT-SECRET-CANARY"
    with LocalTestClient(application, base_url=ORIGIN) as client:
        created = client.post(
            "/api/works", json={"text": "ordinary"},
            headers={"X-CSRF-Token": client.csrf_token},
        ).json()
        with sqlite3.connect(application.state.store.path) as db:
            db.execute("UPDATE works SET id=? WHERE id=?", (secret, created["id"]))
        response = client.get("/api/v1/snapshot")
        assert_error(response, status=503, code="storage_failed")
        assert secret not in response.text


def test_default_command_route_is_dependency_unavailable_without_any_local_effect(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    body = command_payload()
    with LocalTestClient(application, base_url=ORIGIN) as client:
        response = client.post(
            "/api/v1/commands", json=body,
            headers={"X-CSRF-Token": client.csrf_token},
        )
        error = assert_error(response, status=503, code="dependency_unavailable")
        assert body["command_id"] not in response.text
        assert error["retryability"] == "not_retryable"
        assert table_count(application, "api_commands") == 0
        assert table_count(application, "api_event_envelopes") == 0
        assert table_count(application, "runtime_commands") == 0
        assert table_count(application, "runtime_budget_reservations") == 0
        assert application.state.runtime_ledger.pending_permit_count == 0


def test_injected_trusted_context_runs_the_real_root_once_and_returns_202(
        tmp_path, monkeypatch):
    resolved = {}
    resolver_calls = []
    dispatcher_generations = []

    def resolver(envelope, authenticated, *, deadline):
        assert type(deadline) is broker.Deadline
        resolved.setdefault("resolver_deadlines", []).append(deadline)
        resolver_calls.append((envelope.command_id, authenticated.session.session_id))
        assert envelope.command_id == resolved["command_id"]
        assert authenticated.session is resolved["session"]
        if resolved.get("fail_resolver"):
            raise RuntimeError("replay must not need a runtime resolver")
        return resolved["context"]

    def dispatch_factory(api):
        attempt_snapshot = api.runtime_ledger.reserve_attempt(
            identifier(), resolved["attempt"], lease_duration_ms=30_000,
        )
        attempt = resolved["attempt"]
        grant = resolved["grant"]
        budget_request = resolved["budget_request"]
        body = {
            "schema_version": "command-v1",
            "command_id": resolved["command_id"],
            "command_type": "attempt.dispatch",
            "target": {"kind": "attempt", "id": attempt.attempt_id},
            "expected_revision": attempt_snapshot["revision"],
            "target_hash": attempt_snapshot["object_ref"]["content_hash"],
            "args": {
                "grant_id": grant.id,
                "resource_sha256": resolved["records"].envelope.ref.sha256,
                "budget_request_sha256": sha256(
                    canonical_json(budget_request.as_dict())
                ).hexdigest(),
            },
        }
        resolved["body"] = body
        resolved["context"] = ResolvedDispatch(
            DispatchAuthorization(
                principal=resolved["runtime"],
                grants=(grant,),
                resource_ref=resolved["records"].envelope.ref,
                action="read",
                purpose="operational",
                episode_id=None,
            ),
            attempt.attempt_id,
            resolved["owner"],
            budget_request,
            resolved["records"].profile.ref,
        )
        route = WorkerRouteBinding(
            profile_ref=resolved["records"].profile.ref,
            channel_spec=dispatch_channel(tmp_path / "worker-pair"),
            request_message_type="execute",
            response_message_types=("completed", "failed"),
        )
        coordinator = WorkerCoordinator(
            domain_store=api.domain_store,
            permission_gate=api.permission_gate,
            runtime_ledger=api.runtime_ledger,
            budget_book=api.budget_book,
            route=route,
            boot_secret=broker.BootSecret(b"k" * broker.AUTH_SECRET_BYTES),
            requester_boot_id=f"control-boot-{len(dispatcher_generations) + 1}",
            worker_boot_id=f"document-boot-{len(dispatcher_generations) + 1}",
        )

        def exchange_worker(permit, capability, *, deadline):
            assert capability.permit_id == permit.permit_id
            assert type(deadline) is broker.Deadline
            return AuthenticatedWorkerResponse(
                attempt_id=permit.attempt_id,
                connection_id="c" * 64,
                worker_boot_id=coordinator._worker_boot_id,
                message_id=identifier(),
                correlation_id=permit.command_id,
                message_type="completed",
                payload=b"{}",
            )

        coordinator.exchange = exchange_worker
        dispatcher = WorkerDispatchService(
            runtime_ledger=api.runtime_ledger,
            coordinators=(coordinator,),
        )
        dispatcher_generations.append(dispatcher)
        return dispatcher

    application = create_app(
        tmp_path, port=4193, understanding_provider_ready=False,
        runtime_dispatch_resolver=resolver,
        worker_dispatch_factory=dispatch_factory,
    )
    sessions = application.state.local_sessions
    launch = sessions.mint_bootstrap()
    exchange = sessions.exchange_bootstrap(
        launch.capability,
        method="POST",
        host="127.0.0.1:4193",
        origin=ORIGIN,
        sec_fetch_site="same-origin",
    )
    now = int(time.time())
    host = application.state.permission_host
    human = host.bind_human(exchange.session, expires_at=now + 900)
    runtime = host.bind_runtime(
        Actor(identifier(), "provider", "model_output"),
        purpose="operational",
        expires_at=now + 800,
    )
    domain = application.state.domain_store
    roots = domain.roots()
    policy = BudgetPolicy.create(
        profile="execution",
        provider_mode="subscription",
        max_model_calls=2,
        max_tool_calls=2,
        max_node_visits=3,
        max_loop_rounds=1,
        max_output_bytes=1_024,
        max_concurrency=1,
        max_wall_seconds=60,
        max_candidates=1,
    )
    records = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"),
        environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"),
        budget=immutable(domain, roots, "budget_policy", content=policy.domain_content()),
        manifest=immutable(domain, roots, "run_manifest"),
        envelope=immutable(domain, roots, "execution_envelope"),
        profile=immutable(domain, roots, "runtime_profile"),
    )
    for record in vars(records).values():
        host.register_record(record)
    grant = host.grant(
        human,
        runtime,
        records.envelope.ref,
        action="read",
        purpose="operational",
        expires_at=now + 700,
    )
    budget_session_id = identifier()
    application.state.budget_book.start(budget_session_id, policy)
    ledger = application.state.runtime_ledger
    run = RunSpec(
        identifier(), records.work.ref, records.environment.ref, records.consent.ref,
        "live", records.budget.ref, budget_session_id, records.manifest.ref,
    )
    ledger.create_run(identifier(), run)
    execution = ExecutionSpec(
        identifier(), run.run_id, "writer", identifier(), (0,), (),
    )
    ledger.create_execution(identifier(), execution)
    owner = OwnerIdentity(identifier(), 4_321, 900, identifier())
    attempt = AttemptSpec(
        identifier(), execution.execution_id, 1, records.envelope.ref,
        records.profile.ref, records.budget.ref, identifier(),
        "effect:" + identifier(), owner,
        int(time.time_ns() // 1_000_000) + 60_000,
    )
    budget_request = BudgetDispatchRequest.create(
        session_id=budget_session_id,
        request_id=attempt.reservation_id,
        policy_ref=records.budget.ref,
        model_calls=1,
        tool_calls=0,
        node_visits=1,
        loop_rounds=0,
        output_bytes=100,
        candidates=0,
        api_microunits=None,
    )
    command_id = identifier()
    resolved.update(
        command_id=command_id,
        session=exchange.session,
        attempt=attempt,
        owner=owner,
        runtime=runtime,
        grant=grant,
        budget_request=budget_request,
        records=records,
    )
    headers = {
        **FETCH,
        "Cookie": exchange.cookie_pair,
        "X-CSRF-Token": exchange.csrf_token,
    }
    with TestClient(application, base_url=ORIGIN) as client:
        assert client.get(
            "/api/bootstrap",
            headers={
                "Cookie": exchange.cookie_pair,
                "Sec-Fetch-Site": "same-origin",
            },
        ).json()["capabilities"]["execution"] is False
        body = resolved["body"]
        dispatcher = application.state.worker_dispatch
        real_reserve = dispatcher.reserve

        def busy_reserve(*_args, **_kwargs):
            raise WorkerDispatchBusy()

        monkeypatch.setattr(dispatcher, "reserve", busy_reserve)
        before_busy = {
            name: table_count(application, name)
            for name in (
                "api_commands", "api_event_envelopes",
                "runtime_budget_reservations",
            )
        }
        assert_error(
            client.post("/api/v1/commands", json=body, headers=headers),
            status=429,
            code="dispatch_busy",
        )
        assert {
            name: table_count(application, name) for name in before_busy
        } == before_busy
        assert application.state.runtime_ledger.pending_permit_count == 0
        monkeypatch.setattr(dispatcher, "reserve", real_reserve)

        deadline_bindings = {}
        real_accept = WorkerDispatchService.accept
        real_root_execute = application.state.root_commands.execute_budgeted_dispatch

        def observed_reserve(*args, **kwargs):
            deadline_bindings["reserve"] = kwargs["deadline"]
            return real_reserve(*args, **kwargs)

        def observed_root(*args, **kwargs):
            deadline_bindings["root"] = kwargs["deadline"]
            return real_root_execute(*args, **kwargs)

        def observed_accept(service, *args, **kwargs):
            assert service is dispatcher
            deadline_bindings["accept"] = kwargs["deadline"]
            return real_accept(service, *args, **kwargs)

        monkeypatch.setattr(dispatcher, "reserve", observed_reserve)
        monkeypatch.setattr(WorkerDispatchService, "accept", observed_accept)
        monkeypatch.setattr(
            application.state.root_commands,
            "execute_budgeted_dispatch",
            observed_root,
        )

        first = client.post("/api/v1/commands", json=body, headers=headers)
        replay = client.post("/api/v1/commands", json=body, headers=headers)
        assert first.status_code == replay.status_code == 202
        assert first.json() == replay.json()
        assert first.json()["command_id"] == command_id
        assert first.json()["state"] == "pending"
        route_deadline = resolved["resolver_deadlines"][1]
        assert deadline_bindings == {
            "reserve": route_deadline,
            "root": route_deadline,
            "accept": route_deadline,
        }
        dispatcher_generations[0].wait_idle(broker.Deadline.after_ms(5_000))
        assert application.state.runtime_ledger.pending_permit_count == 0
        status_headers = {
            "Cookie": exchange.cookie_pair,
            "Sec-Fetch-Site": "same-origin",
        }
        status = client.get(first.json()["links"]["self"], headers=status_headers)
        assert status.status_code == 200, status.text
        assert set(status.json()) == {
            "command_id", "state", "object_ref", "revision", "dispatch",
            "event_cursor", "links",
        }
        assert status.json()["command_id"] == command_id
        assert status.json()["state"] == "running"
        assert status.json()["dispatch"] == {
            "state": "transport_accepted",
            "effect": "transport_accepted",
        }
        head = client.head(first.json()["links"]["self"], headers=status_headers)
        assert head.status_code == 200 and head.content == b""
        assert head.headers["x-deeptwin-command-state"] == "running"
        assert head.headers["x-deeptwin-dispatch-state"] == "transport_accepted"
        assert_error(
            client.get(
                f"/api/v1/commands/{identifier()}", headers=status_headers,
            ),
            status=404,
            code="not_found",
        )
        linked = client.get(
            first.json()["links"]["events"],
            headers={"Cookie": exchange.cookie_pair, "Sec-Fetch-Site": "same-origin"},
        )
        assert linked.status_code == 200, linked.text
        assert [event["event_type"] for event in linked.json()["events"]] == [
            "attempt.dispatched"
        ]

        changed = json.loads(json.dumps(body))
        changed["args"]["resource_sha256"] = "d" * 64
        assert_error(
            client.post("/api/v1/commands", json=changed, headers=headers),
            status=409,
            code="stale_state",
        )

        another_launch = sessions.mint_bootstrap()
        another_exchange = sessions.exchange_bootstrap(
            another_launch.capability,
            method="POST",
            host="127.0.0.1:4193",
            origin=ORIGIN,
            sec_fetch_site="same-origin",
        )
        other_headers = {
            **FETCH,
            "Cookie": another_exchange.cookie_pair,
            "X-CSRF-Token": another_exchange.csrf_token,
        }
        assert_error(
            client.get(
                first.json()["links"]["self"],
                headers={
                    "Cookie": another_exchange.cookie_pair,
                    "Sec-Fetch-Site": "same-origin",
                },
            ),
            status=404,
            code="not_found",
        )
        assert_error(
            client.post("/api/v1/commands", json=body, headers=other_headers),
            status=409,
            code="stale_state",
        )
        assert resolver_calls == [
            (command_id, exchange.session.session_id),
            (command_id, exchange.session.session_id),
        ]

        # Simulate a first journal read racing just ahead of another request's commit:
        # the resolver then fails, so the delivery boundary must re-read the exact durable
        # receipt rather than report a false dependency failure or mint another permit.
        original_read = api_routes._stored_command_receipt
        replay_reads = []

        def raced_read(*args, **kwargs):
            replay_reads.append(kwargs.get("synchronize", False))
            if len(replay_reads) == 1:
                return None
            return original_read(*args, **kwargs)

        monkeypatch.setattr(api_routes, "_stored_command_receipt", raced_read)
        resolved["fail_resolver"] = True
        raced = client.post("/api/v1/commands", json=body, headers=headers)
        assert raced.status_code == 202
        assert raced.json() == first.json()
        assert replay_reads == [False, True]
        assert resolver_calls == [
            (command_id, exchange.session.session_id),
            (command_id, exchange.session.session_id),
            (command_id, exchange.session.session_id),
        ]
        # A duplicate racing with a now-full queue still receives its exact durable
        # receipt after the synchronized recheck; it is not reported as a new 429.
        capacity_reads = []

        def capacity_race_read(*args, **kwargs):
            capacity_reads.append(kwargs.get("synchronize", False))
            if len(capacity_reads) == 1:
                return None
            return original_read(*args, **kwargs)

        resolved["fail_resolver"] = False
        monkeypatch.setattr(api_routes, "_stored_command_receipt", capacity_race_read)
        monkeypatch.setattr(dispatcher, "reserve", busy_reserve)
        capacity_race = client.post("/api/v1/commands", json=body, headers=headers)
        assert capacity_race.status_code == 202
        assert capacity_race.json() == first.json()
        assert capacity_reads == [False, True]
        assert application.state.runtime_ledger.pending_permit_count == 0
    assert table_count(application, "api_commands") == 1
    assert table_count(application, "api_event_envelopes") == 1
    assert table_count(application, "runtime_commands") >= 4
    assert table_count(application, "runtime_budget_reservations") == 1


def test_v1_boundary_and_command_errors_have_fixed_redacted_shape(tmp_path):
    secret = "/Users/private/SECRET-CANARY"

    def broken_resolver(*_args, **_kwargs):
        raise RuntimeError(secret)

    application = create_app(
        tmp_path, port=4193, understanding_provider_ready=False,
        runtime_dispatch_resolver=broken_resolver,
    )
    with TestClient(application, base_url=ORIGIN, raise_server_exceptions=False) as raw:
        unauthenticated = raw.get(
            "/api/v1/events", headers={"Sec-Fetch-Site": "same-origin"}
        )
        assert_error(unauthenticated, status=401, code="unauthenticated")

    with LocalTestClient(application, base_url=ORIGIN) as client:
        assert_error(
            client.get("/api/v1/not-a-route"), status=404, code="not_found"
        )
        assert_error(client.get("/api/v1"), status=404, code="not_found")
        assert_error(
            client.put(
                "/api/v1/events", json={},
                headers={"X-CSRF-Token": client.csrf_token},
            ),
            status=405,
            code="invalid_input",
        )
        malformed = client.post(
            "/api/v1/commands", json={"command_id": identifier()},
            headers={"X-CSRF-Token": client.csrf_token},
        )
        assert_error(malformed, status=400, code="invalid_input")
        query_command = client.post(
            "/api/v1/commands?unknown=1", json=command_payload(),
            headers={"X-CSRF-Token": client.csrf_token},
        )
        assert_error(query_command, status=400, code="invalid_input")
        missing_csrf = client.post("/api/v1/commands", json=command_payload())
        assert_error(missing_csrf, status=403, code="access_denied")
        failed = client.post(
            "/api/v1/commands", json=command_payload(),
            headers={"X-CSRF-Token": client.csrf_token},
        )
        assert_error(failed, status=503, code="dependency_unavailable")
        assert secret not in failed.text


def test_invalid_or_expired_session_cookie_on_mutation_is_unauthenticated(tmp_path):
    application = create_app(tmp_path, port=4193, understanding_provider_ready=False)
    sessions = application.state.local_sessions
    launch = sessions.mint_bootstrap()
    exchange = sessions.exchange_bootstrap(
        launch.capability,
        method="POST",
        host="127.0.0.1:4193",
        origin=ORIGIN,
        sec_fetch_site="same-origin",
    )
    with TestClient(application, base_url=ORIGIN) as raw:
        invalid = raw.post(
            "/api/v1/commands",
            json=command_payload(),
            headers={
                **FETCH,
                "Cookie": "deeptwin_local_session=" + "x" * 32,
                "X-CSRF-Token": "y" * 32,
            },
        )
        assert_error(invalid, status=401, code="unauthenticated")

        sessions._clock = lambda: exchange.expires_at + 1
        expired = raw.post(
            "/api/v1/commands",
            json=command_payload(),
            headers={
                **FETCH,
                "Cookie": exchange.cookie_pair,
                "X-CSRF-Token": exchange.csrf_token,
            },
        )
        assert_error(expired, status=401, code="unauthenticated")


def test_documented_v1_head_reads_have_no_body_and_no_side_effects(tmp_path):
    calls = []

    def resolver(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("HEAD route attempted runtime dispatch")

    application = create_app(
        tmp_path,
        port=4193,
        understanding_provider_ready=False,
        runtime_dispatch_resolver=resolver,
    )
    append_public_event(application)
    tables = (
        "events",
        "api_commands",
        "api_event_envelopes",
        "runtime_commands",
        "runtime_budget_reservations",
    )
    before = {table: table_count(application, table) for table in tables}
    with LocalTestClient(application, base_url=ORIGIN) as client:
        responses = (
            client.head("/api/v1/events", params={"limit": "1"}),
            client.head("/api/v1/events/stream", params={"limit": "1"}),
            client.head("/api/v1/events/artifact.sealed", params={"limit": "1"}),
            client.head("/api/v1/snapshot"),
        )
        for response in responses:
            assert response.status_code == 200, response.text
            assert response.content == b""
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-content-type-options"] == "nosniff"
        assert responses[1].headers["content-type"].startswith("text/event-stream")
        assert responses[0].headers["x-deeptwin-event-cursor"]
        assert responses[1].headers["x-deeptwin-event-cursor"]
        assert responses[2].headers["x-deeptwin-event-cursor"]
        assert responses[3].headers["x-deeptwin-event-cursor"]
        for response in responses:
            assert response.headers["x-deeptwin-snapshot-required"] == "false"
        invalid = client.head("/api/v1/events", params={"limit": "101"})
        assert invalid.status_code == 400
        assert invalid.content == b""
    assert {table: table_count(application, table) for table in tables} == before
    assert calls == []


def test_public_gets_do_not_invoke_the_dispatch_resolver(tmp_path):
    calls = []

    def resolver(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("read route attempted runtime dispatch")

    application = create_app(
        tmp_path, port=4193, understanding_provider_ready=False,
        runtime_dispatch_resolver=resolver,
    )
    append_public_event(application)
    with LocalTestClient(application, base_url=ORIGIN) as client:
        assert client.get("/api/v1/events").status_code == 200
        assert client.get("/api/v1/events/stream").status_code == 200
        assert client.get("/api/v1/snapshot").status_code == 200
        assert client.get(f"/api/v1/commands/{identifier()}").status_code == 404
    assert calls == []
