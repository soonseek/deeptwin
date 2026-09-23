"""The run consent: the first missing link of run creation from the intake
(resumption-plan Continuation; T048 "run creation from the intake"; data-model
§3 "`RunConsent` authorizes a specific execution or bounded policy … distinct
grants"; experience §6.3 `업무 시작` fixes the input/environment version and this
run's allowed usage and model path, and never implies more).

`POST /api/v1/run-consents` (`run-consent-command-v1`) seals one immutable
`run_consent` record per command over the exact stored records the run will
name — the graph, the work revision, the environment and the budget policy —
authored by the owner's human actor with its `approval.decided` public event in
the same transaction. Exact replay returns the same consent; any other body
under the same command conflicts; an unresolvable input is not found; a
reference of the wrong kind is invalid. `GET|HEAD …/{consent_id}` reads it.
`POST /api/v1/runs` then accepts the sealed consent as its `consent_ref`. No
model, tool or paid call; the fake executor only.
"""

from uuid import uuid4

from app.services.run_consents import consent_identity
from app.tests.test_graph_execution import linear_graph
from app.tests.test_runs_api import Executor, events, graph_record, owner_app, post
from app.tests.test_server_api_v1 import immutable
from app.tests.test_web_owner_integration import headers

SCHEMA = "run-consent-command-v1"
REF_FIELDS = ("graph_ref", "work_revision_ref", "environment_ref", "budget_policy_ref")


def object_ref(ref):
    """The public event's reference shape for a stored record reference."""
    return {"kind": ref["kind"], "id": ref["id"], "version": ref["version"], "content_hash": ref["sha256"]}


def consent_path(subject):
    return subject.profile.base_path + "api/v1/run-consents"


def consent_command(subject, graph, **changes):
    body = {
        "schema_version": SCHEMA,
        "command_id": str(uuid4()),
        "graph_ref": graph.as_dict(),
        "work_revision_ref": subject.refs.work.as_dict(),
        "environment_ref": subject.refs.environment.as_dict(),
        "budget_policy_ref": subject.refs.budget.as_dict(),
    }
    return {**body, **changes}


def test_an_owner_records_one_consent_per_command_over_the_exact_inputs(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        graph_ref = graph_record(subject, linear_graph())
        body = consent_command(subject, graph_ref)
        created = post(subject, body, consent_path(subject))
        assert created.status_code == 201, created.text
        consent = created.json()
        assert set(consent) == {"consent_id", "ref", "command_id", "decided_at_utc", "expires_at_utc", "revocation",
                                *REF_FIELDS}
        assert consent["expires_at_utc"] is None
        assert consent["revocation"] is None
        assert consent["consent_id"] == consent_identity(body["command_id"])
        assert consent["ref"]["kind"] == "run_consent" and consent["ref"]["id"] == consent["consent_id"]
        assert consent["ref"]["version"] == 1
        for name in REF_FIELDS:
            assert consent[name] == body[name]
        # the consent is its own public fact: decided over the sealed record and the four
        # exact inputs it names
        def decided():
            return [item for item in events(subject, "approval.decided")
                    if object_ref(consent["ref"]) in item["object_refs"]]

        assert len(decided()) == 1 and decided()[0]["public_metadata"]["decision"] == "approved"
        assert decided()[0]["object_refs"] == [object_ref(consent["ref"]), *(object_ref(body[name]) for name in REF_FIELDS)]
        # exact replay: the same consent, nothing new sealed
        again = post(subject, body, consent_path(subject))
        assert again.status_code == 201 and again.json() == consent
        assert len(decided()) == 1
        # the same command over any other input conflicts
        other_graph = graph_record(subject, linear_graph())
        conflict = post(subject, {**body, "graph_ref": other_graph.as_dict()}, consent_path(subject))
        assert conflict.status_code == 409 and conflict.json()["code"] == "conflict"
        # read back, GET and HEAD alike
        current = subject.client.get(consent_path(subject) + "/" + consent["consent_id"],
                                     headers=headers(subject.profile))
        head = subject.client.head(consent_path(subject) + "/" + consent["consent_id"],
                                   headers=headers(subject.profile))
        assert current.status_code == head.status_code == 200 and head.content == b""
        assert current.json() == consent
        assert current.headers["cache-control"] == "no-store"
        missing = subject.client.get(consent_path(subject) + "/" + str(uuid4()), headers=headers(subject.profile))
        assert missing.status_code == 404 and missing.json()["code"] == "not_found"


def test_a_consent_names_only_stored_records_of_the_right_kinds(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        graph_ref = graph_record(subject, linear_graph())
        # an unresolvable input: the exact record (kind, id, version, digest) is not there
        absent = graph_ref.as_dict() | {"sha256": "0" * 64}
        refused = post(subject, consent_command(subject, graph_ref, graph_ref=absent), consent_path(subject))
        assert refused.status_code == 404 and refused.json()["code"] == "not_found"
        # a stored record of another kind in a slot: invalid, never consented to
        refused = post(subject, consent_command(subject, graph_ref, environment_ref=subject.refs.work.as_dict()),
                       consent_path(subject))
        assert refused.status_code == 400 and refused.json()["code"] == "invalid_input"
        # a design record that is not a functional graph
        design = immutable(subject.domain, subject.domain.roots(), "graph", content={"design_kind": "other"}).ref
        refused = post(subject, consent_command(subject, graph_ref, graph_ref=design.as_dict()), consent_path(subject))
        assert refused.status_code == 400 and refused.json()["code"] == "invalid_input"
        assert events(subject, "approval.decided") == []


def test_the_wire_admits_only_the_exact_command(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        graph_ref = graph_record(subject, linear_graph())
        good = consent_command(subject, graph_ref)
        path = consent_path(subject)
        for bad in (
            {**good, "schema_version": "run-consent-command-v0"},
            {**good, "command_id": "not-a-uuid"},
            {**good, "graph_ref": {**good["graph_ref"], "extra": 1}},
            {**good, "graph_ref": {**good["graph_ref"], "version": "1"}},
            {key: value for key, value in good.items() if key != "budget_policy_ref"},
            {**good, "consent_ref": good["graph_ref"]},
        ):
            refused = post(subject, bad, path)
            assert refused.status_code == 400 and refused.json()["code"] == "invalid_input", bad
        oversized = subject.client.post(path, content=b"{" + b" " * 5000 + b"}",
                                        headers={**headers(subject.profile, subject.csrf), "content-type": "application/json"})
        assert oversized.status_code == 413
        with_query = subject.client.post(path + "?x=1", json=good, headers=headers(subject.profile, subject.csrf))
        assert with_query.status_code == 400
        body_on_read = subject.client.request("GET", path + "/" + str(uuid4()), content=b"{}", headers=headers(subject.profile))
        assert body_on_read.status_code == 400
        # no session: a well-formed command is refused as unauthenticated (the wire preflight
        # runs first, as on every route: a malformed anonymous body is a wire refusal)
        cookies = dict(subject.client.cookies)
        subject.client.cookies.clear()
        anonymous = post(subject, good, path)
        assert anonymous.status_code == 401 and anonymous.json()["code"] == "unauthenticated"
        for name, value in cookies.items():
            subject.client.cookies.set(name, value)
        assert events(subject, "approval.decided") == []


def test_a_sealed_consent_starts_the_run_it_names(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        graph_ref = graph_record(subject, linear_graph())
        consent = post(subject, consent_command(subject, graph_ref), consent_path(subject)).json()
        started = post(subject, {
            "command_id": str(uuid4()),
            "graph_ref": graph_ref.as_dict(),
            "work_revision_ref": subject.refs.work.as_dict(),
            "environment_ref": subject.refs.environment.as_dict(),
            "consent_ref": consent["ref"],
            "budget_policy_ref": subject.refs.budget.as_dict(),
        })
        assert started.status_code == 201, started.text
        assert started.json()["phase"] == "completed"
        assert executor.calls == ["intake", "writer", "publish"]


# --- review closures ----------------------------------------------------------------------

def stored_consent(subject, command_id, *, content_changes=None, actor=None):
    """A `run_consent` row written outside the service: by the vault's root actor, with any
    content — never consent evidence unless it carries the writer's whole discipline."""
    from app.domain.schemas import ImmutableRecord
    from app.services.run_consents import consent_identity

    domain = subject.domain
    roots = domain.roots()
    graph_ref = graph_record(subject, linear_graph())
    content = {
        "schema_version": "run-consent-v1", "command_id": command_id,
        "graph_ref": graph_ref.as_dict(), "work_revision_ref": subject.refs.work.as_dict(),
        "environment_ref": subject.refs.environment.as_dict(),
        "budget_policy_ref": subject.refs.budget.as_dict(),
        "decided_at_utc": "2026-09-22T00:00:00.000000Z", "event_sequence": 999,
    }
    content.update(content_changes or {})
    record = ImmutableRecord.create(
        kind="run_consent", id=consent_identity(command_id), version=1,
        created_at_utc="2026-09-22T00:00:00.000000Z", actor_ref=actor or roots.actor, parent_refs=(),
        purpose="operational", access_policy_ref=roots.access_policy,
        retention_policy_ref=roots.retention_policy, content=content,
    )
    domain.put(record)
    return record, graph_ref


def test_a_stored_row_without_the_writers_discipline_is_never_a_consent(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        path = consent_path(subject)
        # written by the vault's root actor, under another command, with no decided event
        command_id = str(uuid4())
        forged, graph_ref = stored_consent(subject, command_id, content_changes={"command_id": str(uuid4())})
        current = subject.client.get(path + "/" + forged.ref.id, headers=headers(subject.profile))
        assert current.status_code == 503 and current.json()["code"] == "unavailable"
        # the replay branch never repairs it: the command it derives from is refused, not served
        replay = post(subject, consent_command(subject, graph_ref, command_id=command_id), path)
        assert replay.status_code == 503 and replay.json()["code"] == "unavailable"
        assert events(subject, "approval.decided") == []
        # a row with the right command but no bound decided event, or the wrong stamp, is the same
        for changes in ({}, {"decided_at_utc": "yesterday"}, {"event_sequence": 0}):
            command_id = str(uuid4())
            forged, _ = stored_consent(subject, command_id, content_changes=changes)
            current = subject.client.get(path + "/" + forged.ref.id, headers=headers(subject.profile))
            assert current.status_code == 503, changes


def test_a_consent_names_only_inputs_the_run_can_read(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        path = consent_path(subject)
        roots = subject.domain.roots()
        # a functional graph record without its design: the executor could not read it
        headless = immutable(subject.domain, roots, "graph", content={"design_kind": "functional_graph"}).ref
        refused = post(subject, consent_command(subject, headless), path)
        assert refused.status_code == 400 and refused.json()["code"] == "invalid_input"
        # a budget policy record that is not a policy binding: it fixes no usage
        graph_ref = graph_record(subject, linear_graph())
        loose = immutable(subject.domain, roots, "budget_policy").ref
        refused = post(subject, consent_command(subject, graph_ref, budget_policy_ref=loose.as_dict()), path)
        assert refused.status_code == 400 and refused.json()["code"] == "invalid_input"
        assert events(subject, "approval.decided") == []


def test_the_wire_and_the_command_are_pinned_at_their_edges(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        path = consent_path(subject)
        graph_ref = graph_record(subject, linear_graph())
        good = consent_command(subject, graph_ref)
        # a POST without the CSRF token is access denied
        no_csrf = subject.client.post(path, json=good, headers=headers(subject.profile))
        assert no_csrf.status_code == 403
        # every absent input is not found, not only the graph
        for name in ("work_revision_ref", "environment_ref", "budget_policy_ref"):
            absent = {**good[name], "sha256": "0" * 64}
            refused = post(subject, {**good, name: absent}, path)
            assert refused.status_code == 404 and refused.json()["code"] == "not_found", name
        sealed = post(subject, good, path)
        assert sealed.status_code == 201
        # the same command over another non-graph input conflicts, and conflict beats not found
        other_work = immutable(subject.domain, subject.domain.roots(), "work_revision").ref
        conflict = post(subject, {**good, "work_revision_ref": other_work.as_dict()}, path)
        assert conflict.status_code == 409
        conflict = post(subject, {**good, "environment_ref": {**good["environment_ref"], "sha256": "0" * 64}}, path)
        assert conflict.status_code == 409
        # methods and shapes off the two routes are refused at the wire
        client, own = subject.client, headers(subject.profile, subject.csrf)
        assert client.put(path, json=good, headers=own).status_code == 400
        assert client.get(path, headers=headers(subject.profile)).status_code == 400
        item = path + "/" + sealed.json()["consent_id"]
        assert client.post(item, json=good, headers=own).status_code == 400
        assert client.delete(item, headers=own).status_code == 400
        assert client.get(item + "/extra", headers=headers(subject.profile)).status_code == 400
        # the exact 4 096-byte bound
        padded = dict(good, command_id=str(uuid4()))
        import json as json_module

        raw = json_module.dumps(padded, separators=(",", ":")).encode()
        filler = 4096 - len(raw) - len(b',"":""')
        at_bound = raw[:-1] + b',"":"' + b"x" * filler + b'"}'
        assert len(at_bound) == 4096
        over = raw[:-1] + b',"":"' + b"x" * (filler + 1) + b'"}'
        assert len(over) == 4097
        json_headers = {**own, "content-type": "application/json"}
        assert client.post(path, content=over, headers=json_headers).status_code == 413
        # at the bound the wire admits the bytes; the extra member is the command's refusal
        assert client.post(path, content=at_bound, headers=json_headers).status_code == 400
        # no refusal emitted an event; only the one sealed consent did
        assert len(events(subject, "approval.decided")) == 1


# --- the run route verifies its consent (experience §6.3: the server verifies each effect,
# version and scope independently; runtime.md: verify the consent before dispatch) ----------

def run_command(subject, graph_ref, consent_ref, **changes):
    body = {
        "command_id": str(uuid4()),
        "graph_ref": graph_ref.as_dict(),
        "work_revision_ref": subject.refs.work.as_dict(),
        "environment_ref": subject.refs.environment.as_dict(),
        "consent_ref": consent_ref,
        "budget_policy_ref": subject.refs.budget.as_dict(),
    }
    return {**body, **changes}


def test_a_run_starts_only_under_a_consent_that_names_exactly_its_inputs(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        path = consent_path(subject)
        graph_ref = graph_record(subject, linear_graph())
        other_graph = graph_record(subject, linear_graph())
        consent = post(subject, consent_command(subject, graph_ref), path).json()
        # a consent over another graph is not this run's consent
        refused = post(subject, run_command(subject, other_graph, consent["ref"]))
        assert refused.status_code == 403 and refused.json()["code"] == "access_denied"
        # nor one over another work revision, environment or budget policy
        roots = subject.domain.roots()
        other_work = immutable(subject.domain, roots, "work_revision").ref
        refused = post(subject, run_command(subject, graph_ref, consent["ref"], work_revision_ref=other_work.as_dict()))
        assert refused.status_code == 403 and refused.json()["code"] == "access_denied"
        # a `run_consent` row without the writer's discipline (a fixture, a foreign author) is no consent
        fixture = immutable(subject.domain, roots, "run_consent").ref
        refused = post(subject, run_command(subject, graph_ref, fixture.as_dict()))
        assert refused.status_code == 403 and refused.json()["code"] == "access_denied"
        assert events(subject, "run.started") == [] and executor.calls == []
        # nor one over another environment or budget policy, nor another version of the graph
        other_environment = immutable(subject.domain, roots, "environment").ref
        refused = post(subject, run_command(subject, graph_ref, consent["ref"], environment_ref=other_environment.as_dict()))
        assert refused.status_code == 403
        other_budget = immutable(subject.domain, roots, "budget_policy").ref  # refused before its parse
        refused = post(subject, run_command(subject, graph_ref, consent["ref"], budget_policy_ref=other_budget.as_dict()))
        assert refused.status_code == 403
        assert events(subject, "run.started") == [] and executor.calls == []
        # the consent that names exactly these inputs starts the run, and its replay is the same run
        body = run_command(subject, graph_ref, consent["ref"])
        started = post(subject, body)
        assert started.status_code == 201, started.text
        assert started.json()["phase"] == "completed"
        assert post(subject, body).json()["run_id"] == started.json()["run_id"]
        assert len(events(subject, "run.started")) == 1
        # once sealed, the consent is a replay input: the same command under another consent
        # is a conflict, not a fresh verification
        other_consent = post(subject, consent_command(subject, graph_ref), path).json()
        assert post(subject, {**body, "consent_ref": other_consent["ref"]}).status_code == 409
        # the sealed manifest names the consent the run was started under
        from app.domain.refs import EntityRef
        from app.services.runs import manifest_identity

        with subject.domain._connection() as db:
            roots = subject.domain._read_roots(db)
            row = db.execute("SELECT sha256 FROM domain_records WHERE vault_id=? AND kind='run_manifest' AND id=?",
                             (roots.genesis.id, manifest_identity(body["command_id"]))).fetchone()
            manifest = subject.domain._load(db, EntityRef("run_manifest", manifest_identity(body["command_id"]), 1, row["sha256"]), roots)[0]
        assert manifest.body["content"]["inputs"]["consent_ref"] == consent["ref"]
        # a consent authorizes one specific execution: a second run under the spent consent is refused
        again = post(subject, run_command(subject, graph_ref, consent["ref"]))
        assert again.status_code == 409 and again.json()["code"] == "conflict"
        assert len(events(subject, "run.started")) == 1
        # a fresh consent over the same inputs starts a fresh run
        fresh = post(subject, run_command(subject, graph_ref, other_consent["ref"]))
        assert fresh.status_code == 201 and fresh.json()["run_id"] != started.json()["run_id"]


# --- revocation: the "current consent" verified before any further dispatch ---------------

REVOKE_SCHEMA = "run-consent-revocation-command-v1"


def revoke(subject, consent_id, command_id=None):
    return post(subject, {"schema_version": REVOKE_SCHEMA, "command_id": command_id or str(uuid4())},
                consent_path(subject) + f"/{consent_id}/revoke")


def test_a_revoked_consent_starts_no_run_and_the_revocation_is_its_own_fact(tmp_path):
    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        graph_ref = graph_record(subject, linear_graph())
        consent = post(subject, consent_command(subject, graph_ref), consent_path(subject)).json()
        command_id = str(uuid4())
        revoked = revoke(subject, consent["consent_id"], command_id)
        assert revoked.status_code == 200, revoked.text
        body = revoked.json()
        assert body["revocation"]["command_id"] == command_id
        assert {key: value for key, value in body.items() if key != "revocation"} == {
            key: value for key, value in consent.items() if key != "revocation"}
        decided = [item for item in events(subject, "approval.decided")
                   if item["public_metadata"]["decision"] == "revoked"]
        assert len(decided) == 1 and object_ref(consent["ref"]) in decided[0]["object_refs"]
        # replay is the same revocation; another command over a revoked consent conflicts
        assert revoke(subject, consent["consent_id"], command_id).json() == body
        assert revoke(subject, consent["consent_id"]).status_code == 409
        assert len([item for item in events(subject, "approval.decided")
                    if item["public_metadata"]["decision"] == "revoked"]) == 1
        # the read shows it; a revoked consent starts no run
        read = subject.client.get(consent_path(subject) + "/" + consent["consent_id"], headers=headers(subject.profile))
        assert read.json() == body
        refused = post(subject, run_command(subject, graph_ref, consent["ref"]))
        assert refused.status_code == 403 and refused.json()["code"] == "access_denied"
        assert events(subject, "run.started") == [] and executor.calls == []
        assert revoke(subject, str(uuid4())).status_code == 404


def test_a_run_under_a_revoked_consent_is_not_resumed_or_recovered_but_can_be_cancelled(tmp_path):
    from app.tests.test_runs_api import command as run_body
    from app.tests.test_runs_api import graph_value

    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        graph_ref = graph_record(subject, graph_value())
        body = run_body(subject, graph_ref)
        receipt = post(subject, body).json()
        assert receipt["phase"] == "awaiting_human"
        run_path = receipt["links"]["self"]
        approved = post(subject, {"command_id": str(uuid4()), "node_id": "owner-gate",
                                  "approval_scope": "release-output", "decision": "approved"}, run_path + "/approvals")
        assert approved.status_code == 201
        assert revoke(subject, body["consent_ref"]["id"]).status_code == 200
        for action in ("resume", "recover"):
            refused = post(subject, {"command_id": str(uuid4())}, f"{run_path}/{action}")
            assert refused.status_code == 403 and refused.json()["code"] == "access_denied", action
        # a replay of the sealed command dispatches too, so it is refused as well
        assert post(subject, body).status_code == 403
        assert executor.calls == ["intake", "writer"]
        cancelled = post(subject, {"command_id": str(uuid4())}, run_path + "/cancel")
        assert cancelled.status_code == 200, cancelled.text


def test_the_revocation_wire_is_exact(tmp_path):
    with owner_app(tmp_path, Executor()) as subject:
        graph_ref = graph_record(subject, linear_graph())
        consent = post(subject, consent_command(subject, graph_ref), consent_path(subject)).json()
        path = consent_path(subject) + f"/{consent['consent_id']}/revoke"
        for bad in ({}, {"schema_version": "x", "command_id": str(uuid4())},
                    {"schema_version": REVOKE_SCHEMA, "command_id": "nope"},
                    {"schema_version": REVOKE_SCHEMA, "command_id": str(uuid4()), "reason": "x"}):
            assert post(subject, bad, path).status_code == 400, bad
        assert post(subject, {"schema_version": REVOKE_SCHEMA, "command_id": str(uuid4())},
                    consent_path(subject) + "/not-a-uuid/revoke").status_code == 400
        assert subject.client.get(path, headers=headers(subject.profile)).status_code in {400, 405}
        subject.client.cookies.clear()
        assert revoke(subject, consent["consent_id"]).status_code in {401, 403}


# --- expiry: a v2 consent carries the owner's expiry and is not current past it ------------

def _stamp_in(seconds):
    from datetime import UTC, datetime, timedelta

    return (datetime.now(UTC) + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _advance_clock(monkeypatch, seconds):
    from datetime import UTC, datetime, timedelta

    import app.services.run_consents as module

    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz or UTC) + timedelta(seconds=seconds)

    monkeypatch.setattr(module, "datetime", Later)


def test_an_expired_consent_is_no_longer_current(tmp_path, monkeypatch):
    from app.tests.test_runs_api import graph_value

    executor = Executor()
    with owner_app(tmp_path, executor) as subject:
        path = consent_path(subject)
        graph_ref = graph_record(subject, graph_value())
        # the expiry must lie ahead, within the wire's 366-day bound, and is part of the replay
        for expires in (_stamp_in(-60), _stamp_in(367 * 24 * 3600), "tomorrow"):
            refused = post(subject, consent_command(subject, graph_ref, schema_version="run-consent-command-v2",
                                                    expires_at_utc=expires), path)
            assert refused.status_code == 400, expires
        assert post(subject, consent_command(subject, graph_ref, expires_at_utc=_stamp_in(3600)), path).status_code == 400
        body = consent_command(subject, graph_ref, schema_version="run-consent-command-v2", expires_at_utc=_stamp_in(3600))
        created = post(subject, body, path)
        assert created.status_code == 201, created.text
        consent = created.json()
        assert consent["expires_at_utc"] == body["expires_at_utc"]
        assert post(subject, {**body, "expires_at_utc": _stamp_in(7200)}, path).status_code == 409
        # within its window it starts the run
        run = run_command(subject, graph_ref, consent["ref"])
        receipt = post(subject, run).json()
        assert receipt["phase"] == "awaiting_human"
        run_path = receipt["links"]["self"]
        # past it, nothing further dispatches under it; cancel stays available
        _advance_clock(monkeypatch, 7200)
        for action in ("resume", "recover"):
            refused = post(subject, {"command_id": str(uuid4())}, f"{run_path}/{action}")
            assert refused.status_code == 403, action
        assert post(subject, run).status_code == 403
        assert executor.calls == ["intake", "writer"]
        # the expired consent still reads back, with its expiry; it is only no longer current
        read = subject.client.get(path + "/" + consent["consent_id"], headers=headers(subject.profile))
        assert read.status_code == 200 and read.json()["expires_at_utc"] == body["expires_at_utc"]
        assert post(subject, {"command_id": str(uuid4())}, run_path + "/cancel").status_code == 200
