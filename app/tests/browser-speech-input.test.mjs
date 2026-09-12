import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile, writeFile, mkdtemp, rm, mkdir } from 'node:fs/promises';
import vm from 'node:vm';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { saveModelSelection } from './helpers/model-selection.mjs';
import { localContextOptions, localGet, localRouteFetch, mintLaunchURL } from './helpers/local-session.mjs';

let chromium;
const root = fileURLToPath(new URL('../../', import.meta.url));
test.before(async () => {
  assert.ok(process.env.CONTROL_PLAYWRIGHT_MODULE, 'Bundled Playwright is required; microphone tests never skip');
  ({ chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href));
});

function wave({ silence = false, continuous = false } = {}) {
  const rate = 48000, count = rate * 20;
  const result = Buffer.alloc(44 + count * 2);
  result.write('RIFF'); result.writeUInt32LE(result.length - 8, 4); result.write('WAVEfmt ', 8);
  result.writeUInt32LE(16, 16); result.writeUInt16LE(1, 20); result.writeUInt16LE(1, 22);
  result.writeUInt32LE(rate, 24); result.writeUInt32LE(rate * 2, 28); result.writeUInt16LE(2, 32); result.writeUInt16LE(16, 34);
  result.write('data', 36); result.writeUInt32LE(count * 2, 40);
  for (let index = 0; index < count; index++) {
    const voiced = !silence && (continuous || (index >= rate * .3 && index < rate * 3.1));
    result.writeInt16LE(voiced ? Math.round(Math.sin(index / rate * Math.PI * 2 * 440) * 6500) : 0, 44 + index * 2);
  }
  return result;
}

async function open(t, { ready = true, silence = false, continuous = false, delay = .02, width = 1024, deny = false, understandingReady = false, speechInfo = null } = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-speech-ui-'));
  const wav = join(dir, 'synthetic-device.wav'); await writeFile(wav, wave({ silence, continuous }));
  const args = ['app/tests/fixtures/speech_server.py', '--data-dir', dir, '--port', '0', '--delay', String(delay)];
  if (!ready) args.push('--not-ready');
  if (understandingReady) args.push('--understanding-ready');
  const server = spawn(process.env.CONTROL_PYTHON || 'python3', args, { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] });
  t.after(async () => {
    if (server.exitCode === null) await new Promise(resolve => { server.once('exit', resolve); server.kill('SIGTERM'); });
    await rm(dir, { recursive: true, force: true });
  });
  const url = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Speech fixture not ready: ${output}`)), 15000);
    const read = bytes => { output += bytes; const match = output.match(/http:\/\/127\.0\.0\.1:\d+/); if (match) { clearTimeout(timer); resolve(match[0]); } };
    server.stdout.on('data', read); server.stderr.on('data', read);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${output}`)); });
  });
  const browser = await chromium.launch({ channel: 'chrome', headless: true, args: ['--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${wav}`] });
  t.after(() => browser.close());
  const context = await browser.newContext(localContextOptions({ baseURL: url, permissions: ['microphone'], viewport: { width, height: 900 } }));
  await context.addInitScript(({ deny }) => {
    window.testMediaStreams = []; window.testMediaRequests = 0;
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async options => {
      window.testMediaRequests++;
      if (deny) throw new DOMException('fixture permission denied', 'NotAllowedError');
      const stream = await original(options); window.testMediaStreams.push(stream); return stream;
    };
  }, { deny });
  const page = await context.newPage();
  if (speechInfo) await page.route('**/api/speech', route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(speechInfo) }));
  const requests = [], errors = [], external = [];
  page.on('request', request => {
    requests.push({ path: new URL(request.url()).pathname, url: request.url(), method: request.method(), size: request.postDataBuffer()?.length || 0, contentType: request.headers()['content-type'] });
    if (!request.url().startsWith(url + '/')) external.push(request.url());
  });
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(await mintLaunchURL(url)); await page.locator('#app[data-ready="true"]').waitFor();
  page.setDefaultTimeout(12000);
  return { page, context, url, requests, errors, external };
}

async function start(page) {
  await page.getByRole('button', { name: '말로 입력', exact: true }).click();
  await page.locator('#speech-input[data-state="recording"]').waitFor();
}
async function ended(page) {
  assert.equal(await page.evaluate(() => window.testMediaStreams.every(stream => stream.getTracks().every(track => track.readyState === 'ended'))), true);
}

test('audio worklet converts native 16/44.1/48 kHz input to bounded PCM16LE 16 kHz without audible output', async () => {
  let source;
  await assert.doesNotReject(async () => { source = await readFile(new URL('../static/audio-capture-worklet.mjs', import.meta.url), 'utf8'); }, 'the real microphone PCM processor is missing');
  for (const rate of [16000, 44100, 48000]) {
    let Processor;
    const messages = [];
    class Base { constructor() { this.port = { postMessage: value => messages.push(value) }; } }
    vm.runInNewContext(source, { sampleRate: rate, AudioWorkletProcessor: Base, registerProcessor: (name, value) => {
      assert.equal(name, 'deeptwin-pcm16-capture'); Processor = value;
    } });
    const processor = new Processor();
    for (let offset = 0; offset < rate; offset += 128) {
      const input = new Float32Array(Math.min(128, rate - offset)).fill(.125);
      const output = new Float32Array(128);
      assert.equal(processor.process([[input]], [[output]]), true);
      assert.ok(output.every(value => value === 0), 'microphone audio must never feed back to speakers');
    }
    assert.equal(messages.length, 50, `${rate}: exactly 16,000 output samples in 20ms frames`);
    for (const message of messages) {
      assert.equal(message.pcm.byteLength, 640);
      assert.ok(message.rms > .12 && message.rms < .13);
      assert.equal(new DataView(message.pcm).getInt16(0, true), 4096);
    }
  }
});

test('speech is opt-in and an unprepared engine never asks for microphone access or creates a work', async t => {
  const { page, requests } = await open(t, { ready: false });
  assert.equal(await page.locator('#speech-input').count(), 1);
  await page.locator('#speech-input[data-ready="false"]').waitFor();
  assert.equal(await page.getByRole('button', { name: '말로 입력', exact: true }).isDisabled(), true);
  await page.waitForTimeout(400);
  assert.equal(await page.evaluate(() => window.testMediaRequests), 0);
  assert.deepEqual(await (await localGet(page, '/api/works')).json(), []);
  assert.equal(requests.filter(item => item.method === 'POST' && item.path !== '/api/session/bootstrap').length, 0);
});

test('a ready flag from a non-local speech identity stays fail-closed before microphone access', async t => {
  const { page } = await open(t, { speechInfo: { ready: true, engine: 'remote', model: 'base', language: 'ko', message: 'wrong identity' } });
  await page.locator('#speech-input[data-ready="false"]').waitFor();
  assert.equal(await page.getByRole('button', { name: '말로 입력', exact: true }).isDisabled(), true);
  assert.equal(await page.evaluate(() => window.testMediaRequests), 0);
});

test('ready copy distinguishes browser microphone capture from instance-owned transcription', async t => {
  const { page } = await open(t);
  await page.locator('#speech-input[data-ready="true"]').waitFor();
  const copy = await page.locator('#speech-status').textContent();
  assert.match(copy, /브라우저.*마이크/);
  assert.match(copy, /DeepTwin 인스턴스.*글로 바꿉니다/);
  assert.doesNotMatch(copy, /이 컴퓨터/);
});

test('native keyboard controls and text states expose recording and stop without color dependence', async t => {
  const { page } = await open(t, { silence: true });
  const toggle = page.getByRole('button', { name: '말로 입력', exact: true });
  assert.equal(await page.locator('#speech-status').getAttribute('role'), 'status');
  assert.equal(await page.locator('#speech-provisional').getAttribute('aria-live'), 'polite');
  await toggle.focus();
  await toggle.press('Enter');
  await page.locator('#speech-input[data-state="recording"]').waitFor();
  assert.equal(await page.getByRole('button', { name: '음성 입력 중지', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.getByRole('button', { name: '음성 입력 취소', exact: true }).isVisible(), true);
  assert.match(await page.locator('#speech-status').textContent(), /듣고 있습니다/);
  const stop = page.getByRole('button', { name: '음성 입력 중지', exact: true });
  await stop.focus();
  await stop.press('Space');
  await page.locator('#speech-input[data-state="idle"]').waitFor();
  assert.equal(await page.getByRole('button', { name: '말로 입력', exact: true }).getAttribute('aria-pressed'), 'false');
  await ended(page);
});

test('real fake-device audio flows through worklet PCM and final text is inserted only once, with immediate microphone stop', async t => {
  const { page, requests, errors, external } = await open(t);
  await start(page);
  assert.equal(await page.locator('#work-select option:checked').textContent(), '작성 중인 업무');
  await page.waitForFunction(() => document.querySelector('#speech-provisional').textContent.includes('음성으로 더한 말'));
  assert.equal(await page.locator('#work-text').inputValue(), '', 'interim text is not committed');
  await page.waitForFunction(() => document.querySelector('#work-text').value.includes('음성으로 더한 말'));
  const out = join(root, 'app/review-output'); await mkdir(out, { recursive: true });
  await page.screenshot({ path: join(out, 'speech-input-1024-light.png') });
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: join(out, 'speech-input-1024-dark.png') });
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click();
  await ended(page);
  await page.locator('#speech-input[data-state="idle"]').waitFor();
  assert.equal((await page.locator('#work-text').inputValue()).match(/음성으로 더한 말/g).length, 1);
  const chunks = requests.filter(item => item.path.endsWith('/chunks'));
  assert.ok(chunks.some(item => new URL(item.url).searchParams.get('final') === 'true'));
  assert.ok(chunks.every(item => item.size >= 8000 && item.size <= 256000 && item.size % 2 === 0 && item.contentType === 'audio/pcm'));
  assert.equal(requests.filter(item => item.path.endsWith('/close')).length, 1);
  assert.equal(requests.filter(item => item.path.endsWith('/understanding-requests') && item.method === 'POST').length, 0);
  assert.deepEqual(errors, []); assert.deepEqual(external, []);
});

test('silence creates no transcription request and permission failure keeps the original input', async t => {
  const { page, requests } = await open(t, { silence: true });
  await start(page); await page.waitForTimeout(2500);
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click();
  await page.locator('#speech-input[data-state="idle"]').waitFor();
  assert.equal(requests.filter(item => item.path.endsWith('/chunks')).length, 0); await ended(page);
  const denied = await open(t, { deny: true });
  await denied.page.locator('#work-text').fill('권한을 거절해도 남길 글');
  await denied.page.getByRole('button', { name: '말로 입력', exact: true }).click();
  await denied.page.locator('#speech-input[data-state="error"]').waitFor();
  assert.equal(await denied.page.locator('#work-text').inputValue(), '권한을 거절해도 남길 글');
  assert.match(await denied.page.locator('#speech-status').textContent(), /마이크.*권한/);
});

test('typing and Korean composition while dictating are preserved before final text is inserted at the current cursor', async t => {
  const { page } = await open(t);
  await page.locator('#work-text').fill('기존 글'); await start(page);
  await page.waitForFunction(() => document.querySelector('#speech-provisional').textContent.length > 0);
  await page.locator('#work-text').evaluate(el => {
    el.focus(); el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true }));
    el.value = '직접 쓰는 한글ㅈ'; el.setSelectionRange(el.value.length, el.value.length);
    el.dispatchEvent(new InputEvent('input', { bubbles: true, isComposing: true }));
  });
  await page.waitForTimeout(1800);
  assert.equal(await page.locator('#work-text').inputValue(), '직접 쓰는 한글ㅈ');
  await page.locator('#work-text').evaluate(el => {
    el.value = '직접 쓴 한글'; el.setSelectionRange(el.value.length, el.value.length);
    el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true }));
    el.dispatchEvent(new InputEvent('input', { bubbles: true }));
  });
  await page.waitForFunction(() => document.querySelector('#work-text').value === '직접 쓴 한글 음성으로 더한 말');
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click(); await ended(page);
});

test('cancel and work switching stop tracks and discard delayed transcription without removing confirmed text', async t => {
  for (const leave of ['cancel', 'switch', 'hidden']) {
    const { page, requests } = await open(t, { delay: 5 });
    await page.locator('#work-text').fill('기존 확정 글'); await start(page);
    await page.waitForRequest(request => new URL(request.url()).pathname.endsWith('/chunks'));
    if (leave === 'cancel') await page.getByRole('button', { name: '음성 입력 취소', exact: true }).click();
    if (leave === 'switch') await page.locator('#new-work').click();
    if (leave === 'hidden') await page.evaluate(() => {
      Object.defineProperty(document, 'hidden', { configurable: true, get: () => true }); document.dispatchEvent(new Event('visibilitychange'));
    });
    await ended(page); await page.waitForTimeout(500);
    assert.equal(await page.locator('#work-text').inputValue(), leave === 'switch' ? '' : '기존 확정 글');
    assert.equal(requests.filter(item => item.path.endsWith('/close')).length, 1);
  }
});

test('long speech is segmented within byte limits and slow inference cannot create an unbounded request queue', async t => {
  const { page, requests } = await open(t, { continuous: true, delay: 20, width: 390 });
  await start(page);
  await page.waitForTimeout(13200);
  const chunks = requests.filter(item => item.path.endsWith('/chunks'));
  assert.ok(chunks.length <= 3, 'only one in-flight request, never a timer-driven request fan-out');
  assert.ok(chunks.every(item => item.size <= 256000));
  assert.equal(await page.locator('#speech-input').getAttribute('data-state'), 'finishing', 'two waiting final windows stop capture rather than accumulating more audio');
  await ended(page);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  const out = join(root, 'app/review-output'); await mkdir(out, { recursive: true });
  await page.screenshot({ path: join(out, 'speech-input-390.png') });
  await page.emulateMedia({ colorScheme: 'dark' });
  await page.screenshot({ path: join(out, 'speech-input-390-dark.png') });
  await page.getByRole('button', { name: '음성 입력 취소', exact: true }).click(); await ended(page);
});

test('stop during an unfinished utterance shuts down tracks first and commits its last final result once', async t => {
  const { page, requests } = await open(t, { continuous: true, delay: 1 });
  await start(page);
  await page.waitForFunction(() => document.querySelector('#speech-provisional').textContent.length > 0);
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click();
  await ended(page);
  assert.equal(await page.locator('#work-text').inputValue(), '');
  await page.locator('#speech-input[data-state="idle"]').waitFor();
  assert.equal(await page.locator('#work-text').inputValue(), '음성으로 더한 말');
  assert.equal(requests.filter(item => item.path.endsWith('/chunks') && new URL(item.url).searchParams.get('final') === 'true').length, 1);
});

test('another window cannot start a simultaneous speech session and keeps its existing input', async t => {
  const { page, context, url } = await open(t, { silence: true });
  await page.locator('#work-text').fill('두 창에서 남길 글');
  await start(page);
  const second = await context.newPage();
  await second.goto(url); await second.locator('#app[data-ready="true"]').waitFor();
  await second.getByRole('button', { name: '말로 입력', exact: true }).click();
  await second.locator('#speech-input[data-state="error"]').waitFor();
  assert.equal(await second.locator('#work-text').inputValue(), '두 창에서 남길 글');
  assert.match(await second.locator('#speech-status').textContent(), /다른 음성 입력|앞선 음성/);
  await ended(second);
  assert.equal(await page.locator('#speech-input').getAttribute('data-state'), 'recording');
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click(); await ended(page);
});

test('an instance transcriber failure is not misreported as another window using the microphone', async t => {
  const { page } = await open(t);
  await page.route('**/api/speech/sessions/*/chunks?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: '인스턴스의 음성 입력 기능을 사용할 수 없습니다.' }) }));
  await start(page);
  await page.locator('#speech-input[data-state="error"]').waitFor();
  await ended(page);
  assert.match(await page.locator('#speech-status').textContent(), /인스턴스의 음성 입력 기능/);
  assert.doesNotMatch(await page.locator('#speech-status').textContent(), /다른 음성 입력/);
});

test('a transcription response with a non-local engine identity never inserts text', async t => {
  const { page } = await open(t);
  await page.route('**/api/speech/sessions/*/chunks?*', async route => {
    const response = await localRouteFetch(route);
    const result = await response.json();
    await route.fulfill({ response, body: JSON.stringify({ ...result, engine: 'remote' }) });
  });
  await start(page);
  await page.locator('#speech-input[data-state="error"]').waitFor();
  await ended(page);
  assert.equal(await page.locator('#work-text').inputValue(), '');
  assert.match(await page.locator('#speech-status').textContent(), /응답을 확인하지 못/);
});

test('failure cleanup is awaited so immediate retry keeps text and opens a fresh session', async t => {
  const { page } = await open(t);
  let first = true;
  await page.route('**/api/speech/sessions/*/chunks?*', async route => {
    if (first) {
      first = false;
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'controlled local failure' }) });
    } else await route.continue();
  });
  await page.route('**/api/speech/sessions/*/close', async route => {
    await new Promise(resolve => setTimeout(resolve, 1200));
    await route.continue();
  });
  await page.locator('#work-text').fill('실패 전 직접 쓴 글');
  await start(page);
  await page.locator('#speech-input[data-state="error"]').waitFor();
  await page.getByRole('button', { name: '말로 입력', exact: true }).click();
  await page.locator('#speech-input[data-state="recording"]').waitFor();
  assert.equal(await page.locator('#work-text').inputValue(), '실패 전 직접 쓴 글');
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click();
  await ended(page);
});

test('typing while the created session response is delayed does not finish or abandon microphone startup', async t => {
  const { page } = await open(t, { silence: true });
  let release, created;
  const held = new Promise(resolve => { release = resolve; });
  const serverCreated = new Promise(resolve => { created = resolve; });
  await page.route('**/api/speech/sessions', async route => {
    const response = await localRouteFetch(route);
    created(); await held; await route.fulfill({ response });
  });
  try {
    await page.getByRole('button', { name: '말로 입력', exact: true }).click();
    await serverCreated;
    await page.locator('#work-text').fill('마이크를 준비하는 동안 쓴 글');
    await page.waitForTimeout(100);
    assert.equal(await page.locator('#speech-input').getAttribute('data-state'), 'starting');
    release();
    await page.locator('#speech-input[data-state="recording"]').waitFor();
    assert.equal(await page.locator('#work-text').inputValue(), '마이크를 준비하는 동안 쓴 글');
    await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click(); await ended(page);
  } finally { release(); }
});

test('microphone stop preserves an unconfirmed server-close warning instead of claiming completion', async t => {
  const { page } = await open(t, { silence: true });
  await start(page);
  await page.route('**/api/speech/sessions/*/close', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'controlled close failure' }) }));
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click();
  await ended(page);
  await page.locator('#speech-input[data-state="idle"]').waitFor();
  assert.match(await page.locator('#speech-status').textContent(), /서버.*종료.*확인하지 못/);
  assert.doesNotMatch(await page.locator('#speech-status').textContent(), /마쳤습니다/);
});

test('final speech waiting on a real revision snapshot freeze is inserted as soon as save completes without another keystroke', async t => {
  const { page } = await open(t, { understandingReady: true });
  await page.locator('#work-text').fill('원래 업무');
  await saveModelSelection(page);
  await start(page);
  await page.waitForFunction(() => document.querySelector('#speech-provisional').textContent.length > 0);
  await page.route('**/api/works/*', async route => {
    if (route.request().method() === 'PUT') await new Promise(resolve => setTimeout(resolve, 2500));
    await route.continue();
  });
  await page.locator('#work-text').fill('직접 바꾼 업무');
  await page.locator('#prepare-design').click();
  await page.waitForFunction(() => document.querySelector('#work-text').readOnly);
  await page.waitForTimeout(1800);
  assert.equal(await page.locator('#work-text').inputValue(), '직접 바꾼 업무');
  await page.waitForFunction(() => !document.querySelector('#work-text').readOnly);
  await page.waitForFunction(() => document.querySelector('#work-text').value === '직접 바꾼 업무 음성으로 더한 말', null, { timeout: 3000 });
  await page.getByRole('button', { name: '음성 입력 중지', exact: true }).click();
  await ended(page);
});
