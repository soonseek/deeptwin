"""One owner-authorized LIVE design-candidate generation through the product boundary.

Runs only with `DEEPTWIN_LIVE_ANTHROPIC_API_KEY` and `DEEPTWIN_LIVE_DESIGN=1`; never in
the ordinary suite. It sends the framework's real generation prompt for the reviewed
fixture request (a confirmed work model, one qualified lens decision whose effect carries
its exact value, and a compilation authority) through `ClaudeRunExecutor.model_turn`, and
admits the answer only through `run_candidate_generation`. One Messages call, capped by
`DEEPTWIN_LIVE_DESIGN_MAX_TOKENS` (default 16000). The outcome, accepted or refused, is
written as non-secret evidence to `DEEPTWIN_LIVE_EVIDENCE_PATH`.
"""

import json
import os

import pytest

from app.services.design_live import run_candidate_generation
from app.services.claude_run_executor import DESIGN_INTENT_SCHEMA, OUTCOME_SCHEMA, ClaudeRunExecutor, LiveLimits
from app.tests.test_claude_design_turn import records
from app.tests.test_claude_live_path import claude
from app.tests.test_design_generation import prepared
from app.tests.test_runs_api import owner_app

KEY = os.environ.get("DEEPTWIN_LIVE_ANTHROPIC_API_KEY")
MODEL = os.environ.get("DEEPTWIN_LIVE_MODEL", "claude-opus-5")
EVIDENCE = os.environ.get("DEEPTWIN_LIVE_EVIDENCE_PATH")
MAX_TOKENS = int(os.environ.get("DEEPTWIN_LIVE_DESIGN_MAX_TOKENS", "16000"))

pytestmark = pytest.mark.skipif(not KEY or os.environ.get("DEEPTWIN_LIVE_DESIGN") != "1",
                                reason="live design needs the key and DEEPTWIN_LIVE_DESIGN=1")


def test_one_live_design_generation_through_the_framework_boundary(tmp_path):
    executor = ClaudeRunExecutor(limits=LiveLimits(max_model_calls=1, max_design_output_tokens=MAX_TOKENS))
    with owner_app(tmp_path, executor) as subject:
        assert claude(subject, "key", {"secret": KEY}).status_code == 200
        assert claude(subject, "catalog").status_code == 200
        # one candidate per call keeps a generation inside the contract's 180 s call
        # deadline; supplementation rounds, not one long call, fill a pool
        _target, _lens, _decision, request, _graph = prepared(carry_value=True, candidate_count=1)
        live_turn = executor.model_turn(MODEL, purpose="design_candidate")
        raw = []

        def turn(system, user):  # keeps the model's own text for the refusal analysis
            raw.append(live_turn(system, user))
            if EVIDENCE:
                with open(EVIDENCE + ".response.json", "w", encoding="utf-8") as handle:
                    handle.write(raw[-1])
            return raw[-1]

        observed = {"model": MODEL, "requested_candidates": request.requested_candidate_count}
        try:
            result = run_candidate_generation(request, model_turn=turn, model_id=MODEL)
            observed["accepted"] = [
                {"graph_digest": item.graph_ref.sha256,
                 "nodes": [(node.node_id, node.kind) for node in item.graph.nodes],
                 "applied_effect_ids": list(item.applied_effect_ids)}
                for item in result.candidates]
        except Exception as exc:  # any refusal or crash is evidence, never hidden
            cause = exc.__cause__
            observed["refused"] = {"error": type(exc).__name__, "message": str(exc),
                                   "cause": None if cause is None else f"{type(cause).__name__}: {cause}"}
        [outcome] = records(subject, OUTCOME_SCHEMA)
        observed["call"] = {key: outcome[key] for key in ("provider_message_id", "state", "stop_reason", "usage")}
        observed["intent"] = records(subject, DESIGN_INTENT_SCHEMA)[0]
        if EVIDENCE:
            with open(EVIDENCE, "w", encoding="utf-8") as handle:
                json.dump(observed, handle, ensure_ascii=False, indent=2)
        assert KEY not in json.dumps(observed)
        assert observed.get("accepted"), observed.get("refused")
