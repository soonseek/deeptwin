"""Provider-neutral immutable model catalogs fetched only by an explicit action.

The catalog service intentionally contains no account model names. Codex
subscription rows come from app-server ``model/list``; Claude and optional
Codex API rows come from their separately bound adapters. A persisted row is
history, while validation also requires a current catalog for the same opaque
connection binding.
"""

import hashlib
import hmac
import json
import re
import threading
import time
from copy import deepcopy
from datetime import UTC, datetime

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}\Z")
_MODALITIES = {'text', 'image'}
_MODES = {('claude', 'api'), ('codex', 'subscription'), ('codex', 'api')}
_MESSAGES = {
    ('claude', 'api'): {
        'unqueried': 'API 연결 후 새로고침을 눌러 현재 Claude 모델 목록을 확인하세요.',
        'ready': 'Claude API가 제공한 현재 모델 목록입니다. 실행 준비와 사용량 과금은 별도입니다.',
        'unavailable': 'Claude API 키 연결이 필요합니다.',
        'error': 'Claude API 모델 목록을 확인하지 못했습니다. 기존 선택을 실행에 사용하지 않습니다.',
    },
    ('codex', 'subscription'): {
        'unqueried': '새로고침을 눌러 현재 Codex 모델 목록을 확인하세요.',
        'ready': 'Codex가 제공한 현재 모델 목록입니다. 실행 가능 여부와 과금은 별도입니다.',
        'unavailable': 'ChatGPT 구독 연결을 확인해야 Codex 모델 목록을 읽을 수 있습니다. API로 전환하지 않았습니다.',
        'error': 'Codex 모델 목록을 확인하지 못했습니다. 기존 선택을 실행에 사용하지 않습니다.',
    },
    ('codex', 'api'): {
        'unqueried': '별도 API 연결 후 새로고침을 눌러 현재 Codex API 모델 목록을 확인하세요.',
        'ready': 'OpenAI API가 제공한 현재 모델 목록입니다. 실행 적격성과 사용량 과금은 별도입니다.',
        'unavailable': '별도의 Codex API 연결이 필요합니다. ChatGPT 구독 인증을 전환하지 않습니다.',
        'error': 'Codex API 모델 목록을 확인하지 못했습니다. 기존 선택을 실행에 사용하지 않습니다.',
    },
}


class _StaleRefresh(RuntimeError):
    pass


def _canonical(value):
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError('Invalid catalog value') from exc


def _digest(value):
    return 'sha256:' + hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _short_text(value, limit=200):
    return isinstance(value, str) and 0 < len(value) <= limit


def _mode(provider, mode=None):
    selected = mode or ('api' if provider == 'claude' else 'subscription')
    if (provider, selected) not in _MODES:
        raise ValueError('Unsupported provider mode')
    return selected


def _empty(provider, mode, status):
    return {
        'provider': provider,
        'mode': mode,
        'auth_mode': 'chatgpt' if mode == 'subscription' else 'api_key',
        'billing': 'subscription' if mode == 'subscription' else 'api',
        'status': status,
        'message': _MESSAGES[(provider, mode)][status],
        'catalog_id': None,
        'source_catalog_id': None,
        'fetched_at': None,
        'fetched_at_ms': None,
        'max_age_ms': None,
        'binding_id': None,
        'workspace_binding': None,
        'request_epoch': None,
        'source_request_epoch': None,
        'credential_generation': None,
        'binding_generation': None,
        'capability_claims_digest': None,
        'models': [],
        'execution_ready': False,
    }


def _claim_supported(value):
    return value is True or (isinstance(value, dict) and value.get('supported') is True)


def _validate_claim_shape(value, *, depth=0):
    """Validate only the capability grammar we rely on, preserving unknown claims."""
    if depth > 12:
        raise ValueError('Capability claims are too deeply nested')
    if isinstance(value, dict):
        if 'supported' in value and not isinstance(value['supported'], bool):
            raise ValueError('Invalid capability support claim')
        if 'types' in value and not isinstance(value['types'], dict):
            raise ValueError('Invalid capability type claims')
        for name, item in value.items():
            if not _short_text(name, 200):
                raise ValueError('Invalid capability claim name')
            _validate_claim_shape(item, depth=depth + 1)
    elif isinstance(value, (list, tuple)):
        if len(value) > 500:
            raise ValueError('Too many capability claim values')
        for item in value:
            _validate_claim_shape(item, depth=depth + 1)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError('Invalid capability claim value')


def _normalized_model(*, model, display_name, default_effort, efforts, modalities,
                      is_default, raw_claims, billing):
    if not _short_text(model) or not _short_text(display_name):
        raise ValueError('Invalid model entry')
    if not isinstance(raw_claims, (dict, type(None))):
        raise ValueError('Invalid capability claims')  # noqa: TRY004
    encoded_claims = _canonical(raw_claims)
    if len(encoded_claims.encode('utf-8')) > 64 * 1024:
        raise ValueError('Capability claims are too large')
    if not isinstance(efforts, list) or len(efforts) > 20:
        raise ValueError('Invalid reasoning efforts')
    normalized_efforts, seen = [], set()
    for item in efforts:
        if not isinstance(item, dict):
            raise ValueError('Invalid reasoning effort')  # noqa: TRY004
        value, label = item.get('value'), item.get('label')
        if not _short_text(value, 80) or value in seen or not _short_text(label, 500):
            raise ValueError('Invalid reasoning effort')
        seen.add(value)
        normalized_efforts.append({'value': value, 'label': label})
    if default_effort is not None and default_effort not in seen:
        raise ValueError('Invalid default reasoning effort')
    if (not isinstance(modalities, list) or len(modalities) > 4
            or any(item not in _MODALITIES for item in modalities)
            or len(set(modalities)) != len(modalities)):
        raise ValueError('Invalid model modalities')
    capabilities = {f'{item}_input': True for item in modalities}
    for item in _MODALITIES - set(modalities):
        if raw_claims is not None and 'inputModalities' in raw_claims:
            capabilities[f'{item}_input'] = False
    if normalized_efforts:
        capabilities['reasoning_efforts'] = [item['value'] for item in normalized_efforts]
    claim_digest = _digest(raw_claims)
    return {
        'model': model,
        'display_name': display_name,
        'default_reasoning_effort': default_effort,
        'reasoning_efforts': normalized_efforts,
        'input_modalities': list(modalities),
        'is_default': is_default,
        'billing': billing,
        'capabilities': capabilities,
        'raw_capability_claims': deepcopy(raw_claims),
        'capability_claims_digest': claim_digest,
    }


def _normalize_subscription_pages(pages):
    if not isinstance(pages, list) or not pages or len(pages) > 20:
        raise ValueError('Invalid model catalog pages')
    models, seen_models, seen_cursors, default_count = [], set(), set(), 0
    for index, page in enumerate(pages):
        if not isinstance(page, dict) or not isinstance(page.get('data'), list):
            raise ValueError('Invalid model catalog page')  # noqa: TRY004
        cursor = page.get('nextCursor')
        if cursor is not None and (not _short_text(cursor, 2048) or cursor in seen_cursors):
            raise ValueError('Invalid model catalog cursor')
        if cursor is not None:
            seen_cursors.add(cursor)
        if (index < len(pages) - 1 and cursor is None) or (index == len(pages) - 1 and cursor is not None):
            raise ValueError('Incomplete model catalog pagination')
        for raw in page['data']:
            if not isinstance(raw, dict) or raw.get('hidden') is not False:
                raise ValueError('Invalid model entry')
            model = raw.get('model')
            if model in seen_models or not isinstance(raw.get('isDefault'), bool):
                raise ValueError('Invalid model entry')
            source_efforts = raw.get('supportedReasoningEfforts')
            if not isinstance(source_efforts, list) or not source_efforts:
                raise ValueError('Invalid reasoning efforts')
            efforts = []
            for effort in source_efforts:
                if not isinstance(effort, dict):
                    raise ValueError('Invalid reasoning effort')  # noqa: TRY004
                efforts.append({'value': effort.get('reasoningEffort'), 'label': effort.get('description')})
            modalities = raw.get('inputModalities')
            if modalities is None:
                modalities = []
            raw_claims = {
                key: deepcopy(value) for key, value in raw.items()
                if key not in {'id', 'model', 'displayName', 'hidden', 'isDefault'}
            }
            seen_models.add(model)
            default_count += int(raw['isDefault'])
            if default_count > 1:
                raise ValueError('Model catalog has multiple defaults')
            models.append(_normalized_model(
                model=model, display_name=raw.get('displayName'),
                default_effort=raw.get('defaultReasoningEffort'), efforts=efforts,
                modalities=modalities, is_default=raw['isDefault'],
                raw_claims=raw_claims, billing='subscription',
            ))
            if len(models) > 500:
                raise ValueError('Model catalog is too large')
    if not models:
        raise ValueError('Empty model catalog')
    return models


# Compatibility seam retained for fault-injection tests and existing callers.
_normalize_pages = _normalize_subscription_pages


def _normalize_claude(snapshot):
    source_models = getattr(snapshot, 'models', None)
    if (not isinstance(source_models, (tuple, list)) or not source_models
            or len(source_models) > 500):
        raise ValueError('Invalid Claude model collection')
    models, seen_models = [], set()
    for raw in source_models:
        claims = getattr(raw, 'capabilities', None)
        if claims is not None and not isinstance(claims, dict):
            raise ValueError('Invalid capability claims')
        _validate_claim_shape(claims)
        modalities = []
        for modality in ('text', 'image'):
            if _claim_supported(None if claims is None else claims.get(f'{modality}_input')):
                modalities.append(modality)
        effort_claim = None if claims is None else claims.get('effort')
        efforts = []
        if isinstance(effort_claim, dict) and effort_claim.get('supported') is True:
            for name, value in effort_claim.items():
                if name != 'supported' and _claim_supported(value):
                    efforts.append({'value': name, 'label': name})
        model = _normalized_model(
            model=getattr(raw, 'id', None), display_name=getattr(raw, 'display_name', None),
            default_effort=efforts[0]['value'] if efforts else None, efforts=efforts,
            modalities=modalities, is_default=False, raw_claims=claims, billing='api',
        )
        if model['model'] in seen_models:
            raise ValueError('Duplicate model entry')
        seen_models.add(model['model'])
        if isinstance(claims, dict):
            for name, claim in claims.items():
                if _SAFE_ID.fullmatch(name) and name != 'effort':
                    if _claim_supported(claim):
                        model['capabilities'][name] = True
                    elif claim is False or (isinstance(claim, dict) and claim.get('supported') is False):
                        model['capabilities'][name] = False
        models.append(model)
    if not models:
        raise ValueError('Empty model catalog')
    return models


def _normalize_codex_api(snapshot):
    source_models = getattr(snapshot, 'models', None)
    if (not isinstance(source_models, (tuple, list)) or not source_models
            or len(source_models) > 500):
        raise ValueError('Invalid Codex API model collection')
    models, seen_models = [], set()
    for raw in source_models:
        capabilities = getattr(raw, 'capabilities', ())
        if (not isinstance(capabilities, (tuple, list)) or len(capabilities) > 100
                or any(not isinstance(item, str) or not _SAFE_ID.fullmatch(item)
                       for item in capabilities)
                or len(set(capabilities)) != len(capabilities)
                or not isinstance(getattr(raw, 'execution_eligible', False), bool)):
            raise ValueError('Invalid Codex API capability claims')
        claims = {
            'capabilities': list(capabilities),
            'execution_eligible': getattr(raw, 'execution_eligible', False),
        }
        model = _normalized_model(
            model=getattr(raw, 'model_id', None), display_name=getattr(raw, 'model_id', None),
            default_effort=None, efforts=[], modalities=[], is_default=False,
            raw_claims=claims, billing='api',
        )
        if model['model'] in seen_models:
            raise ValueError('Duplicate model entry')
        seen_models.add(model['model'])
        models.append(model)
    if not models:
        raise ValueError('Empty model catalog')
    return models


class ModelCatalog:
    def __init__(self, store, codex, *, api_sources=None, clock_ms=None):
        self.store = store
        self.codex = codex
        self._api_sources = dict(api_sources or {})
        self._connection_authority = None
        self._api_source_resolver = None
        if any(key not in {('claude', 'api'), ('codex', 'api')}
               or not isinstance(value, tuple) or len(value) != 2
               for key, value in self._api_sources.items()):
            raise ValueError('Invalid API catalog source')
        self._refresh_lock = threading.Lock()
        self._clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        with store._connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS model_catalogs (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, fetched_at TEXT NOT NULL,
                    account_binding TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS model_catalog_state (
                    provider TEXT PRIMARY KEY, status TEXT NOT NULL,
                    message TEXT NOT NULL, catalog_id TEXT);
                CREATE TABLE IF NOT EXISTS model_catalog_account_state (
                    provider TEXT PRIMARY KEY, binding TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS model_catalogs_v2 (
                    id TEXT PRIMARY KEY, provider TEXT NOT NULL, mode TEXT NOT NULL,
                    fetched_at TEXT NOT NULL, binding_id TEXT NOT NULL,
                    workspace_binding TEXT, request_epoch INTEGER NOT NULL,
                    capability_digest TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS model_catalog_state_v2 (
                    provider TEXT NOT NULL, mode TEXT NOT NULL, status TEXT NOT NULL,
                    message TEXT NOT NULL, catalog_id TEXT,
                    PRIMARY KEY(provider, mode));
                CREATE TABLE IF NOT EXISTS model_catalog_epochs (
                    provider TEXT NOT NULL, mode TEXT NOT NULL, binding_id TEXT NOT NULL,
                    epoch INTEGER NOT NULL, PRIMARY KEY(provider, mode, binding_id));
            ''')

    def bind_connection_authority(self, authority):
        """Bind a local durable API-connection fence without provider or secret I/O."""
        if not callable(authority):
            raise TypeError('Model catalog connection authority must be callable')
        self._connection_authority = authority

    def bind_api_source_resolver(self, resolver):
        """Bind the durable per-process adapter/binding resolver."""
        if not callable(resolver):
            raise TypeError('Model catalog API source resolver must be callable')
        self._api_source_resolver = resolver

    def _source(self, provider, mode, *, db=None):
        if (provider, mode) == ('codex', 'subscription'):
            return self.codex, None
        if self._api_source_resolver is not None:
            return self._api_source_resolver(provider, mode, db=db)
        return self._api_sources.get((provider, mode), (None, None))

    def replace_api_source(self, provider, mode, source):
        """Replace one explicit API connection without retaining its old authority.

        Credential mutation lives outside this service.  This boundary accepts only
        an already-constructed adapter/binding pair, performs no provider or Keychain
        I/O, and makes every prior current-catalog pointer visibly stale.
        """
        key = (provider, mode)
        if key not in {('claude', 'api'), ('codex', 'api')}:
            raise ValueError('Only an API catalog source can be replaced')
        if source is not None:
            if not isinstance(source, tuple) or len(source) != 2:
                raise ValueError('Invalid API catalog source')
            adapter, binding = source
            if (not callable(getattr(adapter, 'fetch_catalog', None))
                    or not callable(getattr(adapter, 'connection_state', None))
                    or not _short_text(getattr(binding, 'binding_id', None), 300)):
                raise ValueError('Invalid API catalog source')
        status = 'unavailable' if source is None else 'unqueried'
        with self._refresh_lock:
            message = _MESSAGES[key][status]
            with self.store._connection() as db:
                db.execute('BEGIN IMMEDIATE')
                binding_id = (
                    None if source is None else source[1].binding_id
                )
                if (self._connection_authority is not None
                        and not self._connection_authority(
                            provider, mode, binding_id, db=db
                        )):
                    raise ValueError('Stale API catalog source publication')
                previous = self._api_sources.get(key)
                same_source = (
                    (source is None and previous is None)
                    or (
                        source is not None
                        and previous is not None
                        and previous[0] is source[0]
                        and hmac.compare_digest(
                            previous[1].binding_id, source[1].binding_id
                        )
                    )
                )
                state = db.execute('''SELECT status,message,catalog_id
                    FROM model_catalog_state_v2 WHERE provider=? AND mode=?''',
                                   (provider, mode)).fetchone()
                state_current = (
                    state is not None
                    and state['status'] == status
                    and state['message'] == message
                    and state['catalog_id'] is None
                )
                if not (same_source and state_current):
                    db.execute('''INSERT INTO model_catalog_state_v2 VALUES (?, ?, ?, ?, NULL)
                        ON CONFLICT(provider, mode) DO UPDATE SET status = excluded.status,
                            message = excluded.message, catalog_id = NULL''',
                               (provider, mode, status, message))
                    self.store._event(db, 'model_catalog_source_changed', None, {
                        'provider': provider,
                        'mode': mode,
                        'configured': source is not None,
                    })
                    observed = db.execute('''SELECT status,message,catalog_id
                        FROM model_catalog_state_v2 WHERE provider=? AND mode=?''',
                                          (provider, mode)).fetchone()
                    if (observed is None or observed['status'] != status
                            or observed['message'] != message
                            or observed['catalog_id'] is not None):
                        raise ValueError('API catalog source state changed before commit')
                if (self._connection_authority is not None
                        and not self._connection_authority(
                            provider, mode, binding_id, db=db
                        )):
                    raise ValueError('API catalog authority changed before commit')
            # The database authority fence commits before this in-memory cache is
            # changed.  A later provider mutation must therefore publish after us,
            # while an older publication is rejected by the binding check above.
            if source is None:
                self._api_sources.pop(key, None)
            else:
                self._api_sources[key] = source
        return self.snapshot(provider, mode)

    @staticmethod
    def _workspace_binding(binding):
        if binding is None:
            return None
        values = {
            name: getattr(binding, name, None)
            for name in ('workspace_id', 'project_id', 'organization_id')
            if getattr(binding, name, None) is not None
        }
        return None if not values else 'workspace-' + _digest(values).split(':', 1)[1]

    @staticmethod
    def _verify_payload(value):
        if not isinstance(value, dict) or not _short_text(value.get('catalog_id'), 300):
            raise ValueError('Model catalog integrity check failed')
        models = value.get('models')
        if not isinstance(models, list) or not models:
            raise ValueError('Model catalog integrity check failed')
        claims = []
        for model in models:
            if not isinstance(model, dict):
                raise ValueError('Model catalog integrity check failed')  # noqa: TRY004
            expected = _digest(model.get('raw_capability_claims'))
            if not hmac.compare_digest(str(model.get('capability_claims_digest')), expected):
                raise ValueError('Model catalog integrity check failed')
            claims.append({'model': model.get('model'), 'claims': model.get('raw_capability_claims')})
        capability_digest = _digest(claims)
        if not hmac.compare_digest(str(value.get('capability_claims_digest')), capability_digest):
            raise ValueError('Model catalog integrity check failed')
        unsigned = {key: item for key, item in value.items() if key != 'catalog_id'}
        catalog_id = 'catalog-' + _digest(unsigned).split(':', 1)[1]
        if not hmac.compare_digest(value['catalog_id'], catalog_id):
            raise ValueError('Model catalog integrity check failed')
        return value

    @classmethod
    def _stored_catalog(cls, row, provider, mode):
        """Bind a valid payload to every authoritative column of its storage row."""
        if row is None:
            raise ValueError('Model catalog row is missing')
        value = cls._verify_payload(json.loads(row['payload']))
        expected = {
            'id': value.get('catalog_id'),
            'provider': value.get('provider'),
            'mode': value.get('mode'),
            'fetched_at': value.get('fetched_at'),
            'binding_id': value.get('binding_id'),
            'workspace_binding': value.get('workspace_binding'),
            'request_epoch': value.get('request_epoch'),
            'capability_digest': value.get('capability_claims_digest'),
        }
        if (row['provider'] != provider or row['mode'] != mode
                or any(row[column] != payload_value
                       for column, payload_value in expected.items())):
            raise ValueError('Model catalog storage row does not match its payload')
        return value

    def _current_authority(self, provider, mode, db=None):
        source, binding = self._source(provider, mode, db=db)
        if source is None:
            return None, None
        if mode == 'api':
            state_reader = getattr(source, 'connection_state', None)
            if not callable(state_reader) or state_reader(binding) != 'catalog_current':
                return None, None
            value = getattr(binding, 'binding_id', None)
            if not _short_text(value, 300):
                return None, None
            if (self._connection_authority is not None
                    and self._connection_authority(
                        provider, mode, value, db=db
                    ) is not True):
                return None, None
            return value, self._workspace_binding(binding)
        if db is not None:
            row = db.execute('SELECT binding FROM model_catalog_account_state WHERE provider = ?',
                             ('codex',)).fetchone()
            return (None if row is None else row['binding']), None
        with self.store._connection() as connection:
            row = connection.execute(
                'SELECT binding FROM model_catalog_account_state WHERE provider = ?', ('codex',)
            ).fetchone()
        return (None if row is None else row['binding']), None

    def _current_binding(self, provider, mode, db=None):
        return self._current_authority(provider, mode, db=db)[0]

    def _remember_status(self, provider, mode, status):
        message = _MESSAGES[(provider, mode)][status]
        with self.store._connection() as db:
            db.execute('''INSERT INTO model_catalog_state_v2 VALUES (?, ?, ?, ?, NULL)
                ON CONFLICT(provider, mode) DO UPDATE SET status = excluded.status,
                    message = excluded.message, catalog_id = NULL''',
                       (provider, mode, status, message))
            if (provider, mode) == ('codex', 'subscription'):
                db.execute('''INSERT INTO model_catalog_state VALUES (?, ?, ?, NULL)
                    ON CONFLICT(provider) DO UPDATE SET status = excluded.status,
                        message = excluded.message, catalog_id = NULL''',
                           ('codex', status, message))
            self.store._event(db, 'model_catalog_refresh_failed', None, {
                'provider': provider, 'mode': mode, 'status': status,
            })

    def snapshot(self, provider, mode=None):
        mode = _mode(provider, mode)
        source, _ = self._source(provider, mode)
        with self.store._connection() as db:
            state = db.execute('''SELECT * FROM model_catalog_state_v2
                WHERE provider = ? AND mode = ?''', (provider, mode)).fetchone()
            row = None if state is None or state['status'] != 'ready' else db.execute('''
                SELECT c.* FROM model_catalogs_v2 c
                JOIN model_catalog_epochs e ON e.provider = c.provider
                    AND e.mode = c.mode AND e.binding_id = c.binding_id
                    AND e.epoch = c.request_epoch
                WHERE c.id = ?''', (state['catalog_id'],)).fetchone()
        if state is None:
            return _empty(provider, mode, 'unqueried' if source is not None else 'unavailable')
        if row is None:
            status = 'error' if state['status'] == 'ready' else state['status']
            return _empty(provider, mode, status)
        try:
            catalog = self._stored_catalog(row, provider, mode)
            if mode == 'api':
                current_binding, current_workspace = self._current_authority(
                    provider, mode
                )
                if (current_binding != catalog['binding_id']
                        or current_workspace != catalog['workspace_binding']):
                    return _empty(provider, mode, 'error')
            return deepcopy(catalog)
        except (ValueError, TypeError, json.JSONDecodeError):
            return _empty(provider, mode, 'error')

    def refresh(self, provider, mode=None):
        mode = _mode(provider, mode)
        with self._refresh_lock:
            try:
                return self._refresh(provider, mode)
            except _StaleRefresh:
                return _empty(provider, mode, 'error')
            except PermissionError:
                self._remember_status(provider, mode, 'unavailable')
                return _empty(provider, mode, 'unavailable')
            # Provider adapters are injected boundaries. Any unexpected adapter
            # failure must fail closed without exposing its detail to the UI.
            except Exception:  # noqa: BLE001
                self._remember_status(provider, mode, 'error')
                return _empty(provider, mode, 'error')

    def _next_epoch(self, db, provider, mode, binding_id, claimed=None):
        row = db.execute('''SELECT epoch FROM model_catalog_epochs
            WHERE provider = ? AND mode = ? AND binding_id = ?''',
                         (provider, mode, binding_id)).fetchone()
        previous = 0 if row is None else row['epoch']
        if claimed is not None and (type(claimed) is not int or claimed < 1):
            raise ValueError('Invalid catalog request epoch')
        epoch = previous + 1
        db.execute('''INSERT INTO model_catalog_epochs VALUES (?, ?, ?, ?)
            ON CONFLICT(provider, mode, binding_id) DO UPDATE SET epoch = excluded.epoch''',
                   (provider, mode, binding_id, epoch))
        return epoch

    def _assert_fresh(self, catalog):
        """Reject an API snapshot after its adapter-declared validity window."""
        if catalog.get('mode') != 'api':
            return
        fetched_at_ms, max_age_ms = catalog.get('fetched_at_ms'), catalog.get('max_age_ms')
        now = self._clock_ms()
        if (type(fetched_at_ms) is not int or fetched_at_ms < 0
                or type(max_age_ms) is not int or not 0 < max_age_ms <= 24 * 60 * 60 * 1000
                or type(now) is not int or now < fetched_at_ms
                or now > fetched_at_ms + max_age_ms):
            raise ValueError('Model catalog is stale or its validity is unknown')

    def _refresh(self, provider, mode):
        source, binding = self._source(provider, mode)
        if source is None:
            raise PermissionError('Provider connection required')
        source_catalog_id = None
        credential_generation = binding_generation = claimed_epoch = None
        fetched_at_ms = max_age_ms = None
        workspace_binding = self._workspace_binding(binding)
        if (provider, mode) == ('codex', 'subscription'):
            connection = source.snapshot()
            if not isinstance(connection, dict) or not isinstance(connection.get('connection'), dict):
                raise ValueError('Invalid provider connection snapshot')
            state, billing = connection['connection'].get('state'), connection.get('billing')
            if state == 'error':
                raise RuntimeError('Provider connection error')
            if state not in {'connected', 'unchecked'} or billing not in {'subscription', 'unknown'}:
                raise PermissionError('ChatGPT subscription required')
            raw = source.read_model_catalog()
            if (not isinstance(raw, dict) or not _short_text(raw.get('binding'), 300)
                    or not isinstance(raw.get('pages'), list)):
                raise ValueError('Invalid catalog source')
            binding_id = raw['binding']
            workspace_binding = raw.get('workspace_binding')
            if workspace_binding is not None and not _short_text(workspace_binding, 300):
                raise ValueError('Invalid workspace binding')
            if workspace_binding is not None:
                workspace_binding = 'workspace-' + _digest(workspace_binding).split(':', 1)[1]
            models = _normalize_pages(raw['pages'])
            fetched_at = datetime.now(UTC).isoformat()
        else:
            if not _short_text(getattr(binding, 'binding_id', None), 300):
                raise ValueError('Invalid API binding')
            raw = source.fetch_catalog(binding, explicit_action=True)
            raw_provider, raw_mode = getattr(raw, 'provider', None), getattr(raw, 'mode', None)
            if ((provider == 'codex' and (raw_provider, raw_mode) != (provider, mode))
                    or (provider == 'claude'
                        and (raw_provider not in {None, provider} or raw_mode not in {None, mode}))):
                raise ValueError('API catalog source identity mismatch')
            binding_id = getattr(raw, 'binding_id', None)
            if binding_id != binding.binding_id:
                raise _StaleRefresh('Provider binding changed during refresh')
            source_catalog_id = getattr(raw, 'catalog_id', None)
            if not _short_text(source_catalog_id, 300):
                raise ValueError('Invalid source catalog id')
            fetched_at_ms = getattr(raw, 'fetched_at_ms', None)
            if type(fetched_at_ms) is not int or fetched_at_ms < 0:
                raise ValueError('Invalid fetch time')
            max_age_ms = getattr(raw, 'max_age_ms', None)
            if (type(max_age_ms) is not int
                    or not 0 < max_age_ms <= 24 * 60 * 60 * 1000):
                raise ValueError('Invalid catalog validity window')
            fetched_at = datetime.fromtimestamp(fetched_at_ms / 1000, tz=UTC).isoformat()
            credential_generation = getattr(raw, 'credential_generation', None)
            binding_generation = getattr(raw, 'binding_generation', None)
            if type(credential_generation) is not int or credential_generation < 0:
                raise ValueError('Invalid credential generation')
            if type(binding_generation) is not int or binding_generation < 0:
                raise ValueError('Invalid binding generation')
            claimed_epoch = getattr(raw, 'request_epoch', None)
            if provider == 'claude' and claimed_epoch is None:
                raise ValueError('Claude catalog source epoch is missing')
            models = _normalize_claude(raw) if provider == 'claude' else _normalize_codex_api(raw)
        capability_digest = _digest([
            {'model': item['model'], 'claims': item['raw_capability_claims']}
            for item in models
        ])
        with self.store._connection() as db:
            db.execute('BEGIN IMMEDIATE')
            current_binding, current_workspace = self._current_authority(
                provider, mode, db=db,
            )
            if current_binding != binding_id:
                raise _StaleRefresh('Provider account changed during refresh')
            if mode == 'api' and current_workspace != workspace_binding:
                raise _StaleRefresh('Provider workspace changed during refresh')
            epoch = self._next_epoch(db, provider, mode, binding_id, claimed_epoch)
            unsigned = {
                'provider': provider, 'mode': mode,
                'auth_mode': 'chatgpt' if mode == 'subscription' else 'api_key',
                'billing': 'subscription' if mode == 'subscription' else 'api',
                'status': 'ready', 'message': _MESSAGES[(provider, mode)]['ready'],
                'source_catalog_id': source_catalog_id, 'fetched_at': fetched_at,
                'fetched_at_ms': fetched_at_ms, 'max_age_ms': max_age_ms,
                'binding_id': binding_id, 'workspace_binding': workspace_binding,
                'request_epoch': epoch,
                'source_request_epoch': claimed_epoch,
                'credential_generation': credential_generation,
                'binding_generation': binding_generation,
                'capability_claims_digest': capability_digest,
                'models': models, 'execution_ready': False,
            }
            catalog_id = 'catalog-' + _digest(unsigned).split(':', 1)[1]
            value = {'catalog_id': catalog_id, **unsigned}
            payload = _canonical(value)
            db.execute('''INSERT INTO model_catalogs_v2 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                       (catalog_id, provider, mode, fetched_at, binding_id, workspace_binding,
                        epoch, capability_digest, payload))
            db.execute('''INSERT INTO model_catalog_state_v2 VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(provider, mode) DO UPDATE SET status = excluded.status,
                    message = excluded.message, catalog_id = excluded.catalog_id''',
                       (provider, mode, 'ready', value['message'], catalog_id))
            if (provider, mode) == ('codex', 'subscription'):
                db.execute('INSERT INTO model_catalogs VALUES (?, ?, ?, ?, ?)',
                           (catalog_id, 'codex', fetched_at, binding_id, payload))
                db.execute('''INSERT INTO model_catalog_state VALUES (?, ?, ?, ?)
                    ON CONFLICT(provider) DO UPDATE SET status = excluded.status,
                        message = excluded.message, catalog_id = excluded.catalog_id''',
                           ('codex', 'ready', value['message'], catalog_id))
            self.store._event(db, 'model_catalog_refreshed', None, {
                'provider': provider, 'mode': mode, 'catalog_id': catalog_id,
                'model_count': len(models), 'binding_id': binding_id,
                'request_epoch': epoch, 'capability_claims_digest': capability_digest,
            })
            committed_binding, committed_workspace = self._current_authority(
                provider, mode, db=db,
            )
            if (committed_binding != binding_id
                    or committed_workspace != workspace_binding):
                raise _StaleRefresh('Provider authority changed before catalog commit')
            committed_state = db.execute('''SELECT status,message,catalog_id
                FROM model_catalog_state_v2 WHERE provider=? AND mode=?''',
                                         (provider, mode)).fetchone()
            if (committed_state is None
                    or committed_state['status'] != 'ready'
                    or committed_state['message'] != value['message']
                    or committed_state['catalog_id'] != catalog_id):
                raise _StaleRefresh('Catalog state changed before commit')
            self._stored_catalog(
                db.execute('SELECT * FROM model_catalogs_v2 WHERE id=?',
                           (catalog_id,)).fetchone(),
                provider,
                mode,
            )
        return deepcopy(value)

    def validate_choice(self, choice, *, required_capabilities=()):
        required = {'provider', 'mode', 'catalog_id', 'model', 'effort'}
        if (not isinstance(choice, dict)
                or set(choice) not in (required, required | {'thinking'})):
            raise ValueError('Invalid model choice')
        provider, mode = choice['provider'], _mode(choice.get('provider'), choice.get('mode'))
        if any(not _short_text(choice[name]) for name in ('catalog_id', 'model')):
            raise ValueError('Invalid model choice')
        if choice['effort'] is not None and not _short_text(choice['effort'], 80):
            raise ValueError('Invalid model choice')
        thinking = choice.get('thinking')
        if thinking is not None and not _short_text(thinking, 80):
            raise ValueError('Invalid model choice')
        if (not isinstance(required_capabilities, (tuple, list))
                or any(not isinstance(item, str) or not _SAFE_ID.fullmatch(item)
                       for item in required_capabilities)):
            raise ValueError('Invalid required capability')
        with self.store._connection() as db:
            original = db.execute('''SELECT * FROM model_catalogs_v2
                WHERE provider = ? AND mode = ? AND id = ?''',
                                  (provider, mode, choice['catalog_id'])).fetchone()
            latest = db.execute('''SELECT c.*
                FROM model_catalog_state_v2 s JOIN model_catalogs_v2 c ON c.id = s.catalog_id
                JOIN model_catalog_epochs e ON e.provider = c.provider
                    AND e.mode = c.mode AND e.binding_id = c.binding_id
                    AND e.epoch = c.request_epoch
                WHERE s.provider = ? AND s.mode = ? AND s.status = 'ready' ''',
                                (provider, mode)).fetchone()
            current_binding, current_workspace = self._current_authority(
                provider, mode, db=db
            )
        if (original is None or latest is None or current_binding is None
                or original['binding_id'] != latest['binding_id']
                or latest['binding_id'] != current_binding):
            raise ValueError('Model catalog is stale or binding changed')
        catalog = self._stored_catalog(original, provider, mode)
        latest_catalog = self._stored_catalog(latest, provider, mode)
        if mode == 'api' and latest_catalog.get('workspace_binding') != current_workspace:
            raise ValueError('Model catalog is stale or workspace binding changed')
        # The saved choice keeps its original catalog provenance, but a successful
        # refresh must not force the user to resave an otherwise unchanged model.
        # Freshness therefore applies to the current validation catalog only.
        self._assert_fresh(latest_catalog)
        original_model = next((model for model in catalog['models']
                               if model['model'] == choice['model']), None)
        if original_model is None:
            raise ValueError('Model is not in the selected catalog')
        selected = next((model for model in latest_catalog['models']
                         if model['model'] == choice['model']), None)
        if selected is None:
            raise ValueError('Model is not in the current catalog')
        effort = choice['effort']
        if effort is not None:
            if effort not in {item['value'] for item in original_model['reasoning_efforts']}:
                raise ValueError(
                    'Requested effort is unknown or unsupported in the selected catalog'
                )
            if effort not in {item['value'] for item in selected['reasoning_efforts']}:
                raise ValueError('Requested effort capability is unknown or unsupported')
        if thinking is not None:
            for index, candidate in enumerate((original_model, selected)):
                claims = candidate.get('raw_capability_claims')
                thinking_claim = None if not isinstance(claims, dict) else claims.get('thinking')
                types = thinking_claim.get('types') if isinstance(thinking_claim, dict) else None
                selected_type = types.get(thinking) if isinstance(types, dict) else None
                if (not _claim_supported(thinking_claim)
                        or not _claim_supported(selected_type)):
                    where = 'selected catalog' if index == 0 else 'current catalog'
                    raise ValueError(f'Requested thinking is unknown or unsupported in the {where}')
        for capability in required_capabilities:
            if selected['capabilities'].get(capability) is not True:
                raise ValueError('A required model capability is unknown or unsupported')
        return {
            **choice,
            'display_name': original_model['display_name'],
            'fetched_at': catalog['fetched_at'],
            'binding_id': catalog['binding_id'],
            'workspace_binding': catalog['workspace_binding'],
            'request_epoch': catalog['request_epoch'],
            'capability_claims_digest': original_model['capability_claims_digest'],
            'validated_catalog_id': latest_catalog['catalog_id'],
            'latest_fetched_at': latest_catalog['fetched_at'],
        }

    def assert_validation_fence(self, db, selection):
        """Fence a previously validated choice against the catalog row in a caller write txn.

        This performs no provider request.  Holding the SQLite write transaction prevents a
        concurrent refresh from replacing the current catalog between this check and the
        caller's immutable run-record insert.
        """
        required = {
            'provider', 'mode', 'catalog_id', 'model', 'binding_id',
            'validated_catalog_id', 'request_epoch', 'capability_claims_digest',
        }
        if not isinstance(selection, dict) or not required.issubset(selection):
            raise ValueError('Model validation fence is incomplete')
        provider, mode = selection['provider'], _mode(selection['provider'], selection['mode'])
        original_row = db.execute('''SELECT * FROM model_catalogs_v2
            WHERE provider = ? AND mode = ? AND id = ?''',
                                  (provider, mode, selection['catalog_id'])).fetchone()
        if original_row is None:
            raise ValueError('Original model catalog changed before the run choice was frozen')
        original = self._stored_catalog(original_row, provider, mode)
        original_model = next((item for item in original['models']
                               if item['model'] == selection['model']), None)
        if (original_model is None
                or original_row['binding_id'] != selection['binding_id']
                or original.get('workspace_binding') != selection.get('workspace_binding')
                or original.get('request_epoch') != selection['request_epoch']
                or original_model.get('capability_claims_digest')
                    != selection['capability_claims_digest']):
            raise ValueError('Original model catalog provenance changed before freeze')
        row = db.execute('''SELECT c.*
            FROM model_catalog_state_v2 s JOIN model_catalogs_v2 c ON c.id = s.catalog_id
            JOIN model_catalog_epochs e ON e.provider = c.provider
                AND e.mode = c.mode AND e.binding_id = c.binding_id
                AND e.epoch = c.request_epoch
            WHERE s.provider = ? AND s.mode = ? AND s.status = 'ready' ''',
                         (provider, mode)).fetchone()
        if row is None:
            raise ValueError('Model catalog changed before the run choice was frozen')
        catalog = self._stored_catalog(row, provider, mode)
        if selection['validated_catalog_id'] != catalog.get('catalog_id'):
            raise ValueError('Model catalog changed before the run choice was frozen')
        self._assert_fresh(catalog)
        current_binding, current_workspace = self._current_authority(provider, mode, db=db)
        if (row['binding_id'] != selection['binding_id']
                or current_binding != row['binding_id']
                or (mode == 'api'
                    and catalog.get('workspace_binding') != current_workspace)):
            raise ValueError('Model binding changed before the run choice was frozen')
        model = next((item for item in catalog['models']
                      if item['model'] == selection['model']), None)
        if model is None:
            raise ValueError('Model changed before the run choice was frozen')
