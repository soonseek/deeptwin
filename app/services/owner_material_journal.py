"""Bounded durable receipts, indexed across text and upload command identities."""
from hashlib import sha256

from ..domain.refs import canonical_json, parse_canonical

MAX_COMMANDS = 100_000
DDL = """CREATE TABLE IF NOT EXISTS owner_material_commands(
    vault_id TEXT NOT NULL, command_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
    receipt BLOB NOT NULL CHECK(length(receipt)<=131072),
    PRIMARY KEY(vault_id,command_id),
    FOREIGN KEY(vault_id) REFERENCES domain_vault(vault_id))"""


def fingerprint(operation, work_id, payload):
    return sha256(canonical_json({"operation": operation, "work_id": work_id, "payload": payload})).hexdigest()


def lookup(db, vault_id, command_id):
    return db.execute("SELECT fingerprint,receipt FROM owner_material_commands WHERE vault_id=? AND command_id=?",
                      (vault_id, command_id)).fetchone()


def receipt(row):
    return parse_canonical(bytes(row["receipt"]))


def save(db, vault_id, command_id, digest, value):
    from .works import WorkServiceError

    if db.execute("SELECT count(*) FROM owner_material_commands WHERE vault_id=?", (vault_id,)).fetchone()[0] >= MAX_COMMANDS:
        raise WorkServiceError("capacity")
    db.execute("INSERT INTO owner_material_commands VALUES (?,?,?,?)", (vault_id, command_id, digest, canonical_json(value)))
