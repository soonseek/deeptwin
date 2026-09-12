"""Actual SQLite audit checks with controlled models; never invokes Codex."""

import json
from uuid import uuid4

import pytest

from app.codex_understanding import CodexUnderstandingModel
from app.storage import Store
from app.tests.test_understanding import Model, output, terminal
from app.understanding import Understanding


PROFILE = {'id': 'codex-0.144.4-environmentless-v1', 'cli_version': '0.144.4',
           'environment_mode': 'none', 'auth_mode': 'managed_chatgpt',
           'native_resource_tools': 'disabled', 'internal_tool_attempts': 'rejected'}


def test_adapter_profile_is_readonly_and_detached_without_provider_start(tmp_path):
    subject = CodexUnderstandingModel(Store(tmp_path))
    assert subject.runtime_profile == PROFILE
    copied = subject.runtime_profile
    copied['id'] = 'changed'
    assert subject.runtime_profile == PROFILE
    with pytest.raises(AttributeError):
        subject.runtime_profile = {}


def test_profile_is_durable_before_generate_and_does_not_change_input_hash(tmp_path):
    store = Store(tmp_path)
    source = '합성 업무의 원본 설명'
    work = store.create_work(source)
    observations = []

    class ProfiledModel(Model):
        runtime_profile = dict(PROFILE)

        def generate(self, prompt, schema, cancel_event):
            with store._connection() as db:
                row = db.execute('SELECT payload, input_json FROM understanding_requests').fetchone()
            observations.append((json.loads(row['payload']), json.loads(row['input_json'])))
            return {'text': json.dumps(output(source), ensure_ascii=False), 'model': 'controlled-model'}

    with Understanding(store, model_factory=ProfiledModel) as service:
        request = service.create(work['id'], 1, str(uuid4()), True)
        record = terminal(service, work['id'])
    assert record['status'] == 'succeeded'
    assert observations[0][0]['runtime_profile'] == PROFILE
    assert observations[0][1]['runtime_profile'] == PROFILE
    assert record['runtime_profile'] == PROFILE
    assert record['input_sha256'] == request['input_sha256']
    assert store.get_work(work['id']) == work
    events = store.events(work['id'])
    assert any(event['metadata'].get('runtime_profile_id') == PROFILE['id'] for event in events)
    assert source not in json.dumps(events, ensure_ascii=False)


@pytest.mark.parametrize('profile', [None, [], {'id': PROFILE['id']},
    {**PROFILE, 'token': 'do-not-persist'}, {**PROFILE, 'id': 'x' * 1000},
    {**PROFILE, 'id': '/private/credential/path'}, {**PROFILE, 'cli_version': False},
    {**PROFILE, 'auth_mode': 'api_key'}, {**PROFILE, 'native_resource_tools': 'enabled'}])
def test_invalid_profile_fails_without_generate_or_secret_persistence(tmp_path, profile):
    store = Store(tmp_path)
    work = store.create_work('합성 설명')
    provider = Model()
    provider.runtime_profile = profile
    with Understanding(store, model_factory=lambda: provider) as service:
        service.create(work['id'], 1, str(uuid4()), True)
        record = terminal(service, work['id'])
    assert provider.calls == []
    assert record['status'] == 'failed' and record['result'] is None
    with store._connection() as db:
        audit = db.execute('SELECT input_json FROM understanding_requests').fetchone()[0]
    assert 'runtime_profile' not in audit and 'do-not-persist' not in audit
    assert 'do-not-persist' not in json.dumps(store.events())


def test_profile_audit_commit_failure_prevents_model_call(tmp_path):
    store = Store(tmp_path)
    work = store.create_work('합성 설명')
    provider = Model()
    provider.runtime_profile = dict(PROFILE)
    with Understanding(store, model_factory=lambda: provider) as service:
        with store._connection() as db:
            db.execute("""CREATE TRIGGER reject_profile BEFORE UPDATE OF input_json ON understanding_requests
                BEGIN SELECT RAISE(ABORT, 'controlled profile save failure'); END""")
        service.create(work['id'], 1, str(uuid4()), True)
        record = terminal(service, work['id'])
    assert provider.calls == []
    assert record['status'] == 'failed'
    assert 'runtime_profile' not in record
    assert not any(event['metadata'].get('runtime_profile_id') for event in store.events())


def test_existing_model_without_profile_still_runs(tmp_path):
    store = Store(tmp_path)
    source = '합성 설명'
    work = store.create_work(source)
    provider = Model(output(source))
    with Understanding(store, model_factory=lambda: provider) as service:
        service.create(work['id'], 1, str(uuid4()), True)
        record = terminal(service, work['id'])
    assert record['status'] == 'succeeded' and len(provider.calls) == 1
    assert 'runtime_profile' not in record
