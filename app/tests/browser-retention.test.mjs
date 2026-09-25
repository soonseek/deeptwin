// T073 in a real browser against the real supported server with a REAL backup-crypto
// worker (app/tests/fixtures/backup_server.py, via helpers/backup-fixture.mjs):
// - retention: the records page states per category what the server keeps, for how long,
//   that nothing is deleted automatically and what is never offered; the owner makes two
//   backups and one failed restore, ticks the older backup and the failed restore (the
//   newest backup cannot be ticked), sees the server's actual cleanup preview, is refused
//   without the separate consent, consents to exactly that preview and cleans up. The
//   older ciphertext is gone (download 404) while its receipt, the newest backup and the
//   saved work still read back; the cleanup receipt and the `retention.deleted` event are
//   listed.
// - settings hub: from every page's header the one settings link opens the hub, which
//   lists every records/operations entry point with the server's own state, and each
//   entry opens its section; no entry is a required final step.
// The owner is a scripted test actor: synthetic evidence of the mechanism, never user
// evidence. Needs Linux, root and DEEPTWIN_AGE_RUNTIME_ROOT; otherwise skipped with why.

import test from 'node:test';
import assert from 'node:assert/strict';
import { base, bytesOf, makeBackup, openBackup, unavailable } from './helpers/backup-fixture.mjs';

async function saveWork(page, url, text) {
  await page.goto(url + 'work.html');
  await page.locator('#work-description').fill(text);
  await page.getByRole('button', { name: '이 인스턴스에 저장' }).click();
  await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();
}

test('retention: per-category state, then preview → consent → cleanup; core records stay readable',
  { timeout: 240000, skip: unavailable }, async t => {
    const { page, url, errors } = await openBackup(t);
    await saveWork(page, url, '정리한 뒤에도 남아야 할 작업 설명');
    const older = await makeBackup(page, url);
    const newer = await makeBackup(page, url);
    // one failed restore: the newer receipt with a tampered bundle
    const bundle = await bytesOf(page, `${base}api/v1/backups/${newer.backup_id}/ciphertext`);
    const tampered = Buffer.from(bundle);
    tampered[tampered.length >> 1] ^= 0x01;
    await page.goto(url + 'records.html');
    const backupPanel = page.locator('#records-backup');
    await backupPanel.locator('.backup-worker[data-state="ready"]').waitFor();
    await backupPanel.locator('#restore-receipt').setInputFiles({ name: 'r.receipt.json', mimeType: 'application/json',
      buffer: Buffer.from(JSON.stringify(newer)) });
    await backupPanel.locator('#restore-bundle').setInputFiles({ name: 'b.age', mimeType: 'application/octet-stream', buffer: tampered });
    await backupPanel.getByRole('button', { name: '스테이징 영역에 복원' }).click();
    await backupPanel.getByText('복원하지 못했습니다.', { exact: false }).first().waitFor();

    await page.reload();
    const panel = page.locator('#records-retention');
    await panel.locator('.retention-categories li').first().waitFor();
    const text = await panel.textContent();
    assert.match(text, /자동 삭제는 없습니다/);
    const kept = await panel.locator('.retention-categories li').evaluateAll(nodes => nodes.map(node => [
      node.dataset.category, node.dataset.kept, node.dataset.ownerCleanup, node.dataset.automaticDeletion]));
    assert.deepEqual(kept.map(row => row[0]), ['core_records', 'deletion_tombstones', 'originals', 'backups',
      'staged_restores', 'regenerable_caches', 'raw_audio']);
    assert.ok(kept.every(row => row[3] === 'never'), 'nothing is deleted automatically');
    assert.deepEqual(kept[0].slice(1, 3), ['forever', 'not_offered']);
    assert.match(text, /핵심 기록\(기록·계보·사건 기록\) · 기한 없이 보존 · 자동 삭제 없음/);
    assert.match(text, /기록은 덧붙이기만 하는 이력이라 지우지 않습니다/);
    assert.match(text, /암호화된 백업 · 소유자가 정리할 때까지 보존 · 자동 삭제 없음 · 2개/);
    assert.match(text, /가장 최근 백업은 항상 남깁니다/);
    const newest = panel.locator(`li[data-item-id="backup:${newer.backup_id}"] input`);
    assert.equal(await newest.isDisabled(), true, 'the newest backup is never offered');
    const olderBox = panel.locator(`li[data-item-id="backup:${older.backup_id}"] input`);
    const failedBox = panel.locator('li[data-item-id^="restore:"] input');
    assert.equal(await failedBox.count(), 1);
    assert.equal(await olderBox.isChecked(), false, 'nothing is preselected');
    await olderBox.check();
    await failedBox.check();
    await panel.getByRole('button', { name: '선택한 항목 정리 미리보기' }).click();
    await panel.locator('#retention-consent').waitFor();
    const preview = await panel.locator('.retention-preview').textContent();
    assert.match(preview, /정리될 항목 2개/);
    assert.match(preview, /지움: 암호화된 백업 파일 · 남김: 외부 영수증, 동의 기록, 삭제 표시/);
    assert.match(preview, /닿지 않는 것: 이미 내려받은 사본/);
    assert.match(preview, /어떤 경우에도 지우지 않는 것: 핵심 기록, 삭제 표시, 저장한 원본\(작업 화면에서만 삭제\), 가장 최근 백업/);
    const digest = (await panel.locator('.retention-digest').textContent()).replace('미리보기 SHA-256 ', '');
    assert.match(digest, /^[0-9a-f]{64}$/);
    // a preview removes nothing
    assert.equal((await bytesOf(page, `${base}api/v1/backups/${older.backup_id}/ciphertext`)).length, older.ciphertext_size);
    await panel.getByRole('button', { name: '이 내용대로 정리' }).click();
    await panel.getByText('미리보기 내용에 동의해야 정리할 수 있습니다.').waitFor();
    await panel.locator('#retention-consent').check();
    await panel.getByRole('button', { name: '이 내용대로 정리' }).click();
    await panel.getByText('정리했습니다. 지운 자리에는 삭제 표시가 남고, 핵심 기록은 그대로 읽힙니다.').waitFor();
    const cleanup = panel.locator('.retention-cleanups li').first();
    assert.match(await cleanup.textContent(), new RegExp(`2개 · .* · 미리보기 SHA-256 ${digest}`));

    const status = await page.evaluate(async ({ base, older, newer }) => ({
      oldCipher: (await fetch(`${base}api/v1/backups/${older}/ciphertext`)).status,
      oldReceipt: (await fetch(`${base}api/v1/backups/${older}/receipt`)).status,
      newCipher: (await fetch(`${base}api/v1/backups/${newer}/ciphertext`)).status,
      state: await (await fetch(`${base}api/v1/backups`)).json(),
      events: await (await fetch(`${base}api/v1/events?limit=100`)).json(),
    }), { base, older: older.backup_id, newer: newer.backup_id });
    assert.equal(status.oldCipher, 404);
    assert.equal(status.oldReceipt, 200);
    assert.equal(status.newCipher, 200);
    const listed = Object.fromEntries(status.state.backups.map(item => [item.backup_id, item.ciphertext_state]));
    assert.deepEqual(listed, { [older.backup_id]: 'deleted', [newer.backup_id]: 'stored' });
    assert.ok(status.state.restores.every(view => view.state === 'discarded'));
    assert.ok(status.events.events.some(event => event.event_type === 'retention.deleted'));
    // the backup list now offers only the receipt of the removed backup
    const row = page.locator(`#records-backup li[data-backup-id="${older.backup_id}"]`);
    assert.equal(await row.getAttribute('data-ciphertext-state'), 'deleted');
    assert.equal(await row.getByRole('link').count(), 1);
    // core records stay readable: the saved work reads back
    await page.goto(url + 'work.html');
    await page.getByText('이 인스턴스에 저장됨 · 수정본', { exact: false }).first().waitFor();
    assert.equal(await page.locator('#work-description').inputValue(), '정리한 뒤에도 남아야 할 작업 설명');
    assert.deepEqual(errors, []);
  });

test('settings hub: one header link on every page opens every entry point, none required',
  { timeout: 180000, skip: unavailable }, async t => {
    const { page, url, errors } = await openBackup(t);
    for (const name of ['work.html', 'observe.html', 'records.html', 'versions.html', 'settings.html']) {
      await page.goto(url + name);
      const link = page.getByRole('navigation', { name: '설정' }).getByRole('link', { name: '설정' });
      await link.click();
      await page.waitForURL(`${url}settings.html`);
      await page.locator('#settings-hub li[data-entry]').first().waitFor();
    }
    const hub = page.locator('#settings-hub');
    await hub.locator('.settings-state').first().waitFor();
    const entries = await hub.locator('li[data-entry]').evaluateAll(nodes => nodes.map(node => [node.dataset.entry, node.dataset.required]));
    assert.deepEqual(entries.map(entry => entry[0]), ['logs', 'export', 'backup', 'retention', 'account', 'connection', 'credentials', 'extensions']);
    assert.ok(entries.every(entry => entry[1] === 'false'), 'no entry is a required step');
    assert.match(await hub.textContent(), /어떤 작업도 마지막에 내보내기를 거치지 않아도 끝납니다/);
    assert.match(await hub.locator('li[data-entry="backup"]').textContent(), /백업 워커 연결됨 · 만든 백업 0개/);
    assert.match(await hub.locator('li[data-entry="retention"]').textContent(), /자동 삭제 없음 · 지금 정리할 수 있는 항목 0개/);
    assert.match(await page.locator('#session-status').textContent(), /브라우저 세션이 연결되어 있습니다/);
    const targets = {
      logs: ['records.html#records-logs', '#records-logs li, #records-logs [role=status]'],
      backup: ['records.html#records-backup', '#records-backup .backup-worker[data-state="ready"]'],
      retention: ['records.html#records-retention', '#records-retention .retention-categories li'],
      account: ['records.html#records-account', '#records-account h2'],
      export: ['work.html#work-records', '#work-records'],
      extensions: ['settings.html#settings-extensions', '#settings-extensions h2'],
    };
    for (const [entry, [target, ready]] of Object.entries(targets)) {
      await page.goto(url + 'settings.html');
      await hub.locator(`li[data-entry="${entry}"] a`).click();
      await page.waitForURL(url + target);
      await page.locator(ready).first().waitFor();
    }
    // the start screen carries the same link
    const start = await page.evaluate(async base => (await fetch(base + 'start.html')).text(), base);
    assert.match(start, /<a href="\.\/settings\.html">설정<\/a>/);
    assert.deepEqual(errors, []);
  });
