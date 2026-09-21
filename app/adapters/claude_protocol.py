"""Pure bounded Claude JSON/SSE framing. No clocks, callbacks, clients or I/O."""

from __future__ import annotations

import json
import math
import re

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")


class ProtocolError(ValueError):
    def __init__(self, detail_code: str):
        self.detail_code = detail_code
        super().__init__(detail_code)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate_json_key")
        result[key] = value
    return result


def decode_json(raw: bytes | str, *, detail_code="invalid_event_json"):
    """Retain legacy finite floating point values; private codecs layer types."""

    def reject(_value):
        raise ProtocolError("nonfinite_json_constant")

    def finite_float(token):
        value = float(token)
        if not math.isfinite(value):
            raise ProtocolError("nonfinite_json_constant")
        return value

    try:
        return json.loads(
            raw,
            object_pairs_hook=_object,
            parse_constant=reject,
            parse_float=finite_float,
        )
    except ProtocolError:
        raise
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, RecursionError) as exc:
        raise ProtocolError(detail_code) from exc


def safe_id(value):
    if type(value) is not str or not SAFE_ID.fullmatch(value):
        raise ProtocolError("invalid_id")
    return value


def integer(value, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError("invalid_integer")
    return value


def parse_sse_fields(lines: list[bytes], *, allow_comments=False):
    event_name = None
    data_lines = []
    for line in lines:
        if line.startswith(b":"):
            # Validate comment UTF8 in the private profile; legacy ignored it.
            if allow_comments:
                try:
                    line.decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ProtocolError("invalid_utf8") from exc
            continue
        field, value = line.split(b":", 1) if b":" in line else (line, b"")
        if value.startswith(b" "):
            value = value[1:]
        if field == b"event":
            if event_name is not None:
                raise ProtocolError("duplicate_event_field")
            try:
                event_name = value.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ProtocolError("invalid_utf8") from exc
        elif field == b"data":
            data_lines.append(value)
        else:
            raise ProtocolError("unknown_sse_field")
    if (
        allow_comments
        and event_name is None
        and not data_lines
        and all(x.startswith(b":") for x in lines)
    ):
        return None
    if event_name is None or not SAFE_ID.fullmatch(event_name):
        raise ProtocolError("invalid_event_name")
    raw = b"\n".join(data_lines)
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("invalid_utf8") from exc
    if event_name == "ping" and not raw:
        return event_name, {"type": "ping"}
    return event_name, decode_json(raw)


class SSEDecoder:
    """Each iterator pull consumes at most one bounded line (None or event).

    Callers exhaust each feed before the next feed and own deadline/cancel
    checks before each pull. Later malformed events cannot suppress earlier ones.
    """

    def __init__(
        self,
        *,
        max_total_bytes=1048576,
        max_event_bytes=262144,
        max_events=10000,
        allow_comments=True,
    ):
        self.buffer = bytearray()
        self.fields = []
        self.total = self.event_bytes = self.event_count = 0
        self.max_total_bytes = max_total_bytes
        self.max_event_bytes = max_event_bytes
        self.max_events = max_events
        self.allow_comments = allow_comments

    def feed(self, chunk):
        if type(chunk) is not bytes:
            raise ProtocolError("invalid_chunk")
        self.total += len(chunk)
        if self.total > self.max_total_bytes:
            raise ProtocolError("stream_limit")
        self.buffer.extend(chunk)
        return self._steps()

    def _steps(self):
        while True:
            newline = self.buffer.find(b"\n")
            if newline < 0:
                if self.event_bytes + len(self.buffer) > self.max_event_bytes:
                    raise ProtocolError("event_limit")
                return
            line = bytes(self.buffer[:newline])
            del self.buffer[: newline + 1]
            if line.endswith(b"\r"):
                line = line[:-1]
            self.event_bytes += newline + 1
            if self.event_bytes > self.max_event_bytes:
                raise ProtocolError("event_limit")
            if line:
                self.fields.append(line)
                yield None
                continue
            if not self.fields:
                self.event_bytes = 0
                yield None
                continue
            self.event_count += 1
            if self.event_count > self.max_events:
                raise ProtocolError("event_count_limit")
            event = parse_sse_fields(self.fields, allow_comments=self.allow_comments)
            self.fields = []
            self.event_bytes = 0
            yield event

    def finish(self):
        if self.buffer or self.fields:
            raise ProtocolError("incomplete_sse")
        yield from ()
