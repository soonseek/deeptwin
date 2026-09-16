"""Owned historical preview fixture; never the supported web serving entry."""
import argparse
import socket
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.server import create_development_app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", args.port))
        port = sock.getsockname()[1]
        application = create_development_app(args.data_dir, port=port)
        capability = application.state.local_sessions.mint_bootstrap()
        print(f"DEEPTWIN_URL=http://127.0.0.1:{port}/#bootstrap={capability.capability}", flush=True)
        uvicorn.Server(uvicorn.Config(application, log_level="warning", access_log=False)).run(sockets=[sock])


if __name__ == "__main__":
    main()
