function hasExited(child) {
  return child.exitCode !== null || child.signalCode !== null;
}

function boundedOutput(current, bytes, maxOutputChars) {
  const next = current + String(bytes);
  return next.length <= maxOutputChars ? next : next.slice(-maxOutputChars);
}

function deadline(promise, timeoutMs, message) {
  let timer;
  return Promise.race([
    Promise.resolve(promise),
    new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    }),
  ]).finally(() => clearTimeout(timer));
}

function waitForExit(child, timeoutMs) {
  if (hasExited(child)) return Promise.resolve(true);
  return new Promise(resolve => {
    let settled = false;
    const finish = exited => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.removeListener('exit', onExit);
      child.removeListener('close', onExit);
      resolve(exited);
    };
    const onExit = () => finish(true);
    const timer = setTimeout(() => finish(false), timeoutMs);
    child.once('exit', onExit);
    child.once('close', onExit);
    if (hasExited(child)) finish(true);
  });
}

export class ForcedCleanupError extends Error {
  constructor(message) {
    super(message);
    this.name = 'ForcedCleanupError';
    this.forced = true;
  }
}

export function waitForOwnedChildOutput(child, {
  pattern,
  timeoutMs,
  label = 'Fixture',
  maxOutputChars = 4_096,
}) {
  return new Promise((resolve, reject) => {
    let output = '';
    let settled = false;
    const cleanup = () => {
      clearTimeout(timer);
      child.stdout?.removeListener('data', onData);
      child.stderr?.removeListener('data', onData);
      child.removeListener('error', onError);
      child.removeListener('exit', onExit);
    };
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      cleanup();
      if (error) reject(error);
      else resolve(value);
    };
    const diagnostics = () => output.trim() || '<no output>';
    const onData = bytes => {
      output = boundedOutput(output, bytes, maxOutputChars);
      pattern.lastIndex = 0;
      const match = pattern.exec(output);
      if (match) finish(null, match[0]);
    };
    const onError = error => finish(new Error(`${label} failed to start: ${error.message}; output: ${diagnostics()}`, { cause: error }));
    const onExit = (code, signal) => finish(new Error(`${label} exited before readiness (code=${code}, signal=${signal}); output: ${diagnostics()}`));
    const timer = setTimeout(
      () => finish(new Error(`${label} was not ready within ${timeoutMs}ms; output: ${diagnostics()}`)),
      timeoutMs,
    );
    child.stdout?.on('data', onData);
    child.stderr?.on('data', onData);
    child.once('error', onError);
    child.once('exit', onExit);
    if (hasExited(child)) onExit(child.exitCode, child.signalCode);
  });
}

export async function terminateOwnedChild(child, {
  graceMs,
  forceMs,
  label = 'Fixture',
}) {
  if (hasExited(child)) return { forced: false };

  const gracefulExit = waitForExit(child, graceMs);
  child.kill('SIGTERM');
  if (await gracefulExit) return { forced: false };

  const forcedExit = waitForExit(child, forceMs);
  child.kill('SIGKILL');
  if (!await forcedExit) {
    throw new ForcedCleanupError(`${label} did not exit within ${forceMs}ms after SIGKILL`);
  }
  throw new ForcedCleanupError(`${label} required SIGKILL after exceeding its ${graceMs}ms SIGTERM grace period`);
}

export async function closeOwnedFixture({ browser, server, removeTemp }, {
  browserCloseMs = 5_000,
  serverGraceMs = 2_000,
  serverForceMs = 2_000,
  tempCleanupMs = 5_000,
  label = 'Fixture',
} = {}) {
  const errors = [];

  if (browser) {
    try {
      await deadline(browser.close(), browserCloseMs, `${label} browser did not close within ${browserCloseMs}ms`);
    } catch (error) {
      errors.push(error);
    }
  }

  if (server) {
    try {
      await terminateOwnedChild(server, { graceMs: serverGraceMs, forceMs: serverForceMs, label });
    } catch (error) {
      errors.push(error);
    }
  }

  if (removeTemp) {
    try {
      await deadline(removeTemp(), tempCleanupMs, `${label} temp cleanup did not finish within ${tempCleanupMs}ms`);
    } catch (error) {
      errors.push(error);
    }
  }

  if (errors.length === 1) throw errors[0];
  if (errors.length > 1) throw new AggregateError(errors, `${label} cleanup failed in ${errors.length} places`);
}
