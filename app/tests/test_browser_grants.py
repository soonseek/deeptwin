"""T043 grants: the projection a browser grant binds, and the owner's persisted grants.

runtime.md §6: "Network GET is also outbound transmission: a grant binds both permitted
recipient and allowed source/projection categories … only an explicitly permitted
outbound projection can cross the broker. The broker inspects the actual normalized
request". Four layers, in-thread (the real-process qualification of the same rules is in
`test_browser_worker.py`, root only):

- the projection grammar (`fetch_channel`): exact entries, canonical encoding, declared
  sources compared by digest;
- the fetch service's enforcement over the real frame codec: registration, navigation,
  subresources and every redirect hop, with `projection_denied`;
- the owner's persisted grant records (`browser_grants`): create / replay / conflict /
  revoke / expiry / listing that never shows a declared value, and the owner-only routes
  (`browser-grants-v1`: session and CSRF);
- dispatch: the transport builds its grant only from the record the compiled binding
  names and the run's approved design names; a revoked or expired grant, or a run
  approved for another grant, is a `denied` attempt with nothing sent.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.tests.support.browser_grant_chain import (
    dispatch,
    grant_command,
    granted_run,
    owner_vault,
    revoke,
)
from app.tests.test_browser_worker import (  # noqa: F401 - pytest fixtures
    FakeSession,
    _code,
    _fetch,
    browser_client,
    fetch_service,
    grant,
)
from app.workers.browser_channel import BrowserChannelError, BrowserRequest
from app.workers.fetch_channel import (
    BrowserGrant,
    DataSource,
    FetchChannelError,
    GrantProjection,
    ProjectionEntry,
    carries_source_values,
    projected_url,
    projection_values,
    value_digest,
)

SEARCH = ProjectionEntry(url="https://granted.test/search", parameters=(("q", "topic"),))
LEAK = ProjectionEntry(url="https://granted.test/leak", parameters=(("q", "topic"),))
HOME = ProjectionEntry(url="https://granted.test/")
TOPIC = DataSource(source_id="topic", value_sha256=tuple(sorted({value_digest("deeptwin"),
                                                                 value_digest("공개 자료")})))


def topic_projection():
    return GrantProjection(entries=(HOME, SEARCH, LEAK), data_sources=(TOPIC,))


def topic_grant(**changes):
    return grant(recipients=("granted.test", "other.test"), projection=topic_projection(), **changes)


# --- the grammar ----------------------------------------------------------------------

def test_a_projection_admits_only_its_exact_entries_with_declared_values():
    projection = topic_projection()
    assert projection_values(projection, "https://granted.test/") == (HOME, ())
    assert projection_values(projection, "https://granted.test/search?q=deeptwin") == (SEARCH, ("deeptwin",))
    korean = projected_url(SEARCH, ("공개 자료",))
    assert korean == "https://granted.test/search?q=%EA%B3%B5%EA%B0%9C%20%EC%9E%90%EB%A3%8C"
    assert projection_values(projection, korean) == (SEARCH, ("공개 자료",))
    for refused in (
        "https://granted.test/search?q=private-diagnosis",  # undeclared value
        "https://granted.test/search",  # the parameter is missing
        "https://granted.test/search?q=",  # an empty value is not declared
        "https://granted.test/search?q=deeptwin&q=deeptwin",  # repeated
        "https://granted.test/search?q=deeptwin&x=1",  # an extra parameter
        "https://granted.test/search?Q=deeptwin",  # another name
        "https://granted.test/search?q=%EA%B3%B5%EA%B0%9C+%EC%9E%90%EB%A3%8C",  # `+` is another spelling
        "https://granted.test/search?q=%64eeptwin",  # a needless percent-encoding is another spelling
        "https://granted.test/search?q=deeptwin#x",  # a fragment
        "https://granted.test/?q=deeptwin",  # pure navigation carries no data
        "https://granted.test/private-notes",  # not an entry, though under the source
        "https://granted.test/search/deeptwin",  # the path is fixed by the entry
        "https://other.test/search?q=deeptwin",
        "http://granted.test/search?q=deeptwin",
    ):
        assert projection_values(projection, refused) is None, refused


def test_projection_objects_are_closed_and_bound_to_the_grant():
    with pytest.raises(ValueError):  # an entry is an exact URL without a query
        ProjectionEntry(url="https://granted.test/search?q=1")
    with pytest.raises(ValueError):
        ProjectionEntry(url="https://granted.test/a", parameters=(("q", "topic"), ("q", "topic")))
    with pytest.raises(ValueError):  # a parameter's source must be declared …
        GrantProjection(entries=(SEARCH,))
    with pytest.raises(ValueError):  # … and a declared source must be used
        GrantProjection(entries=(HOME,), data_sources=(TOPIC,))
    with pytest.raises(ValueError):  # digests only, sorted and unique
        DataSource(source_id="topic", value_sha256=("deeptwin",))
    with pytest.raises(ValueError):
        value_digest("")
    with pytest.raises(ValueError):  # every entry lies under a grant source
        grant(sources=("https://granted.test/docs/",), projection=topic_projection())
    value = topic_grant()
    assert BrowserGrant.from_mapping(value.as_dict()) == value
    assert value.as_dict()["projection"]["data_sources"] == [TOPIC.as_dict()]
    # the grant digest binds the projection
    assert value.digest != grant(recipients=("granted.test", "other.test")).digest
    assert carries_source_values(("deeptwin",), "https://other.test/x?v=DeepTwin")
    assert carries_source_values(("공개 자료",), "https://other.test/x?v=%EA%B3%B5%EA%B0%9C+%EC%9E%90%EB%A3%8C")
    assert not carries_source_values(("deeptwin",), "https://other.test/tracker.png")
    assert not carries_source_values((), "https://other.test/x?v=deeptwin")


# --- the fetch service's enforcement --------------------------------------------------

def test_the_fetch_service_admits_a_declared_value_and_refuses_an_undeclared_one(fetch_service):  # noqa: F811 - the imported fixture
    control = fetch_service.control
    identifier = control.register(topic_grant(), "https://granted.test/search?q=deeptwin")
    assert _fetch(fetch_service, identifier, "https://granted.test/search?q=deeptwin").status == 200
    # a navigation that is not a projection entry, or carries an undeclared value
    assert _code(fetch_service, identifier, "https://granted.test/search?q=secret") == "projection_denied"
    assert _code(fetch_service, identifier, "https://granted.test/docs/page") == "projection_denied"
    for undeclared in ("https://granted.test/search?q=secret", "https://granted.test/search?q=deeptwin+",
                       "https://granted.test/private-notes"):
        with pytest.raises(FetchChannelError) as refused:
            control.register(topic_grant(), undeclared)
        assert refused.value.code == "projection_denied"
    with pytest.raises(FetchChannelError) as outside:  # the source check still comes first
        control.register(topic_grant(), "https://other.test/")
    assert outside.value.code == "grant_denied"
    seen = [item[1] for item in fetch_service.network.seen]
    assert seen == ["https://granted.test/search?q=deeptwin"]  # nothing else reached the network
    usage = control.revoke(identifier)
    assert (usage.requests, usage.denied) == (3, 2)


def test_derived_requests_never_carry_a_source_value_to_another_recipient(fetch_service, monkeypatch):  # noqa: F811 - the imported fixture
    from app.tests.test_browser_worker import PAGES

    monkeypatch.setitem(PAGES, "/leak", (302, {"location": "https://other.test/collect?v=DeepTwin"}, b""))
    identifier = fetch_service.control.register(topic_grant(), "https://granted.test/search?q=deeptwin")
    for leaking in ("https://other.test/collect?v=deeptwin", "https://other.test/collect?v=DEEPTWIN",
                    "https://other.test/collect?v=%64eeptwin", "https://other.test/deeptwin.png"):
        assert _code(fetch_service, identifier, leaking, "subresource") == "projection_denied", leaking
    # value-free requests to the other recipient and the entry's own host carrying it pass
    assert _fetch(fetch_service, identifier, "https://other.test/tracker.png", "subresource").status == 404
    assert _fetch(fetch_service, identifier, "https://granted.test/img?v=deeptwin", "subresource").status == 404
    # a redirect hop carrying the value to another host is refused before it is sent
    assert _code(fetch_service, identifier, "https://granted.test/leak?q=deeptwin") == "projection_denied"
    reached = [item[1] for item in fetch_service.network.seen]
    assert not any("collect" in url or "deeptwin.png" in url for url in reached)
    assert "https://granted.test/leak?q=deeptwin" in reached  # the entry itself was fetched
    # a grant whose navigation carries no value tags nothing: the same subresource passes
    plain = fetch_service.control.register(topic_grant(), "https://granted.test/")
    assert _fetch(fetch_service, plain, "https://other.test/collect?v=deeptwin", "subresource").status == 404
    # … until a navigation under it carries the value: from then on it is tagged too
    assert _fetch(fetch_service, plain, "https://granted.test/search?q=deeptwin").status == 200
    assert _code(fetch_service, plain, "https://other.test/collect?v=deeptwin", "subresource") == "projection_denied"


def test_control_refuses_an_undeclared_value_before_anything_leaves(browser_client):  # noqa: F811 - the imported fixture
    with pytest.raises(BrowserChannelError) as refused:
        browser_client.client.run(BrowserRequest(op="read", url="https://granted.test/search?q=secret"),
                                  topic_grant())
    assert (refused.value.code, refused.value.sent) == ("projection_denied", False)
    assert browser_client.outcomes == [] and browser_client.fetch.network.seen == []
    value = browser_client.client.run(BrowserRequest(op="read", url="https://granted.test/search?q=deeptwin"),
                                      topic_grant())
    assert value.final_url == "https://granted.test/search?q=deeptwin"


# --- the owner's persisted grants -----------------------------------------------------

def _stamp(delta):
    return (datetime.now(UTC) + delta).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def test_an_owner_grant_is_one_immutable_record_per_command_and_never_shows_a_value(tmp_path):
    from app.domain.refs import EntityRef
    from app.services.browser_grants import (
        BrowserGrantError,
        PersistentBrowserGrants,
        grant_identity,
    )

    with owner_vault(tmp_path) as vault:
        domain = vault.app.state.domain_store
        grants = PersistentBrowserGrants(domain, vault.app.state.owner_authority)
        body = grant_command()
        view = grants.create(vault.request, body)
        assert view["grant_id"] == grant_identity(body["command_id"]) and view["state"] == "active"
        assert (view["recipients"], view["sources"], view["tools"]) == (
            ["granted.test"], ["https://granted.test/"], ["browser_navigate", "browser_read", "browser_screenshot"])
        topic = view["projection"]["data_sources"][0]
        assert topic["value_count"] == 2 and topic["value_sha256"] == list(TOPIC.value_sha256)
        record = domain.get(EntityRef.from_dict(view["ref"]))
        assert record.ref.kind == "grant" and b"deeptwin" not in record.body_bytes  # digests only
        assert "공개 자료".encode() not in record.body_bytes
        assert grants.create(vault.request, body) == view  # exact replay
        with pytest.raises(BrowserGrantError) as conflict:
            grants.create(vault.request, {**body, "label": "다른 이름"})
        assert conflict.value.code == "conflict"
        for broken in ({"tools": ["browser_click"]}, {"tools": []}, {"expires_at_utc": _stamp(timedelta(days=-1))},
                       {"expires_at_utc": _stamp(timedelta(days=91))}, {"recipients": ["other.test"]},
                       {"data_sources": [{"source_id": "topic", "values": []}]},
                       {"data_sources": [{"source_id": "topic", "values": ["a", "a"]}]},
                       {"entries": [{"url": "https://granted.test/?x=1", "parameters": []}], "data_sources": []},
                       {"label": " padded"}):
            with pytest.raises(BrowserGrantError) as invalid:
                grants.create(vault.request, grant_command(**broken))
            assert invalid.value.code == "invalid_input", broken
        listed = grants.list(vault.request)["grants"]
        assert [item["grant_id"] for item in listed] == [view["grant_id"]]
        revoked = revoke(vault, SimpleGranted(grants, view))
        assert revoked["state"] == "revoked" and revoked["revocation"]["revoked_at_utc"]
        with pytest.raises(BrowserGrantError) as gone:
            grants.for_dispatch(EntityRef.from_dict(view["ref"]), tool_id="browser_read", version="1.0.0")
        assert gone.value.code == "revoked"
        with pytest.raises(BrowserGrantError) as again:  # a revocation is not undone or repeated differently
            grants.revoke(vault.request, view["grant_id"], {"schema_version": "browser-grant-revocation-command-v1",
                                                            "command_id": str(uuid4())})
        assert again.value.code == "conflict"


class SimpleGranted:
    def __init__(self, grants, view):
        from app.domain.refs import EntityRef

        self.grants, self.grant_ref = grants, EntityRef.from_dict(view["ref"])


def test_expiry_tools_and_foreign_records_refuse_at_dispatch(tmp_path):
    from app.domain.refs import EntityRef
    from app.services.browser_grants import BrowserGrantError, PersistentBrowserGrants
    from app.tests.test_runtime_budget_dispatch import immutable

    with owner_vault(tmp_path) as vault:
        domain, authority = vault.app.state.domain_store, vault.app.state.owner_authority
        clock = [datetime.now(UTC)]
        grants = PersistentBrowserGrants(domain, authority, clock=lambda: clock[0])
        view = grants.create(vault.request, grant_command(tools=["browser_read"], expires_at_utc=_stamp(
            timedelta(hours=1))))
        ref = EntityRef.from_dict(view["ref"])
        current = grants.for_dispatch(ref, tool_id="browser_read", version="1.0.0")
        assert current.grant.ttl_ms == 60_000 and current.ref == ref
        with pytest.raises(BrowserGrantError) as tool:
            grants.for_dispatch(ref, tool_id="browser_screenshot", version="1.0.0")
        assert tool.value.code == "tool_not_granted"
        clock[0] += timedelta(minutes=59, seconds=30)  # the session never outlives the grant
        assert grants.for_dispatch(ref, tool_id="browser_read", version="1.0.0").grant.ttl_ms <= 30_000
        clock[0] += timedelta(minutes=1)
        with pytest.raises(BrowserGrantError) as expired:
            grants.for_dispatch(ref, tool_id="browser_read", version="1.0.0")
        assert expired.value.code == "expired"
        assert grants.list(vault.request)["grants"][0]["state"] == "expired"
        # a `grant` record the owner did not author through the command is no browser grant
        foreign = immutable(domain, domain.roots(), "grant")
        with pytest.raises(BrowserGrantError) as unavailable:
            grants.for_dispatch(foreign, tool_id="browser_read", version="1.0.0")
        assert unavailable.value.code == "unavailable"
        assert [item["grant_id"] for item in grants.list(vault.request)["grants"]] == [view["grant_id"]]


# --- the owner routes -----------------------------------------------------------------

def test_the_routes_are_owner_only_and_csrf_bound(tmp_path):
    from app.tests.test_runs_api import owner_app
    from app.tests.test_web_owner_integration import headers

    with owner_app(tmp_path, None) as subject:
        path = subject.profile.base_path + "api/v1/browser-grants"
        client, profile = subject.client, subject.profile
        body = grant_command()
        assert client.post(path, headers=headers(profile), json=body).status_code == 403  # no CSRF token
        assert client.post(path, headers={"Origin": "https://evil.test", "X-DeepTwin-CSRF": subject.csrf},
                           json=body).status_code == 403
        created = client.post(path, headers=headers(profile, subject.csrf), json=body)
        assert created.status_code == 201, created.text
        grant_id = created.json()["grant_id"]
        listed = client.get(path)
        assert listed.status_code == 200 and listed.headers["cache-control"] == "no-store"
        assert [item["grant_id"] for item in listed.json()["grants"]] == [grant_id]
        assert "deeptwin" not in listed.text  # a declared value is never shown back
        assert client.get(path + "?x=1").status_code == 400
        bad = client.post(path, headers=headers(profile, subject.csrf), json={**body, "extra": 1})
        assert bad.status_code == 400 and bad.json()["code"] == "invalid_input"
        revoke_path = f"{path}/{grant_id}/revoke"
        command = {"schema_version": "browser-grant-revocation-command-v1", "command_id": str(uuid4())}
        assert client.post(revoke_path, headers=headers(profile), json=command).status_code == 403
        revoked = client.post(revoke_path, headers=headers(profile, subject.csrf), json=command)
        assert revoked.status_code == 200 and revoked.json()["state"] == "revoked"
        missing = client.post(f"{path}/{uuid4()}/revoke", headers=headers(profile, subject.csrf), json=command)
        assert missing.status_code == 404
        events = client.get(subject.profile.base_path + "api/v1/events?event_type=approval.decided").json()
        decisions = [item["public_metadata"]["decision"] for item in events["events"]]
        assert decisions[-2:] == ["approved", "revoked"]
        # without the owner's session cookie nothing is read or created
        client.cookies.clear()
        assert client.get(path).status_code == 401
        assert client.post(path, headers=headers(profile, subject.csrf), json=grant_command()).status_code in (
            401, 403)


# --- dispatch -------------------------------------------------------------------------

def _transport(granted, client, url="https://granted.test/", grants=None):
    from app.runtime.browser_attempt_transport import BrowserAttemptTransport

    subject = granted.subject
    return BrowserAttemptTransport.build(
        domain_store=subject.domain, ledger=subject.ledger, compiled=subject.compiled, node_id="writer",
        binding_id="source-read", client=client, request=BrowserRequest(op="read", url=url, max_text_bytes=4_096),
        grants=grants or granted.grants)


def _denied_before_sending(granted, browser_client):  # noqa: F811 - the imported fixture
    from app.runtime import node_attempts as na
    from app.runtime.scheduler import SchedulerError

    attempt_id = na.attempt_identity(granted.run.run_id, "writer", 0, 0)
    attempt = granted.subject.ledger.get_attempt(attempt_id)
    assert (attempt["terminal_outcome"], attempt["usage_finality"]) == ("denied", "final")
    assert [item["state"] for item in granted.subject.ledger.tool_calls_for_attempt(attempt_id)] == ["failed"]
    assert browser_client.outcomes == [] and browser_client.fetch.network.seen == []
    assert browser_client.fetch.service._grants == {}
    return SchedulerError


def test_a_grant_revoked_after_the_build_is_refused_at_dispatch(tmp_path, browser_client):  # noqa: F811 - the imported fixture
    from app.runtime.scheduler import SchedulerError

    with owner_vault(tmp_path) as vault:
        granted = granted_run(vault)
        transport = _transport(granted, browser_client.client)
        revoke(vault, granted)
        with pytest.raises(SchedulerError, match="node_failed:writer"):
            dispatch(granted, transport)
        _denied_before_sending(granted, browser_client)


def test_a_grant_expired_after_the_build_is_refused_at_dispatch(tmp_path, browser_client):  # noqa: F811 - the imported fixture
    from app.runtime.scheduler import SchedulerError
    from app.services.browser_grants import PersistentBrowserGrants

    with owner_vault(tmp_path) as vault:
        granted = granted_run(vault, command=grant_command(expires_at_utc=_stamp(timedelta(hours=1))))
        clock = [datetime.now(UTC)]
        grants = PersistentBrowserGrants(granted.subject.domain, vault.app.state.owner_authority,
                                         clock=lambda: clock[0])
        transport = _transport(granted, browser_client.client, grants=grants)
        clock[0] += timedelta(hours=2)
        with pytest.raises(SchedulerError, match="node_failed:writer"):
            dispatch(granted, transport)
        _denied_before_sending(granted, browser_client)


def test_a_run_approved_for_another_grant_is_refused_at_dispatch(tmp_path, browser_client):  # noqa: F811 - the imported fixture
    from app.domain.refs import EntityRef
    from app.runtime.scheduler import SchedulerError
    from app.services.browser_grants import PersistentBrowserGrants

    with owner_vault(tmp_path) as vault:
        other = PersistentBrowserGrants(vault.app.state.domain_store, vault.app.state.owner_authority).create(
            vault.request, grant_command())
        # the owner's design approval names the other grant; the node's binding names this one
        granted = granted_run(vault, approved=EntityRef.from_dict(other["ref"]))
        transport = _transport(granted, browser_client.client)
        with pytest.raises(SchedulerError, match="node_failed:writer"):
            dispatch(granted, transport)
        _denied_before_sending(granted, browser_client)


def test_an_environment_without_an_approved_design_has_no_tool_permissions(tmp_path):
    from app.services.browser_grants import BrowserGrantError, approved_tool_permissions
    from app.tests.test_runtime_budget_dispatch import immutable

    with owner_vault(tmp_path) as vault:
        domain = vault.app.state.domain_store
        granted = granted_run(vault)
        assert approved_tool_permissions(domain, granted.environment) == granted.grant_ref
        with pytest.raises(BrowserGrantError) as refused:
            approved_tool_permissions(domain, immutable(domain, domain.roots(), "environment"))
        assert refused.value.code == "access_denied"


def test_a_projection_refusal_at_dispatch_is_a_denied_attempt(tmp_path, browser_client, monkeypatch):  # noqa: F811 - the imported fixture
    from app.runtime import node_attempts as na
    from app.runtime.scheduler import SchedulerError
    from app.tests.test_browser_worker import PAGES

    monkeypatch.setitem(PAGES, "/search", (302, {"location": "https://other.test/c?v=deeptwin"}, b""))
    with owner_vault(tmp_path) as vault:
        granted = granted_run(vault, command=grant_command(recipients=["granted.test", "other.test"]))
        transport = _transport(granted, browser_client.client, url="https://granted.test/search?q=deeptwin")
        with pytest.raises(SchedulerError, match="node_failed:writer"):
            dispatch(granted, transport)
        attempt = granted.subject.ledger.get_attempt(na.attempt_identity(granted.run.run_id, "writer", 0, 0))
        assert (attempt["terminal_outcome"], attempt["usage_finality"]) == ("denied", "final")
        assert not any("other.test" in item[1] for item in browser_client.fetch.network.seen)
