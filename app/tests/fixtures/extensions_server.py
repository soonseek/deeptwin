"""Finite test-owned supported app for the Settings > Extensions browser case (T087 UI).

The real supported `create_app` with its fixed extension contributions
(extension-candidates-v1, provider-installation-v1, provider-conformance-v1 with the
transport-qualification routes). It seeds nothing. Before announcing its URL it prints one
`EXTENSIONS_INPUTS=` line of synthetic test-actor files for the browser to pick:

- `candidate`: the inert metadata bundle of `extension_candidate_fixture.candidate_payload`
  without its command id (manifest, service descriptor, support documents; no code/image);
- `candidate_fixed`: the same bundle with an explicit command id, and `candidate_changed`: a
  changed bundle under that same id (the route answers 409 to it);
- `packet_b64`: a structurally valid release-evidence packet (`packet_header` of
  `provider_installation_fixture`, synthetic bytes) naming a staged installation that does
  not exist here, with its `staged_id`.

What this server cannot compose: a staged installation (revision 1), and therefore a
verified installation, a verified-installation conformance run or a transport
qualification. Those need `installation_case`'s pytest-owned release tree, monkeypatched
publication/source fixtures and retained framed conformance worker. No model, provider,
network or paid call."""
import argparse
import base64
import json
import os
import socket
import sys
from pathlib import Path
from uuid import uuid4

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.domain.refs import EntityRef
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app
from app.tests.extension_candidate_fixture import candidate_payload
from app.tests.provider_installation_fixture import packet_header


def inputs():
    bundle = candidate_payload()
    fixed = dict(bundle)
    del bundle["command_id"]
    changed = json.loads(json.dumps(fixed))
    changed["manifest"]["license"]["expression"] = "Synthetic-changed"
    staged = EntityRef("extension_installation", str(uuid4()), 1, "a" * 64)
    raw, objects = packet_header(staged)
    wire = b"DTPIV1\0\0" + len(raw).to_bytes(4, "big") + raw + b"".join(objects)
    return {"candidate": bundle, "candidate_fixed": fixed, "candidate_changed": changed,
            "packet_b64": base64.b64encode(wire).decode(), "staged_id": staged.id}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)  # accept (queue) before the URL is announced
    profile = OriginProfile.local(instance_id="1" * 32, path_id="2" * 32, port=sock.getsockname()[1])
    capability = base64.urlsafe_b64encode(b"T" * 32).rstrip(b"=").decode()
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=derive_capability_verifier(capability))
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=1,
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid())
    print("EXTENSIONS_INPUTS=" + json.dumps(inputs(), separators=(",", ":")), flush=True)
    print(f"EXTENSIONS_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(
            sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
