"""The typed backup stream over the verified `cp-backup` channel (T070).

Both sides import this module and nothing else of each other: the control plane never
imports worker or key code, and the worker never imports vault, route or credential
code. One connection carries exactly one operation:

    requester: backup_request {schema, op, key_mode, recipient, identity, size, sha256}
               backup_chunk * n   (raw body bytes, at most CHUNK_BYTES each)
               backup_end {schema, size, sha256}
    responder: backup_result {schema, ok: true, op, size, sha256, recipient}
               backup_chunk * m
               backup_end {schema, size, sha256}
           or  backup_result {schema, ok: false, code}          (no body)

`op` is `describe` (no body; the worker's own recipient and key state), `encrypt` (the
body is the typed archive; the result body is the age ciphertext) or `decrypt` (the
body is the ciphertext; the result body is the typed archive). `identity` is set only
for a `portable_recovery` decrypt, the owner's one-shot identity; an instance-mode
request never names a key: the worker uses its own read-only backup-key volume.

A body is accepted only whole: every chunk is typed, the running size never exceeds
the declared size, and the end frame and the received bytes must agree with the
declared size and SHA-256. A cut stream, an extra or reordered frame, or a changed
byte raises `BackupStreamError("stream_invalid")`; nothing partial is ever returned.
Frames are already authenticated and sequenced by the broker codec.
"""

from __future__ import annotations

import hashlib
import json
import re
from uuid import uuid4

REQUEST = "backup_request"
RESULT = "backup_result"
CHUNK = "backup_chunk"
END = "backup_end"
REQUEST_SCHEMA = "deeptwin-backup-crypto-request-v1"
RESULT_SCHEMA = "deeptwin-backup-crypto-result-v1"
END_SCHEMA = "deeptwin-backup-crypto-end-v1"
OPS = ("describe", "encrypt", "decrypt")
KEY_MODES = ("instance_backup_key", "portable_recovery")
FAILURE_CODES = ("key_unavailable", "decrypt_failed", "encrypt_failed", "stream_invalid",
                 "request_invalid")
CHUNK_BYTES = 32_768
MAX_STREAM_BYTES = 256 << 20
MAX_MESSAGE_BYTES = 4_096
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()

__all__ = [
    "CHUNK_BYTES", "FAILURE_CODES", "MAX_STREAM_BYTES", "OPS", "BackupStreamError",
    "read_body", "read_message", "write_body", "write_message",
]


class BackupStreamError(RuntimeError):
    """A closed stream failure; never carries body bytes, keys or paths."""

    def __init__(self, code: str = "stream_invalid"):
        self.code = code if code in FAILURE_CODES else "stream_invalid"
        super().__init__(self.code)


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("ascii")


def _strict(payload: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    try:
        if type(payload) is not bytes or not 1 <= len(payload) <= MAX_MESSAGE_BYTES:
            raise ValueError
        value = json.loads(payload.decode("ascii"), object_pairs_hook=pairs)
        if type(value) is not dict or _canonical(value) != payload:
            raise ValueError
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise BackupStreamError("stream_invalid") from None


def _size(value) -> int:
    if type(value) is not int or not 0 <= value <= MAX_STREAM_BYTES:
        raise BackupStreamError("request_invalid")
    return value


def _digest(value) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise BackupStreamError("request_invalid")
    return value


def check_request(value) -> dict:
    """The exact request object, or `request_invalid`."""

    if type(value) is not dict or set(value) != {"schema", "op", "key_mode", "recipient", "identity",
                                                  "size", "sha256"}:
        raise BackupStreamError("request_invalid")
    if value["schema"] != REQUEST_SCHEMA or value["op"] not in OPS or value["key_mode"] not in KEY_MODES:
        raise BackupStreamError("request_invalid")
    _size(value["size"])
    _digest(value["sha256"])
    for name in ("recipient", "identity"):
        if value[name] is not None and (type(value[name]) is not str or not 1 <= len(value[name]) <= 256):
            raise BackupStreamError("request_invalid")
    portable = value["key_mode"] == "portable_recovery"
    if value["op"] == "describe" and (value["size"] or value["recipient"] or value["identity"] or portable):
        raise BackupStreamError("request_invalid")
    if value["op"] == "encrypt" and (value["identity"] is not None or (value["recipient"] is None) == portable):
        raise BackupStreamError("request_invalid")
    if value["op"] == "decrypt" and (value["recipient"] is not None or (value["identity"] is None) == portable):
        raise BackupStreamError("request_invalid")
    return value


def check_result(value) -> dict:
    if type(value) is not dict or value.get("schema") != RESULT_SCHEMA:
        raise BackupStreamError("stream_invalid")
    if value.get("ok") is False:
        if set(value) != {"schema", "ok", "code"} or value["code"] not in FAILURE_CODES:
            raise BackupStreamError("stream_invalid")
        return value
    if (value.get("ok") is not True or set(value) != {"schema", "ok", "op", "size", "sha256", "recipient"}
            or value["op"] not in OPS
            or (value["recipient"] is not None and (type(value["recipient"]) is not str
                                                    or not 1 <= len(value["recipient"]) <= 256))):
        raise BackupStreamError("stream_invalid")
    try:
        _size(value["size"])
        _digest(value["sha256"])
    except BackupStreamError:
        raise BackupStreamError("stream_invalid") from None
    return value


def write_message(connection, message_type: str, value: dict, *, deadline, correlation_id=None) -> str:
    message_id = str(uuid4())
    connection.write(message_id=message_id, correlation_id=correlation_id, message_type=message_type,
                     payload=_canonical(value), deadline=deadline)
    return message_id


def read_message(connection, message_type: str, *, deadline) -> tuple[str, dict]:
    frame = connection.read(deadline=deadline)
    if frame.envelope.message_type != message_type:
        raise BackupStreamError("stream_invalid")
    return frame.envelope.message_id, _strict(frame.payload)


def write_body(connection, body: bytes, *, deadline, correlation_id=None) -> None:
    """The body in bounded chunks, then the end frame binding its size and digest."""

    view = memoryview(body)
    for offset in range(0, len(body), CHUNK_BYTES):
        connection.write(message_id=str(uuid4()), correlation_id=correlation_id, message_type=CHUNK,
                         payload=bytes(view[offset:offset + CHUNK_BYTES]), deadline=deadline)
    write_message(connection, END, {"schema": END_SCHEMA, "size": len(body),
                                    "sha256": hashlib.sha256(body).hexdigest()},
                  deadline=deadline, correlation_id=correlation_id)


def read_body(connection, *, size: int, sha256: str, deadline) -> bytes:
    """Exactly the declared body, or `stream_invalid` with nothing returned."""

    size, sha256 = _size(size), _digest(sha256)
    received = bytearray()
    hasher = hashlib.sha256()
    try:
        while True:
            frame = connection.read(deadline=deadline)
            kind = frame.envelope.message_type
            if kind == END:
                end = _strict(frame.payload)
                if (set(end) != {"schema", "size", "sha256"} or end["schema"] != END_SCHEMA
                        or end["size"] != size or end["sha256"] != sha256
                        or len(received) != size or hasher.hexdigest() != sha256):
                    raise BackupStreamError("stream_invalid")
                return bytes(received)
            if kind != CHUNK or not 1 <= len(frame.payload) <= CHUNK_BYTES \
                    or len(received) + len(frame.payload) > size:
                raise BackupStreamError("stream_invalid")
            received += frame.payload
            hasher.update(frame.payload)
    except BackupStreamError:
        received[:] = b"\x00" * len(received)
        raise
