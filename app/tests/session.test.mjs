// T048 (DOM-half prerequisite) / T025: the shell's session client for the
// SUPPORTED factory. Pure logic over an injected fetch: the deployment base
// path derived from the document location, the fixed session route
// (GET {base}session → the CSRF token bound to the owner cookie), and the
// request adapter the run observer (runtime.mjs) and the approvals module
// need — same-origin credentials, `X-DeepTwin-CSRF` on every non-GET, JSON
// bodies, the closed error partition preserved on thrown errors, and paths
// confined to this deployment's API under its base path. No DOM, no live
// server; the token never leaves the closure.

import test from 'node:test';
import assert from 'node:assert/strict';

import { createRunObserver, runRoutes } from '../static/runtime.mjs';
import {
  CSRF_HEADER,
  ERROR_CODES,
  SESSION_PATH,
  basePathFrom,
  createSupportedSession,
  sessionRoutes,
} from '../static/session.mjs';

const HEX = '2'.repeat(32);
const BASE = `/${HEX}/`;
const RUN_ID = '00000000-0000-4000-8000-00000000b0b1';

function jsonResponse(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      if (payload === undefined) throw new SyntaxError('not json');
      return payload;
    },
  };
}

function fakeFetch(script) {
  const calls = [];
  const fetch = async (path, options = {}) => {
    calls.push([path, options]);
    const step = script.shift();
    if (typeof step === 'function') return step(path, options);
    return step;
  };
  return { fetch, calls };
}

test('the base path is derived from the document location, never guessed', () => {
  assert.equal(basePathFrom('/'), '/');
  assert.equal(basePathFrom('/index.html'), '/');
  assert.equal(basePathFrom('/app.mjs'), '/');
  assert.equal(basePathFrom(BASE), BASE);
  assert.equal(basePathFrom(`${BASE}index.html`), BASE);
  assert.equal(basePathFrom(`${BASE}api/v1/runs/${RUN_ID}`), BASE);
  // a 32-hex segment without its closing slash is not a deployment base path
  assert.equal(basePathFrom(`/${HEX}`), '/');
  assert.equal(basePathFrom(`/${HEX}extra/`), '/');
  assert.equal(basePathFrom(`/${'Z'.repeat(32)}/`), '/');
  assert.equal(basePathFrom('/other/path/'), '/');
  assert.throws(() => basePathFrom(''), /location/);
  assert.throws(() => basePathFrom('relative/'), /location/);
  assert.throws(() => basePathFrom(42), /location/);
});

test('the session route binds the base path exactly', () => {
  assert.equal(SESSION_PATH, '/session');
  assert.equal(CSRF_HEADER, 'X-DeepTwin-CSRF');
  assert.equal(sessionRoutes('/').session, '/session');
  assert.equal(sessionRoutes(BASE).session, `/${HEX}/session`);
  assert.throws(() => sessionRoutes('/nope/'));
  assert.throws(() => sessionRoutes(''));
  assert.throws(() => sessionRoutes(`/${HEX}`));
  // the run routes' partition plus the session boundary's own refusals
  assert.deepEqual([...ERROR_CODES].sort(),
    ['access_denied', 'capacity', 'conflict', 'credentials', 'invalid_input', 'not_found', 'setup_incomplete',
      'setup_unavailable', 'too_large', 'unauthenticated', 'unavailable']);
});

test('establishing reads the token from GET {base}session and keeps it private', async () => {
  const { fetch, calls } = fakeFetch([jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' })]);
  const session = createSupportedSession({ fetch, basePath: BASE });
  assert.deepEqual(session.snapshot(), { established: false, basePath: BASE });
  const established = await session.establish();
  assert.deepEqual(established, { state: 'authenticated' });
  assert.deepEqual(calls, [[`/${HEX}/session`, { method: 'GET', credentials: 'same-origin', headers: {} }]]);
  assert.deepEqual(session.snapshot(), { established: true, basePath: BASE });
  assert.equal(JSON.stringify(session).includes('tok-1'), false);
  assert.equal(Object.keys(session).includes('token'), false);
  assert.equal(Object.isFrozen(session), true);
});

test('a refused command never carries the token in what it throws, and a 403 on a command drops the session', async () => {
  // review closure: after the owner logs in again elsewhere the cookie rotates; reads still
  // pass but every command with the retained token is 403 forever — the shell must be told
  // that establishing again would repair it (api.md: GET /session can return the token again)
  const { fetch } = fakeFetch([
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-secret' }),
    jsonResponse(403, { code: 'access_denied', message: 'Session request could not be admitted' }),
  ]);
  const session = createSupportedSession({ fetch, basePath: '/' });
  await session.establish();
  await assert.rejects(session.request('/api/v1/runs', { method: 'POST', body: { command_id: RUN_ID } }), error => {
    assert.equal(error.code, 'access_denied');
    assert.equal(JSON.stringify(error).includes('tok-secret'), false);
    assert.equal(error.message.includes('tok-secret'), false);
    assert.equal(String(error.stack ?? '').includes('tok-secret'), false);
    return true;
  });
  assert.equal(session.snapshot().established, false);
  // a 403 on a read (an origin or host refusal) is not a CSRF verdict: the session stands
  const reads = fakeFetch([
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-2' }),
    jsonResponse(403, { code: 'access_denied' }),
  ]);
  const reading = createSupportedSession({ fetch: reads.fetch, basePath: '/' });
  await reading.establish();
  await assert.rejects(reading.request(`/api/v1/runs/${RUN_ID}`), error => error.code === 'access_denied');
  assert.equal(reading.snapshot().established, true);
});

test('a success whose body is not a JSON object is unavailable, never a payload', async () => {
  for (const payload of [null, [], 'str', 7, true]) {
    const { fetch } = fakeFetch([jsonResponse(200, payload)]);
    const session = createSupportedSession({ fetch, basePath: '/' });
    await assert.rejects(session.request(`/api/v1/runs/${RUN_ID}`),
      error => error.code === 'unavailable' && error.status === 200);
  }
});

test('a session that cannot be established is a typed failure, never a token', async () => {
  for (const [status, payload, code] of [
    [401, { code: 'unauthenticated', message: 'Session request could not be admitted' }, 'unauthenticated'],
    [403, { code: 'access_denied' }, 'access_denied'],
    [503, { code: 'unavailable' }, 'unavailable'],
    [500, { code: 'bogus' }, 'unavailable'],
    [200, { state: 'authenticated', csrf_token: 7 }, 'unavailable'],
    [200, { state: 'other', csrf_token: 'tok' }, 'unavailable'],
    [200, undefined, 'unavailable'],
    [401, undefined, 'unauthenticated'],
  ]) {
    const { fetch } = fakeFetch([jsonResponse(status, payload)]);
    const session = createSupportedSession({ fetch, basePath: '/' });
    await assert.rejects(session.establish(), error => {
      assert.equal(error.code, code, `${status} ${JSON.stringify(payload)}`);
      assert.equal(error.status, status);
      return true;
    });
    assert.equal(session.snapshot().established, false);
  }
});

test('the request adapter sends the CSRF header on every non-GET and confines paths to this API', async () => {
  const { fetch, calls } = fakeFetch([
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' }),
    jsonResponse(200, { run_id: RUN_ID }),
    jsonResponse(201, { run_id: RUN_ID }),
  ]);
  const session = createSupportedSession({ fetch, basePath: BASE });
  // a command before the session is established never reaches the network
  await assert.rejects(session.request(`/${HEX}/api/v1/runs`, { method: 'POST', body: { command_id: RUN_ID } }),
    error => error.code === 'unauthenticated');
  assert.equal(calls.length, 0);
  await session.establish();
  assert.deepEqual(await session.request(`/${HEX}/api/v1/runs/${RUN_ID}`), { run_id: RUN_ID });
  assert.deepEqual(calls[1], [`/${HEX}/api/v1/runs/${RUN_ID}`,
    { method: 'GET', credentials: 'same-origin', headers: {} }]);
  assert.deepEqual(await session.request(`/${HEX}/api/v1/runs`, { method: 'POST', body: { command_id: RUN_ID } }),
    { run_id: RUN_ID });
  assert.deepEqual(calls[2], [`/${HEX}/api/v1/runs`, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'X-DeepTwin-CSRF': 'tok-1', 'Content-Type': 'application/json' },
    body: JSON.stringify({ command_id: RUN_ID }),
  }]);
  // paths outside this deployment's API are refused before any network call
  for (const path of ['/api/v1/runs', `/${'3'.repeat(32)}/api/v1/runs`, `https://example.test/${HEX}/api/v1/runs`,
    `/${HEX}/session`, `/${HEX}/api/v1/runs?x=1`, `/${HEX}/api/v1/../runs`, `/${HEX}/api/v1//runs`,
    `//${HEX}/api/v1/runs`, `/${HEX}/api/v1/runs#frag`, '', 42]) {
    await assert.rejects(session.request(path), error => error.code === 'invalid_input');
  }
  for (const options of [{ method: 'DELETE' }, { method: 'get' }, { body: {} }, { method: 'POST', body: 'raw' },
    { method: 'POST', body: [] }, { method: 'POST' }]) {
    await assert.rejects(session.request(`/${HEX}/api/v1/runs`, options), error => error.code === 'invalid_input');
  }
  assert.equal(calls.length, 3);
});

test('a refused request keeps the envelope code and the status, and a 401 drops the session', async () => {
  const { fetch } = fakeFetch([
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' }),
    jsonResponse(409, { code: 'conflict', message: 'Run request could not be admitted' }),
    jsonResponse(404, {}),
    jsonResponse(200, undefined),
    jsonResponse(401, { code: 'unauthenticated' }),
  ]);
  const session = createSupportedSession({ fetch, basePath: '/' });
  await session.establish();
  await assert.rejects(session.request(`/api/v1/runs/${RUN_ID}`), error => {
    assert.equal(error.code, 'conflict');
    assert.equal(error.status, 409);
    assert.equal(error.message, 'Run request could not be admitted');
    return true;
  });
  await assert.rejects(session.request(`/api/v1/runs/${RUN_ID}`), error => error.code === 'not_found' && error.status === 404);
  await assert.rejects(session.request(`/api/v1/runs/${RUN_ID}`), error => error.code === 'unavailable' && error.status === 200);
  assert.equal(session.snapshot().established, true);
  await assert.rejects(session.request(`/api/v1/runs/${RUN_ID}`), error => error.code === 'unauthenticated');
  assert.equal(session.snapshot().established, false);
  // a network failure is unavailable, and the session stands
  const failing = createSupportedSession({ fetch: async () => { throw new TypeError('offline'); }, basePath: '/' });
  await assert.rejects(failing.establish(), error => error.code === 'unavailable' && error.status === undefined);
});

test('the run observer runs over the session adapter on the deployment base path', async () => {
  const receipt = {
    command_id: '11111111-2222-4333-8444-555555555555', run_id: RUN_ID,
    graph_ref: { kind: 'graph', id: '33333333-3333-4333-8333-333333333333', version: 1, sha256: 'c'.repeat(64) },
    graph_digest: 'd'.repeat(64), phase: 'completed',
    outcome: { run_id: RUN_ID, graph_digest: 'd'.repeat(64), completed_node_ids: ['intake'],
      execution_ids: [['intake', 'e-intake']],
      result_refs: [['e-intake', { kind: 'artifact', id: '44444444-4444-4444-8444-444444444444', version: 1, sha256: 'c'.repeat(64) }]],
      counters: { intake: 1 }, activations: [], awaiting_human: [], approvals: [], pending_node_ids: [], rejected_human: [] },
    links: { self: `/${HEX}/api/v1/runs/${RUN_ID}`, approvals: `/${HEX}/api/v1/runs/${RUN_ID}/approvals`,
             events: `/${HEX}/api/v1/events` },
    event_cursor: 'opaque-cursor', cancellation: { requested: false, attempts: [] },
  };
  const { fetch, calls } = fakeFetch([
    jsonResponse(200, { state: 'authenticated', csrf_token: 'tok-1' }),
    jsonResponse(200, receipt),
    jsonResponse(200, receipt),
  ]);
  const basePath = basePathFrom(`${BASE}index.html`);
  const session = createSupportedSession({ fetch, basePath });
  await session.establish();
  const observer = createRunObserver({ request: session.request, basePath });
  const view = await observer.read(RUN_ID);
  assert.equal(view.runId, RUN_ID);
  assert.equal(calls[1][0], runRoutes(basePath).read(RUN_ID));
  assert.equal(calls[1][1].headers[CSRF_HEADER], undefined);
  await observer.cancel(RUN_ID, '77777777-7777-4777-8777-777777777777');
  assert.equal(calls[2][0], runRoutes(basePath).cancel(RUN_ID));
  assert.equal(calls[2][1].headers[CSRF_HEADER], 'tok-1');
  assert.throws(() => createSupportedSession({ basePath: '/' }), /fetch/);
  assert.throws(() => createSupportedSession({ fetch, basePath: '/nope/' }));
});
