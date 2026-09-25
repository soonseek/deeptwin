"""Test-only child process for the real-SO_PEERCRED credential gateway qualification (T090).

The parent test runs as root on Linux and starts this module with
``subprocess`` under the fixed numeric service identities (``user=``/``group=``/
``extra_groups=``), so the kernel — not a seam — supplies every peer credential.
Nothing here patches the broker, the handshake, ``connect_verified`` or the
listener: the only substitution is the module-local profile resolution into an
owned temporary pair root, exactly as the in-process harness does. The config
arrives on stdin as JSON; results are secret-free JSON lines on stdout.

Roles:
- ``serve``: the gateway (provider identity). Initializes an encrypted vault as
  itself, binds the real worker listener, prints ``ready``, then accepts the
  planned number of owners, serving each through
  ``CredentialGatewayService.serve_connection``; a refused accept is recorded by
  its exception class. Finally prints the vault's redacted health.
- ``request``: the control plane (control identity, or a deliberately wrong one).
  Runs the planned operations through ``CredentialGatewayClient.for_gateway`` and
  prints each receipt or sanitized code.
- ``connect_only``: calls ``broker.connect_verified`` once and prints the
  exception class (used against an impostor endpoint).
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
from pathlib import Path

CONTROL_BOOT = "control-boot-peercred"
PROVIDER_BOOT = "provider-boot-peercred"


def profile(base: Path):
    """The production `cp-provider` profile relocated into `base` (pair root only)."""

    from app.workers import gateway_channel
    from app.workers.ipc_root import PairRootSpec

    fixed_root, fixed_spec = gateway_channel.gateway_channel()
    root = PairRootSpec(pair_root=base / "cp-provider", responder_uid=fixed_root.responder_uid,
                        responder_gid=fixed_root.responder_gid, pair_gid=fixed_root.pair_gid)
    spec = dataclasses.replace(fixed_spec, pair_root=root.endpoint_path)
    return root, spec


def _emit(value) -> None:
    sys.stdout.write(json.dumps(value, sort_keys=True) + "\n")
    sys.stdout.flush()


def _serve(config) -> None:
    from app.operations.credential_root_init import initialize_credential_root
    from app.workers import broker, listener
    from app.workers.credential_gateway_service import CredentialGatewayService
    from app.workers.credential_vault import CredentialVault

    base = Path(config["base"])
    root, spec = profile(base)
    args = {"root_directory": base / "vault" / "root", "records_directory": base / "vault" / "records",
            "vault_id": config["vault_id"], "expected_uid": os.geteuid(), "expected_gid": os.getegid()}
    if config.get("initialize", True):
        initialize_credential_root(**args)
    outcomes = []
    with CredentialVault(**args) as vault:
        # The boot secret argument is only type-checked by the service; the channel's
        # authentication uses the pair root's generation secret through the listener.
        service = CredentialGatewayService(vault, spec, broker.BootSecret(os.urandom(broker.AUTH_SECRET_BYTES)))
        worker = listener.bind_worker_listener(root, spec, responder_boot_id=PROVIDER_BOOT)
        try:
            _emit("ready")
            for _ in range(config["sessions"]):
                try:
                    owner = worker.accept_authenticated(requester_boot_id=CONTROL_BOOT,
                                                        deadline=broker.Deadline.after_ms(10_000))
                except Exception as error:  # noqa: BLE001 - recorded by class, never by message
                    outcomes.append("refused:" + type(error).__name__)
                    continue
                try:
                    service.serve_connection(owner, deadline=broker.Deadline.after_ms(10_000))
                    outcomes.append("served")
                except Exception as error:  # noqa: BLE001
                    outcomes.append("failed:" + type(error).__name__)
                finally:
                    owner.close()
        finally:
            worker.close()
        _emit({"outcomes": outcomes, "health": vault.health()})


def _request(config) -> None:
    from app.workers import gateway_channel
    from app.workers.credential_channel import (
        CredentialGatewayClient,
        GatewayServiceError,
    )
    from app.workers.credential_contracts import unb64u

    root, spec = profile(Path(config["base"]))
    gateway_channel.gateway_channel = lambda: (root, spec)  # module-local profile only
    client = CredentialGatewayClient.for_gateway(requester_boot_id=CONTROL_BOOT, deadline_ms=10_000)
    results = []
    for step in config["steps"]:
        try:
            if step["op"] == "store_at":
                secret = unb64u(step["secret_b64u"], 1, 65_536)
                value = client.store_at(metadata=step["metadata"], secret=secret)
                del secret
            elif step["op"] == "query_record":
                value = client.query_record(metadata=step["metadata"])
            elif step["op"] == "retire":
                value = client.retire(command_id=step["command_id"], record=step["record"],
                                      reason=step["reason"])
            elif step["op"] == "snapshot":
                value = client.snapshot()
            else:
                raise AssertionError("unknown planned step")
            results.append({"ok": value})
        except GatewayServiceError as error:
            results.append({"error": error.code, "message": str(error)})
    _emit({"identity": [os.geteuid(), os.getegid(), sorted(os.getgroups())], "results": results})


def _connect_only(config) -> None:
    from app.workers import broker

    _root, spec = profile(Path(config["base"]))
    try:
        sock, _identity, _peer = broker.connect_verified(
            spec, local_service=spec.requester_service, deadline=broker.Deadline.after_ms(5_000))
    except broker.BrokerError as error:
        _emit({"refused": type(error).__name__})
        return
    sock.close()
    _emit({"refused": None})


def main() -> int:
    config = json.loads(sys.stdin.read())
    {"serve": _serve, "request": _request, "connect_only": _connect_only}[config["role"]](config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
