"""T031: B4 provider lifecycle — deadline/cancel from preflight through
actual owned process termination (runtime.md B1-B4; verification §5).

One deadline covers the WHOLE lifecycle: a cancel observed before any
provider work spends no process at all, a cancel between preflight calls
stops at that exact boundary (the prepared input is never transferred —
B1 holds), a deadline consumed by slow preflight refuses before
`thread/start` instead of silently granting the turn a fresh budget, and
closing the transport confirms the owned process actually exited —
escalating SIGTERM→SIGKILL and reporting the confirmation honestly.
"""

import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from app import codex_understanding
from app.codex_rpc import CodexRPC, CodexRPCError, terminate_owned_process
from app.tests.test_codex_understanding import choice, factory_for
from app.understanding import ModelError


def lifecycle_model(tmp_path, monkeypatch, factory):
    monkeypatch.setattr(codex_understanding, 'find_codex', lambda: '/tools/codex')
    monkeypatch.setattr(codex_understanding, '_native_tool_isolation_supported',
                        lambda _config: True)
    return codex_understanding.CodexUnderstandingModel(
        SimpleNamespace(data_dir=tmp_path / 'data'), rpc_factory=factory,
        version_reader=lambda _path: True)


def test_a_cancel_already_set_spends_no_provider_process(tmp_path, monkeypatch):
    factory, created = factory_for(tmp_path)
    subject = lifecycle_model(tmp_path, monkeypatch, factory)
    result = subject.generate(
        'PRIVATE INPUT', {'type': 'object'},
        SimpleNamespace(is_set=lambda: True), selection=choice(),
    )
    assert result == {'text': '', 'model': 'cancelled-before-transfer'}
    assert created == []  # no transport, no process, no call at all


def test_a_preflight_cancel_stops_at_that_exact_boundary(tmp_path, monkeypatch):
    cancel = SimpleNamespace(value=False, is_set=lambda: cancel.value)
    factory, created = factory_for(tmp_path)

    def make(*args, **kwargs):
        rpc = factory(*args, **kwargs)
        plain_config = rpc.script['config/read']

        def config_read(_params, _rpc):
            cancel.value = True  # the cancel arrives mid-preflight
            return plain_config

        rpc.script['config/read'] = config_read
        return rpc

    subject = lifecycle_model(tmp_path, monkeypatch, make)
    result = subject.generate('PRIVATE INPUT', {'type': 'object'}, cancel,
                              selection=choice())
    assert result == {'text': '', 'model': 'cancelled-before-transfer'}
    methods = [method for method, _ in created[0].calls]
    assert methods == ['account/read', 'config/read']  # not one call further
    assert 'PRIVATE INPUT' not in repr(created[0].calls)  # B1: never sent
    assert created[0].closed


def test_the_deadline_spans_preflight_not_just_the_turn(tmp_path, monkeypatch):
    factory, created = factory_for(tmp_path)

    def make(*args, **kwargs):
        rpc = factory(*args, **kwargs)
        plain_skills = rpc.script['skills/list']

        def slow_skills(_params, _rpc):
            time.sleep(0.1)  # slow preflight consumes the whole budget
            return plain_skills

        rpc.script['skills/list'] = slow_skills
        return rpc

    subject = lifecycle_model(tmp_path, monkeypatch, make)
    subject.timeout = 0.05
    with pytest.raises(ModelError) as caught:
        subject.generate('PRIVATE INPUT', {'type': 'object'},
                         SimpleNamespace(is_set=lambda: False),
                         selection=choice())
    assert caught.value.reason == 'timeout'
    methods = [method for method, _ in created[0].calls]
    assert 'thread/start' not in methods  # the turn never got a fresh budget
    assert 'turn/start' not in methods
    assert 'PRIVATE INPUT' not in repr(created[0].calls)
    assert created[0].closed


def test_owned_process_termination_escalates_and_confirms(tmp_path):
    polite = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        assert terminate_owned_process(polite) is True
        assert polite.poll() is not None
    finally:
        if polite.poll() is None:
            polite.kill()

    stubborn = subprocess.Popen(
        [sys.executable, '-c',
         ('import signal, sys, time\n'
          'signal.signal(signal.SIGTERM, signal.SIG_IGN)\n'
          'print("armed", flush=True)\n'
          'time.sleep(60)')],
        stdout=subprocess.PIPE,
    )
    try:
        assert stubborn.stdout.readline().strip() == b'armed'
        assert terminate_owned_process(stubborn) is True  # SIGKILL escalation
        assert stubborn.poll() is not None
        assert stubborn.returncode == -signal.SIGKILL
    finally:
        if stubborn.poll() is None:
            stubborn.kill()


def test_close_confirms_the_owned_process_exited(tmp_path):
    rpc = CodexRPC([sys.executable, '-c', 'import time; time.sleep(60)'],
                   cwd=tmp_path, timeout=0.2)
    assert rpc.termination_confirmed is None  # no lifecycle yet, no claim
    with pytest.raises(CodexRPCError):
        rpc.start()  # initialize times out; start must clean up its process
    assert rpc.termination_confirmed is True
