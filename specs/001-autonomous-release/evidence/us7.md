# US7 records — export, secret canaries, PDF redaction, restore (T074, SC-009), 2026-09-25

Status: **partial. T074 stays open.** Candidate/lens/round export, PDF redaction and the
browser restore case are not exercised, for the reasons in the table.

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
| Candidate / lens export | — | **Not exercised.** The supported server has no route or service that produces a lens (the `lenses.py` candidates are not wired). Change candidates exist only as growth-store records seeded by tests. They are vault-scoped US6 state (`/api/v1/versions`), not linked to a work, and the work export does not collect them. `evaluation_evidence` is stated as `이 서버가 아직 모으지 않음` (`unavailable`) in the preview and manifest, never as an empty success | — |
| Round export | — | **Not exercised.** Comparison rounds are produced only by the growth-loop code (seeded directly in `test_versions_api.py`). No supported route runs one, and the work export does not collect them. The preview states this as above | — |
| Missing categories stated | Export panel `빠지는 범주와 이유` | **Pass.** It states exactly `모델 최종 응답`, `도구 관측` and `평가 근거` as `이 서버가 아직 모으지 않음` | synthetic |
| Consent bound to the preview digest | Export panel: the consent checkbox, then `이 내용으로 내보내기`. Server recomputes `preview_sha` | **Pass.** On-screen bundle SHA-256 = SHA-256 of the downloaded bytes. The manifest does not contain the bundle hash | synthetic, test actor |
| Stale preview refused | (a) A second tab revises the work after the preview (2026-09-23 case). (b) New: a run is started after the preview | **Pass.** Both show `미리보기 이후 작업이 바뀌었습니다. 다시 미리보기 하세요.`, and no download link appears. The API test also checks 409 `conflict` for (b) | synthetic, test actor |
| Bundle contents verified | Unzipped member by member with `CONTROL_PYTHON`'s zipfile | **Pass.** The exact member set is `manifest.json`, `originals/*`, `events/work-history.json`, `events/runs.json`, `artifacts/sources.json` and `alternatives/own-versions.json`. With raw off, every item is `metadata_only` | synthetic |
| Secret canaries: bundle | Canaries are planted in: a provider key string (`sk-ant-api03-CANARY…`, stored through `POST /api/v1/connections/claude/key`), the owner password, the bootstrap capability, the CSRF token, the session cookie value(s), a credential-looking value in the work text (`aws_secret_access_key=CANARY…`), the PDF file name, the PDF body and the alternative's text | **Pass.** In the metadata-only bundle, none of them appears in any decompressed member or in the raw zip bytes. With raw originals chosen, the owner's own work text is included, as chosen. The provider key, session secrets, file name, PDF body and alternative text are still absent | synthetic |
| Secret canaries: every response | `context.on('response')` records every response of the whole session, including headers and body | **Pass.** No body and no header (other than `set-cookie`) carries the provider key, password, capability or session cookie. The CSRF value appears only in `GET /session`, its own allowed issuance. The sweep is checked to read real bodies: the owner's work text is seen where it belongs | synthetic |
| PDF redaction | Export of a work with a PDF original | **Not exercised as redaction, because the export pipeline has no PDF redaction.** It never produces a `redacted` item (`redaction_summary` is `{}`). Source originals, PDF included, are never put into a work bundle. Only their kind/id/version are listed, and the PDF bytes and file name are absent. This matches operations.md §7: a format that cannot be safely re-encoded is excluded, not overlaid. Raw inclusion of a source original is not offered | synthetic |
| Interrupted restore: service level | `test_backup.py` with the real age 1.3.2 (`age` sha256 `eb7dd1b5…9b2c`, matching `deploy/manifests/age-1.3.2.json`) | **Pass: 15 of 15.** Covered cases: a flipped byte and a truncated file are refused by the external receipt before decryption; a truncated stream with a forged matching receipt fails age authentication; tampering with a forged receipt fails; a malformed receipt is refused. Every failure leaves the staging directory empty. Also: roundtrip, restored-review open without excluded state, portable one-shot identity, occupied/active target refused, and originals byte-for-byte including deletion. `test_backup_key_init.py` is included: 35 passed across both files | synthetic |
| Interrupted restore: browser | — | **Not exercised.** Restore needs the backup worker service (T070/T081). The supported app has no backup or restore route. The records page states that no backup worker is connected (checked in the 2026-09-23 case) | — |

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
(no identity input yet).
