"""Private fixed-file observer shared by exactly the tool-v1 and provider-v2 sources.

Profiles select code-owned parsers and layouts; public factories expose no paths,
pins, callbacks or expected facts. Sampling seams remain in their owning modules.
"""

from __future__ import annotations
import os
import stat
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from ..deployment import files as f, mounts as m
from ..deployment.contracts import DeploymentSourceError, DeploymentSourceUnavailable
from ..extensions.lineage_contracts import LineageContractError
from ..extensions.provider_identity import ProviderIdentityError
from ..extensions.port_contracts import PORT_SCHEMA_SHAPES
from .broker import ChannelConfigurationError, Deadline, DeadlineExceeded


def _profile(p):
    from . import extension_metadata, provider_metadata

    if p is extension_metadata:
        return "tool-port-v1", "build-identity-v1.json"
    if p is provider_metadata:
        return "provider-port-v1", "build-identity-v2.json"
    raise TypeError("unknown fixed image profile")


def _observe_tool(deadline, *, retained, keep):
    from . import extension_metadata

    return _observe(extension_metadata, deadline, retained=retained, keep=keep)


def _observe_provider(deadline, *, retained, keep):
    from . import provider_metadata

    return _observe(provider_metadata, deadline, retained=retained, keep=keep)


# --- fixed layout ---


def _directories(p) -> tuple[Path, ...]:
    prefix = p.EXTENSION_PREFIX
    if prefix.parent.parent != p.EXTENSION_ROOT:
        raise p._MetadataInvalid()
    return (
        p.EXTENSION_ROOT,
        prefix.parent,
        prefix,
        prefix / "bin",
        prefix / "identity",
        prefix / "ports",
        prefix / "ports" / _profile(p)[0],
    )


def _leaves(p) -> tuple[tuple[Path, str, int, int], ...]:
    prefix = p.EXTENSION_PREFIX
    schemas = tuple(
        (
            prefix / "ports" / _profile(p)[0],
            f"{role}.schema.json",
            p._LEAF_MODE,
            p._SCHEMA_CAP,
        )
        for role in PORT_SCHEMA_SHAPES
    )
    return (
        (prefix / "bin", "worker", p._WORKER_MODE, p._WORKER_CAP),
        (prefix / "identity", _profile(p)[1], p._LEAF_MODE, p._IDENTITY_CAP),
        *schemas,
    )


@dataclass(frozen=True, slots=True)
class _Observation:
    platform: str
    uid: int
    gid: int
    directories: tuple[f.FileIdentity, ...]
    leaves: tuple[tuple, ...]
    identity_bytes: bytes
    schema_bytes: tuple[bytes, bytes, bytes, bytes]
    worker_digest: str
    worker_size: int
    mount_key: tuple


def _check(p, deadline: Deadline) -> None:
    deadline.require()


def _process(p) -> tuple[int, int]:
    values = p._credentials()
    if type(values) is not tuple or len(values) != 4:
        raise p._MetadataInvalid()
    ruid, euid, rgid, egid = values
    for item in values:
        if type(item) is not int or not 1 <= item <= p._MAX_ID:
            raise p._MetadataInvalid()
    if ruid != euid or rgid != egid:
        raise p._MetadataInvalid()
    return ruid, rgid


def _open_directory(
    p, path: Path, owner: tuple[int, int], transient: list[int]
) -> f.FileIdentity:
    before = os.stat(path, follow_symlinks=False)
    if not stat.S_ISDIR(before.st_mode):
        raise p._MetadataInvalid()
    fd = f.open_directory(path)
    transient.append(fd)
    observed = f.validate_directory(
        fd, uid=owner[0], gid=owner[1], mode=p._DIRECTORY_MODE
    )
    if (observed.device, observed.inode) != (before.st_dev, before.st_ino):
        raise p._MetadataInvalid()
    return observed


def _open_leaf(
    p,
    dir_fd: int,
    name: str,
    mode: int,
    cap: int,
    owner: tuple[int, int],
    transient: list[int],
) -> tuple:
    before = f.stat_at(dir_fd, name)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise p._MetadataInvalid()
    # opened directly so that an OSError here stays "unavailable" (contract §2)
    fd = os.open(name, p._LEAF_FLAGS, dir_fd=dir_fd)
    transient.append(fd)
    info = f.stat_fd(fd)
    f.validate_regular(info, uid=owner[0], gid=owner[1], mode=mode, cap=cap)
    signature = f.signature(info)
    if signature != f.signature(f.stat_at(dir_fd, name)) or signature != f.signature(
        before
    ):
        raise p._MetadataInvalid()
    return signature


def _read_bounded(p, fd: int, cap: int, deadline: Deadline) -> bytes:
    """Read one complete bounded file with deadline checks around every chunk."""

    before = f.stat_fd(fd)
    if not 1 <= before.st_size <= cap:
        raise p._MetadataInvalid()
    os.lseek(fd, 0, os.SEEK_SET)
    result = bytearray()
    while len(result) <= cap:
        _check(p, deadline)
        part = os.read(fd, min(p._CHUNK, cap + 1 - len(result)))
        _check(p, deadline)
        if not part:
            break
        result.extend(part)
    if len(result) != before.st_size or f.signature(before) != f.signature(
        f.stat_fd(fd)
    ):
        raise p._MetadataInvalid()
    return bytes(result)


def _hash_worker(p, fd: int, expected_size: int, deadline: Deadline) -> str:
    os.lseek(fd, 0, os.SEEK_SET)
    digest = sha256()
    total = 0
    while total <= expected_size:
        _check(p, deadline)
        chunk = os.read(fd, min(p._CHUNK, expected_size + 1 - total))
        _check(p, deadline)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    if total != expected_size:
        raise p._MetadataInvalid()
    return digest.hexdigest()


def _mount_key(
    p,
    directories: tuple[f.FileIdentity, ...],
    leaves: tuple[tuple, ...],
    paths: tuple[Path, ...],
) -> tuple:
    mounts = p._read_mountinfo()
    root_mount = m.containing(mounts, p.EXTENSION_ROOT)
    if root_mount.mountpoint != p.EXTENSION_ROOT or not root_mount.read_only:
        raise p._MetadataInvalid()
    for path in paths:
        if m.containing(mounts, path) is not root_mount:
            # an intervening mount on the chain (e.g. at /opt)
            raise p._MetadataInvalid()
    for identity in (*directories, *(leaf[0] for leaf in leaves)):
        m.verify_device(root_mount, identity)
    prefix_backing = m.backing(root_mount, p.EXTENSION_PREFIX)
    for mount in mounts:
        if mount is root_mount:
            continue
        if mount.mountpoint.is_relative_to(p.EXTENSION_PREFIX):
            # NO mount at or below the prefix, on the named chain or off it
            raise p._MetadataInvalid()
        if mount.device == root_mount.device and (
            mount.root.is_relative_to(prefix_backing)
            or prefix_backing.is_relative_to(mount.root)
        ):
            # a visible same-device alias of the prefix's backing path
            raise p._MetadataInvalid()
    return (root_mount.device, str(root_mount.root), root_mount.read_only)


def _observe(
    p,
    deadline: Deadline,
    *,
    retained: object | None,
    keep: list[int] | None,
) -> _Observation:
    transient: list[int] = []
    try:
        _check(p, deadline)
        platform_name = p._native_platform()
        uid, gid = _process(p)
        owner = p._expected_owner()
        directory_paths = _directories(p)
        leaf_specs = _leaves(p)
        directories = tuple(
            _open_directory(p, path, owner, transient) for path in directory_paths
        )
        directory_fds = tuple(transient)
        by_path = dict(zip(directory_paths, directory_fds, strict=True))
        leaves = []
        for directory, name, mode, cap in leaf_specs:
            leaves.append(
                _open_leaf(p, by_path[directory], name, mode, cap, owner, transient)
            )
        leaves = tuple(leaves)
        leaf_fds = tuple(transient[len(directory_fds) :])
        keys = {(d.device, d.inode) for d in directories} | {
            (leaf[0].device, leaf[0].inode) for leaf in leaves
        }
        if len(keys) != len(directories) + len(leaves):
            raise p._MetadataInvalid()
        leaf_paths = tuple(directory / name for directory, name, _, _ in leaf_specs)
        all_paths = (*directory_paths, *leaf_paths)
        mount_key = _mount_key(p, directories, leaves, all_paths)
        if retained is not None:
            _compare_retained(p, retained, owner)
        _check(p, deadline)
        worker_size = leaves[0][2]
        identity_bytes = p._read_bounded(leaf_fds[1], p._IDENTITY_CAP, deadline)
        schema_bytes = tuple(
            p._read_bounded(fd, p._SCHEMA_CAP, deadline) for fd in leaf_fds[2:]
        )
        if (
            worker_size + len(identity_bytes) + sum(len(raw) for raw in schema_bytes)
            > p._TOTAL_CAP
        ):
            raise p._MetadataInvalid()
        identity = p.parse_build_identity(identity_bytes)
        declared = identity.as_dict()
        if declared["platform"] != platform_name:
            raise p._MetadataInvalid()
        entrypoint = declared["entrypoint"]
        if entrypoint["size_bytes"] != worker_size:
            raise p._MetadataInvalid()
        p.validate_schema_bytes(identity, schema_bytes)  # type: ignore[arg-type]
        worker_digest = _hash_worker(p, leaf_fds[0], worker_size, deadline)
        if worker_digest != entrypoint["sha256"]:
            raise p._MetadataInvalid()
        # final fence: names, held descriptors, mounts and sampled facts must
        # still agree with what was measured
        for path, baseline in zip(directory_paths, directories, strict=True):
            after = os.stat(path, follow_symlinks=False)
            if (after.st_dev, after.st_ino) != (baseline.device, baseline.inode):
                raise p._MetadataInvalid()
        for (directory, name, _, _), baseline, fd in zip(
            leaf_specs, leaves, leaf_fds, strict=True
        ):
            if f.signature(f.stat_at(by_path[directory], name)) != baseline:
                raise p._MetadataInvalid()
            if f.signature(f.stat_fd(fd)) != baseline:
                raise p._MetadataInvalid()
        if retained is not None:
            _compare_retained(p, retained, owner)
        if _mount_key(p, directories, leaves, all_paths) != mount_key:
            raise p._MetadataInvalid()
        if p._native_platform() != platform_name or _process(p) != (uid, gid):
            raise p._MetadataInvalid()
        _check(p, deadline)
        observation = _Observation(
            platform=platform_name,
            uid=uid,
            gid=gid,
            directories=directories,
            leaves=leaves,
            identity_bytes=identity_bytes,
            schema_bytes=schema_bytes,  # type: ignore[arg-type]
            worker_digest=worker_digest,
            worker_size=worker_size,
            mount_key=mount_key,
        )
        if keep is not None:
            keep.extend(transient)
            transient.clear()
        return observation
    except p._MetadataError:
        raise
    except DeadlineExceeded:
        raise p._MetadataDeadline() from None
    except ChannelConfigurationError:
        raise p._MetadataInvalid() from None
    except DeploymentSourceUnavailable:
        raise p._MetadataUnavailable() from None
    except (
        DeploymentSourceError,
        LineageContractError,
        ProviderIdentityError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        AttributeError,
        UnicodeError,
        RecursionError,
        MemoryError,
    ):
        raise p._MetadataInvalid() from None
    except OSError:
        raise p._MetadataUnavailable() from None
    finally:
        for fd in transient:
            f.close_fd(fd)


def _compare_retained(p, retained: object, owner: tuple[int, int]) -> None:
    """The retained descriptors must still show the acquisition baseline."""

    for fd, baseline in zip(
        retained._directory_fds, retained._baseline.directories, strict=True
    ):
        if (
            f.validate_directory(fd, uid=owner[0], gid=owner[1], mode=p._DIRECTORY_MODE)
            != baseline
        ):
            raise p._MetadataInvalid()
    for fd, baseline in zip(retained._leaf_fds, retained._baseline.leaves, strict=True):
        if f.signature(f.stat_fd(fd)) != baseline:
            raise p._MetadataInvalid()
