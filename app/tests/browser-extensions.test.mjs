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
// The inventory lists are the real (empty) pages; the slot key is computed by the real route and
// a bind without a sealed qualification is refused on the page with no request.
//
// The second case runs the fixture with `--synthetic-bindings`: two synthetic extensions with
// test-validator installation records and the binding service's test qualification resolver (a
// sealed transport qualification cannot be composed here). Two binds and a sibling slot are set
// up through the real routes; then the owner reads the slot (the server's key, digest, history,
// coexistence and retention), meets a stale head after a competing change (409 shown with the
// server's text), re-reads, rolls back to the retained revision, releases the other retained
// revision through its confirmation showing the server's warning, and disables — all real
// routes, real records and CAS.
//
// Not driven here (the standalone server cannot compose them; they need the pytest-owned
// `installation_case` release tree, monkeypatched publication/source fixtures and retained
// framed conformance worker): a successful staged→verified installation, a
// verified-installation conformance run and its matched/mismatch display, the transport
// qualification act, and a bind over a real sealed qualification (covered in pytest,
// test_extension_bindings_qualified.py). The owner is a scripted test actor: synthetic evidence
// of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';
import { BINDING_ERRORS, ERRORS, MESSAGES, NOT_SUPPLIED, SUPPLY } from '../static/extensions.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /EXTENSIONS_INPUTS=(\{[^\n]*\})\r?\nEXTENSIONS_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;

async function open(t, extra = []) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-extensions-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Extensions fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/extensions_server.py', '--owned-dir', dir, ...extra],
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
  const bootstrapped = await page.evaluate(async ({ base, capability }) => {
    const response = await fetch(base + 'session/bootstrap', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
    });
    return { status: response.status, csrf: (await response.json()).csrf_token };
  }, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
  assert.equal(bootstrapped.status, 201);
  return { page, url, errors, requests, inputs: JSON.parse(inputs), csrf: bootstrapped.csrf };
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
    // the real inventory pages are empty; no slot read means no disable/rollback/release control
    await section.locator('[data-view="slot-list"]').getByText('바인딩 slot 없음').waitFor();
    for (const path of ['candidates', 'installations', 'bindings']) {
      assert.ok(requests.includes(`GET ${base}api/v1/extensions/${path}`), path);
    }
    for (const act of ['disable', 'rollback', 'release-start', 'release-confirm']) {
      assert.equal(await section.locator(`button[data-act="${act}"]`).count(), 0, act);
    }
    // the slot key is the server's; a bind without a sealed qualification is refused here
    const bind = section.getByRole('button', { name: '계산한 slot에 바인딩' });
    assert.equal(await bind.getAttribute('aria-disabled'), 'true');
    await section.getByRole('button', { name: 'slot key 계산' }).click();
    await section.locator('[data-extensions-line][data-state="key"]').waitFor();
    const digest = await section.locator('[data-view="slot-key"]').getAttribute('data-digest');
    assert.match(digest, /^[0-9a-f]{64}$/);
    assert.ok(requests.includes(`POST ${base}api/v1/extensions/binding-slot-keys`));
    const beforeBind = requests.length;
    await bind.click({ force: true });
    await section.locator('[data-extensions-line][data-state="refused_here"]').waitFor();
    assert.equal(await line.textContent(), MESSAGES.noQualification);
    assert.equal(requests.slice(beforeBind).filter(item => item.startsWith('POST')).length, 0);
    // an unknown slot digest is the real route's not_found with its text
    await section.getByLabel('slot key digest').fill('a'.repeat(64));
    await section.getByRole('button', { name: 'slot 읽기', exact: true }).click();
    await section.locator('[data-extensions-line][data-state="not_found"]').waitFor();
    assert.equal(await line.textContent(), BINDING_ERRORS.not_found);
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
    // trust tier from the real candidate list (re-read after the registration); no installation
    const listed = await page.evaluate(async ({ base }) => (await fetch(`${base}api/v1/extensions/candidates`)).json(), { base });
    const row = listed.items.find(item => item.candidate_id === id);
    assert.equal(row.trust_tier, 'runtime_worker');
    assert.equal(await dd('trust').textContent(), `${row.trust_tier} (포트 계약 기준)`);
    assert.equal(await dd('installation').textContent(), '읽은 설치 목록에 이 후보의 설치 없음');
    assert.equal(await dd('binding').textContent(), '없음');
    assert.equal(await dd('environments').textContent(), NOT_SUPPLIED);
    assert.equal(await dd('environments').getAttribute('data-supplied'), 'false');
    assert.equal(await section.locator(`[data-candidate-row="${id}"]`).count(), 1);
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
    await section.getByRole('button', { name: '후보 읽기', exact: true }).click();
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

test('Settings > Extensions bindings: slot read, stale head, rollback, warned release and disable over the real routes',
  { timeout: 120000 }, async t => {
    const { page, url, errors, requests, inputs, csrf } = await open(t, ['--synthetic-bindings']);
    const { a, b } = inputs.bindings;
    // set-up through the real routes: A binds the slot, B supersedes it, B also holds a sibling slot
    const setup = await page.evaluate(async ({ base, csrf, a, b }) => {
      const post = async (path, body) => {
        const response = await fetch(`${base}api/v1/extensions/${path}`, { method: 'POST', body: JSON.stringify(body),
          headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': csrf } });
        return { status: response.status, body: await response.json() };
      };
      const scope = { environment_id: null, work_id: null, node_id: null, purpose: 'operational' };
      const selector = { selector_kind: 'provider_role', provider_id: 'claude', auth_mode: 'api', account_binding_ref: null };
      const key = async slot => (await post('binding-slot-keys', { port_contract_version: 'provider-port-v1',
        binding_slot_id: slot, target_scope: scope, capability_selector: selector })).body;
      const bind = (k, q, head) => post('bindings', { command_id: crypto.randomUUID(), extension_id: q.extension_id,
        qualification_ref: q.qualification_ref, binding_slot_key: k.binding_slot_key, binding_slot_key_digest: k.binding_slot_key_digest,
        capability_selector: k.capability_selector, target_scope: k.target_scope, expected_current_binding_head: head });
      const main = await key('default-provider');
      const first = await bind(main, a, null);
      const second = await bind(main, b, first.body.binding_head);
      const sibling = await key('review-provider');
      const third = await bind(sibling, b, null);
      return { main, statuses: [first.status, second.status, third.status], head: second.body.binding_head };
    }, { base, csrf, a, b });
    assert.deepEqual(setup.statuses, [200, 200, 200]);
    const digest = setup.main.binding_slot_key_digest;

    await page.goto(url + 'settings.html#settings-extensions');
    const section = page.locator('#settings-extensions');
    const line = section.locator('[data-extensions-line]');
    await section.locator('[data-slot-row]').nth(1).waitFor();
    assert.equal(await section.locator('[data-slot-row]').count(), 2);
    assert.equal(await section.locator('[data-installation-row]').count(), 2);
    assert.match(await section.locator('[data-installation-row] dd[data-field="trust"]').first().textContent(), /^runtime_worker \(포트 계약 기준\)$/);

    // the slot read shows the server's own key, digest, history, coexistence and retention
    await section.locator(`[data-slot-row="${digest}"]`).getByRole('button', { name: '이 slot 읽기' }).click();
    const slot = section.locator('[data-view="slot"]');
    await page.waitForFunction(expected => document.querySelector('[data-view="slot"]')?.dataset.head === expected, '2:active');
    const server = await page.evaluate(async ({ base, digest }) => (await fetch(`${base}api/v1/extensions/bindings/${digest}`)).json(), { base, digest });
    const dd = name => slot.locator(`dd[data-field="${name}"]`);
    assert.equal(await dd('binding_slot_key').textContent(), JSON.stringify(server.binding_slot_key));
    assert.equal(await dd('binding_slot_key_digest').textContent(), digest);
    assert.equal(await dd('capability_selector').textContent(), JSON.stringify(server.capability_selector));
    assert.match(await dd('coexistence').textContent(), /review-provider · ext-b/);
    assert.match(await dd('competition').textContent(), /ext-a \(수정본 1\) \/ ext-b \(수정본 2\)/);
    assert.match(await dd('environments').textContent(), /이 slot의 수정본을 기록한 환경 버전 없음 · 다시 준비가 필요한 환경 없음/);
    assert.equal(await slot.locator('[data-revision]').count(), 2);
    assert.equal(await slot.locator('[data-retention-target="1"]').getAttribute('data-state'), 'retained');

    // a competing change after the read: the page's act carries the old head and is refused 409
    const competing = await page.evaluate(async ({ base, csrf, server }) => (await fetch(
      `${base}api/v1/extensions/bindings/${server.binding_slot_key_digest}/disable`, { method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': csrf },
        body: JSON.stringify({ command_id: crypto.randomUUID(), extension_id: 'ext-b', binding_slot_key: server.binding_slot_key,
          binding_slot_key_digest: server.binding_slot_key_digest, expected_current_binding_head: server.head }) })).status,
    { base, csrf, server });
    assert.equal(competing, 200);
    await slot.locator('[data-retention-target="1"]').getByRole('button', { name: '이 수정본으로 롤백' }).click();
    await section.locator('[data-extensions-line][data-state="binding_head_stale"]').waitFor();
    assert.equal(await line.textContent(), BINDING_ERRORS.binding_head_stale);
    assert.equal(await slot.getAttribute('data-head'), '2:active', 'the page changes nothing on a conflict');

    // read again, then roll back to A's retained revision
    await section.getByRole('button', { name: 'slot 읽기', exact: true }).click();
    await page.waitForFunction(() => document.querySelector('[data-view="slot"]')?.dataset.head === '3:disabled');
    assert.equal(await slot.getByRole('button', { name: '이 slot 비활성화' }).count(), 0);
    await slot.locator('[data-retention-target="1"]').getByRole('button', { name: '이 수정본으로 롤백' }).click();
    await page.waitForFunction(() => document.querySelector('[data-view="slot"]')?.dataset.head === '4:active');
    assert.equal(await line.textContent(), MESSAGES.rolledBack({ revision: 4, state: 'active' }));
    assert.equal(await slot.locator('[data-retention-target="1"]').getAttribute('data-state'), 'consumed');
    assert.match(await dd('current').textContent(), /^ext-a · /);

    // release B's retained revision: a separate confirmation showing the server's warning
    const target = slot.locator('[data-retention-target="2"]');
    assert.equal(await target.getAttribute('data-state'), 'retained');
    const before = requests.length;
    await target.getByRole('button', { name: '롤백 보존 해제…' }).click();
    const confirm = slot.locator('[data-view="release-confirm"]');
    await confirm.waitFor();
    const read = await page.evaluate(async ({ base, digest }) => (await fetch(`${base}api/v1/extensions/bindings/${digest}`)).json(), { base, digest });
    const warning = read.rollback_retentions.find(item => item.target_binding_revision_ref.revision === 2).release_warning;
    assert.equal(await confirm.locator('[data-view="release-warning"]').textContent(), warning);
    assert.match(await confirm.textContent(), /현재 바인딩: 수정본 4 · active/);
    assert.equal(requests.slice(before).filter(item => item.startsWith('POST')).length, 0, 'opening the confirmation sends nothing');
    await confirm.getByLabel('해제 사유').fill('시험: 퇴역 전 보존 해제');
    const released = page.waitForRequest(request => request.method() === 'POST' && new URL(request.url()).pathname.endsWith('/release'));
    await confirm.getByRole('button', { name: '보존 해제 확인' }).click();
    const body = JSON.parse((await released).postData());
    assert.deepEqual(Object.keys(body), ['command_id', 'extension_id', 'binding_slot_key', 'binding_slot_key_digest',
      'expected_current_binding_head', 'target_binding_revision_ref', 'target_installation_ref', 'target_service_tuple',
      'expected_retention_head', 'reason']);
    await section.locator('[data-extensions-line][data-state="released"]').waitFor();
    assert.equal(await slot.locator('[data-retention-target="2"]').getAttribute('data-state'), 'released');
    assert.equal(await slot.locator('[data-revision]').count(), 4, 'history is kept');
    assert.equal(await slot.getAttribute('data-head'), '4:active', 'the binding head is unchanged');
    assert.equal(await slot.locator('[data-retention-target="2"] button').count(), 0);

    // disable the slot
    await slot.getByRole('button', { name: '이 slot 비활성화' }).click();
    await page.waitForFunction(() => document.querySelector('[data-view="slot"]')?.dataset.head === '5:disabled');

    // the staging request read goes to the real deployment route as the server linked it; the
    // synthetic stand-in is not a deployment request, so the route refuses it and the page says so
    const link = (await page.evaluate(async ({ base }) => (await fetch(`${base}api/v1/extensions/installations`)).json(), { base }))
      .items[0].staging.request_link;
    const answered = page.waitForResponse(response => new URL(response.url()).pathname === link);
    await section.locator('[data-installation-row]').first().getByRole('button', { name: '배포 요청 상태 읽기' }).click();
    const response = await answered;
    assert.ok(response.status() >= 400, String(response.status()));
    await page.waitForFunction(() => !['working', 'released', 'disabled', 'read', 'loaded']
      .includes(document.querySelector('[data-extensions-line]')?.dataset.state));
    const code = await line.getAttribute('data-state');
    assert.equal(await line.textContent(), ERRORS[code], code);
    assert.deepEqual(errors, []);
  });
