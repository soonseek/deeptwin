"""Real HTTP/store/speech-session fixture with only local inference controlled."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import sys
from unittest.mock import patch

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from app.server import create_app
from app.speech import SpeechCancelled
from app.codex_connection import CodexConnection
from app.codex_rpc import CodexRPC

parser = argparse.ArgumentParser()
parser.add_argument('--data-dir', type=Path, required=True)
parser.add_argument('--port', type=int, default=0)
parser.add_argument('--not-ready', action='store_true')
parser.add_argument('--delay', type=float, default=.02)
parser.add_argument('--understanding-ready', action='store_true')
args = parser.parse_args()


class ControlledSpeech:
    def __init__(self, store):
        self.store = store

    def snapshot(self):
        return {'ready': not args.not_ready, 'engine': 'whisper.cpp', 'model': 'base', 'language': 'ko',
                'message': '이 컴퓨터에서 음성 입력을 준비했습니다.' if not args.not_ready else '로컬 음성 엔진이 준비되지 않았습니다.'}

    def transcribe(self, pcm, cancel_event=None):
        # Keep byte metadata only, not microphone audio, in the test audit.
        with (args.data_dir / 'speech-calls.jsonl').open('a') as output:
            output.write(json.dumps({'size': len(pcm), 'sha256': hashlib.sha256(pcm).hexdigest(), 'nonzero': any(pcm)}) + '\n')
        if cancel_event.wait(args.delay):
            raise SpeechCancelled()
        return {'text': '음성으로 더한 말', 'engine': 'whisper.cpp', 'model': 'base', 'language': 'ko', 'elapsed_ms': 20}

    def close(self):
        pass


class ForbiddenUnderstanding:
    def generate(self, *_args, **_kwargs):
        raise RuntimeError('Speech tests never invoke a language model')


def manager(store):
    fake = str(Path(__file__).with_name('fake_codex_rpc.py'))
    def rpc_factory(_command, *, cwd, env=None, timeout=10):
        return CodexRPC([sys.executable, '-u', fake, '--account', 'chatgpt'], cwd=cwd, env=env, timeout=timeout)
    return CodexConnection(store, rpc_factory=rpc_factory)


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind(('127.0.0.1', args.port))
port = sock.getsockname()[1]
with patch('app.codex_connection.find_codex', return_value=str(Path(__file__).with_name('fake_codex_rpc.py'))):
    app = create_app(args.data_dir, port=port, speech_factory=ControlledSpeech, codex_factory=manager,
                     understanding_model_factory=ForbiddenUnderstanding, understanding_provider_ready=args.understanding_ready)

    @app.get('/__test__/launch')
    def test_launch():
        return {'capability': app.state.local_sessions.mint_bootstrap().capability}

    print(f'DEEPTWIN_URL=http://127.0.0.1:{port}', flush=True)
    uvicorn.Server(uvicorn.Config(app, log_level='warning', access_log=False)).run(sockets=[sock])
