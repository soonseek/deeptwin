"""The stopped-control-plane owner-recovery maintenance tool (`app/operations/maintenance_tool.py`).

Every case is offline. The signing stays outside the tool: `recovery_fixture` (tests only)
plays the holder of the recovery trust set, with Ed25519 keys generated in-test. A full
round trip ends with a real `create_app` start whose restricted reconciliation start must
actually have run: the old session, capability and password refuse, the new capability
sets the owner up again.
"""

import json
import os
import sqlite3
from base64 import urlsafe_b64encode
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.deployment.recovery_schema_exports import STAGE_ADAPTER
from app.domain.refs import canonical_json, parse_canonical
from app.operations import deployment_control as maintenance_tool
from app.operations.deployment_control import OwnerRecoveryError, open_maintenance
from app.operations.setup import derive_capability_verifier
from app.server import create_app
from app.tests.recovery_fixture import Signer, receipt_for, trust_v2
from app.tests.test_web_owner_integration import configured, headers

PASSWORD = "synthetic owner passphrase"
NEW_PASSWORD = "another synthetic owner passphrase"


def b64(raw):
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def bootstrap(client, profile, capability, password=PASSWORD):
    return client.post(profile.base_path + "session/bootstrap", headers=headers(profile), json={
        "login_name": "owner", "password": password, "raw_capability_b64u": capability})


def login(client, profile, password):
    return client.post(profile.base_path + "session/login", headers=headers(profile),
                       json={"login_name": "owner", "password": password})


def rows(tmp_path, query):
    with sqlite3.connect(tmp_path / "data" / "intake.sqlite3") as db:
        return db.execute(query).fetchall()


def served(tmp_path):
    """An epoch-1 instance that served once: an owner, a live browser session, stopped."""
    profile, capability, arguments = configured(tmp_path)
    (tmp_path / "config").mkdir(mode=0o700)
    config_path = tmp_path / "config" / "deployment.json"
    config_path.write_bytes(canonical_json(arguments["deployment_config"]))
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        assert bootstrap(client, profile, capability).status_code == 201
        cookie = client.cookies["deeptwin_session"]
    signer = Signer()
    return SimpleNamespace(profile=profile, capability=capability, arguments=arguments, config_path=config_path,
                           cookie=cookie, signer=signer, trust=trust_v2(profile, signer))


def tool(tmp_path, state):
    return open_maintenance(data_dir=tmp_path / "data", session_root_dir=tmp_path / "root",
                            deployment_config=state.config_path, work_dir=tmp_path / "work",
                            expected_uid=os.getuid(), expected_gid=os.getgid())


def new_capability():
    capability = b64(os.urandom(32))
    return capability, derive_capability_verifier(capability)


def configuration(state):
    return json.loads(state.config_path.read_bytes())


def start(tmp_path, state):
    return create_app(tmp_path / "data", deployment_config=configuration(state),
                      session_root_dir=tmp_path / "root", expected_uid=os.getuid(), expected_gid=os.getgid(),
                      recovery_trust_set=state.trust)


def prepared(tmp_path, state, verifier):
    with tool(tmp_path, state) as maintenance:
        result = maintenance_tool.prepare(maintenance, new_verifier=verifier)
    return result, (tmp_path / "work" / "requests" / (result["request_id"] + ".json")).read_bytes()


def imported(tmp_path, state, receipt, trust=None):
    with tool(tmp_path, state) as maintenance:
        return maintenance_tool.import_receipt(maintenance, receipt_bytes=receipt,
                                             trust_bytes=state.trust if trust is None else trust)


def refused(code, action):
    with pytest.raises(OwnerRecoveryError) as error:
        action()
    assert error.value.code == code


def root_epoch(tmp_path, state, epoch):
    with tool(tmp_path, state) as maintenance:
        return maintenance.root_generation(state.profile, epoch)


def assert_recovered_start(tmp_path, state, capability, *, epoch=2):
    app = start(tmp_path, state)
    profile, path = state.profile, state.profile.base_path
    with TestClient(app, base_url=profile.http_origin) as client:
        client.cookies.set("deeptwin_session", state.cookie)
        assert client.get(path + "session", headers=headers(profile)).status_code == 401
        client.cookies.clear()
        assert client.get(path + "health").json() == {
            "state": "available", "owner": False, "setup": "available", "recovered": True}
        assert bootstrap(client, profile, state.capability, NEW_PASSWORD).status_code == 401
        assert login(client, profile, PASSWORD).status_code == 401
        assert bootstrap(client, profile, capability, NEW_PASSWORD).status_code == 201
        assert client.get(path + "health").json()["owner"] is True
    assert rows(tmp_path, "SELECT max(epoch) FROM owner_auth_control") == [(epoch,)]


# ---- the round trip ----------------------------------------------------------------------

def test_cli_round_trip_then_the_app_start_reconciles(tmp_path, capsys):
    state = served(tmp_path)
    common = ["--data-dir", str(tmp_path / "data"), "--session-root-dir", str(tmp_path / "root"),
              "--deployment-config", str(state.config_path), "--work-dir", str(tmp_path / "work"),
              "--expected-uid", str(os.getuid()), "--expected-gid", str(os.getgid())]

    def cli(*args):
        code = maintenance_tool.run(list(args))
        return code, json.loads(capsys.readouterr().out)

    code, status = cli("status", *common)
    assert code == 0 and status == {"state": "status", "configuration_epoch": 1, "root_epoch": 1,
                                    "database_epoch": 1, "pending": None}
    capability, verifier = new_capability()
    code, result = cli("prepare", *common, "--new-verifier", verifier)
    assert code == 0 and result["state"] == "prepared" and result["target_epoch"] == 2
    with open(result["request_path"], "rb") as source:
        request_bytes = source.read()
    request = parse_canonical(request_bytes)
    assert request["kind"] == "owner_recovery" and len(request["request_nonce"]) == 43
    # the request never carries the capability or the verifier
    assert capability.encode() not in request_bytes and verifier.encode() not in request_bytes
    # a re-run of the same prepare is idempotent: the same sealed request
    code, again = cli("prepare", *common, "--new-verifier", verifier)
    assert code == 0 and again["repeated"] and again["request_id"] == result["request_id"]
    # the trust set holder signs outside the tool
    receipt = receipt_for(state.profile, request_bytes, state.signer, state.trust, new_verifier=verifier)
    (tmp_path / "receipt.json").write_bytes(receipt)
    (tmp_path / "trust.json").write_bytes(state.trust)
    code, done = cli("import", *common, "--receipt", str(tmp_path / "receipt.json"),
                     "--trust-set", str(tmp_path / "trust.json"))
    assert code == 0 and done["state"] == "imported" and done["recovery_epoch"] == 2
    assert configuration(state)["recovery_epoch"] == 2 and configuration(state)["verifier_b64u"] == verifier
    code, status = cli("status", *common)
    assert status["root_epoch"] == 2 and status["database_epoch"] == 1
    assert status["pending"] == {"state": "imported", "request_id": result["request_id"]}
    # importing the identical receipt again is a verify-only no-op
    code, repeat = cli("import", *common, "--receipt", str(tmp_path / "receipt.json"),
                       "--trust-set", str(tmp_path / "trust.json"))
    assert code == 0 and repeat["repeated"]
    # the next start runs the restricted reconciliation start
    assert_recovered_start(tmp_path, state, capability)
    assert rows(tmp_path, "SELECT epoch, recovery_request_id FROM owner_auth_control ORDER BY epoch") == [
        (1, None), (2, result["request_id"])]
    code, status = cli("status", *common)
    assert (status["configuration_epoch"], status["root_epoch"], status["database_epoch"]) == (2, 2, 2)


def test_the_tool_refuses_while_the_control_plane_runs(tmp_path):
    state = served(tmp_path)
    app = create_app(tmp_path / "data", **state.arguments)
    with TestClient(app, base_url=state.profile.http_origin):
        refused("busy", lambda: tool(tmp_path, state))
    with tool(tmp_path, state) as maintenance:
        assert maintenance_tool.status(maintenance)["pending"] is None


def test_a_second_recovery_needs_the_first_reconciled_and_refuses_the_first_receipt(tmp_path):
    state = served(tmp_path)
    capability, verifier = new_capability()
    _result, request = prepared(tmp_path, state, verifier)
    first = receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier)
    imported(tmp_path, state, first)
    # the server has not started since: epoch 2 is not reconciled, nothing new is sealed
    second_capability, second_verifier = new_capability()
    with tool(tmp_path, state) as maintenance:
        refused("reconciliation_pending", lambda: maintenance_tool.prepare(maintenance, new_verifier=second_verifier))
    assert_recovered_start(tmp_path, state, capability)
    state.capability = capability
    # epoch 2 → 3
    _result, request = prepared(tmp_path, state, second_verifier)
    # the first recovery's receipt is a replay now
    refused("replayed", lambda: imported(tmp_path, state, first))
    receipt = receipt_for(state.profile, request, state.signer, state.trust, new_verifier=second_verifier)
    imported(tmp_path, state, receipt)
    assert_recovered_start(tmp_path, state, second_capability, epoch=3)


# ---- cancel versus import ----------------------------------------------------------------

def test_cancel_ends_a_prepared_request_and_its_receipt(tmp_path):
    state = served(tmp_path)
    before = state.config_path.read_bytes()
    capability, verifier = new_capability()
    result, request = prepared(tmp_path, state, verifier)
    receipt = receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier)
    # a different verifier while one is prepared: cancel first
    with tool(tmp_path, state) as maintenance:
        refused("pending", lambda: maintenance_tool.prepare(maintenance, new_verifier=new_capability()[1]))
        assert maintenance_tool.cancel(maintenance) == {"state": "cancelled", "repeated": False,
                                                      "request_id": result["request_id"]}
        assert maintenance_tool.cancel(maintenance)["repeated"] is True
    refused("cancelled", lambda: imported(tmp_path, state, receipt))
    assert state.config_path.read_bytes() == before and root_epoch(tmp_path, state, 1) is not None
    # a fresh request (new id and nonce); the cancelled one's receipt is a replay
    fresh, fresh_request = prepared(tmp_path, state, verifier)
    assert fresh["request_id"] != result["request_id"]
    assert parse_canonical(fresh_request)["request_nonce"] != parse_canonical(request)["request_nonce"]
    refused("replayed", lambda: imported(tmp_path, state, receipt))
    imported(tmp_path, state, receipt_for(state.profile, fresh_request, state.signer, state.trust,
                                          new_verifier=verifier))
    with tool(tmp_path, state) as maintenance:
        refused("already_imported", lambda: maintenance_tool.cancel(maintenance))
    assert_recovered_start(tmp_path, state, capability)


def test_nothing_to_cancel_or_import_without_a_prepared_request(tmp_path):
    state = served(tmp_path)
    with tool(tmp_path, state) as maintenance:
        refused("no_pending", lambda: maintenance_tool.cancel(maintenance))
        refused("no_pending", lambda: maintenance_tool.import_receipt(maintenance, receipt_bytes=b"{}",
                                                                    trust_bytes=state.trust))
        # the old capability's verifier never opens a new epoch
        refused("invalid_request", lambda: maintenance_tool.prepare(
            maintenance, new_verifier=state.arguments["deployment_config"]["verifier_b64u"]))
        refused("invalid_request", lambda: maintenance_tool.prepare(maintenance, new_verifier="not-a-verifier"))


# ---- wrong, forged and replayed receipts -------------------------------------------------

def test_wrong_forged_and_foreign_receipts_change_nothing(tmp_path):
    state = served(tmp_path)
    before = state.config_path.read_bytes()
    capability, verifier = new_capability()
    _result, request = prepared(tmp_path, state, verifier)
    stage_only = Signer(adapters=(STAGE_ADAPTER,))
    outsider = Signer()
    both = trust_v2(state.profile, state.signer, stage_only)
    cases = [
        # bound to another verifier than the prepared one
        ("receipt_mismatch", receipt_for(state.profile, request, state.signer, state.trust,
                                         new_verifier=new_capability()[1]), None),
        # an unsigned (zero) signature
        ("receipt_invalid", receipt_for(state.profile, request, state.signer, state.trust,
                                        new_verifier=verifier, sign=False), None),
        # signed by a key the trust set does not hold
        ("receipt_invalid", receipt_for(state.profile, request, outsider, state.trust, new_verifier=verifier), None),
        # a stage-only key in the trust set never signs a recovery
        ("receipt_invalid", receipt_for(state.profile, request, stage_only, both, new_verifier=verifier), both),
        # a correctly signed receipt checked against another trust set
        ("receipt_invalid", receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier),
         trust_v2(state.profile, outsider)),
        # a skipped epoch, even when signed
        ("receipt_invalid", receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier,
                                        new_epoch=3), None),
        # not a receipt at all
        ("receipt_invalid", b'{"schema":"deployment-recovery-receipt-v1"}', None),
    ]
    # a receipt for a request this tool never sealed (same instance, same root)
    with tool(tmp_path, state) as maintenance:
        root = maintenance.root_generation(state.profile, 1)
    from app.tests.recovery_fixture import request_for

    foreign = request_for(state.profile, epoch=1, generation_id=root["generation_id"],
                          manifest_sha256=root["manifest_sha256"])
    cases.append(("receipt_mismatch", receipt_for(state.profile, foreign, state.signer, state.trust,
                                                  new_verifier=verifier), None))
    for code, receipt, trust in cases:
        refused(code, lambda receipt=receipt, trust=trust: imported(tmp_path, state, receipt, trust))
    assert state.config_path.read_bytes() == before
    assert root_epoch(tmp_path, state, 1) is not None and root_epoch(tmp_path, state, 2) is None
    with tool(tmp_path, state) as maintenance:
        assert maintenance.pending()["state"] == "prepared"
    # the genuine receipt still imports afterwards
    imported(tmp_path, state, receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier))
    assert_recovered_start(tmp_path, state, capability)


# ---- a crash between any two steps ---------------------------------------------------------

@pytest.mark.parametrize("step", ["importing_recorded", "root_advanced", "config_written"])
def test_a_crash_between_import_steps_is_completed_by_re_running_import(tmp_path, monkeypatch, step):
    state = served(tmp_path)
    capability, verifier = new_capability()
    _result, request = prepared(tmp_path, state, verifier)
    receipt = receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier)

    def crash(name):
        if name == step:
            raise RuntimeError("the process ended here")

    monkeypatch.setattr(maintenance_tool, "_step", crash)
    with pytest.raises(RuntimeError):
        imported(tmp_path, state, receipt)
    monkeypatch.setattr(maintenance_tool, "_step", lambda name: None)
    with tool(tmp_path, state) as maintenance:
        assert maintenance.pending()["state"] == "importing"
        # a journaled import is completed, never cancelled or switched to another receipt
        refused("import_in_progress", lambda: maintenance_tool.cancel(maintenance))
        refused("import_in_progress", lambda: maintenance_tool.prepare(maintenance, new_verifier=verifier))
    other = receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier)
    refused("import_in_progress", lambda: imported(tmp_path, state, other))
    if step == "root_advanced":
        # the root moved but the configuration did not: the control plane fails closed
        assert configuration(state)["recovery_epoch"] == 1
        with pytest.raises(Exception):  # noqa: B017 - fails closed whatever it reports
            start(tmp_path, state)
    result = imported(tmp_path, state, receipt)
    assert result["state"] == "imported" and result["repeated"] is False
    assert configuration(state)["recovery_epoch"] == 2
    assert_recovered_start(tmp_path, state, capability)


def test_a_crash_after_the_request_file_leaves_an_inert_request(tmp_path, monkeypatch):
    state = served(tmp_path)
    capability, verifier = new_capability()

    def crash(name):
        if name == "request_written":
            raise RuntimeError("the process ended here")

    monkeypatch.setattr(maintenance_tool, "_step", crash)
    with pytest.raises(RuntimeError), tool(tmp_path, state) as maintenance:
        maintenance_tool.prepare(maintenance, new_verifier=verifier)
    monkeypatch.setattr(maintenance_tool, "_step", lambda name: None)
    (orphan,) = (tmp_path / "work" / "requests").iterdir()
    with tool(tmp_path, state) as maintenance:
        assert maintenance.pending() is None
        refused("no_pending", lambda: maintenance_tool.import_receipt(
            maintenance, receipt_bytes=receipt_for(state.profile, orphan.read_bytes(), state.signer, state.trust,
                                                   new_verifier=verifier), trust_bytes=state.trust))
    result, request = prepared(tmp_path, state, verifier)
    assert result["request_id"] + ".json" != orphan.name
    # the unnamed request's receipt is refused; the named one imports
    refused("replayed", lambda: imported(tmp_path, state, receipt_for(
        state.profile, orphan.read_bytes(), state.signer, state.trust, new_verifier=verifier)))
    imported(tmp_path, state, receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier))
    assert_recovered_start(tmp_path, state, capability)


def test_work_files_are_written_by_rename_and_never_left_temporary(tmp_path):
    state = served(tmp_path)
    _capability, verifier = new_capability()
    _result, request = prepared(tmp_path, state, verifier)
    imported(tmp_path, state, receipt_for(state.profile, request, state.signer, state.trust, new_verifier=verifier))
    names = {path.name for path in (tmp_path / "work").rglob("*")} | {path.name for path in (tmp_path / "config").iterdir()}
    assert not any(name.endswith(".tmp") for name in names)
    assert oct((tmp_path / "work").stat().st_mode & 0o777) == oct(0o700)
    assert oct((tmp_path / "work" / "pending.json").stat().st_mode & 0o777) == oct(0o600)
