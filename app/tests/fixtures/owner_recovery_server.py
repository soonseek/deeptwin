"""Finite test-owned supported app restarted over an existing owned instance (T025 recovery
browser case). It starts exactly as the deployment would after the owner-recovery
maintenance tool ran: from the deployment configuration file that tool rewrote (the new
verifier and recovery epoch, never a capability), the existing session root and data
directory, and the public recovery trust set. Nothing here recovers anything itself: the
restricted reconciliation start of `create_app` does, or the start fails closed."""
import argparse
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.operations.setup import OriginProfile
from app.server import create_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    parser.add_argument("--recovery-trust-set", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    if {path.name for path in owned.iterdir()} != {"data", "root"}:
        raise RuntimeError("Fixture requires the owned instance it served before")
    configuration = json.loads(args.configuration.read_text(encoding="utf-8"))
    profile = OriginProfile.from_dict(configuration["origin_profile"])
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", profile.port))
    sock.listen(128)
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid(),
                     recovery_trust_set=args.recovery_trust_set.read_bytes())
    print(f"OWNER_RECOVERY_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                      timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
