"""Private orchestration through the existing owner service and its writer."""

import sys
import time
from base64 import urlsafe_b64decode
from contextlib import contextmanager
from hashlib import sha256
from secrets import token_bytes
from uuid import uuid4

from ..domain.refs import parse_canonical, uuid_string
from ..domain.schemas import ImmutableRecord
from ..domain.store import _writer
from . import contracts as sources
from . import prepare_records as records
from . import prepare_storage as storage
from . import provider_prepare_lifecycle as lifecycle
from . import provider_prepare_records as provider
from .prepare_contracts import MAX_MS, DeploymentPrepareError, epoch_ms, require
from .provider_prepare_contracts import (
    make_provider_request,
    parse_provider_cancel,
    parse_provider_prepare,
    validate_provider_request_sources,
)


@contextmanager
def _owned():
    handles, primary = [], None
    try:
        yield handles
    except BaseException as error:
        primary = error
        raise
    finally:
        failure = None
        for handle in reversed(handles):
            try:
                handle.close()
            except BaseException as error:  # noqa: BLE001 - close every owned handle before reraising.
                if failure is None:
                    failure = error
        if primary is None and failure is not None:
            raise failure


def _source(service, expected=None):
    require(service._provider_context is not None, "dependency_unavailable")
    files = service._provider_context.read_current()
    value = parse_canonical(files[16][1])
    require(
        value["instance_id"] == service._profile.instance_id
        and value["origin_profile_digest"] == service._profile.digest
        and (expected is None or files == expected),
        "dependency_unavailable",
    )
    return files


def _business(service, db, journal, value, *, own=None):
    require(not any("provider_row" in item and item.get("installation") is not None
                    for item in journal["requests"].values()), "conflict")
    bundle, ref = records.candidate(service._domain, db, value["candidate_id"])
    for identity, item in journal["requests"].items():
        if identity == own:
            continue
        require(
            item["row"]["extension_id"] != bundle.manifest.as_dict()["extension_id"],
            "conflict",
        )
        require(item["row"]["slot_id"] != value["slot_id"], "capacity")
        require(
            item["history"][-1]["state"]
            in {"cancelled", "expired", "rejected", "accepted"},
            "conflict",
        )
    require(
        db.execute(
            "SELECT 1 FROM domain_records WHERE kind IN ('extension_qualification','extension_binding') LIMIT 1"
        ).fetchone()
        is None,
        "conflict",
    )
    require(
        sum(
            item.get("installation") is not None
            for item in journal["requests"].values()
        )
        <= 1,
        "conflict",
    )
    return bundle, ref


def _inventory(service, db, journal, files, *, sequence=None):
    roots = service._domain._read_roots(db)
    if sequence is None:
        sequence = (
            db.execute(
                "SELECT next_sequence FROM api_event_streams WHERE vault_id=?",
                (roots.genesis.id,),
            ).fetchone()[0]
            - 1
        )
    return provider.inventory(
        service._domain,
        db,
        roots,
        service._profile,
        journal,
        source_bundle_files=files,
        at_event_sequence=sequence,
    )


def _same_inventory(left, right):
    a, b = parse_canonical(left), parse_canonical(right)
    return {**a, "at_event_sequence": b["at_event_sequence"]} == b


def _validate(raw, bundle, files, inventory, profile):
    try:
        validate_provider_request_sources(
            raw,
            candidate_bundle=bundle,
            source_bundle_files=files,
            provider_schema_bytes=provider._provider_schema_bytes(),
            inventory_bytes=inventory,
            profile=profile,
        )
    except DeploymentPrepareError:
        raise DeploymentPrepareError("dependency_unavailable") from None


def prepare_provider(service, authenticated_request, payload):
    value = parse_provider_prepare(payload)
    replay, now = service._admit(authenticated_request, value, "prepare_provider")
    if replay is not None:
        return replay
    try:
        with _writer(), service._domain._connection(write=True) as db:
            actor = service._authenticate(authenticated_request, db)
            journal = service._journal(db)
            actor_ref = service._actor_ref(db, actor)
            replay = service._replay(journal, actor_ref, "prepare_provider", value)
            if replay is not None:
                return replay
            bundle, candidate_ref = _business(service, db, journal, value)
            control = journal["control"]
            files = _source(service)
            require(
                sha256(files[16][1]).hexdigest() == value["source_context_sha256"],
                "dependency_unavailable",
            )
            inventory = _inventory(service, db, journal, files)
        with _owned() as owned:
            lease = service._acquire(value["slot_id"], control)
            owned.append(lease)
            exchange_raw, _ = service._current_exchange(control)
            require(
                lease.topology_bytes == files[2][1] and exchange_raw == files[3][1],
                "dependency_unavailable",
            )
            require(now <= MAX_MS - value["expires_in_seconds"] * 1000, "unavailable")
            try:
                raw = make_provider_request(
                    candidate_bundle=bundle,
                    source_bundle_files=files,
                    provider_schema_bytes=provider._provider_schema_bytes(),
                    inventory_bytes=inventory,
                    slot_number=value["slot_id"],
                    profile=service._profile,
                    request_id=str(uuid4()),
                    nonce=token_bytes(32),
                    actor_ref=actor_ref.as_dict(),
                    created_ms=now,
                    ttl_seconds=value["expires_in_seconds"],
                )
            except DeploymentPrepareError:
                raise DeploymentPrepareError("dependency_unavailable") from None
            proposal = parse_canonical(raw)
            blobs = [
                service._domain.put_blob(data, purpose="operational")
                for data in (raw, inventory, *(data for _, data in files))
            ]
            with _writer(), service._domain._connection(write=True) as db:
                actor = service._authenticate(authenticated_request, db)
                journal = service._journal(db)
                final_actor = service._actor_ref(db, actor)
                replay = service._replay(
                    journal, final_actor, "prepare_provider", value
                )
                if replay is not None:
                    return replay
                final_now = service._now(db, journal["control"])
                require(
                    final_now < epoch_ms(proposal["expires_at"])
                    and actor_ref == final_actor,
                    "conflict",
                )
                bundle, candidate_ref = _business(service, db, journal, value)
                _source(service, files)
                lease.recheck_current()
                current_exchange, identity = service._current_exchange(
                    journal["control"]
                )
                require(
                    current_exchange == files[3][1]
                    and lease.topology_bytes == files[2][1],
                    "dependency_unavailable",
                )
                sequence = parse_canonical(inventory)["at_event_sequence"]
                require(
                    _inventory(service, db, journal, files, sequence=sequence)
                    == inventory
                    and _same_inventory(
                        inventory, _inventory(service, db, journal, files)
                    ),
                    "conflict",
                )
                _validate(raw, bundle, files, inventory, service._profile)
                roots = service._domain._read_roots(db)
                topology, exchange = records.retained_sources(
                    files[2][1], files[3][1], service._profile
                )
                source_refs = [
                    {"name": name, "blob_ref": blob.as_dict()}
                    for (name, _), blob in zip(files, blobs[2:], strict=True)
                ]
                anchor = {
                    "schema_version": "deployment-provider-request-anchor-v2",
                    "request_id": proposal["request_id"],
                    "request_blob_ref": blobs[0].as_dict(),
                    "preserved_inventory_blob_ref": blobs[1].as_dict(),
                    "source_documents": source_refs,
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
                    created_at_utc=records.lifecycle.instant(now),
                    actor_ref=actor_ref,
                    parent_refs=(candidate_ref,),
                    purpose="operational",
                    access_policy_ref=roots.access_policy,
                    retention_policy_ref=roots.retention_policy,
                    content=anchor,
                )
                service._domain._put_in_transaction(db, record)
                if journal["control"] is None:
                    control = {
                        "singleton": 1,
                        "vault_id": roots.genesis.id,
                        "instance_id": service._profile.instance_id,
                        "origin_digest": service._profile.digest,
                        "topology_id": topology["topology_id"],
                        "topology_revision": 1,
                        "exchange_id": exchange["exchange_id"],
                        "exchange_revision": 1,
                        "exchange_identity_json": storage.encoded(identity),
                        "slot_capacity": len(topology["slots"]),
                        "clock_floor_ms": final_now,
                        "revision": 1,
                    }
                    for prefix, blob in (
                        ("topology", blobs[4]),
                        ("exchange", blobs[5]),
                    ):
                        control.update(
                            {
                                prefix + "_" + field: getattr(blob, field)
                                for field in ("purpose", "sha256", "size")
                            }
                        )
                    storage.insert(db, "control", control)
                else:
                    require(
                        journal["control"]["topology_sha256"] == blobs[4].sha256,
                        "dependency_unavailable",
                    )
                    service._floor(db, journal["control"], final_now)
                context = parse_canonical(files[16][1])
                if not journal["rows"]["provider_contexts"]:
                    storage.insert(
                        db,
                        "provider_contexts",
                        {
                            "context_id": context["context_id"],
                            "vault_id": roots.genesis.id,
                            "topology_id": topology["topology_id"],
                            "epoch": 1,
                            "worker_profile": context["worker_profile"],
                            "purpose": "operational",
                            "context_sha256": blobs[18].sha256,
                            "context_size": blobs[18].size,
                        },
                    )
                    for ordinal, ((name, _), blob) in enumerate(
                        zip(files, blobs[2:], strict=True), 1
                    ):
                        storage.insert(
                            db,
                            "provider_context_documents",
                            {
                                "context_id": context["context_id"],
                                "vault_id": roots.genesis.id,
                                "ordinal": ordinal,
                                "name": name,
                                "purpose": "operational",
                                "sha256": blob.sha256,
                                "size": blob.size,
                            },
                        )
                else:
                    retained = next(
                        item["context"]
                        for item in journal["requests"].values()
                        if "context" in item
                    )
                    require(
                        retained["files"] == files and retained["refs"] == source_refs,
                        "conflict",
                    )
                storage.insert(
                    db,
                    "requests",
                    {
                        "request_id": record.ref.id,
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
                storage.insert(
                    db,
                    "provider_requests",
                    {
                        "request_id": record.ref.id,
                        "vault_id": roots.genesis.id,
                        "context_id": context["context_id"],
                        "purpose": "operational",
                        "inventory_sha256": blobs[1].sha256,
                        "inventory_size": blobs[1].size,
                        "at_event_sequence": sequence,
                    },
                )
                item = {
                    "ref": record.ref,
                    "anchor": anchor,
                    "request": proposal,
                    "raw": raw,
                    "history": [],
                    "outbox": {},
                }
                receipt = lifecycle.transition(
                    db,
                    roots,
                    service._profile,
                    item,
                    state="prepared",
                    now=now,
                    actor_ref=actor_ref,
                    value=value,
                )
                service._journal(db)
        service._reconcile()
        return receipt
    except (sources.DeploymentSourceError, OSError):
        raise DeploymentPrepareError("dependency_unavailable") from None


def _select(journal, request_id):
    item = journal["requests"].get(request_id)
    require(
        item is not None
        and item["anchor"]["schema_version"] == "deployment-provider-request-anchor-v2",
        "not_found",
    )
    return item


def read_provider(service, authenticated_request, request_id):
    try:
        uuid_string(request_id)
    except ValueError:
        raise DeploymentPrepareError("invalid_input") from None
    with _writer(), service._domain._connection(write=True) as db:
        service._authenticate(authenticated_request, db, read=True)
        return lifecycle.read_body(_select(service._journal(db), request_id))


def cancel_provider(service, authenticated_request, request_id, payload):
    if type(payload) is dict and "receipt_digest" in payload:
        from .provider_receipt_service import cancel_pending_provider
        return cancel_pending_provider(service, authenticated_request, request_id, payload)
    value = parse_provider_cancel(request_id, payload)
    service._authenticate(authenticated_request)
    expired = False
    with _writer(), service._domain._connection(write=True) as db:
        actor = service._authenticate(authenticated_request, db)
        journal = service._journal(db)
        actor_ref = service._actor_ref(db, actor)
        replay = service._replay(journal, actor_ref, "cancel_provider", value)
        if replay is not None:
            return replay
        item = _select(journal, request_id)
        require(
            item["actor"] == actor_ref
            and item["row"]["request_digest"] == value["request_digest"]
            and item["head"]["revision"] == 1
            and item["history"][-1]["state"] == "prepared",
            "conflict",
        )
        now = service._now(db, journal["control"])
        service._floor(db, journal["control"], now)
        roots = service._domain._read_roots(db)
        expired = now >= item["row"]["expires_ms"]
        receipt = lifecycle.transition(
            db,
            roots,
            service._profile,
            item,
            state="expired" if expired else "cancelled",
            now=now,
            actor_ref=roots.actor if expired else actor_ref,
            value=None if expired else value,
        )
        service._journal(db)
    if expired:
        raise DeploymentPrepareError("conflict")
    service._reconcile()
    return receipt


def reconcile_item(service, request_id: str, role: str) -> None:
    from .provider_publication import open_provider_outbox_lease

    require(role in {"request", "cancel"}, "unavailable")
    with _writer(), service._domain._connection(write=True) as db:
        service._owner._check(db)
        journal = service._journal(db)
        item = _select(journal, request_id)
        roots = service._domain._read_roots(db)
        service._now(db, journal["control"])
        if role == "request" and item["history"][-1]["state"] == "receipt_pending":
            from .provider_receipt_service import _expire
            service._floor(db, journal["control"], service._highest)
            _expire(service, db, item, service._highest)
            service._journal(db)
            return
        out = item["outbox"].get(role)
        if out is None or out["state"] == "suppressed":
            return

        def expire(sampled):
            if (
                role == "request"
                and item["history"][-1]["state"] == "prepared"
                and sampled >= item["row"]["expires_ms"]
            ):
                lifecycle.transition(
                    db,
                    roots,
                    service._profile,
                    item,
                    state="expired",
                    now=sampled,
                    actor_ref=roots.actor,
                )
                return True
            return False

        def before_deadline():
            sampled = service._now(db, journal["control"])
            return not expire(sampled) and time.monotonic() < getattr(
                service, "_provider_reconcile_deadline", float("inf")
            )

        try:
            files = _source(service, item["context"]["files"])
            all_items = sorted(
                (
                    other
                    for other in journal["requests"].values()
                    if "provider_row" in other
                ),
                key=lambda other: urlsafe_b64decode(
                    other["request"]["request_digest"] + "="
                ),
            )
            expected = tuple(
                (
                    r,
                    other["raw"]
                    if r == "request"
                    else lifecycle.cancellation_payload(
                        other, profile=service._profile
                    ),
                )
                for r in ("request", "cancel")
                for other in all_items
                if r in other["outbox"]
            )
            with _owned() as owned:
                publisher = open_provider_outbox_lease(
                    service._provider_context,
                    profile=service._profile,
                    expected_payloads=expected,
                    expected_receipts=tuple(other["receipt"]["raw"] for other in all_items if other["receipt"] is not None and "cancel" in other["outbox"]),
                )
                owned.append(publisher)
                # A database acknowledgement is authoritative only with its actual final.
                for other in all_items:
                    for other_role, marker in other["outbox"].items():
                        if marker["state"] == "published":
                            require(
                                publisher.observe_existing(
                                    role=other_role,
                                    request_digest=other["request"]["request_digest"],
                                )
                                is not None,
                                "dependency_unavailable",
                            )
                observation = publisher.observe_existing(
                    role=role, request_digest=item["request"]["request_digest"]
                )
                if observation is None:
                    require(out["state"] == "pending", "dependency_unavailable")
                    if not before_deadline():
                        return
                    lease = None
                    if role == "request":
                        require(
                            item["history"][-1]["state"] == "prepared", "unavailable"
                        )
                        value = {
                            "candidate_id": item["anchor"]["candidate_ref"]["id"],
                            "slot_id": item["row"]["slot_id"],
                        }
                        bundle, ref = _business(
                            service, db, journal, value, own=request_id
                        )
                        require(
                            ref.as_dict() == item["anchor"]["candidate_ref"],
                            "dependency_unavailable",
                        )
                        lease = service._acquire(value["slot_id"], journal["control"])
                        owned.append(lease)
                        service._current_exchange(journal["control"])
                        require(
                            lease.topology_bytes == files[2][1]
                            and _same_inventory(
                                item["inventory_raw"],
                                _inventory(service, db, journal, files),
                            ),
                            "dependency_unavailable",
                        )
                        _validate(
                            item["raw"],
                            bundle,
                            files,
                            item["inventory_raw"],
                            service._profile,
                        )
                    else:
                        require(
                            item["history"][-1]["state"] == "cancelled", "unavailable"
                        )
                    _source(service, files)
                    if not before_deadline():
                        return
                    attempt = publisher.stage(
                        role=role, request_digest=item["request"]["request_digest"]
                    )
                    owned.append(attempt)
                    _source(service, files)
                    if lease is not None:
                        lease.recheck_current()
                        service._current_exchange(journal["control"])
                        _business(service, db, journal, value, own=request_id)
                        require(
                            _same_inventory(
                                item["inventory_raw"],
                                _inventory(service, db, journal, files),
                            ),
                            "dependency_unavailable",
                        )
                    if not before_deadline():
                        return
                    observation = publisher.commit(attempt)
                require(observation is not None, "dependency_unavailable")
                acknowledged = service._now(db, journal["control"])
                if out["state"] == "pending":
                    item["outbox"][role] = storage.advance(
                        db,
                        "outbox",
                        out,
                        {"state": "published", "published_ms": acknowledged},
                    )
                expire(acknowledged)
        except (sources.DeploymentSourceError, OSError):
            expire(service._now(db, journal["control"]))
        except DeploymentPrepareError as error:
            if error.code not in {
                "dependency_unavailable",
                "capacity",
                "conflict",
                "not_found",
            }:
                raise
            expire(service._now(db, journal["control"]))
        finally:
            if sys.exc_info()[0] is None:
                control = db.execute(
                    "SELECT * FROM deployment_prepare_control LIMIT 2"
                ).fetchone()
                service._floor(db, control, service._highest)
                service._journal(db)
