"""Deployment-only root genesis and read-only serving verification.

The handle deliberately exposes neither key bytes nor a general purpose MAC.
"""
import hmac
import json
import os
import re
import secrets
import stat
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from uuid import UUID, uuid4

from ..domain.refs import canonical_json
from .setup import OriginProfile, parse_base64url_32


class SessionRootError(ValueError):
    """Closed root startup failure; contains no secret or filesystem detail."""


def _bad():
    return SessionRootError("Session root is unavailable or invalid")


def _b64(value):
    return urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _metadata(fd, uid, gid, mode, *, directory=False):
    value = os.fstat(fd)
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if (not kind(value.st_mode) or stat.S_IMODE(value.st_mode) != mode
            or value.st_uid != uid or value.st_gid != gid
            or (not directory and value.st_nlink != 1)):
        raise _bad()


def _directory(path, uid, gid, *, create=False):
    if type(uid) is not int or type(gid) is not int or min(uid, gid) < 0:
        raise _bad()
    path = Path(os.path.abspath(os.fspath(path)))
    # Resolve only the fixed macOS /var compatibility alias, not caller links.
    if (path.parts[1:2] == ("var",) and os.path.islink("/var")
            and os.readlink("/var") in {"private/var", "/private/var"}):
        path = Path("/private/var").joinpath(*path.parts[2:])
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open("/", flags)
    try:
        for index, part in enumerate(path.parts[1:]):
            final = index == len(path.parts) - 2
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not (create and final):
                    raise _bad() from None
                os.mkdir(part, 0o700, dir_fd=fd)
                os.fsync(fd)
                child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        _metadata(fd, uid, gid, 0o700, directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(fd, name, uid, gid, limit):
    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        _metadata(child, uid, gid, 0o400)
        data = os.read(child, limit + 1)
        if len(data) > limit:
            raise _bad()
        return data
    finally:
        os.close(child)


def _manifest_preimage(manifest):
    return canonical_json({"domain": "deeptwin-session-root-manifest-v1",
                           "manifest": manifest})


_HANDLE_ISSUER = object()


class SessionRootHandle:
    __slots__ = ("__key", "_closed", "_profile", "manifest_digest", "receipt")

    def __init__(self, key, manifest, profile, *, _issuer=None):
        if _issuer is not _HANDLE_ISSUER:
            raise _bad()
        self.__key = key
        self.receipt = MappingProxyType({k: v for k, v in manifest.items()
                                        if k != "integrity_tag"})
        self.manifest_digest = sha256(canonical_json(manifest)).hexdigest()
        self._profile = profile
        self._closed = False

    def derive_csrf(self, token_b64u):
        if self._closed:
            raise _bad()
        parse_base64url_32(token_b64u)
        body = canonical_json({"domain": "deeptwin-csrf-v1",
                               "origin_base": self._profile.origin_base,
                               "session_token_b64url": token_b64u,
                               "recovery_epoch": self.receipt["recovery_epoch"]})
        return _b64(hmac.digest(self.__key, body, "sha256"))

    def close(self):
        self.__key = b""
        self._closed = True


def _verify(fd, *, profile, recovery_epoch, expected_uid, expected_gid):
    if type(profile) is not OriginProfile or type(recovery_epoch) is not int or recovery_epoch != 1:
        raise _bad()
    if set(os.listdir(fd)) != {"root.key", "manifest.json"}:
        raise _bad()
    key = _read(fd, "root.key", expected_uid, expected_gid, 32)
    raw = _read(fd, "manifest.json", expected_uid, expected_gid, 4096)
    if len(key) != 32:
        raise _bad()
    value = json.loads(raw.decode("utf-8"))
    fields = {"schema_version", "generation_id", "key_id", "instance_id",
              "origin_profile_digest", "recovery_epoch", "created_at", "state", "integrity_tag"}
    if type(value) is not dict or set(value) != fields or canonical_json(value) != raw:
        raise _bad()
    if (value["schema_version"] != "session-root-v1" or value["state"] != "initial_genesis"
            or value["instance_id"] != profile.instance_id
            or value["origin_profile_digest"] != profile.digest
            or type(value["recovery_epoch"]) is not int or value["recovery_epoch"] != recovery_epoch
            or value["generation_id"] == value["key_id"]):
        raise _bad()
    for name in ("generation_id", "key_id"):
        if str(UUID(value[name])) != value[name]:
            raise _bad()
    timestamp = value["created_at"]
    if type(timestamp) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", timestamp):
        raise _bad()
    datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    tag = parse_base64url_32(value["integrity_tag"])
    body = {k: v for k, v in value.items() if k != "integrity_tag"}
    if not hmac.compare_digest(tag, hmac.digest(key, _manifest_preimage(body), "sha256")):
        raise _bad()
    return SessionRootHandle(key, value, profile, _issuer=_HANDLE_ISSUER)


def open_session_root(directory, *, profile, recovery_epoch, expected_uid, expected_gid):
    fd = None
    try:
        fd = _directory(directory, expected_uid, expected_gid)
        return _verify(fd, profile=profile, recovery_epoch=recovery_epoch,
                       expected_uid=expected_uid, expected_gid=expected_gid)
    except (OSError, ValueError, TypeError, KeyError):
        raise _bad() from None
    finally:
        if fd is not None:
            os.close(fd)


def initialize_session_root(directory, *, profile, recovery_epoch, expected_uid, expected_gid):
    """Initialize absent owned storage only; any existing state is verify-only."""
    if type(profile) is not OriginProfile or type(recovery_epoch) is not int or recovery_epoch != 1:
        raise _bad()
    fd = None
    try:
        fd = _directory(directory, expected_uid, expected_gid, create=True)
        if not os.listdir(fd):
            key = secrets.token_bytes(32)
            manifest = {"schema_version": "session-root-v1", "generation_id": str(uuid4()),
                        "key_id": str(uuid4()), "instance_id": profile.instance_id,
                        "origin_profile_digest": profile.digest, "recovery_epoch": recovery_epoch,
                        "created_at": datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                        "state": "initial_genesis"}
            manifest["integrity_tag"] = _b64(hmac.digest(key, _manifest_preimage(manifest), "sha256"))
            for name, data in (("root.key", key), ("manifest.json", canonical_json(manifest))):
                child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                0o400, dir_fd=fd)
                try:
                    _metadata(child, expected_uid, expected_gid, 0o400)
                    view = memoryview(data)
                    while view:
                        view = view[os.write(child, view):]
                    os.fsync(child)
                finally:
                    os.close(child)
            os.fsync(fd)
        handle = _verify(fd, profile=profile, recovery_epoch=recovery_epoch,
                         expected_uid=expected_uid, expected_gid=expected_gid)
        receipt = dict(handle.receipt)
        handle.close()
        return receipt
    except (OSError, ValueError, TypeError, KeyError):
        raise _bad() from None
    finally:
        if fd is not None:
            os.close(fd)
