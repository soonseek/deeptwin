"""Test-only control-plane child: the supported app factory over a real credential gateway UDS (T090).

The parent test (root on Linux) starts this module under the control plane's fixed
numeric identity with the pair group, next to a gateway child from
``credential_peercred_child`` (role ``serve``). Nothing here patches the broker,
the handshake, ``connect_verified``, the listener, the client, the ledger, the routes
or the factory: the only substitution is the module-local profile resolution into
the owned temporary pair root, exactly as the peercred child does. The child builds
the real ``create_app`` with a ``CredentialGatewayConfiguration`` naming that pair
root, establishes an owner session over HTTP and runs the planned credential
requests. It prints one secret-free JSON line: each response's status and body, the
ledger's mode and owner, and whether any vault module was loaded.

With ``attachment`` in its config, the child reads the attachment object from that file
(the same file the gateway entrypoint is started with) instead of building it. The
``mark``/``wait_for`` steps create or await a file in the child's own directory so the
parent can act between two requests of one control-plane process (for example restart the
gateway); they make no request.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import time
from base64 import urlsafe_b64encode
from pathlib import Path

from app.tests.support.credential_peercred_child import CONTROL_BOOT, profile

VAULT_MODULES = ("app.workers.credential_vault", "app.workers.credential_root",
                 "app.workers.credential_envelope", "app.workers.credential_journal",
                 "app.operations.credential_root_init", "nacl.secret")


def main() -> int:
    config = json.loads(sys.stdin.read())
    base = Path(config["base"])
    from app.workers import gateway_channel

    root, spec = profile(base)
    gateway_channel.gateway_channel = lambda: (root, spec)  # module-local profile only

    from fastapi.testclient import TestClient

    from app.api.credential_wiring import LEDGER_NAME, CredentialGatewayConfiguration
    from app.operations.session_root import initialize_session_root
    from app.operations.setup import (
        OriginProfile,
        build_bootstrap_configuration,
        derive_capability_verifier,
    )
    from app.server import create_app
    from app.workers.credential_attachment import read_bounded_file

    home = base / "control"
    origin = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=4193)
    capability = urlsafe_b64encode(b"S" * 32).rstrip(b"=").decode()
    deployment = build_bootstrap_configuration(profile=origin,
                                               verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(home / "root", profile=origin, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    if "attachment" in config:
        attachment = CredentialGatewayConfiguration.from_mapping(
            json.loads(read_bounded_file(config["attachment"], 4096)))
    else:
        attachment = CredentialGatewayConfiguration(pair_root=str(root.pair_root),
                                                    requester_boot_id=CONTROL_BOOT)
    application = create_app(
        home / "data", deployment_config=deployment, session_root_dir=home / "root",
        expected_uid=os.getuid(), expected_gid=os.getgid(), credential_gateway=attachment)
    path = origin.base_path + "api/v1/credentials"
    steps = []
    with TestClient(application, base_url=origin.http_origin) as client:
        plain = {"Origin": origin.http_origin, "Sec-Fetch-Site": "same-origin"}
        answer = client.post(origin.base_path + "session/bootstrap", headers=plain, json={
            "login_name": "owner", "password": "synthetic owner passphrase", "raw_capability_b64u": capability})
        if answer.status_code != 201:
            raise SystemExit("owner bootstrap failed: " + str(answer.status_code))
        write = {**plain, "X-DeepTwin-CSRF": answer.json()["csrf_token"], "Content-Type": "application/json"}
        handle = None
        for step in config["steps"]:
            if step["op"] == "mark":
                (home / step["name"]).touch(mode=0o600)
                continue
            if step["op"] == "wait_for":
                limit = time.monotonic() + step.get("seconds", 60)
                while not (home / step["name"]).exists():
                    if time.monotonic() > limit:
                        raise SystemExit("the parent never released the child")
                    time.sleep(0.02)
                continue
            if step["op"] == "list":
                response = client.get(path, headers=plain)
            elif step["op"] == "store":
                body = {"intent_id": step["intent_id"], "provider": "claude", "secret": step["secret"]}
                if step.get("rotate"):
                    body["rotate_from"] = handle
                response = client.post(path, headers=write, content=json.dumps(body))
                del body
            elif step["op"] == "delete":
                response = client.request("DELETE", f"{path}/{handle}", headers=write,
                                          content=json.dumps({"intent_id": step["intent_id"]}))
            else:
                raise AssertionError("unknown planned step")
            value = response.json()
            if response.status_code == 201:
                handle = value["handle"]
            steps.append({"status": response.status_code, "body": value})
    ledger = (home / "data" / LEDGER_NAME).lstat()
    sys.stdout.write(json.dumps({
        "identity": [os.geteuid(), os.getegid(), sorted(os.getgroups())],
        "steps": steps,
        "ledger": [oct(stat.S_IMODE(ledger.st_mode)), ledger.st_uid],
        "vault_modules": [name for name in VAULT_MODULES if name in sys.modules],
    }, sort_keys=True) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
