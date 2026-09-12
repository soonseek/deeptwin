# Inert extension examples

These files demonstrate historical manifest/source shapes. Merely cloning, uploading, opening, or discovering
this directory must not import `handler.py`, install a package, grant permissions, or enable a
binding. The framework records a manifest as inert data and requires staged verification,
qualification, an exact scope binding, and the isolated runtime broker before any invocation.

`pure_text_tool/handler.py` is not a runnable conforming extension: it has no digest-pinned multi-
platform OCI service descriptor, external operator deployment receipt, semantic `tool-port-v1`
qualification or T018 broker proof. T087 must provide a repository-out-of-tree private conformance
fixture with those artifacts; it is not bundled into the core release. The code-free lens example
may be bounded-imported only after the current schema is migrated to ADR-014's core-owned port
contract and validated by the authenticated browser command path.
