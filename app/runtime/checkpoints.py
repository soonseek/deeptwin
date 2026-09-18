"""Bounded root StateGraph checkpoint journal in the existing runtime ledger.

This synchronous development profile accepts only results (execution UUID to
EntityRef), counters, and ordinary root branch controls. Invoke with durability
``sync``. It does not approve graphs, dispatch workers, admit semantic results,
support dynamic interrupts/subgraphs/delta channels, or authorize time travel.
Only ledger cursor records are durable; the reconstructed index is disposable.
"""
import re
from collections import deque
from copy import deepcopy
from datetime import datetime
from hashlib import sha256
from threading import RLock
from uuid import uuid4

from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    CheckpointTuple,
)

from ..domain.refs import (
    MAX_INTEGER,
    EntityRef,
    canonical_json,
    parse_canonical,
    uuid_string,
)
from .ledger import MAX_CHECKPOINT_BYTES, RuntimeLedger

NAMESPACE = "langgraph-v1"
MAX_RECORDS = 4096
MAX_HISTORY_BYTES = 16 * 1024 * 1024
MAX_ENTRIES = 1024
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")


class CheckpointError(ValueError):
    """Safe, fixed diagnostic; private graph/config/exception text is excluded."""


def _require(condition, message="Unsupported checkpoint profile"):
    if not condition:
        raise CheckpointError(message)


def _mapping(value, maximum=MAX_ENTRIES):
    _require(type(value) is dict and len(value) <= maximum)
    return value


def _fields(value, fields):
    _mapping(value)
    _require(set(value) == set(fields))


def _uuid(value):
    try:
        uuid_string(value)
    except (TypeError, ValueError):
        raise CheckpointError("Invalid checkpoint identifier") from None
    return value


def _number(value, minimum=0, maximum=MAX_INTEGER):
    _require(type(value) is int and minimum <= value <= maximum)
    return value


class _NoObjectSerializer:
    """Block inherited serializer entrypoints; the adapter uses its closed codec."""
    def dumps_typed(self, value):
        raise CheckpointError("Use the closed checkpoint journal codec")

    def loads_typed(self, value):
        raise CheckpointError("Object deserialization is unsupported")


class AttemptBindings:
    """The per-run registry of which accepted attempt produced which execution's
    result (T040 checkpoint↔attempt binding). The scheduler registers a pair after
    the visit's capability committed; the saver binds each pending-writes row that
    carries exactly that execution's result to the attempt, and nothing else. In
    memory only, bounded by the journal's own record limit: on restart the rows
    already carry their binding and no already-durable result is written again."""

    __slots__ = ("_entries", "_lock")

    def __init__(self):
        self._entries = {}
        self._lock = RLock()

    def set(self, execution_id, attempt_id):
        execution_id, attempt_id = _uuid(execution_id), _uuid(attempt_id)
        with self._lock:
            current = self._entries.get(execution_id)
            _require(current is None or current == attempt_id,
                     "An execution's result is produced by one attempt")
            _require(current is not None or len(self._entries) < MAX_RECORDS,
                     "Attempt binding registry bound reached")
            self._entries[execution_id] = attempt_id

    def get(self, execution_id):
        with self._lock:
            return self._entries.get(execution_id)


class LedgerCheckpointSaver(BaseCheckpointSaver[int]):
    def __init__(self, ledger, run_id, *, graph_digest, authority_digest,
                 node_ids=(), max_records=MAX_RECORDS, max_history_bytes=MAX_HISTORY_BYTES,
                 attempt_bindings=None):
        super().__init__(serde=_NoObjectSerializer())
        _require(type(ledger) is RuntimeLedger, "An exact RuntimeLedger is required")
        _require(attempt_bindings is None or type(attempt_bindings) is AttemptBindings,
                 "An exact AttemptBindings registry is required")
        self._bindings = attempt_bindings
        self._ledger, self._run_id = ledger, _uuid(run_id)
        for digest in (graph_digest, authority_digest):
            _require(type(digest) is str and _DIGEST.fullmatch(digest) is not None)
        _require(type(node_ids) in (tuple, list) and len(node_ids) <= 256)
        for node in node_ids:
            _require(type(node) is str and _ID.fullmatch(node) is not None)
        _require(len(set(node_ids)) == len(node_ids))
        self._nodes = frozenset(node_ids)
        self._max_records = _number(max_records, 1, MAX_RECORDS)
        self._max_bytes = _number(max_history_bytes, 1, MAX_HISTORY_BYTES)
        self._lock = RLock()
        self._halted = False
        self._revision, self._bytes, self._digest = 0, 0, None
        self._checkpoints, self._writes = {}, {}
        try:
            run = ledger.get_run(run_id)["spec"]
            self._binding = {"run_id": run_id, "graph_digest": graph_digest,
                "authority_digest": authority_digest, "environment_ref": run["environment_ref"],
                "manifest_ref": run["manifest_ref"], "node_ids": sorted(self._nodes)}
            head = self._head()
            if head is not None:
                _number(head["revision"], 1, self._max_records)
                for revision in range(1, head["revision"] + 1):
                    row = ledger.checkpoint_for_replay(run_id, NAMESPACE, revision=revision)
                    self._consume(row["cursor"])
            self._check_head()
        except Exception:  # noqa: BLE001 - Fail closed; recovery errors may contain private data.
            self._halted = True
            raise CheckpointError("Checkpoint recovery or binding validation failed") from None

    def _head(self):
        # This API checks both startup reconciliation and current ledger session.
        try:
            return self._ledger.checkpoint_for_replay(self._run_id, NAMESPACE)
        except KeyError:
            return None

    def _check_head(self):
        _require(not self._halted, "Checkpoint saver is halted")
        try:
            head = self._head()
            actual = (0, None) if head is None else (head["revision"], head["cursor_sha256"])
            _require(actual == (self._revision, self._digest), "Checkpoint journal head changed")
        except Exception:  # noqa: BLE001 - Halt on any session/read failure without exposing details.
            self._halted = True
            raise CheckpointError("Checkpoint journal or ledger session changed; saver halted") from None

    def _config_id(self, config):
        _require(type(config) is dict and type(config.get("configurable")) is dict)
        cfg = config["configurable"]
        _require(cfg.get("thread_id") == self._run_id, "Checkpoint thread binding mismatch")
        _require(cfg.get("checkpoint_ns", "") == "", "Only the root namespace is supported")
        _require(not cfg.get("checkpoint_map"), "Subgraph checkpoint maps are unsupported")
        value = cfg.get("checkpoint_id")
        return None if value is None else _uuid(value)

    def _config(self, checkpoint_id):
        return {"configurable": {"thread_id": self._run_id, "checkpoint_ns": "",
                                  "checkpoint_id": checkpoint_id}}

    def _channel(self, name):
        _require(type(name) is str)
        _require(name in {"results", "counters", "__start__"}
                 or (name.startswith("branch:to:") and name[10:] in self._nodes))
        return name

    def _value(self, channel, value, *, decoding=False):
        self._channel(channel)
        if channel == "results":
            result = {}
            for key, ref in _mapping(value).items():
                _uuid(key)
                if decoding:
                    _fields(ref, ("kind", "id", "version", "sha256"))
                    try:
                        result[key] = EntityRef.from_dict(ref)
                    except (TypeError, ValueError):
                        raise CheckpointError("Invalid result reference") from None
                else:
                    _require(type(ref) is EntityRef, "Exact EntityRef required")
                    result[key] = ref.as_dict()
            return result
        if channel == "counters":
            for key, number in _mapping(value).items():
                _require(type(key) is str and _ID.fullmatch(key) is not None)
                _number(number)
            return dict(value)
        if channel == "__start__":
            _require(set(_mapping(value)) <= {"results", "counters"})
            return {key: self._value(key, item, decoding=decoding) for key, item in value.items()}
        _require(value is None)
        return None

    def _versions(self, values):
        for channel, version in _mapping(values).items():
            self._channel(channel)
            _number(version)
        return dict(values)

    def _pending_value(self, channel, value, *, decoding=False):
        # Completion markers belong only to the pending-write journal, never state.
        if channel == "__no_writes__":
            _require(value is None, "No-writes completion marker must be null")
            return None
        if channel == "__error__":
            # Never inspect exception arguments, repr, or arbitrary metadata.
            if decoding:
                _require(value == "node_failed")
            return "node_failed"
        return self._value(channel, value, decoding=decoding)

    def _checkpoint(self, value, *, decoding=False):
        _fields(value, ("v", "id", "ts", "channel_values", "channel_versions",
                        "versions_seen", "updated_channels"))
        _require(type(value["v"]) is int and value["v"] == 4)
        _uuid(value["id"])
        stamp = value["ts"]
        _require(type(stamp) is str and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00", stamp) is not None)
        try:
            datetime.fromisoformat(stamp)
        except ValueError:
            raise CheckpointError("Invalid checkpoint timestamp") from None
        values = {key: self._value(key, item, decoding=decoding)
                  for key, item in _mapping(value["channel_values"]).items()}
        versions = self._versions(value["channel_versions"])
        _require(set(values) <= set(versions))
        seen = {}
        for node, version in _mapping(value["versions_seen"]).items():
            _require(node in self._nodes | {"__input__", "__start__", "__interrupt__"})
            seen[node] = self._versions(version)
            _require(all(key in versions and number <= versions[key] for key, number in version.items()))
        updated = value["updated_channels"]
        _require(type(updated) is list and len(updated) <= MAX_ENTRIES)
        _require(all(type(key) is str and key in versions for key in updated))
        _require(len(set(updated)) == len(updated))
        return {**value, "channel_values": values, "channel_versions": versions,
                "versions_seen": seen, "updated_channels": list(updated)}

    def _metadata(self, value):
        _fields(value, ("source", "step", "parents"))
        _require(value["source"] in ("input", "loop"), "State editing and forks are unsupported")
        _number(value["step"], -1)
        _require(type(value["parents"]) is dict and value["parents"] == {})
        return deepcopy(value)

    def _validate_data(self, kind, data):
        if kind == "checkpoint":
            _fields(data, ("checkpoint", "metadata", "parent", "new_versions"))
            cp = self._checkpoint(data["checkpoint"], decoding=True)
            _require(cp["id"] not in self._checkpoints, "Duplicate checkpoint ID")
            parent = data["parent"]
            latest = next(reversed(self._checkpoints), None)
            _require(parent == latest, "Checkpoint parent must be the current head")
            if latest is not None:
                _require(cp["id"] > latest, "Checkpoint IDs must increase")
            self._metadata(data["metadata"])
            new = self._versions(data["new_versions"])
            previous = {} if parent is None else self._checkpoints[parent]["checkpoint"]["channel_versions"]
            versions = cp["channel_versions"]
            _require(set(previous) <= set(versions))
            _require(all(versions[key] >= version for key, version in previous.items()))
            changed = {key: version for key, version in versions.items() if previous.get(key) != version}
            _require(new == changed, "New channel versions mismatch")
            if parent is not None:
                previous_values = self._checkpoints[parent]["checkpoint"]["channel_values"]
                values = data["checkpoint"]["channel_values"]
                for key in set(previous_values) | set(values):
                    if key not in changed:
                        _require(key in values and key in previous_values
                                 and values[key] == previous_values[key],
                                 "Channel state changed without a new version")
        elif kind == "writes":
            _fields(data, ("checkpoint_id", "task_id", "task_path", "writes"))
            cp_id = _uuid(data["checkpoint_id"])
            _require(cp_id in self._checkpoints, "Pending writes require a committed checkpoint")
            _require(cp_id == next(reversed(self._checkpoints)),
                     "Pending writes must target the current checkpoint")
            _uuid(data["task_id"])
            _require(data["task_path"] == "" or data["task_path"] in
                     {"~__pregel_pull, " + node for node in self._nodes | {"__start__"}})
            writes = data["writes"]
            _require(type(writes) is list and len(writes) <= MAX_ENTRIES)
            previous = self._writes.get(cp_id, {})
            for position, entry in enumerate(writes):
                _fields(entry, ("index", "channel", "value"))
                channel = entry["channel"]
                _require(type(channel) is str)
                _require(type(entry["index"]) is int and entry["index"] == WRITES_IDX_MAP.get(channel, position))
                self._pending_value(channel, entry["value"], decoding=True)
                old = previous.get((data["task_id"], entry["index"]))
                if entry["index"] >= 0 and old is not None:
                    _require(old == entry, "Conflicting pending write identity")
        else:
            raise CheckpointError("Unsupported journal record")

    def _consume(self, raw):
        _require(type(raw) is bytes and len(raw) <= MAX_CHECKPOINT_BYTES)
        _require(self._revision < self._max_records and self._bytes + len(raw) <= self._max_bytes,
                 "Checkpoint journal limit reached")
        record = parse_canonical(raw)
        _fields(record, ("v", "binding", "previous_sha256", "kind", "data"))
        _require(type(record["v"]) is int and record["v"] == 1)
        _require(record["binding"] == self._binding, "Checkpoint journal binding mismatch")
        _require(record["previous_sha256"] == self._digest, "Checkpoint journal prefix mismatch")
        self._validate_data(record["kind"], record["data"])
        self._apply(record["kind"], record["data"])
        self._revision += 1
        self._bytes += len(raw)
        self._digest = sha256(raw).hexdigest()

    def _apply(self, kind, data):
        if kind == "checkpoint":
            self._checkpoints[data["checkpoint"]["id"]] = deepcopy(data)
        else:
            writes = self._writes.setdefault(data["checkpoint_id"], {})
            for entry in data["writes"]:
                writes[(data["task_id"], entry["index"])] = deepcopy(entry)

    def _append(self, kind, data):
        self._check_head()
        self._validate_data(kind, data)
        try:
            raw = canonical_json({"v": 1, "binding": self._binding,
                "previous_sha256": self._digest, "kind": kind, "data": data})
        except (TypeError, ValueError, RecursionError):
            raise CheckpointError("Checkpoint serialization limit or grammar violation") from None
        _require(len(raw) <= MAX_CHECKPOINT_BYTES and self._revision < self._max_records
                 and self._bytes + len(raw) <= self._max_bytes, "Checkpoint journal limit reached")
        attempt_id = self._bound_attempt(kind, data)
        try:
            row = self._ledger.write_checkpoint(str(uuid4()), self._run_id, NAMESPACE, raw,
                                                 expected_revision=self._revision,
                                                 attempt_id=attempt_id)
            _require(row["revision"] == self._revision + 1 and row["cursor"] == raw)
            self._consume(raw)
        except Exception:  # noqa: BLE001 - Uncertain commits must halt without leaking storage errors.
            self._halted = True
            raise CheckpointError("Checkpoint commit failed; saver halted") from None

    def _bound_attempt(self, kind, data):
        """The attempt a pending-writes row binds: exactly one `results` write naming
        exactly one execution the registry knows; every other row stays unbound
        (a guessed or partial binding would be a permanent integrity failure)."""

        if self._bindings is None or kind != "writes":
            return None
        results = [entry for entry in data["writes"] if entry["channel"] == "results"]
        if len(results) != 1 or type(results[0]["value"]) is not dict or len(results[0]["value"]) != 1:
            return None
        execution_id = next(iter(results[0]["value"]))
        return self._bindings.get(execution_id)

    def put(self, config, checkpoint, metadata, new_versions):
        with self._lock:
            parent = self._config_id(config)
            data = {"checkpoint": self._checkpoint(checkpoint), "metadata": self._metadata(metadata),
                    "parent": parent, "new_versions": self._versions(new_versions)}
            self._append("checkpoint", data)
            return self._config(checkpoint["id"])

    def put_writes(self, config, writes, task_id, task_path=""):
        with self._lock:
            checkpoint_id = self._config_id(config)
            _require(type(writes) in (list, tuple, deque) and len(writes) <= MAX_ENTRIES)
            entries = []
            for position, pair in enumerate(writes):
                _require(type(pair) in (list, tuple) and len(pair) == 2)
                channel, value = pair
                _require(type(channel) is str)
                value = self._pending_value(channel, value)
                entries.append({"index": WRITES_IDX_MAP.get(channel, position),
                                "channel": channel, "value": value})
            self._append("writes", {"checkpoint_id": checkpoint_id, "task_id": task_id,
                                     "task_path": task_path, "writes": entries})

    def _tuple(self, checkpoint_id):
        data = self._checkpoints[checkpoint_id]
        pending = [(task, entry["channel"],
                    self._pending_value(entry["channel"], entry["value"], decoding=True))
                   for (task, _), entry in self._writes.get(checkpoint_id, {}).items()]
        return CheckpointTuple(self._config(checkpoint_id),
            self._checkpoint(data["checkpoint"], decoding=True), deepcopy(data["metadata"]),
            None if data["parent"] is None else self._config(data["parent"]), pending)

    def get_tuple(self, config):
        with self._lock:
            checkpoint_id = self._config_id(config)
            self._check_head()
            if checkpoint_id is None:
                checkpoint_id = next(reversed(self._checkpoints), None)
            if checkpoint_id is None:
                return None
            _require(checkpoint_id in self._checkpoints, "Checkpoint ID is not in this journal")
            return self._tuple(checkpoint_id)

    def list(self, config, *, filter=None, before=None, limit=None):
        with self._lock:
            selected = None if config is None else self._config_id(config)
            before_id = None if before is None else self._config_id(before)
            _require(filter is None, "Metadata filters are unsupported")
            count = 100 if limit is None else _number(limit, 1, 1000)
            self._check_head()
            ids = [key for key in reversed(self._checkpoints)
                   if (selected is None or key == selected) and (before_id is None or key < before_id)]
            # Materialize inside the lock; caller mutation cannot modify the index.
            return iter([self._tuple(key) for key in ids[:count]])

    def get_next_version(self, current, channel):
        return 1 if current is None else _number(current, 0, MAX_INTEGER - 1) + 1

    def get_delta_channel_history(self, **kwargs):
        raise CheckpointError("Delta channels are unsupported")
