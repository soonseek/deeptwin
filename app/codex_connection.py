"""Pre-release host-local Codex authentication development adapter.

Credentials remain owned by Codex. Only explicit connection/login actions start
the auth-only RPC client; uploads and bootstrap never start a provider process.
This adapter inspects the development host's existing Codex installation/auth and
does not qualify ADR-010's server-owned isolated managed runner.  T088 must replace
that release path while keeping every end-user action in DeepTwin's browser UI.
"""

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
import time
from urllib.parse import urlsplit

from .codex_rpc import CodexRPC
from .providers import _candidate_paths
from .storage import ConflictError

PLAN_TYPES = {'free', 'go', 'plus', 'pro', 'team', 'business', 'enterprise', 'edu', 'unknown'}
LOGIN_TTL = 600


def find_codex():
    path = shutil.which('codex')
    if path:
        return path
    return next((str(path) for path in _candidate_paths('codex') if path.is_file() and os.access(path, os.X_OK)), None)


def process_environment():
    # Preserve ordinary runtime locations, never forward API keys, access tokens,
    # proxy credentials or tracing variables into the subscription auth process.
    keys = {'PATH', 'HOME', 'USER', 'LOGNAME', 'SHELL', 'LANG', 'LC_ALL', 'LC_CTYPE', 'TZ', 'TMPDIR',
            'SYSTEMROOT', 'WINDIR', 'APPDATA', 'LOCALAPPDATA', 'XDG_CONFIG_HOME', 'CODEX_HOME'}
    return {key: value for key, value in os.environ.items() if key in keys}


def allowed_auth_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(char) < 33 or char == '\\' for char in value):
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and url.hostname in {'auth.openai.com', 'chatgpt.com'}
                and url.port in {None, 443} and url.username is None and url.password is None)
    except ValueError:
        return False


def rate_windows(result):
    if not isinstance(result, dict):
        return []
    buckets = result.get('rateLimitsByLimitId')
    if not isinstance(buckets, dict):
        legacy = result.get('rateLimits')
        buckets = {'codex': legacy} if isinstance(legacy, dict) else {}
    windows = []
    for index, (key, bucket) in enumerate(list(buckets.items())[:20]):
        if not isinstance(bucket, dict):
            continue
        identifier = key if isinstance(key, str) and re.fullmatch(r'[a-zA-Z0-9_.:-]{1,80}', key) else f'bucket-{index + 1}'
        for name in ('primary', 'secondary'):
            window = bucket.get(name)
            if not isinstance(window, dict):
                continue
            used = window.get('usedPercent')
            remaining = max(0, min(100, 100 - used)) if type(used) in {float, int} and math.isfinite(used) else None
            minutes, reset = window.get('windowDurationMins'), window.get('resetsAt')
            windows.append(dict(id=f'{identifier}:{name}', label=identifier, remaining_percent=remaining,
                window_minutes=minutes if type(minutes) is int and minutes >= 0 else None,
                resets_at=reset if type(reset) is int and 0 <= reset <= 253402300799 else None))
    return windows


class CodexConnection:
    def __init__(self, store, rpc_factory=None):
        self.store = store
        self._factory = rpc_factory or CodexRPC
        self._rpc = None
        self._lock = threading.RLock()
        self._state = 'unchecked' if find_codex() else 'unavailable'
        self._billing = 'unknown'
        self._auth = 'unknown' if self._state == 'unchecked' else 'unavailable'
        self._message = (
            '연결 확인을 누르면 이 DeepTwin 인스턴스의 사전 출시 호스트 어댑터 상태를 확인합니다. '
            '웹 릴리스에서는 서버 소유 관리형 Codex 실행기가 연결을 담당합니다.'
            if self._state == 'unchecked' else
            '이 DeepTwin 인스턴스의 사전 출시 호스트 어댑터를 사용할 수 없습니다. '
            '웹 릴리스에 필요한 서버 소유 관리형 Codex 실행기의 배포는 아직 완료되지 않았습니다.'
        )
        self._plan = None
        self._rates = []
        self._checked_at = None
        self._login = {'status': 'idle'}
        self._login_started = None
        self._catalog_session = secrets.token_urlsafe(18)
        self._account_generation = 0
        self._account_identity = None
        # A persisted catalog is displayable after restart, but cannot be used
        # until this process explicitly verifies the current ChatGPT account.
        self._record_catalog_binding()

    def _event(self, kind):
        # Deliberately exclude email, login IDs, URLs, arbitrary errors and raw
        # provider replies. The shared intake event stream remains export-safe.
        with self.store._connection() as db:
            db.execute('INSERT INTO events(kind, work_id, created_at, metadata) VALUES (?, NULL, ?, ?)',
                (kind, datetime.now(timezone.utc).isoformat(), json.dumps({
                    'provider': 'codex', 'state': self._state, 'billing': self._billing,
                    'login_status': self._login['status']})))

    def _view(self):
        return deepcopy(dict(id='codex', label='Codex', installed=bool(find_codex()),
            auth_status=self._auth, billing=self._billing, message=self._message,
            source_url='https://learn.chatgpt.com/docs/app-server', capabilities={'execution': False},
            connection=dict(state=self._state, message=self._message, plan_type=self._plan,
                login=self._login, rate_limits=self._rates, checked_at=self._checked_at,
                credential_scope='shared_codex')))

    def _ensure(self):
        if self._rpc and self._rpc.running:
            return
        if self._rpc:
            self._rpc.close()
        executable = find_codex()
        if not executable:
            raise FileNotFoundError('Codex unavailable')
        cwd = self.store.data_dir / 'codex-auth-runtime'
        if cwd.is_symlink():
            raise ValueError('Provider directory cannot be a symlink')
        cwd.mkdir(mode=0o700, exist_ok=True)
        cwd.chmod(0o700)
        # Do not override forced_login_method: a mismatch can log out the
        # shared account. Only non-persistent telemetry overrides are applied.
        command = [executable, 'app-server', '--stdio', '-c', 'analytics.enabled=false',
                   '-c', 'otel.exporter="none"', '-c', 'otel.metrics_exporter="none"',
                   '-c', 'otel.trace_exporter="none"', '-c', 'otel.log_user_prompt=false']
        self._rpc = self._factory(command, cwd=cwd, env=process_environment(), timeout=10)
        self._rpc.start()

    def _failed(self, *, login=False):
        if self._rpc:
            self._rpc.close()
        self._state, self._auth, self._billing = 'error', 'unknown', 'unknown'
        self._rates, self._plan, self._checked_at = [], None, None
        self._record_catalog_binding()
        if login or self._login['status'] == 'pending':
            self._login = {'status': 'failed'}
        self._message = 'Codex 연결을 확인하지 못했습니다. 연결 확인으로 다시 시도해 주세요. 업무와 자료는 그대로 있습니다.'
        self._event('codex_connection_failed')

    def _read(self, *, limits=True):
        result = self._rpc.call('account/read', {'refreshToken': False})
        if not isinstance(result, dict):
            raise ValueError('Invalid account response')
        account = result.get('account')
        if account is not None and not isinstance(account, dict):
            raise ValueError('Invalid account')
        kind = account.get('type') if account else None
        self._rates, self._plan = [], None
        if kind == 'chatgpt':
            self._state, self._auth, self._billing = 'connected', 'logged_in', 'subscription'
            plan = account.get('planType')
            self._plan = plan if isinstance(plan, str) and plan in PLAN_TYPES else 'unknown'
            self._message = 'ChatGPT 계정 연결을 확인했습니다. 실제 모델 실행과 환경 설계는 아직 연결되지 않았습니다.'
            if limits:
                try:
                    self._rates = rate_windows(self._rpc.call('account/rateLimits/read', None))
                except Exception:
                    if not self._rpc.running:
                        raise RuntimeError('Provider process exited during account check') from None
                    self._message += ' 사용 한도는 확인하지 못했습니다.'
        elif kind == 'apiKey':
            self._state, self._auth, self._billing = 'api_key', 'logged_in', 'api'
            self._message = '현재 Codex는 API 계정입니다. 구독 연결로 사용하지 않으며 API 요청도 보내지 않습니다. 구독을 쓰려면 ChatGPT로 로그인해 주세요.'
        elif kind is None:
            self._state, self._auth, self._billing = 'disconnected', 'logged_out', 'unknown'
            self._message = 'ChatGPT 로그인이 필요합니다. 입력과 자료는 로그인 전에도 저장할 수 있습니다.'
        else:
            self._state, self._auth, self._billing = 'unavailable', 'unknown', 'unknown'
            self._message = '현재 Codex 인증 방식은 이 구독 연결에서 지원하지 않습니다. 자동으로 인증을 변경하지 않습니다.'
        self._checked_at = datetime.now(timezone.utc).isoformat()
        email = account.get('email') if isinstance(account, dict) else None
        identity = (kind, email if isinstance(email, str) else None, self._plan)
        if identity != self._account_identity:
            self._account_identity = identity
            self._account_generation += 1
        self._record_catalog_binding()

    def _record_catalog_binding(self):
        binding = (f'{self._catalog_session}:{self._account_generation}'
                   if self._state == 'connected' and self._billing == 'subscription' else None)
        with self.store._connection() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS model_catalog_account_state (
                provider TEXT PRIMARY KEY, binding TEXT NOT NULL)''')
            if binding is None:
                db.execute('DELETE FROM model_catalog_account_state WHERE provider = ?', ('codex',))
            else:
                db.execute('''INSERT INTO model_catalog_account_state VALUES (?, ?)
                    ON CONFLICT(provider) DO UPDATE SET binding = excluded.binding''',
                           ('codex', binding))

    def catalog_binding(self):
        """Return an opaque, process-local binding without provider I/O."""
        with self._lock:
            if self._state != 'connected' or self._billing != 'subscription':
                return None
            return f'{self._catalog_session}:{self._account_generation}'

    def read_model_catalog(self):
        """Read visible models only when an explicit catalog refresh calls it."""
        with self._lock:
            self._ensure()
            self._updates()
            self._read(limits=False)
            if self._state != 'connected' or self._billing != 'subscription':
                raise PermissionError('ChatGPT subscription required')
            pages, cursor, seen = [], None, set()
            for _ in range(20):
                params = {'limit': 100, 'includeHidden': False}
                if cursor is not None:
                    params['cursor'] = cursor
                page = self._rpc.call('model/list', params)
                if not isinstance(page, dict):
                    raise ValueError('Invalid model catalog page')
                pages.append(page)
                cursor = page.get('nextCursor')
                if cursor is None:
                    return {'pages': pages, 'binding': self.catalog_binding()}
                if (not isinstance(cursor, str) or not cursor or len(cursor) > 2048
                        or cursor in seen):
                    raise ValueError('Invalid model catalog cursor')
                seen.add(cursor)
            raise ValueError('Model catalog pagination exceeded the limit')

    def _updates(self):
        if not self._rpc:
            return
        if not self._rpc.running:
            if self._state != 'error':
                self._failed()
            return
        for note in self._rpc.drain_notifications():
            if not isinstance(note, dict) or not isinstance(note.get('params'), dict):
                continue
            params, method = note['params'], note.get('method')
            if method == 'account/login/completed':
                if self._login['status'] != 'pending' or params.get('loginId') != self._login.get('login_id'):
                    continue
                if params.get('success') is True:
                    self._read()
                    success = self._state == 'connected'
                    self._login = {'status': 'succeeded' if success else 'failed'}
                    if not success:
                        self._message = '로그인 완료 알림은 받았지만 ChatGPT 계정 연결을 확인하지 못했습니다. 연결 확인을 다시 눌러 주세요.'
                    self._event('codex_login_succeeded' if success else 'codex_login_failed')
                else:
                    self._login = {'status': 'failed'}
                    self._message = '로그인을 완료하지 못했습니다. 다시 로그인할 수 있습니다.'
                    self._event('codex_login_failed')
            elif method == 'account/updated':
                self._read()
                self._event('codex_connection_updated')
            elif method == 'account/rateLimits/updated' and self._state == 'connected':
                self._rates = rate_windows(params if 'rateLimits' in params else {'rateLimits': params})
        if self._login['status'] == 'pending' and time.monotonic() - self._login_started > LOGIN_TTL:
            result = self._rpc.call('account/login/cancel', {'loginId': self._login['login_id']})
            self._login = {'status': 'failed'}
            if not isinstance(result, dict) or result.get('status') != 'canceled':
                self._read()
                self._message += ' 로그인 대기 시간은 지났지만 이미 완료되었을 수 있어 현재 계정을 다시 확인했습니다.'
            else:
                self._message = '로그인 대기 시간이 지났습니다. 다시 로그인해 주세요.'
            self._event('codex_login_expired')

    def snapshot(self):
        with self._lock:
            try:
                self._updates()
            except Exception:
                self._failed()
            return self._view()

    def check(self):
        with self._lock:
            try:
                self._event('codex_connection_check_requested')
                self._ensure()
                self._updates()
                self._read()
                self._event('codex_connection_checked')
            except Exception:
                self._failed()
            return self._view()

    def start_login(self):
        with self._lock:
            try:
                self._updates()
                if self._login['status'] == 'pending':
                    return self._view()
                self._event('codex_login_requested')
                self._ensure()
                self._read(limits=False)
                if self._state == 'connected':
                    return self._view()
                result = self._rpc.call('account/login/start', {
                    'type': 'chatgpt', 'useHostedLoginSuccessPage': True, 'appBrand': 'chatgpt'})
                if (not isinstance(result, dict) or result.get('type') != 'chatgpt'
                        or not isinstance(result.get('loginId'), str)
                        or not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', result['loginId'])
                        or not allowed_auth_url(result.get('authUrl'))):
                    raise ValueError('Invalid managed login response')
                self._login = {'status': 'pending', 'login_id': result['loginId'], 'auth_url': result['authUrl']}
                self._login_started = time.monotonic()
                self._message = '공식 로그인 화면에서 완료한 뒤 이 업무 공간으로 돌아오세요.'
                self._event('codex_login_started')
            except Exception:
                self._failed(login=True)
            return self._view()

    def cancel_login(self, login_id):
        with self._lock:
            if self._login['status'] != 'pending' or login_id != self._login.get('login_id'):
                raise ConflictError('No matching login attempt')
            try:
                self._event('codex_login_cancel_requested')
                result = self._rpc.call('account/login/cancel', {'loginId': login_id})
                if isinstance(result, dict) and result.get('status') == 'canceled':
                    self._login = {'status': 'cancelled'}
                    self._message = '로그인 대기를 취소했습니다. 기존 Codex 계정을 로그아웃하지 않았습니다.'
                    self._event('codex_login_cancelled')
                else:
                    self._login = {'status': 'failed'}
                    self._read()
                    self._message += ' 로그인 취소를 확인하지 못했습니다. 이미 완료되었을 수 있으며 자격 증명을 되돌리지 않았습니다.'
                    self._event('codex_login_cancel_unconfirmed')
            except Exception:
                self._failed(login=True)
            return self._view()

    def close(self):
        with self._lock:
            if self._rpc:
                self._rpc.close()
