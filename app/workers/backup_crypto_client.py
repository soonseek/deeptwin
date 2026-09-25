"""Control-plane side of the backup-crypto channel (T070).

This module imports no key, age or worker-service code: the control plane speaks the
typed backup stream (`backup_stream`) over the verified `cp-backup` connect and
handshake, and never opens, reads or names the backup-key volume. Each call is one
connection and one operation: `describe` (the worker's recipient and whether its key
is present), `encrypt` (typed archive in, ciphertext out) and `decrypt` (ciphertext
in, typed archive out). It is the `crypto` port of `app.operations.backup`.

Failures are closed `BackupWorkerError` codes: `worker_unavailable` (no endpoint,
refused handshake, dropped connection), `stream_invalid` (a cut, reordered or altered
stream in either direction), `key_unavailable` (the worker's backup-key volume is
missing or malformed), `decrypt_failed` (wrong key or a ciphertext that does not
authenticate), `encrypt_failed` and `request_invalid`.
"""

from __future__ import annotations

import hashlib

from . import backup_stream as stream
from . import broker

CODES = frozenset({"worker_unavailable", *stream.FAILURE_CODES})

__all__ = ["BackupCryptoClient", "BackupWorkerError"]


class BackupWorkerError(RuntimeError):
    """A closed backup-worker failure; never carries body bytes, keys or paths."""

    def __init__(self, code: str = "worker_unavailable"):
        self.code = code if code in CODES else "worker_unavailable"
        super().__init__(self.code)


class BackupCryptoClient:
    """The fixed owned client over the `cp-backup` profile."""

    __slots__ = ("_connect", "_deadline_ms")

    def __init__(self, *, _connect, deadline_ms: int = 600_000):
        if not callable(_connect) or type(deadline_ms) is not int or not 1 <= deadline_ms <= 900_000:
            raise TypeError("an owned connect and a bounded deadline are required")
        self._connect = _connect
        self._deadline_ms = deadline_ms

    @classmethod
    def for_worker(cls, configuration, *, deadline_ms: int = 600_000) -> BackupCryptoClient:
        """Each call connects as the control side of `cp-backup` under the attachment's
        requester boot label. No profile, path or peer override."""

        from . import backup_channel as profile
        from . import listener

        if type(configuration) is not profile.BackupWorkerConfiguration:
            raise TypeError("an exact backup worker configuration is required")
        configuration.check_profile()
        boot = configuration.requester_boot_id

        def connect(deadline):
            root, spec = profile.backup_channel()
            return listener.connect_authenticated(root, spec, requester_boot_id=boot, deadline=deadline)

        return cls(_connect=connect, deadline_ms=deadline_ms)

    def _call(self, *, op, key_mode, body=b"", recipient=None, identity=None) -> tuple[bytes, dict]:
        from . import listener

        if type(body) is not bytes or len(body) > stream.MAX_STREAM_BYTES:
            raise BackupWorkerError("request_invalid")
        deadline = broker.Deadline.after_ms(self._deadline_ms)
        try:
            connection = self._connect(deadline)
        except (broker.BrokerError, listener.ListenerError, OSError, ValueError):
            raise BackupWorkerError("worker_unavailable") from None
        try:
            request = {"schema": stream.REQUEST_SCHEMA, "op": op, "key_mode": key_mode,
                       "recipient": recipient, "identity": identity, "size": len(body),
                       "sha256": hashlib.sha256(body).hexdigest()}
            try:
                stream.check_request(request)
            except stream.BackupStreamError:
                raise BackupWorkerError("request_invalid") from None
            stream.write_message(connection, stream.REQUEST, request, deadline=deadline)
            del request
            stream.write_body(connection, body, deadline=deadline)
            _message_id, result = stream.read_message(connection, stream.RESULT, deadline=deadline)
            result = stream.check_result(result)
            if result["ok"] is not True:
                raise BackupWorkerError(result["code"])
            if result["op"] != op:
                raise BackupWorkerError("stream_invalid")
            output = stream.read_body(connection, size=result["size"], sha256=result["sha256"],
                                      deadline=deadline)
            return output, result
        except stream.BackupStreamError:
            raise BackupWorkerError("stream_invalid") from None
        except broker.BrokerError:
            # the connection dropped or a frame failed authentication mid-dialogue
            raise BackupWorkerError("stream_invalid") from None
        finally:
            identity = None
            try:
                connection.close()
            except (broker.BrokerError, listener.ListenerError, OSError):
                pass

    def describe(self) -> dict:
        """The worker's instance recipient (public) and that its key is present."""

        _body, result = self._call(op="describe", key_mode="instance_backup_key")
        return {"key_mode": "instance_backup_key", "recipient": result["recipient"], "key": "present"}

    def encrypt(self, archive: bytes, *, key_mode: str, recipient: str | None = None) -> bytes:
        ciphertext, _result = self._call(op="encrypt", key_mode=key_mode, body=archive,
                                         recipient=recipient if key_mode == "portable_recovery" else None)
        return ciphertext

    def decrypt(self, ciphertext: bytes, *, key_mode: str, identity: bytes | None = None) -> bytes:
        text = None
        if key_mode == "portable_recovery":
            if type(identity) is not bytes:
                raise BackupWorkerError("request_invalid")
            try:
                text = identity.decode("ascii").strip()
            except UnicodeError:
                raise BackupWorkerError("request_invalid") from None
        try:
            archive, _result = self._call(op="decrypt", key_mode=key_mode, body=ciphertext, identity=text)
        finally:
            text = None
        return archive
