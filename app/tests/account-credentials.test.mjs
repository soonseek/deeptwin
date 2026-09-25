// T090: the credentials panel over a fake document, fetch and session adapter. The list
// is the redacted projection only; a secret is read once, cleared from its field before
// the request leaves and never lands in the DOM or browser storage; deleting says it does
// not revoke the key at the provider; command_pending, secret_input_lost and an
// unavailable gateway are shown as they are.

import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CATALOG_RESULTS, CONNECTION_MESSAGES, CONNECTION_STATES, CREDENTIAL_ERRORS, CREDENTIAL_MESSAGES, CREDENTIAL_STATES,
  FENCE_RESULTS, PENDING_MESSAGES, createCredentialsPanel,
} from '../static/account.mjs';

class FakeElement {
  constructor(tagName) { this.tagName = tagName.toUpperCase(); this.children = []; this.attributes = new Map(); this.dataset = {}; this.listeners = new Map(); this._text = ''; this.value = ''; this.disabled = false; }
  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
  set textContent(value) { this._text = String(value); this.children = []; }
  set innerHTML(_value) { throw new Error('markup is never written'); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }
  async dispatch(type) { for (const listener of this.listeners.get(type) ?? []) await listener({}); }
  findAll(predicate, found = []) { for (const child of this.children) { if (predicate(child)) found.push(child); child.findAll(predicate, found); } return found; }
}

const document = { createElement: tag => new FakeElement(tag) };
const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const BASE = `/${'2'.repeat(32)}/`;
const PATH = `${BASE}api/v1/credentials`;
const H1 = 'a'.repeat(32);
const SECRET = 'sk-synthetic-ui-secret-0001';
const CSRF = 'c'.repeat(43);

// every string the page holds: text, attributes, datasets and field values
function everything(node, found = []) {
  found.push(node._text, node.value, ...node.attributes.values(), ...Object.values(node.dataset));
  for (const child of node.children) everything(child, found);
  return found.join('\n');
}

function panelWith(responses) {
  const root = new FakeElement('section');
  const sent = [];
  let counter = 0;
  const fetch = async (path, options) => {
    sent.push([path, { ...options, body: options.body }]);
    const next = responses.shift();
    if (next instanceof Error) throw next;
    const [status, body] = next;
    return { ok: status < 400, status, json: async () => body };
  };
  const randomUUID = () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`;
  const panel = createCredentialsPanel({ root, document, fetch, basePath: BASE, session: { csrfToken: () => CSRF }, randomUUID });
  const byId = id => root.findAll(el => el.getAttribute('id') === id)[0];
  const button = text => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text)[0];
  return { root, sent, panel, byId, button };
}

const listed = (...credentials) => [200, { credentials: credentials.map(entry => ({ provider_revocation: 'not_performed', ...entry })) }];
const refusal = (status, code) => [status, { code, message: 'x', retryability: 'not_retryable', affected_refs: [] }];

test('the list shows only handle, provider and state, and the revocation limit is stated', async () => {
  const { root, sent, panel } = panelWith([listed({ handle: H1, provider: 'claude', state: 'stored_unbound' },
    { handle: 'b'.repeat(32), provider: 'codex', state: 'cleanup_pending' })]);
  const credentials = await panel.load();
  assert.deepEqual(sent[0], [PATH, { method: 'GET', credentials: 'same-origin', headers: {}, body: undefined }]);
  assert.deepEqual(credentials, [{ handle: H1, provider: 'claude', state: 'stored_unbound' },
    { handle: 'b'.repeat(32), provider: 'codex', state: 'cleanup_pending' }]);
  const text = root.textContent;
  assert.match(text, new RegExp(`claude · ${H1} · ${CREDENTIAL_STATES.stored_unbound.replace(/[()]/g, '\\$&')}`));
  assert.match(text, new RegExp(CREDENTIAL_MESSAGES.revocation));
  // a retired credential offers no rotate or delete
  const rows = root.findAll(el => el.tagName === 'LI');
  assert.equal(rows[0].findAll(el => el.tagName === 'BUTTON').length, 2);
  assert.equal(rows[1].findAll(el => el.tagName === 'BUTTON').length, 0);
});

test('adding sends the secret once, clears the field before the request and keeps it nowhere', async () => {
  const touched = [];
  const storage = new Proxy({}, { get(_target, name) { touched.push(name); return () => null; } });
  globalThis.localStorage = storage;
  globalThis.sessionStorage = storage;
  try {
    const { root, sent, panel, byId, button } = panelWith([listed(),
      [201, { handle: H1, provider: 'claude', state: 'stored_unbound' }],
      listed({ handle: H1, provider: 'claude', state: 'stored_unbound' })]);
    await panel.load();
    const field = byId('credential-secret');
    assert.equal(field.getAttribute('type'), 'password');
    assert.equal(field.getAttribute('autocomplete'), 'off');
    field.value = SECRET;
    const pending = button('키 저장').dispatch('click');
    assert.equal(field.value, '');  // cleared synchronously, before the request resolves
    await pending;
    await flush();
    const [path, options] = sent[1];
    assert.equal(path, PATH);
    assert.equal(options.method, 'POST');
    assert.equal(options.headers['X-DeepTwin-CSRF'], CSRF);
    assert.deepEqual(JSON.parse(options.body), { intent_id: '00000000-0000-4000-8000-000000000001', provider: 'claude', secret: SECRET });
    assert.equal(sent.filter(([, value]) => String(value.body).includes(SECRET)).length, 1);
    assert.match(root.textContent, new RegExp(CREDENTIAL_MESSAGES.created));
    assert.ok(!everything(root).includes(SECRET));
    assert.deepEqual(touched, []);
  } finally {
    delete globalThis.localStorage;
    delete globalThis.sessionStorage;
  }
});

test('an empty secret sends nothing', async () => {
  const { sent, panel, root } = panelWith([listed()]);
  await panel.load();
  assert.equal(await panel.store(), null);
  assert.equal(sent.length, 1);
  assert.match(root.textContent, new RegExp(CREDENTIAL_MESSAGES.noSecret));
});

test('rotate carries rotate_from for the chosen handle and clears the field', async () => {
  const { sent, panel, byId, button, root } = panelWith([
    listed({ handle: H1, provider: 'codex', state: 'stored_unbound' }),
    [201, { handle: H1, provider: 'codex', state: 'stored_unbound' }],
    listed({ handle: H1, provider: 'codex', state: 'stored_unbound' })]);
  await panel.load();
  await button('교체').dispatch('click');
  assert.match(root.textContent, new RegExp(CREDENTIAL_MESSAGES.rotating(H1)));
  byId('credential-secret').value = SECRET;
  await button('키 교체').dispatch('click');
  await flush();
  assert.equal(byId('credential-secret').value, '');
  assert.deepEqual(JSON.parse(sent[1][1].body), { intent_id: '00000000-0000-4000-8000-000000000001',
    provider: 'codex', secret: SECRET, rotate_from: H1 });
  assert.match(root.textContent, new RegExp(CREDENTIAL_MESSAGES.rotated));
  assert.ok(!everything(root).includes(SECRET));
});

test('delete asks first, says the provider key is not revoked, and sends only an intent', async () => {
  const { sent, panel, button, root } = panelWith([
    listed({ handle: H1, provider: 'claude', state: 'stored_unbound' }),
    [200, { handle: H1, state: 'cleanup_pending', provider_revocation: 'not_performed' }],
    listed({ handle: H1, provider: 'claude', state: 'cleanup_pending' })]);
  await panel.load();
  await button('삭제').dispatch('click');
  assert.equal(sent.length, 1);  // nothing leaves before the explicit confirmation
  assert.match(root.textContent, /제공자 쪽의 키는 폐기되지 않습니다\(provider_revocation: not_performed\)/);
  await button('삭제 확인').dispatch('click');
  await flush();
  assert.deepEqual(sent[1], [`${PATH}/${H1}`, { method: 'DELETE', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': CSRF },
    body: JSON.stringify({ intent_id: '00000000-0000-4000-8000-000000000001' }) }]);
  assert.match(root.textContent, new RegExp(CREDENTIAL_MESSAGES.deleted));
  assert.match(root.textContent, new RegExp(CREDENTIAL_STATES.cleanup_pending.replace(/[()]/g, '\\$&')));
});

test('command_pending is shown honestly and the retry reuses the same intent, never a new act', async () => {
  const { sent, panel, byId, button, root } = panelWith([
    listed(),
    refusal(503, 'command_pending'),
    listed({ handle: H1, provider: 'claude', state: 'pending' }),
    [201, { handle: H1, provider: 'claude', state: 'stored_unbound' }],
    listed({ handle: H1, provider: 'claude', state: 'stored_unbound' })]);
  await panel.load();
  byId('credential-secret').value = SECRET;
  await button('키 저장').dispatch('click');
  await flush();
  assert.match(root.textContent, new RegExp(CREDENTIAL_ERRORS.command_pending));
  assert.match(root.textContent, new RegExp(CREDENTIAL_STATES.pending));
  assert.match(root.textContent, /결과 다시 확인/);
  assert.equal(byId('credential-secret').value, '');
  byId('credential-secret').value = 'sk-re-entered';
  await button('결과 다시 확인').dispatch('click');
  await flush();
  assert.equal(JSON.parse(sent[1][1].body).intent_id, JSON.parse(sent[3][1].body).intent_id);
  assert.match(root.textContent, new RegExp(CREDENTIAL_MESSAGES.created));
  assert.ok(!everything(root).includes(SECRET) && !everything(root).includes('sk-re-entered'));
});

test('secret_input_lost is terminal for the act: the next submit is a new intent', async () => {
  const { sent, panel, byId, button, root } = panelWith([
    listed(),
    refusal(409, 'secret_input_lost'),
    listed({ handle: H1, provider: 'claude', state: 'secret_input_lost' }),
    [201, { handle: 'b'.repeat(32), provider: 'claude', state: 'stored_unbound' }],
    listed()]);
  await panel.load();
  byId('credential-secret').value = SECRET;
  await button('키 저장').dispatch('click');
  await flush();
  assert.match(root.textContent, new RegExp(CREDENTIAL_ERRORS.secret_input_lost));
  assert.match(root.textContent, new RegExp(CREDENTIAL_STATES.secret_input_lost));
  assert.equal(root.findAll(el => el.tagName === 'LI')[0].findAll(el => el.tagName === 'BUTTON').length, 0);
  byId('credential-secret').value = SECRET;
  await button('키 저장').dispatch('click');
  await flush();
  assert.notEqual(JSON.parse(sent[1][1].body).intent_id, JSON.parse(sent[3][1].body).intent_id);
});

test('an unattached or unreachable gateway is shown as unavailable, with no list', async () => {
  const { panel, root } = panelWith([refusal(503, 'dependency_unavailable')]);
  await assert.rejects(panel.load());
  assert.match(root.textContent, new RegExp(CREDENTIAL_ERRORS.dependency_unavailable));
  assert.equal(root.findAll(el => el.tagName === 'LI').length, 0);
  const offline = panelWith([new Error('offline')]);
  await assert.rejects(offline.panel.load());
  assert.match(offline.root.textContent, new RegExp(CREDENTIAL_ERRORS.unavailable));
});

test('a pending delete retries under the same intent', async () => {
  const { sent, panel, root } = panelWith([
    listed({ handle: H1, provider: 'claude', state: 'stored_unbound' }),
    refusal(503, 'command_pending'),
    listed({ handle: H1, provider: 'claude', state: 'stored_unbound' }),
    [200, { handle: H1, state: 'cleanup_pending', provider_revocation: 'not_performed' }],
    listed({ handle: H1, provider: 'claude', state: 'cleanup_pending' })]);
  await panel.load();
  await assert.rejects(panel.remove(H1));
  assert.match(root.textContent, new RegExp(CREDENTIAL_ERRORS.command_pending));
  await panel.remove(H1);
  assert.equal(sent[1][1].body, sent[3][1].body);
});

// ---- binding heads, pending acts and the owner's fence (T090 binding slice)

const INTENT = '00000000-0000-4000-8000-00000000abcd';
const DUE = '2026-09-25T10:05:00.123456Z';
const DUE_MS = Date.parse('2026-09-25T10:05:00.123Z');

function clockedPanel(responses, start) {
  const timers = [];
  let at = start;
  const root = new FakeElement('section');
  const sent = [];
  let counter = 0;
  const fetch = async (path, options) => {
    sent.push([path, { ...options, body: options.body }]);
    const next = responses.shift();
    if (next instanceof Error) throw next;
    const [status, body] = next;
    return { ok: status < 400, status, json: async () => body };
  };
  const panel = createCredentialsPanel({ root, document, fetch, basePath: BASE, session: { csrfToken: () => CSRF },
    randomUUID: () => `00000000-0000-4000-8000-${String(++counter).padStart(12, '0')}`,
    now: () => at, setTimer: (callback, ms) => { timers.push({ callback, ms }); return timers.length; },
    clearTimer: handle => { timers[handle - 1].cleared = true; } });
  const button = text => root.findAll(el => el.tagName === 'BUTTON' && el.textContent === text)[0];
  const list = label => root.findAll(el => el.getAttribute('aria-label') === label)[0];
  const line = () => root.findAll(el => el.getAttribute('role') === 'status')[0];
  const field = () => root.findAll(el => el.getAttribute('id') === 'credential-secret')[0];
  return { root, sent, panel, timers, button, list, line, field, advance: ms => { at += ms; } };
}

const snapshot = ({ credentials = [], connections = [], pending_acts = [] }) => [200, {
  credentials: credentials.map(entry => ({ provider_revocation: 'not_performed', ...entry })), connections, pending_acts }];
const MODELS = ['synthetic-model-a', 'synthetic-model-b'];
const head = (handle, state, revision, catalog = 'absent', model_choice = 'absent', provider = 'claude',
  { gateway_head = 'applied', models = catalog === 'current' ? MODELS : [],
    chosen_model = model_choice === 'current' ? models[0] : null } = {}) =>
  ({ provider, state, handle, binding_revision: revision, catalog, model_choice, gateway_head, models, chosen_model });
const act = (overrides = {}) => ({ intent_id: INTENT, kind: 'rotate', handle: H1, provider: 'claude',
  state: 'command_pending', fence_available_at: DUE, uncertain_record: null, ...overrides });
const escaped = text => new RegExp(text.replace(/[()]/g, '\\$&'));

test('connections show binding state, revision and catalog/model presence; a head offers only refresh and choice', async () => {
  const H2 = 'b'.repeat(32);
  const { root, panel, list } = clockedPanel([snapshot({
    credentials: [{ handle: H1, provider: 'claude', state: 'stored_unbound' }, { handle: H2, provider: 'codex', state: 'cleanup_pending' }],
    connections: [head(H1, 'bound', 2, 'current', 'absent'), head(H2, 'revoked_pending_erasure', 3, 'absent', 'absent', 'codex')] })], 0);
  await panel.load();
  assert.deepEqual(panel.connections, [head(H1, 'bound', 2, 'current', 'absent'),
    head(H2, 'revoked_pending_erasure', 3, 'absent', 'absent', 'codex')]);
  const rows = list('제공자 연결').children;
  assert.equal(rows.length, 2);
  assert.equal(rows[0].children[0].textContent, `claude · ${CONNECTION_STATES.bound} · 키 ${H1} · 바인딩 수정본 2`);
  assert.match(rows[0].textContent, new RegExp(`${CONNECTION_MESSAGES.catalog.current} · ${CONNECTION_MESSAGES.model_choice.absent}`));
  assert.equal(rows[1].textContent, `codex · ${CONNECTION_STATES.revoked_pending_erasure} · 키 ${H2} · 바인딩 수정본 3`);
  assert.equal(rows[0].getAttribute('data-binding-revision'), '2');
  // the only acts on a bound head: the explicit refresh, and a choice from its catalog
  assert.deepEqual(rows[0].findAll(el => el.tagName === 'BUTTON').map(el => el.textContent),
    ['모델 목록 새로 고침', '이 모델 선택']);
  assert.deepEqual(rows[0].findAll(el => el.tagName === 'OPTION').map(el => el.getAttribute('value')), MODELS);
  assert.equal(rows[1].findAll(el => el.tagName === 'BUTTON').length, 0);
  // rotation voids the catalog/model choice until an explicit refresh, and the page says so
  assert.match(root.textContent, new RegExp(CONNECTION_MESSAGES.voids.replace(/[()]/g, '\\$&')));
  // the direct-adapter Claude connection is a separate key, and the page says so
  assert.match(root.textContent, new RegExp(CONNECTION_MESSAGES.independent.replace(/[()]/g, '\\$&')));
  // the credential row names the key the connection is bound to; the stale label is gone
  assert.match(list('저장된 자격증명').children[0].textContent, escaped(CONNECTION_MESSAGES.boundKey(2)));
  assert.ok(!root.textContent.includes('아직 모델 연결에 쓰이지 않음'));
  assert.ok(!list('저장된 자격증명').children[1].textContent.includes('이 제공자 연결에 쓰이는 키'));
});

test('a pending act shows when it can be fenced; the button appears only once due, with no request', async () => {
  const { sent, panel, timers, button, list, advance } = clockedPanel([snapshot({
    credentials: [{ handle: H1, provider: 'claude', state: 'stored_unbound' }],
    connections: [head(H1, 'bound', 1)],
    pending_acts: [act(), act({ intent_id: '00000000-0000-4000-8000-00000000beef', kind: 'delete', fence_available_at: null })] })],
  DUE_MS - 60_000);
  await panel.load();
  const rows = list('끝나지 않은 요청').children;
  assert.match(rows[0].textContent, escaped(PENDING_MESSAGES.command_pending));
  assert.match(rows[0].textContent, new RegExp(PENDING_MESSAGES.fenceAt('2026-09-25 10:05:00 UTC')));
  assert.match(rows[1].textContent, new RegExp(PENDING_MESSAGES.noFence));
  assert.equal(button('이 요청 차단'), undefined);
  assert.equal(timers.length, 1);
  assert.ok(timers[0].ms >= 60_000 && timers[0].ms < 61_000, String(timers[0].ms));
  advance(60_000);
  timers[0].callback();
  assert.ok(button('이 요청 차단'));
  assert.match(list('끝나지 않은 요청').children[0].textContent, new RegExp(PENDING_MESSAGES.fenceNow));
  // a delete act is never fenceable
  assert.equal(list('끝나지 않은 요청').children[1].findAll(el => el.tagName === 'BUTTON').length, 0);
  assert.equal(sent.length, 1);  // the re-render read nothing
});

const fenced = uncertain => [200, { intent_id: INTENT, state: 'fenced', uncertain_record: uncertain, provider_revocation: 'not_performed' }];

for (const [name, answer, expected, state] of [
  ['unknown -> fenced', fenced('unknown'), FENCE_RESULTS.fenced, 'fenced'],
  ['committed -> orphan retired', fenced('cleanup_pending'), FENCE_RESULTS.orphan_retired, 'orphan_retired'],
  ['committed -> orphan retirement pending', fenced('retirement_pending'), FENCE_RESULTS.orphan_retiring, 'orphan_retiring'],
  ['lost', refusal(409, 'secret_input_lost'), FENCE_RESULTS.secret_input_lost, 'secret_input_lost'],
  ['still pending', refusal(503, 'command_pending'), FENCE_RESULTS.still_pending, 'still_pending'],
  ['not yet due', refusal(409, 'fence_not_due'), FENCE_RESULTS.fence_not_due, 'fence_not_due'],
]) {
  test(`the fence posts only the intent with CSRF and shows the result: ${name}`, async () => {
    const after = state === 'still_pending' || state === 'fence_not_due' ? [act()]
      : state === 'secret_input_lost' ? []
        : [act({ state: 'fenced', fence_available_at: null, uncertain_record: answer[1].uncertain_record })];
    const { root, sent, button, panel, line } = clockedPanel(
      [snapshot({ pending_acts: [act()] }), answer, snapshot({ pending_acts: after })], DUE_MS);
    await panel.load();
    await button('이 요청 차단').dispatch('click');
    await flush();
    assert.deepEqual(sent[1], [`${PATH}/fences`, { method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-DeepTwin-CSRF': CSRF },
      body: JSON.stringify({ intent_id: INTENT }) }]);
    assert.equal(sent.length, 3);  // the fence, then a ledger-only re-read
    assert.equal(sent[2][1].method, 'GET');
    assert.equal(line().textContent, expected);
    assert.equal(line().dataset.state, state);
    if (state === 'fenced' || state.startsWith('orphan_')) {
      assert.match(root.textContent, escaped(`${PENDING_MESSAGES.fenced}: ${PENDING_MESSAGES.uncertain[answer[1].uncertain_record]}`));
      assert.equal(button('이 요청 차단'), undefined);
    } else if (state !== 'secret_input_lost') {
      assert.ok(button('이 요청 차단'));  // still unresolved: the owner may try again
    }
  });
}

test('fencing the page\'s own unconfirmed store ends its retry mode: the next submit is a new act', async () => {
  const own = '00000000-0000-4000-8000-000000000001';
  const { sent, panel, button, root, field } = clockedPanel([
    snapshot({}),
    refusal(503, 'command_pending'),
    snapshot({ pending_acts: [act({ intent_id: own, kind: 'create' })] }),
    [200, { intent_id: own, state: 'fenced', uncertain_record: 'unknown', provider_revocation: 'not_performed' }],
    snapshot({ pending_acts: [act({ intent_id: own, kind: 'create', state: 'fenced', fence_available_at: null, uncertain_record: 'unknown' })] }),
    [201, { handle: H1, provider: 'claude', state: 'stored_unbound' }],
    snapshot({})], DUE_MS);
  await panel.load();
  field().value = SECRET;
  await button('키 저장').dispatch('click');
  await flush();
  assert.ok(button('결과 다시 확인'));
  await button('이 요청 차단').dispatch('click');
  await flush();
  assert.ok(button('키 저장') && !button('결과 다시 확인'));
  field().value = SECRET;
  await button('키 저장').dispatch('click');
  await flush();
  assert.equal(JSON.parse(sent[1][1].body).intent_id, own);
  assert.notEqual(JSON.parse(sent[5][1].body).intent_id, own);
  assert.ok(!everything(root).includes(SECRET));
});

test('connection_bound and connection_conflict are shown with their exact messages', async () => {
  assert.equal(CREDENTIAL_ERRORS.connection_bound, '이 제공자에는 이미 연결된 키가 있습니다. 새 키로 바꾸려면 교체를 사용하세요.');
  assert.equal(CREDENTIAL_ERRORS.connection_conflict, '저장하는 동안 제공자 연결이 바뀌었습니다. 이번 키는 연결하지 않고 정리합니다.');
  for (const code of ['connection_bound', 'connection_conflict']) {
    const { root, panel, button, line, field } = clockedPanel([snapshot({}), refusal(409, code), snapshot({})], 0);
    await panel.load();
    field().value = SECRET;
    await button('키 저장').dispatch('click');
    await flush();
    assert.equal(line().textContent, CREDENTIAL_ERRORS[code]);
    assert.equal(line().dataset.state, code);
    assert.equal(field().value, '');
    assert.ok(button('키 저장'));  // not a retry: a refused act starts over
    assert.ok(!everything(root).includes(SECRET));
  }
});

test('a malformed binding head or pending act is refused as unavailable, nothing listed', async () => {
  for (const bad of [{ connections: [head(H1, 'bound', 0)] }, { connections: [head(H1, 'maybe', 1)] },
    { connections: [head(H1, 'bound', 1, 'stale')] },
    { pending_acts: [act({ fence_available_at: '2026-09-25 10:05' })] }, { pending_acts: [act({ state: 'unknown' })] },
    { pending_acts: [act({ uncertain_record: 'bound' })] }]) {
    const { root, panel } = clockedPanel([snapshot(bad)], 0);
    await assert.rejects(panel.load());
    assert.equal(root.findAll(el => el.tagName === 'LI').length, 0);
    assert.match(root.textContent, new RegExp(CREDENTIAL_ERRORS.unavailable));
  }
});

// ---- explicit catalog refresh and model choice (T090 refresh slice)

const catalogReceipt = (revision, models = MODELS, chosen = null) =>
  [200, { provider: 'claude', binding_revision: revision, catalog: 'current', models, chosen_model: chosen }];
const REFRESH = `${PATH}/connections/claude/catalog-refresh`;
const CHOICE = `${PATH}/connections/claude/model-choice`;

test('the refresh button posts only a fresh intent with CSRF, then re-reads the ledger', async () => {
  const { sent, panel, button, list, line } = clockedPanel([
    snapshot({ credentials: [{ handle: H1, provider: 'claude', state: 'stored_unbound' }], connections: [head(H1, 'bound', 1)] }),
    catalogReceipt(1),
    snapshot({ credentials: [{ handle: H1, provider: 'claude', state: 'stored_unbound' }], connections: [head(H1, 'bound', 1, 'current')] }),
  ], 0);
  await panel.load();
  // no catalog yet: a refresh button, no model select
  let row = list('제공자 연결').children[0];
  assert.equal(row.findAll(el => el.tagName === 'SELECT').length, 0);
  await button('모델 목록 새로 고침').dispatch('click');
  await flush();
  assert.equal(sent.length, 3);
  const [path, options] = sent[1];
  assert.equal(path, REFRESH);
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-DeepTwin-CSRF'], CSRF);
  assert.deepEqual(JSON.parse(options.body), { intent_id: '00000000-0000-4000-8000-000000000001' });
  assert.equal(sent[2][0], PATH);
  assert.equal(line().dataset.state, 'catalog_refreshed');
  assert.equal(line().textContent, CATALOG_RESULTS.refreshed(1, 2));
  row = list('제공자 연결').children[0];
  assert.deepEqual(row.findAll(el => el.tagName === 'OPTION').map(el => el.textContent), MODELS);
  // a second click is a new refresh act (a new intent)
  const again = clockedPanel([snapshot({ connections: [head(H1, 'bound', 1)] }), catalogReceipt(1),
    snapshot({ connections: [head(H1, 'bound', 1, 'current')] }), catalogReceipt(1),
    snapshot({ connections: [head(H1, 'bound', 1, 'current')] })], 0);
  await again.panel.load();
  await again.panel.refreshCatalog('claude');
  await again.panel.refreshCatalog('claude');
  const intents = again.sent.filter(([target]) => target === REFRESH).map(([, value]) => JSON.parse(value.body).intent_id);
  assert.equal(new Set(intents).size, 2);
});

test('a model choice names the binding revision and a listed model; the choice is shown', async () => {
  const { sent, panel, button, list, line, root } = clockedPanel([
    snapshot({ connections: [head(H1, 'bound', 3, 'current')] }),
    [200, { provider: 'claude', binding_revision: 3, model: MODELS[1] }],
    snapshot({ connections: [head(H1, 'bound', 3, 'current', 'current', 'claude', { chosen_model: MODELS[1] })] }),
  ], 0);
  await panel.load();
  const select = list('제공자 연결').findAll(el => el.tagName === 'SELECT')[0];
  assert.equal(select.value, MODELS[0]);
  select.value = MODELS[1];
  await button('이 모델 선택').dispatch('click');
  await flush();
  assert.equal(sent[1][0], CHOICE);
  assert.equal(sent[1][1].headers['X-DeepTwin-CSRF'], CSRF);
  assert.deepEqual(JSON.parse(sent[1][1].body), { binding_revision: 3, model: MODELS[1] });
  assert.equal(line().dataset.state, 'model_chosen');
  assert.equal(line().textContent, CATALOG_RESULTS.chosen(MODELS[1]));
  assert.match(root.textContent, new RegExp(CONNECTION_MESSAGES.chosen(MODELS[1])));
  assert.equal(list('제공자 연결').findAll(el => el.tagName === 'SELECT')[0].value, MODELS[1]);
});

for (const [status, code] of [[409, 'catalog_stale'], [409, 'binding_refused'], [424, 'provider_rejected'],
  [503, 'provider_unavailable'], [409, 'connection_unbound']]) {
  test(`a refresh refused as ${code} is shown with its message and leaves no catalog`, async () => {
    const { panel, line, list } = clockedPanel([snapshot({ connections: [head(H1, 'bound', 2)] }), refusal(status, code),
      snapshot({ connections: [head(H1, 'bound', 2)] })], 0);
    await panel.load();
    await assert.rejects(panel.refreshCatalog('claude'));
    await flush();
    assert.equal(line().dataset.state, code);
    assert.equal(line().textContent, CREDENTIAL_ERRORS[code]);
    assert.equal(list('제공자 연결').findAll(el => el.tagName === 'SELECT').length, 0);
  });
}

test('a model no longer listed, or a stale revision, is refused with its message', async () => {
  for (const code of ['model_not_listed', 'catalog_stale']) {
    const { panel, line } = clockedPanel([snapshot({ connections: [head(H1, 'bound', 1, 'current')] }), refusal(409, code),
      snapshot({ connections: [head(H1, 'bound', 1, 'current')] })], 0);
    await panel.load();
    await assert.rejects(panel.chooseModel('claude', 1, MODELS[0]));
    assert.equal(line().dataset.state, code);
    assert.equal(line().textContent, CREDENTIAL_ERRORS[code]);
  }
});

test('an unlistable provider offers no refresh, and an unacknowledged head says so', async () => {
  const H2 = 'b'.repeat(32);
  const { panel, list } = clockedPanel([snapshot({ connections: [
    head(H1, 'bound', 2, 'absent', 'absent', 'claude', { gateway_head: 'pending' }),
    head(H2, 'bound', 1, 'absent', 'absent', 'codex')] })], 0);
  await panel.load();
  const [claude, codex] = list('제공자 연결').children;
  assert.equal(claude.getAttribute('data-gateway-head'), 'pending');
  assert.match(claude.textContent, new RegExp(CONNECTION_MESSAGES.gatewayPending));
  assert.equal(codex.findAll(el => el.tagName === 'BUTTON').length, 0);
  assert.match(codex.textContent, new RegExp(CONNECTION_MESSAGES.notListable));
});

test('a malformed catalog in the status read is refused as unavailable', async () => {
  for (const bad of [head(H1, 'bound', 1, 'absent', 'absent', 'claude', { models: MODELS }),
    head(H1, 'bound', 1, 'current', 'current', 'claude', { chosen_model: 'synthetic-model-z' }),
    head(H1, 'bound', 1, 'current', 'absent', 'claude', { models: ['bad model'] }),
    head(H1, 'bound', 1, 'absent', 'absent', 'claude', { gateway_head: 'maybe' })]) {
    const { root, panel } = clockedPanel([snapshot({ connections: [bad] })], 0);
    await assert.rejects(panel.load());
    assert.equal(root.findAll(el => el.tagName === 'LI').length, 0);
  }
});
