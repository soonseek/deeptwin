"""The complete build-installed catalog; not a runtime extension registry."""

from .claude_connection import connection_services
from .credential_wiring import credential_services
from .design_workspace import design_workspace_services
from .graphs import graph_services
from .hypotheses import hypothesis_services
from .work_models import work_model_services
from .deployment_prepare import (
    STARTUP_KEYS,
    prepare_services,
    reconcile_prepare_startup,
)
from .extension_candidates import candidate_services
from .first_party import InstalledContribution, core_services
from .provider_conformance import conformance_services
from .provider_installation import installation_services
from .run_approvals import approval_services
from .run_consents import consent_services
from .runs import run_services
from .versions import version_services
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
        provides=("works.service", "work-exports.service"),
    ),
    InstalledContribution(
        "run-consents-v1.json",
        "app.api.run_consents:create_router",
        consent_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("run-consents.service",),
    ),
    InstalledContribution(
        "claude-connection-v1.json",
        "app.api.claude_connection:create_router",
        connection_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("claude.connection",),
    ),
    InstalledContribution(
        "credentials-v1.json",
        "app.api.credential_wiring:create_router",
        credential_services,
        ("browser_session",),
        ("work.command", "work.read"),
    ),
    InstalledContribution(
        "work-models-v1.json",
        "app.api.work_models:create_router",
        work_model_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("work-models.service",),
    ),
    InstalledContribution(
        "runs-v1.json",
        "app.api.runs:create_router",
        run_services,
        ("browser_session",),
        ("work.command", "work.read"),
        requires=("run-approvals.service",),
        provides=("runs.service", "run-artifacts.service", "alternative-drafts.service"),
    ),
    InstalledContribution(
        "graphs-v1.json",
        "app.api.graphs:create_router",
        graph_services,
        ("browser_session",),
        ("work.read",),
        provides=("graphs.service",),
    ),
    InstalledContribution(
        "design-workspace-v1.json",
        "app.api.design_workspace:create_router",
        design_workspace_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("design-workspace.service",),
    ),
    InstalledContribution(
        "hypotheses-v1.json",
        "app.api.hypotheses:create_router",
        hypothesis_services,
        ("browser_session",),
        ("work.command", "work.read"),
        requires=("alternative-drafts.service",),
        provides=("hypotheses.service",),
    ),
    InstalledContribution(
        "versions-v1.json",
        "app.api.versions:create_router",
        version_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("versions.service",),
    ),
    InstalledContribution(
        "deployment-prepare-v1.json",
        "app.api.deployment_prepare:create_router",
        prepare_services,
        ("browser_session",),
        ("deployment.manage", "deployment.read"),
        requires=("extension-candidates.registry",),
        provides=("deployment-prepare.service", "deployment-provider.source-context", "installation-release.source-context"),
        startup_keys=STARTUP_KEYS,
        startup_reconcile=reconcile_prepare_startup,
    ),
    InstalledContribution(
        "provider-conformance-v1.json",
        "app.api.provider_conformance:create_router",
        conformance_services,
        ("browser_session",),
        ("extension.manage", "extension.read"),
        requires=("deployment-prepare.service", "deployment-provider.source-context"),
        provides=("provider-conformance.service",),
    ),
    InstalledContribution(
        "provider-installation-v1.json",
        "app.api.provider_installation:create_router",
        installation_services,
        ("browser_session",),
        ("extension.manage", "extension.read"),
        requires=("deployment-prepare.service", "installation-release.source-context"),
        provides=("provider-installation.service",),
    ),
)
