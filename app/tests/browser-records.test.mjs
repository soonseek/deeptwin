// T074 (US7, SC-009), the parts this server can run today, in a real browser against the
// real supported server: a work saved through the work screen is exported through
// its actual preview and a consent bound to that preview; the downloaded bundle is
// unzipped and checked member by member. Raw text is included only when chosen;
// session secrets (the owner's password, the bootstrap capability, the CSRF token)
// and the canary never cross into a metadata-only bundle; a work revised after its
// preview is refused as stale. The records page lists the vault's public events and
// states honestly that no backup worker is connected. The owner is a scripted test
// actor: synthetic evidence of the mechanism, never user evidence.

import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { open } from './helpers/alternatives-fixture.mjs';

const CANARY = 'CANARY-원문-7f3a9c';
const PASSWORD = 'synthetic owner passphrase';
const CAPABILITY = Buffer.alloc(32, 'T').toString('base64url');

async function unzip(t, bytes) {
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-export-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const file = join(dir, 'bundle.zip');
  await writeFile(file, bytes);
  const listed = spawnSync(process.env.CONTROL_PYTHON, ['-c', `
import json, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    print(json.dumps({info.filename: archive.read(info).decode("utf-8", "replace") for info in archive.infolist()}))
`, file], { encoding: 'utf8' });
  assert.equal(listed.status, 0, listed.stderr);
  return JSON.parse(listed.stdout);
}

async function saveWork(page, url, text) {
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill(text);
  await page.getByRole('button', { name: '이 인스턴스에 저장' }).click();
  await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();
}

async function exportBundle(page, { raw }) {
  const panel = page.locator('#work-records');
  const rawBox = panel.locator('#export-include-raw');
  if ((await rawBox.isChecked()) !== raw) await rawBox.click();
  await panel.getByRole('button', { name: '포함될 내용 미리보기' }).click();
  await panel.locator('#export-consent').waitFor();
  const preview = await panel.locator('.export-preview').textContent();
  await panel.locator('#export-consent').check();
  await panel.getByRole('button', { name: '이 내용으로 내보내기' }).click();
  const link = panel.getByRole('link', { name: '내보낸 묶음 내려받기' });
  await link.waitFor();
  const href = await link.getAttribute('href');
  const digest = (await panel.locator('.export-digest').textContent()).replace('묶음 SHA-256 ', '');
  const bytes = Buffer.from(await page.evaluate(async target => [...new Uint8Array(await (await fetch(target)).arrayBuffer())], href));
  return { preview, bytes, digest, href };
}

test('export: actual preview, bound consent, raw only by choice, no session secret in the bundle', { timeout: 120000 }, async t => {
  const { page, url, errors } = await open(t);
  await saveWork(page, url, `분기 보고서를 정리해 주세요. ${CANARY}`);
  const csrf = await page.evaluate(async base => (await (await fetch(base + 'session')).json()).csrf_token, new URL(url).pathname);

  const metadata = await exportBundle(page, { raw: false });
  assert.match(metadata.preview, /원문 제외\(메타데이터만\)/);
  const { createHash } = await import('node:crypto');
  assert.equal(createHash('sha256').update(metadata.bytes).digest('hex'), metadata.digest);
  const members = await unzip(t, metadata.bytes);
  const all = Object.values(members).join('\n');
  assert.ok(Object.keys(members).length >= 2, JSON.stringify(Object.keys(members)));
  for (const secret of [CANARY, PASSWORD, CAPABILITY, csrf]) assert.ok(!all.includes(secret), `bundle leaked ${secret.slice(0, 8)}`);
  assert.ok(!metadata.bytes.includes(Buffer.from(PASSWORD)) && !metadata.bytes.includes(Buffer.from(CAPABILITY)));

  const withRaw = await exportBundle(page, { raw: true });
  assert.match(withRaw.preview, /원문 포함/);
  const rawAll = Object.values(await unzip(t, withRaw.bytes)).join('\n');
  assert.ok(rawAll.includes(CANARY), 'the chosen raw original is in the bundle');
  for (const secret of [PASSWORD, CAPABILITY, csrf]) assert.ok(!rawAll.includes(secret));
  assert.deepEqual(errors, []);
});

test('export: a work revised after its preview is refused as stale; records page is honest', { timeout: 120000 }, async t => {
  const { context, page, url, errors } = await open(t);
  await saveWork(page, url, '첫 설명');
  const panel = page.locator('#work-records');
  await panel.getByRole('button', { name: '포함될 내용 미리보기' }).click();
  await panel.locator('#export-consent').waitFor();
  // another tab revises the work after this preview
  const other = await context.newPage();
  await other.goto(url + 'work.html');
  await other.locator('#work-description').fill('둘째 설명');
  await other.getByRole('button', { name: '이 인스턴스에 저장' }).click();
  await other.getByText('이 인스턴스에 저장됨 · 수정본 2', { exact: false }).first().waitFor();
  await panel.locator('#export-consent').check();
  await panel.getByRole('button', { name: '이 내용으로 내보내기' }).click();
  await panel.getByText('미리보기 이후 작업이 바뀌었습니다. 다시 미리보기 하세요.', { exact: false }).first().waitFor();
  assert.equal(await panel.getByRole('link', { name: '내보낸 묶음 내려받기' }).count(), 0);

  await page.goto(url + 'records.html');
  const log = page.locator('#records-logs');
  await log.locator('li').first().waitFor();
  assert.match(await log.textContent(), /run\.started/);
  assert.match(await log.textContent(), /approval\.decided/);
  assert.match(await page.locator('#records-backup').textContent(), /백업 워커가 아직 연결되어 있지 않습니다/);
  assert.match(await page.locator('#records-retention').textContent(), /자동 삭제는 없습니다/);
  assert.deepEqual(errors, []);
});

test('an original is deleted only through its preview and consent; readers then say deleted', { timeout: 120000 }, async t => {
  const { page, url, errors } = await open(t);
  await page.goto(url + 'work.html');
  const bytes = Buffer.from('%PDF-1.7\n지울 합성 원본\0');
  await page.getByLabel('원본 자료 선택').setInputFiles({ name: '지울 원본.pdf', mimeType: 'application/pdf', buffer: bytes });
  await page.getByRole('button', { name: '이 인스턴스에 저장', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('#save-status')?.textContent.includes('수정본 2'));
  const panel = page.locator('#work-deletion');
  await panel.getByLabel('지울 원본.pdf', { exact: false }).waitFor();
  const href = await page.getByRole('link', { name: '다운로드' }).getAttribute('href');
  const status = async () => page.evaluate(async target => (await fetch(target)).status, href);
  assert.equal(await status(), 200);
  // a preview removes nothing
  await panel.getByLabel('지울 원본.pdf', { exact: false }).check();
  await panel.getByRole('button', { name: '삭제 미리보기' }).click();
  await panel.getByText('이 삭제 전에 만든 백업', { exact: true }).waitFor();
  assert.match(await panel.textContent(), /이 원본을 가리키는 수정본 1개/);
  assert.equal(await status(), 200);
  // consent is separate and off by default
  await panel.getByRole('button', { name: '선택한 원본 삭제' }).click();
  await panel.getByText('미리보기 내용에 동의해야 삭제할 수 있습니다.').waitFor();
  assert.equal(await status(), 200);
  await panel.locator('#deletion-consent').check();
  await panel.getByRole('button', { name: '선택한 원본 삭제' }).click();
  await panel.getByText('원본 1개를 삭제했고 파일 제거를 확인했습니다', { exact: false }).waitFor();
  assert.match(await panel.textContent(), /지울 원본\.pdf · .* · 삭제됨/);
  assert.equal(await status(), 410);
  // the records log shows the deletion as its own event
  await page.goto(url + 'records.html');
  await page.locator('#records-logs li').first().waitFor();
  assert.match(await page.locator('#records-logs').textContent(), /retention\.deleted/);
  assert.deepEqual(errors, []);
});
