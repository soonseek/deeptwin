"""The `environment` entity record a run names (the design line's last missing
producer; resumption-plan Continuation "the design line records a run consent and
an environment").

`POST /api/v1/runs` and the consent route both require a stored record of kind
`environment`; the design arc persisted only its chained `decision_record` head
(`design_store.persist_environment_head`), so every test fabricated
`{"fixture": "environment"}`. `persist_environment_record` seals one immutable
`environment` record per prepared version — the environment id, the version, the
design the owner approved, the approval digest, the prepared status and the exact
head record it was cut from — content-addressed, so re-persisting the same
preparation is the same record and never a second act. data-model.md §3
(`EnvironmentVersion` carries its design; prepared is never active) and
experience.md §6.3 (`업무 시작` fixes the input and environment version).
"""

from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.services.design_persistence import decode_design_refs
from app.services.design_store import (
    DesignStoreError,
    persist_design_approval,
    persist_environment_head,
    persist_environment_record,
    resume_environment_state,
)
from app.services.environments import prepare_environment_version
from app.tests.test_design_store import headers, prepared_flow
from app.tests.test_design_store import (
    vault as vault,  # noqa: PLC0414 - the fixture, re-exported
)
from app.tests.test_environments import (  # noqa: F401 - design_owner is an autouse fixture
    SESSION,
    design_owner,
)


@pytest.fixture
def decisions():
    return SESSION.decisions()


def persisted(domain, roots, decisions):
    """One prepared head and its `environment` record, through the real producers."""
    approval, other, _state, version, state2 = prepared_flow()
    approval_ref = persist_design_approval(domain, approval, decisions=decisions, **headers(roots))
    head_ref = persist_environment_head(domain, version, state2, parent_ref=None,
                                        approval_ref=approval_ref, **headers(roots))
    environment_ref = persist_environment_record(domain, version, head_ref=head_ref, **headers(roots))
    return approval, other, state2, version, head_ref, environment_ref


def test_a_prepared_version_is_sealed_as_the_environment_a_run_can_name(vault, decisions):
    domain, roots = vault
    _approval, _other, _state, version, head_ref, environment_ref = persisted(domain, roots, decisions)
    assert environment_ref.kind == "environment" and environment_ref.version == version.version
    record = domain.get(environment_ref)
    content = decode_design_refs(record.body["content"])
    assert content == {
        "schema_version": "environment-record-v1",
        "environment_id": version.environment_id,
        "version": version.version,
        "design_ref": version.design_ref.as_dict(),
        "approval_sha": version.approval_sha,
        "status": "prepared",
    }
    assert record.body["parent_refs"] == [head_ref.as_dict()]  # cut from the exact head
    # the same preparation is the same record: an identical re-persist is idempotent
    again = persist_environment_record(domain, version, head_ref=head_ref, **headers(roots))
    assert again == environment_ref
    # the head still resumes its own state: the entity record is beside the chain, not it
    assert resume_environment_state(domain, head_ref).head == version.version


def test_the_second_prepared_version_is_its_own_environment_record(vault, decisions):
    domain, roots = vault
    _approval, other, state2, _version, head_ref, first = persisted(domain, roots, decisions)
    second_version, _state3 = prepare_environment_version(state2, other, expected_head=state2.head)
    second_head = persist_environment_head(domain, second_version, _state3, parent_ref=head_ref,
                                           approval_ref=None, **headers(roots))
    second = persist_environment_record(domain, second_version, head_ref=second_head, **headers(roots))
    assert second.id == first.id and second.version == 2  # one environment, its versions
    assert decode_design_refs(domain.get(second).body["content"])["design_ref"] == second_version.design_ref.as_dict()
    assert decode_design_refs(domain.get(first).body["content"])["version"] == 1  # untouched


def test_only_a_prepared_version_with_its_own_head_is_sealed(vault, decisions):
    domain, roots = vault
    _approval, _other, _state, version, head_ref, _ref = persisted(domain, roots, decisions)
    for bad in (None, version.as_dict(), "environment"):  # never a look-alike
        with pytest.raises(DesignStoreError):
            persist_environment_record(domain, bad, head_ref=head_ref, **headers(roots))
    for bad_head in (None, head_ref.as_dict(),
                     EntityRef(head_ref.kind, str(uuid4()), head_ref.version, head_ref.sha256),
                     EntityRef(head_ref.kind, head_ref.id, 2, head_ref.sha256),
                     EntityRef("graph", head_ref.id, head_ref.version, head_ref.sha256)):
        with pytest.raises(DesignStoreError):
            persist_environment_record(domain, version, head_ref=bad_head, **headers(roots))


# --- review closures ----------------------------------------------------------------------

def test_a_record_names_only_the_preparation_its_own_head_holds(vault, decisions):
    domain, roots = vault
    # two approvals over one environment, each prepared from the same head: two version-1
    # preparations of different designs. The head sealed first is the one that happened;
    # a record claiming the other design must not be sealed beside it.
    approval, other, state, _version, _state2 = prepared_flow()
    mine, _ = prepare_environment_version(state, approval, expected_head=state.head)
    theirs, theirs_state = prepare_environment_version(state, other, expected_head=state.head)
    head = persist_environment_head(domain, theirs, theirs_state, parent_ref=None,
                                    approval_ref=None, **headers(roots))
    assert mine.design_ref != theirs.design_ref and mine.version == theirs.version
    with pytest.raises(DesignStoreError):
        persist_environment_record(domain, mine, head_ref=head, **headers(roots))
    # the head's own preparation seals, and a second writer's different design at the same
    # identity loses the compare-and-swap rather than forking the environment
    sealed = persist_environment_record(domain, theirs, head_ref=head, **headers(roots))
    assert decode_design_refs(domain.get(sealed).body["content"])["design_ref"] == theirs.design_ref.as_dict()


def test_a_head_reference_that_is_not_the_stored_head_is_refused(vault, decisions):
    domain, roots = vault
    _approval, _other, _state, version, head_ref, _ref = persisted(domain, roots, decisions)
    forged = EntityRef(head_ref.kind, head_ref.id, head_ref.version, "0" * 64)
    with pytest.raises(DesignStoreError):
        persist_environment_record(domain, version, head_ref=forged, **headers(roots))


def test_the_run_route_starts_a_run_under_a_persisted_environment_record(tmp_path):
    # the point of the record: the run route resolves it as the run's own environment,
    # and the design arc's own head record is refused in that slot
    from app.tests.test_graph_execution import linear_graph
    from app.tests.test_runs_api import Executor, command, graph_record
    from app.tests.test_runs_api import owner_app as run_app
    from app.tests.test_web_owner_integration import headers as http_headers

    executor = Executor()
    with run_app(tmp_path, executor) as subject:
        domain = subject.domain
        roots = domain.roots()
        _approval, _other, _state, version, state2 = prepared_flow()
        head = persist_environment_head(domain, version, state2, parent_ref=None,
                                        approval_ref=None, **headers(roots))
        environment = persist_environment_record(domain, version, head_ref=head, **headers(roots))
        subject.refs.environment = environment
        graph = graph_record(subject, linear_graph())
        started = subject.client.post(subject.path, headers=http_headers(subject.profile, subject.csrf),
                                      json=command(subject, graph))
        assert started.status_code == 201, started.text
        assert started.json()["phase"] == "completed"
        # the chained head is a design record, never the environment a run may name
        subject.refs.environment = head
        refused = subject.client.post(subject.profile.base_path + "api/v1/run-consents",
                                      headers=http_headers(subject.profile, subject.csrf),
                                      json={"schema_version": "run-consent-command-v1",
                                            "command_id": str(uuid4()),
                                            "graph_ref": graph.as_dict(),
                                            "work_revision_ref": subject.refs.work.as_dict(),
                                            "environment_ref": head.as_dict(),
                                            "budget_policy_ref": subject.refs.budget.as_dict()})
        assert refused.status_code == 400 and refused.json()["code"] == "invalid_input"
