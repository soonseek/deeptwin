"""Synthetic domain/worker prerequisites; authentication always comes from HTTP."""
import time
from types import SimpleNamespace
from uuid import uuid4

from app.api.routes import ResolvedDispatch
from app.api.transaction import DispatchAuthorization
from app.domain.schemas import Actor
from app.runtime.budgets import BudgetDispatchRequest, BudgetPolicy
from app.runtime.ledger import AttemptSpec, ExecutionSpec, OwnerIdentity, RunSpec
from app.tests.test_api_command_transaction import command_payload
from app.tests.test_server_api_v1 import immutable


def runtime_context(application, session, *, profile_record=None):
    api = application.state.api_v1
    domain, host, ledger = api.domain_store, api.permission_host, api.runtime_ledger
    now = int(time.time())
    human = host.bind_human(session, expires_at=now + 900)
    runtime = host.bind_runtime(Actor(str(uuid4()), "provider", "model_output"), purpose="operational", expires_at=now + 800)
    roots = domain.roots()
    policy = BudgetPolicy.create(profile="execution", provider_mode="subscription", max_model_calls=2,
        max_tool_calls=2, max_node_visits=3, max_loop_rounds=1, max_output_bytes=1024,
        max_concurrency=1, max_wall_seconds=60, max_candidates=1)
    records = SimpleNamespace(
        work=immutable(domain, roots, "work_revision"), environment=immutable(domain, roots, "environment"),
        consent=immutable(domain, roots, "run_consent"), budget=immutable(domain, roots, "budget_policy", content=policy.domain_content()),
        manifest=immutable(domain, roots, "run_manifest"), envelope=immutable(domain, roots, "execution_envelope"),
        profile=profile_record or immutable(domain, roots, "runtime_profile"))
    for record in vars(records).values():
        host.register_record(record)
    grant = host.grant(human, runtime, records.envelope.ref, action="read", purpose="operational", expires_at=now + 700)
    budget_id = str(uuid4())
    api.budget_book.start(budget_id, policy)
    run = RunSpec(str(uuid4()), records.work.ref, records.environment.ref, records.consent.ref, "live",
                  records.budget.ref, budget_id, records.manifest.ref)
    ledger.create_run(str(uuid4()), run)
    execution = ExecutionSpec(str(uuid4()), run.run_id, "writer", str(uuid4()), (0,), ())
    ledger.create_execution(str(uuid4()), execution)
    owner = OwnerIdentity(str(uuid4()), 4321, 900, str(uuid4()))
    attempt = AttemptSpec(str(uuid4()), execution.execution_id, 1, records.envelope.ref, records.profile.ref,
        records.budget.ref, str(uuid4()), "effect:" + str(uuid4()), owner, time.time_ns() // 1000000 + 60000)
    before = ledger.reserve_attempt(str(uuid4()), attempt, lease_duration_ms=30000)
    budget_request = BudgetDispatchRequest.create(session_id=budget_id, request_id=attempt.reservation_id,
        policy_ref=records.budget.ref, model_calls=1, tool_calls=0, node_visits=1, loop_rounds=0,
        output_bytes=100, candidates=0, api_microunits=None)
    state = SimpleNamespace(records=records, attempt=attempt, owner=owner, grant=grant, before=before,
                            budget_request=budget_request, runtime=runtime, human=human)
    state.body = command_payload(state)
    state.resolved = ResolvedDispatch(DispatchAuthorization(principal=runtime, grants=(grant,),
        resource_ref=records.envelope.ref, action="read", purpose="operational", episode_id=None),
        attempt.attempt_id, owner, budget_request, records.profile.ref)
    return state
