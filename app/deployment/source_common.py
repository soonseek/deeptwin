"""Neutral retained-source lifecycle shared by fixed deployment readers."""

from dataclasses import dataclass
from pathlib import Path

from app.operations.setup import OriginProfile

from . import contracts as c
from . import files as f
from . import mounts as m


@dataclass(frozen=True, slots=True)
class ObjectIdentity:
    device: int
    inode: int

    def as_dict(self):
        return {"device": self.device, "inode": self.inode}


def _observed(identity):
    return ObjectIdentity(identity.device, identity.inode)


_OPTIONAL_SOURCE_ROOTS = (
    c.TOPOLOGY_ROOT,
    c.EXCHANGE_ROOT,
    c.OUTBOX_ROOT,
    *(c.IPC_ROOT / f"xs{number:02}" for number in range(1, 17)),
    Path("/run/deeptwin/deployment-verify-public"),
    Path("/run/deeptwin/deployment-receipt-ingress"),
    Path("/run/deeptwin/deployment-consumption-exchange"),
    Path("/run/deeptwin/deployment-receipts"),
    Path("/run/deeptwin/deployment-consumed"),
    Path("/run/deeptwin/provider-stage-sources"),
    Path("/run/deeptwin/provider-deployment-outbox"),
    Path("/run/deeptwin/provider-deployment-receipts"),
    Path("/run/deeptwin/provider-deployment-consumed"),
    Path("/run/deeptwin/installation-release-sources"),
)


def _validate_source_startup(*, profile, source_sha256, protected_roots):
    if type(profile) is not OriginProfile or type(protected_roots) is not tuple:
        raise c.DeploymentSourceError()
    c.hex_digest(source_sha256)
    for root in protected_roots:
        if not isinstance(root, Path) or not root.is_absolute() or ".." in root.parts:
            raise c.DeploymentSourceError()
    return m.native_platform()


def _source_mount_observations(observed, required, protected_paths):
    present = tuple(
        path
        for path in _OPTIONAL_SOURCE_ROOTS
        if path not in required and any(item.mountpoint == path for item in observed)
    )
    checked = m.verify_boundaries(
        observed,
        required,
        protected_paths,
    )

    def aliases(left, right):
        left_path, left_mount, left_backing = left
        right_path, right_mount, right_backing = right
        return (
            left_path.is_relative_to(right_path)
            or right_path.is_relative_to(left_path)
            or left_mount.device == right_mount.device
            and (
                left_backing.is_relative_to(right_backing)
                or right_backing.is_relative_to(left_backing)
            )
        )

    protected_observations = tuple(
        (path, mount, backing) for path, (mount, backing) in checked
    )
    optional_observations = []
    for optional_root in present:
        root_mount = next(item for item in observed if item.mountpoint == optional_root)
        optional_observations.append(
            (
                optional_root,
                (optional_root, root_mount, m.backing(root_mount, optional_root)),
            )
        )
        optional_observations.extend(
            (
                optional_root,
                (item.mountpoint, item, m.backing(item, item.mountpoint)),
            )
            for item in observed
            if item.mountpoint != optional_root
            and item.mountpoint.is_relative_to(optional_root)
        )
    for index, (owner, candidate) in enumerate(optional_observations):
        if any(aliases(candidate, retained) for retained in protected_observations):
            raise c.DeploymentSourceError()
        if any(
            other_owner != owner and aliases(candidate, other)
            for other_owner, other in optional_observations[:index]
        ):
            raise c.DeploymentSourceError()
    return checked, tuple(
        sorted(optional_observations, key=lambda item: (str(item[0]), str(item[1][0])))
    )


class _Source(f.RetainedHandle):
    def __init__(self):
        raise TypeError("source construction requires the fixed source factory")

    def _mounts(self):
        return self._mapping_for(self._required)

    def _mapping_for(self, own):
        checked, _optional = _source_mount_observations(
            m.read_mountinfo(),
            own,
            tuple(directory.path for directory in self._protected),
        )
        retained_paths = set(own) | {directory.path for directory in self._protected}
        return tuple(item for item in checked if item[0] in retained_paths)

    def _recheck_base(self):
        if getattr(self, "_closed", True):
            raise c.DeploymentSourceError()
        if (
            m.native_platform() != self._platform
            or self._source.read_current() != self._bytes
        ):
            raise c.DeploymentSourceError()
        identities = [self._source.root.identity]
        for directory in self._protected:
            identities.append(directory.recheck_current())
        if len({(item.device, item.inode) for item in identities}) != len(identities):
            raise c.DeploymentSourceError()
        for directory in (self._source.root, *self._protected):
            m.verify_device(dict(self._mapping)[directory.path][0], directory.identity)
        if self._mounts() != self._mapping:
            raise c.DeploymentSourceError()

    def close(self):
        if not getattr(self, "_closed", True):
            self._closed = True
            for handle in self._handles:
                handle.close()


def _open_pinned_source(
    cls,
    *,
    profile,
    source_sha256,
    protected_roots,
    root,
    name,
    gid,
    cap,
    required,
):
    platform = _validate_source_startup(
        profile=profile,
        source_sha256=source_sha256,
        protected_roots=protected_roots,
    )
    result = object.__new__(cls)
    result._closed, result._handles, result._protected = False, [], []
    result._platform, result._profile, result._required = platform, profile, required
    try:
        source = f.SourceFile.open(
            root, name, uid=0, gid=gid, cap=cap, pin=source_sha256
        )
        result._source = source
        result._handles.append(source)
        result._bytes = source.read_current()
        for path in dict.fromkeys((*c.BUILTIN_ROOTS, *protected_roots)):
            directory = f.Directory.open(path, search=True)
            result._protected.append(directory)
            result._handles.append(directory)
        result._mapping = result._mounts()
        result._recheck_base()
        return result
    except (OSError, c.DeploymentSourceError):
        result.close()
        raise c.DeploymentSourceError() from None
