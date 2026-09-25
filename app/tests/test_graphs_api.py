"""The owner's read of a stored functional graph over the supported app (T037/T048)."""

from uuid import uuid4

from app.tests.test_graph_execution import linear_graph
from app.tests.test_runs_api import Executor, graph_record, owner_app
from app.tests.test_server_api_v1 import immutable
from app.tests.test_web_owner_integration import headers


def path(subject, ref):
    return subject.profile.base_path + f"api/v1/graphs/{ref['id'] if isinstance(ref, dict) else ref.id}/versions/" \
        f"{ref['version'] if isinstance(ref, dict) else ref.version}"


def test_a_stored_functional_graph_reads_back_parsed(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        ref = graph_record(subject, linear_graph())
        read = subject.client.get(path(subject, ref), headers=headers(subject.profile))
        assert read.status_code == 200, read.text
        value = read.json()
        assert value["graph_ref"] == ref.as_dict()
        assert sorted(node["node_id"] for node in value["graph"]["nodes"]) == ["intake", "publish", "writer"]
        assert value["graph"]["model_bindings"][0]["model_choice_ref"]["kind"] == "model_choice"
        assert read.headers["cache-control"] == "no-store"


def test_absent_malformed_and_non_graph_reads_are_refused(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        base = subject.profile.base_path + "api/v1/graphs/"
        assert subject.client.get(base + f"{uuid4()}/versions/1", headers=headers(subject.profile)).status_code == 404
        assert subject.client.get(base + "not-a-uuid/versions/1", headers=headers(subject.profile)).status_code == 400
        assert subject.client.get(base + f"{uuid4()}/versions/01", headers=headers(subject.profile)).status_code == 400
        assert subject.client.get(base + f"{uuid4()}/versions/1?x=1", headers=headers(subject.profile)).status_code == 400
        # a graph record that is not a functional graph is never shown half-read
        other = immutable(subject.domain, subject.domain.roots(), "graph", content={"design_kind": "other"})
        assert subject.client.get(path(subject, other.ref), headers=headers(subject.profile)).status_code == 400
