"""Local speech boundary. Synthetic PCM is not recognition-quality evidence."""

import importlib
import json
import hashlib
from pathlib import Path
import sys
import threading
import time

import pytest

from app.storage import Store


def speech_module():
    assert importlib.util.find_spec('app.speech'), 'Local speech core is missing'
    return importlib.import_module('app.speech')


def test_unprepared_status_is_read_only_and_honest(tmp_path):
    store = Store(tmp_path / 'data')
    target = tmp_path / 'not-installed'
    service = speech_module().Speech(store, runtime_dir=target)
    result = service.snapshot()
    assert result['ready'] is False and result['language'] == 'ko'
    assert result['engine'] == 'whisper.cpp' and result['model'] == 'base'
    assert 'DeepTwin 인스턴스' in result['message'] and '이 컴퓨터' not in result['message']
    assert not target.exists()
    with pytest.raises(speech_module().SpeechUnavailable):
        service.transcribe(bytes(8000))
    assert not target.exists()
    service.close()


@pytest.mark.parametrize('pcm', [b'', b'x', bytes(7998), bytes(256002), 'not bytes'],
                         ids=['empty', 'odd', 'too-short', 'too-long', 'not-bytes'])
def test_pcm_validation_precedes_worker_or_disk_access(tmp_path, pcm):
    service = speech_module().Speech(Store(tmp_path / 'data'), tmp_path / 'missing')
    with pytest.raises(ValueError):
        service.transcribe(pcm)
    assert service.snapshot()['ready'] is False


def test_pre_cancelled_request_does_not_start_worker(tmp_path):
    cancel = threading.Event()
    cancel.set()
    service = speech_module().Speech(Store(tmp_path / 'data'), tmp_path / 'missing')
    with pytest.raises(speech_module().SpeechCancelled):
        service.transcribe(bytes(8000), cancel)


def test_busy_engine_does_not_queue_audio_indefinitely(tmp_path):
    service = speech_module().Speech(Store(tmp_path / 'data'), tmp_path / 'missing')
    with service._engine_lock:
        with pytest.raises(speech_module().SpeechBusy):
            service.transcribe(bytes(8000))


def test_manifest_traversal_and_symlink_are_not_ready(tmp_path):
    module = speech_module()
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    (runtime / 'manifest.json').write_text(json.dumps({'files': {'../outside': 'bad'}}))
    service = module.Speech(Store(tmp_path / 'data'), runtime)
    assert service.snapshot()['ready'] is False
    link = tmp_path / 'link'
    link.symlink_to(runtime, target_is_directory=True)
    assert module.Speech(service.store, link).snapshot()['ready'] is False


def controlled_runtime(tmp_path, monkeypatch, *, root=None):
    module = speech_module()
    runtime = root or tmp_path / 'runtime'
    runtime.mkdir(parents=True)
    payloads = {
        'v1.8.7/speech-worker': b'controlled worker',
        'v1.8.7/ggml-base.bin': b'controlled model',
        'v1.8.7/whisper.framework/Versions/A/whisper': b'controlled library',
    }
    for name, body in payloads.items():
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (runtime / 'v1.8.7/speech-worker').chmod(0o700)
    model_digest = hashlib.sha256(payloads['v1.8.7/ggml-base.bin']).hexdigest()
    monkeypatch.setattr(module, 'MODEL_SHA256', model_digest)
    manifest = {
        'version': 1, 'engine': 'whisper.cpp', 'engine_version': '1.8.7',
        'model': 'base', 'model_sha256': model_digest,
        'worker': 'v1.8.7/speech-worker', 'model_file': 'v1.8.7/ggml-base.bin',
        'library': 'v1.8.7/whisper.framework/Versions/A/whisper',
        'files': {name: hashlib.sha256(body).hexdigest() for name, body in payloads.items()},
    }
    (runtime / 'manifest.json').write_text(json.dumps(manifest))
    return module, runtime, manifest


def test_ready_status_distinguishes_browser_capture_from_instance_transcription(tmp_path, monkeypatch):
    module, runtime, _ = controlled_runtime(tmp_path, monkeypatch)
    result = module.Speech(Store(tmp_path / 'data'), runtime).snapshot()
    assert result['ready'] is True
    assert '브라우저' in result['message'] and 'DeepTwin 인스턴스' in result['message']
    assert 'DeepTwin 인스턴스' in result['message'] and '브라우저' in result['message'] and '이 컴퓨터' not in result['message']


@pytest.mark.parametrize('where', ['root', 'files'])
def test_duplicate_manifest_keys_fail_closed(tmp_path, monkeypatch, where):
    module, runtime, manifest = controlled_runtime(tmp_path, monkeypatch)
    encoded = json.dumps(manifest)
    if where == 'root':
        encoded = encoded.replace('"engine": "whisper.cpp"',
                                  '"engine": "remote", "engine": "whisper.cpp"', 1)
    else:
        name, digest = next(iter(manifest['files'].items()))
        encoded = encoded.replace(f'"{name}": "{digest}"',
                                  f'"{name}": "{"0" * 64}", "{name}": "{digest}"', 1)
    (runtime / 'manifest.json').write_text(encoded)
    assert module.Speech(Store(tmp_path / 'data'), runtime).snapshot()['ready'] is False


def test_symlinked_runtime_ancestor_fails_closed(tmp_path, monkeypatch):
    real_parent = tmp_path / 'real-parent'
    module, _, _ = controlled_runtime(tmp_path, monkeypatch, root=real_parent / 'runtime')
    alias = tmp_path / 'alias-parent'
    alias.symlink_to(real_parent, target_is_directory=True)
    assert module.Speech(Store(tmp_path / 'alias-data'), alias / 'runtime').snapshot()['ready'] is False


def test_non_executable_worker_is_not_reported_ready(tmp_path, monkeypatch):
    module, runtime, _ = controlled_runtime(tmp_path, monkeypatch)
    (runtime / 'v1.8.7/speech-worker').chmod(0o600)
    assert module.Speech(Store(tmp_path / 'mode-data'), runtime).snapshot()['ready'] is False


@pytest.mark.parametrize('content', ['[]', 'null', '42', '"string"'])
def test_non_object_manifest_is_unavailable_not_an_exception(tmp_path, content):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    (runtime / 'manifest.json').write_text(content)
    service = speech_module().Speech(Store(tmp_path / 'data'), runtime)
    assert service.snapshot()['ready'] is False


def test_closed_engine_rejects_new_work_without_installing(tmp_path):
    module = speech_module()
    service = module.Speech(Store(tmp_path / 'data'), tmp_path / 'missing')
    service.close()
    assert not service.snapshot()['ready']
    with pytest.raises(module.SpeechUnavailable):
        service.transcribe(bytes(8000))


def test_explicit_setup_rejects_bad_download_digest_without_publishing(tmp_path):
    assert importlib.util.find_spec('app.scripts.setup_local_speech'), 'Explicit setup tool is missing'
    setup = importlib.import_module('app.scripts.setup_local_speech')
    source = tmp_path / 'public-download'
    source.write_bytes(b'corrupt download')
    target = tmp_path / 'artifact'
    with pytest.raises(ValueError):
        setup.download_verified(source.as_uri(), target, '0' * 64, 16)
    assert not target.exists()


def controlled_worker(tmp_path, monkeypatch, reply="{'text': '한글 확인'}", *, stall=False, raw_reply=None):
    """Only replace the native executable; exercise real framing/OS pipes."""
    module = speech_module()
    script = tmp_path / 'controlled_worker.py'
    script.write_text('''import sys,struct,json,time
def send(value):
 body=json.dumps(value,ensure_ascii=False).encode()
 sys.stdout.buffer.write(struct.pack('<I',len(body))+body);sys.stdout.buffer.flush()
def send_raw(body):
 sys.stdout.buffer.write(struct.pack('<I',len(body))+body);sys.stdout.buffer.flush()
send({'ready':True,'version':'1.8.7'})
while True:
 header=sys.stdin.buffer.read(4)
 if not header: break
 size=struct.unpack('<I',header)[0]
 audio=sys.stdin.buffer.read(size)
 if len(audio)!=size: break
''' + (" time.sleep(10)\n" if stall else
       (f" send_raw({raw_reply!r}.encode())\n" if raw_reply is not None else " send(" + reply + ")\n")))
    service = module.Speech(Store(tmp_path / 'data'), tmp_path / 'runtime')
    monkeypatch.setattr(service, '_installation', lambda: (Path(sys.executable), script))
    return service


def test_real_pipes_preserve_unicode_and_reuse_one_worker_without_audio_files(tmp_path, monkeypatch):
    service = controlled_worker(tmp_path, monkeypatch)
    before = set(tmp_path.rglob('*'))
    try:
        first = service.transcribe(b'\x01\x00' * 4000)
        process = service._process
        second = service.transcribe(b'\x01\x00' * 128000)
        assert first['text'] == second['text'] == '한글 확인'
        assert first['engine'] == 'whisper.cpp' and first['model'] == 'base'
        assert first['language'] == 'ko' and first['elapsed_ms'] >= 0
        assert service._process is process and process.poll() is None
        assert set(tmp_path.rglob('*')) == before
    finally:
        service.close()
    assert process.poll() is not None


@pytest.mark.parametrize('reply', ["{'text':None}", "{'text':'safe','extra':'unsafe'}", "['not-object']"],
                         ids=['null-text', 'extra-field', 'not-object'])
def test_malformed_native_reply_fails_honestly_and_stops_child(tmp_path, monkeypatch, reply):
    service = controlled_worker(tmp_path, monkeypatch, reply)
    with pytest.raises(speech_module().SpeechUnavailable):
        service.transcribe(b'\x01\x00' * 4000)
    assert service._process is None


def test_duplicate_native_reply_key_fails_honestly_and_stops_child(tmp_path, monkeypatch):
    service = controlled_worker(tmp_path, monkeypatch,
                                raw_reply='{"text":"숨긴 값","text":"겉보기 값"}')
    with pytest.raises(speech_module().SpeechUnavailable):
        service.transcribe(b'\x01\x00' * 4000)
    assert service._process is None


def test_stalled_native_worker_times_out_and_does_not_retain_audio(tmp_path, monkeypatch):
    service = controlled_worker(tmp_path, monkeypatch, stall=True)
    service.timeout = .1
    started = time.monotonic()
    with pytest.raises(speech_module().SpeechUnavailable):
        service.transcribe(b'\x01\x00' * 4000)
    assert time.monotonic() - started < 2
    assert service._process is None


def test_cancellation_during_inference_terminates_owned_worker(tmp_path, monkeypatch):
    service = controlled_worker(tmp_path, monkeypatch, stall=True)
    cancel = threading.Event()
    timer = threading.Timer(.1, cancel.set)
    timer.start()
    try:
        with pytest.raises(speech_module().SpeechCancelled):
            service.transcribe(b'\x01\x00' * 4000, cancel)
    finally:
        timer.cancel()
        service.close()
    assert service._process is None


def test_setup_verified_download_preserves_existing_different_file(tmp_path):
    setup = importlib.import_module('app.scripts.setup_local_speech')
    source = tmp_path / 'source'
    source.write_bytes(b'public artifact')
    target = tmp_path / 'verified'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    setup.download_verified(source.as_uri(), target, digest, source.stat().st_size)
    assert target.read_bytes() == b'public artifact'
    target.write_bytes(b'user-owned prior content')
    with pytest.raises(ValueError):
        setup.download_verified(source.as_uri(), target, digest, source.stat().st_size)
    assert target.read_bytes() == b'user-owned prior content'


def test_exact_digital_silence_never_becomes_a_hallucinated_utterance(tmp_path, monkeypatch):
    service = controlled_worker(tmp_path, monkeypatch, "{'text':'invented words'}")
    try:
        result = service.transcribe(bytes(32000))
        assert result['text'] == ''
        assert service._process is None
    finally:
        service.close()
