"""Durable growth-chain persistence with store-enforced CAS (growth.md §7).

The growth loop and the dataset ledger are immutable in-process values; the
audits recorded that lineage single-liveness and replay prevention are the
storage layer's obligation. This module discharges it on the DomainStore:
every loop revision and ledger revision is one immutable record whose
version IS the revision, so two writers advancing from the same state
collide on (kind, id, version) with different content and the second
transaction fails instead of silently forking (G-09); re-opening a lineage
collides with its revision-1 record; a validation report is stored at the
identity of the ledger revision it consumed, so a different run replaying
one pre-consumption revision collides while a byte-identical replay stays
idempotent, closing the unseen-claim replay at the store (F4). Resume
rebuilds framework-issued values
from the stored chain — trust comes from the store's hash-linked records,
and a tampered payload is refused at restore.
"""

import pytest

from app.domain.store import DomainStore
from app.services.growth import apply_round, is_issued_loop, start_growth_loop
from app.services.growth_store import (
    GrowthStoreError,
    advance_and_persist_loop,
    persist_dataset_ledger,
    persist_loop_state,
    persist_validation_report,
    resume_dataset_ledger,
    resume_loop,
)
from app.services.validation import (
    expose_dataset,
    is_issued_ledger,
    run_validation,
)
from app.storage import Store
from app.tests.test_growth_loop import LINEAGE, profile, valid
from app.tests.test_validation import ledger_with_sealed, report_value

STAMP = "2026-09-13T06:00:00.000000Z"


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


def test_a_loop_chain_persists_and_resumes_exactly(vault):
    domain, roots = vault
    state = start_growth_loop(LINEAGE, profile())
    ref1 = persist_loop_state(domain, state, parent_ref=None, **headers(roots))
    state2, ref2 = advance_and_persist_loop(
        domain, state, valid(0, "0.80"), prev_ref=ref1, **headers(roots),
    )
    state3, ref3 = advance_and_persist_loop(
        domain, state2, valid(1, "0.81"), prev_ref=ref2, **headers(roots),
    )
    assert (ref1.version, ref2.version, ref3.version) == (1, 2, 3)
    resumed = resume_loop(domain, ref3)
    assert is_issued_loop(resumed)
    assert resumed.as_dict() == state3.as_dict()
    # a resumed loop is live: it accepts further rounds under the same rules
    advanced = apply_round(resumed, valid(2, "0.805"))
    assert advanced.non_improving_valid_count == 2  # 0.81 was already one


def test_concurrent_advances_collide_instead_of_forking(vault):
    domain, roots = vault
    state = start_growth_loop(LINEAGE, profile())
    ref1 = persist_loop_state(domain, state, parent_ref=None, **headers(roots))
    _stateA, _refA = advance_and_persist_loop(
        domain, state, valid(0, "0.80"), prev_ref=ref1, **headers(roots),
    )
    with pytest.raises(GrowthStoreError):
        # a second writer advancing from the SAME revision must fail (G-09)
        advance_and_persist_loop(
            domain, state, valid(0, "0.79"), prev_ref=ref1, **headers(roots),
        )


def test_a_lineage_can_never_be_reopened_fresh(vault):
    domain, roots = vault
    state = start_growth_loop(LINEAGE, profile())
    persist_loop_state(domain, state, parent_ref=None, **headers(roots))
    fresh = start_growth_loop(LINEAGE, profile())
    again = persist_loop_state(domain, fresh, parent_ref=None, **headers(roots))
    assert again.version == 1  # identical content is idempotent, not a fork
    different = apply_round(fresh, valid(0, "0.99"))
    with pytest.raises(GrowthStoreError):
        # restart laundering: rev-2 content diverging from the stored chain
        persist_loop_state(
            domain, start_growth_loop(LINEAGE, freeze_other_profile()),
            parent_ref=None, **headers(roots),
        )
    del different


def freeze_other_profile():
    from app.services.growth import freeze_quality_profile

    return freeze_quality_profile({
        "profile_id": "other", "version": 1, "quality_floor": "0.10",
        "min_delta": "0.01", "patience": 5,
    })


def test_revision_chain_requires_the_exact_parent(vault):
    domain, roots = vault
    state = start_growth_loop(LINEAGE, profile())
    ref1 = persist_loop_state(domain, state, parent_ref=None, **headers(roots))
    advanced = apply_round(state, valid(0, "0.80"))
    with pytest.raises(GrowthStoreError):
        persist_loop_state(domain, advanced, parent_ref=None, **headers(roots))
    with pytest.raises(GrowthStoreError):
        # revision 1 never carries a parent
        persist_loop_state(domain, state, parent_ref=ref1, **headers(roots))


def test_ledger_replay_collides_at_the_store(vault):
    domain, roots = vault
    ledger = ledger_with_sealed()
    ref = persist_dataset_ledger(domain, ledger, parent_ref=None,
                                 **headers(roots))
    from app.services.validation import freeze_candidate
    from app.tests.test_alternatives import ref as entity_ref
    from app.tests.test_validation import GATES, candidate_value, gate

    candidate = freeze_candidate(candidate_value())
    report1, seen1 = run_validation(candidate, ledger, report_value())
    other_gates = {
        name: gate(evidence_suffix=970 + i) for i, name in enumerate(GATES)
    }
    report2, seen2 = run_validation(
        candidate, ledger, report_value(gates=other_gates),
    )
    ledger_ref = persist_dataset_ledger(
        domain, seen1, parent_ref=ref, **headers(roots),
    )
    # the replayed consumption is byte-identical, so its ledger write is
    # idempotent — no fork, no second revision
    assert persist_dataset_ledger(
        domain, seen2, parent_ref=ref, **headers(roots),
    ) == ledger_ref
    persist_validation_report(
        domain, report1, lineage_id=ledger.lineage_id,
        parent_ref=ledger_ref, **headers(roots),
    )
    with pytest.raises(GrowthStoreError):
        # a DIFFERENT run replaying the same pre-consumption revision
        # collides: exactly one unseen claim per revision becomes durable
        persist_validation_report(
            domain, report2, lineage_id=ledger.lineage_id,
            parent_ref=ledger_ref, **headers(roots),
        )
    del entity_ref


def test_a_resumed_ledger_still_refuses_laundering(vault):
    domain, roots = vault
    ledger = expose_dataset(ledger_with_sealed(), "sealed-a", "tuning")
    ref = persist_dataset_ledger(domain, ledger, parent_ref=None,
                                 **headers(roots))
    resumed = resume_dataset_ledger(domain, ref)
    assert is_issued_ledger(resumed)
    from app.services.validation import GrowthValidationError, register_dataset
    from app.tests.test_alternatives import ref as entity_ref

    with pytest.raises(GrowthValidationError):
        register_dataset(resumed, {
            "dataset_id": "sealed-reborn",
            "classification": "sealed_validation",
            "manifest": entity_ref("run_manifest", 950),
        })


def test_persist_and_restore_are_strict(vault):
    domain, roots = vault
    with pytest.raises(GrowthStoreError):
        persist_loop_state(domain, object(), parent_ref=None, **headers(roots))
    with pytest.raises(GrowthStoreError):
        persist_dataset_ledger(domain, object(), parent_ref=None,
                               **headers(roots))
    state = start_growth_loop(LINEAGE, profile())
    ref1 = persist_loop_state(domain, state, parent_ref=None, **headers(roots))
    from app.services.growth import GrowthLoopError, restore_growth_loop

    good = state.as_dict()
    for tamper in (
        {"status": "promoted"},
        {"non_improving_valid_count": -1},
        {"revision": 0},
        {"profile_id": "someone-else"},
    ):
        with pytest.raises(GrowthLoopError):
            restore_growth_loop(profile(), {**good, **tamper})
    assert resume_loop(domain, ref1).as_dict() == good


PROMOTION_SCOPE = "00000000-0000-4000-8000-00000000c001"


def promoted_state():
    from app.services.promotion import (
        activate_candidate,
        open_promotion_state,
        record_promotion_decision,
    )
    from app.tests.test_promotion import (
        CURRENT_ENV,
        decision_value,
        frozen_candidate,
        passed_report,
    )

    candidate = frozen_candidate()
    decision = record_promotion_decision(
        decision_value(candidate, passed_report(candidate)),
    )
    opened = open_promotion_state(CURRENT_ENV)
    return opened, activate_candidate(opened, decision, candidate), decision, candidate


def test_promotion_state_persists_resumes_and_keeps_consumed_decisions(vault):
    from app.services.growth_store import (
        persist_promotion_state,
        resume_promotion_state,
    )
    from app.services.promotion import (
        PromotionError,
        activate_candidate,
        is_issued_promotion_state,
        rollback_environment,
    )

    domain, roots = vault
    opened, activated, decision, candidate = promoted_state()
    ref1 = persist_promotion_state(
        domain, opened, scope_id=PROMOTION_SCOPE, parent_ref=None,
        **headers(roots),
    )
    ref2 = persist_promotion_state(
        domain, activated, scope_id=PROMOTION_SCOPE, parent_ref=ref1,
        **headers(roots),
    )
    assert (ref1.version, ref2.version) == (1, 2)
    resumed = resume_promotion_state(domain, ref2)
    assert is_issued_promotion_state(resumed)
    assert resumed.as_dict() == activated.as_dict()
    rolled = rollback_environment(resumed, "회귀 발견")
    with pytest.raises(PromotionError):
        # the consumed approval survives persistence: no replay after resume
        activate_candidate(rolled, decision, candidate)


def test_concurrent_promotion_writes_collide(vault):
    from app.services.growth_store import (
        GrowthStoreError,
        persist_promotion_state,
    )
    from app.services.promotion import rollback_environment

    domain, roots = vault
    _opened, activated, _decision, _candidate = promoted_state()
    ref = persist_promotion_state(
        domain, activated, scope_id=PROMOTION_SCOPE, parent_ref=None,
        **headers(roots),
    )
    rolled = rollback_environment(activated, "회귀")
    persist_promotion_state(
        domain, rolled, scope_id=PROMOTION_SCOPE, parent_ref=ref,
        **headers(roots),
    )
    # a second rollback attempt is byte-identical state → idempotent, and a
    # competing writer who instead activated a DIFFERENT candidate from the
    # same revision collides
    from app.services.promotion import (
        activate_candidate,
        record_promotion_decision,
    )
    from app.tests.test_alternatives import ref as entity_ref
    from app.tests.test_promotion import (
        decision_value,
        frozen_candidate,
        passed_report,
    )

    other = frozen_candidate(prompts=entity_ref("artifact", 999))
    other_decision = record_promotion_decision(decision_value(
        other, passed_report(other, "sealed-o"),
        expected_current_environment=activated.current_environment.as_dict(),
    ))
    competing = activate_candidate(activated, other_decision, other)
    assert competing.revision == rolled.revision
    with pytest.raises(GrowthStoreError):
        persist_promotion_state(
            domain, competing, scope_id=PROMOTION_SCOPE, parent_ref=ref,
            **headers(roots),
        )


def test_promotion_restore_is_strict(vault):
    from app.services.growth_store import (
        persist_promotion_state,
        resume_promotion_state,
    )
    from app.services.promotion import PromotionError, restore_promotion_state

    domain, roots = vault
    _opened, activated, _decision, _candidate = promoted_state()
    ref = persist_promotion_state(
        domain, activated, scope_id=PROMOTION_SCOPE, parent_ref=None,
        **headers(roots),
    )
    good = activated.as_dict()
    for tamper in (
        {"revision": 0},
        {"external_effects_reverted": True},
        {"consumed_decisions": ["zz"]},
        {"history": [[good["history"][0][0], "active"]]},
    ):
        with pytest.raises(PromotionError):
            restore_promotion_state({**good, **tamper})
    assert resume_promotion_state(domain, ref).as_dict() == good
