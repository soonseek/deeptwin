"""Sandboxed headless Chromium driven over the DevTools pipe (T043 browser half).

This module runs only inside the browser worker process (`app.workers.browser_worker_main`,
identity 20105, `network_mode: none`); the control plane never imports it (pinned by
`app.tests.test_browser_worker`). It needs no driver library: Chromium is started with
`--remote-debugging-pipe` and spoken to over two inherited pipes (fd 3 in, fd 4 out,
NUL-delimited JSON), so no DevTools port is ever opened.

One `ChromiumSession` is one Chromium process with one fresh profile directory created
under the worker's private profile root (a tmpfs in deploy/compose.yaml) and removed when
the session closes; nothing — cookies, cache, storage — survives into another session.

Networking. Chromium has no network path of its own: the worker's network namespace holds
only loopback, the resolver is mapped to NOTFOUND and no proxy is configured. Every
request a page makes is paused by the DevTools `Fetch` domain at the request stage and
answered through controlled fulfillment: the session hands the URL to the injected
`fetcher` (the broker-backed fetch service), then fulfills the paused request with the
brokered status, content type and body, or fails it. Only GET is ever forwarded; a
redirect the broker followed is replayed to Chromium as a 302 to the final URL, whose
re-request is answered from the one-shot result the broker already produced. Request
headers (cookies, referer) never leave: the fetcher sends none of Chromium's headers, and
no response header except the content type (never `Set-Cookie`) reaches Chromium.

Scripts are disabled for every page (`Emulation.setScriptExecutionDisabled`); downloads
are denied. The DevTools evaluation the session itself uses to read the title and the
text still works with page scripts off.

Sandbox. `--no-sandbox` is never passed. Before any content is loaded, `probe_sandbox`
requires every renderer the browser started to run under seccomp-BPF (`Seccomp: 2`) in
its own PID namespace (a nested `NSpid`) — the positive probe runtime.md requires; a
host that cannot provide it refuses (`sandbox_unavailable`), never a weakened browser.
"""

from __future__ import annotations

import base64
import json
import os
import select
import shutil
import signal
import struct
import tempfile
import time
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path

__all__ = [
    "BROWSER_CODES", "BrowserRefusal", "ChromiumSession", "Navigation", "chromium_arguments",
]

# the closed codes a browser session answers
BROWSER_CODES = frozenset({
    "grant_denied", "dns_denied", "redirect_denied", "too_large", "timeout", "render_failed",
    "fetch_failed", "sandbox_unavailable", "invalid_request",
})
_DENIAL_REASON = {"grant_denied": "BlockedByClient", "dns_denied": "NameNotResolved",
                  "redirect_denied": "BlockedByClient", "too_large": "BlockedByClient",
                  "timeout": "TimedOut", "fetch_failed": "Failed", "invalid_request": "BlockedByClient"}
MAX_MESSAGE_BYTES = 48 * 1024 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_READ_SLICE = 1024 * 1024
_SANDBOX_WAIT_S = 5.0


class BrowserRefusal(Exception):
    """A closed session failure; `code` is one of `BROWSER_CODES`."""

    def __init__(self, code: str):
        if code not in BROWSER_CODES:
            code = "render_failed"
        super().__init__(code)
        self.code = code


def chromium_arguments(executable: str, profile: str, width: int, height: int) -> list[str]:
    """The exact argv: no sandbox relaxation, no DevTools port, no resolver, no proxy."""

    return [
        executable, "--headless", "--remote-debugging-pipe", f"--user-data-dir={profile}",
        "--no-first-run", "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
        "--disable-background-networking", "--disable-component-update", "--disable-sync",
        "--disable-default-apps", "--disable-breakpad", "--disable-domain-reliability",
        "--disable-client-side-phishing-detection", "--no-pings", "--mute-audio", "--hide-scrollbars",
        "--no-proxy-server", "--host-resolver-rules=MAP * ~NOTFOUND",
        "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        "--disable-features=DnsOverHttps,Translate,MediaRouter,OptimizationHints,InterestFeedContentSuggestions",
        f"--window-size={width},{height}", "about:blank",
    ]


class _Pipe:
    """NUL-delimited DevTools messages over the two inherited pipes."""

    def __init__(self, write_fd: int, read_fd: int):
        self._write, self._read = write_fd, read_fd
        self._buffer = bytearray()
        self._next = 0
        self.events: list[dict] = []

    def close(self):
        for descriptor in (self._write, self._read):
            try:
                os.close(descriptor)
            except OSError:
                pass

    def send(self, method, params=None, session=None) -> int:
        self._next += 1
        message = {"id": self._next, "method": method, "params": params or {}}
        if session is not None:
            message["sessionId"] = session
        data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\0"
        view = memoryview(data)
        while view:
            written = os.write(self._write, view)
            view = view[written:]
        return self._next

    def receive(self, deadline: float) -> dict:
        while True:
            index = self._buffer.find(b"\0")
            if index >= 0:
                raw = bytes(self._buffer[:index])
                del self._buffer[:index + 1]
                try:
                    value = json.loads(raw)
                except ValueError:
                    raise BrowserRefusal("render_failed") from None
                if type(value) is not dict:
                    raise BrowserRefusal("render_failed")
                return value
            if len(self._buffer) > MAX_MESSAGE_BYTES:
                raise BrowserRefusal("too_large")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BrowserRefusal("timeout")
            readable, _w, _e = select.select([self._read], [], [], remaining)
            if not readable:
                raise BrowserRefusal("timeout")
            chunk = os.read(self._read, _READ_SLICE)
            if not chunk:
                raise BrowserRefusal("render_failed")
            self._buffer.extend(chunk)

    def call(self, method, params=None, session=None, *, deadline: float) -> dict:
        identifier = self.send(method, params, session)
        while True:
            message = self.receive(deadline)
            if message.get("id") == identifier:
                if "error" in message:
                    raise BrowserRefusal("render_failed")
                result = message.get("result")
                return result if type(result) is dict else {}
            self.events.append(message)


@dataclass(slots=True)
class Navigation:
    """What a navigation observed: the brokered facts, never Chromium's claims alone."""

    requested_url: str
    final_url: str = ""
    status: int = 0
    content_type: str = ""
    document_sha256: str = ""
    document_bytes: int = 0
    title: str = ""
    requests: int = 0
    allowed: int = 0
    denied: int = 0
    body_bytes: int = 0
    main_code: str | None = None
    denials: dict = field(default_factory=dict)


def _children_of(root: int) -> set[int]:
    parents = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            raw = Path(f"/proc/{entry}/stat").read_bytes()
        except OSError:
            continue
        try:
            parents[int(entry)] = int(raw[raw.rindex(b")") + 2:].split()[1])
        except (ValueError, IndexError):
            continue
    found, frontier = set(), {root}
    while frontier:
        frontier = {pid for pid, parent in parents.items() if parent in frontier and pid not in found}
        found |= frontier
    return found


def _renderer_confinement(pid: int):
    """(seccomp mode, PID-namespace depth) of one renderer, or None when it is not one."""

    try:
        command = Path(f"/proc/{pid}/cmdline").read_bytes()
        status = Path(f"/proc/{pid}/status").read_text()
    except OSError:
        return None
    if b"--type=renderer" not in command:
        return None
    seccomp, depth = None, 0
    for line in status.splitlines():
        if line.startswith("Seccomp:"):
            seccomp = line.split()[1] if len(line.split()) > 1 else None
        elif line.startswith("NSpid:"):
            depth = len(line.split()) - 1
    return seccomp, depth


class ChromiumSession:
    """One Chromium process and one fresh profile, for exactly one navigation."""

    def __init__(self, executable: str, profile_root: str, *, width: int = 1280, height: int = 800):
        if not os.path.isabs(executable) or not os.path.isabs(profile_root):
            raise ValueError("the browser executable and profile root are absolute paths")
        self.executable, self.profile_root = executable, profile_root
        self.width, self.height = width, height
        self.profile: str | None = None
        self.pid: int | None = None
        self.sandbox: dict | None = None
        self._pipe: _Pipe | None = None
        self._session: str | None = None
        self._frame: str | None = None

    # --- lifecycle --------------------------------------------------------------------

    def start(self, deadline: float) -> None:
        self.profile = tempfile.mkdtemp(prefix="session-", dir=self.profile_root)
        os.chmod(self.profile, 0o700)
        to_child_read, to_child_write = os.pipe()
        from_child_read, from_child_write = os.pipe()
        # the child's fds 3/4: dup'd first so a pipe already sitting at 3 or 4 cannot collide
        child_in, child_out = os.dup(to_child_read), os.dup(from_child_write)
        null = os.open(os.devnull, os.O_RDWR)
        try:
            environment = {"HOME": self.profile, "TMPDIR": self.profile, "XDG_CONFIG_HOME": self.profile,
                           "XDG_CACHE_HOME": self.profile, "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
            self.pid = os.posix_spawn(
                self.executable, chromium_arguments(self.executable, self.profile, self.width, self.height),
                environment, setpgroup=0, file_actions=[
                    (os.POSIX_SPAWN_DUP2, null, 0), (os.POSIX_SPAWN_DUP2, null, 1),
                    (os.POSIX_SPAWN_DUP2, null, 2), (os.POSIX_SPAWN_DUP2, child_in, 3),
                    (os.POSIX_SPAWN_DUP2, child_out, 4)])
        except OSError:
            raise BrowserRefusal("render_failed") from None
        finally:
            for descriptor in (child_in, child_out, null, to_child_read, from_child_write):
                os.close(descriptor)
        self._pipe = _Pipe(to_child_write, from_child_read)
        pipe = self._pipe
        target = pipe.call("Target.createTarget", {"url": "about:blank"}, deadline=deadline).get("targetId")
        if type(target) is not str:
            raise BrowserRefusal("render_failed")
        session = pipe.call("Target.attachToTarget", {"targetId": target, "flatten": True},
                            deadline=deadline).get("sessionId")
        if type(session) is not str:
            raise BrowserRefusal("render_failed")
        self._session = session
        pipe.call("Browser.setDownloadBehavior", {"behavior": "deny"}, deadline=deadline)
        for method, params in (
                ("Page.enable", {}),
                ("Emulation.setScriptExecutionDisabled", {"value": True}),
                ("Emulation.setDeviceMetricsOverride", {"width": self.width, "height": self.height,
                                                        "deviceScaleFactor": 1, "mobile": False}),
                ("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]})):
            pipe.call(method, params, session, deadline=deadline)
        tree = pipe.call("Page.getFrameTree", {}, session, deadline=deadline)
        frame = tree.get("frameTree", {}).get("frame", {}).get("id") if type(tree.get("frameTree")) is dict else None
        if type(frame) is not str:
            raise BrowserRefusal("render_failed")
        self._frame = frame

    def probe_sandbox(self, deadline: float) -> dict:
        """Every renderer under seccomp-BPF in a nested PID namespace, before any content."""

        limit = min(deadline, time.monotonic() + _SANDBOX_WAIT_S)
        while True:
            readings = [reading for reading in (_renderer_confinement(pid) for pid in _children_of(self.pid))
                        if reading is not None]
            if readings:
                break
            if time.monotonic() >= limit:
                raise BrowserRefusal("sandbox_unavailable")
            time.sleep(0.05)
        if any(seccomp != "2" or depth < 2 for seccomp, depth in readings):
            raise BrowserRefusal("sandbox_unavailable")
        self.sandbox = {"renderers": len(readings), "seccomp_filter": True, "pid_namespace": True}
        return self.sandbox

    def close(self) -> bool:
        """Stop Chromium and remove the profile. True when nothing of the profile remains."""

        if self._pipe is not None:
            try:
                self._pipe.send("Browser.close")
            except OSError:
                pass
        if self.pid is not None:
            end = time.monotonic() + 3.0
            exited = False
            while time.monotonic() < end:
                try:
                    pid, _status = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    exited = True
                    break
                if pid:
                    exited = True
                    break
                time.sleep(0.05)
            try:
                os.killpg(self.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            if not exited:
                try:
                    os.waitpid(self.pid, 0)
                except ChildProcessError:
                    pass
            self.pid = None
        if self._pipe is not None:
            self._pipe.close()
            self._pipe = None
        wiped = True
        if self.profile is not None:
            shutil.rmtree(self.profile, ignore_errors=True)
            wiped = not os.path.lexists(self.profile)
            self.profile = None
        return wiped

    # --- navigation -------------------------------------------------------------------

    def _fulfill(self, request_id, status, headers, body):
        self._pipe.send("Fetch.fulfillRequest", {
            "requestId": request_id, "responseCode": status,
            "responseHeaders": [{"name": name, "value": value} for name, value in headers],
            "body": base64.b64encode(body).decode("ascii")}, self._session)

    def _fail(self, request_id, code):
        self._pipe.send("Fetch.failRequest", {"requestId": request_id,
                                              "errorReason": _DENIAL_REASON.get(code, "Failed")}, self._session)

    def navigate(self, url: str, fetcher, deadline: float) -> Navigation:
        """Load `url`, answering every paused request through `fetcher(url, kind)`, which
        returns an object with `status`, `final_url`, `content_type`, `body`, `sha256` or
        raises an exception carrying a closed `code`."""

        pipe, session = self._pipe, self._session
        observed = Navigation(requested_url=url)
        replay: dict[str, object] = {}
        pipe.events.clear()  # the blank start page's own load events are not this navigation's
        navigate_id = pipe.send("Page.navigate", {"url": url}, session)
        navigated = loaded = False
        main_document = url
        while not (navigated and loaded):
            message = pipe.events.pop(0) if pipe.events else pipe.receive(deadline)
            if message.get("id") == navigate_id:
                navigated = True
                result = message.get("result") if type(message.get("result")) is dict else {}
                if "error" in message or result.get("errorText"):
                    raise BrowserRefusal(observed.main_code or "render_failed")
                continue
            method = message.get("method")
            params = message.get("params") if type(message.get("params")) is dict else {}
            if method == "Page.loadEventFired" or method == "Page.frameStoppedLoading" and params.get("frameId") == self._frame and navigated:
                loaded = True
            elif method == "Fetch.requestPaused":
                self._paused(params, fetcher, observed, replay, main_document)
                request = params.get("request") if type(params.get("request")) is dict else {}
                if params.get("resourceType") == "Document" and params.get("frameId") == self._frame:
                    main_document = request.get("url", main_document)
        if observed.main_code is not None or not observed.document_sha256:
            raise BrowserRefusal(observed.main_code or "render_failed")
        facts = self.evaluate("JSON.stringify({title: document.title, url: location.href})", deadline)
        try:
            value = json.loads(facts)
            observed.title = str(value.get("title", ""))[:512]
            located = str(value.get("url", ""))
        except (ValueError, TypeError, AttributeError):
            raise BrowserRefusal("render_failed") from None
        if located != observed.final_url:
            raise BrowserRefusal("render_failed")  # Chromium shows a document the broker did not deliver
        return observed

    def _paused(self, params, fetcher, observed, replay, main_document):
        request_id = params.get("requestId")
        request = params.get("request") if type(params.get("request")) is dict else {}
        target, method = request.get("url"), request.get("method")
        main = params.get("resourceType") == "Document" and params.get("frameId") == self._frame
        if type(request_id) is not str or type(target) is not str:
            raise BrowserRefusal("render_failed")
        observed.requests += 1
        if method != "GET":
            observed.denied += 1
            observed.denials["method"] = observed.denials.get("method", 0) + 1
            self._fail(request_id, "grant_denied")
            if main:
                observed.main_code = "grant_denied"
            return
        response = replay.pop(target, None)
        if response is None:
            try:
                response = fetcher(target, "navigation" if main else "subresource")
            except Exception as error:  # noqa: BLE001 - every fetch failure is a closed code
                code = getattr(error, "code", "fetch_failed")
                code = code if code in BROWSER_CODES else "fetch_failed"
                observed.denied += 1
                observed.denials[code] = observed.denials.get(code, 0) + 1
                self._fail(request_id, code)
                if main:
                    observed.main_code = code
                return
            observed.allowed += 1
            observed.body_bytes += len(response.body)
            if response.final_url != target:
                # the broker already followed and revalidated the redirect: Chromium is told
                # to go there, and its re-request is answered from this very result
                replay[response.final_url] = response
                self._fulfill(request_id, 302, [("Location", response.final_url)], b"")
                return
        if main:
            observed.final_url, observed.status = response.final_url, response.status
            observed.content_type = response.content_type
            observed.document_sha256, observed.document_bytes = response.sha256, len(response.body)
            observed.main_code = None
        self._fulfill(request_id, response.status, [("Content-Type", response.content_type)], response.body)

    # --- observation ------------------------------------------------------------------

    def evaluate(self, expression: str, deadline: float) -> str:
        result = self._pipe.call("Runtime.evaluate", {"expression": expression, "returnByValue": True},
                                 self._session, deadline=deadline)
        value = result.get("result", {}).get("value") if type(result.get("result")) is dict else None
        if type(value) is not str or "exceptionDetails" in result:
            raise BrowserRefusal("render_failed")
        return value

    def read_text(self, max_bytes: int, deadline: float) -> tuple[bytes, bool]:
        """The rendered body text (`innerText`), UTF-8, cut on a character boundary."""

        text = self.evaluate("document.body ? document.body.innerText : ''", deadline)
        encoded = text.encode("utf-8")
        truncated = len(encoded) > max_bytes
        if truncated:
            encoded = encoded[:max_bytes]
            while encoded:
                try:
                    encoded.decode("utf-8")
                    break
                except UnicodeDecodeError:
                    encoded = encoded[:-1]
        return encoded, truncated

    def screenshot(self, max_bytes: int, deadline: float) -> tuple[bytes, int, int]:
        """A PNG of the viewport; its signature and IHDR size are checked, never trusted."""

        result = self._pipe.call("Page.captureScreenshot", {"format": "png", "fromSurface": True,
                                                            "captureBeyondViewport": False},
                                 self._session, deadline=deadline)
        data = result.get("data")
        if type(data) is not str or len(data) > (max_bytes * 4) // 3 + 8:
            raise BrowserRefusal("too_large")
        try:
            png = base64.b64decode(data, validate=True)
        except ValueError:
            raise BrowserRefusal("render_failed") from None
        if len(png) > max_bytes:
            raise BrowserRefusal("too_large")
        if (len(png) < 33 or not png.startswith(PNG_SIGNATURE) or png[12:16] != b"IHDR"
                or png[8:12] != b"\x00\x00\x00\r"):
            raise BrowserRefusal("render_failed")
        width, height = struct.unpack(">II", png[16:24])
        if (width, height) != (self.width, self.height):
            raise BrowserRefusal("render_failed")
        return png, width, height


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()
