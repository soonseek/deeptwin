"""Durable design-arc persistence: approvals and environment heads (T036).

Approvals persist content-addressed (identical re-persist is idempotent,
never a second act). The environment head persists like the growth chain:
the record version IS the head, parent-chained, so two writers preparing
from the same head collide at the store instead of silently forking, and
the environments module's documented storage-CAS seam is discharged. A
resumed environment state is framework-issued and still refuses a consumed
approval; tampered payloads are refused at restore.
"""

import pytest

from app.domain.store import DomainStore
from app.services.design_store import (
    DesignStoreError,
    persist_design_approval,
    persist_environment_head,
    resume_environment_state,
)
from app.services.environments import (
    EnvironmentContractError,
    open_environment,
    prepare_environment_version,
    record_design_approval,
    restore_environment_state,
)
from app.storage import Store
from app.tests.test_design_review import pool_inputs, verdict
from app.tests.test_environments import (  # noqa: F401 - design_owner is an autouse fixture
    ENV_ID,
    approval_value,
    design_owner,
)

STAMP = "2026-09-13T09:00:00.000000Z"


@pytest.fixture
def vault(tmp_path):
    domain = DomainStore(Store(tmp_path / "vault"))
    roots = domain.initialize_vault()
    return domain, roots


def headers(roots):
    return {
        "actor_ref": roots.actor,
        "access_policy_ref": roots.access_policy,
        "retention_policy_ref": roots.retention_policy,
        "created_at_utc": STAMP,
    }


def prepared_flow():
    _request, two, three, _duplicate = pool_inputs()
    approval = record_design_approval(approval_value(two, verdict(two)))
    state = open_environment(ENV_ID)
    version, state2 = prepare_environment_version(
        state, approval, expected_head=state.head,
    )
    other = record_design_approval(approval_value(three, verdict(three)))
    return approval, other, state, version, state2


def test_the_flow_persists_resumes_and_still_refuses_replay(vault):
    domain, roots = vault
    approval, _other, _state, version, state2 = prepared_flow()
    approval_ref = persist_design_approval(domain, approval, **headers(roots))
    again = persist_design_approval(domain, approval, **headers(roots))
    assert again == approval_ref  # identical act is idempotent, not a second act
    head_ref = persist_environment_head(
        domain, version, state2, parent_ref=None,
        approval_ref=approval_ref, **headers(roots),
    )
    assert head_ref.version == 1
    resumed = resume_environment_state(domain, head_ref)
    assert resumed.as_dict() == state2.as_dict()
    with pytest.raises(EnvironmentContractError):
        # the consumed approval survives persistence: no replay after resume
        prepare_environment_version(
            resumed, approval, expected_head=resumed.head,
        )


def test_concurrent_prepares_collide_at_the_store(vault):
    domain, roots = vault
    approval, other, state, version, state2 = prepared_flow()
    approval_ref = persist_design_approval(domain, approval, **headers(roots))
    persist_environment_head(
        domain, version, state2, parent_ref=None,
        approval_ref=approval_ref, **headers(roots),
    )
    # a competing writer prepared a DIFFERENT approval from the same head
    other_version, other_state = prepare_environment_version(
        state, other, expected_head=state.head,
    )
    other_ref = persist_design_approval(domain, other, **headers(roots))
    with pytest.raises(DesignStoreError):
        persist_environment_head(
            domain, other_version, other_state, parent_ref=None,
            approval_ref=other_ref, **headers(roots),
        )


def test_persist_and_restore_are_strict(vault):
    domain, roots = vault
    approval, _other, _state, version, state2 = prepared_flow()
    with pytest.raises(DesignStoreError):
        persist_design_approval(domain, object(), **headers(roots))
    with pytest.raises(DesignStoreError):
        persist_environment_head(
            domain, object(), state2, parent_ref=None,
            approval_ref=None, **headers(roots),
        )
    good = state2.as_dict()
    for tamper in (
        {"head": -1},
        {"consumed_approvals": ["zz"]},
        {"consumed_approvals": [good["consumed_approvals"][0]] * 2},
        {"schema_version": "wrong"},
    ):
        with pytest.raises(EnvironmentContractError):
            restore_environment_state({**good, **tamper})
    assert restore_environment_state(good).as_dict() == good
    del approval, version
