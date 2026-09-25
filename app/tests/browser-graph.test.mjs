// T037/T048: the selected run's work graph in a real browser against the real supported
// server — every node drawn with its recorded state, and a selected node's details.
// Synthetic test-actor run (the alternatives fixture's code-owned executor).

import test from 'node:test';
import assert from 'node:assert/strict';
import { open } from './helpers/alternatives-fixture.mjs';

test('the observe page draws the selected run graph with its recorded node states', { timeout: 90000 }, async t => {
  const { page, url, errors, runId } = await open(t);
  await page.goto(url + 'observe.html');
  await page.getByRole('combobox', { name: '관제할 실행 선택' }).selectOption(runId);
  const graph = page.locator('#run-graph');
  await graph.getByText('노드 3개 · 연결 2개', { exact: false }).waitFor();
  const labels = await graph.locator('.graph-nodes button').allTextContents();
  assert.deepEqual(labels, ['intake · 정해진 처리 · 완료', 'writer · 에이전트 · 완료', 'publish · 정해진 처리 · 완료']);
  assert.equal(await graph.locator('svg .graph-node').count(), 3);
  assert.equal(await graph.locator('svg .graph-edge').count(), 2);
  await graph.getByRole('button', { name: 'writer · 에이전트 · 완료' }).click();
  const details = await graph.locator('.graph-details').textContent();
  assert.match(details, /책임전체 초안을 만든다/);
  assert.match(details, /모델model_choice:/);
  assert.deepEqual(errors, []);
});
