"""Encrypted initial custody. Custody receipts never supply provider binding authority."""
from contextlib import contextmanager
from hashlib import sha256
import os
import sqlite3
import threading

from . import credential_envelope as envelope
from .credential_contracts import (MAX_SECRET_BYTES, MAX_ENVELOPE_BYTES, CredentialVaultError,
    canonical, fingerprint, metadata_value, reference, secret_value, strict_json, unb64u, uuid_value)
from .credential_files import CustodyBudget, exclusion
from .credential_journal import Journal
from .credential_root import CredentialRoot


class CredentialVault:
    def __init__(self, *legacy, root_directory=None, records_directory=None,
                 vault_id=None, expected_uid=None, expected_gid=None):
        if legacy or None in (root_directory, records_directory, vault_id, expected_uid, expected_gid):
            raise CredentialVaultError("maintenance_required")
        self._lifetime = threading.RLock()
        self._root = CredentialRoot(root_directory=root_directory, records_directory=records_directory,
            vault_id=vault_id, expected_uid=expected_uid, expected_gid=expected_gid)
        self._closed = False
        try:
            with self._operation(recover=True):
                pass
        except BaseException:
            self.close()
            raise

    def close(self):
        with self._lifetime:
            self._closed = True
            self._root.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def _operation(self, *, recover=False, custody_budget=None):
        # Lifetime gate prevents close racing an operation. Every operation opens its own flock FD.
        if custody_budget is not None and recover:
            raise CredentialVaultError("maintenance_required")
        if custody_budget is None:
            acquired = self._lifetime.acquire(timeout=5)
        else:
            acquired = False
            while not acquired:
                acquired = self._lifetime.acquire(timeout=custody_budget.wait_slice())
        if not acquired:
            raise CredentialVaultError("busy")
        try:
            if custody_budget is not None:
                custody_budget.checkpoint()
            if self._closed:
                raise CredentialVaultError("closed")
            with exclusion(self._root._records, "mutation.lock", custody_budget=custody_budget):
                if custody_budget is not None:
                    custody_budget.checkpoint()
                self._root._verify()
                if custody_budget is not None:
                    custody_budget.checkpoint()
                with Journal(self._root._records, self._root._layout,
                             custody_budget=custody_budget) as journal:
                    if recover:
                        self._recover(journal)
                    yield journal
        except (sqlite3.Error, OSError):
            raise CredentialVaultError("storage_failure") from None
        finally:
            self._lifetime.release()

    @contextmanager
    def _record_directory(self, metadata, *, create=False):
        with self._root._records.child("generations") as generations:
            with generations.child(self._root._manifest["generation_id"]) as generation:
                with generation.child("records") as records:
                    if not create and metadata["record_id"] not in records.names():
                        yield None
                    else:
                        with records.child(metadata["record_id"], create=create) as directory:
                            yield directory

    def _published(self, metadata):
        with self._record_directory(metadata) as directory:
            name = str(metadata["record_version"]) + ".json"
            if directory is None or name not in directory.names():
                return None
            return directory.read(name, MAX_ENVELOPE_BYTES)

    def _publish(self, metadata, payload):
        # Exclusive complete write, not atomic publication. Partial destination is retained.
        with self._record_directory(metadata, create=True) as directory:
            directory.write(str(metadata["record_version"]) + ".json", payload)

    def _authenticate(self, payload, metadata, nonce):
        _, actual_nonce, ciphertext = envelope.decode(payload)
        if actual_nonce != nonce:
            raise CredentialVaultError("maintenance_required")
        self._root.open(payload, metadata)
        return sha256(ciphertext).hexdigest()

    @staticmethod
    def _receipt(metadata, digest):
        return {k: metadata[k] for k in ("command_id", "record_id", "record_version", "provider", "auth_mode", "created_at")} | {
            "ciphertext_sha256": digest, "state": "stored_unbound"}

    def _commit_receipt(self, journal, metadata, digest):
        receipt = self._receipt(metadata, digest)
        with journal.transaction() as db:
            db.execute("INSERT INTO receipts VALUES(?,?)", (metadata["command_id"], canonical(receipt)))
            db.execute("UPDATE commands SET state='stored_unbound' WHERE command_id=?", (metadata["command_id"],))
        return receipt

    def _recover(self, journal):
        db = journal.connection
        rows = db.execute("SELECT * FROM commands").fetchall()
        burned = {(row[0], row[1]) for row in db.execute("SELECT key_id,nonce FROM nonces")}
        # Journal has already validated every intent/receipt/retirement. Authenticate
        # the entire bounded tree before planning, and finish every plan check before
        # any publication or journal mutation. A bad sibling cannot cause partial recovery.
        quarantined, stage_copies, published_count = self._inspect_tree(rows, burned)
        actions = []
        for row in rows:
            meta = metadata_value(strict_json(row["metadata"], 4096))
            receipt_row = db.execute("SELECT body FROM receipts WHERE command_id=?", (row["command_id"],)).fetchone()
            receipt = strict_json(receipt_row["body"], 4096) if receipt_row is not None else None
            payload = self._published(meta)
            name = row["command_id"] + ".json"
            copies = stage_copies.get((row["key_id"], row["record_id"], row["version"], row["nonce"]), [])
            with self._root._records.child("staging") as stage:
                staged = stage.read(name, MAX_ENVELOPE_BYTES) if name in copies else None
            # Canonical staging is tied to this command, not merely to a valid root.
            if staged is not None:
                staged_digest = self._authenticate(staged, meta, row["nonce"])
                if payload is not None and payload != staged:
                    raise CredentialVaultError("maintenance_required")
            digest = self._authenticate(payload, meta, row["nonce"]) if payload is not None else None
            if row["state"] == "secret_input_lost":
                if receipt is not None or payload is not None or copies:
                    raise CredentialVaultError("maintenance_required")
                continue
            if row["state"] == "stored_unbound":
                if receipt is None:
                    raise CredentialVaultError("maintenance_required")
                if staged is not None and self._receipt(meta, staged_digest) != receipt:
                    raise CredentialVaultError("maintenance_required")
                if payload is not None:
                    if self._receipt(meta, digest) != receipt:
                        raise CredentialVaultError("maintenance_required")
                else:
                    if copies != [name] or staged is None:
                        raise CredentialVaultError("maintenance_required")
                    # Already receipted bytes can be restored, never relabelled ingress
                    # loss. Original receipt/nonce and effective retirement stay unchanged.
                    actions.append(("restore", meta, staged, staged_digest))
            elif row["state"] == "pending":
                if receipt is not None or (copies and copies != [name]):
                    raise CredentialVaultError("maintenance_required")
                if payload is None and staged is None:
                    actions.append(("lost", meta, None, None))
                else:
                    actions.append(("publish" if payload is None else "receipt", meta,
                                    staged if payload is None else None,
                                    staged_digest if payload is None else digest))
            else:
                raise CredentialVaultError("maintenance_required")
        if published_count + sum(action in ("restore", "publish") for action, *_ in actions) > 2048:
            raise CredentialVaultError("capacity_exhausted")

        # All existing journal/tree identities, authentication and ambiguity checks have
        # succeeded. I/O interruption here remains recoverable on the next open; this is
        # not a claim that multiple file publications form one atomic transaction.
        for action, meta, payload, digest in actions:
            if action in ("restore", "publish"):
                self._publish(meta, payload)
            if action in ("publish", "receipt"):
                self._commit_receipt(journal, meta, digest)
            elif action == "lost":
                with journal.transaction() as tx:
                    tx.execute("UPDATE commands SET state='secret_input_lost' WHERE command_id=?",
                               (meta["command_id"],))
        self._quarantined = quarantined

    def _inspect_tree(self, rows, burned):
        known = {(r["record_id"], str(r["version"]) + ".json"): r for r in rows}
        staged = {r["command_id"] + ".json": r for r in rows}
        stage_copies = {}
        quarantined = 0
        record_count = 0
        with self._root._records.child("generations") as generations:
            if generations.names() != {self._root._manifest["generation_id"]}:
                raise CredentialVaultError("maintenance_required")
            with generations.child(self._root._manifest["generation_id"]) as generation:
                if generation.names() != {"records"}:
                    raise CredentialVaultError("maintenance_required")
                with generation.child("records") as records:
                    if len(records.names()) > 2048:
                        raise CredentialVaultError("capacity_exhausted")
                    for record_id in records.names():
                        uuid_value(record_id)
                        with records.child(record_id) as versions:
                            record_count += len(versions.names())
                            if record_count > 2048:
                                raise CredentialVaultError("capacity_exhausted")
                            for name in versions.names():
                                payload = versions.read(name, MAX_ENVELOPE_BYTES)
                                header, nonce, _ = envelope.decode(payload)
                                if (header["key_id"], nonce) not in burned:
                                    raise CredentialVaultError("maintenance_required")
                                if name != str(header["record_version"]) + ".json" or record_id != header["record_id"]:
                                    raise CredentialVaultError("maintenance_required")
                                if (record_id, name) in known:
                                    row = known[(record_id, name)]
                                    self._authenticate(payload, strict_json(row["metadata"], 4096), row["nonce"])
                                else:
                                    self._check_orphan(payload, header)
                                    quarantined += 1
        with self._root._records.child("staging") as stage:
            if len(stage.names()) > 4096:
                raise CredentialVaultError("capacity_exhausted")
            for name in stage.names():
                payload = stage.read(name, MAX_ENVELOPE_BYTES)
                header, nonce, _ = envelope.decode(payload)
                if (header["key_id"], nonce) not in burned:
                    raise CredentialVaultError("maintenance_required")
                identity = (header["key_id"], header["record_id"], header["record_version"], nonce)
                stage_copies.setdefault(identity, []).append(name)
                if name in staged:
                    row = staged[name]
                    self._authenticate(payload, strict_json(row["metadata"], 4096), row["nonce"])
                else:
                    self._check_orphan(payload, header)
                    quarantined += 1
        return quarantined, stage_copies, record_count

    def _check_orphan(self, payload, header):
        meta = {k: header[k] for k in ("record_id", "record_version", "provider", "auth_mode", "created_at")}
        meta.update(command_id=header["record_id"], predecessor=None)
        self._root.open(payload, meta)

    def _query(self, journal, metadata):
        db = journal.connection
        rows = journal.checked_read("SELECT * FROM commands WHERE command_id=?",
                                    (metadata["command_id"],))
        row = None if not rows else rows[0]
        if row is None:
            if (journal.checked_read("SELECT 1 FROM commands WHERE record_id=? AND version=?",
                                     (metadata["record_id"], metadata["record_version"]))
                    or journal.checked_read("SELECT 1 FROM retirements WHERE command_id=?",
                                            (metadata["command_id"],))):
                raise CredentialVaultError("conflict")
            return {"command_id": metadata["command_id"], "state": "unknown", "terminal": False}
        if row["fingerprint"] != fingerprint(metadata):
            raise CredentialVaultError("conflict")
        receipts = journal.checked_read("SELECT body FROM receipts WHERE command_id=?",
                                        (metadata["command_id"],))
        if not receipts:
            return {"command_id": metadata["command_id"], "state": row["state"]}
        result = strict_json(receipts[0]["body"], 4096)
        if journal.checked_read("SELECT 1 FROM retirements WHERE target_command=?",
                                (metadata["command_id"],)):
            result["state"] = "cleanup_pending"
        elif row["state"] == "secret_input_lost":
            result["state"] = "secret_input_lost"
        return result

    def query_record(self, *, metadata):
        metadata = metadata_value(metadata)
        with self._operation() as journal:
            return self._query(journal, metadata)

    def store_at(self, *, metadata, secret=None, secret_b64u=None):
        metadata = metadata_value(metadata)
        with self._operation() as journal:
            existing = self._query(journal, metadata)
            if existing["state"] != "unknown":
                return existing
            journal.capacity()
            # Replay/capacity decisions precede ingress decoding or validation.
            if secret_b64u is not None:
                secret = unb64u(secret_b64u, 1, MAX_SECRET_BYTES)
            secret = secret_value(secret)
            nonce = None
            for _ in range(8):
                candidate = os.urandom(24)
                if journal.connection.execute("SELECT 1 FROM nonces WHERE key_id=? AND nonce=?", (self._root._manifest["key_id"], candidate)).fetchone() is None:
                    nonce = candidate
                    break
            if nonce is None:
                raise CredentialVaultError("nonce_exhausted")
            key_id = self._root._manifest["key_id"]
            with journal.transaction() as db:
                db.execute("INSERT INTO nonces VALUES(?,?)", (key_id, nonce))
                db.execute("INSERT INTO commands VALUES(?,?,?,'pending',?,?,?,?)", (
                    metadata["command_id"], fingerprint(metadata), canonical(metadata), key_id, nonce,
                    metadata["record_id"], metadata["record_version"]))
            payload = self._root.seal(metadata, secret, nonce)
            with self._root._records.child("staging") as stage:
                stage.write(metadata["command_id"] + ".json", payload)
            self._publish(metadata, payload)
            digest = self._authenticate(self._published(metadata), metadata, nonce)
            return self._commit_receipt(journal, metadata, digest)

    def retire(self, *, command_id, record, reason):
        uuid_value(command_id)
        record = reference(record)
        if reason not in ("owner_delete", "superseded", "unbound_orphan"):
            raise CredentialVaultError("invalid_metadata")
        body = dict(command_id=command_id, record=record, reason=reason)
        digest = sha256(canonical(body)).hexdigest()
        with self._operation() as journal:
            db = journal.connection
            prior = db.execute("SELECT * FROM retirements WHERE command_id=?", (command_id,)).fetchone()
            if prior:
                if prior["fingerprint"] != digest:
                    raise CredentialVaultError("conflict")
                return strict_json(prior["body"], 4096)
            if db.execute("SELECT 1 FROM commands WHERE command_id=?", (command_id,)).fetchone():
                raise CredentialVaultError("conflict")
            target = db.execute("SELECT r.body, r.command_id FROM receipts r JOIN commands c USING(command_id) WHERE c.record_id=? AND c.version=?", (record["record_id"], record["record_version"])).fetchone()
            if target is None or strict_json(target["body"], 4096)["ciphertext_sha256"] != record["ciphertext_sha256"]:
                raise CredentialVaultError("conflict")
            journal.capacity(retirement=True)
            body["state"] = "cleanup_pending"
            with journal.transaction() as tx:
                tx.execute("INSERT INTO retirements VALUES(?,?,?,?)", (command_id, digest, canonical(body), target["command_id"]))
            return body

    def bind_head(self, *, provider, revision, state, record):
        """Adopt the control plane's provider connection binding head (T090).

        The ledger decides the binding by compare-and-swap; this is the gateway's copy
        the send path checks at claim time. Revisions only move forward: a lower
        revision, or the same revision with a different body, is refused ``conflict``
        (a stale publisher never rolls the head back); the identical head is an
        idempotent replay. A ``bound`` head must name a receipted, unretired record of
        that provider; a ``revoked_pending_erasure`` head names the record it revoked."""
        if (type(provider) is not str or provider not in ("claude", "codex")
                or type(revision) is not int or not 1 <= revision <= 2**31
                or state not in ("bound", "revoked_pending_erasure")):
            raise CredentialVaultError("invalid_metadata")
        record = reference(record)
        head = {"provider": provider, "revision": revision, "state": state, "record": record}
        digest = sha256(canonical(head)).hexdigest()
        with self._operation() as journal:
            prior = journal.checked_read("SELECT revision, fingerprint FROM heads WHERE provider=?",
                                         (provider,))
            if prior:
                if prior[0]["revision"] > revision or (
                        prior[0]["revision"] == revision and prior[0]["fingerprint"] != digest):
                    raise CredentialVaultError("conflict")
                if prior[0]["revision"] == revision:
                    return head
            rows = journal.checked_read(
                "SELECT metadata FROM commands WHERE record_id=? AND version=?",
                (record["record_id"], record["record_version"]))
            if len(rows) != 1:
                raise CredentialVaultError("conflict")
            receipt = self._query(journal, strict_json(rows[0][0], 4096))
            if (receipt.get("ciphertext_sha256") != record["ciphertext_sha256"]
                    or receipt.get("provider") != provider
                    or receipt.get("state") not in ("stored_unbound", "cleanup_pending")
                    or (state == "bound" and receipt["state"] != "stored_unbound")):
                raise CredentialVaultError("conflict")
            with journal.transaction() as db:
                db.execute("INSERT OR REPLACE INTO heads VALUES(?,?,?,?)",
                           (provider, revision, digest, canonical(head)))
            return head

    def heads(self):
        """The adopted binding heads (nonsecret)."""
        with self._operation() as journal:
            return [strict_json(row[0], 4096) for row in
                    journal.checked_read("SELECT body FROM heads ORDER BY provider")]

    def snapshot(self):
        with self._operation() as journal:
            return [self._query(journal, strict_json(row[0], 4096)) for row in journal.connection.execute("SELECT metadata FROM commands ORDER BY command_id")]

    def metadata(self, handle):
        uuid_value(handle)
        with self._operation() as journal:
            rows = journal.connection.execute("SELECT metadata FROM commands WHERE record_id=? ORDER BY version DESC", (handle,)).fetchall()
            if not rows:
                raise CredentialVaultError("unknown_record")
            return self._query(journal, strict_json(rows[0][0], 4096))

    def health(self):
        entries = self.snapshot()
        return {state: sum(entry["state"] == state for entry in entries) for state in
                ("stored_unbound", "cleanup_pending", "secret_input_lost", "pending")} | {"quarantined": self._quarantined}

    def capabilities(self):
        return {"port": "credential-op-v2", "operations": ["store_at", "query_record", "retire", "bind_head", "snapshot", "health", "capabilities"],
                "root_rotation": False, "erasure": False, "provider_resolution": False}

    def resolve_for_gateway(self, handle):
        raise CredentialVaultError("provider_binding_unavailable")

    @contextmanager
    def delivery_for_exchange(self, lease):
        """Decrypt one exact stored record only for a claimed one-shot exchange lease."""
        from .provider_send_messages import GatewayExchangeLease, ProviderSendError

        if type(lease) is not GatewayExchangeLease:
            raise CredentialVaultError("invalid_metadata")
        try:
            lease._issuer.claim(lease)
        except ProviderSendError:
            raise CredentialVaultError("provider_binding_unavailable") from None
        budget = CustodyBudget(lease.deadline_monotonic, lease.cancel_event)
        try:
            metadata = metadata_value(lease.credential_metadata)
            record = reference(lease.credential_record)
            if (metadata["record_id"] != record["record_id"]
                    or metadata["record_version"] != record["record_version"]
                    or lease.selected_handle_ref["sha256"] != lease.connection_sha256
                    or lease.connection_pin["credential_metadata_sha256"] != fingerprint(metadata)
                    or metadata["provider"] != "claude" or metadata["auth_mode"] != "api"):
                raise CredentialVaultError("provider_binding_unavailable")
            with self._operation(custody_budget=budget) as journal:
                budget.checkpoint()
                receipt = self._query(journal, metadata)
                if (receipt.get("state") != "stored_unbound"
                        or any(receipt.get(name) != record[name] for name in record)):
                    raise CredentialVaultError("provider_binding_unavailable")
                # Claim-time binding check (T090): only the record the provider connection's
                # current binding head binds may be delivered. A rotated predecessor, a
                # revoked or orphaned record, a fenced command's late commit or a record
                # never bound is refused here, before any provider byte. `bind_head` takes
                # the same vault exclusion, so a rotation either lands before this read
                # (the send is refused) or after the request is written (the send was
                # already claimed under the previous head).
                heads = journal.checked_read("SELECT body FROM heads WHERE provider=?",
                                             (metadata["provider"],))
                head = strict_json(heads[0][0], 4096) if len(heads) == 1 else None
                if head is None or head["state"] != "bound" or head["record"] != record:
                    raise CredentialVaultError("provider_binding_unavailable")
                payload = self._published(metadata)
                if payload is None:
                    raise CredentialVaultError("provider_binding_unavailable")
                nonce_rows = journal.checked_read("SELECT nonce FROM commands WHERE command_id=?",
                                                  (metadata["command_id"],))
                if len(nonce_rows) != 1:
                    raise CredentialVaultError("provider_binding_unavailable")
                digest = self._authenticate(payload, metadata, nonce_rows[0][0])
                if digest != record["ciphertext_sha256"]:
                    raise CredentialVaultError("provider_binding_unavailable")
                budget.checkpoint()
                secret = self._root.open(payload, metadata)
                budget.checkpoint()
                yield secret
        finally:
            # Service completion owns the state transition after HTTP observation.
            pass

    def store(self, *args, **kwargs):
        raise CredentialVaultError("unsupported_operation")

    def erase(self, *args, **kwargs):
        raise CredentialVaultError("maintenance_required")
