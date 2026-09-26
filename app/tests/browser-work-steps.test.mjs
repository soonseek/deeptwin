// UI phase 5 (docs/ui/2026-09-26-product-ux-redesign.md §5.1, experience.md UX-D06): the work page
// as one stepped surface, in a real browser against the real supported server.
// (1) Production's design state (`--design-source none`: no lens is qualified): a new work goes
//     ① description → `업무 이해하기` (one synthetic work model over a mocked Claude transport; no
//     network, key or paid call) → the owner accepts it → step ③ states its honest refusal with the
//     server's own reason folded under "기술 정보", and offers no button.
// (2) TEST-ACTOR, SIMULATED qualification (labelled), as browser-run-start-t048: the scripted design
//     arc over the saved work, `이 설계로 준비`, then step ④ with exactly what the run uses and the
//     simulated label, the explicit consent and `업무 시작`.
// At every point only the reached steps are drawn, plus exactly one next step.

import test from 'node:test';
import assert from 'node:assert/strict';
import { openArc, owner, saveWork, seedArc } from './helpers/design-arc-fixture.mjs';

const BUDGET = { schema_version: 'budget-policy-command-v1', profile: 'execution', provider_mode: 'subscription',
  max_model_calls: 3, max_tool_calls: 5, max_node_visits: 9, max_loop_rounds: 2, max_output_bytes: 100000,
  max_concurrency: 2, max_wall_seconds: 60, max_candidates: 1, currency: null, max_api_microunits: null };

// the drawn steps and their states, e.g. { describe: 'current', understand: 'next' }
async function drawn(page) {
  return page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#work-steps > .work-step')]
    .filter(step => !step.hidden).map(step => [step.dataset.step, step.dataset.state])));
}

async function settledSteps(page, expected) {
  await page.waitForFunction(want => {
    const shown = Object.fromEntries([...document.querySelectorAll('#work-steps > .work-step')]
      .filter(step => !step.hidden).map(step => [step.dataset.step, step.dataset.state]));
    return JSON.stringify(shown) === JSON.stringify(want);
  }, expected);
  const states = await drawn(page);
  assert.equal(Object.values(states).filter(state => state === 'next').length <= 1, true, 'one next step at most');
  return states;
}

test('production: a new work is understood and accepted, then the design step says why it cannot run', { timeout: 120000 }, async t => {
  const { page, url, errors } = await openArc(t, { args: ['--design-source', 'none'] });
  const key = await owner(page, 'api/v1/connections/claude/key', { secret: 'sk-ant-api03-test-only-never-real' });
  const catalog = await owner(page, 'api/v1/connections/claude/catalog', {});
  assert.deepEqual([key.status, catalog.status], [200, 200]);
  await page.goto(url + 'work.html');
  await page.locator('#work-form:not([hidden])').waitFor();
  // a new work: step ① and the next step only, which names its action and says why it waits
  assert.deepEqual(await settledSteps(page, { describe: 'current', understand: 'next' }),
    { describe: 'current', understand: 'next' });
  const understand = page.locator('#step-understand');
  assert.match(await understand.locator('.step-next-action').textContent(), /다음 할 일\s*업무 이해하기/);
  assert.equal(await understand.getByRole('button', { name: '업무 이해하기' }).count(), 0, 'nothing to understand yet');
  assert.match(await understand.textContent(), /먼저 설명을 저장해야 작업 모델을 만들 수 있습니다/);
  assert.equal(await page.locator('#work-side').isHidden(), true, 'an unsaved work has no runs or work menu');
  assert.equal(await page.locator('#source-readings').isHidden(), true);

  // ① description and a material, saved
  await saveWork(page, url);
  await settledSteps(page, { describe: 'current', understand: 'next' });
  assert.equal(await page.locator('#work-side').isVisible(), true);
  assert.equal(await page.locator('#work-records-fold').evaluate(node => node.open), false, 'export is folded away');

  // ② 업무 이해하기: the single call to action, then the draft and its acceptance
  await understand.getByRole('button', { name: '업무 이해하기', exact: true }).click();
  await understand.getByRole('button', { name: '이 작업 모델 수락', exact: true }).click();
  await understand.getByText('이 작업 모델을 수락했습니다.').first().waitFor();
  await settledSteps(page, { describe: 'complete', understand: 'complete', design: 'next' });

  // after a reload: ① and ② fold to one line each, ③ is the next step with its honest refusal
  await page.reload();
  await page.locator('#step-understand[data-folded="true"]').waitFor();
  assert.deepEqual(await settledSteps(page, { describe: 'complete', understand: 'complete', design: 'next' }),
    { describe: 'complete', understand: 'complete', design: 'next' });
  assert.equal(await page.locator('#step-describe').getAttribute('data-folded'), 'true');
  assert.match(await page.locator('#step-describe .step-summary').textContent(), /수정본 \d+ 저장됨 · 자료 1개 · 읽지 않음 1/);
  assert.match(await understand.locator('.step-summary').textContent(), /^작업 모델 수락함 · 수정본 \d+ 기준/);
  assert.equal(await page.locator('#step-understand-body').isHidden(), true);
  const design = page.locator('#step-design');
  assert.match(await design.locator('.step-next-action').textContent(), /환경 제안받기/);
  const refusal = design.locator('[data-state="not_designable"]');
  await refusal.waitFor();
  assert.equal(await refusal.textContent(), '이 인스턴스에서는 설계 요청을 만들 수 없습니다. 자격을 갖춘 렌즈 결정이 없기 때문입니다.');
  const technical = design.locator('.design-create-reason');
  assert.equal(await technical.evaluate(node => node.open), false, 'the server reason is folded under 기술 정보');
  assert.match(await technical.textContent(), /사유: no qualified lens decision exists for this work model/);
  assert.equal(await design.getByRole('button').count(), 0, 'no design action is offered');
  assert.equal(await page.locator('#step-start').isHidden(), true, 'a step beyond the next one is not drawn');
  // the folded step opens again
  await understand.getByRole('button', { name: '업무 이해 펼치기' }).click();
  await understand.getByText('이 작업 모델을 수락했습니다.').first().waitFor();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.deepEqual(errors, []);
});

test('SIMULATED qualification: the steps lead from the design to 업무 시작 with exactly what the run uses', { timeout: 180000 }, async t => {
  const { page, url, errors } = await openArc(t);
  const workId = await saveWork(page, url);
  await seedArc(page, workId, ['three']);
  const budget = await owner(page, 'api/v1/budget-policies', { ...BUDGET, command_id: crypto.randomUUID() });
  assert.equal(budget.status, 201, JSON.stringify(budget.body));
  await page.goto(url + 'work.html');
  // the test actor's design request is this work's: ③ is reached (② was skipped by the seed and
  // is not drawn, and ① counts as done), and ④ is the next step, saying why it cannot start yet
  assert.deepEqual(await settledSteps(page, { describe: 'complete', design: 'current', start: 'next' }),
    { describe: 'complete', design: 'current', start: 'next' });
  const start = page.locator('#step-start');
  assert.match(await start.locator('.step-next-action').textContent(), /업무 시작/);
  await start.locator('.run-start-absent').filter({ hasText: '준비된 실행 환경이 없어 실행을 시작할 수 없습니다' }).waitFor();
  assert.equal(await start.getByRole('button', { name: '업무 시작', exact: true }).count(), 0);
  const design = page.locator('#design-workspace');
  await design.getByRole('button', { name: /후보 생성·평가 실행/ }).click();
  await design.locator('.design-generation-runs li[data-outcome="filled"]').waitFor();
  assert.match(await design.locator('.design-qualification').textContent(), /시뮬레이션\(테스트 행위자\) 자격이며 출시 자격이 아닙니다/);
  const card = design.locator('.design-candidate').first();
  await card.getByRole('button', { name: '이 설계로 준비' }).click();
  await card.locator('.design-command-status').filter({ hasText: '환경 버전 1을 준비했습니다' }).waitFor();
  // preparing reaches ④ on its own: ③ is complete (it stays open in front of the owner), no next step remains
  await settledSteps(page, { describe: 'complete', design: 'complete', start: 'current' });
  const usage = start.locator('.run-start-usage');
  await usage.waitFor();
  assert.match(await usage.textContent(), /평가자 자격qualified .* — 시뮬레이션\(테스트 행위자\) 자격이며 출시 자격이 아닙니다/);
  assert.match(await usage.textContent(), /동의 범위.*실행 한 번에만 쓰입니다\. 외부 쓰기·결제 변경·승격은 포함하지 않습니다\./);
  const go = start.getByRole('button', { name: '업무 시작', exact: true });
  assert.equal(await go.isDisabled(), true, 'nothing starts before the owner consents');
  await start.getByRole('checkbox', { name: '위 내용으로 이 실행 한 번에 동의합니다' }).check();
  await go.click();
  const link = start.getByRole('link', { name: '관제 화면에서 보기' });
  await link.waitFor();
  const runId = await link.getAttribute('data-run');
  // this work's runs list the new run and link to its detail; after a reload the finished steps fold
  await page.locator(`#work-runs li[data-run-id="${runId}"] a`).waitFor();
  assert.equal(await page.locator(`#work-runs li[data-run-id="${runId}"] a`).getAttribute('href'), `./observe.html#run=${runId}`);
  await page.reload();
  await settledSteps(page, { describe: 'complete', design: 'complete', start: 'complete' });
  assert.equal(await page.locator('#step-design').getAttribute('data-folded'), 'true');
  assert.match(await page.locator('#step-start .step-summary').textContent(), /준비된 환경 1개 · 시작한 실행 1개/);
  await page.locator(`#work-runs li[data-run-id="${runId}"] a`).click();
  await page.waitForURL(/observe\.html#run=/);
  await page.locator(`#run-panel[data-run-id="${runId}"]`).waitFor({ state: 'attached' });
  assert.deepEqual(errors, []);
});

test('with several saved works, a switcher and "새 업무" change the work only when nothing here is unsaved', { timeout: 120000 }, async t => {
  const { page, url, errors } = await openArc(t, { args: ['--design-source', 'none'] });
  await saveWork(page, url);
  const switcher = page.locator('#work-switcher');
  // one saved work: only "새 업무"
  await switcher.getByRole('button', { name: '새 업무' }).waitFor();
  assert.equal(await switcher.getByRole('combobox').count(), 0);
  await switcher.getByRole('button', { name: '새 업무' }).click();
  await page.waitForFunction(() => document.querySelector('#work-form') && !document.querySelector('#work-form').hidden
    && document.querySelector('#work-description')?.value === '' && !document.querySelector('#work-side')?.checkVisibility());
  await settledSteps(page, { describe: 'current', understand: 'next' });
  const select = switcher.getByRole('combobox', { name: '다른 업무 열기' });
  await select.waitFor();
  assert.equal(await select.inputValue(), '');
  // a second work, saved: the switcher lists both, the current one chosen
  await page.locator('#work-description').fill('두 번째 합성 업무: 회의록 요약');
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.locator('#save-status[data-state="saved"]').waitFor();
  const second = await page.evaluate(key => JSON.parse(localStorage.getItem(key)).work_id, `deeptwin:intake:/${'2'.repeat(32)}/`);
  // the switcher is read again for the work just saved: both works, the new one chosen
  await page.waitForFunction(id => document.querySelector('#work-switch')?.value === id, second);
  assert.equal(await select.locator('option').count(), 2);
  const labels = await select.locator('option').allTextContents();
  assert.ok(labels.some(text => text.startsWith('두 번째 합성 업무: 회의록 요약')), labels.join());
  assert.ok(labels.some(text => text.startsWith('유튜브 대본을 조사·작성·검토하는 합성 업무')), labels.join());
  const first = await select.locator('option').evaluateAll((options, id) => options.find(option => option.value !== id).value, second);
  // an unsaved edit keeps the work: the switch is refused and said so
  await page.locator('#work-description').fill('두 번째 합성 업무: 회의록 요약 (고치는 중)');
  await select.selectOption(first);
  await switcher.getByText('저장하지 않은 입력이나 전송 중인 자료가 있어 업무를 바꾸지 않았습니다', { exact: false }).waitFor();
  assert.equal(await select.inputValue(), second);
  assert.equal(await page.locator('#work-description').inputValue(), '두 번째 합성 업무: 회의록 요약 (고치는 중)');
  // back to the saved text: the switch opens the other work
  await page.locator('#work-description').fill('두 번째 합성 업무: 회의록 요약');
  await select.selectOption(first);
  await page.waitForFunction(() => document.querySelector('#work-description')?.value.startsWith('유튜브 대본'));
  assert.equal(await page.evaluate(key => JSON.parse(localStorage.getItem(key)).work_id, `deeptwin:intake:/${'2'.repeat(32)}/`), first);
  assert.deepEqual(errors, []);
});
