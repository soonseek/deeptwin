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

## Gaps found, not fixed

- The work export passes `secret_canaries=[]` to `build_export_manifest`, and nothing scans
  a raw original's bytes for known secrets. A credential the owner typed into the work text
  is exported when the owner explicitly chooses raw originals. The contract's final-check
  "secret canary/탐지" over items is not implemented. In metadata-only mode it is
  excluded, as shown above.
- There is no approval GUI mounted on any page (`approvals.mjs` is logic only). The
  browser records the approval through the owner route from the page.

## Observed (2026-09-25, Linux x86_64)

- `node --test app/tests/browser-records.test.mjs` (with `CONTROL_PYTHON` and
  `CONTROL_PLAYWRIGHT_MODULE`): **4 passed**.
- `pytest app/tests/test_work_exports_api.py`: 6 passed.
- `DEEPTWIN_AGE_RUNTIME_ROOT=<verified age dir> pytest app/tests/test_backup.py
  app/tests/test_backup_key_init.py`: 35 passed.
- `node --test` over `work-export`, `records-page`, `records` and `source-deletion`: 23
  passed.
