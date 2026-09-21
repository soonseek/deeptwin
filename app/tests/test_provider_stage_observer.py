"""Provider observer evidence and actual authenticated worker observations."""

import pytest
from dataclasses import replace
from app.domain.refs import canonical_json
from app.deployment.provider_stage_observer import (
    parse_provider_stage_evidence,
    StagePostconditionError,
)


def test_evidence_parser_rejects_missing_evidence_fields():
    with pytest.raises(StagePostconditionError) as caught:
        parse_provider_stage_evidence(
            canonical_json({"schema_version": "provider-stage-postcondition-v1"})
        )
    assert caught.value.code == "probe_invalid"


@pytest.mark.parametrize(
    "incoming,first_read,first_close,second_read,remaining,elapsed,error",
    [
        (5.0, 0.2, 1.1, 0.2, 0.7, 1500, False),
        (1.5, 0.2, 0.9, 0.2, 0.4, 1300, False),
        (5.0, 0.1, 0.1, 1.001, 1.0, None, True),
        (5.0, 0.2, 1.7, 0.2, 0.1, None, True),
    ],
)
def test_actual_deadline_arguments_include_first_teardown_but_not_final_close(
    tmp_path,
    monkeypatch,
    incoming,
    first_read,
    first_close,
    second_read,
    remaining,
    elapsed,
    error,
):
    """Real authenticated frames; local clock advances only after real I/O/close."""
    from hashlib import sha256
    from types import SimpleNamespace
    from app.tests.provider_receipt_fixture import (
        provider_receipt_context,
        provider_worker,
        signed_receipt,
    )
    from app.deployment import provider_stage_observer as observer
    from app.deployment.prepare_contracts import b64
    from app.extensions.provider_identity import parse_provider_build_identity
    from app.workers import broker, listener

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        with provider_worker(actual, monkeypatch) as (mapping, box):
            identity = parse_provider_build_identity(canonical_json(mapping))
            expected = observer.ExpectedProviderStageIdentity(
                request["effect_payload"]["new_service_effect"]["service_identity"],
                identity.digest,
                identity.schema_set_digest,
                "provider-port-v1",
                "linux/amd64",
                22001,
                22001,
            )
            now = [100.0]
            clock = SimpleNamespace(monotonic=lambda: now[0])
            connect_real = listener._connect_extension_authenticated
            read_real, close_real = (
                listener.ExtensionConnection.read,
                listener.ExtensionConnection.close,
            )
            budgets, connections, closed, read_deadlines = [], [], [], []

            def connect(*args, deadline, **kwargs):
                budgets.append((deadline, deadline.remaining()))
                connection = connect_real(*args, deadline=deadline, **kwargs)
                connections.append(connection)
                return connection

            def read(connection, *, deadline):
                frame = read_real(connection, deadline=deadline)
                if connection._read_only:
                    read_deadlines.append(deadline)
                    now[0] += first_read if len(read_deadlines) == 1 else second_read
                return frame

            def close(connection):
                close_real(connection)
                if connection._read_only:
                    closed.append(connection)
                    now[0] += first_close if len(closed) == 1 else 5.0

            with monkeypatch.context() as controlled:
                controlled.setattr(observer, "time", clock)
                controlled.setattr(broker, "time", clock)
                controlled.setattr(
                    listener, "_connect_extension_authenticated", connect
                )
                controlled.setattr(listener.ExtensionConnection, "read", read)
                controlled.setattr(listener.ExtensionConnection, "close", close)
                kwargs = dict(
                    request_id=prepared["request_id"],
                    request_digest=prepared["request_digest"],
                    receipt_digest=b64(sha256(raw).digest()),
                    request_bytes=canonical_json(request),
                    receipt_bytes=raw,
                    source_context_sha256=actual.payload["source_context_sha256"],
                    preserved_inventory_sha256=request["effect_payload"][
                        "preserved_inventory_sha256"
                    ],
                    instance_id=actual.profile.instance_id,
                    slot_number=1,
                    expected=expected,
                    deadline=broker.Deadline(100.0 + incoming),
                )
                if error:
                    with pytest.raises(StagePostconditionError) as caught:
                        observer.observe_provider_stage_postcondition(**kwargs)
                    assert caught.value.code == "probe_deadline"
                else:
                    evidence = observer.observe_provider_stage_postcondition(**kwargs)
                    value = parse_provider_stage_evidence(evidence.content_bytes)
                    # ceil may add one millisecond for binary floating arithmetic.
                    assert value["attempt_ms"] in (elapsed, elapsed + 1)
                assert len(budgets) == len(read_deadlines) == len(connections) == 2
                assert budgets[0][1] == pytest.approx(1.0)
                assert budgets[1][1] == pytest.approx(remaining)
                assert all(read_deadlines[i] is budgets[i][0] for i in range(2))
                assert budgets[0][0].end_monotonic == pytest.approx(101.0)
                assert budgets[1][0].end_monotonic <= min(102.0, 100.0 + incoming)
                assert closed == connections and all(c.closed for c in connections)


def test_two_real_authenticated_provider_identifies(tmp_path, monkeypatch):
    from hashlib import sha256
    from app.tests.provider_receipt_fixture import (
        provider_receipt_context,
        provider_worker,
        signed_receipt,
    )
    from app.deployment.provider_stage_observer import (
        ExpectedProviderStageIdentity,
        observe_provider_stage_postcondition,
    )
    from app.deployment.prepare_contracts import b64
    from app.extensions.provider_identity import parse_provider_build_identity
    from app.workers.broker import Deadline

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        with provider_worker(actual, monkeypatch) as (mapping, box):
            identity = parse_provider_build_identity(canonical_json(mapping))
            expected = ExpectedProviderStageIdentity(
                request["effect_payload"]["new_service_effect"]["service_identity"],
                identity.digest,
                identity.schema_set_digest,
                "provider-port-v1",
                "linux/amd64",
                22001,
                22001,
            )
            evidence = observe_provider_stage_postcondition(
                request_id=prepared["request_id"],
                request_digest=prepared["request_digest"],
                receipt_digest=b64(sha256(raw).digest()),
                request_bytes=canonical_json(request),
                receipt_bytes=raw,
                source_context_sha256=actual.payload["source_context_sha256"],
                preserved_inventory_sha256=request["effect_payload"][
                    "preserved_inventory_sha256"
                ],
                instance_id=actual.profile.instance_id,
                slot_number=1,
                expected=expected,
                deadline=Deadline.after_ms(2000),
            )
            value = parse_provider_stage_evidence(evidence.content_bytes)
            assert [o["ordinal"] for o in value["observations"]] == [1, 2]
            assert (
                value["observations"][0]["connection_id"]
                != value["observations"][1]["connection_id"]
            )
            assert evidence.digest == sha256(evidence.content_bytes).hexdigest()
            # Historical parsing is independent of today's process identity.
            from copy import deepcopy
            from app.deployment import provider_stage_observer as observer

            with monkeypatch.context() as historical:
                historical.setattr(
                    observer, "_process_boot_id", lambda: "different-current-boot"
                )
                assert parse_provider_stage_evidence(evidence.content_bytes) == value
            for field in (
                "connection_id",
                "nonce",
                "challenge",
                "request_message_id",
                "reply_message_id",
            ):
                bad = deepcopy(value)
                bad["observations"][1][field] = bad["observations"][0][field]
                with pytest.raises(StagePostconditionError):
                    parse_provider_stage_evidence(canonical_json(bad))
            for field in (
                "requester_boot_id",
                "responder_boot_id",
                "listener_record_sha256",
            ):
                bad = deepcopy(value)
                bad["observations"][1][field] = "0" * 64
                with pytest.raises(StagePostconditionError):
                    parse_provider_stage_evidence(canonical_json(bad))
            for field, replacement in (
                ("peer_uid", 22002),
                ("peer_gid", 22002),
                ("ordinal", 1),
            ):
                bad = deepcopy(value)
                bad["observations"][1][field] = replacement
                with pytest.raises(StagePostconditionError):
                    parse_provider_stage_evidence(canonical_json(bad))
            for field, replacement in (
                ("attempt_ms", 2001),
                ("attempt_ms", True),
                ("receipt_blob_sha256", "0" * 64),
                ("unknown", True),
            ):
                with pytest.raises(StagePostconditionError):
                    parse_provider_stage_evidence(
                        canonical_json({**value, field: replacement})
                    )


@pytest.mark.parametrize(
    "fault,code",
    [
        ("correlation", "probe_invalid"),
        ("message_id", "probe_invalid"),
        ("reply", "probe_mismatch"),
        ("port_schema_set_digest", "probe_mismatch"),
        ("worker_profile", "probe_invalid"),
        ("implemented_transforms", "probe_invalid"),
        ("platform", "probe_mismatch"),
        ("challenge", "probe_mismatch"),
        ("drift", "probe_unavailable"),
        ("deadline", "probe_deadline"),
        ("control", None),
    ],
)
def test_real_second_identify_refusals_close_both_connections(
    tmp_path, monkeypatch, fault, code
):
    from hashlib import sha256
    from uuid import uuid4
    from app.tests.provider_receipt_fixture import (
        provider_receipt_context,
        provider_worker,
        signed_receipt,
    )
    from app.deployment.provider_stage_observer import (
        ExpectedProviderStageIdentity,
        observe_provider_stage_postcondition,
    )
    from app.deployment.prepare_contracts import b64
    from app.extensions.provider_identity import parse_provider_build_identity
    from app.workers import broker, listener, provider_messages

    with provider_receipt_context(tmp_path.resolve(), monkeypatch) as actual:
        prepared = actual.service.prepare_provider(actual.request, actual.payload)
        request = actual.service.read_provider(
            actual.read_request, prepared["request_id"]
        )["request"]
        raw = signed_receipt(actual, request)
        with provider_worker(actual, monkeypatch) as (mapping, box):
            identity = parse_provider_build_identity(canonical_json(mapping))
            expected = ExpectedProviderStageIdentity(
                request["effect_payload"]["new_service_effect"]["service_identity"],
                identity.digest,
                identity.schema_set_digest,
                "provider-port-v1",
                "linux/amd64",
                22001,
                22001,
            )
            original_read, original_close = (
                listener.ExtensionConnection.read,
                listener.ExtensionConnection.close,
            )
            connections, requests = [], []
            primary = KeyboardInterrupt("synthetic control identity")

            def read(connection, *, deadline):
                frame = original_read(connection, deadline=deadline)
                if not connection._read_only:
                    return frame
                connections.append(connection)
                requests.append(frame.envelope.correlation_id)
                if len(connections) != 2:
                    return frame
                if fault == "correlation":
                    return replace(
                        frame,
                        envelope=replace(frame.envelope, correlation_id=str(uuid4())),
                    )
                if fault == "message_id":
                    return replace(
                        frame, envelope=replace(frame.envelope, message_id=requests[0])
                    )
                if fault in {
                    "reply",
                    "port_schema_set_digest",
                    "worker_profile",
                    "implemented_transforms",
                    "platform",
                    "challenge",
                }:
                    changed = provider_messages.parse_control(frame.payload)
                    key = "build_identity_digest" if fault == "reply" else fault
                    replacement = {
                        "worker_profile": "other-profile",
                        "implemented_transforms": ["text"],
                        "platform": "linux/arm64",
                    }.get(key, "0" * 64)
                    return replace(
                        frame,
                        payload=canonical_json({**changed, key: replacement}),
                    )
                if fault == "drift":
                    connection._fence.close()
                    return frame
                if fault == "deadline":
                    raise broker.DeadlineExceeded()
                raise primary

            closed = []

            def close(connection):
                original_close(connection)
                if connection._read_only:
                    closed.append(connection)
                    if fault == "control" and len(connections) == 2:
                        raise OSError("secondary cleanup failure")

            with monkeypatch.context() as negative:
                negative.setattr(listener.ExtensionConnection, "read", read)
                negative.setattr(listener.ExtensionConnection, "close", close)
                with pytest.raises(
                    KeyboardInterrupt if code is None else StagePostconditionError
                ) as caught:
                    observe_provider_stage_postcondition(
                        request_id=prepared["request_id"],
                        request_digest=prepared["request_digest"],
                        receipt_digest=b64(sha256(raw).digest()),
                        request_bytes=canonical_json(request),
                        receipt_bytes=raw,
                        source_context_sha256=actual.payload["source_context_sha256"],
                        preserved_inventory_sha256=request["effect_payload"][
                            "preserved_inventory_sha256"
                        ],
                        instance_id=actual.profile.instance_id,
                        slot_number=1,
                        expected=expected,
                        deadline=broker.Deadline.after_ms(2000),
                    )
                if code is None:
                    assert caught.value is primary
                else:
                    assert caught.value.code == code
                assert len(connections) == 2 and all(c.closed for c in connections)
                assert all(c in closed for c in connections)
