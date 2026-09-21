"""Authenticated finite binary carrier and two installation browser routes."""
import asyncio
from hashlib import sha256
import re
import time
from uuid import uuid4

from fastapi import APIRouter,Request
from fastapi.responses import JSONResponse,Response
from starlette.concurrency import run_in_threadpool

from ..domain.refs import canonical_json,uuid_string
from ..extensions.provider_installation_contracts import (ERRORS,PREFIX,MEDIA_TYPE,MAX_HEADER,MAX_WIRE,
    InstallationError,ReleasePacket,require,parse_installation_header,parse_installation_reply)
from ..extensions.provider_installation_service import PersistentProviderInstallation
from .first_party import ContributionServices
from .wire import parse_query

PATH = '/api/v1/extensions/provider-installation'
RECEIVE_SECONDS = 60


def installation_services(context,*,dependencies):
    if set(dependencies) != {'deployment-prepare.service','installation-release.source-context'}:
        raise TypeError('Invalid installation dependencies')
    service = PersistentProviderInstallation(context.domain_store,context.owner_authority,
        prepare_service=dependencies['deployment-prepare.service'],release_source=dependencies['installation-release.source-context'])
    return ContributionServices(create_router(service=service,base_path=context.base_path),{'provider-installation.service':service})


def installation_error(error):
    code = getattr(error,'code','unavailable')
    if code not in ERRORS: code = 'unavailable'
    status,message = ERRORS[code]
    return JSONResponse({'code':code,'message':message,'retryability':'not_retryable',
        'affected_refs':[],'correlation_id':str(uuid4())},status_code=status)


def preflight(scope,fields):
    try:
        parse_query(scope.get('query_string',b''),allowed=())
        require('content-encoding' not in fields)
        path,method = scope['path'],scope['method']
        if path == PATH:
            require(method == 'POST' and fields.get('content-type') == MEDIA_TYPE)
            length = fields.get('content-length')
            require(type(length) is str and re.fullmatch('[0-9]{1,10}',length) is not None)
            declared = int(length)
            require(declared <= MAX_WIRE,'too_large')
            require(declared >= 13)
            return declared
        suffix = path[len(PATH)+1:] if path.startswith(PATH+'/') else ''
        require(method in ('GET','HEAD') and '/' not in suffix and fields.get('content-length','0') == '0')
        uuid_string(suffix)
        return 0
    except InstallationError: raise
    except ValueError: raise InstallationError() from None


async def receive_packet(receive,declared):
    require(type(declared) is int and 13 <= declared <= MAX_WIRE)
    deadline = time.monotonic()+RECEIVE_SECONDS
    current,objects = bytearray(),[]
    phase,needed,total,index = 'prefix',12,0,0
    command,descriptors,hasher = None,None,sha256()
    while True:
        remaining = deadline-time.monotonic()
        require(remaining > 0,'unavailable')
        try: message = await asyncio.wait_for(receive(),remaining)
        except TimeoutError: raise InstallationError('unavailable') from None
        if message['type'] == 'http.disconnect': raise asyncio.CancelledError()
        require(message['type'] == 'http.request')
        chunk = message.get('body',b'')
        require(type(chunk) is bytes)
        require(total+len(chunk) <= declared,'too_large')
        total += len(chunk)
        view,position = memoryview(chunk),0
        while position < len(view):
            require(phase != 'done')
            count = min(needed-len(current),len(view)-position)
            fragment = view[position:position+count]
            current.extend(fragment)
            if phase == 'object': hasher.update(fragment)
            position += count
            if len(current) != needed: continue
            if phase == 'prefix':
                require(current[:8] == PREFIX)
                needed = int.from_bytes(current[8:12],'big')
                require(1 <= needed <= MAX_HEADER)
                phase = 'header'
            elif phase == 'header':
                command = parse_installation_header(bytes(current))
                descriptors = command.as_dict()['objects']
                require(12+len(current)+sum(row['size_bytes'] for row in descriptors) == declared)
                phase,needed = 'object',descriptors[0]['size_bytes']
            else:
                require(hasher.hexdigest() == descriptors[index]['sha256'])
                objects.append(bytes(current))
                index += 1
                if index == len(descriptors): phase = 'done'
                else: needed,hasher = descriptors[index]['size_bytes'],sha256()
            current.clear()
        del view
        if not message.get('more_body',False): break
    require(total == declared and phase == 'done' and not current)
    return ReleasePacket(command,tuple(objects))


def create_router(*,service,base_path):
    if type(service) is not PersistentProviderInstallation or type(base_path) is not str:
        raise TypeError('Invalid installation route dependencies')
    router = APIRouter()
    def response(value):
        result = parse_installation_reply(canonical_json(value))
        result['links'] = {key:base_path.rstrip('/')+path for key,path in result['links'].items()}
        raw = canonical_json(result)
        require(len(raw) <= 8192,'unavailable')
        return Response(raw,status_code=200,media_type='application/json')
    @router.post(PATH,name='extensions.provider-installation.execute')
    async def execute(request: Request):
        try:
            result = await request.state.upload_lock.publish(service.execute,
                request.state.authenticated_request,request.state.installation_packet)
            return response(result)
        except InstallationError as error: return installation_error(error)
    @router.api_route(PATH+'/{command_id}',methods=['GET','HEAD'],name='extensions.provider-installation.read')
    async def read(request: Request,command_id: str):
        try: return response(await run_in_threadpool(service.read,request.state.authenticated_request,command_id))
        except InstallationError as error: return installation_error(error)
    return router
