// T038 (FR-005): a design request is created from the work page, from the owner's accepted
// work model, only where a qualified lens decision exists. The real supported server; the
// work model is drafted over a mocked Claude transport (one synthetic work model, no network
// or paid call) and accepted by the owner on the page.
// - `--design-source simulated`: the TEST-ACTOR design source (SIMULATED lens qualification,
//   scripted generator and critic, labelled): the owner creates the request on the page and
//   runs the arc — three presented candidates, every verdict naming the scripted critic.
// - `--design-source none`: production's state — no lens is qualified — and the page states
//   exactly why no request can be created, with no button.

import test from 'node:test';
import assert from 'node:assert/strict';
import { openArc, owner, saveWork } from './helpers/design-arc-fixture.mjs';

async function acceptedWorkModel(page, url) {
  const key = await owner(page, 'api/v1/connections/claude/key', { secret: 'sk-ant-api03-test-only-never-real' });
  const catalog = await owner(page, 'api/v1/connections/claude/catalog', {});
  assert.deepEqual([key.status, catalog.status], [200, 200]);
  await saveWork(page, url);
  const model = page.locator('#work-model');
  await model.getByRole('button', { name: '업무 이해하기', exact: true }).click();
  await model.getByRole('button', { name: '이 작업 모델 수락', exact: true }).click();
  await model.getByText('이 작업 모델을 수락했습니다.').first().waitFor();
}

test('with a simulated qualified lens the owner creates a design request from the work page and generates', { timeout: 120000 }, async t => {
  const { page, url, errors } = await openArc(t, { args: ['--design-source', 'simulated'] });
  const key = await owner(page, 'api/v1/connections/claude/key', { secret: 'sk-ant-api03-test-only-never-real' });
  assert.equal(key.status, 200);
  await saveWork(page, url);
  const workspace = page.locator('#design-workspace');
  const creator = workspace.locator('.design-create');
  // no accepted work model yet: the section says what is missing, and offers nothing. UI phase 5:
  // the design step is not even drawn before understanding is reached (step ② is the next step)
  await creator.getByText('수락한 작업 모델이 있어야 설계 요청을 만들 수 있습니다', { exact: false }).waitFor({ state: 'attached' });
  assert.equal(await creator.getByRole('button', { includeHidden: true }).count(), 0);
  assert.equal(await page.locator('#step-design').isHidden(), true);
  assert.equal(await page.locator('#step-understand').getAttribute('data-state'), 'next');
  const catalog = await owner(page, 'api/v1/connections/claude/catalog', {});
  assert.equal(catalog.status, 200);
  await page.reload();
  const model = page.locator('#work-model');
  await model.getByRole('button', { name: '업무 이해하기', exact: true }).click();
  await model.getByRole('button', { name: '이 작업 모델 수락', exact: true }).click();
  await model.getByText('이 작업 모델을 수락했습니다.').first().waitFor();
  // the lens source is labelled a simulation; the owner creates the request here (the work model's
  // "accepted" line is drawn before the design section re-renders, so wait for the section itself)
  await creator.getByText('SIMULATED lens qualification', { exact: false }).waitFor();
  assert.match(await creator.textContent(), /SIMULATED lens qualification/);
  await creator.getByRole('button', { name: '환경 제안받기', exact: true }).click();
  await workspace.locator('[role=status]').first().filter({ hasText: '을 만들었습니다. 후보는 아직 없습니다.' }).waitFor();
  const pool = workspace.locator('.design-pool');
  assert.match(await pool.locator('.design-pool-count').textContent(), /후보 0개를 제시합니다/);
  assert.match(await workspace.locator('.design-generation').textContent(), /생성자 test-actor-generator · 평가자 test-actor-critic/);
  // the product's own arc from the page
  await workspace.getByRole('button', { name: /후보 생성·평가 실행/ }).click();
  const recorded = workspace.locator('.design-generation-runs li[data-outcome="filled"]');
  await recorded.waitFor({ timeout: 30000 });
  assert.match(await recorded.textContent(), /^기본 3안을 채웠습니다 \(생성 1회\)\. 후보 3개 · 모델 호출 7회/);
  const cards = pool.locator('.design-candidate');
  assert.equal(await cards.count(), 3);
  for (const text of await cards.locator('.design-verdict').allTextContents()) {
    assert.match(text, /기록된 평가: 통과 · 평가자 test-actor-critic/);
  }
  assert.match(await pool.locator('.design-qualification').textContent(), /시뮬레이션\(테스트 행위자\) 자격이며 출시 자격이 아닙니다/);
  // the created request is served again after a reload (from the server, not this page)
  await page.reload();
  await workspace.locator('.design-pool .design-candidate').first().waitFor();
  assert.equal(await workspace.locator('.design-pool .design-candidate').count(), 3);
  assert.deepEqual(errors, []);
});

test('without a qualified lens (production) the work page states exactly why no request can be created', { timeout: 90000 }, async t => {
  const { page, url, errors } = await openArc(t, { args: ['--design-source', 'none'] });
  await acceptedWorkModel(page, url);
  const creator = page.locator('#design-workspace .design-create');
  await creator.locator('[data-state="not_designable"]').waitFor();
  const text = await creator.textContent();
  assert.match(text, /이 인스턴스에서는 설계 요청을 만들 수 없습니다\. 자격을 갖춘 렌즈 결정이 없기 때문입니다\./);
  assert.match(text, /사유: no qualified lens decision exists for this work model: no lens is qualified in this installation \(every lens is a document candidate and no qualification record has been issued\), so a design request cannot be created/);
  assert.equal(await creator.getByRole('button').count(), 0);
  // the route itself refuses the same way (nothing is created behind the page)
  const served = await page.evaluate(async base => {
    const listed = await (await fetch(base + 'api/v1/design-requests')).json();
    return listed.requests.length;
  }, `/${'2'.repeat(32)}/`);
  assert.equal(served, 0);
  assert.deepEqual(errors, []);
});
