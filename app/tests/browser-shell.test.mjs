// 2026-09-26 UI phase 2 in real Chromium against the real supported server (the performance
// fixture: an owner, a 20-node run, a long public event log). Every signed-in page carries
// the one app shell: the same navigation with the current page marked `aria-current="page"`,
// no "개발 미리보기" banner, no sideways overflow. Below 1024px the navigation folds behind a
// menu button, opens as a drawer that takes focus and makes the page inert, and closes with
// Escape, returning focus to the button. The settings page holds the sections moved off the
// records page, one panel at a time, and the records page keeps only the log and export.
// The owner is a scripted test actor: synthetic evidence of the mechanism, never user evidence.

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
const READY = /PERFORMANCE_SEED=(\{[^\n]*\})\nPERFORMANCE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const PAGES = [['work.html', 'work', '업무'], ['observe.html', 'observe', '실행'], ['versions.html', 'versions', '버전·실험'],
  ['records.html', 'records', '기록'], ['settings.html', 'settings', '설정']];
const MOVED = ['records-account', 'records-connection', 'records-credentials', 'records-budgets', 'records-backup',
  'records-retention', 'records-update', 'settings-extensions', 'settings-grants'];

async function openFixture(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-shell-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Shell fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/performance_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Shell fixture' });
  const [, seedText, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  return { page, url, seed: JSON.parse(seedText), errors };
}

const noOverflow = page => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);

test('the app shell: one navigation on every signed-in page, the current page marked, no preview banner, both themes',
  { timeout: 180000 }, async t => {
    const { page, url, errors } = await openFixture(t);
    for (const [file, id, label] of PAGES) {
      for (const colorScheme of ['light', 'dark']) {
        await page.emulateMedia({ colorScheme });
        await page.goto(url + file);
        const nav = page.getByRole('navigation', { name: '주 메뉴' });
        await nav.waitFor();
        assert.deepEqual(await nav.getByRole('link').allTextContents(), ['DeepTwin', '업무', '실행', '버전·실험', '기록', '설정'], file);
        const current = nav.locator('[aria-current="page"]');
        assert.equal(await current.count(), 1, file);
        assert.equal(await current.getAttribute('href'), `./${file}`);
        assert.equal((await current.textContent()).trim(), label);
        assert.equal(await page.getByRole('button', { name: '메뉴 열기' }).isVisible(), false, 'the rail is shown on a wide screen');
        const text = await page.locator('body').innerText();
        assert.doesNotMatch(text, /개발 미리보기/, file);
        assert.equal(await page.locator('.development-preview').count(), 0, file);
        assert.equal(await noOverflow(page), true, `${file} ${colorScheme}`);
        const surface = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--color-surface').trim());
        assert.equal(surface, colorScheme === 'dark' ? '#0e171b' : '#f3f6f6', `${file} ${colorScheme}`);
        // a skip link leads to the page's own content
        assert.equal(await page.locator('a.skip-link').getAttribute('href'), '#main');
      }
    }
    await page.emulateMedia({ colorScheme: 'light' });
    // the start screen stays outside the shell and carries no preview banner either
    const start = await page.evaluate(async base => (await fetch(base + 'start.html')).text(), base);
    assert.doesNotMatch(start, /개발 미리보기|development-preview/);
    assert.doesNotMatch(start, /ui-shell/);
    assert.deepEqual(errors, []);
  });

test('below 1024px the navigation folds behind a menu button; the drawer takes focus and Escape returns it',
  { timeout: 120000 }, async t => {
    const { page, url, errors } = await openFixture(t);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(url + 'observe.html');
    const menu = page.getByRole('button', { name: '메뉴 열기' });
    const nav = page.locator('#shell-nav');
    await menu.waitFor();
    assert.equal(await nav.isVisible(), false, 'folded on a narrow screen');
    assert.equal(await menu.getAttribute('aria-expanded'), 'false');
    assert.equal(await noOverflow(page), true);
    // keyboard: focus the button, open with Enter
    await menu.focus();
    await page.keyboard.press('Enter');
    await nav.waitFor();
    assert.equal(await menu.getAttribute('aria-expanded'), 'true');
    assert.equal(await page.evaluate(() => document.activeElement?.getAttribute('aria-current')), 'page');
    assert.equal(await page.evaluate(() => document.activeElement?.textContent.trim()), '실행');
    assert.equal(await page.evaluate(() => document.getElementById('main').inert), true, 'the page behind the drawer is inert');
    await page.keyboard.press('Escape');
    await nav.waitFor({ state: 'hidden' });
    assert.equal(await menu.getAttribute('aria-expanded'), 'false');
    assert.equal(await page.evaluate(() => document.activeElement?.classList.contains('shell-menu-button')), true, 'focus returns to the menu button');
    assert.equal(await page.evaluate(() => document.getElementById('main').inert), false);
    // the close button and a link work from the drawer too
    await menu.click();
    await page.getByRole('button', { name: '메뉴 닫기' }).click();
    await nav.waitFor({ state: 'hidden' });
    await menu.click();
    await nav.getByRole('link', { name: '기록' }).click();
    await page.waitForURL(`${url}records.html`);
    await page.locator('#records-logs li').first().waitFor();
    assert.equal(await page.locator('#shell-nav').isVisible(), false, 'a new page starts folded');
    // just under the breakpoint it is still folded; at 1024 the rail is back and the button gone
    await page.setViewportSize({ width: 1023, height: 844 });
    assert.equal(await page.locator('#shell-nav').isVisible(), false);
    await page.setViewportSize({ width: 1024, height: 844 });
    await page.locator('#shell-nav').waitFor();
    assert.equal(await page.getByRole('button', { name: '메뉴 열기' }).isVisible(), false);
    for (const [file] of PAGES) {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto(url + file);
      await page.getByRole('button', { name: '메뉴 열기' }).waitFor();
      assert.equal(await noOverflow(page), true, `${file} at 390px`);
    }
    assert.deepEqual(errors, []);
  });

test('settings holds the sections moved off the records page, one panel at a time; records keeps the log and export',
  { timeout: 180000 }, async t => {
    const { page, url, errors, seed } = await openFixture(t);
    await page.goto(url + 'records.html');
    await page.locator('#records-logs li').first().waitFor();
    for (const id of MOVED) assert.equal(await page.locator(`#${id}`).count(), 0, `${id} is not on the records page`);
    assert.equal(await page.locator('#records-export').getByRole('link', { name: '업무 화면에서 내보내기' }).getAttribute('href'),
      './work.html#work-records');
    // one event: a sentence for the owner, the raw type folded under 기술 정보
    const row = page.locator('#records-logs li[data-event-type="work.revised"]').first();
    const reading = await row.locator('.event-sentence').textContent();
    assert.match(reading, /^업무 설명을 고쳤습니다 \(수정본 \d+\)$/);
    assert.equal(await row.locator('.tech-details').getAttribute('open'), null, 'folded by default');
    await row.locator('.tech-details summary').click();
    assert.match(await row.locator('.tech-details').textContent(), /사건 종류work\.revised/);
    assert.match(await row.locator('time').getAttribute('title'), /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/);

    await page.goto(url + 'settings.html');
    for (const id of MOVED) assert.equal(await page.locator(`#${id}`).count(), 1, `${id} is on the settings page`);
    const panels = page.locator('[data-settings-panel]');
    await page.locator('#records-account h2').waitFor();
    assert.equal(await page.locator('[data-settings-panel]:visible').count(), 1, 'one panel at a time');
    assert.equal(await page.locator('#settings-hub a[aria-current="true"]').textContent(), '계정과 세션');
    const entries = await page.locator('#settings-hub li[data-entry] > a').allTextContents();
    assert.deepEqual(entries, ['계정과 세션', '모델 연결', '실행 한도', '백업·보존', '업데이트·복구', '확장', '브라우저 권한']);
    await page.getByRole('link', { name: '모델 연결' }).click();
    await page.waitForURL(`${url}settings.html#settings-models`);
    await page.locator('#records-connection h2').waitFor();
    assert.equal(await page.locator('#records-credentials').isVisible(), true);
    assert.equal(await page.locator('#records-account').isVisible(), false);
    assert.equal(await page.locator('#settings-hub a[aria-current="true"]').textContent(), '모델 연결');
    // an old deep link to a section opens the panel that holds it
    await page.goto(url + 'settings.html#records-retention');
    await page.reload();
    await page.locator('#records-retention h2').waitFor();
    assert.equal(await page.locator('#settings-hub a[aria-current="true"]').textContent(), '백업·보존');
    assert.equal(await panels.count(), 7);
    // the context bar says only what the page knows: the run the owner picked
    await page.goto(url + 'observe.html');
    const bar = page.getByRole('group', { name: '현재 맥락' });
    assert.equal(await bar.isVisible(), false, 'nothing picked, nothing shown');
    const runId = await page.evaluate(async ({ base, seed }) => {
      const session = await (await fetch(base + 'session')).json();
      const headers = { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token };
      const consent = await (await fetch(base + 'api/v1/run-consents', { method: 'POST', headers, body: JSON.stringify({
        schema_version: 'run-consent-command-v1', command_id: crypto.randomUUID(), graph_ref: seed.graph_ref,
        work_revision_ref: seed.work_revision_ref, environment_ref: seed.environment_ref,
        budget_policy_ref: seed.budget_policy_ref }) })).json();
      const run = await (await fetch(base + 'api/v1/runs', { method: 'POST', headers, body: JSON.stringify({
        command_id: crypto.randomUUID(), ...seed, consent_ref: consent.ref }) })).json();
      return run.run_id;
    }, { base, seed });
    await page.reload();
    await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runId);
    await bar.waitFor();
    assert.equal((await bar.textContent()).trim(), `실행${runId.slice(0, 8)}`);
    assert.doesNotMatch(await bar.textContent(), /운영|설계 검토|격리 실험|과거 기록/, 'no mode is guessed');
    // the run's status names the short id, the full one is one fold away; cancel says what it does
    const panel = page.locator('#run-panel');
    await panel.locator('[role=status]', { hasText: runId.slice(0, 8) }).waitFor();
    assert.doesNotMatch(await panel.locator('[role=status]').textContent(), new RegExp(runId));
    assert.match(await panel.locator('.tech-details').textContent(), new RegExp(runId));
    assert.equal(await panel.getByRole('button', { name: '새 작업 보내기 중단' }).count(), 1);
    // a node's raw handler config is folded; its failure policy reads in words
    await page.locator('#run-graph button[data-node]').nth(5).click();
    const details = page.locator('#run-graph .graph-details');
    await details.getByText('실패하면 뒤 단계 멈춤').waitFor();
    assert.doesNotMatch(await details.textContent(), /handler_id|block_dependants/);
    assert.match(await page.locator('#run-graph .tech-details').textContent(), /handler_id/);
    // an artifact row names its type in words; the declared raw type is folded
    const artifact = page.locator('#run-artifacts .artifact-list li').first();
    await artifact.waitFor();
    assert.doesNotMatch(await artifact.locator('.artifact-label').textContent(), /text\/plain|\(선언\)/);
    assert.match(await page.locator('#run-artifacts').textContent(), /형식은 산출물을 만든 쪽이 밝힌 값입니다/);
    // the work page names a work only once it is saved: its first written line and its revision
    await page.goto(url + 'work.html');
    const workBar = page.getByRole('group', { name: '현재 맥락' });
    await page.locator('#work-description').waitFor();
    assert.equal(await workBar.isVisible(), false, 'an unsaved work names nothing');
    await page.locator('#work-description').fill('화요일 공간 안내문 만들기\n자세한 설명은 둘째 줄에');
    await page.getByRole('button', { name: '이 인스턴스에 저장' }).click();
    await page.getByText('이 인스턴스에 저장됨 · 수정본 1', { exact: false }).first().waitFor();
    await workBar.waitFor();
    assert.equal((await workBar.textContent()).trim(), '업무화요일 공간 안내문 만들기저장본수정본 1');
    // the microphone limit the old banner stated now sits beside the input
    assert.match(await page.locator('#work-form').textContent(), /마이크 입력은 아직 지원하지 않습니다/);
    assert.deepEqual(errors, []);
  });
