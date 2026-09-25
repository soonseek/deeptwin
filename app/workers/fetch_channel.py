"""The controlled egress fetch channels (T043): `cp-fetch` and `browser-fetch`.

The fetch service (`fetch`, 20104:20104, the only worker on the `fetch-egress` network in
deploy/compose.yaml) is the one process that reaches the public network for the browser.
It runs the egress broker (`app.runtime.egress.broker_fetch`: HTTPS/443, GET only, grant
hosts only, every resolved address public, pinned connections, every redirect hop
revalidated, bounded bodies) behind two verified pair roots:

- `cp-fetch` (control → fetch, pair group 21102): control registers a grant under a fresh
  random `grant_id` before a browser session and revokes it afterwards. A grant names the
  navigation sources (https URL prefixes), the recipient hosts every request may reach,
  per-response and total byte limits, a request count, a redirect budget and a lifetime,
  and its **projection** (below); the registration also names the one navigation URL
  control will ask the browser to open. The revoke answer is the fetch service's own
  accounting of what the grant was used for.
- `browser-fetch` (browser → fetch, pair group 21110): the browser worker, which has no
  network of its own (`network_mode: none`), asks for one URL under a `grant_id` and a
  `kind` (`navigation` or `subresource`) and receives the status, the content type, the
  final URL and the body — or one closed refusal code. The browser holds only the
  unguessable id: it can never widen, extend or forge a grant, because the grant's content
  lives in the fetch service and came from control.

The projection (runtime.md §6: "a grant binds both permitted recipient and allowed
source/projection categories") is what data may appear in an outbound request. A GET
carries data in its URL only — the browser's request headers are never forwarded (no
Cookie, no Referer: the broker sends its own fixed `Accept`) and there is no body — so
the rule is over the normalized URL:

- a *navigation* URL must be exactly one of the grant's projection entries: the entry's
  exact https URL (no query) for pure navigation ("no source data"), or that URL followed
  by exactly the entry's query parameters, in the entry's order, canonically encoded
  (`quote`, no `+`, no other spelling), each value one the owner declared for the
  parameter's data source — compared by SHA-256 of its UTF-8 bytes, so the grant holds
  digests, never the values;
- a derived request (a redirect hop or a subresource) to any host other than the
  navigation's host must not carry a source value the navigation carried (raw,
  percent-decoded or form-decoded, case-insensitively): derived URLs inherit the
  navigation's source tags, and those tags are permitted only toward the entry's own
  recipient.

A violation is `projection_denied`, closed like every other refusal. This is exact
matching against declared values, not pattern-based secret detection: a value the owner
did not declare can never be sent, whatever it looks like.

Both pairs use the verified pair-root machinery the credential gateway and the document
service use (root-initialized generation, readiness record, socket inode, SO_PEERCRED,
boot-secret HMAC handshake, per-frame MACs). One request per connection, both directions
bounded; this module imports no network client and no browser driver.
"""

from __future__ import annotations

import json
import re
import secrets
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    unquote_plus,
    urlencode,
    urlsplit,
    urlunsplit,
)
from uuid import uuid4

from ..deployment.contracts import CONTROL, IPC_ROOT
from . import broker
from .ipc_root import PairRootSpec

FETCH_SERVICE = "fetch"
FETCH_UID = FETCH_GID = 20_104
BROWSER_SERVICE = "browser"
BROWSER_UID = BROWSER_GID = 20_105
CONTROL_CHANNEL_ID = "cp-fetch"
BROWSER_CHANNEL_ID = "browser-fetch"
CONTROL_PAIR_GID = 21_102
BROWSER_PAIR_GID = 21_110
SOCKET_NAME = "worker.sock"
CONTROL_PROTOCOL_ID = "fetch-grant-v1"
BROWSER_PROTOCOL_ID = "browser-fetch-v1"
GRANT_REQUEST_TYPE = "grant_request"
GRANT_RESULT_TYPE = "grant_result"
FETCH_REQUEST_TYPE = "fetch_request"
FETCH_RESULT_TYPE = "fetch_result"
FETCH_BODY_TYPE = "fetch_body"
GRANT_REQUEST_SCHEMA = "fetch-grant-request-v1"
GRANT_RESULT_SCHEMA = "fetch-grant-result-v1"
FETCH_REQUEST_SCHEMA = "browser-fetch-request-v1"
FETCH_RESULT_SCHEMA = "browser-fetch-result-v1"
ATTACHMENT_SCHEMA = "deeptwin-fetch-worker-attachment-v1"
MAX_FRAME_BYTES = 65_536
CHUNK_BYTES = 32_768
MAX_HEADER_BYTES = 8_192
MAX_GRANT_REQUEST_BYTES = 32_768  # a registration carries the projection's value digests
MAX_OPERATION_MS = 60_000
MAX_URL_BYTES = 2_048
MAX_SOURCES = 16
MAX_RECIPIENTS = 32
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_REQUESTS = 256
MAX_TTL_MS = 300_000
MAX_GRANTS = 64
MAX_CONTENT_TYPE = 128
MAX_ENTRIES = 16
MAX_PARAMETERS = 8
MAX_DATA_SOURCES = 8
MAX_SOURCE_VALUES = 64
MAX_VALUE_BYTES = 512
KINDS = ("navigation", "subresource")
# a fetch refusal: the broker's closed codes (app.runtime.egress.EGRESS_CODES) plus the
# projection's — kept literal here so the channel grammar never imports the runtime
FETCH_CODES = frozenset({"grant_denied", "projection_denied", "dns_denied", "redirect_denied", "too_large",
                         "timeout", "fetch_failed", "invalid_request"})
GRANT_CODES = frozenset({"invalid_request", "grant_denied", "projection_denied", "too_many_grants"})
CLIENT_CODES = FETCH_CODES | GRANT_CODES | {"unavailable", "transport_failed", "malformed_result"}
_BOOT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HOST_LABEL = re.compile(r"[a-z0-9-]{1,63}\Z")
_SOURCE_ID = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_PARAMETER = re.compile(r"[A-Za-z0-9_.~-]{1,64}\Z")

__all__ = [
    "ATTACHMENT_SCHEMA", "BrowserFetchClient", "BrowserGrant", "DataSource", "FetchChannelError",
    "FetchControlClient", "FetchWorkerConfiguration", "FetchedResponse", "GrantProjection", "GrantUsage",
    "ProjectionEntry", "browser_fetch_channel", "carries_source_values", "control_fetch_channel",
    "projected_url", "projection_values", "value_digest",
]


class FetchChannelError(RuntimeError):
    """A closed, sanitized fetch-channel failure. `sent` is False only when nothing of the
    request left this process (the connection or the handshake failed)."""

    def __init__(self, code: str = "transport_failed", *, sent: bool = True):
        if code not in CLIENT_CODES:
            code = "malformed_result"
        super().__init__(code)
        self.code = code
        self.sent = sent is not False


def _spec(channel_id, requester, requester_uid, pair_gid, protocol, requester_types, responder_types,
          pair_root):
    return broker.ChannelSpec(
        channel_id=channel_id, requester_service=requester, responder_service=FETCH_SERVICE,
        request_direction=f"{requester}-to-{FETCH_SERVICE}", protocol_id=protocol,
        requester_uid=requester_uid, requester_gid=requester_uid, responder_uid=FETCH_UID,
        responder_gid=FETCH_GID, pair_gid=pair_gid, pair_root=pair_root, socket_name=SOCKET_NAME,
        root_uid=FETCH_UID, root_gid=pair_gid, socket_uid=FETCH_UID, socket_gid=pair_gid,
        requester_message_types=requester_types, responder_message_types=responder_types,
        max_frame_bytes=MAX_FRAME_BYTES, max_in_flight=1, max_queue_depth=8,
        max_operation_ms=MAX_OPERATION_MS)


def control_fetch_channel() -> tuple[PairRootSpec, broker.ChannelSpec]:
    """The fixed `cp-fetch` pair root and channel (control registers/revokes grants)."""

    root = PairRootSpec(pair_root=IPC_ROOT / CONTROL_CHANNEL_ID, responder_uid=FETCH_UID,
                        responder_gid=FETCH_GID, pair_gid=CONTROL_PAIR_GID)
    return root, _spec(CONTROL_CHANNEL_ID, CONTROL["service_identity"], CONTROL["uid"], CONTROL_PAIR_GID,
                       CONTROL_PROTOCOL_ID, (GRANT_REQUEST_TYPE,), (GRANT_RESULT_TYPE,), root.endpoint_path)


def browser_fetch_channel() -> tuple[PairRootSpec, broker.ChannelSpec]:
    """The fixed `browser-fetch` pair root and channel (the browser asks for one URL)."""

    root = PairRootSpec(pair_root=IPC_ROOT / BROWSER_CHANNEL_ID, responder_uid=FETCH_UID,
                        responder_gid=FETCH_GID, pair_gid=BROWSER_PAIR_GID)
    return root, _spec(BROWSER_CHANNEL_ID, BROWSER_SERVICE, BROWSER_UID, BROWSER_PAIR_GID, BROWSER_PROTOCOL_ID,
                       (FETCH_REQUEST_TYPE,), (FETCH_BODY_TYPE, FETCH_RESULT_TYPE), root.endpoint_path)


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
class FetchWorkerConfiguration:
    """The fetch service's attachment object
    (`app.workers.fetch_worker_main --attachment-config`): its two pair roots and the one
    requester boot label accepted on each."""

    control_pair_root: str
    control_requester_boot_id: str
    browser_pair_root: str
    browser_requester_boot_id: str

    def __post_init__(self):
        _absolute(self.control_pair_root, "fetch control pair root")
        _absolute(self.browser_pair_root, "fetch browser pair root")
        _boot_id(self.control_requester_boot_id, "fetch control requester")
        _boot_id(self.browser_requester_boot_id, "fetch browser requester")

    @classmethod
    def from_mapping(cls, value) -> FetchWorkerConfiguration:
        fields = {"schema", "control_pair_root", "control_requester_boot_id", "browser_pair_root",
                  "browser_requester_boot_id"}
        if type(value) is not dict or set(value) != fields:
            raise ValueError("fetch worker configuration is not the exact attachment object")
        if value["schema"] != ATTACHMENT_SCHEMA:
            raise ValueError("fetch worker configuration schema is unsupported")
        return cls(**{name: value[name] for name in fields - {"schema"}})


# --- the shared wire grammar ---------------------------------------------------------

def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _no_duplicates(pairs):
    result = {}
    for key, item in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = item
    return result


def _reject_float(_text):
    raise ValueError("floats are not part of the grammar")


def strict_object(raw: bytes, *, limit: int = MAX_HEADER_BYTES) -> dict:
    """One canonical JSON object: no duplicate keys, no floats, bounded, re-encoding equal."""

    if type(raw) is not bytes or not 1 <= len(raw) <= limit:
        raise ValueError("header is out of bounds")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                       parse_float=_reject_float, parse_constant=_reject_float)
    if type(value) is not dict or canonical(value) != raw:
        raise ValueError("header is not canonical")
    return value


def chunk_count(size: int) -> int:
    return 0 if size == 0 else (size + CHUNK_BYTES - 1) // CHUNK_BYTES


def write_chunks(connection, data: bytes, *, message_type, correlation_id, deadline) -> None:
    for index in range(chunk_count(len(data))):
        connection.write(message_id=str(uuid4()), correlation_id=correlation_id, message_type=message_type,
                         payload=data[index * CHUNK_BYTES:(index + 1) * CHUNK_BYTES], deadline=deadline)


def read_chunks(connection, *, size, count, digest, message_type, correlation_id, deadline) -> bytes:
    if type(size) is not int or size < 0 or type(count) is not int or count != chunk_count(size):
        raise ValueError("chunk declaration is inconsistent")
    data, seen = bytearray(), set()
    for index in range(count):
        frame = connection.read(deadline=deadline)
        expected = CHUNK_BYTES if index < count - 1 else size - index * CHUNK_BYTES
        if (frame.envelope.message_type != message_type or frame.envelope.correlation_id != correlation_id
                or frame.envelope.message_id in seen or len(frame.payload) != expected):
            raise ValueError("chunk is not bound")
        seen.add(frame.envelope.message_id)
        data.extend(frame.payload)
    data = bytes(data)
    if len(data) != size or type(digest) is not str or sha256(data).hexdigest() != digest:
        raise ValueError("chunk digest mismatch")
    return data


def bounded_int(value, low, high) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ValueError("integer is out of bounds")
    return value


def grant_id() -> str:
    """A fresh unguessable grant id: 256 random bits, lowercase hex."""

    return secrets.token_hex(32)


def check_grant_id(value) -> str:
    if type(value) is not str or _HEX64.fullmatch(value) is None:
        raise ValueError("grant id is invalid")
    return value


def check_hostname(value) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 253 or value != value.lower()
            or value.strip(".") != value or not all(_HOST_LABEL.fullmatch(part) for part in value.split("."))):
        raise ValueError("hostname is invalid")
    return value


def check_url(value) -> str:
    """An absolute https URL on port 443 without userinfo, fragment or control characters."""

    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= MAX_URL_BYTES:
        raise ValueError("url is out of bounds")
    if any(ord(ch) <= 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError("url carries control characters")
    parts = urlsplit(value)
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        raise ValueError("url is not a credential-free https url")
    try:
        port = parts.port
    except ValueError:
        raise ValueError("url port is invalid") from None
    if port not in (None, 443) or parts.fragment:
        raise ValueError("url is outside the brokered form")
    check_hostname(parts.hostname or "")
    if not _plain_path(parts.path):
        raise ValueError("url path carries dot segments or encoded separators")
    return value


def _plain_path(path: str) -> bool:
    """No `.`/`..` segment (literal or percent-encoded) and no encoded or backslash
    separator: a source prefix then means exactly what it says."""

    lowered = path.lower()
    if "\\" in path or "%2f" in lowered or "%5c" in lowered:
        return False
    return not any(segment.replace("%2e", ".") in (".", "..") for segment in lowered.split("/"))


def source_admits(sources, url) -> bool:
    """True when `url` lies under one of the https source prefixes (same host, and the
    path starts with the prefix's path)."""

    try:
        target = urlsplit(url)
    except ValueError:
        return False
    if not _plain_path(target.path):
        return False
    for prefix in sources:
        source = urlsplit(prefix)
        if (target.scheme == source.scheme and target.hostname == source.hostname
                and (target.port or 443) == (source.port or 443)
                and (target.path or "/").startswith(source.path or "/")):
            return True
    return False


def value_digest(value: str) -> str:
    """The digest a projection compares a source value by: SHA-256 of its UTF-8 bytes."""

    if type(value) is not str or not 1 <= len(value.encode("utf-8")) <= MAX_VALUE_BYTES:
        raise ValueError("a source value is 1-512 UTF-8 bytes")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError("a source value carries control characters")
    return sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DataSource:
    """One owner-declared data source: the digests of the values that may flow from it."""

    source_id: str
    value_sha256: tuple[str, ...]

    def __post_init__(self):
        if type(self.source_id) is not str or _SOURCE_ID.fullmatch(self.source_id) is None:
            raise ValueError("a data source id is invalid")
        if (type(self.value_sha256) is not tuple or not 1 <= len(self.value_sha256) <= MAX_SOURCE_VALUES
                or tuple(sorted(set(self.value_sha256))) != self.value_sha256
                or not all(type(item) is str and _HEX64.fullmatch(item) for item in self.value_sha256)):
            raise ValueError("a data source names 1-64 sorted unique value digests")

    def as_dict(self) -> dict:
        return {"source_id": self.source_id, "value_sha256": list(self.value_sha256)}


@dataclass(frozen=True, slots=True)
class ProjectionEntry:
    """One exact navigation the grant permits: an https URL without a query, plus the
    query parameters (in order) that may carry a declared source's values. No parameters
    is pure navigation: no source data at all."""

    url: str
    parameters: tuple[tuple[str, str], ...] = ()

    def __post_init__(self):
        check_url(self.url)
        parts = urlsplit(self.url)
        if parts.query or "?" in self.url or urlunsplit((parts.scheme, parts.netloc, parts.path, "", "")) != self.url:
            raise ValueError("a projection entry is an exact https url without a query")
        if type(self.parameters) is not tuple or len(self.parameters) > MAX_PARAMETERS:
            raise ValueError("a projection entry names at most 8 parameters")
        for item in self.parameters:
            if (type(item) is not tuple or len(item) != 2 or type(item[0]) is not str
                    or _PARAMETER.fullmatch(item[0]) is None or type(item[1]) is not str
                    or _SOURCE_ID.fullmatch(item[1]) is None):
                raise ValueError("a projection parameter is (name, source id)")
        if len({name for name, _source in self.parameters}) != len(self.parameters):
            raise ValueError("projection parameter names are unique")

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname

    def as_dict(self) -> dict:
        return {"url": self.url, "parameters": [{"name": name, "source": source} for name, source in self.parameters]}


@dataclass(frozen=True, slots=True)
class GrantProjection:
    """What data may appear in the grant's outbound requests (runtime.md §6)."""

    entries: tuple[ProjectionEntry, ...]
    data_sources: tuple[DataSource, ...] = ()

    def __post_init__(self):
        if (type(self.entries) is not tuple or not 1 <= len(self.entries) <= MAX_ENTRIES
                or not all(type(item) is ProjectionEntry for item in self.entries)
                or len({item.url for item in self.entries}) != len(self.entries)):
            raise ValueError("a projection names 1-16 unique entries")
        if (type(self.data_sources) is not tuple or len(self.data_sources) > MAX_DATA_SOURCES
                or not all(type(item) is DataSource for item in self.data_sources)
                or len({item.source_id for item in self.data_sources}) != len(self.data_sources)):
            raise ValueError("a projection declares at most 8 unique data sources")
        if sum(len(item.value_sha256) for item in self.data_sources) > MAX_SOURCE_VALUES * 2:
            raise ValueError("a projection declares at most 128 value digests")
        declared = {item.source_id for item in self.data_sources}
        used = {source for entry in self.entries for _name, source in entry.parameters}
        if used != declared:
            raise ValueError("every parameter's source is declared, and every declared source is used")

    def source(self, source_id: str) -> DataSource:
        return next(item for item in self.data_sources if item.source_id == source_id)

    def as_dict(self) -> dict:
        return {"entries": [item.as_dict() for item in self.entries],
                "data_sources": [item.as_dict() for item in self.data_sources]}

    @classmethod
    def from_mapping(cls, value) -> GrantProjection:
        if type(value) is not dict or set(value) != {"entries", "data_sources"}:
            raise ValueError("projection is not the exact object")
        if type(value["entries"]) is not list or type(value["data_sources"]) is not list:
            raise ValueError("projection lists are invalid")
        entries = []
        for item in value["entries"]:
            if type(item) is not dict or set(item) != {"url", "parameters"} or type(item["parameters"]) is not list:
                raise ValueError("projection entry shape")
            parameters = []
            for parameter in item["parameters"]:
                if type(parameter) is not dict or set(parameter) != {"name", "source"}:
                    raise ValueError("projection parameter shape")
                parameters.append((parameter["name"], parameter["source"]))
            entries.append(ProjectionEntry(url=item["url"], parameters=tuple(parameters)))
        sources = []
        for item in value["data_sources"]:
            if type(item) is not dict or set(item) != {"source_id", "value_sha256"} \
                    or type(item["value_sha256"]) is not list:
                raise ValueError("data source shape")
            sources.append(DataSource(source_id=item["source_id"], value_sha256=tuple(item["value_sha256"])))
        return cls(entries=tuple(entries), data_sources=tuple(sources))


def projected_url(entry: ProjectionEntry, values=()) -> str:
    """The one canonical URL of `entry` with `values` (in the entry's parameter order)."""

    if type(entry) is not ProjectionEntry or len(tuple(values)) != len(entry.parameters):
        raise ValueError("one value per projection parameter is required")
    if not entry.parameters:
        return entry.url
    pairs = [(name, value) for (name, _source), value in zip(entry.parameters, values, strict=True)]
    return entry.url + "?" + urlencode(pairs, quote_via=quote, safe="")


def projection_values(projection: GrantProjection, url) -> tuple[ProjectionEntry, tuple[str, ...]] | None:
    """`(entry, carried values)` when `url` is exactly one of the projection's entries with
    only declared values in its parameters, canonically encoded; else None."""

    if type(projection) is not GrantProjection or type(url) is not str:
        return None
    try:
        check_url(url)
        parts = urlsplit(url)
    except ValueError:
        return None
    base = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    entry = next((item for item in projection.entries if item.url == base), None)
    if entry is None:
        return None
    if not entry.parameters:
        return (entry, ()) if url == entry.url else None
    try:
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True, errors="strict")
    except (ValueError, UnicodeDecodeError):
        return None
    if [name for name, _value in pairs] != [name for name, _source in entry.parameters]:
        return None
    values = tuple(value for _name, value in pairs)
    try:
        if projected_url(entry, values) != url:
            return None  # one canonical spelling only: no `+`, no alternative percent-encoding
        for (_name, source), value in zip(entry.parameters, values, strict=True):
            if value_digest(value) not in projection.source(source).value_sha256:
                return None
    except ValueError:
        return None
    return entry, values


def carries_source_values(values, url) -> bool:
    """True when `url` carries any of `values` — raw, percent-decoded or form-decoded,
    ignoring case."""

    if not values:
        return False
    try:
        haystacks = {url.casefold(), unquote(url).casefold(), unquote_plus(url).casefold()}
    except (TypeError, ValueError):
        return True
    return any(value.casefold() in haystack for value in values for haystack in haystacks)


@dataclass(frozen=True, slots=True)
class BrowserGrant:
    """What one browser session may reach: navigation `sources` (https URL prefixes the
    top-level document must lie under, redirects included), the `recipients` (hosts
    every request — the document, its redirects and every subresource — may be sent to)
    and the `projection` (which exact navigations may carry which declared source values),
    with per-response and total byte limits, a request count, a redirect budget and a
    lifetime. Every source host is a recipient; every projection entry lies under a
    source."""

    sources: tuple[str, ...]
    recipients: tuple[str, ...]
    projection: GrantProjection
    max_response_bytes: int = 2 * 1024 * 1024
    max_total_bytes: int = 8 * 1024 * 1024
    max_requests: int = 64
    max_redirects: int = 3
    ttl_ms: int = 60_000

    def __post_init__(self):
        if (type(self.sources) is not tuple or not 1 <= len(self.sources) <= MAX_SOURCES
                or len(set(self.sources)) != len(self.sources)):
            raise ValueError("grant sources must be 1-16 unique https prefixes")
        if (type(self.recipients) is not tuple or not 1 <= len(self.recipients) <= MAX_RECIPIENTS
                or len(set(self.recipients)) != len(self.recipients)):
            raise ValueError("grant recipients must be 1-32 unique hosts")
        for host in self.recipients:
            check_hostname(host)
        for source in self.sources:
            check_url(source)
            parts = urlsplit(source)
            if parts.query or not (parts.path or "/").endswith("/") or parts.hostname not in self.recipients:
                raise ValueError("a grant source is a query-free https prefix on a recipient host")
        if type(self.projection) is not GrantProjection:
            raise ValueError("a grant carries an exact projection")
        if not all(source_admits(self.sources, entry.url) for entry in self.projection.entries):
            raise ValueError("every projection entry lies under a grant source")
        bounded_int(self.max_response_bytes, 1, MAX_RESPONSE_BYTES)
        bounded_int(self.max_total_bytes, self.max_response_bytes, MAX_TOTAL_BYTES)
        bounded_int(self.max_requests, 1, MAX_REQUESTS)
        bounded_int(self.max_redirects, 1, 10)
        bounded_int(self.ttl_ms, 1_000, MAX_TTL_MS)

    def as_dict(self) -> dict:
        return {"sources": list(self.sources), "recipients": list(self.recipients),
                "projection": self.projection.as_dict(),
                "max_response_bytes": self.max_response_bytes, "max_total_bytes": self.max_total_bytes,
                "max_requests": self.max_requests, "max_redirects": self.max_redirects, "ttl_ms": self.ttl_ms}

    @classmethod
    def from_mapping(cls, value) -> BrowserGrant:
        fields = {"sources", "recipients", "projection", "max_response_bytes", "max_total_bytes", "max_requests",
                  "max_redirects", "ttl_ms"}
        if type(value) is not dict or set(value) != fields:
            raise ValueError("grant is not the exact object")
        if type(value["sources"]) is not list or type(value["recipients"]) is not list:
            raise ValueError("grant lists are invalid")
        return cls(sources=tuple(value["sources"]), recipients=tuple(value["recipients"]),
                   projection=GrantProjection.from_mapping(value["projection"]),
                   **{name: value[name] for name in fields - {"sources", "recipients", "projection"}})

    @property
    def digest(self) -> str:
        return sha256(canonical(self.as_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class GrantUsage:
    """The fetch service's own accounting of one grant (the revoke answer)."""

    requests: int
    denied: int
    body_bytes: int

    @classmethod
    def from_mapping(cls, value) -> GrantUsage:
        if type(value) is not dict or set(value) != {"requests", "denied", "body_bytes"}:
            raise ValueError("usage shape")
        return cls(requests=bounded_int(value["requests"], 0, MAX_REQUESTS),
                   denied=bounded_int(value["denied"], 0, 1_000_000),
                   body_bytes=bounded_int(value["body_bytes"], 0, MAX_TOTAL_BYTES))


@dataclass(frozen=True, slots=True)
class FetchedResponse:
    status: int
    final_url: str
    content_type: str
    redirects: int
    body: bytes
    sha256: str


def _connector(root_and_spec, boot, error_code="unavailable"):
    def connect(deadline):
        from . import listener

        root, spec = root_and_spec()
        try:
            return listener.connect_authenticated(root, spec, requester_boot_id=boot, deadline=deadline)
        except listener.ListenerError as error:
            raise FetchChannelError(error_code, sent=False) from error

    return connect


def _open(connect, factory, deadline):
    try:
        if connect is not None:
            return connect(deadline)
        from .gateway_connection import _RawConnection

        sock, codec = factory()
        return _RawConnection(sock, codec, owns_socket=True)
    except FetchChannelError:
        raise
    except (broker.BrokerError, OSError, ValueError) as error:
        raise FetchChannelError("unavailable", sent=False) from error


def _close(connection):
    try:
        connection.close()
    except (broker.BrokerError, OSError):
        pass


class FetchControlClient:
    """Control's frame-only client on `cp-fetch`: register and revoke one grant."""

    __slots__ = ("_connect", "_deadline_ms", "_factory")

    def __init__(self, transport_factory=None, *, deadline_ms: int = 10_000, _connect=None):
        if _connect is None and not callable(transport_factory):
            raise TypeError("a transport factory is required")
        bounded_int(deadline_ms, 1, MAX_OPERATION_MS)
        self._factory, self._deadline_ms, self._connect = transport_factory, deadline_ms, _connect

    @classmethod
    def for_worker(cls, pair_root: str, requester_boot_id: str, *, deadline_ms: int = 10_000):
        root, _spec = control_fetch_channel()
        if Path(pair_root) != root.pair_root:
            raise ValueError("fetch endpoint is not the verified pair root")
        return cls(None, deadline_ms=deadline_ms,
                   _connect=_connector(control_fetch_channel, _boot_id(requester_boot_id, "fetch control")))

    def _call(self, request: dict) -> dict:
        deadline = broker.Deadline.after_ms(self._deadline_ms)
        connection = _open(self._connect, self._factory, deadline)
        try:
            message_id = str(uuid4())
            connection.write(message_id=message_id, correlation_id=None, message_type=GRANT_REQUEST_TYPE,
                             payload=canonical({**request, "schema": GRANT_REQUEST_SCHEMA}), deadline=deadline)
            frame = connection.read(deadline=deadline)
            if frame.envelope.message_type != GRANT_RESULT_TYPE or frame.envelope.correlation_id != message_id:
                raise FetchChannelError("malformed_result")
            try:
                response = strict_object(frame.payload)
            except (ValueError, UnicodeDecodeError):
                raise FetchChannelError("malformed_result") from None
            if response.get("schema") != GRANT_RESULT_SCHEMA or type(response.get("ok")) is not bool:
                raise FetchChannelError("malformed_result")
            if response["ok"] is False:
                if set(response) != {"schema", "ok", "code"} or response["code"] not in GRANT_CODES:
                    raise FetchChannelError("malformed_result")
                raise FetchChannelError(response["code"])
            return response
        except FetchChannelError:
            raise
        except (broker.BrokerError, OSError) as error:
            raise FetchChannelError("transport_failed") from error
        finally:
            _close(connection)

    def register(self, grant: BrowserGrant, navigation_url: str, excluded_hosts=()) -> str:
        """Register `grant` under a fresh id for the one `navigation_url` control will ask
        the browser to open (the fetch service checks it against the projection and
        tags every later request with the source values it carries); `excluded_hosts`
        (the product's own origin hosts) are refused as recipients and never reachable
        through it."""

        if type(grant) is not BrowserGrant:
            raise TypeError("an exact BrowserGrant is required")
        if type(navigation_url) is not str:
            raise TypeError("a navigation url is required")
        excluded = [check_hostname(host) for host in excluded_hosts]
        identifier = grant_id()
        request = {"op": "register", "grant_id": identifier, "grant": grant.as_dict(),
                   "navigation_url": navigation_url}
        if excluded:
            request["excluded_hosts"] = excluded
        response = self._call(request)
        if set(response) != {"schema", "ok", "grant_id", "grant_sha256"} or response["grant_id"] != identifier \
                or response["grant_sha256"] != grant.digest:
            raise FetchChannelError("malformed_result")
        return identifier

    def revoke(self, identifier: str) -> GrantUsage:
        check_grant_id(identifier)
        response = self._call({"op": "revoke", "grant_id": identifier})
        if set(response) != {"schema", "ok", "grant_id", "usage"} or response["grant_id"] != identifier:
            raise FetchChannelError("malformed_result")
        try:
            return GrantUsage.from_mapping(response["usage"])
        except ValueError:
            raise FetchChannelError("malformed_result") from None


class BrowserFetchClient:
    """The browser worker's frame-only client on `browser-fetch`: one URL per call."""

    __slots__ = ("_connect", "_factory")

    def __init__(self, transport_factory=None, *, _connect=None):
        if _connect is None and not callable(transport_factory):
            raise TypeError("a transport factory is required")
        self._factory, self._connect = transport_factory, _connect

    @classmethod
    def for_worker(cls, pair_root: str, requester_boot_id: str):
        root, _spec = browser_fetch_channel()
        if Path(pair_root) != root.pair_root:
            raise ValueError("fetch endpoint is not the verified pair root")
        return cls(None, _connect=_connector(browser_fetch_channel, _boot_id(requester_boot_id, "browser fetch")))

    def fetch(self, identifier: str, url: str, *, kind: str, deadline: broker.Deadline) -> FetchedResponse:
        check_grant_id(identifier)
        if kind not in KINDS:
            raise FetchChannelError("invalid_request", sent=False)
        connection = _open(self._connect, self._factory, deadline)
        try:
            message_id = str(uuid4())
            connection.write(message_id=message_id, correlation_id=None, message_type=FETCH_REQUEST_TYPE,
                             payload=canonical({"schema": FETCH_REQUEST_SCHEMA, "grant_id": identifier,
                                                "url": url, "kind": kind}), deadline=deadline)
            frame = connection.read(deadline=deadline)
            if frame.envelope.message_type != FETCH_RESULT_TYPE or frame.envelope.correlation_id != message_id:
                raise FetchChannelError("malformed_result")
            try:
                response = strict_object(frame.payload)
            except (ValueError, UnicodeDecodeError):
                raise FetchChannelError("malformed_result") from None
            if response.get("schema") != FETCH_RESULT_SCHEMA or type(response.get("ok")) is not bool:
                raise FetchChannelError("malformed_result")
            if response["ok"] is False:
                if set(response) != {"schema", "ok", "code"} or response["code"] not in FETCH_CODES:
                    raise FetchChannelError("malformed_result")
                raise FetchChannelError(response["code"])
            if set(response) != {"schema", "ok", "status", "final_url", "content_type", "redirects",
                                 "body_bytes", "body_sha256", "chunk_count"}:
                raise FetchChannelError("malformed_result")
            try:
                status = bounded_int(response["status"], 100, 599)
                redirects = bounded_int(response["redirects"], 0, 10)
                final_url = check_url(response["final_url"])
                content_type = response["content_type"]
                if type(content_type) is not str or len(content_type) > MAX_CONTENT_TYPE or any(
                        ord(ch) < 0x20 or ord(ch) > 0x7E for ch in content_type):
                    raise ValueError("content type")
                size = bounded_int(response["body_bytes"], 0, MAX_RESPONSE_BYTES)
                if type(response["body_sha256"]) is not str or _HEX64.fullmatch(response["body_sha256"]) is None:
                    raise ValueError("digest")
                body = read_chunks(connection, size=size, count=response["chunk_count"],
                                   digest=response["body_sha256"], message_type=FETCH_BODY_TYPE,
                                   correlation_id=message_id, deadline=deadline)
            except ValueError:
                raise FetchChannelError("malformed_result") from None
            return FetchedResponse(status=status, final_url=final_url, content_type=content_type,
                                   redirects=redirects, body=body, sha256=response["body_sha256"])
        except FetchChannelError:
            raise
        except broker.DeadlineExceeded as error:
            raise FetchChannelError("timeout") from error
        except (broker.BrokerError, OSError) as error:
            raise FetchChannelError("transport_failed") from error
        finally:
            _close(connection)
