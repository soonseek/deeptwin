from app.tests.local_http import LocalTestClient as TestClient
import pytest

from app import codex_understanding, server
from app.understanding import ModelError


@pytest.mark.parametrize('supported', [False, True])
def test_runtime_availability_is_version_gated_and_never_starts_a_model(monkeypatch, supported):
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    monkeypatch.setattr(codex_understanding, '_supported_version', lambda executable: supported)
    monkeypatch.setattr(codex_understanding, '_generation_environment', lambda: {})
    monkeypatch.setattr(codex_understanding, 'GenerationRPC', lambda *a, **k: pytest.fail('no provider process'))
    assert codex_understanding.generation_available() is supported


def test_existing_external_environment_keeps_runtime_unavailable(monkeypatch):
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    monkeypatch.setattr(codex_understanding, '_supported_version', lambda executable: True)
    def rejected():
        raise ModelError('isolation_unavailable')
    monkeypatch.setattr(codex_understanding, '_generation_environment', rejected)
    assert codex_understanding.generation_available() is False


@pytest.mark.parametrize('available', [False, True])
def test_production_capability_uses_local_runtime_check_not_a_fixture_flag(tmp_path, monkeypatch, available):
    monkeypatch.setattr(codex_understanding, 'generation_available', lambda: available)
    with TestClient(server.create_development_app(tmp_path), base_url='http://127.0.0.1:4193') as client:
        flags = client.get('/api/bootstrap').json()['capabilities']
        assert flags['understanding_provider_ready'] is available
        assert flags['design_generation'] is False and flags['execution'] is False


def test_explicit_disabled_fixture_does_not_probe_the_real_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_understanding, 'generation_available', lambda: pytest.fail('no runtime check'))
    with TestClient(server.create_development_app(tmp_path, understanding_provider_ready=False),
                    base_url='http://127.0.0.1:4193') as client:
        assert client.get('/api/bootstrap').json()['capabilities']['understanding_provider_ready'] is False
