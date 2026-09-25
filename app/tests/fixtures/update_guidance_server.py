"""Finite test-owned supported app for the T072 update-guidance browser case. On an empty
owned directory it starts exactly like the T025 owner-lifecycle fixture (the offline
bootstrap page's non-secret configuration, a new session root); on the directory it
served before it restarts over the same data and root, as the deployment would after the
operator ran the update tool with the control plane stopped. Nothing here prepares,
backs up or migrates anything: the operator tool does, and this app only reads it."""
import argparse
import json
import os
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.operations.session_root import initialize_session_root  # noqa: E402
from app.operations.setup import OriginProfile, build_bootstrap_configuration  # noqa: E402
from app.server import create_app  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--owned-dir", required=True, type=Path)
    parser.add_argument("--configuration", required=True, type=Path)
    args = parser.parse_args()
    owned = args.owned_dir.resolve(strict=True)
    handed = json.loads(args.configuration.read_text(encoding="utf-8"))
    profile = OriginProfile.from_dict(handed["origin_profile"])
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=handed["verifier_b64u"],
                                                  recovery_epoch=handed["recovery_epoch"])
    if configuration != handed:
        raise RuntimeError("the handed configuration is not the exact canonical block")
    existing = {path.name for path in owned.iterdir()}
    if existing not in (set(), {"data", "root"}):
        raise RuntimeError("Fixture requires an empty owned directory or the instance it served")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", profile.port))
    sock.listen(128)
    if not existing:
        initialize_session_root(owned / "root", profile=profile, recovery_epoch=configuration["recovery_epoch"],
                                expected_uid=os.getuid(), expected_gid=os.getgid())
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid())
    print(f"UPDATE_GUIDANCE_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False,
                                      timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
