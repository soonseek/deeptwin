"""T038 attempt 5: the simulated owner's well-specified work (`design_specified_work`) is a
valid confirmed work over a real saved work and stored original, its decision is accepted,
and the generation prompt carries its explicit conditions and the verifier effect. Offline."""

import json
from uuid import NAMESPACE_URL, uuid5

from app.services.design import create_generation_request
from app.services.design_live import render_candidate_prompt
from app.tests.design_specified_work import (
    COMPLETION_CONDITIONS,
    SOURCE_TEXT,
    VERIFIER_RESPONSIBILITY,
    WORK_TEXT,
    specified_decision,
    specified_work_model,
    specified_work_with_source,
)
from app.tests.test_design_generation import design_authority, proposed_lens
from app.tests.test_runs_api import Executor, owner_app


def test_the_specified_work_is_confirmed_and_reaches_the_generation_prompt(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        revision, sources = specified_work_with_source(subject)
        domain = subject.app.state.domain_store
        target = specified_work_model(domain, revision, sources)
        assert target.state == "confirmed" and target.design_disposition == "multi_agent"
        assert target.blocked_unknown_ids == () and target.work_model.unknowns == ()
        assert list(target.work_model.completion_conditions) == COMPLETION_CONDITIONS
        registry, lens = proposed_lens(target)
        decision = specified_decision(target, registry, lens)
        request = create_generation_request(
            target, [decision], request_id=str(uuid5(NAMESPACE_URL, f"deeptwin:attempt5-offline:{revision.id}")),
            requested_candidate_count=2, compilation_authority=design_authority())
        _system, user = render_candidate_prompt(request)
        payload = json.loads(user)
        assert payload["work_model"]["completion_conditions"] == COMPLETION_CONDITIONS
        assert payload["required_effects"] == [{
            "effect_id": "verifier-responsibility",
            "target": {"kind": "node", "id": "verifier", "field": "responsibility"},
            "expected_value": VERIFIER_RESPONSIBILITY}]
    # labelled as the simulated owner's, and a different scenario from attempts 1-4
    assert WORK_TEXT.startswith("[시험 행위자(가상 소유자)") and "공개: 아니오" in SOURCE_TEXT
    assert "유튜브" not in WORK_TEXT + "".join(COMPLETION_CONDITIONS)
