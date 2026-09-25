"""Finite test-owned supported app for the design-workspace browser case (T037). It seeds
one persisted design request through the real design persistence — four candidates from a
scripted TEST-ACTOR generator, each criticized by a scripted TEST-ACTOR critic whose
recorded verdicts (two passed and structurally different, one rejected, one passed
duplicate) are labelled with that critic's identity — and registers it with the design
workspace. No critic model turn is configured and the critic is not qualified, exactly as
in production: review is unavailable and preparation is refused. No model, tool or paid
call; every value is synthetic test-actor data."""
import argparse
import base64
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.operations.session_root import initialize_session_root
from app.operations.setup import (
    OriginProfile,
    build_bootstrap_configuration,
    derive_capability_verifier,
)
from app.server import create_app
from app.tests.design_workspace_fixture import open_seeded


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
    request, roles = open_seeded(app)
    seed = {"request_id": request.request_id, **{name: item.candidate_id for name, item in roles.items()}}
    print(f"DESIGN_SEED={json.dumps(seed, separators=(',', ':'))}", flush=True)
    print(f"DESIGN_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
