"""Bounded synchronous JSONL transport for a local Codex app-server process."""

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
import queue
import subprocess
import threading


_ALLOWED_METHODS = {
    'initialize',
    'account/read',
    'account/login/start',
    'account/login/cancel',
    'account/rateLimits/read',
    'model/list',
}
_MAX_LINE_BYTES = 1024 * 1024
_MAX_NOTIFICATIONS = 100
_MAX_PENDING = 32


class CodexRPCError(RuntimeError):
    """A deliberately generic transport failure safe for caller-visible logs."""


def terminate_owned_process(process, grace=0.3):
    """SIGTERM then SIGKILL the owned process; True only when its exit is confirmed."""
    if process.poll() is not None:
        return True
    try:
        process.terminate()
        process.wait(timeout=grace)
        return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=grace)
    except (OSError, subprocess.TimeoutExpired):
        pass
    return process.poll() is not None


@dataclass
class _Pending:
    event: threading.Event
    result: object = None
    error: str | None = None


class CodexRPC:
    def __init__(self, command: list[str], cwd: Path, env: dict | None = None, timeout=10):
        if (not isinstance(command, list) or not command
                or any(not isinstance(part, str) or not part for part in command)):
            raise ValueError('Codex command must be a non-empty argument list')
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0:
            raise ValueError('Codex timeout must be positive')
        self.command = command.copy()
        self.cwd = Path(cwd)
        self.env = None if env is None else dict(env)
        self.timeout = float(timeout)
        self._process = None
        self._reader = None
        self._writer = None
        self._outbound = queue.Queue(maxsize=_MAX_PENDING)
        self._next_id = 1
        self._pending = {}
        self._notifications = deque(maxlen=_MAX_NOTIFICATIONS)
        self._failure = None
        self._closing = False
        self.termination_confirmed = None
        self._state_lock = threading.Lock()
        self._write_lock = threading.Lock()

    @property
    def running(self):
        process = self._process
        return process is not None and process.poll() is None and self._failure is None

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()

    def _initialize_params(self):
        return {'clientInfo': {'name': 'deeptwin', 'title': 'DeepTwin', 'version': '0.1.0'}}

    def start(self):
        with self._state_lock:
            if self._closing:
                raise CodexRPCError('Codex 연결을 시작하지 못했습니다.')
            if self._process is not None:
                if self.running:
                    return self
                raise CodexRPCError('Codex 연결을 시작하지 못했습니다.')
            try:
                self._process = subprocess.Popen(
                    self.command,
                    cwd=self.cwd,
                    env=self.env,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
            except (OSError, ValueError):
                self._process = None
                raise CodexRPCError('Codex 연결을 시작하지 못했습니다.') from None
            self._writer = threading.Thread(target=self._write_loop, name='deeptwin-codex-writer', daemon=True)
            self._reader = threading.Thread(target=self._read_loop, name='deeptwin-codex-reader', daemon=True)
            self._writer.start()
            self._reader.start()
        try:
            self.call('initialize', self._initialize_params())
            self._send({'method': 'initialized', 'params': {}})
        except Exception:
            self.close()
            raise
        return self

    def call(self, method, params, timeout=None):
        if method not in _ALLOWED_METHODS:
            raise ValueError('허용되지 않은 Codex 요청입니다.')
        if params is not None and not isinstance(params, dict):
            raise ValueError('Codex 요청 항목은 객체여야 합니다.')
        if method == 'account/login/start':
            allowed = {'type', 'useHostedLoginSuccessPage', 'appBrand'}
            if (params is None or params.get('type') != 'chatgpt' or set(params) - allowed
                    or ('useHostedLoginSuccessPage' in params
                        and not isinstance(params['useHostedLoginSuccessPage'], bool))
                    or ('appBrand' in params and params['appBrand'] not in {None, 'codex', 'chatgpt'})):
                raise ValueError('ChatGPT 로그인만 시작할 수 있습니다.')
        duration = self.timeout if timeout is None else timeout
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration <= 0:
            raise ValueError('Codex timeout must be positive')

        with self._state_lock:
            if not self.running:
                raise CodexRPCError('Codex 연결을 사용할 수 없습니다.')
            if len(self._pending) >= _MAX_PENDING:
                raise CodexRPCError('Codex 요청이 너무 많습니다.')
            request_id = self._next_id
            self._next_id += 1
            pending = _Pending(threading.Event())
            self._pending[request_id] = pending
        try:
            self._send({'id': request_id, 'method': method, 'params': params})
        except (CodexRPCError, ValueError):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise

        if not pending.event.wait(float(duration)):
            with self._state_lock:
                self._pending.pop(request_id, None)
            raise CodexRPCError('Codex 응답 시간이 초과되었습니다.')
        with self._state_lock:
            self._pending.pop(request_id, None)
        if pending.error is not None:
            raise CodexRPCError(pending.error)
        return pending.result

    def drain_notifications(self):
        with self._state_lock:
            notifications = list(self._notifications)
            self._notifications.clear()
        return notifications

    def close(self):
        with self._state_lock:
            self._closing = True
            process = self._process
        self._fail_pending('Codex 연결이 종료되었습니다.')
        if process is None:
            self.termination_confirmed = True
            return
        self.termination_confirmed = terminate_owned_process(process)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        reader = self._reader
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=0.5)
        writer = self._writer
        if writer is not None and writer is not threading.current_thread():
            writer.join(timeout=0.5)
        with self._state_lock:
            self._process = None
            self._reader = None
            self._writer = None

    def _encode(self, message):
        try:
            body = json.dumps(message, ensure_ascii=False, separators=(',', ':')).encode('utf-8') + b'\n'
        except (TypeError, ValueError, UnicodeError):
            raise ValueError('Codex 요청을 JSON으로 만들 수 없습니다.') from None
        if len(body) > _MAX_LINE_BYTES:
            raise ValueError('Codex 요청 크기를 넘었습니다.')
        return body

    def _send(self, message):
        body = self._encode(message)
        with self._state_lock:
            process = self._process
            if (process is None or process.poll() is not None or process.stdin is None
                    or self._failure is not None or self._closing):
                raise CodexRPCError('Codex 연결을 사용할 수 없습니다.')
        try:
            self._outbound.put_nowait(body)
        except queue.Full:
            raise CodexRPCError('Codex 요청이 너무 많습니다.') from None

    def _write_loop(self):
        process = self._process
        while True:
            try:
                body = self._outbound.get(timeout=0.1)
            except queue.Empty:
                if self._closing:
                    return
                continue
            try:
                if process is None or process.poll() is not None or process.stdin is None:
                    raise BrokenPipeError
                with self._write_lock:
                    process.stdin.write(body)
                    process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                if not self._closing:
                    self._set_failure('Codex 연결에 실패했습니다.')
                return

    def _read_loop(self):
        process = self._process
        try:
            while process is not None and process.stdout is not None:
                line = process.stdout.readline(_MAX_LINE_BYTES + 1)
                if not line:
                    if not self._closing:
                        self._set_failure('Codex 연결이 예기치 않게 종료되었습니다.')
                    return
                if len(line) > _MAX_LINE_BYTES or not line.endswith(b'\n'):
                    self._set_failure('Codex 응답 형식을 확인하지 못했습니다.')
                    return
                try:
                    message = json.loads(line)
                except (json.JSONDecodeError, UnicodeError):
                    self._set_failure('Codex 응답 형식을 확인하지 못했습니다.')
                    return
                if not isinstance(message, dict):
                    self._set_failure('Codex 응답 형식을 확인하지 못했습니다.')
                    return
                self._receive(message)
        except (OSError, ValueError):
            if not self._closing:
                self._set_failure('Codex 연결에 실패했습니다.')

    def _receive(self, message):
        if 'method' in message:
            if 'id' in message:
                if not self._valid_id(message['id']):
                    self._set_failure('Codex 응답 형식을 확인하지 못했습니다.')
                    return
                try:
                    self._send({
                        'id': message['id'],
                        'error': {'code': -32601, 'message': 'Method not found'},
                    })
                except (CodexRPCError, ValueError):
                    self._set_failure('Codex 연결에 실패했습니다.')
                return
            with self._state_lock:
                self._notifications.append(message)
            return

        request_id = message.get('id')
        if not self._valid_id(request_id):
            self._set_failure('Codex 응답 형식을 확인하지 못했습니다.')
            return
        with self._state_lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            if 'error' in message or 'result' not in message:
                pending.error = 'Codex 요청을 완료하지 못했습니다.'
            else:
                pending.result = message['result']
            pending.event.set()

    @staticmethod
    def _valid_id(value):
        return not isinstance(value, bool) and isinstance(value, (int, str))

    def _set_failure(self, message):
        with self._state_lock:
            if self._failure is None:
                self._failure = message
            for item in self._pending.values():
                item.error = self._failure
                item.event.set()

    def _fail_pending(self, message):
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
            for item in pending:
                item.error = message
                item.event.set()
