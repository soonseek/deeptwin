"""What a run of one work can use (T048): `GET /api/v1/run-environments/{work_id}`.

Production today: no environment is prepared (no critic can be qualified), and the read
says exactly that. TEST-ACTOR (SIMULATED qualification, `design_arc_fixture`): a design
generated and prepared over the work is offered with the exact graph record, work
revision, bindings and qualification the run will use; an environment prepared for a
design outside this vault (`browser_grant_chain.approved_environment`) is not offered but
counted with its reason; and the offered inputs start a run through the existing consent
and run routes.
"""

from uuid import uuid4

from app.domain.refs import EntityRef
from app.tests.design_arc_fixture import open_scenarios, simulated_qualification
from app.tests.test_design_arc import generate, post, read, work_with_source
from app.tests.test_runs_api import Executor, owner_app
from app.tests.test_web_owner_integration import headers


class DesignExecutor(Executor):
    """The code-owned test executor, compiling under the design request's authority."""

    def compile(self, graph):
        from app.runtime.graph import compile_graph
        from app.tests.test_design_generation import design_authority

        return compile_graph(graph, design_authority())


def environments(subject, work_id):
    response = subject.client.get(subject.profile.base_path + f"api/v1/run-environments/{work_id}",
                                  headers=headers(subject.profile))
    return response


def prepared(subject):
    revision, sources = work_with_source(subject)
    arcs = open_scenarios(subject.app, revision, sources, scenarios=("three",),
                          critic_qualification=simulated_qualification())
    request_id = arcs["three"]["request"].request_id
    assert generate(subject, request_id).status_code == 201
    candidate = read(subject, request_id)["pool"]["presented_candidate_ids"][0]
    done = post(subject, request_id, "preparations", {"schema_version": "design-prepare-command-v1",
                                                      "candidate_id": candidate})
    assert done.status_code == 201, done.text
    return revision, done.json()


def test_without_a_prepared_environment_the_read_says_exactly_why(tmp_path):
    with owner_app(tmp_path, None) as subject:
        revision, _sources = work_with_source(subject)
        value = environments(subject, revision.id).json()
        assert value["environments"] == []
        assert value["absence"] == {"code": "no_prepared_environment", "reason": "no_approved_design",
                                    "critic_qualifiable": False}
        assert value["runs"] == {"available": False, "reason": "run_executor_not_configured"}
        assert value["work"]["current_revision_ref"]["id"] == revision.id
        assert environments(subject, str(uuid4())).status_code == 404
        assert environments(subject, "not-a-uuid").status_code == 400
        # owner_app's placeholder `environment` row is no prepared version: counted, never offered
        assert value["unresolved"] == [{"reason": "not_an_environment_record", "count": 1}]
        subject.client.cookies.clear()
        assert environments(subject, revision.id).status_code == 401


def test_a_simulated_prepared_environment_is_offered_exactly_and_starts_a_run(tmp_path):
    from app.tests.support.browser_grant_chain import approved_environment

    with owner_app(tmp_path, DesignExecutor()) as subject:
        revision, done = prepared(subject)
        # an environment approved for a design that is not in this vault: never offered
        vault = type("Vault", (), {"app": subject.app, "request": None})()
        vault.request = _owner_request(subject)
        approved_environment(vault, EntityRef.from_dict({"kind": "grant", "id": str(uuid4()), "version": 1,
                                                          "sha256": "a" * 64}))
        value = environments(subject, revision.id).json()
        assert value["absence"] is None and value["runs"]["available"] is True
        assert value["unresolved"] == [{"reason": "graph_not_in_vault", "count": 1},
                                       {"reason": "not_an_environment_record", "count": 1}]
        [entry] = value["environments"]
        assert entry["environment_ref"] == done["environment_ref"]
        assert entry["status"] == "prepared" and entry["activation"] == "not_activated"
        assert entry["usable"] is True and entry["revision_current"] is True
        assert entry["work_revision_ref"] == revision.as_dict()
        assert entry["critic_qualification"]["status"] == "qualified"
        assert entry["critic_qualification"]["simulated"] is True  # test-actor, never a release qualification
        assert entry["graph"]["digest"] == done["environment_version"]["design_ref"]["sha256"]
        assert entry["approval"]["model_bindings_ref"]["kind"] == "model_choice"
        assert entry["approval"]["tool_permissions_ref"]["kind"] == "grant"
        # the offered inputs are exactly what the consent and run routes accept
        policy = subject.refs.budget.as_dict()
        inputs = {"graph_ref": entry["graph_ref"], "work_revision_ref": entry["work_revision_ref"],
                  "environment_ref": entry["environment_ref"], "budget_policy_ref": policy}
        consent = subject.client.post(subject.profile.base_path + "api/v1/run-consents",
                                      headers=headers(subject.profile, subject.csrf),
                                      json={"schema_version": "run-consent-command-v1", "command_id": str(uuid4()),
                                            **inputs})
        assert consent.status_code == 201, consent.text
        started = subject.client.post(subject.path, headers=headers(subject.profile, subject.csrf),
                                      json={"command_id": str(uuid4()), **inputs, "consent_ref": consent.json()["ref"]})
        assert started.status_code == 201, started.text
        assert started.json()["phase"] in {"awaiting_human", "completed"}
        # a newer revision of the work: still offered, for the revision it was designed for
        from app.tests.test_works_api import REVISE

        revised = subject.client.post(subject.profile.base_path + f"api/v1/works/{revision.id}/revisions",
                                      headers=headers(subject.profile, subject.csrf),
                                      json={"schema_version": REVISE, "command_id": str(uuid4()),
                                            "expected_revision": revision.version, "text": "고친 설명"})
        assert revised.status_code in (200, 201), revised.text
        entry = environments(subject, revision.id).json()["environments"][0]
        assert entry["revision_current"] is False and entry["work_revision_ref"] == revision.as_dict()


def _owner_request(subject):
    """The owner's authenticated request, as a route handler holds it (the grant chain's
    producers record the owner's decision through it)."""
    from app.tests.test_web_owner_integration import bound_request

    return bound_request(subject.app, subject.client, subject.profile, subject.csrf)
