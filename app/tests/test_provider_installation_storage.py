"""Exact immediate v5 -> v6 shape and retention; no synthetic journal success rows."""
from hashlib import sha256
import pytest

from app.domain.refs import canonical_json
from app.domain.store import _writer
from app.deployment import prepare_storage as storage
from app.deployment.prepare_contracts import DeploymentPrepareError
from app.tests.provider_installation_fixture import full_release_case,installation_case


def test_v6_literal_extension_preserves_all_five_migration_identities():
    assert hasattr(storage,'DDL_V6'), 'Exact v6 layout is missing'
    assert storage.DDL_V6[1:12] == storage.DDL_V5[1:12]
    assert storage.DDL_V6[13:-1] == storage.DDL_V5[13:]
    assert storage.CHECKSUM_V6 == sha256(canonical_json(list(storage.DDL_V6))).hexdigest()
    assert (storage.CHECKSUM,storage.CHECKSUM_V2,storage.CHECKSUM_V3,storage.CHECKSUM_V4,storage.CHECKSUM_V5) == (
        '68a6ed89486cb48536873e4b107e2e7e1dd4061e5ce65773b0bebe46303cc2ec',
        'd35202bc3d2b3f7be9a0a0d86ba32171c4055334f11531c40497d9b54165693f',
        'ff0931661b7958805f3113bad954110ca702ba3c0205e6dadc73651508a51457',
        'f89a9a8ba7f98da44e4a48f63c0363d2bfa7fafe038bd19bfdc178396c4be7d2',
        '9f3b9426d465524036c8c3ca48db3ba3360e284149b5cee8611aba0d6b4907d2')
    assert storage.CAPS_V6['installation_verifications'] == 1


def test_verification_sql_timestamp_accepts_exact_T_and_refuses_outside(installation_case):
    import sqlite3
    case = installation_case
    case.verification_service.execute(case.actual.request,case.packet)
    before = case.snapshot()
    with _writer(),case.domain._connection(write=True) as db:
        for value in (0,253402300799999):
            db.execute('SAVEPOINT timestamp_endpoint')
            db.execute('UPDATE deployment_prepare_installation_verifications SET verified_ms=?',(value,))
            assert tuple(db.execute('SELECT verified_ms,typeof(verified_ms) FROM deployment_prepare_installation_verifications').fetchone()) == (value,'integer')
            db.execute('ROLLBACK TO timestamp_endpoint'); db.execute('RELEASE timestamp_endpoint')
        for value in (-1,253402300800000):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute('UPDATE deployment_prepare_installation_verifications SET verified_ms=?',(value,))
    assert case.snapshot().authority == before.authority


def _snapshot(db):
    return {table:tuple(tuple(row) for row in db.execute('SELECT rowid,* FROM deployment_prepare_'+table+' ORDER BY rowid'))
        for table in ('migrations',*storage.TABLES_V5)}


@pytest.fixture
def v5_release_case(full_release_case):
    """Exact retained historical v5 setup after today's real fixture constructor.

    This test-only conversion touches only the two changed empty-history parents
    and new empty table; it never exposes a product downgrade or skips a verifier.
    """
    case = full_release_case
    with _writer(),case.domain._connection(write=True) as db:
        before = _snapshot(db)
        assert not db.execute('SELECT 1 FROM deployment_prepare_installation_verifications').fetchall()
        db.execute('PRAGMA defer_foreign_keys=ON')
        db.execute('DROP TABLE deployment_prepare_installation_verifications')
        for table,ddl in (('installation_heads',storage.DDL_V5[12]),('migrations',storage.DDL_V5[0])):
            db.execute('DELETE FROM deployment_prepare_'+table)
            db.execute('DROP TABLE deployment_prepare_'+table)
            db.execute(ddl)
            rows = before[table][:-1] if table == 'migrations' else before[table]
            for row in rows:
                db.execute('INSERT INTO deployment_prepare_'+table+' VALUES ('+','.join('?' for _ in row[1:])+')',row[1:])
                assert db.execute('SELECT rowid FROM deployment_prepare_'+table+' ORDER BY rowid DESC LIMIT 1').fetchone()[0] == row[0]
        assert storage._layout(db) is storage._V5
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        assert case.prepare._journal(db)['rows']['installations']
    return case


def test_immediate_v5_to_v6_preserves_real_stage_cells_types_rowids_and_hashes(v5_release_case):
    assert hasattr(storage,'_rebuild_v5_as_v6'), 'Immediate v5 migration is missing'
    case = v5_release_case
    with _writer(),case.domain._connection(write=True) as db:
        assert storage._layout(db) is storage._V5
        before = _snapshot(db)
        storage._rebuild_v5_as_v6(db)
        after = _snapshot(db)
        assert after['migrations'][:-1] == before['migrations']
        assert after['migrations'][-1][1:] == (6,storage.CHECKSUM_V6)
        assert all(after[table] == before[table] for table in storage.TABLES_V5)
        assert storage._layout(db) is storage._V6
        assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        assert storage.verify(db)['installation_verifications'] == []
        case.domain._assert_write_transaction(db)


def test_immediate_v6_rebuild_rolls_back_after_every_mutating_statement(v5_release_case):
    case = v5_release_case
    class Interrupted(BaseException): pass
    class Checkpoints:
        def __init__(self,db,stop=None): self.db,self.stop,self.statements = db,stop,[]
        def __getattr__(self,name): return getattr(self.db,name)
        def execute(self,sql,args=()):
            result = self.db.execute(sql,args)
            if sql.startswith(('DELETE ','DROP ','CREATE ','INSERT ','PRAGMA defer_foreign_keys=')):
                self.statements.append(sql)
                if len(self.statements) == self.stop: raise Interrupted()
            return result
    with case.domain._connection() as db: before = _snapshot(db)
    with pytest.raises(Interrupted):
        with _writer(),case.domain._connection(write=True) as db:
            probe = Checkpoints(db)
            storage._rebuild_v5_as_v6(probe)
            checkpoints = tuple(probe.statements)
            raise Interrupted()
    assert checkpoints and all('foreign_keys=OFF' not in statement for statement in checkpoints)
    for stop in range(1,len(checkpoints)+1):
        with pytest.raises(Interrupted):
            with _writer(),case.domain._connection(write=True) as db:
                storage._rebuild_v5_as_v6(Checkpoints(db,stop))
        with case.domain._connection() as db:
            assert storage._layout(db) is storage._V5
            assert _snapshot(db) == before
            assert db.execute('PRAGMA foreign_key_check').fetchone() is None
            assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1


@pytest.mark.parametrize('target,column',[('migrations','version'),('installation_heads','extension_id')])
def test_v6_refuses_unexpected_incoming_foreign_key_before_rebuild(v5_release_case,target,column):
    case = v5_release_case
    with _writer(),case.domain._connection(write=True) as db:
        db.execute('CREATE TABLE task46_external_fk (value REFERENCES deployment_prepare_'+target+'('+column+'))')
        before = _snapshot(db)
        with pytest.raises(DeploymentPrepareError): storage._rebuild_v5_as_v6(db)
        assert _snapshot(db) == before
        assert storage._layout(db) is storage._V5


@pytest.mark.parametrize('mutation',['foreign_target','foreign_action','index','trigger','case_alias','checksum'])
def test_current_v6_refuses_each_private_layout_corruption(full_release_case,mutation):
    case = full_release_case
    with _writer(),case.domain._connection(write=True) as db:
        if mutation in ('foreign_target','foreign_action'):
            ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='deployment_prepare_installation_verifications'").fetchone()[0]
            if mutation == 'foreign_target':
                changed = ddl.replace('REFERENCES deployment_prepare_provider_requests','REFERENCES deployment_prepare_requests')
            else:
                changed = ddl.replace('REFERENCES api_event_envelopes(event_id)',
                    'REFERENCES api_event_envelopes(event_id) ON DELETE CASCADE')
            assert changed != ddl
            db.execute('DROP TABLE deployment_prepare_installation_verifications')
            db.execute(changed)
        elif mutation == 'index':
            db.execute('CREATE INDEX task46_extra_index ON deployment_prepare_installation_verifications(command_id)')
        elif mutation == 'trigger':
            db.execute('CREATE TRIGGER task46_extra_trigger AFTER INSERT ON deployment_prepare_installation_verifications BEGIN SELECT 1; END')
        elif mutation == 'case_alias':
            ddl = db.execute("SELECT sql FROM sqlite_master WHERE name='deployment_prepare_installation_verifications'").fetchone()[0]
            db.execute('DROP TABLE deployment_prepare_installation_verifications')
            db.execute(ddl.replace('CREATE TABLE deployment_prepare_installation_verifications',
                'CREATE TABLE Deployment_Prepare_Installation_Verifications'))
        else: db.execute("UPDATE deployment_prepare_migrations SET checksum=? WHERE version=6",('f'*64,))
        before = tuple(tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name'))
        with pytest.raises(DeploymentPrepareError): case.prepare._journal(db)
        assert tuple(tuple(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name')) == before


def test_shared_domain_graph_literal_64mib_and_one_byte_overflow(tmp_path):
    """Shared guard, NOT an impossible oversized coherent installation packet."""
    from app.tests.test_domain_storage import opened,record
    from app.domain.store import MAX_GRAPH_BLOB_BYTES,VerificationLimit
    _,legacy,domain,roots = opened(tmp_path)
    assert MAX_GRAPH_BLOB_BYTES == 67108864 and domain.max_blob_bytes == 16777216
    leaves = []
    for byte in (b'a',b'b',b'c',b'd'):
        blob = domain.put_blob(byte*16777216,purpose='operational')
        leaf = record(roots,content={'evidence':blob.as_dict()})
        domain.put(leaf)
        leaves.append(leaf.ref)
    aggregate = record(roots,parents=tuple(leaves))
    domain.put(aggregate)
    assert domain.get(aggregate.ref).body_bytes == aggregate.body_bytes
    extra = domain.put_blob(b'+',purpose='operational')
    def authority():
        with domain._connection() as db:
            return tuple((table,tuple(tuple(row) for row in db.execute('SELECT * FROM '+table+' ORDER BY rowid')))
                for table in ('domain_records','domain_edges','domain_record_blobs'))
    before = authority()
    overflow = record(roots,parents=(aggregate.ref,),content={'evidence':extra.as_dict()})
    with pytest.raises(VerificationLimit): domain.put(overflow)
    assert authority() == before
    assert domain.read_blob(extra,purpose='operational') == b'+'  # unattached preseal is not authority


@pytest.mark.parametrize('full_release_case',[{'platform':'linux/amd64','legacy_staged':True}],indirect=True)
def test_populated_v5_tool_provider_and_b_migrate_rollback_and_replay_without_source(v5_release_case,monkeypatch):
    """All three histories coexist before the immediate migration; no invented rows."""
    from uuid import uuid4
    from app.tests.provider_conformance_fixture import _retained_provider_conformance_worker,restart_without_provider
    from app.extensions import provider_conformance_service as b_module
    case = v5_release_case
    command = {'command_id':str(uuid4()),'installation_ref':case.installation_ref.as_dict()}
    def extra_authority(db):
        return {table:tuple(tuple(row) for row in db.execute('SELECT rowid,* FROM '+table+' ORDER BY rowid'))
            for table in ('domain_records','domain_edges','domain_record_blobs','api_event_envelopes',
                'provider_conformance_migrations','provider_conformance_control','provider_conformance_runs')}
    class Interrupted(BaseException): pass
    class Checkpoints:
        def __init__(self,db,stop=None): self.db,self.stop,self.statements = db,stop,[]
        def __getattr__(self,name): return getattr(self.db,name)
        def execute(self,sql,args=()):
            result = self.db.execute(sql,args)
            if sql.startswith(('DELETE ','DROP ','CREATE ','INSERT ','PRAGMA defer_foreign_keys=')):
                self.statements.append(sql)
                if len(self.statements) == self.stop: raise Interrupted()
            return result
    with _retained_provider_conformance_worker(case,monkeypatch) as (_,worker):
        reply = case.service.execute(case.actual.request,command)
        assert reply['state'] == 'matched' and worker.completion_count == 6
        headers = {'X-Deeptwin-Csrf':case.csrf,'Origin':case.profile.http_origin,'Sec-Fetch-Site':'same-origin'}
        response = case.client.post(case.path,json=command,headers=headers)
        assert response.status_code == 200
        projected = {**reply,'links':{key:case.profile.base_path.rstrip('/')+value
            for key,value in reply['links'].items()}}
        assert response.json() == projected
        with case.domain._connection() as db:
            assert storage._layout(db) is storage._V5
            before,extra = _snapshot(db),extra_authority(db)
            assert before['receipts'] and before['provider_requests'] and before['installations']
            assert extra['provider_conformance_runs']
            assert db.execute("SELECT 1 FROM domain_records WHERE kind='extension_installation' AND id<>?",
                (case.installation_ref.id,)).fetchone() is not None
        with pytest.raises(Interrupted):
            with _writer(),case.domain._connection(write=True) as db:
                probe = Checkpoints(db)
                storage._rebuild_v5_as_v6(probe)
                checkpoints = tuple(probe.statements)
                raise Interrupted()
        for stop in range(1,len(checkpoints)+1):
            with pytest.raises(Interrupted):
                with _writer(),case.domain._connection(write=True) as db:
                    storage._rebuild_v5_as_v6(Checkpoints(db,stop))
            with case.domain._connection() as db:
                assert storage._layout(db) is storage._V5
                assert _snapshot(db) == before and extra_authority(db) == extra
                assert db.execute('PRAGMA foreign_key_check').fetchone() is None
                assert db.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        with _writer(),case.domain._connection(write=True) as db:
            storage._rebuild_v5_as_v6(db)
            after = _snapshot(db)
            assert after['migrations'][:-1] == before['migrations']
            assert after['migrations'][-1][1:] == (6,storage.CHECKSUM_V6)
            assert all(after[table] == before[table] for table in storage.TABLES_V5)
            assert extra_authority(db) == extra
            assert not storage.verify(db)['installation_verifications']
            assert db.execute('PRAGMA foreign_key_check').fetchone() is None
        def forbidden(*args,**kwargs): raise AssertionError('Historical migrated B sampled fresh source/time or worker')
        monkeypatch.setattr(b_module,'run_fixed_suite',forbidden)
        monkeypatch.setattr(b_module,'resolve_subject',forbidden)
        monkeypatch.setattr(type(case.service),'_wall_now',staticmethod(forbidden))
        with restart_without_provider(case,monkeypatch) as reopened:
            with reopened.domain._connection() as db:
                restarted,post_extra = _snapshot(db),extra_authority(db)
                assert all(restarted[table] == after[table] for table in after if table != 'control')
                assert restarted['control'][0][0] == after['control'][0][0]
                prior,current = (dict(zip(storage.COLUMNS_V6['control'],rows['control'][0][1:],strict=True))
                    for rows in (after,restarted))
                assert current['clock_floor_ms'] >= prior['clock_floor_ms']
                assert current['revision'] == prior['revision']+int(current['clock_floor_ms'] > prior['clock_floor_ms'])
                assert current['hash'] == storage.digest('control',current)
                assert {key:value for key,value in current.items() if key not in ('clock_floor_ms','revision','hash')} == {
                    key:value for key,value in prior.items() if key not in ('clock_floor_ms','revision','hash')}
                assert post_extra == extra
                assert storage._layout(db) is storage._V6
            assert reopened.client.post(case.path,json=command,headers=headers).content == response.content
            assert reopened.client.get(case.path+'/'+command['command_id']).content == response.content
            assert reopened.stopped_worker_completion_count == 6
            with reopened.domain._connection() as db:
                assert _snapshot(db) == restarted and extra_authority(db) == post_extra
