"""Service-client command adapters and the owner-only durable lifecycle routes.

`service_client_services` is the build-installed `service-clients-v1` contribution: the
owner creates (secret shown once), lists, reads, rotates and revokes durable scoped
clients from an authenticated browser session with CSRF. The same contribution publishes
the bearer authenticator the web boundary uses for routes whose descriptor declares
`browser_session_or_service_bearer`, and only on the portable HTTPS profile.
"""

import re
import secrets
import time
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from ..domain.refs import uuid_string
from ..domain.request_identity import AuthenticatedRequest
from ..domain.schemas import Actor
from ..services.command_clients import (
    CommandPrincipal,
    CommandService,
    CommandServiceDenied,
)
from ..services.service_client_auth import (
    IndependentTokenBuckets,
    ServiceClientAuthenticator,
)
from ..services.service_clients import (
    CorruptServiceClient,
    PersistentServiceClientRegistry,
    ServiceClientDenied,
    ServiceClientRegistry,
)
from .wire import (
    WireInputError,
    WireLimits,
    parse_json_object,
    parse_query,
    parse_singleton_headers,
)


class ServiceRequestDenied(PermissionError):
    pass


class BrowserCommandSurface:
    def __init__(self, *, service, verify_owner):
        if type(service) is not CommandService or not callable(verify_owner):
            raise TypeError("Browser command surface requires trusted dependencies")
        self._service = service
        self._verify_owner = verify_owner

    def submit(self, value, *, owner_request):
        candidate = owner_request
        owner_request = None
        failed = False
        actor = None
        try:
            actor = self._verify_owner(candidate)
        except Exception:  # noqa: BLE001 - sanitize the owner-verification boundary
            failed = True
        candidate = None
        if failed or type(actor) is not Actor or actor.kind != "human":
            try:
                self._service.deny_delivery()
            except CommandServiceDenied:
                pass
            raise ServiceRequestDenied("Authenticated browser owner required")
        try:
            return self._service.submit_mapping(value, CommandPrincipal.human(actor))
        except CommandServiceDenied:
            raise ServiceRequestDenied("Browser command was denied") from None


class HeadlessCommandSurface:
    """Strict HTTPS bearer adapter with no cookie/CORS/session fallback."""

    def __init__(self, *, service, clients):
        if type(service) is not CommandService or type(clients) not in {
            ServiceClientRegistry,
            PersistentServiceClientRegistry,
        }:
            raise TypeError("Headless command surface requires trusted dependencies")
        self._service = service
        self._clients = clients

    def submit(self, value, *, authorization, network_profile, tls, cookie_header):
        candidate = authorization
        authorization = None
        supplied_cookie = cookie_header
        cookie_header = None
        valid = (tls is True and supplied_cookie is None and type(candidate) is str
                 and candidate.startswith("Bearer ") and candidate.count(" ") == 1
                 and not any(character in candidate for character in "\r\n,"))
        if not valid:
            candidate = supplied_cookie = None
            try:
                self._service.deny_delivery()
            except CommandServiceDenied:
                pass
            raise ServiceRequestDenied("Headless requests require one TLS bearer credential")
        supplied_cookie = None
        secret = candidate[7:]
        candidate = None
        if not secret:
            try:
                self._service.deny_delivery()
            except CommandServiceDenied:
                pass
            raise ServiceRequestDenied("Headless bearer credential is empty")
        try:
            authenticated = self._clients.authenticate(
                secret, network_profile=network_profile,
            )
            secret = None
            principal = CommandPrincipal.service_client(
                client_id=authenticated.client_id,
                scopes=authenticated.scopes,
                expires_at=authenticated.expires_at,
            )
            return self._service.submit_mapping(value, principal)
        except (ServiceClientDenied, CommandServiceDenied):
            secret = None
            raise ServiceRequestDenied("Headless command was denied") from None


_LIFECYCLE_LIMITS = WireLimits(
    max_bytes=8_192,
    max_depth=4,
    max_items=128,
    max_members=8,
    max_string_bytes=1_024,
)


def _error(status, code, message):
    return JSONResponse(
        {
            "code": code,
            "message": message,
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


def _owner_request(request, verify_owner):
    candidate = request.scope.get("state", {}).get("authenticated_request")
    if candidate is None:
        return None
    try:
        actor = verify_owner(candidate)
    except Exception:  # noqa: BLE001 - sanitize the session-verification boundary
        return None
    if type(actor) is not Actor or actor.kind != "human":
        return None
    return candidate


def _raw_query(request, *, allowed=(), required=()):
    try:
        return parse_query(
            request.scope.get("query_string", b""),
            allowed=allowed,
            required=required,
            max_bytes=1_024,
        )
    except (TypeError, ValueError, WireInputError):
        return None


async def _json_body(request, *, required, field_types):
    try:
        headers = parse_singleton_headers(
            request.scope.get("headers", ()),
            names=("content-type",),
            required=("content-type",),
            max_value_bytes=64,
        )
        if headers["content-type"] != "application/json":
            raise WireInputError("invalid request wire format")
        return parse_json_object(
            await request.body(),
            required=required,
            field_types=field_types,
            limits=_LIFECYCLE_LIMITS,
        )
    except (TypeError, ValueError, WireInputError):
        return None


def _public(record):
    return {
        "client_id": record.client_id,
        "owner_id": record.owner_id,
        "name": record.name,
        "scopes": list(record.scopes),
        "allowed_network_profile": record.allowed_network_profile,
        "created_at": record.created_at,
        "expires_at": record.expires_at,
        "revision": record.revision,
        "state": record.state,
    }


PATH = "/api/v1/service-clients"
# the only network profile on which a bearer is ever admitted (contracts/api.md §1, ADR-010)
BEARER_NETWORK_PROFILE = "portable_https"
_CREATE_FIELDS = ("client_id", "name", "scopes", "allowed_network_profile", "expires_at")
_CLIENT_PATH = re.compile(r"^/api/v1/service-clients/([^/]+)(?:/(rotate|revoke))?$")
# Provisional bounded rate buckets (contracts/api.md requires independent client, source
# and route buckets but fixes no numbers; recorded as an open owner decision).
RATE_CAPACITY = 60
RATE_REFILL_INTERVAL_MS = 1_000
RATE_MAX_KEYS = 1_024
RATE_IDLE_TTL_MS = 600_000


def is_service_clients_path(path):
    return path == PATH or path.startswith(PATH + "/")


def preflight(scope, body):
    """Cheap exact wire admission before any auth state, storage or entropy is touched."""
    path, method = scope["path"], scope["method"]
    raw_query = scope.get("query_string", b"")
    if path == PATH:
        if method == "GET":
            parse_query(raw_query, allowed=("cursor", "limit"), max_bytes=1_024)
            if body:
                raise WireInputError("invalid request wire format")
            return
        if method != "POST":
            raise WireInputError("invalid request wire format")
        parse_query(raw_query, allowed=())
        parse_json_object(body, required=_CREATE_FIELDS, field_types={
            "client_id": str, "name": str, "scopes": list,
            "allowed_network_profile": str, "expires_at": int,
        }, limits=_LIFECYCLE_LIMITS)
        return
    match = _CLIENT_PATH.fullmatch(path)
    if match is None:
        raise WireInputError("invalid request wire format")
    parse_query(raw_query, allowed=())
    try:
        uuid_string(match.group(1))
    except (TypeError, ValueError):
        raise WireInputError("invalid request wire format") from None
    if match.group(2) is None:
        if method != "GET" or body:
            raise WireInputError("invalid request wire format")
        return
    if method != "POST":
        raise WireInputError("invalid request wire format")
    parse_json_object(body, required=("expected_revision",),
                      field_types={"expected_revision": int}, limits=_LIFECYCLE_LIMITS)


def service_client_services(context):
    """The fixed `service-clients-v1` contribution bound to the deployment's own profile."""
    from ..services.owner_auth import OwnerAuthError
    from .first_party import ContributionServices

    authority = context.owner_authority
    network_profile = authority.profile.mode

    def verify_owner(candidate):
        if type(candidate) is not AuthenticatedRequest or (
                not candidate.is_read and not candidate.csrf_verified):
            raise OwnerAuthError("unauthenticated")
        return authority.authenticate_bound(candidate.session)

    registry = PersistentServiceClientRegistry(
        context.domain_store._legacy_store,
        verify_owner=verify_owner,
        # recovery revokes every client inside the deployment reconciliation transaction
        verify_recovery=lambda _candidate: False,
        clock=lambda: time.time_ns() // 1_000_000_000,
        random_bytes=secrets.token_bytes,
    )
    authenticator = ServiceClientAuthenticator(
        registry=registry,
        limiter=IndependentTokenBuckets(
            clock_ms=lambda: time.monotonic_ns() // 1_000_000,
            capacity=RATE_CAPACITY,
            refill_interval_ms=RATE_REFILL_INTERVAL_MS,
            max_keys_per_dimension=RATE_MAX_KEYS,
            idle_ttl_ms=RATE_IDLE_TTL_MS,
        ),
    )
    return ContributionServices(
        create_router(registry=registry, verify_owner=verify_owner,
                      network_profile=network_profile),
        {"service-clients.registry": registry,
         "service-clients.authenticator": authenticator},
    )


def create_router(*, registry, verify_owner, network_profile=None):
    """Build the passive fixed route contribution used by the core composer.

    With ``network_profile`` (the supported factory), a client can be created only on the
    portable HTTPS profile, bound to exactly that profile, and granted only scopes some
    composed route declares for a bearer; nothing else could ever admit it.
    """
    if type(registry) is not PersistentServiceClientRegistry:
        raise TypeError("service-client routes require the persistent registry")
    if not callable(verify_owner):
        raise TypeError("service-client routes require owner verification")
    if network_profile is not None and type(network_profile) is not str:
        raise TypeError("service-client routes require the deployment network profile")
    router = APIRouter()

    def grantable(request, value):
        if network_profile is None:
            return True
        composition = getattr(request.app.state, "route_composition", None)
        scopes = () if composition is None else composition.bearer_scopes()
        return (
            network_profile == BEARER_NETWORK_PROFILE
            and value["allowed_network_profile"] == network_profile
            and bool(value["scopes"])
            and all(type(item) is str and item in scopes for item in value["scopes"])
        )

    @router.get("/api/v1/service-clients")
    async def list_clients(request: Request):
        owner_request = _owner_request(request, verify_owner)
        if owner_request is None:
            return _error(401, "unauthenticated", "브라우저 소유자 세션이 필요합니다.")
        query = _raw_query(request, allowed=("cursor", "limit"))
        if query is None:
            return _error(400, "invalid_input", "목록 요청 형식을 확인해 주세요.")
        limit_text = query.get("limit", "50")
        if (
            not limit_text.isascii()
            or not limit_text.isdecimal()
            or (len(limit_text) > 1 and limit_text.startswith("0"))
            or not 1 <= int(limit_text) <= 100
        ):
            return _error(400, "invalid_input", "목록 요청 형식을 확인해 주세요.")
        try:
            page = await run_in_threadpool(
                registry.list_for_owner,
                owner_request,
                after_client_id=query.get("cursor"),
                limit=int(limit_text),
            )
            return JSONResponse(page, headers={"Cache-Control": "no-store"})
        except ServiceClientDenied:
            return _error(400, "invalid_input", "목록 요청 형식을 확인해 주세요.")
        except CorruptServiceClient:
            return _error(503, "state_unavailable", "저장된 클라이언트를 확인하지 못했습니다.")

    @router.post("/api/v1/service-clients", status_code=201)
    async def issue_client(request: Request):
        owner_request = _owner_request(request, verify_owner)
        if owner_request is None:
            return _error(401, "unauthenticated", "브라우저 소유자 세션이 필요합니다.")
        if _raw_query(request) is None:
            return _error(400, "invalid_input", "클라이언트 요청 형식을 확인해 주세요.")
        value = await _json_body(
            request,
            required=(
                "client_id",
                "name",
                "scopes",
                "allowed_network_profile",
                "expires_at",
            ),
            field_types={
                "client_id": str,
                "name": str,
                "scopes": list,
                "allowed_network_profile": str,
                "expires_at": int,
            },
        )
        if value is None:
            return _error(400, "invalid_input", "클라이언트 요청 형식을 확인해 주세요.")
        if not grantable(request, value):
            return _error(422, "invalid_state", "클라이언트를 만들 수 없습니다.")
        try:
            issued = await run_in_threadpool(
                registry.issue,
                owner_request,
                client_id=value["client_id"],
                name=value["name"],
                scopes=value["scopes"],
                allowed_network_profile=value["allowed_network_profile"],
                expires_at=value["expires_at"],
            )
        except ServiceClientDenied:
            return _error(422, "invalid_state", "클라이언트를 만들 수 없습니다.")
        except CorruptServiceClient:
            return _error(503, "state_unavailable", "저장 상태를 확인하지 못했습니다.")
        try:
            response = JSONResponse(
                {
                    "client": _public(issued.client),
                    "secret": issued.secret,
                    "secret_available_once": True,
                },
                status_code=201,
                headers={"Cache-Control": "no-store"},
            )
        finally:
            issued = None
        return response

    @router.get("/api/v1/service-clients/{client_id}")
    async def get_client(client_id: str, request: Request):
        owner_request = _owner_request(request, verify_owner)
        if owner_request is None:
            return _error(401, "unauthenticated", "브라우저 소유자 세션이 필요합니다.")
        if _raw_query(request) is None:
            return _error(400, "invalid_input", "클라이언트 요청 형식을 확인해 주세요.")
        try:
            snapshot = await run_in_threadpool(registry.snapshot, owner_request, client_id)
            return JSONResponse(snapshot, headers={"Cache-Control": "no-store"})
        except ServiceClientDenied:
            return _error(404, "not_found", "클라이언트를 찾지 못했습니다.")
        except CorruptServiceClient:
            return _error(503, "state_unavailable", "저장 상태를 확인하지 못했습니다.")

    async def revision_body(request):
        if _raw_query(request) is None:
            return None
        return await _json_body(
            request,
            required=("expected_revision",),
            field_types={"expected_revision": int},
        )

    @router.post("/api/v1/service-clients/{client_id}/rotate")
    async def rotate_client(client_id: str, request: Request):
        owner_request = _owner_request(request, verify_owner)
        if owner_request is None:
            return _error(401, "unauthenticated", "브라우저 소유자 세션이 필요합니다.")
        value = await revision_body(request)
        if value is None:
            return _error(400, "invalid_input", "회전 요청 형식을 확인해 주세요.")
        try:
            issued = await run_in_threadpool(
                registry.rotate,
                owner_request,
                client_id,
                expected_revision=value["expected_revision"],
            )
        except ServiceClientDenied:
            return _error(409, "state_conflict", "현재 리비전에서는 회전할 수 없습니다.")
        except CorruptServiceClient:
            return _error(503, "state_unavailable", "저장 상태를 확인하지 못했습니다.")
        try:
            response = JSONResponse(
                {
                    "client": _public(issued.client),
                    "secret": issued.secret,
                    "secret_available_once": True,
                },
                headers={"Cache-Control": "no-store"},
            )
        finally:
            issued = None
        return response

    @router.post("/api/v1/service-clients/{client_id}/revoke")
    async def revoke_client(client_id: str, request: Request):
        owner_request = _owner_request(request, verify_owner)
        if owner_request is None:
            return _error(401, "unauthenticated", "브라우저 소유자 세션이 필요합니다.")
        value = await revision_body(request)
        if value is None:
            return _error(400, "invalid_input", "폐기 요청 형식을 확인해 주세요.")
        try:
            record = await run_in_threadpool(
                registry.revoke,
                owner_request,
                client_id,
                expected_revision=value["expected_revision"],
            )
        except ServiceClientDenied:
            return _error(409, "state_conflict", "현재 리비전에서는 폐기할 수 없습니다.")
        except CorruptServiceClient:
            return _error(503, "state_unavailable", "저장 상태를 확인하지 못했습니다.")
        return JSONResponse(_public(record), headers={"Cache-Control": "no-store"})

    return router


__all__ = [
    "BEARER_NETWORK_PROFILE",
    "PATH",
    "BrowserCommandSurface",
    "HeadlessCommandSurface",
    "ServiceRequestDenied",
    "create_router",
    "is_service_clients_path",
    "preflight",
    "service_client_services",
]
