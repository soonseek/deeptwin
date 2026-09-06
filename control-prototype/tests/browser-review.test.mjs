import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdir, readFile } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { createServer } from '../server.mjs';
import { ARTIFACTS, CASE, DESIGNS, REVISED_DESIGN, ROUNDS, RUNS } from '../fixtures.mjs';
import { KEY, createState } from '../state.mjs';

const modulePath = process.env.CONTROL_PLAYWRIGHT_MODULE;
if (!modulePath) throw new Error('CONTROL_PLAYWRIGHT_MODULE is required; browser review cannot silently skip.');
const { chromium } = await import(pathToFileURL(modulePath).href);
const output = fileURLToPath(new URL('../review-output/', import.meta.url));
const origin = Object.values(RUNS).find(run => run.attempts.some(attempt => attempt.outputs.includes(CASE.original)));
const originalAttempt = origin.attempts.find(attempt => attempt.outputs.includes(CASE.original));
const action = (scope, name, value = '') => scope.locator(`[data-action="${name}"][data-value="${value}"]`).first();
let server;
let browser;
let baseURL;

test.before(async () => {
  await mkdir(output, { recursive: true });
  server = createServer();
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  baseURL = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});

test.after(async () => {
  try { await browser?.close(); }
  finally {
    if (server?.listening) await new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
  }
});

async function openPage(t, { init, initPayload = KEY, viewport = { width: 1440, height: 1000 }, colorScheme = 'dark' } = {}) {
  const context = await browser.newContext({ viewport, colorScheme, acceptDownloads: true });
  if (init) await context.addInitScript(init, initPayload);
  const errors = [];
  const external = [];
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  context.on('request', request => {
    const url = request.url();
    if (/^https?:/.test(url) && new URL(url).origin !== baseURL) external.push(url);
  });
  t.after(async () => {
    try {
      assert.deepEqual(errors, [], 'uncaught browser errors');
      assert.deepEqual(external, [], 'unexpected external HTTP requests');
    } finally { await context.close(); }
  });
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  const response = await page.goto(baseURL, { waitUntil: 'networkidle' });
  assert.equal(response.status(), 200, 'Task 6 browser document must exist and load');
  await page.locator('#page-title').waitFor();
  return page;
}

async function persistedSource(page) {
  return page.evaluate(key => {
    const state = JSON.parse(sessionStorage.getItem(key));
    return { run: state.run, ...state.targets[state.run] };
  }, KEY);
}

async function ensureOpen(details) {
  if (!(await details.evaluate(node => node.open))) await details.locator(':scope > summary').click();
}

async function chooseAttempt(page, run, attempt) {
  await action(page, 'area', 'run').click();
  await ensureOpen(page.locator('details.run-picker'));
  await action(page, 'run', run.id).click();
  await action(page, 'mode', 'graph').click();
  await ensureOpen(page.locator('details.run-graph'));
  await action(page, 'node', attempt.node).click();
  await action(page, 'attempt', attempt.id).click();
}

async function choosePairAttempt(page, side, attempt) {
  let pair = page.locator(`[data-pair="${side}"]`);
  await action(pair, 'pairNode', `${side}:${attempt.node}`).click();
  pair = page.locator(`[data-pair="${side}"]`);
  await action(pair.locator('.attempt-history'), 'pairAttempt', `${side}:${attempt.id}`).click();
  assert.equal(await pair.locator('[data-inspected-attempt]').getAttribute('data-inspected-attempt'), attempt.id);
  return pair;
}

async function verifyFiles(scope, ids) {
  for (const id of ids) {
    const file = scope.locator(`[data-artifact="${id}"]`).first();
    assert.equal(await file.count(), 1, id);
    assert.equal(await file.locator('a[download]').getAttribute('href'), ARTIFACTS[id].path, id);
  }
}

async function decodeImages(page) {
  for (const image of await page.locator('img').all()) {
    const decoded = await image.evaluate(async node => {
      await node.decode();
      return node.complete && node.naturalWidth > 0 && node.naturalHeight > 0;
    });
    assert.equal(decoded, true, await image.getAttribute('src'));
  }
}

async function capture(page, name, locator) {
  await decodeImages(page);
  if (locator) await locator.screenshot({ path: `${output}${name}.png` });
  else await page.screenshot({ path: `${output}${name}.png`, fullPage: false });
}

test('native source Range, exact partial drafts and scoped notes survive navigation and reload', async t => {
  const page = await openPage(t);
  const inputAttempt = origin.attempts.find(attempt => attempt.inputs.includes('source-policy'));
  await chooseAttempt(page, origin, inputAttempt);
  await action(page, 'artifact', 'source-policy').click();
  const selectedText = ARTIFACTS['source-policy'].body.slice(3, 28);
  await page.locator('#original-body').evaluate(node => {
    const range = document.createRange();
    range.setStart(node.firstChild, 3);
    range.setEnd(node.firstChild, 28);
    const selection = getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
  });
  assert.equal(await page.evaluate(() => getSelection().toString()), selectedText);
  await action(page, 'textScope').click();
  assert.equal(await page.locator('[data-selected-region]').textContent(), selectedText);
  const source = await persistedSource(page);
  assert.deepEqual(source.scope, { kind: 'text', start: 3, end: 28 });
  const draft = '\n\n선택 문구에 남긴 한국어 시험 대안';
  await page.locator('[data-field="draft"]').fill(draft);
  await action(page, 'mode', 'conversation').click();
  await page.locator('[data-field="note"]').fill('이 원본과 범위에 대한 메모');
  for (const mode of ['workspace', 'graph', 'conversation']) {
    await action(page, 'mode', mode).click();
    assert.deepEqual(await persistedSource(page), source);
    assert.equal(await page.locator('[data-field="draft"]').inputValue(), draft);
  }
  assert.equal(await page.locator('[data-field="note"]').inputValue(), '이 원본과 범위에 대한 메모');
  await action(page, 'currentGrowth').click();
  await page.locator('[data-field="note"]').fill('현재 입력의 개선 메모');
  await action(page, 'sample', 'true').click();
  await action(page, 'round', ROUNDS[1].id).click();
  await action(page, 'sample', 'false').click();
  assert.equal(await page.locator('[data-field="note"]').inputValue(), '현재 입력의 개선 메모');
  assert.equal(await page.locator('.fresh-growth [data-hypothesis]').count(), 0);
  await action(page, 'area', 'run').click();
  await page.reload({ waitUntil: 'networkidle' });
  assert.deepEqual(await persistedSource(page), source);
  assert.equal(await page.locator('[data-field="draft"]').inputValue(), draft);
  assert.equal(await page.locator('[data-selected-region]').textContent(), selectedText);
});

test('typed original links download real complete files without executing a page fetch', async t => {
  const page = await openPage(t);
  for (const type of ['pdf', 'csv', 'svg', 'text']) {
    const attempt = origin.attempts.find(item => [...item.inputs, ...item.outputs].some(id => ARTIFACTS[id].type === type));
    const id = [...attempt.inputs, ...attempt.outputs].find(value => ARTIFACTS[value].type === type);
    await chooseAttempt(page, origin, attempt);
    await action(page, 'artifact', id).click();
    const original = page.locator(`.alternative-editor [data-artifact="${id}"]`);
    if (type === 'text') assert.equal(await original.locator('pre').textContent(), ARTIFACTS[id].body);
    if (type === 'csv') assert.equal(await original.locator('tr').count(), ARTIFACTS[id].body.trimEnd().split('\n').length);
    if (type === 'pdf') assert.match(await original.textContent(), /SVG 파생 미리보기/);
    if (type === 'pdf' || type === 'svg') assert.equal(await original.locator('img').count(), 1);
    const [download] = await Promise.all([page.waitForEvent('download'), original.locator('a[download]').click()]);
    assert.equal(await download.failure(), null);
    const stream = await download.createReadStream();
    const chunks = [];
    for await (const chunk of stream) chunks.push(chunk);
    const bytes = Buffer.concat(chunks);
    assert.deepEqual(bytes, await readFile(new URL(`../${ARTIFACTS[id].path}`, import.meta.url)), id);
    if (type === 'pdf') assert.equal(bytes.subarray(0, 5).toString(), '%PDF-');
    await decodeImages(page);
    const before = await persistedSource(page);
    const trigger = action(page, 'overlay', 'artifact');
    await trigger.click();
    await verifyFiles(page.locator('#detail-body'), [id]);
    await page.keyboard.press('Escape');
    assert.deepEqual(await persistedSource(page), before);
    assert.equal(await trigger.evaluate(node => node === document.activeElement), true);
  }
});

test('file alternatives remain attached only to their exact scope and disappear on reload', async t => {
  const page = await openPage(t);
  await action(page, 'scope', CASE.region).click();
  await page.locator('[data-field="draft"]').fill('첨부와 함께 보관되는 부분 초안');
  const input = page.locator('#alternative-file');
  const file = { name: 'synthetic-alternative.md', mimeType: 'text/markdown', buffer: Buffer.from('Synthetic file alternative only.') };
  await input.setInputFiles(file);
  assert.match(await page.locator('#file-status').textContent(), /synthetic-alternative.md/);
  assert.equal((await page.evaluate(key => sessionStorage.getItem(key), KEY)).includes(file.name), false);
  await action(page, 'scope', 'whole').click();
  assert.doesNotMatch(await page.locator('#file-status').textContent(), /synthetic-alternative.md/);
  await action(page, 'scope', CASE.region).click();
  assert.match(await page.locator('#file-status').textContent(), /synthetic-alternative.md/);
  assert.equal(await page.locator('[data-field="draft"]').inputValue(), '첨부와 함께 보관되는 부분 초안');
  await input.setInputFiles({ name: 'oversized.pdf', mimeType: 'application/pdf', buffer: Buffer.alloc(5 * 1024 * 1024 + 1) });
  assert.match(await page.locator('#file-status').textContent(), /synthetic-alternative.md/);
  await input.setInputFiles({ name: 'not-supported.html', mimeType: 'text/html', buffer: Buffer.from('<script>globalThis.reviewExecuted=true</script>') });
  assert.match(await page.locator('#file-status').textContent(), /synthetic-alternative.md/);
  await input.setInputFiles({ name: 'unexecuted.svg', mimeType: 'image/svg+xml', buffer: Buffer.from('<svg xmlns="http://www.w3.org/2000/svg"><script>globalThis.reviewExecuted=true</script></svg>') });
  assert.match(await page.locator('#file-status').textContent(), /unexecuted.svg/);
  assert.equal(await page.locator('#file-status img, #file-status object, #file-status iframe, #file-status svg').count(), 0);
  assert.equal(await page.evaluate(() => globalThis.reviewExecuted), undefined);
  const trigger = action(page, 'overlay', 'logs');
  await trigger.click();
  await page.locator('#detail-body [data-record]').first().check();
  await page.keyboard.press('Escape');
  assert.equal(await trigger.evaluate(node => node === document.activeElement), true);
  await page.reload({ waitUntil: 'networkidle' });
  assert.doesNotMatch(await page.locator('#file-status').textContent(), /unexecuted.svg|synthetic-alternative.md/);
  assert.equal(await page.locator('[data-field="draft"]').inputValue(), '첨부와 함께 보관되는 부분 초안');
});

test('every comparison round exposes exact side histories, full files and actual recipients', { timeout: 120000 }, async t => {
  const page = await openPage(t);
  await page.locator('[data-field="draft"]').fill('비교 탐색 중 보존할 현재 초안');
  const source = await persistedSource(page);
  await action(page, 'currentGrowth').click();
  await action(page, 'sample', 'true').click();
  for (const round of ROUNDS) {
    await action(page, 'round', round.id).click();
    const comparison = await page.locator('.fixed-example').textContent();
    for (const value of [CASE.region, round.result, round.limits, round.finalEvidence, round.approval]) {
      assert.ok(comparison.includes(value), `${round.id}: missing partial-scope, result or evidence boundary`);
    }
    const checks = page.locator('.round-checks tbody tr');
    assert.equal(await checks.count(), round.checks.length);
    for (const [index, check] of round.checks.entries()) {
      assert.equal(await checks.nth(index).locator('td').nth(0).textContent(), check.label);
      assert.equal(await checks.nth(index).locator('td').nth(1).textContent(), check.result);
      assert.equal(await checks.nth(index).locator('[data-action="evidence"]').getAttribute('data-value'), check.evidence);
    }
    for (const side of ['baseline', 'candidate']) {
      const run = RUNS[round[`${side}Run`]];
      assert.equal(await page.locator(`[data-pair="${side}"]`).getAttribute('data-run'), run.id);
      for (const attempt of run.attempts) {
        let pair = await choosePairAttempt(page, side, attempt);
        await verifyFiles(pair, [...attempt.inputs, ...attempt.outputs]);
        if (!attempt.outputs.length) assert.match(await pair.textContent(), /출력 없음/);
        for (const consumer of attempt.consumers) {
          pair = await choosePairAttempt(page, side, attempt);
          await action(pair.locator('.consumers'), 'pairAttempt', `${side}:${consumer.attempt}`).click();
          assert.equal(await pair.locator('[data-inspected-attempt]').getAttribute('data-inspected-attempt'), consumer.attempt);
          const recipient = run.attempts.find(item => item.id === consumer.attempt);
          assert.ok(recipient.inputs.includes(consumer.artifact));
          await verifyFiles(pair, [...recipient.inputs, ...recipient.outputs]);
        }
      }
      const resource = run.nodes.find(node => !run.attempts.some(attempt => attempt.node === node.id));
      const pair = page.locator(`[data-pair="${side}"]`);
      await action(pair, 'pairNode', `${side}:${resource.id}`).click();
      assert.equal(await pair.locator('[data-inspected-attempt]').count(), 0);
      assert.match(await pair.textContent(), /실제 수행 기록 없음/);
      assert.equal(await pair.locator('[data-artifact]').count(), 0);
    }
    assert.deepEqual(await persistedSource(page), source);
    for (const check of round.checks) {
      const trigger = action(page, 'evidence', check.evidence);
      await trigger.click();
      await verifyFiles(page.locator('#detail-body'), [check.evidence]);
      await page.locator('#detail-close').click();
      assert.equal(await trigger.evaluate(node => node === document.activeElement), true);
    }
  }
  await action(page, 'sample', 'false').click();
  await action(page, 'area', 'run').click();
  assert.deepEqual(await persistedSource(page), source);
  assert.equal(await page.locator('[data-field="draft"]').inputValue(), '비교 탐색 중 보존할 현재 초안');
});

test('sample modal follows exact attempts and consumers without retargeting the fresh source', async t => {
  const page = await openPage(t);
  await action(page, 'scope', CASE.region).click();
  await page.locator('[data-field="draft"]').fill('고정 사례와 별개의 현재 부분 대안');
  const source = await persistedSource(page);
  await action(page, 'currentGrowth').click();
  await action(page, 'sample', 'true').click();
  for (const attempt of origin.attempts) {
    const trigger = action(page, 'sampleNode', attempt.node);
    await trigger.click();
    await action(page.locator('#detail-body'), 'sampleAttempt', attempt.id).click();
    assert.equal(await page.locator('#detail-body [data-inspected-attempt]').getAttribute('data-inspected-attempt'), attempt.id);
    await verifyFiles(page.locator('#detail-body'), [...attempt.inputs, ...attempt.outputs]);
    for (const consumer of attempt.consumers) {
      await action(page.locator('#detail-body'), 'sampleAttempt', attempt.id).click();
      await action(page.locator('#detail-body .consumers'), 'sampleConsumer', consumer.attempt).click();
      assert.equal(await page.locator('#detail-body [data-inspected-attempt]').getAttribute('data-inspected-attempt'), consumer.attempt);
      const recipient = origin.attempts.find(item => item.id === consumer.attempt);
      await verifyFiles(page.locator('#detail-body'), [...recipient.inputs, ...recipient.outputs]);
      // Return through the frozen origin trigger: modal history belongs to the
      // currently inspected node, not to every node in the source run.
      await page.locator('#detail-close').click();
      await trigger.click();
    }
    await page.keyboard.press('Escape');
    assert.equal(await trigger.evaluate(node => node === document.activeElement), true);
    assert.deepEqual(await persistedSource(page), source);
  }
  await action(page, 'sampleNode', 'files').click();
  assert.match(await page.locator('#detail-body').textContent(), /실제 수행 기록 없음/);
  assert.equal(await page.locator('#detail-body [data-artifact]').count(), 0);
  await page.locator('#detail-close').click();
  await action(page, 'sample', 'false').click();
  await action(page, 'area', 'run').click();
  assert.deepEqual(await persistedSource(page), source);
  assert.equal(await page.locator('[data-field="draft"]').inputValue(), '고정 사례와 별개의 현재 부분 대안');
});

test('narrow graph selection, details state and dialog focus survive repaint', async t => {
  const page = await openPage(t, { viewport: { width: 390, height: 900 } });
  const graphDetails = page.locator('details.run-graph');
  const scroller = graphDetails.locator('.graph-scroll');
  await scroller.evaluate(node => { node.scrollLeft = node.scrollWidth; });
  await action(page, 'node', 'approve').click();
  assert.equal(await graphDetails.evaluate(node => node.open), true);
  assert.ok(await scroller.evaluate(node => node.scrollLeft > 0));
  const selectedIsVisible = await graphDetails.locator('.node.selected').evaluate(node => {
    const box = node.getBoundingClientRect();
    const frame = node.closest('.graph-scroll').getBoundingClientRect();
    return box.left >= frame.left - 1 && box.right <= frame.right + 1;
  });
  assert.equal(selectedIsVisible, true);
  const position = await scroller.evaluate(node => node.scrollLeft);
  await action(page, 'mode', 'conversation').click();
  assert.equal(await graphDetails.evaluate(node => node.open), true);
  assert.ok(Math.abs(await scroller.evaluate(node => node.scrollLeft) - position) <= 1);
  const trigger = action(page, 'overlay', 'connection');
  await trigger.click();
  await page.locator('#detail-body [data-action="close"]').click();
  assert.equal(await trigger.evaluate(node => node === document.activeElement), true);
  assert.ok(Math.abs(await scroller.evaluate(node => node.scrollLeft) - position) <= 1);
  await graphDetails.locator(':scope > summary').click();
  await action(page, 'mode', 'workspace').click();
  assert.equal(await graphDetails.evaluate(node => node.open), false);
  await action(page, 'area', 'design').click();
  await action(page, 'mode', 'graph').click();
  const workModel = page.locator('details.work-model-details');
  await ensureOpen(workModel);
  await page.locator('[data-field="workText"]').fill('열어 본 업무 조건을 유지하는 합성 설명');
  await action(page, 'focus', 'approval').click();
  assert.equal(await workModel.evaluate(node => node.open), true);
  assert.equal(await page.locator('[data-field="workText"]').inputValue(), '열어 본 업무 조건을 유지하는 합성 설명');
  await workModel.locator(':scope > summary').click();
  await action(page, 'focus', 'memory').click();
  assert.equal(await workModel.evaluate(node => node.open), false);
});

test('write failures preserve the last saved snapshot and the current in-memory draft', async t => {
  const prior = JSON.stringify(createState());
  const page = await openPage(t, { initPayload: { key: KEY, prior }, init: ({ key, prior }) => {
    if (location.protocol !== 'http:') return;
    sessionStorage.setItem(key, prior);
    sessionStorage.setItem('review-unrelated', 'keep');
    const originalSet = Storage.prototype.setItem;
    Storage.prototype.setItem = function (name, value) {
      if (name === key) throw new Error('synthetic quota failure');
      return originalSet.call(this, name, value);
    };
  } });
  const draft = '\n쓰기 실패 중에도 유지할 시험 입력';
  await page.locator('[data-field="draft"]').fill(draft);
  assert.match(await page.locator('#storage-status').textContent(), /보관 실패/);
  await action(page, 'mode', 'conversation').click();
  assert.equal(await page.locator('[data-field="draft"]').inputValue(), draft);
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), KEY), prior);
  assert.equal(await page.evaluate(() => sessionStorage.getItem('review-unrelated')), 'keep');
});

test('read failures block implicit replacement and cancelling recovery preserves unread data', async t => {
  const page = await openPage(t, { init: key => {
    if (location.protocol !== 'http:') return;
    sessionStorage.setItem(key, 'synthetic-unread-snapshot');
    const originalGet = Storage.prototype.getItem;
    const originalSet = Storage.prototype.setItem;
    globalThis.reviewReadSnapshot = () => originalGet.call(sessionStorage, key);
    globalThis.reviewWriteCount = 0;
    Storage.prototype.getItem = function () { throw new Error('synthetic read failure'); };
    Storage.prototype.setItem = function (name, value) {
      if (name === key) globalThis.reviewWriteCount += 1;
      return originalSet.call(this, name, value);
    };
  } });
  await page.locator('[data-field="draft"]').fill('읽지 못한 보관본과 별도로 남길 현재 입력');
  await action(page, 'mode', 'workspace').click();
  assert.equal(await page.evaluate(() => reviewReadSnapshot()), 'synthetic-unread-snapshot');
  assert.equal(await page.evaluate(() => reviewWriteCount), 0);
  page.once('dialog', dialog => dialog.dismiss());
  await action(page, 'save').click();
  assert.equal(await page.evaluate(() => reviewReadSnapshot()), 'synthetic-unread-snapshot');
  assert.equal(await page.evaluate(() => reviewWriteCount), 0);
  assert.match(await page.locator('#storage-status').textContent(), /자동 보관 중지|이전 값/);
});

test('failed reset preserves current text, attachment and stored data', async t => {
  const page = await openPage(t, { init: () => {
    if (location.protocol !== 'http:') return;
    Storage.prototype.removeItem = function () { throw new Error('synthetic deletion failure'); };
  } });
  await page.locator('[data-field="draft"]').fill('초기화 실패 시 유지할 내용');
  await page.locator('#alternative-file').setInputFiles({ name: 'retained.md', mimeType: 'text/plain', buffer: Buffer.from('Retained synthetic file.') });
  const before = await page.evaluate(key => sessionStorage.getItem(key), KEY);
  page.once('dialog', dialog => dialog.accept());
  await action(page, 'reset').click();
  assert.match(await page.locator('#storage-status').textContent(), /초기화 실패/);
  assert.equal(await page.locator('[data-field="draft"]').inputValue(), '초기화 실패 시 유지할 내용');
  assert.match(await page.locator('#file-status').textContent(), /retained.md/);
  assert.equal(await page.evaluate(key => sessionStorage.getItem(key), KEY), before);
});

test('named review captures show design, fresh input, inquiry, exact pairs and read-only details', async t => {
  const page = await openPage(t);
  await capture(page, '00-run-overview');
  await action(page, 'area', 'design').click();
  await action(page, 'focus', 'approval').click();
  assert.equal(await page.locator('.candidates .candidate').count(), DESIGNS.length);
  for (const design of DESIGNS) {
    const candidate = page.locator(`.candidate[data-design="${design.id}"]`);
    assert.equal(await candidate.locator('.node.selected').count(), design.focus.approval.length);
  }
  await page.evaluate(() => scrollTo(0, 0));
  await capture(page, '01-design');
  for (const design of DESIGNS) await capture(page, `01-design-${design.id}-graph`, page.locator(`.candidate[data-design="${design.id}"]`));
  await action(page, 'design', REVISED_DESIGN.id).click();
  assert.match(await page.locator('.selected-design').textContent(), new RegExp(REVISED_DESIGN.version));
  await capture(page, '01-merged-design-graph', page.locator('.selected-design .graph-scroll'));
  await chooseAttempt(page, origin, originalAttempt);
  await action(page, 'artifact', CASE.original).click();
  await action(page, 'scope', CASE.region).click();
  await page.locator('[data-field="draft"]').fill('동시에 이용 가능한 공간과 각각의 시간 선택지를 구분하는 시험용 부분 문구');
  await capture(page, '02-run-graph', page.locator('details.run-graph .graph-scroll'));
  await page.locator('.alternative-editor').evaluate(node => node.scrollIntoView({ block: 'start' }));
  await capture(page, '02-run-and-alternative');
  await action(page, 'currentGrowth').click();
  await page.evaluate(() => scrollTo(0, 0));
  await capture(page, '03-new-input-unanalysed');
  await action(page, 'sample', 'true').click();
  await page.evaluate(() => scrollTo(0, 0));
  await capture(page, '04-fixed-inquiry');
  await capture(page, '04-inquiry-graph', page.locator('.fixed-example > .graph-scroll'));
  await capture(page, '04-competing-explanations', page.locator('.hypotheses'));
  await action(page, 'round', ROUNDS[0].id).click();
  await page.locator('.paired-runs').evaluate(node => node.scrollIntoView({ block: 'start' }));
  await capture(page, '05-paired-review');
  for (const side of ['baseline', 'candidate']) await capture(page, `05-${side}-graph`, page.locator(`[data-pair="${side}"] .graph-scroll`));
  await capture(page, '05-partial-outside-effects', page.locator('.round-checks'));
  for (const name of ['connection', 'logs', 'audit', 'approval']) {
    await action(page, 'overlay', name).click();
    await capture(page, `06-${name}`);
    await page.locator('#detail-close').click();
  }
});

test('all areas and modes fit 1440, 1024 and 390 widths in both themes with valid images', { timeout: 180000 }, async t => {
  const page = await openPage(t);
  await action(page, 'area', 'growth').click();
  await action(page, 'sample', 'true').click();
  for (const width of [1440, 1024, 390]) for (const colorScheme of ['light', 'dark']) {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ colorScheme });
    for (const area of ['design', 'run', 'growth']) for (const mode of ['workspace', 'conversation', 'graph']) {
      const label = `${area}/${mode}/${width}/${colorScheme}`;
      await action(page, 'area', area).click();
      await action(page, 'mode', mode).click();
      await page.evaluate(() => scrollTo(0, 0));
      const dimensions = await page.evaluate(() => ({ width: innerWidth, root: document.documentElement.scrollWidth, body: document.body.scrollWidth }));
      assert.ok(dimensions.root <= width + 1 && dimensions.body <= width + 1, `${label}: body overflow ${JSON.stringify(dimensions)}`);
      await decodeImages(page);
      for (const node of await page.locator('.graph .node').all()) {
        const fits = await node.evaluate(element => [...element.querySelectorAll('text')].every(text => {
          const box = text.getBBox();
          return box.x >= 0 && box.x + box.width <= 140 && box.y >= 0 && box.y + box.height <= 48;
        }));
        assert.equal(fits, true, `${label}: node label exceeds its box`);
      }
      await capture(page, `matrix-${width}-${colorScheme}-${area}-${mode}`);
    }
    await capture(page, `07-growth-${width}-${colorScheme}`);
    await action(page, 'area', 'run').click();
    await action(page, 'mode', 'graph').click();
    await ensureOpen(page.locator('details.run-graph'));
    // The narrow supplement should show the actual selected node, not just
    // the left edge of a larger scrollable graph after an area round trip.
    await page.locator('details.run-graph .node.selected').click();
    assert.equal(await page.locator('details.run-graph .node.selected').evaluate(node => {
      const box = node.getBoundingClientRect();
      const frame = node.closest('.graph-scroll').getBoundingClientRect();
      return box.width > 0 && box.height > 0 && box.left >= frame.left - 1 && box.right <= frame.right + 1;
    }), true, `selected run node must be visible before capture ${width}/${colorScheme}`);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await capture(page, `08-run-graph-${width}-${colorScheme}`, page.locator('details.run-graph .graph-scroll'));
  }
});
