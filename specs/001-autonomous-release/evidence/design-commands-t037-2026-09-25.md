# Design workspace: pool, side-by-side comparison and select/edit/merge/review/prepare (T037, 2026-09-25)

Status: **the owner can compare pooled candidates of a persisted design request side by side,
focus one node on both sides with its model and tool bindings, and act on them through owner
routes: select / edit / merge persist a new design version that requires re-review and
inherits no verdict; review runs only through a configured critic turn; prepare attempts the
approval and preparation and shows the exact refusal.** T037's text is met for the surfaces it
names, over TEST-ACTOR data. It is **not ticked**, because no production path produces or
registers a design request yet (see Open), so the commands have never acted on a real design.

## What landed

- **`design-workspace-v1`** (installed routes 78 → 83; `app/api/design_workspace.py`,
  `app/api/route_contributions/design-workspace-v1.json`, the first-party catalog, and the
  shared `/api/v1` preflight in `app/api/routes.py`):
  - `GET|HEAD /api/v1/design-requests` (`work.read`): the requests this instance serves.
  - `GET|HEAD /api/v1/design-requests/{request_id}` (`work.read`): the honest pool.
  - `POST …/derivations` (`work.command`): `design-derivation-command-v1`
    `{action: select|edit|merge, parent_candidate_ids, instruction}`.
  - `POST …/reviews` (`work.command`): `design-review-command-v1 {derivation_id}`.
  - `POST …/preparations` (`work.command`): `design-prepare-command-v1 {candidate_id}`.
  - Bodies are admitted exactly before auth. Commands are CSRF-verified owner acts, re-checked
    against the live session (`_authenticate_owner`).
  - Refusals carry a closed code plus, where the owner must read it, the exact `reason`:
    `not_approvable` (409), `review_unavailable` (503).
- **`app/services/design_workspace.py` (`PersistentDesignWorkspace`).**
  - **Read back through the issuing gates.** It walks the persisted chain by its stored
    edges: request → generation calls → candidates → graph and criticism. Every candidate is
    re-admitted by `accept_design_candidates` against the exact issued request and must
    equal its stored record. Every verdict is re-folded by `fold_candidate_criticism` from
    its stored review and chains and must equal the stored verdict. Anything that does not
    reproduce is refused (`unavailable`), never shown.
  - **The pool.** `assemble_selection_pool` gives the presented ids, every exclusion with its
    reason (`structural_duplicate`, `pool_full`, `rejected:…`, `insufficient_evidence:…`;
    an unreviewed candidate is `unreviewed`), the real count, and whether supplementation is
    available.
  - **Verdicts are labelled as recorded.** Each verdict is `source: persisted_criticism`
    with the critic's model ids, profile digests and call count taken from the persisted
    criticism call records.
  - **Derive.** `derive_design_version` issues the act. It persists as one immutable
    `design_derivation` decision record: its id comes from the command id, it is authored
    by the owner's human actor, and it is parented to the exact candidate records. It holds
    `re_review_required: true` and `inherited_verdict: null`.
    - Only a presented candidate can be a parent.
    - An exact replay returns the same record; any other body under the same command is a
      `conflict`.
  - **Review.** It runs `run_candidate_criticism` + `persist_criticism_run` only when the host
    registered a critic model turn (with its model identity and the lens registry) for the
    request. Otherwise it refuses with `review_unavailable` / `critic_model_not_configured`.
    - Only a `select` has a graph to review. It is re-admitted as a new candidate
      (`parent_candidate_refs` = the parent), parented to its derivation, and reviewed from
      scratch.
    - An edit or merge refuses with `derived_graph_not_generated`: no generation turn
      realizes an instruction or a merge yet.
  - **Prepare.** It calls `design_approval_subject` on the exact candidate, its verdict, the
    graph's first model choice, first tool grant and observation contract, and the critic
    qualification. With a subject, it records the owner decision, then
    `record_design_approval` → `persist_design_approval` → `prepare_environment_version`
    (CAS on the resumed head) → `persist_environment_head` + `persist_environment_record`.
    The result is `prepared`, `not_activated`.
    - Any `EnvironmentContractError` is returned verbatim as the `not_approvable` reason.
      A derived version that has not been re-reviewed is refused with `re_review_required`.
  - **The critic qualification.** It is the registered issued value if the host gave one.
    Otherwise it is `unknown_critic_qualification` over a digest of the persisted critic
    configuration (model ids × profile digests): no suite record names it. In production no
    critic can be `qualified` (`V3_VERIFYING_DESIGN_IDS` is empty), so prepare always answers
    `the critic configuration is not qualified (unknown: no_suite_record)`.
- **`app/static/workspace.mjs`** (mounted on the work page as `#design-workspace`; added to
  the asset catalogue):
  - The pool summary with the real count ("… 3개를 채우지 못했습니다. 채워 넣지 않고 실제
    수를 보여 줍니다."), every exclusion with a readable reason, and the critic
    qualification. It states that the verdicts shown are recorded conclusions and not live
    ones.
  - A card per presented candidate: node, agent, model and tool counts, the recorded verdict
    with its critic identity, and the commands (select; edit with an instruction, 4096 bytes
    at most; include in a merge; compare left or right; `이 설계로 준비` with the up-front
    not-approvable reason and the server's exact refusal on click).
  - The side-by-side comparison. Both graphs are drawn in full with `createGraphView`
    (larger node text), `differenceSummary(compareGraphs(...))` lists what differs, and a
    same-node picker shows `focusDifference` on both sides with `nodeDetails` (model binding,
    tools, grants, slots and so on).
  - Derived versions show `재검토 필요 · 원본의 평가·승인은 이어지지 않습니다`, a review
    button disabled with the reason when no critic turn is configured or the version has no
    graph, and preparation only after its own review.
- **`app/static/graph.mjs`.** `differenceSummary`, `unionNodeIds`, and a `title` option on
  `createGraphView`, so the comparison can host two headless views.
- **`app/static/session.mjs`.** A refusal keeps the server's bounded plain-text `reason`.

## TEST-ACTOR data

`app/tests/design_workspace_fixture.py` seeds one request through the real persistence, with
two generation rounds from a scripted `test-actor-generator` and four real criticism runs by
the scripted `test-actor-critic` (`auto_critic` from the orchestration suite):

- two passed, structurally different candidates (presented);
- one rejected with a mandatory review failure;
- one passed structural duplicate.

The page names the critic as `test-actor-critic`, and its qualification shows as `unknown`.
No fixture verdict is presented as live.

The qualified-critic prepare path is exercised only in pytest, under `actor_v3_design()`
(the test-only V3-verifying design id from `test_environments.py`).

## Observed

- `test_design_workspace_api.py`: 5 passed, over the supported app with a real owner session:
  - the pool with its count and reasons, the recorded-verdict labels, HEAD;
  - select, edit and merge with re-review, the refusals, replay and conflict;
  - review unavailable and the exact prepare refusal, with no owner decision recorded;
  - a configured critic re-reviewing a select, plus a TEST-ACTOR-qualified critic preparing
    environment version 1 (`prepared`, `not_activated`);
  - wire and auth closure.
- `workspace.test.mjs`: 6 passed (fake DOM: summary, count, reasons, verdict text,
  side-by-side, focus, commands and their states, refusal text, the reviewed derivation's
  prepare, the empty instance).
- `browser-design-workspace.test.mjs`: 1 passed. In real Chrome against the real server on
  `work.html`:
  - pool: count 2 of 3, 4 candidates, 3 passed; both exclusions with reasons; the
    `test-actor-critic` label; the qualification text;
  - comparison: two drawn graphs (≥ 400 px wide each), the `final-script` contract
    difference, and focus on an agent node showing model and tool lines;
  - prepare: shows `준비하지 않았습니다: the critic configuration is not qualified
    (unknown: no_suite_record)`;
  - select, edit (instruction) and merge (two checked) give three derived versions, all
    `재검토 필요`, with review disabled and its reason. The server holds exactly
    `[edit, merge, select]` with `re_review_required` and a null inherited verdict;
  - no page errors.
- Kept passing: `graph.test.mjs` with all 212 node unit tests, `browser-graph`, and the work
  page's browser cases (`first-use`, `owner-material-intake`, `understanding`, `performance`,
  `first-use-integration-t023`, `records`). The Python design, environment, graph, owner
  integration, first-party, route-count and asset suites pass; route pins are 78 → 83
  (84 with the example contribution).

## Open

- **No production request source.** An issued `DesignGenerationRequest` cannot be rebuilt
  from the store: its design decisions and compilation authority are not persisted. A request
  is served only while the host that generated it has called `open_request`, and after a
  restart a persisted request answers `not_found` until registered again. No production code
  registers one: the design arc (`propose_environment`) is not yet wired to a route or to the
  owner's Claude connection (T038).
- **Review of an edit or merge** needs a generation turn that realizes the instruction or
  merge into a new graph. None exists, and the refusal says so.
- **Preparation is never approvable in production.** V3 is unverified and no qualified critic
  exists (T077). Verdicts do not yet carry the critic configuration digest, so the unknown
  qualification's digest is derived from the persisted call records, not bound by the verdict
  (critic_qualification.py, audit 3 open item).
- The approval's model, tool and observation bindings are the graph's first model choice,
  first tool grant and its observation contract. A multi-binding design approves only those
  three refs, the shape the environments module takes today.
