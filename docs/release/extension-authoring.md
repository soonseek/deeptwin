# Extension authoring (draft)

Date: 2026-09-23 · Updated: 2026-09-25 · Status: **draft for T084; the extension framework (T087)
is not complete and the installable extension-author SDK is not yet provided.** Normative sources: ADR-014 in
`specs/001-autonomous-release/decisions.md`, `contracts/extension-ports.md`,
`contracts/extension-candidates.md`, `contracts/operations.md` §8 and `contracts/runtime.md` §6.

This page tells a prospective extension author what the contract will require and what exists
today. It is not an invitation to install third-party code into a running instance: the only
staging, qualification and binding path that exists is the provider port's, and it has been
exercised only with synthetic, test-owned release trees.

## 1. Principles

- **The core owns the semantics.** Each extension binds to exactly one core-owned semantic port.
  The core defines the port's operations, config/request/result/error shapes, authority, effect,
  idempotency, cancellation, terminal states and artifact rules. An author writes a manifest and
  permitted refinements only; an extension can never publish a replacement base schema or widen an
  operation, error, authority or effect.
- **The worker envelope is transport, not an SPI.** The authenticated envelope carries identity,
  size, deadline, cancel and references. Meaning comes from the port.
- **Nothing runs because it was discovered.** Cloning, uploading, opening or registering an
  extension imports no code, installs nothing and grants no permission. Invocation requires an
  operator-staged service, a verified signed receipt, a real handshake, qualification, an exact scope
  binding and the isolated runtime broker.
- **The product has no container authority.** It never downloads images or code, never uses a
  Docker socket and never rebuilds the core image for an extension.

## 2. Trust tiers

| Tier | Examples | Who installs | How it runs |
| --- | --- | --- | --- |
| `deployment_trusted` | storage, secret storage | deployment operator only | fixed core adapter |
| `runtime_worker` | provider, model runtime, tool, artifact codec, executable evaluator, export sink | deployment operator stages an OCI service | isolated worker reached through the broker |
| `definition_package` | lens and evaluator **definitions** with no executable code | authenticated owner, bounded import | schema-validated data |
| `managed_provider_runner` | built-in official-subscription provider runner | part of the core deployment | own auth volume, own egress, no Docker/vault/work-DB access |

## 3. Semantic ports

The closed port set has 11 ports, each with four schemas under
`schemas/v1/extensions/ports/<port>/{config,request,result,error}.schema.json` (44 artifacts):

`provider-port-v1`, `managed-provider-runner-port-v1`, `model-runtime-port-v1`, `tool-port-v1`,
`artifact-codec-port-v1`, `lens-definition-port-v1`, `evaluator-definition-port-v1`,
`evaluator-runtime-port-v1`, `export-sink-port-v1`, `storage-port-v1`, `credential-vault-port-v1`.

Schema identifiers use the `https://deeptwin.local/schemas/v1/extensions/ports/…` namespace; this
is an identifier, not a fetchable URL. The generated files exist in the repository; their full
qualification (operation × terminal × artifact matrices) is T087 work and is not complete.

## 4. What an executable extension must supply (target contract)

1. **`extension-manifest-v2`**: identity, numeric version, extension kind, exact port contract
   version, an artifact reference that points to the service descriptor digest, inert source
   locator and provenance/licence/SBOM references. The manifest points to the descriptor; the
   descriptor never points back.
2. **`extension-service-descriptor-v1`**: one OCI index descriptor and a closed per-platform list
   of manifest/config/ordered-layer media types, digests and sizes; entrypoint and protocol; UID,
   resources, isolation, network, secret and broker endpoint declarations; the exact dedicated
   socket and named-volume mounts. No mutable tags, host paths, post-start mounts or runtime
   downloads.
3. **Operator staging**: the deployment operator creates the service from the descriptor, selecting
   exactly one host-platform entry, and returns a signed receipt.
4. **Verification in the product**: receipt check, handshake, qualification against the current
   runtime/framework/platform/port, then an owner-chosen binding in `Settings > Extensions`.

Bindings are keyed by a five-field slot key (port version, target scope, purpose, slot id,
capability selector) that the **server** computes (`POST /api/v1/extensions/binding-slot-keys`).
An extension id is the candidate that occupies a slot, not the key: only candidates for the same key
compete, and other slots or selectors coexist on the same port. Every bind, disable, rollback and
rollback-retention release names the exact head the owner last read and is refused (`409`) with no
write when the head moved. History is immutable; a supersession or disable retains the displaced
active revision for rollback until the owner releases it.

Registration caps (from `extension-candidates.md`): manifest and descriptor ≤ 256 KiB each, support
documents ≤ 64 KiB, total registration ≤ 1 MiB. Source, provenance and licence statements are
stored as **unverified** metadata; registration never means authenticated, available, licence
approved, installed, qualified or executable.

## 5. Code-free definitions

Under the target contract, lens and evaluator definitions without executable code may be imported
by the authenticated owner through a bounded, schema-validated command (the `/extensions` import
route in `contracts/api.md`; not yet mounted in the supported server). Downloaded `SKILL.md` files, plugin code or uploaded
documents are never installed or activated automatically. Skills installed in a developer's tools
are unrelated to product extensions.

## 6. What exists today

| Item | Location | State |
| --- | --- | --- |
| Candidate registration and listing (inert metadata) | `POST /api/v1/extensions/candidates`, `GET …/candidates?limit&after`, `GET …/{candidate_id}` | implemented; creates no channel, grant, installation, binding or dispatch |
| Provider staging request and receipt | `/api/v1/deployment/provider-requests…` (`deployment-prepare-v1`) | implemented for the provider port; the staging itself is the operator's |
| Provider installation (staged revision 1 → verified revision 2) | `/api/v1/extensions/provider-installation`, `GET /api/v1/extensions/installations` | implemented; verification consumes a release evidence bundle |
| Provider conformance over four fixed vectors | `/api/v1/extensions/provider-conformance` | implemented |
| Provider-transport qualification (sealed record adopted by the credential gateway) | `/api/v1/extensions/provider-transport-qualification` | implemented; the only durable qualification record in this server |
| Bindings: slot key, bind, disable, rollback, rollback-retention release, slot and list reads | `extension-bindings-v1` (8 routes), `app/extensions/binding_service.py` | implemented for `provider-port-v1` only; other ports are refused (`qualification_missing`, `selector_unsupported`); no environment version records a binding yet and the dispatch path does not yet read binding heads |
| `Settings > Extensions` UI | `app/static/extensions.mjs` on `settings.html` | shows exactly what the routes above supply and marks the rest "제공되지 않음" |
| Port schema artifacts | `schemas/v1/extensions/ports/` | generated; qualification matrices open |
| Tool path in the extension worker | `app/workers/extension_probe.py`, `app/runtime/extension_attempt_transport.py`, `app/runtime/tools.py` | two code-owned tools (`text_profile`, `text_normalize`) over the bounded artifact stream, with execution-bound approvals; not a third-party path |
| Extension kit package root | `sdk/python/deeptwin_ext/` | `deeptwin-ext` wheel/sdist (in-tree PEP 517 backend) carrying the `extension-manifest-v1` helpers; no port-schema bindings yet, so **not** the complete SDK |
| Examples | `examples/extensions/code_free_lens`, `examples/extensions/pure_text_tool` | inert historical shapes; the tool example is explicitly not a conforming runnable extension |
| Code-free lens/evaluator definition import | — | not yet provided |
| Installable `deeptwin_ext` SDK | — | not yet provided (T087) |
| Out-of-tree conformance fixture | — | not yet provided; will not be bundled into the core release |

Evidence: `evidence/extensions-ui-2026-09-25.md` (synthetic, test actor).

## 7. Licensing of extensions

An extension's licence is its author's choice and is recorded as unverified metadata. The example
manifests declare `Apache-2.0` (tool) and `CC0-1.0` (lens) in their own `license_expression`
fields; those declarations cover only the example files as authored and have **not** been approved
or reviewed, and they do not license the DeepTwin repository. The core's own licence is Apache-2.0
([license-recommendation.md](license-recommendation.md)).
