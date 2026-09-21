"""Startup-owned two-file source borrowing the exact retained provider source."""
from pathlib import Path

from app.operations.setup import OriginProfile
from . import contracts as c, files as f, mounts as m
from . import installation_release_contracts as r
from .provider_sources import ProviderSourceContext
from .source_common import _source_mount_observations


class _ReleaseBundle(f.RetainedHandle):
    def __init__(self):
        raise TypeError('release bundle requires retained factory')

    def read_current(self):
        try:
            r._require(not self._closed)
            self.root.recheck_current()
            self.directory.recheck_current()
            r._require(f.members(self.root.fd,1) == {'documents'})
            r._require(f.members(self.directory.fd,2) == {name for name,_ in r.LAYOUT})
            for directory,signature in self.signatures:
                r._require(f.signature(f.stat_fd(directory.fd)) == signature)
            result = []
            for (name,cap),(fd,signature,raw) in zip(r.LAYOUT,self.leaves,strict=True):
                r._require(f.signature(f.stat_fd(fd)) == signature)
                r._require(f.signature(f.stat_at(self.directory.fd,name)) == signature)
                actual = f.read_exact(fd,cap)
                r._require(actual == raw)
                result.append((name,actual))
            for (name,_),(fd,signature,_) in zip(r.LAYOUT,self.leaves,strict=True):
                r._require(f.signature(f.stat_fd(fd)) == signature)
                r._require(f.signature(f.stat_at(self.directory.fd,name)) == signature)
            r._require(f.members(self.directory.fd,2) == {name for name,_ in r.LAYOUT})
            for directory,signature in self.signatures:
                directory.recheck_current()
                r._require(f.signature(f.stat_fd(directory.fd)) == signature)
            return tuple(result)
        except OSError:
            raise c.DeploymentSourceUnavailable() from None

    def recheck_current(self):
        self.read_current()

    def close(self):
        if not self._closed:
            self._closed = True
            failure = None
            for fd in self.owned_fds:
                try: f.close_fd(fd)
                except BaseException as error:
                    if failure is None: failure = error
            if self.directory is not None:
                try: self.directory.close()
                except BaseException as error:
                    if failure is None: failure = error
            if failure is not None: raise failure


def _open_bundle(root, *, context_sha256):
    c.hex_digest(context_sha256)
    r._require(type(root) is f.Directory and root.path == r.ROOT)
    r._require((root.identity.uid,root.identity.gid,root.identity.mode) == (0,21201,0o750))
    result = object.__new__(_ReleaseBundle)
    result._closed,result.root,result.directory = False,root,None
    result.owned_fds,result.leaves = [],[]
    try:
        root.recheck_current()
        result.directory = f.Directory.open(r.ROOT / 'documents',uid=0,gid=21201,mode=0o750)
        r._require(result.directory.identity.device == root.identity.device)
        result.signatures = tuple((d,f.signature(f.stat_fd(d.fd))) for d in (root,result.directory))
        for name,cap in r.LAYOUT:
            fd = f.open_regular(result.directory.fd,name,uid=0,gid=21201,mode=0o440,cap=cap)
            result.owned_fds.append(fd)
            signature = f.signature(f.stat_fd(fd))
            r._require(signature[0].device == root.identity.device)
            raw = f.read_exact(fd,cap)
            result.leaves.append((fd,signature,raw))
        raw = result.read_current()
        r._require(c.digest(raw[1][1]) == context_sha256)
        return result
    except BaseException:
        try: result.close()
        except BaseException: pass
        raise


class InstallationReleaseSource(f.RetainedHandle):
    def __init__(self):
        raise TypeError('installation release source requires fixed factory')

    def _mounts(self):
        return _source_mount_observations(m.read_mountinfo(),{r.ROOT:True},tuple(d.path for d in self._protected))

    def read_current(self):
        try:
            r._require(type(self) is InstallationReleaseSource and not self._closed)
            r._require(m.native_platform() == self._platform)
            provider = self._provider_context.read_current()
            r._require(provider == self._provider_bytes)
            r._require(self._mounts() == self._mapping)
            raw = self._bundle.read_current()
            for directory in self._protected: directory.recheck_current()
            r.validate_release_sources(raw,provider_files=provider,profile=self._profile)
            r._require(self._provider_context.read_current() == provider)
            r._require(self._mounts() == self._mapping)
            r._require(self._bundle.read_current() == raw)
            return raw
        except OSError:
            raise c.DeploymentSourceUnavailable() from None
        except BaseException as error:
            if not isinstance(error,Exception):
                try: self.close()
                except BaseException: pass
            raise

    def recheck_current(self):
        self.read_current()

    def close(self):
        if not getattr(self,'_closed',True):
            self._closed = True
            failure = None
            for handle in reversed(self._owned):
                try: handle.close()
                except BaseException as error:
                    if failure is None: failure = error
            if failure is not None: raise failure


def open_installation_release_sources(*,profile,context_sha256,provider_source_context,protected_roots):
    c.hex_digest(context_sha256)
    r._require(type(profile) is OriginProfile and type(provider_source_context) is ProviderSourceContext)
    r._require(type(protected_roots) is tuple and len(protected_roots) <= 64)
    for path in protected_roots:
        r._require(isinstance(path,Path) and path.is_absolute() and '..' not in path.parts)
    result = object.__new__(InstallationReleaseSource)
    result._closed,result._owned,result._protected = False,[],[]
    result._profile,result._provider_context = profile,provider_source_context
    try:
        result._platform = m.native_platform()
        result._provider_bytes = provider_source_context.read_current()
        root = f.Directory.open(r.ROOT,uid=0,gid=21201,mode=0o750)
        result._owned.append(root)
        result._bundle = _open_bundle(root,context_sha256=context_sha256)
        result._owned.append(result._bundle)
        identities = [root.identity,result._bundle.directory.identity,
                      *(signature[0] for _,signature,_ in result._bundle.leaves)]
        for path in dict.fromkeys((*c.BUILTIN_ROOTS,*protected_roots)):
            directory = f.Directory.open(path,search=True)
            result._owned.append(directory)
            result._protected.append(directory)
            identities.append(directory.identity)
        r._require(len({(i.device,i.inode) for i in identities}) == len(identities))
        result._mapping = result._mounts()
        mapping = dict(result._mapping[0])
        for directory in (root,*result._protected): m.verify_device(mapping[directory.path][0],directory.identity)
        raw = result._bundle.read_current()
        r._require(r.parse_release_context(raw[1][1]).as_dict()['platform'] == result._platform)
        result.recheck_current()
        return result
    except BaseException as error:
        try: result.close()
        except BaseException: pass
        if isinstance(error,OSError): raise c.DeploymentSourceUnavailable() from None
        raise
