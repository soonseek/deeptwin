from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict, fields, replace
import hashlib
import json
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest


from app import critic_audit as audit


def frozen_call(**changes):
    call = audit.FrozenCall(
        "request-1", "run-1", "review", "c71", "v1", "visible",
        "{}", "{}", "{}", audit.canonical({"call_seconds": 1.0}),
    )
    return replace(call, **changes) if changes else call


def opened_ledger(tmp_path, *, max_calls=10, max_seconds=10, clock=lambda: 100.0):
    ledger = audit.Ledger(tmp_path.resolve() / "audit" / "eval.sqlite3", clock=clock)
    ledger.open_run("run-1", max_calls=max_calls, max_seconds=max_seconds)
    return ledger


def test_canonical_uses_sorted_compact_unicode_json():
    assert audit.canonical({"z": [1, True, None], "a": "한국어"}) == '{"a":"한국어","z":[1,true,null]}'


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_rejects_nonfinite_values(value):
    with pytest.raises(ValueError):
        audit.canonical({"nested": [value]})


@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), "1", None, 10**1000])
def test_positive_seconds_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        audit.positive_seconds(value)


@pytest.mark.parametrize("value", [1, 0.5])
def test_positive_seconds_returns_float(value):
    result = audit.positive_seconds(value)
    assert result == value
    assert type(result) is float


def test_positive_seconds_rejects_numeric_subclasses():

    class IntSeconds(int):
        pass

    class FloatSeconds(float):
        pass

    for value in (IntSeconds(1), FloatSeconds(1)):
        with pytest.raises(ValueError):
            audit.positive_seconds(value)


@pytest.mark.parametrize("value", ["", "../id", "x/y", "a.b", "a b", "a\n", "한글", "x" * 101, 1, None])
def test_identifier_rejects_unsafe_values(value):
    with pytest.raises(ValueError):
        audit.identifier(value)


def test_identifier_accepts_exact_safe_bounds():
    for value in ("a", "A_9-z", "x" * 100):
        assert audit.identifier(value) == value


def test_frozen_call_has_exact_fields_and_is_immutable():
    call = frozen_call()
    assert [field.name for field in fields(call)] == [
        "request_id", "run_id", "purpose", "candidate_id", "candidate_version", "prompt",
        "schema_json", "manifest_json", "selection_json", "metadata_json",
    ]
    with pytest.raises(FrozenInstanceError):
        call.prompt = "changed"
    returned = call.as_dict()
    assert returned == asdict(call)
    returned["prompt"] = "detached"
    assert call.prompt == "visible"
    expected = json.dumps(asdict(call), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    assert call.digest == hashlib.sha256(expected.encode("utf-8")).hexdigest()


@pytest.mark.parametrize("field", ["request_id", "run_id", "purpose", "candidate_id", "candidate_version", "prompt", "schema_json", "manifest_json", "selection_json", "metadata_json"])
@pytest.mark.parametrize("value", ["", None, 1])
def test_frozen_call_requires_nonempty_strings(field, value):
    with pytest.raises(ValueError):
        frozen_call(**{field: value})


@pytest.mark.parametrize("purpose", ["review", "counterexample_proposal", "counterexample_validity", "candidate_response"])
def test_frozen_call_accepts_only_critic_purposes(purpose):
    assert frozen_call(purpose=purpose).purpose == purpose
    with pytest.raises(ValueError):
        frozen_call(purpose="semantic_score")


def test_frozen_call_identifiers_are_safe_but_candidate_labels_are_opaque():
    with pytest.raises(ValueError):
        frozen_call(request_id="../request")
    with pytest.raises(ValueError):
        frozen_call(run_id="run/id")
    call = frozen_call(candidate_id="후보/71", candidate_version="revision 1.0")
    assert call.candidate_id == "후보/71"
    assert call.candidate_version == "revision 1.0"


@pytest.mark.parametrize("field", ["schema_json", "manifest_json", "selection_json", "metadata_json"])
@pytest.mark.parametrize("payload", ['{ "a":1}', '{"a":1,"a":2}', '{"a":NaN}', '{"a":1e999}', "not json"])
def test_frozen_call_rejects_noncanonical_or_invalid_json(field, payload):
    with pytest.raises(ValueError):
        frozen_call(**{field: payload})


def test_frozen_call_size_limit_counts_whole_canonical_utf8_payload():
    call = frozen_call(prompt="x")
    overhead = len(audit.canonical(call.as_dict()).encode("utf-8")) - 1
    boundary = frozen_call(prompt="x" * (1_000_000 - overhead))
    assert len(audit.canonical(boundary.as_dict()).encode("utf-8")) == 1_000_000
    with pytest.raises(ValueError):
        frozen_call(prompt=boundary.prompt + "x")
    with pytest.raises(ValueError):
        frozen_call(prompt="한" * 400_000)


def test_reservation_commits_exact_predispatch_record(tmp_path):
    ledger = opened_ledger(tmp_path)
    call = frozen_call(prompt="원문\nvisible", schema_json='{"type":"object"}')
    ledger.reserve(call)
    reopened = audit.Ledger(tmp_path.resolve() / "audit" / "eval.sqlite3", clock=lambda: 100.0)
    record = reopened.get(call.request_id)
    assert record == {
        "call": call.as_dict(), "digest": call.digest, "state": "reserved", "details": {},
        "events": [{"seq": 1, "at": 100.0, "kind": "reserved", "details": {}}],
    }
    with sqlite3.connect(tmp_path.resolve() / "audit" / "eval.sqlite3") as db:
        assert db.execute("SELECT payload, digest FROM calls").fetchone() == (audit.canonical(call.as_dict()), call.digest)
        assert db.execute("SELECT used FROM runs").fetchone() == (1,)


def test_begin_transitions_once_and_records_transfer_not_started(tmp_path):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    assert ledger.begin("request-1") is True
    assert ledger.begin("request-1") is False
    record = ledger.get("request-1")
    assert record["state"] == "dispatching"
    assert record["details"] == {"transfer": "not_started"}
    assert [event["kind"] for event in record["events"]] == ["reserved", "dispatching"]
    assert record["events"][-1]["details"] == record["details"]


@pytest.mark.parametrize("changed", [False, True])
def test_duplicate_request_id_cannot_replace_original_or_spend_budget(tmp_path, changed):
    ledger = opened_ledger(tmp_path, max_calls=2)
    call = frozen_call()
    ledger.reserve(call)
    original = ledger.get("request-1")
    duplicate = replace(call, prompt="different") if changed else call
    with pytest.raises(ValueError, match="request identifier already used"):
        ledger.reserve(duplicate)
    assert ledger.get("request-1") == original
    ledger.reserve(frozen_call(request_id="request-2"))


def test_request_ids_are_globally_unique_across_runs(tmp_path):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    ledger.open_run("run-2", max_calls=1, max_seconds=10)
    with pytest.raises(ValueError, match="request identifier already used"):
        ledger.reserve(frozen_call(run_id="run-2"))
    ledger.reserve(frozen_call(request_id="request-2", run_id="run-2"))
    assert ledger.get("request-1")["call"]["run_id"] == "run-1"


def test_reserve_requires_exact_frozen_call_type(tmp_path):
    ledger = opened_ledger(tmp_path)

    class OtherCall(audit.FrozenCall):
        pass

    for invalid in (frozen_call().as_dict(), OtherCall(**frozen_call().as_dict())):
        with pytest.raises((TypeError, ValueError)):
            ledger.reserve(invalid)


def test_four_parallel_reservations_obey_one_call_cap(tmp_path):
    ledger = opened_ledger(tmp_path, max_calls=1)
    start = Barrier(4)

    def reserve(index):
        start.wait(timeout=5)
        try:
            ledger.reserve(frozen_call(request_id=f"request-{index}"))
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=4) as pool:
        accepted = list(pool.map(reserve, range(4)))
    assert sum(accepted) == 1
    with sqlite3.connect(tmp_path.resolve() / "audit" / "eval.sqlite3") as db:
        assert db.execute("SELECT used FROM runs").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM calls").fetchone() == (1,)
        assert db.execute("SELECT COUNT(*) FROM events").fetchone() == (1,)


@pytest.mark.parametrize("begin_first", [False, True])
def test_cancel_is_terminal_and_cannot_finish_or_begin(tmp_path, begin_first):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    if begin_first:
        ledger.begin("request-1")
    assert ledger.cancel("request-1") is True
    original = ledger.get("request-1")
    assert original["state"] == "cancelled"
    assert original["details"] == {"remote_stop": "unconfirmed", "score": None}
    assert ledger.finish("request-1", "completed", {"score": 1}) is False
    assert ledger.begin("request-1") is False
    assert ledger.cancel("request-1") is False
    assert ledger.get("request-1") == original


def test_reopened_ledger_does_not_recover_implicitly(tmp_path):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    ledger.begin("request-1")
    original = ledger.get("request-1")
    reopened = audit.Ledger(tmp_path.resolve() / "audit" / "eval.sqlite3", clock=lambda: 100.0)
    assert reopened.get("request-1") == original
    assert reopened.recover() == 1
    interrupted = reopened.get("request-1")
    assert interrupted["state"] == "interrupted"
    assert interrupted["details"] == {"reason": "restart", "score": None, "remote_stop": "unconfirmed"}
    assert interrupted["events"][:-1] == original["events"]
    assert interrupted["events"][-1]["details"] == interrupted["details"]
    assert reopened.recover() == 0
    assert reopened.get("request-1") == interrupted


def test_recover_covers_reserved_and_dispatching_but_preserves_terminal_calls(tmp_path):
    ledger = opened_ledger(tmp_path)
    for index in range(3):
        ledger.reserve(frozen_call(request_id=f"request-{index}"))
    ledger.begin("request-1")
    ledger.finish("request-2", "completed", {"response": "synthetic"})
    completed = ledger.get("request-2")
    assert ledger.recover() == 2
    assert ledger.get("request-0")["state"] == "interrupted"
    assert ledger.get("request-1")["state"] == "interrupted"
    assert ledger.get("request-2") == completed


def test_two_concurrent_terminal_commits_have_exactly_one_winner(tmp_path):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    ledger.begin("request-1")
    start = Barrier(2)

    def finish(state):
        start.wait(timeout=5)
        return ledger.finish("request-1", state, {"winner": state})

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finish, ["completed", "timed_out"]))
    assert sum(results) == 1
    record = ledger.get("request-1")
    assert record["details"] == {"winner": record["state"]}
    assert [event["kind"] for event in record["events"]] == ["reserved", "dispatching", record["state"]]
    assert record["events"][-1]["details"] == record["details"]


@pytest.mark.parametrize("state", ["completed", "invalid", "cancelled", "timed_out", "interrupted"])
def test_finish_terminal_states_are_first_commit_wins(tmp_path, state):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    assert ledger.finish("request-1", state, {"message": "한국어"}) is True
    before = ledger.get("request-1")
    assert ledger.finish("request-1", "invalid", {}) is False
    assert ledger.get("request-1") == before


@pytest.mark.parametrize("state,details", [("reserved", {}), ("unknown", {}), (None, {}), ("completed", []), ("completed", {"score": float("nan")}), ("completed", {"text": "x" * 1_000_000})])
def test_finish_rejects_invalid_state_or_details_without_changes(tmp_path, state, details):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    original = ledger.get("request-1")
    with pytest.raises(ValueError):
        ledger.finish("request-1", state, details)
    assert ledger.get("request-1") == original


def test_late_worker_observation_does_not_change_terminal_result(tmp_path):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    ledger.cancel("request-1")
    original = ledger.get("request-1")
    details = {"worker_state": "completed", "response": "late synthetic result"}
    ledger.observe("request-1", "late_worker_finished", details)
    after = ledger.get("request-1")
    assert {key: value for key, value in after.items() if key != "events"} == {key: value for key, value in original.items() if key != "events"}
    assert after["events"][:-1] == original["events"]
    assert after["events"][-1]["kind"] == "late_worker_finished"
    assert after["events"][-1]["details"] == details


@pytest.mark.parametrize("kind,details", [("completed", {}), ("late_worker_finished", []), ("late_worker_finished", {"text": "x" * 10_000}), ("late_worker_finished", {"score": float("inf")})])
def test_observe_validates_kind_and_bounded_details(tmp_path, kind, details):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    original = ledger.get("request-1")
    with pytest.raises(ValueError):
        ledger.observe("request-1", kind, details)
    assert ledger.get("request-1") == original


@pytest.mark.parametrize("seconds", [True, 0, -1, float("nan"), float("inf"), 10**1000])
def test_open_run_rejects_invalid_seconds(tmp_path, seconds):
    ledger = audit.Ledger(tmp_path.resolve() / "audit" / "eval.sqlite3")
    with pytest.raises(ValueError):
        ledger.open_run("run-1", max_calls=1, max_seconds=seconds)


@pytest.mark.parametrize("count", [True, 0, -1, 1.5, 1_000_001])
def test_open_run_rejects_invalid_call_caps(tmp_path, count):
    ledger = audit.Ledger(tmp_path.resolve() / "audit" / "eval.sqlite3")
    with pytest.raises(ValueError):
        ledger.open_run("run-1", max_calls=count, max_seconds=1)


def test_open_run_rejects_nonfinite_deadline_and_id_reuse(tmp_path):
    ledger = audit.Ledger(tmp_path.resolve() / "audit" / "eval.sqlite3", clock=lambda: 1e308)
    with pytest.raises(ValueError):
        ledger.open_run("overflow", max_calls=1, max_seconds=1e308)
    with pytest.raises(ValueError):
        ledger.open_run("unsafe/id", max_calls=1, max_seconds=1)
    ledger.open_run("run-1", max_calls=1, max_seconds=1)
    with pytest.raises((ValueError, sqlite3.IntegrityError)):
        ledger.open_run("run-1", max_calls=2, max_seconds=2)


def test_expired_run_rejects_reservation_without_spending_budget(tmp_path):
    now = [100.0]
    ledger = opened_ledger(tmp_path, max_seconds=1, clock=lambda: now[0])
    assert ledger.remaining("run-1") == 1.0
    now[0] = 101.0
    with pytest.raises(ValueError):
        ledger.reserve(frozen_call())
    assert ledger.remaining("run-1") == 0
    now[0] = 200.0
    assert ledger.remaining("run-1") == 0
    with sqlite3.connect(tmp_path.resolve() / "audit" / "eval.sqlite3") as db:
        assert db.execute("SELECT used FROM runs").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM calls").fetchone() == (0,)


def test_begin_after_deadline_times_out_without_starting_transfer(tmp_path):
    now = [100.0]
    ledger = opened_ledger(tmp_path, max_seconds=1, clock=lambda: now[0])
    ledger.reserve(frozen_call())
    now[0] = 101.0
    assert ledger.begin("request-1") is False
    record = ledger.get("request-1")
    assert record["state"] == "timed_out"
    assert record["details"] == {"transfer": "not_started"}
    assert record["events"][-1] == {"seq": 2, "at": 101.0, "kind": "timed_out", "details": {"transfer": "not_started"}}
    assert ledger.begin("request-1") is False
    assert ledger.finish("request-1", "completed", {}) is False


def test_unknown_ids_have_explicit_behavior(tmp_path):
    ledger = opened_ledger(tmp_path)
    for operation in (lambda: ledger.get("missing"), lambda: ledger.remaining("missing"), lambda: ledger.begin("missing")):
        with pytest.raises(KeyError):
            operation()
    with pytest.raises(ValueError, match="run budget unavailable"):
        ledger.reserve(frozen_call(run_id="missing"))
    assert ledger.finish("missing", "completed", {}) is False
    assert ledger.cancel("missing") is False
    with pytest.raises(sqlite3.IntegrityError):
        ledger.observe("missing", "late_worker_finished", {})


def test_ledger_creates_private_dedicated_file_and_directory(tmp_path):
    path = tmp_path.resolve() / "audit" / "eval.sqlite3"
    audit.Ledger(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    path.chmod(0o644)
    path.parent.chmod(0o755)
    audit.Ledger(path)
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700


def test_ledger_rejects_relative_or_wrong_named_paths(tmp_path):
    for path in (Path("audit/eval.sqlite3"), tmp_path.resolve() / "other.sqlite3"):
        with pytest.raises(ValueError):
            audit.Ledger(path)
    assert list(tmp_path.iterdir()) == []


def test_ledger_rejects_symlink_file_and_ancestor_without_touching_target(tmp_path):
    root = tmp_path.resolve()
    actual = root / "actual"
    actual.mkdir()
    target = actual / "eval.sqlite3"
    target.write_bytes(b"synthetic target must not be touched")
    before_mode = target.stat().st_mode
    linked_dir = root / "linked-dir"
    linked_dir.symlink_to(actual, target_is_directory=True)
    with pytest.raises(ValueError):
        audit.Ledger(linked_dir / "nested" / "eval.sqlite3")
    assert not (actual / "nested").exists()
    other = root / "other"
    other.mkdir()
    (other / "eval.sqlite3").symlink_to(target)
    with pytest.raises(ValueError):
        audit.Ledger(other / "eval.sqlite3")
    assert target.read_bytes() == b"synthetic target must not be touched"
    assert target.stat().st_mode == before_mode


def test_ledger_rejects_non_dedicated_directory_without_changes(tmp_path):
    path = tmp_path.resolve() / "eval.sqlite3"
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("synthetic unrelated content")
    before_mode = tmp_path.stat().st_mode
    with pytest.raises(ValueError):
        audit.Ledger(path)
    assert not path.exists()
    assert unrelated.read_text() == "synthetic unrelated content"
    assert tmp_path.stat().st_mode == before_mode


def test_ledger_rejects_symlink_journal_before_opening_database(tmp_path):
    root = tmp_path.resolve()
    directory = root / "audit"
    directory.mkdir()
    outside = root / "journal-target"
    outside.write_bytes(b"preserve me")
    (directory / "eval.sqlite3-journal").symlink_to(outside)
    with pytest.raises(ValueError):
        audit.Ledger(directory / "eval.sqlite3")
    assert not (directory / "eval.sqlite3").exists()
    assert outside.read_bytes() == b"preserve me"


def test_failed_reservation_event_rolls_back_payload_and_budget(tmp_path):
    ledger = opened_ledger(tmp_path, max_calls=1)
    path = tmp_path.resolve() / "audit" / "eval.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'synthetic event failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic event failure"):
        ledger.reserve(frozen_call())
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT used FROM runs").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM calls").fetchone() == (0,)
        db.execute("DROP TRIGGER fail_event")
    ledger.reserve(frozen_call())
    assert ledger.get("request-1")["state"] == "reserved"


@pytest.mark.parametrize("operation", ["begin", "finish", "recover"])
def test_failed_transition_event_rolls_back_call_state(tmp_path, operation):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    before = ledger.get("request-1")
    path = tmp_path.resolve() / "audit" / "eval.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'synthetic event failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        if operation == "begin":
            ledger.begin("request-1")
        elif operation == "finish":
            ledger.finish("request-1", "completed", {})
        else:
            ledger.recover()
    assert ledger.get("request-1") == before


@pytest.mark.parametrize("corruption", ["digest", "payload", "invalid_call"])
def test_get_rejects_corrupt_frozen_record(tmp_path, corruption):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    path = tmp_path.resolve() / "audit" / "eval.sqlite3"
    with sqlite3.connect(path) as db:
        if corruption == "digest":
            db.execute("UPDATE calls SET digest = ?", ("0" * 64,))
        elif corruption == "payload":
            data = frozen_call().as_dict()
            data["prompt"] = "changed"
            db.execute("UPDATE calls SET payload = ?", (audit.canonical(data),))
        else:
            data = frozen_call().as_dict()
            data["purpose"] = "bad"
            payload = audit.canonical(data)
            digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            db.execute("UPDATE calls SET payload = ?, digest = ?", (payload, digest))
    with pytest.raises(ValueError):
        ledger.get("request-1")


def test_get_reads_call_and_events_from_one_snapshot(tmp_path, monkeypatch):
    ledger = opened_ledger(tmp_path)
    ledger.reserve(frozen_call())
    path = tmp_path.resolve() / "audit" / "eval.sqlite3"
    connect = sqlite3.connect
    inserted = []

    class InterleavedConnection(sqlite3.Connection):
        def execute(self, sql, parameters=()):
            # WAL lets a real writer commit while this reader's transaction is open.
            # Interleave only once, immediately before the reader fetches its events.
            if "from events" in " ".join(sql.lower().split()) and not inserted:
                inserted.append(True)
                assert ledger.finish("request-1", "completed", {"response": "synthetic"}) is True
            return super().execute(sql, parameters)

    def interleaved_connect(*args, **kwargs):
        return connect(*args, **kwargs, factory=InterleavedConnection)

    keeper = connect(path)
    try:
        assert keeper.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        monkeypatch.setattr(audit.sqlite3, "connect", interleaved_connect)
        snapshot = ledger.get("request-1")
        assert inserted == [True]
        assert snapshot["state"] == "reserved"
        assert [event["kind"] for event in snapshot["events"]] == ["reserved"]
        latest = ledger.get("request-1")
        assert latest["state"] == "completed"
        assert [event["kind"] for event in latest["events"]] == ["reserved", "completed"]
    finally:
        keeper.close()
