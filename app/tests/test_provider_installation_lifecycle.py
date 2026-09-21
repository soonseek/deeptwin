"""Actual transaction rollback and preseal/source races, never simulated approval."""
import pytest
from app.tests.provider_installation_fixture import installation_case


@pytest.mark.parametrize('boundary',['record','event','row','head'])
def test_each_final_writer_mutation_interruption_rolls_back_all_authority(installation_case,monkeypatch,boundary):
    from app.extensions import provider_installation_service as service
    from app.deployment import prepare_storage as storage
    case = installation_case
    before = case.snapshot()
    class Interrupted(BaseException): pass
    seen = []
    if boundary == 'record':
        original = case.domain._put_in_transaction
        def operation(db,record):
            result = original(db,record)
            if record.body['content'].get('schema_version') == 'provider-installation-verified-v1':
                seen.append(boundary); raise Interrupted()
            return result
        monkeypatch.setattr(case.domain,'_put_in_transaction',operation)
    elif boundary == 'event':
        original = service._append_event_in_transaction
        def operation(*args,**kwargs):
            original(*args,**kwargs)
            seen.append(boundary); raise Interrupted()
        monkeypatch.setattr(service,'_append_event_in_transaction',operation)
    elif boundary == 'row':
        original = storage.insert
        def operation(db,table,values):
            result = original(db,table,values)
            if table == 'installation_verifications':
                seen.append(boundary); raise Interrupted()
            return result
        monkeypatch.setattr(storage,'insert',operation)
    else:
        original = storage._advance_installation_head
        def operation(*args):
            original(*args)
            seen.append(boundary); raise Interrupted()
        monkeypatch.setattr(storage,'_advance_installation_head',operation)
    with pytest.raises(Interrupted): case.verification_service.execute(case.actual.request,case.packet)
    assert seen == [boundary]
    after = case.snapshot()
    assert after.authority == before.authority
    assert after.old_record_bytes == before.old_record_bytes
    assert not after.verified_refs and after.verified_event_count == 0


def test_source_change_after_allowed_preseal_cannot_create_authority(installation_case,monkeypatch):
    from app.extensions.provider_installation_contracts import InstallationError
    case = installation_case
    before = case.snapshot()
    original = case.domain.put_blob
    seen = []
    def put(raw,**kwargs):
        blob = original(raw,**kwargs)
        if not seen:
            seen.append(blob)
            path = case.source_root/'documents'/'release-trust.json'
            case.actual.tree.write(path,b'{}',0,21201)
        return blob
    monkeypatch.setattr(case.domain,'put_blob',put)
    with pytest.raises(InstallationError): case.verification_service.execute(case.actual.request,case.packet)
    assert seen
    assert case.snapshot().authority == before.authority


def test_cancel_before_publish_releases_lease_and_writes_no_authority(installation_case):
    import asyncio
    from app.tests.test_provider_installation_api import request_scope,wire
    from app.services.owner_material_upload_lock import UploadLock
    case = installation_case
    before = case.snapshot()
    async def scenario():
        waiting = asyncio.Event()
        first = True
        async def receive():
            nonlocal first
            if first:
                first = False
                return {'type':'http.request','body':wire(case.packet)[:13],'more_body':True}
            waiting.set()
            await asyncio.Event().wait()
        async def send(message): raise AssertionError('Cancelled intake sent a success')
        task = asyncio.create_task(case.actual.app(request_scope(case),receive,send))
        await asyncio.wait_for(waiting.wait(),10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())
    lease = UploadLock(case.domain.data_dir); lease.close()
    assert case.snapshot().authority == before.authority


def test_cancel_during_actual_owned_publish_holds_lease_until_durable_completion(installation_case,monkeypatch):
    import asyncio,threading
    from app.tests.test_provider_installation_api import request_scope,wire
    from app.services.owner_material_upload_lock import UploadLock
    from app.services.works import WorkServiceError
    case = installation_case
    entered,release,finished = (threading.Event() for _ in range(3))
    original = case.verification_service.execute
    outcome = []
    def execute(*args):
        entered.set()
        assert release.wait(15),'Controlled publication was not released'
        try:
            result = original(*args)
            outcome.append(result)
            return result
        finally: finished.set()
    monkeypatch.setattr(case.verification_service,'execute',execute)
    before = case.snapshot()
    async def scenario():
        async def receive(): return {'type':'http.request','body':wire(case.packet),'more_body':False}
        async def send(message): raise AssertionError('Disconnected request sent a result')
        task = asyncio.create_task(case.actual.app(request_scope(case),receive,send))
        try:
            assert await asyncio.to_thread(entered.wait,10)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            with pytest.raises(WorkServiceError) as error: UploadLock(case.domain.data_dir)
            assert error.value.code == 'capacity'
            assert case.snapshot().authority == before.authority
        finally: release.set()
        assert await asyncio.to_thread(finished.wait,15)
        # The actual UploadLock child task and its close callback finish on this loop.
        await asyncio.sleep(0.05)
    asyncio.run(scenario())
    assert len(outcome) == 1
    lease = UploadLock(case.domain.data_dir); lease.close()
    after = case.snapshot()
    assert len(after.verified_refs) == 1 and after.verified_event_count == 1
    assert case.post_packet(case.packet).json() == {**outcome[0], 'links':{
        key:case.profile.base_path.rstrip('/')+value for key,value in outcome[0]['links'].items()}}
    assert case.snapshot().authority == after.authority


def test_boundary_cleanup_preserves_primary_baseexception(installation_case,monkeypatch):
    import asyncio
    from app.tests.test_provider_installation_api import request_scope
    from app.services.owner_material_upload_lock import UploadLock
    case = installation_case
    class Primary(BaseException): pass
    primary = Primary('controlled intake interruption')
    cleanup = RuntimeError('controlled cleanup failure')
    original = UploadLock.close
    closed = []
    def close(lease):
        original(lease)
        closed.append(lease._fd)
        raise cleanup
    monkeypatch.setattr(UploadLock,'close',close)
    before = case.snapshot()
    async def receive(): raise primary
    sent = []
    async def send(message): sent.append(message)
    with pytest.raises(Primary) as error:
        asyncio.run(case.actual.app(request_scope(case),receive,send))
    assert error.value is primary and closed == [None]
    assert sent == []
    assert case.snapshot().authority == before.authority


@pytest.mark.parametrize('mutation',['missing','replaced'])
def test_final_writer_rereads_actual_presealed_blob(installation_case,monkeypatch,mutation):
    import os
    from app.extensions.provider_installation_contracts import InstallationError
    case = installation_case
    before = case.snapshot()
    original = case.domain.put_blob
    count = 0
    def put(raw,**kwargs):
        nonlocal count
        blob = original(raw,**kwargs)
        count += 1
        if count == len(case.packet.objects)+2:
            with case.domain._blob_directory('operational') as directory:
                os.unlink(blob.sha256,dir_fd=directory)
                if mutation == 'replaced':
                    descriptor = os.open(blob.sha256,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600,dir_fd=directory)
                    try: os.write(descriptor,b'x'*len(raw))
                    finally: os.close(descriptor)
        return blob
    monkeypatch.setattr(case.domain,'put_blob',put)
    with pytest.raises(InstallationError) as error: case.verification_service.execute(case.actual.request,case.packet)
    assert error.value.code == 'unavailable'
    assert count == len(case.packet.objects)+2
    assert case.snapshot().authority == before.authority


def test_owner_revocation_during_preseal_refuses_final_commit(installation_case,monkeypatch):
    from uuid import uuid4
    from app.extensions.provider_installation_contracts import InstallationError
    case = installation_case
    original = case.domain.put_blob
    after_revocation = []
    def put(raw,**kwargs):
        blob = original(raw,**kwargs)
        if not after_revocation:
            owner = case.actual.owner
            owner.logout(case.actual.request,command_id=str(uuid4()),
                token_b64u=case.client.cookies.get(owner.cookie_name))
            after_revocation.append(case.snapshot())
        return blob
    monkeypatch.setattr(case.domain,'put_blob',put)
    with pytest.raises(InstallationError) as error: case.verification_service.execute(case.actual.request,case.packet)
    assert error.value.code == 'unauthenticated'
    assert len(after_revocation) == 1
    assert case.snapshot().authority == after_revocation[0].authority
    assert not case.snapshot().verified_refs


def test_interleaved_real_verification_wins_cas_without_loser_authority(installation_case,monkeypatch):
    from uuid import uuid4
    from app.domain.refs import canonical_json
    from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header,InstallationError
    case = installation_case
    header = case.packet.header.as_dict(); header['command_id'] = str(uuid4())
    other = ReleasePacket(parse_installation_header(canonical_json(header)),case.packet.objects)
    original = case.domain.put_blob
    started = False
    winner = []
    def put(raw,**kwargs):
        nonlocal started
        blob = original(raw,**kwargs)
        if not started:
            started = True
            reply = case.verification_service.execute(case.actual.request,other)
            winner.append((reply,case.snapshot()))
        return blob
    monkeypatch.setattr(case.domain,'put_blob',put)
    with pytest.raises(InstallationError) as error: case.verification_service.execute(case.actual.request,case.packet)
    assert error.value.code == 'conflict'
    assert len(winner) == 1 and winner[0][0]['command_id'] == other.header.command_id
    assert len(winner[0][1].verified_refs) == 1 and winner[0][1].verified_event_count == 1
    assert case.snapshot().authority == winner[0][1].authority


def test_actual_sqlite_commit_failure_rolls_back_verified_authority(installation_case,monkeypatch):
    import sqlite3
    from app.deployment import prepare_storage as storage
    from app.extensions.provider_installation_contracts import InstallationError
    case = installation_case
    before = case.snapshot()
    original = storage._advance_installation_head
    interrupted = []
    def advance(db,*args):
        result = original(db,*args)
        def authorize(action,first,second,database,trigger):
            if action == sqlite3.SQLITE_TRANSACTION and first == 'COMMIT':
                interrupted.append(True)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        return result
    monkeypatch.setattr(storage,'_advance_installation_head',advance)
    with pytest.raises(InstallationError) as error: case.verification_service.execute(case.actual.request,case.packet)
    assert error.value.code == 'unavailable' and interrupted == [True]
    assert case.snapshot().authority == before.authority
