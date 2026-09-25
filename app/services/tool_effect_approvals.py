"""The owner's approvals of tool effect isolation boundaries (US6, G-14; T067).

A persisted comparison plan freezes a `tool_effect_policy` that names, per tool and
version, the one boundary an isolated re-run may use — `replay` (the recorded result
of the original call is handed back; nothing is sent) or `isolated_sink` (the call is
kept inside the isolated run's own vault; nothing is sent). Neither boundary is
admitted until the owner approves it here.

`read` lists every persisted plan with the boundaries its policy needs and the
owner's standing decision over each (`pending`, `approved`, `rejected`; the latest
decision decides). `decide` records one approve / reject as an owner decision
(`owner_decisions`, kind `tool_effect_boundary`) over the exact subject
`tool_effect_isolation.boundary_subject` computes from the stored plan and policy —
the policy record's identity, the tool and version, the boundary kind (and sink) and
the boundary digest. The command names the boundary digest the owner saw; a digest
that is not the stored boundary's is a conflict, never a decision over something
else. One record per command id: an exact replay returns the same decision, any
other body under the same id conflicts. The paired runner reads these decisions
through the same owner-decision reader (`ToolEffectSource`). Nothing here runs a
model, a tool or an external effect.
"""

from __future__ import annotations

import re
from functools import wraps

from ..domain.refs import DomainContractError, EntityRef, uuid_string
from ..domain.store import DomainStore
from .growth_store import RECORD_KIND, GrowthStoreError, resume_comparison_plan
from .owner_auth import OwnerAuthError
from .owner_decisions import OwnerDecisionError, PersistentOwnerDecisions
from .run_approvals import _authenticate_owner
from .tool_effect_isolation import (
    ToolEffectIsolationError,
    boundary_decision_command,
    boundary_digest,
    boundary_state,
    read_policy,
)
from .versions import VersionError

__all__ = ["PersistentToolEffectApprovals"]

MAX_PLANS = 256
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:+-]{0,63}\Z")
_DECIDE_KEYS = frozenset({"command_id", "plan_record_ref", "tool_id", "version", "boundary_sha256",
                          "decision"})


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (VersionError, OwnerAuthError):
            raise
        except OwnerDecisionError as error:
            code = str(error)
            raise VersionError("conflict" if code == "conflict" else
                               "invalid_input" if code.startswith("invalid") else "unavailable") from None
        except (ToolEffectIsolationError, DomainContractError):
            raise VersionError("invalid_input") from None
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise VersionError("unavailable") from None

    return invoke


class PersistentToolEffectApprovals:
    def __init__(self, domain_store, owner_authority, decisions):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(decisions) is not PersistentOwnerDecisions or not decisions.bound_to(domain_store):
            raise TypeError("An owner-decision service bound to this store is required")
        self._domain = domain_store
        self._owner = owner_authority
        self._decisions = decisions

    def _plan_rows(self):
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            return db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND version=1 "
                "AND instr(body, ?) > 0 ORDER BY id LIMIT ?",
                (roots.genesis.id, RECORD_KIND, b'"growth_kind":"growth_comparison_plan"', MAX_PLANS),
            ).fetchall()

    def _boundary_view(self, policy_ref, boundary):
        view = {"tool_id": boundary["tool_id"], "version": boundary["version"],
                "effect_class": boundary["effect_class"], "boundary": boundary["boundary"],
                "sink_id": boundary.get("sink_id")}
        try:
            view.update(boundary_state(self._decisions, policy_ref, boundary))
        except (OwnerDecisionError, ToolEffectIsolationError):
            view.update({"state": "unreadable", "decisions": None, "approval_ref": None,
                         "decided_at_utc": None, "boundary_sha256": boundary_digest(boundary)})
        return view

    def _plan_view(self, ref):
        try:
            plan = resume_comparison_plan(self._domain, ref)
        except GrowthStoreError:
            return {"plan_record": ref.as_dict(), "readable": False,
                    "reason": "the stored comparison plan does not read back exactly", "boundaries": []}
        base = {"plan_record": ref.as_dict(), "lineage_id": plan.lineage_id,
                "tool_effect_policy_ref": plan.tool_effect_policy.as_dict()}
        boundaries, gap = read_policy(self._domain, plan.tool_effect_policy)
        if boundaries is None:
            return {**base, "readable": False, "reason": gap, "boundaries": []}
        return {**base, "readable": True, "reason": None,
                "boundaries": [self._boundary_view(plan.tool_effect_policy, item) for item in boundaries]}

    @_closed
    def read(self, request) -> dict:
        """Every persisted plan, the boundaries its policy needs and their decisions."""

        if request is None:
            raise VersionError("unauthenticated")
        self._owner.authenticate_bound(request.session)
        plans = [self._plan_view(EntityRef(RECORD_KIND, row["id"], row["version"], row["sha256"]))
                 for row in self._plan_rows()]
        plans.sort(key=lambda item: (item.get("lineage_id") or "", item["plan_record"]["id"]))
        return {"plans": plans}

    @_closed
    def decide(self, request, payload) -> dict:
        """Record the owner's approve / reject over one boundary of one stored plan."""

        # authentication first: an unauthenticated caller learns nothing about plans
        _authenticate_owner(self._owner, request)
        if type(payload) is not dict or set(payload) != _DECIDE_KEYS:
            raise VersionError("invalid_input")
        uuid_string(payload["command_id"])
        if payload["decision"] not in {"approve", "reject"}:
            raise VersionError("invalid_input")
        for name in ("tool_id", "version"):
            if type(payload[name]) is not str or _TOKEN.fullmatch(payload[name]) is None:
                raise VersionError("invalid_input")
        if type(payload["boundary_sha256"]) is not str or _SHA.fullmatch(payload["boundary_sha256"]) is None:
            raise VersionError("invalid_input")
        plan_ref = EntityRef.from_dict(payload["plan_record_ref"])
        if plan_ref.kind != RECORD_KIND or plan_ref.version != 1:
            raise VersionError("invalid_input")
        try:
            plan = resume_comparison_plan(self._domain, plan_ref)
        except GrowthStoreError:
            raise VersionError("not_found") from None
        boundaries, _gap = read_policy(self._domain, plan.tool_effect_policy)
        if boundaries is None:
            raise VersionError("conflict")  # no boundary of an unreadable policy can be decided
        found = [item for item in boundaries
                 if (item["tool_id"], item["version"]) == (payload["tool_id"], payload["version"])]
        if len(found) != 1:
            raise VersionError("not_found")
        boundary = found[0]
        if boundary_digest(boundary) != payload["boundary_sha256"]:
            raise VersionError("conflict")  # the owner decided over other content than the stored boundary
        decision = self._decisions.record(request, boundary_decision_command(
            plan.tool_effect_policy, boundary, payload["decision"], payload["command_id"]))
        return {"approval_ref": decision.approval_ref.as_dict(), "decision": decision.decision,
                "decided_at_utc": decision.decided_at_utc, "plan_record_ref": plan_ref.as_dict(),
                "boundary": self._boundary_view(plan.tool_effect_policy, boundary)}
