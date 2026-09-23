# Extension authoring (draft)

Date: 2026-09-23 · Status: **draft for T084; the extension framework (T087) is not complete and
the installable extension-author SDK is not yet provided.** Normative sources: ADR-014 in
`specs/001-autonomous-release/decisions.md`, `contracts/extension-ports.md`,
`contracts/extension-candidates.md`, `contracts/operations.md` §8 and `contracts/runtime.md` §6.

This page tells a prospective extension author what the contract will require and what exists
today. It is not an invitation to install third-party code into a running instance: no path for that
exists yet.

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
| Candidate registration (inert metadata) | `POST /api/v1/extensions/candidates`, `GET …/{candidate_id}` | implemented; creates no channel, grant, installation, binding or dispatch |
| Provider conformance / installation records | `/api/v1/extensions/provider-conformance`, `/api/v1/extensions/provider-installation` | implemented slices for provider path |
| Port schema artifacts | `schemas/v1/extensions/ports/` | generated; qualification open |
| Tool path in the extension worker | `app/workers/extension_probe.py`, `app/runtime/extension_attempt_transport.py`, `app/runtime/tools.py` | two code-owned tools (`text_profile`, `text_normalize`) over the bounded artifact stream; not a third-party path |
| Historical extension kit | `sdk/python/deeptwin_ext/` | source checkpoint for `extension-manifest-v1`; no packaging metadata; **not** the SDK |
| Examples | `examples/extensions/code_free_lens`, `examples/extensions/pure_text_tool` | inert historical shapes; the tool example is explicitly not a conforming runnable extension |
| `Settings > Extensions` UI | — | not yet provided in the supported browser shell |
| Installable `deeptwin_ext` SDK | — | not yet provided (T087) |
| Out-of-tree conformance fixture | — | not yet provided; will not be bundled into the core release |

## 7. Licensing of extensions

An extension's licence is its author's choice and is recorded as unverified metadata. The example
manifests declare `Apache-2.0` (tool) and `CC0-1.0` (lens) in their own `license_expression`
fields; those declarations cover only the example files as authored and have **not** been approved
or reviewed, and they do not license the DeepTwin repository. The core's own licence is undecided
([license-recommendation.md](license-recommendation.md)).
