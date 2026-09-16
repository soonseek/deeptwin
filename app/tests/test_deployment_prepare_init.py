import errno
import importlib
import json
import os

import pytest

from app.tests.deployment_source_fixture import ActualSources, inputs
from app.tests.deployment_source_fixture import (
    actual_sources as actual_sources,  # noqa: PLC0414
)
from app.tests.test_deployment_publication import cancel, syscall_fixture


def initializer():
    try:
        return importlib.import_module("app.operations.deployment_prepare_init")
    except ModuleNotFoundError:
        assert False, "Fixed external initializer is missing"


def install_inputs(s):
    for logical in (s.c.RELEASE_ROOT.parent, s.c.RELEASE_ROOT.parent.parent):
        parent = s.actual(logical)
        parent.mkdir(parents=True, exist_ok=True)
        parent.chmod(0o755)
        s.register(parent, 0, 0)
    for logical, data, mode in [
        (s.c.INPUT_ROOT / "prepare-instance.json", s.instance_bytes, 0o440),
        (s.c.INPUT_ROOT / "prepare-source-pins.json", s.output.pins_bytes, 0o440),
        (s.c.RELEASE_ROOT / "deploy/compose.yaml", inputs()[0], 0o644),
        (s.c.RELEASE_ROOT / "deploy/security/service-ids.json", inputs()[1], 0o644),
        (
            s.c.RELEASE_ROOT / "deploy/security/deployment-prepare-recipe-v1.json",
            inputs()[2],
            0o644,
        ),
    ]:
        path = s.actual(logical)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(mode)
        s.register(path, 0, 0)
        parent = path.parent
        while parent.is_relative_to(
            s.actual(s.c.RELEASE_ROOT)
        ) or parent.is_relative_to(s.actual(s.c.INPUT_ROOT)):
            parent.chmod(0o750 if parent == s.actual(s.c.INPUT_ROOT) else 0o755)
            s.register(parent, 0, 0)
            parent = parent.parent
    s.mount_lines.append(
        f"200 999 {s.device} /release /opt/deeptwin ro - overlay overlay rw\n"
    )
    s.mount_lines.append(
        f"201 999 {s.device} /input /run/deeptwin/prepare-init-input ro - tmpfs tmpfs rw\n"
    )


def init_environment(s, monkeypatch):
    init = initializer()
    install_inputs(s)
    monkeypatch.setattr(os, "geteuid", lambda: 0)
    s.mount_lines = [
        line.replace(" ro -", " rw -") if index < 3 + s.slot_capacity else line
        for index, line in enumerate(s.mount_lines)
    ]
    syscall_fixture(monkeypatch)
    return init


def empty_root(s, logical):
    root = s.actual(logical)
    for entry in root.iterdir():
        if entry.is_dir():
            for child in entry.iterdir():
                child.unlink()
            entry.rmdir()
        else:
            entry.unlink()
    root.chmod(0o755)
    s.register(root, 0, 0)


def test_fixed_initializer_handles_real_empty_volumes(actual_sources, monkeypatch):
    s = actual_sources
    init = init_environment(s, monkeypatch)
    for root in (
        s.c.TOPOLOGY_ROOT,
        s.c.EXCHANGE_ROOT,
        s.c.OUTBOX_ROOT,
        s.c.IPC_ROOT / "xs01",
    ):
        empty_root(s, root)
    result = init.initialize_prepare_sources()
    assert result == {
        "topology_sha256": s.pins["topology_sha256"],
        "exchange_sha256": s.pins["exchange_sha256"],
    }
    assert (
        s.actual(s.c.TOPOLOGY_ROOT) / "topology.json"
    ).read_bytes() == s.output.topology_bytes
    assert (
        s.actual(s.c.EXCHANGE_ROOT) / "exchange.json"
    ).read_bytes() == s.output.exchange_bytes
    assert sorted(p.name for p in s.actual(s.c.OUTBOX_ROOT).iterdir()) == [
        "cancelled",
        "requests",
    ]
    assert (s.actual(s.c.IPC_ROOT / "xs01") / "boot-secret").stat().st_size == 32


def test_restart_preserves_valid_projection_and_sources(actual_sources, monkeypatch):
    s = actual_sources
    syscall_fixture(monkeypatch)
    data = cancel()
    with s.open_exchange() as source:
        source.publish(
            role="cancel",
            request_digest=data["request_digest"],
            payload=s.c.encode(data),
        )
    before = {
        p: (p.stat().st_ino, p.read_bytes())
        for p in s.actual(s.c.OUTBOX_ROOT / "cancelled").iterdir()
    }
    init = init_environment(s, monkeypatch)
    init.initialize_prepare_sources()
    assert before == {
        p: (p.stat().st_ino, p.read_bytes())
        for p in s.actual(s.c.OUTBOX_ROOT / "cancelled").iterdir()
    }


@pytest.mark.parametrize(
    "change",
    [
        "extra",
        "stage",
        "partial",
        "wrong_source",
        "wrong_pin",
        "input_mode",
        "input_symlink",
        "rw_alias",
    ],
)
def test_invalid_initializer_preflight_has_no_writes(
    actual_sources, monkeypatch, change
):
    s = actual_sources
    init = init_environment(s, monkeypatch)
    if change in {"extra", "stage"}:
        name = (
            ".stage-33333333-3333-4333-8333-333333333333.tmp"
            if change == "stage"
            else "extra"
        )
        (s.actual(s.c.TOPOLOGY_ROOT) / name).touch()
    elif change == "partial":
        (s.actual(s.c.OUTBOX_ROOT) / "requests").rmdir()
    elif change == "wrong_source":
        path = s.actual(s.c.EXCHANGE_ROOT / "exchange.json")
        path.chmod(0o640)
        path.write_bytes(b"{}")
        path.chmod(0o440)
    elif change == "wrong_pin":
        path = s.actual(s.c.INPUT_ROOT / "prepare-source-pins.json")
        path.chmod(0o640)
        value = json.loads(path.read_bytes())
        value["exchange_sha256"] = "a" * 64
        path.write_bytes(s.c.encode(value))
        path.chmod(0o440)
    elif change == "input_mode":
        s.actual(s.c.INPUT_ROOT / "prepare-instance.json").chmod(0o644)
    elif change == "input_symlink":
        path = s.actual(s.c.INPUT_ROOT / "prepare-instance.json")
        path.rename(path.with_name("other"))
        path.symlink_to(path.with_name("other"))
    else:
        s.mount_lines[2] = s.mount_lines[2].replace("/vol3", "/vol2")

    def forbidden(*args, **kwargs):
        raise AssertionError("preflight attempted mutation")

    monkeypatch.setattr(os, "fchown", forbidden)
    monkeypatch.setattr(os, "fchmod", forbidden)
    monkeypatch.setattr(os, "mkdir", forbidden)
    with pytest.raises(s.c.DeploymentSourceError):
        init.initialize_prepare_sources()


def test_main_enforces_platform_uid_and_no_arguments(actual_sources, monkeypatch):
    init = initializer()
    monkeypatch.setattr(os, "geteuid", lambda: 501)
    assert init.main() == 1
    with pytest.raises(TypeError):
        init.initialize_prepare_sources(path="/tmp")


@pytest.mark.parametrize(
    "change",
    [
        "empty_handed_off",
        "empty_0700",
        "rw_release",
        "release_mode",
        "slot_stage",
        "outbox_stage",
    ],
)
def test_strict_initializer_states_require_external_recovery(
    actual_sources, monkeypatch, change
):
    s = actual_sources
    init = init_environment(s, monkeypatch)
    if change in {"empty_handed_off", "empty_0700"}:
        empty_root(s, s.c.TOPOLOGY_ROOT)
        root = s.actual(s.c.TOPOLOGY_ROOT)
        if change == "empty_handed_off":
            s.register(root, 0, 20102)
            root.chmod(0o750)
        else:
            root.chmod(0o700)
    elif change == "rw_release":
        s.mount_lines = [
            line.replace(" ro -", " rw -") if "/opt/deeptwin" in line else line
            for line in s.mount_lines
        ]
    elif change == "release_mode":
        s.actual(s.c.RELEASE_ROOT / "deploy/compose.yaml").chmod(0o664)
    elif change == "slot_stage":
        (
            s.actual(s.c.IPC_ROOT / "xs01")
            / ".boot-secret.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.tmp"
        ).touch()
    else:
        path = (
            s.actual(s.c.OUTBOX_ROOT / "requests")
            / ".stage-33333333-3333-4333-8333-333333333333.tmp"
        )
        path.touch(mode=0o600)
        s.register(path, 20102, 20102)

    def forbidden(*args, **kwargs):
        raise AssertionError("must not repair invalid existing roots")

    monkeypatch.setattr(os, "fchown", forbidden)
    with pytest.raises(s.c.DeploymentSourceError):
        init.initialize_prepare_sources()


def test_initializer_never_opens_private_or_existing_state_roots(
    actual_sources, monkeypatch
):
    s = actual_sources
    init = init_environment(s, monkeypatch)
    original = s.f.open_directory
    seen = []

    def recording(path, **kwargs):
        seen.append(path)
        if path in s.c.BUILTIN_ROOTS:
            raise AssertionError("initializer opened old state")
        return original(path, **kwargs)

    monkeypatch.setattr(s.f, "open_directory", recording)
    assert init.main() == 0
    assert s.c.INPUT_ROOT in seen and s.c.TOPOLOGY_ROOT in seen


@pytest.mark.parametrize("target", ["release", "operator_input"])
def test_nested_rw_release_or_config_mount_denies_before_effects(
    actual_sources, monkeypatch, target
):
    s = actual_sources
    init = init_environment(s, monkeypatch)
    path = (
        s.c.RELEASE_ROOT / "deploy/compose.yaml"
        if target == "release"
        else s.c.INPUT_ROOT / "prepare-instance.json"
    )
    s.mount_lines.append(f"300 200 {s.device} /nested {path} rw - ext4 /dev/fake rw\n")

    def forbidden(*args, **kwargs):
        raise AssertionError("effect before input mount validation")

    monkeypatch.setattr(os, "fchown", forbidden)
    with pytest.raises(s.c.DeploymentSourceError):
        init.initialize_prepare_sources()


def enforce_rendered_endpoint_search(service, monkeypatch):
    """Low-level DAC fixture, not a real Linux capability-qualified execution."""
    uid, primary_gid = map(int, service["user"].split(":"))
    groups = {primary_gid, *map(int, service["group_add"])}
    assert service["cap_drop"] == ["ALL"]
    assert set(service["cap_add"]) == {"CHOWN", "FOWNER", "FSETID"}
    assert service["privileged"] is False
    monkeypatch.setattr(os, "geteuid", lambda: uid)
    observed_stat = os.stat
    searched, denied = set(), []

    def search_checked(name, *args, **kwargs):
        if (
            name in ("worker.sock", "listener.json")
            and kwargs.get("dir_fd") is not None
        ):
            info = os.fstat(kwargs["dir_fd"])
            bit = (
                0o100
                if uid == info.st_uid
                else 0o010
                if info.st_gid in groups
                else 0o001
            )
            if not info.st_mode & bit:
                denied.append((name, info.st_uid, info.st_gid, info.st_mode & 0o7777))
                raise PermissionError(errno.EACCES, "controlled DAC search denial")
            searched.add((name, info.st_gid))
        return observed_stat(name, *args, **kwargs)

    monkeypatch.setattr(os, "stat", search_checked)
    return searched, denied


@pytest.mark.parametrize("capacity", [1, 16])
def test_emitted_credentials_restart_every_existing_slot(
    tmp_path, monkeypatch, capacity
):
    s = ActualSources(tmp_path, monkeypatch, capacity=capacity)
    init = init_environment(s, monkeypatch)
    service = json.loads(s.output.expanded_compose_bytes)["services"][
        "deployment-prepare-root-init"
    ]
    searched, denied = enforce_rendered_endpoint_search(service, monkeypatch)
    result = init.initialize_prepare_sources()
    assert result == {
        "topology_sha256": s.pins["topology_sha256"],
        "exchange_sha256": s.pins["exchange_sha256"],
    }
    assert denied == []
    assert searched == {
        (name, 23000 + number)
        for number in range(1, capacity + 1)
        for name in ("worker.sock", "listener.json")
    }
    for number in range(1, capacity + 1):
        endpoint = s.actual(s.c.IPC_ROOT / f"xs{number:02}" / "endpoint")
        info = endpoint.stat()
        assert (info.st_uid, info.st_gid, info.st_mode & 0o7777) == (
            22000 + number,
            23000 + number,
            0o2710,
        )


@pytest.mark.parametrize("capacity", [1, 16])
def test_missing_final_slot_group_denies_restart_before_effects(
    tmp_path, monkeypatch, capacity
):
    s = ActualSources(tmp_path, monkeypatch, capacity=capacity)
    init = init_environment(s, monkeypatch)
    service = json.loads(s.output.expanded_compose_bytes)["services"][
        "deployment-prepare-root-init"
    ]
    service["group_add"] = [
        group for group in service["group_add"] if group != str(23000 + capacity)
    ]
    searched, denied = enforce_rendered_endpoint_search(service, monkeypatch)

    def forbidden(*args, **kwargs):
        raise AssertionError("denied restart attempted a mutation")

    monkeypatch.setattr(os, "fchown", forbidden)
    with pytest.raises(s.c.DeploymentSourceError, match="^deployment_source_invalid$"):
        init.initialize_prepare_sources()
    assert denied == [("worker.sock", 22000 + capacity, 23000 + capacity, 0o2710)]
    assert searched == {
        (name, 23000 + number)
        for number in range(1, capacity)
        for name in ("worker.sock", "listener.json")
    }
