"""T090 production gateway entrypoint (`app.workers.credential_gateway_main`).

The real-UDS tests (root on Linux; skipped elsewhere) start the production entrypoint
as a subprocess under the provider identity 20103:20103 with the pair group 21101, and
the real supported app factory (`credential_app_child`) under the control identity
20102:20102 with the pair group. The only substitution on either side is the
module-local relocation of the fixed `cp-provider` profile into an owned temporary pair
root (``credential_gateway_launcher`` for the gateway). The pair root generation is
created by the real root-only ``ipc_root.initialize_pair_root`` and the vault pair by
the real deployment-only ``initialize_credential_root`` run as the provider identity.
Both processes read the one attachment file that names the requester boot label.

The configuration tests need no privileges and run everywhere.
"""

from __future__ import annotations

import fcntl
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest

from app.tests.test_credential_gateway_peercred import (  # noqa: F401 - the `base` fixture
    CONTROL_GID,
    CONTROL_UID,
    PAIR_GID,
    PROVIDER_GID,
    PROVIDER_UID,
    REPOSITORY,
    _child_environment,
    assert_no_secret_bytes,
    base,
    journal_counts,
)
from app.workers import credential_gateway_main, gateway_channel, ipc_root
from app.workers.credential_attachment import SCHEMA

FIRST = "sk-synthetic-gateway-main-first-0001"
SECOND = "sk-synthetic-gateway-main-second-0002"
BOOT = "control-boot-t090-main"
SECONDS = 90

real_uds = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED")
    or not hasattr(os, "geteuid") or os.geteuid() != 0
    or not Path("/proc/self/fd").is_dir(),
    reason="the real gateway entrypoint needs Linux, root and /proc/self/fd",
)


def connection(handle, state, revision):
    """The GET projection of a provider connection's binding head (no catalog yet)."""
    return {"provider": "claude", "state": state, "handle": handle, "binding_revision": revision,
            "catalog": "absent", "model_choice": "absent"}


# --- configuration refusals (no privileges) ------------------------------------------

def _write(path, value):
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


def _configs(directory, *, vault_id=None, pair_root=None, boot=BOOT):
    fixed_root, _spec = gateway_channel.gateway_channel()
    service = _write(directory / "service.json", {
        "schema": credential_gateway_main.SERVICE_SCHEMA, "vault_id": vault_id or str(uuid4()),
        "root_directory": str(directory / "vault" / "root"),
        "records_directory": str(directory / "vault" / "records")})
    attachment = _write(directory / "attachment.json", {
        "schema": SCHEMA, "pair_root": pair_root or str(fixed_root.pair_root), "requester_boot_id": boot})
    return service, attachment


def _argv(service, attachment):
    return ["gateway", f"--service-config={service}", f"--attachment-config={attachment}"]


def _events(capsys):
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


@pytest.mark.parametrize("argv", [
    ["gateway"],
    ["gateway", "--service-config=/a.json"],
    ["gateway", "--service-config=/a.json", "--service-config=/b.json"],
    ["gateway", "--service-config=/a.json", "--attachment-config=relative.json"],
    ["gateway", "--service-config=/a.json", "--attachment-config=/b.json", "--extra=/c"],
    ["gateway", "--service-config", "/a.json", "--attachment-config", "/b.json"],
])
def test_argv_outside_the_exact_shape_exits_2(argv, capsys):
    assert credential_gateway_main.main(argv) == credential_gateway_main.EXIT_CONFIG
    assert _events(capsys) == [{"event": "configuration_invalid", "class": "ValueError"}]


def test_an_attachment_naming_another_pair_root_exits_2_before_any_open(tmp_path, capsys, monkeypatch):
    service, attachment = _configs(tmp_path, pair_root=str(tmp_path / "cp-provider"))

    def refuse(*_args, **_kwargs):
        pytest.fail("the gateway opened something for a wrongly named endpoint")

    from app.workers import credential_vault, listener
    monkeypatch.setattr(credential_vault, "CredentialVault", refuse)
    monkeypatch.setattr(listener, "bind_worker_listener", refuse)
    assert credential_gateway_main.main(_argv(service, attachment)) == credential_gateway_main.EXIT_CONFIG
    assert _events(capsys) == [{"event": "configuration_invalid", "class": "ValueError"}]


@pytest.mark.parametrize("mutation", ["service_schema", "service_extra", "vault_id", "relative_root",
                                      "attachment_schema", "attachment_boot", "duplicate_key", "not_json"])
def test_configurations_outside_the_exact_objects_exit_2(tmp_path, capsys, mutation):
    service, attachment = _configs(tmp_path)
    value = json.loads(service.read_text())
    attached = json.loads(attachment.read_text())
    if mutation == "service_schema":
        _write(service, {**value, "schema": "other"})
    elif mutation == "service_extra":
        _write(service, {**value, "key": "inline"})
    elif mutation == "vault_id":
        _write(service, {**value, "vault_id": "00000000-0000-0000-0000-000000000000"})
    elif mutation == "relative_root":
        _write(service, {**value, "root_directory": "vault/root"})
    elif mutation == "attachment_schema":
        _write(attachment, {**attached, "schema": "other"})
    elif mutation == "attachment_boot":
        _write(attachment, {**attached, "requester_boot_id": "-bad boot"})
    elif mutation == "duplicate_key":
        _write(attachment, f'{{"schema": "{SCHEMA}", "schema": "{SCHEMA}", '
                           f'"pair_root": "{attached["pair_root"]}", "requester_boot_id": "b"}}')
    else:
        _write(service, "{not json")
    assert credential_gateway_main.main(_argv(service, attachment)) == credential_gateway_main.EXIT_CONFIG
    events = _events(capsys)
    assert [event["event"] for event in events] == ["configuration_invalid"]


def test_an_unopenable_vault_exits_1_without_binding(tmp_path, capsys, monkeypatch):
    from app.workers import listener

    monkeypatch.setattr(listener, "bind_worker_listener",
                        lambda *_a, **_k: pytest.fail("bound a listener without a vault"))
    service, attachment = _configs(tmp_path)  # nothing initialized at the named pair
    assert credential_gateway_main.main(_argv(service, attachment)) == credential_gateway_main.EXIT_SERVICE
    events = _events(capsys)
    assert [event["event"] for event in events] == ["gateway_unavailable"]
    assert set(events[0]) == {"event", "class"}  # a class name, never a message or path


def test_the_entrypoint_imports_no_web_or_control_plane_code():
    code = ("import sys, app.workers.credential_gateway_main as m; "
            "print(sorted(n for n in sys.modules if n.split('.')[0] in ('fastapi', 'starlette', 'uvicorn')"
            " or n.startswith(('app.api', 'app.server', 'app.services'))))")
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=REPOSITORY, env=_child_environment(),
                            capture_output=True, text=True, timeout=60, check=True)
    assert result.stdout.strip() == "[]"


# --- the real entrypoint over a real UDS ----------------------------------------------

def _event(line):
    try:
        value = json.loads(line)
    except ValueError:
        return {"event": "unstructured", "line": line}
    return value if type(value) is dict and "event" in value else {"event": "unstructured", "line": line}


class Gateway:
    """The production entrypoint as a provider-identity subprocess; stderr events collected."""

    def __init__(self, directory, attachment):
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-m", "app.tests.support.credential_gateway_launcher", str(directory),
             f"--service-config={directory / 'config' / 'service.json'}",
             f"--attachment-config={attachment}"],
            cwd=REPOSITORY, env=_child_environment(), user=PROVIDER_UID, group=PROVIDER_GID,
            extra_groups=[PAIR_GID], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines: list[str] = []
        self._changed = threading.Condition()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()
        self.wait_for("gateway_ready")

    def _read(self):
        for raw in self.process.stderr:
            with self._changed:
                self.lines.append(raw.decode(errors="replace").rstrip("\n"))
                self._changed.notify_all()
        with self._changed:
            self._changed.notify_all()

    def events(self):
        with self._changed:
            lines = list(self.lines)
        return [_event(line) for line in lines]

    def names(self):
        return [event["event"] for event in self.events()]

    def wait_for(self, name, count=1):
        limit = time.monotonic() + SECONDS
        with self._changed:
            while sum(1 for line in self.lines if _event(line)["event"] == name) < count:
                if self.process.poll() is not None and not self._reader.is_alive():
                    pytest.fail(f"gateway exited before {name}: {self.lines}")
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    pytest.fail(f"gateway never logged {name}: {self.lines}")
                self._changed.wait(min(remaining, 0.5))

    def terminate(self):
        """SIGTERM and wait: a requested stop is exit 0 after `gateway_stopped`."""
        self.process.send_signal(signal.SIGTERM)
        try:
            code = self.process.wait(SECONDS)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(5)
            pytest.fail("gateway did not stop on SIGTERM")
        self._reader.join(5)
        assert self.process.stdout.read() == b""  # nothing on stdout, ever
        return code

    def kill(self):
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(5)


def _deploy(directory, *, boot=BOOT):
    """The deployment steps the entrypoint does not perform: vault genesis (as the
    provider identity) and the two nonsecret configuration files."""

    vault_id = str(uuid4())
    genesis = ("import sys; from app.operations.credential_root_init import initialize_credential_root as i; "
               "i(sys.argv[1] + '/vault/root', sys.argv[1] + '/vault/records', vault_id=sys.argv[2], "
               "expected_uid=20103, expected_gid=20103)")
    subprocess.run([sys.executable, "-B", "-c", genesis, str(directory), vault_id], cwd=REPOSITORY,
                   env=_child_environment(), user=PROVIDER_UID, group=PROVIDER_GID, check=True, timeout=60,
                   capture_output=True)
    config = directory / "config"
    config.mkdir(mode=0o755)
    _write(config / "service.json", {
        "schema": credential_gateway_main.SERVICE_SCHEMA, "vault_id": vault_id,
        "root_directory": str(directory / "vault" / "root"),
        "records_directory": str(directory / "vault" / "records")})
    return attachment_file(directory, "attachment.json", boot)


def attachment_file(directory, name, boot):
    path = _write(directory / "config" / name, {
        "schema": SCHEMA, "pair_root": str(directory / "cp-provider"), "requester_boot_id": boot})
    os.chmod(path, 0o644)
    os.chmod(directory / "config" / "service.json", 0o644)
    return path


def _control(directory, steps, attachment):
    home = directory / "control"
    if not home.exists():
        home.mkdir(mode=0o700)
        os.chown(home, CONTROL_UID, CONTROL_GID)
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "app.tests.support.credential_app_child"],
        cwd=REPOSITORY, env=_child_environment(), user=CONTROL_UID, group=CONTROL_GID,
        extra_groups=[PAIR_GID], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdin.write(json.dumps({"base": str(directory), "steps": steps,
                                    "attachment": str(attachment)}).encode())
    process.stdin.close()
    process.stdin = None  # the plan is complete; `communicate` only reads from here
    return process


def _control_result(process):
    try:
        out, err = process.communicate(timeout=SECONDS * 2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.communicate()
        pytest.fail("control child did not finish")
    assert process.returncode == 0, err.decode(errors="replace")[-3000:]
    return json.loads(out)


def _wait_file(path):
    limit = time.monotonic() + SECONDS
    while not path.exists():
        if time.monotonic() > limit:
            pytest.fail(f"{path.name} never appeared")
        time.sleep(0.02)


def _assert_clean_stop(directory, gateway, code):
    assert code == credential_gateway_main.EXIT_OK
    assert gateway.names()[-1] == "gateway_stopped"
    assert "gateway_unavailable" not in gateway.names()
    endpoint = directory / "cp-provider" / ipc_root.ENDPOINT_NAME
    # the listener unlinked its socket and readiness record; the generation stays
    assert not (endpoint / gateway_channel.SOCKET_NAME).exists()
    assert not (endpoint / ipc_root.LISTENER_NAME).exists()
    assert (directory / "cp-provider" / ipc_root.BOOT_SECRET_NAME).exists()
    for event in gateway.events():
        assert set(event) <= {"event", "class"}


class _MutationLock:
    """Holds the vault's own mutation lock from outside, so a gateway dialogue that
    reached the vault waits (bounded, 5 s) at a known point before any commit."""

    def __init__(self, directory):
        self._fd = os.open(directory / "vault" / "records" / "mutation.lock", os.O_RDONLY)
        fcntl.flock(self._fd, fcntl.LOCK_EX)

    def release(self):
        if self._fd >= 0:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = -1


@real_uds
def test_the_entrypoint_serves_create_list_rotate_delete_to_the_supported_factory(base):  # noqa: F811
    attachment = _deploy(base)
    gateway = Gateway(base, attachment)
    try:
        result = _control_result(_control(base, [
            {"op": "store", "intent_id": str(uuid4()), "secret": FIRST},
            {"op": "list"},
            {"op": "store", "intent_id": str(uuid4()), "secret": SECOND, "rotate": True},
            {"op": "list"},
            {"op": "delete", "intent_id": str(uuid4())},
            {"op": "list"},
        ], attachment))
        code = gateway.terminate()
    finally:
        gateway.kill()
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
    assert result["vault_modules"] == []
    # four gateway dialogues (create; rotate store + superseded retire; delete), no GET
    assert gateway.names() == ["gateway_ready", *(["session_accepted", "session_served"] * 4), "gateway_stopped"]
    _assert_clean_stop(base, gateway, code)
    assert journal_counts(base) == (2, 2, 2, 2)
    assert_no_secret_bytes(base, FIRST.encode(), SECOND.encode())
    assert FIRST not in "\n".join(gateway.lines) and SECOND not in "\n".join(gateway.lines)


@real_uds
def test_a_requester_boot_label_other_than_the_attachment_is_refused_with_zero_effect(base):  # noqa: F811
    expected = _deploy(base, boot="control-boot-expected")
    other = attachment_file(base, "other.json", "control-boot-other")
    gateway = Gateway(base, expected)
    try:
        refused = _control_result(_control(base, [
            {"op": "store", "intent_id": str(uuid4()), "secret": FIRST},
            {"op": "list"},
        ], other))
        assert gateway.process.poll() is None  # one refused peer never ends the service
        code = gateway.terminate()
    finally:
        gateway.kill()
    store, listing = refused["steps"]
    assert store["status"] == 503 and store["body"]["code"] == "dependency_unavailable"
    assert FIRST not in json.dumps(store)
    assert listing == {"status": 200, "body": {"credentials": [], "connections": [],
                                               "pending_acts": []}}
    names = gateway.names()
    assert "session_accepted" not in names and "session_refused" in names
    _assert_clean_stop(base, gateway, code)
    assert journal_counts(base) == (0, 0, 0, 0)
    assert_no_secret_bytes(base, FIRST.encode())


@real_uds
def test_sigterm_during_a_dialogue_completes_it_then_stops_cleanly(base):  # noqa: F811
    attachment = _deploy(base)
    gateway = Gateway(base, attachment)
    lock = _MutationLock(base)
    try:
        control = _control(base, [{"op": "store", "intent_id": str(uuid4()), "secret": FIRST}], attachment)
        gateway.wait_for("session_accepted")
        gateway.process.send_signal(signal.SIGTERM)
        time.sleep(0.5)
        assert gateway.process.poll() is None  # the dialogue in progress is not interrupted
        lock.release()
        result = _control_result(control)
        code = gateway.process.wait(SECONDS)
        gateway._reader.join(5)
    finally:
        lock.release()
        gateway.kill()
    (created,) = result["steps"]
    assert created["status"] == 201 and created["body"]["state"] == "stored_unbound"
    assert gateway.names() == ["gateway_ready", "session_accepted", "session_served", "gateway_stopped"]
    _assert_clean_stop(base, gateway, code)
    assert journal_counts(base) == (1, 1, 1, 0)


@real_uds
def test_a_command_pending_across_a_gateway_restart_resolves_by_query(base):  # noqa: F811
    attachment = _deploy(base)
    intent = str(uuid4())
    first = Gateway(base, attachment)
    second = None
    lock = _MutationLock(base)
    control = None
    try:
        control = _control(base, [
            {"op": "store", "intent_id": intent, "secret": FIRST},
            {"op": "mark", "name": "first-answered"},
            {"op": "wait_for", "name": "gateway-restarted", "seconds": 120},
            {"op": "store", "intent_id": intent, "secret": SECOND},
            {"op": "list"},
        ], attachment)
        # the store reached the gateway, which now waits for the vault's mutation lock:
        # stopping it here means the request was sent and nothing is committed yet
        first.wait_for("session_accepted")
        first.process.send_signal(signal.SIGSTOP)
        # the control plane's store and its recovery query both time out (5 s each), so
        # the act stays pending in the ledger: nothing is re-sent, nothing is lost
        _wait_file(base / "control" / "first-answered")
        assert journal_counts(base) == (0, 0, 0, 0)  # nothing committed while stopped
        lock.release()
        first.process.send_signal(signal.SIGCONT)
        # the gateway resumes, commits the command and fails only to answer it
        first.wait_for("session_failed")
        assert journal_counts(base) == (1, 1, 1, 0)
        code = first.terminate()
        _assert_clean_stop(base, first, code)
        second = Gateway(base, attachment)  # a new process, the same vault and pair root
        (base / "control" / "gateway-restarted").touch()
        result = _control_result(control)
        second_code = second.terminate()
    finally:
        lock.release()
        first.process.send_signal(signal.SIGCONT)
        first.kill()
        if second is not None:
            second.kill()
        if control is not None and control.poll() is None:
            control.kill()
    pending, retried, listing = result["steps"]
    assert pending["status"] == 503 and pending["body"]["code"] == "command_pending"
    handle = retried["body"]["handle"]
    # the retry of the same act only queried: the committed receipt is adopted and the
    # re-entered bytes were never sent or ingested
    assert retried == {"status": 201, "body": {"handle": handle, "provider": "claude", "state": "stored_unbound"}}
    assert listing == {"status": 200, "body": {
        "credentials": [{"handle": handle, "provider": "claude", "state": "stored_unbound",
                         "provider_revocation": "not_performed"}],
        "connections": [connection(handle, "bound", 1)], "pending_acts": []}}
    assert second.names() == ["gateway_ready", "session_accepted", "session_served", "gateway_stopped"]
    _assert_clean_stop(base, second, second_code)
    assert journal_counts(base) == (1, 1, 1, 0)
    assert_no_secret_bytes(base, FIRST.encode(), SECOND.encode())
    logs = "\n".join(first.lines + second.lines)
    assert FIRST not in logs and SECOND not in logs
