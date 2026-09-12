"""Superseded standalone macOS launcher feasibility experiment (former T018).

Production browser launch is fail-closed until a signed native report proves both
directions of peer authentication and inherited browser sandboxing.  The explicit
development canary below uses only local locked/environment inputs, broker-supplied
synthetic bytes and a private stdio channel.  Its result is never production-eligible.

ADR-009 replaced this product boundary with the self-hosted web framework and official
browser control plane.  This file is retained as historical evidence only.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import struct
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.request import ProxyHandler, build_opener
import uuid


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.native.worker_bridge.protocol import (  # noqa: E402
    MAX_FRAME_BYTES,
    ProtocolViolation,
    decode_browser_request,
    encode_browser_request,
    strict_json_loads,
)


HELPER = ROOT / "app/native/worker_bridge/browser_capture.mjs"
MAX_SCREENSHOT_BYTES = 48 * 1024
MAX_STDERR_CAPTURE_BYTES = 64 * 1024


class UnqualifiedNativeBoundary(RuntimeError):
    """The native evidence is insufficient for a product worker launch."""


class ComponentIntegrityError(RuntimeError):
    """A selected local executable does not match its expected bytes."""


class BrowserCanaryError(RuntimeError):
    """The bounded browser helper failed or violated its reply contract."""


def _sha256_fd(fd: int) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def _lexical_absolute(path: Path) -> Path:
    expanded = path.expanduser()
    if ".." in expanded.parts:
        raise ComponentIntegrityError("parent traversal is not accepted in an authorized path")
    return expanded if expanded.is_absolute() else Path.cwd() / expanded


def _reject_symlink_components(path: Path, label: str, *, include_leaf: bool = True) -> Path:
    absolute = _lexical_absolute(path)
    parts = absolute.parts
    current = Path(parts[0])
    limit = len(parts) if include_leaf else len(parts) - 1
    for part in parts[1:limit]:
        current /= part
        try:
            metadata = current.lstat()
        except OSError as error:
            raise ComponentIntegrityError(f"{label} path component is unavailable: {current}") from error
        if stat.S_ISLNK(metadata.st_mode):
            raise ComponentIntegrityError(f"{label} path contains a symlink component: {current}")
    return absolute


def _identity(metadata: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _authorize_component(
    path: Path,
    label: str,
    expected_sha256: str,
    *,
    executable: bool = False,
) -> dict[str, Any]:
    authorized_path = _reject_symlink_components(path, label)
    if (
        not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise ComponentIntegrityError(f"{label} SHA-256 authorization is malformed")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd: int | None = None
    try:
        fd = os.open(authorized_path, flags)
        metadata = os.fstat(fd)
        path_metadata = authorized_path.lstat()
    except OSError as error:
        if fd is not None:
            os.close(fd)
        raise ComponentIntegrityError(f"{label} is not an authorized regular file") from error
    try:
        if not stat.S_ISREG(metadata.st_mode) or _identity(metadata) != _identity(path_metadata):
            raise ComponentIntegrityError(f"{label} changed while it was being authorized")
        if executable and not os.access(authorized_path, os.X_OK, follow_symlinks=False):
            raise ComponentIntegrityError(f"{label} is not executable")
        actual_sha256 = _sha256_fd(fd)
        if actual_sha256 != expected_sha256:
            raise ComponentIntegrityError(f"{label} SHA-256 does not match the authorized component")
        return {
            "path": authorized_path,
            "fd": fd,
            "identity": _identity(metadata),
            "sha256": actual_sha256,
            "label": label,
        }
    except Exception:
        os.close(fd)
        raise


def _verify_authorized_component(component: dict[str, Any]) -> None:
    try:
        metadata = component["path"].lstat()
    except OSError as error:
        raise ComponentIntegrityError(f"{component['label']} disappeared after authorization") from error
    if _identity(metadata) != component["identity"] or _sha256_fd(component["fd"]) != component["sha256"]:
        raise ComponentIntegrityError(f"{component['label']} changed after authorization")


def _close_components(components: list[dict[str, Any]]) -> None:
    for component in components:
        try:
            os.close(component["fd"])
        except OSError:
            pass


def _load_n0(path: Path) -> dict[str, Any]:
    try:
        report = strict_json_loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ProtocolViolation) as error:
        raise UnqualifiedNativeBoundary("native N0 report is absent or malformed") from error
    if not isinstance(report, dict) or report.get("schema") != "native-canary-n0-v1":
        raise UnqualifiedNativeBoundary("native N0 report schema is not accepted")
    if report.get("worker", {}).get("app_sandbox") is not True or report.get("child", {}).get("app_sandbox") is not True:
        raise UnqualifiedNativeBoundary("native worker and child sandbox evidence is incomplete")
    if report.get("wrong_server_rejected") is not True:
        raise UnqualifiedNativeBoundary("native worker identity binding evidence is incomplete")
    return report


def _require_product_boundary(report: dict[str, Any]) -> None:
    if report.get("peer_auth_complete") is not True:
        raise UnqualifiedNativeBoundary("worker-to-host peer authentication is not qualified")
    if report.get("browser_children_app_sandbox") is not True:
        raise UnqualifiedNativeBoundary("browser child sandbox inheritance is not qualified")
    if report.get("browser_boundary_complete") is not True:
        raise UnqualifiedNativeBoundary("the native browser boundary is not qualified")
    raise UnqualifiedNativeBoundary(
        "T018 has no authenticated native attestation; production browser launch remains disabled"
    )


class _SyntheticFixtureHandler(BaseHTTPRequestHandler):
    server_version = "DeepTwinSyntheticFixture/1"

    def do_GET(self) -> None:  # noqa: N802
        server = self.server
        if self.path != server.fixture_path:
            self.send_error(404)
            return
        server.receipts.append({"method": "GET", "path": self.path, "peer": self.client_address[0]})
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(server.fixture_body)))
        self.end_headers()
        self.wfile.write(server.fixture_body)

    def log_message(self, format: str, *args: object) -> None:
        return


def _host_fetch_synthetic_fixture(body: bytes, token: str) -> tuple[bytes, list[dict[str, str]]]:
    if not body or len(body) > 32_768:
        raise BrowserCanaryError("synthetic fixture must contain 1..32768 bytes")
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SyntheticFixtureHandler)
    server.fixture_body = body
    server.fixture_path = f"/t018/{token}"
    server.receipts = []
    thread = threading.Thread(target=server.serve_forever, name="deeptwin-t018-fixture", daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}{server.fixture_path}"
        response = build_opener(ProxyHandler({})).open(url, timeout=3)
        fetched = response.read(32_769)
        if response.status != 200 or len(fetched) > 32_768:
            raise BrowserCanaryError("bounded host fixture fetch failed")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
    if thread.is_alive() or len(server.receipts) != 1 or server.receipts[0]["peer"] != "127.0.0.1":
        raise BrowserCanaryError("host fixture broker did not close cleanly")
    return fetched, server.receipts


def _encode_control(value: dict[str, Any]) -> bytes:
    payload = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    if not payload or len(payload) > MAX_FRAME_BYTES:
        raise ProtocolViolation("control frame is outside the IPC limit")
    return struct.pack(">I", len(payload)) + payload


def _write_all_fd(fd: int, value: bytes) -> None:
    view = memoryview(value)
    offset = 0
    while offset < len(view):
        count = os.write(fd, view[offset:])
        if not isinstance(count, int) or count <= 0:
            raise BrowserCanaryError("IPC write did not make progress")
        offset += count


def _drain_stderr(stream) -> dict[str, Any]:
    digest = hashlib.sha256()
    captured = bytearray()
    total = 0
    while True:
        chunk = os.read(stream.fileno(), 64 * 1024)
        if not chunk:
            break
        total += len(chunk)
        digest.update(chunk)
        remaining = MAX_STDERR_CAPTURE_BYTES - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
    return {
        "total_bytes": total,
        "captured_bytes": len(captured),
        "truncated": total > len(captured),
        "sha256": digest.hexdigest(),
    }


def _stage_png(target: dict[str, Any], screenshot: bytes) -> str:
    stage = f".deeptwin-t018-{uuid.uuid4().hex}.stage"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(stage, flags, 0o600, dir_fd=target["parent_fd"])
    try:
        os.fchmod(fd, 0o600)
        _write_all_fd(fd, screenshot)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        try:
            os.unlink(stage, dir_fd=target["parent_fd"])
        except FileNotFoundError:
            pass
        raise
    os.close(fd)
    return stage


def _publish_private_stage(stage: str, target: dict[str, Any]) -> None:
    parent_metadata = os.fstat(target["parent_fd"])
    try:
        path_parent_metadata = target["path"].parent.lstat()
    except OSError as error:
        raise BrowserCanaryError("authorized output directory path disappeared") from error
    if (
        (parent_metadata.st_dev, parent_metadata.st_ino) != target["parent_identity"]
        or (path_parent_metadata.st_dev, path_parent_metadata.st_ino) != target["parent_identity"]
    ):
        raise BrowserCanaryError("authorized output directory changed before publication")
    stage_identity = _identity(os.stat(stage, dir_fd=target["parent_fd"], follow_symlinks=False))
    linked = False
    try:
        os.link(
            stage,
            target["name"],
            src_dir_fd=target["parent_fd"],
            dst_dir_fd=target["parent_fd"],
            follow_symlinks=False,
        )
        linked = True
        os.unlink(stage, dir_fd=target["parent_fd"])
    except Exception:
        if linked:
            try:
                published = os.stat(target["name"], dir_fd=target["parent_fd"], follow_symlinks=False)
                if _identity(published) == stage_identity:
                    os.unlink(target["name"], dir_fd=target["parent_fd"])
            except OSError:
                pass
        raise


def _read_exact(stream, length: int, timeout: float) -> bytes:
    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    remaining = length
    try:
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0 or not selector.select(wait):
                raise BrowserCanaryError("timed out waiting for helper IPC")
            chunk = os.read(stream.fileno(), remaining)
            if not chunk:
                raise BrowserCanaryError("helper IPC closed before its reply")
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        selector.close()
    return b"".join(chunks)


def _read_reply(stream, timeout: float = 25) -> dict[str, Any]:
    header = _read_exact(stream, 4, timeout)
    (length,) = struct.unpack(">I", header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise BrowserCanaryError("helper reply has an invalid frame length")
    try:
        value = strict_json_loads(_read_exact(stream, length, timeout).decode("utf-8"))
    except UnicodeDecodeError as error:
        raise BrowserCanaryError("helper reply is not UTF-8 JSON") from error
    if not isinstance(value, dict):
        raise BrowserCanaryError("helper reply is not an object")
    return value


def _descendants(root_pid: int) -> list[int]:
    snapshot = subprocess.run(
        ["/bin/ps", "-axo", "pid=,ppid="],
        check=True,
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        timeout=3,
    )
    children: dict[int, list[int]] = {}
    for line in snapshot.stdout.splitlines():
        try:
            pid_text, parent_text = line.split()
            children.setdefault(int(parent_text), []).append(int(pid_text))
        except ValueError:
            continue
    found: list[int] = []
    pending = list(children.get(root_pid, ()))
    while pending:
        pid = pending.pop()
        if pid in found:
            continue
        found.append(pid)
        pending.extend(children.get(pid, ()))
    return sorted(found)


def _process_group_members(group_id: int) -> list[int]:
    snapshot = subprocess.run(
        ["/bin/ps", "-axo", "pid=,pgid="],
        check=True,
        text=True,
        capture_output=True,
        env={"PATH": "/usr/bin:/bin", "LANG": "C"},
        timeout=3,
    )
    members: list[int] = []
    for line in snapshot.stdout.splitlines():
        try:
            pid_text, group_text = line.split()
            if int(group_text) == group_id:
                members.append(int(pid_text))
        except ValueError:
            continue
    return sorted(members)


def _terminate_owned_group(process: subprocess.Popen[bytes], descendants: list[int]) -> bool:
    members = _process_group_members(process.pid)
    if members:
        try:
            if process.poll() is None and os.getpgid(process.pid) != process.pid:
                raise BrowserCanaryError("refusing to signal a non-owned process group")
            os.killpg(process.pid, signal.SIGTERM)
            if process.poll() is None:
                process.wait(timeout=5)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            pass
    if _process_group_members(process.pid):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.wait(timeout=5)
    if _process_group_members(process.pid):
        return False
    for pid in [process.pid, *descendants]:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        return False
    return True


def _validate_output_target(path: Path) -> dict[str, Any]:
    output = _lexical_absolute(path)
    _reject_symlink_components(output.parent, "output directory")
    if output.suffix.lower() != ".png" or output.name in {"", ".", ".."}:
        raise BrowserCanaryError("output must be a new PNG in an existing authorized directory")
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        parent_fd = os.open(output.parent, flags)
        parent_metadata = os.fstat(parent_fd)
        path_metadata = output.parent.lstat()
        if not stat.S_ISDIR(parent_metadata.st_mode) or _identity(parent_metadata) != _identity(path_metadata):
            raise BrowserCanaryError("output directory changed during authorization")
        try:
            os.stat(output.name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise BrowserCanaryError("output must be a new PNG in an existing authorized directory")
    except Exception:
        if "parent_fd" in locals():
            os.close(parent_fd)
        raise
    return {
        "path": output,
        "name": output.name,
        "parent_fd": parent_fd,
        "parent_identity": (parent_metadata.st_dev, parent_metadata.st_ino),
    }


def _validate_capture_reply(
    reply: dict[str, Any],
    *,
    request_id: str,
    generation: str,
    expected_marker: str,
) -> bytes:
    expected_reply = {
        "schema": "deeptwin-browser-helper-reply-v1",
        "request_id": request_id,
        "generation": generation,
        "state": "captured_waiting_for_shutdown",
    }
    allowed_reply = {
        "schema", "request_id", "generation", "state", "broker_fulfilled",
        "unexpected_request_count", "marker", "javascript", "browser_version",
        "screenshot_base64", "screenshot_sha256",
    }
    if (
        set(reply) != allowed_reply
        or any(reply.get(key) != value for key, value in expected_reply.items())
        or reply.get("broker_fulfilled") is not True
        or type(reply.get("unexpected_request_count")) is not int
        or reply["unexpected_request_count"] != 0
        or reply.get("marker") != expected_marker
        or reply.get("javascript") != "executed"
        or not isinstance(reply.get("browser_version"), str)
        or not 1 <= len(reply["browser_version"]) <= 128
    ):
        raise BrowserCanaryError("capture receipt failed the exact launcher acceptance contract")
    try:
        screenshot = base64.b64decode(reply["screenshot_base64"], validate=True)
    except (KeyError, TypeError, ValueError) as error:
        raise BrowserCanaryError("capture receipt contains invalid screenshot base64") from error
    if not screenshot.startswith(b"\x89PNG\r\n\x1a\n") or len(screenshot) > MAX_SCREENSHOT_BYTES:
        raise BrowserCanaryError("capture receipt does not contain a bounded PNG")
    if hashlib.sha256(screenshot).hexdigest() != reply.get("screenshot_sha256"):
        raise BrowserCanaryError("capture receipt screenshot digest mismatch")
    return screenshot


def capture_browser_canary(
    *,
    node_path: Path,
    playwright_module: Path,
    browser_path: Path,
    node_sha256: str,
    playwright_module_sha256: str,
    browser_sha256: str,
    helper_sha256: str,
    n0_report_path: Path,
    output_path: Path,
    development_canary: bool = False,
) -> dict[str, Any]:
    """Run one broker-fulfilled capture, or fail closed for product use.

    `development_canary=True` is evidence mode, not an escape hatch: the returned
    receipt always says `production_boundary_accepted=False` and cannot be passed
    to the product dispatcher as boundary qualification.
    """
    n0 = _load_n0(Path(n0_report_path))
    if not development_canary:
        _require_product_boundary(n0)
    output = _validate_output_target(Path(output_path))
    components: list[dict[str, Any]] = []
    stage: str | None = None
    try:
        components.append(_authorize_component(Path(node_path), "Node", node_sha256, executable=True))
        components.append(_authorize_component(HELPER, "browser helper", helper_sha256))
        components.append(
            _authorize_component(Path(playwright_module), "Playwright module", playwright_module_sha256)
        )
        components.append(_authorize_component(Path(browser_path), "Chromium", browser_sha256, executable=True))
        node, helper, module, browser = (component["path"] for component in components)
        for component in components:
            _verify_authorized_component(component)

        token = uuid.uuid4().hex
        marker = f"t018-default-marker-{token}"
        fixture = (
            "<!doctype html><meta charset=utf-8><title>T018</title>"
            f"<main id=marker>{marker}</main><script>document.body.dataset.js='executed'</script>"
        ).encode("utf-8")
        fetched, broker_receipts = _host_fetch_synthetic_fixture(fixture, token)
        request_id, generation = uuid.uuid4().hex, uuid.uuid4().hex
        browser_url = f"https://fixture.deeptwin.invalid/t018/{token}"
        frame = encode_browser_request(
            {
                "schema": "deeptwin-browser-ipc-v1",
                "request_id": request_id,
                "generation": generation,
                "action": "capture",
                "url": browser_url,
                "status": 200,
                "headers": [["content-type", "text/html; charset=utf-8"]],
                "body_base64": base64.b64encode(fetched).decode("ascii"),
            }
        )
        clean_environment = {
            "PATH": "/usr/bin:/bin",
            "LANG": "C",
            "DEEPTWIN_PLAYWRIGHT_MODULE": str(module),
            "DEEPTWIN_BROWSER_PATH": str(browser),
            "LANGCHAIN_TRACING_V2": "false",
            "LANGSMITH_TRACING": "false",
            "NO_PROXY": "*",
        }
        process = subprocess.Popen(
            [str(node), str(helper)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=clean_environment,
            close_fds=True,
            start_new_session=True,
        )
        descendants: list[int] = []
        reply: dict[str, Any] | None = None
        terminated = False
        stderr_observation: dict[str, Any] = {}
        assert process.stderr is not None

        def drain_stderr() -> None:
            stderr_observation.update(_drain_stderr(process.stderr))

        stderr_thread = threading.Thread(target=drain_stderr, name="deeptwin-t018-stderr", daemon=True)
        stderr_thread.start()
        try:
            assert process.stdin is not None and process.stdout is not None
            _write_all_fd(process.stdin.fileno(), frame)
            reply = _read_reply(process.stdout)
            descendants = _descendants(process.pid)
            if not descendants:
                raise BrowserCanaryError("no owned Chromium descendant was observed")
            screenshot = _validate_capture_reply(
                reply,
                request_id=request_id,
                generation=generation,
                expected_marker=marker,
            )
            stage = _stage_png(output, screenshot)
            _write_all_fd(
                process.stdin.fileno(),
                _encode_control(
                    {
                        "schema": "deeptwin-browser-ipc-v1",
                        "request_id": request_id,
                        "generation": generation,
                        "action": "shutdown",
                    }
                ),
            )
            shutdown = _read_reply(process.stdout, timeout=10)
            if shutdown != {
                "schema": "deeptwin-browser-helper-reply-v1",
                "request_id": request_id,
                "generation": generation,
                "state": "terminated",
            }:
                raise BrowserCanaryError("helper did not acknowledge the exact owned shutdown")
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired as error:
                raise BrowserCanaryError("helper did not exit after shutdown acknowledgement") from error
        finally:
            terminated = _terminate_owned_group(process, descendants)
            stderr_thread.join(timeout=5)
        if stderr_thread.is_alive():
            raise BrowserCanaryError("helper stderr drain did not terminate")
        if not terminated:
            raise BrowserCanaryError("owned browser process tree did not terminate")
        if process.returncode != 0:
            raise BrowserCanaryError(
                f"helper exited with status {process.returncode}; stderr_sha256={stderr_observation.get('sha256')}"
            )
        for component in components:
            _verify_authorized_component(component)
        if stage is None:
            raise BrowserCanaryError("private screenshot stage is missing")
        assert reply is not None
        result = {
            "schema": "deeptwin-browser-capture-v1",
            "status": "passed_development_canary",
            "production_boundary_accepted": False,
            "boundary_limit": "worker-to-host peer auth and browser sandbox inheritance remain unqualified",
            "request_id": request_id,
            "generation": generation,
            "driver_pid": process.pid,
            "owned_descendant_pids": descendants,
            "owned_processes_terminated": True,
            "component_identity_verified_after_run": True,
            "published_after_clean_shutdown": True,
            "broker_fulfilled": True,
            "broker_receipts": broker_receipts,
            "unexpected_request_count": 0,
            "marker": marker,
            "javascript": "executed",
            "browser_version": reply["browser_version"],
            "screenshot_sha256": reply["screenshot_sha256"],
            "browser_executable_sha256": components[3]["sha256"],
            "node_sha256": components[0]["sha256"],
            "playwright_module_sha256": components[2]["sha256"],
            "helper_sha256": components[1]["sha256"],
            "fixture_body_sha256": hashlib.sha256(fetched).hexdigest(),
            "fixture_url": browser_url,
            "stderr": stderr_observation,
        }
        _publish_private_stage(stage, output)
        stage = None
        return result
    finally:
        if stage is not None:
            try:
                os.unlink(stage, dir_fd=output["parent_fd"])
            except FileNotFoundError:
                pass
        _close_components(components)
        os.close(output["parent_fd"])


__all__ = (
    "MAX_FRAME_BYTES",
    "BrowserCanaryError",
    "ComponentIntegrityError",
    "ProtocolViolation",
    "UnqualifiedNativeBoundary",
    "capture_browser_canary",
    "decode_browser_request",
    "encode_browser_request",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DeepTwin standalone macOS boundary launcher")
    parser.add_argument("mode", choices=("browser-canary",))
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--playwright-module", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--node-sha256", required=True)
    parser.add_argument("--playwright-module-sha256", required=True)
    parser.add_argument("--browser-sha256", required=True)
    parser.add_argument("--helper-sha256", required=True)
    parser.add_argument("--n0-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--development-canary",
        action="store_true",
        help="run an explicitly non-production capture despite the known native evidence gap",
    )
    args = parser.parse_args(argv)
    try:
        result = capture_browser_canary(
            node_path=args.node,
            playwright_module=args.playwright_module,
            browser_path=args.browser,
            node_sha256=args.node_sha256,
            playwright_module_sha256=args.playwright_module_sha256,
            browser_sha256=args.browser_sha256,
            helper_sha256=args.helper_sha256,
            n0_report_path=args.n0_report,
            output_path=args.output,
            development_canary=args.development_canary,
        )
    except (BrowserCanaryError, ComponentIntegrityError, ProtocolViolation, UnqualifiedNativeBoundary) as error:
        print(json.dumps({"schema": "deeptwin-launch-error-v1", "state": "blocked", "error": str(error)}), file=sys.stderr)
        return 78
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
