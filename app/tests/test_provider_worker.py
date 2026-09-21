"""Fixed private worker argv and lifecycle."""

import pytest
from app.tests.test_provider_service import slot
from app.tests.test_extension_listener import channel, INSTANCE, open_fds
from app.tests._provider_worker_fixture import provider_tree


def argv():
    return ["worker", "--instance-id", INSTANCE, "--slot-number", "4"]


def test_worker_rejects_network_or_callback_flags():
    from app.workers.provider_worker import main

    assert main(["worker", "--url", "https://invalid.example"]) == 2


def test_handler_install_interruption_still_closes_actual_service(slot, monkeypatch):
    from app.workers import provider_worker as pw

    before = open_fds()

    def interrupt():
        raise KeyboardInterrupt()

    monkeypatch.setattr(pw, "_install_handlers", interrupt)
    with pytest.raises(KeyboardInterrupt):
        pw.main(argv())
    assert open_fds() == before


def test_requested_stop_unwinds_actual_service_without_user_signal(slot, monkeypatch):
    from app.workers import provider_worker as pw, provider_service as ps

    before = open_fds()
    monkeypatch.setattr(pw, "_install_handlers", lambda: [])

    def stop(service, deadline):
        pw._request_stop(15)

    monkeypatch.setattr(ps.ProviderWorkerService, "serve_one", stop)
    assert pw.main(argv()) == 0
    assert open_fds() == before


def test_worker_unavailable_metadata_exits_one(slot):
    from app.workers import provider_worker as pw

    _, _, _, tree = slot
    tree["identity"].unlink()
    assert pw.main(argv()) == 1


def test_partial_handler_install_restores_already_changed_handler(monkeypatch):
    from app.workers import provider_worker as pw

    calls = []

    def signal(number, handler):
        calls.append((number, handler))
        if len(calls) == 2:
            raise KeyboardInterrupt()
        return "previous-fixture-handler"

    monkeypatch.setattr(pw.signal, "signal", signal)
    with pytest.raises(KeyboardInterrupt):
        pw._install_handlers()
    assert calls[-1] == (pw._STOP_SIGNALS[0], "previous-fixture-handler")
