import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest

from app.model_catalog import ModelCatalog
from app.storage import Store


class CodexFixture:
    def __init__(self, store):
        self.store = store
        self.reads = 0
        self.binding_reads = 0
        self.binding = 'session-1:account-1'
        self.state = 'connected'
        self.billing = 'subscription'
        self.pages = [
            {'data': [{
                'id': 'gpt-fixture', 'model': 'gpt-fixture',
                'displayName': 'GPT Fixture', 'hidden': False, 'isDefault': True,
                'defaultReasoningEffort': 'medium',
                'supportedReasoningEfforts': [
                    {'reasoningEffort': 'low', 'description': '빠르게'},
                    {'reasoningEffort': 'medium', 'description': '균형'},
                ],
                'inputModalities': ['text'],
            }], 'nextCursor': 'page-2'},
            {'data': [{
                'id': 'gpt-second', 'model': 'gpt-second',
                'displayName': 'GPT Second', 'hidden': False, 'isDefault': False,
                'defaultReasoningEffort': 'high',
                'supportedReasoningEfforts': [
                    {'reasoningEffort': 'high', 'description': '깊게'},
                ],
                'inputModalities': ['text', 'image'],
            }], 'nextCursor': None},
        ]

    def snapshot(self):
        return {'connection': {'state': self.state}, 'billing': self.billing}

    def read_model_catalog(self):
        self.reads += 1
        if self.state != 'connected' or self.billing != 'subscription':
            raise PermissionError('not subscription')
        with self.store._connection() as db:
            db.execute('''INSERT INTO model_catalog_account_state VALUES (?, ?)
                ON CONFLICT(provider) DO UPDATE SET binding = excluded.binding''',
                       ('codex', self.binding))
        return {'pages': self.pages, 'binding': self.binding}

    def catalog_binding(self):
        self.binding_reads += 1
        return self.binding if self.state == 'connected' and self.billing == 'subscription' else None


@pytest.fixture
def catalog(tmp_path):
    store = Store(tmp_path)
    codex = CodexFixture(store)
    return ModelCatalog(store, codex), codex, store


def test_snapshot_is_lazy_and_claude_never_fabricates_a_public_model_list(catalog):
    subject, codex, _ = catalog

    value = subject.snapshot('codex')
    claude = subject.snapshot('claude')

    assert value['provider'] == 'codex' and value['mode'] == 'subscription'
    assert value['auth_mode'] == 'chatgpt' and value['billing'] == 'subscription'
    assert value['status'] == 'unqueried'
    assert value['message'] == '새로고침을 눌러 현재 Codex 모델 목록을 확인하세요.'
    assert value['catalog_id'] is value['fetched_at'] is None
    assert value['models'] == [] and value['execution_ready'] is False
    assert claude['status'] == 'unavailable' and claude['models'] == []
    assert claude['mode'] == 'api' and 'API' in claude['message']
    assert '미구현' not in claude['message']
    assert '사전 승인' not in claude['message'] and '구독' not in claude['message']
    assert codex.reads == 0


def test_explicit_refresh_normalizes_all_pages_and_persists_immutable_snapshot(catalog):
    subject, codex, store = catalog

    value = subject.refresh('codex')

    assert codex.reads == 1
    assert value['status'] == 'ready' and value['execution_ready'] is False
    assert value['catalog_id'] and value['fetched_at']
    expected = [{
        'model': 'gpt-fixture', 'display_name': 'GPT Fixture',
        'default_reasoning_effort': 'medium',
        'reasoning_efforts': [
            {'value': 'low', 'label': '빠르게'},
            {'value': 'medium', 'label': '균형'},
        ],
        'input_modalities': ['text'], 'is_default': True, 'billing': 'subscription',
    }, {
        'model': 'gpt-second', 'display_name': 'GPT Second',
        'default_reasoning_effort': 'high',
        'reasoning_efforts': [{'value': 'high', 'label': '깊게'}],
        'input_modalities': ['text', 'image'], 'is_default': False,
        'billing': 'subscription',
    }]
    projection = [{key: model[key] for key in expected[index]}
                  for index, model in enumerate(value['models'])]
    assert projection == expected
    assert all(model['capability_claims_digest'].startswith('sha256:')
               for model in value['models'])
    assert value['capability_claims_digest'].startswith('sha256:')
    assert value['binding_id'] == codex.binding and value['request_epoch'] == 1
    assert subject.snapshot('codex') == value
    with sqlite3.connect(store.path) as db:
        stored = db.execute('SELECT payload FROM model_catalogs WHERE id = ?',
                            (value['catalog_id'],)).fetchone()
    assert json.loads(stored[0]) == value
    event = store.events()[-1]
    assert event['kind'] == 'model_catalog_refreshed'
    assert event['metadata'] == {
        'provider': 'codex', 'mode': 'subscription',
        'catalog_id': value['catalog_id'], 'model_count': 2,
        'binding_id': codex.binding, 'request_epoch': 1,
        'capability_claims_digest': value['capability_claims_digest'],
    }


def test_choice_is_bound_to_current_catalog_account_model_and_effort(catalog):
    subject, codex, _ = catalog
    first = subject.refresh('codex')
    choice = {'provider': 'codex', 'mode': 'subscription',
              'catalog_id': first['catalog_id'], 'model': 'gpt-fixture', 'effort': 'low'}

    assert subject.validate_choice(choice) == {
        **choice, 'display_name': 'GPT Fixture', 'fetched_at': first['fetched_at'],
        'binding_id': first['binding_id'], 'workspace_binding': None,
        'request_epoch': first['request_epoch'],
        'capability_claims_digest': first['models'][0]['capability_claims_digest'],
        'validated_catalog_id': first['catalog_id'],
        'latest_fetched_at': first['fetched_at'],
    }
    assert codex.binding_reads == 0, 'validation inside a storage transaction must be pure'

    for change in (
        {'provider': 'claude'}, {'mode': 'api'}, {'catalog_id': 'old'},
        {'model': 'not-advertised'}, {'effort': 'xhigh'},
    ):
        with pytest.raises(ValueError):
            subject.validate_choice({**choice, **change})

    second = subject.refresh('codex')
    assert second['catalog_id'] != first['catalog_id']
    assert subject.validate_choice(choice)['validated_catalog_id'] == second['catalog_id']

    with sqlite3.connect(subject.store.path) as db:
        db.execute("UPDATE model_catalog_account_state SET binding = 'different-account'")
    with pytest.raises(ValueError, match='stale'):
        subject.validate_choice(choice)


def test_failed_refresh_invalidates_ready_catalog_for_validation(catalog):
    subject, codex, store = catalog
    first = subject.refresh('codex')
    choice = {'provider': 'codex', 'mode': 'subscription',
              'catalog_id': first['catalog_id'], 'model': 'gpt-fixture', 'effort': 'low'}
    codex.pages = [{'data': 'broken', 'nextCursor': None}]

    assert subject.refresh('codex')['status'] == 'error'
    assert subject.snapshot('codex')['status'] == 'error'
    with pytest.raises(ValueError, match='stale'):
        subject.validate_choice(choice)
    assert store.events()[-1]['kind'] == 'model_catalog_refresh_failed'
    assert store.events()[-1]['metadata'] == {
        'provider': 'codex', 'mode': 'subscription', 'status': 'error'
    }


@pytest.mark.parametrize(('state', 'billing'), [
    ('disconnected', 'unknown'), ('api_key', 'api'), ('error', 'unknown'),
])
def test_refresh_never_labels_non_subscription_state_ready(catalog, state, billing):
    subject, codex, _ = catalog
    codex.state, codex.billing = state, billing

    value = subject.refresh('codex')

    assert value['status'] in {'unavailable', 'error'}
    assert value['models'] == [] and value['execution_ready'] is False


@pytest.mark.parametrize('pages', [
    [{'data': 'not-a-list', 'nextCursor': None}],
    [{'data': [], 'nextCursor': 'same'}, {'data': [], 'nextCursor': 'same'}],
    [{'data': [{'model': 'gpt', 'displayName': 'GPT', 'hidden': False,
               'isDefault': True, 'defaultReasoningEffort': 'low',
               'supportedReasoningEfforts': [], 'inputModalities': ['text']}],
      'nextCursor': None}],
])
def test_malformed_or_empty_catalog_is_error_not_salvaged(catalog, pages):
    subject, codex, _ = catalog
    codex.pages = pages
    value = subject.refresh('codex')
    assert value['status'] == 'error' and value['models'] == []


def test_malformed_connection_snapshot_is_a_bounded_catalog_error(catalog):
    subject, codex, _ = catalog
    codex.snapshot = lambda: None
    assert subject.refresh('codex')['status'] == 'error'


def test_late_refresh_cannot_restore_an_obsolete_account_binding(catalog, monkeypatch):
    subject, _, store = catalog
    import app.model_catalog as implementation

    entered, release = threading.Event(), threading.Event()
    original = implementation._normalize_pages
    first = True

    def delayed_normalize(pages):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(3)
        return original(pages)

    current = subject.refresh('codex')
    monkeypatch.setattr(implementation, '_normalize_pages', delayed_normalize)
    with ThreadPoolExecutor(max_workers=1) as pool:
        obsolete = pool.submit(subject.refresh, 'codex')
        assert entered.wait(2)
        with store._connection() as db:
            db.execute("UPDATE model_catalog_account_state SET binding = 'session-1:account-2'")
        release.set()
        assert obsolete.result(timeout=2)['status'] == 'error'

    assert subject.snapshot('codex') == current
    with sqlite3.connect(store.path) as db:
        assert db.execute('''SELECT binding FROM model_catalog_account_state
            WHERE provider = 'codex' ''').fetchone()[0] == 'session-1:account-2'


def test_refresh_checks_account_binding_inside_its_write_transaction(catalog, monkeypatch):
    subject, _, store = catalog
    original_connection = store._connection
    observed = []

    @contextmanager
    def checked_connection():
        with original_connection() as db:
            def trace(statement):
                if 'SELECT binding FROM model_catalog_account_state' in statement:
                    observed.append(db.in_transaction)
            db.set_trace_callback(trace)
            yield db

    monkeypatch.setattr(store, '_connection', checked_connection)
    assert subject.refresh('codex')['status'] == 'ready'
    assert observed == [True, True]
