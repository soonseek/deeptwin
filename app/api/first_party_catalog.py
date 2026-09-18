"""The complete build-installed catalog; not a runtime extension registry."""

from .deployment_prepare import (
    STARTUP_KEYS,
    prepare_services,
    reconcile_prepare_startup,
)
from .extension_candidates import candidate_services
from .first_party import InstalledContribution, core_services
from .run_approvals import approval_services
from .runs import run_services
from .works import work_services

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
        "run-approvals-v1.json",
        "app.api.run_approvals:create_router",
        approval_services,
        ("browser_session",),
        ("approval.manage", "approval.read"),
        provides=("run-approvals.service",),
    ),
    InstalledContribution(
        "works-v1.json",
        "app.api.works:create_router",
        work_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("works.service",),
    ),
    InstalledContribution(
        "runs-v1.json",
        "app.api.runs:create_router",
        run_services,
        ("browser_session",),
        ("work.command", "work.read"),
        requires=("run-approvals.service",),
        provides=("runs.service",),
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
