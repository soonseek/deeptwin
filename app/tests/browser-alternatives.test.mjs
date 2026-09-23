// T054 (US4, SC-006): the owner's own version in a real browser against the real
// supported server. A run that produced a text and a CSV artifact is started through
// the owner's own consent and run routes; the observe page lists its artifacts; the
// in-place editor autosaves revisions, switches between the original, the owner's
// version and the observed differences, survives a page refresh, and recovers from a
// stale tab's conflicting save (reload the newer revision, or keep the text as a new
// draft) without ever overwriting. Everything the owner "types" here is a scripted
// test actor: this is synthetic evidence of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { base, open, openEditor, saved } from './helpers/alternatives-fixture.mjs';

test('three views, autosave, refresh and freeze on a real run artifact', { timeout: 90000 }, async t => {
  const { page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId);
  const area = page.getByRole('textbox', { name: '내 버전 텍스트' });
  assert.equal(await area.inputValue(), '첫 줄\n둘째 줄\n셋째 줄\n');
  await area.fill('첫 줄\n고친 둘째 줄\n셋째 줄\n');
  await saved(page, 1);
  // the original view is the recorded artifact, read-only
  await page.getByRole('button', { name: '원본', exact: true }).click();
  assert.equal(await page.getByRole('button', { name: '원본', exact: true }).getAttribute('aria-pressed'), 'true');
  assert.equal(await page.locator('#run-alternative pre').textContent(), '첫 줄\n둘째 줄\n셋째 줄\n');
  assert.equal(await page.getByRole('textbox', { name: '내 버전 텍스트' }).count(), 0);
  // the differences view is what the framework observed on the saved revision
  await page.getByRole('button', { name: '차이', exact: true }).click();
  await page.getByText('수정본 1에서 관측한 차이 1개', { exact: false }).waitFor();
  assert.match(await page.locator('#run-alternative').textContent(), /원본 2–2행이 대안 2–2행으로 바뀌었다/);
  await page.getByRole('button', { name: '내 버전', exact: true }).click();
  assert.equal(await area.inputValue(), '첫 줄\n고친 둘째 줄\n셋째 줄\n');
  // a refresh resumes the saved revision from the server, not from the page
  await openEditor(page, url, runId);
  await page.getByText('저장된 내 버전을 이어서 편집합니다. (수정본 1)').waitFor();
  assert.equal(await page.getByRole('textbox', { name: '내 버전 텍스트' }).inputValue(), '첫 줄\n고친 둘째 줄\n셋째 줄\n');
  // freezing is explicit; the changed line alone is the evidence
  await page.getByRole('button', { name: '분석용으로 고정' }).click();
  await page.getByText('바꾼 부분 1곳을 내 근거로 기록했습니다.', { exact: false }).waitFor();
  assert.deepEqual(errors, []);
});

test('a stale tab never overwrites: reload the newer revision or keep the text as a new draft', { timeout: 90000 }, async t => {
  const { context, page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId);
  const first = page.getByRole('textbox', { name: '내 버전 텍스트' });
  await first.fill('A의 첫 수정\n');
  await saved(page, 1);
  const other = await context.newPage();
  await openEditor(other, url, runId);  // both tabs now edit from revision 1
  await first.fill('A의 둘째 수정\n');
  await saved(page, 2);
  const second = other.getByRole('textbox', { name: '내 버전 텍스트' });
  await second.fill('B의 늦은 수정\n');
  await other.getByText('다른 화면에서 이 버전을 먼저 저장했습니다.', { exact: false }).waitFor();
  assert.equal(await second.inputValue(), 'B의 늦은 수정\n');  // the owner's text is kept
  await other.getByRole('button', { name: '지금 내용을 새 초안으로 저장' }).click();
  await saved(other, 1);  // a new draft of its own, revision 1
  // the first draft still holds A's revision 2: nothing was overwritten
  await openEditor(page, url, runId);
  const listed = await page.evaluate(async ({ base, runId }) => {
    const artifacts = await (await fetch(`${base}api/v1/runs/${runId}/artifacts`)).json();
    const report = artifacts.artifacts.find(item => item.role === 'report');
    return (await fetch(`${base}api/v1/runs/${runId}/artifacts/${report.artifact_id}/drafts`)).json();
  }, { base, runId });
  assert.deepEqual(listed.drafts.map(item => item.revision).sort(), [1, 2]);
  // a stale tab can instead reload the newer revision
  const third = await context.newPage();
  await openEditor(third, url, runId);
  await page.getByRole('textbox', { name: '내 버전 텍스트' }).fill('B 초안의 새 수정\n');
  await saved(page, 2);
  await third.getByRole('textbox', { name: '내 버전 텍스트' }).fill('낡은 탭의 수정\n');
  await third.getByRole('button', { name: '최신 수정본 불러오기' }).click();
  await third.getByText('(수정본 2)', { exact: false }).waitFor();
  assert.equal(await third.getByRole('textbox', { name: '내 버전 텍스트' }).inputValue(), 'B 초안의 새 수정\n');
  assert.deepEqual(errors, []);
});

test('a table is edited cell by cell with the keyboard', { timeout: 90000 }, async t => {
  const { page, url, errors, runId } = await open(t);
  await openEditor(page, url, runId, 'table');
  const cell = page.getByRole('textbox', { name: '2행 2열' });
  await cell.focus();
  await page.keyboard.press('Control+A');
  await page.keyboard.type('10');
  await saved(page, 1);
  await page.getByRole('button', { name: '차이', exact: true }).click();
  await page.getByText('원본 2행 2열과 대안 2행 2열의 값이 다르다.', { exact: false }).waitFor();
  assert.deepEqual(errors, []);
});
