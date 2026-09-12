"""Source-backed lens contracts; no model, user data, or live qualification."""

from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pytest

from app.services.lenses import (
    ApplicabilityAssessment,
    CompositionInput,
    LensDecision,
    LensError,
    LensQualification,
    LensRegistry,
    RouteEvidence,
)
from app.domain.refs import EntityRef


ROOT = Path(__file__).resolve().parents[2]
LENS_DIR = ROOT / "docs/lenses"
DEFINITIONS = LENS_DIR / "definition-candidates.md"
COMPOSITION = LENS_DIR / "composition-contract.md"
EXPECTED_IDS = {
    "L-P001-01", "L-P029-01", "L-P030-01", "L-P030-02", "L-P031-01",
    "L-P032-01", "L-P033-01", "L-P033-02", "L-P034-01", "L-P035-01",
    "L-P035-02", "L-P049-01", "L-P050-01", "L-P050-02", "L-P051-01",
    "L-P051-02", "L-P052-01",
}
HASH = "a" * 64
QUALIFICATION_HASH = "d" * 64


class FixtureEvidenceVerifier:
    """Synthetic test authority, never selected by production composition."""

    def verify_route(self, route):
        return isinstance(route, RouteEvidence)

    def verify_assessment(self, assessment, route):
        return assessment.lens_ref is not None and assessment.evidence_hashes is not None

    def verify_qualification(self, qualification):
        return qualification.qualification_record_hash == QUALIFICATION_HASH

    def verify_composition_input(self, item, decision):
        return (
            isinstance(item, CompositionInput)
            and isinstance(decision, LensDecision)
            and item.lens_ref == decision.lens_ref
            and item.judgment_ref.kind == "design_decision"
            and item.proposal_ref.kind == "design_decision"
        )


def registry():
    return LensRegistry.from_markdown(DEFINITIONS, COMPOSITION)


def trusted_fixture_registry():
    return LensRegistry.from_markdown(
        DEFINITIONS, COMPOSITION, evidence_verifier=FixtureEvidenceVerifier()
    )


def copy_bundle(tmp_path):
    for name in (
        "definition-candidates.md", "composition-contract.md", "source-map.md",
        "review-report.md", "review-cases.md",
    ):
        (tmp_path / name).write_bytes((LENS_DIR / name).read_bytes())
    return tmp_path / "definition-candidates.md", tmp_path / "composition-contract.md"


def initial(scope=HASH):
    return RouteEvidence.create(
        path="initial_design", scope_hash=scope, work_revision_hash="b" * 64,
        purpose_confirmed=True, deliverables_confirmed=True,
        completion_confirmed=True, observable_conditions=True,
        authorized_source_hashes=("c" * 64,),
    )


def critic(scope=HASH):
    return RouteEvidence.create(
        path="critic_counterexample", scope_hash=scope, original_hash="1" * 64,
        candidate_hash="2" * 64, criteria_hash="3" * 64,
        authorized_source_hashes=("4" * 64,),
    )


def spli(scope=HASH, alternative_scope="partial"):
    return RouteEvidence.create(
        path="post_alternative_spli", scope_hash=scope, original_hash="1" * 64,
        alternative_hash="2" * 64, alternative_scope=alternative_scope,
        observed_difference_hash="3" * 64, h_exp_hash="4" * 64,
        authorized_source_hashes=("5" * 64,),
    )


def qualification(item, route, *, status="qualified", scope=None, record=QUALIFICATION_HASH):
    return LensQualification.create(
        lens_ref=item.ref, path=route.path, scope_hash=scope or route.scope_hash,
        status=status, qualification_record_hash=record,
    )


def supported(item, *, duplicate=False):
    return ApplicabilityAssessment.create(
        lens_ref=item.ref, status="supported", evidence_hashes=("e" * 64,),
        existing_process_duplicate=duplicate,
    )


def proposed(value, item, route):
    return value.decide(item.ref, route, supported(item), qualification(item, route))


def _design_decision_ref(role, digest):
    return EntityRef(
        "design_decision",
        str(uuid5(NAMESPACE_URL, f"deeptwin:test:{role}:{digest}")),
        1,
        digest,
    )


def composition_input(value, decision, key, judgment_hash, proposal_hash):
    return value.bind_composition_input(
        decision,
        judgment_key=key,
        judgment_ref=_design_decision_ref("judgment", judgment_hash),
        proposal_ref=_design_decision_ref("proposal", proposal_hash),
    )


def test_loads_exact_reviewed_bundle_with_separate_status_axes():
    value = registry()
    assert set(value.ids()) == EXPECTED_IDS
    assert len(value.ids()) == 17
    assert set(value.companion_hashes) == {
        "definition-candidates.md", "composition-contract.md", "source-map.md",
        "review-report.md", "review-cases.md",
    }
    for item in value.definitions():
        assert item.ref.version == "draft-1"
        assert len(item.ref.content_hash) == 64
        assert item.neutral_name and item.atomic_claim and item.source_scope
        assert item.applicability and item.non_applicability and item.abstention_condition
        assert item.distinguishing_question and item.expected_contrast
        assert item.disconfirmation and item.engineering_translation
        assert item.document_review_status == "passed_scoped"
        assert item.scholarly_review_status == "not_reviewed"
        assert item.effect_status == "not_validated"
        assert item.adoption_status == "not_adopted"
        assert item.qualified_paths == ()
    assert value.definition_source_hash != value.composition_contract_hash


def test_changed_source_or_common_contract_cannot_claim_reviewed_draft_status(tmp_path):
    definitions, composition = copy_bundle(tmp_path)
    text = definitions.read_text(encoding="utf-8")
    definitions.write_text(
        text.replace("전체 판단을 지탱하는 세부 단서", "전체 판단을 지탱하는 세부 단서 수정", 1),
        encoding="utf-8",
    )
    with pytest.raises(LensError, match="reviewed bundle"):
        LensRegistry.from_markdown(definitions, composition)

    definitions, composition = copy_bundle(tmp_path)
    text = definitions.read_text(encoding="utf-8")
    start = text.index("## 모든 카드가 명시적으로 상속하는 계약")
    end = text.index("## 후보 카드")
    definitions.write_text(text[:start] + text[end:], encoding="utf-8")
    with pytest.raises(LensError, match="reviewed bundle"):
        LensRegistry.from_markdown(definitions, composition)


def test_registry_direct_construction_and_untrusted_self_qualification_are_blocked():
    value = registry()
    item = value.get("L-P032-01")
    route = initial()
    decision = value.decide(item.ref, route, supported(item), qualification(item, route))
    assert (decision.state, decision.reason) == (
        "abstained", "qualification_record_untrusted"
    )
    with pytest.raises(LensError, match="loaded"):
        LensRegistry(
            {item.ref.lens_id: item},
            definition_source_hash="0" * 64,
            composition_contract_hash="1" * 64,
            companion_hashes={}, evidence_verifier=FixtureEvidenceVerifier(),
        )


def test_document_review_and_user_bundle_review_do_not_activate_any_lens():
    value = registry()
    item = value.get("L-P032-01")
    decision = value.decide(item.ref, initial(), supported(item), qualification=None)
    assert (decision.state, decision.reason) == ("abstained", "usage_unqualified")


@pytest.mark.parametrize("path", ["initial_design", "critic_counterexample", "post_alternative_spli"])
def test_trusted_exact_hash_path_and_scope_qualification_can_only_propose_there(path):
    value = trusted_fixture_registry()
    item = value.get("L-P032-01")
    route = {"initial_design": initial(), "critic_counterexample": critic(),
             "post_alternative_spli": spli()}[path]
    assert proposed(value, item, route).state == "proposed"
    wrong_scope = qualification(item, route, scope="f" * 64)
    assert value.decide(item.ref, route, supported(item), wrong_scope).reason == \
        "qualification_scope_mismatch"


def test_initial_description_and_identical_records_cannot_be_relabelled_as_spli():
    with pytest.raises(LensError):
        RouteEvidence.create(
            path="post_alternative_spli", scope_hash=HASH,
            work_revision_hash="b" * 64, purpose_confirmed=True,
            deliverables_confirmed=True, completion_confirmed=True,
            observable_conditions=True, authorized_source_hashes=("c" * 64,),
        )
    with pytest.raises(LensError):
        RouteEvidence.create(
            path="post_alternative_spli", scope_hash=HASH,
            original_hash="1" * 64, alternative_hash="2" * 64,
            alternative_scope="partial", observed_difference_hash=None,
            h_exp_hash="4" * 64, authorized_source_hashes=("5" * 64,),
        )
    with pytest.raises(LensError, match="distinct"):
        RouteEvidence.create(
            path="post_alternative_spli", scope_hash=HASH,
            original_hash="1" * 64, alternative_hash="1" * 64,
            alternative_scope="partial", observed_difference_hash="1" * 64,
            h_exp_hash="1" * 64, authorized_source_hashes=("5" * 64,),
        )


@pytest.mark.parametrize(("status", "duplicate", "state", "reason"), [
    ("unknown", False, "abstained", "applicability_unknown"),
    ("not_applicable", False, "excluded", "not_applicable"),
    ("supported", True, "excluded", "existing_process_duplicate"),
])
def test_unknown_not_applicable_and_existing_process_duplication_stay_distinct(
    status, duplicate, state, reason
):
    value = trusted_fixture_registry()
    item = value.get("L-P052-01")
    route = initial()
    assessment = ApplicabilityAssessment.create(
        lens_ref=item.ref, status=status,
        evidence_hashes=() if status == "unknown" else ("e" * 64,),
        existing_process_duplicate=duplicate,
    )
    decision = value.decide(item.ref, route, assessment, qualification(item, route))
    assert (decision.state, decision.reason) == (state, reason)


@pytest.mark.parametrize("status", ["failed", "unknown", "revoked"])
def test_qualification_outcomes_are_auditable_and_never_activate(status):
    value = trusted_fixture_registry()
    item = value.get("L-P052-01")
    route = initial()
    decision = value.decide(
        item.ref, route, supported(item), qualification(item, route, status=status)
    )
    assert (decision.state, decision.reason) == ("abstained", f"qualification_{status}")
    assert decision.qualification_status == status


def test_composition_preserves_complement_duplicate_and_unresolved_conflict_without_voting():
    value = trusted_fixture_registry()
    route = initial()
    first = value.get("L-P050-01")
    second = value.get("L-P033-02")
    decisions = tuple(proposed(value, item, route) for item in (first, second))
    complement = value.compose(decisions, (
        composition_input(value, decisions[0], "meaning", "8" * 64, "1" * 64),
        composition_input(value, decisions[1], "handoff", "9" * 64, "2" * 64),
    ), required_constraints_satisfied=True)
    assert complement.state == "complementary"
    assert complement.conflicts == () and complement.duplicates == ()

    duplicate = value.compose(decisions, (
        composition_input(value, decisions[0], "caption", "7" * 64, "3" * 64),
        composition_input(value, decisions[1], "caption_alias", "7" * 64, "3" * 64),
    ), required_constraints_satisfied=True)
    assert duplicate.state == "redundant"
    assert duplicate.duplicates == ((first.ref, second.ref),)

    conflict = value.compose(decisions, (
        composition_input(value, decisions[0], "panel_space", "6" * 64, "4" * 64),
        composition_input(value, decisions[1], "layout_area_alias", "6" * 64, "5" * 64),
    ), required_constraints_satisfied=True)
    assert conflict.state == "unresolved_conflict" and conflict.resolution is None
    assert conflict.conflicts[0].judgment_aliases == ("panel_space", "layout_area_alias")
    assert conflict.conflicts[0].proposal_hashes == ("4" * 64, "5" * 64)
    assert conflict.conflicts[0].proposals == (
        (first.ref, "4" * 64), (second.ref, "5" * 64)
    )


def test_duplicates_inside_a_conflict_are_not_discarded():
    value = trusted_fixture_registry()
    route = initial()
    items = tuple(value.get(lens_id) for lens_id in (
        "L-P050-01", "L-P033-02", "L-P031-01"
    ))
    decisions = tuple(proposed(value, item, route) for item in items)
    proposals = ("4" * 64, "4" * 64, "5" * 64)
    inputs = tuple(
        composition_input(value, decision, f"alias_{index}", "6" * 64, proposal)
        for index, (decision, proposal) in enumerate(zip(decisions, proposals))
    )
    result = value.compose(decisions, inputs, required_constraints_satisfied=True)
    assert result.state == "unresolved_conflict"
    assert result.duplicates == ((items[0].ref, items[1].ref),)


def test_cross_path_or_scope_decisions_cannot_be_composed():
    value = trusted_fixture_registry()
    first = value.get("L-P050-01")
    second = value.get("L-P033-02")
    decisions = (proposed(value, first, initial()), proposed(value, second, critic("f" * 64)))
    inputs = (
        composition_input(value, decisions[0], "a", "7" * 64, "1" * 64),
        composition_input(value, decisions[1], "b", "8" * 64, "2" * 64),
    )
    with pytest.raises(LensError, match="one path, scope"):
        value.compose(decisions, inputs, required_constraints_satisfied=True)


def test_decisions_and_composition_inputs_cannot_cross_registry_issuers():
    first_registry = trusted_fixture_registry()
    second_registry = trusted_fixture_registry()
    item = first_registry.get("L-P050-01")
    route = initial()
    decision = proposed(first_registry, item, route)
    item_input = composition_input(
        first_registry, decision, "meaning", "8" * 64, "1" * 64
    )
    assert not hasattr(LensDecision, "_create")
    assert not hasattr(CompositionInput, "create")
    with pytest.raises(LensError, match="registry instance"):
        second_registry.compose(
            (decision,), (item_input,), required_constraints_satisfied=True
        )


def test_one_display_key_cannot_split_one_judgment_across_self_declared_refs():
    value = trusted_fixture_registry()
    route = initial()
    items = (value.get("L-P050-01"), value.get("L-P033-02"))
    decisions = tuple(proposed(value, item, route) for item in items)
    inputs = (
        composition_input(value, decisions[0], "panel_space", "6" * 64, "4" * 64),
        composition_input(value, decisions[1], "panel_space", "7" * 64, "5" * 64),
    )
    with pytest.raises(LensError, match="one judgment key"):
        value.compose(decisions, inputs, required_constraints_satisfied=True)


def test_one_lens_can_contribute_to_multiple_typed_graph_judgments():
    value = trusted_fixture_registry()
    route = initial()
    item = value.get("L-P050-01")
    decision = proposed(value, item, route)
    inputs = (
        composition_input(value, decision, "meaning", "8" * 64, "1" * 64),
        composition_input(value, decision, "attribution", "9" * 64, "2" * 64),
    )
    result = value.compose((decision,), inputs, required_constraints_satisfied=True)
    assert result.state == "complementary"
    assert result.conflicts == () and result.duplicates == ()


def test_one_lens_cannot_duplicate_or_self_conflict_on_one_judgment_ref():
    value = trusted_fixture_registry()
    route = initial()
    item = value.get("L-P050-01")
    decision = proposed(value, item, route)
    inputs = (
        composition_input(value, decision, "meaning", "8" * 64, "1" * 64),
        composition_input(value, decision, "meaning_alias", "8" * 64, "2" * 64),
    )
    with pytest.raises(LensError, match="only once"):
        value.compose((decision,), inputs, required_constraints_satisfied=True)


def test_same_typed_judgment_identity_cannot_claim_two_content_hashes():
    value = trusted_fixture_registry()
    route = initial()
    items = (value.get("L-P050-01"), value.get("L-P033-02"))
    decisions = tuple(proposed(value, item, route) for item in items)
    first_ref = _design_decision_ref("judgment", "6" * 64)
    changed_ref = EntityRef(
        first_ref.kind, first_ref.id, first_ref.version, "7" * 64
    )
    inputs = (
        value.bind_composition_input(
            decisions[0], judgment_key="panel_space", judgment_ref=first_ref,
            proposal_ref=_design_decision_ref("proposal", "4" * 64),
        ),
        value.bind_composition_input(
            decisions[1], judgment_key="layout_area_alias", judgment_ref=changed_ref,
            proposal_ref=_design_decision_ref("proposal", "5" * 64),
        ),
    )
    with pytest.raises(LensError, match="conflicting immutable content"):
        value.compose(decisions, inputs, required_constraints_satisfied=True)


def test_required_constraint_failure_rejects_candidate_not_value_conflict():
    value = trusted_fixture_registry()
    route = initial()
    item = value.get("L-P031-01")
    decision = proposed(value, item, route)
    result = value.compose((decision,), (
        composition_input(value, decision, "delivery", "7" * 64, "6" * 64),
    ), required_constraints_satisfied=False)
    assert result.state == "rejected_required_constraint"
    assert result.conflicts == () and result.resolution is None


def test_connected_kant_cards_keep_one_source_relationship_without_two_effects():
    value = registry()
    first = value.get("L-P030-01")
    second = value.get("L-P030-02")
    assert second.ref in value.linked_refs(first.ref)
    assert first.ref in value.linked_refs(second.ref)
    assert value.effect_evidence_groups((first.ref, second.ref)) == ((first.ref, second.ref),)


def test_malformed_extra_or_detached_card_bundle_fails_closed(tmp_path):
    definitions, composition = copy_bundle(tmp_path)
    text = definitions.read_text(encoding="utf-8")
    definitions.write_text(
        text.replace("- **관찰 조건:**", "- **관찰 조건 누락:**", 1), encoding="utf-8"
    )
    with pytest.raises(LensError):
        LensRegistry.from_markdown(definitions, composition)
    definitions, composition = copy_bundle(tmp_path)
    definitions.write_text(text + "\n### L-P999-01 · draft-1 · 가짜\n", encoding="utf-8")
    with pytest.raises(LensError):
        LensRegistry.from_markdown(definitions, composition)


def test_partial_spli_and_qualification_status_survive_safe_audit_projection():
    value = trusted_fixture_registry()
    item = value.get("L-P001-01")
    decision = proposed(value, item, spli(alternative_scope="partial"))
    audit = decision.as_audit_dict()
    assert set(audit) == {
        "lens_ref", "registry_bundle_id", "path", "scope_hash", "alternative_scope",
        "qualification_status", "state", "reason", "evidence_hashes",
    }
    assert audit["alternative_scope"] == "partial"
    assert audit["qualification_status"] == "qualified"
    encoded = str(audit).casefold()
    for forbidden in ("personality", "religion", "politic", "h_phi", "user_profile"):
        assert forbidden not in encoded
