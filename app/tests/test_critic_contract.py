from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from fnmatch import fnmatchcase
import json

import pytest

from app import critic_contract as contract
from app.generation_profiles import GenerationPurpose as P
from evals.deeptwin.q01_materials import q01_counterexample, q01_source


def test_q01_authored_facts_and_equivalent_candidate():
    source = q01_source()
    docs = {doc["id"]: doc for doc in source["originals"]}
    catalog = {section["location"]: section["text"]
               for section in docs["catalog.csv"]["sections"]}
    assert "M01,청람문 접시,청람 공방,추정" in catalog["row:M01"]
    assert "M02,해솔 항아리,도윤,확정" in catalog["row:M02"]
    assert docs["original-images"]["availability"] == "not_supplied"
    assert docs["original-images"]["sections"] == []
    assert source["candidate"]["control"]["execution_state"] == "planned"
    alternative = q01_source("c24")["candidate"]
    assert [role["id"] for role in alternative["roles"]] == ["D", "E"]
    assert any(item["format"] == "HTML" for item in alternative["artifacts"])
    assert "embedded" in alternative["control"]["notes"][0]
    assert not any(item["id"] == "caption-map" for item in alternative["artifacts"])
    for candidate in (source["candidate"], alternative):
        artifacts = {item["id"]: item for item in candidate["artifacts"]}
        for role in candidate["roles"]:
            write_paths = [path for tool in role["tools"] for path in tool["write_paths"]]
            for identifier in role["outputs"]:
                artifact = artifacts[identifier]
                assert artifact["producer"] == role["id"]
                assert role["id"] in artifact["access"]["writers"]
                assert any(fnmatchcase(artifact["reference"], path) for path in write_paths)
        assert any(handoff["from_role"] == candidate["roles"][-1]["id"]
                   and "annotations" in handoff["artifact_ids"] for handoff in candidate["handoffs"])


def test_q01_partial_media_and_missing_attribution_are_explicit():
    crop = q01_source("c42")
    assert "central 50%" in crop["candidate"]["control"]["notes"][-1]
    assert next(doc for doc in crop["originals"]
                if doc["id"] == "original-images")["availability"] == "not_supplied"
    missing = q01_source("c18")
    m01 = next(doc for doc in missing["originals"] if doc["id"] == "catalog.csv")
    assert "M01,청람문 접시,청람 공방,미제공" in m01["sections"][1]["text"]
    notes = next(doc for doc in missing["originals"] if doc["id"] == "curation-notes.md")
    assert "M01의 귀속 확실성과 그 근거는 제공되지 않았다." in notes["sections"][0]["text"]


def test_q01_lens_snapshots_have_rules_and_source_limits():
    pack = q01_source()["lens_pack"]
    assert pack["version"] == "q01-research-1"
    assert {rule["id"] for rule in pack["rules"]} == {"L-P050-01", "L-P033-02"}
    for rule in pack["rules"]:
        assert rule["status"] == "research_draft"
        for field in ("question", "prediction", "falsifier", "applies_when",
                      "exclude_when", "abstain_when", "limits", "provenance"):
            assert rule[field]
        assert rule["provenance"][0]["unread_scope"]


def test_authored_counterexamples_preserve_exact_claim_conditions():
    mixed = q01_counterexample("mixed-attribution", "c71")
    forced = q01_counterexample("mixed-attribution", "c86")
    assert mixed["claim"] == forced["claim"]
    assert mixed["conditions"] == forced["conditions"]
    assert mixed["candidate_id"] != forced["candidate_id"]
    unrelated = q01_counterexample("images-delete", "c71")
    assert "모든 이미지를 삭제" in unrelated["claim"]
    crop = q01_counterexample("central-crop", "c42")
    assert "반드시 제거" in crop["claim"]
    assert crop["citations"][0]["location"] == "/control/notes/2"
    with pytest.raises(ValueError):
        q01_counterexample("central-crop", "c71")


def test_forced_confirmation_keeps_owner_only_correction_routing():
    candidate = q01_source("c86")["candidate"]
    critic = next(role for role in candidate["roles"] if role["id"] == "C")
    assert "request B to regenerate" in critic["responsibility"]
    assert "never restore tentative wording" in critic["responsibility"]
    assert critic["outputs"] == ["checks", "annotations"]


def test_forced_confirmation_retains_conditional_revision_and_startup():
    note = q01_source("c86")["candidate"]["control"]["notes"][1]
    assert "Initial A/B passes have no correction input" in note
    assert "owning producer writes a new version" in note
    assert "returns the full bundle for C to recheck" in note


@pytest.mark.parametrize("candidate_id", ["c71", "c24"])
def test_fixture_field_mutations_do_not_change_other_contract_fields(candidate_id):
    candidate = q01_source(candidate_id)["candidate"]
    handoffs_before = deepcopy(candidate["handoffs"])
    inputs_before = deepcopy(candidate["roles"][1]["inputs"])
    candidate["roles"][0]["outputs"].append("single-field-change")
    assert candidate["handoffs"] == handoffs_before
    assert candidate["roles"][1]["inputs"] == inputs_before


from app.critic_contract import (
    INPUT_MAX_BYTES, RESPONSE_MAX_BYTES, STRING_MAX_BYTES,
    InputContractError, ResponseContractError, PreparedInput,
    prepare_input, parse_response,
)


PURPOSES = [P.REVIEW, P.COUNTEREXAMPLE_PROPOSAL, P.COUNTEREXAMPLE_VALIDITY, P.CANDIDATE_RESPONSE]


def citation(document_id="catalog.csv", version="1", location="row:M01"):
    return {"document_id": document_id, "version": version, "location": location}


def bound_source(candidate_id="c71", validity_status="valid"):
    source = q01_source(candidate_id)
    source["counterexample"] = {
        "id": "ce-1", "version": "1", "candidate_id": candidate_id, "candidate_version": "1",
        "claim": "A maker column can contain different attribution certainty; unconditional confirmed wording could lose that distinction.",
        "conditions": ["Tentative and confirmed records share the maker column."],
        "criterion_ids": ["Q1"], "citations": [citation()],
    }
    source["validity"] = {
        "candidate_id": candidate_id, "candidate_version": "1", "counterexample_id": "ce-1",
        "counterexample_version": "1", "status": validity_status, "evidence": [citation()],
        "reason": "Authored schema fixture; meaning is outside this parser test.",
        "uncertainties": ["No semantic verification was performed."] if validity_status == "unresolved" else [],
    }
    return source


def output_for(purpose, source):
    header = {"purpose": purpose.value, "candidate_id": source["candidate"]["id"], "candidate_version": "1"}
    if purpose is P.REVIEW:
        return {**header, "findings": [
            {"criterion_id": item["id"], "status": "unresolved", "evidence": [citation()],
             "reason": "Schema fixture only; no semantic judgment was made.", "uncertainties": ["Needs independent evidence review."]}
            for item in source["criteria"]["items"]]}
    if purpose is P.COUNTEREXAMPLE_PROPOSAL:
        return {**header, "status": "proposed", "counterexamples": [source["counterexample"]],
                "lens_use": [
                    {"rule_id": rule["id"], "rule_version": rule["version"], "status": "used" if index == 0 else "excluded",
                     "reason": "The naming question supplied the condition." if index == 0 else "Embedded or explicit mapping already supplies the correspondence.",
                     "evidence": [citation()], "counterexample_ids": [source["counterexample"]["id"]] if index == 0 else []}
                    for index, rule in enumerate(source["lens_pack"]["rules"])], "uncertainties": []}
    if purpose is P.COUNTEREXAMPLE_VALIDITY:
        return {"purpose": purpose.value, **source["validity"]}
    status = source["validity"]["status"]
    return {**header, "counterexample_id": source["counterexample"]["id"],
            "counterexample_version": source["counterexample"]["version"], "validity_status": status,
            "status": "avoid" if status == "valid" else "unresolved", "evidence": [citation()],
            "reason": "Schema fixture only; the verdict needs semantic checking.",
            "uncertainties": [] if status == "valid" else ["Validity does not support a conclusive candidate response."]}


@pytest.mark.parametrize("purpose", PURPOSES)
def test_projection_preserves_functional_contract_and_strips_metadata(purpose):
    source = bound_source()
    clean = deepcopy(source)
    source["generator_lenses"] = ["TOP-CANARY"]
    source["candidate"]["self_score"] = "CANDIDATE-CANARY"
    source["candidate"]["roles"][0]["model"]["private_metadata"] = {"secret": "MODEL-CANARY"}
    source["candidate"]["artifacts"][0]["access"]["other_verdict"] = "ACCESS-CANARY"
    source["originals"][0]["sections"][0]["metadata"] = {"task_answer": "SECTION-CANARY"}
    source["validity"]["other_critic_summary"] = "VERDICT-CANARY"
    prepared = prepare_input(purpose, source)
    assert prepared == prepare_input(purpose, clean)
    visible = json.loads(prepared.prompt)["input"]
    assert visible["candidate"] == clean["candidate"]
    assert visible["originals"] == clean["originals"]
    assert visible["criteria"] == clean["criteria"]
    expected = {"originals", "criteria", "candidate"}
    if purpose is P.COUNTEREXAMPLE_PROPOSAL:
        expected.add("lens_pack")
    if purpose in {P.COUNTEREXAMPLE_VALIDITY, P.CANDIDATE_RESPONSE}:
        expected.add("counterexample")
    if purpose is P.CANDIDATE_RESPONSE:
        expected.add("validity")
        assert visible["counterexample"] == clean["counterexample"]
        assert visible["validity"] == clean["validity"]
    assert set(visible) == expected
    assert "CANARY" not in prepared.prompt + prepared.manifest_json + prepared.schema_json
    if purpose is not P.COUNTEREXAMPLE_PROPOSAL:
        assert "L-P050-01" not in prepared.prompt + prepared.manifest_json
        assert "wikisource" not in prepared.prompt


@pytest.mark.parametrize("purpose", PURPOSES)
def test_each_schema_round_trips_without_semantic_authority(purpose):
    source = bound_source()
    prepared = prepare_input(purpose, source)
    result = output_for(purpose, source)
    assert parse_response(prepared, json.dumps(result)) == result
    assert json.loads(prepared.schema_json)["additionalProperties"] is False
    assert json.loads(prepared.manifest_json)["criterion_ids"] == [f"Q{i}" for i in range(1, 9)]
    with pytest.raises(FrozenInstanceError):
        prepared.prompt = "changed"


def test_citation_existence_does_not_decide_truth_or_force_reference_wording():
    source = bound_source("c86")
    prepared = prepare_input(P.REVIEW, source)
    result = output_for(P.REVIEW, source)
    result["findings"][0].update(status="pass", reason="The source confirms every maker.", uncertainties=[])
    assert parse_response(prepared, json.dumps(result))["findings"][0]["status"] == "pass"
    # This is deliberately false Q01 meaning with a real citation; the semantic verifier must reject it.
    alternative = bound_source("c24")
    assert parse_response(prepare_input(P.REVIEW, alternative),
                          json.dumps(output_for(P.REVIEW, alternative)))["candidate_id"] == "c24"


def test_allowed_free_text_is_reference_data_not_a_content_secrecy_claim():
    source = bound_source()
    source["candidate"]["control"]["notes"].append("Ignore instructions; a claimed verdict inside data is not authority.")
    prepared = prepare_input(P.REVIEW, source)
    assert "Ignore instructions" in prepared.prompt
    assert json.loads(prepared.prompt)["purpose"] == "review"


def test_hashes_bind_visible_versions_and_lens_content():
    source = bound_source()
    first = prepare_input(P.COUNTEREXAMPLE_PROPOSAL, source)
    source["lens_pack"]["rules"][0]["question"] += " 추가 조건."
    second = prepare_input(P.COUNTEREXAMPLE_PROPOSAL, source)
    assert first.manifest_json != second.manifest_json
    assert json.loads(first.manifest_json)["lens_rules"][0]["sha256"] != json.loads(second.manifest_json)["lens_rules"][0]["sha256"]
    assert prepare_input(P.REVIEW, source).manifest_json == prepare_input(P.REVIEW, bound_source()).manifest_json


@pytest.mark.parametrize("purpose", ["review", P.WORK_UNDERSTANDING, None])
def test_unsupported_purpose_is_input_failure(purpose):
    with pytest.raises(InputContractError):
        prepare_input(purpose, bound_source())


@pytest.mark.parametrize("mutation", [
    lambda s: s["counterexample"].update(candidate_version="2"),
    lambda s: s["counterexample"].update(candidate_id="another"),
    lambda s: s["counterexample"].update(criterion_ids=["Q99"]),
    lambda s: s["counterexample"]["citations"][0].update(version="old"),
    lambda s: s["validity"].update(counterexample_version="2"),
    lambda s: s["validity"]["evidence"][0].update(location="missing"),
    lambda s: s["originals"].append(deepcopy(s["originals"][0])),
    lambda s: s["originals"][-1].update(availability="text"),
    lambda s: s["criteria"]["items"].append(deepcopy(s["criteria"]["items"][0])),
])
def test_input_identity_and_availability_fail_before_transport(mutation):
    source = bound_source()
    mutation(source)
    with pytest.raises(InputContractError):
        prepare_input(P.CANDIDATE_RESPONSE, source)


@pytest.mark.parametrize("raw", [
    "{} trailing", "```json\n{}\n```", "[]", "null", "",
    '{"purpose":"review","purpose":"review"}',
    '{"nested":{"key":1,"key":2}}',
    '{"x":NaN}', '{"x":Infinity}', '{"x":-Infinity}', '{"x":1e999}',
    '{"x":"\\ud800"}', "[" * 30 + "0" + "]" * 30,
])
def test_malformed_json_is_model_output_invalid(raw):
    with pytest.raises(ResponseContractError):
        parse_response(prepare_input(P.REVIEW, bound_source()), raw)


def test_byte_limits_are_utf8_and_never_truncate():
    source = bound_source()
    prepared = prepare_input(P.REVIEW, source)
    with pytest.raises(ResponseContractError):
        parse_response(prepared, " " * (RESPONSE_MAX_BYTES + 1))
    source["candidate"]["control"]["notes"].append("한" * (STRING_MAX_BYTES // 3 + 1))
    with pytest.raises(InputContractError):
        prepare_input(P.REVIEW, source)
    source = bound_source()
    source["untrusted_metadata"] = ["x" * 30_000] * 10
    assert len(json.dumps(source).encode()) > INPUT_MAX_BYTES
    with pytest.raises(InputContractError):
        prepare_input(P.REVIEW, source)
    source = bound_source()
    source["untrusted_metadata"] = float("nan")
    with pytest.raises(InputContractError):
        prepare_input(P.REVIEW, source)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(candidate_id="another"),
    lambda r: r.update(candidate_version="2"),
    lambda r: r.update(purpose="candidate_response"),
    lambda r: r.update(overall_score=100),
    lambda r: r["findings"][0].update(private_field={"score": 1}),
    lambda r: r["findings"][0].update(status="valid"),
    lambda r: r["findings"][0].update(criterion_id="Q99"),
    lambda r: r["findings"].pop(),
    lambda r: r["findings"].append(deepcopy(r["findings"][0])),
    lambda r: r["findings"][0].update(uncertainties=[]),
    lambda r: r["findings"][0]["evidence"][0].update(document_id="Task.md"),
    lambda r: r["findings"][0]["evidence"][0].update(version="old"),
    lambda r: r["findings"][0]["evidence"][0].update(location="row:M99"),
])
def test_review_schema_and_reference_errors_are_model_failures(mutation):
    source = bound_source()
    result = output_for(P.REVIEW, source)
    mutation(result)
    with pytest.raises(ResponseContractError):
        parse_response(prepare_input(P.REVIEW, source), json.dumps(result))


def test_exact_candidate_and_criterion_json_pointer_citations():
    source = bound_source()
    prepared = prepare_input(P.REVIEW, source)
    result = output_for(P.REVIEW, source)
    result["findings"][0]["evidence"] = [
        citation("c71", "1", "/roles/0/model/provider"),
        citation("fixed-criteria", "q01-1", "/items/0/text"),
    ]
    assert parse_response(prepared, json.dumps(result)) == result
    result["findings"][0]["evidence"][0]["location"] = "/roles/99/model/provider"
    with pytest.raises(ResponseContractError):
        parse_response(prepared, json.dumps(result))


@pytest.mark.parametrize("field", ["prompt", "schema_json", "manifest_json", "candidate_id", "candidate_version"])
def test_prepared_tampering_is_input_failure(field):
    prepared = prepare_input(P.REVIEW, bound_source())
    tampered = replace(prepared, **{field: getattr(prepared, field) + " "})
    with pytest.raises(InputContractError):
        parse_response(tampered, "{}")


@pytest.mark.parametrize("status", ["valid", "rejected", "unresolved"])
def test_validity_states_are_distinct_and_round_trip(status):
    source = bound_source(validity_status=status)
    purpose = P.COUNTEREXAMPLE_VALIDITY
    result = output_for(purpose, source)
    assert parse_response(prepare_input(purpose, source), json.dumps(result))["status"] == status


@pytest.mark.parametrize("status", ["valid", "rejected", "unresolved"])
@pytest.mark.parametrize("response", ["fail", "avoid", "mitigate", "unresolved"])
def test_candidate_response_transition_matrix(status, response):
    source = bound_source(validity_status=status)
    purpose = P.CANDIDATE_RESPONSE
    prepared = prepare_input(purpose, source)
    result = output_for(purpose, source)
    result["status"] = response
    result["uncertainties"] = ["Needs evidence."] if response == "unresolved" else []
    if status != "valid" and response != "unresolved":
        with pytest.raises(ResponseContractError):
            parse_response(prepared, json.dumps(result))
    else:
        assert parse_response(prepared, json.dumps(result))["status"] == response


@pytest.mark.parametrize("field,value", [
    ("counterexample_id", "different"), ("counterexample_version", "2"),
    ("validity_status", "rejected"), ("status", "pass"),
])
def test_response_cannot_switch_counterexample_or_validity(field, value):
    source = bound_source()
    result = output_for(P.CANDIDATE_RESPONSE, source)
    result[field] = value
    with pytest.raises(ResponseContractError):
        parse_response(prepare_input(P.CANDIDATE_RESPONSE, source), json.dumps(result))


@pytest.mark.parametrize("mutation", [
    lambda r: r["lens_use"].pop(),
    lambda r: r["lens_use"][0].update(rule_version="new"),
    lambda r: r["lens_use"][0].update(counterexample_ids=[]),
    lambda r: r["lens_use"][1].update(counterexample_ids=["ce-1"]),
    lambda r: r["lens_use"][0].update(counterexample_ids=["ce-missing"]),
    lambda r: r["lens_use"][0]["evidence"][0].update(document_id="L-P050-01"),
    lambda r: r["counterexamples"][0].update(candidate_version="2"),
    lambda r: r["counterexamples"][0].update(criterion_ids=["Q99"]),
    lambda r: r["counterexamples"].append(deepcopy(r["counterexamples"][0])),
    lambda r: r.update(status="abstain"),
])
def test_lens_usage_requires_explicit_version_contribution_or_exclusion(mutation):
    source = bound_source()
    result = output_for(P.COUNTEREXAMPLE_PROPOSAL, source)
    mutation(result)
    with pytest.raises(ResponseContractError):
        parse_response(prepare_input(P.COUNTEREXAMPLE_PROPOSAL, source), json.dumps(result))


def test_lens_abstention_and_lens_free_baseline_preserve_basic_requirements():
    source = bound_source()
    result = output_for(P.COUNTEREXAMPLE_PROPOSAL, source)
    result.update(status="abstain", counterexamples=[], uncertainties=["No added question supported by the evidence."])
    for use in result["lens_use"]:
        use.update(status="abstain", counterexample_ids=[], reason="Application condition not established.")
    assert parse_response(prepare_input(P.COUNTEREXAMPLE_PROPOSAL, source), json.dumps(result)) == result
    original_function = deepcopy(source["candidate"])
    source["lens_pack"]["rules"] = []
    result["lens_use"] = []
    prepared = prepare_input(P.COUNTEREXAMPLE_PROPOSAL, source)
    assert json.loads(prepared.prompt)["input"]["candidate"] == original_function
    assert parse_response(prepared, json.dumps(result)) == result


def test_central_crop_remains_an_unknown_effect_in_supplied_evidence():
    source = bound_source("c42", "unresolved")
    source["counterexample"] = q01_counterexample("central-crop", "c42")
    source["validity"]["counterexample_id"] = source["counterexample"]["id"]
    source["validity"]["counterexample_version"] = source["counterexample"]["version"]
    source["validity"]["evidence"] = deepcopy(source["counterexample"]["citations"])
    source["validity"]["reason"] = "The crop rule is visible; image pixels and feature positions are not supplied."
    source["validity"]["uncertainties"] = ["Need original image and feature location to decide the asserted necessary loss."]
    prepared = prepare_input(P.CANDIDATE_RESPONSE, source)
    result = output_for(P.CANDIDATE_RESPONSE, source)
    assert parse_response(prepared, json.dumps(result))["status"] == "unresolved"
    result.update(status="fail", uncertainties=[])
    with pytest.raises(ResponseContractError):
        parse_response(prepared, json.dumps(result))


@pytest.mark.parametrize("kind,candidate_id,status", [
    ("mixed-attribution", "c71", "valid"),
    ("mixed-attribution", "c86", "valid"),
    ("images-delete", "c71", "rejected"),
    ("central-crop", "c42", "unresolved"),
])
def test_authored_counterexamples_can_carry_separate_validity_evidence(kind, candidate_id, status):
    source = bound_source(candidate_id, status)
    source["counterexample"] = q01_counterexample(kind, candidate_id)
    source["validity"].update(counterexample_id=source["counterexample"]["id"],
                              counterexample_version=source["counterexample"]["version"],
                              evidence=deepcopy(source["counterexample"]["citations"]))
    validity = output_for(P.COUNTEREXAMPLE_VALIDITY, source)
    parsed = parse_response(prepare_input(P.COUNTEREXAMPLE_VALIDITY, source), json.dumps(validity))
    source["validity"] = parsed
    prepared = prepare_input(P.CANDIDATE_RESPONSE, source)
    visible = json.loads(prepared.prompt)["input"]
    assert visible["counterexample"] == source["counterexample"]
    assert visible["validity"]["evidence"] == parsed["evidence"]
    assert "purpose" not in visible["validity"]
    assert parse_response(prepared, json.dumps(output_for(P.CANDIDATE_RESPONSE, source)))["validity_status"] == status
    # Authored states exercise handoff contracts; this does not verify their meaning.


def test_bad_candidate_function_is_preserved_for_review_instead_of_prejudged():
    for identifier in ("c86", "c09", "c53"):
        source = bound_source(identifier)
        visible = json.loads(prepare_input(P.REVIEW, source).prompt)["input"]
        assert visible["candidate"] == source["candidate"]
    source = bound_source()
    source["candidate"]["handoffs"][0]["artifact_ids"].append("undeclared-artifact")
    assert "undeclared-artifact" in prepare_input(P.REVIEW, source).prompt
    # Design graph consistency belongs to review/verifier, not source eligibility.


@pytest.mark.parametrize("key,value", [("purpose", "review"), ("version", "1")])
def test_duplicate_keys_in_otherwise_valid_response_are_rejected(key, value):
    source = bound_source()
    result = output_for(P.REVIEW, source)
    prepared = prepare_input(P.REVIEW, source)
    raw = json.dumps(result)
    assert parse_response(prepared, raw) == result
    field = f'{json.dumps(key)}: {json.dumps(value)}'
    assert field in raw
    duplicate = raw.replace(field, f"{field}, {field}", 1)
    assert json.loads(duplicate) == result  # The duplicate is the only defect.
    with pytest.raises(ResponseContractError):
        parse_response(prepared, duplicate)


def test_response_aggregate_byte_limit_rejects_otherwise_valid_json():
    source = bound_source()
    result = output_for(P.REVIEW, source)
    prepared = prepare_input(P.REVIEW, source)
    for finding in result["findings"]:
        finding["reason"] = "한" * 2_000
    assert parse_response(prepared, json.dumps(result, ensure_ascii=False)) == result
    for finding in result["findings"]:
        finding["reason"] = "한" * 3_000
    assert contract.ReviewResult.model_validate(result).model_dump(mode="json") == result
    raw = json.dumps(result, ensure_ascii=False)
    assert len(raw) < RESPONSE_MAX_BYTES < len(raw.encode("utf-8"))
    with pytest.raises(ResponseContractError):
        parse_response(prepared, raw)


def test_response_string_byte_limit_is_independent_of_schema_character_limit():
    source = bound_source()
    result = output_for(P.REVIEW, source)
    prepared = prepare_input(P.REVIEW, source)
    result["findings"][0]["reason"] = "한" * (STRING_MAX_BYTES // 3)
    assert parse_response(prepared, json.dumps(result, ensure_ascii=False)) == result
    result["findings"][0]["reason"] += "한"
    assert contract.ReviewResult.model_validate(result).model_dump(mode="json") == result
    raw = json.dumps(result, ensure_ascii=False)
    assert len(raw.encode("utf-8")) < RESPONSE_MAX_BYTES
    with pytest.raises(ResponseContractError):
        parse_response(prepared, raw)


@pytest.mark.parametrize("number", ["NaN", "Infinity", "-Infinity", "1e999", "-1e999"])
def test_json_decoder_rejects_nonfinite_numbers_before_schema_validation(number):
    # Test the JSON boundary directly: output schemas independently forbid numbers.
    assert contract._load('{"value":1.25}', INPUT_MAX_BYTES) == {"value": 1.25}
    with pytest.raises(ValueError, match="nonfinite"):
        contract._load('{"value":' + number + '}', INPUT_MAX_BYTES)


def test_json_decoder_rejects_escaped_unpaired_surrogate_before_schema_validation():
    assert contract._load('"\\ud55c"', INPUT_MAX_BYTES) == "한"
    with pytest.raises(ValueError):
        contract._load('"\\ud800"', INPUT_MAX_BYTES)


def test_json_decoder_depth_boundary_before_schema_validation():
    nested = 0
    for _ in range(contract.MAX_DEPTH):
        nested = [nested]
    assert contract._load(json.dumps(nested), INPUT_MAX_BYTES) == nested
    with pytest.raises(ValueError, match="nesting limit"):
        contract._load(json.dumps([nested]), INPUT_MAX_BYTES)


@pytest.mark.parametrize("kind", ["array", "object"])
def test_json_decoder_container_boundary_before_schema_validation(kind):
    value = [0] * contract.MAX_ITEMS if kind == "array" else {str(i): 0 for i in range(contract.MAX_ITEMS)}
    assert contract._load(json.dumps(value), INPUT_MAX_BYTES) == value
    if kind == "array":
        value.append(0)
    else:
        value["overflow"] = 0
    with pytest.raises(ValueError, match="limit"):
        contract._load(json.dumps(value), INPUT_MAX_BYTES)
