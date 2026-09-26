// T045 in a real browser against the real supported server: two runs are started through
// the owner's own consent and run routes (one produced a three-page PDF and a text note,
// the other a DOCX). The observe page previews the PDF as the page image the isolated
// document worker — a separate process reached over the cp-document frame channel —
// rendered, pages to page 2 and back, shows the DOCX as the worker's extracted text, and
// the vault-wide index (on the records page since UI phase 4) lists all three artifacts across
// both runs, filters them by type and opens any listed one on its run's screen, in the viewer. Scripted test actor only: synthetic evidence of the
// mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /PREVIEWS_SEED=(\{[^\n]*\})\nPREVIEWS_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-previews-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Artifact previews fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/artifact_previews_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 30000, label: 'Artifact previews fixture' });
  const [, seedText, url] = READY.exec(announced);
  const seed = JSON.parse(seedText);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1400 } });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  const runIds = await page.evaluate(async ({ base, seed }) => {
    const session = await (await fetch(base + 'session')).json();
    const headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token };
    const ids = [];
    for (const graph of seed.graphs) {
      const consent = await (await fetch(base + 'api/v1/run-consents', { method: 'POST', headers, body: JSON.stringify({
        schema_version: 'run-consent-command-v1', command_id: crypto.randomUUID(), graph_ref: graph,
        work_revision_ref: seed.refs.work_revision_ref, environment_ref: seed.refs.environment_ref,
        budget_policy_ref: seed.refs.budget_policy_ref }) })).json();
      const run = await (await fetch(base + 'api/v1/runs', { method: 'POST', headers, body: JSON.stringify({
        command_id: crypto.randomUUID(), graph_ref: graph, ...seed.refs, consent_ref: consent.ref }) })).json();
      ids.push(run.run_id);
    }
    return ids;
  }, { base, seed });
  for (const id of runIds) assert.match(id, /^[0-9a-f-]{36}$/);
  return { page, url, errors, runIds };
}

async function imageLoaded(page, selector) {
  await page.waitForFunction(sel => {
    const image = document.querySelector(sel);
    return image && image.complete && image.naturalWidth > 0;
  }, selector);
  return page.evaluate(sel => {
    const image = document.querySelector(sel);
    return { width: image.naturalWidth, height: image.naturalHeight, src: image.getAttribute('src') };
  }, selector);
}

test('a PDF page rendered by the isolated worker, page navigation, DOCX text and the vault-wide index', { timeout: 120000 }, async t => {
  const { page, url, errors, runIds } = await open(t);
  await page.goto(url + 'observe.html');
  await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runIds[0]);
  const paper = page.locator('#run-artifacts li', { hasText: 'paper ·' });
  await paper.getByRole('button', { name: '미리보기' }).click();
  const viewer = page.locator('#run-artifacts .artifact-viewer');
  await viewer.getByText('전체 3쪽 중 1쪽 표시', { exact: false }).waitFor();
  const first = await imageLoaded(page, '#run-artifacts img.artifact-page');
  assert.match(first.src, /\/pages\/1\/image$/);
  assert.ok(Math.max(first.width, first.height) <= 1200 && first.width > 100, JSON.stringify(first));
  assert.match(await viewer.textContent(), /문서 변환 워커|isolated document worker/);
  assert.match(await viewer.textContent(), /미리보기 SHA-256 [0-9a-f]{12}/);
  // the image the page shows is exactly the worker's PNG the server disclosed
  const digests = await page.evaluate(async ({ src, base, runId }) => {
    const bytes = new Uint8Array(await (await fetch(src)).arrayBuffer());
    const hex = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(b => b.toString(16).padStart(2, '0')).join('');
    const listed = await (await fetch(`${base}api/v1/runs/${runId}/artifacts`)).json();
    const paper = listed.artifacts.find(item => item.role === 'paper');
    const disclosed = await (await fetch(`${base}api/v1/runs/${runId}/artifacts/${paper.artifact_id}/pages/1`)).json();
    return { hex, disclosed: disclosed.preview.sha256, magic: [...bytes.slice(0, 4)] };
  }, { src: first.src, base, runId: runIds[0] });
  assert.equal(digests.hex, digests.disclosed);
  assert.deepEqual(digests.magic, [0x89, 0x50, 0x4e, 0x47]);
  await page.getByRole('button', { name: '다음 쪽' }).click();
  await viewer.getByText('전체 3쪽 중 2쪽 표시', { exact: false }).waitFor();
  const second = await imageLoaded(page, '#run-artifacts img.artifact-page[data-page="2"]');
  assert.match(second.src, /\/pages\/2\/image$/);
  await page.getByRole('button', { name: '다음 쪽' }).click();
  await viewer.getByText('전체 3쪽 중 3쪽 표시', { exact: false }).waitFor();
  assert.equal(await page.getByRole('button', { name: '다음 쪽' }).isDisabled(), true);
  await page.getByRole('button', { name: '이전 쪽' }).click();
  await viewer.getByText('전체 3쪽 중 2쪽 표시', { exact: false }).waitFor();
  await viewer.screenshot({ path: join(tmpdir(), 'deeptwin-t045-pdf-page.png') });

  // the vault-wide index lists every run's artifacts and opens any one. UI phase 4: it lives on the
  // records page (the run page shows only its own run); a row opens its run's screen with the
  // artifact previewed
  assert.equal(await page.locator('#artifact-index').count(), 0);
  await page.goto(url + 'records.html');
  const index = page.locator('#artifacts');
  await index.getByText('산출물 3개 중 3개 표시', { exact: false }).waitFor();
  await index.getByRole('combobox', { name: '산출물 형식 필터' }).selectOption('application/pdf');
  await index.getByText('산출물 1개 중 1개 표시', { exact: false }).waitFor();
  await index.getByRole('combobox', { name: '산출물 형식 필터' }).selectOption('');
  await index.getByText('산출물 3개 중 3개 표시', { exact: false }).waitFor();
  const draft = index.locator('li', { hasText: 'draft ·' });
  assert.match(await draft.textContent(), new RegExp(`실행 ${runIds[1].slice(0, 8)}`));
  await index.screenshot({ path: join(tmpdir(), 'deeptwin-t045-index.png') });
  await draft.getByRole('link', { name: '실행 화면에서 열기' }).click();
  await viewer.getByText('브라우저 확인용 문서 본문', { exact: true }).waitFor();
  assert.match(await viewer.textContent(), /본문 문단 1개, 표 0개\(셀 0개\)의 텍스트/);
  assert.match(await page.locator('#run-artifacts').textContent(), /산출물 1개/);
  // and back to the PDF of the first run, from the index
  await page.goto(url + 'records.html');
  await index.locator('li', { hasText: 'paper ·' }).getByRole('link', { name: '실행 화면에서 열기' }).click();
  await viewer.getByText('전체 3쪽 중 1쪽 표시', { exact: false }).waitFor();
  await imageLoaded(page, '#run-artifacts img.artifact-page[data-page="1"]');
  assert.deepEqual(errors, []);
});
