"""Finite test-owned supported app with a real backup-crypto worker, for the browser case (T073).

Two roles in one file:

- ``supervisor`` (the default; root on Linux, started by app/tests/browser-backup.test.mjs):
  prepares the owned base through ``backup_worker_harness.WorkerBase`` (the real root-only
  pair-root initializer on a relocated `cp-backup` root, the locked age copy, the real
  backup-key-init volume handed read-only to the backup identity), starts the production
  worker entrypoint in an empty network namespace as 20111:20111 with the pair group,
  then starts the ``app`` role as the control identity 20102:20102 with the pair group,
  relays its announcement lines and stops both children when it is stopped.
- ``app`` (the control identity): the supported factory ``create_app`` with
  ``backup_worker`` naming the relocated endpoint; nothing is seeded. The owner
  bootstraps, saves a work, previews, consents and restores only through the product
  routes. Both children die with the supervisor (PR_SET_PDEATHSIG).

The only relocation is the pair root (module-local, as every real-UDS test child does).
No model, tool, network or paid call; every value is synthetic test-actor data.
"""
import argparse
import base64
import json
import os
import signal
import socket
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.tests.support import backup_worker_harness as harness


def app_role(owned: Path) -> None:
    import uvicorn

    from app.operations.session_root import initialize_session_root
    from app.operations.setup import (
        OriginProfile,
        build_bootstrap_configuration,
        derive_capability_verifier,
    )
    from app.server import create_app
    from app.tests.support.backup_crypto_launcher import die_with_parent, relocate
    from app.workers.backup_channel import BackupWorkerConfiguration

    die_with_parent()
    base = owned / "worker"
    relocate(base)
    control = owned / "control"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(control / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    app = create_app(control / "data", deployment_config=configuration, session_root_dir=control / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(),
                     backup_worker=BackupWorkerConfiguration(pair_root=str(base / "cp-backup"),
                                                             requester_boot_id=harness.BOOT))
    print(f"BACKUP_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                      timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


def supervisor(owned: Path) -> int:
    reason = harness.available()
    if reason is not None:
        print(f"BACKUP_UNAVAILABLE={reason}", flush=True)
        return 3
    os.chmod(owned, 0o755)
    worker = harness.WorkerBase(owned / "worker")
    control = owned / "control"
    control.mkdir(mode=0o700)
    os.chown(control, harness.CONTROL_UID, harness.CONTROL_GID)
    app = None
    stopping = []

    def stop(_signum=None, _frame=None):
        stopping.append(True)
        if app is not None and app.poll() is None:
            app.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        worker.start(die_with_parent=True)
        print(f"BACKUP_WORKER_NETWORKLESS={json.dumps(worker.networkless)}", flush=True)
        app = subprocess.Popen(
            ["setpriv", f"--reuid={harness.CONTROL_UID}", f"--regid={harness.CONTROL_GID}",
             f"--groups={harness.PAIR_GID}", "--inh-caps=-all", "--no-new-privs",
             sys.executable, "-B", str(Path(__file__).resolve()), "--role=app", "--owned-dir", str(owned)],
            cwd=harness.REPOSITORY, env={**harness.child_environment(), "LANGSMITH_TRACING": "false"},
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=None)
        for line in app.stdout:
            sys.stdout.write(line.decode(errors="replace"))
            sys.stdout.flush()
        return app.wait()
    finally:
        if app is not None and app.poll() is None:
            app.terminate()
            try:
                app.wait(5)
            except subprocess.TimeoutExpired:
                app.kill()
        worker.stop()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--role", choices=("supervisor", "app"), default="supervisor")
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if args.role == "app":
        app_role(owned)
        return 0
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    return supervisor(owned)


if __name__ == "__main__":
    sys.exit(main())
