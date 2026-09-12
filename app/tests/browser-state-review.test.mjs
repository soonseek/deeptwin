import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { ensureModelSelection } from './helpers/model-selection.mjs';
import { localContextOptions, localGet, localRouteFetch, mintLaunchURL } from './helpers/local-session.mjs';

let server, browser, dataDir, baseURL;
test.before(async () => {
  assert.ok(process.env.CONTROL_PLAYWRIGHT_MODULE, 'browser runtime is required, never skipped');
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  dataDir = await mkdtemp(join(tmpdir(), 'deeptwin-state-review-'));
  server = spawn(process.env.CONTROL_PYTHON || 'python3', ['app/tests/fixtures/understanding_server.py', '--data-dir', dataDir, '--port', '0'], {
    cwd: fileURLToPath(new URL('../../', import.meta.url)), stdio: ['ignore', 'pipe', 'pipe'],
  });
  baseURL = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Server not ready: ${output}`)), 15000);
    const read = chunk => {
      output += chunk;
      const url = output.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (url) { clearTimeout(timer); resolve(url[0]); }
    };
    server.stdout.on('data', read); server.stderr.on('data', read);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Server exited ${code}`)); });
  });
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
test.after(async () => {
  await browser?.close();
  if (server?.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
  if (dataDir) await rm(dataDir, { recursive: true, force: true });
});

async function open(t) {
  const context = await browser.newContext(localContextOptions({ baseURL }));
  t.after(() => context.close());
  const page = await context.newPage();
  await page.goto(await mintLaunchURL(baseURL));
  await page.locator('#app[data-ready="true"]').waitFor();
  return page;
}
async function saved(page) {
  await page.locator('#save-status[data-state="saved"]').waitFor();
  const id = await page.locator('#app').getAttribute('data-work-id');
  return (await localGet(page, `/api/works/${id}`)).json();
}
async function create(page, text) {
  await page.locator('#work-text').fill(text);
  return saved(page);
}
function gate() {
  let release, started;
  return { wait: new Promise(resolve => { release = resolve; }), started: new Promise(resolve => { started = resolve; }),
    release: () => release(), start: () => started() };
}

test('failed work switch keeps picker, actual work and unsaved literal text aligned', async t => {
  const page = await open(t);
  const first = await create(page, '첫 번째 업무');
  await page.locator('#new-work').click();
  const second = await create(page, '두 번째 업무');
  await page.locator('#work-select').selectOption(first.id);
  await page.waitForFunction(id => document.querySelector('#app').dataset.workId === id, first.id);
  await page.route(`**/api/works/${first.id}`, route => route.request().method() === 'PUT' ? route.abort() : route.continue());
  const literal = '\n실패 후 남아야 할 첫 업무 수정 <script>literal</script>';
  await page.locator('#work-text').fill(literal);
  await page.locator('#work-select').selectOption(second.id);
  await page.locator('#save-status[data-state="error"]').waitFor();
  assert.equal(await page.locator('#app').getAttribute('data-work-id'), first.id);
  assert.equal(await page.locator('#work-text').inputValue(), literal);
  assert.equal(await page.locator('#work-select').inputValue(), first.id, 'failed navigation must not label the first work as the second');
  assert.equal((await (await localGet(page, `/api/works/${second.id}`)).json()).text, second.text);
});

test('typing while a file upload is pending survives its old-text response and restart', async t => {
  const page = await open(t);
  const work = await create(page, '업로드 전');
  const delayed = gate();
  t.after(() => delayed.release());
  await page.route(`**/api/works/${work.id}/files?*`, async route => { delayed.start(); await delayed.wait; await route.continue(); });
  await page.locator('#work-files').setInputFiles({ name: '자료.txt', mimeType: 'text/plain', buffer: Buffer.from('자료 원문') });
  await delayed.started;
  const literal = '\n업로드 도중 새 설명\n공백  ';
  await page.locator('#work-text').fill(literal);
  assert.equal(await page.locator('#new-work').isDisabled(), true);
  assert.equal(await page.locator('#work-select').isDisabled(), true);
  delayed.release();
  await page.locator('#upload-status[data-state="done"]').waitFor();
  const stored = await saved(page);
  assert.equal(stored.text, literal);
  assert.equal(stored.files.length, 1);
  await page.reload();
  await page.locator('#app[data-ready="true"]').waitFor();
  assert.equal(await page.locator('#work-text').inputValue(), literal);
  assert.equal(await page.locator('#file-list [data-file-id]').count(), 1);
});

test('an in-flight understanding request stays bound to its old revision while newer text is saved', async t => {
  const page = await open(t);
  const old = await create(page, '요청할 원문');
  await ensureModelSelection(page);
  const delayed = gate();
  t.after(() => delayed.release());
  let requested;
  await page.route(`**/api/works/${old.id}/understanding-requests`, async route => {
    if (route.request().method() === 'POST') {
      requested = route.request().postDataJSON();
      // Commit the immutable request before delaying only its network response.
      const response = await localRouteFetch(route);
      delayed.start(); await delayed.wait; await route.fulfill({ response });
    } else await route.continue();
  });
  await page.locator('#prepare-design').click();
  await delayed.started;
  await page.locator('#work-text').fill('요청 이후의 새 입력');
  delayed.release();
  await page.locator('#understanding-record[data-status]').waitFor();
  await page.waitForFunction(() => document.querySelector('#save-status').dataset.state === 'saved' && document.querySelector('#work-text').value === '요청 이후의 새 입력');
  const newer = await saved(page);
  assert.equal(requested.revision, old.revision);
  assert.ok(newer.revision > old.revision);
  assert.match(await page.locator('#understanding-record').textContent(), new RegExp(`저장본 ${old.revision}`));
  assert.equal(newer.text, '요청 이후의 새 입력');
});

test('uploading from a stale tab cannot overwrite a newer text revision from another tab', async t => {
  const page = await open(t);
  const first = await create(page, '첫 탭이 읽은 원문');
  const other = await page.context().newPage();
  await other.goto(baseURL);
  await other.locator('#app[data-ready="true"]').waitFor();
  assert.equal(await other.locator('#app').getAttribute('data-work-id'), first.id);
  const latestText = '다른 탭에서 확정해 저장한 새 원문';
  await other.locator('#work-text').fill(latestText);
  await other.locator('#save-work').click();
  assert.equal((await saved(other)).text, latestText);
  await page.locator('#work-files').setInputFiles({ name: '추가.txt', mimeType: 'text/plain', buffer: Buffer.from('보관할 자료') });
  await page.waitForFunction(() => !document.querySelector('#new-work').disabled);
  const persisted = await (await localGet(page, `/api/works/${first.id}`)).json();
  assert.equal(persisted.text, latestText, 'a file response must not rebase stale textarea content and overwrite another editor');
  assert.equal(persisted.files.length, 0, 'stale upload must be rejected before adding original bytes');
  assert.equal(persisted.revision, first.revision + 1, 'rejected upload must not create a new work revision');
  assert.match(await page.locator('#upload-results').textContent(), /추가\.txt[\s\S]*실패/);
  assert.equal(await page.locator('#work-text').inputValue(), first.text, 'retain the stale local text until the user resolves the conflict');
});
