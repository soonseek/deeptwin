"""Explicit verified-descendant B, using actual retained history and framed worker."""
from uuid import uuid4
import pytest

from app.domain.refs import EntityRef
from app.tests.provider_installation_fixture import installation_case


def verified_command(case,reply,*,command_id=None):
    return {'schema_version':'provider-conformance-command-v2','command_id':command_id or str(uuid4()),
        'staged_installation_ref':case.stage_ref.as_dict(),
        'expected_verified_installation_ref':reply['verified_installation_ref']}


def test_new_legacy_b_conflicts_after_verification_before_probe(installation_case,monkeypatch):
    from app.extensions import provider_conformance_service as module
    from app.extensions.provider_conformance_contracts import ConformanceError
    case = installation_case
    case.verification_service.execute(case.actual.request,case.packet)
    def forbidden(*args,**kwargs): raise AssertionError('Legacy B probed after verified head')
    monkeypatch.setattr(module,'run_fixed_suite',forbidden)
    before = case.snapshot()
    with pytest.raises(ConformanceError) as error:
        case.b_service.execute(case.actual.request,{'command_id':str(uuid4()),'installation_ref':case.stage_ref.as_dict()})
    assert error.value.code == 'conflict'
    assert case.snapshot().authority == before.authority


def test_explicit_verified_b_runs_actual_fixed_worker_suite(installation_case,monkeypatch):
    from app.extensions.provider_conformance_contracts import parse_command
    from app.tests.provider_conformance_fixture import _retained_provider_conformance_worker
    case = installation_case
    verified = case.verification_service.execute(case.actual.request,case.packet)
    command = verified_command(case,verified)
    assert parse_command(command) == command
    with _retained_provider_conformance_worker(case,monkeypatch) as (_,worker):
        reply = case.b_service.execute(case.actual.request,command)
        assert reply['schema_version'] == 'provider-conformance-reply-v2'
        assert reply['state'] == 'matched' and reply['completed_count'] == 4 and reply['matched_count'] == 4
        assert reply['staged_installation_ref'] == case.stage_ref.as_dict()
        assert reply['verified_installation_ref'] == verified['verified_installation_ref']
        assert reply['stage_context_sha256'] != reply['admission_sha256']
        assert worker.completion_count == 6
        from app.domain.store import _writer
        from app.domain.schema_exports import domain_schema
        from app.extensions.provider_conformance_schema_exports import record_schema,input_schema,reply_schema
        from jsonschema import Draft202012Validator
        assert Draft202012Validator(input_schema()).is_valid(command)
        assert Draft202012Validator(reply_schema()).is_valid(reply)
        with _writer(),case.domain._connection(write=True) as db:
            roots = case.domain._read_roots(db)
            for key in ('intent_ref','result_ref'):
                ref = EntityRef.from_dict(reply[key]); record = case.domain._load(db,ref,roots)[0]
                for schema in (record_schema(),domain_schema()):
                    assert Draft202012Validator(schema).is_valid({'ref':ref.as_dict(),'body':record.body})
    before = case.snapshot()
    assert case.b_service.execute(case.actual.request,command) == reply
    assert case.b_service.read(case.actual.read_request,command['command_id']) == reply
    assert case.snapshot().authority == before.authority


def test_old_b_history_replays_unchanged_after_verified_successor(installation_case,monkeypatch):
    from app.extensions import provider_conformance_service as module
    from app.tests.provider_conformance_fixture import _retained_provider_conformance_worker
    case = installation_case
    command = {'command_id':str(uuid4()),'installation_ref':case.stage_ref.as_dict()}
    with _retained_provider_conformance_worker(case,monkeypatch) as (_,worker):
        old = case.b_service.execute(case.actual.request,command)
        assert old['state'] == 'matched' and worker.completion_count == 6
    old_records = case.snapshot().old_record_bytes
    case.verification_service.execute(case.actual.request,case.packet)
    assert case.snapshot().old_record_bytes == old_records
    def forbidden(*args,**kwargs): raise AssertionError('Historical B replay probed or read fresh admission')
    monkeypatch.setattr(module,'run_fixed_suite',forbidden)
    monkeypatch.setattr(module,'resolve_subject',forbidden)
    before = case.snapshot()
    assert case.b_service.execute(case.actual.request,command) == old
    assert case.b_service.read(case.actual.read_request,command['command_id']) == old
    assert case.snapshot().authority == before.authority


def test_verified_b_http_rehydrate_and_source_less_actual_restart(installation_case,monkeypatch):
    from app.domain.store import _writer
    from app.extensions import provider_conformance_service as module
    from app.extensions.provider_conformance_contracts import RehydratedVerifiedConformance
    from app.tests.provider_conformance_fixture import _retained_provider_conformance_worker,restart_without_provider
    case = installation_case
    verified = case.verification_service.execute(case.actual.request,case.packet)
    command = verified_command(case,verified)
    path = case.profile.base_path.rstrip('/')+'/api/v1/extensions/provider-conformance'
    headers = {key:value for key,value in case.auth_headers.items() if key != 'Content-Type'}
    with _retained_provider_conformance_worker(case,monkeypatch) as (_,worker):
        response = case.client.post(path,json=command,headers=headers)
        assert response.status_code == 200,response.text
        reply = response.json()
        assert reply['state'] == 'matched' and worker.completion_count == 6
        with _writer(),case.domain._connection(write=True) as db:
            loaded = case.b_service.rehydrate(db,EntityRef.from_dict(reply['result_ref']))
            assert type(loaded) is RehydratedVerifiedConformance
            assert loaded.admission.verified_installation_ref.as_dict() == verified['verified_installation_ref']
            assert loaded.comparison.completion == 'matched' and loaded.capture_bytes
        def forbidden(*args,**kwargs): raise AssertionError('Source-less historical B invoked fresh execution')
        monkeypatch.setattr(module,'run_fixed_suite',forbidden)
        monkeypatch.setattr(module,'resolve_verified_admission',forbidden)
        # Existing exact restart helper owns and closes this exercised real worker.
        with restart_without_provider(case,monkeypatch) as reopened:
            assert reopened.client.post(path,json=command,headers=headers).content == response.content
            assert reopened.client.get(path+'/'+command['command_id']).content == response.content
            assert reopened.stopped_worker_completion_count == 6


@pytest.mark.parametrize('mutation',['wrong_hash','wrong_id','wrong_version','same_id_other_variant'])
def test_verified_b_expected_identity_and_command_variant_refusal(installation_case,monkeypatch,mutation):
    from app.extensions import provider_conformance_service as module
    from app.extensions.provider_conformance_contracts import ConformanceError
    case = installation_case
    verified = case.verification_service.execute(case.actual.request,case.packet)
    command = verified_command(case,verified)
    if mutation == 'wrong_hash': command['expected_verified_installation_ref']['sha256'] = 'f'*64
    elif mutation == 'wrong_id': command['expected_verified_installation_ref']['id'] = str(uuid4())
    elif mutation == 'wrong_version': command['expected_verified_installation_ref']['version'] = 3
    else:
        class Interrupted(BaseException): pass
        def interrupted(*args,**kwargs): raise Interrupted()
        monkeypatch.setattr(module,'run_fixed_suite',interrupted)
        with pytest.raises(Interrupted): case.b_service.execute(case.actual.request,command)
        command = {'command_id':command['command_id'],'installation_ref':case.stage_ref.as_dict()}
    def forbidden(*args,**kwargs): raise AssertionError('Invalid B selector probed')
    monkeypatch.setattr(module,'run_fixed_suite',forbidden)
    before = case.snapshot()
    with pytest.raises(ConformanceError) as error: case.b_service.execute(case.actual.request,command)
    assert error.value.code in ('conflict','invalid_input')
    assert case.snapshot().authority == before.authority


def test_verified_b_pending_recovery_retains_explicit_variant(installation_case,monkeypatch):
    from app.domain.store import _writer
    from app.extensions import provider_conformance_service as module
    from app.tests.provider_conformance_fixture import _retained_provider_conformance_worker
    case = installation_case
    verified = case.verification_service.execute(case.actual.request,case.packet)
    first = verified_command(case,verified)
    class Interrupted(BaseException): pass
    real = module.run_fixed_suite
    def interrupted(*args,**kwargs): raise Interrupted()
    monkeypatch.setattr(module,'run_fixed_suite',interrupted)
    with pytest.raises(Interrupted): case.b_service.execute(case.actual.request,first)
    pending = case.b_service.read(case.actual.read_request,first['command_id'])
    assert pending['schema_version'] == 'provider-conformance-reply-v2' and pending['state'] == 'pending'
    from types import SimpleNamespace
    clock = module.time
    advanced = SimpleNamespace(time_ns=lambda:clock.time_ns()+60001000000,monotonic=clock.monotonic)
    monkeypatch.setattr(module,'time',advanced)
    from app.workers import provider_client
    monkeypatch.setattr(provider_client,'time',advanced)
    monkeypatch.setattr(module,'run_fixed_suite',real)
    second = verified_command(case,verified)
    with case.restart_without_release_source() as reopened:
        # Startup itself preserves the pending variant; explicit authenticated second
        # command, not startup, is the only recovery authority after the deadline.
        assert reopened.b_service.read(reopened.actual.read_request,first['command_id']) == pending
        with _retained_provider_conformance_worker(reopened,monkeypatch) as (_,worker):
            reply = reopened.b_service.execute(reopened.actual.request,second)
            assert reply['state'] == 'matched' and worker.completion_count == 6
        recovered = reopened.b_service.read(reopened.actual.read_request,first['command_id'])
        assert recovered['state'] == 'incomplete' and recovered['schema_version'] == 'provider-conformance-reply-v2'
        with _writer(),reopened.domain._connection(write=True) as db:
            loaded = reopened.b_service.rehydrate(db,EntityRef.from_dict(recovered['result_ref']))
            assert loaded.comparison.reason == 'interrupted' and loaded.capture_bytes is None


def test_legacy_b_stage_to_verified_during_real_worker_run_never_rebases(installation_case,monkeypatch):
    from app.workers import provider_client
    from app.tests.provider_conformance_fixture import _provider_conformance_worker
    case = installation_case
    real = provider_client._identify
    calls = []
    def identify(*args):
        result = real(*args)
        calls.append(result)
        case.verification_service.execute(case.actual.request,case.packet)
        return result
    monkeypatch.setattr(provider_client,'_identify',identify)
    with _provider_conformance_worker(case.actual,monkeypatch,serve_count=1) as (_,worker):
        reply = case.b_service.execute(case.actual.request,{'command_id':str(uuid4()),'installation_ref':case.stage_ref.as_dict()})
        assert reply['state'] == 'incomplete' and reply['schema_version'] == 'provider-conformance-reply-v1'
        assert worker.completion_count == 1 and len(calls) == 1
    from app.domain.store import _writer
    with _writer(),case.domain._connection(write=True) as db:
        loaded = case.b_service.rehydrate(db,EntityRef.from_dict(reply['result_ref']))
        assert loaded.comparison.reason == 'source_changed'
        assert loaded.subject.installation_ref == case.stage_ref


@pytest.mark.parametrize('mutation',['admission_head','report_comparison','cursor'])
def test_verified_b_coherent_history_tampering_refuses(installation_case,monkeypatch,mutation):
    from hashlib import sha256
    from app.domain.store import _writer
    from app.domain.refs import canonical_json,parse_canonical
    from app.domain.schemas import ImmutableRecord
    from app.domain.public_events import EventEnvelope
    from app.extensions import provider_conformance_service as module
    from app.extensions.provider_conformance_contracts import ConformanceError
    from app.tests.provider_conformance_fixture import _retained_provider_conformance_worker
    case = installation_case
    verified = case.verification_service.execute(case.actual.request,case.packet)
    command = verified_command(case,verified)
    if mutation == 'admission_head':
        class Interrupted(BaseException): pass
        def interrupted(*args,**kwargs): raise Interrupted()
        monkeypatch.setattr(module,'run_fixed_suite',interrupted)
        with pytest.raises(Interrupted): case.b_service.execute(case.actual.request,command)
    else:
        with _retained_provider_conformance_worker(case,monkeypatch) as (_,worker):
            assert case.b_service.execute(case.actual.request,command)['state'] == 'matched'
            assert worker.completion_count == 6
    with _writer(),case.domain._connection(write=True) as db:
        row = dict(db.execute('SELECT * FROM provider_conformance_runs WHERE command_id=?',(command['command_id'],)).fetchone())
        if mutation == 'cursor':
            reply = parse_canonical(row['terminal_reply']); pending = parse_canonical(row['pending_reply'])
            reply['event_cursor'] = pending['event_cursor']
            db.execute('UPDATE provider_conformance_runs SET terminal_reply=? WHERE command_id=?',
                (canonical_json(reply),command['command_id']))
        else:
            version = 1 if mutation == 'admission_head' else 2
            body = parse_canonical(db.execute("SELECT body FROM domain_records WHERE kind='provider_conformance_run' AND id=? AND version=?",
                (command['command_id'],version)).fetchone()[0])
            content = body['content']
            reply_column,hash_column,sequence = (('pending_reply','intent_sha256','started_sequence') if version == 1
                else ('terminal_reply','report_sha256','finished_sequence'))
            reply = parse_canonical(row[reply_column])
            if version == 1:
                content['admission']['installation_head_hash'] = 'f'*64
                content['admission_sha256'] = sha256(canonical_json(content['admission'])).hexdigest()
                reply['admission_sha256'] = content['admission_sha256']
            else:
                content['completion'] = 'mismatch'; content['vectors'][0]['comparison'] = 'mismatch'
                content['covered_subchecks'] = content['covered_subchecks'][1:]
                reply['state'] = 'mismatch'; reply['matched_count'] = 3
            changed = ImmutableRecord.from_bytes(canonical_json(body))
            reply['intent_ref' if version == 1 else 'result_ref'] = changed.ref.as_dict()
            event = parse_canonical(db.execute('SELECT envelope FROM api_event_envelopes WHERE sequence=?',(row[sequence],)).fetchone()[0])
            event['object_refs'][0]['content_hash'] = changed.ref.sha256
            if version == 2:
                event['private_evidence_refs'] = [changed.ref.as_dict()]
                event['status'] = 'failed'; event['public_metadata'].update(matched_count=3,outcome='mismatch')
            EventEnvelope.from_mapping(event)
            db.execute('PRAGMA defer_foreign_keys=ON')
            db.execute("UPDATE domain_records SET body=?,sha256=? WHERE kind='provider_conformance_run' AND id=? AND version=?",
                (changed.body_bytes,changed.ref.sha256,command['command_id'],version))
            db.execute('UPDATE provider_conformance_runs SET '+hash_column+'=?,'+reply_column+'=?'+
                (",state='mismatch'" if version == 2 else '')+' WHERE command_id=?',
                (changed.ref.sha256,canonical_json(reply),command['command_id']))
            db.execute('UPDATE api_event_envelopes SET envelope=? WHERE sequence=?',(canonical_json(event),row[sequence]))
            assert db.execute('PRAGMA foreign_key_check').fetchone() is None
            case.domain._check_graph(db,[changed.ref],case.domain._read_roots(db))
    before = case.snapshot()
    with pytest.raises(ConformanceError): case.b_service.read(case.actual.read_request,command['command_id'])
    assert case.snapshot().authority == before.authority


def test_owned_b_schema_exports_and_runtime_allocation_boundary():
    import json
    from pathlib import Path
    from app.extensions.provider_conformance_schema_exports import exported_schemas
    from app.extensions.provider_conformance_contracts import ConformanceSubject,ConformanceVerifiedAdmission
    for cls in (ConformanceSubject,ConformanceVerifiedAdmission):
        with pytest.raises(TypeError): cls()
    root = Path(__file__).resolve().parents[2]/'schemas/v2/extensions'
    for name,schema in exported_schemas().items():
        assert json.loads((root/name).read_bytes()) == schema


def test_verified_b_backward_clock_refuses_before_durable_intent(installation_case,monkeypatch):
    from types import SimpleNamespace
    from app.extensions import provider_conformance_service as module
    from app.extensions.provider_conformance_contracts import ConformanceError
    case = installation_case
    verified = case.verification_service.execute(case.actual.request,case.packet)
    real_time = module.time
    monkeypatch.setattr(module,'time',SimpleNamespace(time_ns=lambda:(verified['verified_at_ms']-1)*1000000,
        monotonic=real_time.monotonic))
    def forbidden(*args,**kwargs): raise AssertionError('Backdated verified B reached worker')
    monkeypatch.setattr(module,'run_fixed_suite',forbidden)
    before = case.snapshot()
    with pytest.raises(ConformanceError) as error:
        case.b_service.execute(case.actual.request,verified_command(case,verified))
    assert error.value.code == 'unavailable'
    assert case.snapshot().authority == before.authority


@pytest.mark.parametrize('variant',['legacy','verified'])
@pytest.mark.parametrize('association',['edges','blobs'])
def test_intent_association_counts_refuse_before_domain_load(installation_case,monkeypatch,variant,association):
    from app.domain.store import _writer
    from app.extensions import provider_conformance_service as service,provider_conformance_records as records
    from app.extensions.provider_conformance_contracts import ConformanceError
    case = installation_case
    if variant == 'verified':
        verified = case.verification_service.execute(case.actual.request,case.packet)
        command = verified_command(case,verified)
    else: command = {'command_id':str(uuid4()),'installation_ref':case.stage_ref.as_dict()}
    class Interrupted(BaseException): pass
    def interrupted(*args,**kwargs): raise Interrupted()
    monkeypatch.setattr(service,'run_fixed_suite',interrupted)
    with pytest.raises(Interrupted): case.b_service.execute(case.actual.request,command)
    calls = []
    original = case.domain._load
    with _writer(),case.domain._connection(write=True) as db:
        roots = case.domain._read_roots(db)
        row = db.execute('SELECT * FROM provider_conformance_runs WHERE command_id=?',(command['command_id'],)).fetchone()
        ref = EntityRef('provider_conformance_run',command['command_id'],1,row['intent_sha256'])
        source = (roots.genesis.id,ref.kind,ref.id,1)
        edge_sql = 'SELECT count(*) FROM domain_edges WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?'
        blob_sql = 'SELECT count(*) FROM domain_record_blobs WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?'
        assert db.execute(edge_sql,source).fetchone()[0] == (8 if variant == 'verified' else 7)
        assert db.execute(blob_sql,source).fetchone()[0] == 0
        if association == 'edges':
            existing = {tuple(item) for item in db.execute('SELECT target_kind,target_id,target_version,target_sha256 FROM domain_edges WHERE vault_id=? AND source_kind=? AND source_id=? AND source_version=?',source)}
            candidates = [tuple(item) for item in db.execute('SELECT kind,id,version,sha256 FROM domain_records ORDER BY rowid') if tuple(item) not in existing]
            for target in candidates[:9-len(existing)]:
                db.execute('INSERT INTO domain_edges VALUES (?,?,?,?,?,?,?,?)',(*source,*target))
            assert db.execute(edge_sql,source).fetchone()[0] == 9
        else:
            blob = db.execute('SELECT purpose,sha256,size FROM domain_record_blobs LIMIT 1').fetchone()
            assert blob is not None
            db.execute('INSERT INTO domain_record_blobs VALUES (?,?,?,?,?,?,?)',(*source,*blob))
            assert db.execute(blob_sql,source).fetchone()[0] == 1
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        before = tuple(tuple(item) for item in db.execute('SELECT * FROM provider_conformance_runs'))
        def load(connection,target,actual_roots):
            if target == ref: calls.append(target)
            return original(connection,target,actual_roots)
        monkeypatch.setattr(case.domain,'_load',load)
        owner = case.prepare._actor_ref(db,case.prepare._authenticate(case.actual.request,db))
        with pytest.raises(ConformanceError): records._load_one(case.prepare,db,row,owner)
        assert calls == [],'Oversized actual intent association index was materialized before count refusal'
        assert tuple(tuple(item) for item in db.execute('SELECT * FROM provider_conformance_runs')) == before


def test_completed_legacy_b_past_run_deadline_then_verified_b_is_fresh(installation_case,monkeypatch):
    from types import SimpleNamespace
    from app.extensions import provider_conformance_service as b,provider_installation_service as installation
    from app.workers import provider_client
    from app.tests.provider_conformance_fixture import _provider_conformance_worker
    case = installation_case
    old_command = {'command_id':str(uuid4()),'installation_ref':case.stage_ref.as_dict()}
    with _provider_conformance_worker(case.actual,monkeypatch) as (_,old_worker):
        old_reply = case.b_service.execute(case.actual.request,old_command)
        assert old_reply['state'] == 'matched' and old_worker.completion_count == 6
    with case.domain._connection() as db:
        deadline = db.execute('SELECT deadline_ms FROM provider_conformance_runs WHERE command_id=?',(old_command['command_id'],)).fetchone()[0]
        old_records = tuple(tuple(row) for row in db.execute("SELECT rowid,* FROM domain_records WHERE kind='provider_conformance_run' AND id=? ORDER BY version",(old_command['command_id'],)))
    real_clock = b.time
    advanced = SimpleNamespace(time_ns=lambda:real_clock.time_ns()+60001000000,monotonic=real_clock.monotonic)
    assert advanced.time_ns()//1000000 > deadline
    for module in (b,installation,provider_client): monkeypatch.setattr(module,'time',advanced)
    real_suite = b.run_fixed_suite
    def forbidden(*args,**kwargs): raise AssertionError('Completed old reply replay probed after its run deadline')
    monkeypatch.setattr(b,'run_fixed_suite',forbidden)
    before = case.snapshot()
    assert case.b_service.execute(case.actual.request,old_command) == old_reply
    assert case.b_service.read(case.actual.read_request,old_command['command_id']) == old_reply
    assert case.snapshot().authority == before.authority
    verified = case.verification_service.execute(case.actual.request,case.packet)
    assert verified['verified_at_ms'] > deadline
    fresh = verified_command(case,verified)
    assert fresh['command_id'] != old_command['command_id']
    monkeypatch.setattr(b,'run_fixed_suite',real_suite)
    with _provider_conformance_worker(case.actual,monkeypatch) as (_,new_worker):
        reply = case.b_service.execute(case.actual.request,fresh)
        assert reply['state'] == 'matched' and reply['schema_version'] == 'provider-conformance-reply-v2'
        assert reply['completed_count'] == reply['matched_count'] == 4
        assert new_worker.completion_count == 6 and reply != old_reply
    assert case.b_service.read(case.actual.read_request,old_command['command_id']) == old_reply
    with case.domain._connection() as db:
        assert tuple(tuple(row) for row in db.execute("SELECT rowid,* FROM domain_records WHERE kind='provider_conformance_run' AND id=? ORDER BY version",(old_command['command_id'],))) == old_records
