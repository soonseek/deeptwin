"""Closed projection codec and Linux no-clobber publication observations only."""

import ctypes
import errno
import os
import re
from base64 import urlsafe_b64encode
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.domain.refs import DomainContractError, EntityRef
from app.operations.setup import OriginProfile, SetupContractError, parse_base64url_32

from . import contracts as c
from . import files as f
from . import mounts as m


@dataclass(frozen=True, slots=True)
class Projection:
    role: str
    request_digest: str
    payload_sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class PublicationObservation:
    role: str
    request_digest: str
    payload_sha256: str
    size_bytes: int
    file_identity: f.FileIdentity


@dataclass(slots=True)
class _StagedFile:
    directory: f.Directory
    name: str
    fd: int
    signature: tuple
    closed: bool = False

    def close(self):
        if not self.closed:
            self.closed = True
            f.close_fd(self.fd)


def _timestamp(value):
    if (
        type(value) is not str
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z", value
        )
        is None
    ):
        raise c.DeploymentSourceError()
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        raise c.DeploymentSourceError() from None


def validate_projection(
    *, role: str, request_digest: str, payload: bytes, profile: OriginProfile
) -> Projection:
    """Check common file shape/hash/binding, never owner or kind-specific effect authority."""
    if (
        type(role) is not str
        or role not in ("request", "cancel")
        or type(profile) is not OriginProfile
    ):
        raise c.DeploymentSourceError()
    try:
        parse_base64url_32(request_digest)
        data = c.parse(
            payload, cap=65536 if role == "request" else 4096, depth=32, items=10000
        )
        common = (
            "schema domain request_id request_digest instance_id origin_profile_digest "
        )
        c.fields(
            data,
            common
            + (
                "kind request_nonce effect_payload preconditions created_by created_at expires_at"
                if role == "request"
                else "lifecycle_revision cancelled_at"
            ),
        )
        schema = (
            "deployment-request-v1"
            if role == "request"
            else "deployment-cancellation-v1"
        )
        origin = (
            urlsafe_b64encode(bytes.fromhex(profile.digest))
            .rstrip(b"=")
            .decode("ascii")
        )
        if (
            data["schema"] != schema
            or data["domain"] != f"deeptwin-{schema}"
            or data["request_digest"] != request_digest
            or data["instance_id"] != profile.instance_id
            or data["origin_profile_digest"] != origin
        ):
            raise c.DeploymentSourceError()
        c.uuid(data["request_id"])
        if role == "request":
            parse_base64url_32(data["request_nonce"])
            if (
                data["kind"] != "extension_stage"
                or type(data["preconditions"]) is not dict
                or data["preconditions"]
                or type(data["effect_payload"]) is not dict
                or EntityRef.from_dict(data["created_by"]).kind != "actor"
                or _timestamp(data["created_at"]) >= _timestamp(data["expires_at"])
            ):
                raise c.DeploymentSourceError()
            preimage = c.encode(
                {key: value for key, value in data.items() if key != "request_digest"}
            )
            expected = (
                urlsafe_b64encode(bytes.fromhex(c.digest(preimage)))
                .rstrip(b"=")
                .decode("ascii")
            )
            if expected != request_digest:
                raise c.DeploymentSourceError()
        else:
            c.integer(data["lifecycle_revision"], 2, 2)
            _timestamp(data["cancelled_at"])
        return Projection(role, request_digest, c.digest(payload), len(payload))
    except (DomainContractError, SetupContractError):
        raise c.DeploymentSourceError() from None


def validate_cancellation_v2(
    *, request_digest: str, payload: bytes, profile: OriginProfile
) -> Projection:
    """Validate the one pure v2 marker without adding publication authority."""
    from .prepare_contracts import DeploymentPrepareError
    from .prepare_v2_contracts import parse_cancellation_v2

    try:
        parse_cancellation_v2(
            request_digest=request_digest,
            payload=payload,
            profile=profile,
        )
        return Projection("cancel", request_digest, c.digest(payload), len(payload))
    except DeploymentPrepareError:
        raise c.DeploymentSourceError() from None


def _validate_retained_projection(
    *, role: str, request_digest: str, payload: bytes, profile: OriginProfile
) -> Projection:
    """Dispatch only the two fixed cancellation marker versions in retained E."""
    if role == "request":
        return validate_projection(
            role=role,
            request_digest=request_digest,
            payload=payload,
            profile=profile,
        )
    if role != "cancel":
        raise c.DeploymentSourceError()
    value = c.parse(payload, cap=4096, depth=4, items=32)
    if type(value) is not dict:
        raise c.DeploymentSourceError()
    schema = value.get("schema")
    if schema == "deployment-cancellation-v1":
        return validate_projection(
            role=role,
            request_digest=request_digest,
            payload=payload,
            profile=profile,
        )
    if schema == "deployment-cancellation-v2":
        return validate_cancellation_v2(
            request_digest=request_digest,
            payload=payload,
            profile=profile,
        )
    raise c.DeploymentSourceError()


def _rename_noreplace(directory_fd, stage, final):
    m.native_platform()
    try:
        function = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError):
        raise c.PublicationUnavailable() from None
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    if (
        function(directory_fd, os.fsencode(stage), directory_fd, os.fsencode(final), 1)
        != 0
    ):
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise FileExistsError(code, "publication_exists")
        raise c.PublicationUnavailable()


def _write_all(fd, payload):
    offset = 0
    while offset < len(payload):
        written = os.write(fd, payload[offset:])
        if written <= 0:
            raise c.PublicationUnavailable()
        offset += written


def _existing_for_policy(directory, filename, payload, *, policy):
    if type(directory) is not f.Directory or type(policy) is not f._NamespacePolicy:
        raise c.DeploymentSourceError()
    fd = f.open_regular(
        directory.fd,
        filename,
        uid=policy.writer_uid,
        gid=policy.pair_gid,
        mode=0o440,
        cap=policy.payload_cap,
    )
    try:
        before = f.signature(f.stat_fd(fd))
        if (
            f.read_exact(fd, policy.payload_cap) != payload
            or f.signature(f.stat_at(directory.fd, filename)) != before
        ):
            raise c.DeploymentSourceError()
        os.fsync(fd)
        os.fsync(directory.fd)
        if (
            f.signature(f.stat_at(directory.fd, filename)) != before
            or f.signature(f.stat_fd(fd)) != before
        ):
            raise c.DeploymentSourceError()
        result = f.identity(f.stat_fd(fd))
    except BaseException:
        try:
            f.close_fd(fd)
        except BaseException:  # noqa: BLE001, S110 - preserve the active primary
            pass
        raise
    else:
        f.close_fd(fd)
        return result


def _existing(directory, filename, payload, cap):
    policy = f._NamespacePolicy(20102, 20102, 21201, 16, 32, cap)
    return _existing_for_policy(directory, filename, payload, policy=policy)


def _stage_payload(directory, payload, *, policy):
    if (
        type(directory) is not f.Directory
        or type(payload) is not bytes
        or type(policy) is not f._NamespacePolicy
    ):
        raise c.DeploymentSourceError()
    name = f".stage-{uuid4()}.tmp"
    fd = -1
    result = None
    try:
        fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory.fd,
        )
        _write_all(fd, payload)
        os.fchown(fd, -1, policy.pair_gid)
        os.fchmod(fd, 0o440)
        os.fsync(fd)
        info = f.stat_fd(fd)
        f.validate_regular(
            info,
            uid=policy.writer_uid,
            gid=policy.pair_gid,
            mode=0o440,
            cap=policy.payload_cap,
        )
        observed = f.signature(info)
        if f.signature(f.stat_at(directory.fd, name)) != observed:
            raise c.DeploymentSourceError()
        result = _StagedFile(directory, name, fd, observed)
        fd = -1
    except BaseException:
        try:
            if result is not None:
                result.close()
            else:
                f.close_fd(fd)
        except BaseException:  # noqa: BLE001, S110 - preserve the active primary
            pass
        raise
    return result


def _commit_stage(directory, stage, filename):
    if (
        type(directory) is not f.Directory
        or type(stage) is not _StagedFile
        or stage.closed
        or stage.directory is not directory
        or f.signature(f.stat_fd(stage.fd)) != stage.signature
        or f.signature(f.stat_at(directory.fd, stage.name)) != stage.signature
    ):
        raise c.DeploymentSourceError()
    try:
        _rename_noreplace(directory.fd, stage.name, filename)
    except FileExistsError:
        os.fsync(directory.fd)
        raise
    os.fsync(directory.fd)


def _publish_projection(source, *, projection, payload):
    from .sources import ExchangeSource

    if type(source) is not ExchangeSource or getattr(source, "_closed", True):
        raise c.DeploymentSourceError()
    source.recheck_current()
    directory = source._namespaces[projection.role]
    policy = (
        f._REQUEST_NAMESPACE if projection.role == "request" else f._CANCEL_NAMESPACE
    )
    filename = parse_base64url_32(projection.request_digest).hex() + ".json"
    stage = None
    try:
        scan = f._scan_namespace(directory, policy=policy)
        if filename not in {entry.name for entry in scan.finals}:
            if (
                len(scan.finals) >= policy.final_limit
                or scan.stages >= policy.stage_limit
            ):
                raise c.DeploymentSourceError()
            stage = _stage_payload(directory, payload, policy=policy)
            source.recheck_current()
            try:
                _commit_stage(directory, stage, filename)
            except FileExistsError:
                pass
        identity = _existing_for_policy(directory, filename, payload, policy=policy)
        source.recheck_current()
        return PublicationObservation(
            projection.role,
            projection.request_digest,
            projection.payload_sha256,
            projection.size_bytes,
            identity,
        )
    except OSError:
        raise c.PublicationUnavailable() from None
    finally:
        if stage is not None:
            stage.close()


def publish(source, *, role, request_digest, payload):
    from .sources import ExchangeSource

    if type(source) is not ExchangeSource or getattr(source, "_closed", True):
        raise c.DeploymentSourceError()
    projection = validate_projection(
        role=role,
        request_digest=request_digest,
        payload=payload,
        profile=source._profile,
    )
    return _publish_projection(source, projection=projection, payload=payload)


def publish_cancellation_v2(source, *, request_digest, payload):
    from .sources import ExchangeSource

    if type(source) is not ExchangeSource or getattr(source, "_closed", True):
        raise c.DeploymentSourceError()
    projection = validate_cancellation_v2(
        request_digest=request_digest,
        payload=payload,
        profile=source._profile,
    )
    return _publish_projection(source, projection=projection, payload=payload)
