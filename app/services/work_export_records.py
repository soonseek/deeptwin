"""The design and growth records one work's export carries (US7, T074).

Two record families are collected for a work, metadata only — identities, versions,
digests, closed codes, times and the names of the actors that produced them, never a
graph body, a model response, a node result or owner text:

- **Design** (`design_requests`). A design request names its common-work target by the
  content hash of a work model (`work_model_ref`); a stored `work_model` record names the
  exact work revision it was drafted from (`work_revision_ref`, a real store edge). A
  request belongs to this work exactly when its `work_model_ref` equals the design ref of
  a `work_model` record whose revision is a revision of this work. Under each request the
  store's own lineage (`domain_edges`) is followed: request -> generation calls ->
  candidates -> recorded criticism and owner derivations -> derived candidates -> their
  criticism; design approvals are matched by the candidate they approve. A verdict is
  exported AS RECORDED — the stored status and reasons with the critic identities its
  call records name — and says so (`basis: recorded`, `re_verified_by_export: false`):
  re-folding it needs the issued request, which the store cannot rebuild.
- **Lenses** (`lenses`). Every lens a candidate audited (`audit_lens_refs`) or a critic
  used (`lens_use`) is resolved against the reviewed lens bundle
  (`docs/lenses/*.md`, `LensRegistry.from_markdown`): its definition and review state
  when the exact version/hash is the loaded one, otherwise the stated mismatch.
- **Growth rounds** (`growth_rounds`). A comparison round is not bound to a work: it pairs
  isolated runs of a frozen comparison plan over one baseline ENVIRONMENT. Scope rule: a
  round belongs to this work's export exactly when its plan's `baseline_environment` is
  (id, version, sha256) the environment one of this work's runs ran in. Every other
  round is outside the scope and only counted. With a round come the experiment (the
  lineage's newest loop revision), its per-item outcomes and isolation boundaries (G-14,
  when the round involved tool effects) and what each side's nodes changed — node ids,
  never node results.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.refs import EntityRef, canonical_json
from .design import confirm_work_model
from .design_persistence import decode_design_refs
from .growth_store import (
    RECORD_KIND,
    GrowthStoreError,
    resume_comparison_round_record,
    resume_loop,
    resume_round_item_outcomes,
    resume_round_outputs,
)

__all__ = ["DesignRecords", "RoundRecords", "collect_design_records", "collect_rounds", "lens_view"]

MAX_REQUESTS = 64
MAX_CHILDREN = 256
MAX_ROUNDS = 256
MAX_LINEAGES = 64
LENS_ROOT = Path(__file__).resolve().parents[2] / "docs" / "lenses"
_EFFECT_KEYS = ("tool_id", "version", "effect_class", "boundary", "tool_call_sha256", "inputs_digest")


class DesignRecords(tuple):
    """(requests, lens references) — a named pair for readability."""


class RoundRecords(tuple):
    """(rounds in scope, experiments, rounds out of scope)."""


def _load(domain, db, roots, kind, identifier, version, sha):
    return domain._load(db, EntityRef(kind, identifier, version, sha), roots)[0]


def _children(domain, db, roots, ref, kind, design_kind):
    rows = db.execute(
        "SELECT DISTINCT r.kind, r.id, r.version, r.sha256 FROM domain_edges e JOIN domain_records r "
        "ON r.vault_id=e.vault_id AND r.kind=e.source_kind AND r.id=e.source_id AND r.version=e.source_version "
        "WHERE e.vault_id=? AND e.target_kind=? AND e.target_id=? AND e.target_version=? "
        "AND e.target_sha256=? AND e.source_kind=? ORDER BY r.id, r.version LIMIT ?",
        (roots.genesis.id, ref.kind, ref.id, ref.version, ref.sha256, kind, MAX_CHILDREN + 1)).fetchall()
    if len(rows) > MAX_CHILDREN:
        raise ValueError("too many design children")
    found = []
    for row in rows:
        record = _load(domain, db, roots, row["kind"], row["id"], row["version"], row["sha256"])
        content = record.body.get("content")
        if type(content) is dict and content.get("design_kind") == design_kind:
            found.append((record, decode_design_refs(content["design"])))
    return found


def _tagged(domain, db, roots, needle, *, limit, version_one=False):
    rows = db.execute(
        "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='decision_record' "
        + ("AND version=1 " if version_one else "") + "AND instr(body, ?) > 0 ORDER BY id, version LIMIT ?",
        (roots.genesis.id, needle, limit + 1)).fetchall()
    if len(rows) > limit:
        raise ValueError("too many records")
    return [_load(domain, db, roots, "decision_record", row["id"], row["version"], row["sha256"]) for row in rows]


def _work_model_refs(domain, db, roots, work_id):
    """The design refs of every stored work model drafted from a revision of this work."""

    refs = {}
    for row in db.execute(
            "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind='work_model' "
            "AND instr(body, ?) > 0 ORDER BY id, version LIMIT ?",
            (roots.genesis.id, work_id.encode(), MAX_REQUESTS + 1)).fetchall():
        record = _load(domain, db, roots, "work_model", row["id"], row["version"], row["sha256"])
        content = record.body["content"]
        revision = content.get("work_revision_ref") if type(content) is dict else None
        if type(revision) is not dict or revision.get("kind") != "work_revision" or revision.get("id") != work_id:
            continue
        target = confirm_work_model(content, None)
        refs[canonical_json(target.work_model_ref.as_dict())] = {
            "work_model_id": record.ref.id, "work_revision": revision["version"]}
    return refs


def _verdict(criticisms):
    if not criticisms:
        return None
    record, design = criticisms[0]
    calls = design.get("call_records") or []
    verdict = design["verdict"]
    lens_use = design.get("lens_use") or {}
    return {
        "basis": "recorded", "re_verified_by_export": False,
        "status": verdict["status"], "reasons": list(verdict["reasons"]),
        "critic": {"model_ids": sorted({item["model_id"] for item in calls}),
                   "profile_digests": sorted({item["profile_digest"] for item in calls}),
                   "call_count": len(calls), "purposes": [item["purpose"] for item in calls]},
        "criticism_record_id": record.ref.id, "recorded_at_utc": record.body["created_at_utc"],
        "lens_use": {"proposal_status": lens_use.get("proposal_status"),
                     "rules": [{"rule_id": rule["rule_id"], "rule_version": rule["rule_version"],
                                "status": rule["status"]} for rule in lens_use.get("rules", [])]},
        "criticism_count": len(criticisms),
    }


def _candidate(domain, db, roots, record, stored, lenses, *, derivation_id=None):
    criticisms = _children(domain, db, roots, record.ref, "decision_record", "candidate_criticism")
    verdict = _verdict(criticisms)
    for ref in stored.get("audit_lens_refs", []):
        lenses.setdefault(("audit", ref), None)
    if verdict is not None:
        for rule in verdict["lens_use"]["rules"]:
            lenses.setdefault(("use", f"{rule['rule_id']}@{rule['rule_version']}"), None)
    graph = stored["graph_ref"]
    return {
        "candidate_id": stored["candidate_id"], "version": stored["version"],
        "recorded_at_utc": record.body["created_at_utc"],
        "graph": {"graph_id": graph["id"], "version": graph["version"], "graph_sha256": graph["sha256"],
                  "content": "그래프 본문 미포함"},
        "parent_candidate_ids": [item["id"] for item in stored.get("parent_candidate_refs", [])],
        "generation_call_ids": [item["id"] for item in stored.get("generation_call_refs", [])],
        "applied_effect_ids": list(stored.get("applied_effect_ids", [])),
        "audit_lens_refs": list(stored.get("audit_lens_refs", [])),
        "derived_by": derivation_id,
        "verdict": verdict,
    }


def collect_design_records(domain, db, roots, work_id):
    """(requests, referenced lens keys) for this work, deterministically ordered."""

    models = _work_model_refs(domain, db, roots, work_id)
    if not models:
        return DesignRecords(([], {}))
    lenses, requests = {}, []
    approvals = [decode_design_refs(record.body["content"]["design"]) | {"_at": record.body["created_at_utc"],
                                                                         "_id": record.ref.id}
                 for record in _tagged(domain, db, roots, b'"design_kind":"design_approval_record"',
                                       limit=MAX_REQUESTS * 4)]
    for record in _tagged(domain, db, roots, b'"design_kind":"design_generation_request"', limit=MAX_REQUESTS):
        content = record.body["content"]
        if content.get("design_kind") != "design_generation_request":
            continue
        design = decode_design_refs(content["design"])
        target = models.get(canonical_json(design["work_model_ref"]))
        if target is None:
            continue
        calls, candidates, derivations = [], [], []
        for call, call_design in _children(domain, db, roots, record.ref, "decision_record",
                                           "design_generation_call"):
            calls.append({"call_id": call.ref.id, "generator_model_id": call_design["model_id"],
                          "purpose": call_design["purpose"], "profile_digest": call_design["profile_digest"],
                          "recorded_at_utc": call.body["created_at_utc"]})
            for child, stored in _children(domain, db, roots, call.ref, "design_candidate", "design_candidate"):
                candidates.append(_candidate(domain, db, roots, child, stored, lenses))
                for derivation, derived in _children(domain, db, roots, child.ref, "decision_record",
                                                     "design_derivation"):
                    if any(item["derivation_id"] == derivation.ref.id for item in derivations):
                        continue
                    derivations.append({
                        "derivation_id": derivation.ref.id, "action": derived["action"],
                        "parent_candidate_ids": list(derived["parent_candidate_ids"]),
                        "instruction": None if derived["instruction"] is None else "지시 내용 미포함",
                        "instruction_characters": None if derived["instruction"] is None
                        else len(derived["instruction"]),
                        "re_review_required": derived["re_review_required"],
                        "inherited_verdict": derived["inherited_verdict"],
                        "recorded_at_utc": derivation.body["created_at_utc"], "actor": "owner",
                    })
                    for grandchild, again in _children(domain, db, roots, derivation.ref, "design_candidate",
                                                       "design_candidate"):
                        candidates.append(_candidate(domain, db, roots, grandchild, again, lenses,
                                                     derivation_id=derivation.ref.id))
        ids = {(item["candidate_id"], item["version"]) for item in candidates}
        approved = [{"approval_record_id": item["_id"], "candidate_id": item["candidate_id"],
                     "candidate_version": item["candidate_version"], "environment_id": item["environment_id"],
                     "verdict_sha": item["verdict_sha"], "approved_at": item["approved_at"],
                     "approver": "owner",
                     "critic_qualification": {key: item["critic_qualification"].get(key)
                                              for key in ("status", "reason")}}
                    for item in approvals if (item["candidate_id"], item["candidate_version"]) in ids]
        requests.append({
            "request_id": design["request_id"], "version": design["version"],
            "recorded_at_utc": record.body["created_at_utc"],
            "work_model_id": target["work_model_id"], "work_revision": target["work_revision"],
            "requested_candidate_count": design["requested_candidate_count"],
            "design_disposition": design["design_disposition"],
            "generation_calls": sorted(calls, key=lambda item: (item["recorded_at_utc"], item["call_id"])),
            "candidates": sorted(candidates, key=lambda item: (item["derived_by"] or "", item["candidate_id"])),
            "derivations": sorted(derivations, key=lambda item: (item["recorded_at_utc"], item["derivation_id"])),
            "design_approvals": sorted(approved, key=lambda item: (item["approved_at"], item["approval_record_id"])),
        })
    return DesignRecords((sorted(requests, key=lambda item: (item["recorded_at_utc"], item["request_id"])), lenses))


_REGISTRY = []


def _registry():
    if not _REGISTRY:
        from .lenses import LensRegistry

        try:
            _REGISTRY.append(LensRegistry.from_markdown(LENS_ROOT / "definition-candidates.md",
                                                        LENS_ROOT / "composition-contract.md"))
        except Exception:  # noqa: BLE001 - the bundle is absent or differs: stated per lens
            _REGISTRY.append(None)
    return _REGISTRY[0]


_DEFINITION_FIELDS = (
    "neutral_name", "source_scope", "atomic_claim", "counter_reading", "functional_layers", "route_contract",
    "applicability", "non_applicability", "abstention_condition", "distinguishing_question",
    "expected_contrast", "disconfirmation", "confounders_and_prohibitions", "engineering_translation",
    "no_change_condition")
_STATUS_FIELDS = ("document_review_status", "scholarly_review_status", "effect_status", "adoption_status")


def lens_view(keys) -> list:
    """Each referenced lens resolved against the reviewed bundle, by (id, version)."""

    registry = _registry()
    grouped = {}
    for source, text in keys:
        head, _, digest = text.partition("#")
        lens_id, _, version = head.partition("@")
        entry = grouped.setdefault((lens_id, version), {"lens_id": lens_id, "version": version,
                                                        "referenced_hashes": set(), "referenced_by": set()})
        if digest:
            entry["referenced_hashes"].add(digest)
        entry["referenced_by"].add({"audit": "candidate_audit", "use": "criticism_lens_use"}[source])
    found = []
    for (lens_id, version), entry in sorted(grouped.items()):
        view = {"lens_id": lens_id, "version": version, "referenced_by": sorted(entry["referenced_by"]),
                "referenced_content_hashes": sorted(entry["referenced_hashes"])}
        definition = None
        if registry is None:
            view["definition_state"] = "registry_unavailable"
        else:
            try:
                definition = registry.get(lens_id)
            except Exception:  # noqa: BLE001 - an id this bundle does not have
                definition = None
            if definition is None:
                view["definition_state"] = "not_in_bundle"
            elif definition.ref.version != version or any(
                    digest != definition.ref.content_hash for digest in entry["referenced_hashes"]):
                view["definition_state"] = "differs_from_bundle"
                view["bundle_ref"] = str(definition.ref)
                definition = None
            else:
                view["definition_state"] = "current"
                view["registry_bundle_id"] = registry.bundle_id
                view["content_hash"] = definition.ref.content_hash
        if definition is not None:
            view["definition"] = {name: getattr(definition, name) for name in _DEFINITION_FIELDS}
            view["review"] = {name: getattr(definition, name) for name in _STATUS_FIELDS}
        found.append(view)
    return found


# --- growth rounds ---------------------------------------------------------------------

def _effects(values):
    return [{key: item[key] for key in _EFFECT_KEYS if key in item} for item in values or ()]


def _item_outcomes(values):
    if values is None:
        return None
    return [{"item_index": item["item_index"], "outcome": item["outcome"], "reasons": list(item["reasons"]),
             "past_tool_effects": _effects(item.get("past_tool_effects")),
             "baseline_effects": _effects(item.get("baseline_effects")),
             "candidate_effects": _effects(item.get("candidate_effects"))} for item in values]


def collect_rounds(domain, db, roots, environment_refs):
    """(rounds in scope, their experiments, count of rounds outside the scope)."""

    wanted = {canonical_json(ref) for ref in environment_refs}
    rows = db.execute(
        "SELECT id, version, sha256 FROM domain_records WHERE vault_id=? AND kind=? AND version=1 "
        "AND instr(body, ?) > 0 ORDER BY id LIMIT ?",
        (roots.genesis.id, RECORD_KIND, b'"growth_kind":"growth_comparison_round"', MAX_ROUNDS + 1)).fetchall()
    if len(rows) > MAX_ROUNDS:
        raise ValueError("too many rounds")
    rounds, outside, unreadable, lineages = [], 0, 0, set()
    for row in rows:
        ref = EntityRef(RECORD_KIND, row["id"], row["version"], row["sha256"])
        try:
            plan, result = resume_comparison_round_record(domain, ref)
        except GrowthStoreError:
            unreadable += 1  # a round that does not read back cannot be scoped: counted, never shown
            continue
        baseline = plan.baseline_environment.as_dict()
        if canonical_json(baseline) not in wanted:
            outside += 1
            continue
        value = result.as_dict()
        try:
            outputs = resume_round_outputs(domain, ref)
            outcomes = resume_round_item_outcomes(domain, ref)
            outputs_state = "recorded" if outputs is not None else "not_recorded"
        except GrowthStoreError:
            outputs, outcomes, outputs_state = None, None, "unreadable"
        lineages.add(plan.lineage_id)
        rounds.append({
            "round_record_id": ref.id, "lineage_id": plan.lineage_id, "plan_mode": plan.mode,
            "baseline_environment": {"id": baseline["id"], "version": baseline["version"]},
            "tool_effect_policy_id": plan.tool_effect_policy.id,
            "round_id": value["round_id"], "round_index": value["round_index"],
            "candidate_ref": {"kind": value["candidate_ref"]["kind"], "id": value["candidate_ref"]["id"],
                              "version": value["candidate_ref"]["version"]},
            "pair_count": len(value["baseline_run_refs"]),
            "validity": value["validity"], "validity_reasons": list(value["validity_reasons"]),
            "metric_vector": value["metric_vector"], "utility": value["utility"],
            "outputs_state": outputs_state,
            "outputs": None if outputs is None else [
                {"item_index": item["item_index"], "changed_nodes": list(item["changed_nodes"]),
                 "unexplained_nodes": list(item["unexplained_nodes"]), "node_results": "노드 결과 내용 미포함"}
                for item in outputs],
            "item_outcomes": _item_outcomes(outcomes),
            "item_outcomes_state": "recorded" if outcomes is not None else (
                "no_tool_effects" if outputs_state == "recorded" else outputs_state),
        })
    rounds.sort(key=lambda item: (item["lineage_id"], item["round_index"], item["round_record_id"]))
    experiments = []
    if lineages:
        heads = db.execute(
            "SELECT id, MAX(version) AS version FROM domain_records WHERE vault_id=? AND kind=? "
            "AND instr(body, ?) > 0 GROUP BY id ORDER BY id LIMIT ?",
            (roots.genesis.id, RECORD_KIND, b'"growth_kind":"growth_loop_state"', MAX_LINEAGES + 1)).fetchall()
        for row in heads:
            digest = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind=? AND id=? AND version=?",
                                (roots.genesis.id, RECORD_KIND, row["id"], row["version"])).fetchone()
            try:
                loop = resume_loop(domain, EntityRef(RECORD_KIND, row["id"], row["version"], digest["sha256"])).as_dict()
            except GrowthStoreError:
                continue
            if loop["lineage_id"] not in lineages:
                continue
            experiments.append({key: loop[key] for key in (
                "lineage_id", "revision", "status", "floor_reached", "best_observed", "progress_reference",
                "non_improving_valid_count", "completed_round_ids", "consumed_budget", "stop_reason")})
    return RoundRecords((rounds, sorted(experiments, key=lambda item: item["lineage_id"]),
                         {"outside_scope": outside, "unreadable": unreadable}))
