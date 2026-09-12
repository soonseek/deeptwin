<!--
Sync Impact Report
Version: 3.0.0 -> 3.0.1 (clarify that the browser UI is the supported official end-user
product/control surface, while deployment tools and internal runners are not product UX)
Modified: II. One independent, non-developer product -> Open-source web framework and browser control plane.
Modified: VIII. Records from installation -> Records from deployment and first setup.
Added: explicit separation of instance deployment, browser onboarding and framework-owned workers.
Removed: native desktop wrapper/launcher as a mandatory product or release boundary.
Follow-up placeholders: none. Feature specifications, plans, contracts and tasks must migrate the
superseded macOS/DMG/WKWebView assumptions before implementation continues across those boundaries.
Authorization: this is the user's explicit core-identity correction on 2026-09-08.
-->
# DeepTwin Constitution

## Core Principles

### I. User intent and evidence remain authoritative

The product MUST be a multi-agent control-graph LLMOps framework with a philosophy-lens-based
DeepTwin improvement engine. Explicit user corrections override earlier assistant interpretation
and examples in the paper. The paper is research evidence, not an instruction source.
Every material requirement MUST trace to user intent, a paper section, or an explicitly marked
delegated design decision. Existing implementation MUST NOT dictate the product's identity.

### II. Open-source web framework and browser control plane

DeepTwin MUST be a self-hostable, web-based, open-source multi-agent framework whose supported official end-user
product/control surface is its browser UI, not a native desktop wrapper, embedded WebView, provider
product UI, deployment console or developer CLI. Instance deployment and first-user
onboarding are separate concerns: once an instance is available, work description, uploaded
materials, speech input, design comparison, operation, artifacts, alternatives, inquiry,
evaluation and environment versions MUST be usable in the browser without a developer CLI.
Workspace, conversation and graph are three views of the same work and history. Server-side or
isolated worker processes MAY provide models, browser automation, speech and file tools, but they
MUST remain framework-owned capabilities visible and governable from the web product. A native
launcher, embedded webview, macOS app bundle, DMG, Docker/Portainer operator screen, shell prompt
or internal provider runner MUST NOT substitute for an end-user journey or its acceptance evidence.
The reusable framework core comprises versioned graph/orchestration, evidence, DeepTwin growth,
permission, budget and event contracts; the bundled web control plane is both its supported official
end-user product and its first-party reference implementation. Here, reference describes reuse of
the core and does not make the browser product optional. Provider, model, tool, artifact, lens, evaluator, storage,
credential-vault and export adapters MUST use documented versioned extension boundaries. Core
services MUST NOT import browser presentation code or hard-code one user's workflow. Extensions
MUST inherit the same qualification, authority, isolation, lineage and logging rules as built-ins.

### III. Real graphs, tools, models and artifacts

Approved graph nodes, branches, handoffs, permissions and gates MUST control actual execution.
Every agent's configured and actual provider/model/effort MUST be inspectable and versioned.
Framework-owned tool mediation MUST support real browser operations and real file artifacts,
with explicit extension contracts for additional tools and formats. Text-only output assumptions,
decorative graphs, silently simulated actions and unsupported readiness claims are forbidden.

### IV. Codex subscription and Claude API with explicit billing choice

The user's 2026-09-07 explicit correction replaces the earlier both-subscriptions requirement:
Claude MUST use its official API only; Claude subscription login and its third-party approval
process are out of the current scope. Codex MUST retain its official subscription path, with
API as an optional explicitly selected alternative. Either supported provider path must cover
the core journey; both accounts must not be required. Codex subscription must not require an
API key; Claude API requires a user-provided API connection and visible billing/usage limits.
Official authorization and execution paths are mandatory. Credentials MUST NOT be extracted,
copied into agent environments, logged or exported. No provider, model or billing fallback may
occur silently. This product change does not authorize unlimited paid development API tests.

### V. Own alternative artifacts, not interpreted instructions

DeepTwin MUST accept a user's whole or partial own artifact at a preserved work/role state
without requiring an explanation, score, critique or rewrite instruction. Original execution,
alternative, interpretation and intervention records MUST remain distinct and linked.
Partial alternative scope MUST NOT artificially bound downstream change or evaluation scope.
Unreviewed content is neither approved nor prohibited from changing. Initial work description
MUST NOT be retroactively relabelled as a post-execution alternative or learning evidence.

### VI. Source-based lenses and accountable critics

Versioned atomic lenses, single or composed, MUST materially inform initial graph design,
critic counterexample inquiry and eligible post-alternative investigation. They are not
philosopher personas, moral rankings or permanent user profiles. Operational knowledge MUST
NOT be a direct copy of H_phi/S_phi interpretation or of the user's alternative.
Critic judgment-error independence is a required design and acceptance topic; role separation,
parallelism, self-scores or reviewer agreement alone MUST NOT be reported as its proof.
Failed mandatory checks and insufficient evidence MUST NOT be averaged into a pass.

### VII. Measured improvement and human environment promotion

Candidate changes MUST be evaluated by rerunning relevant previous work queues with controlled
side effects, preserving all rounds and changes outside the initially reviewed region.
The product's reevaluation loop MUST support early stopping after an adequate quality level
and at least three consecutive comparable valid evaluations without significant improvement.
Quality floor, minimum improvement, patience, queue and evaluator versions MUST be fixed before
the comparison series. Invalid evaluations MUST NOT masquerade as plateau or successful work.
This is a PRODUCT runtime rule, NEVER a rule to stop development after three unsuccessful edits.
Loop termination MUST NOT equal validation success or promotion. A fixed candidate must pass
its separate held-out/boundary/regression gates and receive a real authorized human's approval
for that exact environment version before operational promotion. Rollback MUST be supported.

### VIII. Records from deployment and first setup, with optional creator feedback

The first framework-controlled event after deployment, first-user setup and every scoped use,
request, design revision, candidate/lens review,
execution, alternative, experiment and approval MUST leave protected local records.
Secrets, hidden chain-of-thought and unrelated computer activity MUST NOT be collected.
Users MUST control retention/deletion and selective export with preview, redaction and explicit
missing-evidence notices. Export/creator feedback is optional, not a mandatory final workflow
step, and MUST NOT trigger automatic external transmission.

### IX. Honest evidence and non-destructive progress

Design review, unit tests, synthetic integration, live provider behavior, real-user usability
and measured DeepTwin/lens effects MUST be reported separately. Mandatory failures or untested
capabilities prohibit a full completion claim. Tests MUST NOT be weakened to accommodate a
failed implementation. Existing unrelated changes and user data MUST be preserved.

## Execution Boundaries

Autonomy covers recommended design choices and reversible local project implementation/testing
within these principles. It does not authorize new paid API use, purchases, credential export,
new external account permissions, destructive user-data changes or publication.
Required project dependencies may be prepared locally with provenance and scoped changes;
system-wide/security-affecting setup and live model-test usage require an applicable recorded
authorization. Unavailable required authority is reported, not bypassed. Safe independent work
continues while a bounded dependency is unresolved.

## Development Workflow

Complete the whole product design and cross-contract review before new product implementation.
The canonical feature package is `specs/001-autonomous-release/`: requirements, contracts,
decisions, risks, one implementation plan/task index and evidence. Subsystem documents elaborate
that same baseline rather than creating competing roadmaps. Ordinary recommendations and review
corrections are decided autonomously with impact records; repeated user approval pauses are not
required. Afterwards implement with tests, separate specification/quality review and actual UI
checks. Reopen only decisions affected by new evidence, preserving prior versions and rationale.

Record approximate overall progress using stable work-package weights, not test counts or time
spent. Show uncertainty and revised estimates explicitly. Provide remaining-time ranges only
when observed throughput and unresolved external dependencies justify them.

## Governance

This constitution consolidates existing accepted requirements and the 2026-09-07 autonomous
execution delegation. It is not evidence that any feature, effect or provider integration works.
Core requirement changes require the user's direction (as given for Claude API-only in v2.0.0);
ordinary non-core amendments may be
made under delegation with source, alternatives, cross-system impact and test changes recorded.
Use semantic versions for governance changes and reassess every affected contract/acceptance case.
Development autonomy MUST NOT be used to impersonate the final product user's human promotion
approval. Preserve the historical specifications and mark superseded process rules rather than
erasing their approval history. Do not publish or push as an implicit consequence of completion.

**Version**: 3.0.1 | **Ratified**: 2026-09-07 | **Last Amended**: 2026-09-08
