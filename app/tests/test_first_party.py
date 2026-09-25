"""Build-owned contributions share actual dependencies without feature startup wiring."""

import ast
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.server import create_app
from app.tests.extension_candidate_fixture import candidate_payload
from app.tests.test_web_owner_integration import bootstrap_client, configured, headers


@pytest.fixture
def shared_context(tmp_path):
    from app.api.first_party import ApplicationContext

    profile, _, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin):
        yield ApplicationContext(
            app.state.api_v1, app.state.owner_authority, profile.base_path
        )


def test_additional_build_installed_contribution_without_server_or_composer_edits(
    tmp_path, monkeypatch
):
    import json
    from dataclasses import FrozenInstanceError

    from fastapi import APIRouter

    from app.api import first_party, first_party_catalog
    from app.api.first_party import ContributionServices, InstalledContribution
    from app.tests.test_router_composition import descriptor

    root = tmp_path / "route_contributions"
    root.mkdir()
    for path in (
        Path(first_party.__file__).with_name("route_contributions").glob("*.json")
    ):
        (root / path.name).write_bytes(path.read_bytes())
    (root / "example-v1.json").write_text(json.dumps(descriptor()))
    contexts = []

    def factory(context):
        contexts.append(context)
        router = APIRouter()

        @router.get("/api/v1/example")
        def read():
            return {"same_vault": context.domain_store.vault_id}

        return ContributionServices(router, {"example.context": context})

    entry = InstalledContribution(
        "example-v1.json",
        "app.api.example:create_router",
        factory,
        ("browser_session",),
        ("work.read",),
        provides=("example.context",),
    )
    monkeypatch.setattr(
        first_party_catalog, "INSTALLED", (*first_party_catalog.INSTALLED, entry)
    )
    # Simulate a different installed build's files, not an operator-selectable path.
    monkeypatch.setattr(first_party, "__file__", str(tmp_path / "first_party.py"))
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        assert client.get(
            profile.base_path + "api/v1/example", headers=headers(profile)
        ).json() == {"same_vault": app.state.domain_store.vault_id}
        assert (
            client.post(
                profile.base_path + "api/v1/extensions/candidates",
                headers=headers(profile, csrf),
                json=candidate_payload(),
            ).status_code
            == 201
        )
        assert len(contexts) == 1
        context = contexts[0]
        assert context is app.state.first_party_exports["example.context"]
        assert context.components is app.state.api_v1
        assert context.owner_authority is app.state.owner_authority
        assert context.worker_dispatch_slot is None
        with pytest.raises(FrozenInstanceError):
            context.base_path = "/replacement/"
        assert app.state.route_composition.route_count == 87  # 86 installed + example


@pytest.mark.parametrize(
    "fault",
    [
        "duplicate-export",
        "missing",
        "wrong-factory",
        "reused-factory",
        "swapped-descriptors",
        "routes",
        "hooks",
    ],
)
def test_common_seam_failure_is_atomic_and_frozen(tmp_path, shared_context, fault):
    from dataclasses import replace

    from fastapi import FastAPI

    from app.api.first_party import (
        ContributionServices,
        FirstPartyApplicationComposer,
        InstalledContribution,
    )
    from app.api.router_composition import RouteCompositionError
    from app.tests.test_router_composition import (
        descriptor,
        router_for,
        write_descriptor,
    )

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

    def first(context):
        return ContributionServices(router_for(), {"shared": context})

    def second(context):
        router = router_for("/api/v1/wrong" if fault == "routes" else "/api/v1/other")
        if fault == "hooks":
            router.on_startup.append(lambda: None)
        return ContributionServices(
            router, {"shared" if fault == "duplicate-export" else "other": context}
        )

    entries = (
        InstalledContribution(
            "example-v1.json",
            "app.api.example:create_router",
            first,
            ("browser_session",),
            ("work.read",),
            provides=("shared",),
        ),
        InstalledContribution(
            "other-v1.json",
            "app.api.other:create_router",
            second,
            ("browser_session",),
            ("work.read",),
            provides=("other",),
        ),
    )
    if fault == "missing":
        entries = entries[:1]
    if fault == "wrong-factory":
        entries = (
            entries[0],
            replace(entries[1], factory_name="app.api.wrong:create_router"),
        )
    if fault == "swapped-descriptors":
        entries = (
            replace(entries[0], descriptor_name="other-v1.json"),
            replace(entries[1], descriptor_name="example-v1.json"),
        )
    if fault == "reused-factory":
        write_descriptor(
            root,
            "other-v1.json",
            descriptor(
                contribution_id="other-v1",
                factory="app.api.example:create_router",
                route_id="other.get",
                path="/api/v1/other",
            ),
        )
    composer = FirstPartyApplicationComposer(
        context=shared_context, descriptor_root=root, installed=entries
    )
    app = FastAPI()
    before = tuple(app.routes)
    with pytest.raises(RouteCompositionError):
        composer.compose(app)
    assert tuple(app.routes) == before
    assert not hasattr(app.state, "first_party_exports")
    with pytest.raises(RouteCompositionError, match="frozen"):
        composer.compose(app)


def test_common_seam_freezes_success_and_detaches_exports(tmp_path, shared_context):
    from fastapi import FastAPI

    from app.api.first_party import (
        ContributionServices,
        FirstPartyApplicationComposer,
        InstalledContribution,
    )
    from app.api.router_composition import RouteCompositionError
    from app.tests.test_router_composition import (
        descriptor,
        router_for,
        write_descriptor,
    )

    root = tmp_path / "descriptors"
    root.mkdir()
    write_descriptor(root, "example-v1.json", descriptor())
    exports = {"example": shared_context}
    services = ContributionServices(router_for(), exports)
    exports.clear()
    entry = InstalledContribution(
        "example-v1.json",
        "app.api.example:create_router",
        lambda context: services,
        ("browser_session",),
        ("work.read",),
        provides=("example",),
    )
    composer = FirstPartyApplicationComposer(
        context=shared_context, descriptor_root=root, installed=(entry,)
    )
    app = FastAPI()
    publication = composer.compose(app)
    assert publication.exports["example"] is shared_context
    with pytest.raises(TypeError):
        publication.exports["other"] = shared_context
    with pytest.raises(RouteCompositionError, match="frozen"):
        composer.compose(app)


@pytest.mark.parametrize(
    "field,value",
    [
        ("components", object()),
        ("owner_authority", object()),
        ("base_path", "/wrong/"),
        ("runtime_dispatch_resolver", "module:function"),
    ],
)
def test_shared_context_rejects_replaced_dependencies(shared_context, field, value):
    from dataclasses import replace

    with pytest.raises(TypeError):
        replace(shared_context, **{field: value})


def test_catalog_rejects_mutable_declarations():
    from app.api.first_party import InstalledContribution

    with pytest.raises(TypeError):
        InstalledContribution(
            "example-v1.json",
            "app.api.example:create_router",
            lambda context: None,
            ["browser_session"],
            ("work.read",),
        )


def test_failed_contribution_publication_releases_real_startup_ownership(
    tmp_path, monkeypatch
):
    from dataclasses import replace

    from app.api import first_party_catalog
    from app.api.first_party import ContributionServices
    from app.api.router_composition import RouteCompositionError

    installed = first_party_catalog.INSTALLED

    def duplicate_export(context):
        core = installed[0].factory(context)
        return ContributionServices(
            core.router, {"extension-candidates.registry": context}
        )

    profile, capability, arguments = configured(tmp_path)
    with monkeypatch.context() as changed_build:
        changed_build.setattr(
            first_party_catalog,
            "INSTALLED",
            (replace(installed[0], factory=duplicate_export), *installed[1:]),
        )
        with pytest.raises(RouteCompositionError):
            create_app(tmp_path / "data", **arguments)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        assert (
            client.post(
                profile.base_path + "api/v1/extensions/candidates",
                json=candidate_payload(),
                headers=headers(profile, csrf),
            ).status_code
            == 201
        )


def test_supported_cookie_uses_contribution_owned_actual_dependencies(tmp_path):
    profile, capability, arguments = configured(tmp_path)
    app = create_app(tmp_path / "data", **arguments)
    with TestClient(app, base_url=profile.http_origin) as client:
        csrf = bootstrap_client(client, profile, capability)
        response = client.post(
            profile.base_path + "api/v1/extensions/candidates",
            json=candidate_payload(),
            headers=headers(profile, csrf),
        )
        assert response.status_code == 201
        assert hasattr(app.state, "first_party_exports"), (
            "common contribution exports missing"
        )
        registry = app.state.first_party_exports["extension-candidates.registry"]
        assert registry._domain is app.state.domain_store
        assert registry._owner is app.state.owner_authority
        with pytest.raises(TypeError):
            app.state.first_party_exports["replacement"] = registry


def test_supported_server_has_only_common_composition_dependencies():
    tree = ast.parse((Path(__file__).parents[1] / "server.py").read_text())
    factory = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )
    forbidden = []
    for node in ast.walk(factory):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and (
                "extension" in node.module
                or node.module in {"api.routes", "api.router_composition"}
            )
        ):
            forbidden.append(node.module)
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and (
                node.value.endswith(".json")
                or node.value.startswith(("extension.", "app.api."))
            )
        ):
            forbidden.append(node.value)
    assert forbidden == []
