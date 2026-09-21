"""Source-only wire admission and bounded authenticated ASGI receiving."""
import asyncio
import base64
import hashlib
import re
import time

from ..domain.owner_material import MAX_FILE_BYTES, validate_upload
from ..domain.refs import uuid_string
from ..services.works import WorkServiceError
from .wire import WireLimits, parse_json_object, parse_query

RECEIVE_SECONDS = 60
PATH = "/api/v1/works/"


def is_source_upload(path, method):
    return method == "POST" and path.startswith(PATH) and path.endswith("/sources")


def preflight(scope, fields):
    try:
        parts = scope["path"][len(PATH):].split("/")
        if len(parts) != 2 or parts[1] != "sources" or scope["method"] != "POST":
            raise ValueError()
        work_id = uuid_string(parts[0])
        parse_query(scope.get("query_string", b""), allowed=())
        header = fields.get("x-deeptwin-source-metadata", "")
        if (fields.get("content-type") != "application/octet-stream" or "content-encoding" in fields
                or not 1 <= len(header) <= 2048 or re.fullmatch(r"[A-Za-z0-9_-]+", header) is None):
            raise ValueError()
        raw = base64.b64decode(header + "=" * (-len(header) % 4), altchars=b"-_", validate=True)
        if len(raw) > 1536 or base64.urlsafe_b64encode(raw).rstrip(b"=").decode() != header:
            raise ValueError()
        value = parse_json_object(raw, required=("schema_version", "command_id", "expected_revision", "name", "declared_media_type", "size", "sha256"),
                                 limits=WireLimits(max_bytes=1536, max_depth=2, max_members=7, max_items=20, max_string_bytes=1024))
        meta = validate_upload(value)
        length = fields.get("content-length")
        if length is not None and (re.fullmatch(r"[0-9]{1,10}", length) is None or int(length) != meta["size"]):
            raise ValueError()
        return work_id, meta
    except (ValueError, TypeError, UnicodeError):
        raise WorkServiceError("invalid_input") from None


async def receive_original(receive, meta):
    data = bytearray()
    digest = hashlib.sha256()
    deadline = time.monotonic() + RECEIVE_SECONDS
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise WorkServiceError("unavailable")
        try:
            message = await asyncio.wait_for(receive(), remaining)
        except TimeoutError:
            raise WorkServiceError("unavailable") from None
        if message["type"] == "http.disconnect":
            raise asyncio.CancelledError()
        if message["type"] != "http.request":
            raise WorkServiceError("invalid_input")
        chunk = message.get("body", b"")
        if len(data) + len(chunk) > min(meta["size"], MAX_FILE_BYTES):
            raise WorkServiceError("too_large")
        data.extend(chunk)
        digest.update(chunk)
        if not message.get("more_body", False):
            break
    if len(data) != meta["size"] or digest.hexdigest() != meta["sha256"]:
        raise WorkServiceError("invalid_input")
    return bytes(data)
