"""Pure critic field contracts. A citation or parsed verdict is not semantic proof."""

from dataclasses import dataclass
from hashlib import sha256
import json
import math
from typing import Annotated, Literal, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from .generation_profiles import GenerationPurpose


INPUT_MAX_BYTES = 262_144
RESPONSE_MAX_BYTES = 64_000
STRING_MAX_BYTES = 32_768
MAX_DEPTH = 24
MAX_ITEMS = 512
CONTRACT_VERSION = "critic-contract-1"
PARSER_VERSION = "critic-parser-1"
Id = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:/-]*$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=16_384)]
Location = Annotated[str, StringConstraints(min_length=1, max_length=512)]


class InputContractError(ValueError):
    """Preparation or caller-owned evidence is invalid; no agent score."""


class ResponseContractError(ValueError):
    """Invalid model output; an agent failure when the trial is healthy."""


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Citation(Contract):
    document_id: Id
    version: Id
    location: Location


class Section(Contract):
    location: Location
    text: Text


class Original(Contract):
    id: Id
    version: Id
    media_type: Text
    availability: Literal["text", "not_supplied"]
    sections: list[Section]


class Criterion(Contract):
    id: Id
    text: Text


class Criteria(Contract):
    id: Id
    version: Id
    items: Annotated[list[Criterion], Field(min_length=1)]


class Parameter(Contract):
    name: Text
    value: Text


class RoleModel(Contract):
    provider: Text
    model: Text
    reasoning: Text
    parameters: list[Parameter]


class Tool(Contract):
    name: Text
    description: Text
    operations: list[Text]
    read_paths: list[Text]
    write_paths: list[Text]


class Role(Contract):
    id: Id
    responsibility: Text
    model: RoleModel
    tools: list[Tool]
    inputs: list[Id]
    outputs: list[Id]
    checks: list[Text]


class Access(Contract):
    readers: list[Id]
    writers: list[Id]
    mode: Text


class Artifact(Contract):
    id: Id
    version: Id
    format: Text
    reference: Text
    producer: Id
    consumers: list[Id]
    access: Access
    content_contract: Text


class Handoff(Contract):
    id: Id
    from_role: Id
    to_role: Id
    artifact_ids: list[Id]
    mode: Text


class Control(Contract):
    execution_state: Literal["planned"]
    publication: Text
    original_mutation: Text
    notes: list[Text]


class Candidate(Contract):
    id: Id
    version: Id
    roles: list[Role]
    artifacts: list[Artifact]
    handoffs: list[Handoff]
    control: Control


class Provenance(Contract):
    url: Text
    locator: Text
    read_scope: Text
    unread_scope: Text


class LensRule(Contract):
    id: Id
    version: Id
    status: Literal["research_draft"]
    question: Text
    prediction: Text
    falsifier: Text
    applies_when: Text
    exclude_when: Text
    abstain_when: Text
    limits: Annotated[list[Text], Field(min_length=1)]
    provenance: Annotated[list[Provenance], Field(min_length=1)]


class LensPack(Contract):
    id: Id
    version: Id
    rules: list[LensRule]


class Counterexample(Contract):
    id: Id
    version: Id
    candidate_id: Id
    candidate_version: Id
    claim: Text
    conditions: Annotated[list[Text], Field(min_length=1)]
    criterion_ids: Annotated[list[Id], Field(min_length=1)]
    citations: Annotated[list[Citation], Field(min_length=1)]


class ValidityEvidence(Contract):
    candidate_id: Id
    candidate_version: Id
    counterexample_id: Id
    counterexample_version: Id
    status: Literal["valid", "rejected", "unresolved"]
    evidence: Annotated[list[Citation], Field(min_length=1)]
    reason: Text
    uncertainties: list[Text]


class ReviewInput(Contract):
    originals: Annotated[list[Original], Field(min_length=1)]
    criteria: Criteria
    candidate: Candidate


class ProposalInput(ReviewInput):
    lens_pack: LensPack


class ValidityInput(ReviewInput):
    counterexample: Counterexample


class ResponseInput(ValidityInput):
    validity: ValidityEvidence


class Header(Contract):
    candidate_id: Id
    candidate_version: Id


class Finding(Contract):
    criterion_id: Id
    status: Literal["pass", "fail", "unresolved"]
    evidence: Annotated[list[Citation], Field(min_length=1)]
    reason: Text
    uncertainties: list[Text]


class ReviewResult(Header):
    purpose: Literal["review"]
    findings: Annotated[list[Finding], Field(min_length=1)]


class LensUse(Contract):
    rule_id: Id
    rule_version: Id
    status: Literal["used", "excluded", "abstain"]
    reason: Text
    evidence: Annotated[list[Citation], Field(min_length=1)]
    counterexample_ids: list[Id]


class ProposalResult(Header):
    purpose: Literal["counterexample_proposal"]
    status: Literal["proposed", "abstain"]
    counterexamples: Annotated[list[Counterexample], Field(max_length=16)]
    lens_use: list[LensUse]
    uncertainties: list[Text]


class ValidityResult(ValidityEvidence):
    purpose: Literal["counterexample_validity"]


class ResponseResult(Header):
    purpose: Literal["candidate_response"]
    counterexample_id: Id
    counterexample_version: Id
    validity_status: Literal["valid", "rejected", "unresolved"]
    status: Literal["fail", "avoid", "mitigate", "unresolved"]
    evidence: Annotated[list[Citation], Field(min_length=1)]
    reason: Text
    uncertainties: list[Text]


INPUT_MODELS = {
    GenerationPurpose.REVIEW: ReviewInput,
    GenerationPurpose.COUNTEREXAMPLE_PROPOSAL: ProposalInput,
    GenerationPurpose.COUNTEREXAMPLE_VALIDITY: ValidityInput,
    GenerationPurpose.CANDIDATE_RESPONSE: ResponseInput,
}
OUTPUT_MODELS = {
    GenerationPurpose.REVIEW: ReviewResult,
    GenerationPurpose.COUNTEREXAMPLE_PROPOSAL: ProposalResult,
    GenerationPurpose.COUNTEREXAMPLE_VALIDITY: ValidityResult,
    GenerationPurpose.CANDIDATE_RESPONSE: ResponseResult,
}


@dataclass(frozen=True)
class PreparedInput:
    purpose: GenerationPurpose
    candidate_id: str
    candidate_version: str
    prompt: str
    schema_json: str
    manifest_json: str


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _tree(value, depth=0):
    _require(depth <= MAX_DEPTH, "JSON nesting limit")
    if type(value) is str:
        _require(len(value.encode("utf-8")) <= STRING_MAX_BYTES, "JSON string byte limit")
    elif type(value) is dict:
        _require(len(value) <= MAX_ITEMS and all(type(key) is str for key in value), "JSON object limit or key type")
        for key, item in value.items():
            _tree(key, depth + 1)
            _tree(item, depth + 1)
    elif type(value) is list:
        _require(len(value) <= MAX_ITEMS, "JSON array limit")
        for item in value:
            _tree(item, depth + 1)
    elif type(value) is float:
        _require(math.isfinite(value), "nonfinite JSON number")
    else:
        _require(value is None or type(value) in {bool, int}, "non-JSON value")


def _dump(value, maximum=INPUT_MAX_BYTES):
    _tree(value)
    result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    _require(len(result.encode("utf-8")) <= maximum, "JSON byte limit")
    return result


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("nonfinite JSON constant")


def _load(raw, maximum):
    _require(type(raw) is str and len(raw.encode("utf-8")) <= maximum, "JSON text or byte limit")
    value = json.loads(raw, object_pairs_hook=_pairs, parse_constant=_nonfinite)
    _tree(value)
    return value


def _allow(annotation, value):
    # Every nested object is one explicit Contract; no dict metadata fields exist.
    if isinstance(annotation, type) and issubclass(annotation, Contract) and type(value) is dict:
        return {name: _allow(field.annotation, value[name])
                for name, field in annotation.model_fields.items() if name in value}
    if get_origin(annotation) is list and type(value) is list:
        item_type = get_args(annotation)[0]
        return [_allow(item_type, item) for item in value]
    return value


def _pointers(value, path=""):
    if path:
        yield path
    if type(value) is dict:
        for key, child in value.items():
            escaped = key.replace("~", "~0").replace("/", "~1")
            yield from _pointers(child, path + "/" + escaped)
    elif type(value) is list:
        for index, child in enumerate(value):
            yield from _pointers(child, path + "/" + str(index))


def _unique(values, label):
    _require(len(values) == len(set(values)), "duplicate " + label)


def _registry(visible):
    documents = visible["originals"] + [visible["criteria"], visible["candidate"]]
    _unique([doc["id"] for doc in documents], "document id")
    references = set()
    for doc in visible["originals"]:
        _require(bool(doc["sections"]) == (doc["availability"] == "text"), "original availability mismatch")
        locations = [section["location"] for section in doc["sections"]]
        _unique(locations, "source location")
        references.update((doc["id"], doc["version"], location) for location in locations)
    for doc in [visible["criteria"], visible["candidate"]]:
        references.update((doc["id"], doc["version"], pointer) for pointer in _pointers(doc))
    _unique([item["id"] for item in visible["criteria"]["items"]], "criterion id")
    return references


def _citations(items, references):
    for item in items:
        _require((item["document_id"], item["version"], item["location"]) in references, "citation is not visible")


def _candidate_binding(item, visible):
    _require((item["candidate_id"], item["candidate_version"]) ==
             (visible["candidate"]["id"], visible["candidate"]["version"]), "candidate binding mismatch")


def _counterexample(item, visible, references):
    _candidate_binding(item, visible)
    ids = item["criterion_ids"]
    _unique(ids, "counterexample criterion")
    _require(set(ids) <= {criterion["id"] for criterion in visible["criteria"]["items"]}, "unknown criterion")
    _citations(item["citations"], references)


def _counterexample_binding(item, visible):
    ce = visible["counterexample"]
    _require((item["counterexample_id"], item["counterexample_version"]) == (ce["id"], ce["version"]), "counterexample binding mismatch")


def _unresolved(item):
    if item["status"] == "unresolved":
        _require(bool(item["uncertainties"]), "unresolved result needs uncertainty")


def _validate_visible(visible):
    references = _registry(visible)
    if "lens_pack" in visible:
        _unique([rule["id"] for rule in visible["lens_pack"]["rules"]], "lens rule id")
    if "counterexample" in visible:
        _counterexample(visible["counterexample"], visible, references)
    if "validity" in visible:
        validity = visible["validity"]
        _candidate_binding(validity, visible)
        _counterexample_binding(validity, visible)
        _citations(validity["evidence"], references)
        _unresolved(validity)
    return references


def _schema(purpose, visible):
    schema = OUTPUT_MODELS[purpose].model_json_schema()
    schema["properties"]["candidate_id"]["const"] = visible["candidate"]["id"]
    schema["properties"]["candidate_version"]["const"] = visible["candidate"]["version"]
    criteria = [item["id"] for item in visible["criteria"]["items"]]
    if purpose is GenerationPurpose.REVIEW:
        schema["$defs"]["Finding"]["properties"]["criterion_id"]["enum"] = criteria
    if purpose is GenerationPurpose.COUNTEREXAMPLE_PROPOSAL:
        schema["$defs"]["Counterexample"]["properties"]["criterion_ids"]["items"]["enum"] = criteria
    if "counterexample" in visible:
        schema["properties"]["counterexample_id"]["const"] = visible["counterexample"]["id"]
        schema["properties"]["counterexample_version"]["const"] = visible["counterexample"]["version"]
    if "validity" in visible:
        schema["properties"]["validity_status"]["const"] = visible["validity"]["status"]
    return _dump(schema)


def _hash(value):
    return sha256(_dump(value).encode("utf-8")).hexdigest()


def prepare_input(purpose: GenerationPurpose, source: dict) -> PreparedInput:
    try:
        _require(type(purpose) is GenerationPurpose and purpose in INPUT_MODELS, "unsupported critic purpose")
        _require(type(source) is dict, "source must be an object")
        _dump(source)  # Bound the entire untrusted object before dropping fields.
        visible = INPUT_MODELS[purpose].model_validate(_allow(INPUT_MODELS[purpose], source)).model_dump(mode="json")
        references = _validate_visible(visible)
        schema_json = _schema(purpose, visible)
        prompt = _dump({"contract_version": CONTRACT_VERSION, "purpose": purpose.value, "input": visible})
        manifest = {
            "contract_version": CONTRACT_VERSION, "parser_version": PARSER_VERSION, "purpose": purpose.value,
            "candidate_id": visible["candidate"]["id"], "candidate_version": visible["candidate"]["version"],
            "criterion_ids": [item["id"] for item in visible["criteria"]["items"]],
            "prompt_sha256": sha256(prompt.encode("utf-8")).hexdigest(),
            "schema_sha256": sha256(schema_json.encode("utf-8")).hexdigest(),
            "visible_sha256": _hash(visible),
            "documents": [{"id": item["id"], "version": item["version"], "sha256": _hash(item)}
                          for item in visible["originals"] + [visible["criteria"], visible["candidate"]]],
            "citation_count": len(references),
            "lens_pack": ({"id": visible["lens_pack"]["id"], "version": visible["lens_pack"]["version"],
                           "sha256": _hash(visible["lens_pack"])} if "lens_pack" in visible else None),
            "lens_rules": [{"id": rule["id"], "version": rule["version"], "sha256": _hash(rule)}
                           for rule in visible.get("lens_pack", {"rules": []})["rules"]],
            "counterexample": ({"id": visible["counterexample"]["id"],
                                "version": visible["counterexample"]["version"],
                                "sha256": _hash(visible["counterexample"])} if "counterexample" in visible else None),
            "validity_sha256": _hash(visible["validity"]) if "validity" in visible else None,
        }
        return PreparedInput(purpose, visible["candidate"]["id"], visible["candidate"]["version"],
                             prompt, schema_json, _dump(manifest))
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise InputContractError("invalid critic input") from None


def _prepared_visible(prepared):
    try:
        _require(type(prepared) is PreparedInput, "not prepared input")
        payload = _load(prepared.prompt, INPUT_MAX_BYTES)
        _require(type(payload) is dict and set(payload) == {"contract_version", "purpose", "input"}, "invalid prepared wrapper")
        rebuilt = prepare_input(prepared.purpose, payload["input"])
        _require(prepared == rebuilt, "prepared input integrity mismatch")
        return payload["input"]
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise InputContractError("invalid prepared critic input") from None


def _proposal(result, visible, references):
    examples = result["counterexamples"]
    ids = [example["id"] for example in examples]
    _unique(ids, "counterexample id")
    _require(bool(examples) == (result["status"] == "proposed"), "proposal status mismatch")
    if result["status"] == "abstain":
        _require(bool(result["uncertainties"]), "abstention needs reason in uncertainties")
    for example in examples:
        _counterexample(example, visible, references)
    expected = {(rule["id"], rule["version"]) for rule in visible["lens_pack"]["rules"]}
    actual = [(use["rule_id"], use["rule_version"]) for use in result["lens_use"]]
    _unique(actual, "lens usage")
    _require(set(actual) == expected, "lens usage set mismatch")
    for use in result["lens_use"]:
        _citations(use["evidence"], references)
        _unique(use["counterexample_ids"], "lens contribution")
        _require(set(use["counterexample_ids"]) <= set(ids), "unknown contributed counterexample")
        _require(bool(use["counterexample_ids"]) == (use["status"] == "used"), "lens contribution status mismatch")


def parse_response(prepared: PreparedInput, raw: str) -> dict:
    visible = _prepared_visible(prepared)
    try:
        result = OUTPUT_MODELS[prepared.purpose].model_validate(_load(raw, RESPONSE_MAX_BYTES)).model_dump(mode="json")
        _candidate_binding(result, visible)
        references = _registry(visible)
        if prepared.purpose is GenerationPurpose.REVIEW:
            ids = [finding["criterion_id"] for finding in result["findings"]]
            _unique(ids, "finding criterion")
            _require(set(ids) == {item["id"] for item in visible["criteria"]["items"]}, "finding coverage mismatch")
            for finding in result["findings"]:
                _citations(finding["evidence"], references)
                _unresolved(finding)
        elif prepared.purpose is GenerationPurpose.COUNTEREXAMPLE_PROPOSAL:
            _proposal(result, visible, references)
        else:
            _counterexample_binding(result, visible)
            _citations(result["evidence"], references)
            _unresolved(result)
            if prepared.purpose is GenerationPurpose.CANDIDATE_RESPONSE:
                status = visible["validity"]["status"]
                _require(result["validity_status"] == status, "validity status mismatch")
                _require(status == "valid" or result["status"] == "unresolved", "invalid candidate-response transition")
        return result
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
        raise ResponseContractError("invalid critic model output") from None

