"""Closed immutable record profiles for provider conformance history."""

from hashlib import sha256
import re

from .refs import DomainContractError, EntityRef, canonical_json, uuid_string


VECTOR_IDS = ("text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
              "catalog-negative-capability-v1")
FAILURES = frozenset({"connection_unavailable", "identity_mismatch", "source_changed",
    "protocol_error", "deadline", "observation_limit", "interrupted", "owner_revoked",
    "storage_unavailable"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_INSTANCE = re.compile(r"[0-9a-f]{32}\Z")
_SERVICE = re.compile(r"[a-z][a-z0-9]*(?:[-_.][a-z0-9]+)*\Z")


def _fail():
    raise DomainContractError("Invalid provider conformance record")


def _exact(value, fields):
    if type(value) is not dict or set(value) != set(fields):
        _fail()


def _integer(value, low=0, high=2**63 - 1):
    if type(value) is not int or not low <= value <= high:
        _fail()
    return value


def _hash(value):
    if type(value) is not str or _HASH.fullmatch(value) is None:
        _fail()


def _ref(value, kind, version):
    try:
        result = EntityRef.from_dict(value)
    except DomainContractError:
        _fail()
    if result.kind != kind or result.version != version:
        _fail()
    return result


def _subject(value):
    fields = ("vault_id", "instance_id", "origin_digest", "topology_id",
        "source_context_sha256", "provider_geometry_sha256", "installation_ref", "candidate_ref",
        "request_ref", "receipt_ref", "platform", "selected_platform_entry_digest",
        "image_manifest_digest", "service_descriptor_digest", "service_identity", "slot_id",
        "build_identity_digest", "port_schema_set_digest", "port_contract_version",
        "worker_profile", "implemented_transforms")
    _exact(value, fields)
    try:
        uuid_string(value["vault_id"]); uuid_string(value["topology_id"])
    except DomainContractError:
        _fail()
    if type(value["instance_id"]) is not str or _INSTANCE.fullmatch(value["instance_id"]) is None:
        _fail()
    for name in ("origin_digest", "source_context_sha256", "provider_geometry_sha256",
                 "selected_platform_entry_digest", "service_descriptor_digest",
                 "build_identity_digest", "port_schema_set_digest"):
        _hash(value[name])
    if (type(value["image_manifest_digest"]) is not str
            or not value["image_manifest_digest"].startswith("sha256:")):
        _fail()
    _hash(value["image_manifest_digest"][7:])
    _ref(value["installation_ref"], "extension_installation", 1)
    _ref(value["candidate_ref"], "extension_manifest", 1)
    _ref(value["request_ref"], "deployment_request", 1)
    _ref(value["receipt_ref"], "deployment_receipt", 1)
    if (value["platform"] not in ("linux/amd64", "linux/arm64")
            or type(value["service_identity"]) is not str
            or len(value["service_identity"]) > 64
            or _SERVICE.fullmatch(value["service_identity"]) is None
            or value["port_contract_version"] != "provider-port-v1"
            or value["worker_profile"] != "claude-text-transform-v1"
            or value["implemented_transforms"] != ["catalog", "text"]):
        _fail()
    _integer(value["slot_id"], 1, 16)


def _intent(body, content):
    fields = ("schema_version", "command_id", "request_sha256", "installation_ref", "subject",
        "context_sha256", "suite_version", "suite_sha256", "requester_version",
        "comparator_version", "admitted_ms", "deadline_ms")
    _exact(content, fields)
    if (content["schema_version"] != "provider-conformance-intent-v1"
            or content["suite_version"] != "private-provider-conformance-v1"
            or content["requester_version"] != "private-provider-requester-v1"
            or content["comparator_version"] != "private-provider-literal-oracle-v1"):
        _fail()
    try:
        uuid_string(content["command_id"])
    except DomainContractError:
        _fail()
    _hash(content["request_sha256"]); _hash(content["context_sha256"]); _hash(content["suite_sha256"])
    installation = _ref(content["installation_ref"], "extension_installation", 1)
    _subject(content["subject"])
    if (content["subject"]["installation_ref"] != content["installation_ref"]
            or sha256(canonical_json(content["subject"])).hexdigest() != content["context_sha256"]):
        _fail()
    admitted = _integer(content["admitted_ms"], 0, 253402300739999)
    if type(content["deadline_ms"]) is not int or content["deadline_ms"] != admitted + 60000:
        _fail()
    if (body["version"] != 1 or body["id"] != content["command_id"]
            or body["purpose"] != "operational"
            or body["parent_refs"] != [installation.as_dict()] or len(canonical_json(content)) > 8192):
        _fail()


def _report(body, content):
    from .store import BlobRef

    fields = ("schema_version", "command_id", "intent_ref", "installation_ref", "context_sha256",
        "suite_sha256", "finished_ms", "elapsed_ms", "observations_blob_ref", "completion", "reason",
        "vectors", "covered_subchecks", "recovery_command_id")
    _exact(content, fields)
    if content["schema_version"] != "provider-conformance-report-v1":
        _fail()
    try:
        uuid_string(content["command_id"])
    except DomainContractError:
        _fail()
    intent = _ref(content["intent_ref"], "provider_conformance_run", 1)
    installation = _ref(content["installation_ref"], "extension_installation", 1)
    _hash(content["context_sha256"]); _hash(content["suite_sha256"])
    _integer(content["finished_ms"], 0, 253402300799999)
    if content["elapsed_ms"] is not None:
        _integer(content["elapsed_ms"])
    if content["observations_blob_ref"] is not None:
        try:
            blob = BlobRef.from_dict(content["observations_blob_ref"])
        except (DomainContractError, ValueError, TypeError):
            _fail()
        if blob.purpose != "operational" or blob.size > 1048576:
            _fail()
    if content["completion"] not in ("matched", "mismatch", "incomplete"):
        _fail()
    if content["reason"] not in ({"compared"} | FAILURES):
        _fail()
    vectors = content["vectors"]
    if type(vectors) is not list or len(vectors) != 4:
        _fail()
    comparisons = []
    for expected, vector in zip(VECTOR_IDS, vectors, strict=True):
        _exact(vector, ("vector_id", "comparison"))
        if vector["vector_id"] != expected or vector["comparison"] not in (
                "matched", "mismatch", "not_observed"):
            _fail()
        comparisons.append(vector["comparison"])
    covered = content["covered_subchecks"]
    if (type(covered) is not list or covered != [vector_id for vector_id, comparison
            in zip(VECTOR_IDS, comparisons, strict=True) if comparison == "matched"]):
        _fail()
    recovery = content["recovery_command_id"]
    if content["reason"] == "interrupted":
        try:
            uuid_string(recovery)
        except DomainContractError:
            _fail()
        if (content["completion"] != "incomplete" or content["elapsed_ms"] is not None
                or content["observations_blob_ref"] is not None
                or comparisons != ["not_observed"] * 4):
            _fail()
    else:
        if recovery is not None or content["elapsed_ms"] is None or content["observations_blob_ref"] is None:
            _fail()
    if content["completion"] == "matched" and (content["reason"] != "compared"
            or comparisons != ["matched"] * 4):
        _fail()
    if content["completion"] == "mismatch" and not (
            content["reason"] == "identity_mismatch"
            or content["reason"] == "compared" and "mismatch" in comparisons):
        _fail()
    if (body["version"] != 2 or body["id"] != content["command_id"] or intent.id != body["id"]
            or body["purpose"] != "operational"
            or body["parent_refs"] != [intent.as_dict(), installation.as_dict()]
            or len(canonical_json(content)) > 65536):
        _fail()


def validate_body(body):
    if type(body) is not dict or body.get("kind") != "provider_conformance_run":
        _fail()
    content = body.get("content")
    if type(content) is not dict:
        _fail()
    if content.get('schema_version') in ('provider-conformance-intent-v2','provider-conformance-report-v2'):
        _verified_body(body,content)
        return
    if body.get("version") == 1:
        _intent(body, content)
    elif body.get("version") == 2:
        _report(body, content)
    else:
        _fail()


def _admission(value):
    _exact(value,('schema_version','stage_subject','stage_context_sha256','staged_installation_ref',
        'verified_installation_ref','installation_head_hash','release_review_sha256','verification_source_context_sha256'))
    if value['schema_version'] != 'provider-conformance-verified-admission-v1': _fail()
    _subject(value['stage_subject'])
    stage = _ref(value['staged_installation_ref'],'extension_installation',1)
    verified = _ref(value['verified_installation_ref'],'extension_installation',2)
    for name in ('stage_context_sha256','installation_head_hash','release_review_sha256','verification_source_context_sha256'):
        _hash(value[name])
    if (stage.id != verified.id or value['stage_subject']['installation_ref'] != stage.as_dict()
            or sha256(canonical_json(value['stage_subject'])).hexdigest() != value['stage_context_sha256']): _fail()


def _verified_body(body,content):
    stage = _ref(content.get('staged_installation_ref'),'extension_installation',1)
    verified = _ref(content.get('verified_installation_ref'),'extension_installation',2)
    if stage.id != verified.id: _fail()
    _hash(content.get('admission_sha256'))
    projected = {key:value for key,value in content.items() if key not in (
        'staged_installation_ref','verified_installation_ref','admission','admission_sha256','stage_context_sha256')}
    projected['installation_ref'] = stage.as_dict()
    if content['schema_version'] == 'provider-conformance-intent-v2':
        _exact(content,('schema_version','command_id','request_sha256','staged_installation_ref','verified_installation_ref',
            'admission','admission_sha256','suite_version','suite_sha256','requester_version','comparator_version','admitted_ms','deadline_ms'))
        _admission(content['admission'])
        admission = content['admission']
        if (admission['staged_installation_ref'] != stage.as_dict() or admission['verified_installation_ref'] != verified.as_dict()
                or sha256(canonical_json(admission)).hexdigest() != content['admission_sha256']
                or admission['stage_context_sha256'] == content['admission_sha256']
                or body['parent_refs'] != [stage.as_dict(),verified.as_dict()]
                or len(canonical_json(content)) > 16384): _fail()
        projected.update(schema_version='provider-conformance-intent-v1',subject=admission['stage_subject'],
            context_sha256=admission['stage_context_sha256'])
        _intent({**body,'parent_refs':[stage.as_dict()]},projected)
    else:
        _exact(content,('schema_version','command_id','intent_ref','staged_installation_ref','verified_installation_ref',
            'admission_sha256','stage_context_sha256','suite_sha256','finished_ms','elapsed_ms','observations_blob_ref',
            'completion','reason','vectors','covered_subchecks','recovery_command_id'))
        _hash(content['stage_context_sha256'])
        if content['stage_context_sha256'] == content['admission_sha256']: _fail()
        intent = _ref(content['intent_ref'],'provider_conformance_run',1)
        if body['parent_refs'] != [intent.as_dict(),stage.as_dict(),verified.as_dict()]: _fail()
        projected.update(schema_version='provider-conformance-report-v1',context_sha256=content['stage_context_sha256'])
        _report({**body,'parent_refs':[intent.as_dict(),stage.as_dict()]},projected)


def content_schema():
    """Detached closed structural schemas; runtime enforces cross-field identity joins."""
    from copy import deepcopy
    from ..extensions.provider_conformance_schema_exports import _intent_content, _report_content, _verified_intent_content, _verified_report_content

    return {"oneOf": [deepcopy(_intent_content()), deepcopy(_report_content()),
        deepcopy(_verified_intent_content()),deepcopy(_verified_report_content())]}
