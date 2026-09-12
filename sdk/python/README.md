# DeepTwin Python extension kit — historical source-tree checkpoint

This dependency-free source directory constructs the historical `extension-manifest-v1` data and
shared worker **transport** messages. It has no packaging metadata and is not yet the separately
installable extension-author SDK required by ADR-014/T087. The generic envelope is not a semantic
SPI: the DeepTwin core must provide a closed kind/artifact/port/trust/staging matrix plus per-kind
operation, schema, effect, idempotency, cancellation, outcome and artifact contracts.

Importing `deeptwin_ext` has no discovery or registration side effect. A worker is launched only
after an external deployment operator stages an exact digest-pinned OCI service/descriptor and the
framework verifies its signed receipt, handshake and qualification. Applications must not import
an executable extension package inside the web control-plane process. Code-free definitions alone
may use bounded owner import.

T087 must deliver two separate installable distributions: `deeptwin_ext` for extension manifests,
permitted refinement schemas and read-only hash-equal bindings to the core-owned
`extension-ports-v1` schemas, and `deeptwin_client` for HTTP/OpenAPI automation. `deeptwin_ext`
never authors or registers a core port contract. The latter package is not present in this
checkpoint and must prove parity from a separate process that cannot import `app` against the actual
server. Until then this directory is compatibility evidence only, not SDK/framework completion.
