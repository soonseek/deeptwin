import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { createServer } from '../server.mjs';
import { DESIGNS, ROUNDS } from '../fixtures.mjs';
import { KEY } from '../state.mjs';

const modulePath = process.env.CONTROL_PLAYWRIGHT_MODULE;
if (!modulePath) throw new Error('CONTROL_PLAYWRIGHT_MODULE is required; UX browser coverage cannot silently skip.');
const { chromium } = await import(pathToFileURL(modulePath).href);

let server;
let browser;
let baseURL;

test.before(async () => {
  server = createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  baseURL = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});

test.after(async () => {
  await browser?.close();
  if (server?.listening) await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
});

async function openPage(t, viewport) {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  page.setDefaultTimeout(3000);
  const errors = [];
  const external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const url = request.url();
    if (!url.startsWith(baseURL) && !url.startsWith('blob:') && !url.startsWith('data:')) external.push(url);
  });
  t.after(async () => {
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    await context.close();
  });
  await page.goto(baseURL, { waitUntil: 'networkidle' });
  await page.locator('#page-title').waitFor();
  return page;
}

const action = (page, type, value = '') => page.locator(`[data-action="${type}"][data-value="${value}"]`).first();

async function stored(page) {
  return page.evaluate(key => sessionStorage.getItem(key), KEY);
}

test('explicit narrow selections reveal results while desktop graph choices retain keyboard focus', async t => {
  const narrow = await openPage(t, { width: 900, height: 760 });
  assert.equal(await narrow.evaluate(() => scrollY), 0, 'initial load must not jump to a result');
  const result = narrow.locator('#selection-workspace');
  assert.equal(await result.getAttribute('tabindex'), '-1');

  await action(narrow, 'node', 'draft').click();
  assert.equal(await narrow.evaluate(() => document.activeElement?.id), 'selection-workspace');
  assert.equal(await result.evaluate(node => {
    const box = node.getBoundingClientRect();
    return box.top >= 0 && box.top < innerHeight;
  }), true);

  const beforeNavigation = await stored(narrow);
  await action(narrow, 'graphBack').click();
  assert.equal(await narrow.locator('details.run-graph').evaluate(node => node.open), true);
  assert.equal(await narrow.evaluate(() => document.activeElement?.id), 'run-graph-target');
  assert.equal(await stored(narrow), beforeNavigation);
  await action(narrow, 'inspect').click();
  assert.equal(await narrow.evaluate(() => document.activeElement?.id), 'selection-workspace');
  assert.equal(await stored(narrow), beforeNavigation);
  await action(narrow, 'compose').click();
  assert.equal(await narrow.locator('#draft-input').isVisible(), true);
  assert.equal(await narrow.evaluate(() => document.activeElement?.id), 'draft-input');
  assert.equal(await stored(narrow), beforeNavigation);

  const desktop = await openPage(t, { width: 1280, height: 850 });
  const desktopNode = action(desktop, 'node', 'approve');
  await desktopNode.focus();
  await desktop.keyboard.press('Enter');
  assert.deepEqual(await desktop.evaluate(() => ({
    action: document.activeElement?.dataset.action,
    value: document.activeElement?.dataset.value,
  })), { action: 'node', value: 'approve' });
});

test('the initial selected node is visible without moving page scroll or focus', async t => {
  for (const width of [1280, 1440]) {
    const page = await openPage(t, { width, height: 850 });
    const visible = await page.locator('.run-graph .node.selected').evaluate(node => {
      const box = node.getBoundingClientRect();
      const frame = node.closest('.graph-scroll').getBoundingClientRect();
      return box.left >= frame.left && box.right <= frame.right;
    });
    assert.equal(visible, true, `${width}px initial selected node is contained by its graph frame`);
    assert.equal(await page.evaluate(() => scrollY), 0);
    assert.notEqual(await page.evaluate(() => document.activeElement?.id), 'selection-workspace');
  }
});

test('run disclosures keep same-mode choices without leaking defaults across modes', async t => {
  const page = await openPage(t, { width: 640, height: 850 });
  await page.evaluate(() => {
    const actualRects = Element.prototype.getClientRects;
    Element.prototype.getClientRects = function () {
      if (this.matches?.('.graph-scroll') && this.closest('details:not([open])')) return [];
      return actualRects.call(this);
    };
  });
  const graph = page.locator('details.run-graph');
  const context = page.locator('details.run-context');
  assert.equal(await graph.evaluate(node => node.open), true);
  assert.equal(await context.evaluate(node => node.open), false);

  await graph.locator(':scope > summary').click();
  await action(page, 'scope', 'whole').click();
  assert.equal(await graph.evaluate(node => node.open), false, 'same graph-mode repaint keeps manual closure');

  await action(page, 'mode', 'workspace').click();
  assert.equal(await graph.evaluate(node => node.open), false, 'workspace uses its authored default');
  assert.equal(await context.evaluate(node => node.open), false, 'run context stays compact by default');
  await graph.locator(':scope > summary').click();
  await context.locator(':scope > summary').click();
  const scroller = graph.locator('.graph-scroll');
  await scroller.evaluate(node => { node.scrollLeft = node.scrollWidth; });
  const workspacePosition = await scroller.evaluate(node => node.scrollLeft);
  assert.ok(workspacePosition > 0);

  await action(page, 'area', 'design').click();
  await action(page, 'area', 'run').click();
  assert.equal(await graph.evaluate(node => node.open), true);
  assert.ok(Math.abs(await scroller.evaluate(node => node.scrollLeft) - workspacePosition) <= 1,
    'scroll is restored after the remembered closed-by-default graph is reopened');

  await action(page, 'mode', 'conversation').click();
  assert.equal(await graph.evaluate(node => node.open), false, 'a new mode is not overwritten by the prior mode');
  assert.equal(await context.evaluate(node => node.open), false, 'new mode keeps its authored context default');

  await action(page, 'mode', 'workspace').click();
  assert.equal(await graph.evaluate(node => node.open), true, 'workspace graph disclosure is remembered');
  assert.equal(await context.evaluate(node => node.open), true, 'workspace context disclosure is remembered');
  assert.ok(Math.abs(await scroller.evaluate(node => node.scrollLeft) - workspacePosition) <= 1,
    'scroll is restored after the remembered disclosure is reopened');
  await action(page, 'mode', 'graph').click();
  assert.equal(await graph.evaluate(node => node.open), false, 'graph-mode closure is remembered separately');
});

test('fresh file-only content uses the explicit user-version surface and remains memory-only', async t => {
  const page = await openPage(t, { width: 900, height: 760 });
  await page.locator('#alternative-file').setInputFiles({
    name: '로컬-대안.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('Synthetic local alternative.'),
  });
  assert.equal((await stored(page)).includes('로컬-대안.md'), false);
  await action(page, 'currentGrowth').click();

  const version = page.locator('.fresh-growth .user-version-content');
  assert.equal(await version.count(), 1);
  assert.match(await version.textContent(), /텍스트 자기 버전 없음/);
  assert.match(await page.locator('.fresh-growth .local-file-context').textContent(), /로컬-대안.md/);

  await page.evaluate(() => {
    dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
    dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
  });
  assert.equal(await page.locator('.fresh-growth .local-file-context').count(), 0);
  assert.match(await version.textContent(), /현재 맥락에 작성된 자기 버전 없음/);
});

test('hidden design graphs cannot erase another candidate graph scroll position', async t => {
  const page = await openPage(t, { width: 640, height: 760 });
  await action(page, 'area', 'design').click();
  await action(page, 'mode', 'graph').click();
  const first = page.locator(`.candidate[data-design="${DESIGNS[0].id}"] .graph-scroll`);
  await first.evaluate(node => { node.scrollLeft = node.scrollWidth; });
  const position = await first.evaluate(node => node.scrollLeft);
  assert.ok(position > 0);

  await action(page, 'design', DESIGNS[1].id).click();
  assert.equal(await first.isVisible(), false);
  await action(page, 'design', DESIGNS[0].id).click();
  assert.ok(Math.abs(await first.evaluate(node => node.scrollLeft) - position) <= 1);
});

test('repeated disclosure labels remain scoped to their individual hypothesis', async t => {
  const page = await openPage(t, { width: 1000, height: 800 });
  await action(page, 'area', 'growth').click();
  await action(page, 'sample', 'true').click();
  const hypotheses = page.locator('[data-hypothesis]');
  const first = hypotheses.nth(0).locator('details.hypothesis-evidence');
  const second = hypotheses.nth(1).locator('details.hypothesis-evidence');
  await first.locator(':scope > summary').click();
  assert.equal(await first.evaluate(node => node.open), true);
  assert.equal(await second.evaluate(node => node.open), false);

  await action(page, 'round', ROUNDS[1].id).click();
  assert.equal(await first.evaluate(node => node.open), true);
  assert.equal(await second.evaluate(node => node.open), false);
});
