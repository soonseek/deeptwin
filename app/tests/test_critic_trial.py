"""Controlled local fixtures exercise lifecycle, never model quality or readiness."""

from dataclasses import FrozenInstanceError, replace
from hashlib import sha256
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import threading
from types import SimpleNamespace

import pytest

from app.codex_critic import CodexCriticTransport
from app.critic_audit import FrozenCall, Ledger, canonical
from app.critic_contract import InputContractError, prepare_input
from app.generation_profiles import GenerationPurpose as P, profile_for
from app.model_catalog import ModelCatalog
from app.model_selection import ModelSelection
from app.storage import Store
from app.tests.test_model_catalog import CodexFixture
from app.tests.test_critic_contract import PURPOSES, bound_source, output_for


@pytest.fixture(autouse=True)
def prohibit_real_startup(monkeypatch):
    monkeypatch.setattr("app.codex_rpc.CodexRPC.start",
                        lambda *_args, **_kwargs: pytest.fail("real model startup forbidden"))


@pytest.fixture
def trial():
    from app import critic_trial
    return critic_trial


@pytest.fixture
def rig(tmp_path):
    store = Store(tmp_path / "synthetic-intake")
    provider = CodexFixture(store)
    catalog = ModelCatalog(store, provider)
    snapshot = catalog.refresh("codex")  # The explicit CodexFixture is entirely offline.
    selections = ModelSelection(store, catalog)
    work = store.create_work("synthetic controlled trial")
    choice = {"provider": "codex", "mode": "subscription", "model": "gpt-fixture",
              "effort": "low", "catalog_id": snapshot["catalog_id"]}
    selected = selections.save(work["id"], 0, choice)
    ledger = Ledger(tmp_path / "audit" / "eval.sqlite3")
    ledger.open_run("run1", max_calls=4, max_seconds=10)
    prepared = prepare_input(P.REVIEW, bound_source())
    yield SimpleNamespace(store=store, provider=provider, catalog=catalog, selections=selections,
                          work=work, choice=choice, selected=selected, ledger=ledger,
                          root=tmp_path / "runtime", prepared=prepared)
    assert provider.reads == 1
    assert provider.binding_reads == 0


def frozen(trial, rig, *, request_id="request1", prepared=None, **kwargs):
    options = {"run_id": "run1", "request_id": request_id, "call_seconds": 2,
               "code_hashes": {"synthetic_fixture": "0" * 64}}
    options.update(kwargs)
    return trial.freeze_call(prepared or rig.prepared, rig.selections, rig.work["id"], 1, **options)


def test_freeze_records_exact_declared_metadata_without_preflight(trial, rig):
    hashes = {"synthetic_fixture": "0" * 64}
    call = frozen(trial, rig, code_hashes=hashes)
    profile = profile_for(P.REVIEW)
    assert type(call) is FrozenCall
    assert call.prompt == rig.prepared.prompt
    assert call.schema_json == canonical(json.loads(rig.prepared.schema_json))
    assert call.manifest_json == canonical(json.loads(rig.prepared.manifest_json))
    assert json.loads(call.selection_json) == rig.selected["selection"]
    assert json.loads(call.metadata_json) == {
        "work_id": rig.work["id"], "selection_version": 1, "call_seconds": 2,
        "code_hashes": hashes,
        "instruction": {"purpose": "review", "version": profile.version,
                        "base_instructions": profile.base_instructions,
                        "developer_instructions": profile.developer_instructions,
                        "digest": profile.digest},
        "runtime_profile": CodexCriticTransport(None, purpose=P.REVIEW).runtime_profile,
        "runtime_evidence": "declared_not_preflight_confirmed", "actual_effort": None,
        "execution_backend": "offline-only",
    }
    hashes["synthetic_fixture"] = "1" * 64
    rig.selected["selection"]["model"] = "mutated-caller-dict"
    assert json.loads(call.metadata_json)["code_hashes"] == {"synthetic_fixture": "0" * 64}
    assert json.loads(call.selection_json)["model"] == "gpt-fixture"
    with pytest.raises(FrozenInstanceError):
        call.prompt = "changed"


@pytest.mark.parametrize("seconds", [True, False, 0, -1, float("nan"), float("inf"), "2", None, 10**1000])
def test_freeze_rejects_non_strict_positive_finite_seconds(trial, rig, seconds):
    with pytest.raises(ValueError):
        frozen(trial, rig, call_seconds=seconds)


@pytest.mark.parametrize("hashes", [None, {}, [], {1: "0" * 64}, {"": "0" * 64},
                                   {"file": "A" * 64}, {"file": "0" * 63}, {"file": 0}])
def test_freeze_requires_explicit_nonempty_hash_mapping(trial, rig, hashes):
    with pytest.raises(ValueError):
        frozen(trial, rig, code_hashes=hashes)


@pytest.mark.parametrize("field,value", [
    ("prompt", "{}"), ("prompt", "not-json"), ("schema_json", "{}"),
    ("manifest_json", "{}"), ("candidate_id", "forged"),
    ("candidate_version", "forged"), ("purpose", P.CANDIDATE_RESPONSE),
])
def test_freeze_rebuilds_all_prepared_fields(trial, rig, field, value):
    forged = replace(rig.prepared, **{field: value})
    with pytest.raises(InputContractError):
        frozen(trial, rig, prepared=forged)


@pytest.mark.parametrize("target", ["selections", "catalog"])
def test_freeze_requires_real_selection_and_catalog_services(trial, rig, target):
    if target == "selections":
        rig.selections = SimpleNamespace(store=rig.store, catalog=rig.catalog)
    else:
        rig.selections.catalog = object()
    with pytest.raises(ValueError):
        frozen(trial, rig)


@pytest.mark.parametrize("change", ["version", "account"])
def test_freeze_revalidates_current_sql_selection(trial, rig, change):
    if change == "version":
        rig.selections.save(rig.work["id"], 1, {**rig.choice, "effort": "medium"})
    else:
        with rig.store._connection() as db:
            db.execute("UPDATE model_catalog_account_state SET binding = 'changed-synthetic-account'")
    with pytest.raises((ValueError, RuntimeError)):
        frozen(trial, rig)


def test_offline_marker_has_an_explicit_unimplemented_contract(trial, tmp_path):
    context = trial.RuntimeContext(tmp_path)
    assert context.data_dir == tmp_path
    with pytest.raises(FrozenInstanceError):
        context.data_dir = Path("changed")
    with pytest.raises(NotImplementedError, match="supply a controlled offline test double"):
        trial.OfflineTransport().generate("prompt", {}, None, selection={})


def controlled(trial, rig, *, text="{}", mode=None, entered=None, release=None, finished=None):
    """The sole provider boundary is an explicit, bounded in-process fixture."""
    observations = SimpleNamespace(contexts=[], arguments=[], stops=[], states=[])
    read_committed_state = rig.ledger.get

    class ControlledOfflineTransport(trial.OfflineTransport):
        def generate(self, prompt, schema, cancel_event, *, selection):
            observations.arguments.append((prompt, schema, selection))
            observations.stops.append(cancel_event)
            if entered is not None:
                entered.set()
            try:
                if release is not None:
                    assert release.wait(3), "controlled worker release was not signalled"
                if mode == "error":
                    raise RuntimeError("PRIVATE-TRANSPORT-EXCEPTION")
                if mode == "wrong_model":
                    return {"text": text, "model": "unselected-model"}
                if mode == "extra_key":
                    return {"text": text, "model": selection["model"], "extra": "forbidden"}
                if mode == "not_dict":
                    return [text, selection["model"]]
                if mode is not None and mode.startswith("attested"):
                    reply = trial.ProviderReply(text, served_model=selection["model"],
                                                provider_request_id="req_0123456789ab", provider_message_id="msg_01")
                    attestation = reply.attestation()
                    if mode == "attested_other_model":
                        attestation["served_model"] = "unselected-model"
                    elif mode == "attested_bad_request_id":
                        attestation["provider_request_id"] = "has spaces"
                    elif mode == "attested_extra_key":
                        attestation["extra"] = "forbidden"
                    return {"text": text, "model": selection["model"], "attestation": attestation}
                return {"text": text, "model": selection["model"]}
            finally:
                if finished is not None:
                    finished.set()

    def factory(context):
        observations.contexts.append(context)
        observations.states.append(read_committed_state(context.data_dir.name)["state"])
        if mode == "factory_error":
            raise RuntimeError("PRIVATE-FACTORY-EXCEPTION")
        if mode == "not_offline":
            return SimpleNamespace(generate=lambda *_a, **_k: pytest.fail("unmarked transport dispatched"))
        return ControlledOfflineTransport()

    return factory, observations


def runner(trial, rig):
    return trial.OfflineRunner(rig.ledger, rig.root, rig.selections)


def assert_blocked(subject, call, prepared, factory):
    with pytest.raises(RuntimeError, match="quarantin"):
        subject.run(replace(call, request_id="next-request"), prepared, factory)


_LINEAGE_SEEDS = {
    P.COUNTEREXAMPLE_PROPOSAL: [P.REVIEW],
    P.COUNTEREXAMPLE_VALIDITY: [P.REVIEW, P.COUNTEREXAMPLE_PROPOSAL],
    P.CANDIDATE_RESPONSE: [
        P.REVIEW, P.COUNTEREXAMPLE_PROPOSAL, P.COUNTEREXAMPLE_VALIDITY,
    ],
}


def seeded_lineage(trial, rig, purpose, source):
    """Complete the B4 parent chain in the rig ledger; return run() lineage."""
    parent_id = evidence_sha = None
    for index, seed_purpose in enumerate(_LINEAGE_SEEDS.get(purpose, [])):
        call = frozen(trial, rig, request_id=f"lineage-{index}",
                      prepared=prepare_input(seed_purpose, source))
        if seed_purpose is P.REVIEW:
            rig.ledger.reserve(call)
        else:
            rig.ledger.reserve_with_lineage(
                call, parent_request_id=parent_id,
                evidence_sha=None if seed_purpose is P.COUNTEREXAMPLE_PROPOSAL
                else evidence_sha)
        rig.ledger.begin(call.request_id)
        rig.ledger.finish(call.request_id, "completed", {"seed": True})
        shas = rig.ledger.register_result_evidence(
            call.request_id, [{"seed": seed_purpose.value}])
        parent_id, evidence_sha = call.request_id, shas[0]
    if parent_id is None:
        return None
    return (parent_id,
            None if purpose is P.COUNTEREXAMPLE_PROPOSAL else evidence_sha)


@pytest.mark.parametrize("purpose", PURPOSES)
def test_offline_roundtrip_retains_contract_result_without_semantic_score(trial, rig, purpose):
    source = bound_source()
    prepared = prepare_input(purpose, source)
    expected = output_for(purpose, source)
    raw = json.dumps(expected, ensure_ascii=False)
    call = frozen(trial, rig, prepared=prepared)
    factory, seen = controlled(trial, rig, text=raw)
    record = runner(trial, rig).run(call, prepared, factory,
                                    lineage=seeded_lineage(trial, rig, purpose, source))
    assert record == rig.ledger.get(call.request_id)
    assert record["state"] == "completed"
    assert record["details"] == {
        "model": "gpt-fixture", "actual_effort": None, "semantic": "not_checked", "score": None,
        "raw_final": raw, "raw_sha256": sha256(raw.encode()).hexdigest(),
        "raw_bytes": len(raw.encode()), "output_contract": "valid", "parsed": expected,
    }
    assert [event["kind"] for event in record["events"]] == ["reserved", "dispatching", "completed"]
    assert seen.states == ["dispatching"]
    assert seen.arguments == [(call.prompt, json.loads(call.schema_json), json.loads(call.selection_json))]
    assert type(seen.contexts[0]) is trial.RuntimeContext
    assert seen.contexts[0].data_dir == rig.root / call.run_id / call.purpose / call.request_id
    assert seen.contexts[0].data_dir.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("raw", ["{}", "not-json", "\ud800", "é" * 32000, "é" * 32001],
                         ids=["empty_object", "bad_json", "surrogate", "64000_utf8_bytes", "64002_utf8_bytes"])
def test_model_output_classification_uses_utf8_limit_and_hash(trial, rig, raw):
    call = frozen(trial, rig)
    factory, _ = controlled(trial, rig, text=raw)
    record = runner(trial, rig).run(call, rig.prepared, factory)
    assert record["state"] == "completed"
    details = record["details"]
    assert details["score"] is None and details["semantic"] == "not_checked"
    assert details["output_contract"] == "model_output_invalid"
    assert "parsed" not in details
    if raw == "\ud800":
        assert details["raw_omitted"] == "invalid_unicode"
        assert details["raw_sha256"] is None and details["raw_bytes"] is None
        assert "raw_final" not in details
    else:
        encoded = raw.encode("utf-8")
        assert details["raw_sha256"] == sha256(encoded).hexdigest()
        assert details["raw_bytes"] == len(encoded)
        if len(encoded) > 64000:
            assert "raw_final" not in details
            assert details["raw_omitted"] == "exceeds_64000_bytes"
        else:
            assert details["raw_final"] == raw


@pytest.mark.parametrize("mode", ["error", "factory_error", "wrong_model", "extra_key", "not_dict", "not_offline",
                                  "attested_other_model", "attested_bad_request_id", "attested_extra_key"])
def test_transport_or_fixture_failures_are_invalid_and_do_not_leak_exception_text(trial, rig, mode):
    call = frozen(trial, rig)
    factory, _ = controlled(trial, rig, mode=mode)
    record = runner(trial, rig).run(call, rig.prepared, factory)
    assert record["state"] == "invalid"
    reason = ("transport_or_fixture_error" if mode in {"error", "factory_error", "not_offline"}
              else "transport_contract_or_model_mismatch")
    assert record["details"] == {"reason": reason, "score": None}
    assert "PRIVATE" not in canonical(record)


def test_a_provider_attestation_is_bound_into_the_durable_details(trial, rig):
    # release-v6 (audit 5, X1): what the provider reported serving is recorded, not the selection
    source = bound_source()
    raw = json.dumps(output_for(P.REVIEW, source), ensure_ascii=False)
    call = frozen(trial, rig)
    factory, _ = controlled(trial, rig, text=raw, mode="attested")
    record = runner(trial, rig).run(call, rig.prepared, factory)
    assert record["state"] == "completed" and record == rig.ledger.get(call.request_id)
    details = record["details"]
    assert (details["model_identity"], details["served_model"], details["provider_request_id"],
            details["provider_message_id"]) == ("provider_reported", "gpt-fixture", "req_0123456789ab", "msg_01")


@pytest.mark.parametrize("change", ["version", "account", "selection_bytes", "offline_flag", "seconds"])
def test_run_revalidates_current_choice_and_required_metadata_before_reserve(trial, rig, change):
    call = frozen(trial, rig)
    subject = runner(trial, rig)
    if change == "version":
        rig.selections.save(rig.work["id"], 1, {**rig.choice, "effort": "medium"})
    elif change == "account":
        with rig.store._connection() as db:
            db.execute("UPDATE model_catalog_account_state SET binding = 'changed-synthetic-account'")
    elif change == "selection_bytes":
        selected = json.loads(call.selection_json)
        selected["effort"] = "medium"
        call = replace(call, selection_json=canonical(selected))
    else:
        metadata = json.loads(call.metadata_json)
        metadata["execution_backend" if change == "offline_flag" else "call_seconds"] = "real" if change == "offline_flag" else True
        call = replace(call, metadata_json=canonical(metadata))
    factory, seen = controlled(trial, rig)
    with pytest.raises((ValueError, RuntimeError)):
        subject.run(call, rig.prepared, factory)
    assert seen.contexts == []
    with pytest.raises(KeyError):
        rig.ledger.get(call.request_id)


@pytest.mark.parametrize("field,value", [
    ("prompt", "{}"), ("schema_json", "{}"), ("manifest_json", "{}"),
    ("candidate_id", "forged"), ("candidate_version", "forged"),
])
def test_matching_forged_prepared_and_call_are_rejected_before_reserve(trial, rig, field, value):
    original = frozen(trial, rig)
    prepared = replace(rig.prepared, **{field: value})
    call = replace(original, **{field: value})
    factory, seen = controlled(trial, rig)
    with pytest.raises(InputContractError):
        runner(trial, rig).run(call, prepared, factory)
    assert seen.contexts == []
    with pytest.raises(KeyError):
        rig.ledger.get(call.request_id)


@pytest.mark.parametrize("field,value", [("prompt", "changed"), ("schema_json", "{}"),
                                        ("manifest_json", "{}"), ("purpose", "candidate_response"),
                                        ("candidate_id", "other"), ("candidate_version", "2")])
def test_call_must_match_exact_validated_prepared_fields(trial, rig, field, value):
    call = replace(frozen(trial, rig), **{field: value})
    factory, seen = controlled(trial, rig)
    with pytest.raises(InputContractError):
        runner(trial, rig).run(call, rig.prepared, factory)
    assert seen.contexts == []


@pytest.mark.parametrize("relation", ["same", "runtime_inside", "audit_inside", "relative", "symlink", "ancestor_symlink"])
def test_runtime_requires_absolute_separate_non_symlink_tree(trial, rig, relation, tmp_path):
    roots = {"same": rig.ledger.path.parent, "runtime_inside": rig.ledger.path.parent / "runtime",
             "audit_inside": tmp_path, "relative": Path("relative")}
    if relation == "symlink":
        link = tmp_path / "runtime-link"
        link.symlink_to(rig.root, target_is_directory=True)
        root = link
    elif relation == "ancestor_symlink":
        link = tmp_path / "parent-link"
        link.symlink_to(tmp_path / "other", target_is_directory=True)
        root = link / "runtime"
    else:
        root = roots[relation]
    with pytest.raises(ValueError):
        trial.OfflineRunner(rig.ledger, root, rig.selections)


def test_two_requests_get_fresh_private_runtime_paths(trial, rig):
    subject = runner(trial, rig)
    factory, seen = controlled(trial, rig)
    for request_id in ["request1", "request2"]:
        subject.run(frozen(trial, rig, request_id=request_id), rig.prepared, factory)
    assert len(seen.contexts) == 2
    assert seen.contexts[0].data_dir != seen.contexts[1].data_dir
    assert set(rig.ledger.path.parent.iterdir()) == {rig.ledger.path}


@pytest.mark.parametrize("fault", ["reserve", "begin", "remaining", "thread_create", "thread_start", "begin_false_get", "finish", "get"])
def test_journal_and_thread_failures_quarantine_cleanup_and_preserve_real_state(trial, rig, monkeypatch, fault):
    call = frozen(trial, rig)
    subject = runner(trial, rig)
    factory, seen = controlled(trial, rig)
    real_get = rig.ledger.get

    def broken(*_args, **_kwargs):
        raise OSError("synthetic audit or startup fault")

    if fault == "thread_create":
        monkeypatch.setattr(trial, "Thread", broken)
    elif fault == "thread_start":
        class StartFailure:
            def __init__(self, *args, **kwargs):
                pass

            def start(self):
                raise RuntimeError("synthetic start fault")
        monkeypatch.setattr(trial, "Thread", StartFailure)
    elif fault == "begin_false_get":
        monkeypatch.setattr(rig.ledger, "begin", lambda _id: False)
        monkeypatch.setattr(rig.ledger, "get", broken)
    else:
        monkeypatch.setattr(rig.ledger, fault, broken)
    with pytest.raises((OSError, RuntimeError)):
        subject.run(call, rig.prepared, factory)
    assert subject._active == {}
    assert_blocked(subject, call, rig.prepared, factory)
    if fault == "reserve":
        with pytest.raises(KeyError):
            real_get(call.request_id)
    else:
        expected = "reserved" if fault in {"begin", "begin_false_get"} else "dispatching"
        if fault == "get":
            expected = "completed"
        assert real_get(call.request_id)["state"] == expected
    if fault not in {"finish", "get"}:
        assert seen.contexts == [] and seen.arguments == []


def test_actual_reserve_commit_failure_prevents_factory(trial, rig, monkeypatch):
    call = frozen(trial, rig)
    subject = runner(trial, rig)
    factory, seen = controlled(trial, rig)
    real_transaction = rig.ledger._transaction

    @contextmanager
    def rollback_at_commit(*args, **kwargs):
        with real_transaction(*args, **kwargs) as db:
            yield db
            raise OSError("synthetic commit failure")

    monkeypatch.setattr(rig.ledger, "_transaction", rollback_at_commit)
    with pytest.raises(OSError):
        subject.run(call, rig.prepared, factory)
    monkeypatch.setattr(rig.ledger, "_transaction", real_transaction)
    assert seen.contexts == [] and subject._active == {}
    with pytest.raises(KeyError):
        rig.ledger.get(call.request_id)
    assert_blocked(subject, call, rig.prepared, factory)


def test_reserve_budget_precondition_does_not_fabricate_record(trial, rig):
    subject = runner(trial, rig)
    call = frozen(trial, rig, run_id="absent")
    factory, seen = controlled(trial, rig)
    with pytest.raises(ValueError, match="budget"):
        subject.run(call, rig.prepared, factory)
    assert seen.contexts == [] and subject._active == {}
    assert subject.run(frozen(trial, rig), rig.prepared, factory)["state"] == "completed"


def test_timeout_returns_real_journal_blocks_dispatch_and_bounds_late_event(trial, rig):
    subject = runner(trial, rig)
    call = frozen(trial, rig, call_seconds=0.04)
    entered, release, observed = threading.Event(), threading.Event(), threading.Event()
    factory, seen = controlled(trial, rig, text="PRIVATE-LATE-OUTPUT", entered=entered, release=release)
    real_observe = rig.ledger.observe

    def observe(*args):
        real_observe(*args)
        observed.set()

    rig.ledger.observe = observe
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(subject.run, call, rig.prepared, factory)
            assert entered.wait(2)
            record = pending.result(timeout=2)
        assert record["state"] == "timed_out"
        assert record["details"] == {"score": None, "remote_stop": "unconfirmed"}
        assert seen.stops[0].is_set()
        assert_blocked(subject, call, rig.prepared, factory)
    finally:
        release.set()
    assert observed.wait(2)
    record = rig.ledger.get(call.request_id)
    late = [e for e in record["events"] if e["kind"] == "late_worker_finished"]
    assert len(late) == 1
    assert late[0]["details"] == {"result_received": True, "application": "discarded",
                                    "remote_stop": "unconfirmed",
                                    "raw_retention": "not_retained_in_offline_runner"}
    assert "PRIVATE-LATE-OUTPUT" not in canonical(record)


@pytest.mark.parametrize("phase", ["begin", "remaining", "done_before_poll"])
def test_every_timeout_branch_quarantines_even_when_worker_already_done(trial, rig, monkeypatch, phase):
    call = frozen(trial, rig, call_seconds=1)
    subject = runner(trial, rig)
    factory, seen = controlled(trial, rig)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(trial, "monotonic", lambda: clock.now)
    if phase == "begin":
        real_reserve = rig.ledger.reserve

        def reserve_then_expire(value):
            real_reserve(value)
            rig.ledger.clock = lambda: 10**12

        monkeypatch.setattr(rig.ledger, "reserve", reserve_then_expire)
    elif phase == "remaining":
        monkeypatch.setattr(rig.ledger, "remaining", lambda _run: 0)
    else:
        real_factory = factory

        def factory(context):
            transport = real_factory(context)
            real_generate = transport.generate

            def finish_after_deadline(*args, **kwargs):
                result = real_generate(*args, **kwargs)
                clock.now += 2
                return result

            transport.generate = finish_after_deadline
            return transport

        class InlineThread:
            def __init__(self, *, target, daemon):
                assert daemon is True
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(trial, "Thread", InlineThread)
    record = subject.run(call, rig.prepared, factory)
    assert record["state"] == "timed_out"
    assert record == rig.ledger.get(call.request_id)
    assert subject._active == {}
    assert_blocked(subject, call, rig.prepared, factory)
    if phase != "done_before_poll":
        assert seen.contexts == []


def test_cancel_commits_before_signalling_and_conservatively_quarantines(trial, rig, monkeypatch):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    entered, release, observed = threading.Event(), threading.Event(), threading.Event()
    factory, seen = controlled(trial, rig, entered=entered, release=release)
    real_cancel, real_observe = rig.ledger.cancel, rig.ledger.observe

    def cancel(request_id):
        assert not seen.stops[0].is_set()
        changed = real_cancel(request_id)
        assert rig.ledger.get(request_id)["state"] == "cancelled"
        assert not seen.stops[0].is_set()
        return changed

    def observe(*args):
        real_observe(*args)
        observed.set()

    monkeypatch.setattr(rig.ledger, "cancel", cancel)
    monkeypatch.setattr(rig.ledger, "observe", observe)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(subject.run, call, rig.prepared, factory)
            assert entered.wait(2)
            assert subject.cancel(call.request_id) is True
            assert seen.stops[0].is_set()
            record = pending.result(timeout=2)
        assert record["state"] == "cancelled"
        assert record["details"] == {"score": None, "remote_stop": "unconfirmed"}
        assert subject._active == {}
        assert_blocked(subject, call, rig.prepared, factory)
    finally:
        release.set()
    assert observed.wait(2)
    assert rig.ledger.get(call.request_id)["state"] == "cancelled"


def test_cancel_write_failure_stops_run_without_publishing_completion(trial, rig, monkeypatch):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    entered, release, observed = threading.Event(), threading.Event(), threading.Event()
    factory, seen = controlled(trial, rig, entered=entered, release=release)
    real_transaction, real_observe = rig.ledger._transaction, rig.ledger.observe

    @contextmanager
    def rollback_at_commit(*args, **kwargs):
        with real_transaction(*args, **kwargs) as db:
            yield db
            if kwargs.get("write", True):
                raise OSError("synthetic cancel commit failure")

    def observe(*args):
        real_observe(*args)
        observed.set()

    monkeypatch.setattr(rig.ledger, "observe", observe)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(subject.run, call, rig.prepared, factory)
            assert entered.wait(2)
            monkeypatch.setattr(rig.ledger, "_transaction", rollback_at_commit)
            with pytest.raises(OSError, match="cancel commit"):
                subject.cancel(call.request_id)
            monkeypatch.setattr(rig.ledger, "_transaction", real_transaction)
            assert seen.stops[0].is_set()
            release.set()
            with pytest.raises(RuntimeError, match="audit"):
                pending.result(timeout=2)
        assert subject._active == {}
        assert rig.ledger.get(call.request_id)["state"] == "dispatching"
        assert_blocked(subject, call, rig.prepared, factory)
    finally:
        monkeypatch.setattr(rig.ledger, "_transaction", real_transaction)
        release.set()
    assert observed.wait(2)
    assert [e["kind"] for e in rig.ledger.get(call.request_id)["events"]] == [
        "reserved", "dispatching", "late_worker_finished"]


def test_successful_active_cancel_after_worker_done_still_quarantines(trial, rig, monkeypatch):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    factory, seen = controlled(trial, rig)

    class CancelAfterDoneThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()
            assert subject.cancel(call.request_id) is True

    monkeypatch.setattr(trial, "Thread", CancelAfterDoneThread)
    record = subject.run(call, rig.prepared, factory)
    assert record["state"] == "cancelled"
    assert seen.stops[0].is_set()
    assert_blocked(subject, call, rig.prepared, factory)


def test_completed_terminal_wins_over_later_cancellation(trial, rig):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    factory, _ = controlled(trial, rig)
    completed = subject.run(call, rig.prepared, factory)
    assert subject.cancel(call.request_id) is False
    assert subject.cancel("not-registered") is False
    assert rig.ledger.get(call.request_id) == completed
    assert subject.run(frozen(trial, rig, request_id="request2"), rig.prepared, factory)["state"] == "completed"


@pytest.mark.parametrize("changed", [False, True])
def test_duplicate_request_never_reaches_factory_or_changes_first_record(trial, rig, changed):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    factory, seen = controlled(trial, rig)
    original = subject.run(call, rig.prepared, factory)
    duplicate = replace(call, metadata_json=canonical({**json.loads(call.metadata_json),
                                                      "call_seconds": 1})) if changed else call
    with pytest.raises(ValueError, match="already used"):
        subject.run(duplicate, rig.prepared, factory)
    assert len(seen.contexts) == len(seen.arguments) == 1
    assert rig.ledger.get(call.request_id) == original


def test_runner_serializes_requests_before_reservation(trial, rig, monkeypatch):
    subject = runner(trial, rig)
    first = frozen(trial, rig)
    second = frozen(trial, rig, request_id="request2")
    entered, release, second_attempted = threading.Event(), threading.Event(), threading.Event()
    factory, seen = controlled(trial, rig, entered=entered, release=release)
    actual_lock = subject._lock

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == "second-offline-request":
                second_attempted.set()
            return actual_lock.__enter__()

        def __exit__(self, *args):
            return actual_lock.__exit__(*args)

    monkeypatch.setattr(subject, "_lock", ObservedLock())

    def next_request():
        threading.current_thread().name = "second-offline-request"
        return subject.run(second, rig.prepared, factory)

    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(subject.run, first, rig.prepared, factory)
        try:
            assert entered.wait(2)
            next_pending = pool.submit(next_request)
            assert second_attempted.wait(2)
            with pytest.raises(KeyError):
                rig.ledger.get(second.request_id)
            assert len(seen.contexts) == len(seen.arguments) == 1
        finally:
            release.set()
        assert pending.result(timeout=2)["state"] == "completed"
        assert next_pending.result(timeout=2)["state"] == "completed"
    assert len(seen.contexts) == len(seen.arguments) == 2


@pytest.mark.parametrize("stage", ["active_creation", "active_registration"])
def test_post_reserve_registration_faults_quarantine_without_starting_worker(trial, rig, monkeypatch, stage):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    factory, seen = controlled(trial, rig)

    def broken(*args, **kwargs):
        raise RuntimeError("synthetic registration failure")

    if stage == "active_creation":
        monkeypatch.setattr(trial, "_Active", broken)
    else:
        class BrokenRegistration(dict):
            __setitem__ = broken
        subject._active = BrokenRegistration()
    with pytest.raises(RuntimeError, match="registration"):
        subject.run(call, rig.prepared, factory)
    assert subject._active == {}
    assert seen.contexts == [] and seen.arguments == []
    assert rig.ledger.get(call.request_id)["state"] == "reserved"
    assert_blocked(subject, call, rig.prepared, factory)


@pytest.mark.parametrize("boundary", ["before_path", "before_factory", "before_generate"])
def test_worker_checks_deadline_at_each_dispatch_boundary(trial, rig, monkeypatch, boundary):
    subject = runner(trial, rig)
    call = frozen(trial, rig, call_seconds=1)
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(trial, "monotonic", lambda: clock.now)
    factory, seen = controlled(trial, rig)
    original_runtime = subject._runtime_context

    class InlineThread:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            if boundary == "before_path":
                clock.now += 2
            self.target()

    monkeypatch.setattr(trial, "Thread", InlineThread)
    if boundary == "before_factory":
        def context_then_expire(value):
            context = original_runtime(value)
            clock.now += 2
            return context
        monkeypatch.setattr(subject, "_runtime_context", context_then_expire)
    elif boundary == "before_generate":
        original_factory = factory

        def factory(context):
            transport = original_factory(context)
            clock.now += 2
            return transport

    record = subject.run(call, rig.prepared, factory)
    assert record["state"] == "timed_out"
    assert seen.arguments == []
    assert len(seen.contexts) == (1 if boundary == "before_generate" else 0)
    if boundary == "before_path":
        assert not rig.root.exists()
    late = next(event for event in record["events"] if event["kind"] == "late_worker_finished")
    assert late["details"]["result_received"] is False
    assert_blocked(subject, call, rig.prepared, factory)


def test_late_observation_failure_cannot_prevent_done_or_fabricate_durable_event(trial, rig, monkeypatch):
    subject = runner(trial, rig)
    call = frozen(trial, rig, call_seconds=0.04)
    entered, release = threading.Event(), threading.Event()
    factory, _ = controlled(trial, rig, entered=entered, release=release)

    def broken_observe(*args, **kwargs):
        raise OSError("synthetic observation commit failure")

    monkeypatch.setattr(rig.ledger, "observe", broken_observe)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(subject.run, call, rig.prepared, factory)
        try:
            assert entered.wait(2)
            active = subject._active[call.request_id]
            assert pending.result(timeout=2)["state"] == "timed_out"
        finally:
            release.set()
        assert active.done.wait(2)
    assert active.audit_fault is True
    assert [event["kind"] for event in rig.ledger.get(call.request_id)["events"]] == [
        "reserved", "dispatching", "timed_out"]
    assert_blocked(subject, call, rig.prepared, factory)


@pytest.mark.parametrize("object_type", ["prepared_subclass", "call_subclass", "wrong_prepared"])
def test_runner_rejects_non_exact_contract_classes(trial, rig, object_type):
    call, prepared = frozen(trial, rig), rig.prepared
    if object_type == "prepared_subclass":
        class DerivedPrepared(type(prepared)):
            pass
        prepared = DerivedPrepared(**prepared.__dict__)
    elif object_type == "call_subclass":
        class DerivedCall(FrozenCall):
            pass
        call = DerivedCall(**call.as_dict())
    else:
        prepared = SimpleNamespace(**prepared.__dict__)
    factory, seen = controlled(trial, rig)
    with pytest.raises(InputContractError):
        runner(trial, rig).run(call, prepared, factory)
    assert seen.contexts == []


@pytest.mark.parametrize("replacement", [None, 1, {}, ["text"]])
def test_non_text_transport_field_is_invalid_without_scoring(trial, rig, replacement):
    factory, _ = controlled(trial, rig, text=replacement)
    record = runner(trial, rig).run(frozen(trial, rig), rig.prepared, factory)
    assert record["state"] == "invalid"
    assert record["details"] == {"reason": "transport_contract_or_model_mismatch", "score": None}


@pytest.mark.parametrize("location", ["runtime_root", "request_directory"])
def test_runtime_symlink_recheck_prevents_factory(trial, rig, location):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    factory, seen = controlled(trial, rig)
    if location == "runtime_root":
        rig.root.symlink_to(rig.root.parent / "other-runtime", target_is_directory=True)
        with pytest.raises(ValueError):
            subject.run(call, rig.prepared, factory)
        with pytest.raises(KeyError):
            rig.ledger.get(call.request_id)
    else:
        path = rig.root / call.run_id / call.purpose / call.request_id
        path.parent.mkdir(parents=True)
        path.symlink_to(rig.root.parent / "other-runtime", target_is_directory=True)
        assert subject.run(call, rig.prepared, factory)["state"] == "invalid"
    assert seen.contexts == []


def test_existing_runtime_directory_is_never_reused(trial, rig):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    path = rig.root / call.run_id / call.purpose / call.request_id
    path.mkdir(parents=True)
    factory, seen = controlled(trial, rig)
    assert subject.run(call, rig.prepared, factory)["state"] == "invalid"
    assert seen.contexts == []


def test_cancel_audit_failure_during_validation_blocks_later_dispatch(trial, rig, monkeypatch):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    factory, seen = controlled(trial, rig)
    entered, release = threading.Event(), threading.Event()
    real_validate = subject._validate_call

    def paused_validation(*args):
        seconds = real_validate(*args)
        entered.set()
        assert release.wait(3)
        return seconds

    def failed_cancel(_request_id):
        raise OSError("synthetic concurrent cancel audit failure")

    monkeypatch.setattr(subject, "_validate_call", paused_validation)
    monkeypatch.setattr(rig.ledger, "cancel", failed_cancel)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(subject.run, call, rig.prepared, factory)
        try:
            assert entered.wait(2)
            with pytest.raises(OSError):
                subject.cancel("not-yet-registered")
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="quarantin"):
            pending.result(timeout=2)
    assert subject._active == {} and seen.contexts == []
    with pytest.raises(KeyError):
        rig.ledger.get(call.request_id)


def test_cancel_audit_failure_for_another_id_stops_active_publication(trial, rig, monkeypatch):
    subject = runner(trial, rig)
    call = frozen(trial, rig)
    entered, release = threading.Event(), threading.Event()
    factory, seen = controlled(trial, rig, entered=entered, release=release)

    def failed_cancel(_request_id):
        raise OSError("synthetic shared audit failure")

    monkeypatch.setattr(rig.ledger, "cancel", failed_cancel)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(subject.run, call, rig.prepared, factory)
        try:
            assert entered.wait(2)
            active = subject._active[call.request_id]
            with pytest.raises(OSError):
                subject.cancel("different-request")
            assert seen.stops[0].is_set()
        finally:
            release.set()
        with pytest.raises(RuntimeError, match="audit"):
            pending.result(timeout=2)
        assert active.done.wait(2)
    assert rig.ledger.get(call.request_id)["state"] == "dispatching"
