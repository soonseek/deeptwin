"""Extension bindings, rollback retention and the owner inventory lists (T087, `extension-bindings-v1`).

The real supported `create_app`, owner cookie and CSRF. The only qualification record this server
has is the sealed provider-transport qualification, which needs `installation_case`'s pytest-owned
release tree (driven in `test_extension_bindings_qualified.py`). Here the binding service's
qualification resolver is replaced by a test resolver over real `validation_report` records, so
the binding/retention records, CAS, events and routes are the production ones.
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.extension_bindings import REFUSALS
from app.domain.extension_binding import digest_of, retention_record_id, scope_fingerprint, slot_record_id
from app.domain.refs import DomainContractError
from app.domain.schemas import ImmutableRecord
from app.extensions.binding_service import (
    RELEASE_RESULT_FIELDS,
    BindingError,
    release_warning,
)
from app.server import create_app
from app.tests.extension_candidate_fixture import candidate_payload
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers

ROUTE_IDS = ("extensions.installations.list", "extensions.bindings.list", "extensions.bindings.read",
             "extensions.bindings.slot_key", "extensions.bindings.bind", "extensions.bindings.disable",
             "extensions.bindings.rollback", "extensions.bindings.retention_release")
SELECTOR = {"selector_kind": "provider_role", "provider_id": "claude", "auth_mode": "api",
            "account_binding_ref": None}


def _scope(**changes):
    return {"instance_id": "1" * 32, "environment_id": None, "work_id": None, "node_id": None,
            "purpose": "operational", **changes}


def _tuple(label):
    return {"service_identity": f"provider-{label}", "manifest_digest": digest_of({"m": label}),
            "service_descriptor_digest": digest_of({"d": label}),
            "selected_platform_entry_digest": digest_of({"p": label}),
            "image_manifest_digest": "sha256:" + digest_of({"i": label})}


class Resolver:
    """Test stand-in for the transport-qualification resolver: real `validation_report` records for
    the qualifications, and staged/verified `extension_installation` records admitted by a test-only
    validator (the closed installation codecs are proven by their own suites); `stale` marks a
    qualification that is no longer current."""

    def __init__(self, domain, installations):
        self.domain, self.by_ref, self.stale, self.installations = domain, {}, set(), installations

    def _put(self, kind, content, *, record_id=None, version=1, parents=()):
        roots = self.domain.roots()
        return self.domain.put(ImmutableRecord.create(
            kind=kind, id=record_id or str(uuid4()), version=version,
            created_at_utc="2026-09-25T00:00:00.000000Z", actor_ref=roots.actor, parent_refs=parents,
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy, content=content))

    def qualification(self, extension_id, label, *, provider="claude"):
        service = _tuple(label)
        installation_id = str(uuid4())
        self.installations.add(installation_id)
        stand_in = {"schema_version": "test-deployment-stand-in-v1", "label": label}
        request = self._put("validation_report", stand_in)
        receipt = self._put("validation_report", {**stand_in, "receipt": True})
        staged = self._put("extension_installation", {
            "schema_version": "extension-provider-installation-anchor-v1", "extension_id": extension_id,
            "platform": "linux/amd64", "staging_authority": "deployment-provider-receipt-v1",
            "request_ref": request.as_dict(), "receipt_ref": receipt.as_dict(),
            "consume_command_id": str(uuid4()), "installed_at": "2026-09-25T00:00:00.000Z", **service},
            record_id=installation_id)
        verified = self._put("extension_installation", {
            "schema_version": "provider-installation-verified-v1", "extension_id": extension_id,
            "extension_version": "1.0.0", "previous_record_digest": staged.sha256, "verified_at_ms": 1},
            record_id=installation_id, version=2, parents=(staged,))
        ref = self._put("validation_report", {"schema_version": "test-qualification-v1", "label": label},
                        parents=(verified,))
        self.by_ref[ref.sha256] = {
            "qualification_ref": ref.as_dict(), "port_contract_version": "provider-port-v1",
            "provider_id": provider, "extension_id": extension_id, "installation_ref": verified.as_dict(),
            "target_installation_ref": {"extension_id": extension_id, "revision": 2,
                                        "installation_record_digest": verified.sha256},
            "service_tuple": service, "staged": staged.as_dict()}
        return self.by_ref[ref.sha256]

    def __call__(self, _db, _roots, qualification_ref):
        value = self.by_ref.get(qualification_ref.get("sha256"))
        if value is None or value["qualification_ref"] != qualification_ref:
            raise BindingError("qualification_missing")
        if qualification_ref["sha256"] in self.stale:
            raise BindingError("qualification_not_current")
        return value


def _admit_test_installations(monkeypatch):
    from app.domain import extension_installation

    installations = set()
    original = extension_installation.validate_installation_body

    def validate(body):
        if body["id"] not in installations:
            original(body)

    monkeypatch.setattr(extension_installation, "validate_installation_body", validate)
    return installations


@pytest.fixture
def case(tmp_path, monkeypatch):
    installations = _admit_test_installations(monkeypatch)
    profile, capability, arguments = configured(tmp_path)
    application = create_app(tmp_path / "data", **arguments)
    with TestClient(application, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        service = application.state.first_party_exports["extension-bindings.service"]
        resolver = Resolver(application.state.domain_store, installations)
        service._resolver = resolver
        base = profile.base_path + "api/v1/extensions/"

        def get(path):
            return client.get(base + path, headers=headers(profile))

        def post(path, body, *, csrf_token=csrf):
            return client.post(base + path, headers=headers(profile, csrf_token), json=body)

        yield SimpleNamespace(app=application, client=client, profile=profile, csrf=csrf, service=service,
                              resolver=resolver, get=get, post=post, base=base, arguments=arguments,
                              tmp_path=tmp_path)


def _ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def _refused(response, code):
    assert response.status_code == REFUSALS[code][0], response.text
    value = response.json()
    assert (value["code"], value["message"]) == (code, REFUSALS[code][1])


def _given(scope=None):
    """The scope the owner gives; the server adds this instance's id."""
    value = dict(scope or _scope())
    del value["instance_id"]
    return value


def _key(case, slot_id="default-provider", scope=None, selector=None):
    return _ok(case.post("binding-slot-keys", {"port_contract_version": "provider-port-v1",
                                               "binding_slot_id": slot_id, "target_scope": _given(scope),
                                               "capability_selector": selector or SELECTOR}))


def _bind(key, qualification, head, *, command_id=None):
    return {"command_id": command_id or str(uuid4()), "extension_id": qualification["extension_id"],
            "qualification_ref": qualification["qualification_ref"], "binding_slot_key": key["binding_slot_key"],
            "binding_slot_key_digest": key["binding_slot_key_digest"],
            "capability_selector": key["capability_selector"], "target_scope": key["target_scope"],
            "expected_current_binding_head": head}


def _slot_body(key, extension_id, head, **extra):
    return {"command_id": str(uuid4()), "extension_id": extension_id, "binding_slot_key": key["binding_slot_key"],
            "binding_slot_key_digest": key["binding_slot_key_digest"], "expected_current_binding_head": head,
            **extra}


def _release_body(key, slot, retention, reason="A를 퇴역하기 전에 보존을 해제합니다"):
    return _slot_body(key, retention["target_extension_id"], slot["head"],
                      target_binding_revision_ref=retention["target_binding_revision_ref"],
                      target_installation_ref=retention["target_installation_ref"],
                      target_service_tuple=retention["target_service_tuple"],
                      expected_retention_head=retention["retention_head"], reason=reason)


def _records(case):
    with case.app.state.domain_store._connection() as db:
        return db.execute("SELECT COUNT(*) FROM domain_records WHERE kind='extension_binding'").fetchone()[0]


BINDING_EVENT_TYPES = (
    "extension.binding_activated", "extension.binding_superseded", "extension.binding_disabled",
    "extension.binding_rolled_back", "extension.rollback_retention_created",
    "extension.rollback_retention_released", "extension.rollback_retention_consumed")


def _events(case):
    response = case.client.get(case.profile.base_path + "api/v1/events", headers=headers(case.profile))
    events = response.json()["events"]
    assert not [event for event in events if event["event_type"] == "extension.binding_changed"]
    return [event for event in events if event["event_type"] in BINDING_EVENT_TYPES]


def _binding_meta(revision, previous, affected=0):
    return {"extension_kind": "provider", "trust_tier": "runtime_worker", "port_contract_version": "provider-port-v1",
            "purpose": "operational", "revision": revision, "previous_revision": previous,
            "affected_environment_count": affected}


def _retention_meta(retention, target, binding, previous, state):
    return {"extension_kind": "provider", "trust_tier": "runtime_worker", "port_contract_version": "provider-port-v1",
            "purpose": "operational", "retention_revision": retention, "target_revision": target,
            "binding_revision": binding, "previous_state": previous, "state": state}


def test_contribution_is_composed_and_the_wire_is_closed(case):
    composition = case.app.state.route_composition
    assert "extension-bindings-v1" in composition.contribution_ids
    assert set(ROUTE_IDS) <= set(composition.route_ids)
    assert "extensions.candidates.list" in composition.route_ids
    for path in ("installations", "bindings", "candidates"):
        assert _ok(case.get(path))["items"] == []
    for path in ("bindings?limit=0", "bindings?limit=51", "bindings?limit=x", "bindings?other=1",
                 "installations?after=not-a-uuid", "bindings?after=" + "A" * 64, "candidates?limit=0"):
        assert case.get(path).status_code == 400, path
    assert case.get("bindings/" + "a" * 64).status_code == 404
    assert case.get("bindings/not-a-digest").status_code in (400, 404)
    assert case.get("bindings/" + "a" * 64 + "?x=1").status_code == 400
    key = _key(case)
    # no CSRF: refused before the service; malformed and unknown bodies are invalid_input
    assert case.post("binding-slot-keys", {}, csrf_token=None).status_code in (401, 403)
    response = case.client.post(case.base + "bindings", headers={**headers(case.profile, case.csrf),
                                "Content-Type": "application/json"}, content=b'{"a":1,"a":2}')
    assert response.status_code == 400
    _refused(case.post("bindings", {**_bind(key, case.resolver.qualification("ext-a", "a"), None), "x": 1}),
             "invalid_input")
    # the server computes the key; the slot key and selector are exact and port-bound
    assert key["binding_slot_key"] == {
        "port_contract_version": "provider-port-v1", "purpose": "operational",
        "target_scope_fingerprint": scope_fingerprint(_scope()), "binding_slot_id": "default-provider",
        "capability_selector_digest": digest_of(SELECTOR)}
    assert key["binding_slot_key_digest"] == digest_of(key["binding_slot_key"])
    assert key["current_binding_head"] is None
    assert key["target_scope"] == _scope()
    _refused(case.post("binding-slot-keys", {"port_contract_version": "tool-port-v1", "binding_slot_id": "x",
                                             "target_scope": _given(), "capability_selector": {}}),
             "selector_unsupported")
    # the instance id is the server's own; a given one is refused, as is an incomplete hierarchy
    _refused(case.post("binding-slot-keys", {"port_contract_version": "provider-port-v1", "binding_slot_id": "x",
                                             "target_scope": _scope(), "capability_selector": SELECTOR}),
             "invalid_input")
    _refused(case.post("binding-slot-keys", {"port_contract_version": "provider-port-v1", "binding_slot_id": "x",
                                             "target_scope": _given(_scope(work_id=str(uuid4()))),
                                             "capability_selector": SELECTOR}), "invalid_input")
    # a bind whose scope names another instance is refused even with a matching fingerprint
    other = _scope(instance_id="2" * 32)
    forged = {**key["binding_slot_key"], "target_scope_fingerprint": scope_fingerprint(other)}
    _refused(case.post("bindings", {**_bind(key, case.resolver.qualification("ext-z", "z"), None),
                                    "binding_slot_key": forged, "binding_slot_key_digest": digest_of(forged),
                                    "target_scope": other}), "invalid_input")
    assert _records(case) == 0


def test_bind_compete_coexist_disable_rollback_and_release(case):
    a = case.resolver.qualification("ext-a", "a")
    b = case.resolver.qualification("ext-b", "b")
    key = _key(case)
    digest = key["binding_slot_key_digest"]
    # a key digest that does not match its five fields, or a four-field key, is refused
    _refused(case.post("bindings", {**_bind(key, a, None), "binding_slot_key_digest": "0" * 64}), "invalid_input")
    four = dict(key["binding_slot_key"])
    del four["capability_selector_digest"]
    _refused(case.post("bindings", {**_bind(key, a, None), "binding_slot_key": four}), "invalid_input")
    _refused(case.post("bindings", {**_bind(key, a, None), "extension_id": "ext-b"}), "extension_mismatch")
    other_provider = case.resolver.qualification("ext-c", "c", provider="other")
    _refused(case.post("bindings", _bind(key, other_provider, None)), "selector_mismatch")
    _refused(case.post("bindings", _bind(key, a, {"revision": 1, "binding_record_digest": "0" * 64,
                                                  "state": "active"})), "binding_head_stale")

    first = _ok(case.post("bindings", _bind(key, a, None)))
    assert first["binding_action"] == "bind" and first["retained"] is None
    head1 = first["binding_head"]
    assert head1["revision"] == 1 and head1["state"] == "active"
    assert first["binding_slot_key"] == key["binding_slot_key"] and first["binding_slot_key_digest"] == digest
    _refused(case.post("bindings", _bind(key, a, head1)), "binding_unchanged")

    # same-slot competition: B with the absent head it saw is refused and A is untouched
    records = _records(case)
    _refused(case.post("bindings", _bind(key, b, None)), "binding_head_stale")
    assert _records(case) == records and _ok(case.get("bindings/" + digest))["head"] == head1

    # a different slot id under the same port/scope/purpose coexists
    sibling = _key(case, "review-provider")
    assert sibling["binding_slot_key_digest"] != digest
    sibling_bound = _ok(case.post("bindings", _bind(sibling, b, None)))
    assert sibling_bound["binding_head"]["state"] == "active"

    # B supersedes A through the exact head; A's revision is retained for rollback
    second = _ok(case.post("bindings", _bind(key, b, head1)))
    head2 = second["binding_head"]
    assert second["binding_action"] == "supersede" and head2["revision"] == 2
    assert second["retained"]["target_binding_revision_ref"] == {
        "revision": 1, "binding_record_digest": head1["binding_record_digest"]}
    slot = _ok(case.get("bindings/" + digest))
    assert slot["head"] == head2 and slot["competition"]["current_holder"] == "ext-b"
    assert [row["extension_id"] for row in slot["history"]] == ["ext-a", "ext-b"]
    assert slot["history"][1]["supersedes_ref"] == {"revision": 1,
                                                     "binding_record_digest": head1["binding_record_digest"]}
    assert slot["coexisting_slots"] == [{
        "binding_slot_key_digest": sibling["binding_slot_key_digest"], "binding_slot_id": "review-provider",
        "capability_selector_digest": digest_of(SELECTOR), "head": sibling_bound["binding_head"],
        "extension_id": "ext-b"}]
    assert slot["logical_slot"] == {"binding_slot_id": "default-provider", "purpose": "operational",
                                    "port_contract_version": "provider-port-v1"}
    assert slot["trust_tier"] == "runtime_worker" and slot["extension_kind"] == "provider"
    assert slot["affected_environments"] == {
        "target_environment_id": None, "bound_environment_versions": [],
        "basis": "no_environment_version_records_extension_binding_revisions"}
    (retention_a,) = slot["rollback_retentions"]
    assert retention_a["retention_head"]["state"] == "retained" and retention_a["rollback_available"] is True
    assert retention_a["release_warning"] == release_warning(retention_a["target_binding_revision_ref"],
                                                             "ext-a", head2)
    assert "롤백할 수 없습니다" in retention_a["release_warning"]

    # disable B: the head is disabled and B's active revision is retained too
    _refused(case.post(f"bindings/{digest}/disable", _slot_body(key, "ext-b", head1)), "binding_head_stale")
    _refused(case.post(f"bindings/{digest}/disable", _slot_body(key, "ext-a", head2)), "extension_mismatch")
    disabled = _ok(case.post(f"bindings/{digest}/disable", _slot_body(key, "ext-b", head2)))
    head3 = disabled["binding_head"]
    assert (head3["revision"], head3["state"]) == (3, "disabled")
    slot = _ok(case.get("bindings/" + digest))
    assert slot["competition"]["current_holder"] is None
    retained = {row["target_extension_id"]: row for row in slot["rollback_retentions"]}
    assert set(retained) == {"ext-a", "ext-b"}

    # rollback to A re-checks A's qualification, consumes A's retention and appends revision 4
    body = _slot_body(key, "ext-a", head3, target_binding_revision_ref=retained["ext-a"]["target_binding_revision_ref"],
                      expected_retention_head=retained["ext-a"]["retention_head"])
    case.resolver.stale.add(a["qualification_ref"]["sha256"])
    _refused(case.post(f"bindings/{digest}/rollback", body), "qualification_not_current")
    case.resolver.stale.clear()
    _refused(case.post(f"bindings/{digest}/rollback", {**body, "expected_current_binding_head": head2}),
             "binding_head_stale")
    _refused(case.post(f"bindings/{digest}/rollback", {**body, "target_binding_revision_ref": {
        "revision": 3, "binding_record_digest": head3["binding_record_digest"]}}), "rollback_target_invalid")
    rolled = _ok(case.post(f"bindings/{digest}/rollback", body))
    head4 = rolled["binding_head"]
    assert (head4["revision"], head4["state"], rolled["binding_action"]) == (4, "active", "rollback")
    assert rolled["consumed"]["retention_head"]["state"] == "consumed"
    assert rolled["retained"] is None  # the displaced head was disabled, not active
    slot = _ok(case.get("bindings/" + digest))
    assert slot["current"]["extension_id"] == "ext-a"
    assert slot["history"][3]["rollback_of_ref"] == retained["ext-a"]["target_binding_revision_ref"]
    by_target = {row["target_binding_revision_ref"]["revision"]: row for row in slot["rollback_retentions"]}
    assert by_target[1]["retention_head"]["state"] == "consumed" and by_target[1]["release_warning"] is None
    # a consumed retention cannot be used again
    _refused(case.post(f"bindings/{digest}/rollback", {**body, "command_id": str(uuid4()),
                                                        "expected_current_binding_head": head4}),
             "retention_not_retained")

    # release B's retained revision (owner only, exact heads); nothing else changes
    retention_b = by_target[2]
    assert retention_b["retention_head"]["state"] == "retained"
    release_path = f"bindings/{digest}/rollback-retentions/{retention_b['target_binding_revision_ref']['binding_record_digest']}/release"
    release = _release_body(key, slot, retention_b)
    assert case.post(release_path, release, csrf_token=None).status_code in (401, 403)
    _refused(case.post(release_path, {**release, "target_service_tuple": _tuple("x")}), "target_mismatch")
    _refused(case.post(release_path, {**release, "expected_current_binding_head": head3}), "binding_head_stale")
    _refused(case.post(release_path, {**release, "reason": " "}), "invalid_input")
    _refused(case.post(f"bindings/{digest}/rollback-retentions/{'0' * 64}/release", release), "invalid_input")
    installation_heads = _ok(case.get("installations"))
    records = _records(case)
    released = _ok(case.post(release_path, release))
    assert tuple(released) == RELEASE_RESULT_FIELDS
    assert released["state"] == "released" and released["new_retention_revision"] == 2
    for name in ("command_id", "extension_id", "binding_slot_key", "binding_slot_key_digest",
                 "expected_current_binding_head", "target_binding_revision_ref", "target_installation_ref",
                 "target_service_tuple", "expected_retention_head"):
        assert released[name] == release[name], name
    assert _records(case) == records + 2  # the retention revision and its command record only
    after = _ok(case.get("bindings/" + digest))
    assert after["head"] == head4 and after["history"] == slot["history"]
    assert _ok(case.get("installations")) == installation_heads
    by_target = {row["target_binding_revision_ref"]["revision"]: row for row in after["rollback_retentions"]}
    assert by_target[2]["retention_head"]["state"] == "released"
    assert by_target[2]["history"][-1]["reason"] == release["reason"]
    assert by_target[2]["rollback_available"] is False and by_target[2]["release_warning"] is None
    # replay answers the same result; a changed body under the id conflicts; a repeat release is refused
    assert _ok(case.post(release_path, release)) == released
    _refused(case.post(release_path, {**release, "reason": "다른 사유"}), "command_conflict")
    _refused(case.post(release_path, {**release, "command_id": str(uuid4())}), "retention_not_retained")
    _refused(case.post(release_path, {**release, "command_id": str(uuid4()),
                                      "expected_retention_head": by_target[2]["retention_head"]}), "invalid_input")
    # a released target cannot be rolled back
    _refused(case.post(f"bindings/{digest}/rollback", _slot_body(
        key, "ext-b", head4, target_binding_revision_ref=retention_b["target_binding_revision_ref"],
        expected_retention_head=retention_b["retention_head"])), "retention_not_retained")
    # a current target and a cross-slot target are refused
    current = {"revision": 4, "binding_record_digest": head4["binding_record_digest"]}
    _refused(case.post(f"bindings/{digest}/rollback-retentions/{head4['binding_record_digest']}/release",
                       {**release, "command_id": str(uuid4()), "target_binding_revision_ref": current}),
             "rollback_target_invalid")
    sibling_digest = sibling["binding_slot_key_digest"]
    target_b = retention_b["target_binding_revision_ref"]["binding_record_digest"]
    _refused(case.post(f"bindings/{sibling_digest}/rollback-retentions/{target_b}/release",
                       {**release, "command_id": str(uuid4())}), "invalid_input")  # key is not the path's slot
    _refused(case.post(f"bindings/{sibling_digest}/rollback-retentions/{target_b}/release", {
        **release, "command_id": str(uuid4()), "binding_slot_key": sibling["binding_slot_key"],
        "binding_slot_key_digest": sibling_digest,
        "expected_current_binding_head": sibling_bound["binding_head"]}), "rollback_target_invalid")

    # one contract event per head move and per retention revision, each committed with its records
    events = _events(case)
    assert [(event["event_type"], event["public_metadata"]) for event in events] == [
        ("extension.binding_activated", _binding_meta(1, 0)),
        ("extension.binding_activated", _binding_meta(1, 0)),
        ("extension.binding_superseded", _binding_meta(2, 1)),
        ("extension.rollback_retention_created", _retention_meta(1, 1, 2, "absent", "retained")),
        ("extension.binding_disabled", _binding_meta(3, 2)),
        ("extension.rollback_retention_created", _retention_meta(1, 2, 3, "absent", "retained")),
        ("extension.binding_rolled_back", _binding_meta(4, 3)),
        ("extension.rollback_retention_consumed", _retention_meta(2, 1, 4, "retained", "consumed")),
        ("extension.rollback_retention_released", _retention_meta(2, 2, 4, "retained", "released")),
    ]
    # the object refs name the exact slot record (its id derives from the recomputed key digest)
    slot_id = slot_record_id(digest)
    rolled_event = events[6]
    assert rolled_event["object_refs"] == [
        {"kind": "extension_binding", "id": slot_id, "version": 4, "content_hash": head4["binding_record_digest"]},
        {"kind": "extension_binding", "id": slot_id, "version": 3, "content_hash": head3["binding_record_digest"]}]
    assert events[1]["object_refs"][0]["id"] == slot_record_id(sibling["binding_slot_key_digest"]) != slot_id
    released_event = events[8]
    assert released_event["object_refs"] == [
        {"kind": "extension_binding", "id": retention_record_id(digest, target_b), "version": 2,
         "content_hash": released["new_retention_record_digest"]},
        {"kind": "extension_binding", "id": slot_id, "version": 2, "content_hash": target_b},
        {"kind": "extension_binding", "id": slot_id, "version": 4, "content_hash": head4["binding_record_digest"]}]

    # the list pages the two slots; the history survives a cold reopen
    listed = _ok(case.get("bindings?limit=1"))
    assert len(listed["items"]) == 1 and listed["next_after"] == listed["items"][0]["binding_slot_key_digest"]
    rest = _ok(case.get("bindings?limit=1&after=" + listed["next_after"]))
    assert rest["next_after"] is None and len(rest["items"]) == 1
    assert {row["binding_slot_key_digest"] for row in listed["items"] + rest["items"]} == {digest, sibling_digest}
    row = next(item for item in listed["items"] + rest["items"] if item["binding_slot_key_digest"] == digest)
    assert row["head"] == head4 and row["retained_rollback_count"] == 0 and row["extension_id"] == "ext-a"
    assert row["links"]["self"] == case.base + "bindings/" + digest


def test_command_ids_replay_and_conflict(case):
    a = case.resolver.qualification("ext-a", "a")
    key = _key(case)
    body = _bind(key, a, None)
    first = _ok(case.post("bindings", body))
    records = _records(case)
    assert _ok(case.post("bindings", body)) == first and _records(case) == records
    _refused(case.post("bindings", {**body, "extension_id": "ext-a", "target_scope": body["target_scope"],
                                    "expected_current_binding_head": first["binding_head"]}), "command_conflict")
    # the same id used for another act conflicts too
    _refused(case.post(f"bindings/{key['binding_slot_key_digest']}/disable",
                       {**_slot_body(key, "ext-a", first["binding_head"]), "command_id": body["command_id"]}),
             "command_conflict")


def test_list_routes_page_candidates_and_installations(case):
    ids = []
    for _ in range(3):
        response = case.client.post(case.base + "candidates", headers=headers(case.profile, case.csrf),
                                    json=candidate_payload())
        assert response.status_code == 201, response.text
        ids.append(response.json()["candidate_ref"]["candidate_id"])
    page = _ok(case.get("candidates?limit=2"))
    assert page["schema_version"] == "extension-candidate-list-v1" and len(page["items"]) == 2
    assert page["next_after"] == page["items"][-1]["candidate_id"]
    rest = _ok(case.get("candidates?after=" + page["next_after"]))
    assert rest["next_after"] is None
    listed = [item["candidate_id"] for item in page["items"] + rest["items"]]
    assert listed == sorted(ids)
    row = page["items"][0]
    assert row["state"] == "registered_unqualified" and row["trust_tier"] == "runtime_worker"
    assert row["trust_tier_basis"] == "port_contract" and row["port_contract_version"] == "tool-port-v1"
    assert row["links"]["self"] == case.base + "candidates/" + row["candidate_id"]
    read = case.client.get(row["links"]["self"], headers=headers(case.profile)).json()
    assert read["candidate_ref"]["manifest_digest"] == row["manifest_digest"]
    assert case.client.head(case.base + "candidates", headers=headers(case.profile)).status_code in (400, 405)
    assert _ok(case.get("installations?limit=50")) == {
        "schema_version": "extension-installation-list-v1", "limit": 50, "items": [], "next_after": None}


def test_domain_rejects_inexact_binding_content(case):
    domain = case.app.state.domain_store
    roots = domain.roots()
    a = case.resolver.qualification("ext-a", "a")
    key = _key(case)
    _ok(case.post("bindings", _bind(key, a, None)))
    with domain._connection() as db:
        body = db.execute("SELECT body FROM domain_records WHERE kind='extension_binding' AND version=1 "
                          "ORDER BY rowid LIMIT 1").fetchone()[0]
    from app.domain.refs import parse_canonical
    content = parse_canonical(body)["content"]
    assert content["schema_version"] == "extension-binding-revision-v1"

    def attempt(changed, *, version=1):
        return ImmutableRecord.create(
            kind="extension_binding", id=parse_canonical(body)["id"], version=version,
            created_at_utc="2026-09-25T00:00:00.000000Z", actor_ref=roots.actor, parent_refs=(),
            purpose="operational", access_policy_ref=roots.access_policy,
            retention_policy_ref=roots.retention_policy, content=changed)

    four = dict(content["binding_slot_key"])
    del four["purpose"]
    for changed in ({**content, "binding_slot_key": four}, {**content, "binding_slot_key_digest": "0" * 64},
                    {**content, "trust_tier": "definition_package"}, {**content, "state": "disabled"},
                    {**content, "extra": 1}):
        with pytest.raises(DomainContractError):
            attempt(changed)
    with pytest.raises(DomainContractError):
        attempt(content, version=2)  # a revision is its record version
    # other content of the kind (outside these schemas) is left to its owner
    attempt({"historical_state": "tombstone"})


def test_installation_list_pages_with_trust_tier_staging_and_bindings(case):
    a = case.resolver.qualification("ext-a", "a")
    case.resolver.qualification("ext-b", "b")
    key = _key(case)
    _ok(case.post("bindings", _bind(key, a, None)))
    page = _ok(case.get("installations?limit=1"))
    assert len(page["items"]) == 1 and page["next_after"] == page["items"][0]["installation_id"]
    rest = _ok(case.get("installations?limit=1&after=" + page["next_after"]))
    assert rest["next_after"] is None and len(rest["items"]) == 1
    rows = {row["extension_id"]: row for row in page["items"] + rest["items"]}
    row = rows["ext-a"]
    assert (row["state"], row["revision"], row["extension_version"]) == ("verified", 2, "1.0.0")
    assert row["head_ref"] == a["installation_ref"] and row["staged_installation_ref"] == a["staged"]
    assert row["target_installation_ref"] == a["target_installation_ref"]
    assert (row["port_contract_version"], row["extension_kind"], row["trust_tier"], row["trust_tier_basis"]) == (
        "provider-port-v1", "provider", "runtime_worker", "port_contract")
    assert row["service_tuple"] == a["service_tuple"]
    staging = row["staging"]
    assert staging["state"] == "receipt_consumed" and staging["staging_authority"] == "deployment-provider-receipt-v1"
    assert staging["request_link"] == (case.base.removesuffix("extensions/")
                                       + "deployment/provider-requests/" + staging["request_ref"]["id"])
    assert row["active_binding_slot_digests"] == [key["binding_slot_key_digest"]]
    assert rows["ext-b"]["active_binding_slot_digests"] == []


def test_the_owner_screen_shows_the_exact_binding_refusal_texts():
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "static" / "extensions.mjs").read_text()
    block = source.split("export const BINDING_ERRORS = Object.freeze({", 1)[1].split("\n});", 1)[0]
    shown = {name: text for name, _quote, text in
             re.findall(r"^\s+([a-z_]+): (['\"])(.*)\2,$", block, re.MULTILINE)}
    assert shown == {code: message for code, (_status, message, _retry) in REFUSALS.items()}
