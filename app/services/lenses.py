"""Fail-closed, source-bound contracts for DeepTwin micro-lens candidates.

This module deliberately does not execute a lens or infer anything about a
person.  It loads reviewed *document candidates*, keeps every candidate
inactive by default, and validates the evidence needed by three distinct use
paths.  Runtime activation remains an explicit, content-bound qualification.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from hashlib import sha256
from itertools import combinations
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, TypeVar

from ..domain.refs import EntityRef, canonical_json


_MAX_SOURCE_BYTES = 2 * 1024 * 1024
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CARD_HEADER = re.compile(
    r"^### (?P<id>L-P\d{3}-\d{2}) · (?P<version>[^ ·\n]+) · (?P<name>[^\n]+)$",
    re.MULTILINE,
)
_EXPECTED_IDS = frozenset(
    {
        "L-P001-01",
        "L-P029-01",
        "L-P030-01",
        "L-P030-02",
        "L-P031-01",
        "L-P032-01",
        "L-P033-01",
        "L-P033-02",
        "L-P034-01",
        "L-P035-01",
        "L-P035-02",
        "L-P049-01",
        "L-P050-01",
        "L-P050-02",
        "L-P051-01",
        "L-P051-02",
        "L-P052-01",
    }
)
_PATHS = frozenset(
    {"initial_design", "critic_counterexample", "post_alternative_spli"}
)
_COMPOSITION_ANCHORS = (
    "## 1. 입력 경로와 허용된 판단",
    "## 3. 조합과 충돌의 처리 규칙",
    "필수 제약 위반은 해당 후보의 탈락 사유",
    "평균·다수결",
    "## 6. 해석 감사와 SPLI 학습 방화벽",
    "## 7. 비평가 격리와 판정 책임",
)
_DEFINITION_ANCHORS = (
    "# 원전 기반 마이크로렌즈 정의 후보",
    "## 읽기 지도",
    "## 모든 카드가 명시적으로 상속하는 계약",
    "### C1 — 사용 경로의 전제와 허용 범위",
    "- **초기 설계 전제:**",
    "- **비평가 반례 전제:**",
    "- **대안 이후 SPLI 전제:**",
    "### C2 — 판단·설계 효과의 경계",
    "개인의 성격·심리 본성, 정치·종교 성향, 도덕적 서열",
    "### S0 — 새로 만든 합성 업무와 완전한 산출물 인계",
    "브라우저·파일 도구는 프레임워크가 소유하고 실행한다",
    "### R0 — 검토 상태를 분리하는 표기",
    "학술 검토·실제 효과·용도별 사용 허가는 별개",
    "## 후보 카드",
)
# DG-L01 candidate cards remain draft-1.  The inseparable document bundle is
# review revision 2 after the ADR-009 deployment-boundary wording correction.
# A changed byte is a new, unreviewed bundle and must be introduced with a new
# review revision rather than inheriting the labels printed inside Markdown.
_APPROVED_BUNDLE_HASHES = MappingProxyType(
    {
        "definition-candidates.md": "4c183d846e481c8252ad7e00e7edf9efbd0b61b90135ae6d45259ef8fe95dd88",
        "composition-contract.md": "25b2c023454767cd6750711970b1ae8dc13107a6ae23694dcb1ad2e6a54d2c8e",
        "source-map.md": "43174bc3bc98543cb8ee4892ad84ae2f7a1162e499999e1b28f61936b84bb78e",
        "review-report.md": "61ca0c7840eb51089219b214b2282d7daca6fd0b1d8d89468aad9e1aa3534e67",
        "review-cases.md": "4bc03b62ae1c2a081b5f610b386a98505f4d5cf995d4fd5d71db11f1485a46ac",
    }
)
_REGISTRY_LOAD_TOKEN = object()


class LensError(ValueError):
    """A lens source or decision violates the bounded registry contract."""


class LensEvidenceVerifier(Protocol):
    """Trusted application boundary supplied by later qualification work.

    The reviewed Markdown never supplies this authority.  T035/T056 must back
    these checks with durable qualification and lineage records; without such a
    verifier every current candidate remains inactive.
    """

    def verify_route(self, route: "RouteEvidence") -> bool: ...

    def verify_assessment(
        self, assessment: "ApplicabilityAssessment", route: "RouteEvidence"
    ) -> bool: ...

    def verify_qualification(self, qualification: "LensQualification") -> bool: ...

    def verify_composition_input(
        self, item: "CompositionInput", decision: "LensDecision"
    ) -> bool: ...


_T = TypeVar("_T")


def _validated_instance(kind: type[_T], **fields: Any) -> _T:
    """Construct an init-disabled frozen value after its factory validates it."""
    value = object.__new__(kind)
    for name, field_value in fields.items():
        object.__setattr__(value, name, field_value)
    return value


def _hash_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def _validate_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise LensError(f"{field} must be a lowercase SHA-256 hex digest")
    return value


def _validate_hashes(values: Iterable[str], field: str, *, required: bool) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise LensError(f"{field} must be a sequence of hashes")
    result = tuple(_validate_hash(value, field) for value in values)
    if required and not result:
        raise LensError(f"{field} must not be empty")
    if len(set(result)) != len(result):
        raise LensError(f"{field} contains duplicate hashes")
    return result


def _read_bounded(path: Path, label: str) -> tuple[str, bytes]:
    try:
        raw = path.read_bytes()
    except (OSError, ValueError) as exc:
        raise LensError(f"cannot read {label}") from exc
    if not raw or len(raw) > _MAX_SOURCE_BYTES:
        raise LensError(f"{label} must contain 1..{_MAX_SOURCE_BYTES} bytes")
    try:
        return raw.decode("utf-8"), raw
    except UnicodeDecodeError as exc:
        raise LensError(f"{label} must be UTF-8") from exc


def _line_field(section: str, label: str) -> str:
    match = re.search(rf"^- \*\*{re.escape(label)}:\*\*\s*(.+)$", section, re.MULTILINE)
    if match is None:
        raise LensError(f"card is missing required field: {label}")
    value = match.group(1).strip()
    if not value:
        raise LensError(f"card field is empty: {label}")
    return value


def _split_required(value: str, marker: str, field: str) -> tuple[str, str]:
    token = f"**{marker}:**"
    if token not in value:
        raise LensError(f"card field {field} is missing {marker}")
    before, after = (part.strip() for part in value.split(token, 1))
    if not before or not after:
        raise LensError(f"card field {field} has an empty component")
    return before, after


def _split_no_change(value: str) -> tuple[str, str]:
    """Accept the one source card's deliberately qualified no-change label."""
    match = re.search(
        r"\*\*(?:이 핵심 설명 배치 제안의 )?무변경 조건:\*\*",
        value,
    )
    if match is None:
        raise LensError("card field 우리 공학 번역—설계 효과 is missing 무변경 조건")
    before = value[: match.start()].strip()
    after = value[match.end() :].strip()
    if not before or not after:
        raise LensError("card field 우리 공학 번역—설계 효과 has an empty component")
    return before, after


@dataclass(frozen=True, slots=True, order=True)
class LensRef:
    lens_id: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.lens_id not in _EXPECTED_IDS:
            raise LensError("unknown lens id")
        if self.version != "draft-1":
            raise LensError("unsupported lens document version")
        _validate_hash(self.content_hash, "content_hash")

    def __str__(self) -> str:
        return f"{self.lens_id}@{self.version}#{self.content_hash}"


@dataclass(frozen=True, slots=True)
class LensDefinition:
    ref: LensRef
    neutral_name: str
    source_scope: str
    atomic_claim: str
    counter_reading: str
    functional_layers: str
    route_contract: str
    applicability: str
    non_applicability: str
    abstention_condition: str
    distinguishing_question: str
    expected_contrast: str
    disconfirmation: str
    confounders_and_prohibitions: str
    engineering_translation: str
    no_change_condition: str
    document_review_status: str = "passed_scoped"
    scholarly_review_status: str = "not_reviewed"
    effect_status: str = "not_validated"
    adoption_status: str = "not_adopted"
    qualified_paths: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, init=False)
class RouteEvidence:
    path: str
    scope_hash: str
    authorized_source_hashes: tuple[str, ...]
    evidence_hashes: tuple[str, ...]
    alternative_scope: str | None = None

    @classmethod
    def create(
        cls,
        *,
        path: str,
        scope_hash: str,
        authorized_source_hashes: Iterable[str],
        **evidence: object,
    ) -> "RouteEvidence":
        if path not in _PATHS:
            raise LensError("unknown lens use path")
        scope = _validate_hash(scope_hash, "scope_hash")
        authorized = _validate_hashes(
            authorized_source_hashes, "authorized_source_hashes", required=True
        )
        expected: tuple[str, ...]
        alternative_scope: str | None = None
        if path == "initial_design":
            expected = (
                "work_revision_hash",
                "purpose_confirmed",
                "deliverables_confirmed",
                "completion_confirmed",
                "observable_conditions",
            )
            if set(evidence) != set(expected):
                raise LensError("initial_design requires only its confirmed work contract")
            if any(evidence[name] is not True for name in expected[1:]):
                raise LensError("initial_design work conditions must be explicitly confirmed")
            hashes = (_validate_hash(evidence[expected[0]], expected[0]),)
        elif path == "critic_counterexample":
            expected = ("original_hash", "candidate_hash", "criteria_hash")
            if set(evidence) != set(expected):
                raise LensError("critic_counterexample requires original, candidate and fixed criteria")
            hashes = tuple(_validate_hash(evidence[name], name) for name in expected)
            if len(set(hashes)) != len(hashes):
                raise LensError("critic evidence roles must reference distinct records")
        else:
            expected = (
                "original_hash",
                "alternative_hash",
                "alternative_scope",
                "observed_difference_hash",
                "h_exp_hash",
            )
            if set(evidence) != set(expected):
                raise LensError("post_alternative_spli requires an actual alternative, difference and H_exp")
            alternative_scope_value = evidence["alternative_scope"]
            if alternative_scope_value not in {"whole", "partial"}:
                raise LensError("alternative_scope must be whole or partial")
            alternative_scope = str(alternative_scope_value)
            hashes = tuple(
                _validate_hash(evidence[name], name)
                for name in expected
                if name != "alternative_scope"
            )
            if len(set(hashes)) != len(hashes):
                raise LensError("SPLI requires distinct original, alternative, difference and H_exp records")
        return _validated_instance(
            cls,
            path=path,
            scope_hash=scope,
            authorized_source_hashes=authorized,
            evidence_hashes=hashes,
            alternative_scope=alternative_scope,
        )


@dataclass(frozen=True, slots=True, init=False)
class LensQualification:
    lens_ref: LensRef
    path: str
    scope_hash: str
    status: str
    qualification_record_hash: str

    @classmethod
    def create(
        cls,
        *,
        lens_ref: LensRef,
        path: str,
        scope_hash: str,
        status: str,
        qualification_record_hash: str,
    ) -> "LensQualification":
        if path not in _PATHS:
            raise LensError("unknown qualification path")
        if status not in {"qualified", "failed", "unknown", "revoked"}:
            raise LensError("invalid qualification status")
        if not isinstance(lens_ref, LensRef):
            raise LensError("lens_ref must be a LensRef")
        return _validated_instance(
            cls,
            lens_ref=lens_ref,
            path=path,
            scope_hash=_validate_hash(scope_hash, "scope_hash"),
            status=status,
            qualification_record_hash=_validate_hash(
                qualification_record_hash, "qualification_record_hash"
            ),
        )


@dataclass(frozen=True, slots=True, init=False)
class ApplicabilityAssessment:
    lens_ref: LensRef
    status: str
    evidence_hashes: tuple[str, ...]
    existing_process_duplicate: bool

    @classmethod
    def create(
        cls,
        *,
        lens_ref: LensRef,
        status: str,
        evidence_hashes: Iterable[str],
        existing_process_duplicate: bool = False,
    ) -> "ApplicabilityAssessment":
        if status not in {"supported", "not_applicable", "unknown"}:
            raise LensError("invalid applicability status")
        if not isinstance(existing_process_duplicate, bool):
            raise LensError("existing_process_duplicate must be boolean")
        hashes = _validate_hashes(
            evidence_hashes, "evidence_hashes", required=status != "unknown"
        )
        if status == "unknown" and hashes:
            raise LensError("unknown applicability cannot claim supporting evidence")
        if existing_process_duplicate and status != "supported":
            raise LensError("duplication can only be recorded for a supported condition")
        if not isinstance(lens_ref, LensRef):
            raise LensError("lens_ref must be a LensRef")
        return _validated_instance(
            cls,
            lens_ref=lens_ref,
            status=status,
            evidence_hashes=hashes,
            existing_process_duplicate=existing_process_duplicate,
        )


@dataclass(frozen=True, slots=True, init=False)
class LensDecision:
    lens_ref: LensRef
    registry_bundle_id: str
    path: str
    scope_hash: str
    alternative_scope: str | None
    qualification_status: str
    state: str
    reason: str
    evidence_hashes: tuple[str, ...]
    # Until T035 supplies durable decision records, this in-process capability
    # prevents a reconstructed value from inheriting issuance authority.
    _issuer_token: object = field(repr=False, compare=False)

    def as_audit_dict(self) -> dict[str, object]:
        return {
            "lens_ref": str(self.lens_ref),
            "registry_bundle_id": self.registry_bundle_id,
            "path": self.path,
            "scope_hash": self.scope_hash,
            "alternative_scope": self.alternative_scope,
            "qualification_status": self.qualification_status,
            "state": self.state,
            "reason": self.reason,
            "evidence_hashes": self.evidence_hashes,
        }


@dataclass(frozen=True, slots=True, init=False)
class CompositionInput:
    lens_ref: LensRef
    judgment_key: str
    judgment_ref: EntityRef
    proposal_ref: EntityRef
    _decision: LensDecision = field(repr=False, compare=False)
    _issuer_token: object = field(repr=False, compare=False)

    @property
    def judgment_ref_hash(self) -> str:
        """Audit handle derived from the complete immutable domain reference."""
        return _hash_bytes(canonical_json(self.judgment_ref.as_dict()))

    @property
    def proposal_hash(self) -> str:
        """Detect byte-identical proposals even if their record IDs differ."""
        return self.proposal_ref.sha256

    @property
    def judgment_identity(self) -> tuple[str, str, int]:
        """Canonical graph-record identity, independent of display aliases."""
        return (
            self.judgment_ref.kind,
            self.judgment_ref.id,
            self.judgment_ref.version,
        )


@dataclass(frozen=True, slots=True)
class CompositionConflict:
    judgment_key: str
    judgment_ref_hash: str
    judgment_aliases: tuple[str, ...]
    proposals: tuple[tuple[LensRef, str], ...]

    @property
    def lens_refs(self) -> tuple[LensRef, ...]:
        return tuple(ref for ref, _ in self.proposals)

    @property
    def proposal_hashes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(proposal for _, proposal in self.proposals))


@dataclass(frozen=True, slots=True)
class CompositionResult:
    state: str
    path: str
    scope_hash: str
    alternative_scope: str | None
    conflicts: tuple[CompositionConflict, ...]
    duplicates: tuple[tuple[LensRef, LensRef], ...]
    resolution: None = None


class LensRegistry:
    """Immutable view of source-bound lens document candidates."""

    def __init__(
        self,
        definitions: Mapping[str, LensDefinition],
        *,
        definition_source_hash: str,
        composition_contract_hash: str,
        companion_hashes: Mapping[str, str],
        evidence_verifier: LensEvidenceVerifier | None,
        _loader_token: object | None = None,
    ) -> None:
        if _loader_token is not _REGISTRY_LOAD_TOKEN:
            raise LensError("LensRegistry must be loaded from the reviewed source bundle")
        if set(definitions) != _EXPECTED_IDS or any(
            key != value.ref.lens_id for key, value in definitions.items()
        ):
            raise LensError("registry definitions do not match the reviewed source bundle")
        _validate_hash(definition_source_hash, "definition_source_hash")
        _validate_hash(composition_contract_hash, "composition_contract_hash")
        if dict(companion_hashes) != dict(_APPROVED_BUNDLE_HASHES):
            raise LensError("registry companion hashes do not match the reviewed bundle")
        if evidence_verifier is not None and not all(
            callable(getattr(evidence_verifier, method, None))
            for method in (
                "verify_route",
                "verify_assessment",
                "verify_qualification",
                "verify_composition_input",
            )
        ):
            raise LensError("evidence_verifier does not implement the required boundary")
        self._definitions = MappingProxyType(dict(definitions))
        self.definition_source_hash = definition_source_hash
        self.composition_contract_hash = composition_contract_hash
        self.companion_hashes = MappingProxyType(dict(companion_hashes))
        self.bundle_id = "lens-bundle-" + _hash_bytes(
            "\n".join(f"{name}:{digest}" for name, digest in sorted(companion_hashes.items())).encode()
        )
        self._evidence_verifier = evidence_verifier
        self.__issuer_token = object()

    @classmethod
    def from_markdown(
        cls,
        definitions_path: Path | str,
        composition_path: Path | str,
        *,
        evidence_verifier: LensEvidenceVerifier | None = None,
    ) -> "LensRegistry":
        definitions_path = Path(definitions_path)
        composition_path = Path(composition_path)
        if (
            definitions_path.name != "definition-candidates.md"
            or composition_path.name != "composition-contract.md"
            or definitions_path.parent.resolve() != composition_path.parent.resolve()
        ):
            raise LensError("lens documents must be loaded from one reviewed bundle directory")
        definitions_text, definitions_raw = _read_bounded(
            definitions_path, "lens definitions"
        )
        composition_text, composition_raw = _read_bounded(
            composition_path, "composition contract"
        )
        bundle_raw = {
            "definition-candidates.md": definitions_raw,
            "composition-contract.md": composition_raw,
        }
        for companion in ("source-map.md", "review-report.md", "review-cases.md"):
            _, raw = _read_bounded(definitions_path.parent / companion, companion)
            bundle_raw[companion] = raw
        bundle_hashes = {name: _hash_bytes(raw) for name, raw in bundle_raw.items()}
        if bundle_hashes != dict(_APPROVED_BUNDLE_HASHES):
            raise LensError("lens draft-1 bytes do not match the reviewed bundle")

        anchor_positions = [definitions_text.find(anchor) for anchor in _DEFINITION_ANCHORS]
        if any(position < 0 for position in anchor_positions) or anchor_positions != sorted(anchor_positions):
            raise LensError("lens definitions are missing an ordered C1/C2/S0/R0 contract")
        for anchor in _COMPOSITION_ANCHORS:
            if anchor not in composition_text:
                raise LensError(f"composition contract is missing anchor: {anchor}")

        matches = tuple(_CARD_HEADER.finditer(definitions_text))
        ids = tuple(match.group("id") for match in matches)
        if len(ids) != len(_EXPECTED_IDS) or set(ids) != _EXPECTED_IDS or len(set(ids)) != len(ids):
            raise LensError("lens source must contain exactly the reviewed 17 card ids")

        source_hash = _hash_bytes(definitions_raw)
        composition_hash = _hash_bytes(composition_raw)
        parsed: dict[str, LensDefinition] = {}
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(definitions_text)
            section = definitions_text[match.start():end].rstrip() + "\n"
            lens_id = match.group("id")
            version = match.group("version")
            if version != "draft-1":
                raise LensError("all reviewed candidate cards must remain draft-1")

            source_scope = _line_field(section, "출처·원전 검토자/범위")
            claim_line = _line_field(section, "원전 주장")
            atomic_claim, remainder = _split_required(claim_line, "범위·반대 독해", "원전 주장")
            counter_reading, functional_layers = _split_required(
                remainder, "기능층", "원전 주장"
            )
            route_contract = _line_field(section, "경로별 전제 → 허용(C1)")
            observation = _line_field(section, "관찰 조건")
            observation_match = re.fullmatch(
                r"적용—(?P<yes>.+?)\s+비적용—(?P<no>.+?)\s+기권—(?P<abstain>.+)",
                observation,
            )
            if observation_match is None:
                raise LensError(f"{lens_id} has a malformed observation contract")

            question_line = _line_field(section, "판별 질문·예상 대비")
            contrast, disconfirmation = _split_required(
                question_line, "반증 단서", "판별 질문·예상 대비"
            )
            question_match = re.match(r"(?P<question>“[^”]+”)(?P<expected>.*)", contrast)
            if question_match is None or not question_match.group("expected").strip():
                raise LensError(f"{lens_id} must separate its question and expected contrast")

            prohibited = _line_field(section, "교란·금지")
            engineering_line = _line_field(section, "우리 공학 번역—설계 효과")
            engineering, after_reason = _split_required(
                engineering_line, "이유·예상 이점", "우리 공학 번역—설계 효과"
            )
            _, after_cost = _split_required(
                after_reason, "비용", "우리 공학 번역—설계 효과"
            )
            _, no_change = _split_no_change(after_cost)
            status = _line_field(section, "상태(R0)")
            if status != "문서 검토 통과(범위 R0) / 학술 미검토 / 실제 효과 미검증 / 운영 사용 미채택.":
                raise LensError(f"{lens_id} has an unsupported review status")

            # Bind each ref to both complete source contracts and its exact card.
            # A shared C1/C2/R0 or composition edit therefore cannot silently
            # inherit a qualification issued for an older document bundle.
            content_hash = _hash_bytes(
                bytes.fromhex(source_hash)
                + bytes.fromhex(composition_hash)
                + section.encode("utf-8")
            )
            ref = LensRef(lens_id, version, content_hash)
            parsed[lens_id] = LensDefinition(
                ref=ref,
                neutral_name=match.group("name").strip(),
                source_scope=source_scope,
                atomic_claim=atomic_claim,
                counter_reading=counter_reading,
                functional_layers=functional_layers.rstrip("."),
                route_contract=route_contract,
                applicability=observation_match.group("yes").strip(),
                non_applicability=observation_match.group("no").strip(),
                abstention_condition=observation_match.group("abstain").strip(),
                distinguishing_question=question_match.group("question"),
                expected_contrast=question_match.group("expected").strip(),
                disconfirmation=disconfirmation,
                confounders_and_prohibitions=prohibited,
                engineering_translation=engineering,
                no_change_condition=no_change,
            )
        return cls(
            parsed,
            definition_source_hash=source_hash,
            composition_contract_hash=composition_hash,
            companion_hashes=bundle_hashes,
            evidence_verifier=evidence_verifier,
            _loader_token=_REGISTRY_LOAD_TOKEN,
        )

    def ids(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def definitions(self) -> tuple[LensDefinition, ...]:
        return tuple(self._definitions.values())

    def get(self, lens_id: str) -> LensDefinition:
        try:
            return self._definitions[lens_id]
        except KeyError as exc:
            raise LensError("lens id is not in this source bundle") from exc

    def _current(self, ref: LensRef) -> LensDefinition:
        item = self.get(ref.lens_id)
        if item.ref != ref:
            raise LensError("lens ref does not match the loaded source bundle")
        return item

    def decide(
        self,
        lens_ref: LensRef,
        route: RouteEvidence,
        assessment: ApplicabilityAssessment,
        qualification: LensQualification | None,
    ) -> LensDecision:
        self._current(lens_ref)
        if not isinstance(route, RouteEvidence):
            raise LensError("route must be factory-validated RouteEvidence")
        if not isinstance(assessment, ApplicabilityAssessment):
            raise LensError("assessment must be factory-validated ApplicabilityAssessment")
        if assessment.lens_ref != lens_ref:
            raise LensError("applicability assessment ref mismatch")

        evidence = route.authorized_source_hashes + route.evidence_hashes + assessment.evidence_hashes

        def result(
            state: str,
            reason: str,
            extra: tuple[str, ...] = (),
            qualification_status: str = "absent",
        ) -> LensDecision:
            return _validated_instance(
                LensDecision,
                lens_ref=lens_ref,
                registry_bundle_id=self.bundle_id,
                path=route.path,
                scope_hash=route.scope_hash,
                alternative_scope=route.alternative_scope,
                qualification_status=qualification_status,
                state=state,
                reason=reason,
                evidence_hashes=evidence + extra,
                _issuer_token=self.__issuer_token,
            )

        if qualification is None:
            return result("abstained", "usage_unqualified")
        if not isinstance(qualification, LensQualification):
            raise LensError("qualification must be factory-validated LensQualification")
        if qualification.lens_ref != lens_ref:
            return result("abstained", "qualification_ref_mismatch")
        if qualification.path != route.path:
            return result("abstained", "qualification_path_mismatch")
        if qualification.scope_hash != route.scope_hash:
            return result("abstained", "qualification_scope_mismatch")

        qualified_evidence = (qualification.qualification_record_hash,)
        verifier = self._evidence_verifier
        try:
            qualification_trusted = (
                verifier is not None and verifier.verify_qualification(qualification) is True
            )
        except Exception:
            qualification_trusted = False
        if not qualification_trusted:
            return result(
                "abstained",
                "qualification_record_untrusted",
                qualified_evidence,
                qualification.status,
            )
        if qualification.status != "qualified":
            return result(
                "abstained",
                f"qualification_{qualification.status}",
                qualified_evidence,
                qualification.status,
            )
        try:
            route_trusted = verifier.verify_route(route) is True
            assessment_trusted = verifier.verify_assessment(assessment, route) is True
        except Exception:
            route_trusted = assessment_trusted = False
        if not route_trusted:
            return result(
                "abstained", "route_evidence_unverified", qualified_evidence, qualification.status
            )
        if not assessment_trusted:
            return result(
                "abstained", "applicability_evidence_unverified", qualified_evidence, qualification.status
            )
        if assessment.status == "unknown":
            return result(
                "abstained", "applicability_unknown", qualified_evidence, qualification.status
            )
        if assessment.status == "not_applicable":
            return result(
                "excluded", "not_applicable", qualified_evidence, qualification.status
            )
        if assessment.existing_process_duplicate:
            return result(
                "excluded", "existing_process_duplicate", qualified_evidence, qualification.status
            )
        return result(
            "proposed", "qualified_and_supported", qualified_evidence, qualification.status
        )

    def vouches_for(self, decision: object) -> bool:
        """True only for a LensDecision this exact registry instance issued.

        The issuer token is a per-instance capability, so a reconstructed or
        forged decision carrying a fabricated token cannot pass.
        """
        return (
            isinstance(decision, LensDecision)
            and decision._issuer_token is self.__issuer_token
        )

    def bind_composition_input(
        self,
        decision: LensDecision,
        *,
        judgment_key: str,
        judgment_ref: EntityRef,
        proposal_ref: EntityRef,
    ) -> CompositionInput:
        """Bind a lens proposal to verified, typed graph records.

        The label is presentation metadata, never canonical identity.  The
        application-supplied verifier must confirm both refs belong to this
        decision's exact graph and scope before composition can inspect them.
        """
        if not isinstance(decision, LensDecision):
            raise LensError("decision must be a registry-issued LensDecision")
        self._current(decision.lens_ref)
        if decision._issuer_token is not self.__issuer_token:
            raise LensError("decision was not issued by this registry instance")
        if decision.state != "proposed":
            raise LensError("only proposed decisions may bind composition inputs")
        key = judgment_key.strip() if isinstance(judgment_key, str) else ""
        if not key or len(key) > 128 or not re.fullmatch(r"[a-z0-9_:-]+", key):
            raise LensError("judgment_key must be a bounded machine identifier")
        if not isinstance(judgment_ref, EntityRef) or judgment_ref.kind != "design_decision":
            raise LensError("judgment_ref must be an immutable design_decision ref")
        if not isinstance(proposal_ref, EntityRef) or proposal_ref.kind != "design_decision":
            raise LensError("proposal_ref must be an immutable design_decision ref")
        item = _validated_instance(
            CompositionInput,
            lens_ref=decision.lens_ref,
            judgment_key=key,
            judgment_ref=judgment_ref,
            proposal_ref=proposal_ref,
            _decision=decision,
            _issuer_token=self.__issuer_token,
        )
        verifier = self._evidence_verifier
        try:
            trusted = (
                verifier is not None
                and verifier.verify_composition_input(item, decision) is True
            )
        except Exception:
            trusted = False
        if not trusted:
            raise LensError("composition input is not backed by the graph evidence store")
        return item

    def linked_refs(self, ref: LensRef) -> tuple[LensRef, ...]:
        self._current(ref)
        links = {
            "L-P030-01": ("L-P030-02",),
            "L-P030-02": ("L-P030-01",),
        }
        return tuple(self.get(lens_id).ref for lens_id in links.get(ref.lens_id, ()))

    def effect_evidence_groups(
        self, refs: Iterable[LensRef]
    ) -> tuple[tuple[LensRef, ...], ...]:
        ordered = tuple(refs)
        if len(set(ordered)) != len(ordered):
            raise LensError("effect evidence refs must be unique")
        for ref in ordered:
            self._current(ref)
        kant = {"L-P030-01", "L-P030-02"}
        selected = {ref.lens_id: ref for ref in ordered}
        groups: list[tuple[LensRef, ...]] = []
        consumed: set[str] = set()
        if kant <= set(selected):
            groups.append((selected["L-P030-01"], selected["L-P030-02"]))
            consumed.update(kant)
        groups.extend((ref,) for ref in ordered if ref.lens_id not in consumed)
        return tuple(groups)

    def compose(
        self,
        decisions: Iterable[LensDecision],
        inputs: Iterable[CompositionInput],
        *,
        required_constraints_satisfied: bool,
    ) -> CompositionResult:
        decisions_tuple = tuple(decisions)
        inputs_tuple = tuple(inputs)
        if not decisions_tuple or not inputs_tuple:
            raise LensError("composition requires proposed decisions and inputs")
        if not isinstance(required_constraints_satisfied, bool):
            raise LensError("required_constraints_satisfied must be boolean")
        if any(not isinstance(decision, LensDecision) for decision in decisions_tuple):
            raise LensError("decision must be a registry-issued LensDecision")
        if any(not isinstance(item, CompositionInput) for item in inputs_tuple):
            raise LensError("input must be a registry-bound CompositionInput")
        decision_by_ref = {decision.lens_ref: decision for decision in decisions_tuple}
        if len(decision_by_ref) != len(decisions_tuple):
            raise LensError("proposed decision refs must be unique")
        inputs_by_ref: dict[LensRef, list[CompositionInput]] = defaultdict(list)
        contribution_keys: set[tuple[LensRef, tuple[str, str, int]]] = set()
        for item in inputs_tuple:
            contribution_key = (item.lens_ref, item.judgment_identity)
            if contribution_key in contribution_keys:
                raise LensError("one lens may contribute only once to one judgment ref")
            contribution_keys.add(contribution_key)
            inputs_by_ref[item.lens_ref].append(item)
        if set(decision_by_ref) != set(inputs_by_ref):
            raise LensError("every proposed decision requires at least one composition input")
        for ref, decision in decision_by_ref.items():
            self._current(ref)
            if decision._issuer_token is not self.__issuer_token:
                raise LensError("decision was not issued by this registry instance")
            if decision.registry_bundle_id != self.bundle_id:
                raise LensError("decision was not issued by this registry bundle")
            if decision.state != "proposed":
                raise LensError("only proposed decisions may be composed")
            for item in inputs_by_ref[ref]:
                if item._issuer_token is not self.__issuer_token:
                    raise LensError("composition input was not bound by this registry instance")
                if item._decision is not decision:
                    raise LensError("composition input was bound to a different decision")
                verifier = self._evidence_verifier
                try:
                    trusted = (
                        verifier is not None
                        and verifier.verify_composition_input(item, decision) is True
                    )
                except Exception:
                    trusted = False
                if not trusted:
                    raise LensError("composition input is no longer backed by graph evidence")
        contexts = {
            (decision.path, decision.scope_hash, decision.alternative_scope)
            for decision in decisions_tuple
        }
        if len(contexts) != 1:
            raise LensError("composition decisions must share one path, scope and alternative scope")
        path, scope_hash, alternative_scope = next(iter(contexts))
        if not required_constraints_satisfied:
            return CompositionResult(
                "rejected_required_constraint",
                path,
                scope_hash,
                alternative_scope,
                (),
                (),
            )

        aliases: dict[str, tuple[str, str, int]] = {}
        grouped: dict[tuple[str, str, int], list[CompositionInput]] = defaultdict(list)
        for item in inputs_tuple:
            prior_identity = aliases.setdefault(item.judgment_key, item.judgment_identity)
            if prior_identity != item.judgment_identity:
                raise LensError("one judgment key cannot name multiple canonical graph refs")
            grouped[item.judgment_identity].append(item)

        conflicts: list[CompositionConflict] = []
        duplicates: list[tuple[LensRef, LensRef]] = []
        for group in grouped.values():
            judgment_ref_hash = group[0].judgment_ref_hash
            if any(item.judgment_ref_hash != judgment_ref_hash for item in group):
                raise LensError("canonical judgment ref has conflicting immutable content")
            distinct_hashes = tuple(dict.fromkeys(item.proposal_hash for item in group))
            by_proposal: dict[str, list[CompositionInput]] = defaultdict(list)
            for item in group:
                by_proposal[item.proposal_hash].append(item)
            for duplicate_group in by_proposal.values():
                if len(duplicate_group) > 1:
                    duplicates.extend(
                        (left.lens_ref, right.lens_ref)
                        for left, right in combinations(duplicate_group, 2)
                    )
            if len(distinct_hashes) > 1:
                conflicts.append(
                    CompositionConflict(
                        group[0].judgment_key,
                        judgment_ref_hash,
                        tuple(dict.fromkeys(item.judgment_key for item in group)),
                        tuple((item.lens_ref, item.proposal_hash) for item in group),
                    )
                )

        if conflicts:
            state = "unresolved_conflict"
        elif duplicates:
            state = "redundant"
        else:
            state = "complementary"
        return CompositionResult(
            state,
            path,
            scope_hash,
            alternative_scope,
            tuple(conflicts),
            tuple(duplicates),
        )


__all__ = [
    "ApplicabilityAssessment",
    "CompositionInput",
    "CompositionResult",
    "LensDecision",
    "LensDefinition",
    "LensEvidenceVerifier",
    "LensError",
    "LensQualification",
    "LensRef",
    "LensRegistry",
    "RouteEvidence",
]
