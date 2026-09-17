# Evidence — Task 24 step (f): the owner-session consume route and prepare-api-v3

- Date: 2026-09-18
- Task: Task 24 redraft step (f) "route + prepare-api-v3" —
  `contracts/deployment-receipt-journal-v3.md` §6 (route identity, auth policy and scope, the
  consume body, the frozen 200 body, GET/HEAD fields, error partition) by way of journal v2 §11
  (extend the same contribution descriptor; the shared bounded WebBoundary parsing; the route
  binds the request id again inside the service; frozen unprefixed replies; HEAD equivalence).
  Builds on (e2b) the service transaction.

## Frozen identities

```
b04470cbbe39d19efa561dde6fb4c10bd434a2b0b97780b505575f249e91c6db  app/api/deployment_prepare.py
dd4ca4d4063d6d336aa1720121716b7a38a8b2de75504e144de86d3dcd544c57  app/api/route_contributions/deployment-prepare-v1.json
d408859b176f62b5c2305c8ac8a3c5dbe856f395e3112807562b4d83e0b70ce4  app/tests/test_deployment_consume_api.py
83a8fe70b9caeb28f475eb3ce6d5cc50159d0c668da95928d4f83c9144f67fa1  app/tests/test_deployment_consume.py
dce11ddee628ac86fe1ecbf58f82a3324ed664fb2930faf4b717a4299cf45504  app/tests/test_web_owner_integration.py
10ebd3d0522496c38d14a55f39f86d472a04e2bafa6a3b6e8eedd046ca729588  app/tests/test_first_party.py
```

## What was built

- `app/api/deployment_prepare.py`: `preflight` admits the `consume` suffix (POST only; the same
  4096 B / depth 4 / items 32 / members 8 / string 256 limits and no query; required
  `command_id`, `request_digest`, `receipt_digest`, `expected_revision`; parsed by
  `parse_consume`, which pins `expected_revision` to 2 at the boundary); the router adds
  `POST /api/v1/deployment/requests/{request_id}/consume` → `service.consume_receipt`, returning
  the frozen consume reply without link projection; the read route already serves the v3 body.
- `app/api/route_contributions/deployment-prepare-v1.json`: the route
  `deployment.requests.consume` (POST, `browser_session`, `deployment.manage`) added to the same
  contribution; the web composition pin (15 routes, the id tuple) updated.
- Test infrastructure: `StagedWorker(fixture, profile, monkeypatch)` takes any source fixture
  and profile, so the HTTP suite runs the actual in-process staged worker on the HTTP fixture's
  slot (the HTTP and service fixtures share the same instance id); the first-party composition
  test's route count (installed routes plus its example contribution) moves 15 → 16.

## Review (independent, adversarial) and closures

Verdict: ACCEPT WITH CHANGES (no MUST). The reviewer probed the live status partition of the
route with a scratch client (GET/HEAD/PUT 400 before auth; oversize by length or streamed 413;
query, revision 1 or 3, extra member, a body `request_id`, non-JSON, text/plain, a longer path
400; cookie without transport headers 403; no cookie 401; authenticated unknown id 404),
confirmed the preflight limits and the body filtering (a body `request_id` cannot ride in), the
descriptor entry against the contribution schema and the composition order, the frozen
unprefixed reply bytes, that `links_schema` is meaningfully strict, and that the
`StagedWorker` refactor changed no behaviour. Closures:

1. SHOULD — the "unauthenticated" case still carried the session cookie and was refused by the
   transport gate (403) before authentication → the cookie is cleared with the transport
   headers present: 401 `unauthenticated`, then 404 `not_found` once authenticated.
2. SHOULD — the oversize expectation admitted 400 → pinned to the transport gate's 413.
3. NIT — an unused `instance_id` parameter and an evidence claim about it → dropped and the
   claim corrected (the fixtures share the instance id).
4. NIT — HEAD equivalence compares the same seven headers as the receipts precedent.
5. NIT — the docstring cited a v3 section that does not exist → corrected.
6. NIT — the first-party route-count adaptation is named in this evidence.
7. NIT — the handler duplicates the import handler's shape; kept in the precedent style.

## Verification

- TDD: RED retained — the preflight refused the `consume` suffix (400 invalid_input) before the
  route existed; GREEN after the preflight, the endpoint and the descriptor entry.
- Tests (9): the owner consume route commits accepted3 through HTTP against the actual staged
  worker and returns the frozen canonical body (validated against the consume reply and api
  schemas); GET/HEAD show the accepted head with the installation summary (validated against
  `prepare-api-v3`), HEAD equals GET's headers with an empty body; exact replay returns
  identical bytes; a fresh consume of the accepted head is 409; the composition carries the
  route id; seven closed shapes (query, revision 1, missing receipt digest, extra member, GET,
  oversize, non-JSON) are refused before the service with no observation and the head untouched;
  an unknown request is 404 only after authentication.
- Covering (consume API, web owner integration, first party, receipt API, prepare API):
  **167 passed, 2 failed** on the first run — the first-party composition test counts the
  installed routes plus its example contribution (15 → 16, adapted), and a GET on `/consume` is
  closed by the preflight as 400 exactly like the receipts route (the test's expectation pinned
  to 400); re-run: consume API, first party and the consume service suite **45 passed**. Ruff
  clean.
- After the closures: consume API **9 passed**; Ruff clean.
- Full regression: recorded in `resumption-2026-09-15.md` for this iteration.

## Boundaries kept

- No discovery/list/import-all route; the contribution id is unchanged; no reconcile or startup
  change; no GUI (UX-AC11 open); the live container/socket/worker run stays a host gate.
