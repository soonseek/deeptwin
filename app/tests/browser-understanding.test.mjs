import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm, readFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { ensureModelSelection } from './helpers/model-selection.mjs';
import { localContextOptions, localGet, localRouteFetch, mintLaunchURL } from './helpers/local-session.mjs';

let browser;
const root = fileURLToPath(new URL('../../', import.meta.url));
test.before(async () => {
  assert.ok(process.env.CONTROL_PLAYWRIGHT_MODULE, 'Bundled Playwright is required; never skip browser evidence');
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
test.after(async () => browser?.close());

async function open(t, scenario = 'success', options = {}, providerReady = true) {
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-understanding-ui-'));
  const args = ['app/tests/fixtures/understanding_server.py', '--data-dir', dir, '--port', '0', '--scenario', scenario];
  if (!providerReady) args.push('--not-ready');
  const server = spawn(process.env.CONTROL_PYTHON || 'python3', args, { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(async () => {
    if (server.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
    await rm(dir, { recursive: true, force: true });
  });
  const url = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Fixture server not ready: ${output}`)), 15000);
    const read = data => { output += data; const match = output.match(/http:\/\/127\.0\.0\.1:\d+/); if (match) { clearTimeout(timer); resolve(match[0]); } };
    server.stdout.on('data', read); server.stderr.on('data', read);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${output}`)); });
  });
  const context = await browser.newContext(localContextOptions({ baseURL: url, ...options }));
  t.after(() => context.close());
  const page = await context.newPage();
  const requests = [], errors = [], external = [];
  page.on('request', request => {
    requests.push({ path: new URL(request.url()).pathname, method: request.method(), body: request.postData() });
    if (!request.url().startsWith(url + '/')) external.push(request.url());
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(await mintLaunchURL(url));
  await page.locator('#app[data-ready="true"]').waitFor();
  page.setDefaultTimeout(6000);
  return { page, requests, errors, external, calls: async () => {
    try { return (await readFile(join(dir, 'model-calls.jsonl'), 'utf8')).trim().split('\n').map(JSON.parse); }
    catch (error) { if (error.code === 'ENOENT') return []; throw error; }
  } };
}
async function save(page, text) {
  await page.locator('#work-text').fill(text);
  await page.locator('#save-status[data-state="saved"]').waitFor();
  const id = await page.locator('#app').getAttribute('data-work-id');
  return (await localGet(page, `/api/works/${id}`)).json();
}
async function submit(page) {
  await ensureModelSelection(page);
  await page.getByRole('button', { name: '업무 이해하기', exact: true }).click();
}
async function finished(page, status = 'succeeded') { await page.locator(`#understanding-record[data-status="${status}"]`).waitFor(); }

test('artifact format labels preserve provider aliases and unfamiliar non-text kinds', async t => {
  const { page, calls } = await open(t);
  await save(page, 'PDF와 CSV 형식으로 정리하는 합성 업무');
  await submit(page); await finished(page);
  let mediaType = 'PDF';
  await page.route('**/understanding-requests', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await localRouteFetch(route);
    const records = await response.json();
    for (const record of records) if (record.result) record.result.deliverables[0].media_type = mediaType;
    await route.fulfill({ response, json: records });
  });
  for (const [format, label] of [['PDF', 'PDF'], ['CSV', 'CSV 표'], ['video/custom-v1', '형식: video/custom-v1']]) {
    mediaType = format;
    await page.reload(); await finished(page);
    assert.equal(await page.locator('[data-media-type]').first().textContent(), label);
  }
  assert.equal((await calls()).length, 1);
});

test('an unready provider blocks understanding before transfer while input, saving, files and connections remain usable', async t => {
  const { page, requests, calls } = await open(t, 'success', { viewport: { width: 1024, height: 900 } }, false);
  const bootstrap = await (await localGet(page, '/api/bootstrap')).json();
  assert.equal(bootstrap.capabilities.understanding_provider_ready, false);
  await save(page, '연결을 준비하는 동안 보관할 업무');
  await page.locator('#work-files').setInputFiles({ name: '보관.txt', mimeType: 'text/plain', buffer: Buffer.from('아직 보내지 않을 자료') });
  await page.locator('#upload-status[data-state="done"]').waitFor();
  assert.equal(await page.locator('#prepare-design').isDisabled(), true);
  assert.match(await page.locator('.transfer-boundary').textContent(), /사용할 모델.*저장.*보내지/);
  await page.locator('#prepare-design').dispatchEvent('click');
  await page.waitForTimeout(300);
  assert.equal(requests.filter(item => item.method === 'POST' && item.path.endsWith('/understanding-requests')).length, 0);
  assert.deepEqual(await calls(), []);
  assert.equal(await page.locator('#work-text').inputValue(), '연결을 준비하는 동안 보관할 업무');
  assert.equal(await page.locator('#file-list [data-file-id]').count(), 1);
  await page.locator('#open-connections').click();
  await page.locator('#provider-panel:not([hidden])').waitFor();
  assert.equal(await page.getByRole('button', { name: '연결 확인', exact: true }).isEnabled(), true);
  await page.locator('#prepare-design').scrollIntoViewIfNeeded();
  const out = join(root, 'app/review-output'); await mkdir(out, { recursive: true });
  await page.screenshot({ path: join(out, 'understanding-not-ready-1024-light.png'), fullPage: true });
});

test('the single explicit action previews exact transfer boundaries and saving never calls a model', async t => {
  const { page, calls, requests, errors, external } = await open(t);
  assert.equal(await page.getByRole('button', { name: '업무 이해하기', exact: true }).count(), 1);
  assert.equal(await page.locator('#prepare-design').isDisabled(), true);
  const literal = '\n  회의 전에 PDF로 정리해 주세요. <script>literal</script>  ';
  await save(page, literal);
  await page.locator('#work-files').setInputFiles([
    { name: '읽을 원문.txt', mimeType: 'text/plain', buffer: Buffer.from('자료의 정확한 글자\n공백  ') },
    { name: '읽지 못한.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nRAW-PDF-CONTENT-NOT-TRANSFERRED') },
  ]);
  await page.locator('#upload-status[data-state="done"]').waitFor();
  await page.locator('#transfer-preview > summary').click();
  assert.equal(await page.locator('#transfer-description').textContent(), literal);
  assert.match(await page.locator('#transfer-files').textContent(), /자료의 정확한 글자\n공백  /);
  assert.match(await page.locator('#transfer-files').textContent(), /읽지 못한\.pdf/);
  assert.match(await page.locator('#transfer-preview').textContent(), /읽지 못한.*내용.*보내지|미독해.*보내지/);
  assert.deepEqual(await calls(), []);
  await submit(page);
  await finished(page);
  const [envelope] = await calls();
  assert.equal(envelope.sources[0].text, literal);
  assert.equal(envelope.sources.find(source => source.name === '읽을 원문.txt').text, '자료의 정확한 글자\n공백  ');
  assert.equal(envelope.sources.find(source => source.name === '읽지 못한.pdf').text, '');
  assert.equal(requests.filter(item => item.path.endsWith('/understanding-requests') && item.method === 'POST').length, 1);
  assert.equal(await page.locator('[data-provider], svg, .graph').count(), 0);
  assert.equal(await page.locator('#understanding-record img, #understanding-record script').count(), 0);
  assert.equal(await page.evaluate(() => window.injected), undefined);
  assert.match(await page.locator('#understanding-record').textContent(), /제가 이해한 업무|업무 이해 초안/);
  assert.equal(await page.locator('[data-media-type="application/pdf"]').textContent(), 'PDF');
  assert.equal(await page.locator('[data-media-type="application/pdf"]').getAttribute('title'), 'application/pdf');
  assert.match(await page.locator('.understanding-questions').textContent(), /누가 최종 검토하나요.*검토 책임자/s);
  assert.equal(await page.locator('#understanding-record input, #understanding-record textarea, #understanding-record form').count(), 0);
  assert.equal(await page.locator('#prepare-design').isEnabled(), true, 'open questions cannot become a mandatory approval gate');
  assert.deepEqual(errors, []); assert.deepEqual(external, []);
});

test('running results recover with GET only and cancel explicitly without a second model call', async t => {
  const { page, calls, requests } = await open(t, 'cancel');
  await save(page, '취소할 업무'); await submit(page);
  await page.locator('#understanding-record[data-status="running"]').waitFor();
  const id = await page.locator('#understanding-record').getAttribute('data-request-id');
  await page.reload(); await page.locator('#app[data-ready="true"]').waitFor();
  await page.locator('#understanding-record[data-status="running"]').waitFor();
  assert.equal(await page.locator('#understanding-record').getAttribute('data-request-id'), id);
  await page.getByRole('button', { name: '업무 이해 취소', exact: true }).click();
  await finished(page, 'cancelled');
  assert.equal((await calls()).length, 1);
  assert.equal(requests.filter(item => item.path.endsWith('/understanding-requests') && item.method === 'POST').length, 1);
});

test('editing and file additions mark old results, preserve literal input, and corrections focus the original input', async t => {
  const { page } = await open(t, 'slow');
  const old = await save(page, '첫 저장본의 업무'); await submit(page);
  await page.locator('#understanding-record').waitFor();
  const literal = '\n새 입력 <b>그대로</b>  ';
  await page.locator('#work-text').fill(literal);
  await page.locator('#understanding-record[data-stale="true"]').waitFor();
  await finished(page);
  assert.equal(await page.locator('#work-text').inputValue(), literal);
  assert.match(await page.locator('#understanding-revision').textContent(), new RegExp(`저장본 ${old.revision}`));
  assert.match(await page.locator('#understanding-revision').textContent(), /이전|달라/);
  await page.getByRole('button', { name: '원 입력에서 바로잡기', exact: true }).click();
  assert.equal(await page.evaluate(() => document.activeElement.id), 'work-text');
  await page.locator('#work-files').setInputFiles({ name: '추가.txt', mimeType: 'text/plain', buffer: Buffer.from('새 자료') });
  await page.locator('#upload-status[data-state="done"]').waitFor();
  assert.equal(await page.locator('#understanding-record').getAttribute('data-stale'), 'true');
});

test('work switching never paints another work result and returning restores its exact request', async t => {
  const { page } = await open(t, 'slow');
  const first = await save(page, '첫 업무'); await submit(page);
  await page.locator('#understanding-record').waitFor();
  const requestId = await page.locator('#understanding-record').getAttribute('data-request-id');
  await page.locator('#new-work').click();
  const second = await save(page, '두 번째 업무');
  await page.waitForTimeout(2000);
  assert.equal(await page.locator('#understanding-record').count(), 0);
  assert.equal(await page.locator('#work-text').inputValue(), second.text);
  await page.locator('#work-select').selectOption(first.id); await finished(page);
  assert.equal(await page.locator('#understanding-record').getAttribute('data-request-id'), requestId);
});

test('failed generation retries only by explicit new request and never claims approval', async t => {
  const { page, calls, requests } = await open(t, 'fail-once');
  await save(page, '재시도할 업무'); await submit(page); await finished(page, 'failed');
  assert.match(await page.locator('#understanding-record').textContent(), /연결|완료하지/);
  await page.waitForTimeout(1200); assert.equal((await calls()).length, 1);
  await submit(page); await finished(page);
  const bodies = requests.filter(item => item.path.endsWith('/understanding-requests') && item.method === 'POST').map(item => JSON.parse(item.body));
  assert.equal(bodies.length, 2); assert.notEqual(bodies[0].request_key, bodies[1].request_key);
  assert.match(await page.locator('#understanding-record').textContent(), /초안/);
  assert.match(await page.locator('#understanding-record').textContent(), /틀린 부분.*바로잡/);
  assert.match(await page.locator('#capability-note').textContent(), /설계와 실행.*연결되지/);
  assert.doesNotMatch(await page.locator('#understanding-record').textContent(), /승인 완료|설계 생성 완료/);
});

test('an uncertain response can retry the identical request key without a second model call', async t => {
  const { page, calls, requests } = await open(t);
  await save(page, '응답 유실 업무');
  let intercepted = false;
  await page.route('**/understanding-requests', async route => {
    if (route.request().method() === 'POST' && !intercepted) {
      intercepted = true; await localRouteFetch(route); await route.abort();
    } else await route.continue();
  });
  await submit(page);
  await page.getByRole('button', { name: '같은 요청 확인하기', exact: true }).waitFor();
  const firstWorkId = await page.locator('#app').getAttribute('data-work-id');
  await page.locator('#new-work').click();
  await save(page, '잠깐 확인한 다른 업무');
  await page.locator('#work-select').selectOption(firstWorkId);
  await page.waitForFunction(id => document.querySelector('#app').dataset.workId === id, firstWorkId);
  assert.match(await page.locator('#understanding-message').textContent(), /같은 요청 번호|같은 요청.*확인/);
  await save(page, '응답이 유실된 뒤 새로 고친 입력');
  await page.getByRole('button', { name: '같은 요청 확인하기', exact: true }).click();
  await finished(page);
  const bodies = requests.filter(item => item.path.endsWith('/understanding-requests') && item.method === 'POST').map(item => JSON.parse(item.body));
  assert.equal(bodies.length, 2); assert.deepEqual(bodies[0], bodies[1]);
  assert.equal((await calls()).length, 1);
  assert.equal(await page.locator('#understanding-record').getAttribute('data-stale'), 'true');
  assert.equal(await page.evaluate(() => Object.keys(localStorage).join(',')), 'deeptwin.selected-work');
});

test('unreadable files alone fail honestly with no model invocation', async t => {
  const { page, calls } = await open(t);
  await page.locator('#work-files').setInputFiles({ name: '미독해.pdf', mimeType: 'application/pdf', buffer: Buffer.from('%PDF-1.4\nNO-EXTRACTABLE-TEXT') });
  await page.locator('#upload-status[data-state="done"]').waitFor();
  await submit(page); await finished(page, 'failed');
  assert.match(await page.locator('#understanding-record').textContent(), /보낼 글자가 없습니다/);
  assert.deepEqual(await calls(), []);
});

test('connection failures offer an explicit return path but isolation failure does not prescribe login', async t => {
  for (const scenario of ['subscription_required', 'fail-once', 'isolation_unavailable']) {
    const { page, requests } = await open(t, scenario);
    await save(page, '실패 경계 확인'); await submit(page); await finished(page, 'failed');
    assert.equal(await page.locator('#understanding-record').getAttribute('data-reason'), scenario === 'fail-once' ? 'provider_unavailable' : scenario);
    const connect = page.locator('#understanding-record').getByRole('button', { name: 'Codex 연결 살펴보기', exact: true });
    if (scenario === 'isolation_unavailable') {
      assert.equal(await connect.count(), 0);
      assert.match(await page.locator('#understanding-record').textContent(), /격리.*자료를 보내지/);
    } else {
      await connect.click();
      await page.locator('#provider-panel:not([hidden])').waitFor();
    }
    assert.equal(requests.filter(item => item.method === 'POST' && /\/providers\//.test(item.path)).length, 0, 'returning to connections neither logs in nor checks automatically');
  }
});

test('only the explicit initial response reveals progress; typing, polling, and reload never force scrolling', async t => {
  for (const editing of [false, true]) {
    const { page } = await open(t, 'slow', { viewport: { width: 1024, height: 600 } });
    await save(page, '진행 상태 위치 확인');
    await page.evaluate(() => {
      window.panelScrolls = 0;
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (...args) {
        if (this.id === 'understanding-panel') window.panelScrolls++;
        return original.apply(this, args);
      };
    });
    let release, announce;
    const gate = new Promise(resolve => { release = resolve; });
    const started = new Promise(resolve => { announce = resolve; });
    t.after(() => release());
    await page.route('**/understanding-requests', async route => {
      if (route.request().method() === 'POST') {
        const response = await localRouteFetch(route); announce(); await gate; await route.fulfill({ response });
      } else await route.continue();
    });
    await submit(page); await started;
    if (editing) await page.locator('#work-text').fill('응답 전에 입력을 고치는 중');
    release(); await page.locator('#understanding-record').waitFor();
    assert.equal(await page.evaluate(() => window.panelScrolls), editing ? 0 : 1);
    if (!editing) assert.equal(await page.locator('#understanding-title').evaluate(el => el.getBoundingClientRect().top >= 0 && el.getBoundingClientRect().bottom <= innerHeight), true);
    await finished(page);
    assert.equal(await page.evaluate(() => window.panelScrolls), editing ? 0 : 1, 'poll completion must not scroll');
    await page.addInitScript(() => {
      window.restoredScrolls = 0;
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (...args) { if (this.id === 'understanding-panel') window.restoredScrolls++; return original.apply(this, args); };
    });
    await page.reload(); await finished(page);
    assert.equal(await page.evaluate(() => window.restoredScrolls), 0);
  }
});

test('unchanged running requests stop after 120 real status reads and never restart the model', async t => {
  const { page, calls, requests } = await open(t, 'cancel');
  await save(page, '응답 대기 한도 확인');
  await page.clock.install(); await submit(page);
  await page.locator('#understanding-record').waitFor();
  const initial = requests.filter(item => item.method === 'GET' && item.path.endsWith('/understanding-requests')).length;
  for (let index = 0; index < 120; index++) {
    const response = page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname.endsWith('/understanding-requests'));
    await page.clock.runFor(1500); await response;
    // Only the browser timer is accelerated; each HTTP read and service state is real.
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  await page.waitForFunction(() => document.querySelector('#understanding-message').textContent.includes('자동 확인은 멈췄습니다'));
  assert.equal(requests.filter(item => item.method === 'GET' && item.path.endsWith('/understanding-requests')).length, initial + 120);
  await page.clock.runFor(30000);
  assert.equal(requests.filter(item => item.method === 'GET' && item.path.endsWith('/understanding-requests')).length, initial + 120);
  assert.equal((await calls()).length, 1);
  await page.getByRole('button', { name: '업무 이해 취소', exact: true }).click(); await finished(page, 'cancelled');
  assert.equal(await page.locator('#understanding-message').textContent(), '', 'successful cancellation clears the obsolete polling notice');
  assert.equal(await page.locator('#refresh-understanding').isVisible(), false);
});

test('successful record recovery clears only its temporary read error without sending a new request', async t => {
  const { page, requests } = await open(t);
  await save(page, '기록 복구 확인'); await submit(page); await finished(page);
  await page.route('**/understanding-requests', route => route.request().method() === 'GET' ? route.abort() : route.continue());
  await page.reload();
  await page.getByRole('button', { name: '결과 다시 확인', exact: true }).waitFor();
  assert.match(await page.locator('#understanding-message').textContent(), /읽지 못했습니다/);
  await page.unroute('**/understanding-requests');
  await page.getByRole('button', { name: '결과 다시 확인', exact: true }).click(); await finished(page);
  assert.equal(await page.locator('#understanding-message').textContent(), '');
  assert.equal(requests.filter(item => item.path.endsWith('/understanding-requests') && item.method === 'POST').length, 1);
});

test('understanding result remains readable on mobile and desktop in both schemes without external content', async t => {
  const out = join(root, 'app/review-output'); await mkdir(out, { recursive: true });
  for (const width of [390, 1024]) for (const colorScheme of ['light', 'dark']) {
    const { page, errors, external } = await open(t, 'success', { viewport: { width, height: 1000 }, colorScheme });
    await save(page, '월요일 회의 전에 자료를 모아 PDF로 정리해 주세요.'); await submit(page); await finished(page);
    await page.locator('#understanding-record').scrollIntoViewIfNeeded();
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
    assert.deepEqual(errors, []); assert.deepEqual(external, []);
    await page.screenshot({ path: join(out, `understanding-${width}-${colorScheme}.png`), fullPage: true });
  }
});
