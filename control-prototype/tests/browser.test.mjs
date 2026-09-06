import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { createServer } from '../server.mjs';
import { CASE, RUNS } from '../fixtures.mjs';
import { KEY } from '../state.mjs';

const modulePath = process.env.CONTROL_PLAYWRIGHT_MODULE;
if (!modulePath) throw new Error('CONTROL_PLAYWRIGHT_MODULE is required; browser coverage cannot silently skip.');
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

async function openPage(t, { init, viewport = { width: 1280, height: 900 }, colorScheme } = {}) {
  const context = await browser.newContext({ viewport, colorScheme });
  if (init) await context.addInitScript(init);
  const page = await context.newPage();
  const errors = [];
  const external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => {
    const url = request.url();
    if (!url.startsWith(baseURL) && !url.startsWith('blob:') && !url.startsWith('data:')) external.push(url);
  });
  t.after(async () => {
    assert.deepEqual(errors, [], `page errors: ${errors.join('\n')}`);
    assert.deepEqual(external, [], `unexpected external requests: ${external.join('\n')}`);
    await context.close();
  });
  const response = await page.goto(baseURL, { waitUntil: 'networkidle' });
  assert.equal(response.status(), 200);
  await page.locator('#page-title').waitFor();
  return page;
}

const action = (page, type, value) => page.locator(`[data-action="${type}"][data-value="${value}"]`).first();

test('entry shell starts in run control with the required external module document', async t => {
  const page = await openPage(t);
  assert.equal(await page.title(), 'DeepTwin · 관제 작업대 시제품');
  assert.equal(await page.locator('html').getAttribute('lang'), 'ko');
  assert.equal(await page.locator('#page-title').textContent(), '실행 관제');
  assert.equal(await page.locator('script[type="module"][src="app.mjs"]').count(), 1);
  assert.equal(await page.locator('#storage-status').getAttribute('role'), 'status');
  assert.notEqual(await page.evaluate(() => document.activeElement?.id), 'page-title');
});

test('drafts preserve leading LF, Korean, and literal markup across modes and reload', async t => {
  const page = await openPage(t);
  const suffix = '한국어 초안 </textarea><script>globalThis.__injected=true</script>';
  for (const prefix of ['', '\n', '\n\n\n']) {
    const value = prefix + suffix;
    await page.locator('[data-field="draft"]').fill(value);
    for (const mode of ['workspace', 'conversation', 'graph']) {
      await action(page, 'mode', mode).click();
      assert.equal(await page.locator('[data-field="draft"]').inputValue(), value);
    }
    await page.reload({ waitUntil: 'networkidle' });
    assert.equal(await page.locator('[data-field="draft"]').inputValue(), value);
    assert.equal(await page.evaluate(() => globalThis.__injected), undefined);
  }
});

test('logs dialog changes only preview choices and restores trigger and source context', async t => {
  const page = await openPage(t);
  const before = await page.locator('.ribbon').textContent();
  const trigger = action(page, 'overlay', 'logs');
  await trigger.focus();
  await trigger.click();
  await page.locator('#detail-dialog[open]').waitFor();
  await page.locator('[data-record="log-start"]').check();
  assert.match(await page.locator('#detail-body').textContent(), /선택한 기록 1개/);
  await page.locator('#redact').uncheck();
  assert.match(await page.locator('#detail-body').textContent(), /synthetic-fixture/);
  await page.locator('#detail-body [data-action="close"]').click();
  assert.equal(await page.locator('#detail-dialog').getAttribute('open'), null);
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.action), 'overlay');
  assert.equal(await page.evaluate(() => document.activeElement?.dataset.value), 'logs');
  assert.equal(await page.locator('.ribbon').textContent(), before);
});

test('fresh growth stays unanalysed until the fixed example is explicitly selected', async t => {
  const page = await openPage(t);
  await page.locator('[data-field="draft"]').fill('\n나의 현재 버전');
  const before = await page.locator('.ribbon').textContent();
  await action(page, 'currentGrowth', '').click();
  assert.match(await page.locator('main').textContent(), /분석 결과 없음/);
  assert.equal((await page.locator('main').textContent()).includes(CASE.id), false);
  assert.match(await page.locator('main').textContent(), /나의 현재 버전/);
  await action(page, 'sample', 'true').click();
  assert.match(await page.locator('main').textContent(), new RegExp(CASE.id));
  assert.match(await page.locator('main').textContent(), /사전 구성된 합성 개선 사례/);
  await action(page, 'sample', 'false').click();
  assert.match(await page.locator('.ribbon').textContent(), new RegExp(before.split(' · ')[1]));
});

test('the actual PDF route returns PDF bytes and failed attempts never get an editor fallback', async t => {
  const page = await openPage(t);
  const href = await page.locator('.alternative-editor a[download]').getAttribute('href');
  const response = await page.request.get(new URL(href, baseURL).href);
  const signature = (await response.body()).subarray(0, 5).toString();
  assert.equal(signature, '%PDF-');
  const preview = page.locator('.artifact-image.pdf').first();
  assert.ok(await preview.evaluate(node => node.getBoundingClientRect().height <= 850));
  assert.equal(await preview.evaluate(node => getComputedStyle(node).objectFit), 'contain');

  await page.locator('details.run-picker > summary').click();
  await action(page, 'run', 'run-j1-b1').click();
  await action(page, 'mode', 'graph').click();
  assert.equal(await page.locator('details.run-graph').getAttribute('open'), '');
  await action(page, 'node', 'draft').click();
  await action(page, 'attempt', 'run-j1-b1-draft-1-failed').click();
  assert.match(await page.locator('.attempt-inspector').textContent(), /실패/);
  assert.match(await page.locator('.run-workbench').textContent(), /출력 없음 · 다른 시도의 최신 파일로 채우지 않음/);
  assert.equal(await page.locator('[data-field="draft"]').count(), 0);
});

test('text Range selection becomes an exact scope and stale selections are cleared', async t => {
  const page = await openPage(t);
  await action(page, 'artifact', 'review-j1-origin-v1').click();
  await page.locator('#original-body').evaluate(node => {
    const range = document.createRange();
    range.setStart(node.firstChild, 2);
    range.setEnd(node.firstChild, 20);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  });
  await action(page, 'textScope', '').click();
  assert.match(await page.locator('.scope-summary').textContent(), /문자 2–20/);
  await page.locator('[data-field="draft"]').fill('선택 범위 버전');
  await action(page, 'scope', 'whole').click();
  assert.match(await page.locator('#draft-status').textContent(), /아직/);
  assert.equal(await page.evaluate(() => getSelection().rangeCount), 0);
});

test('sample modal navigation explores frozen origin history without retargeting fresh state', async t => {
  const page = await openPage(t);
  const before = await page.locator('.ribbon').textContent();
  await action(page, 'area', 'growth').click();
  await action(page, 'sample', 'true').click();
  await action(page, 'sampleNode', 'draft').click();
  await page.locator('#detail-dialog[open]').waitFor();
  await page.locator('#detail-body [data-action="sampleAttempt"]').first().evaluate(button => {
    button.dataset.value = 'run-j1-origin-extract-1';
    button.click();
  });
  assert.equal(await page.locator('#detail-body [data-inspected-attempt="run-j1-origin-extract-1"]').count(), 0);
  await action(page, 'sampleAttempt', 'run-j1-origin-draft-1-complete').click();
  assert.match(await page.locator('#detail-body').textContent(), /run-j1-origin-draft-1-complete/);
  await action(page, 'sampleConsumer', 'run-j1-origin-review-1').click();
  assert.match(await page.locator('#detail-body').textContent(), /run-j1-origin-review-1/);
  await page.locator('#detail-close').click();
  await action(page, 'sample', 'false').click();
  assert.match(await page.locator('.ribbon').textContent(), new RegExp(before.split(' · ')[1]));
});

test('graph scroll and expanded state survive repaint while the selected node stays visible', async t => {
  const page = await openPage(t, { viewport: { width: 720, height: 820 } });
  const details = page.locator('details.run-graph');
  await details.locator(':scope > summary').click();
  assert.equal(await details.getAttribute('open'), null);
  await action(page, 'scope', 'whole').click();
  assert.equal(await details.getAttribute('open'), null);
  await details.locator(':scope > summary').click();
  const scroller = details.locator('.graph-scroll');
  await scroller.evaluate(node => { node.scrollLeft = node.scrollWidth; });
  await action(page, 'node', 'approve').click();
  assert.equal(await details.getAttribute('open'), '');
  const visible = await page.locator('.run-graph .node.selected').evaluate(node => {
    const box = node.getBoundingClientRect();
    const frame = node.closest('.graph-scroll').getBoundingClientRect();
    return box.left >= frame.left && box.right <= frame.right;
  });
  assert.equal(visible, true);
  assert.ok(await scroller.evaluate(node => node.scrollLeft > 0));
  await action(page, 'mode', 'conversation').click();
  assert.equal(await details.getAttribute('open'), '');
});

test('local files stay memory-only, reject invalid replacements, and disappear on reload', async t => {
  const page = await openPage(t);
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAF/gL+3MxZ5wAAAABJRU5ErkJggg==', 'base64');
  const input = page.locator('#alternative-file');
  await input.setInputFiles({ name: '증거.png', mimeType: 'image/png', buffer: png });
  assert.match(await page.locator('#file-status').textContent(), /증거.png/);
  assert.equal(await page.locator('#file-status img').count(), 1);
  assert.equal((await page.evaluate(key => sessionStorage.getItem(key), KEY)).includes('증거.png'), false);
  await action(page, 'currentGrowth', '').click();
  assert.match(await page.locator('.fresh-growth blockquote').textContent(), /텍스트 자기 버전 없음/);
  assert.match(await page.locator('.fresh-growth .local-file-context').textContent(), /로컬 첨부 파일 있음 · 증거.png/);
  assert.match(await page.locator('.fresh-growth .local-file-context').textContent(), /메모리에만 유지 · 분석되지 않음/);
  await action(page, 'area', 'run').click();
  await page.locator('[data-field="draft"]').fill('텍스트와 파일을 함께 둔 버전');
  await action(page, 'currentGrowth', '').click();
  assert.match(await page.locator('.fresh-growth blockquote').textContent(), /텍스트와 파일을 함께 둔 버전/);
  assert.match(await page.locator('.fresh-growth .local-file-context').textContent(), /증거.png/);
  await page.evaluate(() => {
    dispatchEvent(new PageTransitionEvent('pagehide', { persisted: true }));
    dispatchEvent(new PageTransitionEvent('pageshow', { persisted: true }));
  });
  assert.equal(await page.locator('.fresh-growth .local-file-context').count(), 0);
  assert.match(await page.locator('.fresh-growth blockquote').textContent(), /텍스트와 파일을 함께 둔 버전/);
  await action(page, 'area', 'run').click();
  await page.locator('[data-field="draft"]').fill('');
  await input.setInputFiles({ name: '증거.png', mimeType: 'image/png', buffer: png });
  await input.setInputFiles({ name: 'too-big.png', mimeType: 'image/png', buffer: Buffer.alloc(5 * 1024 * 1024 + 1) });
  assert.match(await page.locator('#file-status').textContent(), /5MiB/);
  assert.match(await page.locator('#file-status').textContent(), /증거.png/);
  await action(page, 'clearFile', '').click();
  assert.match(await page.locator('#file-status').textContent(), /첨부 파일 지움/);
  assert.match(await page.locator('#draft-status').textContent(), /아직/);
  await input.setInputFiles({ name: '증거.png', mimeType: 'image/png', buffer: png });
  await page.reload({ waitUntil: 'networkidle' });
  assert.match(await page.locator('#file-status').textContent(), /첨부 파일은 복원되지 않음/);
});

test('blocked storage requires confirmation and reset removes only the state key', async t => {
  const page = await openPage(t, { init: () => {
    sessionStorage.setItem('deeptwin:control-ui:v1', '{broken');
    sessionStorage.setItem('unrelated', 'keep');
  } });
  assert.match(await page.locator('#storage-status').textContent(), /이전 값은 덮어쓰지 않음/);
  await page.locator('[data-field="draft"]').fill('메모리에만 남은 값');
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), KEY), '{broken');
  page.once('dialog', dialog => dialog.dismiss());
  await action(page, 'save', '').click();
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), KEY), '{broken');
  page.once('dialog', dialog => dialog.accept());
  await action(page, 'save', '').click();
  const replaced = await page.evaluate(key => sessionStorage.getItem(key), KEY);
  assert.doesNotThrow(() => JSON.parse(replaced));
  assert.notEqual(replaced, '{broken');
  page.once('dialog', dialog => dialog.accept());
  await action(page, 'reset', '').click();
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), KEY), null);
  assert.equal(await page.evaluate(() => sessionStorage.getItem('unrelated')), 'keep');
});

test('narrow artifact tables stay locally scrollable and paper text remains readable in both themes', async t => {
  const contrast = locator => locator.evaluate(node => {
    const parse = value => value.match(/[\d.]+/g).slice(0, 3).map(Number);
    const luminance = value => {
      const channels = parse(value).map(channel => {
        const normalized = channel / 255;
        return normalized <= .04045 ? normalized / 12.92 : ((normalized + .055) / 1.055) ** 2.4;
      });
      return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
    };
    const style = getComputedStyle(node);
    const foreground = luminance(style.color);
    const surface = style.backgroundColor === 'rgba(0, 0, 0, 0)' ? node.closest('article') : node;
    const background = luminance(getComputedStyle(surface).backgroundColor);
    return (Math.max(foreground, background) + .05) / (Math.min(foreground, background) + .05);
  });

  for (const colorScheme of ['light', 'dark']) {
    const page = await openPage(t, {
      viewport: { width: 390, height: 844 },
      colorScheme,
    });
    await action(page, 'area', 'growth').click();
    const blockquoteContrast = await contrast(page.locator('.fresh-growth blockquote'));
    await action(page, 'sample', 'true').click();
    await action(page, 'mode', 'workspace').click();

    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    const table = page.locator('article table').first();
    assert.equal(await table.evaluate(node => getComputedStyle(node).overflowX), 'auto');
    const metadataContrast = await contrast(page.locator('article small').first());
    const legendContrast = await contrast(page.locator('.graph-legend').first());
    assert.ok(blockquoteContrast >= 4.5, `${colorScheme} paper blockquote contrast ${blockquoteContrast} is below 4.5:1`);
    assert.ok(metadataContrast >= 4.5, `${colorScheme} artifact metadata contrast ${metadataContrast} is below 4.5:1`);
    assert.ok(legendContrast >= 4.5, `${colorScheme} graph legend contrast ${legendContrast} is below 4.5:1`);
  }
});
