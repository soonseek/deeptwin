"""The owner's design workspace over the supported app (T037; FR-005/FR-008/FR-009).

A persisted design request (TEST-ACTOR seed: scripted generator and critic, never a
model) is read back through the issuing gates into the honest selection pool; select,
edit and merge persist a new derived version that requires re-review and inherits no
verdict; review runs only through a configured critic turn; and prepare attempts the
approval and answers the environments module's exact refusal while no critic is
qualified.
"""

from uuid import uuid4

from app.services.critic_qualification import critic_qualification_from_suite
from app.tests.design_workspace_fixture import CRITIC_ID, open_seeded
from app.tests.test_runs_api import Executor, owner_app
from app.tests.test_web_owner_integration import headers

ROOT = "api/v1/design-requests"


def url(subject, *parts):
    return subject.profile.base_path + "/".join((ROOT, *parts))


def post(subject, request_id, kind, body):
    return subject.client.post(url(subject, request_id, kind), headers=headers(subject.profile, subject.csrf),
                               json={"command_id": str(uuid4()), **body})


def derive(subject, request_id, action, parents, instruction=None):
    return post(subject, request_id, "derivations", {"schema_version": "design-derivation-command-v1",
                                                     "action": action, "parent_candidate_ids": parents,
                                                     "instruction": instruction})


def read(subject, request_id):
    response = subject.client.get(url(subject, request_id), headers=headers(subject.profile))
    assert response.status_code == 200, response.text
    return response.json()


def test_the_pool_is_read_back_honestly_with_the_real_count_and_reasons(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        request, roles = open_seeded(subject.app)
        listed = subject.client.get(url(subject), headers=headers(subject.profile)).json()
        assert listed["requests"] == [{"request_id": request.request_id, "version": 1,
                                       "requested_candidate_count": 3}]
        view = read(subject, request.request_id)
        pool = view["pool"]
        presented = {roles["base"].candidate_id, roles["reshaped"].candidate_id}
        assert set(pool["presented_candidate_ids"]) == presented
        assert pool["presented_count"] == 2 and pool["pool_size"] == 3 and pool["candidate_count"] == 4
        assert pool["passed_count"] == 3 and pool["supplementation_available"] is True
        reasons = {item["candidate_id"]: item["reason"] for item in pool["excluded"]}
        assert reasons[roles["duplicate"].candidate_id] == "structural_duplicate"
        assert reasons[roles["rejected"].candidate_id].startswith("rejected:review_fail:")
        shown = {item["candidate_id"]: item for item in view["candidates"]}
        assert [item["presented"] for item in view["candidates"]][:2] == [True, True]
        verdict = shown[roles["base"].candidate_id]["verdict"]
        # the verdict is the recorded conclusion of the named test-actor critic, never live
        assert verdict["status"] == "passed" and verdict["source"] == "persisted_criticism"
        assert verdict["model_ids"] == [CRITIC_ID] and verdict["call_count"] == 2
        graph = shown[roles["base"].candidate_id]["graph"]
        assert graph["model_bindings"] and graph["tool_bindings"]
        assert view["review"] == {"available": False, "reason": "critic_model_not_configured",
                                  "critic_model_id": None, "realizes": ["select"]}
        assert view["preparation"]["approvable"] is False
        assert view["preparation"]["critic_qualification"]["status"] == "unknown"
        assert view["preparation"]["reason"] == "the critic configuration is not qualified (unknown: no_suite_record)"
        head = subject.client.head(url(subject, request.request_id), headers=headers(subject.profile))
        assert head.status_code == 200 and head.content == b""


def test_select_edit_merge_persist_new_versions_that_require_re_review(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        request, roles = open_seeded(subject.app)
        base, reshaped = roles["base"].candidate_id, roles["reshaped"].candidate_id
        selected = derive(subject, request.request_id, "select", [base])
        assert selected.status_code == 201, selected.text
        edited = derive(subject, request.request_id, "edit", [reshaped], "검토 단계를 하나 더 둔다")
        merged = derive(subject, request.request_id, "merge", [base, reshaped])
        for response in (selected, edited, merged):
            value = response.json()
            assert value["re_review_required"] is True and value["inherited_verdict"] is None
            assert value["reviewed_candidate"] is None
        assert edited.json()["instruction"] == "검토 단계를 하나 더 둔다"
        view = read(subject, request.request_id)
        assert sorted(item["action"] for item in view["derivations"]) == ["edit", "merge", "select"]
        # the originals keep their own verdicts; nothing moved to the derived versions
        assert all(item["re_review_required"] for item in view["derivations"])
        # refused: an edit without its instruction, a one-parent merge, a non-presented parent
        assert derive(subject, request.request_id, "edit", [base]).status_code == 400
        assert derive(subject, request.request_id, "merge", [base]).status_code == 400
        refused = derive(subject, request.request_id, "select", [roles["rejected"].candidate_id])
        assert refused.status_code == 400
        assert refused.json()["reason"] == "only a presented candidate can be selected, edited or merged"
        # an exact replay of one command is the same act, never a second version
        body = {"schema_version": "design-derivation-command-v1", "command_id": str(uuid4()),
                "action": "select", "parent_candidate_ids": [reshaped], "instruction": None}
        first = subject.client.post(url(subject, request.request_id, "derivations"),
                                    headers=headers(subject.profile, subject.csrf), json=body)
        again = subject.client.post(url(subject, request.request_id, "derivations"),
                                    headers=headers(subject.profile, subject.csrf), json=body)
        assert first.json()["derivation_id"] == again.json()["derivation_id"]
        other = subject.client.post(url(subject, request.request_id, "derivations"),
                                    headers=headers(subject.profile, subject.csrf),
                                    json={**body, "parent_candidate_ids": [base]})
        assert other.status_code == 409
        assert len(read(subject, request.request_id)["derivations"]) == 4


def test_review_is_unavailable_without_a_configured_critic_and_prepare_refuses_exactly(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        request, roles = open_seeded(subject.app)
        derivation = derive(subject, request.request_id, "select", [roles["base"].candidate_id]).json()
        review = post(subject, request.request_id, "reviews", {"schema_version": "design-review-command-v1",
                                                               "derivation_id": derivation["derivation_id"]})
        assert review.status_code == 503
        assert review.json()["code"] == "review_unavailable"
        assert review.json()["reason"] == "critic_model_not_configured"
        prepare = post(subject, request.request_id, "preparations", {"schema_version": "design-prepare-command-v1",
                                                                     "candidate_id": roles["base"].candidate_id})
        assert prepare.status_code == 409
        assert prepare.json() | {"correlation_id": None} == {
            "code": "not_approvable", "message": "This design cannot be approved or prepared",
            "reason": "the critic configuration is not qualified (unknown: no_suite_record)",
            "retryability": "not_retryable", "affected_refs": [], "correlation_id": None}
        derived = post(subject, request.request_id, "preparations", {"schema_version": "design-prepare-command-v1",
                                                                     "candidate_id": derivation["derivation_id"]})
        assert derived.status_code == 409 and derived.json()["reason"] == "re_review_required"
        rejected = post(subject, request.request_id, "preparations", {"schema_version": "design-prepare-command-v1",
                                                                      "candidate_id": roles["rejected"].candidate_id})
        assert rejected.json()["reason"] == "only a passed design version is approvable"
        # nothing was approved: no owner decision was recorded
        with subject.domain._connection() as db:
            assert db.execute("SELECT count(*) FROM domain_records WHERE kind='action_approval'").fetchone()[0] == 0


def test_a_configured_critic_re_reviews_a_select_and_a_qualified_test_actor_critic_prepares(tmp_path):
    from app.tests.test_environments import CRITIC_DIGEST, actor_record, actor_v3_design

    with actor_v3_design():
        # TEST-ACTOR qualification of the test-only V3-verifying design id; no real one exists
        qualified = critic_qualification_from_suite(actor_record(), CRITIC_DIGEST)
    with owner_app(tmp_path, Executor()) as subject:
        request, roles = open_seeded(subject.app, criticism_turn=True, critic_qualification=qualified)
        derivation = derive(subject, request.request_id, "select", [roles["base"].candidate_id]).json()
        edit = derive(subject, request.request_id, "edit", [roles["base"].candidate_id], "바꾼다").json()
        body = {"schema_version": "design-review-command-v1"}
        not_generated = post(subject, request.request_id, "reviews", {**body, "derivation_id": edit["derivation_id"]})
        assert not_generated.status_code == 503 and not_generated.json()["reason"] == "derived_graph_not_generated"
        reviewed = post(subject, request.request_id, "reviews", {**body, "derivation_id": derivation["derivation_id"]})
        assert reviewed.status_code == 201, reviewed.text
        value = reviewed.json()
        assert value["re_review_required"] is False and value["inherited_verdict"] is None
        candidate = value["reviewed_candidate"]
        assert candidate["verdict"]["status"] == "passed" and candidate["verdict"]["model_ids"] == [CRITIC_ID]
        assert candidate["parent_candidate_ids"] and candidate["candidate_id"] != roles["base"].candidate_id
        prepared = post(subject, request.request_id, "preparations", {"schema_version": "design-prepare-command-v1",
                                                                      "candidate_id": candidate["candidate_id"]})
        assert prepared.status_code == 201, prepared.text
        result = prepared.json()
        assert result["status"] == "prepared" and result["activation"] == "not_activated"
        assert result["environment_version"]["status"] == "prepared"
        assert result["environment_version"]["version"] == 1


def test_wire_and_auth_are_closed(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        request, _roles = open_seeded(subject.app)
        base = subject.profile.base_path + ROOT
        assert subject.client.get(base + f"/{uuid4()}", headers=headers(subject.profile)).status_code == 404
        assert subject.client.get(base + "/not-a-uuid", headers=headers(subject.profile)).status_code == 400
        assert subject.client.get(base + "?x=1", headers=headers(subject.profile)).status_code == 400
        wrong = subject.client.post(base + f"/{request.request_id}/derivations",
                                    headers=headers(subject.profile, subject.csrf),
                                    json={"schema_version": "design-derivation-command-v1"})
        assert wrong.status_code == 400
        no_csrf = subject.client.post(base + f"/{request.request_id}/derivations", headers=headers(subject.profile),
                                      json={"schema_version": "design-derivation-command-v1",
                                            "command_id": str(uuid4()), "action": "select",
                                            "parent_candidate_ids": [], "instruction": None})
        assert no_csrf.status_code in {401, 403}
