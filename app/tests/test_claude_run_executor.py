"""The Claude run executor records what the provider reported for each model call, and the
call's cost with its basis, so the owner's run trace can show them (2026-09-26, T048).

Each run goes through the supported app over a scripted mock transport: no network, no key
from the environment, no paid call. The provider's reported usage, the ceiling rates and
every amount here are synthetic test-actor values; the rates are this test's own host
configuration, never a price this product knows.

- Tokens: the output artifact (a completed call) or the outcome record (anything else)
  carries the provider's reported input, output and cache counts; a count it did not report
  stays unreported.
- Cost basis: `subscription_mode` (no money) under a subscription budget;
  `reserved_ceiling`, labelled an estimate, when the budget is API-priced and the host
  configured ceiling rates in that currency (the recorded tokens at those rates, rounded
  up); `not_recorded` otherwise. The executor never settles against the budget book.
"""

import httpx2
import pytest

from app.domain.refs import EntityRef
from app.runtime.budgets import BudgetPolicy
from app.services import claude_run_executor as executor_module
from app.services.claude_run_executor import (
    INTENT_SCHEMA,
    OUTPUT_SCHEMA,
    CeilingRates,
    ClaudeRunExecutor,
    LiveLimits,
    ceiling_rates_from_environment,
)
from app.services.runs import run_identity
from app.tests.test_claude_api import (
    MODEL_ID,
    SECRET,
    Spy,
    model,
    model_page,
    response,
    sse_event,
)
from app.tests.test_claude_live_path import (
    EFFORT,
    connected,
    live_graph,
    messages,
    real_work,
    start,
)
from app.tests.test_runs_api import owner_app
from app.tests.test_server_api_v1 import immutable
from app.tests.test_web_owner_integration import headers

# this test's own ceiling configuration (synthetic): micro-units per million tokens
RATES = CeilingRates(currency="USD", input_microunits_per_mtok=4_000_000,
                     output_microunits_per_mtok=20_000_000)
REPORTED = {"input_tokens": 812, "output_tokens": 164, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0}
# 812 x 4 + 164 x 20 micro-units
ESTIMATE = 6_528


def scripted_stream(usage, text="합성 모델 출력 (테스트 행위자)"):
    start_usage = {**usage, "output_tokens": 1}
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_synthetic_usage_1", "type": "message", "role": "assistant", "model": MODEL_ID,
            "content": [], "stop_reason": None, "stop_sequence": None, "usage": start_usage}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta", "text": text}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": usage["output_tokens"]}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return b"".join(sse_event(name, payload) for name, payload in events)


def scripted(usage=REPORTED, *, status=200):
    def responder(request, body):
        if request.url.path == "/v1/models":
            return response(request, payload=model_page([model(capabilities=EFFORT)]))
        if request.url.path == "/v1/messages":
            if status != 200:
                return response(request, status=status, payload={
                    "type": "error", "error": {"type": "api_error", "message": "synthetic failure"}})
            return response(request, body=scripted_stream(usage), headers={"content-type": "text/event-stream"})
        raise AssertionError(request.url.path)

    spy = Spy(responder)
    return spy, httpx2.MockTransport(spy)


def budget(subject, *, provider_mode="api", currency="USD"):
    """The run's budget policy, sealed as the owner's run inputs name it."""

    api = {"currency": currency, "max_api_microunits": 5_000_000} if provider_mode == "api" else {}
    policy = BudgetPolicy.create(
        profile="execution", provider_mode=provider_mode, max_model_calls=3, max_tool_calls=5,
        max_node_visits=7, max_loop_rounds=2, max_output_bytes=1_000, max_concurrency=2,
        max_wall_seconds=60, max_candidates=1, **api)
    subject.refs.budget = immutable(subject.domain, subject.domain.roots(), "budget_policy",
                                    content=policy.domain_content()).ref


def fresh(tmp_path, name):
    """A separate owned directory for one more app in the same test."""

    path = tmp_path / name
    path.mkdir()
    return path


def run_once(subject):
    """One owner-connected run of intake → writer (one model call) → publish."""

    choice = connected(subject)
    body, started = start(subject, live_graph(subject, choice), real_work(subject))
    return run_identity(body["command_id"]), started


def records(subject, run_id):
    """The writer's call records: (intent, output artifact or None, outcome or None)."""

    found = {}
    with subject.domain._connection() as db:
        rows = db.execute("SELECT kind, id, version, sha256 FROM domain_records WHERE kind IN "
                          "('decision_record', 'artifact')").fetchall()
    for row in rows:
        record = subject.domain.get(EntityRef(row["kind"], row["id"], row["version"], row["sha256"]))
        content = record.body["content"]
        if type(content) is dict and content.get("run_id", run_id) == run_id:
            found.setdefault(content.get("schema_version"), []).append(record)
    [intent] = found[INTENT_SCHEMA]
    output = found.get(OUTPUT_SCHEMA, [None])[0]
    outcome = found.get("claude-call-outcome-v1", [None])[0]
    return intent, output, outcome


def trace(subject, run_id):
    answer = subject.client.get(f"{subject.path}/{run_id}/trace", headers=headers(subject.profile))
    assert answer.status_code == 200, answer.text
    assert SECRET not in answer.text
    value = answer.json()
    writer = next(item for item in value["nodes"] if item["node_id"] == "writer")
    [call] = writer["visits"][0]["model_calls"]
    return value, call


def gaps(value):
    return {item["category"] for item in value["gaps"]}


def test_a_subscription_run_records_the_reported_tokens_and_states_no_money(tmp_path):
    spy, transport = scripted()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=64),
                                 transport=transport, ceiling_rates=RATES)
    with owner_app(tmp_path, executor) as subject:  # the default budget is a subscription
        run_id, started = run_once(subject)
        assert started.status_code == 201 and started.json()["phase"] == "completed", started.text
        assert len(messages(spy)) == 1
        intent, output, outcome = records(subject, run_id)
        assert outcome is None  # a completed call's record is its output artifact
        assert intent.body["content"]["ceiling_rates"] is None  # a subscription is never priced
        content = output.body["content"]
        assert content["output"]["usage"] == REPORTED
        assert content["output"]["provider_message_id"] == "msg_synthetic_usage_1"
        assert content["output"]["observed_model"] == MODEL_ID
        assert content["cost"] == {"state": "unknown", "basis": "subscription_mode"}
        value, call = trace(subject, run_id)
        assert call["tokens"] == {"input": 812, "output": 164, "cache_creation_input": 0, "cache_read_input": 0}
        assert call["cost"] == {"state": "unknown", "basis": "subscription_mode"}
        assert call["observed_model"] == MODEL_ID and call["provider_message_id"] == "msg_synthetic_usage_1"
        assert call["reasoning"] == "not_stored"
        assert value["totals"]["input_tokens"] == 812 and value["totals"]["output_tokens"] == 164
        assert value["totals"]["tokens_complete"] is True
        assert value["totals"]["cost"] == {"state": "unknown", "microunits": "not_recorded", "currency": None}
        # the cost is known to be a subscription's, so it is not a gap; hidden reasoning is
        assert "model_cost" not in gaps(value) and "reasoning" in gaps(value)


def test_an_api_priced_call_is_estimated_from_its_recorded_tokens_at_the_configured_ceiling(tmp_path):
    spy, transport = scripted()
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=64),
                                 transport=transport, ceiling_rates=RATES)
    with owner_app(tmp_path, executor) as subject:
        budget(subject, provider_mode="api", currency="USD")
        run_id, started = run_once(subject)
        assert started.json()["phase"] == "completed", started.text
        intent, output, _ = records(subject, run_id)
        # the rates in force are sealed with the intent, before the send
        assert intent.body["content"]["ceiling_rates"] == RATES.as_dict()
        expected = {"state": "estimate", "basis": "reserved_ceiling",
                    "method": "recorded_tokens_at_ceiling_rates", "microunits": ESTIMATE, "currency": "USD",
                    "rates": RATES.as_dict()}
        assert output.body["content"]["cost"] == expected
        value, call = trace(subject, run_id)
        # labelled an estimate, with the rates it was made from; never a settled charge
        assert call["cost"] == expected
        assert value["totals"]["cost"] == {"state": "estimate", "microunits": ESTIMATE, "currency": "USD"}
        assert "model_cost" not in gaps(value)
        # the executor never settled a call against the run's budget book
        assert value["budget_mode"] == "api"
        assert len(messages(spy)) == 1


def test_without_rates_in_the_run_currency_an_api_priced_call_cost_is_not_recorded(tmp_path):
    for rates in (None, CeilingRates(currency="EUR", input_microunits_per_mtok=4_000_000,
                                     output_microunits_per_mtok=20_000_000)):
        _spy, transport = scripted()
        executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=64),
                                     transport=transport, ceiling_rates=rates)
        with owner_app(fresh(tmp_path, "none" if rates is None else rates.currency), executor) as subject:
            budget(subject, provider_mode="api", currency="USD")
            run_id, started = run_once(subject)
            assert started.json()["phase"] == "completed", started.text
            intent, output, _ = records(subject, run_id)
            # never a currency conversion: rates in another currency do not apply
            assert intent.body["content"]["ceiling_rates"] is None
            assert output.body["content"]["cost"] == {"state": "unknown", "basis": "not_recorded"}
            value, call = trace(subject, run_id)
            assert call["tokens"]["input"] == 812 and call["tokens"]["output"] == 164
            assert call["cost"] == {"state": "unknown", "basis": "not_recorded"}
            assert value["totals"]["cost"]["state"] == "unknown"
            assert "model_cost" in gaps(value)


def test_a_reported_cache_token_is_priced_only_at_its_own_configured_rate(tmp_path):
    usage = {**REPORTED, "cache_read_input_tokens": 1_000}
    with_cache = CeilingRates(currency="USD", input_microunits_per_mtok=4_000_000,
                              output_microunits_per_mtok=20_000_000, cache_read_microunits_per_mtok=400_000)
    for rates, expected in ((RATES, None), (with_cache, ESTIMATE + 400)):
        _spy, transport = scripted(usage)
        executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=64),
                                     transport=transport, ceiling_rates=rates)
        with owner_app(fresh(tmp_path, str(expected)), executor) as subject:
            budget(subject, provider_mode="api", currency="USD")
            run_id, started = run_once(subject)
            assert started.json()["phase"] == "completed", started.text
            _value, call = trace(subject, run_id)
            assert call["tokens"]["cache_read_input"] == 1_000
            if expected is None:
                # a cache read with no configured rate is never priced as input
                assert call["cost"] == {"state": "unknown", "basis": "not_recorded"}
            else:
                assert call["cost"]["state"] == "estimate" and call["cost"]["microunits"] == expected


def test_a_call_whose_provider_reported_no_usage_stays_not_recorded(tmp_path):
    spy, transport = scripted(status=500)
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=64),
                                 transport=transport, ceiling_rates=RATES)
    with owner_app(tmp_path, executor) as subject:
        budget(subject, provider_mode="api", currency="USD")
        run_id, started = run_once(subject)
        assert started.status_code == 503  # the failed call fails the node; nothing retries
        assert len(messages(spy)) == 1
        _intent, output, outcome = records(subject, run_id)
        assert output is None and outcome.body["content"]["usage"] is None
        # rates are configured, but there are no recorded tokens to price
        assert outcome.body["content"]["cost"] == {"state": "unknown", "basis": "not_recorded"}
        value, call = trace(subject, run_id)
        assert call["state"] != "completed"
        assert set(call["tokens"].values()) == {"not_recorded"}
        assert call["cost"] == {"state": "unknown", "basis": "not_recorded"}
        assert value["totals"]["tokens_complete"] is False
        assert "model_cost" in gaps(value)


def test_a_call_recorded_before_its_cost_basis_reads_from_the_run_budget_only(tmp_path, monkeypatch):
    original = ClaudeRunExecutor._seal_artifact

    def as_before(self, *, record_id, text, role, content, parents=()):
        # an output sealed before the executor recorded a cost basis
        return original(self, record_id=record_id, text=text, role=role,
                        content={key: value for key, value in content.items() if key != "cost"},
                        parents=parents)

    monkeypatch.setattr(ClaudeRunExecutor, "_seal_artifact", as_before)
    for mode, expected in (("subscription", "subscription_mode"), ("api", "not_recorded")):
        _spy, transport = scripted()
        executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=2, max_output_tokens=64),
                                     transport=transport, ceiling_rates=RATES)
        with owner_app(fresh(tmp_path, mode), executor) as subject:
            budget(subject, provider_mode=mode, currency="USD")
            run_id, started = run_once(subject)
            assert started.json()["phase"] == "completed", started.text
            _intent, output, _ = records(subject, run_id)
            assert "cost" not in output.body["content"]
            _value, call = trace(subject, run_id)
            # nothing is priced at read time, even with rates configured now
            assert call["cost"] == {"state": "unknown", "basis": expected}


def test_ceiling_rates_are_explicit_host_configuration():
    assert RATES.as_dict() == {"currency": "USD", "unit": "microunits_per_million_tokens",
                               "input_microunits_per_mtok": 4_000_000,
                               "output_microunits_per_mtok": 20_000_000,
                               "cache_creation_microunits_per_mtok": None,
                               "cache_read_microunits_per_mtok": None}
    # rounded up to a whole micro-unit: a ceiling never rounds down
    tiny = CeilingRates(currency="USD", input_microunits_per_mtok=1, output_microunits_per_mtok=1)
    assert tiny.estimate({"input_tokens": 1, "output_tokens": 0}) == 1
    assert RATES.estimate(REPORTED) == ESTIMATE
    # an unreported input or output count is never priced; an unreported cache count adds nothing
    assert RATES.estimate({**REPORTED, "output_tokens": None}) is None
    assert RATES.estimate({"input_tokens": 812, "output_tokens": 164}) == ESTIMATE
    assert RATES.estimate(None) is None
    valid = {"currency": "USD", "input_microunits_per_mtok": 1, "output_microunits_per_mtok": 1}
    for bad in ({"currency": "usd"}, {"input_microunits_per_mtok": 0}, {"output_microunits_per_mtok": -1},
                {"cache_read_microunits_per_mtok": 0}, {"input_microunits_per_mtok": 1.5},
                {"output_microunits_per_mtok": 10 ** 13}):
        with pytest.raises(ValueError):
            CeilingRates(**{**valid, **bad})
    with pytest.raises(TypeError):
        ClaudeRunExecutor(ceiling_rates=RATES.as_dict())
    # the operator's environment: nothing set is no rates; a partial or malformed setting refuses
    prefix = "DEEPTWIN_LIVE_CEILING_"
    assert ceiling_rates_from_environment({}) is None
    full = {prefix + "CURRENCY": "USD", prefix + "INPUT_MICROUNITS_PER_MTOK": "4000000",
            prefix + "OUTPUT_MICROUNITS_PER_MTOK": "20000000"}
    assert ceiling_rates_from_environment(full) == RATES
    assert ceiling_rates_from_environment({**full, prefix + "CACHE_READ_MICROUNITS_PER_MTOK": "400000"}
                                          ).cache_read_microunits_per_mtok == 400_000
    for broken in ({prefix + "CURRENCY": "USD"}, {**full, prefix + "INPUT_MICROUNITS_PER_MTOK": "4e6"},
                   {**full, prefix + "OUTPUT_MICROUNITS_PER_MTOK": " 20000000"},
                   {**full, prefix + "OUTPUT_MICROUNITS_PER_MTOK": "20_000_000"},
                   {**full, prefix + "CACHE_CREATION_MICROUNITS_PER_MTOK": "0"},
                   {**full, prefix + "CURRENCY": "dollars"}):
        with pytest.raises(ValueError):
            ceiling_rates_from_environment(broken)
    assert executor_module.ESTIMATE_METHOD == "recorded_tokens_at_ceiling_rates"
