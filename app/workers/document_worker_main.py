"""Document service entrypoint (T045): `python -m app.workers.document_worker_main`.

The document service's long-running process on the `cp-document` pair. Argv is exactly

    --attachment-config=<abs path>

naming the very object the control plane reads (`deeptwin-document-worker-attachment-v1`:
`pair_root`, `requester_boot_id`). Its pair root must be the fixed profile's
(`document_channel.document_channel()`); its `requester_boot_id` is the only requester
boot label a handshake is accepted under.

Startup: argv and the configuration; the profile check; then `listener.bind_worker_listener`,
which requires this process to be the profile's responder UID/GID with the pair group,
acquires the root-initialized generation (the IPC initializer creates and rotates it; this
process never does), binds the 0660 socket and publishes the HMAC readiness record under a
fresh responder boot id. The parsers are imported only after that, inside this process.

Serving: one authenticated requester at a time; one request per connection. A refused peer
(SO_PEERCRED, wrong requester boot, malformed handshake) or a failed dialogue closes only
that connection; generation drift or listener integrity loss ends the process with exit 1
so the supervisor restarts it. SIGTERM/SIGINT set a flag; the current render completes,
then the listener unlinks its socket and readiness record and the process exits 0.

Logging: one JSON object per line on stderr from a closed vocabulary, carrying at most an
exception class name or a closed outcome code — never document bytes, text, paths or ids.

Exit codes: 0 after a requested stop; 1 when the listener cannot open; 2 for argv or
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
from . import broker, document_channel, ipc_root, listener
from .credential_attachment import read_bounded_file

EXIT_OK = 0
EXIT_SERVICE = 1
EXIT_CONFIG = 2
MAX_ATTACHMENT_BYTES = 4_096
_WAIT_SLICE_S = 0.25
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)
_EVENTS = frozenset({
    "document_ready", "document_stopped", "document_unavailable", "configuration_invalid",
    "session_accepted", "session_served", "session_refused", "session_failed",
})
_OUTCOMES = frozenset({"ok"}) | document_channel.WORKER_CODES
_stop = threading.Event()

__all__ = ["main", "load_configuration"]


def _log(event: str, error: BaseException | None = None, outcome: str | None = None) -> None:
    if event not in _EVENTS:  # pragma: no cover - a closed vocabulary by construction
        raise AssertionError("unknown document event")
    record = {"event": event}
    if error is not None:
        record["class"] = type(error).__name__
    if outcome is not None and outcome in _OUTCOMES:
        record["outcome"] = outcome
    try:
        sys.stderr.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _parse_argv(argv) -> Path:
    arguments = list(argv)[1:]
    if len(arguments) != 1 or type(arguments[0]) is not str:
        raise ValueError("document argv is invalid")
    name, _, raw = arguments[0].partition("=")
    if name != "--attachment-config" or not raw:
        raise ValueError("document argv is invalid")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("document argv is invalid")
    return path


def load_configuration(path) -> document_channel.DocumentWorkerConfiguration:
    attachment = document_channel.DocumentWorkerConfiguration.from_mapping(parse_json_object(
        read_bounded_file(path, MAX_ATTACHMENT_BYTES),
        required=("schema", "pair_root", "requester_boot_id"),
        limits=WireLimits(max_bytes=MAX_ATTACHMENT_BYTES)))
    root, _spec = document_channel.document_channel()
    if Path(attachment.pair_root) != root.pair_root:
        raise ValueError("document endpoint is not the verified pair root")
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


def _pending(worker) -> bool:
    try:
        readable, _writable, _errors = select.select([worker._socket], [], [], _WAIT_SLICE_S)
    except (OSError, ValueError):
        raise listener.ListenerIntegrityError() from None
    return bool(readable)


def serve(worker, service, attachment) -> int:
    spec = worker.spec
    while not _stop.is_set():
        if not _pending(worker):
            continue
        deadline = broker.Deadline.after_ms(spec.max_operation_ms)
        try:
            owner = worker.accept_authenticated(requester_boot_id=attachment.requester_boot_id,
                                                deadline=deadline)
        except broker.BrokerError as error:
            _log("session_refused", error)
            continue
        except (listener.ListenerError, ipc_root.IpcRootError) as error:
            _log("document_unavailable", error)
            return EXIT_SERVICE
        _log("session_accepted")
        try:
            outcome = service.serve_connection(owner, deadline=deadline)
            _log("session_served", outcome=outcome)
        except (broker.BrokerError, OSError, ValueError) as error:
            _log("session_failed", error)
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
    root, spec = document_channel.document_channel()
    try:
        from .document_service import DocumentCodecService

        service = DocumentCodecService(spec)
        try:
            worker = listener.bind_worker_listener(root, spec, responder_boot_id=secrets.token_hex(32))
        except (listener.ListenerError, ipc_root.IpcRootError, broker.BrokerError) as error:
            _log("document_unavailable", error)
            return EXIT_SERVICE
        try:
            _log("document_ready")
            result = serve(worker, service, attachment)
        finally:
            try:
                worker.close()
            except listener.ListenerError as error:
                _log("document_unavailable", error)
                result = EXIT_SERVICE
        if result == EXIT_OK:
            _log("document_stopped")
        return result
    except Exception as error:  # noqa: BLE001 - poisoned: class only, never the message
        _log("document_unavailable", error)
        return EXIT_SERVICE


if __name__ == "__main__":  # pragma: no cover - the document image runs this
    sys.exit(main())
