# Whole-journey verification guide

2026-09-08 · Expected test flow after ADR-009 and ADR-014, not a current runnable product claim.
This is a developer verification guide. DeepTwin targets an open-source web framework release, but
the repository has no approved project license yet; ordinary
users work in its browser UI rather than a native desktop or provider application.

## Safe offline preparation

Use a new temporary test vault and synthetic documents with explicit provenance. Never use
the user's own project files/real inbox as destructive fixtures. Preserve the existing dirty
worktree. Read spec/contracts/tasks before changing a module. Run existing Python and browser
regressions with the pinned project environment; record commands, code version and results.
Set no cloud tracing or provider credentials for offline tests. An empty-credential fresh
checkout must reproduce schemas, permission, lineage, loop and snapshot tests without APIs.

## Seven connected acceptance checkpoints

1. Repeat this checkpoint independently for both mandatory profiles: macOS arm64 Docker Desktop+
   Portainer CE using only the qualified no-terminal operator UI, and Linux amd64 Compose with the
   pinned HTTPS edge/operator TLS secrets. Verify one immutable source/Compose/service-keyed image-
   lock set plus each platform manifest. Claim the first owner through the common offline-bootstrap
   and web setup flow, and open a fresh vault in a supported browser. Records start at
   the first framework-observable deployment/setup event. Enter a synthetic work description,
   upload a mixed-format input set and exercise
   STT with a consented test audio/device. Show extraction omissions and saved revisions.
   On each host, externally stage the same repository-out-of-tree tool OCI service using its exact
   manifest, acyclic service descriptor and signed deployment receipt. Verify the real component
   handshake, semantic tool port, browser `Settings > Extensions`, restart/requalification/binding
   rollback and actual broker invocation without product-side download, Docker authority, dynamic
   mount or core-image rebuild. Exercise A stage → B non-destructive replace; verify immutable A
   binding history and its separate retained rollback head, then use the owner-only exact-head release
   action for every A target. Confirm B's binding/installation heads remain unchanged, A history stays
   readable, and A rollback is rejected. Only then retire superseded A; B dispatch remains unchanged
   and only A's retirement head advances. For current uninstall, use the conformance slot with no
   active-environment refs: disable B, release the retained B target created by that disable, and
   verify all three dependency sets are empty. Then current-uninstall B, verify the exact B uninstall
   tombstone advanced the installation head, and stage C from that tombstone at the next monotonic
   revision; C must handshake, qualify, bind and dispatch without reviving A or B.

   Install and run the HTTP/OpenAPI client only in a separate clean environment against the portable
   HTTPS host, prohibit `app` imports and compare real-server durable receipt/revision/authority/event
   order with the browser path. On local HTTP loopback do not send a real bearer: use a fixed
   non-secret Authorization canary to prove the automation route is not registered or is denied
   before bearer parsing, and confirm it cannot fall back to browser cookie or plaintext bearer.
2. For offline mechanics use an explicitly fixture-labeled transport. Then, under separate bounded
   authorizations and evidence records, run the actual Claude API path and Codex subscription path;
   neither path substitutes for the other. Repeat the core first-use-to-result check on each
   deployment profile without requiring both provider accounts in one run.
   Generate a common work model and genuinely different candidate graphs. Inspect independent
   review and insufficient-candidate behavior. Select/modify/prepare the exact candidate.
3. Run a graph with sequential, parallel and conditional work, a human gate and finite loop.
   Have a framework browser retrieve a controlled public test source and a role create actual
   PDF/table/document/image artifacts. Follow exact artifacts to the consuming role. Cancel,
   restart and inspect old attempts without false completion or duplicate effects.
4. After a real test original exists, use a clearly labeled synthetic actor to create a whole
   and a partial alternative through the GUI. This tests mechanics, not the real user's style
   or learning. Confirm the original, selected scope and downstream impact remain distinct.
5. Trace the difference, system/expert/exception/error alternatives and eligible lens inquiry.
   Freeze questions/predictions before new evidence. Check the H_phi/alternative/heldout
   firewall. Produce typed restore/learn/protect candidates without answer copying.
6. Freeze a baseline/candidate comparison plan with prior-work queue, evaluator/rubric and
   finite budget. Exercise every G-07/08/09 plateau path, including cumulative small gains,
   invalid results and restarts. Keep every round and best candidate. Then freeze candidate,
   use separate validation cases and test exact-version human-approval enforcement/rollback.
   Test-actor approval stays in the test vault and is never real user acceptance.
7. From any stage export a chosen record subset. Inspect exact preview, redactions, missing
   evidence and manifest; verify no secrets or automatic upload. Test encrypted backup into
   an empty staging restore, corruption/key loss, update failure and core-record preservation.

## Evidence gates

- Unit/fixture passes establish only tested deterministic behavior.
- B4 lifecycle/harness/isolation/verifier readiness precedes new scored live evaluation.
- Actual calls use a frozen authorized plan (model/mode/count/deadline/concurrency/cost/data).
  If no applicable authorization exists, do not call paid services; keep independent work moving.
- Real provider/tool/multimodal behavior, semantic critic qualification, lens effects, actual
  user usability and verified fresh-host web-deployment readiness have separate reports and unresolved fields.
- Real user alternatives/approval cannot be manufactured by the development agent. A synthetic
  whole loop is valuable implementation evidence but not proof of that person's improvement.
- Final report lists every FR/SC and its exact evidence scope. Missing mandatory evidence
  remains missing; no broad completion from 729 historical tests or an attractive graph.

## Failure behavior to inspect

Disconnect, key locked/expired, model unavailable, 429/spend cap, unsupported modality, malformed
tool response, renderer failure, disk full, wrong artifact hash, stale approval, malicious URL,
cross-purpose access, duplicate result, premature EOF and unknown remote stop. Each must show
its real affected scope and safe next action, not automatic fallback or a generic green success.

The product's three-round plateau ends an internal tuning series only. It is not a developer
test retry limit, an automatic environment promotion or permission to stop unfinished work.
