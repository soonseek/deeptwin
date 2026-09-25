// T066: the versions page in a real browser against the real supported server. With
// nothing adopted and no persisted candidates or rounds, the page says exactly that —
// every module (versions, experiments, session) loads from the closed asset list and
// no page error occurs. Synthetic test-actor evidence of the wiring only.

import test from 'node:test';
import assert from 'node:assert/strict';
import { open } from './helpers/alternatives-fixture.mjs';

test('the versions page states an empty operating state honestly', { timeout: 90000 }, async t => {
  const { page, url, errors } = await open(t);
  await page.goto(url + 'versions.html');
  const root = page.locator('#versions');
  await root.getByText('운영 버전이 아직 채택되지 않았습니다', { exact: false }).waitFor();
  await root.locator('[role=status][data-state=loaded]').waitFor({ state: 'attached' });
  const text = await root.textContent();
  assert.match(text, /검증을 마친 후보가 없습니다/);
  assert.match(text, /기록된 성장 실험이 없습니다/);
  assert.match(text, /기록된 비교 라운드가 없습니다/);
  assert.match(text, /도구 효과 경계를 정한 비교 계획이 없습니다/);  // G-14: nothing to approve
  assert.equal(await root.getByRole('button', { name: '승인' }).count(), 0);
  assert.deepEqual(errors, []);
});
