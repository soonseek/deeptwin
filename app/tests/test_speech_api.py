from app.tests.local_http import LocalTestClient as TestClient
import pytest
import sqlite3

from app.server import create_development_app as create_app


class Engine:
    def __init__(self):
        self.calls = []
        self.closed = False

    def snapshot(self):
        return {'ready': True, 'engine': 'whisper.cpp', 'model': 'base',
                'language': 'ko', 'message': 'controlled local engine'}

    def transcribe(self, pcm, cancel_event=None):
        self.calls.append(pcm)
        return {'text': '새 발화', 'engine': 'whisper.cpp', 'model': 'base',
                'language': 'ko', 'elapsed_ms': 1}

    def close(self):
        self.closed = True


def test_speech_http_is_explicit_local_and_does_not_edit_original_input(tmp_path):
    engine = Engine()
    app = create_app(tmp_path, speech_factory=lambda store: engine)
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        headers = {'X-CSRF-Token': client.csrf_token}
        assert client.get('/api/speech').json()['ready'] is True
        assert engine.calls == []
        work = client.post('/api/works', json={'text': '이미 쓴 글'}, headers=headers).json()
        body = {'work_id': work['id'], 'revision': 1}
        assert client.post('/api/speech/sessions', json=body).status_code == 403
        opened = client.post('/api/speech/sessions', json=body, headers=headers)
        assert opened.status_code == 201, opened.text
        session = opened.json()
        assert engine.calls == []
        base = '/api/speech/sessions/' + session['id']
        pcm = b'\x01\x00' * 8000
        url = base + '/chunks?sequence=1&utterance=1&final=false'
        sent = client.post(url, content=pcm, headers={**headers, 'Content-Type': 'audio/pcm'})
        assert sent.status_code == 200, sent.text
        assert sent.json()['text'] == '새 발화'
        assert sent.json()['work_id'] == work['id'] and sent.json()['final'] is False
        assert client.post(url, content=pcm, headers={**headers, 'Content-Type': 'audio/pcm'}).json() == sent.json()
        assert len(engine.calls) == 1
        assert client.get('/api/works/' + work['id']).json() == work
        assert client.post(base + '/close', json={}, headers=headers).json()['status'] == 'closed'
        assert client.post(url, content=pcm, headers={**headers, 'Content-Type': 'audio/pcm'}).status_code == 400
    assert engine.closed is True


def test_pcm_bounds_query_and_content_type_reject_before_engine(tmp_path):
    engine = Engine()
    app = create_app(tmp_path, speech_factory=lambda store: engine)
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        headers = {'X-CSRF-Token': client.csrf_token}
        work = client.post('/api/works', json={'text': ''}, headers=headers).json()
        session = client.post('/api/speech/sessions', json={'work_id': work['id'], 'revision': 1}, headers=headers).json()
        base = '/api/speech/sessions/' + session['id'] + '/chunks'
        query = '?sequence=1&utterance=1&final=true'
        pcm = b'\x01\x00' * 8000
        for query_string in ['?sequence=true&utterance=1&final=true', '?sequence=1&utterance=1&final=1',
                             '?sequence=1&utterance=1&final=true&extra=x', '?sequence=1&sequence=2&utterance=1&final=true']:
            assert client.post(base + query_string, content=pcm, headers={**headers, 'Content-Type': 'audio/pcm'}).status_code == 400
        assert client.post(base + query, content=pcm, headers={**headers, 'Content-Type': 'application/json'}).status_code == 400
        for raw, status in [(b'\0' * 7998, 400), (b'\0' * 8001, 400), (b'\0' * 256002, 413)]:
            response = client.post(base + query, content=raw, headers={**headers, 'Content-Type': 'audio/pcm'})
            assert response.status_code == status
            if status == 413:
                assert '음성' in response.json()['detail'] and '10MB' not in response.json()['detail']
        assert engine.calls == []


def test_speech_worklet_is_same_origin_script_not_arbitrary_file(tmp_path):
    app = create_app(tmp_path, speech_factory=lambda store: Engine())
    with TestClient(app, base_url='http://127.0.0.1:4193') as client:
        response = client.get('/audio-capture-worklet.mjs')
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('application/javascript')
        assert client.get('/native/speech_worker.cpp').status_code == 404


def test_shutdown_still_closes_engines_when_session_state_cannot_be_saved(tmp_path):
    engine = Engine()
    app = create_app(tmp_path, speech_factory=lambda store: engine)
    connection_closed = []
    app.state.codex.close = lambda: connection_closed.append(True)
    with pytest.raises(sqlite3.IntegrityError):
        with TestClient(app, base_url='http://127.0.0.1:4193'):
            store = app.state.store
            work = store.create_work('')
            app.state.speech_sessions.start(work['id'], 1)
            with store._connection() as db:
                db.execute("""CREATE TRIGGER reject_speech_close BEFORE UPDATE ON speech_sessions
                    WHEN NEW.status = 'closed' BEGIN SELECT RAISE(ABORT, 'controlled failure'); END""")
    assert engine.closed
    assert app.state.understanding._closed
    assert connection_closed == [True]
