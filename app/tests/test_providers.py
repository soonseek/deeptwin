import subprocess
from unittest.mock import patch

import pytest

from app import providers


def test_installed_binaries_do_not_imply_authentication_or_execution(monkeypatch):
    monkeypatch.setattr(providers.shutil, 'which', lambda name: f'/tools/{name}')

    entries = providers.list_providers()

    assert [entry['id'] for entry in entries] == ['codex', 'claude']
    assert entries[0]['installed'] is True
    assert entries[0]['auth_status'] == 'unknown'
    assert all(entry['billing'] == 'unknown' for entry in entries)
    assert all(entry['capabilities'] == {'execution': False} for entry in entries)
    assert '로그인 확인 전' in entries[0]['message']
    claude = entries[1]
    assert claude['mode'] == 'api'
    assert claude['installation_required'] is False
    assert claude['installed'] is False
    assert claude['auth_status'] == 'unavailable'
    assert claude['connection'] == {'state': 'not_configured', 'adapter_status': 'available'}
    assert 'API' in claude['message'] and '미구현' not in claude['message']
    assert '사전 승인' not in claude['message'] and '구독' not in claude['message']
    assert claude['source_url'] == 'https://platform.claude.com/docs/en/api/overview'
    assert claude['default_mode'] == 'api'
    assert claude['modes'] == [{
        'id': 'api', 'auth_mode': 'api_key', 'billing': 'api',
        'label': 'Claude API', 'automatic_fallback': False,
        'catalog': 'anthropic:models',
    }]
    codex = entries[0]
    assert codex['default_mode'] == 'subscription'
    assert [(mode['id'], mode['billing']) for mode in codex['modes']] == [
        ('subscription', 'subscription'), ('api', 'api')
    ]
    assert all(mode['automatic_fallback'] is False for mode in codex['modes'])


def test_unavailable_binary_is_reported_without_claiming_auth(monkeypatch):
    monkeypatch.setattr(providers.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(providers, '_candidate_paths', lambda _provider: ())

    entries = providers.list_providers()

    assert all(entry['installed'] is False for entry in entries)
    assert all(entry['auth_status'] == 'unavailable' for entry in entries)
    assert all(entry['billing'] == 'unknown' for entry in entries)
    assert all(entry['capabilities']['execution'] is False for entry in entries)


def test_executable_standard_location_is_a_fallback(monkeypatch, tmp_path):
    fallback = tmp_path / 'codex'
    fallback.write_text('#!/bin/sh\n', encoding='utf-8')
    fallback.chmod(0o700)
    monkeypatch.setattr(providers.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(
        providers,
        '_candidate_paths',
        lambda provider: (fallback,) if provider == 'codex' else (),
    )

    codex, claude = providers.list_providers()

    assert codex['installed'] is True
    assert codex['auth_status'] == 'unknown'
    assert claude['installed'] is False


def test_discovery_never_runs_commands_or_exposes_environment_secrets(monkeypatch):
    monkeypatch.setattr(providers.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(providers, '_candidate_paths', lambda _provider: ())

    class UnreadEnvironment(dict):
        def __getitem__(self, key):
            raise AssertionError(f'Unexpected environment read: {key}')

        def get(self, key, default=None):
            raise AssertionError(f'Unexpected environment read: {key}')

    with monkeypatch.context() as guarded:
        guarded.setattr(providers.os, 'environ', UnreadEnvironment())
        guarded.setattr(providers.Path, 'read_text', lambda *_args, **_kwargs: pytest.fail('Authentication file read'))
        guarded.setattr(providers.Path, 'read_bytes', lambda *_args, **_kwargs: pytest.fail('Authentication file read'))
        with patch.object(subprocess, 'run') as run, patch.object(subprocess, 'Popen') as popen:
            result = providers.list_providers()

    run.assert_not_called()
    popen.assert_not_called()
    assert all(entry['billing'] == 'unknown' for entry in result)
    assert all(entry['capabilities'] == {'execution': False} for entry in result)


def test_claude_listing_never_looks_for_a_cli_or_auth_store(monkeypatch):
    searched = []

    def codex_only(name):
        searched.append(name)
        assert name == 'codex'
        return '/tools/codex'

    monkeypatch.setattr(providers.shutil, 'which', codex_only)
    monkeypatch.setattr(providers.Path, 'home', lambda: pytest.fail('Unexpected home/auth discovery'))

    claude = providers.list_providers()[1]

    assert searched == ['codex']
    assert claude['auth_status'] == 'unavailable'
    assert claude['capabilities'] == {'execution': False}


def test_legacy_cli_helpers_cannot_probe_claude(monkeypatch):
    monkeypatch.setattr(providers.shutil, 'which', lambda *_args: pytest.fail('Unexpected CLI discovery'))
    monkeypatch.setattr(providers.Path, 'home', lambda: pytest.fail('Unexpected home/auth discovery'))

    assert providers._candidate_paths('claude') == ()
    assert providers._installed('claude') is False


@pytest.mark.parametrize('mode', [0o600, 0o644])
def test_non_executable_fallback_is_not_an_install(monkeypatch, tmp_path, mode):
    fallback = tmp_path / 'codex'
    fallback.write_text('not executable', encoding='utf-8')
    fallback.chmod(mode)
    monkeypatch.setattr(providers.shutil, 'which', lambda _name: None)
    monkeypatch.setattr(
        providers,
        '_candidate_paths',
        lambda provider: (fallback,) if provider == 'codex' else (),
    )

    assert providers.list_providers()[0]['installed'] is False
