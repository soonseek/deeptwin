// Settings > Extensions in a real browser against the real supported server
// (app/tests/fixtures/extensions_server.py: create_app with its fixed extension
// contributions, nothing seeded). The owner opens the section from the settings hub; the
// first read is the real transport-qualification state (no verified installation, no
// gateway), shown with the link to the credentials section. The owner picks a synthetic
// candidate metadata file and registers it; the screen shows the server's own read of it
// (source, license and its text, kind/port, digests, platforms) and marks trust,
// installation/qualification, binding/slot key and affected environments as not supplied.
// An explicit-command-id file registers once and its changed twin under the same id is
// shown as a 409 conflict. A structurally valid release-evidence packet naming a staged
// installation that does not exist is sent unchanged and refused 409 by the real route.
// A conformance run is refused on the page (no head was read) with no request.
//
// Not driven here (the standalone server cannot compose them; they need the pytest-owned
// `installation_case` release tree, monkeypatched publication/source fixtures and retained
// framed conformance worker): a successful staged→verified installation, a
// verified-installation conformance run and its matched/mismatch display, the transport
// qualification act. Those renderings are unit-tested in extensions.test.mjs only.
// The owner is a scripted test actor: synthetic evidence of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';
import { ERRORS, MESSAGES, NOT_SUPPLIED, SUPPLY } from '../static/extensions.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /EXTENSIONS_INPUTS=(\{[^\n]*\})\r?\nEXTENSIONS_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

async function open(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-extensions-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Extensions fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/extensions_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 30000, label: 'Extensions fixture',
    maxOutputChars: 1_048_576 });
  const [, inputs, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const requests = [];
  page.on('request', request => requests.push(`${request.method()} ${new URL(request.url()).pathname}`));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
  })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped, 201);
  return { page, url, errors, requests, inputs: JSON.parse(inputs) };
}

const file = (name, value) => ({ name, mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(value)) });

test('Settings > Extensions: real reads, candidate registration and conflict, refused packet, nothing invented',
  { timeout: 120000 }, async t => {
    const { page, url, errors, requests, inputs } = await open(t);
    await page.goto(url + 'settings.html');
    await page.locator('#settings-hub li[data-entry="extensions"] a').click();
    await page.waitForURL(url + 'settings.html#settings-extensions');
    const section = page.locator('#settings-extensions');
    const line = section.locator('[data-extensions-line]');
    await section.locator('[data-extensions-line][data-state="loaded"]').waitFor();
    assert.equal(await section.getByRole('heading', { name: '확장', exact: true }).count(), 1);
    assert.ok(requests.includes(`GET ${base}api/v1/extensions/provider-transport-qualification`));

    // what the server supplies, and what it does not
    const supplied = await section.locator('li[data-supply]').evaluateAll(nodes => nodes.map(node => [node.dataset.supply, node.dataset.supplied]));
    assert.deepEqual(supplied, SUPPLY.map(entry => [entry.id, String(entry.supplied)]));
    const qualification = section.locator('[data-view="qualification"]');
    assert.equal(await qualification.getAttribute('data-state'), 'unqualified');
    assert.match(await qualification.locator('dd[data-field="prerequisite"]').textContent(), /verified_installation_missing/);
    assert.match(await qualification.locator('dd[data-field="gateway"]').textContent(), /unavailable/);
    assert.equal(await section.locator('a[data-link="transport-qualification"]').getAttribute('href'), './records.html#records-credentials');
    assert.equal(await section.locator('[data-extensions-section="binding"] dd[data-supplied="false"]').count(), 8);
    const buttons = await section.getByRole('button').allTextContents();
    assert.ok(buttons.every(label => !/바인딩|비활성|롤백|해제|제거/.test(label)), buttons.join('|'));
    const all = await section.textContent();
    for (const word of [/docker/i, /compose/i, /portainer/i, /kubectl/i, /sudo/i, /터미널/, /CLI/]) assert.ok(!word.test(all), String(word));

    // a conformance run needs a read head: refused on the page, no request
    const before = requests.length;
    const run = section.getByRole('button', { name: '읽은 헤드로 적합성 검사 실행' });
    assert.equal(await run.getAttribute('aria-disabled'), 'true');
    await run.click({ force: true });
    await section.locator('[data-extensions-line][data-state="refused_here"]').waitFor();
    assert.equal(await line.textContent(), MESSAGES.noHead);
    assert.equal(requests.slice(before).filter(item => item.startsWith('POST')).length, 0);

    // register the synthetic candidate metadata file; the screen shows the server's own read
    await section.getByLabel('후보 메타데이터 파일(JSON, 코드 없음)').setInputFiles(file('candidate.json', inputs.candidate));
    await section.getByRole('button', { name: '이 메타데이터로 후보 등록' }).click();
    await section.locator('[data-extensions-line][data-state="registered"]').waitFor();
    const view = section.locator('[data-view="candidate"]');
    const id = await view.getAttribute('data-candidate-id');
    assert.match(id, /^[0-9a-f-]{36}$/);
    assert.equal(await line.textContent(), MESSAGES.registered(id));
    const server = await page.evaluate(async ({ base, id }) => (await fetch(`${base}api/v1/extensions/candidates/${id}`)).json(), { base, id });
    const dd = name => view.locator(`dd[data-field="${name}"]`);
    assert.equal(await dd('manifest_digest').textContent(), server.candidate_ref.manifest_digest);
    assert.equal(await dd('registration_digest').textContent(), server.registration_digest);
    assert.equal(await dd('port_contract_version').textContent(), 'tool-port-v1');
    assert.equal(await dd('kind').textContent(), 'tool');
    assert.match(await dd('source').textContent(), /third_party · https:\/\/example\.test\/synthetic/);
    assert.match(await dd('license').textContent(), /^Synthetic · 원문 license · sha256 [0-9a-f]{64}/);
    assert.equal(await dd('license_text').textContent(), 'Synthetic license\n');
    assert.match(await dd('platforms').textContent(), /linux\/amd64.*linux\/arm64/);
    assert.equal(await dd('state').textContent(), MESSAGES.candidateState.registered_unqualified);
    for (const name of ['trust', 'installation', 'binding', 'environments']) {
      assert.equal(await dd(name).textContent(), NOT_SUPPLIED, name);
      assert.equal(await dd(name).getAttribute('data-supplied'), 'false', name);
    }
    // the request was metadata JSON only
    assert.ok(requests.includes(`POST ${base}api/v1/extensions/candidates`));

    // the same command id with changed content: the route's 409 is shown, nothing else changes
    await section.getByLabel('후보 메타데이터 파일(JSON, 코드 없음)').setInputFiles(file('fixed.json', inputs.candidate_fixed));
    await section.getByRole('button', { name: '이 메타데이터로 후보 등록' }).click();
    await section.locator('[data-extensions-line][data-state="registered"]').waitFor();
    const fixedId = await view.getAttribute('data-candidate-id');
    assert.notEqual(fixedId, id);
    await section.getByLabel('후보 메타데이터 파일(JSON, 코드 없음)').setInputFiles(file('changed.json', inputs.candidate_changed));
    await section.getByRole('button', { name: '이 메타데이터로 후보 등록' }).click();
    await section.locator('[data-extensions-line][data-state="conflict"]').waitFor();
    assert.equal(await line.textContent(), ERRORS.conflict);
    assert.equal(await view.getAttribute('data-candidate-id'), fixedId);

    // a read of the first candidate by its id
    await section.getByLabel('후보 ID').fill(id);
    await section.getByRole('button', { name: '후보 읽기' }).click();
    await page.waitForFunction(expected => document.querySelector('[data-view="candidate"]')?.dataset.candidateId === expected, id);

    // the release-evidence packet: header shown, bytes sent unchanged, the real route refuses it
    const packet = Buffer.from(inputs.packet_b64, 'base64');
    await section.getByLabel('릴리스 증거 묶음 파일').setInputFiles({ name: 'evidence.dtpi', mimeType: 'application/octet-stream', buffer: packet });
    await section.locator('[data-view="packet"]').getByText(inputs.staged_id, { exact: false }).waitFor();
    const posted = page.waitForRequest(request => request.method() === 'POST'
      && new URL(request.url()).pathname === `${base}api/v1/extensions/provider-installation`);
    await section.getByRole('button', { name: '이 증거 묶음으로 설치 검증' }).click();
    const request = await posted;
    assert.equal(request.headers()['content-type'], 'application/vnd.deeptwin.provider-installation-v1');
    assert.ok(Buffer.from(request.postDataBuffer()).equals(packet), 'the exact file bytes');
    await section.locator('[data-extensions-line][data-state="conflict"]').waitFor();
    assert.equal(await section.locator('[data-view="installation"] dl').count(), 0);

    // a read of an unknown installation command is the route's not_found
    await section.getByLabel('설치 검증 요청 ID').fill('88888888-8888-4888-8888-888888888888');
    await section.getByRole('button', { name: '설치 검증 결과 읽기' }).click();
    await section.locator('[data-extensions-line][data-state="not_found"]').waitFor();
    assert.equal(await line.textContent(), ERRORS.not_found);
    assert.deepEqual(errors, []);
  });
