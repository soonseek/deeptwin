"""Finite test-owned supported app on the portable HTTPS profile, served over real TLS.

The listener is uvicorn with the test's own certificate (a throwaway CA made by the test
with `openssl`, loopback only), so every request reaches `create_app`'s actually composed
route surface with `scope["scheme"] == "https"`. The synthetic bootstrap capability is
read from stdin, never from argv; only its verifier reaches the configuration.
"""
import argparse
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--certificate", required=True, type=Path)
    parser.add_argument("--private-key", required=True, type=Path)
    parser.add_argument("--host-name", default="localhost")
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    capability = sys.stdin.readline().strip()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    port = sock.getsockname()[1]
    profile = OriginProfile.portable(instance_id="3" * 32, url=f"https://{args.host_name}:{port}")
    configuration = build_bootstrap_configuration(
        profile=profile, verifier_b64u=derive_capability_verifier(capability))
    capability = None
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=configuration["recovery_epoch"],
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid())
    config = uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3,
                            ssl_certfile=str(args.certificate), ssl_keyfile=str(args.private_key))
    print(f"PORTABLE_HTTPS_URL={profile.http_origin}", flush=True)
    try:
        uvicorn.Server(config).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
