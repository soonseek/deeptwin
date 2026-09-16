"""Compatibility imports for the shared strict wire codec."""
# ruff: noqa: PLC0414 - explicit compatibility re-exports.

from ..domain.wire import (
    WireInputError as WireInputError,
)
from ..domain.wire import (
    WireLimits as WireLimits,
)
from ..domain.wire import (
    parse_json_object as parse_json_object,
)
from ..domain.wire import (
    parse_json_then as parse_json_then,
)
from ..domain.wire import (
    parse_query as parse_query,
)
from ..domain.wire import (
    parse_singleton_headers as parse_singleton_headers,
)
