// T090 credentials panel in a real browser against the real supported server
// (`app/tests/fixtures/credentials_server.py`): the records page's panel over the
// credentials-v1 routes, the control-plane ledger and the frame-only client talking
// authenticated frames to an encrypted gateway vault. The fixture's fence delay is a few
// seconds (test only; production stays 300 s) and two synthetic secret prefixes script a
// gateway that commits without replying and a store that is never admitted, so both
// produce an unconfirmed act. The page shows each binding head (state, revision,
// catalog/model presence), each pending act with its fence time, offers the fence only
// once due, and reports its outcome; a second create is refused `connection_bound`;
// the owner's explicit catalog refresh reads the model list through the gateway's
// provider-send path (a loopback mock provider in the fixture) for the current binding
// revision only, and a model is chosen from it; a rotation voids both until the next
// refresh; delete says the provider key is not revoked. No secret reaches the DOM, browser storage,
// any response or any file on disk. The owner is a scripted test actor: synthetic
// evidence of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readdir, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';
import {
  CATALOG_RESULTS, CONNECTION_MESSAGES, CONNECTION_STATES, CREDENTIAL_ERRORS, CREDENTIAL_MESSAGES, FENCE_RESULTS, PENDING_MESSAGES,
} from '../static/account.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /CREDENTIALS_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const FENCE_DELAY_SECONDS = 3;
const SECRETS = {
  first: 'sk-synthetic-browser-first-7c1e0001',
  second: 'sk-synthetic-browser-second-7c1e0002',
  noReply: 'sk-fixture-noreply-browser-7c1e0003',
  unadmitted: 'sk-fixture-unadmitted-browser-7c1e0004',
  third: 'sk-synthetic-browser-third-7c1e0005',
};

async function filesHolding(dir, needles) {
  const found = [];
  for (const entry of await readdir(dir, { withFileTypes: true, recursive: true })) {
    if (!entry.isFile()) continue;
    const path = join(entry.parentPath ?? entry.path, entry.name);
    const data = await readFile(path);
    for (const needle of needles) if (data.includes(Buffer.from(needle))) found.push(path);
  }
  return found;
}

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-credentials-'));
  let server, browser;
  let output = '';
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: async () => {
    // after the server stopped: no synthetic secret in cleartext in any file it owned or in its output
    const leaks = await filesHolding(dir, Object.values(SECRETS));
    await rm(dir, { recursive: true, force: true });
    if (leaks.length) throw new Error(`secret on disk: ${leaks.join(', ')}`);
    for (const secret of Object.values(SECRETS)) if (output.includes(secret)) throw new Error('secret in server output');
  } }, { serverGraceMs: 5000, serverForceMs: 2000, label: 'Credentials fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/credentials_server.py', '--owned-dir', dir,
    '--fence-delay-seconds', String(FENCE_DELAY_SECONDS)],
  { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 30000, label: 'Credentials fixture' });
  const collect = bytes => { output = (output + bytes.toString()).slice(-65536); };
  server.stdout.on('data', collect);
  server.stderr.on('data', collect);
  const [, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const bodies = [];
  page.on('response', async response => {
    try { bodies.push(`${response.url()}\n${await response.text()}`); } catch { /* redirects and aborted bodies */ }
  });
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  return { page, url, errors, bodies };
}

test('credentials panel: binding heads, catalog refresh and model choice, pending acts, the owner fence and refusals, no secret anywhere', { timeout: 120000 }, async t => {
  const { page, url, errors, bodies } = await open(t);
  await page.goto(url + 'records.html');
  const panel = page.locator('#records-credentials');
  const line = panel.locator('[role=status]');
  const connections = panel.getByRole('list', { name: '제공자 연결' });
  const acts = panel.getByRole('list', { name: '끝나지 않은 요청' });
  const credentials = panel.getByRole('list', { name: '저장된 자격증명' });
  const secretField = panel.locator('#credential-secret');
  const said = async text => {
    try {
      await line.filter({ hasText: text }).waitFor();
    } catch (error) {
      throw new Error(`status was ${JSON.stringify(await line.textContent())} (${await line.getAttribute('data-state')})`, { cause: error });
    }
    assert.equal(await line.textContent(), text);
  };
  const typeSecret = async value => {
    await secretField.fill(value);
    return async name => {
      await panel.getByRole('button', { name, exact: true }).click();
      assert.equal(await secretField.inputValue(), '');  // cleared before the answer
    };
  };

  await credentials.getByText(CREDENTIAL_MESSAGES.empty).waitFor();
  await connections.getByText(CONNECTION_MESSAGES.empty).waitFor();
  await acts.getByText(PENDING_MESSAGES.empty).waitFor();
  assert.ok((await panel.textContent()).includes(CONNECTION_MESSAGES.voids));
  assert.ok((await panel.textContent()).includes(CONNECTION_MESSAGES.independent));
  const upstream = async () => page.evaluate(async () => (await fetch('/__test__/upstream')).json());

  // create: bound at revision 1, no catalog or model choice for it
  await (await typeSecret(SECRETS.first))('키 저장');
  await said(CREDENTIAL_MESSAGES.created);
  const claude = connections.locator('li[data-provider=claude]');
  await claude.and(page.locator('[data-binding-revision="1"]')).waitFor();
  const handle = await credentials.locator('li').first().getAttribute('data-handle');
  assert.match(handle, /^[0-9a-f]{32}$/);
  assert.equal(await claude.locator('span').first().textContent(), `claude · ${CONNECTION_STATES.bound} · 키 ${handle} · 바인딩 수정본 1`);
  assert.ok((await claude.textContent()).includes(`${CONNECTION_MESSAGES.catalog.absent} · ${CONNECTION_MESSAGES.model_choice.absent}`));
  assert.equal(await claude.getAttribute('data-gateway-head'), 'applied');
  assert.match(await credentials.locator('li').first().textContent(), /이 제공자 연결에 쓰이는 키 \(바인딩 수정본 1\)/);
  // the only act on the head before a catalog exists is the explicit refresh; no provider request yet
  assert.deepEqual(await connections.getByRole('button').allTextContents(), ['모델 목록 새로 고침']);
  assert.deepEqual(await upstream(), { requests: 0, distinct_keys: 0 });

  // the owner's explicit refresh: the gateway reads the model list with the key it holds
  await claude.getByRole('button', { name: '모델 목록 새로 고침' }).click();
  await said(CATALOG_RESULTS.refreshed(1, 2));
  await claude.locator('[data-catalog=current]').waitFor();
  assert.deepEqual(await upstream(), { requests: 1, distinct_keys: 1 });
  const models = claude.locator('select');
  assert.deepEqual(await models.locator('option').allTextContents(), ['synthetic-model-a', 'synthetic-model-b']);
  await models.selectOption('synthetic-model-b');
  await claude.getByRole('button', { name: '이 모델 선택' }).click();
  await said(CATALOG_RESULTS.chosen('synthetic-model-b'));
  await claude.locator('[data-chosen-model="synthetic-model-b"]').waitFor();
  assert.ok((await claude.textContent()).includes(`${CONNECTION_MESSAGES.catalog.current} · ${CONNECTION_MESSAGES.model_choice.current}`));
  assert.deepEqual(await upstream(), { requests: 1, distinct_keys: 1 });  // a choice calls no provider

  // a second create for a bound provider is refused before any gateway call
  await (await typeSecret(SECRETS.second))('키 저장');
  await said(CREDENTIAL_ERRORS.connection_bound);
  assert.equal(await line.getAttribute('data-state'), 'connection_bound');

  // a rotation the gateway commits without replying: unconfirmed, fence offered only once due
  await credentials.locator(`li[data-handle="${handle}"]`).getByRole('button', { name: '교체' }).click();
  await (await typeSecret(SECRETS.noReply))('키 교체');
  await said(CREDENTIAL_ERRORS.command_pending);
  const stuck = acts.locator('li[data-state=command_pending]');
  await stuck.waitFor();
  const firstIntent = await stuck.getAttribute('data-intent');
  assert.match(await stuck.textContent(), new RegExp(`키 교체 · claude · ${handle} · 요청 ${firstIntent}`));
  assert.match(await stuck.textContent(), /차단 가능 시각: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} UTC/);
  assert.equal(await stuck.getByRole('button', { name: '이 요청 차단' }).count(), 0);
  assert.ok(await panel.getByRole('button', { name: '결과 다시 확인' }).isVisible());
  // the unfinished rotation has not moved the binding or voided its catalog
  assert.equal(await claude.getAttribute('data-binding-revision'), '1');
  await claude.locator('[data-catalog=current]').waitFor();
  // the server refuses an early fence on its own
  const early = await page.evaluate(async ({ base, intent }) => {
    const session = await (await fetch(base + 'session')).json();
    const response = await fetch(base + 'api/v1/credentials/fences', { method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token }, body: JSON.stringify({ intent_id: intent }) });
    return [response.status, (await response.json()).code];
  }, { base, intent: firstIntent });
  assert.deepEqual(early, [409, 'fence_not_due']);
  // the button appears by itself when due (a re-render, no request), and the fence finds the commit
  await stuck.getByRole('button', { name: '이 요청 차단' }).click({ timeout: (FENCE_DELAY_SECONDS + 5) * 1000 });
  await line.and(page.locator('[data-state^=orphan_]')).waitFor();
  assert.ok([FENCE_RESULTS.orphan_retired, FENCE_RESULTS.orphan_retiring].includes(await line.textContent()));
  const orphan = acts.locator(`li[data-intent="${firstIntent}"][data-state=fenced]`);
  await orphan.waitFor();
  assert.match(await orphan.locator('[data-uncertain-record]').getAttribute('data-uncertain-record'), /^(cleanup_pending|retirement_pending)$/);
  assert.equal(await panel.getByRole('button', { name: '결과 다시 확인' }).count(), 0);  // the act is over
  assert.equal(await claude.getAttribute('data-binding-revision'), '1');  // never bound
  await claude.locator('[data-catalog=current]').waitFor();

  // a rotation that is never admitted: its command stays unknown and the fence makes it terminal
  await credentials.locator(`li[data-handle="${handle}"]`).getByRole('button', { name: '교체' }).click();
  await (await typeSecret(SECRETS.unadmitted))('키 교체');
  await said(CREDENTIAL_ERRORS.command_pending);
  const unknown = acts.locator('li[data-state=command_pending]');
  const secondIntent = await unknown.getAttribute('data-intent');
  assert.notEqual(secondIntent, firstIntent);
  await unknown.getByRole('button', { name: '이 요청 차단' }).click({ timeout: (FENCE_DELAY_SECONDS + 5) * 1000 });
  await said(FENCE_RESULTS.fenced);
  assert.equal(await line.getAttribute('data-state'), 'fenced');
  const fenced = acts.locator(`li[data-intent="${secondIntent}"][data-state=fenced]`);
  await fenced.waitFor();
  assert.equal(await fenced.locator('[data-uncertain-record]').getAttribute('data-uncertain-record'), 'unknown');
  assert.match(await fenced.textContent(), new RegExp(`${PENDING_MESSAGES.fenced}: ${PENDING_MESSAGES.uncertain.unknown.replace(/[()]/g, '\\$&')}`));

  // a real rotation moves the binding to revision 2 and voids the catalog/model choice
  await credentials.locator(`li[data-handle="${handle}"]`).getByRole('button', { name: '교체' }).click();
  await (await typeSecret(SECRETS.third))('키 교체');
  await said(CREDENTIAL_MESSAGES.rotated);
  await claude.and(page.locator('[data-binding-revision="2"]')).waitFor();
  assert.ok((await claude.textContent()).includes(`${CONNECTION_MESSAGES.catalog.absent} · ${CONNECTION_MESSAGES.model_choice.absent}`));
  assert.equal(await claude.locator('select').count(), 0);
  assert.equal(await claude.locator('[data-chosen-model]').count(), 0);
  assert.deepEqual(await upstream(), { requests: 1, distinct_keys: 1 });  // the rotation made no provider request
  // only a new explicit refresh gives revision 2 a catalog, read with the new key
  await claude.getByRole('button', { name: '모델 목록 새로 고침' }).click();
  await said(CATALOG_RESULTS.refreshed(2, 2));
  await claude.locator('[data-catalog=current]').waitFor();
  assert.deepEqual(await upstream(), { requests: 2, distinct_keys: 2 });

  // delete: asks first, says the provider key is not revoked; the binding is revoked
  await credentials.locator(`li[data-handle="${handle}"]`).getByRole('button', { name: '삭제' }).click();
  assert.match(await panel.textContent(), /제공자 쪽의 키는 폐기되지 않습니다\(provider_revocation: not_performed\)/);
  await panel.getByRole('button', { name: '삭제 확인' }).click();
  await said(CREDENTIAL_MESSAGES.deleted);
  await claude.and(page.locator('[data-state=revoked_pending_erasure]')).waitFor();
  assert.equal(await claude.textContent(), `claude · ${CONNECTION_STATES.revoked_pending_erasure} · 키 ${handle} · 바인딩 수정본 3`);
  assert.equal(await connections.getByRole('button').count(), 0);  // a revoked head offers nothing

  // no secret in the DOM, in browser storage or in any response the page received
  const dom = await page.evaluate(() => [document.documentElement.outerHTML,
    ...[...document.querySelectorAll('input')].map(input => input.value),
    JSON.stringify({ ...localStorage }), JSON.stringify({ ...sessionStorage })].join('\n'));
  for (const secret of Object.values(SECRETS)) {
    assert.ok(!dom.includes(secret), 'a secret reached the page or its storage');
    assert.ok(!bodies.some(body => body.includes(secret)), 'a secret was echoed in a response');
  }
  assert.deepEqual(errors, []);
});
