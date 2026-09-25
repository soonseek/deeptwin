"""Test support (T043 grants): one owner vault in which a browser tool call is authorized
the way production authorizes it — never by a grant supplied in code.

`granted_run` creates the owner's browser grant record through `PersistentBrowserGrants`
(the route's own service, under the owner's authenticated request), records the owner's
design approval whose `tool_permissions` is exactly that grant record through the real
producers (owner decision → `record_design_approval` → prepared version →
`persist_design_approval` / `persist_environment_head` / `persist_environment_record`),
starts a run whose environment is that sealed record, and compiles a graph whose `writer`
node binds the browser tool with the grant record as its `grant_ref`. The ledger and the
budget book are the app's own over the same vault.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app.domain.refs import EntityRef

GRANTED_HOST = "granted.test"


def future(days=7):
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def grant_command(**changes) -> dict:
    """An owner's `browser-grant-command-v1`: pure navigation to the home page, and one
    search entry whose `q` may carry only the owner's declared topic values."""

    body = {
        "schema_version": "browser-grant-command-v1", "command_id": str(uuid4()), "label": "공개 문서 읽기",
        "tools": ["browser_navigate", "browser_read", "browser_screenshot"],
        "sources": ["https://granted.test/"], "recipients": ["granted.test"],
        "entries": [{"url": "https://granted.test/", "parameters": []},
                    {"url": "https://granted.test/search", "parameters": [{"name": "q", "source": "topic"}]}],
        "data_sources": [{"source_id": "topic", "values": ["deeptwin", "공개 자료"]}],
        "limits": {"max_response_bytes": 1024 * 1024, "max_total_bytes": 4 * 1024 * 1024, "max_requests": 32,
                   "max_redirects": 3, "ttl_ms": 60_000},
        "expires_at_utc": future(),
    }
    body.update(changes)
    return body


@contextmanager
def owner_vault(tmp_path):
    from app.tests.test_extension_candidates_persistent import owner

    with owner(tmp_path) as (app, client, request, profile, arguments):
        yield SimpleNamespace(app=app, client=client, request=request, profile=profile, arguments=arguments)


def _replace_grant(value, old, new):
    if value == old:
        return new
    if type(value) is dict:
        return {key: _replace_grant(item, old, new) for key, item in value.items()}
    if type(value) is list:
        return [_replace_grant(item, old, new) for item in value]
    return value


def compiled_with_grant(tool, grant_ref: EntityRef):
    """`linear_graph` with its one grant replaced by the owner's grant record, compiled
    under an authority whose browser ToolDefinition requires exactly that record."""

    from app.runtime.graph import CompilationAuthority
    from app.tests.test_graph_contract import compile_value, ref, trusted_tool
    from app.tests.test_graph_execution import linear_graph

    old = ref("grant", 6)
    graph = _replace_grant(linear_graph(), old, grant_ref.as_dict())
    definition = list(trusted_tool(tool_id=tool, version="1.0.0"))
    definition[1] = grant_ref
    authority = CompilationAuthority.from_trusted(
        model_choices=[(EntityRef.from_dict(ref("model_choice", 3)), ("text",))],
        tool_definitions=[tuple(definition)], grant_refs=[grant_ref], approval_scopes=["release-output"],
        observation_contract_refs=[EntityRef.from_dict(ref("observation_contract", 7))],
        budget_policy_refs=[EntityRef.from_dict(ref("budget_policy", 8))], artifact_schema_refs=[])
    return compile_value(graph, compilation_authority=authority)


def approved_environment(vault, tool_permissions: EntityRef) -> EntityRef:
    """The `environment` record of one prepared version whose owner-approved design
    names `tool_permissions` — through the real producers."""

    from app.services.design_store import (
        persist_design_approval,
        persist_environment_head,
        persist_environment_record,
    )
    from app.services.environments import (
        design_approval_subject,
        open_environment,
        prepare_environment_version,
        record_design_approval,
    )
    from app.services.owner_decisions import PersistentOwnerDecisions
    from app.tests.test_design_review import pool_inputs, verdict
    from app.tests.test_environments import approval_value

    domain = vault.app.state.domain_store
    decisions = PersistentOwnerDecisions(domain, vault.app.state.owner_authority)
    environment = str(uuid4())
    _request, candidate, _three, _duplicate = pool_inputs()
    value = approval_value(candidate, verdict(candidate), environment=environment,
                           tool_permissions=tool_permissions.as_dict(), approval=None)
    value.pop("approval")
    decision = decisions.record(vault.request, {
        "schema_version": "owner-decision-command-v1", "command_id": str(uuid4()),
        "subject_kind": "design_approval", "subject": design_approval_subject(value), "decision": "approve"})
    approval = record_design_approval({**value, "approval": decision})
    state = open_environment(environment)
    version, state2 = prepare_environment_version(state, approval, expected_head=state.head)
    roots = domain.roots()
    headers = {"actor_ref": roots.actor, "access_policy_ref": roots.access_policy,
               "retention_policy_ref": roots.retention_policy, "created_at_utc": decision.decided_at_utc}
    approval_ref = persist_design_approval(domain, approval, decisions=decisions, **headers)
    head = persist_environment_head(domain, version, state2, parent_ref=None, approval_ref=approval_ref, **headers)
    return persist_environment_record(domain, version, head_ref=head, **headers)


def granted_run(vault, *, tool="browser_read", command=None, approved=None):
    """One run authorized for `tool` by the owner's grant record. `approved` overrides the
    grant the design approval names (a run approved for another grant)."""

    from app.domain.permissions import Grant, Principal
    from app.domain.schemas import Actor
    from app.runtime.budgets import BudgetBook, BudgetPolicy
    from app.runtime.ledger import OwnerIdentity, RunSpec, RuntimeLedger
    from app.services.browser_grants import PersistentBrowserGrants
    from app.tests.test_runtime_budget_dispatch import identifier, immutable

    app = vault.app
    domain = app.state.domain_store
    grants = PersistentBrowserGrants(domain, app.state.owner_authority)
    view = grants.create(vault.request, command or grant_command())
    grant_ref = EntityRef.from_dict(view["ref"])
    environment = approved_environment(vault, approved or grant_ref)
    roots = domain.roots()
    policy = BudgetPolicy.create(
        profile="execution", provider_mode="subscription", max_model_calls=3, max_tool_calls=5, max_node_visits=7,
        max_loop_rounds=2, max_output_bytes=9 * 1024 * 1024, max_concurrency=2, max_wall_seconds=60,
        max_candidates=1)
    refs = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"), environment=environment,
        consent=immutable(domain, roots, "run_consent"),
        budget=immutable(domain, roots, "budget_policy", content=policy.domain_content()),
        manifest=immutable(domain, roots, "run_manifest"), envelope=immutable(domain, roots, "execution_envelope"),
        profile=immutable(domain, roots, "runtime_profile"), result=immutable(domain, roots, "artifact"))
    # the same clocks the in-thread dispatch fixtures use (test_runtime_budget_dispatch.opened)
    book, ledger = BudgetBook(app.state.store, clock=lambda: 100), RuntimeLedger(domain, clock_ms=lambda: 1_000)
    ledger.reconcile_startup(identifier(), observed_owners={})
    budget_session_id = identifier()
    book.start(budget_session_id, policy)
    principal = Principal(identifier(), Actor(identifier(), "test_actor", "test_fixture"), "runtime", "operational",
                          10_000)
    permission = Grant(identifier(), identifier(), principal.id, refs.envelope, "read", "operational", None, 10_000, 1)
    run = RunSpec(identifier(), refs.work, refs.environment, refs.consent, "live", refs.budget, budget_session_id,
                  refs.manifest)
    ledger.create_run(identifier(), run)
    subject = SimpleNamespace(legacy=app.state.store, domain=domain, refs=refs, policy=policy, book=book,
                              ledger=ledger, principal=principal, grant=permission,
                              owner=OwnerIdentity(identifier(), 4321, 900, identifier()))
    subject.compiled = compiled_with_grant(tool, grant_ref)
    return SimpleNamespace(subject=subject, run=run, grants=grants, grant_ref=grant_ref, view=view,
                           environment=environment)


def dispatch(granted, transport):
    """The compiled graph through the real `NodeAttemptDispatcher` and the scheduler."""

    from app.runtime import node_attempts as na
    from app.tests.test_scheduler_attempt_dispatch import build, handlers

    subject = granted.subject
    dispatcher = na.NodeAttemptDispatcher.build(
        ledger=subject.ledger, budget_book=subject.book, owner=subject.owner,
        bindings={"writer": na.AttemptBinding.create(
            envelope_ref=subject.refs.envelope, profile_ref=subject.refs.profile,
            budget_policy_ref=subject.refs.budget, deadline_at_ms=60_000, lease_duration_ms=60_000,
            model_calls=1, tool_calls=1, node_visits=1, loop_rounds=0, output_bytes=transport.output_bytes_bound,
            candidates=0, api_microunits=None, principal=subject.principal, grant=subject.grant)},
        transport=transport)
    return build(subject, granted.run, dispatcher, handlers(subject, []), compiled=subject.compiled).run()


def revoke(vault, granted):
    return granted.grants.revoke(vault.request, granted.grant_ref.id, {
        "schema_version": "browser-grant-revocation-command-v1", "command_id": str(uuid4())})


def summary(value) -> str:
    return json.dumps(value, sort_keys=True, default=str)
