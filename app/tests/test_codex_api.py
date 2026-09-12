from app.tests.local_http import LocalTestClient as TestClient

from app.server import create_app
from app.storage import Store


class ConnectionFixture:
    def __init__(self, store):
        self.calls = []
        self.closed = False
        self.value = {'id': 'codex', 'label': 'Codex', 'installed': True, 'auth_status': 'unknown',
                      'billing': 'unknown', 'message': 'unchecked', 'capabilities': {'execution': False},
                      'connection': {'state': 'unchecked', 'login': {'status': 'idle'}, 'rate_limits': []}}

    def snapshot(self):
        return self.value.copy()

    def check(self):
        self.calls.append('check')
        self.value = {**self.value, 'auth_status': 'logged_in', 'billing': 'subscription',
                      'connection': {'state': 'connected', 'login': {'status': 'idle'}, 'rate_limits': []}}
        return self.snapshot()

    def start_login(self):
        self.calls.append('login')
        return self.snapshot()

    def cancel_login(self, login_id):
        self.calls.append(('cancel', login_id))
        return self.snapshot()

    def close(self):
        self.closed = True


def test_connection_api_is_explicit_and_closes_its_provider(tmp_path):
    connection = ConnectionFixture(Store(tmp_path))
    with TestClient(create_app(tmp_path, port=4193, codex_factory=lambda store: connection,
                               understanding_provider_ready=False), base_url='http://127.0.0.1:4193') as client:
        bootstrap = client.get('/api/bootstrap').json()
        assert connection.calls == []
        assert bootstrap['capabilities'] == {'understanding': True, 'understanding_provider_ready': False,
                                             'design_generation': False, 'execution': False}
        token = {'X-CSRF-Token': client.csrf_token}
        result = client.post('/api/providers/codex/check', json={}, headers=token)
        assert result.status_code == 200
        assert result.json()['connection']['state'] == 'connected'
        assert client.get('/api/providers/codex').json()['billing'] == 'subscription'
        assert client.get('/api/providers').json()['providers'][0]['connection']['state'] == 'connected'
        assert client.post('/api/providers/codex/login', json={}, headers=token).status_code == 200
        assert client.post('/api/providers/codex/login/cancel', json={'login_id': 'owned-login'}, headers=token).status_code == 200
        assert connection.calls == ['check', 'login', ('cancel', 'owned-login')]
    assert connection.closed


def test_auth_endpoints_reject_csrf_extra_modes_and_untrusted_bodies(tmp_path):
    connection = ConnectionFixture(Store(tmp_path))
    with TestClient(create_app(tmp_path, port=4193, codex_factory=lambda store: connection), base_url='http://127.0.0.1:4193') as client:
        token = {'X-CSRF-Token': client.csrf_token}
        for path in ['/check', '/login', '/login/cancel']:
            assert client.post('/api/providers/codex' + path, json={}).status_code == 403
        for body in [{'type': 'apiKey', 'apiKey': 'secret'}, {'command': ['evil']}, {'mode': 'api'}]:
            assert client.post('/api/providers/codex/login', json=body, headers=token).status_code == 400
        for login_id in [[], {}, None, '', 'a' * 200]:
            assert client.post('/api/providers/codex/login/cancel', json={'login_id': login_id}, headers=token).status_code == 400
        assert client.post('/api/providers/claude/login', json={}, headers=token).status_code == 404
        assert connection.calls == []
