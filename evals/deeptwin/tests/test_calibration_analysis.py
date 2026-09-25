"""T035: the recorded calibration result yields honest abstention/joint-error/alternative counts."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAL = ROOT / "evals/deeptwin/qualification/calibration"


def _analyze():
    spec = importlib.util.spec_from_file_location("analyze_observed", CAL / "analyze_observed.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.analyze(json.loads((CAL / "observed/run-2-continued-results.json").read_text()))


def test_the_complete_tuned_calibration_counts_are_derived_from_the_recorded_verdicts():
    result = _analyze()
    assert result["trials"] == 10 and result["output_contract_failures"] == ["c86/ce-17"]
    assert (result["review_findings"], result["unresolved_findings"]) == (72, 15)
    assert result["unresolved_where_a_decision_was_expected"] == 2
    assert result["abstained_proposals"] == 0 and result["proposal_stages"] == 9
    assert [verdict for _name, verdict in result["valid_alternative_cases"]] == ["pass", "pass"]
    errors = {row["trial"]: row for row in result["critic_semantic_errors"]}
    assert set(errors) == {"c71/ce-17", "c42/ce-43", "c18/-"}
    # only c18's error has a judge item on the same criterion, and the judge disagreed
    assert [name for name, row in errors.items() if row["measurable"]] == ["c18/-"]
    assert not any(row["joint_error"] for row in errors.values())
    assert result["independence_established"] is False
