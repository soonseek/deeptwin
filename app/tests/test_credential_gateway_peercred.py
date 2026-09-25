"""T090 credential gateway over a real Unix-domain socket with kernel peer credentials.

Unlike the in-process harness (``verify_peer=False`` seams, a path-based
``connect_verified``), nothing here substitutes any broker, handshake, listener or
connect step: the gateway and the control plane run as separate processes under
the fixed numeric service identities of the production ``cp-provider`` profile,
the socket is addressed through ``/proc/self/fd``, and every peer check reads
``SO_PEERCRED`` from the kernel. The only relocation is the pair root, moved into
an owned temporary directory. Requires Linux and root (to start children under
other identities); skipped otherwise.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from app.tests.support.credential_peercred_child import profile
from app.tests.test_credential_custody import metadata
from app.workers import gateway_channel, ipc_root
from app.workers.credential_contracts import b64u

REPOSITORY = Path(__file__).resolve().parents[2]
CONTROL_UID = CONTROL_GID = 20_102
PROVIDER_UID = gateway_channel.PROVIDER_UID
PROVIDER_GID = gateway_channel.PROVIDER_GID
PAIR_GID = gateway_channel.PAIR_GID
FOREIGN_UID = FOREIGN_GID = 20_104  # the fetch service's identity: never a gateway peer
SECRET = b"sk-synthetic-peercred-gateway-0001"
REPLAY_SECRET = b"sk-synthetic-peercred-replay-0002"
CHILD_SECONDS = 60

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED")
    or not hasattr(os, "geteuid") or os.geteuid() != 0
    or not Path("/proc/self/fd").is_dir(),
    reason="real SO_PEERCRED qualification needs Linux, root and /proc/self/fd",
)


@pytest.fixture
def base():
    # pytest's own temporary base is 0700 root-only; the service identities must be
    # able to traverse to their pair root, so an owned 0755 directory is used instead
    directory = Path(tempfile.mkdtemp(prefix="dt-t090-peercred-", dir="/tmp")).resolve()
    try:
        os.chmod(directory, 0o755)
        (directory / "cp-provider").mkdir(mode=0o700)
        vault = directory / "vault"
        vault.mkdir(mode=0o700)
        os.chown(vault, PROVIDER_UID, PROVIDER_GID)
        root, _spec = profile(directory)
        ipc_root.initialize_pair_root(root)
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _child_environment():
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPOSITORY), "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8"}


def _spawn(config, *, uid, gid, groups):
    process = subprocess.Popen(
        [sys.executable, "-B", "-m", "app.tests.support.credential_peercred_child"],
        cwd=REPOSITORY, env=_child_environment(), user=uid, group=gid, extra_groups=list(groups),
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    process.stdin.write(json.dumps(config).encode())
    process.stdin.close()
    return process


def _read_line(process):
    readable, _, _ = select.select([process.stdout], [], [], CHILD_SECONDS)
    if not readable:
        process.kill()
        pytest.fail("child produced no output in time")
    line = process.stdout.readline()
    if not line:
        process.wait(5)
        pytest.fail("child exited early: " + process.stderr.read().decode(errors="replace")[-2000:])
    return json.loads(line)


def _finish(process):
    try:
        process.wait(CHILD_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(5)
        pytest.fail("child did not exit in time")
    error_output = process.stderr.read().decode(errors="replace")
    assert process.returncode == 0, error_output[-2000:]
    return error_output


def start_gateway(directory, sessions):
    server = _spawn({"role": "serve", "base": str(directory), "vault_id": str(uuid4()),
                     "sessions": sessions}, uid=PROVIDER_UID, gid=PROVIDER_GID, groups=(PAIR_GID,))
    assert _read_line(server) == "ready"
    return server


def run_control(directory, steps, *, uid=CONTROL_UID, gid=CONTROL_GID):
    child = _spawn({"role": "request", "base": str(directory), "steps": steps},
                   uid=uid, gid=gid, groups=(PAIR_GID,))
    result = _read_line(child)
    _finish(child)
    return result


def finish_gateway(server):
    summary = _read_line(server)
    _finish(server)
    return summary


def journal_counts(directory):
    path = directory / "vault" / "records" / "journal.sqlite"
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
        return tuple(db.execute("SELECT count(*) FROM " + table).fetchone()[0]
                     for table in ("commands", "nonces", "receipts", "retirements"))


def assert_no_secret_bytes(directory, *secrets):
    for path in directory.rglob("*"):
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            for secret in secrets:
                assert secret not in data
                assert sha256(secret).hexdigest().encode() not in data


def test_the_real_socket_serves_store_query_replay_snapshot_and_retire_under_kernel_identities(base):
    meta = metadata()
    server = start_gateway(base, sessions=6)
    try:
        first = run_control(base, [
            {"op": "store_at", "metadata": meta, "secret_b64u": b64u(SECRET)},
            {"op": "query_record", "metadata": meta},
            # an identical command id with different bytes is a replay: the original
            # receipt returns and the new secret is never decoded, sealed or stored
            {"op": "store_at", "metadata": meta, "secret_b64u": b64u(REPLAY_SECRET)},
            {"op": "snapshot"},
        ])
        assert first["identity"] == [CONTROL_UID, CONTROL_GID, [PAIR_GID]]
        stored, queried, replayed, listing = (entry["ok"] for entry in first["results"])
        assert stored["state"] == "stored_unbound" and stored["command_id"] == meta["command_id"]
        assert queried == stored and replayed == stored
        assert listing == [stored]
        reference = {key: stored[key] for key in ("record_id", "record_version", "ciphertext_sha256")}
        second = run_control(base, [
            {"op": "retire", "command_id": str(uuid4()), "record": reference, "reason": "owner_delete"},
            {"op": "query_record", "metadata": meta},
        ])
        retired, after = (entry["ok"] for entry in second["results"])
    finally:
        summary = finish_gateway(server)
    assert retired["state"] == "cleanup_pending" and retired["record"] == reference
    assert after["state"] == "cleanup_pending"
    assert summary["outcomes"] == ["served"] * 6
    assert summary["health"]["cleanup_pending"] == 1 and summary["health"]["stored_unbound"] == 0
    assert journal_counts(base) == (1, 1, 1, 1)  # one ingestion despite the replayed secret
    assert_no_secret_bytes(base, SECRET, REPLAY_SECRET)
    # the listener unlinked its socket and readiness record on close
    assert not (base / "cp-provider" / ipc_root.ENDPOINT_NAME / gateway_channel.SOCKET_NAME).exists()


@pytest.mark.parametrize("wrong", ["uid", "gid"])
def test_a_wrong_requester_identity_is_refused_by_the_kernel_check_with_zero_vault_effect(base, wrong):
    uid, gid = (FOREIGN_UID, CONTROL_GID) if wrong == "uid" else (CONTROL_UID, FOREIGN_GID)
    meta = metadata()
    server = start_gateway(base, sessions=2)
    try:
        # the wrong peer holds the pair group, so the socket mode admits its connect:
        # only the gateway's SO_PEERCRED check stands between it and the vault
        refused = run_control(base, [
            {"op": "store_at", "metadata": meta, "secret_b64u": b64u(SECRET)},
        ], uid=uid, gid=gid)
        assert refused["identity"][:2] == [uid, gid]
        assert refused["results"] == [{"error": "credential_operation_rejected",
                                       "message": "gateway channel failed"}]
        # the same listener still serves the genuine control identity afterwards
        genuine = run_control(base, [{"op": "query_record", "metadata": meta}])
    finally:
        summary = finish_gateway(server)
    assert summary["outcomes"] == ["refused:PeerCredentialError", "served"]
    assert genuine["results"] == [{"ok": {"command_id": meta["command_id"], "state": "unknown",
                                          "terminal": False}}]
    assert journal_counts(base) == (0, 0, 0, 0)
    assert_no_secret_bytes(base, SECRET)


def test_an_impostor_responder_is_refused_by_the_requester_before_any_byte(base):
    # root (not the provider identity) listens on a socket file that carries the exact
    # expected owner, group and mode: every path/inode check passes and only the
    # requester's SO_PEERCRED check can tell the impostor apart
    root, spec = profile(base)
    path = root.endpoint_path / spec.socket_name
    impostor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        impostor.bind(str(path))
        os.chown(path, spec.socket_uid, spec.socket_gid)
        os.chmod(path, spec.socket_mode)
        assert stat.S_IMODE(path.lstat().st_mode) == spec.socket_mode
        impostor.listen(1)
        child = _spawn({"role": "connect_only", "base": str(base)},
                       uid=CONTROL_UID, gid=CONTROL_GID, groups=(PAIR_GID,))
        outcome = _read_line(child)
        _finish(child)
        assert outcome == {"refused": "PeerCredentialError"}
        impostor.settimeout(5)
        accepted, _ = impostor.accept()
        with accepted:
            accepted.settimeout(5)
            assert accepted.recv(1) == b""  # the requester wrote nothing before refusing
    finally:
        impostor.close()
        path.unlink(missing_ok=True)
