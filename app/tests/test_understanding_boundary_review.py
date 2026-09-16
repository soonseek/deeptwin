"""Independent persistence/HTTP probes; no real provider is ever constructed."""

import hashlib
import json
import sqlite3
import threading
import time
from uuid import uuid4

import pytest
from app.tests.local_http import LocalTestClient as TestClient

from app.server import create_development_app as create_app
from app.storage import Store
from app.understanding import PROMPT_VERSION, Understanding
from app.tests.test_model_selection_api import CatalogBoundary
from app.tests.test_model_selection import choice


class ControlledModel:
    def __init__(self, text='회의 자료', *, blocked=False, error=None):
        self.text, self.error = text, error
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = []
        self.schemas = []
        if not blocked:
            self.release.set()

    def generate(self, prompt, schema, cancel, *, selection=None):
        self.calls.append(prompt)
        self.schemas.append(schema)
        self.entered.set()
        assert self.release.wait(3), 'Test must release its controlled model'
        if self.error:
            raise self.error
        return {'model': selection['model'] if selection else 'controlled-review-model', 'text': json.dumps({
            'summary': {'text': self.text, 'evidence': [
                {'source_id': 'work-description', 'quote': self.text}]},
            'deliverables': [], 'constraints': [], 'open_questions': [], 'assumptions': []})}


def settled(service):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with service._lock:
            if not service._jobs:
                return
        time.sleep(.005)
    pytest.fail('Worker did not settle')


def test_uuid_key_cannot_be_reassigned_to_other_work_or_revision(tmp_path):
    store = Store(tmp_path)
    first, other = store.create_work('회의 자료'), store.create_work('다른 업무')
    model, key = ControlledModel(), str(uuid4())
    with Understanding(store, lambda: model) as service:
        record = service.create(first['id'], 1, key, True)
        settled(service)
        before = store.events()
        with pytest.raises(ValueError):
            service.create(other['id'], 1, key, True)
        store.update_work(first['id'], '수정 업무', 1)
        with pytest.raises(ValueError):
            service.create(first['id'], 2, key, True)
        assert service.list_for(other['id']) == []
        assert len(model.calls) == 1
        assert service.create(first['id'], 1, key, True)['id'] == record['id']
        assert len(store.events()) == len(before) + 1


@pytest.mark.parametrize('active', ['queued', 'running'])
def test_restart_marks_persisted_active_failed_without_replay(tmp_path, active):
    store, model, key = Store(tmp_path), ControlledModel(), str(uuid4())
    work = store.create_work('회의 자료')
    with Understanding(store, lambda: model) as original:
        original.create(work['id'], 1, key, True)
        settled(original)
    # A persisted active row is the only state an abruptly terminated worker leaves.
    with store._connection() as db:
        record = json.loads(db.execute('SELECT payload FROM understanding_requests').fetchone()[0])
        record.update(status=active, result=None, model=None)
        db.execute('UPDATE understanding_requests SET payload=?, response_json=NULL', (json.dumps(record),))
    forbidden = []
    with Understanding(store, lambda: forbidden.append(True)) as restored:
        recovered = restored.list_for(work['id'])[0]
        assert recovered['status'] == 'failed' and recovered['reason'] == 'interrupted'
        assert restored.create(work['id'], 1, key, True) == recovered
        assert not forbidden and recovered['result'] is None
        assert store.get_work(work['id']) == work


@pytest.mark.parametrize('cancel_first', [True, False])
def test_cancel_and_completion_preserve_first_committed_terminal_state(tmp_path, cancel_first):
    store, model = Store(tmp_path), ControlledModel(blocked=True)
    work = store.create_work('회의 자료')
    with Understanding(store, lambda: model) as service:
        request = service.create(work['id'], 1, str(uuid4()), True)
        assert model.entered.wait(2)
        if cancel_first:
            assert service.cancel(work['id'], request['id'])['status'] == 'cancelled'
        model.release.set()
        settled(service)
        record = service.cancel(work['id'], request['id'])
        assert record['status'] == ('cancelled' if cancel_first else 'succeeded')
        assert (record['result'] is None) == cancel_first
        terminal_events = [e['kind'] for e in store.events() if e['kind'] in
                           {'understanding_cancelled', 'understanding_succeeded'}]
        assert terminal_events == ['understanding_' + record['status']]


def test_deferred_commit_failure_does_not_call_model_or_leave_busy_worker(tmp_path):
    store, model = Store(tmp_path), ControlledModel()
    work = store.create_work('회의 자료')
    service = Understanding(store, lambda: model)
    with store._connection() as db:
        db.executescript('''
            CREATE TABLE review_parent(id INTEGER PRIMARY KEY);
            CREATE TABLE review_deferred(id INTEGER REFERENCES review_parent(id)
                DEFERRABLE INITIALLY DEFERRED);
            CREATE TRIGGER review_fail_commit AFTER INSERT ON events
                WHEN NEW.kind = 'understanding_queued' BEGIN
                INSERT INTO review_deferred VALUES (999); END;
        ''')
    with pytest.raises(sqlite3.IntegrityError):
        service.create(work['id'], 1, str(uuid4()), True)
    assert not model.calls
    assert service.list_for(work['id']) == []
    # Failed COMMIT must not strand an unstarted Thread in the live registry.
    assert not service._jobs
    service.close()


def test_cancel_storage_failure_does_not_signal_uncommitted_cancellation(tmp_path):
    store, model = Store(tmp_path), ControlledModel(blocked=True)
    work = store.create_work('회의 자료')
    with Understanding(store, lambda: model) as service:
        request = service.create(work['id'], 1, str(uuid4()), True)
        assert model.entered.wait(2)
        with store._connection() as db:
            db.executescript('''CREATE TRIGGER review_cancel_failure BEFORE INSERT ON events
                WHEN NEW.kind='understanding_cancelled' BEGIN
                SELECT RAISE(ABORT, 'controlled storage failure'); END;''')
        with pytest.raises(sqlite3.IntegrityError):
            service.cancel(work['id'], request['id'])
        with store._connection() as db:
            db.execute('DROP TRIGGER review_cancel_failure')
        model.release.set()
        settled(service)
        assert service.list_for(work['id'])[0]['status'] == 'succeeded'


def test_frozen_envelope_hash_version_and_original_blob_remain_auditable(tmp_path):
    store, model = Store(tmp_path), ControlledModel(blocked=True)
    work = store.create_work('\n회의 자료')
    raw = '\n첨부 원문\r\n그대로'.encode()
    attachment = store.add_file(work['id'], '자료.txt', raw, 'text/plain', 1)
    frozen = store.get_revision(work['id'], 2)
    with Understanding(store, lambda: model) as service:
        request = service.create(work['id'], 2, str(uuid4()), True)
        assert model.entered.wait(2)
        store.update_work(work['id'], '나중 내용', 2)
        model.release.set()
        settled(service)
        with store._connection() as db:
            row = db.execute('SELECT * FROM understanding_requests').fetchone()
        bundle = json.loads(row['input_json'])
        value = bundle['envelope']
        assert value['revision'] == 2 and value['sources'][0]['text'] == '\n회의 자료'
        assert value['sources'][1]['text'] == raw.decode()
        assert bundle['prompt'] == model.calls[0]
        assert bundle['output_schema'] == model.schemas[0]
        encoded_envelope = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
        assert request['input_sha256'] == hashlib.sha256(encoded_envelope).hexdigest()
        assert request['prompt_version'] == PROMPT_VERSION
        assert store.get_revision(work['id'], 2) == frozen
        assert store.read_file(work['id'], attachment['id'])[1] == raw
        for event in store.events():
            if event['kind'].startswith('understanding_'):
                assert event['metadata']['revision'] == 2
                assert event['metadata']['input_sha256'] == request['input_sha256']
                assert event['metadata']['prompt_version'] == PROMPT_VERSION
                assert '회의 자료' not in json.dumps(event, ensure_ascii=False)
                assert '첨부 원문' not in json.dumps(event, ensure_ascii=False)


def test_http_get_is_read_only_and_mutations_require_same_origin_csrf(tmp_path):
    constructed = []
    app = create_app(tmp_path, understanding_model_factory=lambda: constructed.append(True))
    work = app.state.store.create_work('회의 자료')
    route = f'/api/works/{work["id"]}/understanding-requests'
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        token = client.csrf_token
        before = app.state.store.events()
        for path in [route, '/api/bootstrap', '/api/providers', f'/api/works/{work["id"]}']:
            assert client.get(path).status_code == 200
        body = {'revision': 1, 'request_key': str(uuid4()), 'allow_transfer': True}
        for headers in [{}, {'x-csrf-token': 'wrong'},
                        {'x-csrf-token': token, 'origin': 'https://evil.invalid'},
                        {'x-csrf-token': token, 'sec-fetch-site': 'cross-site'}]:
            assert client.post(route, json=body, headers=headers).status_code == 403
            assert client.post(route + '/' + str(uuid4()) + '/cancel', json={}, headers=headers).status_code == 403
        assert not constructed and app.state.understanding.list_for(work['id']) == []
        assert app.state.store.events() == before


def test_http_provider_error_never_returns_raw_exception_or_source_body(tmp_path):
    secret = 'PRIVATE-ORIGINAL-BODY-987 auth-token=never-return'
    model = ControlledModel(error=RuntimeError(secret))
    app = create_app(tmp_path, understanding_model_factory=lambda: model,
                     model_catalog_factory=lambda store, codex: CatalogBoundary())
    work = app.state.store.create_work(secret)
    app.state.model_selections.save(work['id'], 0, choice())
    route = f'/api/works/{work["id"]}/understanding-requests'
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        token = client.csrf_token
        response = client.post(route, json={'revision': 1, 'request_key': str(uuid4()),
                               'allow_transfer': True, 'model_selection_version': 1}, headers={'x-csrf-token': token})
        assert response.status_code == 202 and secret not in response.text
        settled(app.state.understanding)
        response = client.get(route)
        record = response.json()[0]
        assert record['status'] == 'failed' and record['reason'] == 'provider_unavailable'
        assert record['result'] is None and secret not in response.text
        assert secret not in json.dumps(app.state.store.events(), ensure_ascii=False)


def test_worker_does_not_construct_model_when_running_event_cannot_be_saved(tmp_path):
    store, constructed = Store(tmp_path), []
    work = store.create_work('회의 자료')
    with Understanding(store, lambda: constructed.append(True)) as service:
        with store._connection() as db:
            db.executescript('''CREATE TRIGGER review_running_failure BEFORE INSERT ON events
                WHEN NEW.kind='understanding_running' BEGIN
                SELECT RAISE(ABORT, 'private-storage-location'); END;''')
        service.create(work['id'], 1, str(uuid4()), True)
        settled(service)
        record = service.list_for(work['id'])[0]
        assert not constructed
        assert record['status'] == 'failed'
        assert 'private-storage-location' not in json.dumps(record)


def test_http_storage_error_does_not_send_input_or_expose_storage_exception(tmp_path):
    constructed = []
    app = create_app(tmp_path, understanding_model_factory=lambda: constructed.append(True),
                     model_catalog_factory=lambda store, codex: CatalogBoundary())
    work = app.state.store.create_work('private-source-content')
    app.state.model_selections.save(work['id'], 0, choice())
    route = f'/api/works/{work["id"]}/understanding-requests'
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        token = client.csrf_token
        before = app.state.store.events()
        with app.state.store._connection() as db:
            db.executescript('''CREATE TRIGGER review_queued_failure BEFORE INSERT ON events
                WHEN NEW.kind='understanding_queued' BEGIN
                SELECT RAISE(ABORT, 'private-source-content /private/db auth=secret'); END;''')
        response = client.post(route, json={'revision': 1, 'request_key': str(uuid4()),
                               'allow_transfer': True, 'model_selection_version': 1}, headers={'x-csrf-token': token})
        assert response.status_code == 503
        assert 'private' not in response.text and 'auth=secret' not in response.text
        assert not constructed and app.state.understanding.list_for(work['id']) == []
        assert app.state.store.events() == before
        assert app.state.store.get_work(work['id']) == work


def test_http_cancel_cannot_target_another_works_request(tmp_path):
    model = ControlledModel(blocked=True)
    app = create_app(tmp_path, understanding_model_factory=lambda: model,
                     model_catalog_factory=lambda store, codex: CatalogBoundary())
    work, other = app.state.store.create_work('회의 자료'), app.state.store.create_work('다른 업무')
    app.state.model_selections.save(work['id'], 0, choice())
    route = f'/api/works/{work["id"]}/understanding-requests'
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        token = client.csrf_token
        headers = {'x-csrf-token': token}
        request = client.post(route, json={'revision': 1, 'request_key': str(uuid4()),
                              'allow_transfer': True, 'model_selection_version': 1}, headers=headers).json()
        assert model.entered.wait(2)
        wrong_route = f'/api/works/{other["id"]}/understanding-requests/{request["id"]}/cancel'
        assert client.post(wrong_route, json={}, headers=headers).status_code == 404
        assert client.get(route).json()[0]['status'] == 'running'
        model.release.set()
        settled(app.state.understanding)
        assert client.get(route).json()[0]['status'] == 'succeeded'
        assert app.state.store.get_work(work['id']) == work
        assert app.state.store.get_work(other['id']) == other
