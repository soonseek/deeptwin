"""Durable design-arc persistence: approvals and environment heads (T036).

Approvals persist content-addressed (identical re-persist is idempotent,
never a second act). The environment head persists like the growth chain:
the record version IS the head, parent-chained, so two writers preparing
from the same head collide at the store instead of silently forking, and
the environments module's documented storage-CAS seam is discharged. A
resumed environment state is framework-issued and still refuses a consumed
approval; tampered payloads are refused at restore.
"""

import dataclasses
from uuid import uuid4

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
    SESSION,
    approval_value,
    design_owner,
)

STAMP = "2026-09-13T09:00:00.000000Z"


@pytest.fixture
def vault():
    # the owner's own vault: a persisted approval must resolve its evidence
    # in the vault it lives in
    domain = SESSION.app.state.domain_store
    return domain, domain.roots()


@pytest.fixture
def decisions():
    return SESSION.decisions()


def test_a_persisted_approval_resolves_its_owner_evidence_in_this_vault(vault, decisions, tmp_path):
    domain, roots = vault
    approval, other, _state, _version, _state2 = prepared_flow()
    foreign = DomainStore(Store(tmp_path / "foreign"))
    foreign_roots = foreign.initialize_vault()

    def approval_records():
        with domain._connection() as db:
            return db.execute(
                "SELECT count(*) FROM domain_records WHERE kind='decision_record'"
            ).fetchone()[0]

    before = approval_records()
    with pytest.raises(DesignStoreError):
        # a decision reader is bound to one store: persisting into another
        # store with it is refused before any resolution is attempted
        persist_design_approval(
            foreign, approval, decisions=decisions, **headers(foreign_roots)
        )
    assert decisions.bound_to(domain) and not decisions.bound_to(foreign)
    with pytest.raises(DesignStoreError):
        persist_design_approval(domain, approval, decisions=object(), **headers(roots))
    with pytest.raises(TypeError):
        dataclasses.replace(approval, approver_evidence=other.approver_evidence)

    def tampered(**changes):
        # an issued value copied slot by slot with one field changed: the
        # persisted record must be refused because the resolved owner
        # decision is not over exactly this approval
        copy = object.__new__(type(approval))
        for name in type(approval).__slots__:
            object.__setattr__(copy, name, getattr(approval, name))
        for name, value in changes.items():
            object.__setattr__(copy, name, value)
        return copy

    bindings = approval.model_bindings
    for wrong in (
        tampered(approver_evidence=other.approver_evidence),  # another design's decision
        # the last hex digit replaced by one it is not: a 1-in-16 no-op tamper (an id
        # already ending in "0") was a hidden flake of this pin
        tampered(approver_id=approval.approver_id[:-1]
                 + ("1" if approval.approver_id.endswith("0") else "0")),
        tampered(approved_at="2026-09-13T09:00:00.000000Z"),
        tampered(model_bindings=dataclasses.replace(bindings, kind="grant")),  # kind is bound
    ):
        with pytest.raises(DesignStoreError):
            persist_design_approval(domain, wrong, decisions=decisions, **headers(roots))
    assert approval_records() == before  # nothing refused was written
    ref = persist_design_approval(domain, approval, decisions=decisions, **headers(roots))
    assert ref.kind == "decision_record"
    assert approval_records() == before + 1


def headers(roots):
    return {
        "actor_ref": roots.actor,
        "access_policy_ref": roots.access_policy,
        "retention_policy_ref": roots.retention_policy,
        "created_at_utc": STAMP,
    }


def prepared_flow():
    # every flow owns a fresh environment: the tests share the owner's vault,
    # and an environment head is a content-addressed, parent-chained record
    environment = str(uuid4())
    _request, two, three, _duplicate = pool_inputs()
    approval = record_design_approval(
        approval_value(two, verdict(two), environment=environment)
    )
    state = open_environment(environment)
    version, state2 = prepare_environment_version(
        state, approval, expected_head=state.head,
    )
    other = record_design_approval(
        approval_value(three, verdict(three), environment=environment)
    )
    return approval, other, state, version, state2


def test_the_flow_persists_resumes_and_still_refuses_replay(vault, decisions):
    domain, roots = vault
    approval, _other, _state, version, state2 = prepared_flow()
    approval_ref = persist_design_approval(domain, approval, decisions=decisions, **headers(roots))
    again = persist_design_approval(domain, approval, decisions=decisions, **headers(roots))
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


def test_concurrent_prepares_collide_at_the_store(vault, decisions):
    domain, roots = vault
    approval, other, state, version, state2 = prepared_flow()
    approval_ref = persist_design_approval(domain, approval, decisions=decisions, **headers(roots))
    persist_environment_head(
        domain, version, state2, parent_ref=None,
        approval_ref=approval_ref, **headers(roots),
    )
    # a competing writer prepared a DIFFERENT approval from the same head
    other_version, other_state = prepare_environment_version(
        state, other, expected_head=state.head,
    )
    other_ref = persist_design_approval(domain, other, decisions=decisions, **headers(roots))
    with pytest.raises(DesignStoreError):
        persist_environment_head(
            domain, other_version, other_state, parent_ref=None,
            approval_ref=other_ref, **headers(roots),
        )


def test_persist_and_restore_are_strict(vault, decisions):
    domain, roots = vault
    approval, _other, _state, version, state2 = prepared_flow()
    with pytest.raises(DesignStoreError):
        persist_design_approval(domain, object(), decisions=decisions, **headers(roots))
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
