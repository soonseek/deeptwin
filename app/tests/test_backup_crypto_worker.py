"""T070: the networkless backup-crypto worker as a separate process over the verified channel.

The real-socket tests (Linux, root, and DEEPTWIN_AGE_RUNTIME_ROOT; skipped elsewhere and
saying why) start the production entrypoint (`app.workers.backup_crypto_main`, through
the relocating ``backup_crypto_launcher``) in an empty network namespace under the backup
identity 20111:20111 with the pair group 21109, and the control-plane side
(``backup_control_child``) under the control identity 20102:20102 with the pair group.
The control side runs the real `create_backup`/`restore_backup` with the real
`BackupCryptoClient` as their crypto port; it never has a key handle, and the kernel
refuses it the backup-key volume. See ``backup_worker_harness`` for what is relocated.

The stream, configuration, guard and boundary tests need no privileges and run everywhere.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from app.tests.support import backup_worker_harness as harness
from app.workers import backup_channel, backup_crypto_main, backup_stream, broker

REPOSITORY = Path(__file__).resolve().parents[2]
CANARY = "credential-canary-7f3a"
SECONDS = 120

real_worker = pytest.mark.skipif(harness.available() is not None, reason=harness.available() or "")


# --- the typed stream (no privileges) ---------------------------------------------------

class _Frame:
    def __init__(self, message_type, payload):
        self.envelope = type("E", (), {"message_type": message_type, "message_id": "m"})()
        self.payload = payload


class _Pipe:
    """An in-memory connection: frames written are read back in order."""

    def __init__(self):
        self.frames = []

    def write(self, *, message_id, correlation_id, message_type, payload, deadline):
        self.frames.append(_Frame(message_type, payload))

    def read(self, *, deadline):
        if not self.frames:
            raise broker.TransportClosed()
        return self.frames.pop(0)


BODY = b"".join(hashlib.sha256(str(i).encode()).digest() for i in range(5_600))  # several distinct chunks


def _deadline():
    return broker.Deadline.after_ms(5_000)


def test_a_body_round_trips_whole_in_bounded_chunks():
    pipe = _Pipe()
    backup_stream.write_body(pipe, BODY, deadline=_deadline())
    assert all(len(frame.payload) <= backup_stream.CHUNK_BYTES for frame in pipe.frames)
    assert pipe.frames[-1].envelope.message_type == backup_stream.END
    got = backup_stream.read_body(pipe, size=len(BODY), sha256=hashlib.sha256(BODY).hexdigest(),
                                  deadline=_deadline())
    assert got == BODY


@pytest.mark.parametrize("damage", ["cut", "drop_end", "flip", "reorder", "extra", "short_end", "oversize"])
def test_an_interrupted_or_altered_stream_returns_nothing(damage):
    pipe = _Pipe()
    backup_stream.write_body(pipe, BODY, deadline=_deadline())
    frames = pipe.frames
    if damage == "cut":
        del frames[1:]
    elif damage == "drop_end":
        frames.pop()
    elif damage == "flip":
        frames[1].payload = bytes([frames[1].payload[0] ^ 1]) + frames[1].payload[1:]
    elif damage == "reorder":
        frames[0], frames[1] = frames[1], frames[0]
    elif damage == "extra":
        frames.insert(1, _Frame(backup_stream.REQUEST, b"{}"))
    elif damage == "short_end":
        frames[-2].payload = frames[-2].payload[:-1]
    else:
        frames.insert(0, _Frame(backup_stream.CHUNK, b"x" * (backup_stream.CHUNK_BYTES + 1)))
    with pytest.raises((backup_stream.BackupStreamError, broker.TransportClosed)):
        backup_stream.read_body(pipe, size=len(BODY), sha256=hashlib.sha256(BODY).hexdigest(),
                                deadline=_deadline())


def _request(**changes):
    value = {"schema": backup_stream.REQUEST_SCHEMA, "op": "encrypt", "key_mode": "instance_backup_key",
             "recipient": None, "identity": None, "size": 3, "sha256": "0" * 64}
    return {**value, **changes}


@pytest.mark.parametrize("changes", [
    {"op": "sign"}, {"key_mode": "passphrase"}, {"identity": "AGE-SECRET-KEY-1X"},
    {"key_mode": "portable_recovery"},  # portable encryption names its recipient
    {"op": "decrypt", "key_mode": "portable_recovery"},  # portable decryption needs the one-shot identity
    {"op": "decrypt", "recipient": "age1x"}, {"op": "describe"}, {"size": -1},
    {"size": backup_stream.MAX_STREAM_BYTES + 1}, {"sha256": "A" * 64}, {"path": "/key"},
])
def test_requests_outside_the_exact_shape_are_refused(changes):
    with pytest.raises(backup_stream.BackupStreamError) as refused:
        backup_stream.check_request(_request(**changes))
    assert refused.value.code == "request_invalid"
    assert backup_stream.check_request(_request())


# --- the entrypoint's configuration (no privileges) ------------------------------------

def _configs(directory, *, key_root=None, age_root=None, pair_root=None, schema=None):
    fixed_root, _spec = backup_channel.backup_channel()
    service = directory / "service.json"
    service.write_text(json.dumps({"schema": schema or backup_crypto_main.SERVICE_SCHEMA,
                                   "key_root": str(key_root or directory / "backup-key"),
                                   "age_root": str(age_root or directory / "age")}))
    attachment = directory / "attachment.json"
    attachment.write_text(json.dumps({"schema": backup_channel.ATTACHMENT_SCHEMA,
                                      "pair_root": pair_root or str(fixed_root.pair_root),
                                      "requester_boot_id": harness.BOOT}))
    return service, attachment


def _events(capsys):
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


@pytest.mark.parametrize("argv", [
    ["w"], ["w", "--service-config=/a.json"], ["w", "--service-config=/a", "--attachment-config=rel"],
    ["w", "--service-config=/a", "--attachment-config=/b", "--key=/c"],
])
def test_argv_outside_the_exact_shape_exits_2(argv, capsys):
    assert backup_crypto_main.main(argv) == backup_crypto_main.EXIT_CONFIG
    assert _events(capsys) == [{"event": "configuration_invalid", "class": "ValueError"}]


@pytest.mark.parametrize("mutation", ["schema", "other_pair_root", "same_roots", "key_in_pair_root"])
def test_configurations_outside_the_exact_objects_exit_2_before_any_open(tmp_path, capsys, monkeypatch, mutation):
    fixed_root, _spec = backup_channel.backup_channel()
    kwargs = {"schema": "other"} if mutation == "schema" else \
        {"pair_root": str(tmp_path / "cp-backup")} if mutation == "other_pair_root" else \
        {"key_root": tmp_path / "age", "age_root": tmp_path / "age"} if mutation == "same_roots" else \
        {"key_root": fixed_root.pair_root / "backup-key"}
    service, attachment = _configs(tmp_path, **kwargs)

    def refuse(*_args, **_kwargs):
        pytest.fail("the worker opened something for a refused configuration")

    monkeypatch.setattr(backup_crypto_main, "forbid_network", refuse)
    from app.workers import listener
    monkeypatch.setattr(listener, "bind_worker_listener", refuse)
    argv = ["w", f"--service-config={service}", f"--attachment-config={attachment}"]
    assert backup_crypto_main.main(argv) == backup_crypto_main.EXIT_CONFIG
    assert [event["event"] for event in _events(capsys)] == ["configuration_invalid"]


def test_a_key_root_that_is_a_credential_root_or_writable_is_refused(tmp_path):
    from app.workers.backup_crypto_service import BackupKeyRootError, check_key_root

    assert check_key_root(tmp_path / "absent") is False  # a lost volume: serve, answer key_unavailable
    credential_like = tmp_path / "credential-root"
    credential_like.mkdir()
    for name in ("identity.age", "manifest.json", "vault.sqlite"):
        (credential_like / name).write_text("x")
    with pytest.raises(BackupKeyRootError, match="something other"):
        check_key_root(credential_like)
    writable = tmp_path / "writable"
    writable.mkdir()
    for name in ("identity.age", "manifest.json"):
        (writable / name).write_text("x")
    with pytest.raises(BackupKeyRootError, match="writable"):
        check_key_root(writable)
    os.chmod(writable, 0o500)
    assert check_key_root(writable) is True
    os.chmod(writable, 0o700)


# --- networkless and boundary (no privileges) -------------------------------------------

GUARD_PROBE = """
import json, socket, subprocess, sys
from pathlib import Path
from app.workers.backup_crypto_main import forbid_network
forbid_network(Path(sys.argv[1]))
results = {}
for name, attempt in {
    "inet": lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM),
    "inet6": lambda: socket.socket(socket.AF_INET6, socket.SOCK_DGRAM),
    "resolve": lambda: socket.getaddrinfo("example.com", 443),
    "spawn": lambda: subprocess.run(["/bin/true"]),
}.items():
    try:
        attempt()
        results[name] = "allowed"
    except PermissionError:
        results[name] = "refused"
unix = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
unix.close()
results["unix"] = "allowed"
print(json.dumps(results))
"""


def test_the_worker_process_guard_refuses_every_network_socket_and_foreign_spawn(tmp_path):
    completed = subprocess.run([sys.executable, "-B", "-c", GUARD_PROBE, str(tmp_path / "age")],
                               cwd=REPOSITORY, env=harness.child_environment(), capture_output=True,
                               text=True, timeout=60, check=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {"inet": "refused", "inet6": "refused", "resolve": "refused",
                                            "spawn": "refused", "unix": "allowed"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add("." * node.level + (node.module or ""))
    return names


def test_the_worker_never_imports_credential_vault_or_route_code_and_the_client_no_key_code():
    workers = REPOSITORY / "app" / "workers"
    forbidden = ("credential", "vault", "api", "services", "storage", "domain", "provider")
    for module in ("backup_crypto_main.py", "backup_crypto_service.py", "backup_stream.py", "backup_channel.py"):
        for name in _imports(workers / module):
            assert not any(word in name for word in forbidden), (module, name)
    client = _imports(workers / "backup_crypto_client.py")
    assert not any("backup_crypto_service" in name or "backup_key" in name or name.endswith("backup_crypto")
                   for name in client), client


# --- the real process boundary ---------------------------------------------------------

def _vault(base: Path, name="vault"):
    from app.tests.test_backup import populated_vault

    vault = base / name
    _domain, record = populated_vault(vault)
    return vault, record


def _own(path: Path, uid=harness.CONTROL_UID, gid=harness.CONTROL_GID):
    for item in (path, *path.rglob("*")):
        os.chown(item, uid, gid)


def _control(worker, steps, *, uid=harness.CONTROL_UID, gid=harness.CONTROL_GID):
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "app.tests.support.backup_control_child"], cwd=REPOSITORY,
        env=harness.child_environment(), user=uid, group=gid, extra_groups=[harness.PAIR_GID],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    out, err = process.communicate(json.dumps({"base": str(worker.base), "boot": harness.BOOT,
                                               "steps": steps}).encode(), timeout=SECONDS)
    assert process.returncode == 0, err.decode(errors="replace")[-3000:]
    lines = [json.loads(line) for line in out.decode().splitlines()]
    assert lines[0]["identity"][:2] == [uid, gid]
    return lines[1:]


@pytest.fixture
def worker():
    base = harness.WorkerBase()
    try:
        base.start()
        yield base
    finally:
        base.close()


def _workspace(worker):
    work = worker.base / "control"
    work.mkdir(mode=0o700)
    vault, record = _vault(work)
    (work / "out").mkdir(mode=0o700)
    (work / "staging").mkdir(mode=0o700)
    _own(work)
    return work, vault, record


@real_worker
def test_create_and_restore_cross_the_process_boundary_and_the_control_never_reads_the_key(worker):
    work, vault, _record = _workspace(worker)
    described, created, key_read = _control(worker, [
        {"op": "describe"}, {"op": "create", "vault": str(vault), "out": str(work / "out")},
        {"op": "read_key", "path": str(worker.key_root / "identity.age")}])
    assert described == {"ok": {"key": "present", "key_mode": "instance_backup_key",
                                "recipient": worker.recipient}}
    assert created["state"] == "ready", created["failure"]
    assert created["states"] == ["backup_pending", "snapshotting", "encrypting", "verify_restore", "ready"]
    assert key_read == {"read": False, "class": "PermissionError"}  # the kernel, not a convention
    ciphertext = Path(created["ciphertext"]).read_bytes()
    assert ciphertext.startswith(b"age-encryption.org/v1\n") and CANARY.encode() not in ciphertext
    assert created["receipt"]["ciphertext_sha256"] == hashlib.sha256(ciphertext).hexdigest()
    assert created["receipt"]["recoverable_after_host_or_volume_loss"] is False
    # the ciphertext really is to the worker's own recipient: the worker's key opens it
    identity = (worker.key_root / "identity.age").read_bytes()  # the test (root) may look
    assert worker.runtime.decrypt(ciphertext, identity).startswith(b"manifest.json")
    restored, = _control(worker, [{"op": "restore", "ciphertext": created["ciphertext"],
                                   "receipt": created["receipt"], "staging": str(work / "staging"),
                                   "active": str(vault)}])
    assert restored["state"] == "restored_review", restored["failure"]
    assert "record_lineage" in restored["checked"]
    marker = json.loads((work / "staging" / "restored_review.json").read_bytes())
    assert marker["dispatch"] == "blocked"
    assert marker["requires"] == ["new_owner_bootstrap", "recreate_connections_and_service_clients",
                                  "review_and_activate_exact_environment"]
    with sqlite3.connect(Path(restored["vault"]) / "intake.sqlite3") as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    assert not {"owner_auth_sessions", "conversation_challenges", "provider_connections"} & tables
    worker.stop()
    served = [event.get("outcome") for event in worker.events if event["event"] == "session_served"]
    assert served == ["served"] * 4  # describe, encrypt, verify_restore decrypt, restore decrypt
    assert worker.networkless
    for event in worker.events:
        assert set(event) <= {"event", "class", "outcome"}


@real_worker
def test_a_foreign_identity_is_refused_by_the_kernel_check(worker):
    work, _vault, _record = _workspace(worker)
    os.chmod(work, 0o755)
    for path in (work, *work.rglob("*")):
        os.chmod(path, 0o777 if path.is_dir() else 0o666)
    refused, = _control(worker, [{"op": "describe"}], uid=20_104, gid=20_104)
    assert refused == {"error": "worker_unavailable"}
    genuine, = _control(worker, [{"op": "describe"}])
    assert "ok" in genuine
    worker.stop()
    assert [event["event"] for event in worker.events].count("session_refused") == 1


@real_worker
def test_interrupted_lying_and_malformed_streams_produce_no_ciphertext(worker):
    _workspace(worker)
    cut, lie, extra, after = _control(worker, [{"op": "cut_stream"}, {"op": "lie_digest"},
                                               {"op": "extra_frame"}, {"op": "describe"}])
    assert cut == {"sent": "partial"}
    assert lie == {"result": {"schema": backup_stream.RESULT_SCHEMA, "ok": False, "code": "stream_invalid"}}
    assert extra["result"]["code"] == "stream_invalid"
    assert "ok" in after  # the worker keeps serving after each refused stream
    worker.stop()
    outcomes = [(event["event"], event.get("outcome"), event.get("class")) for event in worker.events
                if event["event"] in ("session_served", "session_failed")]
    assert outcomes[0][0] == "session_failed"  # the cut stream: nothing encrypted, nothing returned
    assert outcomes[1:] == [("session_served", "stream_invalid", None)] * 2 + [("session_served", "served", None)]


@real_worker
def test_corruption_wrong_key_and_key_loss_are_stated_and_restore_nothing(worker):
    work, vault, _record = _workspace(worker)
    created, = _control(worker, [{"op": "create", "vault": str(vault), "out": str(work / "out")}])
    assert created["state"] == "ready", created["failure"]
    ciphertext = Path(created["ciphertext"]).read_bytes()
    flipped = bytearray(ciphertext)
    flipped[len(flipped) // 2] ^= 0x40
    forged = work / "forged.age"
    forged.write_bytes(bytes(flipped))
    forged_receipt = {**created["receipt"], "ciphertext_sha256": hashlib.sha256(bytes(flipped)).hexdigest()}
    for name in ("corrupt", "other-key", "lost"):
        (work / name).mkdir(mode=0o700)
    _own(work)
    corrupt, raw = _control(worker, [
        {"op": "restore", "ciphertext": str(forged), "receipt": forged_receipt, "staging": str(work / "corrupt")},
        {"op": "decrypt", "ciphertext": str(forged)}])
    assert corrupt["state"] == "failed" and "authenticate" in corrupt["failure"]
    assert raw == {"error": "decrypt_failed"}
    assert list((work / "corrupt").iterdir()) == []
    # the same bundle against another instance's worker (another backup-key): wrong key
    other = harness.WorkerBase()
    try:
        other.start()
        shutil.copytree(work, other.base / "control")
        _own(other.base / "control")
        wrong, = _control(other, [{"op": "restore", "ciphertext": str(other.base / "control" / "out" / Path(created["ciphertext"]).name),
                                   "receipt": created["receipt"], "staging": str(other.base / "control" / "other-key")}])
    finally:
        other.close()
    assert wrong["state"] == "failed" and "authenticate" in wrong["failure"]
    # host/volume loss: the worker's backup-key volume is gone
    worker.lose_key()
    described, lost, again = _control(worker, [
        {"op": "describe"},
        {"op": "restore", "ciphertext": created["ciphertext"], "receipt": created["receipt"],
         "staging": str(work / "lost")},
        {"op": "create", "vault": str(vault), "out": str(work / "out")}])
    assert described == {"error": "key_unavailable"}
    assert lost["state"] == "failed" and "backup-key volume" in lost["failure"]
    assert again["state"] == "failed" and "backup-key volume" in again["failure"]
    assert list((work / "lost").iterdir()) == []


@real_worker
def test_a_stale_preview_refuses_before_anything_reaches_the_worker(worker):
    from app.operations.backup import backup_preview

    work, vault, _record = _workspace(worker)
    shown = backup_preview(vault)
    fresh, = _control(worker, [{"op": "create", "vault": str(vault), "out": str(work / "out"),
                                "preview_sha": shown["preview_sha"]}])
    assert fresh["state"] == "ready", fresh["failure"]
    stale, = _control(worker, [{"op": "create", "vault": str(vault), "out": str(work / "out"),
                                "preview_sha": "0" * 64}])
    assert stale["state"] == "failed" and "preview" in stale["failure"]
    assert stale["states"] == ["backup_pending", "snapshotting", "failed"]


@real_worker
def test_a_worker_given_a_writable_or_credential_key_root_does_not_start(tmp_path):
    base = harness.WorkerBase()
    try:
        os.chmod(base.key_root, 0o700)  # the worker could write its key root
        process = subprocess.run(base.command(), cwd=REPOSITORY, env=harness.child_environment(),
                                 capture_output=True, timeout=SECONDS, check=False)
        assert process.returncode == backup_crypto_main.EXIT_CONFIG
        assert [json.loads(line)["event"] for line in process.stderr.decode().splitlines()] == ["configuration_invalid"]
        (base.key_root / "records.sqlite").write_text("credential records")
        os.chmod(base.key_root, 0o500)
        process = subprocess.run(base.command(), cwd=REPOSITORY, env=harness.child_environment(),
                                 capture_output=True, timeout=SECONDS, check=False)
        assert process.returncode == backup_crypto_main.EXIT_CONFIG
    finally:
        base.close()


@real_worker
def test_the_worker_starts_in_an_empty_network_namespace():
    base = harness.WorkerBase()
    try:
        base.start()
        assert base.networkless and base.process.poll() is None
        pid = base.process.pid
        # the worker process (under unshare and setpriv) sees only an unconfigured loopback
        children = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True, check=False).stdout.split()
        target = children[0] if children else str(pid)
        devices = Path(f"/proc/{target}/net/dev").read_text().splitlines()[2:]
        assert [line.split(":")[0].strip() for line in devices] == ["lo"]
    finally:
        base.close()
