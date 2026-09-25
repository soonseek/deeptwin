"""The owner's run budgets over the supported factory (`budget-policies-v1`, T023).

Exact finite limits, admitted by the runtime's own `BudgetPolicy`, sealed as the binding
content runs enforce; idempotent by content; a subscription budget never claims an API
bill; authoring calls and starts nothing. No network, key or model call.
"""

from uuid import uuid4

from app.domain.refs import EntityRef
from app.services.runs import PersistentRuns
from app.tests.test_web_owner_integration import headers
from app.tests.test_works_api import owner_app

PATH = "api/v1/budget-policies"


def body(**changes):
    value = {"schema_version": "budget-policy-command-v1", "command_id": str(uuid4()), "profile": "execution",
             "provider_mode": "subscription", "max_model_calls": 4, "max_tool_calls": 6, "max_node_visits": 8,
             "max_loop_rounds": 2, "max_output_bytes": 200_000, "max_concurrency": 2, "max_wall_seconds": 600,
             "max_candidates": 1, "currency": None, "max_api_microunits": None}
    value.update(changes)
    return value


def post(subject, value):
    return subject.client.post(subject.profile.base_path + PATH, json=value, headers=headers(subject.profile, subject.csrf))


def test_an_owner_budget_is_sealed_as_the_runtimes_binding_and_idempotent_by_content(tmp_path):
    with owner_app(tmp_path) as subject:
        assert subject.client.get(subject.profile.base_path + PATH, headers=headers(subject.profile)).json() == {
            "policies": []}
        created = post(subject, body())
        assert created.status_code == 201, created.text
        view = created.json()
        assert view["max_model_calls"] == 4 and view["provider_mode"] == "subscription" and view["currency"] is None
        # the same limits under another command id are the same budget
        assert post(subject, body()).json()["budget_policy_ref"] == view["budget_policy_ref"]
        record = subject.domain.get(EntityRef.from_dict(view["budget_policy_ref"]))
        policy = PersistentRuns._policy(record)  # the runs service enforces exactly this record
        assert policy.id == view["policy_hash"] and policy.max_output_bytes == 200_000
        api = post(subject, body(provider_mode="api", currency="USD", max_api_microunits=2_000_000))
        assert api.status_code == 201 and api.json()["currency"] == "USD"
        listed = subject.client.get(subject.profile.base_path + PATH, headers=headers(subject.profile)).json()
        assert [item["provider_mode"] for item in listed["policies"]] == ["api", "subscription"]


def test_budgets_are_exact_finite_and_never_mix_a_subscription_with_an_api_bill(tmp_path):
    with owner_app(tmp_path) as subject:
        for bad in (body(provider_mode="api"), body(currency="USD", max_api_microunits=10),
                    body(max_model_calls=0), body(max_wall_seconds=-1), body(max_tool_calls=1.5),
                    body(profile="anything"), {**body(), "approved": True}, body(schema_version="v0")):
            assert post(subject, bad).status_code == 400, bad
        assert subject.client.get(subject.profile.base_path + PATH + "?x=1", headers=headers(subject.profile)
                                  ).status_code == 400
        no_csrf = subject.client.post(subject.profile.base_path + PATH, json=body(), headers=headers(subject.profile))
        assert no_csrf.status_code in {401, 403}
        with subject.domain._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind='budget_policy'").fetchone()[0] == 0


def test_a_changed_key_drops_the_old_catalog_and_no_key_mutation_calls_the_provider(tmp_path):
    from app.tests.test_claude_live_path import claude, connected
    from app.tests.test_work_models import app_with, authored

    spy, context = app_with(tmp_path, authored())
    with context as subject:
        connected(subject)
        calls = len(spy.requests)
        rotated = claude(subject, "key", {"secret": "sk-ant-api03-test-only-rotated-key"})
        assert rotated.status_code == 200 and rotated.json()["catalog"] is None  # never inherited
        assert len(spy.requests) == calls  # storing a key checks, refreshes and runs nothing
        refused = claude(subject, "model-choice", {"model_id": "anything"})
        assert refused.status_code == 503 and refused.json()["code"] == "provider_unavailable"
        forgotten = claude(subject, "forget", {})
        assert forgotten.json()["key_present"] is False and forgotten.json()["catalog"] is None
        assert len(spy.requests) == calls
