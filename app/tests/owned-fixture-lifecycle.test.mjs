import test from 'node:test';
import assert from 'node:assert/strict';
import { once } from 'node:events';
import { spawn } from 'node:child_process';

import {
  ForcedCleanupError,
  closeOwnedFixture,
  terminateOwnedChild,
  waitForOwnedChildOutput,
} from './helpers/owned-fixture-lifecycle.mjs';

const caseTimeout = 2_000;

function isAlive(child) {
  if (child.exitCode !== null || child.signalCode !== null) return false;
  try {
    process.kill(child.pid, 0);
    return true;
  } catch (error) {
    if (error.code === 'ESRCH') return false;
    throw error;
  }
}

function spawnOwned(t, source) {
  const child = spawn(process.execPath, ['--input-type=module', '--eval', source], {
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  t.after(async () => {
    if (!isAlive(child)) return;
    const exited = once(child, 'exit');
    child.kill('SIGKILL');
    await Promise.race([exited, new Promise(resolve => setTimeout(resolve, 500))]);
  });
  return child;
}

test('an owned child that ignores SIGTERM is force-stopped within the deadline and reports forced cleanup', { timeout: caseTimeout }, async t => {
  const child = spawnOwned(t, `
    process.on('SIGTERM', () => {});
    console.log('READY');
    setInterval(() => {}, 1000);
  `);
  await waitForOwnedChildOutput(child, { pattern: /READY/, timeoutMs: 500, label: 'ignoring child' });

  const started = Date.now();
  await assert.rejects(
    terminateOwnedChild(child, { graceMs: 60, forceMs: 500, label: 'ignoring child' }),
    error => error instanceof ForcedCleanupError && /SIGKILL/.test(error.message),
  );

  assert.ok(Date.now() - started < 1_000, 'owned-child cleanup must have a finite upper bound');
  assert.equal(isAlive(child), false, 'forced cleanup must finish before it reports failure');
});

test('an already signal-exited child does not wait for an exit event that already happened', { timeout: caseTimeout }, async t => {
  const child = spawnOwned(t, `process.kill(process.pid, 'SIGTERM')`);
  await once(child, 'exit');

  const started = Date.now();
  const result = await terminateOwnedChild(child, { graceMs: 500, forceMs: 500, label: 'exited child' });

  assert.equal(result.forced, false);
  assert.ok(Date.now() - started < 100, 'past exit must be observed synchronously');
  assert.equal(isAlive(child), false);
});

test('startup without readiness settles and releases the owned child', { timeout: caseTimeout }, async t => {
  const child = spawnOwned(t, `setInterval(() => {}, 1000)`);

  await assert.rejects(
    waitForOwnedChildOutput(child, { pattern: /READY/, timeoutMs: 60, label: 'silent fixture' }),
    /silent fixture was not ready within 60ms/,
  );
  await closeOwnedFixture({ server: child }, {
    serverGraceMs: 500,
    serverForceMs: 500,
    label: 'silent fixture',
  });

  assert.equal(isAlive(child), false, 'startup failure must not leave its child running');
});

test('partial setup closes browser resources before its server and temp state', { timeout: caseTimeout }, async t => {
  const events = [];
  const child = spawnOwned(t, `
    console.log('READY');
    setInterval(() => {}, 1000);
  `);
  await waitForOwnedChildOutput(child, { pattern: /READY/, timeoutMs: 500, label: 'partial fixture' });
  child.once('exit', () => events.push('server'));
  const browser = {
    async close() {
      assert.equal(isAlive(child), true, 'server must still be available while browser resources close');
      events.push('browser');
    },
  };

  await closeOwnedFixture({
    browser,
    server: child,
    removeTemp: async () => events.push('temp'),
  }, {
    browserCloseMs: 500,
    serverGraceMs: 500,
    serverForceMs: 500,
    label: 'partial fixture',
  });

  assert.deepEqual(events, ['browser', 'server', 'temp']);
  assert.equal(isAlive(child), false);
});
