"""Binary owner boundary, actual publication, and exact browser replay."""
import asyncio
import importlib
import pytest
from app.tests.provider_installation_fixture import full_release_case
from app.tests.provider_installation_fixture import installation_case
from app.extensions.provider_installation_contracts import PREFIX,MEDIA_TYPE


def wire(packet):
    header = packet.header.content_bytes
    return PREFIX+len(header).to_bytes(4,'big')+header+b''.join(packet.objects)


@pytest.mark.parametrize('full_release_case',[{'platform':'linux/amd64','release_source':True}],indirect=True)
def test_binary_browser_command_publishes_exact_result_and_read_replay(full_release_case):
    case = full_release_case
    assert 'provider-installation.service' in case.actual.app.state.first_party_exports
    path = case.profile.base_path.rstrip('/')+'/api/v1/extensions/provider-installation'
    headers = {'Origin':case.profile.http_origin,'Sec-Fetch-Site':'same-origin',
        'X-Deeptwin-Csrf':case.csrf,'Content-Type':MEDIA_TYPE}
    raw = wire(case.packet)
    response = case.client.post(path,content=raw,headers=headers)
    assert response.status_code == 200,response.text
    assert response.json()['state'] == 'verified'
    assert case.client.post(path,content=raw,headers=headers).content == response.content
    read = case.client.get(path+'/'+case.packet.header.command_id)
    assert read.status_code == 200 and read.content == response.content
    head = case.client.head(path+'/'+case.packet.header.command_id)
    assert head.status_code == 200 and head.content == b''


def test_carrier_receiver_interface_exists():
    try: module = importlib.import_module('app.api.provider_installation')
    except ModuleNotFoundError: pytest.fail('Actual installation binary receiver is missing')
    assert callable(module.receive_packet)


def _small_packet():
    from uuid import uuid4
    from app.domain.refs import EntityRef
    from app.tests.provider_installation_fixture import packet_header
    from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header
    raw,objects = packet_header(EntityRef('extension_installation',str(uuid4()),1,'a'*64))
    return ReleasePacket(parse_installation_header(raw),objects)


@pytest.mark.parametrize('size',[1,2,7,8,11,12,13,31,32768])
def test_binary_receiver_accepts_split_and_coalesced_exact_bytes(size):
    from app.api.provider_installation import receive_packet
    packet = _small_packet()
    raw = wire(packet)
    chunks = iter([raw[i:i+size] for i in range(0,len(raw),size)])
    received = 0
    async def receive():
        nonlocal received
        chunk = next(chunks)
        received += len(chunk)
        return {'type':'http.request','body':chunk,'more_body':received < len(raw)}
    assert asyncio.run(receive_packet(receive,len(raw))) == packet


@pytest.mark.parametrize('mutation',['magic','zero_header','large_header','truncated','trailing','hash','wire_length','disconnect'])
def test_binary_receiver_refuses_malformed_carrier_before_service(mutation):
    from app.api.provider_installation import receive_packet
    from app.extensions.provider_installation_contracts import InstallationError
    raw = wire(_small_packet())
    if mutation == 'magic': raw = b'BADMAGIC'+raw[8:]
    if mutation == 'zero_header': raw = raw[:8]+bytes(4)+raw[12:]
    if mutation == 'large_header': raw = raw[:8]+(32769).to_bytes(4,'big')+raw[12:]
    if mutation == 'truncated': raw = raw[:-1]
    if mutation == 'trailing': raw += b'x'
    if mutation == 'hash': raw = raw[:-1]+bytes([raw[-1]^1])
    declared = len(raw)+(1 if mutation == 'wire_length' else 0)
    async def receive():
        return {'type':'http.disconnect'} if mutation == 'disconnect' else {'type':'http.request','body':raw,'more_body':False}
    with pytest.raises(asyncio.CancelledError if mutation == 'disconnect' else InstallationError):
        asyncio.run(receive_packet(receive,declared))


def request_scope(case,*,method='POST',headers=None):
    path = case.path
    fields = [(b'host',case.profile.http_origin.split('://',1)[1].encode()),
        (b'origin',case.profile.http_origin.encode()),(b'sec-fetch-site',b'same-origin'),
        (b'cookie','; '.join(key+'='+value for key,value in case.client.cookies.items()).encode()),
        (b'x-deeptwin-csrf',case.csrf.encode()),(b'content-type',MEDIA_TYPE.encode()),
        (b'content-length',str(len(wire(case.packet))).encode())]
    return {'type':'http','asgi':{'version':'3.0'},'http_version':'1.1','method':method,
        'scheme':case.profile.scheme,'path':path,'raw_path':path.encode(),'query_string':b'',
        'root_path':'','headers':fields if headers is None else headers,'client':('127.0.0.1',1234),
        'server':('localhost',8080)}


@pytest.mark.parametrize('mutation,status',[('cookie',401),('csrf',403),('origin',403),('media',400),
    ('encoding',400),('duplicate_length',400),('oversize',413),('query',400)])
def test_actual_boundary_refuses_before_any_asgi_receive(installation_case,mutation,status):
    case = installation_case
    scope = request_scope(case)
    fields = scope['headers']
    remove = {'cookie':b'cookie','csrf':b'x-deeptwin-csrf','origin':b'origin','media':b'content-type'}
    if mutation in remove: fields[:] = [(k,v) for k,v in fields if k != remove[mutation]]
    if mutation == 'encoding': fields.append((b'content-encoding',b'gzip'))
    if mutation == 'duplicate_length': fields.append((b'content-length',b'13'))
    if mutation == 'oversize': fields[:] = [(k,b'50364429' if k == b'content-length' else v) for k,v in fields]
    if mutation == 'query': scope['query_string'] = b'approve=true'
    before = case.snapshot()
    output = []
    async def receive(): raise AssertionError('Unauthorized/malformed preflight received body')
    async def send(message): output.append(message)
    asyncio.run(case.actual.app(scope,receive,send))
    assert next(row['status'] for row in output if row['type'] == 'http.response.start') == status
    assert case.snapshot().authority == before.authority


def test_actual_upload_lease_contention_refuses_before_second_receive(installation_case):
    from app.services.owner_material_upload_lock import UploadLock
    case = installation_case
    lease = UploadLock(case.domain.data_dir)
    output = []
    async def receive(): raise AssertionError('Contending upload allocated a receiving buffer')
    async def send(message): output.append(message)
    try: asyncio.run(case.actual.app(request_scope(case),receive,send))
    finally: lease.close()
    assert next(row['status'] for row in output if row['type'] == 'http.response.start') == 429


def test_receiver_uses_one_deadline_across_fragments(monkeypatch):
    from types import SimpleNamespace
    from app.api import provider_installation as module
    from app.extensions.provider_installation_contracts import InstallationError
    raw = wire(_small_packet())
    readings = iter((0,1,59,61))
    monkeypatch.setattr(module,'time',SimpleNamespace(monotonic=lambda:next(readings)))
    position = 0
    async def receive():
        nonlocal position
        position += 1
        return {'type':'http.request','body':raw[position-1:position],'more_body':True}
    with pytest.raises(InstallationError): asyncio.run(module.receive_packet(receive,len(raw)))
    assert position == 2


def test_second_process_upload_lease_refuses_before_receive(installation_case):
    import subprocess,sys,selectors
    case = installation_case
    code = ('from pathlib import Path; import sys; from app.services.owner_material_upload_lock import UploadLock; '
        'lease=UploadLock(Path(sys.argv[1])); print("owned",flush=True); sys.stdin.read(1); lease.close()')
    process = subprocess.Popen([sys.executable,'-B','-c',code,str(case.domain.data_dir)],
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            assert selector.select(5),'Controlled lease owner did not become ready'
        assert process.stdout.readline() == b'owned\n'
        before = case.snapshot()
        output = []
        async def receive(): raise AssertionError('Second-process contention read packet body')
        async def send(message): output.append(message)
        asyncio.run(case.actual.app(request_scope(case),receive,send))
        assert next(row['status'] for row in output if row['type'] == 'http.response.start') == 429
        assert case.snapshot().authority == before.authority
    finally:
        stdout,stderr = process.communicate(b'1',timeout=5)
        assert process.returncode == 0,(stdout,stderr)


@pytest.mark.parametrize('method,mutation',[('GET','body'),('HEAD','body'),('GET','query'),('HEAD','query')])
def test_installation_read_wire_remains_bodyless_and_queryless(installation_case,method,mutation):
    case = installation_case
    scope = request_scope(case,method=method)
    scope['path'] += '/'+case.packet.header.command_id
    scope['raw_path'] = scope['path'].encode()
    scope['headers'] = [(key,value) for key,value in scope['headers'] if key not in (b'content-length',b'content-type')]
    if mutation == 'body': scope['headers'].append((b'content-length',b'1'))
    else: scope['query_string'] = b'extra=1'
    before = case.snapshot()
    output = []
    async def receive(): raise AssertionError('Invalid read wire consumed body')
    async def send(message): output.append(message)
    asyncio.run(case.actual.app(scope,receive,send))
    assert next(row['status'] for row in output if row['type'] == 'http.response.start') == 400
    assert case.snapshot().authority == before.authority


def test_receiver_exact_effective_group_caps_and_one_byte_over():
    """Transport bytes, not synthetic semantic admission: tighter groups total40MiB."""
    from hashlib import sha256
    from app.domain.refs import canonical_json
    from app.extensions.provider_installation_contracts import ReleasePacket,parse_installation_header,InstallationError
    from app.api.provider_installation import receive_packet
    packet = _small_packet(); value = packet.header.as_dict()
    sizes = [262144,262144,8388608,4194304,8388608,8388608,262144,262144,1048576,1048576,524288,524288]
    objects = [bytes([index])*size for index,size in enumerate(sizes)]
    for row,raw in zip(value['objects'],objects,strict=True):
        row.update(sha256=sha256(raw).hexdigest(),size_bytes=len(raw))
    for index in (12,13):
        raw = bytes([index])*4194304
        objects.append(raw); value['objects'].append({'role':'license_text','sha256':sha256(raw).hexdigest(),'size_bytes':len(raw)})
    tail = sorted(zip(value['objects'][10:],objects[10:]),key=lambda item:(item[0]['role'],item[0]['sha256']))
    value['objects'][10:] = [row for row,_ in tail]; objects[10:] = [raw for _,raw in tail]
    packet = ReleasePacket(parse_installation_header(canonical_json(value)),tuple(objects))
    assert sum(map(len,objects)) == 41943040
    header = PREFIX+len(packet.header.content_bytes).to_bytes(4,'big')+packet.header.content_bytes
    chunks = iter([header,*[raw[start:start+65536] for raw in objects for start in range(0,len(raw),65536)]])
    remaining = len(header)+41943040
    async def receive():
        nonlocal remaining
        raw = next(chunks); remaining -= len(raw)
        return {'type':'http.request','body':raw,'more_body':remaining != 0}
    assert asyncio.run(receive_packet(receive,len(header)+41943040)) == packet
    for role in ('license_text','invocation'):
        changed = packet.header.as_dict()
        next(row for row in changed['objects'] if row['role'] == role)['size_bytes'] += 1
        with pytest.raises(InstallationError): parse_installation_header(canonical_json(changed))
