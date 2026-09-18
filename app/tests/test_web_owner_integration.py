"""Supported ASGI factory requires deployment authority, never preview fallback."""
import json
import os
import sqlite3
import time
from base64 import urlsafe_b64encode
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app


def test_supported_factory_refuses_missing_deployment_authority_before_services(tmp_path):
    with pytest.raises((TypeError, ValueError)):
        create_app(tmp_path / "data")


def configured(tmp_path, mode="local"):
    profile = (OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=4193)
               if mode == "local" else OriginProfile.portable(instance_id="1" * 32, url="https://example.test"))
    capability = urlsafe_b64encode(b"S" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(tmp_path / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    return profile, capability, {"deployment_config": configuration, "session_root_dir": tmp_path / "root",
                                    "expected_uid": os.getuid(), "expected_gid": os.getgid()}


def headers(profile, csrf=None):
    result = {"Origin": profile.http_origin, "Sec-Fetch-Site": "same-origin"}
    if csrf is not None:
        result["X-DeepTwin-CSRF"] = csrf
    return result


@pytest.mark.parametrize("mode", ["local", "https"])
def test_real_cookie_snapshot_cold_restart_login_logout(tmp_path, mode):
    profile, capability, arguments = configured(tmp_path, mode)
    app = create_app(tmp_path / "data", **arguments)
    path = profile.base_path
    with TestClient(app, base_url=profile.http_origin) as client:
        assert client.get(path + "api/v1/snapshot", headers=headers(profile)).status_code == 401
        response = client.post(path + "session/bootstrap", headers=headers(profile), json={
            "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": capability})
        assert response.status_code == 201, response.text
        cookie = response.headers["set-cookie"]
        assert "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert ("Secure" in cookie) == (mode == "https")
        csrf = response.json()["csrf_token"]
        snapshot = client.get(path + "api/v1/snapshot", headers=headers(profile))
        assert snapshot.status_code == 200
        assert client.get(snapshot.json()["links"]["events"], headers=headers(profile)).status_code == 200
        assert client.get(path + "session", headers=headers(profile)).json()["csrf_token"] == csrf
        saved_cookies = dict(client.cookies)
        replay = client.post(path + "session/bootstrap", headers=headers(profile), json={
            "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": capability})
        assert replay.status_code == 409
        assert client.get(path + "session", headers=headers(profile)).status_code == 200
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        client.cookies.update(saved_cookies)
        assert client.get(path + "session", headers=headers(profile)).status_code == 200
        client.cookies.clear()
        response = client.post(path + "session/login", headers=headers(profile), json={
            "login_name": "owner", "password": "synthetic owner passphrase"})
        assert response.status_code == 200, response.text
        csrf = response.json()["csrf_token"]
        revoked = dict(client.cookies)
        command = {"command_id": str(uuid4())}
        logout = client.post(path + "session/logout", headers=headers(profile, csrf), json=command)
        assert logout.status_code == 200
        client.cookies.update(revoked)
        assert client.get(path + "session", headers=headers(profile)).status_code == 401
        assert client.post(path + "session/logout", headers=headers(profile, csrf), json=command).json() == logout.json()


def test_supported_startup_never_constructs_preview_services(tmp_path, monkeypatch):
    from app import server
    profile, _, arguments = configured(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail("Supported authentication constructed a development provider/STT service")
    monkeypatch.setattr(server, "CodexConnection", forbidden)
    monkeypatch.setattr(server, "Speech", forbidden)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        assert client.get(profile.base_path + "health").status_code == 200


def bootstrap_client(client, profile, capability):
    response = client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
        "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": capability})
    assert response.status_code == 201, response.text
    return response.json()["csrf_token"]


def bound_request(application, client, profile, csrf):
    authority = application.state.owner_authority
    return authority.authenticate_request(method="POST", host=profile.http_origin.split("://", 1)[1],
        origin=profile.http_origin, sec_fetch_site="same-origin", csrf_token=csrf,
        cookie_header=f"{authority.cookie_name}={client.cookies[authority.cookie_name]}")


def test_command_writer_revalidates_real_session_after_early_auth_logout(tmp_path, monkeypatch):
    from app.services.owner_auth import OwnerAuthError
    from app.tests.test_server_api_v1 import command_payload
    from app.workers import broker
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        request = bound_request(application, client, profile, csrf)
        root = application.state.root_commands
        original = root._authenticated_actor
        raced = []
        def authenticate_then_logout(*args, **kwargs):
            actor = original(*args, **kwargs)
            if not raced:
                raced.append(True)
                application.state.owner_authority.logout(request, command_id=str(uuid4()),
                    token_b64u=client.cookies[application.state.owner_authority.cookie_name])
            return actor
        monkeypatch.setattr(root, "_authenticated_actor", authenticate_then_logout)
        with pytest.raises(OwnerAuthError, match="unauthenticated"):
            root.execute_budgeted_dispatch(command_payload(), request=request, authorization=None,
                attempt_id=str(uuid4()), owner=None, budget_request=None, route_profile_ref=None,
                deadline=broker.Deadline.after_ms(3000))
        with application.state.domain_store._connection() as db:
            assert db.execute("SELECT count(*) FROM api_commands").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM runtime_budget_reservations").fetchone()[0] == 0
        assert application.state.runtime_ledger.pending_permit_count == 0


@pytest.mark.parametrize("raw", [b'{}', b'\xef\xbb\xbf{}', b'{"login_name":"owner","login_name":"owner"}',
    b'{"login_name":true,"password":"long synthetic passphrase","raw_capability_b64u":"a"}',
    b'{"login_name":"owner","password":NaN}', b'{} {}', b'\xff', b'[' + b' ' * 8192 + b']'])
def test_malformed_bootstrap_performs_no_auth_state_or_native_work(tmp_path, monkeypatch, raw):
    profile, _, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    authority = application.state.owner_authority
    def forbidden(*args, **kwargs):
        pytest.fail("Malformed wire reached auth state or native work")
    monkeypatch.setattr(authority, "bootstrap", forbidden)
    with TestClient(application, base_url=profile.http_origin) as client:
        response = client.post(profile.base_path + "session/bootstrap", content=raw,
            headers={**headers(profile), "Content-Type": "application/json"})
        assert response.status_code in (400, 413)
        with application.state.domain_store._connection() as db:
            assert db.execute("SELECT attempts FROM owner_auth_bootstrap_claims").fetchone()[0] == 0


@pytest.mark.parametrize("path,extra", [
    ("/api/v1/snapshot", {}), ("/{base}/../api/v1/snapshot", {}),
    ("/{base}/api%2fv1/snapshot", {}), ("/{base}//api/v1/snapshot", {}),
    ("/{base}/api/v1/snapshot", {"Host": "elsewhere.test"}),
    ("/{base}/api/v1/snapshot", {"Origin": "null"}),
    ("/{base}/api/v1/snapshot", {"X-Forwarded-Proto": "https"}),
    ("/{base}/api/v1/snapshot", {"Forwarded": "proto=https"}),
    ("/{base}/api/v1/snapshot", {"Sec-Fetch-Site": "cross-site"}),
])
def test_transport_is_rejected_before_authentication(tmp_path, monkeypatch, path, extra):
    profile, _, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    def forbidden(*args, **kwargs):
        pytest.fail("Wrong transport reached authentication")
    monkeypatch.setattr(application.state.owner_authority, "authenticate_request", forbidden)
    with TestClient(application, base_url=profile.http_origin) as client:
        response = client.get(path.replace("{base}", "2" * 32), headers={**headers(profile), **extra})
        assert response.status_code == 403
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("stage", ["claim_commit", "hash", "actor", "descriptor", "accounts", "authenticators", "sessions", "event", "owner_commit"])
def test_bootstrap_faults_preserve_two_commit_boundary_on_reopen(tmp_path, monkeypatch, stage):
    from app.services import owner_auth_storage as storage
    from app.services.owner_auth import OwnerAuthError
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    authority, domain = application.state.owner_authority, application.state.domain_store
    native_calls = []
    original_hash = authority._hash
    def hash_password(password):
        native_calls.append(True)
        if stage == "hash":
            raise RuntimeError("synthetic hash failure")
        with sqlite3.connect(domain.path, timeout=0.1) as probe:
            probe.execute("BEGIN IMMEDIATE")
            probe.rollback()
        return original_hash(password)
    monkeypatch.setattr(authority, "_hash", hash_password)
    original_insert = storage.insert
    def insert(db, table, values):
        if table == stage:
            raise sqlite3.DatabaseError("synthetic write failure")
        return original_insert(db, table, values)
    monkeypatch.setattr(storage, "insert", insert)
    def fail(*args, **kwargs):
        raise sqlite3.DatabaseError("synthetic stage failure")
    if stage == "actor":
        monkeypatch.setattr(domain, "_put_in_transaction", fail)
    if stage == "descriptor":
        monkeypatch.setattr(application.state.permission_host, "_register_record_in_transaction", fail)
    if stage == "event":
        monkeypatch.setattr(authority, "_event", fail)
    original_connection = domain._connection
    @contextmanager
    def connection(*, write=False):
        with original_connection(write=write) as db:
            yield db
            if write and stage in {"claim_commit", "owner_commit"}:
                accounts = db.execute("SELECT count(*) FROM owner_auth_accounts").fetchone()[0]
                claim = db.execute("SELECT state FROM owner_auth_bootstrap_claims").fetchone()[0]
                if (stage == "claim_commit" and claim == "consumed") or (stage == "owner_commit" and accounts):
                    db.set_authorizer(lambda action, arg, *_: sqlite3.SQLITE_DENY
                                      if action == sqlite3.SQLITE_TRANSACTION and arg == "COMMIT" else sqlite3.SQLITE_OK)
    monkeypatch.setattr(domain, "_connection", connection)
    with TestClient(application, base_url=profile.http_origin) as client:
        response = client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
            "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": capability})
        assert response.status_code == 503
        with original_connection() as db:
            assert db.execute("SELECT count(*) FROM owner_auth_accounts").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM owner_auth_sessions").fetchone()[0] == 0
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind='actor'").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM api_event_envelopes").fetchone()[0] == 0
    assert len(native_calls) == (0 if stage == "claim_commit" else 1)
    monkeypatch.undo()
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin):
        if stage != "claim_commit":
            with pytest.raises(OwnerAuthError, match="setup_incomplete"):
                reopened.state.owner_authority.bootstrap(login_name="owner", password="synthetic owner passphrase",
                                                        raw_capability_b64u=capability, source_key="synthetic")


def test_fifth_valid_guess_can_win_and_attempts_survive_restart(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        for _ in range(4):
            response = client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
                "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": "A" * 43})
            assert response.status_code == 401
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        bootstrap_client(client, profile, capability)
        with reopened.state.domain_store._connection() as db:
            assert db.execute("SELECT attempts,state FROM owner_auth_bootstrap_claims").fetchone()[:] == (5, "completed")


def test_uniform_bad_password_and_unknown_account_and_private_hash_profile(tmp_path):
    from argon2 import Type, extract_parameters
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        raw_cookie = client.cookies[application.state.owner_authority.cookie_name]
        with application.state.domain_store._connection() as db:
            encoded = db.execute("SELECT encoded_hash FROM owner_auth_authenticators").fetchone()[0]
            parameters = extract_parameters(encoded)
            assert (parameters.type, parameters.version, parameters.salt_len, parameters.hash_len,
                    parameters.memory_cost, parameters.time_cost, parameters.parallelism) == (Type.ID, 19, 16, 32, 65536, 3, 4)
            dumped = "\n".join(db.iterdump())
        for secret in ("synthetic owner passphrase", raw_cookie, capability, csrf):
            assert secret not in dumped
        timings, responses = [], []
        for name in ("owner", "unknown"):
            before = time.monotonic()
            response = client.post(profile.base_path + "session/login", headers=headers(profile), json={"login_name": name, "password": "x"})
            timings.append(time.monotonic() - before)
            assert response.status_code == 401
            responses.append(response.json())
        assert responses[0] == responses[1]
        assert all(elapsed >= 0.25 for elapsed in timings)
        print("auth-failure-canary-seconds", [round(value, 4) for value in timings])
        public = client.get(profile.base_path + "api/v1/snapshot", headers=headers(profile)).text
        assert encoded not in public and raw_cookie not in public


def test_copied_stale_identities_and_wrong_writer_are_rejected(tmp_path):
    from app.services.owner_auth import OwnerAuthError
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        request = bound_request(application, client, profile, csrf)
        with pytest.raises(OwnerAuthError):
            application.state.owner_authority.authenticate_bound(replace(request.session))
        with sqlite3.connect(application.state.store.path) as db, pytest.raises(OwnerAuthError, match="unavailable"):
            application.state.owner_authority.authenticate_bound(request.session, db=db)
        saved = dict(client.cookies)
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        client.cookies.update(saved)
        assert client.get(profile.base_path + "session", headers=headers(profile)).status_code == 200
        with pytest.raises(OwnerAuthError):
            reopened.state.owner_authority.authenticate_bound(request.session)


def test_real_owner_http_command_reaches_existing_worker_boundary(tmp_path, monkeypatch):
    import socket
    from threading import Event, Thread

    from app.runtime.worker_coordinator import WorkerCoordinator, WorkerRouteBinding
    from app.runtime.worker_dispatch import WorkerDispatchService
    from app.tests.owner_runtime_fixture import runtime_context
    from app.tests.test_server_api_v1 import dispatch_channel, immutable
    from app.workers import broker
    state, threads, errors = {}, [], []
    delivered = Event()
    profile, capability, arguments = configured(tmp_path)
    def resolver(envelope, request, *, deadline):
        assert request.session is state["session"]
        return state["context"].resolved
    def factory(api):
        record = immutable(api.domain_store, api.domain_store.roots(), "runtime_profile")
        state["profile"] = record
        route = WorkerRouteBinding(profile_ref=record.ref, channel_spec=dispatch_channel(tmp_path / "pair"),
                                   request_message_type="execute", response_message_types=("completed", "failed"))
        coordinator = WorkerCoordinator(domain_store=api.domain_store, permission_gate=api.permission_gate,
            runtime_ledger=api.runtime_ledger, budget_book=api.budget_book, route=route,
            boot_secret=broker.BootSecret(b"k" * broker.AUTH_SECRET_BYTES),
            requester_boot_id="synthetic-control", worker_boot_id="synthetic-worker")
        def connect(spec, *, local_service, deadline):
            client, worker = socket.socketpair()
            def serve():
                codec = None
                try:
                    session = broker.server_handshake(worker, spec, coordinator._secret,
                        requester_boot_id="synthetic-control", responder_boot_id="synthetic-worker", deadline=deadline)
                    codec = broker.FrameCodec(spec, session, local_service=spec.responder_service)
                    frame = codec.read(worker, deadline=deadline)
                    assert frame.payload == state["context"].records.envelope.body_bytes
                    state["worker_command"] = frame.envelope.message_id
                    delivered.set()
                    codec.write(worker, message_id=str(uuid4()), correlation_id=frame.envelope.message_id,
                                message_type="completed", payload=b"{}", deadline=deadline)
                except BaseException as error:  # noqa: BLE001 - surface all failures from the owned fixture thread
                    errors.append(error)
                finally:
                    if codec is not None:
                        codec.close()
                    worker.close()
            thread = Thread(target=serve)
            threads.append(thread)
            thread.start()
            return client, None, None
        monkeypatch.setattr(broker, "connect_verified", connect)
        monkeypatch.setattr(broker, "_verify_peer", lambda *_args, **_kwargs: None)
        return WorkerDispatchService(runtime_ledger=api.runtime_ledger, coordinators=(coordinator,))
    application = create_app(tmp_path / "data", **arguments, runtime_dispatch_resolver=resolver,
                             worker_dispatch_factory=factory)
    try:
        with TestClient(application, base_url=profile.http_origin) as client:
            csrf = bootstrap_client(client, profile, capability)
            request = bound_request(application, client, profile, csrf)
            state["session"] = request.session
            state["context"] = runtime_context(application, request.session, profile_record=state["profile"])
            response = client.post(profile.base_path + "api/v1/commands", headers=headers(profile, csrf),
                                   json=state["context"].body)
            assert response.status_code == 202, response.text
            replay = client.post(profile.base_path + "api/v1/commands", headers=headers(profile, csrf),
                                 json=state["context"].body)
            assert replay.status_code == 202 and replay.json() == response.json()
            assert delivered.wait(3), errors
            assert state["worker_command"] == state["context"].body["command_id"]
            with application.state.domain_store._connection() as db:
                assert db.execute("SELECT count(*) FROM api_commands").fetchone()[0] == 1
    finally:
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
    assert errors == []


def test_missing_runtime_resolver_is_explicit_after_real_login(tmp_path):
    from app.tests.test_server_api_v1 import command_payload
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        response = client.post(profile.base_path + "api/v1/commands", headers=headers(profile, csrf), json=command_payload())
        assert response.status_code == 503 and response.json()["code"] == "dependency_unavailable"
        with application.state.domain_store._connection() as db:
            assert db.execute("SELECT count(*) FROM api_commands").fetchone()[0] == 0


def test_root_and_work_mounts_must_be_separate_before_store_write(tmp_path):
    _profile, _, arguments = configured(tmp_path)
    with pytest.raises(ValueError):
        create_app(tmp_path / "root", **arguments)
    assert set(os.listdir(tmp_path / "root")) == {"manifest.json", "root.key"}


def test_main_uses_required_config_and_fixed_internal_listener(tmp_path, monkeypatch, capsys):
    import sys

    import uvicorn

    from app import server
    profile, _, arguments = configured(tmp_path)
    path = tmp_path / "deployment.json"
    path.write_text(json.dumps(arguments["deployment_config"]))
    called = []
    def serve(application, **options):
        called.append(options)
        with TestClient(application, base_url=profile.http_origin) as client:
            assert client.get(profile.base_path + "health").status_code == 200
    monkeypatch.setattr(uvicorn, "run", serve)
    monkeypatch.setattr(sys, "argv", ["app.server", "--data-dir", str(tmp_path / "data"),
        "--deployment-config", str(path), "--session-root-dir", str(tmp_path / "root"),
        "--expected-uid", str(os.getuid()), "--expected-gid", str(os.getgid())])
    server.main()
    assert called == [{"host": "0.0.0.0", "port": 8080, "workers": 1, "reload": False, "proxy_headers": False,
                           "forwarded_allow_ips": "", "access_log": False}]
    assert capsys.readouterr().out == ""


def test_expired_observation_cannot_be_reversed_by_clock_rollback(tmp_path, monkeypatch):
    from app.services import owner_auth
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        bootstrap_client(client, profile, capability)
        actual = time.time_ns
        monkeypatch.setattr(owner_auth.time, "time_ns", lambda: actual() + 13 * 3600 * 1000000000)
        assert client.get(profile.base_path + "session", headers=headers(profile)).status_code == 401
        monkeypatch.setattr(owner_auth.time, "time_ns", actual)
        assert client.get(profile.base_path + "session", headers=headers(profile)).status_code == 401


def test_corrupt_private_state_is_closed_unavailable_with_security_headers(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        bootstrap_client(client, profile, capability)
        with sqlite3.connect(application.state.store.path) as db:
            db.execute("UPDATE owner_auth_accounts SET hash='corrupt'")
        response = client.get(profile.base_path + "session", headers=headers(profile))
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["code"] == "unavailable"


@pytest.mark.parametrize("stage,claimed,owned", [("before_claim_commit", False, False),
    ("after_claim_commit", True, False), ("before_owner_commit", True, False), ("after_owner_commit", True, True)])
def test_owned_child_exit_preserves_exact_bootstrap_commit(tmp_path, stage, claimed, owned):
    import subprocess
    import sys
    profile, capability, arguments = configured(tmp_path)
    # Child only opens this test's explicit synthetic root and store; no listener/provider is started.
    script = '''
import json,os,sys
from app.server import create_app
from app.services import owner_auth_storage as storage
base,config,stage,capability=sys.argv[1:]
app=create_app(base+'/data',deployment_config=json.loads(config),session_root_dir=base+'/root',expected_uid=os.getuid(),expected_gid=os.getgid())
auth=app.state.owner_authority
original_audit=storage.audit
def audit(db,kind,entity,now):
    original_audit(db,kind,entity,now)
    if (stage=='before_claim_commit' and kind=='claim') or (stage=='before_owner_commit' and kind=='owner'):
        os._exit(73)
storage.audit=audit
if stage=='after_claim_commit':
    auth._hash=lambda password: os._exit(73)
if stage=='after_owner_commit':
    auth._publish=lambda row: os._exit(73)
auth.bootstrap(login_name='owner',password='synthetic owner passphrase',raw_capability_b64u=capability,source_key='owned-child')
os._exit(74)
'''
    result = subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path), json.dumps(arguments["deployment_config"]), stage, capability],
                            capture_output=True, timeout=10, check=False)
    assert result.returncode == 73, result.stderr.decode()
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        with reopened.state.domain_store._connection() as db:
            claim = db.execute("SELECT state FROM owner_auth_bootstrap_claims").fetchone()[0]
            assert claim == ("completed" if owned else "consumed" if claimed else "available")
            assert db.execute("SELECT count(*) FROM owner_auth_accounts").fetchone()[0] == int(owned)
            assert db.execute("SELECT count(*) FROM owner_auth_sessions").fetchone()[0] == int(owned)
        if owned:
            response = client.post(profile.base_path + "session/login", headers=headers(profile),
                                   json={"login_name": "owner", "password": "synthetic owner passphrase"})
            assert response.status_code == 200


def test_close_keeps_serving_lock_until_running_native_hash_ends(tmp_path, monkeypatch):
    from threading import Event, Thread

    from app.services.owner_admission import AdmissionRejected, ServingLock
    from app.services.owner_auth import OwnerAuthError
    _profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    authority = application.state.owner_authority
    entered, release, closed = Event(), Event(), Event()
    failures = []
    original = authority._hash
    def native(password):
        entered.set()
        assert release.wait(3)
        return original(password)
    monkeypatch.setattr(authority, "_hash", native)
    def bootstrap():
        try:
            authority.bootstrap(login_name="owner", password="synthetic owner passphrase",
                                raw_capability_b64u=capability, source_key="owned-native")
        except OwnerAuthError as error:
            failures.append(error.code)
    worker = Thread(target=bootstrap)
    worker.start()
    assert entered.wait(3)
    def close():
        authority.close()
        closed.set()
    closer = Thread(target=close)
    closer.start()
    try:
        assert not closed.wait(0.03)
        with pytest.raises(AdmissionRejected):
            ServingLock(tmp_path / "data", expected_uid=os.getuid(), expected_gid=os.getgid())
    finally:
        release.set()
        worker.join(3)
        closer.join(3)
        application.state.store.close_verified_handles()
    assert not worker.is_alive() and not closer.is_alive()
    assert closed.is_set() and failures == ["unavailable"]
    ServingLock(tmp_path / "data", expected_uid=os.getuid(), expected_gid=os.getgid()).close()


def test_same_writer_revision_cas_rejects_stale_snapshot(tmp_path):
    from app.services import owner_auth_storage as storage
    profile, _, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin):
        domain = application.state.domain_store
        with domain._connection(write=True) as db:
            row = db.execute("SELECT * FROM owner_auth_control").fetchone()
            updated = storage.update(db, "control", row, {"clock_floor": row["clock_floor"] + 1}, identity="singleton")
            assert updated["revision"] == row["revision"] + 1
            with pytest.raises(storage.AuthStorageError):
                storage.update(db, "control", row, {"clock_floor": row["clock_floor"] + 2}, identity="singleton")
        with domain._connection() as db:
            row2 = db.execute("SELECT * FROM owner_auth_control").fetchone()
            assert row2["revision"] == updated["revision"]
            assert row2["clock_floor"] == updated["clock_floor"]


@pytest.mark.parametrize("method,path,body", [("GET", "api/v1/snapshot?unexpected=1", None),
    ("GET", "api/v1/events?limit=1&limit=2", None), ("GET", "api/v1/events?event_type=made.up", None),
    ("GET", "api/v1/events?limit=%FF", None), ("POST", "api/v1/commands", b'{"command_id":true}')])
def test_malformed_work_wire_never_reaches_authentication(tmp_path, monkeypatch, method, path, body):
    from app.services.owner_auth import OwnerAuthError
    profile, _, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    def forbidden(*args, **kwargs):
        raise OwnerAuthError("access_denied")
    monkeypatch.setattr(application.state.owner_authority, "authenticate_request", forbidden)
    with TestClient(application, base_url=profile.http_origin) as client:
        response = client.request(method, profile.base_path + path, content=body,
                                  headers={**headers(profile), "Content-Type": "application/json"})
        assert response.status_code == 400


@pytest.mark.parametrize("which", ["host", "origin", "cookie", "x-deeptwin-csrf", "content-length", "sec-fetch-site"])
def test_duplicate_security_headers_are_rejected_before_session_work(tmp_path, monkeypatch, which):
    profile, _, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    def forbidden(*args, **kwargs):
        pytest.fail("Duplicate security header reached authentication")
    monkeypatch.setattr(application.state.owner_authority, "authenticate_request", forbidden)
    with TestClient(application, base_url=profile.http_origin) as client:
        value = profile.http_origin.split("://", 1)[1] if which == "host" else "synthetic"
        response = client.get(profile.base_path + "session", headers=[(which, value), (which, value)])
        assert response.status_code == 400
        assert response.headers["cache-control"] == "no-store"


def test_https_does_not_trust_internal_http_or_forwarded_scheme(tmp_path):
    _profile, _, arguments = configured(tmp_path, "https")
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url="http://example.test") as client:
        response = client.get("/health", headers={"X-Forwarded-Proto": "https"})
        assert response.status_code == 403
        assert client.get("/health").status_code == 403


def test_composition_failure_releases_all_serving_ownership(tmp_path, monkeypatch):
    from app.api.router_composition import (
        FirstPartyRouteComposer,
        RouteCompositionError,
    )
    profile, _, arguments = configured(tmp_path)
    original = FirstPartyRouteComposer.compose
    def fail(self, application):
        raise RouteCompositionError("synthetic descriptor failure")
    monkeypatch.setattr(FirstPartyRouteComposer, "compose", fail)
    with pytest.raises(RouteCompositionError):
        create_app(tmp_path / "data", **arguments)
    monkeypatch.setattr(FirstPartyRouteComposer, "compose", original)
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin) as client:
        assert client.get(profile.base_path + "health").status_code == 200
        composition = reopened.state.route_composition
        assert composition.route_count == 20
        assert composition.contribution_ids == ("core-v1", "extension-candidates-v1", "run-approvals-v1",
                                                "runs-v1", "deployment-prepare-v1")
        assert composition.route_ids == ("events.read", "events.stream", "events.type", "snapshot.read",
            "commands.read", "commands.create", "extensions.candidates.create", "extensions.candidates.read",
            "runs.approvals.record", "runs.approvals.read",
            "runs.create", "runs.read", "runs.resume", "runs.cancel", "runs.recover",
            "deployment.requests.prepare", "deployment.requests.cancel", "deployment.requests.read",
            "deployment.requests.receipts.import", "deployment.requests.consume")


def test_live_session_root_pin_rejects_a_different_valid_pair(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        bootstrap_client(client, profile, capability)
    initialize_session_root(tmp_path / "different-root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    arguments["session_root_dir"] = tmp_path / "different-root"
    from app.services.owner_auth import OwnerAuthError
    with pytest.raises(OwnerAuthError, match="unavailable"):
        create_app(tmp_path / "data", **arguments)


def test_login_preserves_other_sessions_and_csrf_is_profile_exact(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        first_cookie = dict(client.cookies)
        client.cookies.clear()
        response = client.post(profile.base_path + "session/login", headers=headers(profile),
                               json={"login_name": "owner", "password": "synthetic owner passphrase"})
        assert response.status_code == 200
        second_cookie = dict(client.cookies)
        assert second_cookie != first_cookie
        client.cookies.clear()
        client.cookies.update(first_cookie)
        assert client.get(profile.base_path + "session", headers=headers(profile)).status_code == 200
        assert client.head(profile.base_path + "session", headers=headers(profile)).content == b""
        assert client.post(profile.base_path + "session/logout", headers=headers(profile, "A" * 43),
                           json={"command_id": str(uuid4())}).status_code == 403
        assert client.post(profile.base_path + "session/logout", headers={**headers(profile), "X-CSRF-Token": csrf},
                           json={"command_id": str(uuid4())}).status_code == 403
        assert client.post(profile.base_path + "session/logout", headers=headers(profile, csrf),
                           json={"command_id": str(uuid4())}).status_code == 200
        client.cookies.clear()
        client.cookies.update(second_cookie)
        assert client.get(profile.base_path + "session", headers=headers(profile)).status_code == 200


def test_writer_admission_sees_uncommitted_revocation_not_an_earlier_read(tmp_path):
    from app.domain.store import _writer
    from app.services import owner_auth_storage as storage
    from app.services.owner_auth import OwnerAuthError
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        request = bound_request(application, client, profile, csrf)
        authority = application.state.owner_authority
        host = application.state.permission_host
        human = host.bind_human(request.session, expires_at=int(time.time()) + 600)
        with pytest.raises(RuntimeError, match="synthetic rollback"), _writer(), application.state.domain_store._connection(write=True) as db:
            row = db.execute("SELECT * FROM owner_auth_sessions WHERE session_id=?", (request.session.session_id,)).fetchone()
            storage.update(db, "sessions", row, {"revoked_at": time.time_ns() // 1000000}, identity="session_id")
            # An independent read cannot see this transaction's revocation.
            assert authority.authenticate_bound(request.session) is request.session.actor
            with pytest.raises(OwnerAuthError, match="unauthenticated"):
                application.state.root_commands._authenticated_actor(request, read=False, db=db)
            with pytest.raises(OwnerAuthError, match="unauthenticated"):
                host._principal(human, human=True, db=db)
            raise RuntimeError("synthetic rollback")
        assert client.get(profile.base_path + "session", headers=headers(profile)).status_code == 200


def test_queue_capacity_preserves_claim_and_post_consumption_timeout_does_not(tmp_path, monkeypatch):
    from app.services.owner_auth import OwnerAuthError
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    authority = application.state.owner_authority
    with TestClient(application, base_url=profile.http_origin):
        reservations = [authority._lane.reserve() for _ in range(4)]
        try:
            with pytest.raises(OwnerAuthError, match="capacity"):
                authority.bootstrap(login_name="owner", password="synthetic owner passphrase",
                                    raw_capability_b64u=capability, source_key="capacity")
            with application.state.domain_store._connection() as db:
                assert db.execute("SELECT state,attempts FROM owner_auth_bootstrap_claims").fetchone()[:] == ("available", 0)
        finally:
            for reservation in reservations:
                reservation.close()
        monkeypatch.setattr(authority._lane, "_timeout", 0.02)
        first = authority._lane.reserve()
        try:
            with pytest.raises(OwnerAuthError, match="capacity"):
                authority.bootstrap(login_name="owner", password="synthetic owner passphrase",
                                    raw_capability_b64u=capability, source_key="timeout")
        finally:
            first.close()
        with application.state.domain_store._connection() as db:
            assert db.execute("SELECT state,attempts FROM owner_auth_bootstrap_claims").fetchone()[:] == ("consumed", 1)
            assert db.execute("SELECT count(*) FROM owner_auth_accounts").fetchone()[0] == 0


def test_competing_valid_claims_have_one_hash_and_one_durable_owner(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app.services.owner_auth import OwnerAuthError
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    authority = application.state.owner_authority
    entered, release = Event(), Event()
    hashes = []
    original = authority._hash
    def hash_password(password):
        hashes.append(True)
        entered.set()
        assert release.wait(3)
        return original(password)
    monkeypatch.setattr(authority, "_hash", hash_password)
    values = {"login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": capability, "source_key": "competition"}
    with TestClient(application, base_url=profile.http_origin), ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(authority.bootstrap, **values)
        assert entered.wait(3)
        try:
            second = executor.submit(authority.bootstrap, **values)
            with pytest.raises(OwnerAuthError, match="setup_incomplete"):
                second.result(3)
        finally:
            release.set()
        exchange = first.result(3)
        assert authority.authenticate_bound(exchange.session).kind == "human"
        with application.state.domain_store._connection() as db:
            assert db.execute("SELECT count(*) FROM owner_auth_accounts").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM owner_auth_sessions").fetchone()[0] == 1
        assert hashes == [True]


@pytest.mark.parametrize("boundary", ["insert", "verify", "reopen"])
def test_authenticator_revision_requires_nonnull_predecessor(tmp_path, boundary):
    from app.services import owner_auth_storage as storage

    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        bootstrap_client(client, profile, capability)
        domain = application.state.domain_store
        with domain._connection(write=True) as db:
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            original = dict(db.execute("SELECT * FROM owner_auth_authenticators").fetchone())
            original.pop("hash")
            broken = {**original, "revision": 2, "previous_revision": None}
            if boundary == "insert":
                with pytest.raises(sqlite3.IntegrityError):
                    storage.insert(db, "authenticators", broken)
            else:
                # Simulate an already-corrupt row, with intact schema and row hash.
                # The normal writer must reject it; reopen must independently reject it.
                db.execute("PRAGMA ignore_check_constraints=ON")
                storage.insert(db, "authenticators", broken)
                db.execute("PRAGMA ignore_check_constraints=OFF")
        if boundary == "verify":
            with domain._connection() as db, pytest.raises(storage.AuthStorageError):
                storage.verify(db)
    if boundary == "reopen":
        with pytest.raises(storage.AuthStorageError):
            reopened = create_app(tmp_path / "data", **arguments)
            # Clean up if the regression returns an authority instead of rejecting.
            reopened.state.owner_authority.close()
            reopened.state.store.close_verified_handles()


def test_authenticator_explicit_previous_revision_survives_reopen(tmp_path):
    from app.services import owner_auth_storage as storage

    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        bootstrap_client(client, profile, capability)
        with application.state.domain_store._connection(write=True) as db:
            original = dict(db.execute("SELECT * FROM owner_auth_authenticators").fetchone())
            original.pop("hash")
            storage.insert(db, "authenticators", {**original, "revision": 2, "previous_revision": 1})
            storage.verify(db)
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin), reopened.state.domain_store._connection() as db:
        storage.verify(db)
        assert [tuple(row) for row in db.execute(
            "SELECT revision,previous_revision FROM owner_auth_authenticators ORDER BY revision"
        )] == [(1, None), (2, 1)]


@pytest.mark.parametrize("mode", ["local", "https"])
def test_real_auth_secrets_stay_out_of_ordinary_projections_and_logs(tmp_path, mode, caplog, capsys):
    import logging

    from app.domain.refs import EntityRef

    caplog.set_level(logging.DEBUG)
    profile, capability, arguments = configured(tmp_path, mode)
    root_bytes = (tmp_path / "root" / "root.key").read_bytes()
    password = 'Synthetic owner "password" \\ newline\n한글 canary'
    secrets = [root_bytes, repr(root_bytes).encode(), root_bytes.hex().encode(),
               urlsafe_b64encode(root_bytes).rstrip(b"="), password.encode(), capability.encode()]
    secrets.extend((repr(password).encode(), json.dumps(password).encode(),
                    json.dumps(password, ensure_ascii=False).encode()))
    projections = []

    def remember_response(response, *, establishment=False, csrf_read=False):
        # Only the exact cookie establishment and CSRF response fields are allowed.
        body = response.json()
        if establishment or csrf_read:
            csrf = body.pop("csrf_token")
            secrets.append(csrf.encode())
            assert body == {"state": "authenticated"}
        response_headers = dict(response.headers)
        if establishment:
            cookie = response_headers.pop("set-cookie")
            token = response.cookies[application.state.owner_authority.cookie_name]
            assert token in cookie
            secrets.append(token.encode())
        projections.extend((body, response_headers))

    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        authority = application.state.owner_authority
        created = client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
            "login_name": "owner", "password": password, "raw_capability_b64u": capability})
        assert created.status_code == 201
        remember_response(created, establishment=True)
        session = client.get(profile.base_path + "session", headers=headers(profile))
        assert session.status_code == 200
        remember_response(session, csrf_read=True)
        replay = client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
            "login_name": "owner", "password": password, "raw_capability_b64u": capability})
        assert replay.status_code == 409
        remember_response(replay)
        denied = client.post(profile.base_path + "session/login", headers=headers(profile), json={
            "login_name": "owner", "password": password + " wrong"})
        assert denied.status_code == 401
        remember_response(denied)
        secrets.append((password + " wrong").encode())

        # An actual service-issued exchange, not a constructed identity, exercises repr.
        exchange = authority.login(login_name="owner", password=password, source_key="synthetic-repr")
        secrets.extend((exchange.token_b64u.encode(), exchange.csrf_token.encode()))
        projections.extend((repr(exchange), repr(exchange.session), repr(authority),
                            repr(authority._root), dict(authority._root.receipt)))
        logged_in = client.post(profile.base_path + "session/login", headers=headers(profile), json={
            "login_name": "owner", "password": password})
        assert logged_in.status_code == 200
        remember_response(logged_in, establishment=True)
        request = bound_request(application, client, profile, logged_in.json()["csrf_token"])
        projections.append(repr(request))
        logout = client.post(profile.base_path + "session/logout",
            headers=headers(profile, logged_in.json()["csrf_token"]), json={"command_id": str(uuid4())})
        assert logout.status_code == 200
        remember_response(logout)
        revoked = client.get(profile.base_path + "session", headers=headers(profile))
        assert revoked.status_code == 401
        remember_response(revoked)

        # This independently issued session survives logout of the other browser token.
        client.cookies.set(authority.cookie_name, exchange.token_b64u)
        work = application.state.store.create_work("Neutral synthetic work; no authentication material")
        projections.extend((work, application.state.store.get_work(work["id"]),
                            application.state.store.list_work(), application.state.store.get_revision(work["id"], 1)))
        snapshot = client.get(profile.base_path + "api/v1/snapshot", headers=headers(profile))
        assert snapshot.status_code == 200
        assert snapshot.json()["state"]["works"] == [{"id": work["id"], "revision": 1, "file_count": 0}]
        remember_response(snapshot)
        events = client.get(profile.base_path + "api/v1/events", headers=headers(profile))
        assert events.status_code == 200
        assert {event["event_type"] for event in events.json()["events"]} == {
            "owner.created", "session.created", "session.revoked"}
        remember_response(events)
        head = client.head(profile.base_path + "api/v1/snapshot", headers=headers(profile))
        assert head.status_code == 200 and head.content == b""
        projections.append(dict(head.headers))
        with application.state.domain_store._connection() as db:
            secrets.extend(row[0].encode() for row in db.execute("SELECT encoded_hash FROM owner_auth_authenticators"))
            secrets.extend(row[0].encode() for row in db.execute("SELECT token_digest FROM owner_auth_sessions"))
            secrets.append(db.execute("SELECT verifier FROM owner_auth_bootstrap_claims").fetchone()[0].encode())
            refs = [EntityRef(*row) for row in db.execute("SELECT kind,id,version,sha256 FROM domain_records")]
            assert len(refs) >= 5
            ordinary_events = [dict(row) for row in db.execute("SELECT * FROM api_event_envelopes")]
            assert ordinary_events
            projections.extend(ordinary_events)
        for ref in refs:
            record = application.state.domain_store.get(ref)
            projections.extend((record.body, record.body_bytes, repr(record)))

    captured = capsys.readouterr()
    assert any("/session/bootstrap" in record.getMessage() for record in caplog.records)
    projections.extend((caplog.text, [record.getMessage() for record in caplog.records],
                        captured.out, captured.err))

    def assert_no_secret(value):
        # Decoded values and byte/encoded representations both matter: quoting a
        # password in JSON must not make the check blind to an accidental leak.
        if isinstance(value, dict):
            for key, item in value.items():
                assert_no_secret(key)
                assert_no_secret(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                assert_no_secret(item)
        else:
            encoded = value if isinstance(value, bytes) else str(value).encode()
            for secret in secrets:
                assert secret not in encoded, "Authentication secret entered an ordinary projection"
    assert_no_secret(projections)


@pytest.mark.parametrize("category", ["credentials", "session_root", "owner_auth_migrations",
    "owner_auth_control", "owner_auth_bootstrap_claims", "owner_auth_accounts", "owner_auth_authenticators",
    "owner_auth_sessions", "owner_auth_commands", "owner_auth_audit"])
def test_private_auth_is_not_an_available_export_category(category):
    from app.operations.export import ExportError, create_export_request
    from app.tests.test_export import request_value

    # Existing request admission only: no DB collector or archive endpoint exists.
    accepted = create_export_request(request_value(selected_categories=["events", "artifacts_metadata"]))
    assert accepted.selected_categories == ("artifacts_metadata", "events")
    with pytest.raises(ExportError, match="selected categories"):
        create_export_request(request_value(selected_categories=["events", category]))
