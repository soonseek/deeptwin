"""Revision-bound requests share the intake transaction and instance event log.

There is deliberately no worker yet. A recorded request is blocked, never
fabricated as a pending/running design or as an inferred user approval.
Previously stored request payloads remain immutable historical records.
"""

from datetime import datetime, timezone
import json
from uuid import uuid4

from .storage import ConflictError


SUPPORTED_PROVIDER_MODES = frozenset({
    ('claude', 'api'),
    ('codex', 'subscription'),
    ('codex', 'api'),
})


class Requests:
    def __init__(self, store):
        self.store = store
        with store._connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS design_requests (
                id TEXT PRIMARY KEY, work_id TEXT NOT NULL, revision INTEGER NOT NULL,
                provider TEXT NOT NULL, mode TEXT NOT NULL, payload TEXT NOT NULL,
                UNIQUE(work_id, revision, provider, mode),
                FOREIGN KEY(work_id, revision) REFERENCES revisions(work_id, revision))''')

    def list_for(self, work_id):
        self.store.get_work(work_id)
        with self.store._connection() as db:
            return [json.loads(row[0]) for row in db.execute(
                'SELECT payload FROM design_requests WHERE work_id = ? ORDER BY rowid', (work_id,))]

    def create(self, work_id, revision, provider, mode):
        if (type(revision) is not int or revision < 1 or not isinstance(provider, str)
                or not isinstance(mode, str)
                or (provider, mode) not in SUPPORTED_PROVIDER_MODES):
            raise ValueError('Unsupported design request')
        with self.store._connection() as db:
            db.execute('PRAGMA foreign_keys = ON')
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision, text FROM works WHERE id = ?', (work_id,)).fetchone()
            if row is None:
                raise KeyError(work_id)
            if row[0] != revision:
                raise ConflictError('Request does not match the current work revision')
            if not row[1].strip() and not db.execute('SELECT 1 FROM files WHERE work_id = ?', (work_id,)).fetchone():
                raise ValueError('Work description or material is required')
            existing = db.execute('''SELECT payload FROM design_requests
                WHERE work_id = ? AND revision = ? AND provider = ? AND mode = ?''',
                (work_id, revision, provider, mode)).fetchone()
            if existing:
                return json.loads(existing[0])
            path_label = {
                ('claude', 'api'): 'Claude API',
                ('codex', 'subscription'): 'Codex 구독',
                ('codex', 'api'): 'Codex API',
            }[(provider, mode)]
            reason = 'design_engine_not_connected'
            message = (f'입력과 자료는 이 DeepTwin 인스턴스에 보관했습니다. 현재 개발본에는 '
                       f'{path_label}로 설계를 만드는 엔진이 아직 연결되지 않아 그래프를 생성하지 '
                       '않았습니다. 모델 호출이나 API 과금은 발생하지 않았습니다.')
            timestamp = datetime.now(timezone.utc).isoformat()
            request = dict(id=str(uuid4()), work_id=work_id, revision=revision, provider=provider,
                           mode=mode, status='blocked', reason=reason, message=message, created_at=timestamp)
            db.execute('INSERT INTO design_requests VALUES (?, ?, ?, ?, ?, ?)',
                       (request['id'], work_id, revision, provider, mode, json.dumps(request, ensure_ascii=False)))
            db.execute('INSERT INTO events(kind, work_id, created_at, metadata) VALUES (?, ?, ?, ?)',
                       ('design_request_blocked', work_id, timestamp, json.dumps({
                           'request_id': request['id'], 'revision': revision, 'provider': provider,
                           'mode': mode, 'reason': reason})))
        return request
