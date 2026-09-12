from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import time

import pytest

from app.codex_rpc import CodexRPC, CodexRPCError


FAKE = Path(__file__).parent / 'fixtures' / 'fake_codex_rpc.py'


def peer(timeout=1, *arguments):
    return CodexRPC([sys.executable, '-u', str(FAKE), *arguments], cwd=FAKE.parent, timeout=timeout)


def test_start_performs_exact_handshake_and_close_owns_process_lifecycle():
    rpc = peer().start()
    try:
        assert rpc.running is True
        assert rpc.call('account/read', {}) == {'account': None, 'requiresOpenaiAuth': True}
        assert rpc.drain_notifications() == [
            {'method': 'account/updated', 'params': {'authMode': None}},
        ]
    finally:
        rpc.close()
    assert rpc.running is False


def test_public_calls_are_allowlisted_and_never_implicitly_start_a_process():
    rpc = peer()
    with pytest.raises(CodexRPCError):
        rpc.call('account/read', {})
    with pytest.raises(ValueError, match='허용'):
        rpc.call('turn/start', {'prompt': 'do not execute'})
    assert rpc.running is False


def test_concurrent_calls_are_correlated_when_responses_arrive_out_of_order():
    with peer().start() as rpc, ThreadPoolExecutor(max_workers=2) as executor:
        slow = executor.submit(rpc.call, 'account/read', {'test': 'slow'})
        time.sleep(0.03)
        fast = rpc.call('account/read', {'test': 'fast'})
        assert fast == {'tag': 'fast'}
        assert slow.result(timeout=1) == {'tag': 'slow'}


def test_server_requests_are_refused_and_notifications_are_bounded_and_atomic():
    with peer().start() as rpc:
        assert rpc.call('account/read', {'test': 'server-request'}) == {'refused': True}
        assert rpc.call('account/read', {'test': 'notifications'}) == {'done': True}
        notifications = rpc.drain_notifications()
        assert len(notifications) == 100
        assert notifications[0]['params']['sequence'] == 150
        assert notifications[-1]['params']['sequence'] == 249
        assert rpc.drain_notifications() == []


def test_timeout_drops_late_response_without_hanging_or_breaking_future_calls():
    with peer().start() as rpc:
        with pytest.raises(CodexRPCError, match='시간'):
            rpc.call('account/read', {'test': 'hang'}, timeout=0.05)
        time.sleep(1.05)
        assert rpc.call('account/rateLimits/read', {})['rateLimits']['limitId'] == 'codex'


def test_schema_allows_null_params_for_parameterless_account_method():
    with peer().start() as rpc:
        assert rpc.call('account/rateLimits/read', None)['rateLimits']['limitId'] == 'codex'


def test_unhashable_response_id_fails_all_waiters_generically_without_deadlock():
    with peer(timeout=0.5).start() as rpc, ThreadPoolExecutor(max_workers=2) as executor:
        waiting = executor.submit(rpc.call, 'account/read', {'test': 'slow'})
        time.sleep(0.03)
        with pytest.raises(CodexRPCError) as invalid:
            rpc.call('account/read', {'test': 'invalid-id'})
        with pytest.raises(CodexRPCError):
            waiting.result(timeout=1)
        assert 'invalid response id' not in str(invalid.value)


def test_blocked_child_stdin_cannot_extend_the_call_timeout():
    with peer().start() as rpc, ThreadPoolExecutor(max_workers=1) as executor:
        blocked = executor.submit(rpc.call, 'account/read', {'test': 'hang'}, 0.05)
        time.sleep(0.02)
        started = time.monotonic()
        with pytest.raises(CodexRPCError, match='시간'):
            rpc.call('account/read', {'blob': 'x' * (512 * 1024)}, timeout=0.05)
        assert time.monotonic() - started < 0.3
        with pytest.raises(CodexRPCError):
            blocked.result(timeout=2)


def test_concurrent_pending_calls_have_a_hard_bound():
    barrier = threading.Barrier(33)

    def wait_for_result(rpc):
        barrier.wait()
        try:
            rpc.call('account/read', {'test': 'hang'}, timeout=0.15)
        except CodexRPCError as error:
            return str(error)

    with peer().start() as rpc, ThreadPoolExecutor(max_workers=33) as executor:
        errors = list(executor.map(lambda _: wait_for_result(rpc), range(33)))
    assert any('너무 많' in error for error in errors)


def test_late_duplicate_response_cannot_replace_the_correlated_result():
    with peer().start() as rpc:
        assert rpc.call('account/read', {'test': 'duplicate'}) == {'delivery': 'first'}


@pytest.mark.parametrize('mode, private', [
    ('error', 'private server payload'),
    ('exit', 'private stderr token'),
    ('oversized', 'x' * 100),
])
def test_protocol_process_and_size_failures_are_generic(mode, private):
    rpc = peer(timeout=0.5).start()
    try:
        with pytest.raises(CodexRPCError) as raised:
            rpc.call('account/read', {'test': mode})
        assert private not in str(raised.value)
    finally:
        rpc.close()


def test_constructor_requires_a_command_argv_not_a_shell_string(tmp_path):
    with pytest.raises(ValueError):
        CodexRPC('codex app-server; echo unsafe', cwd=tmp_path)


def test_rejected_outbound_message_releases_its_correlation_slot():
    with peer().start() as rpc:
        with pytest.raises(ValueError, match='크기'):
            rpc.call('account/read', {'value': 'x' * (1024 * 1024 + 1)})
        assert rpc._pending == {}
        assert rpc.call('account/read', {})['account'] is None


def test_all_permitted_account_methods_round_trip_without_other_capabilities():
    with peer().start() as rpc:
        assert rpc.call('account/login/start', {'type': 'chatgpt'})['type'] == 'chatgpt'
        assert rpc.call('account/login/cancel', {'loginId': 'test'}) == {'status': 'canceled'}
        assert rpc.call('account/rateLimits/read', {})['rateLimits']['limitId'] == 'codex'


def test_model_catalog_read_is_the_only_non_auth_public_capability():
    with peer().start() as rpc:
        result = rpc.call('model/list', {'limit': 100, 'includeHidden': False})
        assert [item['model'] for item in result['data']] == [
            'gpt-fixture', 'gpt-fixture-deep',
        ]
        assert result['nextCursor'] is None
        with pytest.raises(ValueError, match='허용'):
            rpc.call('thread/start', {'model': 'gpt-fixture'})


@pytest.mark.parametrize('kind', ['apiKey', 'chatgptAuthTokens'])
def test_login_start_cannot_select_api_or_external_token_auth(kind):
    with peer().start() as rpc:
        with pytest.raises(ValueError, match='ChatGPT'):
            rpc.call('account/login/start', {'type': kind})


def test_chatgpt_login_cannot_smuggle_external_auth_material():
    with peer().start() as rpc:
        with pytest.raises(ValueError, match='ChatGPT'):
            rpc.call('account/login/start', {'type': 'chatgpt', 'accessToken': 'private'})


def test_fixture_supports_official_account_login_and_limit_shapes():
    with peer(1, '--account', 'chatgpt', '--limits', 'known').start() as rpc:
        account = rpc.call('account/read', {})
        assert account['account'] == {
            'type': 'chatgpt', 'email': 'fixture@example.invalid', 'planType': 'plus',
        }
        assert rpc.call('account/rateLimits/read', {})['rateLimits']['primary']['usedPercent'] == 25

    with peer(1, '--login', 'complete').start() as rpc:
        login = rpc.call('account/login/start', {'type': 'chatgpt'})
        assert login == {
            'type': 'chatgpt', 'loginId': 'fixture-login',
            'authUrl': 'https://auth.openai.com/authorize?state=fixture-login',
        }
        time.sleep(0.06)
        assert rpc.call('account/read', {})['account']['type'] == 'chatgpt'
        methods = [item['method'] for item in rpc.drain_notifications()]
        assert 'account/login/completed' in methods
        assert 'account/updated' in methods


def test_fixture_pending_login_can_be_canceled_without_authenticating():
    with peer(1, '--login', 'pending').start() as rpc:
        rpc.call('account/login/start', {'type': 'chatgpt'})
        assert rpc.call('account/login/cancel', {'loginId': 'fixture-login'}) == {'status': 'canceled'}
        assert rpc.call('account/read', {})['account'] is None
