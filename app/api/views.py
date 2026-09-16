"""API compatibility facade and HTTP Server-Sent Events framing."""
# ruff: noqa: PLC0414 - explicit compatibility re-exports.

from ..domain.public_events import (
    _DDL as _DDL,
)
from ..domain.public_events import (
    _ENVELOPE_KEYS as _ENVELOPE_KEYS,
)
from ..domain.public_events import (
    _EVENT_DDL as _EVENT_DDL,
)
from ..domain.public_events import (
    _EXPECTED_EVENT_SCHEMA as _EXPECTED_EVENT_SCHEMA,
)
from ..domain.public_events import (
    _MIGRATION_HASH as _MIGRATION_HASH,
)
from ..domain.public_events import (
    _TIMESTAMP as _TIMESTAMP,
)
from ..domain.public_events import (
    ACTOR_KINDS as ACTOR_KINDS,
)
from ..domain.public_events import (
    CURSOR_VERSION as CURSOR_VERSION,
)
from ..domain.public_events import (
    ERROR_CODES as ERROR_CODES,
)
from ..domain.public_events import (
    EVENT_VERSION as EVENT_VERSION,
)
from ..domain.public_events import (
    GAP_REASONS as GAP_REASONS,
)
from ..domain.public_events import (
    MAX_PUBLIC_PAGE as MAX_PUBLIC_PAGE,
)
from ..domain.public_events import (
    MAX_REFS as MAX_REFS,
)
from ..domain.public_events import (
    MAX_SCAN_ROWS as MAX_SCAN_ROWS,
)
from ..domain.public_events import (
    RETENTION_CLASSES as RETENTION_CLASSES,
)
from ..domain.public_events import (
    STATUSES as STATUSES,
)
from ..domain.public_events import (
    CursorMismatch as CursorMismatch,
)
from ..domain.public_events import (
    EventBoundaryError as EventBoundaryError,
)
from ..domain.public_events import (
    EventCorrupt as EventCorrupt,
)
from ..domain.public_events import (
    EventEnvelope as EventEnvelope,
)
from ..domain.public_events import (
    EventInvalid as EventInvalid,
)
from ..domain.public_events import (
    EventPage as EventPage,
)
from ..domain.public_events import (
    GapView as GapView,
)
from ..domain.public_events import (
    PublicEventJournal as PublicEventJournal,
)
from ..domain.public_events import (
    PublicEventView as PublicEventView,
)
from ..domain.public_events import (
    _append_event_in_transaction as _append_event_in_transaction,
)
from ..domain.public_events import (
    _assert_event_schema as _assert_event_schema,
)
from ..domain.public_events import (
    _at_epoch as _at_epoch,
)
from ..domain.public_events import (
    _cursor_body as _cursor_body,
)
from ..domain.public_events import (
    _cursor_for as _cursor_for,
)
from ..domain.public_events import (
    _decode_cursor as _decode_cursor,
)
from ..domain.public_events import (
    _encode_cursor as _encode_cursor,
)
from ..domain.public_events import (
    _entity as _entity,
)
from ..domain.public_events import (
    _event_cursor_in_transaction as _event_cursor_in_transaction,
)
from ..domain.public_events import (
    _event_stream as _event_stream,
)
from ..domain.public_events import (
    _filter as _filter,
)
from ..domain.public_events import (
    _install_event_schema as _install_event_schema,
)
from ..domain.public_events import (
    _normalize_schema_sql as _normalize_schema_sql,
)
from ..domain.public_events import (
    _object as _object,
)
from ..domain.public_events import (
    _read_events_in_transaction as _read_events_in_transaction,
)
from ..domain.public_events import (
    _timestamp as _timestamp,
)
from ..domain.public_events import (
    _unique_tuple as _unique_tuple,
)
from ..domain.refs import canonical_json


def render_sse(page):
    if type(page) is not EventPage:
        raise TypeError("Expected a public event page")
    try:
        _decode_cursor(page.next_cursor)
        for cursor in page.event_cursors:
            _decode_cursor(cursor)
    except CursorMismatch as exc:
        raise EventCorrupt("Public event page contains an invalid cursor") from exc
    if len(page.events) != len(page.event_cursors):
        raise EventCorrupt("Public event page cursor count differs")
    chunks = []
    if page.gap is not None:
        if (
            page.gap.reason not in GAP_REASONS
            or type(page.gap.from_sequence) is not int
            or page.gap.from_sequence < 1
            or type(page.gap.to_sequence) is not int
            or page.gap.to_sequence < page.gap.from_sequence
            or page.snapshot_required is not True
        ):
            raise EventCorrupt("Public event gap is invalid")
        data = canonical_json({"gap": page.gap.as_dict(), "snapshot_required": True}).decode("utf-8")
        chunks.append(f"id: {page.next_cursor}\nevent: gap\ndata: {data}\n\n")
    for event, cursor in zip(page.events, page.event_cursors, strict=True):
        data = canonical_json(event.as_dict()).decode("utf-8")
        chunks.append(f"id: {cursor}\nevent: public_event\ndata: {data}\n\n")
    return "".join(chunks).encode("utf-8")
