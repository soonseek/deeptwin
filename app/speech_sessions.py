"""Revision-bound local speech sessions. Audio never enters SQLite or events."""

from datetime import datetime, timezone
import hashlib
import json
import threading
import time
from uuid import uuid4

from .speech import (MAX_PCM_BYTES, MIN_PCM_BYTES, SpeechBusy, SpeechCancelled,
                     SpeechUnavailable, _strict_json)
from .storage import ConflictError


# Idle cleanup happens on explicit start/transcribe, not a background recorder.
LEASE_SECONDS = 300
MAX_SEQUENCE = 128


class SpeechSessionClosed(ValueError):
    def __init__(self):
        super().__init__('종료되거나 만료된 음성 입력입니다. 음성 입력을 새로 시작해 주세요.')


def now():
    return datetime.now(timezone.utc).isoformat()


class SpeechSessions:
    def __init__(self, store, speech, *, clock=None):
        self.store, self.speech = store, speech
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._pending = {}
        self._leases = {}
        self._closed = False
        with store._connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS speech_sessions (
                    id TEXT PRIMARY KEY, work_id TEXT NOT NULL, revision INTEGER NOT NULL,
                    status TEXT NOT NULL, next_sequence INTEGER NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(work_id, revision) REFERENCES revisions(work_id, revision));
                CREATE TABLE IF NOT EXISTS speech_transcripts (
                    session_id TEXT NOT NULL REFERENCES speech_sessions(id), sequence INTEGER NOT NULL,
                    utterance INTEGER NOT NULL, final INTEGER NOT NULL,
                    pcm_sha256 TEXT NOT NULL, pcm_size INTEGER NOT NULL,
                    status TEXT NOT NULL, result_json TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, sequence));
            ''')
            for session in db.execute("SELECT * FROM speech_sessions WHERE status='active'").fetchall():
                self._end(db, session, 'interrupted')

    @staticmethod
    def _public(session):
        return {name: session[name] for name in ('id', 'work_id', 'revision', 'status')}

    @staticmethod
    def _session(db, session_id):
        if not isinstance(session_id, str):
            raise ValueError('Invalid session identifier')
        row = db.execute('SELECT * FROM speech_sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        return row

    def _event(self, db, session, kind, **metadata):
        self.store._event(db, kind, session['work_id'],
                          {'session_id': session['id'], 'revision': session['revision'], **metadata})

    def _end(self, db, session, status):
        db.execute('UPDATE speech_sessions SET status=?, updated_at=? WHERE id=?',
                   (status, now(), session['id']))
        db.execute("UPDATE speech_transcripts SET status=?, updated_at=? WHERE session_id=? AND status='pending'",
                   (status, now(), session['id']))
        self._event(db, session, 'speech_session_' + status)

    def _signal_closed(self, session_ids):
        # Caller holds the session lock and has committed the state change.
        for session_id in session_ids:
            self._leases.pop(session_id, None)
            if session_id in self._pending:
                self._pending[session_id].set()

    def _expire(self):
        expired = [session_id for session_id, touched in self._leases.items()
                   if self._clock() - touched >= LEASE_SECONDS]
        if not expired:
            return
        with self.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for session_id in expired:
                session = self._session(db, session_id)
                if session['status'] == 'active':
                    self._end(db, session, 'expired')
        self._signal_closed(expired)

    def start(self, work_id, revision):
        if type(revision) is not int or revision < 1 or not isinstance(work_id, str):
            raise ValueError('Exact work revision required')
        with self._lock:
            if self._closed:
                raise SpeechSessionClosed()
            self._expire()
            with self.store._connection() as db:
                db.execute('BEGIN IMMEDIATE')
                work = self.store._work(db, work_id)
                if work['revision'] != revision:
                    raise ConflictError('Work revision changed')
                if db.execute("SELECT 1 FROM speech_sessions WHERE status='active' LIMIT 1").fetchone():
                    raise SpeechBusy()
                stamp, session_id = now(), str(uuid4())
                db.execute('INSERT INTO speech_sessions VALUES(?,?,?,?,?,?,?)',
                           (session_id, work_id, revision, 'active', 1, stamp, stamp))
                session = self._session(db, session_id)
                self._event(db, session, 'speech_session_started')
            self._leases[session_id] = self._clock()
            return self._public(session)

    @staticmethod
    def _validate(sequence, utterance, final, pcm):
        if (type(sequence) is not int or not 1 <= sequence <= MAX_SEQUENCE
                or type(utterance) is not int or not 1 <= utterance <= MAX_SEQUENCE
                or type(final) is not bool):
            raise ValueError('Invalid speech sequence, utterance, or final marker')
        if not isinstance(pcm, bytes) or not MIN_PCM_BYTES <= len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
            raise ValueError('Expected 0.25–8 seconds PCM16LE mono 16kHz')

    @staticmethod
    def _result(value):
        if (not isinstance(value, dict) or not isinstance(value.get('text'), str)
                or len(value['text']) > 20_000 or value.get('engine') != 'whisper.cpp'
                or value.get('model') != 'base' or value.get('language') != 'ko'
                or type(value.get('elapsed_ms')) is not int or value['elapsed_ms'] < 0):
            raise SpeechUnavailable()
        return {key: value[key] for key in ('text', 'engine', 'model', 'language', 'elapsed_ms')}

    def _replay(self, raw, session, sequence, utterance, final):
        # Persisted JSON is an input boundary too; never replay corrupt content
        # or repair it by silently running the engine again.
        try:
            value = _strict_json(raw)
        except (TypeError, ValueError):
            raise SpeechUnavailable() from None
        keys = {'session_id', 'work_id', 'sequence', 'utterance', 'final',
                'text', 'engine', 'model', 'language', 'elapsed_ms'}
        if (not isinstance(value, dict) or set(value) != keys
                or value['session_id'] != session['id'] or value['work_id'] != session['work_id']
                or type(value['sequence']) is not int or value['sequence'] != sequence
                or type(value['utterance']) is not int or value['utterance'] != utterance
                or type(value['final']) is not bool or value['final'] != final):
            raise SpeechUnavailable()
        return {'session_id': session['id'], 'work_id': session['work_id'],
                'sequence': sequence, 'utterance': utterance, 'final': final,
                **self._result(value)}

    def transcribe(self, session_id, sequence, utterance, final, pcm):
        self._validate(sequence, utterance, final, pcm)
        digest = hashlib.sha256(pcm).hexdigest()
        with self._lock:
            if self._closed:
                raise SpeechSessionClosed()
            self._expire()
            with self.store._connection() as db:
                db.execute('BEGIN IMMEDIATE')
                session = self._session(db, session_id)
                if session['status'] != 'active':
                    raise SpeechSessionClosed()
                prior = db.execute('SELECT * FROM speech_transcripts WHERE session_id=? AND sequence=?',
                                   (session_id, sequence)).fetchone()
                if prior:
                    if (prior['pcm_sha256'] != digest or prior['pcm_size'] != len(pcm)
                            or prior['utterance'] != utterance or prior['final'] != int(final)):
                        raise ValueError('Sequence belongs to different audio or markers')
                    if prior['status'] == 'completed':
                        result = self._replay(prior['result_json'], session, sequence, utterance, final)
                        self._leases[session_id] = self._clock()
                        return result
                if sequence != session['next_sequence']:
                    raise ValueError('Speech sequence must be consecutive')
                if self._pending:
                    raise SpeechBusy()
                stamp = now()
                if prior:
                    db.execute("UPDATE speech_transcripts SET status='pending', updated_at=? WHERE session_id=? AND sequence=?",
                               (stamp, session_id, sequence))
                else:
                    db.execute('INSERT INTO speech_transcripts VALUES(?,?,?,?,?,?,?,?,?,?)',
                               (session_id, sequence, utterance, int(final), digest, len(pcm), 'pending', None, stamp, stamp))
                self._event(db, session, 'speech_transcription_requested', sequence=sequence,
                            utterance=utterance, final=final, pcm_sha256=digest, pcm_size=len(pcm))
            cancel = threading.Event()
            self._pending[session_id] = cancel
            self._leases[session_id] = self._clock()

        # No session lock during inference: close/expiry can persist and signal cancellation.
        try:
            try:
                value = self._result(self.speech.transcribe(pcm, cancel_event=cancel))
            except Exception as error:
                with self._lock, self.store._connection() as db:
                    db.execute('BEGIN IMMEDIATE')
                    current = self._session(db, session_id)
                    if current['status'] != 'active' or cancel.is_set():
                        raise SpeechSessionClosed() from None
                    db.execute("UPDATE speech_transcripts SET status='failed', updated_at=? WHERE session_id=? AND sequence=?",
                               (now(), session_id, sequence))
                    self._event(db, current, 'speech_transcription_failed', sequence=sequence)
                if isinstance(error, (SpeechBusy, SpeechCancelled, SpeechUnavailable)):
                    raise
                raise SpeechUnavailable() from None
            with self._lock, self.store._connection() as db:
                db.execute('BEGIN IMMEDIATE')
                current = self._session(db, session_id)
                if current['status'] != 'active' or cancel.is_set():
                    raise SpeechSessionClosed()
                result = {'session_id': session_id, 'work_id': current['work_id'], 'sequence': sequence,
                          'utterance': utterance, 'final': final, **value}
                db.execute("UPDATE speech_transcripts SET status='completed', result_json=?, updated_at=? WHERE session_id=? AND sequence=?",
                           (json.dumps(result, ensure_ascii=False), now(), session_id, sequence))
                db.execute('UPDATE speech_sessions SET next_sequence=?, updated_at=? WHERE id=?',
                           (sequence + 1, now(), session_id))
                self._event(db, current, 'speech_transcription_completed', sequence=sequence,
                            utterance=utterance, final=final, pcm_sha256=digest)
            return result
        finally:
            with self._lock:
                if self._pending.get(session_id) is cancel:
                    self._pending.pop(session_id)

    def close_session(self, session_id):
        with self._lock:
            with self.store._connection() as db:
                db.execute('BEGIN IMMEDIATE')
                session = self._session(db, session_id)
                if session['status'] == 'active':
                    self._end(db, session, 'closed')
                    session = self._session(db, session_id)
            self._signal_closed([session_id])
            return self._public(session)

    def close(self):
        with self._lock:
            with self.store._connection() as db:
                db.execute('BEGIN IMMEDIATE')
                owned = list(self._leases)
                for session_id in owned:
                    session = self._session(db, session_id)
                    if session['status'] == 'active':
                        self._end(db, session, 'closed')
            self._closed = True
            self._signal_closed(owned)
