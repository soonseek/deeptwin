"""UID0 fixed provider source initialization, without payload admission or repair."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import mounts as m
from app.deployment import public_init_files as pf
from app.deployment._provider_source_files import (
    _open_provider_bundle,
    _snapshot_provider_namespace,
)
from app.deployment.provider_source_contracts import (
    parse_provider_pins,
    validate_provider_source_bundle,
)
from app.deployment.provider_source_render import render_provider_sources
from app.operations._provider_source_init_files import _commit_bundle, _stage_bundle
from app.operations.setup import OriginProfile

_BASE = Path("/run/deeptwin")
_INPUT = _BASE / "provider-source-init-input"
_ROOTS = tuple(
    _BASE / name
    for name in (
        "provider-stage-sources",
        "provider-deployment-outbox",
        "provider-deployment-receipts",
        "provider-deployment-consumed",
    )
)
_CHANNELS = (
    (_ROOTS[1], ("cancelled", "requests"), 20102),
    (_ROOTS[2], ("receipts",), 20113),
    (_ROOTS[3], ("consumed",), 20102),
)
_CONFIGS = (
    ("original-prepare-instance.json", 4096, "original_prepare_instance_bytes"),
    ("original-receipt-instance.json", 4096, "original_receipt_instance_bytes"),
    ("original-trust-set.json", 16384, "original_trust_bytes"),
    ("provider-instance.json", 8192, "provider_instance_bytes"),
    ("provider-trust-set.json", 16384, "provider_trust_bytes"),
    ("provider-source-pins.json", 8192, None),
)
_RELEASE = (
    ("deploy/compose.yaml", 1048576, "base_compose_bytes"),
    ("deploy/security/service-ids.json", 65536, "base_service_ids_bytes"),
    (
        "deploy/security/deployment-prepare-recipe-v1.json",
        4096,
        "original_prepare_recipe_bytes",
    ),
    (
        "deploy/security/deployment-receipt-recipe-v1.json",
        4096,
        "original_receipt_recipe_bytes",
    ),
    (
        "deploy/security/deployment-provider-source-recipe-v1.json",
        8192,
        "provider_recipe_bytes",
    ),
)
_ORIGINALS = (
    (c.TOPOLOGY_ROOT, "topology.json", 20102),
    (c.EXCHANGE_ROOT, "exchange.json", 21201),
    (_BASE / "deployment-verify-public", "trust-set.json", 20102),
    (_BASE / "deployment-receipt-ingress", "ingress.json", 21201),
    (_BASE / "deployment-consumption-exchange", "consumption-exchange.json", 21201),
)
_OPTIONAL = (
    *c.BUILTIN_ROOTS,
    c.OUTBOX_ROOT,
    _BASE / "deployment-receipts",
    _BASE / "deployment-consumed",
    *(c.IPC_ROOT / f"xs{n:02}" for n in range(1, 17)),
)


class _InitInputs(f.RetainedHandle):
    def recheck_current(self):
        if self._closed or f.members(self.directory.fd, 6) != {
            row[0] for row in _CONFIGS
        }:
            raise c.DeploymentSourceError()
        self.directory.recheck_current()
        for handle, signature in self.signatures:
            handle.recheck_current()
            if f.signature(f.stat_fd(handle.fd)) != signature:
                raise c.DeploymentSourceError()
        for source in (*self.configs.values(), *self.release.values()):
            source.read_current()

    def close(self):
        if not self._closed:
            self._closed = True
            failure = None
            for handle in reversed(self.owned):
                try:
                    handle.close()
                except BaseException as error:  # noqa: BLE001 - rethrow after all closes
                    if failure is None:
                        failure = error
            if failure is not None:
                raise failure


def _open_inputs():
    result = _InitInputs()
    result._closed, result.owned, result.configs, result.release = False, [], {}, {}
    try:
        result.directory = f.Directory.open(_INPUT, uid=0, gid=0, mode=0o750)
        result.owned.append(result.directory)
        if f.members(result.directory.fd, 6) != {row[0] for row in _CONFIGS}:
            raise c.DeploymentSourceError()
        for name, cap, _ in _CONFIGS:
            source = pf._PublicInputFile.open(
                result.directory, name, cap=cap, modes=(0o440,)
            )
            result.owned.append(source)
            result.configs[name] = source
        for relative, cap, _ in _RELEASE:
            source = pf._ReleaseInput.open(relative, cap)
            result.owned.append(source)
            result.release[relative] = source
        result.signatures = tuple(
            (handle, f.signature(f.stat_fd(handle.fd)))
            for handle in (
                result.directory,
                *(
                    handle
                    for source in result.release.values()
                    for handle in source._ancestors
                    if handle.path.is_relative_to(c.RELEASE_ROOT)
                ),
            )
        )
        kwargs = {
            key: result.configs[name].read_current()
            for name, _, key in _CONFIGS
            if key is not None
        }
        kwargs.update(
            {key: result.release[name].read_current() for name, _, key in _RELEASE}
        )
        pins = result.configs["provider-source-pins.json"].read_current()
        if sum(map(len, kwargs.values())) + len(pins) > 2097152:
            raise c.DeploymentSourceError()
        result.output = render_provider_sources(**kwargs)
        if result.output.pins_bytes != pins:
            raise c.DeploymentSourceError()
        validate_provider_source_bundle(result.output.bundle_files)
        result.pins = parse_provider_pins(result.output.pins_bytes)
        result.instance = c.parse_instance(kwargs["original_prepare_instance_bytes"])
        result.profile = OriginProfile.from_dict(result.instance["origin_profile"])
        result.recheck_current()
        return result
    except BaseException:
        try:
            result.close()
        except BaseException:  # noqa: BLE001, S110 - preserve the active primary
            pass
        raise


def _observe_boundaries(inputs, originals):
    mounts = m.read_mountinfo()
    protected = tuple(
        dict.fromkeys(
            (
                *(
                    handle.path
                    for source in inputs.release.values()
                    for handle in source._ancestors
                    if handle.path.is_relative_to(c.RELEASE_ROOT)
                ),
                *(c.RELEASE_ROOT / name for name, _, _ in _RELEASE),
                _INPUT,
                *(_INPUT / name for name, _, _ in _CONFIGS),
            )
        )
    )
    required = {
        **dict.fromkeys(_ROOTS, False),
        **dict.fromkeys((row[0] for row in _ORIGINALS), True),
    }
    mapping = m.verify_boundaries(mounts, required, protected)
    observed = dict(mapping)
    if any(not observed[path][0].read_only for path in protected):
        raise c.DeploymentSourceError()
    identities = []
    backings = []
    for path, identity in (
        (_INPUT, inputs.directory.identity),
        *(
            (handle.path, handle.identity)
            for source in inputs.release.values()
            for handle in source._ancestors
            if handle.path.is_relative_to(c.RELEASE_ROOT)
        ),
        *((_INPUT / name, source.identity) for name, source in inputs.configs.items()),
        *((source.path, source.identity) for source in inputs.release.values()),
    ):
        m.verify_device(observed[path][0], identity)
    for source in (*inputs.configs.values(), *inputs.release.values()):
        path = source.path if type(source) is pf._ReleaseInput else _INPUT / source.name
        identities.append((source.identity.device, source.identity.inode))
        backings.append((observed[path][0].device, observed[path][1]))
    for source, _, _ in originals:
        mount = m.containing(mounts, source.root.path / source.name)
        if not mount.read_only:
            raise c.DeploymentSourceError()
        leaf = f.identity(f.stat_fd(source.fd))
        m.verify_device(mount, leaf)
        m.verify_device(observed[source.root.path][0], source.root.identity)
        identities.append((leaf.device, leaf.inode))
        backings.append(
            (mount.device, m.backing(mount, source.root.path / source.name))
        )
    if len(set(identities)) != len(identities) or len(set(backings)) != len(backings):
        raise c.DeploymentSourceError()
    optional = tuple(
        (root, item.mountpoint, item, m.backing(item, item.mountpoint))
        for root in _OPTIONAL
        for item in mounts
        if item.mountpoint.is_relative_to(root)
    )

    def aliases(path, mount, backing, other, other_mount, other_backing):
        return (
            path.is_relative_to(other)
            or other.is_relative_to(path)
            or mount.device == other_mount.device
            and (
                backing.is_relative_to(other_backing)
                or other_backing.is_relative_to(backing)
            )
        )

    for index, (owner, path, mount, backing) in enumerate(optional):
        if any(
            aliases(path, mount, backing, other, om, ob) for other, (om, ob) in mapping
        ):
            raise c.DeploymentSourceError()
        if any(
            owner != oo and aliases(path, mount, backing, other, om, ob)
            for oo, other, om, ob in optional[:index]
        ):
            raise c.DeploymentSourceError()
    return mapping, optional


def _retain_channels(state, root, names, uid, adopted=None):
    directory = state.roots[root]
    if (directory.identity.uid, directory.identity.gid, directory.identity.mode) != (
        uid,
        21201,
        0o750,
    ) or f.members(directory.fd, 2) != set(names):
        raise c.DeploymentSourceError()
    for index, name in enumerate(names):
        if adopted is None:
            child = f.Directory.open(root / name, uid=uid, gid=21201, mode=0o750)
            state.owned.append(child)
        else:
            child = adopted[index]
        if child.identity.device != directory.identity.device:
            raise c.DeploymentSourceError()
        snapshot = _snapshot_provider_namespace(child, namespace=name)
        if adopted is not None and snapshot.entries:
            raise c.DeploymentSourceError()
        state.namespaces[name] = child, snapshot


def _recheck_guard(state, publication=None):
    state.inputs.recheck_current()
    if (
        m.native_platform() != state.inputs.instance["platform"]
        or _observe_boundaries(state.inputs, state.originals) != state.mapping
    ):
        raise c.DeploymentSourceError()
    identities = []
    for source, raw, signature in state.originals:
        if (
            source.read_current() != raw
            or f.signature(f.stat_fd(source.root.fd)) != signature
        ):
            raise c.DeploymentSourceError()
        identities.append((source.root.identity.device, source.root.identity.inode))
    for root, directory in state.roots.items():
        directory.recheck_current()
        m.verify_device(dict(state.mapping[0])[root][0], directory.identity)
        identities.append((directory.identity.device, directory.identity.inode))
        if publication is not None and root == _ROOTS[0]:
            publication.recheck_current()
        elif (
            f.signature(f.stat_fd(directory.fd)),
            tuple(sorted(f.members(directory.fd, 2))),
        ) != state.root_snapshots[root]:
            raise c.DeploymentSourceError()
    if len(set(identities)) != len(identities):
        raise c.DeploymentSourceError()
    if (
        state.bundle is not None
        and state.bundle.read_current() != state.inputs.output.bundle_files
    ):
        raise c.DeploymentSourceError()
    count = 0
    for name, (directory, snapshot) in state.namespaces.items():
        if _snapshot_provider_namespace(directory, namespace=name) != snapshot:
            raise c.DeploymentSourceError()
        count += snapshot.final_count + snapshot.stage_count
    if count > 240:
        raise c.DeploymentSourceError()
    state.inputs.recheck_current()


def _reopen_owned_root(state, root, uid):
    previous = state.roots[root]
    directory = f.Directory.open(root, uid=uid, gid=21201, mode=0o750)
    state.owned.append(directory)
    if (directory.identity.device, directory.identity.inode) != (
        previous.identity.device,
        previous.identity.inode,
    ):
        raise c.DeploymentSourceError()
    state.roots[root] = directory
    state.root_snapshots[root] = (
        f.signature(f.stat_fd(directory.fd)),
        tuple(sorted(f.members(directory.fd, 2))),
    )
    # The old root stays retained until the staged/final overlap comparison completes.


def initialize_provider_sources() -> dict[str, str]:
    if os.geteuid() != 0:
        raise c.DeploymentSourceUnavailable()
    owned, primary = [], None
    try:
        native = m.native_platform()
        inputs = _open_inputs()
        owned.append(inputs)
        if inputs.instance["platform"] != native:
            raise c.DeploymentSourceError()
        state = SimpleNamespace(
            inputs=inputs,
            owned=owned,
            originals=[],
            roots={},
            root_snapshots={},
            namespaces={},
            bundle=None,
        )
        old = inputs.output.original_artifacts
        for (root, name, gid), raw in zip(
            _ORIGINALS,
            (
                old.prepare_artifacts.topology_bytes,
                old.prepare_artifacts.exchange_bytes,
                old.trust_bytes,
                old.ingress_bytes,
                old.consumption_exchange_bytes,
            ),
            strict=True,
        ):
            source = f.SourceFile.open(
                root, name, uid=0, gid=gid, cap=len(raw), pin=c.digest(raw)
            )
            owned.append(source)
            if source.read_current() != raw:
                raise c.DeploymentSourceError()
            state.originals.append(
                (source, raw, f.signature(f.stat_fd(source.root.fd)))
            )
        state.mapping = _observe_boundaries(inputs, state.originals)
        virgin = {}
        for root in _ROOTS:
            directory = f.Directory.open(root)
            owned.append(directory)
            state.roots[root] = directory
            virgin[root] = pf._empty(directory)
            state.root_snapshots[root] = (
                f.signature(f.stat_fd(directory.fd)),
                tuple(sorted(f.members(directory.fd, 2))),
            )
        if not virgin[_ROOTS[0]]:
            state.bundle = _open_provider_bundle(
                state.roots[_ROOTS[0]],
                context_sha256=c.digest(inputs.output.context_bytes),
            )
            owned.append(state.bundle)
            if state.bundle.read_current() != inputs.output.bundle_files:
                raise c.DeploymentSourceError()
        for root, names, uid in _CHANNELS:
            if not virgin[root]:
                _retain_channels(state, root, names, uid)
        _recheck_guard(state)
        if virgin[_ROOTS[0]]:
            staged = _stage_bundle(state.roots[_ROOTS[0]], inputs.output.bundle_files)
            owned.append(staged)
            _recheck_guard(state, staged)
            _commit_bundle(staged)
            _reopen_owned_root(state, _ROOTS[0], 0)
            final = _open_provider_bundle(
                state.roots[_ROOTS[0]],
                context_sha256=c.digest(inputs.output.context_bytes),
            )
            owned.append(final)
            if (
                final._object_identities() != staged._object_identities()
                or final.read_current() != inputs.output.bundle_files
            ):
                raise c.DeploymentSourceError()
            state.bundle = final
            staged.close()
            _recheck_guard(state)
        for root, names, uid in _CHANNELS:
            if virgin[root]:
                _recheck_guard(state)
                children = pf._install_namespaces_retained(
                    state.roots[root], names=names, uid=uid, gid=21201
                )
                owned.extend(children)
                _reopen_owned_root(state, root, uid)
                _retain_channels(state, root, names, uid, children)
                _recheck_guard(state)
        _recheck_guard(state)
        return {
            key: inputs.pins[key]
            for key in ("context_sha256", "geometry_sha256", "provider_recipe_sha256")
        }
    except BaseException as error:
        primary = error
        if isinstance(error, OSError):
            raise c.DeploymentSourceError() from None
        raise
    finally:
        failure = None
        for handle in reversed(owned):
            try:
                handle.close()
            except BaseException as error:  # noqa: BLE001 - preserve primary; finish cleanup
                if failure is None:
                    failure = error
        if primary is None and failure is not None:
            raise failure


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print(c.DeploymentSourceError.code, file=sys.stderr)
        return 2
    try:
        initialize_provider_sources()
    except c.DeploymentSourceError as error:
        print(error.code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
