"""Strict TLS bearer authentication and independent bounded rate buckets."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, BrokenBarrierError, Lock
from uuid import uuid4

import pytest

from app.domain.schemas import Actor
from app.services.service_client_auth import (
    IndependentTokenBuckets,
    ServiceClientAuthDenied,
    ServiceClientAuthenticator,
)
from app.services.service_clients import ServiceClientDenied, ServiceClientPrincipal

SECRET = "dt_sc_" + "A" * 43


class Registry:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.client_id = str(uuid4())

    def authenticate(self, secret, *, network_profile):
        self.calls.append((secret, network_profile))
        if self.fail:
            raise ServiceClientDenied("denied")
        return ServiceClientPrincipal(
            client_id=self.client_id,
            actor=Actor(str(uuid4()), "service_client", "service_credential"),
            scopes=("command:work.revise", "events.read"),
            allowed_network_profile=network_profile,
            expires_at=2_000,
            credential_revision=3,
        )


def headers(value=SECRET, *, cookie=False):
    result = [(b"authorization", f"Bearer {value}".encode("ascii"))]
    if cookie:
        result.append((b"cookie", b"browser=must-not-fallback"))
    return result


def authenticator(*, capacity=5, max_keys=32):
    now = [1_000]
    registry = Registry()
    limiter = IndependentTokenBuckets(
        clock_ms=lambda: now[0],
        capacity=capacity,
        refill_interval_ms=6_000,
        max_keys_per_dimension=max_keys,
        idle_ttl_ms=60_000,
    )
    return ServiceClientAuthenticator(registry=registry, limiter=limiter), registry, now, limiter


def test_exact_single_tls_bearer_authenticates_and_authorizes_scope():
    subject, registry, _, _ = authenticator()
    authorized = subject.authorize(
        headers(), tls=True, network_profile="portable_https",
        source_key="peer:203.0.113.4", route_id="work.revise",
        required_scope="command:work.revise",
    )
    assert authorized.principal.credential_revision == 3
    assert authorized.route_id == "work.revise"
    assert registry.calls == [(SECRET, "portable_https")]


@pytest.mark.parametrize(
    ("raw_headers", "tls"),
    (
        (headers(), False),
        ([(b"authorization", SECRET.encode("ascii"))], True),
        ([(b"authorization", f"bearer {SECRET}".encode("ascii"))], True),
        ([(b"authorization", f"Bearer  {SECRET}".encode("ascii"))], True),
        ([(b"authorization", f"Bearer {SECRET},x".encode("ascii"))], True),
        (headers() + headers(), True),
        (headers(cookie=True), True),
    ),
)
def test_tls_scheme_duplicate_comma_cookie_and_browser_fallback_fail_before_registry(
    raw_headers, tls,
):
    subject, registry, _, _ = authenticator()
    with pytest.raises(ServiceClientAuthDenied):
        subject.authorize(
            raw_headers, tls=tls, network_profile="portable_https",
            source_key="peer:203.0.113.4", route_id="work.revise",
            required_scope="command:work.revise",
        )
    assert registry.calls == []


def test_network_profile_is_bound_by_registry_and_missing_scope_is_denied():
    subject, registry, _, _ = authenticator()
    registry.fail = True
    with pytest.raises(ServiceClientAuthDenied):
        subject.authorize(
            headers(), tls=True, network_profile="dedicated_https",
            source_key="peer:203.0.113.4", route_id="work.revise",
            required_scope="command:work.revise",
        )
    assert registry.calls == [(SECRET, "dedicated_https")]

    registry.fail = False
    with pytest.raises(ServiceClientAuthDenied):
        subject.authorize(
            headers(), tls=True, network_profile="portable_https",
            source_key="peer:203.0.113.4", route_id="artifact.delete",
            required_scope="command:artifact.delete",
        )


def test_invalid_credentials_consume_the_same_source_and_route_rate_budget():
    subject, registry, _, limiter = authenticator(capacity=2)
    registry.fail = True
    arguments = {
        "tls": True,
        "network_profile": "portable_https",
        "source_key": "peer:one",
        "route_id": "work.revise",
        "required_scope": "command:work.revise",
    }
    for _ in range(2):
        with pytest.raises(ServiceClientAuthDenied, match="authentication"):
            subject.authorize(headers(), **arguments)
    with pytest.raises(ServiceClientAuthDenied, match="rate"):
        subject.authorize(headers(), **arguments)
    assert len(registry.calls) == 2
    assert limiter.snapshot_counts() == {"client": 1, "route": 1, "source": 1}


def test_source_route_and_credential_buckets_are_consumed_atomically_and_refill():
    subject, registry, now, limiter = authenticator(capacity=2)
    arguments = {
        "tls": True,
        "network_profile": "portable_https",
        "source_key": "peer:one",
        "route_id": "work.revise",
        "required_scope": "command:work.revise",
    }
    subject.authorize(headers(), **arguments)
    subject.authorize(headers(), **arguments)
    with pytest.raises(ServiceClientAuthDenied, match="rate"):
        subject.authorize(headers(), **arguments)
    assert len(registry.calls) == 2
    assert limiter.snapshot_counts() == {"client": 1, "route": 1, "source": 1}

    now[0] += 6_000
    subject.authorize(headers(), **arguments)
    assert len(registry.calls) == 3


def test_each_dimension_has_a_bounded_map_and_capacity_refuses_churn():
    subject, registry, _, limiter = authenticator(max_keys=1)
    subject.authorize(
        headers(), tls=True, network_profile="portable_https", source_key="peer:one",
        route_id="work.revise", required_scope="command:work.revise",
    )
    with pytest.raises(ServiceClientAuthDenied, match="rate"):
        subject.authorize(
            headers("dt_sc_" + "B" * 42 + "E"), tls=True,
            network_profile="portable_https", source_key="peer:two",
            route_id="work.other", required_scope="command:work.revise",
        )
    assert len(registry.calls) == 1
    assert limiter.snapshot_counts() == {"client": 1, "route": 1, "source": 1}


def test_client_map_refusal_does_not_partially_consume_source_or_route_tokens():
    subject, registry, _, _ = authenticator(capacity=2, max_keys=1)
    arguments = {
        "tls": True,
        "network_profile": "portable_https",
        "source_key": "peer:one",
        "route_id": "work.revise",
        "required_scope": "command:work.revise",
    }
    first_id = registry.client_id
    subject.authorize(headers(), **arguments)
    registry.client_id = str(uuid4())
    with pytest.raises(ServiceClientAuthDenied, match="rate"):
        subject.authorize(headers(), **arguments)
    registry.client_id = first_id
    subject.authorize(headers(), **arguments)


def test_concurrent_rate_consumption_cannot_exceed_capacity():
    subject, registry, _, _ = authenticator(capacity=3)

    def attempt(_index):
        try:
            subject.authorize(
                headers(), tls=True, network_profile="portable_https",
                source_key="peer:one", route_id="work.revise",
                required_scope="command:work.revise",
            )
            return True
        except ServiceClientAuthDenied:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(20)))
    assert outcomes.count(True) == 3
    # Source and route capacity is reserved before the expensive registry call.
    assert len(registry.calls) == 3


def test_capacity_is_reserved_before_concurrent_registry_authentication():
    subject, registry, now, _ = authenticator(capacity=1)
    original = registry.authenticate
    rendezvous = Barrier(2)
    calls_lock = Lock()

    def blocking_authenticate(secret, *, network_profile):
        with calls_lock:
            registry.calls.append((secret, network_profile))
        try:
            rendezvous.wait(timeout=0.2)
        except BrokenBarrierError:
            raise ServiceClientDenied("blocked") from None
        return original(secret, network_profile=network_profile)

    registry.calls = []
    registry.authenticate = blocking_authenticate
    arguments = {
        "tls": True,
        "network_profile": "portable_https",
        "source_key": "peer:one",
        "route_id": "work.revise",
        "required_scope": "command:work.revise",
    }

    def attempt(_index):
        try:
            subject.authorize(headers(), **arguments)
            return True
        except ServiceClientAuthDenied:
            return False

    with ThreadPoolExecutor(max_workers=6) as pool:
        outcomes = list(pool.map(attempt, range(6)))
    assert outcomes == [False] * 6
    assert len(registry.calls) == 1

    # The failed registry attempt is finalized as a charged request, not leaked or bypassed.
    with pytest.raises(ServiceClientAuthDenied, match="rate"):
        subject.authorize(headers(), **arguments)
    assert len(registry.calls) == 1

    now[0] += 6_000
    registry.authenticate = original
    subject.authorize(headers(), **arguments)


def test_malformed_registry_principal_is_charged_without_leaking_a_reservation():
    subject, registry, now, _ = authenticator(capacity=1)
    calls = []

    def malformed_principal(secret, *, network_profile):
        calls.append((secret, network_profile))
        return ServiceClientPrincipal(
            client_id="not a rate key\n",
            actor=Actor(str(uuid4()), "service_client", "service_credential"),
            scopes=("command:work.revise",),
            allowed_network_profile=network_profile,
            expires_at=2_000,
            credential_revision=1,
        )

    registry.authenticate = malformed_principal
    arguments = {
        "tls": True,
        "network_profile": "portable_https",
        "source_key": "peer:one",
        "route_id": "work.revise",
        "required_scope": "command:work.revise",
    }
    with pytest.raises(ServiceClientAuthDenied, match="authentication"):
        subject.authorize(headers(), **arguments)
    with pytest.raises(ServiceClientAuthDenied, match="rate"):
        subject.authorize(headers(), **arguments)
    assert len(calls) == 1

    now[0] += 6_000
    registry.authenticate = Registry().authenticate
    subject.authorize(headers(), **arguments)


@pytest.mark.parametrize(
    ("raw_headers", "registry_failure"),
    (
        (headers(), True),
        ([(b"authorization", f"Bearer {SECRET[:-1]}!".encode("ascii"))], False),
    ),
)
def test_rejected_bearer_is_absent_from_all_auth_traceback_locals(
    raw_headers, registry_failure,
):
    subject, registry, _, _ = authenticator()
    registry.fail = registry_failure
    raw_bearer = raw_headers[0][1].decode("ascii")

    with pytest.raises(ServiceClientAuthDenied) as captured:
        subject.authorize(
            raw_headers,
            tls=True,
            network_profile="portable_https",
            source_key="peer:one",
            route_id="work.revise",
            required_scope="command:work.revise",
        )

    current = captured.value.__traceback__
    while current is not None:
        if current.tb_frame.f_globals.get("__name__", "").startswith("app."):
            assert raw_bearer not in repr(current.tb_frame.f_locals)
        current = current.tb_next
