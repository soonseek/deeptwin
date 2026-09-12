"""Closed, typed transports for owned native workers."""

from .protocol import MAX_FRAME_BYTES, ProtocolViolation, decode_browser_request, encode_browser_request

__all__ = ("MAX_FRAME_BYTES", "ProtocolViolation", "decode_browser_request", "encode_browser_request")
