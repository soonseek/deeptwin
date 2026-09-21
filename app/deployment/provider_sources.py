"""Startup-owned read-only provider source graph; never payload admission."""

from pathlib import Path

from app.operations.setup import OriginProfile, SetupContractError

from . import contracts as c
from . import files as f
from . import mounts as m
from ._provider_source_files import _open_provider_bundle, _snapshot_provider_namespace
from .provider_source_contracts import (
    parse_provider_context,
    parse_provider_instance,
    parse_provider_pins,
)
from .source_common import _source_mount_observations
from .provider_receipt_contracts import ProviderReceiptChannelIdentity

PROVIDER_CONTEXT_STARTUP_KEY = "DEEPTWIN_PROVIDER_STAGE_CONTEXT_SHA256"
_BASE = Path("/run/deeptwin")
_STATIC = _BASE / "provider-stage-sources"
_ORIGINALS = (
    (
        _BASE / "extension-topology",
        "topology.json",
        20102,
        65536,
        "original-topology.json",
    ),
    (
        _BASE / "deployment-exchange",
        "exchange.json",
        21201,
        8192,
        "original-outgoing-exchange.json",
    ),
    (
        _BASE / "deployment-verify-public",
        "trust-set.json",
        20102,
        16384,
        "original-trust-set.json",
    ),
    (
        _BASE / "deployment-receipt-ingress",
        "ingress.json",
        21201,
        8192,
        "original-receipt-ingress.json",
    ),
    (
        _BASE / "deployment-consumption-exchange",
        "consumption-exchange.json",
        21201,
        8192,
        "original-consumption-exchange.json",
    ),
)
_CHANNEL_ROOTS = (
    (_BASE / "provider-deployment-outbox", 20102, False, ("cancelled", "requests")),
    (_BASE / "provider-deployment-receipts", 20113, True, ("receipts",)),
    (_BASE / "provider-deployment-consumed", 20102, False, ("consumed",)),
)
_REQUIRED = {
    _STATIC: True,
    **{p: True for p, *_ in _ORIGINALS},
    **{p: ro for p, _, ro, _ in _CHANNEL_ROOTS},
}


class ProviderSourceContext(f.RetainedHandle):
    def __init__(self):
        raise TypeError("provider context requires the fixed source factory")

    def _mounts(self):
        return _source_mount_observations(
            m.read_mountinfo(), _REQUIRED, tuple(d.path for d in self._protected)
        )

    def _guard(self):
        if m.native_platform() != self._platform:
            raise c.DeploymentSourceError()
        raw = self._bundle.read_current()
        for source, expected, root_signature in self._originals:
            if (
                source.read_current() != expected
                or f.signature(f.stat_fd(source.root.fd)) != root_signature
            ):
                raise c.DeploymentSourceError()
        for root, names, signature in self._channels:
            root.recheck_current()
            if (
                f.members(root.fd, len(names)) != set(names)
                or f.signature(f.stat_fd(root.fd)) != signature
            ):
                raise c.DeploymentSourceError()
        for directory in (*self._protected, *self._namespaces.values()):
            directory.recheck_current()
        if self._mounts() != self._mapping:
            raise c.DeploymentSourceError()
        return raw

    def _snapshot(self):
        snapshots = tuple(
            _snapshot_provider_namespace(directory, namespace=name)
            for name, directory in self._namespaces.items()
        )
        if sum(value.final_count + value.stage_count for value in snapshots) > 240:
            raise c.DeploymentSourceError()
        return snapshots

    def _read_observed(self, *, receipt=False):
        try:
            if type(self) is not ProviderSourceContext or self._closed:
                raise c.DeploymentSourceError()
            self._guard()
            before = self._snapshot()
            raw = self._guard()
            identities = tuple(
                f.identity(f.stat_fd(directory.fd))
                for directory in (
                    self._channels[0][0],
                    self._namespaces["requests"],
                    self._namespaces["cancelled"],
                )
            )
            if receipt:
                mapping = dict(self._mapping[0])
                channels = {}
                for label, index, namespace in (("incoming", 1, "receipts"), ("consumed", 2, "consumed")):
                    root = self._channels[index][0]
                    root_id = f.identity(f.stat_fd(root.fd))
                    leaf_id = f.identity(f.stat_fd(self._namespaces[namespace].fd))
                    channels[label] = {
                        "root": {"device": root_id.device, "inode": root_id.inode},
                        "namespace": {"device": leaf_id.device, "inode": leaf_id.inode},
                        "backing_root_digest": c.digest(str(mapping[root.path][1]).encode("utf-8")),
                    }
                identities = ProviderReceiptChannelIdentity(
                    "deployment-provider-receipt-channel-identity-v1",
                    c.digest(dict(raw)["source-context.json"]),
                    channels["incoming"], channels["consumed"],
                )
            # Finish with the complete closing capture: further filesystem work
            # after it would leave channel changes during that work unobserved.
            if self._snapshot() != before:
                raise c.DeploymentSourceError()
            snapshots = dict(zip(self._namespaces, before, strict=True))
            return raw, (
                identities,
                tuple(
                    (name, snapshots[name])
                    for name in ("requests", "cancelled", "receipts", "consumed")
                ),
            )
        except (AttributeError, KeyError):
            raise c.DeploymentSourceError() from None
        except OSError:
            raise c.DeploymentSourceUnavailable() from None
        except BaseException as error:
            if not isinstance(error, Exception):
                try:
                    self.close()
                except BaseException:  # noqa: BLE001, S110 - preserve primary
                    pass
            raise

    def read_current(self) -> tuple[tuple[str, bytes], ...]:
        return self._read_observed()[0]

    def _provider_publication_observation(self):
        return self._read_observed()[1]

    def _provider_receipt_observation(self):
        return self._read_observed(receipt=True)[1]

    def recheck_current(self) -> None:
        self.read_current()

    def close(self) -> None:
        if not getattr(self, "_closed", True):
            self._closed = True
            failure = None
            for handle in reversed(self._handles):
                try:
                    handle.close()
                except BaseException as error:  # noqa: BLE001 - attempt all owned closes
                    if failure is None:
                        failure = error
            if failure is not None:
                raise failure


def open_provider_source_context(
    *,
    profile: OriginProfile,
    context_sha256: str,
    protected_roots: tuple[Path, ...],
) -> ProviderSourceContext:
    if (
        type(profile) is not OriginProfile
        or type(protected_roots) is not tuple
        or len(protected_roots) > 64
    ):
        raise c.DeploymentSourceError()
    c.hex_digest(context_sha256)
    try:
        if OriginProfile.from_dict(profile.as_dict()).as_dict() != profile.as_dict():
            raise c.DeploymentSourceError()
        for path in protected_roots:
            if (
                not isinstance(path, Path)
                or not path.is_absolute()
                or ".." in path.parts
                or not 1 <= len(str(path).encode("utf-8")) <= 4096
            ):
                raise c.DeploymentSourceError()
    except (SetupContractError, AttributeError, UnicodeError):
        raise c.DeploymentSourceError() from None
    platform = m.native_platform()
    result = object.__new__(ProviderSourceContext)
    result._closed, result._handles = False, []
    result._platform = platform
    result._originals, result._channels, result._protected, result._namespaces = (
        [],
        [],
        [],
        {},
    )
    try:
        root = f.Directory.open(_STATIC, uid=0, gid=21201, mode=0o750)
        result._handles.append(root)
        bundle = _open_provider_bundle(root, context_sha256=context_sha256)
        result._handles.append(bundle)
        result._bundle = bundle
        raw = dict(bundle.read_current())
        parse_provider_context(raw["source-context.json"])
        parse_provider_pins(raw["source-pins.json"])
        parse_provider_instance(raw["provider-instance.json"])
        instance = c.parse_instance(raw["original-prepare-instance.json"])
        if (
            instance["origin_profile"] != profile.as_dict()
            or instance["platform"] != platform
        ):
            raise c.DeploymentSourceError()
        documents, leaves = bundle._object_identities()
        identities = [root.identity, documents, *(value for _, value in leaves)]
        directories = [root]
        for path, name, gid, cap, document in _ORIGINALS:
            source = f.SourceFile.open(
                path, name, uid=0, gid=gid, cap=cap, pin=c.digest(raw[document])
            )
            result._handles.append(source)
            if source.read_current() != raw[document]:
                raise c.DeploymentSourceError()
            result._originals.append(
                (source, raw[document], f.signature(f.stat_fd(source.root.fd)))
            )
            identities.extend((source.root.identity, f.identity(f.stat_fd(source.fd))))
            directories.append(source.root)
            if identities[-1].device != source.root.identity.device:
                raise c.DeploymentSourceError()
        for path, uid, _ro, names in _CHANNEL_ROOTS:
            channel = f.Directory.open(path, uid=uid, gid=21201, mode=0o750)
            result._handles.append(channel)
            result._channels.append(
                (channel, names, f.signature(f.stat_fd(channel.fd)))
            )
            identities.append(channel.identity)
            directories.append(channel)
            for name in names:
                directory = f.Directory.open(
                    path / name, uid=uid, gid=21201, mode=0o750
                )
                result._handles.append(directory)
                result._namespaces[name] = directory
                identities.append(directory.identity)
                if directory.identity.device != channel.identity.device:
                    raise c.DeploymentSourceError()
        for path in dict.fromkeys((*c.BUILTIN_ROOTS, *protected_roots)):
            directory = f.Directory.open(path, search=True)
            result._handles.append(directory)
            result._protected.append(directory)
            identities.append(directory.identity)
            directories.append(directory)
        if len({(value.device, value.inode) for value in identities}) != len(
            identities
        ):
            raise c.DeploymentSourceError()
        result._mapping = result._mounts()
        checked = dict(result._mapping[0])
        for directory in directories:
            m.verify_device(checked[directory.path][0], directory.identity)
        result.recheck_current()
        return result
    except BaseException as error:
        try:
            result.close()
        except BaseException:  # noqa: BLE001, S110 - preserve primary
            pass
        if isinstance(error, OSError):
            raise c.DeploymentSourceUnavailable() from None
        raise
