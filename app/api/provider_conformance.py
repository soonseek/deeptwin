"""Authenticated browser adapter for fixed private-provider conformance."""

from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..domain.refs import canonical_json, uuid_string
from ..extensions.provider_conformance_contracts import (
    ConformanceError,
    parse_command,
    parse_reply,
)
from ..extensions.provider_conformance_service import PersistentProviderConformance
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query


PATH = "/api/v1/extensions/provider-conformance"
_STATUS = {"invalid_input": 400, "unauthenticated": 401, "access_denied": 403,
           "not_found": 404, "conflict": 409, "too_large": 413, "capacity": 429,
           "unavailable": 503}


def conformance_services(context, *, dependencies):
    if set(dependencies) != {"deployment-prepare.service",
                            "deployment-provider.source-context"}:
        raise TypeError("Invalid provider conformance dependencies")
    prepare = dependencies["deployment-prepare.service"]
    source = dependencies["deployment-provider.source-context"]
    service = PersistentProviderConformance(context.domain_store, context.owner_authority,
        prepare_service=prepare, source_context=source)
    # T087 -> T090: the owner's qualification of the shipped provider-transport manifest
    # from a matched verified run; the gateway document is published through the
    # credential gateway client when the host attached one (no HTTP route yet)
    from ..extensions.provider_transport_qualification import PersistentTransportQualification

    attachment = context.credential_gateway
    publisher = None if attachment is None else getattr(attachment.client, "bind_transport", None)
    qualification = PersistentTransportQualification(service, publisher=publisher)
    return ContributionServices(create_router(service=service, base_path=context.base_path),
        {"provider-conformance.service": service,
         "provider-transport-qualification.service": qualification})


def conformance_error(error):
    code = error.code if error.code in _STATUS else "unavailable"
    return JSONResponse({"code": code,
        "message": "Provider conformance request could not be admitted",
        "retryability": "not_retryable", "affected_refs": [],
        "correlation_id": str(uuid4())}, status_code=_STATUS[code])


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        if path == PATH:
            if method != "POST" or content_type.split(";", 1)[0] != "application/json":
                raise ConformanceError("invalid_input")
            value = parse_json_object(body, required=("command_id",),
                optional=('installation_ref','schema_version','staged_installation_ref','expected_verified_installation_ref'),
                limits=WireLimits(max_bytes=4096, max_depth=4, max_items=32,
                                  max_members=8, max_string_bytes=256))
            return parse_command(value)
        suffix = path[len(PATH) + 1:] if path.startswith(PATH + "/") else ""
        if method not in {"GET", "HEAD"} or "/" in suffix or body:
            raise ConformanceError("invalid_input")
        uuid_string(suffix)
        return None
    except ConformanceError:
        raise
    except (WireInputError, ValueError):
        raise ConformanceError("invalid_input") from None


def create_router(*, service, base_path):
    if type(service) is not PersistentProviderConformance or type(base_path) is not str:
        raise TypeError("Invalid provider conformance route dependencies")
    router = APIRouter()

    def response(value, status=200):
        validated = parse_reply(canonical_json(value))
        projected = {**validated, "links": {name: base_path.rstrip("/") + path
            for name, path in validated["links"].items()}}
        raw = canonical_json(projected)
        if len(raw) > 8192:
            raise ConformanceError("unavailable")
        return Response(raw, status_code=status, media_type="application/json")

    @router.post(PATH, name="extensions.provider-conformance.execute")
    async def execute(request: Request):
        try:
            result = await run_in_threadpool(service.execute,
                request.state.authenticated_request,
                request.state.provider_conformance_payload)
            return response(result, 202 if result["state"] == "pending" else 200)
        except ConformanceError as error:
            return conformance_error(error)

    @router.api_route(PATH + "/{command_id}", methods=["GET", "HEAD"],
                      name="extensions.provider-conformance.read")
    async def read(request: Request, command_id: str):
        try:
            result = await run_in_threadpool(service.read,
                request.state.authenticated_request, command_id)
            return response(result, 200)
        except ConformanceError as error:
            return conformance_error(error)

    return router
