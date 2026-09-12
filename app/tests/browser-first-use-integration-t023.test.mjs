import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';

import { ensureModelSelection } from './helpers/model-selection.mjs';
import { localContextOptions, localGet, mintLaunchURL } from './helpers/local-session.mjs';

let browser;
const root = fileURLToPath(new URL('../../', import.meta.url));

test.before(async () => {
  assert.ok(process.env.CONTROL_PLAYWRIGHT_MODULE, 'Bundled Playwright is required; no skipped browser cases');
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
});
test.after(async () => browser?.close());

async function open(t, {
  width = 1024,
  colorScheme = 'light',
  reducedMotion = 'no-preference',
  understandingReady = false,
} = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-t023-ui-'));
  const fixtureArguments = ['app/tests/fixtures/understanding_server.py', '--data-dir', dir, '--port', '0'];
  if (!understandingReady) fixtureArguments.push('--not-ready');
  const server = spawn(
    process.env.CONTROL_PYTHON || 'python3',
    fixtureArguments,
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'] },
  );
  t.after(async () => {
    if (server.exitCode === null) await new Promise(resolve => {
      server.once('exit', resolve);
      server.kill('SIGTERM');
    });
    await rm(dir, { recursive: true, force: true });
  });
  const url = await new Promise((resolve, reject) => {
    let output = '';
    const timer = setTimeout(() => reject(new Error(`Fixture not ready: ${output}`)), 15_000);
    const read = bytes => {
      output += bytes;
      const match = output.match(/http:\/\/127\.0\.0\.1:\d+/);
      if (match) { clearTimeout(timer); resolve(match[0]); }
    };
    server.stdout.on('data', read);
    server.stderr.on('data', read);
    server.once('error', error => { clearTimeout(timer); reject(error); });
    server.once('exit', code => { clearTimeout(timer); reject(new Error(`Fixture exited ${code}: ${output}`)); });
  });
  const context = await browser.newContext(localContextOptions({
    baseURL: url, viewport: { width, height: 900 }, colorScheme, reducedMotion,
  }));
  t.after(() => context.close());
  const page = await context.newPage();
  const requests = [];
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  page.on('request', request => requests.push({
    method: request.method(), url: request.url(), body: request.postData(),
  }));
  await page.goto(await mintLaunchURL(url));
  page.setDefaultTimeout(6_000);
  try { await page.locator('#app[data-ready="true"]').waitFor(); }
  catch (error) {
    const state = await page.locator('body').evaluate(body => ({
      text: body.innerText, ready: document.querySelector('#app')?.dataset.ready,
    }));
    throw new Error(`${error.message}\npage errors: ${pageErrors.join(' | ')}\nstate: ${JSON.stringify(state)}`);
  }
  return { page, context, url, requests, pageErrors };
}

test('blank workspace keeps intake primary and every setup surface subordinate', async t => {
  const { page } = await open(t, { width: 1440 });
  assert.equal(await page.locator('#work-stage').getAttribute('data-view'), 'intake');
  assert.equal(await page.locator('#understanding-panel').isHidden(), true);
  assert.equal(await page.locator('#provider-panel').isHidden(), true);
  assert.equal(await page.locator('#model-settings').evaluate(element => element.open), false);
  assert.equal(await page.locator('#transfer-preview').evaluate(element => element.open), false);
  assert.equal(await page.locator('#work-files').evaluate(element => element.closest('.work-surface') !== null), true);
  assert.equal(await page.locator('#speech-toggle').evaluate(element => element.closest('.work-surface') !== null), true);
  const intake = await page.locator('.work-surface').boundingBox();
  const setup = await page.locator('.understanding-start').boundingBox();
  assert.ok(intake && setup && intake.y < setup.y, 'description and source intake precede model/setup controls');
  assert.equal(await page.locator('svg, .graph, [role="progressbar"]').count(), 0);
  assert.doesNotMatch(await page.locator('main').textContent(), /철학|렌즈|3개 안|3가지 안/);
});

test('one work surface expands into original-and-understanding comparison without a fake graph', async t => {
  const { page, pageErrors } = await open(t, { width: 1440, understandingReady: true });
  await save(page, '여러 자료를 읽고 회의에서 쓸 PDF 요약을 만들어 주세요.');
  await ensureModelSelection(page);
  await page.locator('#usage-limits > summary').click();
  await page.locator('#transfer-preview > summary').click();
  assert.equal(await page.locator('#model-settings').evaluate(element => element.open), true);
  assert.equal(await page.locator('#usage-limits').evaluate(element => element.open), true);
  assert.equal(await page.locator('#transfer-preview').evaluate(element => element.open), true);
  await page.locator('#prepare-design').click();
  await page.locator('#understanding-record[data-status="succeeded"]').waitFor();

  assert.equal(await page.locator('#work-stage').getAttribute('data-view'), 'understanding');
  assert.equal(await page.locator('#app').getAttribute('data-workspace-view'), 'understanding');
  assert.equal(await page.locator('#understanding-title').textContent(), 'DeepTwin이 이해한 업무');
  assert.equal(await page.locator('#work-text').inputValue(), '여러 자료를 읽고 회의에서 쓸 PDF 요약을 만들어 주세요.');
  assert.match(await page.locator('#understanding-record').textContent(), /업무 이해 초안/);
  assert.doesNotMatch(await page.locator('#understanding-record').textContent(), /환경 생성 완료|설계 완료|그래프 생성 완료/);
  assert.equal(await page.locator('svg, .graph, [role="progressbar"]').count(), 0);
  assert.equal(await page.locator('#model-settings').evaluate(element => element.open), false, 'first understanding transition collapses model setup');
  assert.equal(await page.locator('#usage-limits').evaluate(element => element.open), false, 'first understanding transition collapses nested request limits');
  assert.equal(await page.locator('#transfer-preview').evaluate(element => element.open), false, 'first understanding transition collapses transfer details');

  await page.locator('#model-settings > summary').click();
  assert.equal(await page.locator('#usage-limits').evaluate(element => element.open), false, 'reopening model setup does not resurrect nested admin detail');
  await page.locator('#usage-limits > summary').click();
  await page.locator('#transfer-preview > summary').click();
  await page.locator('#understanding-history').dispatchEvent('change');
  assert.equal(await page.locator('#model-settings').evaluate(element => element.open), true, 'a manually reopened setting survives understanding rerenders');
  assert.equal(await page.locator('#usage-limits').evaluate(element => element.open), true, 'a later explicit limits reopen survives understanding rerenders');
  assert.equal(await page.locator('#transfer-preview').evaluate(element => element.open), true, 'a manually reopened transfer preview survives understanding rerenders');

  for (const width of [1440, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    const original = await page.locator('.work-input-pane').boundingBox();
    const understood = await page.locator('#understanding-panel').boundingBox();
    assert.ok(original && understood && original.x + original.width <= understood.x, `${width}px keeps the two real views side by side`);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  }
  await page.setViewportSize({ width: 390, height: 900 });
  const original = await page.locator('.work-input-pane').boundingBox();
  const understood = await page.locator('#understanding-panel').boundingBox();
  assert.ok(original && understood && original.y + original.height <= understood.y, '390px stacks the same two views without replacing either');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(pageErrors, []);
});

test('dark and reduced-motion preferences keep the first action intact without external assets', async t => {
  const { page, requests, pageErrors } = await open(t, { width: 390, colorScheme: 'dark', reducedMotion: 'reduce' });
  assert.equal(await page.evaluate(() => matchMedia('(prefers-color-scheme: dark)').matches), true);
  assert.equal(await page.evaluate(() => matchMedia('(prefers-reduced-motion: reduce)').matches), true);
  assert.equal(await page.locator('#work-text').isVisible(), true);
  assert.equal(await page.locator('#model-settings').evaluate(element => element.open), false);
  const duration = await page.locator('#work-stage').evaluate(element => getComputedStyle(element).transitionDuration);
  assert.ok(duration === '0s' || Number.parseFloat(duration) <= .001, `reduced transition duration: ${duration}`);
  assert.equal(requests.some(request => !request.url.startsWith(page.url().split('/').slice(0, 3).join('/'))), false);
  assert.deepEqual(pageErrors, []);
});

async function save(page, text) {
  await page.locator('#work-text').fill(text);
  await page.locator('#save-status[data-state="saved"]').waitFor();
  const id = await page.locator('#app').getAttribute('data-work-id');
  return (await localGet(page, `/api/works/${id}`)).json();
}

function catalog(provider, mode, { thinking = false } = {}) {
  const model = `${provider}-${mode}-fixture`;
  return {
    provider, mode, status: 'ready', message: `${provider} ${mode} fixture`,
    catalog_id: `catalog-${provider}-${mode}`, models: [{
      model, display_name: model, default_reasoning_effort: 'medium',
      reasoning_efforts: [{ value: 'medium', label: '중간' }], is_default: true,
      raw_capability_claims: thinking ? {
        thinking: { supported: true, types: { adaptive: { supported: true } } },
      } : {},
    }],
  };
}

test('actual provider modes drive exact catalog URLs while only the production understanding path becomes runnable', async t => {
  const { page, requests } = await open(t, { understandingReady: true });
  await save(page, '연결 모드를 분리해서 쓰는 업무');
  assert.equal(await page.locator('#prepare-design').textContent(), '업무 이해하기');
  await page.locator('#model-settings > summary').click();
  const connection = page.locator('#model-connection');
  assert.deepEqual(await connection.locator('option').evaluateAll(options => options.map(option => [option.value, option.textContent])), [
    ['codex:subscription', 'Codex · ChatGPT 구독'],
    ['claude:api', 'Claude · Claude API'],
    ['codex:api', 'Codex · 별도 API'],
  ]);
  assert.equal(await connection.locator('option[value="claude:subscription"]').count(), 0);

  await page.route('**/api/model-catalogs/claude?mode=api', route => route.fulfill({ json: catalog('claude', 'api', { thinking: true }) }));
  await connection.selectOption('claude:api');
  await page.locator('#model-settings[data-catalog-status="ready"]').waitFor();
  assert.match(requests.at(-1).url, /\/api\/model-catalogs\/claude\?mode=api$/);
  assert.equal(await page.locator('#model-thinking').isEnabled(), true);
  await page.locator('#model-thinking').selectOption('adaptive');

  let saved;
  await page.route('**/api/works/*/model-selection', async route => {
    if (route.request().method() !== 'PUT') return route.continue();
    const payload = route.request().postDataJSON();
    saved = payload;
    await route.fulfill({ json: { version: 1, selection: {
      ...payload.selection, display_name: payload.selection.model,
    } } });
  });
  await page.locator('#save-model-selection').click();
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  assert.equal(await page.locator('#prepare-design').textContent(), '업무 이해하기', 'Claude API does not brand DeepTwin’s product action');
  assert.equal(await page.locator('#prepare-design').isDisabled(), true, 'Claude API selection does not imply an implemented understanding executor');
  assert.match(await page.locator('#understanding-readiness').textContent(), /Claude API.*저장.*실행 경로.*연결되지.*보내지/s);
  await page.locator('#prepare-design').dispatchEvent('click');
  await page.waitForTimeout(100);
  assert.equal(requests.filter(item => item.method === 'POST' && item.url.endsWith('/understanding-requests')).length, 0);
  assert.equal(await page.locator('#model-thinking').inputValue(), 'adaptive');
  assert.equal(saved.selection.provider, 'claude');
  assert.equal(saved.selection.mode, 'api');
  assert.equal(saved.selection.thinking, 'adaptive');
  assert.match(await page.locator('#model-billing-note').textContent(), /API.*구독.*따로|구독.*API.*따로/);

  await page.route('**/api/model-catalogs/codex?mode=api', route => route.fulfill({ json: catalog('codex', 'api') }));
  await connection.selectOption('codex:api');
  await page.locator('#model-settings[data-catalog-status="ready"]').waitFor();
  await page.locator('#save-model-selection').click();
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  assert.equal(await page.locator('#prepare-design').textContent(), '업무 이해하기', 'Codex API does not brand DeepTwin’s product action');
  assert.equal(await page.locator('#prepare-design').isDisabled(), true, 'Codex API selection does not imply an implemented understanding executor');
  assert.match(await page.locator('#understanding-readiness').textContent(), /Codex API.*저장.*실행 경로.*연결되지.*보내지/s);
  await page.locator('#prepare-design').dispatchEvent('click');
  await page.waitForTimeout(100);
  assert.equal(requests.filter(item => item.method === 'POST' && item.url.endsWith('/understanding-requests')).length, 0);

  await page.route('**/api/model-catalogs/codex?mode=subscription', route => route.fulfill({ json: catalog('codex', 'subscription') }));
  await connection.selectOption('codex:subscription');
  await page.locator('#model-settings[data-catalog-status="ready"]').waitFor();
  await page.locator('#save-model-selection').click();
  await page.locator('#model-selection-status[data-state="saved"]').waitFor();
  assert.equal(await page.locator('#prepare-design').textContent(), '업무 이해하기', 'Codex subscription does not brand DeepTwin’s product action');
  assert.equal(await page.locator('#prepare-design').isEnabled(), true, 'only the implemented Codex subscription understanding path is runnable');
  assert.match(await page.locator('#understanding-readiness').textContent(), /Codex ChatGPT 구독.*업무 이해 초안.*구독 사용량/s);
});

test('Claude API key is submitted only by explicit action and cleared from the page', async t => {
  const { page, requests } = await open(t);
  const secret = 'sk-ant-api03-browser-explicit-canary';
  await page.locator('#open-connections').click();
  assert.equal(await page.locator('#provider-title').getAttribute('tabindex'), '-1');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'provider-title', 'opening connections moves keyboard focus to the revealed panel');
  const card = page.locator('.api-key-connection[data-provider="claude"]');
  await card.locator('[data-state="not_configured"], .connection-state').first().waitFor();
  assert.equal(requests.some(request => request.body?.includes(secret)), false);

  await card.locator('input[name="api-key"]').fill(secret);
  assert.equal(requests.some(request => request.body?.includes(secret)), false);
  await card.getByRole('button', { name: 'API 키 연결', exact: true }).click();
  try {
    await page.locator('.api-key-connection[data-provider="claude"][data-state="configured"]').waitFor();
  } catch (error) {
    throw new Error(`${error.message}\nconnection message: ${await page.locator('#connection-message').textContent()}\ncard: ${await page.locator('.api-key-connection[data-provider="claude"]').textContent()}`);
  }
  assert.equal(await page.locator('.api-key-connection[data-provider="claude"] input[name="api-key"]').inputValue(), '');
  assert.equal((await page.locator('body').textContent()).includes(secret), false);
  assert.equal(JSON.stringify(await page.evaluate(() => Object.fromEntries(Object.entries(localStorage)))).includes(secret), false);

  await page.reload();
  await page.locator('#app[data-ready="true"]').waitFor();
  await page.locator('#open-connections').click();
  await page.locator('.api-key-connection[data-provider="claude"][data-state="configured"]').waitFor();
  assert.equal(await page.locator('.api-key-connection[data-provider="claude"] input[name="api-key"]').inputValue(), '');
});

test('finite limits stay subordinate and API money fields are required only for API mode', async t => {
  const { page } = await open(t);
  await page.locator('#model-settings > summary').click();
  await page.locator('#usage-limits > summary').click();
  assert.equal(await page.locator('#usage-api-fields').isHidden(), true);
  assert.match(await page.locator('#usage-status').textContent(), /로컬 초안|저장되지|적용되지/);
  assert.match(await page.locator('#usage-status').textContent(), /구독.*금액.*표시하지/);

  await page.locator('#model-connection').selectOption('codex:api');
  assert.equal(await page.locator('#usage-api-fields').isVisible(), true);
  assert.equal(await page.locator('#usage-api-cap').getAttribute('required'), '');
  assert.match(await page.locator('#usage-status').textContent(), /통화.*비용 한도|비용 한도.*통화/);
  await page.locator('#usage-api-cap').fill('5');
  assert.match(await page.locator('#usage-status').textContent(), /API.*5.*USD.*초안|USD.*5.*API.*초안/);
  assert.equal(await page.locator('#usage-limits').evaluate(details => details.closest('.understanding-start') !== null), true);
});

test('ordinary same-work chat is inert, retains failed drafts, and isolates work drafts', async t => {
  const { page } = await open(t);
  const first = await save(page, '첫 업무');
  const chat = page.locator('#work-chat');
  await chat.waitFor({ state: 'visible' });
  assert.equal(await page.locator('#work-memo').evaluate(details => details.open), false);
  assert.equal(await page.locator('#work-chat-title').textContent(), '업무 메모 · 현재 업무 이해 요청에는 포함되지 않음');
  assert.match(await chat.textContent(), /원문.*직접 수정|직접 수정.*원문/);
  assert.doesNotMatch(await chat.textContent(), /피드백|feedback/i);
  await page.locator('#work-chat-title').click();

  await page.locator('#chat-draft').fill('응');
  await page.locator('#chat-send').click();
  await page.locator('#chat-messages [data-sequence="1"]').waitFor();
  assert.equal(await page.locator('#chat-messages [data-sequence="1"] p').nth(1).textContent(), '응');
  const commands = await localGet(page, `/api/v1/works/${first.id}/conversation-commands`);
  assert.deepEqual((await commands.json()).commands, []);

  await page.route(`**/api/v1/works/${first.id}/messages`, route => {
    if (route.request().method() === 'POST') return route.abort();
    return route.continue();
  });
  await page.locator('#chat-draft').fill('실패해도 남아야 하는 첫 업무 초안');
  await page.locator('#chat-send').click();
  await page.locator('#chat-status[data-state="error"]').waitFor();
  assert.equal(await page.locator('#chat-draft').inputValue(), '실패해도 남아야 하는 첫 업무 초안');
  await page.unroute(`**/api/v1/works/${first.id}/messages`);

  await page.locator('#new-work').click();
  const second = await save(page, '두 번째 업무');
  await page.locator('#chat-draft').fill('두 번째 업무만의 초안');
  await page.locator('#work-select').selectOption(first.id);
  await page.locator('#chat-panel[data-work-id="' + first.id + '"]').waitFor();
  assert.equal(await page.locator('#chat-draft').inputValue(), '실패해도 남아야 하는 첫 업무 초안');
  await page.locator('#work-select').selectOption(second.id);
  await page.locator('#chat-panel[data-work-id="' + second.id + '"]').waitFor();
  assert.equal(await page.locator('#chat-draft').inputValue(), '두 번째 업무만의 초안');
});

test('390px and keyboard keep description first while chat and settings remain reachable', async t => {
  const { page } = await open(t, { width: 390 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.equal(await page.locator('main > h1').textContent(), '어떤 일을 맡기고 싶으세요?');
  await page.locator('#work-text').focus();
  const workFocus = await page.locator('#work-text').evaluate(element => {
    const style = getComputedStyle(element);
    return { width: style.outlineWidth, style: style.outlineStyle };
  });
  assert.deepEqual(workFocus, { width: '3px', style: 'solid' });
  await page.locator('#work-text').pressSequentially('키보드로 맡기는 업무');
  await page.locator('#save-status[data-state="saved"]').waitFor();
  await page.locator('#work-chat-title').click();
  await page.locator('#chat-draft').focus();
  await page.locator('#chat-draft').pressSequentially('덧붙일 말');
  await page.locator('#chat-draft').press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'chat-send');
  await page.locator('#model-settings > summary').focus();
  await page.locator('#model-settings > summary').press('Enter');
  assert.equal(await page.locator('#model-settings').evaluate(details => details.open), true);
  assert.equal(await page.locator('#model-connection').isVisible(), true);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
});
