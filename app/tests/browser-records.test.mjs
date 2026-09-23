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
