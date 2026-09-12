#!/usr/bin/env python3
"""Deterministically derive DeepTwin's PCM-only faster-whisper wheel.

The exact upstream wheel is an immutable T089 build input. The derived wheel is a reproducible T089
intermediate input that T081 later embeds after re-verification: it rejects media decoding, VAD
inference, in-memory/remote model sources, tokenizer fallback downloads and all runtime downloads.
It intentionally contains no PyAV, FFmpeg, ONNX Runtime or Silero model payload. Run this script in
a networkless build step after the input wheel hash is verified.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import io
from pathlib import Path, PurePosixPath
import zipfile


UPSTREAM_SHA256 = "79a66ad50688c0b794dd501dc340a736992a6342f7f95e5811be60b5224a26a7"
UPSTREAM_DIST_INFO = "faster_whisper-1.2.1.dist-info"
DOWNSTREAM_DIST_INFO = "deeptwin_faster_whisper-1.2.1+deeptwin.1.dist-info"
OUTPUT_FILENAME = "deeptwin_faster_whisper-1.2.1+deeptwin.1-py3-none-any.whl"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one exact patch target, found {count}")
    return text.replace(old, new, 1)


def _load_verified_wheel(path: Path) -> dict[str, bytes]:
    raw = path.read_bytes()
    actual = _sha256(raw)
    if actual != UPSTREAM_SHA256:
        raise ValueError(f"unexpected upstream wheel SHA-256: {actual}")
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(io.BytesIO(raw), "r") as archive:
        for info in archive.infolist():
            name = info.filename
            pure = PurePosixPath(name)
            if pure.is_absolute() or ".." in pure.parts or name in entries:
                raise ValueError(f"unsafe or duplicate wheel member: {name}")
            if not info.is_dir():
                entries[name] = archive.read(info)
    return entries


def _patch_audio(source: bytes) -> bytes:
    text = source.decode("utf-8")
    marker = "def pad_or_trim(array, length: int = 3000, *, axis: int = -1):\n"
    if text.count(marker) != 1:
        raise ValueError("audio.py: pad_or_trim boundary changed")
    preserved = marker + text.split(marker, 1)[1]
    prefix = '''"""DeepTwin PCM-only downstream audio boundary.

The browser/worker contract supplies a validated contiguous mono float32 NumPy waveform. Media
file and BinaryIO decoding are deliberately absent so the worker does not ship PyAV/FFmpeg.
"""

from typing import BinaryIO, Union

import numpy as np


def decode_audio(
    input_file: Union[str, BinaryIO],
    sampling_rate: int = 16000,
    split_stereo: bool = False,
):
    raise ValueError(
        "deeptwin-faster-whisper accepts only a validated NumPy PCM waveform; "
        "file and stream decoding are disabled"
    )


'''
    return (prefix + preserved).encode("utf-8")


def _patch_transcribe(source: bytes) -> bytes:
    text = source.decode("utf-8")
    import_boundary = '''from faster_whisper.vad import (
    SpeechTimestampsMap,
    VadOptions,
    collect_chunks,
    get_speech_timestamps,
)


'''
    validators = '''from faster_whisper.vad import (
    SpeechTimestampsMap,
    VadOptions,
    collect_chunks,
    get_speech_timestamps,
)


def _validate_deeptwin_pcm(audio: np.ndarray) -> np.ndarray:
    """Accept only the exact worker-owned float32 PCM projection."""
    if not isinstance(audio, np.ndarray):
        raise ValueError("deeptwin-faster-whisper accepts only a NumPy PCM waveform")
    if audio.dtype != np.dtype("float32"):
        raise ValueError("deeptwin-faster-whisper PCM dtype must be float32")
    if audio.ndim != 1:
        raise ValueError("deeptwin-faster-whisper PCM must be one-dimensional mono audio")
    if not audio.flags.c_contiguous:
        raise ValueError("deeptwin-faster-whisper PCM must be C-contiguous")
    if audio.size == 0:
        raise ValueError("deeptwin-faster-whisper PCM must not be empty")
    if not np.isfinite(audio).all():
        raise ValueError("deeptwin-faster-whisper PCM must contain only finite samples")
    if np.any(audio < np.float32(-1.0)) or np.any(
        audio > np.float32(32767.0 / 32768.0)
    ):
        raise ValueError("deeptwin-faster-whisper PCM sample is outside the signed-16 range")
    return audio


'''
    text = _replace_once(
        text, import_boundary, validators, "install PCM validator after VAD imports"
    )
    text = _replace_once(
        text,
        "from faster_whisper.utils import download_model, format_timestamp, get_end, get_logger\n",
        "from faster_whisper.utils import format_timestamp, get_end, get_logger\n",
        "remove model downloader import",
    )
    guard_prefix = (
        "        audio = _validate_deeptwin_pcm(audio)\n"
        "        if vad_filter:\n"
        "            raise ValueError(\"VAD is disabled in deeptwin-faster-whisper\")\n\n"
    )
    for guard_target in (
        "        sampling_rate = self.model.feature_extractor.sampling_rate\n",
        "        sampling_rate = self.feature_extractor.sampling_rate\n",
    ):
        text = _replace_once(
            text, guard_target, guard_prefix + guard_target, "transcribe input boundary"
        )
    decode_target = '''        if not isinstance(audio, np.ndarray):
            audio = decode_audio(audio, sampling_rate=sampling_rate)
'''
    if text.count(decode_target) != 2:
        raise ValueError("transcribe.py: expected two upstream decode branches")
    text = text.replace(decode_target, "")
    model_target = '''        if files:
            model_path = model_size_or_path
            tokenizer_bytes = files.pop("tokenizer.json", None)
            preprocessor_bytes = files.pop("preprocessor_config.json", None)
        elif os.path.isdir(model_size_or_path):
            model_path = model_size_or_path
        else:
            model_path = download_model(
                model_size_or_path,
                local_files_only=local_files_only,
                cache_dir=download_root,
                revision=revision,
                use_auth_token=use_auth_token,
            )
'''
    model_replacement = '''        if files is not None:
            raise ValueError(
                "deeptwin-faster-whisper rejects in-memory model files"
            )
        if os.path.isdir(model_size_or_path):
            model_path = model_size_or_path
        else:
            raise ValueError(
                "deeptwin-faster-whisper requires an existing local model directory"
            )
'''
    text = _replace_once(text, model_target, model_replacement, "local model boundary")
    text = _replace_once(
        text,
        "            files=files,\n",
        "            files=None,\n",
        "disable CTranslate2 in-memory model files",
    )
    tokenizer_target = '''        else:
            self.hf_tokenizer = tokenizers.Tokenizer.from_pretrained(
                "openai/whisper-tiny" + ("" if self.model.is_multilingual else ".en")
            )
'''
    tokenizer_replacement = '''        else:
            raise ValueError(
                "the locked local model is missing tokenizer.json; remote fallback is disabled"
            )
'''
    text = _replace_once(
        text, tokenizer_target, tokenizer_replacement, "local tokenizer boundary"
    )
    text = _replace_once(
        text,
        "        vad_filter: bool = True,\n",
        "        vad_filter: bool = False,\n",
        "batched VAD-safe default",
    )
    detect_target = '''        if audio is not None:
            if vad_filter:
                speech_chunks = get_speech_timestamps(audio, vad_parameters)
                audio_chunks, chunks_metadata = collect_chunks(audio, speech_chunks)
                audio = np.concatenate(audio_chunks, axis=0)

            audio = audio[
'''
    detect_replacement = '''        if audio is not None:
            audio = _validate_deeptwin_pcm(audio)
            if vad_filter:
                raise ValueError("VAD is disabled in deeptwin-faster-whisper")

            audio = audio[
'''
    text = _replace_once(
        text, detect_target, detect_replacement, "detect-language PCM boundary"
    )
    return text.encode("utf-8")


def _patch_utils(source: bytes) -> bytes:
    text = source.decode("utf-8")
    text = _replace_once(text, "import re\n", "", "remove remote-ID parser")
    text = _replace_once(text, "import huggingface_hub\n\n", "", "remove hub import")
    start = text.find("def download_model(\n")
    end = text.find("\ndef format_timestamp(\n")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("utils.py: download_model boundary changed")
    replacement = '''def download_model(
    size_or_id: str,
    output_dir: Optional[str] = None,
    local_files_only: bool = False,
    cache_dir: Optional[str] = None,
    revision: Optional[str] = None,
    use_auth_token: Optional[Union[str, bool]] = None,
):
    raise RuntimeError(
        "runtime model downloads are disabled; use the exact read-only DeepTwin model directory"
    )

'''
    return (text[:start] + replacement + text[end + 1 :]).encode("utf-8")


def _patch_vad(source: bytes) -> bytes:
    text = source.decode("utf-8")
    text = _replace_once(text, "import functools\n", "", "remove VAD cache import")
    text = _replace_once(text, "import os\n", "", "remove VAD model path import")
    text = _replace_once(
        text,
        "from faster_whisper.utils import get_assets_path\n\n",
        "",
        "remove VAD asset helper",
    )
    marker = "@functools.lru_cache\ndef get_vad_model():\n"
    start = text.find(marker)
    if start < 0:
        raise ValueError("vad.py: model boundary changed")
    replacement = '''def get_vad_model():
    raise RuntimeError("VAD is disabled in deeptwin-faster-whisper")
'''
    return (text[:start] + replacement).encode("utf-8")


def _patch_metadata(source: bytes) -> bytes:
    text = source.decode("utf-8")
    text = _replace_once(text, "Name: faster-whisper\n", "Name: deeptwin-faster-whisper\n", "name")
    text = _replace_once(text, "Version: 1.2.1\n", "Version: 1.2.1+deeptwin.1\n", "version")
    text = _replace_once(text, "Requires-Dist: onnxruntime<2,>=1.14\n", "", "onnxruntime requirement")
    text = _replace_once(text, "Requires-Dist: av>=11\n", "", "av requirement")
    text = _replace_once(
        text, "Requires-Dist: huggingface-hub>=0.21\n", "", "huggingface-hub requirement"
    )
    text = _replace_once(
        text,
        "License-File: LICENSE\n",
        "License-File: LICENSE\nLicense-File: LICENSES/Silero-MIT.txt\n",
        "Silero license declaration",
    )
    text = "\n".join(
        line
        for line in text.split("\n")
        if not line.startswith("Provides-Extra:") and "extra == " not in line
    )
    summary = "Summary: Faster Whisper transcription with CTranslate2\n"
    if summary in text:
        text = text.replace(
            summary,
            "Summary: DeepTwin PCM-only downstream of faster-whisper 1.2.1\n",
            1,
        )
    headers, separator, _description = text.partition("\n\n")
    if not separator:
        raise ValueError("METADATA: description boundary changed")
    description = '''# deeptwin-faster-whisper

This is DeepTwin's reproducible PCM-only downstream of faster-whisper 1.2.1. It is an internal
speech-worker dependency, not an upstream replacement. The public worker boundary accepts only a
validated contiguous one-dimensional float32 waveform produced from signed 16-bit little-endian
16 kHz mono PCM. Media/file decoding, VAD, in-memory or remote model loading, tokenizer fallback
downloads and optional extras are disabled. PyAV, FFmpeg, ONNX Runtime and the Silero ONNX payload
are not included. See `DEEPTWIN_PATCH_NOTICE.txt` and the declared license files for provenance.
'''
    return (headers + "\n\n" + description).encode("utf-8")


def _patch_wheel_metadata(source: bytes) -> bytes:
    text = source.decode("utf-8")
    text = _replace_once(
        text,
        "Generator: bdist_wheel (0.45.1)\n",
        "Generator: deeptwin-downstream-wheel-builder/1\n",
        "wheel generator",
    )
    return text.encode("utf-8")


def _patch_version(source: bytes) -> bytes:
    text = source.decode("utf-8")
    text = _replace_once(
        text,
        '__version__ = "1.2.1"\n',
        '__version__ = "1.2.1+deeptwin.1"\n',
        "runtime version",
    )
    return text.encode("utf-8")


def _verify_patched_entries(entries: dict[str, bytes]) -> None:
    forbidden_members = {
        "faster_whisper/assets/silero_vad_v6.onnx",
    }
    present_forbidden = sorted(forbidden_members & entries.keys())
    if present_forbidden:
        raise ValueError(f"forbidden downstream payload remains: {present_forbidden}")

    metadata = entries[f"{DOWNSTREAM_DIST_INFO}/METADATA"].decode("utf-8")
    for forbidden in (
        "Requires-Dist: av",
        "Requires-Dist: onnxruntime",
        "Requires-Dist: huggingface-hub",
        "Provides-Extra:",
        "extra == ",
    ):
        if forbidden in metadata:
            raise ValueError(f"forbidden downstream metadata remains: {forbidden}")
    for required in (
        "Name: deeptwin-faster-whisper\n",
        "Version: 1.2.1+deeptwin.1\n",
        "License-File: LICENSES/Silero-MIT.txt\n",
    ):
        if required not in metadata:
            raise ValueError(f"required downstream metadata missing: {required.strip()}")

    transcribe = entries["faster_whisper/transcribe.py"].decode("utf-8")
    required_guards = (
        "def _validate_deeptwin_pcm(",
        "audio.dtype != np.dtype(\"float32\")",
        "audio.ndim != 1",
        "audio.flags.c_contiguous",
        "np.isfinite(audio).all()",
        "if files is not None:",
        "files=None,",
        "VAD is disabled in deeptwin-faster-whisper",
    )
    for guard in required_guards:
        if guard not in transcribe:
            raise ValueError(f"required downstream guard missing: {guard}")
    for forbidden in (
        "Tokenizers.Tokenizer.from_pretrained",
        "tokenizers.Tokenizer.from_pretrained",
        "from faster_whisper.utils import download_model",
        "files=files,",
    ):
        if forbidden in transcribe:
            raise ValueError(f"forbidden downstream path remains: {forbidden}")
    if transcribe.count("audio = _validate_deeptwin_pcm(audio)") != 3:
        raise ValueError("expected PCM validation on both transcribe paths and detect_language")

    version = entries["faster_whisper/version.py"].decode("utf-8")
    if '__version__ = "1.2.1+deeptwin.1"' not in version:
        raise ValueError("runtime package version is not the downstream identity")
    wheel = entries[f"{DOWNSTREAM_DIST_INFO}/WHEEL"].decode("utf-8")
    if "Generator: deeptwin-downstream-wheel-builder/1\n" not in wheel:
        raise ValueError("downstream wheel generator identity is missing")


def _patch_entries(entries: dict[str, bytes], silero_license: bytes) -> dict[str, bytes]:
    old_record = f"{UPSTREAM_DIST_INFO}/RECORD"
    required = {
        "faster_whisper/audio.py",
        "faster_whisper/transcribe.py",
        "faster_whisper/utils.py",
        "faster_whisper/vad.py",
        f"{UPSTREAM_DIST_INFO}/METADATA",
        f"{UPSTREAM_DIST_INFO}/WHEEL",
        f"{UPSTREAM_DIST_INFO}/LICENSE",
        old_record,
        "faster_whisper/version.py",
        "faster_whisper/assets/silero_vad_v6.onnx",
    }
    missing = sorted(required - entries.keys())
    if missing:
        raise ValueError(f"upstream wheel members changed: {missing}")

    patched: dict[str, bytes] = {}
    for name, data in entries.items():
        if name in {old_record, "faster_whisper/assets/silero_vad_v6.onnx"}:
            continue
        new_name = name.replace(UPSTREAM_DIST_INFO, DOWNSTREAM_DIST_INFO, 1)
        patched[new_name] = data

    patched["faster_whisper/audio.py"] = _patch_audio(entries["faster_whisper/audio.py"])
    patched["faster_whisper/transcribe.py"] = _patch_transcribe(
        entries["faster_whisper/transcribe.py"]
    )
    patched["faster_whisper/utils.py"] = _patch_utils(entries["faster_whisper/utils.py"])
    patched["faster_whisper/vad.py"] = _patch_vad(entries["faster_whisper/vad.py"])
    patched[f"{DOWNSTREAM_DIST_INFO}/METADATA"] = _patch_metadata(
        entries[f"{UPSTREAM_DIST_INFO}/METADATA"]
    )
    patched[f"{DOWNSTREAM_DIST_INFO}/WHEEL"] = _patch_wheel_metadata(
        entries[f"{UPSTREAM_DIST_INFO}/WHEEL"]
    )
    patched["faster_whisper/version.py"] = _patch_version(entries["faster_whisper/version.py"])
    patched[f"{DOWNSTREAM_DIST_INFO}/LICENSES/Silero-MIT.txt"] = silero_license
    patched[f"{DOWNSTREAM_DIST_INFO}/DEEPTWIN_PATCH_NOTICE.txt"] = (
        "deeptwin-faster-whisper 1.2.1+deeptwin.1\n"
        "Upstream: faster-whisper 1.2.1, Git tag v1.2.1, "
        "commit 65882eee9f5cdbeeb2d877f1131d48cf241b327d.\n"
        f"Upstream wheel SHA-256: {UPSTREAM_SHA256}.\n"
        "Changes: PCM NumPy input only; local model/tokenizer only; runtime downloads, optional "
        "extras and VAD rejected; PyAV, FFmpeg, ONNX Runtime and the Silero ONNX payload removed.\n"
        "The preserved VAD-derived source attribution remains covered by the bundled Silero MIT "
        "license even though its inference path and model payload are disabled.\n"
    ).encode("utf-8")
    _verify_patched_entries(patched)
    return patched


def _record(entries: dict[str, bytes]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    for name in sorted(entries):
        digest = base64.urlsafe_b64encode(hashlib.sha256(entries[name]).digest()).rstrip(b"=")
        writer.writerow((name, "sha256=" + digest.decode("ascii"), str(len(entries[name]))))
    writer.writerow((f"{DOWNSTREAM_DIST_INFO}/RECORD", "", ""))
    return output.getvalue().encode("utf-8")


def _write_wheel(path: Path, entries: dict[str, bytes]) -> None:
    entries = dict(entries)
    entries[f"{DOWNSTREAM_DIST_INFO}/RECORD"] = _record(entries)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name], compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_wheel", type=Path)
    parser.add_argument("output_directory", type=Path)
    args = parser.parse_args()
    license_path = Path(__file__).with_name("licenses") / "Silero-MIT.txt"
    license_bytes = license_path.read_bytes()
    # The vendored copy adds one final LF to the exact upstream license text.
    if _sha256(license_bytes) != "51c19c8be941a3fb00ccf58f0bf9053de9f7237a0b37327896eabad32dffe873":
        raise ValueError("unexpected Silero license bytes")
    entries = _patch_entries(_load_verified_wheel(args.input_wheel), license_bytes)
    args.output_directory.mkdir(parents=True, exist_ok=True)
    output = args.output_directory / OUTPUT_FILENAME
    _write_wheel(output, entries)
    print(f"{_sha256(output.read_bytes())}  {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
