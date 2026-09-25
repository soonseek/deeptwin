// T060 (US5, UX-AC05/07): after a real freeze in a real browser, the observed
// difference is sealed and shown with every unknown stated — no explanation is
// invented, no question is put to the owner, no stand-in answer appears, and the
// unreviewed area and pending impact stay visible. Scripted test actor only.

import test from 'node:test';
import assert from 'node:assert/strict';
import { base, open, openEditor, saved } from './helpers/alternatives-fixture.mjs';

test('a frozen alternative shows its observed difference and no invented explanation or quiz', { timeout: 90000 }, async t => {
  const { page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId);
  await page.getByRole('textbox', { name: '내 버전 텍스트' }).fill('첫 줄\n고친 둘째 줄\n셋째 줄\n');
  await saved(page, 1);
  await page.getByRole('button', { name: '분석용으로 고정' }).click();
  const panel = page.locator('#run-inquiry');
  await panel.getByText('관측된 차이 1개').waitFor();
  const text = await panel.textContent();
  assert.match(text, /원본 2–2행이 대안 2–2행으로 바뀌었다/);
  assert.match(text, /내가 바꾼 1곳이 근거입니다/);
  assert.match(text, /검토하지 않은 영역으로 남고, 영향 범위는 따로 조사합니다/);
  assert.match(text, /소유자가 요청할 때만 Claude 연결로 만든다/);
  assert.match(text, /새로운 조건부 판단: 검토되지 않음/);
  assert.match(text, /질문에 답하도록 요구하지 않습니다/);
  assert.match(text, /변경 후보를 만들지 않았다/);
  // nothing in the panel asks the owner for an answer
  assert.equal(await panel.locator('input, textarea, select').count(), 0);
  // the difference is a sealed record the server reads back the same way after a reload
  const reread = await page.evaluate(async ({ base, runId }) => {
    const artifacts = await (await fetch(`${base}api/v1/runs/${runId}/artifacts`)).json();
    const report = artifacts.artifacts.find(item => item.role === 'report');
    const drafts = await (await fetch(`${base}api/v1/runs/${runId}/artifacts/${report.artifact_id}/drafts`)).json();
    return drafts.drafts[0].frozen_revisions;
  }, { base, runId });
  assert.deepEqual(reread, [1]);
  assert.deepEqual(errors, []);
});
