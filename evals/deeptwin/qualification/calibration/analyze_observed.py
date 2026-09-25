"""T035: derive abstention, valid-alternative and critic/judge joint-error counts from a
recorded calibration result file, without re-running anything or reading raw outputs.

Every number comes from the verifier's own rule checks and judge items in the file. Counts
carry their real denominators, and no rate or guarantee is inferred. The critic and the judge
share a model here, so a critic/judge agreement is not independent evidence.

    python evals/deeptwin/qualification/calibration/analyze_observed.py \
        evals/deeptwin/qualification/calibration/observed/run-2-continued-results.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Criteria where the frozen calibration expectations admit `unresolved` for every case.
_UNRESOLVED_ALLOWED = frozenset({"Q5", "Q6", "Q7", "Q8"})


def analyze(results: dict) -> dict:
    review_findings = unresolved = unresolved_where_expected_decided = 0
    proposals = abstained_proposals = 0
    critic_semantic_errors = []
    judge_items = judge_not_supported = 0
    valid_alternatives = []
    contract_failures = []
    for trial in results["trials"]:
        key = trial["case_key"]
        name = f"{key['candidate_id']}/{key['counterexample_id'] or '-'}"
        verifier = trial.get("verifier_result") or {}
        checks = verifier.get("rule_checks") or []
        items = verifier.get("judge_items") or []
        if trial.get("cause") == "output_contract":
            contract_failures.append(name)
            continue
        for check in checks:
            parts = check["id"].split(":")
            if parts[0] == "review" and parts[2] == "status":
                review_findings += 1
                if check.get("detail") == "unresolved":
                    unresolved += 1
                    if parts[1] not in _UNRESOLVED_ALLOWED:
                        unresolved_where_expected_decided += 1
            if not check["ok"] and check["id"].endswith(":status"):
                critic_semantic_errors.append((name, check["id"], check.get("detail")))
        chains = [item for item in items if item["id"].startswith("proposed_chain_supported:")]
        proposals += 1
        if not chains:
            abstained_proposals += 1
        judge_items += len(items)
        judge_not_supported += sum(item["status"] == "not_supported" for item in items)
        if trial["boundary"] == "accept_without_false_rejection":
            valid_alternatives.append((name, trial["verdict"]))
    flagged = []
    for name, check, detail in critic_semantic_errors:
        trial = next(t for t in results["trials"]
                     if f"{t['case_key']['candidate_id']}/{t['case_key']['counterexample_id'] or '-'}" == name)
        criterion = check.split(":")[1].lower()
        covering = [item for item in trial["verifier_result"]["judge_items"]
                    if item["id"].startswith(criterion + "_")]
        flagged.append({
            "trial": name, "rule": check, "critic_status": detail,
            "judge_items_covering_criterion": [(i["id"], i["status"]) for i in covering],
            "joint_error": bool(covering) and all(i["status"] == "supported" for i in covering),
            "measurable": bool(covering),
        })
    return {
        "trials": len(results["trials"]),
        "output_contract_failures": contract_failures,
        "review_findings": review_findings,
        "unresolved_findings": unresolved,
        "unresolved_where_a_decision_was_expected": unresolved_where_expected_decided,
        "proposal_stages": proposals,
        "abstained_proposals": abstained_proposals,
        "critic_semantic_errors": flagged,
        "judge_items": judge_items,
        "judge_not_supported": judge_not_supported,
        "valid_alternative_cases": valid_alternatives,
        "independence_established": results.get("independence_established"),
    }


if __name__ == "__main__":
    print(json.dumps(analyze(json.loads(Path(sys.argv[1]).read_text())), indent=1, ensure_ascii=False))
