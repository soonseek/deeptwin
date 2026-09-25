"""Test-only harness: a real backup-crypto worker process on a relocated `cp-backup` pair (T070).

Used by app/tests/test_backup_crypto_worker.py and the real-browser fixture
app/tests/fixtures/backup_server.py. Requires Linux and root (to initialize the pair root
and start the worker under the backup identity). Nothing here substitutes a broker,
handshake, listener or connect step:

- the pair root generation is created by the real root-only `ipc_root.initialize_pair_root`
  in an owned 0755 base under /tmp (the scratch roots of the test runner are root-only and
  would not be traversable by the service identities);
- the locked age 1.3.2 binaries are copied from ``DEEPTWIN_AGE_RUNTIME_ROOT`` into
  ``<base>/age`` (0755), because that root may be readable by root only; the worker
  re-verifies their locked digests itself;
- the backup-key volume is initialized by the real `backup-key-init`
  (`initialize_backup_key` with the verified `age-keygen`), then handed to the backup
  identity and made read-only (directory 0500): the control identity cannot traverse it;
- the worker is the production entrypoint (`backup_crypto_launcher`) started with
  ``unshare --net`` (an empty network namespace: only an unconfigured loopback exists)
  and ``setpriv`` to 20111:20111 with the pair group 21109 and no inheritable
  capabilities.
"""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[3]
BACKUP_UID = BACKUP_GID = 20_111
CONTROL_UID = CONTROL_GID = 20_102
PAIR_GID = 21_109
BOOT = "control-boot-t070-backup"
READY_SECONDS = 60


def available() -> str | None:
    """None when a real worker can run here, else why not."""

    if sys.platform != "linux" or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return "the real backup worker needs Linux and root"
    if not os.environ.get("DEEPTWIN_AGE_RUNTIME_ROOT"):
        return "DEEPTWIN_AGE_RUNTIME_ROOT (the verified locked age 1.3.2) is not set"
    if shutil.which("setpriv") is None:
        return "setpriv is not installed"
    return None


def child_environment() -> dict:
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPOSITORY), "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8"}


def _write(path: Path, value) -> Path:
    path.write_text(json.dumps(value))
    os.chmod(path, 0o644)
    return path


class WorkerBase:
    """One owned base: pair root, age copy, key volume, configurations."""

    def __init__(self, directory: Path | None = None, *, key: bool = True):
        from app.operations.backup import age_keygen
        from app.operations.backup_key import initialize_backup_key
        from app.tests.support.backup_crypto_launcher import backup_profile
        from app.workers import ipc_root
        from app.workers.backup_channel import ATTACHMENT_SCHEMA
        from app.workers.backup_crypto import AgeRuntime
        from app.workers.backup_crypto_main import SERVICE_SCHEMA

        self.owned = directory is None
        if directory is not None:
            Path(directory).mkdir(mode=0o755)
        self.base = Path(directory or tempfile.mkdtemp(prefix="dt-t070-backup-", dir="/tmp")).resolve()
        os.chmod(self.base, 0o755)
        (self.base / "cp-backup").mkdir(mode=0o700)
        self.root, self.spec = backup_profile(self.base)
        ipc_root.initialize_pair_root(self.root)
        self.age_root = self.base / "age"
        self.age_root.mkdir(mode=0o755)
        source = Path(os.environ["DEEPTWIN_AGE_RUNTIME_ROOT"])
        for name in ("age", "age-keygen"):
            shutil.copyfile(source / name, self.age_root / name)
            os.chmod(self.age_root / name, 0o755)
        self.runtime = AgeRuntime.open(self.age_root)
        self.key_root = self.base / "backup-key"
        self.key_root.mkdir(mode=0o700)
        self.recipient = None
        if key:
            self.recipient = initialize_backup_key(self.key_root, keygen=age_keygen(self.runtime)).recipient
        for path in (self.key_root, *self.key_root.iterdir()):
            os.chown(path, BACKUP_UID, BACKUP_GID)
        os.chmod(self.key_root, 0o500)
        self.service_config = _write(self.base / "backup-service.json", {
            "schema": SERVICE_SCHEMA, "key_root": str(self.key_root), "age_root": str(self.age_root)})
        self.attachment_config = _write(self.base / "backup-attachment.json", {
            "schema": ATTACHMENT_SCHEMA, "pair_root": str(self.root.pair_root), "requester_boot_id": BOOT})
        self.process = None
        self.networkless = False

    # --- the worker process ---------------------------------------------------------

    def command(self, *, service_config=None, attachment_config=None) -> list[str]:
        argv = [sys.executable, "-B", "-m", "app.tests.support.backup_crypto_launcher", str(self.base),
                f"--service-config={service_config or self.service_config}",
                f"--attachment-config={attachment_config or self.attachment_config}"]
        drop = ["setpriv", f"--reuid={BACKUP_UID}", f"--regid={BACKUP_GID}", f"--groups={PAIR_GID}",
                "--inh-caps=-all", "--no-new-privs"]
        self.networkless = shutil.which("unshare") is not None
        prefix = ["unshare", "--net", "--"] if self.networkless else []
        return [*prefix, *drop, *argv]

    def start(self, *, die_with_parent=False, **kwargs) -> subprocess.Popen:
        environment = child_environment()
        if die_with_parent:
            environment["DEEPTWIN_TEST_DIE_WITH_PARENT"] = "1"
        self.process = subprocess.Popen(self.command(**kwargs), cwd=REPOSITORY, env=environment,
                                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                        stderr=subprocess.PIPE)
        self.events = []
        self.wait_for("backup_worker_ready")
        return self.process

    def wait_for(self, event: str, seconds: float = READY_SECONDS) -> dict:
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            readable, _, _ = select.select([self.process.stderr], [], [], max(0.0, end - time.monotonic()))
            if not readable:
                break
            line = self.process.stderr.readline()
            if not line:
                self.process.wait(5)
                raise RuntimeError(f"the backup worker exited early ({self.process.returncode}): "
                                   + json.dumps(self.events))
            record = json.loads(line)
            self.events.append(record)
            if record.get("event") == event:
                return record
        raise RuntimeError(f"the backup worker did not report {event}: " + json.dumps(self.events))

    def stop(self) -> int | None:
        if self.process is None:
            return None
        if self.process.poll() is None:
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        rest = self.process.stderr.read().decode(errors="replace")
        self.events.extend(json.loads(line) for line in rest.splitlines() if line.startswith("{"))
        return self.process.returncode

    def close(self) -> None:
        try:
            self.stop()
        finally:
            if self.owned:
                shutil.rmtree(self.base, ignore_errors=True)

    def lose_key(self) -> None:
        """The backup-key volume is gone (host or volume loss)."""

        os.chmod(self.key_root, 0o700)
        shutil.rmtree(self.key_root)
