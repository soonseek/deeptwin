"""Independent boundary checks using only controlled providers, never user auth."""

import json
import sys

import pytest
from app.tests.local_http import LocalTestClient as TestClient

from app import codex_connection
from app.codex_connection import CodexConnection
from app.codex_rpc import CodexRPC
from app.storage import Store


def test_manager_and_real_transport_preserve_no_parameter_rate_limit_request(tmp_path, monkeypatch):
    child = tmp_path / 'controlled_provider.py'
    child.write_text('''import json, sys
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    method = message["method"]
    if method == "initialize":
        result = {"userAgent":"controlled", "codexHome":"/private/test", "platformFamily":"unix", "platformOs":"test"}
    elif method == "account/read":
        result = {"account":{"type":"chatgpt","email":"hidden@example.test","planType":"plus"},"requiresOpenaiAuth":True}
    elif method == "account/rateLimits/read" and message.get("params") is None:
        result = {"rateLimits":{"primary":{"usedPercent":27,"windowDurationMins":300,"resetsAt":2000000000}}}
    else:
        print(json.dumps({"id":message["id"],"error":{"code":-32602,"message":"unexpected request"}}), flush=True)
        continue
    print(json.dumps({"id":message["id"],"result":result}), flush=True)
''')
    monkeypatch.setattr(codex_connection, 'find_codex', lambda: '/controlled/codex')
    store = Store(tmp_path / 'data')
    original = store.create_work('\nDo not send this work to auth')

    def factory(command, **kwargs):
        assert not any('forced_login_method' in part for part in command)
        return CodexRPC([sys.executable, '-u', str(child)], **kwargs)

    manager = CodexConnection(store, rpc_factory=factory)
    try:
        view = manager.check()
        assert view['connection']['state'] == 'connected'
        assert view['connection']['rate_limits'] == [{
            'id': 'codex:primary', 'label': 'codex', 'remaining_percent': 73,
            'window_minutes': 300, 'resets_at': 2000000000,
        }]
        assert store.get_work(original['id']) == original
        assert 'hidden@example.test' not in json.dumps([view, store.events()])
    finally:
        manager.close()


class ControlledRPC:
    def __init__(self):
        self.running = False
        self.account = {'account': None, 'requiresOpenaiAuth': True}
        self.notes = []
        self.calls = []
        self.cancel = {'status': 'canceled'}
        self.exit_during_limits = False

    def start(self):
        self.running = True

    def close(self):
        self.running = False

    def call(self, method, params):
        self.calls.append((method, params))
        if method == 'account/read':
            return self.account
        if method == 'account/login/start':
            return {'type': 'chatgpt', 'loginId': 'owned-login', 'authUrl': 'https://auth.openai.com/authorize?state=private-login-state'}
        if method == 'account/login/cancel':
            return self.cancel
        if method == 'account/rateLimits/read':
            if self.exit_during_limits:
                self.running = False
                raise RuntimeError('raw accessToken=private-token')
            return {'rateLimits': {'primary': {'usedPercent': None}}}
        raise AssertionError(method)

    def drain_notifications(self):
        result, self.notes = self.notes, []
        return result


@pytest.fixture
def controlled(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_connection, 'find_codex', lambda: '/controlled/codex')
    rpc, store = ControlledRPC(), Store(tmp_path)
    manager = CodexConnection(store, rpc_factory=lambda *args, **kwargs: rpc)
    yield manager, rpc, store
    manager.close()


def test_transport_exit_during_optional_rate_read_is_not_returned_as_live_connection(controlled):
    manager, rpc, store = controlled
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'plus'}, 'requiresOpenaiAuth': True}
    rpc.exit_during_limits = True
    view = manager.check()
    assert view['connection']['state'] == 'error'
    assert view['billing'] == 'unknown'
    assert 'private-token' not in json.dumps([view, store.events()])


def test_expired_login_not_found_rechecks_account_without_claiming_cancel_or_reverting_auth(controlled, monkeypatch):
    manager, rpc, store = controlled
    monkeypatch.setattr(codex_connection.time, 'monotonic', lambda: 1)
    manager.start_login()
    rpc.account = {'account': {'type': 'chatgpt', 'planType': 'plus'}, 'requiresOpenaiAuth': True}
    rpc.cancel = {'status': 'notFound'}
    monkeypatch.setattr(codex_connection.time, 'monotonic', lambda: 1000)
    view = manager.snapshot()
    assert view['connection']['state'] == 'connected', 'expiry cancellation can race with completed shared login'
    assert view['connection']['login']['status'] != 'cancelled'
    assert not any(method == 'account/logout' for method, _ in rpc.calls)
    assert 'auth_url' not in view['connection']['login']
    assert 'private-login-state' not in json.dumps(store.events())


def test_unrelated_and_late_login_completions_do_not_reactivate_cancelled_attempt(controlled):
    manager, rpc, store = controlled
    work = store.create_work('actual user work')
    manager.start_login()
    rpc.notes = [{'method': 'account/login/completed', 'params': {'loginId': 'someone-else', 'success': True}}]
    assert manager.snapshot()['connection']['login']['status'] == 'pending'
    manager.cancel_login('owned-login')
    rpc.notes = [{'method': 'account/login/completed', 'params': {'loginId': 'owned-login', 'success': True, 'error': 'private-secret'}}]
    view = manager.snapshot()
    assert view['connection']['login']['status'] == 'cancelled'
    assert view['capabilities']['execution'] is False
    assert store.get_work(work['id']) == work
    assert 'private-secret' not in json.dumps([view, store.events()])


def test_auth_http_endpoints_enforce_origin_csrf_and_keep_work_untouched(tmp_path, monkeypatch):
    from app.server import create_development_app as create_app
    monkeypatch.setattr(codex_connection, 'find_codex', lambda: '/controlled/codex')
    rpc = ControlledRPC()
    application = create_app(tmp_path, port=4193,
        codex_factory=lambda store: CodexConnection(store, rpc_factory=lambda *args, **kwargs: rpc))
    work = application.state.store.create_work('\n실제 업무는 인증 요청과 별개')
    with TestClient(application, base_url='http://127.0.0.1:4193') as client:
        bootstrap = client.get('/api/bootstrap').json()
        token = {'X-CSRF-Token': client.csrf_token}
        assert rpc.calls == [] and not rpc.running
        for suffix in ['check', 'login', 'login/cancel']:
            path = '/api/providers/codex/' + suffix
            body = {'login_id': 'owned-login'} if suffix == 'login/cancel' else {}
            assert client.get(path).status_code == 405
            assert client.post(path, json=body).status_code == 403
            assert client.post(path, json=body, headers={**token, 'Origin': 'https://untrusted.test'}).status_code == 403
        assert rpc.calls == []
        assert client.post('/api/providers/codex/login', json={'apiKey': 'private-api-key'}, headers=token).status_code == 400
        started = client.post('/api/providers/codex/login', json={}, headers=token)
        assert started.status_code == 200
        assert started.headers['cache-control'] == 'no-store'
        assert client.post('/api/providers/codex/login/cancel', json={'login_id': 'unowned'}, headers=token).status_code == 409
        assert not any(method == 'account/login/cancel' for method, _ in rpc.calls)
        assert client.post('/api/providers/codex/login/cancel', json={'login_id': 'owned-login'}, headers=token).status_code == 200
        assert application.state.store.get_work(work['id']) == work
        events = json.dumps(application.state.store.events())
        assert 'private-api-key' not in events and 'private-login-state' not in events
