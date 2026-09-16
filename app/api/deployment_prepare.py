"""Fixed browser adapter and startup-owned source assembly for preparation."""

from contextlib import ExitStack
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from ..deployment.contracts import DeploymentSourceError, hex_digest
from ..deployment.prepare_contracts import (
    ERRORS,
    DeploymentPrepareError,
    parse_prepare,
)
from ..deployment.prepare_service import PersistentDeploymentPrepare
from ..deployment.prepare_v2_contracts import parse_cancel_v2, parse_receipt_import
from ..deployment.receipt_sources import (
    open_consumption_exchange_source,
    open_public_trust_source,
    open_receipt_ingress_source,
)
from ..deployment.sources import open_exchange_source, open_topology_source
from ..domain.refs import canonical_json, uuid_string
from .first_party import ContributionServices
from .wire import WireInputError, WireLimits, parse_json_object, parse_query

PATH = "/api/v1/deployment/requests"
STARTUP_KEYS = (
    "DEEPTWIN_PREPARE_RECIPE_SHA256",
    "DEEPTWIN_PREPARE_INSTANCE_SHA256",
    "DEEPTWIN_TOPOLOGY_SHA256",
    "DEEPTWIN_EXCHANGE_SHA256",
    "DEEPTWIN_RECEIPT_RECIPE_SHA256",
    "DEEPTWIN_RECEIPT_INSTANCE_SHA256",
    "DEEPTWIN_DEPLOYMENT_TRUST_SHA256",
    "DEEPTWIN_RECEIPT_INGRESS_SHA256",
    "DEEPTWIN_CONSUMPTION_EXCHANGE_SHA256",
)


def _own_source(stack, resources, source):
    def close(exception_type, _exception, _traceback):
        try:
            source.close()
        except BaseException:
            # A cleanup failure cannot replace the active construction error.
            if exception_type is None:
                raise
        return False

    stack.push(close)
    resources.append(source)


def prepare_services(context, *, dependencies):
    if set(dependencies) != {"extension-candidates.registry"}:
        raise TypeError("Invalid deployment dependencies")
    registry = dependencies["extension-candidates.registry"]
    values = context.startup_inputs.values
    with ExitStack() as stack:
        resources = []
        topology = exchange = None
        try:
            common = {
                "profile": context.owner_authority.profile,
                "recipe_sha256": hex_digest(values.get(STARTUP_KEYS[0])),
                "instance_sha256": hex_digest(values.get(STARTUP_KEYS[1])),
                "protected_roots": context.startup_inputs.protected_roots,
            }
        except DeploymentSourceError:
            common = None
        if common is not None:
            try:
                topology = open_topology_source(
                    **common, topology_sha256=hex_digest(values.get(STARTUP_KEYS[2]))
                )
                _own_source(stack, resources, topology)
            except DeploymentSourceError:
                pass
            try:
                exchange = open_exchange_source(
                    **common, exchange_sha256=hex_digest(values.get(STARTUP_KEYS[3]))
                )
                _own_source(stack, resources, exchange)
            except DeploymentSourceError:
                pass
        trust = ingress = consumption = None
        try:
            trust = open_public_trust_source(
                profile=context.owner_authority.profile,
                trust_sha256=hex_digest(values.get(STARTUP_KEYS[6])),
                protected_roots=context.startup_inputs.protected_roots,
            )
            _own_source(stack, resources, trust)
        except DeploymentSourceError:
            pass
        try:
            receipt_common = {
                "profile": context.owner_authority.profile,
                "receipt_recipe_sha256": hex_digest(values.get(STARTUP_KEYS[4])),
                "receipt_instance_sha256": hex_digest(values.get(STARTUP_KEYS[5])),
                "protected_roots": context.startup_inputs.protected_roots,
            }
        except DeploymentSourceError:
            receipt_common = None
        if receipt_common is not None:
            try:
                ingress = open_receipt_ingress_source(
                    **receipt_common,
                    ingress_sha256=hex_digest(values.get(STARTUP_KEYS[7])),
                )
                _own_source(stack, resources, ingress)
            except DeploymentSourceError:
                pass
            try:
                consumption = open_consumption_exchange_source(
                    **receipt_common,
                    consumption_exchange_sha256=hex_digest(values.get(STARTUP_KEYS[8])),
                )
                _own_source(stack, resources, consumption)
            except DeploymentSourceError:
                pass
        service = PersistentDeploymentPrepare(
            context.domain_store,
            context.owner_authority,
            registry,
            topology_source=topology,
            exchange_source=exchange,
            public_trust_source=trust,
            receipt_ingress_source=ingress,
            consumption_exchange_source=consumption,
        )
        result = ContributionServices(
            create_router(service=service, base_path=context.base_path),
            {"deployment-prepare.service": service},
            owned_resources=tuple(resources),
        )
        stack.pop_all()
        return result


def reconcile_prepare_startup(own_exports):
    own_exports["deployment-prepare.service"].reconcile_startup()


def deployment_error(error):
    status, message = ERRORS[error.code]
    return JSONResponse(
        {
            "code": error.code,
            "message": message,
            "retryability": "not_retryable",
            "affected_refs": [],
            "correlation_id": str(uuid4()),
        },
        status_code=status,
    )


def preflight(scope, body, content_type):
    try:
        path, method = scope["path"], scope["method"]
        parse_query(scope.get("query_string", b""), allowed=())
        request_id = None
        if path == PATH:
            if method != "POST":
                raise DeploymentPrepareError()
            required = (
                "command_id",
                "kind",
                "candidate_id",
                "slot_id",
                "expires_in_seconds",
            )
        else:
            suffix = path[len(PATH) + 1 :] if path.startswith(PATH + "/") else ""
            parts = suffix.split("/")
            request_id = uuid_string(parts[0])
            if len(parts) == 1 and method in {"GET", "HEAD"}:
                if body:
                    raise DeploymentPrepareError()
                return None
            if (
                len(parts) != 2
                or parts[1] not in {"cancel", "receipts"}
                or method != "POST"
            ):
                raise DeploymentPrepareError()
            required = ("command_id", "request_digest", "expected_revision")
            if parts[1] == "receipts":
                required += ("receipt_digest",)
        if content_type.split(";", 1)[0] != "application/json":
            raise DeploymentPrepareError()
        value = parse_json_object(
            body,
            required=required,
            limits=WireLimits(
                max_bytes=4096,
                max_depth=4,
                max_items=32,
                max_members=8,
                max_string_bytes=256,
            ),
        )
        if request_id is None:
            return parse_prepare(value)
        parser = parse_receipt_import if parts[1] == "receipts" else parse_cancel_v2
        parsed = parser(request_id, value)
        # The route binds the ID again inside the actual service; body cannot override it.
        return {key: parsed[key] for key in required}
    except DeploymentPrepareError:
        raise
    except (WireInputError, ValueError):
        raise DeploymentPrepareError() from None


def create_router(*, service, base_path):
    router = APIRouter()

    def response(value, status=200, *, project_links=True):
        projected = (
            value
            if not project_links
            else {
                **value,
                "links": {
                    name: base_path.rstrip("/") + path
                    for name, path in value["links"].items()
                },
            }
        )
        return Response(
            canonical_json(projected), status_code=status, media_type="application/json"
        )

    @router.post(PATH)
    async def prepare(request: Request):
        try:
            result = await run_in_threadpool(
                service.prepare,
                request.state.authenticated_request,
                request.state.deployment_payload,
            )
            return response(result, 201)
        except DeploymentPrepareError as error:
            return deployment_error(error)

    @router.post(PATH + "/{request_id}/cancel")
    async def cancel(request: Request, request_id: str):
        try:
            result = await run_in_threadpool(
                service.cancel,
                request.state.authenticated_request,
                request_id,
                request.state.deployment_payload,
            )
            return response(result)
        except DeploymentPrepareError as error:
            return deployment_error(error)

    @router.api_route(PATH + "/{request_id}", methods=["GET", "HEAD"])
    async def read(request: Request, request_id: str):
        try:
            result = await run_in_threadpool(
                service.read, request.state.authenticated_request, request_id
            )
            return response(result)
        except DeploymentPrepareError as error:
            return deployment_error(error)

    @router.post(PATH + "/{request_id}/receipts")
    async def import_receipt(request: Request, request_id: str):
        try:
            result = await run_in_threadpool(
                service.import_receipt,
                request.state.authenticated_request,
                request_id,
                request.state.deployment_payload,
            )
            return response(result, project_links=False)
        except DeploymentPrepareError as error:
            return deployment_error(error)

    return router
