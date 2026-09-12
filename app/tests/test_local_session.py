from dataclasses import replace
import sqlite3
from threading import Barrier, Lock, Thread
from uuid import uuid4

import pytest

from app.api.commands import (
    ArgField,
    CommandConflict,
    CommandDefinition,
    CommandEnvelope,
    CommandInvalid,
    CommandJournal,
    CommandOutcomeUnknown,
    CommandRegistry,
)
from app.api.session import (
    AuthenticatedSession,
    BootstrapReplay,
    BootstrapUnavailable,
    LocalSessionAuthority,
    RequestDenied,
    parse_request_headers,
)


class Clock:
    def __init__(self, value=1_800_000_000):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture
def boundary():
    clock = Clock()
    authority = LocalSessionAuthority(
        {"127.0.0.1:4193", "localhost:4193"}, clock=clock,
        session_ttl_seconds=300, max_bootstrap_attempts=8,
    )
    launch = authority.mint_bootstrap(ttl_seconds=60)
    exchange = authority.exchange_bootstrap(
        launch.capability,
        method="POST",
        host="127.0.0.1:4193",
        origin="http://127.0.0.1:4193",
        sec_fetch_site="same-origin",
    )
    return clock, authority, launch, exchange


def get_request(authority, exchange):
    return authority.authenticate_request(
        method="GET",
        host="127.0.0.1:4193",
        origin=None,
        sec_fetch_site="same-origin",
        cookie_header=exchange.cookie_pair,
        csrf_token=None,
    )


def post_request(authority, exchange):
    return authority.authenticate_request(
        method="POST",
        host="127.0.0.1:4193",
        origin="http://127.0.0.1:4193",
        sec_fetch_site="same-origin",
        cookie_header=exchange.cookie_pair,
        csrf_token=exchange.csrf_token,
    )


def test_page_csrf_tokens_are_multi_tab_safe_and_fifo_bounded(boundary):
    _, authority, _, exchange = boundary
    authenticated_get = get_request(authority, exchange)
    page_tokens = [authority.rotate_csrf(authenticated_get) for _ in range(8)]

    # The bootstrap page plus eight refreshed pages exceed the bounded FIFO, so
    # only the oldest bootstrap token is evicted and existing recent tabs work.
    with pytest.raises(RequestDenied):
        post_request(authority, exchange)
    for token in page_tokens:
        request = authority.authenticate_request(
            method="POST", host="127.0.0.1:4193",
            origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
            cookie_header=exchange.cookie_pair, csrf_token=token,
        )
        assert request.csrf_verified is True


def test_bootstrap_is_one_use_and_replay_revokes_the_issued_session(boundary):
    _, authority, launch, exchange = boundary
    assert len(launch.capability) >= 43
    assert exchange.cookie_header.startswith("deeptwin_local_session=")
    assert "; HttpOnly" in exchange.cookie_header
    assert "; SameSite=Strict" in exchange.cookie_header
    assert "; Path=/" in exchange.cookie_header
    assert "Domain=" not in exchange.cookie_header
    assert get_request(authority, exchange).session.actor.kind == "human"

    with pytest.raises(BootstrapReplay):
        authority.exchange_bootstrap(
            launch.capability,
            method="POST",
            host="127.0.0.1:4193",
            origin="http://127.0.0.1:4193",
            sec_fetch_site="same-origin",
        )
    with pytest.raises(RequestDenied):
        get_request(authority, exchange)


def test_replay_after_launch_capability_expiry_still_revokes_issued_session():
    clock = Clock()
    authority = LocalSessionAuthority(
        {"127.0.0.1:4193"}, clock=clock, session_ttl_seconds=300,
    )
    launch = authority.mint_bootstrap(ttl_seconds=1)
    exchange = authority.exchange_bootstrap(
        launch.capability, method="POST", host="127.0.0.1:4193",
        origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
    )
    clock.value += 2
    with pytest.raises(BootstrapReplay):
        authority.exchange_bootstrap(
            launch.capability, method="POST", host="127.0.0.1:4193",
            origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
        )
    with pytest.raises(RequestDenied):
        get_request(authority, exchange)


def test_bootstrap_is_short_lived_bounded_and_post_only():
    clock = Clock()
    authority = LocalSessionAuthority(
        {"127.0.0.1:4193"}, clock=clock, max_bootstrap_attempts=2,
    )
    with pytest.raises(ValueError):
        authority.mint_bootstrap(ttl_seconds=61)
    launch = authority.mint_bootstrap(ttl_seconds=2)
    with pytest.raises(RequestDenied):
        authority.exchange_bootstrap(
            launch.capability, method="GET", host="127.0.0.1:4193",
            origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
        )
    clock.value += 3
    with pytest.raises(BootstrapUnavailable):
        authority.exchange_bootstrap(
            launch.capability, method="POST", host="127.0.0.1:4193",
            origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
        )

    fresh = authority.mint_bootstrap()
    for token in ("not-a-capability", "also-not-a-capability"):
        with pytest.raises(BootstrapUnavailable):
            authority.exchange_bootstrap(
                token, method="POST", host="127.0.0.1:4193",
                origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
            )
    with pytest.raises(BootstrapUnavailable):
        authority.exchange_bootstrap(
            fresh.capability, method="POST", host="127.0.0.1:4193",
            origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
        )


@pytest.mark.parametrize("host", [
    "attacker.example", "127.0.0.1:4194", "user@127.0.0.1:4193",
    "127.0.0.1:4193,attacker", "127.0.0.1:4193/path", "127.0.0.1.",
    "2130706433:4193", "127.1:4193", "[::ffff:127.0.0.1]:4193",
])
def test_ambiguous_or_nonexact_host_is_rejected(boundary, host):
    _, authority, _, exchange = boundary
    with pytest.raises(RequestDenied):
        authority.authenticate_request(
            method="GET", host=host, origin=None, sec_fetch_site="same-origin",
            cookie_header=exchange.cookie_pair, csrf_token=None,
        )


@pytest.mark.parametrize("origin", [
    None, "null", "https://127.0.0.1:4193", "http://localhost:4193",
    "http://127.0.0.1:4193/", "http://user@127.0.0.1:4193",
    "http://127.0.0.1:4193?x=1",
])
def test_mutation_requires_the_session_bound_exact_origin(boundary, origin):
    _, authority, _, exchange = boundary
    with pytest.raises(RequestDenied):
        authority.authenticate_request(
            method="POST", host="127.0.0.1:4193", origin=origin,
            sec_fetch_site="same-origin", cookie_header=exchange.cookie_pair,
            csrf_token=exchange.csrf_token,
        )


@pytest.mark.parametrize("site", [None, "none", "same-site", "cross-site"])
def test_mutation_requires_same_origin_fetch_metadata(boundary, site):
    _, authority, _, exchange = boundary
    with pytest.raises(RequestDenied):
        authority.authenticate_request(
            method="POST", host="127.0.0.1:4193",
            origin="http://127.0.0.1:4193", sec_fetch_site=site,
            cookie_header=exchange.cookie_pair, csrf_token=exchange.csrf_token,
        )


def test_session_csrf_cookie_and_expiry_fail_closed(boundary):
    clock, authority, _, exchange = boundary
    for cookie, csrf in [
        (None, exchange.csrf_token),
        ("deeptwin_local_session=wrong", exchange.csrf_token),
        (exchange.cookie_pair + "; deeptwin_local_session=duplicate", exchange.csrf_token),
        (exchange.cookie_pair, None),
        (exchange.cookie_pair, "wrong"),
    ]:
        with pytest.raises(RequestDenied):
            authority.authenticate_request(
                method="POST", host="127.0.0.1:4193",
                origin="http://127.0.0.1:4193", sec_fetch_site="same-origin",
                cookie_header=cookie, csrf_token=csrf,
            )
    clock.value += 301
    with pytest.raises(RequestDenied):
        get_request(authority, exchange)


def test_raw_http_security_headers_are_ascii_singletons_not_last_value_wins(boundary):
    _, _, _, exchange = boundary
    fields = parse_request_headers([
        (b"host", b"127.0.0.1:4193"),
        (b"origin", b"http://127.0.0.1:4193"),
        (b"sec-fetch-site", b"same-origin"),
        (b"cookie", exchange.cookie_pair.encode("ascii")),
        (b"x-csrf-token", exchange.csrf_token.encode("ascii")),
    ])
    assert fields.host == "127.0.0.1:4193"
    assert fields.origin == "http://127.0.0.1:4193"
    assert fields.cookie_header == exchange.cookie_pair

    for name, first, second in [
        (b"host", b"127.0.0.1:4193", b"attacker.example"),
        (b"origin", b"http://127.0.0.1:4193", b"null"),
        (b"sec-fetch-site", b"same-origin", b"cross-site"),
        (b"cookie", exchange.cookie_pair.encode("ascii"), b"x=y"),
        (b"x-csrf-token", exchange.csrf_token.encode("ascii"), b"wrong"),
    ]:
        headers = [(b"host", b"127.0.0.1:4193"), (name, first), (name, second)]
        if name == b"host":
            headers = [(name, first), (name, second)]
        with pytest.raises(RequestDenied):
            parse_request_headers(headers)
    with pytest.raises(RequestDenied):
        parse_request_headers([(b"host", b"127.0.0.1:4193\xff")])


def command_registry():
    return CommandRegistry((
        CommandDefinition(
            "work.update", target_kind="work", revision="required", target_hash="forbidden",
            arguments=(ArgField("text", "text", max_bytes=100),),
        ),
        CommandDefinition(
            "run.cancel", target_kind="run", revision="required", target_hash="required",
            arguments=(ArgField("reason", "enum", values=("human_stop", "safety_stop")),),
        ),
    ))


def command_payload(command_id=None, *, text="new text"):
    return {
        "schema_version": "command-v1",
        "command_id": command_id or str(uuid4()),
        "command_type": "work.update",
        "target": {"kind": "work", "id": str(uuid4())},
        "expected_revision": 3,
        "target_hash": None,
        "args": {"text": text},
    }


def result(envelope):
    return {
        "state": "completed",
        "object_ref": envelope.target.as_dict(),
        "revision": envelope.expected_revision + 1,
        "event_cursor": "opaque-cursor",
        "links": {"self": "/api/v1/works/" + envelope.target.id},
    }


def test_command_envelope_is_exact_typed_and_canonical():
    registry = command_registry()
    payload = command_payload()
    envelope = CommandEnvelope.from_mapping(payload, registry)
    assert envelope.as_dict() == payload
    assert CommandEnvelope.from_bytes(envelope.body_bytes, registry) == envelope

    for changed in (
        {**payload, "extra": True},
        {**payload, "expected_revision": True},
        {**payload, "command_type": "unknown.command"},
        {**payload, "args": {"text": "x", "hidden": "value"}},
        {**payload, "target": {**payload["target"], "content_hash": "0" * 64}},
    ):
        with pytest.raises(CommandInvalid):
            CommandEnvelope.from_mapping(changed, registry)
    with pytest.raises(CommandInvalid):
        CommandEnvelope.from_bytes(b'{"schema_version": "command-v1"}', registry)


def test_identical_duplicate_is_returned_without_running_handler_again(tmp_path, boundary):
    clock, authority, _, exchange = boundary
    vault_id = str(uuid4())
    path = tmp_path / "intake.sqlite3"
    journal = CommandJournal(
        path, vault_id=vault_id, registry=command_registry(),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    request = post_request(authority, exchange)
    payload = command_payload()
    calls = []

    first = journal.execute(payload, request=request, handler=lambda env: calls.append(env) or result(env))
    duplicate = journal.execute(payload, request=request, handler=lambda env: pytest.fail("duplicate dispatched"))
    reopened = CommandJournal(
        path, vault_id=vault_id, registry=command_registry(),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    after_restart = reopened.execute(
        payload, request=request, handler=lambda env: pytest.fail("restart duplicate dispatched"),
    )
    assert first == duplicate == after_restart
    assert first["command_id"] == payload["command_id"]
    assert len(calls) == 1


def test_same_command_id_with_changed_payload_conflicts_before_handler(tmp_path, boundary):
    clock, authority, _, exchange = boundary
    journal = CommandJournal(
        tmp_path / "commands.sqlite3", vault_id=str(uuid4()), registry=command_registry(),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    request = post_request(authority, exchange)
    payload = command_payload()
    journal.execute(payload, request=request, handler=result)
    calls = []
    with pytest.raises(CommandConflict):
        journal.execute(
            command_payload(payload["command_id"], text="different"), request=request,
            handler=lambda env: calls.append(env) or result(env),
        )
    assert calls == []


def test_get_head_and_forged_sessions_cannot_dispatch(tmp_path, boundary):
    clock, authority, _, exchange = boundary
    journal = CommandJournal(
        tmp_path / "commands.sqlite3", vault_id=str(uuid4()), registry=command_registry(),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    calls = []
    for request in (get_request(authority, exchange),):
        with pytest.raises(CommandInvalid):
            journal.execute(command_payload(), request=request,
                            handler=lambda env: calls.append(env) or result(env))
    valid = post_request(authority, exchange)
    forged_session = AuthenticatedSession(
        valid.session.session_id, valid.session.actor, valid.session.expires_at,
    )
    forged = replace(valid, session=forged_session)
    with pytest.raises(RequestDenied):
        journal.execute(command_payload(), request=forged,
                        handler=lambda env: calls.append(env) or result(env))
    assert calls == []


def test_handler_uncertainty_is_durable_and_never_auto_retried(tmp_path, boundary):
    clock, authority, _, exchange = boundary
    path = tmp_path / "commands.sqlite3"
    vault_id = str(uuid4())
    journal = CommandJournal(
        path, vault_id=vault_id, registry=command_registry(),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    request = post_request(authority, exchange)
    payload = command_payload()
    calls = []

    def uncertain(envelope):
        calls.append(envelope)
        raise RuntimeError("private provider detail")

    with pytest.raises(CommandOutcomeUnknown):
        journal.execute(payload, request=request, handler=uncertain)
    reopened = CommandJournal(
        path, vault_id=vault_id, registry=command_registry(),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    with pytest.raises(CommandOutcomeUnknown):
        reopened.execute(payload, request=request, handler=uncertain)
    assert len(calls) == 1
    with sqlite3.connect(path) as db:
        row = db.execute("SELECT state,error_code FROM api_commands").fetchone()
        assert row == ("outcome_unknown", "handler_outcome_unknown")
        assert "private provider detail" not in " ".join(str(value) for value in row)


def test_concurrent_duplicate_has_one_handler_owner(tmp_path, boundary):
    clock, authority, _, exchange = boundary
    journal = CommandJournal(
        tmp_path / "commands.sqlite3", vault_id=str(uuid4()), registry=command_registry(),
        authenticate_session=authority.authenticate_bound, clock=clock,
    )
    request = post_request(authority, exchange)
    payload = command_payload()
    gate = Barrier(2)
    release = Barrier(2)
    lock = Lock()
    calls = []
    outcomes = []

    def handler(envelope):
        with lock:
            calls.append(envelope)
        gate.wait(timeout=3)
        release.wait(timeout=3)
        return result(envelope)

    def owner():
        outcomes.append(journal.execute(payload, request=request, handler=handler))

    thread = Thread(target=owner)
    thread.start()
    gate.wait(timeout=3)
    with pytest.raises(CommandOutcomeUnknown):
        journal.execute(payload, request=request,
                        handler=lambda env: pytest.fail("parallel duplicate dispatched"))
    release.wait(timeout=3)
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert len(calls) == 1 and len(outcomes) == 1
