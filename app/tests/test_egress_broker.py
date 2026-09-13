"""T043 (broker half): the controlled egress broker policy engine
(runtime.md §5-6 controlled egress; R09; FR-014).

Every supported HTTP(S) request becomes a typed broker fetch: HTTPS only on
port 443, GET/HEAD only, hostnames from the frozen grant set, no inherited
credentials (URL userinfo and auth/cookie headers refuse), every resolved
address must be public (private/loopback/link-local/metadata networks
refuse, and one bad address poisons the set), the connection is pinned to
the exact addresses the policy check resolved (DNS-rebinding defense),
every redirect revalidates the FULL policy with a fresh pinned resolution,
and the response body is byte-bounded. Unsupported routes (ws/wss/file/
data/http) fail visibly, and the product's own origin is never reachable
even when granted. The transport and resolver are injected — nothing here
touches a live network.
"""

import dataclasses

import pytest

from app.runtime.egress import (
    EgressBrokerError,
    broker_fetch,
    freeze_egress_policy,
    is_issued_fetch_result,
)


def policy(**overrides):
    fields = {
        "granted_hosts": ("docs.example.org", "mirror.example.net"),
        "product_origins": ("app.deeptwin.local",),
        "max_redirects": 3,
        "max_response_bytes": 4096,
    }
    fields.update(overrides)
    return freeze_egress_policy(**fields)


def resolver(table):
    def resolve(hostname):
        return table.get(hostname, ())
    return resolve


def scripted(responses, calls):
    def transport(method, url, addresses, headers):
        calls.append((method, url, tuple(addresses), dict(headers)))
        return responses[url]
    return transport


PUBLIC = {"docs.example.org": ("93.184.216.34",),
          "mirror.example.net": ("104.16.132.229", "2606:4700::7")}


def test_a_granted_fetch_pins_the_resolved_addresses():
    calls = []
    result = broker_fetch(
        policy(), "GET", "https://docs.example.org/guide",
        resolver=resolver(PUBLIC),
        transport=scripted(
            {"https://docs.example.org/guide": (200, {}, b"ok-body")}, calls,
        ),
    )
    assert is_issued_fetch_result(result)
    assert result.status == 200
    assert result.body == b"ok-body"
    assert result.final_url == "https://docs.example.org/guide"
    assert result.redirect_chain == ()
    # the transport connects only to the addresses the CHECK resolved
    assert calls[0][2] == ("93.184.216.34",)
    with pytest.raises(TypeError):
        dataclasses.replace(result, body=b"forged")


@pytest.mark.parametrize("url", [
    "http://docs.example.org/guide",
    "ws://docs.example.org/socket",
    "wss://docs.example.org/socket",
    "file:///etc/passwd",
    "data:text/html,hi",
    "ftp://docs.example.org/pub",
])
def test_unsupported_routes_fail_visibly(url):
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", url,
                     resolver=resolver(PUBLIC), transport=None)


def test_inherited_credentials_never_leave():
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", "https://user:pw@docs.example.org/",
                     resolver=resolver(PUBLIC), transport=None)
    for header in ("Authorization", "proxy-authorization", "Cookie"):
        with pytest.raises(EgressBrokerError):
            broker_fetch(policy(), "GET", "https://docs.example.org/guide",
                         headers={header: "secret"},
                         resolver=resolver(PUBLIC), transport=None)


def test_method_port_and_grant_limits():
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "POST", "https://docs.example.org/guide",
                     resolver=resolver(PUBLIC), transport=None)
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", "https://docs.example.org:8443/guide",
                     resolver=resolver(PUBLIC), transport=None)
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", "https://evil.example.com/guide",
                     resolver=resolver(PUBLIC), transport=None)


def test_the_product_origin_is_never_reachable():
    granted = policy(
        granted_hosts=("docs.example.org", "app.deeptwin.local"),
    )
    with pytest.raises(EgressBrokerError):
        broker_fetch(granted, "GET", "https://app.deeptwin.local/api",
                     resolver=resolver({"app.deeptwin.local": ("93.184.216.34",)}),
                     transport=None)


@pytest.mark.parametrize("address", [
    "10.0.0.8", "127.0.0.1", "169.254.169.254", "192.168.1.5",
    "172.16.0.9", "::1", "fd00::1", "fe80::1", "0.0.0.0",
])
def test_non_public_resolutions_refuse(address):
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", "https://docs.example.org/guide",
                     resolver=resolver({"docs.example.org": (address,)}),
                     transport=None)


def test_one_private_address_poisons_the_whole_set():
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(), "GET", "https://docs.example.org/guide",
            resolver=resolver(
                {"docs.example.org": ("93.184.216.34", "10.0.0.8")},
            ),
            transport=None,
        )


def test_empty_or_garbage_resolution_refuses():
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", "https://docs.example.org/guide",
                     resolver=resolver({}), transport=None)
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", "https://docs.example.org/guide",
                     resolver=resolver({"docs.example.org": ("not-an-ip",)}),
                     transport=None)


def test_redirects_revalidate_with_a_fresh_pinned_resolution():
    calls = []
    result = broker_fetch(
        policy(), "GET", "https://docs.example.org/guide",
        resolver=resolver(PUBLIC),
        transport=scripted({
            "https://docs.example.org/guide": (
                302, {"Location": "https://mirror.example.net/guide"}, b"",
            ),
            "https://mirror.example.net/guide": (200, {}, b"moved-ok"),
        }, calls),
    )
    assert result.body == b"moved-ok"
    assert result.final_url == "https://mirror.example.net/guide"
    assert result.redirect_chain == ("https://docs.example.org/guide",)
    assert calls[0][2] == ("93.184.216.34",)
    assert calls[1][2] == ("104.16.132.229", "2606:4700::7")


def test_a_rebinding_or_ungranted_redirect_refuses():
    # the redirect target resolves privately — classic rebinding
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(), "GET", "https://docs.example.org/guide",
            resolver=resolver({"docs.example.org": ("93.184.216.34",),
                               "mirror.example.net": ("192.168.1.5",)}),
            transport=scripted({
                "https://docs.example.org/guide": (
                    302, {"Location": "https://mirror.example.net/guide"}, b"",
                ),
            }, []),
        )
    # the redirect target is outside the grant set
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(), "GET", "https://docs.example.org/guide",
            resolver=resolver(PUBLIC),
            transport=scripted({
                "https://docs.example.org/guide": (
                    302, {"Location": "https://evil.example.com/"}, b"",
                ),
            }, []),
        )
    # a redirect with no destination is malformed, not silently final
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(), "GET", "https://docs.example.org/guide",
            resolver=resolver(PUBLIC),
            transport=scripted(
                {"https://docs.example.org/guide": (302, {}, b"")}, [],
            ),
        )


def test_redirect_loops_are_bounded():
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(max_redirects=2), "GET", "https://docs.example.org/a",
            resolver=resolver(PUBLIC),
            transport=scripted({
                "https://docs.example.org/a": (
                    302, {"Location": "https://docs.example.org/b"}, b"",
                ),
                "https://docs.example.org/b": (
                    302, {"Location": "https://docs.example.org/a"}, b"",
                ),
            }, []),
        )


def test_over_limit_bodies_refuse():
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(max_response_bytes=8), "GET",
            "https://docs.example.org/guide",
            resolver=resolver(PUBLIC),
            transport=scripted({
                "https://docs.example.org/guide": (200, {}, b"way-over-eight"),
            }, []),
        )


def test_the_policy_is_issued_and_validated():
    with pytest.raises(EgressBrokerError):
        freeze_egress_policy(granted_hosts=(), product_origins=(),
                             max_redirects=3, max_response_bytes=4096)
    with pytest.raises(EgressBrokerError):
        freeze_egress_policy(granted_hosts=("Docs.Example.org/path",),
                             product_origins=(), max_redirects=3,
                             max_response_bytes=4096)
    with pytest.raises(EgressBrokerError):
        freeze_egress_policy(granted_hosts=("docs.example.org",),
                             product_origins=(), max_redirects=0,
                             max_response_bytes=4096)
    with pytest.raises(EgressBrokerError):
        freeze_egress_policy(granted_hosts=("docs.example.org",),
                             product_origins=(), max_redirects=3,
                             max_response_bytes=0)
    frozen = policy()
    with pytest.raises(TypeError):
        dataclasses.replace(frozen, granted_hosts=("evil.example.com",))
    assert not is_issued_fetch_result(object())
