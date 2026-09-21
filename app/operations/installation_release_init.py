"""Root-owned fixed release-source initialization with independently derived context."""
import os
from pathlib import Path

from app.deployment import contracts as c, files as f, mounts as m, public_init_files as pf
from app.deployment import installation_release_contracts as r
from app.deployment._provider_source_files import _open_provider_bundle
from app.deployment.installation_release_sources import _open_bundle
from app.deployment.source_common import _source_mount_observations
from app.operations.setup import OriginProfile
from ._installation_release_init_files import _stage_bundle, _commit_bundle

_PROVIDER_ROOT = Path('/run/deeptwin/provider-stage-sources')


def initialize_installation_release_sources() -> dict:
    if os.geteuid() != 0: raise c.DeploymentSourceUnavailable()
    owned,primary = [],None
    try:
        platform = m.native_platform()
        directory = f.Directory.open(r.INPUT_ROOT,uid=0,gid=0,mode=0o750)
        owned.append(directory)
        r._require(f.members(directory.fd,2) == {name for name,_ in r.LAYOUT})
        inputs = []
        for name,cap in r.LAYOUT:
            leaf = pf._PublicInputFile.open(directory,name,cap=cap,modes=(0o440,))
            owned.append(leaf)
            inputs.append(leaf)
        trust,context = (leaf.read_current() for leaf in inputs)
        parsed = r.parse_release_context(context).as_dict()
        provider_root = f.Directory.open(_PROVIDER_ROOT,uid=0,gid=21201,mode=0o750)
        owned.append(provider_root)
        provider = _open_provider_bundle(provider_root,context_sha256=parsed['provider_source_context']['sha256'])
        owned.append(provider)
        provider_files = provider.read_current()
        profile = OriginProfile.from_dict(c.parse_instance(dict(provider_files)['original-prepare-instance.json'])['origin_profile'])
        independently_derived = r._context_bytes(provider_files,trust,profile)
        r._require(context == independently_derived and parsed['platform'] == platform)
        files = tuple(zip((name for name,_ in r.LAYOUT),(trust,context),strict=True))
        r.validate_release_sources(files,provider_files=provider_files,profile=profile)
        root = f.Directory.open(r.ROOT)
        owned.append(root)
        required = {r.ROOT:False,_PROVIDER_ROOT:True}
        protected = (r.INPUT_ROOT,*(r.INPUT_ROOT / name for name,_ in r.LAYOUT))
        mapping = _source_mount_observations(m.read_mountinfo(),required,protected)
        for path in protected: r._require(dict(mapping[0])[path][0].read_only)
        for d in (root,provider_root,directory): m.verify_device(dict(mapping[0])[d.path][0],d.identity)
        source_identities = [directory.identity,provider_root.identity,provider._directory.identity,
                             *(leaf.identity for leaf in inputs),
                             *(signature[0] for _,signature,_ in provider._leaves.values())]
        source_identities.append(root.identity)
        r._require(len({(i.device,i.inode) for i in source_identities}) == len(source_identities))
        root_signature = f.signature(f.stat_fd(root.fd))
        input_signature = f.signature(f.stat_fd(directory.fd))

        def guard(publication=None):
            r._require(m.native_platform() == platform)
            r._require(_source_mount_observations(m.read_mountinfo(),required,protected) == mapping)
            directory.recheck_current()
            r._require(f.signature(f.stat_fd(directory.fd)) == input_signature)
            r._require(f.members(directory.fd,2) == {name for name,_ in r.LAYOUT})
            r._require(tuple(leaf.read_current() for leaf in inputs) == (trust,context))
            r._require(provider.read_current() == provider_files)
            if publication is None:
                root.recheck_current()
                r._require(f.signature(f.stat_fd(root.fd)) == root_signature)
            else: publication.recheck_current()

        guard()
        if f.members(root.fd,1):
            final = _open_bundle(root,context_sha256=c.digest(context))
            owned.append(final)
            r._require(final.read_current() == files)
            guard()
        else:
            staged = _stage_bundle(root,files)
            owned.append(staged)
            guard(staged)
            _commit_bundle(staged)
            guard(staged)
            reopened = f.Directory.open(r.ROOT,uid=0,gid=21201,mode=0o750)
            owned.append(reopened)
            r._require((reopened.identity.device,reopened.identity.inode) == (root.identity.device,root.identity.inode))
            final = _open_bundle(reopened,context_sha256=c.digest(context))
            owned.append(final)
            r._require(final.read_current() == files)
            r._require(final.directory.identity == staged.directory_identity)
            r._require(tuple(signature[0] for _,signature,_ in final.leaves) ==
                       tuple(signature[0] for _,signature in staged.leaves))
            guard(staged)
        return {'context_sha256':c.digest(context)}
    except BaseException as error:
        primary = error
        if isinstance(error,OSError): raise c.DeploymentSourceError() from None
        raise
    finally:
        failure = None
        for handle in reversed(owned):
            try: handle.close()
            except BaseException as error:
                if failure is None: failure = error
        if primary is None and failure is not None: raise failure


if __name__ == '__main__':
    import sys
    if sys.argv[1:]: raise SystemExit(2)
    try: initialize_installation_release_sources()
    except c.DeploymentSourceError: raise SystemExit(1)
