"""Fixed extension worker image entrypoint (Task 25 slice 3; T087 worker
startup). `main()` parses only the fixed argv, opens one probe service and
serves connections one at a time until stopped.

Exit codes: 0 after a requested stop, 1 when the service cannot open or
has been poisoned, 2 for an argv outside the fixed shape. A single bad
requester never ends the process. Whether this module is actually the
packaged `bin/worker` of a qualified image is an image gate reported by
the deployment evidence, never claimed here.
"""

from __future__ import annotations

import signal
import sys
import threading

from . import broker
from .extension_channel import ExtensionChannelError, parse_worker_argv
from .extension_probe import ProbeServiceError, open_worker_probe_service

EXIT_OK = 0
EXIT_SERVICE = 1
EXIT_ARGV = 2
_ACCEPT_MS = 30_000
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)
_stop = threading.Event()


class _StopRequested(BaseException):
    """Raised by the signal handler so a blocking accept (which retries
    after EINTR) ends at once; it unwinds the service's own paths, which
    are BaseException-safe, and is caught only by `main()`."""


def _request_stop(signum: int | None = None, _frame: object = None) -> None:
    first = not _stop.is_set()
    _stop.set()
    if signum is not None and first:
        raise _StopRequested()


def _install_handlers() -> list[tuple[signal.Signals, object]]:
    previous = []
    for number in _STOP_SIGNALS:
        try:
            previous.append((number, signal.signal(number, _request_stop)))
        except ValueError:
            # not the main thread: stopping is then the caller's `_request_stop`
            break
    return previous


def _restore_handlers(previous: list[tuple[signal.Signals, object]]) -> None:
    for number, handler in previous:
        try:
            signal.signal(number, handler)
        except (ValueError, TypeError):
            pass


def main(argv: list[str] | None = None) -> int:
    _stop.clear()
    try:
        instance_id, slot_number = parse_worker_argv(
            list(sys.argv) if argv is None else argv
        )
    except ExtensionChannelError:
        return EXIT_ARGV
    try:
        service = open_worker_probe_service(
            instance_id=instance_id, slot_number=slot_number
        )
    except ProbeServiceError:
        return EXIT_SERVICE
    previous = _install_handlers()
    try:
        while not _stop.is_set():
            try:
                service.serve_one(broker.Deadline.after_ms(_ACCEPT_MS))
            except ProbeServiceError:
                if service.closed:
                    return EXIT_SERVICE
        return EXIT_OK
    except _StopRequested:
        return EXIT_OK
    finally:
        # a second stop signal during the close only re-sets the flag
        try:
            service.close()
        except ProbeServiceError:
            pass
        _restore_handlers(previous)


if __name__ == "__main__":  # pragma: no cover - the image runs this
    sys.exit(main())
