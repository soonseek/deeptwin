import test from 'node:test';
import assert from 'node:assert/strict';
import { access, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { ensureModelSelection } from './helpers/model-selection.mjs';
import { localContextOptions, localGet, mintLaunchURL } from './helpers/local-session.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
let running;
let browser;
let server;
let dataDir;

test('first-use frontend has its own three static entry files', async () => {
  for (const file of ['index.html', 'app.mjs', 'styles.css']) {
    await assert.doesNotReject(access(new URL(`../static/${file}`, import.meta.url)), `${file}: first-use frontend is missing`);
  }
});

async function start() {
  if (running) return running;
  running = (async () => {
    assert.ok(process.env.CONTROL_PLAYWRIGHT_MODULE, 'CONTROL_PLAYWRIGHT_MODULE must name the bundled Playwright module; tests are never skipped');
    const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
    dataDir = await mkdtemp(join(tmpdir(), 'deeptwin-first-use-'));
    server = spawn(process.env.CONTROL_PYTHON || 'python3', ['app/tests/fixtures/understanding_server.py', '--data-dir', dataDir, '--port', '0'], { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
    const url = await new Promise((resolve, reject) => {
      let output = '';
      const timer = setTimeout(() => reject(new Error(`App server did not become ready: ${output}`)), 15000);
      const read = chunk => {
        output += chunk;
        const match = output.match(/http:\/\/127\.0\.0\.1:\d+/);
        if (match) { clearTimeout(timer); resolve(match[0]); }
      };
      server.stdout.on('data', read);
      server.stderr.on('data', read);
      server.once('error', error => { clearTimeout(timer); reject(error); });
      server.once('exit', code => { clearTimeout(timer); reject(new Error(`App server exited ${code}: ${output}`)); });
    });
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    return url;
  })();
  return running;
}

test.after(async () => {
  await browser?.close();
  if (server && server.exitCode === null) {
    await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
  }
  if (dataDir) await rm(dataDir, { recursive: true, force: true });
});

async function pageFor(options = {}, init) {
  const url = await start();
  const context = await browser.newContext(localContextOptions({ baseURL: url, ...options }));
  if (init) await context.addInitScript(init);
  const page = await context.newPage();
  const errors = [];
  const external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith(url + '/')) external.push(request.url()); });
  await page.goto(await mintLaunchURL(url));
  await page.locator('#app[data-ready="true"]').waitFor();
  await page.getByRole('button', { name: '새 업무', exact: true }).click();
  return { page, context, url, errors, external };
}

async function savedWork(page) {
  await page.locator('#save-status[data-state="saved"]').waitFor();
  const id = await page.locator('#app').getAttribute('data-work-id');
  assert.ok(id);
  const response = await localGet(page, `/api/works/${id}`);
  assert.equal(response.status(), 200);
  return response.json();
}

test('blank entry is an input space, not a fake graph, and creates no blank record', async () => {
  const { page, context } = await pageFor();
  try {
    const before = await (await localGet(page, '/api/works')).json();
    await page.waitForTimeout(900);
    assert.deepEqual(await (await localGet(page, '/api/works')).json(), before);
    assert.equal(await page.locator('h1').textContent(), '어떤 일을 맡기고 싶으세요?');
    const preview = await page.locator('.development-preview').textContent();
    assert.match(preview, /개발 미리보기/);
    assert.match(preview, /멀티에이전트 환경.*설계·관제/);
    assert.match(preview, /웹 기반 오픈소스 프레임워크로 공개하기 위한/);
    assert.match(preview, /웹 배포.*최초 소유자 설정.*관리형 실행기.*환경 설계·실행.*구현·검증 중/s);
    assert.equal(await page.locator('#work-text').inputValue(), '');
    assert.equal(await page.locator('#save-status').textContent(), '내용을 입력하면 이 DeepTwin 인스턴스에 저장됩니다');
    const storageBoundary = await page.locator('footer').textContent();
    assert.match(storageBoundary, /DeepTwin 인스턴스의 업무 저장소/);
    assert.match(storageBoundary, /브라우저 기기/);
    assert.doesNotMatch(storageBoundary, /이 컴퓨터/);
    assert.equal(await page.locator('svg, .graph, .rail').count(), 0);
    assert.equal(await page.getByRole('button', { name: '업무 이해하기', exact: true }).isEnabled(), false);
  } finally { await context.close(); }
});

test('Claude API-only connection states the supported account path without implying subscription login', async () => {
  const { page, context, external } = await pageFor();
  try {
    await page.locator('#open-connections').click();
    const claude = page.locator('#providers .provider').filter({ has: page.getByRole('heading', { name: 'Claude', exact: true }) });
    await claude.waitFor({ state: 'visible' });
    const text = await claude.textContent();
    assert.match(text, /별도 API 키.*연결/);
    assert.match(text, /구독 로그인.*지원하지/);
    assert.doesNotMatch(text, /CLI|설치 확인|사전 승인/);
    assert.equal(await claude.locator('input[type="password"]').count(), 1);
    assert.equal(await claude.getByRole('button', { name: 'API 키 연결', exact: true }).count(), 1);
    assert.deepEqual(external, []);
  } finally { await context.close(); }
});

test('literal Korean and composition survive saving, selection, reload, and local-storage corruption', async () => {
  const { page, context } = await pageFor({}, () => {
    if (localStorage.getItem('deeptwin.selected-work') === null) localStorage.setItem('deeptwin.selected-work', '{corrupt');
  });
  try {
    const before = await (await localGet(page, '/api/works')).json();
    await page.locator('#work-text').evaluate(el => {
      el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
      el.value = '조합 중';
      el.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true }));
    });
    await page.waitForTimeout(900);
    assert.deepEqual(await (await localGet(page, '/api/works')).json(), before, 'IME in-progress input is not saved');
    const literal = '\n  한국어 업무 <script>window.bad=1</script>\n공백 그대로  ';
    await page.locator('#work-text').evaluate((el, value) => {
      el.value = value;
      el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }));
      el.dispatchEvent(new InputEvent('input', { bubbles: true }));
      el.focus(); el.setSelectionRange(4, 9);
    }, literal);
    const work = await savedWork(page);
    assert.equal(work.text, literal);
    assert.match(await page.locator('#save-status').textContent(), /^DeepTwin 인스턴스에 저장됨/);
    assert.doesNotMatch(await page.locator('#save-status').textContent(), /이 컴퓨터/);
    assert.deepEqual(await page.locator('#work-text').evaluate(el => [el.selectionStart, el.selectionEnd]), [4, 9]);
    assert.equal(await page.evaluate(() => window.bad), undefined);
    const storage = await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)));
    assert.equal(storage['deeptwin.selected-work'], work.id);
    assert.ok(!JSON.stringify(storage).includes(literal));
    await page.reload();
    await page.locator('#app[data-ready="true"]').waitFor();
    assert.equal(await page.locator('#work-text').inputValue(), literal);
    assert.match(await page.locator('#save-status').textContent(), /^DeepTwin 인스턴스에 저장됨/);
  } finally { await context.close(); }
});

test('multiple real uploads report per-file outcomes and keep successful originals across reload', async () => {
  const { page, context } = await pageFor();
  try {
    const files = [
      { name: '회의 원문.txt', mimeType: 'text/plain', buffer: Buffer.from('첫 자료\n<script>literal</script>') },
      { name: '실행.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('not executable') },
      { name: '다음 자료.md', mimeType: 'text/markdown', buffer: Buffer.from('# 두 번째 자료') },
    ];
    await page.locator('#work-files').setInputFiles(files);
    await page.locator('#upload-status[data-state="done"]').waitFor();
    const work = await savedWork(page);
    assert.deepEqual(work.files.map(file => file.name), [files[0].name, files[2].name]);
    assert.match(await page.locator('#upload-results').textContent(), /실행\.exe[\s\S]*실패/);
    assert.match(await page.locator('#upload-results').textContent(), /파일 형식|20,000자/, 'show the actual server recovery reason, not only an HTTP code');
    for (const [index, file] of work.files.entries()) {
      const original = await localGet(page, `/api/works/${work.id}/files/${file.id}`);
      assert.deepEqual(await original.body(), files[index === 0 ? 0 : 2].buffer);
      assert.equal(await page.locator(`[data-file-id="${file.id}"] a[download]`).count(), 1);
    }
    assert.match(await page.locator('#file-list').textContent(), /읽음/);
    assert.doesNotMatch(await page.locator('#file-list').textContent(), /업무 이해 완료|분석 완료/);
    await page.reload();
    await page.locator('#app[data-ready="true"]').waitFor();
    assert.equal(await page.locator('#file-list [data-file-id]').count(), 2);
  } finally { await context.close(); }
});

test('composition starting during an in-flight save does not persist unfinished Korean', async () => {
  const { page, context } = await pageFor();
  let release;
  try {
    await page.locator('#work-text').fill('기존 내용');
    const work = await savedWork(page);
    const gate = new Promise(resolve => { release = resolve; });
    let intercepted;
    const started = new Promise(resolve => { intercepted = resolve; });
    let delayed = false;
    await page.route(`**/api/works/${work.id}`, async route => {
      if (route.request().method() === 'PUT' && !delayed) { delayed = true; intercepted(); await gate; }
      await route.continue();
    });
    await page.locator('#work-text').fill('저장 요청한 내용');
    await started;
    await page.locator('#work-text').evaluate(el => {
      el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
      el.value = '아직 조합 중ㅇ';
      el.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true }));
    });
    release();
    await page.waitForTimeout(850);
    assert.equal((await (await localGet(page, `/api/works/${work.id}`)).json()).text, '저장 요청한 내용');
    assert.equal(await page.locator('#work-text').inputValue(), '아직 조합 중ㅇ');
    assert.notEqual(await page.locator('#save-status').getAttribute('data-state'), 'saved');
    await page.locator('#work-text').evaluate(el => {
      el.value = '입력을 마친 한국어';
      el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }));
      el.dispatchEvent(new InputEvent('input', { bubbles: true }));
    });
    assert.equal((await savedWork(page)).text, '입력을 마친 한국어');
  } finally { release?.(); await context.close(); }
});

test('failed saves retain unsaved text and cannot create a request for an unsaved revision', async () => {
  const { page, context } = await pageFor();
  try {
    await page.locator('#work-text').fill('먼저 저장');
    const work = await savedWork(page);
    await ensureModelSelection(page);
    await page.route(`**/api/works/${work.id}`, route => route.request().method() === 'PUT' ? route.abort() : route.continue());
    await page.locator('#work-text').fill('사라지면 안 되는 수정');
    await page.getByRole('button', { name: '저장', exact: true }).click();
    await page.locator('#save-status[data-state="error"]').waitFor();
    assert.equal(await page.locator('#work-text').inputValue(), '사라지면 안 되는 수정');
    let requests = 0;
    page.on('request', request => { if (request.url().includes('/understanding-requests') && request.method() === 'POST') requests++; });
    await page.getByRole('button', { name: '업무 이해하기', exact: true }).click();
    await page.locator('#save-status[data-state="error"]').waitFor();
    assert.equal(requests, 0);
    assert.equal((await (await localGet(page, `/api/works/${work.id}`)).json()).text, '먼저 저장');
  } finally { await context.close(); }
});

test('understanding request explicitly transfers the exact saved revision without claiming design generation', async () => {
  const { page, context } = await pageFor();
  try {
    await page.locator('#work-text').fill('자료를 매주 정리하고 싶어요');
    await ensureModelSelection(page);
    let captured;
    page.on('request', request => { if (request.url().endsWith('/understanding-requests') && request.method() === 'POST') captured = request.postDataJSON(); });
    await page.getByRole('button', { name: '업무 이해하기', exact: true }).click();
    await page.locator('#understanding-record[data-status="succeeded"]').waitFor();
    const work = await savedWork(page);
    assert.equal(captured.revision, work.revision);
    assert.equal(captured.allow_transfer, true);
    assert.match(captured.request_key, /^[0-9a-f-]{36}$/);
    assert.match(await page.locator('#understanding-record').textContent(), /초안/);
    assert.equal(await page.locator('svg, .graph').count(), 0);
    assert.equal(await page.locator('#work-text').inputValue(), work.text);
    assert.doesNotMatch(await page.locator('#understanding-record').textContent(), /생성 완료|설계가 완성|분석 완료/);
  } finally { await context.close(); }
});

test('work switching flushes the current work and blocked storage does not block real persistence', async () => {
  const { page, context } = await pageFor({}, () => {
    Object.defineProperty(window, 'localStorage', { get() { throw new DOMException('blocked', 'SecurityError'); } });
  });
  try {
    await page.locator('#work-text').fill('첫 번째 업무');
    const first = await savedWork(page);
    await page.getByRole('button', { name: '새 업무', exact: true }).click();
    await page.locator('#work-text').fill('두 번째 업무');
    const second = await savedWork(page);
    assert.notEqual(first.id, second.id);
    await page.locator('#work-text').fill('두 번째 업무의 아직 저장 중인 수정');
    await page.locator('#work-select').selectOption(first.id);
    await page.waitForFunction(id => document.querySelector('#app').dataset.workId === id, first.id);
    assert.equal(await page.locator('#work-text').inputValue(), first.text);
    assert.equal((await (await localGet(page, `/api/works/${second.id}`)).json()).text, '두 번째 업무의 아직 저장 중인 수정');
  } finally { await context.close(); }
});

test('first-use page fits Korean mobile and desktop in both schemes with no external requests or script errors', async () => {
  for (const width of [390, 1024, 1440]) for (const colorScheme of ['light', 'dark']) {
    const { page, context, errors, external } = await pageFor({ viewport: { width, height: 900 }, colorScheme });
    try {
      await page.locator('#work-text').fill('자료를 읽고 회의에서 쓸 요약을 만들어 주세요.');
      await savedWork(page);
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `${width} ${colorScheme}: no horizontal overflow`);
      assert.equal(await page.locator('#work-text').evaluate(el => el.getBoundingClientRect().width > 250), true);
      assert.deepEqual(errors, []);
      assert.deepEqual(external, []);
    } finally { await context.close(); }
  }
});
