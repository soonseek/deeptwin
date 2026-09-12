import importlib.util
import json

import pytest
from app.tests.local_http import LocalTestClient as TestClient


def test_server_exists():
    assert importlib.util.find_spec('app.server') is not None, 'real intake API is missing'


@pytest.fixture
def client(tmp_path):
    from app.server import create_app
    with TestClient(create_app(tmp_path, port=4193, understanding_provider_ready=False), base_url='http://127.0.0.1:4193') as value:
        yield value


def auth(client):
    return {'X-CSRF-Token': client.csrf_token}


def create(client, text='첫 업무'):
    response = client.post('/api/works', json={'text': text}, headers=auth(client))
    assert response.status_code == 201, response.text
    return response.json()


def test_bootstrap_is_empty_and_does_not_claim_an_engine(client):
    data = client.get('/api/bootstrap').json()
    assert data['works'] == []
    assert len(client.csrf_token) >= 32 and 'csrf_token' not in data
    assert data['capabilities'] == {'understanding': True, 'understanding_provider_ready': False,
                                    'design_generation': False, 'execution': False}
    assert {p['id'] for p in data['providers']} == {'claude', 'codex'}


def test_exact_text_persisted_and_revision_conflict_does_not_overwrite(client):
    text = '\n  사용자 <script>literal</script> & ${value}\n끝  '
    work = create(client, text)
    assert work['text'] == text
    path = '/api/works/' + work['id']
    assert client.get(path).json()['text'] == text
    updated = client.put(path, json={'text': text + '다음', 'expected_revision': 1}, headers=auth(client))
    assert updated.json()['revision'] == 2
    conflict = client.put(path, json={'text': 'overwrite', 'expected_revision': 1}, headers=auth(client))
    assert conflict.status_code == 409
    assert client.get(path).json()['text'] == text + '다음'


def test_uploads_preserve_unique_originals_and_safe_download(client):
    work = create(client)
    path = '/api/works/' + work['id'] + '/files'
    for revision, payload in enumerate([b'first', b'second'], 1):
        result = client.post(path, params={'name': '자료.txt', 'expected_revision': revision}, content=payload,
                             headers={**auth(client), 'Content-Type': 'text/html'})
        assert result.status_code == 201, result.text
    files = result.json()['files']
    assert len(files) == 2 and files[0]['id'] != files[1]['id']
    for file, expected in zip(files, [b'first', b'second']):
        response = client.get(path + '/' + file['id'])
        assert response.content == expected
        assert response.headers['content-type'] == 'application/octet-stream'
        assert response.headers['content-disposition'].startswith('attachment;')
        assert response.headers['x-content-type-options'] == 'nosniff'
    assert result.json()['revision'] == 3


def test_upload_rejections_do_not_discard_previous_material(client):
    work = create(client)
    path = '/api/works/' + work['id']
    assert client.post(path + '/files', params={'name': 'ok.txt', 'expected_revision': 1}, content=b'keep', headers=auth(client)).status_code == 201
    for name, data, expected in [('../x.txt', b'x', 400), ('code.exe', b'x', 400),
                                  ('large.txt', b'x' * (10 * 1024 * 1024 + 1), 413)]:
        assert client.post(path + '/files', params={'name': name, 'expected_revision': 2}, content=data, headers=auth(client)).status_code == expected
    current = client.get(path).json()
    assert len(current['files']) == 1 and current['revision'] == 2


@pytest.mark.parametrize('headers', [{}, {'X-CSRF-Token': 'wrong'},
    {'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_mutations_reject_missing_csrf_or_cross_site(client, headers):
    assert client.post('/api/works', json={'text': 'attack'}, headers=headers).status_code == 403
    assert client.get('/api/works').json() == []


def test_even_valid_csrf_cannot_cross_origin_or_host(client):
    for extra in [{'Origin': 'http://127.0.0.1:4999'}, {'Origin': 'null'},
                  {'Host': 'attacker.example'}, {'Sec-Fetch-Site': 'cross-site'}]:
        response = client.post('/api/works', json={'text': 'attack'}, headers={**auth(client), **extra})
        assert response.status_code == 403
    assert client.get('/api/bootstrap', headers={'Origin': 'https://evil.example'}).status_code == 403


def test_errors_are_bounded_and_do_not_echo_content(client):
    secret = 'private-secret-value'
    for data in [b'{', json.dumps({'text': secret, 'bad': True}).encode(), json.dumps({'text': 4}).encode()]:
        response = client.post('/api/works', content=data, headers={**auth(client), 'Content-Type': 'application/json'})
        assert response.status_code == 400
        assert secret not in response.text
    assert client.post('/api/works', content=b'a' * (128 * 1024 + 1), headers=auth(client)).status_code == 413
    assert client.get('/api/works/missing').status_code == 404
    assert client.get('/api/works/missing/files/missing').status_code == 404


def test_design_request_is_real_durable_blocked_and_exact_revision_bound(client, tmp_path):
    work = create(client)
    path = '/api/works/' + work['id']
    payload = {'revision': 1, 'provider': 'codex', 'mode': 'subscription'}
    response = client.post(path + '/design-requests', json=payload, headers=auth(client))
    assert response.status_code == 201, response.text
    request = response.json()
    assert request['status'] == 'blocked' and request['revision'] == 1
    assert 'graph' not in request and request['message']
    repeat = client.post(path + '/design-requests', json=payload, headers=auth(client))
    assert repeat.json()['id'] == request['id']
    client.put(path, json={'text': 'new', 'expected_revision': 1}, headers=auth(client))
    assert client.post(path + '/design-requests', json=payload, headers=auth(client)).status_code == 409
    from app.server import create_app
    with TestClient(create_app(tmp_path, port=4193), base_url='http://127.0.0.1:4193') as reopened:
        assert reopened.get(path + '/design-requests').json() == [request]
        assert reopened.get(path).json()['text'] == 'new'


def test_claude_design_request_accepts_api_only_without_subscription_preapproval(client):
    work = create(client)
    path = '/api/works/' + work['id'] + '/design-requests'
    response = client.post(path, json={'revision': 1, 'provider': 'claude', 'mode': 'api'}, headers=auth(client))
    assert response.status_code == 201, response.text
    request = response.json()
    assert request['provider'] == 'claude' and request['mode'] == 'api'
    assert request['status'] == 'blocked' and request['reason'] == 'design_engine_not_connected'
    assert 'Claude API' in request['message'] and '구독' not in request['message'] and '사전 승인' not in request['message']
    event = client.app.state.store.events(work['id'])[-1]
    assert event['metadata']['provider'] == 'claude' and event['metadata']['mode'] == 'api'
    assert event['metadata']['reason'] == 'design_engine_not_connected'
    for payload in [{'revision': 1, 'provider': 'claude', 'mode': 'subscription'},
                    {'revision': True, 'provider': 'codex', 'mode': 'subscription'},
                    {'revision': 1, 'provider': 'other', 'mode': 'subscription'}]:
        assert client.post(path, json=payload, headers=auth(client)).status_code == 400


def test_explicit_codex_api_remains_a_separate_supported_design_request_mode(client):
    work = create(client)
    path = '/api/works/' + work['id'] + '/design-requests'
    response = client.post(path, json={
        'revision': 1, 'provider': 'codex', 'mode': 'api',
    }, headers=auth(client))
    assert response.status_code == 201, response.text
    request = response.json()
    assert request['provider'] == 'codex' and request['mode'] == 'api'
    assert request['reason'] == 'design_engine_not_connected'
    assert 'Codex API' in request['message'] and '구독' not in request['message']


def test_legacy_claude_subscription_history_is_read_verbatim_not_relabelled(client):
    work = create(client)
    path = '/api/works/' + work['id'] + '/design-requests'
    legacy = {
        'id': 'legacy-claude-subscription-request', 'work_id': work['id'], 'revision': 1,
        'provider': 'claude', 'mode': 'subscription', 'status': 'blocked',
        'reason': 'provider_approval_required', 'message': 'historical pre-API policy',
        'created_at': '2026-09-07T00:00:00+00:00',
    }
    with client.app.state.store._connection() as db:
        db.execute('INSERT INTO design_requests VALUES (?, ?, ?, ?, ?, ?)', (
            legacy['id'], work['id'], 1, 'claude', 'subscription',
            json.dumps(legacy, ensure_ascii=False),
        ))
        db.execute('INSERT INTO events(kind, work_id, created_at, metadata) VALUES (?, ?, ?, ?)', (
            'design_request_blocked', work['id'], legacy['created_at'], json.dumps({
                'request_id': legacy['id'], 'revision': 1, 'provider': 'claude',
                'mode': 'subscription', 'reason': 'provider_approval_required',
            }),
        ))

    assert client.get(path).json() == [legacy]
    assert client.post(path, json={
        'revision': 1, 'provider': 'claude', 'mode': 'subscription',
    }, headers=auth(client)).status_code == 400
    assert client.get(path).json() == [legacy]
    event = client.app.state.store.events(work['id'])[-1]
    assert event['kind'] == 'design_request_blocked'
    assert event['metadata']['reason'] == 'provider_approval_required'


def test_request_records_metadata_event_without_body(client, tmp_path):
    work = create(client, 'a confidential description')
    client.post('/api/works/' + work['id'] + '/design-requests',
                json={'revision': 1, 'provider': 'codex', 'mode': 'subscription'}, headers=auth(client))
    from app.storage import Store
    events = Store(tmp_path).events(work['id'])
    assert events[-1]['kind'] == 'design_request_blocked'
    assert 'confidential' not in json.dumps(events)


def test_storage_failures_are_not_reported_as_saved(client, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('secret local path')
    monkeypatch.setattr(client.app.state.store, 'create_work', fail)
    response = client.post('/api/works', json={'text': 'not saved'}, headers=auth(client))
    assert response.status_code == 503
    assert 'secret local path' not in response.text


def test_private_files_cannot_be_served(client):
    for path in ['/../server.py', '/server.py', '/intake.sqlite3', '/.env', '/docs']:
        assert client.get(path).status_code == 404
    response = client.get('/api/bootstrap')
    assert "default-src 'none'" in response.headers['content-security-policy']
    assert response.headers['cache-control'] == 'no-store'


def test_malformed_nested_request_fields_return_safe_errors(client):
    work = create(client)
    for provider, mode in [([], 'subscription'), ({}, 'subscription'), ('codex', [])]:
        response = client.post('/api/works/' + work['id'] + '/design-requests',
            json={'revision': 1, 'provider': provider, 'mode': mode}, headers=auth(client))
        assert response.status_code == 400


def test_non_ascii_csrf_header_is_rejected_without_server_error(client):
    response = client.post('/api/works', json={'text': 'attack'},
                           headers=[(b'x-csrf-token', b'\xff')])
    assert response.status_code == 403


def test_upload_requires_observed_revision_and_rejects_stale_tab(client):
    work = create(client, 'original')
    path = '/api/works/' + work['id']
    assert client.post(path + '/files', params={'name': 'missing-revision.txt'}, content=b'no', headers=auth(client)).status_code == 400
    client.put(path, json={'text': 'another tab', 'expected_revision': 1}, headers=auth(client))
    response = client.post(path + '/files', params={'name': 'stale.txt', 'expected_revision': 1}, content=b'no', headers=auth(client))
    assert response.status_code == 409
    current = client.get(path).json()
    assert current['text'] == 'another tab' and current['revision'] == 2 and current['files'] == []
