"""Explicit app preparation, never imported/called by status or transcription.

Public release digest: GitHub release asset 449112012 (v1.8.7).
Public model digest: ggerganov/whisper.cpp Hugging Face ggml-base.bin LFS oid.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile


ARCHIVE_URL = 'https://github.com/ggml-org/whisper.cpp/releases/download/v1.8.7/whisper-v1.8.7-xcframework.zip'
ARCHIVE_SHA256 = '501076a091bf4b2d76ec92df9dd13278382dfb266b82bbd438c210a21c10b84c'
MODEL_URL = 'https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin'
MODEL_SHA256 = '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe'
ARCHIVE_SIZE = 50_438_532
MODEL_SIZE = 147_951_465


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download_verified(url, destination, digest, size):
    destination = Path(destination)
    if destination.is_symlink():
        raise ValueError('Unsafe artifact path')
    if destination.exists():
        if destination.stat().st_size == size and sha256(destination) == digest:
            return
        raise ValueError('Existing artifact differs; it was not replaced')
    handle, temporary = tempfile.mkstemp(prefix='.download-', dir=destination.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(handle, 'wb') as output, urllib.request.urlopen(url, timeout=30) as response:
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > size:
                    raise ValueError('Artifact exceeds published size')
                output.write(chunk)
        if count != size or sha256(temporary) != digest:
            raise ValueError('Artifact does not match published digest')
        temporary.chmod(0o600)
        # Hard link publishes without overwriting an existing path.
        os.link(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def setup(runtime_dir):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise RuntimeError('This preparation targets Apple Silicon macOS only')
    root = Path(runtime_dir).absolute()
    if any(path.is_symlink() for path in (root, *root.parents)):
        raise ValueError('Runtime path cannot contain symlinks')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    root.chmod(0o700)
    if (root / 'manifest.json').exists() or (root / 'v1.8.7').exists():
        raise ValueError('Runtime already exists; no files were replaced')
    archive = root / 'whisper-v1.8.7-xcframework.zip'
    download_verified(ARCHIVE_URL, archive, ARCHIVE_SHA256, ARCHIVE_SIZE)
    with tempfile.TemporaryDirectory(prefix='.prepare-', dir=root) as temp:
        stage = Path(temp)
        prefix = 'build-apple/whisper.xcframework/macos-arm64_x86_64/whisper.framework/Versions/A/'
        framework = stage / 'whisper.framework'
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                if not entry.filename.startswith(prefix) or entry.is_dir():
                    continue
                name = entry.filename[len(prefix):]
                if '..' in Path(name).parts or Path(name).is_absolute() or entry.file_size > 100_000_000:
                    raise ValueError('Unsafe framework archive')
                # Only regular files from the fixed Versions/A prefix, no archive symlinks.
                if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('Unexpected framework link')
                target = framework / 'Versions/A' / name
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(entry) as source, target.open('xb') as output:
                    shutil.copyfileobj(source, output)
        source = Path(__file__).resolve().parents[1] / 'native/speech_worker.cpp'
        binary = stage / 'speech-worker'
        subprocess.run(['/usr/bin/clang++', '-std=c++17', '-O2', str(source),
                        '-I', str(framework / 'Versions/A/Headers'),
                        str(framework / 'Versions/A/whisper'), '-Wl,-rpath,@executable_path',
                        '-o', str(binary)], check=True, timeout=120)
        # Keep the verified framework bytes unchanged. The release's install
        # name uses Current; this minimal package keeps only the real A directory.
        subprocess.run(['/usr/bin/install_name_tool', '-change',
                        '@rpath/whisper.framework/Versions/Current/whisper',
                        '@rpath/whisper.framework/Versions/A/whisper', str(binary)],
                       check=True, timeout=10)
        binary.chmod(0o700)
        model = stage / 'ggml-base.bin'
        download_verified(MODEL_URL, model, MODEL_SHA256, MODEL_SIZE)
        files = {'v1.8.7/' + str(path.relative_to(stage)): sha256(path)
                 for path in stage.rglob('*') if path.is_file()}
        manifest = {'version': 1, 'engine': 'whisper.cpp', 'engine_version': '1.8.7',
                    'model': 'base', 'model_sha256': MODEL_SHA256,
                    'worker': 'v1.8.7/speech-worker', 'model_file': 'v1.8.7/ggml-base.bin',
                    'library': 'v1.8.7/whisper.framework/Versions/A/whisper', 'files': files,
                    'sources': {'archive': {'url': ARCHIVE_URL, 'sha256': ARCHIVE_SHA256, 'size': ARCHIVE_SIZE},
                                'model': {'url': MODEL_URL, 'sha256': MODEL_SHA256, 'size': MODEL_SIZE}},
                    'worker_source_sha256': sha256(source), 'platform': 'macOS-arm64'}
        os.rename(stage, root / 'v1.8.7')
        with (root / 'manifest.json').open('x') as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
        (root / 'manifest.json').chmod(0o600)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Explicitly prepare local speech; downloads public engine/model only')
    parser.add_argument('--runtime-dir', type=Path, required=True)
    args = parser.parse_args()
    setup(args.runtime_dir)
    print('Local speech engine prepared; no microphone was used.')
