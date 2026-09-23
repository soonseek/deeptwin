"""Finite test-owned supported app configured from the offline bootstrap page's own
non-secret output (T025 browser case): the verifier, recovery epoch and exact
OriginProfile the operator would hand to the deployment. The raw capability never
reaches this process; the owner types it into the first screen."""
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
    if not owned.is_dir() or any(owned.iterdir()):
        raise RuntimeError("Fixture requires its newly owned empty directory")
    handed = json.loads(args.configuration.read_text(encoding="utf-8"))
    profile = OriginProfile.from_dict(handed["origin_profile"])
    configuration = build_bootstrap_configuration(profile=profile, verifier_b64u=handed["verifier_b64u"],
                                                  recovery_epoch=handed["recovery_epoch"])
    if configuration != handed:
        raise RuntimeError("the handed configuration is not the exact canonical block")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", profile.port))
    sock.listen(128)
    initialize_session_root(owned / "root", profile=profile, recovery_epoch=configuration["recovery_epoch"],
                            expected_uid=os.getuid(), expected_gid=os.getgid())
    app = create_app(owned / "data", deployment_config=configuration, session_root_dir=owned / "root",
                     expected_uid=os.getuid(), expected_gid=os.getgid())
    print(f"OWNER_LIFECYCLE_URL={profile.http_origin}{profile.base_path}", flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, timeout_graceful_shutdown=3)).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
