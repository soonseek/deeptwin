// T038 (SC-003/SC-005): generation → criticism → selection in a real browser against the
// real supported server, on the work page's design workspace. The owner saves a real work;
// the fixture registers TEST-ACTOR design requests over it whose model turns are scripted
// (`test-actor-generator`, `test-actor-critic`) and whose critic qualification is a
// SIMULATED test-actor record (labelled on the page, never a release qualification). The
// product's own arc then runs from the page: 0, 1, 2 and 3 presented candidates with the
// real count and every exclusion reason, a refused model call recorded as a refusal, an
// edit realized by a revision call and re-reviewed from scratch, preparation of the
// re-reviewed version, and the owner's cancel stopping the arc before its next model call.
// No fixture verdict is presented as live: every verdict names its scripted critic.

import test from 'node:test';
import assert from 'node:assert/strict';
import { openArc, read, saveWork, seedArc } from './helpers/design-arc-fixture.mjs';

async function choose(workspace, requestId) {
  await workspace.getByRole('combobox', { name: '설계 요청 선택' }).selectOption(requestId);
  await workspace.locator('[role=status]').first().filter({ hasText: `설계 요청 ${requestId.slice(0, 8)}의 후보를 보여 줍니다` }).waitFor();
}

async function generate(workspace, outcome) {
  await workspace.getByRole('button', { name: /후보 생성·평가 실행/ }).click();
  const recorded = workspace.locator(`.design-generation-runs li[data-outcome="${outcome}"]`);
  await recorded.waitFor({ timeout: 30000 });
  return recorded.textContent();
}

test('0/1/2/3 presented, a refused call, an edit re-reviewed and prepared, and cancel — in the real browser', { timeout: 240000 }, async t => {
  const { page, url, errors } = await openArc(t);
  const workId = await saveWork(page, url);
  const seed = await seedArc(page, workId);
  assert.match(seed.simulation.label, /SIMULATED \(test-actor\)/);
  await page.goto(url + 'work.html');
  const workspace = page.locator('#design-workspace');
  await workspace.locator('[role=status]').first().filter({ hasText: '후보를 보여 줍니다' }).waitFor();
  const pool = workspace.locator('.design-pool');

  // before any generation: nothing presented, the arc offered with the scripted turns named
  await choose(workspace, seed.requests.zero);
  assert.match(await workspace.locator('.design-generation').textContent(), /생성자 test-actor-generator · 평가자 test-actor-critic/);
  assert.match(await pool.locator('.design-qualification').textContent(),
    /자격 있음 \(qualified: .*\) — 시뮬레이션\(테스트 행위자\) 자격이며 출시 자격이 아닙니다\..*실시간 평가가 아닙니다/);

  // 0 valid: a malformed answer (refused) and two defective graphs rejected — an honest shortfall
  const zero = await generate(workspace, 'shortfall');
  assert.match(zero, /통과한 구조적으로 다른 후보가 0개뿐입니다 \(생성 3회 한도\)\. 채워 넣지 않았습니다\./);
  assert.match(zero, /거절된 호출 1개: 1회차 생성 — model response is not valid JSON/);
  assert.match(await pool.locator('.design-pool-count').textContent(), /후보 0개를 제시합니다 \(기본 3안\) — 3개를 채우지 못했습니다.*전체 후보 2개 · 통과 0개/);
  assert.equal(await pool.locator('.design-candidate').count(), 0);
  const rejected = await pool.locator('.design-exclusions li').allTextContents();
  assert.equal(rejected.length, 2);
  for (const text of rejected) assert.match(text, /필수 결함으로 탈락 \(review_fail:/);
  assert.match(await workspace.locator('.design-compare').textContent(), /비교하려면 제시된 후보가 두 개 이상 있어야 합니다/);

  // 1 valid: one passed graph, then only structural duplicates
  await choose(workspace, seed.requests.one);
  const one = await generate(workspace, 'shortfall');
  assert.match(one, /후보가 1개뿐입니다 \(생성 3회 한도\)/);
  assert.equal(await pool.locator('.design-candidate').count(), 1);
  const duplicates = await pool.locator('.design-exclusions li').allTextContents();
  assert.equal(duplicates.length, 2);
  for (const text of duplicates) assert.match(text, /이미 제시된 후보와 구조가 같습니다/);

  // 2 valid
  await choose(workspace, seed.requests.two);
  assert.match(await generate(workspace, 'shortfall'), /후보가 2개뿐입니다/);
  assert.equal(await pool.locator('.design-candidate').count(), 2);
  assert.equal(await workspace.locator('.design-compare-side').count(), 2);

  // 3 valid in one round; every verdict is the scripted critic's recorded one
  await choose(workspace, seed.requests.three);
  assert.match(await generate(workspace, 'filled'), /^기본 3안을 채웠습니다 \(생성 1회\)\. 후보 3개 · 모델 호출 7회/);
  const cards = pool.locator('.design-candidate');
  assert.equal(await cards.count(), 3);
  for (const text of await cards.locator('.design-verdict').allTextContents()) {
    assert.match(text, /기록된 평가: 통과 · 평가자 test-actor-critic/);
  }
  assert.match(await pool.locator('.design-pool-count').textContent(), /후보 3개를 제시합니다 \(기본 3안\) 전체 후보 3개/);

  // revision: an edit realized by one revision call, then re-reviewed from scratch
  await cards.nth(0).getByRole('textbox', { name: '후보 1 수정 지시' }).fill('최종 대본 크기 한도를 절반으로 줄인다');
  await cards.nth(0).getByRole('button', { name: '지시대로 수정' }).click();
  const derivation = workspace.locator('.design-derivation', { hasText: '지시 "최종 대본 크기 한도를 절반으로 줄인다"' });
  await derivation.waitFor();
  assert.match(await derivation.textContent(), /재검토 필요 · 원본의 평가·승인은 이어지지 않습니다/);
  const review = derivation.getByRole('button', { name: '재검토' });
  assert.equal(await review.isDisabled(), false);
  await review.click();
  const reviewed = workspace.locator('.design-derivation', { hasText: '기록된 평가: 통과 · 평가자 test-actor-critic' });
  await reviewed.waitFor();
  const stored = (await read(page, `api/v1/design-requests/${seed.requests.three}`)).derivations[0];
  assert.equal(stored.re_review_required, false);
  assert.equal(stored.inherited_verdict, null);
  const parentGraph = (await read(page, `api/v1/design-requests/${seed.requests.three}`)).candidates
    .find(item => item.candidate_id === stored.parent_candidate_ids[0]).graph;
  const size = graph => graph.artifact_contracts.find(item => item.artifact_contract_id === 'final-script').max_total_bytes;
  assert.equal(size(stored.reviewed_candidate.graph), Math.floor(size(parentGraph) / 2));
  // the re-reviewed version is prepared (SIMULATED qualification): prepared, not activated
  await reviewed.getByRole('button', { name: '이 설계로 준비' }).click();
  await reviewed.locator('.design-command-status').filter({ hasText: '환경 버전 1을 준비했습니다. 준비는 활성화가 아니며 작업을 시작하지 않습니다.' }).waitFor();
  // a merge still has no generation turn: its review stays unavailable and says why
  await pool.getByRole('checkbox', { name: '후보 1 합치기에 포함' }).check();
  await pool.getByRole('checkbox', { name: '후보 2 합치기에 포함' }).check();
  await pool.getByRole('button', { name: '선택한 후보 합치기' }).click();
  const merged = workspace.locator('.design-derivation', { hasText: '합치기 · 원본' });
  await merged.waitFor();
  assert.equal(await merged.getByRole('button', { name: '재검토' }).isDisabled(), true);
  assert.match(await merged.locator('.design-review-unavailable').textContent(), /생성 단계가 아직 없어/);

  // cancel: the critic's second candidate waits; the owner cancels; the arc stops before its next call
  await choose(workspace, seed.requests.cancel);
  await workspace.getByRole('button', { name: /후보 생성·평가 실행/ }).click();
  const cancel = workspace.getByRole('button', { name: '생성 취소' });
  assert.equal(await cancel.isDisabled(), false);
  // wait until the first candidate's criticism is recorded (the second is then in its review)
  const deadline = Date.now() + 20000;
  for (;;) {
    const view = await read(page, `api/v1/design-requests/${seed.requests.cancel}`);
    if (view.candidates.filter(item => item.verdict).length === 1 && view.generation.running) break;
    assert.ok(Date.now() < deadline, 'the first criticism is recorded while the arc runs');
    await page.waitForTimeout(100);
  }
  await cancel.click();
  await workspace.locator('.design-generation-status').filter({ hasText: '다음 모델 호출 전에 멈춥니다' }).waitFor();
  const cancelled = await workspace.locator('.design-generation-runs li[data-outcome="cancelled"]').textContent();
  assert.match(cancelled, /소유자가 취소했습니다: 다음 모델 호출 전에 멈췄습니다 \(생성 1회\)\. 평가를 마치지 못한 후보 2개는 제시하지 않습니다\. 후보 3개 · 모델 호출 4회/);
  assert.equal(await pool.locator('.design-candidate').count(), 1);
  const unreviewed = await pool.locator('.design-exclusions li').allTextContents();
  assert.deepEqual(unreviewed.map(text => /아직 평가되지 않았습니다/.test(text)), [true, true]);
  assert.equal((await read(page, `api/v1/design-requests/${seed.requests.cancel}`)).generation.running, false);
  assert.deepEqual(errors, []);
});
