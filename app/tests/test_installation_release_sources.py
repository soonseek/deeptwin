import importlib
import pytest
from app.tests.installation_release_fixture import ROOT, trust_document
from app.tests.provider_source_reader_fixture import ReaderTree
from app.domain.refs import canonical_json
from app.deployment.contracts import DeploymentSourceError


def retained_case(tmp_path, monkeypatch):
    from app.deployment.installation_release_contracts import _context_bytes
    tree = ReaderTree(tmp_path, monkeypatch)
    trust = canonical_json(trust_document(tree.bundle))
    context = _context_bytes(tree.bundle, trust, tree.profile)
    tree.directory(ROOT,0,21201)
    tree.directory(ROOT / 'documents',0,21201)
    tree.mount(ROOT,True)
    for name,raw in (('release-trust.json',trust),('installation-release-context.json',context)):
        tree.write(ROOT / 'documents' / name,raw,0,21201)
    return tree,context


def test_fixed_retained_source_factory_exists_without_service_import():
    try:
        module = importlib.import_module('app.deployment.installation_release_sources')
    except ModuleNotFoundError:
        pytest.fail('Actual installation release retained source factory is missing')
    with pytest.raises(TypeError): module.InstallationReleaseSource()


@pytest.mark.parametrize('mutation',['mount','file'])
def test_source_change_inside_actual_leaf_read_refuses_without_rebase(tmp_path,monkeypatch,mutation):
    from hashlib import sha256
    from app.deployment import installation_release_sources as module
    tree,context = retained_case(tmp_path,monkeypatch)
    provider = tree.open()
    baseline = set(tree.live)
    source = module.open_installation_release_sources(profile=tree.profile,
        context_sha256=sha256(context).hexdigest(),provider_source_context=provider,protected_roots=())
    original = module.f.read_exact
    target = source._bundle.leaves[0][0]
    changed = []
    def read(fd,cap):
        raw = original(fd,cap)
        if fd == target and not changed:
            changed.append(mutation)
            if mutation == 'mount':
                tree.mount_lines = [line.replace(' ro - ext4',' rw - ext4')
                    if f' {ROOT} ' in line else line for line in tree.mount_lines]
            else:
                tree.write(ROOT/'documents'/'release-trust.json',b'{}',0,21201)
        return raw
    monkeypatch.setattr(module.f,'read_exact',read)
    try:
        with pytest.raises(DeploymentSourceError): source.read_current()
        assert changed == [mutation]
        with pytest.raises(DeploymentSourceError): source.read_current()
        assert not provider._closed
    finally:
        source.close()
        assert set(tree.live) == baseline
        provider.close()
        assert not tree.live


@pytest.mark.parametrize('mutation',['none','same_bytes_inode','extra_file','missing_file','source18','mount','overlay','alias'])
def test_S_whole_retention_and_borrowed_source(tmp_path,monkeypatch,mutation):
    from app.deployment.installation_release_sources import open_installation_release_sources
    from hashlib import sha256
    tree,context = retained_case(tmp_path,monkeypatch)
    provider = tree.open()
    baseline = set(tree.live)
    source = open_installation_release_sources(profile=tree.profile,
        context_sha256=sha256(context).hexdigest(),provider_source_context=provider,protected_roots=())
    try:
        expected = source.read_current()
        if mutation == 'none':
            assert expected[1] == ('installation-release-context.json',context)
        else:
            leaf = ROOT / 'documents' / 'release-trust.json'
            if mutation == 'same_bytes_inode':
                raw = tree.actual(leaf).read_bytes()
                tree.actual(leaf).unlink()
                tree.write(leaf,raw,0,21201)
            if mutation == 'extra_file': tree.write(ROOT / 'documents' / 'extra.json',b'{}',0,21201)
            if mutation == 'missing_file': tree.actual(leaf).unlink()
            if mutation == 'source18':
                tree.write('/run/deeptwin/provider-stage-sources/documents/provider-trust-set.json',b'{}',0,21201)
            if mutation == 'mount':
                tree.mount_lines = [line.replace(' ro - ext4',' rw - ext4') if f' {ROOT} ' in line else line for line in tree.mount_lines]
            if mutation == 'overlay': tree.mount(ROOT / 'documents',True)
            if mutation == 'alias':
                tree.mount_lines[-1] = tree.mount_lines[-1].replace(tree.mount_lines[-1].split()[3],'/volume-100')
            with pytest.raises(DeploymentSourceError): source.read_current()
    finally:
        source.close()
        assert set(tree.live) == baseline
        assert not provider._closed
        provider.close()
        assert not tree.live


@pytest.mark.parametrize('pin',[None,'0'*64])
def test_S_missing_wrong_pin_closes_new_resources(tmp_path,monkeypatch,pin):
    from app.deployment.installation_release_sources import open_installation_release_sources
    tree,_ = retained_case(tmp_path,monkeypatch)
    provider = tree.open()
    baseline = set(tree.live)
    try:
        with pytest.raises(DeploymentSourceError):
            open_installation_release_sources(profile=tree.profile,context_sha256=pin,
                provider_source_context=provider,protected_roots=())
        assert set(tree.live) == baseline
    finally: provider.close()


@pytest.mark.parametrize('boundary',['root','documents','release-trust.json','installation-release-context.json','protected'])
def test_each_new_acquisition_failure_closes_owned_fds(tmp_path,monkeypatch,boundary):
    from hashlib import sha256
    from app.deployment import files as f
    from app.deployment.installation_release_sources import open_installation_release_sources
    tree,context = retained_case(tmp_path,monkeypatch)
    provider = tree.open()
    baseline = set(tree.live)
    original_directory,original_regular = f.Directory.open,f.open_regular
    reached = False
    primary = KeyboardInterrupt('synthetic acquisition interruption')
    def opening(label):
        nonlocal reached
        if label == boundary:
            reached = True
            raise primary
    def directory(path,**kwargs):
        opening('root' if path == ROOT else 'documents' if path == ROOT / 'documents' else 'protected')
        return original_directory(path,**kwargs)
    def regular(fd,name,**kwargs):
        opening(name)
        return original_regular(fd,name,**kwargs)
    monkeypatch.setattr(f.Directory,'open',staticmethod(directory))
    monkeypatch.setattr(f,'open_regular',regular)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            open_installation_release_sources(profile=tree.profile,context_sha256=sha256(context).hexdigest(),
                provider_source_context=provider,protected_roots=())
        assert reached and caught.value is primary
        assert set(tree.live) == baseline
        assert not provider._closed
    finally: provider.close()


def test_cleanup_attempts_all_new_handles_with_primary_preserved(tmp_path,monkeypatch):
    from hashlib import sha256
    from app.deployment import files as f
    from app.deployment.installation_release_sources import open_installation_release_sources
    tree,context = retained_case(tmp_path,monkeypatch)
    provider = tree.open()
    baseline = set(tree.live)
    source = open_installation_release_sources(profile=tree.profile,context_sha256=sha256(context).hexdigest(),
        provider_source_context=provider,protected_roots=())
    original = f.close_fd
    primary = KeyboardInterrupt('synthetic close interruption')
    count = 0
    def closed(fd):
        nonlocal count
        original(fd)
        count += 1
        if count == 1: raise primary
    monkeypatch.setattr(f,'close_fd',closed)
    try:
        with pytest.raises(KeyboardInterrupt) as caught: source.close()
        assert caught.value is primary
        assert set(tree.live) == baseline
        assert not provider._closed
    finally: provider.close()
