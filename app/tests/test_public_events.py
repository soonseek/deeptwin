import base64
from dataclasses import replace
import json
import sqlite3
from uuid import uuid4

import pytest

from app.api.session import LocalSessionAuthority, RequestDenied
from app.api.views import (
    CursorMismatch,
    EventCorrupt,
    EventInvalid,
    PublicEventJournal,
    render_sse,
)
from app.domain.refs import EntityRef, ObjectRef


class Clock:
    def __init__(self, value=1_800_000_000):
        self.value = value

    def __call__(self):
        return self.value


def authenticated_read(clock):
    authority = LocalSessionAuthority({"127.0.0.1:4193"}, clock=clock)
    launch = authority.mint_bootstrap()
    exchange = authority.exchange_bootstrap(
        launch.capability, method="POST", host="127.0.0.1:4193",
        origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
    )
    request = authority.authenticate_request(
        method="GET", host="127.0.0.1:4193", origin=None,
        sec_fetch_site="same-origin", cookie_header=exchange.cookie_pair, csrf_token=None,
    )
    return authority, request


def entity(kind):
    return EntityRef(kind, str(uuid4()), 1, "a" * 64)


def event_args(*, event_type="artifact.sealed", count=17):
    return dict(
        observed_at_utc="2027-01-15T08:00:00.000000Z",
        actor_kind="system",
        actor_ref=entity("actor"),
        event_type=event_type,
        object_refs=(ObjectRef("artifact", str(uuid4()), 1, "b" * 64),),
        correlation_id=str(uuid4()),
        causation_id=None,
        status="succeeded",
        error_code=None,
        public_metadata={"byte_count": count},
        private_evidence_refs=(entity("artifact"),),
        retention_class="core",
        policy_ref=entity("access_policy"),
    )


@pytest.fixture
def journal(tmp_path):
    clock = Clock()
    authority, request = authenticated_read(clock)
    value = PublicEventJournal(
        tmp_path / "events.sqlite3", vault_id=str(uuid4()),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    return clock, authority, request, value


def test_projection_is_an_explicit_allowlist_without_private_or_actor_refs(journal):
    _, _, request, events = journal
    envelope = events.append(**event_args())
    page = events.read(request=request, limit=10)
    assert len(page.events) == 1
    public = page.events[0].as_dict()
    assert set(public) == {
        "event_id", "sequence", "observed_at_utc", "event_type", "object_refs",
        "status", "public_metadata",
    }
    assert public["sequence"] == envelope.sequence == 1
    encoded = json.dumps(public, sort_keys=True)
    for forbidden in (
        "private_evidence_refs", "actor_ref", "policy_ref", "vault_id",
        envelope.private_evidence_refs[0].id, envelope.actor_ref.id,
    ):
        assert forbidden not in encoded


@pytest.mark.parametrize("field", [
    "api_key", "filename", "url", "prompt", "raw_error", "private_evidence_ref",
])
def test_public_metadata_rejects_private_and_freeform_canaries(journal, field):
    _, _, _, events = journal
    args = event_args()
    args["public_metadata"] = {field: "secret-canary-do-not-export"}
    with pytest.raises(EventInvalid):
        events.append(**args)


def test_sequences_and_cursor_survive_restart_and_bind_vault_stream_filter(tmp_path):
    clock = Clock()
    authority, request = authenticated_read(clock)
    path = tmp_path / "events.sqlite3"
    vault_id = str(uuid4())
    events = PublicEventJournal(
        path, vault_id=vault_id, authenticate_session=authority.authenticate_bound, clock=clock,
    )
    events.append(**event_args(count=1))
    first = events.read(request=request, event_types=("artifact.sealed",), limit=1)
    assert first.events[0].sequence == 1

    reopened = PublicEventJournal(
        path, vault_id=vault_id, authenticate_session=authority.authenticate_bound, clock=clock,
    )
    reopened.append(**event_args(count=2))
    second = reopened.read(
        request=request, after_cursor=first.next_cursor,
        event_types=("artifact.sealed",), limit=1,
    )
    assert [event.sequence for event in second.events] == [2]

    with pytest.raises(CursorMismatch):
        reopened.read(request=request, after_cursor=first.next_cursor,
                      event_types=("source.stored",), limit=1)
    other = PublicEventJournal(
        path, vault_id=str(uuid4()), authenticate_session=authority.authenticate_bound, clock=clock,
    )
    with pytest.raises(CursorMismatch):
        other.read(request=request, after_cursor=first.next_cursor,
                   event_types=("artifact.sealed",), limit=1)


def test_tampered_or_integer_only_cursor_is_rejected(journal):
    _, _, request, events = journal
    events.append(**event_args())
    cursor = events.read(request=request, limit=1).next_cursor
    raw = bytearray(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    raw[len(raw) // 2] ^= 1
    tampered = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    for value in ("1", tampered, "", "x" * 2000):
        with pytest.raises(CursorMismatch):
            events.read(request=request, after_cursor=value, limit=1)


def test_declared_generation_gap_requires_snapshot_and_does_not_cross_gap(journal):
    _, _, request, events = journal
    for count in range(1, 4):
        events.append(**event_args(count=count))
    old = events.read(request=request, limit=1)
    events.declare_gap(first_available_sequence=3, reason="storage_failed")

    resumed = events.read(request=request, after_cursor=old.next_cursor, limit=10)
    assert resumed.events == ()
    assert resumed.snapshot_required is True
    assert resumed.gap.as_dict() == {
        "reason": "storage_failed", "from_sequence": 2, "to_sequence": 2,
    }
    fresh = events.read(request=request, limit=10)
    assert [event.sequence for event in fresh.events] == [3]


def test_physical_sequence_hole_is_not_silently_skipped(journal):
    _, _, request, events = journal
    for count in range(1, 4):
        events.append(**event_args(count=count))
    first = events.read(request=request, limit=1)
    with sqlite3.connect(events.path) as db:
        db.execute("DELETE FROM api_event_envelopes WHERE vault_id=? AND sequence=2",
                   (events.vault_id,))
    resumed = events.read(request=request, after_cursor=first.next_cursor, limit=10)
    assert resumed.events == ()
    assert resumed.snapshot_required is True
    assert resumed.gap.as_dict() == {
        "reason": "missing", "from_sequence": 2, "to_sequence": 2,
    }


def test_sse_uses_bound_cursor_ids_and_only_public_json(journal):
    _, _, request, events = journal
    envelope = events.append(**event_args())
    page = events.read(request=request, limit=10)
    payload = render_sse(page)
    assert payload.startswith(b"id: ")
    assert b"event: public_event\n" in payload
    assert b"data: " in payload and payload.endswith(b"\n\n")
    assert str(envelope.sequence).encode() in payload
    for forbidden in (b"private_evidence_refs", b"actor_ref", b"policy_ref", b"vault_id"):
        assert forbidden not in payload
    event_id = payload.split(b"\n", 1)[0].removeprefix(b"id: ").decode()
    resumed = events.read(request=request, after_cursor=event_id, limit=10)
    assert resumed.events == ()


def test_mutating_a_returned_metadata_copy_cannot_turn_sse_into_a_private_channel(journal):
    _, _, request, events = journal
    events.append(**event_args())
    page = events.read(request=request, limit=10)
    page.events[0].public_metadata["api_key"] = "secret-canary-do-not-export"
    with pytest.raises(EventCorrupt):
        render_sse(page)


def test_event_read_requires_live_authenticated_get_and_bounded_page(journal):
    _, authority, request, events = journal
    events.append(**event_args())
    for limit in (0, 101, True):
        with pytest.raises(EventInvalid):
            events.read(request=request, limit=limit)
    mutation = replace(request, method="POST")
    with pytest.raises(EventInvalid):
        events.read(request=mutation, limit=1)
    authority.revoke(request.session)
    with pytest.raises(RequestDenied):
        events.read(request=request, limit=1)


def test_corrupt_envelope_fails_closed_instead_of_emitting_partial_view(journal):
    _, _, request, events = journal
    events.append(**event_args())
    with sqlite3.connect(events.path) as db:
        db.execute("UPDATE api_event_envelopes SET envelope=? WHERE vault_id=? AND sequence=1",
                   (b'{"private":"secret-canary"}', events.vault_id))
    with pytest.raises(EventCorrupt):
        events.read(request=request, limit=10)
