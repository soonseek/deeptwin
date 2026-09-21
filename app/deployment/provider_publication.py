"""Fixed provider outbox publication bound to a borrowed, retained source context.

Exact source coherence is not candidate, history, owner, or live-send admission.
"""

from pathlib import Path

from app.domain.refs import canonical_json, parse_canonical, DomainContractError
from .provider_receipt_contracts import parse_provider_pending_cancellation, parse_provider_receipt, make_provider_pending_cancellation, verify_provider_receipt
from .receipt_contracts import ReceiptWireError
from app.operations.setup import OriginProfile, SetupContractError, parse_base64url_32

from . import contracts as c
from . import files as f
from . import mounts as m
from . import publication as p
from ._provider_source_files import _provider_namespace_policy
from .prepare_contracts import DeploymentPrepareError, epoch_ms
from .provider_prepare_contracts import (
    make_provider_cancellation,
    parse_provider_cancellation,
    parse_provider_inventory,
    parse_provider_request,
)
from .provider_source_contracts import parse_provider_context
from .provider_sources import ProviderSourceContext

_ROOT = Path("/run/deeptwin/provider-deployment-outbox")
_ROLES = {"request": "requests", "cancel": "cancelled"}
_SEAL = object()


def _close_all(handles, primary=None):
    failure = primary
    for handle in handles:
        try:
            handle.close()
        except BaseException as error:  # noqa: BLE001 - exhaust owned cleanup
            if failure is None:
                failure = error
    if primary is None and failure is not None:
        raise failure


def _parse_payloads(expected_payloads, profile):
    if type(profile) is not OriginProfile:
        raise c.DeploymentSourceError()
    try:
        if OriginProfile.from_dict(profile.as_dict()).as_dict() != profile.as_dict():
            raise c.DeploymentSourceError()
    except (AttributeError, SetupContractError):
        raise c.DeploymentSourceError() from None
    if type(expected_payloads) is not tuple or len(expected_payloads) > 32:
        raise c.DeploymentSourceError()
    counts, total = {"request": 0, "cancel": 0}, 0
    for pair in expected_payloads:
        if type(pair) is not tuple or len(pair) != 2:
            raise c.DeploymentSourceError()
        role, raw = pair
        if type(role) is not str or role not in _ROLES or type(raw) is not bytes:
            raise c.DeploymentSourceError()
        policy = _provider_namespace_policy(_ROLES[role])
        counts[role] += 1
        total += len(raw)
        if (
            not 0 < len(raw) <= policy.payload_cap
            or counts[role] > policy.final_limit
            or total > 1179648
        ):
            raise c.DeploymentSourceError()
    parsed, requests, ids = {}, {}, set()
    previous = None
    for role, raw in expected_payloads:
        pending = role == "cancel" and parse_canonical(raw).get("schema") == "deployment-provider-cancellation-v2"
        value = (parse_provider_request if role == "request" else parse_provider_pending_cancellation if pending else parse_provider_cancellation)(raw, profile=profile)
        digest = value["request_digest"]
        order = (0 if role == "request" else 1, parse_base64url_32(digest).hex())
        if previous is not None and order <= previous:
            raise c.DeploymentSourceError()
        previous = order
        if role == "request":
            if value["request_id"] in ids:
                raise c.DeploymentSourceError()
            ids.add(value["request_id"])
            requests[digest] = raw
        elif (
            digest not in requests
            or (not pending and make_provider_cancellation(
                requests[digest],
                profile=profile,
                cancelled_ms=epoch_ms(value["cancelled_at"]),
            )
            != raw)
        ):
            raise c.DeploymentSourceError()
        parsed[(role, digest)] = (raw, value)
    return parsed


def _receipt_joins(parsed, expected_receipts, files, profile):
    if type(expected_receipts) is not tuple or len(expected_receipts) > 16 or any(type(raw) is not bytes or not 0 < len(raw) <= 16384 for raw in expected_receipts) or sum(map(len, expected_receipts)) > 262144 or sum(len(raw) for raw, _ in parsed.values()) + sum(map(len, expected_receipts)) > 1441792:
        raise c.DeploymentSourceError()
    pending = {digest: (raw, value) for (role, digest), (raw, value) in parsed.items() if role == "cancel" and value["schema"] == "deployment-provider-cancellation-v2"}
    seen, ids, hashes, previous = set(), set(), set(), None
    for raw in expected_receipts:
        value = parse_provider_receipt(raw)
        digest = value["request_digest"]
        order = parse_base64url_32(digest).hex()
        hashed = c.digest(raw)
        if (previous is not None and order <= previous) or digest in seen or value["request_id"] in ids or hashed in hashes or digest not in pending or ("request", digest) not in parsed or value["outcome"] != "succeeded":
            raise c.DeploymentSourceError()
        previous = order
        seen.add(digest)
        ids.add(value["request_id"])
        hashes.add(hashed)
        request = parsed[("request", digest)][0]
        verify_provider_receipt(raw, request_bytes=request, trust_bytes=dict(files)["provider-trust-set.json"], source_bundle_files=files, profile=profile)
        marker, cancellation = pending[digest]
        if make_provider_pending_cancellation(request_bytes=request, receipt_bytes=raw, profile=profile, cancelled_ms=epoch_ms(cancellation["cancelled_at"])) != marker:
            raise c.DeploymentSourceError()
    if seen != set(pending):
        raise c.DeploymentSourceError()


def _join_sources(parsed, raw, profile):
    context = parse_provider_context(raw["source-context.json"])
    original = c.parse_instance(raw["original-prepare-instance.json"])
    topology = c.parse_topology(
        raw["original-topology.json"],
        profile=profile,
        recipe_sha256=c.digest(raw["original-prepare-recipe.json"]),
        platform=original["platform"],
    )
    if original["origin_profile"] != profile.as_dict():
        raise c.DeploymentSourceError()
    slots = topology["slots"]
    for (role, _), (_, value) in parsed.items():
        if role != "request":
            continue
        effect = value["effect_payload"]
        inventory_raw = canonical_json(effect["preserved_inventory"])
        inventory = parse_provider_inventory(inventory_raw)
        if (
            effect["source_context"]
            != {
                "context_id": context["context_id"],
                "epoch": context["epoch"],
                "sha256": c.digest(raw["source-context.json"]),
                "size_bytes": len(raw["source-context.json"]),
            }
            or effect["geometry"]
            != {
                "sha256": c.digest(raw["geometry.json"]),
                "size_bytes": len(raw["geometry.json"]),
            }
            or inventory["instance_id"] != profile.instance_id
            or inventory["origin_profile_digest"] != profile.digest
            or inventory["topology_id"] != topology["topology_id"]
            or inventory["topology_sha256"] != c.digest(raw["original-topology.json"])
            or effect["preserved_inventory_sha256"] != c.digest(inventory_raw)
            or effect["selected_platform_entry"]["platform"] != topology["platform"]
        ):
            raise c.DeploymentSourceError()
        service = effect["new_service_effect"]
        matches = [
            slot
            for slot in slots
            if slot["service_identity"] == service["service_identity"]
            and service["socket_mounts"] == [slot["socket_mount"]]
        ]
        if len(matches) != 1 or service["named_volume_mounts"]:
            raise c.DeploymentSourceError()
        selected = matches[0]["slot_number"]
        for entry in inventory["installations"]:
            number = entry["slot_id"]
            if (
                number > len(slots)
                or number == selected
                or slots[number - 1]["service_identity"] != entry["service_identity"]
                or entry["extension_id"] == effect["extension_id"]
            ):
                raise c.DeploymentSourceError()


def _transition(
    before, after, *, namespace=None, stage=None, filename=None, outcome=None
):
    for (name, old), (new_name, new) in zip(before, after, strict=True):
        if name != new_name:
            raise c.DeploymentSourceError()
        if name != namespace:
            if old != new:
                raise c.DeploymentSourceError()
            continue
        # Only size/mtime/ctime of the affected directory may change.
        if old.directory_signature[:2] != new.directory_signature[:2]:
            raise c.DeploymentSourceError()
        left, right = dict(old.entries), dict(new.entries)
        if outcome == "stage":
            if stage.name in left or right.pop(stage.name, None) != stage.signature:
                raise c.DeploymentSourceError()
        else:
            if left.get(stage.name) != stage.signature:
                raise c.DeploymentSourceError()
            if outcome == "commit":
                left.pop(stage.name)
                final = right.pop(filename, None)
                # Rename preserves identity, links, size and mtime; ctime changes.
                if (
                    filename in left
                    or stage.name in right
                    or final is None
                    or final[:4] != stage.signature[:4]
                ):
                    raise c.DeploymentSourceError()
            elif outcome == "exists":
                if filename not in left and right.pop(filename, None) is None:
                    raise c.DeploymentSourceError()
            else:
                raise c.DeploymentSourceError()
        if left != right:
            raise c.DeploymentSourceError()


class ProviderPublicationAttempt(f.RetainedHandle):
    def __init__(self):
        raise TypeError("provider attempt requires its owning lease")

    def close(self):
        if (
            type(self) is not ProviderPublicationAttempt
            or getattr(self, "_seal", None) is not _SEAL
        ):
            raise c.DeploymentSourceError()
        if self._closed:
            return
        if self._lease._active is not self:
            raise c.DeploymentSourceError()
        self._closed = True
        self._lease._active = None
        self._stage.close()


class ProviderOutboxLease(f.RetainedHandle):
    def __init__(self):
        raise TypeError("provider lease requires the fixed factory")

    def _observation(self):
        if (
            type(self) is not ProviderOutboxLease
            or getattr(self, "_seal", None) is not _SEAL
            or self._closed
        ):
            raise c.DeploymentSourceError()
        identities = tuple(
            directory.recheck_current() for directory in self._directories
        )
        observed, snapshots = self._context._provider_publication_observation()
        if identities != observed:
            raise c.DeploymentSourceError()
        return snapshots

    def _selection(self, role, request_digest):
        if (
            type(role) is not str
            or role not in _ROLES
            or type(request_digest) is not str
        ):
            raise c.DeploymentSourceError()
        try:
            filename = parse_base64url_32(request_digest).hex() + ".json"
            payload = self._payloads[(role, request_digest)]
        except (SetupContractError, KeyError, AttributeError):
            raise c.DeploymentSourceError() from None
        namespace = _ROLES[role]
        directory = self._directories[1 if role == "request" else 2]
        return (
            payload,
            filename,
            namespace,
            directory,
            _provider_namespace_policy(namespace),
        )

    def _outgoing(self, snapshots):
        found = {}
        for role, namespace in _ROLES.items():
            directory = self._directories[1 if role == "request" else 2]
            policy = _provider_namespace_policy(namespace)
            for name, _ in dict(snapshots)[namespace].entries:
                if not name.endswith(".json"):
                    continue
                key = (role, name)
                if key not in self._finals:
                    raise c.DeploymentSourceError()
                digest, raw = self._finals[key]
                identity = p._existing_for_policy(directory, name, raw, policy=policy)
                found[(role, digest)] = p.PublicationObservation(
                    role, digest, c.digest(raw), len(raw), identity
                )
        return found

    def _failed(self, error):
        if not isinstance(error, Exception):
            _close_all((self,), error)
        if isinstance(error, OSError):
            raise c.PublicationUnavailable() from None

    def observe_existing(self, *, role: str, request_digest: str):
        try:
            before = self._observation()
            self._selection(role, request_digest)
            result = self._outgoing(before).get((role, request_digest))
            _transition(before, self._observation())
            return result
        except BaseException as error:
            self._failed(error)
            raise

    def stage(self, *, role: str, request_digest: str):
        stage = None
        try:
            before = self._observation()
            raw, _filename, namespace, directory, policy = self._selection(
                role, request_digest
            )
            if self._active is not None or (role, request_digest) in self._outgoing(
                before
            ):
                raise c.DeploymentSourceError()
            snapshot = dict(before)[namespace]
            if (
                snapshot.final_count >= policy.final_limit
                or snapshot.stage_count >= policy.stage_limit
            ):
                raise c.DeploymentSourceError()
            stage = p._stage_payload(directory, raw, policy=policy)
            _transition(
                before,
                self._observation(),
                namespace=namespace,
                stage=stage,
                outcome="stage",
            )
            result = object.__new__(ProviderPublicationAttempt)
            result._seal, result._closed = _SEAL, False
            result._lease, result._stage = self, stage
            result._role, result._digest = role, request_digest
            self._active = result
            return result
        except BaseException as error:
            if stage is not None:
                _close_all((stage,), error)
            self._failed(error)
            raise

    def commit(self, attempt: ProviderPublicationAttempt):
        # Refuse alien/hollow arguments before taking any ownership of them.
        if (
            type(self) is not ProviderOutboxLease
            or getattr(self, "_seal", None) is not _SEAL
            or type(attempt) is not ProviderPublicationAttempt
            or getattr(attempt, "_seal", None) is not _SEAL
            or getattr(self, "_active", None) is not attempt
            or attempt._lease is not self
            or attempt._closed
        ):
            raise c.DeploymentSourceError()
        primary = None
        try:
            before = self._observation()
            raw, filename, namespace, directory, policy = self._selection(
                attempt._role, attempt._digest
            )
            self._outgoing(before)
            outcome = "commit"
            try:
                p._commit_stage(directory, attempt._stage, filename)
            except FileExistsError:
                outcome = "exists"
            final_signature = f.signature(f.stat_at(directory.fd, filename))
            identity = p._existing_for_policy(directory, filename, raw, policy=policy)
            after = self._observation()
            if (
                identity != final_signature[0]
                or dict(dict(after)[namespace].entries).get(filename) != final_signature
            ):
                raise c.DeploymentSourceError()
            _transition(
                before,
                after,
                namespace=namespace,
                stage=attempt._stage,
                filename=filename,
                outcome=outcome,
            )
            return p.PublicationObservation(
                attempt._role, attempt._digest, c.digest(raw), len(raw), identity
            )
        except BaseException as error:
            primary = error
            self._failed(error)
            raise
        finally:
            try:
                _close_all((attempt,), primary)
            except BaseException as error:
                self._failed(error)
                raise

    def close(self):
        if (
            type(self) is not ProviderOutboxLease
            or getattr(self, "_seal", None) is not _SEAL
        ):
            raise c.DeploymentSourceError()
        if not self._closed:
            self._closed = True
            handles = (() if self._active is None else (self._active,)) + tuple(
                reversed(self._directories)
            )
            _close_all(handles)


def open_provider_outbox_lease(
    context: ProviderSourceContext,
    *,
    profile: OriginProfile,
    expected_payloads: tuple[tuple[str, bytes], ...],
    expected_receipts: tuple[bytes, ...] = (),
) -> ProviderOutboxLease:
    result = None
    try:
        parsed = _parse_payloads(expected_payloads, profile)
        if type(expected_receipts) is not tuple or len(expected_receipts) > 16 or any(type(raw) is not bytes or not 0 < len(raw) <= 16384 for raw in expected_receipts):
            raise c.DeploymentSourceError()
        if type(context) is not ProviderSourceContext:
            raise c.DeploymentSourceError()
        m.native_platform()
        identities, before = context._provider_publication_observation()
        files = context.read_current()
        _join_sources(parsed, dict(files), profile)
        _receipt_joins(parsed, expected_receipts, files, profile)
        result = object.__new__(ProviderOutboxLease)
        result._seal, result._closed, result._active = _SEAL, False, None
        result._context, result._directories = context, []
        result._payloads = {key: raw for key, (raw, _) in parsed.items()}
        result._finals = {
            (role, parse_base64url_32(digest).hex() + ".json"): (digest, raw)
            for (role, digest), raw in result._payloads.items()
        }
        for path, expected in zip(
            (_ROOT, _ROOT / "requests", _ROOT / "cancelled"), identities, strict=True
        ):
            directory = f.Directory.open(path, uid=20102, gid=21201, mode=0o750)
            result._directories.append(directory)
            if directory.identity != expected:
                raise c.DeploymentSourceError()
        result._outgoing(before)
        _transition(before, result._observation())
        return result
    except BaseException as error:
        if result is not None:
            _close_all((result,), error)
        if isinstance(
            error,
            (DeploymentPrepareError, ReceiptWireError, DomainContractError, SetupContractError, AttributeError, KeyError),
        ):
            raise c.DeploymentSourceError() from None
        if isinstance(error, OSError):
            raise c.PublicationUnavailable() from None
        raise
