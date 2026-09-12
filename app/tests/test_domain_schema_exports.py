import json
from pathlib import Path

from app.domain.schema_exports import domain_schema, events_schema
from app.domain.refs import ENTITY_KINDS
from app.domain.events import EVENT_TYPES


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
