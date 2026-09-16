"""The complete build-installed catalog; not a runtime extension registry."""

from .deployment_prepare import (
    STARTUP_KEYS,
    prepare_services,
    reconcile_prepare_startup,
)
from .extension_candidates import candidate_services
from .first_party import InstalledContribution, core_services

INSTALLED = (
    InstalledContribution(
        "core-v1.json",
        "app.api.routes:create_router",
        core_services,
        ("browser_session",),
        ("work.read", "work.command"),
    ),
    InstalledContribution(
        "extension-candidates-v1.json",
        "app.api.extension_candidates:create_router",
        candidate_services,
        ("browser_session",),
        ("extension.manage", "extension.read"),
        provides=("extension-candidates.registry",),
    ),
    InstalledContribution(
        "deployment-prepare-v1.json",
        "app.api.deployment_prepare:create_router",
        prepare_services,
        ("browser_session",),
        ("deployment.manage", "deployment.read"),
        requires=("extension-candidates.registry",),
        provides=("deployment-prepare.service",),
        startup_keys=STARTUP_KEYS,
        startup_reconcile=reconcile_prepare_startup,
    ),
)
