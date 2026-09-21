"""Closed values for the fixed private-provider conformance protocol."""

from base64 import b64decode, b64encode
from dataclasses import dataclass
import re

from ..domain.refs import DomainContractError, EntityRef, canonical_json, parse_canonical, uuid_string


class ConformanceError(ValueError):
    def __init__(self, code="invalid_input"):
        self.code = code
        super().__init__(code)


ERROR_CODES = frozenset({"invalid_input", "unauthenticated", "access_denied", "not_found",
                         "conflict", "too_large", "capacity", "unavailable"})
FAILURE_CODES = frozenset({"connection_unavailable", "identity_mismatch", "source_changed",
    "protocol_error", "deadline", "observation_limit", "interrupted", "owner_revoked",
    "storage_unavailable"})
VECTOR_IDS = ("text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
              "catalog-negative-capability-v1")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_BROKER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")


def _invalid():
    raise ConformanceError("invalid_input")


def _exact(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        _invalid()
    return value


def _integer(value, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        _invalid()
    return value


def _hash(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _invalid()
    return value


def _uuid(value):
    try:
        return uuid_string(value)
    except DomainContractError:
        _invalid()


def _ref(value, kind, version):
    try:
        result = EntityRef.from_dict(value)
    except DomainContractError:
        _invalid()
    if result.kind != kind or result.version != version:
        _invalid()
    return result


@dataclass(frozen=True, slots=True, init=False)
class ConformanceSubject:
    vault_id: str
    instance_id: str
    origin_digest: str
    topology_id: str
    source_context_sha256: str
    provider_geometry_sha256: str
    installation_ref: EntityRef
    candidate_ref: EntityRef
    request_ref: EntityRef
    receipt_ref: EntityRef
    platform: str
    selected_platform_entry_digest: str
    image_manifest_digest: str
    service_descriptor_digest: str
    service_identity: str
    slot_id: int
    build_identity_digest: str
    port_schema_set_digest: str
    port_contract_version: str
    worker_profile: str
    implemented_transforms: tuple[str, str]
    uid: int
    gid: int

    def __new__(cls, *args, **kwargs):
        raise TypeError("ConformanceSubject is resolver-owned")

    def as_dict(self):
        return {"vault_id": self.vault_id, "instance_id": self.instance_id,
            "origin_digest": self.origin_digest, "topology_id": self.topology_id,
            "source_context_sha256": self.source_context_sha256,
            "provider_geometry_sha256": self.provider_geometry_sha256,
            "installation_ref": self.installation_ref.as_dict(),
            "candidate_ref": self.candidate_ref.as_dict(), "request_ref": self.request_ref.as_dict(),
            "receipt_ref": self.receipt_ref.as_dict(), "platform": self.platform,
            "selected_platform_entry_digest": self.selected_platform_entry_digest,
            "image_manifest_digest": self.image_manifest_digest,
            "service_descriptor_digest": self.service_descriptor_digest,
            "service_identity": self.service_identity, "slot_id": self.slot_id,
            "build_identity_digest": self.build_identity_digest,
            "port_schema_set_digest": self.port_schema_set_digest,
            "port_contract_version": self.port_contract_version,
            "worker_profile": self.worker_profile,
            "implemented_transforms": list(self.implemented_transforms)}


@dataclass(frozen=True, slots=True)
class ConformanceCapture:
    content_bytes: bytes

    def __post_init__(self):
        if type(self.content_bytes) is not bytes:
            _invalid()


@dataclass(frozen=True, slots=True)
class ConformanceComparison:
    completion: str
    reason: str
    vectors: tuple[tuple[str, str], ...]
    covered_subchecks: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RehydratedConformance:
    intent_ref: EntityRef
    report_ref: EntityRef
    subject: ConformanceSubject
    comparison: ConformanceComparison
    capture_bytes: bytes | None


@dataclass(frozen=True, slots=True, init=False)
class ConformanceVerifiedAdmission:
    stage_subject: ConformanceSubject
    stage_context_sha256: str
    staged_installation_ref: EntityRef
    verified_installation_ref: EntityRef
    installation_head_hash: str
    release_review_sha256: str
    verification_source_context_sha256: str

    def __new__(cls, *args, **kwargs):
        raise TypeError('ConformanceVerifiedAdmission is resolver-owned')

    def as_dict(self):
        return {'schema_version':'provider-conformance-verified-admission-v1',
            'stage_subject':self.stage_subject.as_dict(),'stage_context_sha256':self.stage_context_sha256,
            'staged_installation_ref':self.staged_installation_ref.as_dict(),
            'verified_installation_ref':self.verified_installation_ref.as_dict(),
            'installation_head_hash':self.installation_head_hash,'release_review_sha256':self.release_review_sha256,
            'verification_source_context_sha256':self.verification_source_context_sha256}


@dataclass(frozen=True, slots=True)
class RehydratedVerifiedConformance:
    intent_ref: EntityRef
    report_ref: EntityRef
    admission: ConformanceVerifiedAdmission
    comparison: ConformanceComparison
    capture_bytes: bytes | None


def parse_command(value):
    try:
        if type(value) is dict and value.get('schema_version') == 'provider-conformance-command-v2':
            _exact(value,('schema_version','command_id','staged_installation_ref','expected_verified_installation_ref'))
            stage = _ref(value['staged_installation_ref'],'extension_installation',1)
            verified = _ref(value['expected_verified_installation_ref'],'extension_installation',2)
            if stage.id != verified.id: _invalid()
        else:
            _exact(value, ("command_id", "installation_ref"))
            _ref(value["installation_ref"], "extension_installation", 1)
        _uuid(value["command_id"])
        detached = parse_canonical(canonical_json(value))
        if len(canonical_json(detached)) > 4096:
            _invalid()
        return detached
    except ConformanceError:
        raise
    except (DomainContractError, ValueError, TypeError, UnicodeError, RecursionError, MemoryError):
        _invalid()


def _connection(value):
    _exact(value, ("connection_id", "requester_boot_id", "responder_boot_id", "generation_id",
                   "listener_sha256", "peer_pid", "peer_uid", "peer_gid"))
    _hash(value["connection_id"]); _hash(value["generation_id"]); _hash(value["listener_sha256"])
    if (type(value["requester_boot_id"]) is not str
            or _BROKER_ID.fullmatch(value["requester_boot_id"]) is None
            or type(value["responder_boot_id"]) is not str
            or _BROKER_ID.fullmatch(value["responder_boot_id"]) is None):
        _invalid()
    _integer(value["peer_pid"], 1, 2**31 - 1)
    _integer(value["peer_uid"], 0, 2**32 - 1); _integer(value["peer_gid"], 0, 2**32 - 1)


def _frame(value):
    _exact(value, ("direction", "message_id", "correlation_id", "message_type", "payload_chunks"))
    if value["direction"] not in ("sent", "received") or value["message_type"] not in (
            "extension-request-v1", "extension-result-v1", "extension-artifact-v1"):
        _invalid()
    _uuid(value["message_id"])
    if value["correlation_id"] is not None:
        _uuid(value["correlation_id"])
    chunks = value["payload_chunks"]
    if type(chunks) is not list or not chunks:
        _invalid()
    total = 0
    for index, encoded in enumerate(chunks):
        if type(encoded) is not str or len(encoded) > 32768:
            _invalid()
        try:
            raw = b64decode(encoded.encode("ascii"), validate=True)
        except (ValueError, UnicodeError):
            _invalid()
        if b64encode(raw).decode("ascii") != encoded or len(raw) > 24576:
            _invalid()
        if index < len(chunks) - 1 and len(raw) != 24576:
            _invalid()
        if not raw and not (len(chunks) == 1 and encoded == ""):
            _invalid()
        total += len(raw)
    return total


def parse_capture(raw):
    try:
        if type(raw) is not bytes or not raw or len(raw) > 1048576:
            _invalid()
        value = parse_canonical(raw)
        _exact(value, ("schema_version", "context_sha256", "suite_sha256", "started_ms",
                       "finished_ms", "elapsed_ms", "attempts"))
        if value["schema_version"] != "provider-conformance-observations-v1":
            _invalid()
        _hash(value["context_sha256"]); _hash(value["suite_sha256"])
        start = _integer(value["started_ms"], 0, 253402300799999)
        finish = _integer(value["finished_ms"], start, 253402300799999)
        _integer(value["elapsed_ms"])
        attempts = value["attempts"]
        roles = ("identify-before", *VECTOR_IDS, "identify-after")
        if type(attempts) is not list or not 1 <= len(attempts) <= 6:
            _invalid()
        frames = 0
        stopped = False
        for index, attempt in enumerate(attempts):
            _exact(attempt, ("role", "connection", "frames", "failure"))
            if (stopped or attempt["role"] != roles[index]
                    or type(attempt["frames"]) is not list):
                _invalid()
            if attempt["connection"] is None:
                if attempt["frames"] or attempt["failure"] is None:
                    _invalid()
            else:
                _connection(attempt["connection"])
            if attempt["failure"] is not None and attempt["failure"] not in FAILURE_CODES:
                _invalid()
            for frame in attempt["frames"]:
                _frame(frame); frames += 1
                if frames > 256:
                    _invalid()
            stopped = attempt["failure"] is not None
        return ConformanceCapture(bytes(raw))
    except ConformanceError:
        raise
    except (DomainContractError, ValueError, TypeError, UnicodeError, RecursionError, MemoryError):
        _invalid()


def parse_reply(raw):
    try:
        if type(raw) is not bytes or not raw or len(raw) > 8192:
            _invalid()
        value = parse_canonical(raw)
        if value.get('schema_version') == 'provider-conformance-reply-v2':
            _exact(value,('schema_version','command_id','staged_installation_ref','verified_installation_ref',
                'intent_ref','result_ref','state','suite_version','suite_sha256','stage_context_sha256',
                'admission_sha256','completed_count','matched_count','event_cursor','links'))
            stage = _ref(value['staged_installation_ref'],'extension_installation',1)
            verified = _ref(value['verified_installation_ref'],'extension_installation',2)
            if stage.id != verified.id: _invalid()
            _hash(value['admission_sha256']); _hash(value['stage_context_sha256'])
            if value['admission_sha256'] == value['stage_context_sha256']: _invalid()
            projected = {key:child for key,child in value.items() if key not in (
                'staged_installation_ref','verified_installation_ref','admission_sha256','stage_context_sha256')}
            projected.update(schema_version='provider-conformance-reply-v1',installation_ref=stage.as_dict(),
                context_sha256=value['stage_context_sha256'])
            parse_reply(canonical_json(projected))
            return value
        _exact(value, ("schema_version", "command_id", "installation_ref", "intent_ref",
                       "result_ref", "state", "suite_version", "suite_sha256", "context_sha256",
                       "completed_count", "matched_count", "event_cursor", "links"))
        if (value["schema_version"] != "provider-conformance-reply-v1"
                or value["suite_version"] != "private-provider-conformance-v1"):
            _invalid()
        command_id = _uuid(value["command_id"])
        _ref(value["installation_ref"], "extension_installation", 1)
        intent = _ref(value["intent_ref"], "provider_conformance_run", 1)
        if intent.id != command_id or value["state"] not in ("pending", "matched", "mismatch", "incomplete"):
            _invalid()
        _hash(value["suite_sha256"]); _hash(value["context_sha256"])
        completed = _integer(value["completed_count"], 0, 4)
        matched = _integer(value["matched_count"], 0, completed)
        if type(value["event_cursor"]) is not str or not 1 <= len(value["event_cursor"]) <= 4096:
            _invalid()
        _exact(value["links"], ("self", "events"))
        if (value["links"]["self"] != "/api/v1/extensions/provider-conformance/" + command_id
                or value["links"]["events"] != "/api/v1/events"):
            _invalid()
        if value["state"] == "pending":
            if value["result_ref"] is not None or completed != 0 or matched != 0:
                _invalid()
        else:
            result = _ref(value["result_ref"], "provider_conformance_run", 2)
            if result.id != command_id:
                _invalid()
            if value["state"] == "matched" and (completed != 4 or matched != 4):
                _invalid()
        return value
    except ConformanceError:
        raise
    except (DomainContractError, ValueError, TypeError, UnicodeError, RecursionError, MemoryError):
        _invalid()
