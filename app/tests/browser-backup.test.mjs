// T073/T070 in a real browser against the real supported server with a REAL backup-crypto
// worker: the fixture (app/tests/fixtures/backup_server.py) runs the production worker
// entrypoint as a separate process in an empty network namespace under the backup
// identity, holding the read-only backup-key volume, and the supported app under the
// control identity; they speak only over the verified `cp-backup` channel. The owner
// saves a work, opens the records page, sees the ACTUAL backup preview (included
// categories with counts, excluded categories with reasons), consents to exactly that
// preview, creates the backup, downloads the encrypted bundle and its external receipt,
// then restores them through the restore screen and sees the staged `restored_review`
// state with the new-owner bootstrap and explicit environment reactivation shown as
// required. The owner is a scripted test actor: synthetic evidence of the mechanism,
// never user evidence. Needs Linux and root for the fixture's identities; otherwise the
// fixture reports why and this case is skipped with that reason.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { spawn } from 'node:child_process';
import { closeOwnedFixture, waitForOwnedChildOutput } from './helpers/owned-fixture-lifecycle.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
const base = `/${'2'.repeat(32)}/`;
const READY = /BACKUP_WORKER_NETWORKLESS=(true|false)\n(?:[^\n]*\n)*?BACKUP_URL=(http:\/\/[0-9a-f]{32}\.localhost:\d+\/[0-9a-f]{32}\/)/;
const PASSWORD = 'synthetic owner passphrase';
const CAPABILITY = Buffer.alloc(32, 'T').toString('base64url');
const CANARY = 'CANARY-백업-원문-5e1d';
const unavailable = process.platform !== 'linux' || process.getuid?.() !== 0 || !process.env.DEEPTWIN_AGE_RUNTIME_ROOT
  ? 'the real backup worker fixture needs Linux, root and DEEPTWIN_AGE_RUNTIME_ROOT' : false;

async function openBackup(t) {
  assert.ok(process.env.CONTROL_PYTHON && process.env.CONTROL_PLAYWRIGHT_MODULE, 'Controlled installed runtimes required; never skip');
  const dir = await mkdtemp(join(tmpdir(), 'deeptwin-backup-'));
  let server, browser;
  t.after(() => closeOwnedFixture({ browser, server, removeTemp: () => rm(dir, { recursive: true, force: true }) },
    { serverGraceMs: 8000, serverForceMs: 3000, label: 'Backup fixture' }));
  server = spawn(process.env.CONTROL_PYTHON, ['-B', 'app/tests/fixtures/backup_server.py', '--owned-dir', dir],
    { cwd: root, stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, LANGSMITH_TRACING: 'false', LANGCHAIN_TRACING_V2: 'false' } });
  const announced = await waitForOwnedChildOutput(server, { pattern: READY, timeoutMs: 60000, label: 'Backup fixture' });
  const [, networkless, url] = READY.exec(announced);
  const { chromium } = await import(pathToFileURL(process.env.CONTROL_PLAYWRIGHT_MODULE).href);
  browser = await chromium.launch({ channel: 'chrome', headless: true });
  const context = await browser.newContext({ viewport: { width: 1200, height: 1400 }, acceptDownloads: true });
  const page = await context.newPage();
  page.setDefaultTimeout(20000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const bootstrapped = await page.evaluate(async ({ base, capability, password }) => (await fetch(base + 'session/bootstrap', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ login_name: 'owner', password, raw_capability_b64u: capability }),
  })).status, { base, capability: CAPABILITY, password: PASSWORD });
  assert.equal(bootstrapped, 201);
  return { page, url, errors, networkless: networkless === 'true' };
}

async function bytesOf(page, href) {
  return Buffer.from(await page.evaluate(async target => [...new Uint8Array(await (await fetch(target)).arrayBuffer())], href));
}

test('backup: actual preview, bound consent, encrypted bundle + receipt, restore staged for review',
  { timeout: 180000, skip: unavailable }, async t => {
    const { page, url, errors, networkless } = await openBackup(t);
    assert.equal(networkless, true, 'the worker runs in an empty network namespace');
    await page.goto(url + 'work.html');
    await page.locator('#work-description').fill(`백업할 작업 설명입니다. ${CANARY}`);
    await page.getByRole('button', { name: '이 인스턴스에 저장' }).click();
    await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();

    await page.goto(url + 'records.html');
    const panel = page.locator('#records-backup');
    await panel.locator('.backup-worker[data-state="ready"]').waitFor();
    assert.match(await panel.textContent(), /백업 키는 네트워크가 없는 워커에만 있고/);
    await panel.getByRole('button', { name: '백업에 포함될 내용 미리보기' }).click();
    await panel.locator('#backup-consent').waitFor();
    const preview = await panel.locator('.backup-preview').textContent();
    assert.match(preview, /기록과 계보 \d+행/);
    assert.match(preview, /작업 이력|기록과 계보/);
    assert.match(preview, /소유자 인증 수단·세션·초기 설정 검증값: 인증 수단은 복원하지 않습니다/);
    assert.match(preview, /제공자 자격증명 저장소: 별도 비공개 저장소라 백업하지 않습니다/);
    assert.match(preview, /백업 키 볼륨: 별도 비공개 저장소라 백업하지 않습니다/);
    assert.ok(!preview.includes(CANARY), 'the preview counts content, never shows it');
    const previewSha = (await panel.locator('.backup-digest').textContent()).replace('미리보기 SHA-256 ', '');
    assert.match(previewSha, /^[0-9a-f]{64}$/);
    // consent is separate and off by default
    await panel.getByRole('button', { name: '이 내용으로 백업 만들기' }).click();
    await panel.getByText('미리보기 내용에 동의해야 백업을 만들 수 있습니다.').waitFor();
    await panel.locator('#backup-consent').check();
    await panel.getByRole('button', { name: '이 내용으로 백업 만들기' }).click();
    await panel.getByText('백업을 만들고 복원 확인을 마쳤습니다.', { exact: false }).first().waitFor();
    assert.match(await panel.textContent(), /이 호스트의 backup-key 볼륨을 잃으면 복구할 수 없습니다/);
    const bundleHref = await panel.locator('.backup-preview').getByRole('link', { name: '암호화된 백업 내려받기' }).getAttribute('href');
    const receiptHref = await panel.locator('.backup-preview').getByRole('link', { name: '외부 영수증 내려받기' }).getAttribute('href');
    const bundle = await bytesOf(page, bundleHref);
    const receiptBytes = await bytesOf(page, receiptHref);
    const receipt = JSON.parse(receiptBytes.toString('utf8'));
    assert.ok(bundle.subarray(0, 22).equals(Buffer.from('age-encryption.org/v1\n')));
    assert.equal(createHash('sha256').update(bundle).digest('hex'), receipt.ciphertext_sha256);
    assert.equal(receipt.recoverable_after_host_or_volume_loss, false);
    assert.ok(receipt.restore_verification_ref.scope.includes('record_lineage'));
    for (const secret of [CANARY, PASSWORD, CAPABILITY]) assert.ok(!bundle.includes(Buffer.from(secret)), 'encrypted: no plaintext');
    // the state lists it with the consented preview digest
    const state = await page.evaluate(async base => (await fetch(base + 'api/v1/backups')).json(), base);
    assert.equal(state.backups[0].backup_id, receipt.backup_id);
    assert.equal(state.backups[0].consented_preview_sha, previewSha);

    // the restore screen: the receipt and the bundle, staged for review
    await page.goto(url + 'records.html');
    await panel.locator('.backup-worker[data-state="ready"]').waitFor();
    await panel.locator('#restore-receipt').setInputFiles({ name: 'backup.receipt.json', mimeType: 'application/json', buffer: receiptBytes });
    await panel.locator('#restore-bundle').setInputFiles({ name: 'backup.age', mimeType: 'application/octet-stream', buffer: bundle });
    await panel.getByRole('button', { name: '스테이징 영역에 복원' }).click();
    const review = panel.locator('.restore-review[data-state="restored_review"]');
    await review.waitFor();
    const text = await review.textContent();
    assert.match(text, /검토 대기\(restored_review\) 상태이고 실행은 막혀 있습니다/);
    const steps = await review.locator('[data-required="true"][data-step]').evaluateAll(nodes => nodes.map(node => node.dataset.step));
    assert.deepEqual(steps, ['new_owner_bootstrap', 'recreate_connections_and_service_clients', 'review_and_activate_exact_environment']);
    assert.match(text, /새 소유자 초기 설정/);
    assert.match(text, /정확한 환경을 검토하고 명시적으로 다시 활성화하기 · 필요/);
    assert.match(text, /환경은 자동으로 다시 켜지지 않습니다/);
    assert.match(text, /세션 루트/);
    assert.match(await panel.textContent(), /활성 인스턴스는 바뀌지 않았습니다/);
    // the active instance keeps serving the same owner
    await page.goto(url + 'work.html');
    assert.equal(await page.evaluate(async base => (await fetch(base + 'session')).status, base), 200);

    // a tampered bundle against the same receipt is refused and stages nothing
    await page.goto(url + 'records.html');
    await panel.locator('.backup-worker[data-state="ready"]').waitFor();
    const tampered = Buffer.from(bundle);
    tampered[tampered.length >> 1] ^= 0x01;
    await panel.locator('#restore-receipt').setInputFiles({ name: 'backup.receipt.json', mimeType: 'application/json', buffer: receiptBytes });
    await panel.locator('#restore-bundle').setInputFiles({ name: 'backup.age', mimeType: 'application/octet-stream', buffer: tampered });
    await panel.getByRole('button', { name: '스테이징 영역에 복원' }).click();
    await panel.getByText('복원하지 못했습니다. 스테이징 영역에 아무것도 남기지 않았습니다.').waitFor();
    assert.deepEqual(errors, []);
  });
