// T023/T025 (experience.md §5.1 items 4–6): the first work screen on the supported
// factory over `works-v1`. After the owner session is established the page shows
// the retention notices, asks `어떤 일을 맡기고 싶으세요?`, keeps an unsaved draft in
// this browser only (said so, never claimed as instance storage), and saves the
// explanation as a work revision on the instance under an idempotent command; a
// stale revision is a conflict the owner resolves. No session → the start screen
// is named and nothing that could send a command is mounted. Tested over a fake
// document/fetch/storage; the browser case stays T049's.

import test from 'node:test';
import assert from 'node:assert/strict';

import { MAX_TEXT_BYTES, MAX_TEXT_CHARS, MOUNT_IDS, boot, bootPage, storageKey } from '../static/work.mjs';

const HEX = '2'.repeat(32);
const BASE = `/${HEX}/`;
const WORK = '00000000-0000-4000-8000-0000000000a1';

class FakeElement {
  constructor(tagName) {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.listeners = new Map();
    this.hidden = false;
    this.disabled = false;
    this.value = '';
    this.type = '';
    this._text = '';
  }

  get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }

  set textContent(value) { this._text = String(value); this.children = []; }

  append(...nodes) { this.children.push(...nodes); }

  replaceChildren(...nodes) { this.children = [...nodes]; this._text = ''; }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }

  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }

  addEventListener(type, listener) { this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]); }

  async dispatch(type) {
    let prevented = false;
    for (const listener of this.listeners.get(type) ?? []) await listener({ preventDefault() { prevented = true; } });
    return prevented;
  }

  find(predicate) {
    for (const child of this.children) {
      if (predicate(child)) return child;
      const found = child.find(predicate);
      if (found) return found;
    }
    return null;
  }
}

function fakeDocument() {
  const byId = new Map(Object.values(MOUNT_IDS).map(id => [id, new FakeElement(id.endsWith('form') ? 'form' : 'section')]));
  return { createElement: tag => new FakeElement(tag), getElementById: id => byId.get(id) ?? null, elements: byId };
}

function fakeStorage(initial = {}) {
  const map = new Map(Object.entries(initial));
  return { getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, String(value)),
    removeItem: key => map.delete(key), map };
}

function jsonResponse(status, payload) {
  return { ok: status >= 200 && status < 300, status, async json() { return payload; } };
}

const SESSION = () => jsonResponse(200, { state: 'authenticated', csrf_token: 't' });
const revision = (n, text) => ({ work_id: WORK, revision: n, text,
  ref: { kind: 'work_revision', id: WORK, version: n, sha256: 'a'.repeat(64) }, created_at_utc: '2026-09-18T00:00:00.000000Z' });

function booted(replies, { storage = fakeStorage(), pathname = BASE } = {}) {
  const fetched = [];
  const document = fakeDocument();
  const navigated = [];
  const location = { pathname, assign: url => navigated.push(url) };
  let counter = 0;
  const crypto = { subtle: globalThis.crypto.subtle, randomUUID: () => `00000000-0000-4000-8000-00000000c0${String(++counter).padStart(2, '0')}` };
  const promise = boot({
    document, location, crypto, storage,
    fetch: async (path, options) => { fetched.push([path, options]); const reply = replies.shift(); if (reply instanceof Error) throw reply; return reply; },
  });
  return { promise, fetched, document, navigated, storage, crypto };
}

const field = (document, id) => document.getElementById(id);
const textarea = document => field(document, 'work-form').find(el => el.dataset.field === 'text');

test('the bounds mirror the works route and the storage key is per deployment', () => {
  assert.deepEqual(MOUNT_IDS, { session: 'session-status', notice: 'intake-notice', form: 'work-form',
    save: 'save-status', materials: 'materials', link: 'observe-link' });
  assert.equal(MAX_TEXT_CHARS, 20_000);
  assert.equal(MAX_TEXT_BYTES, 65_536);
  assert.equal(storageKey(BASE), `deeptwin:intake:${BASE}`);
  assert.notEqual(storageKey('/'), storageKey(BASE));
});

test('without a session the start screen is named and nothing that could send a command is mounted', async () => {
  const { promise, fetched, document, navigated } = booted([jsonResponse(401, { code: 'unauthenticated' })]);
  const result = await promise;
  assert.equal(result.mode, 'unauthenticated');
  assert.deepEqual(fetched.map(([path]) => path), [`${BASE}session`]);
  assert.equal(field(document, 'work-form').hidden, true);
  assert.equal(field(document, 'session-status').dataset.state, 'unauthenticated');
  assert.match(field(document, 'session-status').textContent, /시작 화면/);
  assert.deepEqual(navigated, []);
  assert.equal(field(document, 'work-form').listeners.size, 0);
});

test('a new work is asked for, kept as a browser draft, and saved on the instance under one command', async () => {
  const { promise, fetched, document, storage } = booted([SESSION(), jsonResponse(201, revision(1, '보고서 요약'))]);
  const result = await promise;
  assert.equal(result.mode, 'new');
  const form = field(document, 'work-form');
  assert.equal(form.hidden, false);
  assert.match(form.textContent, /어떤 일을 맡기고 싶으세요\?/);
  // item 4: the notices — local retention scope, when external transmission happens, nothing
  // sent to the maker — with a detail
  const notice = field(document, 'intake-notice').textContent;
  assert.match(notice, /이 인스턴스/);
  assert.match(notice, /외부 모델/);
  assert.match(notice, /제작자/);
  // item 5: materials and the microphone are not on this factory yet — said, not faked
  const materials = field(document, 'materials');
  assert.match(form.textContent, /자료 추가/);
  assert.equal(form.find(el => el.tagName === 'BUTTON' && el.textContent === '자료 추가')?.disabled, false);
  assert.match(materials.textContent, /아직/);
  assert.equal(field(document, 'observe-link').find(el => el.tagName === 'A').getAttribute('href'), './observe.html');
  // an empty submit sends nothing
  const area = textarea(document);
  assert.equal(area.tagName, 'TEXTAREA');
  assert.equal(await form.dispatch('submit'), true);
  assert.equal(fetched.length, 1);
  assert.equal(field(document, 'save-status').dataset.state, 'invalid_input');
  // typing keeps a draft in this browser only, and says so
  area.value = '보고서 요약';
  await area.dispatch('input');
  assert.match(field(document, 'save-status').textContent, /이 브라우저/);
  assert.match(field(document, 'save-status').textContent, /인스턴스에 저장되지 않/);
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).draft_text, '보고서 요약');
  // the save: one command, persisted before the send so a retry replays it
  assert.equal(await form.dispatch('submit'), true);
  assert.equal(fetched.length, 2);
  const [path, options] = fetched[1];
  assert.equal(path, `${BASE}api/v1/works`);
  assert.equal(options.method, 'POST');
  assert.equal(options.headers['X-DeepTwin-CSRF'], 't');
  const body = JSON.parse(options.body);
  assert.deepEqual(body, { schema_version: 'work-create-command-v1', command_id: '00000000-0000-4000-8000-00000000c001', text: '보고서 요약' });
  const stored = JSON.parse(storage.getItem(storageKey(BASE)));
  assert.equal(stored.work_id, WORK);
  assert.equal(stored.revision, 1);
  assert.equal(stored.draft_text, undefined);
  assert.equal(stored.pending_command_id, undefined);
  assert.equal(field(document, 'save-status').dataset.state, 'saved');
  assert.match(field(document, 'save-status').textContent, /인스턴스에 저장됨/);
  assert.match(field(document, 'save-status').textContent, /수정본 1/);
});

test('a stored work is reopened, revised under its expected revision, and a stale one is a conflict the owner resolves', async () => {
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1 }) });
  const { promise, fetched, document } = booted([
    SESSION(), jsonResponse(200, revision(1, '보고서 요약')),
    jsonResponse(201, revision(2, '보고서를 세 문단으로 요약')),
    jsonResponse(409, { code: 'conflict' }),
    jsonResponse(200, revision(3, '다른 화면의 수정')),
  ], { storage });
  const result = await promise;
  assert.equal(result.mode, 'open');
  assert.equal(fetched[1][0], `${BASE}api/v1/works/${WORK}`);
  const area = textarea(document);
  assert.equal(area.value, '보고서 요약');
  assert.match(field(document, 'save-status').textContent, /수정본 1/);
  area.value = '보고서를 세 문단으로 요약';
  await area.dispatch('input');
  const form = field(document, 'work-form');
  await form.dispatch('submit');
  const body = JSON.parse(fetched[2][1].body);
  assert.equal(fetched[2][0], `${BASE}api/v1/works/${WORK}/revisions`);
  assert.deepEqual(body, { schema_version: 'work-revise-command-v1', command_id: '00000000-0000-4000-8000-00000000c001',
    expected_revision: 1, text: '보고서를 세 문단으로 요약' });
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).revision, 2);
  assert.match(field(document, 'save-status').textContent, /수정본 2/);
  // a conflict: another screen revised first — the draft is kept, the saved one reopens only on the owner's click
  area.value = '내 편집';
  await area.dispatch('input');
  await form.dispatch('submit');
  assert.equal(field(document, 'save-status').dataset.state, 'conflict');
  assert.match(field(document, 'save-status').textContent, /다른 화면/);
  assert.equal(area.value, '내 편집');
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).draft_text, '내 편집');
  const reopen = field(document, 'save-status').find(el => el.tagName === 'BUTTON');
  assert.match(reopen.textContent, /다시 열기/);
  await reopen.dispatch('click');
  assert.equal(fetched[4][0], `${BASE}api/v1/works/${WORK}`);
  assert.equal(area.value, '다른 화면의 수정');
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).revision, 3);
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).draft_text, undefined);
});

test('a draft survives a failed save and a lost connection, and a pending command is replayed', async () => {
  const { promise, fetched, document, storage } = booted([
    SESSION(), new TypeError('offline'), jsonResponse(201, revision(1, '초안')),
  ]);
  await promise;
  const area = textarea(document);
  const form = field(document, 'work-form');
  area.value = '초안';
  await area.dispatch('input');
  await form.dispatch('submit');
  assert.equal(field(document, 'save-status').dataset.state, 'unavailable');
  assert.match(field(document, 'save-status').textContent, /연결하지 못했/);  // offline, not a server failure
  assert.match(field(document, 'save-status').textContent, /이 브라우저/);
  assert.equal(area.value, '초안');
  const pending = JSON.parse(storage.getItem(storageKey(BASE)));
  assert.equal(pending.draft_text, '초안');
  assert.equal(pending.pending_command.payload.command_id, '00000000-0000-4000-8000-00000000c001');
  await form.dispatch('submit');
  assert.equal(JSON.parse(fetched[2][1].body).command_id, '00000000-0000-4000-8000-00000000c001');  // the same command
  assert.equal(field(document, 'save-status').dataset.state, 'saved');
});

test('a browser draft is restored on reopen and said to be this browser\'s only', async () => {
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, draft_text: '고친 초안' }) });
  const { promise, document } = booted([SESSION(), jsonResponse(200, revision(1, '보고서 요약'))], { storage });
  await promise;
  assert.equal(textarea(document).value, '고친 초안');
  assert.match(field(document, 'save-status').textContent, /이 브라우저에만/);
  assert.match(field(document, 'save-status').textContent, /수정본 1/);
});

test('a stored work the instance no longer has is forgotten and the form starts new', async () => {
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1 }) });
  const { promise, document } = booted([SESSION(), jsonResponse(404, { code: 'not_found' })], { storage });
  const result = await promise;
  assert.equal(result.mode, 'new');
  assert.equal(storage.getItem(storageKey(BASE)), null);
  assert.equal(textarea(document).value, '');
});

test('the client mirrors the route\'s bounds and names the limit', async () => {
  const { promise, fetched, document } = booted([SESSION()]);
  await promise;
  const area = textarea(document);
  const form = field(document, 'work-form');
  area.value = '가'.repeat(MAX_TEXT_CHARS + 1);
  await form.dispatch('submit');
  assert.equal(fetched.length, 1);
  assert.match(field(document, 'save-status').textContent, /20,000|20000/);
  area.value = '\u{1F600}'.repeat(16_385);  // 65 540 bytes under the character bound
  await form.dispatch('submit');
  assert.equal(fetched.length, 1);
  assert.match(field(document, 'save-status').textContent, /65,536|65536/);
});

test('a session that ends mid-way names the start screen; a page whose boot fails still reaches the status line', async () => {
  const { promise, document, navigated } = booted([SESSION(), jsonResponse(401, { code: 'unauthenticated' })]);
  await promise;
  const area = textarea(document);
  area.value = '설명';
  await field(document, 'work-form').dispatch('submit');
  assert.equal(field(document, 'save-status').dataset.state, 'unauthenticated');
  assert.match(field(document, 'save-status').textContent, /시작 화면/);
  assert.deepEqual(navigated, []);
  const broken = await bootPage({ document: fakeDocument(), location: { pathname: BASE, assign() {} },
    crypto: { randomUUID: () => 'x' }, fetch: 'not a function' });
  assert.equal(broken, null);
  // storage failures never break the page
  const throwing = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); } };
  const { promise: quiet, document: doc2 } = booted([SESSION(), jsonResponse(201, revision(1, 'x'))], { storage: throwing });
  assert.equal((await quiet).mode, 'new');
  textarea(doc2).value = 'x';
  await field(doc2, 'work-form').dispatch('submit');
  assert.equal(field(doc2, 'save-status').dataset.state, 'saved');
});


test('a lost send is settled with its own text before an edited draft is saved as the next revision', async () => {
  // review MUST: the pending command is bound to the text it was minted for; the owner's
  // edit never rides on a spent command (a conflict blamed on "another screen"), and the
  // sentence the lost send may have sealed is not orphaned — it is completed first
  const { promise, fetched, document, storage } = booted([
    SESSION(), new TypeError('offline'),
    jsonResponse(201, revision(1, 'A')), jsonResponse(201, revision(2, 'B')),
  ]);
  await promise;
  const area = textarea(document);
  const form = field(document, 'work-form');
  area.value = 'A';
  await area.dispatch('input');
  await form.dispatch('submit');
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).pending_command.payload.text, 'A');
  area.value = 'B';
  await area.dispatch('input');
  await form.dispatch('submit');
  assert.equal(fetched.length, 4);
  assert.deepEqual(JSON.parse(fetched[2][1].body), { schema_version: 'work-create-command-v1',
    command_id: '00000000-0000-4000-8000-00000000c001', text: 'A' });
  assert.deepEqual(JSON.parse(fetched[3][1].body), { schema_version: 'work-revise-command-v1',
    command_id: '00000000-0000-4000-8000-00000000c002', expected_revision: 1, text: 'B' });
  const stored = JSON.parse(storage.getItem(storageKey(BASE)));
  assert.equal(stored.revision, 2);
  assert.equal(stored.pending_command_id, undefined);
  assert.equal(stored.draft_text, undefined);
  assert.match(field(document, 'save-status').textContent, /수정본 2/);
});

test('a conflict before any work exists never offers a reopen of nothing', async () => {
  const { promise, document, storage } = booted([SESSION(), jsonResponse(409, { code: 'conflict' })]);
  await promise;
  const area = textarea(document);
  area.value = 'A';
  await field(document, 'work-form').dispatch('submit');
  assert.equal(field(document, 'save-status').dataset.state, 'conflict');
  assert.equal(field(document, 'save-status').find(el => el.tagName === 'BUTTON'), null);
  assert.doesNotMatch(field(document, 'save-status').textContent, /다른 화면/);
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).pending_command_id, undefined);
  assert.equal(area.value, 'A');
});

test('legacy pending state without an exact original revision keeps an unresolved draft', async () => {
  // review MUST: the draft was the only copy of the sentence
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1,
    draft_text: '소유자의 미저장 문장', pending_command_id: '00000000-0000-4000-8000-00000000c0aa', pending_text: 'x' }) });
  const { promise, document } = booted([SESSION(), jsonResponse(404, { code: 'not_found' })], { storage });
  const result = await promise;
  assert.equal(result.mode, 'open');
  assert.equal(textarea(document).value, '소유자의 미저장 문장');
  assert.match(field(document, 'save-status').textContent, /원래 수정본/);
  await field(document, 'work-form').dispatch('submit');
  assert.equal(textarea(document).value, '소유자의 미저장 문장');
});

test('a revision that meets a vanished work forgets the work, keeps the draft, and the next save creates', async () => {
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1 }) });
  const { promise, fetched, document } = booted([
    SESSION(), jsonResponse(200, revision(1, '저장본')), jsonResponse(404, { code: 'not_found' }),
    jsonResponse(201, { ...revision(1, '고침'), work_id: '00000000-0000-4000-8000-0000000000b2' }),
  ], { storage });
  await promise;
  const area = textarea(document);
  const form = field(document, 'work-form');
  area.value = '고침';
  await area.dispatch('input');
  await form.dispatch('submit');
  assert.equal(field(document, 'save-status').dataset.state, 'not_found');
  assert.equal(area.value, '고침');
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).work_id, undefined);
  await form.dispatch('submit');
  assert.equal(fetched[3][0], `${BASE}api/v1/works`);
  assert.equal(JSON.parse(storage.getItem(storageKey(BASE))).work_id, '00000000-0000-4000-8000-0000000000b2');
});

test('a draft keeps the revision it was based on, so another screen\'s save is a conflict, not a silent overwrite', async () => {
  // review SHOULD: the draft's base revision travels with it across a reload
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, base_revision: 1, draft_text: '내 초안' }) });
  const { promise, fetched, document } = booted([
    SESSION(), jsonResponse(200, revision(2, '다른 화면의 저장')), jsonResponse(409, { code: 'conflict' }),
  ], { storage });
  await promise;
  const area = textarea(document);
  assert.equal(area.value, '내 초안');
  assert.equal(field(document, 'save-status').dataset.state, 'conflict');
  assert.match(field(document, 'save-status').textContent, /다른 화면/);
  assert.match(field(document, 'save-status').textContent, /수정본 2/);
  assert.notEqual(field(document, 'save-status').find(el => el.tagName === 'BUTTON'), null);
  await field(document, 'work-form').dispatch('submit');
  assert.equal(JSON.parse(fetched[2][1].body).expected_revision, 1);  // the base, never the refreshed latest
  assert.equal(field(document, 'save-status').dataset.state, 'conflict');
  // typing on a clean saved work records the base
  const clean = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 2 }) });
  const second = booted([SESSION(), jsonResponse(200, revision(2, '저장본'))], { storage: clean });
  await second.promise;
  textarea(second.document).value = '편집';
  await textarea(second.document).dispatch('input');
  assert.equal(JSON.parse(clean.getItem(storageKey(BASE))).base_revision, 2);
});

test('tampered or corrupt storage is dropped field by field and never steers a request', async () => {
  for (const bad of [{ work_id: 'x/y', revision: 1 }, { work_id: 42, revision: 1 }, { work_id: WORK, revision: '1' },
    { work_id: WORK, revision: 0 }, { pending_command_id: '../x', draft_text: 'ok' }, 'junk', [1]]) {
    const storage = fakeStorage({ [storageKey(BASE)]: typeof bad === 'string' ? bad : JSON.stringify(bad) });
    const { promise, fetched, document } = booted([SESSION(), jsonResponse(201, revision(1, 'ok'))], { storage });
    const result = await promise;
    assert.equal(result.mode, 'new', JSON.stringify(bad));
    assert.equal(fetched.length, 1, JSON.stringify(bad));
    const area = textarea(document);
    if (bad?.draft_text) assert.equal(area.value, 'ok');
    area.value = 'ok';
    await field(document, 'work-form').dispatch('submit');
    assert.equal(fetched[1][0], `${BASE}api/v1/works`, JSON.stringify(bad));
    assert.equal(JSON.parse(fetched[1][1].body).command_id, '00000000-0000-4000-8000-00000000c001', JSON.stringify(bad));
  }
});

test('a rotated session token is repaired once by re-establishing, not blamed on the address', async () => {
  // review SHOULD: 403 on a command means the token no longer matches the cookie (the owner
  // logged in again elsewhere); the page re-establishes and retries once
  const { promise, fetched, document } = booted([
    SESSION(), jsonResponse(403, { code: 'access_denied' }),
    jsonResponse(200, { state: 'authenticated', csrf_token: 't2' }), jsonResponse(201, revision(1, 'x')),
  ]);
  await promise;
  textarea(document).value = 'x';
  await field(document, 'work-form').dispatch('submit');
  assert.deepEqual(fetched.map(([path]) => path), [`${BASE}session`, `${BASE}api/v1/works`, `${BASE}session`, `${BASE}api/v1/works`]);
  assert.equal(fetched[3][1].headers['X-DeepTwin-CSRF'], 't2');
  assert.equal(field(document, 'save-status').dataset.state, 'saved');
  // a second refusal is said as such
  const again = booted([SESSION(), jsonResponse(403, { code: 'access_denied' }),
    jsonResponse(200, { state: 'authenticated', csrf_token: 't2' }), jsonResponse(403, { code: 'access_denied' })]);
  await again.promise;
  textarea(again.document).value = 'x';
  await field(again.document, 'work-form').dispatch('submit');
  assert.equal(field(again.document, 'save-status').dataset.state, 'access_denied');
  assert.match(field(again.document, 'save-status').textContent, /다시 열어/);
});

test('a save in flight ignores a second submit, and the notices claim only what holds', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const { promise, fetched, document } = booted([SESSION(), { ok: true, status: 201, async json() { await gate; return revision(1, 'x'); } }]);
  await promise;
  textarea(document).value = 'x';
  const form = field(document, 'work-form');
  const first = form.dispatch('submit');
  const second = form.dispatch('submit');
  release();
  await Promise.all([first, second]);
  assert.equal(fetched.length, 2);
  const notice = field(document, 'intake-notice').textContent;
  assert.match(notice, /저장한 설명/);
  assert.match(notice, /이 브라우저/);
  assert.doesNotMatch(notice, /연결된 제공자가 없습니다/);  // instance state is not claimed from the page
  assert.match(notice, /아무것도 전송하지 않/);
});


test('an exactly reconstructible legacy pending send resolves its command receipt before latest revision', async () => {
  // Matching text is not command evidence: query its exact receipt before reading latest.
  const PENDING = '00000000-0000-4000-8000-00000000c0aa';
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, base_revision: 1,
    draft_text: 'A', pending_command_id: PENDING, pending_text: 'A' }) });
  const { promise, document } = booted([SESSION(), jsonResponse(200, revision(2, 'A')), jsonResponse(200, revision(2, 'A'))], { storage });
  await promise;
  assert.deepEqual(JSON.parse(storage.getItem(storageKey(BASE))), { work_id: WORK, revision: 2 });
  assert.equal(field(document, 'save-status').dataset.state, 'saved');
  assert.match(field(document, 'save-status').textContent, /수정본 2/);
  // the owner had already edited to B before the reload: B is a draft on rev 2, not a conflict
  const edited = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, base_revision: 1,
    draft_text: 'B', pending_command_id: PENDING, pending_text: 'A' }) });
  const second = booted([SESSION(), jsonResponse(200, revision(2, 'A')), jsonResponse(200, revision(2, 'A')), jsonResponse(201, revision(3, 'B'))], { storage: edited });
  await second.promise;
  assert.equal(field(second.document, 'save-status').dataset.state, 'draft');
  assert.equal(textarea(second.document).value, 'B');
  assert.deepEqual(JSON.parse(edited.getItem(storageKey(BASE))), { work_id: WORK, revision: 2, base_revision: 2, draft_text: 'B' });
  await field(second.document, 'work-form').dispatch('submit');
  const body = JSON.parse(second.fetched[3][1].body);
  assert.equal(body.expected_revision, 2);
  assert.equal(body.command_id, '00000000-0000-4000-8000-00000000c001');  // a fresh command, the pending one is spent
  assert.equal(field(second.document, 'save-status').dataset.state, 'saved');
});

test('text typed while a save is in flight stays a browser draft, never reported as saved', async () => {
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  const { promise, document, storage } = booted([SESSION(), { ok: true, status: 201, async json() { await gate; return revision(1, 'A'); } }]);
  await promise;
  const area = textarea(document);
  area.value = 'A';
  const saving = field(document, 'work-form').dispatch('submit');
  area.value = 'A plus more';
  await area.dispatch('input');
  release();
  await saving;
  assert.equal(field(document, 'save-status').dataset.state, 'draft');
  assert.match(field(document, 'save-status').textContent, /수정본 1/);
  const stored = JSON.parse(storage.getItem(storageKey(BASE)));
  assert.equal(stored.draft_text, 'A plus more');
  assert.equal(stored.base_revision, 1);
  assert.equal(area.value, 'A plus more');
});

test('a conflict also offers to keep the draft on top of the latest revision', async () => {
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, base_revision: 1, draft_text: '내 초안' }) });
  const { promise, fetched, document } = booted([
    SESSION(), jsonResponse(200, revision(2, '다른 화면의 저장')), jsonResponse(200, revision(2, '다른 화면의 저장')),
    jsonResponse(201, revision(3, '내 초안')),
  ], { storage });
  await promise;
  assert.equal(field(document, 'save-status').dataset.state, 'conflict');
  const buttons = [];
  field(document, 'save-status').children.forEach(child => { if (child.tagName === 'BUTTON') buttons.push(child); });
  assert.equal(buttons.length, 2);
  assert.match(buttons[0].textContent, /다시 열기/);
  assert.match(buttons[1].textContent, /최신 수정본 위에/);
  await buttons[1].dispatch('click');
  assert.equal(fetched[2][0], `${BASE}api/v1/works/${WORK}`);
  assert.equal(textarea(document).value, '내 초안');  // the draft is kept
  assert.equal(field(document, 'save-status').dataset.state, 'draft');
  assert.deepEqual(JSON.parse(storage.getItem(storageKey(BASE))), { work_id: WORK, revision: 2, base_revision: 2, draft_text: '내 초안' });
  await field(document, 'work-form').dispatch('submit');
  assert.equal(JSON.parse(fetched[3][1].body).expected_revision, 2);
  assert.match(field(document, 'save-status').textContent, /수정본 3/);
});

test('an unchanged text on a saved work is not sealed again', async () => {
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1 }) });
  const { promise, fetched, document } = booted([SESSION(), jsonResponse(200, revision(1, '저장본'))], { storage });
  await promise;
  await field(document, 'work-form').dispatch('submit');
  assert.equal(fetched.length, 2);
  assert.equal(field(document, 'save-status').dataset.state, 'saved');
});

const pendingDescriptor = (operation, payload, workId = null) => ({ schema_version: 'owner-pending-command-v2', operation,
  work_id: workId, payload });

test('file-first selection creates honest empty v2 then uploads exact bytes under returned revision', async () => {
  const sourceRef = { kind: 'source', id: WORK, version: 1, sha256: 'b'.repeat(64) };
  const subject = booted([SESSION(), jsonResponse(201, { ...revision(1, ''), source_refs: [] }),
    jsonResponse(201, { ...revision(2, ''), source_refs: [sourceRef] }),
    jsonResponse(200, { source_ref: sourceRef, source: { name: '원본.txt' }, artifact: { name: '원본.txt', size: 3 } })]);
  await subject.promise;
  const picker = field(subject.document, 'materials').find(el => el.getAttribute('type') === 'file');
  assert.ok(picker, 'file selection is available without a model');
  picker.files = [new File(['abc'], '원본.txt', { type: 'text/plain' })];
  await picker.dispatch('change');
  await field(subject.document, 'work-form').dispatch('submit');
  const create = JSON.parse(subject.fetched[1][1].body);
  assert.deepEqual(create, { schema_version: 'work-create-command-v2', command_id: '00000000-0000-4000-8000-00000000c001', text: '', input_origin: 'owner_material' });
  const uploaded = subject.fetched[2][1];
  assert.deepEqual([...uploaded.body], [97, 98, 99]);
  assert.equal(JSON.parse(Buffer.from(uploaded.headers['X-DeepTwin-Source-Metadata'], 'base64url')).expected_revision, 1);
  assert.match(field(subject.document, 'materials').textContent, /원본 보관됨/);
  assert.match(field(subject.document, 'materials').textContent, /내용 읽기는 아직 지원되지 않습니다/);
  assert.equal(JSON.parse(subject.storage.getItem(storageKey(BASE))).pending_command, undefined);
});

test('refresh recovers exact lost empty create v2 and preserves newer unsaved draft', async () => {
  const payload = { schema_version: 'work-create-command-v2', command_id: WORK, text: '', input_origin: 'owner_material' };
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ draft_text: '새 문장', pending_command: pendingDescriptor('create', payload) }) });
  const subject = booted([SESSION(), jsonResponse(200, { ...revision(1, ''), source_refs: [] }),
    jsonResponse(200, { ...revision(1, ''), source_refs: [] })], { storage });
  await subject.promise;
  assert.equal(subject.fetched[1][0], `${BASE}api/v1/works/commands/${WORK}`);
  assert.equal(subject.fetched.some(([, options]) => options.method === 'POST'), false);
  assert.equal(textarea(subject.document).value, '새 문장');
  const state = JSON.parse(storage.getItem(storageKey(BASE)));
  assert.equal(state.work_id, WORK);
  assert.equal(state.pending_command, undefined);
  assert.equal(state.draft_text, '새 문장');
});

test('receipt404 retains original v2 descriptor and exact retry never rebuilds from newer draft', async () => {
  const payload = { schema_version: 'work-create-command-v2', command_id: WORK, text: '', input_origin: 'owner_material' };
  const descriptor = pendingDescriptor('create', payload);
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ draft_text: '', pending_command: descriptor }) });
  const subject = booted([SESSION(), jsonResponse(404, { code: 'not_found' }), jsonResponse(201, { ...revision(1, ''), source_refs: [] })], { storage });
  await subject.promise;
  assert.deepEqual(JSON.parse(storage.getItem(storageKey(BASE))).pending_command, descriptor);
  assert.match(field(subject.document, 'save-status').textContent, /저장 상태 확인 중/);
  await field(subject.document, 'work-form').dispatch('submit');
  assert.deepEqual(JSON.parse(subject.fetched[2][1].body), payload);
});

test('lost upload receipt on refresh preserves newer text and exact upload metadata after404', async () => {
  const payload = { schema_version: 'owner-source-upload-v1', command_id: WORK, expected_revision: 1,
    name: 'same.txt', declared_media_type: 'text/plain', size: 3,
    sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' };
  const descriptor = pendingDescriptor('upload', payload, WORK);
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, base_revision: 1,
    draft_text: 'newer draft', pending_command: descriptor }) });
  const subject = booted([SESSION(), jsonResponse(404, { code: 'not_found' }), jsonResponse(200, revision(1, '')),
    jsonResponse(404, { code: 'not_found' })], { storage });
  await subject.promise;
  assert.equal(textarea(subject.document).value, 'newer draft');
  await field(subject.document, 'work-form').dispatch('submit');
  assert.deepEqual(JSON.parse(storage.getItem(storageKey(BASE))).pending_command, descriptor);
  assert.equal(subject.fetched.filter(([, options]) => options.method === 'POST').length, 0);
  assert.match(field(subject.document, 'save-status').textContent, /같은 이름과 내용/);
});

for (const unrelated of [null,
  { name: 'other.txt', type: 'text/plain', text: 'abc' },
  { name: 'same.txt', type: 'text/plain', text: 'xyz' },
  { name: 'same.txt', type: 'application/octet-stream', text: 'abc' },
]) {
  test(`committed upload receipt consumes verified reselected original, not ${unrelated ? JSON.stringify(unrelated) : 'a new upload'}`, async () => {
    const payload = { schema_version: 'owner-source-upload-v1', command_id: WORK, expected_revision: 1,
      name: 'same.txt', declared_media_type: 'text/plain', size: 3,
      sha256: 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad' };
    const descriptor = pendingDescriptor('upload', payload, WORK);
    const sourceRef = { kind: 'source', id: WORK, version: 1, sha256: 'b'.repeat(64) };
    const otherRef = { kind: 'source', id: '00000000-0000-4000-8000-0000000000a2', version: 1, sha256: 'c'.repeat(64) };
    const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1,
      pending_command: descriptor }) });
    const subject = booted([SESSION(), jsonResponse(404, { code: 'not_found' }), jsonResponse(200, revision(1, '')),
      jsonResponse(200, { ...revision(2, ''), source_refs: [sourceRef] }),
      jsonResponse(200, { source_ref: sourceRef, artifact: { name: 'same.txt', size: 3 } }),
      ...(unrelated ? [jsonResponse(201, { ...revision(3, ''), source_refs: [sourceRef, otherRef] }),
        jsonResponse(200, { source_ref: otherRef, artifact: { name: unrelated.name, size: 3 } })] : []),
    ], { storage });
    await subject.promise;
    assert.deepEqual(JSON.parse(storage.getItem(storageKey(BASE))).pending_command, descriptor);
    const picker = field(subject.document, 'materials').find(el => el.getAttribute('type') === 'file');
    // Put the unrelated file first: matching only name/size (or consuming all queued
    // selections) must not swallow a different original when the receipt arrives.
    picker.files = [...(unrelated ? [new File([unrelated.text], unrelated.name, { type: unrelated.type })] : []),
      new File(['abc'], 'same.txt', { type: 'text/plain' })];
    await picker.dispatch('change');
    await field(subject.document, 'work-form').dispatch('submit');
    const uploads = subject.fetched.filter(([path, options]) => path.endsWith('/sources') && options.method === 'POST');
    assert.equal(uploads.length, unrelated ? 1 : 0, 'resolving the original receipt must not mint another upload for that file');
    if (unrelated) {
      const metadata = JSON.parse(Buffer.from(uploads[0][1].headers['X-DeepTwin-Source-Metadata'], 'base64url'));
      assert.equal(metadata.name, unrelated.name);
      assert.equal(metadata.declared_media_type, unrelated.type);
      assert.equal(metadata.expected_revision, 2);
      assert.equal(new TextDecoder().decode(uploads[0][1].body), unrelated.text);
    }
    const state = JSON.parse(storage.getItem(storageKey(BASE)));
    assert.equal(state.pending_command, undefined);
    assert.equal(state.revision, unrelated ? 3 : 2);
    assert.equal(field(subject.document, 'save-status').dataset.state, 'saved');
  });
}

test('revise-v2 replay retains its original expectation even after the saved revision advances', async () => {
  const payload = { schema_version: 'work-revise-command-v2', command_id: WORK, expected_revision: 1, text: 'own edit' };
  const descriptor = pendingDescriptor('revise', payload, WORK);
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, base_revision: 1,
    draft_text: 'own edit', pending_command: descriptor }) });
  const subject = booted([SESSION(), jsonResponse(404, { code: 'not_found' }), jsonResponse(200, revision(5, 'later edit')),
    jsonResponse(409, { code: 'conflict' })], { storage });
  await subject.promise;
  assert.deepEqual(JSON.parse(storage.getItem(storageKey(BASE))).pending_command, descriptor);
  await field(subject.document, 'work-form').dispatch('submit');
  assert.deepEqual(JSON.parse(subject.fetched[3][1].body), payload);
  assert.equal(textarea(subject.document).value, 'own edit');
  assert.equal(field(subject.document, 'save-status').dataset.state, 'conflict');
});

test('late upload response keeps text edited while receiving as an unsaved draft', async () => {
  let release, announced;
  const gate = new Promise(resolve => { release = resolve; });
  const receiving = new Promise(resolve => { announced = resolve; });
  const subject = booted([SESSION(), jsonResponse(201, { ...revision(1, ''), source_refs: [] }),
    { ok: true, status: 201, async json() { announced(); await gate; return { ...revision(2, ''), source_refs: [] }; } }]);
  await subject.promise;
  const picker = field(subject.document, 'materials').find(el => el.getAttribute('type') === 'file');
  picker.files = [new File(['abc'], 'original.txt', { type: 'text/plain' })];
  await picker.dispatch('change');
  const pending = field(subject.document, 'work-form').dispatch('submit');
  await receiving;
  textarea(subject.document).value = 'typed during upload';
  await textarea(subject.document).dispatch('input');
  release(); await pending;
  assert.equal(textarea(subject.document).value, 'typed during upload');
  const state = JSON.parse(subject.storage.getItem(storageKey(BASE)));
  assert.equal(state.draft_text, 'typed during upload');
  assert.equal(state.base_revision, 2);
  assert.equal(state.pending_command, undefined);
  assert.equal(field(subject.document, 'save-status').dataset.state, 'draft');
});

test('resolving an older pending receipt never calls its text the current saved revision', async () => {
  const payload = { schema_version: 'work-revise-command-v2', command_id: WORK, expected_revision: 1, text: 'own edit' };
  const storage = fakeStorage({ [storageKey(BASE)]: JSON.stringify({ work_id: WORK, revision: 1, base_revision: 1,
    draft_text: 'own edit', pending_command: pendingDescriptor('revise', payload, WORK) }) });
  const subject = booted([SESSION(), jsonResponse(404, { code: 'not_found' }), jsonResponse(200, revision(5, 'later edit')),
    jsonResponse(201, revision(2, 'own edit')), jsonResponse(200, revision(5, 'later edit'))], { storage });
  await subject.promise;
  await field(subject.document, 'work-form').dispatch('submit');
  assert.equal(field(subject.document, 'save-status').dataset.state, 'conflict');
  assert.equal(textarea(subject.document).value, 'own edit');
  const state = JSON.parse(storage.getItem(storageKey(BASE)));
  assert.equal(state.revision, 5);
  assert.equal(state.base_revision, 2);
  assert.equal(state.draft_text, 'own edit');
});
