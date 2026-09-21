import importlib
import pytest
from pathlib import Path
from app.tests.provider_source_reader_fixture import ReaderTree
from app.tests.installation_release_fixture import ROOT, trust_document
from app.domain.refs import canonical_json


def init_tree(tmp_path,monkeypatch):
    import os
    from app.deployment import files as f, publication as p
    from app.deployment.installation_release_contracts import _context_bytes, INPUT_ROOT
    tree = ReaderTree(tmp_path,monkeypatch)
    trust = canonical_json(trust_document(tree.bundle))
    context = _context_bytes(tree.bundle,trust,tree.profile)
    tree.directory(ROOT,0,0)
    tree.actual(ROOT).chmod(0o755)
    tree.mount(ROOT,False)
    tree.directory(INPUT_ROOT,0,0)
    tree.mount(INPUT_ROOT,True)
    tree.write(INPUT_ROOT / 'release-trust.json',trust,0,0)
    tree.write(INPUT_ROOT / 'installation-release-context.json',context,0,0)
    monkeypatch.setattr(os,'geteuid',lambda:0)
    def chown(fd,uid,gid):
        info = tree.raw_fstat(fd)
        tree.metadata[(info.st_dev,info.st_ino)] = uid,gid
    monkeypatch.setattr(os,'fchown',chown)
    def rename(fd,old,new):
        try: tree.raw_stat(new,dir_fd=fd,follow_symlinks=False)
        except FileNotFoundError: os.rename(old,new,src_dir_fd=fd,dst_dir_fd=fd)
        else: raise ValueError('synthetic no-replace conflict')
    monkeypatch.setattr(p,'_rename_noreplace',rename)
    return tree,context


def test_fixed_initializer_rejects_non_root_without_mutation(monkeypatch):
    try:
        module = importlib.import_module('app.operations.installation_release_init')
    except ModuleNotFoundError:
        pytest.fail('Actual installation release initializer is missing')
    monkeypatch.setattr(module.os, 'geteuid', lambda: 1000)
    from app.deployment.contracts import DeploymentSourceUnavailable
    with pytest.raises(DeploymentSourceUnavailable): module.initialize_installation_release_sources()


def test_real_initializer_recomputes_and_retains_exact_two_files(tmp_path,monkeypatch):
    from hashlib import sha256
    from app.operations.installation_release_init import initialize_installation_release_sources
    tree,context = init_tree(tmp_path,monkeypatch)
    assert initialize_installation_release_sources() == {'context_sha256':sha256(context).hexdigest()}
    assert not tree.live
    assert tree.actual(ROOT / 'documents' / 'installation-release-context.json').read_bytes() == context
    before = tree.actual(ROOT / 'documents').stat().st_ino
    assert initialize_installation_release_sources() == {'context_sha256':sha256(context).hexdigest()}
    assert tree.actual(ROOT / 'documents').stat().st_ino == before
    assert not tree.live


@pytest.mark.parametrize('mutation',['partial','wrong_context','extra_config'])
def test_initializer_refuses_without_repair(tmp_path,monkeypatch,mutation):
    from app.operations.installation_release_init import initialize_installation_release_sources
    from app.deployment.installation_release_contracts import INPUT_ROOT
    from app.deployment.contracts import DeploymentSourceError
    tree,_ = init_tree(tmp_path,monkeypatch)
    if mutation == 'partial': tree.directory(ROOT / 'documents',0,21201)
    if mutation == 'wrong_context': tree.write(INPUT_ROOT / 'installation-release-context.json',b'{}',0,0)
    if mutation == 'extra_config': tree.write(INPUT_ROOT / 'extra.json',b'{}',0,0)
    before = tuple(sorted(p.name for p in tree.actual(ROOT).iterdir()))
    with pytest.raises(DeploymentSourceError): initialize_installation_release_sources()
    assert tuple(sorted(p.name for p in tree.actual(ROOT).iterdir())) == before
    assert not tree.live


@pytest.mark.parametrize('interrupt',[False,True,'secondary_close'])
def test_root_metadata_is_synced_before_commit_and_failure_preserves_primary(tmp_path,monkeypatch,interrupt):
    import os
    from app.operations import _installation_release_init_files as files
    from app.operations import installation_release_init as initializer
    from app.operations.installation_release_init import initialize_installation_release_sources
    tree,_ = init_tree(tmp_path,monkeypatch)
    identity = tree.actual(ROOT).stat()
    primary = KeyboardInterrupt('controlled final root metadata fsync')
    events,publications = [],[]
    real_chown,real_chmod,real_sync,real_commit = os.fchown,os.fchmod,os.fsync,files._commit_bundle
    def is_root(fd):
        stat = tree.raw_fstat(fd)
        return (stat.st_dev,stat.st_ino) == (identity.st_dev,identity.st_ino)
    def chown(fd,*args):
        result = real_chown(fd,*args)
        if is_root(fd): events.append('owner')
        return result
    def chmod(fd,*args):
        result = real_chmod(fd,*args)
        if is_root(fd): events.append('mode')
        return result
    def sync(fd):
        if is_root(fd):
            after_metadata = events[-2:] == ['owner','mode']
            events.append('sync')
            if after_metadata:
                assert len(publications) == 1 and not publications[0].committed
                if interrupt: raise primary
        return real_sync(fd)
    def commit(publication):
        publications.append(publication)
        return real_commit(publication)
    monkeypatch.setattr(os,'fchown',chown); monkeypatch.setattr(os,'fchmod',chmod)
    monkeypatch.setattr(os,'fsync',sync); monkeypatch.setattr(initializer,'_commit_bundle',commit)
    secondary = []
    if interrupt == 'secondary_close':
        from app.deployment import files as retained_files
        real_close = retained_files.close_fd
        def close(fd):
            real_close(fd)
            if publications and events[-3:] == ['owner','mode','sync'] and not secondary:
                secondary.append(fd)
                raise RuntimeError('controlled secondary cleanup failure')
        monkeypatch.setattr(retained_files,'close_fd',close)
    if interrupt:
        with pytest.raises(KeyboardInterrupt) as error: initialize_installation_release_sources()
        assert error.value is primary and not publications[0].committed
    else:
        initialize_installation_release_sources()
        assert publications[0].committed
    assert events[-3:] == ['owner','mode','sync']
    assert not tree.live
    if interrupt == 'secondary_close': assert secondary


@pytest.mark.parametrize('boundary',['before_open','after_open_stat'])
def test_initializer_each_actual_fd_acquisition_preserves_primary_and_closes_all(tmp_path,monkeypatch,boundary):
    import os
    from app.operations.installation_release_init import initialize_installation_release_sources
    from app.deployment import files as files
    # Enumerate new ownership acquisitions, not the unchanged shared ancestor-walk
    # and pathname-recheck opens. Each primitive still opens/closes real temp FDs.
    def instrument(patch,position=None):
        original_directory,original_regular,original_open,original_stat = files.Directory.open,files.open_regular,os.open,files.stat_fd
        state = {'labels':[],'watch':False,'raised':False}
        primary = KeyboardInterrupt('controlled initializer acquisition '+str(position))
        def acquire(label,operation,*args,**kwargs):
            state['labels'].append(label)
            if len(state['labels']) == position:
                if boundary == 'before_open':
                    state['raised'] = True
                    raise primary
                state['watch'] = True
            return operation(*args,**kwargs)
        def directory(path,**kwargs): return acquire('directory:'+str(path),original_directory,path,**kwargs)
        def regular(fd,name,**kwargs): return acquire('regular:'+name,original_regular,fd,name,**kwargs)
        def opened(path,flags,*args,**kwargs):
            if str(path).startswith('.stage-') or flags & os.O_CREAT:
                return acquire('staging:'+str(path),original_open,path,flags,*args,**kwargs)
            return original_open(path,flags,*args,**kwargs)
        def stat(fd):
            if state['watch'] and not state['raised']:
                state['raised'] = True
                raise primary
            return original_stat(fd)
        patch.setattr(files.Directory,'open',staticmethod(directory)); patch.setattr(files,'open_regular',regular)
        patch.setattr(os,'open',opened); patch.setattr(files,'stat_fd',stat)
        return state,primary
    with monkeypatch.context() as patch:
        (tmp_path/'discovery').mkdir()
        tree,_ = init_tree(tmp_path/'discovery',patch)
        state,_ = instrument(patch)
        initialize_installation_release_sources()
        assert not tree.live
        observed = state['labels']
    assert len(observed) >= 26
    assert any('release-trust.json' in path for path in observed)
    assert any('provider-stage-sources' in path for path in observed)
    assert any('.stage-' in path for path in observed)
    for position in range(1,len(observed)+1):
        with monkeypatch.context() as patch:
            (tmp_path/str(position)).mkdir()
            tree,_ = init_tree(tmp_path/str(position),patch)
            state,primary = instrument(patch,position)
            with pytest.raises(KeyboardInterrupt) as error: initialize_installation_release_sources()
            assert state['raised'] and error.value is primary,(boundary,position,observed[position-1])
            assert not tree.live,(boundary,position,observed[position-1])
    print('initializer acquisition boundaries',boundary,len(observed))
