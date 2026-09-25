"""Test-only control-plane child for the real backup-crypto worker (T070).

The parent test (root on Linux) starts this under the control identity 20102:20102 with
the pair group 21109, so the worker's SO_PEERCRED check sees the kernel's identity. The
only substitution is the module-local relocation of the fixed `cp-backup` profile into
the owned base (``backup_crypto_launcher.relocate``). The control side runs the real
`create_backup` / `restore_backup` with the real `BackupCryptoClient` as their crypto
port: it never receives a key handle. The config arrives on stdin as JSON; each step's
secret-free result is one JSON line on stdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path


def _emit(value) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")
    sys.stdout.flush()


def _client(base: Path, boot: str):
    from app.workers.backup_channel import BackupWorkerConfiguration
    from app.workers.backup_crypto_client import BackupCryptoClient

    return BackupCryptoClient.for_worker(BackupWorkerConfiguration(
        pair_root=str(base / "cp-backup"), requester_boot_id=boot), deadline_ms=60_000)


def _raw(base: Path, boot: str):
    from app.tests.support.backup_crypto_launcher import backup_profile
    from app.workers import broker, listener

    root, spec = backup_profile(base)
    deadline = broker.Deadline.after_ms(30_000)
    return listener.connect_authenticated(root, spec, requester_boot_id=boot, deadline=deadline), deadline


def step(value, base: Path, boot: str):
    from app.operations.backup import create_backup, restore_backup
    from app.workers import backup_stream as stream
    from app.workers.backup_crypto_client import BackupWorkerError

    op = value["op"]
    client = _client(base, boot)
    if op == "describe":
        try:
            return {"ok": client.describe()}
        except BackupWorkerError as error:
            return {"error": error.code}
    if op == "create":
        outcome = create_backup(value["vault"], value["out"], crypto=client, key_mode="instance_backup_key",
                                server_release="1.0.0", expected_preview_sha=value.get("preview_sha"))
        return {"state": outcome.state, "states": list(outcome.states), "failure": outcome.failure,
                "receipt": outcome.receipt, "manifest": outcome.manifest,
                "ciphertext": None if outcome.ciphertext_path is None else str(outcome.ciphertext_path)}
    if op == "restore":
        outcome = restore_backup(value["ciphertext"], value["receipt"], value["staging"], crypto=client,
                                 active_vault_dir=value.get("active"))
        return {"state": outcome.state, "failure": outcome.failure, "checked": list(outcome.checked),
                "vault": None if outcome.vault_dir is None else str(outcome.vault_dir)}
    if op == "decrypt":
        try:
            client.decrypt(Path(value["ciphertext"]).read_bytes(), key_mode="instance_backup_key")
            return {"ok": True}
        except BackupWorkerError as error:
            return {"error": error.code}
    if op == "read_key":
        try:
            Path(value["path"]).read_bytes()
            return {"read": True}
        except OSError as error:
            return {"read": False, "class": type(error).__name__}
    if op in ("cut_stream", "lie_digest", "extra_frame"):
        connection, deadline = _raw(base, boot)
        body = b"typed archive bytes " * 4096
        declared = hashlib.sha256(body).hexdigest() if op != "lie_digest" else hashlib.sha256(b"other").hexdigest()
        stream.write_message(connection, stream.REQUEST, {
            "schema": stream.REQUEST_SCHEMA, "op": "encrypt", "key_mode": "instance_backup_key",
            "recipient": None, "identity": None, "size": len(body), "sha256": declared}, deadline=deadline)
        if op == "cut_stream":
            # half the archive, then the control side goes away mid-stream
            connection.write(message_id="00000000-0000-4000-8000-000000000001", correlation_id=None,
                             message_type=stream.CHUNK, payload=body[:stream.CHUNK_BYTES], deadline=deadline)
            connection.close()
            return {"sent": "partial"}
        if op == "extra_frame":
            connection.write(message_id="00000000-0000-4000-8000-000000000002", correlation_id=None,
                             message_type=stream.REQUEST, payload=b"{}", deadline=deadline)
        else:
            stream.write_body(connection, body, deadline=deadline)
        try:
            _id, result = stream.read_message(connection, stream.RESULT, deadline=deadline)
            return {"result": result}
        except Exception as error:  # noqa: BLE001 - recorded by class only
            return {"closed": type(error).__name__}
        finally:
            connection.close()
    raise ValueError("unknown step")


def main() -> int:
    from app.tests.support.backup_crypto_launcher import relocate

    config = json.loads(sys.stdin.read())
    base = Path(config["base"])
    relocate(base)
    _emit({"identity": [os.geteuid(), os.getegid(), sorted(os.getgroups())]})
    for value in config["steps"]:
        _emit(step(value, base, config["boot"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
