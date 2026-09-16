import json
import time
from uuid import uuid4

from app.server import create_development_app as create_app
from app.tests.local_http import LocalTestClient as TestClient
from app.tests.test_model_selection import Catalog, choice


class CatalogBoundary(Catalog):
    def __init__(self):
        super().__init__()
        self.refreshes = 0

    def snapshot(self, provider, mode=None):
        if provider not in {'codex', 'claude'}:
            raise KeyError(provider)
        mode = mode or ('api' if provider == 'claude' else 'subscription')
        if (provider, mode) not in {
            ('codex', 'subscription'), ('codex', 'api'), ('claude', 'api')
        }:
            raise ValueError('unsupported mode')
        return {'provider': provider, 'mode': mode,
                'status': 'ready' if self.refreshes else 'unqueried',
                'models': [], 'catalog_id': 'catalog-1' if self.refreshes else None,
                'message': 'controlled catalog', 'execution_ready': False}

    def refresh(self, provider, mode=None):
        self.refreshes += 1
        return self.snapshot(provider, mode)


def test_catalog_is_explicit_and_selection_api_is_work_scoped(tmp_path):
    catalog = CatalogBoundary()
    app = create_app(tmp_path, model_catalog_factory=lambda store, codex: catalog)
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        headers = {'X-CSRF-Token': client.csrf_token}
        codex = next(
            item for item in client.get('/api/providers').json()['providers']
            if item['id'] == 'codex'
        )
        assert codex['default_mode'] == 'subscription'
        assert [(item['id'], item['billing']) for item in codex['modes']] == [
            ('subscription', 'subscription'), ('api', 'api'),
        ]
        assert client.get('/api/model-catalogs/codex').json()['status'] == 'unqueried'
        assert catalog.refreshes == 0
        assert client.post('/api/model-catalogs/codex/refresh', json={}).status_code == 403
        assert client.post('/api/model-catalogs/codex/refresh', json={}, headers=headers).status_code == 200
        assert catalog.refreshes == 1
        assert client.get('/api/model-catalogs/unknown').status_code == 404
        work = client.post('/api/works', json={'text': '내 업무'}, headers=headers).json()
        path = '/api/works/' + work['id'] + '/model-selection'
        assert client.get(path).json() == {'version': 0, 'selection': None}
        first = client.put(path, json={'expected_version': 0, 'selection': choice()}, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json()['version'] == 1
        assert client.get(path).json() == first.json()
        conflict = client.put(path, json={'expected_version': 0, 'selection': choice('model-b')}, headers=headers)
        assert conflict.status_code == 409 and '모델' in conflict.json()['detail']
        assert client.get('/api/works/' + work['id']).json()['revision'] == 1
        assert catalog.refreshes == 1


def test_catalog_api_binds_explicit_provider_mode_and_rejects_query_smuggling(tmp_path):
    catalog = CatalogBoundary()
    app = create_app(tmp_path, model_catalog_factory=lambda store, codex: catalog)
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        headers = {'X-CSRF-Token': client.csrf_token}
        codex_api = client.get('/api/model-catalogs/codex?mode=api')
        claude_api = client.post(
            '/api/model-catalogs/claude/refresh?mode=api', json={}, headers=headers,
        )

        assert codex_api.status_code == 200
        assert codex_api.json()['mode'] == 'api'
        assert claude_api.status_code == 200
        assert claude_api.json()['mode'] == 'api'
        for path in (
            '/api/model-catalogs/claude?mode=subscription',
            '/api/model-catalogs/codex?mode=subscription&mode=api',
            '/api/model-catalogs/codex?provider=claude',
        ):
            assert client.get(path).status_code == 400


def test_complete_model_policy_api_supports_default_purpose_and_agent_choices(tmp_path):
    catalog = CatalogBoundary()
    app = create_app(tmp_path, model_catalog_factory=lambda store, codex: catalog)
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        headers = {'X-CSRF-Token': client.csrf_token}
        work = client.post('/api/works', json={'text': '내 업무'}, headers=headers).json()
        path = '/api/works/' + work['id'] + '/model-policy'
        assert client.get(path).json() == {
            'version': 0, 'default': None,
            'purpose_overrides': {}, 'agent_overrides': {},
        }
        body = {
            'expected_version': 0,
            'default': choice(),
            'purpose_overrides': {'critique': choice('model-b')},
            'agent_overrides': {'fact-checker': choice()},
        }
        saved = client.put(path, json=body, headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()['version'] == 1
        assert saved.json()['purpose_overrides']['critique']['model'] == 'model-b'
        assert saved.json()['agent_overrides']['fact-checker']['model'] == 'model-a'
        assert client.get(path).json() == saved.json()
        stale = client.put(
            path, json={**body, 'default': choice('model-b')}, headers=headers,
        )
        assert stale.status_code == 409
        assert client.get('/api/works/' + work['id']).json()['revision'] == 1


class SelectedModel:
    def __init__(self):
        self.selections = []

    def generate(self, prompt, schema, cancel, *, selection):
        self.selections.append(selection)
        return {'model': selection['model'], 'text': json.dumps({
            'summary': {'text': '원 업무', 'evidence': [{'source_id': 'work-description', 'quote': '원 업무'}]},
            'deliverables': [], 'constraints': [], 'open_questions': [], 'assumptions': []})}


def test_understanding_api_requires_and_forwards_exact_saved_selection(tmp_path):
    catalog, model = CatalogBoundary(), SelectedModel()
    app = create_app(tmp_path, model_catalog_factory=lambda store, codex: catalog,
                     understanding_model_factory=lambda: model, understanding_provider_ready=True)
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        headers = {'X-CSRF-Token': client.csrf_token}
        work = client.post('/api/works', json={'text': '원 업무'}, headers=headers).json()
        base = '/api/works/' + work['id']
        request = {'revision': 1, 'request_key': str(uuid4()), 'allow_transfer': True}
        assert client.post(base + '/understanding-requests', json=request, headers=headers).status_code == 400
        assert client.post(base + '/understanding-requests', json={**request, 'model_selection_version': 0}, headers=headers).status_code == 400
        assert model.selections == []
        client.put(base + '/model-selection', json={'expected_version': 0, 'selection': choice()}, headers=headers)
        request['model_selection_version'] = 1
        response = client.post(base + '/understanding-requests', json=request, headers=headers)
        assert response.status_code == 202, response.text
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            record = client.get(base + '/understanding-requests').json()[-1]
            if record['status'] not in {'queued', 'running'}:
                break
            time.sleep(.01)
        assert record['status'] == 'succeeded'
        assert record['model_selection_version'] == 1
        assert record['model_selection']['model'] == record['model'] == 'model-a'
        assert model.selections[0]['model'] == 'model-a'
        assert client.post(base + '/understanding-requests', json=request, headers=headers).json()['id'] == record['id']
        for malformed_version in [True, 1.0]:
            assert client.post(base + '/understanding-requests',
                json={**request, 'model_selection_version': malformed_version}, headers=headers).status_code == 400
        assert len(model.selections) == 1
