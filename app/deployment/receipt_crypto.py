"""Detached PureEd25519 public verification for canonical receipt bytes."""

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from .receipt_contracts import ReceiptWireError


def verify_detached(public_key: bytes, message: bytes, signature: bytes) -> bytes:
    if (
        type(public_key) is not bytes
        or len(public_key) != 32
        or type(message) is not bytes
        or type(signature) is not bytes
        or len(signature) != 64
    ):
        raise ReceiptWireError()
    try:
        verified = VerifyKey(public_key).verify(message, signature)
    except BadSignatureError:
        raise ReceiptWireError("receipt_signature_invalid") from None
    if type(verified) is not bytes or verified != message:
        raise ReceiptWireError()
    return verified


__all__ = ["verify_detached"]
