"""Independent retained public receipt sources; no receipt admission."""

from base64 import urlsafe_b64encode
from dataclasses import dataclass
from pathlib import Path

from app.operations.setup import OriginProfile, SetupContractError, parse_base64url_32

from . import contracts as c
from . import files as f
from . import mounts as m
from .receipt_contracts import ReceiptWireError, parse_receipt, parse_trust_set
from .receipt_publication import (
    ConsumedFileObservation,
    ConsumedPublicationObservation,
    validate_consumed_marker,
)
from .receipt_source_contracts import parse_consumption_exchange, parse_ingress
from .source_common import ObjectIdentity, _observed, _open_pinned_source, _Source

PUBLIC_TRUST_ROOT = Path("/run/deeptwin/deployment-verify-public")
RECEIPT_INGRESS_ROOT = Path("/run/deeptwin/deployment-receipt-ingress")
INCOMING_ROOT = Path("/run/deeptwin/deployment-receipts")
RECEIPTS_ROOT = INCOMING_ROOT / "receipts"
CONSUMPTION_EXCHANGE_ROOT = Path("/run/deeptwin/deployment-consumption-exchange")
CONSUMED_ROOT = Path("/run/deeptwin/deployment-consumed")
CONSUMED_NAMESPACE_ROOT = CONSUMED_ROOT / "consumed"


class DeploymentReceiptInvalid(c.DeploymentSourceError):
    code = "deployment_receipt_invalid"


@dataclass(frozen=True, slots=True)
class PublicSourceIdentity:
    source_kind: str
    root: ObjectIdentity
    file: ObjectIdentity
    backing_root_digest: str

    def as_dict(self):
        return {
            "schema_version": "deployment-public-source-identity-v1",
            "source_kind": self.source_kind,
            "root": self.root.as_dict(),
            "file": self.file.as_dict(),
            "backing_root_digest": self.backing_root_digest,
        }


@dataclass(frozen=True, slots=True)
class ReceiptIngressIdentity:
    source: PublicSourceIdentity
    root: ObjectIdentity
    receipts: ObjectIdentity
    backing_root_digest: str

    def as_dict(self):
        return {
            "schema_version": "deployment-receipt-ingress-identity-v1",
            "source": self.source.as_dict(),
            "root": self.root.as_dict(),
            "receipts": self.receipts.as_dict(),
            "backing_root_digest": self.backing_root_digest,
        }


@dataclass(frozen=True, slots=True)
class ConsumedIdentity:
    source: PublicSourceIdentity
    root: ObjectIdentity
    consumed: ObjectIdentity
    backing_root_digest: str

    def as_dict(self):
        return {
            "schema_version": "deployment-consumed-identity-v1",
            "source": self.source.as_dict(),
            "root": self.root.as_dict(),
            "consumed": self.consumed.as_dict(),
            "backing_root_digest": self.backing_root_digest,
        }


class PublicTrustSource(_Source):
    @property
    def trust_bytes(self):
        self.recheck_current()
        return self._bytes

    def recheck_current(self) -> PublicSourceIdentity:
        self._recheck_base()
        _mount, backing_root = dict(self._mapping)[PUBLIC_TRUST_ROOT]
        return PublicSourceIdentity(
            "trust",
            _observed(self._source.root.identity),
            _observed(self._source._signature[0]),
            c.digest(str(backing_root).encode("utf-8")),
        )


class ReceiptIngressSource(_Source):
    def _scan_receipts(self):
        try:
            self._recheck_base()
            mapping = dict(self._mapping)
            root_identity = self._incoming.recheck_current()
            receipts_identity = self._receipts.recheck_current()
            if (
                root_identity.device != receipts_identity.device
                or root_identity.inode == receipts_identity.inode
                or f.members(self._incoming.fd, 1) != {"receipts"}
            ):
                raise c.DeploymentSourceError()
            m.verify_device(mapping[INCOMING_ROOT][0], root_identity)
            m.verify_device(mapping[INCOMING_ROOT][0], receipts_identity)
            root_signature = f.signature(f.stat_fd(self._incoming.fd))
            receipts_signature = f.signature(f.stat_fd(self._receipts.fd))
            scan = f._scan_namespace(self._receipts, policy=f._INCOMING_NAMESPACE)
            if (
                f.members(self._incoming.fd, 1) != {"receipts"}
                or f.signature(f.stat_fd(self._incoming.fd)) != root_signature
                or f.signature(f.stat_fd(self._receipts.fd)) != receipts_signature
                or self._incoming.recheck_current() != root_identity
                or self._receipts.recheck_current() != receipts_identity
            ):
                raise c.DeploymentSourceError()
            self._recheck_base()
            source_mount, source_backing = mapping[RECEIPT_INGRESS_ROOT]
            incoming_mount, incoming_backing = mapping[INCOMING_ROOT]
            m.verify_device(source_mount, self._source.root.identity)
            m.verify_device(incoming_mount, root_identity)
            return (
                ReceiptIngressIdentity(
                    PublicSourceIdentity(
                        "ingress",
                        _observed(self._source.root.identity),
                        _observed(self._source._signature[0]),
                        c.digest(str(source_backing).encode("utf-8")),
                    ),
                    _observed(root_identity),
                    _observed(receipts_identity),
                    c.digest(str(incoming_backing).encode("utf-8")),
                ),
                scan,
            )
        except OSError:
            raise c.DeploymentSourceUnavailable() from None

    @property
    def ingress_bytes(self):
        self._scan_receipts()
        return self._bytes

    def recheck_current(self) -> ReceiptIngressIdentity:
        identity, _scan = self._scan_receipts()
        return identity

    def list_available_receipt_digests(self) -> tuple[str, ...]:
        _identity, scan = self._scan_receipts()
        return tuple(
            urlsafe_b64encode(bytes.fromhex(entry.name[:-5]))
            .rstrip(b"=")
            .decode("ascii")
            for entry in scan.finals
        )

    def open_receipt(self, receipt_digest: str) -> "ReceiptFileLease":
        try:
            digest_bytes = parse_base64url_32(receipt_digest)
        except (SetupContractError, TypeError, ValueError):
            raise c.DeploymentSourceError() from None
        digest_hex = digest_bytes.hex()
        name = f"{digest_hex}.json"
        identity, scan = self._scan_receipts()
        entry = next((item for item in scan.finals if item.name == name), None)
        if entry is None:
            raise c.DeploymentSourceError()
        opened = f._open_final(self._receipts, entry, policy=f._INCOMING_NAMESPACE)
        try:
            raw = opened.read_current()
            if c.digest(raw) != digest_hex:
                raise c.DeploymentSourceError()
            after_identity, after_scan = self._scan_receipts()
            after_entry = next(
                (item for item in after_scan.finals if item.name == name), None
            )
            if (
                after_identity != identity
                or after_entry is None
                or after_entry.signature != entry.signature
                or opened.read_current() != raw
            ):
                raise c.DeploymentSourceError()
            result = object.__new__(ReceiptFileLease)
            result._owner, result._file = self, opened
            result._bytes, result._digest = raw, receipt_digest
            result._digest_hex, result._signature = digest_hex, entry.signature
            result._file_identity, result._closed = entry.signature[0], False
            receipt = None
            try:
                receipt = parse_receipt(raw)
            except ReceiptWireError:
                pass
            result.recheck_current()
            if receipt is None:
                raise DeploymentReceiptInvalid() from None
            expected_origin = (
                urlsafe_b64encode(bytes.fromhex(self._ingress["origin_profile_digest"]))
                .rstrip(b"=")
                .decode("ascii")
            )
            expected_trust = (
                urlsafe_b64encode(bytes.fromhex(self._ingress["trust_set_digest"]))
                .rstrip(b"=")
                .decode("ascii")
            )
            if (
                receipt["instance_id"] != self._ingress["instance_id"]
                or receipt["origin_profile_digest"] != expected_origin
                or receipt["deployment_profile_id"]
                != self._profile.deployment_profile_id
                or receipt["trust_set_digest"] != expected_trust
            ):
                raise c.DeploymentSourceError()
            result.recheck_current()
            return result
        except DeploymentReceiptInvalid:
            opened.close()
            raise
        except (OSError, c.DeploymentSourceError):
            opened.close()
            raise c.DeploymentSourceError() from None


class ConsumptionExchangeSource(_Source):
    def _inspect_inventory(
        self,
    ) -> tuple[ConsumedIdentity, tuple[ConsumedFileObservation, ...]]:
        opened = []
        try:
            self._recheck_base()
            mapping = dict(self._mapping)
            root_identity = self._consumed_root.recheck_current()
            consumed_identity = self._consumed.recheck_current()
            if (
                root_identity.device != consumed_identity.device
                or root_identity.inode == consumed_identity.inode
                or f.members(self._consumed_root.fd, 1) != {"consumed"}
            ):
                raise c.DeploymentSourceError()
            m.verify_device(mapping[CONSUMED_ROOT][0], root_identity)
            m.verify_device(mapping[CONSUMED_ROOT][0], consumed_identity)
            root_signature = f.signature(f.stat_fd(self._consumed_root.fd))
            consumed_signature = f.signature(f.stat_fd(self._consumed.fd))
            scan = f._scan_namespace(self._consumed, policy=f._CONSUMED_NAMESPACE)
            observations = []
            for entry in scan.finals:
                selected = f._open_final(
                    self._consumed, entry, policy=f._CONSUMED_NAMESPACE
                )
                opened.append(selected)
                raw = selected.read_current()
                receipt_digest = (
                    urlsafe_b64encode(bytes.fromhex(entry.name[:-5]))
                    .rstrip(b"=")
                    .decode("ascii")
                )
                validate_consumed_marker(
                    receipt_digest=receipt_digest,
                    payload=raw,
                )
                observations.append(
                    ConsumedFileObservation(receipt_digest, raw, entry.signature[0])
                )
            for selected, observation in zip(opened, observations, strict=True):
                if selected.read_current() != observation.payload:
                    raise c.DeploymentSourceError()
            if (
                f.members(self._consumed_root.fd, 1) != {"consumed"}
                or f.signature(f.stat_fd(self._consumed_root.fd)) != root_signature
                or f.signature(f.stat_fd(self._consumed.fd)) != consumed_signature
                or self._consumed_root.recheck_current() != root_identity
                or self._consumed.recheck_current() != consumed_identity
            ):
                raise c.DeploymentSourceError()
            self._recheck_base()
            source_mount, source_backing = mapping[CONSUMPTION_EXCHANGE_ROOT]
            consumed_mount, consumed_backing = mapping[CONSUMED_ROOT]
            m.verify_device(source_mount, self._source.root.identity)
            m.verify_device(consumed_mount, root_identity)
            identity = ConsumedIdentity(
                PublicSourceIdentity(
                    "consumption",
                    _observed(self._source.root.identity),
                    _observed(self._source._signature[0]),
                    c.digest(str(source_backing).encode("utf-8")),
                ),
                _observed(root_identity),
                _observed(consumed_identity),
                c.digest(str(consumed_backing).encode("utf-8")),
            )
            return identity, tuple(observations)
        except OSError:
            raise c.DeploymentSourceUnavailable() from None
        finally:
            for selected in opened:
                selected.close()

    @property
    def consumption_exchange_bytes(self):
        self._inspect_inventory()
        return self._bytes

    def recheck_current(self) -> ConsumedIdentity:
        identity, _observations = self._inspect_inventory()
        return identity

    def inspect_consumed(self) -> tuple[ConsumedFileObservation, ...]:
        _identity, observations = self._inspect_inventory()
        return observations

    def publish_consumed(
        self, *, receipt_digest: str, payload: bytes
    ) -> ConsumedPublicationObservation:
        from .receipt_publication import publish_consumed

        return publish_consumed(
            self,
            receipt_digest=receipt_digest,
            payload=payload,
        )


class ReceiptFileLease(f.RetainedHandle):
    def __init__(self):
        raise TypeError("receipt lease construction requires the owning ingress source")

    def _ensure_open(self):
        if self._closed or getattr(self._owner, "_closed", True):
            raise c.DeploymentSourceError()

    @property
    def receipt_bytes(self):
        self.recheck_current()
        return self._bytes

    @property
    def receipt_digest(self):
        self._ensure_open()
        return self._digest

    @property
    def file_identity(self):
        self._ensure_open()
        return self._file_identity

    def recheck_current(self) -> f.FileIdentity:
        self._ensure_open()
        before_identity, before_scan = self._owner._scan_receipts()
        name = f"{self._digest_hex}.json"
        before_entry = next(
            (item for item in before_scan.finals if item.name == name), None
        )
        if before_entry is None or before_entry.signature != self._signature:
            raise c.DeploymentSourceError()
        raw = self._file.read_current()
        if raw != self._bytes or c.digest(raw) != self._digest_hex:
            raise c.DeploymentSourceError()
        after_identity, after_scan = self._owner._scan_receipts()
        after_entry = next(
            (item for item in after_scan.finals if item.name == name), None
        )
        if (
            after_identity != before_identity
            or after_entry is None
            or after_entry.signature != self._signature
            or self._file.read_current() != self._bytes
        ):
            raise c.DeploymentSourceError()
        return self._file_identity

    def close(self):
        if not getattr(self, "_closed", True):
            self._closed = True
            self._file.close()


def open_public_trust_source(
    *,
    profile: OriginProfile,
    trust_sha256: str,
    protected_roots: tuple[Path, ...],
) -> PublicTrustSource:
    source = _open_pinned_source(
        PublicTrustSource,
        profile=profile,
        source_sha256=trust_sha256,
        protected_roots=protected_roots,
        root=PUBLIC_TRUST_ROOT,
        name="trust-set.json",
        gid=20102,
        cap=16384,
        required={PUBLIC_TRUST_ROOT: True},
    )
    try:
        parse_trust_set(source._bytes, profile=profile)
        source.recheck_current()
        return source
    except (ReceiptWireError, c.DeploymentSourceError):
        source.close()
        raise c.DeploymentSourceError() from None


def open_receipt_ingress_source(
    *,
    profile: OriginProfile,
    receipt_recipe_sha256: str,
    receipt_instance_sha256: str,
    ingress_sha256: str,
    protected_roots: tuple[Path, ...],
) -> ReceiptIngressSource:
    source = _open_pinned_source(
        ReceiptIngressSource,
        profile=profile,
        source_sha256=ingress_sha256,
        protected_roots=protected_roots,
        root=RECEIPT_INGRESS_ROOT,
        name="ingress.json",
        gid=21201,
        cap=8192,
        required={RECEIPT_INGRESS_ROOT: True, INCOMING_ROOT: True},
    )
    try:
        source._ingress = parse_ingress(
            source._bytes,
            profile=profile,
            receipt_recipe_sha256=receipt_recipe_sha256,
            receipt_instance_sha256=receipt_instance_sha256,
        )
        incoming = f.Directory.open(INCOMING_ROOT, uid=20113, gid=21201, mode=0o750)
        source._incoming = incoming
        source._handles.append(incoming)
        if f.members(incoming.fd, 1) != {"receipts"}:
            raise c.DeploymentSourceError()
        receipts = f.Directory.open(RECEIPTS_ROOT, uid=20113, gid=21201, mode=0o750)
        source._receipts = receipts
        source._handles.append(receipts)
        source._scan_receipts()
        return source
    except (OSError, c.DeploymentSourceError):
        source.close()
        raise c.DeploymentSourceError() from None


def open_consumption_exchange_source(
    *,
    profile: OriginProfile,
    receipt_recipe_sha256: str,
    receipt_instance_sha256: str,
    consumption_exchange_sha256: str,
    protected_roots: tuple[Path, ...],
) -> ConsumptionExchangeSource:
    source = _open_pinned_source(
        ConsumptionExchangeSource,
        profile=profile,
        source_sha256=consumption_exchange_sha256,
        protected_roots=protected_roots,
        root=CONSUMPTION_EXCHANGE_ROOT,
        name="consumption-exchange.json",
        gid=21201,
        cap=8192,
        required={CONSUMPTION_EXCHANGE_ROOT: True, CONSUMED_ROOT: False},
    )
    try:
        source._consumption_exchange = parse_consumption_exchange(
            source._bytes,
            profile=profile,
            receipt_recipe_sha256=receipt_recipe_sha256,
            receipt_instance_sha256=receipt_instance_sha256,
        )
        consumed_root = f.Directory.open(
            CONSUMED_ROOT, uid=20102, gid=21201, mode=0o750
        )
        source._consumed_root = consumed_root
        source._handles.append(consumed_root)
        if f.members(consumed_root.fd, 1) != {"consumed"}:
            raise c.DeploymentSourceError()
        consumed = f.Directory.open(
            CONSUMED_NAMESPACE_ROOT, uid=20102, gid=21201, mode=0o750
        )
        source._consumed = consumed
        source._handles.append(consumed)
        source._inspect_inventory()
        return source
    except (OSError, c.DeploymentSourceError):
        source.close()
        raise c.DeploymentSourceError() from None
