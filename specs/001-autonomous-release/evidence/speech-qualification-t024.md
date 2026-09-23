# T024 local speech qualification — development evidence

Date: 2026-09-08 (Asia/Seoul)

## Verdict

The owned speech code is ready for independent code audit. T024 itself is **not closed** by this
evidence. The local-only protocol, bounded capture/session behavior, Korean IME/edit isolation,
late-result rejection, restart interruption, retry, and keyboard-visible state have controlled
coverage. A fresh packaged GUI install, the selected release worker build, WK/WebKit permission
behavior, and a real-user microphone/accuracy matrix remain external qualification work.

No network/download, provider, credential, paid action, Keychain access, signing, OS policy change,
physical microphone, or personal recording was used. Browser audio was a generated sine wave. The
engine canary used a temporary `/usr/bin/say` Yuna utterance and deleted it with its temporary vault.

## Failure-first defects reproduced and closed

Nine new negative canaries failed before production changes:

1. Python accepted duplicate `engine` and duplicate nested `files` keys in the runtime manifest.
2. A runtime reached through a symlinked ancestor was reported ready.
3. A non-executable worker was reported ready.
4. Native worker JSON and persisted replay JSON accepted duplicate `text` keys.
5. The browser trusted `ready: true` from a non-local engine identity.
6. The browser accepted transcription text marked as coming from a non-local engine.
7. An immediate retry could race the prior failed session's delayed close and fail as busy.

The first Python command reported 5 failures (the duplicate-manifest parametrization is two cases),
the separate executable-mode canary reported 1 failure, and the browser command reported 3 failures:

```text
<workspace>/.venv/bin/python -m pytest \
  app/tests/test_speech.py::test_duplicate_manifest_keys_fail_closed \
  app/tests/test_speech.py::test_symlinked_runtime_ancestor_fails_closed \
  app/tests/test_speech.py::test_duplicate_native_reply_key_fails_honestly_and_stops_child \
  app/tests/test_speech_sessions.py::test_duplicate_key_in_completed_reply_is_not_replayed -q
# 5 failed

<workspace>/.venv/bin/python -m pytest \
  app/tests/test_speech.py::test_non_executable_worker_is_not_reported_ready -q
# 1 failed

CONTROL_PYTHON=<workspace>/.venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
<node-runtime>/dependencies/node/bin/node \
  --test --test-name-pattern='non-local speech identity|non-local engine identity|failure cleanup' \
  app/tests/browser-speech-input.test.mjs
# 0 passed, 3 failed
```

After the patch, strict duplicate-key parsing applies to manifest, native reply, and replay JSON.
Manifest paths reject symlink components, selected runtime files are regular files, the worker must
be executable, and file identity must remain unchanged across hashing and before/after process
launch. The browser now requires the exact `whisper.cpp`/`base`/`ko` identity and strict session and
transcription response shapes. A new start waits for the prior session close, preserving the user's
typed text and avoiding the busy race. No native capture bridge was added because the controlled
WebAudio path did not demonstrate a capture failure.

These checks establish unchanged authorized path identity around launch, not executed-byte
attestation. `Popen` and the dynamic loader still consume pathnames. A swap-and-restore race is not
cryptographically excluded, and the runtime manifest is not itself a production trust anchor.

## Controlled regression results

Baseline before the new tests:

```text
<workspace>/.venv/bin/python -m pytest \
  app/tests/test_speech.py app/tests/test_speech_sessions.py app/tests/test_speech_api.py -q
# 66 passed, 1 pre-existing Starlette/AnyIO deprecation warning, 2.74s

CONTROL_PYTHON=<workspace>/.venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
<node-runtime>/dependencies/node/bin/node \
  --test app/tests/browser-speech-input.test.mjs
# 13 passed, 0 failed, 80.594s
```

Green runs after the fix:

```text
<workspace>/.venv/bin/python -m pytest \
  app/tests/test_speech.py app/tests/test_speech_sessions.py app/tests/test_speech_api.py -q
# 72 passed, 1 pre-existing Starlette/AnyIO deprecation warning, 1.92s

CONTROL_PYTHON=<workspace>/.venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
<node-runtime>/dependencies/node/bin/node \
  --test --test-name-pattern='non-local speech identity|non-local engine identity|failure cleanup' \
  app/tests/browser-speech-input.test.mjs
# 3 passed, 0 failed, 12.192s

CONTROL_PYTHON=<workspace>/.venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
<node-runtime>/dependencies/node/bin/node \
  --test --test-name-pattern='native keyboard controls' app/tests/browser-speech-input.test.mjs
# 1 passed, 0 failed, 2.806s

<workspace>/.venv/bin/python -m pytest \
  app/tests/test_speech.py app/tests/test_speech_sessions.py app/tests/test_speech_api.py -q
# final: 72 passed, 1 pre-existing Starlette/AnyIO deprecation warning, 1.78s

CONTROL_PYTHON=<workspace>/.venv/bin/python \
CONTROL_PLAYWRIGHT_MODULE=<node-runtime>/dependencies/node/node_modules/playwright/index.mjs \
<node-runtime>/dependencies/node/bin/node \
  --test app/tests/browser-speech-input.test.mjs
# final after the last production edit: 17 passed, 0 failed, 82.907s
```

The browser suite uses local Chrome with a generated fake audio device. It covers explicit action
before permission, 16/44.1/48 kHz worklet conversion, bounded chunks and request queue, interim vs
final display, no duplicate insertion, Korean composition and simultaneous typing, cursor edits,
cancel/work-switch/visibility late-response isolation, immediate track stop, session contention,
failure retry, close warnings, keyboard Enter/Space operation, text status, and no external request.
Python covers 0.25–8 second chunks, a 128-request session cap, five-minute action-triggered expiry,
one active session, cancellation, process timeout/ownership, retry/replay, restart interruption,
and verifies that PCM bytes are absent from SQLite and events.

An initial attempt with `/opt/homebrew/bin/python3` failed collection because it lacked the locked
application dependencies; an attempt with the bundled document Python lacked `pytest`/`uvicorn`.
Neither is counted as a product result. The repository's existing `.venv` was then used explicitly.

## Existing local-engine synthetic canary

The canary generated “오늘은 파란 공 세 개를 상자에 넣습니다.” with the installed Yuna voice,
converted it locally with `/usr/bin/afconvert` to mono PCM16LE 16 kHz, and called `Speech.transcribe`
against the existing app-specific runtime. It did not invoke an HTTP/provider path.

```text
<workspace>/.venv/bin/python - <<'PY'
# tempfile.TemporaryDirectory; /usr/bin/say; /usr/bin/afconvert;
# Speech(Store(temp_vault), runtime_dir=existing_development_runtime).transcribe(pcm)
PY
# ready=True; pcm_bytes=88352
# pcm_sha256=87871badf3a91af723639848435a4f0b9f33f1ecd8c1670d46d4b144f34dbd67
# text=' 오늘은 파란 공세기를 상자에 넣습니다.'
# engine=whisper.cpp; model=base; language=ko; elapsed_ms=450
```

This confirms a real local worker/model invocation, while reproducing the known `세 개` → `세기`
recognition error. It is not a real microphone, noise, long-form, latency-distribution, or Korean
accuracy pass.

## Observed identities

```text
packaging/macos/component-manifest.json
  95e0cad92263a4fd88995b1261a39d614533eb9b5016445c2a7d023c104a4ceb
development runtime manifest
  23a080c019a0d9d686a1a7eaa5888f7ab675f579faa08320284b959a05837f05
development speech-worker
  fde97c5b90b97995db96cbc0c208994dcbd75b94e2d95c47162710c9cc7867b7
development whisper framework binary
  b9a8fa21567837f785aad230b7014e353d4d7d1e28db941e4d36cfd9e722ad53
development ggml-base.bin
  60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe
```

The component manifest pins whisper.cpp source and the model, but its selected source-build
`built_cli_sha256` is still null. The development runtime was prepared from the separately recorded
XCFramework alternative and is not a fresh product package. Caller/runtime manifest hashes do not
establish production manifest trust.

## Mandatory remaining qualification

- T025 must produce a GUI-only fresh install whose bundled worker/library/model identities match the
  selected locked release components; end users must not run the existing developer setup CLI.
- Exercise the actual packaged host's microphone entitlement/permission and WebKit/WebAudio route.
  Only a demonstrated failure there can justify a native capture bridge.
- Run consented physical-microphone tests across the supported macOS/device matrix, including Korean
  composition, speech/noise/long utterances, denial, disconnect, sleep/restart, cancel, and latency.
- Independently audit the runtime-manifest trust anchor and remaining pathname TOCTOU/dynamic-loader
  boundary. Do not infer code signing, notarization, redistribution, sandbox inheritance, or exact
  executed-component attestation from this development canary.

Accordingly, this slice is code-audit-ready but **not T024 closure-ready as packaged product
qualification**.
