"""Backup-crypto worker entrypoint (T070): `python -m app.workers.backup_crypto_main`.

The `backup` service's long-running process on the `cp-backup` pair (responder
`backup` 20111:20111, pair group 21109). Argv is exactly

    --service-config=<abs path>  --attachment-config=<abs path>   (either order, each once)

- The *service configuration* is the exact nonsecret object
  `{"schema": "deeptwin-backup-crypto-service-v1", "key_root", "age_root"}`: the
  read-only mount of the deployment's `backup-key` volume (backup-key-init's
  `identity.age` + `manifest.json`, nothing else) and the directory of the locked age
  1.3.2 binaries. The worker never mounts, reads or is configured with the provider
  credential root or records, the session root, the state volume or any vault: a key
  root holding anything but the two key files refuses the start, and so does a key
  root the worker could write.
- The *attachment configuration* is the very object the control plane reads
  (`app.workers.backup_channel.BackupWorkerConfiguration`); its pair root must be the
  fixed profile's.

Networkless: before anything is opened the process installs an audit hook
(`forbid_network`) that refuses every socket that is not AF_UNIX (creation, bind,
connect, sendto) and every spawn other than the two locked age binaries. The compose
service is `network_mode: none` as well; the hook makes the property hold for the
process itself, whatever namespace it is started in.

Startup order: argv and both configurations; the profile check; the network guard;
the verified age runtime (locked member digests and version); the key-root check;
then the listener (`listener.bind_worker_listener`, which requires this process to be
the profile's responder identity with the pair group, and publishes the HMAC
readiness record under a fresh responder boot id).

Serving: one authenticated control-plane connection at a time, one operation per
connection (`backup_crypto_service.BackupCryptoService.serve_connection`). A refused
peer (SO_PEERCRED, wrong requester boot, malformed handshake) or a failed dialogue
closes only that connection. Generation drift or listener integrity loss ends the
process with exit 1.

SIGTERM/SIGINT only set a flag; the current operation completes, then the listener
unlinks its socket and readiness record and the process exits 0.

Logging: one JSON object per line on stderr from a closed vocabulary, carrying at
most an exception class name or a closed outcome code; never a path, byte, key or
recipient.

Exit codes: 0 after a requested stop; 1 when the runtime or listener cannot open;
2 for argv or configuration outside the exact shapes.
"""

from __future__ import annotations

import json
import os
import secrets
import select
import signal
import socket
import stat
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from . import backup_channel, broker, ipc_root, listener

EXIT_OK = 0
EXIT_SERVICE = 1
EXIT_CONFIG = 2
SERVICE_SCHEMA = "deeptwin-backup-crypto-service-v1"
MAX_SERVICE_CONFIG_BYTES = 4_096
_WAIT_SLICE_S = 0.25
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)
_EVENTS = frozenset({
    "backup_worker_ready", "backup_worker_stopped", "backup_worker_unavailable",
    "configuration_invalid", "session_accepted", "session_served", "session_refused",
    "session_failed",
})
_stop = threading.Event()
_guard = {"installed": False, "age_root": None}

__all__ = ["SERVICE_SCHEMA", "BackupServiceConfiguration", "forbid_network", "main"]


@dataclass(frozen=True, slots=True)
class BackupServiceConfiguration:
    key_root: Path
    age_root: Path

    @classmethod
    def from_mapping(cls, value) -> BackupServiceConfiguration:
        if type(value) is not dict or set(value) != {"schema", "key_root", "age_root"}:
            raise ValueError("backup worker service configuration is not the exact object")
        if value["schema"] != SERVICE_SCHEMA:
            raise ValueError("backup worker service configuration schema is unsupported")
        paths = []
        for name in ("key_root", "age_root"):
            raw = value[name]
            if type(raw) is not str or not 1 <= len(raw.encode("utf-8")) <= 4096:
                raise ValueError("backup worker path is invalid")
            path = Path(raw)
            if not path.is_absolute() or ".." in path.parts or path == Path(os.sep):
                raise ValueError("backup worker path is invalid")
            paths.append(path)
        key_root, age_root = paths
        if key_root == age_root or key_root in age_root.parents or age_root in key_root.parents:
            raise ValueError("the backup key and the age runtime need separate roots")
        return cls(key_root=key_root, age_root=age_root)


def _read_bounded(path: Path, maximum: int) -> bytes:
    """One regular, non-symlink file of at most `maximum` bytes, read whole."""

    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("configuration path is invalid")
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= maximum:
            raise ValueError("configuration file is invalid")
        raw = os.read(descriptor, maximum + 1)
        if not 1 <= len(raw) <= maximum:
            raise ValueError("configuration file is invalid")
        return raw
    finally:
        os.close(descriptor)


def _strict_object(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("configuration is not strict JSON") from None
    if type(value) is not dict:
        raise ValueError("configuration is not an object")
    return value


def load_configuration(service_path, attachment_path):
    service = BackupServiceConfiguration.from_mapping(
        _strict_object(_read_bounded(Path(service_path), MAX_SERVICE_CONFIG_BYTES)))
    attachment = backup_channel.BackupWorkerConfiguration.from_mapping(
        _strict_object(_read_bounded(Path(attachment_path), backup_channel.MAX_ATTACHMENT_BYTES)))
    attachment.check_profile()
    root, _spec = backup_channel.backup_channel()
    for path in (service.key_root, service.age_root):
        if path == root.pair_root or root.pair_root in path.parents or path in root.pair_root.parents:
            raise ValueError("the backup key and the age runtime never live in the pair root")
    return service, attachment


# --- networkless -----------------------------------------------------------------------

def _network_hook(event, args):
    if event == "socket.__new__":
        family = args[1] if len(args) > 1 else None
        if family not in (socket.AF_UNIX, -1):
            raise PermissionError("the backup worker opens no network socket")
    elif event in ("socket.bind", "socket.connect", "socket.sendto", "socket.sendmsg"):
        sock = args[0]
        if getattr(sock, "family", None) != socket.AF_UNIX:
            raise PermissionError("the backup worker opens no network socket")
    elif event in ("socket.getaddrinfo", "socket.gethostbyname", "socket.gethostbyaddr",
                   "socket.gethostbyname_ex"):
        raise PermissionError("the backup worker resolves no network name")
    elif event in ("subprocess.Popen", "os.posix_spawn", "os.exec", "os.spawn", "os.system"):
        executable = args[0] if args else None
        if executable is None and len(args) > 1 and isinstance(args[1], (list, tuple)) and args[1]:
            executable = args[1][0]
        allowed = _guard["age_root"]
        try:
            target = Path(os.fsdecode(executable))
        except TypeError:
            target = None
        if (event != "subprocess.Popen" and event != "os.posix_spawn") or allowed is None \
                or target is None or target.parent != allowed or target.name not in ("age", "age-keygen"):
            raise PermissionError("the backup worker spawns only the locked age binaries")


def forbid_network(age_root: Path) -> None:
    """Install the process-wide guard once (audit hooks cannot be removed)."""

    if _guard["installed"]:
        if _guard["age_root"] != Path(age_root):
            raise PermissionError("the network guard is already bound to another age root")
        return
    _guard["age_root"] = Path(age_root)
    sys.addaudithook(_network_hook)
    _guard["installed"] = True


# --- serving ---------------------------------------------------------------------------

def _log(event: str, error: BaseException | None = None, outcome: str | None = None) -> None:
    if event not in _EVENTS:  # pragma: no cover - a closed vocabulary by construction
        raise AssertionError("unknown backup worker event")
    record = {"event": event}
    if error is not None:
        record["class"] = type(error).__name__
    if outcome is not None:
        record["outcome"] = outcome
    try:
        sys.stderr.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _parse_argv(argv) -> tuple[Path, Path]:
    values = {}
    for argument in list(argv)[1:]:
        if type(argument) is not str or "=" not in argument:
            raise ValueError("backup worker argv is invalid")
        name, _, raw = argument.partition("=")
        if name not in ("--service-config", "--attachment-config") or name in values or not raw:
            raise ValueError("backup worker argv is invalid")
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("backup worker argv is invalid")
        values[name] = path
    if set(values) != {"--service-config", "--attachment-config"}:
        raise ValueError("backup worker argv is invalid")
    return values["--service-config"], values["--attachment-config"]


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
    from .backup_stream import BackupStreamError

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
            _log("backup_worker_unavailable", error)
            return EXIT_SERVICE
        _log("session_accepted")
        try:
            outcome = service.serve_connection(owner, deadline=deadline)
            _log("session_served", outcome=outcome)
        except (BackupStreamError, broker.BrokerError, OSError) as error:
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
        service_path, attachment_path = _parse_argv(argv)
        configuration, attachment = load_configuration(service_path, attachment_path)
    except (ValueError, OSError) as error:
        _log("configuration_invalid", error)
        return EXIT_CONFIG

    from .backup_crypto import AgeRuntime, BackupCryptoError
    from .backup_crypto_service import (
        BackupCryptoService,
        BackupKeyRootError,
        check_key_root,
    )

    try:
        forbid_network(configuration.age_root)
        runtime = AgeRuntime.open(configuration.age_root)
    except (BackupCryptoError, PermissionError, OSError) as error:
        _log("backup_worker_unavailable", error)
        return EXIT_SERVICE
    try:
        check_key_root(configuration.key_root)
    except (BackupKeyRootError, OSError) as error:
        _log("configuration_invalid", error)
        return EXIT_CONFIG
    root, spec = backup_channel.backup_channel()
    try:
        service = BackupCryptoService(runtime, configuration.key_root)
        try:
            worker = listener.bind_worker_listener(root, spec, responder_boot_id=secrets.token_hex(32))
        except (listener.ListenerError, ipc_root.IpcRootError, broker.BrokerError) as error:
            _log("backup_worker_unavailable", error)
            return EXIT_SERVICE
        try:
            _log("backup_worker_ready")
            result = serve(worker, service, attachment)
        finally:
            try:
                worker.close()
            except listener.ListenerError as error:
                _log("backup_worker_unavailable", error)
                result = EXIT_SERVICE
        if result == EXIT_OK:
            _log("backup_worker_stopped")
        return result
    except Exception as error:  # noqa: BLE001 - poisoned: class only, never the message
        _log("backup_worker_unavailable", error)
        return EXIT_SERVICE


if __name__ == "__main__":  # pragma: no cover - the backup image runs this
    sys.exit(main())
