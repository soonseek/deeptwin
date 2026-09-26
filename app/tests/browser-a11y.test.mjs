// UI phase 6 (docs/ui/2026-09-26-product-ux-redesign.md §15; experience.md §12) in real Chromium
// against the real supported server (fixtures/trace_server.py: a scripted test-actor owner, run A
// completed with a failed and a retried attempt, run B waiting at its gate; no provider is called
// and no key is read). Everything here is synthetic evidence of the mechanism.
//
// 1. The in-house audit (helpers/a11y-audit.mjs; axe-core was not available offline) over every
//    shell page — work, the run list, a run's detail, versions, records, every settings panel —
//    and the start screen, in the light and the dark theme: accessible names, labels, images,
//    heading order, landmarks, IDREFs, duplicate ids, rendered text contrast; the design tokens'
//    contrast pair by pair; a visible focus indicator on every tab stop; reduced motion.
// 2. Reflow: at 320px and at 1280px under 200% zoom (a 640 CSS px viewport at 2x) no page scrolls
//    sideways; only the graph, tables and code scroll inside their own box.
// 3. Keyboard journeys, keyboard only (no mouse, no fill): (a) create a work and save; (b) open a
//    run from the list, move through the graph's nodes, switch the attempt, switch the detail tabs
//    with the arrow keys; (c) open 내 버전 in place, type, 차이 살펴보기, close, focus returns;
//    (d) mark 확인 필요 and save; (e) the 390px drawer traps focus and returns it; (f) the settings
//    panels.
// 4. Screen-reader semantics: polite live regions without repeated announcements, the graph's
//    equivalent list, state in words beside every colour.
// Passing this is not a real screen-reader user's test and not the owner's acceptance.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';
import { AUDIT_LAUNCH_ARGS, auditPage, focusAudit, recordAnnouncements, reflowAudit, tokenContrast } from './helpers/a11y-audit.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const READY = /TRACE_SEED=(\{[^\n]*\})\nTRACE_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const SETTINGS_PANELS = ['account', 'models', 'budgets', 'backup', 'update', 'extensions', 'service-clients', 'grants'];
const SETTINGS_LABELS = ['계정과 세션', '모델 연결', '실행 한도', '백업·보존', '업데이트·복구', '확장', '서비스 클라이언트', '브라우저 권한'];

async function openFixture(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  assert.equal(process.env.DEEPTWIN_LIVE_ANTHROPIC_API_KEY, undefined, 'the trace fixture runs with the live key unset');
  const dir = await mkdtemp(join(tmpdir(), 'dt-a11y-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Trace fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/trace_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 90000, label: 'Trace fixture' });
  const [, seedText, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true, args: [...AUDIT_LAUNCH_ARGS] });
  const base = new URL(url).pathname;
  const errors = [];
  // a signed-in page in its own context (viewport, theme, zoom as 2x device pixels)
  async function signedIn({ width = 1280, height = 900, colorScheme = 'light', deviceScaleFactor = 1, reducedMotion = 'no-preference' } = {}) {
    const context = await browser.newContext({ viewport: { width, height }, colorScheme, deviceScaleFactor, reducedMotion });
    const page = await context.newPage();
    page.setDefaultTimeout(20000);
    page.on('pageerror', error => errors.push(error.message));
    await page.goto(url);
    const status = await page.evaluate(async ({ base }) => (await fetch(base + 'session/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase' }) })).status, { base });
    assert.equal(status, 200);
    return { context, page };
  }
  return { browser, url, base, seed: JSON.parse(seedText), errors, signedIn };
}

// each shell page with what it is ready by
function pagesOf(seed) {
  return [
    ['work', 'work.html', '#work-steps .work-step'],
    ['run list', 'observe.html', `#run-table tr[data-run-row="${seed.run_id}"][data-state="read"]`],
    ['run detail', `observe.html#run=${seed.run_id}`, '#run-summary .run-title'],
    ['waiting run', `observe.html#run=${seed.waiting_run_id}`, '#run-summary .run-title'],
    ['versions', 'versions.html', '#versions [role=tab]'],
    ['records', 'records.html', '#records-log ol.event-log li'],
    ...SETTINGS_PANELS.map(id => [`settings ${id}`, `settings.html#settings-${id}`, `#settings-${id}:not([hidden])`]),
  ];
}

async function ready(page, url, path, selector) {
  await page.goto(url + path);
  await page.locator(selector).first().waitFor();
  await page.waitForLoadState('networkidle');
}

function report(found) {
  return found.map(item => `${item.page}: ${item.rule} ${item.node} ${item.detail}`).join('\n');
}

// keyboard only: Tab (or Shift+Tab) until the focused element satisfies `test`
async function tabTo(page, predicate, { arg = null, max = 120, back = false, what = 'the control' } = {}) {
  for (let index = 0; index < max; index += 1) {
    await page.keyboard.press(back ? 'Shift+Tab' : 'Tab');
    if (await page.evaluate(predicate, arg)) return;
  }
  const focused = await page.evaluate(() => `${document.activeElement?.tagName} ${document.activeElement?.computedName ?? ''}`);
  assert.fail(`${what} was not reached by keyboard within ${max} presses (focus on ${focused})`);
}

const focusedName = page => page.evaluate(() => (document.activeElement?.computedName ?? '').trim());
const focusedIs = (page, selector) => page.evaluate(selector => document.activeElement?.matches(selector) ?? false, selector);

test('UI phase 6: audit, reflow, reduced motion and keyboard journeys on every shell page', { timeout: 900000 }, async t => {
  const env = await openFixture(t);
  const { url, seed } = env;

  await t.test('automated audit: every page in both themes, the start screen, the tokens and the focus ring', async () => {
    const all = [];
    for (const colorScheme of ['light', 'dark']) {
      const { context, page } = await env.signedIn({ colorScheme });
      const tokens = await tokenContrast(page);
      assert.equal(tokens.surface, colorScheme === 'dark' ? '#0e171b' : '#f3f6f6');
      const failing = tokens.rows.filter(row => !row.pass);
      assert.deepEqual(failing, [], `${colorScheme} token pairs under WCAG AA`);
      for (const [label, path, selector] of pagesOf(seed)) {
        await ready(page, url, path, selector);
        all.push(...await auditPage(page, { label: `${colorScheme} ${label}` }));
        if (colorScheme === 'light') {
          const focus = await focusAudit(page, { max: 160, label: `${colorScheme} ${label}` });
          assert.ok(focus.stops.length > 0, `${label} has tab stops`);
          assert.ok(focus.ended || focus.wrapped, `${label}: the tab order ends or wraps (${focus.stops.length} stops)`);
          all.push(...focus.problems);
        }
      }
      await context.close();
    }
    // the start screen, signed out
    const context = await env.browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    await page.goto(url);
    await page.locator('#login-form:not([hidden]) input').first().waitFor();
    all.push(...await auditPage(page, { label: 'start' }));
    const focus = await focusAudit(page, { label: 'start' });
    all.push(...focus.problems);
    await context.close();
    assert.equal(all.length, 0, report(all));
  });

  await t.test('reflow: no sideways page scroll at 320px or at 1280px under 200% zoom', async () => {
    const problems = [];
    for (const size of [{ width: 320, height: 720 }, { width: 640, height: 450, deviceScaleFactor: 2 }]) {
      const { context, page } = await env.signedIn(size);
      for (const [label, path, selector] of pagesOf(seed)) {
        await ready(page, url, path, selector);
        const reflow = await reflowAudit(page, { label: `${size.width}px ${label}` });
        assert.equal(reflow.width, size.width);
        problems.push(...reflow.problems.map(problem => `${reflow.page}: ${problem}`));
        // the narrow screen's own audit (a folded menu, stacked panels)
        const found = await auditPage(page, { label: `${size.width}px ${label}` });
        problems.push(...found.map(item => `${item.page}: ${item.rule} ${item.node} ${item.detail}`));
      }
      // the selection's detail tabs wrap instead of hiding a tab behind a sideways scroll
      await ready(page, url, `observe.html#run=${seed.run_id}`, '#run-summary .run-title');
      const tabs = await page.locator('#run-selection [role=tablist] [role=tab]').evaluateAll(nodes => nodes.map(node => {
        const box = node.getBoundingClientRect();
        return box.right <= document.documentElement.clientWidth + 1 && box.width > 0;
      }));
      assert.ok(tabs.length === 5 && tabs.every(Boolean), `${size.width}px: every detail tab is on screen`);
      await context.close();
    }
    assert.deepEqual(problems, []);
  });

  await t.test('reduced motion: transitions collapse when the owner asks for less motion', async () => {
    for (const reducedMotion of ['no-preference', 'reduce']) {
      const { context, page } = await env.signedIn({ reducedMotion });
      await ready(page, url, 'records.html', '#records-log ol.event-log li');
      const durations = await page.evaluate(() => {
        const longest = [];
        for (const node of document.querySelectorAll('*')) {
          for (const pseudo of [null, '::before', '::after']) {
            const style = getComputedStyle(node, pseudo);
            const seconds = [...style.transitionDuration.split(','), ...style.animationDuration.split(',')]
              .map(value => (value.trim().endsWith('ms') ? parseFloat(value) / 1000 : parseFloat(value)) || 0);
            longest.push(Math.max(...seconds));
          }
        }
        return { max: Math.max(...longest), smooth: getComputedStyle(document.documentElement).scrollBehavior };
      });
      if (reducedMotion === 'reduce') {
        assert.ok(durations.max < 0.01, `no motion left: ${durations.max}s`);
        assert.equal(durations.smooth, 'auto');
      } else {
        assert.ok(durations.max > 0.05, 'the page has transitions to reduce');
      }
      await context.close();
    }
  });

  await t.test('journey (a): create a work and save it, keyboard only', async () => {
    const { context, page } = await env.signedIn();
    await ready(page, url, 'work.html', '#work-description');
    const said = await recordAnnouncements(page);
    await tabTo(page, () => document.activeElement?.id === 'work-description', { what: 'the description field' });
    assert.equal(await focusedName(page), '어떤 일을 맡기고 싶으세요?');
    await page.keyboard.type('키보드로 만든 업무: 금요일 회의록 정리');
    await tabTo(page, () => document.activeElement?.computedName === '이 인스턴스에 저장', { what: '이 인스턴스에 저장' });
    await page.keyboard.press('Enter');
    await page.getByText(/이 인스턴스에 저장됨 · 수정본 1/).first().waitFor();
    assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY', 'focus stays on the page after saving');
    const bar = page.getByRole('region', { name: '현재 맥락' });
    await bar.getByText('키보드로 만든 업무: 금요일 회의록 정리').waitFor();
    const announcements = await said();
    assert.ok(announcements.some(item => /저장됨/.test(item.text) && item.politeness === 'polite'), JSON.stringify(announcements));
    assert.deepEqual(announcements.filter(item => item.repeated), [], 'no live region repeats itself');
    assert.equal(announcements.filter(item => item.politeness === 'assertive').length, 0);
    await context.close();
  });

  await t.test('journey (b): open a run from the list, walk the graph, switch the attempt and the detail tabs', async () => {
    const { context, page } = await env.signedIn();
    await ready(page, url, 'observe.html', `#run-table tr[data-run-row="${seed.run_id}"][data-state="read"]`);
    const said = await recordAnnouncements(page);
    await tabTo(page, runId => document.activeElement?.tagName === 'A' && document.activeElement.dataset.runId === runId,
      { arg: seed.run_id, what: 'run A in the run list' });
    // two runs of one work share a title; the link is described by its own run's line
    assert.equal(await page.evaluate(() => document.activeElement.computedName), '화요일 공간 안내');
    assert.match(await page.evaluate(() => document.getElementById(document.activeElement.getAttribute('aria-describedby'))?.textContent),
      new RegExp(`실행 ${seed.run_id.slice(0, 8)}`));
    await page.keyboard.press('Enter');
    await page.waitForURL(new RegExp(`#run=${seed.run_id}$`));
    await page.locator('#run-summary .run-title').waitFor();
    // the context bar knows this run's mode from its trace (a live run: 운영)
    await page.getByRole('region', { name: '현재 맥락' }).locator('.mode-badge[data-mode="operating"]').waitFor();

    // the graph has an equivalent list: one button per drawn node, its state in words
    const drawn = await page.locator('#run-graph svg g[data-node]').evaluateAll(nodes => nodes.map(node => node.dataset.node).sort());
    const listed = await page.locator('#run-graph .graph-nodes button[data-node]').evaluateAll(nodes =>
      nodes.map(node => [node.dataset.node, node.textContent]));
    assert.deepEqual(listed.map(([id]) => id).sort(), drawn);
    assert.ok(listed.every(([, text]) => /완료|실패|승인 대기|대기|진행 중|수행 안 됨/.test(text)), JSON.stringify(listed));
    assert.equal(await page.locator('#run-graph svg').getAttribute('role'), 'img');
    assert.match(await page.locator('#run-graph svg').getAttribute('aria-label'), /^노드 \d+개, 연결 \d+개$/);
    assert.equal(await page.locator('#run-graph svg [aria-pressed]').count(), 0, 'the drawing takes no pressed state');

    // into the node list; the arrow keys move between nodes, Enter selects
    await tabTo(page, () => document.activeElement?.matches('#run-graph .graph-nodes button') ?? false, { what: 'the first graph node' });
    const first = await page.evaluate(() => document.activeElement.dataset.node);
    await page.keyboard.press('Enter');
    await page.locator(`#run-graph .graph-nodes button[data-node="${first}"][aria-pressed="true"]`).waitFor();
    await page.locator(`#run-graph svg g[data-node="${first}"][data-selected="true"]`).waitFor({ state: 'attached' });
    assert.equal(await page.evaluate(() => document.activeElement.dataset.node), first, 'selecting keeps the keyboard on the node');
    const at = () => page.evaluate(() => document.activeElement.dataset.node);
    for (let index = 0; index < 8 && await at() !== 'publish'; index += 1) await page.keyboard.press('ArrowDown');
    assert.equal(await at(), 'publish');
    await page.keyboard.press('End');
    const last = await at();
    await page.keyboard.press('Home');
    assert.equal(await at(), first);
    assert.notEqual(last, first);
    for (let index = 0; index < 8 && await at() !== 'publish'; index += 1) await page.keyboard.press('ArrowRight');
    await page.keyboard.press('Space');
    const selection = page.locator('#run-selection');
    await page.locator('#run-graph .graph-nodes button[data-node="publish"][aria-pressed="true"]').waitFor();
    await selection.locator('.selection-sub', { hasText: 'publish' }).waitFor();

    // the attempt switch: attempt 2 is shown; the arrow key picks attempt 1 and the keyboard stays there
    await tabTo(page, () => document.activeElement?.computedName === '시도 선택', { what: '시도 선택' });
    assert.equal(await page.evaluate(() => document.activeElement.value), '2');
    await page.keyboard.press('ArrowUp');
    await selection.locator('.past-attempt').waitFor();
    assert.equal(await page.evaluate(() => document.activeElement?.computedName), '시도 선택', 'focus stays on the attempt picker');
    assert.equal(await page.evaluate(() => document.activeElement.value), '1');
    assert.match(await selection.locator('.selection-error').textContent(), /시도 1 오류/);
    await page.keyboard.press('ArrowDown');
    await selection.locator('.past-attempt').waitFor({ state: 'detached' });
    assert.equal(await page.evaluate(() => document.activeElement.value), '2');

    // the detail tabs: one tab stop, the arrow keys (and Home/End) select
    await tabTo(page, () => document.activeElement?.getAttribute('role') === 'tab'
      && document.activeElement.closest('[role=tablist]')?.getAttribute('aria-label') === '선택한 단계의 기록', { what: 'the detail tabs' });
    const tabName = () => page.evaluate(() => document.activeElement.textContent);
    const startTab = await tabName();
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-selected')), 'true');
    await page.keyboard.press('ArrowRight');
    assert.notEqual(await tabName(), startTab);
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-selected')), 'true');
    const panelShown = () => page.evaluate(() => {
      const panel = document.getElementById(document.activeElement.getAttribute('aria-controls'));
      return panel !== null && !panel.hidden;
    });
    assert.equal(await panelShown(), true);
    await page.keyboard.press('End');
    assert.equal(await tabName(), '기록');
    assert.equal(await panelShown(), true);
    await page.keyboard.press('Home');
    assert.equal(await tabName(), '입력');
    await page.keyboard.press('ArrowLeft');
    assert.equal(await tabName(), '기록', 'the arrows wrap');
    // Tab leaves the tab list into the shown panel (one stop per tab list)
    await page.keyboard.press('Tab');
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('role')), 'tabpanel');

    // "실행 전체 보기" removes itself: the keyboard lands on the new heading, not the page body
    await tabTo(page, () => document.activeElement?.computedName === '실행 전체 보기', { back: true, what: '실행 전체 보기' });
    await page.keyboard.press('Enter');
    await selection.locator('.selection-title', { hasText: '실행 전체' }).waitFor();
    assert.equal(await focusedIs(page, '#run-selection .selection-title'), true);

    // the process view tabs switch to the timeline by keyboard as well
    await tabTo(page, () => document.activeElement?.getAttribute('role') === 'tab'
      && document.activeElement.closest('[role=tablist]')?.getAttribute('aria-label') === '과정 보기 전환', { back: true, what: 'the process tabs' });
    await page.keyboard.press('ArrowRight');
    assert.equal(await tabName(), '타임라인');
    await page.locator('#run-timeline button.timeline-entry').first().waitFor();

    const announcements = await said();
    assert.deepEqual(announcements.filter(item => item.repeated), [], 'no live region repeats itself');
    assert.equal(announcements.filter(item => item.politeness === 'assertive').length, 0, JSON.stringify(announcements));
    // the page with the timeline shown still passes the audit
    assert.deepEqual(await auditPage(page, { label: 'run detail, timeline' }), []);
    await context.close();
  });

  await t.test('journey (c): 내 버전 in place, type, 차이 살펴보기, close, focus returns to the control that opened it', async () => {
    const { context, page } = await env.signedIn();
    await ready(page, url, `observe.html#run=${seed.run_id}`, '#run-summary .run-title');
    await tabTo(page, () => document.activeElement?.computedName === '내 버전 만들기'
      && document.activeElement.closest('#run-final') !== null, { what: '내 버전 만들기' });
    await page.keyboard.press('Enter');
    const editor = page.locator('#run-final #run-alternative');
    await editor.locator('textarea').waitFor();
    // the keyboard is taken to the editor's heading, which says what is being edited
    await page.waitForFunction(() => document.activeElement?.matches('#run-alternative .alternative-title'));
    assert.match(await focusedName(page), /^내 버전 — report/);
    await tabTo(page, () => document.activeElement?.computedName === '내 버전 텍스트', { what: 'the text field' });
    await page.keyboard.press('Control+End');
    await page.keyboard.type('\n키보드로 더한 문장입니다.');
    await tabTo(page, () => document.activeElement?.computedName === '차이 살펴보기'
      && document.activeElement.closest('#run-alternative') !== null, { what: '차이 살펴보기' });
    await page.keyboard.press('Enter');
    const difference = page.locator('#run-final #run-difference');
    await difference.locator('.difference-observed li').first().waitFor();
    await page.waitForFunction(() => document.activeElement?.matches('#run-difference .difference-title'));
    assert.deepEqual(await auditPage(page, { label: 'editor and difference open' }), []);
    // close the difference view: the keyboard returns to 차이 살펴보기
    await tabTo(page, () => document.activeElement?.computedName === '닫기'
      && document.activeElement.closest('#run-difference') !== null, { what: 'the difference view\'s 닫기' });
    await page.keyboard.press('Enter');
    await difference.waitFor({ state: 'detached' });
    assert.equal(await focusedName(page), '차이 살펴보기');
    assert.equal(await focusedIs(page, '#run-alternative button'), true);
    // close the editor: the keyboard returns to 내 버전 만들기
    await tabTo(page, () => document.activeElement?.computedName === '닫기'
      && document.activeElement.closest('#run-alternative') !== null, { back: true, what: 'the editor\'s 닫기' });
    await page.keyboard.press('Enter');
    await editor.waitFor({ state: 'detached' });
    assert.equal(await focusedName(page), '내 버전 만들기');
    assert.equal(await focusedIs(page, '#run-final button'), true);
    await context.close();
  });

  await t.test('journey (d): mark the whole result 확인 필요 and save it', async () => {
    const { context, page } = await env.signedIn();
    await ready(page, url, `observe.html#run=${seed.run_id}`, '#run-summary .run-title');
    const said = await recordAnnouncements(page);
    const box = page.locator('[data-feedback-for="feedback-run"]');
    await tabTo(page, () => document.activeElement?.computedName === '확인 필요'
      && document.activeElement.closest('[data-feedback-for="feedback-run"]') !== null, { what: '확인 필요' });
    await page.keyboard.press('Space');
    assert.equal(await page.evaluate(() => document.activeElement.getAttribute('aria-pressed')), 'true');
    // the pressed state is in words and a glyph, not only colour
    assert.match(await page.evaluate(() => document.activeElement.textContent), /!확인 필요/);
    await tabTo(page, () => document.activeElement?.computedName === '저장'
      && document.activeElement.closest('[data-feedback-for="feedback-run"]') !== null, { what: '저장' });
    await page.keyboard.press('Enter');
    await box.locator('.feedback-status[data-state="saved"]').waitFor();
    assert.match(await box.locator('.feedback-status').textContent(), /저장됨/);
    assert.notEqual(await page.evaluate(() => document.activeElement?.tagName), 'BODY');
    // the header's summary says it in words
    await page.locator('#run-summary').getByText(/결과 전체: 확인 필요/).waitFor();
    const announcements = await said();
    const saved = announcements.filter(item => /저장됨/.test(item.text));
    assert.ok(saved.length >= 1, JSON.stringify(announcements));
    assert.ok(saved.every(item => item.politeness === 'polite'));
    assert.deepEqual(announcements.filter(item => item.repeated), [], JSON.stringify(announcements));
    await context.close();
  });

  await t.test('journey (e): the 390px drawer traps focus and returns it', async () => {
    const { context, page } = await env.signedIn({ width: 390, height: 844 });
    await ready(page, url, 'records.html', '#records-log ol.event-log li');
    // on a narrow screen the event log comes before the export note, the filters in two columns
    const order = await page.evaluate(() => document.getElementById('records-logs').getBoundingClientRect().top
      < document.getElementById('records-export').getBoundingClientRect().top);
    assert.equal(order, true, '사건 기록 before 내보내기');
    const columns = await page.locator('.records-filter-fields').evaluate(node => getComputedStyle(node).gridTemplateColumns.split(' ').length);
    assert.equal(columns, 2, 'the filters sit in two columns');
    await tabTo(page, () => document.activeElement?.classList.contains('shell-menu-button') ?? false, { what: '메뉴 열기' });
    assert.equal(await focusedName(page), '메뉴 열기');
    await page.keyboard.press('Enter');
    await page.locator('#shell-nav').waitFor();
    assert.equal(await focusedName(page), '기록');
    assert.equal(await page.evaluate(() => document.getElementById('main').inert), true);
    assert.equal(await page.evaluate(() => document.querySelector('.skip-link').inert), true, 'the skip link sleeps too');
    // Tab and Shift+Tab stay inside the drawer, whichever way round
    const inside = () => page.evaluate(() => document.getElementById('shell-nav').contains(document.activeElement));
    const seen = new Set();
    for (let index = 0; index < 14; index += 1) {
      await page.keyboard.press('Tab');
      assert.equal(await inside(), true, `Tab ${index + 1} stays in the drawer`);
      seen.add(await focusedName(page));
    }
    assert.deepEqual([...seen].sort(), ['DeepTwin', '기록', '메뉴 닫기', '버전·실험', '설정', '실행', '업무'].sort());
    for (let index = 0; index < 9; index += 1) {
      await page.keyboard.press('Shift+Tab');
      assert.equal(await inside(), true, `Shift+Tab ${index + 1} stays in the drawer`);
    }
    // the page behind is inert on purpose; what the drawer exposes passes on its own
    assert.deepEqual(await auditPage(page, { label: 'drawer open', modal: true }), []);
    await page.keyboard.press('Escape');
    await page.locator('#shell-nav').waitFor({ state: 'hidden' });
    assert.equal(await focusedName(page), '메뉴 열기', 'focus returns to the menu button');
    // and by the close button, from the keyboard
    await page.keyboard.press('Enter');
    await page.locator('#shell-nav').waitFor();
    await tabTo(page, () => document.activeElement?.computedName === '메뉴 닫기', { what: '메뉴 닫기' });
    await page.keyboard.press('Enter');
    await page.locator('#shell-nav').waitFor({ state: 'hidden' });
    assert.equal(await focusedName(page), '메뉴 열기');
    assert.equal(await page.evaluate(() => document.getElementById('main').inert), false);
    await context.close();
  });

  await t.test('journey (f): every settings panel by keyboard', async () => {
    const { context, page } = await env.signedIn();
    await ready(page, url, 'settings.html', '#records-account h2');
    for (const [index, label] of SETTINGS_LABELS.entries()) {
      await tabTo(page, name => document.activeElement?.closest('#settings-hub') !== null && document.activeElement.computedName === name,
        { arg: label, back: index > 0, what: label });
      await page.keyboard.press('Enter');
      const id = `settings-${SETTINGS_PANELS[index]}`;
      await page.waitForURL(new RegExp(`#${id}$`));
      await page.locator(`#${id}`).waitFor();
      assert.equal(await page.locator('[data-settings-panel]:visible').count(), 1);
      if (index > 0) assert.equal(await page.evaluate(() => document.activeElement?.id), id, `${label}: the panel takes the keyboard`);
      assert.equal(await page.locator('#settings-hub a[aria-current="true"]').textContent(), label);
      if (index > 0) {
        // Tab walks into the shown panel, never into a hidden one
        await page.keyboard.press('Tab');
        assert.equal(await page.evaluate(() => document.activeElement?.closest('[data-settings-panel]')?.hidden !== true), true);
      }
    }
    // the service clients panel: this loopback instance refuses creation, said in words with
    // the server's answer folded under 기술 정보 (keyboard only)
    await tabTo(page, () => document.activeElement?.closest('#settings-hub') !== null
      && document.activeElement.computedName === '서비스 클라이언트', { back: true, what: '서비스 클라이언트' });
    await page.keyboard.press('Enter');
    await page.waitForURL(/#settings-service-clients$/);
    await tabTo(page, () => document.activeElement?.id === 'service-client-name', { what: 'the client name' });
    await page.keyboard.type('키보드 클라이언트');
    await tabTo(page, () => document.activeElement?.id === 'service-client-scope-events-read', { what: 'events.read' });
    await page.keyboard.press('Space');
    await tabTo(page, () => document.activeElement?.computedName === '클라이언트 만들기', { what: '클라이언트 만들기' });
    await page.keyboard.press('Enter');
    const refusal = page.locator('#service-clients .service-clients-refusal[role=alert]');
    await refusal.waitFor();
    assert.match(await refusal.textContent(), /이 배포에서는 서비스 클라이언트를 만들 수 없습니다/);
    assert.match(await refusal.locator('.tech-details').textContent(), /422/);
    assert.match(await refusal.locator('.tech-details').textContent(), /invalid_state/);
    assert.deepEqual(await auditPage(page, { label: 'service clients refused' }), []);
    await context.close();
  });

  assert.deepEqual(env.errors, []);
});
