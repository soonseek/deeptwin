"""Versioned prepare schemas describe shapes without granting lifecycle authority."""

import importlib
import json
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from app.tests.deployment_source_fixture import profile
from app.tests.test_deployment_prepare_v2_contracts import (
    accepted_request,
    command_input,
    import_input,
    marker,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "schemas/v1/deployment"


def implementation():
    return importlib.import_module("app.deployment.prepare_v2_schema_exports")


def validator(schema):
    return Draft202012Validator(schema, format_checker=FormatChecker())


def state(*, state, revision, receipt=None, consumption=None):
    return {
        "request_id": str(uuid4()),
        "request_digest": "A" * 43,
        "kind": "extension_stage",
        "state": state,
        "revision": revision,
        "publication_state": "suppressed" if revision > 1 else "pending",
        "cancellation_publication_state": "pending" if state == "cancelled" else None,
        "receipt": receipt,
        "consumption_publication_state": consumption,
        "request": accepted_request(profile()),
        "links": {
            "self": "/api/v1/deployment/requests/" + str(uuid4()),
            "cancel": "/api/v1/deployment/requests/" + str(uuid4()) + "/cancel",
            "events": "/api/v1/events",
        },
    }


def receipt(outcome="succeeded"):
    return {
        "receipt_digest": "E" * 43,
        "outcome": outcome,
        "disposition": (
            "pending_postconditions"
            if outcome == "succeeded"
            else "consumed_non_success"
        ),
        "import_revision": 2,
    }


def test_exact_two_exports_are_detached_and_match_fresh_artifact_bytes(tmp_path):
    module = implementation()
    values = module.exported_schemas()
    assert set(values) == {
        "prepare-api-v2.schema.json",
        "cancellation-v2.schema.json",
    }
    for name, schema in values.items():
        Draft202012Validator.check_schema(schema)
        assert schema["$id"] == (
            "urn:deeptwin:schemas:v1:deployment:" + name.removesuffix(".schema.json")
        )
        assert "Structural only" in schema["$comment"]
    values["prepare-api-v2.schema.json"].clear()
    assert implementation().exported_schemas()["prepare-api-v2.schema.json"]
    module.write_schemas(tmp_path)
    for name, schema in module.exported_schemas().items():
        expected = (
            json.dumps(schema, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
        assert (tmp_path / name).read_bytes() == expected
        assert (ARTIFACT_ROOT / name).read_bytes() == expected


def test_v2_command_schemas_accept_inputs_and_reject_bool_extra_or_revision_four():
    module = implementation()
    cancel = validator(module.cancel_input_schema())
    imported = validator(module.receipt_import_input_schema())
    assert all(cancel.is_valid(command_input(revision=value)) for value in (1, 2, 3))
    assert all(imported.is_valid(import_input(revision=value)) for value in (1, 2, 3))
    for bad in (
        {**command_input(), "expected_revision": True},
        {**command_input(), "expected_revision": 4},
        {**command_input(), "extra": None},
    ):
        assert not cancel.is_valid(bad)
    assert not imported.is_valid({**import_input(), "receipt_digest": "A" * 42 + "B"})


def test_cancellation_schema_accepts_revision_two_or_three_and_is_closed():
    schema = implementation().cancellation_schema()
    check = validator(schema)
    origin = profile()
    assert check.is_valid(marker(origin, revision=2))
    assert check.is_valid(marker(origin, revision=3))
    assert not check.is_valid(marker(origin, revision=1))
    assert not check.is_valid({**marker(origin), "future": None})


def test_current_read_schema_covers_exact_state_receipt_consumption_combinations():
    check = validator(implementation().read_schema())
    valid = [
        state(state="prepared", revision=1),
        state(state="cancelled", revision=2),
        state(state="expired", revision=2),
        state(state="receipt_pending", revision=2, receipt=receipt()),
        state(
            state="rejected",
            revision=2,
            receipt=receipt("failed"),
            consumption="pending",
        ),
        state(
            state="rejected",
            revision=2,
            receipt=receipt("unknown"),
            consumption="published",
        ),
        state(state="cancelled", revision=3, receipt=receipt()),
        state(state="expired", revision=3, receipt=receipt()),
    ]
    assert all(check.is_valid(value) for value in valid)
    invalid = [
        {**valid[0], "receipt": receipt()},
        {**valid[3], "receipt": None},
        {**valid[4], "consumption_publication_state": None},
        {**valid[4], "receipt": receipt()},
        {**valid[6], "receipt": None},
        {**valid[7], "cancellation_publication_state": "pending"},
        {k: v for k, v in valid[0].items() if k != "receipt"},
    ]
    assert not any(check.is_valid(value) for value in invalid)


def test_historical_receipts_stay_frozen_while_revision_three_and_import_are_explicit():
    module = implementation()
    historical = state(state="prepared", revision=1)
    historical.pop("receipt")
    historical.pop("consumption_publication_state")
    historical.pop("request")
    historical.update(command_id=str(uuid4()), event_cursor="cursor")
    check = validator(module.command_receipt_schema())
    assert check.is_valid(historical)
    assert not check.is_valid({**historical, "receipt": None})
    cancelled = {
        **historical,
        "state": "cancelled",
        "revision": 3,
        "publication_state": "suppressed",
        "cancellation_publication_state": "pending",
    }
    assert check.is_valid(cancelled)
    imported = {
        "command_id": str(uuid4()),
        "request_id": str(uuid4()),
        "receipt_digest": "E" * 43,
        "outcome": "unknown",
        "disposition": "consumed_non_success",
        "revision": 2,
        "event_cursor": "cursor",
    }
    assert validator(module.import_receipt_schema()).is_valid(imported)
    assert not validator(module.import_receipt_schema()).is_valid(
        {**imported, "consumption_publication_state": "pending"}
    )


def test_structural_validity_does_not_prove_currentness_correspondence_or_approval():
    module = implementation()
    origin = profile()
    supplied = deepcopy(marker(origin))
    supplied["request_id"] = str(uuid4())
    assert validator(module.cancellation_schema()).is_valid(supplied)
    assert validator(module.receipt_import_input_schema()).is_valid(import_input())
