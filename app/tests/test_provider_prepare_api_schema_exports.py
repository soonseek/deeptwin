"""Closed response schemas and the frozen provider-v1 core schema projection."""

import importlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from app.deployment.provider_prepare_records import _provider_schema_bytes
from app.tests.test_provider_lineage import shipped_schema_bytes


def test_three_fresh_exports_and_four_frozen_core_schema_bytes():
    module = importlib.import_module(
        "app.deployment.provider_prepare_api_schema_exports"
    )
    exports = module.exported_schemas()
    assert set(exports) == {
        "provider-command-receipt-v1.schema.json",
        "provider-request-read-v1.schema.json",
        "provider-prepare-api-v1.schema.json",
    }
    root = Path(__file__).resolve().parents[2] / "schemas/v2/deployment"
    for name, schema in exports.items():
        Draft202012Validator.check_schema(schema)
        assert (root / name).read_bytes() == (
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        assert schema[
            "$id"
        ] == "urn:deeptwin:schemas:v2:deployment:" + name.removesuffix(".schema.json")
    exports.clear()
    assert len(module.exported_schemas()) == 3
    assert _provider_schema_bytes() == shipped_schema_bytes()


def test_prepared_receipt_is_closed_and_requires_null_cancellation_state():
    module = importlib.import_module(
        "app.deployment.provider_prepare_api_schema_exports"
    )
    identity = "11111111-1111-4111-8111-111111111111"
    value = {
        "command_id": identity,
        "request_id": identity,
        "request_digest": "A" * 43,
        "kind": "extension_stage",
        "state": "prepared",
        "revision": 1,
        "publication_state": "pending",
        "cancellation_publication_state": None,
        "source_context_sha256": "1" * 64,
        "preserved_inventory_sha256": "2" * 64,
        "event_cursor": "frozen",
        "links": {
            "self": "/api/v1/deployment/provider-requests/" + identity,
            "cancel": "/api/v1/deployment/provider-requests/" + identity + "/cancel",
            "events": "/api/v1/events",
        },
    }
    validator = Draft202012Validator(module.provider_command_receipt_schema())
    assert validator.is_valid(value)
    for changed in (
        {"extra": True},
        {"revision": 2},
        {"publication_state": "published"},
        {"cancellation_publication_state": "pending"},
        {"event_cursor": "x" * 4097},
    ):
        assert not validator.is_valid({**value, **changed})
