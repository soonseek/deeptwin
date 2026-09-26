"""The complete build-installed catalog; not a runtime extension registry."""

from .artifact_index import artifact_index_services
from .backups import backup_services
from .browser_grants import browser_grant_services
from .budget_policies import budget_services
from .claude_connection import connection_services
from .conversations import conversation_services
from .credential_wiring import credential_services
from .deployment_prepare import (
    STARTUP_KEYS,
    prepare_services,
    reconcile_prepare_startup,
)
from .design_workspace import design_workspace_services
from .extension_bindings import binding_services, reconcile_binding_startup
from .extension_candidates import candidate_services
from .first_party import InstalledContribution, core_services
from .graphs import graph_services
from .hypotheses import hypothesis_services
from .platform_update import platform_update_services
from .provider_conformance import conformance_services
from .provider_installation import installation_services
from .retention import retention_services
from .run_approvals import approval_services
from .run_consents import consent_services
from .runs import run_services
from .source_readings import reading_services
from .versions import version_services
from .work_models import work_model_services
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
        "backups-v1.json",
        "app.api.backups:create_router",
        backup_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("backups.service",),
    ),
    InstalledContribution(
        "retention-v1.json",
        "app.api.retention:create_router",
        retention_services,
        ("browser_session",),
        ("work.command", "work.read"),
        requires=("backups.service", "works.service"),
        provides=("retention.service",),
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
        "source-readings-v1.json",
        "app.api.source_readings:create_router",
        reading_services,
        ("browser_session",),
        ("work.command", "work.read"),
        requires=("works.service",),
        provides=("source-readings.service",),
    ),
    InstalledContribution(
        "conversations-v1.json",
        "app.api.conversations:create_router",
        conversation_services,
        ("browser_session",),
        ("work.command", "work.read"),
        requires=("works.service", "work-models.service"),
        provides=("conversations.service",),
    ),
    InstalledContribution(
        "budget-policies-v1.json",
        "app.api.budget_policies:create_router",
        budget_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("budget-policies.service",),
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
        "artifact-index-v1.json",
        "app.api.artifact_index:create_router",
        artifact_index_services,
        ("browser_session",),
        ("work.read",),
        requires=("run-artifacts.service",),
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
        provides=("provider-conformance.service", "provider-transport-qualification.service"),
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
    InstalledContribution(
        "extension-bindings-v1.json",
        "app.api.extension_bindings:create_router",
        binding_services,
        ("browser_session",),
        ("extension.manage", "extension.read"),
        requires=("provider-transport-qualification.service",),
        provides=("extension-bindings.service",),
        startup_reconcile=reconcile_binding_startup,
    ),
    InstalledContribution(
        "browser-grants-v1.json",
        "app.api.browser_grants:create_router",
        browser_grant_services,
        ("browser_session",),
        ("work.command", "work.read"),
        provides=("browser-grants.service",),
    ),
    InstalledContribution(
        "platform-update-v1.json",
        "app.api.platform_update:create_router",
        platform_update_services,
        ("browser_session",),
        ("deployment.read",),
        provides=("platform-update.guidance",),
    ),
)
