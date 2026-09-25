# US7 records — export, secret canaries, PDF redaction, restore (T074, SC-009), 2026-09-25

Status (updated 2026-09-25, T074 rest): **every T074 case is now exercised; T074 is ticked.**
The rows below marked *superseded* were the earlier gaps; the section
"T074 rest: candidate/lens, rounds, PDF redaction, interrupted restore" at the end has the
dated cases that close them, and its "Still not claimed" list what stays open.

Everything in the browser runs in real Chromium (the `chrome` channel) against the real
supported server (`create_app`). The owner is a scripted **test actor** and every value is
**synthetic**: this is evidence that the mechanism works, not user evidence.

## Surfaces

- `app/tests/browser-records.test.mjs` has 4 cases. Three are the earlier 2026-09-23 cases.
  The new one is `export of every produced category…`.
- `app/tests/fixtures/records_server.py` is the new fixture. It seeds only what no owner
  route creates:
  - three stored graphs: one that completes with a text and a CSV artifact, one with a
    human gate, and one whose handlers raise;
  - one environment;
  - one budget policy.

  The browser does everything else through the product's screens and routes: it
  bootstraps, stores the provider key, saves the work and its PDF on the work screen,
  consents to and starts each run, records the approval, resumes, edits and freezes the
  alternative on the observe screen, previews, consents and downloads.
- `app/tests/test_work_exports_api.py::test_the_runs_of_the_work_are_exported_with_their_stops_consents_and_approvals`
  runs the same run, consent and approval routes through the ASGI client.
- `app/tests/test_backup.py` covers restore at the service level, using the real age 1.3.2
  runtime (`DEEPTWIN_AGE_RUNTIME_ROOT`).

## Per-case table

| Case | Exercised surface | Result | Label |
|---|---|---|---|
| Setup/source export | Work screen: the description and a PDF original are saved. Export panel preview, then the bundle | **Pass.** The preview lists `작업 설명 N판 (원문 제외)`, `작업 개정 기록` and `첨부 자료 1개의 목록`. The bundle has `originals/*.json`, `events/work-history.json` and `artifacts/sources.json` (the source listed by kind/id/version only) | synthetic, test actor |
| Run export: completed, gated + approved, failed | Owner routes `run-consents`, `runs`, `runs/{id}/approvals` and `runs/{id}/resume`, called from the page. Export panel | **Pass.** The preview lists `실행 3개 (실패 1개) · 실행 동의 3개 · 승인 결정 1개`. `events/runs.json` has the completed run's `completed` stop, the gated run's `owner-gate approved` approval, and exactly one run whose stop is `infrastructure_failure`. Each run carries its consent id, decided time and revocation state. The handler's failure text is absent | synthetic, test actor |
| Approval export | As above: each run's consent is an `approval.decided`, and the gate decision is an `action_approval` | **Pass** (inside `events/runs.json`) | synthetic, test actor |
| Alternative export | Observe screen: edit the completed run's report, autosave, `분석용으로 고정`. Export panel | **Pass.** `내 버전 1개 (범위·선택 영역만, 내용 제외)`. The bundle names the run, and its content is `내 버전 내용 미포함`. The alternative's text canary is absent | synthetic, test actor |
| Candidate / lens export | — | *Superseded 2026-09-25 (see the last section).* **Not exercised.** The supported server has no route or service that produces a lens (the `lenses.py` candidates are not wired). Change candidates exist only as growth-store records seeded by tests. They are vault-scoped US6 state (`/api/v1/versions`), not linked to a work, and the work export does not collect them. `evaluation_evidence` is stated as `이 서버가 아직 모으지 않음` (`unavailable`) in the preview and manifest, never as an empty success | — |
| Round export | — | *Superseded 2026-09-25 (see the last section).* **Not exercised.** Comparison rounds are produced only by the growth-loop code (seeded directly in `test_versions_api.py`). No supported route runs one, and the work export does not collect them. The preview states this as above | — |
| Missing categories stated | Export panel `빠지는 범주와 이유` | **Pass.** It states exactly `모델 최종 응답`, `도구 관측` and `평가 근거` as `이 서버가 아직 모으지 않음` | synthetic |
| Consent bound to the preview digest | Export panel: the consent checkbox, then `이 내용으로 내보내기`. Server recomputes `preview_sha` | **Pass.** On-screen bundle SHA-256 = SHA-256 of the downloaded bytes. The manifest does not contain the bundle hash | synthetic, test actor |
| Stale preview refused | (a) A second tab revises the work after the preview (2026-09-23 case). (b) New: a run is started after the preview | **Pass.** Both show `미리보기 이후 작업이 바뀌었습니다. 다시 미리보기 하세요.`, and no download link appears. The API test also checks 409 `conflict` for (b) | synthetic, test actor |
| Bundle contents verified | Unzipped member by member with `CONTROL_PYTHON`'s zipfile | **Pass.** The exact member set is `manifest.json`, `originals/*`, `events/work-history.json`, `events/runs.json`, `artifacts/sources.json` and `alternatives/own-versions.json`. With raw off, every item is `metadata_only` | synthetic |
| Secret canaries: bundle | Canaries are planted in: a provider key string (`sk-ant-api03-CANARY…`, stored through `POST /api/v1/connections/claude/key`), the owner password, the bootstrap capability, the CSRF token, the session cookie value(s), a credential-looking value in the work text (`aws_secret_access_key=CANARY…`), the PDF file name, the PDF body and the alternative's text | **Pass.** In the metadata-only bundle, none of them appears in any decompressed member or in the raw zip bytes. With raw originals chosen, the owner's own work text is included, as chosen. The provider key, session secrets, file name, PDF body and alternative text are still absent | synthetic |
| Secret canaries: every response | `context.on('response')` records every response of the whole session, including headers and body | **Pass.** No body and no header (other than `set-cookie`) carries the provider key, password, capability or session cookie. The CSRF value appears only in `GET /session`, its own allowed issuance. The sweep is checked to read real bodies: the owner's work text is seen where it belongs | synthetic |
| PDF redaction | Export of a work with a PDF original | *Superseded 2026-09-25 (see the last section).* **Not exercised as redaction, because the export pipeline has no PDF redaction.** It never produces a `redacted` item (`redaction_summary` is `{}`). Source originals, PDF included, are never put into a work bundle. Only their kind/id/version are listed, and the PDF bytes and file name are absent. This matches operations.md §7: a format that cannot be safely re-encoded is excluded, not overlaid. Raw inclusion of a source original is not offered | synthetic |
| Interrupted restore: service level | `test_backup.py` with the real age 1.3.2 (`age` sha256 `eb7dd1b5…9b2c`, matching `deploy/manifests/age-1.3.2.json`) | **Pass: 15 of 15.** Covered cases: a flipped byte and a truncated file are refused by the external receipt before decryption; a truncated stream with a forged matching receipt fails age authentication; tampering with a forged receipt fails; a malformed receipt is refused. Every failure leaves the staging directory empty. Also: roundtrip, restored-review open without excluded state, portable one-shot identity, occupied/active target refused, and originals byte-for-byte including deletion. `test_backup_key_init.py` is included: 35 passed across both files | synthetic |
| Interrupted restore: browser | — | *Superseded: tampered restore 2026-09-25 (backup section), interrupted upload 2026-09-25 (last section).* **Not exercised.** Restore needs the backup worker service (T070/T081). The supported app has no backup or restore route. The records page states that no backup worker is connected (checked in the 2026-09-23 case) | — |

## Defect found and fixed

The work export's `events` category left out the work's runs and said nothing about it.
The preview listed only the work's revision history as the whole of `events`, with no
missing-evidence entry. So a work that had completed, failed and approved runs exported
as if none of them existed.

`PersistentWorkExports._runs` now collects them. It reads the run manifests whose
`work_revision_ref` names this work. For each run it adds:

- its start time;
- each `run.stopped` correlated to the run's command after its start, with the closed
  reason code;
- its consent, with decided and revoked times;
- the action approvals recorded on it.

These are written into `events/runs.json` as metadata only (identities, times and closed
codes, never graph, artifact or model content). The file is covered by the preview digest,
so a run, stop or approval recorded after the preview makes the consent stale.

When a work has no runs, the bundle is unchanged. The existing exact-member tests still
pass.

## Gaps found (2026-09-25 audit)

- ~~The work export passes `secret_canaries=[]` and nothing scans a raw original for
  secrets.~~ **Fixed the same day**; see "Secret scan over raw originals" below.
- ~~There is no approval GUI mounted on any page.~~ **Fixed the same day**: the observe page
  has an approval screen (evidence/approval-screen-2026-09-25.md). The records case above
  still records its approval through the owner route; `browser-approvals.test.mjs` records a
  gate approval and a rejection through the screen.

## Secret scan over raw originals (2026-09-25)

`app/services/export_secret_scan.py` runs over every raw original the export would carry, at
preview time and again inside the confirmation's writer. Only when `include_raw` is chosen;
a metadata-only export is not scanned and is unchanged (`secret_scan: null`).

- **What it finds.** Credential shapes: `sk-ant-…` (anthropic_api_key), `sk-…`/`sk-proj-…`
  (provider_api_key), AWS access key ids (`AKIA…`/`ASIA…` and the other IAM prefixes),
  `aws_secret_access_key = …` assignments (any case, quoted or not), PEM `-----BEGIN … PRIVATE
  KEY-----` headers and `Bearer …` tokens. The instance's own secrets, without reading any new
  secret: each 43-character base64url candidate is hashed and compared with the stored
  `owner_auth_sessions.token_digest` (session cookie tokens, `instance_session_token`) and with
  the bootstrap capability verifier (`instance_bootstrap_capability`), through
  `PersistentOwnerAuthority.recognizes_secret`, which returns only a closed kind.
- **Not found.** CSRF values: the server stores no session token to derive them from (only
  token digests), so they cannot be checked without holding a new secret. The provider key is
  held in memory only and has no stored digest; it is caught by its `sk-ant-` shape, not by
  identity. Generic high-entropy strings are not flagged.
- **Bounded, deterministic.** At most 200 000 characters per original (the rest is an
  `unscanned_text` finding), at most 64 instance-secret candidates (the rest is an
  `unscanned_candidates` finding), at most 32 findings shown (`truncated: true` beyond);
  linear regular expressions without nested quantifiers; findings ordered by position.
- **What the owner sees.** `secret_scan.findings`: `relative_path`, `kind`, `line`, `column`,
  never the matched value; the export panel lists them as e.g. `AWS 비밀 액세스 키 지정 · 작업
  설명 1판 1행 32열`. The digest `findings_sha` covers the work id and the exact finding list
  (revisions are immutable, so the path names exact bytes).
- **Withheld unless confirmed.** A raw original with a finding is exported as its metadata-only
  item (label `(비밀로 보이는 값이 있어 원문 제외)`), with a `redacted` missing entry for
  `originals`. The owner can tick `위에 표시된 비밀 의심 값을 확인했고…` and re-preview; the
  preview carries `acknowledged_findings_sha` for the SAME selection, the server recomputes the
  findings and includes the raw original only if the digest equals the current finding set
  (otherwise `conflict`). The scan (with `confirmed`) is inside the preview digest, the
  confirmation must carry the same `acknowledged_findings_sha` (a preview without it cannot be
  confirmed with it, and vice versa: `conflict`), and the consent record stores
  `confirmed_secret_findings_sha`. A new revision changes the finding set and the old
  confirmation no longer holds.
- **Canaries.** When findings are withheld, their matched values are passed as
  `secret_canaries` to `build_export_manifest` (at most 64), so the manifest check refuses a
  manifest that would carry one.

| Case | Surface | Result | Label |
|---|---|---|---|
| Shapes found, value never shown | `test_export_secret_scan.py` (5) | **Pass.** Every shape with exact line/column; near misses (`task-ant`, `sk-short`, `AKIA123`, `bearer of news`, a bare `aws_secret_access_key`) are not findings; bounds as above | synthetic |
| Withheld without confirmation | `test_work_exports_api.py::test_a_raw_original_with_a_secret_is_withheld_and_the_value_never_shown` | **Pass.** Findings `anthropic_api_key 2:4`, `aws_secret_access_key 3:3`; the item is metadata-only; neither value is in the preview, the receipt or any bundle member | synthetic |
| Only the exact set confirms | `…::test_only_the_exact_confirmed_finding_set_includes_the_raw_original`, `…::test_a_new_revision_changes_the_finding_set…` | **Pass.** A wrong digest is 409, one without raw 400, a malformed one 400; the confirmed preview has a different `preview_sha`, still never shows the value; the confirmation without the digest is 409; with it the raw original (value included) is in the bundle, not in the manifest; the consent record binds the digest; a new revision makes the old digest 409 | synthetic |
| Instance secrets by digest | `…::test_the_instance_own_session_token_and_capability_are_recognised_by_digest` | **Pass.** The live session cookie token and the bootstrap capability typed into the work text are found as `instance_session_token` / `instance_bootstrap_capability`; an unrelated 43-character string is not; neither value appears in the response | synthetic |
| Metadata-only unaffected | `…::test_a_metadata_only_export_is_not_scanned_and_unchanged` | **Pass.** `secret_scan: null`, unchanged label, exports | synthetic |
| Export panel | `work-export.test.mjs` (+2) | **Pass.** Findings by kind and location; the confirmation is its own unchecked box; re-preview sends the shown selection with the digest; the confirmation carries it; a withheld preview exports without it | synthetic |
| Real browser | `browser-records.test.mjs` case 4, extended | **Pass.** With raw chosen, the panel lists `AWS 비밀 액세스 키 지정 · 작업 설명 1판 1행 32열` and the same for 2판 (the PDF attachment made a second revision); every original is `원문 제외`; `작업 설명 원문: 가림 처리됨`; the panel text and the bundle (every member and the raw zip bytes) do not contain the credential value or the work text. After ticking the confirmation and re-previewing, the bundle has the work text and the credential as typed, and still none of the provider key, password, capability, CSRF, cookies, PDF name/body or alternative text. No export preview or confirmation response of the session carries the credential value | synthetic, test actor |

## Observed (2026-09-25, Linux x86_64)

Secret scan and approval screen (later the same day):

- `node --test app/tests/browser-records.test.mjs`: **4 passed**; with
  `browser-graph` and `browser-approvals`: 6 passed; `browser-alternatives`,
  `browser-inquiry`, `browser-performance`: 5 passed.
- `pytest app/tests/test_work_exports_api.py`: 11 passed; with `test_export.py`,
  `test_execution_approval_route.py`, `test_run_approvals.py`, `test_web_owner_integration.py`,
  `test_first_party.py`, `test_web_shell_assets.py`, `test_export_secret_scan.py`,
  `test_works_api.py` and `test_run_approval_api.py`: 212 passed.
- `node --test` over `work-export`, `approval-screen`, `observe`, `approvals`,
  `approvals-execution`, `records`, `records-page`, `source-deletion`, `work`: 82 passed.

Earlier:

- `node --test app/tests/browser-records.test.mjs` (with `CONTROL_PYTHON` and
  `CONTROL_PLAYWRIGHT_MODULE`): **4 passed**.
- `pytest app/tests/test_work_exports_api.py`: 6 passed.
- `DEEPTWIN_AGE_RUNTIME_ROOT=<verified age dir> pytest app/tests/test_backup.py
  app/tests/test_backup_key_init.py`: 35 passed.
- `node --test` over `work-export`, `records-page`, `records` and `source-deletion`: 23
  passed.

## Browser backup and staged restore (2026-09-25, later)

The row "Interrupted restore: browser" above was `Not exercised` because there was no backup
worker. That gap is now closed for `instance_backup_key`. The details are in
`evidence/backup-age-t070-2026-09-23.md` §2026-09-25.

| Case | Exercised surface | Result | Label |
|---|---|---|---|
| Backup create through the screen | `app/tests/browser-backup.test.mjs`, real Chromium, real supported app as 20102, real backup-crypto worker process as 20111 in an empty network namespace over the verified `cp-backup` channel | **Pass.** The preview shows the included categories with row counts and the excluded categories with reasons, and no work text. Consent is off by default and bound to the preview digest. The encrypted bundle SHA-256 equals the receipt. No work-text canary, password or capability bytes appear in the bundle | synthetic, test actor |
| Restore screen: staged review | Same case: upload the receipt and the bundle | **Pass.** `restored_review`, dispatch blocked. The new-owner bootstrap, re-created connections/service clients and explicit environment reactivation are each shown as `필요`. The active instance is unchanged | synthetic, test actor |
| Interrupted/tampered restore: browser | Same case: a byte-flipped bundle against the true receipt | **Pass.** `복원하지 못했습니다. 스테이징 영역에 아무것도 남기지 않았습니다.` | synthetic |
| Stream interruption across the process boundary | `test_backup_crypto_worker.py` (control child 20102, worker 20111) | **Pass.** A cut stream gives no ciphertext. A lying digest and an extra frame each give `stream_invalid`. The worker keeps serving | synthetic |

Observed: `browser-backup.test.mjs` 1 passed; `browser-records.test.mjs` 4 passed;
`test_backup_crypto_worker.py` 37 passed; `test_backups_api.py` 5 passed;
`records-backup.test.mjs` 7 passed. Not exercised: portable-recovery restore through the browser
(no identity input yet). This was closed later the same day; see the next section.

## Retention screen, settings hub and portable restore (2026-09-25, T073)

This closes the T073 open items "retention and settings screens", "backup cleanup" and
"portable_recovery has no browser input". As above, the owner is a scripted **test actor**
and every value is **synthetic**.

What the server now does:

- **Retention state.** `GET /api/v1/retention` is part of the new `retention-v1`
  contribution (`app/api/retention.py`, `app/services/retention_cleanup.py`). It reads what
  the vault and the data directory actually hold. For each category it states what is
  kept, for how long, that nothing is deleted automatically, and whether and where the
  owner may clean it up:
  - **Core records** (records, lineage, the event log) are kept forever
    (`core_mode = manual_only`) and are never offered for cleanup. The record store is
    append-only, and other records rest on them.
  - **Deletion tombstones** are never offered.
  - **Originals** are deleted only on the work screen, with their own preview.
  - **Encrypted backups** are kept until the owner cleans them up. The newest one is always
    kept.
  - **Staged restores** (failed, abandoned for over an hour, or a decrypted copy waiting
    for review) are kept until the owner cleans them up.
  - **Regenerable caches** and **raw audio** are not stored, so there is nothing to clean.
- **Owner cleanup** mirrors source deletion:
  - The server computes the preview: the exact items and bytes, what goes and what stays,
    what it cannot reach (copies already downloaded), what is never deleted, and a digest
    over all of that plus the request id and the reason.
  - The cleanup needs `confirmed: true` and that exact digest. It recomputes the preview
    under the backup lock, so a changed scope answers 409 and a gone item answers 404.
  - It then writes a tombstone for each item: `{backup_id}.deleted.json` next to the kept
    receipt and consent, or a restore status of `discarded` next to the kept receipt.
  - It commits the core `retention.deleted` event (`object_count`, `byte_count`), and only
    after that removes the bytes. The cleanup receipt, holding the preview shown, the
    consent and what was removed, is kept under `retention/`.
  - The same request replays its receipt.
  - The ciphertext of a removed backup answers 404. Its receipt still downloads.
- **Portable restore.** `POST /api/v1/backups/restores/{id}/portable-bundle` (a
  `backups-v1` route) takes one `application/octet-stream` body: the owner's kept age
  identity as the first LF-terminated line, then the encrypted bundle.
  - The identity is checked as a native X25519 identity before the worker is asked. A
    malformed one answers 400.
  - It is wrapped in `OneShotIdentity`, used for one worker decrypt and then wiped. It is
    never written to disk, to a status, to an error or to a log.
  - `restore_begin` now accepts `portable_recovery` receipts. The plain `/bundle` route
    refuses a portable restore, and the portable route refuses an instance-key restore.
  - Limit: the ASGI request body is an immutable `bytes` object, so its copy of the
    identity cannot be zeroed and lives until garbage collection.
- **Browser.**
  - The records page's retention section (`app/static/records-retention.mjs`) shows each
    category and the eligible items. Nothing is preselected and kept items are disabled.
    It shows the server's preview and a separate consent box that is unchecked by default.
    After a cleanup it refreshes the backup list, where a removed backup offers only its
    receipt.
  - The restore screen has a masked `type=password` input for the kept identity. The input
    is read once and cleared at once. The identity is framed into the upload and the sent
    buffer is zeroed after the upload. It is never put in an attribute, a status,
    `localStorage` or `sessionStorage`.
  - The settings hub (`settings.html` + `app/static/settings.mjs`) is linked from the header
    of every page (work, observe, records, versions, settings, start; the preview shell
    `index.html` too). It lists the event log, export, backup/restore, retention/cleanup,
    account/session, the Claude connection and API credentials. Each is a plain link with no
    order or prerequisite, marked `data-required="false"`. The hub states that no work ends
    in a required export. With a session it adds the server's own backup and retention state.

| Case | Exercised surface | Result | Label |
|---|---|---|---|
| Retention state per category | `test_retention_cleanup_api.py`; `browser-retention.test.mjs` (real Chromium, real supported app as 20102, real backup-crypto worker as 20111 in an empty network namespace) | **Pass.** 7 categories, each `automatic_deletion=never`. Core records: `forever`/`not_offered`. Counts come from the server, never content | synthetic, test actor |
| Cleanup preview → consent → cleanup | Same browser case: 2 backups made through the screen plus 1 failed restore (tampered bundle). The older backup and the failed restore are ticked | **Pass.** The newest backup's box is disabled. The preview lists 2 items with what goes and what stays, and removes nothing. Without the consent box: `미리보기 내용에 동의해야 정리할 수 있습니다.` With it: cleaned. Older ciphertext 404, its receipt 200, newest 200, restore `discarded`, `retention.deleted` in the event log, the saved work reads back | synthetic, test actor |
| Stale/foreign scope | `test_retention_cleanup_api.py` | **Pass.** Wrong digest 409. `confirmed:false` 400. The newest backup or a fresh restore 409. An item already cleaned by another request 404. A reason changed after the preview 409. The same request replays its receipt | synthetic |
| Portable restore: API | `test_backups_api.py` (real age 1.3.2, the worker's own dialogue code) | **Pass.** A wrong identity gives `failed`/`restore_failed` and stages nothing. The kept identity gives `restored_review` with dispatch blocked. A second upload 409. The identity bytes are in no response and in no file under the data directory. Malformed lines 400 | synthetic |
| Portable restore: browser | `browser-backup.test.mjs` second case. The fixture makes a `portable_recovery` backup of a separate synthetic vault with a fresh identity | **Pass.** With no identity, nothing is sent. With a wrong one, refused. With the kept one, staged review with every required step shown. The input is empty after reading. The identity is not in the DOM, browser storage or any response the page saw | synthetic, test actor |
| Settings hub navigation | `browser-retention.test.mjs` second case | **Pass.** From the work, observe, records, versions and settings pages, the header `설정` link opens the hub. The 7 entries all have `data-required="false"`. The live backup/retention lines are shown. The log, backup, retention, account and export entries each open their section. `start.html` carries the same link | synthetic, test actor |

Observed (Linux x86_64, `DEEPTWIN_AGE_RUNTIME_ROOT` = the verified age 1.3.2):

- `pytest` over `test_backups_api.py`, `test_backup_crypto_worker.py`, `test_backup.py`,
  `test_source_deletions.py`, `test_retention.py`, `test_retention_cleanup_api.py`,
  `test_work_exports_api.py`, `test_records_contract_mirror.py`, `test_web_shell_assets.py` and
  `test_core_import_boundary.py`: 135 passed. Of these, `test_backups_api.py` has 6 and
  `test_retention_cleanup_api.py` has 4.
- The route-count set (`test_first_party.py`, `test_web_owner_integration.py`,
  `test_runs_api.py`, `test_works_api.py`, `test_provider_source_startup.py`,
  `test_web_shell_assets.py`): 183 passed. There are 98 installed routes: 94, plus 3
  retention routes, plus 1 portable upload.
- The composition/mirror/boundary set (credential import boundary, deployment/provider
  receipt API, document codec, first-party dependencies, the four GUI mirrors, router
  composition, owner material intake): 178 passed.
- `node --test` over the 31 non-browser `.test.mjs` files: 236 passed. That includes
  `records-retention.test.mjs` 5, `records-backup.test.mjs` 9 and `settings.test.mjs` 7.
- Real browser: `browser-backup.test.mjs` 2 passed; `browser-retention.test.mjs` 2 passed;
  `browser-records.test.mjs` 4 passed. The header change was also run against
  `browser-first-use`, `browser-owner-lifecycle-t025`, `browser-owner-recovery-t025`,
  `browser-versions`, `browser-owner-material-intake` and `browser-first-use-integration-t023`:
  24 passed.

Not done, stated rather than claimed:

- There is no deletion of core records other than originals. The domain store is
  append-only. `app/operations/retention.py`'s `delete_items` is a value-layer ledger with
  no persisted counterpart.
- There is no cache cleanup, because this server stores no regenerable cache on disk.
- Portable backup *creation* is still not offered on the screen. Only instance-key backups
  are made here.

## T074 rest: candidate/lens, rounds, PDF redaction, interrupted restore (2026-09-25)

This closes the four T074 cases still open above. As everywhere in this file, the owner is
a scripted **test actor** and every value is **synthetic**; the design pool, its generator
and critic, and the comparison rounds are test-actor seeds made through the real
persistence functions (the product has no route that generates designs or drives growth
rounds, so no user or model produced any of them). This is evidence that the export,
redaction and restore mechanisms work, not user evidence.

What the server now does:

- **Design and lens export** (`app/services/work_export_records.py`, category
  `evaluation_evidence`, metadata only):
  - *Scope rule.* A design request names its target by the content hash of a work model; a
    stored `work_model` record names the exact work revision it was drafted from. A request
    belongs to a work exactly when its `work_model_ref` is the design ref of a `work_model`
    record over a revision of that work. Under it the store's own lineage is followed:
    generation calls → candidates → recorded criticism and owner derivations → derived
    candidates → their criticism; design approvals are matched by the candidate they approve.
  - `evaluation/design-requests.json`: each request (id, version, work model, revision,
    requested count, disposition), its generation calls with the **generator identity**,
    every candidate (id, version, graph id/version/digest — never the graph body — parents,
    audited lens refs, applied effects, which derivation made it), each **verdict as
    recorded** (`basis: recorded`, `re_verified_by_export: false`, status, closed reasons,
    **critic identities** and profile digests from its call records, lens-use rule states),
    every derivation (action, parents; an owner instruction only as `지시 내용 미포함` + its
    length) and every design approval (candidate, environment id, verdict digest, time,
    the critic qualification's status). Re-verifying a verdict needs the issued request,
    which the store cannot rebuild, so the export says it did not.
  - `evaluation/lenses.json`: every lens a candidate audited or a critic used, resolved
    against the reviewed bundle (`docs/lenses`, `LensRegistry.from_markdown`): definition
    and review state when the id/version/hash is the loaded one (`current`), otherwise
    `differs_from_bundle` / `not_in_bundle` / `registry_unavailable`.
- **Round export** (same module, `evaluation/rounds.json`). *Scope rule:* a comparison round
  is bound to an environment, not a work; it is exported with a work exactly when its frozen
  plan's `baseline_environment` is (id, version, sha256) an environment one of this work's
  runs ran in. Other rounds are only counted (`outside_scope_round_count`). With a round come
  its lineage's experiment (the newest loop revision), validity and reasons, metric vector
  and utility, which nodes each item changed (node ids — never node results), and the G-14
  per-item outcomes with each effect's isolation boundary identity (tool id/version, effect
  class, boundary, digests) when the round involved tool effects; otherwise
  `item_outcomes_state: no_tool_effects`.
- **PDF redaction** (`app/services/work_export_sources.py`, worker ops in
  `app/workers/document_service.py`). operations.md §7: an overlay that leaves the original
  data is a failure; a format that cannot be safely re-encoded, stripped and re-verified is
  included raw only by explicit choice, or excluded.
  - Attached originals enter an export only by a new explicit choice,
    `include_source_originals` (only with `include_raw`; the panel checkbox `첨부 원본도 포함`).
  - The control plane never parses a PDF (pinned by the AST and process import tests in
    `test_document_codec.py`, which now include the export modules, and by an export run
    with every PDF parser poisoned in-process). The isolated document worker extracts each
    page's text layer one PDFium character index at a time (`extract_pdf_text`); the secret
    scan runs over it with spans (`scan_text_spans`).
  - On an unconfirmed finding the worker makes a **new image-only PDF** (`redact_pdf`): every
    page rasterized at 144 dpi, each matched span painted over with an opaque box, written by
    Pillow with no metadata — no text layer, info, links, forms or attachments survive. The
    worker reopens it and requires the same page count, zero text characters and every box
    dark when re-rendered. The control plane then has the worker extract the copy again,
    rescans it, and checks the copy's bytes for every matched value. Only then is it
    exported as `redacted` (`originals/sources/source-N.redacted.pdf`), labelled `원본과 같지
    않음`, with a `redacted` missing entry, `redaction_summary` and a reproduction limit.
    The copy is deterministic (the preview digest covers its bytes).
  - A clean PDF is exported raw. A rotated or oversized page, a bounded scan
    (`unscanned_text`), a damaged/encrypted PDF (`content_rejected`), any format with no scan
    (images, archives, DOCX), or no document worker at all: excluded with the stated reason.
    If the owner confirms that exact finding set (the existing confirmation flow, whose digest
    now covers PDF findings too), the original PDF is exported as chosen.
  - The file name of an attached original is never exported (generic paths only).
- **Interrupted restore.** The web boundary buffers a bundle upload before routing it. When
  the client disconnects before the declared body is complete, it now drops the partial
  body and, for an authenticated owner request (the same cookie + CSRF check), calls
  `BackupService.restore_interrupted`: an `awaiting_bundle` restore becomes `failed`
  (`restore_failed`, `interrupted_after_bytes`), only if its directory holds nothing but its
  status and receipt. It is then cleanable at once (`failed_restore`) instead of waiting an
  hour as an abandoned upload, and cannot be resumed; a fresh restore starts over. The
  restore screen has an `업로드 중단` button (AbortController) and reads the failed restore
  back instead of assuming.

| Case (2026-09-25) | Exercised surface | Result | Label |
|---|---|---|---|
| Candidate/lens export: browser | `browser-records.test.mjs` case "design candidates, recorded verdicts, lenses, growth rounds and a redacted PDF…" (called case 7 here; real Chromium, real supported app; the records fixture with `--growth-rounds`). The owner saves the work with a PDF on the work screen; the test-owned fixture route seeds the test-actor design pool over that work's actual revision; the owner's own `derivations` / `reviews` / `preparations` routes select, re-review (scripted test-actor critic) and prepare one candidate (test-actor critic qualification) | **Pass.** Preview item `설계 요청 1개 · 후보 5개 · 기록된 평가 5개(평가자 test-actor-critic, 다시 검증하지 않음) · 파생 1개 · 설계 승인 1개 · 원문 제외(메타데이터만)` and `참조한 렌즈 정의 1개 (판본·검토 상태)`. In the bundle: the request bound to the work's revision, both generation calls by `test-actor-generator`, the rejected candidate's verdict `recorded` / not re-verified / `rejected` by `test-actor-critic`, the derived candidate linked to its derivation, the approval of that candidate, no graph body; lens `L-P032-01@draft-1` `current`, `effect_status: not_validated` | synthetic, test actor |
| Candidate/lens export: API | `test_work_exports_api.py::test_the_design_records_of_the_work_are_exported_as_recorded_with_their_lenses` | **Pass.** Also an `edit` derivation: its owner instruction canary is absent (`지시 내용 미포함`, re-review required). Another work of the vault exports none of it | synthetic, test actor |
| Round export: browser | Same case 7: the fixture ran two paired rounds (valid; candidate run crashed → invalid) over the fixture's environment and one over an unrelated environment; the owner's run of the work used the fixture's environment | **Pass.** `이 작업의 실행 환경에서 한 비교 2개 · 실험 1개 (… · 다른 환경의 비교 1개는 범위 밖)`; `rounds.json` has the two round ids in order, validities `valid`/`invalid`, the environment id/version, `outside_scope_round_count: 1`, the lineage's experiment; no node result text (`quality=`) anywhere in the bundle | synthetic, test actor |
| Round export: API | `…::test_growth_rounds_are_exported_by_the_environment_scope_rule`, `…::test_a_round_item_outcome_keeps_its_boundaries_and_drops_everything_else` | **Pass.** Same scope rule; the invalid round is completed but not counted (`non_improving_valid_count` 0); a work without runs in that environment exports no round; an item outcome keeps outcome, reasons and each effect's boundary identity and drops a tool's result | synthetic |
| PDF redaction: browser | Same case 7: a real two-page PDF (reportlab) whose page 2 carries `aws_secret_access_key=CANARY…`, attached under a canary file name; export with raw + attached originals | **Pass.** Finding `AWS 비밀 액세스 키 지정 · 첨부 원본 1 2쪽 2행 N열`; item `첨부 원본 1 (PDF 가림 사본: 비밀 의심 값 1곳을 덮은 이미지 PDF, 텍스트 층 없음, 원본과 같지 않음) · 가림 처리`; the reason list states the copy's limits. The bundle holds `source-1.redacted.pdf`, not the original; re-extracted on the test side (pypdfium2) its pages are `['', '']`; the canary value and the file name are in no member and not in the zip bytes; `redaction_summary {originals: 1}`. After the owner confirms that exact finding set, the original PDF is exported byte-identical (`원문 포함`); the file name still never | synthetic, test actor |
| PDF redaction: API and worker | `test_work_exports_api.py` (3 new: redacted copy / damaged PDF / PNG / confirmation; no worker → excluded; parsers poisoned in the control-plane process with the worker as its own process), `test_document_codec.py` (3 new: per-page extraction; image-only, deterministic, dark-box, no-metadata copy; refusals for out-of-range, missing page, rotated page, malformed ranges before sending) | **Pass.** | synthetic |
| Interrupted restore: browser | `browser-records.test.mjs` case "an interrupted restore upload…" (case 8 here) over the backup fixture (real backup-crypto worker as its own networkless process). Chromium's own network throttling (CDP `Network.emulateNetworkConditions`, upload ≈ bundle/30 s) keeps the upload streaming; the owner presses `업로드 중단` after 2.5 s | **Pass.** The server received **32 768 of 491 832** bundle bytes before the cut. The screen shows `업로드를 중단했습니다. 이 복원은 실패로 기록되었고 스테이징 영역에 아무것도 남지 않았으며…` and the server's own failure text; the restore is `failed`/`restore_failed`; retention lists it `eligible`, `failed_restore`, 0 bytes; the same session reads the saved work unchanged; a fresh restore through the screen stages `restored_review` | synthetic, test actor |
| Interrupted restore: API | `test_backups_api.py::test_an_upload_cut_mid_stream_fails_its_restore_stages_nothing_and_a_fresh_restore_works` (real age 1.3.2; the real ASGI app driven with a partial body then `http.disconnect`) | **Pass.** A disconnect carrying a wrong CSRF value marks nothing; the owner's marks the restore failed with `interrupted_after_bytes`, its directory holds only status and receipt, it is cleanable, a re-upload to it is 409, a fresh restore stages for review, the data directory is unchanged | synthetic |

Still not claimed (open, stated rather than hidden):

- No production path generates design candidates or drives growth rounds; both families
  are exported from test-actor seeds made through the real persistence functions. Item
  outcomes with isolation boundaries are exported by the tested projection, but the rounds
  in the browser case involved no tool effects (`item_outcomes_state: no_tool_effects`).
- Verdicts are exported as recorded, not re-folded (the issued request cannot be rebuilt
  from the store).
- Redaction covers only what the scan finds (credential shapes and the instance's own
  secrets); it is a raster copy that loses every text layer. Plain-text attachments with a
  finding are withheld, not redacted; DOCX/images are never scanned and so never included.
- A run's completion-evaluation evidence is still not collected (`unavailable`).
- CSRF values still cannot be recognised by the scan (unchanged from above).

Observed (Linux x86_64, `DEEPTWIN_AGE_RUNTIME_ROOT` = the verified age 1.3.2):

- Real browser: `browser-records.test.mjs` **6 passed** (the 4 earlier cases + the two new
  ones, called cases 7 and 8 above in the order of this file's tables); with `browser-backup`
  (2) and `browser-retention` (2): 10 passed. `browser-design-workspace`,
  `browser-artifact-previews`, `browser-growth`, `browser-versions`,
  `browser-owner-material-intake` together with `browser-records`: 20 passed.
- `pytest` over `test_work_exports_api.py` (21), `test_export.py`, `test_export_secret_scan.py`,
  `test_backups_api.py` (7), `test_retention_cleanup_api.py`, `test_document_codec.py` (21),
  `test_document_tools.py`, `test_document_worker_main.py`, `test_design_workspace_api.py`,
  `test_backup.py`, `test_backup_crypto_worker.py`, `test_records_contract_mirror.py`,
  `test_web_shell_assets.py`, `test_core_import_boundary.py`, plus the route-count and
  neighbouring sets (`test_first_party.py`, `test_web_owner_integration.py`, `test_runs_api.py`,
  `test_works_api.py`, `test_provider_source_startup.py`, `test_owner_material_intake.py`,
  `test_source_deletions.py`, `test_run_artifact_previews.py`, `test_versions_api.py`,
  `test_growth_chain_store.py`, `test_design_persistence.py`, `test_router_composition.py`,
  `test_retention.py`), run serially: **477 passed**. No route was added (the fixture's
  `/__test__/seed-design` is a wrapper in front of the test app, not a product route).
- `node --test` over the 31 non-browser `.test.mjs` files: 241 passed (`work-export` 10,
  `records-backup` 10).
