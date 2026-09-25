// T067 (US6, growth.md §9): G-06..G-13 and rollback in a real browser against the real
// supported server over a durable chain seeded through the real services
// (app/tests/fixtures/growth_server.py → app/tests/growth_chain_fixture.py): isolated
// paired rounds on the real scheduler, CAS loop revisions, sealed validation, the
// owner's own approvals. The server is then restarted over the same store. Every fact
// is SYNTHETIC and authored by the vault's test actor; no actual user evidence exists.
// G-14 (past external effects replay) and G-15 (lens on/off comparison) have no product
// surface yet and are not exercised here (evidence/us6.md).

import { after, before, describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, terminateOwnedChild, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /GROWTH_PORT=(\d+)\nGROWTH_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const PLATEAU = '67001000-0000-4000-8000-000000000000';
const BELOW = '67002000-0000-4000-8000-000000000000';
const OLD = '67003000-0000-4000-8000-000000000000';
const NEW = '67004000-0000-4000-8000-000000000000';
const short = ref => `${ref.kind} ${ref.id.slice(0, 8)} (${ref.sha256.slice(0, 12)})`;
const CONFLICT = '운영 버전이 그사이 바뀌었거나 이 승인은 이미 적용되었습니다. 다시 확인해 주세요.';

let dir, server, browser, page, url, port, seed;
const errors = [];
const approvals = [];

async function start(args) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const child = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/growth_server.py', '--owned-dir', dir, ...args],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(child, { pattern: READY, timeoutMs: 180000, label: 'Growth fixture' });
  const [, announcedPort, announcedUrl] = READY.exec(announced);
  return { child, port: Number(announcedPort), url: announcedUrl };
}

async function api(path, body) {
  return page.evaluate(async ({ base, path, body }) => {
    const session = await (await fetch(base + 'session')).json();
    const response = await fetch(base + 'api/v1/versions' + path, body === undefined ? {} : {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': session.csrf_token },
      body: JSON.stringify(body) });
    return { status: response.status, body: await response.json() };
  }, { base, path, body });
}

async function openVersions() {
  await page.goto(url + 'versions.html');
  await page.locator('#versions [role=status][data-state=loaded]').waitFor({ state: 'attached' });
}

const section = name => page.locator(`#versions section[aria-label="${name}"]`);
const experiment = lineage => section('성장 실험').locator('p', { hasText: `계보 ${lineage.slice(0, 8)}` });
const candidate = ref => section('후보').locator('article', { hasText: short(ref) });
const current = async () => section('운영 버전').textContent();

describe('US6 growth chain in the real browser (synthetic test-actor evidence)', { timeout: 600000 }, () => {
  before(async () => {
    dir = await mkdtemp(join(tmpdir(), 'deeptwin-growth-'));
    ({ child: server, port, url } = await start([]));
    seed = JSON.parse(await readFile(join(dir, 'growth-seed.json'), 'utf8'));
    assert.equal(seed.evidence_label, 'synthetic/test-actor');
    const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
    browser = await chromium.launch({ channel: 'chrome', headless: true });
    const context = await browser.newContext({ viewport: { width: 1200, height: 1000 } });
    page = await context.newPage();
    page.setDefaultTimeout(15000);
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', async response => {
      if (response.url().endsWith('/api/v1/versions/decisions') && response.ok()) approvals.push(await response.json());
    });
    await page.goto(url);
    const bootstrapped = await page.evaluate(async ({ base, capability }) => (await fetch(base + 'session/bootstrap', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase', raw_capability_b64u: capability }),
    })).status, { base, capability: Buffer.alloc(32, 'T').toString('base64url') });
    assert.equal(bootstrapped, 201);
    // the owner adopts the (synthetic) operating environment once; the page has no adopt control
    const adopted = await api('/adopt', { environment_ref: seed.operating_environment_ref });
    assert.equal(adopted.status, 200);
    await openVersions();
  });

  after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 5000, serverForceMs: 2000, label: 'Growth fixture' }));

  it('G-06: paired baseline/candidate rounds with validity, and a score only on valid rounds', async () => {
    const group = section('비교 라운드').locator(`section[aria-label="계보 ${PLATEAU.slice(0, 8)}"]`);
    const rounds = group.locator('article');
    assert.equal(await rounds.count(), 6);
    assert.match(await section('비교 라운드').textContent(), /기준과 후보가 만든 노드 결과를 나란히/);
    // T066: every round shows both sides' node results side by side, the changed writer marked
    const first = group.locator('article[aria-label="라운드 0"]');
    const compared = first.locator('table[aria-label="항목 0 산출물 비교"]');
    assert.equal(await compared.count(), 1);
    assert.ok((await compared.locator('tr[data-changed="true"] th').allTextContents()).includes('writer · 다름'));
    for (let index = 0; index < 6; index += 1) {
      const round = group.locator(`article[aria-label="라운드 ${index}"]`);
      const text = await round.textContent();
      const validity = await round.getAttribute('data-validity');
      assert.equal(validity, seed.lineages[PLATEAU].validities[index]);
      // every baseline run sits next to the candidate run it was paired with, and they differ
      const cells = await round.locator('td').allTextContents();
      assert.ok(cells.length >= 2 && cells.length % 2 === 0);
      for (let cell = 0; cell < cells.length; cell += 2) assert.notEqual(cells[cell], cells[cell + 1]);
      assert.ok(cells.includes(short(seed.lineages[PLATEAU].baseline_runs[index][0])));
      if (validity === 'valid') assert.match(text, /유효 · .*utility \d.*효용 0\.8/);
      else {
        assert.match(text, /무효 · 사유: .+ · 유효한 라운드가 아니므로 측정값과 효용을 표시하지 않습니다/);
        assert.doesNotMatch(text, /효용 \d|utility \d/);
      }
    }
    // the crashed round kept only the pair that completed; its reason names the failure class only
    assert.match(await group.locator('article[aria-label="라운드 1"]').textContent(), /짝지은 실행 1쌍.*run failed \(SchedulerError\)/);
    assert.match(await group.locator('article[aria-label="라운드 3"]').textContent(), /평가기가 판정을 내리지 못함\(미결\)/);
  });

  it('G-07: the plateau and below-floor series end with the stop reason the loop recorded', async () => {
    const plateau = await experiment(PLATEAU).textContent();
    assert.match(plateau, /plateau_reached · 하한 도달 뒤 세 번 연속 의미 있는 개선이 없어 멈춤/);
    assert.match(plateau, /최고 0\.81 \(67001-round-2\)/); // the tie at round 5 keeps the earlier best
    assert.match(plateau, /연속 비개선 3/);
    const below = await experiment(BELOW).textContent();
    assert.match(below, /below_floor_exhausted · 하한에 한 번도 닿지 못한 채 예산을 모두 씀\(품질 미달, 승격 아님\)/);
    assert.match(below, /연속 비개선 0/);
    assert.deepEqual([seed.lineages[PLATEAU].progress_reference, seed.lineages[BELOW].progress_reference],
      [{ round_id: '67001-round-0', utility: '0.8' }, null]);
  });

  it('G-08: invalid rounds are never scored or counted, while their consumption accrues', async () => {
    const plateau = await experiment(PLATEAU).textContent();
    // six completed rounds, two of them invalid: exactly three valid non-improvements counted
    assert.match(plateau, /완료 라운드 6개 · 연속 비개선 3/);
    assert.match(plateau, /소비 isolated_runs 12, node_visits 36/);
    const invalid = section('비교 라운드').locator(`section[aria-label="계보 ${PLATEAU.slice(0, 8)}"] article[data-validity=invalid]`);
    assert.equal(await invalid.count(), 2);
  });

  it('G-10: a changed evaluator starts a new lineage that carries no counter, round or baseline run over', async () => {
    const old = await experiment(OLD).textContent();
    assert.match(old, /lineage_changed · 비교 조건이 바뀌어 새 계보로 다시 해야 함/);
    assert.match(old, /연속 비개선 1/);
    const fresh = await experiment(NEW).textContent();
    assert.match(fresh, /running · 진행 중\(멈춤 사유 없음\) · 최고 0\.82 \(67004-round-0\) · 완료 라운드 1개 · 연속 비개선 0/);
    const group = await section('비교 라운드').locator(`section[aria-label="계보 ${NEW.slice(0, 8)}"]`).textContent();
    assert.match(group, /라운드 0 \(67004-round-0\)/);
    for (const pair of seed.lineages[OLD].baseline_runs) {
      for (const run of pair) assert.ok(!group.includes(short(run)), 'the new lineage re-ran its own baseline');
    }
  });

  it('G-11: an early-stop candidate cannot be put into operation without separate validation and exact approval', async () => {
    const early = candidate(seed.early.bundle_ref).filter({ hasText: '(shadow)' });
    assert.match(await early.textContent(), /검증 passed \(shadow\).*봉인 검증을 통과하지 못한 후보는 승인할 수 없습니다/);
    assert.equal(await early.getByRole('button', { name: '승인' }).count(), 0);
    // even recorded through the route, an approve over tuning-only evidence never applies
    const recorded = await api('/decisions', { command_id: crypto.randomUUID(), decision: 'approve',
      validation_report_ref: seed.early.validation_report_ref });
    assert.equal(recorded.status, 200);
    const before = await api('');
    const refused = await api('/activate', { approval_ref: recorded.body.approval_ref, expected_revision: before.body.state.revision });
    assert.equal(refused.status, 409);
    // a separately validated candidate still needs the owner's approval: no apply control, no apply without one
    const p = candidate(seed.candidates.P.bundle_ref);
    assert.equal(await p.getByRole('button', { name: '승인', exact: true }).count(), 1);
    assert.equal(await p.getByRole('button', { name: '승인한 이 버전 적용' }).count(), 0);
    const unapproved = await api('/activate', { approval_ref: seed.candidates.P.report_record, expected_revision: before.body.state.revision });
    assert.ok(unapproved.status >= 400);
    assert.deepEqual((await api('')).body.state, before.body.state);
  });

  it('G-12: a candidate edited after its sealed data was reviewed gets no unseen pass', async () => {
    const q = candidate(seed.candidates.Q.bundle_ref);
    assert.match(await q.textContent(), /검증 failed \(sealed_offline\).*미관측 전이: fail · 비교 라운드 1개 · 새 사례 전이에서 필수 출처가 빠짐/);
    assert.equal(await q.getByRole('button', { name: '승인', exact: true }).count(), 0);
    // the edited Q' exists as a frozen bundle but has no report: nothing to decide over
    assert.equal(await candidate(seed.edited_q.bundle_ref).count(), 0);
    assert.equal(seed.edited_q.sealed_q_classification, 'tuning');
    assert.deepEqual(seed.edited_q.unseen_after_review, []);
    assert.match(seed.edited_q.unseen_pass, /^refused: an unseen pass requires unexposed sealed data/);
  });

  it('G-13 and rollback: a moved version fails the conditional apply; nothing else is promoted; rollback states its reason', async () => {
    const operating = short(seed.operating_environment_ref);
    assert.match(await current(), new RegExp(`지금 운영: ${operating.replace(/[()]/g, '\\$&')} · 수정본 1`));
    const p = candidate(seed.candidates.P.bundle_ref);
    const r = candidate(seed.candidates.R.bundle_ref);
    await p.getByRole('button', { name: '승인', exact: true }).click();
    await p.getByRole('button', { name: '승인한 이 버전 적용' }).waitFor();
    await r.getByRole('button', { name: '승인', exact: true }).click();
    await r.getByRole('button', { name: '승인한 이 버전 적용' }).click();
    await page.locator('#versions [role=status][data-state=applied]').waitFor();
    assert.match(await current(), new RegExp(`지금 운영: ${short(seed.candidates.R.bundle_ref).replace(/[()]/g, '\\$&')} · 수정본 2`));
    // P was approved against the version that was current then; the version moved
    await p.getByRole('button', { name: '승인한 이 버전 적용' }).click();
    await page.locator('#versions [role=status][data-state=conflict]').waitFor();
    assert.equal(await page.locator('#versions [role=status]').textContent(), CONFLICT);
    assert.match(await current(), new RegExp(`${short(seed.candidates.R.bundle_ref).replace(/[()]/g, '\\$&')} · 수정본 2`));
    // rollback needs a stated reason and does not claim to undo what went outside
    await page.getByRole('button', { name: '이전 버전으로 되돌리기' }).click();
    await page.locator('#versions [role=status][data-state=invalid_input]').waitFor();
    assert.match(await current(), /이미 보낸 것·게시한 것은 되돌리지 않습니다/);
    await page.locator('#versions-rollback-reason').fill('합성 사례: 적용 뒤 보고서 품질 저하');
    await page.getByRole('button', { name: '이전 버전으로 되돌리기' }).click();
    await page.locator('#versions [role=status][data-state=rolled_back]').waitFor();
    const restored = await current();
    assert.match(restored, new RegExp(`지금 운영: ${operating.replace(/[()]/g, '\\$&')} · 수정본 3`));
    assert.match(restored, new RegExp(`${short(seed.candidates.R.bundle_ref).replace(/[()]/g, '\\$&')} · 되돌림으로 내림`));
    // the adopted version is current again, but P's approval was given over a state that
    // no longer holds: it is never revived, and nothing is promoted in its place
    await p.getByRole('button', { name: '승인한 이 버전 적용' }).click();
    await page.locator('#versions [role=status][data-state=conflict]').waitFor();
    const refusedAgain = page.waitForResponse(response => response.url().endsWith('/api/v1/versions/activate'));
    await r.getByRole('button', { name: '승인한 이 버전 적용' }).click();
    assert.equal((await refusedAgain).status(), 409);
    const state = (await api('')).body.state;
    assert.deepEqual(state.current_environment_ref, seed.operating_environment_ref);
    assert.equal(state.revision, 3);
    assert.equal(state.external_effects_reverted, false);
    assert.deepEqual(approvals.map(item => item.decision), ['approve', 'approve', 'approve']);  // EARLY (route), P, R
    assert.deepEqual(errors, []);
  });

  it('G-09: a restart over the same store shows the same counters, best and budget, with no duplicate dispatch', async () => {
    await openVersions();
    const experimentsBefore = await section('성장 실험').textContent();
    const roundsBefore = await section('비교 라운드').textContent();
    const stateBefore = (await api('')).body.state;
    await terminateOwnedChild(server, { graceMs: 5000, forceMs: 2000, label: 'Growth fixture' });
    ({ child: server } = await start(['--resume', '--port', String(port)]));
    const resumed = JSON.parse(await readFile(join(dir, 'growth-resume.json'), 'utf8'));
    assert.equal(resumed.evidence_label, 'synthetic/test-actor');
    // the restart added no round and no loop revision: nothing was dispatched again
    assert.deepEqual(resumed.after, resumed.before);
    for (const lineage of [PLATEAU, BELOW, OLD, NEW]) {
      const { loop_heads: _heads, round_ids: _ids, validities: _validities, baseline_runs: _runs, ...stored } = seed.lineages[lineage];
      assert.deepEqual(resumed.lineages[lineage].resumed, stored);
    }
    assert.match(resumed.lineages[NEW].late_duplicate, /^refused: a round result can never apply twice/);
    assert.match(resumed.lineages[NEW].fork, /^refused: this revision was already written with different content/);
    await openVersions().catch(async () => {
      // a restart may end the browser session; the owner signs in again
      const login = await page.evaluate(async base => (await fetch(base + 'session/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ login_name: 'owner', password: 'synthetic owner passphrase' }) })).status, base);
      assert.equal(login, 200);
      await openVersions();
    });
    assert.equal(await section('성장 실험').textContent(), experimentsBefore);
    assert.equal(await section('비교 라운드').textContent(), roundsBefore);
    assert.deepEqual((await api('')).body.state, stateBefore);
    // an approval applied before the restart is still consumed after it
    const consumed = approvals.find(item => item.candidate_bundle_ref.id === seed.candidates.R.bundle_ref.id);
    const again = await api('/activate', { approval_ref: consumed.approval_ref, expected_revision: stateBefore.revision });
    assert.equal(again.status, 409);
    assert.deepEqual(errors, []);
  });
});
