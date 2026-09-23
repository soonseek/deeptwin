# Evidence — T044 closed: bounded PDF and PNG creation with actual render inspection (2026-09-23)

- Task: T044 — "bounded declarative DOCX/CSV/JSON/PDF/image creation and safe format validation …;
  use PDF skill and actual render inspection, not file-exists-only checks (SC-004)". DOCX/CSV/JSON
  landed 2026-09-13 (evidence/document-tools-t044.md); PDF and images were deferred because the
  libraries were absent from the development environment.
- The PDF skill was loaded and followed (reportlab for creation, pypdf for reading, pypdfium2 for
  rendering; ReportLab markup tags rather than raw text).

## Dependencies — no new build input

`Pillow==12.3.0`, `pypdf==6.17.0`, `pypdfium2==5.13.0` and `reportlab==5.0.1` are exactly the
`document-worker` root set already locked in `deploy/locks/service-roots.json` and
`deploy/manifests/python-wheel-artifacts.json` (T089, with license evidence: MIT-CMU, BSD-3-Clause,
BSD). They were added to `pyproject.toml` and its generated `app/requirements.txt` projection;
`uv lock` added exactly these four and changed nothing else. `test_dependency_manifest_parity.py`
4 passed.

## Frozen identities

```
724d9fcaf7a09c14ee1a4e1417cfbd988df1bfeea5b303523aae028d588a9c7f  app/adapters/documents.py
d4a842b07357fdd33842c7f0b7e5a76a485da19bccfb0d78fe9337c6ae85350f  app/tests/test_document_tools.py
2bcc5587cbdf4eca97a5aa035c933bfb52f6707444136ae4e4e115b7643d67f2  pyproject.toml
3e0ee0c8bb6d5a13f5363c04e2a0f400f04104dd69911802edd1d39110627d39  uv.lock
b5fc15d97b5bd00cf9b1936d1c82f69506329eeff4020b0f06f30a4373caa4f2  app/requirements.txt
```

## What landed (app/adapters/documents.py)

- `render_pdf(spec, path)` — the DOCX spec (title, paragraphs, tables; one shared parser now).
  Adobe's Korean CID font (`HYSMyeongJo-Medium`) draws Hangul and Latin; `invariant=1` output
  (equal specs give equal bytes). Declared text is **data, never markup**: escaped before layout,
  so `<b>`, `<font>` and `&amp;` stay literal. Inspection reopens the produced bytes three ways:
  pypdf parses it and bounds pages (≤ 50); pdfium's text layer must hold the title, every
  paragraph and every cell in declared order (whitespace-insensitive, as layout wraps); every
  page is rasterized at 2× and **every declared visible character must leave ink inside the box
  the text layer gives it** — a glyph the font cannot draw fails the render.
- `render_png(spec, path)` — a bounded declarative canvas (≤ 4096² px, ≤ 256 filled rectangles,
  integer RGB). Reopened, format/size checked, every shape's centre sampled against the last
  shape drawn there, and the background corner checked; the sampled pixels are the report.
- `validate_format(path, "pdf")` — magic bytes; a regex scan refusing action/script/embedded-file/
  form names (`JavaScript`, `JS`, `OpenAction`, `AA`, `Launch`, `EmbeddedFile(s)`, `RichMedia`,
  `XFA`, `SubmitForm`, `ImportData`, `GoToR`, `GoToE`, `URI`) at a name boundary; strict pypdf
  parse; encryption refused; catalog `/OpenAction`, `/AA`, `/AcroForm`, `/Names` refused; and —
  because names inside compressed object streams escape a byte scan — any page carrying
  `/Annots` or `/AA` refused. `validate_format(path, "png")` — magic, Pillow parse and `verify()`,
  the side bound, decompression-bomb errors refused.

## Tests (app/tests/test_document_tools.py): 20 passed

Hangul + table PDF found by text layer and rasterization, byte-identical re-render; markup is
data; a 60-paragraph document wraps across pages and is still found in order; a blanked
rasterization fails with "no ink" (the inspection is real); bounded specs; four hostile catalog
payloads refused as active content; a link annotation added through pypdf and written with
compressed objects refused; truncated/mislabelled PDFs refused; PNG pixels sampled including an
overlap; bounded image specs; truncated, over-sized and mislabelled PNGs refused.

## Not claimed

- The Korean CID font is referenced, not embedded: pdfium, Chrome and Acrobat substitute it; a
  viewer with no Korean font cannot draw Hangul. Embedding a font file is a font-closure decision
  for the document worker image (T081/T084), not made here.
- The document worker's service boundary (T018/T087) and the artifact viewers (T045/T053) are
  separate tasks; this is the adapter they will call.
