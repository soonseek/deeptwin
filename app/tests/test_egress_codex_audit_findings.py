"""Iter-55 adversarial audit closures: egress URL/header injection,
redirect-hop bounds, honest termination reporting, mandatory lineage.

F1 (HIGH): control characters (`\\r\\n`, `\\t`, leading space) survive
urlsplit's stripping and reach the transport verbatim — request-line/Host
header injection through a policy-clean parse. Any URL carrying a
character below 0x21 (or DEL) now refuses.
F2 (HIGH): header VALUES with CRLF and padded header NAMES
("Authorization ") smuggled credential headers past the name blocklist.
Names must be RFC 7230 tokens; values refuse control characters.
F3 (MEDIUM): redirect-hop bodies were never size-checked; every hop's
body is now bounded, not just the final one.
F4/F5 (LOW): lowercase `location` broke every real redirect (fail-closed
interop); transport status was vouched for unvalidated.
F7 (MEDIUM): a second close() overwrote termination_confirmed False→True
— and double-close is the NORMAL error flow.
F8 (LOW): no deadline gate stood between thread/start and turn/start, so
the prompt could transfer after the deadline.
F10 (MEDIUM): plain Ledger.reserve() admitted lineage-requiring purposes
parentless, making the whole B4 chain opt-in; chained purposes now
refuse outside reserve_with_lineage, and the trial runner routes them.
"""

import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app import codex_understanding
from app.codex_rpc import CodexRPC, terminate_owned_process
from app.critic_audit import Ledger
from app.runtime.egress import EgressBrokerError, broker_fetch
from app.tests.test_codex_understanding import choice, factory_for
from app.tests.test_critic_lineage import frozen as lineage_frozen
from app.tests.test_egress_broker import PUBLIC, policy, resolver, scripted
from app.understanding import ModelError


@pytest.mark.parametrize("url", [
    "https://docs.example.org/a\r\nHost: evil.example.com",
    "https://docs\t.example.org/x",
    " https://docs.example.org/x",
    "https://docs.example.org:4\t43/x",
    "https://docs.example.org/a\nb",
])
def test_f1_control_characters_never_reach_the_transport(url):
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", url,
                     resolver=resolver(PUBLIC), transport=None)


@pytest.mark.parametrize("headers", [
    {"X-Meta": "x\r\nCookie: session=stolen"},
    {"Authorization ": "Bearer token"},
    {"AUTHORIZATION\t": "x"},
    {"X-Ok\r\nCookie": "x"},
    {"": "empty-name"},
])
def test_f2_header_injection_and_padded_names_refuse(headers):
    with pytest.raises(EgressBrokerError):
        broker_fetch(policy(), "GET", "https://docs.example.org/guide",
                     headers=headers,
                     resolver=resolver(PUBLIC), transport=None)


def test_f3_redirect_hop_bodies_are_bounded_too():
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(max_response_bytes=8), "GET",
            "https://docs.example.org/guide",
            resolver=resolver(PUBLIC),
            transport=scripted({
                "https://docs.example.org/guide": (
                    302,
                    {"Location": "https://mirror.example.net/guide"},
                    b"an-over-limit-redirect-body",
                ),
            }, []),
        )


def test_f4_the_location_header_is_case_insensitive():
    calls = []
    result = broker_fetch(
        policy(), "GET", "https://docs.example.org/guide",
        resolver=resolver(PUBLIC),
        transport=scripted({
            "https://docs.example.org/guide": (
                302, {"location": "https://mirror.example.net/guide"}, b"",
            ),
            "https://mirror.example.net/guide": (200, {}, b"ok"),
        }, calls),
    )
    assert result.final_url == "https://mirror.example.net/guide"


@pytest.mark.parametrize("status", ["200 OK", True, 99, 600, None])
def test_f5_a_non_integer_or_out_of_range_status_refuses(status):
    with pytest.raises(EgressBrokerError):
        broker_fetch(
            policy(), "GET", "https://docs.example.org/guide",
            resolver=resolver(PUBLIC),
            transport=scripted(
                {"https://docs.example.org/guide": (status, {}, b"ok")}, [],
            ),
        )


class _Unkillable:
    """A process handle whose child never dies — poll always running."""

    stdin = None
    stdout = None

    def poll(self):
        return None

    def terminate(self):
        pass

    def kill(self):
        pass

    def wait(self, timeout=None):
        raise subprocess.TimeoutExpired(cmd="unkillable", timeout=timeout)


def test_f7_a_second_close_never_upgrades_the_verdict(tmp_path):
    assert terminate_owned_process(_Unkillable(), grace=0.01) is False
    rpc = CodexRPC([sys.executable, "-c", "pass"], cwd=tmp_path, timeout=0.2)
    rpc._process = _Unkillable()
    rpc.close()
    assert rpc.termination_confirmed is False
    rpc.close()  # double-close is the NORMAL error flow — the fact stands
    assert rpc.termination_confirmed is False


def test_f8_the_deadline_gates_the_prompt_transfer_itself(tmp_path, monkeypatch):
    factory, created = factory_for(tmp_path)

    def make(*args, **kwargs):
        rpc = factory(*args, **kwargs)
        plain_started = rpc.script["thread/start"]

        def slow_thread_start(_params, _rpc):
            time.sleep(0.1)  # the budget dies between thread and turn
            return plain_started

        rpc.script["thread/start"] = slow_thread_start
        return rpc

    monkeypatch.setattr(codex_understanding, "find_codex", lambda: "/tools/codex")
    monkeypatch.setattr(codex_understanding, "_native_tool_isolation_supported",
                        lambda _config: True)
    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / "data"), rpc_factory=make,
        version_reader=lambda _path: True)
    subject.timeout = 0.05
    with pytest.raises(ModelError) as caught:
        subject.generate("PRIVATE INPUT", {"type": "object"},
                         SimpleNamespace(is_set=lambda: False),
                         selection=choice())
    assert caught.value.reason == "timeout"
    methods = [method for method, _ in created[0].calls]
    assert "turn/start" not in methods
    assert "PRIVATE INPUT" not in repr(created[0].calls)


@pytest.mark.parametrize("purpose", [
    "counterexample_proposal", "counterexample_validity", "candidate_response",
])
def test_f10_plain_reserve_refuses_lineage_purposes(tmp_path, purpose):
    ledger = Ledger(tmp_path / "audit" / "eval.sqlite3")
    ledger.open_run("run-1", max_calls=8, max_seconds=600)
    with pytest.raises(ValueError, match="lineage"):
        ledger.reserve(lineage_frozen("req-1", purpose))
