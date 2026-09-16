"""Dependency, startup snapshot and resource ownership at the real common seam."""

from dataclasses import replace
from pathlib import Path
from types import MappingProxyType

import pytest
from fastapi import FastAPI

from app.api import first_party as fp
from app.api.router_composition import RouteCompositionError
from app.tests.test_first_party import shared_context as context_fixture
from app.tests.test_router_composition import descriptor, router_for, write_descriptor

shared_context = context_fixture


def test_startup_reconcile_requires_a_direct_installed_function():
    class CallableHook:
        def __call__(self, exports):
            return None

    with pytest.raises(TypeError):
        fp.InstalledContribution(
            "example-v1.json",
            "app.api.example:create_router",
            lambda context: None,
            ("browser_session",),
            ("work.read",),
            startup_reconcile=CallableHook(),
        )


def test_ambient_snapshot_does_not_enumerate_and_reads_each_declared_key_once(
    monkeypatch, tmp_path
):
    from app.api.first_party_catalog import INSTALLED

    keys = tuple(key for entry in INSTALLED for key in entry.startup_keys)
    read = []

    class Environment:
        def __getitem__(self, key):
            assert key in keys
            read.append(key)
            return "a" * 64

        def __iter__(self):
            pytest.fail("Startup copied the ambient environment")

    with monkeypatch.context() as environment:
        environment.setattr(fp.os, "environ", Environment())
        inputs = fp.build_startup_inputs(values=None, protected_roots=(tmp_path,))
    assert read == list(keys)
    assert tuple(inputs.values) == keys


class Resource:
    def __init__(self, name, closed, fail=False):
        self.name, self.closed, self.fail = name, closed, fail

    def close(self):
        self.closed.append(self.name)
        if self.fail:
            raise RuntimeError("private cleanup text")


def catalog(tmp_path, first, second, **kwargs):
    root = tmp_path / "descriptors"
    root.mkdir()
    write_descriptor(root, "example-v1.json", descriptor())
    write_descriptor(
        root,
        "other-v1.json",
        descriptor(
            contribution_id="other-v1",
            factory="app.api.other:create_router",
            route_id="other.get",
            path="/api/v1/other",
        ),
    )
    assert "provides" in fp.InstalledContribution.__dataclass_fields__, (
        "Missing declared dependency seam"
    )
    return root, (
        fp.InstalledContribution(
            "example-v1.json",
            "app.api.example:create_router",
            first,
            ("browser_session",),
            ("work.read",),
            provides=("example.service",),
            **kwargs,
        ),
        fp.InstalledContribution(
            "other-v1.json",
            "app.api.other:create_router",
            second,
            ("browser_session",),
            ("work.read",),
            requires=("example.service",),
            provides=("other.service",),
        ),
    )


def test_malformed_resource_container_fails_while_factory_owns_actual_file(
    tmp_path, shared_context
):
    import io
    from contextlib import ExitStack

    acquired = []

    class OwnedFile(io.FileIO):
        closes = 0

        def close(self):
            self.closes += 1
            super().close()

    def first(context):
        with ExitStack() as stack:
            resource = OwnedFile(tmp_path / "owned-resource", "w+b")
            acquired.append(resource)
            stack.callback(resource.close)
            services = fp.ContributionServices(
                router_for(),
                {"example.service": resource},
                owned_resources=[resource],
            )
            stack.pop_all()
            return services

    def forbidden(context, *, dependencies):
        pytest.fail("Malformed resource ownership reached a later factory")

    root, entries = catalog(tmp_path, first, forbidden)
    try:
        with pytest.raises(RouteCompositionError):
            fp.FirstPartyApplicationComposer(
                context=shared_context, descriptor_root=root, installed=entries
            ).compose(FastAPI())
        assert len(acquired) == 1
        assert acquired[0].closed, "Factory relinquished an unclosed actual file"
        assert acquired[0].closes == 1
    finally:
        # Keep a RED run from itself leaking the acquired OS handle.
        for resource in acquired:
            if not resource.closed:
                io.FileIO.close(resource)


def test_exact_dependencies_activation_and_reverse_single_cleanup(
    tmp_path, shared_context
):
    closed, calls, activated = [], [], []
    a, b = Resource("a", closed), Resource("b", closed)

    def first(context):
        calls.append(context)
        return fp.ContributionServices(
            router_for(), {"example.service": a}, owned_resources=(a,)
        )

    def second(context, *, dependencies):
        calls.append(context)
        assert type(dependencies) is MappingProxyType
        assert dict(dependencies) == {"example.service": a}
        return fp.ContributionServices(
            router_for("/api/v1/other"), {"other.service": b}, owned_resources=(b,)
        )

    def activate(exports):
        assert type(exports) is MappingProxyType
        assert dict(exports) == {"example.service": a}
        activated.append(a)

    root, entries = catalog(tmp_path, first, second, startup_reconcile=activate)
    publication = fp.FirstPartyApplicationComposer(
        context=shared_context, descriptor_root=root, installed=entries
    ).compose(FastAPI())
    assert calls == [shared_context, shared_context] and calls[0] is calls[1]
    assert not activated and not closed
    publication.activate_startup()
    assert activated == [a]
    with pytest.raises(RouteCompositionError):
        publication.activate_startup()
    publication.close()
    publication.close()
    assert closed == ["b", "a"]
    with pytest.raises(RouteCompositionError):
        publication.activate_startup()


@pytest.mark.parametrize(
    "fault",
    ["forward", "duplicate", "repeat", "bad-name", "too-many", "bad-key", "keys-total"],
)
def test_catalog_validation_precedes_factories(tmp_path, shared_context, fault):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid catalog invoked a factory")

    root, entries = catalog(tmp_path, forbidden, forbidden)
    changes = {
        "forward": {"requires": ("other.service",)},
        "duplicate": {"provides": ("other.service",)},
        "repeat": {"provides": ("example.service", "example.service")},
        "bad-name": {"provides": ("EXAMPLE",)},
        "too-many": {"provides": tuple(f"name{i}" for i in range(65))},
        "bad-key": {"startup_keys": ("secret.path",)},
        "keys-total": {"startup_keys": tuple(f"PIN_{i}" for i in range(64))},
    }[fault]
    with pytest.raises((RouteCompositionError, TypeError, ValueError)):
        entries = (replace(entries[0], **changes), entries[1])
        if fault == "keys-total":
            entries = (entries[0], replace(entries[1], startup_keys=("EXTRA",)))
        fp.FirstPartyApplicationComposer(
            context=shared_context, descriptor_root=root, installed=entries
        ).compose(FastAPI())


@pytest.mark.parametrize(
    "fault",
    [
        "exports",
        "router",
        "later-factory",
        "inclusion",
        "duplicate-within",
        "duplicate-across",
    ],
)
def test_resources_adopted_before_validation_and_failures_do_not_mask_original(
    tmp_path, shared_context, fault
):
    closed = []
    a, b = Resource("a", closed, fail=True), Resource("b", closed)

    def first(context):
        return fp.ContributionServices(
            router_for(),
            {"wrong" if fault == "exports" else "example.service": a},
            owned_resources=(a, a) if fault == "duplicate-within" else (a,),
        )

    def second(context, *, dependencies):
        if fault == "later-factory":
            raise RuntimeError("private factory text")
        return fp.ContributionServices(
            router_for("/wrong" if fault == "router" else "/api/v1/other"),
            {"other.service": b},
            owned_resources=(a, b) if fault == "duplicate-across" else (b,),
        )

    root, entries = catalog(tmp_path, first, second)
    app = FastAPI()
    if fault == "inclusion":

        def fail(*args, **kwargs):
            raise RuntimeError("private inclusion text")

        app.include_router = fail
    with pytest.raises(RouteCompositionError) as caught:
        fp.FirstPartyApplicationComposer(
            context=shared_context, descriptor_root=root, installed=entries
        ).compose(app)
    assert "private" not in str(caught.value)
    assert closed == (
        ["a"]
        if fault in {"exports", "duplicate-within", "later-factory"}
        else ["b", "a"]
    )


@pytest.mark.parametrize("fault", ["raise", "async", "awaitable", "value", "reentrant"])
def test_activation_is_one_shot_even_on_failure(tmp_path, shared_context, fault):
    calls, closed = [], []
    resource = Resource("a", closed)
    publication = None

    async def async_activate(exports):
        pytest.fail("Async activation executed")

    def activate(exports):
        calls.append(1)
        if fault == "raise":
            raise RuntimeError("private activation text")
        if fault == "awaitable":
            return async_activate(exports)
        if fault == "value":
            return True
        publication.activate_startup()

    root, entries = catalog(
        tmp_path,
        lambda context: fp.ContributionServices(
            router_for(), {"example.service": resource}, owned_resources=(resource,)
        ),
        lambda context, *, dependencies: fp.ContributionServices(
            router_for("/api/v1/other"), {"other.service": object()}
        ),
        startup_reconcile=async_activate if fault == "async" else activate,
    )
    publication = fp.FirstPartyApplicationComposer(
        context=shared_context, descriptor_root=root, installed=entries
    ).compose(FastAPI())
    for _ in range(2):
        with pytest.raises(RouteCompositionError) as caught:
            publication.activate_startup()
        assert "private" not in str(caught.value)
    assert calls == ([] if fault == "async" else [1])
    publication.close()
    assert closed == ["a"]


def test_startup_snapshot_only_declared_keys_and_lexical_roots(tmp_path, monkeypatch):
    assert hasattr(fp, "build_startup_inputs"), "Missing bounded startup snapshot"
    from app.api.first_party_catalog import INSTALLED

    key = "DEEPTWIN_TOPOLOGY_SHA256"
    monkeypatch.setenv(key, "x" * 256)
    inputs = fp.build_startup_inputs(values=None, protected_roots=(tmp_path, tmp_path))
    assert inputs.values[key] == "x" * 256
    assert inputs.protected_roots == (tmp_path,)
    monkeypatch.setenv(key, "changed")
    assert inputs.values[key] == "x" * 256
    assert set(inputs.values) <= {k for entry in INSTALLED for k in entry.startup_keys}
    with pytest.raises(TypeError):
        inputs.values[key] = "changed"
    for value in (False, None, "x" * 257, "é" * 129, "\ud800"):
        invalid = fp.build_startup_inputs(
            values={key: value}, protected_roots=(tmp_path,)
        )
        assert dict(invalid.values) == {} and invalid.invalid_keys == (key,)
    for values in ([], "text", {"UNKNOWN": "x"}):
        with pytest.raises((ValueError, TypeError, RouteCompositionError)):
            fp.build_startup_inputs(values=values, protected_roots=(tmp_path,))
    for roots in (
        (Path("relative"),),
        (tmp_path / ".." / "other",),
        tuple(tmp_path / str(i) for i in range(65)),
        (Path("/" + "a" * 4096),),
    ):
        with pytest.raises((ValueError, TypeError, RouteCompositionError)):
            fp.build_startup_inputs(values={}, protected_roots=roots)


@pytest.mark.parametrize(
    "fault",
    [
        "application",
        "session-registration",
        "middleware",
        "handler",
        "activation",
        "worker",
        "shutdown",
    ],
)
def test_supported_host_closes_every_owner_and_activates_after_registration(
    tmp_path, monkeypatch, fault
):
    from fastapi.testclient import TestClient

    from app import server
    from app.api import first_party_catalog, session_routes
    from app.server import create_app
    from app.tests.test_web_owner_integration import configured

    profile, _, arguments = configured(tmp_path)
    closed, calls = [], []
    resource = Resource("source", closed)
    entry = first_party_catalog.INSTALLED[0]

    def factory(context):
        calls.append(context)
        result = entry.factory(context)
        return fp.ContributionServices(result.router, result.exports, (resource,))

    def activate(exports):
        calls.append("activate")
        if fault == "activation":
            raise RuntimeError("private activation")

    def fail(*args, **kwargs):
        raise RuntimeError("original failure")

    monkeypatch.setattr(
        first_party_catalog,
        "INSTALLED",
        (
            replace(entry, factory=factory, startup_reconcile=activate),
            *first_party_catalog.INSTALLED[1:],
        ),
    )
    if fault in {"application", "session-registration", "middleware", "handler"}:
        with monkeypatch.context() as patch:
            if fault == "application":
                patch.setattr(server, "FastAPI", fail)
            elif fault == "session-registration":
                patch.setattr(session_routes, "create_session_router", fail)
            elif fault == "handler":
                patch.setattr(FastAPI, "add_exception_handler", fail)
            else:
                patch.setattr(FastAPI, "add_middleware", fail)
            with pytest.raises(RuntimeError, match="original failure"):
                create_app(tmp_path / "data", **arguments)
        assert "activate" not in calls
    else:
        app = create_app(
            tmp_path / "data",
            worker_dispatch_factory=fail if fault == "worker" else None,
            **arguments,
        )
        assert "activate" not in calls
        if fault == "shutdown":
            with TestClient(app, base_url=profile.http_origin):
                assert calls[-1] == "activate"
        else:
            with (
                pytest.raises((RuntimeError, RouteCompositionError)),
                TestClient(app, base_url=profile.http_origin),
            ):
                pytest.fail("Failed startup admitted HTTP")
        assert calls[-1] == "activate"
    assert closed == ([] if fault == "application" else ["source"])
    if calls:
        assert calls[0].owner_authority._closed
    # Actual serving-lock and store ownership was released: same data can reopen.
    monkeypatch.setattr(
        first_party_catalog, "INSTALLED", (entry, *first_party_catalog.INSTALLED[1:])
    )
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin):
        pass


def test_main_passes_actual_config_parent_and_mandatory_roots(tmp_path, monkeypatch):
    import json
    import os
    import sys

    import uvicorn
    from fastapi.testclient import TestClient

    from app import server
    from app.api import first_party_catalog
    from app.tests.test_web_owner_integration import configured

    profile, _, arguments = configured(tmp_path)
    config = tmp_path / "deployment.json"
    config.write_text(json.dumps(arguments["deployment_config"]))
    seen = []
    entry = first_party_catalog.INSTALLED[0]

    def factory(context):
        seen.append(context.startup_inputs.protected_roots)
        return entry.factory(context)

    monkeypatch.setattr(
        first_party_catalog,
        "INSTALLED",
        (replace(entry, factory=factory), *first_party_catalog.INSTALLED[1:]),
    )

    def serve(app, **kwargs):
        assert kwargs == {
            "host": "0.0.0.0",
            "port": 8080,
            "workers": 1,
            "reload": False,
            "proxy_headers": False,
            "forwarded_allow_ips": "",
            "access_log": False,
        }
        with TestClient(app, base_url=profile.http_origin):
            pass

    monkeypatch.setattr(uvicorn, "run", serve)
    monkeypatch.chdir(tmp_path)
    argv = [
        "app.server",
        "--data-dir",
        str(tmp_path / "data"),
        "--deployment-config",
        "deployment.json",
        "--session-root-dir",
        str(tmp_path / "root"),
        "--expected-uid",
        str(os.getuid()),
        "--expected-gid",
        str(os.getgid()),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    server.main()
    assert set(seen[0]) == {tmp_path, tmp_path / "data", tmp_path / "root"}
    argv[5] = "../" + tmp_path.name + "/deployment.json"
    with pytest.raises((ValueError, SystemExit)):
        server.main()


def test_extra_roots_cannot_remove_mandatory_roots_or_exceed_total_cap(tmp_path):
    from fastapi.testclient import TestClient

    from app.server import create_app
    from app.tests.test_web_owner_integration import configured

    profile, _, arguments = configured(tmp_path)
    with pytest.raises(ValueError, match="protected roots"):
        create_app(
            tmp_path / "data",
            additional_protected_roots=tuple(tmp_path / str(i) for i in range(63)),
            **arguments,
        )
    assert not (tmp_path / "data").exists()
    # Repeating an actual mandatory root uses one lexical slot, not two.
    app = create_app(
        tmp_path / "data",
        additional_protected_roots=(tmp_path / "data",) * 65,
        **arguments,
    )
    with TestClient(app, base_url=profile.http_origin):
        assert not app.state.owner_authority._closed


@pytest.mark.parametrize("original_failure", [False, True])
def test_shutdown_cleanup_is_sanitized_and_preserves_original_failure(
    tmp_path, monkeypatch, original_failure
):
    from fastapi.testclient import TestClient

    from app.api import first_party_catalog
    from app.server import create_app
    from app.tests.test_web_owner_integration import configured

    profile, _, arguments = configured(tmp_path)
    closed = []
    entry = first_party_catalog.INSTALLED[0]

    def factory(context):
        result = entry.factory(context)
        return fp.ContributionServices(
            result.router,
            result.exports,
            (Resource("first", closed), Resource("second", closed, fail=True)),
        )

    def fail(*args, **kwargs):
        raise LookupError("original worker failure")

    with monkeypatch.context() as installed:
        installed.setattr(
            first_party_catalog,
            "INSTALLED",
            (replace(entry, factory=factory), *first_party_catalog.INSTALLED[1:]),
        )
        app = create_app(
            tmp_path / "data",
            worker_dispatch_factory=fail if original_failure else None,
            **arguments,
        )
        expected = LookupError if original_failure else RouteCompositionError
        with (
            pytest.raises(expected) as caught,
            TestClient(app, base_url=profile.http_origin),
        ):
            pass
        assert "private" not in str(caught.value)
    assert closed == ["second", "first"] and app.state.owner_authority._closed
    reopened = create_app(tmp_path / "data", **arguments)
    with TestClient(reopened, base_url=profile.http_origin):
        pass
