"""Read-only provider/mode discovery without account or credential probing."""

import os
import platform
import shutil
from copy import deepcopy
from pathlib import Path

_PROVIDERS = (
    {
        'id': 'codex',
        'label': 'Codex',
        'default_mode': 'subscription',
        'modes': [
            {
                'id': 'subscription', 'auth_mode': 'chatgpt', 'billing': 'subscription',
                'label': 'ChatGPT 구독', 'automatic_fallback': False,
                'catalog': 'app-server:model/list',
            },
            {
                'id': 'api', 'auth_mode': 'api_key', 'billing': 'api',
                'label': '별도 API', 'automatic_fallback': False,
                'catalog': 'openai:models',
            },
        ],
        'message': 'ChatGPT 구독이 기본이며 별도 API는 사용자가 명시적으로 선택합니다. 로그인 확인 전입니다.',
        'source_url': 'https://learn.chatgpt.com/docs/app-server',
    },
    {
        'id': 'claude',
        'label': 'Claude',
        'mode': 'api',
        'default_mode': 'api',
        'modes': [{
            'id': 'api', 'auth_mode': 'api_key', 'billing': 'api',
            'label': 'Claude API', 'automatic_fallback': False,
            'catalog': 'anthropic:models',
        }],
        'installation_required': False,
        'message': 'API 전용 · API 키를 연결한 뒤 현재 계정의 모델 목록을 조회합니다.',
        'source_url': 'https://platform.claude.com/docs/en/api/overview',
    },
)


def _candidate_paths(provider):
    """Return Codex installer locations without inspecting credential stores."""
    if provider != 'codex':
        return ()
    home = Path.home()
    system = platform.system()
    if system == 'Windows':
        local = Path(os.environ.get('LOCALAPPDATA', home / 'AppData/Local'))
        roaming = Path(os.environ.get('APPDATA', home / 'AppData/Roaming'))
        names = (f'{provider}.exe', f'{provider}.cmd')
        return tuple(
            path
            for name in names
            for path in (
                home / '.local/bin' / name,
                roaming / 'npm' / name,
                local / 'Programs' / provider / name,
            )
        )

    common = (
        home / '.local/bin' / provider,
        Path('/usr/local/bin') / provider,
        Path('/opt/homebrew/bin') / provider,
    )
    return common


def _installed(provider):
    if provider != 'codex':
        return False
    if shutil.which(provider) is not None:
        return True
    return any(path.is_file() and os.access(path, os.X_OK) for path in _candidate_paths(provider))


def list_providers():
    """Describe current capability without checking accounts, keys or API access."""
    result = []
    for provider in _PROVIDERS:
        provider = deepcopy(provider)
        if provider['id'] == 'claude':
            result.append({
                **provider,
                # Legacy consumers expect this field. Installation is not applicable
                # to Claude API; this is not an observation about a user's CLI.
                'installed': False,
                'auth_status': 'unavailable',
                'billing': 'unknown',
                'capabilities': {'execution': False},
                'connection': {'state': 'not_configured', 'adapter_status': 'available'},
            })
            continue
        installed = _installed(provider['id'])
        result.append({
            **provider,
            'installed': installed,
            'auth_status': 'unknown' if installed else 'unavailable',
            'billing': 'unknown',
            'capabilities': {'execution': False},
        })
    return result
