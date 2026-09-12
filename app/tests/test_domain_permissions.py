"""Process-local authorization/projection tests; no user vault, credentials or network."""

from dataclasses import replace
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from app.domain.refs import EntityRef
from app.domain.schemas import Actor, ImmutableRecord
from app.domain.store import DomainStore
from app.storage import Store


STAMP = "2026-09-07T00:00:00.000000Z"


def api():
    if importlib.util.find_spec("app.domain.permissions") is None:
        pytest.fail("Missing purpose/authorization firewall")
    return importlib.import_module("app.domain.permissions")


def setup():
    module = api()
    vault = str(uuid4())
    time = [1000]
    session = object()
    human_actor = Actor(str(uuid4()), "human", "local_session")
    sessions = {session: human_actor}
    registered, verified = {}, set()
    host, gate = module.create_policy(vault,
        authenticate_session=lambda handle: sessions.get(handle),
        verify_registered=lambda value: registered.get(value.ref if type(value) is ImmutableRecord else value) == value,
        verify_projection=lambda value: value.digest in verified,
        clock=lambda: time[0])
    human = host.bind_human(session, expires_at=1500)
    runtime = host.bind_runtime(Actor(str(uuid4()), "provider", "model_output"),
                                purpose="operational", expires_at=1400)
    genesis = ImmutableRecord.genesis(vault_id=vault, created_at_utc=STAMP)
    roots = [ImmutableRecord.bootstrap(kind=kind, id=str(uuid4()), genesis_ref=genesis.ref,
                                      created_at_utc=STAMP)
             for kind in ("actor", "access_policy", "retention_policy")]
    return dict(m=module, host=host, gate=gate, human=human, runtime=runtime,
                vault=vault, time=time, session=session, sessions=sessions,
                registered=registered, verified=verified, roots=roots)


def persistent_setup(tmp_path, prior=None):
    module = api()
    if prior is None:
        legacy = Store(tmp_path / "vault")
        domain = DomainStore(legacy)
        domain_roots = domain.initialize_vault()
        vault = domain_roots.genesis.id
        time = [1000]
        registered, verified = {}, set()
        human_actor = Actor(str(uuid4()), "human", "local_session")
        runtime_actor = Actor(str(uuid4()), "provider", "model_output")
        roots = [domain.get(ref) for ref in
                 (domain_roots.actor, domain_roots.access_policy,
                  domain_roots.retention_policy)]
    else:
        vault, legacy, domain, time = (prior["vault"], prior["legacy"],
                                       prior["domain"], prior["time"])
        registered, verified = prior["registered"], prior["verified"]
        human_actor, runtime_actor = prior["human"].actor, prior["runtime"].actor
        roots = prior["roots"]
    session = object()
    sessions = {session: human_actor}
    host, gate = module.create_persistent_policy(
        domain, authenticate_session=lambda handle: sessions.get(handle),
        verify_projection=lambda value: value.digest in verified,
        clock=lambda: time[0],
    )
    human = host.bind_human(session, expires_at=1500)
    runtime = host.bind_runtime(runtime_actor, purpose="operational", expires_at=1400)
    return dict(m=module, host=host, gate=gate, human=human, runtime=runtime,
                vault=vault, legacy=legacy, domain=domain, time=time, session=session,
                sessions=sessions, registered=registered, verified=verified, roots=roots)


def resource(state, *, kind="work_model", purpose="operational", content=None,
             parents=(), episode_id=None, secret=False):
    actor, access, retention = state["roots"]
    item = ImmutableRecord.create(kind=kind, id=str(uuid4()), version=1, created_at_utc=STAMP,
        actor_ref=actor.ref, parent_refs=parents, purpose=purpose,
        access_policy_ref=access.ref, retention_policy_ref=retention.ref,
        content={} if content is None else content)
    state["registered"][item.ref] = item
    if "domain" in state:
        state["domain"].put(item)
    state["host"].register_record(item, episode_id=episode_id, secret=secret)
    return item


def grant(state, item, *, subject=None, action="read", purpose="operational", episode_id=None,
          expires_at=1300):
    ref = item.ref if type(item) is ImmutableRecord else item
    return state["host"].grant(state["human"], subject or state["runtime"], ref,
        action=action, purpose=purpose, expires_at=expires_at, episode_id=episode_id)


def read(state, item, grants=(), *, principal=None, purpose="operational", episode_id=None, loader=None):
    return state["gate"].read(principal or state["runtime"], item.ref if type(item) is ImmutableRecord else item,
        purpose=purpose, grants=grants, episode_id=episode_id,
        loader=loader or (lambda ref: b"authorized bytes"))


def test_default_deny_happens_before_any_loader_call():
    s = setup()
    item = resource(s)
    calls = []
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, loader=lambda ref: calls.append(ref))
    assert calls == []


def test_exact_action_purpose_and_reference_grant_allows_ordinary_work():
    s = setup()
    item = resource(s)
    g = grant(s, item)
    assert read(s, item, [g]) == b"authorized bytes"
    write_grant = grant(s, item, action="write")
    assert s["gate"].authorize(
        s["runtime"], item.ref, action="write", purpose="operational",
        grants=[write_grant]) is None
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [write_grant])


@pytest.mark.parametrize("forgery", ["actor", "dict", "copied_principal", "other_engine"])
def test_provenance_and_client_objects_cannot_mint_human_authority(forgery):
    s = setup()
    item = resource(s)
    actor = Actor(str(uuid4()), "human", "local_session")
    fake = {"actor": actor, "dict": dict(kind="human", origin="local_session"),
            "copied_principal": replace(s["human"]), "other_engine": setup()["human"]}[forgery]
    with pytest.raises(s["m"].AccessDenied):
        s["host"].grant(fake, s["runtime"], item.ref, action="read", purpose="operational", expires_at=1300)


def test_unknown_session_and_provider_or_test_actor_cannot_bind_as_human():
    s = setup()
    with pytest.raises(s["m"].AccessDenied):
        s["host"].bind_human(object(), expires_at=1300)
    for kind, origin in [("provider", "model_output"), ("test_actor", "test_fixture")]:
        handle = object()
        s["sessions"][handle] = Actor(str(uuid4()), kind, origin)
        with pytest.raises(s["m"].AccessDenied):
            s["host"].bind_human(handle, expires_at=1300)


def test_json_and_copied_grant_are_not_registered_grants():
    s = setup()
    item = resource(s)
    g = grant(s, item)
    for forged in [replace(g), {"id": g.id, "allowed": True}]:
        with pytest.raises(s["m"].AccessDenied):
            read(s, item, [forged])


def test_expiry_revocation_and_session_revocation_are_immediate():
    s = setup()
    item = resource(s)
    g = grant(s, item, expires_at=1001)
    s["time"][0] = 1001
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [g])
    s = setup()
    item = resource(s)
    g = grant(s, item)
    s["host"].revoke(g)
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [g])
    g = grant(s, item)
    del s["sessions"][s["session"]]
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [g])


def test_policy_revision_invalidates_old_grant_and_does_not_delete_content():
    s = setup()
    item = resource(s)
    g = grant(s, item)
    s["host"].set_available(item.ref, False)
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [g])
    s["host"].set_available(item.ref, True)
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [g])
    assert read(s, item, [grant(s, item)]) == b"authorized bytes"
    assert item.ref in s["registered"]


def test_runtime_purpose_cannot_be_widened_by_new_grant():
    s = setup()
    item = resource(s, purpose="diagnosis")
    with pytest.raises(s["m"].AccessDenied):
        grant(s, item, purpose="diagnosis")
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, purpose="diagnosis")


@pytest.mark.parametrize("position", ["parent", "nested"])
def test_nested_dependencies_need_their_own_grants_before_loader(position):
    s = setup()
    dependency = resource(s)
    item = resource(s, parents=[dependency.ref] if position == "parent" else [],
                    content={"nested": [{"source_ref": dependency.ref.as_dict()}]} if position == "nested" else {})
    g = grant(s, item)
    calls = []
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [g], loader=lambda ref: calls.append(ref))
    assert calls == []
    assert read(s, item, [g, grant(s, dependency)]) == b"authorized bytes"


def test_cross_vault_and_unregistered_descriptor_are_denied():
    s = setup()
    other = setup()
    foreign = resource(other)
    with pytest.raises(s["m"].AccessDenied):
        grant(s, foreign)
    wrong_hash = EntityRef(foreign.ref.kind, foreign.ref.id, 1, "0" * 64)
    with pytest.raises(s["m"].AccessDenied):
        s["gate"].authorize(s["runtime"], wrong_hash, action="read", purpose="operational", grants=[])
    with pytest.raises(s["m"].AccessDenied):
        s["host"].register_record(foreign)


def test_inquiry_requires_one_exact_episode_even_for_human():
    s = setup()
    episode = str(uuid4())
    item = resource(s, kind="inquiry_audit", purpose="inquiry_audit", episode_id=episode,
                    content={"H_phi": "PRIVATE_PHI_CANARY"})
    g = grant(s, item, subject=s["human"], purpose="inquiry_audit", episode_id=episode)
    assert read(s, item, [g], principal=s["human"], purpose="inquiry_audit", episode_id=episode) == b"authorized bytes"
    for wrong in [None, str(uuid4())]:
        with pytest.raises(s["m"].AccessDenied):
            read(s, item, [g], principal=s["human"], purpose="inquiry_audit", episode_id=wrong)


@pytest.mark.parametrize("kind,purpose,content", [
    ("own_alternative", "operational", {"classification": "ordinary", "text": "RAW_CANARY"}),
    ("inquiry_audit", "inquiry_audit", {"H_phi": "PHI_CANARY"}),
    ("work_model", "operational", {"deep": [{"S_phi": "PHI_CANARY"}]}),
    ("evaluation_dataset", "evaluation_sealed", {"truth": "HELDOUT_CANARY"}),
    ("work_model", "operational", {"api_key": "SYNTHETIC_SECRET_CANARY"}),
])
def test_sensitive_classification_cannot_be_laundered_by_operational_label(kind, purpose, content):
    s = setup()
    episode = str(uuid4()) if kind == "inquiry_audit" or "deep" in content else None
    sensitive = resource(s, kind=kind, purpose=purpose, content=content, episode_id=episode)
    derived = resource(s, parents=[sensitive.ref], content={"classification": "ordinary"}, episode_id=episode)
    with pytest.raises(s["m"].AccessDenied):
        grant(s, derived)


def test_byte_loader_result_is_discarded_if_grant_expires_during_load():
    s = setup()
    item = resource(s)
    g = grant(s, item, expires_at=1001)
    def expires(ref):
        s["time"][0] = 1001
        return b"must not deliver after expiry"
    with pytest.raises(s["m"].AccessDenied):
        read(s, item, [g], loader=expires)


def compiler_fixture():
    s = setup()
    s["compiler"] = s["host"].bind_runtime(Actor(str(uuid4()), "system", "host_service"),
                                            purpose="compiler", expires_at=1400)
    behavior = resource(s, kind="original_execution", content={"observed": "actual fixture behavior"})
    source = resource(s, kind="hypothesis", purpose="diagnosis", parents=[behavior.ref], content={
        "condition": "Repeated formatting review is redundant",
        "action": "Remove the duplicate formatting review step",
        "exception": "Keep required final human approval",
        "prediction": "Preserve accuracy while reducing repeated work",
        "private_metadata": {"raw_alternative": "RAW_CANARY", "self_score": "SCORE_CANARY"},
        "verified": True})
    projection = s["m"].CompilerProjection.create(source, target="graph_config", change_kind="restore",
        support_by_field={name: [behavior.ref] for name in ("condition", "action", "exception", "prediction")},
        expires_at=1250)
    return s, behavior, source, projection


def test_model_verified_label_does_not_approve_a_compiler_projection():
    s, _, source, projection = compiler_fixture()
    with pytest.raises(s["m"].AccessDenied):
        s["host"].register_projection(projection)
    with pytest.raises(s["m"].AccessDenied):
        grant(s, source, subject=s["compiler"], purpose="compiler", action="compile")


def test_verified_projection_preserves_ordinary_workflow_changes_and_excludes_private_fields():
    s, behavior, source, projection = compiler_fixture()
    s["verified"].add(projection.digest)
    s["host"].register_projection(projection)
    grants = [grant(s, source, subject=s["compiler"], purpose="compiler", action="compile"),
              grant(s, behavior, subject=s["compiler"], purpose="compiler", action="compile")]
    payload = s["gate"].compiler_input(s["compiler"], source.ref, grants=grants)
    assert payload["action"] == "Remove the duplicate formatting review step"
    assert set(payload) == {"schema_version", "target", "change_kind", "condition", "action",
                            "exception", "prediction", "support_by_field"}
    assert "CANARY" not in str(payload) and "private_metadata" not in str(payload)
    assert "verified" not in payload


def test_public_compiler_authorization_never_returns_record_bearing_descriptor():
    s, behavior, source, projection = compiler_fixture()
    s["verified"].add(projection.digest)
    s["host"].register_projection(projection)
    grants = [grant(s, source, subject=s["compiler"], purpose="compiler", action="compile"),
              grant(s, behavior, subject=s["compiler"], purpose="compiler", action="compile")]
    result = s["gate"].authorize(
        s["compiler"], source.ref, action="compile", purpose="compiler", grants=grants)
    assert result is None
    assert "RAW_CANARY" not in str(result) and "SCORE_CANARY" not in str(result)


def test_verified_digest_cannot_be_reused_for_substituted_projection_fields():
    s, _, source, projection = compiler_fixture()
    s["verified"].add(projection.digest)
    malicious = replace(
        projection, target="authority_policy",
        values=(("condition", "c"), ("action", "RAW_ALTERNATIVE_CANARY"),
                ("exception", "e"), ("prediction", "p")),
    )
    with pytest.raises(s["m"].AccessDenied, match="Invalid compiler projection"):
        s["host"].register_projection(malicious)
    assert source.ref not in s["host"]._projections


def test_compiler_projection_is_deeply_immutable_after_authorization():
    s, behavior, source, projection = compiler_fixture()
    s["verified"].add(projection.digest)
    s["host"].register_projection(projection)
    grants = [grant(s, source, subject=s["compiler"], purpose="compiler", action="compile"),
              grant(s, behavior, subject=s["compiler"], purpose="compiler", action="compile")]
    payload = s["gate"].compiler_input(s["compiler"], source.ref, grants=grants)
    with pytest.raises(TypeError):
        payload["support_by_field"]["action"] += ({"kind": "artifact"},)
    with pytest.raises(TypeError):
        payload["support_by_field"]["action"][0]["sha256"] = "0" * 64


@pytest.mark.parametrize("target", ["authority_policy", "constitution", "final_human_approval", "current_test_requirements"])
def test_compiler_rejects_protected_policy_targets(target):
    s, behavior, source, _ = compiler_fixture()
    with pytest.raises(ValueError):
        s["m"].CompilerProjection.create(source, target=target, change_kind="learn",
            support_by_field={name: [behavior.ref] for name in ("condition", "action", "exception", "prediction")},
            expires_at=1250)


def test_derived_sensitive_evidence_cannot_pass_even_with_trusted_projection_receipt():
    s, behavior, source, projection = compiler_fixture()
    secret = resource(s, content={"text": "HIDDEN_SECRET"}, secret=True)
    tainted = resource(s, kind="original_execution", parents=[secret.ref])
    candidate = s["m"].CompilerProjection.create(source, target="graph_config", change_kind="restore",
        support_by_field={name: [tainted.ref] for name in ("condition", "action", "exception", "prediction")},
        expires_at=1250)
    s["verified"].add(candidate.digest)
    with pytest.raises(s["m"].AccessDenied):
        s["host"].register_projection(candidate)


def test_source_withdrawal_invalidates_projection_and_downstream_grants():
    s, behavior, source, projection = compiler_fixture()
    s["verified"].add(projection.digest)
    s["host"].register_projection(projection)
    grants = [grant(s, source, subject=s["compiler"], purpose="compiler", action="compile"),
              grant(s, behavior, subject=s["compiler"], purpose="compiler", action="compile")]
    s["host"].set_available(behavior.ref, False)
    with pytest.raises(s["m"].AccessDenied):
        s["gate"].compiler_input(s["compiler"], source.ref, grants=grants)


@pytest.mark.parametrize("expiry", [True, 1000, 999, 1000.5, 2 ** 63])
def test_invalid_or_unbounded_expiry_is_rejected(expiry):
    s = setup()
    with pytest.raises(ValueError):
        s["host"].bind_human(s["session"], expires_at=expiry)


def test_persistent_policy_uses_hashed_additive_component_schema(tmp_path):
    s = persistent_setup(tmp_path)
    assert s["host"]._storage.domain_store is s["domain"]
    assert s["host"]._storage.path == s["domain"].path == s["legacy"].path
    with sqlite3.connect(s["legacy"].path) as db:
        row = db.execute("SELECT sha256 FROM permission_migrations "
                         "WHERE component='policy' AND version=1").fetchone()
        tables = {item[0] for item in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'permission_%'")}
    assert row == (s["m"].PERMISSION_MIGRATION_SHA256,)
    assert tables == {"permission_migrations", "permission_control",
                      "permission_descriptors", "permission_grants",
                      "permission_projections"}
    with sqlite3.connect(s["legacy"].path) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(permission_descriptors)")}
        control_columns = {
            row[1] for row in db.execute("PRAGMA table_info(permission_control)")}
    assert "record" not in columns
    assert control_columns == {
        "singleton", "vault_id", "policy_revision", "last_observed", "row_digest"}


def test_transaction_authorization_uses_only_callers_exact_domain_connection(
        tmp_path, monkeypatch):
    s = persistent_setup(tmp_path)
    item = resource(s)
    issued = grant(s, item)
    s["time"][0] = 1001

    with s["domain"]._connection(write=True) as db:
        def nested_connection(**_kwargs):
            raise AssertionError("authorization opened a nested database connection")
        monkeypatch.setattr(s["domain"], "_connection", nested_connection)
        assert s["gate"]._authorize_in_transaction(
            db, s["runtime"], item.ref, action="read", purpose="operational",
            grants=(issued,)) is None
        assert db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1").fetchone()[0] == 1001


def test_transaction_authorization_rejects_nonpersistent_or_foreign_connection(tmp_path):
    local = setup()
    persistent = persistent_setup(tmp_path)
    item = resource(persistent)
    issued = grant(persistent, item)
    with persistent["domain"]._connection(write=True) as db:
        with pytest.raises(local["m"].AccessDenied, match="Persistent permission"):
            local["gate"]._authorize_in_transaction(
                db, local["runtime"], item.ref, action="read", purpose="operational",
                grants=())

    foreign_path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(foreign_path, isolation_level=None) as foreign:
        foreign.row_factory = sqlite3.Row
        foreign.execute("BEGIN IMMEDIATE")
        with pytest.raises(persistent["m"].AccessDenied, match="DomainStore transaction"):
            persistent["gate"]._authorize_in_transaction(
                foreign, persistent["runtime"], item.ref, action="read",
                purpose="operational", grants=(issued,))


def test_outer_rollback_can_persist_clock_floor_without_business_effects(tmp_path):
    s = persistent_setup(tmp_path)
    item = resource(s)
    issued = grant(s, item)
    s["time"][0] = 1100
    with pytest.raises(RuntimeError, match="outer rollback"):
        with s["domain"]._connection(write=True) as db:
            s["gate"]._authorize_in_transaction(
                db, s["runtime"], item.ref, action="read", purpose="operational",
                grants=(issued,))
            assert db.execute(
                "SELECT last_observed FROM permission_control WHERE singleton=1").fetchone()[0] == 1100
            raise RuntimeError("outer rollback")
    with sqlite3.connect(s["legacy"].path) as db:
        assert db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1").fetchone()[0] == 1000
    assert s["host"]._persist_clock_watermark() is None
    with sqlite3.connect(s["legacy"].path) as db:
        assert db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1").fetchone()[0] == 1100
    s["time"][0] = 1099
    with pytest.raises(s["m"].AccessDenied, match="clock moved backwards"):
        s["host"]._persist_clock_watermark()
    with s["domain"]._connection(write=True) as db:
        with pytest.raises(s["m"].AccessDenied, match="clock moved backwards"):
            s["gate"]._authorize_in_transaction(
                db, s["runtime"], item.ref, action="read", purpose="operational",
                grants=(issued,))
    with pytest.raises(s["m"].AccessDenied, match="clock moved backwards"):
        persistent_setup(tmp_path, s)


def test_persistent_descriptor_resolves_canonical_domain_record_without_second_copy(tmp_path):
    module = api()
    legacy = Store(tmp_path / "vault")
    domain = DomainStore(legacy)
    roots = domain.initialize_vault()
    human_actor = Actor(str(uuid4()), "human", "local_session")
    runtime_actor = Actor(str(uuid4()), "provider", "model_output")
    session = object()
    sessions = {session: human_actor}

    host, gate = module.create_persistent_policy(
        domain, authenticate_session=lambda handle: sessions.get(handle),
        verify_projection=lambda value: False, clock=lambda: 1000)
    human = host.bind_human(session, expires_at=1500)
    runtime = host.bind_runtime(runtime_actor, purpose="operational", expires_at=1400)
    item = ImmutableRecord.create(
        kind="work_model", id=str(uuid4()), version=1, created_at_utc=STAMP,
        actor_ref=roots.actor, parent_refs=[], purpose="operational",
        access_policy_ref=roots.access_policy, retention_policy_ref=roots.retention_policy,
        content={"goal": "canonical record"})
    domain.put(item)
    host.register_record(item)
    issued = host.grant(human, runtime, item.ref, action="read", purpose="operational",
                        expires_at=1300)
    assert gate.read(runtime, item.ref, purpose="operational", grants=[issued],
                     loader=lambda ref: domain.get(ref).body_bytes) == item.body_bytes
    with sqlite3.connect(legacy.path) as db:
        db.execute("UPDATE domain_records SET body=? WHERE vault_id=? AND kind=? AND id=? "
                   "AND version=?", (b"{}", roots.genesis.id, item.ref.kind, item.ref.id,
                                     item.ref.version))
    with pytest.raises(module.CorruptPolicy):
        module.create_persistent_policy(
            domain,
            authenticate_session=lambda handle: sessions.get(handle),
            verify_projection=lambda value: False, clock=lambda: 1000)


def test_compiler_projection_rejects_hypothesis_as_its_own_behavior_evidence():
    s, _, source, _ = compiler_fixture()
    with pytest.raises(ValueError, match="behavioral evidence"):
        s["m"].CompilerProjection.create(
            source, target="graph_config", change_kind="learn",
            support_by_field={name: [source.ref]
                              for name in ("condition", "action", "exception", "prediction")},
            expires_at=1250)


@pytest.mark.parametrize("kind", [
    "lens_definition", "lens_composition", "design_decision", "work_model",
])
def test_compiler_support_is_a_narrow_observed_behavior_allowlist(kind):
    s = setup()
    candidate = resource(s, kind=kind, purpose="diagnosis", content={"claim": "audit only"})
    source = resource(s, kind="hypothesis", purpose="diagnosis", parents=[candidate.ref],
                      content={"condition": "c", "action": "a", "exception": "e",
                               "prediction": "p"})
    with pytest.raises(ValueError, match="behavioral evidence"):
        s["m"].CompilerProjection.create(
            source, target="graph_config", change_kind="learn",
            support_by_field={name: [candidate.ref]
                              for name in ("condition", "action", "exception", "prediction")},
            expires_at=1250)


def test_restart_requires_explicit_reauthentication_and_grant_claim(tmp_path):
    first = persistent_setup(tmp_path)
    item = resource(first)
    issued = grant(first, item)
    second = persistent_setup(tmp_path, first)
    with pytest.raises(second["m"].AccessDenied):
        read(second, item, [issued])
    claimed = second["host"].claim_grant(issued.id, second["human"], second["runtime"])
    assert claimed.id == issued.id
    assert read(second, item, [claimed]) == b"authorized bytes"
    with pytest.raises(second["m"].AccessDenied):
        second["host"].claim_grant(issued.id, first["human"], second["runtime"])


def test_persistent_revocation_expiry_and_stale_session_fail_after_restart(tmp_path):
    first = persistent_setup(tmp_path)
    item = resource(first)
    revoked = grant(first, item)
    first["host"].revoke(revoked)
    second = persistent_setup(tmp_path, first)
    with pytest.raises(second["m"].AccessDenied):
        second["host"].claim_grant(revoked.id, second["human"], second["runtime"])

    live = grant(second, item, expires_at=1001)
    third = persistent_setup(tmp_path, second)
    claimed = third["host"].claim_grant(live.id, third["human"], third["runtime"])
    del third["sessions"][third["session"]]
    with pytest.raises(third["m"].AccessDenied):
        read(third, item, [claimed])
    third["time"][0] = 1001
    fourth = persistent_setup(tmp_path, third)
    with pytest.raises(fourth["m"].AccessDenied):
        fourth["host"].claim_grant(live.id, fourth["human"], fourth["runtime"])


def test_persistent_clock_rollback_cannot_resurrect_expired_grant(tmp_path):
    first = persistent_setup(tmp_path)
    item = resource(first)
    issued = grant(first, item, expires_at=1100)
    first["time"][0] = 1200
    expired = persistent_setup(tmp_path, first)
    with pytest.raises(expired["m"].AccessDenied):
        expired["host"].claim_grant(issued.id, expired["human"], expired["runtime"])
    first["time"][0] = 1000
    with pytest.raises(first["m"].AccessDenied, match="clock moved backwards"):
        persistent_setup(tmp_path, first)


def test_persistent_vault_binding_and_cross_vault_refs_fail_closed(tmp_path):
    first = persistent_setup(tmp_path)
    with pytest.raises(TypeError, match="DomainStore"):
        first["m"].create_persistent_policy(
            first["legacy"], authenticate_session=lambda value: None,
            verify_projection=lambda value: True, clock=lambda: 1000)
    with pytest.raises(TypeError):
        first["m"].create_policy(
            first["vault"], authenticate_session=lambda value: None,
            verify_registered=lambda value: True, verify_projection=lambda value: True,
            clock=lambda: 1000, legacy_store=first["legacy"],
            resolve_registered=first["domain"].get)
    foreign = persistent_setup(tmp_path / "foreign")
    item = resource(foreign)
    with pytest.raises(first["m"].AccessDenied):
        first["host"].register_record(item)


def test_episode_and_purpose_bindings_survive_restart(tmp_path):
    first = persistent_setup(tmp_path)
    episode = str(uuid4())
    item = resource(first, kind="inquiry_audit", purpose="inquiry_audit",
                    episode_id=episode, content={"H_phi": "PRIVATE"})
    issued = grant(first, item, subject=first["human"], purpose="inquiry_audit",
                   episode_id=episode)
    second = persistent_setup(tmp_path, first)
    claimed = second["host"].claim_grant(issued.id, second["human"], second["human"])
    assert read(second, item, [claimed], principal=second["human"],
                purpose="inquiry_audit", episode_id=episode) == b"authorized bytes"
    for wrong_purpose, wrong_episode in [("operational", episode),
                                         ("inquiry_audit", str(uuid4())),
                                         ("inquiry_audit", None)]:
        with pytest.raises(second["m"].AccessDenied):
            read(second, item, [claimed], principal=second["human"],
                 purpose=wrong_purpose, episode_id=wrong_episode)


def test_concurrent_persistent_registration_preserves_both_descriptors(tmp_path):
    first = persistent_setup(tmp_path)
    left = persistent_setup(tmp_path, first)
    right = persistent_setup(tmp_path, first)
    items = []
    for _ in range(2):
        actor, access, retention = first["roots"]
        item = ImmutableRecord.create(
            kind="work_model", id=str(uuid4()), version=1, created_at_utc=STAMP,
            actor_ref=actor.ref, parent_refs=[], purpose="operational",
            access_policy_ref=access.ref, retention_policy_ref=retention.ref, content={})
        first["registered"][item.ref] = item
        first["domain"].put(item)
        items.append(item)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda pair: pair[0]["host"].register_record(pair[1]),
                                [(left, items[0]), (right, items[1])]))
    assert {value.ref for value in results} == {item.ref for item in items}
    reopened = persistent_setup(tmp_path, first)
    grants = [grant(reopened, item) for item in items]
    for item, issued in zip(items, grants):
        assert read(reopened, item, [issued]) == b"authorized bytes"


def test_peer_policy_change_invalidates_previously_issued_grant(tmp_path):
    first = persistent_setup(tmp_path)
    item = resource(first)
    issued = grant(first, item)
    peer = persistent_setup(tmp_path, first)
    peer["host"].set_available(item.ref, False)
    with pytest.raises(first["m"].AccessDenied):
        read(first, item, [issued])


def test_cross_table_trigger_cannot_reset_generation_and_resurrect_stale_grant(tmp_path):
    first = persistent_setup(tmp_path)
    item = resource(first)
    issued = grant(first, item)
    first["host"].set_available(item.ref, False)
    first["host"].set_available(item.ref, True)
    with pytest.raises(first["m"].AccessDenied):
        read(first, item, [issued])
    with sqlite3.connect(first["legacy"].path) as db:
        db.execute(
            "CREATE TRIGGER stealth_policy_reset AFTER INSERT ON events "
            "BEGIN UPDATE PERMISSION_CONTROL SET policy_revision=1; END")
    first["legacy"].create_work("fire cross-table trigger")
    with pytest.raises(first["m"].CorruptPolicy, match="permission schema object"):
        read(first, item, [issued])


def test_in_process_revision_floor_rejects_self_consistent_control_rollback(tmp_path):
    first = persistent_setup(tmp_path)
    item = resource(first)
    issued = grant(first, item)
    first["host"].set_available(item.ref, False)
    first["host"].set_available(item.ref, True)
    with sqlite3.connect(first["legacy"].path) as db:
        last = db.execute(
            "SELECT last_observed FROM permission_control WHERE singleton=1").fetchone()[0]
        digest = first["m"]._row_digest(
            first["m"]._control_semantics(first["vault"], 1, last))
        db.execute("UPDATE permission_control SET policy_revision=1,row_digest=?",
                   (digest,))
    with pytest.raises(first["m"].CorruptPolicy, match="revision moved backwards"):
        read(first, item, [issued])


def test_failed_descriptor_write_is_atomic_and_restart_has_no_partial_row(tmp_path, monkeypatch):
    first = persistent_setup(tmp_path)
    actor, access, retention = first["roots"]
    item = ImmutableRecord.create(
        kind="work_model", id=str(uuid4()), version=1, created_at_utc=STAMP,
        actor_ref=actor.ref, parent_refs=[], purpose="operational",
        access_policy_ref=access.ref, retention_policy_ref=retention.ref, content={})
    first["registered"][item.ref] = item
    first["domain"].put(item)
    original_insert = first["host"]._storage.insert_descriptor
    def crash_after_insert(db, descriptor):
        original_insert(db, descriptor)
        raise RuntimeError("simulated process failure before commit")
    monkeypatch.setattr(first["host"]._storage, "insert_descriptor", crash_after_insert)
    with sqlite3.connect(first["legacy"].path) as db:
        before = db.execute("SELECT policy_revision FROM permission_control").fetchone()[0]
    with pytest.raises(RuntimeError, match="simulated process failure"):
        first["host"].register_record(item)
    with sqlite3.connect(first["legacy"].path) as db:
        assert db.execute("SELECT COUNT(*) FROM permission_descriptors WHERE id=?",
                          (item.ref.id,)).fetchone()[0] == 0
        assert db.execute("SELECT policy_revision FROM permission_control").fetchone()[0] == before
    monkeypatch.setattr(first["host"]._storage, "insert_descriptor", original_insert)
    reopened = persistent_setup(tmp_path, first)
    assert reopened["host"].register_record(item).ref == item.ref


@pytest.mark.parametrize("target,mutation", [
    ("migration", "UPDATE permission_migrations SET sha256='0000000000000000000000000000000000000000000000000000000000000000' WHERE component='policy'"),
    ("schema", "CREATE TRIGGER injected_permission_trigger BEFORE UPDATE ON permission_control BEGIN SELECT RAISE(ABORT,'fixture'); END"),
    ("control", "UPDATE permission_control SET policy_revision=2"),
    ("descriptor", "UPDATE permission_descriptors SET purpose='diagnosis'"),
    ("grant", "UPDATE permission_grants SET action='write'"),
])
def test_persistent_permission_tampering_is_detected_on_restart(tmp_path, target, mutation):
    first = persistent_setup(tmp_path)
    if target in ("descriptor", "grant"):
        item = resource(first)
        if target == "grant":
            grant(first, item)
    with sqlite3.connect(first["legacy"].path) as db:
        db.execute(mutation)
    with pytest.raises(first["m"].CorruptPolicy):
        persistent_setup(tmp_path, first)


def persistent_compiler_fixture(tmp_path):
    s = persistent_setup(tmp_path)
    s["compiler"] = s["host"].bind_runtime(
        Actor(str(uuid4()), "system", "host_service"), purpose="compiler", expires_at=1400)
    behavior = resource(s, kind="original_execution", content={"observed": "actual"})
    source = resource(s, kind="hypothesis", purpose="diagnosis", parents=[behavior.ref], content={
        "condition": "Repeated review", "action": "Remove duplicate review",
        "exception": "Keep human approval", "prediction": "Preserve accuracy",
        "private_metadata": {"raw_alternative": "RAW_CANARY"},
    })
    projection = s["m"].CompilerProjection.create(
        source, target="graph_config", change_kind="restore",
        support_by_field={name: [behavior.ref]
                          for name in ("condition", "action", "exception", "prediction")},
        expires_at=1250)
    s["verified"].add(projection.digest)
    s["host"].register_projection(projection)
    grants = [grant(s, source, subject=s["compiler"], purpose="compiler", action="compile"),
              grant(s, behavior, subject=s["compiler"], purpose="compiler", action="compile")]
    return s, behavior, source, projection, grants


def test_projection_registration_crash_rolls_back_projection_and_policy_revision(tmp_path, monkeypatch):
    s = persistent_setup(tmp_path)
    compiler = s["host"].bind_runtime(
        Actor(str(uuid4()), "system", "host_service"), purpose="compiler", expires_at=1400)
    behavior = resource(s, kind="original_execution", content={"observed": "actual"})
    source = resource(s, kind="hypothesis", purpose="diagnosis", parents=[behavior.ref], content={
        "condition": "condition", "action": "action", "exception": "exception",
        "prediction": "prediction",
    })
    projection = s["m"].CompilerProjection.create(
        source, target="graph_config", change_kind="restore",
        support_by_field={name: [behavior.ref]
                          for name in ("condition", "action", "exception", "prediction")},
        expires_at=1250)
    s["verified"].add(projection.digest)
    original_insert = s["host"]._storage.insert_projection
    def crash_after_insert(db, value, revision):
        original_insert(db, value, revision)
        raise RuntimeError("projection crash before commit")
    monkeypatch.setattr(s["host"]._storage, "insert_projection", crash_after_insert)
    with sqlite3.connect(s["legacy"].path) as db:
        before = db.execute("SELECT policy_revision FROM permission_control").fetchone()[0]
    with pytest.raises(RuntimeError, match="projection crash"):
        s["host"].register_projection(projection)
    with sqlite3.connect(s["legacy"].path) as db:
        assert db.execute("SELECT COUNT(*) FROM permission_projections").fetchone()[0] == 0
        assert db.execute("SELECT policy_revision FROM permission_control").fetchone()[0] == before
    monkeypatch.setattr(s["host"]._storage, "insert_projection", original_insert)
    assert s["host"].register_projection(projection) == projection.digest
    assert compiler.purpose == "compiler"


def test_substituted_projection_is_rejected_before_persistent_mutation(tmp_path):
    s = persistent_setup(tmp_path)
    behavior = resource(s, kind="original_execution", content={"observed": "actual"})
    source = resource(s, kind="hypothesis", purpose="diagnosis", parents=[behavior.ref],
                      content={"condition": "c", "action": "a", "exception": "e",
                               "prediction": "p"})
    projection = s["m"].CompilerProjection.create(
        source, target="graph_config", change_kind="learn",
        support_by_field={name: [behavior.ref]
                          for name in ("condition", "action", "exception", "prediction")},
        expires_at=1250)
    s["verified"].add(projection.digest)
    malicious = replace(projection, expires_at=1399)
    with sqlite3.connect(s["legacy"].path) as db:
        before = db.execute(
            "SELECT policy_revision FROM permission_control WHERE singleton=1").fetchone()[0]
    with pytest.raises(s["m"].AccessDenied, match="Invalid compiler projection"):
        s["host"].register_projection(malicious)
    with sqlite3.connect(s["legacy"].path) as db:
        assert db.execute("SELECT COUNT(*) FROM permission_projections").fetchone()[0] == 0
        assert db.execute(
            "SELECT policy_revision FROM permission_control WHERE singleton=1").fetchone()[0] == before
    reopened = persistent_setup(tmp_path, s)
    assert source.ref in reopened["host"]._resources


def test_grant_registration_crash_never_leaves_replayable_authority(tmp_path, monkeypatch):
    s = persistent_setup(tmp_path)
    item = resource(s)
    original_insert = s["host"]._storage.insert_grant
    def crash_after_insert(db, *args):
        original_insert(db, *args)
        raise RuntimeError("grant crash before commit")
    monkeypatch.setattr(s["host"]._storage, "insert_grant", crash_after_insert)
    with pytest.raises(RuntimeError, match="grant crash"):
        grant(s, item)
    with sqlite3.connect(s["legacy"].path) as db:
        assert db.execute("SELECT COUNT(*) FROM permission_grants").fetchone()[0] == 0
    monkeypatch.setattr(s["host"]._storage, "insert_grant", original_insert)
    issued = grant(s, item)
    assert read(s, item, [issued]) == b"authorized bytes"


def test_projection_persists_but_requires_explicit_compiler_grant_claim(tmp_path):
    first, behavior, source, projection, grants = persistent_compiler_fixture(tmp_path)
    second = persistent_setup(tmp_path, first)
    compiler = second["host"].bind_runtime(
        first["compiler"].actor, purpose="compiler", expires_at=1400)
    claimed = [second["host"].claim_grant(item.id, second["human"], compiler)
               for item in grants]
    payload = second["gate"].compiler_input(compiler, source.ref, grants=claimed)
    assert payload["action"] == "Remove duplicate review"
    assert "CANARY" not in str(payload)


def test_projection_withdrawal_is_durable_and_invalidates_grant_replay(tmp_path):
    first, _, source, _, grants = persistent_compiler_fixture(tmp_path)
    first["host"].withdraw_projection(source.ref)
    with pytest.raises(first["m"].AccessDenied):
        first["gate"].compiler_input(first["compiler"], source.ref, grants=grants)
    second = persistent_setup(tmp_path, first)
    compiler = second["host"].bind_runtime(
        first["compiler"].actor, purpose="compiler", expires_at=1400)
    with pytest.raises(second["m"].AccessDenied):
        second["host"].claim_grant(grants[0].id, second["human"], compiler)
    with pytest.raises(second["m"].AccessDenied):
        second["gate"].compiler_input(compiler, source.ref, grants=[])


def test_transitive_taint_is_recomputed_after_restart(tmp_path):
    first = persistent_setup(tmp_path)
    secret = resource(first, content={"text": "hidden"}, secret=True)
    derived = resource(first, parents=[secret.ref], content={"classification": "ordinary"})
    second = persistent_setup(tmp_path, first)
    with pytest.raises(second["m"].AccessDenied):
        grant(second, derived)


def test_projection_row_tampering_is_detected_on_restart(tmp_path):
    first, _, _, _, _ = persistent_compiler_fixture(tmp_path)
    with sqlite3.connect(first["legacy"].path) as db:
        db.execute("UPDATE permission_projections SET state='withdrawn'")
    with pytest.raises(first["m"].CorruptPolicy):
        persistent_setup(tmp_path, first)
