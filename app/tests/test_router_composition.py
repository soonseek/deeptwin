"""Frozen build-installed first-party route composition seam."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, BrokenBarrierError

import jsonschema
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.api.router_composition import (
    FirstPartyRouteComposer,
    RouteCompositionError,
)

POLICIES = ("browser_session", "service_bearer")
SCOPES = ("work.read", "work.write", "extensions.manage")
SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "schemas"
    / "v1"
    / "first-party-route-contribution.schema.json"
)


def router_for(path="/api/v1/example", method="GET"):
    router = APIRouter()

    async def endpoint():
        return {"ok": True}

    router.add_api_route(path, endpoint, methods=[method])
    return router


def descriptor(*, contribution_id="example-v1", factory="app.api.example:create_router",
               route_id="example.get", path="/api/v1/example", methods=("GET",),
               auth_policy="browser_session", required_scope="work.read"):
    return {
        "schema_version": "deeptwin-first-party-route-contribution-v1",
        "contribution_id": contribution_id,
        "factory": factory,
        "routes": [{
            "route_id": route_id,
            "methods": list(methods),
            "path": path,
            "auth_policy": auth_policy,
            "required_scope": required_scope,
        }],
    }


def write_descriptor(root: Path, name: str, value):
    target = root / name
    target.write_text(json.dumps(value, separators=(",", ":")), encoding="utf-8")
    return target


def composer(root, names=("example-v1.json",), factories=None):
    return FirstPartyRouteComposer(
        descriptor_root=root,
        descriptor_names=names,
        factory_allowlist=factories or {"app.api.example:create_router": router_for},
        allowed_auth_policies=POLICIES,
        allowed_scopes=SCOPES,
    )


def test_valid_fixed_contribution_is_staged_then_mounted_once(tmp_path):
    write_descriptor(tmp_path, "example-v1.json", descriptor())
    app = FastAPI()
    original = app.include_router
    calls = []

    def include_once(value):
        calls.append(value)
        return original(value)

    app.include_router = include_once
    receipt = composer(tmp_path).compose(app)
    assert len(calls) == 1
    assert receipt.contribution_ids == ("example-v1",)
    assert receipt.route_ids == ("example.get",)
    assert receipt.route_count == 1
    assert TestClient(app).get("/api/v1/example").json() == {"ok": True}


def test_exported_descriptor_schema_is_valid_and_rejects_noncanonical_segments():
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)
    assert list(validator.iter_errors(descriptor())) == []
    for path in ("/api/v1/.", "/api/v1/..", "/api/v1/good/..", "/api/v1/not allowed"):
        value = descriptor(path=path)
        assert list(validator.iter_errors(value))


def test_exported_schema_and_runtime_share_one_exact_method_order(tmp_path):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    canonical = ("DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT")
    for mask in range(1, 1 << len(canonical)):
        methods = tuple(
            method for index, method in enumerate(canonical) if mask & (1 << index)
        )
        assert list(validator.iter_errors(descriptor(methods=methods))) == []
    for methods in (("GET", "DELETE"), ("PUT", "POST"), ("GET", "GET")):
        assert list(validator.iter_errors(descriptor(methods=methods)))

    write_descriptor(
        tmp_path,
        "example-v1.json",
        descriptor(methods=("GET", "DELETE")),
    )
    with pytest.raises(RouteCompositionError, match="route declaration"):
        composer(tmp_path).compose(FastAPI())


def test_existing_deferred_included_router_collision_is_detected(tmp_path):
    write_descriptor(tmp_path, "example-v1.json", descriptor())
    app = FastAPI()
    existing = APIRouter()

    @existing.get("/example")
    async def existing_endpoint():
        return {}

    # Current FastAPI versions retain include_router() as a deferred _IncludedRouter.
    app.include_router(existing, prefix="/api/v1")
    calls = []
    with pytest.raises(RouteCompositionError, match="collides"):
        composer(
            tmp_path,
            factories={"app.api.example:create_router": lambda: calls.append(True)},
        ).compose(app)
    assert calls == []


@pytest.mark.parametrize(
    "change",
    (
        {"extra": True},
        {"schema_version": "other"},
        {"contribution_id": "UPPER"},
        {"factory": "os:path"},
        {"routes": []},
    ),
)
def test_descriptor_is_closed_and_validated_before_factory_or_app_mutation(tmp_path, change):
    value = descriptor()
    value.update(change)
    write_descriptor(tmp_path, "example-v1.json", value)
    app = FastAPI()
    before = tuple(app.routes)
    calls = []
    with pytest.raises(RouteCompositionError):
        composer(tmp_path, factories={"app.api.example:create_router": lambda: calls.append(True)}).compose(app)
    assert calls == [] and tuple(app.routes) == before


def test_all_descriptors_validate_before_any_factory_or_app_mutation(tmp_path):
    write_descriptor(tmp_path, "a.json", descriptor(contribution_id="a", route_id="a.get"))
    write_descriptor(tmp_path, "b.json", descriptor(contribution_id="b", route_id="b.get") | {"bad": 1})
    app = FastAPI()
    calls = []
    with pytest.raises(RouteCompositionError):
        composer(
            tmp_path,
            names=("a.json", "b.json"),
            factories={"app.api.example:create_router": lambda: calls.append(True)},
        ).compose(app)
    assert calls == []
    assert not any(getattr(route, "path", "") == "/api/v1/example" for route in app.routes)


def test_duplicate_contribution_route_and_method_path_ids_fail_closed(tmp_path):
    cases = (
        (
            descriptor(contribution_id="same", route_id="first", path="/api/v1/first"),
            descriptor(contribution_id="same", route_id="second", path="/api/v1/second"),
        ),
        (
            descriptor(contribution_id="first", route_id="same", path="/api/v1/first"),
            descriptor(contribution_id="second", route_id="same", path="/api/v1/second"),
        ),
        (
            descriptor(contribution_id="first", route_id="first"),
            descriptor(contribution_id="second", route_id="second"),
        ),
    )
    for first, second in cases:
        root = tmp_path / first["contribution_id"] / second["routes"][0]["route_id"]
        root.mkdir(parents=True)
        write_descriptor(root, "a.json", first)
        write_descriptor(root, "b.json", second)
        with pytest.raises(RouteCompositionError):
            composer(root, names=("a.json", "b.json")).compose(FastAPI())


@pytest.mark.parametrize(
    "change",
    (
        {"path": "/api/v2/example"},
        {"path": "/api/v1//example"},
        {"path": "/api/v1/../example"},
        {"path": "/api/v1/example?x=1"},
        {"methods": ("get",)},
        {"methods": ("GET", "GET")},
        {"auth_policy": "ambient"},
        {"required_scope": "admin.all"},
        {"unknown": True},
    ),
)
def test_route_declaration_requires_exact_path_method_auth_scope_and_fields(tmp_path, change):
    value = descriptor()
    value["routes"][0].update(change)
    write_descriptor(tmp_path, "example-v1.json", value)
    with pytest.raises(RouteCompositionError):
        composer(tmp_path).compose(FastAPI())


@pytest.mark.parametrize(
    "change",
    (
        {"contribution_id": "a" * 129},
        {"factory": f"app.api.{'a' * 235}:create_router"},
        {"route_id": "a" * 129},
        {"path": "/api/v1/not allowed"},
        {"path": "/api/v1/" + "a" * 1017},
        {"auth_policy": "a" * 129},
        {"required_scope": "a" * 129},
    ),
)
def test_runtime_enforces_exported_schema_string_bounds_and_path_alphabet(tmp_path, change):
    value = descriptor()
    for key, replacement in change.items():
        if key in {"contribution_id", "factory"}:
            value[key] = replacement
        else:
            value["routes"][0][key] = replacement
    write_descriptor(tmp_path, "example-v1.json", value)
    with pytest.raises(RouteCompositionError):
        composer(tmp_path).compose(FastAPI())


def test_existing_route_collision_fails_before_factory_call(tmp_path):
    write_descriptor(tmp_path, "example-v1.json", descriptor())
    app = FastAPI()

    @app.get("/api/v1/example")
    async def existing():
        return {}

    calls = []
    with pytest.raises(RouteCompositionError):
        composer(
            tmp_path,
            factories={"app.api.example:create_router": lambda: calls.append(True)},
        ).compose(app)
    assert calls == []


def test_missing_factory_and_route_shape_mismatch_fail_without_mount(tmp_path):
    write_descriptor(tmp_path, "example-v1.json", descriptor())
    for factories in ({}, {"app.api.example:create_router": lambda: router_for("/api/v1/other")}):
        app = FastAPI()
        before = tuple(app.routes)
        with pytest.raises(RouteCompositionError):
            FirstPartyRouteComposer(
                descriptor_root=tmp_path,
                descriptor_names=("example-v1.json",),
                factory_allowlist=factories,
                allowed_auth_policies=POLICIES,
                allowed_scopes=SCOPES,
            ).compose(app)
        assert tuple(app.routes) == before


def test_symlink_nonregular_hardlink_and_unlisted_runtime_descriptor_are_rejected(tmp_path):
    real = write_descriptor(tmp_path, "real.json", descriptor())
    (tmp_path / "link.json").symlink_to(real)
    with pytest.raises(RouteCompositionError):
        composer(tmp_path, names=("link.json",)).compose(FastAPI())
    (tmp_path / "link.json").unlink()
    (tmp_path / "hard.json").hardlink_to(real)
    with pytest.raises(RouteCompositionError):
        composer(tmp_path, names=("real.json",)).compose(FastAPI())
    (tmp_path / "hard.json").unlink()
    write_descriptor(tmp_path, "runtime.json", descriptor(contribution_id="runtime"))
    with pytest.raises(RouteCompositionError):
        composer(tmp_path, names=("real.json",)).compose(FastAPI())


def test_symlink_descriptor_root_is_rejected(tmp_path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    write_descriptor(real_root, "example-v1.json", descriptor())
    link_root = tmp_path / "linked-root"
    link_root.symlink_to(real_root, target_is_directory=True)
    with pytest.raises(RouteCompositionError):
        composer(link_root).compose(FastAPI())


def test_factory_cannot_hide_duplicate_routes_behind_set_equality(tmp_path):
    write_descriptor(tmp_path, "example-v1.json", descriptor())

    def duplicate_router():
        value = router_for()
        duplicate = router_for()
        value.routes.extend(duplicate.routes)
        return value

    with pytest.raises(RouteCompositionError):
        composer(
            tmp_path,
            factories={"app.api.example:create_router": duplicate_router},
        ).compose(FastAPI())


def test_composer_freezes_after_first_success_and_rejects_late_mutation(tmp_path):
    target = write_descriptor(tmp_path, "example-v1.json", descriptor())
    value = composer(tmp_path)
    value.compose(FastAPI())
    target.write_text(json.dumps(descriptor(path="/api/v1/changed")), encoding="utf-8")
    with pytest.raises(RouteCompositionError):
        value.compose(FastAPI())


def test_composer_freeze_is_atomic_and_exactly_once_under_concurrency(tmp_path):
    write_descriptor(tmp_path, "example-v1.json", descriptor())
    subject = composer(tmp_path)
    apps = (FastAPI(), FastAPI())
    original_parse = subject._parse_descriptor
    rendezvous = Barrier(2)

    def synchronized_parse(raw):
        try:
            rendezvous.wait(timeout=0.2)
        except BrokenBarrierError:
            pass
        return original_parse(raw)

    subject._parse_descriptor = synchronized_parse

    def attempt(index):
        try:
            return subject.compose(apps[index])
        except RouteCompositionError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, range(2)))
    assert sum(value is not None for value in outcomes) == 1
    assert sum(
        ("/api/v1/example", "GET") in subject._route_pairs(app.routes)
        for app in apps
    ) == 1


def test_descriptor_rewrite_during_bounded_read_is_rejected(tmp_path, monkeypatch):
    target = write_descriptor(tmp_path, "example-v1.json", descriptor())
    replacement = json.dumps(
        descriptor(path="/api/v1/changed"), separators=(",", ":"),
    ).encode("utf-8")
    assert len(replacement) == target.stat().st_size
    original_read = __import__("os").read
    rewritten = False

    def rewrite_after_read(fd, size):
        nonlocal rewritten
        raw = original_read(fd, size)
        if not rewritten:
            rewritten = True
            target.write_bytes(replacement)
        return raw

    monkeypatch.setattr("app.api.router_composition.os.read", rewrite_after_read)
    with pytest.raises(RouteCompositionError, match="changed"):
        composer(tmp_path).compose(FastAPI())


def test_constructor_rejects_ambiguous_allowlists_and_paths(tmp_path):
    write_descriptor(tmp_path, "example-v1.json", descriptor())
    with pytest.raises((TypeError, ValueError, RouteCompositionError)):
        FirstPartyRouteComposer(
            descriptor_root=tmp_path,
            descriptor_names=("../example-v1.json",),
            factory_allowlist={"app.api.example:create_router": router_for},
            allowed_auth_policies=POLICIES,
            allowed_scopes=SCOPES,
        )
    with pytest.raises((TypeError, ValueError, RouteCompositionError)):
        composer(tmp_path, names=("example-v1.json", "example-v1.json"))
