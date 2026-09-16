"""Exact private deployment journal schema and bounded row primitives."""

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from types import MappingProxyType

from ..domain.refs import EntityRef, canonical_json, parse_canonical, uuid_string
from ..operations.setup import parse_base64url_32
from .prepare_contracts import DeploymentPrepareError, require

DDL = (
    """CREATE TABLE deployment_prepare_migrations (
 version INTEGER PRIMARY KEY CHECK(version=1),
 checksum TEXT NOT NULL CHECK(length(checksum)=64)
);""",
    """CREATE TABLE deployment_prepare_control (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1),
 vault_id TEXT NOT NULL UNIQUE REFERENCES domain_vault(vault_id),
 instance_id TEXT NOT NULL CHECK(length(instance_id)=32),
 origin_digest TEXT NOT NULL CHECK(length(origin_digest)=64),
 topology_id TEXT NOT NULL UNIQUE CHECK(length(topology_id)=36),
 topology_revision INTEGER NOT NULL CHECK(topology_revision=1),
 topology_purpose TEXT NOT NULL CHECK(topology_purpose='operational'),
 topology_sha256 TEXT NOT NULL CHECK(length(topology_sha256)=64),
 topology_size INTEGER NOT NULL CHECK(topology_size BETWEEN 1 AND 65536),
 exchange_id TEXT NOT NULL UNIQUE CHECK(length(exchange_id)=36),
 exchange_revision INTEGER NOT NULL CHECK(exchange_revision=1),
 exchange_purpose TEXT NOT NULL CHECK(exchange_purpose='operational'),
 exchange_sha256 TEXT NOT NULL CHECK(length(exchange_sha256)=64),
 exchange_size INTEGER NOT NULL CHECK(exchange_size BETWEEN 1 AND 8192),
 exchange_identity_json TEXT NOT NULL CHECK(length(exchange_identity_json) BETWEEN 2 AND 4096),
 slot_capacity INTEGER NOT NULL CHECK(slot_capacity BETWEEN 1 AND 16),
 clock_floor_ms INTEGER NOT NULL CHECK(clock_floor_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision>=1),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(vault_id,topology_id),
 FOREIGN KEY(vault_id,topology_purpose,topology_sha256)
  REFERENCES domain_blobs(vault_id,purpose,sha256),
 FOREIGN KEY(vault_id,exchange_purpose,exchange_sha256)
  REFERENCES domain_blobs(vault_id,purpose,sha256)
);""",
    """CREATE TABLE deployment_prepare_requests (
 request_id TEXT PRIMARY KEY CHECK(length(request_id)=36),
 vault_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='deployment_request'),
 version INTEGER NOT NULL CHECK(version=1),
 anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 request_digest TEXT NOT NULL UNIQUE CHECK(length(request_digest)=43),
 nonce_hex TEXT NOT NULL UNIQUE CHECK(length(nonce_hex)=64),
 topology_id TEXT NOT NULL,
 slot_id INTEGER NOT NULL CHECK(slot_id BETWEEN 1 AND 16),
 reservation_revision INTEGER NOT NULL CHECK(reservation_revision=1),
 extension_id TEXT NOT NULL CHECK(length(extension_id) BETWEEN 1 AND 128),
 created_ms INTEGER NOT NULL CHECK(created_ms BETWEEN 0 AND 253402300799999),
 expires_ms INTEGER NOT NULL CHECK(expires_ms<=253402300799999),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 CHECK(expires_ms-created_ms BETWEEN 60000 AND 86400000),
 UNIQUE(vault_id,topology_id,slot_id),
 UNIQUE(vault_id,extension_id),
 FOREIGN KEY(vault_id,topology_id)
  REFERENCES deployment_prepare_control(vault_id,topology_id),
 FOREIGN KEY(vault_id,kind,request_id,version,anchor_digest)
  REFERENCES domain_records(vault_id,kind,id,version,sha256)
);""",
    """CREATE TABLE deployment_prepare_lifecycle (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2),
 previous_revision INTEGER,
 previous_hash TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','cancelled','expired')),
 transitioned_ms INTEGER NOT NULL CHECK(transitioned_ms BETWEEN 0 AND 253402300799999),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024),
 command_id TEXT,
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,revision),
 UNIQUE(request_id,revision,hash),
 UNIQUE(command_id),
 FOREIGN KEY(request_id,previous_revision,previous_hash)
  REFERENCES deployment_prepare_lifecycle(request_id,revision,hash),
 FOREIGN KEY(command_id) REFERENCES deployment_prepare_commands(command_id)
  DEFERRABLE INITIALLY DEFERRED,
 CHECK((revision=1 AND state='prepared' AND previous_revision IS NULL
        AND previous_hash IS NULL AND command_id IS NOT NULL)
    OR (revision=2 AND state IN ('cancelled','expired') AND previous_revision IS NOT NULL AND previous_revision=1
        AND previous_hash IS NOT NULL)),
 CHECK((state='expired' AND command_id IS NULL)
    OR (state IN ('prepared','cancelled') AND command_id IS NOT NULL))
);""",
    """CREATE TABLE deployment_prepare_heads (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2),
 lifecycle_hash TEXT NOT NULL CHECK(length(lifecycle_hash)=64),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,revision,lifecycle_hash)
  REFERENCES deployment_prepare_lifecycle(request_id,revision,hash)
);""",
    """CREATE TABLE deployment_prepare_commands (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 namespace TEXT NOT NULL CHECK(namespace IN ('deployment-prepare-v1','deployment-cancel-v1')),
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024),
 input_json TEXT NOT NULL CHECK(length(input_json) BETWEEN 2 AND 4096),
 input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
 http_status INTEGER NOT NULL CHECK(http_status IN (200,201)),
 receipt_json TEXT NOT NULL CHECK(length(receipt_json) BETWEEN 2 AND 8192),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 2),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(namespace,request_id),
 FOREIGN KEY(request_id,lifecycle_revision)
  REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((namespace='deployment-prepare-v1' AND http_status=201 AND lifecycle_revision=1)
    OR (namespace='deployment-cancel-v1' AND http_status=200 AND lifecycle_revision=2))
);""",
    """CREATE TABLE deployment_prepare_outbox (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 role TEXT NOT NULL CHECK(role IN ('request','cancel')),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 2),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 payload_size INTEGER NOT NULL CHECK(payload_size BETWEEN 1 AND 65536),
 state TEXT NOT NULL CHECK(state IN ('pending','published','suppressed')),
 published_ms INTEGER CHECK(published_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,role),
 FOREIGN KEY(request_id,lifecycle_revision)
  REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((role='request' AND lifecycle_revision=1)
    OR (role='cancel' AND lifecycle_revision=2 AND state<>'suppressed')),
 CHECK((state='pending' AND revision=1 AND published_ms IS NULL)
    OR (state='published' AND revision=2 AND published_ms IS NOT NULL)
    OR (state='suppressed' AND revision=2 AND published_ms IS NULL))
);""",
)

DDL_V2 = (
    """CREATE TABLE deployment_prepare_migrations (
 version INTEGER PRIMARY KEY CHECK(version IN (1,2)),
 checksum TEXT NOT NULL CHECK(length(checksum)=64)
);""",
    DDL[1],
    DDL[2],
    """CREATE TABLE deployment_prepare_lifecycle (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 3),
 previous_revision INTEGER, previous_hash TEXT,
 state TEXT NOT NULL CHECK(state IN ('prepared','cancelled','expired','receipt_pending','rejected')),
 transitioned_ms INTEGER NOT NULL CHECK(transitioned_ms BETWEEN 0 AND 253402300799999),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024), command_id TEXT,
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,revision), UNIQUE(request_id,revision,hash), UNIQUE(command_id),
 FOREIGN KEY(request_id,previous_revision,previous_hash)
  REFERENCES deployment_prepare_lifecycle(request_id,revision,hash),
 FOREIGN KEY(command_id) REFERENCES deployment_prepare_commands(command_id) DEFERRABLE INITIALLY DEFERRED,
 CHECK((revision=1 AND state='prepared' AND previous_revision IS NULL AND previous_hash IS NULL AND command_id IS NOT NULL)
  OR (revision=2 AND state IN ('cancelled','expired','receipt_pending','rejected') AND previous_revision IS NOT NULL AND previous_revision=1 AND previous_hash IS NOT NULL)
  OR (revision=3 AND state IN ('cancelled','expired') AND previous_revision IS NOT NULL AND previous_revision=2 AND previous_hash IS NOT NULL)),
 CHECK((state='expired' AND command_id IS NULL) OR (state<>'expired' AND command_id IS NOT NULL))
);""",
    """CREATE TABLE deployment_prepare_heads (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 3),
 lifecycle_hash TEXT NOT NULL CHECK(length(lifecycle_hash)=64), hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,revision,lifecycle_hash) REFERENCES deployment_prepare_lifecycle(request_id,revision,hash)
);""",
    """CREATE TABLE deployment_prepare_commands (
 command_id TEXT PRIMARY KEY CHECK(length(command_id)=36),
 namespace TEXT NOT NULL CHECK(namespace IN ('deployment-prepare-v1','deployment-cancel-v1','deployment-cancel-v2','deployment-receipt-import-v1')),
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 actor_ref TEXT NOT NULL CHECK(length(actor_ref) BETWEEN 1 AND 1024),
 input_json TEXT NOT NULL CHECK(length(input_json) BETWEEN 2 AND 4096),
 input_digest TEXT NOT NULL CHECK(length(input_digest)=64),
 http_status INTEGER NOT NULL CHECK(http_status IN (200,201)),
 receipt_json TEXT NOT NULL CHECK(length(receipt_json) BETWEEN 2 AND 8192),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 3),
 hash TEXT NOT NULL CHECK(length(hash)=64), UNIQUE(namespace,request_id),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((namespace='deployment-prepare-v1' AND http_status=201 AND lifecycle_revision=1)
  OR (namespace='deployment-cancel-v1' AND http_status=200 AND lifecycle_revision=2)
  OR (namespace='deployment-cancel-v2' AND http_status=200 AND lifecycle_revision=3)
  OR (namespace='deployment-receipt-import-v1' AND http_status=200 AND lifecycle_revision=2))
);""",
    """CREATE TABLE deployment_prepare_outbox (
 request_id TEXT NOT NULL REFERENCES deployment_prepare_requests(request_id),
 role TEXT NOT NULL CHECK(role IN ('request','cancel')),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision BETWEEN 1 AND 3),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 payload_size INTEGER NOT NULL CHECK(payload_size BETWEEN 1 AND 65536),
 state TEXT NOT NULL CHECK(state IN ('pending','published','suppressed')),
 published_ms INTEGER CHECK(published_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2), hash TEXT NOT NULL CHECK(length(hash)=64),
 PRIMARY KEY(request_id,role),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 CHECK((role='request' AND lifecycle_revision=1)
  OR (role='cancel' AND lifecycle_revision IN (2,3) AND state<>'suppressed')),
 CHECK((state='pending' AND revision=1 AND published_ms IS NULL)
  OR (state='published' AND revision=2 AND published_ms IS NOT NULL)
  OR (state='suppressed' AND revision=2 AND published_ms IS NULL))
);""",
    """CREATE TABLE deployment_prepare_receipt_sources (
 singleton INTEGER PRIMARY KEY CHECK(singleton=1) REFERENCES deployment_prepare_control(singleton),
 vault_id TEXT NOT NULL REFERENCES domain_vault(vault_id),
 purpose TEXT NOT NULL CHECK(purpose='operational'),
 trust_sha256 TEXT NOT NULL CHECK(length(trust_sha256)=64),
 trust_size INTEGER NOT NULL CHECK(trust_size BETWEEN 1 AND 16384),
 ingress_sha256 TEXT NOT NULL CHECK(length(ingress_sha256)=64),
 ingress_size INTEGER NOT NULL CHECK(ingress_size BETWEEN 1 AND 8192),
 consumption_exchange_sha256 TEXT NOT NULL CHECK(length(consumption_exchange_sha256)=64),
 consumption_exchange_size INTEGER NOT NULL CHECK(consumption_exchange_size BETWEEN 1 AND 8192),
 identity_json TEXT NOT NULL CHECK(length(identity_json) BETWEEN 2 AND 8192),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(vault_id,purpose,trust_sha256) REFERENCES domain_blobs(vault_id,purpose,sha256),
 FOREIGN KEY(vault_id,purpose,ingress_sha256) REFERENCES domain_blobs(vault_id,purpose,sha256),
 FOREIGN KEY(vault_id,purpose,consumption_exchange_sha256) REFERENCES domain_blobs(vault_id,purpose,sha256)
);""",
    """CREATE TABLE deployment_prepare_receipts (
 request_id TEXT PRIMARY KEY REFERENCES deployment_prepare_requests(request_id),
 vault_id TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind='deployment_receipt'),
 version INTEGER NOT NULL CHECK(version=1), anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 receipt_sha256 TEXT NOT NULL UNIQUE CHECK(length(receipt_sha256)=64),
 receipt_size INTEGER NOT NULL CHECK(receipt_size BETWEEN 1 AND 16384),
 outcome TEXT NOT NULL CHECK(outcome IN ('succeeded','failed','unknown')),
 source_singleton INTEGER NOT NULL CHECK(source_singleton=1) REFERENCES deployment_prepare_receipt_sources(singleton),
 import_command_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_commands(command_id),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision=2), hash TEXT NOT NULL CHECK(length(hash)=64),
 UNIQUE(request_id,receipt_sha256),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 FOREIGN KEY(vault_id,kind,request_id,version,anchor_digest) REFERENCES domain_records(vault_id,kind,id,version,sha256)
);""",
    """CREATE TABLE deployment_prepare_consumptions (
 request_id TEXT PRIMARY KEY, receipt_sha256 TEXT NOT NULL UNIQUE CHECK(length(receipt_sha256)=64),
 consumption_id TEXT NOT NULL UNIQUE CHECK(length(consumption_id)=36), vault_id TEXT NOT NULL,
 kind TEXT NOT NULL CHECK(kind='deployment_receipt_consumption'), version INTEGER NOT NULL CHECK(version=1),
 anchor_digest TEXT NOT NULL CHECK(length(anchor_digest)=64),
 lifecycle_revision INTEGER NOT NULL CHECK(lifecycle_revision=2),
 command_id TEXT NOT NULL UNIQUE REFERENCES deployment_prepare_commands(command_id),
 event_id TEXT NOT NULL UNIQUE REFERENCES api_event_envelopes(event_id),
 consumed_ms INTEGER NOT NULL CHECK(consumed_ms BETWEEN 0 AND 253402300799999),
 hash TEXT NOT NULL CHECK(length(hash)=64),
 FOREIGN KEY(request_id,receipt_sha256) REFERENCES deployment_prepare_receipts(request_id,receipt_sha256),
 FOREIGN KEY(request_id,lifecycle_revision) REFERENCES deployment_prepare_lifecycle(request_id,revision),
 FOREIGN KEY(vault_id,kind,consumption_id,version,anchor_digest) REFERENCES domain_records(vault_id,kind,id,version,sha256)
);""",
    """CREATE TABLE deployment_prepare_consumed_outbox (
 consumption_id TEXT PRIMARY KEY REFERENCES deployment_prepare_consumptions(consumption_id),
 payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256)=64),
 payload_size INTEGER NOT NULL CHECK(payload_size BETWEEN 1 AND 4096),
 state TEXT NOT NULL CHECK(state IN ('pending','published')),
 published_ms INTEGER CHECK(published_ms BETWEEN 0 AND 253402300799999),
 revision INTEGER NOT NULL CHECK(revision BETWEEN 1 AND 2), hash TEXT NOT NULL CHECK(length(hash)=64),
 CHECK((state='pending' AND revision=1 AND published_ms IS NULL)
  OR (state='published' AND revision=2 AND published_ms IS NOT NULL))
);""",
)

CHECKSUM = sha256(canonical_json(list(DDL))).hexdigest()
TABLES = ("control", "requests", "lifecycle", "heads", "commands", "outbox")
CAPS = {
    "control": 1,
    "requests": 16,
    "lifecycle": 32,
    "heads": 16,
    "commands": 32,
    "outbox": 32,
}
NULLABLE = {
    "lifecycle": {"previous_revision", "previous_hash", "command_id"},
    "outbox": {"published_ms"},
}
CHECKSUM_V2 = sha256(canonical_json(list(DDL_V2))).hexdigest()
TABLES_V2 = (*TABLES, "receipt_sources", "receipts", "consumptions", "consumed_outbox")
CAPS_V2 = {
    **CAPS,
    "lifecycle": 48,
    "commands": 48,
    "receipt_sources": 1,
    "receipts": 16,
    "consumptions": 16,
    "consumed_outbox": 16,
}
NULLABLE_V2 = {**NULLABLE, "consumed_outbox": {"published_ms"}}


def fail():
    raise DeploymentPrepareError("unavailable")


def shape(db):
    return {
        r["name"]: (r["type"], r["tbl_name"], r["sql"])
        for r in db.execute(
            "SELECT name,type,tbl_name,sql FROM sqlite_master WHERE lower(name) GLOB 'deployment_prepare_*' "
            "OR type='trigger' OR (lower(tbl_name) GLOB 'deployment_prepare_*' AND sql IS NOT NULL) "
            "OR (type='view' AND lower(sql) LIKE '%deployment_prepare_%')"
        )
    }


def _expected(ddl=DDL, tables=TABLES):
    with closing(sqlite3.connect(":memory:")) as db:
        db.row_factory = sqlite3.Row
        for statement in ddl:
            db.execute(statement)
        expected = shape(db)
        columns = {
            table: {
                row[1]: int if row[2] == "INTEGER" else str
                for row in db.execute(
                    "PRAGMA table_info(deployment_prepare_" + table + ")"
                )
            }
            for table in tables
        }
        return expected, columns


SHAPE, COLUMNS = _expected(DDL, TABLES)
SHAPE_V2, COLUMNS_V2 = _expected(DDL_V2, TABLES_V2)


@dataclass(frozen=True)
class _Layout:
    ddl: tuple
    tables: tuple
    shape: object
    columns: object
    caps: object
    nullable: object
    migrations: tuple


def _freeze(ddl, tables, expected, columns, caps, nullable, migrations):
    return _Layout(
        ddl,
        tables,
        MappingProxyType(expected.copy()),
        MappingProxyType(
            {key: MappingProxyType(value.copy()) for key, value in columns.items()}
        ),
        MappingProxyType(caps.copy()),
        MappingProxyType({key: frozenset(value) for key, value in nullable.items()}),
        migrations,
    )


_V1 = _freeze(DDL, TABLES, SHAPE, COLUMNS, CAPS, NULLABLE, ((1, CHECKSUM),))
_V2 = _freeze(
    DDL_V2,
    TABLES_V2,
    SHAPE_V2,
    COLUMNS_V2,
    CAPS_V2,
    NULLABLE_V2,
    ((1, CHECKSUM), (2, CHECKSUM_V2)),
)


def _private_sizes(db, layout):
    caps = {
        "input_json": 4096,
        "receipt_json": 8192,
        "exchange_identity_json": 4096,
        "identity_json": 8192,
        "checksum": 64,
    }
    for table, columns in {
        "migrations": {"version": int, "checksum": str},
        **layout.columns,
    }.items():
        cap = len(layout.migrations) if table == "migrations" else layout.caps[table]
        expressions = [
            expression
            for name in columns
            for expression in (
                "typeof(" + name + ")",
                "length(CAST(" + name + " AS BLOB))",
            )
        ]
        values = list(
            db.execute(
                "SELECT "
                + ",".join(expressions)
                + " FROM deployment_prepare_"
                + table
                + " LIMIT ?",
                (cap + 1,),
            )
        )
        if len(values) > cap:
            fail()
        for row in values:
            for index, (name, expected) in enumerate(columns.items()):
                kind, size = row[2 * index : 2 * index + 2]
                if not (
                    (kind == "null" and name in layout.nullable.get(table, ()))
                    or (expected is int and kind == "integer")
                    or (
                        expected is str
                        and kind == "text"
                        and size <= caps.get(name, 1024)
                    )
                ):
                    fail()


def _layout(db):
    observed = shape(db)
    if observed == _V1.shape:
        layout = _V1
    elif observed == _V2.shape:
        layout = _V2
    else:
        fail()
    _private_sizes(db, layout)
    migration = tuple(
        tuple(row)
        for row in db.execute(
            "SELECT version,checksum FROM deployment_prepare_migrations ORDER BY version LIMIT ?",
            (len(layout.migrations) + 1,),
        )
    )
    if migration != layout.migrations:
        fail()
    return layout


def encoded(value):
    return canonical_json(value).decode("utf-8")


def _json(value, cap):
    if type(value) is not str or not 2 <= len(value.encode("utf-8")) <= cap:
        fail()
    return parse_canonical(value.encode("utf-8"))


def _hex(value, size=64):
    if (
        type(value) is not str
        or re.fullmatch("[0-9a-f]{" + str(size) + "}", value) is None
    ):
        fail()


def validate_identity(value):
    try:
        body = _json(value, 4096)
        if type(body) is not dict or set(body) != {
            "schema_version",
            "root",
            "requests",
            "cancelled",
            "backing_root_digest",
        }:
            fail()
        if body["schema_version"] != "deployment-outbox-identity-v1":
            fail()
        _hex(body["backing_root_digest"])
        for name in ("root", "requests", "cancelled"):
            pair = body[name]
            if type(pair) is not dict or set(pair) != {"device", "inode"}:
                fail()
            if (
                type(pair["device"]) is not int
                or not 0 <= pair["device"] <= 2**63 - 1
                or type(pair["inode"]) is not int
                or not 1 <= pair["inode"] <= 2**63 - 1
            ):
                fail()
        identities = [
            (body[k]["device"], body[k]["inode"])
            for k in ("root", "requests", "cancelled")
        ]
        if (
            len(set(identities)) != 3
            or len({identity[0] for identity in identities}) != 1
        ):
            fail()
        return body
    except (ValueError, TypeError, UnicodeError, RecursionError):
        fail()


def validate_receipt_identity(value):
    require(
        type(value) is dict and set(value) == {"trust", "ingress", "consumption"},
        "unavailable",
    )
    identities = []

    def pair(item):
        require(
            type(item) is dict
            and set(item) == {"device", "inode"}
            and type(item["device"]) is int
            and 0 <= item["device"] < 2**63
            and type(item["inode"]) is int
            and 0 < item["inode"] < 2**63,
            "unavailable",
        )
        identities.append((item["device"], item["inode"]))

    for name, observation in value.items():
        source = observation if name == "trust" else observation["source"]
        require(
            type(source) is dict
            and set(source)
            == {"schema_version", "source_kind", "root", "file", "backing_root_digest"}
            and source["schema_version"] == "deployment-public-source-identity-v1"
            and source["source_kind"] == name,
            "unavailable",
        )
        _hex(source["backing_root_digest"])
        pair(source["root"])
        pair(source["file"])
        require(source["root"]["device"] == source["file"]["device"], "unavailable")
        if name != "trust":
            child = "receipts" if name == "ingress" else "consumed"
            require(
                set(observation)
                == {"schema_version", "source", "root", child, "backing_root_digest"}
                and observation["schema_version"]
                == (
                    "deployment-receipt-ingress-identity-v1"
                    if name == "ingress"
                    else "deployment-consumed-identity-v1"
                ),
                "unavailable",
            )
            _hex(observation["backing_root_digest"])
            pair(observation["root"])
            pair(observation[child])
            require(
                observation["root"]["device"] == observation[child]["device"],
                "unavailable",
            )
    require(len(set(identities)) == len(identities), "unavailable")


def digest(table, values):
    if type(table) is not str or table not in TABLES_V2:
        fail()
    return sha256(
        canonical_json(
            {
                "namespace": "deployment-prepare-storage-v1"
                if table in TABLES
                else "deployment-prepare-storage-v2",
                "table": table,
                "row": {k: v for k, v in dict(values).items() if k != "hash"},
            }
        )
    ).hexdigest()


def _row(layout, table, row):
    """Verify Python scalar types and canonical fields in addition to SQL CHECKs."""
    if table not in layout.tables or set(row) != set(layout.columns[table]):
        fail()
    for key, value in row.items():
        if value is None and key in layout.nullable.get(table, ()):
            continue
        if type(value) is not layout.columns[table][key]:
            fail()
        if key in {
            "request_id",
            "vault_id",
            "topology_id",
            "exchange_id",
            "command_id",
            "event_id",
            "consumption_id",
            "import_command_id",
        }:
            uuid_string(value)
        if key in {
            "hash",
            "previous_hash",
            "anchor_digest",
            "nonce_hex",
            "origin_digest",
            "topology_sha256",
            "exchange_sha256",
            "lifecycle_hash",
            "input_digest",
            "payload_sha256",
            "receipt_sha256",
            "trust_sha256",
            "ingress_sha256",
            "consumption_exchange_sha256",
        }:
            _hex(value)
        if key == "instance_id":
            _hex(value, 32)
        if key == "request_digest":
            parse_base64url_32(value)
        if (
            key == "extension_id"
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?", value) is None
        ):
            fail()
        if (
            key == "actor_ref"
            and EntityRef.from_dict(_json(value, 1024)).kind != "actor"
        ):
            fail()
        if key in {"input_json", "receipt_json"}:
            body = _json(value, 4096 if key == "input_json" else 8192)
            if type(body) is not dict:
                fail()
        if key == "exchange_identity_json":
            validate_identity(value)
        if key == "identity_json":
            validate_receipt_identity(_json(value, 8192))
    if row["hash"] != digest(table, row):
        fail()


def _check_rows(layout, rows):
    # An isolated in-memory schema checks the *same literal* CHECK/UNIQUE constraints,
    # including NULL logic, even if a damaged disk was edited with ignore_check_constraints.
    # Domain/event foreign keys are checked against the real database in verify().
    with closing(sqlite3.connect(":memory:")) as checks:
        for statement in layout.ddl:
            checks.execute(statement)
        for table, values in rows.items():
            for row in values:
                _row(layout, table, row)
                checks.execute(
                    "INSERT INTO deployment_prepare_"
                    + table
                    + " ("
                    + ",".join(row)
                    + ") VALUES ("
                    + ",".join("?" for _ in row)
                    + ")",
                    tuple(row.values()),
                )


def _validate_row(layout, table, row):
    try:
        _check_rows(layout, {table: [dict(row)]})
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        RecursionError,
        sqlite3.Error,
    ):
        fail()


def validate_row(table, row):
    _validate_row(_V1, table, row)


def validate_current_row(db, table, row):
    _validate_row(_layout(db), table, row)


def insert(db, table, values):
    layout = _layout(db)
    if (
        type(table) is not str
        or table not in layout.tables
        or type(values) is not dict
        or set(values) != set(layout.columns[table]) - {"hash"}
    ):
        fail()
    row = {**values, "hash": digest(table, values)}
    _validate_row(layout, table, row)
    db.execute(
        "INSERT INTO deployment_prepare_"
        + table
        + " ("
        + ",".join(row)
        + ") VALUES ("
        + ",".join("?" for _ in row)
        + ")",
        tuple(row.values()),
    )
    return row


def advance(db, table, old, changes):
    layout = _layout(db)
    allowed = {
        "control": {"clock_floor_ms"},
        "heads": {"lifecycle_hash"},
        "outbox": {"state", "published_ms"},
        "consumed_outbox": {"state", "published_ms"},
    }
    identities = {
        "control": ("singleton",),
        "heads": ("request_id",),
        "outbox": ("request_id", "role"),
        "consumed_outbox": ("consumption_id",),
    }
    if (
        type(table) is not str
        or table not in allowed
        or type(changes) is not dict
        or set(changes) != allowed[table]
    ):
        fail()
    _validate_row(layout, table, old)
    if table == "control" and (
        type(changes["clock_floor_ms"]) is not int
        or changes["clock_floor_ms"] < old["clock_floor_ms"]
    ):
        fail()
    if table in {"outbox", "consumed_outbox"} and (
        old["state"] != "pending"
        or changes["state"]
        not in ({"published", "suppressed"} if table == "outbox" else {"published"})
    ):
        fail()
    row = {**dict(old), **changes, "revision": old["revision"] + 1}
    row["hash"] = digest(table, row)
    _validate_row(layout, table, row)
    changed = {key: row[key] for key in (*changes, "revision", "hash")}
    keys = identities[table]
    result = db.execute(
        "UPDATE deployment_prepare_"
        + table
        + " SET "
        + ",".join(k + "=?" for k in changed)
        + " WHERE "
        + " AND ".join(k + "=?" for k in keys)
        + " AND revision=? AND hash=?",
        (*changed.values(), *(old[k] for k in keys), old["revision"], old["hash"]),
    )
    if result.rowcount != 1:
        fail()
    return row


def install(db):
    if not shape(db):
        if (
            db.execute(
                "SELECT 1 FROM domain_records WHERE kind='deployment_request' LIMIT 1"
            ).fetchone()
            is not None
        ):
            fail()
        for statement in DDL:
            db.execute(statement)
        db.execute("INSERT INTO deployment_prepare_migrations VALUES(1,?)", (CHECKSUM,))
    if _layout(db) is not _V1:
        fail()
    verify(db)


def verify(db):
    try:
        layout = _layout(db)
        rows = {
            table: [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM deployment_prepare_" + table + " LIMIT ?",
                    (layout.caps[table] + 1,),
                )
            ]
            for table in layout.tables
        }
        if any(len(values) > layout.caps[table] for table, values in rows.items()):
            fail()
        _check_rows(layout, rows)
        if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
            fail()
        return rows
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        RecursionError,
        sqlite3.Error,
    ):
        fail()


def _rebuild_v1_as_v2(db):
    if _layout(db) is not _V1 or db.execute("PRAGMA foreign_keys").fetchone()[0] != 1:
        fail()
    keys = {
        "migrations": ("version",),
        "lifecycle": ("request_id", "revision"),
        "commands": ("command_id",),
        "heads": ("request_id",),
        "outbox": ("request_id", "role"),
    }
    snapshots = {
        table: [
            dict(row)
            for row in db.execute(
                "SELECT * FROM deployment_prepare_"
                + table
                + " ORDER BY "
                + ",".join(pk)
                + " LIMIT ?",
                ((1 if table == "migrations" else CAPS[table]) + 1,),
            )
        ]
        for table, pk in keys.items()
    }
    unchanged = {
        table: [
            tuple(row)
            for row in db.execute(
                "SELECT * FROM deployment_prepare_" + table + " ORDER BY 1 LIMIT ?",
                (CAPS[table] + 1,),
            )
        ]
        for table in ("control", "requests")
    }
    db.execute("PRAGMA defer_foreign_keys=ON")
    if db.execute("PRAGMA defer_foreign_keys").fetchone()[0] != 1:
        fail()
    for table in ("outbox", "heads", "commands", "lifecycle", "migrations"):
        for row in reversed(snapshots[table]):
            db.execute(
                "DELETE FROM deployment_prepare_"
                + table
                + " WHERE "
                + " AND ".join(key + "=?" for key in keys[table]),
                tuple(row[key] for key in keys[table]),
            )
    for table in ("outbox", "heads", "commands", "lifecycle", "migrations"):
        db.execute("DROP TABLE deployment_prepare_" + table)
    for statement in (DDL_V2[0], *DDL_V2[3:]):
        db.execute(statement)
    for table in ("migrations", "lifecycle", "commands", "heads", "outbox"):
        for row in snapshots[table]:
            db.execute(
                "INSERT INTO deployment_prepare_"
                + table
                + " ("
                + ",".join(row)
                + ") VALUES ("
                + ",".join("?" for _ in row)
                + ")",
                tuple(row.values()),
            )
    db.execute("INSERT INTO deployment_prepare_migrations VALUES(2,?)", (CHECKSUM_V2,))
    for table, pk in keys.items():
        restored = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM deployment_prepare_"
                + table
                + " ORDER BY "
                + ",".join(pk)
                + " LIMIT ?",
                (len(snapshots[table]) + 2,),
            )
        ]
        if table == "migrations":
            restored = restored[:1]
        if restored != snapshots[table]:
            fail()
    for table, before in unchanged.items():
        if [
            tuple(row)
            for row in db.execute(
                "SELECT * FROM deployment_prepare_" + table + " ORDER BY 1 LIMIT ?",
                (CAPS[table] + 1,),
            )
        ] != before:
            fail()
