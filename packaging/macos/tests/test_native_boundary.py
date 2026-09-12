"""Actual local N0 canary. No provider, user secret, browser or OS policy changes."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import plistlib
import socket
import subprocess
import tempfile
import threading
import time
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "app/native/worker_bridge/feasibility"


def test_native_canary_has_closed_policy_and_real_sources():
    for name in ("Host.m", "Worker.m", "Probe.m", "Protocol.h", "Checks.h"):
        assert (SOURCE / name).is_file(), name
    worker = plistlib.loads((SOURCE / "Worker.entitlements.plist").read_bytes())
    inherit = plistlib.loads((SOURCE / "Inherit.entitlements.plist").read_bytes())
    assert worker == {"com.apple.security.app-sandbox": True}
    assert inherit == {"com.apple.security.app-sandbox": True, "com.apple.security.inherit": True}


class Sink:
    def __init__(self, family, style):
        self.sock = socket.socket(family, style)
        self.sock.bind(("::1" if family == socket.AF_INET6 else "127.0.0.1", 0))
        if style == socket.SOCK_STREAM:
            self.sock.listen(8)
        self.sock.settimeout(.1)
        self.port = self.sock.getsockname()[1]
        self.style = style
        self.receipts = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.receive, daemon=True)
        self.thread.start()

    def receive(self):
        while not self.stop.is_set():
            try:
                if self.style == socket.SOCK_STREAM:
                    peer, _ = self.sock.accept()
                    with peer:
                        peer.settimeout(1)
                        data = peer.recv(1024)
                else:
                    data, _ = self.sock.recvfrom(1024)
                self.receipts.append(data.decode("ascii", errors="replace"))
            except (TimeoutError, OSError):
                pass

    def close(self):
        self.stop.set()
        self.sock.close()
        self.thread.join(timeout=2)
        assert not self.thread.is_alive()


def command(argv, *, timeout=40):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    assert result.returncode == 0, f"{argv!r}\n{result.stdout}\n{result.stderr}"
    return result


def build_bundle(build, *, deny_peer=False):
    app = build / ("DenyCanary.app" if deny_peer else "DeepTwinCanary.app")
    xpc = app / "Contents/XPCServices/DeepTwinWorker.xpc"
    for path in (app / "Contents/MacOS", xpc / "Contents/MacOS", xpc / "Contents/Helpers"):
        path.mkdir(parents=True)
    tag = "deny" if deny_peer else "normal"
    worker_id = f"org.deeptwin.n0.{build.name}.{tag}.worker"
    host_info = dict(CFBundleIdentifier=f"org.deeptwin.n0.{build.name}.{tag}.host",
                     CFBundleExecutable="DeepTwinCanary", CFBundlePackageType="APPL",
                     CFBundleVersion="1", NSPrincipalClass="NSApplication", LSUIElement=True,
                     NativeWorkerIdentifier=worker_id, NativeExpectDenied=deny_peer)
    worker_info = dict(CFBundleIdentifier=worker_id, CFBundleExecutable="DeepTwinWorker",
                       CFBundlePackageType="XPC!", CFBundleVersion="1",
                       XPCService=dict(ServiceType="Application"), NativeDenyPeer=deny_peer)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps(host_info))
    (xpc / "Contents/Info.plist").write_bytes(plistlib.dumps(worker_info))
    sdk = command(["xcrun", "--show-sdk-path"]).stdout.strip()
    flags = ["xcrun", "clang", "-target", "arm64-apple-macos26.5.1", "-isysroot", sdk,
             "-fobjc-arc", "-fblocks", "-Wall", "-Wextra", "-Werror",
             "-framework", "Foundation", "-framework", "Security"]
    targets = [("Host.m", app / "Contents/MacOS/DeepTwinCanary"),
               ("Worker.m", xpc / "Contents/MacOS/DeepTwinWorker"),
               ("Probe.m", xpc / "Contents/Helpers/DeepTwinProbe")]
    for source, target in targets:
        command(flags + [str(SOURCE / source), "-o", str(target)])
    for target, entitlements in ((targets[2][1], "Inherit.entitlements.plist"),
                                 (xpc, "Worker.entitlements.plist"), (app, None)):
        args = ["codesign", "--force", "--sign", "-", "--options", "runtime"]
        if entitlements:
            args += ["--entitlements", str(SOURCE / entitlements)]
        command(args + [str(target)])
        command(["codesign", "--verify", "--strict", "--verbose=2", str(target)])
    return app


@pytest.fixture(scope="module")
def native_run():
    build = Path(tempfile.mkdtemp(prefix="deeptwin-n0-"))
    print(f"N0_BUILD={build}", flush=True)
    private = Path.home() / "Library/Application Support/DeepTwinCanaryFixtures" / build.name
    private.mkdir(parents=True, exist_ok=False)
    secret = private / "synthetic-private.txt"
    original = b"synthetic-native-canary-" + uuid.uuid4().hex.encode()
    secret.write_bytes(original)
    os.chmod(private, 0o700)
    os.chmod(secret, 0o600)
    with ExitStack() as stack:
        sinks = {}
        for key, family, style in (("tcp4", socket.AF_INET, socket.SOCK_STREAM),
                                    ("tcp6", socket.AF_INET6, socket.SOCK_STREAM),
                                    ("udp4", socket.AF_INET, socket.SOCK_DGRAM),
                                    ("udp6", socket.AF_INET6, socket.SOCK_DGRAM)):
            sink = Sink(family, style)
            stack.callback(sink.close)
            sinks[key] = sink
        config = dict(generation=uuid.uuid4().hex, ports={k: v.port for k, v in sinks.items()},
                      private_path=str(secret), fixture_root=str(private))
        request = build / "request.json"
        request.write_text(json.dumps(config))
        result = build / "native-results.json"
        app = build_bundle(build)
        command(["open", "-W", "-n", str(app), "--args", "--config", str(request), "--result", str(result)], timeout=55)
        assert result.is_file(), f"No canary result; stop for launch/prompt review: {build}"
        report = json.loads(result.read_text())
        time.sleep(.25)  # bounded delivery fence; sink positive controls are asserted below
        receipts = {k: list(v.receipts) for k, v in sinks.items()}
        receipt_path = build / "sink-receipts.json"
        receipt_path.write_text(json.dumps(receipts, indent=2))
        (build / "source-manifest.json").write_text(json.dumps({str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [*SOURCE.iterdir(), Path(__file__)] if p.is_file()}, indent=2))
        yield dict(build=build, app=app, config=request, report=report, receipts=receipts,
                   original=original, current=secret.read_bytes())
    # Only this exact generated synthetic fixture is removed, never a user original.
    secret.unlink()
    private.rmdir()


def test_actual_xpc_and_child_handshake(native_run):
    report = native_run["report"]
    assert report.get("worker", {}).get("role") == "worker", report
    assert report["worker"]["pid"] != report["host_pid"]
    assert report["child"]["role"] == "child"
    assert report["child"]["pid"] != report["worker"]["pid"]
    assert report["worker"]["app_sandbox"] is True
    assert report["child"]["app_sandbox"] is True
    assert report["peer_auth_complete"] is False, "N0 cannot claim production peer authentication"


def test_native_direct_network_denied_with_positive_sink_controls(native_run):
    report = native_run["report"]
    for key, receipts in native_run["receipts"].items():
        assert "host-before:" + key in receipts, (key, receipts, report)
        assert "host-after:" + key in receipts, (key, receipts, report)
        assert not any(value.startswith(("worker:", "child:")) for value in receipts), receipts
    for role in ("worker", "child"):
        assert all(not item["ok"] for item in report[role]["network"]), report[role]


def test_native_file_boundary_has_actual_positive_and_negative_controls(native_run):
    report = native_run["report"]
    assert native_run["current"] == native_run["original"], report
    for role in ("worker", "child"):
        assert report[role]["own_file_ok"] is True
        assert report[role]["private_read_ok"] is False
        assert report[role]["private_write_ok"] is False


def test_native_server_bind_is_denied_for_both_worker_generations(native_run):
    for role in ("worker", "child"):
        assert all(item["ok"] is False for item in native_run["report"][role]["servers"])


def test_wrong_peer_and_malformed_input_fail_closed(native_run):
    report = native_run["report"]
    assert report["wrong_server_rejected"] is True, report
    assert report["oversize_rejected"] is True, report
    assert report["malformed_rejected"] is True, report
    assert report["stale_rejected"] is True, report
    assert report["unknown_rejected"] is True, report


def test_worker_exit_has_no_success_reply_or_owned_child_leak(native_run):
    report = native_run["report"]
    assert report["worker_exit_observed"] is True, report
    assert report["child_exited"] is True, report
    assert report["child_status"] == 0
    for role in ("worker", "child"):
        pid = report[role]["pid"]
        assert type(pid) is int and pid > 1 and pid != os.getpid()
        deadline = time.monotonic() + 5
        while True:
            try:
                os.kill(pid, 0)  # existence check, not a termination signal
            except ProcessLookupError:
                break
            assert time.monotonic() < deadline, f"Owned {role} still alive: {pid}"
            time.sleep(.05)


def test_listener_rejects_actual_nonmatching_caller(native_run):
    assert native_run["report"].get("worker", {}).get("role") == "worker", "Positive handshake required before interpreting denial"
    app = build_bundle(native_run["build"], deny_peer=True)
    result = native_run["build"] / "denied-results.json"
    command(["open", "-W", "-n", str(app), "--args", "--config", str(native_run["config"]),
             "--result", str(result)], timeout=35)
    report = json.loads(result.read_text())
    assert report["listener_denied"] is True, report
    assert "worker" not in report
