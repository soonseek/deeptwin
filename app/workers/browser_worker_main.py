"""Browser service entrypoint (T043): `python -m app.workers.browser_worker_main`.

The browser service's long-running process on `cp-browser` (responder) and `browser-fetch`
(requester). Argv is exactly

    --attachment-config=<abs path>

naming a `deeptwin-browser-worker-attachment-v1` object (`BrowserWorkerConfiguration`).

Startup, in order, before anything is bound:
- argv and the configuration; both pair roots must be their fixed profiles';
- the network check: this process's network namespace must hold no interface but
  loopback (`network_mode: none`, or `unshare --net`). A process that could reach any
  network directly refuses to start (`network_present`): the only path out of this worker
  is the fetch service's broker;
- the profile root: an existing directory owned by this process with mode 0700; stale
  session directories a previous process left are removed;
- `listener.bind_worker_listener` (the browser identity with the pair group, the
  root-initialized generation, the 0660 socket, the HMAC readiness record).

Serving: one authenticated requester at a time; one request per connection, one fresh
Chromium session per request. SIGTERM/SIGINT stop after the current session.

Logging: one JSON object per line on stderr from a closed vocabulary, carrying at most an
exception class name or a closed outcome code — never a URL, a title, text or an id.

Exit codes: 0 after a requested stop; 1 when the listener cannot open or the network or
profile checks fail; 2 for argv or configuration outside the exact shapes.
"""

from __future__ import annotations

import json
import os
import secrets
import select
import shutil
import signal
import stat
import sys
import threading
from pathlib import Path

from ..domain.wire import WireInputError, WireLimits, parse_json_object
from . import broker, browser_channel, fetch_channel, ipc_root, listener
from .credential_attachment import read_bounded_file

EXIT_OK = 0
EXIT_SERVICE = 1
EXIT_CONFIG = 2
MAX_ATTACHMENT_BYTES = 4_096
_WAIT_SLICE_S = 0.25
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)
_EVENTS = frozenset({
    "browser_ready", "browser_stopped", "browser_unavailable", "configuration_invalid", "network_present",
    "profile_invalid", "session_accepted", "session_served", "session_refused", "session_failed",
})
_OUTCOMES = frozenset({"ok"}) | browser_channel.WORKER_CODES
_stop = threading.Event()

__all__ = ["load_configuration", "main", "network_interfaces"]


def _log(event, error=None, outcome=None) -> None:
    if event not in _EVENTS:  # pragma: no cover - a closed vocabulary by construction
        raise AssertionError("unknown browser event")
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
        raise ValueError("browser argv is invalid")
    name, _, raw = arguments[0].partition("=")
    if name != "--attachment-config" or not raw:
        raise ValueError("browser argv is invalid")
    path = Path(raw)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("browser argv is invalid")
    return path


def load_configuration(path) -> browser_channel.BrowserWorkerConfiguration:
    attachment = browser_channel.BrowserWorkerConfiguration.from_mapping(parse_json_object(
        read_bounded_file(path, MAX_ATTACHMENT_BYTES),
        required=("schema", "pair_root", "requester_boot_id", "fetch_pair_root", "fetch_requester_boot_id",
                  "chromium_path", "profile_root"),
        limits=WireLimits(max_bytes=MAX_ATTACHMENT_BYTES)))
    root, _spec = browser_channel.browser_channel()
    fetch_root, _spec = fetch_channel.browser_fetch_channel()
    if Path(attachment.pair_root) != root.pair_root or Path(attachment.fetch_pair_root) != fetch_root.pair_root:
        raise ValueError("browser endpoints are not the verified pair roots")
    return attachment


def network_interfaces() -> tuple[str, ...]:
    """The interfaces of this process's network namespace (`/proc/self/net/dev`)."""

    lines = Path("/proc/self/net/dev").read_text().splitlines()[2:]
    return tuple(sorted(line.split(":", 1)[0].strip() for line in lines if ":" in line))


def _require_isolated_network() -> None:
    if network_interfaces() != ("lo",):
        raise PermissionError("the browser worker has a network path of its own")


def _prepare_profile_root(path: str) -> None:
    info = os.lstat(path)
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise PermissionError("the profile root is not a private directory of this worker")
    for entry in os.listdir(path):  # sessions a previous process could not remove
        target = os.path.join(path, entry)
        if os.path.isdir(target) and not os.path.islink(target):
            shutil.rmtree(target, ignore_errors=True)
        else:
            os.unlink(target)
    if os.listdir(path):
        raise PermissionError("the profile root could not be emptied")


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
            owner = worker.accept_authenticated(requester_boot_id=attachment.requester_boot_id, deadline=deadline)
        except broker.BrokerError as error:
            _log("session_refused", error)
            continue
        except (listener.ListenerError, ipc_root.IpcRootError) as error:
            _log("browser_unavailable", error)
            return EXIT_SERVICE
        _log("session_accepted")
        try:
            _log("session_served", outcome=service.serve_connection(owner, deadline=deadline))
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
    try:
        _require_isolated_network()
    except OSError as error:
        _log("network_present", error)
        return EXIT_SERVICE
    try:
        _prepare_profile_root(attachment.profile_root)
    except OSError as error:
        _log("profile_invalid", error)
        return EXIT_SERVICE
    root, spec = browser_channel.browser_channel()
    try:
        from .browser_service import BrowserService

        service = BrowserService(
            spec, chromium_path=attachment.chromium_path, profile_root=attachment.profile_root,
            fetch_client=fetch_channel.BrowserFetchClient.for_worker(attachment.fetch_pair_root,
                                                                     attachment.fetch_requester_boot_id))
        try:
            worker = listener.bind_worker_listener(root, spec, responder_boot_id=secrets.token_hex(32))
        except (listener.ListenerError, ipc_root.IpcRootError, broker.BrokerError) as error:
            _log("browser_unavailable", error)
            return EXIT_SERVICE
        try:
            _log("browser_ready")
            result = serve(worker, service, attachment)
        finally:
            try:
                worker.close()
            except listener.ListenerError as error:
                _log("browser_unavailable", error)
                result = EXIT_SERVICE
        if result == EXIT_OK:
            _log("browser_stopped")
        return result
    except Exception as error:  # noqa: BLE001 - poisoned: class only, never the message
        _log("browser_unavailable", error)
        return EXIT_SERVICE


if __name__ == "__main__":  # pragma: no cover - the browser image runs this
    sys.exit(main())
