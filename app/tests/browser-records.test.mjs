// T074 (US7, SC-009), the parts this server can run today, in a real browser against the
// real supported server: a work saved through the work screen is exported through
// its actual preview and a consent bound to that preview; the downloaded bundle is
// unzipped and checked member by member. Raw text is included only when chosen;
// session secrets (the owner's password, the bootstrap capability, the CSRF token)
// and the canary never cross into a metadata-only bundle; a work revised after its
// preview is refused as stale. The records page lists the vault's public events and
// states honestly that no backup worker is connected. The last case exports every
// category the supported server produces for one work (setup/source, runs completed,
// gated+approved and failed, their consents and approvals, a frozen alternative) and
// sweeps the bundles and every response of the session for planted secret canaries.
// The owner is a scripted test actor: synthetic evidence of the mechanism, never user
// evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { base, open, openEditor, saved } from './helpers/alternatives-fixture.mjs';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const CANARY = 'CANARY-원문-7f3a9c';
const PASSWORD = 'synthetic owner passphrase';
const CAPABILITY = Buffer.alloc(32, 'T').toString('base64url');

async function unzip(t, bytes) {
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-export-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const file = join(dir, 'bundle.zip');
  await writeFile(file, bytes);
  const listed = spawnSync(process.env.CONTROL_PYTHON, ['-c', `
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    print(json.dumps({info.filename: archive.read(info).decode("utf-8", "replace") for info in archive.infolist()}))
`, file], { encoding: 'utf8' });
  assert.equal(listed.status, 0, listed.stderr);
  return JSON.parse(listed.stdout);
}

async function saveWork(page, url, text) {
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill(text);
  await page.getByRole('button', { name: '이 인스턴스에 저장' }).click();
  await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();
}

async function exportBundle(page, { raw }) {
  const panel = page.locator('#work-records');
  const rawBox = panel.locator('#export-include-raw');
  if ((await rawBox.isChecked()) !== raw) await rawBox.click();
  await panel.getByRole('button', { name: '포함될 내용 미리보기' }).click();
  await panel.locator('#export-consent').waitFor();
  const preview = await panel.locator('.export-preview').textContent();
  await panel.locator('#export-consent').check();
  await panel.getByRole('button', { name: '이 내용으로 내보내기' }).click();
  const link = panel.getByRole('link', { name: '내보낸 묶음 내려받기' });
  await link.waitFor();
  const href = await link.getAttribute('href');
  const digest = (await panel.locator('.export-digest').textContent()).replace('묶음 SHA-256 ', '');
  const bytes = Buffer.from(await page.evaluate(async target => [...new Uint8Array(await (await fetch(target)).arrayBuffer())], href));
  return { preview, bytes, digest, href };
}

test('export: actual preview, bound consent, raw only by choice, no session secret in the bundle', { timeout: 120000 }, async t => {
  const { page, url, errors } = await open(t);
  await saveWork(page, url, `분기 보고서를 정리해 주세요. ${CANARY}`);
  const csrf = await page.evaluate(async base => (await (await fetch(base + 'session')).json()).csrf_token, new URL(url).pathname);

  const metadata = await exportBundle(page, { raw: false });
  assert.match(metadata.preview, /원문 제외\(메타데이터만\)/);
  const { createHash } = await import('node:crypto');
  assert.equal(createHash('sha256').update(metadata.bytes).digest('hex'), metadata.digest);
  const members = await unzip(t, metadata.bytes);
  const all = Object.values(members).join('\n');
  assert.ok(Object.keys(members).length >= 2, JSON.stringify(Object.keys(members)));
  for (const secret of [CANARY, PASSWORD, CAPABILITY, csrf]) assert.ok(!all.includes(secret), `bundle leaked ${secret.slice(0, 8)}`);
  assert.ok(!metadata.bytes.includes(Buffer.from(PASSWORD)) && !metadata.bytes.includes(Buffer.from(CAPABILITY)));

  const withRaw = await exportBundle(page, { raw: true });
  assert.match(withRaw.preview, /원문 포함/);
  const rawAll = Object.values(await unzip(t, withRaw.bytes)).join('\n');
  assert.ok(rawAll.includes(CANARY), 'the chosen raw original is in the bundle');
  for (const secret of [PASSWORD, CAPABILITY, csrf]) assert.ok(!rawAll.includes(secret));
  assert.deepEqual(errors, []);
});

test('export: a work revised after its preview is refused as stale; records page is honest', { timeout: 120000 }, async t => {
  const { context, page, url, errors } = await open(t);
  await saveWork(page, url, '첫 설명');
  const panel = page.locator('#work-records');
  await panel.getByRole('button', { name: '포함될 내용 미리보기' }).click();
  await panel.locator('#export-consent').waitFor();
  // another tab revises the work after this preview
  const other = await context.newPage();
  await other.goto(url + 'work.html');
  await other.locator('#work-description').fill('둘째 설명');
  await other.getByRole('button', { name: '이 인스턴스에 저장' }).click();
  await other.getByText('이 인스턴스에 저장됨 · 수정본 2', { exact: false }).first().waitFor();
  await panel.locator('#export-consent').check();
  await panel.getByRole('button', { name: '이 내용으로 내보내기' }).click();
  await panel.getByText('미리보기 이후 작업이 바뀌었습니다. 다시 미리보기 하세요.', { exact: false }).first().waitFor();
  assert.equal(await panel.getByRole('link', { name: '내보낸 묶음 내려받기' }).count(), 0);

  await page.goto(url + 'records.html');
  const log = page.locator('#records-logs');
  await log.locator('li').first().waitFor();
  assert.match(await log.textContent(), /run\.started/);
  assert.match(await log.textContent(), /approval\.decided/);
  assert.match(await page.locator('#records-backup').textContent(), /백업 워커가 아직 연결되어 있지 않습니다/);
  assert.match(await page.locator('#records-retention').textContent(), /자동 삭제는 없습니다/);
  assert.deepEqual(errors, []);
});

test('an original is deleted only through its preview and consent; readers then say deleted', { timeout: 120000 }, async t => {
  const { page, url, errors } = await open(t);
  await page.goto(url + 'work.html');
  const bytes = Buffer.from('%PDF-1.7\n지울 합성 원본\0');
  await page.getByLabel('원본 자료 선택').setInputFiles({ name: '지울 원본.pdf', mimeType: 'application/pdf', buffer: bytes });
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#save-status')?.textContent.includes('수정본 2'));
  const panel = page.locator('#work-deletion');
  await panel.getByLabel('지울 원본.pdf', { exact: false }).waitFor();
  const href = await page.getByRole('link', { name: '다운로드' }).getAttribute('href');
  const status = async () => page.evaluate(async target => (await fetch(target)).status, href);
  assert.equal(await status(), 200);
  // a preview removes nothing
  await panel.getByLabel('지울 원본.pdf', { exact: false }).check();
  await panel.getByRole('button', { name: '삭제 미리보기' }).click();
  await panel.getByText('이 삭제 전에 만든 백업', { exact: true }).waitFor();
  assert.match(await panel.textContent(), /이 원본을 가리키는 수정본 1개/);
  assert.equal(await status(), 200);
  // consent is separate and off by default
  await panel.getByRole('button', { name: '선택한 원본 삭제' }).click();
  await panel.getByText('미리보기 내용에 동의해야 삭제할 수 있습니다.').waitFor();
  assert.equal(await status(), 200);
  await panel.locator('#deletion-consent').check();
  await panel.getByRole('button', { name: '선택한 원본 삭제' }).click();
  await panel.getByText('원본 1개를 삭제했고 파일 제거를 확인했습니다', { exact: false }).waitFor();
  assert.match(await panel.textContent(), /지울 원본\.pdf · .* · 삭제됨/);
  assert.equal(await status(), 410);
  // the records log shows the deletion as its own event
  await page.goto(url + 'records.html');
  await page.locator('#records-logs li').first().waitFor();
  assert.match(await page.locator('#records-logs').textContent(), /retention\.deleted/);
  assert.deepEqual(errors, []);
});

// --- T074: every category the supported server can produce, secret canaries everywhere ---
// The records fixture seeds only three stored graphs, an environment and a budget policy;
// the owner (a scripted test actor) creates everything else through the product's own
// screens and routes. All values below are synthetic.

const root = fileURLToPath(new URL('../../', import.meta.url));
const RECORDS_READY = /RECORDS_SEED=(\{[^\n]*\})\nRECORDS_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const SYNTHETIC = {
  text: 'CANARY-work-text-4b1e',
  credential: 'aws_secret_access_key=CANARY-cred-wJalrXUtnFEMI-K7MDENG',
  fileName: 'CANARY-filename-9d2c.pdf',
  pdf: 'CANARY-pdf-body-51af',
  alternative: 'CANARY-alternative-e07b',
  providerKey: 'sk-ant-api03-CANARY-provider-key-0000000000000000000000000000-AA',
};

async function openRecords(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-records-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Records fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/records_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: RECORDS_READY, timeoutMs: 30000, label: 'Records fixture' });
  const [, seedText, url] = RECORDS_READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
  // every response the browser receives, with its headers and body, for the canary sweep
  const responses = [];
  context.on('response', response => {
    const entry = { url: response.url(), method: response.request().method(), headers: response.headers() };
    responses.push(response.body().then(body => ({ ...entry, body }), () => ({ ...entry, body: Buffer.alloc(0) })));
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability, password }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password, raw_capability_b64u: capability }),
  })).status, { base, capability: CAPABILITY, password: PASSWORD });
  assert.equal(bootstrapped, 201);
  return { context, page, url, errors, responses, seed: JSON.parse(seedText) };
}

// the owner's own routes, called from the page with the session's CSRF value
async function owner(page, path, body) {
  return page.evaluate(async ({ base, path, body }) => {
    const session = await (await fetch(base + 'session')).json();
    const response = await fetch(base + path, { method: 'POST', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token } });
    return { status: response.status, body: await response.json().catch(() => null) };
  }, { base, path, body });
}

async function startRun(page, seed, graph, workRef) {
  const inputs = { graph_ref: seed.graphs[graph], work_revision_ref: workRef,
    environment_ref: seed.environment_ref, budget_policy_ref: seed.budget_policy_ref };
  const consent = await owner(page, 'api/v1/run-consents', { schema_version: 'run-consent-command-v1',
    command_id: crypto.randomUUID(), ...inputs });
  assert.equal(consent.status, 201, JSON.stringify(consent.body));
  return owner(page, 'api/v1/runs', { command_id: crypto.randomUUID(), ...inputs, consent_ref: consent.body.ref });
}

async function exportAll(page, { raw }) {
  const panel = page.locator('#work-records');
  for (const box of await panel.locator('.export-categories input[type=checkbox]').all()) {
    if (!(await box.isChecked())) await box.check();
  }
  const rawBox = panel.locator('#export-include-raw');
  if ((await rawBox.isChecked()) !== raw) await rawBox.click();
  await panel.getByRole('button', { name: '포함될 내용 미리보기' }).click();
  await panel.locator('#export-consent').waitFor();
  const items = await panel.locator('.export-items li').allTextContents();
  const missing = await panel.locator('.export-missing li').allTextContents();
  await panel.locator('#export-consent').check();
  await panel.getByRole('button', { name: '이 내용으로 내보내기' }).click();
  const link = panel.getByRole('link', { name: '내보낸 묶음 내려받기' });
  await link.waitFor();
  const href = await link.getAttribute('href');
  const digest = (await panel.locator('.export-digest').textContent()).replace('묶음 SHA-256 ', '');
  const bytes = Buffer.from(await page.evaluate(async target => [...new Uint8Array(await (await fetch(target)).arrayBuffer())], href));
  return { items, missing, bytes, digest };
}

test('export of every produced category: actual preview, bound consent, verified bundle, canaries absent everywhere', { timeout: 240000 }, async t => {
  const { context, page, url, errors, responses, seed } = await openRecords(t);
  // a provider key string held by the server (memory only), never to be echoed or exported
  const stored = await owner(page, 'api/v1/connections/claude/key', { secret: SYNTHETIC.providerKey });
  assert.equal(stored.status, 200, JSON.stringify(stored.body));
  assert.equal(stored.body.key_present, true);

  // setup/source: the work is described and a PDF original attached through the work screen
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill(`합성 업무 설명 ${SYNTHETIC.text} ${SYNTHETIC.credential}`);
  await page.getByLabel('원본 자료 선택').setInputFiles({ name: SYNTHETIC.fileName, mimeType: 'application/pdf',
    buffer: Buffer.from(`%PDF-1.7\n1 0 obj << /Title (${SYNTHETIC.pdf}) >> endobj\n(${SYNTHETIC.pdf})\n%%EOF\n`) });
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.locator('#work-deletion').getByLabel(SYNTHETIC.fileName, { exact: false }).waitFor();
  const workId = await page.evaluate(key => JSON.parse(localStorage.getItem(key)).work_id, `deeptwin:intake:${base}`);
  const work = await page.evaluate(async ({ base, id }) => (await fetch(`${base}api/v1/works/${id}`)).json(), { base, id: workId });
  assert.equal(work.ref.kind, 'work_revision');

  // runs of this work, each under its own consent (an approval): completed, gated+approved, failed
  const completed = await startRun(page, seed, 'completes', work.ref);
  assert.equal(completed.status, 201, JSON.stringify(completed.body));
  const gated = await startRun(page, seed, 'gated', work.ref);
  assert.equal(gated.body.phase, 'awaiting_human');
  const approved = await owner(page, `api/v1/runs/${gated.body.run_id}/approvals`, { command_id: crypto.randomUUID(),
    node_id: 'owner-gate', approval_scope: 'release-output', decision: 'approved' });
  assert.equal(approved.status, 201, JSON.stringify(approved.body));
  const resumed = await owner(page, `api/v1/runs/${gated.body.run_id}/resume`, { command_id: crypto.randomUUID() });
  assert.equal(resumed.body.phase, 'completed');
  const failed = await startRun(page, seed, 'fails', work.ref);
  assert.equal(failed.status, 503);  // the execution failed; the server says so without detail

  // alternative: the owner's own version of the completed run's report, frozen for analysis
  await openEditor(page, url, completed.body.run_id);
  await page.getByRole('textbox', { name: '내 버전 텍스트' }).fill(`첫 줄\n${SYNTHETIC.alternative}\n셋째 줄\n`);
  await saved(page, 1);
  await page.getByRole('button', { name: '분석용으로 고정' }).click();
  await page.getByText('내 근거로 기록했습니다.', { exact: false }).waitFor();

  // metadata-only export of every selectable category
  await page.goto(url + 'work.html');
  await page.locator('#work-records').getByRole('button', { name: '포함될 내용 미리보기' }).waitFor();
  const metadata = await exportAll(page, { raw: false });
  const shown = metadata.items.join('\n');
  assert.match(shown, /작업 설명 \d판 \(원문 제외\) · 원문 제외\(메타데이터만\)/);
  assert.match(shown, /작업 개정 기록/);
  assert.match(shown, /실행 3개 \(실패 1개\) · 실행 동의 3개 · 승인 결정 1개/);
  assert.match(shown, /첨부 자료 1개의 목록/);
  assert.match(shown, /내 버전 1개 \(범위·선택 영역만, 내용 제외\)/);
  assert.deepEqual(metadata.missing.sort(), ['도구 관측: 이 서버가 아직 모으지 않음',
    '모델 최종 응답: 이 서버가 아직 모으지 않음', '평가 근거: 이 서버가 아직 모으지 않음']);
  const { createHash } = await import('node:crypto');
  assert.equal(createHash('sha256').update(metadata.bytes).digest('hex'), metadata.digest);
  const members = await unzip(t, metadata.bytes);
  assert.deepEqual(Object.keys(members).filter(name => !name.startsWith('originals/')).sort(), [
    'alternatives/own-versions.json', 'artifacts/sources.json', 'events/runs.json', 'events/work-history.json',
    'manifest.json']);
  const runs = JSON.parse(members['events/runs.json']);
  assert.equal(runs.length, 3);
  const byId = Object.fromEntries(runs.map(run => [run.run_id, run]));
  assert.deepEqual(byId[completed.body.run_id].stops.map(stop => stop.reason_code), ['completed']);
  assert.deepEqual(byId[gated.body.run_id].approvals.map(item => [item.node_id, item.decision]), [['owner-gate', 'approved']]);
  const failures = runs.filter(run => run.stops.some(stop => stop.reason_code === 'infrastructure_failure'));
  assert.equal(failures.length, 1);
  assert.ok(![completed.body.run_id, gated.body.run_id].includes(failures[0].run_id));
  const [alternative] = JSON.parse(members['alternatives/own-versions.json']);
  assert.equal(alternative.run_id, completed.body.run_id);
  assert.equal(alternative.content, '내 버전 내용 미포함');
  assert.equal(JSON.parse(members['artifacts/sources.json']).length, 1);
  const manifest = JSON.parse(members['manifest.json']);
  assert.ok(manifest.items.every(item => item.content_mode === 'metadata_only'));
  // PDF: the pipeline has no PDF redaction; it never emits a `redacted` item and the PDF
  // original (its bytes and its file name) stays out of every bundle, listed by id only
  assert.deepEqual(manifest.redaction_summary, {});
  assert.ok(!members['manifest.json'].includes(metadata.digest), 'the manifest never carries its own bundle hash');

  const csrf = await page.evaluate(async b => (await (await fetch(b + 'session')).json()).csrf_token, base);
  const cookies = (await context.cookies()).map(cookie => cookie.value).filter(value => value.length >= 16);
  assert.ok(cookies.length >= 1, 'a session cookie exists');
  const secrets = [SYNTHETIC.providerKey, PASSWORD, CAPABILITY, csrf, ...cookies];
  const metadataText = Object.values(members).join('\n');
  for (const canary of [...secrets, SYNTHETIC.text, SYNTHETIC.credential, SYNTHETIC.fileName, SYNTHETIC.pdf,
    SYNTHETIC.alternative]) {
    assert.ok(!metadataText.includes(canary) && !metadata.bytes.includes(Buffer.from(canary)),
      `metadata bundle leaked ${canary.slice(0, 14)}`);
  }

  // raw originals only by explicit choice: the owner's own text is in, nothing else is
  const withRaw = await exportAll(page, { raw: true });
  assert.match(withRaw.items.join('\n'), /작업 설명 \d판 원문 · 원문 포함/);
  const rawText = Object.values(await unzip(t, withRaw.bytes)).join('\n');
  assert.ok(rawText.includes(SYNTHETIC.text), 'the chosen raw original is in the bundle');
  for (const canary of [...secrets, SYNTHETIC.fileName, SYNTHETIC.pdf, SYNTHETIC.alternative]) {
    assert.ok(!rawText.includes(canary) && !withRaw.bytes.includes(Buffer.from(canary)), `raw bundle leaked ${canary.slice(0, 14)}`);
  }

  // a run recorded after the preview makes that preview stale: the consent is refused
  const panel = page.locator('#work-records');
  await panel.getByRole('button', { name: '포함될 내용 미리보기' }).click();
  await panel.locator('#export-consent').waitFor();
  assert.equal((await startRun(page, seed, 'completes', work.ref)).status, 201);
  await panel.locator('#export-consent').check();
  await panel.getByRole('button', { name: '이 내용으로 내보내기' }).click();
  await panel.getByText('미리보기 이후 작업이 바뀌었습니다. 다시 미리보기 하세요.', { exact: false }).first().waitFor();
  assert.equal(await panel.getByRole('link', { name: '내보낸 묶음 내려받기' }).count(), 0);

  // no response of the whole session carries a secret; the CSRF value only in its own issuance
  const seen = await Promise.all(responses);
  assert.ok(seen.length > 20, `responses observed: ${seen.length}`);
  // the sweep reads real bodies: the owner's own work text does come back where it belongs
  assert.ok(seen.some(({ body }) => body.includes(Buffer.from(SYNTHETIC.text))));
  for (const { url: target, method, headers, body } of seen) {
    const { pathname } = new URL(target);
    const headerText = Object.entries(headers).filter(([name]) => name !== 'set-cookie')
      .map(pair => pair.join(': ')).join('\n');
    for (const secret of [SYNTHETIC.providerKey, PASSWORD, CAPABILITY, ...cookies]) {
      assert.ok(!body.includes(Buffer.from(secret)) && !headerText.includes(secret), `${method} ${pathname} leaked ${secret.slice(0, 14)}`);
    }
    if (pathname !== `${base}session`) assert.ok(!body.includes(Buffer.from(csrf)), `${method} ${pathname} carried the CSRF value`);
  }
  assert.deepEqual(errors, []);
});
