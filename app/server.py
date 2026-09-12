"""Local first-use API; explicit requests may send frozen input to Codex."""

import argparse
import json
import os
import socket
import sqlite3
import stat
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api.conversation_routes import install_conversation_routes
from .api.provider_routes import install_provider_connection_routes
from .api.routes import api_error, initialize_api_v1, install_api_v1
from .api.session import (
    BootstrapReplay,
    BootstrapUnavailable,
    LocalSessionAuthority,
    RequestDenied,
    parse_request_headers,
)
from .codex_connection import CodexConnection
from .ingestion import MAX_FILE_BYTES
from .model_catalog import ModelCatalog
from .model_selection import ModelSelection, ModelSelectionConflict, ModelSelectionError
from .providers import list_providers
from .requests import Requests
from .runtime.budgets import CorruptBudget
from .runtime.worker_dispatch import WorkerDispatchService, WorkerDispatchServiceSlot
from .services.conversation import Conversation
from .services.provider_connections import ProviderConnections
from .services.usage_settings import WorkUsagePolicies
from .speech import (
    MAX_PCM_BYTES,
    Speech,
    SpeechBusy,
    SpeechCancelled,
    SpeechUnavailable,
)
from .speech_sessions import SpeechSessions
from .storage import ConflictError, Store
from .understanding import Understanding, UnderstandingBusy

STATIC = Path(__file__).parent / 'static'
CAPABILITIES = {'understanding': True, 'understanding_provider_ready': False,
                'design_generation': False, 'execution': False}
SECURITY_HEADERS = {
    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
    'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
    'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
}


class LocalBoundary:
    """Exact loopback session boundary plus bounded streaming request bodies."""
    def __init__(self, app, *, sessions):
        self.app, self.sessions = app, sessions

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)

        async def safe_send(message):
            if message['type'] == 'http.response.start':
                replace = {key.lower().encode() for key in SECURITY_HEADERS}
                message['headers'] = [(k, v) for k, v in message['headers'] if k.lower() not in replace]
                message['headers'].extend((key.lower().encode(), value.encode()) for key, value in SECURITY_HEADERS.items())
            elif message['type'] == 'http.response.body' and scope['method'] == 'HEAD':
                # Apply HEAD semantics to success and error responses alike.  Route-level
                # empty responses avoid needless serialization; this boundary is the final
                # guarantee that no body bytes leave the process.
                message = {**message, 'body': b''}
            await send(message)

        async def reject(status, detail, code=None):
            if scope['path'] == '/api/v1' or scope['path'].startswith('/api/v1/'):
                response = api_error(
                    status=status,
                    code=code or ('unauthenticated' if status == 401 else 'access_denied'),
                    message=detail,
                )
            else:
                response = JSONResponse({'detail': detail}, status_code=status)
            await response(scope, receive, safe_send)

        try:
            fields = parse_request_headers(scope['headers'])
        except RequestDenied:
            return await reject(403, '이 화면과 같은 주소에서 다시 요청해 주세요.',
                                'access_denied')
        expected_origin = 'http://' + fields.host
        is_api = scope['path'].startswith('/api/')
        is_exchange = scope['path'] == '/api/session/bootstrap' and scope['method'] == 'POST'
        if is_api and not is_exchange:
            try:
                authenticated = self.sessions.authenticate_request(
                    method=scope['method'], host=fields.host, origin=fields.origin,
                    sec_fetch_site=fields.sec_fetch_site,
                    cookie_header=fields.cookie_header, csrf_token=fields.csrf_token,
                )
            except RequestDenied:
                is_v1 = scope['path'] == '/api/v1' or scope['path'].startswith('/api/v1/')
                status = 403 if not is_v1 else 401
                if is_v1 and scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
                    # A supplied cookie is not proof of authentication.  Distinguish a
                    # live authenticated session with a bad CSRF token (403) from an
                    # absent, invalid, revoked or expired session (401).  Transport
                    # violations remain access denials even when no valid cookie exists.
                    transport_valid = (
                        fields.host in self.sessions.authorities
                        and fields.origin == expected_origin
                        and fields.sec_fetch_site == 'same-origin'
                    )
                    if not transport_valid:
                        status = 403
                    else:
                        try:
                            self.sessions.authenticate_request(
                                method='GET', host=fields.host,
                                origin=fields.origin,
                                sec_fetch_site=fields.sec_fetch_site,
                                cookie_header=fields.cookie_header,
                                csrf_token=None,
                            )
                        except RequestDenied:
                            status = 401
                        else:
                            status = 403
                return await reject(
                    status, '브라우저 세션이 만료됐습니다. DeepTwin 인스턴스에서 다시 열어 주세요.',
                    'access_denied' if status == 403 else 'unauthenticated',
                )
            scope.setdefault('state', {})['authenticated_request'] = authenticated
        elif not is_api:
            if (fields.host not in self.sessions.authorities
                    or fields.origin not in (None, expected_origin)
                    or fields.sec_fetch_site == 'cross-site'):
                return await reject(403, '이 화면과 같은 주소에서 다시 요청해 주세요.',
                                    'access_denied')
        if scope['method'] not in {'GET', 'HEAD', 'OPTIONS'}:
            audio_chunk = scope['path'].startswith('/api/speech/sessions/') and scope['path'].endswith('/chunks')
            limit = MAX_FILE_BYTES if scope['path'].endswith('/files') else MAX_PCM_BYTES if audio_chunk else 128 * 1024
            oversized = ('음성 구간이 너무 깁니다. 음성 입력을 중지한 뒤 다시 시작해 주세요.'
                         if audio_chunk else '전송 가능한 크기를 넘었습니다. 파일은 각각 10MB까지 보관할 수 있습니다.')
            try:
                content_lengths = [value for name, value in scope['headers']
                                   if name.lower() == b'content-length']
                if len(content_lengths) > 1:
                    raise ValueError
                declared = (content_lengths[0].decode('ascii')
                            if content_lengths else '0')
                if not declared.isdecimal() or int(declared) > limit:
                    if declared.isdecimal():
                        return await reject(413, oversized, 'invalid_input')
                    raise ValueError
            except (ValueError, UnicodeDecodeError):
                return await reject(400, '요청 크기를 확인하지 못했습니다.',
                                    'invalid_input')
            chunks, size = [], 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                body = message.get('body', b'')
                size += len(body)
                if size > limit:
                    return await reject(413, oversized, 'invalid_input')
                chunks.append(body)
                if not message.get('more_body', False):
                    break
            consumed = False

            async def replay():
                nonlocal consumed
                if not consumed:
                    consumed = True
                    return {'type': 'http.request', 'body': b''.join(chunks), 'more_body': False}
                return await receive()

            return await self.app(scope, replay, safe_send)
        await self.app(scope, receive, safe_send)


async def payload(request, required, optional=()):
    if request.headers.get('content-type', '').split(';')[0] != 'application/json':
        raise HTTPException(400, 'JSON 요청 형식이 필요합니다.')
    try:
        value = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, '요청을 읽지 못했습니다.') from None
    if not isinstance(value, dict) or not set(required).issubset(value) or set(value) - set(required) - set(optional):
        raise HTTPException(400, '요청 항목을 확인해 주세요.')
    return value


async def usage_payload(request):
    """Read the complete usage-policy object without duplicate-key ambiguity."""
    if (request.query_params
            or request.headers.get('content-type', '').split(';')[0]
            != 'application/json'):
        raise HTTPException(400, '사용 한도 요청 형식을 확인해 주세요.')

    def exact_object(pairs):
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError
            result[key] = item
        return result

    try:
        raw = (await request.body()).decode('utf-8')
        value = json.loads(
            raw,
            object_pairs_hook=exact_object,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError, RecursionError):
        raise HTTPException(
            400, '사용 한도 요청 형식을 확인해 주세요.'
        ) from None
    if type(value) is not dict or set(value) != {'expected_version', 'policy'}:
        raise HTTPException(400, '사용 한도 요청 형식을 확인해 주세요.')
    return value


@contextmanager
def _validated_data_dir(value):
    """Retain the verified directory identity while creating a missing safe tail.

    Rejecting an ancestor only in ``DomainStore`` is too late because the legacy
    constructor may already have followed that link.  Every existing component is opened
    with ``O_NOFOLLOW``; once a component is absent, the remainder is created and opened
    relative to the retained parent descriptor.  The final descriptor stays live until
    ``Store`` has committed its initial schema/event write.
    """
    candidate = Path(os.path.abspath(os.fspath(Path(value))))

    # macOS exposes one fixed OS compatibility alias.  Recognize only its exact link
    # destination; every other symlink, including a caller-created temporary alias, is
    # left visible to the no-follow walk and rejected.
    if len(candidate.parts) > 1 and candidate.parts[1] == 'var':
        try:
            var_metadata = os.lstat('/var')
            var_target = os.readlink('/var') if stat.S_ISLNK(var_metadata.st_mode) else None
        except OSError:
            var_target = None
        if var_target in {'private/var', '/private/var'}:
            candidate = Path('/private/var').joinpath(*candidate.parts[2:])

    if not hasattr(os, 'O_NOFOLLOW'):
        raise RuntimeError('This platform cannot perform a no-follow storage path check')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, 'O_CLOEXEC'):
        flags |= os.O_CLOEXEC
    descriptor = os.open('/', flags)
    try:
        for name in candidate.parts[1:]:
            try:
                child = os.open(name, flags, dir_fd=descriptor)
            except FileNotFoundError:
                # All ancestors that can exist have now been validated.  Create each
                # missing component only through the retained identity, never by pathname.
                try:
                    os.mkdir(name, 0o700, dir_fd=descriptor)
                    child = os.open(name, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise ValueError(
                        'Storage path changed while its directory was being created'
                    ) from exc
            except OSError as exc:
                raise ValueError('Storage path contains an unsafe component') from exc
            os.close(descriptor)
            descriptor = child
        yield candidate, descriptor
    finally:
        os.close(descriptor)


def create_app(data_dir, port=4193, *, codex_factory=None, understanding_model_factory=None,
               understanding_provider_ready=None, model_catalog_factory=None, speech_factory=None,
               runtime_dispatch_resolver=None, worker_dispatch_factory=None,
               credential_vault=None):
    if worker_dispatch_factory is not None and not callable(worker_dispatch_factory):
        raise TypeError("Worker dispatch factory must be a trusted callable")
    with _validated_data_dir(data_dir) as (data_dir, directory_fd):
        store = Store(data_dir, _verified_directory_fd=directory_fd)

    def close_services(bundle, *, suppress=False):
        first_error = None
        for name in ('speech_sessions', 'speech', 'understanding', 'codex'):
            service = bundle.get(name)
            if service is None:
                continue
            try:
                service.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None and not suppress:
            raise first_error

    def build_services():
        built = {}
        try:
            built['codex'] = (codex_factory or CodexConnection)(store)
            built['provider_connections'] = ProviderConnections(
                store, credential_vault=credential_vault,
            )
            if model_catalog_factory is None:
                # Preserve the long-standing two-argument construction seam used by
                # startup identity canaries. API sources are attached explicitly
                # afterwards and never probe credentials or the network.
                built['model_catalog'] = ModelCatalog(store, built['codex'])
            else:
                built['model_catalog'] = model_catalog_factory(store, built['codex'])
            built['provider_connections'].bind_catalog(built['model_catalog'])
            # Bind durable connection authority before publishing any captured
            # source. Reconcile while the shared Store lock is held so lifespan
            # re-entry cannot install an old binding between capture and publish.
            built['provider_connections'].reconcile_catalog()
            built['model_selections'] = ModelSelection(
                store, built['model_catalog'],
            )
            built['speech'] = (speech_factory or Speech)(store)
            built['speech_sessions'] = SpeechSessions(store, built['speech'])
            built['understanding'] = Understanding(
                store, model_factory=understanding_model_factory,
                selection_store=built['model_selections'],
            )
            capabilities = CAPABILITIES.copy()
            if understanding_model_factory is not None:
                # Test providers require explicit opt-in and never probe real providers.
                capabilities['understanding_provider_ready'] = (
                    understanding_provider_ready is True
                )
            elif understanding_provider_ready is not False:
                from .codex_understanding import generation_available
                capabilities['understanding_provider_ready'] = generation_available()
            built['capabilities'] = capabilities
            return built
        except BaseException:
            close_services(built, suppress=True)
            raise

    services = None
    try:
        services = build_services()
        codex = services['codex']
        provider_connections = services['provider_connections']
        model_catalog = services['model_catalog']
        model_selections = services['model_selections']
        speech = services['speech']
        speech_sessions = services['speech_sessions']
        understanding = services['understanding']
        capabilities = services['capabilities']
        requests = Requests(store)
        conversation = Conversation(
            store,
            clock_ms=lambda: time.time_ns() // 1_000_000,
        )
        usage_policies = WorkUsagePolicies(store)
        local_sessions = LocalSessionAuthority(
            {f'127.0.0.1:{port}', f'localhost:{port}'},
            clock=lambda: int(time.monotonic()),
        )
        api_v1 = initialize_api_v1(store, local_sessions)
        worker_dispatch_slot = (
            None if worker_dispatch_factory is None else WorkerDispatchServiceSlot(
                domain_store=api_v1.domain_store,
                permission_gate=api_v1.permission_gate,
                budget_book=api_v1.budget_book,
                runtime_ledger=api_v1.runtime_ledger,
            )
        )
    except BaseException:
        # Startup never downgrades a server-created Store to pathname authority.
        # Revoke retained capabilities even when a downstream constructor fails.
        if services is not None:
            close_services(services, suppress=True)
        store.close_verified_handles()
        raise

    services_open = True

    @asynccontextmanager
    async def lifespan(app):
        nonlocal services, services_open
        nonlocal codex, provider_connections, model_catalog, model_selections
        nonlocal speech, speech_sessions, understanding, capabilities
        # TestClient and embedded hosts may enter one app object more than once. A
        # previous clean shutdown closed both filesystem capabilities and owned
        # services. Reacquire only the original inode pair, then construct a fresh,
        # internally bound service set before accepting another request.
        await run_in_threadpool(store.reopen_verified_handles)
        if not services_open:
            try:
                services = await run_in_threadpool(build_services)
            except BaseException:
                store.close_verified_handles()
                raise
            codex = services['codex']
            provider_connections = services['provider_connections']
            model_catalog = services['model_catalog']
            model_selections = services['model_selections']
            speech = services['speech']
            speech_sessions = services['speech_sessions']
            understanding = services['understanding']
            capabilities = services['capabilities']
            app.state.codex = codex
            app.state.provider_connections = provider_connections
            app.state.model_catalog = model_catalog
            app.state.model_selections = model_selections
            app.state.speech = speech
            app.state.speech_sessions = speech_sessions
            app.state.understanding = understanding
            services_open = True
        worker_dispatch = None
        dispatch_published = False
        try:
            if worker_dispatch_factory is not None:
                await run_in_threadpool(
                    api_v1.runtime_ledger.reconcile_startup,
                    str(uuid4()),
                    observed_owners={},
                )
                worker_dispatch = await run_in_threadpool(
                    worker_dispatch_factory, api_v1
                )
                if type(worker_dispatch) is not WorkerDispatchService:
                    raise TypeError("Worker dispatch factory returned an invalid service")
                worker_dispatch.assert_components(
                    domain_store=api_v1.domain_store,
                    permission_gate=api_v1.permission_gate,
                    budget_book=api_v1.budget_book,
                    runtime_ledger=api_v1.runtime_ledger,
                )
                await run_in_threadpool(worker_dispatch.start)
                worker_dispatch_slot.publish(worker_dispatch)
                dispatch_published = True
                app.state.worker_dispatch = worker_dispatch
            yield
        finally:
            try:
                if worker_dispatch is not None:
                    try:
                        if dispatch_published:
                            worker_dispatch_slot.clear(worker_dispatch)
                    finally:
                        app.state.worker_dispatch = None
                        await run_in_threadpool(worker_dispatch.close)
            finally:
                try:
                    # A failed close must not skip terminating the other owned workers.
                    await run_in_threadpool(close_services, services)
                finally:
                    services_open = False
                    await run_in_threadpool(store.close_verified_handles)

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.store, app.state.codex = store, codex
    app.state.provider_connections = provider_connections
    app.state.conversation = conversation
    app.state.usage_policies = usage_policies
    app.state.understanding = understanding
    app.state.model_catalog, app.state.model_selections = model_catalog, model_selections
    app.state.speech, app.state.speech_sessions = speech, speech_sessions
    app.state.local_sessions = local_sessions
    app.state.domain_store = api_v1.domain_store
    app.state.permission_host = api_v1.permission_host
    app.state.permission_gate = api_v1.permission_gate
    app.state.budget_book = api_v1.budget_book
    app.state.runtime_ledger = api_v1.runtime_ledger
    app.state.root_commands = api_v1.root_commands
    app.state.worker_dispatch = None
    app.state.worker_dispatch_slot = worker_dispatch_slot
    app.state.api_v1 = api_v1
    app.add_middleware(LocalBoundary, sessions=local_sessions)
    install_api_v1(
        app,
        components=api_v1,
        runtime_dispatch_resolver=runtime_dispatch_resolver,
        worker_dispatch_slot=worker_dispatch_slot,
    )
    install_conversation_routes(app, conversation=conversation)
    install_provider_connection_routes(app, connections=provider_connections)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        if request.url.path == '/api/v1' or request.url.path.startswith('/api/v1/'):
            if error.status_code == 404:
                return api_error(
                    status=404, code='not_found',
                    message='요청한 API 대상을 찾지 못했습니다.',
                )
            return api_error(
                status=error.status_code, code='invalid_input',
                message='이 API에서 지원하지 않는 요청입니다.',
            )
        return JSONResponse({'detail': error.detail}, status_code=error.status_code,
                            headers=error.headers)

    @app.exception_handler(ConflictError)
    async def conflict(_, error):
        return JSONResponse({'detail': '다른 화면에서 이 업무가 변경되었습니다. 현재 입력을 복사한 뒤 저장된 업무를 다시 열어 주세요.'}, status_code=409)

    @app.exception_handler(KeyError)
    async def missing(_, error):
        return JSONResponse({'detail': '해당 업무 또는 파일을 찾지 못했습니다.'}, status_code=404)

    @app.exception_handler(CorruptBudget)
    async def corrupt_budget(_, error):
        return JSONResponse(
            {'detail': '저장된 사용 한도를 안전하게 확인하지 못했습니다.'},
            status_code=503,
        )

    @app.exception_handler(ValueError)
    async def invalid(_, error):
        return JSONResponse({'detail': '입력이나 파일 형식을 확인해 주세요. 설명은 20,000자, 파일은 각 10MB·업무당 20개까지 가능합니다.'}, status_code=400)

    @app.exception_handler(ModelSelectionError)
    async def invalid_selection(_, error):
        return JSONResponse({'detail': str(error)}, status_code=400)

    @app.exception_handler(ModelSelectionConflict)
    async def selection_conflict(_, error):
        return JSONResponse({'detail': str(error)}, status_code=409)

    @app.exception_handler(SpeechUnavailable)
    async def speech_unavailable(_, error):
        return JSONResponse({'detail': str(SpeechUnavailable())}, status_code=503)

    @app.exception_handler(SpeechBusy)
    async def speech_busy(_, error):
        return JSONResponse({'detail': str(SpeechBusy())}, status_code=503)

    @app.exception_handler(SpeechCancelled)
    async def speech_cancelled(_, error):
        return JSONResponse({'detail': '이 음성 입력은 중단됐습니다. 이미 입력한 글은 유지됩니다.'}, status_code=400)

    async def storage_error(_, error):
        return JSONResponse({'detail': 'DeepTwin 인스턴스의 업무 저장소에 저장하지 못했습니다. 입력을 유지한 채 다시 시도해 주세요.'}, status_code=503)
    app.add_exception_handler(OSError, storage_error)
    app.add_exception_handler(sqlite3.Error, storage_error)

    @app.exception_handler(UnderstandingBusy)
    async def understanding_busy(_, error):
        return JSONResponse({'detail': str(error)}, status_code=503)

    @app.post('/api/session/bootstrap', status_code=201)
    async def session_bootstrap(request: Request):
        value = await payload(request, {'capability'})
        fields = parse_request_headers(request.scope['headers'])
        try:
            exchange = local_sessions.exchange_bootstrap(
                value['capability'], method=request.method, host=fields.host,
                origin=fields.origin, sec_fetch_site=fields.sec_fetch_site)
        except (RequestDenied, BootstrapUnavailable, BootstrapReplay):
            raise HTTPException(403, '브라우저 세션을 확인하지 못했습니다. DeepTwin 인스턴스에서 다시 열어 주세요.') from None
        response = JSONResponse(
            {'csrf_token': exchange.csrf_token, 'expires_at': exchange.expires_at},
            status_code=201,
        )
        response.headers['Set-Cookie'] = exchange.cookie_header
        return response

    @app.get('/api/bootstrap')
    def bootstrap():
        return dict(works=store.list_work(), capabilities=capabilities.copy(), providers=provider_list())

    @app.get('/api/session/csrf')
    def rotate_csrf(request: Request):
        authenticated = request.scope.get('state', {}).get('authenticated_request')
        try:
            return {'csrf_token': local_sessions.rotate_csrf(authenticated)}
        except RequestDenied:
            raise HTTPException(403, '브라우저 세션이 만료됐습니다. DeepTwin 인스턴스에서 다시 열어 주세요.') from None

    def provider_list():
        return [
            {**provider, **codex.snapshot()}
            if provider['id'] == 'codex' else provider
            for provider in list_providers()
        ]

    @app.get('/api/providers')
    def providers():
        return {'providers': provider_list()}

    @app.get('/api/speech')
    def speech_status():
        return speech.snapshot()

    @app.post('/api/speech/sessions', status_code=201)
    async def start_speech(request: Request):
        value = await payload(request, {'work_id', 'revision'})
        if not isinstance(value['work_id'], str) or not 0 < len(value['work_id']) <= 100:
            raise HTTPException(400, '음성을 입력할 업무를 확인해 주세요.')
        return await run_in_threadpool(speech_sessions.start, value['work_id'], value['revision'])

    @app.post('/api/speech/sessions/{session_id}/chunks')
    async def transcribe_speech(session_id: str, request: Request):
        if (request.headers.get('content-type', '').split(';')[0] != 'audio/pcm'
                or set(request.query_params) != {'sequence', 'utterance', 'final'}
                or len(list(request.query_params.multi_items())) != 3):
            raise HTTPException(400, '음성 구간의 전송 형식을 확인하지 못했습니다.')
        raw_sequence, raw_utterance, raw_final = (request.query_params[key] for key in ('sequence', 'utterance', 'final'))
        if (any(not value.isascii() or not value.isdecimal() or len(value) > 3
                for value in (raw_sequence, raw_utterance)) or raw_final not in {'true', 'false'}):
            raise HTTPException(400, '음성 구간의 순서와 상태를 확인하지 못했습니다.')
        body = await request.body()
        try:
            return await run_in_threadpool(speech_sessions.transcribe, session_id,
                int(raw_sequence), int(raw_utterance), raw_final == 'true', body)
        except CorruptBudget:
            raise
        except ValueError:
            raise HTTPException(400, '이 음성 구간을 처리할 수 없습니다. 입력한 글을 유지한 채 음성 입력을 다시 시작해 주세요.') from None

    @app.post('/api/speech/sessions/{session_id}/close')
    async def close_speech(session_id: str, request: Request):
        await payload(request, set())
        return await run_in_threadpool(speech_sessions.close_session, session_id)

    def known_provider(provider):
        if provider not in {'codex', 'claude'}:
            raise HTTPException(404, '해당 모델 제공자를 찾지 못했습니다.')

    def catalog_mode(request, provider):
        pairs = list(request.query_params.multi_items())
        if len(pairs) > 1 or any(key != 'mode' for key, _ in pairs):
            raise HTTPException(400, '모델 연결 방식을 하나만 선택해 주세요.')
        mode = pairs[0][1] if pairs else ('api' if provider == 'claude' else 'subscription')
        if (provider, mode) not in {
                ('codex', 'subscription'), ('codex', 'api'), ('claude', 'api')}:
            raise HTTPException(400, '이 제공자에서 지원하지 않는 연결 방식입니다.')
        return mode

    @app.get('/api/model-catalogs/{provider}')
    def catalog(provider: str, request: Request):
        known_provider(provider)
        return model_catalog.snapshot(provider, catalog_mode(request, provider))

    @app.post('/api/model-catalogs/{provider}/refresh')
    async def refresh_catalog(provider: str, request: Request):
        known_provider(provider)
        mode = catalog_mode(request, provider)
        await payload(request, set())
        return await run_in_threadpool(model_catalog.refresh, provider, mode)

    @app.get('/api/providers/codex')
    def codex_status():
        return codex.snapshot()

    @app.post('/api/providers/codex/check')
    async def codex_check(request: Request):
        await payload(request, set())
        return await run_in_threadpool(codex.check)

    @app.post('/api/providers/codex/login')
    async def codex_login(request: Request):
        await payload(request, set())
        return await run_in_threadpool(codex.start_login)

    @app.post('/api/providers/codex/login/cancel')
    async def codex_cancel(request: Request):
        value = await payload(request, {'login_id'})
        login_id = value['login_id']
        if not isinstance(login_id, str) or not 0 < len(login_id) <= 128:
            raise HTTPException(400, '취소할 로그인 요청을 확인하지 못했습니다.')
        return await run_in_threadpool(codex.cancel_login, login_id)

    @app.get('/api/works')
    def works():
        return store.list_work()

    @app.post('/api/works', status_code=201)
    async def create(request: Request):
        value = await payload(request, {'text'})
        return await run_in_threadpool(store.create_work, value['text'])

    @app.get('/api/works/{work_id}')
    def work(work_id: str):
        return store.get_work(work_id)

    @app.get('/api/works/{work_id}/model-selection')
    def selected_model(work_id: str):
        return model_selections.get(work_id)

    @app.put('/api/works/{work_id}/model-selection')
    async def select_model(work_id: str, request: Request):
        value = await payload(request, {'expected_version', 'selection'})
        return await run_in_threadpool(model_selections.save, work_id,
                                      value['expected_version'], value['selection'])

    @app.get('/api/works/{work_id}/model-policy')
    def model_policy(work_id: str):
        return model_selections.get_policy(work_id)

    @app.put('/api/works/{work_id}/model-policy')
    async def save_model_policy(work_id: str, request: Request):
        value = await payload(request, {
            'expected_version', 'default', 'purpose_overrides', 'agent_overrides',
        })
        return await run_in_threadpool(
            model_selections.save_policy,
            work_id,
            value['expected_version'],
            default=value['default'],
            purpose_overrides=value['purpose_overrides'],
            agent_overrides=value['agent_overrides'],
        )

    @app.get('/api/works/{work_id}/usage-policies/{profile}')
    def usage_policy(work_id: str, profile: str, request: Request):
        if request.query_params:
            raise HTTPException(400, '사용 한도 요청 형식을 확인해 주세요.')
        return usage_policies.get(work_id, profile)

    @app.put('/api/works/{work_id}/usage-policies/{profile}')
    async def save_usage_policy(work_id: str, profile: str, request: Request):
        value = await usage_payload(request)
        try:
            return await run_in_threadpool(
                usage_policies.save,
                work_id,
                profile,
                value['expected_version'],
                value['policy'],
            )
        except ValueError:
            policy = value.get('policy')
            legacy_api = (
                type(policy) is dict and policy.get('provider_mode') == 'api'
            )
            api_lanes = (
                policy.get('api_lanes', []) if type(policy) is dict else []
            )
            invalid_api_money = legacy_api or (
                type(api_lanes) is list
                and any(
                    type(lane) is dict and lane.get('mode') == 'api'
                    for lane in api_lanes
                )
            )
            if invalid_api_money:
                raise HTTPException(
                    400,
                    'API 연결의 통화와 0보다 큰 비용 한도를 확인해 주세요.',
                ) from None
            raise HTTPException(
                400, '사용 한도 값을 확인해 주세요.'
            ) from None

    @app.put('/api/works/{work_id}')
    async def update(work_id: str, request: Request):
        value = await payload(request, {'text', 'expected_revision'})
        return await run_in_threadpool(store.update_work, work_id, value['text'], value['expected_revision'])

    @app.post('/api/works/{work_id}/files', status_code=201)
    async def upload(work_id: str, request: Request):
        name = request.query_params.get('name', '')
        raw_revision = request.query_params.get('expected_revision', '')
        if not raw_revision.isascii() or not raw_revision.isdecimal() or len(raw_revision) > 10:
            raise HTTPException(400, '자료를 추가할 업무의 저장본을 확인하지 못했습니다.')
        expected_revision = int(raw_revision)
        body = await request.body()
        await run_in_threadpool(store.add_file, work_id, name, body,
                                request.headers.get('content-type', 'application/octet-stream'), expected_revision)
        # Return the snapshot this upload committed, not a possibly newer
        # text/revision from another tab between commit and response.
        return await run_in_threadpool(store.get_revision, work_id, expected_revision + 1)

    @app.get('/api/works/{work_id}/files/{file_id}')
    def download(work_id: str, file_id: str):
        metadata, body = store.read_file(work_id, file_id)
        return Response(body, media_type='application/octet-stream', headers={
            'Content-Disposition': "attachment; filename=download; filename*=UTF-8''" + quote(metadata['name'], safe='')})

    @app.post('/api/works/{work_id}/design-requests', status_code=201)
    async def prepare(work_id: str, request: Request):
        value = await payload(request, {'revision', 'provider', 'mode'})
        return await run_in_threadpool(requests.create, work_id, value['revision'], value['provider'], value['mode'])

    @app.get('/api/works/{work_id}/design-requests')
    def design_requests(work_id: str):
        return requests.list_for(work_id)

    @app.post('/api/works/{work_id}/understanding-requests', status_code=202)
    async def understand(work_id: str, request: Request):
        value = await payload(request, {'revision', 'request_key', 'allow_transfer', 'model_selection_version'})
        return await run_in_threadpool(understanding.create, work_id, value['revision'],
                                      value['request_key'], value['allow_transfer'], value['model_selection_version'])

    @app.get('/api/works/{work_id}/understanding-requests')
    def understandings(work_id: str):
        return understanding.list_for(work_id)

    @app.post('/api/works/{work_id}/understanding-requests/{request_id}/cancel')
    async def cancel_understanding(work_id: str, request_id: str, request: Request):
        await payload(request, set())
        return await run_in_threadpool(understanding.cancel, work_id, request_id)

    def asset(name, media_type):
        path = STATIC / name
        if not path.is_file():
            raise HTTPException(404, '화면을 아직 준비하지 못했습니다.')
        return FileResponse(path, media_type=media_type)

    @app.get('/')
    def index():
        return asset('index.html', 'text/html')

    @app.get('/app.mjs')
    def javascript():
        return asset('app.mjs', 'application/javascript')

    @app.get('/styles.css')
    def css():
        return asset('styles.css', 'text/css')

    @app.get('/audio-capture-worklet.mjs')
    def speech_worklet():
        return asset('audio-capture-worklet.mjs', 'application/javascript')

    @app.get('/speech-input.mjs')
    def speech_input():
        return asset('speech-input.mjs', 'application/javascript')

    @app.get('/chat.mjs')
    def chat_module():
        return asset('chat.mjs', 'application/javascript')

    @app.get('/settings.mjs')
    def settings_module():
        return asset('settings.mjs', 'application/javascript')

    return app


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description='DeepTwin local first-use development server')
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4193)
    args = parser.parse_args()
    # Binding before printing supports ephemeral test ports without a port race.
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('127.0.0.1', args.port))
    port = sock.getsockname()[1]
    server = create_app(args.data_dir, port=port)
    launch = server.state.local_sessions.mint_bootstrap()
    print(f'DEEPTWIN_URL=http://127.0.0.1:{port}/#bootstrap='
          f'{quote(launch.capability, safe="")}', flush=True)
    uvicorn.Server(uvicorn.Config(server, log_level='warning', access_log=False)).run(sockets=[sock])


if __name__ == '__main__':
    main()
