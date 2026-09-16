"""Pure v2 command and cancellation codecs; parsed values remain inert."""

from base64 import urlsafe_b64encode

from jsonschema import Draft202012Validator, FormatChecker

from ..domain.refs import DomainContractError, canonical_json, uuid_string
from ..domain.wire import WireLimits, parse_json_object
from ..operations.setup import OriginProfile, SetupContractError, parse_base64url_32
from .prepare_contracts import (
    DeploymentPrepareError,
    _input,
    epoch_ms,
    parse_request,
    stamp,
)
from .prepare_v2_schema_exports import (
    cancel_input_schema,
    cancellation_schema,
    receipt_import_input_schema,
)

_MARKER_FIELDS = (
    "schema",
    "domain",
    "request_id",
    "request_digest",
    "instance_id",
    "origin_profile_digest",
    "lifecycle_revision",
    "cancelled_at",
)
_MARKER_LIMITS = WireLimits(
    max_bytes=4096,
    max_depth=4,
    max_items=32,
    max_members=8,
    max_string_bytes=256,
)


def _route_input(request_id, value, schema):
    try:
        uuid_string(request_id)
        return {**_input(value, schema), "request_id": request_id}
    except DeploymentPrepareError:
        raise
    except (DomainContractError, TypeError, ValueError):
        raise DeploymentPrepareError() from None


def parse_cancel_v2(request_id, value):
    return _route_input(request_id, value, cancel_input_schema())


def parse_receipt_import(request_id, value):
    return _route_input(request_id, value, receipt_import_input_schema())


def parse_cancellation_v2(*, request_digest, payload, profile):
    """Parse one canonical marker without granting publication or journal authority."""
    try:
        if type(profile) is not OriginProfile:
            raise ValueError
        parse_base64url_32(request_digest)
        value = parse_json_object(
            payload,
            required=_MARKER_FIELDS,
            limits=_MARKER_LIMITS,
        )
        if canonical_json(value) != payload or not Draft202012Validator(
            cancellation_schema(), format_checker=FormatChecker()
        ).is_valid(value):
            raise ValueError
        uuid_string(value["request_id"])
        parse_base64url_32(value["request_digest"])
        parse_base64url_32(value["origin_profile_digest"])
        epoch_ms(value["cancelled_at"])
        origin = (
            urlsafe_b64encode(bytes.fromhex(profile.digest))
            .rstrip(b"=")
            .decode("ascii")
        )
        if (
            value["request_digest"] != request_digest
            or value["instance_id"] != profile.instance_id
            or value["origin_profile_digest"] != origin
        ):
            raise ValueError
        return dict(value)
    except DeploymentPrepareError:
        raise
    except (
        DomainContractError,
        KeyError,
        RecursionError,
        SetupContractError,
        TypeError,
        ValueError,
    ):
        raise DeploymentPrepareError() from None


def cancellation_v2(request, transitioned_ms, *, profile):
    """Reparse an accepted request and emit only the revision-three marker."""
    try:
        if type(request) is not dict:
            raise ValueError
        accepted = parse_request(canonical_json(request), profile=profile)
        raw = canonical_json(
            {
                "schema": "deployment-cancellation-v2",
                "domain": "deeptwin-deployment-cancellation-v2",
                "request_id": accepted["request_id"],
                "request_digest": accepted["request_digest"],
                "instance_id": accepted["instance_id"],
                "origin_profile_digest": accepted["origin_profile_digest"],
                "lifecycle_revision": 3,
                "cancelled_at": stamp(transitioned_ms),
            }
        )
        parse_cancellation_v2(
            request_digest=accepted["request_digest"], payload=raw, profile=profile
        )
        return raw
    except DeploymentPrepareError:
        raise
    except (DomainContractError, KeyError, RecursionError, TypeError, ValueError):
        raise DeploymentPrepareError() from None
