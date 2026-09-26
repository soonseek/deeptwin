// T023 real-browser evidence on the supported factory: mixed text/file intake, the
// owner's explicit readings (complete / partial / unreadable), the shared conversation
// with referenced records, and approval inside the conversation — an ambiguous answer
// refused with the typed text kept, the exact phrase executing the same work-model
// decision the panel shows. A synthetic Claude catalog/model answer in-process; no
// network, key or paid call; no microphone.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const LOOPBACK_WORDING = /이 컴퓨터에 저장됨|이 컴퓨터의 Codex 로그인과 공유|이 컴퓨터|네이티브 앱|설치 실행기|install launcher|native app/i;

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-work-conversation-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Work conversation fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/work_conversation_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false', DD_TRACE_ENABLED: 'false' } });
  const url = await waitForOwnedChildOutput(server, { pattern: /http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\//, timeoutMs: 20000, label: 'Work conversation fixture' });
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1024, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [], external = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('request', request => { if (!request.url().startsWith(new URL(url).origin)) external.push(request.url()); });
  await page.goto(url);
  const status = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(status, 201);
  // the owner's Claude connection (the settings page's job; set here through the same routes)
  const connected = await page.evaluate(async base => {
    const csrf = (await (await fetch(base + 'session')).json()).csrf_token;
    const post = (path, body) => fetch(base + path, { method: 'POST', body: JSON.stringify(body),
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': csrf } });
    const key = await post('api/v1/connections/claude/key', { secret: 'sk-ant-api03-test-only-never-real' });
    const catalog = await post('api/v1/connections/claude/catalog', {});
    return [key.status, catalog.status];
  }, base);
  assert.deepEqual(connected, [200, 200]);
  await page.goto(url + 'work.html');
  await page.locator('#work-form:not([hidden])').waitFor();
  return { page, url, errors, external };
}

test('mixed intake, explicit readings and an in-conversation approval that refuses ambiguity', { timeout: 90000 }, async t => {
  const { page, errors, external } = await open(t);
  // mixed text and files in one save
  await page.locator('textarea#work-description').fill('분기 보고서 초안을 표 자료로 정리하는 업무');
  await page.getByLabel('원본 자료 선택').setInputFiles([
    { name: '표.txt', mimeType: 'text/plain', buffer: Buffer.from('매출 표 원문 1분기 120') },
    { name: '섞인.txt', mimeType: 'text/plain', buffer: Buffer.concat([Buffer.from('앞부분은 읽힘 '), Buffer.from([0xff, 0xfe]), Buffer.from('뒷부분도 읽힘')]) },
    { name: '그림.png', mimeType: 'image/png', buffer: Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), Buffer.alloc(24)]) },
  ]);
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#save-status')?.textContent.includes('수정본 4')
    && !document.querySelector('#save-status')?.textContent.includes('저장하는 중'));
  // storing read nothing: every original is "not read" until the owner reads it
  const readings = page.locator('#source-readings');
  await page.waitForFunction(() => document.querySelectorAll('#source-readings [data-reading-state="not_read"]').length === 3);
  for (const [name, state, label] of [['표.txt', 'complete', '전부 읽음'], ['섞인.txt', 'partial', '일부만 읽음'],
    ['그림.png', 'unreadable', '읽을 수 없음']]) {
    await readings.getByRole('button', { name: `${name} 내용 읽기`, exact: true }).click();
    await readings.locator(`li[data-reading-state="${state}"]`).filter({ hasText: name }).waitFor();
    assert.match(await readings.locator('li').filter({ hasText: name }).textContent(), new RegExp(label));
  }
  assert.match(await readings.textContent(), /UTF-8이 아닌 바이트/);
  assert.match(await readings.textContent(), /이 형식은 읽을 수 없습니다/);
  // understanding: one explicit model turn over the text and the readings made
  const model = page.locator('#work-model');
  await model.getByRole('button', { name: '작업 모델 만들기', exact: true }).click();
  await model.getByRole('button', { name: '이 작업 모델 수락', exact: true }).waitFor();
  // the conversation: ordinary words are recorded and approve nothing
  const chat = page.locator('#work-conversation');
  await chat.locator('#conversation-input').fill('응');
  await chat.getByLabel('현재 작업 모델').check();
  await chat.getByRole('button', { name: '메시지 남기기', exact: true }).click();
  await chat.locator('li[data-origin="owner_message"]').filter({ hasText: '응' }).waitFor();
  assert.equal(await model.getByRole('button', { name: '이 작업 모델 수락', exact: true }).count(), 1);
  // a referenced-object command, proposed explicitly
  await chat.locator('#conversation-input').fill('이 작업 모델을 확정하자');
  await chat.getByLabel('현재 작업 모델').check();
  await chat.locator('select#conversation-command').selectOption('work_model.confirm');
  await chat.getByRole('button', { name: '메시지 남기기', exact: true }).click();
  const phraseNode = chat.locator('.conversation-phrase');
  await phraseNode.waitFor();
  const phrase = (await phraseNode.textContent()).replace('확인 문구: ', '');
  assert.match(phrase, /^작업 모델 확정 승인 [0-9A-F]{8}$/);
  // an ambiguous answer is refused: nothing decided, the typed text stays
  await chat.locator('#conversation-input').fill('네');
  await chat.getByRole('button', { name: '승인 응답으로 보내기', exact: true }).click();
  await page.locator('#conversation-status[data-state="approval_ambiguous"]').waitFor();
  assert.equal(await chat.locator('#conversation-input').inputValue(), '네');
  assert.equal(await model.getByRole('button', { name: '이 작업 모델 수락', exact: true }).count(), 1);
  // the exact phrase approves; the same decision the panel shows
  await chat.locator('#conversation-input').fill(phrase);
  await chat.getByRole('button', { name: '승인 응답으로 보내기', exact: true }).click();
  await chat.locator('li[data-proposal-state="executed"]').waitFor();
  await model.getByText('이 작업 모델을 수락했습니다.').first().waitFor();
  assert.equal(await model.getByRole('button', { name: '이 작업 모델 수락', exact: true }).count(), 0);
  // after a reload the shared history is the instance's, not this page's
  await page.reload();
  await chat.locator('li[data-origin="approval_response"]').filter({ hasText: phrase }).waitFor();
  assert.equal(await chat.locator('li[data-proposal-state="executed"]').count(), 1);
  assert.equal(await readings.locator('li[data-reading-state="complete"]').count(), 1);
  // product wording: instance-scoped storage, never the loopback prototype's device claims
  const text = await page.locator('body').innerText();
  assert.doesNotMatch(text, LOOPBACK_WORDING);
  assert.match(text, /이 인스턴스/);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
});

test('the owner authors a run budget: exact finite limits, never an API bill on a subscription', { timeout: 60000 }, async t => {
  const { page, url, errors, external } = await open(t);
  await page.goto(url + 'settings.html#settings-budgets');
  const panel = page.locator('#records-budgets');
  await panel.getByText('저장된 실행 한도가 없습니다.').waitFor();
  assert.equal(await panel.locator('.budget-api').isVisible(), false, 'a subscription budget shows no currency field');
  await panel.getByLabel('모델 호출').fill('3');
  await panel.getByRole('button', { name: '실행 한도 저장', exact: true }).click();
  await panel.locator('#budget-status[data-state="saved"]').waitFor();
  await panel.locator('li').filter({ hasText: '구독 연결 · 모델 호출 3' }).waitFor();
  assert.doesNotMatch(await panel.locator('li').first().textContent(), /비용 상한/);
  // an API budget without its currency and cap is refused before anything is sent
  await panel.getByLabel('연결 방식').selectOption('api');
  await panel.getByRole('button', { name: '실행 한도 저장', exact: true }).click();
  await panel.locator('#budget-status[data-state="invalid_input"]').waitFor();
  await panel.getByLabel('통화', { exact: true }).fill('usd');
  await panel.getByLabel('비용 상한(백만분의 1 단위)').fill('2000000');
  await panel.getByRole('button', { name: '실행 한도 저장', exact: true }).click();
  await panel.locator('li').filter({ hasText: '비용 상한 2000000 USD' }).waitFor();
  assert.equal(await panel.locator('li').count(), 2);
  assert.doesNotMatch(await page.locator('body').innerText(), LOOPBACK_WORDING);
  assert.deepEqual(external, []);
  assert.deepEqual(errors, []);
});
