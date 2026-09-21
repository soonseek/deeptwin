"""Synthetic retained release bytes. Full application imports stay inside fixtures."""
from types import MappingProxyType
from uuid import uuid4
from hashlib import sha256
from contextlib import contextmanager

import pytest

from app.domain.refs import canonical_json


@pytest.fixture
def release_documents():
    # Complete raw synthetic vectors, no store/app/evaluator or claimed approval.
    release = SyntheticRelease()
    envelope = release.documents('linux/amd64',medium=True)
    rows = {'release_review':canonical_json(envelope)}
    repeated = {'origin_evidence','license_text','invocation'}
    for digest,(role,raw) in release.retained.items():
        rows[role+':'+digest if role in repeated else role] = raw
    return MappingProxyType(rows)


def packet_header(stage):
    roles = ('release_review','provenance','image_sbom','component_license_review','image_scan',
        'component_scan','source_report','dependency_report','filesystem_report','cohort_manifest',
        'invocation','invocation')
    raws = tuple(('SYNTHETIC TEST ONLY '+role+str(index)).encode() for index,role in enumerate(roles))
    objects = [{'role':role,'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)} for role,raw in zip(roles,raws,strict=True)]
    tail = sorted(zip(objects[10:],raws[10:]),key=lambda row:row[0]['sha256'])
    objects[10:] = [row[0] for row in tail]
    raws = (*raws[:10],*(row[1] for row in tail))
    return canonical_json({'schema_version':'provider-installation-command-v1','command_id':str(uuid4()),
        'staged_installation_ref':stage.as_dict(),'objects':objects}),raws


def review_envelope():
    """Structural-only envelope, not a signature or release authority fixture."""
    ref = {'sha256':sha256(b'SYNTHETIC TEST ONLY').hexdigest(),'size_bytes':19}
    subject = {'extension_id':'synthetic-provider','extension_version':'1.0.0','platform':'linux/amd64',
        **{key:ref for key in ('image_index','selected_manifest','config','source_closure','dependency_closure','filesystem_inspection')},
        'layers':[ref],'build_identity_sha256':ref['sha256']}
    decision = {'rationale':'SYNTHETIC TEST ONLY','evidence':[ref]}
    return {'schema_version':'provider-release-review-envelope-v1','key_id':str(uuid4()),
        'algorithm':'ed25519','signature':'A'*86,'payload':{'schema_version':'provider-release-review-v1',
        'review_profile_id':'provider-artifact-review-v1','evidence_policy_sha256':ref['sha256'],'issued_at_ms':1700000000000,
        'reviewer':{'id':'synthetic','name':'SYNTHETIC TEST ONLY','authority_basis':[ref]},'subject':subject,
        'objects':[{'role':'origin_evidence',**ref}],**{key:ref for key in ('provenance','component_map','cohort','image_invocation','component_invocation')},
        'scope':'local-artifact-use-only','origin_review':decision,'license_review':decision,
        'finding_review':{'image_scan':ref,'component_scan':ref,'rationale':'SYNTHETIC TEST ONLY','accepted':[]}}}


def syft_structure():
    """Literal tagged-type vector; not a complete admitted inventory."""
    location = {'path':'/synthetic','accessPath':'/synthetic','layerID':'sha256:'+'1'*64}
    artifact = {'id':'synthetic-deb','name':'synthetic','version':'1.0','type':'deb',
        'foundBy':'dpkg-db-cataloger','locations':[location],'licenses':[],'language':'','cpes':[],
        'purl':'pkg:deb/debian/synthetic@1.0?arch=amd64&distro=debian-13','metadataType':'dpkg-db-entry',
        'metadata':{'package':'synthetic','source':'synthetic-src','version':'1.0','sourceVersion':'1.0',
            'architecture':'amd64','maintainer':'SYNTHETIC TEST ONLY','installedSize':1,
            'files':[{'path':'/synthetic','isConfigFile':False}]}}
    return {'artifacts':[artifact],'artifactRelationships':[],
        'files':[{'id':'synthetic-file','location':{'path':'/synthetic','layerID':'sha256:'+'1'*64},
            'metadata':{'mode':292,'type':'RegularFile','userID':0,'groupID':0,'mimeType':'text/plain','size':19},
            'digests':[{'algorithm':'sha256','value':sha256(b'SYNTHETIC TEST ONLY').hexdigest()}]}],
        'source':{'id':'synthetic-image','name':'SYNTHETIC TEST ONLY','version':'1.0','type':'image','metadata':{}},
        'distro':{'id':'debian','versionID':'13'},'descriptor':{'name':'syft','version':'1.42.3','configuration':{}},
        'schema':{'version':'16.1.3','url':'https://raw.githubusercontent.com/anchore/syft/main/schema/json/schema-16.1.3.json'}}


def grype_configuration():
    return {'output':['json'],'file':'','distro':'','output-template-file':'','ignore-wontfix':'','platform':'',
        'fail-on-severity':'','name':'','default-image-pull-source':'','pretty':False,'add-cpes-if-none':False,
        'check-for-app-update':False,'only-fixed':False,'only-notfixed':False,'show-suppressed':False,'by-cve':False,
        'ignore':[],'exclude':[],'vex-documents':[],'vex-add':[],'from':None,'match-upstream-kernel-headers':True,'timestamp':True,
        'search':{'scope':'squashed','unindexed-archives':False,'indexed-archives':True},
        'externalSources':{'enable':False,'maven':{'searchUpstreamBySha1':False,
            'baseUrl':'https://search.maven.org/solrsearch/select','rateLimit':300000000}},
        'registry':{'insecure-skip-tls-verify':False,'insecure-use-http':False,'ca-cert':''},
        'SortBy':{'sort-by':'risk'},'fix-channel':{'redhat-eus':{'apply':'never','versions':'>= 8.0'}},
        'alerts':{'enable-eol-distro-warnings':True},'exp':{},'dev':{'db':{'debug':False}},
        'match':{'java':{'using-cpes':False},'dotnet':{'using-cpes':False},'javascript':{'using-cpes':False},
            'python':{'using-cpes':False},'ruby':{'using-cpes':False},'rust':{'using-cpes':False},'hex':{'using-cpes':False},
            'jvm':{'using-cpes':True},'stock':{'using-cpes':True},'golang':{'using-cpes':False,
                'always-use-cpe-for-stdlib':True,'allow-main-module-pseudo-version-comparison':False},
            'dpkg':{'using-cpes':False,'missing-epoch-strategy':'zero','use-cpes-for-eol':False},
            'rpm':{'using-cpes':False,'missing-epoch-strategy':'auto','use-cpes-for-eol':False}},
        'db':{'cache-dir':'/inputs/db','update-url':'https://grype.anchore.io/databases','ca-cert':'',
            'auto-update':False,'validate-by-hash-on-start':True,'validate-age':True,
            'max-allowed-built-age':432000000000000,'require-update-check':False,
            'update-available-timeout':30000000000,'update-download-timeout':300000000000,'max-update-check-frequency':7200000000000}}


def grype_finding_document():
    from decimal import Decimal
    return {'matches':[{'vulnerability':{'id':'CVE-2099-0001','dataSource':'urn:synthetic:test-only',
        'severity':'Medium','urls':[],'cvss':[{'version':'3.1','vector':'SYNTHETIC TEST ONLY',
            'metrics':{'baseScore':Decimal('5.40')},'vendorMetadata':{'diagnostic':Decimal('0.001')}}],
        'fix':{'versions':[],'state':'unknown'},'advisories':[],'risk':Decimal('1.20')},
        'relatedVulnerabilities':[],'matchDetails':[{'type':'exact-direct-match','matcher':'python-matcher',
            'searchedBy':{'diagnostic':'SYNTHETIC TEST ONLY'},'found':{'synthetic':True}}],
        'artifact':{'id':'synthetic-python','name':'synthetic','version':'1.0','type':'python',
            'locations':None,'language':'python','licenses':['MIT'],'cpes':[],
            'purl':'pkg:pypi/synthetic@1.0','upstreams':[]}}],
        'source':{'type':'file','target':'/inputs/components.spdx.json'},'distro':{},
        'descriptor':{'name':'grype','version':'0.110.0','timestamp':'2023-11-14T22:13:20Z',
            'configuration':grype_configuration(),'db':{}}}


def signed_authority_packet(case,mutation=None):
    """Ephemeral signature over real stage identities; inner reports remain structural stubs.

    This is solely a current source/signature unit fixture, never a complete
    evaluate_release positive or an observed native scan.
    """
    from base64 import urlsafe_b64encode
    import json
    from nacl.signing import SigningKey
    from app.domain.store import _writer
    from app.deployment.installation_release_contracts import _context_bytes,installation_evidence_policy_sha256
    from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header
    from app.tests.installation_release_fixture import trust_document
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    lineage = json.loads(stage.lineage_bytes)
    content = stage.stage_record['content']
    platform = next(row for row in lineage['platforms'] if row['measured_platform_entry']['platform'] == content['platform'])
    entry,identity = platform['measured_platform_entry'],platform['build_identity']
    header,objects = packet_header(stage.stage_ref)
    header = json.loads(header)
    envelope = review_envelope()
    key = SigningKey.generate()
    payload = envelope['payload']
    def oci(value): return {'sha256':value['digest'][7:],'size_bytes':value['size_bytes']}
    def ref(index): return {key:value for key,value in header['objects'][index].items() if key != 'role'}
    payload.update(evidence_policy_sha256=installation_evidence_policy_sha256(),objects=header['objects'][1:],
        provenance=ref(1),cohort=ref(9),image_invocation=ref(10),component_invocation=ref(11))
    payload['finding_review'].update(image_scan=ref(4),component_scan=ref(5))
    payload['subject'] = {'extension_id':lineage['extension_id'],'extension_version':lineage['extension_version'],
        'platform':content['platform'],'image_index':oci(lineage['index']),'selected_manifest':oci(entry['manifest']),
        'config':oci(entry['config']),'layers':[oci(row) for row in entry['layers']],
        'build_identity_sha256':sha256(canonical_json(identity)).hexdigest(),
        'source_closure':ref(6),'dependency_closure':ref(7),'filesystem_inspection':ref(8)}
    if mutation == 'foreign_policy': payload['evidence_policy_sha256'] = 'f'*64
    if mutation == 'wrong_subject': payload['subject']['selected_manifest']['sha256'] = 'f'*64
    unsigned = {key:value for key,value in envelope.items() if key != 'signature'}
    signature = key.sign(b'deeptwin:provider-release-review:v1\n'+canonical_json(unsigned)).signature
    envelope['signature'] = urlsafe_b64encode(signature).rstrip(b'=').decode()
    if mutation == 'bad_signature': envelope['signature'] = 'A'*86
    raw = canonical_json(envelope)
    objects = (raw,*objects[1:])
    header['objects'][0].update(sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    trust = trust_document(stage.provider_files)
    trust['keys'][0].update(key_id=envelope['key_id'],public_key=urlsafe_b64encode(bytes(key.verify_key)).rstrip(b'=').decode())
    trust['allowed_releases'] = [{'extension_id':payload['subject']['extension_id'],
        'extension_version':payload['subject']['extension_version'],'platform':payload['subject']['platform'],
        'image_index_sha256':payload['subject']['image_index']['sha256'],
        'selected_manifest_sha256':payload['subject']['selected_manifest']['sha256'],
        'release_review':{'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)},'key_id':envelope['key_id']}]
    if mutation == 'deny': trust['allowed_releases'] = []
    if mutation == 'revoked_key': trust['revoked_key_ids'] = [envelope['key_id']]
    if mutation == 'revoked_review': trust['revoked_review_sha256'] = [sha256(raw).hexdigest()]
    if mutation == 'revoked_manifest': trust['revoked_manifest_sha256'] = [payload['subject']['selected_manifest']['sha256']]
    if mutation == 'expired': trust['valid_until_ms'] = 1699999999999
    if mutation == 'future': trust['valid_from_ms'] = 1700000000001
    if mutation == 'issuance': trust['keys'][0]['issuance_not_after_ms'] = 1699999999999
    trust_bytes = canonical_json(trust)
    sources = (('release-trust.json',trust_bytes),('installation-release-context.json',
        _context_bytes(stage.provider_files,trust_bytes,case.profile)))
    return ReleasePacket(parse_installation_header(canonical_json(header)),objects),sources,stage


def db_observations():
    status = {'schemaVersion':'6.1.4','valid':True,'from':'manual import',
        'built':'2023-11-13T22:13:20Z','path':'/inputs/db/6/vulnerability.db'}
    providers = [{'name':'synthetic-feed','version':'synthetic-1','processor':'SYNTHETIC TEST ONLY',
        'dateCaptured':'2023-11-13T22:13:20.123456789Z','inputDigest':'xxh64:abcdef'}]
    scan = {'status':status,'providers':{'synthetic-feed':{'captured':'2023-11-13T22:13:20Z','input':'xxh64:abcdef'}}}
    return status,providers,scan


def image_observation():
    from base64 import b64encode
    diff_ids = ['sha256:'+sha256(b'SYNTHETIC TEST ONLY uncompressed layer').hexdigest()]
    config = {'architecture':'amd64','os':'linux','created':'1970-01-01T00:00:00Z',
        'config':{'Entrypoint':['/opt/deeptwin-extension/bin/worker'],'Cmd':[],
            'Env':['LANG=C.UTF-8','LC_ALL=C.UTF-8','PATH=/usr/local/bin:/usr/bin:/bin'],
            'User':'65532:65532','WorkingDir':'/','StopSignal':'SIGTERM'},
        'rootfs':{'type':'layers','diff_ids':diff_ids},
        'history':[{'created':'1970-01-01T00:00:00Z','created_by':'provider-oci-build-v1'}]}
    config_bytes = canonical_json(config)
    manifest = {'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json',
        'config':{'mediaType':'application/vnd.oci.image.config.v1+json','digest':'sha256:'+sha256(config_bytes).hexdigest(),
            'size':len(config_bytes)},'layers':[{'mediaType':'application/vnd.oci.image.layer.v1.tar+gzip',
            'digest':'sha256:'+sha256(b'SYNTHETIC TEST ONLY compressed layer').hexdigest(),'size':36}]}
    manifest_bytes = canonical_json(manifest)
    entry = {'platform':'linux/amd64','manifest':{'media_type':manifest['mediaType'],
        'digest':'sha256:'+sha256(manifest_bytes).hexdigest(),'size_bytes':len(manifest_bytes)},
        'config':{'media_type':manifest['config']['mediaType'],'digest':manifest['config']['digest'],'size_bytes':len(config_bytes)},
        'layers':[{'position':1,'media_type':manifest['layers'][0]['mediaType'],
            'digest':manifest['layers'][0]['digest'],'size_bytes':36}]}
    metadata = {'userInput':'/inputs/image','imageID':entry['config']['digest'],
        'manifestDigest':entry['manifest']['digest'],'mediaType':entry['manifest']['media_type'],
        'tags':[],'repoDigests':[],'architecture':'amd64','os':'linux','imageSize':19,
        'layers':[{'mediaType':entry['layers'][0]['media_type'],'digest':diff_ids[0],'size':19}],
        'config':b64encode(config_bytes).decode(),'manifest':b64encode(manifest_bytes).decode()}
    observed = {'architecture':'amd64','os':'linux','entrypoint':config['config']['Entrypoint'],
        'cmd':[],'env':config['config']['Env'],'working_dir':'/','user':'65532:65532','stop_signal':'SIGTERM','diff_ids':diff_ids}
    return metadata,{'platform':'linux/amd64','entry':entry,'config':observed}


def syft_configurations(platform='linux/amd64'):
    catalogers = ['binary-classifier-cataloger','dpkg-db-cataloger','file-digest-cataloger',
        'file-metadata-cataloger','python-installed-package-cataloger']
    classifiers = ('python-binary,python-binary-lib,pypy-binary-lib,go-binary,julia-binary,helm,redis-binary,'
        'valkey-binary,nodejs-binary,busybox-binary,util-linux-binary,haproxy-binary,perl-binary,'
        'php-composer-binary,httpd-binary,memcached-binary,traefik-binary,arangodb-binary,'
        'postgresql-binary,mysql-binary,mysql-binary,mysql-binary,xtrabackup-binary,mariadb-binary,'
        'rust-standard-library-linux,rust-standard-library-macos,ruby-binary,erlang-binary,'
        'erlang-alpine-binary,erlang-library,swipl-binary,dart-binary,haskell-ghc-binary,'
        'haskell-cabal-binary,haskell-stack-binary,consul-binary,hashicorp-vault-binary,nginx-binary,'
        'bash-binary,openssl-binary,qt-qtbase-lib,gcc-binary,fluent-bit-binary,wordpress-cli-binary,'
        'curl-binary,lighttpd-binary,proftpd-binary,zstd-binary,xz-binary,gzip-binary,sqlcipher-binary,'
        'jq-binary,chrome-binary,ffmpeg-binary,ffmpeg-library,ffmpeg-library,elixir-binary,'
        'elixir-library,istio-binary,istio-binary,grafana-binary,grafana-binary,envoy-binary,mongodb-binary,'
        'java-binary,java-jdb-binary').split(',')
    python = {'guess-unpinned-requirements':False,'search-remote-licenses':False,'pypi-base-url':'https://pypi.org/pypi'}
    audit = {'search':{'scope':'squashed'},'relationships':{'package-file-ownership':True,
        'package-file-ownership-overlap':False,'exclude-binary-packages-with-file-ownership-overlap':False},
        'data-generation':{'generate-cpes':True},'files':{'selection':'all','hashers':['sha256'],
            'content':{'globs':None,'skip-files-above-size':0}},'licenses':{'include-content':'all','coverage':75},
        'catalogers':{'requested':{'default':catalogers},'used':list(catalogers)},
        'packages':{'binary':classifiers,'python':python,'dotnet':{},'golang':{},'java-archive':{},'javascript':{},'linux-kernel':{},'nix':{}}}
    input_ = {'check-for-app-update':False,'scope':'squashed','from':['oci-dir'],'platform':platform,
        'exclude':[],'enrich':[],'default-catalogers':catalogers,'select-catalogers':[],
        'package':{'search-indexed-archives':False,'search-unindexed-archives':False,'exclude-binary-overlap-by-ownership':False},
        'relationships':{'package-file-ownership':True,'package-file-ownership-overlap':False},
        'file':{'metadata':{'selection':'all','digests':['sha256']}},'license':{'content':'all','coverage':75},
        'python':python,'compliance':{'missing-name':'keep','missing-version':'keep'},
        'unknowns':{'remove-when-packages-defined':False,'executables-without-packages':True,'unexpanded-archives':True}}
    return input_,audit


def dpkg_status_bytes(platform='linux/amd64'):
    return ('Package: synthetic-runtime\nStatus: install ok installed\nVersion: 1:2.3-4\n'
        'Architecture: '+platform.split('/')[1]+'\nMulti-Arch: same\nSource: synthetic-src (1:2.3-4)\n'
        'Description: SYNTHETIC TEST ONLY\n continued description\n .\nConffiles: \n /etc/synthetic 0000\n\n'
        'Package: synthetic-data\nStatus: install ok installed\nVersion: 2.0\nArchitecture: all\n').encode()


LAUNCHER = (b'#!/usr/local/bin/python3.12 -ISB\nimport sys\n'
    b'sys.path[:] = ["/opt/deeptwin-extension/lib", "/opt/deeptwin-extension/site", "/usr/local/lib/python3.12", "/usr/local/lib/python3.12/lib-dynload"]\n'
    b'from app.workers.provider_worker import main\nraise SystemExit(main())\n')


def _fixture_ref(raw): return {'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)}


def _source_paths():
    groups = {'app':['__init__'],'app/adapters':['__init__','claude_protocol'],
        'app/deployment':['__init__','contracts','files','mounts'],'app/domain':['__init__','events','refs','wire'],
        'app/extensions':['__init__','candidate_contracts','candidate_schema_exports','contracts','lineage_contracts',
            'lineage_schema_exports','port_contracts','port_schema_generator','provider_identity','provider_identity_schema_exports','registry','schema_exports'],
        'app/operations':['__init__','setup'],'app/workers':['__init__','_fixed_image_metadata','artifact_stream',
            'artifact_stream_transport','broker','extension_channel','extension_metadata','ipc_root','listener',
            'provider_messages','provider_metadata','provider_service','provider_transform','provider_worker']}
    return sorted([directory+'/'+name+'.py' for directory,names in groups.items() for name in names]+[
        'deploy/provider_release/worker',*['schemas/v1/extensions/ports/provider-port-v1/'+role+'.schema.json'
            for role in ('config','request','result','error')]])


class SyntheticRelease:
    """Complete retained-byte narrative; no native archive, install or scan claim."""
    def __init__(self,*,status_variant=None):
        from pathlib import Path
        from copy import deepcopy
        import json,io,tarfile,tomllib
        from app.tests.test_provider_lineage import provider_identity_fixture,shipped_schema_bytes
        root = Path(__file__).resolve().parents[2]
        self.retained = {}
        self.raw_members = {}
        self.platforms = ('linux/amd64','linux/arm64')
        lock_raw = (root/'deploy/manifests/upstream-images.json').read_bytes()
        base = next(row for row in json.loads(lock_raw)['images'] if row['image_id'] == 'python-service-base')
        uv = tomllib.loads((root/'uv.lock').read_text())
        names = ('attrs','idna','jsonschema','jsonschema-specifications','referencing','rpds-py','typing-extensions')
        versions = {'attrs':'26.1.0','idna':'3.19','jsonschema':'4.26.0','jsonschema-specifications':'2025.9.1',
            'referencing':'0.37.0','rpds-py':'2026.6.3','typing-extensions':'4.16.0'}
        wheels = {}
        for platform in self.platforms:
            rows = []
            for name in names:
                package = next(p for p in uv['package'] if p['name'] == name and p['version'] == versions[name])
                tag = ('cp312-cp312-manylinux_2_17_'+('x86_64.manylinux2014_x86_64' if platform.endswith('amd64') else 'aarch64.manylinux2014_aarch64')) if name == 'rpds-py' else 'py3-none-any'
                wheel = next(w for w in package['wheels'] if w['url'].endswith('-'+tag+'.whl'))
                rows.append({'name':name,'version':versions[name],'filename':wheel['url'].rsplit('/',1)[1],
                    'wheel':{'sha256':wheel['hash'][7:],'size_bytes':wheel['size']}})
            wheels[platform] = rows
        dependency_lock = ''.join(name+'=='+versions[name]+''.join(' --hash=sha256:'+digest
            for digest in sorted({r['wheel']['sha256'] for rows in wheels.values() for r in rows if r['name'] == name}))+'\n'
            for name in names).encode()
        toolset = [{'path':'deploy/provider_release/'+name+'.py',**_fixture_ref(('SYNTHETIC TEST ONLY '+name).encode())}
            for name in ('__init__','contracts','inputs','oci','build','inspect','capsule','service')]
        self.toolset = sorted(toolset,key=lambda row:row['path'])
        toolset_ref = self.add('origin_evidence',canonical_json(self.toolset))
        self.inputs = {}
        distributions = {}
        for platform in self.platforms:
            upstream = next(row for row in base['platforms'] if row['architecture'] == platform.split('/')[1])
            entry = {'platform':platform,**{key:deepcopy(upstream[key]) for key in ('manifest','config','layers')}}
            self.inputs[platform] = {'schema_version':'provider-private-dependency-input-set-v1','platform':platform,
                'python':{'implementation':'CPython','version':'3.12.14','abi':'cp312','glibc_floor':'2.28'},
                'roots':['idna==3.19','jsonschema==4.26.0'],'base':{'index':deepcopy(base['top_descriptor']),'entry':entry},
                'lock':_fixture_ref(dependency_lock),'artifacts':wheels[platform]}
            members = {}
            dists = []
            for artifact in wheels[platform]:
                name = artifact['name']
                package = name.replace('-','_')
                if name == 'rpds-py':
                    package = 'rpds'
                    member = package+'/rpds.cpython-312-'+('x86_64' if platform.endswith('amd64') else 'aarch64')+'-linux-gnu.so'
                else: member = package+'/__init__.py'
                paths = [member,artifact['name'].replace('-','_')+'-'+artifact['version']+'.dist-info/LICENSE']
                files = []
                for relative in paths:
                    path = '/opt/deeptwin-extension/site/'+relative
                    raw = ('SYNTHETIC TEST ONLY installed member '+platform+' '+relative).encode()
                    members[path] = raw
                    files.append({'path':path,**_fixture_ref(raw),'mode':292})
                dists.append({'name':name,'version':artifact['version'],'wheel':artifact['wheel'],
                    'files':sorted(files,key=lambda row:row['path'])})
            self.raw_members[platform] = members
            distributions[platform] = dists
        self.recipe = {'schema_version':'provider-private-build-recipe-v1','builder_id':'provider-oci-build-v1',
            'inspector_id':'provider-oci-inspect-v1','source_layout':'provider-private-source44-v1',
            'launch_policy':'provider-cpython-isolated-v1','base_lock':_fixture_ref(lock_raw),'toolset':toolset_ref,
            'dependency_sets':[{'platform':p,'input':_fixture_ref(canonical_json(self.inputs[p]))} for p in self.platforms],
            'overlay_format':'ustar-uncompressed-v1','created':'1970-01-01T00:00:00Z'}
        source_files,source_members = [],{}
        tar = io.BytesIO()
        with tarfile.open(fileobj=tar,mode='w',format=tarfile.USTAR_FORMAT) as archive:
            for path in _source_paths():
                raw = LAUNCHER if path == 'deploy/provider_release/worker' else (root/path).read_bytes()
                mode = 365 if path == 'deploy/provider_release/worker' else 292
                image_path = '/opt/deeptwin-extension/'+('bin/worker' if path == 'deploy/provider_release/worker'
                    else 'lib/'+path if path.startswith('app/') else 'ports/provider-port-v1/'+path.rsplit('/',1)[1])
                source_members[image_path] = raw
                source_files.append({'source_path':path,'image_path':image_path,**_fixture_ref(raw),'mode':mode})
                info = tarfile.TarInfo(path)
                info.mode,info.size = mode,len(raw)
                archive.addfile(info,io.BytesIO(raw))
        source_bundle = _fixture_ref(tar.getvalue())
        triples = {p:{'schema_version':'extension-build-inputs-v1','source_bundle':source_bundle,
            'build_recipe':_fixture_ref(canonical_json(self.recipe)),
            'dependency_input_set':_fixture_ref(canonical_json(self.inputs[p]))} for p in self.platforms}
        self.source = {'schema_version':'provider-source-closure-v1','producer_id':'provider-oci-build-v1',
            'toolset':toolset_ref,'source_bundle':source_bundle,'recipe':self.recipe,
            'platform_inputs':[{'platform':p,'inputs':triples[p]} for p in self.platforms],'files':source_files}
        self.dependency = {'schema_version':'provider-dependency-closure-v1','producer_id':'provider-oci-build-v1',
            'toolset':toolset_ref,'platforms':[{'platform':p,'input':self.inputs[p],'distributions':distributions[p]} for p in self.platforms]}
        self.source_ref = self.add('source_report',canonical_json(self.source))
        self.dependency_ref = self.add('dependency_report',canonical_json(self.dependency))
        self.entries,self.identities,self.configs,self.manifests,self.filesystems = {},{},{},{},{}
        for platform in self.platforms:
            identity = provider_identity_fixture(platform,shipped_schema_bytes())
            identity.update(inputs=triples[platform],entrypoint=_fixture_ref(LAUNCHER))
            self.identities[platform] = identity
            members = self.raw_members[platform]
            members.update(source_members)
            members['/opt/deeptwin-extension/identity/build-identity-v2.json'] = canonical_json(identity)
            status_bytes = dpkg_status_bytes(platform)
            if status_variant == 'not-installed': status_bytes = status_bytes.replace(b'install ok installed',b'deinstall ok installed',1)
            elif status_variant == 'unknown-field': status_bytes += b'Unknown-Authority: approved\n'
            elif status_variant == 'duplicate-record': status_bytes += b'\n'+status_bytes.split(b'\n\n')[0]+b'\n'
            elif status_variant == 'extra-record': status_bytes += b'\nPackage: extra-package\nStatus: install ok installed\nVersion: 1\nArchitecture: all\n'
            elif status_variant == 'missing-record': status_bytes = status_bytes.split(b'\n\n')[0]+b'\n'
            else: assert status_variant in (None,'intermediate-alias','protected-alias','protected-ancestor','long-status-alias')
            members.update({'/var/lib/dpkg/status':status_bytes,
                '/usr/lib/synthetic-runtime.so':('SYNTHETIC TEST ONLY Debian runtime '+platform).encode(),
                '/usr/share/synthetic-data':b'SYNTHETIC TEST ONLY Debian all data',
                '/usr/local/bin/python3.12':('SYNTHETIC TEST ONLY CPython ELF '+platform).encode()})
            diff_ids = ['sha256:'+sha256(('SYNTHETIC TEST ONLY diff '+platform+str(i)).encode()).hexdigest() for i in range(5)]
            config = {'architecture':platform.split('/')[1],'os':'linux','created':'1970-01-01T00:00:00Z',
                'config':{'User':'65532:65532','Env':['LANG=C.UTF-8','LC_ALL=C.UTF-8','PATH=/usr/local/bin:/usr/bin:/bin'],
                    'Entrypoint':['/opt/deeptwin-extension/bin/worker'],'Cmd':[],'WorkingDir':'/','StopSignal':'SIGTERM'},
                'rootfs':{'type':'layers','diff_ids':diff_ids},
                'history':[{'created':'1970-01-01T00:00:00Z','created_by':'SYNTHETIC TEST ONLY base'} for _ in range(4)]+
                    [{'created':'1970-01-01T00:00:00Z','created_by':'provider-oci-build-v1'}]}
            config_raw = canonical_json(config)
            layers = deepcopy(self.inputs[platform]['base']['entry']['layers'])
            # This is a synthetic overlay identity, not an observed tar or native OCI build.
            overlay_raw = ('SYNTHETIC TEST ONLY overlay '+platform).encode()
            layers.append({'position':5,'media_type':'application/vnd.oci.image.layer.v1.tar',
                'digest':'sha256:'+sha256(overlay_raw).hexdigest(),'size_bytes':len(overlay_raw)})
            diff_ids[-1] = layers[-1]['digest']
            config_raw = canonical_json(config)
            manifest = {'schemaVersion':2,'mediaType':'application/vnd.oci.image.manifest.v1+json',
                'config':{'mediaType':'application/vnd.oci.image.config.v1+json','digest':'sha256:'+sha256(config_raw).hexdigest(),
                    'size':len(config_raw)},'layers':[{'mediaType':r['media_type'],'digest':r['digest'],'size':r['size_bytes']} for r in layers]}
            manifest_raw = canonical_json(manifest)
            self.configs[platform],self.manifests[platform] = config_raw,manifest_raw
            self.entries[platform] = {'platform':platform,'manifest':{'media_type':manifest['mediaType'],
                'digest':'sha256:'+sha256(manifest_raw).hexdigest(),'size_bytes':len(manifest_raw)},
                'config':{'media_type':manifest['config']['mediaType'],'digest':manifest['config']['digest'],'size_bytes':len(config_raw)},'layers':layers}
        index_raw = canonical_json({'schemaVersion':2,'mediaType':'application/vnd.oci.image.index.v1+json',
            'manifests':[{'mediaType':self.entries[p]['manifest']['media_type'],'digest':self.entries[p]['manifest']['digest'],
                'size':self.entries[p]['manifest']['size_bytes'],'platform':{'os':'linux','architecture':p.split('/')[1]}} for p in self.platforms]})
        self.index = {'media_type':'application/vnd.oci.image.index.v1+json','digest':'sha256:'+sha256(index_raw).hexdigest(),'size_bytes':len(index_raw)}
        for platform in self.platforms:
            directories = {'/'}
            rows = []
            for path,raw in self.raw_members[platform].items():
                parent = path.rsplit('/',1)[0]
                while parent:
                    directories.add(parent)
                    parent = parent.rsplit('/',1)[0]
                rows.append({'path':path,'kind':'file','uid':0,'gid':0,'mode':365 if path.endswith('/bin/worker') else 292,
                    **_fixture_ref(raw),'nlink':1})
            rows.extend({'path':path,'kind':'directory','uid':0,'gid':0,'mode':493} for path in directories)
            if status_variant == 'intermediate-alias':
                rows.append({'path':'/var/lib/dpkg/subdir','kind':'directory','uid':0,'gid':0,'mode':493})
                rows.extend({'path':path,'kind':'symlink','uid':0,'gid':0,'mode':511,'target':target}
                    for path,target in (('/x','/var/lib/dpkg/subdir'),('/alias','/x/../status')))
            if status_variant == 'protected-alias':
                rows.extend({'path':path,'kind':'symlink','uid':0,'gid':0,'mode':511,'target':target}
                    for path,target in (('/x','/opt'),('/alias','/x/deeptwin-extension')))
            if status_variant == 'protected-ancestor':
                rows.append({'path':'/x','kind':'symlink','uid':0,'gid':0,'mode':511,'target':'/opt'})
            if status_variant == 'long-status-alias':
                rows.append({'path':'/var/lib/dpkg/subdir','kind':'directory','uid':0,'gid':0,'mode':493})
                rows.extend({'path':'/x'+str(i),'kind':'symlink','uid':0,'gid':0,'mode':511,
                    'target':'/x'+str(i+1) if i < 40 else '/var/lib/dpkg/subdir'} for i in range(41))
                rows.append({'path':'/alias','kind':'symlink','uid':0,'gid':0,'mode':511,'target':'/x0/../status'})
            cfg = json.loads(self.configs[platform])
            self.filesystems[platform] = {'schema_version':'provider-filesystem-inspection-v1','inspector_id':'provider-oci-inspect-v1',
                'toolset':toolset_ref,'platform':platform,'index':self.index,'entry':self.entries[platform],
                'build_identity':self.identities[platform],'source_closure':self.source_ref,'dependency_closure':self.dependency_ref,
                'launch_policy':'provider-cpython-isolated-v1','config':{'architecture':cfg['architecture'],'os':'linux',
                    'entrypoint':cfg['config']['Entrypoint'],'cmd':[],'env':cfg['config']['Env'],'working_dir':'/',
                    'user':'65532:65532','stop_signal':'SIGTERM','diff_ids':cfg['rootfs']['diff_ids']},
                'filesystem':sorted(rows,key=lambda row:row['path'])}
        self.lineage = {'schema_version':'extension-build-lineage-v2','extension_id':'synthetic-provider','extension_version':'1.0.0',
            'port_contract_version':'provider-port-v1','launch_profile':'provider-private-transform-v1','index':self.index,
            'platforms':[{'measured_platform_entry':self.entries[p],'build_identity':self.identities[p],
                'extraction_evidence_sha256':sha256(canonical_json(self.filesystems[p])).hexdigest()} for p in self.platforms]}
        self.base_retained = dict(self.retained)

    def add(self,role,raw):
        ref = _fixture_ref(raw)
        previous = self.retained.get(ref['sha256'])
        assert previous is None or previous == (role,raw), 'Fixture digest cannot acquire a second role'
        self.retained[ref['sha256']] = (role,raw)
        return ref

    def candidate(self,slot):
        from copy import deepcopy
        from app.tests.test_provider_prepare_contracts import _provider_candidate
        from app.extensions.candidate_contracts import metadata_ref,parse_bundle
        bundle,_ = _provider_candidate(slot)
        value = bundle.as_dict()
        for doc in value['documents']:
            if doc['document_kind'] == 'provenance': doc['content'] = deepcopy(self.lineage)
        descriptor = value['service_descriptor']
        descriptor['index'] = deepcopy(self.index)
        descriptor['platforms'] = [deepcopy(self.entries[p]) for p in self.platforms]
        provenance = metadata_ref('provenance',canonical_json(self.lineage))
        descriptor['evidence']['provenance_ref'] = provenance
        value['manifest']['source']['provenance_ref'] = provenance
        value['manifest']['artifact']['service_descriptor_ref'] = metadata_ref('service_descriptor',canonical_json(descriptor))
        return parse_bundle(value)

    def documents(self,platform,*,medium=False):
        from copy import deepcopy
        from base64 import b64encode
        import json
        from urllib.parse import quote
        fs = self.filesystems[platform]
        fs_ref = self.add('filesystem_report',canonical_json(fs))
        statement = self.add('origin_evidence',b'SYNTHETIC TEST ONLY accountable origin, acquisition, supplier-build linkage and rights assertion; no native observation.')
        license_text = b'SYNTHETIC TEST ONLY license text for this labeled fixture; no permission for any real dependency is asserted.'
        license_ref = self.add('license_text',license_text)
        status_ref = self.add('origin_evidence',self.raw_members[platform]['/var/lib/dpkg/status'])
        components,artifacts = [],[]
        status_layer = fs['config']['diff_ids'][0]
        regulars = [row for row in fs['filesystem'] if row['kind'] == 'file']
        files = []
        file_ids = {}
        for index,row in enumerate(regulars):
            path = row['path']
            file_ids[path] = 'file-'+str(index)
            layer = fs['config']['diff_ids'][-1] if path.startswith('/opt/') else status_layer
            files.append({'id':file_ids[path],'location':{'path':path,'layerID':layer},
                'metadata':{'mode':row['mode'],'type':'RegularFile','userID':row['uid'],'groupID':row['gid'],
                    'mimeType':'application/octet-stream','size':row['size_bytes']},
                'digests':[{'algorithm':'sha256','value':row['sha256']}]})
        def component(id_,class_,name,version,purl,paths,syft_ids,inputs,parents=(),cpes=()):
            value = {'spdx_id':'SPDXRef-'+id_,'class':class_,'name':name,'version':version,'purl':purl,'cpes':list(cpes),
                'syft_ids':list(syft_ids),'parent_spdx_ids':list(parents),'files':sorted(paths),'inputs':inputs,
                'license':{'concluded':'LicenseRef-Synthetic','texts':[license_ref],'rationale':'SYNTHETIC TEST ONLY',
                    'obligations':[{'kind':kind,'disposition':'not-applicable','rationale':'SYNTHETIC TEST ONLY',
                        'evidence':[statement]} for kind in ('notice','source-offer','redistribution','local-use')]},
                'scanner_scope':'first-party-not-covered' if class_ == 'first-party' else 'third-party'}
            components.append(value)
            return value
        base_identity = {'sha256':self.inputs[platform]['base']['index']['digest'][7:],
            'size_bytes':self.inputs[platform]['base']['index']['size_bytes']}
        for name,version,arch,path,source in (
            ('synthetic-runtime','1:2.3-4',platform.split('/')[1],'/usr/lib/synthetic-runtime.so','synthetic-src'),
            ('synthetic-data','2.0','all','/usr/share/synthetic-data','synthetic-data')):
            id_ = 'deb-'+name
            purl = 'pkg:deb/debian/'+name+'@'+quote(version,safe='.-_~')+'?arch='+arch+'&distro=debian-12'
            component(id_,'debian',name,version,purl,[path],[id_],[{'kind':'base','identity':base_identity,'evidence':[statement]}])
            artifacts.append({'id':id_,'name':name,'version':version,'type':'deb','foundBy':'dpkg-db-cataloger',
                'locations':[{'path':'/var/lib/dpkg/status','accessPath':'/var/lib/dpkg/status','layerID':status_layer}],
                'licenses':[],'language':'','cpes':[],'purl':purl,'metadataType':'dpkg-db-entry',
                'metadata':{'package':name,'source':source,'version':version,'sourceVersion':version,
                    'architecture':arch,'maintainer':'SYNTHETIC TEST ONLY','installedSize':1,
                    'files':[{'path':path,'isConfigFile':False}]}})
        distributions = next(row['distributions'] for row in self.dependency['platforms'] if row['platform'] == platform)
        for distribution in distributions:
            name,version = distribution['name'],distribution['version']
            id_ = 'python-'+name
            paths = [row['path'] for row in distribution['files']]
            purl = 'pkg:pypi/'+name+'@'+version
            component(id_,'python-wheel',name,version,purl,paths,[id_],
                [{'kind':'wheel','identity':distribution['wheel'],'evidence':[statement]}])
            artifacts.append({'id':id_,'name':name,'version':version,'type':'python','foundBy':'python-installed-package-cataloger',
                'locations':[{'path':paths[-1],'accessPath':paths[-1],'layerID':fs['config']['diff_ids'][-1]}],
                'licenses':[],'language':'python','cpes':[],'purl':purl,'metadataType':'python-package',
                'metadata':{'name':name,'version':version,'author':'SYNTHETIC TEST ONLY','authorEmail':'','platform':'any',
                    'sitePackagesRootPath':'/opt/deeptwin-extension/site','files':[{'path':row['path'].removeprefix('/opt/deeptwin-extension/site/'),
                        'digest':{'algorithm':'sha256','value':row['sha256']},'size':str(row['size_bytes'])} for row in distribution['files']]}})
        cpes = ['cpe:2.3:a:'+vendor+':python:3.12.14:*:*:*:*:*:*:*' for vendor in ('python','python_software_foundation')]
        location = {'path':'/usr/local/bin/python3.12','accessPath':'/usr/local/bin/python3.12','layerID':status_layer}
        component('cpython','cpython','python','3.12.14','pkg:generic/python@3.12.14',['/usr/local/bin/python3.12'],['cpython'],
            [{'kind':'base','identity':base_identity,'evidence':[statement]}],cpes=cpes)
        artifacts.append({'id':'cpython','name':'python','version':'3.12.14','type':'binary','foundBy':'binary-classifier-cataloger',
            'locations':[location],'licenses':[],'language':'','cpes':[{'cpe':value,'source':'SYNTHETIC TEST ONLY'} for value in cpes],
            'purl':'pkg:generic/python@3.12.14','metadataType':'binary-signature',
            'metadata':{'matches':[{'classifier':'python-binary','location':location}]}})
        rpds = next(row for row in distributions if row['name'] == 'rpds-py')
        rust_paths = [row['path'] for row in rpds['files'] if row['path'].endswith('.so')]
        component('synthetic-crate','rust-crate','synthetic-crate','1.0.0','pkg:cargo/synthetic-crate@1.0.0',rust_paths,[],
            [{'kind':'wheel','identity':rpds['wheel'],'evidence':[statement]},
             {'kind':'supplier','identity':statement,'evidence':[statement]}],parents=['SPDXRef-python-rpds-py'])
        first_paths = [row['image_path'] for row in self.source['files']]+['/opt/deeptwin-extension/identity/build-identity-v2.json']
        component('first-party','first-party','synthetic-provider','1.0.0','',first_paths,[],
            [{'kind':'source','identity':self.source['source_bundle'],'evidence':[statement]}])
        components.sort(key=lambda row:row['spdx_id'])
        artifacts.sort(key=lambda row:row['id'])
        relationships = [{'parent':artifact['id'],'child':file_ids[path],'type':'contains'} for artifact in artifacts
            for comp in components if artifact['id'] in comp['syft_ids'] for path in comp['files']]
        layer_sizes = {diff:0 for diff in fs['config']['diff_ids']}
        for file_ in files: layer_sizes[file_['location']['layerID']] += file_['metadata']['size']
        syft_input,audit = syft_configurations(platform)
        syft = {'artifacts':artifacts,'artifactRelationships':relationships,'files':files,
            'source':{'id':'synthetic-image','name':'SYNTHETIC TEST ONLY','version':'1.0.0','type':'image','metadata':{
                'userInput':'/inputs/image','imageID':self.entries[platform]['config']['digest'],
                'manifestDigest':self.entries[platform]['manifest']['digest'],'mediaType':self.entries[platform]['manifest']['media_type'],
                'tags':[],'repoDigests':[],'imageSize':sum(layer_sizes.values()),'architecture':platform.split('/')[1],'os':'linux',
                'layers':[{'mediaType':layer['media_type'],'digest':diff,'size':layer_sizes[diff]}
                    for layer,diff in zip(self.entries[platform]['layers'],fs['config']['diff_ids'],strict=True)],
                'manifest':b64encode(self.manifests[platform]).decode(),'config':b64encode(self.configs[platform]).decode()}},
            'distro':{'id':'debian','versionID':'12'},'descriptor':{'name':'syft','version':'1.42.3','configuration':audit},
            'schema':{'version':'16.1.3','url':'https://raw.githubusercontent.com/anchore/syft/main/schema/json/schema-16.1.3.json'}}
        syft_ref = self.add('image_sbom',canonical_json(syft))
        root_id = 'SPDXRef-CONTAINER'
        def package(comp):
            return {'SPDXID':comp['spdx_id'],'name':comp['name'],'versionInfo':comp['version'],
                'downloadLocation':'NOASSERTION','filesAnalyzed':False,'licenseConcluded':'LicenseRef-Synthetic',
                'licenseDeclared':'(LicenseRef-Synthetic OR MIT)','copyrightText':'SYNTHETIC TEST ONLY',
                'primaryPackagePurpose':'APPLICATION' if comp['class'] in ('cpython','first-party') else 'LIBRARY',
                'externalRefs':([{'referenceCategory':'PACKAGE-MANAGER','referenceType':'purl','referenceLocator':comp['purl']}] if comp['purl'] else [])+
                    [{'referenceCategory':'SECURITY','referenceType':'cpe23Type','referenceLocator':cpe} for cpe in comp['cpes']]}
        root_package = {'SPDXID':root_id,'name':'synthetic-provider','versionInfo':'1.0.0','downloadLocation':'NOASSERTION',
            'filesAnalyzed':False,'licenseConcluded':'LicenseRef-Synthetic','licenseDeclared':'LicenseRef-Synthetic',
            'copyrightText':'SYNTHETIC TEST ONLY','primaryPackagePurpose':'CONTAINER','externalRefs':[],
            'checksums':[{'algorithm':'SHA256','checksumValue':self.entries[platform]['manifest']['digest'][7:]}]}
        spdx_files = [{'SPDXID':'SPDXRef-'+file_ids[row['path']],'fileName':row['path'],
            'checksums':[{'algorithm':'SHA256','checksumValue':row['sha256']}],'licenseConcluded':'LicenseRef-Synthetic',
            'licenseInfoInFiles':['LicenseRef-Synthetic'],'copyrightText':'SYNTHETIC TEST ONLY'} for row in regulars]
        spdx_relationships = [{'spdxElementId':'SPDXRef-DOCUMENT','relationshipType':'DESCRIBES','relatedSpdxElement':root_id}]
        for comp in components:
            spdx_relationships.extend({'spdxElementId':parent,'relationshipType':'CONTAINS','relatedSpdxElement':comp['spdx_id']}
                for parent in (comp['parent_spdx_ids'] or [root_id]))
            spdx_relationships.extend({'spdxElementId':comp['spdx_id'],'relationshipType':'CONTAINS',
                'relatedSpdxElement':'SPDXRef-'+file_ids[path]} for path in comp['files'])
        spdx_relationships.append({'spdxElementId':root_id,'relationshipType':'CONTAINS',
            'relatedSpdxElement':'SPDXRef-'+file_ids['/var/lib/dpkg/status']})
        spdx = {'spdxVersion':'SPDX-2.3','dataLicense':'CC0-1.0','SPDXID':'SPDXRef-DOCUMENT','name':'SYNTHETIC TEST ONLY',
            'documentNamespace':'urn:uuid:'+str(uuid4()),'creationInfo':{'creators':['Organization: SYNTHETIC TEST ONLY'],
                'created':'2023-11-14T22:13:20Z'},'packages':[root_package,*[package(comp) for comp in components]],
            'files':spdx_files,'relationships':spdx_relationships,
            'hasExtractedLicensingInfos':[{'licenseId':'LicenseRef-Synthetic','extractedText':license_text.decode()}]}
        spdx_ref = self.add('component_license_review',canonical_json(spdx))
        image_projection,component_projection = [],[]
        by_id = {artifact['id']:artifact for artifact in artifacts}
        for comp in components:
            upstreams = []
            if comp['class'] == 'debian':
                metadata = by_id[comp['syft_ids'][0]]['metadata']
                upstreams = [{'name':metadata['source'],'version':metadata['sourceVersion']}]
            for id_ in comp['syft_ids']:
                artifact = by_id[id_]
                image_projection.append({'input_id':id_,'grype_id':id_,'type':artifact['type'],
                    'name':comp['name'],'version':comp['version'],'purl':comp['purl'],'cpes':comp['cpes'],'upstreams':upstreams})
            component_projection.append({'input_id':comp['spdx_id'],'grype_id':comp['spdx_id'].removeprefix('SPDXRef-'),
                'type':{'debian':'deb','python-wheel':'python','rust-crate':'rust-crate','cpython':'UnknownPackage','first-party':'UnknownPackage'}[comp['class']],
                'name':comp['name'],'version':comp['version'],'purl':comp['purl'],'cpes':comp['cpes'],'upstreams':upstreams})
        mapping = {'schema_version':'provider-component-map-v2','image_sbom':syft_ref,'component_spdx':spdx_ref,
            'filesystem_report':fs_ref,'dependency_report':self.dependency_ref,'source_report':self.source_ref,
            'dpkg_status':status_ref,'components':components,
            'file_links':[{'path':row['path'],'syft_file_ids':[file_ids[row['path']]],
                'spdx_file_id':'SPDXRef-'+file_ids[row['path']],
                'components':[comp['spdx_id'] for comp in components if row['path'] in comp['files']]} for row in regulars],
            'image_projection':sorted(image_projection,key=lambda row:row['input_id']),
            'component_projection':sorted(component_projection,key=lambda row:row['input_id'])}
        map_ref = self.add('origin_evidence',canonical_json(mapping))
        grype_input = grype_configuration()
        grype_input['external-sources'] = {'enable':False,'maven':{'search-maven-upstream':False,
            'base-url':'https://search.maven.org/solrsearch/select','rate-limit':'300ms'}}
        del grype_input['externalSources'],grype_input['ignore-wontfix'],grype_input['SortBy']
        grype_input.update({'from':[],'sort-by':'risk'})
        grype_input['db'].update({'max-allowed-built-age':'120h','update-available-timeout':'30s',
            'update-download-timeout':'300s','max-update-check-frequency':'2h'})
        status,providers,database = db_observations()
        scan_refs = {}
        accepted = []
        for scan,input_path in (('image','/inputs/image.syft.json'),('component','/inputs/components.spdx.json')):
            matches = []
            if medium:
                match = deepcopy(grype_finding_document()['matches'][0])
                native = next(row for row in artifacts if row['id'] == 'python-idna')
                match['artifact'] = {key:deepcopy(native[key]) for key in ('id','name','version','type','locations','language','purl')}
                match['artifact'].update(licenses=[],cpes=[],upstreams=[])
                if scan == 'component': match['artifact']['locations'] = None
                match['matchDetails'][0]['matcher'] = 'python-matcher'
                matches = [match]
                accepted.append({'scan':scan,'match_index':0,'vulnerability_id':match['vulnerability']['id'],
                    'artifact_id':'python-idna','severity':'Medium'})
            document = {'matches':matches,'source':{'type':'file','target':input_path},'distro':{'name':'debian','version':'12'},
                'descriptor':{'name':'grype','version':'0.110.0','timestamp':'2023-11-14T22:13:20Z',
                    'configuration':grype_configuration(),'db':database}}
            # Explicit raw native numeric observations; no project canonical float codec.
            raw = json.dumps(document,default=float,ensure_ascii=False,separators=(',',':')).encode()
            scan_refs[scan] = self.add(scan+'_scan',raw)
        db_content = _fixture_ref(b'SYNTHETIC TEST ONLY database bytes')
        def tool(name,version,input_,resolved):
            return {'name':name,'version':version,'archive_identity':_fixture_ref(('SYNTHETIC TEST ONLY archive '+name).encode()),
                'executable_identity':_fixture_ref(('SYNTHETIC TEST ONLY executable '+name).encode()),'acquisition':[statement],
                'version_output':self.add('origin_evidence',('SYNTHETIC TEST ONLY '+name+' '+version).encode()),
                'config_input':self.add('origin_evidence',canonical_json(input_)),
                'resolved_config':self.add('origin_evidence',canonical_json(resolved))}
        syft_tool,grype_tool = tool('syft','1.42.3',syft_input,audit),tool('grype','0.110.0',grype_input,grype_configuration())
        def run(name,argv,inputs,output):
            return {'invocation_id':'synthetic-'+name+'-'+output['sha256'][:8],'tool':name,'started_at_ms':1699999999000,
                'finished_at_ms':1700000000000,'argv':argv,'environment':[{'name':'LANG','value':'C.UTF-8'},
                    {'name':'LC_ALL','value':'C.UTF-8'}],'cwd':'/work','inputs':[{'name':key,'identity':value} for key,value in inputs],
                'output':output,'stderr_utf8':'','exit_code':0,'diagnostics':[]}
        cohort = {'schema_version':'provider-scanner-cohort-v1','host_platform':platform,'syft':syft_tool,'grype':grype_tool,
            'adapter_source':self.add('origin_evidence',b'SYNTHETIC TEST ONLY adapter source bytes'),
            'producer_recipe':self.add('origin_evidence',b'SYNTHETIC TEST ONLY fixed offline producer recipe'),
            'schema_sources':[{'uri':'urn:synthetic:schema:source','content':self.add('origin_evidence',
                b'{"title":"SYNTHETIC TEST ONLY schema source"}')}],
            'db':{'schema_version':6,'archive_identity':_fixture_ref(b'SYNTHETIC TEST ONLY DB archive'),
                'content_identity':db_content,'built_at_ms':1699913600000,'acquisition':[statement],
                'distribution_metadata':self.add('origin_evidence',b'{"synthetic":"TEST ONLY DB distribution metadata"}'),
                'status':self.add('origin_evidence',canonical_json(status)),
                'providers':self.add('origin_evidence',canonical_json(providers))},
            'syft_run':run('syft',['/tools/syft','scan','/inputs/image','--config','/config/syft.json','--output','syft-json'],
                [('image_index',{'sha256':self.index['digest'][7:],'size_bytes':self.index['size_bytes']}),
                 ('selected_manifest',{'sha256':self.entries[platform]['manifest']['digest'][7:],'size_bytes':self.entries[platform]['manifest']['size_bytes']}),
                 ('config',syft_tool['config_input']),('executable',syft_tool['executable_identity'])],syft_ref)}
        cohort_ref = self.add('cohort_manifest',canonical_json(cohort))
        invocations = {}
        for scan,path,sbom in (('image','/inputs/image.syft.json',syft_ref),('component','/inputs/components.spdx.json',spdx_ref)):
            invocation = {'schema_version':'provider-scanner-invocation-v1','cohort':cohort_ref,'scan':scan,
                'run':run('grype',['/tools/grype','sbom:'+path,'--config','/config/grype.json','--output','json'],
                    [('sbom',sbom),('db',db_content),('config',grype_tool['config_input']),('executable',grype_tool['executable_identity'])],scan_refs[scan])}
            invocations[scan] = self.add('invocation',canonical_json(invocation))
        def dep(suffix,digest): return {'uri':'urn:deeptwin:r1:'+suffix,'digest':{'sha256':digest}}
        selected = self.inputs[platform]
        dependencies = [dep('recipe',_fixture_ref(canonical_json(self.recipe))['sha256']),dep('source-bundle',self.source['source_bundle']['sha256']),
            dep('dependency-input-set',_fixture_ref(canonical_json(selected))['sha256']),dep('base-lock',self.recipe['base_lock']['sha256']),
            dep('dependency-lock',selected['lock']['sha256']),dep('base',selected['base']['index']['digest'][7:]),
            dep('toolset',self.recipe['toolset']['sha256']),dep('observer',next(row['sha256'] for row in self.toolset if row['path'].endswith('/inspect.py')))]
        dependencies.extend(dep('source/'+quote(row['source_path'],safe='/.-_~'),row['sha256']) for row in self.source['files'])
        dependencies.extend(dep('wheel/'+quote(row['filename'],safe='/.-_~'),row['wheel']['sha256']) for row in selected['artifacts'])
        builder_deps = [dep('toolset',self.recipe['toolset']['sha256']),
            *[dep('tool/'+quote(row['path'],safe='/.-_~'),row['sha256']) for row in self.toolset]]
        provenance = {'_type':'https://in-toto.io/Statement/v1','subject':[
            {'name':'image-index','digest':{'sha256':self.index['digest'][7:]}},
            {'name':'selected-manifest','digest':{'sha256':self.entries[platform]['manifest']['digest'][7:]}},
            {'name':'image-config','digest':{'sha256':self.entries[platform]['config']['digest'][7:]}}],
            'predicateType':'https://slsa.dev/provenance/v1','predicate':{'buildDefinition':{
                'buildType':'urn:deeptwin:build-type:provider-r1-offline-assembly:v1','internalParameters':{},
                'externalParameters':{'extension_id':'synthetic-provider','extension_version':'1.0.0','platform':platform,
                    'recipe':_fixture_ref(canonical_json(self.recipe)),'source_closure':self.source_ref,
                    'dependency_closure':self.dependency_ref,'toolset':self.recipe['toolset']},
                'resolvedDependencies':sorted(dependencies,key=lambda row:row['uri'])},
                'runDetails':{'builder':{'id':'urn:deeptwin:builder:provider-r1-observer:v1',
                    'version':{'observer':next(row['sha256'] for row in self.toolset if row['path'].endswith('/inspect.py'))},
                    'builderDependencies':sorted(builder_deps,key=lambda row:row['uri'])},
                    'metadata':{'invocationId':str(uuid4()),'startedOn':'2023-11-14T22:13:00Z','finishedOn':'2023-11-14T22:13:10Z'},
                    'byproducts':[{'name':name,'digest':{'sha256':ref['sha256']}} for name,ref in
                        (('source-report',self.source_ref),('dependency-report',self.dependency_ref),('filesystem-report',fs_ref))]}}}
        provenance_ref = self.add('provenance',canonical_json(provenance))
        envelope = review_envelope()
        review = envelope['payload']
        from app.deployment.installation_release_contracts import installation_evidence_policy_sha256
        review.update(evidence_policy_sha256=installation_evidence_policy_sha256(),
            reviewer={'id':'synthetic','name':'SYNTHETIC TEST ONLY','authority_basis':[statement]},
            subject={'extension_id':'synthetic-provider','extension_version':'1.0.0','platform':platform,
                'image_index':{'sha256':self.index['digest'][7:],'size_bytes':self.index['size_bytes']},
                'selected_manifest':{'sha256':self.entries[platform]['manifest']['digest'][7:],'size_bytes':self.entries[platform]['manifest']['size_bytes']},
                'config':{'sha256':self.entries[platform]['config']['digest'][7:],'size_bytes':self.entries[platform]['config']['size_bytes']},
                'layers':[{'sha256':row['digest'][7:],'size_bytes':row['size_bytes']} for row in self.entries[platform]['layers']],
                'build_identity_sha256':_fixture_ref(canonical_json(self.identities[platform]))['sha256'],
                'source_closure':self.source_ref,'dependency_closure':self.dependency_ref,'filesystem_inspection':fs_ref},
            provenance=provenance_ref,component_map=map_ref,cohort=cohort_ref,image_invocation=invocations['image'],component_invocation=invocations['component'],
            origin_review={'rationale':'SYNTHETIC TEST ONLY','evidence':[statement]},
            license_review={'rationale':'SYNTHETIC TEST ONLY','evidence':[statement]},
            finding_review={'image_scan':scan_refs['image'],'component_scan':scan_refs['component'],'rationale':'SYNTHETIC TEST ONLY','accepted':accepted})
        return envelope

    def signed_documents(self,*,platform,bundle,profile,edit=None,review_edit=None,trust_edit=None,medium=False,extra_objects=()):
        from nacl.signing import SigningKey
        from base64 import urlsafe_b64encode
        from app.extensions.provider_installation_contracts import FIRST_ROLES,ReleasePacket,parse_installation_header
        from app.deployment.installation_release_contracts import _context_bytes
        from app.tests.installation_release_fixture import trust_document
        self.retained = dict(self.base_retained)
        envelope = self.documents(platform,medium=medium)
        if edit is not None:
            import json
            from copy import deepcopy
            original = dict(self.retained)
            rebuilt,refs = {},{}
            def translate(value):
                if type(value) is dict:
                    if set(value) == {'sha256','size_bytes'} and value['sha256'] in original:
                        return rebuild(value['sha256'])
                    return {key:translate(child) for key,child in value.items()}
                if type(value) is list: return [translate(child) for child in value]
                return value
            def rebuild(digest):
                if digest in refs: return refs[digest]
                role,raw = original[digest]
                try: value = json.loads(raw)
                except (ValueError,UnicodeError): pass
                else:
                    value = translate(value)
                    raw = (json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
                        if role in ('image_sbom','component_license_review','image_scan','component_scan','provenance')
                        else canonical_json(value))
                raw = edit(role,raw)
                ref = _fixture_ref(raw)
                rebuilt[ref['sha256']] = (role,raw)
                refs[digest] = ref
                return ref
            envelope = translate(deepcopy(envelope))
            for digest in original: rebuild(digest)
            self.retained = rebuilt
        if review_edit is not None: review_edit(envelope)
        for role,raw in extra_objects: self.add(role,raw)
        ordered = []
        for role in FIRST_ROLES[1:]:
            entries = [(digest,raw) for digest,(kind,raw) in self.retained.items() if kind == role]
            assert len(entries) == 1
            digest,raw = entries[0]
            ordered.append(({'role':role,'sha256':digest,'size_bytes':len(raw)},raw))
        ordered.extend(sorted([({'role':role,'sha256':digest,'size_bytes':len(raw)},raw)
            for digest,(role,raw) in self.retained.items() if role not in FIRST_ROLES],key=lambda row:(row[0]['role'],row[0]['sha256'])))
        envelope['payload']['objects'] = [row for row,_ in ordered]
        key = SigningKey.generate()
        unsigned = {key:value for key,value in envelope.items() if key != 'signature'}
        envelope['signature'] = urlsafe_b64encode(key.sign(b'deeptwin:provider-release-review:v1\n'+canonical_json(unsigned)).signature).rstrip(b'=').decode()
        raw = canonical_json(envelope)
        descriptors = [{'role':'release_review',**_fixture_ref(raw)},*[row for row,_ in ordered]]
        trust = trust_document(bundle)
        trust['keys'][0].update(key_id=envelope['key_id'],public_key=urlsafe_b64encode(bytes(key.verify_key)).rstrip(b'=').decode())
        trust['allowed_releases'] = [{'extension_id':'synthetic-provider','extension_version':'1.0.0','platform':platform,
            'image_index_sha256':self.index['digest'][7:],'selected_manifest_sha256':self.entries[platform]['manifest']['digest'][7:],
            'release_review':_fixture_ref(raw),'key_id':envelope['key_id']}]
        if trust_edit is not None: trust_edit(trust,envelope)
        trust_raw = canonical_json(trust)
        sources = (('release-trust.json',trust_raw),('installation-release-context.json',
            _context_bytes(bundle,trust_raw,profile)))
        return descriptors,(raw,*[body for _,body in ordered]),sources

    def packet(self,case,**options):
        from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header
        descriptors,objects,sources = self.signed_documents(platform=case.actual.tree.platform,
            bundle=case.actual.tree.bundle,profile=case.profile,**options)
        header = {'schema_version':'provider-installation-command-v1','command_id':str(uuid4()),
            'staged_installation_ref':case.installation_ref.as_dict(),'objects':descriptors}
        return ReleasePacket(parse_installation_header(canonical_json(header)),objects),sources


@pytest.fixture
def full_release_case(tmp_path,monkeypatch,request):
    with _full_release_context(tmp_path,monkeypatch,getattr(request,'param','linux/amd64')) as case:
        yield case


@contextmanager
def _full_release_context(tmp_path,monkeypatch,parameter):
    from app.tests import provider_receipt_fixture as receipt_fixture
    from app.tests import provider_source_fixture as source_fixture
    from app.tests import provider_conformance_fixture as conformance_fixture
    from app.tests.provider_conformance_fixture import staged_conformance_app
    platform = parameter if type(parameter) is str else parameter['platform']
    release = SyntheticRelease(status_variant=parameter.get('status') if type(parameter) is dict else None)
    original_publication,original_case = receipt_fixture.publication_tree,source_fixture.case
    def publication(path,patch,**kwargs): return original_publication(path,patch,platform=platform,**kwargs)
    def source_case(**kwargs): return original_case(**{**kwargs,'platform':platform})
    monkeypatch.setattr(receipt_fixture,'publication_tree',publication)
    monkeypatch.setattr(source_fixture,'case',source_case)
    monkeypatch.setattr(receipt_fixture,'worker_candidate',release.candidate)
    monkeypatch.setattr(receipt_fixture,'WORKER_BYTES',LAUNCHER)
    if type(parameter) is dict and parameter.get('legacy_staged'):
        original_receipt_context = conformance_fixture.provider_receipt_context
        def coexistence_context(path,patch,**kwargs):
            return original_receipt_context(path,patch,**{**kwargs,
                'slot_id':2,'legacy_staged':True,'legacy_case':'valid_succeeded_present'})
        monkeypatch.setattr(conformance_fixture,'provider_receipt_context',coexistence_context)
    frozen = []
    if type(parameter) is dict and parameter.get('release_source'):
        from app.deployment.installation_release_contracts import ROOT,STARTUP_KEY
        original_arguments = receipt_fixture.app_arguments
        def arguments(tree):
            data,options = original_arguments(tree)
            variant = parameter.get('variant','valid')
            def trust_edit(trust,envelope):
                if variant in ('deny_empty','P1','P9'): trust['allowed_releases'] = []
                elif variant == 'P2': trust['revoked_key_ids'] = [envelope['key_id']]
                elif variant == 'P3': trust['revoked_review_sha256'] = [trust['allowed_releases'][0]['release_review']['sha256']]
                elif variant == 'P4': trust['revoked_manifest_sha256'] = [trust['allowed_releases'][0]['selected_manifest_sha256']]
                elif variant == 'P6': trust['valid_until_ms'] = 1700000000000
                elif variant == 'P7': trust['valid_from_ms'] = 253402300700000
                elif variant in ('P8','P10'): trust['keys'][0]['issuance_not_after_ms'] = 1700000000001
            def review_edit(envelope):
                if variant == 'foreign_policy': envelope['payload']['evidence_policy_sha256'] = 'f'*64
            def edit(role,raw):
                import json
                if variant == 'wrong_toolset' and role == 'source_report':
                    value = json.loads(raw); value['toolset']['sha256'] = 'f'*64
                    return canonical_json(value)
                if variant == 'high_finding' and role == 'image_scan':
                    value = json.loads(raw); value['matches'][0]['vulnerability']['severity'] = 'High'
                    return json.dumps(value,separators=(',',':')).encode()
                return raw
            descriptors,objects,sources = release.signed_documents(platform=platform,bundle=tree.bundle,profile=tree.profile,
                trust_edit=trust_edit,review_edit=review_edit,edit=edit if variant in ('wrong_toolset','high_finding') else None,
                medium=variant == 'high_finding')
            if variant == 'P5':
                import json
                trust,context = (json.loads(raw) for _,raw in sources)
                trust['allowed_releases'][0]['key_id'] = str(uuid4())
                raw = canonical_json(trust)
                context['release_trust'] = _fixture_ref(raw)
                sources = (('release-trust.json',raw),('installation-release-context.json',canonical_json(context)))
            tree.directory(ROOT,0,21201)
            tree.directory(ROOT/'documents',0,21201)
            tree.mount(ROOT,True)
            for name,raw in sources: tree.write(ROOT/'documents'/name,raw,0,21201)
            options['first_party_startup_values'][STARTUP_KEY] = sha256(sources[1][1]).hexdigest()
            frozen.append((descriptors,objects,sources))
            return data,options
        monkeypatch.setattr(receipt_fixture,'app_arguments',arguments)
    if platform == 'linux/arm64':
        from types import SimpleNamespace
        original_worker = conformance_fixture.provider_worker
        class SelectedWorkerMetadata:
            def __init__(self,bundle): self.bundle = bundle
            def as_dict(self):
                value = self.bundle.as_dict()
                lineage = next(row['content'] for row in value['documents'] if row['document_kind'] == 'provenance')
                lineage['platforms'].sort(key=lambda row:row['build_identity']['platform'] != platform)
                return value
        def worker(actual,patch):
            # The inherited image-writer fixture takes its metadata from row zero.
            # Select ARM only for that fixture reader, never reorder the stored candidate/lineage.
            image_writer_input = SimpleNamespace(**{**vars(actual),'bundle':SelectedWorkerMetadata(actual.bundle)})
            return original_worker(image_writer_input,patch)
        monkeypatch.setattr(conformance_fixture,'provider_worker',worker)
    with staged_conformance_app(tmp_path,monkeypatch) as case:
        case.release = release
        if frozen:
            from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header
            descriptors,objects,sources = frozen[0]
            case.packet = ReleasePacket(parse_installation_header(canonical_json({
                'schema_version':'provider-installation-command-v1','command_id':str(uuid4()),
                'staged_installation_ref':case.installation_ref.as_dict(),'objects':descriptors})),objects)
            case.source_files = sources
        yield case


def installation_snapshot(case):
    from types import SimpleNamespace
    from app.deployment import prepare_storage as storage
    with case.domain._connection() as db:
        tables = ('domain_records','domain_edges','domain_record_blobs','api_event_envelopes',
            *('deployment_prepare_'+table for table in ('migrations',*storage.TABLES_V6)),
            'provider_conformance_migrations','provider_conformance_control','provider_conformance_runs')
        authority = tuple((table,tuple(tuple(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid'))) for table in tables)
        old = tuple(tuple(row) for row in db.execute("SELECT kind,id,version,sha256,body FROM domain_records WHERE NOT(kind='extension_installation' AND version=2) ORDER BY rowid"))
        verified = tuple(tuple(row) for row in db.execute("SELECT kind,id,version,sha256 FROM domain_records WHERE kind='extension_installation' AND version=2"))
        count = db.execute("SELECT count(*) FROM api_event_envelopes WHERE event_type='extension.verified'").fetchone()[0]
        return SimpleNamespace(authority=authority,old_record_bytes=old,verified_refs=verified,verified_event_count=count)


@pytest.fixture
def installation_case(tmp_path,monkeypatch,request):
    parameter = getattr(request,'param','valid')
    assert parameter in ('valid','framed_worker','deny_empty','high_finding','foreign_policy','wrong_toolset',*[f'P{i}' for i in range(1,11)])
    with _full_release_context(tmp_path,monkeypatch,{'platform':'linux/amd64','release_source':True,'variant':parameter}) as case:
        from app.deployment.installation_release_contracts import ROOT
        from app.extensions.provider_installation_contracts import PREFIX,MEDIA_TYPE
        case.stage_ref = case.installation_ref
        case.variant = parameter
        case.b_service = case.service
        case.verification_service = case.actual.app.state.first_party_exports['provider-installation.service']
        case.source_root,case.source_pin = ROOT,sha256(case.source_files[1][1]).hexdigest()
        case.files = {row['role']:raw for row,raw in zip(case.packet.header.as_dict()['objects'][:10],case.packet.objects[:10])}
        case.auth_headers = {'Origin':case.profile.http_origin,'Sec-Fetch-Site':'same-origin',
            'X-Deeptwin-Csrf':case.csrf,'Content-Type':MEDIA_TYPE}
        case.path = case.profile.base_path.rstrip('/')+'/api/v1/extensions/provider-installation'
        def post_packet(packet):
            header = packet.header.content_bytes
            raw = PREFIX+len(header).to_bytes(4,'big')+header+b''.join(packet.objects)
            return case.client.post(case.path,content=raw,headers=case.auth_headers)
        case.post_packet = post_packet
        case.snapshot = lambda:installation_snapshot(case)
        case.rebuild_packet = lambda changes:case.release.packet(case,edit=lambda role,raw:changes.get(role,raw))[0]
        case.restart_without_release_source = lambda:_restart_installation_without_source(case)
        if parameter == 'framed_worker':
            from app.tests.provider_conformance_fixture import _retained_provider_conformance_worker
            with _retained_provider_conformance_worker(case,monkeypatch) as worker:
                case.worker = worker
                yield case
        else: yield case


@contextmanager
def _restart_installation_without_source(case):
    from types import SimpleNamespace
    from dataclasses import replace
    from starlette.testclient import TestClient
    from app.deployment.installation_release_contracts import STARTUP_KEY
    from app.server import create_app
    from app.tests.provider_receipt_fixture import bound_request
    owner = case._receipt_owner
    assert not owner[1]
    cookies = dict(case.client.cookies)
    arguments = dict(case.actual.arguments)
    arguments['first_party_startup_values'] = {key:value for key,value in arguments['first_party_startup_values'].items() if key != STARTUP_KEY}
    worker_owner = case._conformance_worker_owner
    if worker_owner is not None and not worker_owner[2]:
        worker_owner[2] = True
        worker_owner[0].__exit__(None,None,None)
    owner[1] = True
    owner[0].__exit__(None,None,None)
    application = create_app(case.actual.data,**arguments)
    with TestClient(application,base_url=case.profile.http_origin) as client:
        client.cookies.update(cookies)
        exports = application.state.first_party_exports
        assert exports['installation-release.source-context'] is None
        request = bound_request(application,client,case.profile,case.csrf)
        actual = SimpleNamespace(**{**vars(case.actual),'app':application,'client':client,
            'owner':application.state.owner_authority,'domain':application.state.domain_store,
            'service':exports['deployment-prepare.service'],'context':exports['deployment-provider.source-context'],
            'request':request,'read_request':replace(request,method='GET')})
        reopened = SimpleNamespace(**{**vars(case),'actual':actual,'client':client,'domain':actual.domain,
            'prepare':actual.service,'b_service':exports['provider-conformance.service'],
            'verification_service':exports['provider-installation.service']})
        reopened.snapshot = lambda:installation_snapshot(reopened)
        def post(packet):
            from app.extensions.provider_installation_contracts import PREFIX
            header = packet.header.content_bytes
            return client.post(case.path,headers=case.auth_headers,
                content=PREFIX+len(header).to_bytes(4,'big')+header+b''.join(packet.objects))
        reopened.post_packet = post
        yield reopened


@pytest.fixture
def release_evaluation_case(full_release_case,request):
    from types import SimpleNamespace
    from app.domain.store import _writer
    from app.deployment.installation_release_contracts import parse_release_trust
    variant = getattr(request,'param','valid')
    assert variant in ('valid','foreign_policy','wrong_toolset',*[f'P{i}' for i in range(1,11)])
    case = full_release_case
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    def trust_edit(trust,envelope):
        if variant in ('P1','P9'): trust['allowed_releases'] = []
        elif variant == 'P2': trust['revoked_key_ids'] = [envelope['key_id']]
        elif variant == 'P3': trust['revoked_review_sha256'] = [trust['allowed_releases'][0]['release_review']['sha256']]
        elif variant == 'P4': trust['revoked_manifest_sha256'] = [trust['allowed_releases'][0]['selected_manifest_sha256']]
        elif variant == 'P6': trust['valid_until_ms'] = 1700000000000
        elif variant == 'P7': trust['valid_from_ms'] = 1700000000001
        elif variant in ('P8','P10'): trust['keys'][0]['issuance_not_after_ms'] = 1700000000001
    def review_edit(envelope):
        if variant == 'foreign_policy': envelope['payload']['evidence_policy_sha256'] = 'f'*64
    def edit(role,raw):
        if role == 'source_report' and variant == 'wrong_toolset':
            import json
            value = json.loads(raw); value['toolset']['sha256'] = 'f'*64
            return canonical_json(value)
        return raw
    packet,sources = case.release.packet(case,edit=edit if variant == 'wrong_toolset' else None,
        trust_edit=trust_edit,review_edit=review_edit)
    if variant == 'P5':
        malformed = parse_release_trust(sources[0][1]).as_dict()
        malformed['allowed_releases'][0]['key_id'] = str(uuid4())
        bad_trust = canonical_json(malformed)
        sources = None  # no fabricated well-typed evaluator source for malformed authority
    else: bad_trust = None
    now = 1700086400000 if variant in ('P8','P10') else 1700000000000
    yield SimpleNamespace(packet=packet,source_files=sources,stage=stage,now_ms=now,
        malformed_trust_bytes=bad_trust,variant=variant)


@pytest.fixture
def staged_installation(tmp_path,monkeypatch):
    from app.tests.provider_conformance_fixture import staged_conformance_app
    with staged_conformance_app(tmp_path,monkeypatch) as case:
        yield case
