"""Run-level cancellation in the ledger (api.md Runtime row: cancel; runtime.md
§: cancellation first durably closes the dispatch gate). `cancel_run` is a
replayable command that moves the run to `cancelled` (a durable phase, not a
projection) so no new execution or attempt of the run can be admitted;
`attempts_for_run` is the read-only enumerator the service uses to close the
gates of the run's live attempts. Neither claims that any remote computation
stopped.
"""

import pytest

from app.runtime.ledger import DispatchBlocked, ExecutionSpec
from app.tests.test_runtime_budget_dispatch import identifier, opened, prepare


def test_cancel_run_is_a_replayable_command_that_closes_the_run(tmp_path):
    subject = opened(tmp_path)
    _owner, attempt, _request, _ = prepare(subject)
    run_id = subject.ledger.get_execution(attempt.execution_id)["spec"]["run_id"]
    assert subject.ledger.get_run(run_id)["phase"] == "created"
    command = identifier()
    first = subject.ledger.cancel_run(command, run_id)
    assert first["applied"] is True
    assert first["run"]["phase"] == "cancelled" and first["run"]["revision"] == 2
    assert subject.ledger.get_run(run_id)["phase"] == "cancelled"
    assert subject.ledger.get_run(run_id)["revision"] == 2
    # exact replay returns the stored result; a fresh command is honest about no change
    assert subject.ledger.cancel_run(command, run_id) == first
    again = subject.ledger.cancel_run(identifier(), run_id)
    assert again["applied"] is False and again["run"]["phase"] == "cancelled"
    assert subject.ledger.get_run(run_id)["revision"] == 2
    with pytest.raises(KeyError):
        subject.ledger.cancel_run(identifier(), identifier())
    # the existing attempt is untouched by the run command: closing its gate is
    # the service's explicit, per-attempt request_cancel
    stored = subject.ledger.get_attempt(attempt.attempt_id)
    assert stored["cancel_state"] == "none" and stored["dispatch_gate"] == "open"
    # a cancelled run admits no new execution
    with pytest.raises(DispatchBlocked):
        subject.ledger.create_execution(
            identifier(), ExecutionSpec(identifier(), run_id, "publish", identifier(), (0,), ())
        )
    # startup reconciliation and the run readers still accept the cancelled row
    subject.ledger.reconcile_startup(identifier(), observed_owners={})
    assert subject.ledger.get_run(run_id)["phase"] == "cancelled"
    assert [item["spec"]["node_id"] for item in subject.ledger.executions_for_run(run_id)] == ["writer"]


def test_attempts_for_run_enumerates_every_attempt_of_the_run(tmp_path):
    subject = opened(tmp_path)
    _owner, attempt, _request, _ = prepare(subject)
    run_id = subject.ledger.get_execution(attempt.execution_id)["spec"]["run_id"]
    listed = subject.ledger.attempts_for_run(run_id)
    assert [item["spec"]["attempt_id"] for item in listed] == [attempt.attempt_id]
    assert listed[0]["phase"] == "reserved" and listed[0]["cancel_state"] == "none"
    _other, other_attempt, _, _ = prepare(subject)  # another run
    other_run = subject.ledger.get_execution(other_attempt.execution_id)["spec"]["run_id"]
    assert [item["spec"]["attempt_id"] for item in subject.ledger.attempts_for_run(other_run)] == [other_attempt.attempt_id]
    assert len(subject.ledger.attempts_for_run(run_id)) == 1
    with pytest.raises(KeyError):
        subject.ledger.attempts_for_run(identifier())
