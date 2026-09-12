import importlib.util
import json
import sqlite3

import pytest

from app.storage import Store, ConflictError


def test_connection_manager_exists():
    assert importlib.util.find_spec('app.codex_connection') is not None, 'Codex connection lifecycle is missing'


class RPCFixture:
    def __init__(self):
        self.running = False
        self.calls = []
        self.notes = []
        self.account = {'account': None, 'requiresOpenaiAuth': True}
        self.limits = {'rateLimits': {'limitId': 'codex', 'primary': {'usedPercent': 25, 'windowDurationMins': 300, 'resetsAt': 2000000000}, 'secondary': None}}
        self.login = {'type': 'chatgpt', 'loginId': 'login-1', 'authUrl': 'https://auth.openai.com/authorize?state=private-state'}
        self.cancel_result = {'status': 'canceled'}
        self.fail = None
        self.env = None
        self.command = None

    def factory(self, command, **kwargs):
        self.command, self.env = command, kwargs['env']
        return self

    def start(self):
        self.running = True

    def close(self):
        self.running = False

    def call(self, method, params, **kwargs):
        self.calls.append((method, params))
        if self.fail == method:
            raise RuntimeError('secret raw transport data')
        if method == 'model/list':
            if params.get('cursor') == 'next-page':
                return {'data': [{'model': 'gpt-2'}], 'nextCursor': None}
            return {'data': [{'model': 'gpt-1'}], 'nextCursor': 'next-page'}
        return {'account/read': self.account, 'account/rateLimits/read': self.limits,
                'account/login/start': self.login, 'account/login/cancel': self.cancel_result}[method]

    def drain_notifications(self):
        result, self.notes = self.notes, []
        return result


@pytest.fixture
def connection(tmp_path, monkeypatch):
    from app import codex_connection
    monkeypatch.setattr(codex_connection, 'find_codex', lambda: '/tools/codex')
    rpc, store = RPCFixture(), Store(tmp_path)
    value = codex_connection.CodexConnection(store, rpc_factory=rpc.factory)
    yield value, rpc, store
    value.close()


def test_snapshot_is_lazy_and_keeps_auth_separate_from_engine(connection):
    manager, rpc, _ = connection
    data = manager.snapshot()
    assert data['connection']['state'] == 'unchecked'
    assert data['auth_status'] == 'unknown'
    assert data['capabilities']['execution'] is False
    assert 'DeepTwin 인스턴스' in data['message']
    assert '서버 소유 관리형 Codex 실행기' in data['message']
    assert '이 컴퓨터' not in data['message']
    assert not rpc.running and rpc.calls == []


def test_missing_development_adapter_reports_server_deployment_gap_not_native_install(tmp_path, monkeypatch):
    from app import codex_connection
    monkeypatch.setattr(codex_connection, 'find_codex', lambda: None)
    manager = codex_connection.CodexConnection(Store(tmp_path), rpc_factory=RPCFixture().factory)
    try:
        data = manager.snapshot()
        assert data['connection']['state'] == 'unavailable'
        assert '서버 소유 관리형 Codex 실행기' in data['message']
        assert '배포' in data['message']
        assert '설치 안내' not in data['message']
        assert '이 컴퓨터' not in data['message']
    finally:
        manager.close()


def test_new_connection_session_invalidates_persisted_account_binding_without_rpc(tmp_path, monkeypatch):
    from app import codex_connection
    store, rpc = Store(tmp_path), RPCFixture()
    with store._connection() as db:
        db.execute('''CREATE TABLE model_catalog_account_state (
            provider TEXT PRIMARY KEY, binding TEXT NOT NULL)''')
        db.execute('INSERT INTO model_catalog_account_state VALUES (?, ?)',
                   ('codex', 'old-process-binding'))
    monkeypatch.setattr(codex_connection, 'find_codex', lambda: '/tools/codex')

    manager = codex_connection.CodexConnection(store, rpc_factory=rpc.factory)
    try:
        with store._connection() as db:
            assert db.execute('SELECT binding FROM model_catalog_account_state').fetchone() is None
        assert rpc.calls == [] and not rpc.running
    finally:
        manager.close()


def test_model_catalog_is_read_only_paginated_and_only_runs_when_explicit(connection):
    manager, rpc, _ = connection
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'plus'},
                   'requiresOpenaiAuth': True}
    assert not any(method == 'model/list' for method, _ in rpc.calls)

    result = manager.read_model_catalog()

    assert result['pages'] == [
        {'data': [{'model': 'gpt-1'}], 'nextCursor': 'next-page'},
        {'data': [{'model': 'gpt-2'}], 'nextCursor': None},
    ]
    assert isinstance(result['binding'], str) and result['binding']
    assert manager.catalog_binding() == result['binding']
    with sqlite3.connect(manager.store.path) as db:
        assert db.execute('SELECT binding FROM model_catalog_account_state').fetchone()[0] == result['binding']
    assert [params for method, params in rpc.calls if method == 'model/list'] == [
        {'limit': 100, 'includeHidden': False},
        {'limit': 100, 'includeHidden': False, 'cursor': 'next-page'},
    ]

    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'plus',
                               'email': 'another@example.invalid'},
                   'requiresOpenaiAuth': True}
    manager.check()
    assert manager.catalog_binding() != result['binding']


def test_model_catalog_never_reads_models_for_api_credentials(connection):
    manager, rpc, _ = connection
    rpc.account = {'account': {'type': 'apiKey'}, 'requiresOpenaiAuth': True}
    with pytest.raises(PermissionError):
        manager.read_model_catalog()
    assert not any(method == 'model/list' for method, _ in rpc.calls)


def test_explicit_check_detects_subscription_without_exposing_account_details(connection, monkeypatch):
    manager, rpc, store = connection
    monkeypatch.setenv('OPENAI_API_KEY', 'private-api-key')
    monkeypatch.setenv('CODEX_ACCESS_TOKEN', 'private-access-token')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'private-anthropic-key')
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'pro', 'email': 'private@example.com', 'accessToken': 'secret'}, 'requiresOpenaiAuth': True}
    result = manager.check()
    assert result['connection']['state'] == 'connected'
    assert result['connection']['plan_type'] == 'pro'
    assert result['auth_status'] == 'logged_in' and result['billing'] == 'subscription'
    assert result['capabilities']['execution'] is False
    assert result['connection']['rate_limits'][0]['remaining_percent'] == 75
    assert rpc.calls == [('account/read', {'refreshToken': False}), ('account/rateLimits/read', None)]
    assert not {'OPENAI_API_KEY', 'CODEX_ACCESS_TOKEN', 'ANTHROPIC_API_KEY'}.intersection(rpc.env)
    assert 'analytics.enabled=false' in rpc.command
    assert 'forced_login_method' not in str(rpc.command)
    rendered = json.dumps([result, store.events()])
    assert 'private@example.com' not in rendered and 'accessToken' not in rendered


def test_api_account_is_never_reported_as_subscription_or_silently_changed(connection):
    manager, rpc, _ = connection
    rpc.account = {'account': {'type': 'apiKey'}, 'requiresOpenaiAuth': True}
    result = manager.check()
    assert result['connection']['state'] == 'api_key' and result['billing'] == 'api'
    assert not any(method == 'account/login/start' for method, _ in rpc.calls)
    assert result['capabilities']['execution'] is False


def test_null_account_does_not_treat_provider_no_auth_as_logged_in(connection):
    manager, rpc, _ = connection
    rpc.account = {'account': None, 'requiresOpenaiAuth': False}
    assert manager.check()['connection']['state'] != 'connected'
    assert manager.snapshot()['billing'] == 'unknown'


def test_login_is_explicit_deduplicated_and_url_is_not_in_events(connection):
    manager, rpc, store = connection
    result = manager.start_login()
    assert result['connection']['login']['status'] == 'pending'
    assert result['connection']['login']['auth_url'].startswith('https://auth.openai.com/')
    assert manager.start_login()['connection']['login']['login_id'] == 'login-1'
    starts = [p for m, p in rpc.calls if m == 'account/login/start']
    assert starts == [{'type': 'chatgpt', 'useHostedLoginSuccessPage': True, 'appBrand': 'chatgpt'}]
    assert 'private-state' not in json.dumps(store.events())
    assert 'auth_url' not in json.dumps(store.events())


def test_login_success_requires_correlated_notification_and_fresh_account_read(connection):
    manager, rpc, _ = connection
    manager.start_login()
    rpc.notes = [{'method': 'account/login/completed', 'params': {'loginId': 'unrelated', 'success': True}}]
    assert manager.snapshot()['connection']['login']['status'] == 'pending'
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'plus'}, 'requiresOpenaiAuth': True}
    rpc.notes = [{'method': 'account/login/completed', 'params': {'loginId': 'login-1', 'success': True}}]
    result = manager.snapshot()
    assert result['connection']['state'] == 'connected'
    assert result['connection']['login'] == {'status': 'succeeded'}
    assert result['billing'] == 'subscription'


def test_success_notification_without_matching_account_never_claims_connected(connection):
    manager, rpc, _ = connection
    manager.start_login()
    rpc.notes = [{'method': 'account/login/completed', 'params': {'loginId': 'login-1', 'success': True}}]
    result = manager.snapshot()
    assert result['connection']['state'] != 'connected'
    assert result['connection']['login']['status'] == 'failed'


def test_cancel_rejects_wrong_id_and_does_not_logout_shared_credentials(connection):
    manager, rpc, _ = connection
    manager.start_login()
    with pytest.raises(ConflictError):
        manager.cancel_login('another-id')
    result = manager.cancel_login('login-1')
    assert result['connection']['login'] == {'status': 'cancelled'}
    assert ('account/login/cancel', {'loginId': 'login-1'}) in rpc.calls
    assert not any(method == 'account/logout' for method, _ in rpc.calls)


def test_cancel_not_found_rechecks_account_and_never_claims_rollback(connection):
    manager, rpc, _ = connection
    manager.start_login()
    rpc.cancel_result = {'status': 'notFound'}
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'plus'}, 'requiresOpenaiAuth': True}
    result = manager.cancel_login('login-1')
    assert result['connection']['state'] == 'connected'
    assert result['connection']['login']['status'] != 'cancelled'


@pytest.mark.parametrize('url', ['http://auth.openai.com/a', 'https://auth.openai.com.evil.test/a', 'javascript:alert(1)', 'https://evil.test/a', 'https://user@auth.openai.com/a', 'https://auth.openai.com:8443/a'])
def test_untrusted_auth_url_is_never_returned_or_logged(connection, url):
    manager, rpc, store = connection
    rpc.login['authUrl'] = url
    result = manager.start_login()
    assert result['connection']['login']['status'] == 'failed'
    assert 'auth_url' not in result['connection']['login']
    assert url not in json.dumps(store.events())
    assert not rpc.running


def test_transport_failure_and_process_exit_invalidate_connection_without_secrets(connection):
    manager, rpc, store = connection
    rpc.fail = 'account/read'
    result = manager.check()
    assert result['connection']['state'] == 'error'
    assert 'secret raw' not in json.dumps([result, store.events()])
    rpc.fail = None
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'plus'}, 'requiresOpenaiAuth': True}
    assert manager.check()['connection']['state'] == 'connected'
    rpc.running = False
    assert manager.snapshot()['connection']['state'] == 'error'
    assert manager.snapshot()['billing'] == 'unknown'
    with sqlite3.connect(manager.store.path) as db:
        assert db.execute('SELECT binding FROM model_catalog_account_state').fetchone() is None


def test_rate_limit_missing_values_remain_unknown_and_stale_buckets_clear(connection):
    manager, rpc, _ = connection
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'pro'}, 'requiresOpenaiAuth': True}
    rpc.limits = {'rateLimits': {'primary': {'usedPercent': 0}}, 'rateLimitsByLimitId': {
        'codex': {'primary': {'usedPercent': 110, 'windowDurationMins': 300, 'resetsAt': 2000000000}, 'secondary': {'usedPercent': None, 'windowDurationMins': None, 'resetsAt': None}}}}
    limits = manager.check()['connection']['rate_limits']
    assert limits[0]['remaining_percent'] == 0
    assert limits[1]['remaining_percent'] is None
    rpc.account = {'account': {'type': 'apiKey'}, 'requiresOpenaiAuth': True}
    rpc.notes = [{'method': 'account/updated', 'params': {'authMode': 'apikey'}}]
    assert manager.snapshot()['connection']['rate_limits'] == []


def test_login_expiry_drops_url_and_cancels_owned_attempt(connection, monkeypatch):
    from app import codex_connection
    manager, rpc, _ = connection
    monkeypatch.setattr(codex_connection.time, 'monotonic', lambda: 10)
    manager.start_login()
    monkeypatch.setattr(codex_connection.time, 'monotonic', lambda: 10000)
    result = manager.snapshot()
    assert result['connection']['login']['status'] == 'failed'
    assert 'auth_url' not in result['connection']['login']
    assert ('account/login/cancel', {'loginId': 'login-1'}) in rpc.calls
