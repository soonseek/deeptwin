"""Offline saver contract: real graphs and the existing SQLite runtime ledger."""
import importlib
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Annotated, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph

from app.domain.store import DomainStore
from app.storage import Store
from app.tests.test_runtime_ledger import identifier, opened, run_spec


class State(TypedDict):
    results: Annotated[dict, lambda left, right: left | right]
    counters: Annotated[dict, lambda left, right: left | right]


def setup(tmp_path):
    module = importlib.import_module("app.runtime.checkpoints")
    subject = opened(tmp_path)
    run = run_spec(subject)
    subject.ledger.create_run(identifier(), run)
    return module, subject, run


def saver(module, subject, run, **kwargs):
    return module.LedgerCheckpointSaver(subject.ledger, run.run_id,
        graph_digest="a" * 64, authority_digest="b" * 64,
        node_ids=("first", "second", "sibling", "failing"), **kwargs)


def config(run, checkpoint_id=None):
    value = {"thread_id": run.run_id, "checkpoint_ns": ""}
    if checkpoint_id is not None:
        value["checkpoint_id"] = checkpoint_id
    return {"configurable": value}


def reopen(subject, tmp_path):
    # Store/DomainStore/RuntimeLedger keep no open connection between operations.
    subject.legacy = Store(tmp_path / "vault")
    subject.domain = DomainStore(subject.legacy)
    subject.ledger = subject.module.RuntimeLedger(subject.domain, clock_ms=lambda: 1000)
    subject.ledger.reconcile_startup(identifier(), observed_owners={})


def checkpoint():
    from langgraph.checkpoint.base import empty_checkpoint
    return {"v": 4, "id": empty_checkpoint()["id"], "ts": "2026-09-15T00:00:00.000000+00:00",
            "channel_values": {"results": {}, "counters": {}},
            "channel_versions": {"results": 1, "counters": 1},
            "versions_seen": {}, "updated_channels": ["results", "counters"]}


def put(subject, run, value=None, parent=None):
    cp = checkpoint() if value is None else value
    return subject.put(config(run, parent), cp,
                       {"source": "input", "step": -1, "parents": {}},
                       cp["channel_versions"] if parent is None else {})


def test_sequential_graph_reopens_exact_refs_and_parent_history(tmp_path):
    module, subject, run = setup(tmp_path)
    seen = []
    ids = [identifier(), identifier()]
    def first(state):
        seen.append("first")
        return {"results": {ids[0]: subject.refs.result}, "counters": {"first": 1}}
    def second(state):
        assert state["results"][ids[0]] == subject.refs.result
        seen.append("second")
        return {"results": {ids[1]: subject.refs.manifest}, "counters": {"second": 1}}
    builder = (StateGraph(State).add_node("first", first).add_node("second", second)
               .add_edge(START, "first").add_edge("first", "second").add_edge("second", END))
    saved = saver(module, subject, run)
    builder.compile(checkpointer=saved, interrupt_before=["second"]).invoke(
        {"results": {}, "counters": {}}, config(run), durability="sync")
    assert seen == ["first"]
    before = list(saved.list(config(run), limit=10))
    reopen(subject, tmp_path)
    restored = saver(module, subject, run)
    assert list(restored.list(config(run), limit=10)) == before
    result = builder.compile(checkpointer=restored).invoke(None, config(run), durability="sync")
    assert seen == ["first", "second"]
    assert result == {"results": {ids[0]: subject.refs.result, ids[1]: subject.refs.manifest},
                      "counters": {"first": 1, "second": 1}}
    history = list(restored.list(config(run), limit=10))
    assert len(history) == 4
    assert history[0].parent_config == history[1].config
    history[0].checkpoint["channel_values"]["counters"]["first"] = 999
    assert restored.get_tuple(config(run)).checkpoint["channel_values"]["counters"]["first"] == 1


def test_parallel_failure_preserves_completed_sibling_pending_writes(tmp_path):
    module, subject, run = setup(tmp_path)
    calls = {"sibling": 0, "failing": 0}
    execution = identifier()
    def sibling(state):
        calls["sibling"] += 1
        return {"results": {execution: subject.refs.result}, "counters": {"sibling": 1}}
    def failing(state):
        calls["failing"] += 1
        if calls["failing"] == 1:
            raise RuntimeError("PRIVATE_ERROR_CANARY")
        return {"counters": {"failing": 1}}
    builder = (StateGraph(State).add_node("sibling", sibling).add_node("failing", failing)
               .add_edge(START, "sibling").add_edge(START, "failing")
               .add_edge("sibling", END).add_edge("failing", END))
    saved = saver(module, subject, run)
    with pytest.raises(RuntimeError, match="PRIVATE_ERROR_CANARY"):
        builder.compile(checkpointer=saved).invoke({"results": {}, "counters": {}},
            {**config(run), "metadata": {"secret": "PRIVATE_CONFIG_CANARY"}}, durability="sync")
    pending = saved.get_tuple(config(run)).pending_writes
    assert any(channel == "results" and value == {execution: subject.refs.result}
               for _, channel, value in pending)
    reopen(subject, tmp_path)
    restored = saver(module, subject, run)
    assert restored.get_tuple(config(run)).pending_writes == pending
    result = builder.compile(checkpointer=restored).invoke(None, config(run), durability="sync")
    assert calls == {"sibling": 1, "failing": 2}
    assert result["results"] == {execution: subject.refs.result}
    with sqlite3.connect(subject.legacy.path) as db:
        cursors = b"".join(row[0] for row in db.execute("SELECT cursor FROM runtime_checkpoints"))
    assert b"PRIVATE_ERROR_CANARY" not in cursors
    assert b"PRIVATE_CONFIG_CANARY" not in cursors
    events = str(subject.ledger.events(after_sequence=0, limit=1000))
    assert execution not in events and "CANARY" not in events


def test_duplicate_ids_write_identity_and_reserved_error_replacement(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cp = checkpoint()
    cfg = put(saved, run, cp)
    with pytest.raises(module.CheckpointError):
        put(saved, run, cp)
    task = identifier()
    saved.put_writes(cfg, [("counters", {"first": 1})], task)
    saved.put_writes(cfg, [("counters", {"first": 1})], task)
    with pytest.raises(module.CheckpointError):
        saved.put_writes(cfg, [("counters", {"first": 2})], task)
    saved.put_writes(cfg, [("__error__", RuntimeError("SECRET"))], task)
    saved.put_writes(cfg, [("__error__", ValueError("OTHER"))], task)
    assert saved.get_tuple(cfg).pending_writes == [(task, "counters", {"first": 1}),
                                                 (task, "__error__", "node_failed")]


def test_foreign_writer_halts_stale_saver_and_session_replay(tmp_path):
    module, subject, run = setup(tmp_path)
    first, second = saver(module, subject, run), saver(module, subject, run)
    put(first, run)
    with pytest.raises(module.CheckpointError):
        put(second, run)
    with pytest.raises(module.CheckpointError):
        second.get_tuple(config(run))
    reopen(subject, tmp_path)
    with pytest.raises(module.CheckpointError):
        first.get_tuple(config(run))


@pytest.mark.parametrize("channel,value", [("messages", []), ("counters", {"first": True}),
    ("counters", {"first": -1}), ("results", {"bad": "PRIVATE_STATE_CANARY"}),
    ("__start__", {"secret": "PRIVATE_STATE_CANARY"}), ("branch:to:unknown", None),
    ("__interrupt__", ["approve"]), ("__resume__", True), ("__scheduled__", True)])
def test_unsupported_channels_and_values_do_not_commit(tmp_path, channel, value):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cfg = put(saved, run)
    head = subject.ledger.read_checkpoint(run.run_id, "langgraph-v1")["revision"]
    with pytest.raises(module.CheckpointError):
        saved.put_writes(cfg, [(channel, value)], identifier())
    assert subject.ledger.read_checkpoint(run.run_id, "langgraph-v1")["revision"] == head


def test_wrong_bindings_config_and_unreconciled_session(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    put(saved, run)
    for field in ("graph_digest", "authority_digest"):
        values = {"graph_digest": "a" * 64, "authority_digest": "b" * 64}
        values[field] = "c" * 64
        with pytest.raises(module.CheckpointError):
            module.LedgerCheckpointSaver(subject.ledger, run.run_id, **values,
                node_ids=("first", "second", "sibling", "failing"))
    for bad in ({"thread_id": identifier()}, {"thread_id": run.run_id, "checkpoint_ns": "child"}):
        with pytest.raises(module.CheckpointError):
            saved.get_tuple({"configurable": bad})
    subject.ledger = subject.module.RuntimeLedger(subject.domain, clock_ms=lambda: 1000)
    with pytest.raises(module.CheckpointError):
        saver(module, subject, run)


@pytest.mark.parametrize("damage", ["missing", "digest", "grammar", "environment", "manifest", "parent"])
def test_recovery_rejects_damaged_committed_prefix(tmp_path, damage):
    from hashlib import sha256

    from app.domain.refs import canonical_json, parse_canonical
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cfg = put(saved, run)
    put(saved, run, parent=cfg["configurable"]["checkpoint_id"])
    with sqlite3.connect(subject.legacy.path) as db:
        if damage == "missing":
            db.execute("DELETE FROM runtime_checkpoints WHERE revision=1")
        elif damage == "digest":
            db.execute("UPDATE runtime_checkpoints SET cursor=? WHERE revision=1", (b"bad",))
        else:
            raw = db.execute("SELECT cursor FROM runtime_checkpoints WHERE revision=2").fetchone()[0]
            record = parse_canonical(raw)
            if damage == "grammar":
                record["unexpected"] = "PRIVATE"
            elif damage in {"environment", "manifest"}:
                record["binding"][damage + "_ref"]["sha256"] = "f" * 64
            else:
                record["data"]["parent"] = identifier()
            raw = canonical_json(record)
            db.execute("UPDATE runtime_checkpoints SET cursor=?,cursor_sha256=? WHERE revision=2",
                       (raw, sha256(raw).hexdigest()))
    with pytest.raises(module.CheckpointError):
        saver(module, subject, run)


def test_bounds_and_failed_commit_never_acknowledge_or_advance_node(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run, max_records=1)
    cfg = put(saved, run)
    with pytest.raises(module.CheckpointError):
        saved.put_writes(cfg, [("counters", {"first": 1})], identifier())
    assert saved.get_tuple(cfg).pending_writes == []
    with pytest.raises(module.CheckpointError):
        saver(module, subject, run, max_history_bytes=1)
    # An actual SQLite abort exercises ledger rollback, including command acknowledgement.
    module, subject, run = setup(tmp_path / "abort")
    saved = saver(module, subject, run)
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("CREATE TRIGGER fail_checkpoint BEFORE INSERT ON runtime_checkpoints "
                   "BEGIN SELECT RAISE(ABORT, 'PRIVATE_SQL_CANARY'); END")
    calls = []
    graph = StateGraph(State).add_node("first", lambda state: calls.append(1) or {})
    graph.add_edge(START, "first").add_edge("first", END)
    with pytest.raises(module.CheckpointError) as exc:
        graph.compile(checkpointer=saved).invoke({"results": {}, "counters": {}},
            config(run), durability="sync")
    assert calls == [] and "PRIVATE_SQL_CANARY" not in str(exc.value)
    with pytest.raises(KeyError):
        subject.ledger.read_checkpoint(run.run_id, "langgraph-v1")


def test_simultaneous_savers_cas_one_commit_and_halt_loser(tmp_path, monkeypatch):
    module, subject, run = setup(tmp_path)
    savers = [saver(module, subject, run), saver(module, subject, run)]
    barrier = Barrier(2)
    original = subject.ledger.write_checkpoint
    def at_commit(*args, **kwargs):
        barrier.wait(timeout=5)
        return original(*args, **kwargs)
    monkeypatch.setattr(subject.ledger, "write_checkpoint", at_commit)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(put, item, run) for item in savers]
        outcomes = [future.exception() for future in futures]
    assert sum(value is None for value in outcomes) == 1
    loser = savers[next(i for i, value in enumerate(outcomes) if value is not None)]
    with pytest.raises(module.CheckpointError):
        loser.get_tuple(config(run))
    assert subject.ledger.read_checkpoint(run.run_id, "langgraph-v1")["revision"] == 1


def test_pending_write_abort_stops_dependent_node_and_restarts_from_prefix(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    calls = []
    builder = (StateGraph(State)
        .add_node("first", lambda state: calls.append("first") or {"counters": {"first": 1}})
        .add_node("second", lambda state: calls.append("second") or {"counters": {"second": 1}})
        .add_edge(START, "first").add_edge("first", "second").add_edge("second", END))
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("CREATE TRIGGER fail_checkpoint BEFORE INSERT ON runtime_checkpoints "
                   "WHEN NEW.revision=4 BEGIN SELECT RAISE(ABORT, 'private'); END")
    with pytest.raises(module.CheckpointError):
        builder.compile(checkpointer=saved).invoke({"results": {}, "counters": {}},
            config(run), durability="sync")
    assert calls == ["first"]
    assert subject.ledger.read_checkpoint(run.run_id, "langgraph-v1")["revision"] == 3
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("DROP TRIGGER fail_checkpoint")
    reopen(subject, tmp_path)
    restored = saver(module, subject, run)
    assert restored.get_tuple(config(run)).pending_writes == []
    result = builder.compile(checkpointer=restored).invoke(None, config(run), durability="sync")
    assert calls == ["first", "first", "second"]
    assert result["counters"] == {"first": 1, "second": 1}


def test_byte_limit_and_list_bounds_are_visible(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run, max_history_bytes=1)
    with pytest.raises(module.CheckpointError):
        put(saved, run)
    assert saved.get_tuple(config(run)) is None
    for limit in (0, -1, True, 1001):
        with pytest.raises(module.CheckpointError):
            list(saved.list(config(run), limit=limit))


def test_rejects_wrong_run_object_state_versions_metadata_and_unknown_parent(tmp_path):
    module, subject, run = setup(tmp_path)
    with pytest.raises(module.CheckpointError):
        module.LedgerCheckpointSaver(subject.ledger, identifier(), graph_digest="a" * 64,
                                     authority_digest="b" * 64)
    saved = saver(module, subject, run)
    for change in ({"channel_values": {"counters": object()}}, {"v": 3},
                   {"versions_seen": {"foreign": {}}}, {"pending_sends": []}):
        with pytest.raises(module.CheckpointError):
            put(saved, run, checkpoint() | change)
    with pytest.raises(module.CheckpointError):
        saved.put(config(run), checkpoint(),
                  {"source": "input", "step": -1, "parents": {}, "secret": "CANARY"}, {})
    with pytest.raises(module.CheckpointError):
        put(saved, run, parent=identifier())
    with pytest.raises(module.CheckpointError):
        saved.put_writes(config(run, identifier()), [("counters", {})], identifier())
    assert saved.get_tuple(config(run)) is None


def test_unchanged_version_cannot_replace_state_and_old_writes_cannot_fork(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cfg = put(saved, run)
    cp = checkpoint()
    cp["channel_values"]["counters"] = {"first": 1}
    with pytest.raises(module.CheckpointError):
        put(saved, run, cp, parent=cfg["configurable"]["checkpoint_id"])
    latest = put(saved, run, parent=cfg["configurable"]["checkpoint_id"])
    with pytest.raises(module.CheckpointError):
        saved.put_writes(cfg, [("counters", {"first": 1})], identifier())
    assert saved.get_tuple(latest).checkpoint["channel_values"]["counters"] == {}


def test_cursor_limit_rejects_before_commit_and_history_restore_bound(tmp_path, monkeypatch):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    monkeypatch.setattr(module, "MAX_CHECKPOINT_BYTES", 128)
    with pytest.raises(module.CheckpointError):
        put(saved, run)
    assert saved.get_tuple(config(run)) is None
    monkeypatch.undo()
    cfg = put(saved, run)
    put(saved, run, parent=cfg["configurable"]["checkpoint_id"])
    with pytest.raises(module.CheckpointError):
        saver(module, subject, run, max_records=1)


def test_serialization_complexity_bound_has_safe_adapter_error(tmp_path):
    module, subject, run = setup(tmp_path)
    nodes = tuple("n" + str(i) for i in range(256))
    saved = module.LedgerCheckpointSaver(subject.ledger, run.run_id,
        graph_digest="a" * 64, authority_digest="b" * 64, node_ids=nodes)
    cp = checkpoint()
    cp["channel_versions"].update({"branch:to:" + node: 1 for node in nodes})
    cp["versions_seen"] = {node: dict(cp["channel_versions"]) for node in nodes}
    with pytest.raises(module.CheckpointError):
        put(saved, run, cp)
    assert saved.get_tuple(config(run)) is None


@pytest.mark.parametrize("damage", ["checkpoint_id", "index", "value", "conflict"])
def test_recovery_revalidates_pending_write_references_and_identity(tmp_path, damage):
    from hashlib import sha256

    from app.domain.refs import canonical_json, parse_canonical
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cfg = put(saved, run)
    task = identifier()
    saved.put_writes(cfg, [("counters", {"first": 1})], task)
    saved.put_writes(cfg, [("counters", {"first": 1})], task)
    with sqlite3.connect(subject.legacy.path) as db:
        raw = db.execute("SELECT cursor FROM runtime_checkpoints WHERE revision=3").fetchone()[0]
        record = parse_canonical(raw)
        if damage == "checkpoint_id":
            record["data"]["checkpoint_id"] = identifier()
        elif damage == "index":
            record["data"]["writes"][0]["index"] = -1
        else:
            record["data"]["writes"][0]["value"] = {"first": -1 if damage == "value" else 2}
        raw = canonical_json(record)
        db.execute("UPDATE runtime_checkpoints SET cursor=?,cursor_sha256=? WHERE revision=3",
                   (raw, sha256(raw).hexdigest()))
    with pytest.raises(module.CheckpointError):
        saver(module, subject, run)


def test_bounded_listing_returns_exact_configs_without_private_metadata(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    first = put(saved, run)
    second = put(saved, run, parent=first["configurable"]["checkpoint_id"])
    assert [item.config for item in saved.list(config(run), limit=1)] == [second]
    assert [item.config for item in saved.list(config(run), before=second, limit=2)] == [first]
    assert [item.config for item in saved.list(first, limit=2)] == [first]
    with pytest.raises(module.CheckpointError):
        list(saved.list(config(run), filter={"private": "CANARY"}))
    cfg = {"configurable": second["configurable"] | {"secret": "CANARY"},
           "metadata": {"secret": "CANARY"}}
    assert saved.get_tuple(cfg).config == second
    saved.put_writes(second, [("counters", {"first": 1})], identifier())
    returned = saved.get_tuple(second)
    returned.pending_writes[0][2]["first"] = 99
    returned.metadata["step"] = 999
    assert saved.get_tuple(second).pending_writes[0][2] == {"first": 1}
    assert saved.get_tuple(second).metadata["step"] == -1


def test_noop_graph_completes_and_reopens_without_rerunning(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    calls = []
    def noop(state):
        calls.append("first")
        return {}
    builder = (StateGraph(State).add_node("first", noop)
               .add_edge(START, "first").add_edge("first", END))
    assert builder.compile(checkpointer=saved).invoke(
        {"results": {}, "counters": {}}, config(run), durability="sync") == {
            "results": {}, "counters": {}}
    before = list(saved.list(config(run), limit=10))
    assert any(channel == "__no_writes__" and value is None
               for item in before for _, channel, value in item.pending_writes)
    reopen(subject, tmp_path)
    restored = saver(module, subject, run)
    assert list(restored.list(config(run), limit=10)) == before
    assert builder.compile(checkpointer=restored).invoke(None, config(run), durability="sync") == {
        "results": {}, "counters": {}}
    assert calls == ["first"]


def test_committed_noop_pending_marker_survives_next_checkpoint_failure(tmp_path):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    calls = []
    def noop(state):
        calls.append("first")
        return {}
    builder = (StateGraph(State).add_node("first", noop)
               .add_edge(START, "first").add_edge("first", END))
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("CREATE TRIGGER fail_checkpoint BEFORE INSERT ON runtime_checkpoints "
                   "WHEN NEW.revision=5 BEGIN SELECT RAISE(ABORT, 'private'); END")
    with pytest.raises(module.CheckpointError):
        builder.compile(checkpointer=saved).invoke({"results": {}, "counters": {}},
                                                 config(run), durability="sync")
    assert calls == ["first"]
    assert subject.ledger.read_checkpoint(run.run_id, "langgraph-v1")["revision"] == 4
    with sqlite3.connect(subject.legacy.path) as db:
        db.execute("DROP TRIGGER fail_checkpoint")
    reopen(subject, tmp_path)
    restored = saver(module, subject, run)
    pending = restored.get_tuple(config(run)).pending_writes
    assert len(pending) == 1 and pending[0][1:] == ("__no_writes__", None)
    assert builder.compile(checkpointer=restored).invoke(None, config(run), durability="sync") == {
        "results": {}, "counters": {}}
    assert calls == ["first"]


@pytest.mark.parametrize("value", [True, 0, "", {}, [], "PRIVATE_CANARY"])
def test_noop_marker_rejects_non_null_pending_values(tmp_path, value):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cfg = put(saved, run)
    with pytest.raises(module.CheckpointError):
        saved.put_writes(cfg, [("__no_writes__", value)], identifier())
    assert subject.ledger.read_checkpoint(run.run_id, "langgraph-v1")["revision"] == 1
    assert saved.get_tuple(cfg).pending_writes == []


@pytest.mark.parametrize("location", ["channel_values", "channel_versions", "start", "seen"])
def test_noop_marker_is_not_a_checkpoint_or_application_channel(tmp_path, location):
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cp = checkpoint()
    if location == "channel_values":
        cp["channel_values"]["__no_writes__"] = None
        cp["channel_versions"]["__no_writes__"] = 1
    elif location == "channel_versions":
        cp["channel_versions"]["__no_writes__"] = 1
    elif location == "start":
        cp["channel_values"]["__start__"] = {"__no_writes__": None}
        cp["channel_versions"]["__start__"] = 1
    else:
        cp["versions_seen"] = {"first": {"__no_writes__": 1}}
    with pytest.raises(module.CheckpointError):
        put(saved, run, cp)
    assert saved.get_tuple(config(run)) is None


def test_recovery_rejects_non_null_noop_marker_in_committed_journal(tmp_path):
    from hashlib import sha256

    from app.domain.refs import canonical_json, parse_canonical
    module, subject, run = setup(tmp_path)
    saved = saver(module, subject, run)
    cfg = put(saved, run)
    saved.put_writes(cfg, [("__no_writes__", None)], identifier())
    with sqlite3.connect(subject.legacy.path) as db:
        raw = db.execute("SELECT cursor FROM runtime_checkpoints WHERE revision=2").fetchone()[0]
        record = parse_canonical(raw)
        record["data"]["writes"][0]["value"] = "PRIVATE_CANARY"
        raw = canonical_json(record)
        db.execute("UPDATE runtime_checkpoints SET cursor=?,cursor_sha256=? WHERE revision=2",
                   (raw, sha256(raw).hexdigest()))
    with pytest.raises(module.CheckpointError):
        saver(module, subject, run)


def test_pending_writes_bind_the_attempt_registered_for_their_execution(tmp_path):
    # T040: the journal row that first carries a bound node's accepted result is
    # bound to the attempt that produced it; every other row stays unbound
    from app.tests.test_runtime_ledger import attempt_spec, execution_spec, owner

    module, subject, run = setup(tmp_path)
    bindings = module.AttemptBindings()
    saved = saver(module, subject, run, attempt_bindings=bindings)
    cp = checkpoint()
    cfg = put(saved, run, cp)
    execution = execution_spec(subject, run.run_id)
    subject.ledger.create_execution(identifier(), execution)
    lease_owner = owner(subject)
    spec = attempt_spec(subject, execution.execution_id, lease_owner)
    subject.ledger.reserve_attempt(identifier(), spec, lease_duration_ms=1_000)
    bindings.set(execution.execution_id, spec.attempt_id)
    saved.put_writes(cfg, [("results", {execution.execution_id: subject.refs.result})], identifier(),
                     "~__pregel_pull, first")
    row = subject.ledger.read_checkpoint(run.run_id, module.NAMESPACE)
    assert row["revision"] == 2
    assert row["bound_attempt_id"] == spec.attempt_id
    assert row["bound_execution_id"] == execution.execution_id
    assert row["bound_envelope_sha256"] == spec.envelope_ref.sha256
    assert row["bound_attempt_revision"] == subject.ledger.get_attempt(spec.attempt_id)["revision"]
    # an unregistered execution, a counters-only write and the merging checkpoint stay unbound
    saved.put_writes(cfg, [("results", {identifier(): subject.refs.result})], identifier())
    assert subject.ledger.read_checkpoint(run.run_id, module.NAMESPACE)["bound_attempt_id"] is None
    saved.put_writes(cfg, [("counters", {"first": 1})], identifier())
    assert subject.ledger.read_checkpoint(run.run_id, module.NAMESPACE)["bound_attempt_id"] is None
    merged = checkpoint()
    merged["channel_values"] = {"results": {execution.execution_id: subject.refs.result}, "counters": {}}
    merged["channel_versions"] = {"results": 2, "counters": 1}
    saved.put(config(run, cp["id"]), merged, {"source": "loop", "step": 0, "parents": {}}, {"results": 2})
    assert subject.ledger.read_checkpoint(run.run_id, module.NAMESPACE)["bound_attempt_id"] is None
    # the bound row replays on reopen and the binding is verified by the ledger
    reopen(subject, tmp_path)
    replayed = saver(module, subject, run, attempt_bindings=module.AttemptBindings())
    assert replayed.get_tuple(config(run)).checkpoint["channel_values"]["results"] == {
        execution.execution_id: subject.refs.result,
    }
    assert subject.ledger.checkpoint_for_replay(run.run_id, module.NAMESPACE, revision=2)["bound_attempt_id"] == spec.attempt_id
    # a registry entry naming an attempt of another run never commits: the saver halts
    other = run_spec(subject)
    subject.ledger.create_run(identifier(), other)
    other_execution = execution_spec(subject, other.run_id)
    subject.ledger.create_execution(identifier(), other_execution)
    foreign = attempt_spec(subject, other_execution.execution_id, owner(subject))
    subject.ledger.reserve_attempt(identifier(), foreign, lease_duration_ms=1_000)
    poisoned = module.AttemptBindings()
    poisoned.set(execution.execution_id, foreign.attempt_id)
    halting = saver(module, subject, run, attempt_bindings=poisoned)
    head = subject.ledger.read_checkpoint(run.run_id, module.NAMESPACE)["revision"]
    with pytest.raises(module.CheckpointError):
        halting.put_writes(config(run, merged["id"]),
                           [("results", {execution.execution_id: subject.refs.result})], identifier())
    assert subject.ledger.read_checkpoint(run.run_id, module.NAMESPACE)["revision"] == head
    with pytest.raises(module.CheckpointError):
        halting.put_writes(config(run, merged["id"]), [("counters", {"first": 2})], identifier())
    with pytest.raises(module.CheckpointError):
        saver(module, subject, run, attempt_bindings=object())
