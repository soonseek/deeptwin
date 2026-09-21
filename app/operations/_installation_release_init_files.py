"""Fixed two-file no-replace publication; no general filesystem policy interface."""
import os
from uuid import uuid4

from app.deployment import files as f, publication as p
from app.deployment import installation_release_contracts as r


class _Publication(f.RetainedHandle):
    def __init__(self):
        raise TypeError('publication requires fixed staging')

    def recheck_current(self):
        r._require(not self._closed)
        identity = f.identity(f.stat_fd(self.root.fd))
        r._require((identity.device,identity.inode) == (self.root.identity.device,self.root.identity.inode))
        if not self.committed:
            self.root.recheck_current()
            r._require(f.signature(f.stat_fd(self.root.fd)) == self.root_signature)
        else: r._require((identity.uid,identity.gid,identity.mode) == (0,21201,0o750))
        r._require(f.members(self.root.fd,1) == {self.name})
        r._require(f.identity(f.stat_at(self.root.fd,self.name)) == self.directory_identity)
        r._require(f.identity(f.stat_fd(self.fd)) == self.directory_identity)
        r._require(f.members(self.fd,2) == {name for name,_ in r.LAYOUT})
        for (name,raw),(fd,signature) in zip(self.files,self.leaves,strict=True):
            r._require(f.signature(f.stat_fd(fd)) == signature)
            r._require(f.signature(f.stat_at(self.fd,name)) == signature)
            r._require(f.read_exact(fd,len(raw)) == raw)

    def close(self):
        if not self._closed:
            self._closed = True
            failure = None
            for fd in self.owned:
                try: f.close_fd(fd)
                except BaseException as error:
                    if failure is None: failure = error
            if failure is not None: raise failure


def _stage_bundle(root,files):
    r._require(type(root) is f.Directory and root.path == r.ROOT)
    r._require((root.identity.uid,root.identity.gid,root.identity.mode) == (0,0,0o755))
    r._require(not f.members(root.fd,1))
    r._require(tuple(name for name,_ in files) == tuple(name for name,_ in r.LAYOUT))
    for (_,raw),(_,cap) in zip(files,r.LAYOUT,strict=True): r._require(type(raw) is bytes and 0 < len(raw) <= cap)
    r.parse_release_trust(files[0][1])
    r.parse_release_context(files[1][1])
    result = object.__new__(_Publication)
    result._closed,result.committed,result.root,result.files = False,False,root,files
    result.owned,result.leaves = [],[]
    result.name = f'.stage-{uuid4()}.tmp'
    try:
        root.recheck_current()
        os.mkdir(result.name,0o700,dir_fd=root.fd)
        result.fd = os.open(result.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=root.fd)
        result.owned.append(result.fd)
        initial = f.identity(f.stat_fd(result.fd))
        r._require(initial == f.identity(f.stat_at(root.fd,result.name)) and initial.device == root.identity.device)
        for name,raw in files:
            fd = os.open(name,os.O_RDWR|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=result.fd)
            result.owned.append(fd)
            p._write_all(fd,raw)
            os.fchown(fd,0,21201)
            os.fchmod(fd,0o440)
            os.fsync(fd)
            info = f.stat_fd(fd)
            f.validate_regular(info,uid=0,gid=21201,mode=0o440,cap=len(raw))
            r._require(info.st_dev == initial.device)
            result.leaves.append((fd,f.signature(info)))
        os.fchown(result.fd,0,21201)
        os.fchmod(result.fd,0o750)
        os.fsync(result.fd)
        result.directory_identity = f.validate_directory(result.fd,uid=0,gid=21201,mode=0o750)
        r._require((result.directory_identity.device,result.directory_identity.inode) == (initial.device,initial.inode))
        result.root_signature = f.signature(f.stat_fd(root.fd))
        result.recheck_current()
        return result
    except BaseException:
        try: result.close()
        except BaseException: pass
        raise


def _commit_bundle(publication):
    r._require(type(publication) is _Publication and not publication.committed)
    publication.recheck_current()
    p._rename_noreplace(publication.root.fd,publication.name,'documents')
    publication.name = 'documents'
    os.fsync(publication.root.fd)
    os.fchown(publication.root.fd,0,21201)
    os.fchmod(publication.root.fd,0o750)
    os.fsync(publication.root.fd)
    publication.committed = True
    publication.recheck_current()
