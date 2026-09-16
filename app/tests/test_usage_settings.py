import json
from dataclasses import FrozenInstanceError, replace
from hashlib import sha256

import pytest

from app.domain.refs import MAX_INTEGER, canonical_json, parse_canonical
from app.runtime.budgets import BudgetPolicy, CorruptBudget
from app.server import create_development_app as create_app
from app.services.usage_settings import UsagePolicyConflict, WorkUsagePolicies
from app.storage import Store
from app.tests.local_http import LocalTestClient as TestClient


def draft(mode="subscription"):
    value = {
        "provider_mode": mode,
        "max_model_calls": 64,
        "max_tool_calls": 128,
        "max_wall_seconds": 1_200,
        "max_output_bytes": 64 * 1024 * 1024,
        "currency": None,
        "max_api_microunits": None,
    }
    if mode == "api":
        value.update(currency="USD", max_api_microunits=5_000_000)
    return value


def profile_draft(profile, mode="subscription"):
    base = BudgetPolicy.recommended(
        profile,
        provider_mode=mode,
        currency="USD" if mode == "api" else None,
        max_api_microunits=5_000_000 if mode == "api" else None,
    )
    return {
        "provider_mode": mode,
        "max_model_calls": base.max_model_calls,
        "max_tool_calls": base.max_tool_calls,
        "max_wall_seconds": base.max_wall_seconds,
        "max_output_bytes": base.max_output_bytes,
        "currency": base.currency,
        "max_api_microunits": base.max_api_microunits,
    }


def aggregate_limits():
    return {
        "max_model_calls": 64,
        "max_tool_calls": 128,
        "max_wall_seconds": 1_200,
        "max_output_bytes": 64 * 1024 * 1024,
    }


def api_lane(provider, binding_id, *, currency="USD", cap=5_000_000):
    return {
        "provider": provider,
        "mode": "api",
        "binding_id": binding_id,
        "currency": currency,
        "max_api_microunits": cap,
    }


def usage_bundle(*lanes):
    return {
        "aggregate": aggregate_limits(),
        "api_lanes": list(lanes),
    }


def frozen_choice(provider, mode, binding_id):
    return {
        "provider": provider,
        "mode": mode,
        "binding_id": binding_id,
    }


def subject(tmp_path):
    store = Store(tmp_path)
    work = store.create_work("내 업무")
    return store, work, WorkUsagePolicies(store)


def test_empty_profile_is_explicit_and_read_does_not_install_a_default(tmp_path):
    store, work, settings = subject(tmp_path)
    before = store.events(work["id"])

    assert settings.get(work["id"], "design") == {
        "version": 0,
        "profile": "design",
        "policy": None,
    }
    assert settings.get(work["id"], "execution")["policy"] is None
    assert store.events(work["id"]) == before


def test_subscription_policy_never_accepts_or_reports_an_api_money_cap(tmp_path):
    _, work, settings = subject(tmp_path)
    saved = settings.save(work["id"], "design", 0, draft())

    assert saved["version"] == 1
    assert saved["policy"]["provider_mode"] == "subscription"
    assert saved["policy"]["currency"] is None
    assert saved["policy"]["max_api_microunits"] is None
    assert isinstance(settings.for_runtime(work["id"], "design", 1), BudgetPolicy)

    for invalid in (
        {**draft(), "currency": "USD", "max_api_microunits": 1},
        {**draft(), "max_model_calls": True},
        {**draft(), "max_wall_seconds": 0},
        {**draft(), "unexpected": 1},
    ):
        with pytest.raises(ValueError):
            settings.save(work["id"], "design", 1, invalid)


def test_api_policy_requires_an_explicit_currency_and_positive_cost_cap(tmp_path):
    _, work, settings = subject(tmp_path)
    for invalid in (
        {**draft("api"), "currency": None},
        {**draft("api"), "currency": "usd"},
        {**draft("api"), "max_api_microunits": 0},
    ):
        with pytest.raises(ValueError):
            settings.save(work["id"], "execution", 0, invalid)

    saved = settings.save(work["id"], "execution", 0, draft("api"))
    assert saved["policy"]["currency"] == "USD"
    assert saved["policy"]["max_api_microunits"] == 5_000_000


def test_profiles_are_versioned_independently_and_cas_survives_restart(tmp_path):
    store, work, settings = subject(tmp_path)
    design = settings.save(work["id"], "design", 0, draft())
    execution = settings.save(work["id"], "execution", 0, draft("api"))

    with pytest.raises(UsagePolicyConflict):
        settings.save(work["id"], "design", 0, {**draft(), "max_model_calls": 20})
    reopened = WorkUsagePolicies(store)
    assert reopened.get(work["id"], "design") == design
    assert reopened.get(work["id"], "execution") == execution
    assert store.get_work(work["id"])["revision"] == work["revision"]
    assert [event["kind"] for event in store.events(work["id"])].count(
        "usage_policy_saved"
    ) == 2


def test_idempotent_save_does_not_create_a_new_version_or_event(tmp_path):
    store, work, settings = subject(tmp_path)
    first = settings.save(work["id"], "growth", 0, draft())
    before = store.events(work["id"])

    repeated = settings.save(work["id"], "growth", 1, draft())

    assert repeated == first
    assert store.events(work["id"]) == before


def test_persisted_policy_bytes_hash_and_profile_fail_closed(tmp_path):
    store, work, settings = subject(tmp_path)
    settings.save(work["id"], "design", 0, draft())
    with store._connection() as db:
        row = db.execute(
            "SELECT policy FROM work_usage_policies WHERE work_id=? AND profile='design'",
            (work["id"],),
        ).fetchone()
        changed = replace(
            BudgetPolicy.recommended("design", provider_mode="subscription"),
            body_bytes=bytes(row["policy"]),
        )
        assert changed.profile == "design"
        db.execute(
            "UPDATE work_usage_policies SET policy_hash=? "
            "WHERE work_id=? AND profile='design'",
            ("0" * 64, work["id"]),
        )

    with pytest.raises(CorruptBudget):
        settings.get(work["id"], "design")
    with pytest.raises(CorruptBudget):
        settings.for_runtime(work["id"], "design", 1)


def test_product_api_saves_exact_finite_policy_without_changing_work_revision(tmp_path):
    app = create_app(tmp_path / "product", understanding_provider_ready=False)
    with TestClient(app, base_url="http://127.0.0.1:4193") as client:
        headers = {"X-CSRF-Token": client.csrf_token}
        work = client.post(
            "/api/works", json={"text": "내 업무"}, headers=headers
        ).json()
        path = f'/api/works/{work["id"]}/usage-policies/design'
        assert client.get(path).json() == {
            "version": 0,
            "profile": "design",
            "policy": None,
        }
        saved = client.put(
            path,
            json={"expected_version": 0, "policy": draft("api")},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["policy"]["provider_mode"] == "api"
        assert saved.json()["policy"]["max_api_microunits"] == 5_000_000
        assert client.get(path).json() == saved.json()
        assert client.get(f'/api/works/{work["id"]}').json()["revision"] == 1
        assert client.put(
            path,
            json={"expected_version": 1, "policy": draft()},
        ).status_code == 403
        assert client.get(
            f'/api/works/{work["id"]}/usage-policies/unknown'
        ).status_code == 400


@pytest.mark.parametrize(
    "mutation",
    (
        "foreign_transplant",
        "version_rewrite",
        "history_replay",
        "previous_hash_rewrite",
        "history_delete",
        "head_delete",
    ),
)
def test_canonical_policy_chain_and_head_fail_closed_on_storage_mutation(
    tmp_path, mutation
):
    store, work, settings = subject(tmp_path)
    first = settings.save(work["id"], "design", 0, draft())
    second_draft = {**draft(), "max_model_calls": 65}
    settings.save(work["id"], "design", 1, second_draft)

    with store._connection() as db:
        if mutation == "foreign_transplant":
            other = store.create_work("다른 업무")
            other_settings = WorkUsagePolicies(store)
            other_settings.save(other["id"], "design", 0, {
                **draft(), "max_model_calls": 777,
            })
            other_settings.save(other["id"], "design", 1, {
                **draft(), "max_model_calls": 778,
            })
            foreign = db.execute(
                "SELECT policy,policy_hash FROM work_usage_policies "
                "WHERE work_id=? AND profile='design' AND version=2",
                (other["id"],),
            ).fetchone()
            db.execute(
                "UPDATE work_usage_policies SET policy=?,policy_hash=? "
                "WHERE work_id=? AND profile='design' AND version=2",
                (foreign["policy"], foreign["policy_hash"], work["id"]),
            )
        elif mutation == "version_rewrite":
            db.execute(
                "UPDATE work_usage_policies SET version=7 "
                "WHERE work_id=? AND profile='design' AND version=2",
                (work["id"],),
            )
        elif mutation == "history_replay":
            old = db.execute(
                "SELECT policy,policy_hash FROM work_usage_policies "
                "WHERE work_id=? AND profile='design' AND version=1",
                (work["id"],),
            ).fetchone()
            assert old["policy_hash"] == first["policy"]["policy_id"]
            db.execute(
                "UPDATE work_usage_policies SET policy=?,policy_hash=? "
                "WHERE work_id=? AND profile='design' AND version=2",
                (old["policy"], old["policy_hash"], work["id"]),
            )
        elif mutation == "previous_hash_rewrite":
            current = db.execute(
                "SELECT policy FROM work_usage_policies "
                "WHERE work_id=? AND profile='design' AND version=2",
                (work["id"],),
            ).fetchone()
            envelope = parse_canonical(bytes(current["policy"]))
            envelope["previous_hash"] = "0" * 64
            changed = canonical_json(envelope)
            changed_hash = sha256(changed).hexdigest()
            db.execute(
                "UPDATE work_usage_policies SET policy=?,policy_hash=? "
                "WHERE work_id=? AND profile='design' AND version=2",
                (changed, changed_hash, work["id"]),
            )
            db.execute(
                "UPDATE work_usage_policy_heads SET policy_hash=? "
                "WHERE work_id=? AND profile='design'",
                (changed_hash, work["id"]),
            )
        elif mutation == "history_delete":
            db.execute(
                "DELETE FROM work_usage_policies "
                "WHERE work_id=? AND profile='design' AND version=1",
                (work["id"],),
            )
        else:
            db.execute(
                "DELETE FROM work_usage_policies "
                "WHERE work_id=? AND profile='design' AND version=2",
                (work["id"],),
            )

    with pytest.raises(CorruptBudget):
        settings.get(work["id"], "design")
    with pytest.raises(CorruptBudget):
        settings.for_runtime(work["id"], "design", 2)


@pytest.mark.parametrize("profile", ("design", "execution", "growth"))
@pytest.mark.parametrize(
    "hidden_field",
    ("max_node_visits", "max_loop_rounds", "max_concurrency", "max_candidates"),
)
def test_every_hidden_recommended_field_is_rederived_for_each_profile(
    tmp_path, profile, hidden_field
):
    store, work, settings = subject(tmp_path)
    settings.save(work["id"], profile, 0, profile_draft(profile))

    with store._connection() as db:
        row = db.execute(
            "SELECT policy FROM work_usage_policies "
            "WHERE work_id=? AND profile=? AND version=1",
            (work["id"], profile),
        ).fetchone()
        envelope = parse_canonical(bytes(row["policy"]))
        forged_policy = dict(envelope["budget_policy"])
        forged_policy[hidden_field] += 1
        envelope["budget_policy"] = forged_policy
        forged = canonical_json(envelope)
        forged_hash = sha256(forged).hexdigest()
        db.execute(
            "UPDATE work_usage_policies SET policy=?,policy_hash=? "
            "WHERE work_id=? AND profile=? AND version=1",
            (forged, forged_hash, work["id"], profile),
        )
        db.execute(
            "UPDATE work_usage_policy_heads SET policy_hash=? "
            "WHERE work_id=? AND profile=?",
            (forged_hash, work["id"], profile),
        )

    with pytest.raises(CorruptBudget):
        settings.get(work["id"], profile)
    with pytest.raises(CorruptBudget):
        settings.for_runtime(work["id"], profile, 1)


def test_storage_envelope_binds_scope_chain_and_the_full_budget_policy(tmp_path):
    store, work, settings = subject(tmp_path)
    settings.save(work["id"], "design", 0, draft())
    settings.save(
        work["id"], "design", 1, {**draft(), "max_model_calls": 65}
    )

    with store._connection() as db:
        rows = db.execute(
            "SELECT version,policy,policy_hash FROM work_usage_policies "
            "WHERE work_id=? AND profile='design' ORDER BY version",
            (work["id"],),
        ).fetchall()
        head = db.execute(
            "SELECT version,policy_hash FROM work_usage_policy_heads "
            "WHERE work_id=? AND profile='design'",
            (work["id"],),
        ).fetchone()

    assert len(rows) == 2
    first = parse_canonical(bytes(rows[0]["policy"]))
    second = parse_canonical(bytes(rows[1]["policy"]))
    assert first["schema_version"] == "work-usage-policy-envelope-v1"
    assert {
        key: first[key]
        for key in ("work_id", "profile", "version", "previous_hash")
    } == {
        "work_id": work["id"],
        "profile": "design",
        "version": 1,
        "previous_hash": None,
    }
    assert second["work_id"] == work["id"]
    assert second["profile"] == "design"
    assert second["version"] == 2
    assert second["previous_hash"] == rows[0]["policy_hash"]
    assert rows[0]["policy_hash"] == sha256(rows[0]["policy"]).hexdigest()
    assert rows[1]["policy_hash"] == sha256(rows[1]["policy"]).hexdigest()

    expected_full = parse_canonical(
        BudgetPolicy.recommended(
            "design", provider_mode="subscription"
        ).body_bytes
    )
    assert first["budget_policy"] == expected_full
    assert set(first["budget_policy"]) == {
        "schema_version",
        "profile",
        "provider_mode",
        "max_model_calls",
        "max_tool_calls",
        "max_node_visits",
        "max_loop_rounds",
        "max_output_bytes",
        "max_concurrency",
        "max_wall_seconds",
        "max_candidates",
        "currency",
        "max_api_microunits",
    }
    assert dict(head) == {
        "version": 2,
        "policy_hash": rows[1]["policy_hash"],
    }


@pytest.mark.parametrize(
    "mutation", ("delete", "rollback", "foreign_transplant", "version_rewrite")
)
def test_head_pointer_mutation_fails_closed(tmp_path, mutation):
    store, work, settings = subject(tmp_path)
    settings.save(work["id"], "design", 0, draft())
    settings.save(
        work["id"], "design", 1, {**draft(), "max_model_calls": 65}
    )

    if mutation == "foreign_transplant":
        other = store.create_work("다른 업무")
        settings.save(other["id"], "design", 0, {
            **draft(), "max_model_calls": 777,
        })
        settings.save(other["id"], "design", 1, {
            **draft(), "max_model_calls": 778,
        })

    with store._connection() as db:
        if mutation == "delete":
            db.execute(
                "DELETE FROM work_usage_policy_heads "
                "WHERE work_id=? AND profile='design'",
                (work["id"],),
            )
        elif mutation == "rollback":
            first = db.execute(
                "SELECT policy_hash FROM work_usage_policies "
                "WHERE work_id=? AND profile='design' AND version=1",
                (work["id"],),
            ).fetchone()
            db.execute(
                "UPDATE work_usage_policy_heads SET version=1,policy_hash=? "
                "WHERE work_id=? AND profile='design'",
                (first["policy_hash"], work["id"]),
            )
        elif mutation == "foreign_transplant":
            foreign = db.execute(
                "SELECT version,policy_hash FROM work_usage_policy_heads "
                "WHERE work_id=? AND profile='design'",
                (other["id"],),
            ).fetchone()
            db.execute(
                "UPDATE work_usage_policy_heads SET version=?,policy_hash=? "
                "WHERE work_id=? AND profile='design'",
                (foreign["version"], foreign["policy_hash"], work["id"]),
            )
        else:
            db.execute(
                "UPDATE work_usage_policy_heads SET version=7 "
                "WHERE work_id=? AND profile='design'",
                (work["id"],),
            )

    with pytest.raises(CorruptBudget):
        settings.get(work["id"], "design")
    with pytest.raises(CorruptBudget):
        settings.for_runtime(work["id"], "design", 2)


def test_save_rereads_after_insert_and_rolls_back_trigger_mutation(tmp_path):
    store, work, settings = subject(tmp_path)
    source = store.create_work("변조 원본")
    settings.save(source["id"], "design", 0, {
        **draft(), "max_model_calls": 777,
    })
    before_events = store.events(work["id"])

    with store._connection() as db:
        db.execute(f"""
            CREATE TRIGGER mutate_usage_policy_after_insert
            AFTER INSERT ON work_usage_policies
            WHEN NEW.work_id='{work["id"]}' AND NEW.profile='design'
            BEGIN
                UPDATE work_usage_policies
                SET policy=(
                    SELECT policy FROM work_usage_policies
                    WHERE work_id='{source["id"]}'
                      AND profile='design' AND version=1
                ), policy_hash=(
                    SELECT policy_hash FROM work_usage_policies
                    WHERE work_id='{source["id"]}'
                      AND profile='design' AND version=1
                )
                WHERE work_id=NEW.work_id AND profile=NEW.profile
                  AND version=NEW.version;
            END
        """)

    with pytest.raises(CorruptBudget):
        settings.save(work["id"], "design", 0, draft())

    assert settings.get(work["id"], "design") == {
        "version": 0,
        "profile": "design",
        "policy": None,
    }
    assert store.events(work["id"]) == before_events


def test_save_rereads_after_head_update_and_rolls_back_trigger_mutation(tmp_path):
    store, work, settings = subject(tmp_path)
    first = settings.save(work["id"], "design", 0, draft())
    before_events = store.events(work["id"])

    with store._connection() as db:
        db.execute(f"""
            CREATE TRIGGER mutate_usage_policy_head_after_update
            AFTER UPDATE ON work_usage_policy_heads
            WHEN NEW.work_id='{work["id"]}' AND NEW.profile='design'
            BEGIN
                UPDATE work_usage_policy_heads
                SET policy_hash='{'0' * 64}'
                WHERE work_id=NEW.work_id AND profile=NEW.profile;
            END
        """)

    with pytest.raises(CorruptBudget):
        settings.save(
            work["id"], "design", 1, {**draft(), "max_model_calls": 65}
        )

    assert settings.get(work["id"], "design") == first
    assert store.events(work["id"]) == before_events


def test_usage_http_rejects_query_smuggling_and_duplicate_json_without_state_change(
    tmp_path,
):
    app = create_app(tmp_path / "product", understanding_provider_ready=False)
    with TestClient(app, base_url="http://127.0.0.1:4193") as client:
        headers = {"X-CSRF-Token": client.csrf_token}
        work = client.post(
            "/api/works", json={"text": "내 업무"}, headers=headers
        ).json()
        path = f'/api/works/{work["id"]}/usage-policies/design'
        expected_error = {"detail": "사용 한도 요청 형식을 확인해 주세요."}

        get_with_query = client.get(path + "?unexpected=1")
        assert get_with_query.status_code == 400
        assert get_with_query.json() == expected_error

        put_with_query = client.put(
            path + "?unexpected=1",
            json={"expected_version": 0, "policy": draft()},
            headers=headers,
        )
        assert put_with_query.status_code == 400
        assert put_with_query.json() == expected_error

        duplicate = client.put(
            path,
            content=(
                '{"expected_version":999,"expected_version":0,"policy":'
                + json.dumps(draft(), separators=(",", ":"))
                + "}"
            ),
            headers={**headers, "content-type": "application/json"},
        )
        assert duplicate.status_code == 400
        assert duplicate.json() == expected_error
        assert client.get(path).json() == {
            "version": 0,
            "profile": "design",
            "policy": None,
        }


def test_usage_http_reports_the_exact_api_cost_validation_error(tmp_path):
    app = create_app(tmp_path / "product", understanding_provider_ready=False)
    with TestClient(app, base_url="http://127.0.0.1:4193") as client:
        headers = {"X-CSRF-Token": client.csrf_token}
        work = client.post(
            "/api/works", json={"text": "내 업무"}, headers=headers
        ).json()
        path = f'/api/works/{work["id"]}/usage-policies/execution'

        response = client.put(
            path,
            json={
                "expected_version": 0,
                "policy": {**draft("api"), "currency": None},
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "API 연결의 통화와 0보다 큰 비용 한도를 확인해 주세요."
        }


def test_aggregate_limits_without_api_lanes_never_authorize_an_api_choice(tmp_path):
    _, work, settings = subject(tmp_path)
    saved = settings.save(work["id"], "design", 0, usage_bundle())
    subscription = frozen_choice(
        "codex", "subscription", "codex-subscription-binding-1"
    )

    frozen = settings.freeze_for_runtime(
        work["id"], "design", saved["version"], model_choices=[subscription]
    )
    subscription_budget = frozen.budget_for(subscription)
    assert isinstance(subscription_budget, BudgetPolicy)
    assert subscription_budget.provider_mode == "subscription"
    assert subscription_budget.currency is None
    assert subscription_budget.max_api_microunits is None

    for provider in ("claude", "codex"):
        with pytest.raises(UsagePolicyConflict, match="API.*비용 한도"):
            settings.freeze_for_runtime(
                work["id"],
                "design",
                saved["version"],
                model_choices=[
                    frozen_choice(provider, "api", f"{provider}-api-binding-1")
                ],
            )


def test_mixed_model_choices_store_read_and_freeze_exact_binding_cost_lanes(tmp_path):
    store, work, settings = subject(tmp_path)
    claude_lane = api_lane("claude", "claude-api-binding-1", cap=7_000_000)
    codex_lane = api_lane("codex", "codex-api-binding-1", cap=9_000_000)
    saved = settings.save(
        work["id"], "design", 0, usage_bundle(codex_lane, claude_lane)
    )

    assert saved["policy"]["aggregate"] == aggregate_limits()
    assert saved["policy"]["api_lanes"] == [claude_lane, codex_lane]
    assert WorkUsagePolicies(store).get(work["id"], "design") == saved

    codex_subscription = frozen_choice(
        "codex", "subscription", "codex-subscription-binding-1"
    )
    claude_api = frozen_choice("claude", "api", "claude-api-binding-1")
    codex_api = frozen_choice("codex", "api", "codex-api-binding-1")
    frozen = WorkUsagePolicies(store).freeze_for_runtime(
        work["id"],
        "design",
        saved["version"],
        model_choices=[codex_subscription, claude_api, codex_api],
    )

    assert frozen.work_id == work["id"]
    assert frozen.profile == "design"
    assert frozen.version == saved["version"]
    assert {
        field: getattr(frozen.aggregate, field)
        for field in aggregate_limits()
    } == aggregate_limits()
    recommended = BudgetPolicy.recommended(
        "design", provider_mode="subscription"
    )
    assert frozen.aggregate.max_node_visits == recommended.max_node_visits
    assert frozen.aggregate.max_loop_rounds == recommended.max_loop_rounds
    assert frozen.aggregate.max_concurrency == recommended.max_concurrency
    assert frozen.aggregate.max_candidates == recommended.max_candidates
    with pytest.raises(FrozenInstanceError):
        frozen.aggregate.max_model_calls = 1

    subscription_budget = frozen.budget_for(codex_subscription)
    claude_budget = frozen.budget_for(claude_api)
    codex_budget = frozen.budget_for(codex_api)
    assert isinstance(subscription_budget, BudgetPolicy)
    assert subscription_budget.provider_mode == "subscription"
    assert subscription_budget.max_api_microunits is None
    assert claude_budget.provider_mode == "api"
    assert claude_budget.currency == "USD"
    assert claude_budget.max_api_microunits == 7_000_000
    assert codex_budget.provider_mode == "api"
    assert codex_budget.currency == "USD"
    assert codex_budget.max_api_microunits == 9_000_000
    assert {
        budget.max_model_calls
        for budget in (subscription_budget, claude_budget, codex_budget)
    } == {aggregate_limits()["max_model_calls"]}

    for wrong_choice in (
        frozen_choice("claude", "api", "claude-api-binding-other"),
        frozen_choice("codex", "api", "claude-api-binding-1"),
    ):
        with pytest.raises(UsagePolicyConflict, match="API.*비용 한도"):
            settings.freeze_for_runtime(
                work["id"],
                "design",
                saved["version"],
                model_choices=[wrong_choice],
            )


@pytest.mark.parametrize(
    "invalid",
    (
        {"aggregate": {**aggregate_limits(), "max_model_calls": True}, "api_lanes": []},
        {"aggregate": {**aggregate_limits(), "max_tool_calls": 0}, "api_lanes": []},
        {
            "aggregate": {
                **aggregate_limits(),
                "max_output_bytes": MAX_INTEGER + 1,
            },
            "api_lanes": [],
        },
        {"aggregate": {**aggregate_limits(), "unexpected": 1}, "api_lanes": []},
        usage_bundle(api_lane("claude", "", cap=1)),
        usage_bundle(api_lane("unknown", "binding-1", cap=1)),
        usage_bundle({
            **api_lane("claude", "binding-1", cap=1),
            "mode": "subscription",
        }),
        usage_bundle(api_lane("claude", "binding-1", currency="usd", cap=1)),
        usage_bundle(api_lane("claude", "binding-1", currency=None, cap=1)),
        usage_bundle(api_lane("claude", "binding-1", cap=0)),
        usage_bundle(api_lane("claude", "binding-1", cap=True)),
        usage_bundle(api_lane("claude", "binding-1", cap=MAX_INTEGER + 1)),
        usage_bundle({**api_lane("claude", "binding-1", cap=1), "unexpected": 1}),
        usage_bundle(
            api_lane("claude", "binding-1", cap=1),
            api_lane("claude", "binding-1", cap=2),
        ),
    ),
)
def test_aggregate_and_api_lane_schema_currency_caps_and_keys_are_strict(
    tmp_path, invalid
):
    _, work, settings = subject(tmp_path)
    with pytest.raises(ValueError):
        settings.save(work["id"], "design", 0, invalid)


def test_usage_http_rejects_nested_duplicate_policy_fields(tmp_path):
    app = create_app(tmp_path / "product", understanding_provider_ready=False)
    with TestClient(app, base_url="http://127.0.0.1:4193") as client:
        headers = {
            "X-CSRF-Token": client.csrf_token,
            "content-type": "application/json",
        }
        work = client.post(
            "/api/works",
            json={"text": "내 업무"},
            headers={"X-CSRF-Token": client.csrf_token},
        ).json()
        path = f'/api/works/{work["id"]}/usage-policies/design'
        response = client.put(
            path,
            content=(
                '{"expected_version":0,"policy":{'
                '"provider_mode":"subscription",'
                '"max_model_calls":999,"max_model_calls":64,'
                '"max_tool_calls":128,"max_wall_seconds":1200,'
                '"max_output_bytes":67108864,"currency":null,'
                '"max_api_microunits":null}}'
            ),
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json() == {
            "detail": "사용 한도 요청 형식을 확인해 주세요."
        }
        assert client.get(path).json()["version"] == 0
