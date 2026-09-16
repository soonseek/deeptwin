"""Pure v2 prepare codecs are closed structural helpers, never admission."""

import importlib
import os
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest

from app.domain.refs import canonical_json
from app.tests.deployment_source_fixture import profile
from app.tests.test_deployment_prepare_contracts import matching_bundle


def implementation():
    try:
        return importlib.import_module("app.deployment.prepare_v2_contracts")
    except ModuleNotFoundError:
        pytest.fail("Deployment prepare v2 contracts are missing")


def command_input(*, revision=1):
    return {
        "command_id": str(uuid4()),
        "request_digest": "A" * 43,
        "expected_revision": revision,
    }


def import_input(*, revision=1):
    return {**command_input(revision=revision), "receipt_digest": "E" * 43}


def accepted_request(origin):
    from app.deployment.prepare_contracts import make_request

    bundle, topology, slot = matching_bundle()
    return make_request(
        bundle=bundle,
        topology=topology,
        slot=slot,
        profile=origin,
        request_id="12345678-1234-4234-8234-123456789abc",
        nonce=b"n" * 32,
        actor_ref={
            "kind": "actor",
            "id": "87654321-4321-4321-8321-cba987654321",
            "version": 1,
            "sha256": "b" * 64,
        },
        created_ms=1_700_000_000_000,
        ttl_seconds=60,
    )


@pytest.mark.parametrize("revision", [1, 2, 3])
def test_cancel_and_import_inputs_retain_route_identity_for_supported_revisions(
    revision,
):
    module = implementation()
    request_id = str(uuid4())
    cancel = command_input(revision=revision)
    receipt = import_input(revision=revision)
    assert module.parse_cancel_v2(request_id, cancel) == {
        **cancel,
        "request_id": request_id,
    }
    assert module.parse_receipt_import(request_id, receipt) == {
        **receipt,
        "request_id": request_id,
    }


@pytest.mark.parametrize(
    "parser,value",
    [
        ("parse_cancel_v2", {**command_input(), "extra": "private-canary"}),
        (
            "parse_cancel_v2",
            {k: v for k, v in command_input().items() if k != "command_id"},
        ),
        ("parse_cancel_v2", {**command_input(), "command_id": "not-a-uuid"}),
        ("parse_cancel_v2", {**command_input(), "request_digest": "A" * 42 + "B"}),
        ("parse_cancel_v2", {**command_input(), "expected_revision": True}),
        ("parse_cancel_v2", {**command_input(), "expected_revision": 4}),
        ("parse_receipt_import", {**import_input(), "receipt_digest": "A" * 43 + "="}),
        ("parse_receipt_import", {**import_input(), "receipt_digest": "A" * 42 + "B"}),
    ],
)
def test_v2_command_inputs_reject_closed_type_uuid_and_b32_violations(parser, value):
    module = implementation()
    with pytest.raises(module.DeploymentPrepareError) as error:
        getattr(module, parser)(str(uuid4()), value)
    assert error.value.code in {"invalid_input", "too_large"}
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize("parser", ["parse_cancel_v2", "parse_receipt_import"])
def test_v2_command_inputs_reject_route_uuid_mismatch_and_oversize(parser):
    module = implementation()
    payload = command_input() if parser == "parse_cancel_v2" else import_input()
    with pytest.raises(module.DeploymentPrepareError):
        getattr(module, parser)("00000000-0000-0000-0000-000000000000", payload)
    with pytest.raises(module.DeploymentPrepareError) as error:
        getattr(module, parser)(str(uuid4()), {**payload, "command_id": "x" * 4097})
    assert error.value.code == "too_large"
    with pytest.raises(module.DeploymentPrepareError):
        getattr(module, parser)(str(uuid4()), {**payload, "request_id": str(uuid4())})


def marker(origin, *, revision=3):
    from app.deployment.prepare_contracts import b64

    request = accepted_request(origin)
    return {
        "schema": "deployment-cancellation-v2",
        "domain": "deeptwin-deployment-cancellation-v2",
        "request_id": request["request_id"],
        "request_digest": request["request_digest"],
        "instance_id": origin.instance_id,
        "origin_profile_digest": b64(bytes.fromhex(origin.digest)),
        "lifecycle_revision": revision,
        "cancelled_at": "2023-11-14T22:13:20.123Z",
    }


@pytest.mark.parametrize("portable", [False, True])
@pytest.mark.parametrize("revision", [2, 3])
def test_cancellation_v2_parser_accepts_exact_canonical_marker(portable, revision):
    module = implementation()
    origin = profile(portable)
    value = marker(origin, revision=revision)
    raw = canonical_json(value)
    assert (
        module.parse_cancellation_v2(
            request_digest=value["request_digest"], payload=raw, profile=origin
        )
        == value
    )


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "bool_revision",
        "unsupported_revision",
        "route_digest",
        "bad_uuid",
        "bad_b32",
        "bad_time",
        "noncanonical",
        "oversize",
    ],
)
def test_cancellation_v2_parser_rejects_closed_canonical_and_binding_violations(change):
    module = implementation()
    origin = profile()
    value = marker(origin)
    request_digest = value["request_digest"]
    if change == "missing":
        del value["cancelled_at"]
    elif change == "extra":
        value["extra"] = "private-canary"
    elif change == "bool_revision":
        value["lifecycle_revision"] = True
    elif change == "unsupported_revision":
        value["lifecycle_revision"] = 1
    elif change == "route_digest":
        request_digest = "I" * 43
    elif change == "bad_uuid":
        value["request_id"] = "00000000-0000-0000-0000-000000000000"
    elif change == "bad_b32":
        value["request_digest"] = "A" * 42 + "B"
        request_digest = value["request_digest"]
    elif change == "bad_time":
        value["cancelled_at"] = "2023-02-30T22:13:20.123Z"
    raw = canonical_json(value)
    if change == "noncanonical":
        raw = b'{"schema": "deployment-cancellation-v2"}'
    elif change == "oversize":
        raw = raw + b" " * 4097
    with pytest.raises(module.DeploymentPrepareError) as error:
        module.parse_cancellation_v2(
            request_digest=request_digest, payload=raw, profile=origin
        )
    assert error.value.code == "invalid_input"
    assert "private-canary" not in str(error.value)


@pytest.mark.parametrize("bad_profile", [None, {}, "private-profile-canary"])
def test_cancellation_v2_parser_requires_exact_origin_profile(bad_profile):
    module = implementation()
    origin = profile()
    value = marker(origin)
    with pytest.raises(module.DeploymentPrepareError):
        module.parse_cancellation_v2(
            request_digest=value["request_digest"],
            payload=canonical_json(value),
            profile=bad_profile,
        )


def test_cancellation_v2_emitter_reparses_request_and_emits_revision_three():
    module = implementation()
    origin = profile()
    request = accepted_request(origin)
    before = deepcopy(request)
    raw = module.cancellation_v2(request, 1_700_000_000_123, profile=origin)
    parsed = module.parse_cancellation_v2(
        request_digest=request["request_digest"], payload=raw, profile=origin
    )
    assert parsed == marker(origin, revision=3)
    assert request == before
    with pytest.raises(module.DeploymentPrepareError):
        module.cancellation_v2(
            {**request, "request_digest": "A" * 43},
            1_700_000_000_123,
            profile=origin,
        )


def test_successful_pure_parsing_returns_only_fresh_inert_dictionaries():
    module = implementation()
    request_id = str(uuid4())
    value = import_input()
    first = module.parse_receipt_import(request_id, value)
    first["command_id"] = str(uuid4())
    assert module.parse_receipt_import(request_id, value) == {
        **value,
        "request_id": request_id,
    }


def test_fresh_structure_import_loads_no_crypto_reader_owner_http_or_service():
    root = os.fspath(Path(__file__).resolve().parents[2])
    program = """
import sys
import app.deployment.prepare_v2_contracts
import app.domain.deployment_receipt
forbidden = {
    'nacl',
    'app.deployment.receipt_sources',
    'app.deployment.sources',
    'app.deployment.prepare_service',
    'app.services.owner_auth',
    'app.api.deployment_prepare',
}
assert forbidden.isdisjoint(sys.modules), forbidden & set(sys.modules)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = root
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", "-c", program],
        cwd=root,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
