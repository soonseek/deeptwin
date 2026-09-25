"""The restricted reconciliation start of an owner recovery (recovery port §5).

The stopped-control-plane maintenance has already advanced the session root to epoch N+1
from a verified `deployment-recovery-receipt-v1`, and the deployment configuration names
N+1 with the new verifier. The database still says N. `verify_recovery_start` binds the
receipt to exactly these three facts before anything is served; then
`reconcile_recovery_in_transaction` runs the one DB transaction that installs epoch N+1
and ends every earlier authority:

- inserts `owner_auth_control(epoch=N+1)` bound to the request/nonce/receipt that opened it
- revokes every authenticator and every session
- revokes every service client (advancing its recovery epoch to N+1)
- expires every unconsumed bootstrap capability/verifier and pending conversation challenge
- expires every pending gate approval (`approval.decided(expired)`)
- revokes every open run consent (`approval.decided(revoked)`)
- appends `auth.recovery_completed`

Historical records stay as evidence and authorize nothing. A crash before the commit leaves
epoch N, so the next start verifies and reconciles again; after the commit the next start
is an ordinary equal-epoch start. Any other combination fails closed.
"""

import time
from datetime import UTC, datetime
from hashlib import sha256

from ..deployment.receipt_contracts import ReceiptWireError
from ..deployment.recovery_contracts import verifier_sha256, verify_recovery_receipt
from ..domain.public_events import _append_event_in_transaction
from . import owner_auth_storage as storage
from .owner_auth import OwnerAuthError


def _stamp(milliseconds):
    return datetime.fromtimestamp(milliseconds / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def verify_recovery_start(control, *, root, profile, binding, verifier, trust_bytes):
    """Bind a recovered root generation, its receipt and the configured verifier to the
    database's current epoch N. Returns the inert recovery evidence; never writes."""

    try:
        recovery = root.recovery
        if type(trust_bytes) is not bytes or recovery is None:
            raise OwnerAuthError("unavailable")
        receipt_bytes = recovery["receipt"]
        receipt = verify_recovery_receipt(receipt_bytes, request_bytes=recovery["request"],
                                          trust_bytes=trust_bytes, profile=profile)
        receipt_sha256 = sha256(receipt_bytes).hexdigest()
        manifest = root.receipt
        control = dict(control)
        if (manifest["generation_id"] != receipt["new_generation_id"]
                or manifest["recovery_epoch"] != receipt["new_epoch"]
                or manifest["recovery_receipt_sha256"] != receipt_sha256
                or binding["epoch"] != receipt["new_epoch"]
                or receipt["new_verifier_sha256"] != verifier_sha256(verifier.verifier_b64u)
                # the database is at exactly the generation the receipt advanced from
                or control["epoch"] != receipt["previous_epoch"]
                or control["generation_id"] != receipt["previous_generation_id"]
                or control["manifest_digest"] != receipt["previous_manifest_sha256"]
                or any(control[name] != binding[name] for name in ("vault_id", "instance_id", "origin_digest"))):
            raise OwnerAuthError("unavailable")
        return {"receipt": receipt, "receipt_sha256": receipt_sha256, "control": control}
    except OwnerAuthError:
        raise
    except (ReceiptWireError, KeyError, TypeError, ValueError):
        raise OwnerAuthError("unavailable") from None


def _table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def reconcile_recovery_in_transaction(domain, db, *, recovery, binding, verifier):
    """The one reconciliation transaction; the caller owns the writer and commits it."""

    from .run_approvals import expire_pending_in_transaction
    from .run_consents import revoke_open_in_transaction
    from .service_clients import PersistentServiceClientRegistry

    domain._assert_write_transaction(db)
    storage.verify(db)
    receipt, previous = recovery["receipt"], recovery["control"]
    control = storage.current_control(db)
    # nothing moved since the start was verified, and this request/nonce/receipt never
    # opened an epoch before (a replayed receipt cannot reopen a later epoch)
    if control is None or dict(control) != previous:
        raise OwnerAuthError("unavailable")
    if db.execute("SELECT 1 FROM owner_auth_control WHERE recovery_request_id=? OR recovery_request_nonce=? "
                  "OR recovery_receipt_digest=?", (receipt["request_id"], receipt["request_nonce"],
                                                   recovery["receipt_sha256"])).fetchone() is not None:
        raise OwnerAuthError("unavailable")
    new_epoch = receipt["new_epoch"]
    now = max(time.time_ns() // 1_000_000, control["clock_floor"])
    storage.insert(db, "control", {
        "epoch": new_epoch, "vault_id": binding["vault_id"], "instance_id": binding["instance_id"],
        "origin_digest": binding["origin_digest"], "generation_id": binding["generation_id"],
        "key_id": binding["key_id"], "manifest_digest": binding["manifest_digest"],
        "previous_epoch": control["epoch"], "recovery_request_id": receipt["request_id"],
        "recovery_request_nonce": receipt["request_nonce"],
        "recovery_receipt_digest": recovery["receipt_sha256"],
        "opened_at": now, "deadline": now + 600000, "clock_floor": now, "revision": 1})
    # every unconsumed human/bootstrap capability and verifier of an earlier epoch ends
    for claim in [dict(row) for row in db.execute(
            "SELECT * FROM owner_auth_bootstrap_claims WHERE state='available' ORDER BY epoch")]:
        storage.update(db, "bootstrap_claims", claim, {"state": "expired"}, identity="epoch")
    storage.insert(db, "bootstrap_claims", {"epoch": new_epoch, "verifier": verifier.verifier_b64u,
        "attempts": 0, "state": "available", "claim_id": None, "consumed_at": None,
        "completed_at": None, "revision": 1})
    for row in [dict(item) for item in db.execute(
            "SELECT * FROM owner_auth_authenticators WHERE revoked_at IS NULL ORDER BY owner_id,revision")]:
        storage.revoke_authenticator(db, row, max(now, row["created_at"]))
    for row in [dict(item) for item in db.execute(
            "SELECT * FROM owner_auth_sessions WHERE revoked_at IS NULL ORDER BY session_id")]:
        storage.update(db, "sessions", row, {"revoked_at": now}, identity="session_id")
    if _table(db, "service_client_control"):
        epoch, _sequence, _hash, last_observed_at, _control = \
            PersistentServiceClientRegistry._read_control(db)
        # the service-client clock keeps its own units; its last observation is reused
        PersistentServiceClientRegistry._revoke_all_in_transaction(
            db, expected_epoch=epoch, new_epoch=new_epoch, now=last_observed_at)
    if _table(db, "conversation_challenges"):
        # an open challenge ends at its own creation instant: never current again
        db.execute("UPDATE conversation_challenges SET expires_at_ms=created_at_ms "
                   "WHERE consumed_at_ms IS NULL AND expires_at_ms>created_at_ms")
    roots = domain._read_roots(db)
    stamp = _stamp(now)
    expire_pending_in_transaction(domain, db, roots, recovery_id=receipt["request_id"], stamp=stamp)
    revoke_open_in_transaction(domain, db, roots, recovery_id=receipt["request_id"], stamp=stamp)
    _append_event_in_transaction(
        db, vault_id=roots.genesis.id, recorded_at_utc=stamp, observed_at_utc=stamp,
        actor_kind="system", actor_ref=roots.actor, event_type="auth.recovery_completed",
        object_refs=(), correlation_id=receipt["request_id"], causation_id=None,
        status="succeeded", error_code=None, public_metadata={"revision": new_epoch},
        private_evidence_refs=(), retention_class="core", policy_ref=roots.access_policy)
    storage.audit(db, "recovered", receipt["request_id"], now)
    storage.verify(db)
    return new_epoch


__all__ = ["reconcile_recovery_in_transaction", "verify_recovery_start"]
