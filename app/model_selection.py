"""Immutable work-scoped defaults, overrides, and effective run choices."""

import json
import re

from .storage import ConflictError

CHOICE_KEYS = {'provider', 'mode', 'model', 'effort', 'catalog_id'}
CHOICE_OPTIONAL_KEYS = {'thinking'}
_SCOPE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z')


class ModelSelectionError(ValueError):
    pass


class ModelSelectionConflict(ConflictError):
    pass


class ModelSelection:
    def __init__(self, store, catalog):
        self.store, self.catalog = store, catalog
        with store._connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS work_model_selections (
                    work_id TEXT NOT NULL REFERENCES works(id),
                    version INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(work_id, version));
                CREATE TABLE IF NOT EXISTS work_model_policies (
                    work_id TEXT NOT NULL REFERENCES works(id),
                    version INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(work_id, version));
                CREATE TABLE IF NOT EXISTS run_model_choices (
                    run_id TEXT NOT NULL, purpose TEXT NOT NULL, agent_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, purpose, agent_id));
            ''')

    @staticmethod
    def _version(version):
        if type(version) is not int or version < 0:
            raise ModelSelectionError('저장할 모델 설정 버전을 확인해 주세요.')

    def _validate(self, selection, *, required_capabilities=()):
        if (not isinstance(selection, dict)
                or set(selection) not in (CHOICE_KEYS, CHOICE_KEYS | CHOICE_OPTIONAL_KEYS)):
            raise ModelSelectionError('사용할 모델과 추론 수준을 선택해 주세요.')
        try:
            if required_capabilities:
                return self.catalog.validate_choice(
                    selection, required_capabilities=tuple(required_capabilities)
                )
            return self.catalog.validate_choice(selection)
        except ValueError:
            raise ModelSelectionError('현재 모델 목록에서 이 설정을 확인하지 못했습니다. 목록을 다시 조회하고 선택해 주세요.') from None

    def _get(self, db, work_id, version=None):
        if db.execute('SELECT 1 FROM works WHERE id = ?', (work_id,)).fetchone() is None:
            raise KeyError(work_id)
        if version is None:
            row = db.execute('SELECT payload FROM work_model_selections WHERE work_id = ? ORDER BY version DESC LIMIT 1',
                             (work_id,)).fetchone()
        else:
            self._version(version)
            row = db.execute('SELECT payload FROM work_model_selections WHERE work_id = ? AND version = ?',
                             (work_id, version)).fetchone()
        if row:
            return json.loads(row['payload'])
        if version not in {None, 0}:
            raise KeyError((work_id, version))
        return {'version': 0, 'selection': None}

    def get(self, work_id, version=None):
        with self.store._connection() as db:
            return self._get(db, work_id, version)

    def save(self, work_id, expected_version, selection):
        self._version(expected_version)
        normalized = self._validate(selection)
        with self.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._get(db, work_id)
            if current['version'] != expected_version:
                raise ModelSelectionConflict('다른 화면에서 모델 설정이 바뀌었습니다. 저장된 설정을 다시 확인해 주세요.')
            if current['selection'] == normalized:
                return current
            record = {'version': expected_version + 1, 'selection': normalized}
            db.execute('INSERT INTO work_model_selections VALUES (?, ?, ?)',
                       (work_id, record['version'], json.dumps(record, ensure_ascii=False)))
            event = {'version': record['version'],
                     **{key: normalized[key] for key in CHOICE_KEYS}}
            if 'thinking' in normalized:
                event['thinking'] = normalized['thinking']
            self.store._event(db, 'model_selection_saved', work_id, event)
            return record

    def for_request(self, db, work_id, version):
        self._version(version)
        current = self._get(db, work_id)
        if version < 1 or current['selection'] is None:
            raise ModelSelectionError('업무를 이해할 모델을 먼저 선택하고 저장해 주세요.')
        if current['version'] != version:
            raise ModelSelectionConflict('모델 설정이 바뀌었습니다. 현재 선택을 확인한 뒤 요청해 주세요.')
        choice = {key: current['selection'][key] for key in CHOICE_KEYS}
        for key in CHOICE_OPTIONAL_KEYS:
            if key in current['selection']:
                choice[key] = current['selection'][key]
        validated = self._validate(choice)
        return {**current, 'selection': validated}

    @staticmethod
    def _scope(value, label):
        if not isinstance(value, str) or not _SCOPE_ID.fullmatch(value):
            raise ModelSelectionError(f'{label} 식별자를 확인해 주세요.')
        return value

    @classmethod
    def _capabilities(cls, values):
        if not isinstance(values, (tuple, list)) or len(values) > 100:
            raise ModelSelectionError('필요한 모델 능력 목록을 확인해 주세요.')
        normalized = [cls._scope(value, '모델 능력') for value in values]
        if len(set(normalized)) != len(normalized):
            raise ModelSelectionError('필요한 모델 능력이 중복되었습니다.')
        return tuple(sorted(normalized))

    def _get_policy(self, db, work_id, version=None):
        if db.execute('SELECT 1 FROM works WHERE id = ?', (work_id,)).fetchone() is None:
            raise KeyError(work_id)
        if version is None:
            row = db.execute('''SELECT payload FROM work_model_policies
                WHERE work_id = ? ORDER BY version DESC LIMIT 1''', (work_id,)).fetchone()
        else:
            self._version(version)
            row = db.execute('''SELECT payload FROM work_model_policies
                WHERE work_id = ? AND version = ?''', (work_id, version)).fetchone()
        if row is not None:
            return json.loads(row['payload'])
        if version not in {None, 0}:
            raise KeyError((work_id, version))
        return {
            'version': 0,
            'default': None,
            'purpose_overrides': {},
            'agent_overrides': {},
        }

    def get_policy(self, work_id, version=None):
        with self.store._connection() as db:
            return self._get_policy(db, work_id, version)

    def _validated_overrides(self, value, label):
        if not isinstance(value, dict) or len(value) > 200:
            raise ModelSelectionError(f'{label} 모델 설정을 확인해 주세요.')
        normalized = {}
        for scope, selection in value.items():
            scope = self._scope(scope, label)
            normalized[scope] = self._validate(selection)
        return normalized

    def save_policy(self, work_id, expected_version, *, default,
                    purpose_overrides, agent_overrides):
        """CAS-save a complete work policy; partial merges are not accepted."""
        self._version(expected_version)
        normalized_default = None if default is None else self._validate(default)
        normalized_purposes = self._validated_overrides(purpose_overrides, '목적')
        normalized_agents = self._validated_overrides(agent_overrides, '에이전트')
        record = {
            'version': expected_version + 1,
            'default': normalized_default,
            'purpose_overrides': normalized_purposes,
            'agent_overrides': normalized_agents,
        }
        with self.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._get_policy(db, work_id)
            if current['version'] != expected_version:
                raise ModelSelectionConflict(
                    '다른 화면에서 모델 정책이 바뀌었습니다. 저장된 설정을 다시 확인해 주세요.'
                )
            comparable = {key: record[key] for key in
                          ('default', 'purpose_overrides', 'agent_overrides')}
            if all(current[key] == comparable[key] for key in comparable):
                return current
            db.execute('INSERT INTO work_model_policies VALUES (?, ?, ?)',
                       (work_id, record['version'], json.dumps(record, ensure_ascii=False)))
            self.store._event(db, 'model_policy_saved', work_id, {
                'version': record['version'],
                'default_provider': None if normalized_default is None else normalized_default['provider'],
                'purpose_override_count': len(normalized_purposes),
                'agent_override_count': len(normalized_agents),
            })
        return record

    def _resolve_record(self, policy, *, purpose, agent_id, required_capabilities=()):
        purpose = self._scope(purpose, '목적')
        agent_id = self._scope(agent_id, '에이전트')
        required_capabilities = self._capabilities(required_capabilities)
        if agent_id in policy['agent_overrides']:
            source, selected = 'agent', policy['agent_overrides'][agent_id]
        elif purpose in policy['purpose_overrides']:
            source, selected = 'purpose', policy['purpose_overrides'][purpose]
        else:
            source, selected = 'default', policy['default']
        if selected is None:
            raise ModelSelectionError('이 실행 목적에 사용할 기본 모델을 먼저 선택해 주세요.')
        choice = {key: selected[key] for key in CHOICE_KEYS}
        for key in CHOICE_OPTIONAL_KEYS:
            if key in selected:
                choice[key] = selected[key]
        validated = self._validate(choice, required_capabilities=required_capabilities)
        return {
            'policy_version': policy['version'],
            'purpose': purpose,
            'agent_id': agent_id,
            'source': source,
            'selection': validated,
        }

    def resolve(self, work_id, version, *, purpose, agent_id, required_capabilities=()):
        self._version(version)
        if version < 1:
            raise ModelSelectionError('업무 모델 정책을 먼저 저장해 주세요.')
        with self.store._connection() as db:
            current = self._get_policy(db, work_id)
        if current['version'] != version:
            raise ModelSelectionConflict('모델 정책이 바뀌었습니다. 현재 설정을 다시 확인해 주세요.')
        return self._resolve_record(
            current, purpose=purpose, agent_id=agent_id,
            required_capabilities=required_capabilities,
        )

    def freeze_for_run(self, run_id, work_id, policy_version, *, purpose, agent_id,
                       required_capabilities=()):
        """Record the exact effective choice once for one run/agent/purpose."""
        run_id = self._scope(run_id, '실행')
        purpose = self._scope(purpose, '목적')
        agent_id = self._scope(agent_id, '에이전트')
        required_capabilities = self._capabilities(required_capabilities)
        self._version(policy_version)
        with self.store._connection() as db:
            existing = db.execute('''SELECT payload FROM run_model_choices
                WHERE run_id = ? AND purpose = ? AND agent_id = ?''',
                                  (run_id, purpose, agent_id)).fetchone()
        if existing is not None:
            frozen = json.loads(existing['payload'])
            if (frozen['work_id'] != work_id
                    or frozen['policy_version'] != policy_version
                    or frozen.get('required_capabilities') != list(required_capabilities)):
                raise ModelSelectionConflict('이미 다른 모델 정책으로 동결된 실행입니다.')
            return frozen
        resolved = self.resolve(
            work_id, policy_version, purpose=purpose, agent_id=agent_id,
            required_capabilities=required_capabilities,
        )
        frozen = {
            'run_id': run_id, 'work_id': work_id,
            'required_capabilities': list(required_capabilities), **resolved,
        }
        with self.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current = self._get_policy(db, work_id)
            if current['version'] != policy_version:
                raise ModelSelectionConflict('동결 전에 모델 정책이 바뀌었습니다.')
            try:
                self.catalog.assert_validation_fence(db, resolved['selection'])
            except ValueError:
                raise ModelSelectionConflict(
                    '동결 전에 모델 목록이나 연결 상태가 바뀌었습니다.'
                ) from None
            existing = db.execute('''SELECT payload FROM run_model_choices
                WHERE run_id = ? AND purpose = ? AND agent_id = ?''',
                                  (run_id, purpose, agent_id)).fetchone()
            if existing is not None:
                observed = json.loads(existing['payload'])
                if observed != frozen:
                    raise ModelSelectionConflict('동시에 다른 모델 선택이 동결되었습니다.')
                return observed
            db.execute('INSERT INTO run_model_choices VALUES (?, ?, ?, ?)',
                       (run_id, purpose, agent_id, json.dumps(frozen, ensure_ascii=False)))
            self.store._event(db, 'run_model_choice_frozen', work_id, {
                'run_id': run_id, 'purpose': purpose, 'agent_id': agent_id,
                'policy_version': policy_version, 'source': resolved['source'],
                'provider': resolved['selection']['provider'],
                'mode': resolved['selection']['mode'],
                'catalog_id': resolved['selection']['catalog_id'],
                'model': resolved['selection']['model'],
            })
        return frozen

    def get_run_choice(self, run_id, *, purpose, agent_id):
        run_id = self._scope(run_id, '실행')
        purpose = self._scope(purpose, '목적')
        agent_id = self._scope(agent_id, '에이전트')
        with self.store._connection() as db:
            row = db.execute('''SELECT payload FROM run_model_choices
                WHERE run_id = ? AND purpose = ? AND agent_id = ?''',
                             (run_id, purpose, agent_id)).fetchone()
        if row is None:
            raise KeyError((run_id, purpose, agent_id))
        return json.loads(row['payload'])
