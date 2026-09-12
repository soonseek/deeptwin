from pathlib import Path

import pytest

from app import codex_understanding
from app.understanding import ModelError


def test_generation_disables_process_environments_without_relocating_auth(tmp_path, monkeypatch):
    original = {'HOME': str(tmp_path), 'CODEX_HOME': str(tmp_path / 'official-auth')}
    monkeypatch.setattr(codex_understanding, 'process_environment', lambda: original.copy())
    environment = codex_understanding._generation_environment()
    assert environment == {**original, 'CODEX_EXEC_SERVER_URL': 'none',
                           'CODEX_INTERNAL_APP_SERVER_REMOTE_CONTROL_DISABLED': '1'}
    assert original == {'HOME': str(tmp_path), 'CODEX_HOME': str(tmp_path / 'official-auth')}


@pytest.mark.parametrize('custom_home', [False, True])
def test_existing_environment_configuration_fails_before_provider_start(tmp_path, monkeypatch, custom_home):
    config_home = tmp_path / ('official-auth' if custom_home else '.codex')
    config_home.mkdir()
    (config_home / 'environments.toml').touch()
    environment = {'HOME': str(tmp_path)}
    if custom_home:
        environment['CODEX_HOME'] = str(config_home)
    monkeypatch.setattr(codex_understanding, 'process_environment', lambda: environment)
    with pytest.raises(ModelError) as caught:
        codex_understanding._generation_environment()
    assert caught.value.reason == 'isolation_unavailable'


def test_dangling_environment_configuration_symlink_is_not_treated_as_absent(tmp_path, monkeypatch):
    config_home = tmp_path / '.codex'
    config_home.mkdir()
    (config_home / 'environments.toml').symlink_to(tmp_path / 'absent.toml')
    monkeypatch.setattr(codex_understanding, 'process_environment', lambda: {'HOME': str(tmp_path)})
    with pytest.raises(ModelError):
        codex_understanding._generation_environment()


@pytest.mark.parametrize('environment', [{}, {'HOME': ''}, {'CODEX_HOME': 'relative'}])
def test_unknown_auth_location_is_not_guessed(environment, monkeypatch):
    monkeypatch.setattr(codex_understanding, 'process_environment', lambda: environment)
    with pytest.raises(ModelError):
        codex_understanding._generation_environment()
