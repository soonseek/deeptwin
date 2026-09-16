"""Persistent owner commands over the actual candidate and retained source journal."""

import sqlite3
import time
from contextlib import closing
from functools import wraps
from hashlib import sha256
from secrets import token_bytes
from threading import RLock
from uuid import uuid4

from ..domain.refs import (
    DomainContractError,
    EntityRef,
    canonical_json,
    parse_canonical,
    uuid_string,
)
from ..domain.request_identity import AuthenticatedRequest
from ..domain.schemas import ImmutableRecord
from ..domain.store import DomainStore, StorageError, _writer
from ..extensions.candidate_contracts import CandidateError
from ..extensions.persistence import PersistentCandidateRegistry
from ..services.owner_auth import OwnerAuthError, PersistentOwnerAuthority
from . import contracts as sources
from . import prepare_lifecycle as lifecycle
from . import prepare_records as records
from . import prepare_storage as storage
from .prepare_contracts import (
    MAX_MS,
    DeploymentPrepareError,
    epoch_ms,
    make_request,
    parse_prepare,
    require,
    stage_for_candidate,
)
from .prepare_v2_contracts import parse_cancel_v2, parse_receipt_import
from .receipt_contracts import ReceiptWireError, _ReceiptRequestMismatch, verify_receipt
from .receipt_sources import (
    ConsumptionExchangeSource,
    DeploymentReceiptInvalid,
    PublicTrustSource,
    ReceiptIngressSource,
)
from .sources import ExchangeSource, TopologySource


def closed(method):
    @wraps(method)
    def invoke(self, *args, **kwargs):
        try:
            with self._lock:
                return method(self, *args, **kwargs)
        except OwnerAuthError as error:
            raise DeploymentPrepareError(
                error.code
                if error.code in {"unauthenticated", "access_denied"}
                else "unavailable"
            ) from None
        except DeploymentPrepareError:
            raise
        except (
            sqlite3.Error,
            OSError,
            StorageError,
            DomainContractError,
            CandidateError,
        ):
            self._unavailable = True
            raise DeploymentPrepareError("unavailable") from None
        except Exception:  # noqa: BLE001 - preserve programmer failure without private diagnostic text
            raise RuntimeError("Deployment preparation failed.") from None

    return invoke


class PersistentDeploymentPrepare:
    def __init__(
        self,
        domain_store,
        owner_authority,
        candidate_registry,
        *,
        topology_source,
        exchange_source,
        public_trust_source=None,
        receipt_ingress_source=None,
        consumption_exchange_source=None,
    ):
        require(
            type(domain_store) is DomainStore
            and type(owner_authority) is PersistentOwnerAuthority
            and type(candidate_registry) is PersistentCandidateRegistry
            and owner_authority._domain is domain_store
            and candidate_registry._domain is domain_store
            and candidate_registry._owner is owner_authority,
            "unavailable",
        )
        require(
            (topology_source is None or type(topology_source) is TopologySource)
            and (exchange_source is None or type(exchange_source) is ExchangeSource),
            "unavailable",
        )
        self._domain, self._owner, self._registry = (
            domain_store,
            owner_authority,
            candidate_registry,
        )
        self._topology, self._exchange = topology_source, exchange_source
        for source, expected in (
            (public_trust_source, PublicTrustSource),
            (receipt_ingress_source, ReceiptIngressSource),
            (consumption_exchange_source, ConsumptionExchangeSource),
        ):
            require(source is None or type(source) is expected, "unavailable")
        self._trust, self._ingress, self._consumption = (
            public_trust_source,
            receipt_ingress_source,
            consumption_exchange_source,
        )
        self._profile = owner_authority.profile
        self._lock, self._highest, self._unavailable = RLock(), 0, False
        try:
            with _writer(), self._domain._connection(write=True) as db:
                records.install(
                    self._domain, db, self._profile, candidate_registry=self._registry
                )
                self._journal(db)
        except (
            ValueError,
            KeyError,
            TypeError,
            RecursionError,
            sqlite3.Error,
            OSError,
        ):
            self._unavailable = True
        except Exception:  # noqa: BLE001 - failed construction must not expose private source details
            raise RuntimeError("Deployment preparation failed.") from None

    def _authenticate(self, request, db=None, *, read=False):
        require(
            type(request) is AuthenticatedRequest
            and type(request.method) is str
            and request.method in ({"GET", "HEAD"} if read else {"POST"})
            and type(request.csrf_verified) is bool
            and (read or request.csrf_verified)
            and type(request.host) is str
            and request.host == self._profile.http_origin.split("://", 1)[1]
            and request.origin in (None, self._profile.http_origin)
            and (read or request.origin == self._profile.http_origin),
            "access_denied",
        )
        actor = self._owner.authenticate_bound(request.session, db=db)
        require(
            actor is request.session.actor
            and actor.kind == "human"
            and actor.origin == "local_session",
            "unauthenticated",
        )
        return actor

    def _journal(self, db):
        require(not self._unavailable, "unavailable")
        try:
            records.bounded_candidates(self._domain, db)
            self._registry._verify(db)
            return records.verify(self._domain, db, self._profile)
        except (
            ValueError,
            KeyError,
            TypeError,
            RecursionError,
            sqlite3.Error,
            OSError,
        ):
            self._unavailable = True
            raise DeploymentPrepareError("unavailable") from None

    def _actor_ref(self, db, actor):
        row = db.execute(
            "SELECT actor_ref FROM owner_auth_accounts WHERE owner_id=? LIMIT 2",
            (actor.id,),
        ).fetchone()
        require(row is not None, "unavailable")
        return EntityRef.from_dict(parse_canonical(row[0].encode()))

    def _replay(self, journal, actor_ref, operation, value):
        namespaces = {
            "prepare": {"deployment-prepare-v1"},
            "cancel": {"deployment-cancel-v1", "deployment-cancel-v2"},
            "receipt_import": {"deployment-receipt-import-v1"},
        }
        require(operation in namespaces, "unavailable")
        command = next(
            (
                r
                for r in journal["rows"]["commands"]
                if r["command_id"] == value["command_id"]
            ),
            None,
        )
        if command is None:
            return None
        namespace = command["namespace"]
        require(
            namespace in namespaces[operation]
            and command["actor_ref"] == storage.encoded(actor_ref.as_dict())
            and command["input_json"] == storage.encoded(value)
            and command["input_digest"]
            == lifecycle.input_digest(
                self._profile, actor_ref.as_dict(), namespace, value
            ),
            "conflict",
        )
        return parse_canonical(command["receipt_json"].encode())

    def _now(self, db, control):
        sampled = self._owner._now(db, write=True)
        self._highest = max(
            self._highest, sampled, control["clock_floor_ms"] if control else 0
        )
        require(
            type(self._highest) is int and 0 <= self._highest <= MAX_MS, "unavailable"
        )
        return self._highest

    def _floor(self, db, control, now):
        if control is not None and now > control["clock_floor_ms"]:
            return storage.advance(db, "control", control, {"clock_floor_ms": now})
        return control

    def _admit(self, request, value, operation):
        self._authenticate(request)
        with _writer(), self._domain._connection(write=True) as db:
            actor = self._authenticate(request, db)
            journal = self._journal(db)
            actor_ref = self._actor_ref(db, actor)
            replay = self._replay(journal, actor_ref, operation, value)
            if replay is not None:
                return replay, None
            now = self._now(db, journal["control"])
            self._floor(db, journal["control"], now)
        return None, now

    def _current_exchange(self, control=None):
        require(self._exchange is not None, "dependency_unavailable")
        try:
            require(self._exchange._profile == self._profile, "dependency_unavailable")
            identity = self._exchange.recheck_current().as_dict()
            raw = self._exchange.exchange_bytes
            if control is not None:
                require(
                    sources.digest(raw) == control["exchange_sha256"]
                    and len(raw) == control["exchange_size"]
                    and storage.encoded(identity) == control["exchange_identity_json"],
                    "dependency_unavailable",
                )
            return raw, identity
        except sources.DeploymentSourceError:
            raise DeploymentPrepareError("dependency_unavailable") from None

    def _acquire(self, slot_id, control):
        require(self._topology is not None, "dependency_unavailable")
        try:
            require(self._topology._profile == self._profile, "dependency_unavailable")
            self._topology.recheck_current()
            require(
                control is None or self._topology._capacity == control["slot_capacity"],
                "dependency_unavailable",
            )
            require(slot_id <= self._topology._capacity, "not_found")
            lease = self._topology.acquire_slot(slot_id)
            if (
                control is not None
                and sources.digest(lease.topology_bytes) != control["topology_sha256"]
            ):
                lease.close()
                raise DeploymentPrepareError("dependency_unavailable")
            return lease
        except sources.DeploymentSourceBusy:
            raise DeploymentPrepareError("capacity") from None
        except sources.DeploymentSourceError:
            raise DeploymentPrepareError("dependency_unavailable") from None

    def _business(self, db, journal, payload):
        bundle, candidate_ref = records.candidate(
            self._domain, db, payload["candidate_id"]
        )
        require(
            not any(
                item["row"]["extension_id"] == bundle.manifest.as_dict()["extension_id"]
                for item in journal["requests"].values()
            ),
            "conflict",
        )
        require(
            not any(
                item["row"]["slot_id"] == payload["slot_id"]
                for item in journal["requests"].values()
            ),
            "capacity",
        )
        require(
            db.execute(
                "SELECT 1 FROM domain_records WHERE kind IN "
                "('extension_installation','extension_qualification','extension_binding') LIMIT 1"
            ).fetchone()
            is None,
            "conflict",
        )
        return bundle, candidate_ref

    @closed
    def prepare(self, authenticated_request, payload):
        value = parse_prepare(payload)
        replay, now = self._admit(authenticated_request, value, "prepare")
        if replay is not None:
            return replay
        with _writer(), self._domain._connection(write=True) as db:
            actor = self._authenticate(authenticated_request, db)
            journal = self._journal(db)
            actor_ref = self._actor_ref(db, actor)
            bundle, candidate_ref = self._business(db, journal, value)
            control = journal["control"]
        with closing(self._acquire(value["slot_id"], control)) as lease:
            topology_raw = lease.topology_bytes
            exchange_raw, _ = self._current_exchange(control)
            topology, _ = records.retained_sources(
                topology_raw, exchange_raw, self._profile
            )
            try:
                stage_for_candidate(bundle, topology, lease.slot)
            except DeploymentPrepareError:
                raise DeploymentPrepareError("dependency_unavailable") from None
            require(now <= MAX_MS - value["expires_in_seconds"] * 1000, "unavailable")
            proposal = make_request(
                bundle=bundle,
                topology=topology,
                slot=lease.slot,
                profile=self._profile,
                request_id=str(uuid4()),
                nonce=token_bytes(32),
                actor_ref=actor_ref.as_dict(),
                created_ms=now,
                ttl_seconds=value["expires_in_seconds"],
            )
            raw = canonical_json(proposal)
            blobs = [
                self._domain.put_blob(data, purpose="operational")
                for data in (raw, topology_raw, exchange_raw)
            ]
            with _writer(), self._domain._connection(write=True) as db:
                actor = self._authenticate(authenticated_request, db)
                journal = self._journal(db)
                actor_ref = self._actor_ref(db, actor)
                replay = self._replay(journal, actor_ref, "prepare", value)
                if replay is not None:
                    return replay
                final_now = self._now(db, journal["control"])
                require(final_now < epoch_ms(proposal["expires_at"]), "conflict")
                bundle, candidate_ref = self._business(db, journal, value)
                try:
                    lease.recheck_current()
                except sources.DeploymentSourceError:
                    raise DeploymentPrepareError("dependency_unavailable") from None
                current_raw, identity = self._current_exchange(journal["control"])
                require(
                    current_raw == exchange_raw
                    and lease.topology_bytes == topology_raw,
                    "dependency_unavailable",
                )
                if journal["control"]:
                    require(
                        sources.digest(topology_raw)
                        == journal["control"]["topology_sha256"],
                        "dependency_unavailable",
                    )
                roots = self._domain._read_roots(db)
                anchor = {
                    "schema_version": "deployment-request-anchor-v1",
                    "request_id": proposal["request_id"],
                    "request_blob_ref": blobs[0].as_dict(),
                    "topology_blob_ref": blobs[1].as_dict(),
                    "exchange_blob_ref": blobs[2].as_dict(),
                    "candidate_ref": candidate_ref.as_dict(),
                    "topology_id": topology["topology_id"],
                    "topology_revision": 1,
                    "slot_id": value["slot_id"],
                    "reservation_revision": 1,
                    "prepare_command_id": value["command_id"],
                }
                record = ImmutableRecord.create(
                    kind="deployment_request",
                    id=proposal["request_id"],
                    version=1,
                    created_at_utc=lifecycle.instant(now),
                    actor_ref=actor_ref,
                    parent_refs=(candidate_ref,),
                    purpose="operational",
                    access_policy_ref=roots.access_policy,
                    retention_policy_ref=roots.retention_policy,
                    content=anchor,
                )
                self._domain._put_in_transaction(db, record)
                if journal["control"] is None:
                    exchange = parse_canonical(exchange_raw)
                    control = {
                        "singleton": 1,
                        "vault_id": roots.genesis.id,
                        "instance_id": self._profile.instance_id,
                        "origin_digest": self._profile.digest,
                        "topology_id": topology["topology_id"],
                        "topology_revision": 1,
                        "exchange_id": exchange["exchange_id"],
                        "exchange_revision": 1,
                        "exchange_identity_json": storage.encoded(identity),
                        "slot_capacity": len(topology["slots"]),
                        "clock_floor_ms": final_now,
                        "revision": 1,
                    }
                    for name, blob in zip(
                        ("topology", "exchange"), blobs[1:], strict=True
                    ):
                        control.update(
                            {
                                name + "_" + key: getattr(blob, key)
                                for key in ("purpose", "sha256", "size")
                            }
                        )
                    storage.insert(db, "control", control)
                else:
                    self._floor(db, journal["control"], final_now)
                from base64 import urlsafe_b64decode

                storage.insert(
                    db,
                    "requests",
                    {
                        "request_id": proposal["request_id"],
                        "vault_id": roots.genesis.id,
                        "kind": "deployment_request",
                        "version": 1,
                        "anchor_digest": record.ref.sha256,
                        "request_digest": proposal["request_digest"],
                        "nonce_hex": urlsafe_b64decode(
                            proposal["request_nonce"] + "="
                        ).hex(),
                        "topology_id": topology["topology_id"],
                        "slot_id": value["slot_id"],
                        "reservation_revision": 1,
                        "extension_id": proposal["effect_payload"]["extension_id"],
                        "created_ms": now,
                        "expires_ms": epoch_ms(proposal["expires_at"]),
                    },
                )
                item = {
                    "ref": record.ref,
                    "request": proposal,
                    "raw": raw,
                    "history": [],
                    "outbox": {},
                }
                receipt = lifecycle.transition(
                    db,
                    roots,
                    self._profile,
                    item,
                    state="prepared",
                    now=now,
                    actor_ref=actor_ref,
                    value=value,
                )
                self._journal(db)
        self._reconcile()
        return receipt

    @closed
    def read(self, authenticated_request, request_id):
        try:
            uuid_string(request_id)
        except ValueError:
            raise DeploymentPrepareError() from None
        with _writer(), self._domain._connection(write=True) as db:
            self._authenticate(authenticated_request, db, read=True)
            journal = self._journal(db)
            require(request_id in journal["requests"], "not_found")
            return lifecycle.read_body(journal["requests"][request_id])

    @closed
    def cancel(self, authenticated_request, request_id, payload):
        value = parse_cancel_v2(request_id, payload)
        replay, _ = self._admit(authenticated_request, value, "cancel")
        if replay is not None:
            return replay
        expired = False
        with _writer(), self._domain._connection(write=True) as db:
            actor = self._authenticate(authenticated_request, db)
            journal = self._journal(db)
            actor_ref = self._actor_ref(db, actor)
            replay = self._replay(journal, actor_ref, "cancel", value)
            if replay is not None:
                return replay
            require(request_id in journal["requests"], "not_found")
            item = journal["requests"][request_id]
            require(
                item["request"]["request_digest"] == value["request_digest"]
                and item["head"]["revision"] == value["expected_revision"]
                and item["history"][-1]["state"] in {"prepared", "receipt_pending"},
                "conflict",
            )
            now = self._now(db, journal["control"])
            self._floor(db, journal["control"], now)
            roots = self._domain._read_roots(db)
            expired = now >= item["row"]["expires_ms"]
            receipt = lifecycle.transition(
                db,
                roots,
                self._profile,
                item,
                state="expired" if expired else "cancelled",
                now=now,
                actor_ref=roots.actor if expired else actor_ref,
                value=None if expired else value,
            )
            self._journal(db)
        if expired:
            raise DeploymentPrepareError("conflict")
        self._reconcile()
        return receipt

    def _consumption_inventory(self, journal):
        require(
            self._consumption is not None
            and self._consumption._profile == self._profile,
            "dependency_unavailable",
        )
        try:
            identity = self._consumption.recheck_current().as_dict()
            raw = self._consumption.consumption_exchange_bytes
            binding = journal["receipt_sources"]
            if binding is not None:
                require(
                    raw == binding["raw"][2]
                    and identity == binding["identity"]["consumption"],
                    "dependency_unavailable",
                )
            observed = self._consumption.inspect_consumed()
            expected = {
                item["receipt"]["digest"]: item
                for item in journal["requests"].values()
                if item["consumption"] is not None
            }
            found = {}
            for observation in observed:
                item = expected.get(observation.receipt_digest)
                require(
                    item is not None
                    and observation.receipt_digest not in found
                    and observation.payload == lifecycle.consumed_payload(item),
                    "dependency_unavailable",
                )
                found[observation.receipt_digest] = observation
            require(
                all(
                    item["consumed_outbox"]["state"] != "published" or digest in found
                    for digest, item in expected.items()
                ),
                "dependency_unavailable",
            )
            return raw, identity, found
        except sources.DeploymentSourceError:
            raise DeploymentPrepareError("dependency_unavailable") from None

    def _current_receipt_sources(self, journal, item):
        require(
            self._trust is not None
            and self._ingress is not None
            and self._trust._profile == self._ingress._profile == self._profile,
            "dependency_unavailable",
        )
        try:
            trust_identity = self._trust.recheck_current().as_dict()
            ingress_identity = self._ingress.recheck_current().as_dict()
            trust_raw, ingress_raw = (
                self._trust.trust_bytes,
                self._ingress.ingress_bytes,
            )
            consumption_raw, consumption_identity, _ = self._consumption_inventory(
                journal
            )
            raw = [trust_raw, ingress_raw, consumption_raw]
            identity = {
                "trust": trust_identity,
                "ingress": ingress_identity,
                "consumption": consumption_identity,
            }
            _, ingress, _ = records.receipt_bindings(
                *raw, self._profile, journal["control"]
            )
            require(
                ingress["prepare_recipe_digest"]
                == item["exchange"]["deployment_recipe_digest"]
                and ingress["prepare_instance_digest"]
                == item["exchange"]["instance_configuration_digest"],
                "dependency_unavailable",
            )
            storage.validate_receipt_identity(identity)
            binding = journal["receipt_sources"]
            require(
                binding is None
                or (raw == binding["raw"] and identity == binding["identity"]),
                "dependency_unavailable",
            )
            return raw, identity
        except (
            sources.DeploymentSourceError,
            ReceiptWireError,
            DeploymentPrepareError,
        ):
            raise DeploymentPrepareError("dependency_unavailable") from None

    def _import_head(self, db, journal, value):
        require(value["request_id"] in journal["requests"], "not_found")
        item = journal["requests"][value["request_id"]]
        require(
            item["row"]["request_digest"] == value["request_digest"]
            and item["head"]["revision"] == value["expected_revision"]
            and item["history"][-1]["state"] == "prepared",
            "conflict",
        )
        require(
            db.execute(
                "SELECT 1 FROM domain_records WHERE kind IN ('extension_installation','extension_qualification','extension_binding') LIMIT 1"
            ).fetchone()
            is None,
            "conflict",
        )
        return item

    def _expire_import(self, db, journal, item, now):
        if now < item["row"]["expires_ms"]:
            return False
        roots = self._domain._read_roots(db)
        lifecycle.transition(
            db,
            roots,
            self._profile,
            item,
            state="expired",
            now=now,
            actor_ref=roots.actor,
        )
        self._journal(db)
        return True

    def _verify_selected(self, raw, item, trust_raw):
        try:
            return verify_receipt(
                raw,
                request_bytes=item["raw"],
                trust_bytes=trust_raw,
                trust_sha256=sha256(trust_raw).hexdigest(),
                profile=self._profile,
            )
        except _ReceiptRequestMismatch:
            raise DeploymentPrepareError("conflict") from None
        except ReceiptWireError:
            raise DeploymentPrepareError("invalid_input") from None

    @closed
    def import_receipt(self, authenticated_request, request_id, payload):
        value = parse_receipt_import(request_id, payload)
        replay, _ = self._admit(authenticated_request, value, "receipt_import")
        if replay is not None:
            return replay
        lease = None
        try:
            with _writer(), self._domain._connection(write=True) as db:
                actor = self._authenticate(authenticated_request, db)
                journal = self._journal(db)
                replay = self._replay(
                    journal, self._actor_ref(db, actor), "receipt_import", value
                )
                if replay is not None:
                    return replay
                item = self._import_head(db, journal, value)
                now = self._now(db, journal["control"])
                self._floor(db, journal["control"], now)
                expired = self._expire_import(db, journal, item, now)
                if not expired:
                    # Keep live inventory and its journal snapshot under the same writer:
                    # a competing commit must not look like an alien consumed final.
                    raw_sources, identity = self._current_receipt_sources(journal, item)
                    lease = self._ingress.open_receipt(value["receipt_digest"])
                    raw = lease.receipt_bytes
                    self._verify_selected(raw, item, raw_sources[0])
            if expired:
                raise DeploymentPrepareError("conflict")
            blobs = [
                self._domain.put_blob(data, purpose="operational")
                for data in (raw, *raw_sources)
            ]
            with _writer(), self._domain._connection(write=True) as db:
                actor = self._authenticate(authenticated_request, db)
                journal = self._journal(db)
                actor_ref = self._actor_ref(db, actor)
                replay = self._replay(journal, actor_ref, "receipt_import", value)
                if replay is not None:
                    return replay
                item = self._import_head(db, journal, value)
                now = self._now(db, journal["control"])
                control = self._floor(db, journal["control"], now)
                expired = self._expire_import(db, journal, item, now)
                if not expired:
                    current_raw, current_identity = self._current_receipt_sources(
                        journal, item
                    )
                    lease.recheck_current()
                    require(
                        current_raw == raw_sources
                        and current_identity == identity
                        and lease.receipt_bytes == raw,
                        "dependency_unavailable",
                    )
                    verified = self._verify_selected(
                        lease.receipt_bytes, item, current_raw[0]
                    )
                    final_now = self._now(db, control)
                    self._floor(db, control, final_now)
                    expired = self._expire_import(db, journal, item, final_now)
                    if not expired:
                        require(
                            epoch_ms(verified["completed_at"]) <= final_now, "conflict"
                        )
                        result = self._attach_receipt(
                            db,
                            journal,
                            item,
                            value,
                            actor_ref,
                            final_now,
                            blobs,
                            identity,
                            verified,
                        )
                        self._journal(db)
        except DeploymentReceiptInvalid:
            raise DeploymentPrepareError("invalid_input") from None
        except sources.DeploymentSourceError:
            raise DeploymentPrepareError("dependency_unavailable") from None
        finally:
            if lease is not None:
                lease.close()
        if expired:
            raise DeploymentPrepareError("conflict")
        self._reconcile()
        return result

    def _attach_receipt(
        self, db, journal, item, value, actor_ref, now, blobs, identity, verified
    ):
        roots = self._domain._read_roots(db)
        if journal["receipt_sources"] is None:
            source_row = {
                "singleton": 1,
                "vault_id": roots.genesis.id,
                "purpose": "operational",
                "identity_json": storage.encoded(identity),
            }
            for name, blob in zip(
                ("trust", "ingress", "consumption_exchange"), blobs[1:], strict=True
            ):
                source_row.update(
                    {name + "_sha256": blob.sha256, name + "_size": blob.size}
                )
            storage.insert(db, "receipt_sources", source_row)
        common = {
            "version": 1,
            "created_at_utc": lifecycle.instant(now),
            "actor_ref": actor_ref,
            "purpose": "operational",
            "access_policy_ref": roots.access_policy,
            "retention_policy_ref": roots.retention_policy,
        }
        anchor = {
            "schema_version": "deployment-receipt-anchor-v1",
            "request_ref": item["ref"].as_dict(),
            "import_command_id": value["command_id"],
        }
        for name, blob in zip(
            ("receipt", "trust", "ingress", "consumption_exchange"), blobs, strict=True
        ):
            anchor[name + "_blob_ref"] = blob.as_dict()
        record = ImmutableRecord.create(
            kind="deployment_receipt",
            id=item["ref"].id,
            parent_refs=(item["ref"],),
            content=anchor,
            **common,
        )
        self._domain._put_in_transaction(db, record)
        result, event = lifecycle.commit_receipt_transition(
            db,
            roots,
            self._profile,
            item,
            now=now,
            actor_ref=actor_ref,
            value=value,
            receipt_outcome=verified["outcome"],
        )
        receipt_row = storage.insert(
            db,
            "receipts",
            {
                "request_id": item["ref"].id,
                "vault_id": roots.genesis.id,
                "kind": "deployment_receipt",
                "version": 1,
                "anchor_digest": record.ref.sha256,
                "receipt_sha256": blobs[0].sha256,
                "receipt_size": blobs[0].size,
                "outcome": verified["outcome"],
                "source_singleton": 1,
                "import_command_id": value["command_id"],
                "lifecycle_revision": 2,
            },
        )
        item["receipt"] = {
            "ref": record.ref,
            "anchor": anchor,
            "row": receipt_row,
            "value": verified,
            "digest": value["receipt_digest"],
        }
        if verified["outcome"] != "succeeded":
            content = {
                "schema_version": "deployment-receipt-consumption-anchor-v1",
                "request_ref": item["ref"].as_dict(),
                "receipt_ref": record.ref.as_dict(),
                "winning_lifecycle_revision": 2,
                "consumed_at": lifecycle.stamp(now),
                "actor_ref": actor_ref.as_dict(),
                "transaction_id": value["command_id"],
                "public_event_id": event.event_id,
                "outcome": verified["outcome"],
            }
            consumption = ImmutableRecord.create(
                kind="deployment_receipt_consumption",
                id=str(uuid4()),
                parent_refs=(item["ref"], record.ref),
                content=content,
                **common,
            )
            self._domain._put_in_transaction(db, consumption)
            row = storage.insert(
                db,
                "consumptions",
                {
                    "request_id": item["ref"].id,
                    "receipt_sha256": blobs[0].sha256,
                    "consumption_id": consumption.ref.id,
                    "vault_id": roots.genesis.id,
                    "kind": "deployment_receipt_consumption",
                    "version": 1,
                    "anchor_digest": consumption.ref.sha256,
                    "lifecycle_revision": 2,
                    "command_id": value["command_id"],
                    "event_id": event.event_id,
                    "consumed_ms": now,
                },
            )
            item["consumption"] = {
                "ref": consumption.ref,
                "anchor": content,
                "row": row,
            }
            payload = lifecycle.consumed_payload(item)
            storage.insert(
                db,
                "consumed_outbox",
                {
                    "consumption_id": consumption.ref.id,
                    "payload_sha256": sha256(payload).hexdigest(),
                    "payload_size": len(payload),
                    "state": "pending",
                    "published_ms": None,
                    "revision": 1,
                },
            )
        return result

    def _reconcile(self):
        started = time.monotonic()
        try:
            with _writer(), self._domain._connection(write=True) as db:
                self._owner._check(db)
                journal = self._journal(db)
                if journal["control"] is None:
                    return
                now = self._now(db, journal["control"])
                self._floor(db, journal["control"], now)
                cancellations = [
                    (identity, "cancel")
                    for identity, item in journal["requests"].items()
                    if item["outbox"].get("cancel", {}).get("state") == "pending"
                ]
                consumptions = [
                    (identity, "consumed")
                    for identity, item in journal["requests"].items()
                    if item["consumed_outbox"] is not None
                    and item["consumed_outbox"]["state"] == "pending"
                ]
                preparations = [
                    (identity, "request")
                    for identity, item in journal["requests"].items()
                    if item["history"][-1]["state"] in {"prepared", "receipt_pending"}
                    and (
                        now >= item["row"]["expires_ms"]
                        or (
                            item["history"][-1]["state"] == "prepared"
                            and item["outbox"]["request"]["state"] == "pending"
                        )
                    )
                ]
            for identity, role in (cancellations + consumptions + preparations)[:16]:
                if time.monotonic() - started >= 1:
                    break
                self._reconcile_item(identity, role)
        except (
            DeploymentPrepareError,
            OwnerAuthError,
            sqlite3.Error,
            OSError,
            StorageError,
            DomainContractError,
            CandidateError,
        ):
            self._unavailable = True

    def _reconcile_item(self, request_id, role):
        with _writer(), self._domain._connection(write=True) as db:
            self._owner._check(db)
            journal = self._journal(db)
            item = journal["requests"][request_id]
            now = self._now(db, journal["control"])
            self._floor(db, journal["control"], now)
            roots = self._domain._read_roots(db)
            if (
                role == "request"
                and item["history"][-1]["state"] in {"prepared", "receipt_pending"}
                and now >= item["row"]["expires_ms"]
            ):
                lifecycle.transition(
                    db,
                    roots,
                    self._profile,
                    item,
                    state="expired",
                    now=now,
                    actor_ref=roots.actor,
                )
                self._journal(db)
                return
            out = (
                item["consumed_outbox"]
                if role == "consumed"
                else item["outbox"].get(role)
            )
            if out is None or out["state"] != "pending":
                return
            require(
                item["history"][-1]["state"]
                == {
                    "request": "prepared",
                    "cancel": "cancelled",
                    "consumed": "rejected",
                }[role],
                "unavailable",
            )
            lease = None
            try:
                if role == "consumed":
                    self._publish_consumed(db, journal, item, out)
                else:
                    self._current_exchange(journal["control"])
                if role == "request":
                    if journal["receipt_sources"] is not None:
                        self._consumption_inventory(journal)
                    lease = self._acquire(item["row"]["slot_id"], journal["control"])
                    lease.recheck_current()
                # Same actual writer excludes cancellation/expiry across admission and no-clobber I/O.
                before_io = self._now(db, journal["control"])
                if role == "request" and before_io >= item["row"]["expires_ms"]:
                    lifecycle.transition(
                        db,
                        roots,
                        self._profile,
                        item,
                        state="expired",
                        now=before_io,
                        actor_ref=roots.actor,
                    )
                elif role != "consumed":
                    payload = (
                        item["raw"]
                        if role == "request"
                        else lifecycle.cancellation_payload(item, profile=self._profile)
                    )
                    if role == "cancel" and item["head"]["revision"] == 3:
                        self._exchange.publish_cancellation_v2(
                            request_digest=item["request"]["request_digest"],
                            payload=payload,
                        )
                    else:
                        self._exchange.publish(
                            role=role,
                            request_digest=item["request"]["request_digest"],
                            payload=payload,
                        )
                    if role == "request" and journal["receipt_sources"] is not None:
                        self._consumption_inventory(journal)
                    acknowledged = self._now(db, journal["control"])
                    storage.advance(
                        db,
                        "outbox",
                        out,
                        {"state": "published", "published_ms": acknowledged},
                    )
            except sources.DeploymentSourceError:
                pass
            except DeploymentPrepareError as error:
                if error.code not in {"dependency_unavailable", "capacity"}:
                    raise
            finally:
                if lease is not None:
                    lease.close()
            # Re-read the current CAS row because the item may already have advanced its floor.
            control = db.execute(
                "SELECT * FROM deployment_prepare_control LIMIT 2"
            ).fetchone()
            self._floor(db, control, self._highest)
            self._journal(db)

    def _publish_consumed(self, db, journal, item, out):
        self._current_receipt_sources(journal, item)
        payload = lifecycle.consumed_payload(item)
        digest = item["receipt"]["digest"]
        observation = self._consumption.publish_consumed(
            receipt_digest=digest, payload=payload
        )
        self._current_receipt_sources(journal, item)
        _, _, inventory = self._consumption_inventory(journal)
        require(
            observation.role == "consumed"
            and observation.receipt_digest == digest
            and observation.payload_sha256
            == out["payload_sha256"]
            == sha256(payload).hexdigest()
            and observation.size_bytes == out["payload_size"] == len(payload)
            and digest in inventory
            and inventory[digest].file_identity == observation.file_identity,
            "dependency_unavailable",
        )
        acknowledged = self._now(db, journal["control"])
        storage.advance(
            db,
            "consumed_outbox",
            out,
            {"state": "published", "published_ms": acknowledged},
        )

    @closed
    def reconcile_startup(self):
        self._reconcile()
