import json
from pathlib import Path

from app.domain.events import EVENT_TYPES
from app.domain.refs import ENTITY_KINDS
from app.domain.schema_exports import domain_schema, events_schema


def test_original_profiles_export_closed_variants_and_preserve_generic_history(tmp_path):
    import copy

    import pytest
    from jsonschema import Draft202012Validator

    from app.domain.refs import EntityRef
    from app.domain.schemas import ImmutableRecord
    from app.tests.test_owner_material_intake import material_work, upload
    from app.tests.test_works_api import owner_app

    validator = Draft202012Validator(domain_schema())
    with owner_app(tmp_path) as subject:
        response = material_work(subject)
        assert response.status_code == 201, response.text
        saved = upload(subject, response.json()).json()
        revision = subject.domain.get(EntityRef.from_dict(saved["ref"]))
        source = subject.domain.get(EntityRef.from_dict(saved["source_refs"][0]))
        artifact = subject.domain.get(EntityRef.from_dict(source.body["content"]["artifact_ref"]))
        for record in [revision, source, artifact]:
            validator.validate(record.as_dict())
            changed = copy.deepcopy(record.as_dict())
            changed["body"]["content"]["invented_claim"] = True
            assert list(validator.iter_errors(changed))
        for record in [source, artifact]:
            changed = copy.deepcopy(record.as_dict())
            changed["body"]["version"] = 2
            changed["ref"]["version"] = 2
            assert list(validator.iter_errors(changed)), "Original source/artifact are version-one profiles"
        content = artifact.body["content"]
        roots = subject.domain.roots()
        for changes in [{"size": content["size"] + 1}, {"rights": "invented license"}, {"format_validation": "valid"}]:
            with pytest.raises(ValueError):
                ImmutableRecord.create(kind="artifact", id=artifact.ref.id, version=1,
                    created_at_utc=artifact.body["created_at_utc"], actor_ref=roots.actor, parent_refs=(), purpose="operational",
                    access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
                    content={**content, **changes})
        # Generic historical artifacts are not subjected to this feature's schema.
        generic = ImmutableRecord.create(kind="artifact", id=artifact.ref.id, version=1,
            created_at_utc=artifact.body["created_at_utc"], actor_ref=roots.actor, parent_refs=(), purpose="operational",
            access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
            content={"schema_version": {"historical": "generic"}, "text": "unchanged"})
        validator.validate(generic.as_dict())


ROOT = Path(__file__).resolve().parents[2] / "schemas" / "v1"


def test_domain_schema_export_matches_runtime_envelope_contract():
    schema = domain_schema()
    assert schema == json.loads((ROOT / "domain-envelopes.schema.json").read_text())
    assert set(schema["$defs"]["EntityRef"]["properties"]["kind"]["enum"]) == ENTITY_KINDS
    for name in ("EntityRef", "ObjectRef", "DomainBody", "GenesisBody", "BootstrapBody", "Record"):
        assert schema["$defs"][name]["additionalProperties"] is False


def test_event_schema_export_has_exact_registered_payloads():
    schema = events_schema()
    assert schema == json.loads((ROOT / "event-metadata.schema.json").read_text())
    assert set(schema["$defs"]) == EVENT_TYPES
    assert all(value["additionalProperties"] is False for value in schema["$defs"].values())
