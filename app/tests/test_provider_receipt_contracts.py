"""Independent signatures against actual prepared requests and retained public trust."""

from uuid import uuid4

import pytest
from copy import deepcopy
from nacl.signing import VerifyKey

from app.deployment.prepare_contracts import DeploymentPrepareError
from app.domain.refs import canonical_json, parse_canonical
from app.operations.setup import parse_base64url_32
from app.tests.provider_receipt_fixture import provider_receipt_context, signed_receipt
from app.tests.provider_receipt_fixture import resign
from app.deployment.receipt_contracts import ReceiptWireError


@pytest.mark.parametrize("content", [None, [], "not-an-object", 1])
@pytest.mark.parametrize("kind", ["receipt", "installation"])
def test_existing_anchor_invalid_content_retains_domain_error_partition(content, kind):
    from app.domain.deployment_receipt import validate_receipt_body
    from app.domain.extension_installation import validate_installation_body
    from app.domain.refs import DomainContractError

    validate = (
        validate_receipt_body if kind == "receipt" else validate_installation_body
    )
    with pytest.raises(DomainContractError):
        validate({"content": content})


def test_signed_receipt_validation_and_independent_tampering(tmp_path, monkeypatch):
    from app.deployment.provider_receipt_contracts import verify_provider_receipt

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        kwargs = dict(
            request_bytes=canonical_json(request),
            trust_bytes=actual.tree.bundle[12][1],
            source_bundle_files=actual.tree.bundle,
            profile=actual.profile,
        )
        for outcome in ("succeeded", "failed", "unknown"):
            raw = signed_receipt(actual, request, outcome=outcome)
            assert verify_provider_receipt(raw, **kwargs)["outcome"] == outcome
            forged = parse_canonical(raw)
            forged["key_id"] = str(uuid4())
            with pytest.raises(ReceiptWireError):
                verify_provider_receipt(canonical_json(forged), **kwargs)


@pytest.mark.parametrize(
    "preservation",
    [{"state": "not_attempted"}, {"state": "preserved", "observations": []}],
)
def test_resigned_failed_empty_observations_cannot_reverse_time(
    tmp_path, monkeypatch, preservation
):
    from app.deployment.provider_receipt_contracts import verify_provider_receipt

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        value = parse_canonical(
            signed_receipt(actual, request, outcome="failed", preservation=preservation)
        )
        value["started_at"] = request["expires_at"]
        with pytest.raises(ReceiptWireError):
            verify_provider_receipt(
                resign(actual, value),
                request_bytes=canonical_json(request),
                trust_bytes=actual.tree.bundle[12][1],
                source_bundle_files=actual.tree.bundle,
                profile=actual.profile,
            )


def test_synthetic_fixture_uses_real_startup_and_prepared_request(
    tmp_path, monkeypatch
):
    from base64 import urlsafe_b64decode

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        value = parse_canonical(raw)
        trust = parse_canonical(
            dict(actual.context.read_current())["provider-trust-set.json"]
        )
        preimage = canonical_json({k: v for k, v in value.items() if k != "signature"})
        assert (
            VerifyKey(parse_base64url_32(trust["keys"][0]["public_key"])).verify(
                preimage, urlsafe_b64decode(value["signature"] + "==")
            )
            == preimage
        )
        assert value["request_id"] == prepared["request_id"]


def test_import_revision_rejects_bool_after_real_parser_is_available():
    from app.deployment.provider_receipt_contracts import parse_provider_receipt_import

    value = {
        "command_id": str(uuid4()),
        "request_digest": "A" * 43,
        "receipt_digest": "A" * 43,
        "expected_revision": True,
    }
    with pytest.raises(DeploymentPrepareError) as caught:
        parse_provider_receipt_import(str(uuid4()), value)
    assert caught.value.code == "invalid_input"


def test_closed_receipt_fields_crypto_and_source_binding_matrix(tmp_path, monkeypatch):
    from app.deployment.provider_receipt_contracts import (
        parse_provider_receipt,
        verify_provider_receipt,
        ReceiptRequestMismatch,
    )

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        reply = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, reply["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        value = parse_canonical(raw)
        kwargs = dict(
            request_bytes=canonical_json(request),
            trust_bytes=actual.tree.bundle[12][1],
            source_bundle_files=actual.tree.bundle,
            profile=actual.profile,
        )
        for field in value:
            missing = {k: v for k, v in value.items() if k != field}
            with pytest.raises(ReceiptWireError):
                parse_provider_receipt(canonical_json(missing))
        for forged in (
            {**value, "extra": 1},
            {**value, "signature": "A" * 86},
            {**value, "operator_adapter": "other"},
            {
                **value,
                "claimed_facts": ["request_binding"],
                "verified_facts": ["request_binding"],
            },
        ):
            with pytest.raises(ReceiptWireError):
                verify_provider_receipt(canonical_json(forged), **kwargs)
        for field in ("request_id", "request_digest", "request_nonce"):
            forged = deepcopy(value)
            forged[field] = str(uuid4()) if field == "request_id" else "A" * 43
            with pytest.raises(ReceiptRequestMismatch):
                verify_provider_receipt(resign(actual, forged), **kwargs)
        for field in (
            "manifest_digest",
            "service_descriptor_digest",
            "selected_platform_entry_digest",
        ):
            forged = deepcopy(value)
            forged["effect_result"]["new_service"][field] = "0" * 64
            with pytest.raises(ReceiptRequestMismatch):
                verify_provider_receipt(resign(actual, forged), **kwargs)
        for malformed in (
            raw + b" ",
            b"\xef\xbb\xbf" + raw,
            raw[:-1] + b',"signature":"x"}',
            b" " * 16385,
        ):
            with pytest.raises(ReceiptWireError):
                parse_provider_receipt(malformed)


@pytest.mark.parametrize("revision", [False, True, 0, 1.0, "1", None, 2])
def test_import_selector_exact_types(revision):
    from app.deployment.provider_receipt_contracts import parse_provider_receipt_import

    with pytest.raises(DeploymentPrepareError):
        parse_provider_receipt_import(
            str(uuid4()),
            {
                "command_id": str(uuid4()),
                "request_digest": "A" * 43,
                "receipt_digest": "A" * 43,
                "expected_revision": revision,
            },
        )


def test_channel_identity_cannot_mutate_retained_observation(tmp_path, monkeypatch):
    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        identity, _ = actual.context._provider_receipt_observation()
        original = identity.as_dict()
        exported = identity.as_dict()
        exported["incoming"]["root"]["inode"] += 1
        assert identity.as_dict() == original
        with pytest.raises(TypeError):
            identity.incoming["root"]["inode"] += 1


def test_every_signed_field_and_all_eight_result_arms(tmp_path, monkeypatch):
    from app.deployment.provider_receipt_contracts import (
        verify_provider_receipt,
        parse_provider_receipt,
    )

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        kwargs = dict(
            request_bytes=canonical_json(request),
            trust_bytes=actual.tree.bundle[12][1],
            source_bundle_files=actual.tree.bundle,
            profile=actual.profile,
        )
        base = parse_canonical(signed_receipt(actual, request))
        for field, current in base.items():
            changed = deepcopy(base)
            if isinstance(current, str):
                changed[field] = ("B" if current[:1] != "B" else "C") + current[1:]
            elif type(current) is dict:
                changed[field]["preserved_inventory_sha256"] = "0" * 64
            elif type(current) is list:
                changed[field] = ["request_binding"]
            else:
                changed[field] = "effect_failed"
            with pytest.raises(ReceiptWireError):
                verify_provider_receipt(canonical_json(changed), **kwargs)
        arms = [
            ("succeeded", "present", "preserved"),
            ("failed", "absent", "not_attempted"),
            ("failed", "absent", "preserved"),
            ("failed", "absent", "unconfirmed"),
            ("failed", "unknown", "preserved"),
            ("failed", "unknown", "unconfirmed"),
            ("unknown", "unknown", "preserved"),
            ("unknown", "unknown", "unconfirmed"),
        ]
        for outcome, presence, preservation in arms:
            value = parse_canonical(
                signed_receipt(
                    actual,
                    request,
                    outcome="unknown" if presence == "unknown" else outcome,
                )
            )
            value["outcome"] = outcome
            value["failure_class"] = (
                None
                if outcome == "succeeded"
                else "observation_unavailable"
                if outcome == "unknown"
                else "effect_failed"
            )
            value["effect_result"]["preservation"] = {
                "state": preservation,
                **(
                    {"observations": []}
                    if preservation == "preserved"
                    else {"failure_class": "observation_unavailable"}
                    if preservation == "unconfirmed"
                    else {}
                ),
            }
            assert (
                verify_provider_receipt(resign(actual, value), **kwargs)["outcome"]
                == outcome
            )
        for version in ("deployment-receipt-v1", "deployment-provider-receipt-v2"):
            with pytest.raises(ReceiptWireError):
                parse_provider_receipt(canonical_json({**base, "schema": version}))


def test_one_preserved_snapshot_binds_native_config_and_nanosecond_time(
    tmp_path, monkeypatch
):
    from app.deployment.provider_receipt_contracts import verify_provider_receipt

    with provider_receipt_context(
        tmp_path.resolve(), monkeypatch, slot_id=2, legacy_staged=True
    ) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        base = parse_canonical(signed_receipt(actual, request))
        kwargs = dict(
            request_bytes=canonical_json(request),
            trust_bytes=actual.tree.bundle[12][1],
            source_bundle_files=actual.tree.bundle,
            profile=actual.profile,
        )
        assert (
            len(
                verify_provider_receipt(resign(actual, base), **kwargs)[
                    "effect_result"
                ]["preservation"]["observations"]
            )
            == 1
        )
        for field in (
            "configured_uid",
            "configured_gid",
            "socket_volume",
            "socket_path",
            "started_at",
            "container_id",
            "restart_count",
            "init_pid",
            "image_config_digest",
        ):
            changed = deepcopy(base)
            snapshot = changed["effect_result"]["preservation"]["observations"][0][
                "after"
            ]
            snapshot[field] = (
                snapshot[field] + 1 if type(snapshot[field]) is int else "invalid"
            )
            with pytest.raises(ReceiptWireError):
                verify_provider_receipt(resign(actual, changed), **kwargs)
        doubled = deepcopy(base)
        doubled["effect_result"]["preservation"]["observations"] *= 2
        with pytest.raises(ReceiptWireError):
            verify_provider_receipt(resign(actual, doubled), **kwargs)
