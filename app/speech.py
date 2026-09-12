"""Bounded instance-owned PCM transcriber. No downloads, recording, or provider calls."""

import hashlib
import json
import os
from pathlib import Path
import selectors
import stat
import struct
import subprocess
import threading
import time


MIN_PCM_BYTES = 8_000
MAX_PCM_BYTES = 256_000
ENGINE_VERSION = '1.8.7'
MODEL_SHA256 = '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe'
MAX_REPLY_BYTES = 65_536
MAX_RUNTIME_FILES = 64


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _strict_json(value):
    return json.loads(value, object_pairs_hook=_unique_object)


def _has_symlink_component(path):
    path = path.absolute()
    return any(component.is_symlink() for component in (path, *path.parents))


def _identity(path):
    value = path.lstat()
    return (value.st_dev, value.st_ino, value.st_mode, value.st_size,
            value.st_mtime_ns, value.st_ctime_ns)


class SpeechUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('DeepTwin 인스턴스의 음성 입력 기능을 사용할 수 없습니다. 인스턴스 운영 상태를 확인해 주세요. 브라우저가 받은 마이크 음성은 이 인스턴스 밖의 제공자에게 보내지 않았습니다.')


class SpeechBusy(RuntimeError):
    def __init__(self):
        super().__init__('앞선 음성 구간을 처리하고 있습니다. 잠시 후 다시 시도해 주세요.')


class SpeechCancelled(RuntimeError):
    def __init__(self):
        super().__init__('음성 처리를 중단했습니다.')


class Speech:
    def __init__(self, store, runtime_dir=None):
        self.store = store
        self.runtime_dir = Path(runtime_dir) if runtime_dir is not None else store.data_dir / 'speech-runtime'
        self._engine_lock = threading.Lock()
        self._process_lock = threading.Lock()
        self._process = None
        self._closed = False
        self._verified = None
        self.timeout = 30
        self.startup_timeout = 60

    def _installation(self):
        root = self.runtime_dir
        if _has_symlink_component(root) or not root.is_dir():
            raise SpeechUnavailable()
        manifest_path = root / 'manifest.json'
        manifest_identity = _identity(manifest_path)
        if (manifest_path.is_symlink() or not stat.S_ISREG(manifest_identity[2])
                or not 0 < manifest_identity[3] <= 32_768):
            raise SpeechUnavailable()
        manifest_bytes = manifest_path.read_bytes()
        if _identity(manifest_path) != manifest_identity:
            raise SpeechUnavailable()
        value = _strict_json(manifest_bytes)
        if (not isinstance(value, dict) or type(value.get('version')) is not int or value['version'] != 1
                or value.get('engine') != 'whisper.cpp'
                or value.get('engine_version') != ENGINE_VERSION or value.get('model') != 'base'
                or value.get('model_sha256') != MODEL_SHA256 or not isinstance(value.get('files'), dict)
                or not 3 <= len(value['files']) <= MAX_RUNTIME_FILES):
            raise SpeechUnavailable()
        paths = {}
        fingerprints = []
        for name, digest in value['files'].items():
            if not isinstance(name, str) or not 0 < len(name) <= 1_024:
                raise SpeechUnavailable()
            relative = Path(name)
            if (relative.is_absolute() or not relative.parts or any(p in {'.', '..'} for p in relative.parts)
                    or not isinstance(digest, str) or len(digest) != 64
                    or any(character not in '0123456789abcdef' for character in digest)):
                raise SpeechUnavailable()
            path = root
            for part in relative.parts:
                path = path / part
                if path.is_symlink():
                    raise SpeechUnavailable()
            path_identity = _identity(path)
            if not stat.S_ISREG(path_identity[2]):
                raise SpeechUnavailable()
            paths[name] = path
            fingerprints.append((name, digest, path_identity))
        for key in ('worker', 'model_file', 'library'):
            if value.get(key) not in paths:
                raise SpeechUnavailable()
        if value['files'][value['model_file']] != MODEL_SHA256:
            raise SpeechUnavailable()
        if not paths[value['worker']].stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
            raise SpeechUnavailable()
        signature = (manifest_bytes, tuple(fingerprints))
        if signature != self._verified:
            for name, path in paths.items():
                before = _identity(path)
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    opened = os.fstat(stream.fileno())
                    opened_identity = (opened.st_dev, opened.st_ino, opened.st_mode, opened.st_size,
                                       opened.st_mtime_ns, opened.st_ctime_ns)
                if digest != value['files'][name] or before != opened_identity or _identity(path) != opened_identity:
                    raise SpeechUnavailable()
            self._verified = signature
        selected = (paths[value['worker']], paths[value['model_file']], paths[value['library']])
        self._launch_paths = selected
        self._launch_identity = tuple(_identity(path) for path in selected)
        return selected[0], selected[1]

    def snapshot(self):
        ready = False
        if not self._closed:
            try:
                self._installation()
                ready = True
            except (OSError, ValueError, TypeError, KeyError, SpeechUnavailable):
                pass
        return {'ready': ready, 'engine': 'whisper.cpp', 'model': 'base', 'language': 'ko',
                'message': ('브라우저가 받은 마이크 음성을 이 DeepTwin 인스턴스가 글로 바꿀 준비가 됐습니다. 한국어 인식 품질은 확인이 필요합니다.'
                            if ready else 'DeepTwin 인스턴스의 음성 입력 기능이 준비되지 않았습니다. 글이나 파일로 계속할 수 있습니다. 브라우저가 받은 마이크 음성은 이 인스턴스 밖의 제공자에게 보내지 않습니다.')}

    @staticmethod
    def _cancelled(cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise SpeechCancelled()

    def _check(self, process, deadline, cancel_event):
        self._cancelled(cancel_event)
        if self._closed or process.poll() is not None or time.monotonic() >= deadline:
            raise SpeechUnavailable()

    def _write(self, process, body, deadline, cancel_event):
        offset = 0
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            while offset < len(body):
                self._check(process, deadline, cancel_event)
                if selector.select(.05):
                    try:
                        count = os.write(process.stdin.fileno(), body[offset:offset + 8192])
                        if not count:
                            raise SpeechUnavailable()
                        offset += count
                    except BlockingIOError:
                        pass

    def _read(self, process, count, deadline, cancel_event):
        result = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while len(result) < count:
                self._check(process, deadline, cancel_event)
                if selector.select(.05):
                    try:
                        chunk = os.read(process.stdout.fileno(), count - len(result))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        raise SpeechUnavailable()
                    result.extend(chunk)
        return bytes(result)

    def _reply(self, process, deadline, cancel_event):
        size, = struct.unpack('<I', self._read(process, 4, deadline, cancel_event))
        if not 0 < size <= MAX_REPLY_BYTES:
            raise SpeechUnavailable()
        result = _strict_json(self._read(process, size, deadline, cancel_event))
        if not isinstance(result, dict):
            raise SpeechUnavailable()
        return result

    def _start(self, cancel_event):
        worker, model = self._installation()
        launch_paths = getattr(self, '_launch_paths', (worker, model))
        expected_identity = getattr(self, '_launch_identity', None)
        if expected_identity is not None and tuple(_identity(path) for path in launch_paths[:len(expected_identity)]) != expected_identity:
            raise SpeechUnavailable()
        with self._process_lock:
            if self._closed:
                raise SpeechUnavailable()
            if self._process is not None and self._process.poll() is None:
                return self._process
            env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'TMPDIR') if key in os.environ}
            process = subprocess.Popen([str(worker), str(model)], cwd=worker.parent, env=env,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, bufsize=0, shell=False)
            self._process = process
            os.set_blocking(process.stdin.fileno(), False)
            os.set_blocking(process.stdout.fileno(), False)
        if expected_identity is not None:
            current = tuple(_identity(path) for path in launch_paths[:len(expected_identity)])
            if current != expected_identity:
                self._stop()
                raise SpeechUnavailable()
        hello = self._reply(process, time.monotonic() + self.startup_timeout, cancel_event)
        if hello != {'ready': True, 'version': ENGINE_VERSION}:
            raise SpeechUnavailable()
        return process

    def transcribe(self, pcm: bytes, cancel_event=None):
        if not isinstance(pcm, bytes) or not MIN_PCM_BYTES <= len(pcm) <= MAX_PCM_BYTES or len(pcm) % 2:
            raise ValueError('PCM16LE 모노 16kHz 음성 구간은 0.25초에서 8초까지 가능합니다.')
        self._cancelled(cancel_event)
        if not self._engine_lock.acquire(blocking=False):
            raise SpeechBusy()
        started = time.monotonic()
        try:
            # The real base model hallucinated a phrase for digital silence.
            # This catches exact zero PCM only; it is not general VAD or proof
            # that quiet/noisy microphone input will never hallucinate.
            if not any(pcm):
                if self._closed:
                    raise SpeechUnavailable()
                self._installation()
                self._cancelled(cancel_event)
                return {'text': '', 'engine': 'whisper.cpp', 'model': 'base',
                        'language': 'ko', 'elapsed_ms': round((time.monotonic() - started) * 1000)}
            process = self._start(cancel_event)
            deadline = time.monotonic() + self.timeout
            self._write(process, struct.pack('<I', len(pcm)) + pcm, deadline, cancel_event)
            reply = self._reply(process, deadline, cancel_event)
            self._cancelled(cancel_event)
            if (set(reply) != {'text'} or not isinstance(reply['text'], str)
                    or len(reply['text']) > 20_000):
                raise SpeechUnavailable()
            return {'text': reply['text'], 'engine': 'whisper.cpp', 'model': 'base',
                    'language': 'ko', 'elapsed_ms': round((time.monotonic() - started) * 1000)}
        except SpeechCancelled:
            self._stop()
            raise
        except (OSError, ValueError, TypeError, KeyError, SpeechUnavailable):
            self._stop()
            raise SpeechUnavailable() from None
        finally:
            self._engine_lock.release()

    def _stop(self):
        with self._process_lock:
            process, self._process = self._process, None
            if process is None:
                return
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
            for stream in (process.stdin, process.stdout):
                stream.close()

    def close(self):
        self._closed = True
        self._stop()
