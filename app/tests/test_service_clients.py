"""Pure service-client authority contracts; no HTTP listener or credential is contacted."""

import json
import traceback
from uuid import uuid4

import pytest

from app.domain.events import EVENT_TYPES
from app.domain.schemas import Actor
from app.services.service_clients import (
    ServiceClientDenied,
    ServiceClientRegistry,
)


def identifier():
    return str(uuid4())


@pytest.fixture
def subject():
    clock = [1_000]
    owner_token = object()
    owner = Actor(identifier(), "human", "local_session")
    random_values = iter((b"a" * 32, b"b" * 32))
    registry = ServiceClientRegistry(
        verify_owner=lambda candidate: owner if candidate is owner_token else None,
        clock=lambda: clock[0],
        random_bytes=lambda size: next(random_values) if size == 32 else b"",
    )
    return registry, clock, owner_token, owner


def test_issue_shows_secret_once_and_retains_only_digest(subject):
    registry, _, owner_token, owner = subject
    issued = registry.issue(
        owner_token,
        client_id=identifier(),
        name="내 자동화",
        scopes=("command:work.revise", "events.read"),
        allowed_network_profile="portable_https",
        expires_at=2_000,
    )
    assert issued.secret.startswith("dt_sc_")
    assert issued.client.owner_id == owner.id
    assert issued.client.revision == 1
    snapshot = registry.snapshot(owner_token, issued.client.client_id)
    serialized = json.dumps([snapshot, registry.events], sort_keys=True)
    assert issued.secret not in serialized
    assert "credential_digest" not in snapshot
    assert registry.authenticate(
        issued.secret, network_profile="portable_https"
    ).actor.kind == "service_client"
    with pytest.raises(ServiceClientDenied):
        registry.authenticate("dt_sc_not-a-real-secret", network_profile="portable_https")


@pytest.mark.parametrize("scope", [
    "bootstrap.claim", "approval.decide", "promotion.approve", "deployment.update",
    "recovery.owner", "service_client.issue", "command:deployment.apply",
])
def test_service_client_scope_can_never_gain_human_or_deployment_authority(subject, scope):
    registry, _, owner_token, _ = subject
    with pytest.raises(ServiceClientDenied, match="scope"):
        registry.issue(
            owner_token, client_id=identifier(), name="unsafe", scopes=(scope,),
            allowed_network_profile="portable_https", expires_at=2_000,
        )
    assert registry.events[-1] == {
        "event_type": "service_client.denied",
        "public_metadata": {"reason_code": "scope"},
    }


def test_rotate_invalidates_predecessor_and_revoke_is_terminal(subject):
    registry, _, owner_token, _ = subject
    issued = registry.issue(
        owner_token, client_id=identifier(), name="headless",
        scopes=("command:work.revise",),
        allowed_network_profile="portable_https", expires_at=2_000,
    )
    rotated = registry.rotate(owner_token, issued.client.client_id)
    assert rotated.client.revision == 2
    assert rotated.secret != issued.secret
    with pytest.raises(ServiceClientDenied):
        registry.authenticate(issued.secret, network_profile="portable_https")
    assert registry.authenticate(
        rotated.secret, network_profile="portable_https"
    ).credential_revision == 2

    revoked = registry.revoke(owner_token, issued.client.client_id)
    assert revoked.state == "revoked" and revoked.revision == 3
    with pytest.raises(ServiceClientDenied):
        registry.authenticate(rotated.secret, network_profile="portable_https")
    with pytest.raises(ServiceClientDenied):
        registry.rotate(owner_token, issued.client.client_id)


def test_expiry_network_binding_and_clock_rollback_fail_closed(subject):
    registry, clock, owner_token, _ = subject
    issued = registry.issue(
        owner_token, client_id=identifier(), name="bounded",
        scopes=("snapshot.read",), allowed_network_profile="portable_https",
        expires_at=1_100,
    )
    with pytest.raises(ServiceClientDenied, match="network"):
        registry.authenticate(issued.secret, network_profile="local_loopback")
    clock[0] = 1_100
    with pytest.raises(ServiceClientDenied, match="expired"):
        registry.authenticate(issued.secret, network_profile="portable_https")
    clock[0] = 999
    with pytest.raises(ServiceClientDenied, match="clock"):
        registry.snapshot(owner_token, issued.client.client_id)


def test_service_client_expiry_has_a_short_lived_upper_bound(subject):
    registry, clock, owner_token, _ = subject
    with pytest.raises(ServiceClientDenied, match="expiry"):
        registry.issue(
            owner_token, client_id=identifier(), name="too-long",
            scopes=("events.read",), allowed_network_profile="portable_https",
            expires_at=clock[0] + 86_401,
        )
    issued = registry.issue(
        owner_token, client_id=identifier(), name="one-day",
        scopes=("events.read",), allowed_network_profile="portable_https",
        expires_at=clock[0] + 86_400,
    )
    assert issued.client.expires_at - issued.client.created_at == 86_400


def test_all_issue_validation_precedes_secret_generation_and_is_denial_logged():
    owner_token = object()
    owner = Actor(identifier(), "human", "local_session")
    random_calls = []
    registry = ServiceClientRegistry(
        verify_owner=lambda candidate: owner if candidate is owner_token else None,
        clock=lambda: 1_000,
        random_bytes=lambda size: random_calls.append(size) or b"a" * size,
    )
    invalid_name = "\ud800private-name-sentinel"
    with pytest.raises(ServiceClientDenied, match="name") as captured:
        registry.issue(
            owner_token, client_id=identifier(), name=invalid_name,
            scopes=("events.read",), allowed_network_profile="portable_https",
            expires_at=2_000,
        )
    assert random_calls == []
    current = captured.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "app.services.service_clients":
            assert "private-name-sentinel" not in repr(current.tb_frame.f_locals)
        current = current.tb_next
    assert registry.events[-1]["public_metadata"]["reason_code"] == "name"

    for changes, reason in (
        ({"expires_at": 1_000}, "expiry"),
        ({"allowed_network_profile": "ambient"}, "network"),
    ):
        arguments = {
            "client_id": identifier(), "name": "invalid", "scopes": ("events.read",),
            "allowed_network_profile": "portable_https", "expires_at": 2_000,
            **changes,
        }
        with pytest.raises(ServiceClientDenied):
            registry.issue(owner_token, **arguments)
        assert registry.events[-1]["public_metadata"]["reason_code"] == reason
    assert random_calls == []


def test_repeated_generated_secret_is_scrubbed_and_denial_logged():
    owner_token = object()
    owner = Actor(identifier(), "human", "local_session")
    registry = ServiceClientRegistry(
        verify_owner=lambda candidate: owner if candidate is owner_token else None,
        clock=lambda: 1_000, random_bytes=lambda size: b"a" * size,
    )
    registry.issue(
        owner_token, client_id=identifier(), name="first", scopes=("events.read",),
        allowed_network_profile="portable_https", expires_at=2_000,
    )
    raw = "dt_sc_" + "YWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWFhYWE"
    with pytest.raises(ServiceClientDenied, match="could not be issued") as captured:
        registry.issue(
            owner_token, client_id=identifier(), name="second", scopes=("events.read",),
            allowed_network_profile="portable_https", expires_at=2_000,
        )
    current = captured.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "app.services.service_clients":
            assert raw not in repr(current.tb_frame.f_locals)
        current = current.tb_next
    assert registry.events[-1]["public_metadata"]["reason_code"] == "credential"


def test_owner_verification_is_mandatory_for_every_mutation(subject):
    registry, _, owner_token, _ = subject
    issued = registry.issue(
        owner_token, client_id=identifier(), name="owned",
        scopes=("events.read",), allowed_network_profile="portable_https",
        expires_at=2_000,
    )
    for operation in (
        lambda: registry.issue(
            object(), client_id=identifier(), name="x", scopes=("events.read",),
            allowed_network_profile="portable_https", expires_at=2_000,
        ),
        lambda: registry.rotate(object(), issued.client.client_id),
        lambda: registry.revoke(object(), issued.client.client_id),
    ):
        with pytest.raises(ServiceClientDenied, match="owner"):
            operation()


def test_service_client_events_are_closed_and_secret_free(subject):
    registry, _, owner_token, _ = subject
    issued = registry.issue(
        owner_token, client_id=identifier(), name="audit",
        scopes=("events.read",), allowed_network_profile="portable_https",
        expires_at=2_000,
    )
    rotated = registry.rotate(owner_token, issued.client.client_id)
    registry.revoke(owner_token, rotated.client.client_id)
    assert {"service_client.created", "service_client.rotated", "service_client.revoked",
            "service_client.denied"} <= EVENT_TYPES
    assert [event["event_type"] for event in registry.events] == [
        "service_client.created", "service_client.rotated", "service_client.revoked",
    ]
    assert issued.secret not in json.dumps(registry.events)


def test_denial_traceback_frames_do_not_retain_raw_bearer(subject):
    registry, _, owner_token, _ = subject
    issued = registry.issue(
        owner_token, client_id=identifier(), name="trace",
        scopes=("events.read",), allowed_network_profile="portable_https",
        expires_at=2_000,
    )
    raw = issued.secret + "x"
    with pytest.raises(ServiceClientDenied) as captured:
        registry.authenticate(raw, network_profile="portable_https")
    frames = traceback.extract_tb(captured.value.__traceback__)
    assert frames
    current = captured.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__") == "app.services.service_clients":
            assert raw not in repr(current.tb_frame.f_locals)
        current = current.tb_next
