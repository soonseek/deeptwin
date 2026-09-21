"""Real owner HTTP receipt admission with retained public source and signature fixtures."""

from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.domain.public_events import _decode_cursor
from app.domain.refs import canonical_json
from app.server import create_app
from app.tests.deployment_prepare_fixture import http_sources
from app.tests.deployment_receipt_import_fixture import (
    http_receipt_sources,
    http_signed_case,
)
from app.tests.deployment_receipt_session_fixture import OwnedReceiptSession
from app.tests.test_deployment_prepare_api import prepare_payload
from app.tests.test_deployment_prepare_contracts import matching_bundle
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers


@contextmanager
def http_case(
    tmp_path,
    monkeypatch,
    *,
    mode="local",
    case_name="valid_succeeded_present",
    capacity=1,
):
    profile, capability, arguments = configured(tmp_path, mode)
    physical, values = http_sources(tmp_path, monkeypatch, profile, capacity=capacity)
    with OwnedReceiptSession(profile) as session:
        values.update(
            http_receipt_sources(physical, profile, session, capacity=capacity)
        )
        arguments["first_party_startup_values"] = values
        app = create_app(tmp_path / "data", **arguments)
        with TestClient(app, base_url=profile.http_origin) as client:
            csrf = bootstrap_client(client, profile, capability)
            registration = client.post(
                profile.base_path + "api/v1/extensions/candidates",
                json=matching_bundle()[0].as_dict(),
                headers=headers(profile, csrf),
            )
            assert registration.status_code == 201, registration.text
            with app.state.domain_store._connection() as db:
                for table in (
                    "deployment_prepare_requests",
                    "deployment_prepare_receipts",
                ):
                    assert (
                        db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
                    )
            path = profile.base_path + "api/v1/deployment/requests"
            payload = prepare_payload(
                registration.json()["candidate_ref"]["candidate_id"]
            )
            prepared = client.post(path, json=payload, headers=headers(profile, csrf))
            assert prepared.status_code == 201, prepared.text
            request_path = prepared.json()["links"]["self"]
            current = client.get(request_path, headers=headers(profile))
            assert current.status_code == 200, current.text
            command, final = http_signed_case(
                physical,
                session,
                current.json(),
                monkeypatch,
                case_name=case_name,
            )
            yield SimpleNamespace(
                app=app,
                client=client,
                profile=profile,
                csrf=csrf,
                physical=physical,
                values=values,
                arguments=arguments,
                path=path,
                payload=payload,
                prepared=prepared,
                request_path=request_path,
                current=current.json(),
                command=command,
                final=final,
                import_path=request_path + "/receipts",
                service=app.state.first_party_exports["deployment-prepare.service"],
            )


@pytest.mark.parametrize("mode", ["local", "https"])
def test_actual_owner_import_read_head_and_cold_replay(tmp_path, monkeypatch, mode):
    with http_case(tmp_path, monkeypatch, mode=mode) as case:
        response = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result == {
            "command_id": case.command["command_id"],
            "request_id": case.prepared.json()["request_id"],
            "receipt_digest": case.command["receipt_digest"],
            "outcome": "succeeded",
            "disposition": "pending_postconditions",
            "revision": 2,
            "event_cursor": result["event_cursor"],
        }
        assert response.content == canonical_json(result)
        current = case.client.get(case.request_path, headers=headers(case.profile))
        head = case.client.head(case.request_path, headers=headers(case.profile))
        assert head.status_code == current.status_code == 200
        assert head.content == b""
        for name in (
            "content-type",
            "content-length",
            "cache-control",
            "content-security-policy",
            "x-content-type-options",
            "referrer-policy",
            "x-frame-options",
        ):
            assert head.headers[name] == current.headers[name]
        state = current.json()
        assert state["state"] == "receipt_pending" and state["revision"] == 2
        assert state["receipt"] == {
            "receipt_digest": case.command["receipt_digest"],
            "outcome": "succeeded",
            "disposition": "pending_postconditions",
            "import_revision": 2,
        }
        assert state["consumption_publication_state"] is None
        assert state["links"]["self"] == case.request_path
        with case.app.state.domain_store._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM domain_records WHERE kind IN ('extension_installation','extension_qualification','extension_binding')"
                ).fetchone()[0]
                == 0
            )
            row = db.execute(
                "SELECT receipt_json FROM deployment_prepare_commands WHERE command_id=?",
                (case.command["command_id"],),
            ).fetchone()
            assert row[0].encode() == response.content
            sequence = db.execute(
                "SELECT sequence FROM api_event_envelopes WHERE event_type='deployment.receipt_committed'"
            ).fetchone()[0]
            assert _decode_cursor(result["event_cursor"])["sequence"] == sequence
        assert (
            case.client.post(
                case.path, json=case.payload, headers=headers(case.profile, case.csrf)
            ).content
            == case.prepared.content
        )
    # The real app and owner database reopen with no receipt or prepare sources.
    arguments = {**case.arguments, "first_party_startup_values": {}}
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=case.profile.http_origin) as client:
        login = client.post(
            case.profile.base_path + "session/login",
            json={"login_name": "owner", "password": "synthetic owner passphrase"},
            headers=headers(case.profile),
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        replay = client.post(
            case.import_path, json=case.command, headers=headers(case.profile, csrf)
        )
        assert replay.content == response.content and replay.status_code == 200
        assert (
            client.post(
                case.path, json=case.payload, headers=headers(case.profile, csrf)
            ).content
            == case.prepared.content
        )
        assert (
            client.get(case.request_path, headers=headers(case.profile)).json() == state
        )
        changed = client.post(
            case.import_path,
            json={**case.command, "expected_revision": 2},
            headers=headers(case.profile, csrf),
        )
        assert changed.status_code == 409 and changed.json()["code"] == "conflict"


@pytest.mark.parametrize(
    "case_name,outcome",
    [
        ("valid_failed_absent", "failed"),
        ("valid_failed_unknown", "failed"),
        ("valid_unknown_unknown", "unknown"),
    ],
)
def test_non_success_commits_one_consumption_and_pending_intent(
    tmp_path, monkeypatch, case_name, outcome
):
    with http_case(tmp_path, monkeypatch, case_name=case_name) as case:
        response = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert set(result) == {
            "command_id",
            "request_id",
            "receipt_digest",
            "outcome",
            "disposition",
            "revision",
            "event_cursor",
        }
        assert result["outcome"] == outcome
        assert (
            result["disposition"] == "consumed_non_success" and result["revision"] == 2
        )
        state = case.client.get(case.request_path, headers=headers(case.profile)).json()
        assert (
            state["state"] == "rejected"
            and state["consumption_publication_state"] == "pending"
        )
        assert (
            case.client.post(
                case.import_path,
                json=case.command,
                headers=headers(case.profile, case.csrf),
            ).content
            == response.content
        )
        cancelled = case.client.post(
            case.request_path + "/cancel",
            json={
                "command_id": str(uuid4()),
                "request_digest": case.command["request_digest"],
                "expected_revision": 2,
            },
            headers=headers(case.profile, case.csrf),
        )
        assert cancelled.status_code == 409
        with case.app.state.domain_store._connection() as db:
            for table in (
                "deployment_prepare_receipts",
                "deployment_prepare_consumptions",
                "deployment_prepare_consumed_outbox",
            ):
                assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 1
            assert (
                db.execute(
                    "SELECT state FROM deployment_prepare_consumed_outbox"
                ).fetchone()[0]
                == "pending"
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM api_event_envelopes WHERE event_type='deployment.receipt_committed'"
                ).fetchone()[0]
                == 1
            )


def test_pending_success_cancel3_uses_intact_exchange_and_reopens_v2_marker(
    tmp_path, monkeypatch
):
    import json
    from base64 import urlsafe_b64decode

    from app.tests.test_deployment_publication import syscall_fixture

    with http_case(tmp_path, monkeypatch) as case:
        imported = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert imported.status_code == 200
        for source in (
            case.service._topology,
            case.service._trust,
            case.service._ingress,
            case.service._consumption,
        ):
            source.close()
        syscall_fixture(monkeypatch)
        command = {
            "command_id": str(uuid4()),
            "request_digest": case.command["request_digest"],
            "expected_revision": 2,
        }
        cancelled = case.client.post(
            case.request_path + "/cancel",
            json=command,
            headers=headers(case.profile, case.csrf),
        )
        assert cancelled.status_code == 200, cancelled.text
        assert (
            cancelled.json()["revision"] == 3
            and cancelled.json()["state"] == "cancelled"
        )
        assert cancelled.json()["cancellation_publication_state"] == "pending"
        final = case.physical.actual(case.physical.c.OUTBOX_ROOT / "cancelled") / (
            urlsafe_b64decode(command["request_digest"] + "=").hex() + ".json"
        )
        raw = final.read_bytes()
        marker = json.loads(raw)
        assert (
            marker["schema"] == "deployment-cancellation-v2"
            and marker["lifecycle_revision"] == 3
        )
        current = case.client.get(
            case.request_path, headers=headers(case.profile)
        ).json()
        assert current["cancellation_publication_state"] == "published"
        assert current["receipt"]["disposition"] == "pending_postconditions"
    arguments = {
        **case.arguments,
        "first_party_startup_values": {
            key: value
            for key, value in case.values.items()
            if key.startswith("DEEPTWIN_PREPARE_") or key == "DEEPTWIN_EXCHANGE_SHA256"
        },
    }
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=case.profile.http_origin) as client:
        login = client.post(
            case.profile.base_path + "session/login",
            json={"login_name": "owner", "password": "synthetic owner passphrase"},
            headers=headers(case.profile),
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        assert (
            client.post(
                case.request_path + "/cancel",
                json=command,
                headers=headers(case.profile, csrf),
            ).content
            == cancelled.content
        )
        assert (
            client.post(
                case.import_path, json=case.command, headers=headers(case.profile, csrf)
            ).content
            == imported.content
        )
        assert (
            client.get(case.request_path, headers=headers(case.profile)).json()
            == current
        )
        assert final.read_bytes() == raw


@pytest.mark.parametrize("first", ["cancel", "import", "expiry"])
def test_http_first_committed_winner_and_due_expiry_precede_receipt_io(
    tmp_path, monkeypatch, first
):
    import time

    from app.deployment.prepare_contracts import epoch_ms

    with http_case(tmp_path, monkeypatch) as case:
        command = {
            "command_id": str(uuid4()),
            "request_digest": case.command["request_digest"],
            "expected_revision": 1,
        }
        post_headers = headers(case.profile, case.csrf)
        if first == "cancel":
            won = case.client.post(
                case.request_path + "/cancel", json=command, headers=post_headers
            )
            assert won.status_code == 200
            lost = case.client.post(
                case.import_path, json=case.command, headers=post_headers
            )
            expected = "cancelled"
        elif first == "import":
            won = case.client.post(
                case.import_path, json=case.command, headers=post_headers
            )
            assert won.status_code == 200
            lost = case.client.post(
                case.request_path + "/cancel", json=command, headers=post_headers
            )
            expected = "receipt_pending"
        else:
            deadline = epoch_ms(case.current["request"]["expires_at"])
            monkeypatch.setattr(time, "time_ns", lambda: deadline * 1000000)
            case.final.unlink()
            lost = case.client.post(
                case.import_path, json=case.command, headers=post_headers
            )
            expected = "expired"
        assert lost.status_code == 409 and lost.json()["code"] == "conflict"
        state = case.client.get(case.request_path, headers=headers(case.profile)).json()
        assert state["state"] == expected and state["revision"] == 2
        assert (
            case.client.post(case.path, json=case.payload, headers=post_headers).content
            == case.prepared.content
        )
        with case.app.state.domain_store._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_lifecycle"
                ).fetchone()[0]
                == 2
            )
            assert db.execute(
                "SELECT count(*) FROM deployment_prepare_commands"
            ).fetchone()[0] == (1 if first == "expiry" else 2)


@pytest.mark.parametrize(
    "case_name,status,code",
    [
        ("invalid_cross_request", 409, "conflict"),
        ("invalid_time", 400, "invalid_input"),
        ("invalid_key_adapter", 400, "invalid_input"),
        ("invalid_profile", 503, "dependency_unavailable"),
        ("missing", 503, "dependency_unavailable"),
        ("signature", 400, "invalid_input"),
    ],
)
def test_actual_receipt_error_partition_never_creates_evidence(
    tmp_path, monkeypatch, case_name, status, code
):
    import json
    from hashlib import sha256

    from app.tests.deployment_receipt_import_fixture import b64

    with http_case(
        tmp_path,
        monkeypatch,
        case_name=case_name
        if case_name.startswith("invalid_")
        else "valid_succeeded_present",
    ) as case:
        if case_name == "missing":
            case.final.unlink()
        elif case_name == "signature":
            value = json.loads(case.final.read_bytes())
            value["signature"] = "A" * 86
            raw = canonical_json(value)
            case.final.unlink()
            digest = sha256(raw).digest()
            final = case.final.with_name(digest.hex() + ".json")
            final.write_bytes(raw)
            final.chmod(0o440)
            case.physical.register(final, 20113, 21201)
            case.command["receipt_digest"] = b64(digest)
        response = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert response.status_code == status, response.text
        assert response.json()["code"] == code
        assert set(response.json()) == {
            "code",
            "message",
            "retryability",
            "affected_refs",
            "correlation_id",
        }
        with case.app.state.domain_store._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_receipts"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == 0
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_commands"
                ).fetchone()[0]
                == 1
            )


@pytest.mark.parametrize(
    "changes,expected",
    [
        (
            {"DEEPTWIN_DEPLOYMENT_TRUST_SHA256": "invalid"},
            (True, True, False, True, True),
        ),
        (
            {"DEEPTWIN_RECEIPT_RECIPE_SHA256": "invalid"},
            (True, True, True, False, False),
        ),
        ({"DEEPTWIN_RECEIPT_INSTANCE_SHA256": False}, (True, True, True, False, False)),
        (
            {"DEEPTWIN_RECEIPT_INGRESS_SHA256": "invalid"},
            (True, True, True, False, True),
        ),
        (
            {"DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256": None},
            (True, True, True, True, False),
        ),
        (
            {"DEEPTWIN_PREPARE_RECIPE_SHA256": "invalid"},
            (False, False, True, True, True),
        ),
    ],
)
def test_actual_receipt_sources_open_independently_from_frozen_pins(
    tmp_path, monkeypatch, changes, expected
):
    profile, _, arguments = configured(tmp_path)
    physical, values = http_sources(tmp_path, monkeypatch, profile)
    with OwnedReceiptSession(profile) as session:
        values.update(http_receipt_sources(physical, profile, session))
        values.update(changes)
        app = create_app(
            tmp_path / "data", first_party_startup_values=values, **arguments
        )
        with TestClient(app, base_url=profile.http_origin) as client:
            service = app.state.first_party_exports["deployment-prepare.service"]
            sources = (
                service._topology,
                service._exchange,
                service._trust,
                service._ingress,
                service._consumption,
            )
            assert tuple(source is not None for source in sources) == expected
            assert client.get(profile.base_path + "health").status_code == 200
            with app.state.domain_store._connection() as db:
                assert (
                    db.execute(
                        "SELECT count(*) FROM deployment_prepare_receipt_sources"
                    ).fetchone()[0]
                    == 0
                )
        assert all(source._closed for source in sources if source is not None)


def test_receipt_wire_limits_and_closed_paths_deny_before_auth(tmp_path, monkeypatch):
    from app.tests.deployment_receipt_import_fixture import b64

    profile, _, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", first_party_startup_values={}, **arguments)
    calls = []
    original = app.state.owner_authority.authenticate_request

    def observed(**kwargs):
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(app.state.owner_authority, "authenticate_request", observed)
    payload = {
        "command_id": str(uuid4()),
        "request_digest": b64(b"r" * 32),
        "receipt_digest": b64(b"s" * 32),
        "expected_revision": 1,
    }
    path = (
        profile.base_path + "api/v1/deployment/requests/" + str(uuid4()) + "/receipts"
    )
    with TestClient(app, base_url=profile.http_origin) as client:
        for changes in (
            {"expected_revision": True},
            {"expected_revision": 0},
            {"expected_revision": 4},
            {"command_id": "00000000-0000-0000-0000-000000000000"},
            {"receipt_digest": "a" * 64},
            {"request_digest": "A" * 42 + "B"},
            {"path": "/private/receipt.json"},
            {"key": "synthetic"},
            {"receipt": {}},
            {"receipt_digest": "x" * 257},
            {"receipt_digest": {"a": {"b": {"c": {"d": 1}}}}},
            {"receipt_digest": [1] * 33},
            {str(i): i for i in range(9)},
        ):
            response = client.post(
                path, json={**payload, **changes}, headers=headers(profile)
            )
            assert response.status_code == 400, (changes, response.text)
            assert response.json()["code"] == "invalid_input"
        for method, suffix, body, media, status in (
            ("POST", "?x=1", canonical_json(payload), "application/json", 400),
            ("POST", "", b'{"command_id":1,"command_id":2}', "application/json", 400),
            ("POST", "", canonical_json(payload), "text/plain", 400),
            ("POST", "/more", canonical_json(payload), "application/json", 400),
            ("GET", "", b"", "application/json", 400),
            ("PUT", "", canonical_json(payload), "application/json", 400),
            ("POST", "", b"x" * 4097, "application/json", 413),
        ):
            response = client.request(
                method,
                path + suffix,
                content=body,
                headers={**headers(profile), "Content-Type": media},
            )
            assert response.status_code == status
            assert response.headers["cache-control"] == "no-store"
        streamed = client.post(
            path,
            content=iter([b"x" * 4096, b"x"]),
            headers={**headers(profile), "Content-Type": "application/json"},
        )
        assert streamed.status_code == 413
        for route in (path.replace("/receipts", "/%72eceipts"), path + "//more"):
            assert (
                client.post(route, json=payload, headers=headers(profile)).status_code
                == 403
            )
        assert calls == []
        # All three revisions are syntactically valid and reach actual session denial.
        for revision in (1, 2, 3):
            response = client.post(
                path,
                json={**payload, "expected_revision": revision},
                headers=headers(profile),
            )
            assert response.status_code == 401
            cancel = client.post(
                path.removesuffix("receipts") + "cancel",
                json={
                    key: value
                    for key, value in {**payload, "expected_revision": revision}.items()
                    if key != "receipt_digest"
                },
                headers=headers(profile),
            )
            assert cancel.status_code == 401
        assert len(calls) == 6


def test_actual_receipt_session_transport_and_generic_failure_do_not_import(
    tmp_path, monkeypatch
):
    with http_case(tmp_path, monkeypatch) as case:
        for changed in (
            {"Origin": "https://evil.test"},
            {"Host": "evil.test"},
            {"Sec-Fetch-Site": "cross-site"},
            {"X-DeepTwin-CSRF": "wrong"},
        ):
            response = case.client.post(
                case.import_path,
                json=case.command,
                headers={**headers(case.profile, case.csrf), **changed},
            )
            assert response.status_code == 403
        assert (
            case.client.post(
                case.import_path, json=case.command, headers=headers(case.profile)
            ).status_code
            == 403
        )
        cookies = dict(case.client.cookies)
        case.client.cookies.clear()
        bearer = case.client.post(
            case.import_path,
            json=case.command,
            headers={**headers(case.profile), "Authorization": "Bearer service-client"},
        )
        assert bearer.status_code == 401
        case.client.cookies.update(cookies)
        missing = case.client.post(
            case.path + "/" + str(uuid4()) + "/receipts",
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert missing.status_code == 404
        with case.app.state.domain_store._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_receipts"
                ).fetchone()[0]
                == 0
            )

        def broken(*args, **kwargs):
            raise RuntimeError("private diagnostic must never reach HTTP")

        monkeypatch.setattr(case.service, "_journal", broken)
        # The existing client raises server exceptions, so observe the actual ASGI 500
        # using its transport flag without opening a second lifespan/authority.
        case.client._transport.raise_server_exceptions = False
        failed = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert failed.status_code == 500 and failed.content == b"Internal Server Error"


@pytest.mark.parametrize(
    "fault",
    [
        "ingress",
        "consumption",
        "service",
        "router",
        "return",
        "exports",
        "later",
        "registration",
        "worker",
        "shutdown",
        "local-cleanup",
    ],
)
def test_actual_five_source_ownership_survives_failures(tmp_path, monkeypatch, fault):
    from dataclasses import replace
    import os

    from app.api import deployment_prepare, first_party_catalog, session_routes
    from app.api.first_party import ContributionServices
    from app.api.router_composition import RouteCompositionError

    caller_fds = len(os.listdir('/dev/fd')) - 1
    profile, _, arguments = configured(tmp_path)
    physical, values = http_sources(tmp_path, monkeypatch, profile)
    opened, closed, contexts, errors = [], [], [], []
    fault_reached = []
    failure = RuntimeError("original synthetic factory failure")
    (entry,) = tuple(entry for entry in first_party_catalog.INSTALLED
                     if entry.descriptor_name == "deployment-prepare-v1.json")

    def factory(context, *, dependencies):
        contexts.append(context)
        try:
            result = entry.factory(context, dependencies=dependencies)
        except BaseException as error:
            errors.append(error)
            raise
        service = result.exports["deployment-prepare.service"]
        assert service._registry is dependencies["extension-candidates.registry"]
        assert (
            service._domain is context.domain_store
            and service._owner is context.owner_authority
        )
        assert result.owned_resources == tuple(opened)
        assert (
            service._topology,
            service._exchange,
            service._trust,
            service._ingress,
            service._consumption,
        ) == tuple(opened)
        assert set(result.exports) == {
            "deployment-prepare.service", "deployment-provider.source-context",
            "installation-release.source-context"}
        assert result.exports["deployment-provider.source-context"] is None
        assert result.exports["installation-release.source-context"] is None
        if fault == "exports":
            fault_reached.append(fault)
            return ContributionServices(result.router, {}, result.owned_resources)
        return result

    monkeypatch.setattr(
        first_party_catalog,
        "INSTALLED",
        tuple(replace(current, factory=factory) if current is entry else current
              for current in first_party_catalog.INSTALLED),
    )

    def fail(*args, **kwargs):
        fault_reached.append(fault)
        raise failure

    if fault == "later":
        import json
        from pathlib import Path

        from app.api import first_party
        from app.api.first_party import InstalledContribution
        from app.tests.test_router_composition import descriptor

        root = tmp_path / "route_contributions"
        root.mkdir()
        for path in (
            Path(first_party.__file__).with_name("route_contributions").glob("*.json")
        ):
            (root / path.name).write_bytes(path.read_bytes())
        (root / "example-v1.json").write_text(json.dumps(descriptor()))
        later = InstalledContribution(
            "example-v1.json",
            "app.api.example:create_router",
            fail,
            ("browser_session",),
            ("work.read",),
        )
        monkeypatch.setattr(
            first_party_catalog, "INSTALLED", (*first_party_catalog.INSTALLED, later)
        )
        monkeypatch.setattr(first_party, "__file__", str(tmp_path / "first_party.py"))

    names = (
        "open_topology_source",
        "open_exchange_source",
        "open_public_trust_source",
        "open_receipt_ingress_source",
        "open_consumption_exchange_source",
    )
    for index, name in enumerate(names):
        original = getattr(deployment_prepare, name)

        def tracked(*, _original=original, _index=index, **kwargs):
            assert kwargs["profile"] is contexts[0].owner_authority.profile
            assert (
                kwargs["protected_roots"] is contexts[0].startup_inputs.protected_roots
            )
            assert kwargs["protected_roots"] == (tmp_path / "data", tmp_path / "root")
            if (fault == "ingress" and _index == 3) or (
                fault == "consumption" and _index == 4
            ):
                fail()
            source = _original(**kwargs)
            close = source.close

            def counted_close():
                closed.append(source)
                close()
                if fault == "local-cleanup" and _index == 4:
                    raise RuntimeError("secondary cleanup failure")

            source.close = counted_close
            opened.append(source)
            return source

        monkeypatch.setattr(deployment_prepare, name, tracked)
    if fault in {"service", "local-cleanup"}:
        monkeypatch.setattr(deployment_prepare, "PersistentDeploymentPrepare", fail)
    elif fault == "router":
        monkeypatch.setattr(deployment_prepare, "create_router", fail)
    elif fault == "return":
        monkeypatch.setattr(deployment_prepare, "ContributionServices", fail)
    elif fault == "registration":
        monkeypatch.setattr(session_routes, "create_session_router", fail)
    with OwnedReceiptSession(profile) as session:
        values.update(http_receipt_sources(physical, profile, session))
        arguments["first_party_startup_values"] = values
        if fault in {"worker", "shutdown"}:
            app = create_app(
                tmp_path / "data",
                worker_dispatch_factory=fail if fault == "worker" else None,
                **arguments,
            )
            if fault == "worker":
                with (
                    pytest.raises(RuntimeError, match="original synthetic"),
                    TestClient(app, base_url=profile.http_origin),
                ):
                    pytest.fail("Failed worker admitted HTTP")
            else:
                with TestClient(app, base_url=profile.http_origin) as client:
                    assert client.get(profile.base_path + "health").status_code == 200
        else:
            with pytest.raises((RuntimeError, RouteCompositionError)):
                create_app(tmp_path / "data", **arguments)
        assert len(opened) == (
            3 if fault == "ingress" else 4 if fault == "consumption" else 5
        )
        assert closed == list(reversed(opened))
        assert all(source._closed for source in opened)
        assert fault_reached == ([] if fault == "shutdown" else [fault])
        assert errors == ([failure] if fault in {
            "ingress", "consumption", "service", "router", "return", "local-cleanup"
        } else [])
        if fault == "local-cleanup":
            assert errors == [failure], (
                "Secondary close failure replaced original construction error"
            )
    assert len(os.listdir('/dev/fd')) - 1 == caller_fds


def test_exact_import_replay_uses_no_clock_live_sources_or_flush(tmp_path, monkeypatch):
    with http_case(tmp_path, monkeypatch) as case:
        response = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert response.status_code == 200

        def forbidden(*args, **kwargs):
            raise AssertionError("Exact replay reached clock/source/reconciliation")

        for name in ("_now", "_current_receipt_sources", "_reconcile"):
            monkeypatch.setattr(case.service, name, forbidden)
        replay = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert replay.status_code == 200 and replay.content == response.content
        assert (
            case.client.get(case.request_path, headers=headers(case.profile)).json()[
                "state"
            ]
            == "receipt_pending"
        )


def test_consumed_startup_waits_for_complete_composition_and_survives_worker_failure(
    tmp_path, monkeypatch
):
    from base64 import urlsafe_b64decode

    from app.api import session_routes
    from app.deployment.receipt_sources import CONSUMED_NAMESPACE_ROOT
    from app.tests.test_deployment_publication import syscall_fixture

    with http_case(tmp_path, monkeypatch, case_name="valid_failed_absent") as case:
        imported = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert imported.status_code == 200
        final = case.physical.actual(CONSUMED_NAMESPACE_ROOT) / (
            urlsafe_b64decode(case.command["receipt_digest"] + "=").hex() + ".json"
        )
        assert not final.exists()
        cookies = dict(case.client.cookies)
    syscall_fixture(monkeypatch)

    def fail(*args, **kwargs):
        raise RuntimeError("controlled receipt startup failure")

    with monkeypatch.context() as fault:
        fault.setattr(session_routes, "create_session_router", fail)
        with pytest.raises(RuntimeError, match="controlled receipt"):
            create_app(tmp_path / "data", **case.arguments)
    assert not final.exists()
    app = create_app(tmp_path / "data", worker_dispatch_factory=fail, **case.arguments)
    assert not final.exists()
    with (
        pytest.raises(RuntimeError, match="controlled receipt"),
        TestClient(app, base_url=case.profile.http_origin),
    ):
        pytest.fail("Worker startup failure admitted HTTP")
    raw = final.read_bytes()
    reopened = create_app(tmp_path / "data", **case.arguments)
    with TestClient(reopened, base_url=case.profile.http_origin) as client:
        client.cookies.update(cookies)
        current = client.get(case.request_path, headers=headers(case.profile))
        assert current.json()["consumption_publication_state"] == "published"
        assert (
            client.post(
                case.import_path,
                json=case.command,
                headers=headers(case.profile, case.csrf),
            ).content
            == imported.content
        )
        assert final.read_bytes() == raw
        with reopened.state.domain_store._connection() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM deployment_prepare_consumptions"
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM api_event_envelopes WHERE event_type='deployment.receipt_committed'"
                ).fetchone()[0]
                == 1
            )


def test_enrolled_missing_receipt_sources_keep_new_prepare_pending_and_e_cancel_available(
    tmp_path, monkeypatch
):
    from base64 import urlsafe_b64decode

    from app.domain.refs import parse_canonical
    from app.extensions.candidate_contracts import metadata_ref
    from app.tests.test_deployment_publication import syscall_fixture

    with http_case(tmp_path, monkeypatch, capacity=2) as case:
        imported = case.client.post(
            case.import_path,
            json=case.command,
            headers=headers(case.profile, case.csrf),
        )
        assert imported.status_code == 200
        topology = parse_canonical(
            (
                case.physical.actual(case.physical.c.TOPOLOGY_ROOT) / "topology.json"
            ).read_bytes()
        )
    syscall_fixture(monkeypatch)
    arguments = {
        **case.arguments,
        "first_party_startup_values": {
            key: value
            for key, value in case.values.items()
            if key
            in {
                "DEEPTWIN_PREPARE_RECIPE_SHA256",
                "DEEPTWIN_PREPARE_INSTANCE_SHA256",
                "DEEPTWIN_TOPOLOGY_SHA256",
                "DEEPTWIN_EXCHANGE_SHA256",
            }
        },
    }
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=case.profile.http_origin) as client:
        login = client.post(
            case.profile.base_path + "session/login",
            json={"login_name": "owner", "password": "synthetic owner passphrase"},
            headers=headers(case.profile),
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        payload = matching_bundle()[0].as_dict()
        payload["command_id"] = str(uuid4())
        payload["manifest"]["extension_id"] = "second-extension"
        descriptor = payload["service_descriptor"]
        descriptor["extension_id"] = "second-extension"
        slot = topology["slots"][1]
        descriptor.update(
            {key: slot[key] for key in ("service_identity", "uid", "gid")}
        )
        descriptor["socket_mounts"] = [slot["socket_mount"]]
        descriptor["broker_endpoint"].update(
            channel_id=slot["channel_id"],
            responder_service=slot["service_identity"],
            pair_gid=slot["pair_gid"],
            socket_mount_id=slot["socket_mount"]["mount_id"],
        )
        payload["manifest"]["artifact"]["service_descriptor_ref"] = metadata_ref(
            "service_descriptor", canonical_json(descriptor)
        )
        registration = client.post(
            case.profile.base_path + "api/v1/extensions/candidates",
            json=payload,
            headers=headers(case.profile, csrf),
        )
        assert registration.status_code == 201, registration.text
        command = {
            **prepare_payload(registration.json()["candidate_ref"]["candidate_id"]),
            "slot_id": 2,
        }
        prepared = client.post(
            case.path, json=command, headers=headers(case.profile, csrf)
        )
        assert prepared.status_code == 201, prepared.text
        result = prepared.json()
        current = client.get(
            result["links"]["self"], headers=headers(case.profile)
        ).json()
        assert (
            current["publication_state"] == "pending" and current["state"] == "prepared"
        )
        assert (
            current["receipt"] is None
            and current["consumption_publication_state"] is None
        )
        request_file = case.physical.actual(
            case.physical.c.OUTBOX_ROOT / "requests"
        ) / (urlsafe_b64decode(result["request_digest"] + "=").hex() + ".json")
        assert not request_file.exists()
        cancel = client.post(
            result["links"]["cancel"],
            json={
                "command_id": str(uuid4()),
                "request_digest": result["request_digest"],
                "expected_revision": 1,
            },
            headers=headers(case.profile, csrf),
        )
        assert cancel.status_code == 200
        assert (
            client.get(result["links"]["self"], headers=headers(case.profile)).json()[
                "cancellation_publication_state"
            ]
            == "published"
        )
        assert (
            client.post(
                case.import_path, json=case.command, headers=headers(case.profile, csrf)
            ).content
            == imported.content
        )
        service = reopened.state.first_party_exports["deployment-prepare.service"]
        assert not service._unavailable


def test_actual_v1_cold_http_upgrade_preserves_historical_reply_bytes(
    tmp_path, monkeypatch
):
    from app.deployment import prepare_storage as storage
    from app.deployment.prepare_contracts import DeploymentPrepareError
    from app.tests.deployment_v1_history_fixture import snapshot_v1, v1_history

    with v1_history(
        tmp_path, monkeypatch, states=("prepared", "cancelled", "expired")
    ) as old:
        before = snapshot_v1(old.domain)
    profile = old.profile
    # Missing sources require no host mapping; all persisted history is real disk data.
    app = create_app(tmp_path / "data", first_party_startup_values={}, **old.arguments)
    # Compare the migration before lifespan activation legitimately advances its clock floor.
    after = snapshot_v1(app.state.domain_store)
    after["rows"]["migrations"] = after["rows"]["migrations"][:1]
    assert after == before
    with TestClient(app, base_url=profile.http_origin) as client:
        login = client.post(
            profile.base_path + "session/login",
            json={"login_name": "owner", "password": "synthetic owner passphrase"},
            headers=headers(profile),
        )
        assert login.status_code == 200
        csrf = login.json()["csrf_token"]
        with app.state.domain_store._connection() as db:
            assert [
                tuple(row)
                for row in db.execute(
                    "SELECT * FROM deployment_prepare_migrations ORDER BY version"
                )
            ] == [
                (1, "68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec"),
                (2, "d35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f"),
                # The cold HTTP upgrade continues forward-only to current v6.
                (3, "ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457"),
                (4, "f89a9a8ba7f98da44e4a48f63c0363d2bfa7fafe038bd19bfdc178396c4be7d2"),
                (5, "9f3b9426d465524036c8c3ca48db3ba3360e284149b5cee8611aba0d6b4907d2"),
                (6, "8065412b2560175517eee1b56ce12f04912cb2f74fe76a7446f17b2f33924c72"),
            ]
            assert storage.shape(db) == storage.SHAPE_V6
            with pytest.raises(DeploymentPrepareError):
                storage.install(db)
        for value, reply, cancel_value, cancel_reply in old.cases:
            path = profile.base_path + "api/v1/deployment/requests"
            response = client.post(path, json=value, headers=headers(profile, csrf))
            expected = {
                **reply,
                "links": {
                    name: profile.base_path.rstrip("/") + link
                    for name, link in reply["links"].items()
                },
            }
            assert response.status_code == 201 and response.content == canonical_json(
                expected
            )
            current = client.get(
                path + "/" + reply["request_id"], headers=headers(profile)
            )
            assert current.status_code == 200
            assert (
                current.json()["receipt"] is None
                and current.json()["consumption_publication_state"] is None
            )
            if cancel_reply is not None:
                response = client.post(
                    path + "/" + reply["request_id"] + "/cancel",
                    json={
                        key: val
                        for key, val in cancel_value.items()
                        if key != "request_id"
                    },
                    headers=headers(profile, csrf),
                )
                expected = {
                    **cancel_reply,
                    "links": {
                        name: profile.base_path.rstrip("/") + link
                        for name, link in cancel_reply["links"].items()
                    },
                }
                assert (
                    response.status_code == 200
                    and response.content == canonical_json(expected)
                )
        assert (
            snapshot_v1(app.state.domain_store)["rows"]["commands"]
            == before["rows"]["commands"]
        )
