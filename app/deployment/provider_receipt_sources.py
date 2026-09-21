"""Retained provider receipt channels; filesystem observations are inert."""

from pathlib import Path
from hashlib import sha256
from ..operations.setup import OriginProfile, parse_base64url_32
from . import contracts as c, files as f, publication as p
from .provider_sources import ProviderSourceContext
from ._provider_source_files import _provider_namespace_policy
from .provider_publication import _close_all, _transition
from .provider_receipt_contracts import parse_provider_receipt, parse_provider_consumed
from .receipt_contracts import ReceiptWireError
from .receipt_sources import DeploymentReceiptInvalid
from .receipt_publication import ConsumedPublicationObservation

_INCOMING = Path("/run/deeptwin/provider-deployment-receipts")
_CONSUMED = Path("/run/deeptwin/provider-deployment-consumed")
_SEAL = object()


class ProviderReceiptFileLease(f.RetainedHandle):
    def __init__(self):
        raise TypeError("receipt lease requires its channel owner")

    def recheck_current(self):
        if (
            type(self) is not ProviderReceiptFileLease
            or getattr(self, "_seal", None) is not _SEAL
            or self._closed
            or self._owner._active is not self
        ):
            raise c.DeploymentSourceError()
        before = self._owner._observation()
        entries = dict(dict(before)["receipts"].entries)
        if (
            entries.get(self._name) != self._signature
            or self._file.read_current() != self._bytes
        ):
            raise c.DeploymentSourceError()
        _transition(before, self._owner._observation())

    @property
    def receipt_bytes(self):
        self.recheck_current()
        return self._bytes

    def close(self):
        if (
            type(self) is not ProviderReceiptFileLease
            or getattr(self, "_seal", None) is not _SEAL
        ):
            raise c.DeploymentSourceError()
        if not self._closed:
            self._closed = True
            self._owner._active = None
            self._file.close()


class ProviderReceiptChannels(f.RetainedHandle):
    def __init__(self):
        raise TypeError("receipt channels require the retained source factory")

    def _observation(self):
        if (
            type(self) is not ProviderReceiptChannels
            or getattr(self, "_seal", None) is not _SEAL
            or self._closed
        ):
            raise c.DeploymentSourceError()
        identities = [d.recheck_current() for d in self._directories]
        identity, snapshots = self._context._provider_receipt_observation()
        if identity.as_dict() != self._identity.as_dict():
            raise c.DeploymentSourceError()
        expected = identity.as_dict()
        for actual, old in zip(
            identities,
            (
                expected["incoming"]["root"],
                expected["incoming"]["namespace"],
                expected["consumed"]["root"],
                expected["consumed"]["namespace"],
            ),
            strict=True,
        ):
            if {"device": actual.device, "inode": actual.inode} != old:
                raise c.DeploymentSourceError()
        return snapshots

    def recheck_current(self):
        self._observation()
        return self._identity

    def open_receipt(self, receipt_digest):
        opened = None
        try:
            name = parse_base64url_32(receipt_digest).hex() + ".json"
            before = self._observation()
            if self._active is not None:
                raise c.DeploymentSourceError()
            scan = f._scan_namespace(
                self._directories[1], policy=_provider_namespace_policy("receipts")
            )
            entry = next((e for e in scan.finals if e.name == name), None)
            if entry is None:
                raise c.DeploymentSourceError()
            opened = f._open_final(
                self._directories[1],
                entry,
                policy=_provider_namespace_policy("receipts"),
            )
            raw = opened.read_current()
            if sha256(raw).hexdigest() != name[:-5]:
                raise DeploymentReceiptInvalid()
            try:
                parse_provider_receipt(raw)
            except ReceiptWireError:
                raise DeploymentReceiptInvalid() from None
            _transition(before, self._observation())
            result = object.__new__(ProviderReceiptFileLease)
            result._seal, result._closed = _SEAL, False
            result._owner, result._file = self, opened
            result._bytes, result._name, result._signature = raw, name, entry.signature
            self._active = result
            try:
                result.recheck_current()
            except BaseException as error:
                _close_all((result,), error)
                opened = None
                raise
            return result
        except BaseException as error:
            if opened is not None:
                _close_all((opened,), error)
            if isinstance(error, OSError):
                raise c.DeploymentSourceUnavailable() from None
            raise

    def publish_consumed(self, *, receipt_digest, expected_payloads):
        if (
            type(self) is not ProviderReceiptChannels
            or getattr(self, "_seal", None) is not _SEAL
            or self._closed
        ):
            raise c.DeploymentSourceError()
        if (
            type(expected_payloads) is not tuple
            or len(expected_payloads) > 16
            or any(
                type(raw) is not bytes or not 1 <= len(raw) <= 8192
                for raw in expected_payloads
            )
            or sum(map(len, expected_payloads)) > 131072
        ):
            raise c.DeploymentSourceError()
        payloads, ids, previous = {}, set(), None
        for raw in expected_payloads:
            value = parse_provider_consumed(raw, profile=self._profile)
            name = parse_base64url_32(value["receipt_digest"]).hex() + ".json"
            if (
                (previous is not None and name <= previous)
                or value["consumption_id"] in ids
                or value["source_context_sha256"]
                != self._identity.source_context_sha256
            ):
                raise c.DeploymentSourceError()
            previous = name
            ids.add(value["consumption_id"])
            payloads[name] = raw
        name = parse_base64url_32(receipt_digest).hex() + ".json"
        if name not in payloads or self._active is not None:
            raise c.DeploymentSourceError()
        stage = None
        try:
            before = self._observation()
            directory, policy = (
                self._directories[3],
                _provider_namespace_policy("consumed"),
            )
            for existing, _signature in dict(before)["consumed"].entries:
                if existing.endswith(".json"):
                    if existing not in payloads:
                        raise c.DeploymentSourceError()
                    p._existing_for_policy(
                        directory, existing, payloads[existing], policy=policy
                    )
            raw = payloads[name]
            if name in dict(dict(before)["consumed"].entries):
                identity = p._existing_for_policy(directory, name, raw, policy=policy)
                _transition(before, self._observation())
                return ConsumedPublicationObservation(
                    "consumed", receipt_digest, c.digest(raw), len(raw), identity
                )
            snapshot = dict(before)["consumed"]
            if (
                snapshot.final_count >= policy.final_limit
                or snapshot.stage_count >= policy.stage_limit
            ):
                raise c.DeploymentSourceError()
            stage = p._stage_payload(directory, raw, policy=policy)
            self._active = stage
            after = self._observation()
            _transition(
                before, after, namespace="consumed", stage=stage, outcome="stage"
            )
            outcome = "commit"
            try:
                p._commit_stage(directory, stage, name)
            except FileExistsError:
                outcome = "exists"
            final_signature = f.signature(f.stat_at(directory.fd, name))
            identity = p._existing_for_policy(directory, name, raw, policy=policy)
            closing = self._observation()
            if (
                identity != final_signature[0]
                or dict(dict(closing)["consumed"].entries).get(name) != final_signature
            ):
                raise c.DeploymentSourceError()
            _transition(
                after,
                closing,
                namespace="consumed",
                stage=stage,
                filename=name,
                outcome=outcome,
            )
            return ConsumedPublicationObservation(
                "consumed", receipt_digest, c.digest(raw), len(raw), identity
            )
        except BaseException as error:
            if stage is not None:
                self._active = None
                _close_all((stage,), error)
                stage = None
            if not isinstance(error, Exception):
                _close_all((self,), error)
            if isinstance(error, OSError):
                raise c.PublicationUnavailable() from None
            raise
        finally:
            if stage is not None:
                self._active = None
                stage.close()

    def _require_consumed(self, payload):
        value = parse_provider_consumed(payload, profile=self._profile)
        name = parse_base64url_32(value["receipt_digest"]).hex() + ".json"
        before = self._observation()
        if self._active is not None or name not in dict(
            dict(before)["consumed"].entries
        ):
            raise c.DeploymentSourceError()
        p._existing_for_policy(
            self._directories[3],
            name,
            payload,
            policy=_provider_namespace_policy("consumed"),
        )
        _transition(before, self._observation())

    def close(self):
        if (
            type(self) is not ProviderReceiptChannels
            or getattr(self, "_seal", None) is not _SEAL
        ):
            raise c.DeploymentSourceError()
        if not self._closed:
            self._closed = True
            handles = ([self._active] if self._active is not None else []) + list(
                reversed(self._directories)
            )
            self._directories = []
            _close_all(handles)


def open_provider_receipt_channels(context, *, profile):
    result = None
    try:
        if (
            type(context) is not ProviderSourceContext
            or type(profile) is not OriginProfile
            or OriginProfile.from_dict(profile.as_dict()) != profile
        ):
            raise c.DeploymentSourceError()
        raw = dict(context.read_current())
        from ..domain.refs import parse_canonical

        if (
            parse_canonical(raw["source-context.json"])["instance_id"]
            != profile.instance_id
            or parse_canonical(raw["source-context.json"])["origin_profile_digest"]
            != profile.digest
        ):
            raise c.DeploymentSourceError()
        identity, before = context._provider_receipt_observation()
        result = object.__new__(ProviderReceiptChannels)
        result._seal, result._closed, result._active = _SEAL, False, None
        result._context, result._profile, result._identity = context, profile, identity
        result._directories = []
        for root, uid, child in (
            (_INCOMING, 20113, "receipts"),
            (_CONSUMED, 20102, "consumed"),
        ):
            for path in (root, root / child):
                result._directories.append(
                    f.Directory.open(path, uid=uid, gid=21201, mode=0o750)
                )
        _transition(before, result._observation())
        return result
    except BaseException as error:
        if result is not None:
            _close_all((result,), error)
        if isinstance(
            error, (OSError, AttributeError, KeyError, TypeError, ValueError)
        ):
            raise c.DeploymentSourceError() from None
        raise
