"""Fail-closed isolated Codex generation, separate from authentication.

The caller owns consent, selection freshness and durable pre-transfer audit.
Account and isolation checks precede thread creation and reference transfer.
The critic transport remains internal until its guarded runner is connected.
"""

import json
from pathlib import Path
import re
import subprocess
import threading
import time

from .codex_connection import find_codex, process_environment
from .codex_rpc import CodexRPC, CodexRPCError, _MAX_PENDING, _Pending
from .generation_profiles import GenerationPurpose, profile_for
from .understanding import ModelError


_GENERATION_METHODS = {
    'initialize', 'account/read', 'config/read', 'skills/list',
    'thread/start', 'turn/start', 'turn/interrupt',
}
_ISOLATED_FEATURES = {
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
_STRUCTURED_FEATURES = {'token_budget', 'current_time_reminder', 'multi_agent_v2'}


class _CancelledBeforeTransfer(Exception):
    """A cancel arrived before the prepared input was transferred."""
_SAFE_ITEM_TYPES = {'userMessage', 'agentMessage', 'reasoning'}
_BASE_INSTRUCTIONS = profile_for(
    GenerationPurpose.WORK_UNDERSTANDING).base_instructions
_DEVELOPER_INSTRUCTIONS = profile_for(
    GenerationPurpose.WORK_UNDERSTANDING).developer_instructions


def _generation_environment():
    """Keep managed auth in place, but create no process-level exec environment.

    In 0.144.4 environments.toml takes precedence over the official `none`
    switch and can start remote connections before a thread is created. Refuse
    any such configuration without opening it or modifying the user's files.
    """
    environment = process_environment()
    location = environment.get('CODEX_HOME')
    if location is None:
        home = environment.get('HOME')
        if not home or not Path(home).is_absolute():
            raise ModelError('isolation_unavailable')
        location = str(Path(home) / '.codex')
    if not location or not Path(location).is_absolute():
        raise ModelError('isolation_unavailable')
    try:
        (Path(location) / 'environments.toml').lstat()
    except FileNotFoundError:
        pass
    except OSError:
        raise ModelError('isolation_unavailable') from None
    else:
        raise ModelError('isolation_unavailable')
    return {**environment, 'CODEX_EXEC_SERVER_URL': 'none',
            'CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED': '1'}


def _supported_version(executable):
    try:
        result = subprocess.run(
            [executable, '--version'], env=process_environment(),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, timeout=2,
            check=False, shell=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return result.returncode == 0 and result.stdout.strip() == 'codex-cli 0.144.4'


def generation_available():
    """Local compatibility hint only, never auth, a thread or a model call.

    Every explicit request still repeats the complete account/config/skills/
    instructions preflight before transferring its frozen input.
    """
    executable = find_codex()
    if not executable or not _supported_version(executable):
        return False
    try:
        _generation_environment()
    except ModelError:
        return False
    return True


class GenerationRPC(CodexRPC):
    """Codex transport whose callable surface cannot perform auth or tools."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.isolation_violation = False

    def _initialize_params(self):
        return {**super()._initialize_params(), 'capabilities': {'experimentalApi': True}}

    def call(self, method, params, timeout=None):
        if method not in _GENERATION_METHODS:
            raise ValueError('허용되지 않은 Codex 생성 요청입니다.')
        if params is not None and not isinstance(params, dict):
            raise ValueError('Codex 요청 항목은 객체여야 합니다.')
        duration = self.timeout if timeout is None else timeout
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValueError('Codex timeout must be positive')

        with self._state_lock:
            if not self.running:
                raise CodexRPCError('Codex 연결을 사용할 수 없습니다.')
            if len(self._pending) >= _MAX_PENDING:
                raise CodexRPCError('Codex 요청이 너무 많습니다.')
            request_id = self._next_id
            self._next_id += 1
            pending = _Pending(threading.Event())
            self._pending[request_id] = pending
        try:
            self._send({'id': request_id, 'method': method, 'params': params})
        except (CodexRPCError, ValueError):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise
        if not pending.event.wait(float(duration)):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise CodexRPCError('Codex 응답 시간이 초과되었습니다.')
        with self._state_lock:
            self._pending.pop(request_id, None)
        if pending.error is not None:
            raise CodexRPCError(pending.error)
        return pending.result

    def _receive(self, message):
        if 'method' in message:
            with self._state_lock:
                if len(self._notifications) >= self._notifications.maxlen:
                    # A truncated event stream cannot establish safe completion.
                    self.isolation_violation = True
        if 'method' in message and 'id' in message:
            with self._state_lock:
                self.isolation_violation = True
                self._notifications.append({'method': 'deeptwin/forbiddenServerRequest'})
        elif 'method' in message and _unsafe_notification(message):
            self.isolation_violation = True
        super()._receive(message)


def _command(executable):
    command = [executable, 'app-server', '--stdio']
    for feature in sorted(_ISOLATED_FEATURES):
        command.extend(('-c', f'features.{feature}=false'))
    for setting in (
        'web_search="disabled"',
        'project_doc_max_bytes=0', 'developer_instructions=""', 'notify=[]',
        'model_provider="openai"',
        'orchestrator.skills.enabled=false', 'orchestrator.mcp.enabled=false',
        'include_permissions_instructions=false',
        'include_apps_instructions=false',
        'include_collaboration_mode_instructions=false',
        'include_environment_context=false',
        'skills.include_instructions=false',
        'tools.experimental_request_user_input.enabled=false',
        'memories.use_memories=false', 'memories.generate_memories=false',
        'analytics.enabled=false', 'otel.exporter="none"',
        'otel.metrics_exporter="none"', 'otel.trace_exporter="none"',
        'otel.log_user_prompt=false',
    ):
        command.extend(('-c', setting))
    return command


def _safe_config(response, allow_enabled_mcp=False):
    if not isinstance(response, dict) or not isinstance(response.get('config'), dict):
        return False
    config = response['config']
    features = config.get('features')
    if not isinstance(features, dict) or any(
            features.get(name) is not False and not (
                name in _STRUCTURED_FEATURES and isinstance(features.get(name), dict)
                and features[name].get('enabled') is False)
            for name in _ISOLATED_FEATURES):
        return False
    if config.get('web_search') != 'disabled' or config.get('project_doc_max_bytes') != 0:
        return False
    if config.get('developer_instructions') not in {'', None}:
        return False
    if (config.get('instructions') is not None or config.get('model_instructions_file') is not None
            or config.get('model_provider') != 'openai'
            or config.get('model_providers') not in ({}, None)
            or config.get('openai_base_url') is not None
            or config.get('chatgpt_base_url') is not None
            or config.get('notify') not in ([], None)):
        return False
    if any(config.get(name) is not False for name in (
            'include_permissions_instructions', 'include_apps_instructions',
            'include_collaboration_mode_instructions', 'include_environment_context')):
        return False
    orchestrator = config.get('orchestrator')
    if (not isinstance(orchestrator, dict)
            or not isinstance(orchestrator.get('skills'), dict)
            or orchestrator['skills'].get('enabled') is not False
            or not isinstance(orchestrator.get('mcp'), dict)
            or orchestrator['mcp'].get('enabled') is not False):
        return False
    skills = config.get('skills')
    if not isinstance(skills, dict) or skills.get('include_instructions') is not False:
        return False
    tool_config = config.get('tools')
    # ToolsV2 projects only web_search, although ConfigToml honors the exact
    # question-tool override. Do not pretend this response proves its absence;
    # client question requests are refused and invalidate the result as well.
    if (not isinstance(tool_config, dict)
            or set(tool_config) - {'web_search', 'experimental_request_user_input'}):
        return False
    if 'experimental_request_user_input' in tool_config:
        question_tool = tool_config['experimental_request_user_input']
        if not isinstance(question_tool, dict) or question_tool.get('enabled') is not False:
            return False
    servers = config.get('mcp_servers', {})
    if not isinstance(servers, dict):
        return False
    if not all(isinstance(value, dict) and isinstance(value.get('enabled', True), bool)
               for value in servers.values()):
        return False
    return allow_enabled_mcp or all(value.get('enabled', True) is False for value in servers.values())


def _native_tool_isolation_supported(config_response):
    """Check the config half of our pinned environmentless generation profile.

    0.144.4 with no process/thread/turn environments omits shell, apply_patch,
    permissions and view_image from the model's tool registry. Independent
    MCP, skill, hosted and extension capabilities must also be disabled.
    Internal update_plan remains registered; any plan/tool event rejects the
    response. This is NOT a claim of zero internal tools or OS isolation.
    Exact version, environment selection and instruction sources are checked
    separately before any user input is transferred.
    """
    return _safe_config(config_response)


def _safe_skills(response, runtime, allow_enabled=False):
    if not isinstance(response, dict) or not isinstance(response.get('data'), list):
        return False
    if len(response['data']) != 1 or response['data'][0].get('cwd') != str(runtime):
        return False
    for entry in response['data']:
        if (not isinstance(entry, dict) or not isinstance(entry.get('skills'), list)
                or not isinstance(entry.get('errors'), list) or entry['errors']):
            return False
        if any(not isinstance(skill, dict) or not isinstance(skill.get('enabled'), bool)
               or (not allow_enabled and skill['enabled'] is not False) for skill in entry['skills']):
            return False
    return True


def _disabling_overrides(config_response, skills_response, runtime):
    if (not _safe_config(config_response, allow_enabled_mcp=True)
            or not _safe_skills(skills_response, runtime, allow_enabled=True)):
        return None
    config = config_response['config']
    server_ids = [name for name, value in config.get('mcp_servers', {}).items()
                  if value.get('enabled', True)]
    skills = [skill for entry in skills_response['data'] for skill in entry['skills']
              if skill['enabled']]
    if len(server_ids) > 64 or len(skills) > 128:
        return None
    if any(not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', name)
           for name in server_ids):
        return None
    paths = []
    for skill in skills:
        path = skill.get('path')
        if (not isinstance(path, str) or len(path) > 2048 or '\x00' in path
                or not Path(path).is_absolute()):
            return None
        paths.append(path)
    overrides = []
    for name in server_ids:
        overrides.extend(('-c', f'mcp_servers.{name}.enabled=false'))
    if paths:
        value = 'skills.config=[' + ','.join(
            '{path=' + json.dumps(path, ensure_ascii=False) + ',enabled=false}'
            for path in paths) + ']'
        overrides.extend(('-c', value))
    return overrides


def _safe_account(response):
    return (isinstance(response, dict) and isinstance(response.get('account'), dict)
            and response['account'].get('type') == 'chatgpt')


def _valid_selection(selection):
    required = {'provider', 'mode', 'catalog_id', 'model', 'effort',
                'display_name', 'fetched_at', 'validated_catalog_id',
                'latest_fetched_at'}
    optional = set()
    if (not isinstance(selection, dict) or not required.issubset(selection)
            or set(selection) - required - optional
            or selection.get('provider') != 'codex'
            or selection.get('mode') != 'subscription'):
        return False
    return all(isinstance(selection.get(name), str)
               and 0 < len(selection[name]) <= 300
               for name in required - {'provider', 'mode'})


def _unsafe_notification(notification):
    if not isinstance(notification, dict) or not isinstance(notification.get('method'), str):
        return True
    if notification['method'] == 'deeptwin/forbiddenServerRequest':
        return True
    if notification['method'] in {
            'skills/changed', 'config/changed', 'config/mcpServer/reload',
            'mcpServer/startupStatus/updated', 'app/list/updated', 'turn/plan/updated'}:
        return True
    if notification['method'] not in {'item/started', 'item/completed'}:
        return False
    params = notification.get('params')
    item = params.get('item') if isinstance(params, dict) else None
    return not isinstance(item, dict) or item.get('type') not in _SAFE_ITEM_TYPES


class _CodexIsolatedModel:
    @property
    def runtime_profile(self):
        # This identifies the implemented/requested boundary, not a claim that
        # this request's preflight or inference has already succeeded.
        return {'id': 'codex-0.144.4-environmentless-v1', 'cli_version': '0.144.4',
                'environment_mode': 'none', 'auth_mode': 'managed_chatgpt',
                'native_resource_tools': 'disabled', 'internal_tool_attempts': 'rejected'}

    def __init__(self, store, rpc_factory=None, timeout=120, version_reader=None, *, purpose):
        self._instruction_profile = profile_for(purpose)
        self.store = store
        self.rpc_factory = rpc_factory or GenerationRPC
        self.timeout = timeout
        self.version_reader = version_reader or _supported_version

    @property
    def instruction_profile(self):
        return self._instruction_profile

    def _runtime(self):
        runtime = self.store.data_dir / 'codex-generation-runtime'
        if runtime.is_symlink():
            raise ModelError('isolation_unavailable')
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        runtime.chmod(0o700)
        return runtime

    @staticmethod
    def _interrupt(rpc, thread_id, turn_id, confirm=False):
        try:
            rpc.call('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id}, timeout=2)
        except Exception:
            return False
        if not confirm:
            return True
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            for notification in rpc.drain_notifications():
                params = notification.get('params') if isinstance(notification, dict) else None
                turn = params.get('turn') if isinstance(params, dict) else None
                if (notification.get('method') == 'turn/completed'
                        and params.get('threadId') == thread_id
                        and isinstance(turn, dict) and turn.get('id') == turn_id
                        and turn.get('status') == 'interrupted'):
                    return True
            time.sleep(0.01)
        return False

    @staticmethod
    def _transport_clean(rpc):
        notifications = rpc.drain_notifications()
        return not getattr(rpc, 'isolation_violation', False) and not any(
            _unsafe_notification(item) for item in notifications)

    def generate(self, prompt, schema, cancel_event, *, selection=None):
        if (not isinstance(prompt, str) or not isinstance(schema, dict)
                or not _valid_selection(selection)):
            raise ModelError('provider_unavailable')
        # One deadline covers the whole lifecycle, preflight included; a
        # cancel observed here spends no provider process at all.
        overall_deadline = time.monotonic() + self.timeout

        def _gate():
            if cancel_event.is_set():
                raise _CancelledBeforeTransfer
            if time.monotonic() >= overall_deadline:
                raise ModelError('timeout')

        if cancel_event.is_set():
            return {'text': '', 'model': 'cancelled-before-transfer'}
        executable = find_codex()
        if not executable:
            raise ModelError('provider_unavailable')
        if not self.version_reader(executable):
            raise ModelError('isolation_unavailable')
        runtime = self._runtime()
        base_command = _command(executable)
        rpc = self.rpc_factory(base_command, cwd=runtime,
                               env=_generation_environment(), timeout=10)
        thread_id = turn_id = None
        actual_model = ''
        try:
            rpc.start()
            _gate()
            if not _safe_account(rpc.call('account/read', {'refreshToken': False})):
                raise ModelError('subscription_required')
            _gate()
            config = rpc.call('config/read', {'cwd': str(runtime), 'includeLayers': False})
            _gate()
            skills = rpc.call('skills/list', {'cwds': [str(runtime)], 'forceReload': True})
            _gate()
            if not self._transport_clean(rpc):
                raise ModelError('isolation_unavailable')
            if not (_safe_config(config) and _safe_skills(skills, runtime)):
                overrides = _disabling_overrides(config, skills, runtime)
                if not overrides:
                    raise ModelError('isolation_unavailable')
                rpc.close()
                _gate()
                rpc = self.rpc_factory(base_command + overrides, cwd=runtime,
                                       env=_generation_environment(), timeout=10)
                rpc.start()
                _gate()
                if not _safe_account(rpc.call('account/read', {'refreshToken': False})):
                    raise ModelError('subscription_required')
                _gate()
                config = rpc.call('config/read', {'cwd': str(runtime), 'includeLayers': False})
                _gate()
                skills = rpc.call('skills/list', {'cwds': [str(runtime)], 'forceReload': True})
                _gate()
                if (not _safe_config(config) or not _safe_skills(skills, runtime)
                        or not self._transport_clean(rpc)):
                    raise ModelError('isolation_unavailable')
            if not _native_tool_isolation_supported(config):
                raise ModelError('isolation_unavailable')
            _gate()

            thread_config = {
                'project_doc_max_bytes': 0,
                'developer_instructions': '',
                'web_search': 'disabled',
                'features': {name: False for name in _ISOLATED_FEATURES},
                'orchestrator': {
                    'skills': {'enabled': False},
                    'mcp': {'enabled': False},
                },
                'include_permissions_instructions': False,
                'include_apps_instructions': False,
                'include_collaboration_mode_instructions': False,
                'include_environment_context': False,
                'skills': {'include_instructions': False},
                'tools': {'experimental_request_user_input': {'enabled': False}},
            }
            started = rpc.call('thread/start', {
                'serviceName': 'deeptwin', 'cwd': str(runtime),
                'model': selection['model'],
                'modelProvider': 'openai', 'approvalPolicy': 'never',
                'sandbox': 'read-only', 'ephemeral': True,
                'environments': [], 'dynamicTools': [], 'selectedCapabilityRoots': [],
                'baseInstructions': self.instruction_profile.base_instructions,
                'developerInstructions': self.instruction_profile.developer_instructions,
                'config': thread_config,
            })
            if not isinstance(started, dict) or started.get('instructionSources') != []:
                raise ModelError('isolation_unavailable')
            thread = started.get('thread')
            if (not isinstance(thread, dict) or not isinstance(thread.get('id'), str)
                    or thread.get('ephemeral') is not True
                    or started.get('modelProvider') != 'openai'
                    or started.get('approvalPolicy') != 'never'
                    or started.get('cwd') != str(runtime)):
                raise ModelError('isolation_unavailable')
            sandbox = started.get('sandbox')
            if not isinstance(sandbox, dict) or sandbox.get('type') != 'readOnly':
                raise ModelError('isolation_unavailable')
            actual_model = started.get('model')
            if (not isinstance(actual_model, str) or not 0 < len(actual_model) <= 200
                    or actual_model != selection['model']):
                raise ModelError('provider_unavailable')
            thread_id = thread['id']

            if cancel_event.is_set():
                return {'text': '', 'model': actual_model}
            if not self._transport_clean(rpc):
                raise ModelError('isolation_unavailable')

            turn_started = rpc.call('turn/start', {
                'threadId': thread_id, 'input': [{'type': 'text', 'text': prompt}],
                'environments': [],
                'cwd': str(runtime), 'approvalPolicy': 'never',
                'sandboxPolicy': {'type': 'readOnly', 'networkAccess': False},
                'outputSchema': schema,
                'model': selection['model'], 'effort': selection['effort'],
            })
            turn = turn_started.get('turn') if isinstance(turn_started, dict) else None
            if (not isinstance(turn, dict) or not isinstance(turn.get('id'), str)
                    or turn.get('status') != 'inProgress'):
                raise ModelError('provider_unavailable')
            turn_id = turn['id']
            deadline = overall_deadline
            completed_finals = {}
            while time.monotonic() < deadline:
                if cancel_event.is_set():
                    if self._interrupt(rpc, thread_id, turn_id, confirm=True):
                        return {'text': '', 'model': actual_model}
                    raise ModelError('timeout')
                notifications = rpc.drain_notifications()
                # Inspect the whole batch before accepting its completion: an
                # unsafe event can follow it, or have fallen out of the queue.
                if any(item.get('method') == 'model/rerouted' for item in notifications
                       if isinstance(item, dict)):
                    self._interrupt(rpc, thread_id, turn_id)
                    raise ModelError('model_mismatch')
                if (getattr(rpc, 'isolation_violation', False)
                        or any(_unsafe_notification(item) for item in notifications)):
                    self._interrupt(rpc, thread_id, turn_id)
                    raise ModelError('isolation_violation')
                for notification in notifications:
                    if notification.get('method') == 'item/completed':
                        params = notification.get('params')
                        if (not isinstance(params, dict) or params.get('threadId') != thread_id
                                or params.get('turnId') != turn_id):
                            raise ModelError('provider_unavailable')
                        item = params['item']  # Validated by the whole-batch safety check.
                        if item.get('type') == 'agentMessage' and item.get('phase') == 'final_answer':
                            item_id, text = item.get('id'), item.get('text')
                            if (not isinstance(item_id, str) or not item_id
                                    or not isinstance(text, str)
                                    or len(text.encode('utf-8')) > 64_000
                                    or (completed_finals and completed_finals != {item_id: text})):
                                raise ModelError('provider_unavailable')
                            completed_finals[item_id] = text
                        continue
                    if notification.get('method') != 'turn/completed':
                        continue
                    params = notification.get('params')
                    completed = params.get('turn') if isinstance(params, dict) else None
                    if (not isinstance(params, dict) or params.get('threadId') != thread_id
                            or not isinstance(completed, dict) or completed.get('id') != turn_id
                            or completed.get('status') != 'completed'):
                        raise ModelError('provider_unavailable')
                    items = completed.get('items')
                    if not isinstance(items, list) or any(
                            not isinstance(item, dict) or item.get('type') not in _SAFE_ITEM_TYPES
                            for item in items):
                        raise ModelError('isolation_violation')
                    finals = [item.get('text') for item in items
                              if item.get('type') == 'agentMessage'
                              and item.get('phase') == 'final_answer']
                    # Pinned 0.144.4 omits items from the terminal notification.
                    # Only complete final items from this exact turn may fill it;
                    # deltas and item-started events are never authoritative.
                    if not items and completed.get('itemsView') == 'notLoaded':
                        finals = list(completed_finals.values())
                    elif completed_finals and finals != list(completed_finals.values()):
                        raise ModelError('provider_unavailable')
                    if len(finals) != 1 or not isinstance(finals[0], str):
                        raise ModelError('provider_unavailable')
                    if getattr(rpc, 'isolation_violation', False):
                        self._interrupt(rpc, thread_id, turn_id)
                        raise ModelError('isolation_violation')
                    return {'text': finals[0], 'model': actual_model}
                time.sleep(0.01)
            self._interrupt(rpc, thread_id, turn_id)
            raise ModelError('timeout')
        except _CancelledBeforeTransfer:
            return {'text': '', 'model': 'cancelled-before-transfer'}
        except ModelError:
            raise
        except CodexRPCError as error:
            reason = 'timeout' if '시간이 초과' in str(error) else 'provider_unavailable'
            raise ModelError(reason) from None
        except Exception:
            raise ModelError('provider_unavailable') from None
        finally:
            rpc.close()


class CodexUnderstandingModel(_CodexIsolatedModel):
    def __init__(self, store, rpc_factory=None, timeout=120, version_reader=None):
        super().__init__(
            store,
            rpc_factory=rpc_factory,
            timeout=timeout,
            version_reader=version_reader,
            purpose=GenerationPurpose.WORK_UNDERSTANDING,
        )
