"""Owned subprocess failures must terminate within the complete exchange deadline."""

import importlib.util
import os
import signal
import subprocess
import sys
import time

import pytest

from app.tests.deployment_source_fixture import profile


def session_module():
    name = "app.tests.deployment_receipt_session_fixture"
    assert importlib.util.find_spec(name) is not None, (
        "bounded owned session is missing"
    )
    return importlib.import_module(name)


@pytest.fixture
def owned_program(monkeypatch):
    children = []
    popen = subprocess.Popen

    def configure(code):
        module = session_module()

        def start(*args, **kwargs):
            child = popen([sys.executable, "-B", "-u", "-c", code], **kwargs)
            children.append(child)
            return child

        monkeypatch.setattr(module.subprocess, "Popen", start)
        monkeypatch.setattr(module, "_EXCHANGE_SECONDS", 0.15)
        monkeypatch.setattr(module, "_EOF_SECONDS", 0.1)
        monkeypatch.setattr(module, "_TERMINATE_SECONDS", 0.1)
        return module, children

    yield configure
    for child in children:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=2)


@pytest.mark.parametrize(
    "code,reason",
    [
        ("import os,time; os.write(1,b'{'); time.sleep(10)", "deadline"),
        ("import os,time; os.close(1); time.sleep(10)", "EOF"),
        ("import os,time; os.write(1,b'x'*131073); time.sleep(10)", "overflow"),
    ],
)
def test_partial_frame_eof_and_overflow_are_bounded_and_reaped(
    owned_program, code, reason
):
    module, children = owned_program(code)
    session = module.OwnedReceiptSession(profile())
    started = time.monotonic()
    with pytest.raises(module.ReceiptSessionError, match=reason):
        session.__enter__()
    assert time.monotonic() - started < 3
    assert children[0].poll() is not None
    assert all(
        pipe.closed
        for pipe in (children[0].stdin, children[0].stdout, children[0].stderr)
    )
    session.close()


def test_stalled_input_shares_complete_reply_deadline(owned_program):
    module, children = owned_program(
        'import os,time; os.read(0,4096); os.write(1,b\'{"trust_b64":"e30"}\\n\'); time.sleep(10)'
    )
    with module.OwnedReceiptSession(profile()) as session:
        started = time.monotonic()
        with pytest.raises(module.ReceiptSessionError, match="deadline"):
            session.case(b"x" * 65536, case_name="valid_failed_absent")
        assert time.monotonic() - started < 3
    assert children[0].poll() is not None


def test_ignoring_eof_and_termination_requires_owned_kill_and_reap(owned_program):
    module, children = owned_program(
        "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        'os.read(0,4096); os.write(1,b\'{"trust_b64":"e30"}\\n\'); time.sleep(10)'
    )
    with module.OwnedReceiptSession(profile()) as session:
        assert session.trust_bytes == b"{}"
    assert children[0].returncode == -signal.SIGKILL
    session.close()


def test_normal_eof_reap_idempotent_close_and_read_only_trust():
    module = session_module()
    session = module.OwnedReceiptSession(profile())
    with session:
        assert type(session.trust_bytes) is bytes
        with pytest.raises(AttributeError):
            session.trust_bytes = b"changed"
        child = session._child
    assert child.returncode == 0
    session.close()
    with pytest.raises(module.ReceiptSessionError):
        _ = session.trust_bytes


def test_stderr_capture_is_bounded_while_waiting_for_stdout(owned_program):
    module, children = owned_program(
        "import os,time; os.write(2,b'x'*100000); os.close(1); time.sleep(10)"
    )
    session = module.OwnedReceiptSession(profile())
    with pytest.raises(module.ReceiptSessionError):
        session.__enter__()
    assert len(session._stderr) <= 4096
    assert children[0].poll() is not None


def test_runtime_resolution_retains_configured_and_path_contract(monkeypatch):
    module = session_module()
    runtime = module.node_runtime()
    monkeypatch.setenv("DEEPTWIN_RECEIPT_TEST_NODE", str(runtime))
    assert module.node_runtime() == runtime
    assert os.access(runtime, os.X_OK)


def test_failed_owned_reap_is_explicit_and_closes_all_pipes(owned_program, monkeypatch):
    module, children = owned_program(
        "import os,signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        'os.read(0,4096); os.write(1,b\'{"trust_b64":"e30"}\\n\'); time.sleep(10)'
    )
    session = module.OwnedReceiptSession(profile()).__enter__()
    child = children[0]
    actual_wait = child.wait

    def cannot_reap(*, timeout):
        raise subprocess.TimeoutExpired("owned test child", timeout)

    monkeypatch.setattr(child, "wait", cannot_reap)
    try:
        with pytest.raises(module.ReceiptSessionError, match="reap failed"):
            session.close()
    finally:
        actual_wait(timeout=2)
    assert all(pipe.closed for pipe in (child.stdin, child.stdout, child.stderr))
    assert child.returncode == -signal.SIGKILL
