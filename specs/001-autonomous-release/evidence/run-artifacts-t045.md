# Evidence — T045: the owner reads what a run produced (routes and viewer) (2026-09-23)

- Task: T045 — "purpose-scoped artifact storage/preview/range reads and multi-format viewers …;
  preserve originals and disclose derived/unsupported coverage (FR-015)". The value layer
  (app/services/artifacts.py, 2026-09-13) had no route, no binding to real run output and no UI.

## Frozen identities

```
521d5ff779b31988527bc99a786344a608c3e1fd4daf58318e06a1a7f7beead9  app/services/run_artifacts.py
15b74f8709194ea9fc4e5d9e9f62349cb4d3a184c7a1008b10815c6b9c400336  app/api/runs.py
c5df4a8534fb0d48e8ee5b38630f3ad3caef06eca1dc7e7589c162699d868f31  app/static/artifacts.mjs
edefccea4b3f0084de1f49f6c96fb4732a9934424b0149b415a47c612b6fc814  app/static/observe.mjs
b6a9882b40cb07d85c7a3c462fa9fe7bfd11d8f1e9b097b603b5ce4eb0127db7  app/tests/test_run_artifacts_api.py
3b78259399ed56d26c42670240aaadf4bb309967ae491b6096235abb85e530d7  app/tests/artifacts.test.mjs
```

## What landed

- **Source of truth** (`app/services/run_artifacts.py`): a run's artifacts are exactly the
  registered blobs its accepted results name — result records of kind `artifact` carrying the
  `artifacts` list the extension/provider attempt transports seal (`ordinal`, `role`,
  `media_type`, `blob`), validated strictly. IDs are `uuid5(result id, version, ordinal)`; a
  result named by several visits lists once. Owner session re-checked on every read.
- **Routes** (runs-v1 contribution, all `GET|HEAD`, `work.read`):
  `/api/v1/runs/{run}/artifacts`, `…/{artifact}`, `…/{artifact}/content` (whole, or one
  `Range: bytes=a-b` ≤ 1 MiB → 206 with `Content-Range`; out of range → 416; a multi-range or
  another unit → 400; duplicate `Range` headers refused at the boundary),
  `…/{artifact}/preview`. The original is served as-is, **always as an attachment**, typed
  `image/png|jpeg` only when its bytes carry that magic and `application/octet-stream`
  otherwise, with `nosniff` and a `sandbox` CSP — a worker-produced HTML file declared as an
  image is served as octet-stream and previewed as text.
- **Previews** are derived with their own digest, a fidelity note and disclosed coverage
  (original bytes, covered spans, omissions): UTF-8 text ≤ 64 KiB (cut on a character
  boundary), JSON re-indented (depth-bounded), CSV as ≤ 200 × 50 text cells (formulas never
  evaluated). Images are left to the browser. **PDF, DOCX and other containers are never
  parsed in the control plane** — worker output is untrusted and runtime.md §6 assigns
  rendering to the isolated `artifact-codec-port-v1` worker — so they are disclosed as
  `codec_required`, with the original downloadable; unknown bytes are `unsupported`.
- **Viewer** (`app/static/artifacts.mjs`, mounted on the observe page beside the run panel):
  the list (role, node, declared type, size, digest prefix, download link) and the preview by
  kind; artifact content reaches the DOM only through `textContent` or attributes; coverage and
  fidelity shown beside every preview; stale answers never overwrite a newer run.
- **Boundary**: the supported page policy gains `img-src 'self'` (same-origin images only) so
  the viewer can show an image original; `range` joins the singleton-header list.
- The store verifies every blob a record names when it reads it, so an original whose bytes
  vanished fails the listing closed (503) rather than being listed.

## Tests

- `test_run_artifacts_api.py` 6 (list/read/content headers, byte ranges, text/JSON/CSV previews
  with digest and coverage, images/PDF/DOCX/unknown/fake-image disclosure, vanished bytes and
  foreign ids, owner session required); `test_artifacts_gui_mirror.py` 5 (preview kinds, bound,
  messages, asset catalogue, page policy mirror the server); `artifacts.test.mjs` 7;
  `observe.test.mjs` 5 (the choice now also shows the run's artifacts).
- Neighbours: shell assets, owner integration, runs/works API, first-party composition, runtime
  and run-list mirrors — 105 + 219 passed after pinning the four new route ids (39 → 43).

## Still open in T045

- PDF/DOCX/page previews through the isolated artifact codec worker (the document worker's
  service boundary, T018/T087); until then those formats are disclosed, not previewed.
- Artifacts are read per run; a vault-wide `/artifacts/{id}` index (api.md) and lineage view wait
  on the handoff/UI work (T048/T053).
