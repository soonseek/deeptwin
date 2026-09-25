"""T090 production wiring: the supported app factory composes the credential routes.

- Named (``credential_gateway=CredentialGatewayConfiguration``): the factory opens the
  0600 command ledger in the instance state directory and a frame-only client over the
  verified ``cp-provider`` connect and handshake. The real-UDS test runs the actual
  ``create_app`` in a child under the control plane's numeric identity against a
  gateway child under the provider identity (kernel SO_PEERCRED on both sides) and
  drives HTTP create -> GET -> rotate -> GET -> delete -> GET. Root on Linux only.
- Not named: the routes are composed but unbound and answer ``503
  dependency_unavailable`` with zero effect (no ledger file, no connect attempt).
- Named wrongly: the start fails before anything is served.
"""

from __future__ import annotations

import json
import os
import select
import socket
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.credential_wiring import (
    LEDGER_NAME,
    SCHEMA,
    CredentialGatewayConfiguration,
)
from app.server import create_app
from app.tests.test_credential_gateway_peercred import (  # noqa: F401 - the `base` fixture
    CONTROL_GID,
    CONTROL_UID,
    PAIR_GID,
    REPOSITORY,
    _child_environment,
    _finish,
    assert_no_secret_bytes,
    base,
    finish_gateway,
    journal_counts,
    start_gateway,
)
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers
from app.workers import broker, gateway_channel, listener

FIRST = "sk-synthetic-startup-first-0001"
SECOND = "sk-synthetic-startup-second-0002"
CHILD_SECONDS = 90

real_uds = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED")
    or not hasattr(os, "geteuid") or os.geteuid() != 0
    or not Path("/proc/self/fd").is_dir(),
    reason="real SO_PEERCRED startup needs Linux, root and /proc/self/fd",
)


def connection(handle, state, revision):
    """The GET projection of a provider connection's binding head (no catalog yet)."""
    return {"provider": "claude", "state": state, "handle": handle, "binding_revision": revision,
            "catalog": "absent", "model_choice": "absent", "gateway_head": "applied",
            "models": [], "chosen_model": None}


def _no_connect(monkeypatch):
    def refuse(*_args, **_kwargs):
        pytest.fail("an unbound credential route attempted a gateway connection")

    monkeypatch.setattr(listener, "connect_authenticated", refuse)
    monkeypatch.setattr(broker, "connect_verified", refuse)


def _write_headers(profile, csrf):
    return {**headers(profile, csrf), "Content-Type": "application/json"}


def test_an_unnamed_gateway_composes_unbound_routes_that_answer_503_with_zero_effect(tmp_path, monkeypatch):
    _no_connect(monkeypatch)
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    path = profile.base_path + "api/v1/credentials"
    with TestClient(application, base_url=profile.http_origin) as client:
        composition = application.state.route_composition
        assert "credentials-v1" in composition.contribution_ids
        assert application.state.credential_attachment is None
        # the routes stay behind the owner session
        assert client.get(path, headers=headers(profile)).status_code == 401
        csrf = bootstrap_client(client, profile, capability)
        responses = [
            client.get(path, headers=headers(profile)),
            client.post(path, headers=_write_headers(profile, csrf), content=json.dumps(
                {"intent_id": str(uuid4()), "provider": "claude", "secret": FIRST})),
            client.request("DELETE", f"{path}/{'0' * 32}", headers=_write_headers(profile, csrf),
                           content=json.dumps({"intent_id": str(uuid4())})),
        ]
        for response in responses:
            assert response.status_code == 503, response.text
            assert response.json()["code"] == "dependency_unavailable"
            assert FIRST not in response.text
    assert not (tmp_path / "data" / LEDGER_NAME).exists()
    for item in tmp_path.rglob("*"):
        if item.is_file():
            assert FIRST.encode() not in item.read_bytes(), item


def test_a_named_endpoint_that_is_not_the_verified_pair_root_fails_the_start(tmp_path, monkeypatch):
    _no_connect(monkeypatch)
    _profile, _capability, arguments = configured(tmp_path)
    wrong = CredentialGatewayConfiguration(pair_root=str(tmp_path / "cp-provider"),
                                           requester_boot_id="control-boot")
    with pytest.raises(ValueError, match="verified pair root"):
        create_app(tmp_path / "data", **arguments, credential_gateway=wrong)
    assert not (tmp_path / "data" / LEDGER_NAME).exists()
    with pytest.raises(ValueError):
        create_app(tmp_path / "data", **arguments, credential_gateway={"pair_root": "/run"})


def test_a_named_fixed_endpoint_binds_the_ledger_and_the_fixed_client(tmp_path, monkeypatch):
    _no_connect(monkeypatch)
    _profile, _capability, arguments = configured(tmp_path)
    fixed_root, _spec = gateway_channel.gateway_channel()
    named = CredentialGatewayConfiguration(pair_root=str(fixed_root.pair_root), requester_boot_id="control-boot")
    application = create_app(tmp_path / "data", **arguments, credential_gateway=named)
    with TestClient(application):
        attachment = application.state.credential_attachment
        assert attachment.ledger_path == (tmp_path / "data" / LEDGER_NAME).absolute()
        assert attachment.ledger_path.stat().st_mode & 0o777 == 0o600
        assert type(attachment.client).__name__ == "CredentialGatewayClient"


def test_the_attachment_configuration_is_exact():
    good = {"schema": SCHEMA, "pair_root": "/run/deeptwin/ipc/cp-provider", "requester_boot_id": "control-boot"}
    assert CredentialGatewayConfiguration.from_mapping(good).requester_boot_id == "control-boot"
    for broken in ({**good, "extra": 1}, {**good, "schema": "other"}, {**good, "pair_root": "relative"},
                   {**good, "pair_root": "/run/../etc"}, {**good, "requester_boot_id": ""},
                   {k: v for k, v in good.items() if k != "schema"}):
        with pytest.raises(ValueError):
            CredentialGatewayConfiguration.from_mapping(broken)


def test_main_reads_the_optional_attachment_file(tmp_path, monkeypatch):
    import uvicorn

    from app import server
    _profile, _capability, arguments = configured(tmp_path)
    deployment = tmp_path / "deployment.json"
    deployment.write_text(json.dumps(arguments["deployment_config"]))
    attachment = tmp_path / "credential-gateway.json"
    fixed_root, _spec = gateway_channel.gateway_channel()
    attachment.write_text(json.dumps({"schema": SCHEMA, "pair_root": str(fixed_root.pair_root),
                                      "requester_boot_id": "control-boot"}))
    seen = []
    monkeypatch.setattr(server, "create_app", lambda *args, **kwargs: seen.append(kwargs) or object())
    monkeypatch.setattr(uvicorn, "run", lambda *args, **kwargs: None)
    argv = ["app.server", "--data-dir", str(tmp_path / "data"), "--deployment-config", str(deployment),
            "--session-root-dir", str(tmp_path / "root"), "--expected-uid", str(os.getuid()),
            "--expected-gid", str(os.getgid())]
    monkeypatch.setattr(sys, "argv", argv)
    server.main()
    monkeypatch.setattr(sys, "argv", [*argv, "--credential-gateway-config", str(attachment)])
    server.main()
    assert seen[0]["credential_gateway"] is None
    assert seen[1]["credential_gateway"] == CredentialGatewayConfiguration(
        pair_root=str(fixed_root.pair_root), requester_boot_id="control-boot")


def _run_app_child(directory, steps):
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "app.tests.support.credential_app_child"],
        cwd=REPOSITORY, env=_child_environment(), user=CONTROL_UID, group=CONTROL_GID,
        extra_groups=[PAIR_GID], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdin.write(json.dumps({"base": str(directory), "steps": steps}).encode())
    process.stdin.close()
    readable, _, _ = select.select([process.stdout], [], [], CHILD_SECONDS)
    if not readable:
        process.kill()
        pytest.fail("app child produced no output in time")
    line = process.stdout.readline()
    if not line:
        process.wait(5)
        pytest.fail("app child exited early: " + process.stderr.read().decode(errors="replace")[-3000:])
    _finish(process)
    return json.loads(line)


@real_uds
def test_the_supported_factory_serves_create_list_rotate_delete_over_the_real_socket(base):  # noqa: F811
    control = base / "control"
    control.mkdir(mode=0o700)
    os.chown(control, CONTROL_UID, CONTROL_GID)
    # the HTTP flow makes exactly seven gateway calls: create store_at + bind_head, rotate
    # store_at + bind_head + superseded retire, delete bind_head (the revoked head) + retire;
    # the status reads make none
    server = start_gateway(base, sessions=7)
    try:
        result = _run_app_child(base, [
            {"op": "store", "intent_id": str(uuid4()), "secret": FIRST},
            {"op": "list"},
            {"op": "store", "intent_id": str(uuid4()), "secret": SECOND, "rotate": True},
            {"op": "list"},
            {"op": "delete", "intent_id": str(uuid4())},
            {"op": "list"},
        ])
    finally:
        summary = finish_gateway(server)
    assert result["identity"] == [CONTROL_UID, CONTROL_GID, [PAIR_GID]]
    created, listed, rotated, relisted, deleted, final = result["steps"]
    handle = created["body"]["handle"]
    assert created == {"status": 201, "body": {"handle": handle, "provider": "claude", "state": "stored_unbound"}}
    assert listed == {"status": 200, "body": {
        "credentials": [{"handle": handle, "provider": "claude", "state": "stored_unbound",
                         "provider_revocation": "not_performed"}],
        "connections": [connection(handle, "bound", 1)], "pending_acts": []}}
    assert rotated == {"status": 201, "body": {"handle": handle, "provider": "claude", "state": "stored_unbound"}}
    # the rotation moved the binding by CAS to revision 2; the credential entry is unchanged
    assert relisted == {"status": 200, "body": {**listed["body"],
                                                "connections": [connection(handle, "bound", 2)]}}
    assert deleted == {"status": 200, "body": {"handle": handle, "state": "cleanup_pending",
                                               "provider_revocation": "not_performed"}}
    assert final == {"status": 200, "body": {
        "credentials": [{"handle": handle, "provider": "claude", "state": "cleanup_pending",
                         "provider_revocation": "not_performed"}],
        "connections": [connection(handle, "revoked_pending_erasure", 3)], "pending_acts": []}}
    assert result["ledger"] == ["0o600", CONTROL_UID]
    assert result["vault_modules"] == []  # the control plane never loaded the vault
    assert summary["outcomes"] == ["served"] * 7
    assert summary["health"]["cleanup_pending"] == 2 and summary["health"]["stored_unbound"] == 0
    assert journal_counts(base) == (2, 2, 2, 2)
    assert_no_secret_bytes(base, FIRST.encode(), SECOND.encode())
