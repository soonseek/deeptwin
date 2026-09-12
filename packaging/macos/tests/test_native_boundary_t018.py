"""Superseded former-T018 launcher and typed browser-broker feasibility tests.

The real N0 App Sandbox/XPC enforcement suite remains in test_native_boundary.py.
This module refuses to turn its deliberately open peer-auth result into a product
browser boundary while still exercising a local, broker-fulfilled Chromium capture.
ADR-009 retains it as historical experiment evidence only.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import struct
import subprocess
import sys
import threading

import pytest


ROOT = Path(__file__).resolve().parents[3]
LAUNCHER_PATH = ROOT / "packaging/macos/launcher.py"
PLAYWRIGHT_MODULE_CANDIDATES = (
    Path.home()
    / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs",
)
NODE_CANDIDATES = (
    Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
)


def load_launcher():
    spec = importlib.util.spec_from_file_location("deeptwin_macos_launcher", LAUNCHER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def local_browser_inputs():
    node = next((str(path) for path in NODE_CANDIDATES if path.is_file()), shutil.which("node"))
    playwright_module = next((path for path in PLAYWRIGHT_MODULE_CANDIDATES if path.is_file()), None)
    browsers = sorted(
        Path.home().glob(
            "Library/Caches/ms-playwright/chromium-*/chrome-mac-arm64/"
            "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
        )
    )
    if not node or playwright_module is None or not browsers:
        pytest.skip("locked/local Node, Playwright, and Chromium inputs are not all present")
    return Path(node), playwright_module, browsers[-1]


def identity_arguments(node, module, browser):
    return {
        "node_sha256": hashlib.sha256(node.read_bytes()).hexdigest(),
        "playwright_module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
        "browser_sha256": hashlib.sha256(browser.read_bytes()).hexdigest(),
        "helper_sha256": hashlib.sha256(
            (ROOT / "app/native/worker_bridge/browser_capture.mjs").read_bytes()
        ).hexdigest(),
    }


def valid_ipc_message():
    return {
        "schema": "deeptwin-browser-ipc-v1",
        "request_id": "a" * 32,
        "generation": "b" * 32,
        "action": "capture",
        "url": "https://fixture.deeptwin.invalid/t018/fixture",
        "status": 200,
        "headers": [["content-type", "text/html; charset=utf-8"]],
        "body_base64": "PGh0bWw+PC9odG1sPg==",
    }


def raw_frame(message):
    payload = json.dumps(message, separators=(",", ":")).encode()
    return struct.pack(">I", len(payload)) + payload


def open_n0_report(tmp_path):
    report = tmp_path / "n0-report.json"
    report.write_text(
        json.dumps(
            {
                "schema": "native-canary-n0-v1",
                "peer_auth_complete": False,
                "worker": {"app_sandbox": True},
                "child": {"app_sandbox": True},
                "wrong_server_rejected": True,
            }
        )
    )
    return report


def test_production_browser_boundary_fails_closed_on_open_n0_peer_auth(tmp_path):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    with pytest.raises(launcher.UnqualifiedNativeBoundary, match="peer authentication"):
        launcher.capture_browser_canary(
            node_path=node,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=tmp_path / "must-not-exist.png",
        )
    assert not (tmp_path / "must-not-exist.png").exists()


def test_standalone_launcher_reports_blocked_without_development_authority(tmp_path):
    node, module, browser = local_browser_inputs()
    output = tmp_path / "must-not-exist.png"
    result = subprocess.run(
        [
            sys.executable,
            str(LAUNCHER_PATH),
            "browser-canary",
            "--node",
            str(node),
            "--playwright-module",
            str(module),
            "--browser",
            str(browser),
            "--browser-sha256",
            hashlib.sha256(browser.read_bytes()).hexdigest(),
            "--node-sha256",
            hashlib.sha256(node.read_bytes()).hexdigest(),
            "--playwright-module-sha256",
            hashlib.sha256(module.read_bytes()).hexdigest(),
            "--helper-sha256",
            hashlib.sha256((ROOT / "app/native/worker_bridge/browser_capture.mjs").read_bytes()).hexdigest(),
            "--n0-report",
            str(open_n0_report(tmp_path)),
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 78
    assert json.loads(result.stderr)["state"] == "blocked"
    assert "peer authentication" in result.stderr
    assert not output.exists()


def test_caller_supplied_success_flags_cannot_mint_native_attestation(tmp_path):
    launcher = load_launcher()
    report = tmp_path / "fabricated-complete-report.json"
    report.write_text(
        json.dumps(
            {
                "schema": "native-canary-n0-v1",
                "peer_auth_complete": True,
                "worker": {"app_sandbox": True},
                "child": {"app_sandbox": True},
                "wrong_server_rejected": True,
                "browser_children_app_sandbox": True,
                "browser_boundary_complete": True,
            }
        )
    )
    with pytest.raises(launcher.UnqualifiedNativeBoundary, match="no authenticated native attestation"):
        launcher.capture_browser_canary(
            node_path=tmp_path / "not-consulted-node",
            playwright_module=tmp_path / "not-consulted-playwright",
            browser_path=tmp_path / "not-consulted-browser",
            node_sha256="0" * 64,
            playwright_module_sha256="0" * 64,
            browser_sha256="0" * 64,
            helper_sha256="0" * 64,
            n0_report_path=report,
            output_path=tmp_path / "must-not-exist.png",
        )
    assert not (tmp_path / "must-not-exist.png").exists()


def test_typed_protocol_rejects_unknown_oversize_and_mismatched_messages():
    launcher = load_launcher()
    valid = valid_ipc_message()
    encoded = launcher.encode_browser_request(valid)
    assert launcher.decode_browser_request(encoded) == valid
    for mutation in (
        {**valid, "action": "shell"},
        {**valid, "generation": "stale"},
        {**valid, "extra": "ambient capability"},
    ):
        with pytest.raises(launcher.ProtocolViolation):
            launcher.encode_browser_request(mutation)
    with pytest.raises(launcher.ProtocolViolation):
        launcher.decode_browser_request(b"x" * (launcher.MAX_FRAME_BYTES + 1))


@pytest.mark.parametrize(
    "duplicate",
    (
        b'"action":"capture","action":"shell"',
        b'"status":200,"status":201',
    ),
)
def test_python_and_javascript_reject_duplicate_json_keys_before_launch(duplicate):
    launcher = load_launcher()
    node, _, _ = local_browser_inputs()
    fields = [
        b'"schema":"deeptwin-browser-ipc-v1"',
        b'"request_id":"' + b"a" * 32 + b'"',
        b'"generation":"' + b"b" * 32 + b'"',
        duplicate,
        b'"url":"https://fixture.deeptwin.invalid/t018/fixture"',
        b'"status":200' if not duplicate.startswith(b'"status"') else b'"action":"capture"',
        b'"headers":[["content-type","text/html; charset=utf-8"]]',
        b'"body_base64":"PGh0bWw+PC9odG1sPg=="',
    ]
    payload = b"{" + b",".join(fields) + b"}"
    frame = struct.pack(">I", len(payload)) + payload
    with pytest.raises(launcher.ProtocolViolation, match="duplicate JSON object key"):
        launcher.decode_browser_request(frame)
    helper = ROOT / "app/native/worker_bridge/browser_capture.mjs"
    result = subprocess.run(
        [str(node), str(helper)],
        input=frame,
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        timeout=5,
    )
    assert result.returncode != 0
    assert b"duplicate_json_key" in result.stderr
    assert b"missing_owned_component_path" not in result.stderr


@pytest.mark.parametrize(
    "mutation",
    (
        {"headers": [["Content-Type", "text/html; charset=utf-8"]]},
        {
            "headers": [
                ["content-type", "text/html; charset=utf-8"],
                ["Content-Type", "text/html; charset=utf-8"],
            ]
        },
        {"headers": [["content-type", "text/plain"]]},
        {"body_base64": "PGh0bWw+PC9odG1sPg"},
        {"body_base64": base64.b64encode(b"a" * 32_769).decode()},
        {"url": "https://fixture.deeptwin.invalid/t018/" + "x" * 260},
    ),
)
def test_python_and_javascript_apply_the_same_bounded_request_policy(mutation):
    launcher = load_launcher()
    node, _, _ = local_browser_inputs()
    message = {**valid_ipc_message(), **mutation}
    frame = raw_frame(message)
    with pytest.raises(launcher.ProtocolViolation):
        launcher.decode_browser_request(frame)
    result = subprocess.run(
        [str(node), str(ROOT / "app/native/worker_bridge/browser_capture.mjs")],
        input=frame,
        capture_output=True,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        timeout=5,
    )
    assert result.returncode != 0
    assert b"invalid_capture_request" in result.stderr
    assert b"missing_owned_component_path" not in result.stderr


def test_browser_helper_has_no_direct_fetch_or_permissive_launch_fallback():
    helper = (ROOT / "app/native/worker_bridge/browser_capture.mjs").read_text()
    for forbidden in ("route.continue", "route.fetch", "--no-sandbox", "remote-debugging-port", "child_process"):
        assert forbidden not in helper


def test_python_ipc_full_write_handles_partial_syscalls(monkeypatch):
    launcher = load_launcher()
    written = bytearray()

    def partial_write(fd, value):
        chunk = bytes(value[:3])
        written.extend(chunk)
        return len(chunk)

    monkeypatch.setattr(launcher.os, "write", partial_write)
    launcher._write_all_fd(91, b"0123456789")
    assert written == b"0123456789"


def test_stderr_drain_is_bounded_without_backpressure_deadlock():
    launcher = load_launcher()
    read_fd, write_fd = os.pipe()
    payload = os.urandom(launcher.MAX_STDERR_CAPTURE_BYTES * 4)

    def writer():
        try:
            launcher._write_all_fd(write_fd, payload)
        finally:
            os.close(write_fd)

    thread = threading.Thread(target=writer)
    thread.start()
    with os.fdopen(read_fd, "rb", closefd=True) as stream:
        observation = launcher._drain_stderr(stream)
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert observation["total_bytes"] == len(payload)
    assert observation["captured_bytes"] == launcher.MAX_STDERR_CAPTURE_BYTES
    assert observation["truncated"] is True
    assert observation["sha256"] == hashlib.sha256(payload).hexdigest()


def test_real_local_chromium_capture_is_broker_fulfilled_and_children_terminate(tmp_path):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    output = tmp_path / "broker-capture.png"
    result = launcher.capture_browser_canary(
        node_path=node,
        playwright_module=module,
        browser_path=browser,
        **identity_arguments(node, module, browser),
        n0_report_path=open_n0_report(tmp_path),
        output_path=output,
        development_canary=True,
    )
    assert result["schema"] == "deeptwin-browser-capture-v1"
    assert result["status"] == "passed_development_canary"
    assert result["production_boundary_accepted"] is False
    assert result["broker_fulfilled"] is True
    assert result["unexpected_request_count"] == 0
    assert result["marker"].startswith("t018-default-marker-")
    assert result["javascript"] == "executed"
    assert result["browser_executable_sha256"] == hashlib.sha256(browser.read_bytes()).hexdigest()
    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert result["screenshot_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert result["driver_pid"] > 1
    assert result["owned_descendant_pids"]
    assert result["owned_processes_terminated"] is True
    assert result["component_identity_verified_after_run"] is True
    assert result["published_after_clean_shutdown"] is True
    for pid in [result["driver_pid"], *result["owned_descendant_pids"]]:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, signal.SIGCONT)


@pytest.mark.parametrize(
    ("field", "label"),
    (
        ("node_sha256", "Node SHA-256"),
        ("helper_sha256", "browser helper SHA-256"),
        ("playwright_module_sha256", "Playwright module SHA-256"),
        ("browser_sha256", "Chromium SHA-256"),
    ),
)
def test_each_component_hash_mismatch_stops_before_browser_spawn(tmp_path, field, label):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    identities = identity_arguments(node, module, browser)
    identities[field] = "0" * 64
    with pytest.raises(launcher.ComponentIntegrityError, match=label):
        launcher.capture_browser_canary(
            node_path=node,
            playwright_module=module,
            browser_path=browser,
            **identities,
            n0_report_path=open_n0_report(tmp_path),
            output_path=tmp_path / "must-not-exist.png",
            development_canary=True,
        )
    assert not (tmp_path / "must-not-exist.png").exists()


def test_symlinked_component_and_ancestor_are_rejected_before_spawn(tmp_path):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    linked_node = tmp_path / "node-link"
    linked_node.symlink_to(node)
    with pytest.raises(launcher.ComponentIntegrityError, match="symlink"):
        launcher.capture_browser_canary(
            node_path=linked_node,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=tmp_path / "must-not-exist.png",
            development_canary=True,
        )


def test_authorized_component_detects_deterministic_path_replacement(tmp_path):
    launcher = load_launcher()
    component = tmp_path / "component.bin"
    component.write_bytes(b"authorized-component-v1")
    authorized = launcher._authorize_component(
        component,
        "test component",
        hashlib.sha256(component.read_bytes()).hexdigest(),
    )
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"unauthorized-component-v2")
    os.replace(replacement, component)
    try:
        with pytest.raises(launcher.ComponentIntegrityError, match="changed after authorization"):
            launcher._verify_authorized_component(authorized)
    finally:
        launcher._close_components([authorized])


@pytest.mark.parametrize("component_name", ("helper", "module", "browser"))
def test_each_remaining_component_rejects_symlink_leaf(tmp_path, monkeypatch, component_name):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    helper = ROOT / "app/native/worker_bridge/browser_capture.mjs"
    target = {"helper": helper, "module": module, "browser": browser}[component_name]
    link = tmp_path / f"{component_name}-link"
    link.symlink_to(target)
    arguments = {
        "node_path": node,
        "playwright_module": link if component_name == "module" else module,
        "browser_path": link if component_name == "browser" else browser,
        **identity_arguments(node, module, browser),
        "n0_report_path": open_n0_report(tmp_path),
        "output_path": tmp_path / "must-not-exist.png",
        "development_canary": True,
    }
    if component_name == "helper":
        monkeypatch.setattr(launcher, "HELPER", link)
    with pytest.raises(launcher.ComponentIntegrityError, match="symlink"):
        launcher.capture_browser_canary(**arguments)
    ancestor = tmp_path / "node-parent-link"
    ancestor.symlink_to(node.parent, target_is_directory=True)
    with pytest.raises(launcher.ComponentIntegrityError, match="symlink"):
        launcher.capture_browser_canary(
            node_path=ancestor / node.name,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=tmp_path / "must-not-exist.png",
            development_canary=True,
        )


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (("unexpected_request_count", 1), ("marker", "forged"), ("javascript", "not-executed")),
)
def test_launcher_rejects_invalid_capture_receipt_and_never_publishes(tmp_path, monkeypatch, field, bad_value):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    original = launcher._read_reply
    calls = 0

    def corrupt_first_reply(*args, **kwargs):
        nonlocal calls
        calls += 1
        reply = original(*args, **kwargs)
        if calls == 1:
            reply[field] = bad_value
        return reply

    monkeypatch.setattr(launcher, "_read_reply", corrupt_first_reply)
    output = tmp_path / "rejected.png"
    with pytest.raises(launcher.BrowserCanaryError, match="capture receipt"):
        launcher.capture_browser_canary(
            node_path=node,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=output,
            development_canary=True,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".deeptwin-t018-*.stage"))


def test_shutdown_failure_removes_private_stage_without_publishing(tmp_path, monkeypatch):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    original = launcher._read_reply
    calls = 0

    def corrupt_shutdown(*args, **kwargs):
        nonlocal calls
        calls += 1
        reply = original(*args, **kwargs)
        if calls == 2:
            reply["state"] = "not-terminated"
        return reply

    monkeypatch.setattr(launcher, "_read_reply", corrupt_shutdown)
    output = tmp_path / "shutdown-failed.png"
    with pytest.raises(launcher.BrowserCanaryError, match="acknowledge"):
        launcher.capture_browser_canary(
            node_path=node,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=output,
            development_canary=True,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".deeptwin-t018-*.stage"))


def test_owned_termination_failure_removes_private_stage_without_publishing(tmp_path, monkeypatch):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    original = launcher._terminate_owned_group

    def terminate_but_report_failure(*args, **kwargs):
        assert original(*args, **kwargs) is True
        return False

    monkeypatch.setattr(launcher, "_terminate_owned_group", terminate_but_report_failure)
    output = tmp_path / "termination-failed.png"
    with pytest.raises(launcher.BrowserCanaryError, match="process tree did not terminate"):
        launcher.capture_browser_canary(
            node_path=node,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=output,
            development_canary=True,
        )
    assert not output.exists()
    assert not list(tmp_path.glob(".deeptwin-t018-*.stage"))


def test_existing_final_output_is_preserved_and_never_used_as_stage(tmp_path):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    output = tmp_path / "existing.png"
    original = b"unrelated-preexisting-output"
    output.write_bytes(original)
    with pytest.raises(launcher.BrowserCanaryError, match="new PNG"):
        launcher.capture_browser_canary(
            node_path=node,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=output,
            development_canary=True,
        )
    assert output.read_bytes() == original


def test_symlinked_output_directory_is_rejected_before_spawn(tmp_path):
    launcher = load_launcher()
    node, module, browser = local_browser_inputs()
    real_directory = tmp_path / "real-output"
    real_directory.mkdir()
    linked_directory = tmp_path / "linked-output"
    linked_directory.symlink_to(real_directory, target_is_directory=True)
    with pytest.raises(launcher.ComponentIntegrityError, match="symlink"):
        launcher.capture_browser_canary(
            node_path=node,
            playwright_module=module,
            browser_path=browser,
            **identity_arguments(node, module, browser),
            n0_report_path=open_n0_report(tmp_path),
            output_path=linked_directory / "must-not-exist.png",
            development_canary=True,
        )
    assert not (real_directory / "must-not-exist.png").exists()
