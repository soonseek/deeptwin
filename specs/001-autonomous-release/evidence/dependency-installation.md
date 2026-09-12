# T003 Python closure build and fresh install

> **2026-09-08 superseded release target:** 이 문서는 ADR-009 이전 macOS/native dependency
> 실험의 재현 기록이다. 현재 웹 릴리스의 서비스 잠금·설치 또는 지원 증거가 아니며,
> `deploy/locks/`, `deploy/manifests/`와 T089가 현재 Linux build-input 권위다.

2026-09-07. **Python artifact closure installed/checked; native component closure pending.**
This follows, and does not rewrite, the earlier read-only dependency-resolution.md report.

## Reviewed source build

Created `/private/tmp/deeptwin-t003-build.EIO0ZY` with mktemp; downloaded only the exact
proxy_tools0.1.0 source archive from the report. Actual SHA256 matched
`ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`.
Read all setup.py/setup.cfg and the one Python source module using non-extracting archive
reads before executing the build backend. No setup hook downloads or compiled extension;
the source module itself declares BSD, whereas package metadata declares MIT.
The fixed-commit [upstream license](https://raw.githubusercontent.com/jtushman/proxy_tools/db43f1e35d4f90a65c5a4d56d9e9af88212ec6e6/LICENSE.txt)
was also read. Preserve source notices and metadata discrepancy in the component manifest;
local build success is not the completed distribution notice/legal provenance review.

In the disposable `venv` beneath that directory, installed exactly the hash-locked
`packaging/macos/requirements-build-bootstrap.lock` with `pip --isolated install --no-index
--find-links /private/tmp/deeptwin-t003-wheels.58ytEM --require-hashes`. Existing project
environment was not modified. The newly created venv's bootstrap pip25.0.1 was replaced
with pinned pip26.2.1; no system/global pip was changed.

Build command (same absolute interpreter on both runs):

```sh
env SOURCE_DATE_EPOCH=1399248144 /private/tmp/deeptwin-t003-build.EIO0ZY/venv/bin/python -I -m pip --isolated wheel --no-deps --no-build-isolation --no-index --no-cache-dir --wheel-dir /private/tmp/deeptwin-t003-build.EIO0ZY/wheels /private/tmp/deeptwin-t003-build.EIO0ZY/proxy_tools-0.1.0.tar.gz
```

Repeated with `repeat-wheels` output. Both produced a 2936-byte wheel with SHA256
`05c6569bed050329df696d1a4a928e1a0702ca3dd80d04a3c12d596ac89ef7ef`.
Its 6409-byte source member SHA256 remains
`d1539d95e1a713c068ca81d42e047b2c76568964cf277596d4e19efb22f476be`, identical to the
reviewed sdist module. Package-manager indexes/dependency fetches were disabled during the
build; this is not a claim that an OS network sandbox was applied to the build process.

## Complete resolution and fresh environment

`pip --isolated install --dry-run --ignore-installed --only-binary=:all: --no-index` with
both verified wheel directories and the exact requirements-release.in / requirements-build.in
roots succeeded. Unlike the earlier subset attempt, pywebview AND its built proxy dependency
are included. Reports in the task directory: release-resolution.json / combined-resolution.json.
All selected versions/hashes were matched to verified upstream wheels or the recorded build.

- Runtime closure: **67 wheels** in app/requirements-release.lock.
- Complete development closure: **80 wheels**, comprising the runtime plus13 in
  packaging/macos/requirements-build.lock.
- Component manifest records each source URL, exact version/hash, declared license and
  outstanding native/resource notices. Native hashes still lacking are not invented.

A second fresh venv, `/private/tmp/deeptwin-t003-build.EIO0ZY/runtime-venv`, installed the
complete build lock with `--require-hashes --no-index --only-binary=:all:` and those wheel
directories. Exit0. `python -I -m pip --isolated check`: **No broken requirements found**.
Size observed after installation/import: approximately336 MiB (not final app size).

Secret-free `env -i PATH=/usr/bin:/bin LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false`
smoke import passed for FastAPI, Starlette, Uvicorn, Pydantic, DOCX, Anthropic, httpx2,
LangGraph graph/sqlite, pywebview, Cocoa/Quartz/WebKit/Security/UniformTypeIdentifiers,
Playwright, pypdf/PDFium, Pillow, ReportLab and py2app (22 modules). Imports do not prove
network/tool interaction, Keychain access, real PDF rendering or standalone packaging.

Fresh-environment command: `runtime-venv/bin/python -m pytest app/tests
--ignore=app/tests/test_domain_storage.py -q`, run from the authoritative worktree.
**1505 passed, 1 existing warning in 10.74s**. The ignored storage file is a concurrently
developing separate slice, not a waived release test. Browser baseline is separately recorded.

## Browser candidates observed after Python closure

Playwright's current downloaded browser was identified as branded Chrome for Testing
151.0.7922.34 and contains the proprietary Widevine module. It remains development-canary
only; no whole-bundle redistribution grant was established. See
[browser-distribution.md](browser-distribution.md).

An official Google-hosted, unbranded arm64 Chromium snapshot was then downloaded into a
task-scoped temporary directory: revision `1693281`, source commit
`4bb4d9e4159daba6fe1b9889e28a2daa4a8eaf52`, version `155.0.8045.0`, archive size
173,402,912 bytes, SHA-256
`f3369098e501d8e43603059be914bd642d823fb34a8193823e64c74a9b9beb4c`.
The archive's MD5 also matched the official object metadata. A bounded archive inspection
found 683 entries, 375,016,130 expanded bytes, five internal relative symlinks, no traversal,
and no path named for Widevine/license/notices/credits. Absence of a Widevine path is useful
component evidence, not notice or redistribution closure.

Using the exact installed Playwright 1.62.0 package, this Chromium binary launched headlessly
with a fresh temporary profile and background networking disabled. A controlled in-memory
page produced the exact DOM marker, a working canvas context and an 11,711-byte PNG; observed
browser version was `155.0.8045.0`. The main executable SHA-256 is
`bfe4ce6074bf6d35524f28936054e160abaa9d9df5dcd3410b2b401e145d2f7c` and the framework
binary is `c673e09baa5cddc2a1b02ee138b28689080aee947f989efc40cb1b7b6a942b8e`.

This snapshot is ad-hoc/linker signed, has no Team ID, and fails `codesign --verify --deep
--strict` because the bundle has no sealed resources. It also lacks a colocated third-party
notice artifact. It is therefore only a functional qualification candidate, not yet an
eligible release payload. Packaging must preserve source/component notices, apply the final
nested signing order under actual signing authority, and prove the brokered native isolation
boundary before release.

## Remaining T003/native work

Pin/download/verify actual browser, matching driver, native STT binary/weights, redistributable
Python runtime, Codex binary/notices, all native/resource licenses and signed bundle closure.
T003 therefore remains open, with Python closure subwork complete. No account/key reads,
live inference, new paid usage, microphone capture, OS permission changes, signing or
publication occurred in this install. Temporary build/venv/wheel paths are rebuildable
development material, not a portable final-user installer.
