"""External UID0 one-shot producer at fixed image/config/mounted-volume paths."""

import os
import sys
from base64 import urlsafe_b64encode
from pathlib import Path

from app.deployment import contracts as c
from app.deployment import files as f
from app.deployment import mounts as m
from app.deployment import public_init_files as public_files
from app.deployment import publication as p
from app.deployment.render import render_prepare_sources
from app.operations.setup import OriginProfile
from app.workers import ipc_root


def _read_at(directory, name, *, cap, modes):
    return public_files._read_at(directory, name, cap=cap, modes=modes)


def _release(relative, cap):
    return public_files._release(relative, cap)


def _inputs():
    with f.Directory.open(c.INPUT_ROOT, uid=0, gid=0, mode=0o750) as directory:
        if f.members(directory.fd, 2) != {
            "prepare-instance.json",
            "prepare-source-pins.json",
        }:
            raise c.DeploymentSourceError()
        instance = _read_at(
            directory, "prepare-instance.json", cap=4096, modes=(0o440,)
        )
        pins = _read_at(directory, "prepare-source-pins.json", cap=4096, modes=(0o440,))
    base = _release("deploy/compose.yaml", 1048576)
    identities = _release("deploy/security/service-ids.json", 65536)
    recipe = _release("deploy/security/deployment-prepare-recipe-v1.json", 4096)
    artifacts = render_prepare_sources(base, identities, recipe, instance)
    if pins != artifacts.pins_bytes:
        raise c.DeploymentSourceError()
    return c.parse_instance(instance), artifacts


def _empty(directory):
    return public_files._empty(directory)


def _verify_outbox(directory, profile):
    if (directory.identity.uid, directory.identity.gid, directory.identity.mode) != (
        20102,
        21201,
        0o750,
    ):
        raise c.DeploymentSourceError()
    if f.members(directory.fd, 2) != {"cancelled", "requests"}:
        raise c.DeploymentSourceError()
    for role, name in (("request", "requests"), ("cancel", "cancelled")):
        with f.Directory.open(
            directory.path / name, uid=20102, gid=21201, mode=0o750
        ) as namespace:
            finals, stages = f.inspect_namespace(
                namespace, 65536 if role == "request" else 4096
            )
            if stages:
                raise c.DeploymentSourceError()
            for filename, raw in finals:
                request_digest = (
                    urlsafe_b64encode(bytes.fromhex(filename[:-5]))
                    .rstrip(b"=")
                    .decode("ascii")
                )
                p.validate_projection(
                    role=role,
                    request_digest=request_digest,
                    payload=raw,
                    profile=profile,
                )


def _install_source(directory, name, raw, gid):
    return public_files._install_source(directory, name, raw, gid)


def _install_outbox(directory):
    return public_files._install_namespaces(
        directory,
        names=("cancelled", "requests"),
        uid=20102,
        gid=21201,
    )


def initialize_prepare_sources():
    """Validate all fixed inputs and roots before any bounded initialization effect."""
    if os.geteuid() != 0:
        raise c.DeploymentSourceUnavailable()
    native = m.native_platform()
    handles = []
    try:
        instance, output = _inputs()
        if instance["platform"] != native:
            raise c.DeploymentSourceError()
        profile = OriginProfile.from_dict(instance["origin_profile"])
        slots = [
            c.slot(profile.instance_id, n)
            for n in range(1, instance["slot_capacity"] + 1)
        ]
        roots = (c.TOPOLOGY_ROOT, c.EXCHANGE_ROOT, c.OUTBOX_ROOT) + tuple(
            Path(s["socket_mount"]["container_path"]) for s in slots
        )
        mounts = m.read_mountinfo()
        required = dict.fromkeys(roots, False)
        protected = (
            c.RELEASE_ROOT,
            c.RELEASE_ROOT / "deploy/compose.yaml",
            c.RELEASE_ROOT / "deploy/security/service-ids.json",
            c.RELEASE_ROOT / "deploy/security/deployment-prepare-recipe-v1.json",
            c.INPUT_ROOT,
            c.INPUT_ROOT / "prepare-instance.json",
            c.INPUT_ROOT / "prepare-source-pins.json",
        )
        mapping = m.verify_boundaries(mounts, required, protected)
        if any(not m.containing(mounts, path).read_only for path in protected):
            raise c.DeploymentSourceError()
        directories = {}
        empties = {}
        for root in roots:
            directory = f.Directory.open(root)
            handles.append(directory)
            directories[root] = directory
            m.verify_device(dict(mapping)[root][0], directory.identity)
            empties[root] = _empty(directory)
        if len(
            {(d.identity.device, d.identity.inode) for d in directories.values()}
        ) != len(directories):
            raise c.DeploymentSourceError()
        for root, name, raw, gid in (
            (c.TOPOLOGY_ROOT, "topology.json", output.topology_bytes, 20102),
            (c.EXCHANGE_ROOT, "exchange.json", output.exchange_bytes, 21201),
        ):
            if not empties[root]:
                with f.SourceFile.open(
                    root, name, uid=0, gid=gid, cap=len(raw), pin=c.digest(raw)
                ) as source:
                    if source.read_current() != raw:
                        raise c.DeploymentSourceError()
        if not empties[c.OUTBOX_ROOT]:
            _verify_outbox(directories[c.OUTBOX_ROOT], profile)
        specs = []
        for slot in slots:
            root = Path(slot["socket_mount"]["container_path"])
            spec = ipc_root.PairRootSpec(
                root, slot["uid"], slot["gid"], slot["pair_gid"]
            )
            specs.append(spec)
            if not empties[root]:
                if f.members(directories[root].fd, 3) != {
                    "generation.lock",
                    "boot-secret",
                    "endpoint",
                }:
                    raise c.DeploymentSourceError()
                with ipc_root.acquire_generation_metadata(spec) as lease:
                    lease.recheck_current()
        if mapping != m.verify_boundaries(m.read_mountinfo(), required, protected):
            raise c.DeploymentSourceError()
        for directory in directories.values():
            directory.recheck_current()
        for root, name, raw, gid in (
            (c.TOPOLOGY_ROOT, "topology.json", output.topology_bytes, 20102),
            (c.EXCHANGE_ROOT, "exchange.json", output.exchange_bytes, 21201),
        ):
            if empties[root]:
                _install_source(directories[root], name, raw, gid)
        if empties[c.OUTBOX_ROOT]:
            _install_outbox(directories[c.OUTBOX_ROOT])
        for spec in specs:
            ipc_root.initialize_pair_root(spec)
        # Verify installed public sources/outbox independently after effects.
        for root, name, raw, gid in (
            (c.TOPOLOGY_ROOT, "topology.json", output.topology_bytes, 20102),
            (c.EXCHANGE_ROOT, "exchange.json", output.exchange_bytes, 21201),
        ):
            with f.SourceFile.open(
                root, name, uid=0, gid=gid, cap=len(raw), pin=c.digest(raw)
            ) as source:
                source.read_current()
        with f.Directory.open(
            c.OUTBOX_ROOT, uid=20102, gid=21201, mode=0o750
        ) as outbox:
            _verify_outbox(outbox, profile)
        if mapping != m.verify_boundaries(m.read_mountinfo(), required, protected):
            raise c.DeploymentSourceError()
        return {
            "topology_sha256": c.digest(output.topology_bytes),
            "exchange_sha256": c.digest(output.exchange_bytes),
        }
    except (OSError, ipc_root.IpcRootError):
        raise c.DeploymentSourceError() from None
    finally:
        for handle in handles:
            handle.close()


def main():
    try:
        initialize_prepare_sources()
    except c.DeploymentSourceError as error:
        print(error.code, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 1:
        print(c.DeploymentSourceError.code, file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(main())
