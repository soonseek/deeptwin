import importlib
from decimal import Decimal
import pytest
from app.tests.provider_installation_fixture import release_documents
from app.tests.provider_installation_fixture import staged_installation
from app.tests.provider_installation_fixture import full_release_case
from app.tests.provider_installation_fixture import release_evaluation_case


def module():
    try: return importlib.import_module('app.extensions.provider_installation_evidence')
    except ModuleNotFoundError: pytest.fail('Actual bounded release evidence parser is missing')


def test_external_scan_preserves_original_numeric_observations(release_documents):
    raw = release_documents['image_scan']
    parsed = module().parse_external_document('image_scan',raw)
    assert parsed.content_bytes == raw
    assert parsed.as_dict()['matches'][0]['vulnerability']['cvss'][0]['metrics']['baseScore'] == Decimal('5.4')
    assert type(parsed.as_dict()['matches']) is list


@pytest.mark.parametrize('raw',[b'{"x":1,"x":2}',b'{"x":{"a":0,"a":1}}',b'{"x":NaN}',
    b'{"x":1e309}',b'{"x":1e-309}',b'{"x":Infinity}',b'{}{}',b'\xef\xbb\xbf{}',
    b'{"x":"\\ud800"}',b'{"x":'+b'1'*65+b'}',b'['*65+b'0'+b']'*65])
def test_external_invalid_lexemes_refuse_before_materialization(raw):
    m = module()
    with pytest.raises(ValueError): m.parse_external_document('image_scan',raw)


@pytest.mark.parametrize('role',['license_text','source_report','unknown'])
def test_external_parser_cannot_reclassify_project_or_plain_objects(role):
    with pytest.raises(ValueError): module().parse_external_document(role,b'{}')


@pytest.mark.parametrize('mutation',[None,'source_version','unknown','metadata_unknown','legacy','null_metadata',
    'location_access','file_access','bool_integer','empty_inventory','unselected'])
def test_syft_literal_selected_type_boundary(mutation):
    from app.tests.provider_installation_fixture import syft_structure
    value = syft_structure()
    if mutation == 'source_version': value['source'].pop('version')
    if mutation == 'unknown': value['files'][0]['future'] = 'not selected'
    if mutation == 'metadata_unknown': value['artifacts'][0]['metadata']['status'] = 'installed'
    if mutation == 'legacy': value['artifacts'][0]['metadataType'] = 'DpkgMetadata'
    if mutation == 'null_metadata': value['artifacts'][0]['metadata'] = None
    if mutation == 'location_access': value['artifacts'][0]['locations'][0].pop('accessPath')
    if mutation == 'file_access': value['files'][0]['location']['accessPath'] = '/synthetic'
    if mutation == 'bool_integer': value['artifacts'][0]['metadata']['installedSize'] = True
    if mutation == 'empty_inventory': value['artifacts'] = []
    if mutation == 'unselected': value['artifacts'][0]['metadataType'] = 'apk-db-entry'
    m = module()
    assert hasattr(m,'_validate_syft_structure'), 'Native Syft selected type validator is missing'
    if mutation is None: m._validate_syft_structure(value)
    else:
        with pytest.raises(m.InstallationError): m._validate_syft_structure(value)


@pytest.mark.parametrize('size',['19',19])
def test_syft_python_record_size_remains_native_string(size):
    from app.tests.provider_installation_fixture import syft_structure
    value = syft_structure()
    value['artifacts'][0].update(type='python',metadataType='python-package',metadata={
        'name':'synthetic','version':'1.0','author':'SYNTHETIC TEST ONLY','authorEmail':'','platform':'any',
        'sitePackagesRootPath':'/synthetic','files':[{'path':'synthetic.py','size':size}]})
    m = module()
    assert hasattr(m,'_validate_syft_structure'), 'Native Syft selected type validator is missing'
    if type(size) is str: m._validate_syft_structure(value)
    else:
        with pytest.raises(m.InstallationError): m._validate_syft_structure(value)


@pytest.mark.parametrize('mutation',[None,'null_empty','sort','duration','kernel','ignore','vex','db','unknown','bool_duration','input_alias'])
def test_exact_native_grype_configuration(mutation):
    from app.tests.provider_installation_fixture import grype_configuration
    value = grype_configuration()
    if mutation == 'null_empty': value['ignore'] = None
    if mutation == 'sort': value['sort-by'] = value.pop('SortBy')['sort-by']
    if mutation == 'duration': value['db']['max-allowed-built-age'] = '120h'
    if mutation == 'kernel': value['match-upstream-kernel-headers'] = False
    if mutation == 'ignore': value['ignore'] = [{'vulnerability':'synthetic'}]
    if mutation == 'vex': value['vex-documents'] = ['/synthetic']
    if mutation == 'db': value['db']['auto-update'] = True
    if mutation == 'unknown': value['match']['python']['future'] = False
    if mutation == 'bool_duration': value['externalSources']['maven']['rateLimit'] = True
    if mutation == 'input_alias': value['external-sources'] = value.pop('externalSources')
    m = module()
    assert hasattr(m,'_validate_grype_configuration'), 'Exact native Grype config validator is missing'
    if mutation in (None,'null_empty'): m._validate_grype_configuration(value)
    else:
        with pytest.raises(m.InstallationError): m._validate_grype_configuration(value)


def test_grype_input_uses_mapstructure_not_native_aliases():
    from app.tests.provider_installation_fixture import grype_configuration
    value = grype_configuration()
    value['external-sources'] = value.pop('externalSources')
    value['external-sources']['maven'] = {'search-maven-upstream':False,
        'base-url':'https://search.maven.org/solrsearch/select','rate-limit':'300ms'}
    value.pop('ignore-wontfix')
    value['sort-by'] = value.pop('SortBy')['sort-by']
    value['from'] = []
    value['db'].update({'max-allowed-built-age':'120h','update-available-timeout':'30s',
        'update-download-timeout':'300s','max-update-check-frequency':'2h'})
    m = module()
    assert hasattr(m,'_validate_grype_configuration'), 'Exact native Grype config validator is missing'
    m._validate_grype_configuration(value,input_file=True)
    value['external-sources']['maven']['search-upstream'] = False
    with pytest.raises(m.InstallationError): m._validate_grype_configuration(value,input_file=True)


def test_raw_string_limit_is_checked_before_decoded_value_materialization(monkeypatch):
    import json
    m = module()
    original = json.decoder.scanstring
    observed = []
    def scan(text,start,strict):
        observed.append(start)
        assert start != 6, 'Over-limit value reached ordinary decoded materialization'
        return original(text,start,strict)
    monkeypatch.setattr(json.decoder,'scanstring',scan)
    with pytest.raises(m.InstallationError):
        m.parse_external_document('image_scan',b'{"x":"'+b'a'*1048577+b'"}')
    assert observed == [2]  # only the small key, not the over-limit value


@pytest.mark.parametrize('count',[1048576,1048577])
def test_raw_decoded_string_byte_boundary(count):
    m = module()
    raw = b'{"x":"'+b'a'*count+b'"}'
    if count == 1048576: assert len(m.parse_external_document('image_scan',raw).as_dict()['x']) == count
    else:
        with pytest.raises(m.InstallationError): m.parse_external_document('image_scan',raw)


@pytest.mark.parametrize('escaped',[b'\\ud83d\\ude00',b'\\u0061',b'\\n',b'\\ud800',b'\\udc00'])
def test_raw_string_preflight_preserves_exact_json_unicode(escaped):
    import json
    m = module()
    raw = b'{"x":"'+escaped+b'"}'
    if escaped in (b'\\ud800',b'\\udc00'):
        with pytest.raises(m.InstallationError): m.parse_external_document('image_scan',raw)
    else: assert m.parse_external_document('image_scan',raw).as_dict() == json.loads(raw)


@pytest.mark.parametrize('declared,concluded,ok',[
    ('MIT','MIT',True),('(MIT OR Apache-2.0)','MIT',True),
    ('(MIT AND (BSD-2-Clause OR ISC))','(MIT AND ISC)',True),
    ('GPL-2.0-only WITH Classpath-exception-2.0','GPL-2.0-only WITH Classpath-exception-2.0',True),
    ('LicenseRef-Synthetic','LicenseRef-Synthetic',True),
    ('NONE','NONE',False),('NOASSERTION','NOASSERTION',False),
    ('(MIT AND ISC)','MIT',False),('(MIT OR ISC)','(MIT OR ISC)',False),
    ('(MIT OR ISC)','BSD-3-Clause',False),('MIT  WITH LLVM-exception','MIT',False),
    ('LicenseRef-Missing','LicenseRef-Missing',False),
    ('LicenseRef-Synthetic WITH LLVM-exception','LicenseRef-Synthetic WITH LLVM-exception',False),
    ('DocumentRef-external:LicenseRef-X','DocumentRef-external:LicenseRef-X',False),
    ('(MIT OR Apache-2.0)\n','MIT',False)])
def test_exact_reviewed_license_selection(declared,concluded,ok):
    m = module()
    assert hasattr(m,'_validate_license_selection'), 'Finite license selection parser is missing'
    if ok: m._validate_license_selection(declared,concluded,{'LicenseRef-Synthetic'})
    else:
        with pytest.raises(m.InstallationError): m._validate_license_selection(declared,concluded,{'LicenseRef-Synthetic'})


@pytest.mark.parametrize('mutation',[None,'diagnostic','high','critical','unknown','missing_severity','related_high',
    'ignored','alerts','null_ignored','extra_artifact','metadata','locations','artifact_version','matcher',
    'detail_type','cpe_python','empty_details','fix_null','extra_vulnerability','bad_cvss','first_party'])
def test_every_native_finding_counts_and_diagnostics_cannot_reduce_it(mutation):
    from copy import deepcopy
    from app.tests.provider_installation_fixture import grype_finding_document
    m = module()
    assert hasattr(m,'_scan_findings'), 'Native every-match scanner interpretation is missing'
    document = grype_finding_document()
    match = document['matches'][0]
    projected = deepcopy(match['artifact'])
    projected.pop('licenses')
    classes = {'synthetic-python':'python-wheel'}
    if mutation == 'diagnostic': match['vulnerability']['cvss'][0]['vendorMetadata']['passed'] = True
    if mutation in ('high','critical','unknown'): match['vulnerability']['severity'] = mutation.title()
    if mutation == 'missing_severity': match['vulnerability'].pop('severity')
    if mutation == 'related_high': match['relatedVulnerabilities'] = [{'id':'CVE-2099-0002','dataSource':'urn:synthetic',
        'severity':'High','urls':[],'cvss':[]}]
    if mutation == 'ignored': document['ignoredMatches'] = [deepcopy(match)]
    if mutation == 'alerts': document['alertsByPackage'] = [{'synthetic':True}]
    if mutation == 'null_ignored': document['ignoredMatches'] = None
    if mutation == 'extra_artifact': match['artifact']['extra'] = False
    if mutation == 'metadata': match['artifact']['metadata'] = {}
    if mutation == 'locations': match['artifact']['locations'] = []
    if mutation == 'artifact_version': match['artifact']['version'] = '2.0'
    if mutation == 'matcher': match['matchDetails'][0]['matcher'] = 'unknown-matcher'
    if mutation == 'detail_type': match['matchDetails'][0]['type'] = 'diagnostic-match'
    if mutation == 'cpe_python': match['matchDetails'][0]['type'] = 'cpe-match'
    if mutation == 'empty_details': match['matchDetails'] = []
    if mutation == 'fix_null': match['matchDetails'][0]['fix'] = None
    if mutation == 'extra_vulnerability': match['vulnerability']['approved'] = True
    if mutation == 'bad_cvss': match['vulnerability']['cvss'][0]['metrics']['baseScore'] = '5.4'
    if mutation == 'first_party': classes['synthetic-python'] = 'first-party'
    if mutation in (None,'diagnostic'):
        assert m._scan_findings(document,{'synthetic-python':projected},classes,scan='component') == [
            {'scan':'component','match_index':0,'vulnerability_id':'CVE-2099-0001',
             'artifact_id':'synthetic-python','severity':'Medium'}]
        assert match['vulnerability']['cvss'][0]['metrics']['baseScore'] == Decimal('5.40')
    else:
        with pytest.raises(m.InstallationError): m._scan_findings(document,{'synthetic-python':projected},classes,scan='component')


def test_independent_signature_and_current_allow_against_actual_staged_identity(staged_installation):
    from app.tests.provider_installation_fixture import signed_authority_packet
    m = module()
    assert hasattr(m,'_authenticate_review'), 'Independent current trust/signature join is missing'
    packet,sources,stage = signed_authority_packet(staged_installation)
    review = m._authenticate_review(packet,sources,stage,1700000000000)
    assert review['subject']['platform'] == stage.stage_record['content']['platform']
    # Artifact issuance does not gain a daily-review expiry.
    assert m._authenticate_review(packet,sources,stage,1700086400000) == review
    for mutation in ('foreign_policy','wrong_subject','bad_signature','deny','revoked_key','revoked_review',
                     'revoked_manifest','expired','future','issuance'):
        packet,sources,stage = signed_authority_packet(staged_installation,mutation)
        with pytest.raises(m.InstallationError): m._authenticate_review(packet,sources,stage,1700000000000)


@pytest.mark.parametrize('mutation',[None,'empty','lost','changed_digest','truncation','error','invalid','schema','null_capture','duplicate'])
def test_db_native_provider_provenance_is_not_a_sha256_or_feed_success_claim(mutation):
    from copy import deepcopy
    from app.tests.provider_installation_fixture import db_observations
    status,providers,scan = db_observations()
    scan = deepcopy(scan)
    if mutation == 'empty': scan['providers'] = {}
    if mutation == 'lost': scan['providers'] = None
    if mutation == 'changed_digest': scan['providers']['synthetic-feed']['input'] = 'sha256:'+'f'*64
    if mutation == 'truncation': scan['providers']['synthetic-feed']['captured'] = '2023-11-13T22:13:21Z'
    if mutation == 'error': scan['status']['error'] = None
    if mutation == 'invalid': scan['status']['valid'] = False
    if mutation == 'schema': scan['status']['schemaVersion'] = '6.1.5'
    if mutation == 'null_capture': providers[0]['dateCaptured'] = None
    if mutation == 'duplicate': providers.append(deepcopy(providers[0]))
    m = module()
    assert hasattr(m,'_validate_database'), 'Native DB cross-view validator is missing'
    if mutation is None: m._validate_database(status,providers,[scan,deepcopy(scan)],1699913600000)
    else:
        with pytest.raises(m.InstallationError): m._validate_database(status,providers,[scan,deepcopy(scan)],1699913600000)


@pytest.mark.parametrize('text,expected',[
    ('2023-11-14T22:13:20Z','1700000000000'),('2023-11-15T07:13:20+09:00','1700000000000'),
    ('2023-11-14T22:13:20.000000001Z','1700000000000000001/1000000'),
    ('2023-11-14T22:13:60Z',None),('2023-11-14 22:13:20Z',None),
    ('2023-11-14T22:13:20.1234567890Z',None)])
def test_native_timestamp_boundaries_do_not_round_submilliseconds(text,expected):
    from fractions import Fraction
    m = module()
    assert hasattr(m,'_timestamp_ms'), 'Exact native timestamp parser is missing'
    if expected is not None: assert m._timestamp_ms(text) == Fraction(expected)
    else:
        with pytest.raises(m.InstallationError): m._timestamp_ms(text)


@pytest.mark.parametrize('mutation',[None,'compressed_id','compressed_size','unknown','base64','decoded_object',
    'config_hash','platform','duplicate_diff','variant'])
def test_native_image_uses_diffid_coordinates_and_raw_embedded_oci(mutation):
    from app.tests.provider_installation_fixture import image_observation
    metadata,filesystem = image_observation()
    if mutation == 'compressed_id': metadata['layers'][0]['digest'] = filesystem['entry']['layers'][0]['digest']
    if mutation == 'compressed_size': metadata['layers'][0]['size'] = filesystem['entry']['layers'][0]['size_bytes']
    if mutation == 'unknown': metadata['repoTags'] = []
    if mutation == 'base64': metadata['config'] += '\n'
    if mutation == 'decoded_object': metadata['config'] = {}
    if mutation == 'config_hash': metadata['imageID'] = 'sha256:'+'f'*64
    if mutation == 'platform': metadata['architecture'] = 'arm64'
    if mutation == 'duplicate_diff': filesystem['config']['diff_ids'].append(filesystem['config']['diff_ids'][0])
    if mutation == 'variant': metadata['architectureVariant'] = 'v8'
    m = module()
    assert hasattr(m,'_validate_image_metadata'), 'Selected image metadata joins are missing'
    if mutation is None: m._validate_image_metadata(metadata,filesystem)
    else:
        with pytest.raises(m.InstallationError): m._validate_image_metadata(metadata,filesystem)


@pytest.mark.parametrize('mutation',[None,'inactive','extra_cataloger','removed_classifier','unknown_packages',
    'overlap','selection','content','remote','input_alias','audit_alias'])
def test_exact_syft_five_cataloger_audit_and_input_configuration(mutation):
    from app.tests.provider_installation_fixture import syft_configurations
    input_,audit = syft_configurations()
    if mutation == 'inactive': audit['packages']['golang'] = {'opaque-descriptive-observation':{'decimal':Decimal('1.20')}}
    if mutation == 'extra_cataloger': audit['catalogers']['used'].append('go-module-cataloger')
    if mutation == 'removed_classifier': audit['packages']['binary'].pop()
    if mutation == 'unknown_packages': audit['packages']['future'] = {}
    if mutation == 'overlap': audit['relationships']['exclude-binary-packages-with-file-ownership-overlap'] = True
    if mutation == 'selection': audit['catalogers']['requested']['selection'] = []
    if mutation == 'content': audit['files']['content']['globs'] = []
    if mutation == 'remote': input_['python']['search-remote-licenses'] = True
    if mutation == 'input_alias': input_['source-name'] = 'synthetic'
    if mutation == 'audit_alias': audit['extra'] = {}
    m = module()
    assert hasattr(m,'_validate_syft_configuration'), 'Exact Syft audit/input selection is missing'
    if mutation in (None,'inactive'): m._validate_syft_configuration(input_,audit,'linux/amd64')
    else:
        with pytest.raises(m.InstallationError): m._validate_syft_configuration(input_,audit,'linux/amd64')


def test_typed_retained_reference_closure_refuses_missing_orphans_and_parser_aliases():
    import json
    from uuid import uuid4
    from hashlib import sha256
    from app.domain.refs import EntityRef,canonical_json
    from app.tests.provider_installation_fixture import packet_header
    from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header
    raw,objects = packet_header(EntityRef('extension_installation',str(uuid4()),1,'a'*64))
    header = json.loads(raw)
    extra = b'{"statement":"SYNTHETIC TEST ONLY"}'
    reference = {'sha256':sha256(extra).hexdigest(),'size_bytes':len(extra)}
    header['objects'].append({'role':'origin_evidence',**reference})
    packet = ReleasePacket(parse_installation_header(canonical_json(header)),(*objects,extra))
    m = module()
    assert hasattr(m,'_EvidenceGraph'), 'Typed retained-reference closure is missing'
    graph = m._EvidenceGraph(packet)
    assert graph.text(reference) == extra.decode()
    with pytest.raises(m.InstallationError): graph.raw_json(reference,'configuration')
    with pytest.raises(m.InstallationError): graph.text({'sha256':'f'*64,'size_bytes':1})
    with pytest.raises(m.InstallationError): graph.finish()
    wrong_size = {**reference,'size_bytes':reference['size_bytes']+1}
    with pytest.raises(m.InstallationError): graph.text(wrong_size)
    with pytest.raises(m.InstallationError): graph.project(reference,'source_report','provider-source-closure-v1')


@pytest.mark.parametrize('platform',['linux/amd64','linux/arm64'])
def test_retained_dpkg_control_parser_preserves_original_folded_bytes(platform):
    from app.tests.provider_installation_fixture import dpkg_status_bytes
    raw = dpkg_status_bytes(platform)
    m = module()
    assert hasattr(m,'parse_dpkg_status'), 'Retained installed status parser is missing'
    parsed = m.parse_dpkg_status(raw,platform)
    assert parsed.content_bytes == raw
    assert [row['Package'] for row in parsed.as_dict()] == ['synthetic-runtime','synthetic-data']
    assert parsed.as_dict()[0]['Description'] == 'SYNTHETIC TEST ONLY\ncontinued description\n.'
    parsed.as_dict()[0]['Status'] = 'deinstall ok config-files'
    assert parsed.as_dict()[0]['Status'] == 'install ok installed'


@pytest.mark.parametrize('status',['','Install ok installed','hold ok installed','deinstall ok config-files',
    'purge ok config-files','install ok config-files','install ok not-installed','install ok unpacked',
    'install ok half-installed','install ok half-configured','install ok triggers-awaited',
    'install ok triggers-pending','install reinstreq installed','install ok installed ',' install ok installed'])
def test_every_uninstalled_or_unsupported_dpkg_status_refuses_whole_document(status):
    from app.tests.provider_installation_fixture import dpkg_status_bytes
    raw = dpkg_status_bytes().replace(b'Status: install ok installed',('Status: '+status).encode(),1)
    m = module()
    assert hasattr(m,'parse_dpkg_status'), 'Retained installed status parser is missing'
    with pytest.raises(m.InstallationError): m.parse_dpkg_status(raw,'linux/amd64')


@pytest.mark.parametrize('mutation',['missing','unknown','duplicate','case_duplicate','separator','blank_identity',
    'identity_fold','orphan_fold','crlf','bom','nul','tab','invalid_utf8','comment','no_final_lf',
    'repeated_separator','duplicate_record','foreign_arch','same_name_arch','multiarch','source'])
def test_closed_dpkg_control_fields_and_record_identity(mutation):
    from app.tests.provider_installation_fixture import dpkg_status_bytes
    raw = dpkg_status_bytes()
    if mutation == 'missing': raw = raw.replace(b'Status: install ok installed\n',b'',1)
    if mutation == 'unknown': raw = b'Unknown: nope\n'+raw
    if mutation == 'duplicate': raw = b'Package: synthetic-runtime\n'+raw
    if mutation == 'case_duplicate': raw = b'package: synthetic-runtime\n'+raw
    if mutation == 'separator': raw = raw.replace(b'Package: ',b'Package:',1)
    if mutation == 'blank_identity': raw = raw.replace(b'Package: synthetic-runtime',b'Package: ',1)
    if mutation == 'identity_fold': raw = raw.replace(b'Version: 1:2.3-4\n',b'Version: 1:2.3-4\n bad\n',1)
    if mutation == 'orphan_fold': raw = b' orphan\n'+raw
    if mutation == 'crlf': raw = raw.replace(b'\n',b'\r\n')
    if mutation == 'bom': raw = b'\xef\xbb\xbf'+raw
    if mutation == 'nul': raw += b'\0'
    if mutation == 'tab': raw = raw.replace(b'continued description',b'continued\tdescription')
    if mutation == 'invalid_utf8': raw = raw.replace(b'continued description',b'\xff')
    if mutation == 'comment': raw = b'# comment\n'+raw
    if mutation == 'no_final_lf': raw = raw[:-1]
    if mutation == 'repeated_separator': raw = raw.replace(b'\n\n',b'\n\n\n')
    if mutation == 'duplicate_record': raw += b'\n'+raw
    if mutation == 'foreign_arch': raw = raw.replace(b'Architecture: amd64',b'Architecture: arm64')
    if mutation == 'same_name_arch': raw = raw.replace(b'Package: synthetic-data',b'Package: synthetic-runtime')
    if mutation == 'multiarch': raw = raw.replace(b'Multi-Arch: same',b'Multi-Arch: maybe')
    if mutation == 'source': raw = raw.replace(b'Source: synthetic-src (1:2.3-4)',b'Source: synthetic-src 1:2.3-4')
    m = module()
    assert hasattr(m,'parse_dpkg_status'), 'Retained installed status parser is missing'
    with pytest.raises(m.InstallationError): m.parse_dpkg_status(raw,'linux/amd64')


def _status_tree():
    from hashlib import sha256
    from app.tests.provider_installation_fixture import dpkg_status_bytes
    raw = dpkg_status_bytes()
    reference = {'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)}
    rows = [{'path':path,'kind':'directory','uid':0,'gid':0,'mode':493}
        for path in ('/','/var','/var/lib','/var/lib/dpkg','/etc')]
    rows.append({'path':'/var/lib/dpkg/status','kind':'file','uid':0,'gid':0,'mode':420,'nlink':1,**reference})
    return rows,reference


@pytest.mark.parametrize('path',['/other/lib/dpkg/status','/other/lib/dpkg/status.d/one',
    '/other/lib/opkg/status','/other/lib/opkg/info/one.control','/var/lib/dpkg/status.d/one'])
def test_every_alternate_retained_cataloger_input_refuses(path):
    rows,reference = _status_tree()
    rows.append({'path':path,'kind':'file'})
    m = module()
    assert hasattr(m,'_validate_dpkg_paths'), 'Complete retained status-path analysis is missing'
    with pytest.raises(m.InstallationError): m._validate_dpkg_paths(rows,reference)


@pytest.mark.parametrize('mutation',[None,'unrelated_dangling','empty_statusd','direct_alias','prefix_alias','ancestor',
    'nlink','size','hash','kind','statusd_symlink'])
def test_dpkg_source_alias_analysis_is_not_host_resolution_or_global_existence(mutation):
    rows,reference = _status_tree()
    status = rows[-1]
    if mutation == 'unrelated_dangling': rows.append({'path':'/etc/mtab','kind':'symlink','target':'/proc/mounts'})
    if mutation == 'empty_statusd': rows.append({'path':'/var/lib/dpkg/status.d','kind':'directory'})
    if mutation == 'direct_alias': rows.append({'path':'/alias','kind':'symlink','target':'/var/lib/dpkg/status'})
    if mutation == 'prefix_alias':
        rows.extend([{'path':'/retained','kind':'directory'},{'path':'/retained/status','kind':'file'},
            {'path':'/other/lib/dpkg','kind':'symlink','target':'/retained'}])
    if mutation == 'ancestor': rows[3] = {'path':'/var/lib/dpkg','kind':'symlink','target':'/retained'}
    if mutation == 'nlink': status['nlink'] = 2
    if mutation == 'size': status['size_bytes'] += 1
    if mutation == 'hash': status['sha256'] = 'f'*64
    if mutation == 'kind': status['kind'] = 'symlink'
    if mutation == 'statusd_symlink': rows.append({'path':'/var/lib/dpkg/status.d','kind':'symlink','target':'/empty'})
    m = module()
    assert hasattr(m,'_validate_dpkg_paths'), 'Complete retained status-path analysis is missing'
    if mutation in (None,'unrelated_dangling','empty_statusd'): m._validate_dpkg_paths(rows,reference)
    else:
        with pytest.raises(m.InstallationError): m._validate_dpkg_paths(rows,reference)


@pytest.mark.parametrize('extra',[False,True])
def test_dpkg_alias_unique_path_budget_exact_and_plus_one(extra):
    rows = [{'path':'/safe','kind':'directory'}]
    rows.extend({'path':'/safe/f'+str(index),'kind':'file'} for index in range(4095))
    rows.extend({'path':path,'kind':'symlink','target':'/safe'} for path in ('/a','/b'))
    if extra: rows.append({'path':'/c','kind':'symlink','target':'/safe/f0'})
    m = module()
    if extra:
        with pytest.raises(m.InstallationError): m._dpkg_alias_paths(rows)
    else: assert len(m._dpkg_alias_paths(rows)) == 8192


@pytest.mark.parametrize('target',['/x/../status','x/../status','/x/./../status'])
def test_dpkg_alias_resolves_intermediate_link_before_parent_component(target):
    rows,reference = _status_tree()
    rows.extend([{'path':'/var/lib/dpkg/subdir','kind':'directory'},
        {'path':'/x','kind':'symlink','target':'/var/lib/dpkg/subdir'},
        {'path':'/alias','kind':'symlink','target':target}])
    m = module()
    with pytest.raises(m.InstallationError): m._validate_dpkg_paths(rows,reference)


def test_native_virtual_location_uses_same_component_order_without_host_resolution():
    rows,reference = _status_tree()
    rows.extend([{'path':'/etc/subdir','kind':'directory'},{'path':'/etc/safe','kind':'file'},
        {'path':'/x','kind':'symlink','target':'/etc/subdir'},
        {'path':'/alias','kind':'symlink','target':'/x/../safe'}])
    m = module()
    m._validate_dpkg_paths(rows,reference)
    assert m._resolve_image_path('/alias',{row['path']:row for row in rows}) == '/etc/safe'


@pytest.mark.parametrize('extra',[False,True])
def test_dpkg_derived_path_byte_budget_exact_and_plus_one(extra):
    rows = [{'path':'/a/'+ 'f'*1000,'kind':'file'}]
    rows.extend({'path':'/'+name+'/'+name*length,'kind':'symlink','target':'/'+target}
        for name,target,length in (('b','a',1000),('c','b',1000),('d','c',1000),('e','d',89+int(extra))))
    m = module()
    if extra:
        with pytest.raises(m.InstallationError): m._dpkg_alias_paths(rows)
    else: assert max(len(path.encode()) for path in m._dpkg_alias_paths(rows)) == 4096


def _status_paragraph(name='synthetic'):
    return ('Package: '+name+'\nStatus: install ok installed\nVersion: 1.0\nArchitecture: amd64\n').encode()


@pytest.mark.parametrize('boundary',['bytes','line','paragraph_lines','paragraphs','physical_lines','fields'])
def test_dpkg_parser_at_each_bound_and_plus_one(boundary):
    m = module()
    if boundary == 'line':
        valid = _status_paragraph()+b'Description: '+b'x'*4083+b'\n'
        invalid = _status_paragraph()+b'Description: '+b'x'*4084+b'\n'
    elif boundary == 'paragraph_lines':
        valid = _status_paragraph()+b'Description: \n'+b' x\n'*4091
        invalid = valid+b' x\n'
    elif boundary == 'paragraphs':
        valid = b'\n'.join(_status_paragraph('p'+str(index)) for index in range(8192))
        invalid = valid+b'\n'+_status_paragraph('p8192')
    elif boundary == 'physical_lines':
        valid = b'\n'.join(_status_paragraph('p'+str(index))+b'Description: \n'+b' x\n'*4090 for index in range(16))+b'\n'
        assert valid.count(b'\n') == 65536
        invalid = valid+b'\n'
    elif boundary == 'fields':
        optional = ['Source','Multi-Arch','Essential','Protected','Priority','Section','Installed-Size','Maintainer',
            'Original-Maintainer','Homepage','Description','Depends','Pre-Depends','Provides','Recommends',
            'Suggests','Enhances','Breaks','Conflicts','Replaces','Conffiles','Built-Using']
        valid = _status_paragraph()+''.join(name+': '+('same' if name == 'Multi-Arch' else 'synthetic')+'\n' for name in optional).encode()
        invalid = valid+b'Unknown: extra\n'
    else:
        prefix = _status_paragraph()+b'Description: \n'
        count,remainder = divmod(1048576-len(prefix),4097)
        valid = prefix+(b' '+b'x'*4095+b'\n')*count+b' '+b'x'*(remainder-2)+b'\n'
        assert len(valid) == 1048576
        invalid = valid[:-1]+b'x\n'
    assert m.parse_dpkg_status(valid,'linux/amd64').content_bytes == valid
    with pytest.raises(m.InstallationError): m.parse_dpkg_status(invalid,'linux/amd64')


@pytest.mark.parametrize('full_release_case',['linux/amd64','linux/arm64'],indirect=True)
def test_complete_retained_release_evaluation_uses_actual_stage_and_immutable_raw_graph(full_release_case):
    m = module()
    from app.domain.store import _writer
    case = full_release_case
    packet,sources = case.release.packet(case)
    assert hasattr(m,'evaluate_release'), 'Connected actual release evaluator is missing'
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    assessment = m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)
    assert assessment.review_sha256 == packet.header.as_dict()['objects'][0]['sha256']
    assert tuple(raw for _,raw in assessment.evidence) == packet.objects
    assert assessment.source_files == sources
    # Current allow admits the unchanged historical review; no new scan or re-signing.
    tomorrow = m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700086400000)
    assert tomorrow.evidence == assessment.evidence
    medium_packet,medium_sources = case.release.packet(case,medium=True)
    medium = m.evaluate_release(medium_packet,source_files=medium_sources,stage=stage,now_ms=1700000000000)
    assert medium.evidence[4][1] == medium_packet.objects[4]
    assert b'"baseScore":5.4' in medium.evidence[4][1]
    assert m.parse_external_document('image_scan',medium.evidence[4][1]).as_dict()['matches'][0]['vulnerability']['risk'] == Decimal('1.2')
    def diagnostic(value):
        value['matches'][0]['matchDetails'][0]['found'] = {'different':'SYNTHETIC TEST ONLY diagnostic','score':0.123}
    changed_packet,changed_sources = case.release.packet(case,medium=True,edit=_edit_release_document('image_scan',diagnostic))
    changed = m.evaluate_release(changed_packet,source_files=changed_sources,stage=stage,now_ms=1700000000000)
    assert changed.evidence[4][1] == changed_packet.objects[4] != medium.evidence[4][1]
    def run_assertion(value):
        value['predicate']['runDetails']['metadata'].update(startedOn='2023-11-14T22:12:00Z',finishedOn='2023-11-14T22:12:59Z')
    changed_packet,changed_sources = case.release.packet(case,edit=_edit_release_document('provenance',run_assertion))
    assert m.evaluate_release(changed_packet,source_files=changed_sources,stage=stage,now_ms=1700000000000).evidence[1][1] == changed_packet.objects[1]


def test_complete_r1_reports_join_actual_stage_before_inventory_assessment(full_release_case):
    m = module()
    from app.domain.store import _writer
    case = full_release_case
    packet,sources = case.release.packet(case)
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    review = m._authenticate_review(packet,sources,stage,1700000000000)
    source,dependency,filesystem,toolset = m._validate_r1(m._EvidenceGraph(packet),review,stage)
    assert source == case.release.source
    assert dependency == case.release.dependency
    assert filesystem == case.release.filesystems[case.actual.tree.platform]
    assert toolset == case.release.toolset


def test_retained_validator_is_read_only_and_never_calls_fresh_admission(full_release_case,monkeypatch):
    from app.domain.store import _writer
    m,case = module(),full_release_case
    packet,sources = case.release.packet(case)
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    assert hasattr(m,'validate_retained_release'), 'Distinct retained-history validator is missing'
    def forbidden(*args,**kwargs): raise AssertionError('History invoked fresh admission')
    monkeypatch.setattr(m,'evaluate_release',forbidden)
    assert m.validate_retained_release(packet,source_files=sources,stage=stage,verified_ms=1700000000000) is None


@pytest.mark.parametrize('medium',[False,True])
def test_native_location_annotations_obey_external_not_canonical_string_budget(full_release_case,medium):
    import json
    from app.domain.store import _writer
    m,case = module(),full_release_case
    def edit(role,raw):
        if role not in ('image_sbom','image_scan'): return raw
        value = json.loads(raw)
        artifacts = value['artifacts'] if role == 'image_sbom' else [row['artifact'] for row in value['matches']]
        for artifact in artifacts:
            if artifact['id'] == 'python-idna':
                artifact['locations'][0]['annotations'] = {'synthetic-note':'x'*65537}
        return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
    packet,sources = case.release.packet(case,medium=medium,edit=edit)
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    assessment = m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)
    assert assessment.evidence[2][1] == packet.objects[2]
    assert assessment.evidence[4][1] == packet.objects[4]
    if medium:
        def unequal(role,raw):
            raw = edit(role,raw)
            if role != 'image_scan': return raw
            value = json.loads(raw)
            value['matches'][0]['artifact']['locations'][0]['annotations']['synthetic-note'] += 'y'
            return json.dumps(value,separators=(',',':')).encode()
        bad,bad_sources = case.release.packet(case,medium=True,edit=unequal)
        m._authenticate_review(bad,bad_sources,stage,1700000000000)
        with pytest.raises(m.InstallationError): m.evaluate_release(bad,source_files=bad_sources,stage=stage,now_ms=1700000000000)
        def duplicate(role,raw):
            raw = edit(role,raw)
            if role != 'image_scan': return raw
            value = json.loads(raw)
            locations = value['matches'][0]['artifact']['locations']
            locations.append(locations[0])
            return json.dumps(value,separators=(',',':')).encode()
        bad,bad_sources = case.release.packet(case,medium=True,edit=duplicate)
        m._authenticate_review(bad,bad_sources,stage,1700000000000)
        with pytest.raises(m.InstallationError): m.evaluate_release(bad,source_files=bad_sources,stage=stage,now_ms=1700000000000)


def _edit_release_document(target,change):
    import json
    from app.domain.refs import canonical_json
    def edit(role,raw):
        try: value = json.loads(raw)
        except (ValueError,UnicodeError): return raw
        selected = (role == target or type(value) is dict and value.get('schema_version') == target
            or target == 'toolset' and type(value) is list and value and 'path' in value[0])
        if not selected: return raw
        change(value)
        if role in ('image_sbom','component_license_review','image_scan','component_scan','provenance'):
            return json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()
        return canonical_json(value)
    return edit


def test_signed_re_pinned_semantic_mutations_cannot_acquire_assessment(full_release_case):
    from app.domain.store import _writer
    from app.domain.refs import canonical_json
    m,case = module(),full_release_case
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    def component(value,class_): return next(row for row in value['components'] if row['class'] == class_)
    def deb(value): return next(row for row in value['artifacts'] if row['type'] == 'deb')
    def match(value): return value['matches'][0]
    def predicate(value): return value['predicate']
    def metadata(value): return predicate(value)['runDetails']['metadata']
    def map_field(field,transform):
        return ('provider-component-map-v2',lambda value:transform(value[field]))
    mutations = [
        ('empty-native', 'image_sbom',lambda v:v.update(artifacts=[])),
        ('duplicate-native-id','image_sbom',lambda v:v['artifacts'].append(v['artifacts'][0])),
        ('epoch','image_sbom',lambda v:deb(v).update(version='2.3-4')),
        ('architecture','image_sbom',lambda v:deb(v)['metadata'].update(architecture='s390x')),
        ('missing-status-location','image_sbom',lambda v:deb(v).update(locations=[])),
        ('wrong-status-layer','image_sbom',lambda v:deb(v)['locations'][0].update(layerID=v['source']['metadata']['layers'][-1]['digest'])),
        ('source-upstream','image_sbom',lambda v:deb(v)['metadata'].update(source='wrong-source')),
        ('unknown-binary','image_sbom',lambda v:next(r for r in v['artifacts'] if r['type']=='binary')['metadata']['matches'][0].update(classifier='bash-binary')),
        ('file-hash','image_sbom',lambda v:v['files'][0]['digests'][0].update(value='f'*64)),
        ('file-size','image_sbom',lambda v:v['files'][0]['metadata'].update(size=9999)),
        ('file-layer','image_sbom',lambda v:v['files'][0]['location'].update(layerID='sha256:'+'f'*64)),
        ('extra-cataloger','image_sbom',lambda v:v['descriptor']['configuration']['catalogers']['used'].append('extra-cataloger')),
        ('projection-prefix',*map_field('component_projection',lambda rows:rows[0].update(grype_id=rows[0]['input_id']))),
        ('missing-projection',*map_field('image_projection',lambda rows:rows.pop())),
        ('missing-package',*map_field('components',lambda rows:rows.pop())),
        ('unowned-file',*map_field('file_links',lambda rows:rows[0].update(components=[]))),
        ('missing-status-ref','provider-component-map-v2',lambda v:v.pop('dpkg_status')),
        ('component-claims-status','provider-component-map-v2',lambda v:component(v,'debian')['files'].append('/var/lib/dpkg/status')),
        ('first-party-relabel','provider-component-map-v2',lambda v:component(v,'python-wheel').update(**{'class':'first-party'})),
        ('rust-supplier-missing','provider-component-map-v2',lambda v:component(v,'rust-crate')['inputs'].pop()),
        ('wheel-hash','provider-component-map-v2',lambda v:component(v,'python-wheel')['inputs'][0]['identity'].update(sha256='f'*64)),
        ('missing-license-text','provider-component-map-v2',lambda v:component(v,'python-wheel')['license'].update(texts=[])),
        ('missing-obligation','provider-component-map-v2',lambda v:component(v,'python-wheel')['license']['obligations'].pop()),
        ('inverse-parent-cycle','provider-component-map-v2',lambda v:component(v,'first-party')['parent_spdx_ids'].append(component(v,'first-party')['spdx_id'])),
        ('second-root','component_license_review',lambda v:v['packages'][1].update(primaryPackagePurpose='CONTAINER')),
        ('multiple-purls','component_license_review',lambda v:v['packages'][1]['externalRefs'].append(v['packages'][1]['externalRefs'][0])),
        ('NOASSERTION','component_license_review',lambda v:v['packages'][1].update(licenseConcluded='NOASSERTION')),
        ('unresolved-license','component_license_review',lambda v:v.update(hasExtractedLicensingInfos=[])),
        ('illegal-choice','component_license_review',lambda v:v['packages'][1].update(licenseConcluded='Apache-2.0')),
        ('forbidden-edge','component_license_review',lambda v:v['relationships'][0].update(relationshipType='GENERATED_FROM')),
        ('forbidden-purpose','component_license_review',lambda v:v['packages'][1].update(primaryPackagePurpose='FILE')),
        ('file-checksum','component_license_review',lambda v:v['files'][0]['checksums'][0].update(checksumValue='f'*64)),
        ('high','image_scan',lambda v:match(v)['vulnerability'].update(severity='High')),
        ('critical','image_scan',lambda v:match(v)['vulnerability'].update(severity='Critical')),
        ('unknown-severity','image_scan',lambda v:match(v)['vulnerability'].update(severity='Unknown')),
        ('missing-severity','image_scan',lambda v:match(v)['vulnerability'].pop('severity')),
        ('ignored','image_scan',lambda v:v.update(ignoredMatches=[{}])),
        ('alerts','image_scan',lambda v:v.update(alertsByPackage=[{}])),
        ('filtering','image_scan',lambda v:v['descriptor']['configuration'].update(**{'only-fixed':True})),
        ('native-sort-key','image_scan',lambda v:v['descriptor']['configuration'].update(**{'sort-by':'risk'})),
        ('native-duration','image_scan',lambda v:v['descriptor']['configuration']['db'].update(**{'max-allowed-built-age':'120h'})),
        ('implicit-ignore','image_scan',lambda v:v['descriptor']['configuration'].update(**{'match-upstream-kernel-headers':False})),
        ('provider-empty','image_scan',lambda v:v['descriptor']['db'].update(providers={})),
        ('spdx-locations','component_scan',lambda v:match(v)['artifact'].update(locations=[])),
        ('run-exit','provider-scanner-invocation-v1',lambda v:v['run'].update(exit_code=1)),
        ('run-diagnostic','provider-scanner-invocation-v1',lambda v:v['run'].update(diagnostics=[{'kind':'warning','message':'test'}])),
        ('run-stderr','provider-scanner-invocation-v1',lambda v:v['run'].update(stderr_utf8='warning')),
        ('run-input','provider-scanner-invocation-v1',lambda v:v['run']['inputs'][0]['identity'].update(sha256='f'*64)),
        ('db-stale','provider-scanner-cohort-v1',lambda v:v['db'].update(built_at_ms=1)),
        ('provenance-subject','provenance',lambda v:v['subject'][0]['digest'].update(sha256='f'*64)),
        ('omitted-input','provenance',lambda v:predicate(v)['buildDefinition']['resolvedDependencies'].pop()),
        ('extra-input','provenance',lambda v:predicate(v)['buildDefinition']['resolvedDependencies'].append({'uri':'urn:extra','digest':{'sha256':'f'*64}})),
        ('build-type','provenance',lambda v:predicate(v)['buildDefinition'].update(buildType='urn:unsupported')),
        ('observer','provenance',lambda v:predicate(v)['runDetails']['builder']['version'].update(observer='f'*64)),
        ('byproduct','provenance',lambda v:predicate(v)['runDetails']['byproducts'][0]['digest'].update(sha256='f'*64)),
        ('byproduct-order','provenance',lambda v:predicate(v)['runDetails']['byproducts'].reverse()),
        ('nil-run','provenance',lambda v:metadata(v).update(invocationId='00000000-0000-0000-0000-000000000000')),
        ('fractional-run','provenance',lambda v:metadata(v).update(startedOn='2023-11-14T22:13:00.000Z')),
        ('offset-run','provenance',lambda v:metadata(v).update(startedOn='2023-11-14T22:13:00+00:00')),
        ('run-order','provenance',lambda v:metadata(v).update(startedOn='2023-11-14T22:13:11Z')),
        ('run-after-scan','provenance',lambda v:metadata(v).update(finishedOn='2023-11-14T22:13:20Z')),
        ('wrong-toolset','provider-source-closure-v1',lambda v:v['toolset'].update(sha256='f'*64)),
        ('missing-inspect','toolset',lambda v:v.remove(next(r for r in v if r['path'].endswith('/inspect.py')))),
        ('duplicate-inspect','toolset',lambda v:v.append(next(r for r in v if r['path'].endswith('/inspect.py')))),
        ('invented-r1-clock','provider-source-closure-v1',lambda v:v.update(started_at_ms=1)),
        ('old-topology','provider-source-closure-v1',lambda v:v['files'][0].update(source_path='app/old.py')),
        ('incompatible-parser','provider-scanner-cohort-v1',lambda v:v['syft'].update(version_output=v['syft']['config_input'])),
        ('missing-support','provider-scanner-cohort-v1',lambda v:v.update(adapter_source={'sha256':'f'*64,'size_bytes':1})),
    ]
    for label,target,change in mutations:
        packet,sources = case.release.packet(case,medium=True,edit=_edit_release_document(target,change))
        # Signature/current allow must pass, so a cryptographic mismatch cannot mask the semantic check.
        m._authenticate_review(packet,sources,stage,1700000000000)
        with pytest.raises(m.InstallationError,match='invalid_input'):
            m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)
    packet,sources = case.release.packet(case,extra_objects=(('origin_evidence',b'SYNTHETIC TEST ONLY unused object'),))
    m._authenticate_review(packet,sources,stage,1700000000000)
    with pytest.raises(m.InstallationError):
        m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)
    for field in ('manifest','config','layers'):
        base = case.release.inputs[case.actual.tree.platform]['base']['entry']
        alternate = base[field][0] if field == 'layers' else base[field]
        def change(value):
            for row in value['components']:
                for input_ in row['inputs']:
                    if input_['kind'] == 'base': input_['identity'] = {'sha256':alternate['digest'][7:],'size_bytes':alternate['size_bytes']}
        packet,sources = case.release.packet(case,edit=_edit_release_document('provider-component-map-v2',change))
        m._authenticate_review(packet,sources,stage,1700000000000)
        with pytest.raises(m.InstallationError):
            m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)


@pytest.mark.parametrize('release_evaluation_case',['valid',*[f'P{i}' for i in range(1,11)],'foreign_policy','wrong_toolset'],indirect=True)
def test_pb_actual_stage_evaluation_uses_current_policy_and_historical_issuance(release_evaluation_case):
    m,case = module(),release_evaluation_case
    if case.variant == 'P5':
        from app.deployment.installation_release_contracts import parse_release_trust
        with pytest.raises(ValueError): parse_release_trust(case.malformed_trust_bytes)
        assert case.source_files is None
    elif case.variant in ('valid','P8','P10'):
        assessment = m.evaluate_release(case.packet,source_files=case.source_files,stage=case.stage,now_ms=case.now_ms)
        assert assessment.evidence[4][1] == case.packet.objects[4]
    else:
        with pytest.raises(m.InstallationError):
            m.evaluate_release(case.packet,source_files=case.source_files,stage=case.stage,now_ms=case.now_ms)


@pytest.mark.parametrize('full_release_case',[{'platform':'linux/amd64','status':value} for value in (
    'not-installed','unknown-field','duplicate-record','extra-record','missing-record')],
    ids=['not-installed','unknown-field','duplicate-record','extra-record','missing-record'],indirect=True)
def test_status_refusal_after_actual_stage_has_matching_raw_status_hash(full_release_case):
    from app.domain.store import _writer
    m,case = module(),full_release_case
    packet,sources = case.release.packet(case)
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    review = m._authenticate_review(packet,sources,stage,1700000000000)
    graph = m._EvidenceGraph(packet)
    _,_,filesystem,_ = m._validate_r1(graph,review,stage)
    mapping = graph.project(review['component_map'],'origin_evidence','provider-component-map-v2')
    m._validate_dpkg_paths(filesystem['filesystem'],mapping['dpkg_status'])
    with pytest.raises(m.InstallationError):
        m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)


@pytest.mark.parametrize('full_release_case',[{'platform':'linux/amd64','status':value}
    for value in ('intermediate-alias','long-status-alias')],indirect=True)
def test_intermediate_link_alias_refuses_coherent_real_staged_signed_packet(full_release_case):
    from app.domain.store import _writer
    m,case = module(),full_release_case
    packet,sources = case.release.packet(case)
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    review = m._authenticate_review(packet,sources,stage,1700000000000)
    graph = m._EvidenceGraph(packet)
    retained_fs = case.release.filesystems[case.actual.tree.platform]
    alias = next(row for row in retained_fs['filesystem'] if row['path'] == '/alias')
    if alias['target'] == '/x0/../status':
        from app.domain.refs import parse_canonical,canonical_json
        from hashlib import sha256
        lineage = parse_canonical(stage.lineage_bytes)
        selected = next(row for row in lineage['platforms'] if row['measured_platform_entry']['platform'] == case.actual.tree.platform)
        assert selected['extraction_evidence_sha256'] == sha256(canonical_json(retained_fs)).hexdigest()
        # Shared R1 target analysis reaches the same bounded resolution first.
        with pytest.raises(m.InstallationError) as error:
            m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)
        assert error.value.code == 'too_large'
        return
    _,_,filesystem,_ = m._validate_r1(graph,review,stage)
    assert next(row for row in filesystem['filesystem'] if row['path'] == '/alias')['target'] in ('/x/../status','/x0/../status')
    with pytest.raises(m.InstallationError):
        m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)


@pytest.mark.parametrize('full_release_case',[{'platform':'linux/amd64','status':value}
    for value in ('protected-alias','protected-ancestor')],indirect=True)
def test_r1_protected_alias_uses_resolved_target_not_only_immediate_spelling(full_release_case):
    from app.domain.store import _writer
    m,case = module(),full_release_case
    packet,sources = case.release.packet(case)
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    review = m._authenticate_review(packet,sources,stage,1700000000000)
    with pytest.raises(m.InstallationError): m._validate_r1(m._EvidenceGraph(packet),review,stage)


def test_dpkg_resolution_overflow_cannot_drop_parent_component_source_alias():
    rows,reference = _status_tree()
    rows.append({'path':'/var/lib/dpkg/subdir','kind':'directory'})
    rows.extend({'path':'/x'+str(i),'kind':'symlink','target':'/x'+str(i+1) if i < 40 else '/var/lib/dpkg/subdir'} for i in range(41))
    rows.append({'path':'/alias','kind':'symlink','target':'/x0/../status'})
    m = module()
    with pytest.raises(m.InstallationError): m._validate_dpkg_paths(rows,reference)


def test_unrelated_closed_symlink_cycle_does_not_invent_status_reachability():
    rows,reference = _status_tree()
    rows.extend([{'path':'/a','kind':'symlink','target':'/b'},
        {'path':'/b','kind':'symlink','target':'/a'}])
    module()._validate_dpkg_paths(rows,reference)


def test_native_package_and_file_identifier_namespaces_cannot_alias(full_release_case):
    import json
    from app.domain.refs import canonical_json
    from app.domain.store import _writer
    m,case = module(),full_release_case
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    def edit(role,raw):
        if role not in ('image_sbom','origin_evidence'): return raw
        try: value = json.loads(raw)
        except ValueError: return raw
        if role == 'origin_evidence' and (type(value) is not dict or value.get('schema_version') != 'provider-component-map-v2'): return raw
        def translate(item):
            if type(item) is str: return 'file-0' if item == 'cpython' else item
            if type(item) is list: return [translate(child) for child in item]
            if type(item) is dict: return {key:translate(child) for key,child in item.items()}
            return item
        value = translate(value)
        if role == 'origin_evidence':
            # Class is not an ID and stays CPython; every decision projection is otherwise consistent.
            next(row for row in value['components'] if row['spdx_id']=='SPDXRef-cpython')['class'] = 'cpython'
            next(row for row in value['component_projection'] if row['input_id']=='SPDXRef-cpython')['grype_id'] = 'cpython'
            value['image_projection'].sort(key=lambda row:row['input_id'])
        return canonical_json(value)
    packet,sources = case.release.packet(case,edit=edit)
    m._authenticate_review(packet,sources,stage,1700000000000)
    with pytest.raises(m.InstallationError):
        m.evaluate_release(packet,source_files=sources,stage=stage,now_ms=1700000000000)


@pytest.mark.parametrize('boundary',['depth','members','bytes'])
def test_raw_parser_exact_budget_and_one_more(boundary):
    m = module()
    if boundary == 'depth':
        valid = b'{"x":'+b'['*63+b'0'+b']'*63+b'}'
        invalid = b'{"x":'+b'['*64+b'0'+b']'*64+b'}'
    elif boundary == 'members':
        valid = b'{"x":['+b'0,'*262142+b'0]}'
        invalid = b'{"x":['+b'0,'*262143+b'0]}'
    else:
        valid = b'{}'+b' '*(8388608-2)
        invalid = valid+b' '
    assert m.parse_external_document('image_scan',valid).content_bytes == valid
    with pytest.raises(m.InstallationError): m.parse_external_document('image_scan',invalid)


@pytest.mark.parametrize('boundary',['items','bytes'])
def test_project_map_uses_unchanged_canonical_budget_including_keys(boundary):
    import json
    from app.domain.refs import EntityRef,canonical_json
    from uuid import uuid4
    from hashlib import sha256
    from app.tests.provider_installation_fixture import packet_header
    from app.extensions.provider_installation_contracts import parse_installation_header,ReleasePacket
    m = module()
    value = {'schema_version':'provider-component-map-v2','left':[0]*5000,'right':[0]*4993}
    if boundary == 'bytes':
        value = {'schema_version':'provider-component-map-v2','pad':['x'*65000]*16+['']}
        value['pad'][-1] = 'x'*(1048576-len(canonical_json(value)))
    valid = canonical_json(value)
    if boundary == 'items': value['right'].append(0)
    else: value['pad'][-1] += 'x'
    invalid = json.dumps(value,sort_keys=True,separators=(',',':')).encode()
    def project(raw):
        header,objects = packet_header(EntityRef('extension_installation',str(uuid4()),1,'a'*64))
        header = json.loads(header)
        ref = {'sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)}
        header['objects'].append({'role':'origin_evidence',**ref})
        packet = ReleasePacket(parse_installation_header(canonical_json(header)),(*objects,raw))
        return m._EvidenceGraph(packet).project(ref,'origin_evidence','provider-component-map-v2')
    assert project(valid)['schema_version'] == 'provider-component-map-v2'
    with pytest.raises(ValueError): project(invalid)
