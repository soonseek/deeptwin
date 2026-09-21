"""Deployment-only fresh pair initializer. Never called by serving or HTTP routes."""
from datetime import datetime, timezone
from hashlib import sha256
import os
from uuid import uuid4

from app.workers.credential_contracts import CredentialVaultError, canonical, uuid_value
from app.workers.credential_files import Directory, approved_directory, exclusion, separate
from app.workers.credential_journal import Journal
from app.workers.credential_root import manifest_tag, verify_pair


def initialize_credential_root(root_directory, records_directory, *, vault_id, expected_uid, expected_gid):
    uuid_value(vault_id)
    separate(root_directory, records_directory)
    root_empty = not os.path.lexists(root_directory)
    if not root_empty:
        with Directory(root_directory, expected_uid, expected_gid) as existing_root:
            root_empty = not existing_root.names()
    # Unknown/partial records cannot cause a fresh root directory or lock write.
    if root_empty and os.path.lexists(records_directory):
        with Directory(records_directory, expected_uid, expected_gid) as existing_records:
            if existing_records.names() not in (set(), {"lifecycle.lock"}):
                raise CredentialVaultError("maintenance_required")
    root = approved_directory(root_directory, expected_uid, expected_gid)
    records = None
    try:
        # Reject a partial/unknown root before even creating initializer lock.
        names = root.names()
        complete_root = {"root.key", "manifest.json", "init.lock"}
        if names not in (set(), {"init.lock"}, complete_root):
            raise CredentialVaultError("maintenance_required")
        with exclusion(root, "init.lock", create=True):
            names = root.names()
            if names == complete_root:
                # A complete root must verify its bound EXISTING records; never initialize another.
                records = Directory(records_directory, expected_uid, expected_gid)
                with exclusion(records, "lifecycle.lock"):
                    manifest, layout, _ = verify_pair(root, records, vault_id)
                    with exclusion(records, "mutation.lock"), Journal(records, layout):
                        pass
                    return manifest
            if names != {"init.lock"}:
                raise CredentialVaultError("maintenance_required")
            records = approved_directory(records_directory, expected_uid, expected_gid)
            if records.names() not in (set(), {"lifecycle.lock"}):
                raise CredentialVaultError("maintenance_required")
            with exclusion(records, "lifecycle.lock", create=True):
                root.verify()
                records.verify()
                separate(root.path, records.path)
                if root.names() != {"init.lock"} or records.names() != {"lifecycle.lock"}:
                    raise CredentialVaultError("maintenance_required")
                ids = {vault_id}
                def fresh_id():
                    while True:
                        value = str(uuid4())
                        if value not in ids:
                            ids.add(value)
                            return value
                key = os.urandom(32)
                manifest = dict(schema_version="credential-root-v1", key_id=fresh_id(), vault_id=vault_id,
                                storage_id=fresh_id(), generation_id=fresh_id(),
                                created_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"))
                manifest["integrity_tag"] = manifest_tag(key, manifest)
                raw = canonical(manifest)
                layout = {k: manifest[k] for k in ("key_id", "vault_id", "storage_id", "generation_id")}
                layout.update(schema_version="credential-layout-v1", root_manifest_sha256=sha256(raw).hexdigest())
                root.write("root.key", key, 0o400)
                root.write("manifest.json", raw, 0o400)
                records.write("layout.json", canonical(layout))
                records.write("mutation.lock", b"")
                with records.child("staging", create=True):
                    pass
                with records.child("generations", create=True) as generations:
                    with generations.child(manifest["generation_id"], create=True) as generation:
                        with generation.child("records", create=True):
                            pass
                with Journal(records, layout, initialize=True):
                    pass
                os.fsync(root.fd)
                os.fsync(records.fd)
                return manifest
    except OSError:
        raise CredentialVaultError("storage_failure") from None
    finally:
        if records is not None:
            records.close()
        root.close()
