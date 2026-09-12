"""Work-scoped finite limits with exact API billing lanes and durable history."""

import hmac
import re
from dataclasses import dataclass
from hashlib import sha256

from ..domain.refs import (
    MAX_INTEGER,
    DomainContractError,
    canonical_json,
    parse_canonical,
)
from ..runtime.budgets import BudgetPolicy, CorruptBudget
from ..storage import ConflictError, Store

PROFILES = frozenset({"design", "execution", "growth"})
PUBLIC_POLICY_FIELDS = (
    "provider_mode",
    "max_model_calls",
    "max_tool_calls",
    "max_wall_seconds",
    "max_output_bytes",
    "currency",
    "max_api_microunits",
)
AGGREGATE_FIELDS = (
    "max_model_calls",
    "max_tool_calls",
    "max_wall_seconds",
    "max_output_bytes",
)
HIDDEN_FIELDS = (
    "max_node_visits",
    "max_loop_rounds",
    "max_concurrency",
    "max_candidates",
)
_INPUT_FIELDS = frozenset(PUBLIC_POLICY_FIELDS)
_BUNDLE_FIELDS = frozenset({"aggregate", "api_lanes"})
_LANE_FIELDS = frozenset({
    "provider", "mode", "binding_id", "currency", "max_api_microunits",
})
_BUDGET_FIELDS = frozenset({
    "schema_version", "profile", "provider_mode", "max_model_calls",
    "max_tool_calls", "max_node_visits", "max_loop_rounds",
    "max_output_bytes", "max_concurrency", "max_wall_seconds",
    "max_candidates", "currency", "max_api_microunits",
})
_ENVELOPE_FIELDS = frozenset({
    "schema_version", "work_id", "profile", "version", "previous_hash",
    "policy_format", "budget_policy", "api_lanes",
})
_BINDING = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,299}\Z")


class UsagePolicyConflict(ConflictError):
    pass


@dataclass(frozen=True, slots=True)
class APICostLane:
    provider: str
    mode: str
    binding_id: str
    currency: str
    max_api_microunits: int

    def public(self):
        return {
            "provider": self.provider,
            "mode": self.mode,
            "binding_id": self.binding_id,
            "currency": self.currency,
            "max_api_microunits": self.max_api_microunits,
        }


@dataclass(frozen=True, slots=True)
class FrozenUsagePlan:
    work_id: str
    profile: str
    version: int
    policy_hash: str
    aggregate: BudgetPolicy
    api_lanes: tuple[APICostLane, ...]

    def budget_for(self, choice):
        if type(choice) is not dict:
            raise UsagePolicyConflict("모델 선택에 맞는 사용 한도를 확인해 주세요.")
        provider = choice.get("provider")
        mode = choice.get("mode")
        binding_id = choice.get("binding_id")
        if (provider not in {"claude", "codex"}
                or mode not in {"subscription", "api"}
                or type(binding_id) is not str
                or _BINDING.fullmatch(binding_id) is None):
            raise UsagePolicyConflict("모델 선택에 맞는 사용 한도를 확인해 주세요.")
        if mode == "subscription":
            if provider != "codex":
                raise UsagePolicyConflict(
                    "이 모델의 구독 연결 방식을 사용할 수 없습니다."
                )
            return self.aggregate
        lane = next((
            item for item in self.api_lanes
            if item.provider == provider and item.mode == mode
            and item.binding_id == binding_id
        ), None)
        if lane is None:
            raise UsagePolicyConflict("이 API 연결에 지정된 비용 한도가 없습니다.")
        return BudgetPolicy.create(
            profile=self.profile,
            provider_mode="api",
            max_model_calls=self.aggregate.max_model_calls,
            max_tool_calls=self.aggregate.max_tool_calls,
            max_node_visits=self.aggregate.max_node_visits,
            max_loop_rounds=self.aggregate.max_loop_rounds,
            max_output_bytes=self.aggregate.max_output_bytes,
            max_concurrency=self.aggregate.max_concurrency,
            max_wall_seconds=self.aggregate.max_wall_seconds,
            max_candidates=self.aggregate.max_candidates,
            currency=lane.currency,
            max_api_microunits=lane.max_api_microunits,
        )


class WorkUsagePolicies:
    def __init__(self, store):
        if type(store) is not Store:
            raise TypeError("Usage policies require the canonical Store")
        self.store = store
        with store._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS work_usage_policies (
                    work_id TEXT NOT NULL REFERENCES works(id),
                    profile TEXT NOT NULL CHECK(profile IN ('design','execution','growth')),
                    version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0),
                    policy BLOB NOT NULL CHECK(typeof(policy)='blob'),
                    policy_hash TEXT NOT NULL,
                    PRIMARY KEY(work_id, profile, version)
                );
                CREATE TABLE IF NOT EXISTS work_usage_policy_heads (
                    work_id TEXT NOT NULL REFERENCES works(id),
                    profile TEXT NOT NULL CHECK(profile IN ('design','execution','growth')),
                    version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>0),
                    policy_hash TEXT NOT NULL,
                    PRIMARY KEY(work_id, profile)
                );
            """)

    @staticmethod
    def _profile(value):
        if type(value) is not str or value not in PROFILES:
            raise ValueError("Unknown usage policy profile")
        return value

    @staticmethod
    def _version(value):
        if type(value) is not int or not 0 <= value <= MAX_INTEGER:
            raise ValueError("Usage policy version is invalid")
        return value

    @classmethod
    def _create_single(cls, profile, value):
        if type(value) is not dict or set(value) != _INPUT_FIELDS:
            raise ValueError("Usage policy fields are invalid")
        mode = value["provider_mode"]
        base = BudgetPolicy.recommended(
            profile, provider_mode=mode, currency=value["currency"],
            max_api_microunits=value["max_api_microunits"],
        )
        return BudgetPolicy.create(
            profile=profile, provider_mode=mode,
            max_model_calls=value["max_model_calls"],
            max_tool_calls=value["max_tool_calls"],
            max_node_visits=base.max_node_visits,
            max_loop_rounds=base.max_loop_rounds,
            max_output_bytes=value["max_output_bytes"],
            max_concurrency=base.max_concurrency,
            max_wall_seconds=value["max_wall_seconds"],
            max_candidates=base.max_candidates,
            currency=value["currency"],
            max_api_microunits=value["max_api_microunits"],
        )

    @staticmethod
    def _normalize_lanes(value):
        if type(value) is not list or len(value) > 20:
            raise ValueError("API cost lanes are invalid")
        result = []
        seen = set()
        for item in value:
            if type(item) is not dict or set(item) != _LANE_FIELDS:
                raise ValueError("API cost lane fields are invalid")
            provider, mode = item["provider"], item["mode"]
            binding_id, currency = item["binding_id"], item["currency"]
            cap = item["max_api_microunits"]
            if (provider not in {"claude", "codex"} or mode != "api"
                    or type(binding_id) is not str
                    or _BINDING.fullmatch(binding_id) is None
                    or type(currency) is not str
                    or re.fullmatch(r"[A-Z]{3}", currency) is None
                    or type(cap) is not int or not 1 <= cap <= MAX_INTEGER):
                raise ValueError("API cost lane is invalid")
            key = (provider, mode, binding_id)
            if key in seen:
                raise ValueError("API cost lane is duplicated")
            seen.add(key)
            result.append(APICostLane(provider, mode, binding_id, currency, cap))
        return tuple(sorted(
            result, key=lambda lane: (lane.provider, lane.mode, lane.binding_id)
        ))

    @classmethod
    def _create_bundle(cls, profile, value):
        if type(value) is not dict or set(value) != _BUNDLE_FIELDS:
            raise ValueError("Usage policy bundle fields are invalid")
        aggregate = value["aggregate"]
        if type(aggregate) is not dict or set(aggregate) != set(AGGREGATE_FIELDS):
            raise ValueError("Aggregate usage fields are invalid")
        base = BudgetPolicy.recommended(profile, provider_mode="subscription")
        policy = BudgetPolicy.create(
            profile=profile, provider_mode="subscription",
            max_model_calls=aggregate["max_model_calls"],
            max_tool_calls=aggregate["max_tool_calls"],
            max_node_visits=base.max_node_visits,
            max_loop_rounds=base.max_loop_rounds,
            max_output_bytes=aggregate["max_output_bytes"],
            max_concurrency=base.max_concurrency,
            max_wall_seconds=aggregate["max_wall_seconds"],
            max_candidates=base.max_candidates,
        )
        return policy, cls._normalize_lanes(value["api_lanes"])

    @classmethod
    def _normalize(cls, profile, value):
        profile = cls._profile(profile)
        if type(value) is dict and set(value) == _BUNDLE_FIELDS:
            policy, lanes = cls._create_bundle(profile, value)
            return "mixed", policy, lanes
        return "single", cls._create_single(profile, value), ()

    @staticmethod
    def _assert_hidden_defaults(policy):
        expected = BudgetPolicy.recommended(
            policy.profile, provider_mode=policy.provider_mode,
            currency=policy.currency,
            max_api_microunits=policy.max_api_microunits,
        )
        if any(
            getattr(policy, field) != getattr(expected, field)
            for field in HIDDEN_FIELDS
        ):
            raise CorruptBudget(
                "Stored work usage policy changed hidden scheduler limits"
            )

    @classmethod
    def _decode(cls, row, work_id, profile, previous_hash):
        try:
            if (row["work_id"] != work_id or row["profile"] != profile
                    or type(row["version"]) is not int or row["version"] < 1
                    or type(row["policy"]) is not bytes
                    or type(row["policy_hash"]) is not str):
                raise ValueError
            envelope = parse_canonical(row["policy"])
            if (type(envelope) is not dict or set(envelope) != _ENVELOPE_FIELDS
                    or envelope["schema_version"]
                    != "work-usage-policy-envelope-v1"
                    or envelope["work_id"] != work_id
                    or envelope["profile"] != profile
                    or envelope["version"] != row["version"]
                    or envelope["previous_hash"] != previous_hash
                    or envelope["policy_format"] not in {"single", "mixed"}
                    or type(envelope["budget_policy"]) is not dict
                    or set(envelope["budget_policy"]) != _BUDGET_FIELDS):
                raise ValueError
            digest = sha256(row["policy"]).hexdigest()
            if (not hmac.compare_digest(row["policy_hash"], digest)
                    or canonical_json(envelope) != row["policy"]):
                raise ValueError
            body = envelope["budget_policy"]
            if body["schema_version"] != "budget-policy-v1":
                raise ValueError
            policy = BudgetPolicy.create(**{
                key: item for key, item in body.items() if key != "schema_version"
            })
            if parse_canonical(policy.body_bytes) != body:
                raise ValueError
            cls._assert_hidden_defaults(policy)
            lanes = cls._normalize_lanes(envelope["api_lanes"])
            if (envelope["policy_format"] == "single" and lanes
                    or envelope["policy_format"] == "mixed"
                    and policy.provider_mode != "subscription"):
                raise ValueError
        except CorruptBudget:
            raise
        except (DomainContractError, KeyError, TypeError, ValueError) as exc:
            raise CorruptBudget(
                "Stored work usage policy failed integrity validation"
            ) from exc
        return {
            "version": row["version"], "policy_hash": row["policy_hash"],
            "policy_format": envelope["policy_format"], "budget": policy,
            "api_lanes": lanes,
        }

    def _history(self, db, work_id, profile):
        if db.execute("SELECT 1 FROM works WHERE id=?", (work_id,)).fetchone() is None:
            raise KeyError(work_id)
        rows = list(db.execute(
            "SELECT work_id,profile,version,policy,policy_hash "
            "FROM work_usage_policies WHERE work_id=? AND profile=? ORDER BY version",
            (work_id, profile),
        ))
        head = db.execute(
            "SELECT version,policy_hash FROM work_usage_policy_heads "
            "WHERE work_id=? AND profile=?",
            (work_id, profile),
        ).fetchone()
        if not rows and head is None:
            return []
        if (not rows or head is None or head["version"] != len(rows)
                or [row["version"] for row in rows]
                != list(range(1, len(rows) + 1))
                or not hmac.compare_digest(
                    head["policy_hash"], rows[-1]["policy_hash"]
                )):
            raise CorruptBudget("Stored work usage policy head is invalid")
        result = []
        previous_hash = None
        for row in rows:
            decoded = self._decode(row, work_id, profile, previous_hash)
            result.append(decoded)
            previous_hash = decoded["policy_hash"]
        return result

    @staticmethod
    def _public(decoded):
        policy = decoded["budget"]
        if decoded["policy_format"] == "single":
            return {
                "policy_id": decoded["policy_hash"],
                **{
                    name: getattr(policy, name)
                    for name in PUBLIC_POLICY_FIELDS
                },
            }
        return {
            "policy_id": decoded["policy_hash"],
            "aggregate": {
                name: getattr(policy, name) for name in AGGREGATE_FIELDS
            },
            "api_lanes": [lane.public() for lane in decoded["api_lanes"]],
        }

    def get(self, work_id, profile, version=None):
        profile = self._profile(profile)
        if version is not None:
            self._version(version)
        with self.store._connection() as db:
            history = self._history(db, work_id, profile)
        if not history:
            if version in (None, 0):
                return {"version": 0, "profile": profile, "policy": None}
            raise KeyError((work_id, profile, version))
        if version is None:
            decoded = history[-1]
        elif version < 1 or version > len(history):
            raise KeyError((work_id, profile, version))
        else:
            decoded = history[version - 1]
        return {
            "version": decoded["version"], "profile": profile,
            "policy": self._public(decoded),
        }

    @staticmethod
    def _same(decoded, policy_format, policy, lanes):
        return (
            decoded["policy_format"] == policy_format
            and decoded["budget"].body_bytes == policy.body_bytes
            and decoded["api_lanes"] == lanes
        )

    def save(self, work_id, profile, expected_version, value):
        profile = self._profile(profile)
        self._version(expected_version)
        policy_format, policy, lanes = self._normalize(profile, value)
        with self.store._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            history = self._history(db, work_id, profile)
            current_version = len(history)
            if current_version != expected_version:
                raise UsagePolicyConflict(
                    "Usage policy changed; reload the saved version"
                )
            if history and self._same(history[-1], policy_format, policy, lanes):
                return {
                    "version": current_version, "profile": profile,
                    "policy": self._public(history[-1]),
                }
            if expected_version >= MAX_INTEGER:
                raise UsagePolicyConflict("Usage policy version is exhausted")
            version = expected_version + 1
            previous_hash = None if not history else history[-1]["policy_hash"]
            envelope = {
                "schema_version": "work-usage-policy-envelope-v1",
                "work_id": work_id, "profile": profile, "version": version,
                "previous_hash": previous_hash, "policy_format": policy_format,
                "budget_policy": parse_canonical(policy.body_bytes),
                "api_lanes": [lane.public() for lane in lanes],
            }
            body = canonical_json(envelope)
            policy_hash = sha256(body).hexdigest()
            db.execute(
                "INSERT INTO work_usage_policies VALUES (?,?,?,?,?)",
                (work_id, profile, version, body, policy_hash),
            )
            db.execute(
                "INSERT INTO work_usage_policy_heads VALUES (?,?,?,?) "
                "ON CONFLICT(work_id,profile) DO UPDATE SET "
                "version=excluded.version,policy_hash=excluded.policy_hash",
                (work_id, profile, version, policy_hash),
            )
            observed = self._history(db, work_id, profile)
            if (len(observed) != version
                    or observed[-1]["policy_hash"] != policy_hash
                    or not self._same(
                        observed[-1], policy_format, policy, lanes
                    )):
                raise CorruptBudget(
                    "Work usage policy changed while it was being saved"
                )
            Store._event(db, "usage_policy_saved", work_id, {
                "profile": profile, "version": version,
                "policy_id": policy_hash,
                "provider_mode": (
                    policy.provider_mode if policy_format == "single" else "mixed"
                ),
                "max_model_calls": policy.max_model_calls,
                "max_tool_calls": policy.max_tool_calls,
                "max_wall_seconds": policy.max_wall_seconds,
                "max_output_bytes": policy.max_output_bytes,
                "api_lane_count": len(lanes),
            })
            final = self._history(db, work_id, profile)[-1]
            if final != observed[-1]:
                raise CorruptBudget("Work usage policy changed before commit")
        return {
            "version": version, "profile": profile,
            "policy": self._public(final),
        }

    def _current(self, work_id, profile, version):
        profile = self._profile(profile)
        self._version(version)
        if version < 1:
            raise ValueError("A saved usage policy is required")
        with self.store._connection() as db:
            history = self._history(db, work_id, profile)
        if not history or history[-1]["version"] != version:
            raise UsagePolicyConflict(
                "Usage policy changed; resolve the current version"
            )
        return history[-1]

    def for_runtime(self, work_id, profile, version):
        current = self._current(work_id, profile, version)
        if current["policy_format"] != "single":
            raise UsagePolicyConflict(
                "혼합 모델 실행은 정확한 모델 선택과 비용 한도를 함께 동결해야 합니다."
            )
        if current["budget"].provider_mode == "api":
            raise UsagePolicyConflict(
                "API 실행은 정확한 연결별 비용 한도를 함께 동결해야 합니다."
            )
        return current["budget"]

    def freeze_for_runtime(
        self, work_id, profile, version, *, model_choices,
    ):
        current = self._current(work_id, profile, version)
        if current["policy_format"] != "mixed":
            raise UsagePolicyConflict(
                "모델별 실행에는 전체 한도와 API 연결별 비용 한도가 필요합니다."
            )
        if type(model_choices) is not list or not model_choices:
            raise ValueError("At least one exact model choice is required")
        plan = FrozenUsagePlan(
            work_id, profile, version, current["policy_hash"],
            current["budget"], current["api_lanes"],
        )
        for choice in model_choices:
            plan.budget_for(choice)
        return plan
