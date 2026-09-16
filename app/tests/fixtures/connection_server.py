"""Real app/manager/RPC with a controlled child; never launch the user's Codex."""

import argparse
from pathlib import Path
import socket
import sys
from unittest.mock import patch

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.codex_connection import CodexConnection
from app.codex_rpc import CodexRPC
from app.server import create_development_app as create_app


parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', type=Path, required=True)
parser.add_argument('--port', type=int, default=0)
parser.add_argument('--scenario', required=True, choices=[
    'connected', 'api-key', 'pending', 'complete', 'failure', 'unsafe-url', 'unknown-limits',
])
args = parser.parse_args()
account = 'chatgpt' if args.scenario in {'connected', 'unknown-limits'} else 'apiKey' if args.scenario == 'api-key' else 'none'
login = args.scenario if args.scenario in {'complete', 'failure'} else 'pending'
command = [sys.executable, '-u', str(Path(__file__).with_name('fake_codex_rpc.py')),
           '--account', account, '--login', login, '--limits', 'unknown' if args.scenario == 'unknown-limits' else 'known']
if args.scenario == 'unsafe-url':
    command.extend(['--auth-url', 'https://auth.openai.com.attacker.invalid/authorize'])


def manager(store):
    def rpc_factory(_official_command, *, cwd, env=None, timeout=10):
        return CodexRPC(command, cwd=cwd, env=env, timeout=timeout)
    return CodexConnection(store, rpc_factory=rpc_factory)


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(('127.0.0.1', args.port))
port = sock.getsockname()[1]
# Discovery and transport are both controlled boundaries. This fixture does not
# require a real Codex installation and never opens its credential store.
with patch('app.codex_connection.find_codex', return_value=str(Path(__file__).with_name('fake_codex_rpc.py'))):
    app = create_app(args.data_dir, port=port, codex_factory=manager)

    @app.get('/__test__/launch')
    def test_launch():
        return {'capability': app.state.local_sessions.mint_bootstrap().capability}

    print(f'DEEPTWIN_URL=http://127.0.0.1:{port}', flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])
