"""The owner's operating versions: what runs now, what is waiting, approve, apply,
roll back (US6, T066 server half; growth.md §8, FR-026, UX-AC06).

One operating scope per vault holds a `PromotionState` lineage (growth_store's
promotion records, CAS by revision). The owner adopts the current environment once;
after that the only ways the operating version changes are an exact approved
candidate applied through `activate_candidate` (the approval binds the candidate
bundle, the validation report the owner saw and the current environment it was
given against; an approval is consumed once) or an explicit rollback with a stated
reason to the last retired version. Candidates are the persisted validation
reports whose bundle and cited rounds resume exactly (growth_store); a candidate
without a passed sealed-offline report can be rejected or deferred, never
approved. Nothing here runs a model, a tool or an external effect, and a rollback
restores the bundle, never the world (`external_effects_reverted` stays false).
"""

from __future__ import annotations

from functools import wraps
from uuid import NAMESPACE_URL, uuid5

from ..domain.refs import EntityRef, uuid_string
from ..domain.store import DomainStore
from .growth_store import (
    RECORD_KIND,
    GrowthStoreError,
    persist_promotion_state,
    resume_comparison_round_record,
    resume_loop,
    resume_promotion_state,
    resume_validation_report,
)
from .owner_auth import OwnerAuthError
from .promotion import (
    PromotionError,
    activate_candidate,
    open_promotion_state,
    record_promotion_decision,
    rollback_environment,
)
from .promotion_approvals import PersistentPromotionApprovals, PromotionApprovalError
from .run_approvals import _authenticate_owner, _owner_actor_ref
from .validation import validation_report_ref

__all__ = ["PersistentVersions", "VersionError"]

CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "conflict",
                   "unavailable"})
MAX_CANDIDATES = 64
MAX_ROUNDS = 256
_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


class VersionError(ValueError):
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
        except (VersionError, OwnerAuthError):
            raise
        except PromotionApprovalError as error:
            raise VersionError("conflict" if str(error) == "conflict" else "invalid_input") from None
        except (PromotionError, GrowthStoreError):
            raise VersionError("conflict") from None
        except Exception:  # noqa: BLE001 - storage errors must not disclose detail
            raise VersionError("unavailable") from None

    return invoke


def _stamp():
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime(_STAMP_FORMAT)


class PersistentVersions:
    def __init__(self, domain_store, owner_authority, approvals):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(approvals) is not PersistentPromotionApprovals:
            raise TypeError("Exact PersistentPromotionApprovals required")
        self._domain = domain_store
        self._owner = owner_authority
        self._approvals = approvals

    # --- the scope's promotion lineage -----------------------------------------------

    def _scope(self, roots) -> str:
        return str(uuid5(NAMESPACE_URL, f"deeptwin:operating-scope:{roots.genesis.id}"))

    def _head(self):
        """(state, record ref) of the newest promotion revision, or (None, None)."""

        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            scope = self._scope(roots)
            record_id = str(uuid5(NAMESPACE_URL, f"deeptwin:promotion:{scope}"))
            row = db.execute(
                "SELECT version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
                "ORDER BY version DESC LIMIT 1", (roots.genesis.id, RECORD_KIND, record_id)).fetchone()
        if row is None:
            return None, None, scope, roots
        ref = EntityRef(RECORD_KIND, record_id, row["version"], row["sha256"])
        return resume_promotion_state(self._domain, ref), ref, scope, roots

    def _headers(self, request, roots):
        with self._domain._connection() as db:
            actor = _authenticate_owner(self._owner, request)
            actor_ref = _owner_actor_ref(db, actor)
        return {"actor_ref": actor_ref, "access_policy_ref": roots.access_policy,
                "retention_policy_ref": roots.retention_policy, "created_at_utc": _stamp()}

    def _candidates(self):
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            rows = db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind=? "
                "AND instr(body, ?) > 0 ORDER BY id LIMIT ?",
                (roots.genesis.id, RECORD_KIND, b'"growth_kind":"growth_validation_report"',
                 MAX_CANDIDATES)).fetchall()
        found = []
        for row in rows:
            ref = EntityRef(RECORD_KIND, row["id"], row["version"], row["sha256"])
            try:
                candidate, report = resume_validation_report(self._domain, ref)
            except GrowthStoreError:
                # a report whose chain does not resume is shown as such, never as a candidate
                found.append({"report_record": ref.as_dict(), "readable": False})
                continue
            found.append({
                "report_record": ref.as_dict(), "readable": True,
                "validation_report_ref": validation_report_ref(report).as_dict(),
                "candidate_bundle_ref": candidate.bundle_ref.as_dict(),
                "change_candidate_ref": candidate.candidate.as_dict(),
                "mode": report.mode, "status": report.status,
                "approvable": report.mode == "sealed_offline" and report.status == "passed",
                "gates": {name: {"status": outcome.status, "reasons": list(outcome.reasons),
                                 "rounds": len(outcome.evidence)} for name, outcome in report.gates},
            })
        return found

    def _experiments(self):
        """Each growth lineage's newest loop revision, resumed exactly: status, the stop
        reason the loop actually recorded, best and progress rounds and counters."""

        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            rows = db.execute(
                "SELECT id, MAX(version) AS version FROM domain_records WHERE vault_id=? AND kind=? "
                "AND instr(body, ?) > 0 GROUP BY id ORDER BY id LIMIT ?",
                (roots.genesis.id, RECORD_KIND, b'"growth_kind":"growth_loop_state"', MAX_CANDIDATES)).fetchall()
            refs = []
            for row in rows:
                digest = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? "
                                    "AND version=?", (roots.genesis.id, RECORD_KIND, row["id"], row["version"])).fetchone()
                refs.append(EntityRef(RECORD_KIND, row["id"], row["version"], digest["sha256"]))
        found = []
        for ref in refs:
            try:
                loop = resume_loop(self._domain, ref).as_dict()
            except GrowthStoreError:
                found.append({"lineage_id": ref.id, "readable": False})
                continue
            found.append({"readable": True, **{key: loop[key] for key in (
                "lineage_id", "revision", "status", "floor_reached", "best_observed", "progress_reference",
                "non_improving_valid_count", "completed_round_ids", "consumed_budget", "stop_reason")}})
        return found

    def _rounds(self):
        """Every persisted paired round, re-issued exactly over its stored plan: which
        baseline run is paired with which candidate run, the round's validity and its
        stated reasons, and — only on a valid round — the measurements and utility it
        recorded. Nothing is scored here; a round that does not read back is listed as
        unreadable, never dropped."""

        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            rows = db.execute(
                "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND version=1 "
                "AND instr(body, ?) > 0 ORDER BY id LIMIT ?",
                (roots.genesis.id, RECORD_KIND, b'"growth_kind":"growth_comparison_round"',
                 MAX_ROUNDS)).fetchall()
        found = []
        for row in rows:
            ref = EntityRef(RECORD_KIND, row["id"], row["version"], row["sha256"])
            try:
                plan, result = resume_comparison_round_record(self._domain, ref)
            except GrowthStoreError:
                found.append({"round_record": ref.as_dict(), "readable": False})
                continue
            value = result.as_dict()
            found.append({
                "round_record": ref.as_dict(), "readable": True, "lineage_id": plan.lineage_id,
                "plan_mode": plan.mode, "baseline_environment_ref": plan.baseline_environment.as_dict(),
                "round_id": value["round_id"], "round_index": value["round_index"],
                "candidate_ref": value["candidate_ref"],
                "pairs": [{"baseline_run_ref": baseline, "candidate_run_ref": candidate}
                          for baseline, candidate in zip(value["baseline_run_refs"],
                                                         value["candidate_run_refs"], strict=True)],
                "validity": value["validity"], "validity_reasons": value["validity_reasons"],
                "metric_vector": value["metric_vector"], "utility": value["utility"],
                "evidence_refs": value["evidence_refs"],
            })
        found.sort(key=lambda item: (item.get("lineage_id", ""), item.get("round_index", -1),
                                     item["round_record"]["id"]))
        return found

    @staticmethod
    def _state_view(state):
        if state is None:
            return None
        return {"current_environment_ref": state.current_environment.as_dict(),
                "history": [{"environment_ref": ref.as_dict(), "lifecycle": lifecycle}
                            for ref, lifecycle in state.history],
                "applied_approvals": len(state.consumed_decisions),
                "external_effects_reverted": state.external_effects_reverted,
                "revision": state.revision}

    # --- reads --------------------------------------------------------------------------

    @_closed
    def read(self, request) -> dict:
        if request is None:
            raise VersionError("unauthenticated")
        self._owner.authenticate_bound(request.session)
        state, _ref, _scope, _roots = self._head()
        return {"state": self._state_view(state), "candidates": self._candidates(),
                "experiments": self._experiments(), "rounds": self._rounds()}

    # --- commands -----------------------------------------------------------------------

    @_closed
    def adopt(self, request, payload) -> dict:
        """Adopt an existing environment record as the first operating version, once."""

        if type(payload) is not dict or set(payload) != {"environment_ref"}:
            raise VersionError("invalid_input")
        _authenticate_owner(self._owner, request)
        environment = EntityRef.from_dict(payload["environment_ref"])
        if environment.kind != "environment":
            raise VersionError("invalid_input")
        self._domain.get(environment)  # it must be an actual record of this vault
        state, _ref, scope, roots = self._head()
        if state is not None:
            raise VersionError("conflict")  # adoption happens once; later changes are promotions
        persist_promotion_state(self._domain, open_promotion_state(environment.as_dict()),
                                scope_id=scope, parent_ref=None, **self._headers(request, roots))
        return self.read(request)

    @_closed
    def decide(self, request, payload) -> dict:
        """Record the owner's approve / reject / defer over one exact candidate."""

        if type(payload) is not dict or set(payload) != {"command_id", "decision", "validation_report_ref"}:
            raise VersionError("invalid_input")
        uuid_string(payload["command_id"])
        state, _ref, _scope, _roots = self._head()
        if state is None:
            raise VersionError("conflict")  # nothing operates yet: adopt first
        candidate = self._candidate_for(payload["validation_report_ref"])
        approval = self._approvals.record(request, {
            "schema_version": "promotion-approval-command-v1", "command_id": payload["command_id"],
            "decision": payload["decision"],
            "candidate_bundle": candidate["candidate_bundle_ref"],
            "validation_report": candidate["validation_report_ref"],
            "expected_current_environment": state.current_environment.as_dict(),
        })
        return {"approval_ref": approval.approval_ref.as_dict(), "decision": approval.decision,
                "candidate_bundle_ref": candidate["candidate_bundle_ref"]}

    def _candidate_for(self, report_ref_value):
        wanted = EntityRef.from_dict(report_ref_value)
        for item in self._candidates():
            if item["readable"] and item["validation_report_ref"] == wanted.as_dict():
                return item
        raise VersionError("not_found")

    @_closed
    def activate(self, request, payload) -> dict:
        """Apply exactly the approved bundle, or fail honestly (G-11/G-13)."""

        if type(payload) is not dict or set(payload) != {"approval_ref", "expected_revision"}:
            raise VersionError("invalid_input")
        _authenticate_owner(self._owner, request)
        approval = self._approvals.resolve(EntityRef.from_dict(payload["approval_ref"]))
        state, head_ref, scope, roots = self._head()
        if state is None or state.revision != payload["expected_revision"]:
            raise VersionError("conflict")
        if self._domain.get(head_ref).body["created_at_utc"] > approval.decided_at_utc:
            # The operating version moved after the owner decided (G-13). Matching the
            # expected environment is not enough: after an apply and a rollback the same
            # environment is current again, but the owner decided over a state that no
            # longer holds, so the approval is never revived — it is given again.
            raise VersionError("conflict")
        candidate_item = self._candidate_for(approval.validation_report.as_dict())
        candidate, report = resume_validation_report(
            self._domain, EntityRef.from_dict(candidate_item["report_record"]))
        decision = record_promotion_decision({
            "candidate": candidate, "validation_report": report, "scope": candidate.scope.as_dict(),
            "approval": approval, "expected_current_environment": approval.expected_current_environment.as_dict(),
            "rollback_bundle": candidate.rollback_bundle.as_dict(),
        })
        applied = activate_candidate(state, decision, candidate)
        persist_promotion_state(self._domain, applied, scope_id=scope, parent_ref=head_ref,
                                **self._headers(request, roots))
        return self.read(request)

    @_closed
    def rollback(self, request, payload) -> dict:
        """Restore the last retired version, stating why; nothing external is undone."""

        if (type(payload) is not dict or set(payload) != {"reason", "expected_revision"}
                or type(payload["reason"]) is not str):
            raise VersionError("invalid_input")
        _authenticate_owner(self._owner, request)
        state, head_ref, scope, roots = self._head()
        if state is None or state.revision != payload["expected_revision"]:
            raise VersionError("conflict")
        restored = rollback_environment(state, payload["reason"])
        persist_promotion_state(self._domain, restored, scope_id=scope, parent_ref=head_ref,
                                **self._headers(request, roots))
        return self.read(request)
