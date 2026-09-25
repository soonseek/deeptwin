"""Owner sessions across an owner recovery: the restricted reconciliation start (recovery port
design §5, approved 2026-09-24).

An instance with a live owner session, a service client, a pending gate approval and an open
run consent is recovered N→N+1: maintenance advances the stopped root from a signed
receipt, the configuration names the new verifier, and the next start runs one DB
transaction. Every earlier authority must then actually refuse, history must remain, and
bootstrap/login must open only after the commit. Keys are generated in-test (offline).
"""

import os
import sqlite3
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.refs import EntityRef, canonical_json
from app.domain.schemas import Actor
from app.runtime.gates import GATE_REQUEST_COMMAND, gate_request_identity
from app.server import create_app
from app.services.owner_auth import OwnerAuthError, PersistentOwnerAuthority
from app.services.run_approvals import PersistentRunApprovals, RunApprovalError
from app.services.run_consents import RunConsentError, consent_current
from app.services.service_clients import (
    PersistentServiceClientRegistry,
    ServiceClientDenied,
)
from app.tests.recovery_fixture import Recovery
from app.tests.test_graph_execution import linear_graph
from app.tests.test_run_consents import run_command
from app.tests.test_runs_api import Executor, consent_for, graph_record, owner_app, post
from app.tests.test_web_owner_integration import bound_request, configured, headers

PASSWORD = "synthetic owner passphrase"
NEW_PASSWORD = "another synthetic owner passphrase"


def registry(store, owner_id, token):
    actor = Actor(owner_id, "human", "local_session")
    return PersistentServiceClientRegistry(
        store, verify_owner=lambda candidate: actor if candidate is token else None,
        verify_recovery=lambda _candidate: False, clock=lambda: 1_000, random_bytes=os.urandom)


def epoch_one(tmp_path):
    """A live epoch-1 instance: owner session, service client, pending gate, open consent."""
    with owner_app(tmp_path, Executor()) as subject:
        authority = subject.app.state.owner_authority
        with subject.domain._connection() as db:
            owner_id = db.execute("SELECT owner_id FROM owner_auth_accounts").fetchone()[0]
        graph = graph_record(subject, linear_graph())
        consent = consent_for(subject, graph)
        # the ledger's own durable ask for one human gate of some run
        ledger = subject.app.state.runtime_ledger
        gate = {"run_id": str(uuid4()), "node_id": "review", "approval_scope": "publish"}
        with ledger._transaction(write=True) as db:
            ledger._record_command(db, gate_request_identity(**gate), GATE_REQUEST_COMMAND,
                                   canonical_json(gate), {**gate, "requested": True}, 1)
        token = object()
        clients = registry(subject.app.state.store, owner_id, token)
        issued = clients.issue(token, client_id=str(uuid4()), name="automation", scopes=("events.read",),
                               allowed_network_profile="portable_https", expires_at=2_000)
        assert clients.authenticate(issued.secret, network_profile="portable_https").client_id
        cookie = subject.client.cookies[authority.cookie_name]
        result = SimpleNamespace(owner_id=owner_id, graph=graph, consent=consent, gate=gate,
                                 secret=issued.secret, cookie=cookie, csrf=subject.csrf,
                                 cookie_name=authority.cookie_name, refs=subject.refs)
    profile, capability, arguments = configured(tmp_path)
    return SimpleNamespace(**vars(result), profile=profile, capability=capability, arguments=arguments)


def recovered_app(tmp_path, state, recovery):
    return create_app(tmp_path / "data", **recovery.arguments, recovery_trust_set=recovery.trust,
                      run_executor=Executor())


def rows(tmp_path, query):
    with sqlite3.connect(tmp_path / "data" / "intake.sqlite3") as db:
        return db.execute(query).fetchall()


def bootstrap(client, profile, capability, *, login_name="owner", password=NEW_PASSWORD):
    return client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
        "login_name": login_name, "password": password, "raw_capability_b64u": capability})


def login(client, profile, password, login_name="owner"):
    return client.post(profile.base_path + "session/login", headers=headers(profile),
                       json={"login_name": login_name, "password": password})


def test_every_earlier_authority_refuses_after_the_reconciliation_commits(tmp_path):
    state = epoch_one(tmp_path)
    recovery = Recovery(state.profile, state.arguments)
    recovery.advance()
    app = recovered_app(tmp_path, state, recovery)
    profile, path = state.profile, state.profile.base_path
    with TestClient(app, base_url=profile.http_origin) as client:
        domain, authority = app.state.domain_store, app.state.owner_authority
        # the old browser session and its CSRF token
        client.cookies.set(state.cookie_name, state.cookie)
        assert client.get(path + "session", headers=headers(profile)).status_code == 401
        assert client.post(path + "session/revoke-others", headers=headers(profile, state.csrf),
                           json={}).status_code in {401, 403}
        client.cookies.clear()
        # the old service-client bearer
        with pytest.raises(ServiceClientDenied):
            registry(app.state.store, state.owner_id, object()).authenticate(
                state.secret, network_profile="portable_https")
        # the pending gate approval is now an expired decision
        approvals = PersistentRunApprovals(domain, authority)
        expired = approvals.lookup(**state.gate)
        assert expired is not None and expired.decision == "expired"
        # the open consent is revoked
        with domain._connection() as db, pytest.raises(RunConsentError) as error:
            consent_current(domain, db, domain.roots(), EntityRef.from_dict(state.consent))
        assert error.value.code == "access_denied"
        # the old capability, the old password: nothing opens
        refused = bootstrap(client, profile, state.capability)
        assert refused.status_code == 401 and refused.json()["code"] == "credentials"
        assert login(client, profile, PASSWORD).status_code == 401
        assert client.get(path + "health").json() == {"state": "available", "owner": False, "setup": "available"}
        # the new capability re-binds the same owner actor on the next authenticator
        created = bootstrap(client, profile, recovery.capability)
        assert created.status_code == 201, created.text
        csrf = created.json()["csrf_token"]
        assert client.get(path + "health").json()["owner"] is True
        with domain._connection() as db:
            account = db.execute("SELECT owner_id,recovery_epoch,auth_epoch FROM owner_auth_accounts").fetchone()
            assert (account["owner_id"], account["recovery_epoch"], account["auth_epoch"]) == (state.owner_id, 2, 2)
            assert [tuple(row) for row in db.execute(
                "SELECT revision, revoked_at IS NULL FROM owner_auth_authenticators ORDER BY revision")] == [
                (1, 0), (2, 1)]
        # an expired gate cannot be approved later, a revoked consent starts no run
        request = bound_request(app, client, profile, csrf)
        with pytest.raises(RunApprovalError, match="conflict"):
            approvals.record(request, {"schema_version": "run-approval-command-v1", "command_id": str(uuid4()),
                                       **state.gate, "decision": "approved"})
        subject = SimpleNamespace(client=client, profile=profile, csrf=csrf, refs=state.refs,
                                  path=path + "api/v1/runs")
        started = post(subject, run_command(subject, state.graph, state.consent))
        assert started.status_code == 403 and started.json()["code"] == "access_denied"
        # login opens with the new password only
        client.cookies.clear()
        assert login(client, profile, PASSWORD).status_code == 401
        assert login(client, profile, NEW_PASSWORD).status_code == 200
    # historical evidence stays: epoch-1 sessions and control rows are kept, not deleted
    assert rows(tmp_path, "SELECT epoch, previous_epoch FROM owner_auth_control ORDER BY epoch") == [(1, None), (2, 1)]
    assert rows(tmp_path, "SELECT count(*) FROM owner_auth_sessions WHERE recovery_epoch=1 "
                          "AND revoked_at IS NOT NULL")[0][0] >= 1
    assert rows(tmp_path, "SELECT epoch, state FROM owner_auth_bootstrap_claims ORDER BY epoch") == [
        (1, "completed"), (2, "completed")]
    events = [row[0] for row in rows(tmp_path, "SELECT event_type FROM api_event_envelopes ORDER BY sequence")]
    assert events.count("auth.recovery_completed") == 1
    assert rows(tmp_path, "SELECT count(*) FROM service_client_heads WHERE state='active'") == [(0,)]


def test_bootstrap_and_login_open_only_after_the_reconciliation_commits(tmp_path, monkeypatch):
    from app.api.session_routes import create_session_router

    state = epoch_one(tmp_path)
    recovery = Recovery(state.profile, state.arguments)
    recovery.advance()
    original = PersistentOwnerAuthority.reconcile_recovery
    observed = []

    def checked(self):
        assert self.reconciling
        for attempt in (self.setup_state,
                        lambda: self.login(login_name="owner", password=PASSWORD, source_key="test"),
                        lambda: self.bootstrap(login_name="owner", password=NEW_PASSWORD,
                                               raw_capability_b64u=recovery.capability, source_key="test")):
            with pytest.raises(OwnerAuthError) as error:
                attempt()
            assert error.value.code == "unavailable"
        probe = FastAPI()
        probe.include_router(create_session_router(self))
        observed.append(TestClient(probe).get("/health").json())
        # the database still says epoch 1 until the one transaction commits
        assert rows(tmp_path, "SELECT max(epoch) FROM owner_auth_control") == [(1,)]
        original(self)
        assert not self.reconciling

    monkeypatch.setattr(PersistentOwnerAuthority, "reconcile_recovery", checked)
    app = recovered_app(tmp_path, state, recovery)
    assert observed == [{"state": "recovery_reconciliation"}]
    with TestClient(app, base_url=state.profile.http_origin) as client:
        assert bootstrap(client, state.profile, recovery.capability).status_code == 201


def test_a_crash_before_the_commit_is_reconciled_again_by_the_next_start(tmp_path, monkeypatch):
    from app.services import deployment_control

    state = epoch_one(tmp_path)
    recovery = Recovery(state.profile, state.arguments)
    recovery.advance()
    real = deployment_control.reconcile_recovery_in_transaction

    def crash(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError("process ended between the writes and the commit")

    monkeypatch.setattr(deployment_control, "reconcile_recovery_in_transaction", crash)
    with pytest.raises(Exception):  # noqa: B017 - the start fails closed whatever it reports
        recovered_app(tmp_path, state, recovery)
    # nothing of the transaction survived: epoch 1 still current, nothing revoked yet
    assert rows(tmp_path, "SELECT max(epoch) FROM owner_auth_control") == [(1,)]
    assert rows(tmp_path, "SELECT count(*) FROM owner_auth_sessions WHERE revoked_at IS NULL")[0][0] >= 1
    assert rows(tmp_path, "SELECT count(*) FROM api_event_envelopes WHERE event_type='auth.recovery_completed'") == [(0,)]
    monkeypatch.setattr(deployment_control, "reconcile_recovery_in_transaction", real)
    app = recovered_app(tmp_path, state, recovery)
    with TestClient(app, base_url=state.profile.http_origin) as client:
        assert bootstrap(client, state.profile, recovery.capability).status_code == 201
    # a later start is an ordinary equal-epoch start: no second reconciliation
    again = create_app(tmp_path / "data", **recovery.arguments, run_executor=Executor())
    with TestClient(again, base_url=state.profile.http_origin) as client:
        assert login(client, state.profile, NEW_PASSWORD).status_code == 200
    assert rows(tmp_path, "SELECT count(*) FROM owner_auth_control") == [(2,)]
    assert rows(tmp_path, "SELECT count(*) FROM api_event_envelopes WHERE event_type='auth.recovery_completed'") == [(1,)]


def test_a_rolled_back_or_skipped_configuration_and_a_missing_trust_set_fail_closed(tmp_path):
    from app.operations.setup import build_recovered_configuration

    state = epoch_one(tmp_path)
    recovery = Recovery(state.profile, state.arguments)
    recovery.advance()
    before = rows(tmp_path, "SELECT * FROM owner_auth_control")
    # the root is at 2: the old epoch-1 configuration is a rollback
    with pytest.raises(Exception):  # noqa: B017
        create_app(tmp_path / "data", **state.arguments, run_executor=Executor())
    # a configuration naming epoch 3 skips an epoch the root never reached
    skipped = {**recovery.arguments, "deployment_config": build_recovered_configuration(
        profile=state.profile, verifier_b64u=recovery.verifier, recovery_epoch=3)}
    with pytest.raises(Exception):  # noqa: B017
        create_app(tmp_path / "data", **skipped, recovery_trust_set=recovery.trust, run_executor=Executor())
    # no trust set, or one that does not hold the signing key: no plaintext fallback
    with pytest.raises(Exception):  # noqa: B017
        create_app(tmp_path / "data", **recovery.arguments, run_executor=Executor())
    other = Recovery(state.profile, {**state.arguments, "session_root_dir": state.arguments["session_root_dir"]},
                     epoch=2)
    with pytest.raises(Exception):  # noqa: B017
        create_app(tmp_path / "data", **recovery.arguments, recovery_trust_set=other.trust,
                   run_executor=Executor())
    # a configuration whose verifier is not the one the receipt bound
    wrong = {**recovery.arguments, "deployment_config": build_recovered_configuration(
        profile=state.profile, verifier_b64u=other.verifier, recovery_epoch=2)}
    with pytest.raises(Exception):  # noqa: B017
        create_app(tmp_path / "data", **wrong, recovery_trust_set=recovery.trust, run_executor=Executor())
    assert rows(tmp_path, "SELECT * FROM owner_auth_control") == before
    # the exact configuration and trust set still reconcile afterwards
    app = recovered_app(tmp_path, state, recovery)
    with TestClient(app, base_url=state.profile.http_origin) as client:
        assert bootstrap(client, state.profile, recovery.capability).status_code == 201
