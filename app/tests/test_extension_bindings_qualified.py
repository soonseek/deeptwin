"""Bindings over the real qualified provider path (T087, `extension-bindings-v1`).

`installation_case` is the pytest-owned release tree: a staged installation, its verification to
revision 2 through the supported app, the fixed provider-port suite matched 4/4 through the framed
worker and the owner's transport qualification sealed through its route. The binding service here
uses its production resolver: the sealed `provider-transport-qualification-record-v1` named by exact
ref, re-checked as current (shipped manifest digest and verified-installation admission).
"""

from __future__ import annotations

from uuid import uuid4

from app.api.extension_bindings import REFUSALS
from app.tests.provider_installation_fixture import (
    installation_case,  # noqa: F401 - fixture
)
from app.tests.test_provider_transport_qualification_routes import DIGEST, _matched_run

SELECTOR = {"selector_kind": "provider_role", "provider_id": "claude", "auth_mode": "api",
            "account_binding_ref": None}


def _headers(case, *, csrf=True):
    value = {"Origin": case.profile.http_origin, "Sec-Fetch-Site": "same-origin"}
    if csrf:
        value["X-Deeptwin-Csrf"] = case.csrf
    return value


def _url(case, path):
    return case.profile.base_path.rstrip("/") + "/api/v1/extensions/" + path


def _get(case, path, client=None):
    response = (client or case.client).get(_url(case, path), headers=_headers(case, csrf=False))
    assert response.status_code == 200, response.text
    return response.json()


def _post(case, path, body):
    return case.client.post(_url(case, path), json=body, headers=_headers(case))


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def _refused(response, code):
    assert response.status_code == REFUSALS[code][0], response.text
    assert response.json()["code"] == code


def test_owner_binds_the_qualified_provider_installation_and_uses_retention(installation_case, monkeypatch):  # noqa: F811
    case = installation_case
    scope = {"environment_id": None, "work_id": None, "node_id": None, "purpose": "operational"}
    key = _ok(_post(case, "binding-slot-keys", {"port_contract_version": "provider-port-v1",
                                                 "binding_slot_id": "default-provider", "target_scope": scope,
                                                 "capability_selector": SELECTOR}))
    digest = key["binding_slot_key_digest"]
    assert key["target_scope"] == {"instance_id": case.profile.instance_id, **scope}

    # the staged installation is listed with its trust tier and staging request/receipt
    (staged_row,) = _get(case, "installations")["items"]
    assert staged_row["state"] == "staged" and staged_row["verified_installation_ref"] is None
    assert (staged_row["port_contract_version"], staged_row["trust_tier"]) == ("provider-port-v1", "runtime_worker")
    assert staged_row["staging"]["staging_authority"] == "deployment-provider-receipt-v1"
    assert staged_row["staging"]["request_link"].endswith(
        "/api/v1/deployment/provider-requests/" + staged_row["staging"]["request_ref"]["id"])

    verified, run, _reply = _matched_run(case, monkeypatch)
    sealed = case.client.post(_url(case, "provider-transport-qualification"), headers=_headers(case), json={
        "command_id": str(uuid4()), "manifest_sha256": DIGEST, "conformance_command_id": run["command_id"]})
    assert sealed.status_code == 200, sealed.text
    qualification_ref = sealed.json()["qualification"]["qualification_ref"]
    (row,) = _get(case, "installations")["items"]
    assert row["state"] == "verified" and row["verified_installation_ref"] == verified["verified_installation_ref"]
    extension_id = row["extension_id"]

    def bind_body(head, **changes):
        return {"command_id": str(uuid4()), "extension_id": extension_id, "qualification_ref": qualification_ref,
                "binding_slot_key": key["binding_slot_key"], "binding_slot_key_digest": digest,
                "capability_selector": key["capability_selector"], "target_scope": key["target_scope"],
                "expected_current_binding_head": head, **changes}

    # a qualification ref that is not a sealed transport qualification is refused
    _refused(_post(case, "bindings", bind_body(None, qualification_ref=verified["verified_installation_ref"])),
             "qualification_missing")
    _refused(_post(case, "bindings", bind_body(None, extension_id="other-extension")), "extension_mismatch")
    bound = _ok(_post(case, "bindings", bind_body(None)))
    head1 = bound["binding_head"]
    slot = _get(case, "bindings/" + digest)
    assert slot["current"]["installation_ref"] == verified["verified_installation_ref"]
    assert slot["current"]["qualification_ref"] == qualification_ref
    assert slot["current"]["qualification_current"] is True
    assert slot["current"]["service_tuple"] == row["service_tuple"]
    assert slot["current"]["target_installation_ref"] == row["target_installation_ref"]
    assert _get(case, "installations")["items"][0]["active_binding_slot_digests"] == [digest]
    _refused(_post(case, "bindings", bind_body(head1)), "binding_unchanged")

    def slot_body(head, **extra):
        return {"command_id": str(uuid4()), "extension_id": extension_id, "binding_slot_key": key["binding_slot_key"],
                "binding_slot_key_digest": digest, "expected_current_binding_head": head, **extra}

    head2 = _ok(_post(case, f"bindings/{digest}/disable", slot_body(head1)))["binding_head"]
    (retention,) = _get(case, "bindings/" + digest)["rollback_retentions"]
    assert retention["qualification_current"] is True
    rolled = _ok(_post(case, f"bindings/{digest}/rollback", slot_body(
        head2, target_binding_revision_ref=retention["target_binding_revision_ref"],
        expected_retention_head=retention["retention_head"])))
    head3 = rolled["binding_head"]
    assert (head3["revision"], head3["state"]) == (3, "active")
    head4 = _ok(_post(case, f"bindings/{digest}/disable", slot_body(head3)))["binding_head"]
    slot = _get(case, "bindings/" + digest)
    retained = [item for item in slot["rollback_retentions"] if item["retention_head"]["state"] == "retained"]
    assert [item["target_binding_revision_ref"]["revision"] for item in retained] == [3]
    target = retained[0]
    released = _ok(_post(case, f"bindings/{digest}/rollback-retentions/"
                         f"{target['target_binding_revision_ref']['binding_record_digest']}/release", slot_body(
        head4, target_binding_revision_ref=target["target_binding_revision_ref"],
        target_installation_ref=target["target_installation_ref"],
        target_service_tuple=target["target_service_tuple"], expected_retention_head=target["retention_head"],
        reason="시험: 퇴역 전 보존 해제")))
    assert released["state"] == "released" and released["target_service_tuple"] == row["service_tuple"]
    after = _get(case, "bindings/" + digest)
    assert after["head"] == head4 and len(after["history"]) == 4

    # history is read back after a cold reopen (without the release source, the qualification
    # cannot be re-checked, so it is not current; nothing about the history changes)
    with case.restart_without_release_source() as reopened:
        again = _get(reopened, "bindings/" + digest, client=reopened.client)
        assert again["history"] == after["history"] and again["head"] == head4
        assert again["rollback_retentions"][-1]["retention_head"]["state"] == "released"
