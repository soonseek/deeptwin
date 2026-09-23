# T074 partial — records in a real browser (2026-09-23)

Status: **the cases this server can run are in `app/tests/browser-records.test.mjs`;
T074 stays open.**

Setup/source/candidate/lens/round/approval export, PDF redaction and interrupted restore are
not run here. The server does not yet collect those categories (they are honestly
`unavailable` in the preview), no backup worker is connected, and no PDF redaction exists.

## What runs

Everything runs in real Chromium against the real supported server. The fixture is
`app/tests/fixtures/alternatives_server.py`: it bootstraps the owner, and the owner's own
consent and run routes start the run.

1. **Export.** A work is saved through the work screen. Its description carries a canary.
   The owner opens the preview, ticks the consent box bound to it, exports, and the test
   downloads the bundle.
   - The digest shown on screen equals the SHA-256 of the downloaded bytes.
   - The bundle is unzipped member by member through `CONTROL_PYTHON`'s zipfile.
   - With raw inclusion off, the preview says metadata only, and no member contains the
     canary, the owner's password, the bootstrap capability or the CSRF token. The raw zip
     bytes contain neither the password nor the capability.
   - With raw inclusion chosen, the preview says the original is included and the canary is
     in the bundle. The session secrets are still absent.
2. **Stale preview.** A second tab revises the work after the preview. Consenting and
   exporting on the first tab is refused with the stale message, and no download link
   appears.
3. **Records page.** The log lists the vault's actual public events (`run.started`,
   `approval.decided`). The backup and retention sections state that no backup worker is
   connected and that there is no automatic deletion. No page errors occur.

## Defect found and fixed

The records page's log never rendered against the real server. The server's public event
projection carries `observed_at_utc` and no `error_code`, but `records-page.mjs` required
`recorded_at_utc`, so every real page showed "기록을 불러오지 못했습니다". The unit test's fake
events carried the wrong field, which is why it passed. The page now reads `observed_at_utc`,
and the fake events match the real projection.

## Observed

- `browser-records.test.mjs`: **2 passed**, in Linux Chromium through the `chrome` channel
  symlink.
- `records-page.test.mjs`: 3 passed.

This is synthetic test-actor evidence, not user evidence.
