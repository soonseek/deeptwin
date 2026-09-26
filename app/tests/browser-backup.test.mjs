// T073/T070 in a real browser against the real supported server with a REAL backup-crypto
// worker: the fixture (app/tests/fixtures/backup_server.py) runs the production worker
// entrypoint as a separate process in an empty network namespace under the backup
// identity, holding the read-only backup-key volume, and the supported app under the
// control identity; they speak only over the verified `cp-backup` channel. The owner
// saves a work, opens the settings page's 백업·보존 panel, sees the ACTUAL backup preview (included
// categories with counts, excluded categories with reasons), consents to exactly that
// preview, creates the backup, downloads the encrypted bundle and its external receipt,
// then restores them through the restore screen and sees the staged `restored_review`
// state with the new-owner bootstrap and explicit environment reactivation shown as
// required. A second case restores a `portable_recovery` backup made elsewhere with the
// identity the owner kept, typed once into a masked input (never stored or echoed). The
// fixture start-up lives in helpers/backup-fixture.mjs. The owner is a scripted test actor: synthetic evidence of the mechanism,
// never user evidence. Needs Linux and root for the fixture's identities; otherwise the
// fixture reports why and this case is skipped with that reason.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { CAPABILITY, PASSWORD, base, bytesOf, openBackup, unavailable } from './helpers/backup-fixture.mjs';
import { openSettings } from './helpers/settings-page.mjs';

const CANARY = 'CANARY-백업-원문-5e1d';

test('backup: actual preview, bound consent, encrypted bundle + receipt, restore staged for review',
  { timeout: 180000, skip: unavailable }, async t => {
    const { page, url, errors, networkless } = await openBackup(t);
    assert.equal(networkless, true, 'the worker runs in an empty network namespace');
    await page.goto(url + 'work.html');
    await page.locator('#work-description').fill(`백업할 작업 설명입니다. ${CANARY}`);
    await page.getByRole('button', { name: '이 인스턴스에 저장' }).click();
    await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();

    await openSettings(page, url, 'settings-backup');
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
    await openSettings(page, url, 'settings-backup');
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
    await openSettings(page, url, 'settings-backup');
    await panel.locator('.backup-worker[data-state="ready"]').waitFor();
    const tampered = Buffer.from(bundle);
    tampered[tampered.length >> 1] ^= 0x01;
    await panel.locator('#restore-receipt').setInputFiles({ name: 'backup.receipt.json', mimeType: 'application/json', buffer: receiptBytes });
    await panel.locator('#restore-bundle').setInputFiles({ name: 'backup.age', mimeType: 'application/octet-stream', buffer: tampered });
    await panel.getByRole('button', { name: '스테이징 영역에 복원' }).click();
    await panel.getByText('복원하지 못했습니다. 스테이징 영역에 아무것도 남기지 않았습니다.').waitFor();
    assert.deepEqual(errors, []);
  });

// Portable recovery through the browser: a `portable_recovery` backup made elsewhere (the
// fixture's separate synthetic vault) is restored here with the identity the owner kept.
// The identity is typed into a masked input that is cleared at once, reaches the worker
// once through the portable route, and is found nowhere afterwards: not in the DOM, not
// in localStorage/sessionStorage, not in any response the page saw. Without it, nothing
// is asked of the server; a wrong one stages nothing.
test('portable recovery: the kept identity restores once into staged review and is stored nowhere',
  { timeout: 180000, skip: unavailable }, async t => {
    const { page, url, errors, portableDir } = await openBackup(t);
    const identity = (await readFile(`${portableDir}/identity.txt`, 'utf8')).trim();
    const receiptBytes = await readFile(`${portableDir}/receipt.json`);
    const bundle = await readFile(`${portableDir}/bundle.age`);
    assert.equal(JSON.parse(receiptBytes).key_mode, 'portable_recovery');
    const seen = [];
    page.on('response', async response => {
      try { seen.push(await response.text()); } catch { /* a download body is not text */ }
    });
    await openSettings(page, url, 'settings-backup');
    const panel = page.locator('#records-backup');
    await panel.locator('.backup-worker[data-state="ready"]').waitFor();
    const input = panel.locator('#restore-recovery-identity');
    assert.equal(await input.getAttribute('type'), 'password');
    const pick = async () => {
      await panel.locator('#restore-receipt').setInputFiles({ name: 'portable.receipt.json', mimeType: 'application/json', buffer: receiptBytes });
      await panel.locator('#restore-bundle').setInputFiles({ name: 'portable.age', mimeType: 'application/octet-stream', buffer: bundle });
    };
    // without the kept identity nothing is sent
    await pick();
    await panel.getByRole('button', { name: '스테이징 영역에 복원' }).click();
    await panel.getByText('이 백업은 휴대용 복구 백업입니다.', { exact: false }).waitFor();
    const before = await page.evaluate(async base => (await (await fetch(base + 'api/v1/backups')).json()).restores.length, base);
    assert.equal(before, 0);
    // a wrong identity (a valid-looking native identity of nobody): the worker cannot decrypt
    const wrong = `AGE-SECRET-KEY-1${'Q'.repeat(58)}`;
    await pick();
    await input.fill(wrong);
    await panel.getByRole('button', { name: '스테이징 영역에 복원' }).click();
    await panel.getByText(/복원하지 못했습니다|요청 형식이 맞지 않습니다/).first().waitFor();
    assert.equal(await input.inputValue(), '');
    // the kept identity: staged for review, blocked, the active instance unchanged
    await pick();
    await input.fill(identity);
    await panel.getByRole('button', { name: '스테이징 영역에 복원' }).click();
    const review = panel.locator('.restore-review[data-state="restored_review"]');
    await review.waitFor();
    assert.equal(await input.inputValue(), '', 'the masked input is cleared once read');
    assert.match(await review.textContent(), /검토 대기\(restored_review\) 상태이고 실행은 막혀 있습니다/);
    const steps = await review.locator('[data-required="true"][data-step]').evaluateAll(nodes => nodes.map(node => node.dataset.step));
    assert.deepEqual(steps, ['new_owner_bootstrap', 'recreate_connections_and_service_clients', 'review_and_activate_exact_environment']);
    assert.match(await panel.textContent(), /따로 보관한 복구 키로 복호화해 스테이징 영역에 만들었습니다/);
    assert.match(await panel.textContent(), /활성 인스턴스는 바뀌지 않았습니다/);
    const receipt = JSON.parse(receiptBytes);
    assert.match(await review.textContent(), new RegExp(receipt.backup_id));
    // the identity is nowhere the page can reach
    const html = await page.content();
    assert.ok(!html.includes(identity) && !html.includes('AGE-SECRET-KEY'), 'not in the DOM');
    const stored = await page.evaluate(() => JSON.stringify([{ ...localStorage }, { ...sessionStorage }]));
    assert.ok(!stored.includes('AGE-SECRET-KEY'), 'not in browser storage');
    const state = await page.evaluate(async base => (await fetch(base + 'api/v1/backups')).text(), base);
    for (const text of [...seen, state]) assert.ok(!text.includes(identity), 'no response carries the identity');
    const views = JSON.parse(state).restores;
    assert.ok(views.some(view => view.state === 'restored_review' && view.key_mode === 'portable_recovery'));
    // the active instance keeps serving the same owner
    assert.equal(await page.evaluate(async base => (await fetch(base + 'session')).status, base), 200);
    for (const secret of [PASSWORD, CAPABILITY]) assert.ok(!state.includes(secret));
    assert.deepEqual(errors, []);
  });
