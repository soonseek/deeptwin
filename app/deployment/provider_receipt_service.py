"""Provider receipt operations delegated by the existing owner service."""

from ..domain.store import _writer
from hashlib import sha256
import sys
import time
from . import prepare_storage as storage
from .prepare_contracts import DeploymentPrepareError, require, epoch_ms
from . import provider_prepare_service as prepared, provider_prepare_lifecycle
from . import (
    provider_receipt_lifecycle as lifecycle,
    provider_receipt_records as records,
)
from .provider_receipt_contracts import (
    parse_provider_receipt_import,
    parse_provider_pending_cancel,
    verify_provider_receipt,
    ReceiptRequestMismatch,
)
from .provider_receipt_sources import open_provider_receipt_channels
from .receipt_contracts import ReceiptWireError
from .receipt_sources import DeploymentReceiptInvalid
from .contracts import DeploymentSourceError


def _head(journal, value, state):
    item = prepared._select(journal, value["request_id"])
    require(
        item["request"]["request_digest"] == value["request_digest"]
        and item["head"]["revision"] == value["expected_revision"]
        and item["history"][-1]["state"] == state,
        "conflict",
    )
    return item


def _expire(service, db, item, now):
    if now < item["row"]["expires_ms"]:
        return False
    roots = service._domain._read_roots(db)
    helper = lifecycle if item["receipt"] else provider_prepare_lifecycle
    helper.transition(
        db,
        roots,
        service._profile,
        item,
        state="expired",
        now=now,
        actor_ref=roots.actor,
    )
    service._journal(db)
    return True


def _managed(service, db, journal, item):
    bundle, _ = prepared._business(
        service,
        db,
        journal,
        {
            "candidate_id": item["anchor"]["candidate_ref"]["id"],
            "slot_id": item["row"]["slot_id"],
        },
        own=item["ref"].id,
    )
    require(
        not any(
            v["installation"] is not None
            and (
                "context" in v
                or v["row"]["extension_id"] == item["row"]["extension_id"]
                or v["row"]["slot_id"] == item["row"]["slot_id"]
            )
            for v in journal["requests"].values()
        ),
        "conflict",
    )
    files = prepared._source(service, item["context"]["files"])
    require(
        prepared._same_inventory(
            item["inventory_raw"], prepared._inventory(service, db, journal, files)
        ),
        "conflict",
    )
    prepared._validate(
        item["raw"], bundle, files, item["inventory_raw"], service._profile
    )
    return files


def _identity(journal, channels):
    identity = channels.recheck_current().as_dict()
    binding = journal["provider_receipt_sources"]
    require(
        binding is None or binding["identity"] == identity, "dependency_unavailable"
    )
    return identity


def _verify(service, item, raw, files):
    try:
        return verify_provider_receipt(
            raw,
            request_bytes=item["raw"],
            trust_bytes=dict(files)["provider-trust-set.json"],
            source_bundle_files=files,
            profile=service._profile,
        )
    except ReceiptRequestMismatch:
        raise DeploymentPrepareError("conflict") from None
    except ReceiptWireError:
        raise DeploymentPrepareError("invalid_input") from None


def import_provider_receipt(service, authenticated_request, request_id, payload):
    value = parse_provider_receipt_import(request_id, payload)
    replay, _ = service._admit(authenticated_request, value, "import_provider_receipt")
    if replay is not None:
        return replay
    expired = False
    try:
        with prepared._owned() as owned:
            with _writer(), service._domain._connection(write=True) as db:
                actor = service._authenticate(authenticated_request, db)
                journal = service._journal(db)
                actor_ref = service._actor_ref(db, actor)
                replay = service._replay(
                    journal, actor_ref, "import_provider_receipt", value
                )
                if replay is not None:
                    return replay
                item = _head(journal, value, "prepared")
                now = service._now(db, journal["control"])
                service._floor(db, journal["control"], now)
                expired = _expire(service, db, item, now)
                if not expired:
                    files = _managed(service, db, journal, item)
                    channels = open_provider_receipt_channels(
                        service._provider_context, profile=service._profile
                    )
                    owned.append(channels)
                    identity = _identity(journal, channels)
                    lease = channels.open_receipt(value["receipt_digest"])
                    owned.append(lease)
                    raw = lease.receipt_bytes
                    _verify(service, item, raw, files)
            if expired:
                raise DeploymentPrepareError("conflict")
            blob = service._domain.put_blob(raw, purpose="operational")
            with _writer(), service._domain._connection(write=True) as db:
                actor = service._authenticate(authenticated_request, db)
                journal = service._journal(db)
                final_actor = service._actor_ref(db, actor)
                replay = service._replay(
                    journal, final_actor, "import_provider_receipt", value
                )
                if replay is not None:
                    return replay
                item = _head(journal, value, "prepared")
                require(actor_ref == final_actor == item["actor"], "conflict")
                now = service._now(db, journal["control"])
                control = service._floor(db, journal["control"], now)
                expired = _expire(service, db, item, now)
                if not expired:
                    current = _managed(service, db, journal, item)
                    require(
                        current == files
                        and _identity(journal, channels) == identity
                        and lease.receipt_bytes == raw,
                        "dependency_unavailable",
                    )
                    verified = _verify(service, item, raw, current)
                    now = service._now(db, control)
                    service._floor(db, control, now)
                    expired = _expire(service, db, item, now)
                    if not expired:
                        require(epoch_ms(verified["completed_at"]) <= now, "conflict")
                        result = records.attach_receipt(
                            service,
                            db,
                            journal,
                            item,
                            value,
                            actor_ref,
                            now,
                            blob,
                            raw,
                            identity,
                            verified,
                        )
                        service._journal(db)
    except DeploymentReceiptInvalid:
        raise DeploymentPrepareError("invalid_input") from None
    except DeploymentSourceError:
        raise DeploymentPrepareError("dependency_unavailable") from None
    if expired:
        raise DeploymentPrepareError("conflict")
    service._reconcile()
    return result


def cancel_pending_provider(service, authenticated_request, request_id, payload):
    value = parse_provider_pending_cancel(request_id, payload)
    service._authenticate(authenticated_request)
    with _writer(), service._domain._connection(write=True) as db:
        actor = service._authenticate(authenticated_request, db)
        journal = service._journal(db)
        actor_ref = service._actor_ref(db, actor)
        replay = service._replay(journal, actor_ref, "cancel_provider", value)
        if replay is not None:
            return replay
        item = _head(journal, value, "receipt_pending")
        require(
            item["actor"] == actor_ref
            and item["receipt"]["digest"] == value["receipt_digest"]
            and item["receipt"]["value"]["outcome"] == "succeeded",
            "conflict",
        )
        now = service._now(db, journal["control"])
        service._floor(db, journal["control"], now)
        expired = _expire(service, db, item, now)
        if not expired:
            result = lifecycle.transition(
                db,
                service._domain._read_roots(db),
                service._profile,
                item,
                state="cancelled",
                now=now,
                actor_ref=actor_ref,
                value=value,
            )
            service._journal(db)
    if expired:
        raise DeploymentPrepareError("conflict")
    service._reconcile()
    return result


def reconcile_consumed(service, request_id):
    with _writer(), service._domain._connection(write=True) as db:
        service._owner._check(db)
        journal = service._journal(db)
        item = prepared._select(journal, request_id)
        out = item["consumed_outbox"]
        if out is None or out["state"] != "pending":
            return
        try:
            files = prepared._source(service, item["context"]["files"])
            intents = sorted(
                (
                    other
                    for other in journal["requests"].values()
                    if "context" in other and other["consumed_outbox"] is not None
                ),
                key=lambda other: other["receipt"]["row"]["receipt_sha256"],
            )
            payloads = tuple(lifecycle.consumed_payload(other) for other in intents)
            with prepared._owned() as owned:
                channels = open_provider_receipt_channels(
                    service._provider_context, profile=service._profile
                )
                owned.append(channels)
                _identity(journal, channels)
                for other, raw in zip(intents, payloads, strict=True):
                    if other["consumed_outbox"]["state"] == "published":
                        channels._require_consumed(raw)
                if time.monotonic() >= getattr(
                    service, "_provider_reconcile_deadline", float("inf")
                ):
                    return
                observed = channels.publish_consumed(
                    receipt_digest=item["receipt"]["digest"], expected_payloads=payloads
                )
                raw = lifecycle.consumed_payload(item)
                require(
                    observed.role == "consumed"
                    and observed.receipt_digest == item["receipt"]["digest"]
                    and observed.payload_sha256
                    == out["payload_sha256"]
                    == sha256(raw).hexdigest()
                    and observed.size_bytes == out["payload_size"] == len(raw),
                    "dependency_unavailable",
                )
                prepared._source(service, files)
                _identity(journal, channels)
                now = service._now(db, journal["control"])
                require(now >= item["consumption"]["row"]["consumed_ms"], "unavailable")
                storage.advance(
                    db,
                    "consumed_outbox",
                    out,
                    {"state": "published", "published_ms": now},
                )
        except (DeploymentSourceError, OSError):
            pass
        except DeploymentPrepareError as error:
            if error.code not in {"dependency_unavailable", "capacity"}:
                raise
        finally:
            if sys.exc_info()[0] is None:
                control = db.execute(
                    "SELECT * FROM deployment_prepare_control LIMIT 2"
                ).fetchone()
                service._floor(db, control, service._highest)
                service._journal(db)


def consume_provider_receipt(service, authenticated_request, request_id, payload):
    from ..workers.broker import Deadline
    from .provider_receipt_contracts import parse_provider_consume
    from .provider_stage_observer import (
        observe_provider_stage_postcondition,
        parse_provider_stage_evidence,
        StagePostconditionError,
    )

    value = parse_provider_consume(request_id, payload)
    replay, _ = service._admit(authenticated_request, value, "consume_provider_receipt")
    if replay is not None:
        return replay
    try:
        with prepared._owned() as owned:
            with _writer(), service._domain._connection(write=True) as db:
                actor = service._authenticate(authenticated_request, db)
                journal = service._journal(db)
                actor_ref = service._actor_ref(db, actor)
                replay = service._replay(
                    journal, actor_ref, "consume_provider_receipt", value
                )
                if replay is not None:
                    return replay
                item = _head(journal, value, "receipt_pending")
                require(
                    item["actor"] == actor_ref
                    and item["receipt"]["digest"] == value["receipt_digest"]
                    and item["receipt"]["value"]["outcome"] == "succeeded",
                    "conflict",
                )
                now = service._now(db, journal["control"])
                service._floor(db, journal["control"], now)
                expired = _expire(service, db, item, now)
                if not expired:
                    files = _managed(service, db, journal, item)
                    channels = open_provider_receipt_channels(
                        service._provider_context, profile=service._profile
                    )
                    owned.append(channels)
                    identity = _identity(journal, channels)
                    expected = records.expected_stage_identity(
                        service._domain, db, service._profile, item
                    )
                    facts = {
                        "request_bytes": item["raw"],
                        "receipt_bytes": item["receipt"]["raw"],
                        "slot_number": item["row"]["slot_id"],
                        "source_context_sha256": item["request"]["effect_payload"][
                            "source_context"
                        ]["sha256"],
                        "preserved_inventory_sha256": item["request"]["effect_payload"][
                            "preserved_inventory_sha256"
                        ],
                    }
            if expired:
                raise DeploymentPrepareError("conflict")
            evidence = observe_provider_stage_postcondition(
                request_id=request_id,
                request_digest=value["request_digest"],
                receipt_digest=value["receipt_digest"],
                expected=expected,
                instance_id=service._profile.instance_id,
                deadline=Deadline.after_ms(2000),
                **facts,
            )
            blob = service._domain.put_blob(
                evidence.content_bytes, purpose="operational"
            )
            with _writer(), service._domain._connection(write=True) as db:
                actor = service._authenticate(authenticated_request, db)
                journal = service._journal(db)
                final_actor = service._actor_ref(db, actor)
                replay = service._replay(
                    journal, final_actor, "consume_provider_receipt", value
                )
                if replay is not None:
                    return replay
                item = _head(journal, value, "receipt_pending")
                require(
                    actor_ref == final_actor == item["actor"]
                    and item["receipt"]["digest"] == value["receipt_digest"],
                    "conflict",
                )
                now = service._now(db, journal["control"])
                control = service._floor(db, journal["control"], now)
                expired = _expire(service, db, item, now)
                if not expired:
                    require(
                        _managed(service, db, journal, item) == files
                        and _identity(journal, channels) == identity,
                        "dependency_unavailable",
                    )
                    require(
                        records.expected_stage_identity(
                            service._domain, db, service._profile, item
                        )
                        == expected,
                        "conflict",
                    )
                    parsed = parse_provider_stage_evidence(evidence.content_bytes)
                    now = service._now(db, control)
                    service._floor(db, control, now)
                    expired = _expire(service, db, item, now)
                    if not expired:
                        require(
                            records.evidence_agrees(parsed, item, expected, now),
                            "conflict",
                        )
                        result = records.accept_stage(
                            service._domain,
                            db,
                            service._domain._read_roots(db),
                            service._profile,
                            item,
                            now=now,
                            actor_ref=actor_ref,
                            value=value,
                            evidence=blob,
                            evidence_bytes=evidence.content_bytes,
                        )
                        service._journal(db)
    except StagePostconditionError as error:
        raise DeploymentPrepareError(
            "conflict" if error.code == "probe_mismatch" else "dependency_unavailable"
        ) from None
    except DeploymentSourceError:
        raise DeploymentPrepareError("dependency_unavailable") from None
    if expired:
        raise DeploymentPrepareError("conflict")
    service._reconcile()
    return result
