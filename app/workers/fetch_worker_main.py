"""Fetch service entrypoint (T043): `python -m app.workers.fetch_worker_main`.

The fetch service's long-running process: the responder of `cp-fetch` (control registers
and revokes browser grants) and of `browser-fetch` (the networkless browser worker asks for
one URL under a grant). Argv is exactly

    --attachment-config=<abs path>

naming a `deeptwin-fetch-worker-attachment-v1` object (both pair roots and the one
requester boot label accepted on each). Each pair root must be its fixed profile's.

Startup binds both listeners through `listener.bind_worker_listener`, which requires this
process to be the fetch identity with both pair groups, acquires each root-initialized
generation and publishes each readiness record under a fresh responder boot id.

Serving: one authenticated connection at a time, one request per connection, from
whichever listener is ready. A refused peer or a failed dialogue closes only that
connection; generation drift or listener integrity loss ends the process with exit 1.
SIGTERM/SIGINT stop after the current request.

Logging: one JSON object per line on stderr from a closed vocabulary, carrying at most an
exception class name, the pair and a closed outcome code — never a URL, a body or an id.

Exit codes: 0 after a requested stop; 1 when a listener cannot open; 2 for argv or
configuration outside the exact shapes.
"""

from __future__ import annotations

import json
import secrets
import select
import signal
import sys
import threading
from pathlib import Path

from ..domain.wire import WireInputError, WireLimits, parse_json_object
from . import broker, fetch_channel, ipc_root, listener
from .credential_attachment import read_bounded_file

EXIT_OK = 0
EXIT_SERVICE = 1
EXIT_CONFIG = 2
MAX_ATTACHMENT_BYTES = 4_096
_WAIT_SLICE_S = 0.25
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)
_EVENTS = frozenset({
    "fetch_ready", "fetch_stopped", "fetch_unavailable", "configuration_invalid",
    "session_accepted", "session_served", "session_refused", "session_failed",
})
_PAIRS = frozenset({"cp-fetch", "browser-fetch"})
_OUTCOMES = (frozenset({"ok", "registered", "revoked"}) | fetch_channel.FETCH_CODES
             | fetch_channel.GRANT_CODES)
_stop = threading.Event()

__all__ = ["load_configuration", "main"]


def _log(event, error=None, outcome=None, pair=None) -> None:
    if event not in _EVENTS:  # pragma: no cover - a closed vocabulary by construction
        raise AssertionError("unknown fetch event")
    record = {"event": event}
    if error is not None:
        record["class"] = type(error).__name__
    if outcome is not None and outcome in _OUTCOMES:
        record["outcome"] = outcome
    if pair is not None and pair in _PAIRS:
        record["pair"] = pair
    try:
        sys.stderr.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _parse_argv(argv) -> Path:
    arguments = list(argv)[1:]
    if len(arguments) != 1 or type(arguments[0]) is not str:
        raise ValueError("fetch argv is invalid")
    name, _, raw = arguments[0].partition("=")
    if name != "--attachment-config" or not raw:
        raise ValueError("fetch argv is invalid")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("fetch argv is invalid")
    return path


def load_configuration(path) -> fetch_channel.FetchWorkerConfiguration:
    attachment = fetch_channel.FetchWorkerConfiguration.from_mapping(parse_json_object(
        read_bounded_file(path, MAX_ATTACHMENT_BYTES),
        required=("schema", "control_pair_root", "control_requester_boot_id", "browser_pair_root",
                  "browser_requester_boot_id"),
        limits=WireLimits(max_bytes=MAX_ATTACHMENT_BYTES)))
    control_root, _spec = fetch_channel.control_fetch_channel()
    browser_root, _spec = fetch_channel.browser_fetch_channel()
    if (Path(attachment.control_pair_root) != control_root.pair_root
            or Path(attachment.browser_pair_root) != browser_root.pair_root):
        raise ValueError("fetch endpoints are not the verified pair roots")
    return attachment


def _request_stop(_signum=None, _frame=None) -> None:
    _stop.set()


def _install_handlers():
    previous = []
    for number in _STOP_SIGNALS:
        try:
            previous.append((number, signal.signal(number, _request_stop)))
        except ValueError:
            break
    return previous


def _restore_handlers(previous) -> None:
    for number, handler in previous:
        try:
            signal.signal(number, handler)
        except (ValueError, TypeError):
            pass


def _ready(workers):
    try:
        readable, _writable, _errors = select.select([worker._socket for worker, *_ in workers], [], [],
                                                     _WAIT_SLICE_S)
    except (OSError, ValueError):
        raise listener.ListenerIntegrityError() from None
    return [entry for entry in workers if entry[0]._socket in readable]


def serve(workers) -> int:
    """`workers` holds (listener, pair name, requester boot id, serve callable)."""

    while not _stop.is_set():
        for worker, pair, boot, handler in _ready(workers):
            deadline = broker.Deadline.after_ms(worker.spec.max_operation_ms)
            try:
                owner = worker.accept_authenticated(requester_boot_id=boot, deadline=deadline)
            except broker.BrokerError as error:
                _log("session_refused", error, pair=pair)
                continue
            except (listener.ListenerError, ipc_root.IpcRootError) as error:
                _log("fetch_unavailable", error, pair=pair)
                return EXIT_SERVICE
            _log("session_accepted", pair=pair)
            try:
                _log("session_served", outcome=handler(owner, deadline=deadline), pair=pair)
            except (broker.BrokerError, OSError, ValueError) as error:
                _log("session_failed", error, pair=pair)
            finally:
                try:
                    owner.close()
                except (broker.BrokerError, listener.ListenerError, ipc_root.IpcRootError, OSError):
                    pass
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    _stop.clear()
    previous = _install_handlers()
    try:
        return _run(list(sys.argv) if argv is None else argv)
    finally:
        _restore_handlers(previous)


def _run(argv) -> int:
    try:
        attachment = load_configuration(_parse_argv(argv))
    except (ValueError, WireInputError, OSError) as error:
        _log("configuration_invalid", error)
        return EXIT_CONFIG
    control_root, control_spec = fetch_channel.control_fetch_channel()
    browser_root, browser_spec = fetch_channel.browser_fetch_channel()
    bound = []
    try:
        from .fetch_service import FetchService

        service = FetchService(control_spec, browser_spec)
        try:
            for root, spec, pair, boot, handler in (
                    (control_root, control_spec, "cp-fetch", attachment.control_requester_boot_id,
                     service.serve_control),
                    (browser_root, browser_spec, "browser-fetch", attachment.browser_requester_boot_id,
                     service.serve_browser)):
                worker = listener.bind_worker_listener(root, spec, responder_boot_id=secrets.token_hex(32))
                bound.append((worker, pair, boot, handler))
        except (listener.ListenerError, ipc_root.IpcRootError, broker.BrokerError) as error:
            _log("fetch_unavailable", error)
            return EXIT_SERVICE
        _log("fetch_ready")
        result = serve(bound)
        if result == EXIT_OK:
            _log("fetch_stopped")
        return result
    except Exception as error:  # noqa: BLE001 - poisoned: class only, never the message
        _log("fetch_unavailable", error)
        return EXIT_SERVICE
    finally:
        for worker, *_rest in bound:
            try:
                worker.close()
            except listener.ListenerError as error:
                _log("fetch_unavailable", error)


if __name__ == "__main__":  # pragma: no cover - the fetch image runs this
    sys.exit(main())
