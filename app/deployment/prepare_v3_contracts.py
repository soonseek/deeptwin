"""Pure v3 consume command codec (contracts/deployment-receipt-journal-v3.md §6/§7);
a parsed value is inert route input, never admission."""

from .prepare_contracts import DeploymentPrepareError
from .prepare_v2_contracts import _route_input
from .prepare_v3_schema_exports import consume_input_schema

__all__ = ["DeploymentPrepareError", "parse_consume"]


def parse_consume(request_id, value):
    """`{command_id, request_digest, receipt_digest, expected_revision:2}` with the
    route's request id attached; every closed violation is the shared error."""
    return _route_input(request_id, value, consume_input_schema())
