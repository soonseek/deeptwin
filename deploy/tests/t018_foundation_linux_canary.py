"""Linux/root canary for the T018-F1 two-level IPC endpoint lifecycle.

This is intentionally not collected by pytest.  It must run as root in the
candidate Linux service environment so every service pair uses its fixed
numeric UID/GID and the real SO_PEERCRED plus /proc/self/fd path.
"""

from __future__ import annotations

import argparse
import json
import os
import select
import socket
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from app.workers import broker, ipc_root, listener

EXPECTED_PAIRS = (
    "browser-fetch",
    "cp-backup",
    "cp-browser",
    "cp-codex",
    "cp-document",
    "cp-evaluation",
    "cp-fetch",
    "cp-provider",
    "cp-runtime",
    "cp-speech",
)
EXPECTED_SERVICE_IDS = {
    "backup": 20_111,
    "browser": 20_105,
    "codex": 20_110,
    "control": 20_102,
    "document": 20_106,
    "edge-local": 20_101,
    "edge-portable": 20_112,
    "evaluation": 20_108,
    "fetch": 20_104,
    "provider": 20_103,
    "runtime-extension": 20_109,
    "speech": 20_107,
}
EXPECTED_PAIR_GIDS = {
    "browser-fetch": 21_110,
    "cp-backup": 21_109,
    "cp-browser": 21_104,
    "cp-codex": 21_103,
    "cp-document": 21_105,
    "cp-evaluation": 21_107,
    "cp-fetch": 21_102,
    "cp-provider": 21_101,
    "cp-runtime": 21_108,
    "cp-speech": 21_106,
}
EXPECTED_PAIR_SERVICES = {
    "browser-fetch": ("browser", "fetch"),
    "cp-backup": ("control", "backup"),
    "cp-browser": ("control", "browser"),
    "cp-codex": ("control", "codex"),
    "cp-document": ("control", "document"),
    "cp-evaluation": ("control", "evaluation"),
    "cp-fetch": ("control", "fetch"),
    "cp-provider": ("control", "provider"),
    "cp-runtime": ("control", "runtime-extension"),
    "cp-speech": ("control", "speech"),
}
PAIR_FIELDS = {
    "boot_secret",
    "boot_secret_bytes",
    "boot_secret_gid",
    "boot_secret_mode",
    "boot_secret_policy",
    "boot_secret_uid",
    "endpoint",
    "endpoint_gid",
    "endpoint_mode",
    "endpoint_uid",
    "generation_lock",
    "generation_lock_gid",
    "generation_lock_mode",
    "generation_lock_uid",
    "pair_gid",
    "requester",
    "responder",
    "root",
    "root_gid",
    "root_mode",
    "root_uid",
    "socket",
    "socket_gid",
    "socket_mode",
    "socket_uid",
}
_CHILD_TIMEOUT_SECONDS = 10.0


class CanaryFailure(RuntimeError):
    pass


def _require_exact_int(value: object) -> int:
    if type(value) is not int or not 1 <= value < (1 << 32):
        raise CanaryFailure("service identity manifest is invalid")
    return value


def _strict_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CanaryFailure("service identity manifest is invalid")
        result[key] = value
    return result


def _reject_json_number(_value: str) -> None:
    raise CanaryFailure("service identity manifest is invalid")


def _load_identities(
    path: Path,
) -> tuple[dict[str, dict[str, object]], dict[str, dict[str, object]]]:
    try:
        value = json.loads(
            path.read_bytes().decode("utf-8", errors="strict"),
            object_pairs_hook=_strict_object,
            parse_float=_reject_json_number,
            parse_constant=_reject_json_number,
        )
        if type(value) is not dict or set(value) != {
            "schema_version",
            "status",
            "scope",
            "services",
            "pairs",
            "limitations",
        }:
            raise CanaryFailure("service identity manifest is invalid")
        if (
            value["schema_version"] != "deeptwin-static-service-identity-v1"
            or value["status"] != "candidate_not_runtime_qualified"
            or value["scope"] != "ipc_network_isolation_skeleton"
            or type(value["limitations"]) is not list
            or not value["limitations"]
            or any(type(item) is not str or not item for item in value["limitations"])
        ):
            raise CanaryFailure("service identity manifest is invalid")
        services = value["services"]
        pairs = value["pairs"]
    except CanaryFailure:
        raise
    except (
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
    ):
        raise CanaryFailure("service identity manifest is invalid") from None
    if type(services) is not dict or type(pairs) is not dict:
        raise CanaryFailure("service identity manifest is invalid")
    if tuple(sorted(pairs)) != EXPECTED_PAIRS:
        raise CanaryFailure("exact ten service pairs are required")
    if not set(EXPECTED_SERVICE_IDS) < set(services) or set(services) != {
        *EXPECTED_SERVICE_IDS,
        "ipc-root-init",
        "state-root-init",
    }:
        raise CanaryFailure("service identity manifest is invalid")
    runtime_uids: set[int] = set()
    runtime_gids: set[int] = set()
    for name, expected_id in EXPECTED_SERVICE_IDS.items():
        service = services[name]
        if type(service) is not dict or set(service) != {"uid", "gid", "lifecycle"}:
            raise CanaryFailure("service identity manifest is invalid")
        if (
            service["uid"] != expected_id
            or service["gid"] != expected_id
            or service["lifecycle"] != "long_running"
        ):
            raise CanaryFailure("service identity manifest is invalid")
        runtime_uids.add(_require_exact_int(service["uid"]))
        runtime_gids.add(_require_exact_int(service["gid"]))
    if len(runtime_uids) != len(EXPECTED_SERVICE_IDS) or len(runtime_gids) != len(
        EXPECTED_SERVICE_IDS
    ):
        raise CanaryFailure("service identity manifest is invalid")
    ipc_initializer = services["ipc-root-init"]
    if (
        type(ipc_initializer) is not dict
        or set(ipc_initializer) != {"uid", "gid", "lifecycle", "capabilities"}
        or ipc_initializer
        != {
            "uid": 0,
            "gid": 0,
            "lifecycle": "one_shot",
            "capabilities": ["CHOWN", "FOWNER", "FSETID"],
        }
    ):
        raise CanaryFailure("service identity manifest is invalid")
    pair_gids: set[int] = set()
    socket_paths: set[str] = set()
    for name in EXPECTED_PAIRS:
        pair = pairs[name]
        if type(pair) is not dict or set(pair) != PAIR_FIELDS:
            raise CanaryFailure("service identity manifest is invalid")
        requester = pair["requester"]
        responder = pair["responder"]
        if (
            type(requester) is not str
            or type(responder) is not str
            or requester not in EXPECTED_SERVICE_IDS
            or responder not in EXPECTED_SERVICE_IDS
            or requester == responder
            or (requester, responder) != EXPECTED_PAIR_SERVICES[name]
        ):
            raise CanaryFailure("service identity manifest is invalid")
        pair_gid = _require_exact_int(pair["pair_gid"])
        responder_id = EXPECTED_SERVICE_IDS[responder]
        expected_root = f"/run/deeptwin/ipc/{name}"
        expected = {
            "boot_secret": "boot-secret",
            "boot_secret_bytes": 32,
            "boot_secret_gid": pair_gid,
            "boot_secret_mode": "0640",
            "boot_secret_policy": "generate_or_overwrite_per_boot",
            "boot_secret_uid": 0,
            "endpoint": "endpoint",
            "endpoint_gid": pair_gid,
            "endpoint_mode": "02710",
            "endpoint_uid": responder_id,
            "generation_lock": "generation.lock",
            "generation_lock_gid": pair_gid,
            "generation_lock_mode": "0640",
            "generation_lock_uid": 0,
            "pair_gid": EXPECTED_PAIR_GIDS[name],
            "requester": requester,
            "responder": responder,
            "root": expected_root,
            "root_gid": pair_gid,
            "root_mode": "0710",
            "root_uid": 0,
            "socket": "worker.sock",
            "socket_gid": pair_gid,
            "socket_mode": "0660",
            "socket_uid": responder_id,
        }
        if pair != expected:
            raise CanaryFailure("service identity manifest is invalid")
        pair_gids.add(pair_gid)
        socket_paths.add(f"{expected_root}/endpoint/worker.sock")
    if (
        len(pair_gids) != len(EXPECTED_PAIRS)
        or len(socket_paths) != len(EXPECTED_PAIRS)
        or pair_gids & runtime_uids
        or pair_gids & runtime_gids
    ):
        raise CanaryFailure("service identity manifest is invalid")
    return services, pairs


def _pair_contract(
    name: str,
    services: dict[str, dict[str, object]],
    pairs: dict[str, dict[str, object]],
) -> tuple[ipc_root.PairRootSpec, broker.ChannelSpec]:
    pair = pairs[name]
    if type(pair) is not dict or {"requester", "responder", "pair_gid"} - set(pair):
        raise CanaryFailure("service identity manifest is invalid")
    requester_name = pair["requester"]
    responder_name = pair["responder"]
    if type(requester_name) is not str or type(responder_name) is not str:
        raise CanaryFailure("service identity manifest is invalid")
    try:
        requester = services[requester_name]
        responder = services[responder_name]
        requester_uid = _require_exact_int(requester["uid"])
        requester_gid = _require_exact_int(requester["gid"])
        responder_uid = _require_exact_int(responder["uid"])
        responder_gid = _require_exact_int(responder["gid"])
        pair_gid = _require_exact_int(pair["pair_gid"])
    except (KeyError, TypeError):
        raise CanaryFailure("service identity manifest is invalid") from None
    pair_root = ipc_root.PairRootSpec(
        pair_root=Path(pair["root"]),
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
    )
    channel = broker.ChannelSpec(
        channel_id=name,
        requester_service=requester_name,
        responder_service=responder_name,
        request_direction=f"{requester_name}-to-{responder_name}",
        protocol_id="foundation-canary-v1",
        requester_uid=requester_uid,
        requester_gid=requester_gid,
        responder_uid=responder_uid,
        responder_gid=responder_gid,
        pair_gid=pair_gid,
        pair_root=pair_root.endpoint_path,
        socket_name="worker.sock",
        root_uid=responder_uid,
        root_gid=pair_gid,
        socket_uid=responder_uid,
        socket_gid=pair_gid,
        requester_message_types=("execute",),
        responder_message_types=("result",),
        max_queue_depth=2,
        max_operation_ms=5_000,
    )
    return pair_root, channel


def _drop_identity(uid: int, gid: int, pair_gid: int) -> None:
    os.setgroups([pair_gid])
    os.setgid(gid)
    os.setuid(uid)
    if (
        os.geteuid() != uid
        or os.getegid() != gid
        or frozenset(os.getgroups()) != frozenset({pair_gid})
    ):
        raise CanaryFailure("child identity transition failed")


def _assert_generation_layout(
    root: ipc_root.PairRootSpec,
    initialized: ipc_root.InitializedGeneration,
) -> bytes:
    """Independently inspect the mounted, dirfd-anchored generation metadata."""

    with ipc_root.acquire_generation(root) as generation:
        if generation.generation_id != initialized.generation_id:
            raise CanaryFailure("generation identity mismatch")
        try:
            parent_info = os.fstat(generation.pair_fd)
            endpoint_info = os.fstat(generation.endpoint_fd)
            secret_info = os.stat(
                ipc_root.BOOT_SECRET_NAME,
                dir_fd=generation.pair_fd,
                follow_symlinks=False,
            )
            lock_info = os.stat(
                ipc_root.GENERATION_LOCK_NAME,
                dir_fd=generation.pair_fd,
                follow_symlinks=False,
            )
            listing_fd = os.open(
                ".",
                os.O_RDONLY | os.O_CLOEXEC | os.O_DIRECTORY | os.O_NOFOLLOW,
                dir_fd=generation.pair_fd,
            )
            try:
                entries = set(os.listdir(listing_fd))
            finally:
                os.close(listing_fd)
        except OSError:
            raise CanaryFailure("generation metadata inspection failed") from None
        if entries != {
            ipc_root.BOOT_SECRET_NAME,
            ipc_root.ENDPOINT_NAME,
            ipc_root.GENERATION_LOCK_NAME,
        }:
            raise CanaryFailure("generation metadata contains unexpected entries")
        if (
            not stat.S_ISDIR(parent_info.st_mode)
            or (
                parent_info.st_uid,
                parent_info.st_gid,
                stat.S_IMODE(parent_info.st_mode),
            )
            != (0, root.pair_gid, ipc_root.PAIR_ROOT_MODE)
            or not stat.S_ISDIR(endpoint_info.st_mode)
            or (
                endpoint_info.st_uid,
                endpoint_info.st_gid,
                stat.S_IMODE(endpoint_info.st_mode),
            )
            != (root.responder_uid, root.pair_gid, ipc_root.ENDPOINT_MODE)
        ):
            raise CanaryFailure("generation directory identity mismatch")
        for info in (secret_info, lock_info):
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
                != (0, root.pair_gid, ipc_root.PAIR_METADATA_MODE)
            ):
                raise CanaryFailure("generation metadata identity mismatch")
        if secret_info.st_size != broker.AUTH_SECRET_BYTES or lock_info.st_size != 0:
            raise CanaryFailure("generation metadata size mismatch")
        return generation.secret._material()


def _assert_live_endpoint(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    worker: listener.WorkerListener,
) -> None:
    """Check the actual responder-owned names and inode identities before use."""

    try:
        entries = set(os.listdir(worker._endpoint_fd))
        socket_info = os.stat(
            spec.socket_name,
            dir_fd=worker._endpoint_fd,
            follow_symlinks=False,
        )
        readiness_info = os.stat(
            ipc_root.LISTENER_NAME,
            dir_fd=worker._endpoint_fd,
            follow_symlinks=False,
        )
        lock_info = os.stat(
            ipc_root.LISTENER_LOCK_NAME,
            dir_fd=worker._endpoint_fd,
            follow_symlinks=False,
        )
    except OSError:
        raise CanaryFailure("live endpoint inspection failed") from None
    if entries != {
        ipc_root.LISTENER_LOCK_NAME,
        ipc_root.LISTENER_NAME,
        spec.socket_name,
    }:
        raise CanaryFailure("live endpoint contains unexpected entries")
    if (
        not stat.S_ISSOCK(socket_info.st_mode)
        or socket_info.st_nlink != 1
        or (
            socket_info.st_uid,
            socket_info.st_gid,
            stat.S_IMODE(socket_info.st_mode),
        )
        != (root.responder_uid, root.pair_gid, spec.socket_mode)
        or listener.SocketIdentity.from_stat(spec.socket_name, socket_info)
        != worker.record.socket
    ):
        raise CanaryFailure("live socket identity mismatch")
    if (
        not stat.S_ISREG(readiness_info.st_mode)
        or readiness_info.st_nlink != 1
        or (
            readiness_info.st_uid,
            readiness_info.st_gid,
            stat.S_IMODE(readiness_info.st_mode),
        )
        != (root.responder_uid, root.pair_gid, listener.LISTENER_FILE_MODE)
        or not stat.S_ISREG(lock_info.st_mode)
        or lock_info.st_nlink != 1
        or (lock_info.st_uid, lock_info.st_gid, stat.S_IMODE(lock_info.st_mode))
        != (root.responder_uid, root.pair_gid, listener.LISTENER_LOCK_MODE)
    ):
        raise CanaryFailure("live readiness identity mismatch")


def _child_exit(callback: Callable[[], None], status_fd: int) -> NoReturn:
    try:
        callback()
        os.write(status_fd, b"ok")
        code = 0
    except Exception as error:  # noqa: BLE001 - report any child probe failure.
        message = getattr(error, "code", type(error).__name__)
        os.write(status_fd, f"fail:{message}".encode("ascii", errors="replace"))
        code = 1
    finally:
        os.close(status_fd)
    os._exit(code)


def _wait_child(pid: int, status_fd: int, label: str) -> None:
    readable, _writable, _exceptional = select.select(
        [status_fd],
        [],
        [],
        _CHILD_TIMEOUT_SECONDS,
    )
    if not readable:
        try:
            os.kill(pid, 9)
        except ProcessLookupError:
            pass
        os.waitpid(pid, 0)
        raise CanaryFailure(f"{label}: child timeout")
    status = os.read(status_fd, 256)
    os.close(status_fd)
    waited, wait_status = os.waitpid(pid, 0)
    if (
        waited != pid
        or not os.WIFEXITED(wait_status)
        or os.WEXITSTATUS(wait_status) != 0
    ):
        detail = status.decode("ascii", errors="replace")
        raise CanaryFailure(f"{label}: {detail}")


def _spawn(callback: Callable[[], None]) -> tuple[int, int]:
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        _child_exit(callback, write_fd)
    os.close(write_fd)
    return pid, read_fd


def _serve(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    requester_boot_id: str,
    responder_boot_id: str,
    ready_fd: int,
    expected_failure: type[broker.BrokerError] | None = None,
) -> None:
    _drop_identity(spec.responder_uid, spec.responder_gid, spec.pair_gid)
    worker = listener.bind_worker_listener(
        root,
        spec,
        responder_boot_id=responder_boot_id,
    )
    try:
        _assert_live_endpoint(root, spec, worker)
        os.write(ready_fd, b"ready")
        os.close(ready_fd)
        try:
            connection = worker.accept_authenticated(
                requester_boot_id=requester_boot_id,
                deadline=broker.Deadline.after_ms(5_000),
            )
        except broker.BrokerError as error:
            if expected_failure is None or type(error) is not expected_failure:
                raise
            return
        if expected_failure is not None:
            connection.close()
            raise CanaryFailure(
                "unauthenticated connection reached application framing"
            )
        worker.close()
        with connection:
            received = connection.read(deadline=broker.Deadline.after_ms(5_000))
            if (
                received.payload != b"probe"
                or received.envelope.message_type != "execute"
            ):
                raise CanaryFailure("request frame mismatch")
            connection.write(
                message_id=str(uuid4()),
                correlation_id=received.envelope.message_id,
                message_type="result",
                payload=b"ok",
                deadline=broker.Deadline.after_ms(5_000),
            )
    finally:
        if not worker.closed:
            worker.close()


def _request(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    requester_boot_id: str,
) -> None:
    _drop_identity(spec.requester_uid, spec.requester_gid, spec.pair_gid)
    with listener.connect_authenticated(
        root,
        spec,
        requester_boot_id=requester_boot_id,
        deadline=broker.Deadline.after_ms(5_000),
    ) as connection:
        request_id = str(uuid4())
        connection.write(
            message_id=request_id,
            correlation_id=None,
            message_type="execute",
            payload=b"probe",
            deadline=broker.Deadline.after_ms(5_000),
        )
        received = connection.read(deadline=broker.Deadline.after_ms(5_000))
        if (
            received.payload != b"ok"
            or received.envelope.message_type != "result"
            or received.envelope.correlation_id != request_id
        ):
            raise CanaryFailure("response frame mismatch")


def _stale_request(
    spec: broker.ChannelSpec,
    *,
    old_secret: bytes,
    requester_boot_id: str,
    responder_boot_id: str,
) -> None:
    _drop_identity(spec.requester_uid, spec.requester_gid, spec.pair_gid)
    connection, _identity, _peer = broker.connect_verified(
        spec,
        local_service=spec.requester_service,
        deadline=broker.Deadline.after_ms(5_000),
    )
    try:
        broker.client_handshake(
            connection,
            spec,
            broker.BootSecret(old_secret),
            requester_boot_id=requester_boot_id,
            responder_boot_id=responder_boot_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
    except broker.BrokerError:
        return
    finally:
        connection.close()
    raise CanaryFailure("old generation authenticated")


def _wrong_peer_request(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    wrong_uid: int,
    wrong_gid: int,
    requester_boot_id: str,
) -> None:
    _drop_identity(wrong_uid, wrong_gid, spec.pair_gid)
    try:
        listener.connect_authenticated(
            root,
            spec,
            requester_boot_id=requester_boot_id,
            deadline=broker.Deadline.after_ms(5_000),
        )
    except broker.BrokerError:
        return
    raise CanaryFailure("wrong primary peer authenticated")


def _exchange(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    suffix: str,
) -> None:
    requester_boot = f"{spec.requester_service}-boot-{suffix}"
    responder_boot = f"{spec.responder_service}-boot-{suffix}"
    ready_read, ready_write = os.pipe2(os.O_CLOEXEC)
    server_pid, server_status = _spawn(
        lambda: _serve(
            root,
            spec,
            requester_boot_id=requester_boot,
            responder_boot_id=responder_boot,
            ready_fd=ready_write,
        )
    )
    os.close(ready_write)
    readable, _writable, _exceptional = select.select(
        [ready_read],
        [],
        [],
        _CHILD_TIMEOUT_SECONDS,
    )
    if not readable or os.read(ready_read, 5) != b"ready":
        raise CanaryFailure("listener readiness timeout")
    os.close(ready_read)
    client_pid, client_status = _spawn(
        lambda: _request(
            root,
            spec,
            requester_boot_id=requester_boot,
        )
    )
    _wait_child(client_pid, client_status, f"{spec.channel_id}: requester")
    _wait_child(server_pid, server_status, f"{spec.channel_id}: responder")


def _rejected_exchange(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    *,
    suffix: str,
    expected_server_failure: type[broker.BrokerError],
    request: Callable[[], None],
) -> None:
    requester_boot = f"{spec.requester_service}-boot-{suffix}"
    responder_boot = f"{spec.responder_service}-boot-{suffix}"
    ready_read, ready_write = os.pipe2(os.O_CLOEXEC)
    server_pid, server_status = _spawn(
        lambda: _serve(
            root,
            spec,
            requester_boot_id=requester_boot,
            responder_boot_id=responder_boot,
            ready_fd=ready_write,
            expected_failure=expected_server_failure,
        )
    )
    os.close(ready_write)
    readable, _writable, _exceptional = select.select(
        [ready_read],
        [],
        [],
        _CHILD_TIMEOUT_SECONDS,
    )
    if not readable or os.read(ready_read, 5) != b"ready":
        raise CanaryFailure("listener readiness timeout")
    os.close(ready_read)
    client_pid, client_status = _spawn(request)
    _wait_child(client_pid, client_status, f"{spec.channel_id}: rejected requester")
    _wait_child(server_pid, server_status, f"{spec.channel_id}: rejecting responder")


def _qualify_pair(root: ipc_root.PairRootSpec, spec: broker.ChannelSpec) -> None:
    first = ipc_root.initialize_pair_root(root)
    old_secret = _assert_generation_layout(root, first)
    _exchange(root, spec, suffix="g1")

    second = ipc_root.initialize_pair_root(root)
    if second.generation_id == first.generation_id:
        raise CanaryFailure("restart did not rotate the generation")
    if _assert_generation_layout(root, second) == old_secret:
        raise CanaryFailure("restart repeated the boot secret")
    _exchange(root, spec, suffix="g2")

    requester_boot = f"{spec.requester_service}-boot-stale"
    responder_boot = f"{spec.responder_service}-boot-stale"
    _rejected_exchange(
        root,
        spec,
        suffix="stale",
        expected_server_failure=broker.AuthenticationError,
        request=lambda: _stale_request(
            spec,
            old_secret=old_secret,
            requester_boot_id=requester_boot,
            responder_boot_id=responder_boot,
        ),
    )


def _qualify_wrong_primary_peer(
    root: ipc_root.PairRootSpec,
    spec: broker.ChannelSpec,
    services: dict[str, dict[str, object]],
) -> None:
    candidates = [
        value
        for value in services.values()
        if type(value) is dict
        and value.get("uid") not in {spec.requester_uid, spec.responder_uid, 0}
    ]
    if not candidates:
        raise CanaryFailure("wrong-peer identity is unavailable")
    wrong_uid = _require_exact_int(candidates[0]["uid"])
    wrong_gid = _require_exact_int(candidates[0]["gid"])
    requester_boot = f"{spec.requester_service}-boot-wrong"
    _rejected_exchange(
        root,
        spec,
        suffix="wrong",
        expected_server_failure=broker.PeerCredentialError,
        request=lambda: _wrong_peer_request(
            root,
            spec,
            wrong_uid=wrong_uid,
            wrong_gid=wrong_gid,
            requester_boot_id=requester_boot,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--service-ids",
        type=Path,
        default=REPOSITORY_ROOT / "deploy/security/service-ids.json",
    )
    args = parser.parse_args()
    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        parser.exit(1, "FAIL: native Linux SO_PEERCRED is required\n")
    if os.geteuid() != 0 or not Path("/proc/self/fd").is_dir():
        parser.exit(1, "FAIL: root plus /proc/self/fd is required\n")

    try:
        services, pairs = _load_identities(args.service_ids)
        contracts = [_pair_contract(name, services, pairs) for name in EXPECTED_PAIRS]
        for root, spec in contracts:
            _qualify_pair(root, spec)
        _qualify_wrong_primary_peer(*contracts[0], services)
        for root, _spec in contracts:
            pair_info = root.pair_root.lstat()
            endpoint_info = root.endpoint_path.lstat()
            if (
                pair_info.st_uid,
                pair_info.st_gid,
                stat.S_IMODE(pair_info.st_mode),
            ) != (0, root.pair_gid, ipc_root.PAIR_ROOT_MODE) or (
                endpoint_info.st_uid,
                endpoint_info.st_gid,
                stat.S_IMODE(endpoint_info.st_mode),
            ) != (root.responder_uid, root.pair_gid, ipc_root.ENDPOINT_MODE):
                raise CanaryFailure("post-restart filesystem identity drift")
        print(
            json.dumps(
                {
                    "generation_rotations": len(contracts),
                    "old_generation_application_frames": 0,
                    "pairs": len(contracts),
                    "peer_credential_path": "SO_PEERCRED",
                    "socket_anchor": "/proc/self/fd",
                    "status": "PASS",
                    "wrong_primary_peer_application_frames": 0,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 0
    except CanaryFailure as error:
        parser.exit(1, f"FAIL: {error}\n")
    except (broker.BrokerError, ipc_root.IpcRootError, listener.ListenerError, OSError):
        parser.exit(1, "FAIL: worker foundation qualification failed\n")


if __name__ == "__main__":
    raise SystemExit(main())
