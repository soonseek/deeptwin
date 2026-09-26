"""Environment versions record the extension binding revisions they were prepared with (T087).

`prepare_environment_version` takes the durable active binding heads for the environment's scope
(`binding_heads.environment_binding_revisions`, read by the design workspace's prepare path); the
sealed `environment` record carries them (`environment-record-v2`); the binding slot inspection
lists every environment version that recorded a revision of the slot and whether the
environment's latest prepared version needs re-preparation. A binding change only marks that
state (and counts it in the contract event): no environment is re-prepared or promoted.

The pure version shape is pinned in `test_design_store.py`. The prepare flow is the real supported app (`test_design_workspace_api`'s TEST-ACTOR seed and
qualified test-actor critic); the binding records are written by the production binding
transaction (`app/tests/support/durable_binding.py`).
"""

from __future__ import annotations

import pytest

from app.tests.support import durable_binding
from app.tests.test_design_workspace_api import derive, post
from app.tests.test_web_owner_integration import headers


def _prepared(subject, request, roles):
    derivation = derive(subject, request.request_id, "select", [roles["base"].candidate_id]).json()
    reviewed = post(subject, request.request_id, "reviews", {"schema_version": "design-review-command-v1",
                                                             "derivation_id": derivation["derivation_id"]})
    assert reviewed.status_code == 201, reviewed.text
    candidate = reviewed.json()["reviewed_candidate"]
    prepared = post(subject, request.request_id, "preparations", {"schema_version": "design-prepare-command-v1",
                                                                  "candidate_id": candidate["candidate_id"]})
    assert prepared.status_code == 201, prepared.text
    return prepared.json()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from app.services.critic_qualification import critic_qualification_from_suite
    from app.tests.design_workspace_fixture import open_seeded
    from app.tests.test_environments import CRITIC_DIGEST, actor_record, actor_v3_design
    from app.tests.test_runs_api import Executor, owner_app

    installations = durable_binding.admit_test_installations(monkeypatch)
    with actor_v3_design():
        qualified = critic_qualification_from_suite(actor_record(), CRITIC_DIGEST)
    with owner_app(tmp_path, Executor()) as subject:
        request, roles = open_seeded(subject.app, criticism_turn=True, critic_qualification=qualified)
        qualification = durable_binding._put(subject.domain, "validation_report", {"fixture": "qualification"})
        yield subject, request, roles, installations, qualification


def _slot(subject, digest):
    response = subject.client.get(subject.profile.base_path + f"api/v1/extensions/bindings/{digest}",
                                  headers=headers(subject.profile))
    assert response.status_code == 200, response.text
    return response.json()


def _environments(subject):
    with subject.domain._connection() as db:
        return db.execute("SELECT id, version, sha256 FROM domain_records WHERE kind='environment' "
                          "ORDER BY id, version").fetchall()


def test_prepare_records_the_active_heads_and_a_binding_change_marks_the_environment(workspace):
    from app.services.design_persistence import decode_design_refs
    from app.services.design_workspace import environment_id_for

    subject, request, roles, installations, qualification = workspace
    environment_id = environment_id_for(request.request_id)
    wide = durable_binding.bind(subject.domain, installations, qualification_ref=qualification.as_dict())
    scoped = durable_binding.bind(subject.domain, installations, label="scoped", binding_slot_id="scoped-provider",
                                  environment_id=environment_id, qualification_ref=qualification.as_dict())
    elsewhere = durable_binding.bind(subject.domain, installations, label="elsewhere",
                                     binding_slot_id="other-environment",
                                     environment_id="00000000-0000-4000-8000-000000000001",
                                     qualification_ref=qualification.as_dict())
    off = durable_binding.bind(subject.domain, installations, label="off", binding_slot_id="disabled-provider",
                               qualification_ref=qualification.as_dict())
    durable_binding.disable(subject.domain, off.digest)
    result = _prepared(subject, request, roles)
    expected = sorted([
        {"binding_slot_key_digest": item.digest, "revision": 1,
         "binding_record_digest": item.result["binding_head"]["binding_record_digest"]}
        for item in (wide, scoped)], key=lambda item: item["binding_slot_key_digest"])
    # instance-wide and this environment's active heads; not another environment's, not a disabled one
    assert result["environment_version"]["extension_binding_revisions"] == expected
    record = subject.domain.get(__import__("app.domain.refs", fromlist=["EntityRef"]).EntityRef.from_dict(
        result["environment_ref"]))
    content = decode_design_refs(record.body["content"])
    assert content["schema_version"] == "environment-record-v2"
    assert content["extension_binding_revisions"] == expected
    slot = _slot(subject, wide.digest)
    (bound,) = slot["affected_environments"]["bound_environment_versions"]
    assert bound == {"environment_id": environment_id, "environment_version": 1,
                     "environment_record": result["environment_ref"], "binding_revision": 1,
                     "binding_record_digest": expected[[item["binding_slot_key_digest"] for item in expected].index(
                         wide.digest)]["binding_record_digest"],
                     "latest_prepared": True, "uses_current_head": True, "needs_re_preparation": False}
    assert slot["affected_environments"]["needs_re_preparation"] == []
    assert _slot(subject, elsewhere.digest)["affected_environments"]["bound_environment_versions"] == []

    # a supersession marks the environment as needing re-preparation; nothing is re-prepared or promoted
    before = _environments(subject)
    moved = durable_binding.bind(subject.domain, installations, label="wide-b", qualification_ref=qualification.as_dict())
    assert moved.result["environments_needing_re_preparation"] == [environment_id]
    assert _environments(subject) == before
    slot = _slot(subject, wide.digest)
    (bound,) = slot["affected_environments"]["bound_environment_versions"]
    assert (bound["uses_current_head"], bound["needs_re_preparation"]) == (False, True)
    assert slot["affected_environments"]["needs_re_preparation"] == [environment_id]
    assert _slot(subject, scoped.digest)["affected_environments"]["needs_re_preparation"] == []
    events = subject.client.get(subject.profile.base_path + "api/v1/events", headers=headers(subject.profile)).json()
    superseded = [event for event in events["events"] if event["event_type"] == "extension.binding_superseded"]
    assert superseded[-1]["public_metadata"]["affected_environment_count"] == 1
    # a rollback to the recorded revision is a new revision: the environment still needs re-preparation
    rolled = durable_binding.rollback(subject.domain, wide.digest, 1)
    assert rolled.result["environments_needing_re_preparation"] == [environment_id]
    assert _environments(subject) == before


def test_a_binding_change_between_the_read_and_the_prepare_is_marked_at_once(workspace, monkeypatch):
    from app.extensions import binding_heads
    from app.services.design_workspace import environment_id_for

    subject, request, roles, installations, qualification = workspace
    environment_id = environment_id_for(request.request_id)
    wide = durable_binding.bind(subject.domain, installations, qualification_ref=qualification.as_dict())
    original = binding_heads.environment_binding_revisions

    def read_then_disable(store, value):
        revisions = original(store, value)
        durable_binding.disable(subject.domain, wide.digest)  # a concurrent owner disable after the read
        return revisions

    monkeypatch.setattr(binding_heads, "environment_binding_revisions", read_then_disable)
    result = _prepared(subject, request, roles)
    assert [item["revision"] for item in result["environment_version"]["extension_binding_revisions"]] == [1]
    slot = _slot(subject, wide.digest)
    assert slot["head"]["state"] == "disabled"
    assert slot["affected_environments"]["needs_re_preparation"] == [environment_id]
