import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import codex_understanding
from app.understanding import ModelError


ISOLATED_FEATURES = {
    'apps', 'auth_elicitation', 'browser_use', 'browser_use_external',
    'artifact', 'browser_use_full_cdp_access', 'code_mode', 'code_mode_host',
    'computer_use', 'hooks', 'image_generation', 'in_app_browser', 'memories',
    'mentions_v2', 'multi_agent', 'goals', 'enable_mcp_apps',
    'plugin_sharing', 'plugins', 'remote_plugin',
    'request_permissions_tool',
    'shell_tool', 'skill_mcp_dependency_install', 'tool_call_mcp_elicitation',
    'tool_suggest', 'unified_exec', 'workspace_dependencies',
    'deferred_executor', 'standalone_web_search', 'enable_fanout',
    'code_mode_only', 'chronicle',
    'token_budget', 'current_time_reminder', 'multi_agent_v2',
}


def safe_config(**changes):
    config = {
        'features': {name: False for name in ISOLATED_FEATURES},
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
        'tools': {'experimental_request_user_input': {'enabled': False}},
    }
    config.update(changes)
    return {'config': config, 'origins': {}}


class ScriptedRPC:
    def __init__(self, command, cwd, env=None, timeout=10, *, script=None, notifications=None):
        self.command = command
        self.cwd = Path(cwd)
        self.env = env
        self.timeout = timeout
        self.script = script or {}
        self.notifications = []
        self.after_turn_notifications = list(notifications or [])
        self.calls = []
        self.running = False
        self.closed = False

    def start(self):
        self.running = True
        return self

    def call(self, method, params, timeout=None):
        self.calls.append((method, params))
        value = self.script[method]
        result = value(params, self) if callable(value) else value
        if method == 'turn/start':
            self.notifications.extend(self.after_turn_notifications)
            self.after_turn_notifications.clear()
        return result

    def drain_notifications(self):
        if not self.notifications:
            return []
        return self.notifications.pop(0)

    def close(self):
        self.closed = True
        self.running = False


def choice():
    return {'provider': 'codex', 'mode': 'subscription', 'catalog_id': 'catalog-1',
            'model': 'gpt-5.6-terra', 'effort': 'high',
            'display_name': 'GPT-5.6-Terra', 'fetched_at': '2026-09-07T00:00:00+00:00',
            'validated_catalog_id': 'catalog-1',
            'latest_fetched_at': '2026-09-07T00:00:00+00:00'}


def factory_for(tmp_path, *, config=None, account=None, skills=None, notifications=None,
                started=None):
    created = []
    script = {
        'account/read': account or {'account': {'type': 'chatgpt', 'planType': 'plus'}, 'requiresOpenaiAuth': True},
        'config/read': config or safe_config(),
        'skills/list': skills or {'data': [{'cwd': str(tmp_path / 'data/codex-generation-runtime'), 'skills': [], 'errors': []}]},
        'thread/start': started or {
            'thread': {'id': 'thread-1', 'ephemeral': True},
            'instructionSources': [], 'model': 'gpt-5.6-terra', 'modelProvider': 'openai',
            'cwd': str(tmp_path / 'data/codex-generation-runtime'),
            'approvalPolicy': 'never', 'approvalsReviewer': 'user',
            'sandbox': {'type': 'readOnly', 'access': {'type': 'restricted', 'includePlatformDefaults': False, 'readableRoots': []}},
        },
        'turn/start': {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': [], 'error': None}},
        'turn/interrupt': {},
    }

    def make(command, cwd, env=None, timeout=10):
        rpc = ScriptedRPC(command, cwd, env, timeout, script=script, notifications=notifications)
        created.append(rpc)
        return rpc
    return make, created


def model(tmp_path, monkeypatch, **fixture):
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    monkeypatch.setattr(codex_understanding, '_native_tool_isolation_supported',
                        lambda _config: True)
    factory, created = factory_for(tmp_path, **fixture)
    store = SimpleNamespace(data_dir=tmp_path / 'data')
    return codex_understanding.CodexUnderstandingModel(
        store, rpc_factory=factory, version_reader=lambda _path: True), created


def test_unsafe_effective_configuration_fails_before_thread_or_input(tmp_path, monkeypatch):
    config = safe_config()
    config['config']['mcp_servers'] = {'inherited': {'enabled': True, 'url': 'https://example.invalid'}}
    subject, created = model(tmp_path, monkeypatch, config=config)

    with pytest.raises(ModelError) as caught:
        subject.generate('PRIVATE INPUT', {'type': 'object'}, SimpleNamespace(is_set=lambda: False),
                         selection=choice())

    assert caught.value.reason == 'isolation_unavailable'
    assert [method for method, _ in created[0].calls] == ['account/read', 'config/read', 'skills/list']
    assert 'PRIVATE INPUT' not in repr(created[0].calls)


def test_enabled_or_unreadable_skills_fail_before_thread_start(tmp_path, monkeypatch):
    for skills in (
        {'data': [{'cwd': 'x', 'skills': [{'enabled': True, 'path': '/private/skill'}], 'errors': []}]},
        {'data': [{'cwd': 'x', 'skills': [], 'errors': [{'path': 'x', 'message': 'bad'}]}]},
    ):
        subject, created = model(tmp_path, monkeypatch, skills=skills)
        with pytest.raises(ModelError) as caught:
            subject.generate('PRIVATE INPUT', {'type': 'object'}, SimpleNamespace(is_set=lambda: False),
                             selection=choice())
        assert caught.value.reason == 'isolation_unavailable'
        assert [method for method, _ in created[0].calls] == ['account/read', 'config/read', 'skills/list']


@pytest.mark.parametrize('change', [
    {'instructions': 'inherited instruction'},
    {'model_instructions_file': '/private/instructions.md'},
    {'model_provider': 'custom'},
    {'model_providers': {'custom': {'base_url': 'https://example.invalid'}}},
    {'openai_base_url': 'https://example.invalid'},
    {'chatgpt_base_url': 'https://example.invalid'},
    {'notify': ['/tmp/leak-input']},
    {'include_permissions_instructions': True},
    {'include_apps_instructions': True},
    {'include_collaboration_mode_instructions': True},
    {'include_environment_context': True},
    {'orchestrator': {'skills': {'enabled': True}, 'mcp': {'enabled': False}}},
    {'skills': {'include_instructions': True}},
])
def test_inherited_instructions_or_custom_provider_fail_before_transfer(tmp_path, monkeypatch, change):
    config = safe_config(**change)
    completed = {'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': {
        'id': 'turn-1', 'status': 'completed',
        'items': [{'type': 'agentMessage', 'id': 'message-1', 'phase': 'final_answer', 'text': '{}'}],
    }}}
    subject, created = model(tmp_path, monkeypatch, config=config, notifications=[[completed]])
    with pytest.raises(ModelError) as caught:
        subject.generate('PRIVATE INPUT', {'type': 'object'}, SimpleNamespace(is_set=lambda: False),
                         selection=choice())
    assert caught.value.reason == 'isolation_unavailable'
    assert [method for method, _ in created[0].calls] == ['account/read', 'config/read', 'skills/list']
    assert 'PRIVATE INPUT' not in repr(created[0].calls)


def test_non_chatgpt_account_never_starts_a_thread(tmp_path, monkeypatch):
    subject, created = model(tmp_path, monkeypatch,
        account={'account': {'type': 'apiKey'}, 'requiresOpenaiAuth': True})
    with pytest.raises(ModelError) as caught:
        subject.generate('PRIVATE INPUT', {'type': 'object'}, SimpleNamespace(is_set=lambda: False),
                         selection=choice())
    assert caught.value.reason == 'subscription_required'
    assert [method for method, _ in created[0].calls] == ['account/read']


def test_generation_uses_ephemeral_isolated_thread_and_authoritative_completion(tmp_path, monkeypatch):
    output = json.dumps({'summary': '확인'}, ensure_ascii=False)
    completed = {'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': {
        'id': 'turn-1', 'status': 'completed',
        'items': [{'type': 'agentMessage', 'id': 'message-1', 'phase': 'final_answer', 'text': output}],
    }}}
    subject, created = model(tmp_path, monkeypatch, notifications=[[completed]])

    result = subject.generate('민감한 업무 설명', {'type': 'object', 'additionalProperties': False},
                              SimpleNamespace(is_set=lambda: False), selection=choice())

    assert result == {'text': output, 'model': 'gpt-5.6-terra'}
    rpc = created[0]
    assert rpc.closed
    assert rpc.calls[:3] == [
        ('account/read', {'refreshToken': False}),
        ('config/read', {'cwd': str(rpc.cwd), 'includeLayers': False}),
        ('skills/list', {'cwds': [str(rpc.cwd)], 'forceReload': True}),
    ]
    start = dict(rpc.calls)["thread/start"]
    assert start['ephemeral'] is True
    assert start['model'] == 'gpt-5.6-terra'
    assert start['cwd'] == str(rpc.cwd)
    assert start['approvalPolicy'] == 'never' and start['sandbox'] == 'read-only'
    assert start['baseInstructions'] and start['developerInstructions']
    assert start['config']['project_doc_max_bytes'] == 0
    turn = dict(rpc.calls)['turn/start']
    assert turn['input'] == [{'type': 'text', 'text': '민감한 업무 설명'}]
    assert turn['model'] == 'gpt-5.6-terra' and turn['effort'] == 'high'
    assert turn['outputSchema'] == {'type': 'object', 'additionalProperties': False}
    assert turn['sandboxPolicy']['type'] == 'readOnly'
    command = ' '.join(rpc.command)
    for feature in ISOLATED_FEATURES:
        assert f'features.{feature}=false' in command
    assert 'web_search="disabled"' in command
    assert 'tools.view_image=false' not in command
    for setting in (
        'orchestrator.skills.enabled=false', 'orchestrator.mcp.enabled=false',
        'include_permissions_instructions=false', 'include_apps_instructions=false',
        'include_collaboration_mode_instructions=false',
        'include_environment_context=false', 'skills.include_instructions=false',
    ):
        assert setting in command


def test_made_up_native_tool_setting_does_not_replace_environmentless_profile(tmp_path, monkeypatch):
    """A made-up view_image override cannot replace the independently checked
    process, thread and turn environmentless profile.
    """
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    config = safe_config()
    config['config']['tools'] = {'view_image': False}
    factory, created = factory_for(tmp_path, config=config)
    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'), rpc_factory=factory,
        version_reader=lambda _path: True)

    with pytest.raises(ModelError) as caught:
        subject.generate('PRIVATE INPUT', {'type': 'object'},
                         SimpleNamespace(is_set=lambda: False), selection=choice())

    assert caught.value.reason == 'isolation_unavailable'
    assert [method for method, _ in created[0].calls] == [
        'account/read', 'config/read', 'skills/list',
    ]
    assert 'thread/start' not in repr(created[0].calls)
    assert 'PRIVATE INPUT' not in repr(created[0].calls)
    assert 'tools.view_image=false' not in ' '.join(created[0].command)


def test_tool_activity_is_rejected_and_interrupted(tmp_path, monkeypatch):
    tool = {'method': 'item/started', 'params': {'threadId': 'thread-1', 'turnId': 'turn-1',
            'item': {'type': 'commandExecution', 'id': 'tool-1'}}}
    subject, created = model(tmp_path, monkeypatch, notifications=[[tool]])
    with pytest.raises(ModelError) as caught:
        subject.generate('input', {'type': 'object'}, SimpleNamespace(is_set=lambda: False),
                         selection=choice())
    assert caught.value.reason == 'isolation_violation'
    assert ('turn/interrupt', {'threadId': 'thread-1', 'turnId': 'turn-1'}) in created[0].calls


def test_model_reroute_is_a_mismatch_not_a_success(tmp_path, monkeypatch):
    rerouted = {'method': 'model/rerouted', 'params': {
        'threadId': 'thread-1', 'turnId': 'turn-1',
        'fromModel': 'gpt-5.6-terra', 'toModel': 'substitute',
        'reason': 'highRiskCyberActivity',
    }}
    subject, created = model(tmp_path, monkeypatch, notifications=[[rerouted]])
    with pytest.raises(ModelError) as caught:
        subject.generate('input', {'type': 'object'}, SimpleNamespace(is_set=lambda: False),
                         selection=choice())
    assert caught.value.reason == 'model_mismatch'
    assert ('turn/interrupt', {'threadId': 'thread-1', 'turnId': 'turn-1'}) in created[0].calls


def test_cancel_event_interrupts_without_accepting_output(tmp_path, monkeypatch):
    cancel = SimpleNamespace(value=False, is_set=lambda: cancel.value)

    def after_start(_params, rpc):
        cancel.value = True
        return {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': [], 'error': None}}

    factory, created = factory_for(tmp_path, notifications=[])
    original = factory

    def make(*args, **kwargs):
        rpc = original(*args, **kwargs)
        rpc.script['turn/start'] = after_start
        def interrupt(_params, current):
            current.notifications.append([{'method': 'turn/completed', 'params': {
                'threadId': 'thread-1', 'turn': {
                    'id': 'turn-1', 'status': 'interrupted', 'items': []}}}])
            return {}
        rpc.script['turn/interrupt'] = interrupt
        return rpc

    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    monkeypatch.setattr(codex_understanding, '_native_tool_isolation_supported',
                        lambda _config: True)
    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'), rpc_factory=make,
        version_reader=lambda _path: True)

    result = subject.generate('input', {'type': 'object'}, cancel, selection=choice())
    assert result == {'text': '', 'model': 'gpt-5.6-terra'}
    assert ('turn/interrupt', {'threadId': 'thread-1', 'turnId': 'turn-1'}) in created[0].calls


def test_generation_rpc_has_a_separate_narrow_method_boundary(tmp_path):
    rpc = codex_understanding.GenerationRPC(['/tools/codex'], cwd=tmp_path)
    for method in ('account/login/start', 'command/exec', 'mcpServer/tool/call', 'thread/inject_items'):
        with pytest.raises(ValueError):
            rpc.call(method, {})


def test_unknown_codex_version_fails_before_starting_transport(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    factory, created = factory_for(tmp_path)
    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'), rpc_factory=factory,
        version_reader=lambda _path: False)
    with pytest.raises(ModelError) as caught:
        subject.generate('PRIVATE INPUT', {'type': 'object'}, SimpleNamespace(is_set=lambda: False),
                         selection=choice())
    assert caught.value.reason == 'isolation_unavailable'
    assert created == []


def test_discovered_mcp_and_skills_are_disabled_in_a_fresh_process_before_input(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    monkeypatch.setattr(codex_understanding, '_native_tool_isolation_supported',
                        lambda _config: True)
    created = []
    runtime = tmp_path / 'data/codex-generation-runtime'
    unsafe = safe_config()
    unsafe['config']['mcp_servers'] = {'fixture_server': {'enabled': True}}
    skill = {'enabled': True, 'path': '/fixture/SKILL.md'}
    completed = {'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': {
        'id': 'turn-1', 'status': 'completed',
        'items': [{'type': 'agentMessage', 'id': 'm', 'phase': 'final_answer', 'text': '{}'}]}}}

    def make(command, cwd, env=None, timeout=10):
        second = len(created) == 1
        script = {
            'account/read': {'account': {'type': 'chatgpt'}, 'requiresOpenaiAuth': True},
            'config/read': safe_config() if second else unsafe,
            'skills/list': {'data': [{'cwd': str(runtime),
                'skills': [] if second else [skill], 'errors': []}]},
            'thread/start': {'thread': {'id': 'thread-1', 'ephemeral': True},
                'instructionSources': [], 'model': 'gpt-5.6-terra', 'modelProvider': 'openai',
                'cwd': str(runtime), 'approvalPolicy': 'never', 'approvalsReviewer': 'user',
                'sandbox': {'type': 'readOnly'}},
            'turn/start': {'turn': {'id': 'turn-1', 'status': 'inProgress', 'items': []}},
            'turn/interrupt': {},
        }
        rpc = ScriptedRPC(command, cwd, env, timeout, script=script,
                          notifications=[[completed]] if second else [])
        created.append(rpc)
        return rpc

    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'), rpc_factory=make,
        version_reader=lambda _path: True)
    assert subject.generate('PRIVATE INPUT', {'type': 'object'},
                            SimpleNamespace(is_set=lambda: False), selection=choice())['text'] == '{}'
    assert len(created) == 2 and created[0].closed
    assert all(method != 'thread/start' for method, _ in created[0].calls)
    assert 'PRIVATE INPUT' not in repr(created[0].calls)
    command = ' '.join(created[1].command)
    assert 'mcp_servers.fixture_server.enabled=false' in command
    assert 'skills.config=[' in command and '/fixture/SKILL.md' in command


def test_missing_or_unvalidated_selection_fails_before_provider_discovery(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_understanding, 'find_codex',
                        lambda: pytest.fail('provider must remain untouched'))
    subject = codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'))
    missing_validation = choice()
    missing_validation.pop('validated_catalog_id')
    for invalid in (None, {}, missing_validation, {**choice(), 'effort': ''},
                    {**choice(), 'provider': 'claude'}):
        with pytest.raises(ModelError) as caught:
            subject.generate('PRIVATE INPUT', {'type': 'object'},
                             SimpleNamespace(is_set=lambda: False), selection=invalid)
        assert caught.value.reason == 'provider_unavailable'


def test_provider_model_mismatch_stops_before_turn_input(tmp_path, monkeypatch):
    started = {
        'thread': {'id': 'thread-1', 'ephemeral': True}, 'instructionSources': [],
        'model': 'unexpected-model', 'modelProvider': 'openai',
        'cwd': str(tmp_path / 'data/codex-generation-runtime'),
        'approvalPolicy': 'never', 'sandbox': {'type': 'readOnly'},
    }
    subject, created = model(tmp_path, monkeypatch, started=started)
    with pytest.raises(ModelError) as caught:
        subject.generate('PRIVATE INPUT', {'type': 'object'},
                         SimpleNamespace(is_set=lambda: False), selection=choice())
    assert caught.value.reason == 'provider_unavailable'
    assert not any(method == 'turn/start' for method, _ in created[0].calls)
    assert 'PRIVATE INPUT' not in repr(created[0].calls)
