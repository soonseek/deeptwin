"""Independent retained topology and outgoing-exchange readers owned by startup."""

from dataclasses import dataclass
from pathlib import Path

from app.operations.setup import OriginProfile
from app.workers import ipc_root

from . import contracts as c
from . import files as f
from . import mounts as m
from .source_common import ObjectIdentity, _observed, _open_pinned_source, _Source


@dataclass(frozen=True, slots=True)
class OutboxIdentity:
    root: ObjectIdentity
    requests: ObjectIdentity
    cancelled: ObjectIdentity
    backing_root_digest: str

    def as_dict(self):
        return {
            "schema_version": "deployment-outbox-identity-v1",
            "root": self.root.as_dict(),
            "requests": self.requests.as_dict(),
            "cancelled": self.cancelled.as_dict(),
            "backing_root_digest": self.backing_root_digest,
        }


def _validate_startup(
    profile, recipe_sha256, instance_sha256, source_sha256, protected_roots
):
    for value in (recipe_sha256, instance_sha256):
        c.hex_digest(value)
    if recipe_sha256 != c.digest(c.encode(c.RECIPE)):
        raise c.DeploymentSourceError()


def _open_common(
    cls,
    *,
    profile,
    recipe_sha256,
    instance_sha256,
    source_sha256,
    protected_roots,
    root,
    name,
    gid,
    cap,
    required,
):
    _validate_startup(
        profile, recipe_sha256, instance_sha256, source_sha256, protected_roots
    )
    return _open_pinned_source(
        cls,
        profile=profile,
        source_sha256=source_sha256,
        protected_roots=protected_roots,
        root=root,
        name=name,
        gid=gid,
        cap=cap,
        required=required,
    )


class SlotMetadataLease(f.RetainedHandle):
    def __init__(self):
        raise TypeError("slot construction requires topology admission")

    @property
    def topology_bytes(self):
        if getattr(self, "_closed", True):
            raise c.DeploymentSourceError()
        return self._source._bytes

    @property
    def slot(self):
        # Return inert copies; caller mutation cannot modify the source/lease binding.
        if getattr(self, "_closed", True):
            raise c.DeploymentSourceError()
        return c.slot(self._source._profile.instance_id, self._slot_number)

    @property
    def metadata_lease(self):
        if getattr(self, "_closed", True):
            raise c.DeploymentSourceError()
        return self._metadata

    def recheck_current(self):
        if getattr(self, "_closed", True):
            raise c.DeploymentSourceError()
        self._source.recheck_current()
        try:
            self._metadata.recheck_current()
        except ipc_root.IpcRootError:
            raise c.DeploymentSourceError() from None
        self._directory.recheck_current()
        if self._source._mapping_for(self._required) != self._mapping:
            raise c.DeploymentSourceError()

    def close(self):
        if not getattr(self, "_closed", True):
            self._closed = True
            first_error = None
            for handle in (self._metadata, self._directory):
                try:
                    handle.close()
                except BaseException as error:  # noqa: BLE001 - attempt both children
                    if first_error is None:
                        first_error = error
            if first_error is not None:
                raise first_error


class TopologySource(_Source):
    def recheck_current(self):
        self._recheck_base()

    def acquire_slot(self, slot_number):
        self.recheck_current()
        c.integer(slot_number, 1, self._capacity)
        slot = c.slot(self._profile.instance_id, slot_number)
        directory = f.Directory.open(
            Path(slot["socket_mount"]["container_path"]),
            uid=0,
            gid=slot["pair_gid"],
            mode=0o710,
            search=True,
        )
        metadata = None
        lease = None
        transferred = False
        try:
            required = dict(self._required) | {directory.path: True}
            mapping = self._mapping_for(required)
            m.verify_device(dict(mapping)[directory.path][0], directory.identity)
            if not mapping or directory.identity in [self._source.root.identity] + [
                d.identity for d in self._protected
            ]:
                raise c.DeploymentSourceError()
            metadata = ipc_root.acquire_generation_metadata(
                ipc_root.PairRootSpec(
                    directory.path, slot["uid"], slot["gid"], slot["pair_gid"]
                )
            )
            lease = object.__new__(SlotMetadataLease)
            lease._source, lease._slot_number = self, slot_number
            lease._required, lease._mapping = required, mapping
            lease._metadata, lease._directory, lease._closed = (
                metadata,
                directory,
                False,
            )
            directory = metadata = None
            transferred = True
            lease.recheck_current()
            return lease
        except BaseException as error:
            owned = (lease,) if transferred else (metadata, directory)
            for handle in owned:
                if handle is not None:
                    try:
                        handle.close()
                    except BaseException:  # noqa: BLE001, S110 - preserve primary
                        pass
            if isinstance(error, ipc_root.IpcRootBusy):
                raise c.DeploymentSourceBusy() from None
            if isinstance(
                error, (OSError, c.DeploymentSourceError, ipc_root.IpcRootError)
            ):
                raise c.DeploymentSourceError() from None
            raise


def open_topology_source(
    *,
    profile: OriginProfile,
    recipe_sha256: str,
    instance_sha256: str,
    topology_sha256: str,
    protected_roots: tuple[Path, ...],
) -> TopologySource:
    source = _open_common(
        TopologySource,
        profile=profile,
        recipe_sha256=recipe_sha256,
        instance_sha256=instance_sha256,
        source_sha256=topology_sha256,
        protected_roots=protected_roots,
        root=c.TOPOLOGY_ROOT,
        name="topology.json",
        gid=20102,
        cap=65536,
        required={c.TOPOLOGY_ROOT: True},
    )
    try:
        topology = c.parse_topology(
            source._bytes,
            profile=profile,
            recipe_sha256=recipe_sha256,
            platform=source._platform,
        )
        source._capacity = len(topology["slots"])
        return source
    except c.DeploymentSourceError:
        source.close()
        raise


class ExchangeSource(_Source):
    @property
    def exchange_bytes(self):
        if getattr(self, "_closed", True):
            raise c.DeploymentSourceError()
        return self._bytes

    def recheck_current(self) -> OutboxIdentity:
        try:
            return self._recheck_outbox()
        except OSError:
            raise c.DeploymentSourceUnavailable() from None

    def _recheck_outbox(self):
        self._recheck_base()
        root = self._outbox.recheck_current()
        if f.members(self._outbox.fd, 2) != {"requests", "cancelled"}:
            raise c.DeploymentSourceError()
        identities = []
        for role, directory in self._namespaces.items():
            identities.append(directory.recheck_current())
            finals, _stages = f.inspect_namespace(
                directory, 65536 if role == "request" else 4096
            )
            if finals:
                from base64 import urlsafe_b64encode

                from .publication import _validate_retained_projection

                for name, raw in finals:
                    request_digest = (
                        urlsafe_b64encode(bytes.fromhex(name[:-5]))
                        .rstrip(b"=")
                        .decode("ascii")
                    )
                    _validate_retained_projection(
                        role=role,
                        request_digest=request_digest,
                        payload=raw,
                        profile=self._profile,
                    )
        if (
            f.members(self._outbox.fd, 2) != {"requests", "cancelled"}
            or self._outbox.recheck_current() != root
            or any(
                directory.recheck_current() != identity
                for directory, identity in zip(
                    self._namespaces.values(), identities, strict=True
                )
            )
        ):
            raise c.DeploymentSourceError()
        self._recheck_base()
        all_ids = [
            root,
            *identities,
            self._source.root.identity,
            *(d.identity for d in self._protected),
        ]
        if len({(i.device, i.inode) for i in all_ids}) != len(all_ids):
            raise c.DeploymentSourceError()
        root_mount, _backing = dict(self._mapping)[c.OUTBOX_ROOT]
        for identity in (root, *identities):
            m.verify_device(root_mount, identity)
        return OutboxIdentity(
            _observed(root),
            _observed(identities[0]),
            _observed(identities[1]),
            c.digest(str(root_mount.root).encode("utf-8")),
        )

    def publish(self, *, role: str, request_digest: str, payload: bytes):
        from .publication import publish

        return publish(self, role=role, request_digest=request_digest, payload=payload)

    def publish_cancellation_v2(self, *, request_digest: str, payload: bytes):
        from .publication import publish_cancellation_v2

        return publish_cancellation_v2(
            self, request_digest=request_digest, payload=payload
        )


def open_exchange_source(
    *,
    profile: OriginProfile,
    recipe_sha256: str,
    instance_sha256: str,
    exchange_sha256: str,
    protected_roots: tuple[Path, ...],
) -> ExchangeSource:
    source = _open_common(
        ExchangeSource,
        profile=profile,
        recipe_sha256=recipe_sha256,
        instance_sha256=instance_sha256,
        source_sha256=exchange_sha256,
        protected_roots=protected_roots,
        root=c.EXCHANGE_ROOT,
        name="exchange.json",
        gid=21201,
        cap=8192,
        required={c.EXCHANGE_ROOT: True, c.OUTBOX_ROOT: False},
    )
    try:
        c.parse_exchange(
            source._bytes,
            profile=profile,
            recipe_sha256=recipe_sha256,
            instance_sha256=instance_sha256,
        )
        source._outbox = f.Directory.open(
            c.OUTBOX_ROOT, uid=20102, gid=21201, mode=0o750
        )
        source._handles.append(source._outbox)
        source._namespaces = {}
        for role, name in (("request", "requests"), ("cancel", "cancelled")):
            directory = f.Directory.open(
                c.OUTBOX_ROOT / name, uid=20102, gid=21201, mode=0o750
            )
            source._namespaces[role] = directory
            source._handles.append(directory)
        source.recheck_current()
        return source
    except (OSError, c.DeploymentSourceError):
        source.close()
        raise c.DeploymentSourceError() from None
