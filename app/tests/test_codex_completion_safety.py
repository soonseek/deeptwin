"""Controlled transport tests: no installed provider, credentials, or model calls."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app import codex_understanding
from app.codex_rpc import _MAX_NOTIFICATIONS
from app.tests.test_codex_understanding import choice, model
from app.tests.test_understanding import output, terminal
from app.storage import Store
from app.understanding import MESSAGES, ModelError, Understanding


def completed():
    return {'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': {
        'id': 'turn-1', 'status': 'completed', 'items': [
            {'type': 'agentMessage', 'id': 'answer', 'phase': 'final_answer', 'text': '{}'}]}}}


def forbidden():
    return {'method': 'item/started', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1',
            'item': {'type': 'commandExecution', 'id': 'forbidden'}}}


def run(subject):
    return subject.generate('synthetic review input', {'type': 'object'},
                            SimpleNamespace(is_set=lambda: False), selection=choice())


@pytest.mark.parametrize('event', [forbidden(),
    {'method': 'turn/plan/updated', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'plan': []}}])
@pytest.mark.parametrize('after_completion', [False, True])
def test_entire_completion_batch_rejects_forbidden_activity(tmp_path, monkeypatch, event, after_completion):
    batch = [completed(), event] if after_completion else [event, completed()]
    subject, created = model(tmp_path, monkeypatch, notifications=[batch])
    with pytest.raises(ModelError) as caught:
        run(subject)
    assert caught.value.reason == 'isolation_violation'
    assert ('turn/interrupt', {'threadId': 'thread-1', 'turnId': 'turn-1'}) in created[0].calls
    assert created[0].closed


def test_model_reroute_after_completed_in_same_batch_is_not_success(tmp_path, monkeypatch):
    event = {'method': 'model/rerouted', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1',
             'fromModel': choice()['model'], 'toModel': 'other'}}
    subject, created = model(tmp_path, monkeypatch, notifications=[[completed(), event]])
    with pytest.raises(ModelError) as caught:
        run(subject)
    assert caught.value.reason == 'model_mismatch'
    assert created[0].closed


@pytest.mark.parametrize('lost_event', [False, True])
def test_sticky_violation_survives_real_notification_queue_eviction(tmp_path, monkeypatch, lost_event):
    subject, created = model(tmp_path, monkeypatch)
    factory = subject.rpc_factory

    def make(*args, **kwargs):
        rpc = factory(*args, **kwargs)
        receiver = codex_understanding.GenerationRPC(['/never-executed'], cwd=tmp_path)

        def start(_params, current):
            if lost_event:
                receiver._receive(forbidden())
            for _ in range(_MAX_NOTIFICATIONS + 1):
                receiver._receive({'method': 'thread/tokenUsage/updated', 'params': {}})
            receiver._receive(completed())
            current.isolation_violation = receiver.isolation_violation
            current.notifications.append(receiver.drain_notifications())
            return {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': []}}

        rpc.script['turn/start'] = start
        return rpc

    subject.rpc_factory = make
    with pytest.raises(ModelError) as caught:
        run(subject)
    assert caught.value.reason == 'isolation_violation'
    assert created[0].closed


def test_post_transfer_failure_does_not_claim_input_was_never_sent():
    assert 'isolation_violation' in MESSAGES
    assert '보내지 않았' not in MESSAGES['isolation_violation']
    assert '결과' in MESSAGES['isolation_violation']
    assert '보내지 않았' in MESSAGES['isolation_unavailable']


def final_item(**changes):
    params = {'threadId': 'thread-1', 'turnId': 'turn-1', 'item': {
        'type': 'agentMessage', 'id': 'answer', 'phase': 'final_answer', 'text': '{}'}}
    params.update(changes)
    return {'method': 'item/completed', 'params': params}


def empty_completion(status='completed'):
    event = completed()
    event['params']['turn'].update(items=[], itemsView='notLoaded', status=status)
    return event


@pytest.mark.parametrize('same_batch', [False, True])
def test_official_not_loaded_completion_uses_exact_completed_final_item(tmp_path, monkeypatch, same_batch):
    # 0.144.4 emit_turn_completed_with_status emits items:[], itemsView:notLoaded.
    batches = [[final_item(), empty_completion()]] if same_batch else [[final_item()], [empty_completion()]]
    subject, created = model(tmp_path, monkeypatch, notifications=batches)
    assert run(subject) == {'text': '{}', 'model': choice()['model']}
    assert created[0].closed


@pytest.mark.parametrize('events', [
    [final_item(threadId='other')],
    [final_item(turnId='other')],
    [{'method': 'item/agentMessage/delta', 'params': {
        'threadId': 'thread-1', 'turnId': 'turn-1', 'itemId': 'answer', 'delta': '{}'}}],
    [final_item(), final_item(item={
        'type': 'agentMessage', 'id': 'answer', 'phase': 'final_answer', 'text': '{"changed":true}'})],
    [final_item(), final_item(item={
        'type': 'agentMessage', 'id': 'second-answer', 'phase': 'final_answer', 'text': '{}'})],
])
def test_unbound_partial_or_ambiguous_items_never_become_final_output(tmp_path, monkeypatch, events):
    subject, _ = model(tmp_path, monkeypatch, notifications=[events, [empty_completion()]])
    with pytest.raises(ModelError):
        run(subject)


@pytest.mark.parametrize('status', ['failed', 'interrupted'])
def test_completed_final_item_cannot_override_terminal_failure(tmp_path, monkeypatch, status):
    subject, _ = model(tmp_path, monkeypatch, notifications=[[final_item()], [empty_completion(status)]])
    with pytest.raises(ModelError):
        run(subject)


def test_assembled_response_keeps_exact_raw_output_source_revision_and_actual_model(tmp_path, monkeypatch):
    store = Store(tmp_path / 'data')
    source = '합성 검토용 회의 요약을 준비합니다.'
    work = store.create_work(source)
    raw = json.dumps(output(source), ensure_ascii=False, indent=2)
    event = final_item(item={'type': 'agentMessage', 'id': 'answer',
                             'phase': 'final_answer', 'text': raw})
    subject, _ = model(tmp_path, monkeypatch, notifications=[[event], [empty_completion()]])
    # Fixed selection belongs to this controlled provider fixture; production
    # model-selection validation has its own actual-store API regressions.
    provider = SimpleNamespace(generate=lambda prompt, schema, cancel:
        subject.generate(prompt, schema, cancel, selection=choice()))
    with Understanding(store, model_factory=lambda: provider) as service:
        request = service.create(work['id'], 1, str(uuid4()), True)
        record = terminal(service, work['id'])
    assert record['status'] == 'succeeded'
    assert record['revision'] == 1 and record['model'] == choice()['model']
    assert record['result'] == output(source)
    with store._connection() as db:
        row = db.execute('SELECT input_json, response_json FROM understanding_requests WHERE id=?',
                         (request['id'],)).fetchone()
    assert row['response_json'] == raw
    audit = json.loads(row['input_json'])
    assert source in json.dumps(audit['envelope'], ensure_ascii=False)
    assert source in audit['prompt']
    assert store.get_work(work['id']) == work
    events = store.events(work['id'])
    assert raw not in json.dumps(events, ensure_ascii=False)
    assert events[-1]['metadata']['actual_model'] == choice()['model']
