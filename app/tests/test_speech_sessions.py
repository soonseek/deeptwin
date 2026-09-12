"""Actual SQLite session/sequence contracts with a controlled local engine."""

import hashlib
import importlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.speech import SpeechBusy, SpeechUnavailable
from app.storage import ConflictError, Store

PCM = b'\x01\x00' * 4000


def module():
    assert importlib.util.find_spec('app.speech_sessions'), 'Speech session service is missing'
    return importlib.import_module('app.speech_sessions')


class Engine:
    def __init__(self, blocked=False):
        self.calls = []
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail = False
        if not blocked:
            self.release.set()

    def transcribe(self, pcm, cancel_event=None):
        self.calls.append((pcm, cancel_event))
        self.entered.set()
        assert self.release.wait(3)
        if self.fail:
            raise SpeechUnavailable()
        return {'text': '\n내 음성 원문', 'engine': 'whisper.cpp', 'model': 'base',
                'language': 'ko', 'elapsed_ms': 12}


def fixture(tmp_path, blocked=False):
    store = Store(tmp_path)
    work = store.create_work('\n기존 업무 설명')
    engine = Engine(blocked)
    service = module().SpeechSessions(store, engine)
    return store, work, engine, service


def test_start_requires_exact_revision_and_does_not_start_engine(tmp_path):
    store, work, engine, service = fixture(tmp_path)
    with pytest.raises(ConflictError):
        service.start(work['id'], 2)
    with pytest.raises(ValueError):
        service.start(work['id'], True)
    session = service.start(work['id'], 1)
    assert session == {'id': session['id'], 'work_id': work['id'], 'revision': 1, 'status': 'active'}
    with pytest.raises(SpeechBusy):
        service.start(work['id'], 1)
    assert not engine.calls and store.get_work(work['id']) == work


def test_sequence_replay_is_exact_and_pcm_never_enters_database(tmp_path):
    store, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    result = service.transcribe(session['id'], 1, 1, False, PCM)
    assert result['text'] == '\n내 음성 원문' and result['final'] is False
    assert result['session_id'] == session['id'] and result['work_id'] == work['id']
    assert result['sequence'] == 1 and result['utterance'] == 1
    assert service.transcribe(session['id'], 1, 1, False, PCM) == result
    assert len(engine.calls) == 1
    for args in [(1, 1, False, b'\x02\x00' * 4000), (1, 2, False, PCM), (1, 1, True, PCM)]:
        with pytest.raises(ValueError):
            service.transcribe(session['id'], *args)
    with pytest.raises(ValueError):
        service.transcribe(session['id'], 3, 1, True, PCM)
    final = service.transcribe(session['id'], 2, 1, True, PCM)
    assert final['final'] is True
    assert store.get_work(work['id']) == work
    with store._connection() as db:
        rows = [dict(row) for row in db.execute('SELECT * FROM speech_transcripts')]
    assert len(rows) == 2 and rows[0]['pcm_sha256'] == hashlib.sha256(PCM).hexdigest()
    assert rows[0]['pcm_size'] == len(PCM)
    assert not any(isinstance(value, bytes) for row in rows for value in row.values())
    assert '\n내 음성 원문' not in json.dumps(store.events(), ensure_ascii=False)
    assert '내 음성 원문' in json.dumps(rows, ensure_ascii=False)


@pytest.mark.parametrize('sequence,utterance,final,pcm', [
    (True, 1, False, PCM), (0, 1, False, PCM), (129, 1, False, PCM),
    (1, True, False, PCM), (1, 0, False, PCM), (1, 129, False, PCM),
    (1, 1, 1, PCM), (1, 1, False, b'x'), (1, 1, False, bytes(256002)),
], ids=['seq-bool', 'seq-zero', 'seq-cap', 'utterance-bool', 'utterance-zero', 'utterance-cap',
        'final-int', 'odd-pcm', 'oversize-pcm'])
def test_bad_frames_do_not_call_engine_or_reserve_sequence(tmp_path, sequence, utterance, final, pcm):
    store, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    before = store.events()
    with pytest.raises(ValueError):
        service.transcribe(session['id'], sequence, utterance, final, pcm)
    assert not engine.calls and store.events() == before


def test_failed_engine_same_sequence_can_retry_without_auto_advance(tmp_path):
    _, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    engine.fail = True
    with pytest.raises(SpeechUnavailable):
        service.transcribe(session['id'], 1, 1, False, PCM)
    with pytest.raises(ValueError):
        service.transcribe(session['id'], 2, 1, True, PCM)
    engine.fail = False
    assert service.transcribe(session['id'], 1, 1, False, PCM)['sequence'] == 1


def test_close_during_engine_discards_late_result_and_signals_cancel(tmp_path):
    store, work, engine, service = fixture(tmp_path, blocked=True)
    session = service.start(work['id'], 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.transcribe, session['id'], 1, 1, False, PCM)
        assert engine.entered.wait(2)
        with pytest.raises(SpeechBusy):
            service.transcribe(session['id'], 1, 1, False, PCM)
        closed = service.close_session(session['id'])
        assert closed['status'] == 'closed'
        assert engine.calls[0][1].is_set()
        engine.release.set()
        with pytest.raises(module().SpeechSessionClosed):
            pending.result(timeout=2)
    with store._connection() as db:
        row = dict(db.execute('SELECT * FROM speech_transcripts').fetchone())
    assert row['result_json'] is None
    assert '내 음성 원문' not in json.dumps(row, ensure_ascii=False)
    assert service.close_session(session['id']) == closed
    with pytest.raises(module().SpeechSessionClosed):
        service.transcribe(session['id'], 1, 1, False, PCM)
    with pytest.raises(KeyError):
        service.close_session('missing')


def test_close_commit_failure_does_not_cancel_unclosed_engine(tmp_path):
    store, work, engine, service = fixture(tmp_path, blocked=True)
    session = service.start(work['id'], 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.transcribe, session['id'], 1, 1, False, PCM)
        assert engine.entered.wait(2)
        with store._connection() as db:
            db.executescript('''CREATE TRIGGER fail_close BEFORE UPDATE ON speech_sessions
                WHEN NEW.status='closed' BEGIN SELECT RAISE(ABORT,'controlled failure'); END;''')
        with pytest.raises(sqlite3.IntegrityError):
            service.close_session(session['id'])
        assert not engine.calls[0][1].is_set()
        engine.release.set()
        assert pending.result(timeout=2)['text'] == '\n내 음성 원문'


def test_request_commit_failure_never_calls_engine(tmp_path):
    store, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    with store._connection() as db:
        db.executescript('''CREATE TABLE review_parent(id INTEGER PRIMARY KEY);
            CREATE TABLE review_deferred(id INTEGER REFERENCES review_parent(id) DEFERRABLE INITIALLY DEFERRED);
            CREATE TRIGGER fail_request AFTER INSERT ON speech_transcripts BEGIN
            INSERT INTO review_deferred VALUES(999); END;''')
    with pytest.raises(sqlite3.IntegrityError):
        service.transcribe(session['id'], 1, 1, False, PCM)
    assert not engine.calls
    with store._connection() as db:
        assert db.execute('SELECT COUNT(*) FROM speech_transcripts').fetchone()[0] == 0


def test_restart_interrupts_active_session_and_never_resumes_audio(tmp_path):
    store, work, engine, original = fixture(tmp_path)
    session = original.start(work['id'], 1)
    restored = module().SpeechSessions(store, engine)
    with pytest.raises(module().SpeechSessionClosed):
        restored.transcribe(session['id'], 1, 1, False, PCM)
    with store._connection() as db:
        assert db.execute('SELECT status FROM speech_sessions WHERE id=?', (session['id'],)).fetchone()[0] == 'interrupted'
    assert not engine.calls
    assert restored.start(work['id'], 1)['id'] != session['id']


def test_service_close_prevents_new_sessions(tmp_path):
    _, work, _, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    service.close()
    with pytest.raises(module().SpeechSessionClosed):
        service.start(work['id'], 1)
    with pytest.raises(module().SpeechSessionClosed):
        service.transcribe(session['id'], 1, 1, True, PCM)


def test_idle_lease_expires_only_on_action_without_auto_resume(tmp_path):
    store = Store(tmp_path)
    work = store.create_work('업무')
    clock = [0.0]
    engine = Engine()
    service = module().SpeechSessions(store, engine, clock=lambda: clock[0])
    session = service.start(work['id'], 1)
    clock[0] = 299
    with pytest.raises(SpeechBusy):
        service.start(work['id'], 1)
    clock[0] = 301
    new = service.start(work['id'], 1)
    assert new['id'] != session['id'] and not engine.calls
    with pytest.raises(module().SpeechSessionClosed):
        service.transcribe(session['id'], 1, 1, False, PCM)
    with store._connection() as db:
        assert db.execute('SELECT status FROM speech_sessions WHERE id=?', (session['id'],)).fetchone()[0] == 'expired'


def test_active_frame_refreshes_idle_lease(tmp_path):
    store = Store(tmp_path)
    work = store.create_work('업무')
    clock = [0.0]
    service = module().SpeechSessions(store, Engine(), clock=lambda: clock[0])
    session = service.start(work['id'], 1)
    clock[0] = 299
    service.transcribe(session['id'], 1, 1, True, PCM)
    clock[0] = 500
    with pytest.raises(SpeechBusy):
        service.start(work['id'], 1)
    clock[0] = 600
    assert service.start(work['id'], 1)['id'] != session['id']


def test_lease_expiry_cancels_inflight_engine_before_accepting_new_session(tmp_path):
    store = Store(tmp_path)
    work = store.create_work('업무')
    clock = [0.0]
    engine = Engine(blocked=True)
    service = module().SpeechSessions(store, engine, clock=lambda: clock[0])
    session = service.start(work['id'], 1)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(service.transcribe, session['id'], 1, 1, False, PCM)
        assert engine.entered.wait(2)
        clock[0] = 301
        replacement = service.start(work['id'], 1)
        assert replacement['id'] != session['id']
        assert engine.calls[0][1].is_set()
        engine.release.set()
        with pytest.raises(module().SpeechSessionClosed):
            pending.result(timeout=2)
    with store._connection() as db:
        row = dict(db.execute('SELECT * FROM speech_transcripts').fetchone())
    assert row['status'] == 'expired' and row['result_json'] is None


def test_128_successful_slots_are_bound_and_last_replay_does_not_call_engine(tmp_path):
    _, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    for sequence in range(1, 129):
        service.transcribe(session['id'], sequence, sequence, True, PCM)
    assert len(engine.calls) == 128
    assert service.transcribe(session['id'], 128, 128, True, PCM)['sequence'] == 128
    assert len(engine.calls) == 128
    with pytest.raises(ValueError):
        service.transcribe(session['id'], 129, 128, True, PCM)


def test_completion_storage_failure_does_not_publish_text_or_advance(tmp_path):
    store, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    with store._connection() as db:
        db.executescript('''CREATE TRIGGER fail_complete BEFORE UPDATE ON speech_transcripts
            WHEN NEW.status='completed' BEGIN SELECT RAISE(ABORT,'controlled failure'); END;''')
    with pytest.raises(sqlite3.IntegrityError):
        service.transcribe(session['id'], 1, 1, False, PCM)
    with store._connection() as db:
        transcript = dict(db.execute('SELECT * FROM speech_transcripts').fetchone())
        assert transcript['result_json'] is None
        assert db.execute('SELECT next_sequence FROM speech_sessions').fetchone()[0] == 1
        db.execute('DROP TRIGGER fail_complete')
    assert service.transcribe(session['id'], 1, 1, False, PCM)['text'] == '\n내 음성 원문'
    assert len(engine.calls) == 2


@pytest.mark.parametrize('change', ['array', 'null', 'invalid-json', 'extra', 'missing',
                                  'session', 'work', 'sequence', 'sequence-bool', 'utterance',
                                  'utterance-float', 'final', 'final-int', 'text', 'engine', 'elapsed'])
def test_corrupt_completed_reply_is_unavailable_without_new_engine_call(tmp_path, change):
    store, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    result = service.transcribe(session['id'], 1, 1, False, PCM)
    bad = dict(result)
    updates = {'extra': {'unknown': 'field'}, 'session': {'session_id': 'other'},
               'work': {'work_id': 'other'}, 'sequence': {'sequence': 2},
               'sequence-bool': {'sequence': True}, 'utterance': {'utterance': 2},
               'utterance-float': {'utterance': 1.0}, 'final': {'final': True},
               'final-int': {'final': 0}, 'text': {'text': None},
               'engine': {'engine': 'remote'}, 'elapsed': {'elapsed_ms': True}}
    if change in updates:
        bad.update(updates[change])
    elif change == 'array':
        bad = [1, 2, 3]
    elif change == 'null':
        bad = None
    elif change == 'missing':
        bad.pop('text')
    encoded = 'not-json' if change == 'invalid-json' else json.dumps(bad)
    with store._connection() as db:
        db.execute('UPDATE speech_transcripts SET result_json=?', (encoded,))
    before = store.events()
    with pytest.raises(SpeechUnavailable):
        service.transcribe(session['id'], 1, 1, False, PCM)
    assert len(engine.calls) == 1 and store.events() == before
    with store._connection() as db:
        row = dict(db.execute('SELECT * FROM speech_transcripts').fetchone())
    assert row['result_json'] == encoded
    assert row['pcm_sha256'] == hashlib.sha256(PCM).hexdigest()


def test_duplicate_key_in_completed_reply_is_not_replayed(tmp_path):
    store, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    result = service.transcribe(session['id'], 1, 1, False, PCM)
    encoded = json.dumps(result, ensure_ascii=False).replace(
        '"text": "\\n내 음성 원문"', '"text": "숨긴 값", "text": "\\n내 음성 원문"')
    with store._connection() as db:
        db.execute('UPDATE speech_transcripts SET result_json=?', (encoded,))
    with pytest.raises(SpeechUnavailable):
        service.transcribe(session['id'], 1, 1, False, PCM)
    assert len(engine.calls) == 1


def test_autosave_revision_change_does_not_retarget_or_interrupt_dictation(tmp_path):
    store, work, engine, service = fixture(tmp_path)
    session = service.start(work['id'], 1)
    first = service.transcribe(session['id'], 1, 1, False, PCM)
    saved = store.update_work(work['id'], '자동 저장된 새 글', 1)
    assert service.transcribe(session['id'], 1, 1, False, PCM) == first
    assert service.transcribe(session['id'], 2, 1, True, PCM)['work_id'] == work['id']
    assert store.get_work(work['id']) == saved
    with store._connection() as db:
        assert db.execute('SELECT revision FROM speech_sessions').fetchone()[0] == 1
    assert len(engine.calls) == 2
