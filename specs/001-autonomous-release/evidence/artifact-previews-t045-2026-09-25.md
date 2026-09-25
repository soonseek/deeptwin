# Evidence — T045: PDF/DOCX previews through the isolated document worker, and the vault-wide artifact index (2026-09-25)

- Task: T045 — "purpose-scoped artifact storage/preview/range reads and multi-format viewers in
  app/services/artifacts.py and app/static/artifacts.mjs; preserve originals and disclose
  derived/unsupported coverage (FR-015)".
- Before this slice (evidence/run-artifacts-t045.md, 2026-09-23): runs-v1 served a run's
  artifacts (metadata, original whole or one byte range, derived text/JSON/CSV previews, images
  to the browser); PDF/DOCX were disclosed as needing the isolated codec worker; there was no
  worker path and no vault-wide index.
- Branch `t045-previews` from `codex/ui-structure` (contains 5d73a8a).

## Frozen identities

```
0e3af01041914f9232929298961160ed9b0ec18c1359aae6bbb79f8c82a151ae  app/workers/document_channel.py
4ca42ccb5412db4a51122ccf6d79f08e2cca61b525444de6e9fe94430685dddf  app/workers/document_service.py
f7ccd495a5227af1b11f726280ecf4369c872d2308e2a6cb5ad48a0b76d61102  app/workers/document_worker_main.py
75120b2bd484599bfa808ca73d6fca559869799cee2df9f6d1ed777833443a64  app/services/run_artifacts.py
d804051588a581627eede3e5aab4046f0da57a053b1e37cb84497c2fb19b6520  app/api/runs.py
b901ee0d0c2b4c6a2f54c9155276e80bbe62d590abbb3ec8e833cfc9c442afe0  app/api/artifact_index.py
4bd37db76f49b9a76095b3c0803011ca493064b50f4fb9392ca6420e48c48fac  app/api/route_contributions/artifact-index-v1.json
3780a3e1e3b5d782a493af9f5198ae67def25e6029b78975a4a724f4bc921886  app/api/route_contributions/runs-v1.json
bc914e54c2573032608c89230b99274cc229ec22f94fa48ea4b1e174f3694197  app/static/artifacts.mjs
a6847282cd14a94aeb576b5056cdfa2bbc211daf7f5074ce3c5602bd68090e59  app/static/observe.mjs
26387fdff94a8cfd812db9500c90373e4192ae94c37dc7f008824780e64f78f9  app/tests/test_document_codec.py
cd5a6276a8438bb27a942492e0a8fa3908d3029e3f8041feaf4485c973268478  app/tests/test_document_worker_main.py
bd5f8e5382ce48affb457e5da15416219ca4a4da1bf3b3042668573664d96567  app/tests/test_run_artifact_previews.py
4c3aee6fe82d27dc9cf67f15542c4bb702a0256f843395b094e3ed43f3d99b29  app/tests/artifacts.test.mjs
d09a2e02f783993843b462fc71e21dd56e214fa8592f7c3b6773a8bc1714f003  app/tests/browser-artifact-previews.test.mjs
```

## What landed

### The document codec channel (`cp-document`) and its worker

- **Profile** (`app/workers/document_channel.py`, control side, parser-free): the fixed pair
  root `/run/deeptwin/ipc/cp-document`, responder `document` 20106:20106, pair group 21105,
  requester `control` 20102:20102 — the identities `deploy/compose.yaml` already gives the
  `document` service (`network_mode: none`, 768 MiB, 128 pids) and the `cp-document` channel of
  the root-only IPC initializer. It is the same verified machinery as the credential gateway:
  `ipc_root` generation, `listener` readiness record and socket inode, SO_PEERCRED, boot-secret
  HMAC handshake, per-frame MACs. Protocol `document-codec-v1`: one request per connection,
  `document_request` (canonical JSON header) + `document_input` chunks (32 KiB) →
  `document_result` (`ok` + result + output byte count/SHA-256/chunk count, or `ok: false` + a
  closed code) + `document_output` chunks.
- **Bounds**: input ≤ 16 MiB (refused client-side before anything is sent), output ≤ 8 MiB,
  pages 1..10 000, longest edge 64..2048 px (the control plane asks 1200), DOCX text ≤ 64 KiB
  UTF-8, 30 s operation cap, 20 s client deadline.
- **Engine** (`app/workers/document_service.py`, the only module that opens a PDF/DOCX; runs only
  in the worker process): PDF via pypdfium2 (damaged/encrypted → `content_rejected`; the page is
  checked against the real page count → `page_out_of_range` carrying that count; rasterized with
  the longest edge bounded, never upscaled past 4×; the PNG is reopened with Pillow and its size
  checked before it is sent). DOCX via python-docx after a zip guard (≤ 2 000 entries, ≤ 64 MiB
  uncompressed, ratio ≤ 200, no encrypted members, `word/document.xml` present else
  `media_unsupported`); body paragraphs and table cells in document order, cut on a character
  boundary (`truncated`). Both codecs are in the pinned locks
  (`deploy/locks/requirements-document-linux.lock`: pypdfium2 5.13.0, python-docx 1.2.0,
  pillow 12.3.0; also `app/requirements-release.lock`) — no dependency was added.
- **Client checks** without parsing: result shape, output digest over the bytes received, and for
  a PNG the signature and the IHDR size against the declared size. Closed client codes:
  `unavailable` (`sent: false`: connect/handshake failed), `transport_failed`,
  `malformed_result`, and the worker's `invalid_request|media_unsupported|page_out_of_range|
  content_rejected|render_failed|too_large`.
- **Entrypoint** (`python -m app.workers.document_worker_main --attachment-config=<abs>`): the
  exact attachment object `deeptwin-document-worker-attachment-v1` (`pair_root`,
  `requester_boot_id`) both sides read; the pair root must be the fixed profile's; binds via
  `listener.bind_worker_listener` (never creates the generation); one requester at a time;
  closed JSON-line log vocabulary (event, exception class, closed outcome code — no bytes, text,
  paths or ids); SIGTERM completes the current render, unlinks socket + readiness record, exit 0;
  exit 1 on listener loss, 2 on configuration. It imports no web/route/service code.

### Wiring into runs-v1

- `create_app(..., document_worker=)` takes a `DocumentWorkerConfiguration` (checked against the
  fixed profile; each call runs the verified connect + handshake) or the host's already built
  `DocumentCodecClient`; `app.server --document-worker-config` reads the attachment file.
  `ApplicationContext.document_codec` carries it to `PersistentRunArtifacts(codec=)`.
- `…/{artifact}/preview`: a PDF → `page_image` (page 1; the worker's PNG digest; coverage by
  page: `unit: page`, `page_count`, `covered [[1,1]]`, `omissions`, `not_rendered` = annotations'
  interactivity, links, text layer, forms, attachments); a DOCX → `document_text` (the worker's
  text and its digest; `unit: text_layer`, covered body paragraphs and table cells, omitted
  comments, footnotes, formatting, headers/footers, images, text boxes, tracked changes, and the
  text beyond the bound when truncated). Without the worker: `codec_required` with
  `reason: not_connected` (as before); worker unreachable or dialogue dropped:
  `reason: unavailable`; original over the input bound: `reason: too_large` (never sent); worker
  refusal: `codec_failed` with its code; a zip that is not a DOCX: `unsupported`. Nothing is
  rendered in the control plane in place of a page.
- New routes (runs-v1, `GET|HEAD`, `work.read`): `…/{artifact}/pages/{n}` (the page disclosure)
  and `…/{artifact}/pages/{n}/image` (the worker's PNG, `image/png`, `X-DeepTwin-Derived-SHA256`,
  inline, under the boundary's `nosniff`/`no-store`/page CSP). Page numbers are canonical
  decimals ≤ 5 digits. Codes: out of range → 416 `range_not_satisfiable`; not a PDF → 415
  `unsupported_media`; over the bound → 413 `too_large`; worker not named/unreachable → 503
  `unavailable`; worker refusal → 502 `codec_failed`. Rendered pages are cached in-process by
  (original SHA-256, page, edge), at most 16.
- The original stays as it was: served whole or by range, never transcoded.

### The vault-wide artifact index

- `artifact-index-v1` contribution (`app/api/artifact_index.py`, requires `run-artifacts.service`):
  `GET|HEAD /api/v1/artifacts?run_id=&media_type=&cursor=&limit=` — every run's artifacts (runs
  oldest first from the runtime ledger, at most 1 000 scanned; each run's artifacts in order), a
  page of 1..100 (default 25) from a decimal offset cursor, filters by exact run id and by
  declared media type (`type/subtype` or `type/*`). Each entry is the run-scoped projection plus
  `run_id`; the response discloses `total`, `next_cursor` and `runs {scanned, unreadable,
  omitted}` (a run that is not a runs-v1 run or cannot be read now is counted, never hidden
  silently). A named unknown run → 404; any other query shape → 400; no session → 401.
- Route composition: 78 → 81 installed (runs-v1 +2, artifact-index-v1 +1); pins updated in
  test_first_party.py (82 with the example), test_web_owner_integration.py (ids and contribution
  order), test_runs_api.py, test_works_api.py, test_provider_source_startup.py.

### The viewer

- `app/static/artifacts.mjs`: preview kinds `page_image` (the worker's image via
  `…/pages/{n}/image`, 이전 쪽/다음 쪽 navigation through `…/pages/{n}`, "전체 N쪽 중 n쪽 표시
  (W×H 픽셀) — 이미지에 없는 것: …"), `document_text` (text + the parts not included),
  `codec_failed`, and the three `codec_required` reasons, each in its own words; the derived
  digest is shown; new refusal messages for 416/415/413/502. `createArtifactIndex` renders the
  index (type filter, 더 보기, 열기 → the viewer's `open(run, artifact)` with the run's panel,
  graph and approvals beside it). Content still reaches the DOM only through `textContent` or
  attributes. Mounted on the observe page (`#artifact-index`).

## Tests (all serial, no network, no API calls)

- `test_document_codec.py` 17: profile = compose identities; bounded page render and real page
  count; damaged/encrypted PDFs refused; DOCX order, counts, bound and character-boundary cut;
  non-DOCX zip, zip bomb and garbage refused; client-side bounds with nothing sent; the client
  refuses a lying worker (declared size ≠ PNG, digest mismatch, unknown code); a failed connect
  is `unavailable`/unsent; attachment shape; **import boundary**: an AST check that the
  control-plane artifact path (run_artifacts, document_channel, artifact_index, runs,
  first_party_catalog, server) imports no parser or the worker engine; a subprocess check that
  the control-plane process never loads pypdfium2/pypdf/PIL/reportlab nor
  `app.workers.document_service`; the worker entrypoint loads no web/control code; and a live
  check that both previews succeed through the separate worker process while every parser entry
  point in the control-plane process is poisoned.
- `test_document_worker_main.py` 12: argv/configuration refusals exit 2 before any bind; a missing
  generation exits 1 with a class only; **real UDS (root, ran here)**: the production entrypoint
  as 20106:20106+21105 over a generation from `ipc_root.initialize_pair_root`, a requester as
  20102 renders page 2 at 500 px (digest verified) and gets `page_out_of_range` with the count;
  the fetch identity 20104 is refused by SO_PEERCRED (unsent); a wrong boot label fails the
  handshake; SIGTERM → `document_stopped`, exit 0, socket and readiness record unlinked; every
  log line ⊆ {event, class, outcome}.
- `test_run_artifact_previews.py` 8 (supported factory; worker as a separate process): page image
  and DOCX text previews with digests/coverage, page 2, original unchanged; out-of-range 416, bad
  page numbers 400, unknown view 404, not-a-PDF 415, damaged PDF 502 + `codec_failed`
  disclosure, oversize 413 + `too_large` disclosure; unnamed worker (`not_connected`, pages 503)
  and unreachable worker (`unavailable`, 503); a worker that drops the dialogue → 503 and
  `unavailable`; cache (one render for disclosure + two image reads); factory accepts only a
  configuration on the fixed pair root or a client; the index (order across runs, paging,
  filters, run filter, open through the run routes, 404/400/401, empty vault, HEAD).
- `artifacts.test.mjs` 13 (7 before): page routes, page image + navigation, DOCX text and worker
  disclosures, page refusals, index paging/filter/open, index refusal and `open`.
- `browser-artifact-previews.test.mjs` 1 (real Chromium, real server, worker as a separate
  process): two runs started through the owner's consent and run routes; the PDF's page 1 image
  loads (natural size ≤ 1200 px), its bytes' SHA-256 equals the disclosed digest and starts with
  the PNG signature; 다음 쪽 → page 2 → page 3 (다음 쪽 disabled) → 이전 쪽 → page 2; the index
  shows 3 artifacts across both runs, the PDF filter shows 1, 열기 on the DOCX of the second run
  shows the worker's extracted text, 열기 on the PDF returns to page 1; no page errors.
- Neighbours kept passing: test_runs_api, test_web_owner_integration, test_first_party,
  test_works_api, test_provider_source_startup, test_run_artifacts_api (existing disclosure case
  unchanged), test_artifacts_gui_mirror, test_web_shell_assets, test_alternative_drafts_api,
  test_artifacts_service, test_document_tools, test_router_composition,
  test_credential_gateway_main; node observe/alternatives/alternative-file/session/run-list;
  browser-graph, browser-records, browser-alternatives.

## Open (honest)

- **Deployment wiring** (T081): the `document` compose service has no command and its image is
  built outside this repository; nothing here makes that image run
  `app.workers.document_worker_main` or makes the control command pass
  `--document-worker-config`; compose.yaml is digest-pinned in the deployment recipe and was not
  changed. Until then a deployed instance keeps disclosing PDF/DOCX as `codec_required`.
- This is a fixed first-party channel, not the `artifact-codec-port-v1` extension port
  (probe/decode_projection/render_preview/encode/cancel, content-addressed outputs); a derived
  page is not stored as its own artifact record — it is re-derived (and cached in memory).
- The control-plane process still imports python-docx at start through the legacy owner-upload
  extractor (`app/domain/store.py` → `app/storage.py` → `app/ingestion.py`, pre-existing); the
  artifact preview path never calls it (poisoned-parser test), but the boundary is only
  enforced for the PDF stack at process level.
- api.md's `/artifacts/{id}/metadata|content|preview|lineage` addressing is served run-scoped;
  the index returns `run_id` for that. Lineage views wait on T053.
- Page/image/time selector regions for format differences (T055) can now build on the page
  route; not done here.
