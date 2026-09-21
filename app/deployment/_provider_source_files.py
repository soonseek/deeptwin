"""Fixed read-only provider bundle and channel metadata observations."""

from dataclasses import dataclass
from pathlib import Path

from . import contracts as c
from . import files as f
from .provider_source_contracts import validate_provider_source_bundle

_ROOT = Path("/run/deeptwin/provider-stage-sources")
_FILES = (
    ("original-prepare-recipe.json", 4096),
    ("original-prepare-instance.json", 4096),
    ("original-topology.json", 65536),
    ("original-outgoing-exchange.json", 8192),
    ("original-receipt-recipe.json", 4096),
    ("original-receipt-instance.json", 4096),
    ("original-trust-set.json", 16384),
    ("original-receipt-ingress.json", 8192),
    ("original-consumption-exchange.json", 8192),
    ("geometry.json", 65536),
    ("provider-recipe.json", 8192),
    ("provider-instance.json", 8192),
    ("provider-trust-set.json", 16384),
    ("outgoing-exchange.json", 8192),
    ("receipt-ingress.json", 8192),
    ("consumption-exchange.json", 8192),
    ("source-context.json", 16384),
    ("source-pins.json", 8192),
)
_PROVIDER_REQUEST_NAMESPACE = f._NamespacePolicy(20102, 20102, 21201, 16, 32, 65536)
_PROVIDER_CANCEL_NAMESPACE = f._NamespacePolicy(20102, 20102, 21201, 16, 32, 8192)
_PROVIDER_INCOMING_NAMESPACE = f._NamespacePolicy(20113, 20113, 21201, 64, 32, 16384)
_PROVIDER_CONSUMED_NAMESPACE = f._NamespacePolicy(20102, 20102, 21201, 16, 32, 8192)
_NAMESPACES = {
    "requests": ("provider-deployment-outbox", _PROVIDER_REQUEST_NAMESPACE),
    "cancelled": ("provider-deployment-outbox", _PROVIDER_CANCEL_NAMESPACE),
    "receipts": ("provider-deployment-receipts", _PROVIDER_INCOMING_NAMESPACE),
    "consumed": ("provider-deployment-consumed", _PROVIDER_CONSUMED_NAMESPACE),
}


def _require_directory(directory, path, uid):
    try:
        if type(directory) is not f.Directory or directory.path != path:
            raise c.DeploymentSourceError()
        observed = directory.recheck_current()
        if (observed.uid, observed.gid, observed.mode) != (uid, 21201, 0o750):
            raise c.DeploymentSourceError()
    except AttributeError:
        raise c.DeploymentSourceError() from None


class _RetainedProviderBundle(f.RetainedHandle):
    def __init__(self):
        raise TypeError("provider bundle requires fixed observation")

    def read_current(self):
        try:
            if type(self) is not _RetainedProviderBundle or self._closed:
                raise c.DeploymentSourceError()
            _require_directory(self._root, _ROOT, 0)
            _require_directory(self._directory, _ROOT / "documents", 0)
            if (
                f.members(self._root.fd, 1) != {"documents"}
                or f.signature(f.stat_fd(self._root.fd)) != self._root_signature
                or f.signature(f.stat_at(self._root.fd, "documents"))
                != self._directory_signature
                or f.signature(f.stat_fd(self._directory.fd))
                != self._directory_signature
                or f.members(self._directory.fd, 18) != {n for n, _ in _FILES}
            ):
                raise c.DeploymentSourceError()
            result = []
            for name, cap in _FILES:
                fd, signature, raw = self._leaves[name]
                if (
                    f.signature(f.stat_fd(fd)) != signature
                    or f.signature(f.stat_at(self._directory.fd, name)) != signature
                ):
                    raise c.DeploymentSourceError()
                value = f.read_exact(fd, cap)
                if (
                    value != raw
                    or f.signature(f.stat_at(self._directory.fd, name)) != signature
                ):
                    raise c.DeploymentSourceError()
                result.append((name, value))
            if (
                f.members(self._directory.fd, 18) != {n for n, _ in _FILES}
                or f.signature(f.stat_fd(self._directory.fd))
                != self._directory_signature
                or f.signature(f.stat_fd(self._root.fd)) != self._root_signature
                or any(
                    f.signature(f.stat_fd(fd)) != signature
                    or f.signature(f.stat_at(self._directory.fd, name)) != signature
                    for name, (fd, signature, _) in self._leaves.items()
                )
            ):
                raise c.DeploymentSourceError()
            self._directory.recheck_current()
            self._root.recheck_current()
            return tuple(result)
        except (AttributeError, KeyError):
            raise c.DeploymentSourceError() from None
        except OSError:
            raise c.DeploymentSourceUnavailable() from None

    def recheck_current(self):
        self.read_current()

    def _object_identities(self):
        self.recheck_current()
        return self._directory.identity, tuple(
            (name, self._leaves[name][1][0]) for name, _ in _FILES
        )

    def close(self):
        if not self._closed:
            self._closed = True
            failure = None
            for fd in self._owned_fds:
                try:
                    f.close_fd(fd)
                except BaseException as error:  # noqa: BLE001 - rethrow after all closes
                    if failure is None:
                        failure = error
            if self._directory is not None:
                try:
                    self._directory.close()
                except BaseException as error:  # noqa: BLE001 - rethrow after all closes
                    if failure is None:
                        failure = error
            if failure is not None:
                raise failure


def _open_provider_bundle(root: f.Directory, *, context_sha256: str):
    c.hex_digest(context_sha256)
    _require_directory(root, _ROOT, 0)
    result = object.__new__(_RetainedProviderBundle)
    result._closed, result._directory = False, None
    result._root, result._owned_fds, result._leaves = root, [], {}
    try:
        result._root_signature = f.signature(f.stat_fd(root.fd))
        if f.members(root.fd, 1) != {"documents"}:
            raise c.DeploymentSourceError()
        result._directory = f.Directory.open(
            _ROOT / "documents", uid=0, gid=21201, mode=0o750
        )
        directory = result._directory
        result._directory_signature = f.signature(f.stat_fd(directory.fd))
        if directory.identity.device != root.identity.device:
            raise c.DeploymentSourceError()
        for name, cap in (_FILES[16], *_FILES[:16], _FILES[17]):
            fd = f.open_regular(
                directory.fd, name, uid=0, gid=21201, mode=0o440, cap=cap
            )
            result._owned_fds.append(fd)
            signature = f.signature(f.stat_fd(fd))
            raw = f.read_exact(fd, cap)
            if (
                signature != f.signature(f.stat_at(directory.fd, name))
                or signature[0].device != directory.identity.device
            ):
                raise c.DeploymentSourceError()
            if name == "source-context.json" and c.digest(raw) != context_sha256:
                raise c.DeploymentSourceError()
            result._leaves[name] = fd, signature, raw
        bundle = result.read_current()
        if sum(len(raw) for _, raw in bundle) > 524288:
            raise c.DeploymentSourceError()
        validate_provider_source_bundle(bundle)
        result.recheck_current()
        return result
    except BaseException as error:
        try:
            result.close()
        except BaseException:  # noqa: BLE001, S110 - preserve the active primary
            pass
        if isinstance(error, OSError):
            raise c.DeploymentSourceUnavailable() from None
        raise


@dataclass(frozen=True, slots=True)
class _ProviderNamespaceSnapshot:
    directory_signature: tuple
    entries: tuple
    final_count: int
    stage_count: int


def _provider_namespace_policy(namespace: str) -> f._NamespacePolicy:
    if type(namespace) is not str or namespace not in _NAMESPACES:
        raise c.DeploymentSourceError()
    return _NAMESPACES[namespace][1]


def _snapshot_provider_namespace(directory: f.Directory, *, namespace: str):
    policy = _provider_namespace_policy(namespace)
    root = _NAMESPACES[namespace][0]
    _require_directory(
        directory, Path("/run/deeptwin") / root / namespace, policy.writer_uid
    )
    try:

        def capture():
            signature = f.signature(f.stat_fd(directory.fd))
            entries = tuple(
                (name, f.signature(f.stat_at(directory.fd, name)))
                for name in sorted(
                    f.members(directory.fd, policy.final_limit + policy.stage_limit)
                )
            )
            return signature, entries

        before = capture()
        scan = f._scan_namespace(directory, policy=policy)
        if capture() != before:
            raise c.DeploymentSourceError()
        return _ProviderNamespaceSnapshot(*before, len(scan.finals), scan.stages)
    except OSError:
        raise c.DeploymentSourceUnavailable() from None
