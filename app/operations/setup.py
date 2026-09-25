"""Strict, side-effect-free first-owner bootstrap delivery primitives.

The offline deployment helper owns capability generation.  This module validates the
non-secret verifier and OriginProfile at the application boundary; it never persists,
prints, logs, or returns a raw capability.
"""

import hmac
import ipaddress
import re
from base64 import b64decode, urlsafe_b64encode
from dataclasses import dataclass
from hashlib import sha256
from unicodedata import category, normalize
from urllib.parse import urlsplit

import idna
from idna.intranges import intranges_contain

from ..domain.refs import canonical_json

LOCAL_DEPLOYMENT_PROFILE = "local-no-terminal-v1"
PORTABLE_DEPLOYMENT_PROFILE = "portable-compose-v1"
LOCAL_MODE = "local_loopback"
PORTABLE_MODE = "portable_https"
INITIAL_RECOVERY_EPOCH = 1
# a bound on the epoch any deployment reaches, not a policy (matches the recovery schemas)
MAX_RECOVERY_EPOCH = 1_000_000

_HEX_128 = re.compile(r"[0-9a-f]{32}")
_HEX_256 = re.compile(r"[0-9a-f]{64}")
_B64U_32 = re.compile(r"[A-Za-z0-9_-]{43}")
_DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
_PORT = re.compile(r"[1-9][0-9]{0,4}")
_PROFILE_FIELDS = (
    "deployment_profile_id",
    "instance_id",
    "mode",
    "scheme",
    "host",
    "port",
    "base_path",
    "origin_base",
)
_SERIALIZED_FIELDS = frozenset((*_PROFILE_FIELDS, "digest"))
_IDNA_PVALID_RANGES = idna.idnadata.codepoint_classes["PVALID"]


class SetupContractError(ValueError):
    """A bootstrap value is ambiguous, noncanonical, or outside the closed contract."""


def _invalid() -> SetupContractError:
    return SetupContractError("Invalid bootstrap input")


def _identifier(value: object) -> str:
    if type(value) is not str or _HEX_128.fullmatch(value) is None:
        raise _invalid()
    return value


def _port(value: object) -> int:
    if type(value) is not int or not 1 <= value <= 65_535:
        raise _invalid()
    return value


def _origin(scheme: str, host: str, port: int) -> str:
    default = 80 if scheme == "http" else 443
    suffix = "" if port == default else f":{port}"
    return f"{scheme}://{host}{suffix}"


def _portable_host(raw_host: str) -> str:
    if (type(raw_host) is not str or not raw_host or raw_host.endswith(".")
            or "%" in raw_host or "_" in raw_host
            or any(not (
                character.isascii() and (character.isalnum() or character in ".-")
                or category(character)[0] in {"L", "M"}
            ) for character in raw_host)):
        raise _invalid()
    raw_labels = raw_host.split(".")
    if (any(not label or label.startswith("-") or label.endswith("-") for label in raw_labels)
            or any(label[2:4] == "--" and not label.lower().startswith("xn--")
                   for label in raw_labels)):
        raise _invalid()
    normalized_host = normalize("NFC", raw_host.lower())
    normalized_labels = normalized_host.split(".")
    if (any(not label or label.startswith("-") or label.endswith("-")
            for label in normalized_labels)
            or any(label[2:4] == "--" and not label.startswith("xn--")
                   for label in normalized_labels)):
        raise _invalid()
    try:
        canonical_labels = []
        for label in normalized_labels:
            if label.isascii():
                ascii_label = label
                unicode_label = idna.ulabel(label) if label.startswith("xn--") else label
            else:
                unicode_label = label
                ascii_label = idna.alabel(label).decode("ascii")
            if any(
                character != "-"
                and not intranges_contain(ord(character), _IDNA_PVALID_RANGES)
                for character in unicode_label
            ):
                raise _invalid()
            if idna.alabel(unicode_label).decode("ascii") != ascii_label:
                raise _invalid()
            canonical_labels.append(ascii_label)
        ascii_host = ".".join(canonical_labels)
    except (idna.IDNAError, UnicodeError):
        raise _invalid() from None
    if len(ascii_host) > 253 or "." not in ascii_host:
        raise _invalid()
    labels = ascii_host.split(".")
    if any(_DNS_LABEL.fullmatch(label) is None for label in labels):
        raise _invalid()
    if any(label[2:4] == "--" and not label.startswith("xn--") for label in labels):
        raise _invalid()
    if (not any("a" <= character <= "z" for character in labels[-1])
            or re.fullmatch(r"0x[0-9a-f]*", labels[-1]) is not None):
        raise _invalid()
    try:
        ipaddress.ip_address(ascii_host)
    except ValueError:
        pass
    else:
        raise _invalid()
    numeric_forms = re.compile(r"(?:0x[0-9a-f]+|[0-9]+)")
    if all(numeric_forms.fullmatch(label) is not None for label in labels):
        raise _invalid()
    return ascii_host


def _portable_url(value: object) -> tuple[str, int, str]:
    if type(value) is not str or not value or len(value) > 2_048:
        raise _invalid()
    try:
        encoded_length = len(value.encode("utf-8"))
    except UnicodeError:
        raise _invalid() from None
    if (encoded_length > 2_048 or value != value.strip()
            or any(ord(character) <= 0x20 or ord(character) == 0x7F for character in value)
            or "\\" in value or "?" in value or "#" in value
            or re.match(r"(?i)^https://", value) is None):
        raise _invalid()

    authority_and_path = value[value.index("://") + 3:]
    authority, separator, raw_path = authority_and_path.partition("/")
    raw_path = f"/{raw_path}" if separator else ""
    if raw_path not in {"", "/"}:
        raise _invalid()
    if (not authority or "@" in authority or "[" in authority or "]" in authority
            or "%" in authority or authority.count(":") > 1):
        raise _invalid()
    if ":" in authority:
        raw_host, port_text = authority.rsplit(":", 1)
        if _PORT.fullmatch(port_text) is None or int(port_text) > 65_535:
            raise _invalid()
        port = int(port_text)
    else:
        raw_host = authority
        port = 443
    if raw_host.endswith("."):
        raise _invalid()

    try:
        parsed = urlsplit(value)
        parsed_port = parsed.port or 443
    except ValueError:
        raise _invalid() from None
    if (parsed.scheme.lower() != "https" or not parsed.netloc or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment
            or parsed.path not in {"", "/"} or parsed_port != port):
        raise _invalid()
    host = _portable_host(raw_host)
    origin_base = f"{_origin('https', host, port)}/"
    return host, port, origin_base


def parse_base64url_32(value: object) -> bytes:
    """Decode one exact canonical base64url-no-padding 32-byte value."""

    if type(value) is not str or _B64U_32.fullmatch(value) is None:
        raise _invalid()
    try:
        decoded = b64decode(value + "=", altchars=b"-_", validate=True)
    except (ValueError, TypeError):
        raise _invalid() from None
    if len(decoded) != 32 or urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii") != value:
        raise _invalid()
    return decoded


def derive_capability_verifier(raw_capability_b64u: object) -> str:
    """Derive the non-secret SHA-256 verifier without retaining the capability."""

    value = parse_base64url_32(raw_capability_b64u)
    return urlsafe_b64encode(sha256(value).digest()).rstrip(b"=").decode("ascii")


@dataclass(frozen=True, slots=True)
class CapabilityVerifier:
    """A non-secret verifier that can check one submitted bootstrap capability."""

    verifier_b64u: str

    def __post_init__(self) -> None:
        parse_base64url_32(self.verifier_b64u)

    def matches(self, candidate_b64u: object) -> bool:
        candidate = parse_base64url_32(candidate_b64u)
        expected = parse_base64url_32(self.verifier_b64u)
        return hmac.compare_digest(sha256(candidate).digest(), expected)


def verify_bootstrap_capability(raw_capability_b64u: object, verifier_b64u: object) -> bool:
    if type(verifier_b64u) is not str:
        raise _invalid()
    return CapabilityVerifier(verifier_b64u).matches(raw_capability_b64u)


@dataclass(frozen=True, slots=True)
class OriginProfile:
    deployment_profile_id: str
    instance_id: str
    mode: str
    scheme: str
    host: str
    port: int
    base_path: str
    origin_base: str
    digest: str

    def __post_init__(self) -> None:
        _identifier(self.instance_id)
        _port(self.port)
        if type(self.digest) is not str or _HEX_256.fullmatch(self.digest) is None:
            raise _invalid()
        if self.mode == LOCAL_MODE:
            if (self.deployment_profile_id != LOCAL_DEPLOYMENT_PROFILE
                    or self.scheme != "http"
                    or self.host != f"{self.instance_id}.localhost"
                    or type(self.base_path) is not str
                    or re.fullmatch(r"/[0-9a-f]{32}/", self.base_path) is None):
                raise _invalid()
        elif self.mode == PORTABLE_MODE:
            if (self.deployment_profile_id != PORTABLE_DEPLOYMENT_PROFILE
                    or self.scheme != "https" or self.base_path != "/"
                    or _portable_host(self.host) != self.host):
                raise _invalid()
        else:
            raise _invalid()
        expected_origin = f"{_origin(self.scheme, self.host, self.port)}{self.base_path}"
        if self.origin_base != expected_origin:
            raise _invalid()
        expected_digest = sha256(self.canonical_preimage()).hexdigest()
        if not hmac.compare_digest(self.digest, expected_digest):
            raise _invalid()

    @property
    def http_origin(self) -> str:
        return _origin(self.scheme, self.host, self.port)

    def canonical_preimage(self) -> bytes:
        return canonical_json({name: getattr(self, name) for name in _PROFILE_FIELDS})

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in (*_PROFILE_FIELDS, "digest")}

    @classmethod
    def local(cls, *, instance_id: object, path_id: object, port: object) -> "OriginProfile":
        instance = _identifier(instance_id)
        path = _identifier(path_id)
        checked_port = _port(port)
        host = f"{instance}.localhost"
        base_path = f"/{path}/"
        fields = {
            "deployment_profile_id": LOCAL_DEPLOYMENT_PROFILE,
            "instance_id": instance,
            "mode": LOCAL_MODE,
            "scheme": "http",
            "host": host,
            "port": checked_port,
            "base_path": base_path,
            "origin_base": f"{_origin('http', host, checked_port)}{base_path}",
        }
        return cls(**fields, digest=sha256(canonical_json(fields)).hexdigest())

    @classmethod
    def portable(cls, *, instance_id: object, url: object) -> "OriginProfile":
        instance = _identifier(instance_id)
        host, port, origin_base = _portable_url(url)
        fields = {
            "deployment_profile_id": PORTABLE_DEPLOYMENT_PROFILE,
            "instance_id": instance,
            "mode": PORTABLE_MODE,
            "scheme": "https",
            "host": host,
            "port": port,
            "base_path": "/",
            "origin_base": origin_base,
        }
        return cls(**fields, digest=sha256(canonical_json(fields)).hexdigest())

    @classmethod
    def from_dict(cls, value: object) -> "OriginProfile":
        if type(value) is not dict or set(value) != _SERIALIZED_FIELDS:
            raise _invalid()
        return cls(**value)


def build_bootstrap_configuration(
    *, profile: OriginProfile | dict[str, object], verifier_b64u: object,
    recovery_epoch: object = INITIAL_RECOVERY_EPOCH,
) -> dict[str, object]:
    """Build the exact non-secret initial deployment handoff block."""

    checked_profile = profile if type(profile) is OriginProfile else OriginProfile.from_dict(profile)
    if type(recovery_epoch) is not int or recovery_epoch != INITIAL_RECOVERY_EPOCH:
        raise _invalid()
    if type(verifier_b64u) is not str:
        raise _invalid()
    CapabilityVerifier(verifier_b64u)
    return {
        "verifier_b64u": verifier_b64u,
        "recovery_epoch": recovery_epoch,
        "origin_profile": checked_profile.as_dict(),
    }


def build_recovered_configuration(
    *, profile: OriginProfile | dict[str, object], verifier_b64u: object, recovery_epoch: object,
) -> dict[str, object]:
    """The same non-secret handoff block after an owner recovery: the new verifier and a
    recovery epoch above the initial one. Only a matching recovered session root and a
    verified recovery receipt make it serve; the block itself grants nothing."""

    checked_profile = profile if type(profile) is OriginProfile else OriginProfile.from_dict(profile)
    if (type(recovery_epoch) is not int
            or not INITIAL_RECOVERY_EPOCH < recovery_epoch <= MAX_RECOVERY_EPOCH):
        raise _invalid()
    if type(verifier_b64u) is not str:
        raise _invalid()
    CapabilityVerifier(verifier_b64u)
    return {
        "verifier_b64u": verifier_b64u,
        "recovery_epoch": recovery_epoch,
        "origin_profile": checked_profile.as_dict(),
    }


__all__ = (
    "INITIAL_RECOVERY_EPOCH",
    "LOCAL_DEPLOYMENT_PROFILE",
    "LOCAL_MODE",
    "MAX_RECOVERY_EPOCH",
    "PORTABLE_DEPLOYMENT_PROFILE",
    "PORTABLE_MODE",
    "CapabilityVerifier",
    "OriginProfile",
    "SetupContractError",
    "build_bootstrap_configuration",
    "build_recovered_configuration",
    "derive_capability_verifier",
    "parse_base64url_32",
    "verify_bootstrap_capability",
)
