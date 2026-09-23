# T052 — in-place own-version editors with revision-safe autosave (2026-09-23)

## What landed

### Server (`app/services/alternative_drafts.py`)

These are draft routes in `runs-v1`, four in total; the installed route count went from 46 to 50.

- **Drafts**:
  - A draft copies one exact run artifact: a text/markdown/JSON artifact as text, a CSV artifact
    as a table of cells.
  - Revision n is record version n of the draft (an `artifact` record carrying
    `alternative_draft`), linked to revision n-1. Two screens saving from the same revision collide
    on the same identity, so the second gets `conflict` and nothing is overwritten.
  - Each save is idempotent per command id. A reused command with different content gets
    `conflict`.
  - No reason or instruction is required.
  - The draft list also returns the original's content, so the editor never asks for raw bytes.
    It is bounded to 256 KiB; anything larger gets `too_large`.
- **Freeze**:
  - It freezes exactly the revision the owner saw (`expected_revision`), then goes through
    `accept_own_alternative` against the boundary the run recorded: the manifest's work revision
    and environment, and the result record as output.
  - Inputs, handoffs, tools and model bindings, which this server does not trace, are stated as
    observation gaps.
  - By default the changed lines (`text_span`) or cells (`table_range`) become selectors with
    `proposed` alignment bound to the original digest: coverage is `partial`, and the rest is
    stated as unreviewed.
  - `whole` is claimed only when the owner sets `reviewed_whole`.
  - An unchanged copy, a non-editable format and a stale revision are all refused.
- The web boundary raises the body limit only for draft saves (`is_draft_save`), to 600 KB. Every
  other run route keeps 4 KiB.

### GUI (`app/static/alternatives.mjs`)

It is mounted on the observe page (`#run-alternative`), opened from the artifact viewer's
"내 버전 편집" button.

- Text is edited in a textarea; a table is edited cell by cell, with a button to add rows.
- Autosave runs after 800 ms and names the revision it edited from. Text typed during a save stays
  unsaved.
- On `conflict` the owner's text is kept, and the editor offers to load the newest revision or to
  save the current text as a new draft.
- It tells the owner that no reason is needed.
- Freeze is an explicit button:
  - It saves first.
  - The "reviewed the whole" checkbox is off by default.
  - The result states how many changed places were recorded as evidence, that the rest is
    unreviewed, and that impact is investigated separately.
- All text reaches the DOM through textContent or form values only.

## Observed

- `test_alternative_drafts_api.py`: **4 passed**. It covers revisions, idempotency, stale-tab
  conflict, the original left unchanged, the partial selectors, whole coverage only when set, and
  refusal of an unchanged copy, the wrong format, a binary artifact, a bad revision start, both
  bodies at once, a missing draft and an oversize text.
- `alternatives.test.mjs`: **6 passed**.
- The affected Python suites passed: route counts, runs, artifacts, works, exports, assets, server
  and first party (224 passed).

## Remaining elsewhere

- PDF, image, structured and time selectors are T053.
- The three-view switch, refresh, conflict and stale-range browser cases are T054.
- The actual-user versus synthetic evidence labeling is also T054.

## T053 — PDF/image/structured/time selectors and alternative-file flows (same day)

- **Server**: `POST …/runs/{run}/artifacts/{aid}/alternative-files` (`alternative-file-v1`). The
  file travels base64-encoded, up to 4 MiB decoded; the boundary limit is raised to 5.6 MB for
  this route only.
- The file is sealed as an `alternative_file` artifact record plus its blob, and then goes through
  `accept_own_alternative` in the same transaction, sharing `_seal_alternative` with the editor's
  freeze.
- Selectors must fit the original's format:

  | Original format | Selector kinds accepted | Locator |
  | --- | --- | --- |
  | PDF | `page_region` | page 1..10 000 plus an integer basis-point region (0..10 000) |
  | image | `image_region` | integer basis-point region (0..10 000) |
  | JSON | `structured_path` | RFC 6901 pointer |
  | JSON, text | `text_span` | line span |
  | CSV | `table_range` | row and column range |
  | audio or video | `time_range` | start_ms < end_ms ≤ 24 h |

- Every selector is stored with alignment **`unresolved`**, and the response carries a note saying
  so. The server computes no semantic alignment, so it never claims one.
- A format with no formal selector is answered whole or not at all.
- Refused: the same bytes, an empty file, a region that leaves the original, a float coordinate,
  an invalid pointer, and a name containing path characters.
- A replay of the same command is idempotent; different bytes under that command get `conflict`.
- **GUI** (`app/static/alternative-file.mjs`): the viewer's "대안 파일 올리기" opens the form on
  the observe page.
  - Region fields are typed as percentages and converted to basis points, validated before
    sending. Each region is added to a readable list.
  - The page states that alignment stays "미정" (unresolved).
  - Formats without selectors say whole only. "Reviewed the whole" is off by default.
  - The file bytes are never read for rendering.
- Observed: `test_alternative_drafts_api.py` **6 passed** (2 new), `alternative-file.test.mjs`
  **3 passed**, and the affected suites 217 passed.
