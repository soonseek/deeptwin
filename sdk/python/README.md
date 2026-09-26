# DeepTwin Python distributions (T087, ADR-014)

Two separate, independently versioned PEP 517 package roots:

| Root | Distribution | Import | What it is |
| --- | --- | --- | --- |
| `deeptwin_ext/` | `deeptwin-ext` | `deeptwin_ext` | extension-author kit: `extension-manifest-v1` data and worker-transport messages |
| `deeptwin_client/` | `deeptwin-client` | `deeptwin_client` | HTTPS service client: verified TLS, one bearer credential, no cookie or plaintext mode |

Each root has `pyproject.toml`, `src/<package>/`, its own `LICENSE`/`NOTICE` copies and the
in-tree build backend `_build/deeptwin_build_backend.py` (stdlib only; the project pins no build
tool, and the file is byte-identical in both roots). Neither distribution imports or ships the
DeepTwin core (`app`). Build and install, for example:

    cd sdk/python/deeptwin_client && pip wheel --no-index --no-deps . -w /tmp/dist
    pip install --no-index --no-deps sdk/python/deeptwin_client

The tests `app/tests/test_sdk_package_builds.py`, `test_sdk_package_install.py` and
`test_extension_client_blackbox.py` build both artifacts, install each into a fresh venv and run
the installed code from outside the repository.

Still not the complete SDK/client that ADR-014 requires: `deeptwin_ext` has no read-only,
hash-equal bindings to the core-owned `extension-ports-v1` schemas and no refinement authoring;
the generic envelope is not a semantic SPI. `deeptwin_client` has no bearer route to call yet
(the server mounts only browser-session routes), so browser/client parity is unproven.

Importing `deeptwin_ext` has no discovery or registration side effect. A worker is launched only
after an external deployment operator stages an exact digest-pinned OCI service/descriptor and the
framework verifies its signed receipt, handshake and qualification. Applications must not import
an executable extension package inside the web control-plane process. Code-free definitions alone
may use bounded owner import. `deeptwin_ext` never authors or registers a core port contract.
