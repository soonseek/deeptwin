"""T045 document service entrypoint (`app.workers.document_worker_main`).

The configuration tests need no privileges and run everywhere. The real-UDS tests (root on
Linux; skipped elsewhere) start the production entrypoint as a subprocess under the
document identity 20106:20106 with the pair group 21105, and the requester under the
control identity 20102:20102 (and, to be refused, the fetch identity 20104), over a pair
root generation created by the real root-only `ipc_root.initialize_pair_root`: readiness
record, socket inode, SO_PEERCRED and the boot-secret handshake are all the production
ones. The only substitution is the module-local relocation of the fixed profile.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import pytest

from app.tests.support.document_worker_children import profile
from app.tests.test_run_artifact_previews import pdf_bytes
from app.workers import document_channel, document_worker_main, ipc_root

REPOSITORY = Path(__file__).resolve().parents[2]
DOCUMENT_UID = DOCUMENT_GID = document_channel.DOCUMENT_UID
PAIR_GID = document_channel.PAIR_GID
CONTROL_UID = CONTROL_GID = 20_102
FOREIGN_UID = FOREIGN_GID = 20_104
BOOT = "control-boot-t045-document"
SECONDS = 60

real_uds = pytest.mark.skipif(
    sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED")
    or not hasattr(os, "geteuid") or os.geteuid() != 0
    or not Path("/proc/self/fd").is_dir(),
    reason="the real document entrypoint needs Linux, root and /proc/self/fd",
)


def _write(path, value):
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)
    return path


def _events(capsys):
    return [json.loads(line) for line in capsys.readouterr().err.splitlines()]


@pytest.mark.parametrize("argv", [
    ["document"], ["document", "--attachment-config=relative.json"],
    ["document", "--attachment-config=/a.json", "--attachment-config=/b.json"],
    ["document", "--attachment-config", "/a.json"], ["document", "--other=/a.json"],
])
def test_argv_outside_the_exact_shape_exits_2(argv, capsys):
    assert document_worker_main.main(argv) == document_worker_main.EXIT_CONFIG
    assert _events(capsys) == [{"event": "configuration_invalid", "class": "ValueError"}]


@pytest.mark.parametrize("mutation", ["schema", "extra", "pair_root", "boot", "not_json"])
def test_configurations_outside_the_exact_object_exit_2_before_any_bind(tmp_path, capsys, monkeypatch, mutation):
    from app.workers import listener

    monkeypatch.setattr(listener, "bind_worker_listener",
                        lambda *_a, **_k: pytest.fail("bound a listener for a refused configuration"))
    value = {"schema": document_channel.ATTACHMENT_SCHEMA, "pair_root": "/run/deeptwin/ipc/cp-document",
             "requester_boot_id": BOOT}
    changed = {"schema": {**value, "schema": "other"}, "extra": {**value, "x": 1},
               "pair_root": {**value, "pair_root": str(tmp_path / "cp-document")},
               "boot": {**value, "requester_boot_id": "-bad"}, "not_json": "{nope"}[mutation]
    path = _write(tmp_path / "attachment.json", changed)
    assert document_worker_main.main(["document", f"--attachment-config={path}"]) == document_worker_main.EXIT_CONFIG
    assert [event["event"] for event in _events(capsys)] == ["configuration_invalid"]


def test_a_missing_generation_exits_1_with_a_class_only(tmp_path, capsys):
    path = _write(tmp_path / "attachment.json", {"schema": document_channel.ATTACHMENT_SCHEMA,
                                                 "pair_root": "/run/deeptwin/ipc/cp-document",
                                                 "requester_boot_id": BOOT})
    assert document_worker_main.main(["document", f"--attachment-config={path}"]) == document_worker_main.EXIT_SERVICE
    events = _events(capsys)
    assert [event["event"] for event in events] == ["document_unavailable"]
    assert set(events[0]) == {"event", "class"}


# --- the real entrypoint over a real UDS ----------------------------------------------

def _environment():
    return {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(REPOSITORY), "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8"}


@pytest.fixture
def base():
    directory = Path(tempfile.mkdtemp(prefix="dt-t045-document-", dir="/tmp")).resolve()
    try:
        os.chmod(directory, 0o755)
        (directory / "cp-document").mkdir(mode=0o700)
        root, _spec = profile(directory)
        ipc_root.initialize_pair_root(root)
        config = directory / "config"
        config.mkdir(mode=0o755)
        attachment = _write(config / "attachment.json", {
            "schema": document_channel.ATTACHMENT_SCHEMA, "pair_root": str(directory / "cp-document"),
            "requester_boot_id": BOOT})
        os.chmod(attachment, 0o644)
        document = config / "report.pdf"
        document.write_bytes(pdf_bytes(3))
        os.chmod(document, 0o644)
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class Worker:
    def __init__(self, directory):
        self.process = subprocess.Popen(
            [sys.executable, "-B", "-m", "app.tests.support.document_worker_children", "serve", str(directory),
             f"--attachment-config={directory / 'config' / 'attachment.json'}"],
            cwd=REPOSITORY, env=_environment(), user=DOCUMENT_UID, group=DOCUMENT_GID,
            extra_groups=[PAIR_GID], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines: list[str] = []
        self._changed = threading.Condition()
        threading.Thread(target=self._read, daemon=True).start()
        self.wait_for("document_ready")

    def _read(self):
        for raw in self.process.stderr:
            with self._changed:
                self.lines.append(raw.decode(errors="replace").rstrip("\n"))
                self._changed.notify_all()
        with self._changed:
            self._changed.notify_all()

    def events(self):
        with self._changed:
            return [json.loads(line) for line in self.lines if line.startswith("{")]

    def wait_for(self, name, count=1):
        limit = time.monotonic() + SECONDS
        with self._changed:
            while sum(1 for line in self.lines if f'"event": "{name}"' in line) < count:
                if self.process.poll() is not None:
                    pytest.fail(f"document worker exited before {name}: {self.lines}")
                remaining = limit - time.monotonic()
                if remaining <= 0:
                    pytest.fail(f"document worker never logged {name}: {self.lines}")
                self._changed.wait(min(remaining, 0.5))

    def stop(self):
        self.process.send_signal(signal.SIGTERM)
        try:
            return self.process.wait(SECONDS)
        finally:
            if self.process.poll() is None:
                self.process.kill()


def _request(directory, *, page=1, edge=800, uid=CONTROL_UID, gid=CONTROL_GID, boot=BOOT):
    child = subprocess.run(
        [sys.executable, "-B", "-m", "app.tests.support.document_worker_children", "request", str(directory)],
        cwd=REPOSITORY, env=_environment(), user=uid, group=gid, extra_groups=[PAIR_GID],
        input=json.dumps({"boot": boot, "document": str(directory / "config" / "report.pdf"), "page": page,
                          "edge": edge}).encode(), capture_output=True, timeout=SECONDS)
    assert child.returncode == 0, child.stderr.decode(errors="replace")[-2000:]
    return json.loads(child.stdout)


@real_uds
def test_the_entrypoint_renders_for_the_control_identity_and_refuses_others(base):
    worker = Worker(base)
    try:
        rendered = _request(base, page=2, edge=500)
        assert rendered["ok"] is True and rendered["digest_matches"] is True
        assert rendered["page_count"] == 3 and max(rendered["width"], rendered["height"]) == 500
        missing = _request(base, page=7)
        assert missing == {"ok": False, "code": "page_out_of_range", "sent": True, "page_count": 3}
        # a foreign service identity is refused by SO_PEERCRED before any frame
        foreign = _request(base, uid=FOREIGN_UID, gid=FOREIGN_GID)
        assert foreign["ok"] is False and foreign["code"] == "unavailable" and foreign["sent"] is False
        # a requester under another boot label fails the handshake
        other = _request(base, boot="control-boot-other")
        assert other["ok"] is False and other["sent"] is False
        worker.wait_for("session_served", 2)
    finally:
        code = worker.stop()
    assert code == document_worker_main.EXIT_OK
    names = [event["event"] for event in worker.events()]
    assert names[0] == "document_ready" and names[-1] == "document_stopped"
    assert {"outcome": "ok", "event": "session_served"} in worker.events()
    assert {"outcome": "page_out_of_range", "event": "session_served"} in worker.events()
    for event in worker.events():
        assert set(event) <= {"event", "class", "outcome"}
    endpoint = base / "cp-document" / ipc_root.ENDPOINT_NAME
    assert not (endpoint / document_channel.SOCKET_NAME).exists()
    assert not (endpoint / ipc_root.LISTENER_NAME).exists()
