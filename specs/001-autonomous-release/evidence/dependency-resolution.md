# T003 dependency resolution evidence — Apple Silicon local RC

> **2026-09-08 superseded by ADR-009.** 아래 macOS/pywebview/py2app 후보 그래프는 역사적
> 조사이며 현재 자체 호스팅 웹 릴리스의 dependency root 또는 지원 플랫폼 선언이 아니다.
> 현재 권위는 T089의 Linux 다중아키텍처 service roots와 lock manifests다.

Date: 2026-09-07 (Asia/Seoul). Status: **partial dependency preparation; T003 remains unchecked**.

This is evidence for the [release plan](../plan.md), [research decisions](../research.md), [packaging design](../packaging-research.md), [sandbox design](../sandbox-research.md), and [T003](../tasks.md). It is **not** the release lock, component manifest, successful installation, native feasibility approval, or RC acceptance.

## 1. Result and authority boundary

The full proposed wheel-only graph failed because pywebview 6.2.1 requires `proxy_tools`, whose only PyPI release is a source archive. Keeping pywebview in the product design, a diagnostic graph without that package resolved 74 wheels; five additional wheels were downloaded without dependency resolution. All **79 wheel files / 85,592,375 bytes** were SHA-256 checked against the matching official PyPI release JSON. This proves artifact identity and the successful subset's dependency/platform selection, not runtime compatibility or completion of the full graph.

Only public source/metadata reads, stdlib ZIP/tar inspection, and the explicitly permitted `pip download` were performed. No package installation, source build/backend execution, imported downloaded code, browser/model/provider execution, credentials, account changes, signing, or services. The wheel files remain in the task-specific directory `/private/tmp/deeptwin-t003-wheels.58ytEM`; this temporary location is evidence material, not an installed runtime or durable release artifact.

Skills used: research for primary-source evidence; ecosystem-primer and langchain-dependencies for native-provider/graph dependency separation; openai-docs for Codex documentation-first verification. The generic skill's cloud tracing/agent-factory suggestions do not supersede this product's local-first/no-automatic-cloud architecture.

## 2. Existing baseline and proposed exact roots

Read-only metadata inspection used `<workspace>/.venv/bin/python -I`: CPython **3.12.13**, stdlib SQLite runtime **3.53.1**, pip **26.2.1**. The host target is **macOS 26.5.1 (25F80), arm64**; supporting older macOS is not established by this research. No project `.venv` was created in the worktree. Existing requirements remain unchanged:

- Runtime direct: FastAPI 0.141.1, Uvicorn 0.52.4, python-docx 1.2.0, Pydantic 2.13.5.
- Development: pytest 9.1.1 and httpx 0.28.1.
- Also already installed by metadata: Starlette 1.6.0, LangGraph 1.2.11, langgraph-checkpoint-sqlite 3.1.1, langchain-core 1.6.2, LangSmith 0.12.2. Installed metadata is not a new-package compatibility test.

Proposed release roots, before the full graph and application tests are accepted:

| Purpose | Exact candidate pins | Evidence / boundary |
|---|---|---|
| Existing HTTP/schema/DOCX | fastapi 0.141.1; starlette 1.6.0; uvicorn 0.52.4; pydantic 2.13.5; python-docx 1.2.0; httpx 0.28.1 | Preserve current baseline. Starlette is explicit because the product directly uses its backend facilities. |
| Claude direct API | anthropic **1.4.0** | Python 3.10+; current SDK uses **httpx2**, not existing httpx. No Claude subscription adapter or SDK hidden retry authority. |
| Graph/checkpoints | langgraph **1.2.11**; langgraph-checkpoint-sqlite **3.1.1** | Preserve observed versions. Explicit compatibility pins langchain-core **1.6.2**, langsmith **0.12.2**; neither tracing activation nor LangChain agent factory is authorized. |
| Browser driver | playwright **1.62.0** | macOS arm64 wheel exists; its Chromium payload is separate and unverified. |
| Native GUI | pywebview **6.2.1** | Wheel exists, but complete closure blocked on proxy_tools source. WKWebView backend; no Qt/CEF extras. |
| macOS GUI/Keychain bindings | pyobjc-core, pyobjc-framework-Cocoa, -Quartz, -WebKit, -Security, -UniformTypeIdentifiers, all **12.2.2** | Six explicit bindings; do not install the entire PyObjC umbrella. Five cp312 universal2 wheels; UniformTypeIdentifiers uses a pure-tag wheel but still needs macOS facilities. |
| PDF/image | pypdf **6.17.0**; pypdfium2 **5.13.0**; Pillow **12.3.0**; reportlab **5.0.1** | Base extras only; binary and font notices matter. |
| GUI transitive pins | bottle **0.13.4**; proxy_tools **0.1.0** | Bottle wheel resolved. proxy_tools source/license reconciliation and wheel build are still required. |

Proposed build/development-only roots: **py2app 0.28.10**, **pytest 9.1.1**, **httpx 0.28.1**, **pip 26.2.1**, **build 1.6.0**, **wheel 0.48.0**, **pyproject-hooks 1.2.0**, **setuptools 84.0.0**. Build tooling is not an end-user CLI requirement and should not be shipped merely because it appears in this combined resolution. py2app's altgraph/modulegraph/macholib are build closure. A production/development split must retain every actual runtime dependency and notice, not just prune by name.

The machine-readable report below contains every downloaded filename, exact official URL, full SHA-256, Requires-Python, declared license, and raw dependency edge. The filenames encode actual wheel tags; universal2 includes arm64 but does not prove successful loading in a signed standalone app.

Primary version/license/platform evidence is each exact [PyPI JSON release endpoint](https://docs.pypi.org/api/json/) named in the report and the downloaded wheel's own METADATA. These pins are observed candidates, not estimates or a promise to use whichever release is latest later.

## 3. Resolution attempts and consequential edges

All download commands used this prefix (no target-environment install):

```sh
<workspace>/.venv/bin/python -I -m pip --isolated download --index-url https://pypi.org/simple --only-binary=:all: --no-cache-dir --dest /private/tmp/deeptwin-t003-wheels.58ytEM
```

Append the exact `attempts[].roots` values from the report: A and B used normal dependency resolution; C additionally used `--no-deps`. The existing native arm64 Python selected platform tags; this was not a cross-platform resolver run.

- **A, exit 1:** full 25-root candidate. `Could not find a version that satisfies the requirement proxy_tools (from pywebview)` / `No matching distribution found for proxy_tools`. There is no full wheels-only success.
- **B, exit 0:** removed only pywebview from the diagnostic input and added bottle 0.13.4 to retain its available dependency; 74 wheels selected. This is an investigative subset, **not** approval to drop the GUI.
- **C, exit 0:** `--no-deps` downloaded pywebview 6.2.1 plus build, wheel, pip, pyproject-hooks (five files). It does not turn A into a resolved whole graph.

| Dependency path | Actual selected closure / implementation consequence |
|---|---|
| anthropic 1.4.0 → httpx2 <3, >=2 | httpx2 **2.12.0** → httpcore2 **2.12.0** / truststore **0.10.4**; separate from httpx **0.28.1** → httpcore **1.0.9**. SDK fake transport/SSE/cancel tests must use the correct stack. The [official Python SDK docs](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python) document httpx2 and the major-version migration. |
| langgraph 1.2.11 → checkpoint/prebuilt/sdk/core | checkpoint **4.2.0**, prebuilt **1.1.0**, sdk **0.4.4**, core **1.6.2**. Transitive prebuilt does not change the choice to compile a product-owned StateGraph. [Official install guidance](https://docs.langchain.com/oss/python/langgraph/install) treats full LangChain as optional. |
| sqlite checkpointer 3.1.1 → aiosqlite / sqlite-vec | aiosqlite **0.22.1**, sqlite-vec **0.1.9** (native arm64 wheel). SQLite extension loading/signing is a native gate; stdlib SQLite 3.53.1 is not a pip `sqlite` dependency. |
| langsmith 0.12.2 + langgraph-sdk 0.4.4 | LangSmith requires websockets >=15; SDK requires >=14,<17; actual resolution selects **16.1.1**, not 17.1 considered earlier by the resolver. No tracing environment variables or automatic telemetry approval. |
| pywebview 6.2.1 → PyObjC + bottle + proxy_tools | Six macOS bindings above; Windows pythonnet and optional Qt/CEF/Gtk extras are inactive. proxy_tools remains a source boundary. |
| playwright 1.62.0 → pyee / greenlet | pyee **13.0.1**, greenlet **3.5.5**; wheel includes a Node driver but not downloaded Chromium. |
| py2app 0.28.10 → altgraph/modulegraph/macholib | **0.17.5 / 0.19.7 / 1.16.4**, modulegraph also pulls setuptools **84.0.0**; packaging **26.3** is shared. Build tools cannot establish native ABI closure through metadata alone. |

No `deepagents`, full `langchain`, provider-wrapper libraries, browser extras, or speech PyPI package are introduced. No Python `age` package is a substitute for the required cryptographic age binary. There is no direct cryptography dependency in this base selection: encrypted-PDF support, pywebview SSL extra, or a future feature needing it requires an explicit separate decision/resolution. Native microphone capture through PyObjC AVFoundation is not yet the chosen implementation; if required, AVFoundation **12.2.2** exists for cp312 universal2 and adds CoreMedia/CoreAudio closure which has **not** been included in these 79 downloads.

## 4. proxy_tools source-only and license boundary

[Official PyPI 0.1.0 metadata](https://pypi.org/pypi/proxy_tools/0.1.0/json) exposes one **2,978-byte** `proxy_tools-0.1.0.tar.gz`, uploaded 2014-05-05, SHA-256:

`ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`

The source archive's bytes were verified in memory against PyPI, without extraction or execution. It has `setup.py`, `setup.cfg`, one 6,409-byte Python module, metadata/README, **no pyproject.toml and no LICENSE file**. Setup declares no runtime dependencies, no compiled extension, Python 2.7/Python 3 classifiers, MIT, and old nose test configuration; no Requires-Python is declared. Setup code was read, but this research does not certify the full module for execution.

The archive does not declare a build backend. With current pip, a setup.py project without build-system metadata uses the documented fallback **setuptools.build_meta:__legacy__**, with setuptools >=40.8.0. Proposed constrained build tooling is setuptools **84.0.0**; that is a test candidate, not a completed build. The old direct setup.py build invocation is not the current pip contract. [pip build-system documentation](https://pip.pypa.io/en/stable/reference/build-system/index.html)

License is **not safely summarized as “MIT verified.”** PyPI/PKG-INFO/setup.py say MIT, whereas the official repository's [LICENSE.txt at db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6](https://github.com/jtushman/proxy_tools/blob/db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6/LICENSE.txt) contains BSD two-condition text naming Armin Ronacher and Jonathan Tushman. Its observed SHA-256 is `a428fb8a2e762af3eb0a6edbbb88e9b42ccfee80fd9b423958bcacf9b9abbfe4`; the repository exposes no tags. Preserve this discrepancy for source/provenance review and required notices; the contemporary master license does not by itself prove which text accompanied the 2014 release.

Next allowed implementation step needs a dedicated disposable build environment, reviewed exact sdist, pinned build tooling, bounded/no-network build, resulting wheel hash/METADATA inspection, source-to-wheel identity and license/notice decision, then **full** graph resolution including pywebview. No source wheel hash can be supplied before that build. Do not omit the dependency, patch it away, silently use an unrelated similarly named package, or fetch an unpinned latest backend.

## 5. Non-PyPI/native component candidates

| Component | Exact identity and evidence | Remaining release proof |
|---|---|---|
| CPython / SQLite | Existing interpreter 3.12.13 / stdlib SQLite runtime 3.53.1 | Standalone framework/source provenance, distribution license, arm64 dynamic dependencies and bundle hashes are not yet captured. Existing uv-linked environment is not a redistributable .app proof. |
| age | **1.3.2**, official `age-v1.3.2-darwin-arm64.tar.gz`; archive SHA and executable member SHAs in report. [Official release](https://github.com/FiloSottile/age/releases/tag/v1.3.2), [BSD-3-Clause source license](https://github.com/FiloSottile/age/blob/v1.3.2/LICENSE). | Retain complete archive license including Go/dependency notices. Package only required age/age-keygen; do not auto-enable bundled plugins. No encryption/decryption process was run. |
| Codex subscription subprocess | Keep existing adapter's **codex-cli 0.144.4** supported-version pin. [Official CLI docs](https://learn.chatgpt.com/docs/cli), [official rust-v0.144.4 release](https://github.com/openai/codex/releases/tag/rust-v0.144.4). API published separate arm64 CLI and full-package archive hashes, both in report. Candidate full package is an upstream closure unit, not a verified extraction. | Neither archive downloaded here. Verify exact members/notices/signatures and executable hash, app-server handshake/cancel/model declarations in a scoped later test. Do not replace CLI with an app-server-only asset or copy another app's internal binary. No auth reads/model call. |
| whisper.cpp | Existing **1.8.7**, commit `48f628a84833905ee4a0658ee6d4a5c915ce1997`, MIT. [Official release](https://github.com/ggml-org/whisper.cpp/releases/tag/v1.8.7). Observed source archive hash recorded. | **No standalone Darwin whisper-cli release asset**: pinned arm64 source build and resulting binary hash needed. XCFramework alternative is universal arm64/x86_64, min macOS 13.3; its hash is not a CLI hash and it is not an unannounced implementation switch. |
| Local multilingual speech weights | `ggml-base.bin`, **147,951,465 bytes**, pinned repository revision and SHA-256 in report, from the upstream [v1.8.7 model documentation](https://github.com/ggml-org/whisper.cpp/blob/v1.8.7/models/README.md) and [pinned model card](https://huggingface.co/ggerganov/whisper.cpp/blob/5359861c739e955e79d9a303bcbc70fb988958b1/README.md). MIT weights/source notice. | SHA is the publisher's LFS pointer, not a local hash of downloaded 147 MB. Need actual file verification and local capture/Korean/interim/final/cancel test. Base.en is not multilingual base. |
| Playwright browser | 1.62.0 wheel's browsers.json fixes **Chromium revision 1234, 151.0.7922.34**, titled **Chrome for Testing**. Chromium/headless-shell each have this revision; select only required payloads explicitly. | No browser archive download/hash yet. Wheel SHA is not browser SHA. Pin actual browser asset/notices, extract closure and prove App Sandbox child inheritance/no direct TCP/UDP/DNS/QUIC; no claim that request routing alone provides containment. |
| Playwright Node driver | Member byte SHA is recorded; package.json requires Node >=20. | Exact bundled Node version was not executed/reported; version and Node/transitive notices must be pinned from verified artifact evidence. “>=20” is not a component version. No Node binary was run. |
| PDFium | pypdfium2 **5.13.0** wheel contains PDFium **153.0.7999.0**, dylib member SHA in report. Binary producer is **bblanchon/pdfium-binaries**, not a claim that Google published this binary. [Binding licensing](https://github.com/pypdfium2-team/pypdfium2/blob/5.13.0/README.md#licensing). | Preserve all 16 relevant bundled license files (PDFium/builder and dependencies). No native load/render test; do not swap in newer PDFium release 8044 just because available. |
| Pillow / ReportLab resources | Pillow 12.3.0 wheel includes 8 native extensions and 18 dylibs with aggregate dependency license text. ReportLab 5.0.1 base wheel has no native binary, but includes font assets. | MIT-CMU/BSD top-level labels do not cover all bundled resources. ReportLab DarkGarden fonts carry GPL-2-or-later with document embedding exception; Vera has its own license. Decide explicit font exclusion or compliant redistribution/notices; this does not imply every output document or whole app is GPL. Approved Korean font source/hash/coverage remains to be recorded. |

The source-model MIT notice is also documented by [OpenAI Whisper's license section](https://github.com/openai/whisper#license). Exact PyPI license labels below are publisher declarations, not a completed third-party-license inventory or legal conclusion.

## 6. Acceptance work still required

1. Review/reconcile proxy_tools source and notices, build one pinned wheel in a dedicated environment, record its hash. Re-resolve the **entire** intended release plus development graph with that wheel, then fresh scoped install, `pip check`, imports and actual application regression tests. Do not mutate the established baseline environment.
2. Split release and build/dev closure, retaining necessary transitive wheels, exact source URLs/hashes and every native/resource notice. Create `app/requirements-release.lock` and `packaging/macos/component-manifest.json` only from this completed evidence. A wheel-only failure cannot be renamed “lock complete.”
3. Native feasibility remains an early gate: standalone py2app/WKWebView launch; XPC sandboxed worker and child inheritance; browser real DOM/screenshot with broker-only mediated content and forbidden network/file/Keychain canaries; pipe lifecycle/cancel/quit and helper process ownership. Metadata cannot establish those security properties.
4. Capture/verify missing Chromium, Codex, whisper-cli/model and Python bundle hashes. Test actual Claude httpx2 fixture semantics/retry disablement, LangGraph persistence/crash/replay with ledger and sqlite-vec loading, document rendering/Korean glyphs, and microphone permissions/offline STT. This research authorizes no paid trial or real credentials.
5. Signed/notarized package, hardened runtime/dylib closure, Gatekeeper acceptance on a clean GUI-only user account, offline first launch, component integrity, update/rollback and quit cleanup remain independent empirical acceptance. No security-policy workarounds or user CLI instructions are an acceptable substitute.

## Machine-readable resolution report

This is the **single JSON fenced block** in this file. Its canonical local report path is `specs/001-autonomous-release/evidence/dependency-resolution.md#machine-readable-resolution-report`. A consumer may extract it with a JSON parser; it is an authored metadata report, **not** a `pip install --report` result. `attempts` preserve the failed/full versus successful/subset distinction; `wheels` contains raw Requires-Dist including inactive markers and extras. Exact final lock derivation must evaluate markers and resolve the missing source wheel, not treat this union as an accepted production lock.

```json
{
  "report_schema": "deeptwin-t003-resolution-v1",
  "observed_date": "2026-09-07",
  "status": "partial_not_release_lock",
  "evidence_path": "specs/001-autonomous-release/evidence/dependency-resolution.md#machine-readable-resolution-report",
  "download_directory": "/private/tmp/deeptwin-t003-wheels.58ytEM",
  "python_executable": "<workspace>/.venv/bin/python",
  "python_version": "3.12.13",
  "python_sqlite_runtime": "3.53.1",
  "platform": "macOS 26.5.1 (25F80) arm64",
  "pip_version": "26.2.1",
  "installed_new_packages": false,
  "executed_downloaded_packages": false,
  "invoked_build_backend": false,
  "downloaded_browser": false,
  "source_index": "https://pypi.org/simple",
  "resolver_options": [
    "--isolated",
    "download",
    "--index-url",
    "https://pypi.org/simple",
    "--only-binary=:all:",
    "--no-cache-dir",
    "--dest",
    "/private/tmp/deeptwin-t003-wheels.58ytEM"
  ],
  "attempts": [
    {
      "id": "A",
      "roots": [
        "fastapi==0.141.1",
        "starlette==1.6.0",
        "uvicorn==0.52.4",
        "python-docx==1.2.0",
        "pydantic==2.13.5",
        "httpx==0.28.1",
        "langgraph==1.2.11",
        "langgraph-checkpoint-sqlite==3.1.1",
        "langchain-core==1.6.2",
        "langsmith==0.12.2",
        "anthropic==1.4.0",
        "playwright==1.62.0",
        "pywebview==6.2.1",
        "pyobjc-core==12.2.2",
        "pyobjc-framework-Cocoa==12.2.2",
        "pyobjc-framework-Quartz==12.2.2",
        "pyobjc-framework-WebKit==12.2.2",
        "pyobjc-framework-Security==12.2.2",
        "pyobjc-framework-UniformTypeIdentifiers==12.2.2",
        "pypdf==6.17.0",
        "pypdfium2==5.13.0",
        "Pillow==12.3.0",
        "reportlab==5.0.1",
        "py2app==0.28.10",
        "pytest==9.1.1"
      ],
      "resolve_dependencies": true,
      "exit_code": 1,
      "status": "failed",
      "error": "No matching distribution found for proxy_tools (from pywebview)"
    },
    {
      "id": "B",
      "roots": [
        "fastapi==0.141.1",
        "starlette==1.6.0",
        "uvicorn==0.52.4",
        "python-docx==1.2.0",
        "pydantic==2.13.5",
        "httpx==0.28.1",
        "langgraph==1.2.11",
        "langgraph-checkpoint-sqlite==3.1.1",
        "langchain-core==1.6.2",
        "langsmith==0.12.2",
        "anthropic==1.4.0",
        "playwright==1.62.0",
        "pyobjc-core==12.2.2",
        "pyobjc-framework-Cocoa==12.2.2",
        "pyobjc-framework-Quartz==12.2.2",
        "pyobjc-framework-WebKit==12.2.2",
        "pyobjc-framework-Security==12.2.2",
        "pyobjc-framework-UniformTypeIdentifiers==12.2.2",
        "pypdf==6.17.0",
        "pypdfium2==5.13.0",
        "Pillow==12.3.0",
        "reportlab==5.0.1",
        "py2app==0.28.10",
        "pytest==9.1.1",
        "bottle==0.13.4"
      ],
      "resolve_dependencies": true,
      "exit_code": 0,
      "status": "resolved_wheels_only_subset",
      "downloaded_wheel_count": 74
    },
    {
      "id": "C",
      "roots": [
        "pywebview==6.2.1",
        "build==1.6.0",
        "wheel==0.48.0",
        "pip==26.2.1",
        "pyproject-hooks==1.2.0"
      ],
      "resolve_dependencies": false,
      "exit_code": 0,
      "status": "download_only_no_deps",
      "downloaded_wheel_count": 5
    }
  ],
  "proposed_release_direct": [
    "fastapi==0.141.1",
    "starlette==1.6.0",
    "uvicorn==0.52.4",
    "python-docx==1.2.0",
    "pydantic==2.13.5",
    "httpx==0.28.1",
    "anthropic==1.4.0",
    "langgraph==1.2.11",
    "langgraph-checkpoint-sqlite==3.1.1",
    "playwright==1.62.0",
    "pywebview==6.2.1",
    "pypdf==6.17.0",
    "pypdfium2==5.13.0",
    "Pillow==12.3.0",
    "reportlab==5.0.1"
  ],
  "proposed_macos_binding_pins": [
    "pyobjc-core==12.2.2",
    "pyobjc-framework-Cocoa==12.2.2",
    "pyobjc-framework-Quartz==12.2.2",
    "pyobjc-framework-WebKit==12.2.2",
    "pyobjc-framework-Security==12.2.2",
    "pyobjc-framework-UniformTypeIdentifiers==12.2.2"
  ],
  "explicit_compatibility_pins": [
    "langchain-core==1.6.2",
    "langsmith==0.12.2",
    "bottle==0.13.4",
    "proxy_tools==0.1.0"
  ],
  "proposed_build_dev_direct": [
    "py2app==0.28.10",
    "pytest==9.1.1",
    "httpx==0.28.1",
    "pip==26.2.1",
    "build==1.6.0",
    "wheel==0.48.0",
    "pyproject-hooks==1.2.0",
    "setuptools==84.0.0"
  ],
  "sdist_blockers": [
    {
      "name": "proxy_tools",
      "version": "0.1.0",
      "filename": "proxy_tools-0.1.0.tar.gz",
      "size": 2978,
      "url": "https://files.pythonhosted.org/packages/f2/cf/77d3e19b7fabd03895caca7857ef51e4c409e0ca6b37ee6e9f7daa50b642/proxy_tools-0.1.0.tar.gz",
      "sha256": "ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010",
      "sha256_verified_from_bytes": true,
      "pypi_match": true,
      "upload_time": "2014-05-05T21:02:24.606594Z",
      "requires_python": null,
      "has_pyproject_toml": false,
      "has_license_file": false,
      "declared_license": "MIT",
      "setup_py_sha256": "2bb5e8e3c91a5cc5768310b67c2da6c7e5942f8d348402b5e9cee2fcce558b5b",
      "package_source_sha256": "d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be",
      "declared_build_backend": null,
      "pip_inferred_backend": "setuptools.build_meta:__legacy__",
      "pip_inferred_build_requires": [
        "setuptools>=40.8.0"
      ],
      "proposed_build_pin": "setuptools==84.0.0",
      "wheel_built": false,
      "wheel_sha256": null,
      "repository_license_commit": "db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6",
      "repository_license_filename": "LICENSE.txt",
      "repository_license_sha256": "a428fb8a2e762af3eb0a6edbbb88e9b42ccfee80fd9b423958bcacf9b9abbfe4",
      "repository_license_observation": "BSD 2-clause text; conflicts with MIT package metadata; no release tags exposed; provenance reconciliation pending"
    }
  ],
  "wheel_count": 79,
  "total_wheel_bytes": 85592375,
  "requires_dist_note": "Raw wheel METADATA, including optional extras and inactive platform markers. Presence in requires_dist_raw is not selection or installation; attempts B/C describe what was resolved.",
  "wheels": [
    {
      "name": "aiosqlite",
      "version": "0.22.1",
      "filename": "aiosqlite-0.22.1-py3-none-any.whl",
      "size": 17405,
      "sha256": "21c002eb13823fad740196c5a2e9d8e62f6243bd9e7e4a1f87fb5e44ecb4fceb",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/00/b7/e3bf5133d697a08128598c8d0abc5e16377b51465a33756de24fa7dee953/aiosqlite-0.22.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/aiosqlite/0.22.1/json",
      "uploaded_at": "2025-12-23T19:25:42.139290Z",
      "requires_python": ">=3.9",
      "declared_license": "License :: OSI Approved :: MIT License",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "attribution==1.8.0 ; extra == \"dev\"",
        "black==25.11.0 ; extra == \"dev\"",
        "build>=1.2 ; extra == \"dev\"",
        "coverage[toml]==7.10.7 ; extra == \"dev\"",
        "flake8==7.3.0 ; extra == \"dev\"",
        "flake8-bugbear==24.12.12 ; extra == \"dev\"",
        "flit==3.12.0 ; extra == \"dev\"",
        "mypy==1.19.0 ; extra == \"dev\"",
        "ufmt==2.8.0 ; extra == \"dev\"",
        "usort==1.0.8.post1 ; extra == \"dev\"",
        "sphinx==8.1.3 ; extra == \"docs\"",
        "sphinx-mdinclude==0.6.2 ; extra == \"docs\""
      ]
    },
    {
      "name": "altgraph",
      "version": "0.17.5",
      "filename": "altgraph-0.17.5-py2.py3-none-any.whl",
      "size": 21228,
      "sha256": "f3a22400bce1b0c701683820ac4f3b159cd301acab067c51c653e06961600597",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/a9/ba/000a1996d4308bc65120167c21241a3b205464a2e0b58deda26ae8ac21d1/altgraph-0.17.5-py2.py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/altgraph/0.17.5/json",
      "uploaded_at": "2025-11-21T20:35:49.444851Z",
      "requires_python": null,
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "annotated-doc",
      "version": "0.0.5",
      "filename": "annotated_doc-0.0.5-py3-none-any.whl",
      "size": 5302,
      "sha256": "117bac03a25ede5df5440e855b32d556049ca169ead221505badf432fed4b101",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/3e/30/e900b21425a860e195f32e37657aa1f7c7f2b1bfb26f03ca209b90933c06/annotated_doc-0.0.5-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/annotated-doc/0.0.5/json",
      "uploaded_at": "2026-07-28T13:50:57.239109Z",
      "requires_python": ">=3.9",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "annotated-types",
      "version": "0.8.0",
      "filename": "annotated_types-0.8.0-py3-none-any.whl",
      "size": 13427,
      "sha256": "f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/99/91/8acff4f5e50511b911bbccb72b8628a49c68ce14148cd9f6431094859a90/annotated_types-0.8.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/annotated-types/0.8.0/json",
      "uploaded_at": "2026-07-23T20:16:12.938651Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "anthropic",
      "version": "1.4.0",
      "filename": "anthropic-1.4.0-py3-none-any.whl",
      "size": 1300390,
      "sha256": "590e85bff75b713a123b03f586d68f02266b5fdc49f70dd75f721ced93a4716c",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/dd/e3/34a88f0e1e854022a352d67f72ca9baa8b952d4541315088411ba2bfbc2a/anthropic-1.4.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/anthropic/1.4.0/json",
      "uploaded_at": "2026-09-04T22:20:33.078534Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "anyio<5,>=3.5.0",
        "docstring-parser<1,>=0.15",
        "httpx2<3,>=2.0.0",
        "jiter<1,>=0.4.0",
        "pydantic<3,>=1.9.0",
        "sniffio<2,>=1",
        "typing-extensions<5,>=4.14",
        "aiohttp<4,>=3.10.0; extra == 'aiohttp'",
        "boto3<2,>=1.28.57; extra == 'aws'",
        "botocore<2,>=1.31.57; extra == 'aws'",
        "boto3<2,>=1.28.57; extra == 'bedrock'",
        "botocore<2,>=1.31.57; extra == 'bedrock'",
        "google-auth[requests]<3,>=2; extra == 'google-cloud'",
        "mcp<3,>=1.0; (python_version >= '3.10') and extra == 'mcp'",
        "google-auth[requests]<3,>=2; extra == 'vertex'",
        "standardwebhooks<2,>=1.0.1; extra == 'webhooks'"
      ]
    },
    {
      "name": "anyio",
      "version": "4.15.1",
      "filename": "anyio-4.15.1-py3-none-any.whl",
      "size": 132079,
      "sha256": "6152fdbbf9a77fdec97731721bebf7c4c44f7c29b424b0065826173efc7ed101",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/12/b8/4bd346e22b28902df4d651910f5242c28d84e4a5c2435ca5c3f797ed7e2e/anyio-4.15.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/anyio/4.15.1/json",
      "uploaded_at": "2026-09-05T10:42:37.923487Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "exceptiongroup>=1.0.2; python_version < \"3.11\"",
        "idna>=2.8",
        "typing_extensions>=4.16.0; python_version < \"3.15\"",
        "trio>=0.32.0; extra == \"trio\""
      ]
    },
    {
      "name": "bottle",
      "version": "0.13.4",
      "filename": "bottle-0.13.4-py2.py3-none-any.whl",
      "size": 103807,
      "sha256": "045684fbd2764eac9cdeb824861d1551d113e8b683d8d26e296898d3dd99a12e",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/83/f6/b55ec74cfe68c6584163faa311503c20b0da4c09883a41e8e00d6726c954/bottle-0.13.4-py2.py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/bottle/0.13.4/json",
      "uploaded_at": "2025-06-15T10:08:57.691845Z",
      "requires_python": null,
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "build",
      "version": "1.6.0",
      "filename": "build-1.6.0-py3-none-any.whl",
      "size": 31187,
      "sha256": "f7aaf1ebbb79178a02ba248bb524f2176b256017e17e8e4bd4289c7b38cc2bad",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/ab/e5/aa1e81b21aea0ce0ba435311837a37d4cb936e7461f9fecac08580073ba9/build-1.6.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/build/1.6.0/json",
      "uploaded_at": "2026-08-27T21:01:14.957317Z",
      "requires_python": ">= 3.10",
      "declared_license": "MIT",
      "download_group": "C_no_deps",
      "requires_dist_raw": [
        "packaging >= 24.0",
        "pyproject_hooks",
        "colorama; os_name == \"nt\"",
        "importlib-metadata >= 4.6; python_full_version < \"3.10.2\"",
        "tomli >= 1.1.0; python_version < \"3.11\"",
        "keyring ; extra == \"keyring\"",
        "uv >= 0.1.18 ; extra == \"uv\"",
        "virtualenv >= 20.36.1 ; extra == \"virtualenv\""
      ]
    },
    {
      "name": "certifi",
      "version": "2026.7.22",
      "filename": "certifi-2026.7.22-py3-none-any.whl",
      "size": 136983,
      "sha256": "62f22742b58a1a33014a2b6b706588a8d7e2a88ae7bd1a6ebe8c992928483775",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/0b/a7/71ac2cff56fec219ed242bb11b8efb69fcc4bec75db06fb7bfe35de520e6/certifi-2026.7.22-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/certifi/2026.7.22/json",
      "uploaded_at": "2026-07-22T03:35:11.276376Z",
      "requires_python": ">=3.7",
      "declared_license": "MPL-2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "charset-normalizer",
      "version": "3.5.1",
      "filename": "charset_normalizer-3.5.1-cp312-cp312-macosx_10_13_universal2.whl",
      "size": 344456,
      "sha256": "5b6d1386bf0096d26d3a863dc0a487a5b4eb9aa93cf5ba69683d29dde6b9d60f",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/30/27/78873dc8b6a56357517b74b6bb9568b80450e7bb4f6ef7e3fa9d22aa0bd7/charset_normalizer-3.5.1-cp312-cp312-macosx_10_13_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/charset-normalizer/3.5.1/json",
      "uploaded_at": "2026-08-15T08:17:10.072179Z",
      "requires_python": ">=3.7",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "click",
      "version": "8.5.0",
      "filename": "click-8.5.0-py3-none-any.whl",
      "size": 125251,
      "sha256": "255bc9599cf7748b4b1a446ccc735421bd08a2ae529a8b88597d3de5664ee360",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/58/50/6c0d534c5f134586a8e1ba4e330569e32f057e33372ae556463212fb4cd3/click-8.5.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/click/8.5.0/json",
      "uploaded_at": "2026-08-26T13:33:12.928043Z",
      "requires_python": ">=3.10",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "distro",
      "version": "1.9.0",
      "filename": "distro-1.9.0-py3-none-any.whl",
      "size": 20277,
      "sha256": "7bffd925d65168f85027d8da9af6bddab658135b840670a223589bc0c8ef02b2",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/12/b3/231ffd4ab1fc9d679809f356cebee130ac7daa00d6d6f3206dd4fd137e9e/distro-1.9.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/distro/1.9.0/json",
      "uploaded_at": "2023-12-24T09:54:30.421191Z",
      "requires_python": ">=3.6",
      "declared_license": "Apache License, Version 2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "docstring_parser",
      "version": "0.18.0",
      "filename": "docstring_parser-0.18.0-py3-none-any.whl",
      "size": 22484,
      "sha256": "b3fcbed555c47d8479be0796ef7e19c2670d428d72e96da63f3a40122860374b",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/a7/5f/ed01f9a3cdffbd5a008556fc7b2a08ddb1cc6ace7effa7340604b1d16699/docstring_parser-0.18.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/docstring_parser/0.18.0/json",
      "uploaded_at": "2026-04-14T04:09:18.638975Z",
      "requires_python": ">=3.8",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pre-commit>=2.16.0; (python_version >= '3.9') and extra == 'dev'",
        "pydoctor>=25.4.0; extra == 'dev'",
        "pytest; extra == 'dev'",
        "pydoctor>=25.4.0; extra == 'docs'",
        "pytest; extra == 'test'"
      ]
    },
    {
      "name": "fastapi",
      "version": "0.141.1",
      "filename": "fastapi-0.141.1-py3-none-any.whl",
      "size": 131954,
      "sha256": "bfb91aa2d334c61cb35ba9a116fc123b3d3df31640b801cf57a7a78ec3f603b3",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/cb/03/10388a42375ee7e4ac9b94eb2c5c569c8b5795e377e701c9ac3ad63de890/fastapi-0.141.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/fastapi/0.141.1/json",
      "uploaded_at": "2026-07-29T17:18:04.364385Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "starlette>=0.46.0",
        "pydantic>=2.9.0",
        "typing-extensions>=4.8.0",
        "typing-inspection>=0.4.2",
        "annotated-doc>=0.0.2",
        "fastapi-cli[standard]>=0.0.32; extra == \"standard\"",
        "fastar>=0.9.0; extra == \"standard\"",
        "httpx<1.0.0,>=0.23.0; extra == \"standard\"",
        "jinja2>=3.1.5; extra == \"standard\"",
        "python-multipart>=0.0.18; extra == \"standard\"",
        "email-validator>=2.0.0; extra == \"standard\"",
        "uvicorn[standard]>=0.12.0; extra == \"standard\"",
        "pydantic-settings>=2.0.0; extra == \"standard\"",
        "pydantic-extra-types>=2.0.0; extra == \"standard\"",
        "fastapi-cli[standard-no-fastapi-cloud-cli]>=0.0.32; extra == \"standard-no-fastapi-cloud-cli\"",
        "httpx<1.0.0,>=0.23.0; extra == \"standard-no-fastapi-cloud-cli\"",
        "jinja2>=3.1.5; extra == \"standard-no-fastapi-cloud-cli\"",
        "python-multipart>=0.0.18; extra == \"standard-no-fastapi-cloud-cli\"",
        "email-validator>=2.0.0; extra == \"standard-no-fastapi-cloud-cli\"",
        "uvicorn[standard]>=0.12.0; extra == \"standard-no-fastapi-cloud-cli\"",
        "pydantic-settings>=2.0.0; extra == \"standard-no-fastapi-cloud-cli\"",
        "pydantic-extra-types>=2.0.0; extra == \"standard-no-fastapi-cloud-cli\"",
        "fastapi-cli[standard]>=0.0.32; extra == \"all\"",
        "httpx<1.0.0,>=0.23.0; extra == \"all\"",
        "jinja2>=3.1.5; extra == \"all\"",
        "python-multipart>=0.0.18; extra == \"all\"",
        "itsdangerous>=1.1.0; extra == \"all\"",
        "pyyaml>=5.3.1; extra == \"all\"",
        "email-validator>=2.0.0; extra == \"all\"",
        "uvicorn[standard]>=0.12.0; extra == \"all\"",
        "pydantic-settings>=2.0.0; extra == \"all\"",
        "pydantic-extra-types>=2.0.0; extra == \"all\""
      ]
    },
    {
      "name": "greenlet",
      "version": "3.5.5",
      "filename": "greenlet-3.5.5-cp312-cp312-macosx_11_0_universal2.whl",
      "size": 295809,
      "sha256": "49520f0c95a48b42cf55414b8e8479beb274ea70431afc33e3f79903c71f4380",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/2e/7e/9ecd0285e3153532ae07aeb88063c43c72b4221cf0d4d123b02f3682e3ff/greenlet-3.5.5-cp312-cp312-macosx_11_0_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/greenlet/3.5.5/json",
      "uploaded_at": "2026-08-10T13:25:34.023923Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT AND PSF-2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "Sphinx; extra == \"docs\"",
        "furo; extra == \"docs\"",
        "objgraph; extra == \"test\"",
        "psutil; extra == \"test\"",
        "setuptools; extra == \"test\""
      ]
    },
    {
      "name": "h11",
      "version": "0.16.0",
      "filename": "h11-0.16.0-py3-none-any.whl",
      "size": 37515,
      "sha256": "63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/04/4b/29cac41a4d98d144bf5f6d33995617b185d14b22401f75ca86f384e87ff1/h11-0.16.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/h11/0.16.0/json",
      "uploaded_at": "2025-04-24T03:35:24.344199Z",
      "requires_python": ">=3.8",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "httpcore",
      "version": "1.0.9",
      "filename": "httpcore-1.0.9-py3-none-any.whl",
      "size": 78784,
      "sha256": "2d400746a40668fc9dec9810239072b40b4484b640a8c38fd654a024c7a1bf55",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/7e/f5/f66802a942d491edb555dd61e3a9961140fd64c90bce1eafd741609d334d/httpcore-1.0.9-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/httpcore/1.0.9/json",
      "uploaded_at": "2025-04-24T22:06:20.566605Z",
      "requires_python": ">=3.8",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "certifi",
        "h11>=0.16",
        "anyio<5.0,>=4.0; extra == 'asyncio'",
        "h2<5,>=3; extra == 'http2'",
        "socksio==1.*; extra == 'socks'",
        "trio<1.0,>=0.22.0; extra == 'trio'"
      ]
    },
    {
      "name": "httpcore2",
      "version": "2.12.0",
      "filename": "httpcore2-2.12.0-py3-none-any.whl",
      "size": 83074,
      "sha256": "7e04258ce01013d7d615e5b910a3b27fac937d7a95038227e79652b4ba3b4ceb",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/d2/74/d370e55600d9bcfa0d9794b0166126d49291a3d2b20c268fc98c453a4948/httpcore2-2.12.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/httpcore2/2.12.0/json",
      "uploaded_at": "2026-08-18T13:22:05.854488Z",
      "requires_python": ">=3.10",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "h11>=0.16",
        "truststore>=0.10",
        "anyio<5.0,>=4.5.0; extra == 'asyncio'",
        "h2<5,>=3; extra == 'http2'",
        "socksio==1.*; extra == 'socks'",
        "trio<1.0,>=0.33.0; extra == 'trio'"
      ]
    },
    {
      "name": "httpx",
      "version": "0.28.1",
      "filename": "httpx-0.28.1-py3-none-any.whl",
      "size": 73517,
      "sha256": "d909fcccc110f8c7faf814ca82a9a4d816bc5a6dbfea25d6591d6985b8ba59ad",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/2a/39/e50c7c3a983047577ee07d2a9e53faf5a69493943ec3f6a384bdc792deb2/httpx-0.28.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/httpx/0.28.1/json",
      "uploaded_at": "2024-12-06T15:37:21.509172Z",
      "requires_python": ">=3.8",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "anyio",
        "certifi",
        "httpcore==1.*",
        "idna",
        "brotli; (platform_python_implementation == 'CPython') and extra == 'brotli'",
        "brotlicffi; (platform_python_implementation != 'CPython') and extra == 'brotli'",
        "click==8.*; extra == 'cli'",
        "pygments==2.*; extra == 'cli'",
        "rich<14,>=10; extra == 'cli'",
        "h2<5,>=3; extra == 'http2'",
        "socksio==1.*; extra == 'socks'",
        "zstandard>=0.18.0; extra == 'zstd'"
      ]
    },
    {
      "name": "httpx2",
      "version": "2.12.0",
      "filename": "httpx2-2.12.0-py3-none-any.whl",
      "size": 95427,
      "sha256": "cc8b6eecb8661c146b8f89a60e97456ee086e91a784ed31ac450c3a9e613dd36",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/c8/95/411ba65569158e862368917aaf56597f3e5fa3b91b0502919638465a08f3/httpx2-2.12.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/httpx2/2.12.0/json",
      "uploaded_at": "2026-08-18T13:22:06.834669Z",
      "requires_python": ">=3.10",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "anyio>=4.10; sys_platform != 'emscripten'",
        "httpcore2==2.12.0; sys_platform != 'emscripten'",
        "httpx2-jsfetch; sys_platform == 'emscripten' and python_version >= '3.12'",
        "idna>=3.18",
        "truststore>=0.10; sys_platform != 'emscripten'",
        "typing-extensions>=4.5.0; python_version < '3.13'",
        "brotli>=1.2.0; (platform_python_implementation == 'CPython') and extra == 'brotli'",
        "brotlicffi>=1.2.0.0; (platform_python_implementation != 'CPython') and extra == 'brotli'",
        "click>=8.4.2; extra == 'cli'",
        "pygments==2.*; extra == 'cli'",
        "rich<16,>=10; extra == 'cli'",
        "h2<5,>=3; extra == 'http2'",
        "socksio==1.*; extra == 'socks'",
        "wsproto>=1.2; extra == 'ws'",
        "backports-zstd>=1.0.0; (python_version <= '3.13') and extra == 'zstd'"
      ]
    },
    {
      "name": "idna",
      "version": "3.19",
      "filename": "idna-3.19-py3-none-any.whl",
      "size": 68550,
      "sha256": "815e7be7a7806d54abb586dc943addc79e8b2ee16915059658cbeff4b1b43bf4",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/57/b0/0e52c878c53f245edd3a11020f20979b3f490f245af532c7cae3027754b5/idna-3.19-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/idna/3.19/json",
      "uploaded_at": "2026-08-18T05:14:22.343598Z",
      "requires_python": ">=3.9",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "ruff >= 0.16.0 ; extra == \"all\"",
        "mypy >= 1.11.2 ; extra == \"all\"",
        "ty >= 0.0.37 ; extra == \"all\"",
        "pytest >= 8.3.2 ; extra == \"all\"",
        "hypothesis >= 6.141.1 ; extra == \"all\"",
        "coverage >= 7.10.0 ; extra == \"all\""
      ]
    },
    {
      "name": "iniconfig",
      "version": "2.3.0",
      "filename": "iniconfig-2.3.0-py3-none-any.whl",
      "size": 7484,
      "sha256": "f631c04d2c48c52b84d0d0549c99ff3859c98df65b3101406327ecc7d53fbf12",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/cb/b1/3846dd7f199d53cb17f49cba7e651e9ce294d8497c8c150530ed11865bb8/iniconfig-2.3.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/iniconfig/2.3.0/json",
      "uploaded_at": "2025-10-18T21:55:41.639305Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "jiter",
      "version": "0.16.0",
      "filename": "jiter-0.16.0-cp312-cp312-macosx_11_0_arm64.whl",
      "size": 307779,
      "sha256": "5af7780e4a26bd7d0d989592bf9ef12ebf806b74ab709223ecca37c749872ea9",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/94/2e/34957c2c1b661c252ba9bcc60ae0bddc27e0f7202c6073326a13c5390eec/jiter-0.16.0-cp312-cp312-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/jiter/0.16.0/json",
      "uploaded_at": "2026-06-29T13:03:15.418591Z",
      "requires_python": ">=3.9",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "jsonpatch",
      "version": "1.33",
      "filename": "jsonpatch-1.33-py2.py3-none-any.whl",
      "size": 12898,
      "sha256": "0ae28c0cd062bbd8b8ecc26d7d164fbbea9652a1a3693f3b956c1eae5145dade",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/73/07/02e16ed01e04a374e644b575638ec7987ae846d25ad97bcc9945a3ee4b0e/jsonpatch-1.33-py2.py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/jsonpatch/1.33/json",
      "uploaded_at": "2023-06-16T21:01:28.466546Z",
      "requires_python": ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*, !=3.4.*, !=3.5.*, !=3.6.*",
      "declared_license": "Modified BSD License",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "jsonpointer (>=1.9)"
      ]
    },
    {
      "name": "jsonpointer",
      "version": "3.1.1",
      "filename": "jsonpointer-3.1.1-py3-none-any.whl",
      "size": 7659,
      "sha256": "8ff8b95779d071ba472cf5bc913028df06031797532f08a7d5b602d8b2a488ca",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/9e/6a/a83720e953b1682d2d109d3c2dbb0bc9bf28cc1cbc205be4ef4be5da709d/jsonpointer-3.1.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/jsonpointer/3.1.1/json",
      "uploaded_at": "2026-03-23T22:32:31.568290Z",
      "requires_python": ">=3.10",
      "declared_license": "Modified BSD License",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "langchain-core",
      "version": "1.6.2",
      "filename": "langchain_core-1.6.2-py3-none-any.whl",
      "size": 571690,
      "sha256": "21e6c7cf097c68b777fd69ea00864f09bd9ca76ac73e3e3fa14e1ee366eb4711",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/a8/62/d3fb7c215cb2f237c3fe84880bf347a38deafef6033b6d5f1339ba8ca401/langchain_core-1.6.2-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langchain-core/1.6.2/json",
      "uploaded_at": "2026-09-04T21:29:21.175804Z",
      "requires_python": "<4.0.0,>=3.10.0",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "httpx<1.0.0,>=0.23.0",
        "jsonpatch<2.0.0,>=1.33.0",
        "langchain-protocol>=0.0.17",
        "langsmith<1.0.0,>=0.3.45",
        "packaging>=23.2.0",
        "pydantic<3.0.0,>=2.7.4",
        "pyyaml<7.0.0,>=5.3.0",
        "tenacity!=8.4.0,<10.0.0,>=8.1.0",
        "typing-extensions<5.0.0,>=4.7.0",
        "uuid-utils<1.0,>=0.12.0"
      ]
    },
    {
      "name": "langchain-protocol",
      "version": "0.0.19",
      "filename": "langchain_protocol-0.0.19-py3-none-any.whl",
      "size": 7327,
      "sha256": "4cdf879a492a35980fd859ae792d3c65458ccaae504e183c9a10d7eac1f0720f",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/80/c9/f6cbf357d48ccbd18bb394433b1fd7ad9be004eed9377ad08bb85777e5e6/langchain_protocol-0.0.19-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langchain-protocol/0.0.19/json",
      "uploaded_at": "2026-08-26T21:11:59.781653Z",
      "requires_python": "<4.0.0,>=3.10.0",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "typing-extensions<5.0.0,>=4.13.0"
      ]
    },
    {
      "name": "langgraph",
      "version": "1.2.11",
      "filename": "langgraph-1.2.11-py3-none-any.whl",
      "size": 248854,
      "sha256": "8bab70de7b2d00b5300fb289bcf38d8b241400f3184c1e95e8ce706fb0e8686b",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/0a/7f/c5c30e4be99ff821029c7ac872a480676bb179c9f3df85ea3f38d13f86d4/langgraph-1.2.11-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langgraph/1.2.11/json",
      "uploaded_at": "2026-08-11T14:00:35.494718Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "langchain-core<2,>=1.4.7",
        "langgraph-checkpoint<5.0.0,>=4.1.0",
        "langgraph-prebuilt<1.2.0,>=1.1.0",
        "langgraph-sdk<0.5.0,>=0.4.2",
        "pydantic>=2.7.4",
        "xxhash>=3.5.0"
      ]
    },
    {
      "name": "langgraph-checkpoint",
      "version": "4.2.0",
      "filename": "langgraph_checkpoint-4.2.0-py3-none-any.whl",
      "size": 56833,
      "sha256": "0547fd228935a0b758865de3a3d6d7a2537c308895d0f9ab092ce9151b5da942",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/05/71/3b475f09bd57d3a5649792c66353312b4432afd843f301739dfcebd157f0/langgraph_checkpoint-4.2.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langgraph-checkpoint/4.2.0/json",
      "uploaded_at": "2026-08-07T20:05:02.655126Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "langchain-core>=0.2.38",
        "ormsgpack>=1.12.0"
      ]
    },
    {
      "name": "langgraph-checkpoint-sqlite",
      "version": "3.1.1",
      "filename": "langgraph_checkpoint_sqlite-3.1.1-py3-none-any.whl",
      "size": 40785,
      "sha256": "8505c54c94a658080525d7e6780fdd4e0c078ff2566b30d399c02cc9f9af1c63",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/f5/b9/e458601a1718337839bcfeec9d1b27b8b16ce135be2bd50ed0395d33a878/langgraph_checkpoint_sqlite-3.1.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langgraph-checkpoint-sqlite/3.1.1/json",
      "uploaded_at": "2026-07-30T19:19:36.424946Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "aiosqlite>=0.20",
        "langgraph-checkpoint<5.0.0,>=4.1.0",
        "sqlite-vec>=0.1.6"
      ]
    },
    {
      "name": "langgraph-prebuilt",
      "version": "1.1.0",
      "filename": "langgraph_prebuilt-1.1.0-py3-none-any.whl",
      "size": 41043,
      "sha256": "51e311747d755b751d5c6b39b0c1446124d3a7643d2515017e6714b323508fc9",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/e9/43/3fe1a700b8490ed02679cdbbc8c915eb23a092faf496c9c1118abcd10be3/langgraph_prebuilt-1.1.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langgraph-prebuilt/1.1.0/json",
      "uploaded_at": "2026-05-12T03:37:48.007261Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "langchain-core>=1.3.1",
        "langgraph-checkpoint<5.0.0,>=2.1.0"
      ]
    },
    {
      "name": "langgraph-sdk",
      "version": "0.4.4",
      "filename": "langgraph_sdk-0.4.4-py3-none-any.whl",
      "size": 162270,
      "sha256": "39afe416c91742925e6f8a93715f566d499b36e1b636b804a4ffe3190e4f4e64",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/43/d5/2ad7f3a835c6fcebf58b6669552536ecd52d2dfe4cf49c6c36648fd83572/langgraph_sdk-0.4.4-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langgraph-sdk/0.4.4/json",
      "uploaded_at": "2026-08-27T21:25:21.072502Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "httpx>=0.25.2",
        "langchain-core<2,>=1.4.0",
        "langchain-protocol>=0.0.15",
        "orjson>=3.11.5",
        "websockets<17,>=14"
      ]
    },
    {
      "name": "langsmith",
      "version": "0.12.2",
      "filename": "langsmith-0.12.2-py3-none-any.whl",
      "size": 760692,
      "sha256": "ca2b6386cf452cf8edebf27c9c476503c18bad895e7ad566578393fa0ba7fea2",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/0a/e1/5c751a0f1a14de49f19a2ebc0f5dfadfaf04a07f245c5f749ec31f263715/langsmith-0.12.2-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/langsmith/0.12.2/json",
      "uploaded_at": "2026-09-05T20:26:18.166848Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "anyio>=3.5.0",
        "distro>=1.7.0",
        "httpx2<3,>=2",
        "orjson>=3.9.14; platform_python_implementation != 'PyPy'",
        "packaging>=23.2",
        "pydantic<3,>=2",
        "requests-toolbelt>=1.0.0",
        "requests>=2.0.0",
        "sniffio>=1.1",
        "typing-extensions>=4.0.0",
        "uuid-utils<1.0,>=0.12.0",
        "websockets>=15.0",
        "xxhash>=3.0.0",
        "zstandard>=0.23.0",
        "claude-agent-sdk>=0.1.0; (python_version >= '3.10') and extra == 'claude-agent-sdk'",
        "google-genai>=1.75; extra == 'gemini-live'",
        "google-adk>=1.0.0; extra == 'google-adk'",
        "wrapt>=1.16.0; extra == 'google-adk'",
        "google-adk>=2.3.0; extra == 'google-adk-live'",
        "langsmith-pyo3>=0.1.0rc2; extra == 'langsmith-pyo3'",
        "cachetools>=5.0.0; extra == 'livekit'",
        "livekit-agents>=1.6; extra == 'livekit'",
        "opentelemetry-api>=1.30.0; extra == 'livekit'",
        "opentelemetry-exporter-otlp-proto-http>=1.30.0; extra == 'livekit'",
        "opentelemetry-sdk>=1.30.0; extra == 'livekit'",
        "openai-agents>=0.0.3; extra == 'openai-agents'",
        "openai-agents>=0.0.3; extra == 'openai-realtime'",
        "openai>=1.50; extra == 'openai-realtime'",
        "opentelemetry-api>=1.30.0; extra == 'otel'",
        "opentelemetry-exporter-otlp-proto-http>=1.30.0; extra == 'otel'",
        "opentelemetry-sdk>=1.30.0; extra == 'otel'",
        "cachetools>=5.0.0; extra == 'pipecat'",
        "opentelemetry-api>=1.30.0; extra == 'pipecat'",
        "opentelemetry-exporter-otlp-proto-http>=1.30.0; extra == 'pipecat'",
        "opentelemetry-sdk>=1.30.0; extra == 'pipecat'",
        "pipecat-ai>=1.0; (python_version >= '3.11') and extra == 'pipecat'",
        "pytest>=7.0.0; extra == 'pytest'",
        "rich>=13.9.4; extra == 'pytest'",
        "vcrpy>=7.0.0; extra == 'pytest'",
        "opentelemetry-api>=1.30.0; extra == 'strands-agents'",
        "opentelemetry-exporter-otlp-proto-http>=1.30.0; extra == 'strands-agents'",
        "opentelemetry-sdk>=1.30.0; extra == 'strands-agents'",
        "strands-agents-tools>=0.2.0; extra == 'strands-agents'",
        "strands-agents>=0.1.0; extra == 'strands-agents'",
        "vcrpy>=7.0.0; extra == 'vcr'"
      ]
    },
    {
      "name": "lxml",
      "version": "6.1.3",
      "filename": "lxml-6.1.3-cp312-cp312-macosx_10_13_universal2.whl",
      "size": 8602094,
      "sha256": "0c0710ac085a157b593c38fbcacd950f15c4afa8e2057527185875ab302752bc",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/dd/1f/a180b57d9eeabaab77f9d5aa30356898ea749c4795596a8f66d1eb6bef2e/lxml-6.1.3-cp312-cp312-macosx_10_13_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/lxml/6.1.3/json",
      "uploaded_at": "2026-09-02T14:47:26.054985Z",
      "requires_python": ">=3.8",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "cssselect>=0.7; extra == \"cssselect\"",
        "html5lib; extra == \"html5\"",
        "BeautifulSoup4; extra == \"htmlsoup\"",
        "lxml_html_clean; extra == \"html-clean\""
      ]
    },
    {
      "name": "macholib",
      "version": "1.16.4",
      "filename": "macholib-1.16.4-py2.py3-none-any.whl",
      "size": 38117,
      "sha256": "da1a3fa8266e30f0ce7e97c6a54eefaae8edd1e5f86f3eb8b95457cae90265ea",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/c7/d1/a9f36f8ecdf0fb7c9b1e78c8d7af12b8c8754e74851ac7b94a8305540fc7/macholib-1.16.4-py2.py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/macholib/1.16.4/json",
      "uploaded_at": "2025-11-22T08:28:36.939302Z",
      "requires_python": null,
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "altgraph >=0.17"
      ]
    },
    {
      "name": "modulegraph",
      "version": "0.19.7",
      "filename": "modulegraph-0.19.7-py2.py3-none-any.whl",
      "size": 35151,
      "sha256": "139f89042c9912777ba4bbf1d5496591c6ad780110ea3082c11e8737cf82cacc",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/f1/c1/3eff0be83439f0408866eaacd4106c9d19b762cba66bcf0d0a523a6f6620/modulegraph-0.19.7-py2.py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/modulegraph/0.19.7/json",
      "uploaded_at": "2025-11-22T08:22:42.239343Z",
      "requires_python": null,
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "altgraph",
        "setuptools"
      ]
    },
    {
      "name": "orjson",
      "version": "3.12.0",
      "filename": "orjson-3.12.0-cp312-cp312-macosx_15_0_arm64.whl",
      "size": 123725,
      "sha256": "11edb4660a6680abee9788a3a9072208a2c96538cc1322bd79542065229d8e54",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/29/98/758cf90fbeaaafb7f8141bfac75a432099959f3a2f5db93a412e876415d8/orjson-3.12.0-cp312-cp312-macosx_15_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/orjson/3.12.0/json",
      "uploaded_at": "2026-08-14T16:12:30.013702Z",
      "requires_python": ">=3.10",
      "declared_license": "MPL-2.0 AND (Apache-2.0 OR MIT)",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "ormsgpack",
      "version": "1.12.2",
      "filename": "ormsgpack-1.12.2-cp312-cp312-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl",
      "size": 378618,
      "sha256": "7a29d09b64b9694b588ff2f80e9826bdceb3a2b91523c5beae1fab27d5c940e7",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/4c/36/16c4b1921c308a92cef3bf6663226ae283395aa0ff6e154f925c32e91ff5/ormsgpack-1.12.2-cp312-cp312-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/ormsgpack/1.12.2/json",
      "uploaded_at": "2026-01-18T20:55:50.835138Z",
      "requires_python": ">=3.10",
      "declared_license": "Apache-2.0 OR MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "packaging",
      "version": "26.3",
      "filename": "packaging-26.3-py3-none-any.whl",
      "size": 129956,
      "sha256": "d7193f7c8e4e93f444fde0262bf90af30e16fa0ad0ad44cb553c87339b23cd1c",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/63/34/ba1c580383c9eada3711951fef0795c80b829a078d72188184bcab9dd527/packaging-26.3-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/packaging/26.3/json",
      "uploaded_at": "2026-08-04T18:15:27.159957Z",
      "requires_python": ">=3.9",
      "declared_license": "Apache-2.0 OR BSD-2-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "pillow",
      "version": "12.3.0",
      "filename": "pillow-12.3.0-cp312-cp312-macosx_11_0_arm64.whl",
      "size": 4780323,
      "sha256": "ffd0c5368496f41b0944be820fcb7a838aa6e623d250b01acf2643939c3f99d7",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/d8/66/9a386a92561f402389a4fc70c18838bf6d35eb5eb5c6850b4b2dc64f5048/pillow-12.3.0-cp312-cp312-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/pillow/12.3.0/json",
      "uploaded_at": "2026-07-01T11:54:09.351673Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT-CMU",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "furo; extra == \"docs\"",
        "olefile; extra == \"docs\"",
        "sphinx>=8.2; extra == \"docs\"",
        "sphinx-autobuild; extra == \"docs\"",
        "sphinx-copybutton; extra == \"docs\"",
        "sphinx-inline-tabs; extra == \"docs\"",
        "sphinxext-opengraph; extra == \"docs\"",
        "olefile; extra == \"fpx\"",
        "olefile; extra == \"mic\"",
        "arro3-compute; extra == \"test-arrow\"",
        "arro3-core; extra == \"test-arrow\"",
        "nanoarrow; extra == \"test-arrow\"",
        "pyarrow; extra == \"test-arrow\"",
        "coverage>=7.4.2; extra == \"tests\"",
        "defusedxml; extra == \"tests\"",
        "markdown2; extra == \"tests\"",
        "olefile; extra == \"tests\"",
        "packaging; extra == \"tests\"",
        "pytest; extra == \"tests\"",
        "pytest-cov; extra == \"tests\"",
        "pytest-timeout; extra == \"tests\"",
        "pytest-xdist; extra == \"tests\"",
        "setuptools; extra == \"tests\"",
        "trove-classifiers>=2024.10.12; extra == \"tests\"",
        "defusedxml; extra == \"xmp\""
      ]
    },
    {
      "name": "pip",
      "version": "26.2.1",
      "filename": "pip-26.2.1-py3-none-any.whl",
      "size": 1816632,
      "sha256": "71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/f3/6e/1736e5b4ae2b778ef2f81c47d797de9f891d4d8acb047a24ca37a60294dd/pip-26.2.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pip/26.2.1/json",
      "uploaded_at": "2026-08-04T22:51:12.472093Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "C_no_deps",
      "requires_dist_raw": []
    },
    {
      "name": "playwright",
      "version": "1.62.0",
      "filename": "playwright-1.62.0-py3-none-macosx_11_0_arm64.whl",
      "size": 42510842,
      "sha256": "db755ab27db21a04186f1fe8169888e42356086e439b1059b923ef417f0b6034",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/af/1a/0bfbe9904350961f4dbb713f04342e40d548c5fc26c8157bd13617c81492/playwright-1.62.0-py3-none-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/playwright/1.62.0/json",
      "uploaded_at": "2026-07-31T17:00:48.596764Z",
      "requires_python": ">=3.10",
      "declared_license": "Apache-2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pyee<14,>=13",
        "greenlet<4.0.0,>=3.1.1"
      ]
    },
    {
      "name": "pluggy",
      "version": "1.6.0",
      "filename": "pluggy-1.6.0-py3-none-any.whl",
      "size": 20538,
      "sha256": "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/54/20/4d324d65cc6d9205fabedc306948156824eb9f0ee1633355a8f7ec5c66bf/pluggy-1.6.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pluggy/1.6.0/json",
      "uploaded_at": "2025-05-15T12:30:06.134003Z",
      "requires_python": ">=3.9",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pre-commit; extra == \"dev\"",
        "tox; extra == \"dev\"",
        "pytest; extra == \"testing\"",
        "pytest-benchmark; extra == \"testing\"",
        "coverage; extra == \"testing\""
      ]
    },
    {
      "name": "py2app",
      "version": "0.28.10",
      "filename": "py2app-0.28.10-py3-none-any.whl",
      "size": 837349,
      "sha256": "bdb0cd2cbfa5160b5b11b8d612f6eb92d484a0282801e85b159f1930cd834714",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/be/d8/a04a88b182613370a262f674929f0e284ea04e1803f2d38fc5639fbec2d7/py2app-0.28.10-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/py2app/0.28.10/json",
      "uploaded_at": "2026-02-13T20:49:59.980439Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT or PSF License",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "altgraph>=0.17.5",
        "modulegraph>=0.19.7",
        "macholib>=1.16.4",
        "packaging"
      ]
    },
    {
      "name": "pydantic",
      "version": "2.13.5",
      "filename": "pydantic-2.13.5-py3-none-any.whl",
      "size": 472589,
      "sha256": "346a034f080da3755d8e9cb5e00e8b07de1d39e4f6e2c87d8ab7cafa0b269a73",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/eb/47/c95ffc2009878c7aac0c5e08528022dcb885933252a88b5f170058014464/pydantic-2.13.5-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pydantic/2.13.5/json",
      "uploaded_at": "2026-08-28T14:03:59.136157Z",
      "requires_python": ">=3.9",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "annotated-types>=0.6.0",
        "pydantic-core==2.46.5",
        "typing-extensions>=4.14.1",
        "typing-inspection>=0.4.2",
        "email-validator>=2.0.0; extra == 'email'",
        "tzdata; (python_version >= '3.9' and platform_system == 'Windows') and extra == 'timezone'"
      ]
    },
    {
      "name": "pydantic_core",
      "version": "2.46.5",
      "filename": "pydantic_core-2.46.5-cp312-cp312-macosx_11_0_arm64.whl",
      "size": 1922874,
      "sha256": "a39ac25a9a2fa4072efdb429833c4a4c8009a51ff9eea3eeae131713cd27991e",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/db/50/26b091836076ce4cb2fac264186936acc069e0595772cfd02a563bc4761a/pydantic_core-2.46.5-cp312-cp312-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/pydantic_core/2.46.5/json",
      "uploaded_at": "2026-08-28T09:58:23.766552Z",
      "requires_python": ">=3.9",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "typing-extensions>=4.14.1"
      ]
    },
    {
      "name": "pyee",
      "version": "13.0.1",
      "filename": "pyee-13.0.1-py3-none-any.whl",
      "size": 15659,
      "sha256": "af2f8fede4171ef667dfded53f96e2ed0d6e6bd7ee3bb46437f77e3b57689228",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/a0/c4/b4d4827c93ef43c01f599ef31453ccc1c132b353284fc6c87d535c233129/pyee-13.0.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyee/13.0.1/json",
      "uploaded_at": "2026-02-14T21:12:26.263088Z",
      "requires_python": ">=3.8",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "typing-extensions",
        "build; extra == \"dev\"",
        "flake8; extra == \"dev\"",
        "flake8-black; extra == \"dev\"",
        "pytest; extra == \"dev\"",
        "pytest-asyncio; python_version >= \"3.4\" and extra == \"dev\"",
        "pytest-trio; python_version >= \"3.7\" and extra == \"dev\"",
        "black; extra == \"dev\"",
        "isort; extra == \"dev\"",
        "jupyter-console; extra == \"dev\"",
        "mkdocs; extra == \"dev\"",
        "mkdocs-include-markdown-plugin; extra == \"dev\"",
        "mkdocstrings[python]; extra == \"dev\"",
        "mypy; extra == \"dev\"",
        "sphinx; extra == \"dev\"",
        "toml; extra == \"dev\"",
        "tox; extra == \"dev\"",
        "trio; extra == \"dev\"",
        "trio; python_version > \"3.6\" and extra == \"dev\"",
        "trio-typing; python_version > \"3.6\" and extra == \"dev\"",
        "twine; extra == \"dev\"",
        "twisted; extra == \"dev\"",
        "validate-pyproject[all]; extra == \"dev\""
      ]
    },
    {
      "name": "Pygments",
      "version": "2.21.0",
      "filename": "pygments-2.21.0-py3-none-any.whl",
      "size": 1250147,
      "sha256": "2363c69b61c4a97c838da3b130dcd6468f4848992b21a82f2a63ec34377137d9",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/71/46/17f022dd3e953bf20a04a028a21ec746d942f8d2af30fa0f124fa0e6a684/pygments-2.21.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/Pygments/2.21.0/json",
      "uploaded_at": "2026-08-17T08:02:44.912148Z",
      "requires_python": ">=3.9",
      "declared_license": "BSD-2-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "colorama>=0.4.6; extra == 'windows-terminal'"
      ]
    },
    {
      "name": "pyobjc-core",
      "version": "12.2.2",
      "filename": "pyobjc_core-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "size": 6427637,
      "sha256": "122e6ad302a2abf5d4d4adb0156db751600ddf2768441696cba17b31323085e7",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/86/b2/bbf7f049880ab40d110e66f25122342a1f6c98d6fe3c59bb98985503c660/pyobjc_core-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyobjc-core/12.2.2/json",
      "uploaded_at": "2026-08-11T14:51:36.038204Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "pyobjc-framework-Cocoa",
      "version": "12.2.2",
      "filename": "pyobjc_framework_cocoa-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "size": 388117,
      "sha256": "e106f395531e67694376b0f1184612cbeea3ec8b9bf56b55ef41d026171d2a2d",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/fd/2f/b67e73d8bc367e03fe7861cd9c49fff9dcfa6db83bc0630c0adcfb25b7fa/pyobjc_framework_cocoa-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyobjc-framework-Cocoa/12.2.2/json",
      "uploaded_at": "2026-08-11T19:32:43.161083Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pyobjc-core>=12.2.2"
      ]
    },
    {
      "name": "pyobjc-framework-Quartz",
      "version": "12.2.2",
      "filename": "pyobjc_framework_quartz-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "size": 219003,
      "sha256": "7f668979d0c7320bf8f7ed6e030da578f93ab0f5dd619b295ec735cd8d5faa34",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/ed/e4/8be95d2ff850f82fb55b44c63333a00a920bf8a73642e7d9c2f3638a26d2/pyobjc_framework_quartz-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyobjc-framework-Quartz/12.2.2/json",
      "uploaded_at": "2026-08-11T19:40:24.425160Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pyobjc-core>=12.2.2",
        "pyobjc-framework-Cocoa>=12.2.2"
      ]
    },
    {
      "name": "pyobjc-framework-Security",
      "version": "12.2.2",
      "filename": "pyobjc_framework_security-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "size": 41298,
      "sha256": "266f41995f2fc80660c8451bdb199a7e259a6cad02fbc1e0e2f69dd5576e2203",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/15/59/79722efbbb5cf6a313d364bb4faff39f9c165740e46acaa4d0a3d71c0f8c/pyobjc_framework_security-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyobjc-framework-Security/12.2.2/json",
      "uploaded_at": "2026-08-11T19:41:27.540856Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pyobjc-core>=12.2.2",
        "pyobjc-framework-Cocoa>=12.2.2"
      ]
    },
    {
      "name": "pyobjc-framework-UniformTypeIdentifiers",
      "version": "12.2.2",
      "filename": "pyobjc_framework_uniformtypeidentifiers-12.2.2-py2.py3-none-any.whl",
      "size": 5045,
      "sha256": "1dc6a538df07c410e4bfd6457adcb0b663a5e0df331905dbe135bcfd3f89ae57",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/79/c3/45ec69ed9fdcde5d0f229a031b610127c592d2c4674c3ff0e184d7f2741b/pyobjc_framework_uniformtypeidentifiers-12.2.2-py2.py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyobjc-framework-UniformTypeIdentifiers/12.2.2/json",
      "uploaded_at": "2026-08-11T19:42:56.598712Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pyobjc-core>=12.2.2",
        "pyobjc-framework-Cocoa>=12.2.2"
      ]
    },
    {
      "name": "pyobjc-framework-WebKit",
      "version": "12.2.2",
      "filename": "pyobjc_framework_webkit-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "size": 50371,
      "sha256": "ef37692f0280151bf8164a718e334a9b3cb0abfc5455be14172280de7e277505",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/b9/76/344b197a89878e8b103727984f2815bc38393515be5bf63aa7b847c414e0/pyobjc_framework_webkit-12.2.2-cp312-cp312-macosx_10_13_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyobjc-framework-WebKit/12.2.2/json",
      "uploaded_at": "2026-08-11T19:43:31.561699Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pyobjc-core>=12.2.2",
        "pyobjc-framework-Cocoa>=12.2.2"
      ]
    },
    {
      "name": "pypdf",
      "version": "6.17.0",
      "filename": "pypdf-6.17.0-py3-none-any.whl",
      "size": 388051,
      "sha256": "5bd827266a21553b74d910e350131a6227b72f2ab4209bf372814b8195fa11c5",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/c1/08/1e9731038124a9127e1d27848952b86fb32b2f45f8f1b94adc7f0817a6ac/pypdf-6.17.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pypdf/6.17.0/json",
      "uploaded_at": "2026-09-04T11:30:42.681909Z",
      "requires_python": ">=3.9",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "typing_extensions >= 4.0; python_version < '3.11'",
        "cryptography>3.0 ; extra == \"crypto\"",
        "PyCryptodome ; extra == \"cryptodome\"",
        "flit ; extra == \"dev\"",
        "pip-tools ; extra == \"dev\"",
        "pre-commit ; extra == \"dev\"",
        "pytest-cov ; extra == \"dev\"",
        "pytest-socket ; extra == \"dev\"",
        "pytest-timeout ; extra == \"dev\"",
        "pytest-xdist ; extra == \"dev\"",
        "wheel ; extra == \"dev\"",
        "myst_parser ; extra == \"docs\"",
        "sphinx ; extra == \"docs\"",
        "sphinx_rtd_theme ; extra == \"docs\"",
        "fonttools ; extra == \"fonts\"",
        "arabic-reshaper ; extra == \"full\"",
        "cryptography>3.0 ; extra == \"full\"",
        "fonttools ; extra == \"full\"",
        "Pillow>=8.0.0 ; extra == \"full\"",
        "python-bidi ; extra == \"full\"",
        "Pillow>=8.0.0 ; extra == \"image\"",
        "arabic-reshaper ; extra == \"rtl-text\"",
        "python-bidi ; extra == \"rtl-text\""
      ]
    },
    {
      "name": "pypdfium2",
      "version": "5.13.0",
      "filename": "pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl",
      "size": 3507415,
      "sha256": "da5c7b74eebf40b5c1fbe1de01aa1edc8827a79fb1efd999616bc20dcaf77ba4",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/08/99/1fe58428b69d2722dcbcfaa08ce71834a332c5b518fd58874bcef936b823/pypdfium2-5.13.0-py3-none-macosx_13_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/pypdfium2/5.13.0/json",
      "uploaded_at": "2026-08-13T10:57:43.978023Z",
      "requires_python": ">= 3.6",
      "declared_license": "BSD-3-Clause, Apache-2.0, dependency licenses",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "pyproject_hooks",
      "version": "1.2.0",
      "filename": "pyproject_hooks-1.2.0-py3-none-any.whl",
      "size": 10216,
      "sha256": "9e5c6bfa8dcc30091c74b0cf803c81fdd29d94f01992a7707bc97babb1141913",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/bd/24/12818598c362d7f300f18e74db45963dbcb85150324092410c8b49405e42/pyproject_hooks-1.2.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pyproject_hooks/1.2.0/json",
      "uploaded_at": "2024-09-29T09:24:11.978642Z",
      "requires_python": ">=3.7",
      "declared_license": "License :: OSI Approved :: MIT License",
      "download_group": "C_no_deps",
      "requires_dist_raw": []
    },
    {
      "name": "pytest",
      "version": "9.1.1",
      "filename": "pytest-9.1.1-py3-none-any.whl",
      "size": 386536,
      "sha256": "37a86b45efb9a47a61a36449063e8e18d0cab3161329fc099eb21783169c4f0c",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/24/25/1de2678b631f5a49215c6c96fff41ba892b0a34df68d6d80292b1b48aa7f/pytest-9.1.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pytest/9.1.1/json",
      "uploaded_at": "2026-06-19T10:58:31.347074Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "colorama>=0.4; sys_platform == \"win32\"",
        "exceptiongroup>=1; python_version < \"3.11\"",
        "iniconfig>=1.0.1",
        "packaging>=22",
        "pluggy<2,>=1.5",
        "pygments>=2.7.2",
        "tomli>=1; python_version < \"3.11\"",
        "argcomplete; extra == \"dev\"",
        "attrs>=19.2; extra == \"dev\"",
        "hypothesis>=3.56; extra == \"dev\"",
        "mock; extra == \"dev\"",
        "requests; extra == \"dev\"",
        "setuptools; extra == \"dev\"",
        "xmlschema; extra == \"dev\""
      ]
    },
    {
      "name": "python-docx",
      "version": "1.2.0",
      "filename": "python_docx-1.2.0-py3-none-any.whl",
      "size": 252987,
      "sha256": "3fd478f3250fbbbfd3b94fe1e985955737c145627498896a8a6bf81f4baf66c7",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/d0/00/1e03a4989fa5795da308cd774f05b704ace555a70f9bf9d3be057b680bcf/python_docx-1.2.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/python-docx/1.2.0/json",
      "uploaded_at": "2025-06-16T20:46:22.506016Z",
      "requires_python": ">=3.9",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "lxml>=3.1.0",
        "typing_extensions>=4.9.0"
      ]
    },
    {
      "name": "pywebview",
      "version": "6.2.1",
      "filename": "pywebview-6.2.1-py3-none-any.whl",
      "size": 525463,
      "sha256": "9d07275f53894ab4d5e2e0e996227193e7187dec276d9b624dccbce029216b46",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/3d/25/9491695c22c4842c5b3903b4dc172e0eecf67a27c0af34a71512c9b76a0a/pywebview-6.2.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/pywebview/6.2.1/json",
      "uploaded_at": "2026-04-15T09:02:10.186272Z",
      "requires_python": ">=3.8",
      "declared_license": "BSD 3-Clause License",
      "download_group": "C_no_deps",
      "requires_dist_raw": [
        "pythonnet; sys_platform == \"win32\"",
        "pyobjc-core>=9.0; sys_platform == \"darwin\"",
        "pyobjc-framework-Cocoa>=9.0; sys_platform == \"darwin\"",
        "pyobjc-framework-Quartz>=9.0; sys_platform == \"darwin\"",
        "pyobjc-framework-WebKit>=9.0; sys_platform == \"darwin\"",
        "pyobjc-framework-security>=9.0; sys_platform == \"darwin\"",
        "pyobjc-framework-UniformTypeIdentifiers>=9.0; sys_platform == \"darwin\"",
        "QtPy; sys_platform == \"openbsd6\"",
        "importlib_resources; python_version < \"3.9\"",
        "proxy_tools",
        "bottle",
        "typing_extensions",
        "cefpython3; extra == \"cef\"",
        "PyGObject==3.50.0; extra == \"gtk\"",
        "PyGObject-stubs; extra == \"gtk\"",
        "QtPy; extra == \"pyside2\"",
        "PySide2; extra == \"pyside2\"",
        "QtPy; extra == \"pyside6\"",
        "PySide6; extra == \"pyside6\"",
        "QtPy; extra == \"qt\"",
        "PyQt6; extra == \"qt\"",
        "PyQt6-WebEngine; extra == \"qt\"",
        "QtPy; extra == \"qt5\"",
        "PyQt5; extra == \"qt5\"",
        "pyqtwebengine; extra == \"qt5\"",
        "QtPy; extra == \"qt6\"",
        "PyQt6; extra == \"qt6\"",
        "PyQt6-WebEngine; extra == \"qt6\"",
        "jnius; extra == \"android\"",
        "cryptography; extra == \"ssl\"",
        "ruff; extra == \"dev\"",
        "pre-commit; extra == \"dev\"",
        "pytest; extra == \"dev\"",
        "build; extra == \"dev\"",
        "twine; extra == \"dev\""
      ]
    },
    {
      "name": "PyYAML",
      "version": "6.0.3",
      "filename": "pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl",
      "size": 173973,
      "sha256": "fc09d0aa354569bc501d4e787133afc08552722d3ab34836a80547331bb5d4a0",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/89/a0/6cf41a19a1f2f3feab0e9c0b74134aa2ce6849093d5517a0c550fe37a648/pyyaml-6.0.3-cp312-cp312-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/PyYAML/6.0.3/json",
      "uploaded_at": "2025-09-25T21:32:12.492377Z",
      "requires_python": ">=3.8",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "reportlab",
      "version": "5.0.1",
      "filename": "reportlab-5.0.1-py3-none-any.whl",
      "size": 1957258,
      "sha256": "1c36e6bb0e71780c72331eba60da7f602e8d4389a8723825af71342e49d791e8",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/db/cb/dacbc268cb68d0428ea2cbd85266195a9ab3e677449589ddae59bd7542ac/reportlab-5.0.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/reportlab/5.0.1/json",
      "uploaded_at": "2026-08-20T13:48:14.026116Z",
      "requires_python": ">=3.9,<4",
      "declared_license": "BSD license (see license.txt for details), Copyright (c) 2000-2025, ReportLab Inc.",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pillow>=9.0.0",
        "charset-normalizer",
        "rl_accel<1.1,>=0.9.0; extra == \"accel\"",
        "rlPyCairo<1,>=0.2.0; extra == \"pycairo\"",
        "freetype-py<2.4,>=2.3.0; extra == \"pycairo\"",
        "rlbidi; extra == \"bidi\"",
        "uharfbuzz; extra == \"shaping\""
      ]
    },
    {
      "name": "requests",
      "version": "2.34.2",
      "filename": "requests-2.34.2-py3-none-any.whl",
      "size": 73075,
      "sha256": "2a0d60c172f83ac6ab31e4554906c0f3b3588d37b5cb939b1c061f4907e278e0",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/a0/f4/c67b0b3f1b9245e8d266f0f112c500d50e5b4e83cb6f3b71b6528104182a/requests-2.34.2-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/requests/2.34.2/json",
      "uploaded_at": "2026-05-14T19:25:26.443000Z",
      "requires_python": ">=3.10",
      "declared_license": "Apache-2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "charset_normalizer<4,>=2",
        "idna<4,>=2.5",
        "urllib3<3,>=1.26",
        "certifi>=2023.5.7",
        "PySocks!=1.5.7,>=1.5.6; extra == \"socks\"",
        "chardet<8,>=3.0.2; extra == \"use-chardet-on-py3\""
      ]
    },
    {
      "name": "requests-toolbelt",
      "version": "1.0.0",
      "filename": "requests_toolbelt-1.0.0-py2.py3-none-any.whl",
      "size": 54481,
      "sha256": "cccfdd665f0a24fcf4726e690f65639d272bb0637b9b92dfd91a5568ccf6bd06",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/3f/51/d4db610ef29373b879047326cbf6fa98b6c1969d6f6dc423279de2b1be2c/requests_toolbelt-1.0.0-py2.py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/requests-toolbelt/1.0.0/json",
      "uploaded_at": "2023-05-01T04:11:28.427086Z",
      "requires_python": ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*",
      "declared_license": "Apache 2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "requests (<3.0.0,>=2.0.1)"
      ]
    },
    {
      "name": "setuptools",
      "version": "84.0.0",
      "filename": "setuptools-84.0.0-py3-none-any.whl",
      "size": 818216,
      "sha256": "51a52592b3b99e102b609654876bd65f19f999935166d1352678931132b0c670",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/95/9c/c510029fc6ef33a6275cd2c5d3cecd6613dfd6aa401d57c54f1c18852ccf/setuptools-84.0.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/setuptools/84.0.0/json",
      "uploaded_at": "2026-08-08T18:27:56.719708Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "pytest!=8.1.*,>=6; extra == \"test\"",
        "virtualenv>=13.0.0; extra == \"test\"",
        "wheel>=0.44.0; extra == \"test\"",
        "pip>=19.1; extra == \"test\"",
        "packaging>=24.2; extra == \"test\"",
        "jaraco.envs>=2.2; extra == \"test\"",
        "pytest-xdist>=3; extra == \"test\"",
        "jaraco.path>=3.7.2; extra == \"test\"",
        "build[virtualenv]>=1.0.3; extra == \"test\"",
        "filelock>=3.4.0; extra == \"test\"",
        "ini2toml[lite]>=0.14; extra == \"test\"",
        "tomli-w>=1.0.0; extra == \"test\"",
        "pytest-timeout; extra == \"test\"",
        "pytest-perf; sys_platform != \"cygwin\" and extra == \"test\"",
        "jaraco.develop>=7.21; (python_version >= \"3.9\" and sys_platform != \"cygwin\") and extra == \"test\"",
        "pytest-home>=0.5; extra == \"test\"",
        "pytest-subprocess; extra == \"test\"",
        "pyproject-hooks!=1.1; extra == \"test\"",
        "jaraco.test>=5.5; extra == \"test\"",
        "sphinx>=3.5; extra == \"doc\"",
        "jaraco.packaging>=9.3; extra == \"doc\"",
        "rst.linker>=1.9; extra == \"doc\"",
        "furo; extra == \"doc\"",
        "sphinx-lint; extra == \"doc\"",
        "jaraco.tidelift>=1.4; extra == \"doc\"",
        "pygments-github-lexers==0.0.5; extra == \"doc\"",
        "sphinx-favicon; extra == \"doc\"",
        "sphinx-inline-tabs; extra == \"doc\"",
        "sphinx-reredirects; extra == \"doc\"",
        "sphinxcontrib-towncrier; extra == \"doc\"",
        "sphinx-notfound-page<2,>=1; extra == \"doc\"",
        "pyproject-hooks!=1.1; extra == \"doc\"",
        "towncrier<24.7; extra == \"doc\"",
        "packaging>=24.2; extra == \"core\"",
        "more_itertools>=8.8; extra == \"core\"",
        "jaraco.text>=3.7; extra == \"core\"",
        "importlib_metadata>=6; python_version < \"3.10\" and extra == \"core\"",
        "tomli>=2.0.1; python_version < \"3.11\" and extra == \"core\"",
        "wheel>=0.43.0; extra == \"core\"",
        "jaraco.functools>=4; extra == \"core\"",
        "more_itertools; extra == \"core\"",
        "pytest-checkdocs>=2.14; extra == \"check\"",
        "pytest-ruff>=0.2.1; sys_platform != \"cygwin\" and extra == \"check\"",
        "ruff>=0.13.0; sys_platform != \"cygwin\" and extra == \"check\"",
        "pytest-cov; extra == \"cover\"",
        "pytest-enabler>=3.4; extra == \"enabler\"",
        "pytest-mypy>=1.0.1; platform_python_implementation != \"PyPy\" and extra == \"type\"",
        "mypy==1.18.*; extra == \"type\"",
        "importlib_metadata>=7.0.2; python_version < \"3.10\" and extra == \"type\"",
        "jaraco.develop>=7.21; sys_platform != \"cygwin\" and extra == \"type\""
      ]
    },
    {
      "name": "sniffio",
      "version": "1.3.1",
      "filename": "sniffio-1.3.1-py3-none-any.whl",
      "size": 10235,
      "sha256": "2f6da418d1f1e0fddd844478f41680e794e6051915791a034ff65e5f100525a2",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/e9/44/75a9c9421471a6c4805dbf2356f7c181a29c1879239abab1ea2cc8f38b40/sniffio-1.3.1-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/sniffio/1.3.1/json",
      "uploaded_at": "2024-02-25T23:20:01.196159Z",
      "requires_python": ">=3.7",
      "declared_license": "MIT OR Apache-2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "sqlite-vec",
      "version": "0.1.9",
      "filename": "sqlite_vec-0.1.9-py3-none-macosx_11_0_arm64.whl",
      "size": 165434,
      "sha256": "1d52e30513bae4cc9778ddbf6145610434081be4c3afe57cd877893bad9f6b6c",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/a4/3d/3677e0cd2f92e5ebc43cd29fbf565b75582bff1ccfa0b8327c7508e1084f/sqlite_vec-0.1.9-py3-none-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/sqlite-vec/0.1.9/json",
      "uploaded_at": "2026-03-31T08:02:32.712093Z",
      "requires_python": null,
      "declared_license": "MIT License, Apache License, Version 2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "starlette",
      "version": "1.6.0",
      "filename": "starlette-1.6.0-py3-none-any.whl",
      "size": 75969,
      "sha256": "a86dd39d14bb45f85a3d18525215a9ef0cfd1f192ac793220e72598c90335f0c",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/c8/cb/6a6a47d5b464bd08695d254f3da6e7986cc70c9fa5d778eda57538edfe56/starlette-1.6.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/starlette/1.6.0/json",
      "uploaded_at": "2026-08-08T18:27:56.196765Z",
      "requires_python": ">=3.10",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "anyio<5,>=3.6.2",
        "typing-extensions>=4.10.0; python_version < '3.13'",
        "httpx2>=2.0.0; extra == 'full'",
        "httpx<0.29.0,>=0.27.0; extra == 'full'",
        "itsdangerous; extra == 'full'",
        "jinja2; extra == 'full'",
        "python-multipart>=0.0.18; extra == 'full'",
        "pyyaml; extra == 'full'"
      ]
    },
    {
      "name": "tenacity",
      "version": "9.1.4",
      "filename": "tenacity-9.1.4-py3-none-any.whl",
      "size": 28926,
      "sha256": "6095a360c919085f28c6527de529e76a06ad89b23659fa881ae0649b867a9d55",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/d7/c1/eb8f9debc45d3b7918a32ab756658a0904732f75e555402972246b0b8e71/tenacity-9.1.4-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/tenacity/9.1.4/json",
      "uploaded_at": "2026-02-07T10:45:32.240169Z",
      "requires_python": ">=3.10",
      "declared_license": "Apache 2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "reno; extra == \"doc\"",
        "sphinx; extra == \"doc\"",
        "pytest; extra == \"test\"",
        "tornado>=4.5; extra == \"test\"",
        "typeguard; extra == \"test\""
      ]
    },
    {
      "name": "truststore",
      "version": "0.10.4",
      "filename": "truststore-0.10.4-py3-none-any.whl",
      "size": 18660,
      "sha256": "adaeaecf1cbb5f4de3b1959b42d41f6fab57b2b1666adb59e89cb0b53361d981",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/19/97/56608b2249fe206a67cd573bc93cd9896e1efb9e98bce9c163bcdc704b88/truststore-0.10.4-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/truststore/0.10.4/json",
      "uploaded_at": "2025-08-12T18:49:01.460601Z",
      "requires_python": ">= 3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "typing_extensions",
      "version": "4.16.0",
      "filename": "typing_extensions-4.16.0-py3-none-any.whl",
      "size": 45571,
      "sha256": "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/49/d3/b8441a820a491ddfc024b0b0cf0393375b75ea13866d9c66727e54c2fc80/typing_extensions-4.16.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/typing_extensions/4.16.0/json",
      "uploaded_at": "2026-07-02T08:40:04.659120Z",
      "requires_python": ">=3.9",
      "declared_license": "PSF-2.0",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "typing-inspection",
      "version": "0.4.4",
      "filename": "typing_inspection-0.4.4-py3-none-any.whl",
      "size": 14750,
      "sha256": "65b8397ba37ccbce054456aaccddfc91e6e3083c92824df348d96ca832f3f147",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/67/81/4add07e5172b7ac40d8ed5ff580409a7801a4fe26d529bdd915401dabfbe/typing_inspection-0.4.4-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/typing-inspection/0.4.4/json",
      "uploaded_at": "2026-08-12T12:37:24.648475Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "typing-extensions>=4.15.0"
      ]
    },
    {
      "name": "urllib3",
      "version": "2.7.0",
      "filename": "urllib3-2.7.0-py3-none-any.whl",
      "size": 131087,
      "sha256": "9fb4c81ebbb1ce9531cce37674bbc6f1360472bc18ca9a553ede278ef7276897",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/7f/3e/5db95bcf282c52709639744ca2a8b149baccf648e39c8cc87553df9eae0c/urllib3-2.7.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/urllib3/2.7.0/json",
      "uploaded_at": "2026-05-07T16:13:17.151740Z",
      "requires_python": ">=3.10",
      "declared_license": "MIT",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "brotli>=1.2.0; (platform_python_implementation == 'CPython') and extra == 'brotli'",
        "brotlicffi>=1.2.0.0; (platform_python_implementation != 'CPython') and extra == 'brotli'",
        "h2<5,>=4; extra == 'h2'",
        "pysocks!=1.5.7,<2.0,>=1.5.6; extra == 'socks'",
        "backports-zstd>=1.0.0; (python_version < '3.14') and extra == 'zstd'"
      ]
    },
    {
      "name": "uuid_utils",
      "version": "0.17.0",
      "filename": "uuid_utils-0.17.0-cp312-cp312-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl",
      "size": 556403,
      "sha256": "9205068badf453d2f0821fd5d340389b4679992d7ff79d4f3e5608996dd1b287",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/20/80/a7e685968e3cec99d6fe2fb25d0f5726310e1bba356da68c13dfd8b7d140/uuid_utils-0.17.0-cp312-cp312-macosx_10_12_x86_64.macosx_11_0_arm64.macosx_10_12_universal2.whl",
      "pypi_release_json": "https://pypi.org/pypi/uuid_utils/0.17.0/json",
      "uploaded_at": "2026-07-09T13:48:27.022801Z",
      "requires_python": ">=3.10",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "uvicorn",
      "version": "0.52.4",
      "filename": "uvicorn-0.52.4-py3-none-any.whl",
      "size": 79871,
      "sha256": "f86e41a149d7d05a9969337e3946a9c171c06a5d42680896daaba624aeac8da1",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/f1/79/4a20b54ab0491485ccd8c077db2d39187c7f12b3e15485d38a7be37c81b4/uvicorn-0.52.4-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/uvicorn/0.52.4/json",
      "uploaded_at": "2026-08-19T06:27:40.360546Z",
      "requires_python": ">=3.10",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "click>=7.0",
        "h11>=0.8",
        "typing-extensions>=4.0; python_version < '3.11'",
        "httptools>=0.8.0; extra == 'standard'",
        "python-dotenv>=0.13; extra == 'standard'",
        "pyyaml>=5.1; extra == 'standard'",
        "uvloop>=0.15.1; (sys_platform != 'win32' and (sys_platform != 'cygwin' and platform_python_implementation != 'PyPy')) and extra == 'standard'",
        "watchfiles>=0.20; extra == 'standard'",
        "websockets>=13.0; extra == 'standard'"
      ]
    },
    {
      "name": "websockets",
      "version": "16.1.1",
      "filename": "websockets-16.1.1-cp312-cp312-macosx_11_0_arm64.whl",
      "size": 177542,
      "sha256": "01fbdcbac298efe19360b94bc0039c8f746f0220ba570f327577bfee81059175",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/73/e3/fe2d498c64dea0095c9a9f9a351af4cd6eef31b618395582bc1f38ba45ff/websockets-16.1.1-cp312-cp312-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/websockets/16.1.1/json",
      "uploaded_at": "2026-07-17T22:49:16.875052Z",
      "requires_python": ">=3.10",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "wheel",
      "version": "0.48.0",
      "filename": "wheel-0.48.0-py3-none-any.whl",
      "size": 33320,
      "sha256": "3217dcc807155e45db462d7ef2431f5ddda0d7273b700d05a67b271ceb1287ab",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/2e/29/69cfbb602cd91690c55d38ba9fe53e6a7e76a6fa647bf38f19c138d25449/wheel-0.48.0-py3-none-any.whl",
      "pypi_release_json": "https://pypi.org/pypi/wheel/0.48.0/json",
      "uploaded_at": "2026-08-11T22:02:26.100721Z",
      "requires_python": ">=3.9",
      "declared_license": "MIT",
      "download_group": "C_no_deps",
      "requires_dist_raw": [
        "packaging >= 24.0"
      ]
    },
    {
      "name": "xxhash",
      "version": "4.0.1",
      "filename": "xxhash-4.0.1-cp312-cp312-macosx_11_0_arm64.whl",
      "size": 36195,
      "sha256": "515a822c73abbf6a0b7c70976d9662be342835c9d78b8dc7c023411f39c35dbc",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/75/c9/cf736f6db8c3273af18925061572db0d4357818a9ce425f4b5fb0021918e/xxhash-4.0.1-cp312-cp312-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/xxhash/4.0.1/json",
      "uploaded_at": "2026-08-17T08:35:13.004744Z",
      "requires_python": ">=3.9",
      "declared_license": "BSD-2-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": []
    },
    {
      "name": "zstandard",
      "version": "0.25.0",
      "filename": "zstandard-0.25.0-cp312-cp312-macosx_11_0_arm64.whl",
      "size": 640436,
      "sha256": "913cbd31a400febff93b564a23e17c3ed2d56c064006f54efec210d586171c00",
      "pypi_match": true,
      "url": "https://files.pythonhosted.org/packages/aa/1c/d920d64b22f8dd028a8b90e2d756e431a5d86194caa78e3819c7bf53b4b3/zstandard-0.25.0-cp312-cp312-macosx_11_0_arm64.whl",
      "pypi_release_json": "https://pypi.org/pypi/zstandard/0.25.0/json",
      "uploaded_at": "2025-09-14T22:16:57.774290Z",
      "requires_python": ">=3.9",
      "declared_license": "BSD-3-Clause",
      "download_group": "B_resolved_subset",
      "requires_dist_raw": [
        "cffi~=1.17; (platform_python_implementation != \"PyPy\" and python_version < \"3.14\") and extra == \"cffi\"",
        "cffi>=2.0.0b; (platform_python_implementation != \"PyPy\" and python_version >= \"3.14\") and extra == \"cffi\""
      ]
    }
  ],
  "native_artifacts": [
    {
      "name": "age",
      "version": "1.3.2",
      "filename": "age-v1.3.2-darwin-arm64.tar.gz",
      "sha256": "e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5",
      "evidence": "publisher API digest and archive bytes",
      "url": "https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-darwin-arm64.tar.gz",
      "license": "BSD-3-Clause plus bundled Go/dependency notices",
      "members": {
        "age/age": "4012dfc2725883beafb710894af4f599b7a94f8c8e0f51f02cc96ab8df33915e",
        "age/age-keygen": "c16e229245123d0ad27442317461d63915416cad0294395cd19ca93feb3211ea"
      }
    },
    {
      "name": "codex-cli-standalone",
      "version": "0.144.4",
      "filename": "codex-aarch64-apple-darwin.tar.gz",
      "size": 98301318,
      "sha256": "77c8969a481302f9db1d9ea2a6c21c083abae3f1a8fc8a7275dc38323699391e",
      "evidence": "publisher API digest only; not downloaded",
      "url": "https://github.com/openai/codex/releases/download/rust-v0.144.4/codex-aarch64-apple-darwin.tar.gz",
      "license": "Apache-2.0 source; binary notice closure pending"
    },
    {
      "name": "codex-cli-package-candidate",
      "version": "0.144.4",
      "filename": "codex-package-aarch64-apple-darwin.tar.gz",
      "size": 116111014,
      "sha256": "312e6fa2826596fb23cc1193c30d51902b6522c36ccc43b36417590e0ebd533d",
      "evidence": "publisher API digest only; not downloaded; executable membership not verified",
      "url": "https://github.com/openai/codex/releases/download/rust-v0.144.4/codex-package-aarch64-apple-darwin.tar.gz",
      "license": "Apache-2.0 source; binary notice closure pending"
    },
    {
      "name": "whisper.cpp-source",
      "version": "1.8.7",
      "commit": "48f628a84833905ee4a0658ee6d4a5c915ce1997",
      "sha256": "0b988ba5053cfa720f6d399f3f21885b01c4222178be435ca2272d6872717554",
      "evidence": "observed codeload archive bytes, not publisher-posted checksum",
      "url": "https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v1.8.7",
      "license": "MIT",
      "darwin_cli_release_asset": false,
      "built_cli_sha256": null
    },
    {
      "name": "whisper.cpp-xcframework-alternative",
      "version": "1.8.7",
      "filename": "whisper-v1.8.7-xcframework.zip",
      "sha256": "501076a091bf4b2d76ec92df9dd13278382dfb266b82bbd438c210a21c10b84c",
      "evidence": "publisher asset digest; archive plist read, not a whisper-cli executable",
      "minimum_macos": "13.3",
      "architectures": [
        "arm64",
        "x86_64"
      ],
      "license": "MIT"
    },
    {
      "name": "whisper-multilingual-base-model",
      "filename": "ggml-base.bin",
      "size": 147951465,
      "revision": "5359861c739e955e79d9a303bcbc70fb988958b1",
      "sha256": "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe",
      "evidence": "publisher LFS pointer only; model bytes not downloaded",
      "url": "https://huggingface.co/ggerganov/whisper.cpp/resolve/5359861c739e955e79d9a303bcbc70fb988958b1/ggml-base.bin",
      "license": "MIT"
    },
    {
      "name": "playwright-chromium",
      "playwright_version": "1.62.0",
      "revision": "1234",
      "browser_version": "151.0.7922.34",
      "upstream_title": "Chrome for Testing",
      "evidence": "browsers.json inside verified wheel; browser payload not downloaded",
      "browser_archive_sha256": null,
      "browsers_json_sha256": "f306eed529599b1eaf2f8a85db9de2b23e1a3fe36c2b66434b7c9434fb627a99",
      "driver_node_sha256": "f480e325ee0ca9cb9eef00b5ca6057a2a104807a1b073f1bc373a55c67facff5",
      "driver_node_version": null
    },
    {
      "name": "pdfium-wheel-member",
      "binding_version": "5.13.0",
      "pdfium_version": "153.0.7999.0",
      "member": "pypdfium2_raw/libpdfium.dylib",
      "sha256": "33c98063af28c0b7cbf8227f4422bf5c15942df2455cf7f0a5dce3dc601d52b0",
      "evidence": "member bytes in verified pypdfium2 wheel",
      "producer": "bblanchon/pdfium-binaries",
      "producer_release": "chromium/7999",
      "license": "PDFium and bundled third-party notices"
    }
  ],
  "unresolved_release_gates": [
    "proxy_tools source review, licensed notice provenance, isolated build and resulting wheel hash",
    "complete candidate graph resolution and fresh scoped install/pip check/tests",
    "Python standalone framework and native dylib closure",
    "Chromium payload exact SHA and notices, Node version, no-network inherited sandbox feasibility",
    "Codex selected archive bytes/member closure and app-server compatibility",
    "whisper-cli arm64 build SHA, base model bytes, real microphone/cancel/Korean capture",
    "Keychain helper access isolation and worker filesystem/network denial",
    "license/notice closure including ReportLab fonts and PDFium/Pillow bundled libraries",
    "signed/notarized clean-user GUI-only install/update/quit proof"
  ]
}
```
