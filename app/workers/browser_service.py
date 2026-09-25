"""The browser service's session engine (worker side of `cp-browser`, T043).

It runs only inside the browser service process (`app.workers.browser_worker_main`,
identity 20105, `network_mode: none`). One authenticated connection carries one request;
one request is one fresh Chromium session (`app.adapters.browser.ChromiumSession`): a new
profile directory, the positive sandbox probe before any content, one navigation whose
every request is fulfilled through the fetch service under the request's grant id, the
bounded observation (`navigate`: facts only; `read`: the rendered text; `screenshot`: the
viewport PNG), and then Chromium stopped and the profile removed — before the answer, so
the answer can state that nothing of the session survived. Every failure answers a closed
code; nothing is invented to stand in for a page the session could not produce.
"""

from __future__ import annotations

import time
from hashlib import sha256
from uuid import uuid4

from . import broker
from .browser_channel import (
    MEDIA,
    OUTPUT_TYPE,
    REQUEST_TYPE,
    RESULT_SCHEMA,
    RESULT_TYPE,
    BrowserRequest,
)
from .fetch_channel import (
    FetchChannelError,
    canonical,
    chunk_count,
    strict_object,
    write_chunks,
)

_ANSWER_MARGIN_S = 1.0
_FETCH_CODES = frozenset({"grant_denied", "dns_denied", "redirect_denied", "too_large", "timeout",
                          "fetch_failed", "invalid_request"})


class _Refusal(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class _FetchFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


class BrowserService:
    """Serves one browser session per authenticated connection."""

    def __init__(self, spec: broker.ChannelSpec, *, chromium_path: str, profile_root: str, fetch_client,
                 session_factory=None) -> None:
        if type(spec) is not broker.ChannelSpec:
            raise TypeError("an exact channel spec is required")
        self.spec = spec
        self._chromium, self._profiles, self._fetch = chromium_path, profile_root, fetch_client
        self._session_factory = session_factory
        self.last_profile: str | None = None

    def _session(self, request):
        if self._session_factory is not None:
            return self._session_factory(request)
        from ..adapters.browser import ChromiumSession

        return ChromiumSession(self._chromium, self._profiles, width=request.width, height=request.height)

    def run(self, request: BrowserRequest, grant_id: str, deadline_end: float) -> tuple[dict, bytes]:
        from ..adapters.browser import BrowserRefusal

        fetch_deadline = broker.Deadline(deadline_end)

        def fetcher(url, kind):
            try:
                return self._fetch.fetch(grant_id, url, kind=kind, deadline=fetch_deadline)
            except FetchChannelError as error:
                raise _FetchFailure(error.code if error.code in _FETCH_CODES else "fetch_failed") from None

        session = self._session(request)
        output, width, height, truncated = b"", None, None, False
        try:
            try:
                session.start(deadline_end)
                sandbox = session.probe_sandbox(deadline_end)
                self.last_profile = session.profile
                navigation = session.navigate(request.url, fetcher, deadline_end)
                if request.op == "read":
                    output, truncated = session.read_text(request.max_text_bytes, deadline_end)
                elif request.op == "screenshot":
                    output, width, height = session.screenshot(request.max_png_bytes, deadline_end)
            except BrowserRefusal as refusal:
                raise _Refusal(refusal.code) from None
            except OSError:
                raise _Refusal("render_failed") from None
        finally:
            wiped = session.close()
        if not wiped:
            raise _Refusal("render_failed")
        if time.monotonic() > deadline_end:
            raise _Refusal("timeout")
        result = {
            "op": request.op, "requested_url": request.url, "final_url": navigation.final_url,
            "status": navigation.status, "content_type": navigation.content_type, "title": navigation.title,
            "document_sha256": navigation.document_sha256, "document_bytes": navigation.document_bytes,
            "requests": navigation.requests, "allowed": navigation.allowed, "denied": navigation.denied,
            "body_bytes": navigation.body_bytes, "sandbox": sandbox, "profile_wiped": True,
            "output": {"media_type": MEDIA[request.op], "bytes": len(output), "sha256": sha256(output).hexdigest(),
                       "chunk_count": chunk_count(len(output)), "truncated": truncated,
                       "width": width, "height": height},
        }
        return result, output

    def serve_connection(self, connection, *, deadline: broker.Deadline) -> str:
        """One request, one answer. Returns the closed outcome (`ok` or the refusal code)."""

        from .gateway_connection import _require_connection

        _require_connection(connection)
        first = connection.read(deadline=deadline)
        if first.envelope.message_type != REQUEST_TYPE or first.envelope.correlation_id is not None:
            raise broker.ProtocolViolation()
        message_id = first.envelope.message_id
        try:
            try:
                request, grant_id = BrowserRequest.from_header(strict_object(first.payload))
            except (ValueError, TypeError, UnicodeDecodeError):
                raise _Refusal("invalid_request") from None
            end = min(deadline.end_monotonic - _ANSWER_MARGIN_S, time.monotonic() + request.deadline_ms / 1000.0)
            result, output = self.run(request, grant_id, end)
        except _Refusal as refusal:
            connection.write(message_id=str(uuid4()), correlation_id=message_id, message_type=RESULT_TYPE,
                             payload=canonical({"schema": RESULT_SCHEMA, "ok": False, "code": refusal.code}),
                             deadline=deadline)
            return refusal.code
        connection.write(message_id=str(uuid4()), correlation_id=message_id, message_type=RESULT_TYPE,
                         payload=canonical({"schema": RESULT_SCHEMA, "ok": True, **result}), deadline=deadline)
        write_chunks(connection, output, message_type=OUTPUT_TYPE, correlation_id=message_id, deadline=deadline)
        return "ok"


__all__ = ["BrowserService"]
