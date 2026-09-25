"""The owner's run budgets on the supported factory (T023: the budget half of the
provider/key/model/budget GUI).

A budget is authored by the owner as exact finite limits — model calls, tool calls, node
visits, loop rounds, output bytes, concurrency, wall seconds, candidates — and, for an
API-key connection only, an explicit currency and cost cap in micro-units (a subscription
budget can never claim an API bill). `BudgetPolicy.create` (app/runtime/budgets.py)
admits it; the sealed `budget_policy` record carries the runtime's own binding content
(`budget-policy-binding-v1`), so a run consent and a run name exactly this record and the
runtime enforces exactly these limits. The same limits seal the same record (the id is
derived from the policy digest), so authoring is idempotent. Authoring a budget starts,
checks and calls nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from ..runtime.budgets import BudgetPolicy
from .owner_auth import OwnerAuthError
from .run_approvals import _authenticate_owner, _bound_pair, _owner_actor_ref

__all__ = ["COMMAND_SCHEMA", "LIMIT_FIELDS", "BudgetPolicyError", "PersistentBudgetPolicies"]

COMMAND_SCHEMA = "budget-policy-command-v1"
BINDING_SCHEMA = "budget-policy-binding-v1"
LIMIT_FIELDS = ("max_model_calls", "max_tool_calls", "max_node_visits", "max_loop_rounds", "max_output_bytes",
                "max_concurrency", "max_wall_seconds", "max_candidates")
FIELDS = ("profile", "provider_mode", *LIMIT_FIELDS, "currency", "max_api_microunits")
MAX_LISTED = 200
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "unavailable"})


class BudgetPolicyError(ValueError):
    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (BudgetPolicyError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage detail must not disclose
            raise BudgetPolicyError("unavailable") from None

    return invoke


def _view(record) -> dict:
    content = record.body["content"]
    policy = content["policy"]
    return {"budget_policy_ref": record.ref.as_dict(), "policy_hash": content["policy_hash"],
            **{name: policy[name] for name in FIELDS}, "created_at_utc": record.body["created_at_utc"]}


class PersistentBudgetPolicies:
    def __init__(self, domain_store, owner_authority):
        self._domain, self._owner = _bound_pair(domain_store, owner_authority, BudgetPolicyError)

    @_closed
    def list(self, request) -> dict:
        self._owner.authenticate_bound(request.session)
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            owner = db.execute("SELECT actor_ref FROM owner_auth_accounts").fetchone()
            rows = db.execute("SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND "
                              "kind='budget_policy' ORDER BY rowid DESC LIMIT ?",
                              (roots.genesis.id, MAX_LISTED)).fetchall()
            policies = []
            for row in rows:
                record = self._domain._load(db, EntityRef("budget_policy", row["id"], row["version"],
                                                          row["sha256"]), roots)[0]
                content = record.body["content"]
                if type(content) is not dict or content.get("schema_version") != BINDING_SCHEMA:
                    continue
                if owner is None or record.body["actor_ref"] != json.loads(owner["actor_ref"]):
                    continue  # only the owner's own budgets are offered
                policies.append(_view(record))
        return {"policies": policies}

    @_closed
    def create(self, request, payload) -> dict:
        _authenticate_owner(self._owner, request)
        if (type(payload) is not dict or set(payload) != {"schema_version", "command_id", *FIELDS}
                or payload["schema_version"] != COMMAND_SCHEMA):
            raise BudgetPolicyError("invalid_input")
        try:
            uuid_string(payload["command_id"])
            policy = BudgetPolicy.create(**{name: payload[name] for name in FIELDS})
        except (TypeError, ValueError):
            raise BudgetPolicyError("invalid_input") from None
        record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:budget-policy:{policy.id}"))
        with _writer(), self._domain._connection(write=True) as db:
            actor = _authenticate_owner(self._owner, request, db)
            roots = self._domain._read_roots(db)
            existing = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND "
                                  "kind='budget_policy' AND id=?", (roots.genesis.id, record_id)).fetchone()
            if existing is not None:
                ref = EntityRef("budget_policy", record_id, existing["version"], existing["sha256"])
                return _view(self._domain._load(db, ref, roots)[0])
            record = ImmutableRecord.create(
                kind="budget_policy", id=record_id, version=1,
                created_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z",
                actor_ref=_owner_actor_ref(db, actor), parent_refs=(), purpose="operational",
                access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                content=policy.domain_content())
            self._domain._put_in_transaction(db, record)
            return _view(self._domain._load(db, record.ref, roots)[0])
