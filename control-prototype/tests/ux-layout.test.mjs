import test from 'node:test';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';
import { createServer } from '../server.mjs';

if (!process.env.CONTROL_PLAYWRIGHT_MODULE) throw new Error('CONTROL_PLAYWRIGHT_MODULE required');
const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
let browser, server, url;
test.before(async () => {
  server = createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  url = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
test.after(async () => {
  await browser?.close();
  if (server?.listening) await new Promise(resolve => server.close(resolve));
});

test('desktop graph and selected output share the first work row without shrinking graph labels', async () => {
  for (const width of [1280, 1440]) {
    const page = await browser.newPage({ viewport: { width, height: 900 } });
    try {
      await page.goto(url, { waitUntil: 'networkidle' });
      const graph = await page.locator('.run-graph').boundingBox();
      const selection = await page.locator('#selection-workspace').boundingBox();
      assert.ok(selection.x >= graph.x + graph.width - 1, `${width}: output is beside graph`);
      assert.ok(Math.abs(selection.y - graph.y) < 32, `${width}: output shares graph row`);
      assert.ok(selection.y < 500, `${width}: output entry is in first viewport`);
      assert.equal(await page.locator('.graph').evaluate(el => el.getBoundingClientRect().width), 900);
      const preview = page.locator('.origin-preview .artifact-canvas');
      const visibleImageHeight = await preview.evaluate(el => {
        const canvas = el.getBoundingClientRect();
        const article = el.closest('article').getBoundingClientRect();
        const img = el.querySelector('img').getBoundingClientRect();
        return Math.min(canvas.bottom, article.bottom, img.bottom) - Math.max(canvas.top, article.top, img.top);
      });
      assert.ok(visibleImageHeight >= 300, 'at least 300px of actual PDF content, not just its controls, is exposed');
      assert.ok((await preview.boundingBox()).height <= 360, 'media itself is bounded; controls do not consume its viewport');
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    } finally { await page.close(); }
  }
});

test('conversation has a compact adjacent note pane and no page overflow', async () => {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  try {
    await page.goto(url, { waitUntil: 'networkidle' });
    await page.locator('[data-action="mode"][data-value="conversation"]').click();
    const note = await page.locator('.conversation').boundingBox();
    const work = await page.locator('.mode-content').boundingBox();
    assert.ok(work.x >= note.x + note.width - 1, 'notes do not push the entire work area below');
    assert.equal(await page.locator('.run-graph').evaluate(el => el.open), false);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  } finally { await page.close(); }
});

test('narrow screens confine the wide graph to its own scroller before and after selection', async () => {
  for (const width of [390, 1024]) {
    const page = await browser.newPage({ viewport: { width, height: 768 } });
    try {
      await page.goto(url, { waitUntil: 'networkidle' });
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${width}: initial page has no horizontal overflow`);
      await page.locator('[data-action="node"][data-value="approve"]').click();
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth && scrollX === 0), true, `${width}: result focus does not shift the page sideways`);
      assert.equal(await page.locator('.graph').evaluate(el => el.getBoundingClientRect().width), 900);
    } finally { await page.close(); }
  }
});
