"""Gateway-private initial root verification and authenticated record cryptography."""
from hashlib import sha256
import hmac
import os

from nacl.exceptions import CryptoError
from nacl.secret import Aead

from . import credential_envelope as envelope
from .credential_contracts import (CredentialVaultError, b64u, canonical, secret_value,
    strict_json, timestamp, unb64u, uuid_value)
from .credential_files import Directory, acquire, lock_fd, separate

MANIFEST_KEYS = {"schema_version", "key_id", "vault_id", "storage_id", "generation_id", "created_at", "integrity_tag"}


def manifest_tag(key, body):
    return b64u(hmac.digest(key, canonical({"domain": "deeptwin-credential-root-v1", "manifest": body}), "sha256"))


def verify_pair(root, records, vault_id):
    uuid_value(vault_id)
    if root.names() != {"manifest.json", "root.key", "init.lock"}:
        raise CredentialVaultError("maintenance_required")
    if not {"layout.json", "lifecycle.lock", "mutation.lock", "journal.sqlite", "generations", "staging"} <= records.names():
        raise CredentialVaultError("maintenance_required")
    if records.names() - {"layout.json", "lifecycle.lock", "mutation.lock", "journal.sqlite", "journal.sqlite-journal", "journal.sqlite-wal", "journal.sqlite-shm", "generations", "staging"}:
        raise CredentialVaultError("maintenance_required")
    # Verification does not acquire, create, repair or mutate the root lock.
    if root.read("init.lock", 0) != b"":
        raise CredentialVaultError("maintenance_required")
    raw = root.read("manifest.json", 4096, 0o400)
    key = root.read("root.key", 32, 0o400)
    if len(key) != 32:
        raise CredentialVaultError("maintenance_required")
    manifest = strict_json(raw, 4096)
    if type(manifest) is not dict or set(manifest) != MANIFEST_KEYS or manifest["schema_version"] != "credential-root-v1":
        raise CredentialVaultError("maintenance_required")
    ids = [uuid_value(manifest[n]) for n in ("key_id", "vault_id", "storage_id", "generation_id")]
    if len(set(ids)) != 4 or manifest["vault_id"] != vault_id:
        raise CredentialVaultError("maintenance_required")
    timestamp(manifest["created_at"])
    unb64u(manifest["integrity_tag"], 32, 32)
    body = {k: v for k, v in manifest.items() if k != "integrity_tag"}
    if not hmac.compare_digest(manifest["integrity_tag"], manifest_tag(key, body)):
        raise CredentialVaultError("maintenance_required")
    layout = strict_json(records.read("layout.json", 4096), 4096)
    expected = {k: manifest[k] for k in ("key_id", "vault_id", "storage_id", "generation_id")}
    expected.update(schema_version="credential-layout-v1", root_manifest_sha256=sha256(raw).hexdigest())
    if layout != expected:
        raise CredentialVaultError("maintenance_required")
    return manifest, layout, key


class CredentialRoot:
    """No key accessor or public general-purpose MAC; lifetime owns shared exclusion."""
    __slots__ = ("_root", "_records", "_lifecycle", "_aead", "_manifest", "_layout", "_fixed")

    def __init__(self, *, root_directory, records_directory, vault_id, expected_uid, expected_gid):
        self._root = self._records = self._lifecycle = self._aead = None
        separate(root_directory, records_directory)
        try:
            self._root = Directory(root_directory, expected_uid, expected_gid)
            self._records = Directory(records_directory, expected_uid, expected_gid)
            # Verify before locking so a legacy/unknown directory is never modified.
            self._manifest, self._layout, key = verify_pair(self._root, self._records, vault_id)
            self._lifecycle = lock_fd(self._records, "lifecycle.lock")
            acquire(self._lifecycle, False)
            self._root.verify()
            self._records.verify()
            manifest, layout, key = verify_pair(self._root, self._records, vault_id)
            self._manifest, self._layout = manifest, layout
            self._aead = Aead(key)
            self._fixed = {}
            for name in ("lifecycle.lock", "mutation.lock", "journal.sqlite"):
                fd = self._records.file(name, writable=True)
                try:
                    info = os.fstat(fd)
                    self._fixed[name] = (info.st_dev, info.st_ino)
                    if name == "lifecycle.lock" and (os.fstat(self._lifecycle).st_dev, os.fstat(self._lifecycle).st_ino) != self._fixed[name]:
                        raise CredentialVaultError("maintenance_required")
                finally:
                    os.close(fd)
        except BaseException:
            self.close()
            raise

    def _verify(self):
        self._root.verify()
        self._records.verify()
        manifest, layout, _ = verify_pair(self._root, self._records, self._manifest["vault_id"])
        if manifest != self._manifest or layout != self._layout:
            raise CredentialVaultError("maintenance_required")
        for name, identity in self._fixed.items():
            fd = self._records.file(name, writable=True)
            try:
                info = os.fstat(fd)
                if (info.st_dev, info.st_ino) != identity or (name.endswith(".lock") and info.st_size):
                    raise CredentialVaultError("maintenance_required")
            finally:
                os.close(fd)

    def seal(self, metadata, secret, nonce):
        if self._aead is None:
            raise CredentialVaultError("closed")
        secret_value(secret)
        if type(nonce) is not bytes or len(nonce) != 24:
            raise CredentialVaultError("invalid_nonce")
        header = envelope.header_for(metadata, self._manifest)
        ciphertext = self._aead.encrypt(secret, canonical(header), nonce).ciphertext
        return envelope.encode(header, nonce, ciphertext)

    def open(self, payload, metadata):
        if self._aead is None:
            raise CredentialVaultError("closed")
        header, nonce, ciphertext = envelope.decode(payload)
        if header != envelope.header_for(metadata, self._manifest):
            raise CredentialVaultError("record_identity_mismatch")
        try:
            return secret_value(self._aead.decrypt(ciphertext, canonical(header), nonce))
        except CryptoError:
            raise CredentialVaultError("authentication_failed") from None

    def close(self):
        self._aead = None  # Python memory disposal is best effort, not secure erasure.
        if self._lifecycle is not None:
            os.close(self._lifecycle)
            self._lifecycle = None
        for directory in (self._records, self._root):
            if directory is not None:
                directory.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
