# T087 pure extension and alternate-client checkpoint

Date: 2026-09-08  
Status: **historical partial checkpoint; its tests passed, but ADR-014 supersedes its SPI/lifecycle/
SDK completion interpretation and T087 remains open**

## Claim boundary

This checkpoint implements the portion of T087 that the task explicitly permits before the
self-hosted worker broker exists. It does not claim that a discovered extension can run, that the
current server exposes service-client routes, or that the release has qualified a third-party
package. `ExtensionRegistry.prepare_dispatch()` always fails closed with
`RuntimeBoundaryUnavailable`; T018 must provide and qualify the typed isolated broker first.

DeepTwin targets a self-hostable open-source web framework release, but the repository has no
approved project license and is not currently an open-source release. The official browser UI is its
supported first-party product/control surface and reference client. The Python kit and optional HTTPS service
client do not turn a CLI, native launcher, Codex, or Claude application into the product shell.

## Post-checkpoint ADR-014 correction

A later read-only adversarial audit found six framework gaps that these passing tests did not cover:
the generic worker envelope had no kind-specific semantic ports; lifecycle state was process-local
and could not requalify a verified installation after expiry/drift; no executable extension artifact
staging/distribution path existed; the browser had no extension-management contract; the Python
helpers and alternate client were source-tree/in-process rather than installable black-box surfaces;
and the architecture scan was non-recursive and presentation-framework-blind. It also found an
initial manifest↔service-descriptor digest-cycle risk and the need to keep the managed Codex runner's
agent-loop port distinct from a raw provider model-step port.

ADR-014 and the amended canonical contracts/tasks now own the remediation. Everything below remains
true only for the exact pure implementation and test bytes recorded at this checkpoint. “Pass” here
does not qualify the corrected semantic SPI, persistence, staging, browser UI, SDK/client,
out-of-tree execution or dependency architecture.

## Historical implemented evidence and limits

- `app/extensions/` implemented exact immutable value shapes for manifest, scope, installation,
  qualification and binding. It did not implement ADR-014's durable independent lifecycles or
  kind-specific semantic ports. Discovery records inert data and has no import hook, package loader,
  subprocess, network call or callable entrypoint.
- Nine kind names and four trust tiers are closed enums; the kinds were not independently versioned
  semantic port contracts. Storage and credential-vault
  ports require `deployment_trusted` plus a deployment-operator installation action. Runtime code
  likewise cannot be installed by a work, model, browser import or ordinary product-owner action.
- The built-in source label grants nothing. The historical process-local state machine made built-in
  and third-party tools traverse the same discovered → staged → verified → qualified → enabled →
  binding sequence. ADR-014 replaces this conflated sequence with separate durable verified
  installation, qualification and binding histories. The managed-provider tier was limited to a
  built-in provider manifest but did not yet have its corrected distinct agent-loop port.
- Staging, binding, suspension, revocation and removal require an injected trusted authority
  verifier. A caller-supplied role string is not an authority capability. Code-free definitions
  may be staged by the authenticated product owner or deployment operator; executable and
  instance-critical packages remain deployment-operator staged, and instance-critical
  qualifications are instance-scoped only.
- In the historical in-memory coordinator, every mandatory permission/isolation/egress/secret/
  compatibility result had to be `passed`.
  `failed` and `unknown` both prevent qualification, and claimed passing results cannot qualify
  without an injected trusted evidence verifier. Qualification binds exact artifact, manifest,
  immutable installation-record digest, platform, runtime, framework, extension-API, schema,
  declared/observed capability digests, conformance suite/version and scope values. Installation
  revisions form a retained one-way previous-record digest chain. Qualification expires within at
  most seven days; changed artifact/runtime/platform/framework/API/schema/capability state or expiry
  latched the qualification unusable even if the old context later reappeared. The old state machine
  had no reachable same-installation requalification path, so this is fail-closed invalidation
  evidence, not recovery evidence. Exact generic failure codes were retained for every non-passing
  check. The same extension ID/version could not be rediscovered with different manifest bytes.
- A binding cannot add credential handles or grants that its manifest did not declare, and cannot
  omit required ones. A trusted binding verifier must resolve config, opaque credentials and grant
  references against the exact qualification and scope before the enabled lifecycle revision or
  binding event is committed; rejection is atomic and retryable. Active access rechecks those
  references, and a revocation latched the old binding unusable instead of allowing a transient
  verifier recovery to resurrect it. The claimed fresh qualification/binding recovery was not
  reachable for the same verified installation and remains ADR-014/T087 work.
- An export-sink binding never grants transmission. A separate digest-bound target confirmation is
  required, and the current pure descriptor still reports `dispatch_ready: false`.
- Runtime registries now include extension lifecycle and service-client events with closed public
  metadata. User source locators, credentials and arbitrary telemetry cannot be inserted into those
  payloads.
- `schemas/v1/extensions/` exports four deterministic Draft 2020-12 structural schemas. Runtime
  validation remains authoritative for cross-field authority and lifecycle rules.
- The source directory `sdk/python/deeptwin_ext/` is dependency-free and does not import the
  application, but it had no installable distribution metadata and therefore was not yet a shipped
  SDK. Importing the source tree only exposes manifest/message helpers and has no registration side effect. Its canonical JSON,
  identifier/version/schema and cross-field limits match the core; worker messages reject duplicate,
  unknown, missing, oversized and noncanonical inputs, and expose only a closed set of generic
  operations/failure codes without retaining payload-bearing exception causes.
- `examples/extensions/` contains one code-free definition and one pure function example. Their
  manifests point to exact source/provenance bytes; importing the example does not create files or
  register itself.
- `app/services/service_clients.py` creates short-lived scoped bearer credentials through an
  injected authenticated-owner verifier. The secret is shown once, only a digest is retained,
  each credential is capped at 24 hours, rotation invalidates the predecessor, revocation is
  terminal, network profile and expiry are checked, and registry or delivery-adapter denial
  traceback frames are scrubbed of the raw bearer. Validation happens before secret generation,
  collision/error paths scrub generated values, and every rejection records a closed public denial
  reason without recording credentials.
- `app/services/command_clients.py` is presentation-independent. In-process browser and headless
  adapter objects call one policy/engine port and return the same object revision, event and authority
  class for the same ordinary mutation; this was not an HTTP or separately installed client proof.
  Actor provenance remains distinct. Service clients cannot acquire bootstrap,
  human approval, promotion, recovery, deployment, credential or self-management scopes.
  A trusted engine response is still rejected if it changes the requested target, skips the exact
  next revision or names an event absent from the closed domain event registry. Command projections
  are canonicalized on construction, excluded from secret-bearing representations and returned as
  detached deeply immutable values. Principal expiry is checked against an injected monotonic trusted
  clock. Every client, policy, deployment and engine denial must pass through a trusted denial sink;
  a missing or failed sink itself fails closed.
- `app/api/service_clients.py` is an unmounted delivery adapter. It requires a single TLS bearer,
  rejects browser-cookie fallback, and creates only a `service_client` actor. T025 must durably bind
  it to the release session/owner/origin/rate-limit store and mount it through the frozen core-owned
  router-composition seam before routes may be enabled. Specifically, T025 owns
  `app/services/service_clients.py`, `app/services/service_client_auth.py`,
  `app/api/service_clients.py`, `app/api/router_composition.py`, `app/server.py`, migrations and its
  generic seam/auth tests; T087 owns the fixed extension route module/contribution descriptor and
  black-box parity without editing the T025 seam. None was implemented or tested by this historical
  checkpoint.
- A shallow AST check found no API/static imports in top-level Python files then present. It used a
  non-recursive glob and did not reject direct FastAPI/Starlette/Jinja/server presentation imports,
  so it is not ADR-014's recursive architecture proof.

## Verification

Focused command after deterministic schema export:

```text
<workspace>/.venv/bin/python -m pytest -q \
  app/tests/test_extension_spi.py \
  app/tests/test_extension_sdk.py \
  app/tests/test_service_clients.py \
  app/tests/test_client_conformance.py \
  app/tests/test_domain_contracts.py \
  app/tests/test_domain_events.py \
  app/tests/test_domain_permissions.py \
  app/tests/test_domain_schema_exports.py \
  app/tests/test_domain_storage.py \
  app/tests/test_public_events.py

1082 passed; final full-regression evidence is recorded separately
<workspace>/.venv/bin/python -m compileall -q \
  app sdk/python/deeptwin_ext examples/extensions/pure_text_tool
git diff --check
```

The initial tests failed because `app.extensions`, the SDK/examples and the service-client surfaces
did not exist. Each slice was then implemented and rerun. The extension/SDK/example file-set digest
at the first green checkpoint was
`4a662c2303b502033d999194c58221e150f9a6a67f96ea6c1fa3f9e6781d5ad5`; this is a development
fingerprint, not a release signature or qualification.

## Remaining T087 work

1. T087, not T018, owns durable DB/CAS manifest/verified-installation/qualification/binding and
   rollback-retention history,
   heads and atomic public events; startup rehydrate/reconcile and fresh qualification after
   expiry/runtime/platform/framework/API/schema/port/capability changes are required. Binding heads
   use the exact five-field `BindingSlotKeyV1` plus canonical digest across config/record/head/
   command/result/event/retention so different port versions/slots/selectors coexist and only an
   exact byte-identical key competes by expected-head CAS. Displaced bindings gain an exact
   retained eligibility head; rollback consumes it and owner release preserves history while removing
   rollback authority so superseded retirement can reach a zero-dependency state.
2. Implement the closed kind/artifact/port/trust/staging matrix and core-owned per-kind semantic
   operations/schemas/effect/idempotency/cancel/outcome/artifact rules, including the distinct
   `managed-provider-runner-port-v1`. Generate the 44 exact schemas and both all-52 matrices in
   `contracts/extension-ports.md`: result operation×terminal/cardinality and request artifact-input
   profiles (11 non-empty-capable/41 exact-empty). Export prepare/transmit receive the exact ordered
   snapshot/prepared 1–256 `export_payload` bytes only through the T018 bounded stream. SDKs author
   manifests/refinements only. Reject every wrong tuple, ref-only/shared-store export, extra/missing/
   conflicting ref, frozen/export-list mismatch and ToolDefinition widening. Close result artifact
   role/media/omissions/ref metadata, codec/tool equalities and the sole `result.effect` terminal tuple
   truth; error cannot carry a conflicting effect state and unknown effects are never retryable.
   Successful `invoke_tool` output is exactly `{tool_call_ref,result_ref}`; an output-level
   `effect_receipt_ref` or alias fails even if equal, while artifact bindings remain in `result_ref`.
3. Consume acyclic digest-pinned OCI extension-service descriptors only after external operator
   staging through separate exact stage/replace/current-uninstall/superseded-retirement arms, a
   verified one-use signed deployment receipt, exact postcondition and qualification. Strict-
   ancestor retirement follows A→B→release-retention→retire-A, preserves the descendant current
   head, advances a target-keyed retirement head and rechecks binding/rollback/environment
   dependencies. Enforce request→receipt→postcondition
   →record/head→consumption/event order without future refs. T018-foundation owns the authenticated
   isolated broker listener/handshake and bounded artifact stream; it does not persist extension state.
4. T025 supplies the exact durable common web authority/routes described above. T087 adds
   `Settings > Extensions`, code-free import,
   qualified bind/disable/rollback, exact rollback-retention release, and accurate staging/receipt/
   handshake/failure observability.
5. Ship separately installable extension-author and HTTP/OpenAPI client packages. Run the client in
   another process/environment with no `app` import against the actual portable HTTPS server; on
   HTTP loopback use no real bearer and prove pre-parser route denial. Invoke one
   repository-out-of-tree OCI tool through the actual T018 broker.
6. Recursively enforce core dependency direction from all five roots, explicitly including
   `app/extensions/**`, including direct/indirect FastAPI/Starlette/Jinja and server/static/API
   presentation imports and dynamic-import bypasses. T081 packages the resulting extension service contract;
   T078 validates its browser UX and T083 later repeats extension proof on both clean hosts, client
   parity on portable HTTPS and bearer-route denial on HTTP-only loopback.
   All 52 operation×terminal branches also require exact result artifact cardinality, especially
   `artifacts=[]` for cancelled codec, while all 52 request branches enforce their independent input
   profile. Those later distribution tests are not circular prerequisites
   for closing T087 itself. T018-final later consumes semantic integration evidence, while T083 keeps
   the two-clean-host repetition; neither is a reverse prerequisite for T087's staged proof.
