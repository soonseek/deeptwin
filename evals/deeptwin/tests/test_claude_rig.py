"""Offline tests of the Claude API Q01 rig (mock transport only; no network)."""

import json
import sqlite3

import pytest

from app.critic_trial import ProviderReply
from app.model_catalog import ModelCatalog
from app.model_selection import ModelSelection
from app.tests.test_claude_api import model
from evals.deeptwin.harness.claude_rig import TurnFailed, claude_rig
from evals.deeptwin.harness.q01_harness import run_trial
from evals.deeptwin.tests.claude_mock import EFFORTS, PLAN_MODEL, SECRET, MockClaude
from evals.deeptwin.tests.q01_support import CASE, ScriptedCritic


def echo(system, user):
    return "reply:" + user


def build(tmp_path, mock, **kwargs):
    options = {"secret": SECRET, "model_id": PLAN_MODEL, "effort": "medium", "transport": mock.transport,
               "max_tokens": 4096}
    options.update(kwargs)
    return claude_rig(tmp_path, **options)


def files_contain(root, needle: bytes):
    return [p for p in root.rglob("*") if p.is_file() and needle in p.read_bytes()]


def test_rig_saves_a_real_selection_naming_the_true_model_and_effort(tmp_path):
    mock = MockClaude(echo)
    rig = build(tmp_path, mock)
    selections = rig.config.selections
    assert isinstance(selections, ModelSelection) and isinstance(selections.catalog, ModelCatalog)
    saved = selections.get(rig.config.work_id)
    assert saved["version"] == rig.config.selection_version == 1
    choice = saved["selection"]
    assert (choice["provider"], choice["mode"], choice["model"], choice["effort"]) == (
        "claude", "api", PLAN_MODEL, "medium")
    assert choice["catalog_id"] == rig.catalog["catalog_id"]
    assert sorted(rig.catalog["listed_efforts"]) == ["high", "low", "medium"]
    # Only the catalog was fetched; no message was sent while building the rig.
    assert [r.url.path for r, _ in mock.spy.requests] == ["/v1/models"]
    assert rig.config.call_seconds > 180 - 1 and rig.usage == []


def test_turn_streams_a_toolless_bounded_request_and_records_usage(tmp_path):
    mock = MockClaude(echo, usage=lambda kind, s, u: (1234, 56))
    rig = build(tmp_path, mock)
    assert rig.turn("SYSTEM", "USER") == "reply:USER"
    (body,) = mock.requests()
    assert body["model"] == PLAN_MODEL and body["max_tokens"] == 4096
    assert body["output_config"] == {"effort": "medium"}
    assert body["system"] == "SYSTEM" and body["messages"] == [{"role": "user", "content": "USER"}]
    assert "tools" not in body and body["stream"] is True
    (entry,) = rig.usage
    assert entry["state"] == "completed" and entry["stop_reason"] == "end_turn"
    assert (entry["input_tokens"], entry["output_tokens"]) == (1234, 56)
    assert entry["provider_message_id"] == "msg_q01mock00000001" and entry["observed_model"] == PLAN_MODEL
    assert entry["dispatched"] is True and entry["usage_observed"] is True and entry["role"] == "critic"


def test_default_thinking_is_dropped_and_only_text_is_returned(tmp_path):
    mock = MockClaude(lambda s, u: '{"ok": true}', thinking="private reasoning")
    rig = build(tmp_path, mock)
    assert rig.turn("S", "U") == '{"ok": true}'
    assert "private reasoning" not in json.dumps(rig.usage)


@pytest.mark.parametrize("reason,state", [("max_tokens", "incomplete"), ("refusal", "refused")])
def test_a_non_completed_terminal_raises_and_is_recorded(tmp_path, reason, state):
    mock = MockClaude(echo, stop_reason=reason)
    rig = build(tmp_path, mock)
    with pytest.raises(TurnFailed) as raised:
        rig.turn("S", "U")
    assert raised.value.state == state
    assert rig.usage[0]["state"] == state and rig.usage[0]["stop_reason"] == reason


def test_a_provider_error_raises_without_text(tmp_path):
    mock = MockClaude(echo, message_status=500)
    rig = build(tmp_path, mock)
    with pytest.raises(TurnFailed) as raised:
        rig.turn("S", "U")
    assert raised.value.state == "failed"
    assert rig.usage[0]["failure"] and rig.usage[0]["usage_observed"] is False


def test_an_unlisted_effort_or_model_is_refused_before_any_message(tmp_path):
    no_effort = MockClaude(echo, models=[model(PLAN_MODEL, capabilities={"effort": {
        **EFFORTS, "medium": {"supported": False}}})])
    with pytest.raises(ValueError, match="effort"):
        build(tmp_path / "a", no_effort)
    missing = MockClaude(echo)
    with pytest.raises(ValueError, match="model"):
        build(tmp_path / "b", missing, model_id="claude-absent-1")
    assert not no_effort.requests() and not missing.requests()


def test_a_guard_refusal_sends_nothing(tmp_path):
    class Refuse:
        def before_call(self, entry):
            raise RuntimeError("limit")

        def after_call(self, entry):
            raise AssertionError("not reached")

    mock = MockClaude(echo)
    rig = build(tmp_path, mock, guard=Refuse())
    with pytest.raises(RuntimeError, match="limit"):
        rig.turn("S", "U")
    assert mock.requests() == [] and rig.usage == []


def test_the_secret_is_only_sent_as_the_api_key_header_and_never_stored(tmp_path):
    mock = MockClaude(echo)
    rig = build(tmp_path, mock)
    rig.turn("S", "U")
    for request, body in mock.spy.requests:
        assert request.headers.get("x-api-key") == SECRET
        assert SECRET.encode() not in body
    assert SECRET not in repr(rig) and SECRET not in json.dumps(rig.usage) and SECRET not in json.dumps(rig.catalog)
    assert files_contain(tmp_path, SECRET.encode()) == []


def test_a_harness_trial_runs_through_the_rig_and_freezes_the_claude_selection(tmp_path):
    mock = MockClaude(ScriptedCritic(propose=True))
    rig = build(tmp_path, mock, max_proposed_chains=2)
    trials = tmp_path / "trials"
    trials.mkdir()
    record = run_trial(CASE[("c71", "ce-17")], rig.turn, base_dir=trials, config=rig.config)
    assert record["status"] == "completed" and record["output_contract"] == "valid"
    assert len(record["calls"]) == len(rig.usage) == len(mock.requests()) == 6
    with sqlite3.connect(record["ledger_path"]) as db:
        selections = [json.loads(json.loads(row[0])["selection_json"])
                      for row in db.execute("SELECT payload FROM calls")]
    assert selections and all(s["provider"] == "claude" and s["model"] == PLAN_MODEL and s["effort"] == "medium"
                              for s in selections)
    assert files_contain(tmp_path, SECRET.encode()) == []


def test_the_attested_turn_reports_what_the_provider_response_said(tmp_path):
    # release-v6 (audit 5, X1): served model, message id and request id come from the
    # (fake) provider response as the product adapter parsed it, never from the selection
    mock = MockClaude(echo)
    rig = build(tmp_path, mock)
    reply = rig.attested_turn("S", "U")
    assert type(reply) is ProviderReply and reply.text == "reply:U"
    assert (reply.served_model, reply.provider_message_id) == (PLAN_MODEL, "msg_q01mock00000001")
    assert reply.provider_request_id == "req_q01mock00000001" == rig.usage[0]["request_id"]
    assert rig.turn("S", "U") == "reply:U"  # the calibration turn stays text only


def test_the_attested_turn_is_plain_text_without_a_provider_request_id(tmp_path):
    rig = build(tmp_path, MockClaude(echo, request_ids=False))
    assert rig.attested_turn("S", "U") == "reply:U"  # nothing to attest: the harness records it unattested


def test_an_attested_harness_trial_records_the_provider_reported_identity(tmp_path):
    mock = MockClaude(ScriptedCritic())
    rig = build(tmp_path, mock)
    trials = tmp_path / "trials"
    trials.mkdir()
    record = run_trial(CASE[("c71", None)], rig.attested_turn, base_dir=trials, config=rig.config)
    assert record["status"] == "completed" and record["model_identity"] == "provider_reported"
    ids = [call["ledger"]["details"]["provider_request_id"] for call in record["calls"]]
    assert ids == [entry["request_id"] for entry in rig.usage] and len(set(ids)) == len(ids)
    plain = run_trial(CASE[("c71", None)], rig.turn, base_dir=trials, config=rig.config)
    assert plain["model_identity"] == "selection_declared_not_transport_reported"
