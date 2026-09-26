"""What a run of one work can use: the owner's prepared environment versions for it
(T048: run creation from the intake page).

An `environment` record (`design_store.persist_environment_record`) names the design
the owner approved by its design-space identity, not by a store reference. This read
binds it back to the vault through the records that produced it, and lists a version
only when every link resolves and agrees:

- the environment record → its own head record → the owner's design approval record
  (whose digest must be the version's `approval_sha`), which names the exact bindings:
  the model choice, the tool permission grant, the observation contract and the critic
  qualification the approval was recorded under;
- the design → the stored `graph` record at the same identity, admitted by
  `GraphVersion.from_untrusted` and whose `graph_digest` must equal the design's hash —
  that record is the `graph_ref` a run names;
- the graph's work model → the stored `work_model` record → the work revision the
  design was made for, which must belong to THIS work. The run names that revision
  (and the view says whether a newer one exists).

A version whose chain does not resolve is never offered; it is counted with its
reason. The view also says whether this instance can execute a run at all (a run
executor is host wiring) and, when nothing is offered, exactly why — in production no
design can be approved because no critic configuration can be qualified
(`critic_qualification.V3_VERIFYING_DESIGN_IDS` is empty; V3 is unverified). A
qualification outside the release designs is labelled `simulated` (test-actor).
Nothing here records a consent or starts a run: the page does that through the
run-consents and runs routes, which verify every input themselves.
"""

from __future__ import annotations

from functools import wraps
from hashlib import sha256

from ..domain.graph_schema import GraphContractError, GraphVersion
from ..domain.refs import DomainContractError, EntityRef, canonical_json, uuid_string
from ..domain.store import DomainStore
from ..runtime.graph import graph_digest
from . import critic_qualification as gate
from .design_persistence import DesignPersistenceError, decode_design_refs
from .design_store import ENTITY_SCHEMAS
from .owner_auth import OwnerAuthError, PersistentOwnerAuthority

__all__ = ["PersistentRunEnvironments", "RunEnvironmentError"]

SCHEMA = "run-environments-v1"
CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found", "unavailable"})
MAX_ENVIRONMENTS = 256


class RunEnvironmentError(ValueError):
    def __init__(self, code="invalid_input"):
        if code not in CODES:
            code = "unavailable"
        super().__init__(code)
        self.code = code


class _Skip(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _closed(method):
    @wraps(method)
    def invoke(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (RunEnvironmentError, OwnerAuthError):
            raise
        except Exception:  # noqa: BLE001 - storage detail never leaves the service
            raise RunEnvironmentError("unavailable") from None

    return invoke


def _ref_dict(value) -> dict:
    return EntityRef.from_dict(value).as_dict()


class PersistentRunEnvironments:
    def __init__(self, domain_store, owner_authority, *, runs_available):
        if type(domain_store) is not DomainStore:
            raise TypeError("Exact DomainStore required")
        if type(owner_authority) is not PersistentOwnerAuthority or owner_authority._domain is not domain_store:
            raise TypeError("Owner authority must share the actual domain store")
        if not callable(runs_available):
            raise TypeError("runs_available must be callable")
        self._domain = domain_store
        self._owner = owner_authority
        self._runs_available = runs_available

    # --- the chain ------------------------------------------------------------

    def _one(self, db, roots, kind, identifier, version):
        row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? AND version=?",
                         (roots.genesis.id, kind, identifier, version)).fetchone()
        if row is None:
            return None
        return self._domain._load(db, EntityRef(kind, identifier, version, row["sha256"]), roots)[0]

    def _approval(self, db, roots, head, approval_sha):
        for parent in head.body["parent_refs"]:
            if parent["kind"] != "decision_record":
                continue
            record = self._domain._load(db, EntityRef.from_dict(parent), roots)[0]
            content = record.body.get("content")
            if type(content) is dict and content.get("design_kind") == "design_approval_record":
                approval = decode_design_refs(content["design"])
                if sha256(canonical_json(approval)).hexdigest() != approval_sha:
                    raise _Skip("approval_mismatch")
                return approval
        raise _Skip("approval_not_found")

    def _entry(self, db, roots, record, work_id):
        content = record.body.get("content")
        if type(content) is not dict or content.get("schema_version") not in ENTITY_SCHEMAS:
            raise _Skip("not_an_environment_record")
        prepared = decode_design_refs({key: value for key, value in content.items() if key != "schema_version"})
        heads = [item for item in record.body["parent_refs"] if item["kind"] == "decision_record"]
        if len(heads) != 1:
            raise _Skip("head_not_found")
        head = self._domain._load(db, EntityRef.from_dict(heads[0]), roots)[0]
        approval = self._approval(db, roots, head, prepared["approval_sha"])
        design = EntityRef.from_dict(prepared["design_ref"])
        if design.kind != "graph" or approval["design_ref"] != design.as_dict():
            raise _Skip("design_mismatch")
        graph_record = self._one(db, roots, "graph", design.id, design.version)
        if graph_record is None:
            raise _Skip("graph_not_in_vault")
        graph_content = graph_record.body.get("content")
        if type(graph_content) is not dict or graph_content.get("design_kind") != "functional_graph":
            raise _Skip("graph_not_in_vault")
        try:
            graph = GraphVersion.from_untrusted(decode_design_refs(graph_content["design"]))
        except (DesignPersistenceError, GraphContractError, DomainContractError, TypeError, ValueError):
            raise _Skip("graph_invalid") from None
        if graph_digest(graph) != design.sha256:
            raise _Skip("graph_mismatch")
        value = graph.as_dict()
        model_ref = EntityRef.from_dict(value["work_model_ref"])
        work_model = self._one(db, roots, "work_model", model_ref.id, model_ref.version)
        if work_model is None:
            raise _Skip("work_model_not_in_vault")
        revision = work_model.body["content"].get("work_revision_ref")
        if type(revision) is not dict or revision.get("kind") != "work_revision":
            raise _Skip("work_model_invalid")
        if revision["id"] != work_id:
            raise _Skip("other_work")
        qualification = dict(approval["critic_qualification"])
        return {
            "environment_ref": record.ref.as_dict(),
            "environment_id": prepared["environment_id"],
            "version": prepared["version"],
            "status": prepared["status"],
            "activation": "not_activated",
            "extension_binding_revisions": list(prepared.get("extension_binding_revisions", [])),
            "work_revision_ref": _ref_dict(revision),
            "graph_ref": graph_record.ref.as_dict(),
            "graph": {
                "graph_id": value["graph_id"], "version": value["version"], "digest": design.sha256,
                "nodes": [{"node_id": node["node_id"], "kind": node["kind"],
                           "responsibility": node["responsibility"]} for node in value["nodes"]],
                "model_bindings": [{"binding_id": item["binding_id"], "model_choice_ref": item["model_choice_ref"]}
                                   for item in value["model_bindings"]],
                "tool_bindings": [{"binding_id": item["binding_id"], "grant_ref": item["grant_ref"],
                                   "tool_definition_ref": item["tool_definition_ref"],
                                   "capabilities": list(item["capabilities"])} for item in value["tool_bindings"]],
                "grant_refs": list(value["grant_refs"]),
            },
            "approval": {
                "candidate_id": approval["candidate_id"], "approved_at": approval["approved_at"],
                "model_bindings_ref": approval["model_bindings_ref"],
                "tool_permissions_ref": approval["tool_permissions_ref"],
                "observation_contract_ref": approval["observation_contract_ref"],
            },
            "critic_qualification": {
                "status": qualification.get("status"), "reason": qualification.get("reason"),
                "design_id": qualification.get("design_id"),
                # a qualification outside the release designs is a test-actor simulation
                "simulated": qualification.get("design_id") not in gate.RELEASE_DESIGN_IDS,
            },
        }

    # --- the read -------------------------------------------------------------

    @_closed
    def read(self, request, work_id) -> dict:
        self._owner.authenticate_bound(request.session)
        try:
            work_id = uuid_string(work_id)
        except (TypeError, ValueError):
            raise RunEnvironmentError("invalid_input") from None
        with self._domain._connection() as db:
            roots = self._domain._read_roots(db)
            latest = db.execute("SELECT version, sha256 FROM domain_records WHERE vault_id=? AND "
                                "kind='work_revision' AND id=? ORDER BY version DESC LIMIT 1",
                                (roots.genesis.id, work_id)).fetchone()
            if latest is None:
                raise RunEnvironmentError("not_found")
            current = EntityRef("work_revision", work_id, latest["version"], latest["sha256"]).as_dict()
            rows = db.execute("SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND "
                              "kind='environment' ORDER BY rowid LIMIT ?",
                              (roots.genesis.id, MAX_ENVIRONMENTS + 1)).fetchall()
            if len(rows) > MAX_ENVIRONMENTS:
                raise RunEnvironmentError("unavailable")
            offered, skipped = [], {}
            for row in rows:
                record = self._domain._load(db, EntityRef("environment", row["id"], row["version"], row["sha256"]),
                                            roots)[0]
                try:
                    entry = self._entry(db, roots, record, work_id)
                except _Skip as skip:
                    if skip.reason != "other_work":
                        skipped[skip.reason] = skipped.get(skip.reason, 0) + 1
                    continue
                except (DomainContractError, DesignPersistenceError, KeyError, TypeError, ValueError):
                    skipped["unreadable"] = skipped.get("unreadable", 0) + 1
                    continue
                entry["revision_current"] = entry["work_revision_ref"] == current
                offered.append(entry)
        runs_available = bool(self._runs_available())
        for entry in offered:
            entry["usable"] = entry["status"] == "prepared" and runs_available
            entry["unusable_reason"] = (None if entry["usable"] else
                                        "run_executor_not_configured" if not runs_available else "not_prepared")
        critic_qualifiable = bool(gate.V3_VERIFYING_DESIGN_IDS)
        return {
            "schema_version": SCHEMA,
            "work": {"work_id": work_id, "current_revision_ref": current},
            "runs": {"available": runs_available,
                     "reason": None if runs_available else "run_executor_not_configured"},
            "environments": offered,
            "unresolved": [{"reason": reason, "count": count} for reason, count in sorted(skipped.items())],
            # why nothing is offered: no approved design, and whether any critic could be qualified here
            "absence": None if offered else {
                "code": "no_prepared_environment",
                "reason": "no_approved_design",
                "critic_qualifiable": critic_qualifiable,
            },
            "consent_scope": {
                "names": ["graph_ref", "work_revision_ref", "environment_ref", "budget_policy_ref"],
                "runs": 1,
                "implies_not": ["external_write", "billing_change", "promotion"],
            },
        }
