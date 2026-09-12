#!/usr/bin/env python3
"""Verify a derived deeptwin-faster-whisper wheel without network access."""

from __future__ import annotations

import argparse
import ast
import base64
import csv
import hashlib
import io
from pathlib import Path
import zipfile


DIST_INFO = "deeptwin_faster_whisper-1.2.1+deeptwin.1.dist-info"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_wheel(path: Path) -> dict[str, bytes]:
    entries: dict[str, bytes] = {}
    with zipfile.ZipFile(path, "r") as archive:
        bad = archive.testzip()
        if bad is not None:
            raise ValueError(f"corrupt wheel member: {bad}")
        for info in archive.infolist():
            if not info.is_dir():
                if info.filename in entries:
                    raise ValueError(f"duplicate wheel member: {info.filename}")
                entries[info.filename] = archive.read(info)
    return entries


def verify_record(entries: dict[str, bytes]) -> None:
    record_name = f"{DIST_INFO}/RECORD"
    rows = list(csv.reader(io.StringIO(entries[record_name].decode("utf-8"))))
    seen: set[str] = set()
    for name, encoded, size in rows:
        if name in seen:
            raise ValueError(f"duplicate RECORD row: {name}")
        seen.add(name)
        if name == record_name:
            if encoded or size:
                raise ValueError("RECORD self-row must omit digest and size")
            continue
        data = entries.get(name)
        if data is None:
            raise ValueError(f"RECORD references missing member: {name}")
        expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        if encoded != f"sha256={expected}" or size != str(len(data)):
            raise ValueError(f"RECORD mismatch: {name}")
    if seen != set(entries):
        raise ValueError("RECORD/member set mismatch")


def pcm_validator_from(source: bytes):
    tree = ast.parse(source.decode("utf-8"), filename="faster_whisper/transcribe.py")
    functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_validate_deeptwin_pcm"
    ]
    if len(functions) != 1:
        raise ValueError("exactly one PCM validator is required")
    module = ast.Module(body=functions, type_ignores=[])
    ast.fix_missing_locations(module)
    import numpy as np

    namespace = {"np": np}
    exec(compile(module, "<pcm-validator>", "exec"), namespace)
    return namespace["_validate_deeptwin_pcm"], np


def verify_behavior(entries: dict[str, bytes]) -> None:
    validate, np = pcm_validator_from(entries["faster_whisper/transcribe.py"])
    maximum = np.float32(32767.0 / 32768.0)
    valid = np.ascontiguousarray(np.array([-1.0, 0.0, maximum], dtype=np.float32))
    if validate(valid) is not valid:
        raise ValueError("validator must preserve the exact valid PCM array")

    invalid = [
        np.array([0], dtype=np.int16),
        np.array([0], dtype=np.float64),
        np.array([[0]], dtype=np.float32),
        np.arange(8, dtype=np.float32)[::2],
        np.array([], dtype=np.float32),
        np.array([np.nan], dtype=np.float32),
        np.array([np.inf], dtype=np.float32),
        np.array([-1.0001], dtype=np.float32),
        np.array([1.0], dtype=np.float32),
    ]
    for index, value in enumerate(invalid):
        try:
            validate(value)
        except ValueError:
            continue
        raise ValueError(f"invalid PCM case {index} was accepted")


def verify_wheel(path: Path, behavioral: bool) -> str:
    entries = read_wheel(path)
    verify_record(entries)
    required = {
        f"{DIST_INFO}/LICENSE",
        f"{DIST_INFO}/LICENSES/Silero-MIT.txt",
        f"{DIST_INFO}/DEEPTWIN_PATCH_NOTICE.txt",
        f"{DIST_INFO}/METADATA",
        f"{DIST_INFO}/WHEEL",
        "faster_whisper/transcribe.py",
        "faster_whisper/version.py",
    }
    missing = sorted(required - set(entries))
    if missing:
        raise ValueError(f"required downstream members missing: {missing}")
    forbidden = [
        name
        for name in entries
        if name.endswith("silero_vad_v6.onnx") or name.lower().endswith((".so", ".dylib", ".dll"))
    ]
    if forbidden:
        raise ValueError(f"forbidden binary/model payload: {forbidden}")

    metadata = entries[f"{DIST_INFO}/METADATA"].decode("utf-8")
    for value in ("av", "onnxruntime", "huggingface-hub"):
        if f"Requires-Dist: {value}" in metadata:
            raise ValueError(f"forbidden direct requirement remains: {value}")
    source = entries["faster_whisper/transcribe.py"].decode("utf-8")
    if source.count("audio = _validate_deeptwin_pcm(audio)") != 3:
        raise ValueError("all waveform entry points are not guarded")
    if source.index("if files is not None:") > source.index("self.model = ctranslate2.models.Whisper("):
        raise ValueError("in-memory model rejection occurs after native model construction")
    if "files=files," in source or "tokenizers.Tokenizer.from_pretrained" in source:
        raise ValueError("remote/in-memory model path remains")
    for name, data in entries.items():
        if name.endswith(".py"):
            compile(data, name, "exec")
    if behavioral:
        verify_behavior(entries)
    return sha256(path.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path, nargs="+")
    parser.add_argument("--behavioral", action="store_true")
    args = parser.parse_args()
    digests = [verify_wheel(path, args.behavioral) for path in args.wheel]
    if len(set(digests)) != 1:
        raise ValueError(f"derived wheels differ: {digests}")
    print(f"verified {len(args.wheel)} wheel(s): sha256:{digests[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
