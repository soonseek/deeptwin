"""UID0 one-shot initializer for only the five fixed public receipt roots."""

import os
import sys
from base64 import urlsafe_b64encode
from pathlib import Path

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import mounts as m
from app.deployment import public_init_files as public_files
from app.deployment.receipt_contracts import ReceiptWireError, parse_receipt
from app.deployment.receipt_publication import validate_consumed_marker
from app.deployment.receipt_render import render_receipt_sources
from app.operations.setup import OriginProfile

_PublicInputFile = public_files._PublicInputFile
_ReleaseInput = public_files._ReleaseInput
_empty = public_files._empty
_install_source = public_files._install_source_retained
_install_namespaces = public_files._install_namespaces_retained

INPUT_ROOT = Path("/run/deeptwin/receipt-init-input")
TRUST_ROOT = Path("/run/deeptwin/deployment-verify-public")
INGRESS_ROOT = Path("/run/deeptwin/deployment-receipt-ingress")
CONSUMPTION_ROOT = Path("/run/deeptwin/deployment-consumption-exchange")
INCOMING_ROOT = Path("/run/deeptwin/deployment-receipts")
CONSUMED_ROOT = Path("/run/deeptwin/deployment-consumed")

_INPUT_SPECS = (
    ("prepare-instance.json", 4096),
    ("receipt-instance.json", 4096),
    ("trust-set.json", 16384),
    ("receipt-source-pins.json", 4096),
)
_RELEASE_SPECS = (
    ("deploy/compose.yaml", 1048576),
    ("deploy/security/service-ids.json", 65536),
    ("deploy/security/deployment-prepare-recipe-v1.json", 4096),
    ("deploy/security/deployment-receipt-recipe-v1.json", 4096),
)
_SOURCE_SPECS = (
    (TRUST_ROOT, "trust-set.json", 20102, "trust_bytes"),
    (INGRESS_ROOT, "ingress.json", 21201, "ingress_bytes"),
    (
        CONSUMPTION_ROOT,
        "consumption-exchange.json",
        21201,
        "consumption_exchange_bytes",
    ),
)
_CHANNEL_SPECS = (
    (INCOMING_ROOT, "receipts", 20113, f._INCOMING_NAMESPACE),
    (CONSUMED_ROOT, "consumed", 20102, f._CONSUMED_NAMESPACE),
)
_ROOTS = tuple(item[0] for item in (*_SOURCE_SPECS, *_CHANNEL_SPECS))


class _ReceiptInitInputs(f.RetainedHandle):
    def recheck_current(self):
        if self._closed:
            raise c.DeploymentSourceError()
        self._directory.recheck_current()
        if f.members(self._directory.fd, 4) != set(self._input_files):
            raise c.DeploymentSourceError()
        for name, source in self._input_files.items():
            if source.read_current() != self._input_bytes[name]:
                raise c.DeploymentSourceError()
        for relative, source in self._release_files.items():
            if source.read_current() != self._release_bytes[relative]:
                raise c.DeploymentSourceError()
        if f.members(self._directory.fd, 4) != set(self._input_files):
            raise c.DeploymentSourceError()

    def close(self):
        if not self._closed:
            self._closed = True
            for source in self._input_files.values():
                source.close()
            for source in self._release_files.values():
                source.close()
            if self._directory is not None:
                self._directory.close()


def _open_inputs():
    result = object.__new__(_ReceiptInitInputs)
    result._closed = False
    result._input_files, result._release_files = {}, {}
    result._directory = None
    try:
        result._directory = f.Directory.open(INPUT_ROOT, uid=0, gid=0, mode=0o750)
        if f.members(result._directory.fd, 4) != {name for name, _cap in _INPUT_SPECS}:
            raise c.DeploymentSourceError()
        for name, cap in _INPUT_SPECS:
            result._input_files[name] = _PublicInputFile.open(
                result._directory,
                name,
                cap=cap,
                modes=(0o440,),
            )
        for relative, cap in _RELEASE_SPECS:
            result._release_files[relative] = _ReleaseInput.open(relative, cap)
        result._input_bytes = {
            name: source.read_current() for name, source in result._input_files.items()
        }
        result._release_bytes = {
            relative: source.read_current()
            for relative, source in result._release_files.items()
        }
        result.recheck_current()
        result.output = render_receipt_sources(
            result._release_bytes["deploy/compose.yaml"],
            result._release_bytes["deploy/security/service-ids.json"],
            result._release_bytes["deploy/security/deployment-prepare-recipe-v1.json"],
            result._input_bytes["prepare-instance.json"],
            result._release_bytes["deploy/security/deployment-receipt-recipe-v1.json"],
            result._input_bytes["receipt-instance.json"],
            result._input_bytes["trust-set.json"],
        )
        if result._input_bytes["receipt-source-pins.json"] != result.output.pins_bytes:
            raise c.DeploymentSourceError()
        result.pins = c.parse(
            result.output.pins_bytes,
            cap=4096,
            depth=4,
            items=96,
        )
        result.instance = c.parse_instance(result._input_bytes["prepare-instance.json"])
        result.profile = OriginProfile.from_dict(result.instance["origin_profile"])
        result.recheck_current()
        return result
    except (OSError, c.DeploymentSourceError):
        result.close()
        raise c.DeploymentSourceError() from None


def _retained_release_ancestors(inputs):
    return tuple(
        dict.fromkeys(
            handle.path
            for source in inputs._release_files.values()
            for handle in source._ancestors
            if handle.path.is_relative_to(c.RELEASE_ROOT)
        )
    )


def _protected_paths(inputs):
    return (
        *_retained_release_ancestors(inputs),
        *(c.RELEASE_ROOT / relative for relative, _cap in _RELEASE_SPECS),
        INPUT_ROOT,
        *(INPUT_ROOT / name for name, _cap in _INPUT_SPECS),
    )


def _observe_boundaries(inputs):
    mounts = m.read_mountinfo()
    protected = _protected_paths(inputs)
    mapping = m.verify_boundaries(
        mounts,
        dict.fromkeys(_ROOTS, False),
        protected,
    )
    observed = dict(mapping)
    if any(not observed[path][0].read_only for path in protected):
        raise c.DeploymentSourceError()
    m.verify_device(observed[INPUT_ROOT][0], inputs._directory.identity)
    for source in inputs._release_files.values():
        for handle in source._ancestors:
            if handle.path.is_relative_to(c.RELEASE_ROOT):
                m.verify_device(observed[handle.path][0], handle.identity)
    leaf_identities = []
    leaf_backings = []
    for name, source in inputs._input_files.items():
        path = INPUT_ROOT / name
        m.verify_device(observed[path][0], source.identity)
        leaf_identities.append(source.identity)
        leaf_backings.append((observed[path][0].device, observed[path][1]))
    for relative, source in inputs._release_files.items():
        path = c.RELEASE_ROOT / relative
        m.verify_device(observed[path][0], source.identity)
        leaf_identities.append(source.identity)
        leaf_backings.append((observed[path][0].device, observed[path][1]))
    if len({(item.device, item.inode) for item in leaf_identities}) != len(
        leaf_identities
    ) or len(set(leaf_backings)) != len(leaf_backings):
        raise c.DeploymentSourceError()
    return mapping


def _expected_source(output, field):
    return getattr(output, field)


def _open_source(root, name, gid, raw):
    source = f.SourceFile.open(
        root,
        name,
        uid=0,
        gid=gid,
        cap=len(raw),
        pin=c.digest(raw),
    )
    try:
        if source.read_current() != raw:
            raise c.DeploymentSourceError()
        return source
    except (OSError, c.DeploymentSourceError):
        source.close()
        raise c.DeploymentSourceError() from None


def _receipt_selector(filename):
    return urlsafe_b64encode(bytes.fromhex(filename[:-5])).rstrip(b"=").decode("ascii")


def _validate_incoming(raw, filename, *, profile, ingress):
    if c.digest(raw) != filename[:-5]:
        raise c.DeploymentSourceError()
    receipt = parse_receipt(raw)
    expected_origin = (
        urlsafe_b64encode(bytes.fromhex(profile.digest)).rstrip(b"=").decode("ascii")
    )
    expected_trust = (
        urlsafe_b64encode(bytes.fromhex(ingress["trust_set_digest"]))
        .rstrip(b"=")
        .decode("ascii")
    )
    if (
        receipt["instance_id"] != profile.instance_id
        or receipt["origin_profile_digest"] != expected_origin
        or receipt["deployment_profile_id"] != profile.deployment_profile_id
        or receipt["trust_set_digest"] != expected_trust
    ):
        raise c.DeploymentSourceError()


class _RetainedChannel(f.RetainedHandle):
    @classmethod
    def open(
        cls,
        directory,
        name,
        uid,
        policy,
        *,
        profile,
        ingress,
        namespace=None,
    ):
        opened = []
        owns_namespace = namespace is None
        try:
            if namespace is None:
                namespace = f.Directory.open(
                    directory.path / name,
                    uid=uid,
                    gid=21201,
                    mode=0o750,
                )
            result = cls()
            result._directory, result._namespace = directory, namespace
            result._name, result._uid, result._policy = name, uid, policy
            result._profile, result._ingress = profile, ingress
            result._closed = False
            result._validate_root()
            scan = f._scan_namespace(namespace, policy=policy)
            if scan.stages:
                raise c.DeploymentSourceError()
            finals = []
            for entry in scan.finals:
                selected = f._open_final(namespace, entry, policy=policy)
                opened.append(selected)
                raw = selected.read_current()
                result._validate_final(entry.name, raw)
                finals.append((entry, selected, raw))
            result._scan, result._finals = scan, tuple(finals)
            result.recheck_current()
            return result
        except (OSError, ReceiptWireError, c.DeploymentSourceError):
            for selected in opened:
                selected.close()
            if owns_namespace and namespace is not None:
                namespace.close()
            raise c.DeploymentSourceError() from None

    def _validate_root(self):
        identity = self._directory.recheck_current()
        if (identity.uid, identity.gid, identity.mode) != (
            self._uid,
            21201,
            0o750,
        ) or f.members(self._directory.fd, 1) != {self._name}:
            raise c.DeploymentSourceError()
        namespace_identity = self._namespace.recheck_current()
        if namespace_identity.device != identity.device:
            raise c.DeploymentSourceError()

    def _validate_final(self, filename, raw):
        if self._name == "receipts":
            _validate_incoming(
                raw,
                filename,
                profile=self._profile,
                ingress=self._ingress,
            )
        else:
            validate_consumed_marker(
                receipt_digest=_receipt_selector(filename),
                payload=raw,
            )

    def recheck_current(self):
        if self._closed:
            raise c.DeploymentSourceError()
        self._validate_root()
        scan = f._scan_namespace(self._namespace, policy=self._policy)
        if scan.stages:
            raise c.DeploymentSourceError()
        if scan != self._scan:
            raise c.DeploymentSourceError()
        for entry, selected, expected in self._finals:
            raw = selected.read_current()
            if raw != expected:
                raise c.DeploymentSourceError()
            self._validate_final(entry.name, raw)
        if f._scan_namespace(self._namespace, policy=self._policy) != self._scan:
            raise c.DeploymentSourceError()
        self._validate_root()

    def close(self):
        if not self._closed:
            self._closed = True
            for _entry, selected, _raw in self._finals:
                selected.close()
            self._namespace.close()


def _retain_existing_roots(directories, empties, inputs, handles):
    ingress = c.parse(
        inputs.output.ingress_bytes,
        cap=8192,
        depth=8,
        items=256,
    )
    bindings = {}
    for root, name, gid, field in _SOURCE_SPECS:
        if not empties[root]:
            raw = _expected_source(inputs.output, field)
            source = _open_source(root, name, gid, raw)
            handles.append(source)
            bindings[root] = (source, raw)
    for root, name, uid, policy in _CHANNEL_SPECS:
        if not empties[root]:
            channel = _RetainedChannel.open(
                directories[root],
                name,
                uid,
                policy,
                profile=inputs.profile,
                ingress=ingress,
            )
            handles.append(channel)
            bindings[root] = channel
    return bindings


def _recheck_bindings(bindings):
    for root, _name, _gid, _field in _SOURCE_SPECS:
        if root in bindings:
            source, raw = bindings[root]
            if source.read_current() != raw:
                raise c.DeploymentSourceError()
    for root, _name, _uid, _policy in _CHANNEL_SPECS:
        if root in bindings:
            bindings[root].recheck_current()


def _recheck_guard(inputs, directories, mapping, bindings):
    inputs.recheck_current()
    current = _observe_boundaries(inputs)
    if current != mapping:
        raise c.DeploymentSourceError()
    identities = []
    observed = dict(mapping)
    for root, directory in directories.items():
        identity = directory.recheck_current()
        identities.append(identity)
        m.verify_device(observed[root][0], identity)
    if len({(item.device, item.inode) for item in identities}) != len(identities):
        raise c.DeploymentSourceError()
    _recheck_bindings(bindings)
    inputs.recheck_current()


def _reopen_root(directories, handles, root, uid, gid):
    previous = directories[root]
    expected_object = (previous.identity.device, previous.identity.inode)
    previous.close()
    directory = None
    try:
        directory = f.Directory.open(root, uid=uid, gid=gid, mode=0o750)
        if (directory.identity.device, directory.identity.inode) != expected_object:
            raise c.DeploymentSourceError()
    except (OSError, c.DeploymentSourceError):
        if directory is not None:
            directory.close()
        raise c.DeploymentSourceError() from None
    directories[root] = directory
    handles.append(directory)


def initialize_receipt_public_sources():
    """Validate every fixed input/root, then initialize only genuinely empty roots."""
    if os.geteuid() != 0:
        raise c.DeploymentSourceUnavailable()
    inputs = None
    handles = []
    try:
        native = m.native_platform()
        inputs = _open_inputs()
        if inputs.instance["platform"] != native:
            raise c.DeploymentSourceError()
        mapping = _observe_boundaries(inputs)
        observed = dict(mapping)
        directories = {}
        empties = {}
        for root in _ROOTS:
            directory = f.Directory.open(root)
            directories[root] = directory
            handles.append(directory)
            m.verify_device(observed[root][0], directory.identity)
            empties[root] = _empty(directory)
        if len(
            {
                (item.identity.device, item.identity.inode)
                for item in directories.values()
            }
        ) != len(directories):
            raise c.DeploymentSourceError()
        bindings = _retain_existing_roots(directories, empties, inputs, handles)
        _recheck_guard(inputs, directories, mapping, bindings)

        for root, name, gid, field in _SOURCE_SPECS:
            if empties[root]:
                _recheck_guard(inputs, directories, mapping, bindings)
                source = _install_source(
                    directories[root],
                    name,
                    _expected_source(inputs.output, field),
                    gid,
                )
                handles.append(source)
                _reopen_root(directories, handles, root, 0, gid)
                source.rebind_directory(directories[root])
                bindings[root] = (
                    source,
                    _expected_source(inputs.output, field),
                )
                _recheck_guard(inputs, directories, mapping, bindings)
        ingress = c.parse(
            inputs.output.ingress_bytes,
            cap=8192,
            depth=8,
            items=256,
        )
        for root, name, uid, policy in _CHANNEL_SPECS:
            if empties[root]:
                _recheck_guard(inputs, directories, mapping, bindings)
                (namespace,) = _install_namespaces(
                    directories[root], names=(name,), uid=uid, gid=21201
                )
                handles.append(namespace)
                _reopen_root(directories, handles, root, uid, 21201)
                channel = _RetainedChannel.open(
                    directories[root],
                    name,
                    uid,
                    policy,
                    profile=inputs.profile,
                    ingress=ingress,
                    namespace=namespace,
                )
                handles.append(channel)
                bindings[root] = channel
                _recheck_guard(inputs, directories, mapping, bindings)

        _recheck_bindings(bindings)
        _recheck_guard(inputs, directories, mapping, bindings)
        _recheck_bindings(bindings)
        inputs.recheck_current()
        if _observe_boundaries(inputs) != mapping:
            raise c.DeploymentSourceError()
        inputs.recheck_current()
        return {
            "trust_sha256": inputs.pins["trust_sha256"],
            "ingress_sha256": inputs.pins["ingress_sha256"],
            "consumption_exchange_sha256": inputs.pins["consumption_exchange_sha256"],
        }
    except ReceiptWireError:
        raise c.DeploymentSourceError() from None
    except OSError:
        raise c.DeploymentSourceError() from None
    finally:
        for handle in handles:
            handle.close()
        if inputs is not None:
            inputs.close()


def main():
    try:
        initialize_receipt_public_sources()
    except c.DeploymentSourceError as error:
        print(error.code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print(c.DeploymentSourceError.code, file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main())
