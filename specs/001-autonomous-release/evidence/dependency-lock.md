# T003 exact dependency lock and component selection

> **ADR-009 이후의 용도:** 이 기록의 macOS/py2app/pywebview 네이티브 선택은 역사적
> 실험 입력이며 현재 웹 릴리스의 의존성 또는 완료 증거가 아니다. 재사용 가능한 잠금·출처·
> 무결성 원칙만 유지하며, 현재 Linux 다중아키텍처 웹 배포 입력은 T089와
> `deploy/locks/`·`deploy/manifests/`가 담당한다.

Date: 2026-09-08 (Asia/Seoul). Status: **dependency-selection task complete; native
release qualification is explicitly not claimed**.

This closes the bounded T003 responsibility: exact Python artifacts and exact native
source/archive selections are recorded, install-time resolution is disabled, and the lock was
installed in a disposable environment. It does **not** close the independent sandbox, packaged
binary, license-notice, signing/notarization, or clean-device gates in T018 and T079–T084.

## Architecture decision preserved

DeepTwin uses direct `StateGraph`/LangGraph orchestration. The final runtime therefore pins
`langgraph==1.2.11`, explicitly pins `langchain-core==1.6.2`, and retains the resolved
`langsmith==0.12.2` dependency with tracing disabled. Neither the full `langchain` agent
factory nor `deepagents` is installed. This follows R7 rather than adding a framework solely
because a generic dependency template mentions it. All are Python 1.x ecosystem packages and
the tested interpreter is Python 3.12.13 (the project minimum remains Python 3.10+).

The official LangGraph installation page confirms Python 3.10+ and describes LangChain as one
optional way to add LLMs/tools; DeepTwin instead has native provider adapters:
<https://docs.langchain.com/oss/python/langgraph/install>.

## Exact Python closure

- `app/requirements-release.lock`: **67 runtime wheels**, exact versions and one SHA-256 per
  selected macOS-arm64/Python-3.12 artifact. SHA-256:
  `a83e4c059141475eafce327f728ff5a80e35c28869c0a947f8191e7d1b5472ac`.
- `packaging/macos/component-manifest.json`: **80 Python components** total: 67 runtime and
  13 build/test. Every entry has an exact version, artifact filename, byte size, official
  source URL, SHA-256, scope, and non-empty publisher-declared license.
- The locally and reproducibly built `proxy_tools==0.1.0` wheel remains pinned to
  `05c6569bed050329df696d1a4a928e1a0702ca3dd80d04a3c12d596ac89ef7ef`.
  Its metadata/source-license discrepancy remains visible; it was not relabeled.
- Runtime installation policy in the manifest is `--require-hashes --no-index` from a verified
  wheelhouse. The app must never run a `latest` resolver or package installer at startup.

Disposable verification root:
`/private/tmp/deeptwin-t003-final.gvofXR`. The existing project environment and global Python
were not modified.

Fresh-environment installation used:

```sh
/Users/soonseekyang/Documents/Deeptwin/.venv/bin/python -m venv \
  /private/tmp/deeptwin-t003-final.gvofXR/direct-langgraph-venv

/private/tmp/deeptwin-t003-final.gvofXR/direct-langgraph-venv/bin/python \
  -I -m pip --isolated install --no-index --only-binary=:all: \
  --find-links /private/tmp/deeptwin-t003-wheels.58ytEM \
  --find-links /private/tmp/deeptwin-t003-build.EIO0ZY/wheels \
  --require-hashes -r packaging/macos/requirements-build.lock
```

Observed results:

- installation: exit 0; every runtime/build artifact came from the two scoped wheelhouses;
- `python -I -m pip --isolated check`: `No broken requirements found.`;
- secret-free imports: **22/22** passed, including FastAPI, Anthropic/httpx2, LangGraph graph
  and SQLite checkpoint, pywebview/PyObjC, Playwright, PDFium, Pillow, ReportLab and py2app;
- observed versions: langchain-core 1.6.2, langgraph 1.2.11, langsmith 0.12.2;
- explicit absence checks: `langchain` absent; `deepagents` absent;
- parsed lock ↔ runtime manifest: **67/67 exact version/hash matches**;
- Python license metadata: **80/80 non-empty**; this is metadata coverage, not a legal opinion
  and not the later exact resource/NOTICE audit.

## Exact native/source selections

The manifest distinguishes selected inputs from rejected/development-only alternatives. Seven
selected native/source entries all have a 64-character SHA-256 and a license identity.

| Selected purpose | Exact input and observed evidence | Qualification still separate |
| --- | --- | --- |
| Python runtime source | python-build-standalone `3.12.13+20260623` arm64 stripped archive, 25,003,823 bytes, SHA-256 `41df7d3ae4757e84b97874f76d634268456aaa271740d33f968d826374998fb7`; archive executable member exactly matched the tested base interpreter | py2app membership, relocated dylibs, bundled notices and final signing |
| backup encryption | age 1.3.2 official arm64 archive and executable-member hashes already byte-verified | bundled Go notices and packaged execution |
| Codex subscription bridge | official 0.144.4 arm64 archive, 98,301,318 bytes, SHA-256 `77c8969a481302f9db1d9ea2a6c21c083abae3f1a8fc8a7275dc38323699391e`; sole executable SHA-256 `3302acbda5f53de1a71ebdb0c0f2aae0d47f9324aa9fb6b4e78a47014fd51c7d`; arm64, OpenAI Developer-ID signed/hardened; secret-free `--version` returned `codex-cli 0.144.4` | app-server lifecycle and binary redistribution notices |
| local STT build input | whisper.cpp v1.8.7 codeload bytes matched SHA-256 `0b988ba5053cfa720f6d399f3f21885b01c4222178be435ca2272d6872717554`; exact MIT license member hash recorded | no Darwin CLI release exists; arm64 build output hash and capture behavior remain T024/T081 |
| default STT model | pinned multilingual `ggml-base.bin`, 147,951,465 bytes; downloaded bytes matched publisher LFS SHA-256 `60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe` | Korean/interim/final/cancel and packaged-model tests |
| controlled browser | unbranded Chromium snapshot revision 1693281, archive/member hashes and DOM/canvas/PNG canary already observed | exact third-party notices, sandbox inheritance and final signing |
| PDF renderer | pypdfium2 5.13.0 wheel member, PDFium 153.0.7999.0, exact dylib hash | all 16 bundled license resources and packaged render tests |

The full Codex package archive, whisper XCFramework, and branded Playwright Chrome payload are
recorded as **not selected**, so they cannot silently replace the chosen inputs. A selected
source hash is not represented as a hash of its future compiled/signed output.

## Manifest integrity

Machine checks on the final files observed:

```text
JSON parse                                         pass
lock syntax (exact == plus sha256)                 67/67 pass
lock ↔ runtime manifest version/hash parity        67/67 pass
Python declared-license metadata                   80/80 present
selected native/source SHA-256 and license         7/7 pass
selected vs not-selected set intersection          empty
runtime/build-test/native counts                   67 / 13 / 10
requirements-release.lock digest binding           pass
git diff --check (owned lock + manifest)            pass
```

The final manifest SHA-256 is
`95e0cad92263a4fd88995b1261a39d614533eb9b5016445c2a7d023c104a4ceb`.
The manifest cannot safely contain its own digest, so this external evidence record is the
digest location. A future signed release must bind both files in signed release metadata.

## Regression observation and limits

The clean locked environment ran the current `app/tests` suite on 2026-09-08. It observed
**1,830 passed and 3 failed**. All three failures are concurrent application-migration
expectation defects, not resolver/import failures: two tests still expect only domain migration
v1 after the implementation added v2, and one injected the legacy-mapping failure at an SQL
shape no longer used. They are reported to the integration owner and are not concealed as a
green full regression. Earlier same-lock regressions are preserved in
`dependency-installation.md`; final T085 must rerun the fully reconciled tree.

No provider inference, credential/account access, microphone capture, Keychain mutation,
signing/notarization, publication, or global installation occurred. Downloading and inspecting
the fixed public archives does not establish redistribution permission, sandbox containment,
or a release-ready application.
