"""Credential gateway service entrypoint (T090): `python -m app.workers.credential_gateway_main`.

The provider service's long-running process on the `cp-provider` pair. Argv is exactly

    --service-config=<abs path>  --attachment-config=<abs path>   (either order, each once)

- The *service configuration* is the exact nonsecret object
  `{"schema": "deeptwin-credential-gateway-service-v1", "vault_id", "root_directory",
  "records_directory"}` naming the already initialized encrypted vault pair. Genesis is the
  deployment-only `initialize_credential_root`; this process never initializes, repairs or
  replaces a vault and opens it under the fixed provider identity of the gateway profile.
- The *attachment configuration* is the very object the control plane reads
  (`app.workers.credential_attachment`). Its pair root must be the fixed profile's
  (`gateway_channel.gateway_channel()`); its `requester_boot_id` is the only requester boot
  label a handshake is accepted under (see that module for why the label is shared rather
  than learned from the peer).

Startup order: argv and both configurations; the profile check; the vault open (verified
pair, crash recovery of its journal); then the listener. `bind_worker_listener` is the one
place the `cp-provider` generation is validated: it requires this process to be the
profile's responder UID/GID with the pair group, acquires the root-initialized generation
under its shared lock (layout, owners and modes of the pair root, `generation.lock`,
`boot-secret` and the 02710 endpoint), removes only a stale listener pair of its own, binds
the 0660 socket and publishes the HMAC readiness record under a fresh per-process
responder boot id. The generation itself is created and rotated only by the root-owned
IPC initializer (`ipc_root.initialize_pair_root`); a responder cannot and does not.

Serving: the shared `ProviderGatewayIngress` routes each owner's first frame to the
credential-v2 vault engine or, for a `provider-send-prepare-v1`, to the send engine over
the same vault with the fixed Claude API binding (`provider_gateway.claude_api_binding`).
The send engine delivers custody, at claim time, only for the record the provider's
binding head (`bind_head`) binds. One authenticated owner at a time (the channel's in-flight bound is 1). The loop
waits for a pending connection in short slices, then accepts under a fresh operation
deadline, so an idle wait never shortens a client's handshake window. A refused peer
(SO_PEERCRED, wrong requester boot, malformed handshake) or a failed dialogue closes only
that connection. Generation drift or listener integrity loss (for example the pair was
re-initialized for a new boot) ends the process with exit 1 so the supervisor restarts it
against the new generation; it never retries with weaker checks.

SIGTERM/SIGINT only set a flag: an operation in progress completes (its vault mutation is
never interrupted), then the listener unlinks its socket and readiness record, the vault
closes and the process exits 0.

Logging: one JSON object per line on stderr from a closed event vocabulary, carrying at
most an exception *class* name. No message text, path, metadata, secret, hash or boot id
is ever logged.

Exit codes: 0 after a requested stop; 1 when the vault or listener cannot open or the
service is poisoned; 2 for argv or configuration outside the exact shapes.
"""

from __future__ import annotations

import json
import os
import secrets
import select
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

from ..domain.wire import WireInputError, WireLimits, parse_json_object
from . import broker, gateway_channel, ipc_root, listener
from .credential_attachment import (
    MAX_ATTACHMENT_BYTES,
    CredentialGatewayConfiguration,
    read_bounded_file,
)

EXIT_OK = 0
EXIT_SERVICE = 1
EXIT_CONFIG = 2
SERVICE_SCHEMA = "deeptwin-credential-gateway-service-v1"
MAX_SERVICE_CONFIG_BYTES = 4_096
_WAIT_SLICE_S = 0.25
_STOP_SIGNALS = (signal.SIGTERM, signal.SIGINT)
_EVENTS = frozenset({
    "gateway_ready", "gateway_stopped", "gateway_unavailable", "configuration_invalid",
    "session_accepted", "session_served", "session_refused", "session_failed",
})
_stop = threading.Event()

__all__ = ["SERVICE_SCHEMA", "GatewayServiceConfiguration", "main"]


@dataclass(frozen=True, slots=True)
class GatewayServiceConfiguration:
    """The gateway's own nonsecret naming of its vault pair."""

    vault_id: str
    root_directory: Path
    records_directory: Path

    @classmethod
    def from_mapping(cls, value) -> GatewayServiceConfiguration:
        from .credential_contracts import CredentialVaultError, uuid_value

        if type(value) is not dict or set(value) != {"schema", "vault_id", "root_directory",
                                                      "records_directory"}:
            raise ValueError("gateway service configuration is not the exact object")
        if value["schema"] != SERVICE_SCHEMA:
            raise ValueError("gateway service configuration schema is unsupported")
        try:
            uuid_value(value["vault_id"])
        except CredentialVaultError:
            raise ValueError("gateway vault id is invalid") from None
        paths = []
        for name in ("root_directory", "records_directory"):
            raw = value[name]
            if type(raw) is not str or not 1 <= len(raw.encode("utf-8")) <= 4096:
                raise ValueError("gateway vault path is invalid")
            path = Path(raw)
            if not path.is_absolute() or ".." in path.parts or path == Path(os.sep):
                raise ValueError("gateway vault path is invalid")
            paths.append(path)
        return cls(vault_id=value["vault_id"], root_directory=paths[0], records_directory=paths[1])


def _log(event: str, error: BaseException | None = None) -> None:
    if event not in _EVENTS:  # pragma: no cover - a closed vocabulary by construction
        raise AssertionError("unknown gateway event")
    record = {"event": event}
    if error is not None:
        record["class"] = type(error).__name__
    try:
        sys.stderr.write(json.dumps(record, sort_keys=True) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass


def _parse_argv(argv) -> tuple[Path, Path]:
    arguments = list(argv)[1:]
    values = {}
    for argument in arguments:
        if type(argument) is not str or "=" not in argument:
            raise ValueError("gateway argv is invalid")
        name, _, raw = argument.partition("=")
        if name not in ("--service-config", "--attachment-config") or name in values or not raw:
            raise ValueError("gateway argv is invalid")
        path = Path(raw)
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("gateway argv is invalid")
        values[name] = path
    if set(values) != {"--service-config", "--attachment-config"}:
        raise ValueError("gateway argv is invalid")
    return values["--service-config"], values["--attachment-config"]


def load_configuration(service_path, attachment_path):
    """Both exact configurations, checked against the fixed gateway profile."""

    service = GatewayServiceConfiguration.from_mapping(parse_json_object(
        read_bounded_file(service_path, MAX_SERVICE_CONFIG_BYTES),
        required=("schema", "vault_id", "root_directory", "records_directory"),
        limits=WireLimits(max_bytes=MAX_SERVICE_CONFIG_BYTES)))
    attachment = CredentialGatewayConfiguration.from_mapping(parse_json_object(
        read_bounded_file(attachment_path, MAX_ATTACHMENT_BYTES),
        required=("schema", "pair_root", "requester_boot_id"),
        limits=WireLimits(max_bytes=MAX_ATTACHMENT_BYTES)))
    root, _spec = gateway_channel.gateway_channel()
    if Path(attachment.pair_root) != root.pair_root:
        # only the verified cp-provider pair root is a credential gateway endpoint
        raise ValueError("credential gateway endpoint is not the verified pair root")
    return service, attachment


def _request_stop(_signum=None, _frame=None) -> None:
    # only a flag: the loop notices it within one wait slice or after the current dialogue
    _stop.set()


def _install_handlers():
    previous = []
    for number in _STOP_SIGNALS:
        try:
            previous.append((number, signal.signal(number, _request_stop)))
        except ValueError:  # not the main thread: stopping is the caller's `_request_stop`
            break
    return previous


def _restore_handlers(previous) -> None:
    for number, handler in previous:
        try:
            signal.signal(number, handler)
        except (ValueError, TypeError):
            pass


def _pending(worker: listener.WorkerListener) -> bool:
    """Whether a connection is queued on the listening socket (one bounded wait slice)."""
    try:
        readable, _writable, _errors = select.select([worker._socket], [], [], _WAIT_SLICE_S)
    except (OSError, ValueError):
        raise listener.ListenerIntegrityError() from None
    return bool(readable)


def serve(worker, service, attachment) -> int:
    """Serve accepted owners until a stop is requested or the generation is lost."""

    from .credential_channel import GatewayServiceError
    from .provider_send_messages import ProviderSendError

    spec = worker.spec
    while not _stop.is_set():
        if not _pending(worker):
            continue
        deadline = broker.Deadline.after_ms(spec.max_operation_ms)
        try:
            owner = worker.accept_authenticated(requester_boot_id=attachment.requester_boot_id,
                                                deadline=deadline)
        except broker.BrokerError as error:
            # one refused peer (SO_PEERCRED, boot label, handshake, vanished client)
            _log("session_refused", error)
            continue
        except (listener.ListenerError, ipc_root.IpcRootError) as error:
            _log("gateway_unavailable", error)
            return EXIT_SERVICE
        _log("session_accepted")
        try:
            service.serve_connection(owner, deadline=deadline)
            _log("session_served")
        except (GatewayServiceError, ProviderSendError, broker.BrokerError, OSError) as error:
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
    except (ValueError, WireInputError, OSError) as error:
        _log("configuration_invalid", error)
        return EXIT_CONFIG

    from .credential_contracts import CredentialVaultError
    from .credential_gateway_service import CredentialGatewayService
    from .credential_vault import CredentialVault
    from .provider_gateway import CredentialedProviderTransport, claude_api_binding
    from .provider_gateway_ingress import ProviderGatewayIngress
    from .provider_send_service import ProviderSendService

    root, spec = gateway_channel.gateway_channel()
    try:
        vault = CredentialVault(root_directory=configuration.root_directory,
                                records_directory=configuration.records_directory,
                                vault_id=configuration.vault_id,
                                expected_uid=root.responder_uid, expected_gid=root.responder_gid)
    except (CredentialVaultError, OSError) as error:
        _log("gateway_unavailable", error)
        return EXIT_SERVICE
    try:
        # The service's boot-secret argument is only type-checked: frames are
        # authenticated by the pair root's generation secret through the listener. A
        # fresh random value keeps the generation secret out of the service object.
        credential = CredentialGatewayService(vault, spec,
                                              broker.BootSecret(os.urandom(broker.AUTH_SECRET_BYTES)))
        # One ingress on the one endpoint: a credential-v2 operation goes to the vault
        # engine, a provider-send prepare to the send engine over the same vault, which
        # delivers custody only for the record the provider's binding head binds.
        service = ProviderGatewayIngress(credential, ProviderSendService(
            CredentialedProviderTransport(vault, claude_api_binding())))
        try:
            worker = listener.bind_worker_listener(root, spec, responder_boot_id=secrets.token_hex(32))
        except (listener.ListenerError, ipc_root.IpcRootError, broker.BrokerError) as error:
            _log("gateway_unavailable", error)
            return EXIT_SERVICE
        try:
            _log("gateway_ready")
            result = serve(worker, service, attachment)
        finally:
            try:
                worker.close()
            except listener.ListenerError as error:
                _log("gateway_unavailable", error)
                result = EXIT_SERVICE
        if result == EXIT_OK:
            _log("gateway_stopped")
        return result
    except Exception as error:  # noqa: BLE001 - poisoned: class only, never the message
        _log("gateway_unavailable", error)
        return EXIT_SERVICE
    finally:
        vault.close()


if __name__ == "__main__":  # pragma: no cover - the provider image runs this
    sys.exit(main())
