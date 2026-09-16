"""Bounded developer-only owner of one ephemeral public receipt fixture session."""

import json
import os
import selectors
import shutil
import subprocess
import time
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path

import pytest

NODE_HELPER = Path(__file__).resolve().parent / "helpers/receipt_ed25519_fixtures.mjs"
NODE_OVERRIDE = "DEEPTWIN_RECEIPT_TEST_NODE"
_EXCHANGE_SECONDS = 5.0
_EOF_SECONDS = 0.5
_TERMINATE_SECONDS = 0.5
_KILL_SECONDS = 2.0
_FRAME_MAX = 131072
_STDERR_MAX = 4096


class ReceiptSessionError(RuntimeError):
    """A bounded fixture exchange or owned-child cleanup failed."""


def node_runtime(*, environ=None, which=None):
    environ = os.environ if environ is None else environ
    which = shutil.which if which is None else which
    configured = environ.get(NODE_OVERRIDE)
    candidate = configured if configured else which("node")
    if (
        type(candidate) is not str
        or not Path(candidate).is_file()
        or not os.access(candidate, os.X_OK)
    ):
        pytest.fail(
            f"Node.js prerequisite missing: set {NODE_OVERRIDE} to an executable "
            "or provide node on PATH"
        )
    return Path(candidate)


class OwnedReceiptSession:
    def __init__(self, profile):
        self._profile = profile
        self._child = None
        self._selector = None
        self._trust = None
        self._stderr = bytearray()
        self._closed = False

    def __enter__(self):
        if self._closed or self._child is not None:
            raise ReceiptSessionError("fixture session already entered or closed")
        try:
            self._child = subprocess.Popen(
                [node_runtime(), NODE_HELPER, "--session"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self._selector = selectors.DefaultSelector()
            for pipe in (self._child.stdin, self._child.stdout, self._child.stderr):
                os.set_blocking(pipe.fileno(), False)
            self._selector.register(self._child.stdout, selectors.EVENT_READ, "stdout")
            self._selector.register(self._child.stderr, selectors.EVENT_READ, "stderr")
            response = self._exchange(
                {"op": "init", "profile": self._profile.as_dict()}
            )
            if set(response) != {"trust_b64"} or type(response["trust_b64"]) is not str:
                raise ReceiptSessionError("fixture init frame invalid")
            value = response["trust_b64"]
            self._trust = urlsafe_b64decode(value + "=" * (-len(value) % 4))
            if urlsafe_b64encode(self._trust).decode().rstrip("=") != value:
                raise ReceiptSessionError("fixture init encoding invalid")
            return self
        except BaseException:
            self.close()
            raise

    @property
    def trust_bytes(self):
        if self._closed or self._trust is None:
            raise ReceiptSessionError("fixture session is not open")
        return self._trust

    def case(self, request_bytes: bytes, *, case_name: str) -> dict:
        if self._closed or self._trust is None:
            raise ReceiptSessionError("fixture session is not open")
        if type(request_bytes) is not bytes or not 1 <= len(request_bytes) <= 65536:
            raise ReceiptSessionError("fixture request invalid")
        if type(case_name) is not str or len(case_name) > 128:
            raise ReceiptSessionError("fixture case invalid")
        try:
            response = self._exchange(
                {
                    "op": "case",
                    "request_b64": urlsafe_b64encode(request_bytes)
                    .decode()
                    .rstrip("="),
                    "case": case_name,
                }
            )
            if set(response) != {"receipt_b64", "unsigned_preimage_b64"} or any(
                type(value) is not str for value in response.values()
            ):
                raise ReceiptSessionError("fixture response frame invalid")
            return response
        except BaseException:
            self.close()
            raise

    def _exchange(self, frame):
        wire = json.dumps(frame, separators=(",", ":")).encode() + b"\n"
        if len(wire) - 1 > _FRAME_MAX:
            raise ReceiptSessionError("fixture input overflow")
        deadline = time.monotonic() + _EXCHANGE_SECONDS
        pending = memoryview(wire)
        output = bytearray()
        self._selector.register(self._child.stdin, selectors.EVENT_WRITE, "stdin")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ReceiptSessionError("fixture exchange deadline exceeded")
            for key, _ in self._selector.select(remaining):
                if time.monotonic() >= deadline:
                    raise ReceiptSessionError("fixture exchange deadline exceeded")
                if key.data == "stdin":
                    try:
                        written = os.write(key.fd, pending[:65536])
                    except BlockingIOError:
                        continue
                    except BrokenPipeError as error:
                        raise ReceiptSessionError("fixture input EOF") from error
                    pending = pending[written:]
                    if not pending:
                        self._selector.unregister(self._child.stdin)
                    continue
                try:
                    chunk = os.read(key.fd, 4096)
                except BlockingIOError:
                    continue
                if key.data == "stderr":
                    self._stderr.extend(chunk[: _STDERR_MAX - len(self._stderr)])
                    if not chunk:
                        self._selector.unregister(key.fileobj)
                    continue
                if not chunk:
                    raise ReceiptSessionError("fixture stdout EOF")
                output.extend(chunk)
                boundary = output.find(b"\n")
                if len(output) > _FRAME_MAX + 1 or boundary > _FRAME_MAX:
                    raise ReceiptSessionError("fixture output overflow")
                if boundary >= 0:
                    if pending or boundary != len(output) - 1:
                        raise ReceiptSessionError("fixture unexpected response frame")
                    try:
                        response = json.loads(output)
                    except (ValueError, UnicodeError) as error:
                        raise ReceiptSessionError(
                            "fixture response JSON invalid"
                        ) from error
                    if type(response) is not dict:
                        raise ReceiptSessionError("fixture response object invalid")
                    return response
                if len(output) > _FRAME_MAX:
                    raise ReceiptSessionError("fixture output overflow")

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._trust = None
        child = self._child
        if child is None:
            return
        try:
            child.stdin.close()
            try:
                child.wait(timeout=_EOF_SECONDS)
            except subprocess.TimeoutExpired:
                child.terminate()
                try:
                    child.wait(timeout=_TERMINATE_SECONDS)
                except subprocess.TimeoutExpired:
                    child.kill()
                    try:
                        child.wait(timeout=_KILL_SECONDS)
                    except subprocess.TimeoutExpired as error:
                        raise ReceiptSessionError(
                            "fixture owned child reap failed"
                        ) from error
        finally:
            if self._selector is not None:
                self._selector.close()
            for pipe in (child.stdin, child.stdout, child.stderr):
                pipe.close()

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()
