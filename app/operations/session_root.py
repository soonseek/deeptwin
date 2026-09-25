"""Deployment-only root genesis, recovery maintenance and read-only serving verification.

The handle deliberately exposes neither key bytes nor a general purpose MAC.

Layout. Epoch 1 is the flat `initial_genesis` pair `root.key` + `manifest.json` in the root
directory. A recovery (control plane stopped) never rewrites it: it adds
`generations/<generation_id>/{root.key, manifest.json, recovery-request.json,
recovery-receipt.json}` for epoch N+1 and then names that generation in `current`, written
by atomic rename. Opening walks `current` back through every recovered parent to the flat
genesis and refuses any other member, so a half-written maintenance, a stray generation or
a rolled-back pointer fails closed until maintenance is re-run.
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


_FLAT = frozenset({"root.key", "manifest.json"})
_LAYOUT = frozenset({*_FLAT, "generations", "current"})
_RECOVERED = frozenset({*_FLAT, "recovery-request.json", "recovery-receipt.json"})
_V1_FIELDS = frozenset({"schema_version", "generation_id", "key_id", "instance_id",
                        "origin_profile_digest", "recovery_epoch", "created_at", "state",
                        "integrity_tag"})
_V2_FIELDS = _V1_FIELDS | {"parent_generation_id", "recovery_receipt_sha256"}
_HEX_64 = re.compile(r"[0-9a-f]{64}")


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
    domain = ("deeptwin-session-root-manifest-v2" if manifest["schema_version"] == "session-root-v2"
              else "deeptwin-session-root-manifest-v1")
    return canonical_json({"domain": domain, "manifest": manifest})


_HANDLE_ISSUER = object()


class SessionRootHandle:
    __slots__ = ("__key", "_closed", "_profile", "manifest_digest", "receipt", "recovery")

    def __init__(self, key, manifest, profile, *, recovery=None, _issuer=None):
        if _issuer is not _HANDLE_ISSUER:
            raise _bad()
        self.__key = key
        self.receipt = MappingProxyType({k: v for k, v in manifest.items()
                                        if k != "integrity_tag"})
        self.manifest_digest = sha256(canonical_json(manifest)).hexdigest()
        self._profile = profile
        # the public request/receipt bytes that produced a recovered generation (never a
        # secret); None for the initial genesis
        self.recovery = None if recovery is None else MappingProxyType(dict(recovery))
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


def _manifest(fd, *, profile, expected_uid, expected_gid):
    """One generation's verified key and manifest; the caller checks its place in the chain."""
    key = _read(fd, "root.key", expected_uid, expected_gid, 32)
    raw = _read(fd, "manifest.json", expected_uid, expected_gid, 4096)
    if len(key) != 32:
        raise _bad()
    value = json.loads(raw.decode("utf-8"))
    if type(value) is not dict or canonical_json(value) != raw:
        raise _bad()
    if value.get("schema_version") == "session-root-v1":
        if (set(value) != _V1_FIELDS or value["state"] != "initial_genesis"
                or type(value["recovery_epoch"]) is not int or value["recovery_epoch"] != 1):
            raise _bad()
    elif value.get("schema_version") == "session-root-v2":
        from ..deployment.recovery_contracts import recovery_key_id

        if (set(value) != _V2_FIELDS or value["state"] != "recovered"
                or type(value["recovery_epoch"]) is not int or value["recovery_epoch"] < 2
                or type(value["recovery_receipt_sha256"]) is not str
                or _HEX_64.fullmatch(value["recovery_receipt_sha256"]) is None
                or str(UUID(value["parent_generation_id"])) != value["parent_generation_id"]
                or value["parent_generation_id"] == value["generation_id"]
                or value["key_id"] != recovery_key_id(value["generation_id"])):
            raise _bad()
    else:
        raise _bad()
    if (value["instance_id"] != profile.instance_id
            or value["origin_profile_digest"] != profile.digest
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
    return key, value


def _child(fd, name, uid, gid):
    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
    try:
        _metadata(child, uid, gid, 0o700, directory=True)
        return child
    except BaseException:
        os.close(child)
        raise


def _pointer(fd, uid, gid):
    raw = _read(fd, "current", uid, gid, 256)
    value = json.loads(raw.decode("utf-8"))
    if (type(value) is not dict or set(value) != {"generation_id", "recovery_epoch"}
            or canonical_json(value) != raw or type(value["recovery_epoch"]) is not int
            or value["recovery_epoch"] < 2 or str(UUID(value["generation_id"])) != value["generation_id"]):
        raise _bad()
    return value


def _recovered(fd, generation_id, epoch, *, profile, expected_uid, expected_gid):
    """One recovered generation directory, bound to the receipt stored beside it."""
    from ..deployment.recovery_contracts import (
        manifest_core_sha256,
        parse_recovery_receipt,
        recovered_manifest_core,
    )

    if set(os.listdir(fd)) != _RECOVERED:
        raise _bad()
    key, value = _manifest(fd, profile=profile, expected_uid=expected_uid, expected_gid=expected_gid)
    request = _read(fd, "recovery-request.json", expected_uid, expected_gid, 4096)
    raw = _read(fd, "recovery-receipt.json", expected_uid, expected_gid, 8192)
    receipt = parse_recovery_receipt(raw)
    core = {k: v for k, v in value.items() if k not in {"integrity_tag", "recovery_receipt_sha256"}}
    if (value["schema_version"] != "session-root-v2" or value["generation_id"] != generation_id
            or value["recovery_epoch"] != epoch
            or value["recovery_receipt_sha256"] != sha256(raw).hexdigest()
            or core != recovered_manifest_core(receipt, profile=profile)
            or receipt["new_manifest_sha256"] != manifest_core_sha256(core)):
        raise _bad()
    return key, value, {"request": request, "receipt": raw}, receipt


def _current(fd, *, profile, expected_uid, expected_gid, pending=None):
    """The current generation of an opened root directory: (key, manifest, recovery).

    Serving (`pending` None) accepts only a complete layout. Maintenance names the one
    generation it may be completing, so an interrupted earlier run of the same advance
    (its generation written, `current` not yet moved) is still readable to it.
    """
    names = set(os.listdir(fd))
    if pending is not None:
        names.discard("current.next")
    if names == _FLAT or (pending is not None and names == _FLAT | {"generations"}):
        key, value = _manifest(fd, profile=profile, expected_uid=expected_uid, expected_gid=expected_gid)
        if value["schema_version"] != "session-root-v1":
            raise _bad()
        if "generations" in names:
            generations = _child(fd, "generations", expected_uid, expected_gid)
            try:
                if not set(os.listdir(generations)) <= {pending}:
                    raise _bad()
            finally:
                os.close(generations)
        return key, value, None
    if names != _LAYOUT:
        raise _bad()
    pointer = _pointer(fd, expected_uid, expected_gid)
    generations = _child(fd, "generations", expected_uid, expected_gid)
    try:
        members = set(os.listdir(generations))
        seen, result = set(), None
        generation_id, epoch = pointer["generation_id"], pointer["recovery_epoch"]
        while epoch >= 2:
            if generation_id in seen or generation_id not in members:
                raise _bad()
            child = _child(generations, generation_id, expected_uid, expected_gid)
            try:
                key, value, recovery, receipt = _recovered(
                    child, generation_id, epoch, profile=profile,
                    expected_uid=expected_uid, expected_gid=expected_gid)
            finally:
                os.close(child)
            if result is None:
                result = (key, value, recovery)
            seen.add(generation_id)
            parent = value["parent_generation_id"]
            if receipt["previous_generation_id"] != parent or receipt["previous_epoch"] != epoch - 1:
                raise _bad()
            generation_id, epoch = parent, epoch - 1
        # every recovered generation is on the chain; nothing else may sit beside them
        if seen != members and not (pending is not None and members - seen == {pending}):
            raise _bad()
        _, genesis = _manifest(fd, profile=profile, expected_uid=expected_uid, expected_gid=expected_gid)
        if genesis["schema_version"] != "session-root-v1" or genesis["generation_id"] != generation_id:
            raise _bad()
        return result
    finally:
        os.close(generations)


def _verify(fd, *, profile, recovery_epoch, expected_uid, expected_gid):
    if type(profile) is not OriginProfile or type(recovery_epoch) is not int or recovery_epoch < 1:
        raise _bad()
    key, value, recovery = _current(fd, profile=profile, expected_uid=expected_uid,
                                    expected_gid=expected_gid)
    # the deployment configuration names the epoch; a root at any other epoch (a rollback
    # or an unconfigured advance) never serves
    if value["recovery_epoch"] != recovery_epoch:
        raise _bad()
    return SessionRootHandle(key, value, profile, recovery=recovery, _issuer=_HANDLE_ISSUER)


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


def _write_new(fd, name, data, uid, gid):
    child = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400, dir_fd=fd)
    try:
        _metadata(child, uid, gid, 0o400)
        view = memoryview(data)
        while view:
            view = view[os.write(child, view):]
        os.fsync(child)
    finally:
        os.close(child)


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
                _write_new(fd, name, data, expected_uid, expected_gid)
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


def advance_session_root(directory, *, profile, receipt_bytes, request_bytes, trust_bytes,
                         expected_uid, expected_gid):
    """`session-root-maintenance`: advance the stopped root from epoch N to exactly N+1.

    Only a verified recovery receipt whose `previous_*` names the exact current generation
    advances; the new generation is written O_EXCL beside the old one and then named in
    `current` by atomic rename. Re-running over the already-advanced state is a verify-only
    no-op; a complete new generation left by a crash before the rename is verified and then
    named; any other existing state fails closed and is never replaced.
    """
    from ..deployment.receipt_contracts import ReceiptWireError
    from ..deployment.recovery_contracts import (
        recovered_manifest_core,
        verify_recovery_receipt,
    )

    if type(profile) is not OriginProfile or any(
            type(value) is not bytes for value in (receipt_bytes, request_bytes, trust_bytes)):
        raise _bad()
    fd = generations = None
    try:
        receipt = verify_recovery_receipt(receipt_bytes, request_bytes=request_bytes,
                                          trust_bytes=trust_bytes, profile=profile)
        new_id, new_epoch = receipt["new_generation_id"], receipt["new_epoch"]
        fd = _directory(directory, expected_uid, expected_gid)
        _, value, _ = _current(fd, profile=profile, expected_uid=expected_uid,
                               expected_gid=expected_gid, pending=new_id)
        current_digest = sha256(canonical_json(value)).hexdigest()
        if value["generation_id"] == new_id:
            # already advanced by this very receipt: verify-only
            if (value["recovery_epoch"] != new_epoch
                    or value["recovery_receipt_sha256"] != sha256(receipt_bytes).hexdigest()
                    or value["parent_generation_id"] != receipt["previous_generation_id"]):
                raise _bad()
            return {k: v for k, v in value.items() if k != "integrity_tag"}
        if (value["recovery_epoch"] != receipt["previous_epoch"]
                or value["generation_id"] != receipt["previous_generation_id"]
                or current_digest != receipt["previous_manifest_sha256"]):
            raise _bad()
        if "generations" not in os.listdir(fd):
            os.mkdir("generations", 0o700, dir_fd=fd)
            os.fsync(fd)
        generations = _child(fd, "generations", expected_uid, expected_gid)
        if new_id in os.listdir(generations):
            # a crash after the generation was written but before `current` moved: only a
            # complete, verifying generation for this receipt is named, never repaired
            child = _child(generations, new_id, expected_uid, expected_gid)
            try:
                _, _, recovery, _ = _recovered(child, new_id, new_epoch, profile=profile,
                                               expected_uid=expected_uid, expected_gid=expected_gid)
            finally:
                os.close(child)
            if recovery != {"request": request_bytes, "receipt": receipt_bytes}:
                raise _bad()
        else:
            os.mkdir(new_id, 0o700, dir_fd=generations)
            os.fsync(generations)
            child = _child(generations, new_id, expected_uid, expected_gid)
            try:
                if os.listdir(child):
                    raise _bad()
                new_key = secrets.token_bytes(32)
                manifest = {**recovered_manifest_core(receipt, profile=profile),
                            "recovery_receipt_sha256": sha256(receipt_bytes).hexdigest()}
                manifest["integrity_tag"] = _b64(hmac.digest(new_key, _manifest_preimage(manifest), "sha256"))
                for name, data in (("root.key", new_key), ("manifest.json", canonical_json(manifest)),
                                   ("recovery-request.json", request_bytes),
                                   ("recovery-receipt.json", receipt_bytes)):
                    _write_new(child, name, data, expected_uid, expected_gid)
                new_key = None
                os.fsync(child)
            finally:
                os.close(child)
        # `current.next` is never read; a leftover from an interrupted rename is discarded
        try:
            os.unlink("current.next", dir_fd=fd)
        except FileNotFoundError:
            pass
        _write_new(fd, "current.next", canonical_json({"generation_id": new_id,
                                                       "recovery_epoch": new_epoch}),
                   expected_uid, expected_gid)
        os.rename("current.next", "current", src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
        handle = _verify(fd, profile=profile, recovery_epoch=new_epoch,
                         expected_uid=expected_uid, expected_gid=expected_gid)
        result = dict(handle.receipt)
        handle.close()
        return result
    except (OSError, ValueError, TypeError, KeyError, ReceiptWireError):
        raise _bad() from None
    finally:
        if generations is not None:
            os.close(generations)
        if fd is not None:
            os.close(fd)
