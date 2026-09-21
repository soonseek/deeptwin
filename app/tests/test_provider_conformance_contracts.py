from dataclasses import FrozenInstanceError
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator

from app.domain.refs import EntityRef, canonical_json
from app.domain.provider_conformance import content_schema
from app.domain.events import event_metadata
from app.domain.schemas import ImmutableRecord
from app.extensions.provider_conformance_contracts import (
    ConformanceCapture,
    ConformanceError,
    ConformanceSubject,
    parse_capture,
    parse_command,
    parse_reply,
)
from app.extensions.provider_conformance_schema_exports import exported_schemas, write_schemas


def _ref(kind="extension_installation", version=1):
    return EntityRef(kind=kind, id=str(uuid4()), version=version, sha256="a" * 64)


def test_command_is_closed_bounded_and_strictly_typed():
    command = {"command_id": str(uuid4()), "installation_ref": _ref().as_dict()}
    assert parse_command(command) == command
    for bad in (
        command | {"vector": "text-basic-v1"},
        command | {"command_id": None},
        command | {"installation_ref": _ref(version=2).as_dict()},
        {"command_id": True, "installation_ref": command["installation_ref"]},
    ):
        with pytest.raises(ConformanceError) as caught:
            parse_command(bad)
        assert caught.value.code == "invalid_input"


def test_subject_refuses_caller_construction_and_has_no_mutable_aliases():
    with pytest.raises(TypeError):
        ConformanceSubject()
    assert ConformanceSubject.__dataclass_params__.frozen is True
    assert ConformanceSubject.__slots__


def test_capture_parser_is_canonical_closed_and_returns_immutable_bytes():
    capture = {"schema_version": "provider-conformance-observations-v1",
        "context_sha256": "a" * 64, "suite_sha256": "b" * 64,
        "started_ms": 1, "finished_ms": 2, "elapsed_ms": 1,
        "attempts": [{"role": "identify-before", "connection": None, "frames": [],
            "failure": "connection_unavailable"}]}
    raw = canonical_json(capture)
    parsed = parse_capture(raw)
    assert type(parsed) is ConformanceCapture and parsed.content_bytes == raw
    with pytest.raises(FrozenInstanceError):
        parsed.content_bytes = b"{}"
    for bad in (raw + b" ", canonical_json(capture | {"secret": "x"}),
                canonical_json(capture | {"started_ms": True})):
        with pytest.raises(ConformanceError):
            parse_capture(bad)


def test_reply_parser_requires_exact_pending_or_terminal_shape():
    installation = _ref()
    intent = EntityRef(kind="provider_conformance_run", id=str(uuid4()), version=1, sha256="b" * 64)
    pending = {"schema_version": "provider-conformance-reply-v1", "command_id": intent.id,
        "installation_ref": installation.as_dict(), "intent_ref": intent.as_dict(),
        "result_ref": None, "state": "pending", "suite_version": "private-provider-conformance-v1",
        "suite_sha256": "c" * 64, "context_sha256": "d" * 64, "completed_count": 0,
        "matched_count": 0, "event_cursor": "cursor", "links": {"self": "/api/v1/extensions/provider-conformance/" + intent.id,
            "events": "/api/v1/events"}}
    assert parse_reply(canonical_json(pending)) == pending
    report = _ref("provider_conformance_run", 2).as_dict() | {"id": intent.id}
    matched = pending | {"result_ref": report, "state": "matched",
                         "completed_count": 4, "matched_count": 4}
    mismatch = pending | {"result_ref": report, "state": "mismatch",
                          "completed_count": 0, "matched_count": 0}
    incomplete = pending | {"result_ref": report, "state": "incomplete",
                            "completed_count": 4, "matched_count": 4}
    for value in (matched, mismatch, incomplete):
        assert parse_reply(canonical_json(value)) == value
    for bad in (pending | {"state": "matched"}, pending | {"matched_count": True},
                pending | {"result_ref": intent.as_dict()}, pending | {"extra": None},
                matched | {"completed_count": 0, "matched_count": 0},
                mismatch | {"completed_count": 1, "matched_count": 2}):
        with pytest.raises(ConformanceError):
            parse_reply(canonical_json(bad))

    validator = Draft202012Validator(
        exported_schemas()["provider-conformance-reply-v1.schema.json"])
    for value in (pending, matched, mismatch, incomplete):
        validator.validate(value)
    for value in (pending | {"state": "matched"},
                  matched | {"result_ref": None},
                  matched | {"completed_count": 0, "matched_count": 0},
                  mismatch | {"completed_count": 1, "matched_count": 2}):
        assert list(validator.iter_errors(value))


def _subject_projection(installation, candidate, request, receipt):
    return {"vault_id": str(uuid4()), "instance_id": "1" * 32, "origin_digest": "2" * 64,
        "topology_id": str(uuid4()), "source_context_sha256": "3" * 64,
        "provider_geometry_sha256": "4" * 64, "installation_ref": installation.as_dict(),
        "candidate_ref": candidate.as_dict(), "request_ref": request.as_dict(),
        "receipt_ref": receipt.as_dict(), "platform": "linux/amd64",
        "selected_platform_entry_digest": "5" * 64,
        "image_manifest_digest": "sha256:" + "6" * 64, "service_descriptor_digest": "7" * 64,
        "service_identity": "extension-provider-slot-1", "slot_id": 1,
        "build_identity_digest": "8" * 64, "port_schema_set_digest": "9" * 64,
        "port_contract_version": "provider-port-v1", "worker_profile": "claude-text-transform-v1",
        "implemented_transforms": ["catalog", "text"]}


def _record(version, content, parents):
    roots = {"actor": _ref("actor"), "access": _ref("access_policy"),
        "retention": _ref("retention_policy")}
    return ImmutableRecord.create(kind="provider_conformance_run", id=content["command_id"],
        version=version, created_at_utc="2026-09-20T00:00:00.001000Z",
        actor_ref=roots["actor"], parent_refs=parents, purpose="operational",
        access_policy_ref=roots["access"], retention_policy_ref=roots["retention"], content=content)


def test_new_kind_accepts_only_exact_intent_and_terminal_profiles():
    command_id = str(uuid4())
    installation = _ref(); candidate = _ref("extension_manifest"); request = _ref("deployment_request")
    receipt = _ref("deployment_receipt")
    subject = _subject_projection(installation, candidate, request, receipt)
    intent_content = {"schema_version": "provider-conformance-intent-v1", "command_id": command_id,
        "request_sha256": "a" * 64, "installation_ref": installation.as_dict(),
        "subject": subject, "context_sha256": __import__("hashlib").sha256(canonical_json(subject)).hexdigest(),
        "suite_version": "private-provider-conformance-v1",
        "suite_sha256": "c" * 64, "requester_version": "private-provider-requester-v1",
        "comparator_version": "private-provider-literal-oracle-v1", "admitted_ms": 1,
        "deadline_ms": 60001}
    intent = _record(1, intent_content, (installation,))
    report_content = {"schema_version": "provider-conformance-report-v1", "command_id": command_id,
        "intent_ref": intent.ref.as_dict(), "installation_ref": installation.as_dict(),
        "context_sha256": intent_content["context_sha256"], "suite_sha256": "c" * 64, "finished_ms": 2,
        "elapsed_ms": None, "observations_blob_ref": None, "completion": "incomplete",
        "reason": "interrupted", "vectors": [{"vector_id": value, "comparison": "not_observed"}
            for value in ("text-basic-v1", "text-refusal-v1", "catalog-two-pages-v1",
                "catalog-negative-capability-v1")], "covered_subchecks": [],
        "recovery_command_id": str(uuid4())}
    report = _record(2, report_content, (intent.ref, installation))
    assert intent.ref.version == 1 and report.ref.version == 2
    for bad in (
        intent_content | {"deadline_ms": 60002},
        intent_content | {"subject": intent_content["subject"] | {"uid": 501}},
        report_content | {"completion": "matched"},
        report_content | {"covered_subchecks": ["text-basic-v1"]},
    ):
        with pytest.raises(Exception):
            _record(1 if bad.get("schema_version") == "provider-conformance-intent-v1" else 2,
                    bad, (installation,) if bad.get("schema_version") == "provider-conformance-intent-v1"
                    else (intent.ref, installation))


def test_conformance_events_require_exact_closed_metadata():
    assert event_metadata("provider.conformance_started", {"vector_count": 4}) == {"vector_count": 4}
    completed = {"completed_count": 4, "matched_count": 4, "outcome": "matched"}
    assert event_metadata("provider.conformance_completed", completed) == completed
    for event_type, payload in (("provider.conformance_started", {}),
            ("provider.conformance_started", {"vector_count": 3}),
            ("provider.conformance_completed", completed | {"matched_count": 5}),
            ("provider.conformance_completed", completed | {"secret": "x"})):
        with pytest.raises(Exception):
            event_metadata(event_type, payload)


def test_three_detached_schema_exports_validate_closed_runtime_examples(tmp_path):
    schemas = exported_schemas()
    assert set(schemas) == {"provider-conformance-input-v1.schema.json",
        "provider-conformance-reply-v1.schema.json", "provider-conformance-record-v1.schema.json"}
    assert all(schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
               for schema in schemas.values())
    for name in ("provider-conformance-input-v1.schema.json", "provider-conformance-reply-v1.schema.json"):
        assert len(schemas[name]['oneOf']) == 2
        assert all(arm['type'] == 'object' and arm['additionalProperties'] is False
                   for arm in schemas[name]['oneOf'])
    assert schemas['provider-conformance-record-v1.schema.json']['additionalProperties'] is False
    command = {"command_id": str(uuid4()), "installation_ref": _ref().as_dict()}
    validator = Draft202012Validator(schemas["provider-conformance-input-v1.schema.json"])
    validator.validate(command)
    assert list(validator.iter_errors(command | {"model": "arbitrary"}))
    stage = EntityRef.from_dict(command['installation_ref'])
    verified = EntityRef(stage.kind, stage.id, 2, 'b' * 64)
    explicit = {'schema_version': 'provider-conformance-command-v2',
                'command_id': command['command_id'], 'staged_installation_ref': stage.as_dict(),
                'expected_verified_installation_ref': verified.as_dict()}
    for value in (command, explicit):
        assert parse_command(value) == value
        validator.validate(value)
        bad = value | {'model': 'arbitrary'}
        assert list(validator.iter_errors(bad))
        with pytest.raises(ConformanceError): parse_command(bad)
    intent = EntityRef('provider_conformance_run', command['command_id'], 1, 'c' * 64)
    reply = {'schema_version': 'provider-conformance-reply-v1', 'command_id': intent.id,
        'installation_ref': stage.as_dict(), 'intent_ref': intent.as_dict(), 'result_ref': None,
        'state': 'pending', 'suite_version': 'private-provider-conformance-v1', 'suite_sha256': 'd' * 64,
        'context_sha256': 'e' * 64, 'completed_count': 0, 'matched_count': 0, 'event_cursor': 'cursor',
        'links': {'self': '/api/v1/extensions/provider-conformance/' + intent.id, 'events': '/api/v1/events'}}
    explicit_reply = {key: value for key, value in reply.items()
                      if key not in ('installation_ref', 'context_sha256')}
    explicit_reply.update(schema_version='provider-conformance-reply-v2',
        staged_installation_ref=stage.as_dict(), verified_installation_ref=verified.as_dict(),
        stage_context_sha256='e' * 64, admission_sha256='f' * 64)
    reply_validator = Draft202012Validator(schemas['provider-conformance-reply-v1.schema.json'])
    for value in (reply, explicit_reply):
        assert parse_reply(canonical_json(value)) == value
        reply_validator.validate(value)
        bad = value | {'model': 'arbitrary'}
        assert list(reply_validator.iter_errors(bad))
        with pytest.raises(ConformanceError): parse_reply(canonical_json(bad))
    destination = tmp_path / "schemas"
    write_schemas(destination)
    assert {path.name for path in destination.iterdir()} == set(schemas)
    for name, schema in schemas.items():
        assert (destination / name).read_text() == __import__("json").dumps(
            schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def test_record_export_binds_outer_ref_version_and_domain_content_is_closed():
    command_id = str(uuid4())
    installation = _ref(); candidate = _ref("extension_manifest")
    request = _ref("deployment_request"); receipt = _ref("deployment_receipt")
    subject = _subject_projection(installation, candidate, request, receipt)
    content = {"schema_version": "provider-conformance-intent-v1", "command_id": command_id,
        "request_sha256": "a" * 64, "installation_ref": installation.as_dict(),
        "subject": subject, "context_sha256": __import__("hashlib").sha256(
            canonical_json(subject)).hexdigest(),
        "suite_version": "private-provider-conformance-v1", "suite_sha256": "c" * 64,
        "requester_version": "private-provider-requester-v1",
        "comparator_version": "private-provider-literal-oracle-v1", "admitted_ms": 1,
        "deadline_ms": 60001}
    intent = _record(1, content, (installation,))
    envelope = intent.as_dict()
    validator = Draft202012Validator(
        exported_schemas()["provider-conformance-record-v1.schema.json"])
    validator.validate(envelope)
    assert list(validator.iter_errors(envelope | {"ref": envelope["ref"] | {"version": 2}}))
    detached = content_schema()
    Draft202012Validator(detached).validate(content)
    assert detached["oneOf"][0]["additionalProperties"] is False
    assert list(Draft202012Validator(detached).iter_errors(content | {"extra": None}))
