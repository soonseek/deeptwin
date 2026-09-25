"""Control-plane side of the sandboxed browser channel (`cp-browser`, T043).

The control plane never drives a browser and never reaches the network for one. For one
browser tool call it:

1. registers a `BrowserGrant` (navigation sources, recipient hosts, byte/request/redirect
   limits, lifetime) with the fetch service over `cp-fetch` under a fresh random grant id;
2. sends one typed request — `navigate`, `read` (bounded rendered text) or `screenshot`
   (bounded viewport PNG) of one URL under a granted source — to the browser service
   (`browser`, 20105:20105, pair group 21104, `network_mode: none`) over `cp-browser`,
   naming only the grant id: the browser can reach nothing but that grant, through the
   fetch service over `browser-fetch`;
3. revokes the grant and compares the fetch service's own accounting (requests served,
   body bytes) with what the browser reported — a disagreement is `malformed_result`.

Both workers sit behind the verified pair-root machinery (root-initialized generation,
readiness record, socket inode, SO_PEERCRED, boot-secret HMAC handshake, per-frame MACs).
This module imports no browser driver (`app.adapters.browser`) and no network client;
`app.tests.test_browser_worker` pins that.

Wire (one request per connection): requester → `browser_request` (canonical JSON header);
responder → `browser_result` (`ok` + the observation + the output's byte count, digest and
chunk count, or `ok: false` + a closed `code`) + `browser_output` × n raw chunks.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from ..deployment.contracts import CONTROL, IPC_ROOT
from . import broker
from .fetch_channel import (
    BROWSER_GID,
    BROWSER_SERVICE,
    BROWSER_UID,
    BrowserGrant,
    FetchChannelError,
    FetchControlClient,
    bounded_int,
    canonical,
    check_grant_id,
    check_url,
    projection_values,
    read_chunks,
    source_admits,
    strict_object,
)
from .ipc_root import PairRootSpec

CHANNEL_ID = "cp-browser"
PROTOCOL_ID = "browser-session-v1"
PAIR_GID = 21_104
SOCKET_NAME = "worker.sock"
REQUEST_TYPE = "browser_request"
RESULT_TYPE = "browser_result"
OUTPUT_TYPE = "browser_output"
REQUEST_SCHEMA = "browser-request-v1"
RESULT_SCHEMA = "browser-result-v1"
CONTROL_ATTACHMENT_SCHEMA = "deeptwin-browser-control-attachment-v1"
WORKER_ATTACHMENT_SCHEMA = "deeptwin-browser-worker-attachment-v1"
MAX_FRAME_BYTES = 65_536
MAX_OPERATION_MS = 60_000
MIN_DEADLINE_MS = 1_000
DEFAULT_DEADLINE_MS = 20_000
MAX_TEXT_BYTES = 256 * 1024
DEFAULT_TEXT_BYTES = 64 * 1024
MIN_VIEWPORT, MAX_VIEWPORT = 64, 1_920
DEFAULT_VIEWPORT = (1_280, 800)
MAX_PNG_BYTES = 8 * 1024 * 1024
DEFAULT_PNG_BYTES = 4 * 1024 * 1024
MAX_TITLE = 512
OPERATIONS = ("navigate", "read", "screenshot")
MEDIA = {"navigate": None, "read": "text/plain; charset=utf-8", "screenshot": "image/png"}
# closed codes a worker may answer; anything else is `malformed_result`
WORKER_CODES = frozenset({"grant_denied", "projection_denied", "dns_denied", "redirect_denied", "too_large",
                          "timeout", "render_failed", "fetch_failed", "sandbox_unavailable", "invalid_request"})
CLIENT_CODES = WORKER_CODES | {"unavailable", "transport_failed", "malformed_result"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_RESULT_KEYS = {"schema", "ok", "op", "requested_url", "final_url", "status", "content_type", "title",
                "document_sha256", "document_bytes", "requests", "allowed", "denied", "body_bytes", "sandbox",
                "profile_wiped", "output"}
_OUTPUT_KEYS = {"media_type", "bytes", "sha256", "chunk_count", "truncated", "width", "height"}

__all__ = [
    "BrowserChannelError", "BrowserClient", "BrowserControlConfiguration", "BrowserObservation",
    "BrowserRequest", "BrowserWorkerConfiguration", "browser_channel",
]


class BrowserChannelError(RuntimeError):
    """A closed, sanitized browser failure. `sent` is False only when nothing reached the
    browser service (the request was refused locally, or the connection failed)."""

    def __init__(self, code: str = "transport_failed", *, sent: bool = True):
        if code not in CLIENT_CODES:
            code = "malformed_result"
        super().__init__(code)
        self.code = code
        self.sent = sent is not False


def browser_channel() -> tuple[PairRootSpec, broker.ChannelSpec]:
    """The fixed pair root and channel of the browser service, from nothing."""

    root = PairRootSpec(pair_root=IPC_ROOT / CHANNEL_ID, responder_uid=BROWSER_UID,
                        responder_gid=BROWSER_GID, pair_gid=PAIR_GID)
    spec = broker.ChannelSpec(
        channel_id=CHANNEL_ID, requester_service=CONTROL["service_identity"], responder_service=BROWSER_SERVICE,
        request_direction=f"{CONTROL['service_identity']}-to-{BROWSER_SERVICE}", protocol_id=PROTOCOL_ID,
        requester_uid=CONTROL["uid"], requester_gid=CONTROL["gid"], responder_uid=BROWSER_UID,
        responder_gid=BROWSER_GID, pair_gid=PAIR_GID, pair_root=root.endpoint_path, socket_name=SOCKET_NAME,
        root_uid=BROWSER_UID, root_gid=PAIR_GID, socket_uid=BROWSER_UID, socket_gid=PAIR_GID,
        requester_message_types=(REQUEST_TYPE,), responder_message_types=(OUTPUT_TYPE, RESULT_TYPE),
        max_frame_bytes=MAX_FRAME_BYTES, max_in_flight=1, max_queue_depth=8, max_operation_ms=MAX_OPERATION_MS)
    return root, spec


def _boot_id(value, label):
    if type(value) is not str or _BOOT_ID.fullmatch(value) is None:
        raise ValueError(f"{label} boot id is invalid")
    return value


def _absolute(value, label):
    if (type(value) is not str or not 1 <= len(value.encode("utf-8")) <= 4096
            or not value.startswith("/") or ".." in Path(value).parts):
        raise ValueError(f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True)
class BrowserControlConfiguration:
    """The deployment's nonsecret naming of both endpoints control uses for the browser
    (`app.server --browser-worker-config`): the browser service on `cp-browser` and the
    fetch service's grant side on `cp-fetch`, each with control's requester boot label."""

    browser_pair_root: str
    browser_requester_boot_id: str
    fetch_pair_root: str
    fetch_requester_boot_id: str

    def __post_init__(self):
        _absolute(self.browser_pair_root, "browser pair root")
        _absolute(self.fetch_pair_root, "fetch pair root")
        _boot_id(self.browser_requester_boot_id, "browser requester")
        _boot_id(self.fetch_requester_boot_id, "fetch requester")

    @classmethod
    def from_mapping(cls, value) -> BrowserControlConfiguration:
        fields = {"schema", "browser_pair_root", "browser_requester_boot_id", "fetch_pair_root",
                  "fetch_requester_boot_id"}
        if type(value) is not dict or set(value) != fields:
            raise ValueError("browser control configuration is not the exact attachment object")
        if value["schema"] != CONTROL_ATTACHMENT_SCHEMA:
            raise ValueError("browser control configuration schema is unsupported")
        return cls(**{name: value[name] for name in fields - {"schema"}})


@dataclass(frozen=True, slots=True)
class BrowserWorkerConfiguration:
    """The browser service's attachment object (`app.workers.browser_worker_main
    --attachment-config`): its `cp-browser` pair root and control's boot label, its
    `browser-fetch` pair root and its own requester boot label there, the Chromium
    executable and the private profile root (a 0700 tmpfs owned by the worker)."""

    pair_root: str
    requester_boot_id: str
    fetch_pair_root: str
    fetch_requester_boot_id: str
    chromium_path: str
    profile_root: str

    def __post_init__(self):
        for name in ("pair_root", "fetch_pair_root", "chromium_path", "profile_root"):
            _absolute(getattr(self, name), name.replace("_", " "))
        _boot_id(self.requester_boot_id, "browser requester")
        _boot_id(self.fetch_requester_boot_id, "fetch requester")

    @classmethod
    def from_mapping(cls, value) -> BrowserWorkerConfiguration:
        fields = {"schema", "pair_root", "requester_boot_id", "fetch_pair_root", "fetch_requester_boot_id",
                  "chromium_path", "profile_root"}
        if type(value) is not dict or set(value) != fields:
            raise ValueError("browser worker configuration is not the exact attachment object")
        if value["schema"] != WORKER_ATTACHMENT_SCHEMA:
            raise ValueError("browser worker configuration schema is unsupported")
        return cls(**{name: value[name] for name in fields - {"schema"}})


@dataclass(frozen=True, slots=True)
class BrowserRequest:
    """One typed operation on one URL, with its bounds."""

    op: str
    url: str
    deadline_ms: int = DEFAULT_DEADLINE_MS
    max_text_bytes: int = DEFAULT_TEXT_BYTES
    width: int = DEFAULT_VIEWPORT[0]
    height: int = DEFAULT_VIEWPORT[1]
    max_png_bytes: int = DEFAULT_PNG_BYTES

    def __post_init__(self):
        if self.op not in OPERATIONS:
            raise ValueError("browser operation is outside the closed set")
        check_url(self.url)
        bounded_int(self.deadline_ms, MIN_DEADLINE_MS, MAX_OPERATION_MS)
        bounded_int(self.max_text_bytes, 1, MAX_TEXT_BYTES)
        bounded_int(self.width, MIN_VIEWPORT, MAX_VIEWPORT)
        bounded_int(self.height, MIN_VIEWPORT, MAX_VIEWPORT)
        bounded_int(self.max_png_bytes, 1_024, MAX_PNG_BYTES)

    @property
    def max_output_bytes(self) -> int:
        return {"navigate": 0, "read": self.max_text_bytes, "screenshot": self.max_png_bytes}[self.op]

    def header(self, grant_id: str) -> dict:
        return {"schema": REQUEST_SCHEMA, "op": self.op, "url": self.url, "grant_id": grant_id,
                "deadline_ms": self.deadline_ms,
                "max_text_bytes": self.max_text_bytes if self.op == "read" else None,
                "viewport": {"width": self.width, "height": self.height},
                "max_png_bytes": self.max_png_bytes if self.op == "screenshot" else None}

    @classmethod
    def from_header(cls, value) -> tuple[BrowserRequest, str]:
        """The worker's parse: the exact header, or ValueError."""

        if type(value) is not dict or set(value) != {"schema", "op", "url", "grant_id", "deadline_ms",
                                                      "max_text_bytes", "viewport", "max_png_bytes"}:
            raise ValueError("request shape")
        if value["schema"] != REQUEST_SCHEMA or value["op"] not in OPERATIONS:
            raise ValueError("request schema")
        viewport = value["viewport"]
        if type(viewport) is not dict or set(viewport) != {"width", "height"}:
            raise ValueError("viewport")
        op = value["op"]
        if (value["max_text_bytes"] is None) != (op != "read") or (value["max_png_bytes"] is None) != (
                op != "screenshot"):
            raise ValueError("bounds do not match the operation")
        request = cls(op=op, url=value["url"], deadline_ms=value["deadline_ms"],
                      max_text_bytes=value["max_text_bytes"] or DEFAULT_TEXT_BYTES,
                      width=viewport["width"], height=viewport["height"],
                      max_png_bytes=value["max_png_bytes"] or DEFAULT_PNG_BYTES)
        return request, check_grant_id(value["grant_id"])


@dataclass(frozen=True, slots=True)
class BrowserObservation:
    """One verified browser result: the brokered facts and the bounded output."""

    op: str
    requested_url: str
    final_url: str
    status: int
    content_type: str
    title: str
    document_sha256: str
    document_bytes: int
    requests: int
    allowed: int
    denied: int
    body_bytes: int
    sandbox: dict
    media_type: str | None
    output: bytes
    output_sha256: str
    truncated: bool
    width: int | None
    height: int | None
    grant_sha256: str

    def summary(self) -> dict:
        """Everything but the output bytes: what the sealed artifact records."""

        return {"op": self.op, "requested_url": self.requested_url, "final_url": self.final_url,
                "status": self.status, "content_type": self.content_type, "title": self.title,
                "document_sha256": self.document_sha256, "document_bytes": self.document_bytes,
                "requests": self.requests, "allowed": self.allowed, "denied": self.denied,
                "body_bytes": self.body_bytes, "sandbox": dict(self.sandbox), "media_type": self.media_type,
                "output_bytes": len(self.output), "output_sha256": self.output_sha256,
                "truncated": self.truncated, "width": self.width, "height": self.height,
                "grant_sha256": self.grant_sha256}


def _png_size(data: bytes) -> tuple[int, int]:
    if (len(data) < 33 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR"
            or data[8:12] != b"\x00\x00\x00\r"):
        raise ValueError("output is not a PNG")
    return struct.unpack(">II", data[16:24])


class BrowserClient:
    """The control plane's frame-only client; never sees a browser driver."""

    __slots__ = ("_connect", "_factory", "_fetch")

    def __init__(self, transport_factory=None, *, fetch: FetchControlClient, _connect=None) -> None:
        if _connect is None and not callable(transport_factory):
            raise TypeError("a transport factory is required")
        if type(fetch) is not FetchControlClient:
            raise TypeError("an exact fetch control client is required")
        self._factory, self._connect, self._fetch = transport_factory, _connect, fetch

    @classmethod
    def for_worker(cls, configuration: BrowserControlConfiguration) -> BrowserClient:
        """The fixed client over `cp-browser` and `cp-fetch`: each call runs the listener's
        verified connect and the authenticated handshake under its own deadline."""

        from . import listener

        if type(configuration) is not BrowserControlConfiguration:
            raise TypeError("an exact browser control configuration is required")
        root, _spec = browser_channel()
        if Path(configuration.browser_pair_root) != root.pair_root:
            raise ValueError("browser endpoint is not the verified pair root")
        fetch = FetchControlClient.for_worker(configuration.fetch_pair_root, configuration.fetch_requester_boot_id)
        boot = configuration.browser_requester_boot_id

        def connect(deadline):
            fixed_root, spec = browser_channel()
            try:
                return listener.connect_authenticated(fixed_root, spec, requester_boot_id=boot, deadline=deadline)
            except listener.ListenerError as error:
                raise BrowserChannelError("unavailable", sent=False) from error

        return cls(None, fetch=fetch, _connect=connect)

    def _open(self, deadline):
        try:
            if self._connect is not None:
                return self._connect(deadline)
            from .gateway_connection import _RawConnection

            sock, codec = self._factory()
            return _RawConnection(sock, codec, owns_socket=True)
        except BrowserChannelError:
            raise
        except (broker.BrokerError, OSError, ValueError) as error:
            raise BrowserChannelError("unavailable", sent=False) from error

    def run(self, request: BrowserRequest, grant: BrowserGrant, *, excluded_hosts=()) -> BrowserObservation:
        """One browser operation under one grant, registered before and revoked after."""

        if type(request) is not BrowserRequest or type(grant) is not BrowserGrant:
            raise TypeError("an exact BrowserRequest and BrowserGrant are required")
        if not source_admits(grant.sources, request.url):
            raise BrowserChannelError("grant_denied", sent=False)
        if urlsplit(request.url).hostname in excluded_hosts:
            raise BrowserChannelError("grant_denied", sent=False)
        if projection_values(grant.projection, request.url) is None:
            # the URL carries data the grant's projection does not permit: nothing leaves
            raise BrowserChannelError("projection_denied", sent=False)
        try:
            identifier = self._fetch.register(grant, request.url, tuple(excluded_hosts))
        except FetchChannelError as error:
            raise BrowserChannelError("unavailable" if error.code in ("unavailable", "transport_failed",
                                                                      "malformed_result", "too_many_grants")
                                      else "projection_denied" if error.code == "projection_denied"
                                      else "grant_denied", sent=False) from None
        observation = failure = None
        try:
            observation = self._exchange(request, identifier, grant)
        except BrowserChannelError as error:
            failure = error
        try:
            usage = self._fetch.revoke(identifier)
        except FetchChannelError as error:
            usage = None
            if error.code == "grant_denied":  # expired before the revoke: nothing more can use it
                usage = False
        if failure is not None:
            raise failure
        if usage is False:
            raise BrowserChannelError("timeout")
        if (usage is None or usage.body_bytes != observation.body_bytes
                or usage.requests - usage.denied != observation.allowed or usage.requests > observation.requests):
            # the fetch service's own accounting must be exactly what the browser reported
            raise BrowserChannelError("malformed_result")
        return observation

    def _exchange(self, request: BrowserRequest, identifier: str, grant: BrowserGrant) -> BrowserObservation:
        deadline = broker.Deadline.after_ms(min(request.deadline_ms + 5_000, MAX_OPERATION_MS))
        connection = self._open(deadline)
        try:
            message_id = str(uuid4())
            connection.write(message_id=message_id, correlation_id=None, message_type=REQUEST_TYPE,
                             payload=canonical(request.header(identifier)), deadline=deadline)
            first = connection.read(deadline=deadline)
            if first.envelope.message_type != RESULT_TYPE or first.envelope.correlation_id != message_id:
                raise BrowserChannelError("malformed_result")
            try:
                response = strict_object(first.payload)
            except (ValueError, UnicodeDecodeError):
                raise BrowserChannelError("malformed_result") from None
            if response.get("schema") != RESULT_SCHEMA or type(response.get("ok")) is not bool:
                raise BrowserChannelError("malformed_result")
            if response["ok"] is False:
                if set(response) != {"schema", "ok", "code"} or response["code"] not in WORKER_CODES:
                    raise BrowserChannelError("malformed_result")
                raise BrowserChannelError(response["code"])
            try:
                return self._verified(connection, request, response, message_id, deadline, grant)
            except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                raise BrowserChannelError("malformed_result") from None
        except BrowserChannelError:
            raise
        except broker.DeadlineExceeded as error:
            raise BrowserChannelError("timeout") from error
        except (broker.BrokerError, OSError) as error:
            raise BrowserChannelError("transport_failed") from error
        finally:
            try:
                connection.close()
            except (broker.BrokerError, OSError):
                pass

    def _verified(self, connection, request, response, message_id, deadline, grant) -> BrowserObservation:
        if set(response) != _RESULT_KEYS or response["op"] != request.op or response["requested_url"] != request.url:
            raise ValueError("result shape")
        if response["profile_wiped"] is not True:
            raise ValueError("a session whose profile survived is never admitted")
        final_url = check_url(response["final_url"])
        if not source_admits(grant.sources, final_url):
            raise ValueError("the final document is outside the granted sources")
        sandbox = response["sandbox"]
        if (type(sandbox) is not dict or set(sandbox) != {"renderers", "seccomp_filter", "pid_namespace"}
                or sandbox["seccomp_filter"] is not True or sandbox["pid_namespace"] is not True):
            raise ValueError("no positive sandbox reading")
        bounded_int(sandbox["renderers"], 1, 64)
        output = response["output"]
        if type(output) is not dict or set(output) != _OUTPUT_KEYS or output["media_type"] != MEDIA[request.op]:
            raise ValueError("output shape")
        size = bounded_int(output["bytes"], 0, request.max_output_bytes)
        if type(output["sha256"]) is not str or _HEX64.fullmatch(output["sha256"]) is None:
            raise ValueError("digest")
        data = read_chunks(connection, size=size, count=output["chunk_count"], digest=output["sha256"],
                           message_type=OUTPUT_TYPE, correlation_id=message_id, deadline=deadline)
        deadline.require()
        width = height = None
        if request.op == "screenshot":
            width, height = _png_size(data)
            if (width, height) != (request.width, request.height) or (output["width"], output["height"]) != (
                    width, height) or output["truncated"] is not False:
                raise ValueError("screenshot size")
        else:
            if output["width"] is not None or output["height"] is not None or type(output["truncated"]) is not bool:
                raise ValueError("output fields")
            if request.op == "read":
                data.decode("utf-8")
            elif size != 0 or output["truncated"]:
                raise ValueError("navigate has no output")
        for name in ("document_sha256",):
            if type(response[name]) is not str or _HEX64.fullmatch(response[name]) is None:
                raise ValueError("document digest")
        title, content_type = response["title"], response["content_type"]
        if type(title) is not str or len(title) > MAX_TITLE or type(content_type) is not str or len(content_type) > 128:
            raise ValueError("text fields")
        requests = bounded_int(response["requests"], 1, 10_000)
        allowed = bounded_int(response["allowed"], 1, requests)
        denied = bounded_int(response["denied"], 0, requests)
        if allowed + denied > requests:
            raise ValueError("counts")
        return BrowserObservation(
            op=request.op, requested_url=request.url, final_url=final_url,
            status=bounded_int(response["status"], 100, 599), content_type=content_type, title=title,
            document_sha256=response["document_sha256"],
            document_bytes=bounded_int(response["document_bytes"], 0, grant.max_response_bytes),
            requests=requests, allowed=allowed, denied=denied,
            body_bytes=bounded_int(response["body_bytes"], 0, grant.max_total_bytes),
            sandbox=dict(sandbox), media_type=MEDIA[request.op], output=data,
            output_sha256=sha256(data).hexdigest(), truncated=output["truncated"],
            width=width, height=height, grant_sha256=grant.digest)
