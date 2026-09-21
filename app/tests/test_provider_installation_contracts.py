import importlib
import json
from uuid import uuid4

import pytest
from app.domain.refs import EntityRef,canonical_json
from app.tests.provider_installation_fixture import packet_header,staged_installation


def module():
    try: return importlib.import_module('app.extensions.provider_installation_contracts')
    except ModuleNotFoundError: pytest.fail('Actual installation contracts are missing')


def stage_ref():
    return EntityRef('extension_installation',str(uuid4()),1,'a'*64)


def test_header_packet_checks_every_raw_identity():
    c = module()
    raw,objects = packet_header(stage_ref())
    header = c.parse_installation_header(raw)
    packet = c.ReleasePacket(header,objects)
    assert packet.header.content_bytes == raw
    assert packet.objects == objects
    with pytest.raises(c.InstallationError): c.ReleasePacket(header,(*objects[:-1],b'altered'))


@pytest.mark.parametrize('mutation',['bool','version','extra','duplicate','role_order','missing_invocation','oversize','zero'])
def test_header_closed_caps_and_roles(mutation):
    c = module()
    raw,_ = packet_header(stage_ref())
    value = json.loads(raw)
    if mutation == 'bool': value['objects'][0]['size_bytes'] = True
    if mutation == 'version': value['staged_installation_ref']['version'] = 2
    if mutation == 'extra': value['approved'] = True
    if mutation == 'duplicate': value['objects'][1]['sha256'] = value['objects'][0]['sha256']
    if mutation == 'role_order': value['objects'][0],value['objects'][1] = value['objects'][1],value['objects'][0]
    if mutation == 'missing_invocation': value['objects'].pop()
    if mutation == 'oversize': value['objects'][0]['size_bytes'] = 262145
    if mutation == 'zero': value['objects'][0]['size_bytes'] = 0
    with pytest.raises(c.InstallationError): c.parse_installation_header(canonical_json(value))


def test_actual_stage_delegate_requires_writer_and_preserves_stage(staged_installation):
    case = staged_installation
    from app.domain.store import _writer
    assert hasattr(case.prepare,'_installation_stage_view'), 'Actual writer-owned stage delegate is missing'
    with _writer(),case.domain._connection(write=True) as db:
        view = case.prepare._installation_stage_view(db,case.installation_ref)
        assert view.stage_ref == case.installation_ref
        assert view.provider_files == case.actual.tree.bundle
        assert view.current_head['installation_anchor_digest'] == case.installation_ref.sha256
        assert view.stage_record['content']['state'] == 'staged'


def test_readonly_empty_journal_preserves_legacy_inspection_and_authority(tmp_path):
    from types import SimpleNamespace
    from app.tests.test_extension_candidates_persistent import owner
    from app.tests.provider_installation_fixture import installation_snapshot
    with owner(tmp_path) as (app, _client, _request, _profile, _arguments):
        case = SimpleNamespace(domain=app.state.domain_store)
        prepare = app.state.first_party_exports['deployment-prepare.service']
        before = installation_snapshot(case)
        with case.domain._connection() as db:
            journal = prepare._journal(db)
            assert journal['requests'] == {} and journal['control'] is None
            assert journal['rows']['installation_verifications'] == []
        assert not prepare._unavailable
        assert installation_snapshot(case).authority == before.authority


def test_readonly_staged_journal_preserves_legacy_inspection_and_authority(staged_installation):
    from app.tests.provider_installation_fixture import installation_snapshot
    case = staged_installation
    before = installation_snapshot(case)
    with case.domain._connection() as db:
        journal = case.prepare._journal(db)
        items = [item for item in journal['requests'].values() if item.get('installation')]
        assert len(items) == 1
        assert items[0]['installation_current']['ref'] == case.installation_ref
        assert items[0]['installation_current']['head']['revision'] == 1
        assert items[0]['installation_current']['verification'] is None
        assert journal['rows']['installation_verifications'] == []
    assert not case.prepare._unavailable
    assert installation_snapshot(case).authority == before.authority


def test_stage_view_issuance_rejects_reader_and_foreign_store_writer(staged_installation):
    from app.domain.store import DomainStore, StorageError, _writer
    from app.extensions.provider_installation_records import stage_view
    from app.tests.provider_installation_fixture import installation_snapshot
    case = staged_installation
    foreign = DomainStore(case.domain._legacy_store)
    before = installation_snapshot(case)
    with _writer(), case.domain._connection(write=True) as db:
        journal = case.prepare._journal(db)
        item = next(item for item in journal['requests'].values() if item.get('installation'))
        assert stage_view(case.domain, db, item).stage_ref == case.installation_ref
    for writer_domain in (None, foreign):
        with _writer(), (case.domain._connection() if writer_domain is None
                         else writer_domain._connection(write=True)) as db:
            for issue in (lambda: stage_view(case.domain, db, item),
                          lambda: case.prepare._installation_stage_view(db, case.installation_ref)):
                with pytest.raises(StorageError, match='Exact active DomainStore writer required'):
                    issue()
    assert installation_snapshot(case).authority == before.authority


def test_verified_record_is_distinct_exact_domain_branch():
    from app.domain.schemas import ImmutableRecord
    from app.domain.refs import DomainContractError
    c = module()
    staged = stage_ref()
    refs = {kind:EntityRef(kind,str(uuid4()),1,letter*64)
            for kind,letter in (('actor','b'),('access_policy','c'),('retention_policy','d'))}
    from app.domain.store import BlobRef
    vault_id = str(uuid4())
    blob = BlobRef(vault_id,'operational','e'*64,1)
    raw,_ = packet_header(staged)
    roles = json.loads(raw)['objects']
    content = {'schema_version':'provider-installation-verified-v1','state':'verified','revision':2,
        'stage_ref':staged.as_dict(),'previous_record_digest':staged.sha256,'extension_id':'synthetic-provider',
        'extension_version':'1.0.0','platform':'linux/amd64','image_index_sha256':'1'*64,
        'selected_manifest_sha256':'2'*64,'service_descriptor_sha256':'3'*64,'command_id':str(uuid4()),
        'verified_at_ms':1700000000000,'release_context_blob_ref':blob.as_dict(),
        'release_trust_blob_ref':blob.as_dict(),'release_source_context_sha256':blob.sha256,
        'release_review_sha256':roles[0]['sha256'],'evidence_policy_sha256':'6'*64,
        'evidence':[{'role':obj['role'],'blob_ref':BlobRef(vault_id,'operational',obj['sha256'],obj['size_bytes']).as_dict()} for obj in roles]}
    record = ImmutableRecord.create(kind='extension_installation',id=staged.id,version=2,
        created_at_utc='2023-11-14T22:13:20.000000Z',actor_ref=refs['actor'],parent_refs=[staged],
        purpose='operational',access_policy_ref=refs['access_policy'],retention_policy_ref=refs['retention_policy'],content=content)
    assert record.body['content'] == content
    from jsonschema import Draft202012Validator
    from app.domain.schema_exports import domain_schema
    from app.extensions import provider_installation_schema_exports as exports
    assert hasattr(exports,'record_schema'), 'Exact verified record schema export is missing'
    assert Draft202012Validator(exports.record_schema()).is_valid({'ref':record.ref.as_dict(),'body':record.body})
    assert Draft202012Validator(domain_schema()).is_valid({'ref':record.ref.as_dict(),'body':record.body})
    broken = record.body
    broken['version'] = 3
    with pytest.raises(DomainContractError): ImmutableRecord.from_bytes(canonical_json(broken))
    for key in ('release_source_context_sha256','release_review_sha256'):
        broken = record.body
        broken['content'][key] = 'f'*64
        with pytest.raises(DomainContractError): ImmutableRecord.from_bytes(canonical_json(broken))


def test_four_owned_installation_schema_exports_match_retained_json():
    from pathlib import Path
    from app.extensions import provider_installation_schema_exports as exports
    assert hasattr(exports,'exported_schemas'), 'Owned installation schemas are not exported'
    schemas = exports.exported_schemas()
    assert set(schemas) == {'provider-installation-input-v1.schema.json','provider-installation-reply-v1.schema.json',
        'provider-installation-record-v2.schema.json','provider-release-review-v1.schema.json'}
    root = Path(__file__).resolve().parents[2]/'schemas/v2/extensions'
    for name,value in schemas.items(): assert json.loads((root/name).read_bytes()) == value


@pytest.mark.parametrize('mutation',[None,'extra','subject_extra','nul','unicode_id','bad_signature','bool','severity','version'])
def test_review_envelope_closed_structural_codec(mutation):
    from app.tests.provider_installation_fixture import review_envelope
    c = module()
    assert hasattr(c,'parse_review_envelope'), 'Closed review envelope codec is missing'
    value = review_envelope()
    if mutation == 'extra': value['approved'] = True
    if mutation == 'subject_extra': value['payload']['subject']['passed'] = True
    if mutation == 'nul': value['payload']['reviewer']['name'] = 'bad\0name'
    if mutation == 'unicode_id': value['payload']['reviewer']['id'] = '한글'
    if mutation == 'bad_signature': value['signature'] = 'A'*85+'B'
    if mutation == 'bool': value['payload']['issued_at_ms'] = True
    if mutation == 'version': value['payload']['subject']['extension_version'] = '01.0.0'
    if mutation == 'severity': value['payload']['finding_review']['accepted'] = [{'scan':'image','match_index':0,
        'vulnerability_id':'synthetic','artifact_id':'synthetic','severity':'High'}]
    raw = canonical_json(value)
    if mutation is None:
        parsed = c.parse_review_envelope(raw)
        assert parsed.content_bytes == raw
        detached = parsed.as_dict()
        detached['payload']['scope'] = 'arbitrary'
        assert parsed.as_dict() == value
    else:
        with pytest.raises(c.InstallationError): c.parse_review_envelope(raw)


@pytest.mark.parametrize('role',('release_review','provenance','image_sbom','component_license_review','image_scan',
    'component_scan','source_report','dependency_report','filesystem_report','cohort_manifest','invocation','license_text','origin_evidence'))
def test_each_header_individual_byte_cap_and_plus_one(role):
    c = module()
    raw,_ = packet_header(stage_ref())
    value = json.loads(raw)
    if role in ('license_text','origin_evidence'):
        value['objects'].append({'role':role,'sha256':'f'*64,'size_bytes':1})
    row = next(row for row in value['objects'] if row['role'] == role)
    row['size_bytes'] = c.CAPS[role]
    value['objects'][10:] = sorted(value['objects'][10:],key=lambda item:(item['role'],item['sha256']))
    c.parse_installation_header(canonical_json(value))
    row['size_bytes'] += 1
    with pytest.raises(c.InstallationError): c.parse_installation_header(canonical_json(value))


def test_header_exact_128_object_count_and_plus_one():
    c = module()
    raw,_ = packet_header(stage_ref()); value = json.loads(raw)
    value['objects'].extend({'role':'origin_evidence','sha256':format(index,'064x'),'size_bytes':1} for index in range(116))
    value['objects'][10:] = sorted(value['objects'][10:],key=lambda item:(item['role'],item['sha256']))
    assert len(c.parse_installation_header(canonical_json(value)).as_dict()['objects']) == 128
    value['objects'].append({'role':'origin_evidence','sha256':'f'*64,'size_bytes':1})
    with pytest.raises(c.InstallationError): c.parse_installation_header(canonical_json(value))
