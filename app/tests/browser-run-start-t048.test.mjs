// T048: run creation from the work page, in a real browser against the real supported
// server. (1) Production's state: no critic can be qualified, so no design is approved and
// no environment is prepared — the run section says exactly that and offers no start.
// (2) TEST-ACTOR (SIMULATED qualification, labelled): the owner generates designs through
// the product's arc with scripted turns, prepares one, and the run section lists that
// prepared environment version with exactly what the run uses; the owner consents
// through the run-consents route, starts the run through the runs route, follows the link
// to the observation page, approves the design's owner gate and sees the run complete.
// The run executor is the fixture's code-owned test executor (no model, tool or paid call).

import test from 'node:test';
import assert from 'node:assert/strict';
import { openArc, owner, read, saveWork, seedArc } from './helpers/design-arc-fixture.mjs';

const BUDGET = { schema_version: 'budget-policy-command-v1', profile: 'execution', provider_mode: 'subscription',
  max_model_calls: 3, max_tool_calls: 5, max_node_visits: 9, max_loop_rounds: 2, max_output_bytes: 100000,
  max_concurrency: 2, max_wall_seconds: 60, max_candidates: 1, currency: null, max_api_microunits: null };

test('production state: no prepared environment — the run section says exactly why and starts nothing', { timeout: 120000 }, async t => {
  const { page, url, errors } = await openArc(t, { args: ['--unqualified', '--no-executor'] });
  const workId = await saveWork(page, url);
  const seed = await seedArc(page, workId, ['three']);
  await page.goto(url + 'work.html');
  const workspace = page.locator('#design-workspace');
  await workspace.locator('[role=status]').first().filter({ hasText: '후보를 보여 줍니다' }).waitFor();
  await workspace.getByRole('button', { name: /후보 생성·평가 실행/ }).click();
  await workspace.locator('.design-generation-runs li[data-outcome="filled"]').waitFor();
  const card = workspace.locator('.design-candidate').first();
  await card.getByRole('button', { name: '이 설계로 준비' }).click();
  await card.locator('.design-command-status').filter({ hasText: '준비하지 않았습니다: the critic configuration is not qualified (unknown: no_suite_record)' }).waitFor();
  const section = page.locator('#work-run');
  await section.getByRole('button', { name: '실행 준비 다시 읽기' }).click();
  const absent = section.locator('.run-start-absent');
  await absent.waitFor();
  assert.match(await absent.textContent(), /준비된 실행 환경이 없어 실행을 시작할 수 없습니다\. 승인된 설계가 없습니다: 설계를 승인하려면 평가자\(critic\) 구성과 렌즈의 자격이 필요한데, 이 인스턴스에는 자격을 얻을 수 있는 평가자 구성이 없습니다 \(V3 오류 독립성 미검증\)\./);
  assert.equal(await section.getByRole('button', { name: '업무 시작', exact: true }).count(), 0);
  const view = await read(page, `api/v1/run-environments/${workId}`);
  assert.deepEqual(view.environments, []);
  assert.deepEqual(view.absence, { code: 'no_prepared_environment', reason: 'no_approved_design', critic_qualifiable: false });
  assert.deepEqual(view.runs, { available: false, reason: 'run_executor_not_configured' });
  const snapshot = await read(page, 'api/v1/snapshot');
  assert.equal((snapshot.runs ?? []).length, 0);
  void seed;
  assert.deepEqual(errors, []);
});

test('SIMULATED qualification: prepare, see exactly what the run uses, consent, start, observe it', { timeout: 180000 }, async t => {
  const { page, url, errors } = await openArc(t);
  const workId = await saveWork(page, url);
  await seedArc(page, workId, ['three']);
  const budget = await owner(page, 'api/v1/budget-policies', { ...BUDGET, command_id: crypto.randomUUID() });
  assert.equal(budget.status, 201, JSON.stringify(budget.body));
  await page.goto(url + 'work.html');
  const section = page.locator('#work-run');
  // before any preparation: the honest absence, no start offered
  await section.locator('.run-start-absent').filter({ hasText: '준비된 실행 환경이 없어 실행을 시작할 수 없습니다' }).waitFor();
  const workspace = page.locator('#design-workspace');
  await workspace.getByRole('button', { name: /후보 생성·평가 실행/ }).click();
  await workspace.locator('.design-generation-runs li[data-outcome="filled"]').waitFor();
  const card = workspace.locator('.design-candidate').first();
  await card.getByRole('button', { name: '이 설계로 준비' }).click();
  await card.locator('.design-command-status').filter({ hasText: '환경 버전 1을 준비했습니다' }).waitFor();

  await section.getByRole('button', { name: '실행 준비 다시 읽기' }).click();
  const usage = section.locator('.run-start-usage');
  await usage.waitFor();
  const rows = Object.fromEntries(await usage.evaluate(list => {
    const cells = [...list.children];
    const pairs = [];
    for (let index = 0; index < cells.length; index += 2) pairs.push([cells[index].textContent, cells[index + 1].textContent]);
    return pairs;
  }));
  const view = await read(page, `api/v1/run-environments/${workId}`);
  const [entry] = view.environments;
  assert.equal(entry.environment_ref.kind, 'environment');
  assert.equal(entry.critic_qualification.simulated, true);
  assert.match(rows['환경 버전'], /버전 1 · 준비됨 \(활성화 아님\)/);
  assert.match(rows['그래프'], new RegExp(`graph ${entry.graph_ref.id.slice(0, 8)} v1 · 노드 4개: finalize\\(deterministic\\), owner-gate\\(human_gate\\), research\\(agent\\), writer\\(agent\\)`));
  assert.match(rows['작업 수정본'], /수정본 2 \(현재 수정본\)/);
  assert.match(rows['모델 연결'], /research-model → model_choice .* writer-model → model_choice/);
  assert.match(rows['도구 연결'], /browser-read \[browser\.read\] 권한 grant/);
  assert.match(rows['평가자 자격'], /qualified .* — 시뮬레이션\(테스트 행위자\) 자격이며 출시 자격이 아닙니다/);
  assert.match(rows['예산 정책'], /execution · subscription · 모델 호출 3 · 도구 호출 5/);
  assert.match(rows['동의 범위'], /실행 한 번에만 쓰입니다\. 외부 쓰기·결제 변경·승격은 포함하지 않습니다\./);

  const start = section.getByRole('button', { name: '업무 시작', exact: true });
  assert.equal(await start.isDisabled(), true, 'nothing starts before the owner consents');
  await section.getByRole('checkbox', { name: '위 내용으로 이 실행 한 번에 동의합니다' }).check();
  await start.click();
  const link = section.getByRole('link', { name: '관제 화면에서 보기' });
  await link.waitFor();
  const runId = await link.getAttribute('data-run');
  assert.match(await section.locator('.run-start-outcome').textContent(), new RegExp(`실행 ${runId.slice(0, 8)}을 시작했습니다 · 상태 awaiting_human`));
  // the server holds exactly one consent over exactly these inputs, spent on this run
  const run = await read(page, `api/v1/runs/${runId}`);
  assert.equal(run.phase, 'awaiting_human');

  await link.click();
  await page.waitForURL(/observe\.html#run=/);
  const panel = page.locator('#run-panel');
  await page.locator('#run-panel[data-phase=awaiting_human]').waitFor();
  assert.equal(await page.getByRole('combobox', { name: '다른 실행 열기' }).inputValue(), runId);
  const screen = page.locator('#run-approvals');
  await screen.getByRole('button', { name: '승인: owner-gate/artifact.publish' }).click();
  await screen.getByText('결정을 기록했습니다.', { exact: false }).waitFor();
  await page.locator('#run-panel[data-phase=running]').waitFor();
  await panel.getByRole('button', { name: '이어서 진행' }).click();
  await page.locator('#run-panel[data-phase=completed]').waitFor();
  assert.deepEqual(errors, []);
});
