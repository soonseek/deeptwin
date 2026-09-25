// T043 in a real browser against the real supported server (app/tests/fixtures/grants_server.py):
// the settings page's browser grants section. The owner creates a grant through the form
// (one exact address whose `q` may carry two declared values, one extra recipient, two
// tools, seven days), sees it listed with its recipients, sources, projection (a count of
// declared values — never a value), tools, expiry and state; the server's own list holds
// exactly the SHA-256 digests of the typed values and the screen never shows a value
// back. An invalid form is refused on the page without a request; the owner revokes the
// grant and it is listed as revoked with no revoke control left.
// The owner is a scripted test actor: synthetic evidence of the mechanism, never user
// evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /GRANTS_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const digest = value => createHash('sha256').update(value, 'utf8').digest('hex');

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-grants-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Grants fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/grants_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 30000, label: 'Grants fixture' });
  const [, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = [];
  page.on('request', request => requests.push(`${request.method()} ${new URL(request.url()).pathname}`));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  return { page, url, errors, requests };
}

test('browser grants: create through the settings form, list with projection and expiry, revoke',
  { timeout: 120000 }, async t => {
    const { page, url, errors, requests } = await open(t);
    await page.goto(url + 'settings.html');
    const section = page.locator('#settings-grants');
    await section.getByText('아직 만든 브라우저 접근 허가가 없습니다', { exact: false }).waitFor();
    assert.equal(await section.getByRole('heading', { name: '브라우저 접근 허가' }).count(), 1);

    // an invalid address is refused on the page: no command is sent
    const form = section.getByRole('form', { name: '새 브라우저 접근 허가' });
    await form.getByLabel('이름').fill('잘못된 허가');
    await form.getByLabel('열 수 있는 정확한 주소').fill('https://docs.example.org/search?q=already');
    const before = requests.filter(item => item === `POST ${base}api/v1/browser-grants`).length;
    await form.getByRole('button', { name: '이 내용으로 허가 만들기' }).click();
    await section.getByText('쿼리·포트·계정 없는 https 주소를 입력하세요.').waitFor();
    assert.equal(requests.filter(item => item === `POST ${base}api/v1/browser-grants`).length, before);

    // the owner's grant
    const again = section.getByRole('form', { name: '새 브라우저 접근 허가' });
    await again.getByLabel('이름').fill('공개 문서 검색');
    await again.getByLabel('열 수 있는 정확한 주소').fill('https://docs.example.org/search');
    await again.getByLabel('값이 실릴 수 있는 쿼리 매개변수').fill('q');
    await again.getByLabel('그 매개변수에 실릴 수 있는 값(한 줄에 하나)').fill('deeptwin\n공개 자료');
    await again.getByLabel('추가로 받을 수 있는 호스트').fill('cdn.example.org');
    await again.getByLabel('화면 캡처').check();
    await again.getByLabel('유효 기간(일)').fill('7');
    await again.getByRole('button', { name: '이 내용으로 허가 만들기' }).click();
    await section.getByText('허가를 만들었습니다.').waitFor();

    const row = section.locator('li[data-grant-id]');
    assert.equal(await row.count(), 1);
    assert.equal(await row.getAttribute('data-state'), 'active');
    const text = await row.textContent();
    assert.match(text, /공개 문서 검색 · 유효/);
    assert.match(text, /받는 곳: docs\.example\.org, cdn\.example\.org/);
    assert.match(text, /탐색 범위: https:\/\/docs\.example\.org\//);
    assert.match(text, /https:\/\/docs\.example\.org\/search\?q ← 선언한 값 2개 · 값은 SHA-256 요약으로만 저장되어 다시 보이지 않습니다/);
    assert.match(text, /도구: 본문 읽기, 화면 캡처/);
    assert.match(text, /만료: .*UTC/);
    const page_text = await page.locator('body').textContent();
    assert.ok(!page_text.includes('deeptwin') && !page_text.includes('공개 자료'), 'a declared value is never shown back');

    // the server's own record: exactly the digests of the typed values, and the expiry
    const listed = await page.evaluate(async base => (await fetch(base + 'api/v1/browser-grants')).json(), base);
    assert.equal(listed.grants.length, 1);
    const grant = listed.grants[0];
    assert.deepEqual(grant.recipients, ['docs.example.org', 'cdn.example.org']);
    assert.deepEqual(grant.tools, ['browser_read', 'browser_screenshot']);
    assert.deepEqual(grant.projection.entries, [{ url: 'https://docs.example.org/search',
      parameters: [{ name: 'q', source: 'owner_values' }] }]);
    assert.deepEqual(grant.projection.data_sources[0].value_sha256, [digest('deeptwin'), digest('공개 자료')].sort());
    const days = (Date.parse(grant.expires_at_utc.replace(/(\.\d{3})\d{3}Z$/, '$1Z')) - Date.now()) / 86_400_000;
    assert.ok(days > 6.9 && days <= 7.01, String(days));
    assert.ok(!JSON.stringify(listed).includes('deeptwin'));

    // revoke: the grant stays listed, revoked, with no control left
    await row.getByRole('button', { name: '이 허가 철회' }).click();
    await section.getByText('허가를 철회했습니다.', { exact: false }).waitFor();
    assert.equal(await section.locator('li[data-grant-id]').getAttribute('data-state'), 'revoked');
    assert.match(await section.locator('li[data-grant-id]').textContent(), /· 철회됨/);
    assert.equal(await section.getByRole('button', { name: '이 허가 철회' }).count(), 0);
    const after = await page.evaluate(async base => (await fetch(base + 'api/v1/browser-grants')).json(), base);
    assert.equal(after.grants[0].state, 'revoked');
    assert.deepEqual(errors, []);
  });
