"""Real store/service/HTTP fixture; only Codex and model process boundaries are controlled."""

import argparse
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.adapters.keychain import InMemoryCredentialVault
from app.codex_connection import CodexConnection
from app.codex_rpc import CodexRPC
from app.server import create_app
from app.understanding import ModelError

parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', type=Path, required=True)
parser.add_argument('--port', type=int, default=0)
parser.add_argument('--not-ready', action='store_true')
parser.add_argument('--scenario', choices=['success', 'slow', 'cancel', 'fail-once', 'subscription_required', 'isolation_unavailable'], default='success')
args = parser.parse_args()
calls = 0


class ControlledModel:
    def generate(self, prompt, schema, cancel_event, *, selection=None):
        global calls
        calls += 1
        value = json.loads(prompt.split('UNTRUSTED INPUT ENVELOPE (JSON):\n', 1)[1])
        with (args.data_dir / 'model-calls.jsonl').open('a') as output:
            output.write(json.dumps(value, ensure_ascii=False) + '\n')
        if args.scenario in {'subscription_required', 'isolation_unavailable'}:
            raise ModelError(args.scenario)
        if args.scenario == 'fail-once' and calls == 1:
            raise ModelError('provider_unavailable')
        if cancel_event.wait(20 if args.scenario == 'cancel' else 1.5 if args.scenario == 'slow' else .05):
            raise ModelError('interrupted')
        source = next(item for item in value['sources'] if item['text'].strip())
        evidence = [{'source_id': source['source_id'], 'quote': source['text'][:200]}]
        result = {
            'summary': {'text': '업무 이해 초안: ' + source['text'][:200], 'evidence': evidence},
            'deliverables': [{'name': '회의용 PDF', 'media_type': 'application/pdf', 'description': '검토할 산출물의 형태입니다.', 'evidence': evidence}],
            'constraints': [{'text': '회의 전에 검토가 필요합니다.', 'evidence': evidence}],
            'open_questions': [{'question': '누가 최종 검토하나요?', 'why_needed': '검토 책임자를 아직 알 수 없습니다.'}],
            'assumptions': ['<img src=x onerror=window.injected=1> 검토가 한 차례 필요하다고 잠정 가정합니다.'],
        }
        return {'text': json.dumps(result, ensure_ascii=False), 'model': selection['model'] if selection else 'controlled-test-model'}


def manager(store):
    fake = str(Path(__file__).with_name('fake_codex_rpc.py'))
    def rpc_factory(_command, *, cwd, env=None, timeout=10):
        return CodexRPC([sys.executable, '-u', fake, '--account', 'chatgpt'], cwd=cwd, env=env, timeout=timeout)
    return CodexConnection(store, rpc_factory=rpc_factory)


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(('127.0.0.1', args.port))
port = sock.getsockname()[1]
with patch('app.codex_connection.find_codex', return_value=str(Path(__file__).with_name('fake_codex_rpc.py'))):
    app = create_app(args.data_dir, port=port, codex_factory=manager,
                     understanding_model_factory=ControlledModel,
                     understanding_provider_ready=not args.not_ready,
                     credential_vault=InMemoryCredentialVault())

    @app.get('/__test__/launch')
    def test_launch():
        return {'capability': app.state.local_sessions.mint_bootstrap().capability}

    print(f'DEEPTWIN_URL=http://127.0.0.1:{port}', flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])
