import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

from app import codex_understanding
from app.understanding import ModelError


def _safe_config(runtime):
    features = {name: False for name in codex_understanding._ISOLATED_FEATURES}
    features.update({
        'deferred_executor': False,
        'standalone_web_search': False,
        'token_budget': {'enabled': False},
        'current_time_reminder': {'enabled': False},
    })
    return {'config': {
        'features': features,
        'web_search': 'disabled',
        'project_doc_max_bytes': 0,
        'developer_instructions': '',
        'instructions': None,
        'model_instructions_file': None,
        'model_provider': 'openai',
        'model_providers': {},
        'openai_base_url': None,
        'chatgpt_base_url': None,
        'notify': [],
        'mcp_servers': {},
        'include_permissions_instructions': False,
        'include_apps_instructions': False,
        'include_collaboration_mode_instructions': False,
        'include_environment_context': False,
        'orchestrator': {
            'skills': {'enabled': False},
            'mcp': {'enabled': False},
        },
        'skills': {'include_instructions': False},
        'tools': {'web_search': None},
    }, 'origins': {}, 'runtime': str(runtime)}


def _selection():
    return {
        'provider': 'codex', 'mode': 'subscription',
        'catalog_id': 'catalog-1', 'model': 'gpt-5.6-terra',
        'effort': 'high', 'display_name': 'GPT-5.6-Terra',
        'fetched_at': '2026-09-07T00:00:00+00:00',
        'validated_catalog_id': 'catalog-1',
        'latest_fetched_at': '2026-09-07T00:00:00+00:00',
    }


class RecordingRPC:
    def __init__(self, command, cwd, env=None, timeout=10):
        self.command = list(command)
        self.cwd = Path(cwd)
        self.env = dict(env or {})
        self.timeout = timeout
        self.calls = []
        self.closed = False
        self.isolation_violation = False
        self._notifications = []

    def start(self):
        return self

    def call(self, method, params, timeout=None):
        self.calls.append((method, params))
        if method == 'account/read':
            return {'account': {'type': 'chatgpt'}, 'requiresOpenaiAuth': True}
        if method == 'config/read':
            return _safe_config(self.cwd)
        if method == 'skills/list':
            return {'data': [{'cwd': str(self.cwd), 'skills': [], 'errors': []}]}
        if method == 'thread/start':
            return {
                'thread': {'id': 'thread-1', 'ephemeral': True},
                'instructionSources': [], 'model': 'gpt-5.6-terra',
                'modelProvider': 'openai', 'cwd': str(self.cwd),
                'approvalPolicy': 'never',
                'sandbox': {'type': 'readOnly'},
            }
        if method == 'turn/start':
            self._notifications.append({
                'method': 'turn/completed',
                'params': {'threadId': 'thread-1', 'turn': {
                    'id': 'turn-1', 'status': 'completed', 'items': [{
                        'type': 'agentMessage', 'id': 'message-1',
                        'phase': 'final_answer', 'text': '{"summary":"ok"}',
                    }],
                }},
            })
            return {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': []}}
        if method == 'turn/interrupt':
            return {}
        raise AssertionError(method)

    def drain_notifications(self):
        result, self._notifications = self._notifications, []
        return result

    def close(self):
        self.closed = True


def test_generation_transport_opts_into_experimental_environment_api(tmp_path):
    peer = tmp_path / 'experimental_peer.py'
    peer.write_text(
        """import json, sys
for line in sys.stdin:
    request = json.loads(line)
    if request.get('method') == 'initialize':
        enabled = request.get('params', {}).get('capabilities', {}).get('experimentalApi') is True
        if enabled:
            print(json.dumps({'id': request['id'], 'result': {'ready': True}}), flush=True)
        else:
            print(json.dumps({'id': request['id'], 'error': {'code': -32600, 'message': 'experimental required'}}), flush=True)
""",
        encoding='utf-8',
    )
    rpc = codex_understanding.GenerationRPC(
        [sys.executable, str(peer)], cwd=tmp_path, timeout=1,
    )
    try:
        assert rpc.start() is rpc
    finally:
        rpc.close()


def test_environmentless_generation_sends_no_environment_or_capability_roots(
        tmp_path, monkeypatch):
    created = []

    def factory(*args, **kwargs):
        rpc = RecordingRPC(*args, **kwargs)
        created.append(rpc)
        return rpc

    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'), rpc_factory=factory,
        version_reader=lambda _path: True,
    )

    result = subject.generate(
        'PRIVATE INPUT', {'type': 'object'},
        SimpleNamespace(is_set=lambda: False), selection=_selection(),
    )

    assert result == {'text': '{"summary":"ok"}', 'model': 'gpt-5.6-terra'}
    rpc = created[0]
    thread = dict(rpc.calls)['thread/start']
    turn = dict(rpc.calls)['turn/start']
    assert thread['ephemeral'] is True
    assert thread['environments'] == []
    assert thread['dynamicTools'] == []
    assert thread['selectedCapabilityRoots'] == []
    assert turn['environments'] == []
    assert turn['sandboxPolicy'] == {'type': 'readOnly', 'networkAccess': False}
    assert turn['input'] == [{'type': 'text', 'text': 'PRIVATE INPUT'}]
    calls_before_turn = rpc.calls[:next(
        index for index, call in enumerate(rpc.calls) if call[0] == 'turn/start')]
    assert 'PRIVATE INPUT' not in repr(calls_before_turn)
    assert rpc.env['CODEX_EXEC_SERVER_URL'] == 'none'


@pytest.mark.parametrize(('feature', 'value'), [
    ('deferred_executor', True),
    ('standalone_web_search', True),
    ('enable_fanout', True),
    ('code_mode_only', True),
    ('chronicle', True),
    ('token_budget', {'enabled': True}),
    ('current_time_reminder', {'enabled': True}),
])
def test_independent_utility_feature_fails_native_isolation(feature, value, tmp_path):
    response = _safe_config(tmp_path)
    response['config']['features'][feature] = value
    assert not codex_understanding._native_tool_isolation_supported(response)


def test_unprojected_request_user_input_setting_is_disabled_by_exact_override():
    command = codex_understanding._command('/tools/codex')
    assert 'tools.experimental_request_user_input.enabled=false' in command


def test_public_tools_projection_does_not_claim_internal_question_tool_absence(tmp_path):
    response = _safe_config(tmp_path)
    response['config']['tools'] = {'web_search': None}
    assert codex_understanding._native_tool_isolation_supported(response)
    command = codex_understanding._command('/tools/codex')
    assert 'tools.experimental_request_user_input.enabled=false' in command


def test_generation_environment_disables_legacy_environment_without_replacing_home(
        tmp_path, monkeypatch):
    home = tmp_path / 'home'
    codex_home = tmp_path / 'codex-home'
    home.mkdir()
    codex_home.mkdir()
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('CODEX_HOME', str(codex_home))

    environment = codex_understanding._generation_environment()

    assert environment['HOME'] == str(home)
    assert environment['CODEX_HOME'] == str(codex_home)
    assert environment['CODEX_EXEC_SERVER_URL'] == 'none'


def test_configured_environment_file_blocks_before_transport_or_input(tmp_path, monkeypatch):
    codex_home = tmp_path / 'codex-home'
    codex_home.mkdir()
    (codex_home / 'environments.toml').touch()
    monkeypatch.setenv('CODEX_HOME', str(codex_home))
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    created = []

    def factory(*args, **kwargs):
        created.append((args, kwargs))
        return RecordingRPC(*args, **kwargs)

    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'), rpc_factory=factory,
        version_reader=lambda _path: True,
    )
    with pytest.raises(ModelError) as caught:
        subject.generate(
            'PRIVATE INPUT', {'type': 'object'},
            SimpleNamespace(is_set=lambda: False), selection=_selection(),
        )

    assert caught.value.reason == 'isolation_unavailable'
    assert created == []
