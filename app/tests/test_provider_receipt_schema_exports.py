"""Provider receipt boundary vocabulary and detached schema artifacts."""

from app.deployment.provider_receipt_schema_exports import exported_schemas
import json
from pathlib import Path
from jsonschema import Draft202012Validator
import pytest
from copy import deepcopy
from uuid import uuid4
from app.domain.refs import canonical_json, parse_canonical


@pytest.fixture
def accepted_provider(tmp_path, monkeypatch):
    from app.tests.provider_receipt_fixture import (
        provider_receipt_context,
        signed_receipt,
        install_receipt,
        provider_worker,
    )

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        selector = dict(
            command_id=str(uuid4()),
            request_digest=prepared["request_digest"],
            receipt_digest=install_receipt(actual, raw),
            expected_revision=1,
        )
        imported = actual.service.import_provider_receipt(
            actual.request, prepared["request_id"], selector
        )
        consume = {**selector, "command_id": str(uuid4()), "expected_revision": 2}
        with provider_worker(actual, monkeypatch):
            accepted = actual.service.consume_provider_receipt(
                actual.request, prepared["request_id"], consume
            )
        with actual.domain._connection() as db:
            item = actual.service._journal(db)["requests"][prepared["request_id"]]
        yield actual, item, selector, consume, imported, accepted


def test_all_twelve_closed_schemas_match_runtime_positive_and_negative_vectors(
    accepted_provider,
):
    from app.deployment import provider_receipt_contracts as contracts
    from app.deployment import provider_receipt_lifecycle as lifecycle
    from app.deployment.provider_stage_observer import (
        parse_provider_stage_evidence,
        StagePostconditionError,
    )
    from app.deployment.receipt_contracts import _validate
    from app.deployment.prepare_contracts import epoch_ms
    from app.domain import deployment_receipt, extension_installation
    from app.api.provider_deployment_prepare import preflight, PATH

    actual, item, selector, consume, imported, accepted = accepted_provider
    schemas = exported_schemas()
    request_id = item["ref"].id
    cancellation = parse_canonical(
        contracts.make_provider_pending_cancellation(
            request_bytes=item["raw"],
            receipt_bytes=item["receipt"]["raw"],
            profile=actual.profile,
            cancelled_ms=epoch_ms(item["receipt"]["value"]["completed_at"]),
        )
    )
    # Inert projection vector only: no forged history is installed or accepted.
    rejected = deepcopy(item)
    rejected["consumption"]["anchor"]["outcome"] = "failed"
    consumed = parse_canonical(lifecycle.consumed_payload(rejected))
    read = lifecycle.read_body(item)

    def anchor_runtime(module, method, record, value):
        body = deepcopy(record.body)
        body["content"] = value
        return getattr(module, method)(body)

    vectors = {
        "provider-receipt-v1": (
            item["receipt"]["value"],
            lambda v: contracts.parse_provider_receipt(canonical_json(v)),
        ),
        "provider-stage-postcondition-v1": (
            item["installation"]["evidence"],
            lambda v: parse_provider_stage_evidence(canonical_json(v)),
        ),
        "provider-receipt-import-input-v1": (
            selector,
            lambda v: contracts.parse_provider_receipt_import(request_id, v),
        ),
        "provider-consume-input-v1": (
            consume,
            lambda v: contracts.parse_provider_consume(request_id, v),
        ),
        "provider-cancel-input-v2": (
            consume,
            lambda v: contracts.parse_provider_pending_cancel(request_id, v),
        ),
        "provider-cancellation-v2": (
            cancellation,
            lambda v: contracts.parse_provider_pending_cancellation(
                canonical_json(v), profile=actual.profile
            ),
        ),
        "provider-consumption-v1": (
            consumed,
            lambda v: contracts.parse_provider_consumed(
                canonical_json(v), profile=actual.profile
            ),
        ),
        "provider-receipt-anchor-v1": (
            item["receipt"]["anchor"],
            lambda v: anchor_runtime(
                deployment_receipt,
                "validate_receipt_body",
                item["receipt"]["record"],
                v,
            ),
        ),
        "provider-installation-anchor-v1": (
            item["installation"]["anchor"],
            lambda v: anchor_runtime(
                extension_installation,
                "validate_installation_body",
                item["installation"]["record"],
                v,
            ),
        ),
        "provider-command-receipt-v2": (
            accepted,
            lambda v: _validate(v, schemas["provider-command-receipt-v2.schema.json"]),
        ),
        "provider-request-read-v2": (
            read,
            lambda v: _validate(v, schemas["provider-request-read-v2.schema.json"]),
        ),
        "provider-receipt-api-v1": (
            selector,
            lambda v: preflight(
                {"path": PATH + "/" + request_id + "/receipts", "method": "POST"},
                canonical_json(v),
                "application/json",
            ),
        ),
    }
    assert set(vectors) == {name.removesuffix(".schema.json") for name in schemas}
    for name, (value, runtime) in vectors.items():
        validator = Draft202012Validator(schemas[name + ".schema.json"])
        refusal = (
            StagePostconditionError
            if name == "provider-stage-postcondition-v1"
            else ValueError
        )
        assert validator.is_valid(value), name
        runtime(deepcopy(value))
        for missing in value:
            bad = {k: v for k, v in value.items() if k != missing}
            if name == "provider-receipt-api-v1" and missing == "receipt_digest":
                # The aggregate legitimately includes the old prepared-cancel
                # arm; the /receipts consumer must still refuse that selector.
                assert validator.is_valid(bad)
            else:
                assert not validator.is_valid(bad), (name, missing)
            with pytest.raises(refusal):
                runtime(bad)
        bad = {**deepcopy(value), "unexpected": True}
        assert not validator.is_valid(bad), name
        with pytest.raises(refusal):
            runtime(bad)
    for outcome in ("failed", "unknown"):
        consumed["outcome"] = outcome
        assert Draft202012Validator(
            schemas["provider-consumption-v1.schema.json"]
        ).is_valid(consumed)
        contracts.parse_provider_consumed(
            canonical_json(consumed), profile=actual.profile
        )
    consumed["outcome"] = "succeeded"
    assert not Draft202012Validator(
        schemas["provider-consumption-v1.schema.json"]
    ).is_valid(consumed)
    with pytest.raises(ValueError):
        contracts.parse_provider_consumed(
            canonical_json(consumed), profile=actual.profile
        )


def test_every_new_response_read_arm_and_illegal_cross_state_projection(
    accepted_provider,
):
    """Formatter/schema parity, not authorization of the projected history."""
    from app.deployment import provider_receipt_lifecycle as lifecycle

    actual, base, selector, consume, imported, accepted = accepted_provider
    schemas = exported_schemas()
    aggregate = Draft202012Validator(schemas["provider-receipt-api-v1.schema.json"])
    states = (
        ("receipt_pending", 2, "succeeded"),
        ("rejected", 2, "failed"),
        ("rejected", 2, "unknown"),
        ("accepted", 3, "succeeded"),
        ("cancelled", 3, "succeeded"),
        ("expired", 3, "succeeded"),
    )
    observed = set()
    for read in (False, True):
        validator = Draft202012Validator(
            schemas[
                ("provider-request-read-v2" if read else "provider-command-receipt-v2")
                + ".schema.json"
            ]
        )
        for state, revision, outcome in states:
            if not read and state == "expired":
                continue
            for publication in ("published", "suppressed"):
                for marker in (
                    ("pending", "published")
                    if read and state in {"rejected", "cancelled"}
                    else ("pending",)
                ):
                    item = deepcopy(base)
                    item["history"][-1].update(state=state, revision=revision)
                    item["outbox"] = {"request": {"state": publication}}
                    item["consumed_outbox"] = (
                        {"state": marker} if state == "rejected" else None
                    )
                    if state == "cancelled":
                        item["outbox"]["cancel"] = {"state": marker}
                    item["receipt"]["value"]["outcome"] = outcome
                    if state not in {"accepted", "rejected"}:
                        item["consumption"] = None
                    if state != "accepted":
                        item["installation"] = None
                    kwargs = (
                        {}
                        if read
                        else {
                            "command_id": consume["command_id"],
                            "cursor": accepted["event_cursor"],
                        }
                    )
                    value = lifecycle._body(item, **kwargs)
                    assert validator.is_valid(value) and aggregate.is_valid(value)
                    observed.add((read, state, outcome, publication, marker))
                    mutations = []
                    for key in ("consumption", "installation"):
                        bad = deepcopy(item)
                        bad[key] = None if item[key] else deepcopy(base[key])
                        mutations.append(bad)
                    bad = deepcopy(item)
                    bad["outbox"]["request"]["state"] = "pending"
                    mutations.append(bad)
                    for key in ("cancel", "consumed"):
                        bad = deepcopy(item)
                        if key == "cancel":
                            if state == "cancelled":
                                bad["outbox"].pop("cancel")
                            else:
                                bad["outbox"]["cancel"] = {"state": "pending"}
                        else:
                            bad["consumed_outbox"] = (
                                None if state == "rejected" else {"state": "pending"}
                            )
                        mutations.append(bad)
                    bad = deepcopy(item)
                    bad["receipt"]["value"]["outcome"] = (
                        "succeeded" if outcome != "succeeded" else "failed"
                    )
                    mutations.append(bad)
                    bad = deepcopy(item)
                    bad["history"][-1]["revision"] = 1
                    mutations.append(bad)
                    if not read and state in {"rejected", "cancelled"}:
                        bad = deepcopy(item)
                        if state == "rejected":
                            bad["consumed_outbox"]["state"] = "published"
                        else:
                            bad["outbox"]["cancel"]["state"] = "published"
                        mutations.append(bad)
                    for bad in mutations:
                        with pytest.raises(ValueError):
                            lifecycle._body(bad, **kwargs)
                    for key in value:
                        assert not validator.is_valid(
                            {k: v for k, v in value.items() if k != key}
                        )
                    assert not validator.is_valid({**value, "unexpected": True})
                    # Independently exercise exported cross-state restrictions.
                    for key in ("consumption_ref", "installation_ref"):
                        replacement = None if value[key] else accepted[key]
                        assert not validator.is_valid({**value, key: replacement})
                    if not read and state in {"rejected", "cancelled"}:
                        key = (
                            "consumption_publication_state"
                            if state == "rejected"
                            else "cancellation_publication_state"
                        )
                        assert not validator.is_valid({**value, key: "published"})
    assert len(observed) == 28


def test_new_family_runtime_byte_limits_and_structural_limits_are_distinct(
    accepted_provider, monkeypatch
):
    """Real codecs/formatters, not legal public padding or schema-only byte claims."""
    from types import SimpleNamespace
    from inspect import getclosurevars
    from app.domain import wire, deployment_receipt, extension_installation
    from app.deployment import provider_receipt_contracts as contracts
    from app.deployment import provider_receipt_lifecycle as lifecycle
    from app.deployment.prepare_contracts import DeploymentPrepareError, epoch_ms
    from app.deployment.provider_stage_observer import (
        parse_provider_stage_evidence,
        StagePostconditionError,
    )
    from app.api.provider_deployment_prepare import preflight, create_router, PATH

    actual, item, selector, consume, imported, accepted = accepted_provider
    schemas = exported_schemas()
    cancelled = contracts.make_provider_pending_cancellation(
        request_bytes=item["raw"],
        receipt_bytes=item["receipt"]["raw"],
        profile=actual.profile,
        cancelled_ms=epoch_ms(item["receipt"]["value"]["completed_at"]),
    )
    rejected = deepcopy(item)
    rejected["consumption"]["anchor"]["outcome"] = "failed"
    vectors = (
        (
            "provider-receipt-v1",
            item["receipt"]["raw"],
            16384,
            contracts.parse_provider_receipt,
            ValueError,
        ),
        (
            "provider-stage-postcondition-v1",
            canonical_json(item["installation"]["evidence"]),
            8192,
            parse_provider_stage_evidence,
            StagePostconditionError,
        ),
        (
            "provider-cancellation-v2",
            cancelled,
            8192,
            lambda raw: contracts.parse_provider_pending_cancellation(
                raw, profile=actual.profile
            ),
            ValueError,
        ),
        (
            "provider-consumption-v1",
            lifecycle.consumed_payload(rejected),
            8192,
            lambda raw: contracts.parse_provider_consumed(raw, profile=actual.profile),
            ValueError,
        ),
    )
    real_json = wire.json
    decoded = []

    def loads(*args, **kwargs):
        decoded.append(True)
        return real_json.loads(*args, **kwargs)

    with monkeypatch.context() as decode_spy:
        # Delegate actual JSON decode, observe whether byte admission reached it.
        decode_spy.setattr(
            wire,
            "json",
            SimpleNamespace(loads=loads, JSONDecodeError=real_json.JSONDecodeError),
        )
        for name, raw, cap, runtime, refusal in vectors:
            validator = Draft202012Validator(schemas[name + ".schema.json"])
            assert validator.is_valid(parse_canonical(raw))
            runtime(raw)
            for size in (cap - 1, cap, cap + 1):
                padded = raw + b" " * (size - len(raw))
                assert len(padded) == size and validator.is_valid(json.loads(padded))
                decoded.clear()
                # <=cap decodes then fails canonicality; >cap never decodes.
                with pytest.raises(refusal):
                    runtime(padded)
                assert bool(decoded) is (size <= cap), (name, size)
        for name, value, runtime in (
            (
                "provider-receipt-import-input-v1",
                selector,
                contracts.parse_provider_receipt_import,
            ),
            ("provider-consume-input-v1", consume, contracts.parse_provider_consume),
            (
                "provider-cancel-input-v2",
                consume,
                contracts.parse_provider_pending_cancel,
            ),
        ):
            validator = Draft202012Validator(schemas[name + ".schema.json"])
            assert validator.is_valid(value)
            runtime(item["ref"].id, value)
            for size in (4095, 4096, 4097):
                bad = {**value, "padding": ""}
                extra = size - len(canonical_json(bad))
                bad["padding"] = "é" * (extra // 2) + "x" * (extra % 2)
                assert len(canonical_json(bad)) == size and not validator.is_valid(bad)
                decoded.clear()
                with pytest.raises(DeploymentPrepareError):
                    runtime(item["ref"].id, bad)
                assert bool(decoded) is (size <= 4096), (name, size)
        # The aggregate's actual HTTP selector consumer admits legal whitespace
        # at the wire cap, then canonicalizes its bounded parsed selector.
        raw = canonical_json(selector)
        scope = {"path": PATH + "/" + item["ref"].id + "/receipts", "method": "POST"}
        for size in (4095, 4096, 4097):
            padded = raw + b" " * (size - len(raw))
            assert Draft202012Validator(
                schemas["provider-receipt-api-v1.schema.json"]
            ).is_valid(json.loads(padded))
            decoded.clear()
            if size <= 4096:
                assert preflight(scope, padded, "application/json") == selector
                assert decoded
            else:
                with pytest.raises(DeploymentPrepareError):
                    preflight(scope, padded, "application/json")
                assert not decoded

    # Envelope-only validators' byte cap: content remains valid; padding is an
    # internal envelope test input, never submitted to ImmutableRecord/store.
    for name, child, validate in (
        (
            "provider-receipt-anchor-v1",
            item["receipt"],
            deployment_receipt.validate_receipt_body,
        ),
        (
            "provider-installation-anchor-v1",
            item["installation"],
            extension_installation.validate_installation_body,
        ),
    ):
        for size in (8191, 8192, 8193):
            body = deepcopy(child["record"].body)
            body["padding"] = ""
            extra = size - len(canonical_json(body))
            body["padding"] = "é" * (extra // 2) + "x" * (extra % 2)
            assert len(canonical_json(body)) == size
            assert Draft202012Validator(schemas[name + ".schema.json"]).is_valid(
                body["content"]
            )
            if size <= 8192:
                validate(body)
            else:
                with pytest.raises(ValueError):
                    validate(body)
        blob_key, blob_cap = (
            ("receipt_blob_ref", 16384)
            if name == "provider-receipt-anchor-v1"
            else ("postcondition_evidence_blob_ref", 8192)
        )
        for size in (blob_cap - 1, blob_cap, blob_cap + 1):
            body = deepcopy(child["record"].body)
            body["content"][blob_key]["size"] = size
            assert Draft202012Validator(schemas[name + ".schema.json"]).is_valid(
                body["content"]
            ) is (size <= blob_cap)
            if size <= blob_cap:
                validate(body)
            else:
                with pytest.raises(ValueError):
                    validate(body)

    router = create_router(service=actual.service, base_path=actual.profile.base_path)
    route = next(
        r
        for r in router.routes
        if r.path == PATH + "/{request_id}/consume" and r.methods == {"POST"}
    )
    project = getclosurevars(route.endpoint).nonlocals["response"]
    for read, cap in ((False, 8192), (True, 73728)):
        for size in (cap - 1, cap, cap + 1):
            changed = deepcopy(item)
            kwargs = (
                {} if read else {"command_id": consume["command_id"], "cursor": "_"}
            )
            base = lifecycle._body(changed, **kwargs)
            if read:
                # Closed request schema has no arbitrary padding arm. For this
                # bound probe it must fail schema *after* passing byte admission.
                base["request"]["padding"] = [""] * 8
                extra = size - len(canonical_json(base))
                q, remainder = divmod(extra, 8)
                changed["request"]["padding"] = [
                    "é" * ((q + (i < remainder)) // 2)
                    + "x" * ((q + (i < remainder)) % 2)
                    for i in range(8)
                ]
                base["request"] = changed["request"]
                with pytest.raises(ValueError) as caught:
                    lifecycle._body(changed)
                assert isinstance(caught.value, DeploymentPrepareError) is (size > cap)
            else:
                extra = size - len(canonical_json(base)) + len(base["event_cursor"])
                kwargs["cursor"] = "é" * (extra // 2) + "x" * (extra % 2)
                base["event_cursor"] = kwargs["cursor"]
                assert len(kwargs["cursor"]) <= 4096
                assert Draft202012Validator(
                    schemas["provider-command-receipt-v2.schema.json"]
                ).is_valid(base)
                if size <= cap:
                    assert lifecycle._body(changed, **kwargs) == base
                else:
                    with pytest.raises(DeploymentPrepareError) as caught:
                        lifecycle._body(changed, **kwargs)
                    assert caught.value.code == "unavailable"
            assert len(canonical_json(base)) == size
            # Real router projection guard independently applies the same cap.
            projected = deepcopy(base)
            expansion = 5 * len(actual.profile.base_path.rstrip("/").encode("utf-8"))
            if read:
                projected["request"]["padding"] = [""] * 8
                extra = size - expansion - len(canonical_json(projected))
                q, remainder = divmod(extra, 8)
                projected["request"]["padding"] = [
                    "é" * ((q + (i < remainder)) // 2)
                    + "x" * ((q + (i < remainder)) % 2)
                    for i in range(8)
                ]
            else:
                projected["event_cursor"] = ""
                extra = size - expansion - len(canonical_json(projected))
                projected["event_cursor"] = "é" * (extra // 2) + "x" * (extra % 2)
            if size <= cap:
                assert len(project(projected).body) == size
            else:
                with pytest.raises(DeploymentPrepareError) as caught:
                    project(projected)
                assert caught.value.code == "unavailable"


def test_exact_twelve_detached_exports():
    names = {
        "provider-receipt-v1",
        "provider-stage-postcondition-v1",
        "provider-receipt-import-input-v1",
        "provider-consume-input-v1",
        "provider-cancel-input-v2",
        "provider-cancellation-v2",
        "provider-consumption-v1",
        "provider-receipt-anchor-v1",
        "provider-installation-anchor-v1",
        "provider-command-receipt-v2",
        "provider-request-read-v2",
        "provider-receipt-api-v1",
    }
    actual = exported_schemas()
    assert set(actual) == {name + ".schema.json" for name in names}
    for name, schema in actual.items():
        assert schema[
            "$id"
        ] == "urn:deeptwin:schemas:v2:deployment:" + name.removesuffix(".schema.json")
        schema.clear()
    assert all(exported_schemas().values())


def test_shipped_artifacts_equal_detached_schemas_and_pending_selector_unambiguous():
    for name, value in exported_schemas().items():
        Draft202012Validator.check_schema(value)
        assert (
            Path(__file__).parents[2] / "schemas/v2/deployment" / name
        ).read_bytes() == (
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        ).encode()
    selector = {
        "command_id": "11111111-1111-4111-8111-111111111111",
        "request_digest": "A" * 43,
        "receipt_digest": "A" * 43,
        "expected_revision": 2,
    }
    assert Draft202012Validator(
        exported_schemas()["provider-receipt-api-v1.schema.json"]
    ).is_valid(selector)
