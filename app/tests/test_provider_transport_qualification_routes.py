"""The owner's provider-transport qualification path over HTTP (T087 -> T090).

The supported app's `provider-conformance-v1` contribution carries two routes over
`PersistentTransportQualification`:

- `GET /api/v1/extensions/provider-transport-qualification` reads the shipped manifest's
  digest, what a qualification requires, the prerequisite state (with the run that meets
  it), the newest sealed qualification and what the gateway adopted;
- `POST` the same path (owner, CSRF, `command_id` replay-safe) qualifies from a named
  matched verified run and publishes the document to the gateway (`bind_transport`).

The installation case is the real T087 path: a verified installation staged through the
supported app and the fixed provider-port suite matched 4/4 through the framed worker.
The gateway side is a real `CredentialVault` with no synthetic adoption: it refuses the
manifest-built transport until the document published through the route is adopted.
"""

from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

import pytest

from app.api.provider_transport_qualification import REFUSALS
from app.tests.provider_installation_fixture import (
    installation_case,  # noqa: F401 - fixture
)
from app.workers.provider_transport_manifest import claude_api_manifest

PATH = "api/v1/extensions/provider-transport-qualification"
DIGEST = claude_api_manifest().manifest_sha256


def _url(case):
    return case.profile.base_path.rstrip("/") + "/" + PATH


def _post(case, body, *, csrf=True, content_type="application/json"):
    headers = {"Origin": case.profile.http_origin, "Sec-Fetch-Site": "same-origin",
               "Content-Type": content_type}
    if csrf:
        headers["X-Deeptwin-Csrf"] = case.csrf
    return case.client.post(_url(case), json=body, headers=headers)


def _get(case):
    response = case.client.get(_url(case))
    assert response.status_code == 200, response.text
    return response.json()


def _body(conformance_command_id, *, command_id=None, digest=DIGEST):
    return {"command_id": command_id or str(uuid4()), "manifest_sha256": digest,
            "conformance_command_id": conformance_command_id}


def _refused(response, code):
    assert response.status_code == REFUSALS[code][0], response.text
    value = response.json()
    assert value["code"] == code and value["message"] == REFUSALS[code][1]
    assert set(value) == {"code", "message", "retryability", "affected_refs", "correlation_id"}


def _qualification_records(case):
    from app.domain.store import _writer

    with _writer(), case.domain._connection(write=True) as db:
        return db.execute("SELECT COUNT(*) FROM domain_records WHERE kind='validation_report'"
                          ).fetchone()[0]


def _gateway_vault(path):
    from app.tests.test_credential_custody import metadata
    from app.tests.test_credential_root import initialized
    from app.workers.credential_vault import CredentialVault

    path.mkdir()
    vault = CredentialVault(**initialized(path))
    vault.__enter__()
    meta = metadata()
    receipt = vault.store_at(metadata=meta, secret=b"synthetic-transport-route-key")
    record = {key: receipt[key] for key in ("record_id", "record_version", "ciphertext_sha256")}
    vault.bind_head(provider=meta["provider"], revision=1, state="bound", record=record)
    return vault, meta, record


def _matched_run(case, monkeypatch):
    from app.tests.provider_conformance_fixture import (
        _retained_provider_conformance_worker,
    )
    from app.tests.test_provider_conformance_verified import verified_command

    verified = case.verification_service.execute(case.actual.request, case.packet)
    run = verified_command(case, verified)
    with _retained_provider_conformance_worker(case, monkeypatch):
        reply = case.b_service.execute(case.actual.request, run)
    assert reply["state"] == "matched"
    return verified, run, reply


def _service(case):
    return case.actual.app.state.first_party_exports["provider-transport-qualification.service"]


def test_unqualified_state_names_each_missing_prerequisite_and_refuses_honestly(installation_case):
    case = installation_case
    state = _get(case)
    assert state["schema_version"] == "provider-transport-qualification-state-v1"
    assert (state["provider"], state["manifest_sha256"]) == ("claude", DIGEST)
    assert state["requirements"]["installation_conformance"] == {
        "command_schema": "provider-conformance-command-v2", "verified_installation": True,
        "suite_sha256": state["requirements"]["installation_conformance"]["suite_sha256"],
        "matched_count": 4, "admission": "current"}
    assert state["requirements"]["transport_conformance"]["provider"] == "offline_loopback_mock"
    # no verified installation yet; the case app attached no credential gateway
    assert state["prerequisite"] == "verified_installation_missing"
    assert state["eligible_conformance"] is None and state["qualification"] is None
    assert state["gateway"] == {"state": "unavailable", "revision": None, "manifest_sha256": None}
    assert (state["state"], state["reason"]) == ("unqualified", "gateway_unavailable")
    before = _qualification_records(case)
    _refused(_post(case, _body(None)), "verified_installation_missing")
    _refused(_post(case, _body(str(uuid4()))), "verified_installation_missing")

    # a verified installation without a conformance run over it
    case.verification_service.execute(case.actual.request, case.packet)
    assert _get(case)["prerequisite"] == "conformance_run_missing"
    _refused(_post(case, _body(None)), "conformance_run_missing")
    _refused(_post(case, _body(str(uuid4()))), "conformance_run_missing")
    assert _qualification_records(case) == before  # nothing sealed by a refusal

    # the exact wire: CSRF, body shape, query, method
    missing_csrf = _post(case, _body(None), csrf=False)
    assert missing_csrf.status_code in (401, 403)
    _refused(_post(case, {**_body(None), "extra": 1}), "invalid_input")
    _refused(_post(case, {"command_id": "not-a-uuid", "manifest_sha256": DIGEST,
                          "conformance_command_id": None}), "invalid_input")
    _refused(_post(case, _body(None, digest="A" * 64)), "invalid_input")
    assert case.client.get(_url(case) + "?x=1").status_code == 400
    assert case.client.put(_url(case), headers={"Origin": case.profile.http_origin,
        "Sec-Fetch-Site": "same-origin", "X-Deeptwin-Csrf": case.csrf}).status_code in (400, 405)
    assert _qualification_records(case) == before


def test_the_owner_qualifies_through_the_route_and_the_gateway_then_sends(
        installation_case, monkeypatch, tmp_path):
    from app.tests.support.provider_semantic_harness import (
        connection_values,
        controlled_upstream,
    )
    from app.tests.support.transport_manifest import loopback_binding
    from app.tests.test_provider_send_gateway import prepared_catalog
    from app.tests.test_provider_transport_manifest import exchange
    from app.workers.provider_gateway import CredentialedProviderTransport
    from app.workers.provider_send_messages import ProviderSendError
    from app.workers.provider_send_service import ProviderSendService

    case = installation_case
    vault, meta, record = _gateway_vault(tmp_path / "gateway")
    try:
        service = _service(case)
        failing = []

        def unreachable(**kwargs):
            failing.append(kwargs)
            raise OSError("gateway unreachable")

        # the composed service reads/publishes through the host's gateway client; here a
        # real vault stands in for it (first unreachable for publication)
        monkeypatch.setattr(service, "_publisher", unreachable)
        monkeypatch.setattr(service, "_reader", vault.transports)
        handle, pin, _, _ = connection_values(meta, record)

        # unqualified: the gateway refuses the manifest-built transport before any byte
        with controlled_upstream() as (port, captures, _entered, _release):
            send = ProviderSendService(CredentialedProviderTransport(vault, loopback_binding(port)))
            with pytest.raises(ProviderSendError) as refused:
                exchange(send, prepared_catalog(meta, record, handle, pin))
            assert (refused.value.failure_class, refused.value.phase) == (
                "unsupported_capability", "not_sent")
            assert captures == []

        verified, run, reply = _matched_run(case, monkeypatch)
        # a run whose verified-installation admission is no longer current does not qualify
        from app.extensions import provider_transport_qualification as module
        from app.extensions.provider_conformance_contracts import ConformanceError

        def moved(*_args):
            raise ConformanceError("conflict")

        with monkeypatch.context() as patch:
            patch.setattr(module, "resolve_verified_admission", moved)
            assert _get(case)["prerequisite"] == "conformance_admission_stale"
            _refused(_post(case, _body(run["command_id"])), "conformance_admission_stale")
            _refused(_post(case, _body(None)), "conformance_admission_stale")
        state = _get(case)
        assert state["prerequisite"] == "met"
        assert state["eligible_conformance"] == {
            "command_id": run["command_id"],
            "verified_installation_ref": verified["verified_installation_ref"],
            "result_ref": reply["result_ref"]}
        assert state["gateway"]["state"] == "not_adopted"
        assert (state["state"], state["reason"]) == ("unqualified", "not_qualified")

        # a manifest the owner did not review is refused before anything is sealed
        _refused(_post(case, _body(run["command_id"], digest="0" * 64)), "manifest_changed")

        # the act seals the qualification; the gateway was unreachable, so not adopted
        body = _body(run["command_id"])
        first = _post(case, body)
        assert first.status_code == 200, first.text
        answer = first.json()
        assert answer["published"] is False and len(failing) == 1
        assert answer["command_id"] == body["command_id"]
        qualification = answer["qualification"]
        assert qualification["manifest_sha256"] == DIGEST
        assert qualification["conformance_command_id"] == run["command_id"]
        state = _get(case)
        assert state["qualification"] == {"revision": qualification["revision"],
            "qualification_ref": qualification["qualification_ref"],
            "conformance_command_id": run["command_id"]}
        assert (state["state"], state["reason"]) == ("unqualified", "not_published")
        assert vault.transports() == []

        # replaying the same command republishes the same qualification once reachable
        monkeypatch.setattr(service, "_publisher", vault.bind_transport)
        records = _qualification_records(case)
        again = _post(case, body)
        assert again.status_code == 200, again.text
        assert again.json() == {**answer, "published": True}
        assert _qualification_records(case) == records  # no new record for a replay
        adopted = vault.transports()
        assert len(adopted) == 1 and adopted[0]["manifest_sha256"] == DIGEST
        assert adopted[0]["revision"] == qualification["revision"]
        assert adopted[0]["qualification_ref"] == qualification["qualification_ref"]
        state = _get(case)
        assert state["gateway"] == {"state": "adopted", "revision": qualification["revision"],
                                    "manifest_sha256": DIGEST}
        assert (state["state"], state["reason"]) == ("qualified", None)

        # the same command id with another request is refused, and seals nothing
        _refused(_post(case, _body(str(uuid4()), command_id=body["command_id"])), "command_conflict")
        # a new command over the same run is idempotent: the same qualification
        fresh = _post(case, _body(run["command_id"]))
        assert fresh.status_code == 200 and fresh.json()["qualification"] == qualification
        assert vault.transports() == adopted

        # the document adopted through the owner path lets the manifest-built transport send
        with controlled_upstream() as (port, captures, _entered, _release):
            send = ProviderSendService(CredentialedProviderTransport(vault, loopback_binding(port)))
            assert exchange(send, prepared_catalog(meta, record, handle, pin)).status == 200
            assert len(captures) == 1
    finally:
        vault.__exit__(None, None, None)


def test_the_owner_screen_shows_the_exact_refusal_texts():
    source = (Path(__file__).resolve().parents[1] / "static" / "account.mjs").read_text()
    block = source.split("export const TRANSPORT_QUALIFICATION_ERRORS = Object.freeze({", 1)[1]
    block = block.split("\n});", 1)[0]
    shown = dict(re.findall(r"^\s+([a-z_]+): '([^']*)',$", block, re.MULTILINE))
    assert set(shown) == set(REFUSALS)
    for code, (_status, message, _retry) in REFUSALS.items():
        assert shown.get(code) == message, code
