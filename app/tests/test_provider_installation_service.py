"""Actual same-store installation authority and immutable replay."""
from app.domain.store import _writer
from app.deployment import prepare_storage as storage
from app.tests.provider_installation_fixture import full_release_case
from app.tests.provider_installation_fixture import installation_case
import pytest
import importlib


def test_ordinary_constructor_installs_v6_and_composes_historical_and_current_stage(full_release_case):
    case = full_release_case
    with _writer(),case.domain._connection(write=True) as db:
        assert storage._layout(db) is storage._V6
        journal = case.prepare._journal(db)
        item = next(item for item in journal['requests'].values() if item.get('installation'))
        assert item['installation']['ref'] == case.installation_ref
        assert item['installation_current']['ref'] == case.installation_ref
        assert item['installation']['head'] == item['installation_current']['head']
        assert item['installation']['head']['revision'] == 1
        assert journal['rows']['installation_verifications'] == []


def test_verified_history_requires_exact_store_writer_without_authority_change(installation_case):
    from app.domain.store import DomainStore, StorageError
    from app.deployment import prepare_records
    case = installation_case
    reply = case.verification_service.execute(case.actual.request, case.packet)
    foreign = DomainStore(case.domain._legacy_store)
    before = case.snapshot()
    for writer_domain in (None, foreign):
        with _writer(), (case.domain._connection() if writer_domain is None
                         else writer_domain._connection(write=True)) as db:
            with pytest.raises(StorageError, match='Exact active DomainStore writer required'):
                prepare_records.verify(case.domain, db, case.profile)
    with _writer(), case.domain._connection(write=True) as db:
        journal = prepare_records.verify(case.domain, db, case.profile)
        item = next(item for item in journal['requests'].values() if item.get('installation'))
        assert item['installation_current']['ref'].as_dict() == reply['verified_installation_ref']
        assert item['installation_current']['reply'] == reply
    assert case.snapshot().authority == before.authority


@pytest.mark.parametrize('full_release_case',[{'platform':'linux/amd64','release_source':True}],indirect=True)
def test_real_service_commits_one_verified_successor_and_source_less_exact_replay(full_release_case,monkeypatch):
    case = full_release_case
    try: module = importlib.import_module('app.extensions.provider_installation_service')
    except ModuleNotFoundError: pytest.fail('Actual installation service is missing')
    with _writer(),case.domain._connection(write=True) as db:
        verified_ms = case.prepare._journal(db)['control']['clock_floor_ms']+1
    monkeypatch.setattr(module.time,'time_ns',lambda:verified_ms*1000000)
    service = module.PersistentProviderInstallation(case.domain,case.actual.owner,prepare_service=case.prepare,
        release_source=case.actual.app.state.first_party_exports['installation-release.source-context'])
    reply = service.execute(case.actual.request,case.packet)
    assert reply['state'] == 'verified' and reply['revision'] == 2
    assert reply['verified_installation_ref']['id'] == case.installation_ref.id
    with _writer(),case.domain._connection(write=True) as db:
        journal = case.prepare._journal(db)
        item = next(item for item in journal['requests'].values() if item.get('installation'))
        assert item['installation']['ref'] == case.installation_ref
        assert item['installation']['head']['revision'] == 1
        assert item['installation_current']['ref'].as_dict() == reply['verified_installation_ref']
        assert item['installation_current']['head']['revision'] == 2
        assert len(journal['rows']['installation_verifications']) == 1
    reopened = module.PersistentProviderInstallation(case.domain,case.actual.owner,
        prepare_service=case.prepare,release_source=None)
    def forbidden(*args,**kwargs): raise AssertionError('Replay sampled fresh release admission')
    monkeypatch.setattr(module.PersistentProviderInstallation,'_now',staticmethod(forbidden))
    monkeypatch.setattr(module,'evaluate_release',forbidden)
    assert reopened.execute(case.actual.request,case.packet) == reply
    assert reopened.read(case.actual.read_request,case.packet.header.command_id) == reply


@pytest.mark.parametrize('installation_case',['P1','P2','P3','P4','P5','P6','P7','P8','P9','P10',
    'foreign_policy','wrong_toolset','high_finding'],indirect=True)
def test_PC_independently_provisioned_policy_and_signed_evidence_authority(installation_case):
    case = installation_case
    before = case.snapshot()
    response = case.post_packet(case.packet)
    after = case.snapshot()
    assert after.old_record_bytes == before.old_record_bytes
    if case.variant in ('P8','P10'):
        assert response.status_code == 200,response.text
        assert len(after.verified_refs) == 1 and after.verified_event_count == 1
    else:
        assert response.status_code in (400,409,503),response.text
        assert after.authority == before.authority
        assert not after.verified_refs and after.verified_event_count == 0


@pytest.mark.parametrize('field',['previous_head_hash','input_digest','verified_ms','reply_json','actor_ref'])
def test_composed_history_refuses_rehashed_private_row_corruption(installation_case,field):
    from app.domain.refs import canonical_json
    from app.extensions.provider_installation_contracts import InstallationError
    case = installation_case
    reply = case.verification_service.execute(case.actual.request,case.packet)
    with _writer(),case.domain._connection(write=True) as db:
        row = dict(db.execute('SELECT * FROM deployment_prepare_installation_verifications').fetchone())
        if field in ('previous_head_hash','input_digest'): row[field] = 'f'*64
        elif field == 'verified_ms': row[field] += 1
        elif field == 'reply_json':
            from copy import deepcopy
            changed = deepcopy(reply); changed['release_review_sha256'] = 'f'*64
            row[field] = canonical_json(changed).decode()
        else: row[field] = canonical_json(case.domain._read_roots(db).actor.as_dict()).decode()
        row['hash'] = storage.digest('installation_verifications',row)
        db.execute('UPDATE deployment_prepare_installation_verifications SET '+field+'=?,hash=?',(row[field],row['hash']))
        storage.verify(db)  # local scalar/schema/rowhash is coherent, composed joins are not
    before = case.snapshot()
    with pytest.raises(InstallationError): case.verification_service.read(case.actual.read_request,case.packet.header.command_id)
    assert case.snapshot().authority == before.authority


def test_second_command_and_changed_same_command_conflict_without_authority_change(installation_case):
    from uuid import uuid4
    from app.domain.refs import canonical_json
    from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header,InstallationError
    case = installation_case
    case.verification_service.execute(case.actual.request,case.packet)
    before = case.snapshot()
    changed = case.packet.header.as_dict(); changed['command_id'] = str(uuid4())
    other = ReleasePacket(parse_installation_header(canonical_json(changed)),case.packet.objects)
    with pytest.raises(InstallationError) as error: case.verification_service.execute(case.actual.request,other)
    assert error.value.code == 'conflict'
    assert case.snapshot().authority == before.authority


def test_actual_source_less_app_restart_replays_without_fresh_admission(installation_case,monkeypatch):
    from app.extensions import provider_installation_service as service
    case = installation_case
    response = case.post_packet(case.packet)
    assert response.status_code == 200
    before = case.snapshot()
    def forbidden(*args,**kwargs): raise AssertionError('Historical load attempted fresh release admission')
    monkeypatch.setattr(service,'evaluate_release',forbidden)
    monkeypatch.setattr(service.PersistentProviderInstallation,'_now',staticmethod(forbidden))
    with case.restart_without_release_source() as reopened:
        assert reopened.domain is not case.domain
        restarted = reopened.snapshot()
        assert restarted.old_record_bytes == before.old_record_bytes
        old_rows,new_rows = dict(before.authority),dict(restarted.authority)
        prior,current = (dict(zip(storage.COLUMNS_V6['control'],rows.pop('deployment_prepare_control')[0],strict=True))
            for rows in (old_rows,new_rows))
        assert old_rows == new_rows
        assert current['clock_floor_ms'] >= prior['clock_floor_ms']
        assert current['revision'] == prior['revision']+int(current['clock_floor_ms'] > prior['clock_floor_ms'])
        assert current['hash'] == storage.digest('control',current)
        assert {key:value for key,value in current.items() if key not in ('clock_floor_ms','revision','hash')} == {
            key:value for key,value in prior.items() if key not in ('clock_floor_ms','revision','hash')}
        assert reopened.post_packet(case.packet).content == response.content
        assert reopened.client.get(case.path+'/'+case.packet.header.command_id).content == response.content
        assert reopened.snapshot().authority == restarted.authority


@pytest.mark.parametrize('mutation',['input','actor'])
def test_same_command_changed_input_or_authenticated_actor_refuses_exact_replay(installation_case,monkeypatch,mutation):
    from hashlib import sha256
    from app.domain.refs import canonical_json
    from app.extensions import provider_installation_service as module
    from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header,InstallationError
    case = installation_case
    reply = case.verification_service.execute(case.actual.request,case.packet)
    packet = case.packet
    if mutation == 'input':
        objects = (*packet.objects[:-1],packet.objects[-1]+b' ')
        value = packet.header.as_dict()
        value['objects'][-1].update(sha256=sha256(objects[-1]).hexdigest(),size_bytes=len(objects[-1]))
        tail = sorted(zip(value['objects'][10:],objects[10:],strict=True),key=lambda pair:(pair[0]['role'],pair[0]['sha256']))
        value['objects'][10:] = [row for row,_ in tail]
        objects = (*objects[:10],*(raw for _,raw in tail))
        packet = ReleasePacket(parse_installation_header(canonical_json(value)),objects)
        assert packet.header.command_id == case.packet.header.command_id
        assert packet.header.input_digest != case.packet.header.input_digest
    else:
        with case.domain._connection() as db:
            other = case.domain._read_roots(db).actor
        original = case.verification_service._authenticate
        def authenticated_other(request,db,*,read=False):
            actual = original(request,db,read=read)  # real bound owner authentication still runs
            assert actual != other
            return other  # existing retained system actor, not an invented stored owner account
        monkeypatch.setattr(case.verification_service,'_authenticate',authenticated_other)
    def forbidden(*args,**kwargs): raise AssertionError('Conflicting immutable replay reached fresh evaluation')
    monkeypatch.setattr(module,'evaluate_release',forbidden)
    before = case.snapshot()
    with pytest.raises(InstallationError) as error:
        case.verification_service.execute(case.actual.request,packet)
    assert error.value.code == 'conflict'
    assert case.snapshot().authority == before.authority
    assert len(before.verified_refs) == 1 and before.verified_event_count == 1


@pytest.mark.parametrize('full_release_case',[{'platform':'linux/amd64','release_source':True,'status':status}
    for status in ('not-installed','unknown-field','duplicate-record','extra-record','missing-record')],indirect=True)
def test_actual_http_refuses_signed_status_semantics_after_matching_r1_stage(full_release_case):
    from app.tests.provider_installation_fixture import installation_snapshot
    from app.extensions.provider_installation_contracts import PREFIX,MEDIA_TYPE
    from app.extensions.provider_installation_evidence import _authenticate_review
    case = full_release_case
    service = case.actual.app.state.first_party_exports['provider-installation.service']
    with _writer(),case.domain._connection(write=True) as db:
        stage = case.prepare._installation_stage_view(db,case.installation_ref)
    # Independently prove exact provisioned signature/allow and actual stage joins first.
    _authenticate_review(case.packet,service._source.read_current(),stage,1700000000000)
    before = installation_snapshot(case)
    header = case.packet.header.content_bytes
    response = case.client.post(case.profile.base_path.rstrip('/')+'/api/v1/extensions/provider-installation',
        content=PREFIX+len(header).to_bytes(4,'big')+header+b''.join(case.packet.objects),
        headers={'Origin':case.profile.http_origin,'Sec-Fetch-Site':'same-origin',
            'X-Deeptwin-Csrf':case.csrf,'Content-Type':MEDIA_TYPE})
    assert response.status_code == 400,response.text
    assert installation_snapshot(case).authority == before.authority


@pytest.mark.parametrize('mutation',['orphan_verified','orphan_event','version3','duplicate_successor'])
def test_complete_journal_refuses_unowned_installation_history(installation_case,mutation):
    import sqlite3
    from hashlib import sha256
    from app.domain.refs import canonical_json,parse_canonical
    from app.extensions.provider_installation_contracts import InstallationError
    case = installation_case
    case.verification_service.execute(case.actual.request,case.packet)
    with _writer(),case.domain._connection(write=True) as db:
        if mutation == 'orphan_verified': db.execute('DELETE FROM deployment_prepare_installation_verifications')
        elif mutation == 'orphan_event':
            from app.domain.public_events import _append_event_in_transaction
            roots = case.domain._read_roots(db)
            event = dict(db.execute("SELECT * FROM api_event_envelopes WHERE event_type='extension.verified'").fetchone())
            # A real independently appended event has valid sequence/hash, but no owner row.
            from app.extensions.provider_installation_records import event_fields
            from app.domain.refs import EntityRef
            journal = case.prepare._journal(db)
            item = next(item for item in journal['requests'].values() if item.get('installation'))
            actor = EntityRef.from_dict(parse_canonical(item['installation_current']['verification']['actor_ref'].encode()))
            fields = event_fields(roots,item['installation_current']['ref'],actor,case.packet.header.command_id,
                item['installation_current']['verification']['verified_ms'],item)
            _append_event_in_transaction(db,**fields)
        else:
            row = tuple(db.execute("SELECT * FROM domain_records WHERE kind='extension_installation' AND version=2").fetchone())
            if mutation == 'duplicate_successor':
                with pytest.raises(sqlite3.IntegrityError): db.execute('INSERT INTO domain_records VALUES (?,?,?,?,?,?,?)',row)
                return
            value = parse_canonical(row[-1]); value['version'] = 3
            raw = canonical_json(value)
            db.execute('INSERT INTO domain_records VALUES (?,?,?,?,?,?,?)',(*row[:3],3,sha256(raw).hexdigest(),row[5],raw))
    before = case.snapshot()
    with pytest.raises(InstallationError): case.verification_service.read(case.actual.read_request,case.packet.header.command_id)
    assert case.snapshot().authority == before.authority


def test_real_installation_final_writer_exact_reachable_graph_and_finite_bound(installation_case,monkeypatch):
    from app.domain.refs import EntityRef,parse_canonical
    from app.domain.store import BlobRef,MAX_GRAPH_BLOB_BYTES
    from app.deployment.provider_source_contracts import PROVIDER_RECIPE
    from app.deployment.installation_release_contracts import RECIPE
    from app.extensions.provider_installation_contracts import MAX_RAW
    case = installation_case
    real = case.domain._put_in_transaction
    final = []
    def put(db,record):
        result = real(db,record)
        if record.ref.kind == 'extension_installation' and record.ref.version == 2:
            final.append(record.ref)
        return result
    monkeypatch.setattr(case.domain,'_put_in_transaction',put)
    reply = case.verification_service.execute(case.actual.request,case.packet)
    verified = EntityRef.from_dict(reply['verified_installation_ref'])
    assert final == [verified]
    seen,blobs = set(),set()
    with _writer(),case.domain._connection(write=True) as db:
        roots = case.domain._read_roots(db)
        todo = [verified]
        while todo:
            ref = todo.pop()
            if ref in seen: continue
            seen.add(ref)
            record = case.domain._load(db,ref,roots)[0]
            entities,direct = set(),set()
            def visit(value):
                if type(value) is dict:
                    if set(value) == {'kind','id','version','sha256'}:
                        entities.add(EntityRef.from_dict(value))
                    elif set(value) == {'vault_id','purpose','sha256','size'}:
                        direct.add(BlobRef.from_dict(value))
                    else:
                        for child in value.values(): visit(child)
                elif type(value) is list:
                    for child in value: visit(child)
            visit(record.body)
            actual = {EntityRef(*row) for row in db.execute('SELECT target_kind,target_id,target_version,target_sha256 FROM domain_edges WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?',
                (roots.genesis.id,ref.kind,ref.id,ref.version))}
            assert actual == entities
            actual_blobs = {BlobRef(*row) for row in db.execute('SELECT vault_id,purpose,sha256,size FROM domain_record_blobs WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?',
                (roots.genesis.id,ref.kind,ref.id,ref.version))}
            assert actual_blobs == direct
            todo.extend(entities); blobs.update(direct)
        case.domain._check_graph(db,[verified],roots)
    assert {ref.kind for ref in seen} == {'vault_genesis','actor','access_policy','retention_policy',
        'extension_manifest','deployment_request','deployment_receipt','extension_installation'}
    assert {ref.version for ref in seen if ref.kind == 'extension_installation'} == {1,2}
    # Closed ancestry caps: candidate manifest/descriptor/registration/supports,
    # source18/request/inventory/receipt/postcondition, plus this packet and source2.
    bound = (MAX_RAW+2*262144+1048576+32*65536+PROVIDER_RECIPE['bundle_bytes_max']
        +PROVIDER_RECIPE['request_bytes_max']+16384+PROVIDER_RECIPE['receipt_bytes_max']+8192
        +RECIPE['aggregate_bytes_max'])
    assert bound == 54657024 < MAX_GRAPH_BLOB_BYTES == 67108864
    assert sum(blob.size for blob in blobs) <= bound


def test_verified_row_all_null_slots_and_real_timestamp_refuse(installation_case):
    import sqlite3
    from app.deployment.prepare_contracts import DeploymentPrepareError
    case = installation_case
    case.verification_service.execute(case.actual.request,case.packet)
    before = case.snapshot()
    with _writer(),case.domain._connection(write=True) as db:
        for column in storage.COLUMNS_V6['installation_verifications']:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('UPDATE deployment_prepare_installation_verifications SET '+column+'=NULL')
        db.execute('SAVEPOINT task46_real_scalar')
        db.execute('UPDATE deployment_prepare_installation_verifications SET verified_ms=verified_ms+0.5')
        assert db.execute('SELECT typeof(verified_ms) FROM deployment_prepare_installation_verifications').fetchone()[0] == 'real'
        with pytest.raises(DeploymentPrepareError): case.prepare._journal(db)
        db.execute('ROLLBACK TO task46_real_scalar'); db.execute('RELEASE task46_real_scalar')
    assert case.snapshot().authority == before.authority
